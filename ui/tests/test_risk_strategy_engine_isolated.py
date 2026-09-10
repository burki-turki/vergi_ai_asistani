# ============================================================
# ROW 19C-3c-ii - src/risk_strategy_engine.py ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator - mirrors
# test_issue_spotting_engine_isolated.py's structure, adapted for
# risk_strategy's write_pending(case_id, analysis, expected_issue_count,
# carried_ids=None, ...) signature, its --self-test-preserving CLI
# closure, and the confirmed fact that `write_carry_forward_audit()` is
# dead code in this file (never called, before or after this change).
#
# Run: python ui/tests/test_risk_strategy_engine_isolated.py
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

import risk_strategy_engine                                # noqa: E402
import risk_strategy_agent                                  # noqa: E402
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

_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_risk_strategy_engine_isolated_"))
_tmp_cases = _tmp_root / "cases"
_tmp_cases.mkdir(parents=True)


def _fresh_case_copy():
    dest = _tmp_cases / CASE_ID
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REAL_CASE_0001, dest)
    rs_dir = dest / "risk_strategy"
    if rs_dir.exists():
        for stale in rs_dir.glob("*.pending"):
            stale.unlink()
        for stale_dir_name in ("history", "generation_reviews"):
            stale_dir = rs_dir / stale_dir_name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
    return dest


# 0) additive constants sanity - source-of-truth check, no I/O.
check(
    "risk_strategy_agent.RISK_STRATEGY_AGENT_VERSION and DEFAULT_AGENT_MODEL exist",
    hasattr(risk_strategy_agent, "RISK_STRATEGY_AGENT_VERSION")
    and hasattr(risk_strategy_agent, "DEFAULT_AGENT_MODEL"),
)

_original_cases_dir = risk_strategy_engine.CASES_DIR

try:
    risk_strategy_engine.CASES_DIR = _tmp_cases

    # 1) partial mutation-binding guard
    _fresh_case_copy()
    pending_path_1 = risk_strategy_engine.get_pending_path(CASE_ID)
    expect_raises(
        risk_strategy_engine.RiskStrategyEngineError,
        lambda: risk_strategy_engine.write_pending(
            CASE_ID, {}, 6, mutation_idempotency_key="idk", mutation_resource_key=None,
            mutation_actor_ref="7", input_digest="d", identity_payload={},
        ),
        "write_pending(): partial mutation-binding rejected",
    )
    check("write_pending() partial-binding guard: zero filesystem writes", not pending_path_1.exists())

    # 2) coordinated write (deterministic mode)
    _fresh_case_copy()
    case_root_2 = agf._resolve_module_case_root_real(risk_strategy_engine, CASE_ID)
    paths_2 = agf._derive_verified_output_paths(risk_strategy_engine, case_root_2, CASE_ID, "risk_strategy")
    manifest_2 = agf._build_manifest_containers("risk_strategy", case_root_2, CASE_ID)
    check("manifest container count == 10 for risk_strategy", len(manifest_2) == 10)
    mode_2, model_2, prompt_2 = agf._resolve_generation_provenance("risk_strategy", False, None)
    payload_2 = agf._build_identity_payload(manifest_2, mode_2, model_2, prompt_2)
    payload_bytes_2 = agf._canonical_identity_bytes(payload_2)
    input_digest_2 = agf._compute_input_digest(payload_bytes_2)

    build_result_2 = risk_strategy_engine.build_risk_strategy_engine_output(
        CASE_ID, use_agent=False, llm_client=None, network_allowed=False,
    )
    analysis_2 = build_result_2["analysis"]
    frozen_2 = agf._freeze_pending_bytes(analysis_2)
    candidate_2 = json.loads(frozen_2.decode("utf-8"))
    identity_for_audit_2 = json.loads(payload_bytes_2.decode("utf-8"))

    write_result_2 = risk_strategy_engine.write_pending(
        CASE_ID, candidate_2, build_result_2["issue_count"],
        verified_paths=paths_2, input_digest=input_digest_2, identity_payload=identity_for_audit_2,
        mutation_idempotency_key="TESTKEY1", mutation_resource_key="case:case_0001",
        mutation_actor_ref="42",
    )
    check("coordinated write_pending(): pending bytes == frozen bytes", paths_2.pending_path.read_bytes() == frozen_2)
    audit_record_2 = json.loads(write_result_2["audit_path"].read_text(encoding="utf-8"))
    check(
        "audit record: action_family/target_ref exact",
        audit_record_2["action_family"] == "generation.risk_strategy"
        and audit_record_2["target_ref"] == "risk_strategy.pending",
    )

    # 3) agent-mode provenance: real model_id/prompt_agent_version from
    #    risk_strategy_agent, read via importlib at call time.
    mode_3, model_3, prompt_3 = agf._resolve_generation_provenance("risk_strategy", True, None)
    check(
        "agent mode: model_id/prompt_agent_version are the REAL risk_strategy_agent constants",
        mode_3 == "agent"
        and model_3 == risk_strategy_agent.DEFAULT_AGENT_MODEL
        and prompt_3 == risk_strategy_agent.RISK_STRATEGY_AGENT_VERSION,
    )

    # 4) injected client: model_id becomes sentinel, prompt_agent_version
    #    stays the REAL constant (not a sentinel).
    class _FakeClient:
        def generate(self, prompt):
            raise AssertionError("must not be called by provenance resolution")

    mode_4, model_4, prompt_4 = agf._resolve_generation_provenance("risk_strategy", True, _FakeClient())
    check(
        "injected client: model_id sentinel, prompt_agent_version REAL (not sentinel)",
        model_4 == "external_injected_client" and prompt_4 == risk_strategy_agent.RISK_STRATEGY_AGENT_VERSION,
    )

    # 5) write_carry_forward_audit is confirmed dead code in this file -
    #    never called from write_pending() regardless of mutation binding.
    check(
        "risk_strategy_engine.write_carry_forward_audit exists but write_pending() takes no "
        "carry_records parameter (dead-code family, unlike argument)",
        hasattr(risk_strategy_engine, "write_carry_forward_audit")
        and "carry_records" not in risk_strategy_engine.write_pending.__code__.co_varnames,
    )

finally:
    risk_strategy_engine.CASES_DIR = _original_cases_dir
    shutil.rmtree(_tmp_root, ignore_errors=True)


# 6) legacy CLI closure - --self-test preserved.
import io
import contextlib

_argv_backup = sys.argv
try:
    sys.argv = ["risk_strategy_engine.py", "--case", CASE_ID]
    stderr_capture = io.StringIO()
    exit_code = None
    with contextlib.redirect_stderr(stderr_capture):
        try:
            risk_strategy_engine.main()
        except SystemExit as exit_signal:
            exit_code = exit_signal.code
    check("risk_strategy_engine.main() raises SystemExit(2)", exit_code == 2)
    check(
        "risk_strategy_engine.main() refusal points to --row-key risk_strategy",
        "ui.cli_mutate generation" in stderr_capture.getvalue()
        and "--row-key risk_strategy" in stderr_capture.getvalue(),
        stderr_capture.getvalue(),
    )
finally:
    sys.argv = _argv_backup

check("risk_strategy_engine.run_self_test still exists", hasattr(risk_strategy_engine, "run_self_test"))


print(f"--- test_risk_strategy_engine_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
