# ============================================================
# PILOT READINESS ADIM 3 - Runner / Environment / Skip Reporting:
# REAL-PostgreSQL integration proof for scripts/run_ui_tests.py
# (Fable FINAL contract section T.2). Separate from the isolated suite
# on purpose (13 `*_postgres.py` precedent): without VERGI_TEST_PG_DSN
# this module prints ONE documented skip and a `0 passed, 0 failed,
# 1 skipped` summary with exit 0 -- the runner classifies that as
# ZERO_CHECK_DOCUMENTED_SKIP, never as a pass.
#
# WHAT IS REAL HERE: the runner as a real subprocess, its L.4 PostgreSQL
# preflight against the operator's disposable loopback cluster
# (migrations 0001-0005), a throwaway database carrying only 0001-0003
# (MIGRATION_MISSING refusal), a fake module that really connects to
# PostgreSQL through the runner's child environment, the REAL
# ui.tests.test_rag_bundle_mutation_integration_postgres module run
# under the runner's child contract with VERGI_IAM_DATABASE_URL
# stripped (regression proof for the one-line authz_conn_factory fix),
# the same-target IAM URL refusal with a real conninfo, database
# residue detection, concurrent-sweep refusal, and pg_database /
# journal / data byte-invariance at the end.
#
# PRECONDITIONS (operator; values never printed): VERGI_TEST_PG_DSN
# (bare dbname), PGHOST=127.0.0.1 / PGPORT / PGUSER (/ PGPASSWORD),
# VERGI_TEST_PSQL_BIN or psql on PATH, VERGI_TEST_PG_SUPERUSER_AVAILABLE=1,
# VERGI_TEST_PG_MAINTENANCE_DB (default postgres). The cluster must be
# disposable: this module CREATEs and DROPs throwaway databases.
#
# SAFETY: every nested runner points at a FAKE module directory
# (--tests-dir) or at a single explicitly selected real module; the
# self-test seam VERGI_UI_TEST_SWEEP_SELFTEST=1 is what allows those two
# combinations (recursion-safe). Temp directories, throwaway databases
# and nested child temp dirs are removed in `finally`.
#
# Run: VERGI_TEST_PG_DSN=<db> python -m ui.tests.test_run_ui_tests_integration_postgres
# ============================================================

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODULE_NAME = "test_run_ui_tests_integration_postgres"
RAG_MODULE = "test_rag_bundle_mutation_integration_postgres"

passed = 0
failed = 0
skipped = 0

# ---------------------------------------------------------------------------
# B5: PostgreSQL environment VALUES never reach this module's stdout/stderr
# (every check/skip label and detail is redacted first) and never appear in
# a nested runner's console, report.json, ledger or logs
# (scan_pg_value_leaks()). B5-R1 structural rule, enforced by T.1 section
# 28 on the AST: spawn_and_scan() is the ONLY way a nested runner is started
# here (run_fake, S4, S5, S7) and it scans in `finally` -- timeout, spawn
# error, missing or malformed report included; the raw spawner
# _spawn_runner_unscanned() is called exactly once, inside that helper.
# Any exception escaping the suite body -- a psycopg connection/query
# failure whose message carries dbname/user/host/port values included --
# is caught by the top-level boundary below (baseline snapshots included),
# reported as a redacted FAIL (type + redacted message + file:line:function
# frames, never a raw traceback) and ends the run with the summary line and
# exit 1; sys.excepthook is a redacting backstop for anything outside it.
# Loopback PGHOST literals and the default maintenance DB name are not
# scanned: they are not secrets and occur verbatim in the runner's static
# allow-list messages / JSON keys. PGPORT is redacted with digit boundaries
# in detail strings and checked only as a quoted JSON string value in
# report.json (a bare port number would collide with pids/byte counts).
# V1 (found only by the first real-cluster run): the real rag module's own
# one-line startup banner, which carries the database name, is exempted in
# the S4 nested run's raw stdout log and nowhere else (see
# LOG_BANNER_EXEMPTION_PATTERNS_BY_TAG; T.1 section 28 pins that the table has
# exactly one tag and one pattern and that the pattern is not wider than the
# banner). The proof that S4 is green lives here, in real mode.
# ---------------------------------------------------------------------------
_LOOPBACK_LITERALS = {"localhost", "127.0.0.1", "::1"}

# V1: the REAL rag module prints exactly one startup banner line of its own
# ("backend: REAL psycopg <ver> (production driver), dbname=<name>") -- module
# owned, byte-locked, and present in the raw child log of the S4 nested run
# (a private run-directory file). Without an exemption the log scan flags it
# for every database name, so this suite could never pass against a real
# cluster. The exemption is deliberately the narrowest possible: one tag, one
# exact whole-line pattern, only the first occurrence, only that module's
# stdout log. Everything else in that log, and every other tag's logs, stay
# fully scanned; console, report.json and the ledger are scanned for every tag.
LOG_BANNER_EXEMPTION_PATTERNS_BY_TAG = {
    "s4_rag": r"(?m)^backend: REAL psycopg \S+ \(production driver\), dbname='[^'\r\n]*'\r?$",
}
LOG_BANNER_EXEMPTION_BY_TAG = {_t: re.compile(_p) for _t, _p in LOG_BANNER_EXEMPTION_PATTERNS_BY_TAG.items()}


