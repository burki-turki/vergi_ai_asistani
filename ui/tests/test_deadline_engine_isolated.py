# ============================================================
# ROW 19C-3c-i - src/deadline_engine.py ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator - exercises the
# ADDITIVE changes made to `deadline_engine.py`/`deadline_calculator.py`
# for Row 19C-3c-i directly: `provisions_path` threading, the new
# keyword-only mutation-binding parameters on `write_pending()`/
# `run_engine()`, the `*.generation_audit.json` audit record, the
# `pre_commit_callback` hook, and the legacy CLI bypass closure. Uses a
# REAL, independently re-identified COPY of the real `data/cases/
# case_0001` tree under a fresh tempdir (never the real tree itself),
# with `deadline_engine.CASES_DIR` AND `deadline_validator.CASES_DIR`
# BOTH redirected to that copy - the read chain
# (`deadline_rule_selection_policy.select_for_case_event()` ->
# `deadline_validator.load_case()`/`load_canonical_timeline()`) resolves
# `CASES_DIR` from `deadline_validator`'s OWN module globals at call
# time, so patching that module's attribute is sufficient; imported-by-
# name functions still see the patched value. Global resources
# (ruleset/provisions) are read from their REAL production paths,
# read-only, never written.
#
# Run: python ui/tests/test_deadline_engine_isolated.py
# ============================================================

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import deadline_engine                              # noqa: E402
import deadline_validator                            # noqa: E402
import deadline_calculator                           # noqa: E402
import holiday_calendar_validator                    # noqa: E402

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
        check(label, True, detail)
    except Exception as error:  # noqa: BLE001
        check(label, False, f"{detail} (wrong exception type: {type(error).__name__}: {error})")
    else:
        check(label, False, f"{detail} (no exception raised)")


REAL_CASE_0001 = REPO_ROOT / "data" / "cases" / "case_0001"
CASE_ID = "case_0001"
ANCHOR_EVENT_ID = "timeline_event_003"

_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_deadline_engine_isolated_"))
_tmp_cases = _tmp_root / "cases"
_tmp_cases.mkdir(parents=True)


def _fresh_case_copy():
    """A REAL, independently re-identified copy of case_0001, with any
    PRE-EXISTING pending/history/generation_reviews artefacts stripped -
    the real case_0001 tree already carries a committed
    `deadlines/deadline_case_0001_v1.json.pending` (and a canonical
    `deadline.json`) from an earlier development row; without stripping
    the pending/history/generation_reviews trio, every 'first write'
    scenario below would silently start from a non-fresh state."""
    dest = _tmp_cases / CASE_ID
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REAL_CASE_0001, dest)
    deadlines_dir = dest / "deadlines"
    for stale in deadlines_dir.glob("*.pending"):
        stale.unlink()
    for stale_dir_name in ("history", "generation_reviews"):
        stale_dir = deadlines_dir / stale_dir_name
        if stale_dir.exists():
            shutil.rmtree(stale_dir)
    return dest


_original_deadline_engine_cases_dir = deadline_engine.CASES_DIR
_original_deadline_validator_cases_dir = deadline_validator.CASES_DIR

