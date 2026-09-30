# ============================================================
# PILOT READINESS ADIM 9D - ui.deadline_report REAL-POSTGRESQL
# INTEGRATION TESTS.
#
# Builds a GENUINE, coordinated canonical deadline through the real
# production CLI chain (the same chain
# `test_fact_verification_mutation_integration_postgres.py`'s P10 uses):
# generation.timeline -> promotion.timeline -> verification.fact ->
# generation.timeline -> promotion.timeline -> generation.deadline
# (calculated) -> approval.deadline. The approval writes a REAL audit
# record carrying mutation_idempotency_key/mutation_resource_key and a
# REAL `completed` journal row - exactly the evidence `ui.deadline_report`
# requires. Then exercises the report against real IAM rows, real
# journal rows and the REAL (unfaked) deadline_validator, and proves the
# report connection is read-only AT THE DATABASE LEVEL.
#
# Every case lives in a tempdir (every loaded module's `CASES_DIR`
# redirected); the real `data/` tree is byte-manifested before/after.
# The holiday calendar is a tempdir-only synthetic fixture (Prensip 18).
#
# MUST run only against a DISPOSABLE cluster (never the permanent pilot
# cluster).
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_deadline_report_integration_postgres.py
# ============================================================

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

passed = 0
failed = 0
skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def skip(label, detail=""):
    global skipped
    skipped += 1
    print(f"SKIPPED {label} - {detail}")


def summarize_and_exit():
    print(f"--- test_deadline_report_integration_postgres: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")

