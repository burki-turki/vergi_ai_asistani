# ============================================================
# ROW 19C-3c-iii - ui/services/fact_extraction_mutation_facade.py
# ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no real mutation coordinator connection -
# exercises the facade's own pure/read-only functions directly: usage-
# shape validation (including the family's STRICTER dual network gate),
# the containment-before-traversal FOUR-container manifest scanner
# (including real Windows NTFS junctions for escaping/broken-link
# cases, and a `Path.glob()` zero-call mechanical proof), identity
# payload freeze/reconstruct (7-key shape, `document_id`/`engine_
# version` included), verified output-path derivation, the READ-ONLY,
# UNLOCKED build-skip precheck (spec §D) against a FAKE DB-API-2.0-
# shaped connection, and the build-skipped-writer-unexpectedly-reached
# fail-closed SENTINEL (via a mocked `mutation_coordinator.run_mutation`
# - no real PostgreSQL journal residue is ever produced by this file).
#
# Run: python ui/tests/test_fact_extraction_mutation_facade_isolated.py
# ============================================================

import hashlib
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

import fact_extraction_engine as fee                          # noqa: E402
import document_reference_resolver as drr                     # noqa: E402
from ui.services import fact_extraction_mutation_facade as fac  # noqa: E402
from ui.services import authz as _authz                       # noqa: E402
from ui.services import mutation_coordinator as _mc            # noqa: E402

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


# ============================================================
# 1) Row-key/action-family/target-ref helpers - pure, no I/O.
# ============================================================

check(
    "FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME has exactly the one expected family",
    dict(fac.FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME) == {"fact_extraction": "fact_extraction_engine"},
)
check(
    "fact_extraction_action_family_for produces the exact generation.fact_extraction string",
    fac.fact_extraction_action_family_for("fact_extraction") == "generation.fact_extraction",
)
expect_raises(
    KeyError, lambda: fac.fact_extraction_action_family_for("not_a_real_family"),
    "fact_extraction_action_family_for: unknown row_key raises KeyError",
)
check(
    "fact_extraction_target_ref_for produces the exact fact.<document_id>.pending string "
    "(DOCUMENT-scoped, unlike every other generation family's case-scoped target_ref)",
    fac.fact_extraction_target_ref_for("some_doc_id") == "fact.some_doc_id.pending",
)


# ============================================================
# 2) Usage-shape validation - pure, no I/O, before any connection. This
#    family is STRICTER than the five/two precedent families: with_agent
#    is REQUIRED on BOTH preview and apply (never optional), and apply
#    ALSO requires allow_network unconditionally.
# ============================================================

expect_raises(
    fac.FactExtractionArgumentError,
    lambda: fac._check_argument_shapes("", for_apply=False, with_agent=True),
    "_check_argument_shapes: blank document_id raises FactExtractionArgumentError",
)
expect_raises(
    fac.FactExtractionArgumentError,
    lambda: fac._check_argument_shapes(None, for_apply=False, with_agent=True),
    "_check_argument_shapes: None document_id raises FactExtractionArgumentError",
)
expect_raises(
    fac.FactExtractionArgumentError,
    lambda: fac._check_argument_shapes("doc1", for_apply=False, with_agent=False),
    "_check_argument_shapes: with_agent=False on PREVIEW raises FactExtractionArgumentError "
    "(this family has no deterministic mode)",
)
expect_raises(
    fac.FactExtractionArgumentError,
    lambda: fac._check_argument_shapes("doc1", for_apply=True, with_agent=False, allow_network=True),
    "_check_argument_shapes: with_agent=False on APPLY raises FactExtractionArgumentError even "
    "with allow_network=True",
)
expect_raises(
    fac.FactExtractionArgumentError,
    lambda: fac._check_argument_shapes("doc1", None, for_apply=True, with_agent=True, allow_network=True),
    "_check_argument_shapes: apply without expected_input_digest raises FactExtractionArgumentError",
)
expect_raises(
    fac.FactExtractionArgumentError,
    lambda: fac._check_argument_shapes("doc1", "somedigest", for_apply=True, with_agent=True, allow_network=False),
    "_check_argument_shapes: apply with_agent=True but allow_network=False raises "
    "FactExtractionArgumentError (apply requires BOTH, unconditionally)",
)
try:
    fac._check_argument_shapes("doc1", "somedigest", for_apply=True, with_agent=True, allow_network=True)
    check("_check_argument_shapes: apply WITH with_agent+allow_network+expected_input_digest passes", True)
