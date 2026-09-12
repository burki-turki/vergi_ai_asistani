# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION - isolated tests for
# ui/services/rag_bundle_mutation_facade.py AND
# ui/services/rag_bundle_mutation_adapters.py (fake journal conn, fake
# global-resource session locks, in-memory global authz, a temp
# index/ directory - NEVER the real repo `index/` tree). Mirrors
# `test_generation_mutation_facade_isolated.py`'s established
# FakeJournalConn/on-acquire-hook shapes (independent copy).
#
# Run: python -m ui.tests.test_rag_bundle_mutation_facade_isolated
# ============================================================

import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ui.services import mutation_lock as ml                          # noqa: E402
from ui.services import mutation_registry as mr                      # noqa: E402
from ui.services import global_authz as ga                           # noqa: E402
from ui.services import rag_bundle_mutation_facade as facade         # noqa: E402
from ui.services import rag_bundle_mutation_adapters as adapters     # noqa: E402
from ui.services.authz import Principal                              # noqa: E402

import ingest  # noqa: E402

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
    except exc_type as error:
        check(label, True)
        return error
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {type(error).__name__}: {error!r}")
        return None
    else:
        check(label, False, f"{detail} - no exception raised")
        return None


# ----------------------------------------------------------------
# Fake mutation.mutation_journal.
# ----------------------------------------------------------------

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

        # RAG BUNDLE FOUNDATION: the INNER (under-lock) authz check
        # reuses the SAME real connection that holds the session lock
        # (valid - a real psycopg connection can query any schema);
        # this fake conn therefore also fakes the `iam.*` reads
        # `PostgresGlobalResourceAuthzRepository` issues, seeded from
        # `self._conn.iam_users`/`self._conn.iam_grants`.
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
                row["resource_key"] == resource_key
                and row["state"] in ("prepared", "executing", "reconciliation_required")
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
        # user_id -> {"authz_version": int, "disabled": bool} - fully
        # permissive by default (every user_id in [1, 50) is active,
        # authz_version=1) since the specific authz-DENIAL scenarios in
        # this file are all caught by the OUTER (in-memory) authz check
        # before any connection is opened, never by this inner fake.
        self.iam_users = iam_users if iam_users is not None else {uid: {"authz_version": 1, "disabled": False} for uid in range(1, 50)}
        # {(user_id, resource, capability)} - permissive-by-default for
        # every capability, same rationale as iam_users above.
        self.iam_grants = iam_grants if iam_grants is not None else {
            (uid, "rag_index", cap) for uid in range(1, 50) for cap in ("inspect", "build", "activate")
        }

    def cursor(self):
        return FakeJournalCursor(self)

    def close(self):
        self.closed = True


def snapshot_to_entry(table_row) -> mr.JournalEntrySnapshot:
    return mr.JournalEntrySnapshot(
        journal_id=table_row["id"], resource_key=table_row["resource_key"],
        action_family=table_row["action_family"], target_ref=table_row["target_ref"],
        target_state=table_row["target_state"], pre_hash=table_row["pre_hash"],
        pre_revision=table_row["pre_revision"], expected_post_hash=None, state=table_row["state"],
        idempotency_key=table_row["idempotency_key"], request_fingerprint=table_row["request_fingerprint"],
        actor_label=table_row["actor_label"],
    )


# ----------------------------------------------------------------
# Fake global session locks with an injectable on-acquire hook.
# ----------------------------------------------------------------

_lock_calls = []
_on_acquire_hooks = []
_original_acquire = ml.acquire_global_lock_session
_original_release = ml.release_lock_session


def _fake_acquire(conn, resource_key):
    _lock_calls.append(("acquire", resource_key))
    for hook in list(_on_acquire_hooks):
        hook(resource_key)
    return 9999


def _fake_release(conn, advisory_lock_id):
    _lock_calls.append(("release", advisory_lock_id))
    return True


# ----------------------------------------------------------------
# Fixture data/index tree + fake embedding client.
# ----------------------------------------------------------------

class FakeEmbeddingClient:
    def __init__(self, dimension=4):
        self.dimension = dimension
        self.calls = 0

    class _Embeddings:
        def __init__(self, outer):
            self._outer = outer

        def create(self, *, model, input):
            self._outer.calls += 1
            batch = input if isinstance(input, list) else [input]
            vectors = [[float((i + 1) * (j + 1)) for j in range(self._outer.dimension)] for i in range(len(batch))]

            class _Resp:
                pass

            class _Item:
                def __init__(self, e):
                    self.embedding = e

            resp = _Resp()
            resp.data = [_Item(v) for v in vectors]
            return resp

    @property
    def embeddings(self):
        return FakeEmbeddingClient._Embeddings(self)


def fake_pdf_page_extractor(pdf_path):
    return [{"page": 1, "text": "MADDE 1- test."}]


def make_snapshot_builder(*, embedding_calls_tracker=None):
    """A test-only stand-in for `ingest.build_bundle_snapshot` that
    never imports faiss/numpy - produces deterministic, hashable
    synthetic artifact bytes purely from the (already faiss/numpy-free)
    compute_source_manifest()/build_pipeline_config() outputs, so this
    entire test file runs correctly in an environment without faiss/
    numpy installed."""

    def builder(*, embedding_client=None, pdf_page_extractor=None, build_attempt=0):
        if embedding_calls_tracker is not None:
            embedding_calls_tracker.append(1)
        source_manifest = ingest.compute_source_manifest()
        pipeline_config = ingest.build_pipeline_config()
        chunk_count = 3
        embedding_dimension = 4
        payload_seed = json.dumps({"sm": source_manifest, "ba": build_attempt}, sort_keys=True).encode("utf-8")
        faiss_bytes = b"FAKEFAISS:" + hashlib.sha256(payload_seed + b"faiss").digest()
        documents_bytes = b"FAKEPKL:" + hashlib.sha256(payload_seed + b"pkl").digest()
        config_bytes = b"FAKECFG:" + hashlib.sha256(payload_seed + b"cfg").digest()
        return {
            "source_manifest": source_manifest,
            "pipeline_config": pipeline_config,
            "build_attempt": build_attempt,
            "chunk_count": chunk_count,
            "embedding_dimension": embedding_dimension,
            "artifacts": {
                "mevzuat.faiss": faiss_bytes,
                "documents.pkl": documents_bytes,
                "config.json": config_bytes,
            },
        }

    return builder


def make_data_fixture(tmp_path: Path):
    data_dir = tmp_path / "data"
    mevzuat_dir = data_dir / "mevzuat"
    mevzuat_dir.mkdir(parents=True)
    (mevzuat_dir / "doc_0.pdf").write_bytes(b"fake pdf bytes")
    documents = [{
        "document_id": "doc_0", "file_name": "doc_0.pdf", "active": True, "status": "yururlukte",
        "ingest": {"enabled": True, "parser": "legal_pdf", "chunk_strategy": "legal_hierarchy"},
    }]
    (data_dir / "documents.json").write_text(json.dumps({"documents": documents}), encoding="utf-8")
    index_dir = tmp_path / "index"
    return data_dir, mevzuat_dir, data_dir / "documents.json", index_dir


class Fixture:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        self.data_dir, self.mevzuat_dir, self.manifest_path, self.index_dir = make_data_fixture(tmp_path)
        self._original_ingest_paths = (ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.INDEX_DIR)
        ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.INDEX_DIR = (
            self.data_dir, self.mevzuat_dir, self.manifest_path, self.index_dir,
        )

    def cleanup(self):
        ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.INDEX_DIR = self._original_ingest_paths
        self._tmp.cleanup()


def make_principal_and_repo(user_id=5, *, grants=("inspect", "build", "activate")):
    principal = Principal(user_id=user_id, session_id=0, role_version_at_issue=1)
    repo = ga.InMemoryGlobalResourceAuthzRepository()
    repo.sessions[user_id] = ga._authz.SessionRecord(user_id=user_id, current_authz_version=1, disabled=False)
    for capability in grants:
        repo.grants.add((user_id, "rag_index", capability))
    return principal, repo


def install_fakes():
    ml.acquire_global_lock_session = _fake_acquire
    ml.release_lock_session = _fake_release


def restore_fakes():
    ml.acquire_global_lock_session = _original_acquire
    ml.release_lock_session = _original_release


def reset_hooks():
    _lock_calls.clear()
    _on_acquire_hooks.clear()


# ================================================================
# preview_build
# ================================================================

