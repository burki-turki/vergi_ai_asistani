# ============================================================
# ADIM 10 B YOLU - REAL, END-TO-END PostgreSQL INTEGRATION PROOF for
# `generation.fact_manual` (ui/services/manual_fact_mutation_facade.py +
# manual_fact_mutation_adapters.py + the ui.cli_mutate `manual-fact`
# subcommand + ui/reconciliation_operator.py), exact-scope §5.3:
#   G-P1  manual-fact -> promotion.fact -> verification.fact ->
#         generation/promotion.timeline -> generation/approval.deadline
#         -> ui.deadline_report, all through the REAL CLI, zero mocking
#   G-P2  journal order + states
#   G-N1  K-3 + K-16: a hand-edited verified pending is refused BEFORE any
#         promotion journal row; the case is not gated
#   G-N2  second apply / foreign pending (N-L4 journal state over REAL SQL)
#   G-N3  real merged registry = 53 + gather_evidence() on the real row
#   G-N4  a second document's manual notification date next to an
#         existing verified one: no automatic anchor selection (K-19 STOP
#         condition if violated)
#   G-A   crash cell (a) through the REAL reconciliation operator ->
#         failed -> --attempt 2 completes (N-L7 message over REAL SQL)
#
# WHAT IS NOT REAL: the case tree (re-identified copies of
# data/cases/case_0001 under a fresh tempdir via a CASES_DIR redirect
# sweep - the repository's own data/ tree is NEVER written, proven
# byte-for-byte at the end) and a tempdir-isolated synthetic holiday
# calendar (Prensip 18).
#
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_manual_fact_mutation_integration_postgres.py
# ============================================================

import datetime as _dt
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
    print(
        f"--- test_manual_fact_mutation_integration_postgres: {passed} passed, "
        f"{failed} failed, {skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip(
        "the entire real-PostgreSQL manual-fact integration suite",
        "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip(
        "the entire real-PostgreSQL manual-fact integration suite",
        f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                              # noqa: E402
import ui.deadline_report as deadline_report                                    # noqa: E402
import ui.reconciliation_operator as op                                        # noqa: E402
from ui.services import mutation_registry as mr                                # noqa: E402
from ui.services import paths as _paths                                        # noqa: E402

# Imported BEFORE the CASES_DIR redirect sweep - `ui.cli_mutate` lazily
# imports these inside its dispatch functions and each carries its OWN
# module-level CASES_DIR (same reasoning as the fact-verification PG test).
import manual_fact_entry_engine as _pg_manual_fact_engine                      # noqa: E402,F401
import case_fact_validator as _pg_case_fact_validator                          # noqa: E402,F401
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
from ui.services import manual_fact_mutation_facade as _pg_manual_fact_facade   # noqa: E402,F401
from ui.services import manual_fact_mutation_adapters as _pg_manual_fact_adapters  # noqa: E402,F401
from ui.services import promotion_mutation_facade as _pg_promotion_facade       # noqa: E402,F401
from ui.services import generation_mutation_facade as _pg_generation_facade     # noqa: E402,F401
from ui.services import fact_verification_mutation_facade as _pg_fv_facade      # noqa: E402,F401

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


_JOURNAL_COLUMNS = (
    "id, resource_key, action_family, actor_user_id, actor_label, target_ref, target_state, state, "
    "pre_hash, pre_revision, expected_post_hash, observed_post_hash, resolution_code, idempotency_key, "
    "request_fingerprint, reconciled_by_actor_type, reconciled_by_actor_ref"
)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_JOURNAL_COLUMNS} FROM mutation.mutation_journal WHERE resource_key = %s ORDER BY id",
                (resource_key,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def entry_of(row):
    return mr.JournalEntrySnapshot(
        journal_id=row["id"], resource_key=row["resource_key"], action_family=row["action_family"],
        target_ref=row["target_ref"], target_state=row["target_state"], pre_hash=row["pre_hash"],
        pre_revision=row["pre_revision"], expected_post_hash=row["expected_post_hash"], state=row["state"],
        idempotency_key=row["idempotency_key"], request_fingerprint=row["request_fingerprint"],
        actor_label=row["actor_label"],
    )


# ----------------------------------------------------------------
# Preflight (0001-0006).
# ----------------------------------------------------------------

_preflight = pg_connect()
try:
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('iam.users'), to_regclass('mutation.mutation_resources'), "
            "to_regclass('mutation.mutation_journal'), to_regclass('iam.global_resource_grants')"
        )
        row = cur.fetchone()
    check("preflight: iam + mutation schemas exist (migrations applied)", all(row))
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run against a half-migrated database.")
    summarize_and_exit()

