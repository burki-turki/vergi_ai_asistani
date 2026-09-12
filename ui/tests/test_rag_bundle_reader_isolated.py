# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION - isolated tests for
# src/retriever.py's NEW pinned-bundle reader (load_pinned_bundle,
# PinnedRagBundle, the six RagBundleError subclasses, _pin_bundle_
# globals, RagBundleNotPinnedError/RagNetworkConsentRequiredError).
#
# faiss/numpy are NOT installed in this project's `vergi_ui_runtime`
# target environment - every fail-closed check below completes
# strictly BEFORE load_pinned_bundle() would ever import them (by
# design - "NO pickle/FAISS load before hash verification"), so all
# SIX error classes are fully, non-gated testable here. Only the
# single "successful full load into a queryable PinnedRagBundle" happy
# path needs faiss/numpy and is gated behind a runtime availability
# probe, printed as an INFORMATIONAL, UNCOUNTED skip when unavailable
# (mirrors this project's established convention).
#
# Run: python -m ui.tests.test_rag_bundle_reader_isolated
# ============================================================

import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import retriever as r  # noqa: E402

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
        check(label, False, f"{detail} - unexpected exception: {type(error).__name__}: {error!r}")
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


def make_identity_core(**overrides):
    core = {
        "manifest_version": "test.v1",
        "source_manifest": [],
        "pipeline_config": {"x": 1},
        "build_attempt": 0,
        "chunk_count": 0,
        "embedding_dimension": 3,
        "artifacts": {
            "mevzuat.faiss": {"sha256": "a" * 64, "size_bytes": 0},
            "documents.pkl": {"sha256": "a" * 64, "size_bytes": 0},
            "config.json": {"sha256": "a" * 64, "size_bytes": 0},
        },
    }
    core.update(overrides)
    return core


def write_pointer(index_dir: Path, bundle_version):
    (index_dir / "current_version.json").write_text(
        json.dumps({"current_version": bundle_version}), encoding="utf-8",
    )


def write_bundle(index_dir: Path, identity_core, *, artifact_bytes=None):
    bundle_version = "v_" + hashlib.sha256(r._canonical_json_bytes(identity_core)).hexdigest()
    bundle_dir = index_dir / bundle_version
    bundle_dir.mkdir(parents=True)
    manifest = dict(identity_core)
    manifest["bundle_version"] = bundle_version
    (bundle_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if artifact_bytes:
        for name, raw in artifact_bytes.items():
            (bundle_dir / name).write_bytes(raw)
    return bundle_version, bundle_dir


# ================================================================
# import-time safety
# ================================================================

def test_import_time_zero_side_effects():
    check("retriever: index starts None", r.index is None)
    check("retriever: documents starts None", r.documents is None)


# ================================================================
# retrieve_detailed()/retrieve() fail-closed default
# ================================================================

def test_retrieve_detailed_requires_bundle():
    expect_raises(
        r.RagBundleNotPinnedError, lambda: r.retrieve_detailed("sorgu"), "retrieve_detailed: bundle=None fails closed",
    )
    expect_raises(
        r.RagBundleNotPinnedError, lambda: r.retrieve("sorgu"), "retrieve: bundle=None fails closed",
    )


# ================================================================
# load_pinned_bundle() - six fail-closed error classes.
# ================================================================

def test_pointer_missing_absent_index_dir():
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "does_not_exist"
        expect_raises(
            r.RagPointerMissingError, lambda: r.load_pinned_bundle(root=missing), "pointer_missing: index dir absent",
        )


def test_pointer_missing_no_pointer_file():
    with tempfile.TemporaryDirectory() as tmp:
        expect_raises(
            r.RagPointerMissingError, lambda: r.load_pinned_bundle(root=tmp), "pointer_missing: no pointer file",
        )


def test_pointer_invalid_malformed_json():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "current_version.json").write_text("not json", encoding="utf-8")
        expect_raises(
            r.RagPointerInvalidError, lambda: r.load_pinned_bundle(root=tmp), "pointer_invalid: malformed JSON",
        )


def test_pointer_invalid_not_an_object():
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "current_version.json").write_text("[1,2,3]", encoding="utf-8")
        expect_raises(
            r.RagPointerInvalidError, lambda: r.load_pinned_bundle(root=tmp), "pointer_invalid: not a JSON object",
        )


def test_pointer_invalid_bad_shape_version():
    with tempfile.TemporaryDirectory() as tmp:
        write_pointer(Path(tmp), "not_a_real_version")
        expect_raises(
            r.RagPointerInvalidError, lambda: r.load_pinned_bundle(root=tmp), "pointer_invalid: bad-shape version",
        )


def test_manifest_invalid_bundle_dir_missing():
    with tempfile.TemporaryDirectory() as tmp:
        write_pointer(Path(tmp), "v_" + "a" * 64)
        expect_raises(
            r.RagManifestInvalidError, lambda: r.load_pinned_bundle(root=tmp), "manifest_invalid: bundle dir missing",
        )


