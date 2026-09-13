# ============================================================
# RAG REAL-DEPENDENCY VALIDATION + SYNTHETIC E2E GATE.
#
# ONE NEW file, ZERO modified production files. This is the mandatory
# opening gate for RAG corpus population (see CLAUDE.md's "RAG
# Real-Dependency Validation and Corpus Population Scope
# Reconciliation" pointer): it proves, against WHATEVER real Python
# environment it is invoked with, that faiss/numpy/pypdf/openai/
# python-dotenv/httpx2 are not merely "pip installed" (dist-info
# present) but ACTUALLY IMPORTABLE and API-COMPATIBLE with this
# repository's real production code - by running a full, real,
# synthetic build -> publish -> activate -> load_pinned_bundle ->
# retrieve round trip through the EXACT SAME public production APIs
# the RAG Global-Resource Bundle Foundation (LOCKED) already ships:
# `ui.services.rag_bundle_mutation_facade.{preview_build,apply_build,
# preview_activate,apply_activate}`, `src.ingest.build_bundle_snapshot`
# (via the facade, real pypdf forced - see that module's own `:697`
# `pdf_page_extractor=None`), `src.retriever.{load_pinned_bundle,
# retrieve_detailed}`.
#
# NOTHING production is touched: `ingest.DATA_DIR/MEVZUAT_DIR/
# MANIFEST_PATH/INDEX_DIR` and `manifest_validator.MANIFEST_PATH/
# MEVZUAT_DIR` are redirected to a repo-external TemporaryDirectory for
# the duration of every mutating step (mirrors this Foundation's own
# `test_rag_bundle_mutation_facade_isolated.py` Fixture pattern);
# `manifest_validator.SCHEMA_PATH` is left pointing at the REAL,
# LOCKED `data/documents.schema.json` on purpose - so the synthetic
# manifest this file builds is validated against the SAME schema a
# real corpus manifest would be (closing the cross-module path quirk
# `build_bundle_snapshot():3142`'s `validate_manifest_file()` call
# would otherwise leave uncovered by any Foundation test that only
# redirects `ingest.*`). No real network call is ever made - the
# OpenAI embedding calls run through the real `openai` SDK's real
# request/response-parsing path, but over an `httpx2.MockTransport`
# (zero sockets); a socket-level guard also blocks any *other*
# outbound connection attempt for defense in depth, and is itself
# probed (never by attempting a genuine connection). No PostgreSQL is
# required (contract note: real Postgres was assessed as optional -
# this file uses the same fake-conn/fake-lock fixture shape this
# Foundation's own facade tests already establish and rely on).
#
# GATE CONTRACT (VERGI_RAG_DEPENDENCY_GATE):
#   unset/""   -> developer mode: a genuinely MISSING dependency is an
#                 informational, uncounted skip (never a PASS marker).
#   "require"  -> mandatory mode: a genuinely missing dependency is a
#                 real, counted FAILURE.
#   anything else -> fail-closed: a real, counted FAILURE, always -
#                 there is no silent fallback to developer mode for a
#                 typo'd value.
# In EVERY mode, "dist-info says installed but import/API is actually
# broken or version-mismatched vs. this repo's own pinned
# requirements.txt" is ALWAYS a real, counted failure - this is the
# exact "wrong base interpreter" scenario this gate exists to catch
# (a `.venv`-adjacent base interpreter on this project's own
# development machine carries openai 2.54.0 against a 3.6.0 pin,
# discovered while scoping this gate).
#
# Run (developer mode):
#   python -m ui.tests.test_rag_bundle_dependency_smoke
# Run (mandatory gate mode, the CI/LOCK-evidence invocation):
#   VERGI_RAG_DEPENDENCY_GATE=require python -m ui.tests.test_rag_bundle_dependency_smoke
# ============================================================

import base64
import contextlib
import hashlib
import importlib
import importlib.metadata as importlib_metadata
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
THIS_FILE = Path(__file__).resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import ingest  # noqa: E402
import manifest_validator as mv  # noqa: E402
import retriever as r  # noqa: E402

from ui.services import global_authz as ga  # noqa: E402
from ui.services import mutation_lock as ml  # noqa: E402
from ui.services import rag_bundle_mutation_facade as facade  # noqa: E402
from ui.services.authz import Principal  # noqa: E402

GATE_ENV_VAR = "VERGI_RAG_DEPENDENCY_GATE"
CHILD_ENV_VAR = "VERGI_RAG_DEPENDENCY_GATE_CHILD"
FORCE_INVARIANCE_FAILURE_ENV_VAR = "VERGI_RAG_DEPENDENCY_GATE_FORCE_INVARIANCE_FAILURE_FOR_TEST"

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


# ================================================================
# SECTION A - environment classification (real importlib.metadata +
# real import probe) and the pure, injectable gate-outcome decision.
# ================================================================

REQUIRED_PACKAGES = [
    {"dist": "faiss-cpu", "module": "faiss"},
    {"dist": "numpy", "module": "numpy"},
    {"dist": "pypdf", "module": "pypdf"},
    {"dist": "openai", "module": "openai"},
    {"dist": "python-dotenv", "module": "dotenv"},
    {"dist": "httpx2", "module": "httpx2"},
]

# Anthropic is reported for environment-identity purposes only - the
# Foundation's own build->activate->load->retrieve chain never touches
# it (see CLAUDE.md's RAG Bundle Foundation checkpoint: `src.rag`'s
# module-level `from anthropic import Anthropic` is a SEPARATE, later
# consumption layer this gate does not exercise). It is NEVER a
# pass/fail condition for this gate.
INFORMATIONAL_PACKAGES = [{"dist": "anthropic", "module": "anthropic"}]


def read_root_requirements_pins():
    """`requirements.txt` is UTF-16 (with BOM) + CRLF (a known, pre-
    existing repo anomaly - see CLAUDE.md Row 18a). Read-only; never
    modified by this gate."""
    path = REPO_ROOT / "requirements.txt"
    text = path.read_text(encoding="utf-16")
    pins = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        pins[name.strip()] = version.strip()
    return pins


