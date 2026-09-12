#!/usr/bin/env python3
# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION - GLOBAL RESOURCE GRANT
# ADMINISTRATION (grant / revoke / list `iam.global_resource_grants`).
#
# Mirrors scripts/iam_admin.py's own shape exactly (that file is READ-
# ONLY in this Foundation slice - nothing here imports it; this
# module's own `_verify_actor_is_active_admin`/`_run_locked_as_admin`
# are a DELIBERATE, independent duplication of iam_admin.py's own two
# functions of the same name and behavior, not a shared import - a bug
# in one script's copy must never silently couple with the other's).
#
# Every durable command below acquires the SAME `global:iam`
# MutationCoordinator resource (ui.services.mutation_lock.
# acquire_global_iam_lock, pg_advisory_xact_lock, transaction-scoped)
# FIRST, inside one ui.services.db.transaction(), verifies the calling
# actor is a real, active, admin-role iam.users row, performs its one
# grants-table mutation, writes its own typed event into iam.
# global_resource_grant_events (db/migrations/0005) in the SAME
# transaction, and commits - or rolls back both together on any
# failure. iam.security_events (0001) is NEVER written by this module -
# that table's event_type is a closed enum reserved for the existing
# case/session/auth event set (explicit user decision); a global-
# resource grant/revoke is a DIFFERENT kind of event with its own
# dedicated, independent table.
#
# CLOSED USER DECISION #1 (verbatim, binding): "Admin has NO automatic
# inspect/build/activate capability on rag_index. The CLI must
# structurally REFUSE granting rag_index capability to an active admin
# account." `grant_capability()` below enforces this as a hard,
# unconditional business-rule check - not a DB CHECK constraint (a
# CHECK cannot cross-reference iam.user_roles) - performed INSIDE the
# same global:iam-locked transaction, before the INSERT. There is no
# flag/override/bypass of any kind for this refusal. In the pilot
# phase, ONE designated non-admin operator MAY hold all three
# capabilities (inspect+build+activate) simultaneously - this module
# places no structural limit on how many capabilities one (non-admin)
# user may hold; separating build/activate across different people is
# a recommended, NOT mandatory, pre-production backlog item.
#
# IDEMPOTENT GRANT, HISTORY-PRESERVING RE-GRANT: granting a capability
# that is ALREADY actively held by that user is a no-op (mirrors
# iam_admin.grant_admin_role's own ON CONFLICT ... DO NOTHING
# idempotency and provision_user's "a replay does not re-narrate the
# original provisioning" no-new-event principle) - no second grant row,
# no second grant_created event. Granting after a PRIOR grant of the
# same shape was revoked always succeeds and opens a brand-new history
# row (the surrogate BIGSERIAL id never collides with the revoked row -
# see db/migrations/0005's own partial-unique-index comment) with its
# own grant_created event - the revoked row's history is preserved
# forever, never overwritten or deleted.
#
# REVOKE ONLY AN ACTIVE GRANT: revoking a (user, resource, capability)
# that has no currently-active grant row fails closed with
# GrantCommandError("not_found", ...) - mirrors iam_admin.
# admin_revoke_session's own not-found handling. No partial/silent
# no-op revoke exists.
# ============================================================

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Optional

from ui.services import mutation_lock

_KNOWN_RESOURCES = ("rag_index",)
_KNOWN_CAPABILITIES = ("inspect", "build", "activate")


class GrantCommandError(Exception):
    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


@dataclass(frozen=True)
class GrantResult:
    grant_id: Optional[int]
    created: bool  # False on an idempotent replay (already actively granted)


@dataclass(frozen=True)
class RevokeResult:
    grant_id: int


@dataclass(frozen=True)
class GrantRecord:
    grant_id: int
    user_id: int
    resource: str
    capability: str
    granted_by_user_id: int
    active: bool