def test_preview_build_zero_network_and_correct_digest():
    fx = Fixture()
    try:
        principal, repo = make_principal_and_repo()
        preview = facade.preview_build(build_attempt=0, principal=principal, authz_repository=repo)
        check("preview_build: input_digest present", isinstance(preview["input_digest"], str) and len(preview["input_digest"]) == 64)
        check("preview_build: source_document_count == 2", preview["source_document_count"] == 2)
        preview2 = facade.preview_build(build_attempt=0, principal=principal, authz_repository=repo)
        check("preview_build: deterministic across calls", preview["input_digest"] == preview2["input_digest"])
        preview3 = facade.preview_build(build_attempt=1, principal=principal, authz_repository=repo)
        check("preview_build: different build_attempt -> different input_digest", preview["input_digest"] != preview3["input_digest"])
    finally:
        fx.cleanup()


def test_preview_build_authz_denied():
    fx = Fixture()
    try:
        principal, repo = make_principal_and_repo(grants=("inspect",))
        expect_raises(
            ga.GlobalResourceAccessDeniedError,
            lambda: facade.preview_build(build_attempt=0, principal=principal, authz_repository=repo),
            "preview_build: denied without build grant",
        )
    finally:
        fx.cleanup()


# ================================================================
# apply_build
# ================================================================

def do_apply_build(principal, repo, *, build_attempt=0, expected_input_digest=None, allow_network=True, conn=None, builder=None):
    conn = conn if conn is not None else FakeJournalConn()

    def conn_factory():
        return conn

    if expected_input_digest is None:
        preview = facade.preview_build(build_attempt=build_attempt, principal=principal, authz_repository=repo)
        expected_input_digest = preview["input_digest"]

    builder = builder if builder is not None else make_snapshot_builder()
    result = facade.apply_build(
        expected_input_digest, allow_network=allow_network, build_attempt=build_attempt,
        principal=principal, authz_repository=repo, conn_factory=conn_factory, snapshot_builder=builder,
    )
    return result, conn


def test_apply_build_requires_allow_network():
    fx = Fixture()
    try:
        principal, repo = make_principal_and_repo()
        preview = facade.preview_build(build_attempt=0, principal=principal, authz_repository=repo)
        expect_raises(
            facade.RagBundleArgumentError,
            lambda: facade.apply_build(
                preview["input_digest"], allow_network=False, principal=principal, authz_repository=repo,
                conn_factory=lambda: FakeJournalConn(),
            ),
            "apply_build: allow_network=False rejected unconditionally",
        )
    finally:
        fx.cleanup()


def test_apply_build_stale_input_digest():
    fx = Fixture()
    try:
        principal, repo = make_principal_and_repo()
        expect_raises(
            facade.RagBundleStaleInputError,
            lambda: facade.apply_build(
                "0" * 64, allow_network=True, principal=principal, authz_repository=repo,
                conn_factory=lambda: FakeJournalConn(),
            ),
            "apply_build: stale expected_input_digest rejected",
        )
    finally:
        fx.cleanup()


def test_apply_build_success_full_chain():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result, conn = do_apply_build(principal, repo)
        check("apply_build: bundle_version well-shaped", facade._BUNDLE_VERSION_PATTERN.match(result.bundle_version) is not None)
        check("apply_build: bundle_dir exists", Path(result.bundle_dir).is_dir())
        check("apply_build: manifest_path exists", Path(result.manifest_path).is_file())
        check("apply_build: audit_path exists", Path(result.audit_path).is_file())
        check("apply_build: replayed=False on fresh build", result.replayed is False)
        check("apply_build: journal row completed", conn.table[-1]["state"] == "completed")
        check("apply_build: observed_post_hash == bundle_version", conn.table[-1]["observed_post_hash"] == result.bundle_version)
        check("apply_build: lock acquired and released", _lock_calls == [("acquire", "global:rag_index"), ("release", 9999)])

        manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
        identity_core = {k: v for k, v in manifest.items() if k != "bundle_version"}
        check("apply_build: manifest self-consistent", facade._bundle_version_for(identity_core) == result.bundle_version)
        for name in facade.RAG_BUNDLE_ARTIFACT_NAMES:
            artifact_path = Path(result.bundle_dir) / name
            raw = artifact_path.read_bytes()
            entry = manifest["artifacts"][name]
            check(f"apply_build: artifact {name} hash matches", hashlib.sha256(raw).hexdigest() == entry["sha256"])

        audit = json.loads(Path(result.audit_path).read_text(encoding="utf-8"))
        check("apply_build: audit carries mutation_idempotency_key", audit.get("mutation_idempotency_key") == conn.table[-1]["idempotency_key"])
        check("apply_build: audit carries input_digest == journal pre_revision", audit.get("input_digest") == conn.table[-1]["pre_revision"])
    finally:
        restore_fakes()
        fx.cleanup()


def test_apply_build_safe_replay_does_not_reinvoke_builder():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        conn = FakeJournalConn()
        calls = []
        builder = make_snapshot_builder(embedding_calls_tracker=calls)
        result1, _ = do_apply_build(principal, repo, conn=conn, builder=builder)
        check("safe_replay: first apply built once", len(calls) == 1)
        result2, _ = do_apply_build(principal, repo, conn=conn, builder=builder)
        check("safe_replay: second apply did NOT re-invoke builder", len(calls) == 1)
        check("safe_replay: replayed=True on second call", result2.replayed is True)
        check("safe_replay: same bundle_version", result1.bundle_version == result2.bundle_version)
    finally:
        restore_fakes()
        fx.cleanup()


def test_apply_build_source_drift_under_lock():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()

        def mutate_source(resource_key):
            (fx.mevzuat_dir / "doc_0.pdf").write_bytes(b"MUTATED CONTENT")

        _on_acquire_hooks.append(mutate_source)
        conn = FakeJournalConn()
        expect_raises(
            facade.SourceDriftDetectedError,
            lambda: do_apply_build(principal, repo, conn=conn)[0],
            "apply_build: source drift under lock -> zero journal writes",
        )
        check("apply_build: zero journal rows after drift rejection", len(conn.table) == 0)
    finally:
        restore_fakes()
        fx.cleanup()


