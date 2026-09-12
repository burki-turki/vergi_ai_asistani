# ============================================================
# ROW 19C-3c-iv SLICE 1 -
# ui/services/legal_research_case_law_mutation_facade.py ISOLATED
# TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator connection -
# exercises the facade's own pure/read-only functions directly: usage-
# shape validation (row_key/expected_input_digest, both row_keys), the
# containment-before-traversal manifest scanner across TWO independent
# containment roots (case-scoped `case_root_real` AND data-root-scoped
# `data_root_real` for the global `documents.json`/`provisions.json`
# inputs - including real Windows NTFS junctions for escaping/broken-
# link cases on the case-scoped side, and a `Path.glob()` zero-call
# mechanical proof), deterministic/agent/injected-client provenance
# resolution (including the per-row_key DIFFERENT `engine_version`
# constants), and identity payload freeze/reconstruct (7-key shape,
# `case_id`/`engine_version` included, two distinct `manifest_version`
# literals). End-to-end coordinated `apply_generation()` mutation
# scenarios (fresh mutation/safe replay/idempotency-conflict/composite
# race/writer-crash/reconciliation/authz denial) are deliberately left
# to `test_legal_research_case_law_mutation_integration_postgres.py`
# (a real PostgreSQL server) - mirrors `test_agent_generation_mutation_
# facade_isolated.py`'s own split exactly (that file, too, contains no
# end-to-end `apply_generation()` test).
#
# Run: python ui/tests/test_legal_research_case_law_mutation_facade_isolated.py
# ============================================================

import builtins
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import legal_research_engine as lre                           # noqa: E402
import case_law_engine as cle                                  # noqa: E402
import legal_research_agent                                    # noqa: E402
import case_law_agent                                           # noqa: E402
from ui.services import legal_research_case_law_mutation_facade as fac  # noqa: E402

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


# ============================================================
# 1) Row-key/action-family/target-ref helpers - pure, no I/O.
# ============================================================

check(
    "LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME has exactly the two expected families",
    dict(fac.LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME) == {
        "legal_research": "legal_research_engine", "case_law": "case_law_engine",
    },
)
check(
    "legal_research_case_law_action_family_for produces the exact generation.<row_key> string, "
    "for both row_keys",
    fac.legal_research_case_law_action_family_for("legal_research") == "generation.legal_research"
    and fac.legal_research_case_law_action_family_for("case_law") == "generation.case_law",
)
expect_raises(
    KeyError, lambda: fac.legal_research_case_law_action_family_for("not_a_real_family"),
    "legal_research_case_law_action_family_for: unknown row_key raises KeyError",
)
check(
    "legal_research_case_law_target_ref_for produces the exact <row_key>.pending string "
    "(case_id-free, resource_key already carries it)",
    fac.legal_research_case_law_target_ref_for("legal_research") == "legal_research.pending"
    and fac.legal_research_case_law_target_ref_for("case_law") == "case_law.pending",
)
check(
    "FAMILY_LOGICAL_NAME_COUNTS is exactly 6/4",
    fac.FAMILY_LOGICAL_NAME_COUNTS == {"legal_research": 6, "case_law": 4},
)


# ============================================================
# 2) Usage-shape validation - pure, no I/O, before any connection. This
#    family's network gate mirrors agent_generation's (allow_network
#    requires with_agent; both optional) - NOT fact_extraction's
#    stricter unconditional with_agent requirement (this family HAS a
#    deterministic mode).
# ============================================================

expect_raises(
    KeyError, lambda: fac._check_argument_shapes("not_a_real_family", for_apply=False),
    "_check_argument_shapes: unknown row_key raises KeyError",
)
expect_raises(
    fac.LegalResearchCaseLawArgumentError,
    lambda: fac._check_argument_shapes("legal_research", None, for_apply=True),
    "_check_argument_shapes: apply without expected_input_digest raises "
    "LegalResearchCaseLawArgumentError",
)
try:
    fac._check_argument_shapes("legal_research", "somedigest", for_apply=True)
    check("_check_argument_shapes: apply WITH expected_input_digest passes", True)
