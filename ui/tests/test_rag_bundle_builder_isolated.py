# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION - isolated tests for
# src/ingest.py's NEW read-only manifest/snapshot functions
# (compute_source_manifest, build_bundle_snapshot) and its closed
# direct-CLI mutation entry point / consent-gated run_ingest().
#
# faiss/numpy/dotenv/openai/pypdf are NOT installed in this project's
# `vergi_ui_runtime` target environment (confirmed by direct import
# probe during implementation) - every check that would need faiss/
# numpy to actually run (create_embeddings, build_bundle_snapshot's
# FAISS-index construction) is gated behind a runtime availability
# probe and printed as an INFORMATIONAL, UNCOUNTED skip (mirrors this
# project's own established convention for `test_reconciliation_
# isolated.py`'s Windows self-loop sub-test and `test_path_
# containment_isolated.py`'s Developer-Mode-gated POSIX symlink
# sub-tests) - never silently omitted, never counted as a pass.
#
# Run: python -m ui.tests.test_rag_bundle_builder_isolated
# ============================================================

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import ingest  # noqa: E402
import manifest_validator  # noqa: E402
import corpus_policy_validator  # noqa: E402

passed = 0
failed = 0
informational_skips = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def skip_info(label, detail=""):
    global informational_skips
    informational_skips += 1
    print(f"SKIPPED (NOT counted as pass/fail) {label} - {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")


def _faiss_numpy_available():
    try:
        import faiss  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


FAISS_AVAILABLE = _faiss_numpy_available()


# ----------------------------------------------------------------
# Synthetic fixture: a temp directory shaped like data/, with a
# documents.json + two "PDF" files (content is irrelevant - neither
# compute_source_manifest() nor build_bundle_snapshot() with an
# injected pdf_page_extractor ever parses real PDF bytes).
# ----------------------------------------------------------------

def make_fixture(tmp_path: Path, *, document_count=2):
    data_dir = tmp_path / "data"
    mevzuat_dir = data_dir / "mevzuat"
    mevzuat_dir.mkdir(parents=True)
    documents = []
    for i in range(document_count):
        file_name = f"doc_{i}.pdf"
        (mevzuat_dir / file_name).write_bytes(f"fake pdf bytes {i}".encode("utf-8"))
        documents.append({
            "document_id": f"doc_{i}",
            "file_name": file_name,
            "active": True,
            "status": "yururlukte",
            "ingest": {"enabled": True, "parser": "legal_pdf", "chunk_strategy": "legal_hierarchy"},
        })
    manifest_path = data_dir / "documents.json"
    manifest_path.write_text(json.dumps({"documents": documents}, ensure_ascii=False), encoding="utf-8")
    # CORPUS POLICY FOUNDATION: compute_source_manifest() unconditionally
    # hashes ingest.CORPUS_POLICY_PATH (the 5th fixture-swappable ingest.*
    # constant, alongside DATA_DIR/MEVZUAT_DIR/MANIFEST_PATH) - content is
    # never parsed/validated by compute_source_manifest() itself (only
    # raw-byte hashed), so any bytes suffice here.
    corpus_policy_dir = data_dir / "corpus_policy"
    corpus_policy_dir.mkdir(parents=True)
    corpus_policy_path = corpus_policy_dir / "corpus_policy.json"
    corpus_policy_path.write_text(
        json.dumps({"policy_id": "test_fixture_corpus_policy_for_builder_tests"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return data_dir, mevzuat_dir, manifest_path, corpus_policy_path


def with_fixture_paths(data_dir, mevzuat_dir, manifest_path, fn, *, corpus_policy_path=None):
    original = (ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.CORPUS_POLICY_PATH)
    ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH = data_dir, mevzuat_dir, manifest_path
    if corpus_policy_path is not None:
        ingest.CORPUS_POLICY_PATH = corpus_policy_path
    try:
        return fn()
    finally:
        ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.CORPUS_POLICY_PATH = original


def fake_pdf_page_extractor(pdf_path):
    return [{"page": 1, "text": "MADDE 1- Bu kanun test amaclidir."}]


class FakeEmbeddingResponseItem:
    def __init__(self, embedding):
        self.embedding = embedding


class FakeEmbeddingResponse:
    def __init__(self, vectors):
        self.data = [FakeEmbeddingResponseItem(v) for v in vectors]


class FakeEmbeddingClient:
    def __init__(self, dimension=8):
        self.dimension = dimension
        self.calls = 0

    class _Embeddings:
        def __init__(self, outer):
            self._outer = outer

        def create(self, *, model, input):
            self._outer.calls += 1
            batch = input if isinstance(input, list) else [input]
            vectors = [[float((i + 1) * (j + 1)) for j in range(self._outer.dimension)] for i in range(len(batch))]
            return FakeEmbeddingResponse(vectors)

    @property
    def embeddings(self):
        return FakeEmbeddingClient._Embeddings(self)


# ================================================================
# import-time zero side effects
# ================================================================

def test_import_time_zero_side_effects():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'src'); import ingest; "
         "print('client' in dir(ingest)); print('OPENAI_API_KEY' in dir(ingest))"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    check("import_time: exit 0", result.returncode == 0, result.stderr)
    lines = result.stdout.strip().splitlines()
    check("import_time: no module-level 'client' attribute", lines[:1] == ["False"], result.stdout)
    check("import_time: no module-level 'OPENAI_API_KEY' attribute", lines[1:2] == ["False"], result.stdout)


# ================================================================
# compute_source_manifest()
# ================================================================

def test_compute_source_manifest_deterministic():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp))
        run = lambda: ingest.compute_source_manifest()
        first = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path)
        second = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path)
        check("source_manifest: deterministic across calls", first == second)
        check("source_manifest: 4 entries (documents.json + corpus_policy.json + 2 pdfs)", len(first) == 4, first)
        check("source_manifest: sorted by path", [e["path"] for e in first] == sorted(e["path"] for e in first))
        for entry in first:
            check(f"source_manifest: entry {entry['path']} has sha256+size_bytes", "sha256" in entry and "size_bytes" in entry)
        check(
            "source_manifest: contains the corpus-policy entry",
            any(e["path"] == "data/corpus_policy/corpus_policy.json" for e in first),
            first,
        )


def test_compute_source_manifest_excludes_inactive_document():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=1)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["documents"][0]["active"] = False
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        entries = with_fixture_paths(
            data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
            corpus_policy_path=corpus_policy_path,
        )
        check("source_manifest: inactive document excluded (documents.json + corpus_policy.json remain)", len(entries) == 2, entries)


def test_compute_source_manifest_changes_on_pdf_edit():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=1)
        run = lambda: ingest.compute_source_manifest()
        before = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path)
        (mevzuat_dir / "doc_0.pdf").write_bytes(b"different content")
        after = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path)
        check("source_manifest: hash changes when PDF content changes", before != after)


def test_compute_source_manifest_missing_corpus_policy_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=1)
        missing_path = data_dir / "corpus_policy" / "does_not_exist.json"
        expect_raises(
            FileNotFoundError,
            lambda: with_fixture_paths(
                data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
                corpus_policy_path=missing_path,
            ),
            "source_manifest: missing corpus policy file fails closed",
        )


def test_compute_source_manifest_changes_on_corpus_policy_edit():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=1)
        run = lambda: ingest.compute_source_manifest()
        before = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path)
        corpus_policy_path.write_text(json.dumps({"policy_id": "edited"}, ensure_ascii=False), encoding="utf-8")
        after = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path)
        check("source_manifest: hash changes when corpus policy content changes", before != after)
        before_entry = next(e for e in before if e["path"] == "data/corpus_policy/corpus_policy.json")
        after_entry = next(e for e in after if e["path"] == "data/corpus_policy/corpus_policy.json")
        check(
            "source_manifest: only the corpus-policy entry's hash changed (documents/pdfs unaffected)",
            before_entry["sha256"] != after_entry["sha256"],
        )


# ================================================================
# build_bundle_snapshot() - gated on faiss/numpy availability
# ================================================================

