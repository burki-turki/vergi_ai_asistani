# ============================================================
# Row 19B - isolated tests for scripts/iam_admin.py's decision logic.
#
# Exercises provision_user / disable_user / enable_user / grant_admin_role
# / revoke_admin_role / assign_case / revoke_assignment / admin_revoke_session
# / bootstrap_first_admin against an in-memory fake Postgres-shaped
# connection (a minimal SQL interpreter for exactly the statements these
# functions issue) - no psycopg needed. The CLI argparse wiring
# (main()) and real-DB round trips are NOT EXECUTED here.
#
# Run: python -m ui.tests.test_iam_admin_isolated
# ============================================================

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import iam_admin as ia   # noqa: E402
from ui.services import security_events as se  # noqa: E402

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
# A minimal in-memory "Postgres" fake - just enough SQL pattern
# matching to exercise iam_admin.py's decision logic faithfully,
# including uniqueness enforcement equivalent to the real schema.
# ----------------------------------------------------------------

class FakeDB:
    def __init__(self):
        self.users = {}          # id -> {display_name, disabled, authz_version}
        self.identities = {}     # (issuer, subject) -> user_id
        self.roles = set()       # {(user_id, 'admin')}
        self.assignments = {}    # id -> {user_id, case_id, role, revoked}
        self.sessions = {}       # id -> {user_id, revoked}
        self.bootstrap_done = False
        self.events = []
        self._next_id = 1

    def _alloc(self):
        i = self._next_id
        self._next_id += 1
        return i


class FakeCursor:
    def __init__(self, db: FakeDB):
        self.db = db
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        db = self.db
        s = " ".join(sql.split())

        if s.startswith("SELECT u.id, u.display_name FROM iam.external_identities"):
            issuer, subject = params
            uid = db.identities.get((issuer, subject))
            self._result = (uid, db.users[uid]["display_name"]) if uid is not None else None

        elif s.startswith("INSERT INTO iam.users(display_name)"):
            (display_name,) = params
            uid = db._alloc()
            db.users[uid] = {"display_name": display_name, "disabled": False, "authz_version": 1}
            self._result = (uid,)

        elif s.startswith("INSERT INTO iam.external_identities(user_id, issuer, subject)"):
            user_id, issuer, subject = params
            if (issuer, subject) in db.identities:
                raise RuntimeError("UNIQUE VIOLATION (issuer, subject)")
            db.identities[(issuer, subject)] = user_id
            self._result = None

        elif s.startswith("UPDATE iam.users SET disabled = TRUE"):
            (user_id,) = params
            db.users[user_id]["disabled"] = True
            db.users[user_id]["authz_version"] += 1
            self._result = None

        elif s.startswith("UPDATE iam.sessions SET revoked_at = now() WHERE user_id"):
            (user_id,) = params
            for sess in db.sessions.values():
                if sess["user_id"] == user_id and not sess["revoked"]:
                    sess["revoked"] = True
            self._result = None

        elif s.startswith("UPDATE iam.users SET disabled = FALSE"):
            (user_id,) = params
            db.users[user_id]["disabled"] = False
            self._result = None

        elif "INSERT INTO iam.user_roles" in s and "ON CONFLICT" in s:
            (user_id,) = params
            db.roles.add((user_id, "admin"))
            self._result = None

        elif s.startswith("UPDATE iam.users SET authz_version = authz_version + 1 WHERE id"):
            (user_id,) = params
            db.users[user_id]["authz_version"] += 1
            self._result = None

        elif s.startswith("DELETE FROM iam.user_roles"):
            (user_id,) = params
            db.roles.discard((user_id, "admin"))
            self._result = None

        elif s.startswith("INSERT INTO iam.case_assignments(user_id, case_id, role)"):
            user_id, case_id, role = params
            for a in db.assignments.values():
                if a["user_id"] == user_id and a["case_id"] == case_id and not a["revoked"]:
                    raise RuntimeError("UNIQUE VIOLATION active case_assignment")
            aid = db._alloc()
            db.assignments[aid] = {"user_id": user_id, "case_id": case_id, "role": role, "revoked": False}
            self._result = None

        elif s.startswith("UPDATE iam.case_assignments SET revoked_at = now()"):
            user_id, case_id = params
            found = None
            for a in db.assignments.values():
                if a["user_id"] == user_id and a["case_id"] == case_id and not a["revoked"]:
                    a["revoked"] = True
                    found = a
                    break
            self._result = (found["role"],) if found else None

        elif s.startswith("UPDATE iam.sessions SET revoked_at = now() WHERE id"):
            (session_id,) = params
            sess = db.sessions.get(session_id)
            if sess is None or sess["revoked"]:
                self._result = None
            else:
                sess["revoked"] = True
                self._result = (sess["user_id"],)

        elif s.startswith("INSERT INTO iam.security_events"):
            db.events.append(params[0])  # event_type is always the first bound value
            self._result = None

        elif s.startswith("INSERT INTO iam.bootstrap_state"):
            if db.bootstrap_done:
                raise RuntimeError("bootstrap_state singleton violation")
            db.bootstrap_done = True
            self._result = None

        elif s.startswith("INSERT INTO iam.user_roles(user_id, role) VALUES (%s, 'admin')") or "'admin'" in s and "VALUES" in s and "ON CONFLICT" not in s:
            (user_id,) = params
            db.roles.add((user_id, "admin"))
            self._result = None

        elif s.startswith("SELECT disabled FROM iam.users WHERE id"):
            (user_id,) = params
            user = db.users.get(user_id)
            self._result = (user["disabled"],) if user is not None else None

        elif s.startswith("SELECT 1 FROM iam.user_roles WHERE user_id"):
            (user_id,) = params
            self._result = (1,) if (user_id, "admin") in db.roles else None

        else:
            raise AssertionError(f"unhandled SQL in fake: {s}")

    def fetchone(self):
        return self._result