def classify_package(dist_name, module_name, pin_version):
    """Real classification of ONE package against the REAL running
    interpreter: (1) importlib.metadata dist-info lookup, (2) a real
    `importlib.import_module()` probe. Never uses a bare
    `except Exception: skip()` shortcut - every branch is named and
    every branch's fate (skip vs. fail, and in which mode) is decided
    separately by `decide_gate_outcome()` below, not here."""
    try:
        metadata_version = importlib_metadata.version(dist_name)
    except importlib_metadata.PackageNotFoundError:
        metadata_version = None

    import_ok = False
    import_error = None
    try:
        importlib.import_module(module_name)
        import_ok = True
    except Exception as error:
        import_error = f"{type(error).__name__}: {error}"

    if metadata_version is None and not import_ok:
        classification = "metadata_missing_import_broken"
        detail = (
            f"{dist_name}: no distribution metadata found and "
            f"import {module_name!r} failed ({import_error}) - genuinely not installed here"
        )
    elif metadata_version is not None and not import_ok:
        classification = "metadata_present_import_broken"
        detail = (
            f"{dist_name}: distribution metadata reports version {metadata_version} but "
            f"import {module_name!r} failed ({import_error}) - a real environment defect, "
            "FAILS in every gate mode"
        )
    elif metadata_version is None and import_ok:
        classification = "metadata_missing_import_ok"
        detail = (
            f"{dist_name}: import {module_name!r} succeeded but NO distribution metadata was "
            "found - the version pin cannot be verified; fail-closed, FAILS in every gate mode"
        )
    else:
        if pin_version is not None and metadata_version != pin_version:
            classification = "version_mismatch"
            detail = (
                f"{dist_name}: installed version {metadata_version!r} does not match this "
                f"repository's own requirements.txt pin {pin_version!r} - FAILS in every gate "
                "mode (this is exactly the wrong-base-interpreter scenario this gate exists to catch)"
            )
        else:
            classification = "ok_pinned"
            detail = f"{dist_name}: {metadata_version} (matches requirements.txt pin)"

    return {
        "dist": dist_name,
        "module": module_name,
        "pin_version": pin_version,
        "metadata_version": metadata_version,
        "import_ok": import_ok,
        "import_error": import_error,
        "classification": classification,
        "detail": detail,
    }


def classify_required_packages():
    pins = read_root_requirements_pins()
    return [classify_package(pkg["dist"], pkg["module"], pins.get(pkg["dist"])) for pkg in REQUIRED_PACKAGES]


def _environment_is_fully_dependency_ready():
    """True only when every required package classifies as `ok_pinned` in
    the CURRENT process's own interpreter. Used solely to decide whether
    the heavy, genuine-E2E PASS-marker-ordering subprocess test below is
    meaningful to spawn here - it needs a real, successful E2E run to
    force a later failure against, which a genuinely dependency-broken
    environment cannot provide (that case is already covered by the
    require-mode hard-fail path exercised elsewhere in this file)."""
    return all(c["classification"] == "ok_pinned" for c in classify_required_packages())


def decide_gate_outcome(classifications, mode):
    """Pure function of (classification list, gate mode) -> outcome.
    Deliberately injectable/fabricatable (see the self-tests directly
    below) so every branch (missing-in-dev vs missing-in-require,
    broken-import-in-either-mode, version-mismatch-in-either-mode,
    all-ok) is proven correct WITHOUT needing a genuinely broken real
    environment to exercise it against."""
    hard_fail = [
        c
        for c in classifications
        if c["classification"] in ("version_mismatch", "metadata_present_import_broken", "metadata_missing_import_ok")
    ]
    missing = [c for c in classifications if c["classification"] == "metadata_missing_import_broken"]
    ok = [c for c in classifications if c["classification"] == "ok_pinned"]
    require_mode = mode == "require"
    ready = (not hard_fail) and (not missing) and (len(ok) == len(classifications))
    return {
        "hard_fail": hard_fail,
        "missing": missing,
        "ok": ok,
        "ready": ready,
        "require_mode": require_mode,
        "require_mode_missing_is_fail": require_mode and bool(missing),
    }


def _fabricated_classification(classification, dist="fabricated_pkg"):
    return {
        "dist": dist,
        "module": dist,
        "pin_version": "1.0.0",
        "metadata_version": "1.0.0" if classification != "metadata_missing_import_broken" else None,
        "import_ok": classification == "ok_pinned",
        "import_error": None,
        "classification": classification,
        "detail": "fabricated for decide_gate_outcome() self-test",
    }


def test_decide_gate_outcome_all_ok_ready_in_both_modes():
    classifications = [_fabricated_classification("ok_pinned", dist=f"okpkg{i}") for i in range(3)]
    dev = decide_gate_outcome(classifications, "")
    require = decide_gate_outcome(classifications, "require")
    check("decide_gate_outcome: all ok_pinned -> ready (dev)", dev["ready"] is True)
    check("decide_gate_outcome: all ok_pinned -> ready (require)", require["ready"] is True)
    check("decide_gate_outcome: all ok_pinned -> zero hard_fail (both)", not dev["hard_fail"] and not require["hard_fail"])


def test_decide_gate_outcome_missing_dependency_dev_vs_require():
    classifications = [
        _fabricated_classification("ok_pinned", dist="okpkg"),
        _fabricated_classification("metadata_missing_import_broken", dist="missingpkg"),
    ]
    dev = decide_gate_outcome(classifications, "")
    require = decide_gate_outcome(classifications, "require")
    check("decide_gate_outcome: missing dep -> not ready (dev)", dev["ready"] is False)
    check("decide_gate_outcome: missing dep -> dev mode does NOT mark require_mode_missing_is_fail", dev["require_mode_missing_is_fail"] is False)
    check("decide_gate_outcome: missing dep -> not ready (require)", require["ready"] is False)
    check("decide_gate_outcome: missing dep -> require mode DOES mark require_mode_missing_is_fail", require["require_mode_missing_is_fail"] is True)
    check("decide_gate_outcome: missing dep -> zero hard_fail in either mode (it is 'missing', not 'broken')", not dev["hard_fail"] and not require["hard_fail"])


def test_decide_gate_outcome_metadata_present_import_broken_fails_both_modes():
    classifications = [_fabricated_classification("metadata_present_import_broken", dist="brokenpkg")]
    dev = decide_gate_outcome(classifications, "")
    require = decide_gate_outcome(classifications, "require")
    check("decide_gate_outcome: broken import -> hard_fail present (dev)", len(dev["hard_fail"]) == 1)
    check("decide_gate_outcome: broken import -> hard_fail present (require)", len(require["hard_fail"]) == 1)
    check("decide_gate_outcome: broken import -> not ready (dev)", dev["ready"] is False)
    check("decide_gate_outcome: broken import -> not ready (require)", require["ready"] is False)


def test_decide_gate_outcome_version_mismatch_fails_both_modes():
    classifications = [_fabricated_classification("version_mismatch", dist="mismatchpkg")]
    dev = decide_gate_outcome(classifications, "")
    require = decide_gate_outcome(classifications, "require")
    check("decide_gate_outcome: version mismatch -> hard_fail present (dev)", len(dev["hard_fail"]) == 1)
    check("decide_gate_outcome: version mismatch -> hard_fail present (require)", len(require["hard_fail"]) == 1)
    check("decide_gate_outcome: version mismatch -> not ready (dev)", dev["ready"] is False)
    check("decide_gate_outcome: version mismatch -> not ready (require)", require["ready"] is False)