def test_build_bundle_snapshot_basic():
    if not FAISS_AVAILABLE:
        skip_info("build_bundle_snapshot_basic", "faiss/numpy not installed in this environment")
        return
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=2)
        client = FakeEmbeddingClient()

        def run():
            return ingest.build_bundle_snapshot(
                embedding_client=client, pdf_page_extractor=fake_pdf_page_extractor, build_attempt=0,
            )

        # NOTE: build_bundle_snapshot()'un kendi içindeki corpus_policy_
        # validator/manifest_validator/provision_manifest_validator
        # çağrıları ALWAYS GERÇEK, repo-committed data/*'i doğrular (bu
        # üç modülün kendi path sabitleri bu fixture tarafından
        # monkeypatch EDİLMEZ - yalnız ingest.* fixture-redirect edilir,
        # manifest_validator.validate_manifest_file()'ın bu dosyadaki
        # ÖNCEDEN VAR OLAN çağrısıyla AYNI, kasıtlı ayrım).
        snapshot = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path)
        check("build_bundle_snapshot: artifacts has exactly 3 fixed names", set(snapshot["artifacts"].keys()) == {"mevzuat.faiss", "documents.pkl", "config.json"})
        check("build_bundle_snapshot: chunk_count > 0", snapshot["chunk_count"] > 0)
        check("build_bundle_snapshot: embedding_dimension == client dimension", snapshot["embedding_dimension"] == client.dimension)
        check("build_bundle_snapshot: build_attempt echoed", snapshot["build_attempt"] == 0)
        check("build_bundle_snapshot: writes nothing under index/", not (Path(tmp) / "index").exists())
        check(
            "build_bundle_snapshot: source_manifest contains the corpus-policy entry",
            any(e["path"] == "data/corpus_policy/corpus_policy.json" for e in snapshot["source_manifest"]),
            snapshot["source_manifest"],
        )


def test_build_bundle_snapshot_deterministic_for_same_inputs():
    if not FAISS_AVAILABLE:
        skip_info("build_bundle_snapshot_deterministic", "faiss/numpy not installed in this environment")
        return
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=1)

        def run():
            return ingest.build_bundle_snapshot(
                embedding_client=FakeEmbeddingClient(), pdf_page_extractor=fake_pdf_page_extractor, build_attempt=0,
            )

        first = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path)
        second = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path)
        check(
            "build_bundle_snapshot: identical artifact bytes for identical inputs",
            first["artifacts"] == second["artifacts"],
        )


def test_create_embeddings_never_touches_real_credentials():
    if not FAISS_AVAILABLE:
        skip_info("create_embeddings_injected_client", "faiss/numpy not installed in this environment")
        return
    client = FakeEmbeddingClient()
    matrix = ingest.create_embeddings(["metin bir", "metin iki"], embedding_client=client)
    check("create_embeddings: injected client called", client.calls == 1)
    check("create_embeddings: matrix has 2 rows", matrix.shape[0] == 2)


# ================================================================
# manifest_validator.validate_corpus_policy_admissibility() - direct,
# isolated tests. Called DIRECTLY (never through build_bundle_
# snapshot()'s own always-real-repo-data validator wiring - see the
# NOTE in test_build_bundle_snapshot_basic() above) with an explicit
# `policy=` dict and (only for file-content gates) an isolated
# manifest_validator.MEVZUAT_DIR monkeypatch - own scope, independent
# of make_fixture()/with_fixture_paths() above.
# ================================================================

def with_manifest_validator_mevzuat_dir(mevzuat_dir, fn):
    original = manifest_validator.MEVZUAT_DIR
    manifest_validator.MEVZUAT_DIR = str(mevzuat_dir)
    try:
        return fn()
    finally:
        manifest_validator.MEVZUAT_DIR = original


def make_admissibility_policy(*, admission="allowed", required_fields=None, max_file_size_bytes=1024):
    return {
        "quality_gates": [
            {
                "gate_id": "max_file_size_bytes",
                "enforcement_stage": "policy_foundation",
                "outcome": "reject",
                "threshold": max_file_size_bytes,
            },
        ],
        "document_family_rules": {
            "Kanun": {
                "admission": admission,
                "tier": 1 if admission != "prohibited" else None,
                "required_provenance_fields": required_fields or [],
                "temporal_sensitive": True,
                "prerequisites": ["fixture_prereq"] if admission == "deferred" else [],
                "notes": None,
            },
        },
    }


