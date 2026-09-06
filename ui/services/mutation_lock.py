# ============================================================
# Row 19B - MutationCoordinator lock acquisition.
#
# Every durable IAM admin mutation (all nine scripts/iam_admin.py
# commands) acquires the `global:iam` resource via
# pg_advisory_xact_lock, transaction-scoped, auto-released on
# commit/rollback. The resource-key -> advisory_lock_id mapping comes
# from ONE shared, authoritative table - mutation.mutation_resources
# (db/migrations/0002_mutation_resources.sql) - which Row 19C must
# also reuse rather than create a second registry. This module
# implements NONE of Row 19C's file-write journal / reconciliation
# state machine (mutation_journal) - that is out of scope here, by
# design: a mutation confined to one Postgres transaction has no use
# for it.
#
# `conn` is accepted as a plain DB-API-2.0-shaped object (anything
# with .cursor() returning a context-manager cursor with .execute()/
# .fetchone()) rather than importing psycopg directly - this lets the
# fail-closed lookup logic below be exercised with an in-memory fake
# in ui/tests/test_mutation_lock_isolated.py without psycopg
# installed, while production callers pass a real psycopg connection
# obtained from ui.services.db.transaction().
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
