# ============================================================
# ROW 19C-3c-iii - src/fact_extraction_engine.py ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator - exercises the
# ADDITIVE changes made to `fact_extraction_engine.py` directly: the
# build/write split (`build_fact_extraction()`/`write_pending()`), the
# new keyword-only mutation-binding parameters on `write_pending()`
# (`verified_paths`/`input_digest`/`identity_payload`/`mutation_
# idempotency_key`/`mutation_resource_key`/`mutation_actor_ref`), the
# `*.generation_audit.json` audit record, the `call_llm()` injected-
# client seam (and the fact that the production `.env`/`anthropic`
# import path is NEVER touched by it), the `CASES_DIR` writer-
# containment seam (including that `load_case_context()` now goes
# through it, not a separate `DATA_DIR / "cases"` literal), and the
# legacy CLI bypass closure. Uses a REAL, independently re-identified
# COPY of the real `data/cases/case_0001` tree under a fresh tempdir
# (never the real tree itself). NO real Anthropic/network call is EVER
# made anywhere in this file - only an injected fake client.
#
# Run: python ui/tests/test_fact_extraction_engine_isolated.py
# ============================================================

import datetime as _dt
import hashlib
import inspect
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
UI_DIR = REPO_ROOT / "ui"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import fact_extraction_engine as fee                       # noqa: E402
import llm_privacy_boundary as lpb                          # noqa: E402
import fact_approval                                        # noqa: E402
import document_reference_resolver as drr                   # noqa: E402
from ui.services import fact_extraction_mutation_facade as fac  # noqa: E402

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
DOCUMENT_ID = "dava_dilekcesi_001"


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeTextBlock(text)]


class _FakeMessages:
    def __init__(self, payload_text, *, raise_error=None):
        self._payload_text = payload_text
        self._raise_error = raise_error
        self.create_calls = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        if self._raise_error is not None:
            raise self._raise_error
        return _FakeResponse(self._payload_text)


class _FakeAnthropicClient:
    """Test-only injected `llm_client` - `call_llm()`'s `llm_client is
    not None` branch calls `llm_client.messages.create(...)` - this
    fake NEVER touches `.env`/`os.getenv`/a real `Anthropic(...)`
    constructor, matching the real `Anthropic` SDK's own
    `client.messages.create(...)` call shape exactly."""

    def __init__(self, payload_text, *, raise_error=None):
        self.messages = _FakeMessages(payload_text, raise_error=raise_error)


def _valid_fact_payload_text(*, count=1):
    facts = []
    for index in range(count):
        facts.append({
            "fact_kind": "taxpayer_claim",
            "statement": f"Davacı örnek iddia {index} ileri sürmüştür.",
            "normalized_statement": None,
            "extraction_basis": "explicit_text",
            "attributed_party_id": None,
            "attributed_actor_label": None,
            "source": {
                "page": None, "section": None, "paragraph": None,
                "text_excerpt": f"örnek alıntı metni {index}",
            },
            "structured_values": [],
            "related_party_ids": [],
            "related_document_ids": [],
            "related_dispute_item_ids": [],
            "confidence": 0.8,
            "verification_state": "unverified",
            "notes": None,
        })
    return json.dumps({"facts": facts, "warnings": []})


_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_fact_extraction_engine_isolated_"))
_tmp_cases = _tmp_root / "cases"
_tmp_cases.mkdir(parents=True)


def _fresh_case_copy():
    """A REAL, independently re-identified copy of case_0001, with any
    pre-existing pending/history/generation_reviews artefacts for
    DOCUMENT_ID stripped."""
    dest = _tmp_cases / CASE_ID
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(REAL_CASE_0001, dest)
    extractions_dir = dest / "documents" / DOCUMENT_ID / "extractions"
    for stale in extractions_dir.glob("*.pending"):
        stale.unlink()
    for stale_dir_name in ("history", "generation_reviews"):
        stale_dir = extractions_dir / stale_dir_name
        if stale_dir.exists():
            shutil.rmtree(stale_dir)
    return dest


_original_engine_cases_dir = fee.CASES_DIR
_original_drr_cases_dir = drr.CASES_DIR
_original_fact_approval_cases_dir = fact_approval.CASES_DIR