except Exception as error:  # noqa: BLE001
    check(
        "_check_argument_shapes: apply WITH with_agent+allow_network+expected_input_digest passes",
        False, str(error),
    )
try:
    fac._check_argument_shapes("doc1", for_apply=False, with_agent=True)
    check("_check_argument_shapes: preview WITH with_agent=True passes", True)
except Exception as error:  # noqa: BLE001
    check("_check_argument_shapes: preview WITH with_agent=True passes", False, str(error))


# ============================================================
# 3) Model/engine/prompt provenance - production / injected-client, read
#    fresh via the module reference each call (no caching).
# ============================================================

mode_a, model_a, engine_a, prompt_a = fac._resolve_generation_provenance(fee, None)
check(
    "production provenance: generation_mode='agent' (NO deterministic mode exists for this "
    "family), model_id=fee.DEFAULT_MODEL, engine_version/prompt_agent_version are the REAL "
    "engine constants",
    mode_a == "agent" and model_a == fee.DEFAULT_MODEL
    and engine_a == fee.FACT_EXTRACTION_ENGINE_VERSION and prompt_a == fee.PROMPT_VERSION,
)


class _FakeLLMClient:
    def generate(self, prompt):
        raise AssertionError("provenance resolution must never call .generate()")


mode_b, model_b, engine_b, prompt_b = fac._resolve_generation_provenance(fee, _FakeLLMClient())
check(
    "injected client: model_id sentinel 'external_injected_client', engine_version/"
    "prompt_agent_version REAL (not sentinels), .generate() never called",
    mode_b == "agent" and model_b == "external_injected_client"
    and engine_b == fee.FACT_EXTRACTION_ENGINE_VERSION and prompt_b == fee.PROMPT_VERSION,
)


# ============================================================
# 4) Identity payload freeze/reconstruct - canonical bytes, exact
#    round-trip, mutation-after-freeze does not leak, exactly 7 keys.
# ============================================================

payload_c = fac._build_identity_payload(
    "doc_x", [{"logical_name": "case", "state": "present", "files": []}],
    "agent", fee.DEFAULT_MODEL, fee.FACT_EXTRACTION_ENGINE_VERSION, fee.PROMPT_VERSION,
)
check(
    "identity_payload has exactly the 7 expected keys",
    set(payload_c.keys()) == {
        "manifest_version", "document_id", "manifest", "generation_mode", "model_id",
        "engine_version", "prompt_agent_version",
    },
)
bytes_c1 = fac._canonical_identity_bytes(payload_c)
bytes_c2 = fac._canonical_identity_bytes(json.loads(json.dumps(payload_c)))
check("canonical identity bytes are deterministic across equal-content payloads", bytes_c1 == bytes_c2)

digest_c = fac._compute_input_digest(bytes_c1)
check("input_digest is a 64-hex-char sha256", len(digest_c) == 64 and all(ch in "0123456789abcdef" for ch in digest_c))

reconstructed_c = json.loads(bytes_c1.decode("utf-8"))
payload_c["manifest"].append({"MUTATED": True})  # mutate original after freeze
check(
    "reconstructed identity payload is unaffected by post-freeze mutation of the original dict",
    reconstructed_c["manifest"] == [{"logical_name": "case", "state": "present", "files": []}],
)


# ============================================================
# 5) Manifest scanner - real case_0001, no mutation (read-only scan).
#    Exactly FOUR containers, sorted, POSIX-form relative paths.
# ============================================================

case_root_5 = fac._resolve_module_case_root_real(fee, CASE_ID)
manifest_5 = fac._build_manifest_containers(case_root_5, DOCUMENT_ID)
check("real case_0001 manifest scan: exactly 4 containers", len(manifest_5) == 4)
check(
    "real case_0001 manifest scan: sorted by logical_name",
    [c["logical_name"] for c in manifest_5] == sorted(c["logical_name"] for c in manifest_5),
)
check(
    "real case_0001 manifest scan: logical_name set is exactly "
    "{case, case_documents, target_document, target_document_text}",
    {c["logical_name"] for c in manifest_5}
    == {"case", "case_documents", "target_document", "target_document_text"},
)
for container in manifest_5:
    for file_entry in container["files"]:
        check(
            f"{container['logical_name']}: logical_relative_path is POSIX-form (no backslash)",
            "\\" not in file_entry["logical_relative_path"],
        )