if not PG_DB:
    skip(
        "the entire real-PostgreSQL ui.deadline_report integration suite",
        "VERGI_TEST_PG_DSN is not set (no disposable database with migrations applied is configured "
        "for this run). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover - environment-dependent
    skip(
        "the entire real-PostgreSQL ui.deadline_report integration suite",
        f"VERGI_TEST_PG_DSN is set but `import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                             # noqa: E402
import ui.deadline_report as deadline_report                                   # noqa: E402
from ui.services import paths as _paths                                        # noqa: E402

# Imported BEFORE the CASES_DIR redirect sweep - `ui.cli_mutate` lazily
# imports these inside its dispatch functions and each carries its OWN
# module-level CASES_DIR (same reasoning as the fact-verification PG test).
import fact_verification as _pg_fact_verification                             # noqa: E402,F401
import timeline_engine as _pg_timeline_engine                                   # noqa: E402,F401
import timeline_validator as _pg_timeline_validator                             # noqa: E402,F401
import timeline_approval as _pg_timeline_approval                               # noqa: E402,F401
import fact_approval as _pg_fact_approval                                       # noqa: E402,F401
import deadline_engine as _pg_deadline_engine                                   # noqa: E402,F401
import deadline_approval as _pg_deadline_approval                               # noqa: E402,F401
import deadline_validator as _pg_deadline_validator                             # noqa: E402,F401
import deadline_calculator as _pg_deadline_calculator                           # noqa: E402,F401
import holiday_calendar_validator as _pg_holiday_calendar_validator             # noqa: E402,F401
import deadline_rule_selection_policy as _pg_deadline_rule_selection_policy     # noqa: E402,F401
from ui.services import promotion_mutation_facade as _pg_promotion_facade       # noqa: E402,F401
from ui.services import generation_mutation_facade as _pg_generation_facade     # noqa: E402,F401
from ui.services import fact_verification_mutation_facade as _pg_fv_facade      # noqa: E402,F401

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")

REAL_CASES_ROOT = Path(os.path.realpath(str(REPO_ROOT / "data" / "cases")))
REAL_CASE_0001 = REPO_ROOT / "data" / "cases" / "case_0001"

SENT_IAM_DISPLAY_NAME = "SENTINEL_IAM_DISPLAY_NAME_Av_Deneme_Kişi"


# The production report connects as `vergi_app` (Slice 8A least-privilege
# runtime role). Fixture/IAM/audit/journal preparation stays on the
# disposable bootstrap role; every REPORT connection is switched with
# `SET ROLE vergi_app` HERE, in the harness only (never in production).
APP_ROLE = "vergi_app"
PILOT_PORT = 55433


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def snapshot_real_data_tree():
    real_data_dir = REPO_ROOT / "data"
    out = {}
    for path in real_data_dir.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(real_data_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(real_data_dir))] = "<unreadable>"
    return out


def discover_cases_dir_holders():
    holders = []
    for module in list(sys.modules.values()):
        if getattr(module, "__file__", None) is None:
            continue
        candidate = getattr(module, "CASES_DIR", None)
        if candidate is None:
            continue
        try:
            if Path(os.path.realpath(str(candidate))) == REAL_CASES_ROOT:
                holders.append(module)
        except Exception:
            continue
    return holders


def db_state_snapshot():
    """Full content of every table the report could conceivably touch."""
    conn = pg_connect()
    try:
        out = {}
        with conn.cursor() as cur:
            for table, order in (
                ("mutation.mutation_journal", "id"),
                ("mutation.mutation_resources", "resource_key"),
                ("iam.users", "id"),
                ("iam.case_assignments", "id"),
            ):
                cur.execute(f"SELECT * FROM {table} ORDER BY {order}")
                out[table] = [tuple(str(v) for v in row) for row in cur.fetchall()]
        return out
    finally:
        conn.close()


# ----------------------------------------------------------------
# Preflight.
# ----------------------------------------------------------------
_preflight = pg_connect()
try:
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('iam.users'), to_regclass('iam.case_assignments'), "
            "to_regclass('mutation.mutation_resources'), to_regclass('mutation.mutation_journal')"
        )
        row = cur.fetchone()
        check("preflight: iam + mutation schemas exist", all(row))
        cur.execute("SELECT inet_server_port(), session_user")
        _server_port, BOOTSTRAP_ROLE = cur.fetchone()
        check(f"preflight: target is NOT the permanent pilot port {PILOT_PORT}", _server_port != PILOT_PORT,
              f"port={_server_port!r}")
        check(f"preflight: bootstrap session role is not {APP_ROLE} (else SET ROLE would be vacuous)",
              BOOTSTRAP_ROLE != APP_ROLE, f"session_user={BOOTSTRAP_ROLE!r}")
        cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
        _app_row = cur.fetchone()
        check(f"preflight: role {APP_ROLE} exists and is NOT a superuser (0006 runtime role)",
              _app_row is not None and _app_row[0] is False, f"row={_app_row!r}")
        APP_SELECT_GRANTS = {}
        for _table in ("iam.users", "iam.case_assignments", "iam.user_roles", "mutation.mutation_journal"):
            if _app_row is None:
                APP_SELECT_GRANTS[_table] = None
                continue
            cur.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", (APP_ROLE, _table))
            APP_SELECT_GRANTS[_table] = cur.fetchone()[0]
        print(f"evidence: {APP_ROLE} SELECT grants = {APP_SELECT_GRANTS!r}")
        check(f"preflight: {APP_ROLE} holds SELECT on iam.users / iam.case_assignments / iam.user_roles / "
              "mutation.mutation_journal", all(v is True for v in APP_SELECT_GRANTS.values()),
              f"{APP_SELECT_GRANTS!r}")
        if _app_row is not None:
            cur.execute("SELECT has_table_privilege(%s, 'mutation.mutation_resources', 'INSERT')", (APP_ROLE,))
            APP_HAS_INSERT_ON_RESOURCES = cur.fetchone()[0]
        else:
            APP_HAS_INSERT_ON_RESOURCES = None
        check(f"preflight: {APP_ROLE} normally holds INSERT on mutation.mutation_resources (read-only probe "
              "target - a refusal there can only come from the read-only transaction)",
              APP_HAS_INSERT_ON_RESOURCES is True, f"{APP_HAS_INSERT_ON_RESOURCES!r}")
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run (half-migrated database, pilot port, or missing vergi_app ACL).")
    summarize_and_exit()


