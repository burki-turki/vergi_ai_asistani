# ============================================================
# ROW 19C-3c-ii - src/argument_engine.py ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator - mirrors the
# other four engines' isolated test structure, PLUS argument-specific
# coverage: `write_carry_forward_audit_enabled=False` (zero filesystem
# mutation during build), the ordered dual-audit-write (carry-forward
# first, coordinator second) with real, non-empty carry_records, and
# the best-effort cleanup on coordinator-audit-write failure (proving
# the carry-forward file does not survive as an orphan when the
# coordinator audit write fails immediately after it).
#
# Run: python ui/tests/test_argument_engine_isolated.py
# ============================================================

import dataclasses
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

import argument_engine                                       # noqa: E402
from ui.services import agent_generation_mutation_facade as agf  # noqa: E402
from ui.services import agent_generation_mutation_adapters as ada  # noqa: E402

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

_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_argument_engine_isolated_"))
_tmp_cases = _tmp_root / "cases"
_tmp_cases.mkdir(parents=True)


def _fresh_case_copy():
    dest = _tmp_cases / CASE_ID
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REAL_CASE_0001, dest)
    arg_dir = dest / "arguments"
    if arg_dir.exists():
        for stale in arg_dir.glob("*.pending"):
            stale.unlink()
        for stale_dir_name in ("generation_reviews",):
            stale_dir = arg_dir / stale_dir_name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
        # NOTE: history/ (which nests carry_forward/) is intentionally
        # NOT wiped here for test 1-3 (matches the other engines'
        # convention for the base history dir), but each test below
        # that specifically checks carry_forward/ state re-derives a
        # completely fresh case copy first, so no cross-test leakage.
    return dest


_original_cases_dir = argument_engine.CASES_DIR

