# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION - REAL, END-TO-END PostgreSQL
# INTEGRATION PROOF for ui/services/rag_bundle_mutation_facade.py +
# ui/services/rag_bundle_mutation_adapters.py + scripts/
# global_resource_grants.py + ui/services/global_authz.py + the
# `ui.cli_mutate` `rag-bundle` subcommand (list/preview paths - see
# below for why apply is NOT exercised through the CLI here) +
# ui/reconciliation_operator.py's merged registry.
#
# WHAT IS REAL HERE: real `mutation.mutation_journal`, real
# `pg_advisory_lock` session locking (observed via PostgreSQL's OWN
# pg_locks view - genuine two-connection serialization, not simulated),
# real `iam.global_resource_grants`/`iam.global_resource_grant_events`
# round trips via `scripts.global_resource_grants`, real
# `ui.services.global_authz.PostgresGlobalResourceAuthzRepository`, the
# real merged reconciliation registry.
#
# WHAT IS NOT REAL: `src.ingest.build_bundle_snapshot`'s own actual
# faiss/numpy/embedding-API work - faiss/numpy are NOT installed in
# this project's `vergi_ui_runtime` target environment (confirmed by
# direct import probe during implementation), so `apply_build()` is
# exercised here via its documented `snapshot_builder=` test-injection
# seam (never `embedding_client=` alone - the seam bypasses the
# faiss-dependent parts of `build_bundle_snapshot()` entirely, not just
# its network call). Because of this, `ui.cli_mutate.main()`'s own
# `rag-bundle build --apply`/`activate --apply` paths (which NEVER
# accept a snapshot_builder override, by design - see cli_mutate.py's
# own header comment on why production never injects a test seam) are
# NOT exercised end-to-end as real OS subprocesses in THIS environment;
# `--action list` and both `build`/`activate` PREVIEW paths (genuinely
# faiss-free) ARE exercised through the real `main()` entry point. This
# is a disclosed, environment-driven scope decision, not a silent gap.
#
# The real repo `data/`/`index/` trees are NEVER touched - all case/
# document/index state lives under a fresh tempdir, proven byte-for-
# byte unchanged at the end.
#
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_rag_bundle_mutation_integration_postgres.py
# ============================================================

import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

passed = 0
failed = 0
skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def skip(label, detail=""):
    global skipped
    skipped += 1
    print(f"SKIPPED {label} - {detail}")


def summarize_and_exit():
    print(f"--- test_rag_bundle_mutation_integration_postgres: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip("the entire real-PostgreSQL rag-bundle integration suite", "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass")
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:
    skip("the entire real-PostgreSQL rag-bundle integration suite", f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass")
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                    # noqa: E402
import ui.reconciliation_operator as op                                # noqa: E402
from ui.services import authz as _authz                                # noqa: E402
from ui.services import mutation_lock as _mutation_lock                # noqa: E402
from ui.services import global_authz as ga                             # noqa: E402
from ui.services import rag_bundle_mutation_facade as facade           # noqa: E402
from ui.services import rag_bundle_mutation_adapters as ra_adapters    # noqa: E402
from ui.services import mutation_registry as mr                        # noqa: E402
from scripts import global_resource_grants as grg                      # noqa: E402

import ingest  # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


# ----------------------------------------------------------------
# Preflight.
# ----------------------------------------------------------------

_preflight = pg_connect()
try:
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('iam.users'), to_regclass('mutation.mutation_resources'), "
            "to_regclass('mutation.mutation_journal'), to_regclass('iam.global_resource_grants'), "
            "to_regclass('iam.global_resource_grant_events')"
        )
        row = cur.fetchone()
    check("preflight: iam + mutation + grants schemas all exist (migrations 0001-0005)", all(row))
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run against a half-migrated database.")
    summarize_and_exit()

_ACTORS = {"admin": 401, "operator": 402, "ungranted": 403, "operator2": 404}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"ragbundle-actor-{user_id}"),
            )
        cur.execute(
            "INSERT INTO iam.user_roles (user_id, role) VALUES (%s, 'admin') ON CONFLICT DO NOTHING",
            (_ACTORS["admin"],),
        )
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('iam.users', 'id'), GREATEST((SELECT max(id) FROM iam.users), 1))"
        )
finally:
    _seed.close()

grg._run_locked_as_admin = grg._run_locked_as_admin  # no-op reference (keeps lints quiet)


def grant_all(user_id, actor_user_id=_ACTORS["admin"]):
    conn = pg_connect()
    try:
        _mutation_lock.acquire_global_iam_lock(conn)
        for capability in ("inspect", "build", "activate"):
            grg.grant_capability(conn, subject_user_id=user_id, resource="rag_index", capability=capability, actor_user_id=actor_user_id)
    finally:
        conn.close()


grant_all(_ACTORS["operator"])
grant_all(_ACTORS["operator2"])


def make_principal(user_id):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT authz_version FROM iam.users WHERE id = %s", (user_id,))
            (authz_version,) = cur.fetchone()
    finally:
        conn.close()
    return _authz.Principal(user_id=user_id, session_id=0, role_version_at_issue=authz_version)


# ----------------------------------------------------------------
# Temp data/index fixture - real repo data/index NEVER touched.
# ----------------------------------------------------------------

_repo_data_before = None
_repo_index_before = None