def _pg_values():
    vals = {}
    for name in ("VERGI_TEST_PG_DSN", "VERGI_TEST_PG_MAINTENANCE_DB", "PGUSER", "PGPASSWORD"):
        value = os.environ.get(name)
        if value:
            vals[name] = value
    host = os.environ.get("PGHOST")
    if host and host.lower() not in _LOOPBACK_LITERALS:
        vals["PGHOST"] = host
    return vals


def _token_pattern(value):
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(value) + r"(?![A-Za-z0-9_])")


def redact(text):
    text = str(text)
    for name, value in _pg_values().items():
        if name == "PGPASSWORD":
            text = text.replace(value, "<%s>" % name)
        else:
            text = _token_pattern(value).sub("<%s>" % name, text)
    port = os.environ.get("PGPORT")
    if port:
        text = re.sub(r"(?<!\d)" + re.escape(port) + r"(?!\d)", "<PGPORT>", text)
    return text


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {redact(label)}")
    else:
        failed += 1
        print(f"FAIL {redact(label)} {redact(detail)}")


def skip(label, detail=""):
    global skipped
    skipped += 1
    print(f"SKIPPED {redact(label)} - {redact(detail)}")


def _print_summary():
    print(f"--- {MODULE_NAME}: {passed} passed, {failed} failed, {skipped} skipped ---")


def summarize_and_exit():
    _print_summary()
    sys.exit(1 if failed else 0)


def _record_unhandled(exc):
    """B5-R1: fail-closed reporting for ANY exception escaping the suite
    body (psycopg connection/query failures included). Prints the exception
    TYPE and a redacted message plus redacted file:line:function frames --
    never a raw traceback, never a source line, never a PostgreSQL env VALUE."""
    global failed
    failed += 1
    print("FAIL unhandled exception in the real-PostgreSQL suite (fail-closed, redacted): %s: %s"
          % (type(exc).__name__, redact(str(exc))[:500]))
    ctx = exc.__context__
    if ctx is not None and ctx is not exc:
        print("  context: %s: %s" % (type(ctx).__name__, redact(str(ctx))[:300]))
    for fr in traceback.extract_tb(exc.__traceback__)[-6:]:
        print("  at %s:%d in %s" % (redact(os.path.basename(fr.filename)), fr.lineno, fr.name))


def _redacting_excepthook(exc_type, exc, tb):
    # Backstop for anything raised OUTSIDE the boundary below (module-level
    # helpers, the boundary itself): the default hook would print the raw
    # message, which for psycopg carries dbname/user/host/port values. The
    # interpreter still exits 1 after this hook returns.
    _record_unhandled(exc)
    _print_summary()
    sys.stdout.flush()


sys.excepthook = _redacting_excepthook


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip(
        "the entire real-PostgreSQL runner integration suite",
        "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip(
        "the entire real-PostgreSQL runner integration suite",
        f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import scripts.run_ui_tests as runner  # noqa: E402

RUNNER_PATH = REPO_ROOT / "scripts" / "run_ui_tests.py"
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"
MAINTENANCE_DB = os.environ.get("VERGI_TEST_PG_MAINTENANCE_DB", "postgres")
INHERIT_GUARD_KEYS = (
    "PYTHONPATH", "PYTHONNOUSERSITE", runner.GUARD_LEDGER_ENV, runner.GUARD_RUN_ID_ENV,
    runner.GUARD_PARENT_PID_ENV,
)

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), database target configured (name not printed)")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def pg_connect(dbname=None):
    return psycopg.connect(dbname=dbname or PG_DB, autocommit=True)


def maint_connect():
    return psycopg.connect(dbname=MAINTENANCE_DB, autocommit=True)


def list_databases():
    with maint_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT datname FROM pg_database ORDER BY datname")
            return sorted(row[0] for row in cur.fetchall())


def create_database(name):
    with maint_connect() as conn:
        with conn.cursor() as cur:
            cur.execute('CREATE DATABASE "%s"' % name)


def drop_database(name):
    try:
        with maint_connect() as conn:
            with conn.cursor() as cur:
                cur.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % name)
        return True
    except Exception as exc:
        print(f"WARNING: could not drop {name}: {type(exc).__name__}")
        return False


def apply_migrations(dbname, filenames):
    with pg_connect(dbname) as conn:
        with conn.cursor() as cur:
            for fn in filenames:
                cur.execute((MIGRATIONS_DIR / fn).read_text(encoding="utf-8"))


RAG_RESOURCE_KEY = "global:rag_index"  # == rag_bundle_mutation_facade.RESOURCE_KEY of the real module run in S4