try:
    argument_engine.CASES_DIR = _tmp_cases

    # 1) partial mutation-binding guard
    _fresh_case_copy()
    pending_path_1 = argument_engine.get_pending_path(CASE_ID)
    expect_raises(
        argument_engine.ArgumentEngineError,
        lambda: argument_engine.write_pending(
            CASE_ID, {}, 6, mutation_idempotency_key="idk", mutation_resource_key=None,
            mutation_actor_ref="7", input_digest="d", identity_payload={},
        ),
        "write_pending(): partial mutation-binding rejected",
    )
    check("write_pending() partial-binding guard: zero filesystem writes", not pending_path_1.exists())

    # 2) build_argument_engine_output(write_carry_forward_audit_enabled=False)
    #    -> ZERO filesystem mutation, carry_forward_audit_path is None,
    #    carry_records is exposed in the return dict.
    _fresh_case_copy()
    carry_dir_2 = argument_engine.get_carry_forward_dir(CASE_ID)
    check("carry_forward_dir does not exist before build", not carry_dir_2.exists())
    build_result_2 = argument_engine.build_argument_engine_output(
        CASE_ID, use_agent=False, llm_client=None, network_allowed=False,
        write_carry_forward_audit_enabled=False,
    )
    check(
        "coordinated-mode build: carry_forward_audit_path is None (deferred, not written)",
        build_result_2["carry_forward_audit_path"] is None,
    )
    check("coordinated-mode build: carry_records key present in return dict", "carry_records" in build_result_2)
    check("coordinated-mode build: ZERO filesystem mutation (carry_forward_dir still absent)", not carry_dir_2.exists())

    # 3) legacy build (write_carry_forward_audit_enabled=True, default) -
    #    behavior UNCHANGED, byte-for-byte, from before this slice.
    _fresh_case_copy()
    build_result_3 = argument_engine.build_argument_engine_output(
        CASE_ID, use_agent=False, llm_client=None, network_allowed=False,
    )
    check(
        "legacy-mode build (default): carry_forward_audit_path is None when carry_records is empty "
        "(case_0001's offline baseline has zero claims to carry forward)",
        build_result_3["carry_forward_audit_path"] is None and build_result_3["carry_records"] == [],
    )

    # 4) coordinated write with a REAL, non-empty carry_records - proves
    #    the ordered dual-audit-write (carry-forward first, coordinator
    #    second) and the exact carry_forward_audit_path/_sha256 binding.
    _fresh_case_copy()
    case_root_4 = agf._resolve_module_case_root_real(argument_engine, CASE_ID)
    paths_4 = agf._derive_verified_output_paths(argument_engine, case_root_4, CASE_ID, "argument")
    manifest_4 = agf._build_manifest_containers("argument", case_root_4, CASE_ID)
    check("manifest container count == 8 for argument", len(manifest_4) == 8)
    mode_4, model_4, prompt_4 = agf._resolve_generation_provenance("argument", False, None)
    payload_4 = agf._build_identity_payload(manifest_4, mode_4, model_4, prompt_4)
    payload_bytes_4 = agf._canonical_identity_bytes(payload_4)
    input_digest_4 = agf._compute_input_digest(payload_bytes_4)
    identity_for_audit_4 = json.loads(payload_bytes_4.decode("utf-8"))

    build_result_4 = argument_engine.build_argument_engine_output(
        CASE_ID, use_agent=False, llm_client=None, network_allowed=False,
        write_carry_forward_audit_enabled=False,
    )
    analysis_4 = build_result_4["analysis"]
    frozen_4 = agf._freeze_pending_bytes(analysis_4)
    candidate_4 = json.loads(frozen_4.decode("utf-8"))

    synthetic_carry_records = [
        {"entity_type": "claim", "previous_id": "x", "new_id": "y", "fingerprint": "f", "carried_state": "confirmed"},
    ]
    frozen_carry_4 = agf._freeze_json_bytes(synthetic_carry_records)
    carry_for_write_4 = json.loads(frozen_carry_4.decode("utf-8"))
    synthetic_carry_records.append({"MUTATED": "after-freeze"})  # mutate original after freeze
    check(
        "reconstructed carry_records is unaffected by post-freeze mutation of the original list",
        carry_for_write_4 != synthetic_carry_records and len(carry_for_write_4) == 1,
    )

    write_result_4 = argument_engine.write_pending(
        CASE_ID, candidate_4, build_result_4["issue_count"],
        carried_ids=build_result_4["carried_ids"], carry_records=carry_for_write_4,
        verified_paths=paths_4, input_digest=input_digest_4, identity_payload=identity_for_audit_4,
        mutation_idempotency_key="ARGKEY1", mutation_resource_key="case:case_0001",
        mutation_actor_ref="42",
    )
    audit_record_4 = json.loads(write_result_4["audit_path"].read_text(encoding="utf-8"))
    cf_path_4 = audit_record_4.get("carry_forward_audit_path")
    cf_sha_4 = audit_record_4.get("carry_forward_audit_sha256")
    check("audit record: carry_forward_audit_path/sha256 both set", cf_path_4 is not None and cf_sha_4 is not None)
    cf_file_4 = Path(cf_path_4)
    check("carry-forward audit file exists", cf_file_4.exists())
    check(
        "carry-forward audit file's raw-byte hash matches the recorded sha256",
        hashlib.sha256(cf_file_4.read_bytes()).hexdigest() == cf_sha_4,
    )
    cf_content_4 = json.loads(cf_file_4.read_text(encoding="utf-8"))
    check(
        "carry-forward audit content: audit_type/case_id exact",
        cf_content_4.get("audit_type") == "argument_review_carry_forward" and cf_content_4.get("case_id") == CASE_ID,
    )

    # 5) adapter independently re-verifies this exact record, including
    #    the carry-forward binding, end to end.
    matches_5 = ada._audit_record_matches(
        audit_record_4, "argument",
        idempotency_key="ARGKEY1", resource_key="case:case_0001",
        action_family="generation.argument", target_ref="argument.pending",
        target_state="generated", actor_label="42", pending_sha256=write_result_4["pending_sha256"],
        carry_forward_dir_verified=paths_4.carry_forward_dir,
    )
    check("adapter _audit_record_matches: full match including carry-forward binding", matches_5)

    tampered_5 = dict(audit_record_4)
    tampered_5["carry_forward_audit_sha256"] = "0" * 64
    matches_tampered_5 = ada._audit_record_matches(
        tampered_5, "argument",
        idempotency_key="ARGKEY1", resource_key="case:case_0001",
        action_family="generation.argument", target_ref="argument.pending",
        target_state="generated", actor_label="42", pending_sha256=write_result_4["pending_sha256"],
        carry_forward_dir_verified=paths_4.carry_forward_dir,
    )
    check("adapter _audit_record_matches: tampered carry-forward hash -> False", not matches_tampered_5)

    both_none_or_neither_5 = dict(audit_record_4)
    both_none_or_neither_5["carry_forward_audit_sha256"] = None
    matches_partial_5 = ada._audit_record_matches(
        both_none_or_neither_5, "argument",
        idempotency_key="ARGKEY1", resource_key="case:case_0001",
        action_family="generation.argument", target_ref="argument.pending",
        target_state="generated", actor_label="42", pending_sha256=write_result_4["pending_sha256"],
        carry_forward_dir_verified=paths_4.carry_forward_dir,
    )
    check(
        "adapter _audit_record_matches: path-set/hash-None asymmetry (fail-closed) -> False",
        not matches_partial_5,
    )

    # 6) ROLLBACK/CLEANUP: force the coordinator-audit write (the SECOND
    #    step) to fail AFTER the carry-forward audit (the FIRST step)
    #    already succeeded - proves (a) the whole write_pending() call
    #    raises, (b) pending is fully rolled back, and (c) the orphaned
    #    carry-forward audit file is removed by the best-effort cleanup.
    _fresh_case_copy()
    case_root_6 = agf._resolve_module_case_root_real(argument_engine, CASE_ID)
    paths_6 = agf._derive_verified_output_paths(argument_engine, case_root_6, CASE_ID, "argument")
    manifest_6 = agf._build_manifest_containers("argument", case_root_6, CASE_ID)
    mode_6, model_6, prompt_6 = agf._resolve_generation_provenance("argument", False, None)
    payload_6 = agf._build_identity_payload(manifest_6, mode_6, model_6, prompt_6)
    payload_bytes_6 = agf._canonical_identity_bytes(payload_6)
    input_digest_6 = agf._compute_input_digest(payload_bytes_6)
    identity_for_audit_6 = json.loads(payload_bytes_6.decode("utf-8"))

    build_result_6 = argument_engine.build_argument_engine_output(
        CASE_ID, use_agent=False, llm_client=None, network_allowed=False,
        write_carry_forward_audit_enabled=False,
    )
    frozen_6 = agf._freeze_pending_bytes(build_result_6["analysis"])
    candidate_6 = json.loads(frozen_6.decode("utf-8"))
    synthetic_carry_records_6 = [
        {"entity_type": "claim", "previous_id": "x", "new_id": "y", "fingerprint": "f", "carried_state": "confirmed"},
    ]

    pending_existed_before_6 = paths_6.pending_path.exists()

    # Force the reviews_dir mkdir to fail: put a FILE where the directory
    # needs to be created.
    paths_6.reviews_dir.parent.mkdir(parents=True, exist_ok=True)
    with open(paths_6.reviews_dir, "w", encoding="utf-8") as blocker_file:
        blocker_file.write("blocker")

    raised_6 = False
    try:
        argument_engine.write_pending(
            CASE_ID, candidate_6, build_result_6["issue_count"],
            carried_ids=build_result_6["carried_ids"], carry_records=synthetic_carry_records_6,
            verified_paths=paths_6, input_digest=input_digest_6, identity_payload=identity_for_audit_6,
            mutation_idempotency_key="ARGROLLBACK", mutation_resource_key="case:case_0001",
            mutation_actor_ref="42",
        )
    except Exception:  # noqa: BLE001
        raised_6 = True

    check("rollback scenario: write_pending() raised as expected", raised_6)
    check(
        "rollback scenario: pending existence state unchanged (fully rolled back)",
        paths_6.pending_path.exists() == pending_existed_before_6,
    )
    carry_dir_contents_6 = (
        [p.name for p in paths_6.carry_forward_dir.iterdir()] if paths_6.carry_forward_dir.exists() else []
    )
    check(
        "rollback scenario: carry-forward audit best-effort cleanup left ZERO orphaned files",
        carry_dir_contents_6 == [],
        f"found: {carry_dir_contents_6}",
    )

finally:
    argument_engine.CASES_DIR = _original_cases_dir
    shutil.rmtree(_tmp_root, ignore_errors=True)


# 7) legacy CLI closure - --self-test preserved.
import io
import contextlib

_argv_backup = sys.argv
try:
    sys.argv = ["argument_engine.py", "--case", CASE_ID]
    stderr_capture = io.StringIO()
    exit_code = None
    with contextlib.redirect_stderr(stderr_capture):
        try:
            argument_engine.main()
        except SystemExit as exit_signal:
            exit_code = exit_signal.code
    check("argument_engine.main() raises SystemExit(2)", exit_code == 2)
    check(
        "argument_engine.main() refusal points to --row-key argument",
        "ui.cli_mutate generation" in stderr_capture.getvalue()
        and "--row-key argument" in stderr_capture.getvalue(),
        stderr_capture.getvalue(),
    )
finally:
    sys.argv = _argv_backup

check("argument_engine.run_self_test still exists", hasattr(argument_engine, "run_self_test"))


print(f"--- test_argument_engine_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