_ACTORS = {"lawyer": 701, "analyst": 702}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"manual-fact-actor-{user_id}"),
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


# ----------------------------------------------------------------
# CASES_DIR redirect sweep + synthetic holiday calendar.
# ----------------------------------------------------------------

_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))
REAL_CASE_0001 = REPO_ROOT / "data" / "cases" / "case_0001"


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
            if Path(os.path.realpath(str(candidate))) == _REAL_CASES_ROOT:
                holders.append(module)
        except Exception:
            continue
    return holders


_real_data_before = snapshot_real_data_tree()

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_mf_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
check(
    "the CASES_DIR redirect sweep found ui.services.paths, manual_fact_entry_engine, fact_approval, "
    "fact_verification and every timeline/deadline module the real chain touches",
    all(
        any(getattr(m, "__name__", "") == name for m in _cases_dir_holders)
        for name in (
            "ui.services.paths", "manual_fact_entry_engine", "fact_approval", "fact_verification",
            "timeline_engine", "timeline_validator", "timeline_approval", "deadline_engine",
            "deadline_approval", "deadline_validator",
        )
    ),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
_original_cases_dirs = [(m, m.CASES_DIR) for m in _cases_dir_holders]
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

_original_deadline_rule_policy_data_dir = _pg_deadline_rule_selection_policy.DATA_DIR
_pg_deadline_rule_selection_policy.DATA_DIR = _TMP_ROOT / "data"

_original_default_holiday_calendar_path = _pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH
_cal_dir = _TMP_ROOT / "synthetic_holiday_calendar"
_cal_dir.mkdir(parents=True)
_cal_path = _cal_dir / "holiday_calendar.json"
_cal_doc = {
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
            "verification_ref": "manual_fact_pg_test_only_synthetic_verification_ref",
            "source_refs": [
                {"source_kind": "test_fixture", "citation": "Manual-fact PG test-only synthetic calendar - NOT a real legal source.", "url": None},
            ],
            "holidays": [],
        },
    ],
    "governance": {"change_approval": "test-only", "verification_authority": "test-only", "notes": None},
    "notes": "Manual-fact PG test-only synthetic calendar (Prensip 18) - never written to the real data/ tree.",
}
_pg_holiday_calendar_validator.attach_fixture_verification(_cal_doc, seed="manual_fact_pg_test_only_synthetic")
if not _pg_holiday_calendar_validator.validate_holiday_calendar(calendar=_cal_doc)["valid"]:
    raise AssertionError("synthetic holiday calendar fixture is itself invalid")
_cal_path.write_text(json.dumps(_cal_doc, ensure_ascii=False, indent=2), encoding="utf-8")
_pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH = _cal_path

RUN_TOKEN = uuid.uuid4().hex[:8]
DOC = "ihbarname_001"
DOC_B = "ihbarname_002"
DATE_A = "2026-02-10"
DATE_B = "2026-03-20"
EXCERPT_A = "İhbarname mükellefe 10.02.2026 tarihinde tebliğ edilmiştir."
EXCERPT_B = "İhbarname mükellefe 20.03.2026 tarihinde tebliğ edilmiştir."
LAWYER = str(_ACTORS["lawyer"])


def _rewrite_case_ids(dst, case_id):
    for path in dst.rglob("*"):
        if path.is_file() and (path.suffix in (".json", ".pending", ".bak") or path.name.endswith(".json.pending")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "case_0001" in text:
                path.write_text(text.replace("case_0001", case_id), encoding="utf-8")


def write_json(path, data):
    path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def manual_input(case_id, document_id, date, excerpt):
    return {"schema_version": 1, "case_id": case_id, "document_id": document_id,
            "facts": [{"role": "notification_date", "date": date, "page": 1, "text_excerpt": excerpt}]}


def make_manual_case(tag):
    """Single-document copy of case_0001 (ihbarname_001 only, mirroring
    the fact-verification PG test's trimming), with NO extraction at all
    for that document, an integer page_count (M-04) and the lawyer's
    manual input file in place."""
    case_id = f"mfpg{RUN_TOKEN}{tag}"
    dst = _TMP_CASES / case_id
    shutil.copytree(REAL_CASE_0001, dst)
    _rewrite_case_ids(dst, case_id)
    for other_doc in ("dava_dilekcesi_001", "vir_001"):
        shutil.rmtree(dst / "documents" / other_doc)
    case_data = json.loads((dst / "case.json").read_text(encoding="utf-8"))
    case_data["case_document_refs"] = [r for r in case_data["case_document_refs"] if r.get("document_id") == DOC]
    write_json(dst / "case.json", case_data)
    doc_dir = dst / "documents" / DOC
    shutil.rmtree(doc_dir / "extractions")
    document = json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))
    document["file"]["page_count"] = 1
    write_json(doc_dir / "document.json", document)
    (doc_dir / "manual_input").mkdir()
    write_json(doc_dir / "manual_input" / "manual_facts.input.json", manual_input(case_id, DOC, DATE_A, EXCERPT_A))
    seed_assignment(_ACTORS["lawyer"], case_id, "lawyer")
    return case_id, dst