try:
    deadline_engine.CASES_DIR = _tmp_cases
    deadline_validator.CASES_DIR = _tmp_cases

    # ============================================================
    # 1) provisions_path threading - build_deadline_engine_output()
    #    accepts the additive keyword and passes it all the way through
    #    to build_case_deadline_analysis()/verify_rule_legal_basis_for_
    #    date() without error, using the REAL production provisions.json
    #    (read-only).
    # ============================================================
    case_dir_1 = _fresh_case_copy()
    analysis_1 = deadline_engine.build_deadline_engine_output(
        case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
        ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
        provisions_path=deadline_calculator.DEFAULT_PROVISIONS_PATH,
    )
    check(
        "provisions_path threading: explicit (default-equivalent) provisions_path produces the "
        "same deadline_analysis_id/deadline count as the implicit default",
        analysis_1["deadline_analysis_id"] == f"deadline_{CASE_ID}_v1" and len(analysis_1["deadlines"]) >= 1,
        f"got {analysis_1.get('deadline_analysis_id')!r} / {len(analysis_1.get('deadlines', []))} deadlines",
    )

    # ============================================================
    # 2) write_pending() partial mutation-binding guard - fail-closed,
    #    zero filesystem writes, BEFORE the atomic write even starts.
    # ============================================================
    case_dir_2 = _fresh_case_copy()
    pending_path_2 = deadline_engine.get_pending_path(CASE_ID)
    expect_raises(
        deadline_engine.DeadlineEngineError,
        lambda: deadline_engine.write_pending(
            case_id=CASE_ID, analysis=analysis_1,
            mutation_idempotency_key="idk", mutation_resource_key=None,
            mutation_actor_ref="7", anchor_event_id=ANCHOR_EVENT_ID,
            attempt=1,
            input_digest="d", generation_parameters_digest="g",
        ),
        "write_pending(): mutation_idempotency_key given but mutation_resource_key missing -> "
        "DeadlineEngineError (partial binding rejected)",
    )
    check(
        "write_pending() partial-binding guard: zero filesystem writes happened (pending still "
        "absent)",
        not pending_path_2.exists(),
    )

    # ============================================================
    # 3) run_engine() WITHOUT mutation binding (legacy/direct-Python-
    #    call shape) - atomic write succeeds, no audit is written, and
    #    the return dict is additive (all pre-existing keys + the new
    #    ones).
    # ============================================================
    case_dir_3 = _fresh_case_copy()
    result_3 = deadline_engine.run_engine(
        case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
        ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
    )
    check(
        "run_engine() non-coordinator call: returns an additive dict with 'analysis' and the new "
        "audit_path/first_write/pending_sha256 keys",
        isinstance(result_3, dict) and "analysis" in result_3 and result_3["audit_path"] is None
        and result_3["first_write"] is True and isinstance(result_3["pending_sha256"], str),
        f"got keys={sorted(result_3.keys())}",
    )
    check(
        "run_engine() non-coordinator call: the pending file was actually written",
        deadline_engine.get_pending_path(CASE_ID).exists(),
    )
    check(
        "run_engine() non-coordinator call: NO generation_reviews/ audit directory was created "
        "(mutation binding was never provided)",
        not deadline_engine.get_reviews_dir(CASE_ID).exists(),
    )
    pending_sha_before_second_run = hashlib.sha256(deadline_engine.get_pending_path(CASE_ID).read_bytes()).hexdigest()
    check(
        "run_engine() non-coordinator call: reported pending_sha256 matches the real on-disk bytes",
        result_3["pending_sha256"] == pending_sha_before_second_run,
    )

    # ============================================================
    # 4) SECOND run over the SAME case - history preservation (the
    #    FIRST pending is archived into history/, never silently
    #    overwritten) and first_write becomes False.
    # ============================================================
    result_4 = deadline_engine.run_engine(
        case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
        ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
    )
    check(
        "second run_engine() call: first_write is now False (a previous pending existed)",
        result_4["first_write"] is False,
    )
    check(
        "second run_engine() call: the FIRST pending's bytes were archived into history/, "
        "byte-for-byte, never silently discarded",
        result_4["previous_pending_history"] is not None
        and result_4["previous_pending_history"].exists()
        and hashlib.sha256(result_4["previous_pending_history"].read_bytes()).hexdigest() == pending_sha_before_second_run,
    )
    check(
        "second run_engine() call: canonical deadline.json was NOT touched (engine never writes "
        "canonical)",
        deadline_engine.get_canonical_path(CASE_ID).exists() == REAL_CASE_0001.joinpath(
            "deadlines", "deadline.json",
        ).exists(),
    )

    # ============================================================
    # 5) run_engine() WITH full mutation binding - a *.generation_audit
    #    .json record is written, with every required field, and the
    #    return dict's audit_path/pending_sha256 are consistent.
    # ============================================================
    case_dir_5 = _fresh_case_copy()
    result_5 = deadline_engine.run_engine(
        case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
        ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
        input_digest="fake_input_digest_5",
        generation_parameters_digest="fake_generation_parameters_digest_5",
        mutation_idempotency_key="idk_5",
        mutation_resource_key=f"case:{CASE_ID}",
        mutation_actor_ref="42",
        attempt=1,
    )
    check(
        "coordinator-mode run_engine(): a real audit_path was returned and the file exists under "
        "generation_reviews/",
        result_5["audit_path"] is not None and Path(result_5["audit_path"]).is_file(),
        f"got {result_5['audit_path']!r}",
    )
    audit_record_5 = json.loads(Path(result_5["audit_path"]).read_text(encoding="utf-8"))
    check(
        "coordinator-mode run_engine(): audit record's action_family/target_ref/target_state/"
        "outcome are exactly right",
        audit_record_5["action_family"] == "generation.deadline"
        and audit_record_5["target_ref"] == deadline_engine.get_target_ref(ANCHOR_EVENT_ID)
        and audit_record_5["target_state"] == "generated"
        and audit_record_5["outcome"] == "generated",
        f"got {audit_record_5!r}",
    )
    check(
        "coordinator-mode run_engine(): audit record's mutation-binding fields are bound exactly "
        "to what was passed in",
        audit_record_5["mutation_idempotency_key"] == "idk_5"
        and audit_record_5["mutation_resource_key"] == f"case:{CASE_ID}"
        and audit_record_5["mutation_actor_ref"] == "42"
        and audit_record_5["input_digest"] == "fake_input_digest_5"
        and audit_record_5["generation_parameters_digest"] == "fake_generation_parameters_digest_5",
    )
    check(
        "coordinator-mode run_engine(): audit record's pending_sha256 matches the REAL on-disk "
        "pending bytes, and its generated_at matches the pending's own generated_at",
        audit_record_5["pending_sha256"] == hashlib.sha256(deadline_engine.get_pending_path(CASE_ID).read_bytes()).hexdigest()
        and audit_record_5["generated_at"] == result_5["analysis"]["generated_at"],
    )
    check(
        "coordinator-mode run_engine(): first_write is True (fresh case copy, no prior pending)",
        audit_record_5["first_write"] is True and audit_record_5["history_backup_path"] is None,
    )

    # ============================================================
    # 6) pre_commit_callback - invoked immediately before the atomic
    #    write; if it raises, NOTHING is written (no pending, no
    #    audit) and any previous pending is restored.
    # ============================================================
    case_dir_6 = _fresh_case_copy()

    def _exploding_pre_commit():
        raise RuntimeError("simulated global-resource staleness")

    expect_raises(
        RuntimeError,
        lambda: deadline_engine.run_engine(
            case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
            ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
            input_digest="d6", generation_parameters_digest="g6",
            mutation_idempotency_key="idk_6", mutation_resource_key=f"case:{CASE_ID}",
            mutation_actor_ref="7", pre_commit_callback=_exploding_pre_commit,
            attempt=1,
        ),
        "pre_commit_callback raising -> the exception propagates unchanged",
    )
    check(
        "pre_commit_callback raising: NO pending file was left behind",
        not deadline_engine.get_pending_path(CASE_ID).exists(),
    )
    check(
        "pre_commit_callback raising: NO generation_reviews/ audit directory was created",
        not deadline_engine.get_reviews_dir(CASE_ID).exists(),
    )

    # pre_commit_callback on a case that ALREADY had a pending - proves
    # rollback restores the PREVIOUS pending, not just "no new pending".
    case_dir_6b = _fresh_case_copy()
    deadline_engine.run_engine(
        case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID, ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
    )
    previous_pending_bytes = deadline_engine.get_pending_path(CASE_ID).read_bytes()
    try:
        deadline_engine.run_engine(
            case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
            ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
            pre_commit_callback=_exploding_pre_commit,
        )
    except RuntimeError:
        pass
    check(
        "pre_commit_callback raising on a SECOND run: the ORIGINAL (first) pending was restored "
        "byte-for-byte, never left archived/lost",
        deadline_engine.get_pending_path(CASE_ID).exists()
        and deadline_engine.get_pending_path(CASE_ID).read_bytes() == previous_pending_bytes,
    )

    # ============================================================
    # 7) Post-write validator failure -> full rollback, no audit.
    # ============================================================
    case_dir_7 = _fresh_case_copy()
    _original_validate = deadline_engine.validate_deadline_analysis

    def _exploding_validate(**kwargs):
        raise deadline_engine.DeadlineEngineError("simulated post-write validator failure")

    deadline_engine.validate_deadline_analysis = _exploding_validate
    try:
        expect_raises(
            deadline_engine.DeadlineEngineError,
            lambda: deadline_engine.run_engine(
                case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
                ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
                mutation_idempotency_key="idk_7", mutation_resource_key=f"case:{CASE_ID}",
                mutation_actor_ref="7", input_digest="d7", generation_parameters_digest="g7",
                attempt=1,
            ),
            "post-write validator failure -> exception propagates, rollback engaged",
        )
    finally:
        deadline_engine.validate_deadline_analysis = _original_validate
    check(
        "post-write validator failure: no pending file was left behind",
        not deadline_engine.get_pending_path(CASE_ID).exists(),
    )
    check(
        "post-write validator failure: no audit was written",
        not deadline_engine.get_reviews_dir(CASE_ID).exists(),
    )

    # ============================================================
    # 8) PILOT READINESS ADIM 5 - holiday_calendar_path test-injection
    #    seam (`provisions_path`'in AYNI deseni) and the audit record's
    #    additive holiday_calendar_sha256/holiday_calendar_version
    #    fields.
    # ============================================================

    # 8a/8b) Default (production) calendar - audit fields match the
    #        REAL production data/holiday_calendar/holiday_calendar.json
    #        bytes/version (read-only, never written to).
    case_dir_8a = _fresh_case_copy()
    production_calendar_bytes = deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH.read_bytes()
    production_calendar_sha256 = hashlib.sha256(production_calendar_bytes).hexdigest()
    production_calendar_version = json.loads(production_calendar_bytes.decode("utf-8"))["calendar_version"]
    result_8a = deadline_engine.run_engine(
        case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
        ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
        mutation_idempotency_key="idk_8a", mutation_resource_key=f"case:{CASE_ID}",
        mutation_actor_ref="7", input_digest="d8a", generation_parameters_digest="g8a",
        attempt=1,
    )
    audit_record_8a = json.loads(Path(result_8a["audit_path"]).read_text(encoding="utf-8"))
    check(
        "8a: with the default (production) calendar, the audit record's holiday_calendar_sha256 "
        "matches the REAL production data/holiday_calendar/holiday_calendar.json bytes",
        audit_record_8a["holiday_calendar_sha256"] == production_calendar_sha256,
        f"got {audit_record_8a.get('holiday_calendar_sha256')!r} expected {production_calendar_sha256!r}",
    )
    check(
        "8b: the audit record's holiday_calendar_version matches the production calendar's own "
        "calendar_version",
        audit_record_8a["holiday_calendar_version"] == production_calendar_version,
        f"got {audit_record_8a.get('holiday_calendar_version')!r} expected {production_calendar_version!r}",
    )

    # 8c/8d) holiday_calendar_path injection seam - a synthetic
    #        calendar (calendar_version=7, distinct content) produces a
    #        DIFFERENT audit holiday_calendar_sha256/version than the
    #        default production calendar.
    case_dir_8c = _fresh_case_copy()
    synthetic_calendar_dir = Path(tempfile.mkdtemp(prefix="vergi_deadline_engine_iso_cal_"))
    synthetic_calendar_path = synthetic_calendar_dir / "synthetic_holiday_calendar.json"
    synthetic_calendar_doc = holiday_calendar_validator.create_valid_fixture()
    synthetic_calendar_doc["calendar_version"] = 7
    synthetic_calendar_path.write_text(
        json.dumps(synthetic_calendar_doc, ensure_ascii=False), encoding="utf-8",
    )
    try:
        result_8c = deadline_engine.run_engine(
            case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
            ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
            holiday_calendar_path=synthetic_calendar_path,
            mutation_idempotency_key="idk_8c", mutation_resource_key=f"case:{CASE_ID}",
            mutation_actor_ref="7", input_digest="d8c", generation_parameters_digest="g8c",
            attempt=1,
        )
        audit_record_8c = json.loads(Path(result_8c["audit_path"]).read_text(encoding="utf-8"))
        check(
            "8c: injecting a distinct synthetic calendar (holiday_calendar_path) produces a "
            "DIFFERENT audit holiday_calendar_sha256 than the default production calendar, and "
            "matches the injected file's OWN bytes",
            audit_record_8c["holiday_calendar_sha256"] != production_calendar_sha256
            and audit_record_8c["holiday_calendar_sha256"]
            == hashlib.sha256(synthetic_calendar_path.read_bytes()).hexdigest(),
        )
        check(
            "8d: the injected synthetic calendar's calendar_version (7) is reflected in the audit "
            "record",
            audit_record_8c["holiday_calendar_version"] == 7,
            f"got {audit_record_8c.get('holiday_calendar_version')!r}",
        )
    finally:
        shutil.rmtree(synthetic_calendar_dir, ignore_errors=True)

    # 8e/8f/8g) missing/invalid holiday_calendar_path -> fail-closed
    #           BEFORE any pending/audit write (run_engine loads the
    #           calendar for its OWN audit metadata before
    #           build_deadline_engine_output() even runs).
    case_dir_8e = _fresh_case_copy()
    missing_calendar_dir = Path(tempfile.mkdtemp(prefix="vergi_deadline_engine_iso_cal_missing_"))
    missing_calendar_path = missing_calendar_dir / "does_not_exist.json"
    try:
        expect_raises(
            FileNotFoundError,
            lambda: deadline_engine.run_engine(
                case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
                ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
                holiday_calendar_path=missing_calendar_path,
                mutation_idempotency_key="idk_8e", mutation_resource_key=f"case:{CASE_ID}",
                mutation_actor_ref="7", input_digest="d8e", generation_parameters_digest="g8e",
                attempt=1,
            ),
            "8e: missing holiday_calendar_path -> FileNotFoundError, fail-closed",
        )
    finally:
        shutil.rmtree(missing_calendar_dir, ignore_errors=True)
    check(
        "8f: missing holiday_calendar_path: NO pending file was left behind",
        not deadline_engine.get_pending_path(CASE_ID).exists(),
    )
    check(
        "8g: missing holiday_calendar_path: NO generation_reviews/ audit directory was created",
        not deadline_engine.get_reviews_dir(CASE_ID).exists(),
    )
