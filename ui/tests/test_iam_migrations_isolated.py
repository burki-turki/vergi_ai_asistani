# ============================================================
# Row 19B - isolated tests for db/migrations/0001_iam_schema.sql and
# db/migrations/0002_mutation_resources.sql.
#
# Uses `psql` via subprocess (stdlib `subprocess` only - no psycopg
# needed) against a REAL, disposable PostgreSQL database. Creates and
# drops its OWN throwaway database per run so it never touches
# anything persistent. SKIPPED with an explicit message if no
# reachable PostgreSQL is configured for this run via
# VERGI_TEST_PG_SUPERUSER_AVAILABLE=1 (never silently treated as a
# pass).
#
# CROSS-PLATFORM PORTABLE HARNESS (targeted remediation): the previous
# version of this file hardcoded the Linux-only `["sudo", "-u",
# "postgres", "psql", ...]` invocation pattern, which cannot work on
# the Windows target runtime even when PostgreSQL is installed there
# (no `sudo`, and peer-auth-as-the-"postgres"-OS-user does not exist on
# Windows). This version:
#   - never invokes `sudo` on any platform;
#   - resolves the `psql` executable from VERGI_TEST_PSQL_BIN (a
#     single full path, used AS-IS - this is what supports a Windows
#     path containing spaces, e.g. "C:\Program Files\PostgreSQL\16\
#     bin\psql.exe" - it is one argv element, never split/quoted) or
#     falls back to `shutil.which("psql")` on PATH;
#   - connects using the standard libpq environment variables
#     (PGHOST/PGPORT/PGUSER/PGPASSWORD) that this process already has
#     in its own environment - never places host/port/user/password on
#     the command line, and PGPASSWORD in particular is NEVER read,
#     echoed, or embedded by this file's own code (subprocess.run
#     simply inherits the parent environment, which is where any
#     PGPASSWORD already lives if the caller set one);
#   - the maintenance-database connection (for CREATE DATABASE / DROP
#     DATABASE / pg_terminate_backend, which must run against an
#     existing database, not the not-yet-created throwaway one) uses
#     VERGI_TEST_PG_MAINTENANCE_DB (default "postgres") instead of
#     relying on the OS user's default database via peer auth;
#   - always passes subprocess an argv list, never shell=True or a
#     concatenated shell string.
#
# Run: python -m ui.tests.test_iam_migrations_isolated
# ============================================================

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

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


# ============================================================
# COMMAND-CONSTRUCTION LAYER (pure - no subprocess call here) - kept
# separate from `psql()` below specifically so it can be unit-tested
# in isolation (see the argv-shape checks further down), independent
# of whether a real PostgreSQL/psql is available in this run.
# ============================================================

def resolve_psql_executable():
    """VERGI_TEST_PSQL_BIN (a single full executable path, used exactly
    as given - no splitting, no shell quoting) wins if set; otherwise
    `shutil.which("psql")` searches PATH. Returns None if neither
    resolves to anything - callers must treat that as a hard FAIL when
    opted in (see below), never as a reason to silently skip."""
    override = os.environ.get("VERGI_TEST_PSQL_BIN")
    if override:
        return override
    return shutil.which("psql")


def build_psql_argv(psql_bin, db, *, sql=None, file=None, on_error_stop=True):
    """Builds the full argv list for one `psql` invocation. Never
    returns a shell string, never appends `sudo`, never places a
    password anywhere in it - connection host/port/user/password come
    exclusively from this process's own environment (standard libpq
    PGHOST/PGPORT/PGUSER/PGPASSWORD), which subprocess.run inherits
    automatically when no explicit `env=` is passed."""
    argv = [psql_bin, "-t", "-A"]
    if db:
        argv += ["-d", db]
    if on_error_stop:
        argv += ["-v", "ON_ERROR_STOP=1"]
    if file is not None:
        argv += ["-f", str(file)]
    elif sql is not None:
        argv += ["-c", sql]
    return argv


def psql(psql_bin, db, sql=None, file=None, on_error_stop=True):
    argv = build_psql_argv(psql_bin, db, sql=sql, file=file, on_error_stop=on_error_stop)
    return subprocess.run(argv, capture_output=True, text=True, timeout=30)


# ============================================================
# PURE COMMAND-CONSTRUCTION TESTS - run unconditionally, need no real
# PostgreSQL/psql at all (targeted remediation item 13).
# ============================================================

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
    _argv = build_psql_argv(_fake_bin_with_spaces, "row19b_probe_db", sql="SELECT 1;")

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
import ast as _ast
import inspect as _inspect
_this_tree = _ast.parse(_inspect.getsource(sys.modules[__name__]))
check(
    "this file's own code never passes shell=True to any call (AST-based, comments excluded)",
    not any(
        isinstance(n, _ast.keyword) and n.arg == "shell"
        and isinstance(n.value, _ast.Constant) and n.value.value is True
        for n in _ast.walk(_this_tree)
    ),
)


# ============================================================
# REAL, DISPOSABLE-POSTGRESQL MIGRATION CHECKS (opt-in only).
# ============================================================