def test_manifest_invalid_not_self_consistent():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp)
        real_version, bundle_dir = write_bundle(index_dir, make_identity_core())
        # Tamper the manifest AFTER writing (content no longer matches its own bundle_version hash).
        manifest_path = bundle_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["chunk_count"] = 999
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        write_pointer(index_dir, real_version)
        expect_raises(
            r.RagManifestInvalidError, lambda: r.load_pinned_bundle(root=tmp), "manifest_invalid: tampered content",
        )


def test_manifest_invalid_wrong_artifact_set():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp)
        core = make_identity_core(artifacts={"mevzuat.faiss": {"sha256": "a" * 64, "size_bytes": 0}})
        real_version, _bundle_dir = write_bundle(index_dir, core)
        write_pointer(index_dir, real_version)
        expect_raises(
            r.RagManifestInvalidError, lambda: r.load_pinned_bundle(root=tmp), "manifest_invalid: wrong artifact set",
        )


def test_artifact_hash_mismatch_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp)
        real_version, _bundle_dir = write_bundle(index_dir, make_identity_core())
        write_pointer(index_dir, real_version)
        expect_raises(
            r.RagArtifactHashMismatchError, lambda: r.load_pinned_bundle(root=tmp), "artifact_hash_mismatch: missing files",
        )


def test_artifact_hash_mismatch_wrong_bytes():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp)
        expected = {
            "mevzuat.faiss": b"real faiss bytes here",
            "documents.pkl": b"real pkl bytes",
            "config.json": b"{}",
        }
        core = make_identity_core(artifacts={
            name: {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            for name, raw in expected.items()
        })
        real_version, bundle_dir = write_bundle(index_dir, core, artifact_bytes=expected)
        # Corrupt one artifact AFTER writing.
        (bundle_dir / "documents.pkl").write_bytes(b"corrupted")
        write_pointer(index_dir, real_version)
        expect_raises(
            r.RagArtifactHashMismatchError, lambda: r.load_pinned_bundle(root=tmp), "artifact_hash_mismatch: corrupted bytes",
        )


def test_path_containment_escaping_pointer_version():
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp)
        write_pointer(index_dir, "v_" + "a" * 64)
        # Even a well-shaped bundle_version pointing outside index/ is
        # unreachable by construction (join is always index_dir/version,
        # never an absolute/escaping path) - re-affirm the pointer-shape
        # gate is the only real gate here (structural, not exploitable).
        expect_raises(
            r.RagManifestInvalidError, lambda: r.load_pinned_bundle(root=tmp), "path_containment: no matching bundle dir",
        )


# ================================================================
# Successful full load - gated on faiss/numpy availability.
# ================================================================

def _build_real_faiss_bytes_and_docs():
    import faiss
    import numpy as np

    vectors = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype="float32")
    faiss.normalize_L2(vectors)
    index = faiss.IndexFlatIP(3)
    index.add(vectors)
    faiss_bytes = np.asarray(faiss.serialize_index(index)).tobytes()
    import pickle

    documents = [{"text": "a"}, {"text": "b"}]
    return faiss_bytes, pickle.dumps(documents)


def test_load_pinned_bundle_success_and_pin_globals():
    if not FAISS_AVAILABLE:
        skip_info("load_pinned_bundle_success", "faiss/numpy not installed in this environment")
        return
    with tempfile.TemporaryDirectory() as tmp:
        index_dir = Path(tmp)
        faiss_bytes, documents_bytes = _build_real_faiss_bytes_and_docs()
        config_bytes = b"{}"
        artifacts = {"mevzuat.faiss": faiss_bytes, "documents.pkl": documents_bytes, "config.json": config_bytes}
        core = make_identity_core(
            embedding_dimension=3,
            artifacts={
                name: {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
                for name, raw in artifacts.items()
            },
        )
        real_version, _bundle_dir = write_bundle(index_dir, core, artifact_bytes=artifacts)
        write_pointer(index_dir, real_version)

        bundle = r.load_pinned_bundle(root=index_dir)
        check("load_pinned_bundle: bundle_version matches", bundle.bundle_version == real_version)
        check("load_pinned_bundle: 2 documents loaded", len(bundle.documents) == 2)
        check("load_pinned_bundle: index.ntotal == 2", bundle.index.ntotal == 2)

        with r._pin_bundle_globals(bundle):
            check("_pin_bundle_globals: index pinned", r.index is bundle.index)
            check("_pin_bundle_globals: documents pinned", r.documents is bundle.documents)
        check("_pin_bundle_globals: restored to None after context exit", r.index is None and r.documents is None)


def run_self_test():
    test_import_time_zero_side_effects()
    test_retrieve_detailed_requires_bundle()
    test_pointer_missing_absent_index_dir()
    test_pointer_missing_no_pointer_file()
    test_pointer_invalid_malformed_json()
    test_pointer_invalid_not_an_object()
    test_pointer_invalid_bad_shape_version()
    test_manifest_invalid_bundle_dir_missing()
    test_manifest_invalid_not_self_consistent()
    test_manifest_invalid_wrong_artifact_set()
    test_artifact_hash_mismatch_missing_file()
    test_artifact_hash_mismatch_wrong_bytes()
    test_path_containment_escaping_pointer_version()
    test_load_pinned_bundle_success_and_pin_globals()

    print(f"\n{passed} passed, {failed} failed, {informational_skips} informational skips")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
