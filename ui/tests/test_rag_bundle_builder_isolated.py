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

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import ingest  # noqa: E402

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
    return data_dir, mevzuat_dir, manifest_path


def with_fixture_paths(data_dir, mevzuat_dir, manifest_path, fn):
    original = (ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH)
    ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH = data_dir, mevzuat_dir, manifest_path
    try:
        return fn()
    finally:
        ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH = original


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
        data_dir, mevzuat_dir, manifest_path = make_fixture(Path(tmp))
        run = lambda: ingest.compute_source_manifest()
        first = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run)
        second = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run)
        check("source_manifest: deterministic across calls", first == second)
        check("source_manifest: 3 entries (documents.json + 2 pdfs)", len(first) == 3, first)
        check("source_manifest: sorted by path", [e["path"] for e in first] == sorted(e["path"] for e in first))
        for entry in first:
            check(f"source_manifest: entry {entry['path']} has sha256+size_bytes", "sha256" in entry and "size_bytes" in entry)


def test_compute_source_manifest_excludes_inactive_document():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path = make_fixture(Path(tmp), document_count=1)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["documents"][0]["active"] = False
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        entries = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest())
        check("source_manifest: inactive document excluded", len(entries) == 1)


def test_compute_source_manifest_changes_on_pdf_edit():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path = make_fixture(Path(tmp), document_count=1)
        before = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest())
        (mevzuat_dir / "doc_0.pdf").write_bytes(b"different content")
        after = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, lambda: ingest.compute_source_manifest())
        check("source_manifest: hash changes when PDF content changes", before != after)


# ================================================================
# build_bundle_snapshot() - gated on faiss/numpy availability
# ================================================================

def test_build_bundle_snapshot_basic():
    if not FAISS_AVAILABLE:
        skip_info("build_bundle_snapshot_basic", "faiss/numpy not installed in this environment")
        return
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path = make_fixture(Path(tmp), document_count=2)
        client = FakeEmbeddingClient()

        def run():
            return ingest.build_bundle_snapshot(
                embedding_client=client, pdf_page_extractor=fake_pdf_page_extractor, build_attempt=0,
            )

        snapshot = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run)
        check("build_bundle_snapshot: artifacts has exactly 3 fixed names", set(snapshot["artifacts"].keys()) == {"mevzuat.faiss", "documents.pkl", "config.json"})
        check("build_bundle_snapshot: chunk_count > 0", snapshot["chunk_count"] > 0)
        check("build_bundle_snapshot: embedding_dimension == client dimension", snapshot["embedding_dimension"] == client.dimension)
        check("build_bundle_snapshot: build_attempt echoed", snapshot["build_attempt"] == 0)
        check("build_bundle_snapshot: writes nothing under index/", not (Path(tmp) / "index").exists())


def test_build_bundle_snapshot_deterministic_for_same_inputs():
    if not FAISS_AVAILABLE:
        skip_info("build_bundle_snapshot_deterministic", "faiss/numpy not installed in this environment")
        return
    with tempfile.TemporaryDirectory() as tmp:
        data_dir, mevzuat_dir, manifest_path = make_fixture(Path(tmp), document_count=1)

        def run():
            return ingest.build_bundle_snapshot(
                embedding_client=FakeEmbeddingClient(), pdf_page_extractor=fake_pdf_page_extractor, build_attempt=0,
            )

        first = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run)
        second = with_fixture_paths(data_dir, mevzuat_dir, manifest_path, run)
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


def run_self_test():
    test_import_time_zero_side_effects()
    test_compute_source_manifest_deterministic()
    test_compute_source_manifest_excludes_inactive_document()
    test_compute_source_manifest_changes_on_pdf_edit()
    test_build_bundle_snapshot_basic()
    test_build_bundle_snapshot_deterministic_for_same_inputs()
    test_create_embeddings_never_touches_real_credentials()
    test_run_ingest_fails_closed_without_consent()
    test_direct_cli_refusal_real_subprocess()

    print(f"\n{passed} passed, {failed} failed, {informational_skips} informational skips")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