def _validate_resource_capability(resource: str, capability: str) -> None:
    if resource not in _KNOWN_RESOURCES:
        raise GrantCommandError("invalid_resource", resource)
    if capability not in _KNOWN_CAPABILITIES:
        raise GrantCommandError("invalid_capability", capability)


def _record_grant_event(
    conn, *, grant_id: int, event_type: str, actor_user_id: int, subject_user_id: int,
    resource: str, capability: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO iam.global_resource_grant_events
               (grant_id, event_type, actor_user_id, subject_user_id, resource, capability)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (grant_id, event_type, actor_user_id, subject_user_id, resource, capability),
        )


def grant_capability(
    conn, *, subject_user_id: int, resource: str, capability: str, actor_user_id: int,
) -> GrantResult:
    """Must be called with `conn` already holding the `global:iam` lock
    (see cmd_grant below) and inside the caller's transaction, with the
    caller's actor already verified as a real, active admin. Semantics
    (exact, per the approved contract):
      - subject already holds an ACTIVE grant of this exact shape ->
        no new row, NO additional event, return created=False.
      - subject holds no active grant of this shape (including: never
        granted, or a prior grant of this shape was revoked) -> insert
        a NEW row (new surrogate id), write ONE grant_created event,
        return created=True.
      - subject currently holds the 'admin' role -> fail closed,
        GrantCommandError, no row touched, no event written (closed
        user decision #1).
    """
    _validate_resource_capability(resource, capability)

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM iam.user_roles WHERE user_id = %s AND role = 'admin'", (subject_user_id,))
        subject_is_admin = cur.fetchone() is not None
    if subject_is_admin:
        raise GrantCommandError(
            "admin_grantee_rejected",
            f"user_id={subject_user_id} currently holds the admin role - "
            "admin accounts may never be granted a global resource capability",
        )

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO iam.global_resource_grants
               (user_id, resource, capability, granted_by_user_id)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (user_id, resource, capability) WHERE revoked_at IS NULL
               DO NOTHING
               RETURNING id""",
            (subject_user_id, resource, capability, actor_user_id),
        )
        row = cur.fetchone()

    if row is None:
        return GrantResult(grant_id=None, created=False)

    grant_id = row[0]
    _record_grant_event(
        conn, grant_id=grant_id, event_type="grant_created", actor_user_id=actor_user_id,
        subject_user_id=subject_user_id, resource=resource, capability=capability,
    )
    return GrantResult(grant_id=grant_id, created=True)


def revoke_capability(
    conn, *, subject_user_id: int, resource: str, capability: str, actor_user_id: int,
) -> RevokeResult:
    """Revokes the CURRENTLY ACTIVE grant row (if any) for this exact
    (user, resource, capability) shape. Fails closed with
    GrantCommandError("not_found", ...) if no active grant exists -
    there is no silent/partial revoke."""
    _validate_resource_capability(resource, capability)

    with conn.cursor() as cur:
        cur.execute(
            """UPDATE iam.global_resource_grants
               SET revoked_at = now(), revoked_by_user_id = %s
               WHERE user_id = %s AND resource = %s AND capability = %s AND revoked_at IS NULL
               RETURNING id""",
            (actor_user_id, subject_user_id, resource, capability),
        )
        row = cur.fetchone()
    if row is None:
        raise GrantCommandError(
            "not_found",
            f"no active grant of resource={resource!r} capability={capability!r} "
            f"for user_id={subject_user_id}",
        )
    grant_id = row[0]
    _record_grant_event(
        conn, grant_id=grant_id, event_type="grant_revoked", actor_user_id=actor_user_id,
        subject_user_id=subject_user_id, resource=resource, capability=capability,
    )
    return RevokeResult(grant_id=grant_id)


def list_grants(conn, *, resource: Optional[str] = None, subject_user_id: Optional[int] = None) -> list[GrantRecord]:
    """Read-only - no lock required, no transaction-boundary requirement
    of its own (the caller may pass any open connection/cursor-capable
    object, locked or not)."""
    clauses = []
    params: list = []
    if resource is not None:
        clauses.append("resource = %s")
        params.append(resource)
    if subject_user_id is not None:
        clauses.append("user_id = %s")
        params.append(subject_user_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT id, user_id, resource, capability, granted_by_user_id, revoked_at
                FROM iam.global_resource_grants
                {where}
                ORDER BY id""",
            tuple(params),
        )
        rows = cur.fetchall()
    return [
        GrantRecord(
            grant_id=row[0], user_id=row[1], resource=row[2], capability=row[3],
            granted_by_user_id=row[4], active=row[5] is None,
        )
        for row in rows
    ]