if not os.environ.get("VERGI_TEST_PG_SUPERUSER_AVAILABLE"):
    print(
        "SKIPPED migration checks - VERGI_TEST_PG_SUPERUSER_AVAILABLE not "
        "set (no disposable PostgreSQL superuser access configured for "
        "this run). NOT EXECUTED, not a pass."
    )
    print(f"--- test_iam_migrations_isolated: {passed} passed, {failed} failed ---")
    sys.exit(1 if failed else 0)

# Opted in from here on: a missing psql executable or an unreachable
# database is now an explicit FAIL with a nonzero exit - never a SKIP
# and never counted as a pass (targeted remediation item 8).
PSQL_BIN = resolve_psql_executable()
if not PSQL_BIN:
    check(
        "psql executable resolved (VERGI_TEST_PSQL_BIN or PATH)",
        False,
        "VERGI_TEST_PG_SUPERUSER_AVAILABLE=1 was set but no usable psql executable "
        "was found via VERGI_TEST_PSQL_BIN or PATH",
    )
    print(f"--- test_iam_migrations_isolated: {passed} passed, {failed} failed ---")
    sys.exit(1)
if not Path(PSQL_BIN).is_file():
    # Catches a VERGI_TEST_PSQL_BIN typo/bad-path up front with a clean
    # FAIL, rather than letting a raw FileNotFoundError surface later
    # from inside subprocess.run.
    check(
        "resolved psql executable path exists on disk",
        False,
        f"{PSQL_BIN!r} (from VERGI_TEST_PSQL_BIN or PATH) does not exist or is not a file",
    )
    print(f"--- test_iam_migrations_isolated: {passed} passed, {failed} failed ---")
    sys.exit(1)

MAINTENANCE_DB = os.environ.get("VERGI_TEST_PG_MAINTENANCE_DB", "postgres")
db_name = f"row19b_migtest_{uuid.uuid4().hex[:8]}"

# Outer try/except: opted in means a broken executable/unreachable
# database must surface as an explicit FAIL check (and a nonzero final
# exit code via `failed`), never as an uncaught traceback and never as
# a silent SKIP (targeted remediation item 8) - this wraps BOTH the
# migration steps and the finally-cleanup below, since either one can
# hit the same class of subprocess/OS error (e.g. a bad
# VERGI_TEST_PSQL_BIN, or a database that becomes unreachable
# mid-run).
try:
    try:
        r = psql(PSQL_BIN, MAINTENANCE_DB, sql=f"CREATE DATABASE {db_name};")
        check("throwaway database created", r.returncode == 0, r.stderr)

        r = psql(PSQL_BIN, db_name, file=MIGRATIONS_DIR / "0001_iam_schema.sql")
        check("0001_iam_schema.sql applies cleanly to an empty database", r.returncode == 0, r.stderr)

        r = psql(PSQL_BIN, db_name, file=MIGRATIONS_DIR / "0002_mutation_resources.sql")
        check("0002_mutation_resources.sql applies cleanly after 0001", r.returncode == 0, r.stderr)

        tables = psql(PSQL_BIN, db_name, sql="SELECT table_schema||'.'||table_name FROM information_schema.tables "
                                              "WHERE table_schema IN ('iam','mutation') ORDER BY 1;").stdout.strip().splitlines()
        expected_tables = {
            "iam.bootstrap_state", "iam.case_assignments", "iam.external_identities",
            "iam.oidc_login_transactions", "iam.security_events", "iam.sessions",
            "iam.user_roles", "iam.users", "mutation.mutation_resources",
        }
        check("exactly the expected tables exist in iam/mutation schemas", set(tables) == expected_tables, f"got {tables}")

        seeded = psql(PSQL_BIN, db_name, sql="SELECT advisory_lock_id FROM mutation.mutation_resources WHERE resource_key='global:iam';").stdout.strip()
        check("global:iam is seeded with a database-assigned advisory_lock_id", seeded.isdigit())

        # Re-running both migrations must not fail (IF NOT EXISTS / ON
        # CONFLICT guards) - a legitimate convenience for test/dev re-runs.
        r1 = psql(PSQL_BIN, db_name, file=MIGRATIONS_DIR / "0001_iam_schema.sql")
        r2 = psql(PSQL_BIN, db_name, file=MIGRATIONS_DIR / "0002_mutation_resources.sql")
        check("both migrations are safely re-runnable against an already-migrated database", r1.returncode == 0 and r2.returncode == 0)

        still_one_row = psql(PSQL_BIN, db_name, sql="SELECT count(*) FROM mutation.mutation_resources WHERE resource_key='global:iam';").stdout.strip()
        check("re-running 0002 does not duplicate the global:iam seed row", still_one_row == "1")
    finally:
        psql(PSQL_BIN, MAINTENANCE_DB, sql=f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}';")
        drop = psql(PSQL_BIN, MAINTENANCE_DB, sql=f"DROP DATABASE IF EXISTS {db_name};")
        check("throwaway database was dropped, leaving no trace", drop.returncode == 0, drop.stderr)
except Exception as error:
    check(
        "migration checks completed without an unexpected exception (e.g. psql not runnable, database unreachable)",
        False,
        repr(error),
    )

print(f"--- test_iam_migrations_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