def test_admissibility_magic_byte_gate_positive_and_negative():
    with tempfile.TemporaryDirectory() as tmp:
        mevzuat_dir = Path(tmp) / "mevzuat"
        mevzuat_dir.mkdir()
        (mevzuat_dir / "real.pdf").write_bytes(b"%PDF-1.4\nreal content")
        (mevzuat_dir / "fake.pdf").write_bytes(b"NOT A REAL PDF FILE AT ALL")
        documents = [
            {"document_id": "doc_real", "file_name": "real.pdf", "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True}},
            {"document_id": "doc_fake", "file_name": "fake.pdf", "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True}},
        ]
        policy = make_admissibility_policy()
        errors, _warnings = with_manifest_validator_mevzuat_dir(
            mevzuat_dir,
            lambda: manifest_validator.validate_corpus_policy_admissibility(documents, policy=policy),
        )
        check(
            "admissibility: real.pdf (%PDF-prefixed) produces no magic-byte error",
            not any("doc_real" in e and "magic-byte" in e for e in errors), errors,
        )
        check(
            "admissibility: fake.pdf (no %PDF prefix) rejected via magic-byte gate",
            any("doc_fake" in e and "magic-byte" in e for e in errors), errors,
        )


def test_admissibility_max_file_size_gate():
    with tempfile.TemporaryDirectory() as tmp:
        mevzuat_dir = Path(tmp) / "mevzuat"
        mevzuat_dir.mkdir()
        (mevzuat_dir / "small.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 10)
        (mevzuat_dir / "big.pdf").write_bytes(b"%PDF-1.4\n" + b"x" * 2000)
        documents = [
            {"document_id": "doc_small", "file_name": "small.pdf", "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True}},
            {"document_id": "doc_big", "file_name": "big.pdf", "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True}},
        ]
        policy = make_admissibility_policy(max_file_size_bytes=1024)
        errors, _warnings = with_manifest_validator_mevzuat_dir(
            mevzuat_dir,
            lambda: manifest_validator.validate_corpus_policy_admissibility(documents, policy=policy),
        )
        check("admissibility: small.pdf under max_file_size_bytes passes", not any("doc_small" in e for e in errors), errors)
        check(
            "admissibility: big.pdf over max_file_size_bytes (threshold=1024) rejected",
            any("doc_big" in e and "boyutu" in e for e in errors), errors,
        )


def test_admissibility_cross_document_raw_hash_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        mevzuat_dir = Path(tmp) / "mevzuat"
        mevzuat_dir.mkdir()
        same_bytes = b"%PDF-1.4\nidentical content"
        (mevzuat_dir / "a.pdf").write_bytes(same_bytes)
        (mevzuat_dir / "b.pdf").write_bytes(same_bytes)
        documents = [
            {"document_id": "doc_a", "file_name": "a.pdf", "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True}},
            {"document_id": "doc_b", "file_name": "b.pdf", "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True}},
        ]
        policy = make_admissibility_policy()
        errors, _warnings = with_manifest_validator_mevzuat_dir(
            mevzuat_dir,
            lambda: manifest_validator.validate_corpus_policy_admissibility(documents, policy=policy),
        )
        check(
            "admissibility: identical-content documents rejected via cross-document dedup gate",
            any("doc_a" in e and "doc_b" in e and "dedup" in e for e in errors), errors,
        )


def test_admissibility_required_provenance_fields():
    documents = [
        {"document_id": "doc_missing_provenance", "file_name": "x.pdf", "belge_turu": "Kanun", "active": False, "ingest": {"enabled": False}},
    ]
    policy = make_admissibility_policy(required_fields=["source_url", "kanun_no"])
    errors, _warnings = manifest_validator.validate_corpus_policy_admissibility(documents, policy=policy)
    check(
        "admissibility: missing required provenance fields both rejected",
        any("source_url" in e for e in errors) and any("kanun_no" in e for e in errors), errors,
    )


def test_admissibility_admission_prohibited_rejected():
    documents = [
        {"document_id": "doc_prohibited_family", "file_name": "x.pdf", "belge_turu": "Kanun", "active": False, "ingest": {"enabled": False}},
    ]
    policy = make_admissibility_policy(admission="prohibited")
    errors, _warnings = manifest_validator.validate_corpus_policy_admissibility(documents, policy=policy)
    check("admissibility: admission=prohibited family rejected", any("prohibited" in e for e in errors), errors)


def test_admissibility_unknown_belge_turu_rejected():
    documents = [
        {"document_id": "doc_unknown_family", "file_name": "x.pdf", "belge_turu": "Yargı Kararı", "active": False, "ingest": {"enabled": False}},
    ]
    policy = make_admissibility_policy()  # only defines a rule for "Kanun"
    errors, _warnings = manifest_validator.validate_corpus_policy_admissibility(documents, policy=policy)
    check("admissibility: belge_turu without a policy rule rejected", any("doc_unknown_family" in e for e in errors), errors)


def test_admissibility_default_policy_loads_real_committed_policy():
    real_documents = json.loads((REPO_ROOT / "data" / "documents.json").read_text(encoding="utf-8"))["documents"]
    errors, _warnings = manifest_validator.validate_corpus_policy_admissibility(real_documents)
    check(
        "admissibility: real committed documents.json passes under the real committed policy (policy=None default)",
        errors == [], errors,
    )


# ================================================================
# IngestNetworkConsentRequiredError
# ================================================================

def test_run_ingest_fails_closed_without_consent():
    expect_raises(
        ingest.IngestNetworkConsentRequiredError,
        lambda: ingest.run_ingest(),
        "run_ingest: fails closed with zero consent",
    )


# ================================================================
# Direct CLI mutation closure - REAL subprocess.
# ================================================================

def test_direct_cli_refusal_real_subprocess():
    result = subprocess.run(
        [sys.executable, str(SRC_DIR / "ingest.py")],
        cwd=str(SRC_DIR), capture_output=True, text=True, timeout=30,
    )
    check("direct_cli: exit code exactly 2", result.returncode == 2, f"got {result.returncode}")
    check("direct_cli: fixed stderr message", "DEVRE DISIDIR" in result.stderr, result.stderr)
    check("direct_cli: stdout empty", result.stdout == "", repr(result.stdout))
    check("direct_cli: no traceback", "Traceback" not in result.stderr, result.stderr)


# ================================================================
# F1 REMEDIATION (HIGH) - path-containment closure for src/ingest.py's
# three MEVZUAT_DIR/file_name raw joins the independent review found
# unprotected: compute_source_manifest(), build_bundle_snapshot()'s
# own join, and build_document_chunks() (the actual PDF-content read -
# shared by BOTH build_bundle_snapshot() AND the legacy run_ingest()
# path, so a direct test of it proves both call sites are closed).
# Every test below proves REJECTION happens - via
# src/path_containment.py's already-proven-correct primitive - BEFORE
# any .exists()/open()/.stat()/hash touches a file outside
# MEVZUAT_DIR, using REAL junctions/absolute paths (never mocked path
# objects).
# ================================================================

def make_junction(link_path: Path, target_path: Path) -> None:
    """Windows-native directory reparse point - `mklink /J` needs
    NEITHER elevation NOR Developer Mode on a normal Windows account
    (unlike a POSIX-style Windows symlink), matching the pattern
    already established and proven in
    ui/tests/test_path_containment_windows.py. A failure here is a
    genuine, counted test FAILURE below - never silently downgraded to
    a skip."""
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mklink /J failed (rc={result.returncode}): {result.stdout!r} {result.stderr!r}")


def _malicious_document(file_name, document_id="doc_containment_probe"):
    return {
        "document_id": document_id,
        "file_name": file_name,
        "active": True,
        "status": "yururlukte",
        "ingest": {"enabled": True, "parser": "legal_pdf", "chunk_strategy": "legal_hierarchy"},
    }


def _write_single_document_manifest(manifest_path, document):
    manifest_path.write_text(json.dumps({"documents": [document]}, ensure_ascii=False), encoding="utf-8")


def with_recorded_hash_calls(run_fn):
    """Wraps ingest.calculate_file_hash with a call-recording proxy for
    the duration of run_fn() - independent, mechanism-level proof (not
    an assumption) of exactly which real filesystem paths were ever
    hashed. Restored unconditionally."""
    original = ingest.calculate_file_hash
    calls = []

    def recording(path):
        calls.append(str(path))
        return original(path)

    ingest.calculate_file_hash = recording
    try:
        run_fn()
    finally:
        ingest.calculate_file_hash = original
    return calls


def test_containment_traversal_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=0)
        outside_canary = data_dir / "traversal_canary.pdf"
        outside_canary.write_bytes(b"TRAVERSAL-OUTSIDE-CANARY-CONTENT")
        _write_single_document_manifest(
            manifest_path, _malicious_document("../traversal_canary.pdf", "doc_traversal"),
        )
        # calculate_file_hash() IS legitimately called twice before the
        # per-document loop even starts (MANIFEST_PATH, then
        # CORPUS_POLICY_PATH, per compute_source_manifest()'s own fixed
        # entries list) - the meaningful assertion is that the CANARY's
        # own path specifically never appears among the recorded calls,
        # not that the list is empty.
        calls = with_recorded_hash_calls(lambda: expect_raises(
            FileNotFoundError,
            lambda: with_fixture_paths(
                data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
                corpus_policy_path=corpus_policy_path,
            ),
            "containment: '../' traversal file_name rejected by compute_source_manifest()",
        ))
        check(
            "containment: traversal canary content was never hashed (calculate_file_hash was never "
            "called with its path)",
            str(outside_canary) not in calls and str(outside_canary.resolve()) not in calls,
            calls,
        )


def test_containment_absolute_posix_style_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=0)
        # On Windows a single leading "/" re-anchors to the CURRENT
        # DRIVE's root (e.g. "C:/etc/passwd") rather than escaping the
        # drive entirely - there is deliberately no real file planted
        # there (an unprivileged test must never assume write access
        # to a filesystem root); this proves REJECTION (fail-closed,
        # via a resolve() that cannot succeed) without needing one.
        _write_single_document_manifest(
            manifest_path, _malicious_document("/etc/passwd_does_not_exist_here", "doc_abs_posix"),
        )
        expect_raises(
            FileNotFoundError,
            lambda: with_fixture_paths(
                data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
                corpus_policy_path=corpus_policy_path,
            ),
            "containment: absolute POSIX-style ('/...') file_name rejected by compute_source_manifest()",
        )


def test_containment_absolute_windows_drive_rejected():
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp_outside:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=0)
        outside_canary = Path(tmp_outside) / "abs_drive_canary.pdf"
        outside_canary.write_bytes(b"ABSOLUTE-DRIVE-QUALIFIED-OUTSIDE-CANARY-CONTENT")
        # THE core Diagnostic-E2.1-class escape: MEVZUAT_DIR / file_name
        # with an absolute, drive-qualified file_name silently
        # re-anchors to that absolute path, discarding MEVZUAT_DIR
        # entirely - this canary genuinely exists outside the fixture
        # root, so a successful (unfixed) read would actually succeed.
        _write_single_document_manifest(
            manifest_path, _malicious_document(str(outside_canary), "doc_abs_drive"),
        )
        calls = with_recorded_hash_calls(lambda: expect_raises(
            FileNotFoundError,
            lambda: with_fixture_paths(
                data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
                corpus_policy_path=corpus_policy_path,
            ),
            "containment: absolute Windows drive-qualified file_name (real, existing, outside-root "
            "canary) rejected by compute_source_manifest()",
        ))
        check(
            "containment: absolute-drive canary was NEVER hashed (calculate_file_hash was never "
            "called with its path)",
            str(outside_canary) not in calls and str(outside_canary.resolve()) not in calls, calls,
        )


def test_containment_unc_style_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=0)
        unc_style_name = "\\\\nonexistent-host-vergi-ai-test\\share\\file.pdf"
        _write_single_document_manifest(
            manifest_path, _malicious_document(unc_style_name, "doc_unc"),
        )
        expect_raises(
            FileNotFoundError,
            lambda: with_fixture_paths(
                data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
                corpus_policy_path=corpus_policy_path,
            ),
            "containment: UNC-shaped file_name rejected by compute_source_manifest()",
        )


def test_containment_windows_absolute_path_posix_semantics_note():
    # Item #16 of this remediation's own test matrix: this environment
    # IS Windows (sys.platform == 'win32'), so the exact vulnerability
    # class (a Windows-absolute file_name silently re-anchoring) is
    # already proven with REAL content by
    # test_containment_absolute_windows_drive_rejected() above.
    # Structural, platform-independent note on the inverse concern
    # (would a Windows-shaped absolute string be misread as an
    # ordinary, safely-contained RELATIVE segment on a POSIX host?):
    # POSIX has no concept of a drive letter or '\\' separator, so a
    # string like "C:\\Windows\\win.ini" parses under PurePosixPath as
    # a single, ordinary (non-anchored) relative component - it cannot
    # re-anchor a join on that platform, so on POSIX the fix's
    # existing containment check is not even needed for THIS exact
    # string shape (the file legitimately would not exist under
    # MEVZUAT_DIR and fails closed on existence alone).
    windows_style = "C:\\Windows\\win.ini"
    posix_view = PurePosixPath(windows_style)
    check(
        "containment: a Windows-absolute-shaped file_name is NOT anchored under POSIX path semantics "
        "(informational cross-platform note, not itself an escape)",
        not posix_view.is_absolute(),
        posix_view,
    )


def test_containment_escaping_junction_rejected():
    if sys.platform != "win32":
        skip_info(
            "containment_escaping_junction", f"NTFS junction test is Windows-only (sys.platform={sys.platform!r})",
        )
        return
    tmp_root = Path(tempfile.mkdtemp(prefix="corpus_policy_f1_junction_"))
    tmp_outside = Path(tempfile.mkdtemp(prefix="corpus_policy_f1_junction_outside_"))
    try:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(tmp_root, document_count=0)
        outside_dir = tmp_outside / "escape_target"
        outside_dir.mkdir()
        canary = outside_dir / "junction_canary.pdf"
        canary.write_bytes(b"JUNCTION-ESCAPE-OUTSIDE-CANARY-CONTENT")
        junction_link = mevzuat_dir / "escape_junction"
        try:
            make_junction(junction_link, outside_dir)
        except Exception as error:
            check(
                "containment: mklink /J junction creation for escape test succeeded "
                "(no elevation/Developer Mode required on a normal Windows account)",
                False, f"{error!r} - THIS IS A REAL FAILURE, not a reason to skip",
            )
            return
        _write_single_document_manifest(
            manifest_path,
            _malicious_document("escape_junction/junction_canary.pdf", "doc_junction_escape"),
        )
        calls = with_recorded_hash_calls(lambda: expect_raises(
            FileNotFoundError,
            lambda: with_fixture_paths(
                data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
                corpus_policy_path=corpus_policy_path,
            ),
            "containment: real NTFS junction (physically inside MEVZUAT_DIR, pointing OUTSIDE it) "
            "rejected by compute_source_manifest()",
        ))
        check(
            "containment: junction-escape canary content was never hashed",
            str(canary) not in calls and str(canary.resolve()) not in calls, calls,
        )
    finally:
        try:
            os.rmdir(mevzuat_dir / "escape_junction")
        except OSError:
            pass
        shutil.rmtree(tmp_root, ignore_errors=True)
        shutil.rmtree(tmp_outside, ignore_errors=True)


def test_containment_broken_junction_rejected():
    if sys.platform != "win32":
        skip_info(
            "containment_broken_junction", f"NTFS junction test is Windows-only (sys.platform={sys.platform!r})",
        )
        return
    tmp_root = Path(tempfile.mkdtemp(prefix="corpus_policy_f1_broken_junction_"))
    tmp_outside = Path(tempfile.mkdtemp(prefix="corpus_policy_f1_broken_junction_outside_"))
    try:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(tmp_root, document_count=0)
        outside_target = tmp_outside / "broken_target"
        outside_target.mkdir()
        junction_link = mevzuat_dir / "broken_escape_junction"
        try:
            make_junction(junction_link, outside_target)
        except Exception as error:
            check(
                "containment: mklink /J junction creation for broken-link test succeeded",
                False, f"{error!r} - THIS IS A REAL FAILURE, not a reason to skip",
            )
            return
        shutil.rmtree(outside_target)  # break it: target gone, reparse-point entry itself remains
        broken_candidate = junction_link / "ghost.pdf"
        check(
            "containment: broken-junction precondition - os.path.lexists()==True (reparse-point "
            "entry itself still on disk)",
            os.path.lexists(junction_link) is True,
        )
        check(
            "containment: broken-junction precondition - Path.exists()==False (target cannot be "
            "resolved) - the OLD .exists()-only check this remediation removed would have silently "
            "treated this as 'not yet created'",
            junction_link.exists() is False,
        )
        _write_single_document_manifest(
            manifest_path,
            _malicious_document("broken_escape_junction/ghost.pdf", "doc_broken_junction"),
        )
        expect_raises(
            FileNotFoundError,
            lambda: with_fixture_paths(
                data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
                corpus_policy_path=corpus_policy_path,
            ),
            "containment: a REAL, BROKEN NTFS junction is rejected fail-closed - never silently "
            "treated as 'nothing here' - by compute_source_manifest()",
        )
    finally:
        try:
            os.rmdir(mevzuat_dir / "broken_escape_junction")
        except OSError:
            pass
        shutil.rmtree(tmp_root, ignore_errors=True)
        shutil.rmtree(tmp_outside, ignore_errors=True)


def test_containment_looping_link_rejected_or_platform_skip():
    tmp_root = Path(tempfile.mkdtemp(prefix="corpus_policy_f1_loop_"))
    try:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(tmp_root, document_count=0)
        loop_path = mevzuat_dir / "self_loop.pdf"
        try:
            os.symlink(str(loop_path), str(loop_path))
        except (OSError, NotImplementedError) as error:
            skip_info(
                "containment_looping_link",
                f"this platform/account cannot create a genuinely self-referential symlink ({error!r}) "
                "- POSIX-only capability (see src/path_containment.py's own ELOOP handling); never "
                "claimed as a pass",
            )
            return
        try:
            _write_single_document_manifest(
                manifest_path, _malicious_document("self_loop.pdf", "doc_self_loop"),
            )
            expect_raises(
                FileNotFoundError,
                lambda: with_fixture_paths(
                    data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
                    corpus_policy_path=corpus_policy_path,
                ),
                "containment: a genuinely looping (ELOOP) self-referential symlink is rejected "
                "fail-closed by compute_source_manifest()",
            )
        finally:
            try:
                os.remove(loop_path)
            except OSError:
                pass
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_containment_safe_internal_alias_preserves_logical_name():
    if sys.platform != "win32":
        skip_info(
            "containment_safe_internal_alias", f"NTFS junction test is Windows-only (sys.platform={sys.platform!r})",
        )
        return
    tmp_root = Path(tempfile.mkdtemp(prefix="corpus_policy_f1_safe_alias_"))
    try:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(tmp_root, document_count=0)
        real_subdir = mevzuat_dir / "real_subdir"
        real_subdir.mkdir()
        (real_subdir / "actual.pdf").write_bytes(b"SAFE-INTERNAL-ALIAS-CONTENT")
        alias_dir = mevzuat_dir / "alias_dir"
        try:
            make_junction(alias_dir, real_subdir)
        except Exception as error:
            check(
                "containment: mklink /J junction creation for safe-internal-alias test succeeded",
                False, f"{error!r} - THIS IS A REAL FAILURE, not a reason to skip",
            )
            return
        try:
            logical_file_name = "alias_dir/actual.pdf"
            _write_single_document_manifest(
                manifest_path, _malicious_document(logical_file_name, "doc_safe_alias"),
            )
            entries = with_fixture_paths(
                data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest(),
                corpus_policy_path=corpus_policy_path,
            )
            matching = [e for e in entries if e["path"] == "data/mevzuat/alias_dir/actual.pdf"]
            check(
                "containment: a SAFE root-internal junction (target still inside MEVZUAT_DIR) is "
                "accepted, not rejected",
                len(matching) == 1, entries,
            )
            check(
                "containment: the accepted entry's logical path is the ALIAS's own name "
                "('alias_dir/actual.pdf'), never the resolved real target name "
                "('real_subdir/actual.pdf') - the resolved-alias-name-leak this remediation forbids",
                not any(e["path"] == "data/mevzuat/real_subdir/actual.pdf" for e in entries), entries,
            )
        finally:
            try:
                os.rmdir(alias_dir)
            except OSError:
                pass
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_containment_preview_build_rejects_before_anything_else():
    from ui.services import global_authz as ga
    from ui.services import rag_bundle_mutation_facade as facade
    from ui.services.authz import Principal

    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp_outside:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=0)
        outside_canary = Path(tmp_outside) / "preview_build_canary.pdf"
        outside_canary.write_bytes(b"PREVIEW-BUILD-PUBLIC-API-OUTSIDE-CANARY-CONTENT")
        _write_single_document_manifest(
            manifest_path, _malicious_document(str(outside_canary), "doc_preview_escape"),
        )

        principal = Principal(user_id=5, session_id=0, role_version_at_issue=1)
        repo = ga.InMemoryGlobalResourceAuthzRepository()
        repo.sessions[5] = ga._authz.SessionRecord(user_id=5, current_authz_version=1, disabled=False)
        repo.grants.add((5, "rag_index", "build"))

        def run():
            return facade.preview_build(build_attempt=0, principal=principal, authz_repository=repo)

        expect_raises(
            FileNotFoundError,
            lambda: with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path),
            "containment: facade.preview_build() - the real public API the independent review found "
            "reachable with NO validator in front of it - now rejects an escaping file_name via the "
            "SAME compute_source_manifest() fix, before returning any digest (zero DB/journal/lock "
            "involved in preview_build() at all - this is a pure pre-lock read)",
        )


def test_containment_build_document_chunks_rejects_before_pdf_extraction():
    # This is the JOIN SITE SHARED by build_bundle_snapshot() (coordinated
    # path, via its own call at the end of its per-document loop) AND the
    # legacy run_ingest() path (both call build_document_chunks() for the
    # actual PDF read) - a direct test here proves BOTH callers are closed
    # by this ONE fix, matching this remediation's own scope note #3
    # ("legacy run_ingest/build yolundaki aynı sınıf erişim").
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp_outside:
        outside_canary = Path(tmp_outside) / "build_document_chunks_canary.pdf"
        outside_canary.write_bytes(b"%PDF-1.4\nBUILD-DOCUMENT-CHUNKS-OUTSIDE-CANARY")

        extractor_calls = []

        def counting_extractor(pdf_path):
            extractor_calls.append(str(pdf_path))
            return fake_pdf_page_extractor(pdf_path)

        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=0)
        manifest_document = _malicious_document(str(outside_canary), "doc_bdc_escape")

        def run():
            return ingest.build_document_chunks(
                manifest_document=manifest_document, file_hash="irrelevant", pdf_page_extractor=counting_extractor,
            )

        expect_raises(
            FileNotFoundError,
            lambda: with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path),
            "containment: build_document_chunks() (shared by build_bundle_snapshot AND legacy "
            "run_ingest) rejects an escaping file_name before ever calling pdf_page_extractor",
        )
        check(
            "containment: build_document_chunks() never invoked pdf_page_extractor on the escaping path "
            "(zero PDF content extraction attempted)",
            len(extractor_calls) == 0, extractor_calls,
        )