def test_apply_build_version_collision():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        preview = facade.preview_build(build_attempt=0, principal=principal, authz_repository=repo)
        input_digest = preview["input_digest"]

        # Predict the exact bundle_version this builder+inputs would
        # produce, then pre-seed a DIFFERENT-content directory there.
        probe_builder = make_snapshot_builder()
        snapshot = probe_builder(build_attempt=0)
        artifact_hashes = {
            name: {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
            for name, raw in snapshot["artifacts"].items()
        }
        identity_core = facade._build_identity_core(
            snapshot["source_manifest"], snapshot["pipeline_config"], 0,
            snapshot["chunk_count"], snapshot["embedding_dimension"], artifact_hashes,
        )
        predicted_version = facade._bundle_version_for(identity_core)
        fx.index_dir.mkdir(parents=True, exist_ok=True)
        colliding_dir = fx.index_dir / predicted_version
        colliding_dir.mkdir()
        (colliding_dir / "manifest.json").write_text('{"different": true}', encoding="utf-8")
        (colliding_dir / "mevzuat.faiss").write_bytes(b"x")
        (colliding_dir / "documents.pkl").write_bytes(b"x")
        (colliding_dir / "config.json").write_bytes(b"x")

        conn = FakeJournalConn()
        expect_raises(
            facade.BundleVersionCollisionError,
            lambda: facade.apply_build(
                input_digest, allow_network=True, build_attempt=0,
                principal=principal, authz_repository=repo, conn_factory=lambda: conn,
                snapshot_builder=probe_builder,
            ),
            "apply_build: version collision with differing bytes fails closed",
        )
        check(
            "apply_build: colliding directory left untouched",
            (colliding_dir / "manifest.json").read_text(encoding="utf-8") == '{"different": true}',
        )
    finally:
        restore_fakes()
        fx.cleanup()


# ================================================================
# preview_activate / apply_activate
# ================================================================

def test_activate_full_flow_and_already_active_and_stale():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        build_result, _conn = do_apply_build(principal, repo)

        preview = facade.preview_activate(build_result.bundle_version, principal=principal, authz_repository=repo)
        check("preview_activate: has_build_audit=True", preview["has_build_audit"] is True)
        check("preview_activate: current_pointer_state=none (nothing active yet)", preview["current_pointer_state"] == "none")

        activate_conn = FakeJournalConn()
        activate_result = facade.apply_activate(
            build_result.bundle_version, "none",
            principal=principal, authz_repository=repo, conn_factory=lambda: activate_conn,
        )
        check("apply_activate: bundle_version matches", activate_result.bundle_version == build_result.bundle_version)
        check("apply_activate: previous_version is None (first activation)", activate_result.previous_version is None)
        check("apply_activate: pointer file written", Path(activate_result.pointer_path).is_file())
        pointer_data = json.loads(Path(activate_result.pointer_path).read_text(encoding="utf-8"))
        check("apply_activate: pointer content matches", pointer_data["current_version"] == build_result.bundle_version)
        check("apply_activate: journal completed", activate_conn.table[-1]["state"] == "completed")

        expect_raises(
            facade.AlreadyActiveError,
            lambda: facade.apply_activate(
                build_result.bundle_version, build_result.bundle_version,
                principal=principal, authz_repository=repo, conn_factory=lambda: FakeJournalConn(),
            ),
            "apply_activate: already-active bundle refused",
        )

        expect_raises(
            facade.StaleCurrentVersionError,
            lambda: facade.apply_activate(
                build_result.bundle_version, "none",
                principal=principal, authz_repository=repo, conn_factory=lambda: FakeJournalConn(),
            ),
            "apply_activate: stale expected_current_version refused",
        )
    finally:
        restore_fakes()
        fx.cleanup()


def test_activate_refused_without_build_audit():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        # Hand-craft a self-consistent bundle with NO build audit.
        core = facade._build_identity_core(
            ingest.compute_source_manifest(), ingest.build_pipeline_config(), 0, 1, 4,
            {name: {"sha256": "a" * 64, "size_bytes": 0} for name in facade.RAG_BUNDLE_ARTIFACT_NAMES},
        )
        bundle_version = facade._bundle_version_for(core)
        manifest = dict(core)
        manifest["bundle_version"] = bundle_version
        bundle_dir = fx.index_dir / bundle_version
        bundle_dir.mkdir(parents=True)
        (bundle_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for name in facade.RAG_BUNDLE_ARTIFACT_NAMES:
            (bundle_dir / name).write_bytes(b"")

        expect_raises(
            facade.BundleNotBuildAuditedError,
            lambda: facade.apply_activate(
                bundle_version, "none", principal=principal, authz_repository=repo,
                conn_factory=lambda: FakeJournalConn(),
            ),
            "apply_activate: refused without a build audit",
        )
    finally:
        restore_fakes()
        fx.cleanup()


def test_activate_authz_denied_zero_lock():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo(grants=("inspect", "build"))
        expect_raises(
            ga.GlobalResourceAccessDeniedError,
            lambda: facade.apply_activate(
                "v_" + "a" * 64, "none", principal=principal, authz_repository=repo,
                conn_factory=lambda: FakeJournalConn(),
            ),
            "apply_activate: denied without activate grant",
        )
        check("apply_activate: outer denial takes zero lock", _lock_calls == [])
    finally:
        restore_fakes()
        fx.cleanup()


# ================================================================
# reconciliation adapters
# ================================================================

def test_build_reconciliation_post_state_verified():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result, conn = do_apply_build(principal, repo)
        entry = snapshot_to_entry(conn.table[-1])
        evidence = adapters.BuildReconciliationAdapter().gather_evidence(entry)
        check("reconcile_build: post_state_verified=True", evidence.post_state_verified is True)
        check("reconcile_build: observed_post_hash == bundle_version", evidence.observed_post_hash == result.bundle_version)
    finally:
        restore_fakes()
        fx.cleanup()


def test_build_reconciliation_pre_state_unchanged_when_no_audit():
    fx = Fixture()
    try:
        principal, repo = make_principal_and_repo()
        preview = facade.preview_build(build_attempt=0, principal=principal, authz_repository=repo)
        source_manifest, pipeline_config, source_digest, input_digest = facade._freeze_pre_build_state(0)
        fake_entry = mr.JournalEntrySnapshot(
            journal_id=1, resource_key=facade.RESOURCE_KEY, action_family=facade.BUILD_ACTION_FAMILY,
            target_ref=facade.BUILD_TARGET_REF, target_state=facade.BUILD_TARGET_STATE,
            pre_hash=source_digest, pre_revision=input_digest, expected_post_hash=None, state="executing",
            idempotency_key="deadbeef" * 8, request_fingerprint="cafebabe" * 8, actor_label="5",
        )
        evidence = adapters.BuildReconciliationAdapter().gather_evidence(fake_entry)
        check("reconcile_build: no audit -> pre_state_confirmed_unchanged=True", evidence.pre_state_confirmed_unchanged is True)
        check("reconcile_build: post_state_verified=False", evidence.post_state_verified is False)
    finally:
        fx.cleanup()


def test_build_reconciliation_dual_false_when_wrong_resource():
    entry = mr.JournalEntrySnapshot(
        journal_id=1, resource_key="case:foo", action_family=facade.BUILD_ACTION_FAMILY,
        target_ref=facade.BUILD_TARGET_REF, target_state=facade.BUILD_TARGET_STATE,
        pre_hash="x", pre_revision="y", expected_post_hash=None, state="executing",
        idempotency_key="a" * 64, request_fingerprint="b" * 64, actor_label="5",
    )
    evidence = adapters.BuildReconciliationAdapter().gather_evidence(entry)
    check("reconcile_build: wrong resource_key -> dual-false", evidence.post_state_verified is False and evidence.pre_state_confirmed_unchanged is False)


def test_activate_reconciliation_post_state_verified():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        build_result, _bconn = do_apply_build(principal, repo)
        activate_conn = FakeJournalConn()
        facade.apply_activate(
            build_result.bundle_version, "none", principal=principal, authz_repository=repo,
            conn_factory=lambda: activate_conn,
        )
        entry = snapshot_to_entry(activate_conn.table[-1])
        evidence = adapters.ActivateReconciliationAdapter().gather_evidence(entry)
        check("reconcile_activate: post_state_verified=True", evidence.post_state_verified is True)
        check("reconcile_activate: observed_post_hash matches", evidence.observed_post_hash == build_result.bundle_version)
    finally:
        restore_fakes()
        fx.cleanup()


def test_reconciliation_never_touches_network_or_writer():
    """Structural proof: neither adapter's gather_evidence ever calls
    ingest.build_bundle_snapshot (the only network/embedding entry
    point) - poison it and confirm reconciliation still works."""
    fx = Fixture()
    try:
        principal, repo = make_principal_and_repo()
        original = ingest.build_bundle_snapshot

        def poisoned(*a, **kw):
            raise AssertionError("reconciliation must never call build_bundle_snapshot()")

        ingest.build_bundle_snapshot = poisoned
        try:
            entry = mr.JournalEntrySnapshot(
                journal_id=1, resource_key=facade.RESOURCE_KEY, action_family=facade.BUILD_ACTION_FAMILY,
                target_ref=facade.BUILD_TARGET_REF, target_state=facade.BUILD_TARGET_STATE,
                pre_hash="wrong", pre_revision="wrong", expected_post_hash=None, state="executing",
                idempotency_key="a" * 64, request_fingerprint="b" * 64, actor_label="5",
            )
            evidence = adapters.BuildReconciliationAdapter().gather_evidence(entry)
            check("reconciliation: never invokes build_bundle_snapshot (poisoned OK)", True)
            check("reconciliation: dual-false for unmatched pre_hash", evidence.post_state_verified is False and evidence.pre_state_confirmed_unchanged is False)
        finally:
            ingest.build_bundle_snapshot = original
    finally:
        fx.cleanup()


# ================================================================
# TARGETED F1-F4 REMEDIATION TESTS (T1-T16) - activation identity/
# activation_attempt, W0-W6 writer/rollback ordering, build/activate
# completed-replay corroboration, build/activate audit recompute
# bindings, two-actor semantics.
# ================================================================

def make_two_bundles(principal, repo):
    """Two DISTINCT, real, self-consistent, build-audited bundles A and
    B - `build_attempt` is part of the identity-core, so two different
    attempt values on the SAME fixture sources reliably yield two
    different `bundle_version`s."""
    result_a, _conn_a = do_apply_build(principal, repo, build_attempt=0)
    result_b, _conn_b = do_apply_build(principal, repo, build_attempt=1)
    return result_a, result_b


def predicted_activate_idempotency_key(bundle_version, expected_current_version, activation_attempt, principal, repo):
    """Computes the EXACT idempotency_key `apply_activate()` will use
    internally for these exact arguments - lets a test pre-place a
    colliding audit file at the precise deterministic path (T12) or
    predict the identity used by a fault-injection scenario, without
    duplicating the facade's own hashing logic by hand."""
    preview = facade.preview_activate(
        bundle_version, activation_attempt=activation_attempt, principal=principal, authz_repository=repo,
    )
    identity_payload = facade._activation_identity_payload(
        bundle_version, preview["bundle_manifest_sha256"], expected_current_version, activation_attempt,
    )
    pre_revision = facade._compute_activation_input_digest(identity_payload)
    intent = facade.MutationIntent(
        actor_type=facade.ACTOR_TYPE, actor_ref=str(principal.user_id), resource_key=facade.RESOURCE_KEY,
        action_family=facade.ACTIVATE_ACTION_FAMILY, target_ref=f"{facade.ACTIVATE_TARGET_REF_PREFIX}{bundle_version}",
        target_state=facade.ACTIVATE_TARGET_STATE, pre_hash="unused-for-identity", pre_revision=pre_revision,
    )
    return facade._idempotency_key_of(intent)


def test_t1_reactivation_same_attempt_raises_loudly_pointer_unchanged():
    """T1: A->B->A->B, attempt=0 throughout - the final B request has
    the SAME idempotency_key/fingerprint as the FIRST B activation, so
    the coordinator safe-replays it; the NEW replay corroboration must
    reject it loudly (pointer is at A, not B) rather than silently
    reporting success."""
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, result_b = make_two_bundles(principal, repo)
        shared_conn = FakeJournalConn()

        facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)
        facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)
        facade.apply_activate(result_a.bundle_version, result_b.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)

        pointer_path = fx.index_dir.resolve() / "current_version.json"
        pointer_before = pointer_path.read_bytes()
        audit_dir = facade._activate_audit_dir(fx.index_dir.resolve())
        audit_files_before = sorted(p.name for p in audit_dir.iterdir())

        error = expect_raises(
            facade.ActivationReplayVerificationError,
            lambda: facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn),
            "T1: re-activating B with the SAME attempt=0 raises ActivationReplayVerificationError",
        )
        check("T1: error message names the activation_attempt recovery path", error is not None and "activation_attempt" in str(error) and "--activation-attempt" in str(error))
        check("T1: pointer bytes byte-unchanged after the failed replay", pointer_before == pointer_path.read_bytes())
        pointer_state, current_version = facade._read_pointer_state(fx.index_dir.resolve())
        check("T1: pointer still points at A", current_version == result_a.bundle_version)
        audit_files_after = sorted(p.name for p in audit_dir.iterdir())
        check("T1: zero new activate-audit files were written", audit_files_before == audit_files_after)
    finally:
        restore_fakes()
        fx.cleanup()


