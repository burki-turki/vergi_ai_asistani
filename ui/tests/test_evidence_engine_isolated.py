# ============================================================
# ROW 19C-3c-ii - src/evidence_engine.py ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator - see
# test_issue_spotting_engine_isolated.py's own header for the shared
# rationale (this file mirrors its structure exactly, adapted for
# evidence's write_pending(case_id, analysis, expected_issue_count, ...)
# signature and --self-test-preserving CLI closure).
#
# Run: python ui/tests/test_evidence_engine_isolated.py
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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import evidence_engine                                    # noqa: E402
from ui.services import agent_generation_mutation_facade as agf  # noqa: E402

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

_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_evidence_engine_isolated_"))
_tmp_cases = _tmp_root / "cases"
_tmp_cases.mkdir(parents=True)


def _fresh_case_copy():
    dest = _tmp_cases / CASE_ID
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REAL_CASE_0001, dest)
    evidence_dir = dest / "evidence"
    if evidence_dir.exists():
        for stale in evidence_dir.glob("*.pending"):
            stale.unlink()
        for stale_dir_name in ("history", "generation_reviews"):
            stale_dir = evidence_dir / stale_dir_name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
    return dest


_original_cases_dir = evidence_engine.CASES_DIR

try:
    evidence_engine.CASES_DIR = _tmp_cases

    # 1) partial mutation-binding guard
    _fresh_case_copy()
    pending_path_1 = evidence_engine.get_pending_path(CASE_ID)
    expect_raises(
        evidence_engine.EvidenceEngineError,
        lambda: evidence_engine.write_pending(
            CASE_ID, {}, 6, mutation_idempotency_key="idk", mutation_resource_key=None,
            mutation_actor_ref="7", input_digest="d", identity_payload={},
        ),
        "write_pending(): partial mutation-binding rejected",
    )
    check("write_pending() partial-binding guard: zero filesystem writes", not pending_path_1.exists())

    # 2) legacy run_engine() call
    _fresh_case_copy()
    result_2 = evidence_engine.run_engine(case_id=CASE_ID)
    check(
        "run_engine() legacy call: dict return with pending_path/validation",
        all(k in result_2 for k in ("pending_path", "validation", "previous_pending_history")),
    )
    check("run_engine() legacy call: pending was written", Path(result_2["pending_path"]).exists())
    check(
        "run_engine() legacy call: zero generation_reviews/ directory created",
        not evidence_engine.get_reviews_dir(CASE_ID).exists(),
    )

    # 3) coordinated write
    _fresh_case_copy()
    case_root_3 = agf._resolve_module_case_root_real(evidence_engine, CASE_ID)
    paths_3 = agf._derive_verified_output_paths(evidence_engine, case_root_3, CASE_ID, "evidence")
    manifest_3 = agf._build_manifest_containers("evidence", case_root_3, CASE_ID)
    check("manifest container count == 3 for evidence", len(manifest_3) == 3)
    mode_3, model_3, prompt_3 = agf._resolve_generation_provenance("evidence", False, None)
    payload_3 = agf._build_identity_payload(manifest_3, mode_3, model_3, prompt_3)
    payload_bytes_3 = agf._canonical_identity_bytes(payload_3)
    input_digest_3 = agf._compute_input_digest(payload_bytes_3)

    build_result_3 = evidence_engine.build_evidence_engine_output(
        CASE_ID, use_agent=False, llm_client=None, network_allowed=False,
    )
    analysis_3 = build_result_3["analysis"]
    frozen_3 = agf._freeze_pending_bytes(analysis_3)
    candidate_3 = json.loads(frozen_3.decode("utf-8"))
    identity_for_audit_3 = json.loads(payload_bytes_3.decode("utf-8"))

    write_result_3 = evidence_engine.write_pending(
        CASE_ID, candidate_3, build_result_3["issue_count"],
        verified_paths=paths_3, input_digest=input_digest_3, identity_payload=identity_for_audit_3,
        mutation_idempotency_key="TESTKEY1", mutation_resource_key="case:case_0001",
        mutation_actor_ref="42",
    )
    check("coordinated write_pending(): pending bytes == frozen bytes", paths_3.pending_path.read_bytes() == frozen_3)
    check(
        "coordinated write_pending(): pending_sha256 == sha256(frozen bytes)",
        write_result_3["pending_sha256"] == hashlib.sha256(frozen_3).hexdigest(),
    )
    audit_record_3 = json.loads(write_result_3["audit_path"].read_text(encoding="utf-8"))
    check(
        "audit record: action_family/target_ref/channel exact",
        audit_record_3["action_family"] == "generation.evidence"
        and audit_record_3["target_ref"] == "evidence.pending"
        and audit_record_3["channel"] == "local_lawyer_generation_cli",
    )
    check("audit record: identity_payload matches frozen payload", audit_record_3["identity_payload"] == identity_for_audit_3)

    # 4) evidence never reads its own canonical evidence.json (re-confirmed
    #    at runtime - build must succeed identically whether or not a
    #    canonical evidence.json exists in the fixture, since case_0001's
    #    canonical evidence.json genuinely does not exist yet - Row 12).
    check(
        "evidence build succeeded without any canonical evidence.json present",
        not evidence_engine.get_canonical_path(CASE_ID).exists(),
    )

finally:
    evidence_engine.CASES_DIR = _original_cases_dir
    shutil.rmtree(_tmp_root, ignore_errors=True)


# 5) legacy CLI closure - --self-test path preserved, mutation path closed.
import io
import contextlib

_argv_backup = sys.argv
try:
    sys.argv = ["evidence_engine.py", "--case", CASE_ID]
    stderr_capture = io.StringIO()
    exit_code = None
    with contextlib.redirect_stderr(stderr_capture):
        try:
            evidence_engine.main()
        except SystemExit as exit_signal:
            exit_code = exit_signal.code
    check("evidence_engine.main() raises SystemExit(2)", exit_code == 2)
    check(
        "evidence_engine.main() refusal message points to ui.cli_mutate generation --row-key evidence",
        "ui.cli_mutate generation" in stderr_capture.getvalue()
        and "--row-key evidence" in stderr_capture.getvalue(),
        stderr_capture.getvalue(),
    )
finally:
    sys.argv = _argv_backup

check(
    "evidence_engine.run_self_test still exists (preserved --self-test path)",
    hasattr(evidence_engine, "run_self_test"),
)


print(f"--- test_evidence_engine_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