def test_containment_build_bundle_snapshot_rejects_own_join_site():
    if not FAISS_AVAILABLE:
        skip_info(
            "containment_build_bundle_snapshot_own_join", "faiss/numpy not installed in this environment",
        )
        return
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp_outside:
        data_dir, mevzuat_dir, manifest_path, corpus_policy_path = make_fixture(Path(tmp), document_count=0)
        outside_canary = Path(tmp_outside) / "bbs_own_join_canary.pdf"
        outside_canary.write_bytes(b"%PDF-1.4\nBUILD-BUNDLE-SNAPSHOT-OWN-JOIN-OUTSIDE-CANARY")
        _write_single_document_manifest(
            manifest_path, _malicious_document(str(outside_canary), "doc_bbs_own_join_escape"),
        )

        chunk_calls = []
        original_build_document_chunks = ingest.build_document_chunks

        def counting_build_document_chunks(*args, **kwargs):
            chunk_calls.append(1)
            return original_build_document_chunks(*args, **kwargs)

        ingest.build_document_chunks = counting_build_document_chunks
        try:
            def run():
                # NOTE (same decoupled-constants contract documented in
                # test_build_bundle_snapshot_basic() above): the three
                # gates build_bundle_snapshot() calls first ALWAYS
                # validate the REAL, repo-committed data/* (they are not
                # fixture-redirected), so they pass cleanly here and
                # execution genuinely reaches this function's OWN
                # MEVZUAT_DIR/file_name join against the FIXTURE manifest
                # - proving that specific join site's fix, isolated from
                # build_document_chunks()'s own (separately tested above).
                return ingest.build_bundle_snapshot(
                    embedding_client=FakeEmbeddingClient(), pdf_page_extractor=fake_pdf_page_extractor,
                )
            expect_raises(
                FileNotFoundError,
                lambda: with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run, corpus_policy_path=corpus_policy_path),
                "containment: build_bundle_snapshot()'s OWN MEVZUAT_DIR/file_name join (its file_hash "
                "computation, distinct from build_document_chunks()'s own internal join) rejects an "
                "escaping file_name",
            )
        finally:
            ingest.build_document_chunks = original_build_document_chunks
        check(
            "containment: build_bundle_snapshot()'s own-join rejection happened BEFORE "
            "build_document_chunks() (and therefore before any PDF extraction/embedding) was ever "
            "reached",
            len(chunk_calls) == 0, chunk_calls,
        )