def test_t2_reactivation_new_attempt_succeeds_for_real():
    """T2: the SAME A->B->A->B sequence, but the final B request declares
    `activation_attempt=1` - a genuinely NEW idempotency identity, a
    fresh journal row, and the pointer REALLY flips to B."""
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, result_b = make_two_bundles(principal, repo)
        shared_conn = FakeJournalConn()

        facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)
        first_b = facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)
        facade.apply_activate(result_a.bundle_version, result_b.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)

        second_b = facade.apply_activate(
            result_b.bundle_version, result_a.bundle_version, activation_attempt=1,
            principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn,
        )
        check("T2: activation_attempt=1 succeeds without raising", second_b.bundle_version == result_b.bundle_version)
        check("T2: activation_attempt=1 was NOT a replay (genuinely re-executed)", second_b.replayed is False)
        pointer_state, current_version = facade._read_pointer_state(fx.index_dir.resolve())
        check("T2: pointer GENUINELY flips to B", current_version == result_b.bundle_version)

        b_rows = [row for row in shared_conn.table if row["target_ref"] == f"{facade.ACTIVATE_TARGET_REF_PREFIX}{result_b.bundle_version}"]
        check("T2: journal has two distinct B-activation rows (attempt 0 and 1)", len(b_rows) == 2 and b_rows[0]["idempotency_key"] != b_rows[1]["idempotency_key"])
        check("T2: first_b was a fresh write (not a replay)", first_b.replayed is False)
    finally:
        restore_fakes()
        fx.cleanup()


def build_activate_intent(bundle_version, expected_current_version, activation_attempt, principal, pre_hash, index_root_real):
    """Reconstructs the EXACT `MutationIntent` `apply_activate()` would
    build internally for these arguments - used ONLY to test the
    coordinator's own idempotency/replay mechanism and `_verify_
    completed_activate_replay()` DIRECTLY, bypassing `apply_activate()`
    's OWN outer, pre-lock `expected_current_version`-vs-LIVE-pointer
    freshness gate. That gate is a SEPARATE, correctly-functioning
    "stale view" protection that legitimately rejects ANY sequential
    re-call once the live pointer has moved past what the ORIGINAL
    caller's `expected_current_version` claimed (which, for a
    successful call, is true of literally every subsequent call to the
    public wrapper with the SAME arguments) - a genuine replay is a
    CONCURRENT-caller scenario (two requests reading the SAME pre-
    activation pointer state before either one's write happens), which
    is exactly what directly re-invoking the coordinator with the SAME
    intent simulates, matching how this project's other facades test
    their own coordinator-level replay paths."""
    bundle_manifest_sha256 = facade._sha256_bytes(facade._manifest_bytes_for(index_root_real, bundle_version))
    identity_payload = facade._activation_identity_payload(bundle_version, bundle_manifest_sha256, expected_current_version, activation_attempt)
    pre_revision = facade._compute_activation_input_digest(identity_payload)
    return facade.MutationIntent(
        actor_type=facade.ACTOR_TYPE, actor_ref=str(principal.user_id), resource_key=facade.RESOURCE_KEY,
        action_family=facade.ACTIVATE_ACTION_FAMILY, target_ref=f"{facade.ACTIVATE_TARGET_REF_PREFIX}{bundle_version}",
        target_state=facade.ACTIVATE_TARGET_STATE, pre_hash=pre_hash, pre_revision=pre_revision,
    )


def _writer_must_not_run():
    raise AssertionError("writer_callback must not be invoked on a genuine safe replay")


def test_t3_genuine_same_attempt_replay_full_corroboration():
    """T3: a genuine replay (same identity, nothing changed on disk) -
    full corroboration succeeds, `replayed=True`, and the writer is
    NEVER invoked. Simulated as a concurrent second caller reading the
    SAME pre-activation pointer state (see `build_activate_intent()`'s
    own docstring for why this is the correct way to exercise the
    coordinator's OWN replay path, distinct from `apply_activate()`'s
    separate outer freshness gate)."""
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, _result_b = make_two_bundles(principal, repo)
        conn = FakeJournalConn()

        first = facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn)
        rows_before = len(conn.table)
        audit_dir = facade._activate_audit_dir(fx.index_dir.resolve())
        audit_files_before = sorted(p.name for p in audit_dir.iterdir())

        index_root_real = Path(facade._index_root()).resolve(strict=True)
        intent = build_activate_intent(result_a.bundle_version, "none", 0, principal, facade._POINTER_ABSENT_SENTINEL, index_root_real)
        outcome = facade._mutation_coordinator.run_mutation(
            conn, intent, actor_user_id=principal.user_id,
            authz_callback=lambda: None, precondition_callback=lambda: None,
            writer_callback=_writer_must_not_run,
        )
        check("T3: coordinator recognizes the concurrent request as a safe replay", outcome.replayed is True)
        check("T3: genuine replay creates zero new journal rows", len(conn.table) == rows_before)

        replay_result = facade._verify_completed_activate_replay(
            outcome, intent=intent, index_root_real=index_root_real, bundle_version=result_a.bundle_version,
        )
        check("T3: genuine replay corroboration succeeds with replayed=True", replay_result.replayed is True)
        check("T3: genuine replay reports the same bundle_version", replay_result.bundle_version == first.bundle_version)
        check("T3: previous_version is derived from the bound audit (None - first activation)", replay_result.previous_version is None)
        audit_files_after = sorted(p.name for p in audit_dir.iterdir())
        check("T3: genuine replay writes zero new activate-audit files", audit_files_before == audit_files_after)
    finally:
        restore_fakes()
        fx.cleanup()