except Exception as error:  # noqa: BLE001
    check("_check_argument_shapes: apply WITH expected_input_digest passes", False, str(error))
try:
    fac._check_argument_shapes("case_law", for_apply=False)
    check("_check_argument_shapes: case_law preview (no digest needed) passes", True)
except Exception as error:  # noqa: BLE001
    check("_check_argument_shapes: case_law preview (no digest needed) passes", False, str(error))


# ============================================================
# 3) Model/prompt/engine provenance - deterministic / agent /
#    injected-client, read fresh via importlib each call (no caching).
#    engine_version is call-time read from the MODULE, per row_key.
# ============================================================

mode_a, model_a, engine_a, prompt_a = fac._resolve_generation_provenance(lre, "legal_research", False, None)
check(
    "legal_research deterministic mode: model_id/prompt_agent_version are the closed sentinels, "
    "engine_version is the REAL LEGAL_RESEARCH_ENGINE_VERSION constant",
    mode_a == "deterministic" and model_a == "deterministic_no_model" and prompt_a == "n/a"
    and engine_a == lre.LEGAL_RESEARCH_ENGINE_VERSION,
)

mode_b, model_b, engine_b, prompt_b = fac._resolve_generation_provenance(lre, "legal_research", True, None)
check(
    "legal_research real agent mode: model_id/prompt_agent_version are the REAL "
    "legal_research_agent constants",
    model_b == legal_research_agent.DEFAULT_AGENT_MODEL
    and prompt_b == legal_research_agent.LEGAL_RESEARCH_AGENT_VERSION,
)


class _FakeLLMClient:
    def generate(self, prompt):
        raise AssertionError("provenance resolution must never call .generate()")


mode_c, model_c, engine_c, prompt_c = fac._resolve_generation_provenance(
    lre, "legal_research", True, _FakeLLMClient(),
)
check(
    "injected client: model_id sentinel, engine_version/prompt_agent_version REAL (not "
    "sentinels), .generate() never called",
    model_c == "external_injected_client" and engine_c == lre.LEGAL_RESEARCH_ENGINE_VERSION
    and prompt_c == legal_research_agent.LEGAL_RESEARCH_AGENT_VERSION,
)

mode_d, model_d, engine_d, prompt_d = fac._resolve_generation_provenance(lre, "legal_research", False, _FakeLLMClient())
check(
    "deterministic mode ignores a supplied llm_client entirely",
    mode_d == "deterministic" and model_d == "deterministic_no_model" and prompt_d == "n/a",
)

mode_e, model_e, engine_e, prompt_e = fac._resolve_generation_provenance(cle, "case_law", True, None)
check(
    "case_law real agent mode: model_id/prompt_agent_version are the REAL case_law_agent "
    "constants, engine_version is CASE_LAW_ENGINE_VERSION ('2') - DIFFERENT from "
    "legal_research's ('1')",
    model_e == case_law_agent.DEFAULT_AGENT_MODEL and prompt_e == case_law_agent.CASE_LAW_AGENT_VERSION
    and engine_e == cle.CASE_LAW_ENGINE_VERSION and engine_e != lre.LEGAL_RESEARCH_ENGINE_VERSION,
)


# ============================================================
# 4) Identity payload freeze/reconstruct - canonical bytes, exact
#    round-trip, mutation-after-freeze does not leak, exactly 7 keys,
#    two DISTINCT manifest_version literals per row_key.
# ============================================================