def sha_tree(root: Path):
    out = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if p.is_file():
            try:
                out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                out[str(p.relative_to(root))] = "<unreadable>"
    return out


REAL_DATA_DIR = REPO_ROOT / "data"
REAL_INDEX_DIR = REPO_ROOT / "index"
_repo_data_before = sha_tree(REAL_DATA_DIR)
_repo_index_before = sha_tree(REAL_INDEX_DIR)

_tmpdir = tempfile.TemporaryDirectory()
_tmp_path = Path(_tmpdir.name)
_data_dir = _tmp_path / "data"
_mevzuat_dir = _data_dir / "mevzuat"
_mevzuat_dir.mkdir(parents=True)
(_mevzuat_dir / "doc_0.pdf").write_bytes(b"fake pdf bytes for integration test")
_documents = [{
    "document_id": "doc_0", "file_name": "doc_0.pdf", "active": True, "status": "yururlukte",
    "ingest": {"enabled": True, "parser": "legal_pdf", "chunk_strategy": "legal_hierarchy"},
}]
(_data_dir / "documents.json").write_text(json.dumps({"documents": _documents}), encoding="utf-8")
_index_dir = _tmp_path / "index"

_original_ingest_paths = (ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.INDEX_DIR)
ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.INDEX_DIR = (
    _data_dir, _mevzuat_dir, _data_dir / "documents.json", _index_dir,
)


def make_snapshot_builder(build_index=0):
    def builder(*, embedding_client=None, pdf_page_extractor=None, build_attempt=0):
        source_manifest = ingest.compute_source_manifest()
        pipeline_config = ingest.build_pipeline_config()
        seed = json.dumps({"sm": source_manifest, "ba": build_attempt, "bi": build_index}, sort_keys=True).encode("utf-8")
        artifacts = {
            "mevzuat.faiss": b"FAKEFAISS:" + hashlib.sha256(seed + b"1").digest(),
            "documents.pkl": b"FAKEPKL:" + hashlib.sha256(seed + b"2").digest(),
            "config.json": b"FAKECFG:" + hashlib.sha256(seed + b"3").digest(),
        }
        return {
            "source_manifest": source_manifest, "pipeline_config": pipeline_config, "build_attempt": build_attempt,
            "chunk_count": 3, "embedding_dimension": 4, "artifacts": artifacts,
        }

    return builder


def cleanup_fixture():
    ingest.DATA_DIR, ingest.MEVZUAT_DIR, ingest.MANIFEST_PATH, ingest.INDEX_DIR = _original_ingest_paths
    _tmpdir.cleanup()


def wipe_journal_and_index():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mutation.mutation_journal WHERE resource_key = %s", (facade.RESOURCE_KEY,))
    finally:
        conn.close()
    import shutil
    if _index_dir.exists():
        shutil.rmtree(_index_dir)


# ================================================================
# scripts.global_resource_grants - real DB round trip.
# ================================================================

def test_grant_revoke_regrant_real_db():
    conn = pg_connect()
    try:
        _mutation_lock.acquire_global_iam_lock(conn)
        result1 = grg.grant_capability(conn, subject_user_id=_ACTORS["ungranted"], resource="rag_index", capability="inspect", actor_user_id=_ACTORS["admin"])
        check("real grant: created", result1.created is True)
        grg.revoke_capability(conn, subject_user_id=_ACTORS["ungranted"], resource="rag_index", capability="inspect", actor_user_id=_ACTORS["admin"])
        result2 = grg.grant_capability(conn, subject_user_id=_ACTORS["ungranted"], resource="rag_index", capability="inspect", actor_user_id=_ACTORS["admin"])
        check("real regrant: new history row", result2.grant_id != result1.grant_id)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_type FROM iam.global_resource_grant_events WHERE grant_id IN (%s, %s) ORDER BY id",
                (result1.grant_id, result2.grant_id),
            )
            events = [r[0] for r in cur.fetchall()]
        check("real events: created/revoked/created", events == ["grant_created", "grant_revoked", "grant_created"])
        # cleanup: revoke again so subsequent tests aren't affected
        grg.revoke_capability(conn, subject_user_id=_ACTORS["ungranted"], resource="rag_index", capability="inspect", actor_user_id=_ACTORS["admin"])
    finally:
        conn.close()


def test_grant_admin_rejected_real_db():
    conn = pg_connect()
    try:
        _mutation_lock.acquire_global_iam_lock(conn)
        try:
            grg.grant_capability(conn, subject_user_id=_ACTORS["admin"], resource="rag_index", capability="build", actor_user_id=_ACTORS["admin"])
            check("real: admin-grantee rejected", False, "did not raise")
        except grg.GrantCommandError:
            check("real: admin-grantee rejected", True)
    finally:
        conn.close()


def test_postgres_global_authz_repository_real():
    conn = pg_connect()
    try:
        repo = ga.PostgresGlobalResourceAuthzRepository(conn)
        principal = make_principal(_ACTORS["operator"])
        ga.authorize_global_resource_access(principal, "build", repository=repo)
        check("real global authz: operator has build", True)
        ungranted_principal = make_principal(_ACTORS["ungranted"])
        try:
            ga.authorize_global_resource_access(ungranted_principal, "build", repository=repo)
            check("real global authz: ungranted denied", False, "did not raise")
        except ga.GlobalResourceAccessDeniedError:
            check("real global authz: ungranted denied", True)
    finally:
        conn.close()