class FakeConn:
    def __init__(self):
        self.db = FakeDB()

    def cursor(self):
        return FakeCursor(self.db)


# ----------------------------------------------------------------
# provision-user
# ----------------------------------------------------------------

conn = FakeConn()
r1 = ia.provision_user(conn, issuer="https://issuer.example", subject="sub-1", display_name="Ada Lawyer", actor_user_id=1)
check("provision_user creates exactly one new user on first call", r1.created is True)

r2 = ia.provision_user(conn, issuer="https://issuer.example", subject="sub-1", display_name="Ada Lawyer", actor_user_id=1)
check("provision_user is idempotent on an identical replay (same user_id, created=False)", r2.created is False and r2.user_id == r1.user_id)
check("idempotent replay creates no second user row", len(conn.db.users) == 1)
check("idempotent replay creates no second identity row", len(conn.db.identities) == 1)

expect_raises(
    ia.AdminCommandError,
    lambda: ia.provision_user(conn, issuer="https://issuer.example", subject="sub-1", display_name="DIFFERENT NAME", actor_user_id=1),
    "provision_user fails closed on (issuer, subject) reuse with different display_name",
)
check("failed conflicting attempt created no orphan row", len(conn.db.users) == 1 and len(conn.db.identities) == 1)

r3 = ia.provision_user(conn, issuer="https://issuer.example", subject="sub-2", display_name="Beth Analyst", actor_user_id=1)
check("provision_user creates a second, distinct user for a different (issuer, subject)", r3.user_id != r1.user_id)

user_provisioned_events = [e for e in conn.db.events]  # events are recorded via security_events, captured below
# security_events writes go through the SAME FakeCursor, so verify by
# re-running with an event-catching cursor wrapper instead:
class EventCatchingConn(FakeConn):
    def cursor(self):
        outer = self

        class Wrapped(FakeCursor):
            def execute(self_inner, sql, params=()):
                if "INSERT INTO iam.security_events" in sql:
                    outer.captured_events.append(params[0])
                    return
                return super().execute(sql, params)
        return Wrapped(self.db)

ec = EventCatchingConn()
ec.captured_events = []
ia.provision_user(ec, issuer="https://i2.example", subject="s1", display_name="X", actor_user_id=1)
check("provision_user (create path) writes exactly one user_provisioned event", ec.captured_events == ["user_provisioned"])
ia.provision_user(ec, issuer="https://i2.example", subject="s1", display_name="X", actor_user_id=1)
check("provision_user (idempotent replay) writes NO additional event", ec.captured_events == ["user_provisioned"])

