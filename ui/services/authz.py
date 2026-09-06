# ============================================================
# Row 19B - separated authorization layer.
#
# `authorize_case_access` is called independently at BOTH the route
# layer (main.py, before rendering/dispatching) and the service layer
# (approval_registry.case_scoped_approve, review_registry.
# apply_transition, drafting_request.save_lawyer_input_from_form) -
# route-only checks were judged insufficient. Both call sites use the
# exact same function, so there is one authorization decision, not two
# that could drift apart.
#
# Five-step order, in this exact sequence:
#   1) authenticate session with a FRESH authz_version check (a
#      revoked role/assignment takes effect on the very next request)
#   2) syntactically validate case_id (cheap, before any DB work)
#   3) check for an active case_assignments row for this (user, case)
#   4) check the granted role's capability against the requested one
#   5) only THEN call the unchanged paths.resolve_case_id() for
#      filesystem safety - authorization is decided before
#      filesystem resolution is even attempted, not after.
#
# `repository` is an injectable Protocol so the pure decision logic
# is testable in-process with an in-memory fake (no psycopg needed);
# production wires a real Postgres-backed repository from
# ui.services.db / ui.services.session_store.
# ============================================================

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

# `common` is a leaf module (only hashlib/pathlib, no import back to this
# module or to `paths`) - importing it at module level here is safe and
# creates no cycle. `UnknownCaseError` is the ONLY exception step 5 below
# is permitted to catch and remap - not a broad `except Exception`.
from ui.services.common import UnknownCaseError

Capability = Literal["read", "mutate"]
Role = Literal["admin", "lawyer", "analyst"]

_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# admin is deliberately absent: admin has ZERO case-content capability
# on its own (global identity/role/assignment management only) -
# granting a role does not imply case access.
_ROLE_CAPABILITIES: dict[Role, set[Capability]] = {
    "lawyer": {"read", "mutate"},
    "analyst": {"read"},
}


class CaseAccessDeniedError(Exception):
    """Raised for every denial path (unauthenticated, revoked authz_version,
    malformed case_id, no assignment, insufficient capability). Deliberately
    a single exception type with a `reason_code` - callers must not branch
    on message text, and the HTTP layer renders one generic denial page
    regardless of which of these fired (existence-blind: an unassigned
    case and a nonexistent case_id produce the identical response)."""

    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


@dataclass(frozen=True)
class Principal:
    user_id: int
    session_id: int
    role_version_at_issue: int


@dataclass(frozen=True)
class SessionRecord:
    user_id: int
    current_authz_version: int
    disabled: bool


@dataclass(frozen=True)
class CaseAssignmentRecord:
    role: Role


class AuthzRepository(Protocol):
    def get_session_authz_state(self, principal: Principal) -> SessionRecord | None:
        """Returns None if the session is unknown/revoked/expired."""
        ...

    def get_active_case_assignment(self, user_id: int, case_id: str) -> CaseAssignmentRecord | None:
        """Returns None if no active (non-revoked) assignment exists for
        this (user_id, case_id) - existence-blind: the same None is
        returned whether the case_id doesn't exist or simply isn't
        assigned to this user."""
        ...

    def list_active_case_ids_for_user(self, user_id: int) -> list[str]:
        """Returns the case_ids of every active (non-revoked) case_assignments
        row for this user - raw, not yet filtered by filesystem existence
        (see list_accessible_case_ids, which does that filtering)."""
        ...

    def is_global_admin(self, user_id: int) -> bool:
        """True iff this user currently holds the global 'admin' role."""
        ...


def validate_case_id_syntax(case_id: str) -> None:
    if not _CASE_ID_PATTERN.match(case_id):
        raise CaseAccessDeniedError("assignment_revoked", "case_id fails syntax validation")
        # reason_code is deliberately the same generic denial class as a
        # real missing assignment - a malformed case_id must not be
        # distinguishable from "not assigned to you" in the response.


def authorize_case_access(
    principal: Principal,
    requested_case_id: str,
    capability: Capability,
    *,
    repository: AuthzRepository,
    resolve_case_id=None,
) -> str:
    """Returns the filesystem-safe resolved case path on success (from the
    UNCHANGED paths.resolve_case_id - no new parameter was added to it).
    Raises CaseAccessDeniedError on any failure, always with the same
    externally-visible shape regardless of WHICH step failed."""

    # Step 1: fresh authz_version check.
    session_state = repository.get_session_authz_state(principal)
    if session_state is None:
        raise CaseAccessDeniedError("assignment_revoked", "session not found/expired")
    if session_state.disabled:
        raise CaseAccessDeniedError("disabled_user", "user account is disabled")
    if session_state.current_authz_version != principal.role_version_at_issue:
        raise CaseAccessDeniedError(
            "assignment_revoked",
            "authz_version mismatch - a role/assignment change since this session was issued",
        )

    # Step 2: syntactic case_id validation, before any further work.
    validate_case_id_syntax(requested_case_id)

    # Step 3: active case assignment.
    assignment = repository.get_active_case_assignment(session_state.user_id, requested_case_id)
    if assignment is None:
        raise CaseAccessDeniedError("assignment_revoked", "no active assignment for this case")

    # Step 4: capability check against the granted role.
    if capability not in _ROLE_CAPABILITIES.get(assignment.role, set()):
        raise CaseAccessDeniedError("capability_denied", f"{assignment.role} lacks {capability}")

    # Step 5: only now, filesystem-safety resolution (unchanged function).
    # `paths.resolve_case_id` raises UnknownCaseError for a case_id that
    # does not match any real case directory - including one a stale or
    # permissive assignment record already let through steps 1-4 (e.g. a
    # case_assignments row surviving after the case directory was removed
    # or renamed). That is a real, expected outcome of this authorization
    # decision, not an unexpected fault - it MUST be converted to the same
    # CaseAccessDeniedError family used for "not assigned to you", so a
    # nonexistent case_id and an unassigned-but-real case_id are IDENTICAL
    # from outside this function (existence-blind, same as
    # validate_case_id_syntax above). Only this one specific, expected
    # domain exception is caught - never a broad `except Exception`.
    if resolve_case_id is None:
        from ui.services.paths import resolve_case_id as resolve_case_id  # lazy, avoids a hard import cycle
    try:
        return resolve_case_id(requested_case_id)
    except UnknownCaseError as exc:
        raise CaseAccessDeniedError(
            "assignment_revoked",
            f"case_id does not resolve to a real case: {exc}",
        ) from exc


