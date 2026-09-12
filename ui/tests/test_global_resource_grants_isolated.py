# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION - isolated tests for
# scripts/global_resource_grants.py's decision logic (grant/revoke/
# list) AND ui/services/global_authz.py's authorization decision logic.
# In-memory fake Postgres-shaped connection, mirroring
# ui/tests/test_iam_admin_isolated.py's own FakeDB/FakeCursor pattern
# (independent copy - not imported). No psycopg needed. The CLI
# argparse wiring (main()) and real-DB round trips are NOT EXECUTED
# here (see test_global_resource_grants_integration coverage inside
# test_rag_bundle_mutation_integration_postgres.py for the real-DB
# proof).
#
# Run: python -m ui.tests.test_global_resource_grants_isolated
# ============================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import global_resource_grants as grg  # noqa: E402
from ui.services import authz as _authz  # noqa: E402
from ui.services import global_authz as ga  # noqa: E402

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")


# ----------------------------------------------------------------
# Minimal in-memory "Postgres" fake.
# ----------------------------------------------------------------

class FakeDB:
    def __init__(self):
        self.users = {}       # id -> {disabled}
        self.roles = set()    # {(user_id, 'admin')}
        self.grants = {}      # id -> {user_id, resource, capability, granted_by, revoked_at, revoked_by}
        self.events = []
        self._next_grant_id = 1

    def alloc_grant_id(self):
        i = self._next_grant_id
        self._next_grant_id += 1
        return i


class FakeCursor:
    def __init__(self, db: FakeDB):
        self.db = db
        self._result = None
        self._all = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        db = self.db
        s = " ".join(sql.split())

        if s.startswith("SELECT disabled FROM iam.users WHERE id"):
            (uid,) = params
            self._result = (db.users[uid]["disabled"],) if uid in db.users else None
        elif s.startswith("SELECT 1 FROM iam.user_roles WHERE user_id"):
            (uid,) = params
            self._result = (1,) if (uid, "admin") in db.roles else None
        elif s.startswith("INSERT INTO iam.global_resource_grants"):
            user_id, resource, capability, granted_by = params
            active = [
                g for g in db.grants.values()
                if g["user_id"] == user_id and g["resource"] == resource
                and g["capability"] == capability and g["revoked_at"] is None
            ]
            if active:
                self._result = None
            else:
                gid = db.alloc_grant_id()
                db.grants[gid] = {
                    "id": gid, "user_id": user_id, "resource": resource, "capability": capability,
                    "granted_by": granted_by, "revoked_at": None, "revoked_by": None,
                }
                self._result = (gid,)
        elif s.startswith("UPDATE iam.global_resource_grants"):
            actor_user_id, user_id, resource, capability = params
            match = None
            for g in db.grants.values():
                if (
                    g["user_id"] == user_id and g["resource"] == resource
                    and g["capability"] == capability and g["revoked_at"] is None
                ):
                    match = g
                    break
            if match is None:
                self._result = None
            else:
                match["revoked_at"] = "now"
                match["revoked_by"] = actor_user_id
                self._result = (match["id"],)
        elif s.startswith("INSERT INTO iam.global_resource_grant_events"):
            grant_id, event_type, actor_user_id, subject_user_id, resource, capability = params
            db.events.append({
                "grant_id": grant_id, "event_type": event_type, "actor_user_id": actor_user_id,
                "subject_user_id": subject_user_id, "resource": resource, "capability": capability,
            })
            self._result = None
        elif s.startswith("SELECT id, user_id, resource, capability, granted_by_user_id, revoked_at"):
            rows = []
            for g in db.grants.values():
                rows.append((g["id"], g["user_id"], g["resource"], g["capability"], g["granted_by"], g["revoked_at"]))
            rows.sort(key=lambda r: r[0])
            self._all = rows
            self._result = rows[0] if rows else None
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._all if self._all is not None else []


class FakeConn:
    def __init__(self, db: FakeDB):
        self.db = db

    def cursor(self):
        return FakeCursor(self.db)


def make_db(*, users=None, admins=None):
    db = FakeDB()
    for uid, disabled in (users or {}).items():
        db.users[uid] = {"disabled": disabled}
    for uid in (admins or []):
        db.roles.add((uid, "admin"))
    return db


# ================================================================
# grant_capability / revoke_capability / list_grants pure decision logic
# ================================================================

def test_grant_basic():
    db = make_db(users={1: False, 2: False}, admins=[1])
    conn = FakeConn(db)
    result = grg.grant_capability(conn, subject_user_id=2, resource="rag_index", capability="build", actor_user_id=1)
    check("grant_basic: created=True", result.created is True)
    check("grant_basic: grant_id assigned", result.grant_id is not None)
    check("grant_basic: one grant_created event", len(db.events) == 1 and db.events[0]["event_type"] == "grant_created")


