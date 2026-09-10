# ============================================================
# ROW 19C-3c-ii - src/drafting_engine.py ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator - mirrors
# test_risk_strategy_engine_isolated.py's structure, adapted for
# drafting's `lawyer_input=None` build kwarg (Row 15 Q1/Q2 unaffected)
# and its 12-container manifest.
#
# Run: python ui/tests/test_drafting_engine_isolated.py
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

import drafting_engine                                      # noqa: E402
import drafting_agent                                        # noqa: E402
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

_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_drafting_engine_isolated_"))
_tmp_cases = _tmp_root / "cases"
_tmp_cases.mkdir(parents=True)


def _fresh_case_copy():
    dest = _tmp_cases / CASE_ID
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REAL_CASE_0001, dest)
    dr_dir = dest / "drafting"
    if dr_dir.exists():
        for stale in dr_dir.glob("*.pending"):
            stale.unlink()
        for stale_dir_name in ("history", "generation_reviews"):
            stale_dir = dr_dir / stale_dir_name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
    return dest


check(
    "drafting_agent.DRAFTING_AGENT_VERSION and DEFAULT_AGENT_MODEL exist",
    hasattr(drafting_agent, "DRAFTING_AGENT_VERSION") and hasattr(drafting_agent, "DEFAULT_AGENT_MODEL"),
)

_original_cases_dir = drafting_engine.CASES_DIR

try:
    drafting_engine.CASES_DIR = _tmp_cases

    # 1) partial mutation-binding guard
    _fresh_case_copy()
    pending_path_1 = drafting_engine.get_pending_path(CASE_ID)
    expect_raises(
        drafting_engine.DraftingEngineError,
        lambda: drafting_engine.write_pending(
            CASE_ID, {}, 6, mutation_idempotency_key="idk", mutation_resource_key=None,
            mutation_actor_ref="7", input_digest="d", identity_payload={},
        ),
        "write_pending(): partial mutation-binding rejected",
    )
    check("write_pending() partial-binding guard: zero filesystem writes", not pending_path_1.exists())

    # 2) coordinated write (deterministic, no lawyer_input saved - the
    #    real case_0001 fixture has none, exactly as the checkpoint
    #    history documents).
    _fresh_case_copy()
    case_root_2 = agf._resolve_module_case_root_real(drafting_engine, CASE_ID)
    paths_2 = agf._derive_verified_output_paths(drafting_engine, case_root_2, CASE_ID, "drafting")
    manifest_2 = agf._build_manifest_containers("drafting", case_root_2, CASE_ID)
    check("manifest container count == 12 for drafting", len(manifest_2) == 12)
    lawyer_input_container = next(c for c in manifest_2 if c["logical_name"] == "lawyer_input")
    check(
        "lawyer_input manifest entry state=missing (no saved wrapper in fixture)",
        lawyer_input_container["state"] == "missing",
    )
    lawyer_input_2 = agf._load_drafting_lawyer_input(CASE_ID)
    check("_load_drafting_lawyer_input returns None when no wrapper saved", lawyer_input_2 is None)

    mode_2, model_2, prompt_2 = agf._resolve_generation_provenance("drafting", False, None)
    payload_2 = agf._build_identity_payload(manifest_2, mode_2, model_2, prompt_2)
    payload_bytes_2 = agf._canonical_identity_bytes(payload_2)
    input_digest_2 = agf._compute_input_digest(payload_bytes_2)

    build_result_2 = drafting_engine.build_drafting_engine_output(
        CASE_ID, lawyer_input=lawyer_input_2, use_agent=False, llm_client=None, network_allowed=False,
    )
    analysis_2 = build_result_2["analysis"]
    frozen_2 = agf._freeze_pending_bytes(analysis_2)
    candidate_2 = json.loads(frozen_2.decode("utf-8"))
    identity_for_audit_2 = json.loads(payload_bytes_2.decode("utf-8"))

    write_result_2 = drafting_engine.write_pending(
        CASE_ID, candidate_2, build_result_2["issue_count"],
        verified_paths=paths_2, input_digest=input_digest_2, identity_payload=identity_for_audit_2,
        mutation_idempotency_key="TESTKEY1", mutation_resource_key="case:case_0001",
        mutation_actor_ref="42",
    )
    check("coordinated write_pending(): pending bytes == frozen bytes", paths_2.pending_path.read_bytes() == frozen_2)
    audit_record_2 = json.loads(write_result_2["audit_path"].read_text(encoding="utf-8"))
    check(
        "audit record: action_family/target_ref exact",
        audit_record_2["action_family"] == "generation.drafting"
        and audit_record_2["target_ref"] == "drafting.pending",
    )

    # 3) agent-mode / injected-client provenance
    mode_3, model_3, prompt_3 = agf._resolve_generation_provenance("drafting", True, None)
    check(
        "agent mode: model_id/prompt_agent_version are the REAL drafting_agent constants",
        model_3 == drafting_agent.DEFAULT_AGENT_MODEL and prompt_3 == drafting_agent.DRAFTING_AGENT_VERSION,
    )

    class _FakeClient:
        def generate(self, prompt):
            raise AssertionError("must not be called by provenance resolution")

    mode_4, model_4, prompt_4 = agf._resolve_generation_provenance("drafting", True, _FakeClient())
    check(
        "injected client: model_id sentinel, prompt_agent_version REAL",
        model_4 == "external_injected_client" and prompt_4 == drafting_agent.DRAFTING_AGENT_VERSION,
    )

    # 4) write_carry_forward_audit dead-code confirmation (same as
    #    risk_strategy - drafting has no carry_records parameter either).
    check(
        "drafting write_pending() takes no carry_records parameter",
        "carry_records" not in drafting_engine.write_pending.__code__.co_varnames,
    )

finally:
    drafting_engine.CASES_DIR = _original_cases_dir
    shutil.rmtree(_tmp_root, ignore_errors=True)


# 5) legacy CLI closure - --self-test preserved.
import io
import contextlib

_argv_backup = sys.argv
try:
    sys.argv = ["drafting_engine.py", "--case", CASE_ID]
    stderr_capture = io.StringIO()
    exit_code = None
    with contextlib.redirect_stderr(stderr_capture):
        try:
            drafting_engine.main()
        except SystemExit as exit_signal:
            exit_code = exit_signal.code
    check("drafting_engine.main() raises SystemExit(2)", exit_code == 2)
    check(
        "drafting_engine.main() refusal points to --row-key drafting",
        "ui.cli_mutate generation" in stderr_capture.getvalue()
        and "--row-key drafting" in stderr_capture.getvalue(),
        stderr_capture.getvalue(),
    )
finally:
    sys.argv = _argv_backup

check("drafting_engine.run_self_test still exists", hasattr(drafting_engine, "run_self_test"))


print(f"--- test_drafting_engine_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