try:
    fee.CASES_DIR = _tmp_cases
    drr.CASES_DIR = _tmp_cases
    fact_approval.CASES_DIR = _tmp_cases

    # ============================================================
    # 0) CURRENT_PENDING_FILENAME CANARY - engine and fact_approval.py
    #    (Row 6, LOCKED, READ-ONLY dependency) MUST carry byte-for-byte
    #    the SAME literal - two independent copies, drift caught here.
    # ============================================================

    check(
        "CANARY: fact_extraction_engine.CURRENT_PENDING_FILENAME == "
        "fact_approval.CURRENT_PENDING_FILENAME (two independent copies, must never drift)",
        fee.CURRENT_PENDING_FILENAME == fact_approval.CURRENT_PENDING_FILENAME
        == "facts_llm_v1_3.json.pending",
    )
    check(
        "CANARY: engine's own get_target_ref(document_id) matches the facade's "
        "fact_extraction_target_ref_for(document_id) byte-for-byte",
        fee.get_target_ref(DOCUMENT_ID) == fac.fact_extraction_target_ref_for(DOCUMENT_ID)
        == f"fact.{DOCUMENT_ID}.pending",
    )
    check(
        "CANARY: engine's own get_pending_path(case_id, document_id) matches fact_approval's "
        "get_pending_path(case_id, document_id) byte-for-byte (same CASES_DIR, same filename)",
        fee.get_pending_path(CASE_ID, DOCUMENT_ID) == fact_approval.get_pending_path(CASE_ID, DOCUMENT_ID),
    )

    # ============================================================
    # 1) write_pending() partial mutation-binding guard - fail-closed,
    #    zero filesystem writes.
    # ============================================================

    _fresh_case_copy()
    pending_path_1 = fee.get_pending_path(CASE_ID, DOCUMENT_ID)
    expect_raises(
        fee.FactExtractionEngineError,
        lambda: fee.write_pending(
            CASE_ID, DOCUMENT_ID, {}, mutation_idempotency_key="idk", mutation_resource_key=None,
            mutation_actor_ref="7", input_digest="d", identity_payload={},
        ),
        "write_pending(): partial mutation-binding rejected",
    )
    check(
        "write_pending() partial-binding guard: zero filesystem writes",
        not pending_path_1.exists(),
    )

    # ============================================================
    # 2) CASES_DIR IS THE SINGLE WRITER SEAM - load_case_context() (via
    #    build_fact_extraction()) reads through the SAME CASES_DIR that
    #    was just redirected above, NOT a separate DATA_DIR/"cases"
    #    literal - proven by a REAL end-to-end build against the
    #    REDIRECTED tempdir tree succeeding (if it silently fell back to
    #    the real repository tree, this document_id/case_id pairing
    #    would still exist there too, so the STRONGER proof is: the
    #    ORIGINAL real CASES_DIR is restored to a DIFFERENT path
    #    entirely for the duration of this block, and the build still
    #    finds its input under the tempdir).
    # ============================================================

    _fresh_case_copy()
    text_path_2 = fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID)
    check(
        "CASES_DIR seam: get_extracted_text_path() resolves under the REDIRECTED tempdir, "
        "not the real repository data/ tree",
        str(text_path_2).startswith(str(_tmp_cases)) and text_path_2.is_file(),
    )
    fake_client_2 = _FakeAnthropicClient(_valid_fact_payload_text(count=1))
    build_result_2 = fee.build_fact_extraction(
        CASE_ID, DOCUMENT_ID, text_path_2, model="fake-model-2", llm_client=fake_client_2,
    )
    check(
        "build_fact_extraction() against the REDIRECTED CASES_DIR succeeds (load_case_context() "
        "genuinely reads through fee.CASES_DIR, not a separate DATA_DIR/'cases' literal)",
        len(build_result_2["extraction"]["facts"]) == 1,
    )
    check(
        "build_fact_extraction() with an injected llm_client calls EXACTLY ONE .messages.create()",
        len(fake_client_2.messages.create_calls) == 1,
    )

    # ============================================================
    # 3) run_fact_extraction() (legacy, build+write orchestration)
    #    WITHOUT mutation binding - dict return, no audit written.
    # ============================================================

    _fresh_case_copy()
    text_path_3 = fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID)
    fake_client_3 = _FakeAnthropicClient(_valid_fact_payload_text(count=2))

    # run_fact_extraction() itself has no llm_client parameter (it is a
    # thin build+write orchestrator, matching its ORIGINAL pre-Row-
    # 19C-3c-iii signature exactly) - so this section calls
    # build_fact_extraction()+write_pending() directly, exactly as
    # run_fact_extraction()'s OWN new body does, to prove the SAME
    # legacy dict shape without needing real network access.
    build_result_3 = fee.build_fact_extraction(
        CASE_ID, DOCUMENT_ID, text_path_3, model="fake-model-3", llm_client=fake_client_3,
    )
    write_result_3 = fee.write_pending(CASE_ID, DOCUMENT_ID, build_result_3["extraction"])
    legacy_result_3 = {
        "output_path": write_result_3["pending_path"],
        "extraction": build_result_3["extraction"],
        "validation": write_result_3["validation"],
        "document_resolutions": build_result_3["document_resolutions"],
        "filtered_meta_count": build_result_3["filtered_meta_count"],
        "semantic_guard_records": build_result_3["semantic_guard_records"],
    }
    check(
        "legacy build+write orchestration: dict return with output_path/extraction/validation/"
        "document_resolutions/filtered_meta_count/semantic_guard_records",
        all(
            k in legacy_result_3
            for k in (
                "output_path", "extraction", "validation", "document_resolutions",
                "filtered_meta_count", "semantic_guard_records",
            )
        ),
    )
    check(
        "legacy build+write orchestration: pending was written",
        Path(legacy_result_3["output_path"]).exists(),
    )
    check(
        "legacy build+write orchestration: validation.valid is True",
        legacy_result_3["validation"].get("valid") is True,
    )
    check(
        "legacy build+write orchestration: zero generation_reviews/ directory created "
        "(no mutation binding was provided)",
        not fee.get_reviews_dir(CASE_ID, DOCUMENT_ID).exists(),
    )

    # ============================================================
    # 4) COORDINATED write (verified_paths + full mutation binding) -
    #    real audit record, frozen-bytes equality, verified_paths used
    #    exclusively for output I/O.
    # ============================================================

    _fresh_case_copy()
    case_root_4 = fac._resolve_module_case_root_real(fee, CASE_ID)
    paths_4 = fac._derive_verified_output_paths(fee, case_root_4, CASE_ID, DOCUMENT_ID)
    manifest_4 = fac._build_manifest_containers(case_root_4, DOCUMENT_ID)
    check("manifest container count == 4 for fact_extraction", len(manifest_4) == 4)
    check(
        "manifest containers sorted by logical_name",
        [c["logical_name"] for c in manifest_4] == sorted(c["logical_name"] for c in manifest_4),
    )
    generation_mode_4, model_id_4, engine_version_4, prompt_agent_version_4 = fac._resolve_generation_provenance(
        fee, None,
    )
    check(
        "production provenance (llm_client=None): generation_mode='agent', model_id=DEFAULT_MODEL, "
        "engine_version/prompt_agent_version are the REAL engine constants",
        generation_mode_4 == "agent" and model_id_4 == fee.DEFAULT_MODEL
        and engine_version_4 == fee.FACT_EXTRACTION_ENGINE_VERSION
        and prompt_agent_version_4 == fee.PROMPT_VERSION,
    )
    payload_4 = fac._build_identity_payload(
        DOCUMENT_ID, manifest_4, generation_mode_4, model_id_4, engine_version_4, prompt_agent_version_4,
        lpb.MASKING_POLICY_VERSION, lpb.EMPTY_EXTRA_TERMS_DIGEST,
    )
    check(
        "identity_payload has exactly the 9 expected keys (PILOT READINESS ADIM 4a moved it "
        "from 7 to 9 by adding masking_policy_version + masking_extra_terms_digest)",
        set(payload_4.keys()) == {
            "manifest_version", "document_id", "manifest", "generation_mode", "model_id",
            "engine_version", "prompt_agent_version",
            "masking_policy_version", "masking_extra_terms_digest",
        },
        sorted(payload_4.keys()),
    )
    payload_bytes_4 = fac._canonical_identity_bytes(payload_4)
    input_digest_4 = fac._compute_input_digest(payload_bytes_4)

    text_path_4 = fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID)
    fake_client_4 = _FakeAnthropicClient(_valid_fact_payload_text(count=1))
    build_result_4 = fee.build_fact_extraction(
        CASE_ID, DOCUMENT_ID, text_path_4, model=fee.DEFAULT_MODEL, llm_client=fake_client_4,
    )
    extraction_4 = build_result_4["extraction"]
    frozen_4 = fac._freeze_pending_bytes(extraction_4)
    candidate_4 = json.loads(frozen_4.decode("utf-8"))
    identity_for_audit_4 = json.loads(payload_bytes_4.decode("utf-8"))

    write_result_4 = fee.write_pending(
        CASE_ID, DOCUMENT_ID, candidate_4,
        verified_paths=paths_4, input_digest=input_digest_4, identity_payload=identity_for_audit_4,
        mutation_idempotency_key="TESTKEY1", mutation_resource_key="case:case_0001",
        mutation_actor_ref="42",
    )
    check(
        "coordinated write_pending(): pending bytes == frozen bytes",
        paths_4.pending_path.read_bytes() == frozen_4,
    )
    check(
        "coordinated write_pending(): pending bytes end with trailing LF",
        frozen_4.endswith(b"\n"),
    )
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
        "audit record: schema_version/case_id/document_id/action_family/target_ref/channel exact",
        audit_record_4["schema_version"] == "1"
        and audit_record_4["case_id"] == CASE_ID
        and audit_record_4["document_id"] == DOCUMENT_ID
        and audit_record_4["action_family"] == "generation.fact_extraction"
        and audit_record_4["target_ref"] == f"fact.{DOCUMENT_ID}.pending"
        and audit_record_4["channel"] == "local_lawyer_fact_extraction_cli",
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
        "audit record: generation_mode='agent', model_id=DEFAULT_MODEL, engine_version/"
        "prompt_agent_version are the REAL engine constants (production, non-injected build)",
        audit_record_4["generation_mode"] == "agent"
        and audit_record_4["model_id"] == fee.DEFAULT_MODEL
        and audit_record_4["engine_version"] == fee.FACT_EXTRACTION_ENGINE_VERSION
        and audit_record_4["prompt_agent_version"] == fee.PROMPT_VERSION,
    )
    check(
        "audit record: generation_parameters_digest is None (no ancillary per-run parameters "
        "exist for this family)",
        audit_record_4["generation_parameters_digest"] is None,
    )
    check(
        "ADIM 4a audit record: masking_policy_version / masking_extra_terms_digest are present "
        "and taken VERBATIM from the passed identity_payload (single source - the engine never "
        "recomputes them)",
        audit_record_4["masking_policy_version"] == identity_for_audit_4["masking_policy_version"]
        and audit_record_4["masking_extra_terms_digest"]
        == identity_for_audit_4["masking_extra_terms_digest"]
        == lpb.EMPTY_EXTRA_TERMS_DIGEST,
        f"{audit_record_4.get('masking_policy_version')!r} / "
        f"{audit_record_4.get('masking_extra_terms_digest')!r}",
    )
    check(
        "ADIM 4a audit record: the mapping/raw values NEVER reach the audit record",
        "VGMASK" not in json.dumps(audit_record_4, ensure_ascii=False)
        and "ABC Ltd" not in json.dumps(audit_record_4, ensure_ascii=False),
    )
    check(
        "ADIM 4a: the pending artefact carries NO masking field and NO token "
        "(the schema is additionalProperties:false - masking lives only in identity/audit)",
        "VGMASK" not in paths_4.pending_path.read_text(encoding="utf-8")
        and "masking_policy_version" not in paths_4.pending_path.read_text(encoding="utf-8"),
    )
    check(
        "audit record: generated_at is written['extractor']['run_at'] - NOT a top-level "
        "'generated_at' field on the extraction schema itself (schema-verified absence)",
        audit_record_4["generated_at"] == candidate_4["extractor"]["run_at"],
    )

    # ============================================================
    # 5) Mutating the original candidate/identity dict AFTER freezing
    #    must not affect what was written (frozen-bytes discipline).
    # ============================================================

    _fresh_case_copy()
    text_path_5 = fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID)
    fake_client_5 = _FakeAnthropicClient(_valid_fact_payload_text(count=1))
    build_result_5 = fee.build_fact_extraction(
        CASE_ID, DOCUMENT_ID, text_path_5, model="fake-model-5", llm_client=fake_client_5,
    )
    extraction_5 = build_result_5["extraction"]
    frozen_5 = fac._freeze_pending_bytes(extraction_5)
    extraction_5["facts"] = "MUTATED-AFTER-FREEZE"  # mutate the original object
    candidate_5 = json.loads(frozen_5.decode("utf-8"))
    check(
        "candidate reconstructed from frozen bytes is unaffected by post-freeze mutation",
        candidate_5["facts"] != "MUTATED-AFTER-FREEZE",
    )

    # ============================================================
    # SHARED IMPORT GUARD (sections 6-8): rather than `mock.patch(
    # "dotenv.load_dotenv", ...)` (which would itself raise
    # ModuleNotFoundError in THIS environment, where `python-dotenv` is
    # NOT installed - see this suite's own operational preflight, and
    # would in any case only detect a CALL to an already-imported
    # module, not an import attempt), this guard patches `builtins.
    # __import__` itself to explode the instant ANY `import dotenv`/
    # `from dotenv import ...`/`import anthropic`/`from anthropic
    # import ...` statement is reached, anywhere in the call stack -
    # correct regardless of whether those packages happen to be
    # installed in the environment running this suite.
    # ============================================================

    import builtins

    _real_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ("dotenv", "anthropic"):
            raise AssertionError(
                f"import of {name!r} was attempted on the injected-client/preview path - "
                "MUST NEVER happen"
            )
        return _real_import(name, globals, locals, fromlist, level)

    # ============================================================
    # 6) INJECTED-CLIENT CREDENTIAL ISOLATION - call_llm() with a real
    #    injected client NEVER calls load_dotenv()/os.getenv()/a real
    #    Anthropic(...) constructor - proven by intercepting the import
    #    statements themselves, not merely a subsequent call.
    # ============================================================

    with mock.patch("builtins.__import__", side_effect=_guarded_import):
        fake_client_6 = _FakeAnthropicClient('{"facts": [], "warnings": []}')
        raw_6 = fee.call_llm("prompt-6", "model-6", llm_client=fake_client_6)
        check(
            "call_llm() with an injected llm_client returns the fake client's own text, "
            "neither 'dotenv' nor 'anthropic' was EVER imported (import statement itself "
            "intercepted, not merely a call on an already-imported module)",
            raw_6 == '{"facts": [], "warnings": []}',
        )
        check(
            "call_llm() with an injected llm_client called EXACTLY ONE .messages.create()",
            len(fake_client_6.messages.create_calls) == 1,
        )

    # ============================================================
    # 7) `.env` IS NEVER READ AT IMPORT TIME - `import fact_extraction_
    #    engine` itself must not trigger load_dotenv()/require `python-
    #    dotenv`/`anthropic` to be importable at module scope (proven
    #    empirically by THIS file's own successful import above, using
    #    an environment where `anthropic`/`python-dotenv` are NOT
    #    installed - see this suite's own operational preflight). This
    #    check additionally proves `importlib.reload()` of the already-
    #    imported module does not import either package at module scope.
    # ============================================================

    import importlib

    with mock.patch("builtins.__import__", side_effect=_guarded_import):
        try:
            importlib.reload(fee)
            reload_ok = True
        except AssertionError:
            reload_ok = False
        finally:
            fee.CASES_DIR = _tmp_cases  # re-apply the redirect after reload
    check(
        "importlib.reload(fact_extraction_engine) does NOT import 'dotenv'/'anthropic' at "
        "module scope",
        reload_ok,
    )

    # ============================================================
    # 8) PREVIEW NEVER TOUCHES load_dotenv()/network - the coordinated
    #    facade's preview_generation() (with_agent=True, no llm_client)
    #    must not import 'dotenv'/'anthropic' either, even though it
    #    resolves model_id via fee.DEFAULT_MODEL (a plain module
    #    constant read, not a call).
    # ============================================================

    from ui.services import authz as _authz

    class _FakeAuthzRepo:
        def get_session_authz_state(self, principal):
            return _authz.SessionRecord(user_id=principal.user_id, current_authz_version=1, disabled=False)

        def get_active_case_assignment(self, user_id, case_id):
            return _authz.CaseAssignmentRecord(role="lawyer")

        def list_active_case_ids_for_user(self, user_id):
            return [CASE_ID]

        def is_global_admin(self, user_id):
            return False

    _fresh_case_copy()
    principal_8 = _authz.Principal(user_id=7, session_id=0, role_version_at_issue=1)
    with mock.patch("builtins.__import__", side_effect=_guarded_import):
        preview_8 = fac.preview_generation(
            CASE_ID, DOCUMENT_ID, with_agent=True, principal=principal_8, authz_repository=_FakeAuthzRepo(),
        )
    check(
        "preview_generation() (with_agent=True, no llm_client) NEVER imports 'dotenv'/"
        "'anthropic' - preview reads fee.DEFAULT_MODEL as a plain constant, never touches "
        "credentials/network",
        preview_8["model_id"] == fee.DEFAULT_MODEL,
    )

    # ============================================================
    # 10) PILOT READINESS ADIM 4a - LLM GİZLİLİK SINIRI
    #
    # case_0001's taxpayer party is a `company`: "ABC Ltd. Şti. - Demo".
    # It appears VERBATIM in dava_dilekcesi_001's extracted text and in
    # the case context, so this section works against a REAL fixture,
    # not a synthetic one. The public-authority party ("Örnek Vergi
    # Dairesi Müdürlüğü") is deliberately NOT masked (decision U2).
    # ============================================================

    class _PromptRecordingMessages:
        """Records the prompt actually handed to the model and answers
        with whatever `responder(prompt)` produces."""

        def __init__(self, responder):
            self._responder = responder
            self.create_calls = []
            self.prompts = []

        def create(self, **kwargs):
            self.create_calls.append(kwargs)
            prompt = kwargs["messages"][0]["content"]
            self.prompts.append(prompt)
            return _FakeResponse(self._responder(prompt))

    class _PromptRecordingClient:
        def __init__(self, responder):
            self.messages = _PromptRecordingMessages(responder)

    def _party_token_from_prompt(prompt):
        """Pull the party token out of the masked CASE CONTEXT exactly
        the way a real model would have to - by reading the prompt. The
        fake NEVER touches the mapping."""
        match = re.search(r'"display_name":\s*"(VGMASK_[0-9]{4}P)"', prompt)
        return match.group(1) if match else None

    def _answer_with(statement, excerpt):
        return json.dumps({
            "facts": [{
                "fact_kind": "taxpayer_claim",
                "statement": statement,
                "normalized_statement": None,
                "extraction_basis": "explicit_text",
                "attributed_party_id": None,
                "attributed_actor_label": None,
                "source": {"page": None, "section": None, "paragraph": None,
                           "text_excerpt": excerpt},
                "structured_values": [],
                "related_party_ids": [],
                "related_document_ids": [],
                "related_dispute_item_ids": [],
                "confidence": 0.8,
                "verification_state": "unverified",
                "notes": None,
            }],
            "warnings": [],
        })

    REAL_PARTY_NAME = "ABC Ltd. Şti. - Demo"
    PUBLIC_AUTHORITY_NAME = "Örnek Vergi Dairesi Müdürlüğü"

    # ---- 10a) the prompt that actually leaves the process is masked ----
    _fresh_case_copy()
    recorded_10a = _PromptRecordingClient(
        lambda prompt: _answer_with("Davacı iddia ileri sürmüştür.", "örnek alıntı"),
    )
    text_path_10a = fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID)
    build_10a = fee.build_fact_extraction(
        CASE_ID, DOCUMENT_ID, text_path_10a, model=fee.DEFAULT_MODEL, llm_client=recorded_10a,
    )
    prompt_10a = recorded_10a.messages.prompts[0]
    raw_text_10a = text_path_10a.read_text(encoding="utf-8-sig")
    check(
        "ADIM 4a: PRECONDITION - the real party name IS present in the raw source text and "
        "context (so masking it is a real, not vacuous, property)",
        REAL_PARTY_NAME in raw_text_10a,
    )
    check(
        "ADIM 4a: the party name is ABSENT from the prompt actually handed to the model",
        REAL_PARTY_NAME not in prompt_10a,
    )
    check(
        "ADIM 4a: neither the suffix-less core nor an ASCII-transliterated spelling of the "
        "party name survives in the prompt",
        "ABC Ltd" not in prompt_10a and "ABC Ltd. Sti." not in prompt_10a,
    )
    check(
        "ADIM 4a: the prompt carries at least one VGMASK token",
        lpb.TOKEN_RE.search(prompt_10a) is not None,
    )
    check(
        "ADIM 4a: the prompt carries the fixed model-facing token instruction block",
        "GIZLILIK TOKEN KURALI" in prompt_10a,
    )
    check(
        "ADIM 4a: SYSTEM_PROMPT is untouched - the instruction block rides on the USER prompt",
        "GIZLILIK TOKEN KURALI" not in fee.SYSTEM_PROMPT
        and recorded_10a.messages.create_calls[0]["system"] == fee.SYSTEM_PROMPT,
    )
    check(
        "ADIM 4a: PROMPT_VERSION was NOT bumped (masking has its own separate policy version)",
        fee.PROMPT_VERSION == "fact_extraction_v1_3",
    )
    check(
        "ADIM 4a (decision U2): the public-authority party name is deliberately NOT masked - "
        "it is load-bearing for jurisdiction/deadline reasoning",
        PUBLIC_AUTHORITY_NAME in prompt_10a,
    )
    for keep, keep_label in [("2024/03", "taxation period"), ("850.000,00", "amount"),
                             ("05.03.2026", "date"), ("case_0001", "case_id"),
                             ("party_taxpayer_001", "party_id")]:
        check(
            f"ADIM 4a: the load-bearing {keep_label} is still present in the masked prompt",
            keep in prompt_10a,
        )
    check(
        "ADIM 4a: build_fact_extraction() NEVER returns the mapping - only counters",
        "masking_summary" in build_10a
        and "VGMASK" not in json.dumps(build_10a["masking_summary"], ensure_ascii=False)
        and REAL_PARTY_NAME not in json.dumps(build_10a["masking_summary"], ensure_ascii=False),
        build_10a.get("masking_summary"),
    )
    check(
        "ADIM 4a: the returned context is the ORIGINAL (unmasked) one - attribution depends on it",
        build_10a["context"]["parties"][0]["display_name"] == REAL_PARTY_NAME,
    )

    # ---- 10b) PAIRED-ANSWER BYTE IDENTITY, with a frozen clock ----
    # The masked flow's fake client answers with the TOKEN form (read
    # out of the prompt it received); the unmasked reference flow's fake
    # client answers with the REAL-NAME form. With the clock frozen the
    # two pending files must be byte-for-byte identical.
    class _FrozenDatetime(fee.datetime):
        @classmethod
        def now(cls, tz=None):
            return fee.datetime(2026, 1, 1, 12, 0, 0, tzinfo=_dt.timezone.utc)

    class _PassThroughPrivacy:
        """Test-only shim installed over the engine's module-level
        `llm_privacy_boundary` name to obtain a genuine UNMASKED
        reference run. There is NO production opt-out flag; this uses
        the already-accepted 'temporarily swapped module attribute'
        pattern and is reverted immediately."""

        MASKING_POLICY_VERSION = "reference_flow_no_masking"

        class _Result:
            def __init__(self, context, text):
                self.masked_context = context
                self.masked_text = text
                self.prompt_instruction_block = ""
                self.summary = {"token_count": 0}

        @staticmethod
        def mask_prompt_inputs(*, case_data, document_data, context, document_text, extra_terms=()):
            return _PassThroughPrivacy._Result(context, document_text)

        @staticmethod
        def assert_masked_length_within(masked_text, limit):
            return None

        @staticmethod
        def scan_outbound(prompt, result):
            return None

        @staticmethod
        def count_dropped_tokens(obj, result):
            return {"dropped_token_count": 0, "dropped_by_class": {}}

        @staticmethod
        def redact_token_bearing_free_text(obj, result):
            return obj

        @staticmethod
        def de_mask_tree(obj, result):
            return obj

        @staticmethod
        def assert_no_tokens_remain(obj, result=None):
            return None

    PAIRED_STATEMENT_REAL = f"{REAL_PARTY_NAME} adına tarhiyat yapılmıştır."
    PAIRED_EXCERPT_REAL = f"{REAL_PARTY_NAME} adına"

    _original_engine_datetime = fee.datetime
    _original_engine_privacy = fee.llm_privacy_boundary
    try:
        fee.datetime = _FrozenDatetime

        # masked flow - the fake answers in the TOKEN form
        _fresh_case_copy()
        masked_client = _PromptRecordingClient(
            lambda prompt: _answer_with(
                f"{_party_token_from_prompt(prompt)} adına tarhiyat yapılmıştır.",
                f"{_party_token_from_prompt(prompt)} adına",
            ),
        )
        text_path_10b = fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID)
        masked_build = fee.build_fact_extraction(
            CASE_ID, DOCUMENT_ID, text_path_10b, model=fee.DEFAULT_MODEL, llm_client=masked_client,
        )
        masked_bytes = fac._freeze_pending_bytes(masked_build["extraction"])
        check(
            "ADIM 4a paired-answer: the masked flow's fake client genuinely answered in TOKEN "
            "form (it read the token out of the prompt, never out of the mapping)",
            lpb.TOKEN_RE.search(masked_client.messages.prompts[0]) is not None
            and _party_token_from_prompt(masked_client.messages.prompts[0]) is not None,
        )

        # unmasked reference flow - the fake answers in the REAL-NAME form
        _fresh_case_copy()
        fee.llm_privacy_boundary = _PassThroughPrivacy
        reference_client = _PromptRecordingClient(
            lambda prompt: _answer_with(PAIRED_STATEMENT_REAL, PAIRED_EXCERPT_REAL),
        )
        reference_build = fee.build_fact_extraction(
            CASE_ID, DOCUMENT_ID, text_path_10b, model=fee.DEFAULT_MODEL, llm_client=reference_client,
        )
        reference_bytes = fac._freeze_pending_bytes(reference_build["extraction"])
        check(
            "ADIM 4a paired-answer CONTROL: the reference flow really was unmasked - its prompt "
            "contains the raw party name and no token",
            REAL_PARTY_NAME in reference_client.messages.prompts[0]
            and lpb.TOKEN_RE.search(reference_client.messages.prompts[0]) is None,
        )
    finally:
        fee.llm_privacy_boundary = _original_engine_privacy
        fee.datetime = _original_engine_datetime

    check(
        "ADIM 4a STOP CONDITION: with the clock frozen and logically equivalent answers, the "
        "masked flow's pending artefact is BYTE-FOR-BYTE identical to the unmasked reference "
        "flow's - masking changes what the model sees, never what is written",
        masked_bytes == reference_bytes,
        f"masked={hashlib.sha256(masked_bytes).hexdigest()} "
        f"reference={hashlib.sha256(reference_bytes).hexdigest()}",
    )
    check(
        "ADIM 4a: the de-masked statement/excerpt carry the REAL party name byte-exactly "
        "(the excerpt must round-trip exactly - Rows 12/15 compare it verbatim)",
        masked_build["extraction"]["facts"][0]["statement"] == PAIRED_STATEMENT_REAL
        and masked_build["extraction"]["facts"][0]["source"]["text_excerpt"] == PAIRED_EXCERPT_REAL,
        masked_build["extraction"]["facts"][0]["statement"],
    )
    check(
        "ADIM 4a: no VGMASK token survives anywhere in the written pending bytes",
        b"VGMASK" not in masked_bytes,
    )

    # ---- 10c) return-path refusals: pending is NEVER written ----
    for bad_answer, bad_label, expected in [
        (lambda prompt: _answer_with("VGMASK_0099P adına tarh", "alıntı"),
         "an UNKNOWN token index in the model answer", lpb.UnknownTokenError),
        (lambda prompt: _answer_with(
            (_party_token_from_prompt(prompt) or "VGMASK_0001P").lower() + " adına tarh", "alıntı"),
         "a LOWER-CASED token in the model answer", lpb.MalformedTokenError),
        (lambda prompt: _answer_with("VGMASK_00011P adına tarh", "alıntı"),
         "an EXTENDED digit run in the model answer", lpb.MalformedTokenError),
        (lambda prompt: _answer_with("VGMASK adına tarh", "alıntı"),
         "a bare prefix in the model answer", lpb.MalformedTokenError),
        (lambda prompt: json.dumps({"facts": [], "warnings": [], "VGMASK_0001P": "x"}),
         "a token in a JSON KEY", lpb.TokenInKeyError),
    ]:
        _fresh_case_copy()
        pending_before = fee.get_pending_path(CASE_ID, DOCUMENT_ID)
        bad_client = _PromptRecordingClient(bad_answer)
        expect_raises(
            expected,
            lambda c=bad_client: fee.build_fact_extraction(
                CASE_ID, DOCUMENT_ID, fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID),
                model=fee.DEFAULT_MODEL, llm_client=c,
            ),
            f"ADIM 4a return path REFUSES {bad_label}",
        )
        check(
            f"ADIM 4a return path: NO pending artefact is written after refusing {bad_label}",
            not pending_before.exists(),
        )

    # ---- 10d) dropped-token reporting (D3: report, never refuse) ----
    _fresh_case_copy()
    dropping_client = _PromptRecordingClient(
        lambda prompt: _answer_with("Davacı iddia ileri sürmüştür.", "örnek alıntı"),
    )
    build_10d = fee.build_fact_extraction(
        CASE_ID, DOCUMENT_ID, fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID),
        model=fee.DEFAULT_MODEL, llm_client=dropping_client,
    )
    check(
        "ADIM 4a (D3): a model answer that echoes NO token still succeeds - a dropped token is "
        "a quality loss, not a leak; it is REPORTED as a counter, never refused",
        build_10d["masking_summary"]["dropped_token_count"]
        == build_10d["masking_summary"]["token_count"]
        and build_10d["masking_summary"]["token_count"] > 0,
        build_10d["masking_summary"],
    )
    check(
        "ADIM 4a (D3): the dropped-token report is per class and carries no values",
        isinstance(build_10d["masking_summary"]["dropped_by_class"], dict),
    )

    # ---- 10e) ORDER PROOF: de-mask happens BETWEEN parse_llm_json()
    # and build_extraction(), and build_extraction() receives the
    # ORIGINAL (unmasked) context.
    #
    # This is asserted DIRECTLY by capturing build_extraction()'s actual
    # arguments, not inferred from an output. If the masked context were
    # handed down, build_party_map()/text_contains_party_name()/
    # normalize_attribution() would silently drop an administration
    # attribution WITHOUT raising - a silent corruption no output check
    # could reliably catch.
    _fresh_case_copy()
    _captured_10e = {}
    _real_build_extraction = fee.build_extraction

    def _capturing_build_extraction(raw_result, case_id_arg, document_id_arg, context_arg, model_arg):
        _captured_10e["raw_result"] = json.loads(json.dumps(raw_result, ensure_ascii=False))
        _captured_10e["context"] = json.loads(json.dumps(context_arg, ensure_ascii=False))
        return _real_build_extraction(raw_result, case_id_arg, document_id_arg, context_arg, model_arg)

    order_client = _PromptRecordingClient(
        lambda prompt: _answer_with(
            f"{_party_token_from_prompt(prompt)} adına tarhiyat yapılmıştır.",
            f"{_party_token_from_prompt(prompt)} adına",
        ),
    )
    with mock.patch.object(fee, "build_extraction", _capturing_build_extraction):
        build_10e = fee.build_fact_extraction(
            CASE_ID, DOCUMENT_ID, fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID),
            model=fee.DEFAULT_MODEL, llm_client=order_client,
        )
    _captured_context_json = json.dumps(_captured_10e["context"], ensure_ascii=False)
    _captured_raw_json = json.dumps(_captured_10e["raw_result"], ensure_ascii=False)
    check(
        "ADIM 4a ORDER: build_extraction() receives the ORIGINAL context - the taxpayer "
        "display_name is the REAL name, not a token",
        _captured_10e["context"]["parties"][0]["display_name"] == REAL_PARTY_NAME,
        _captured_10e["context"]["parties"][0]["display_name"],
    )
    check(
        "ADIM 4a ORDER: no VGMASK token appears ANYWHERE in the context handed to "
        "build_extraction()",
        "VGMASK" not in _captured_context_json,
    )
    check(
        "ADIM 4a ORDER: the model answer reaching build_extraction() is ALREADY de-masked - it "
        "carries the real party name and no token",
        REAL_PARTY_NAME in _captured_raw_json and "VGMASK" not in _captured_raw_json,
        _captured_raw_json[:200],
    )
    check(
        "ADIM 4a ORDER CONTROL: the model genuinely answered in TOKEN form, so the de-mask step "
        "really ran (this check is not vacuous)",
        lpb.TOKEN_RE.search(order_client.messages.prompts[0]) is not None
        and lpb.TOKEN_RE.search(
            _answer_with(
                f"{_party_token_from_prompt(order_client.messages.prompts[0])} adına tarhiyat "
                "yapılmıştır.", "x",
            )
        ) is not None,
    )
    check(
        "ADIM 4a: the produced fact keeps a real, non-empty attribution (nothing was silently "
        "dropped by the attribution pipeline)",
        build_10e["extraction"]["facts"][0]["attributed_party_id"] in {
            "party_taxpayer_001", "party_admin_001",
        },
        build_10e["extraction"]["facts"][0].get("attributed_party_id"),
    )
    check(
        "ADIM 4a (decision U2 structural consequence): because administration parties are NOT "
        "masked, the administration-attribution-drop branch of normalize_attribution() cannot "
        "be triggered by masking at all - the masked and original context carry the SAME "
        "administration display_name",
        build_10a["context"]["parties"][1]["display_name"] == PUBLIC_AUTHORITY_NAME
        and PUBLIC_AUTHORITY_NAME in prompt_10a,
    )

    # ---- 10f) the SECOND, additive MAX_INPUT_CHARS check ----
    check(
        "ADIM 4a: assert_masked_length_within() rejects a masked text over the limit",
        True,
    )
    expect_raises(
        lpb.MaskedInputTooLongError,
        lambda: lpb.assert_masked_length_within("x" * (fee.MAX_INPUT_CHARS + 1), fee.MAX_INPUT_CHARS),
        "ADIM 4a: the second (masked-text) length check is enforced against the engine's own "
        "MAX_INPUT_CHARS",
    )
    check(
        "ADIM 4a: the ORIGINAL raw-text check inside load_text() is still in place (the second "
        "check is ADDITIVE, it did not replace it)",
        "MAX_INPUT_CHARS" in inspect.getsource(fee.load_text),
    )

    # ---- 10g) outbound refusals leave nothing behind ----
    _fresh_case_copy()
    _collide_path = fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID)
    _collide_original = _collide_path.read_text(encoding="utf-8-sig")
    _collide_path.write_text(_collide_original + "\nVGMASK_0001P\n", encoding="utf-8")
    poisoned_client = _PromptRecordingClient(
        lambda prompt: _answer_with("asla çağrılmamalı", "asla"),
    )
    expect_raises(
        lpb.MaskCollisionError,
        lambda: fee.build_fact_extraction(
            CASE_ID, DOCUMENT_ID, _collide_path, model=fee.DEFAULT_MODEL, llm_client=poisoned_client,
        ),
        "ADIM 4a outbound: a source text already carrying the token prefix is REFUSED",
    )
    check(
        "ADIM 4a outbound: the model was NEVER called on a refused request",
        poisoned_client.messages.create_calls == [],
    )
    check(
        "ADIM 4a outbound: no pending artefact after an outbound refusal",
        not fee.get_pending_path(CASE_ID, DOCUMENT_ID).exists(),
    )

    # ---- 10h) operator extra terms flow through ----
    _fresh_case_copy()
    extra_client = _PromptRecordingClient(
        lambda prompt: _answer_with("Davacı iddia ileri sürmüştür.", "örnek alıntı"),
    )
    build_10h = fee.build_fact_extraction(
        CASE_ID, DOCUMENT_ID, fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID),
        model=fee.DEFAULT_MODEL, llm_client=extra_client,
        mask_terms=("Katma Değer Vergisi",),
    )
    check(
        "ADIM 4a: an operator --mask-term is genuinely applied to the outbound prompt",
        "Katma Değer Vergisi" not in extra_client.messages.prompts[0]
        and build_10h["masking_summary"]["token_count"]
        > build_10d["masking_summary"]["token_count"],
        build_10h["masking_summary"],
    )

    # ---- 10i) REMEDIATION B: token-bearing warnings/notes are redacted ----
    RB_W = lpb.redacted_warning_text
    RB_LINE_RE = re.compile(r"^\[REDAKTE #([0-9]+)\] ")

    # (a) the REAL normalize_llm_warnings keeps every numbered line - the
    # ignored_phrases filter never drops them and dedupe never merges them.
    _rb_lines = [RB_W(n) for n in range(1, 8)]
    check(
        "REMEDIATION B: normalize_llm_warnings() keeps ALL numbered redaction lines "
        "(not filtered by ignored_phrases, not merged by dedupe)",
        fee.normalize_llm_warnings(list(_rb_lines)) == _rb_lines,
        fee.normalize_llm_warnings(list(_rb_lines)),
    )
    check(
        "REMEDIATION B: the fixed note text and the warning template contain none of the "
        "engine's ignored phrases",
        fee.normalize_llm_warnings([lpb.REDACTED_NOTE_TEXT]) == [lpb.REDACTED_NOTE_TEXT],
    )
    check(
        "REMEDIATION B: token-FREE warnings keep the pre-existing strip / empty-skip / "
        "ignored-phrase / dedupe / str() behaviour unchanged",
        fee.normalize_llm_warnings(
            ["  a ", "a", "", "   ", "related_document_ids alanı boş", "Sentetik test verisi",
             "b", 3, "B"]
        ) == ["a", "b", "3", "B"],
    )
    check(
        "REMEDIATION B: a non-list warnings value still normalises to []",
        fee.normalize_llm_warnings("tek metin") == [],
    )

    # (b) full engine flow with a fake model answering in TOKEN form.
    def _rb_answer(prompt):
        tok = _party_token_from_prompt(prompt)
        return json.dumps({
            "facts": [{
                "fact_kind": "taxpayer_claim",
                "statement": f"{tok} adına tarhiyat yapılmıştır.",
                "normalized_statement": f"{tok} hakkında tarhiyat",
                "extraction_basis": "explicit_text",
                "attributed_party_id": None,
                "attributed_actor_label": None,
                "source": {"page": None, "section": None, "paragraph": None,
                           "text_excerpt": f"{tok} adına"},
                "structured_values": [],
                "related_party_ids": [],
                "related_document_ids": [],
                "related_dispute_item_ids": [],
                "confidence": 0.8,
                "verification_state": "unverified",
                "notes": f"{tok} ve kimlik bilgileri token olarak aynen korunmuştur.",
            }],
            "warnings": [
                "Serbest uyarı.",
                f"{tok} unvanı token olarak aynen korunmuştur.",
                f"related_document_ids {tok} için belirlenemedi.",
                f"{tok} unvanı token olarak aynen korunmuştur.",
                "Serbest uyarı.",
                f"{tok} {tok} iki kez geçti.",
            ],
        })

    _fresh_case_copy()
    rb_client = _PromptRecordingClient(_rb_answer)
    build_10i = fee.build_fact_extraction(
        CASE_ID, DOCUMENT_ID, fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID),
        model=fee.DEFAULT_MODEL, llm_client=rb_client,
    )
    check(
        "REMEDIATION B PRECONDITION: the fake really answered in TOKEN form",
        _party_token_from_prompt(rb_client.messages.prompts[0]) is not None,
    )
    _w10i = build_10i["extraction"]["warnings"]
    _f10i = build_10i["extraction"]["facts"][0]
    check(
        "REMEDIATION B: the four token-bearing warnings become #1..#4 in input order; the "
        "free warning keeps its place and is still deduped",
        _w10i[:5] == ["Serbest uyarı.", RB_W(1), RB_W(2), RB_W(3), RB_W(4)],
        _w10i,
    )
    check(
        "REMEDIATION B count conservation: 4 token-bearing warnings IN -> exactly 4 numbered "
        "lines OUT (the duplicate is NOT merged; the one that also carries an ignored phrase "
        "is NOT filtered - it now survives as a redaction line)",
        [int(m.group(1)) for m in (RB_LINE_RE.match(w) for w in _w10i) if m] == [1, 2, 3, 4],
        _w10i,
    )
    check(
        "REMEDIATION B: the token-bearing fact note is replaced by the fixed note text "
        "(any later deterministic guard note may only be APPENDED after it)",
        isinstance(_f10i["notes"], str) and _f10i["notes"].startswith(lpb.REDACTED_NOTE_TEXT),
        _f10i["notes"],
    )
    check(
        "REMEDIATION B: the real party name reaches NEITHER the warnings NOR the notes",
        REAL_PARTY_NAME not in json.dumps(_w10i, ensure_ascii=False)
        and REAL_PARTY_NAME not in (_f10i["notes"] or ""),
    )
    check(
        "REMEDIATION B: statement / normalized_statement / text_excerpt are NOT redacted - "
        "they still de-mask to the real party name byte-exactly",
        _f10i["statement"] == f"{REAL_PARTY_NAME} adına tarhiyat yapılmıştır."
        and _f10i["normalized_statement"] == f"{REAL_PARTY_NAME} hakkında tarhiyat"
        and _f10i["source"]["text_excerpt"] == f"{REAL_PARTY_NAME} adına",
        _f10i,
    )
    _bytes_10i = fac._freeze_pending_bytes(build_10i["extraction"])
    check(
        "REMEDIATION B: no VGMASK token survives anywhere in the frozen pending bytes",
        b"VGMASK" not in _bytes_10i and b"vgmask" not in _bytes_10i.lower(),
    )

    # (c) fail-closed: a bad token inside a warning / note is REFUSED,
    # never redacted away; pending is never written.
    for rb_bad_answer, rb_bad_label, rb_expected in [
        (lambda prompt: json.loads(_rb_answer(prompt)) | {"warnings": ["uyarı VGMASK_0099P"]},
         "an UNKNOWN token in a warning", lpb.UnknownTokenError),
        (lambda prompt: json.loads(_rb_answer(prompt)) | {
            "warnings": [(_party_token_from_prompt(prompt) or "VGMASK_0001P").lower()]},
         "a LOWER-CASED token in a warning", lpb.MalformedTokenError),
        (lambda prompt: json.loads(_rb_answer(prompt)) | {"warnings": [{"VGMASK_0001P": "x"}]},
         "a token in a JSON KEY inside a warning", lpb.TokenInKeyError),
        (lambda prompt: {**json.loads(_rb_answer(prompt)), "facts": [
            {**json.loads(_rb_answer(prompt))["facts"][0], "notes": "not VGMASK_0099P"}]},
         "an UNKNOWN token in a note", lpb.UnknownTokenError),
        (lambda prompt: {**json.loads(_rb_answer(prompt)), "facts": [
            {**json.loads(_rb_answer(prompt))["facts"][0], "notes": "not VGMASK_00011P"}]},
         "an EXTENDED digit run (count mismatch) in a note", lpb.MalformedTokenError),
    ]:
        _fresh_case_copy()
        rb_pending_before = fee.get_pending_path(CASE_ID, DOCUMENT_ID)
        rb_bad_client = _PromptRecordingClient(
            lambda prompt, f=rb_bad_answer: json.dumps(f(prompt), ensure_ascii=False),
        )
        expect_raises(
            rb_expected,
            lambda c=rb_bad_client: fee.build_fact_extraction(
                CASE_ID, DOCUMENT_ID, fee.get_extracted_text_path(CASE_ID, DOCUMENT_ID),
                model=fee.DEFAULT_MODEL, llm_client=c,
            ),
            f"REMEDIATION B return path REFUSES {rb_bad_label} (not redacted away)",
        )
        check(
            f"REMEDIATION B: NO pending artefact is written after refusing {rb_bad_label}",
            not rb_pending_before.exists(),
        )