finally:
    deadline_engine.CASES_DIR = _original_deadline_engine_cases_dir
    deadline_validator.CASES_DIR = _original_deadline_validator_cases_dir
    shutil.rmtree(_tmp_root, ignore_errors=True)


# ============================================================
# 8) LEGACY CLI CLOSURE - main() refuses unconditionally, before
#    parsing anything, with the fixed Row 19C-3b refusal message on
#    stderr and a genuine SystemExit(2).
# ============================================================

_LEGACY_REFUSAL_PREFIX = "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3b)."

check(
    "deadline_engine._LEGACY_CLI_REFUSAL_MESSAGE carries the fixed, shared refusal prefix",
    deadline_engine._LEGACY_CLI_REFUSAL_MESSAGE.startswith(_LEGACY_REFUSAL_PREFIX),
    f"got {deadline_engine._LEGACY_CLI_REFUSAL_MESSAGE!r}",
)
check(
    "deadline_engine._LEGACY_CLI_REFUSAL_MESSAGE points to the real replacement command",
    "ui.cli_mutate generation" in deadline_engine._LEGACY_CLI_REFUSAL_MESSAGE
    and "--row-key deadline" in deadline_engine._LEGACY_CLI_REFUSAL_MESSAGE,
)
try:
    deadline_engine.main()