def test_t4_attempt0_replay_after_attempt1_success_is_honest():
    """T4 (§2.6 corner case - documented contract, not a bug): after
    A->B->A->B[attempt=1] succeeds (pointer genuinely at B again),
    replaying attempt=0's OWN original request (bundle_version=B,
    expected_current_version=A, activation_attempt=0 - the SAME request
    whose first successful run this project's own B[attempt=0] call
    was) now passes full corroboration TRUTHFULLY: the pointer really
    is at B, attempt=0's own audit from its first successful run is
    still on disk and bound, and the bundle still reverifies. This is
    NOT a sessile-no-op bug - the post-state claim ("B is active") is
    independently, genuinely true at the moment of this replay."""
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, result_b = make_two_bundles(principal, repo)
        shared_conn = FakeJournalConn()

        facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)
        attempt0_first = facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)
        facade.apply_activate(result_a.bundle_version, result_b.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)
        facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=1, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)

        pointer_state, current_version = facade._read_pointer_state(fx.index_dir.resolve())
        check("T4 setup: pointer is genuinely at B after attempt=1's success", current_version == result_b.bundle_version)

        index_root_real = Path(facade._index_root()).resolve(strict=True)
        attempt0_pre_hash = facade._sha256_bytes(facade._canonical_json_bytes({"current_version": result_a.bundle_version}))
        attempt0_intent = build_activate_intent(result_b.bundle_version, result_a.bundle_version, 0, principal, attempt0_pre_hash, index_root_real)
        outcome = facade._mutation_coordinator.run_mutation(
            shared_conn, attempt0_intent, actor_user_id=principal.user_id,
            authz_callback=lambda: None, precondition_callback=lambda: None,
            writer_callback=_writer_must_not_run,
        )
        check("T4: attempt=0's OWN row is recognized as a safe replay", outcome.replayed is True)
        replay_result = facade._verify_completed_activate_replay(
            outcome, intent=attempt0_intent, index_root_real=index_root_real, bundle_version=result_b.bundle_version,
        )
        check("T4: attempt=0's replay NOW corroborates truthfully (pointer coincides with B again)", replay_result.replayed is True)
        check("T4: replayed audit_path is attempt=0's OWN original audit file", replay_result.audit_path == attempt0_first.audit_path)
    finally:
        restore_fakes()
        fx.cleanup()


# ---- T5/T6: build replay corroboration ----

def test_t5_build_replay_rejects_tampered_artifact():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        conn = FakeJournalConn()
        result, _conn = do_apply_build(principal, repo, conn=conn)

        # Tamper with a published artifact byte AFTER the first
        # successful build - the SAME identity's replay must now fail
        # loudly rather than report stale-success.
        artifact_path = Path(result.bundle_dir) / "mevzuat.faiss"
        artifact_path.write_bytes(b"TAMPERED")

        expect_raises(
            facade.BuildReplayVerificationError,
            lambda: do_apply_build(principal, repo, conn=conn)[0],
            "T5: build replay rejects a tampered artifact",
        )
    finally:
        restore_fakes()
        fx.cleanup()


def test_t6_build_replay_rejects_missing_corrupt_duplicate_audit():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()

        # (a) MISSING audit.
        conn_a = FakeJournalConn()
        result_a, _ = do_apply_build(principal, repo, conn=conn_a, build_attempt=10)
        Path(result_a.audit_path).unlink()
        expect_raises(
            facade.BuildReplayVerificationError,
            lambda: do_apply_build(principal, repo, conn=conn_a, build_attempt=10)[0],
            "T6a: build replay rejects a missing audit",
        )

        # (b) CORRUPT audit (some OTHER unrelated audit file made unparseable).
        conn_b = FakeJournalConn()
        result_b, _ = do_apply_build(principal, repo, conn=conn_b, build_attempt=11)
        Path(result_b.audit_path).write_text("{ not valid json", encoding="utf-8")
        expect_raises(
            facade.BuildReplayVerificationError,
            lambda: do_apply_build(principal, repo, conn=conn_b, build_attempt=11)[0],
            "T6b: build replay rejects a corrupted (unparseable) bound audit",
        )

        # (c) DUPLICATE audit - a second file bound to the SAME
        # idempotency_key (simulated by hand-copying the real audit to
        # a second, differently-named .build_audit.json entry).
        conn_c = FakeJournalConn()
        result_c, _ = do_apply_build(principal, repo, conn=conn_c, build_attempt=12)
        original_audit = Path(result_c.audit_path)
        duplicate_audit = original_audit.parent / ("dup_" + original_audit.name)
        duplicate_audit.write_bytes(original_audit.read_bytes())
        expect_raises(
            facade.BuildReplayVerificationError,
            lambda: do_apply_build(principal, repo, conn=conn_c, build_attempt=12)[0],
            "T6c: build replay rejects a duplicate (two matching) bound audit",
        )
    finally:
        restore_fakes()
        fx.cleanup()


# ---- T7/T8: activate replay corroboration ----

def _replay_activate_directly(conn, intent, *, principal, index_root_real, bundle_version):
    """Shared T7/T8 helper: re-invokes the coordinator with the SAME
    intent an earlier, genuine `apply_activate()` call already used
    (see `build_activate_intent()`'s own docstring for why this,
    rather than a second `apply_activate()` call, is the correct way
    to reach the replay-corroboration path for a tampered/moved
    post-state)."""
    outcome = facade._mutation_coordinator.run_mutation(
        conn, intent, actor_user_id=principal.user_id,
        authz_callback=lambda: None, precondition_callback=lambda: None,
        writer_callback=_writer_must_not_run,
    )
    return facade._verify_completed_activate_replay(
        outcome, intent=intent, index_root_real=index_root_real, bundle_version=bundle_version,
    )


def test_t7a_activate_replay_rejects_pointer_not_at_target():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, result_b = make_two_bundles(principal, repo)
        shared_conn = FakeJournalConn()
        facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)
        facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: shared_conn)

        # Move the pointer back to A out-of-band (bypassing the facade
        # entirely - simulating a hand/manual pointer edit) so a replay
        # of the B-activation request finds the pointer NOT at its own
        # target.
        index_root_real = Path(facade._index_root()).resolve(strict=True)
        pointer_path = index_root_real / "current_version.json"
        pointer_path.write_bytes(facade._canonical_json_bytes({"current_version": result_a.bundle_version}))

        b_intent = build_activate_intent(result_b.bundle_version, result_a.bundle_version, 0, principal, facade._POINTER_ABSENT_SENTINEL, index_root_real)
        expect_raises(
            facade.ActivationReplayVerificationError,
            lambda: _replay_activate_directly(shared_conn, b_intent, principal=principal, index_root_real=index_root_real, bundle_version=result_b.bundle_version),
            "T7a: activate replay rejected when pointer is not at the target bundle",
        )
    finally:
        restore_fakes()
        fx.cleanup()


def test_t7b_activate_replay_rejects_noncanonical_pointer_bytes():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, _result_b = make_two_bundles(principal, repo)
        conn = FakeJournalConn()
        facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn)

        # Pointer IS at the target bundle_version (content-correct), but
        # its raw bytes are NOT the canonical serialization the writer
        # itself would produce (hand-written with different whitespace).
        index_root_real = Path(facade._index_root()).resolve(strict=True)
        pointer_path = index_root_real / "current_version.json"
        noncanonical = ('{"current_version": "' + result_a.bundle_version + '" }').encode("utf-8")
        check("T7b setup: noncanonical bytes really differ from the writer's own canonical form", noncanonical != facade._canonical_json_bytes({"current_version": result_a.bundle_version}))
        pointer_path.write_bytes(noncanonical)

        intent = build_activate_intent(result_a.bundle_version, "none", 0, principal, facade._POINTER_ABSENT_SENTINEL, index_root_real)
        expect_raises(
            facade.ActivationReplayVerificationError,
            lambda: _replay_activate_directly(conn, intent, principal=principal, index_root_real=index_root_real, bundle_version=result_a.bundle_version),
            "T7b: activate replay rejected when the pointer's bytes are not byte-canonical",
        )
    finally:
        restore_fakes()
        fx.cleanup()


def test_t8a_activate_replay_rejects_bundle_version_swap():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, result_b = make_two_bundles(principal, repo)
        conn_a = FakeJournalConn()
        activated_a = facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn_a)
        audit_path_a = Path(activated_a.audit_path)
        record_a = json.loads(audit_path_a.read_text(encoding="utf-8"))
        record_a["bundle_version"] = result_b.bundle_version
        audit_path_a.write_text(json.dumps(record_a), encoding="utf-8")

        index_root_real = Path(facade._index_root()).resolve(strict=True)
        intent = build_activate_intent(result_a.bundle_version, "none", 0, principal, facade._POINTER_ABSENT_SENTINEL, index_root_real)
        expect_raises(
            facade.ActivationReplayVerificationError,
            lambda: _replay_activate_directly(conn_a, intent, principal=principal, index_root_real=index_root_real, bundle_version=result_a.bundle_version),
            "T8a: activate replay rejects an audit whose bundle_version field was swapped",
        )
    finally:
        restore_fakes()
        fx.cleanup()


def test_t8b_activate_replay_rejects_identity_payload_tamper():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result, _ = do_apply_build(principal, repo)
        conn = FakeJournalConn()
        activated = facade.apply_activate(result.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn)
        audit_path = Path(activated.audit_path)
        record = json.loads(audit_path.read_text(encoding="utf-8"))
        record["identity_payload"]["activation_attempt"] = 12345
        audit_path.write_text(json.dumps(record), encoding="utf-8")

        index_root_real = Path(facade._index_root()).resolve(strict=True)
        intent = build_activate_intent(result.bundle_version, "none", 0, principal, facade._POINTER_ABSENT_SENTINEL, index_root_real)
        expect_raises(
            facade.ActivationReplayVerificationError,
            lambda: _replay_activate_directly(conn, intent, principal=principal, index_root_real=index_root_real, bundle_version=result.bundle_version),
            "T8b: activate replay rejects a tampered identity_payload (recompute mismatch)",
        )
    finally:
        restore_fakes()
        fx.cleanup()