def test_decide_gate_outcome_metadata_missing_import_ok_fails_both_modes():
    classifications = [_fabricated_classification("metadata_missing_import_ok", dist="unverifiablepkg")]
    dev = decide_gate_outcome(classifications, "")
    require = decide_gate_outcome(classifications, "require")
    check("decide_gate_outcome: import-ok-but-no-metadata -> hard_fail (dev)", len(dev["hard_fail"]) == 1)
    check("decide_gate_outcome: import-ok-but-no-metadata -> hard_fail (require)", len(require["hard_fail"]) == 1)


# ================================================================
# SECTION B - fail-closed socket guard (defense in depth; the real
# OpenAI calls below never reach the socket layer at all, since
# httpx2.MockTransport intercepts them upstream of any real socket -
# this guard exists to prove, mechanically, that NOTHING else in this
# test's own code path ever attempts a real outbound connection).
# ================================================================


class _SocketGuardTripped(Exception):
    """Raised by the guarded `socket.socket.connect`/`create_connection`
    stand-ins below - proves (by construction: no real syscall is ever
    reached) that installing the guard makes a real outbound connection
    attempt impossible, without this test ever actually performing
    one (not even to a reserved/non-routable test address)."""


def _install_socket_guard():
    import socket as socket_module

    original_connect = socket_module.socket.connect
    original_create_connection = socket_module.create_connection

    def _guarded_connect(self, address):
        raise _SocketGuardTripped(f"blocked outbound socket.connect() to {address!r}")

    def _guarded_create_connection(address, *args, **kwargs):
        raise _SocketGuardTripped(f"blocked outbound socket.create_connection() to {address!r}")

    socket_module.socket.connect = _guarded_connect
    socket_module.create_connection = _guarded_create_connection
    return socket_module, original_connect, original_create_connection


def _restore_socket_guard(socket_module, original_connect, original_create_connection):
    socket_module.socket.connect = original_connect
    socket_module.create_connection = original_create_connection


def _probe_socket_guard_without_real_connection():
    """Proves the installed guard actually intercepts - WITHOUT ever
    performing (or even attempting the DNS/syscall machinery of) a
    real connection: the guard replaces the function object entirely,
    so `create_connection()` raises `_SocketGuardTripped` immediately,
    before any real network primitive is invoked."""
    import socket as socket_module

    expect_raises(
        _SocketGuardTripped,
        lambda: socket_module.create_connection(("203.0.113.1", 80), timeout=0.05),
        "socket guard: create_connection() is blocked while the guard is installed",
    )
    expect_raises(
        _SocketGuardTripped,
        lambda: socket_module.socket().connect(("203.0.113.1", 80)),
        "socket guard: socket().connect() is blocked while the guard is installed",
    )


# ================================================================
# SECTION C - fake mutation-journal connection (independent copy of
# this Foundation's own established `test_rag_bundle_mutation_facade_
# isolated.py` FakeJournalConn/FakeJournalCursor shape - the same
# fake-conn fixture pattern that module's own tests already rely on
# for every non-PostgreSQL scenario; PostgreSQL is optional for this
# gate). Reused here unchanged in SQL-shape terms.
# ================================================================


class FakeJournalCursor:
    def __init__(self, conn):
        self._conn = conn
        self._last_result = None
        self.rowcount = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _row(self, journal_id):
        for row in self._conn.table:
            if row["id"] == journal_id:
                return row
        raise AssertionError(f"no fake journal row with id={journal_id}")

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._conn.calls.append(normalized.split()[0])

        if normalized.startswith("SELECT authz_version, disabled FROM iam.users"):
            (user_id,) = params
            row = self._conn.iam_users.get(user_id)
            self._last_result = (row["authz_version"], row["disabled"]) if row else None
        elif normalized.startswith("SELECT 1 FROM iam.global_resource_grants"):
            user_id, resource, capability = params
            hit = (user_id, resource, capability) in self._conn.iam_grants
            self._last_result = (1,) if hit else None
        elif normalized.startswith("SELECT 1 FROM mutation.mutation_journal"):
            (resource_key,) = params
            hit = any(
                row["resource_key"] == resource_key and row["state"] in ("prepared", "executing", "reconciliation_required")
                for row in self._conn.table
            )
            self._last_result = (1,) if hit else None
        elif normalized.startswith("SELECT id, state, request_fingerprint, observed_post_hash"):
            (idempotency_key,) = params
            matches = [row for row in self._conn.table if row["idempotency_key"] == idempotency_key]
            if not matches:
                self._last_result = None
            else:
                row = matches[0]
                self._last_result = (
                    row["id"], row["state"], row["request_fingerprint"], row["observed_post_hash"],
                    row["failure_code"], row["resolution_code"],
                )
        elif normalized.startswith("INSERT INTO mutation.mutation_journal"):
            (
                resource_key, action_family, actor_user_id, actor_label, target_ref, target_state,
                pre_hash, pre_revision, idempotency_key, request_fingerprint,
            ) = params
            new_id = len(self._conn.table) + 1
            self._conn.table.append({
                "id": new_id, "resource_key": resource_key, "action_family": action_family,
                "actor_user_id": actor_user_id, "actor_label": actor_label, "target_ref": target_ref,
                "target_state": target_state, "pre_hash": pre_hash, "pre_revision": pre_revision,
                "idempotency_key": idempotency_key, "request_fingerprint": request_fingerprint,
                "state": "prepared", "failure_code": None, "resolution_code": None,
                "observed_post_hash": None,
            })
            self._last_result = (new_id,)
            self.rowcount = 1
        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'executing'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "executing"
            self.rowcount = 1
        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'completed'"):
            observed_post_hash, journal_id = params
            row = self._row(journal_id)
            row["state"] = "completed"
            row["observed_post_hash"] = observed_post_hash
            self.rowcount = 1
        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'reconciliation_required'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "reconciliation_required"
            self.rowcount = 1
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._last_result


class FakeJournalConn:
    def __init__(self, *, iam_users=None, iam_grants=None):
        self.table = []
        self.calls = []
        self.closed = False
        self.iam_users = iam_users if iam_users is not None else {uid: {"authz_version": 1, "disabled": False} for uid in range(1, 50)}
        self.iam_grants = iam_grants if iam_grants is not None else {
            (uid, "rag_index", cap) for uid in range(1, 50) for cap in ("inspect", "build", "activate")
        }

    def cursor(self):
        return FakeJournalCursor(self)

    def close(self):
        self.closed = True


_original_acquire_global_lock_session = ml.acquire_global_lock_session
_original_release_lock_session = ml.release_lock_session


def _fake_acquire_global_lock_session(conn, resource_key):
    return 999999


def _fake_release_lock_session(conn, advisory_lock_id):
    return True


def _install_lock_fakes():
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session


def _restore_lock_fakes():
    ml.acquire_global_lock_session = _original_acquire_global_lock_session
    ml.release_lock_session = _original_release_lock_session


def make_principal_and_repo(user_id=7, grants=("inspect", "build", "activate")):
    principal = Principal(user_id=user_id, session_id=0, role_version_at_issue=1)
    repo = ga.InMemoryGlobalResourceAuthzRepository()
    repo.sessions[user_id] = ga._authz.SessionRecord(user_id=user_id, current_authz_version=1, disabled=False)
    for capability in grants:
        repo.grants.add((user_id, "rag_index", capability))
    return principal, repo


