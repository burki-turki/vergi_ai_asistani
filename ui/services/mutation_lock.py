# ============================================================
# Row 19B/19C-1 - MutationCoordinator lock acquisition.
#
# Every durable IAM admin mutation (all nine scripts/iam_admin.py
# commands) acquires the `global:iam` resource via
# pg_advisory_xact_lock, transaction-scoped, auto-released on
# commit/rollback. The resource-key -> advisory_lock_id mapping comes
# from ONE shared, authoritative table - mutation.mutation_resources
# (db/migrations/0002_mutation_resources.sql) - Row 19C-1 reuses this
# exact table rather than creating a second registry, per that
# migration's own contract.
#
# `conn` is accepted as a plain DB-API-2.0-shaped object (anything
# with .cursor() returning a context-manager cursor with .execute()/
# .fetchone()) rather than importing psycopg directly - this lets the
# fail-closed lookup logic below be exercised with an in-memory fake
# in ui/tests/test_mutation_lock_isolated.py without psycopg
# installed, while production callers pass a real psycopg connection.
#
# ROW 19C-1 ADDITION - SESSION-LEVEL LOCKS (below the IAM section)
# -------------------------------------------------------------------
# The functions above (`acquire_global_iam_lock`/`acquire_resource_lock`)
# are UNCHANGED and remain TRANSACTION-scoped (`pg_advisory_xact_lock`)
# - correct for IAM, because an IAM mutation never leaves one Postgres
# transaction (commit/rollback alone is a complete durability story).
#
# A file-write mutation (Row 19C-1's actual target) is different: its
# journal must go through separately-committed `prepared` ->
# `executing` -> `completed`/`failed` writes, with the real file
# mutation happening OUTSIDE any Postgres transaction, in between.
# `pg_advisory_xact_lock` would release at the FIRST of those commits -
# far too early. The functions below use `pg_advisory_lock`/
# `pg_advisory_unlock` instead (SESSION-scoped: tied to the
# connection, not any one transaction) so the lock survives every
# intermediate commit and the file I/O itself, and is released only by
# an explicit `release_lock_session()` call or by the connection
# itself dropping (crash/network loss - PostgreSQL's own guarantee,
# not something this module implements). `ui/services/
# mutation_coordinator.py` orchestrates these; this module still owns
# 100% of the raw lock SQL - the coordinator never issues
# `pg_advisory_lock`/`pg_advisory_xact_lock` itself.
# ============================================================

from __future__ import annotations


class UnknownMutationResourceError(Exception):
    """Raised when `resource_key` has no row in mutation.mutation_resources.
    The caller MUST NOT proceed with the mutation unlocked - this is a
    fail-closed condition, not a warning."""


def acquire_global_iam_lock(conn) -> None:
    """Acquires the `global:iam` resource lock inside the CALLER's already-
    open transaction (`conn` must not be in autocommit mode - the lock is
    transaction-scoped and would be meaningless otherwise). Call this
    FIRST, before any durable write, in every one of the nine admin
    commands that require it (see scripts/iam_admin.py)."""
    acquire_resource_lock(conn, "global:iam")


def acquire_resource_lock(conn, resource_key: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT advisory_lock_id FROM mutation.mutation_resources WHERE resource_key = %s",
            (resource_key,),
        )
        row = cur.fetchone()
        if row is None:
            raise UnknownMutationResourceError(
                f"no row in mutation.mutation_resources for resource_key={resource_key!r}; "
                "refusing to proceed unlocked"
            )
        advisory_lock_id = row[0]
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (advisory_lock_id,))


# ============================================================
# ROW 19C-1 - SESSION-LEVEL LOCK PRIMITIVES (file-write mutations).
# ============================================================

def case_resource_key(case_id: str) -> str:
    """Builds the single, shared lock resource key for ALL mutation
    families of one case (Row 19A design decision: one
    `case:<case_id>` lock serializes every artefact family for that
    case, not one lock per family). Does NOT validate `case_id` itself
    - callers MUST have already run it through
    `ui.services.paths.resolve_case_id()` first; this function only
    formats an already-trusted string, exactly like
    `acquire_global_iam_lock` only ever forwards the fixed literal
    `"global:iam"` rather than re-validating it."""
    return f"case:{case_id}"