def list_accessible_case_ids(
    principal: Principal,
    *,
    repository: AuthzRepository,
    resolve_case_id=None,
) -> list[str]:
    """Row 19B targeted remediation (finding 2). The single, authz-layer
    source of truth for `GET /`'s case listing - NOT a template-only
    filter. Contract (exact):
      - unauthenticated / revoked / stale-authz_version / disabled
        session -> empty list (never raises here; the route layer's own
        `require_principal` is what turns a bad session into a redirect
        before this function is ever reached for an unauthenticated
        caller - this function stays defensive and fails closed to []
        if it is ever called with a session in one of those states).
      - global admin -> ALWAYS empty list, unconditionally, even if the
        admin ALSO happens to hold an explicit lawyer/analyst
        case_assignments row. This mirrors _ROLE_CAPABILITIES's existing
        design principle (admin is deliberately absent as a role key -
        admin has ZERO case-content capability on its own) and reads the
        contract's two bullets ("lawyer/analyst ... sees only assigned
        cases" / "admin sees no case ids or content") as parallel,
        unconditional statements rather than one overriding the other
        only in the no-assignment case. This is a conservative reading,
        flagged explicitly in the remediation report: it does NOT change
        `authorize_case_access`'s own per-case decision, so a direct
        request to a case an admin is separately, explicitly assigned to
        would still be evaluated (and could still succeed) there - only
        this listing is affected.
      - lawyer/analyst -> active case_assignments rows only (revoked
        rows are excluded by the same WHERE ... revoked_at IS NULL
        clause `get_active_case_assignment` already uses), each then run
        through `paths.resolve_case_id` and SILENTLY DROPPED (not
        raised) if it does not resolve to a real, existing case
        directory - a stale assignment pointing at a removed/renamed
        case must not appear in the list and must not error the whole
        page. The existing path-traversal/allowlist behavior inside
        resolve_case_id is entirely unchanged; this function only adds a
        try/except around calling it.
    """
    session_state = repository.get_session_authz_state(principal)
    if session_state is None or session_state.disabled:
        return []
    if session_state.current_authz_version != principal.role_version_at_issue:
        return []
    if repository.is_global_admin(session_state.user_id):
        return []

    if resolve_case_id is None:
        from ui.services.paths import resolve_case_id as resolve_case_id  # lazy, avoids a hard import cycle

    resolved_case_ids: list[str] = []
    for case_id in repository.list_active_case_ids_for_user(session_state.user_id):
        try:
            resolved_case_ids.append(resolve_case_id(case_id))
        except UnknownCaseError:
            continue  # stale/nonexistent assigned case - silently omitted, not an error
    return sorted(set(resolved_case_ids))


class PostgresAuthzRepository:
    """Real repository backing production authorize_case_access() calls.
    Takes an already-open connection/transaction (from
    ui.services.db.transaction()) - it does not open its own. No
    psycopg import happens here beyond ordinary DB-API cursor usage
    already established by the connection the caller passed in."""

    def __init__(self, conn):
        self._conn = conn

    def get_session_authz_state(self, principal: Principal) -> SessionRecord | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT s.user_id, u.authz_version, u.disabled
                   FROM iam.sessions s JOIN iam.users u ON u.id = s.user_id
                   WHERE s.id = %s AND s.revoked_at IS NULL""",
                (principal.session_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        user_id, authz_version, disabled = row
        return SessionRecord(user_id=user_id, current_authz_version=authz_version, disabled=disabled)

    def get_active_case_assignment(self, user_id: int, case_id: str) -> CaseAssignmentRecord | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """SELECT role FROM iam.case_assignments
                   WHERE user_id = %s AND case_id = %s AND revoked_at IS NULL""",
                (user_id, case_id),
            )
            row = cur.fetchone()
        return CaseAssignmentRecord(role=row[0]) if row else None

    def list_active_case_ids_for_user(self, user_id: int) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT case_id FROM iam.case_assignments WHERE user_id = %s AND revoked_at IS NULL",
                (user_id,),
            )
            return [row[0] for row in cur.fetchall()]

    def is_global_admin(self, user_id: int) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM iam.user_roles WHERE user_id = %s AND role = 'admin'", (user_id,))
            return cur.fetchone() is not None


class InMemoryAuthzRepository:
    """Fake repository for tests only."""

    def __init__(self) -> None:
        self.sessions: dict[int, SessionRecord] = {}
        self.assignments: dict[tuple[int, str], CaseAssignmentRecord] = {}
        self.admins: set[int] = set()

    def get_session_authz_state(self, principal: Principal) -> SessionRecord | None:
        return self.sessions.get(principal.session_id)

    def get_active_case_assignment(self, user_id: int, case_id: str) -> CaseAssignmentRecord | None:
        return self.assignments.get((user_id, case_id))

    def list_active_case_ids_for_user(self, user_id: int) -> list[str]:
        return [case_id for (uid, case_id) in self.assignments if uid == user_id]

    def is_global_admin(self, user_id: int) -> bool:
        return user_id in self.admins
