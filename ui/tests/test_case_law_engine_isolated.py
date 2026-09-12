# ============================================================
# ROW 19C-3c-iv SLICE 1 - src/case_law_engine.py ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator - exercises the
# ADDITIVE changes made to `case_law_engine.py` directly: the new
# `get_reviews_dir()`/`get_target_ref()` helpers, the `preserve_
# previous_pending()` additive `history_dir=` override, the new
# keyword-only mutation-binding parameters on `write_pending()`
# (`verified_paths`/`input_digest`/`identity_payload`/`mutation_
# idempotency_key`/`mutation_resource_key`/`mutation_actor_ref`), the
# `*.generation_audit.json` audit record, `run_engine()`'s adapted
# dict-based unpacking of `write_pending()`'s new return shape (its OWN
# external return dict shape is UNCHANGED), and the legacy CLI bypass
# closure. Uses a REAL, independently re-identified COPY of the real
# `data/cases/case_0001` tree under a fresh tempdir for CASE-SCOPED
# inputs (never the real tree itself) - the GLOBAL input (`data/
# documents.json`) is read from the REAL repository tree (read-only,
# never redirected, never mutated). This family's manifest carries NO
# `global_provisions` container (case_law's build chain never reads
# `provisions.json` - D13 correction). NO real Anthropic/network call is
# EVER made anywhere in this file - only an injected fake client. Every
# agent-mode build that also exercises `network_allowed=True` (either the
# legacy passthrough or the F1-remediated explicit isolation) runs under
# a BLOCKING `builtins.__import__` guard (`_make_blocking_import_guard()`)
# that raises before the real `retriever`/`rag`/`ingest`/`faiss`/`openai`/
# `dotenv`/`anthropic` module ever executes - so this file is safe
# REGARDLESS of whether the RAG stack happens to be installed in the
# runtime environment (never relies on `ModuleNotFoundError` occurring by
# environment luck).
#
# Run: python ui/tests/test_case_law_engine_isolated.py
# ============================================================

import builtins
import hashlib
import json
import shutil
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

import case_law_engine as cle                                 # noqa: E402
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
ROW_KEY = "case_law"


class _FakeGenerateLLMClient:
    """ROW 19C-3c-iv SLICE 1 F2 REMEDIATION: implements the REAL agent
    injection protocol that `case_law_agent.generate_agent_candidates()`
    actually calls - `client.generate(prompt) -> str`
    (`case_law_agent.py:829`). This is NOT the Anthropic SDK's
    `.messages.create()` shape - that shape belongs only to
    `AnthropicCaseLawLLMClient.generate()`'s OWN internal network
    implementation, never to the object passed in as `llm_client`. A fake
    exposing only `.messages.create()` (the PRIOR, WRONG shape this file
    used) makes the real `client.generate(prompt)` call raise
    `AttributeError`, which `generate_agent_candidates()`'s own
    `except Exception` clause silently swallows into a "LLM çağrısı
    başarısız oldu" warning - making a genuinely-attempted, genuinely-
    failed agent call look like it "never happened" (zero
    `.messages.create()` calls trivially, since `.generate()` itself never
    completes). This class actually IMPLEMENTS `.generate()`, so the real
    call succeeds and the full generate -> parse -> accept round-trip is
    genuinely exercised."""

    def __init__(self, response_text):
        self.response_text = response_text
        self.call_count = 0
        self.last_prompt = None

    def generate(self, prompt):
        self.call_count += 1
        self.last_prompt = prompt
        return self.response_text


def _first_real_issue_id(case_dir):
    """Reads ONE real issue_id directly from the REAL case_0001 fixture
    tree already copied under `case_dir` - never a hardcoded literal, so a
    future edit to case_0001's canonical data cannot silently
    desynchronize this test from what the case ACTUALLY contains."""
    issues_doc = json.loads((case_dir / "issues" / "issues.json").read_text(encoding="utf-8"))
    issues = issues_doc["issues"]
    if not issues:
        raise AssertionError("case_0001 fixture: issues.json has zero issues")
    return issues[0]["issue_id"]


_RAG_STACK_MODULE_NAMES = ("retriever", "rag", "ingest", "faiss", "openai", "dotenv", "anthropic")