payload_f = fac._build_identity_payload(
    "legal_research", CASE_ID, [{"logical_name": "issues", "state": "present", "files": []}],
    "deterministic", "deterministic_no_model", lre.LEGAL_RESEARCH_ENGINE_VERSION, "n/a",
)
check(
    "identity_payload has exactly the 7 expected keys",
    set(payload_f.keys()) == {
        "manifest_version", "case_id", "manifest", "generation_mode", "model_id",
        "engine_version", "prompt_agent_version",
    },
)
check(
    "identity_payload.case_id round-trips the exact case_id given",
    payload_f["case_id"] == CASE_ID,
)
check(
    "legal_research manifest_version and case_law manifest_version are two DISTINCT literals",
    fac._MANIFEST_VERSION_BY_ROW_KEY["legal_research"] != fac._MANIFEST_VERSION_BY_ROW_KEY["case_law"],
)
bytes_f1 = fac._canonical_identity_bytes(payload_f)
bytes_f2 = fac._canonical_identity_bytes(json.loads(json.dumps(payload_f)))
check("canonical identity bytes are deterministic across equal-content payloads", bytes_f1 == bytes_f2)

digest_f = fac._compute_input_digest(bytes_f1)
check(
    "input_digest is a 64-hex-char sha256",
    len(digest_f) == 64 and all(ch in "0123456789abcdef" for ch in digest_f),
)

reconstructed_f = json.loads(bytes_f1.decode("utf-8"))
payload_f["manifest"].append({"MUTATED": True})  # mutate original after freeze
check(
    "reconstructed identity payload is unaffected by post-freeze mutation of the original dict",
    reconstructed_f["manifest"] == [{"logical_name": "issues", "state": "present", "files": []}],
)


# ============================================================
# 5) Manifest scanner - real case_0001, no mutation (read-only scan).
#    TWO containment roots: case_root_real (CASES_DIR) AND
#    data_root_real (the REAL repository's data/documents.json,
#    data/provisions.json - never redirected, always read-only).
# ============================================================

data_root_5 = fac._resolve_module_data_root_real(lre)
check(
    "data_root_real resolves to the real repository's data/ directory",
    data_root_5 == (REPO_ROOT / "data").resolve(),
)

for row_key, module, expected_names in [
    ("legal_research", lre, {"issues", "facts", "timeline", "deadline", "global_documents", "global_provisions"}),
    ("case_law", cle, {"issues", "timeline", "research", "global_documents"}),
]:
    case_root = fac._resolve_module_case_root_real(module, CASE_ID)
    data_root = fac._resolve_module_data_root_real(module)
    manifest = fac._build_manifest_containers(row_key, case_root, data_root)
    check(
        f"real case_0001 manifest scan ({row_key}): container count matches spec exactly",
        len(manifest) == fac.FAMILY_LOGICAL_NAME_COUNTS[row_key],
    )
    check(
        f"real case_0001 manifest scan ({row_key}): sorted by logical_name",
        [c["logical_name"] for c in manifest] == sorted(c["logical_name"] for c in manifest),
    )
    check(
        f"real case_0001 manifest scan ({row_key}): logical_name set matches exactly",
        {c["logical_name"] for c in manifest} == expected_names,
    )
    for container in manifest:
        for file_entry in container["files"]:
            check(
                f"{row_key}/{container['logical_name']}: logical_relative_path is POSIX-form "
                "(no backslash)",
                "\\" not in file_entry["logical_relative_path"],
            )

check(
    "case_law manifest has no 'global_provisions' container at all (D13: builder never reads "
    "provisions.json - this container KIND does not exist for case_law, not merely 'missing')",
    "global_provisions" not in {
        c["logical_name"]
        for c in fac._build_manifest_containers(
            "case_law", fac._resolve_module_case_root_real(cle, CASE_ID), fac._resolve_module_data_root_real(cle),
        )
    },
)

expect_raises(
    fac.LegalResearchCaseLawInputContainmentError,
    lambda: fac._scan_single_file(
        fac._resolve_module_case_root_real(lre, CASE_ID),
        ("issues", "../escape_attempt"), "issues", required=True,
    ),
    "manifest scan: a traversal-shaped segment is rejected by validate_segment() before any "
    "filesystem probe",
)


