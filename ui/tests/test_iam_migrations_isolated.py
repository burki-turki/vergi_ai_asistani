# ============================================================
# Row 19B/19C-1 - isolated tests for db/migrations/0001_iam_schema.sql,
# db/migrations/0002_mutation_resources.sql, and (Row 19C-1 addition)
# db/migrations/0003_mutation_journal.sql.
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

        r = psql(PSQL_BIN, db_name, file=MIGRATIONS_DIR / "0003_mutation_journal.sql")
        check("0003_mutation_journal.sql (Row 19C-1) applies cleanly after 0001+0002", r.returncode == 0, r.stderr)

        tables = psql(PSQL_BIN, db_name, sql="SELECT table_schema||'.'||table_name FROM information_schema.tables "
                                              "WHERE table_schema IN ('iam','mutation') ORDER BY 1;").stdout.strip().splitlines()
        expected_tables = {
            "iam.bootstrap_state", "iam.case_assignments", "iam.external_identities",
            "iam.oidc_login_transactions", "iam.security_events", "iam.sessions",
            "iam.user_roles", "iam.users", "mutation.mutation_resources",
            "mutation.mutation_journal",
        }
        check("exactly the expected tables exist in iam/mutation schemas (0003's mutation_journal included)", set(tables) == expected_tables, f"got {tables}")

        seeded = psql(PSQL_BIN, db_name, sql="SELECT advisory_lock_id FROM mutation.mutation_resources WHERE resource_key='global:iam';").stdout.strip()
        check("global:iam is seeded with a database-assigned advisory_lock_id", seeded.isdigit())

        # Row 19C-1: 0003 seeds three NEW global resource keys
        # (reserved for future Row 19C-2+ global mutators) - never a
        # case:<id> resource, which is created on demand instead (see
        # ui/services/mutation_lock.py's acquire_case_lock_session).
        global_resource_rows = psql(
            PSQL_BIN, db_name,
            sql="SELECT resource_key||'|'||advisory_lock_id FROM mutation.mutation_resources "
                "WHERE resource_key IN ('global:rag_index','global:deadline_rules','global:legal_provisions') "
                "ORDER BY resource_key;",
        ).stdout.strip().splitlines()
        check(
            "0003 seeds exactly the 3 new global resource keys, each with its own DB-assigned advisory_lock_id",
            len(global_resource_rows) == 3 and all("|" in row and row.split("|")[1].isdigit() for row in global_resource_rows),
            f"got {global_resource_rows}",
        )
        all_resource_ids = psql(
            PSQL_BIN, db_name, sql="SELECT advisory_lock_id FROM mutation.mutation_resources ORDER BY advisory_lock_id;",
        ).stdout.strip().splitlines()
        check(
            "every mutation_resources row (0002's global:iam plus 0003's three new ones) has a DISTINCT advisory_lock_id",
            len(all_resource_ids) == len(set(all_resource_ids)) == 4,
            f"got {all_resource_ids}",
        )

        journal_row_count = psql(PSQL_BIN, db_name, sql="SELECT count(*) FROM mutation.mutation_journal;").stdout.strip()
        check("mutation.mutation_journal starts out empty on a freshly migrated database", journal_row_count == "0")

        # Re-running all three migrations must not fail (IF NOT EXISTS
        # / ON CONFLICT / CREATE ... IF NOT EXISTS guards) - a
        # legitimate convenience for test/dev re-runs.
        r1 = psql(PSQL_BIN, db_name, file=MIGRATIONS_DIR / "0001_iam_schema.sql")
        r2 = psql(PSQL_BIN, db_name, file=MIGRATIONS_DIR / "0002_mutation_resources.sql")
        r3 = psql(PSQL_BIN, db_name, file=MIGRATIONS_DIR / "0003_mutation_journal.sql")
        check("all three migrations are safely re-runnable against an already-migrated database", r1.returncode == 0 and r2.returncode == 0 and r3.returncode == 0)

        still_one_row = psql(PSQL_BIN, db_name, sql="SELECT count(*) FROM mutation.mutation_resources WHERE resource_key='global:iam';").stdout.strip()
        check("re-running 0002 does not duplicate the global:iam seed row", still_one_row == "1")

        still_four_resource_rows = psql(PSQL_BIN, db_name, sql="SELECT count(*) FROM mutation.mutation_resources;").stdout.strip()
        check("re-running 0003 does not duplicate any of its 3 global resource-key seed rows", still_four_resource_rows == "4")

        still_empty_journal = psql(PSQL_BIN, db_name, sql="SELECT count(*) FROM mutation.mutation_journal;").stdout.strip()
        check("re-running 0003 does not fabricate any mutation_journal rows", still_empty_journal == "0")

        # ----------------------------------------------------------------
        # Row 19C-1 TARGETED CONTRACT REMEDIATION: idempotency_key must be
        # UNCONDITIONALLY unique across mutation.mutation_journal's ENTIRE
        # history - a plain UNIQUE(idempotency_key) table constraint,
        # never a partial index scoped to non-`failed` rows. An earlier
        # (REJECTED) draft of this migration used a partial index instead,
        # specifically so that TWO `failed` rows could share the same
        # idempotency_key (one per retry attempt) - that design is no
        # longer valid. This proves the reversal directly against the
        # real database: a second row sharing an existing row's
        # idempotency_key is rejected by the DATABASE ITSELF, in ANY
        # state, `failed` included - never merely by application logic in
        # ui/services/mutation_coordinator.py.
        # ----------------------------------------------------------------
        uniq_key = f"uniq_test_key_{uuid.uuid4().hex}"

        first_failed = psql(
            PSQL_BIN, db_name,
            sql=(
                "INSERT INTO mutation.mutation_journal ("
                "  resource_key, action_family, actor_label, target_ref,"
                "  idempotency_key, request_fingerprint, state, executing_at, resolved_at"
                ") VALUES ("
                "  'global:rag_index', 'fam.uniq_test', 'test_actor', 'target_a',"
                f"  '{uniq_key}', 'fp_a', 'failed', now(), now()"
                ");"
            ),
        )
        check("setup: a first FAILED row with a fresh idempotency_key inserts cleanly", first_failed.returncode == 0, first_failed.stderr)

        second_failed_same_key = psql(
            PSQL_BIN, db_name,
            sql=(
                "INSERT INTO mutation.mutation_journal ("
                "  resource_key, action_family, actor_label, target_ref,"
                "  idempotency_key, request_fingerprint, state, executing_at, resolved_at"
                ") VALUES ("
                "  'global:rag_index', 'fam.uniq_test', 'test_actor', 'target_b',"
                f"  '{uniq_key}', 'fp_b', 'failed', now(), now()"
                ");"
            ),
        )
        check(
            "a SECOND 'failed' row sharing an EXISTING failed row's idempotency_key is REJECTED by the database "
            "(unconditional UNIQUE(idempotency_key) - the REJECTED partial-index design would have allowed this)",
            second_failed_same_key.returncode != 0
            and "idempotency_key" in second_failed_same_key.stderr.lower()
            and ("unique" in second_failed_same_key.stderr.lower() or "duplicate" in second_failed_same_key.stderr.lower()),
            second_failed_same_key.stderr,
        )

        second_prepared_same_key = psql(
            PSQL_BIN, db_name,
            sql=(
                "INSERT INTO mutation.mutation_journal ("
                "  resource_key, action_family, actor_label, target_ref,"
                "  idempotency_key, request_fingerprint, state"
                ") VALUES ("
                "  'global:rag_index', 'fam.uniq_test', 'test_actor', 'target_c',"
                f"  '{uniq_key}', 'fp_c', 'prepared'"
                ");"
            ),
        )
        check(
            "a row in a DIFFERENT state ('prepared') sharing the same idempotency_key is ALSO rejected - "
            "state is irrelevant to this constraint",
            second_prepared_same_key.returncode != 0
            and "idempotency_key" in second_prepared_same_key.stderr.lower(),
            second_prepared_same_key.stderr,
        )

        only_one_row_for_key = psql(
            PSQL_BIN, db_name,
            sql=f"SELECT count(*) FROM mutation.mutation_journal WHERE idempotency_key = '{uniq_key}';",
        ).stdout.strip()
        check("exactly ONE row exists for this idempotency_key after both rejected duplicate attempts", only_one_row_for_key == "1")

        # ----------------------------------------------------------------
        # ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION (item 5) - real
        # PostgreSQL negative tests for 0003's CHECK constraints,
        # against the REAL database (never merely asserted by reading
        # the migration's own SQL text). Each negative case gets its
        # own fresh idempotency_key so a REJECTED insert never masks a
        # DIFFERENT constraint's own, unrelated violation.
        # ----------------------------------------------------------------

        def insert_journal_row(*, key_suffix, extra_columns="", extra_values=""):
            key = f"uniq_negtest_{key_suffix}_{uuid.uuid4().hex}"
            columns = "resource_key, action_family, actor_label, target_ref, idempotency_key, request_fingerprint"
            values = f"'global:rag_index', 'fam.negtest', 'test_actor', 't_{key_suffix}', '{key}', 'fp_{key_suffix}'"
            if extra_columns:
                columns += f", {extra_columns}"
                values += f", {extra_values}"
            return psql(
                PSQL_BIN, db_name,
                sql=f"INSERT INTO mutation.mutation_journal ({columns}) VALUES ({values});",
            )

        # (a) 'executing' + executing_at NULL -> REJECTED (the new,
        # stricter direction of mutation_journal_executing_at_matches_state:
        # previously this file's own constraint only enforced
        # prepared->NULL, never non-prepared->NOT NULL).
        r = insert_journal_row(key_suffix="executing_null_executing_at", extra_columns="state", extra_values="'executing'")
        check(
            "'executing' + executing_at NULL is REJECTED by the database (mutation_journal_executing_at_matches_state)",
            r.returncode != 0 and "executing_at" in r.stderr.lower(),
            r.stderr,
        )

        # (b) 'prepared' + executing_at NOT NULL -> REJECTED (the
        # ORIGINAL direction of the same constraint - still enforced).
        r = insert_journal_row(
            key_suffix="prepared_with_executing_at",
            extra_columns="state, executing_at", extra_values="'prepared', now()",
        )
        check(
            "'prepared' + executing_at NOT NULL is REJECTED by the database (mutation_journal_executing_at_matches_state)",
            r.returncode != 0 and "executing_at" in r.stderr.lower(),
            r.stderr,
        )

        # (c) a terminal state ('completed') + resolved_at NULL ->
        # REJECTED (mutation_journal_resolved_at_matches_state).
        # executing_at is set here specifically so this INSERT violates
        # ONLY the resolved_at constraint being tested, not (a)'s
        # separate executing_at one too.
        r = insert_journal_row(
            key_suffix="completed_null_resolved_at",
            extra_columns="state, executing_at, observed_post_hash",
            extra_values="'completed', now(), 'somehash'",
        )
        check(
            "a terminal state ('completed') with resolved_at NULL is REJECTED by the database (mutation_journal_resolved_at_matches_state)",
            r.returncode != 0 and "resolved_at" in r.stderr.lower(),
            r.stderr,
        )

        # (d) 'completed' with NEITHER observed_post_hash NOR
        # resolution_code set -> REJECTED (mutation_journal_completed_
        # requires_evidence) - `completed` is never written on faith
        # alone.
        r = insert_journal_row(
            key_suffix="completed_no_evidence",
            extra_columns="state, executing_at, resolved_at",
            extra_values="'completed', now(), now()",
        )
        check(
            "'completed' with neither observed_post_hash nor resolution_code set is REJECTED (mutation_journal_completed_requires_evidence)",
            r.returncode != 0 and "evidence" in r.stderr.lower(),
            r.stderr,
        )

        # (e) valid rows of every shape are STILL accepted - the
        # tightened constraint does not collaterally reject anything
        # legitimate.
        r = insert_journal_row(key_suffix="valid_prepared", extra_columns="state", extra_values="'prepared'")
        check("a valid 'prepared' row (executing_at NULL) is still accepted", r.returncode == 0, r.stderr)

        r = insert_journal_row(key_suffix="valid_executing", extra_columns="state, executing_at", extra_values="'executing', now()")
        check("a valid 'executing' row (executing_at set) is still accepted", r.returncode == 0, r.stderr)

        r = insert_journal_row(
            key_suffix="valid_completed",
            extra_columns="state, executing_at, resolved_at, observed_post_hash",
            extra_values="'completed', now(), now(), 'realhash'",
        )
        check("a valid 'completed' row (executing_at set, resolved_at set, observed_post_hash set) is still accepted", r.returncode == 0, r.stderr)

        r = insert_journal_row(
            key_suffix="valid_reconciliation_required",
            extra_columns="state, executing_at", extra_values="'reconciliation_required', now()",
        )
        check("a valid 'reconciliation_required' row (executing_at set, resolved_at NULL) is still accepted", r.returncode == 0, r.stderr)

        # ----------------------------------------------------------------
        # ROW 19C-1 TIMESTAMP SEMANTICS CORRECTION - real PostgreSQL
        # negative/positive tests for the two CHECK constraints added in
        # this correction (mutation_journal_executing_at_matches_state's
        # new CASE branch, and the new independent
        # mutation_journal_prepared_never_executed_code_is_exclusive).
        # Each case is isolated so a REJECTED insert is provably caused
        # by the ONE constraint under test, not a different, unrelated
        # violation.
        # ----------------------------------------------------------------

        # (f) the exact, legitimate shape: 'failed' +
        # resolution_code='reconciled_failed_prepared_never_executed' +
        # executing_at NULL + resolved_at set -> ACCEPTED (this is
        # precisely what ui.services.mutation_registry's prepared-never-
        # executed branch writes).
        r = insert_journal_row(
            key_suffix="valid_prepared_never_executed",
            extra_columns="state, resolution_code, resolved_at",
            extra_values="'failed', 'reconciled_failed_prepared_never_executed', now()",
        )
        check(
            "a valid 'failed' + prepared-never-executed resolution_code row (executing_at NULL, resolved_at set) is accepted",
            r.returncode == 0, r.stderr,
        )

        # (g) the SAME resolution_code with a NON-NULL executing_at ->
        # REJECTED - a legal/security journal must never let this
        # specific code coexist with a fabricated execution timestamp.
        r = insert_journal_row(
            key_suffix="prepared_never_executed_with_executing_at",
            extra_columns="state, resolution_code, resolved_at, executing_at",
            extra_values="'failed', 'reconciled_failed_prepared_never_executed', now(), now()",
        )
        check(
            "'failed' + prepared-never-executed resolution_code + NON-NULL executing_at is REJECTED by the database "
            "(mutation_journal_executing_at_matches_state / mutation_journal_prepared_never_executed_code_is_exclusive)",
            r.returncode != 0
            and ("executing_at" in r.stderr.lower() or "prepared_never_executed" in r.stderr.lower()),
            r.stderr,
        )

        # (h) the SAME resolution_code attached to a DIFFERENT state
        # ('completed', with executing_at set so the CASE constraint's
        # OWN "completed -> executing_at NOT NULL" branch is satisfied -
        # isolating THIS failure to the exclusivity constraint alone) ->
        # REJECTED - the prepared-never-executed claim ("writer never
        # invoked") directly contradicts a 'completed' row, which by
        # construction DID cross the writer boundary.
        r = insert_journal_row(
            key_suffix="prepared_never_executed_wrong_state_completed",
            extra_columns="state, resolution_code, resolved_at, executing_at",
            extra_values="'completed', 'reconciled_failed_prepared_never_executed', now(), now()",
        )
        check(
            "the prepared-never-executed resolution_code attached to state='completed' is REJECTED by the database "
            "(mutation_journal_prepared_never_executed_code_is_exclusive - state <> 'failed')",
            r.returncode != 0 and "prepared_never_executed" in r.stderr.lower(),
            r.stderr,
        )

        # (i) same resolution_code attached to a NON-terminal state
        # ('executing', executing_at set so resolved_at may legitimately
        # stay NULL and the CASE constraint's own "executing -> NOT
        # NULL" branch is satisfied) -> REJECTED for the same reason as
        # (h) - the exclusivity constraint rejects ANY state other than
        # 'failed', not just other terminal ones.
        r = insert_journal_row(
            key_suffix="prepared_never_executed_wrong_state_executing",
            extra_columns="state, resolution_code, executing_at",
            extra_values="'executing', 'reconciled_failed_prepared_never_executed', now()",
        )
        check(
            "the prepared-never-executed resolution_code attached to state='executing' is REJECTED by the database "
            "(mutation_journal_prepared_never_executed_code_is_exclusive - state <> 'failed')",
            r.returncode != 0 and "prepared_never_executed" in r.stderr.lower(),
            r.stderr,
        )

        # (j) explicit, dedicated coverage (beyond (a)'s 'executing'
        # case above) that 'reconciliation_required' and 'completed'
        # ALSO still require executing_at NOT NULL under the NEW
        # CASE-based constraint - the correction narrowed the NULL
        # exception to exactly ('prepared', 'failed'+that one code) and
        # must not have loosened it for any other state.
        r = insert_journal_row(key_suffix="reconciliation_required_null_executing_at", extra_columns="state", extra_values="'reconciliation_required'")
        check(
            "'reconciliation_required' + executing_at NULL is REJECTED by the database (mutation_journal_executing_at_matches_state)",
            r.returncode != 0 and "executing_at" in r.stderr.lower(),
            r.stderr,
        )

        r = insert_journal_row(
            key_suffix="completed_null_executing_at",
            extra_columns="state, resolved_at, observed_post_hash",
            extra_values="'completed', now(), 'somehash'",
        )
        check(
            "'completed' + executing_at NULL is REJECTED by the database (mutation_journal_executing_at_matches_state)",
            r.returncode != 0 and "executing_at" in r.stderr.lower(),
            r.stderr,
        )
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
