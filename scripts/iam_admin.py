#!/usr/bin/env python3
# ============================================================
# Row 19B - local-CLI-only IAM administration.
#
# No web admin UI exists (v1 decision - avoids any admin-facing web
# attack surface). Every durable command below acquires the
# `global:iam` MutationCoordinator lock (ui.services.mutation_lock)
# FIRST, inside one transaction (ui.services.db.transaction), performs
# its IAM mutation, writes its one typed security event
# (ui.services.security_events), and commits - or rolls back both
# together on any failure. Sensitive identity values are read from
# interactive stdin by default, not mandatory CLI args (avoids shell-
# history exposure); (issuer, subject) is identity-linking metadata,
# not a password, but is still not casually logged - console output
# is fixed/generic by default.
#
# Nine durable commands, ALL taking the `global:iam` lock:
#   bootstrap-first-admin, provision-user, grant-role, revoke-role,
#   assign-case, revoke-assignment, revoke-session, disable-user,
#   enable-user
#
# Each command's DECISION LOGIC (idempotency, conflict detection,
# atomic sequencing) is implemented as a small pure-ish function
# taking a duck-typed `conn` - this is what
# ui/tests/test_iam_admin_isolated.py exercises against an in-memory
# fake, without psycopg. The `main()` CLI wiring below uses the real
# ui.services.db.transaction() (lazy psycopg) and is NOT EXECUTED in
# this sandbox.
# ============================================================

from __future__ import annotations

import argparse
import getpass
import sys
from dataclasses import dataclass
from typing import Optional

from ui.services import mutation_lock, security_events as se


class AdminCommandError(Exception):
    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


# ---------------------------------------------------------------
# provision-user - atomic create-or-idempotent-replay-or-fail-closed.
# ---------------------------------------------------------------

@dataclass(frozen=True)
class ProvisionUserResult:
    user_id: int
    created: bool  # False on an idempotent replay


def provision_user(conn, *, issuer: str, subject: str, display_name: str, actor_user_id: int) -> ProvisionUserResult:
    """Must be called with `conn` already holding the `global:iam` lock
    (see cmd_provision_user below) and inside the caller's transaction.
    Semantics (exact, per the approved v1 contract):
      - (issuer, subject) not linked -> create user + identity, write
        ONE user_provisioned event, return created=True.
      - (issuer, subject) linked, same display_name -> no new rows, NO
        additional security event (a replay does not re-narrate the
        original provisioning), return created=False.
      - (issuer, subject) linked, DIFFERENT display_name -> fail closed,
        AdminCommandError, no row touched, no event written.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT u.id, u.display_name FROM iam.external_identities ei
               JOIN iam.users u ON u.id = ei.user_id
               WHERE ei.issuer = %s AND ei.subject = %s""",
            (issuer, subject),
        )
        existing = cur.fetchone()

    if existing is not None:
        existing_user_id, existing_display_name = existing
        if existing_display_name == display_name:
            return ProvisionUserResult(user_id=existing_user_id, created=False)
        raise AdminCommandError(
            "conflict",
            f"(issuer, subject) already linked to user {existing_user_id} with a different display_name",
        )

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO iam.users(display_name) VALUES (%s) RETURNING id", (display_name,),
        )
        new_user_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO iam.external_identities(user_id, issuer, subject) VALUES (%s, %s, %s)",
            (new_user_id, issuer, subject),
        )
    se.record_user_provisioned(conn, actor_user_id=actor_user_id, user_id=new_user_id)
    return ProvisionUserResult(user_id=new_user_id, created=True)


# ---------------------------------------------------------------
# disable-user / enable-user
# ---------------------------------------------------------------