# ================================================================
# SECTION D - a minimal but REAL, text-bearing, uncompressed PDF
# builder (hand-built byte template - no external PDF library
# needed to CREATE the fixture; `pypdf` is what READS it, for real,
# via `ingest.extract_pdf_pages()`/`build_bundle_snapshot()`).
# ================================================================


def build_minimal_text_pdf(lines):
    """A single-page PDF with one `Tj` text-show operator per line, an
    uncompressed content stream, and a correct xref/trailer computed
    from real byte offsets (not hardcoded) - readable by a real
    `pypdf.PdfReader(...).pages[0].extract_text()`. ASCII-only text
    (no Turkish-specific glyphs) to avoid PDF text-encoding pitfalls
    unrelated to what this gate is actually testing."""
    for line in lines:
        if not line.isascii():
            raise ValueError("build_minimal_text_pdf: ASCII-only lines are required")

    content_ops = []
    y = 750
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content_ops.append(f"BT /F1 12 Tf 72 {y} Td ({escaped}) Tj ET")
        y -= 18
    content_stream = "\n".join(content_ops).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content_stream)).encode("ascii") + b" >>\nstream\n" + content_stream + b"\nendstream",
    ]

    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"

    xref_offset = len(body)
    object_count = len(objects) + 1
    xref = f"xref\n0 {object_count}\n".encode("ascii") + b"0000000000 65535 f \n"
    for index in range(1, object_count):
        xref += f"{offsets[index]:010d} 00000 n \n".encode("ascii")
    trailer = f"trailer\n<< /Size {object_count} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("ascii")

    body += xref + trailer
    return bytes(body)


# ================================================================
# SECTION E - deterministic, topic-clustered embeddings + a real
# OpenAI SDK client wired to a real httpx2.MockTransport (zero real
# network; real request-body parse, real base64 response-decode path
# - `openai`'s embeddings.create() defaults to `encoding_format=
# "base64"` whenever it is not explicitly given, exactly as `src.
# ingest.create_embeddings()`/`src.retriever.create_query_embedding()`
# call it - so the mock response MUST return base64-packed float32
# bytes, not a plain JSON float list, or the real SDK's own lenient-
# construct-then-decode path would not be genuinely exercised).
# ================================================================

EMBEDDING_DIMENSION_FOR_GATE = 1536


def _topic_key(text):
    upper = text.upper()
    if "ALPHA" in upper:
        return "TOPIC_ALPHA"
    if "BETA" in upper:
        return "TOPIC_BETA"
    return "TOPIC_OTHER"


def _deterministic_embedding(text, dimension=EMBEDDING_DIMENSION_FOR_GATE):
    """Same exact text -> same exact vector, every time, with zero
    randomness sourced from wall-clock/OS entropy. Two texts sharing a
    topic marker (ALPHA or BETA) get a dominant SHARED base direction
    (a query for "alpha" therefore lands extremely close, in cosine
    terms, to a chunk whose text also contains "alpha") plus a tiny,
    text-specific jitter (so two DIFFERENT alpha-texts are not bit-
    identical vectors, without ever weakening the topic clustering the
    retrieval-order assertions below depend on)."""
    import numpy as np

    topic_seed = int(hashlib.sha256(_topic_key(text).encode("utf-8")).hexdigest()[:8], 16)
    base = np.random.RandomState(topic_seed).standard_normal(dimension)
    text_seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
    jitter = np.random.RandomState(text_seed).standard_normal(dimension) * 0.001
    return (base + jitter).astype("float32")


def make_openai_mock_client(call_log):
    """Returns a real `openai.OpenAI` client whose real `http_client`
    is a real `httpx2.Client(transport=httpx2.MockTransport(handler))`
    - every `.embeddings.create()` call goes through the real SDK
    request-building/response-parsing code, over a transport that
    never opens a socket. `call_log` (a list the caller owns) records
    `{"model": ..., "input_count": ...}` per call for assertions."""
    import httpx2
    import numpy as np
    from openai import OpenAI

    def handler(request):
        body = json.loads(request.content)
        model = body.get("model")
        raw_input = body.get("input")
        inputs = raw_input if isinstance(raw_input, list) else [raw_input]
        call_log.append({"model": model, "input_count": len(inputs)})

        data = []
        for index, text in enumerate(inputs):
            vector = _deterministic_embedding(text)
            encoded = base64.b64encode(np.asarray(vector, dtype="float32").tobytes()).decode("ascii")
            data.append({"object": "embedding", "index": index, "embedding": encoded})

        payload = {
            "object": "list",
            "data": data,
            "model": model,
            "usage": {"prompt_tokens": sum(len(text) for text in inputs), "total_tokens": sum(len(text) for text in inputs)},
        }
        return httpx2.Response(200, json=payload)

    mock_http_client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return OpenAI(api_key="test-not-real-smoke-gate-key", http_client=mock_http_client)


# ================================================================
# SECTION F - repo `data/`/`index/` byte-invariance manifest.
# ================================================================


def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_tree(root):
    if not root.exists():
        return {"__root_missing__": True}
    entries = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            entries[str(path.relative_to(root))] = {"size": path.stat().st_size, "sha256": _hash_file(path)}
    return entries


def snapshot_repo_manifest():
    return {"data": _snapshot_tree(REPO_ROOT / "data"), "index": _snapshot_tree(REPO_ROOT / "index")}


def _inject_fake_invariance_drift_if_requested():
    """Test-only, in-memory-only hook: when the dedicated env var is set,
    the SECOND call this process ever makes to `snapshot_repo_manifest()`
    returns a deliberately mutated COPY of the real snapshot (one
    synthetic extra entry), so the final data/index byte-invariance check
    fails deterministically. This never writes a single real byte under
    `data/` or `index/` - the real trees are read once for real, then the
    returned dict is mutated in memory. Never set by any normal gate
    invocation, including the mandatory `--require` one; used exclusively
    by the subprocess proof in Section K below."""
    if os.environ.get(FORCE_INVARIANCE_FAILURE_ENV_VAR) != "1":
        return

    global snapshot_repo_manifest
    real_snapshot_repo_manifest = snapshot_repo_manifest
    call_count = {"n": 0}

    def _rigged_snapshot_repo_manifest():
        call_count["n"] += 1
        result = real_snapshot_repo_manifest()
        if call_count["n"] >= 2:
            result = {"data": dict(result["data"]), "index": dict(result["index"])}
            result["data"]["__forced_invariance_drift_for_test__"] = {"size": 0, "sha256": "0" * 64}
        return result

    snapshot_repo_manifest = _rigged_snapshot_repo_manifest


def _summary_reports_at_least_one_failure(text):
    match = re.search(r"(\d+) passed, (\d+) failed, (\d+) informational skips", text)
    return bool(match) and int(match.group(2)) >= 1