def test_grant_admin_rejected():
    db = make_db(users={1: False, 9: False}, admins=[1, 9])
    conn = FakeConn(db)
    expect_raises(
        grg.GrantCommandError,
        lambda: grg.grant_capability(conn, subject_user_id=9, resource="rag_index", capability="build", actor_user_id=1),
        "grant_admin_rejected",
    )
    check("grant_admin_rejected: zero grants created", len(db.grants) == 0)
    check("grant_admin_rejected: zero events written", len(db.events) == 0)


def test_grant_idempotent_replay():
    db = make_db(users={1: False, 2: False}, admins=[1])
    conn = FakeConn(db)
    grg.grant_capability(conn, subject_user_id=2, resource="rag_index", capability="inspect", actor_user_id=1)
    result = grg.grant_capability(conn, subject_user_id=2, resource="rag_index", capability="inspect", actor_user_id=1)
    check("grant_idempotent_replay: created=False", result.created is False)
    check("grant_idempotent_replay: no second event", len(db.events) == 1)
    check("grant_idempotent_replay: exactly one grant row", len(db.grants) == 1)


def test_revoke_then_regrant_opens_new_history_row():
    db = make_db(users={1: False, 2: False}, admins=[1])
    conn = FakeConn(db)
    first = grg.grant_capability(conn, subject_user_id=2, resource="rag_index", capability="activate", actor_user_id=1)
    grg.revoke_capability(conn, subject_user_id=2, resource="rag_index", capability="activate", actor_user_id=1)
    second = grg.grant_capability(conn, subject_user_id=2, resource="rag_index", capability="activate", actor_user_id=1)
    check("revoke_then_regrant: second grant created", second.created is True)
    check("revoke_then_regrant: new grant_id, history preserved", second.grant_id != first.grant_id)
    check("revoke_then_regrant: 2 grant rows total (both preserved)", len(db.grants) == 2)
    check(
        "revoke_then_regrant: 3 events (created, revoked, created)",
        [e["event_type"] for e in db.events] == ["grant_created", "grant_revoked", "grant_created"],
    )


def test_revoke_only_active_grant():
    db = make_db(users={1: False, 2: False}, admins=[1])
    conn = FakeConn(db)
    expect_raises(
        grg.GrantCommandError,
        lambda: grg.revoke_capability(conn, subject_user_id=2, resource="rag_index", capability="build", actor_user_id=1),
        "revoke_only_active_grant: no active grant -> refused",
    )
    check("revoke_only_active_grant: zero events written", len(db.events) == 0)


def test_list_grants_active_and_revoked():
    db = make_db(users={1: False, 2: False}, admins=[1])
    conn = FakeConn(db)
    grg.grant_capability(conn, subject_user_id=2, resource="rag_index", capability="inspect", actor_user_id=1)
    grg.grant_capability(conn, subject_user_id=2, resource="rag_index", capability="build", actor_user_id=1)
    grg.revoke_capability(conn, subject_user_id=2, resource="rag_index", capability="build", actor_user_id=1)
    records = grg.list_grants(conn, subject_user_id=2)
    active = [r for r in records if r.active]
    revoked = [r for r in records if not r.active]
    check("list_grants: 2 total records", len(records) == 2)
    check("list_grants: 1 active", len(active) == 1 and active[0].capability == "inspect")
    check("list_grants: 1 revoked", len(revoked) == 1 and revoked[0].capability == "build")


def test_invalid_resource_capability_rejected():
    db = make_db(users={1: False, 2: False}, admins=[1])
    conn = FakeConn(db)
    expect_raises(
        grg.GrantCommandError,
        lambda: grg.grant_capability(conn, subject_user_id=2, resource="not_rag_index", capability="build", actor_user_id=1),
        "invalid_resource_rejected",
    )
    expect_raises(
        grg.GrantCommandError,
        lambda: grg.grant_capability(conn, subject_user_id=2, resource="rag_index", capability="delete", actor_user_id=1),
        "invalid_capability_rejected",
    )


# ================================================================
# CLI-level actor verification (_verify_actor_is_active_admin)
# ================================================================

def test_actor_verification_not_found_disabled_not_admin():
    db = make_db(users={1: False, 2: True, 3: False}, admins=[1])
    conn = FakeConn(db)
    expect_raises(
        grg.GrantCommandError, lambda: grg._verify_actor_is_active_admin(conn, 999), "actor_not_found",
    )
    expect_raises(
        grg.GrantCommandError, lambda: grg._verify_actor_is_active_admin(conn, 2), "actor_disabled",
    )
    expect_raises(
        grg.GrantCommandError, lambda: grg._verify_actor_is_active_admin(conn, 3), "actor_not_admin",
    )
    # No exception for a real, active admin.
    grg._verify_actor_is_active_admin(conn, 1)
    check("actor_verification: active admin passes", True)