def _make_blocking_import_guard():
    """ROW 19C-3c-iv SLICE 1 F1 REMEDIATION: returns (attempts, guard).
    `guard` is installed via `mock.patch("builtins.__import__", side_
    effect=guard)`. Unlike a plain recording ledger, this guard actually
    RAISES `ImportError` the instant any `import`/`from ... import ...`
    statement anywhere in the call stack names one of the RAG-stack
    modules - so a test using it is safe REGARDLESS of whether those
    packages happen to be installed in the runtime environment (never
    relies on `ModuleNotFoundError` occurring by environment luck). The
    raised `ImportError` is exactly the kind of exception `case_law_
    discovery.py`'s own PRE-EXISTING `except Exception:` clause around
    `from retriever import retrieve_detailed` already catches - so a
    test asserting the LEGACY passthrough (`discovery_network_
    allowed=None`) still works end-to-end without ever letting the real
    `retriever` module execute."""
    attempts = []
    real_import = builtins.__import__

    def _guard(name, globals=None, locals=None, fromlist=(), level=0):
        if name in _RAG_STACK_MODULE_NAMES:
            attempts.append(name)
            raise ImportError(
                f"BLOCKED by test guard: import of {name!r} must never actually execute in "
                "this test file"
            )
        return real_import(name, globals, locals, fromlist, level)

    return attempts, _guard


_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_case_law_engine_isolated_"))
_tmp_cases = _tmp_root / "cases"
_tmp_cases.mkdir(parents=True)


def _fresh_case_copy():
    """A REAL, independently re-identified copy of case_0001, with any
    pre-existing pending/history/generation_reviews artefacts for the
    case_law family stripped."""
    dest = _tmp_cases / CASE_ID
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REAL_CASE_0001, dest)
    case_law_dir = dest / "case_law"
    for stale in case_law_dir.glob("*.pending"):
        stale.unlink()
    for stale_dir_name in ("history", "generation_reviews"):
        stale_dir = case_law_dir / stale_dir_name
        if stale_dir.exists():
            shutil.rmtree(stale_dir)
    return dest


_original_cases_dir = cle.CASES_DIR

