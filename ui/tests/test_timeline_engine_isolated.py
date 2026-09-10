# ============================================================
# ROW 19C-3c-i - src/timeline_engine.py ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator - exercises the
# STRUCTURAL REWRITE of `timeline_engine.py`'s write path (atomic write
# + history preservation + rollback, replacing the previously unsafe
# plain `open()`/`json.dump()`), the new `document_paths=`/`facts_
# paths=` override parameters (threaded through `timeline_validator.
# load_document_index()`/`load_canonical_fact_index()`), the new
# keyword-only mutation-binding parameters, the `*.generation_audit
# .json` audit record, and the legacy CLI bypass closure. Uses a REAL,
# independently re-identified COPY of the real `data/cases/case_0001`
# tree under a fresh tempdir (never the real tree itself), with
# `timeline_engine.CASES_DIR` AND `timeline_validator.CASES_DIR` BOTH
# redirected to that copy.
#
# Run: python ui/tests/test_timeline_engine_isolated.py
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

import timeline_engine                              # noqa: E402
import timeline_validator                            # noqa: E402

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

_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_timeline_engine_isolated_"))
_tmp_cases = _tmp_root / "cases"
_tmp_cases.mkdir(parents=True)


def _fresh_case_copy():
    """A REAL, independently re-identified copy of case_0001, with any
    PRE-EXISTING pending/history/generation_reviews artefacts stripped -
    the real case_0001 tree already carries a committed
    `timeline/timeline_v1_1.json.pending` (and a canonical
    `timeline.json`) from an earlier development row."""
    dest = _tmp_cases / CASE_ID
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REAL_CASE_0001, dest)
    timeline_dir = dest / "timeline"
    stale_pending = timeline_dir / timeline_engine.CANONICAL_PENDING_FILENAME
    if stale_pending.exists():
        stale_pending.unlink()
    for stale_dir_name in ("history", "generation_reviews"):
        stale_dir = timeline_dir / stale_dir_name
        if stale_dir.exists():
            shutil.rmtree(stale_dir)
    return dest


_original_timeline_engine_cases_dir = timeline_engine.CASES_DIR
_original_timeline_validator_cases_dir = timeline_validator.CASES_DIR