# ================================================================
# SECTION G - source-path redirection context manager (ingest.* +
# manifest_validator.* - SCHEMA_PATH deliberately left pointing at the
# real, LOCKED data/documents.schema.json).
# ================================================================


@contextlib.contextmanager
def patched_source_paths(data_dir, mevzuat_dir, manifest_path, index_dir):
    original_ingest = (ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.INDEX_DIR)
    original_mv = (mv.MANIFEST_PATH, mv.MEVZUAT_DIR)
    ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.INDEX_DIR = data_dir, mevzuat_dir, manifest_path, index_dir
    mv.MANIFEST_PATH, mv.MEVZUAT_DIR = str(manifest_path), str(mevzuat_dir)
    try:
        yield
    finally:
        ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.INDEX_DIR = original_ingest
        mv.MANIFEST_PATH, mv.MEVZUAT_DIR = original_mv


def _document_entry(document_id, file_name, kanun_no):
    return {
        "document_id": document_id,
        "file_name": file_name,
        "active": True,
        "belge_turu": "Kanun",
        "title": f"RAG Smoke Test Kanunu {document_id}",
        "short_title": document_id,
        "kanun_no": kanun_no,
        "official_source": False,
        "status": "active",
        "version": "v1",
        "jurisdiction": "TR",
        "language": "tr",
        "tags": ["smoke-test"],
        "relations": [],
        "ingest": {"enabled": True, "parser": "legal_pdf", "chunk_strategy": "legal_hierarchy", "ocr_required": False},
        "notes": None,
    }


def build_main_fixture(tmp_path):
    data_dir = tmp_path / "data"
    mevzuat_dir = data_dir / "mevzuat"
    mevzuat_dir.mkdir(parents=True)
    index_dir = tmp_path / "index"

    alpha_pdf_path = mevzuat_dir / "rag_smoke_alpha.pdf"
    beta_pdf_path = mevzuat_dir / "rag_smoke_beta.pdf"
    alpha_pdf_path.write_bytes(
        build_minimal_text_pdf(["MADDE 1- Bu kanunun amaci deterministik smoke sentinel ALPHA test ifadesini tasimaktir."])
    )
    beta_pdf_path.write_bytes(
        build_minimal_text_pdf(["MADDE 1- Bu kanunun amaci deterministik smoke sentinel BETA test ifadesini tasimaktir."])
    )

    manifest = {
        "schema_version": 1,
        "documents": [
            _document_entry("rag_smoke_doc_alpha", "rag_smoke_alpha.pdf", "9001"),
            _document_entry("rag_smoke_doc_beta", "rag_smoke_beta.pdf", "9002"),
        ],
    }
    manifest_path = data_dir / "documents.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "data_dir": data_dir,
        "mevzuat_dir": mevzuat_dir,
        "manifest_path": manifest_path,
        "index_dir": index_dir,
        "alpha_pdf_path": alpha_pdf_path,
        "beta_pdf_path": beta_pdf_path,
    }


# ================================================================
# SECTION H - blank-PDF negative proof: zero-chunk MUST raise, and
# MUST do so before any embedding call is ever attempted.
# ================================================================


class _AssertNeverCalledEmbeddingClient:
    class _Embeddings:
        def create(self, *, model, input):
            raise AssertionError(
                "embedding_client.embeddings.create() was called for a document that should "
                "have produced ZERO chunks and failed BEFORE any embedding call - "
                "'no exception raised' alone must never be treated as gate success"
            )

    @property
    def embeddings(self):
        return _AssertNeverCalledEmbeddingClient._Embeddings()


def run_blank_pdf_negative_test():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        data_dir = tmp_path / "data"
        mevzuat_dir = data_dir / "mevzuat"
        mevzuat_dir.mkdir(parents=True)
        blank_pdf_path = mevzuat_dir / "rag_smoke_blank.pdf"
        blank_pdf_path.write_bytes(build_minimal_text_pdf([]))
        manifest = {"schema_version": 1, "documents": [_document_entry("rag_smoke_doc_blank", "rag_smoke_blank.pdf", "9099")]}
        manifest_path = data_dir / "documents.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        extracted = ingest.extract_pdf_pages(blank_pdf_path)
        check(
            "blank-pdf negative fixture: real pypdf extracts zero real text",
            all(not page["text"].strip() for page in extracted),
            extracted,
        )

        with patched_source_paths(data_dir, mevzuat_dir, manifest_path, tmp_path / "index"):
            expect_raises(
                RuntimeError,
                lambda: ingest.build_bundle_snapshot(
                    embedding_client=_AssertNeverCalledEmbeddingClient(), build_attempt=0,
                ),
                "blank-pdf negative: build_bundle_snapshot() fails closed with zero real chunks",
                "a zero-chunk document must raise RuntimeError, never silently succeed",
            )


# ================================================================
# SECTION I - the real FAISS deserialize-failure diagnostic (never
# changes the gate's own FAIL verdict; never touches production code).
# ================================================================


def _diagnose_faiss_deserialize_failure(bundle_dir, original_error):
    print("DEPENDENCY GATE DIAGNOSTIC: a real faiss.deserialize_index() failure was observed "
          "on hash-VERIFIED bytes (i.e. NOT the tamper test below) - this is a genuine "
          "environment/API-compatibility question, not a bug in this test file.")
    print(f"  exception type: {type(original_error).__name__}")
    print(f"  exception: {original_error!r}")
    cause = getattr(original_error, "__cause__", None)
    if cause is not None:
        print(f"  __cause__: {type(cause).__name__}: {cause!r}")
    try:
        import faiss
        import numpy as np

        raw = (bundle_dir / "mevzuat.faiss").read_bytes()
        recovered_index = faiss.deserialize_index(np.frombuffer(raw, dtype=np.uint8).copy())
        print(
            f"  DIAGNOSTIC np.frombuffer(...).copy() variant: SUCCEEDED (ntotal={recovered_index.ntotal}) - "
            "this does NOT change the gate's FAIL verdict and does NOT modify src/retriever.py in this "
            "slice; a separate, dedicated remediation commit would be required to adopt it in production."
        )
    except Exception as copy_error:
        print(f"  DIAGNOSTIC .copy() variant: ALSO FAILED: {type(copy_error).__name__}: {copy_error!r}")


# ================================================================
# SECTION J - the full, real, synthetic E2E round trip.
# ================================================================


def run_full_e2e_round_trip():
    socket_module, original_connect, original_create_connection = _install_socket_guard()
    _install_lock_fakes()
    try:
        _probe_socket_guard_without_real_connection()
        return _run_full_e2e_round_trip_guarded()
    finally:
        _restore_lock_fakes()
        _restore_socket_guard(socket_module, original_connect, original_create_connection)