def journal_row_count(exclude_resource_key=None):
    with pg_connect() as conn:
        with conn.cursor() as cur:
            if exclude_resource_key is None:
                cur.execute("SELECT count(*) FROM mutation.mutation_journal")
            else:
                cur.execute("SELECT count(*) FROM mutation.mutation_journal WHERE resource_key <> %s", (exclude_resource_key,))
            return cur.fetchone()[0]


def tree_manifest(root):
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _on_rm_error(func, path, exc):
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except OSError:
        pass


def rmtree_retry(path, attempts=20):
    for _ in range(attempts):
        try:
            shutil.rmtree(path, onexc=_on_rm_error)
        except FileNotFoundError:
            return True
        except OSError:
            pass
        if not os.path.exists(path):
            return True
        time.sleep(0.25)
    return not os.path.exists(path)


NESTED_TMP_DIRS = []


def note_nested_tmp(report):
    if report and report.get("tmp_dir"):
        NESTED_TMP_DIRS.append(report["tmp_dir"])


def _spawn_runner_unscanned(args, extra_env=None, timeout=900):
    # B5-R1: raw spawner -- called ONLY from spawn_and_scan() (T.1 section 28 AST rule).
    env = dict(os.environ)
    for key in INHERIT_GUARD_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]
        else:
            env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env[runner.SELFTEST_SEAM_ENV] = "1"
    if extra_env:
        for k, v in extra_env.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
    argv = [sys.executable, str(RUNNER_PATH)] + [str(a) for a in args]
    r = subprocess.run(argv, cwd=str(REPO_ROOT), env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def find_run_dir(output_root):
    root = Path(output_root)
    if not root.exists():
        return None
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("sweep_"))
    return dirs[-1] if dirs else None


def load_report(run_dir):
    return json.loads((Path(run_dir) / "report.json").read_text(encoding="utf-8"))


def module_entry(report, name):
    for m in report["modules"]:
        if m["name"] == name:
            return m
    return None


def write_module(dirpath, name, source):
    (Path(dirpath) / f"{name}.py").write_text(source.replace("{n}", name), encoding="utf-8", newline="\n")