try:
    timeline_engine.CASES_DIR = _tmp_cases
    timeline_validator.CASES_DIR = _tmp_cases

    # ============================================================
    # 1) document_paths=/facts_paths= override threading - build_
    #    timeline() with EXPLICIT overrides (the real, glob-discovered
    #    paths) produces the IDENTICAL result to the default (raw-glob)
    #    call - the override changes only the SOURCE of the path list,
    #    never the outcome, when given the same real paths.
    # ============================================================
    case_dir_1 = _fresh_case_copy()
    default_result = timeline_engine.build_timeline(CASE_ID)

    real_document_paths = sorted((case_dir_1 / "documents").glob("*/document.json"))
    real_facts_paths = sorted((case_dir_1 / "documents").glob("*/extractions/facts.json"))
    check(
        "sanity: case_0001's real copy actually has at least one document.json and one "
        "facts.json to override with",
        len(real_document_paths) > 0 and len(real_facts_paths) > 0,
        f"documents={len(real_document_paths)} facts={len(real_facts_paths)}",
    )

    override_result = timeline_engine.build_timeline(
        CASE_ID, document_paths=real_document_paths, facts_paths=real_facts_paths,
    )
    check(
        "document_paths=/facts_paths= override with the SAME real paths produces the IDENTICAL "
        "raw/consolidated candidate counts as the default raw-glob call",
        override_result["raw_candidate_count"] == default_result["raw_candidate_count"]
        and override_result["consolidated_candidate_count"] == default_result["consolidated_candidate_count"]
        and override_result["fact_count"] == default_result["fact_count"]
        and override_result["document_count"] == default_result["document_count"],
        f"default={default_result} override={override_result}",
    )

    # ---- FEWER paths -> genuinely fewer facts/documents considered
    # (proving the override REALLY controls the source set, not
    # silently ignored). ----
    if len(real_facts_paths) > 0:
        reduced_result = timeline_engine.build_timeline(
            CASE_ID, document_paths=real_document_paths, facts_paths=real_facts_paths[:0],
        )
        check(
            "facts_paths=[] (empty override) -> fact_count becomes 0, proving the override "
            "genuinely replaces the source set rather than being silently ignored",
            reduced_result["fact_count"] == 0,
            f"got {reduced_result['fact_count']}",
        )

    # ---- raw-glob-bypass proof: with BOTH overrides given, Path.glob()
    # is NEVER called during build_timeline()/build_raw_event_
    # candidates() - a monkeypatch that raises if called proves this.
    # (validate_timeline() - called separately, by write_pending() as an
    # INDEPENDENT post-write cross-check - legitimately calls its OWN
    # raw glob by design and is NEVER exercised by this narrow check.) ----
    _original_path_glob = Path.glob

    def _exploding_glob(self, pattern):
        raise AssertionError(
            f"Path.glob({pattern!r}) was called even though document_paths=/facts_paths= "
            "overrides were given - the writer fell back to raw glob"
        )

    Path.glob = _exploding_glob
    try:
        no_glob_result = timeline_engine.build_timeline(
            CASE_ID, document_paths=real_document_paths, facts_paths=real_facts_paths,
        )
        check(
            "build_timeline() with BOTH overrides given NEVER calls Path.glob() - proven by a "
            "monkeypatch that raises AssertionError if it is",
            no_glob_result["raw_candidate_count"] == default_result["raw_candidate_count"],
        )
    finally:
        Path.glob = _original_path_glob

    # ============================================================
    # 2) run_timeline_engine() WITHOUT mutation binding - atomic write
    #    succeeds, additive return dict, no audit written.
    # ============================================================
    case_dir_2 = _fresh_case_copy()
    result_2 = timeline_engine.run_timeline_engine(CASE_ID)
    check(
        "run_timeline_engine() non-coordinator call: returns an additive dict with the new "
        "audit_path/first_write/pending_sha256 keys, audit_path is None (no binding given)",
        result_2["audit_path"] is None and result_2["first_write"] is True
        and isinstance(result_2["pending_sha256"], str),
        f"got keys={sorted(result_2.keys())}",
    )
    check(
        "run_timeline_engine() non-coordinator call: the pending file was actually written, at "
        "the SAME pinned filename as before this Row",
        timeline_engine.get_pending_path(CASE_ID).exists()
        and timeline_engine.get_pending_path(CASE_ID).name == "timeline_v1_1.json.pending",
    )
    check(
        "run_timeline_engine() non-coordinator call: NO generation_reviews/ audit directory was "
        "created (mutation binding was never provided)",
        not timeline_engine.get_reviews_dir(CASE_ID).exists(),
    )
    pending_sha_before_second_run = hashlib.sha256(timeline_engine.get_pending_path(CASE_ID).read_bytes()).hexdigest()
    check(
        "run_timeline_engine() non-coordinator call: reported pending_sha256 matches the real "
        "on-disk bytes",
        result_2["pending_sha256"] == pending_sha_before_second_run,
    )

    # ============================================================
    # 3) SECOND run over the SAME case - history preservation (atomic
    #    write + history, brand new for this file - the OLD write_json()
    #    had neither).
    # ============================================================
    result_3 = timeline_engine.run_timeline_engine(CASE_ID)
    check(
        "second run_timeline_engine() call: first_write is now False (a previous pending "
        "existed)",
        result_3["first_write"] is False,
    )
    check(
        "second run_timeline_engine() call: the FIRST pending's bytes were archived into "
        "history/, byte-for-byte, never silently discarded",
        result_3["previous_pending_history"] is not None
        and result_3["previous_pending_history"].exists()
        and hashlib.sha256(result_3["previous_pending_history"].read_bytes()).hexdigest() == pending_sha_before_second_run,
    )

    # ============================================================
    # 4) run_timeline_engine() WITH full mutation binding - a
    #    *.generation_audit.json record is written with every required
    #    field.
    # ============================================================
    case_dir_4 = _fresh_case_copy()
    result_4 = timeline_engine.run_timeline_engine(
        CASE_ID,
        input_digest="fake_input_digest_4",
        mutation_idempotency_key="idk_4",
        mutation_resource_key=f"case:{CASE_ID}",
        mutation_actor_ref="42",
    )
    check(
        "coordinator-mode run_timeline_engine(): a real audit_path was returned and the file "
        "exists under generation_reviews/",
        result_4["audit_path"] is not None and Path(result_4["audit_path"]).is_file(),
        f"got {result_4['audit_path']!r}",
    )
    audit_record_4 = json.loads(Path(result_4["audit_path"]).read_text(encoding="utf-8"))
    check(
        "coordinator-mode run_timeline_engine(): audit record's action_family/target_ref/"
        "target_state/outcome are exactly right, and generation_parameters_digest is explicitly "
        "None (timeline has no tuning parameters)",
        audit_record_4["action_family"] == "generation.timeline"
        and audit_record_4["target_ref"] == timeline_engine.get_target_ref()
        and audit_record_4["target_ref"] == "timeline.pending"
        and audit_record_4["target_state"] == "generated"
        and audit_record_4["outcome"] == "generated"
        and audit_record_4["generation_parameters_digest"] is None,
        f"got {audit_record_4!r}",
    )
    check(
        "coordinator-mode run_timeline_engine(): audit record's mutation-binding fields are "
        "bound exactly to what was passed in",
        audit_record_4["mutation_idempotency_key"] == "idk_4"
        and audit_record_4["mutation_resource_key"] == f"case:{CASE_ID}"
        and audit_record_4["mutation_actor_ref"] == "42"
        and audit_record_4["input_digest"] == "fake_input_digest_4",
    )
    check(
        "coordinator-mode run_timeline_engine(): audit record's pending_sha256 matches the REAL "
        "on-disk pending bytes, and its generated_at matches the pending's own generated_at",
        audit_record_4["pending_sha256"] == hashlib.sha256(timeline_engine.get_pending_path(CASE_ID).read_bytes()).hexdigest()
        and audit_record_4["generated_at"] == result_4["timeline"]["generated_at"],
    )
    check(
        "coordinator-mode run_timeline_engine(): first_write is True (fresh case copy, no prior "
        "pending)",
        audit_record_4["first_write"] is True and audit_record_4["history_backup_path"] is None,
    )

    # ============================================================
    # 5) write_pending() partial mutation-binding guard - fail-closed,
    #    zero filesystem writes.
    # ============================================================
    case_dir_5 = _fresh_case_copy()
    build_result_5 = timeline_engine.build_timeline(CASE_ID)
    expect_raises(
        timeline_engine.TimelineEngineError,
        lambda: timeline_engine.write_pending(
            case_id=CASE_ID, timeline=build_result_5["timeline"],
            mutation_idempotency_key="idk", mutation_resource_key=None,
            mutation_actor_ref="7", input_digest="d",
        ),
        "write_pending(): mutation_idempotency_key given but mutation_resource_key missing -> "
        "TimelineEngineError (partial binding rejected)",
    )
    check(
        "write_pending() partial-binding guard: NO pending file was written",
        not timeline_engine.get_pending_path(CASE_ID).exists(),
    )

    # ============================================================
    # 6) pre_commit_callback raising -> full rollback (no pending, no
    #    audit); on a case that already had a pending, the PREVIOUS
    #    pending is restored byte-for-byte.
    # ============================================================
    case_dir_6 = _fresh_case_copy()
    timeline_engine.run_timeline_engine(CASE_ID)
    previous_pending_bytes_6 = timeline_engine.get_pending_path(CASE_ID).read_bytes()

    def _exploding_pre_commit():
        raise RuntimeError("simulated pre-commit failure")

    try:
        timeline_engine.run_timeline_engine(CASE_ID, pre_commit_callback=_exploding_pre_commit)
    except RuntimeError:
        pass
    else:
        check("pre_commit_callback raising -> the exception propagates unchanged", False, "no exception raised")
    check(
        "pre_commit_callback raising on a case with a prior pending: the ORIGINAL pending was "
        "restored byte-for-byte, never left archived/lost",
        timeline_engine.get_pending_path(CASE_ID).exists()
        and timeline_engine.get_pending_path(CASE_ID).read_bytes() == previous_pending_bytes_6,
    )
    check(
        "pre_commit_callback raising: NO generation_reviews/ audit directory was created",
        not timeline_engine.get_reviews_dir(CASE_ID).exists(),
    )

    # ============================================================
    # 7) Post-write validator failure -> full rollback, no audit.
    # ============================================================
    case_dir_7 = _fresh_case_copy()
    _original_validate = timeline_engine.validate_timeline

    def _exploding_validate(**kwargs):
        raise timeline_engine.TimelineEngineError("simulated post-write validator failure")

    timeline_engine.validate_timeline = _exploding_validate
    try:
        expect_raises(
            timeline_engine.TimelineEngineError,
            lambda: timeline_engine.run_timeline_engine(
                CASE_ID, mutation_idempotency_key="idk_7", mutation_resource_key=f"case:{CASE_ID}",
                mutation_actor_ref="7", input_digest="d7",
            ),
            "post-write validator failure -> exception propagates, rollback engaged",
        )
    finally:
        timeline_engine.validate_timeline = _original_validate
    check(
        "post-write validator failure: no pending file was left behind",
        not timeline_engine.get_pending_path(CASE_ID).exists(),
    )
    check(
        "post-write validator failure: no audit was written",
        not timeline_engine.get_reviews_dir(CASE_ID).exists(),
    )
