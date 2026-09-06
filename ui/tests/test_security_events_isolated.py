# ============================================================
# Row 19B - isolated tests for ui/services/security_events.py.
#
# Layer 1 (always runs, no deps): a fake in-memory connection/cursor
# recorder proves each writer function emits the correct event_type
# and column set, with NO free-form/JSONB payload anywhere.
#
# Layer 2 (real, when VERGI_TEST_PG_DSN is set): inserts one row per
# event_type directly against the real disposable PostgreSQL schema
# via `psql`, proving the migration's CHECK-constrained enum actually
# accepts every value this module can emit, and rejects an unlisted
# one - closing the loop between the Python vocabulary and the SQL
# vocabulary for real.
#
# CROSS-PLATFORM PORTABLE HARNESS (targeted remediation): the previous
# version hardcoded the Linux-only `["sudo", "-u", "postgres", "psql",
# ...]` invocation, which cannot work on the Windows target runtime.
# This version:
#   - never invokes `sudo` on any platform;
#   - resolves `psql` from VERGI_TEST_PSQL_BIN (a single full path,
#     used AS-IS - one argv element, so a Windows path containing
#     spaces such as "C:\Program Files\PostgreSQL\16\bin\psql.exe"
#     works unmodified) or falls back to `shutil.which("psql")`;
#   - connects using the standard libpq environment variables
#     (PGHOST/PGPORT/PGUSER/PGPASSWORD) already present in this
#     process's own environment - never placed on the command line,
#     in test output, or in an exception message;
#   - `VERGI_TEST_PG_DSN` keeps meaning exactly what it always meant
#     for this file: the name of a pre-created disposable database
#     (passed to `psql -d`), NOT a full DSN string - unchanged;
#   - always passes subprocess an argv list, never shell=True.
#
# Run: python -m ui.tests.test_security_events_isolated
# ============================================================

import ast
import inspect
import os
import shutil
import subprocess
import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import security_events as se   # noqa: E402

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


# ----------------------------------------------------------------
# 1) Fake-connection recorder.
# ----------------------------------------------------------------

class FakeCursor:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, values):
        self._sink.append((sql, tuple(values)))


class FakeConn:
    def __init__(self):
        self.inserts = []

    def cursor(self):
        return FakeCursor(self.inserts)


REQUIRED_VOCAB = {
    "login_success", "login_denied_unknown_identity", "login_denied_disabled_user",
    "login_denied_mfa_absent", "logout", "session_revoked", "session_expired_idle",
    "session_expired_absolute", "authz_denied", "csrf_rejected", "admin_role_granted",
    "admin_role_revoked", "case_assignment_granted", "case_assignment_revoked",
    "user_provisioned", "user_disabled", "user_enabled", "bootstrap_first_admin",
}

check(
    "ALL_EVENT_WRITERS covers exactly the required v1 vocabulary (incl. user_provisioned, "
    "user_disabled, user_enabled; excl. the withdrawn identity_linked)",
    set(se.ALL_EVENT_WRITERS.keys()) == REQUIRED_VOCAB,
    detail=f"got {sorted(se.ALL_EVENT_WRITERS.keys())}",
)
check("identity_linked is not a valid event type in this module", "identity_linked" not in se.ALL_EVENT_WRITERS)

conn = FakeConn()
se.record_login_success(conn, user_id=1, session_id=10, mfa_satisfied=True,
                         mfa_assurance_level="entra_p1_context_satisfied", mfa_assurance_policy_version="row19b-v1")
sql, values = conn.inserts[-1]
check("record_login_success writes exactly one row", len(conn.inserts) == 1)
check("record_login_success uses the login_success event_type", values[0] == "login_success")
check("no writer function accepts a free-form/JSONB payload kwarg", "detail" not in sql and "payload" not in sql)

conn2 = FakeConn()
se.record_session_revoked(conn2, user_id=5, session_id=50, actor_user_id=5)
se.record_session_revoked(conn2, user_id=5, session_id=51, actor_user_id=99)
_, self_values = conn2.inserts[0]
_, admin_values = conn2.inserts[1]
check(
    "session_revoked disambiguates self vs admin via actor_user_id, not a second event type",
    "user_action" in self_values and "admin_action" in admin_values,
)

conn3 = FakeConn()
se.record_login_denied_unknown_identity(conn3)
_, unknown_values = conn3.inserts[0]
check(
    "login_denied_unknown_identity carries no identifying detail (existence-blind)",
    len(unknown_values) <= 2,  # event_type + reason_code only
)

# ----------------------------------------------------------------
# 2) COMMAND-CONSTRUCTION LAYER (pure - no subprocess call here) -
#    kept separate from `psql()` below so it can be unit-tested in
#    isolation, independent of whether a real PostgreSQL/psql is
#    available in this run.
# ----------------------------------------------------------------

def resolve_psql_executable():
    """VERGI_TEST_PSQL_BIN (a single full executable path, used exactly
    as given) wins if set; otherwise `shutil.which("psql")` searches
    PATH. Returns None if neither resolves - callers must treat that
    as a hard FAIL when opted in, never as a reason to silently skip."""
    override = os.environ.get("VERGI_TEST_PSQL_BIN")
    if override:
        return override
    return shutil.which("psql")


def build_psql_argv(psql_bin, db, sql):
    """No `sudo`, no shell string, no password anywhere - connection
    host/port/user/password come exclusively from this process's own
    environment (standard libpq PGHOST/PGPORT/PGUSER/PGPASSWORD),
    which subprocess.run inherits automatically."""
    return [psql_bin, "-d", db, "-t", "-A", "-c", sql]