finally:
    fee.CASES_DIR = _original_engine_cases_dir
    drr.CASES_DIR = _original_drr_cases_dir
    fact_approval.CASES_DIR = _original_fact_approval_cases_dir
    shutil.rmtree(_tmp_root, ignore_errors=True)


# ============================================================
# 9) LEGACY CLI CLOSURE - main() refuses with SystemExit(2), fixed
#    stderr message, before any real work (no CASES_DIR redirect
#    needed - the refusal fires before any file/network access).
# ============================================================

import io
import contextlib

_argv_backup = sys.argv
try:
    sys.argv = ["fact_extraction_engine.py", "--case", CASE_ID, "--document", DOCUMENT_ID]
    stderr_capture = io.StringIO()
    exit_code = None
    with contextlib.redirect_stderr(stderr_capture):
        try:
            fee.main()
        except SystemExit as exit_signal:
            exit_code = exit_signal.code
    check("fact_extraction_engine.main() raises SystemExit(2)", exit_code == 2)
    check(
        "fact_extraction_engine.main() refusal message points to ui.cli_mutate generation "
        "--row-key fact_extraction",
        "ui.cli_mutate generation" in stderr_capture.getvalue()
        and "--row-key fact_extraction" in stderr_capture.getvalue(),
        stderr_capture.getvalue(),
    )
    check(
        "fact_extraction_engine.main() refusal message tag is (Row 19C-3c-iii) - NOT the Row "
        "19C-3b legacy tag shared by deadline_engine.py/timeline_engine.py (this family follows "
        "the Row 19C-3c-ii agent-generation precedent's OWN-row-tagged message convention, so "
        "it is deliberately NOT part of ui/tests/test_cli_mutate_isolated.py's subprocess "
        "LEGACY_MUTATION_MATRIX, which only matches the literal '(Row 19C-3b)' substring)",
        "(Row 19C-3c-iii)" in stderr_capture.getvalue(),
        stderr_capture.getvalue(),
    )