def test_t8c_activate_replay_rejects_target_ref_mismatch():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, result_b = make_two_bundles(principal, repo)
        conn = FakeJournalConn()
        activated = facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn)
        audit_path = Path(activated.audit_path)
        record = json.loads(audit_path.read_text(encoding="utf-8"))
        record["target_ref"] = f"{facade.ACTIVATE_TARGET_REF_PREFIX}{result_b.bundle_version}"
        audit_path.write_text(json.dumps(record), encoding="utf-8")

        index_root_real = Path(facade._index_root()).resolve(strict=True)
        intent = build_activate_intent(result_a.bundle_version, "none", 0, principal, facade._POINTER_ABSENT_SENTINEL, index_root_real)
        expect_raises(
            facade.ActivationReplayVerificationError,
            lambda: _replay_activate_directly(conn, intent, principal=principal, index_root_real=index_root_real, bundle_version=result_a.bundle_version),
            "T8c: activate replay rejects a target_ref that names a DIFFERENT bundle_version",
        )
    finally:
        restore_fakes()
        fx.cleanup()


# ---- T9: W1 mkdir obstruction ----

def test_t9_w1_audit_dir_mkdir_obstruction_leaves_pointer_untouched():
    # (a) previous_existed=False (never activated before). Obstructs
    # `index/audit/activate` itself (the leaf) - `index/audit` (the
    # PARENT) already exists as a genuine directory by the time any
    # build has happened (the build writer itself populates `index/
    # audit/build/`), so obstructing the parent is not a reachable
    # real-world scenario once a valid build audit exists (which
    # activation always requires) - see T9b's own comment.
    fx_a = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result, _ = do_apply_build(principal, repo)
        index_root = fx_a.index_dir
        activate_audit_dir = facade._activate_audit_dir(index_root.resolve())
        activate_audit_dir.parent.mkdir(parents=True, exist_ok=True)
        activate_audit_dir.write_bytes(b"obstruction - not a directory")
        conn = FakeJournalConn()
        expect_raises(
            OSError,
            lambda: facade.apply_activate(result.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn),
            "T9a: W1 mkdir obstruction (index/audit is a file) propagates",
        )
        check("T9a: journal row reached reconciliation_required", conn.table[-1]["state"] == "reconciliation_required")
        pointer_state, current_version = facade._read_pointer_state(index_root.resolve())
        check("T9a: pointer remains absent (untouched)", pointer_state == "none")

        entry = snapshot_to_entry(conn.table[-1])
        evidence = adapters.ActivateReconciliationAdapter().gather_evidence(entry)
        check("T9a: reconciliation adapter proves pre-state unchanged (pointer still absent)", evidence.pre_state_confirmed_unchanged is True and evidence.post_state_verified is False)
    finally:
        restore_fakes()
        fx_a.cleanup()

    # (b) previous_existed=True (already activated once before).
    fx_b = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, result_b = make_two_bundles(principal, repo)
        conn = FakeJournalConn()
        facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn)
        pointer_path = fx_b.index_dir.resolve() / "current_version.json"
        pointer_before = pointer_path.read_bytes()

        # Obstruct index/audit/activate (not the parent) this time -
        # the OTHER named obstruction location the spec calls out.
        import shutil

        shutil.rmtree(facade._activate_audit_dir(fx_b.index_dir.resolve()))
        (facade._activate_audit_dir(fx_b.index_dir.resolve())).parent.mkdir(parents=True, exist_ok=True)
        facade._activate_audit_dir(fx_b.index_dir.resolve()).write_bytes(b"obstruction - not a directory")

        expect_raises(
            OSError,
            lambda: facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn),
            "T9b: W1 mkdir obstruction (index/audit/activate is a file) propagates",
        )
        check("T9b: pointer bytes byte-unchanged (still points at A)", pointer_before == pointer_path.read_bytes())
    finally:
        restore_fakes()
        fx_b.cleanup()


# ---- T10: W3/W4 fault injection with pointer rollback ----

def _make_nth_call_failure(original_fn, target_call_number, exc_factory):
    state = {"count": 0}

    def patched(*args, **kwargs):
        state["count"] += 1
        if state["count"] == target_call_number:
            raise exc_factory()
        return original_fn(*args, **kwargs)

    return patched


def test_t10_w3_w4_audit_write_fault_injection_rolls_back_pointer():
    import os as _os

    # (a) previous_existed=False: W4 fsync failure on the AUDIT write
    # (the pointer write's own fsync is call #1; the audit write's own
    # fsync is call #2 - failing #2 lets the pointer genuinely flip
    # before the audit write fails, exercising the rollback-to-absent
    # path).
    fx_a = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result, _ = do_apply_build(principal, repo)
        conn = FakeJournalConn()
        original_fsync = facade.os.fsync
        facade.os.fsync = _make_nth_call_failure(original_fsync, 2, lambda: OSError("simulated fsync failure (T10a)"))
        try:
            expect_raises(
                OSError,
                lambda: facade.apply_activate(result.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn),
                "T10a: W4 fsync failure on the audit write propagates",
            )
        finally:
            facade.os.fsync = original_fsync
        pointer_state, _cv = facade._read_pointer_state(fx_a.index_dir.resolve())
        check("T10a: pointer rolled BACK to absent (previous_existed=False)", pointer_state == "none")
        audit_dir = facade._activate_audit_dir(fx_a.index_dir.resolve())
        remaining = list(audit_dir.iterdir()) if audit_dir.is_dir() else []
        check("T10a: partial audit file was unlinked (no residue)", remaining == [])
        check("T10a: journal row reached reconciliation_required", conn.table[-1]["state"] == "reconciliation_required")
    finally:
        restore_fakes()
        fx_a.cleanup()

    # (b) previous_existed=True: same fault, but pointer must roll back
    # to the EXACT previous bundle's bytes, not to absent.
    fx_b = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result_a, result_b = make_two_bundles(principal, repo)
        conn = FakeJournalConn()
        facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn)
        pointer_path = fx_b.index_dir.resolve() / "current_version.json"
        pointer_before = pointer_path.read_bytes()

        original_fsync = facade.os.fsync
        facade.os.fsync = _make_nth_call_failure(original_fsync, 2, lambda: OSError("simulated fsync failure (T10b)"))
        try:
            expect_raises(
                OSError,
                lambda: facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn),
                "T10b: W4 fsync failure on the audit write propagates (previous_existed=True)",
            )
        finally:
            facade.os.fsync = original_fsync
        check("T10b: pointer rolled BACK to the exact previous bytes", pointer_path.read_bytes() == pointer_before)
    finally:
        restore_fakes()
        fx_b.cleanup()

    # (c) W3 open-failure (a non-FileExistsError OSError, e.g. a
    # permission-style failure) - pointer rolled back, no partial file.
    fx_c = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result, _ = do_apply_build(principal, repo)
        conn = FakeJournalConn()
        original_open = facade.os.open

        def failing_open(path, flags, *a, **kw):
            if str(path).endswith(".activate_audit.json"):
                raise PermissionError("simulated permission denial (T10c)")
            return original_open(path, flags, *a, **kw)

        facade.os.open = failing_open
        try:
            error = expect_raises(
                facade.RagBundleMutationError,
                lambda: facade.apply_activate(result.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn),
                "T10c: W3 os.open failure (non-FileExistsError OSError) is fail-closed (wrapped, chained)",
            )
            check("T10c: the original PermissionError is chained via __cause__", error is not None and isinstance(error.__cause__, PermissionError))
        finally:
            facade.os.open = original_open
        pointer_state, _cv = facade._read_pointer_state(fx_c.index_dir.resolve())
        check("T10c: pointer rolled back to absent after W3 open failure", pointer_state == "none")
    finally:
        restore_fakes()
        fx_c.cleanup()


# ---- T11: W0 unreadable-but-present pointer ----

