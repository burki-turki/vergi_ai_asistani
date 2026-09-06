# ============================================================
# Row 19B - security events: single owner, closed/typed schema.
#
# One function per event_type (matching iam.security_events'
# CHECK-constrained enum exactly - see db/migrations/0001_iam_schema.sql).
# No JSONB, no free-form payload. Every function takes the CALLER's
# already-open transaction (`conn`) so the event commits atomically
# with the IAM mutation/session change it documents - this module
# never opens its own transaction or connection.
#
# `conn` is accepted as a plain DB-API-2.0-shaped object, matching
# ui.services.mutation_lock's convention - lets this be exercised with
# an in-memory fake recorder without psycopg installed.
# ============================================================

from __future__ import annotations

from typing import Optional


def _insert(conn, event_type: str, **fields) -> None:
    columns = ["event_type", *fields.keys()]
    placeholders = ["%s"] * len(columns)
    values = [event_type, *fields.values()]
    sql = f"INSERT INTO iam.security_events ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
    with conn.cursor() as cur:
        cur.execute(sql, values)


def record_login_success(conn, *, user_id: int, session_id: int, mfa_satisfied: bool,
                          mfa_assurance_level: str, mfa_assurance_policy_version: str) -> None:
    _insert(
        conn, "login_success", user_id=user_id, session_id=session_id,
        mfa_satisfied=mfa_satisfied, mfa_assurance_level=mfa_assurance_level,
        mfa_assurance_policy_version=mfa_assurance_policy_version,
    )


def record_login_denied_unknown_identity(conn) -> None:
    # Deliberately carries NO identifying detail beyond the event itself -
    # an unknown (issuer, subject) must not be logged in a way that lets a
    # log reader distinguish "no such identity" from "identity exists but
    # is disabled" (existence-blind, matching the callback's own response).
    _insert(conn, "login_denied_unknown_identity", reason_code="unknown_identity")


def record_login_denied_disabled_user(conn, *, user_id: int) -> None:
    _insert(conn, "login_denied_disabled_user", user_id=user_id, reason_code="disabled_user")


def record_login_denied_mfa_absent(conn, *, user_id: Optional[int], reason_code: str) -> None:
    _insert(conn, "login_denied_mfa_absent", user_id=user_id, reason_code=reason_code)


def record_logout(conn, *, user_id: int, session_id: int) -> None:
    _insert(conn, "logout", user_id=user_id, session_id=session_id, reason_code="user_action")


def record_session_revoked(conn, *, user_id: int, session_id: int, actor_user_id: int) -> None:
    """Covers BOTH self-service and administrator-triggered revocation.
    Disambiguation is `actor_user_id == user_id` (self) vs `!=` (admin) -
    no separate event type is needed for the admin-triggered case."""
    reason = "user_action" if actor_user_id == user_id else "admin_action"
    _insert(conn, "session_revoked", user_id=user_id, session_id=session_id,
            actor_user_id=actor_user_id, reason_code=reason)


def record_session_expired_idle(conn, *, user_id: int, session_id: int) -> None:
    _insert(conn, "session_expired_idle", user_id=user_id, session_id=session_id, reason_code="idle_timeout")


def record_session_expired_absolute(conn, *, user_id: int, session_id: int) -> None:
    _insert(conn, "session_expired_absolute", user_id=user_id, session_id=session_id, reason_code="absolute_timeout")


def record_authz_denied(conn, *, user_id: int, case_id: Optional[str], requested_capability: str,
                         reason_code: str) -> None:
    _insert(conn, "authz_denied", user_id=user_id, case_id=case_id,
            requested_capability=requested_capability, reason_code=reason_code, granted=False)


def record_csrf_rejected(conn, *, user_id: Optional[int], session_id: Optional[int]) -> None:
    _insert(conn, "csrf_rejected", user_id=user_id, session_id=session_id, reason_code="csrf_mismatch")


def record_admin_role_granted(conn, *, actor_user_id: int, user_id: int) -> None:
    _insert(conn, "admin_role_granted", actor_user_id=actor_user_id, user_id=user_id,
            role="admin", granted=True, reason_code="admin_action")


def record_admin_role_revoked(conn, *, actor_user_id: int, user_id: int) -> None:
    _insert(conn, "admin_role_revoked", actor_user_id=actor_user_id, user_id=user_id,
            role="admin", granted=False, reason_code="admin_action")


def record_case_assignment_granted(conn, *, actor_user_id: int, user_id: int, case_id: str, role: str) -> None:
    _insert(conn, "case_assignment_granted", actor_user_id=actor_user_id, user_id=user_id,
            case_id=case_id, role=role, granted=True, reason_code="admin_action")


def record_case_assignment_revoked(conn, *, actor_user_id: int, user_id: int, case_id: str, role: str) -> None:
    _insert(conn, "case_assignment_revoked", actor_user_id=actor_user_id, user_id=user_id,
            case_id=case_id, role=role, granted=False, reason_code="admin_action")


def record_user_provisioned(conn, *, actor_user_id: int, user_id: int) -> None:
    _insert(conn, "user_provisioned", actor_user_id=actor_user_id, user_id=user_id, reason_code="admin_action")


def record_user_disabled(conn, *, actor_user_id: int, user_id: int) -> None:
    _insert(conn, "user_disabled", actor_user_id=actor_user_id, user_id=user_id, reason_code="admin_action")


def record_user_enabled(conn, *, actor_user_id: int, user_id: int) -> None:
    _insert(conn, "user_enabled", actor_user_id=actor_user_id, user_id=user_id, reason_code="admin_action")


def record_bootstrap_first_admin(conn, *, user_id: int) -> None:
    _insert(conn, "bootstrap_first_admin", user_id=user_id, actor_user_id=user_id, reason_code="admin_action")


# The complete set of writer functions, keyed by the event_type string
# they emit - used only by the test file to prove 1:1 coverage against
# the migration's CHECK-constrained enum. Not used by production code.
ALL_EVENT_WRITERS = {
    "login_success": record_login_success,
    "login_denied_unknown_identity": record_login_denied_unknown_identity,
    "login_denied_disabled_user": record_login_denied_disabled_user,
    "login_denied_mfa_absent": record_login_denied_mfa_absent,
    "logout": record_logout,
    "session_revoked": record_session_revoked,
    "session_expired_idle": record_session_expired_idle,
    "session_expired_absolute": record_session_expired_absolute,
    "authz_denied": record_authz_denied,
    "csrf_rejected": record_csrf_rejected,
    "admin_role_granted": record_admin_role_granted,
    "admin_role_revoked": record_admin_role_revoked,
    "case_assignment_granted": record_case_assignment_granted,
    "case_assignment_revoked": record_case_assignment_revoked,
    "user_provisioned": record_user_provisioned,
    "user_disabled": record_user_disabled,
    "user_enabled": record_user_enabled,
    "bootstrap_first_admin": record_bootstrap_first_admin,
}
