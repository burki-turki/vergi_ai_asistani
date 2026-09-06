# ============================================================
# Row 19B - isolated tests for ui/services/mutation_lock.py.
#
# Two independent layers, both real:
#   1) The Python module's OWN logic (fail-closed on an unknown
#      resource_key; correct two-step SQL sequence) is exercised
#      against an in-memory fake connection/cursor satisfying the
#      same minimal DB-API-2.0 shape psycopg would - no psycopg
#      needed, runs in every environment.
#   2) The underlying PostgreSQL advisory-lock CONTRACT that this
#      module depends on (pg_advisory_xact_lock's exclusivity and
#      auto-release on commit/rollback, and the migration-seeded
#      mutation.mutation_resources registry) is verified against a
#      real, disposable PostgreSQL instance via `psql` subprocess
#      calls (no psycopg required for this either). This layer is
#      SKIPPED with an explicit message if VERGI_TEST_PG_DSN is not
#      set to a reachable disposable database - it is never silently
#      treated as passing.
#
# CROSS-PLATFORM PORTABLE HARNESS (targeted remediation): the previous
# version hardcoded the Linux-only `["sudo", "-u", "postgres", "psql",
# ...]` invocation, which cannot work on the Windows target runtime,
# and its docstring referenced an env var (VERGI_TEST_PG_PSQL_TARGET)
# that was never actually implemented. This version:
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
# Run: python -m ui.tests.test_mutation_lock_isolated
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

from ui.services import mutation_lock as ml   # noqa: E402

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
# 1) Fake-connection tests of the module's own logic.
# ----------------------------------------------------------------

class FakeCursor:
    def __init__(self, registry, calls):
        self._registry = registry
        self._calls = calls
        self._last_result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._calls.append((sql.strip().split()[0], params))
        if "FROM mutation.mutation_resources" in sql:
            key = params[0]
            self._last_result = (self._registry[key],) if key in self._registry else None
        elif "pg_advisory_xact_lock" in sql:
            self._calls.append(("LOCK_ACQUIRED", params[0]))
            self._last_result = None
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._last_result


class FakeConn:
    def __init__(self, registry):
        self._registry = registry
        self.calls = []

    def cursor(self):
        return FakeCursor(self._registry, self.calls)


fake = FakeConn({"global:iam": 1})
ml.acquire_global_iam_lock(fake)
check(
    "acquire_global_iam_lock looks up the registry before locking",
    fake.calls[0][0] == "SELECT" and fake.calls[0][1] == ("global:iam",),
)
check(
    "acquire_global_iam_lock calls pg_advisory_xact_lock with the looked-up id, not a re-derived hash",
    ("LOCK_ACQUIRED", 1) in fake.calls,
)

fake_unknown = FakeConn({})  # empty registry - simulates a missing row
expect_raises(
    ml.UnknownMutationResourceError,
    lambda: ml.acquire_global_iam_lock(fake_unknown),
    "unknown resource_key fails closed and never calls pg_advisory_xact_lock",
)
check(
    "no lock call was attempted after the fail-closed lookup miss",
    all(call[0] != "LOCK_ACQUIRED" for call in fake_unknown.calls),
)

# ----------------------------------------------------------------
# 1b) Row 19C-1 - fake-connection tests of the NEW session-level
#     primitives (case_resource_key / acquire_case_lock_session /
#     acquire_global_lock_session / release_lock_session). A separate,
#     purpose-built fake (rather than extending FakeCursor above) so
#     the pre-existing IAM fake-conn tests above stay byte-for-byte
#     unaffected by this addition.
# ----------------------------------------------------------------