# ============================================================
# 6) Containment safety - real Windows NTFS junctions (mklink /J,
#    never monkeypatched) for escaping/broken links on the CASE-scoped
#    side (documents/*/extractions/facts.json, legal_research only),
#    proving the scanner fails closed and never treats a broken/
#    escaping link as "missing".
# ============================================================

_tmp_containment_root = Path(tempfile.mkdtemp(prefix="vergi_lrcl_containment_"))

try:
    fixture_case = _tmp_containment_root / "cases" / CASE_ID
    shutil.copytree(REAL_CASE_0001, fixture_case)
    for stale in (fixture_case / "research").glob("*.pending"):
        stale.unlink()

    original_cases_dir = lre.CASES_DIR
    lre.CASES_DIR = _tmp_containment_root / "cases"
    try:
        if sys.platform == "win32":
            outside_target = _tmp_containment_root / "outside_canary"
            outside_target.mkdir()
            (outside_target / "document.json").write_text("{}", encoding="utf-8")

            documents_dir = fixture_case / "documents"
            documents_dir.mkdir(exist_ok=True)
            escaping_junction = documents_dir / "escaping_doc"

            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(escaping_junction), str(outside_target)],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                case_root_f = fac._resolve_module_case_root_real(lre, CASE_ID)

                stat_calls = []
                real_stat = os.stat

                def _recording_stat(path, *a, **kw):
                    stat_calls.append(str(path))
                    return real_stat(path, *a, **kw)

                with mock.patch("os.stat", side_effect=_recording_stat):
                    raised_escape = False
                    try:
                        fac._scan_verified_leaf_chain(
                            case_root_f, documents_dir.resolve(strict=False), ("extractions", "facts.json"),
                        )
                    except fac.LegalResearchCaseLawInputContainmentError:
                        raised_escape = True

                check("escaping documents/ junction: scanner raises fail-closed", raised_escape)
                canary_stat_paths = [p for p in stat_calls if str(outside_target) in p]
                check(
                    "escaping documents/ junction: outside canary directory NEVER stat'd during "
                    "the scan",
                    canary_stat_paths == [],
                    f"unexpected stat calls: {canary_stat_paths}",
                )
            else:
                print(
                    "SKIPPED (NOT counted as pass/fail): mklink /J failed "
                    f"(rc={result.returncode}, stderr={result.stderr!r}) - junction privilege "
                    "unavailable in this environment"
                )

            broken_target = _tmp_containment_root / "broken_target"
            broken_target.mkdir()
            broken_junction = documents_dir / "broken_doc"
            broken_result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(broken_junction), str(broken_target)],
                capture_output=True, text=True,
            )
            if broken_result.returncode == 0:
                shutil.rmtree(broken_target)
                check(
                    "broken junction: os.path.lexists() is True (reparse point still present)",
                    os.path.lexists(broken_junction),
                )
                check(
                    "broken junction: pathlib.Path.exists() is False (dereference fails)",
                    not broken_junction.exists(),
                )
                case_root_g = fac._resolve_module_case_root_real(lre, CASE_ID)
                raised_broken = False
                try:
                    fac._scan_verified_leaf_chain(
                        case_root_g, documents_dir.resolve(strict=False), ("extractions", "facts.json"),
                    )
                except fac.LegalResearchCaseLawInputContainmentError:
                    raised_broken = True
                check(
                    "broken documents/ junction: scanner fails closed (raises), never classified "
                    "as 'missing'",
                    raised_broken,
                )
            else:
                print(
                    "SKIPPED (NOT counted as pass/fail): broken-junction mklink /J failed "
                    f"(rc={broken_result.returncode})"
                )
        else:
            print("SKIPPED (NOT counted as pass/fail): junction test is Windows-only")
    finally:
        lre.CASES_DIR = original_cases_dir
finally:
    shutil.rmtree(_tmp_containment_root, ignore_errors=True)