def disable_user(conn, *, user_id: int, actor_user_id: int) -> None:
    """Atomically: set disabled=TRUE, bump authz_version, revoke every
    active session for user_id, write ONE user_disabled event covering
    the whole operation (individual sessions do not each get their own
    session_revoked row)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE iam.users SET disabled = TRUE, authz_version = authz_version + 1 WHERE id = %s",
            (user_id,),
        )
        cur.execute(
            "UPDATE iam.sessions SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL",
            (user_id,),
        )
    se.record_user_disabled(conn, actor_user_id=actor_user_id, user_id=user_id)


def enable_user(conn, *, user_id: int, actor_user_id: int) -> None:
    """Clears disabled ONLY. Never recreates sessions, never touches
    authz_version, roles, or case_assignments."""
    with conn.cursor() as cur:
        cur.execute("UPDATE iam.users SET disabled = FALSE WHERE id = %s", (user_id,))
    se.record_user_enabled(conn, actor_user_id=actor_user_id, user_id=user_id)


# ---------------------------------------------------------------
# grant-role / revoke-role (global admin grant only)
# ---------------------------------------------------------------

def grant_admin_role(conn, *, user_id: int, actor_user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO iam.user_roles(user_id, role) VALUES (%s, 'admin') "
            "ON CONFLICT (user_id, role) DO NOTHING",
            (user_id,),
        )
        cur.execute("UPDATE iam.users SET authz_version = authz_version + 1 WHERE id = %s", (user_id,))
    se.record_admin_role_granted(conn, actor_user_id=actor_user_id, user_id=user_id)


def revoke_admin_role(conn, *, user_id: int, actor_user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM iam.user_roles WHERE user_id = %s AND role = 'admin'", (user_id,))
        cur.execute("UPDATE iam.users SET authz_version = authz_version + 1 WHERE id = %s", (user_id,))
    se.record_admin_role_revoked(conn, actor_user_id=actor_user_id, user_id=user_id)


# ---------------------------------------------------------------
# assign-case / revoke-assignment
# ---------------------------------------------------------------

def assign_case(conn, *, user_id: int, case_id: str, role: str, actor_user_id: int) -> None:
    if role not in ("lawyer", "analyst"):
        raise AdminCommandError("invalid_role", role)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO iam.case_assignments(user_id, case_id, role) VALUES (%s, %s, %s)",
            (user_id, case_id, role),
        )
    se.record_case_assignment_granted(conn, actor_user_id=actor_user_id, user_id=user_id, case_id=case_id, role=role)


def revoke_assignment(conn, *, user_id: int, case_id: str, actor_user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE iam.case_assignments SET revoked_at = now() "
            "WHERE user_id = %s AND case_id = %s AND revoked_at IS NULL RETURNING role",
            (user_id, case_id),
        )
        row = cur.fetchone()
    role = row[0] if row else None
    se.record_case_assignment_revoked(conn, actor_user_id=actor_user_id, user_id=user_id, case_id=case_id, role=role)


# ---------------------------------------------------------------
# revoke-session (administrator-triggered)
# ---------------------------------------------------------------

def admin_revoke_session(conn, *, session_id: int, actor_user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE iam.sessions SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL RETURNING user_id",
            (session_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise AdminCommandError("not_found", f"session {session_id} not found or already revoked")
    user_id = row[0]
    se.record_session_revoked(conn, user_id=user_id, session_id=session_id, actor_user_id=actor_user_id)


# ---------------------------------------------------------------
# bootstrap-first-admin
# ---------------------------------------------------------------

def bootstrap_first_admin(conn, *, issuer: str, subject: str, display_name: str) -> int:
    """DB-enforced singleton via iam.bootstrap_state - only one concurrent
    invocation can succeed (the INSERT below fails for every other
    concurrent transaction under the same global:iam lock serialization)."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO iam.bootstrap_state(id) VALUES (TRUE)")  # raises if already bootstrapped
        cur.execute("INSERT INTO iam.users(display_name) VALUES (%s) RETURNING id", (display_name,))
        user_id = cur.fetchone()[0]
        cur.execute("INSERT INTO iam.external_identities(user_id, issuer, subject) VALUES (%s, %s, %s)", (user_id, issuer, subject))
        cur.execute("INSERT INTO iam.user_roles(user_id, role) VALUES (%s, 'admin')", (user_id,))
    se.record_bootstrap_first_admin(conn, user_id=user_id)
    return user_id


# ---------------------------------------------------------------
# CLI wiring - real DB, NOT EXECUTED in this sandbox.
# ---------------------------------------------------------------

def _run_locked(command_fn, **kwargs):
    from ui.services import db  # lazy import (psycopg)

    with db.transaction() as conn:
        mutation_lock.acquire_global_iam_lock(conn)
        return command_fn(conn, **kwargs)