# ================================================================
# F2 REMEDIATION (MEDIUM) - admission="deferred" is now a fail-closed
# ERROR, exactly like admission="prohibited" was already - matching
# the user-approved binding decision matrix: allowed -> passes;
# deferred -> fail-closed ERROR citing prerequisites (even with an
# otherwise-empty required_provenance_fields list); prohibited ->
# unchanged fail-closed ERROR; anything else (missing/unrecognized) ->
# fail-closed ERROR, never silently allowed.
# ================================================================

def test_admissibility_admission_deferred_rejected_each_real_family():
    real_policy = corpus_policy_validator.load_policy()
    family_rules = real_policy["document_family_rules"]
    deferred_families = sorted(
        belge_turu for belge_turu, rule in family_rules.items() if rule.get("admission") == "deferred"
    )
    check(
        "admissibility: real committed policy has exactly 3 deferred families (mechanically counted, "
        "not assumed)",
        len(deferred_families) == 3, deferred_families,
    )
    for index, belge_turu in enumerate(deferred_families):
        document = {
            "document_id": f"doc_deferred_probe_{index}",
            "file_name": "irrelevant_for_this_check.pdf",
            "belge_turu": belge_turu,
            "active": False,
            "ingest": {"enabled": False},
        }
        errors, _warnings = manifest_validator.validate_corpus_policy_admissibility([document], policy=real_policy)
        check(
            f"admissibility: real deferred family {belge_turu!r} individually rejected with an "
            "admission=deferred error",
            any("admission=deferred" in e for e in errors), errors,
        )