# ----------------------------------------------------------------
# disable-user / enable-user
# ----------------------------------------------------------------

conn2 = FakeConn()
u = ia.provision_user(conn2, issuer="i", subject="s", display_name="Target", actor_user_id=1).user_id
conn2.db.sessions[100] = {"user_id": u, "revoked": False}
conn2.db.sessions[101] = {"user_id": u, "revoked": False}
before_authz_version = conn2.db.users[u]["authz_version"]

ia.disable_user(conn2, user_id=u, actor_user_id=1)
check("disable_user sets disabled=True", conn2.db.users[u]["disabled"] is True)
check("disable_user bumps authz_version", conn2.db.users[u]["authz_version"] == before_authz_version + 1)
check("disable_user revokes every active session for the user", all(s["revoked"] for s in conn2.db.sessions.values()))

ia.enable_user(conn2, user_id=u, actor_user_id=1)
check("enable_user clears disabled", conn2.db.users[u]["disabled"] is False)
check("enable_user does NOT recreate/un-revoke sessions", all(s["revoked"] for s in conn2.db.sessions.values()))
check("enable_user does NOT touch authz_version", conn2.db.users[u]["authz_version"] == before_authz_version + 1)

# ----------------------------------------------------------------
# grant-role / revoke-role
# ----------------------------------------------------------------

conn3 = FakeConn()
u3 = ia.provision_user(conn3, issuer="i3", subject="s3", display_name="Admin Candidate", actor_user_id=1).user_id
ia.grant_admin_role(conn3, user_id=u3, actor_user_id=1)
check("grant_admin_role grants the role", (u3, "admin") in conn3.db.roles)
ia.revoke_admin_role(conn3, user_id=u3, actor_user_id=1)
check("revoke_admin_role removes the role", (u3, "admin") not in conn3.db.roles)

# ----------------------------------------------------------------
# assign-case / revoke-assignment - one active role per case
# ----------------------------------------------------------------

conn4 = FakeConn()
u4 = ia.provision_user(conn4, issuer="i4", subject="s4", display_name="Lawyer One", actor_user_id=1).user_id
ia.assign_case(conn4, user_id=u4, case_id="case_0001", role="lawyer", actor_user_id=1)
expect_raises(
    RuntimeError,  # the fake's stand-in for the real partial-unique-index violation
    lambda: ia.assign_case(conn4, user_id=u4, case_id="case_0001", role="analyst", actor_user_id=1),
    "assign_case rejects a second active assignment for the same (user, case) - matches the real partial unique index",
)
ia.revoke_assignment(conn4, user_id=u4, case_id="case_0001", actor_user_id=1)
ia.assign_case(conn4, user_id=u4, case_id="case_0001", role="analyst", actor_user_id=1)
check("after revocation, a new active assignment for the same (user, case) is allowed", True)

# ----------------------------------------------------------------
# revoke-session (admin-triggered)
# ----------------------------------------------------------------

conn5 = FakeConn()
u5 = ia.provision_user(conn5, issuer="i5", subject="s5", display_name="Someone", actor_user_id=1).user_id
conn5.db.sessions[200] = {"user_id": u5, "revoked": False}
ia.admin_revoke_session(conn5, session_id=200, actor_user_id=999)
check("admin_revoke_session revokes the target session", conn5.db.sessions[200]["revoked"] is True)
expect_raises(
    ia.AdminCommandError,
    lambda: ia.admin_revoke_session(conn5, session_id=200, actor_user_id=999),
    "admin_revoke_session on an already-revoked session fails closed rather than silently no-op",
)

# ----------------------------------------------------------------
# bootstrap-first-admin - singleton
# ----------------------------------------------------------------

conn6 = FakeConn()
uid = ia.bootstrap_first_admin(conn6, issuer="i6", subject="s6", display_name="First Admin")
check("bootstrap_first_admin creates the admin user with the admin role", (uid, "admin") in conn6.db.roles)
expect_raises(
    RuntimeError,
    lambda: ia.bootstrap_first_admin(conn6, issuer="i7", subject="s7", display_name="Second Admin"),
    "a second bootstrap_first_admin call is rejected by the singleton (concurrency guarantee)",
)