# ================================================================
# facade.apply_build / apply_activate - real journal + real lock.
# ================================================================

def test_build_success_and_journal_real():
    wipe_journal_and_index()
    principal = make_principal(_ACTORS["operator"])
    repo_conn = pg_connect()
    try:
        outer_repo = ga.PostgresGlobalResourceAuthzRepository(repo_conn)
        preview = facade.preview_build(build_attempt=0, principal=principal, authz_repository=outer_repo)
        result = facade.apply_build(
            preview["input_digest"], allow_network=True, build_attempt=0,
            principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
            snapshot_builder=make_snapshot_builder(),
        )
        check("real build: bundle dir created", Path(result.bundle_dir).is_dir())
        check("real build: replayed=False", result.replayed is False)

        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state, observed_post_hash, resource_key, action_family FROM mutation.mutation_journal "
                    "WHERE resource_key = %s ORDER BY id DESC LIMIT 1",
                    (facade.RESOURCE_KEY,),
                )
                row = cur.fetchone()
            check("real build: journal row completed", row[0] == "completed")
            check("real build: observed_post_hash matches bundle_version", row[1] == result.bundle_version)
            check("real build: resource_key/action_family correct", row[2] == "global:rag_index" and row[3] == "rag_bundle.build")
        finally:
            conn.close()

        # Safe replay against real DB.
        replay = facade.apply_build(
            preview["input_digest"], allow_network=True, build_attempt=0,
            principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
            snapshot_builder=make_snapshot_builder(),
        )
        check("real build: safe replay bundle_version matches", replay.bundle_version == result.bundle_version)
        check("real build: safe replay replayed=True", replay.replayed is True)
        return result
    finally:
        repo_conn.close()


def test_build_fingerprint_conflict_real():
    principal = make_principal(_ACTORS["operator"])
    repo_conn = pg_connect()
    try:
        outer_repo = ga.PostgresGlobalResourceAuthzRepository(repo_conn)
        preview = facade.preview_build(build_attempt=0, principal=principal, authz_repository=outer_repo)
        # Same identity (build_attempt=0, same sources) but a DIFFERENT
        # builder output (different fake artifact bytes) forces a
        # request_fingerprint mismatch is NOT actually possible here
        # since target_state is fixed - identity is the SAME either way,
        # so this exercises the deterministic-replay path, not conflict.
        # Real fingerprint-conflict coverage: attempt build_attempt=0
        # with a stale/incorrect expected_input_digest instead.
        try:
            facade.apply_build(
                "0" * 64, allow_network=True, build_attempt=0,
                principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
                snapshot_builder=make_snapshot_builder(),
            )
            check("real build: stale digest rejected pre-lock", False, "did not raise")
        except facade.RagBundleStaleInputError:
            check("real build: stale digest rejected pre-lock", True)
    finally:
        repo_conn.close()


def test_build_snapshot_builder_crash_before_lock_real():
    """A `snapshot_builder()` failure happens OUTSIDE the lock, BEFORE
    any journal row is ever inserted (contract B: the expensive rebuild
    runs before the journal row exists) - this is NOT a writer_callback
    failure and never produces `reconciliation_required`; it produces
    ZERO journal rows at all, verified here against the real DB."""
    principal = make_principal(_ACTORS["operator"])
    repo_conn = pg_connect()
    try:
        outer_repo = ga.PostgresGlobalResourceAuthzRepository(repo_conn)
        preview = facade.preview_build(build_attempt=1, principal=principal, authz_repository=outer_repo)

        def crashing_builder(*, embedding_client=None, pdf_page_extractor=None, build_attempt=0):
            raise RuntimeError("simulated pre-lock build failure")

        try:
            facade.apply_build(
                preview["input_digest"], allow_network=True, build_attempt=1,
                principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
                snapshot_builder=crashing_builder,
            )
            check("real build: pre-lock crash propagates", False, "did not raise")
        except RuntimeError:
            check("real build: pre-lock crash propagates", True)

        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM mutation.mutation_journal WHERE resource_key = %s AND target_ref = %s "
                    "AND pre_revision = %s",
                    (facade.RESOURCE_KEY, facade.BUILD_TARGET_REF, preview["input_digest"]),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        check("real build: pre-lock crash leaves zero journal rows for this identity", row is None)
    finally:
        repo_conn.close()