def _run_full_e2e_round_trip_guarded():
    run_blank_pdf_negative_test()

    with tempfile.TemporaryDirectory() as tmp:
        fixture = build_main_fixture(Path(tmp))

        alpha_pages = ingest.extract_pdf_pages(fixture["alpha_pdf_path"])
        beta_pages = ingest.extract_pdf_pages(fixture["beta_pdf_path"])
        check(
            "real pypdf: alpha PDF extracted text contains its own sentinel",
            any("ALPHA" in page["text"].upper() for page in alpha_pages),
            alpha_pages,
        )
        check(
            "real pypdf: beta PDF extracted text contains its own sentinel",
            any("BETA" in page["text"].upper() for page in beta_pages),
            beta_pages,
        )

        embedding_calls = []
        embedding_client = make_openai_mock_client(embedding_calls)
        principal, repo = make_principal_and_repo()

        with patched_source_paths(fixture["data_dir"], fixture["mevzuat_dir"], fixture["manifest_path"], fixture["index_dir"]):
            preview_1 = facade.preview_build(build_attempt=0, principal=principal, authz_repository=repo)
            check("preview_build: source_document_count == 3 (documents.json + 2 pdfs)", preview_1["source_document_count"] == 3, preview_1)

            build_result_1 = facade.apply_build(
                preview_1["input_digest"], allow_network=True, build_attempt=0,
                principal=principal, authz_repository=repo,
                conn_factory=lambda: FakeJournalConn(), embedding_client=embedding_client,
            )
            check("apply_build #1: bundle_version has expected shape", build_result_1.bundle_version.startswith("v_") and len(build_result_1.bundle_version) == 66)
            check("apply_build #1: NOT a replay (first-ever build)", build_result_1.replayed is False)
            manifest_1 = json.loads(Path(build_result_1.manifest_path).read_text(encoding="utf-8"))
            check("apply_build #1: manifest chunk_count == 2 (one per document)", manifest_1["chunk_count"] == 2, manifest_1)
            check("apply_build #1: real embedding call happened exactly once (single batch)", len(embedding_calls) == 1, embedding_calls)
            check(
                "apply_build #1: real embedding call used the real production model name + 2 inputs",
                embedding_calls[-1] == {"model": "text-embedding-3-small", "input_count": 2},
                embedding_calls,
            )

            preview_activate_1 = facade.preview_activate(build_result_1.bundle_version, principal=principal, authz_repository=repo)
            check("preview_activate #1: no current pointer yet", preview_activate_1["current_pointer_state"] == "none", preview_activate_1)

            activate_result_1 = facade.apply_activate(
                build_result_1.bundle_version, "none", activation_attempt=0,
                principal=principal, authz_repository=repo, conn_factory=lambda: FakeJournalConn(),
            )
            check("apply_activate #1: activated the built bundle", activate_result_1.bundle_version == build_result_1.bundle_version)
            check("apply_activate #1: previous_version is None (first activation ever)", activate_result_1.previous_version is None)

            bundle_1 = r.load_pinned_bundle(root=fixture["index_dir"])
            check("load_pinned_bundle: pinned bundle matches activated version", bundle_1.bundle_version == build_result_1.bundle_version)
            check("load_pinned_bundle: index.ntotal == 2", bundle_1.index.ntotal == 2)
            check("load_pinned_bundle: 2 documents loaded", len(bundle_1.documents) == 2)

            query_embedding_calls = []
            query_embedding_client = make_openai_mock_client(query_embedding_calls)

            def query(text, bundle):
                # `bundle` is always an explicit argument here - never a
                # value captured from an enclosing closure - so every call
                # site below is unambiguous evidence of which bundle
                # version retrieval actually ran against.
                return r.retrieve_detailed(text, top_k=5, bundle=bundle, allow_network=False, embedding_client=query_embedding_client)

            alpha_response = query("Vergi kanunu smoke sentinel alpha ifadesi ne anlama gelir?", bundle_1)
            check("retrieve: alpha query returns exactly 2 results (both chunks scored)", len(alpha_response["results"]) == 2, alpha_response["results"])
            top_alpha = alpha_response["results"][0]
            check("retrieve: alpha query top result is the ALPHA document", top_alpha["document_id"] == "rag_smoke_doc_alpha", top_alpha)
            check("retrieve: alpha query top result cites the ALPHA source file", top_alpha["source"] == "rag_smoke_alpha.pdf", top_alpha)
            check("retrieve: alpha query top result text carries the ALPHA sentinel", "ALPHA" in top_alpha["text"].upper(), top_alpha)
            check("retrieve: alpha query top result madde == '1'", top_alpha["madde"] == "1", top_alpha)

            beta_response = query("Vergi kanunu smoke sentinel beta ifadesi ne anlama gelir?", bundle_1)
            top_beta = beta_response["results"][0]
            check("retrieve: beta query top result is the BETA document", top_beta["document_id"] == "rag_smoke_doc_beta", top_beta)
            check("retrieve: beta query top result cites the BETA source file", top_beta["source"] == "rag_smoke_beta.pdf", top_beta)
            check("retrieve: beta query top result text carries the BETA sentinel", "BETA" in top_beta["text"].upper(), top_beta)

            # ---- second bundle build (attempt=1): a corpus that is
            # GENUINELY distinguishable from bundle #1's, not merely a
            # different `build_attempt` - two builds over identical source
            # content produce byte-identical artifacts (deterministic
            # embeddings + a deterministic pipeline), which would make a
            # wrong-bundle retrieval bug undetectable by result content
            # alone. A third document carrying a GAMMA sentinel that
            # exists in no bundle #1 chunk is added to the corpus before
            # this build, which is deliberately NOT activated yet. ----
            gamma_pdf_path = fixture["mevzuat_dir"] / "rag_smoke_gamma.pdf"
            gamma_pdf_path.write_bytes(
                build_minimal_text_pdf(["MADDE 1- Bu kanunun amaci deterministik smoke sentinel GAMMA test ifadesini tasimaktir."])
            )
            manifest_for_build_2 = json.loads(fixture["manifest_path"].read_text(encoding="utf-8"))
            manifest_for_build_2["documents"].append(_document_entry("rag_smoke_doc_gamma", "rag_smoke_gamma.pdf", "9003"))
            fixture["manifest_path"].write_text(json.dumps(manifest_for_build_2, ensure_ascii=False, indent=2), encoding="utf-8")

            preview_2 = facade.preview_build(build_attempt=1, principal=principal, authz_repository=repo)
            check(
                "preview_build #2: source_document_count == 4 (documents.json + 3 pdfs, GAMMA added)",
                preview_2["source_document_count"] == 4, preview_2,
            )
            build_result_2 = facade.apply_build(
                preview_2["input_digest"], allow_network=True, build_attempt=1,
                principal=principal, authz_repository=repo,
                conn_factory=lambda: FakeJournalConn(), embedding_client=embedding_client,
            )
            check("apply_build #2: different build_attempt -> different bundle_version", build_result_2.bundle_version != build_result_1.bundle_version)
            manifest_2 = json.loads(Path(build_result_2.manifest_path).read_text(encoding="utf-8"))
            check("apply_build #2: manifest chunk_count == 3 (alpha+beta+gamma)", manifest_2["chunk_count"] == 3, manifest_2)
            check(
                "apply_build #2: artifact hashes differ from build #1 (real corpus difference, not merely a different build_attempt)",
                manifest_1["artifacts"] != manifest_2["artifacts"],
                {"manifest_1_artifacts": manifest_1["artifacts"], "manifest_2_artifacts": manifest_2["artifacts"]},
            )
            check(
                "apply_build #2: mevzuat.faiss artifact bytes differ from build #1",
                manifest_1["artifacts"]["mevzuat.faiss"]["sha256"] != manifest_2["artifacts"]["mevzuat.faiss"]["sha256"],
                {"build_1_faiss": manifest_1["artifacts"]["mevzuat.faiss"], "build_2_faiss": manifest_2["artifacts"]["mevzuat.faiss"]},
            )

            # ---- the PREVIOUSLY activated bundle must still work while #2 exists, unactivated ----
            still_bundle_1 = r.load_pinned_bundle(root=fixture["index_dir"])
            check("continuity: pointer still names bundle #1 while bundle #2 exists un-activated", still_bundle_1.bundle_version == build_result_1.bundle_version)
            still_alpha_response = query("Vergi kanunu smoke sentinel alpha ifadesi ne anlama gelir?", still_bundle_1)
            check(
                "continuity: bundle #1 retrieval still correct while bundle #2 exists un-activated",
                still_alpha_response["results"][0]["document_id"] == "rag_smoke_doc_alpha",
                still_alpha_response["results"],
            )

            # ---- activate bundle #2 - the pointer must now flip ----
            activate_result_2 = facade.apply_activate(
                build_result_2.bundle_version, build_result_1.bundle_version, activation_attempt=0,
                principal=principal, authz_repository=repo, conn_factory=lambda: FakeJournalConn(),
            )
            check("apply_activate #2: previous_version correctly names bundle #1", activate_result_2.previous_version == build_result_1.bundle_version)

            try:
                bundle_2 = r.load_pinned_bundle(root=fixture["index_dir"])
            except r.RagBundleError as error:
                check("load_pinned_bundle (post-second-activation): unexpected failure on hash-verified bytes", False, repr(error))
                _diagnose_faiss_deserialize_failure(fixture["index_dir"] / build_result_2.bundle_version, error)
                return False
            check("post-second-activation: pointer now names bundle #2", bundle_2.bundle_version == build_result_2.bundle_version)
            check("post-second-activation: bundle #2 index.ntotal == 3 (alpha+beta+gamma)", bundle_2.index.ntotal == 3)
            check("post-second-activation: bundle #2 has 3 documents loaded", len(bundle_2.documents) == 3)

            # ---- explicit bundle #2 retrieval evidence: `bundle=bundle_2`
            # is passed explicitly, and the query targets the GAMMA
            # sentinel that exists in no bundle #1 chunk, so retrieval
            # against the wrong bundle would be caught by result content,
            # not merely by comparing version labels. ----
            gamma_response = query("Vergi kanunu smoke sentinel gamma ifadesi ne anlama gelir?", bundle_2)
            check("retrieve (bundle #2, explicit): gamma query returns exactly 3 results (alpha+beta+gamma chunks scored)", len(gamma_response["results"]) == 3, gamma_response["results"])
            top_gamma = gamma_response["results"][0]
            check("retrieve (bundle #2, explicit): gamma query top result is the GAMMA document", top_gamma["document_id"] == "rag_smoke_doc_gamma", top_gamma)
            check("retrieve (bundle #2, explicit): gamma query top result cites the GAMMA source file", top_gamma["source"] == "rag_smoke_gamma.pdf", top_gamma)
            check("retrieve (bundle #2, explicit): gamma query top result text carries the GAMMA sentinel", "GAMMA" in top_gamma["text"].upper(), top_gamma)
            alpha_via_bundle_2 = query("Vergi kanunu smoke sentinel alpha ifadesi ne anlama gelir?", bundle_2)
            check(
                "retrieve (bundle #2, explicit): alpha query against bundle #2 still finds the ALPHA document (bundle #2 carries alpha+beta+gamma)",
                alpha_via_bundle_2["results"][0]["document_id"] == "rag_smoke_doc_alpha",
                alpha_via_bundle_2["results"],
            )

            # ---- previous-pin continuity: the ORIGINAL bundle_1 object
            # (loaded before bundle #2 even existed) must keep answering
            # queries correctly after the pointer has flipped to bundle #2
            # - and must never surface the GAMMA-only content that exists
            # solely in bundle #2's corpus. ----
            gamma_via_old_pin = query("Vergi kanunu smoke sentinel gamma ifadesi ne anlama gelir?", bundle_1)
            check(
                "previous-pin continuity: the ORIGINAL bundle_1 object still answers queries after the pointer flipped to bundle #2",
                len(gamma_via_old_pin["results"]) == 2,
                gamma_via_old_pin["results"],
            )
            check(
                "previous-pin continuity: the ORIGINAL bundle_1 object never surfaces the GAMMA-only document (it has no such chunk)",
                all(res["document_id"] != "rag_smoke_doc_gamma" and "GAMMA" not in res["text"].upper() for res in gamma_via_old_pin["results"]),
                gamma_via_old_pin["results"],
            )
            alpha_via_old_pin_after_swap = query("Vergi kanunu smoke sentinel alpha ifadesi ne anlama gelir?", bundle_1)
            check(
                "previous-pin continuity: the ORIGINAL bundle_1 object still retrieves the ALPHA document correctly after the pointer flipped to bundle #2",
                alpha_via_old_pin_after_swap["results"][0]["document_id"] == "rag_smoke_doc_alpha",
                alpha_via_old_pin_after_swap["results"],
            )

            # ---- tamper + hash-before-deserialize mechanical proof ----
            tampered_path = fixture["index_dir"] / build_result_2.bundle_version / "mevzuat.faiss"
            original_bytes = tampered_path.read_bytes()
            tampered_path.write_bytes(original_bytes[:-1] + bytes([original_bytes[-1] ^ 0xFF]))

            import faiss as _faiss_module

            original_deserialize_index = _faiss_module.deserialize_index

            def _must_not_be_called(*args, **kwargs):
                raise AssertionError(
                    "faiss.deserialize_index() was called on a bundle whose artifact hash check "
                    "should have failed BEFORE any deserialize attempt - hash-before-deserialize "
                    "ordering is violated"
                )

            _faiss_module.deserialize_index = _must_not_be_called
            try:
                expect_raises(
                    r.RagArtifactHashMismatchError,
                    lambda: r.load_pinned_bundle(root=fixture["index_dir"]),
                    "tamper test: corrupted mevzuat.faiss is rejected via RagArtifactHashMismatchError",
                    "and faiss.deserialize_index() must never be reached for a hash-mismatched artifact",
                )
            finally:
                _faiss_module.deserialize_index = original_deserialize_index

        return True