def _verify_actor_is_active_admin(conn, actor_user_id: int) -> None:
    """Row 19B targeted remediation (finding 1). Called INSIDE the same
    `global:iam`-locked transaction as the mutation it guards, BEFORE any
    mutating statement runs. Raising here leaves the transaction with
    nothing to commit; the caller (`_run_locked_as_admin`) lets the
    exception propagate out of the `with db.transaction()` block, which
    per ui.services.db.transaction()'s own contract rolls back and
    re-raises - so a failed verification guarantees zero mutation and
    zero security event, not merely "the command decided not to write
    one". No sentinel actor id (0 or otherwise) and no FK bypass exist
    here: every accepted actor_user_id is a real row this query found.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT disabled FROM iam.users WHERE id = %s", (actor_user_id,))
        row = cur.fetchone()
    if row is None:
        raise AdminCommandError("actor_not_found", f"actor_user_id {actor_user_id} does not exist")
    (disabled,) = row
    if disabled:
        raise AdminCommandError("actor_disabled", f"actor_user_id {actor_user_id} is disabled")

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM iam.user_roles WHERE user_id = %s AND role = 'admin'", (actor_user_id,))
        has_admin_role = cur.fetchone() is not None
    if not has_admin_role:
        raise AdminCommandError("actor_not_admin", f"actor_user_id {actor_user_id} does not hold the admin role")


def _run_locked_as_admin(command_fn, *, actor_user_id: int, **kwargs):
    """Same locked-transaction wrapper as `_run_locked`, plus a mandatory
    real-actor verification step run BEFORE `command_fn`, inside the same
    lock and the same transaction. `bootstrap-first-admin` deliberately
    does NOT go through this wrapper - by definition no actor exists yet
    the first time it runs, and it keeps its own DB-enforced singleton
    semantics (iam.bootstrap_state) unchanged."""
    from ui.services import db  # lazy import (psycopg)

    with db.transaction() as conn:
        mutation_lock.acquire_global_iam_lock(conn)
        _verify_actor_is_active_admin(conn, actor_user_id)
        return command_fn(conn, actor_user_id=actor_user_id, **kwargs)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="iam_admin.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("provision-user")
    p.add_argument("--display-name", required=True)
    p.add_argument("--actor-user-id", required=True, type=int)

    p = sub.add_parser("grant-role")
    p.add_argument("--user-id", required=True, type=int)
    p.add_argument("--actor-user-id", required=True, type=int)

    p = sub.add_parser("revoke-role")
    p.add_argument("--user-id", required=True, type=int)
    p.add_argument("--actor-user-id", required=True, type=int)

    p = sub.add_parser("assign-case")
    p.add_argument("--user-id", required=True, type=int)
    p.add_argument("--case-id", required=True)
    p.add_argument("--role", required=True, choices=["lawyer", "analyst"])
    p.add_argument("--actor-user-id", required=True, type=int)

    p = sub.add_parser("revoke-assignment")
    p.add_argument("--user-id", required=True, type=int)
    p.add_argument("--case-id", required=True)
    p.add_argument("--actor-user-id", required=True, type=int)

    p = sub.add_parser("revoke-session")
    p.add_argument("--session-id", required=True, type=int)
    p.add_argument("--actor-user-id", required=True, type=int)

    p = sub.add_parser("disable-user")
    p.add_argument("--user-id", required=True, type=int)
    p.add_argument("--actor-user-id", required=True, type=int)

    p = sub.add_parser("enable-user")
    p.add_argument("--user-id", required=True, type=int)
    p.add_argument("--actor-user-id", required=True, type=int)

    sub.add_parser("bootstrap-first-admin")

    args = parser.parse_args(argv)

    if args.command == "provision-user":
        issuer = input("issuer: ").strip()
        subject = getpass.getpass("subject (not echoed - identity-linking metadata): ").strip()
        result = _run_locked_as_admin(
            provision_user, issuer=issuer, subject=subject, display_name=args.display_name,
            actor_user_id=args.actor_user_id,
        )
        print("OK" if result.created else "OK (already provisioned - idempotent)")
    elif args.command == "bootstrap-first-admin":
        issuer = input("issuer: ").strip()
        subject = getpass.getpass("subject (not echoed): ").strip()
        display_name = input("display name: ").strip()
        _run_locked(bootstrap_first_admin, issuer=issuer, subject=subject, display_name=display_name)
        print("OK")
    elif args.command == "grant-role":
        _run_locked_as_admin(grant_admin_role, user_id=args.user_id, actor_user_id=args.actor_user_id)
        print("OK")
    elif args.command == "revoke-role":
        _run_locked_as_admin(revoke_admin_role, user_id=args.user_id, actor_user_id=args.actor_user_id)
        print("OK")
    elif args.command == "assign-case":
        _run_locked_as_admin(
            assign_case, user_id=args.user_id, case_id=args.case_id, role=args.role,
            actor_user_id=args.actor_user_id,
        )
        print("OK")
    elif args.command == "revoke-assignment":
        _run_locked_as_admin(
            revoke_assignment, user_id=args.user_id, case_id=args.case_id, actor_user_id=args.actor_user_id,
        )
        print("OK")
    elif args.command == "revoke-session":
        _run_locked_as_admin(admin_revoke_session, session_id=args.session_id, actor_user_id=args.actor_user_id)
        print("OK")
    elif args.command == "disable-user":
        _run_locked_as_admin(disable_user, user_id=args.user_id, actor_user_id=args.actor_user_id)
        print("OK")
    elif args.command == "enable-user":
        _run_locked_as_admin(enable_user, user_id=args.user_id, actor_user_id=args.actor_user_id)
        print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