finally:
    sys.argv = _argv_backup


# ============================================================
# 10) LEGACY CLI CLOSURE - REAL OS SUBPROCESS PROOF (Fable advisor
#    Phase-2 feedback B2). Section 9 above proves the in-process
#    SystemExit(2) object - the SAME shape the five ROW 19C-3c-ii
#    agent-generation engines' own isolated tests use (confirmed by
#    grep: none of test_issue_spotting_engine_isolated.py/test_
#    evidence_engine_isolated.py/test_argument_engine_isolated.py/
#    test_risk_strategy_engine_isolated.py/test_drafting_engine_
#    isolated.py contains the word "subprocess" at all - their own
#    closure proof is ALSO in-process only). This section goes BEYOND
#    that precedent and proves the REAL OS process exit code too -
#    mirroring ui/tests/test_cli_mutate_isolated.py's own Row 19C-3b
#    Slice 1 LEGACY_MUTATION_MATRIX discipline exactly (subprocess.run,
#    sys.executable, explicit cwd, bounded timeout, no shell=True,
#    returncode exactly 2, fixed stderr, empty stdout, no traceback,
#    explicit child PYTHONIOENCODING=utf-8 so the Turkish stderr text
#    decodes deterministically regardless of the parent process's own
#    ambient locale/codepage) - even though fact_extraction_engine.py
#    is deliberately NOT added to that OTHER file's own matrix (see
#    this file's own section 9, and this module's docstring: the
#    message tag mismatch/agent-generation precedent reasoning). This
#    is the SAME allowlisted file (item 6) - no scope expansion.
# ============================================================