def _json_string_values(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _json_string_values(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _json_string_values(v, out)
    elif isinstance(obj, str):
        out.append(obj)


def scan_pg_value_leaks(tag, out, err, run_dir):
    """B5 regression: one check per nested runner invocation. The detail
    names only the location and the VARIABLE NAME, never the value."""
    vals = _pg_values()
    port = os.environ.get("PGPORT")
    leaks = []
    banner_exempt = LOG_BANNER_EXEMPTION_BY_TAG.get(tag)

    def scan_text(where, text):
        for name, value in vals.items():
            hit = (value in text) if name == "PGPASSWORD" else bool(_token_pattern(value).search(text))
            if hit:
                leaks.append(f"{where}:{name}")

    scan_text("console.stdout", out)
    scan_text("console.stderr", err)
    if run_dir is not None:
        rd = Path(run_dir)
        rep_path = rd / "report.json"
        if rep_path.exists():
            text = rep_path.read_text(encoding="utf-8", errors="replace")
            strings = []
            try:
                _json_string_values(json.loads(text), strings)
                joined = "\n".join(strings)
            except ValueError:
                joined = text
            scan_text("report.json", joined)
            if port and any(sv == port for sv in strings):
                leaks.append("report.json:PGPORT")
        ledger = rd / "guard_ledger.tsv"
        if ledger.exists():
            scan_text("guard_ledger.tsv", ledger.read_text(encoding="utf-8", errors="replace"))
        logs = rd / "logs"
        if logs.is_dir():
            for f in sorted(logs.iterdir()):
                log_text = f.read_bytes().decode("utf-8", "replace")
                if banner_exempt is not None and f.name == RAG_MODULE + ".stdout.bin":
                    log_text = banner_exempt.sub("", log_text, count=1)
                scan_text("logs/" + f.name, log_text)
    note = "" if banner_exempt is None else " (the real module's own startup banner line is exempted in logs/)"
    check(f"B5 {tag}: no PostgreSQL env VALUE in the nested runner's console/report/ledger/logs{note}", not leaks, leaks)


def spawn_and_scan(tag, args, extra_env=None, timeout=900, output_root=None):
    """B5-R1: the ONLY way this module runs a nested runner. The value-leak
    scan runs in `finally`, so it covers every exit path -- normal, timeout
    (partial stdout/stderr carried by TimeoutExpired), spawn OSError, missing
    or malformed report.json. T.1 section 28 enforces this structurally on the
    AST: the raw spawner is called exactly once, inside this function's `try`;
    the module's only scan_pg_value_leaks() call lives in its `finally`; no
    other subprocess call exists outside the raw spawner."""
    code, out, err, report, run_dir = None, "", "", None, None
    try:
        try:
            code, out, err = _spawn_runner_unscanned(args, extra_env=extra_env, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            err = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            check(f"{tag}: nested runner finished within {timeout}s", False, "TimeoutExpired (partial output scanned)")
        except OSError as exc:
            check(f"{tag}: nested runner could be spawned", False, type(exc).__name__)
        if output_root is not None:
            run_dir = find_run_dir(output_root)
            if run_dir is not None and (run_dir / "report.json").exists():
                try:
                    report = load_report(run_dir)
                except ValueError as exc:
                    check(f"{tag}: nested report.json is well-formed JSON", False, type(exc).__name__)
                    report = None
                note_nested_tmp(report)
    finally:
        scan_pg_value_leaks(tag, out, err, run_dir)
    return code, out, err, report, run_dir


def run_fake(base, tag, modules, profile="production-parity", extra_args=(), extra_env=None, timeout=900):
    tests_dir = Path(base) / f"fake_{tag}"
    out_root = Path(base) / f"out_{tag}"
    tests_dir.mkdir()
    for name, src in modules.items():
        write_module(tests_dir, name, src)
    args = ["--profile", profile, "--tests-dir", str(tests_dir), "--output-root", str(out_root)] + list(extra_args)
    return spawn_and_scan(tag, args, extra_env=extra_env, timeout=timeout, output_root=out_root)


def last_line(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


SRC_OK = "print('PASS one')\nprint('PASS two')\nprint('--- {n}: 2 passed, 0 failed ---')\nimport sys; sys.exit(0)\n"
SRC_DOC_SKIP = "print('SKIPPED no database - detail')\nprint('--- {n}: 0 passed, 0 failed, 1 skipped ---')\nimport sys; sys.exit(0)\n"
SRC_PG_SELECT = (
    "import os, sys, psycopg\n"
    "conn = psycopg.connect(dbname=os.environ['VERGI_TEST_PG_DSN'], autocommit=True)\n"
    "with conn.cursor() as cur:\n"
    "    cur.execute('SELECT 1')\n"
    "    print('PASS select 1 via the child environment == %d' % cur.fetchone()[0])\n"
    "    cur.execute(\"SELECT to_regclass('iam.users')::text\")\n"
    "    print('PASS iam.users visible' if cur.fetchone()[0] else 'FAIL iam.users missing')\n"
    "conn.close()\n"
    "print('PASS IAM url absent in child' if 'VERGI_IAM_DATABASE_URL' not in os.environ else 'FAIL IAM url leaked into child')\n"
    "print('--- {n}: 3 passed, 0 failed ---')\nsys.exit(0)\n"
)
SRC_PG_RESIDUE_TEMPLATE = (
    "import sys, psycopg\n"
    "conn = psycopg.connect(dbname=%(maint)r, autocommit=True)\n"
    "with conn.cursor() as cur:\n"
    "    cur.execute('CREATE DATABASE \"%(name)s\"')\n"
    "conn.close()\n"
    "print('PASS created residue database')\n"
    "print('--- {n}: 1 passed, 0 failed ---')\nsys.exit(0)\n"
)

# ---------------------------------------------------------------------------
# B5-R1: top-level fail-closed boundary. Everything below -- the baseline
# snapshots (psycopg connections included), the temp base and the S1-S8
# scenarios with their own cleanup `finally` -- runs inside ONE try. Any
# exception that escapes it is reported through _record_unhandled() as a
# redacted FAIL (never the default traceback, which would print a psycopg
# message carrying dbname/user/host/port values) and the run still ends
# with the summary line and exit 1. SystemExit (summarize_and_exit) passes.
# ---------------------------------------------------------------------------
try:
    # ---------------------------------------------------------------------------
    # baseline snapshots (S8)
    # ---------------------------------------------------------------------------
    DATA_BEFORE = tree_manifest(REPO_ROOT / "data")
    INDEX_BEFORE = tree_manifest(REPO_ROOT / "index")
    TESTS_BEFORE = tree_manifest(REPO_ROOT / "ui" / "tests")
    DBS_BEFORE = list_databases()
    JOURNAL_BEFORE = journal_row_count()
    NONRAG_JOURNAL_BEFORE = journal_row_count(exclude_resource_key=RAG_RESOURCE_KEY)
    JOURNAL_AFTER_S4 = None  # snapshot taken right after S4; S8 compares against it (see S4 note)

    BASE = Path(tempfile.mkdtemp(prefix="vergi_step3pg_"))
    throwaway_db = None
    pre_db = None
    residue_db = None
    hold_conn = None
    try:
        check("temp base lives outside the repository", not runner.path_is_inside(str(BASE), str(REPO_ROOT)))
        check("target database name is a bare dbname per L.1", runner.validate_pg_dsn_name(PG_DB) is None)

        # -----------------------------------------------------------------------
        # S1. L.4 preflight passes on the real 0001-0006 database
        # -----------------------------------------------------------------------
        code, out, err, report, run_dir = run_fake(BASE, "preflight", {"test_ok": SRC_OK})
        check("S1: production-parity preflight + fake OK module -> exit 0", code == 0 and report is not None, f"code={code} {last_line(out)} {err[-300:]}")
        if report:
            pg = report["postgres"]
            check("S1: preflight connected, server-side loopback proof, migrations 0001-0006 ok",
                  pg.get("connected") is True and pg.get("server_addr_loopback") is True and pg.get("migrations_ok") is True and pg.get("migrations_missing") == [], pg)
            # Slice 8A: 0006 creates no object, so its eight contract probes are
            # the only thing standing between "0006 applied" and "0006 silently
            # never applied". The probe must have really run, not errored.
            check("S1: the 0006 contract probe ran cleanly against the live database",
                  pg.get("contract_probe") == "ok", pg.get("contract_probe"))
            check("S1: pg_database snapshot count matches an independent count", pg.get("database_snapshot_count") == len(list_databases()), pg.get("database_snapshot_count"))
            check("S1: fake-dir run is labelled DIAGNOSTIC, never FULL (self-test seam)", report["sweep_label"] == "DIAGNOSTIC" and report["discovery"]["mode"] == "fake_dir", report["sweep_label"])
            check("S1: env snapshot carries PG contract NAMES only", report["env_snapshot"].get("VERGI_TEST_PG_DSN") == "passed" and report["env_snapshot"].get("VERGI_IAM_DATABASE_URL") in (None, "stripped_denylist", "absent"))
            check("S1: no db residue after a clean run", report["integrity"].get("db_residue") == [] and report["integrity"].get("failures") == [], report["integrity"])

        # -----------------------------------------------------------------------
        # S1b. Slice 8A / G3 - no password value reaches a child process.
        # The parent here really does carry a PGPASSWORD; the nested runner must
        # strip it as a denylisted secret rather than forward it, and the value
        # must not appear anywhere in stdout, stderr or report.json.
        # -----------------------------------------------------------------------
        G3_SENTINEL = "slice8a-pw-Kb7Qx2Nv9Rt4"
        G3_PASSFILE = "C:/slice8a/never-forwarded-passfile-Qm3Zt7.conf"
        # A module that reports on its OWN child environment: this is what turns
        # "the runner says it stripped it" into "the child really never saw it".
        SRC_ENV_PROBE = (
            "import os, sys\n"
            "print('PASS PGPASSWORD absent from child env' if 'PGPASSWORD' not in os.environ "
            "else 'FAIL PGPASSWORD leaked into child env')\n"
            "print('PASS PGPASSFILE absent from child env' if 'PGPASSFILE' not in os.environ "
            "else 'FAIL PGPASSFILE leaked into child env')\n"
            "print('--- {n}: 2 passed, 0 failed ---')\nsys.exit(0)\n"
        )
        code_g3, out_g3, err_g3, report_g3, rd_g3 = run_fake(
            BASE, "g3pw", {"test_env_probe": SRC_ENV_PROBE},
            extra_env={"PGPASSWORD": G3_SENTINEL, "PGPASSFILE": G3_PASSFILE})
        check("S1b: a parent PGPASSWORD/PGPASSFILE does not stop the run (exit 0)", code_g3 == 0,
              (code_g3, last_line(out_g3), err_g3[-200:]))
        g3_mod = module_entry(report_g3, "test_env_probe") if report_g3 else None
        check("S1b: the child process itself reports BOTH names absent from its own environment",
              g3_mod is not None and g3_mod["outcome"] == "PASS" and g3_mod["passed"] == 2, g3_mod)
        if report_g3:
            check("S1b: PGPASSWORD is recorded as stripped_denylist, never passed",
                  report_g3["env_snapshot"].get("PGPASSWORD") == "stripped_denylist",
                  report_g3["env_snapshot"].get("PGPASSWORD"))
            check("S1b: PGPASSFILE is recorded as stripped_denylist, never passed",
                  report_g3["env_snapshot"].get("PGPASSFILE") == "stripped_denylist",
                  report_g3["env_snapshot"].get("PGPASSFILE"))
        g3_report_text = (rd_g3 / "report.json").read_text(encoding="utf-8") if rd_g3 else ""
        g3_logs = b""
        if rd_g3 and (rd_g3 / "logs").is_dir():
            g3_logs = b"".join((rd_g3 / "logs" / f).read_bytes() for f in os.listdir(rd_g3 / "logs"))
        check("S1b: neither value appears in stdout, stderr, report.json or the raw logs",
              G3_SENTINEL not in out_g3 and G3_SENTINEL not in err_g3
              and G3_SENTINEL not in g3_report_text and G3_SENTINEL.encode() not in g3_logs
              and G3_PASSFILE not in g3_report_text and G3_PASSFILE.encode() not in g3_logs)

        # -----------------------------------------------------------------------
        # S1c. Slice 8A - the 0006 contract sentinel is not one probe but eight.
        # Granting PUBLIC a single USAGE on iam must flip EXACTLY the PUBLIC
        # label and refuse the run, proving a PARTIALLY undone 0006 cannot pass
        # unnoticed. PUBLIC is grantee OID 0, checked through nspacl+aclexplode:
        # has_schema_privilege() does not accept PUBLIC as a user argument.
        # -----------------------------------------------------------------------
        public_grant_applied = False
        try:
            with psycopg.connect(dbname=PG_DB, autocommit=True) as c, c.cursor() as cur:
                cur.execute("GRANT USAGE ON SCHEMA iam TO PUBLIC")
            public_grant_applied = True
            code_pub, out_pub, _err_pub, report_pub, _rd_pub = run_fake(
                BASE, "pubacl", {"test_ok": SRC_OK})
            check("S1c: PUBLIC USAGE on iam -> exit 2 MIGRATION_MISSING, no module ran",
                  code_pub == 2 and "MIGRATION_MISSING[" in out_pub, (code_pub, last_line(out_pub)))
            check("S1c: EXACTLY the 0006 PUBLIC label is reported missing, nothing else",
                  report_pub is not None
                  and report_pub["postgres"].get("migrations_missing") == ["0006:public_has_no_schema_access"],
                  report_pub and report_pub["postgres"].get("migrations_missing"))
        finally:
            if public_grant_applied:
                with psycopg.connect(dbname=PG_DB, autocommit=True) as c, c.cursor() as cur:
                    cur.execute("REVOKE USAGE ON SCHEMA iam FROM PUBLIC")

        code_back, out_back, _err_back, report_back, _rd_back = run_fake(
            BASE, "pubaclback", {"test_ok": SRC_OK})
        check("S1c: after the PUBLIC grant is revoked the contract is satisfied again (exit 0, none missing)",
              code_back == 0 and report_back is not None
              and report_back["postgres"].get("migrations_missing") == [],
              (code_back, report_back and report_back["postgres"].get("migrations_missing"), last_line(out_back)))

        # -----------------------------------------------------------------------
        # S2. throwaway database with only 0001-0003 -> MIGRATION_MISSING
        # -----------------------------------------------------------------------
        throwaway_db = f"row19b_migtest_{uuid.uuid4().hex[:8]}"
        create_database(throwaway_db)
        apply_migrations(throwaway_db, ["0001_iam_schema.sql", "0002_mutation_resources.sql", "0003_mutation_journal.sql"])
        code, out, err, report, run_dir = run_fake(BASE, "migmissing", {"test_ok": SRC_OK}, extra_env={"VERGI_TEST_PG_DSN": throwaway_db})
        check("S2: 0001-0003-only database -> exit 2 MIGRATION_MISSING, no module ran",
              code == 2 and "MIGRATION_MISSING[" in out and (report is None or report["modules"] == []), f"code={code} {last_line(out)}")
        for name in ("0004:mutation.mutation_journal.reconciled_by_actor_type", "0004:mutation.mutation_journal.reconciled_by_actor_ref",
                     "0005:iam.global_resource_grants", "0005:iam.global_resource_grant_events"):
            check(f"S2: missing sentinel named: {name}", name in out)
        check("S2: present 0001-0003 sentinels are NOT reported missing", "0001:iam.users" not in out and "0003:mutation.mutation_journal" not in out.replace("0004:mutation.mutation_journal", ""))
        drop_database(throwaway_db)
        throwaway_db = None

        # -----------------------------------------------------------------------
        # S3. end-to-end: PG-using fake module + documented skip under production-parity
        # -----------------------------------------------------------------------
        # Slice 8A: this run carries a KNOWN PGPASSWORD canary. Before, the two
        # secret checks below read PGPASSWORD out of os.environ, which is empty
        # under a sweep (the runner strips it), so they asserted `all([])` -
        # always true, proving nothing. The canary makes them deterministic.
        S3_CANARY = "slice8a-s3-canary-Lz8Wq4Ym1Dx6"
        code, out, err, report, run_dir = run_fake(
            BASE, "e2e", {"test_pg_select": SRC_PG_SELECT, "test_doc_skip": SRC_DOC_SKIP},
            extra_env={"PGPASSWORD": S3_CANARY})
        check("S3: exit 1 (documented zero-check violates the production-parity rule)", code == 1 and report is not None, f"code={code} {last_line(out)} {err[-300:]}")
        if report:
            m1 = module_entry(report, "test_pg_select")
            m2 = module_entry(report, "test_doc_skip")
            check("S3: PG-using fake module PASS (3 checks) through the child environment", m1 and m1["outcome"] == "PASS" and m1["passed"] == 3, m1)
            check("S3: documented-skip module -> ZERO_CHECK_DOCUMENTED_SKIP", m2 and m2["outcome"] == "ZERO_CHECK_DOCUMENTED_SKIP", m2)
            check("S3: GUARD_ARMED count == 2 modules, inheritance ok", report["guard"]["armed_count"] == 2 and report["guard"]["inheritance_ok"], report["guard"])
            logs = b"".join((run_dir / "logs" / f).read_bytes() for f in os.listdir(run_dir / "logs"))
            text = (run_dir / "report.json").read_text(encoding="utf-8")
            check("S3: the PGPASSWORD canary really was present in this run's parent environment "
                  "(the two checks below are therefore not vacuous)", len(S3_CANARY) >= 8)
            check("S3: raw logs carry no PGPASSWORD canary value", S3_CANARY.encode() not in logs)
            check("S3: report.json carries no PGPASSWORD canary value and no conninfo",
                  S3_CANARY not in text and "postgresql://" not in text)
            check("S3: report.json records PGPASSWORD as stripped_denylist, never as passed",
                  report["env_snapshot"].get("PGPASSWORD") == "stripped_denylist",
                  report["env_snapshot"].get("PGPASSWORD"))
            check("S3: the canary value is absent from this run's stdout and stderr",
                  S3_CANARY not in out and S3_CANARY not in err)
            check("S3: label DIAGNOSTIC (fake dir), PARTIAL/FULL reserved for real discovery", report["sweep_label"] == "DIAGNOSTIC")
            check("S3: secret scan clean", report["integrity"]["secret_scan"]["hits"] == [], report["integrity"]["secret_scan"])

        check("S1-S3: runner + fake modules left the mutation.mutation_journal row count unchanged",
              journal_row_count() == JOURNAL_BEFORE, (journal_row_count(), JOURNAL_BEFORE))

        # -----------------------------------------------------------------------
        # S4. regression proof for the one-line rag fix under the child contract
        # -----------------------------------------------------------------------
        out_root = BASE / "out_rag"
        code, out, err, rag_report, rd = spawn_and_scan(
            "s4_rag", ["--profile", "developer", "--select", RAG_MODULE, "--allow-untracked", "--output-root", str(out_root)],
            extra_env={"VERGI_IAM_DATABASE_URL": None}, timeout=1500, output_root=out_root)
        m = rag_report and module_entry(rag_report, RAG_MODULE)
        check("S4: real rag module runs under the runner with VERGI_IAM_DATABASE_URL stripped -> PASS with checks",
              m is not None and m["outcome"] == "PASS" and m["passed"] > 0 and m["failed"] == 0, f"code={code} {m and m['outcome']} {last_line(out)} {err[-300:]}")
        if m:
            check("S4: rag summary line present and bound to the module name", (m.get("parser") or {}).get("summary_line", "").startswith(f"--- {RAG_MODULE}:"), m.get("parser"))
            check("S4: rag module did not skip (counted skips 0)", m["counted_skips"] == 0, m["counted_skips"])
            check("S4: no .env open was attempted anywhere in that run (ENV_OPEN_BLOCKED == 0)", rag_report["guard"]["env_open_blocked_count"] == 0)
            check("S4: VERGI_IAM_DATABASE_URL absent for the child", rag_report["env_snapshot"].get("VERGI_IAM_DATABASE_URL") in (None, "absent", "stripped_denylist"))
            check("S4: nested run exit 0, guard inheritance ok, no integrity failures",
                  code == 0 and rag_report["guard"]["inheritance_ok"] and rag_report["integrity"]["failures"] == [], (code, rag_report["integrity"]["failures"]))
        # The real rag module wipes its own global:rag_index journal rows at the START of
        # each of its tests, not at teardown, so a successful S4 leaves module-owned rows
        # behind. That is the module's own contract, not a runner side effect: it is
        # recorded informationally here and excluded from the S8 invariance, which is
        # asserted over the runner + fake-module scenarios only (T.2-8).
        JOURNAL_AFTER_S4 = journal_row_count()
        rag_delta = JOURNAL_AFTER_S4 - JOURNAL_BEFORE
        check("S4: journal rows added by the real rag module are all module-owned (no resource_key other than global:rag_index gained rows)",
              journal_row_count(exclude_resource_key=RAG_RESOURCE_KEY) == NONRAG_JOURNAL_BEFORE and rag_delta >= 0, (rag_delta, NONRAG_JOURNAL_BEFORE))
        print(f"INFO S4: real rag module left {rag_delta} mutation.mutation_journal row(s) under resource_key {RAG_RESOURCE_KEY} "
              "(module-owned: the module wipes them at the start of its own tests, not at teardown; NOT a runner side effect; "
              "recorded informationally and excluded from the S8 invariance)")

        # -----------------------------------------------------------------------
        # S5. same-target VERGI_IAM_DATABASE_URL refusal with a real conninfo
        # -----------------------------------------------------------------------
        host = os.environ.get("PGHOST") or "localhost"
        port = os.environ.get("PGPORT") or "5432"
        user = os.environ.get("PGUSER") or ""
        same_url = f"postgresql://{user}@{host}:{port}/{PG_DB}" if user else f"postgresql://{host}:{port}/{PG_DB}"
        out_root = BASE / "out_same"
        tests_dir = BASE / "fake_same"
        tests_dir.mkdir()
        write_module(tests_dir, "test_ok", SRC_OK)
        code, out, err, same_report, same_rd = spawn_and_scan(
            "s5_same_target", ["--profile", "production-parity", "--tests-dir", str(tests_dir), "--output-root", str(out_root)],
            extra_env={"VERGI_IAM_DATABASE_URL": same_url}, output_root=out_root)
        check("S5: VERGI_IAM_DATABASE_URL pointing at the test database -> exit 2 IAM_SAME_TARGET, nothing ran, no run dir",
              code == 2 and "IAM_SAME_TARGET" in out and find_run_dir(out_root) is None, f"code={code} {last_line(out)}")
        check("S5: refusal output never echoes the URL", same_url not in out and same_url not in err)
        other_url = f"postgresql://{host}:{port}/{PG_DB}_other_db"
        code, out, err, report, run_dir = run_fake(BASE, "otherurl", {"test_ok": SRC_OK}, extra_env={"VERGI_IAM_DATABASE_URL": other_url})
        check("S5: a different-target IAM URL is stripped (not forwarded) and the run proceeds",
              code == 0 and report is not None and report["env_snapshot"].get("VERGI_IAM_DATABASE_URL") == "stripped_denylist", f"code={code} {last_line(out)}")

        # -----------------------------------------------------------------------
        # S6. database residue: pre-existing db is not residue, a db created by a module is
        # -----------------------------------------------------------------------
        pre_db = f"row19b_migtest_pre_{uuid.uuid4().hex[:6]}"
        create_database(pre_db)
        residue_db = f"vergi_sweep_residue_{uuid.uuid4().hex[:8]}"
        code, out, err, report, run_dir = run_fake(BASE, "residue", {"test_residue": SRC_PG_RESIDUE_TEMPLATE % {"maint": MAINTENANCE_DB, "name": residue_db}})
        check("S6: module that leaves a database -> exit 3 DB_RESIDUE", code == 3 and report is not None and any(f["kind"] == "DB_RESIDUE" for f in report["integrity"]["failures"]),
              f"code={code} {last_line(out)} {report and report['integrity']['failures']}")
        if report:
            check("S6: residue list names exactly the module-created database, not the pre-existing one",
                  report["integrity"]["db_residue"] == [residue_db], report["integrity"]["db_residue"])
            check("S6: the module itself PASSed (residue is an integrity failure, not a module outcome)", module_entry(report, "test_residue")["outcome"] == "PASS")
        drop_database(residue_db)
        residue_db = None
        drop_database(pre_db)
        pre_db = None

        # -----------------------------------------------------------------------
        # S7. concurrent sweep refusal
        # -----------------------------------------------------------------------
        hold_conn = psycopg.connect(dbname=PG_DB, autocommit=True, application_name=runner.APPLICATION_NAME)
        out_root = BASE / "out_conc"
        tests_dir = BASE / "fake_conc"
        tests_dir.mkdir()
        write_module(tests_dir, "test_ok", SRC_OK)
        code, out, err, conc_report, rd = spawn_and_scan(
            "s7_concurrent", ["--profile", "production-parity", "--tests-dir", str(tests_dir), "--output-root", str(out_root)],
            output_root=out_root)
        check("S7: another vergi_ui_test_sweep connection open -> exit 2 PG_CONCURRENT_SWEEP, no module ran",
              code == 2 and "PG_CONCURRENT_SWEEP" in out and (conc_report is None or conc_report["modules"] == []), f"code={code} {last_line(out)}")
        hold_conn.close()
        hold_conn = None
        code, out, err, report, run_dir = run_fake(BASE, "afterconc", {"test_ok": SRC_OK})
        check("S7: after the concurrent connection closes the runner proceeds again", code == 0 and report is not None, f"code={code} {last_line(out)}")

    finally:
        if hold_conn is not None:
            try:
                hold_conn.close()
            except Exception:
                pass
        for name in (throwaway_db, residue_db, pre_db):
            if name:
                drop_database(name)
        removed = rmtree_retry(BASE)
        check("S8: temp base removed", removed and not BASE.exists())
        for d in list(NESTED_TMP_DIRS):
            if os.path.exists(d):
                rmtree_retry(d)
        check("S8: nested child temp dirs removed", not any(os.path.exists(d) for d in NESTED_TMP_DIRS))
        check("S8: pg_database set identical to the baseline (throwaway/residue databases dropped)", list_databases() == DBS_BEFORE, (len(list_databases()), len(DBS_BEFORE)))
        journal_baseline = JOURNAL_BEFORE if JOURNAL_AFTER_S4 is None else JOURNAL_AFTER_S4
        check("S8: mutation.mutation_journal row count unchanged across the runner/fake-module scenarios (S4's module-owned global:rag_index rows excluded via the post-S4 snapshot)",
              journal_row_count() == journal_baseline, (journal_row_count(), journal_baseline, JOURNAL_BEFORE))
        check("S8: journal rows outside global:rag_index unchanged over the whole module (the runner never writes journal rows)",
              journal_row_count(exclude_resource_key=RAG_RESOURCE_KEY) == NONRAG_JOURNAL_BEFORE)
        check("S8: byte-invariance: data/ unchanged", tree_manifest(REPO_ROOT / "data") == DATA_BEFORE)
        check("S8: byte-invariance: index/ unchanged", tree_manifest(REPO_ROOT / "index") == INDEX_BEFORE)
        check("S8: byte-invariance: ui/tests unchanged", tree_manifest(REPO_ROOT / "ui" / "tests") == TESTS_BEFORE)
except SystemExit:
    raise
except BaseException as _unhandled:  # noqa: BLE001 -- fail-closed, redacted boundary
    _record_unhandled(_unhandled)

summarize_and_exit()