def _get_or_create_resource_advisory_lock_id(conn, resource_key: str) -> int:
    """Race-safe get-or-create for one `mutation.mutation_resources`
    row. `INSERT ... ON CONFLICT DO NOTHING RETURNING` wins the common
    case in a single round trip; if a concurrent session's insert won
    the race instead (zero rows returned here), a plain SELECT picks
    up the row it created. Either way the returned id is ALWAYS the
    database-assigned IDENTITY value from 0002's own contract - this
    function never derives or guesses one itself. `conn` must be
    usable for an immediate, separately-visible write (see
    `ui.services.db.get_session_lock_connection`, which returns an
    autocommit connection for exactly this reason - a case resource
    row must be durable/visible to other sessions immediately, not
    left inside a long-running transaction)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO mutation.mutation_resources (resource_key) VALUES (%s) "
            "ON CONFLICT (resource_key) DO NOTHING "
            "RETURNING advisory_lock_id",
            (resource_key,),
        )
        row = cur.fetchone()
    if row is not None:
        return row[0]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT advisory_lock_id FROM mutation.mutation_resources WHERE resource_key = %s",
            (resource_key,),
        )
        row = cur.fetchone()
    if row is None:
        # Only reachable if a concurrent DELETE raced both branches -
        # fail closed rather than proceed unlocked, same principle as
        # every other lookup miss in this module.
        raise UnknownMutationResourceError(
            f"resource_key={resource_key!r} could not be created or found; refusing to proceed unlocked"
        )
    return row[0]


def acquire_case_lock_session(conn, case_id: str) -> int:
    """Session-level lock (`pg_advisory_lock`, NOT
    `pg_advisory_xact_lock`) on a case's `case:<case_id>` resource,
    get-or-creating that resource row race-safely first. Returns the
    `advisory_lock_id` - the caller MUST pass it to
    `release_lock_session()` in a `finally` block once done, and must
    not use `conn` for anything else concurrently. The lock survives
    every commit made on `conn` afterwards and is released only by
    `release_lock_session()` or by `conn` itself dropping (crash/
    network loss - PostgreSQL's own session-lock guarantee)."""
    advisory_lock_id = _get_or_create_resource_advisory_lock_id(conn, case_resource_key(case_id))
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (advisory_lock_id,))
    return advisory_lock_id


def acquire_global_lock_session(conn, resource_key: str) -> int:
    """Session-level lock on a GLOBAL resource key that must ALREADY
    exist (global resources are seeded by migration - e.g.
    `global:rag_index`, db/migrations/0003_mutation_journal.sql -
    never created on the fly, unlike case resources). Fails closed via
    `UnknownMutationResourceError` if the row is missing, exactly like
    `acquire_resource_lock` above."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT advisory_lock_id FROM mutation.mutation_resources WHERE resource_key = %s",
            (resource_key,),
        )
        row = cur.fetchone()
    if row is None:
        raise UnknownMutationResourceError(
            f"no row in mutation.mutation_resources for resource_key={resource_key!r}; "
            "refusing to proceed unlocked"
        )
    advisory_lock_id = row[0]
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_lock(%s)", (advisory_lock_id,))
    return advisory_lock_id


def release_lock_session(conn, advisory_lock_id: int) -> bool:
    """Releases a session-level lock taken by
    `acquire_case_lock_session`/`acquire_global_lock_session`, via
    `pg_advisory_unlock`. Returns that call's own boolean result -
    True means this session actually held and just released it; False
    means it was NOT held by this session (an anomaly - the caller
    MUST log/surface this, never silently ignore it). This function
    itself never raises on a False result and never skips the
    unlock call, so a caller's cleanup can always proceed to close the
    connection afterwards regardless (no lock/connection leak either
    way)."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (advisory_lock_id,))
        (released,) = cur.fetchone()
    return bool(released)