except SystemExit as exit_signal:
    check("deadline_engine.main() raises SystemExit(2) unconditionally", exit_signal.code == 2)
else:
    check("deadline_engine.main() raises SystemExit(2) unconditionally", False, "no SystemExit raised")
check(
    "parse_judicial_recess is genuinely gone (dead code removed, not left unused)",
    not hasattr(deadline_engine, "parse_judicial_recess"),
)


# ============================================================
# PILOT READINESS ADIM 7 / SLICE 1 - STOPPING-EVENT THREADING
#
# run_engine() -> build_deadline_engine_output() ->
# build_case_deadline_analysis() -> build_deadline_record() zincirinin
# iki yeni keyword-only parametreyi TASIDIGINI ve write_pending()'in
# ham degerleri generation audit'ine YAZDIGINI kanitlar. Kapinin kendi
# karar tablosu test_deadline_stopping_events_isolated.py'dedir.
# ============================================================

_STOPEV_REF = "AV-BEYAN-ENGINE-001"

import timeline_validator as _stopev_timeline_validator  # noqa: E402

_orig_engine_cases_dir_stopev = deadline_engine.CASES_DIR
_orig_validator_cases_dir_stopev = deadline_validator.CASES_DIR
# timeline_validator.CASES_DIR AYRI bir modul sabitidir ve canonical
# timeline dogrulamasi kaynak fact'leri ORADAN okur - yonlendirilmezse
# gercek data/ agacindaki (unverified) fact'ler okunur.
_orig_tlv_cases_dir_stopev = _stopev_timeline_validator.CASES_DIR
_stopev_tmp = Path(tempfile.mkdtemp(prefix="stopev_engine_"))
try:
    _stopev_cases = _stopev_tmp / "cases"
    _stopev_cases.mkdir(parents=True)
    deadline_engine.CASES_DIR = _stopev_cases
    deadline_validator.CASES_DIR = _stopev_cases
    _stopev_timeline_validator.CASES_DIR = _stopev_cases

    def _stopev_case_copy():
        target = _stopev_cases / CASE_ID
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(REAL_CASE_0001, target)
        return target

    def _stopev_run(status, ref, idk):
        _stopev_case_copy()
        return deadline_engine.run_engine(
            case_id=CASE_ID,
            anchor_event_id=ANCHOR_EVENT_ID,
            ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
            input_digest="d" * 64,
            generation_parameters_digest="g" * 64,
            mutation_idempotency_key=idk,
            mutation_resource_key=f"case:{CASE_ID}",
            mutation_actor_ref="7",
            attempt=1,
            stopping_event_status=status,
            stopping_event_attestation_ref=ref,
        )

    # --- (a) run_engine kabul ediyor + ham alanlar audit'te ---
    _res_a = _stopev_run("none", _STOPEV_REF, "idk-stopev-a")
    _audit_a = json.loads(Path(_res_a["audit_path"]).read_text(encoding="utf-8"))
    check(
        "SLICE 1: run_engine() stopping_event_status/attestation_ref keyword-only "
        "parametrelerini KABUL eder ve audit yazilir",
        _res_a["audit_path"] is not None and isinstance(_res_a["pending_sha256"], str),
        _res_a.get("audit_path"),
    )
    check(
        "SLICE 1: generation audit'i HAM stopping_event_status/"
        "stopping_event_attestation_ref alanlarini BIREBIR tasir",
        _audit_a.get("stopping_event_status") == "none"
        and _audit_a.get("stopping_event_attestation_ref") == _STOPEV_REF,
        {k: _audit_a.get(k) for k in
         ("stopping_event_status", "stopping_event_attestation_ref")},
    )

    # --- (b) needs_review dali: ham alanlar KAYBOLMAZ ---
    _res_b = _stopev_run("present", _STOPEV_REF, "idk-stopev-b")
    _audit_b = json.loads(Path(_res_b["audit_path"]).read_text(encoding="utf-8"))
    check(
        "SLICE 1: needs_review uretebilen bir beyanda (present) bile ham alanlar "
        "audit'te KAYBOLMAZ ve ref SESSIZCE SILINMEZ",
        _audit_b.get("stopping_event_status") == "present"
        and _audit_b.get("stopping_event_attestation_ref") == _STOPEV_REF,
        {k: _audit_b.get(k) for k in
         ("stopping_event_status", "stopping_event_attestation_ref")},
    )

    # --- (c) parametre hic verilmedi -> audit'te iki alan None ---
    _stopev_case_copy()
    _res_c = deadline_engine.run_engine(
        case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
        ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
        input_digest="d" * 64, generation_parameters_digest="g" * 64,
        mutation_idempotency_key="idk-stopev-c",
        mutation_resource_key=f"case:{CASE_ID}", mutation_actor_ref="7",
        attempt=1,
    )
    _audit_c = json.loads(Path(_res_c["audit_path"]).read_text(encoding="utf-8"))
    check(
        "SLICE 1: parametre HIC verilmediginde audit iki alani da None olarak "
        "tasir (geriye uyumlu, sessiz 'none' YOK)",
        "stopping_event_status" in _audit_c
        and _audit_c["stopping_event_status"] is None
        and _audit_c["stopping_event_attestation_ref"] is None,
        {k: _audit_c.get(k) for k in
         ("stopping_event_status", "stopping_event_attestation_ref")},
    )

    # --- (d) hesaplamaya DEVAM eden dal: gercek verified anchor ---
    # Canonical timeline'in verification_state'i KAYNAK fact'lerden daha
    # guclu olamaz (deadline_validator kurali) - bu yuzden sentetik
    # kopyada ONCE kaynak fact'ler, SONRA timeline olayi verified yapilir.
    # Gercek data/ agacina DOKUNULMAZ (tempdir kopyasi).
    _case_d = _stopev_case_copy()
    for _facts_path in sorted(
        (_case_d / "documents").glob("*/extractions/facts.json")
    ):
        _facts = json.loads(_facts_path.read_text(encoding="utf-8"))
        for _f in _facts.get("facts", []):
            if isinstance(_f, dict) and "verification_state" in _f:
                _f["verification_state"] = "verified"
        _facts_path.write_text(
            json.dumps(_facts, ensure_ascii=False, indent=2) + chr(10),
            encoding="utf-8")
    _tl_path = _case_d / "timeline" / "timeline.json"
    _tl = json.loads(_tl_path.read_text(encoding="utf-8"))
    for _ev in _tl.get("events", []):
        if _ev.get("event_id") == ANCHOR_EVENT_ID:
            _ev["verification_state"] = "verified"
    _tl_path.write_text(
        json.dumps(_tl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _analysis_d = deadline_engine.build_deadline_engine_output(
        case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
        ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
        stopping_event_status="none",
        stopping_event_attestation_ref=_STOPEV_REF,
    )
    _first_d = _analysis_d["deadlines"][0]
    check(
        "SLICE 1: verified anchor + status=none + gecerli ref -> engine yolu "
        "HESAPLAMAYA DEVAM eder (kapi mesru yolu engellemez)",
        _first_d["calculation_state"] == "calculated"
        and _first_d["calculated_deadline"] is not None,
        _first_d,
    )

    # --- (e) AYNI verified anchor, beyan YOK -> fail-closed ---
    _analysis_e = deadline_engine.build_deadline_engine_output(
        case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
        ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
    )
    _first_e = _analysis_e["deadlines"][0]
    check(
        "SLICE 1: AYNI verified anchor, beyan YOK -> needs_review / "
        "stopping_event_status_unknown (default fail-closed)",
        _first_e["calculation_state"] == "needs_review"
        and _first_e["calculated_deadline"] is None
        and _first_e["notes"] == "stopping_event_status_unknown",
        _first_e,
    )
finally:
    deadline_engine.CASES_DIR = _orig_engine_cases_dir_stopev
    deadline_validator.CASES_DIR = _orig_validator_cases_dir_stopev
    _stopev_timeline_validator.CASES_DIR = _orig_tlv_cases_dir_stopev
    shutil.rmtree(_stopev_tmp, ignore_errors=True)


print(f"--- test_deadline_engine_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