def authz_conn_factory():
    return psycopg.connect(dbname=PG_DB)


def mutation_conn_factory():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def report_conn_factory():
    return psycopg.connect(dbname=PG_DB)


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


def manual_preview(case_id, document_id=DOC):
    return run_cli(["manual-fact", "--case", case_id, "--document", document_id, "--actor-user-id", LAWYER])


def manual_apply(case_id, digest, *, document_id=DOC, attempt=1):
    return run_cli(["manual-fact", "--case", case_id, "--document", document_id, "--actor-user-id", LAWYER,
                    "--apply", "--expected-input-digest", digest, "--attempt", str(attempt)])


def promote_fact(case_id, document_id=DOC):
    code, out, err = run_cli(["promotion", "--case", case_id, "--row-key", "fact", "--document", document_id,
                              "--actor-user-id", LAWYER])
    if code != 0:
        return code, out, err
    pending_hash = parse_kv(out, "pending_hash")
    return run_cli(["promotion", "--case", case_id, "--row-key", "fact", "--document", document_id,
                    "--actor-user-id", LAWYER, "--approve", "--expected-hash", pending_hash])


def verify_fact(case_id, case_dir, document_id=DOC):
    facts_path = case_dir / "documents" / document_id / "extractions" / "facts.json"
    fact_id = json.loads(facts_path.read_bytes())["facts"][0]["fact_id"]
    return run_cli([
        "verification", "--case", case_id, "--document", document_id, "--fact-id", fact_id,
        "--actor-user-id", LAWYER, "--apply", "--target-state", "verified",
        "--expected-hash", hashlib.sha256(facts_path.read_bytes()).hexdigest(), "--evidence-ref", document_id,
    ])


def regenerate_timeline(case_id):
    code, out, err = run_cli(["generation", "--case", case_id, "--row-key", "timeline", "--actor-user-id", LAWYER])
    if code != 0:
        return code, out, err
    digest = parse_kv(out, "input_digest")
    code, out, err = run_cli(["generation", "--case", case_id, "--row-key", "timeline", "--actor-user-id", LAWYER,
                              "--apply", "--expected-input-digest", digest])
    if code != 0:
        return code, out, err
    code, out, err = run_cli(["promotion", "--case", case_id, "--row-key", "timeline", "--actor-user-id", LAWYER])
    if code != 0:
        return code, out, err
    pending_hash = parse_kv(out, "pending_hash")
    return run_cli(["promotion", "--case", case_id, "--row-key", "timeline", "--actor-user-id", LAWYER,
                    "--approve", "--expected-hash", pending_hash])


def generate_deadline(case_id, anchor_event_id, ref):
    code, out, err = run_cli(["generation", "--case", case_id, "--row-key", "deadline", "--anchor", anchor_event_id,
                              "--actor-user-id", LAWYER])
    if code != 0:
        return code, out, err
    digest = parse_kv(out, "input_digest")
    return run_cli([
        "generation", "--case", case_id, "--row-key", "deadline", "--anchor", anchor_event_id,
        "--actor-user-id", LAWYER, "--apply", "--expected-input-digest", digest,
        "--judicial-recess-applicable", "no",
        # SYNTHETIC TEST attestation ref - NOT a real lawyer/client declaration.
        "--stopping-event-status", "none", "--stopping-event-attestation-ref", ref,
    ])


def expected_deadline(anchor_iso):
    """Independent rule arithmetic for the active İYUK m.7 rule under the
    synthetic, holiday-free calendar: next-day start + 30 calendar days,
    rolled forward over Saturday/Sunday."""
    day = _dt.date.fromisoformat(anchor_iso) + _dt.timedelta(days=30)
    while day.weekday() >= 5:
        day += _dt.timedelta(days=1)
    return day.isoformat()