try:
    cle.CASES_DIR = _tmp_cases

    # ============================================================
    # 0) CANARY - engine's own target_ref/action_family literals match
    #    the facade's independent formulas byte-for-byte.
    # ============================================================

    check(
        "CANARY: engine's own get_target_ref() matches the facade's "
        "legal_research_case_law_target_ref_for('case_law') byte-for-byte",
        cle.get_target_ref() == fac.legal_research_case_law_target_ref_for(ROW_KEY) == "case_law.pending",
    )
    check(
        "CANARY: engine's own GENERATION_ACTION_FAMILY matches the facade's "
        "legal_research_case_law_action_family_for('case_law') byte-for-byte",
        cle.GENERATION_ACTION_FAMILY == fac.legal_research_case_law_action_family_for(ROW_KEY)
        == "generation.case_law",
    )
    check(
        "CANARY: get_reviews_dir(case_id) is a sibling of get_pending_path(case_id)'s parent",
        cle.get_reviews_dir(CASE_ID).parent == cle.get_pending_path(CASE_ID).parent,
    )

    # ============================================================
    # 1) write_pending() partial mutation-binding guard - fail-closed,
    #    zero filesystem writes.
    # ============================================================

    _fresh_case_copy()
    pending_path_1 = cle.get_pending_path(CASE_ID)
    expect_raises(
        cle.CaseLawEngineError,
        lambda: cle.write_pending(
            CASE_ID, {}, 0, mutation_idempotency_key="idk", mutation_resource_key=None,
            mutation_actor_ref="7", input_digest="d", identity_payload={},
        ),
        "write_pending(): partial mutation-binding rejected",
    )
    check(
        "write_pending() partial-binding guard: zero filesystem writes",
        not pending_path_1.exists(),
    )

    # ============================================================
    # 2) CASES_DIR IS THE SINGLE WRITER SEAM for case-scoped inputs -
    #    the REAL build succeeds against the REDIRECTED tempdir tree
    #    (deterministic mode, no agent).
    # ============================================================

    _fresh_case_copy()
    build_result_2 = cle.build_case_law_engine_output(
        CASE_ID, use_agent=False, llm_client=None, retrieval_fn=None, network_allowed=False,
    )
    check(
        "build_case_law_engine_output() against the REDIRECTED CASES_DIR succeeds "
        "(deterministic mode)",
        isinstance(build_result_2["analysis"].get("case_law_coverage"), list),
    )
    check(
        "deterministic build produces zero agent suggestions",
        build_result_2["agent_suggestion_count"] == 0,
    )

    # ============================================================
    # 3) run_engine() (legacy orchestration) WITHOUT mutation binding -
    #    its OWN external return dict shape is UNCHANGED, no audit
    #    written.
    # ============================================================

    _fresh_case_copy()
    run_result_3 = cle.run_engine(CASE_ID, use_agent=False, network_allowed=False)
    check(
        "run_engine() legacy dict shape unchanged: analysis/pending_path/validation/"
        "previous_pending_history/issue_count/research_count/document_count/coverage_count/"
        "decision_count/agent_suggestion_count/agent_stats all present",
        all(
            k in run_result_3
            for k in (
                "analysis", "pending_path", "validation", "previous_pending_history",
                "issue_count", "research_count", "document_count", "coverage_count",
                "decision_count", "agent_suggestion_count", "agent_stats",
            )
        ),
    )
    check("run_engine() legacy: pending was written", Path(run_result_3["pending_path"]).exists())
    check("run_engine() legacy: validation.valid is True", run_result_3["validation"].get("valid") is True)
    check(
        "run_engine() legacy: zero generation_reviews/ directory created (no mutation binding)",
        not cle.get_reviews_dir(CASE_ID).exists(),
    )

    # ============================================================
    # 4) COORDINATED write (verified_paths + full mutation binding),
    #    DETERMINISTIC mode - real audit record, frozen-bytes equality,
    #    verified_paths used exclusively for output I/O.
    # ============================================================

    _fresh_case_copy()
    case_root_4 = fac._resolve_module_case_root_real(cle, CASE_ID)
    data_root_4 = fac._resolve_module_data_root_real(cle)
    paths_4 = fac._derive_verified_output_paths(cle, case_root_4, CASE_ID)
    manifest_4 = fac._build_manifest_containers(ROW_KEY, case_root_4, data_root_4)
    check(
        "manifest container count == 4 for case_law (no facts, no deadline, no provisions)",
        len(manifest_4) == 4 == fac.FAMILY_LOGICAL_NAME_COUNTS[ROW_KEY],
    )
    check(
        "manifest containers sorted by logical_name",
        [c["logical_name"] for c in manifest_4] == sorted(c["logical_name"] for c in manifest_4),
    )
    check(
        "case_law manifest has NO global_provisions container (D13: builder never reads "
        "provisions.json)",
        "global_provisions" not in {c["logical_name"] for c in manifest_4},
    )
    check(
        "research container is present (canonical research.json exists for case_0001)",
        next(c for c in manifest_4 if c["logical_name"] == "research")["state"] == "present",
    )
    generation_mode_4, model_id_4, engine_version_4, prompt_agent_version_4 = fac._resolve_generation_provenance(
        cle, ROW_KEY, False, None,
    )
    check(
        "deterministic provenance: generation_mode='deterministic', "
        "model_id='deterministic_no_model', engine_version=REAL engine constant, "
        "prompt_agent_version='n/a'",
        generation_mode_4 == "deterministic" and model_id_4 == "deterministic_no_model"
        and engine_version_4 == cle.CASE_LAW_ENGINE_VERSION and prompt_agent_version_4 == "n/a",
    )
    check(
        "case_law engine_version ('2') differs from legal_research's ('1') - two independent "
        "version dimensions",
        cle.CASE_LAW_ENGINE_VERSION == "2",
    )
    payload_4 = fac._build_identity_payload(
        ROW_KEY, CASE_ID, manifest_4, generation_mode_4, model_id_4, engine_version_4, prompt_agent_version_4,
    )
    check(
        "identity_payload has exactly the 7 expected keys",
        set(payload_4.keys()) == {
            "manifest_version", "case_id", "manifest", "generation_mode", "model_id",
            "engine_version", "prompt_agent_version",
        },
    )
    check(
        "identity_payload manifest_version is the case_law-specific literal (DIFFERENT from "
        "legal_research's)",
        payload_4["manifest_version"] == "row19c3civ.case_law.manifest.v1",
    )
    payload_bytes_4 = fac._canonical_identity_bytes(payload_4)
    input_digest_4 = fac._compute_input_digest(payload_bytes_4)

    build_result_4 = cle.build_case_law_engine_output(
        CASE_ID, use_agent=False, llm_client=None, retrieval_fn=None, network_allowed=False,
    )
    analysis_4 = build_result_4["analysis"]
    frozen_4 = fac._freeze_pending_bytes(analysis_4)
    candidate_4 = json.loads(frozen_4.decode("utf-8"))
    identity_for_audit_4 = json.loads(payload_bytes_4.decode("utf-8"))

    write_result_4 = cle.write_pending(
        CASE_ID, candidate_4, build_result_4["issue_count"],
        verified_paths=paths_4, input_digest=input_digest_4, identity_payload=identity_for_audit_4,
        mutation_idempotency_key="TESTKEY1", mutation_resource_key="case:case_0001",
        mutation_actor_ref="42",
    )
    check(
        "coordinated write_pending(): pending bytes == frozen bytes",
        paths_4.pending_path.read_bytes() == frozen_4,
    )
    check("coordinated write_pending(): pending bytes end with trailing LF", frozen_4.endswith(b"\n"))
    check(
        "coordinated write_pending(): pending_sha256 == sha256(frozen bytes)",
        write_result_4["pending_sha256"] == hashlib.sha256(frozen_4).hexdigest(),
    )
    check(
        "coordinated write_pending(): audit_path is set and exists",
        write_result_4["audit_path"] is not None and write_result_4["audit_path"].exists(),
    )
    audit_record_4 = json.loads(write_result_4["audit_path"].read_text(encoding="utf-8"))
    check(
        "audit record: schema_version/case_id/action_family/target_ref/channel exact",
        audit_record_4["schema_version"] == "1"
        and audit_record_4["case_id"] == CASE_ID
        and audit_record_4["action_family"] == "generation.case_law"
        and audit_record_4["target_ref"] == "case_law.pending"
        and audit_record_4["channel"] == "local_lawyer_legal_research_case_law_cli",
    )
    check(
        "audit record: identity_payload present and matches frozen payload bytes",
        audit_record_4["identity_payload"] == identity_for_audit_4,
    )
    check(
        "audit record: first_write True on a fresh case, backup fields None",
        audit_record_4["first_write"] is True
        and audit_record_4["history_backup_path"] is None
        and audit_record_4["history_backup_sha256"] is None,
    )
    check(
        "audit record: generation_mode/model_id/engine_version/prompt_agent_version match "
        "deterministic provenance",
        audit_record_4["generation_mode"] == "deterministic"
        and audit_record_4["model_id"] == "deterministic_no_model"
        and audit_record_4["engine_version"] == cle.CASE_LAW_ENGINE_VERSION
        and audit_record_4["prompt_agent_version"] == "n/a",
    )
    check(
        "audit record: generation_parameters_digest is None",
        audit_record_4["generation_parameters_digest"] is None,
    )
    check(
        "audit record: generated_at matches the written candidate's own top-level field",
        audit_record_4["generated_at"] == candidate_4.get("generated_at"),
    )

    # ============================================================
    # 5a) F1 REMEDIATION - LEGACY/DEFAULT PRESERVATION: when
    #     `discovery_network_allowed` is NOT passed (defaults to None),
    #     the discovery layer must keep receiving today's `network_
    #     allowed` value EXACTLY as it did before this fix - no existing
    #     direct Python call-site's behavior may change. Proven with the
    #     BLOCKING import guard (never lets the real `retriever` module
    #     execute, so this is safe REGARDLESS of whether the RAG stack
    #     happens to be installed) - it both records the attempt AND
    #     raises `ImportError`, which `case_law_discovery.py`'s own
    #     PRE-EXISTING `except Exception:` clause catches, producing the
    #     SAME 'Retriever import edilemedi'/'retrieval_failed' outcome
    #     the UNFIXED code already produced - this is the OLD behavior,
    #     faithfully preserved, not a new failure mode this fix
    #     introduced.
    # ============================================================

    _fresh_case_copy()
    real_issue_id_5a = _first_real_issue_id(fac._resolve_module_case_root_real(cle, CASE_ID))
    valid_agent_payload_5a = json.dumps([
        {"reason_code": "general_review_needed", "source_issue_id": real_issue_id_5a},
    ])
    fake_client_5a = _FakeGenerateLLMClient(valid_agent_payload_5a)
    import_attempts_5a, blocking_guard_5a = _make_blocking_import_guard()
    with mock.patch("builtins.__import__", side_effect=blocking_guard_5a):
        build_result_5a = cle.build_case_law_engine_output(
            CASE_ID, use_agent=True, llm_client=fake_client_5a, retrieval_fn=None, network_allowed=True,
            # discovery_network_allowed deliberately OMITTED - must default to None (legacy passthrough)
        )
    check(
        "LEGACY passthrough (discovery_network_allowed omitted, network_allowed=True): the "
        "discovery layer STILL attempts a real 'retriever' import once for EVERY issue with a "
        "resolvable case-law intent (exactly matching this case's own coverage-record count, "
        "read at runtime - never a hardcoded number) - proves this fix did NOT change any "
        "existing direct call-site's behavior",
        len(import_attempts_5a) >= 1
        and import_attempts_5a == ["retriever"] * len(build_result_5a["analysis"]["case_law_coverage"]),
        f"import attempts: {import_attempts_5a}, coverage count: "
        f"{len(build_result_5a['analysis']['case_law_coverage'])}",
    )
    check(
        "LEGACY passthrough: the blocked import is caught by case_law_discovery.py's own "
        "pre-existing except-clause, producing the SAME 'retrieval_failed'/'Retriever import "
        "edilemedi' outcome the UNFIXED code already produced - not a new crash",
        all(
            cov.get("execution_state") == "retrieval_failed"
            for cov in build_result_5a["analysis"]["case_law_coverage"]
        )
        and any("Retriever import edilemedi" in w for w in build_result_5a["analysis"]["warnings"]),
        build_result_5a["analysis"]["warnings"],
    )
    check(
        "LEGACY passthrough: the agent layer is COMPLETELY UNAFFECTED by discovery's blocked "
        "import - .generate(prompt) is still genuinely invoked exactly once with a real "
        "accepted candidate reaching the output (the two network authorities stay independent "
        "even when discovery_network_allowed is left at its legacy default)",
        fake_client_5a.call_count == 1
        and build_result_5a["agent_suggestion_count"] == 1
        and build_result_5a["analysis"]["case_law_agent_suggestions"][0]["source_issue_id"] == real_issue_id_5a,
    )

    # ============================================================
    # 5b) COORDINATED write, AGENT mode with an injected fake client and
    #     `discovery_network_allowed=False` EXPLICIT - the EXACT call
    #     shape `ui.services.legal_research_case_law_mutation_facade.
    #     _invoke_builder()` uses for a real coordinated
    #     `--with-agent --allow-network` apply. Provenance reflects
    #     agent/external_injected_client. The fake client implements the
    #     REAL `client.generate(prompt)` injection protocol (F2
    #     remediation) and returns a non-empty, VALID JSON array payload
    #     grounded in a REAL case_0001 issue_id, so the full
    #     generate -> parse -> accept -> output round-trip is genuinely
    #     exercised - not silently swallowed by an AttributeError from a
    #     fake client that only implemented `.messages.create()`. The
    #     SAME blocking import guard proves ZERO RAG-stack import
    #     attempts here (F1 remediation) - in sharp contrast to 5a.
    # ============================================================

    _fresh_case_copy()
    case_root_5 = fac._resolve_module_case_root_real(cle, CASE_ID)
    data_root_5 = fac._resolve_module_data_root_real(cle)
    paths_5 = fac._derive_verified_output_paths(cle, case_root_5, CASE_ID)
    manifest_5 = fac._build_manifest_containers(ROW_KEY, case_root_5, data_root_5)
    real_issue_id_5 = _first_real_issue_id(case_root_5)
    valid_agent_payload_5 = json.dumps([
        {"reason_code": "general_review_needed", "source_issue_id": real_issue_id_5},
    ])
    fake_client_5 = _FakeGenerateLLMClient(valid_agent_payload_5)
    generation_mode_5, model_id_5, engine_version_5, prompt_agent_version_5 = fac._resolve_generation_provenance(
        cle, ROW_KEY, True, fake_client_5,
    )
    check(
        "injected-client agent provenance: generation_mode='agent', "
        "model_id='external_injected_client', prompt_agent_version=REAL agent constant",
        generation_mode_5 == "agent" and model_id_5 == "external_injected_client"
        and prompt_agent_version_5 == cle.CASE_LAW_AGENT_VERSION,
    )
    payload_5 = fac._build_identity_payload(
        ROW_KEY, CASE_ID, manifest_5, generation_mode_5, model_id_5, engine_version_5, prompt_agent_version_5,
    )
    payload_bytes_5 = fac._canonical_identity_bytes(payload_5)
    input_digest_5 = fac._compute_input_digest(payload_bytes_5)
    import_attempts_5b, blocking_guard_5b = _make_blocking_import_guard()
    with mock.patch("builtins.__import__", side_effect=blocking_guard_5b):
        build_result_5 = cle.build_case_law_engine_output(
            CASE_ID, use_agent=True, llm_client=fake_client_5, retrieval_fn=None, network_allowed=True,
            discovery_network_allowed=False,
        )
    check(
        "F1 REMEDIATION: coordinated case_law agent build (discovery_network_allowed=False "
        "explicit): ZERO retriever/rag/ingest/faiss/openai/dotenv/anthropic import attempts - "
        "contrast this with 5a's exactly-one attempt under the untouched legacy default",
        import_attempts_5b == [],
        f"import attempts: {import_attempts_5b}",
    )
    check(
        "F1 remediation: discovery execution_state is the deliberate deferral state "
        "'retrieval_not_run' for every issue - structurally never reached, not a technical "
        "retrieval failure",
        all(
            cov.get("execution_state") == "retrieval_not_run"
            for cov in build_result_5["analysis"]["case_law_coverage"]
        ),
    )
    check(
        "agent build with a REAL `.generate(prompt)`-implementing fake client: the agent layer "
        "is GENUINELY invoked exactly once - proves the PRIOR zero-call reading was an "
        "AttributeError silently swallowed by the engine's own catch-all warning, not a "
        "coverage-based skip",
        fake_client_5.call_count == 1,
    )
    check(
        "agent build: the prompt actually passed to .generate() is a non-empty string carrying "
        "this case's own case_id - proves build_user_prompt() genuinely ran, not a stub",
        isinstance(fake_client_5.last_prompt, str) and CASE_ID in fake_client_5.last_prompt,
    )
    check(
        "agent build: zero 'LLM çağrısı başarısız oldu'/parse-failure warnings - the injected "
        "response was genuinely parsed, not swallowed",
        not any(
            ("LLM çağrısı başarısız" in warning) or ("parse edilemedi" in warning)
            for warning in build_result_5["analysis"]["warnings"]
        ),
        build_result_5["analysis"]["warnings"],
    )
    check(
        "agent build: exactly ONE accepted agent suggestion, grounded in the REAL issue_id fed "
        "into the fake client's response - proves the parsed candidate reached the output path "
        "(generate -> parse -> accept -> output), not just an internal accepted_count",
        build_result_5["agent_suggestion_count"] == 1
        and len(build_result_5["analysis"]["case_law_agent_suggestions"]) == 1
        and build_result_5["analysis"]["case_law_agent_suggestions"][0]["source_issue_id"] == real_issue_id_5,
    )
    frozen_5 = fac._freeze_pending_bytes(build_result_5["analysis"])
    candidate_5 = json.loads(frozen_5.decode("utf-8"))
    write_result_5 = cle.write_pending(
        CASE_ID, candidate_5, build_result_5["issue_count"],
        verified_paths=paths_5, input_digest=input_digest_5,
        identity_payload=json.loads(payload_bytes_5.decode("utf-8")),
        mutation_idempotency_key="TESTKEY2", mutation_resource_key="case:case_0001",
        mutation_actor_ref="42",
    )
    audit_record_5 = json.loads(write_result_5["audit_path"].read_text(encoding="utf-8"))
    check(
        "agent-mode audit record: generation_mode='agent', model_id='external_injected_client'",
        audit_record_5["generation_mode"] == "agent"
        and audit_record_5["model_id"] == "external_injected_client",
    )

    # ============================================================
    # 6) Mutating the original candidate dict AFTER freezing must not
    #    affect what was written (frozen-bytes discipline).
    # ============================================================

    _fresh_case_copy()
    build_result_6 = cle.build_case_law_engine_output(
        CASE_ID, use_agent=False, llm_client=None, retrieval_fn=None, network_allowed=False,
    )
    analysis_6 = build_result_6["analysis"]
    frozen_6 = fac._freeze_pending_bytes(analysis_6)
    analysis_6["case_law_coverage"] = "MUTATED-AFTER-FREEZE"
    candidate_6 = json.loads(frozen_6.decode("utf-8"))
    check(
        "candidate reconstructed from frozen bytes is unaffected by post-freeze mutation",
        candidate_6["case_law_coverage"] != "MUTATED-AFTER-FREEZE",
    )