# ---------------------------------------------------------------
# CLI wiring - real DB, mirrors scripts/iam_admin.py's own
# `_run_locked_as_admin` shape (independent duplication - see module
# docstring).
# ---------------------------------------------------------------

def _verify_actor_is_active_admin(conn, actor_user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT disabled FROM iam.users WHERE id = %s", (actor_user_id,))
        row = cur.fetchone()
    if row is None:
        raise GrantCommandError("actor_not_found", f"actor_user_id {actor_user_id} does not exist")
    (disabled,) = row
    if disabled:
        raise GrantCommandError("actor_disabled", f"actor_user_id {actor_user_id} is disabled")

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM iam.user_roles WHERE user_id = %s AND role = 'admin'", (actor_user_id,))
        has_admin_role = cur.fetchone() is not None
    if not has_admin_role:
        raise GrantCommandError("actor_not_admin", f"actor_user_id {actor_user_id} does not hold the admin role")


def _run_locked_as_admin(command_fn, *, actor_user_id: int, **kwargs):
    from ui.services import db  # lazy import (psycopg)

    with db.transaction() as conn:
        mutation_lock.acquire_global_iam_lock(conn)
        _verify_actor_is_active_admin(conn, actor_user_id)
        return command_fn(conn, actor_user_id=actor_user_id, **kwargs)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="global_resource_grants.py")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("grant")
    p.add_argument("--subject-user-id", required=True, type=int)
    p.add_argument("--resource", required=True, choices=_KNOWN_RESOURCES)
    p.add_argument("--capability", required=True, choices=_KNOWN_CAPABILITIES)
    p.add_argument("--actor-user-id", required=True, type=int)

    p = sub.add_parser("revoke")
    p.add_argument("--subject-user-id", required=True, type=int)
    p.add_argument("--resource", required=True, choices=_KNOWN_RESOURCES)
    p.add_argument("--capability", required=True, choices=_KNOWN_CAPABILITIES)
    p.add_argument("--actor-user-id", required=True, type=int)

    p = sub.add_parser("list")
    p.add_argument("--resource", required=False, choices=_KNOWN_RESOURCES, default=None)
    p.add_argument("--subject-user-id", required=False, type=int, default=None)

    args = parser.parse_args(argv)

    if args.command == "grant":
        result = _run_locked_as_admin(
            grant_capability, subject_user_id=args.subject_user_id, resource=args.resource,
            capability=args.capability, actor_user_id=args.actor_user_id,
        )
        print("OK" if result.created else "OK (already actively granted - idempotent)")
    elif args.command == "revoke":
        _run_locked_as_admin(
            revoke_capability, subject_user_id=args.subject_user_id, resource=args.resource,
            capability=args.capability, actor_user_id=args.actor_user_id,
        )
        print("OK")
    elif args.command == "list":
        from ui.services import db  # lazy import (psycopg)

        with db.transaction() as conn:
            records = list_grants(conn, resource=args.resource, subject_user_id=args.subject_user_id)
        for record in records:
            state = "active" if record.active else "revoked"
            print(
                f"grant_id={record.grant_id} user_id={record.user_id} resource={record.resource} "
                f"capability={record.capability} granted_by={record.granted_by_user_id} state={state}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
