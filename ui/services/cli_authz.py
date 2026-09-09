# ============================================================
# VERGİ AI - ROW 19C-3b SLICE 1: CLI ACTOR AUTHORIZATION REPOSITORY.
#
# `ui.services.authz.authorize_case_access()` is session-shaped by
# design (`Principal.session_id` + `AuthzRepository.get_session_authz_
# state()` joins `iam.sessions` to `iam.users`) - correct for a browser
# request, which always carries a real, previously-issued session. A
# CLI invocation of `ui.cli_mutate` has no such session: the operator
# supplies a bare `--actor-user-id`, verified fresh against `iam.users`
# on every single invocation (this is the "trusted-local-shell" model -
# proving the user row EXISTS/is ACTIVE/is ASSIGNED, never proving the
# person at the keyboard IS cryptographically that user; real OS/
# service-identity enforcement remains Row 19D scope, exactly as already
# documented for `ui/reconciliation_operator.py`'s `cli_service`
# provenance label in db/migrations/0004_mutation_reconciliation_
# provenance.sql).
#
# `authorize_case_access()` ITSELF IS NOT MODIFIED - not here, not
# anywhere in this Slice. This module instead satisfies its EXISTING,
# unchanged `AuthzRepository` Protocol with an implementation that
# never touches `iam.sessions` at all: `CliActorAuthzRepository`
# subclasses `PostgresAuthzRepository` (inheriting its real, tested
# `get_active_case_assignment`/`list_active_case_ids_for_user`/
# `is_global_admin` SQL VERBATIM - these three never reference
# `principal.session_id` in the first place, confirmed by reading
# `PostgresAuthzRepository`'s own implementation) and overrides ONLY
# `get_session_authz_state()` to read `iam.users` directly by
# `principal.user_id`, ignoring `principal.session_id` entirely.
#
# WHY THIS IS A CORRECT, NOT A WEAKENED, SUBSTITUTION FOR THE FRESHNESS
# CHECK `authorize_case_access()`'s STEP 1 PERFORMS
# -------------------------------------------------------------------
# For a real web session, `Principal.role_version_at_issue` is frozen
# at LOGIN time (potentially hours before this request) and compared
# against a FRESH read of `iam.users.authz_version` on every request -
# this is what detects "a role/assignment changed since this session
# was issued". A CLI invocation has no login moment to freeze at - so
# `build_cli_principal()` below performs that freeze itself, ONCE, at
# the very start of the CLI process (a single `SELECT authz_version,
# disabled FROM iam.users WHERE id = %s`), and the SAME resulting
# `Principal` object is then reused, UNCHANGED, for BOTH the OUTER
# (pre-lock) and INNER (under-lock, authoritative) `authorize_case_
# access()` calls the facades already make - exactly mirroring how a
# real session's `role_version_at_issue` is one fixed value reused
# across both calls. Because `ui.services.db.get_connection()` (used by
# `_default_authz_repository()`, which this module's own default-wiring
# helper mirrors) opens a plain, `autocommit=False` connection with NO
# explicit isolation-level override anywhere in this codebase (confirmed
# by grep - PostgreSQL's default is READ COMMITTED), EACH STATEMENT
# within that one connection's implicit transaction sees a FRESH
# snapshot, not a snapshot frozen at the transaction's start - so the
# inner check's own fresh `iam.users` read genuinely can observe a
# revocation that was committed WHILE this CLI process was waiting for
# the case lock between the outer and inner calls. This is not an
# assumption; it is the same property `mutation_approval_facade.py`'s
# own `_default_authz_repository()` docstring already documents and
# relies on for the web path, reused here unchanged for the CLI path.
#
# CONNECTION LIFECYCLE (dispatcher-owned, never shared with the mutation
# side): `ui.cli_mutate` opens exactly ONE plain `ui.services.db.
# get_connection()`-shaped connection for authorization purposes,
# constructs ONE `CliActorAuthzRepository` around it, uses it for BOTH
# the outer and the (facade-internal) inner `authorize_case_access()`
# call, and closes it in its OWN `finally` block once the whole CLI
# invocation is done - completely independent of whatever separate
# `ui.services.db.get_session_lock_connection()` the approval/review
# facade opens for the journal/lock/writer side (that connection's
# `autocommit=True`, session-lock-capable shape is fundamentally
# different from this one's plain, all-read, `autocommit=False` shape -
# mixing them would be incorrect, not merely untidy).
# ============================================================

from __future__ import annotations