def test_t11_unreadable_present_pointer_fails_closed_before_mutation():
    """T11 - the underlying W0 safety property (a present-but-
    UNREADABLE pointer must never be silently treated as absent) proven
    end-to-end: `current_version.json` is replaced with a DIRECTORY
    (lexists=True, but reading raw bytes fails). This is caught at the
    PRE-LOCK `_pointer_composite_hash()` call inside `apply_activate()`
    - BEFORE any lock/journal access - which is a STRICTER, EARLIER
    fail-closed point than the in-writer W0 read (itself unreachable in
    this scenario, since the pre-lock check already raises); both
    enforce the identical "unreadable != absent" contract this
    remediation requires. Directly unit-testing `_pointer_composite_
    hash()` proves the underlying primitive independently of which
    call site reaches it first."""
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result, _ = do_apply_build(principal, repo)
        index_root_real = fx.index_dir.resolve()
        (index_root_real / "current_version.json").mkdir()

        expect_raises(
            facade.RagBundleMutationError,
            lambda: facade._pointer_composite_hash(index_root_real),
            "T11a: _pointer_composite_hash() raises fail-closed for a present-but-unreadable pointer",
        )
        expect_raises(
            facade.RagBundleMutationError,
            lambda: facade.apply_activate(result.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: FakeJournalConn()),
            "T11b: apply_activate() with an unreadable pointer raises before any mutation",
        )
        check("T11c: the pointer path is still a directory (nothing was mutated)", (index_root_real / "current_version.json").is_dir())
    finally:
        restore_fakes()
        fx.cleanup()


# ---- T12: W3 FileExistsError fail-closed (F5.7 closure) ----

def test_t12_w3_audit_file_already_exists_fails_closed_with_rollback():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        result, _ = do_apply_build(principal, repo)

        idempotency_key = predicted_activate_idempotency_key(
            result.bundle_version, "none", 0, principal, repo,
        )
        audit_dir = facade._activate_audit_dir(fx.index_dir.resolve())
        audit_dir.mkdir(parents=True, exist_ok=True)
        preexisting_audit_path = audit_dir / f"{idempotency_key}.activate_audit.json"
        preexisting_audit_path.write_bytes(b'{"tampered": true}')

        conn = FakeJournalConn()
        expect_raises(
            facade.RagBundleMutationError,
            lambda: facade.apply_activate(result.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: conn),
            "T12: W3 FileExistsError (pre-existing audit at this exact key) is fail-closed, no more `pass`",
        )
        pointer_state, _cv = facade._read_pointer_state(fx.index_dir.resolve())
        check("T12: pointer rolled back to absent after the fail-closed refusal", pointer_state == "none")
        check("T12: the pre-existing (tampered) audit file was left EXACTLY as-is", preexisting_audit_path.read_bytes() == b'{"tampered": true}')
    finally:
        restore_fakes()
        fx.cleanup()


# ---- T13: two-actor same-content/attempt semantics ----

def test_t13_two_actors_same_content_get_independent_audits():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal1, repo1 = make_principal_and_repo(user_id=11)
        principal2, repo2 = make_principal_and_repo(user_id=12)
        conn1 = FakeJournalConn()
        conn2 = FakeJournalConn()
        builder = make_snapshot_builder()

        preview1 = facade.preview_build(build_attempt=0, principal=principal1, authz_repository=repo1)
        result1 = facade.apply_build(
            preview1["input_digest"], allow_network=True, build_attempt=0,
            principal=principal1, authz_repository=repo1, conn_factory=lambda: conn1, snapshot_builder=builder,
        )
        preview2 = facade.preview_build(build_attempt=0, principal=principal2, authz_repository=repo2)
        result2 = facade.apply_build(
            preview2["input_digest"], allow_network=True, build_attempt=0,
            principal=principal2, authz_repository=repo2, conn_factory=lambda: conn2, snapshot_builder=builder,
        )
        check("T13: two actors, same content/attempt -> SAME bundle_version", result1.bundle_version == result2.bundle_version)
        check("T13: two actors get DIFFERENT idempotency_keys", conn1.table[-1]["idempotency_key"] != conn2.table[-1]["idempotency_key"])
        check("T13: actor 2's write was an identical-bytes republish (first_publish=False)", json.loads(Path(result2.audit_path).read_text(encoding="utf-8"))["first_publish"] is False)
        check("T13: actor 1's write was the real first publish (first_publish=True)", json.loads(Path(result1.audit_path).read_text(encoding="utf-8"))["first_publish"] is True)
        check("T13: each actor got its OWN, distinctly-named audit file", result1.audit_path != result2.audit_path)

        entry1 = snapshot_to_entry(conn1.table[-1])
        entry2 = snapshot_to_entry(conn2.table[-1])
        evidence1 = adapters.BuildReconciliationAdapter().gather_evidence(entry1)
        evidence2 = adapters.BuildReconciliationAdapter().gather_evidence(entry2)
        check("T13: actor 1's own journal row replay-verifies via ITS OWN audit", evidence1.post_state_verified is True)
        check("T13: actor 2's own journal row replay-verifies via ITS OWN audit (not actor 1's)", evidence2.post_state_verified is True)
    finally:
        restore_fakes()
        fx.cleanup()


# ---- T14: build audit digest recompute mismatch ----

def test_t14_build_audit_recompute_mismatch_blocks_adapter_and_replay():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        conn = FakeJournalConn()
        result, _ = do_apply_build(principal, repo, conn=conn)

        audit_path = Path(result.audit_path)
        record = json.loads(audit_path.read_text(encoding="utf-8"))
        record["input_digest"] = "0" * 64
        audit_path.write_text(json.dumps(record), encoding="utf-8")

        entry = snapshot_to_entry(conn.table[-1])
        evidence = adapters.BuildReconciliationAdapter().gather_evidence(entry)
        check("T14: adapter post-proof is False after an input_digest tamper", evidence.post_state_verified is False)

        expect_raises(
            facade.BuildReplayVerificationError,
            lambda: do_apply_build(principal, repo, conn=conn)[0],
            "T14: build replay also rejects the SAME tampered audit",
        )
    finally:
        restore_fakes()
        fx.cleanup()


# ---- T15: no replay path ever calls builder/network/writer ----

def test_t15_replay_paths_never_invoke_builder_or_writer():
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()
        conn = FakeJournalConn()
        calls = []
        builder = make_snapshot_builder(embedding_calls_tracker=calls)
        result, _ = do_apply_build(principal, repo, conn=conn, builder=builder)
        check("T15 setup: builder called exactly once for the first build", len(calls) == 1)

        original_builder_ref = ingest.build_bundle_snapshot

        def poisoned_builder(*a, **kw):
            raise AssertionError("replay must never call the real builder")

        ingest.build_bundle_snapshot = poisoned_builder
        try:
            replay = do_apply_build(principal, repo, conn=conn, builder=builder)[0]
            check("T15: build replay succeeds without touching the poisoned real builder", replay.replayed is True)
            check("T15: injected test builder was STILL not called again", len(calls) == 1)
        finally:
            ingest.build_bundle_snapshot = original_builder_ref

        activate_conn = FakeJournalConn()
        activated = facade.apply_activate(result.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=repo, conn_factory=lambda: activate_conn)
        check("T15 setup: activation genuinely executed", activated.replayed is False)

        # See build_activate_intent()'s own docstring - a genuine
        # activate replay is tested by directly re-invoking the
        # coordinator with the SAME intent (simulating a concurrent
        # second caller), not by calling apply_activate() twice in a
        # row (its OWN outer freshness gate would otherwise reject the
        # second call as stale, since the live pointer has already
        # moved past "none" by then).
        index_root_real = Path(facade._index_root()).resolve(strict=True)
        activate_intent = build_activate_intent(result.bundle_version, "none", 0, principal, facade._POINTER_ABSENT_SENTINEL, index_root_real)
        activate_outcome = facade._mutation_coordinator.run_mutation(
            activate_conn, activate_intent, actor_user_id=principal.user_id,
            authz_callback=lambda: None, precondition_callback=lambda: None,
            writer_callback=_writer_must_not_run,
        )
        check("T15: activate replay recognized by the coordinator (writer never re-invoked)", activate_outcome.replayed is True)
        activate_replay = facade._verify_completed_activate_replay(
            activate_outcome, intent=activate_intent, index_root_real=index_root_real, bundle_version=result.bundle_version,
        )
        check("T15: activate replay corroboration succeeds", activate_replay.replayed is True)
    finally:
        restore_fakes()
        fx.cleanup()


# ---- T16: adapter pre-proof composite (corrupt1 -> corrupt2) ----