target_doc_container_5 = next(c for c in manifest_5 if c["logical_name"] == "target_document")
check(
    "real case_0001, dava_dilekcesi_001: target_document is present (real document.json exists)",
    target_doc_container_5["state"] == "present",
)
target_text_container_5 = next(c for c in manifest_5 if c["logical_name"] == "target_document_text")
check(
    "real case_0001, dava_dilekcesi_001: target_document_text is present (real extracted/*.txt "
    "exists, matching the deterministic convention)",
    target_text_container_5["state"] == "present",
)
case_documents_container_5 = next(c for c in manifest_5 if c["logical_name"] == "case_documents")
check(
    "real case_0001: case_documents contains the target document AGAIN (kasıtlı hafif "
    "redundancy, defensive completeness - matches precedent's own 'documents' kind principle)",
    any(
        f"documents/{DOCUMENT_ID}/document.json" == f["logical_relative_path"]
        for f in case_documents_container_5["files"]
    ),
)

expect_raises(
    fac.FactExtractionInputContainmentError,
    lambda: fac._build_manifest_containers(case_root_5, "a_document_id_that_does_not_exist"),
    "manifest scan: nonexistent document_id raises FactExtractionInputContainmentError "
    "(target_document required=True)",
)
expect_raises(
    fac.FactExtractionInputContainmentError,
    lambda: fac._build_manifest_containers(case_root_5, "../escape_attempt"),
    "manifest scan: a traversal-shaped document_id is rejected by validate_segment() before "
    "any filesystem probe",
)


# ============================================================
# 6) Containment safety - real Windows NTFS junctions (mklink /J,
#    never monkeypatched) for escaping/broken links, proving the
#    scanner fails closed and never treats a broken/escaping link as
#    "missing".
# ============================================================

_tmp_containment_root = Path(tempfile.mkdtemp(prefix="vergi_fac_containment_"))

try:
    fixture_case = _tmp_containment_root / "cases" / CASE_ID
    shutil.copytree(REAL_CASE_0001, fixture_case)
    stale_extractions = fixture_case / "documents" / DOCUMENT_ID / "extractions"
    for stale in stale_extractions.glob("*.pending"):
        stale.unlink()

    original_cases_dir = fee.CASES_DIR
    fee.CASES_DIR = _tmp_containment_root / "cases"
    try:
        if sys.platform == "win32":
            outside_target = _tmp_containment_root / "outside_canary"
            outside_target.mkdir()
            (outside_target / "document.json").write_text("{}", encoding="utf-8")

            documents_dir = fixture_case / "documents"
            escaping_junction = documents_dir / "escaping_doc"

            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(escaping_junction), str(outside_target)],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                case_root_f = fac._resolve_module_case_root_real(fee, CASE_ID)

                stat_calls = []
                real_stat = os.stat

                def _recording_stat(path, *a, **kw):
                    stat_calls.append(str(path))
                    return real_stat(path, *a, **kw)

                with mock.patch("os.stat", side_effect=_recording_stat):
                    raised_escape = False
                    try:
                        fac._scan_verified_leaf_chain(
                            case_root_f, documents_dir.resolve(strict=False), ("document.json",),
                        )
                    except fac.FactExtractionInputContainmentError:
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
                case_root_g = fac._resolve_module_case_root_real(fee, CASE_ID)
                raised_broken = False
                try:
                    fac._scan_verified_leaf_chain(
                        case_root_g, documents_dir.resolve(strict=False), ("document.json",),
                    )
                except fac.FactExtractionInputContainmentError:
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
        fee.CASES_DIR = original_cases_dir
finally:
    shutil.rmtree(_tmp_containment_root, ignore_errors=True)


# ============================================================
# 7) Path.glob() zero-call mechanical proof - the manifest scanner must
#    never call it, on real case_0001.
# ============================================================

_glob_calls = []
_real_glob = Path.glob


def _recording_glob(self, pattern, *a, **kw):
    _glob_calls.append((str(self), pattern))
    return _real_glob(self, pattern, *a, **kw)


with mock.patch.object(Path, "glob", _recording_glob):
    case_root_7 = fac._resolve_module_case_root_real(fee, CASE_ID)
    fac._build_manifest_containers(case_root_7, DOCUMENT_ID)