def test_build_writer_crash_reconciliation_real():
    """Forces a REAL `writer_callback` failure (after `executing` is
    durably persisted) by pre-obstructing the deterministic staging
    directory path with a plain FILE where the writer expects to
    `mkdir()` a directory - proves the real `reconciliation_required`
    state is reached, and that the reconciliation adapter's PRE-STATE
    proof (source inputs unchanged) resolves it to `failed` against the
    real database."""
    principal = make_principal(_ACTORS["operator"])
    repo_conn = pg_connect()
    try:
        outer_repo = ga.PostgresGlobalResourceAuthzRepository(repo_conn)
        build_attempt = 2
        source_manifest, pipeline_config, source_digest, input_digest = facade._freeze_pre_build_state(build_attempt)
        from mutation_guard import MutationIntent, compute_idempotency_key

        intent = MutationIntent(
            actor_type=facade.ACTOR_TYPE, actor_ref=str(_ACTORS["operator"]), resource_key=facade.RESOURCE_KEY,
            action_family=facade.BUILD_ACTION_FAMILY, target_ref=facade.BUILD_TARGET_REF,
            target_state=facade.BUILD_TARGET_STATE, pre_hash=source_digest, pre_revision=input_digest,
        )
        idempotency_key = compute_idempotency_key(intent)
        staging_name = f"b_{idempotency_key[:24]}"
        _index_dir.mkdir(parents=True, exist_ok=True)
        staging_parent = _index_dir / "staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        obstruction_path = staging_parent / staging_name
        obstruction_path.write_bytes(b"obstruction - not a directory")

        try:
            facade.apply_build(
                input_digest, allow_network=True, build_attempt=build_attempt,
                principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
                snapshot_builder=make_snapshot_builder(),
            )
            check("real build: writer-level crash propagates", False, "did not raise")
        except Exception:
            check("real build: writer-level crash propagates", True)

        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, state, idempotency_key FROM mutation.mutation_journal WHERE idempotency_key = %s",
                    (idempotency_key,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        check("real build: writer-level crash produces reconciliation_required row", row is not None and row[1] == "reconciliation_required", row)

        if row is not None:
            entry = mr.JournalEntrySnapshot(
                journal_id=row[0], resource_key=facade.RESOURCE_KEY, action_family=facade.BUILD_ACTION_FAMILY,
                target_ref=facade.BUILD_TARGET_REF, target_state=facade.BUILD_TARGET_STATE,
                pre_hash=source_digest, pre_revision=input_digest, expected_post_hash=None, state=row[1],
                idempotency_key=idempotency_key, request_fingerprint="unused-not-needed-by-adapter",
                actor_label=str(_ACTORS["operator"]),
            )
            evidence = ra_adapters.BuildReconciliationAdapter().gather_evidence(entry)
            check("real reconcile build: pre_state_confirmed_unchanged=True (sources untouched)", evidence.pre_state_confirmed_unchanged is True)

            reconcile_conn = pg_connect()
            try:
                outcome = mr.reconcile_and_apply_journal_entry(
                    reconcile_conn, row[0], op._default_registry_factory(),
                    resolved_by_actor_type="cli_service", resolved_by_actor_ref="integration-test",
                )
            finally:
                reconcile_conn.close()
            check("real reconcile_and_apply: resolves to failed", outcome.new_state == "failed", outcome.new_state)

        obstruction_path.unlink(missing_ok=True)
    finally:
        repo_conn.close()


def test_lock_serialization_real():
    advisory_lock_id = None
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT advisory_lock_id FROM mutation.mutation_resources WHERE resource_key = %s", (facade.RESOURCE_KEY,))
            (advisory_lock_id,) = cur.fetchone()
    finally:
        conn.close()

    holder_conn = pg_connect()
    _mutation_lock.acquire_global_lock_session(holder_conn, facade.RESOURCE_KEY)

    waiter_result = {}

    def waiter():
        waiter_conn = pg_connect()
        try:
            _mutation_lock.acquire_global_lock_session(waiter_conn, facade.RESOURCE_KEY)
            waiter_result["acquired"] = True
        finally:
            _mutation_lock.release_lock_session(waiter_conn, advisory_lock_id)
            waiter_conn.close()

    thread = threading.Thread(target=waiter)
    thread.start()

    deadline = time.monotonic() + 15.0
    saw_waiter = False
    while time.monotonic() < deadline:
        check_conn = pg_connect()
        try:
            with check_conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = %s AND granted = FALSE",
                    (advisory_lock_id & 0xFFFFFFFF,),
                )
                (count,) = cur.fetchone()
            if count > 0:
                saw_waiter = True
                break
        finally:
            check_conn.close()
        time.sleep(0.1)

    check("real lock: second session genuinely blocks (pg_locks observed)", saw_waiter)
    _mutation_lock.release_lock_session(holder_conn, advisory_lock_id)
    holder_conn.close()
    thread.join(timeout=15)
    check("real lock: waiter eventually acquired after release", waiter_result.get("acquired") is True)


def test_activate_and_reconciliation_real(build_result):
    principal = make_principal(_ACTORS["operator"])
    repo_conn = pg_connect()
    try:
        outer_repo = ga.PostgresGlobalResourceAuthzRepository(repo_conn)
        activate_result = facade.apply_activate(
            build_result.bundle_version, "none", principal=principal, authz_repository=outer_repo,
            conn_factory=pg_connect,
        )
        check("real activate: pointer written", Path(activate_result.pointer_path).is_file())
        check("real activate: replayed=False", activate_result.replayed is False)

        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, resource_key, action_family, target_ref, target_state, pre_hash, pre_revision, "
                    "idempotency_key, request_fingerprint, actor_label, state "
                    "FROM mutation.mutation_journal WHERE resource_key = %s AND action_family = %s "
                    "ORDER BY id DESC LIMIT 1",
                    (facade.RESOURCE_KEY, facade.ACTIVATE_ACTION_FAMILY),
                )
                cols = [d.name for d in cur.description]
                row = dict(zip(cols, cur.fetchone()))
        finally:
            conn.close()

        entry = mr.JournalEntrySnapshot(
            journal_id=row["id"], resource_key=row["resource_key"], action_family=row["action_family"],
            target_ref=row["target_ref"], target_state=row["target_state"], pre_hash=row["pre_hash"],
            pre_revision=row["pre_revision"], expected_post_hash=None, state=row["state"],
            idempotency_key=row["idempotency_key"], request_fingerprint=row["request_fingerprint"],
            actor_label=row["actor_label"],
        )
        evidence = ra_adapters.ActivateReconciliationAdapter().gather_evidence(entry)
        check("real reconcile activate: post_state_verified=True", evidence.post_state_verified is True)
        check("real reconcile activate: observed_post_hash matches", evidence.observed_post_hash == build_result.bundle_version)

        # Real reconciliation_operator merged registry includes the new families.
        registry = op._default_registry_factory()
        families = registry.known_action_families()
        check("real reconciliation_operator: 49 routing keys", len(families) == 49, len(families))
        check("real reconciliation_operator: rag_bundle.build registered", "rag_bundle.build" in families)
        check("real reconciliation_operator: rag_bundle.activate registered", "rag_bundle.activate" in families)
    finally:
        repo_conn.close()