# ================================================================
# ui.services.global_authz - authorize_global_resource_access()
# ================================================================

def make_principal_and_repo(user_id, *, disabled=False, authz_version=1, session_authz_version=1, grants=()):
    principal = _authz.Principal(user_id=user_id, session_id=0, role_version_at_issue=session_authz_version)
    repo = ga.InMemoryGlobalResourceAuthzRepository()
    repo.sessions[user_id] = _authz.SessionRecord(user_id=user_id, current_authz_version=authz_version, disabled=disabled)
    for resource, capability in grants:
        repo.grants.add((user_id, resource, capability))
    return principal, repo


def test_global_authz_granted():
    principal, repo = make_principal_and_repo(2, grants=[("rag_index", "build")])
    ga.authorize_global_resource_access(principal, "build", repository=repo)
    check("global_authz_granted: no exception", True)


def test_global_authz_denied_no_grant():
    principal, repo = make_principal_and_repo(2, grants=[("rag_index", "inspect")])
    expect_raises(
        ga.GlobalResourceAccessDeniedError,
        lambda: ga.authorize_global_resource_access(principal, "build", repository=repo),
        "global_authz_denied_no_grant",
    )


def test_global_authz_denied_unknown_actor():
    principal = _authz.Principal(user_id=999, session_id=0, role_version_at_issue=1)
    repo = ga.InMemoryGlobalResourceAuthzRepository()
    expect_raises(
        ga.GlobalResourceAccessDeniedError,
        lambda: ga.authorize_global_resource_access(principal, "build", repository=repo),
        "global_authz_denied_unknown_actor",
    )


def test_global_authz_denied_disabled():
    principal, repo = make_principal_and_repo(2, disabled=True, grants=[("rag_index", "build")])
    expect_raises(
        ga.GlobalResourceAccessDeniedError,
        lambda: ga.authorize_global_resource_access(principal, "build", repository=repo),
        "global_authz_denied_disabled",
    )


def test_global_authz_denied_stale_authz_version():
    principal, repo = make_principal_and_repo(2, authz_version=2, session_authz_version=1, grants=[("rag_index", "build")])
    expect_raises(
        ga.GlobalResourceAccessDeniedError,
        lambda: ga.authorize_global_resource_access(principal, "build", repository=repo),
        "global_authz_denied_stale_authz_version",
    )


def test_global_authz_exact_capability_only():
    principal, repo = make_principal_and_repo(2, grants=[("rag_index", "inspect"), ("rag_index", "activate")])
    ga.authorize_global_resource_access(principal, "inspect", repository=repo)
    ga.authorize_global_resource_access(principal, "activate", repository=repo)
    expect_raises(
        ga.GlobalResourceAccessDeniedError,
        lambda: ga.authorize_global_resource_access(principal, "build", repository=repo),
        "global_authz_exact_capability_only: build not granted",
    )


def test_global_authz_revoked_grant_treated_absent():
    # InMemoryGlobalResourceAuthzRepository has no revoke concept - a
    # capability simply present or absent in `.grants`; simulate revoke
    # by removing it, proving "absent" (never granted) and "revoked"
    # are handled identically by this pure decision function.
    principal, repo = make_principal_and_repo(2, grants=[("rag_index", "build")])
    repo.grants.discard((2, "rag_index", "build"))
    expect_raises(
        ga.GlobalResourceAccessDeniedError,
        lambda: ga.authorize_global_resource_access(principal, "build", repository=repo),
        "global_authz_revoked_grant_treated_absent",
    )


def test_global_authz_unknown_capability_rejected():
    principal, repo = make_principal_and_repo(2, grants=[("rag_index", "build")])
    expect_raises(
        ga.GlobalResourceAccessDeniedError,
        lambda: ga.authorize_global_resource_access(principal, "delete", repository=repo),
        "global_authz_unknown_capability_rejected",
    )


def run_self_test():
    test_grant_basic()
    test_grant_admin_rejected()
    test_grant_idempotent_replay()
    test_revoke_then_regrant_opens_new_history_row()
    test_revoke_only_active_grant()
    test_list_grants_active_and_revoked()
    test_invalid_resource_capability_rejected()
    test_actor_verification_not_found_disabled_not_admin()
    test_global_authz_granted()
    test_global_authz_denied_no_grant()
    test_global_authz_denied_unknown_actor()
    test_global_authz_denied_disabled()
    test_global_authz_denied_stale_authz_version()
    test_global_authz_exact_capability_only()
    test_global_authz_revoked_grant_treated_absent()
    test_global_authz_unknown_capability_rejected()

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