check(
    "Path.glob() is NEVER called anywhere in the manifest scanner, on real case_0001",
    _glob_calls == [],
    f"unexpected glob calls: {_glob_calls}",
)


# ============================================================
# 8) READ-ONLY, UNLOCKED BUILD-SKIP PRECHECK (spec §D) - fake DB-API-
#    2.0-shaped connection, no real PostgreSQL. Proves the exact table:
#    no row -> True (build needed); ANY row (regardless of state) ->
#    False; DB error/malformed/unexpected -> True (fail-safe, never
#    wrongly skips).
# ============================================================

class _FakeCursor:
    def __init__(self, row, *, raise_on_execute=None):
        self._row = row
        self._raise_on_execute = raise_on_execute

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=()):
        if self._raise_on_execute is not None:
            raise self._raise_on_execute
        self._executed_sql = sql
        self._executed_params = params

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row, *, raise_on_execute=None, raise_on_close=False):
        self._row = row
        self._raise_on_execute = raise_on_execute
        self._raise_on_close = raise_on_close
        self.closed = False

    def cursor(self):
        return _FakeCursor(self._row, raise_on_execute=self._raise_on_execute)

    def close(self):
        self.closed = True
        if self._raise_on_close:
            raise RuntimeError("close() failed")


check(
    "_precheck_build_skip: NO row for this idempotency_key -> build_needed=True (spec §D: "
    "'satır yokken build yanlışlıkla atlanmadı')",
    fac._precheck_build_skip(lambda: _FakeConn(None), "some_key") is True,
)
for label, row in [
    ("a row exists (arbitrary shape - only presence matters)", (1,)),
]:
    check(
        f"_precheck_build_skip: {label} -> build_needed=False (spec §D: ANY existing row, "
        "regardless of state, skips the wasted build - the authoritative decision is always "
        "made later, under lock, by run_mutation()'s own unchanged idempotency lookup)",
        fac._precheck_build_skip(lambda: _FakeConn(row), "some_key") is False,
    )
check(
    "_precheck_build_skip: conn_factory() itself raises -> build_needed=True (fail-safe)",
    fac._precheck_build_skip(
        lambda: (_ for _ in ()).throw(RuntimeError("cannot connect")), "some_key",
    ) is True,
)
check(
    "_precheck_build_skip: cursor.execute() raises -> build_needed=True (fail-safe)",
    fac._precheck_build_skip(
        lambda: _FakeConn(None, raise_on_execute=RuntimeError("query failed")), "some_key",
    ) is True,
)
_closing_conn = _FakeConn(None)
result_closes = fac._precheck_build_skip(lambda: _closing_conn, "some_key")
check(
    "_precheck_build_skip: the connection is closed after use (no-row path)",
    _closing_conn.closed is True and result_closes is True,
)
check(
    "_precheck_build_skip: a raising close() never masks/changes the already-decided result "
    "(best-effort cleanup only)",
    fac._precheck_build_skip(lambda: _FakeConn(None, raise_on_close=True), "some_key") is True,
)


# ============================================================
# 9) MOCKED END-TO-END: build_needed=False FORCED, but the (mocked)
#    coordinator UNEXPECTEDLY reaches writer_callback anyway - the
#    fail-closed SENTINEL must fire, build_fact_extraction() must NEVER
#    be called, and zero REAL PostgreSQL residue is ever produced (the
#    coordinator itself is mocked, never a real connection).
# ============================================================

_tmp_sentinel_root = Path(tempfile.mkdtemp(prefix="vergi_fac_sentinel_"))
_tmp_sentinel_cases = _tmp_sentinel_root / "cases"
_tmp_sentinel_cases.mkdir(parents=True)

_original_fee_cases_dir = fee.CASES_DIR
_original_drr_cases_dir = drr.CASES_DIR


def _fresh_sentinel_case():
    dest = _tmp_sentinel_cases / CASE_ID
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


class _FakeAuthzRepo:
    def get_session_authz_state(self, principal):
        return _authz.SessionRecord(user_id=principal.user_id, current_authz_version=1, disabled=False)

    def get_active_case_assignment(self, user_id, case_id):
        return _authz.CaseAssignmentRecord(role="lawyer")

    def list_active_case_ids_for_user(self, user_id):
        return [CASE_ID]

    def is_global_admin(self, user_id):
        return False