# ----------------------------------------------------------------
# Row 19B targeted remediation (finding 1) - _verify_actor_is_active_admin,
# against the same in-memory fake (no psycopg needed for this layer).
# This is the fail-closed GATE that _run_locked_as_admin() calls before
# every one of the 8 non-bootstrap commands' mutation. A REAL,
# migration-applied disposable PostgreSQL proof of the full
# _run_locked_as_admin wiring (FK behavior + real transactional
# rollback) follows further below and is opt-in (VERGI_TEST_PG_DSN) -
# "Yalnız fake connection testi yeterli değildir" is honored by that
# section, not by this one; this one only proves the gate function's
# own decision logic in isolation.
# ----------------------------------------------------------------

conn7 = FakeConn()
active_admin_id = ia.provision_user(conn7, issuer="i-admin", subject="s-admin", display_name="Real Admin", actor_user_id=1).user_id
conn7.db.roles.add((active_admin_id, "admin"))

disabled_admin_id = ia.provision_user(conn7, issuer="i-disabled", subject="s-disabled", display_name="Disabled Admin", actor_user_id=1).user_id
conn7.db.roles.add((disabled_admin_id, "admin"))
conn7.db.users[disabled_admin_id]["disabled"] = True

non_admin_id = ia.provision_user(conn7, issuer="i-nonadmin", subject="s-nonadmin", display_name="Non Admin", actor_user_id=1).user_id

nonexistent_actor_id = 999_999

# valid, active admin actor -> accepted (no exception)
try:
    ia._verify_actor_is_active_admin(conn7, active_admin_id)
    check("_verify_actor_is_active_admin accepts a real, non-disabled, admin-role actor", True)
except Exception as error:
    check("_verify_actor_is_active_admin accepts a real, non-disabled, admin-role actor", False, repr(error))

expect_raises(
    ia.AdminCommandError,
    lambda: ia._verify_actor_is_active_admin(conn7, nonexistent_actor_id),
    "_verify_actor_is_active_admin fails closed on a nonexistent actor_user_id",
)
try:
    ia._verify_actor_is_active_admin(conn7, nonexistent_actor_id)
    check("nonexistent actor reason_code", False)
except ia.AdminCommandError as e:
    check("nonexistent actor reports reason_code=actor_not_found", e.reason_code == "actor_not_found")

expect_raises(
    ia.AdminCommandError,
    lambda: ia._verify_actor_is_active_admin(conn7, disabled_admin_id),
    "_verify_actor_is_active_admin fails closed on a disabled actor, even one holding the admin role",
)
try:
    ia._verify_actor_is_active_admin(conn7, disabled_admin_id)
    check("disabled actor reason_code", False)
except ia.AdminCommandError as e:
    check("disabled admin actor reports reason_code=actor_disabled (checked before the role check)", e.reason_code == "actor_disabled")

expect_raises(
    ia.AdminCommandError,
    lambda: ia._verify_actor_is_active_admin(conn7, non_admin_id),
    "_verify_actor_is_active_admin fails closed on an existing, active, but non-admin actor",
)
try:
    ia._verify_actor_is_active_admin(conn7, non_admin_id)
    check("non-admin actor reason_code", False)
except ia.AdminCommandError as e:
    check("non-admin actor reports reason_code=actor_not_admin", e.reason_code == "actor_not_admin")

check(
    "no hardcoded actor_user_id=0 sentinel remains anywhere in scripts/iam_admin.py's source",
    "actor_user_id=0" not in Path(REPO_ROOT / "scripts" / "iam_admin.py").read_text(encoding="utf-8"),
)


def _build_parser_actions_by_command():
    """Re-derives argparse's own subparser action list by calling main()'s
    parser-construction code path via --help's SystemExit, rather than
    hand-parsing source text - this proves the ACTUAL wired-up CLI
    surface requires --actor-user-id, not just that the string appears
    somewhere in the file."""
    import argparse as _argparse

    captured = {}
    original_add_parser = _argparse._SubParsersAction.add_parser

    def spy_add_parser(self, name, **kwargs):
        parser = original_add_parser(self, name, **kwargs)
        captured[name] = parser
        return parser

    _argparse._SubParsersAction.add_parser = spy_add_parser
    try:
        try:
            ia.main(["bootstrap-first-admin", "--help"])
        except SystemExit:
            pass
    finally:
        _argparse._SubParsersAction.add_parser = original_add_parser
    return captured