from dataclasses import dataclass

from . import authz as _authz


class CliActorNotFoundError(Exception):
    """Raised by `read_actor_authz_snapshot()` when `--actor-user-id`
    does not name any row in `iam.users` at all. Existence-blind by
    construction with `CliActorDisabledError` below - both are surfaced
    identically by `ui.cli_mutate` (a fixed, generic denial message),
    never distinguished in the CLI's own output, matching `authorize_
    case_access()`'s own existence-blind contract for a nonexistent vs.
    a real-but-unassigned case_id."""


class CliActorDisabledError(Exception):
    """Raised by `read_actor_authz_snapshot()` when `--actor-user-id`
    names a real `iam.users` row with `disabled = TRUE`. See
    `CliActorNotFoundError`'s own docstring for the existence-blind
    pairing with this error."""


@dataclass(frozen=True)
class CliActorAuthzSnapshot:
    """The one-time, frozen read `build_cli_principal()` performs at CLI
    startup - `authz_version` becomes the synthetic `Principal.role_
    version_at_issue`, exactly mirroring what a real session's issuance
    moment would have frozen."""

    user_id: int
    authz_version: int


# A `Principal.session_id` this repository's own `get_session_authz_
# state()` override NEVER reads (see this module's own header comment) -
# not a real `iam.sessions.id` (that sequence starts at 1), and never
# sent in any SQL parameter list this module issues.
_SYNTHETIC_SESSION_ID_SENTINEL = 0


def read_actor_authz_snapshot(conn, actor_user_id: int) -> CliActorAuthzSnapshot:
    """The CLI's OWN one-time bootstrap read - NOT part of the
    `AuthzRepository` Protocol (no browser-session caller ever needs
    this; only `ui.cli_mutate`'s own startup sequence does). Fails
    closed, existence-blind between "no such user" and "disabled user"
    at the EXCEPTION-CLASS level only - `ui.cli_mutate` itself renders
    both identically, never branching its own user-facing message on
    which of the two fired."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT authz_version, disabled FROM iam.users WHERE id = %s",
            (actor_user_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise CliActorNotFoundError(f"no iam.users row for actor_user_id={actor_user_id}")
    authz_version, disabled = row
    if disabled:
        raise CliActorDisabledError(f"actor_user_id={actor_user_id} is disabled")
    return CliActorAuthzSnapshot(user_id=actor_user_id, authz_version=authz_version)


def build_cli_principal(conn, actor_user_id: int) -> _authz.Principal:
    """Reads `read_actor_authz_snapshot()` once and freezes it into a
    `Principal` - the SAME `Principal` instance MUST be reused for both
    the outer and inner `authorize_case_access()` calls a single CLI
    mutation attempt makes (see this module's own header comment on why
    that reuse, not a second fresh read, is what makes the freshness
    check meaningful here exactly as it is for a real session)."""
    snapshot = read_actor_authz_snapshot(conn, actor_user_id)
    return _authz.Principal(
        user_id=snapshot.user_id,
        session_id=_SYNTHETIC_SESSION_ID_SENTINEL,
        role_version_at_issue=snapshot.authz_version,
    )


class CliActorAuthzRepository(_authz.PostgresAuthzRepository):
    """Satisfies `ui.services.authz.AuthzRepository` for a CLI actor.
    Inherits `get_active_case_assignment()`/`list_active_case_ids_for_
    user()`/`is_global_admin()` UNCHANGED from `PostgresAuthzRepository`
    (none of the three ever reference `principal.session_id` or
    `iam.sessions` - confirmed by reading that class's own
    implementation) - overrides ONLY `get_session_authz_state()`."""

    def get_session_authz_state(self, principal: _authz.Principal):
        """Ignores `principal.session_id` entirely (see this module's
        own header comment for why `_SYNTHETIC_SESSION_ID_SENTINEL` is
        never sent to the database) - reads `iam.users` directly by
        `principal.user_id` instead of joining through `iam.sessions`.
        Returns `None` (exactly like the real session-backed
        implementation does for an unknown/revoked session) if the user
        row no longer exists - a narrow, legitimate TOCTOU between this
        module's own startup read and this later re-check, handled by
        `authorize_case_access()`'s own existing `session not found`
        fail-closed path, unchanged."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT authz_version, disabled FROM iam.users WHERE id = %s",
                (principal.user_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        authz_version, disabled = row
        return _authz.SessionRecord(
            user_id=principal.user_id, current_authz_version=authz_version, disabled=disabled,
        )