try:
    # ============================================================
    # G-P1 / G-P2 - the full B-path chain through the REAL CLI.
    # ============================================================
    case1, dir1 = make_manual_case("p1")
    code, out, err = manual_preview(case1)
    check("G-P1a manual-fact preview exits 0", code == 0, f"out={out!r} err={err!r}")
    digest1 = parse_kv(out, "input_digest") if code == 0 else ""
    check("G-P1b preview prints excerpt_found=true + its sha and NEVER the excerpt text (K-18)",
          "excerpt_found=true" in out
          and f"text_excerpt_sha256={hashlib.sha256(EXCERPT_A.encode('utf-8')).hexdigest()}" in out
          and EXCERPT_A not in out and "tebliğ edilmiştir" not in out, out)
    check("G-P1c preview wrote zero journal rows", journal_rows(f"case:{case1}") == [])
    code, out, err = manual_apply(case1, digest1)
    check("G-P1d manual-fact apply exits 0 (APPLIED)", code == 0 and "APPLIED manual-fact" in out,
          f"out={out!r} err={err!r}")
    rows1 = journal_rows(f"case:{case1}")
    check("G-P1e exactly one completed generation.fact_manual journal row",
          len(rows1) == 1 and rows1[0]["action_family"] == "generation.fact_manual"
          and rows1[0]["state"] == "completed" and rows1[0]["target_ref"] == f"fact.{DOC}.pending", f"{rows1!r}")
    pending1 = dir1 / "documents" / DOC / "extractions" / _pg_fact_approval.CURRENT_PENDING_FILENAME
    pending_doc1 = json.loads(pending1.read_bytes())
    check("G-P1f the real pending is method=manual and every fact unverified",
          pending_doc1["extractor"]["method"] == "manual"
          and all(f["verification_state"] == "unverified" for f in pending_doc1["facts"]))
    check("G-P1g no canonical facts.json was written by manual-fact",
          not (dir1 / "documents" / DOC / "extractions" / "facts.json").exists())

    code, out, err = run_cli(["promotion", "--case", case1, "--row-key", "fact", "--document", DOC,
                              "--actor-user-id", LAWYER])
    check("G-P1h promotion.fact preview reports validation_ready=True for the manual pending",
          code == 0 and "validation_ready=True" in out, f"out={out!r} err={err!r}")
    code, out, err = promote_fact(case1)
    check("G-P1i real promotion.fact apply exits 0", code == 0, f"out={out!r} err={err!r}")
    canonical1 = json.loads((dir1 / "documents" / DOC / "extractions" / "facts.json").read_bytes())
    check("G-P1j canonical fact is still unverified after promotion (approval != verification)",
          all(f["verification_state"] == "unverified" for f in canonical1["facts"]))
    code, out, err = verify_fact(case1, dir1)
    check("G-P1k real verification.fact (verified, evidence-ref = the document) exits 0", code == 0,
          f"out={out!r} err={err!r}")
    code, out, err = regenerate_timeline(case1)
    check("G-P1l real generation.timeline + promotion.timeline exit 0", code == 0, f"out={out!r} err={err!r}")
    timeline1 = json.loads((dir1 / "timeline" / "timeline.json").read_bytes())
    events1 = [e for e in timeline1["events"] if e["event_type"] == "notification_date"]
    check("G-P1m the REAL timeline has exactly one notification_date event, verified, exact, 2026-02-10",
          len(events1) == 1 and events1[0]["verification_state"] == "verified"
          and events1[0]["date"] == DATE_A and events1[0]["date_precision"] == "exact", f"{timeline1!r}")
    anchor1 = events1[0]["event_id"] if events1 else ""
    code, out, err = generate_deadline(case1, anchor1, "TEST-MANUAL-FACT-SYNTHETIC-NO-STOPPING-EVENT-ATTESTATION")
    check("G-P1n real generation.deadline apply exits 0", code == 0, f"out={out!r} err={err!r}")
    pending_deadline1 = json.loads(_pg_deadline_engine.get_pending_path(case1).read_bytes())
    expected1 = expected_deadline(DATE_A)
    check(
        f"G-P1o the REAL deadline engine reports calculated / {expected1} (independent rule arithmetic: "
        "2026-02-10 + 30 days, weekend roll-forward, holiday-free synthetic calendar)",
        pending_deadline1["deadlines"][0]["calculation_state"] == "calculated"
        and pending_deadline1["deadlines"][0]["calculated_deadline"] == expected1 == "2026-03-12",
        f"{pending_deadline1['deadlines'][0]!r}",
    )
    code, out, err = run_cli(["approval", "--case", case1, "--row-key", "deadline", "--actor-user-id", LAWYER])
    pending_hash_d1 = parse_kv(out, "pending_hash") if code == 0 else ""
    code, out, err = run_cli(["approval", "--case", case1, "--row-key", "deadline", "--actor-user-id", LAWYER,
                              "--approve", "--expected-hash", pending_hash_d1])
    check("G-P1p real approval.deadline apply exits 0", code == 0, f"out={out!r} err={err!r}")
    canonical_deadline1 = json.loads(_pg_deadline_approval.get_canonical_path(case1).read_bytes())
    check("G-P1q canonical deadline.json: calculated, anchor verified, 2026-03-12",
          canonical_deadline1["deadlines"][0]["calculation_state"] == "calculated"
          and canonical_deadline1["deadlines"][0]["anchor_verification_state"] == "verified"
          and canonical_deadline1["deadlines"][0]["calculated_deadline"] == "2026-03-12",
          f"{canonical_deadline1['deadlines'][0]!r}")
    rep_out, rep_err = io.StringIO(), io.StringIO()
    rep_code = deadline_report.main(["--case", case1, "--actor-user-id", LAWYER],
                                    conn_factory=report_conn_factory, stdout=rep_out, stderr=rep_err)
    check("G-P1r ui.deadline_report exits 0 and reports the calculated date",
          rep_code == 0 and ("12.03.2026" in rep_out.getvalue() or "2026-03-12" in rep_out.getvalue()),
          f"code={rep_code} out={rep_out.getvalue()[:600]!r} err={rep_err.getvalue()!r}")

    rows_chain = journal_rows(f"case:{case1}")
    families_chain = [(r["action_family"], r["state"]) for r in rows_chain]
    check(
        "G-P2 journal order: generation.fact_manual -> promotion.fact -> verification.fact, all completed",
        families_chain[:3] == [("generation.fact_manual", "completed"), ("promotion.fact", "completed"),
                               ("verification.fact", "completed")]
        and all(state == "completed" for _family, state in families_chain),
        f"{families_chain!r}",
    )

    # ============================================================
    # G-N3 - real merged registry + gather_evidence() on the REAL row.
    # ============================================================
    registry = op._default_registry_factory()
    families = set(registry.known_action_families())
    check("G-N3a REAL reconciliation registry: 53 routing keys, the only addition over 52 is generation.fact_manual",
          len(families) == 53 and len(families - {"generation.fact_manual"}) == 52, f"n={len(families)}")
    adapter = registry.get("generation.fact_manual")
    check("G-N3b generation.fact_manual resolves to ManualFactReconciliationAdapter",
          type(adapter).__name__ == "ManualFactReconciliationAdapter")

    # ============================================================
    # G-N2 - second apply after completion / foreign pending (REAL SQL
    #        behind the N-L4 journal-state message).
    # ============================================================
    case2, dir2 = make_manual_case("n2")
    code, out, err = manual_preview(case2)
    digest2 = parse_kv(out, "input_digest")
    code, out, err = manual_apply(case2, digest2)
    rows2 = journal_rows(f"case:{case2}")
    check("G-N2a setup apply completed", code == 0 and len(rows2) == 1 and rows2[0]["state"] == "completed")
    evidence2 = adapter.gather_evidence(entry_of(rows2[0]))
    check("G-N3c gather_evidence on the REAL completed row: post proven, pre not (pending now present)",
          evidence2.post_state_verified is True and evidence2.pre_state_confirmed_unchanged is False
          and evidence2.observed_post_hash == rows2[0]["observed_post_hash"])
    code, out, err = manual_apply(case2, digest2)
    check(
        "G-N2b second apply after completion -> exit 1, ManualFactPendingExistsError naming the REAL "
        "journal row (journal_id + state=completed), zero new rows",
        code == cli_mutate.EXIT_DOMAIN_ERROR and "ManualFactPendingExistsError" in err
        and f"journal_id={rows2[0]['id']} state=completed" in err and len(journal_rows(f"case:{case2}")) == 1,
        f"code={code} err={err!r}",
    )
    case2b, dir2b = make_manual_case("n2b")
    code, out, err = manual_preview(case2b)
    digest2b = parse_kv(out, "input_digest")
    ext2b = dir2b / "documents" / DOC / "extractions"
    ext2b.mkdir()
    foreign = (REAL_CASE_0001 / "documents" / "dava_dilekcesi_001" / "extractions"
               / _pg_fact_approval.CURRENT_PENDING_FILENAME).read_bytes()
    (ext2b / _pg_fact_approval.CURRENT_PENDING_FILENAME).write_bytes(foreign)
    code, out, err = manual_apply(case2b, digest2b)
    check("G-N2c LLM-family pending present -> exit 1 (M-09), zero rows, pending untouched",
          code == cli_mutate.EXIT_DOMAIN_ERROR and "ManualFactPendingExistsError" in err
          and journal_rows(f"case:{case2b}") == []
          and (ext2b / _pg_fact_approval.CURRENT_PENDING_FILENAME).read_bytes() == foreign,
          f"code={code} err={err!r}")

    # ============================================================
    # G-N1 - K-3 + K-16 against REAL promotion: a hand-edited verified
    #        pending is refused with ZERO promotion journal rows and the
    #        case stays ungated.
    # ============================================================
    case3, dir3 = make_manual_case("n1")
    code, out, err = manual_preview(case3)
    code, out, err = manual_apply(case3, parse_kv(out, "input_digest"))
    pending3 = dir3 / "documents" / DOC / "extractions" / _pg_fact_approval.CURRENT_PENDING_FILENAME
    genuine3 = pending3.read_bytes()
    tampered3 = json.loads(genuine3)
    tampered3["facts"][0]["verification_state"] = "verified"
    pending3.write_bytes(json.dumps(tampered3, ensure_ascii=False, indent=2).encode("utf-8"))
    rows3_before = journal_rows(f"case:{case3}")
    code, out, err = run_cli(["promotion", "--case", case3, "--row-key", "fact", "--document", DOC,
                              "--actor-user-id", LAWYER])
    check("G-N1a promotion preview reports validation_ready=False for the verified manual pending",
          code == 0 and "validation_ready=False" in out, f"out={out!r} err={err!r}")
    code, out, err = run_cli(["promotion", "--case", case3, "--row-key", "fact", "--document", DOC,
                              "--actor-user-id", LAWYER, "--approve", "--expected-hash",
                              hashlib.sha256(pending3.read_bytes()).hexdigest()])
    rows3_after = journal_rows(f"case:{case3}")
    check(
        "G-N1b promotion apply -> exit 1, PromotionPendingInvalidError, ZERO new journal rows, no canonical",
        code == cli_mutate.EXIT_DOMAIN_ERROR and "PromotionPendingInvalidError" in err
        and len(rows3_after) == len(rows3_before)
        and not (dir3 / "documents" / DOC / "extractions" / "facts.json").exists(),
        f"code={code} err={err!r} rows={rows3_after!r}",
    )
    pending3.write_bytes(genuine3)
    code, out, err = promote_fact(case3)
    check("G-N1c the case was NOT gated: restoring the genuine pending lets a normal promotion complete",
          code == 0 and journal_rows(f"case:{case3}")[-1]["action_family"] == "promotion.fact"
          and journal_rows(f"case:{case3}")[-1]["state"] == "completed", f"out={out!r} err={err!r}")

    # ============================================================
    # G-A - crash cell (a) through the REAL reconciliation operator.
    # ============================================================
    case4, dir4 = make_manual_case("ca")
    code, out, err = manual_preview(case4)
    digest4 = parse_kv(out, "input_digest")
    _orig_validate = _pg_case_fact_validator.validate_fact_extraction

    def _failing_validate(path, raise_on_error=True):
        raise ValueError("synthetic writer-side validator failure")

    _pg_case_fact_validator.validate_fact_extraction = _failing_validate
    try:
        code, out, err = manual_apply(case4, digest4)
    finally:
        _pg_case_fact_validator.validate_fact_extraction = _orig_validate
    rows4 = journal_rows(f"case:{case4}")
    check("G-Aa writer-side validator FAIL -> exit 1, ManualFactWriteFailedError, row reconciliation_required",
          code == cli_mutate.EXIT_DOMAIN_ERROR and "ManualFactWriteFailedError" in err
          and len(rows4) == 1 and rows4[0]["state"] == "reconciliation_required", f"err={err!r} rows={rows4!r}")
    check("G-Ab (N-L7) the error names the REAL journal row and the operator command",
          f"journal_id={rows4[0]['id']}" in err and "reconciliation_operator" in err, err)
    check("G-Ac disk clean after in-process rollback",
          not (dir4 / "documents" / DOC / "extractions" / _pg_fact_approval.CURRENT_PENDING_FILENAME).exists()
          and not (dir4 / "documents" / DOC / "extractions" / _pg_manual_fact_engine.TEMP_FILENAME).exists())
    code, out, err = manual_apply(case4, digest4, attempt=2)
    check("G-Ad while unresolved the case is gated (ResourceGatedError), zero new rows",
          code == cli_mutate.EXIT_DOMAIN_ERROR and "ResourceGatedError" in err
          and len(journal_rows(f"case:{case4}")) == 1, f"err={err!r}")
    out_io, err_io = io.StringIO(), io.StringIO()
    rc = op.main(["--journal-id", str(rows4[0]["id"])], conn_factory=mutation_conn_factory,
                 stdout=out_io, stderr=err_io)
    check("G-Ae REAL operator dry run -> would resolve failed, zero journal change",
          rc == 0 and "failed" in out_io.getvalue()
          and journal_rows(f"case:{case4}")[0]["state"] == "reconciliation_required",
          f"rc={rc} out={out_io.getvalue()!r} err={err_io.getvalue()!r}")
    out_io, err_io = io.StringIO(), io.StringIO()
    rc = op.main(["--journal-id", str(rows4[0]["id"]), "--apply", "--actor-ref", f"manual-fact-test-{RUN_TOKEN}"],
                 conn_factory=mutation_conn_factory, stdout=out_io, stderr=err_io)
    rows4 = journal_rows(f"case:{case4}")
    check("G-Af REAL operator apply -> failed / reconciled_failed_pre_state_confirmed_unchanged / cli_service",
          rc == 0 and rows4[0]["state"] == "failed"
          and rows4[0]["resolution_code"] == "reconciled_failed_pre_state_confirmed_unchanged"
          and rows4[0]["reconciled_by_actor_type"] == "cli_service",
          f"rc={rc} rows={rows4!r} err={err_io.getvalue()!r}")
    code, out, err = manual_apply(case4, digest4, attempt=1)
    check("G-Ag same input + --attempt 1 after failed -> PriorAttemptFailedError, zero new rows",
          code == cli_mutate.EXIT_DOMAIN_ERROR and "PriorAttemptFailedError" in err
          and len(journal_rows(f"case:{case4}")) == 1, f"err={err!r}")
    code, out, err = manual_apply(case4, digest4, attempt=2)
    rows4 = journal_rows(f"case:{case4}")
    check("G-Ah --attempt 2 -> completed under a NEW idempotency key",
          code == 0 and "attempt=2" in out and len(rows4) == 2 and rows4[1]["state"] == "completed"
          and rows4[1]["idempotency_key"] != rows4[0]["idempotency_key"], f"out={out!r} err={err!r}")

    # ============================================================
    # G-N4 - manual entry on document B next to a verified canonical
    #        notification fact on document A (K-19 STOP condition).
    # ============================================================
    case5 = f"mfpg{RUN_TOKEN}n4"
    dir5 = _TMP_CASES / case5
    shutil.copytree(REAL_CASE_0001, dir5)
    _rewrite_case_ids(dir5, case5)
    for other_doc in ("dava_dilekcesi_001", "vir_001"):
        shutil.rmtree(dir5 / "documents" / other_doc)
    facts_a = dir5 / "documents" / DOC / "extractions" / "facts.json"
    extraction_a = json.loads(facts_a.read_text(encoding="utf-8"))
    extraction_a["facts"] = [f for f in extraction_a["facts"]
                             if f["fact_id"] == "fact_ihbarname_001_llm_v1_2_1_20260901_122652_008"]
    extraction_a["facts"][0]["verification_state"] = "verified"
    write_json(facts_a, extraction_a)
    for leftover in (facts_a.parent).glob("*.pending"):
        leftover.unlink()
    doc_b_dir = dir5 / "documents" / DOC_B
    doc_b_dir.mkdir()
    document_b = json.loads((dir5 / "documents" / DOC / "document.json").read_text(encoding="utf-8"))
    document_b["document_id"] = DOC_B
    document_b["file"]["page_count"] = 1
    document_b["file"]["file_name"] = f"{DOC_B}.pdf"
    document_b["file"]["relative_path"] = f"cases/{case5}/documents/{DOC_B}/{DOC_B}.pdf"
    write_json(doc_b_dir / "document.json", document_b)
    (doc_b_dir / "extracted").mkdir()
    (doc_b_dir / "extracted" / f"{DOC_B}.txt").write_bytes(
        ("VERGİ / CEZA İHBARNAMESİ (ikinci)\n\n6. TEBLİĞ\n\n" + EXCERPT_B + "\n").encode("utf-8"))
    (doc_b_dir / "manual_input").mkdir()
    write_json(doc_b_dir / "manual_input" / "manual_facts.input.json", manual_input(case5, DOC_B, DATE_B, EXCERPT_B))
    case5_data = json.loads((dir5 / "case.json").read_text(encoding="utf-8"))
    ref_a = [r for r in case5_data["case_document_refs"] if r.get("document_id") == DOC][0]
    case5_data["case_document_refs"] = [ref_a, dict(ref_a, document_id=DOC_B, primary=False)]
    write_json(dir5 / "case.json", case5_data)
    seed_assignment(_ACTORS["lawyer"], case5, "lawyer")

    code, out, err = manual_preview(case5, DOC_B)
    check("G-N4a manual-fact preview on document B (A already has a verified canonical tebliğ fact) exits 0",
          code == 0, f"out={out!r} err={err!r}")
    code, out, err = manual_apply(case5, parse_kv(out, "input_digest") if code == 0 else "0" * 64, document_id=DOC_B)
    check("G-N4b manual apply on B succeeds (M-09/M-10 are document-scoped; no cross-document read)",
          code == 0, f"out={out!r} err={err!r}")
    code, out, err = promote_fact(case5, DOC_B)
    check("G-N4c promotion.fact for B exits 0", code == 0, f"out={out!r} err={err!r}")
    code, out, err = verify_fact(case5, dir5, DOC_B)
    check("G-N4d verification.fact for B exits 0", code == 0, f"out={out!r} err={err!r}")
    code, out, err = regenerate_timeline(case5)
    check("G-N4e timeline generation/promotion with two tebliğ facts exits 0", code == 0, f"out={out!r} err={err!r}")
    timeline5 = json.loads((dir5 / "timeline" / "timeline.json").read_bytes()) if code == 0 else {"events": []}
    notif5 = [e for e in timeline5["events"] if e["event_type"] == "notification_date"]
    check(
        "G-N4f MEASURED: the timeline keeps TWO separate notification_date events with the two distinct "
        "dates (no silent merge into one date)",
        len(notif5) == 2 and sorted(e["date"] for e in notif5) == [DATE_A, DATE_B],
        f"{[(e['event_id'], e['date'], e.get('source_fact_ids')) for e in notif5]!r}",
    )
    code, out, err = run_cli(["generation", "--case", case5, "--row-key", "deadline", "--actor-user-id", LAWYER])
    check("G-N4g generation.deadline WITHOUT --anchor is refused (exit 2): no automatic anchor selection",
          code == cli_mutate.EXIT_USAGE_ERROR and journal_rows(f"case:{case5}")[-1]["action_family"] != "generation.deadline",
          f"code={code} err={err!r}")
    by_date5 = {e["date"]: e["event_id"] for e in notif5}
    if DATE_B in by_date5:
        code, out, err = generate_deadline(case5, by_date5[DATE_B], "TEST-MANUAL-FACT-SYNTHETIC-G-N4-ATTESTATION")
        pending_deadline5 = json.loads(_pg_deadline_engine.get_pending_path(case5).read_bytes()) if code == 0 else {}
        deadline5 = (pending_deadline5.get("deadlines") or [{}])[0]
        check(
            f"G-N4h with the explicit anchor = B's event the deadline is computed from B ONLY "
            f"({expected_deadline(DATE_B)}), never from A's date",
            code == 0 and deadline5.get("anchor_event_id") == by_date5[DATE_B]
            and deadline5.get("calculation_state") == "calculated"
            and deadline5.get("calculated_deadline") == expected_deadline(DATE_B)
            and deadline5.get("calculated_deadline") != expected_deadline(DATE_A),
            f"code={code} err={err!r} deadline={deadline5!r}",
        )
finally:
    for _m, _orig in _original_cases_dirs:
        _m.CASES_DIR = _orig
    _pg_deadline_rule_selection_policy.DATA_DIR = _original_deadline_rule_policy_data_dir
    _pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH = _original_default_holiday_calendar_path
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

check("FINAL: tempdir removed", not _TMP_ROOT.exists())
check("FINAL: the real data/ tree is byte-for-byte IDENTICAL to the pre-test snapshot",
      snapshot_real_data_tree() == _real_data_before)

summarize_and_exit()