def test_admissibility_admission_deferred_with_empty_provenance_still_rejected():
    real_policy = corpus_policy_validator.load_policy()
    ozelge_rule = real_policy["document_family_rules"]["Özelge"]
    check(
        "admissibility: real committed policy's 'Özelge' family truly has zero "
        "required_provenance_fields (precondition for this test - proves rejection is NOT merely "
        "a provenance-field side effect)",
        ozelge_rule.get("required_provenance_fields") == [], ozelge_rule,
    )
    document = {
        "document_id": "doc_ozelge_empty_provenance_probe",
        "file_name": "irrelevant_for_this_check.pdf",
        "belge_turu": "Özelge",
        "active": False,
        "ingest": {"enabled": False},
    }
    errors, _warnings = manifest_validator.validate_corpus_policy_admissibility([document], policy=real_policy)
    check(
        "admissibility: 'Özelge' (admission=deferred, zero required provenance fields) is still "
        "rejected - an empty required_provenance_fields list never silently satisfies admission",
        any("admission=deferred" in e for e in errors), errors,
    )


def test_admissibility_deferred_error_message_carries_context():
    policy = make_admissibility_policy(admission="deferred")
    document = {
        "document_id": "doc_context_probe", "file_name": "x.pdf", "belge_turu": "Kanun",
        "active": False, "ingest": {"enabled": False},
    }
    errors, _warnings = manifest_validator.validate_corpus_policy_admissibility([document], policy=policy)
    deferred_errors = [e for e in errors if "admission=deferred" in e]
    check("admissibility: deferred error message references document_id", any("doc_context_probe" in e for e in deferred_errors), deferred_errors)
    check("admissibility: deferred error message references belge_turu", any("Kanun" in e for e in deferred_errors), deferred_errors)
    check("admissibility: deferred error message references prerequisites", any("prerequisites" in e for e in deferred_errors), deferred_errors)
    check(
        "admissibility: deferred error message lists the family's own actual prerequisite value",
        any("fixture_prereq" in e for e in deferred_errors), deferred_errors,
    )


def test_admissibility_unknown_admission_value_not_silently_allowed():
    policy = make_admissibility_policy(admission="mystery_value_not_in_vocabulary")
    document = {
        "document_id": "doc_unknown_admission", "file_name": "x.pdf", "belge_turu": "Kanun",
        "active": False, "ingest": {"enabled": False},
    }
    errors, _warnings = manifest_validator.validate_corpus_policy_admissibility([document], policy=policy)
    check(
        "admissibility: an unrecognized admission value is fail-closed rejected, never silently "
        "treated as allowed (reachable only when this function is called standalone with a "
        "hand-crafted policy dict that bypasses corpus_policy_validator's own closed-vocabulary check)",
        any("doc_unknown_admission" in e and "tanınmıyor" in e for e in errors), errors,
    )


def test_admissibility_deferred_document_rejected_before_extraction_embed_network():
    with tempfile.TemporaryDirectory() as tmp:
        mevzuat_dir = Path(tmp) / "mevzuat"
        mevzuat_dir.mkdir()
        (mevzuat_dir / "sirkuler_test.pdf").write_bytes(b"%PDF-1.4\ntest content")
        manifest_path = Path(tmp) / "documents.json"
        # A genuinely schema-VALID document (all 14 required documents.
        # schema.json fields present) for belge_turu="Sirküler" (a real
        # admission=deferred family) - proven, via an isolated probe
        # during this remediation, to pass every OTHER
        # validate_manifest_file() check cleanly, so the raise below is
        # attributable ONLY to the new admission=deferred gate, not
        # some unrelated schema/date/relation failure.
        document = {
            "document_id": "test_deferred_sirkuler_gate",
            "file_name": "sirkuler_test.pdf",
            "active": True,
            "belge_turu": "Sirküler",
            "title": "Test Sirkuler",
            "short_title": "Test Sirkuler",
            "official_source": True,
            "source_url": "https://example.gov.tr/test",
            "status": "active",
            "version": "1",
            "jurisdiction": "TR",
            "language": "tr",
            "tags": [],
            "relations": [],
            "ingest": {"enabled": True, "parser": "legal_pdf", "chunk_strategy": "legal_hierarchy", "ocr_required": False},
        }
        manifest_path.write_text(json.dumps({"schema_version": 1, "documents": [document]}, ensure_ascii=False), encoding="utf-8")

        chunk_calls = []
        embed_calls = []
        original_chunks = ingest.build_document_chunks
        original_embed = ingest.create_embeddings

        def counting_chunks(*args, **kwargs):
            chunk_calls.append(1)
            return original_chunks(*args, **kwargs)

        def counting_embed(*args, **kwargs):
            embed_calls.append(1)
            return original_embed(*args, **kwargs)

        ingest.build_document_chunks = counting_chunks
        ingest.create_embeddings = counting_embed

        original_manifest_path = manifest_validator.MANIFEST_PATH
        original_mevzuat_dir = manifest_validator.MEVZUAT_DIR
        manifest_validator.MANIFEST_PATH = str(manifest_path)
        manifest_validator.MEVZUAT_DIR = str(mevzuat_dir)
        try:
            expect_raises(
                ValueError,
                lambda: manifest_validator.validate_manifest_file(raise_on_error=True),
                "admissibility: a deferred-family document (Sirküler) is rejected by "
                "validate_manifest_file() - gate #2 of build_bundle_snapshot()'s three-gate sequence, "
                "strictly before its own chunk/embed loop",
            )
        finally:
            manifest_validator.MANIFEST_PATH = original_manifest_path
            manifest_validator.MEVZUAT_DIR = original_mevzuat_dir
            ingest.build_document_chunks = original_chunks
            ingest.create_embeddings = original_embed
        check(
            "admissibility: deferred-family rejection never reached build_document_chunks "
            "(zero PDF extraction attempted)",
            len(chunk_calls) == 0, chunk_calls,
        )
        check(
            "admissibility: deferred-family rejection never reached create_embeddings "
            "(zero network/embedding attempted)",
            len(embed_calls) == 0, embed_calls,
        )
        check(
            "admissibility: deferred rejection produced no index/ directory at all (no staging, no "
            "bundle, no audit)",
            not (Path(tmp) / "index").exists(),
        )


# ================================================================
# RAG CORPUS PREREQUISITE DOCUMENTS-SCHEMA PATCH (P2)
#
# Additive tests for the ten new optional/nullable
# data/documents.schema.json properties (daire, esas_no, karar_no,
# temyiz_kesinlesme_durumu, anonymization_applied, text_basis,
# raw_byte_sha256, acquisition_timestamp, acquisition_channel,
# acquiring_actor_ref) and src/manifest_validator.py's new
# Yargı Kararı / Özelge per-type rules + raw_byte_sha256
# declared-vs-computed integrity gate. No existing assertion above
# this block is weakened or removed.
# ================================================================

REAL_SCHEMA_PATH = REPO_ROOT / "data" / "documents.schema.json"

_P2_NEW_FIELDS = [
    "daire", "esas_no", "karar_no", "temyiz_kesinlesme_durumu",
    "anonymization_applied", "text_basis", "raw_byte_sha256",
    "acquisition_timestamp", "acquisition_channel", "acquiring_actor_ref",
]


def _load_real_schema():
    return json.loads(REAL_SCHEMA_PATH.read_text(encoding="utf-8"))


def _p2_base_document(**overrides):
    document = {
        "document_id": "p2_probe_doc",
        "file_name": "p2_probe.pdf",
        "active": True,
        "belge_turu": "Yargı Kararı",
        "title": "P2 probe",
        "short_title": "P2 probe",
        "official_source": True,
        "status": "active",
        "version": "1",
        "jurisdiction": "TR",
        "language": "tr",
        "tags": [],
        "relations": [],
        "ingest": {
            "enabled": True,
            "parser": "judgment_pdf",
            "chunk_strategy": "judgment_sections",
            "ocr_required": False,
        },
    }
    document.update(overrides)
    return document


def _p2_validate_schema_only(document):
    schema = _load_real_schema()
    manifest = {"schema_version": 1, "documents": [document]}
    return manifest_validator.validate_schema(manifest, schema)