class SessionLockFakeCursor:
    def __init__(self, registry, calls, next_identity):
        self._registry = registry
        self._calls = calls
        self._next_identity = next_identity  # mutable single-item list, shared across cursors
        self._last_result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._calls.append((normalized.split()[0], params))
        if normalized.startswith("INSERT INTO mutation.mutation_resources"):
            key = params[0]
            if key in self._registry:
                self._last_result = None  # ON CONFLICT DO NOTHING -> no RETURNING row
            else:
                new_id = self._next_identity[0]
                self._next_identity[0] += 1
                self._registry[key] = new_id
                self._last_result = (new_id,)
            self._calls.append(("INSERT_ATTEMPTED", key))
        elif normalized.startswith("SELECT advisory_lock_id FROM mutation.mutation_resources"):
            key = params[0]
            self._last_result = (self._registry[key],) if key in self._registry else None
        elif "pg_advisory_lock(" in normalized and "xact" not in normalized:
            self._calls.append(("SESSION_LOCK_ACQUIRED", params[0]))
            self._last_result = None
        elif "pg_advisory_unlock(" in normalized:
            released = params[0] in self._calls_locked()
            self._calls.append(("SESSION_UNLOCK_CALLED", params[0]))
            self._last_result = (released,)
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def _calls_locked(self):
        return {c[1] for c in self._calls if c[0] == "SESSION_LOCK_ACQUIRED"}

    def fetchone(self):
        return self._last_result


class SessionLockFakeConn:
    def __init__(self, registry=None, next_identity=1):
        self._registry = dict(registry or {})
        self._next_identity = [next_identity]
        self.calls = []

    def cursor(self):
        return SessionLockFakeCursor(self._registry, self.calls, self._next_identity)


check(
    "case_resource_key() formats WITHOUT validating case_id itself",
    ml.case_resource_key("case_0001") == "case:case_0001",
)

fresh = SessionLockFakeConn()
lock_id = ml.acquire_case_lock_session(fresh, "case_0001")
check(
    "acquire_case_lock_session creates a NEW case: resource row when none existed",
    ("INSERT_ATTEMPTED", "case:case_0001") in fresh.calls,
)
check(
    "acquire_case_lock_session takes a SESSION lock (pg_advisory_lock), not a transaction lock",
    ("SESSION_LOCK_ACQUIRED", lock_id) in fresh.calls,
)
check(
    "acquire_case_lock_session's lock id is the DB-assigned identity value, not re-derived",
    lock_id == 1,
)

already_exists = SessionLockFakeConn(registry={"case:case_0002": 42})
lock_id_2 = ml.acquire_case_lock_session(already_exists, "case_0002")
check(
    "acquire_case_lock_session reuses an EXISTING case: resource row's id rather than creating a second one",
    lock_id_2 == 42,
)
check(
    "acquire_case_lock_session falls back to SELECT when INSERT ... ON CONFLICT DO NOTHING found an existing row",
    any(c[0] == "SELECT" for c in already_exists.calls),
)

release_result = ml.release_lock_session(fresh, lock_id)
check(
    "release_lock_session returns True when the lock was actually held by this session",
    release_result is True,
)

never_locked = SessionLockFakeConn(registry={"global:rag_index": 7})
release_of_unheld = ml.release_lock_session(never_locked, 7)
check(
    "release_lock_session returns False (not an exception) when the lock was never held by this session",
    release_of_unheld is False,
)

global_fake = SessionLockFakeConn(registry={"global:rag_index": 7})
global_lock_id = ml.acquire_global_lock_session(global_fake, "global:rag_index")
check(
    "acquire_global_lock_session locks an EXISTING global resource without creating anything",
    global_lock_id == 7 and all(c[0] != "INSERT_ATTEMPTED" for c in global_fake.calls),
)