finally:
    timeline_engine.CASES_DIR = _original_timeline_engine_cases_dir
    timeline_validator.CASES_DIR = _original_timeline_validator_cases_dir
    shutil.rmtree(_tmp_root, ignore_errors=True)


# ============================================================
# 8) LEGACY CLI CLOSURE - main() refuses unconditionally, before
#    parsing anything, with the fixed Row 19C-3b refusal message on
#    stderr and a genuine SystemExit(2).
# ============================================================

_LEGACY_REFUSAL_PREFIX = "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3b)."

check(
    "timeline_engine._LEGACY_CLI_REFUSAL_MESSAGE carries the fixed, shared refusal prefix",
    timeline_engine._LEGACY_CLI_REFUSAL_MESSAGE.startswith(_LEGACY_REFUSAL_PREFIX),
    f"got {timeline_engine._LEGACY_CLI_REFUSAL_MESSAGE!r}",
)
check(
    "timeline_engine._LEGACY_CLI_REFUSAL_MESSAGE points to the real replacement command",
    "ui.cli_mutate generation" in timeline_engine._LEGACY_CLI_REFUSAL_MESSAGE
    and "--row-key timeline" in timeline_engine._LEGACY_CLI_REFUSAL_MESSAGE,
)
try:
    timeline_engine.main()
except SystemExit as exit_signal:
    check("timeline_engine.main() raises SystemExit(2) unconditionally", exit_signal.code == 2)
else:
    check("timeline_engine.main() raises SystemExit(2) unconditionally", False, "no SystemExit raised")


print(f"--- test_timeline_engine_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