def test_p2_schema_absent_null_value_for_new_fields():
    # absent: none of the 10 fields present at all
    absent_doc = _p2_base_document()
    for field in _P2_NEW_FIELDS:
        check(f"p2 schema: {field} absent from base fixture", field not in absent_doc)
    errors = _p2_validate_schema_only(absent_doc)
    check(
        "p2 schema: record with all 10 new fields absent is schema-valid",
        errors == [], errors,
    )

    # explicit null on all 10 fields
    null_doc = _p2_base_document(**{field: None for field in _P2_NEW_FIELDS})
    errors = _p2_validate_schema_only(null_doc)
    check(
        "p2 schema: record with all 10 new fields explicitly null is schema-valid",
        errors == [], errors,
    )

    # real, valid values on all 10 fields
    value_doc = _p2_base_document(
        daire="Dördüncü Daire",
        esas_no="2020/1",
        karar_no="2021/1",
        temyiz_kesinlesme_durumu="kesinlesmis",
        anonymization_applied=True,
        text_basis="editorially_consolidated_current",
        raw_byte_sha256="a" * 64,
        acquisition_timestamp="2026-09-14T12:00:00Z",
        acquisition_channel="resmi_gazete",
        acquiring_actor_ref="curator_1",
    )
    errors = _p2_validate_schema_only(value_doc)
    check(
        "p2 schema: record with all 10 new fields populated with valid values is schema-valid",
        errors == [], errors,
    )


def test_p2_schema_enum_rejection():
    # temyiz_kesinlesme_durumu deliberately has NO "bilinmiyor"/"unknown"
    # sentinel (null already carries that meaning) - pins that design
    # decision directly.
    cases = [
        ("temyiz_kesinlesme_durumu", "bilinmiyor"),
        ("text_basis", "some_invalid_basis"),
        # acquisition_channel deliberately has NO "elle_giris"/"diger"
        # catch-all member - unknown channel must be null, not a
        # falsely-specific "other" string.
        ("acquisition_channel", "elle_giris"),
    ]
    for field, bad_value in cases:
        doc = _p2_base_document(**{field: bad_value})
        errors = _p2_validate_schema_only(doc)
        check(
            f"p2 schema: {field}={bad_value!r} (out of closed enum) rejected",
            errors != [], errors,
        )


def test_p2_schema_pattern_rejection():
    bad_hashes = ["A" * 64, "abc123", "g" * 64, "a" * 63]
    for bad_hash in bad_hashes:
        doc = _p2_base_document(raw_byte_sha256=bad_hash)
        errors = _p2_validate_schema_only(doc)
        check(
            f"p2 schema: raw_byte_sha256={bad_hash!r} rejected by pattern",
            errors != [], errors,
        )

    good_hash_doc = _p2_base_document(raw_byte_sha256="a" * 64)
    errors = _p2_validate_schema_only(good_hash_doc)
    check(
        "p2 schema: raw_byte_sha256 (64 lowercase hex) accepted by pattern",
        errors == [], errors,
    )

    # this proves the field is pattern-based (jsonschema `format` is
    # inert in this file - no FormatChecker is passed) rather than
    # format-based: an offset-bearing / date-only / malformed value
    # would silently PASS under a `format`-only implementation.
    bad_timestamps = [
        "2026-09-14",
        "2026-09-14T12:00:00+03:00",
        "2026-09-14 12:00:00Z",
        "not-a-timestamp",
    ]
    for bad_ts in bad_timestamps:
        doc = _p2_base_document(acquisition_timestamp=bad_ts)
        errors = _p2_validate_schema_only(doc)
        check(
            f"p2 schema: acquisition_timestamp={bad_ts!r} rejected by pattern",
            errors != [], errors,
        )

    good_ts_doc = _p2_base_document(acquisition_timestamp="2026-09-14T12:00:00.123Z")
    errors = _p2_validate_schema_only(good_ts_doc)
    check(
        "p2 schema: acquisition_timestamp (UTC, Z-terminated) accepted by pattern",
        errors == [], errors,
    )


def test_p2_schema_additional_properties_still_false():
    doc = _p2_base_document(this_field_does_not_exist_anywhere="x")
    errors = _p2_validate_schema_only(doc)
    check(
        "p2 schema: a genuinely unknown property is still rejected "
        "(additionalProperties:false was not loosened by this patch)",
        errors != [], errors,
    )


def test_p2_per_type_yargi_karari_required_fields():
    active_ingest = {
        "enabled": True, "parser": "judgment_pdf",
        "chunk_strategy": "judgment_sections", "ocr_required": False,
    }
    complete = {
        "daire": "Dördüncü Daire", "esas_no": "2020/1",
        "karar_no": "2021/1", "karar_tarihi": "2021-01-01",
    }
    for missing in ("daire", "esas_no", "karar_no", "karar_tarihi"):
        fields = dict(complete)
        fields.pop(missing)
        doc = _p2_base_document(
            belge_turu="Yargı Kararı", active=True, ingest=dict(active_ingest),
            **fields,
        )
        errors, _warnings = manifest_validator.validate_document_type_logic([doc])
        check(
            f"p2 per-type: active+ingest Yargı Kararı missing {missing} -> "
            f"error naming {missing}",
            any(missing in e and "p2_probe_doc" in e for e in errors), errors,
        )

    complete_doc = _p2_base_document(
        belge_turu="Yargı Kararı", active=True, ingest=dict(active_ingest),
        **complete,
    )
    errors, _warnings = manifest_validator.validate_document_type_logic([complete_doc])
    check(
        "p2 per-type: active+ingest Yargı Kararı with all 4 fields present "
        "-> zero type errors",
        errors == [], errors,
    )

    inactive_doc = _p2_base_document(
        belge_turu="Yargı Kararı", active=False, ingest=dict(active_ingest),
    )
    errors, _warnings = manifest_validator.validate_document_type_logic([inactive_doc])
    check(
        "p2 per-type: inactive Yargı Kararı missing all 4 fields -> inert "
        "(zero type errors)",
        errors == [], errors,
    )

    ingest_disabled_doc = _p2_base_document(
        belge_turu="Yargı Kararı", active=True,
        ingest={**active_ingest, "enabled": False},
    )
    errors, _warnings = manifest_validator.validate_document_type_logic([ingest_disabled_doc])
    check(
        "p2 per-type: ingest.enabled=false Yargı Kararı missing all 4 fields "
        "-> inert (zero type errors)",
        errors == [], errors,
    )


def test_p2_per_type_ozelge_anonymization_identity_check():
    active_ingest = {
        "enabled": True, "parser": "legal_pdf",
        "chunk_strategy": "legal_hierarchy", "ocr_required": False,
    }
    for value in (False, None, 1, "true", "yes"):
        doc = _p2_base_document(
            belge_turu="Özelge", active=True, ingest=dict(active_ingest),
            anonymization_applied=value,
        )
        errors, _warnings = manifest_validator.validate_document_type_logic([doc])
        check(
            f"p2 per-type: active+ingest Özelge with anonymization_applied="
            f"{value!r} rejected (identity check, not truthiness/presence)",
            any("anonymization_applied" in e for e in errors), errors,
        )

    absent_doc = _p2_base_document(
        belge_turu="Özelge", active=True, ingest=dict(active_ingest),
    )
    errors, _warnings = manifest_validator.validate_document_type_logic([absent_doc])
    check(
        "p2 per-type: active+ingest Özelge with anonymization_applied absent "
        "rejected",
        any("anonymization_applied" in e for e in errors), errors,
    )

    accepted_doc = _p2_base_document(
        belge_turu="Özelge", active=True, ingest=dict(active_ingest),
        anonymization_applied=True,
    )
    errors, _warnings = manifest_validator.validate_document_type_logic([accepted_doc])
    check(
        "p2 per-type: active+ingest Özelge with anonymization_applied=True "
        "passes (zero type errors)",
        errors == [], errors,
    )


def test_p2_sirkuler_unaffected_by_new_per_type_rules():
    doc = _p2_base_document(
        belge_turu="Sirküler", active=True,
        ingest={
            "enabled": True, "parser": "legal_pdf",
            "chunk_strategy": "legal_hierarchy", "ocr_required": False,
        },
    )
    errors, _warnings = manifest_validator.validate_document_type_logic([doc])
    check(
        "p2 per-type: active+ingest Sirküler produces zero "
        "validate_document_type_logic errors (no new per-type branch was "
        "added for Sirküler - preserves the existing deferred-gate-only "
        "attribution claim)",
        errors == [], errors,
    )