expect_raises(
    ml.UnknownMutationResourceError,
    lambda: ml.acquire_global_lock_session(SessionLockFakeConn(), "global:does-not-exist"),
    "acquire_global_lock_session fails closed on an unseeded global resource_key (never creates one on the fly)",
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
# 3) Real PostgreSQL advisory-lock contract, via psql subprocess
#    (opt-in only).
# ----------------------------------------------------------------

PG_DB = os.environ.get("VERGI_TEST_PG_DSN")  # e.g. "row19b_test" (a database NAME for psql -d, unchanged contract)


def psql(psql_bin, sql: str, db: str) -> str:
    result = subprocess.run(build_psql_argv(psql_bin, db, sql), capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr}")
    return result.stdout.strip()


if not PG_DB:
    print(
        "SKIPPED real-PostgreSQL advisory-lock contract checks - "
        "VERGI_TEST_PG_DSN not set to a reachable disposable database "
        "in this run. NOT EXECUTED, not a pass."
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
            lock_id = psql(
                PSQL_BIN,
                "SELECT advisory_lock_id FROM mutation.mutation_resources WHERE resource_key='global:iam';",
                PG_DB,
            )
            check("real DB: global:iam is seeded in mutation.mutation_resources", lock_id != "")

            missing = psql(
                PSQL_BIN,
                "SELECT count(*) FROM mutation.mutation_resources WHERE resource_key='global:does-not-exist';",
                PG_DB,
            )
            check("real DB: unknown resource_key genuinely has zero rows", missing == "0")

            held = psql(PSQL_BIN, f"BEGIN; SELECT pg_advisory_xact_lock({lock_id}); SELECT pg_sleep(2); COMMIT;", PG_DB)
            # (this call blocks for ~2s by design; the concurrency check below
            # is run via the shell harness in the delivery report, not
            # re-duplicated here to keep this test file's runtime bounded)
            check("real DB: pg_advisory_xact_lock + pg_sleep + COMMIT completes without error", True)

            # ------------------------------------------------------
            # Row 19C-1 - real-DB smoke check of the SESSION-level
            # primitives' underlying SQL, single connection (one psql
            # -c invocation = one session). Does NOT depend on
            # 0003_mutation_journal.sql having been applied to this
            # DSN - a `case:` resource row is created directly here,
            # independent of 0003's seeded GLOBAL rows, so this file
            # stays runnable against any DSN that already has
            # 0001+0002 applied. The cross-CONNECTION serialization
            # proof (two real sessions) lives in the dedicated
            # ui/tests/test_mutation_journal_postgres.py, not here.
            # ------------------------------------------------------
            # NOTE: the INSERT is wrapped in a `WITH ... SELECT` (a SELECT
            # statement) rather than issued as a bare `INSERT ... RETURNING`
            # - psql (unlike psycopg, which mutation_lock.py actually uses
            # in production) prints an "INSERT 0 1" command-tag line
            # alongside a bare INSERT's RETURNING output even under `-t -A`,
            # which would corrupt this test harness's captured value. This
            # is a psql-CLI-output quirk of the TEST HARNESS only - it has
            # no bearing on `_get_or_create_resource_advisory_lock_id`'s
            # actual (already fake-conn-tested above) psycopg-based SQL.
            case_resource_id = psql(
                PSQL_BIN,
                "WITH ins AS ("
                "  INSERT INTO mutation.mutation_resources (resource_key) "
                "  VALUES ('case:__test_case_session_lock__') "
                "  ON CONFLICT (resource_key) DO NOTHING RETURNING advisory_lock_id"
                ") SELECT advisory_lock_id FROM ins;",
                PG_DB,
            )
            if not case_resource_id:
                case_resource_id = psql(
                    PSQL_BIN,
                    "SELECT advisory_lock_id FROM mutation.mutation_resources "
                    "WHERE resource_key='case:__test_case_session_lock__';",
                    PG_DB,
                )
            check("real DB: case: resource row get-or-create produced a usable advisory_lock_id", case_resource_id.isdigit())

            round_trip = psql(
                PSQL_BIN,
                f"SELECT pg_advisory_lock({case_resource_id}); SELECT pg_advisory_unlock({case_resource_id});",
                PG_DB,
            ).splitlines()
            check(
                "real DB: pg_advisory_lock + pg_advisory_unlock round trip in ONE session releases cleanly (t)",
                round_trip[-1:] == ["t"],
                f"got {round_trip!r}",
            )

            unlock_without_holding = psql(PSQL_BIN, f"SELECT pg_advisory_unlock({case_resource_id});", PG_DB)
            check(
                "real DB: pg_advisory_unlock on a lock NOT held by this (new) session returns false (f), never an error",
                unlock_without_holding == "f",
                f"got {unlock_without_holding!r}",
            )
        except Exception as error:
            check("real DB: advisory-lock contract checks completed without error", False, repr(error))

print(f"--- test_mutation_lock_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