# ================================================================
# ui.cli_mutate.main() - list + preview paths (faiss-free).
# ================================================================

def run_cli(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = cli_mutate.main(argv, mutation_conn_factory=pg_connect, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_cli_list_and_build_preview_real():
    code, out, err = run_cli(["rag-bundle", "--action", "list", "--actor-user-id", str(_ACTORS["operator"])])
    check("real CLI: list exit 0", code == 0, err)
    check("real CLI: list output mentions resource_key", "resource_key=global:rag_index" in out, out)

    code, out, err = run_cli(["rag-bundle", "--action", "build", "--actor-user-id", str(_ACTORS["operator"])])
    check("real CLI: build preview exit 0", code == 0, err)
    check("real CLI: build preview shows input_digest", "input_digest=" in out, out)

    code, out, err = run_cli(["rag-bundle", "--action", "build", "--actor-user-id", str(_ACTORS["ungranted"])])
    check("real CLI: build preview denied for ungranted actor", code == cli_mutate.EXIT_DOMAIN_ERROR, err)


def test_cli_activate_preview_real(build_result):
    code, out, err = run_cli([
        "rag-bundle", "--action", "activate", "--bundle-version", build_result.bundle_version,
        "--actor-user-id", str(_ACTORS["operator"]),
    ])
    check("real CLI: activate preview exit 0", code == 0, err)
    check("real CLI: activate preview shows has_build_audit", "has_build_audit=True" in out, out)


# ================================================================
# TARGETED F1-F4 REMEDIATION (T17-T21) - real disposable PostgreSQL.
# ================================================================

def _install_completion_block(resource_key):
    """P11-style, disposable-DB-only trigger: raises ONLY for THIS
    resource_key's own 'completed' transition - a genuine database-
    level `_mark_completed` failure, nothing in the production
    coordinator/facade/adapters is monkeypatched."""
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE OR REPLACE FUNCTION mutation.rag_bundle_block_completion() "
                "RETURNS trigger AS $$ BEGIN "
                "IF NEW.state = 'completed' AND NEW.resource_key = '" + resource_key + "' THEN "
                "RAISE EXCEPTION 'rag_bundle_remediation injected completion failure'; "
                "END IF; RETURN NEW; END $$ LANGUAGE plpgsql"
            )
            cur.execute(
                "CREATE TRIGGER rag_bundle_block_completion BEFORE UPDATE "
                "ON mutation.mutation_journal FOR EACH ROW "
                "EXECUTE FUNCTION mutation.rag_bundle_block_completion()"
            )
    finally:
        conn.close()


def _drop_completion_block():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TRIGGER IF EXISTS rag_bundle_block_completion ON mutation.mutation_journal")
            cur.execute("DROP FUNCTION IF EXISTS mutation.rag_bundle_block_completion()")
    finally:
        conn.close()


def _journal_row_by_id(journal_id):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, state, observed_post_hash, resolution_code, reconciled_by_actor_type, "
                "reconciled_by_actor_ref FROM mutation.mutation_journal WHERE id = %s",
                (journal_id,),
            )
            cols = [d.name for d in cur.description]
            row = cur.fetchone()
        return dict(zip(cols, row)) if row else None
    finally:
        conn.close()


def _latest_journal_row(resource_key, action_family, target_ref):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, state, observed_post_hash FROM mutation.mutation_journal "
                "WHERE resource_key = %s AND action_family = %s AND target_ref = %s "
                "ORDER BY id DESC LIMIT 1",
                (resource_key, action_family, target_ref),
            )
            cols = [d.name for d in cur.description]
            row = cur.fetchone()
        return dict(zip(cols, row)) if row else None
    finally:
        conn.close()