finally:
    cle.CASES_DIR = _original_cases_dir
    shutil.rmtree(_tmp_root, ignore_errors=True)


# ============================================================
# 7) LEGACY CLI CLOSURE - main() refuses with SystemExit(2), fixed
#    stderr message, before any real work.
# ============================================================

import io
import contextlib

_argv_backup = sys.argv
try:
    sys.argv = ["case_law_engine.py", "--case", CASE_ID]
    stderr_capture = io.StringIO()
    exit_code = None
    with contextlib.redirect_stderr(stderr_capture):
        try:
            cle.main()
        except SystemExit as exit_signal:
            exit_code = exit_signal.code
    check("case_law_engine.main() raises SystemExit(2)", exit_code == 2)
    check(
        "case_law_engine.main() refusal message points to ui.cli_mutate generation "
        "--row-key case_law",
        "ui.cli_mutate generation" in stderr_capture.getvalue()
        and "--row-key case_law" in stderr_capture.getvalue(),
        stderr_capture.getvalue(),
    )
    check(
        "case_law_engine.main() refusal message tag is (Row 19C-3c-iv) - this engine's own "
        "line-labeled closure, deliberately NOT part of "
        "ui/tests/test_cli_mutate_integration_postgres.py's subprocess LEGACY_MUTATION_MATRIX, "
        "which only matches the literal '(Row 19C-3b)' substring",
        "(Row 19C-3c-iv)" in stderr_capture.getvalue(),
        stderr_capture.getvalue(),
    )