# ============================================================
# 7) Path.glob() zero-call mechanical proof - the manifest scanner must
#    never call it, for either family, on real case_0001.
# ============================================================

_glob_calls = []
_real_glob = Path.glob


def _recording_glob(self, pattern, *a, **kw):
    _glob_calls.append((str(self), pattern))
    return _real_glob(self, pattern, *a, **kw)


with mock.patch.object(Path, "glob", _recording_glob):
    for row_key, module in [("legal_research", lre), ("case_law", cle)]:
        case_root = fac._resolve_module_case_root_real(module, CASE_ID)
        data_root = fac._resolve_module_data_root_real(module)
        fac._build_manifest_containers(row_key, case_root, data_root)

check(
    "Path.glob() is NEVER called anywhere in the manifest scanner, for either family, on real "
    "case_0001",
    _glob_calls == [],
    f"unexpected glob calls: {_glob_calls}",
)


# ============================================================
# 8) F1 REMEDIATION - the coordinated case_law agent-apply CALL CHAIN
#    (`_invoke_builder`, the EXACT function `apply_generation()` calls -
#    same call shape, same kwargs) passes `network_allowed=True` to the
#    agent layer WITHOUT it ever reaching the discovery/retrieval layer.
#    Proven with a fail-closed import-ATTEMPT ledger (patching `builtins.
#    __import__` itself - not merely inspecting mock call kwargs, and not
#    merely checking whether a module is already in sys.modules), a REAL
#    `.generate(prompt)`-implementing fake client, and a READ-ONLY build
#    against the REAL case_0001 tree (`build_case_law_engine_output()`
#    never writes anything to disk - only `write_pending()` does, which
#    this test never calls, so no CASES_DIR redirection is needed here).
# ============================================================

_RAG_STACK_MODULE_NAMES_8 = ("retriever", "rag", "ingest", "faiss", "openai", "dotenv", "anthropic")


def _make_import_ledger_8():
    """FAIL-CLOSED: records the attempt AND raises `ImportError` before the
    real module ever executes - so this measurement is safe regardless of
    whether the RAG stack happens to be installed in the runtime
    environment (a merely-recording, pass-through ledger would let a
    regression silently reach a real OpenAI/`.env` call in an environment
    where those packages ARE installed)."""
    attempts = []
    real_import = builtins.__import__

    def _blocking_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in _RAG_STACK_MODULE_NAMES_8:
            attempts.append(name)
            raise ImportError(
                f"BLOCKED by test guard: import of {name!r} must never actually execute in "
                "this test file"
            )
        return real_import(name, globals, locals, fromlist, level)

    return attempts, _blocking_import


class _FakeGenerateLLMClient8:
    """Implements the REAL agent injection protocol (`client.generate
    (prompt) -> str`) - see the F2 remediation note in
    `test_case_law_engine_isolated.py`/`test_legal_research_engine_
    isolated.py` for why a `.messages.create()`-only fake would silently
    hide a broken call chain here too."""

    def __init__(self, response_text):
        self.response_text = response_text
        self.call_count = 0
        self.last_prompt = None

    def generate(self, prompt):
        self.call_count += 1
        self.last_prompt = prompt
        return self.response_text


_issues_doc_8 = json.loads((REAL_CASE_0001 / "issues" / "issues.json").read_text(encoding="utf-8"))
_real_issue_id_8 = _issues_doc_8["issues"][0]["issue_id"]
_valid_agent_payload_8 = json.dumps([
    {"reason_code": "general_review_needed", "source_issue_id": _real_issue_id_8},
])

fake_client_8 = _FakeGenerateLLMClient8(_valid_agent_payload_8)
import_attempts_8, blocking_import_8 = _make_import_ledger_8()

with mock.patch("builtins.__import__", side_effect=blocking_import_8):
    build_result_8 = fac._invoke_builder(
        "case_law", cle, CASE_ID,
        use_agent=True, llm_client=fake_client_8, network_allowed=True,
    )