def test_t17_real_pg_a_b_a_b_activation_attempt_cycle():
    """T17 - real PostgreSQL, real journal, real advisory lock: A->B->A
    ->B(attempt=0) collapses onto the FIRST B-activation's own
    idempotency identity and fails replay corroboration loudly (pointer
    stays at A); B(attempt=1) is a genuinely NEW identity that really
    flips the pointer to B."""
    wipe_journal_and_index()
    principal = make_principal(_ACTORS["operator"])
    repo_conn = pg_connect()
    try:
        outer_repo = ga.PostgresGlobalResourceAuthzRepository(repo_conn)
        preview_a = facade.preview_build(build_attempt=0, principal=principal, authz_repository=outer_repo)
        result_a = facade.apply_build(
            preview_a["input_digest"], allow_network=True, build_attempt=0,
            principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
            snapshot_builder=make_snapshot_builder(build_index=17001),
        )
        preview_b = facade.preview_build(build_attempt=1, principal=principal, authz_repository=outer_repo)
        result_b = facade.apply_build(
            preview_b["input_digest"], allow_network=True, build_attempt=1,
            principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
            snapshot_builder=make_snapshot_builder(build_index=17002),
        )
        check("T17 setup: A and B are genuinely different bundles", result_a.bundle_version != result_b.bundle_version)

        facade.apply_activate(result_a.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=outer_repo, conn_factory=pg_connect)
        facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=0, principal=principal, authz_repository=outer_repo, conn_factory=pg_connect)
        facade.apply_activate(result_a.bundle_version, result_b.bundle_version, activation_attempt=0, principal=principal, authz_repository=outer_repo, conn_factory=pg_connect)

        pointer_path = _index_dir / "current_version.json"
        pointer_before = pointer_path.read_bytes()
        try:
            facade.apply_activate(result_b.bundle_version, result_a.bundle_version, activation_attempt=0, principal=principal, authz_repository=outer_repo, conn_factory=pg_connect)
            check("T17: final B(attempt=0) replay raises ActivationReplayVerificationError", False, "did not raise")
        except facade.ActivationReplayVerificationError:
            check("T17: final B(attempt=0) replay raises ActivationReplayVerificationError", True)
        check("T17: pointer bytes byte-unchanged after the rejected replay", pointer_path.read_bytes() == pointer_before)

        result_attempt1 = facade.apply_activate(
            result_b.bundle_version, result_a.bundle_version, activation_attempt=1,
            principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
        )
        check("T17: activation_attempt=1 genuinely executes", result_attempt1.replayed is False)
        pointer_state, current_version = facade._read_pointer_state(_index_dir)
        check("T17: pointer GENUINELY flips to B via activation_attempt=1", current_version == result_b.bundle_version)

        registry = op._default_registry_factory()
        check("T17: real reconciliation_operator registry still has 49 routing keys", len(registry.known_action_families()) == 49, len(registry.known_action_families()))
        return result_a, result_b
    finally:
        repo_conn.close()


def test_t18_real_pg_activate_mark_completed_crash_reconciles():
    """T18 - a REAL database-level `_mark_completed` failure for
    `rag_bundle.activate` (P11-style trigger): the pointer/audit are
    fully durable, the journal row stays `executing`/NULL, and the REAL
    merged production registry reconciles it to `completed` +
    `reconciled_completed_post_state_verified` WITHOUT the writer being
    invoked a second time."""
    wipe_journal_and_index()
    principal = make_principal(_ACTORS["operator"])
    repo_conn = pg_connect()
    try:
        outer_repo = ga.PostgresGlobalResourceAuthzRepository(repo_conn)
        preview = facade.preview_build(build_attempt=0, principal=principal, authz_repository=outer_repo)
        result = facade.apply_build(
            preview["input_digest"], allow_network=True, build_attempt=0,
            principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
            snapshot_builder=make_snapshot_builder(build_index=18001),
        )

        _install_completion_block(facade.RESOURCE_KEY)
        try:
            try:
                facade.apply_activate(result.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=outer_repo, conn_factory=pg_connect)
                check("T18a: injected completion failure propagates", False, "no exception raised")
            except Exception as error:
                check(
                    "T18a: the DB-level completion failure propagates as the REAL database error "
                    "(never re-classified as a writer failure)",
                    isinstance(error, psycopg.Error) and "injected completion failure" in str(error),
                    f"got {type(error).__name__}: {error!r}",
                )
        finally:
            _drop_completion_block()

        target_ref = f"{facade.ACTIVATE_TARGET_REF_PREFIX}{result.bundle_version}"
        row = _latest_journal_row(facade.RESOURCE_KEY, facade.ACTIVATE_ACTION_FAMILY, target_ref)
        check(
            "T18b: journal row stays 'executing' with observed_post_hash NULL",
            row is not None and row["state"] == "executing" and row["observed_post_hash"] is None,
            f"{row!r}",
        )

        pointer_path = _index_dir / "current_version.json"
        check("T18c: pointer IS durably at the target (writer effects fully succeeded)", pointer_path.read_bytes() == facade._canonical_json_bytes({"current_version": result.bundle_version}))
        audit_dir = facade._activate_audit_dir(_index_dir.resolve())
        audit_files_before = sorted(p.name for p in audit_dir.iterdir())
        check("T18d: exactly one activation audit file exists", len(audit_files_before) == 1)

        out_io, err_io = io.StringIO(), io.StringIO()
        rc = op.main(
            ["--journal-id", str(row["id"]), "--apply", "--actor-ref", f"rag-bundle-t18-{os.getpid()}"],
            conn_factory=pg_connect, stdout=out_io, stderr=err_io,
        )
        row_after = _journal_row_by_id(row["id"])
        check(
            "T18e: REAL merged-registry reconciliation resolves the row to completed + "
            "reconciled_completed_post_state_verified + cli_service provenance",
            rc == 0 and row_after["state"] == "completed"
            and row_after["resolution_code"] == "reconciled_completed_post_state_verified"
            and row_after["observed_post_hash"] == result.bundle_version
            and row_after["reconciled_by_actor_type"] == "cli_service"
            and row_after["reconciled_by_actor_ref"] == f"rag-bundle-t18-{os.getpid()}",
            f"rc={rc} row={row_after!r} err={err_io.getvalue()!r}",
        )
        audit_files_after = sorted(p.name for p in audit_dir.iterdir())
        check("T18f: the writer was NEVER invoked a second time (audit file set is invariant)", audit_files_after == audit_files_before)
    finally:
        repo_conn.close()
        _drop_completion_block()


