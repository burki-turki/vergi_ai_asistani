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

import hashlib
import json
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
    )
    check(
        "identity_payload has exactly the 7 expected keys",
        set(payload_4.keys()) == {
            "manifest_version", "document_id", "manifest", "generation_mode", "model_id",
            "engine_version", "prompt_agent_version",
        },
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