_parsers_by_command = _build_parser_actions_by_command()
_actor_required_commands = [
    "provision-user", "grant-role", "revoke-role", "assign-case",
    "revoke-assignment", "revoke-session", "disable-user", "enable-user",
]
for _cmd in _actor_required_commands:
    _parser = _parsers_by_command.get(_cmd)
    _has_actor_arg = _parser is not None and any(
        "--actor-user-id" in a.option_strings and a.required for a in _parser._actions
    )
    check(f"argparse subparser for {_cmd!r} requires --actor-user-id", _has_actor_arg)

_bootstrap_parser = _parsers_by_command.get("bootstrap-first-admin")
check(
    "bootstrap-first-admin's subparser takes no --actor-user-id (unchanged bootstrap semantics)",
    _bootstrap_parser is not None and not any("--actor-user-id" in a.option_strings for a in _bootstrap_parser._actions),
)

# ----------------------------------------------------------------
# Row 19B targeted remediation (finding 1), continued - REAL,
# migration-applied disposable PostgreSQL CLI-wiring/FK/rollback proof.
#
# This exercises the ACTUAL production code path - scripts.iam_admin.
# _run_locked_as_admin(), which opens a real ui.services.db.transaction()
# (real psycopg connection, real global:iam advisory lock, real SQL) -
# not the in-memory fake above. Per the governing instruction, a
# fake-connection test alone is not accepted as proof for this finding.
#
# Gating (same conventions already established in
# test_mutation_lock_isolated.py / test_security_events_isolated.py /
# test_iam_migrations_isolated.py):
#   - VERGI_TEST_PG_DSN: the NAME of a pre-created, already-migrated
#     (0001_iam_schema.sql + 0002_mutation_resources.sql) disposable
#     PostgreSQL database. Not set -> SKIPPED, NOT EXECUTED, not a pass.
#   - Once opted in via VERGI_TEST_PG_DSN, a missing prerequisite is an
#     explicit FAIL, never a silent downgrade to SKIP: this section
#     specifically needs `psycopg` (unlike the psql-subprocess-only
#     sibling files above) because it drives the real Python code under
#     test, not just raw SQL - so a VERGI_TEST_PG_DSN opt-in without
#     psycopg installed is reported as a FAIL with a clear message, the
#     same discipline the sibling files apply to a missing `psql`
#     executable.
#   - Connection parameters come from the standard libpq environment
#     variables already used by every other real-DB test in this
#     project (PGHOST/PGPORT/PGUSER/PGPASSWORD), combined into a
#     keyword/value libpq conninfo string (never a URI, so a password
#     containing special characters needs no URL-encoding) - never
#     placed in argv, printed, or embedded in an exception message.
#     VERGI_IAM_DATABASE_URL, if already set by the caller, is used
#     as-is instead (lets a caller who already has a full DSN skip
#     the reconstruction entirely).
#   - Every row this section creates is namespaced with a fresh
#     uuid4 suffix, so repeated runs against the same shared disposable
#     database never collide with each other or with rows left behind
#     by other suites (e.g. test_security_events_isolated.py's
#     'sectest' user).
# ----------------------------------------------------------------

PG_DB = os.environ.get("VERGI_TEST_PG_DSN")


def _build_libpq_conninfo(dbname: str) -> str:
    parts = [f"dbname={dbname}"]
    host = os.environ.get("PGHOST")
    port = os.environ.get("PGPORT")
    user = os.environ.get("PGUSER")
    password = os.environ.get("PGPASSWORD")
    if host:
        parts.append(f"host={host}")
    if port:
        parts.append(f"port={port}")
    if user:
        parts.append(f"user={user}")
    if password:
        parts.append(f"password={password}")
    return " ".join(parts)


if not PG_DB:
    print(
        "SKIPPED real-PostgreSQL iam_admin CLI-wiring/FK/rollback checks - "
        "VERGI_TEST_PG_DSN not set to a reachable, migrated disposable database "
        "in this run. NOT EXECUTED, not a pass."
    )