def test_t19_real_pg_two_actor_build_mark_completed_crash_reconciles():
    """T19 - the F4 two-actor corner, closed against a REAL database:
    actor 1 publishes for real; actor 2 republishes IDENTICAL content
    (first_publish=False) but actor 2's OWN `_mark_completed` is made
    to fail at the database level. Reconciliation must resolve actor
    2's row to `completed` using actor 2's OWN bound audit - never
    actor 1's - proving the old false-`failed` corner (a shared,
    version-keyed audit file meant only ONE actor's row could ever be
    post-verified) is closed."""
    wipe_journal_and_index()
    principal1 = make_principal(_ACTORS["operator"])
    principal2 = make_principal(_ACTORS["operator2"])
    repo_conn1 = pg_connect()
    repo_conn2 = pg_connect()
    try:
        outer_repo1 = ga.PostgresGlobalResourceAuthzRepository(repo_conn1)
        outer_repo2 = ga.PostgresGlobalResourceAuthzRepository(repo_conn2)
        builder = make_snapshot_builder(build_index=19001)

        preview1 = facade.preview_build(build_attempt=0, principal=principal1, authz_repository=outer_repo1)
        result1 = facade.apply_build(
            preview1["input_digest"], allow_network=True, build_attempt=0,
            principal=principal1, authz_repository=outer_repo1, conn_factory=pg_connect, snapshot_builder=builder,
        )

        _install_completion_block(facade.RESOURCE_KEY)
        try:
            try:
                preview2 = facade.preview_build(build_attempt=0, principal=principal2, authz_repository=outer_repo2)
                facade.apply_build(
                    preview2["input_digest"], allow_network=True, build_attempt=0,
                    principal=principal2, authz_repository=outer_repo2, conn_factory=pg_connect, snapshot_builder=builder,
                )
                check("T19a: actor 2's injected completion failure propagates", False, "no exception raised")
            except Exception as error:
                check(
                    "T19a: actor 2's DB-level completion failure propagates as the REAL database error",
                    isinstance(error, psycopg.Error) and "injected completion failure" in str(error),
                    f"got {type(error).__name__}: {error!r}",
                )
        finally:
            _drop_completion_block()

        row2 = _latest_journal_row(facade.RESOURCE_KEY, facade.BUILD_ACTION_FAMILY, facade.BUILD_TARGET_REF)
        check(
            "T19b: actor 2's row stays 'executing' with observed_post_hash NULL",
            row2 is not None and row2["state"] == "executing" and row2["observed_post_hash"] is None,
            f"{row2!r}",
        )
        audit_dir = Path(result1.audit_path).parent
        audit_files = sorted(p.name for p in audit_dir.iterdir())
        check("T19c: TWO distinct per-actor build audits exist (not one shared file)", len(audit_files) == 2, audit_files)

        out_io, err_io = io.StringIO(), io.StringIO()
        rc = op.main(
            ["--journal-id", str(row2["id"]), "--apply", "--actor-ref", f"rag-bundle-t19-{os.getpid()}"],
            conn_factory=pg_connect, stdout=out_io, stderr=err_io,
        )
        row2_after = _journal_row_by_id(row2["id"])
        check(
            "T19d: actor 2's row reconciles to completed via ITS OWN bound audit "
            "(the F4 shared-audit false-failed corner is closed)",
            rc == 0 and row2_after["state"] == "completed"
            and row2_after["resolution_code"] == "reconciled_completed_post_state_verified"
            and row2_after["observed_post_hash"] == result1.bundle_version,
            f"rc={rc} row={row2_after!r} err={err_io.getvalue()!r}",
        )
        audit_files_after = sorted(p.name for p in audit_dir.iterdir())
        check("T19e: the writer was NEVER invoked a third time (audit file set is invariant)", audit_files_after == audit_files)
    finally:
        repo_conn1.close()
        repo_conn2.close()
        _drop_completion_block()