finally:
    sys.argv = _argv_backup


# ============================================================
# 8) LEGACY CLI CLOSURE - REAL OS SUBPROCESS PROOF.
# ============================================================

import os
import subprocess


def _snapshot_data_tree_8():
    data_dir = REPO_ROOT / "data"
    snapshot = {}
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            snapshot[path.relative_to(data_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


_data_snapshot_before_8 = _snapshot_data_tree_8()

_script_path_8 = SRC_DIR / "case_law_engine.py"
_child_env_8 = os.environ.copy()
_child_env_8["PYTHONIOENCODING"] = "utf-8"
_completed_8 = subprocess.run(
    [sys.executable, str(_script_path_8), "--case", CASE_ID],
    cwd=str(REPO_ROOT),
    capture_output=True,
    timeout=90,
    env=_child_env_8,
)
_stdout_8 = _completed_8.stdout.decode("utf-8") if _completed_8.stdout else ""
_stderr_8 = _completed_8.stderr.decode("utf-8") if _completed_8.stderr else ""

check(
    "REAL OS subprocess: the real script file exists on disk and is the one actually invoked",
    _script_path_8.is_file(),
    f"resolved path: {_script_path_8}",
)
check(
    "REAL OS subprocess: returncode is exactly 2 (the genuine process exit code SystemExit(2) "
    "produces, not merely main()'s Python-level return value)",
    _completed_8.returncode == 2,
    f"got returncode={_completed_8.returncode!r} stdout={_stdout_8!r} stderr={_stderr_8!r}",
)
check(
    "REAL OS subprocess: the fixed (Row 19C-3c-iv) refusal message appears in stderr, pointing "
    "to ui.cli_mutate generation --row-key case_law",
    "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3c-iv)." in _stderr_8
    and "ui.cli_mutate generation" in _stderr_8 and "--row-key case_law" in _stderr_8,
    f"stderr={_stderr_8!r}",
)
check(
    "REAL OS subprocess: stderr contains no 'Traceback' - a clean, deliberate SystemExit(2), "
    "never an unhandled exception escaping",
    "Traceback" not in _stderr_8,
    f"stderr={_stderr_8!r}",
)
check(
    "REAL OS subprocess: stdout is completely empty",
    _stdout_8 == "",
    f"stdout={_stdout_8!r}",
)

_data_snapshot_after_8 = _snapshot_data_tree_8()
check(
    "REAL OS subprocess refusal: the REAL data/ tree is byte-for-byte UNCHANGED",
    _data_snapshot_before_8 == _data_snapshot_after_8,
    f"changed/added/removed keys: "
    f"{sorted(set(_data_snapshot_before_8) ^ set(_data_snapshot_after_8))}",
)


print(f"--- test_case_law_engine_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
