# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION — GLOBAL RESOURCE AUTHORIZATION.
#
# `ui.services.authz.authorize_case_access()` is CASE-scoped by design
# (a case_id, an `iam.case_assignments` row, a role's read/mutate
# capability). The `rag_index` global resource has no case_id and no
# case_assignments row at all - its authorization instead comes from
# `iam.global_resource_grants` (db/migrations/0005), a per-user,
# per-(resource, capability) grant this module checks. This module is
# a SIBLING of `ui.services.authz`, not a modification of it - that
# file is not touched anywhere in this Foundation slice.
#
# ACTOR MODEL: this Foundation slice ships ONLY a CLI surface for
# `rag_index` (no web route - see `ui/cli_mutate.py`'s new `rag-bundle`
# subcommand). The `_authz.Principal` this module's functions accept is
# therefore always one built by the EXISTING, unmodified
# `ui.services.cli_authz.build_cli_principal()` (the same
# trusted-local-shell model already used by the `approval`/`review`/
# `promotion`/`generation` subcommands) - this module does not define
# its own Principal type or its own actor-freshness bootstrap; it
# reuses `_authz.Principal`/`_authz.SessionRecord` verbatim so a single
# frozen Principal can be passed through both this module's checks AND
# (for other subcommands, in the same process) `authorize_case_access`
# without any type friction.
#
# NO ADMIN BYPASS (closed user decision #1): this module's own
# `authorize_global_resource_access()` never special-cases
# `is_global_admin` - it only ever checks whether an ACTIVE grant row
# exists for the exact (user, resource, capability) triple. An admin
# who happens to ALSO hold a real grant row would pass this check like
# any other grantee; an admin with no such row is denied like any other
# ungranted user. The refusal to let an admin ACQUIRE a grant in the
# first place is enforced separately, at grant-TIME, by
# `scripts/global_resource_grants.py` (this module is never involved in
# that refusal - it only ever reads, never writes, the grants table).
#
# EXISTENCE-BLIND, REVOKED-IS-ABSENT: `has_active_global_grant()`'s own
# SQL filters `revoked_at IS NULL` - a revoked grant is indistinguishable
# from a grant that was never made, from this function's caller's point
# of view (mirrors `authorize_case_access`'s own existence-blind
# denial contract for a nonexistent vs. an unassigned case_id).
#
# OUTER + INNER VERIFICATION (closed contract, mirrors every existing
# facade): this module does not itself enforce "call me twice" - that
# is `ui.services.rag_bundle_mutation_facade.py`'s responsibility,
# exactly as `mutation_approval_facade.py`/`generation_mutation_
# facade.py` call `authorize_case_access()` once pre-lock (outer, fail-
# fast) and once again inside `precondition_callback` under the global
# lock (inner, authoritative) using a FRESH repository bound to the
# lock-holding connection. This module's own functions are stateless
# and safe to call any number of times with any connection.
# ============================================================

from __future__ import annotations

from typing import Literal, Protocol

from ui.services import authz as _authz

Capability = Literal["inspect", "build", "activate"]

RAG_INDEX_RESOURCE = "rag_index"

_KNOWN_CAPABILITIES: frozenset[str] = frozenset({"inspect", "build", "activate"})


class GlobalResourceAccessDeniedError(Exception):
    """Raised for every denial path (actor not found/disabled/stale
    authz_version, or no active grant for the exact requested
    capability). A single exception type with a `reason_code` - callers
    must not branch on message text; `ui.cli_mutate` renders one fixed,
    generic denial message regardless of which reason fired, matching
    `CaseAccessDeniedError`'s own existence-blind contract."""

    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


class GlobalResourceAuthzRepository(Protocol):
    def get_session_authz_state(self, principal: _authz.Principal) -> _authz.SessionRecord | None:
        """Returns None if the actor is unknown/revoked/expired - same
        contract as `ui.services.authz.AuthzRepository.get_session_
        authz_state`."""
        ...

    def has_active_global_grant(self, user_id: int, resource: str, capability: Capability) -> bool:
        """True iff an active (revoked_at IS NULL) `iam.global_resource_
        grants` row exists for exactly this (user_id, resource,
        capability) triple. A revoked grant returns False, identically
        to a grant that was never made."""
        ...


def authorize_global_resource_access(
    principal: _authz.Principal,
    capability: Capability,
    *,
    repository: GlobalResourceAuthzRepository,
    resource: str = RAG_INDEX_RESOURCE,
) -> None:
    """Raises `GlobalResourceAccessDeniedError` on any failure; returns
    None (no filesystem path to resolve - there is no case-scoped
    concept here) on success. Two-step order, mirroring `authorize_
    case_access`'s own step 1 verbatim, then a capability-grant check in
    place of that function's case_assignments/role steps:

      1) actor freshness: not-found / disabled / stale authz_version.
      2) exact-match active grant for (user_id, resource, capability).
    """
    if capability not in _KNOWN_CAPABILITIES:
        raise GlobalResourceAccessDeniedError("capability_denied", f"unknown capability {capability!r}")

    session_state = repository.get_session_authz_state(principal)
    if session_state is None:
        raise GlobalResourceAccessDeniedError("assignment_revoked", "actor not found/expired")
    if session_state.disabled:
        raise GlobalResourceAccessDeniedError("disabled_user", "user account is disabled")
    if session_state.current_authz_version != principal.role_version_at_issue:
        raise GlobalResourceAccessDeniedError(
            "assignment_revoked",
            "authz_version mismatch - a role/grant change since this actor snapshot was taken",
        )

    if not repository.has_active_global_grant(session_state.user_id, resource, capability):
        raise GlobalResourceAccessDeniedError(
            "capability_denied",
            f"no active {capability!r} grant on {resource!r} for user_id={session_state.user_id}",
        )


class PostgresGlobalResourceAuthzRepository:
    """Real repository backing production `authorize_global_resource_
    access()` calls. Takes an already-open connection - does not open
    its own. Independently implements `get_session_authz_state()`
    (rather than importing `ui.services.cli_authz.CliActorAuthzRepository`,
    whose Protocol also carries case-scoped methods this module has no
    use for) reading `iam.users` directly by `principal.user_id` -
    identical query shape to `CliActorAuthzRepository`'s own override,
    intentionally duplicated rather than inherited to keep this module
    self-contained and free of any case-scoped surface."""

    def __init__(self, conn):
        self._conn = conn

    def get_session_authz_state(self, principal: _authz.Principal) -> _authz.SessionRecord | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT authz_version, disabled FROM iam.users WHERE id = %s",
                (principal.user_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        authz_version, disabled = row
        return _authz.SessionRecord(user_id=principal.user_id, current_authz_version=authz_version, disabled=disabled)

    def has_active_global_grant(self, user_id: int, resource: str, capability: Capability) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM iam.global_resource_grants
                   WHERE user_id = %s AND resource = %s AND capability = %s AND revoked_at IS NULL""",
                (user_id, resource, capability),
            )
            return cur.fetchone() is not None


class InMemoryGlobalResourceAuthzRepository:
    """Fake repository for tests only."""

    def __init__(self) -> None:
        self.sessions: dict[int, _authz.SessionRecord] = {}
        self.grants: set[tuple[int, str, str]] = set()

    def get_session_authz_state(self, principal: _authz.Principal) -> _authz.SessionRecord | None:
        return self.sessions.get(principal.user_id)

    def has_active_global_grant(self, user_id: int, resource: str, capability: Capability) -> bool:
        return (user_id, resource, capability) in self.grants