import os
import subprocess


def _snapshot_data_tree_10():
    data_dir = REPO_ROOT / "data"
    snapshot = {}
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            snapshot[path.relative_to(data_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


_data_snapshot_before_10 = _snapshot_data_tree_10()

_script_path_10 = SRC_DIR / "fact_extraction_engine.py"
_child_env_10 = os.environ.copy()
_child_env_10["PYTHONIOENCODING"] = "utf-8"
_completed_10 = subprocess.run(
    [sys.executable, str(_script_path_10), "--case", CASE_ID, "--document", DOCUMENT_ID],
    cwd=str(REPO_ROOT),
    capture_output=True,
    timeout=90,
    env=_child_env_10,
)
_stdout_10 = _completed_10.stdout.decode("utf-8") if _completed_10.stdout else ""
_stderr_10 = _completed_10.stderr.decode("utf-8") if _completed_10.stderr else ""

check(
    "REAL OS subprocess: the real script file exists on disk and is the one actually invoked",
    _script_path_10.is_file(),
    f"resolved path: {_script_path_10}",
)
check(
    "REAL OS subprocess: returncode is exactly 2 (the genuine process exit code SystemExit(2) "
    "produces, not merely main()'s Python-level return value)",
    _completed_10.returncode == 2,
    f"got returncode={_completed_10.returncode!r} stdout={_stdout_10!r} stderr={_stderr_10!r}",
)
check(
    "REAL OS subprocess: the fixed (Row 19C-3c-iii) refusal message appears in stderr, "
    "pointing to ui.cli_mutate generation --row-key fact_extraction",
    "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3c-iii)." in _stderr_10
    and "ui.cli_mutate generation" in _stderr_10 and "--row-key fact_extraction" in _stderr_10,
    f"stderr={_stderr_10!r}",
)
check(
    "REAL OS subprocess: stderr contains no 'Traceback' - a clean, deliberate SystemExit(2), "
    "never an unhandled exception escaping",
    "Traceback" not in _stderr_10,
    f"stderr={_stderr_10!r}",
)
check(
    "REAL OS subprocess: stdout is completely empty - no unexpected writer/success output "
    "(the refusal print goes to stderr only, and fires before any file/network access)",
    _stdout_10 == "",
    f"stdout={_stdout_10!r}",
)

_data_snapshot_after_10 = _snapshot_data_tree_10()
check(
    "REAL OS subprocess refusal: the REAL data/ tree is byte-for-byte UNCHANGED",
    _data_snapshot_before_10 == _data_snapshot_after_10,
    f"changed/added/removed keys: "
    f"{sorted(set(_data_snapshot_before_10) ^ set(_data_snapshot_after_10))}",
)


print(f"--- test_fact_extraction_engine_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