# ================================================================
# SECTION K - subprocess meta-test (unknown env value) and the
# per-process gate orchestration.
# ================================================================


def test_unknown_gate_value_subprocess_rejected():
    env = dict(os.environ)
    env[GATE_ENV_VAR] = "totally_invalid_value_xyz"
    env[CHILD_ENV_VAR] = "1"
    result = subprocess.run(
        [sys.executable, str(THIS_FILE)], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180, env=env,
    )
    check("subprocess: unknown gate value -> nonzero exit code", result.returncode != 0, f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}")
    combined = (result.stdout + result.stderr).lower()
    check("subprocess: unknown gate value -> rejection is mentioned in output", "unknown" in combined, result.stdout + result.stderr)
    check("subprocess: unknown gate value -> no PASS marker was printed", "dependency gate: pass" not in combined, result.stdout)


def test_pass_marker_never_precedes_final_invariance_failure_subprocess():
    """Spawns a real child process that runs the real, full E2E round
    trip to completion in require mode, then forces the FINAL data/index
    byte-invariance check (only) to fail, and proves the child: exits
    nonzero, never prints the PASS marker anywhere in its output, prints
    the invariance check's own FAIL line, and reports at least one real
    failure in its own summary line. Skipped (informationally, uncounted)
    when this process's own environment is not fully dependency-ready,
    since a meaningful proof here requires a genuinely successful E2E run
    to force a later failure against - a dependency-broken environment's
    require-mode hard-fail path is already covered elsewhere in this
    file, and is not what this proof is about."""
    if not _environment_is_fully_dependency_ready():
        skip_info(
            "gate: PASS-marker-vs-final-invariance-failure subprocess proof",
            "this process's own environment is not fully dependency-ready (see package "
            "classification above) - this proof requires a REAL, successful full E2E run "
            "to force a failure against, at the FINAL step; re-run with "
            f"{GATE_ENV_VAR}=require in an environment where all required packages are "
            "ok_pinned (e.g. this repository's own root .venv) to exercise it",
        )
        return

    env = dict(os.environ)
    env[GATE_ENV_VAR] = "require"
    env[CHILD_ENV_VAR] = "1"
    env[FORCE_INVARIANCE_FAILURE_ENV_VAR] = "1"
    result = subprocess.run(
        [sys.executable, str(THIS_FILE)], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180, env=env,
    )
    combined = result.stdout + result.stderr
    check(
        "subprocess: forced final invariance failure -> nonzero exit code",
        result.returncode != 0,
        f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}",
    )
    check(
        "subprocess: forced final invariance failure -> no DEPENDENCY GATE: PASS marker anywhere in output",
        "DEPENDENCY GATE: PASS" not in combined,
        combined,
    )
    check(
        "subprocess: forced final invariance failure -> the invariance check's own FAIL line is present",
        "FAIL repo data/ and index/ byte-invariance across this entire run" in combined,
        combined,
    )
    check(
        "subprocess: forced final invariance failure -> summary line reports at least one real failure",
        _summary_reports_at_least_one_failure(combined),
        combined,
    )