def app_role_connect():
    """Bootstrap-role login, then `SET ROLE vergi_app` on the REAL
    connection (not through the recording wrapper), identity checked, and
    handed back IDLE with autocommit=False (production shape) so the
    report's `conn.read_only = True` is accepted."""
    conn = psycopg.connect(dbname=PG_DB, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET ROLE {APP_ROLE}")
            cur.execute("SELECT current_user, session_user")
            identity = cur.fetchone()
        if identity != (APP_ROLE, BOOTSTRAP_ROLE):
            raise AssertionError(f"SET ROLE did not take effect: {identity!r}")
        conn.autocommit = False
    except BaseException:
        conn.close()
        raise
    return conn, identity


def reset_role_and_close(conn):
    """Harness-side cleanup: prove the role survived the whole run, then
    RESET ROLE and close. The real close ALWAYS happens."""
    evidence = {"at_close": None, "after_reset": None, "error": None}
    try:
        if not conn.closed:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT current_user, session_user")
                evidence["at_close"] = cur.fetchone()
            conn.rollback()
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("RESET ROLE")
                cur.execute("SELECT current_user, session_user")
                evidence["after_reset"] = cur.fetchone()
    except Exception as error:  # pragma: no cover - recorded, asserted below
        evidence["error"] = repr(error)
    finally:
        conn.close()
    return evidence


# Negative ACL control: under the switched role, a table vergi_app has
# NO privilege on must be refused with 42501 - proves the ACL is really
# being applied, not just that current_user carries a label.
_neg_conn, _neg_identity = app_role_connect()
try:
    try:
        with _neg_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM iam.security_events LIMIT 1")
        _neg_sqlstate = None
    except psycopg.Error as _neg_error:
        _neg_sqlstate = _neg_error.sqlstate
finally:
    _neg_evidence = reset_role_and_close(_neg_conn)
check(f"A0 under SET ROLE {APP_ROLE}: SELECT on iam.security_events -> 42501 insufficient_privilege",
      _neg_sqlstate == "42501", f"sqlstate={_neg_sqlstate!r}")
check("A0b the negative-control connection was RESET ROLE'd back to the bootstrap role",
      _neg_evidence["after_reset"] == (BOOTSTRAP_ROLE, BOOTSTRAP_ROLE) and _neg_evidence["error"] is None,
      f"{_neg_evidence!r}")

_ACTORS = {"lawyer": 911, "analyst": 912, "other_lawyer": 913, "disabled_lawyer": 914, "revoked_lawyer": 915}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE, display_name = EXCLUDED.display_name",
                (user_id, SENT_IAM_DISPLAY_NAME),
            )
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('iam.users', 'id'), "
            "GREATEST((SELECT max(id) FROM iam.users), 1))"
        )
finally:
    _seed.close()


def seed_assignment(user_id, case_id, role):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO iam.case_assignments (user_id, case_id, role) VALUES (%s, %s, %s)",
                (user_id, case_id, role),
            )
    finally:
        conn.close()


def revoke_assignment(user_id, case_id):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE iam.case_assignments SET revoked_at = now() "
                "WHERE user_id = %s AND case_id = %s AND revoked_at IS NULL",
                (user_id, case_id),
            )
    finally:
        conn.close()


def set_disabled(user_id, disabled):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE iam.users SET disabled = %s WHERE id = %s", (disabled, user_id))
    finally:
        conn.close()


# ----------------------------------------------------------------
# Tempdir redirect (CASES_DIR holders + rule-policy DATA_DIR + a
# synthetic, tempdir-only holiday calendar).
# ----------------------------------------------------------------
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_deadline_report_pg_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)
_TMP_OUT = _TMP_ROOT / "out"
_TMP_OUT.mkdir()