else:
    try:
        import psycopg  # noqa: F401  (opted in - a missing driver here is a FAIL, not a SKIP)
        _HAS_PSYCOPG = True
    except ModuleNotFoundError:
        _HAS_PSYCOPG = False

    if not _HAS_PSYCOPG:
        check(
            "psycopg is installed (required once VERGI_TEST_PG_DSN opts into the real-DB iam_admin test)",
            False,
            "VERGI_TEST_PG_DSN is set but the `psycopg` package is not importable in this environment - "
            "this section drives the real production code path (ui.services.db.transaction / "
            "scripts.iam_admin._run_locked_as_admin) and cannot be satisfied by psql subprocess calls "
            "alone. Run this suite in an environment with psycopg[binary] installed against the same "
            "disposable database to get a real PASS/FAIL here.",
        )
    else:
        _saved_dsn_env = os.environ.get("VERGI_IAM_DATABASE_URL")
        try:
            dsn = _saved_dsn_env or _build_libpq_conninfo(PG_DB)
            os.environ["VERGI_IAM_DATABASE_URL"] = dsn

            from ui.services import db as real_db  # noqa: E402
            from ui.services import session_store as real_session_store  # noqa: E402

            suffix = uuid.uuid4().hex[:12]

            def _setup_row(sql, params=()):
                with real_db.transaction() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        return cur.fetchone()

            try:
                (admin_actor_id,) = _setup_row(
                    "INSERT INTO iam.users(display_name) VALUES (%s) RETURNING id",
                    (f"row19b_admin_actor_{suffix}",),
                )
                _setup_row("INSERT INTO iam.user_roles(user_id, role) VALUES (%s, 'admin') RETURNING user_id", (admin_actor_id,))

                (disabled_actor_id,) = _setup_row(
                    "INSERT INTO iam.users(display_name, disabled) VALUES (%s, TRUE) RETURNING id",
                    (f"row19b_disabled_actor_{suffix}",),
                )
                _setup_row("INSERT INTO iam.user_roles(user_id, role) VALUES (%s, 'admin') RETURNING user_id", (disabled_actor_id,))

                (non_admin_actor_id,) = _setup_row(
                    "INSERT INTO iam.users(display_name) VALUES (%s) RETURNING id",
                    (f"row19b_nonadmin_actor_{suffix}",),
                )

                (nonexistent_actor_id2,) = _setup_row(
                    "SELECT COALESCE(MAX(id), 0) + 1000000 FROM iam.users",
                )

                check("real DB: fixture actors were created (admin/disabled/non-admin all have real row ids)", True)
            except Exception as error:
                check("real DB: fixture actor setup completed without error", False, repr(error))
                admin_actor_id = disabled_actor_id = non_admin_actor_id = nonexistent_actor_id2 = None

            # ---- HAPPY PATH: all 8 non-bootstrap commands, valid admin actor ----
            if admin_actor_id is not None:
                try:
                    from scripts import iam_admin as ia_real  # same module object as `ia` above

                    provision_result = ia_real._run_locked_as_admin(
                        ia_real.provision_user, actor_user_id=admin_actor_id,
                        issuer=f"https://issuer.example/{suffix}", subject=f"sub-{suffix}",
                        display_name=f"row19b_provisioned_{suffix}",
                    )
                    target_user_id = provision_result.user_id
                    check("real DB: provision-user succeeds with a valid admin actor (no FK violation)", provision_result.created is True)

                    ia_real._run_locked_as_admin(ia_real.grant_admin_role, actor_user_id=admin_actor_id, user_id=target_user_id)
                    check("real DB: grant-role succeeds with a valid admin actor (no FK violation)", True)

                    ia_real._run_locked_as_admin(ia_real.revoke_admin_role, actor_user_id=admin_actor_id, user_id=target_user_id)
                    check("real DB: revoke-role succeeds with a valid admin actor (no FK violation)", True)

                    case_id = f"row19b_case_{suffix}"
                    ia_real._run_locked_as_admin(
                        ia_real.assign_case, actor_user_id=admin_actor_id,
                        user_id=target_user_id, case_id=case_id, role="lawyer",
                    )
                    check("real DB: assign-case succeeds with a valid admin actor (no FK violation)", True)

                    ia_real._run_locked_as_admin(
                        ia_real.revoke_assignment, actor_user_id=admin_actor_id,
                        user_id=target_user_id, case_id=case_id,
                    )
                    check("real DB: revoke-assignment succeeds with a valid admin actor (no FK violation)", True)

                    with real_db.transaction() as _conn:
                        _raw_token, real_session_id = real_session_store.create_session(
                            _conn, user_id=target_user_id, role_version_at_issue=1,
                        )
                    ia_real._run_locked_as_admin(
                        ia_real.admin_revoke_session, actor_user_id=admin_actor_id, session_id=real_session_id,
                    )
                    check("real DB: revoke-session succeeds with a valid admin actor (no FK violation)", True)

                    ia_real._run_locked_as_admin(ia_real.disable_user, actor_user_id=admin_actor_id, user_id=target_user_id)
                    check("real DB: disable-user succeeds with a valid admin actor (no FK violation)", True)

                    ia_real._run_locked_as_admin(ia_real.enable_user, actor_user_id=admin_actor_id, user_id=target_user_id)
                    check("real DB: enable-user succeeds with a valid admin actor (no FK violation)", True)

                    (events_written,) = _setup_row(
                        "SELECT count(*) FROM iam.security_events WHERE actor_user_id = %s", (admin_actor_id,),
                    )
                    check(
                        "real DB: every one of the 8 commands wrote its security event with the REAL verified actor_user_id (never 0)",
                        events_written == 8,
                        f"got {events_written}",
                    )
                except Exception as error:
                    check("real DB: all 8 commands complete for a valid admin actor without an unexpected exception", False, repr(error))

            # ---- NEGATIVE PATH: invalid/disabled/non-admin actors fail closed with real rollback ----
            def _count(sql, params=()):
                (n,) = _setup_row(sql, params)
                return n

            for label, bad_actor_id, expected_reason in (
                ("nonexistent", nonexistent_actor_id2, "actor_not_found"),
                ("disabled", disabled_actor_id, "actor_disabled"),
                ("non-admin", non_admin_actor_id, "actor_not_admin"),
            ):
                if bad_actor_id is None:
                    continue
                try:
                    (probe_user_id,) = _setup_row(
                        "INSERT INTO iam.users(display_name) VALUES (%s) RETURNING id",
                        (f"row19b_probe_{label}_{suffix}",),
                    )
                    roles_before = _count("SELECT count(*) FROM iam.user_roles WHERE user_id = %s", (probe_user_id,))
                    events_before = _count("SELECT count(*) FROM iam.security_events WHERE user_id = %s", (probe_user_id,))

                    raised = None
                    try:
                        ia_real._run_locked_as_admin(ia_real.grant_admin_role, actor_user_id=bad_actor_id, user_id=probe_user_id)
                    except ia_real.AdminCommandError as exc:
                        raised = exc

                    check(f"real DB: {label} actor is rejected (AdminCommandError raised, grant-role never applied)", raised is not None)
                    if raised is not None:
                        check(f"real DB: {label} actor reports reason_code={expected_reason!r}", raised.reason_code == expected_reason)

                    roles_after = _count("SELECT count(*) FROM iam.user_roles WHERE user_id = %s", (probe_user_id,))
                    events_after = _count("SELECT count(*) FROM iam.security_events WHERE user_id = %s", (probe_user_id,))
                    check(
                        f"real DB: {label} actor rejection left ZERO mutation (real re-query, not Python state) - "
                        f"user_roles {roles_before}->{roles_after}",
                        roles_before == roles_after == 0,
                    )
                    check(
                        f"real DB: {label} actor rejection wrote ZERO security events (real re-query) - "
                        f"security_events {events_before}->{events_after}",
                        events_before == events_after == 0,
                    )
                except Exception as error:
                    check(f"real DB: {label}-actor fail-closed/rollback check completed without an unexpected exception", False, repr(error))
        finally:
            if _saved_dsn_env is None:
                os.environ.pop("VERGI_IAM_DATABASE_URL", None)
            else:
                os.environ["VERGI_IAM_DATABASE_URL"] = _saved_dsn_env

print(f"--- test_iam_admin_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