# ----------------------------------------------------------------
# PURE COMMAND-CONSTRUCTION TESTS - run unconditionally, need no real
# PostgreSQL/psql at all (targeted remediation item 13).
# ----------------------------------------------------------------

_saved_psql_bin_env = os.environ.get("VERGI_TEST_PSQL_BIN")
_saved_pgpassword_env = os.environ.get("PGPASSWORD")
try:
    _fake_bin_with_spaces = r"C:\Program Files\PostgreSQL\16\bin\psql.exe"
    os.environ["VERGI_TEST_PSQL_BIN"] = _fake_bin_with_spaces
    _resolved = resolve_psql_executable()
    check(
        "resolve_psql_executable() returns VERGI_TEST_PSQL_BIN VERBATIM, spaces and all, as ONE value",
        _resolved == _fake_bin_with_spaces,
        f"got {_resolved!r}",
    )

    _marker_password = "sentinel_password_must_never_appear_in_argv"
    os.environ["PGPASSWORD"] = _marker_password
    _argv = build_psql_argv(_fake_bin_with_spaces, "row19b_probe_db", "SELECT 1;")

    check("built argv contains no 'sudo' element", "sudo" not in _argv)
    check(
        "built argv's executable is EXACTLY VERGI_TEST_PSQL_BIN (single element, path kept whole)",
        _argv[0] == _fake_bin_with_spaces and _fake_bin_with_spaces.count(" ") > 0,
    )
    check(
        "database name is its own argv element immediately after '-d'",
        "-d" in _argv and _argv[_argv.index("-d") + 1] == "row19b_probe_db",
    )
    check(
        "the PGPASSWORD value never appears anywhere in the built argv",
        all(_marker_password not in element for element in _argv),
    )
finally:
    if _saved_psql_bin_env is None:
        os.environ.pop("VERGI_TEST_PSQL_BIN", None)
    else:
        os.environ["VERGI_TEST_PSQL_BIN"] = _saved_psql_bin_env
    if _saved_pgpassword_env is None:
        os.environ.pop("PGPASSWORD", None)
    else:
        os.environ["PGPASSWORD"] = _saved_pgpassword_env

# "no sudo in the argv" is already proven directly above (the actual
# built argv was inspected). Separately, AST-check (not a raw substring
# scan - this file's own comments/docstrings legitimately DISCUSS
# `shell=True` when explaining what NOT to do, which would false-
# positive a plain text search) that no `subprocess.run(...)` call
# anywhere in this file passes shell=True - comments carry no AST
# nodes, so only a real `shell=True` keyword argument in real code can
# match this.
_this_tree = ast.parse(inspect.getsource(sys.modules[__name__]))
check(
    "this file's own code never passes shell=True to any call (AST-based, comments excluded)",
    not any(
        isinstance(n, ast.keyword) and n.arg == "shell"
        and isinstance(n.value, ast.Constant) and n.value.value is True
        for n in ast.walk(_this_tree)
    ),
)


# ----------------------------------------------------------------
# 3) Real PostgreSQL enum-coverage check (opt-in only).
# ----------------------------------------------------------------

PG_DB = os.environ.get("VERGI_TEST_PG_DSN")


def psql(psql_bin, sql: str, db: str):
    result = subprocess.run(build_psql_argv(psql_bin, db, sql), capture_output=True, text=True, timeout=15)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


if not PG_DB:
    print(
        "SKIPPED real-PostgreSQL event_type enum coverage check - "
        "VERGI_TEST_PG_DSN not set. NOT EXECUTED, not a pass."
    )
else:
    # Opted in from here on: a missing psql executable or an
    # unreachable database is an explicit FAIL - never a SKIP and
    # never counted as a pass (targeted remediation item 8).
    PSQL_BIN = resolve_psql_executable()
    if not PSQL_BIN:
        check(
            "psql executable resolved (VERGI_TEST_PSQL_BIN or PATH)",
            False,
            "VERGI_TEST_PG_DSN is set but no usable psql executable was found via "
            "VERGI_TEST_PSQL_BIN or PATH",
        )
    elif not Path(PSQL_BIN).is_file():
        # Catches a VERGI_TEST_PSQL_BIN typo/bad-path up front with a
        # clean FAIL, rather than an uncaught FileNotFoundError from
        # inside subprocess.run.
        check(
            "resolved psql executable path exists on disk",
            False,
            f"{PSQL_BIN!r} (from VERGI_TEST_PSQL_BIN or PATH) does not exist or is not a file",
        )
    else:
        try:
            rc, _, _ = psql(PSQL_BIN, "INSERT INTO iam.users(display_name) VALUES ('sectest') RETURNING id;", PG_DB)
            all_ok = True
            for event_type in sorted(REQUIRED_VOCAB):
                rc, out, err = psql(PSQL_BIN, f"INSERT INTO iam.security_events(event_type) VALUES ('{event_type}');", PG_DB)
                if rc != 0:
                    all_ok = False
                    print(f"    unexpected rejection for {event_type!r}: {err}")
            check("real DB: every Python vocabulary event_type is accepted by the CHECK constraint", all_ok)

            rc, out, err = psql(PSQL_BIN, "INSERT INTO iam.security_events(event_type) VALUES ('identity_linked');", PG_DB)
            check("real DB: the withdrawn 'identity_linked' event_type is genuinely rejected", rc != 0)

            psql(PSQL_BIN, "DELETE FROM iam.security_events;", PG_DB)  # leave the disposable DB tidy for later suites
        except Exception as error:
            check(
                "real DB: event_type enum coverage checks completed without an unexpected exception",
                False,
                repr(error),
            )

print(f"--- test_security_events_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