def run_gate_for_current_process():
    """Classifies the environment and, if ready, runs the full E2E round
    trip. The return value tells the caller whether the gate reached a
    genuinely successful E2E completion with zero new failures - it is
    NOT by itself sufficient to justify printing the PASS marker (see
    `run_self_test()`, which also requires the FINAL data/index
    byte-invariance check - run strictly after this function returns -
    to have passed, and checks the TOTAL failure count, before ever
    printing that marker)."""
    mode = os.environ.get(GATE_ENV_VAR, "")
    print(f"\n{GATE_ENV_VAR}={mode!r}")
    if mode not in ("", "require"):
        check(f"gate: unknown {GATE_ENV_VAR} value is rejected fail-closed", False, f"got {mode!r} - not a silent developer-mode fallback")
        return False

    classifications = classify_required_packages()

    for info_pkg in INFORMATIONAL_PACKAGES:
        try:
            info_version = importlib_metadata.version(info_pkg["dist"])
        except importlib_metadata.PackageNotFoundError:
            info_version = None
        print(f"  [informational, not a gate condition] {info_pkg['dist']}: metadata_version={info_version!r}")

    print("  package classification:")
    for c in classifications:
        print(
            f"    {c['dist']}: classification={c['classification']} "
            f"metadata_version={c['metadata_version']!r} pin={c['pin_version']!r} "
            f"import_ok={c['import_ok']} - {c['detail']}"
        )

    outcome = decide_gate_outcome(classifications, mode)

    for c in outcome["hard_fail"]:
        check(f"dependency gate: {c['dist']} environment defect ({c['classification']})", False, c["detail"])
    for c in outcome["missing"]:
        if outcome["require_mode"]:
            check(f"dependency gate: {c['dist']} required but not installed here (require mode)", False, c["detail"])
        else:
            skip_info(f"dependency gate: {c['dist']} not installed in this environment", c["detail"])

    if not outcome["ready"]:
        return False

    failed_before_e2e = failed
    e2e_ok = run_full_e2e_round_trip()
    return e2e_ok and failed == failed_before_e2e


def run_self_test():
    print(f"sys.executable: {sys.executable}")
    print(f"python: {sys.version} on {sys.platform}")

    before_manifest = snapshot_repo_manifest()

    test_decide_gate_outcome_all_ok_ready_in_both_modes()
    test_decide_gate_outcome_missing_dependency_dev_vs_require()
    test_decide_gate_outcome_metadata_present_import_broken_fails_both_modes()
    test_decide_gate_outcome_version_mismatch_fails_both_modes()
    test_decide_gate_outcome_metadata_missing_import_ok_fails_both_modes()

    if os.environ.get(CHILD_ENV_VAR) != "1":
        test_unknown_gate_value_subprocess_rejected()
        test_pass_marker_never_precedes_final_invariance_failure_subprocess()

    gate_eligible_for_pass_marker = run_gate_for_current_process()

    after_manifest = snapshot_repo_manifest()
    check("repo data/ and index/ byte-invariance across this entire run", before_manifest == after_manifest)

    print(f"\n{passed} passed, {failed} failed, {informational_skips} informational skips")

    # The PASS marker is the LAST thing this gate can ever print: it
    # requires both a genuinely successful E2E completion and the FINAL
    # data/index byte-invariance check (above) to have passed, and it
    # checks the TOTAL failure count - not just failures introduced
    # during the E2E round trip - before ever printing it.
    if gate_eligible_for_pass_marker and failed == 0:
        print("\nDEPENDENCY GATE: PASS")

    return failed == 0


if __name__ == "__main__":
    _inject_fake_invariance_drift_if_requested()
    ok = run_self_test()
    sys.exit(0 if ok else 1)