class _FakeLockConn:
    def close(self):
        pass


_principal_9 = _authz.Principal(user_id=7, session_id=0, role_version_at_issue=1)

try:
    fee.CASES_DIR = _tmp_sentinel_cases
    drr.CASES_DIR = _tmp_sentinel_cases
    _fresh_sentinel_case()

    preview_9 = fac.preview_generation(
        CASE_ID, DOCUMENT_ID, with_agent=True, principal=_principal_9, authz_repository=_FakeAuthzRepo(),
    )
    expected_digest_9 = preview_9["input_digest"]

    def _poisoned_build_fact_extraction(*args, **kwargs):
        raise AssertionError(
            "build_fact_extraction() was called despite build_needed=False - the precheck's "
            "build-skip optimization was NOT honored"
        )

    def _fake_run_mutation_reaches_writer(conn, intent, *, actor_user_id, authz_callback, precondition_callback, writer_callback):
        authz_callback()
        precondition_callback()
        # Simulates the coordinator's own authoritative idempotency
        # lookup UNEXPECTEDLY disagreeing with the pre-check's
        # optimistic assumption (spec §D: "run_mutation() BEKLENMEDİK
        # biçimde writer'a ulaşırsa") - reaches writer_callback anyway.
        writer_callback()
        raise AssertionError("writer_callback() should have raised before this point")

    with mock.patch.object(fee, "build_fact_extraction", _poisoned_build_fact_extraction), \
         mock.patch.object(fac, "_precheck_build_skip", lambda conn_factory, key: False), \
         mock.patch.object(fac._mutation_lock, "acquire_case_lock_session", lambda conn, case_id: 999), \
         mock.patch.object(fac._mutation_lock, "release_lock_session", lambda conn, lock_id: True), \
         mock.patch.object(fac._mutation_coordinator, "run_mutation", _fake_run_mutation_reaches_writer):
        expect_raises(
            fac.FactExtractionBuildSkippedInvariantError,
            lambda: fac.apply_generation(
                CASE_ID, DOCUMENT_ID, expected_digest_9,
                with_agent=True, allow_network=True,
                principal=_principal_9, authz_repository=_FakeAuthzRepo(),
                conn_factory=lambda: _FakeLockConn(),
            ),
            "apply_generation(): build_needed=False + coordinator unexpectedly reaches "
            "writer_callback -> FactExtractionBuildSkippedInvariantError (fail-closed sentinel), "
            "build_fact_extraction() NEVER called (poisoned function would have raised "
            "AssertionError otherwise, which expect_raises would report as the WRONG exception "
            "type)",
        )

    # ============================================================
    # 10) MOCKED END-TO-END: build_needed=False FORCED, coordinator does
    #     NOT reach the writer (a genuine safe replay) - apply_
    #     generation() must succeed, build_fact_extraction() must NEVER
    #     be called, and post-outcome replay corroboration must find the
    #     real, pre-seeded audit/pending fixture on disk.
    # ============================================================

    pending_path_10 = fee.get_pending_path(CASE_ID, DOCUMENT_ID)
    reviews_dir_10 = fee.get_reviews_dir(CASE_ID, DOCUMENT_ID)
    pending_content_10 = '{"schema_version":1,"extraction_id":"x","facts":[]}'
    pending_path_10.parent.mkdir(parents=True, exist_ok=True)
    pending_path_10.write_text(pending_content_10, encoding="utf-8")
    pending_sha_10 = hashlib.sha256(pending_content_10.encode("utf-8")).hexdigest()

    resource_key_10 = f"case:{CASE_ID}"
    # The REAL idempotency_key apply_generation() would compute for THIS
    # exact (actor, resource, action_family, target_ref, pre_revision)
    # tuple - a fake/arbitrary string here would never match what
    # _verify_completed_replay_binding() actually looks up.
    real_intent_10 = fac.MutationIntent(
        actor_type="iam_user", actor_ref=str(_principal_9.user_id),
        resource_key=resource_key_10, action_family="generation.fact_extraction",
        target_ref=fac.fact_extraction_target_ref_for(DOCUMENT_ID), target_state="generated",
        pre_hash="unused_placeholder_not_part_of_identity", pre_revision=expected_digest_9,
        secondary_input_hash=None,
    )
    real_idempotency_key_10 = fac.compute_idempotency_key(real_intent_10)
    audit_record_10 = {
        "schema_version": "1", "case_id": CASE_ID, "document_id": DOCUMENT_ID,
        "target_ref": fac.fact_extraction_target_ref_for(DOCUMENT_ID), "target_state": "generated",
        "action_family": "generation.fact_extraction", "channel": "local_lawyer_fact_extraction_cli",
        "mutation_idempotency_key": real_idempotency_key_10, "mutation_resource_key": resource_key_10,
        "mutation_actor_ref": "7", "input_digest": expected_digest_9,
        "generation_parameters_digest": None, "generation_mode": "agent",
        # preview_9 was taken WITHOUT an llm_client (production
        # provenance) - the fixture's model_id must match what actually
        # produced expected_digest_9, i.e. fee.DEFAULT_MODEL, NOT the
        # injected-client sentinel.
        "model_id": fee.DEFAULT_MODEL, "engine_version": fee.FACT_EXTRACTION_ENGINE_VERSION,
        "prompt_agent_version": fee.PROMPT_VERSION,
        "identity_payload": json.loads(json.dumps({
            "manifest_version": fac._MANIFEST_VERSION, "document_id": DOCUMENT_ID,
            "manifest": fac._build_manifest_containers(
                fac._resolve_module_case_root_real(fee, CASE_ID), DOCUMENT_ID,
            ),
            "generation_mode": "agent", "model_id": fee.DEFAULT_MODEL,
            "engine_version": fee.FACT_EXTRACTION_ENGINE_VERSION, "prompt_agent_version": fee.PROMPT_VERSION,
        })),
        "first_write": True, "history_backup_path": None, "history_backup_sha256": None,
        "pending_sha256": pending_sha_10, "generated_at": "2026-01-01T00:00:00+00:00",
        "outcome": "generated", "written_at": "2026-01-01T00:00:01+00:00",
    }
    # The audit's own identity_payload must actually re-hash to
    # expected_digest_9 for real corroboration to succeed - use the
    # SAME frozen bytes recipe the facade itself uses.
    recomputed_digest_check = fac._compute_input_digest(
        fac._canonical_identity_bytes(audit_record_10["identity_payload"]),
    )
    check(
        "fixture setup: the hand-built audit's identity_payload genuinely re-hashes to "
        "expected_digest_9 (a real, non-tautological corroboration fixture)",
        recomputed_digest_check == expected_digest_9,
    )
    reviews_dir_10.mkdir(parents=True, exist_ok=True)
    (reviews_dir_10 / "extract_replay_fixture.generation_audit.json").write_text(
        json.dumps(audit_record_10), encoding="utf-8",
    )

    def _fake_run_mutation_safe_replay(conn, intent, *, actor_user_id, authz_callback, precondition_callback, writer_callback):
        authz_callback()
        precondition_callback()
        return _mc.MutationOutcome(
            journal_id=1, state="completed", result=None,
            observed_post_hash=pending_sha_10, replayed=True,
        )

    with mock.patch.object(fee, "build_fact_extraction", _poisoned_build_fact_extraction), \
         mock.patch.object(fac, "_precheck_build_skip", lambda conn_factory, key: False), \
         mock.patch.object(fac._mutation_lock, "acquire_case_lock_session", lambda conn, case_id: 999), \
         mock.patch.object(fac._mutation_lock, "release_lock_session", lambda conn, lock_id: True), \
         mock.patch.object(fac._mutation_coordinator, "run_mutation", _fake_run_mutation_safe_replay):
        result_10 = fac.apply_generation(
            CASE_ID, DOCUMENT_ID, expected_digest_9,
            with_agent=True, allow_network=True,
            principal=_principal_9, authz_repository=_FakeAuthzRepo(),
            conn_factory=lambda: _FakeLockConn(),
        )
    check(
        "apply_generation(): build_needed=False + a genuine safe replay (writer never reached) "
        "succeeds, replayed=True, pending_sha256 matches the real on-disk fixture, "
        "build_fact_extraction() was NEVER called",
        result_10.replayed is True and result_10.pending_sha256 == pending_sha_10,
        f"got {result_10!r}",
    )
finally:
    fee.CASES_DIR = _original_fee_cases_dir
    drr.CASES_DIR = _original_drr_cases_dir
    shutil.rmtree(_tmp_sentinel_root, ignore_errors=True)


print(f"--- test_fact_extraction_mutation_facade_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