def test_t16_adapter_pre_proof_detects_corrupt_content_swap():
    fx = Fixture()
    try:
        index_root_real = fx.index_dir
        index_root_real.mkdir(parents=True, exist_ok=True)
        index_root_real = index_root_real.resolve(strict=True)
        pointer_path = index_root_real / "current_version.json"
        pointer_path.write_bytes(b"{ this is corrupt json #1")
        corrupt1_hash = facade._pointer_composite_hash(index_root_real)

        entry = mr.JournalEntrySnapshot(
            journal_id=1, resource_key=facade.RESOURCE_KEY, action_family=facade.ACTIVATE_ACTION_FAMILY,
            target_ref=f"{facade.ACTIVATE_TARGET_REF_PREFIX}v_{'a' * 64}", target_state=facade.ACTIVATE_TARGET_STATE,
            pre_hash=corrupt1_hash, pre_revision="unused" * 8, expected_post_hash=None, state="executing",
            idempotency_key="a" * 64, request_fingerprint="b" * 64, actor_label="5",
        )
        evidence_before_swap = adapters.ActivateReconciliationAdapter().gather_evidence(entry)
        check("T16 setup: pre-state confirmed unchanged BEFORE any content swap", evidence_before_swap.pre_state_confirmed_unchanged is True)

        pointer_path.write_bytes(b"{ this is a DIFFERENT corrupt json #2 - different bytes")
        corrupt2_hash = facade._pointer_composite_hash(index_root_real)
        check("T16 setup: two different corrupt contents hash DIFFERENTLY", corrupt1_hash != corrupt2_hash)

        evidence_after_swap = adapters.ActivateReconciliationAdapter().gather_evidence(entry)
        check(
            "T16: adapter detects the corrupt-content SWAP (dual-false, no longer pre_state_confirmed_unchanged=True)",
            evidence_after_swap.pre_state_confirmed_unchanged is False and evidence_after_swap.post_state_verified is False,
        )
    finally:
        fx.cleanup()


def test_t17_activation_attempt_shape_rejected_by_facade_directly():
    """TARGETED F1 REMEDIATION test-gap closure: the remediation spec's
    own binding text ("Bool, negatif ve int olmayan attempt facade
    tarafından da bağımsız reddedilir") requires `_validate_activation_
    attempt()` to be proven through BOTH public facade entry points
    directly - not only indirectly through the CLI's own argparse
    layer (T22, in `test_cli_mutate_isolated.py`). `principal`/
    `authz_repository` are left as `None`, and `apply_activate`'s
    `conn_factory` is a lambda that raises if ever called - since
    `_validate_activation_attempt()` is the FIRST line of both
    functions (before any of the three is touched), a
    `RagBundleArgumentError` here proves the shape check fires before
    authz/connection access; any OTHER exception (e.g. an
    `AttributeError` from touching `None`, or the conn_factory's own
    assertion firing) would mean that ordering regressed."""
    dummy_bundle_version = "v_" + "a" * 64

    def _conn_factory_must_not_be_called():
        raise AssertionError("apply_activate must reject the shape before ever calling conn_factory")

    for bad_attempt in (True, False, -1, "0", 1.5, None):
        expect_raises(
            facade.RagBundleArgumentError,
            lambda bad_attempt=bad_attempt: facade.preview_activate(
                dummy_bundle_version, activation_attempt=bad_attempt,
                principal=None, authz_repository=None,
            ),
            f"T17: preview_activate rejects activation_attempt={bad_attempt!r} before authz",
        )
        expect_raises(
            facade.RagBundleArgumentError,
            lambda bad_attempt=bad_attempt: facade.apply_activate(
                dummy_bundle_version, "none", activation_attempt=bad_attempt,
                principal=None, authz_repository=None,
                conn_factory=_conn_factory_must_not_be_called,
            ),
            f"T17: apply_activate rejects activation_attempt={bad_attempt!r} before authz/connection",
        )


def test_t18_corrupt_build_audit_blocks_fresh_activation_of_unrelated_bundle():
    """TARGETED F4 REMEDIATION test-gap closure: the spec requires
    "corrupt build audit girdisi aileyi fail-closed bloklamalı" for
    activation, not only for build-replay (T6b already covers replay).
    This proves the SAME family-wide fail-closed rule blocks a FRESH
    (first-time, non-replay) `apply_activate()` of bundle A, purely
    because an UNRELATED audit file for a DIFFERENT bundle B sitting
    in the same `index/audit/build/` directory has been corrupted -
    `_bundle_has_verified_build_audit()` scans the whole directory and
    refuses to treat ANY bundle as build-audited while a single
    corrupt neighbour exists anywhere in it (see that function's own
    docstring: "ZERO corrupt entries anywhere in the directory")."""
    fx = Fixture()
    install_fakes()
    reset_hooks()
    try:
        principal, repo = make_principal_and_repo()

        # Bundle A: genuine build, genuine own audit - the bundle we
        # will actually try (and expect) to fail activating.
        result_a, _conn_a = do_apply_build(principal, repo, build_attempt=0)

        # Bundle B: a SECOND, genuine, unrelated build (different
        # build_attempt -> different identity -> different
        # bundle_version and its own separate audit file).
        result_b, _conn_b = do_apply_build(principal, repo, build_attempt=1)
        check(
            "T18 setup: bundle A and bundle B are genuinely different bundles",
            result_a.bundle_version != result_b.bundle_version,
        )

        # Confirm A is build-audited BEFORE corrupting B's neighbour audit.
        preview_before = facade.preview_activate(result_a.bundle_version, principal=principal, authz_repository=repo)
        check("T18 setup: bundle A has_build_audit=True before neighbour corruption", preview_before["has_build_audit"] is True)

        # Corrupt ONLY bundle B's audit file (unrelated to A).
        Path(result_b.audit_path).write_text("{ not valid json - corrupt neighbour", encoding="utf-8")

        # Bundle A's OWN preview must now honestly report has_build_audit=False
        # (family-wide fail-closed - never "trust A's own audit alone").
        preview_after = facade.preview_activate(result_a.bundle_version, principal=principal, authz_repository=repo)
        check("T18: bundle A has_build_audit=False once ANY neighbour audit is corrupt", preview_after["has_build_audit"] is False)

        expect_raises(
            facade.BundleNotBuildAuditedError,
            lambda: facade.apply_activate(
                result_a.bundle_version, "none",
                principal=principal, authz_repository=repo, conn_factory=lambda: FakeJournalConn(),
            ),
            "T18: fresh (non-replay) apply_activate of bundle A refused due to corrupt neighbour audit for bundle B",
        )
    finally:
        restore_fakes()
        fx.cleanup()


def run_self_test():
    test_preview_build_zero_network_and_correct_digest()
    test_preview_build_authz_denied()
    test_apply_build_requires_allow_network()
    test_apply_build_stale_input_digest()
    test_apply_build_success_full_chain()
    test_apply_build_safe_replay_does_not_reinvoke_builder()
    test_apply_build_source_drift_under_lock()
    test_apply_build_version_collision()
    test_activate_full_flow_and_already_active_and_stale()
    test_activate_refused_without_build_audit()
    test_activate_authz_denied_zero_lock()
    test_build_reconciliation_post_state_verified()
    test_build_reconciliation_pre_state_unchanged_when_no_audit()
    test_build_reconciliation_dual_false_when_wrong_resource()
    test_activate_reconciliation_post_state_verified()
    test_reconciliation_never_touches_network_or_writer()

    # TARGETED F1-F4 REMEDIATION (T1-T16).
    test_t1_reactivation_same_attempt_raises_loudly_pointer_unchanged()
    test_t2_reactivation_new_attempt_succeeds_for_real()
    test_t3_genuine_same_attempt_replay_full_corroboration()
    test_t4_attempt0_replay_after_attempt1_success_is_honest()
    test_t5_build_replay_rejects_tampered_artifact()
    test_t6_build_replay_rejects_missing_corrupt_duplicate_audit()
    test_t7a_activate_replay_rejects_pointer_not_at_target()
    test_t7b_activate_replay_rejects_noncanonical_pointer_bytes()
    test_t8a_activate_replay_rejects_bundle_version_swap()
    test_t8b_activate_replay_rejects_identity_payload_tamper()
    test_t8c_activate_replay_rejects_target_ref_mismatch()
    test_t9_w1_audit_dir_mkdir_obstruction_leaves_pointer_untouched()
    test_t10_w3_w4_audit_write_fault_injection_rolls_back_pointer()
    test_t11_unreadable_present_pointer_fails_closed_before_mutation()
    test_t12_w3_audit_file_already_exists_fails_closed_with_rollback()
    test_t13_two_actors_same_content_get_independent_audits()
    test_t14_build_audit_recompute_mismatch_blocks_adapter_and_replay()
    test_t15_replay_paths_never_invoke_builder_or_writer()
    test_t16_adapter_pre_proof_detects_corrupt_content_swap()
    test_t17_activation_attempt_shape_rejected_by_facade_directly()
    test_t18_corrupt_build_audit_blocks_fresh_activation_of_unrelated_bundle()

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