_cases_dir_holders = discover_cases_dir_holders()
check(
    "the CASES_DIR redirect sweep found ui.services.paths and every chain module",
    all(
        any(getattr(m, "__name__", "") == name for m in _cases_dir_holders)
        for name in (
            "ui.services.paths", "fact_verification", "timeline_engine", "timeline_validator",
            "timeline_approval", "fact_approval", "deadline_engine", "deadline_approval",
            "deadline_validator",
        )
    ),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
_original_cases_dirs = [(m, m.CASES_DIR) for m in _cases_dir_holders]
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

_original_rule_policy_data_dir = _pg_deadline_rule_selection_policy.DATA_DIR
_pg_deadline_rule_selection_policy.DATA_DIR = _TMP_ROOT / "data"

_original_holiday_calendar_path = _pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH
_calendar_dir = _TMP_ROOT / "holiday_calendar"
_calendar_dir.mkdir()
_calendar_path = _calendar_dir / "holiday_calendar.json"
_calendar_doc = {
    "schema_version": 1,
    "calendar_id": "tr_official_holiday_calendar_v1",
    "calendar_version": 1,
    "effective_from": "2026-01-01",
    "jurisdiction": "TR",
    "weekend_policy": {"non_working_weekdays": [5, 6], "notes": None},
    "half_day_policy": "not_decided",
    "years": [
        {
            "year": 2026,
            "verified": True,
            "verification_ref": "adim9d_test_only_synthetic_verification_ref",
            "source_refs": [
                {"source_kind": "test_fixture", "citation": "Adım 9D test-only synthetic calendar - NOT a real legal source.", "url": None},
            ],
            "holidays": [],
        },
    ],
    "governance": {"change_approval": "test-only", "verification_authority": "test-only", "notes": None},
    "notes": "Adım 9D test-only synthetic calendar (Prensip 18) - never written to the real data/ tree.",
}
_pg_holiday_calendar_validator.attach_fixture_verification(_calendar_doc, seed="adim9d_test_only_synthetic")
_calendar_check = _pg_holiday_calendar_validator.validate_holiday_calendar(calendar=_calendar_doc)
if not _calendar_check["valid"]:
    raise AssertionError(f"synthetic holiday calendar fixture is itself invalid: {_calendar_check['errors']!r}")
with open(_calendar_path, "w", encoding="utf-8") as _calendar_file:
    json.dump(_calendar_doc, _calendar_file, ensure_ascii=False, indent=2)
_pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH = _calendar_path

_real_data_before = snapshot_real_data_tree()
RUN_TOKEN = uuid.uuid4().hex[:8]


def copy_case_0001(case_id):
    dst = _TMP_CASES / case_id
    shutil.copytree(REAL_CASE_0001, dst)
    for path in dst.rglob("*"):
        if path.is_file() and (path.suffix in (".json", ".pending", ".bak") or path.name.endswith(".json.pending")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "case_0001" in text:
                path.write_text(text.replace("case_0001", case_id), encoding="utf-8")
    return dst


def make_single_fact_deadline_case(case_id):
    """Trimmed case_0001 copy: exactly one document (`ihbarname_001`) and
    exactly one fact (the notification-date fact, 2026-02-10) - same
    construction as the fact-verification PG test's P10."""
    dst = copy_case_0001(case_id)
    for other_doc in ("dava_dilekcesi_001", "vir_001"):
        other_dir = dst / "documents" / other_doc
        if other_dir.exists():
            shutil.rmtree(other_dir)
    facts_path = dst / "documents" / "ihbarname_001" / "extractions" / "facts.json"
    extraction = json.loads(facts_path.read_text(encoding="utf-8"))
    keep_fact_id = "fact_ihbarname_001_llm_v1_2_1_20260901_122652_008"
    trimmed = [f for f in extraction["facts"] if f["fact_id"] == keep_fact_id]
    if len(trimmed) != 1:
        raise AssertionError(f"expected exactly 1 kept fact {keep_fact_id!r}")
    extraction["facts"] = trimmed
    facts_path.write_text(json.dumps(extraction, ensure_ascii=False, indent=2), encoding="utf-8")
    case_path = dst / "case.json"
    case_data = json.loads(case_path.read_text(encoding="utf-8"))
    case_data["case_document_refs"] = [
        r for r in case_data.get("case_document_refs", []) if r.get("document_id") == "ihbarname_001"
    ]
    case_path.write_text(json.dumps(case_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def authz_conn_factory():
    return psycopg.connect(dbname=PG_DB)


def mutation_conn_factory():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def run_cli(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_mutate.main(
        argv, authz_conn_factory=authz_conn_factory, mutation_conn_factory=mutation_conn_factory,
        stdout=stdout, stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def parse_kv(out, key):
    prefix = key + "="
    for line in out.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    raise AssertionError(f"key {key!r} not found in real CLI output: {out!r}")


class _RecordingCursor:
    def __init__(self, real, log):
        self._real = real
        self._log = log

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, *exc_info):
        return self._real.__exit__(*exc_info)

    def execute(self, sql, params=None):
        self._log.append(sql)
        return self._real.execute(sql, params)

    def fetchone(self):
        return self._real.fetchone()

    def fetchall(self):
        return self._real.fetchall()


class RecordingConn:
    """Wraps a REAL psycopg connection (production shape: autocommit
    False) and records every statement the report issues."""

    def __init__(self, real, handoff_identity):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "log", [])
        object.__setattr__(self, "commit_calls", 0)
        object.__setattr__(self, "handoff_identity", handoff_identity)
        object.__setattr__(self, "close_evidence", None)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)

    def cursor(self):
        return _RecordingCursor(self._real.cursor(), self.log)

    def commit(self):
        object.__setattr__(self, "commit_calls", self.commit_calls + 1)
        return self._real.commit()

    def close(self):
        # Harness-only: identity-at-close + RESET ROLE on the REAL
        # connection (not logged - `log` holds only report statements).
        if self.close_evidence is None:
            object.__setattr__(self, "close_evidence", reset_role_and_close(self._real))
        else:
            self._real.close()


_report_conns = []


def report_conn_factory():
    real, identity = app_role_connect()
    conn = RecordingConn(real, identity)
    _report_conns.append(conn)
    return conn


def all_report_conns_ran_as_app_role():
    """Every report connection: handed off as (vergi_app, bootstrap),
    still (vergi_app, bootstrap) when the report closed it, RESET back to
    (bootstrap, bootstrap), no cleanup error, really closed."""
    return bool(_report_conns) and all(
        c.handoff_identity == (APP_ROLE, BOOTSTRAP_ROLE)
        and c.close_evidence is not None
        and c.close_evidence["at_close"] == (APP_ROLE, BOOTSTRAP_ROLE)
        and c.close_evidence["after_reset"] == (BOOTSTRAP_ROLE, BOOTSTRAP_ROLE)
        and c.close_evidence["error"] is None
        and c._real.closed
        for c in _report_conns
    )


def run_report(case_id, actor, *extra):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = deadline_report.main(
        ["--case", case_id, "--actor-user-id", str(actor), *extra],
        conn_factory=report_conn_factory, stdout=stdout, stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def refused(code, out, err, expected):
    return code == 1 and out == "" and err == f"RAPOR REDDEDİLDİ: {expected}\n"


try:
    # ============================================================
    # SETUP - genuine coordinated chain to a calculated canonical.
    # ============================================================
    case_id = f"rptpg{RUN_TOKEN}a"
    case_dir = make_single_fact_deadline_case(case_id)
    lawyer = str(_ACTORS["lawyer"])
    seed_assignment(_ACTORS["lawyer"], case_id, "lawyer")
    DOC = "ihbarname_001"

    code, out, err = run_cli(["generation", "--case", case_id, "--row-key", "timeline", "--actor-user-id", lawyer])
    digest = parse_kv(out, "input_digest")
    code, out, err = run_cli(["generation", "--case", case_id, "--row-key", "timeline", "--actor-user-id", lawyer,
                              "--apply", "--expected-input-digest", digest])
    check("S1 generation.timeline apply (first pass) exits 0", code == 0, f"out={out!r} err={err!r}")
    code, out, err = run_cli(["promotion", "--case", case_id, "--row-key", "timeline", "--actor-user-id", lawyer])
    pending_hash = parse_kv(out, "pending_hash")
    code, out, err = run_cli(["promotion", "--case", case_id, "--row-key", "timeline", "--actor-user-id", lawyer,
                              "--approve", "--expected-hash", pending_hash])
    check("S2 promotion.timeline apply (first pass) exits 0", code == 0, f"out={out!r} err={err!r}")
    anchor_event_id = json.loads((case_dir / "timeline" / "timeline.json").read_bytes())["events"][0]["event_id"]

    facts_path = case_dir / "documents" / DOC / "extractions" / "facts.json"
    fact_id = json.loads(facts_path.read_bytes())["facts"][0]["fact_id"]
    code, out, err = run_cli([
        "verification", "--case", case_id, "--document", DOC, "--fact-id", fact_id,
        "--actor-user-id", lawyer, "--apply", "--target-state", "verified",
        "--expected-hash", hashlib.sha256(facts_path.read_bytes()).hexdigest(), "--evidence-ref", DOC,
    ])
    check("S3 verification.fact apply (anchor fact -> verified) exits 0", code == 0, f"out={out!r} err={err!r}")

    code, out, err = run_cli(["generation", "--case", case_id, "--row-key", "timeline", "--actor-user-id", lawyer])
    digest = parse_kv(out, "input_digest")
    code, out, err = run_cli(["generation", "--case", case_id, "--row-key", "timeline", "--actor-user-id", lawyer,
                              "--apply", "--expected-input-digest", digest])
    code, out, err = run_cli(["promotion", "--case", case_id, "--row-key", "timeline", "--actor-user-id", lawyer])
    pending_hash = parse_kv(out, "pending_hash")
    code, out, err = run_cli(["promotion", "--case", case_id, "--row-key", "timeline", "--actor-user-id", lawyer,
                              "--approve", "--expected-hash", pending_hash])
    check("S4 promotion.timeline apply (post-verification) exits 0", code == 0, f"out={out!r} err={err!r}")

    code, out, err = run_cli(["generation", "--case", case_id, "--row-key", "deadline", "--anchor", anchor_event_id,
                              "--actor-user-id", lawyer])
    digest = parse_kv(out, "input_digest")
    code, out, err = run_cli([
        "generation", "--case", case_id, "--row-key", "deadline", "--anchor", anchor_event_id,
        "--actor-user-id", lawyer, "--apply", "--expected-input-digest", digest,
        "--judicial-recess-applicable", "no",
        # SYNTHETIC TEST value only - not a real lawyer/client declaration.
        "--stopping-event-status", "none",
        "--stopping-event-attestation-ref", "SENTINEL-ADIM9D-SYNTHETIC-ATTESTATION",
    ])
    check("S5 generation.deadline apply (anchor verified) exits 0", code == 0, f"out={out!r} err={err!r}")

    code, out, err = run_cli(["approval", "--case", case_id, "--row-key", "deadline", "--actor-user-id", lawyer])
    pending_hash = parse_kv(out, "pending_hash")
    code, out, err = run_cli(["approval", "--case", case_id, "--row-key", "deadline", "--actor-user-id", lawyer,
                              "--approve", "--expected-hash", pending_hash])
    check("S6 approval.deadline apply exits 0", code == 0, f"out={out!r} err={err!r}")

    canonical_path = case_dir / "deadlines" / "deadline.json"
    canonical_raw = canonical_path.read_bytes()
    canonical_sha = hashlib.sha256(canonical_raw).hexdigest()
    canonical_doc = json.loads(canonical_raw)
    deadline = canonical_doc["deadlines"][0]
    check("S7 the REAL canonical is calculated / verified anchor / 2026-03-12 / not_evaluated / stopping none",
          deadline["calculation_state"] == "calculated" and deadline["anchor_verification_state"] == "verified"
          and deadline["calculated_deadline"] == "2026-03-12" and deadline["expiry_state"] == "not_evaluated"
          and deadline["stopping_event_status"] == "none", f"{deadline!r}")

    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT idempotency_key, observed_post_hash FROM mutation.mutation_journal "
                "WHERE resource_key = %s AND action_family = 'approval.deadline' AND state = 'completed'",
                (f"case:{case_id}",),
            )
            approval_rows = cur.fetchall()
    finally:
        conn.close()
    reviews_dir = case_dir / "deadlines" / "reviews"
    matching_audit_paths = []
    for path in sorted(reviews_dir.glob("*.approval.json")):
        record = json.loads(path.read_bytes())
        if record.get("canonical_sha256") == canonical_sha and record.get("mutation_idempotency_key"):
            matching_audit_paths.append(path)
    check("S8 exactly one REAL completed approval.deadline journal row, bound to the canonical sha and to "
          "exactly one REAL audit record carrying the same idempotency key",
          len(approval_rows) == 1 and approval_rows[0][1] == canonical_sha and len(matching_audit_paths) == 1
          and json.loads(matching_audit_paths[0].read_bytes())["mutation_idempotency_key"] == approval_rows[0][0],
          f"rows={approval_rows!r} audits={matching_audit_paths!r}")
    matching_audit_path = matching_audit_paths[0] if matching_audit_paths else None

    # ------------------------------------------------------------
    # ALL harness-side IAM writes happen HERE, before the read-only
    # snapshot below - so D1 measures ONLY what the report runs do.
    # ------------------------------------------------------------
    other_case = f"rptpg{RUN_TOKEN}b"
    copy_case_0001(other_case)
    legacy_case = f"rptpg{RUN_TOKEN}c"
    copy_case_0001(legacy_case)
    seed_assignment(_ACTORS["analyst"], case_id, "analyst")
    seed_assignment(_ACTORS["other_lawyer"], other_case, "lawyer")
    seed_assignment(_ACTORS["disabled_lawyer"], case_id, "lawyer")
    set_disabled(_ACTORS["disabled_lawyer"], True)
    seed_assignment(_ACTORS["revoked_lawyer"], case_id, "lawyer")
    revoke_assignment(_ACTORS["revoked_lawyer"], case_id)
    seed_assignment(_ACTORS["lawyer"], legacy_case, "lawyer")

    db_before_reports = db_state_snapshot()

    # ============================================================
    # R - report against the genuine canonical.
    # ============================================================
    expected = (
        "VERGİ AI - DEADLINE AVUKAT RAPORU (salt-okunur, onaylı canonical kayıt)\n"
        f"case_id: {case_id}\n"
        f"deadline_id: {deadline['deadline_id']}\n"
        f"anchor_event_id: {anchor_event_id}\n"
        "anchor_date (başlangıç olayı / tebliğ tarihi): 2026-02-10\n"
        "anchor_verification_state: verified\n"
        f"rule_id: {deadline['rule_id']}\n"
        "calculated_deadline: 2026-03-12\n"
        "calculation_state: calculated\n"
        f"requires_human_review: {'EVET' if deadline['requires_human_review'] else 'HAYIR'}\n"
        "stopping_event_status: none\n"
        "stopping_event_attestation_ref: VAR\n"
        f"canonical_sha256: {canonical_sha}\n"
        "Süre aşımı (expiry) DEĞERLENDİRİLMEDİ.\n"
        "Bu çıktı hukuki karar değildir; avukat tarafından doğrulanmalıdır.\n"
    )
    code, out, err = run_report(case_id, _ACTORS["lawyer"])
    check("R1 assigned lawyer: exit 0, stdout EXACTLY the allowlisted report (REAL validator, REAL journal, "
          "REAL audit)", code == 0 and err == "" and out == expected, f"code={code} out={out!r} err={err!r}")
    check("R2 no IAM display name / attestation text / notes / description leaked",
          "SENTINEL" not in out + err and all(
              str(v) not in out for v in (deadline.get("description"), deadline.get("notes"), canonical_doc.get("notes"))
              if v))
    last = _report_conns[-1]
    check("R3 every statement the report issued on the REAL connection is a SELECT; commit() never called",
          last.log and all(s.lstrip().upper().startswith("SELECT") for s in last.log) and last.commit_calls == 0,
          f"{last.log!r}")
    check("R4 the report connection was closed", last.closed)
    print(f"evidence: R1 report connection handoff (current_user, session_user) = {last.handoff_identity!r}, "
          f"at close = {last.close_evidence and last.close_evidence['at_close']!r}, "
          f"after RESET ROLE = {last.close_evidence and last.close_evidence['after_reset']!r}")
    check(f"R1b the successful R1 report ran ENTIRELY as current_user={APP_ROLE} / session_user=bootstrap "
          "(identity at handoff AND at close), then RESET ROLE'd",
          len(_report_conns) == 1 and all_report_conns_ran_as_app_role(),
          f"handoff={last.handoff_identity!r} close={last.close_evidence!r} bootstrap={BOOTSTRAP_ROLE!r}")

    ro_probe_holder = []

    def _ro_probe_factory():
        real, identity = app_role_connect()
        ro_probe_holder.append(identity)
        return real

    ro_conn = deadline_report._open_read_only_connection(_ro_probe_factory)
    ro_sqlstate = None
    ro_error_type = None
    try:
        try:
            with ro_conn.cursor() as cur:
                cur.execute("INSERT INTO mutation.mutation_resources (resource_key) VALUES (%s)",
                            (f"case:rpt_readonly_probe_{RUN_TOKEN}",))
        except psycopg.Error as ro_error:
            ro_sqlstate = ro_error.sqlstate
            ro_error_type = type(ro_error).__name__
    finally:
        ro_close_evidence = reset_role_and_close(ro_conn)
    print(f"evidence: R5 probe identity={ro_probe_holder!r} INSERT sqlstate={ro_sqlstate!r} "
          f"error_type={ro_error_type!r} close={ro_close_evidence!r}")
    check(f"R5 the report's read-only connection, as {APP_ROLE} (which HOLDS INSERT on "
          "mutation.mutation_resources), refuses INSERT with SQLSTATE 25006 ReadOnlySqlTransaction "
          "- NOT 42501 permission denied",
          ro_probe_holder == [(APP_ROLE, BOOTSTRAP_ROLE)] and ro_sqlstate == "25006"
          and ro_error_type == "ReadOnlySqlTransaction"
          and ro_close_evidence["at_close"] == (APP_ROLE, BOOTSTRAP_ROLE)
          and ro_close_evidence["after_reset"] == (BOOTSTRAP_ROLE, BOOTSTRAP_ROLE)
          and ro_close_evidence["error"] is None,
          f"identity={ro_probe_holder!r} sqlstate={ro_sqlstate!r} type={ro_error_type!r} close={ro_close_evidence!r}")

    target = _TMP_OUT / "rapor.txt"
    code, out, err = run_report(case_id, _ACTORS["lawyer"], "--output", str(target))
    written = target.read_bytes() if target.exists() else b""
    check("R6 --output: file bytes == stdout-mode report (UTF-8, no BOM, LF only)",
          code == 0 and written == expected.encode("utf-8") and b"\r" not in written
          and not written.startswith(b"\xef\xbb\xbf"), f"code={code} out={out!r} err={err!r}")

    # ============================================================
    # Z - authorization with REAL IAM rows.
    # ============================================================
    code, out, err = run_report(case_id, 999999)
    check("Z1 nonexistent actor -> access_denied", refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    code, out, err = run_report(case_id, _ACTORS["analyst"])
    check("Z2 active ANALYST assignment -> access_denied (lawyer only)",
          refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    code, out, err = run_report(case_id, _ACTORS["other_lawyer"])
    check("Z3 lawyer assigned to ANOTHER case -> access_denied", refused(code, out, err, "access_denied"),
          f"{code} {out!r} {err!r}")

    code, out, err = run_report(case_id, _ACTORS["disabled_lawyer"])
    check("Z4 disabled actor with an active lawyer assignment -> access_denied",
          refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    code, out, err = run_report(case_id, _ACTORS["revoked_lawyer"])
    check("Z5 revoked lawyer assignment -> access_denied", refused(code, out, err, "access_denied"),
          f"{code} {out!r} {err!r}")

    # ============================================================
    # P - audit/journal proof against the real artefacts.
    # ============================================================
    duplicate = reviews_dir / "zz_duplicate_of_matching.approval.json"
    shutil.copyfile(matching_audit_path, duplicate)
    code, out, err = run_report(case_id, _ACTORS["lawyer"])
    check("P1 a second audit matching the same completed journal row -> ambiguous_approval",
          refused(code, out, err, "ambiguous_approval"), f"{code} {out!r} {err!r}")
    duplicate.unlink()

    parked = _TMP_ROOT / "parked.approval.json"
    shutil.move(str(matching_audit_path), str(parked))
    code, out, err = run_report(case_id, _ACTORS["lawyer"])
    check("P2 matching audit record removed -> approval_not_proven",
          refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")
    shutil.move(str(parked), str(matching_audit_path))

    canonical_path.write_bytes(canonical_raw + b"\n")
    code, out, err = run_report(case_id, _ACTORS["lawyer"])
    check("P3 canonical bytes changed after approval -> approval_not_proven (no audit/journal binds them)",
          refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")
    canonical_path.write_bytes(canonical_raw)

    code, out, err = run_report(legacy_case, _ACTORS["lawyer"])
    check("P4 case_0001-shaped legacy approval (no journal row, no mutation keys) -> approval_not_proven",
          refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    code, out, err = run_report(case_id, _ACTORS["lawyer"])
    check("P5 after restoring every artefact the report succeeds again, unchanged",
          code == 0 and out == expected, f"code={code} out={out!r} err={err!r}")

    check("D1 every report run left mutation.* and iam.* table content byte-identical (read-only)",
          db_state_snapshot() == db_before_reports)
    check(f"D2 EVERY report run so far (R/Z/P, success and refusal) ran as {APP_ROLE} and was RESET ROLE'd",
          all_report_conns_ran_as_app_role(), f"n={len(_report_conns)}")
    check("D3 every statement of every report run was a SELECT, and no report ever called commit()",
          all(c.log and all(s.lstrip().upper().startswith("SELECT") for s in c.log) and c.commit_calls == 0
              for c in _report_conns))

    # ============================================================
    # J - an unresolved journal row blocks the report (harness-inserted,
    #     then removed; runs LAST so D1 above is unaffected).
    # ============================================================
    probe_key = hashlib.sha256(f"adim9d-probe-{RUN_TOKEN}".encode()).hexdigest()
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO mutation.mutation_journal (resource_key, action_family, actor_user_id, actor_label, "
                "target_ref, idempotency_key, request_fingerprint, state) "
                "VALUES (%s, 'generation.deadline', %s, %s, 'deadline.pending', %s, %s, 'prepared')",
                (f"case:{case_id}", _ACTORS["lawyer"], str(_ACTORS["lawyer"]), probe_key, probe_key),
            )
    finally:
        conn.close()
    try:
        code, out, err = run_report(case_id, _ACTORS["lawyer"])
        check("J1 a prepared journal row on the case resource -> journal_unresolved_mutation",
              refused(code, out, err, "journal_unresolved_mutation"), f"{code} {out!r} {err!r}")
    finally:
        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM mutation.mutation_journal WHERE idempotency_key = %s", (probe_key,))
        finally:
            conn.close()
    code, out, err = run_report(case_id, _ACTORS["lawyer"])
    check("J2 once the probe row is gone the report succeeds again", code == 0 and out == expected,
          f"code={code} out={out!r} err={err!r}")
    check(f"J3 the J-phase report runs also ran as {APP_ROLE} and were RESET ROLE'd",
          all_report_conns_ran_as_app_role(), f"n={len(_report_conns)}")
    check("D4 after the self-cleaning J probe, mutation.* and iam.* content equals the pre-report snapshot",
          db_state_snapshot() == db_before_reports)

finally:
    for _m, _value in _original_cases_dirs:
        _m.CASES_DIR = _value
    _pg_deadline_rule_selection_policy.DATA_DIR = _original_rule_policy_data_dir
    _pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH = _original_holiday_calendar_path
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

check("G1 real data/ tree byte-identical before/after (incl. ignored data/cases)",
      snapshot_real_data_tree() == _real_data_before)
check("G2 no LLM client module imported", not any(m in sys.modules for m in ("anthropic", "openai")))

summarize_and_exit()