check(
    "coordinated case_law agent-apply call chain (_invoke_builder with network_allowed=True, "
    "the SAME call apply_generation() makes for a real --with-agent --allow-network apply): "
    "ZERO retriever/rag/ingest/faiss/openai/dotenv/anthropic import ATTEMPTS",
    import_attempts_8 == [],
    f"unexpected import attempts: {import_attempts_8}",
)
check(
    "coordinated case_law agent-apply call chain: the agent's REAL .generate(prompt) protocol "
    "was genuinely invoked exactly once (not swallowed by an AttributeError)",
    fake_client_8.call_count == 1 and isinstance(fake_client_8.last_prompt, str)
    and CASE_ID in fake_client_8.last_prompt,
)
check(
    "coordinated case_law agent-apply build result: discovery execution_state is the deliberate "
    "deferral state 'retrieval_not_run' for every issue - discovery was structurally never "
    "reached (discovery_network_allowed=False), NOT a technical retrieval failure",
    [cov.get("execution_state") for cov in build_result_8["analysis"]["case_law_coverage"]]
    and all(
        cov.get("execution_state") == "retrieval_not_run"
        for cov in build_result_8["analysis"]["case_law_coverage"]
    ),
)
check(
    "coordinated case_law agent-apply build result: zero 'retrieval_failed' state and zero "
    "retriever-import-failure warnings anywhere in the output",
    not any(
        cov.get("execution_state") == "retrieval_failed"
        for cov in build_result_8["analysis"]["case_law_coverage"]
    )
    and not any(
        ("retrieval_failed" in warning) or ("Retriever import edilemedi" in warning)
        for warning in build_result_8["analysis"]["warnings"]
    ),
    build_result_8["analysis"]["warnings"],
)
check(
    "coordinated case_law agent-apply build result: exactly ONE agent suggestion reached the "
    "output, grounded in the real issue_id fed into the fake client's response",
    build_result_8["agent_suggestion_count"] == 1
    and build_result_8["analysis"]["case_law_agent_suggestions"][0]["source_issue_id"] == _real_issue_id_8,
)
frozen_bytes_8 = fac._freeze_pending_bytes(build_result_8["analysis"])
check(
    "coordinated case_law agent-apply build produces a valid, freezable pending candidate (the "
    "exact byte recipe apply_generation() runs before ever touching the journal/writer)",
    isinstance(frozen_bytes_8, bytes) and frozen_bytes_8.endswith(b"\n"),
)

# ------------------------------------------------------------
# Deterministic case_law path - SAME _invoke_builder call shape, no
# agent: must ALSO show zero RAG-stack import attempts (regression
# proof that the F1 fix did not disturb the already-correct
# deterministic mode).
# ------------------------------------------------------------

import_attempts_8b, blocking_import_8b = _make_import_ledger_8()
with mock.patch("builtins.__import__", side_effect=blocking_import_8b):
    build_result_8b = fac._invoke_builder(
        "case_law", cle, CASE_ID,
        use_agent=False, llm_client=None, network_allowed=False,
    )
check(
    "coordinated case_law DETERMINISTIC-mode call chain (_invoke_builder, use_agent=False, "
    "network_allowed=False): ZERO retriever/rag/ingest/faiss/openai/dotenv/anthropic import "
    "attempts - unaffected by the F1 fix",
    import_attempts_8b == [],
    f"unexpected import attempts: {import_attempts_8b}",
)
check(
    "coordinated case_law DETERMINISTIC-mode build result: discovery execution_state is "
    "'retrieval_not_run' for every issue, zero agent suggestions",
    all(
        cov.get("execution_state") == "retrieval_not_run"
        for cov in build_result_8b["analysis"]["case_law_coverage"]
    )
    and build_result_8b["agent_suggestion_count"] == 0,
)


print(f"--- test_legal_research_case_law_mutation_facade_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