def test_p2_raw_byte_sha256_gate_match_mismatch_null():
    with tempfile.TemporaryDirectory() as tmp:
        mevzuat_dir = Path(tmp) / "mevzuat"
        mevzuat_dir.mkdir()
        content = b"%PDF-1.4\nraw byte sha256 gate probe content"
        (mevzuat_dir / "probe.pdf").write_bytes(content)
        real_hash = hashlib.sha256(content).hexdigest()
        policy = make_admissibility_policy()

        matching_doc = {
            "document_id": "doc_hash_match", "file_name": "probe.pdf",
            "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True},
            "raw_byte_sha256": real_hash,
        }
        errors, _warnings = with_manifest_validator_mevzuat_dir(
            mevzuat_dir,
            lambda: manifest_validator.validate_corpus_policy_admissibility([matching_doc], policy=policy),
        )
        check(
            "p2 raw_byte_sha256: declared hash matches real bytes -> no "
            "mismatch error",
            not any("raw_byte_sha256" in e for e in errors), errors,
        )

        mismatched_doc = {
            "document_id": "doc_hash_mismatch", "file_name": "probe.pdf",
            "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True},
            "raw_byte_sha256": "0" * 64,
        }
        errors, _warnings = with_manifest_validator_mevzuat_dir(
            mevzuat_dir,
            lambda: manifest_validator.validate_corpus_policy_admissibility([mismatched_doc], policy=policy),
        )
        check(
            "p2 raw_byte_sha256: declared hash mismatched against real bytes "
            "-> ERROR naming document",
            any("doc_hash_mismatch" in e and "raw_byte_sha256" in e for e in errors), errors,
        )

        null_doc = {
            "document_id": "doc_hash_null", "file_name": "probe.pdf",
            "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True},
            "raw_byte_sha256": None,
        }
        errors, _warnings = with_manifest_validator_mevzuat_dir(
            mevzuat_dir,
            lambda: manifest_validator.validate_corpus_policy_admissibility([null_doc], policy=policy),
        )
        check(
            "p2 raw_byte_sha256: null (no claim made) -> no error (skipped)",
            not any("raw_byte_sha256" in e for e in errors), errors,
        )

        absent_doc = {
            "document_id": "doc_hash_absent", "file_name": "probe.pdf",
            "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True},
        }
        errors, _warnings = with_manifest_validator_mevzuat_dir(
            mevzuat_dir,
            lambda: manifest_validator.validate_corpus_policy_admissibility([absent_doc], policy=policy),
        )
        check(
            "p2 raw_byte_sha256: absent (no claim made) -> no error (skipped)",
            not any("raw_byte_sha256" in e for e in errors), errors,
        )


def test_p2_raw_byte_sha256_never_checked_before_containment():
    with tempfile.TemporaryDirectory() as tmp:
        mevzuat_dir = Path(tmp) / "mevzuat"
        mevzuat_dir.mkdir()
        policy = make_admissibility_policy()
        doc = {
            "document_id": "doc_hash_escape_probe", "file_name": "../outside.pdf",
            "belge_turu": "Kanun", "active": True, "ingest": {"enabled": True},
            "raw_byte_sha256": "0" * 64,
        }
        errors, _warnings = with_manifest_validator_mevzuat_dir(
            mevzuat_dir,
            lambda: manifest_validator.validate_corpus_policy_admissibility([doc], policy=policy),
        )
        check(
            "p2 raw_byte_sha256: a declared hash on a containment-failing "
            "(escaping) file_name never produces a raw_byte_sha256 error - "
            "containment is checked BEFORE the hash gate",
            not any("raw_byte_sha256" in e for e in errors), errors,
        )


def test_p2_raw_byte_sha256_disclosed_limitation_ingest_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        mevzuat_dir = Path(tmp) / "mevzuat"
        mevzuat_dir.mkdir()
        (mevzuat_dir / "probe2.pdf").write_bytes(
            b"%PDF-1.4\nignored, never read for a disabled record",
        )
        policy = make_admissibility_policy()
        doc = {
            "document_id": "doc_hash_ingest_disabled", "file_name": "probe2.pdf",
            "belge_turu": "Kanun", "active": True, "ingest": {"enabled": False},
            "raw_byte_sha256": "0" * 64,
        }
        errors, _warnings = with_manifest_validator_mevzuat_dir(
            mevzuat_dir,
            lambda: manifest_validator.validate_corpus_policy_admissibility([doc], policy=policy),
        )
        check(
            "p2 raw_byte_sha256: a deliberately-wrong declared hash on an "
            "ingest.enabled=false record produces NO error - the disclosed "
            "limitation (never verified for inactive/ingest-disabled records)",
            not any("raw_byte_sha256" in e for e in errors), errors,
        )


def test_p2_real_manifest_still_valid_full_orchestration():
    result = manifest_validator.validate_manifest_file(raise_on_error=False)
    check(
        "p2: the real committed data/documents.json is still fully valid "
        "under validate_manifest_file() (schema + all 13 orchestration "
        "steps incl. the new P2 per-type rules and the raw_byte_sha256 "
        "gate) after the P2 patch",
        result["valid"] is True, result["errors"],
    )


def run_self_test():
    test_import_time_zero_side_effects()
    test_compute_source_manifest_deterministic()
    test_compute_source_manifest_excludes_inactive_document()
    test_compute_source_manifest_changes_on_pdf_edit()
    test_compute_source_manifest_missing_corpus_policy_fails_closed()
    test_compute_source_manifest_changes_on_corpus_policy_edit()
    test_build_bundle_snapshot_basic()
    test_build_bundle_snapshot_deterministic_for_same_inputs()
    test_create_embeddings_never_touches_real_credentials()
    test_admissibility_magic_byte_gate_positive_and_negative()
    test_admissibility_max_file_size_gate()
    test_admissibility_cross_document_raw_hash_dedup()
    test_admissibility_required_provenance_fields()
    test_admissibility_admission_prohibited_rejected()
    test_admissibility_unknown_belge_turu_rejected()
    test_admissibility_default_policy_loads_real_committed_policy()
    test_run_ingest_fails_closed_without_consent()
    test_direct_cli_refusal_real_subprocess()

    # F1 REMEDIATION (HIGH) - path-containment closure
    test_containment_traversal_rejected()
    test_containment_absolute_posix_style_rejected()
    test_containment_absolute_windows_drive_rejected()
    test_containment_unc_style_rejected()
    test_containment_windows_absolute_path_posix_semantics_note()
    test_containment_escaping_junction_rejected()
    test_containment_broken_junction_rejected()
    test_containment_looping_link_rejected_or_platform_skip()
    test_containment_safe_internal_alias_preserves_logical_name()
    test_containment_preview_build_rejects_before_anything_else()
    test_containment_build_document_chunks_rejects_before_pdf_extraction()
    test_containment_build_bundle_snapshot_rejects_own_join_site()

    # F2 REMEDIATION (MEDIUM) - admission=deferred fail-closed
    test_admissibility_admission_deferred_rejected_each_real_family()
    test_admissibility_admission_deferred_with_empty_provenance_still_rejected()
    test_admissibility_deferred_error_message_carries_context()
    test_admissibility_unknown_admission_value_not_silently_allowed()
    test_admissibility_deferred_document_rejected_before_extraction_embed_network()

    # RAG CORPUS PREREQUISITE DOCUMENTS-SCHEMA PATCH (P2)
    test_p2_schema_absent_null_value_for_new_fields()
    test_p2_schema_enum_rejection()
    test_p2_schema_pattern_rejection()
    test_p2_schema_additional_properties_still_false()
    test_p2_per_type_yargi_karari_required_fields()
    test_p2_per_type_ozelge_anonymization_identity_check()
    test_p2_sirkuler_unaffected_by_new_per_type_rules()
    test_p2_raw_byte_sha256_gate_match_mismatch_null()
    test_p2_raw_byte_sha256_never_checked_before_containment()
    test_p2_raw_byte_sha256_disclosed_limitation_ingest_disabled()
    test_p2_real_manifest_still_valid_full_orchestration()

    print(f"\n{passed} passed, {failed} failed, {informational_skips} informational skips")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