def test_t20_real_pg_w1_mkdir_failure_reconciles_to_failed():
    """T20 - a REAL W1 mkdir obstruction (index/audit/activate replaced
    by a plain file) against real PostgreSQL: the writer's exception
    propagates as `reconciliation_required`, the pointer is completely
    untouched (W1 runs BEFORE the pointer write), and reconciliation
    resolves it to `failed` + real cli_service provenance."""
    wipe_journal_and_index()
    principal = make_principal(_ACTORS["operator"])
    repo_conn = pg_connect()
    try:
        outer_repo = ga.PostgresGlobalResourceAuthzRepository(repo_conn)
        preview = facade.preview_build(build_attempt=0, principal=principal, authz_repository=outer_repo)
        result = facade.apply_build(
            preview["input_digest"], allow_network=True, build_attempt=0,
            principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
            snapshot_builder=make_snapshot_builder(build_index=20001),
        )

        activate_audit_dir = facade._activate_audit_dir(_index_dir.resolve())
        activate_audit_dir.parent.mkdir(parents=True, exist_ok=True)
        activate_audit_dir.write_bytes(b"obstruction - not a directory")

        try:
            facade.apply_activate(result.bundle_version, "none", activation_attempt=0, principal=principal, authz_repository=outer_repo, conn_factory=pg_connect)
            check("T20a: W1 mkdir obstruction propagates", False, "no exception raised")
        except OSError:
            check("T20a: W1 mkdir obstruction propagates", True)

        target_ref = f"{facade.ACTIVATE_TARGET_REF_PREFIX}{result.bundle_version}"
        row = _latest_journal_row(facade.RESOURCE_KEY, facade.ACTIVATE_ACTION_FAMILY, target_ref)
        check(
            "T20b: journal row reaches reconciliation_required",
            row is not None and row["state"] == "reconciliation_required",
            f"{row!r}",
        )
        pointer_state, _cv = facade._read_pointer_state(_index_dir)
        check("T20c: pointer remains completely untouched (absent)", pointer_state == "none")

        out_io, err_io = io.StringIO(), io.StringIO()
        rc = op.main(
            ["--journal-id", str(row["id"]), "--apply", "--actor-ref", f"rag-bundle-t20-{os.getpid()}"],
            conn_factory=pg_connect, stdout=out_io, stderr=err_io,
        )
        row_after = _journal_row_by_id(row["id"])
        check(
            "T20d: reconciliation resolves the row to failed with real cli_service provenance",
            rc == 0 and row_after["state"] == "failed"
            and row_after["reconciled_by_actor_type"] == "cli_service"
            and row_after["reconciled_by_actor_ref"] == f"rag-bundle-t20-{os.getpid()}",
            f"rc={rc} row={row_after!r} err={err_io.getvalue()!r}",
        )
    finally:
        repo_conn.close()
        activate_audit_dir = facade._activate_audit_dir(_index_dir.resolve())
        if activate_audit_dir.exists() and activate_audit_dir.is_file():
            activate_audit_dir.unlink()


def test_t21_real_cli_activate_preview_round_trip():
    """T21 - the `--activation-attempt` preview round-trip through the
    REAL `ui.cli_mutate.main()` entry point against real PostgreSQL."""
    wipe_journal_and_index()
    principal = make_principal(_ACTORS["operator"])
    repo_conn = pg_connect()
    try:
        outer_repo = ga.PostgresGlobalResourceAuthzRepository(repo_conn)
        preview = facade.preview_build(build_attempt=0, principal=principal, authz_repository=outer_repo)
        result = facade.apply_build(
            preview["input_digest"], allow_network=True, build_attempt=0,
            principal=principal, authz_repository=outer_repo, conn_factory=pg_connect,
            snapshot_builder=make_snapshot_builder(build_index=21001),
        )
    finally:
        repo_conn.close()

    code, out, err = run_cli([
        "rag-bundle", "--action", "activate", "--bundle-version", result.bundle_version,
        "--actor-user-id", str(_ACTORS["operator"]), "--activation-attempt", "2",
    ])
    check("T21a: real CLI activate preview exit 0", code == 0, err)
    check("T21b: real CLI activate preview shows activation_attempt=2", "activation_attempt=2" in out, out)
    check("T21c: real CLI activate preview shows bundle_manifest_sha256=", "bundle_manifest_sha256=" in out, out)
    check("T21d: real CLI activate preview shows activation_input_digest=", "activation_input_digest=" in out, out)
    check("T21e: real CLI activate preview's apply hint includes --activation-attempt 2", "--activation-attempt 2" in out, out)


def run_self_test():
    build_result = None
    try:
        test_grant_revoke_regrant_real_db()
        test_grant_admin_rejected_real_db()
        test_postgres_global_authz_repository_real()
        build_result = test_build_success_and_journal_real()
        test_build_fingerprint_conflict_real()
        test_build_snapshot_builder_crash_before_lock_real()
        test_build_writer_crash_reconciliation_real()
        test_lock_serialization_real()
        test_activate_and_reconciliation_real(build_result)
        test_cli_list_and_build_preview_real()
        test_cli_activate_preview_real(build_result)
        test_t17_real_pg_a_b_a_b_activation_attempt_cycle()
        test_t18_real_pg_activate_mark_completed_crash_reconciles()
        test_t19_real_pg_two_actor_build_mark_completed_crash_reconciles()
        test_t20_real_pg_w1_mkdir_failure_reconciles_to_failed()
        test_t21_real_cli_activate_preview_round_trip()
    finally:
        cleanup_fixture()
        repo_data_after = sha_tree(REAL_DATA_DIR)
        repo_index_after = sha_tree(REAL_INDEX_DIR)
        check("real data/ tree byte-unchanged", repo_data_after == _repo_data_before)
        check("real index/ tree byte-unchanged", repo_index_after == _repo_index_before)

    print(f"--- test_rag_bundle_mutation_integration_postgres: {passed} passed, {failed} failed, {skipped} skipped ---")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
