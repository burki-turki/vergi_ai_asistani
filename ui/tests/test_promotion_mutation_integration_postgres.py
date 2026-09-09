# ============================================================
# ROW 19C-3b SLICE 2 - REAL, END-TO-END PostgreSQL INTEGRATION PROOF
# for the promotion mutation path (ui/services/promotion_mutation_
# facade.py + promotion_mutation_adapters.py + the ui.cli_mutate
# `promotion` subcommand + ui/reconciliation_operator.py).
#
# WHAT IS REAL HERE: `ui.cli_mutate.main()` itself, `ui.services.
# cli_authz.CliActorAuthzRepository` against REAL iam rows, the real
# `mutation.mutation_journal`, real `pg_advisory_lock` session locking
# (observed via PostgreSQL's OWN pg_locks view), the REAL
# `src/fact_approval.py`/`src/timeline_approval.py` writers, and the
# REAL merged reconciliation registry (`ui.reconciliation_operator.
# _default_registry_factory()` - 37 routing keys).
#
# WHAT IS NOT REAL: the case tree (re-identified copies of
# data/cases/case_0001 under a fresh tempdir - the repository's own
# data/ tree is NEVER written, proven byte-for-byte at the end).
#
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_promotion_mutation_integration_postgres.py
# ============================================================

import io
import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

passed = 0
failed = 0
skipped = 0

_IS_WINDOWS = sys.platform == "win32"


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
    print(
        f"--- test_promotion_mutation_integration_postgres: {passed} passed, {failed} failed, "
        f"{skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip(
        "the entire real-PostgreSQL promotion integration suite",
        "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip(
        "the entire real-PostgreSQL promotion integration suite",
        f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                     # noqa: E402
import ui.reconciliation_operator as op                                 # noqa: E402
from ui.services import authz as _authz                                 # noqa: E402
from ui.services import cli_authz as _cli_authz                         # noqa: E402
from ui.services import mutation_lock as _mutation_lock                 # noqa: E402
from ui.services import promotion_mutation_facade as promo              # noqa: E402
from ui.services import promotion_mutation_adapters as promo_adapters   # noqa: E402
from ui.services import paths as _paths                                 # noqa: E402
from ui.services.common import PreconditionRaceDetectedError, sha256_file  # noqa: E402

import fact_approval                                                     # noqa: E402
import timeline_approval                                                 # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, resource_key, action_family, actor_user_id, target_ref, target_state, "
                "state, pre_revision, observed_post_hash, resolution_code, reconciled_by_actor_type, "
                "reconciled_by_actor_ref, executing_at FROM mutation.mutation_journal "
                "WHERE resource_key = %s ORDER BY id",
                (resource_key,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def full_journal_snapshot():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, resource_key, action_family, state, idempotency_key, observed_post_hash, "
                "resolution_code FROM mutation.mutation_journal ORDER BY id"
            )
            return cur.fetchall()
    finally:
        conn.close()


def advisory_lock_id_for(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT advisory_lock_id FROM mutation.mutation_resources WHERE resource_key = %s",
                (resource_key,),
            )
            row = cur.fetchone()
            return None if row is None else row[0]
    finally:
        conn.close()


def _count_advisory_locks(advisory_lock_id, *, granted):
    if advisory_lock_id is None:
        return 0
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND classid = %s AND objid = %s AND granted = %s",
                ((advisory_lock_id >> 32) & 0xFFFFFFFF, advisory_lock_id & 0xFFFFFFFF, granted),
            )
            (count,) = cur.fetchone()
            return count
    finally:
        conn.close()


def wait_for_lock_waiter(advisory_lock_id, *, timeout_seconds=30.0, poll_seconds=0.1):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _count_advisory_locks(advisory_lock_id, granted=False) > 0:
            return True
        time.sleep(poll_seconds)
    return False


# ----------------------------------------------------------------
# Preflight.
# ----------------------------------------------------------------

_preflight = pg_connect()
try:
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('iam.users'), to_regclass('mutation.mutation_resources'), "
            "to_regclass('mutation.mutation_journal')"
        )
        row = cur.fetchone()
    check("preflight: iam + mutation schemas all exist (migrations 0001-0004)", all(row))
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run against a half-migrated database.")
    summarize_and_exit()

_ACTORS = {
    "lawyer": 301,
    "analyst": 302,
    "revoked": 303,
}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"row19c3b-slice2-actor-{user_id}"),
            )
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('iam.users', 'id'), "
            "GREATEST((SELECT max(id) FROM iam.users), 1))"
        )
finally:
    _seed.close()


def seed_assignment(user_id, case_id, role):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO iam.case_assignments (user_id, case_id, role) VALUES (%s, %s, %s)",
                (user_id, case_id, role),
            )
    finally:
        conn.close()


def revoke_assignment(user_id, case_id):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE iam.case_assignments SET revoked_at = now() "
                "WHERE user_id = %s AND case_id = %s AND revoked_at IS NULL",
                (user_id, case_id),
            )
    finally:
        conn.close()


# ----------------------------------------------------------------
# Case fixtures under a fresh tempdir; CASES_DIR redirect sweep.
# ----------------------------------------------------------------

_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))
REAL_CASE_0001 = REPO_ROOT / "data" / "cases" / "case_0001"


def snapshot_real_data_tree():
    real_data_dir = REPO_ROOT / "data"
    out = {}
    for path in real_data_dir.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(real_data_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(real_data_dir))] = "<unreadable>"
    return out


def discover_cases_dir_holders():
    holders = []
    for module in list(sys.modules.values()):
        if getattr(module, "__file__", None) is None:
            continue
        candidate = getattr(module, "CASES_DIR", None)
        if candidate is None:
            continue
        try:
            if Path(os.path.realpath(str(candidate))) == _REAL_CASES_ROOT:
                holders.append(module)
        except Exception:
            continue
    return holders


_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_promo_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
_original_cases_dirs = [(m, m.CASES_DIR) for m in _cases_dir_holders]
check(
    "the CASES_DIR redirect sweep found ui.services.paths AND fact_approval AND timeline_approval",
    all(
        any(getattr(m, "__name__", "") == name for m in _cases_dir_holders)
        for name in ("ui.services.paths", "fact_approval", "timeline_approval")
    ),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

_real_data_before = snapshot_real_data_tree()

RUN_TOKEN = uuid.uuid4().hex[:8]
FACT_DOC = "dava_dilekcesi_001"

_junction_links = []
_outside_dirs = []


def make_junction(link_path: Path, target_path: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mklink /J failed rc={result.returncode}: {result.stdout!r} {result.stderr!r}")
    _junction_links.append(link_path)


def make_promotion_case(tag):
    case_id = f"promopg{RUN_TOKEN}{tag}"
    dst = _TMP_CASES / case_id
    shutil.copytree(REAL_CASE_0001, dst)
    for path in dst.rglob("*"):
        if path.is_file() and (path.suffix in (".json", ".pending", ".bak") or path.name.endswith(".json.pending")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "case_0001" in text:
                path.write_text(text.replace("case_0001", case_id), encoding="utf-8")
    return case_id, dst


def authz_conn_factory():
    return psycopg.connect(dbname=PG_DB)


def mutation_conn_factory():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def run_cli(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_mutate.main(
        argv,
        authz_conn_factory=authz_conn_factory,
        mutation_conn_factory=mutation_conn_factory,
        stdout=stdout, stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def make_pg_principal_and_repo(actor_user_id):
    conn = authz_conn_factory()
    principal = _cli_authz.build_cli_principal(conn, actor_user_id)
    repo = _cli_authz.CliActorAuthzRepository(conn)
    return principal, repo, conn


try:
    # ============================================================
    # P1 - same-case two-connection lock serialization (pg_locks proof).
    # ============================================================
    case_p1, dir_p1 = make_promotion_case("p1")
    seed_assignment(_ACTORS["lawyer"], case_p1, "lawyer")
    tl_p1 = dir_p1 / "timeline"
    pending_sha_p1 = sha256_file(tl_p1 / timeline_approval.CURRENT_PENDING_FILENAME)

    holder_conn = mutation_conn_factory()
    holder_lock_id = _mutation_lock.acquire_case_lock_session(holder_conn, case_p1)
    check("P1a holder connection genuinely holds the case advisory lock (pg_locks granted=True)",
          _count_advisory_locks(holder_lock_id, granted=True) >= 1)

    blocked_result = {}

    def run_blocked_promotion():
        principal, repo, conn = make_pg_principal_and_repo(_ACTORS["lawyer"])
        try:
            result = promo.approve_promotion_mutation(
                "timeline", case_p1, pending_sha_p1,
                principal=principal, authz_repository=repo, conn_factory=mutation_conn_factory,
            )
            blocked_result["result"] = result
        except Exception as error:  # pragma: no cover - surfaced via checks
            blocked_result["error"] = error
        finally:
            conn.close()

    worker = threading.Thread(target=run_blocked_promotion, daemon=True)
    worker.start()
    check("P1b pg_locks reports a genuinely WAITING advisory-lock request while the holder holds",
          wait_for_lock_waiter(holder_lock_id))
    check("P1c the promotion thread is still blocked (no result yet)",
          worker.is_alive() and "result" not in blocked_result and "error" not in blocked_result,
          f"{blocked_result!r}")
    _mutation_lock.release_lock_session(holder_conn, holder_lock_id)
    holder_conn.close()
    worker.join(timeout=120)
    check(
        "P1d after release the blocked promotion completes for real (journal completed, hash chain ok)",
        "result" in blocked_result
        and blocked_result["result"].replayed is False
        and journal_rows(f"case:{case_p1}")[0]["state"] == "completed"
        and journal_rows(f"case:{case_p1}")[0]["observed_post_hash"]
        == sha256_file(tl_p1 / "timeline.json"),
        f"{blocked_result!r}",
    )

    # ============================================================
    # P2 - fact fresh promotion END-TO-END через the real CLI.
    # ============================================================
    case_p2, dir_p2 = make_promotion_case("p2")
    seed_assignment(_ACTORS["lawyer"], case_p2, "lawyer")
    fact_pending_p2 = dir_p2 / "documents" / FACT_DOC / "extractions" / fact_approval.CURRENT_PENDING_FILENAME
    pending_sha_p2 = sha256_file(fact_pending_p2)
    expected_p2 = fact_approval.compute_expected_canonical_sha256(fact_pending_p2)

    code, out, err = run_cli([
        "promotion", "--case", case_p2, "--row-key", "fact", "--actor-user-id", str(_ACTORS["lawyer"]),
    ])
    check("P2a CLI fact enumeration preview exits 0 and lists the pending document",
          code == 0 and FACT_DOC in out and pending_sha_p2 in out, f"code={code} out={out!r} err={err!r}")

    code, out, err = run_cli([
        "promotion", "--case", case_p2, "--row-key", "fact", "--document", FACT_DOC,
        "--actor-user-id", str(_ACTORS["lawyer"]),
    ])
    check("P2b CLI fact single preview exits 0 with pending hash + validation_ready=True",
          code == 0 and pending_sha_p2 in out and "validation_ready=True" in out,
          f"code={code} out={out!r} err={err!r}")

    code, out, err = run_cli([
        "promotion", "--case", case_p2, "--row-key", "fact", "--document", FACT_DOC,
        "--actor-user-id", str(_ACTORS["lawyer"]),
        "--approve", "--expected-hash", pending_sha_p2,
    ])
    rows_p2 = journal_rows(f"case:{case_p2}")
    check("P2c CLI fact apply exits 0 (APPLIED)", code == 0 and "APPLIED promotion" in out,
          f"code={code} out={out!r} err={err!r}")
    check(
        "P2d REAL journal row: promotion.fact / fact.<doc>.canonical / approved / completed / "
        "observed == deterministic expected",
        len(rows_p2) == 1
        and rows_p2[0]["action_family"] == "promotion.fact"
        and rows_p2[0]["target_ref"] == f"fact.{FACT_DOC}.canonical"
        and rows_p2[0]["target_state"] == "approved"
        and rows_p2[0]["state"] == "completed"
        and rows_p2[0]["observed_post_hash"] == expected_p2
        and rows_p2[0]["actor_user_id"] == _ACTORS["lawyer"],
        f"{rows_p2!r}",
    )
    canonical_p2 = fact_pending_p2.parent / "facts.json"
    check("P2e canonical on disk matches the journaled observed hash", sha256_file(canonical_p2) == expected_p2)
    _audits_p2 = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (fact_pending_p2.parent / "reviews").glob("*.approval.json")
    ]
    _bound_p2 = [a for a in _audits_p2 if a.get("mutation_resource_key") == f"case:{case_p2}"]
    check(
        "P2f exactly one bound audit: mutation keys + actor_ref + promotion reviewer sentinel + "
        "pending/canonical hash bindings",
        len(_bound_p2) == 1
        and _bound_p2[0].get("mutation_actor_ref") == str(_ACTORS["lawyer"])
        and _bound_p2[0].get("reviewer_ref") == promo.PROMOTION_REVIEWER_REF
        and _bound_p2[0].get("source_pending_sha256") == pending_sha_p2
        and _bound_p2[0].get("canonical_sha256") == expected_p2,
        f"{_bound_p2!r}",
    )

    # ============================================================
    # P3 - safe replay via CLI: same apply argv again.
    # ============================================================
    audits_before_replay = len(list((fact_pending_p2.parent / "reviews").glob("*.approval.json")))
    code, out, err = run_cli([
        "promotion", "--case", case_p2, "--row-key", "fact", "--document", FACT_DOC,
        "--actor-user-id", str(_ACTORS["lawyer"]),
        "--approve", "--expected-hash", pending_sha_p2,
    ])
    check("P3a CLI replay exits 0 with replayed=True", code == 0 and "replayed=True" in out,
          f"code={code} out={out!r} err={err!r}")
    check(
        "P3b replay: STILL exactly one journal row and unchanged audit count (writer not re-invoked)",
        len(journal_rows(f"case:{case_p2}")) == 1
        and len(list((fact_pending_p2.parent / "reviews").glob("*.approval.json"))) == audits_before_replay,
    )

    # ============================================================
    # P4 - same identity + different note -> IdempotencyConflictError.
    # ============================================================
    code, out, err = run_cli([
        "promotion", "--case", case_p2, "--row-key", "fact", "--document", FACT_DOC,
        "--actor-user-id", str(_ACTORS["lawyer"]),
        "--approve", "--expected-hash", pending_sha_p2, "--note", "farklı not",
    ])
    check(
        "P4a different-note conflict -> clean domain error (exit 1, IdempotencyConflictError named)",
        code == 1 and "IdempotencyConflictError" in err,
        f"code={code} err={err!r}",
    )
    check("P4b conflict created no new journal row", len(journal_rows(f"case:{case_p2}")) == 1)

    # ============================================================
    # P5 - writer crash -> reconciliation_required -> REAL operator
    #      dry-run + REAL apply (failed + provenance).
    # ============================================================
    case_p5, dir_p5 = make_promotion_case("p5")
    seed_assignment(_ACTORS["lawyer"], case_p5, "lawyer")
    tl_p5 = dir_p5 / "timeline"
    pending_sha_p5 = sha256_file(tl_p5 / timeline_approval.CURRENT_PENDING_FILENAME)
    canonical_sha_before_p5 = sha256_file(tl_p5 / "timeline.json")

    _orig_atomic = timeline_approval.atomic_write_json

    def _raising_atomic(path, data):
        raise OSError("simulated canonical-write crash (P5)")

    principal_p5, repo_p5, conn_p5 = make_pg_principal_and_repo(_ACTORS["lawyer"])
    timeline_approval.atomic_write_json = _raising_atomic
    try:
        try:
            promo.approve_promotion_mutation(
                "timeline", case_p5, pending_sha_p5,
                principal=principal_p5, authz_repository=repo_p5, conn_factory=mutation_conn_factory,
            )
            check("P5a writer crash propagates", False, "no exception raised")
        except OSError:
            check("P5a writer crash propagates", True)
    finally:
        timeline_approval.atomic_write_json = _orig_atomic
        conn_p5.close()

    rows_p5 = journal_rows(f"case:{case_p5}")
    check(
        "P5b REAL journal row is reconciliation_required with NULL observed_post_hash",
        len(rows_p5) == 1 and rows_p5[0]["state"] == "reconciliation_required"
        and rows_p5[0]["observed_post_hash"] is None,
        f"{rows_p5!r}",
    )
    check("P5c canonical unchanged on disk", sha256_file(tl_p5 / "timeline.json") == canonical_sha_before_p5)

    jid_p5 = rows_p5[0]["id"]
    out_io, err_io = io.StringIO(), io.StringIO()
    rc = op.main(["--journal-id", str(jid_p5)], conn_factory=mutation_conn_factory,
                 stdout=out_io, stderr=err_io)
    check(
        "P5d operator DRY RUN exits 0 and reports would-resolve failed (pre-state proven unchanged)",
        rc == 0 and "failed" in out_io.getvalue(),
        f"rc={rc} out={out_io.getvalue()!r} err={err_io.getvalue()!r}",
    )
    check("P5e dry run issued ZERO journal changes",
          journal_rows(f"case:{case_p5}")[0]["state"] == "reconciliation_required")

    out_io, err_io = io.StringIO(), io.StringIO()
    rc = op.main(
        ["--journal-id", str(jid_p5), "--apply", "--actor-ref", f"slice2-test-{RUN_TOKEN}"],
        conn_factory=mutation_conn_factory, stdout=out_io, stderr=err_io,
    )
    rows_p5 = journal_rows(f"case:{case_p5}")
    check(
        "P5f REAL reconciliation apply -> failed + reconciled_failed_pre_state_confirmed_unchanged "
        "+ cli_service provenance",
        rc == 0 and rows_p5[0]["state"] == "failed"
        and rows_p5[0]["resolution_code"] == "reconciled_failed_pre_state_confirmed_unchanged"
        and rows_p5[0]["reconciled_by_actor_type"] == "cli_service"
        and rows_p5[0]["reconciled_by_actor_ref"] == f"slice2-test-{RUN_TOKEN}",
        f"rc={rc} rows={rows_p5!r} err={err_io.getvalue()!r}",
    )

    # ============================================================
    # P6 - F3/T2b class: audit-write crash AFTER canonical ->
    #      reconciliation_required; operator apply must NOT terminally
    #      resolve (dual-false; row stays blocked, no provenance).
    #
    # FIXTURE NOTE (real finding from this file's own first run): the
    # F3 class is only genuinely exercised when the canonical REALLY
    # TRANSITIONED. An OVERWRITE re-promotion of an already-promoted
    # pending is byte-IDEMPOTENT (build_canonical + the single-source
    # serializer reproduce the existing canonical exactly), so its
    # audit-crash leaves pending+canonical byte-identical to the
    # request-time pre-state - the composite pre-proof then LEGITIMATELY
    # resolves `failed` (see P6d below, which pins that corner down as
    # its own honest scenario). The dual-false contract case is
    # therefore built as FIRST-SAVE + audit crash: canonical absent at
    # request time, present after the crash - the composite really
    # changed, the deterministic post-match really holds, and ONLY the
    # missing success audit blocks auto-completion.
    # ============================================================
    case_p6, dir_p6 = make_promotion_case("p6")
    seed_assignment(_ACTORS["lawyer"], case_p6, "lawyer")
    fact_pending_p6 = dir_p6 / "documents" / FACT_DOC / "extractions" / fact_approval.CURRENT_PENDING_FILENAME
    (fact_pending_p6.parent / "facts.json").unlink()
    pending_sha_p6 = sha256_file(fact_pending_p6)
    expected_p6 = fact_approval.compute_expected_canonical_sha256(fact_pending_p6)

    _orig_audit_writer = fact_approval._write_audit_record_excl

    def _raising_audit_writer(reviews_dir, extraction_id, record):
        raise OSError("simulated audit-write crash (P6)")

    principal_p6, repo_p6, conn_p6 = make_pg_principal_and_repo(_ACTORS["lawyer"])
    fact_approval._write_audit_record_excl = _raising_audit_writer
    try:
        try:
            promo.approve_promotion_mutation(
                "fact", case_p6, pending_sha_p6, document_id=FACT_DOC,
                principal=principal_p6, authz_repository=repo_p6, conn_factory=mutation_conn_factory,
            )
            check("P6a audit-write crash propagates", False, "no exception raised")
        except OSError:
            check("P6a audit-write crash propagates", True)
    finally:
        fact_approval._write_audit_record_excl = _orig_audit_writer
        conn_p6.close()

    rows_p6 = journal_rows(f"case:{case_p6}")
    jid_p6 = rows_p6[0]["id"]
    check(
        "P6b journal reconciliation_required; canonical IS newly created (deterministic match) "
        "but the success audit is missing (genuine F3: the pre-state composite really changed)",
        rows_p6[0]["state"] == "reconciliation_required"
        and sha256_file(fact_pending_p6.parent / "facts.json") == expected_p6,
        f"{rows_p6!r}",
    )
    out_io, err_io = io.StringIO(), io.StringIO()
    rc = op.main(
        ["--journal-id", str(jid_p6), "--apply", "--actor-ref", f"slice2-test-{RUN_TOKEN}"],
        conn_factory=mutation_conn_factory, stdout=out_io, stderr=err_io,
    )
    rows_p6 = journal_rows(f"case:{case_p6}")
    check(
        "P6c F3 contract: dual-false -> NO terminal resolution, NO auto-completed, NO provenance "
        "(row remains reconciliation_required with NULL resolution_code/observed)",
        rows_p6[0]["state"] == "reconciliation_required"
        and rows_p6[0]["resolution_code"] is None
        and rows_p6[0]["observed_post_hash"] is None
        and rows_p6[0]["reconciled_by_actor_type"] is None,
        f"rc={rc} rows={rows_p6!r} out={out_io.getvalue()!r}",
    )

    # ---- P6d: the byte-IDEMPOTENT OVERWRITE corner, pinned honestly.
    # Audit-crash on an overwrite re-promotion of an already-promoted
    # pending leaves pending+canonical byte-identical to the request-
    # time pre-state (the composite pre-proof holds), so reconciliation
    # LEGITIMATELY resolves `failed` (pre_state_confirmed_unchanged) -
    # NEVER auto-completed (the missing audit still blocks that), and
    # the canonical stays byte-intact. ----
    case_p6d, dir_p6d = make_promotion_case("pd")
    seed_assignment(_ACTORS["lawyer"], case_p6d, "lawyer")
    fact_pending_p6d = dir_p6d / "documents" / FACT_DOC / "extractions" / fact_approval.CURRENT_PENDING_FILENAME
    pending_sha_p6d = sha256_file(fact_pending_p6d)
    canonical_sha_before_p6d = sha256_file(fact_pending_p6d.parent / "facts.json")
    principal_p6d, repo_p6d, conn_p6d = make_pg_principal_and_repo(_ACTORS["lawyer"])
    fact_approval._write_audit_record_excl = _raising_audit_writer
    try:
        try:
            promo.approve_promotion_mutation(
                "fact", case_p6d, pending_sha_p6d, document_id=FACT_DOC,
                principal=principal_p6d, authz_repository=repo_p6d, conn_factory=mutation_conn_factory,
            )
            check("P6d1 overwrite audit-write crash propagates", False, "no exception raised")
        except OSError:
            check("P6d1 overwrite audit-write crash propagates", True)
    finally:
        fact_approval._write_audit_record_excl = _orig_audit_writer
        conn_p6d.close()
    rows_p6d = journal_rows(f"case:{case_p6d}")
    out_io, err_io = io.StringIO(), io.StringIO()
    rc = op.main(
        ["--journal-id", str(rows_p6d[0]["id"]), "--apply", "--actor-ref", f"slice2-test-{RUN_TOKEN}"],
        conn_factory=mutation_conn_factory, stdout=out_io, stderr=err_io,
    )
    rows_p6d = journal_rows(f"case:{case_p6d}")
    check(
        "P6d2 idempotent-overwrite corner: composite pre-proof holds -> resolves failed "
        "(pre_state_confirmed_unchanged) with provenance; canonical byte-intact; NEVER completed",
        rc == 0 and rows_p6d[0]["state"] == "failed"
        and rows_p6d[0]["resolution_code"] == "reconciled_failed_pre_state_confirmed_unchanged"
        and rows_p6d[0]["reconciled_by_actor_type"] == "cli_service"
        and sha256_file(fact_pending_p6d.parent / "facts.json") == canonical_sha_before_p6d,
        f"rc={rc} rows={rows_p6d!r}",
    )

    # ============================================================
    # P7 - prepared-never-executed recovery against the REAL database.
    # ============================================================
    case_p7, dir_p7 = make_promotion_case("p7")
    seed_assignment(_ACTORS["lawyer"], case_p7, "lawyer")
    tl_p7 = dir_p7 / "timeline"
    pending_sha_p7 = sha256_file(tl_p7 / timeline_approval.CURRENT_PENDING_FILENAME)
    composite_p7 = promo_adapters._compute_promotion_composite(
        tl_p7 / timeline_approval.CURRENT_PENDING_FILENAME, tl_p7 / "timeline.json",
    )
    # A resource row must exist before inserting a journal row for it.
    _rk_conn = mutation_conn_factory()
    _lid = _mutation_lock.acquire_case_lock_session(_rk_conn, case_p7)
    _mutation_lock.release_lock_session(_rk_conn, _lid)
    _rk_conn.close()
    _ins = pg_connect()
    try:
        with _ins.cursor() as cur:
            cur.execute(
                "INSERT INTO mutation.mutation_journal (resource_key, action_family, actor_user_id, "
                "actor_label, target_ref, target_state, pre_hash, pre_revision, idempotency_key, "
                "request_fingerprint, state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'prepared') "
                "RETURNING id",
                (
                    f"case:{case_p7}", "promotion.timeline", _ACTORS["lawyer"], "iam_user",
                    "timeline.canonical", "approved", composite_p7, pending_sha_p7,
                    uuid.uuid4().hex + uuid.uuid4().hex, uuid.uuid4().hex + uuid.uuid4().hex,
                ),
            )
            (jid_p7,) = cur.fetchone()
    finally:
        _ins.close()
    out_io, err_io = io.StringIO(), io.StringIO()
    rc = op.main(
        ["--journal-id", str(jid_p7), "--apply", "--actor-ref", f"slice2-test-{RUN_TOKEN}"],
        conn_factory=mutation_conn_factory, stdout=out_io, stderr=err_io,
    )
    rows_p7 = journal_rows(f"case:{case_p7}")
    check(
        "P7a prepared-never-executed -> failed + reconciled_failed_prepared_never_executed + "
        "executing_at stays NULL",
        rc == 0 and rows_p7[0]["state"] == "failed"
        and rows_p7[0]["resolution_code"] == "reconciled_failed_prepared_never_executed"
        and rows_p7[0]["executing_at"] is None,
        f"rc={rc} rows={rows_p7!r} err={err_io.getvalue()!r}",
    )

    # ============================================================
    # P8 - inner authz revocation while WAITING for the real lock.
    # ============================================================
    case_p8, dir_p8 = make_promotion_case("p8")
    seed_assignment(_ACTORS["revoked"], case_p8, "lawyer")
    tl_p8 = dir_p8 / "timeline"
    pending_sha_p8 = sha256_file(tl_p8 / timeline_approval.CURRENT_PENDING_FILENAME)

    holder_conn8 = mutation_conn_factory()
    holder_lock8 = _mutation_lock.acquire_case_lock_session(holder_conn8, case_p8)
    blocked8 = {}

    def run_revoked_promotion():
        principal, repo, conn = make_pg_principal_and_repo(_ACTORS["revoked"])
        try:
            promo.approve_promotion_mutation(
                "timeline", case_p8, pending_sha_p8,
                principal=principal, authz_repository=repo, conn_factory=mutation_conn_factory,
            )
            blocked8["result"] = "unexpected success"
        except Exception as error:
            blocked8["error"] = error
        finally:
            conn.close()

    worker8 = threading.Thread(target=run_revoked_promotion, daemon=True)
    worker8.start()
    check("P8a a real waiter is queued on the case lock", wait_for_lock_waiter(holder_lock8))
    revoke_assignment(_ACTORS["revoked"], case_p8)
    _mutation_lock.release_lock_session(holder_conn8, holder_lock8)
    holder_conn8.close()
    worker8.join(timeout=120)
    check(
        "P8b under-lock INNER authz denies the revoked actor (CaseAccessDeniedError)",
        isinstance(blocked8.get("error"), _authz.CaseAccessDeniedError),
        f"{blocked8!r}",
    )
    check("P8c revoked attempt wrote ZERO journal rows", journal_rows(f"case:{case_p8}") == [])
    check("P8d canonical untouched", sha256_file(tl_p8 / "timeline.json") is not None)

    # ============================================================
    # P9 - outer authz denials via the REAL CLI (existence-blind).
    # ============================================================
    _journal_before_p9 = full_journal_snapshot()
    code, out, err = run_cli([
        "promotion", "--case", case_p2, "--row-key", "fact", "--document", FACT_DOC,
        "--actor-user-id", str(_ACTORS["analyst"]),
        "--approve", "--expected-hash", pending_sha_p2,
    ])
    check("P9a analyst (no mutate capability) apply -> fixed denial, exit 1",
          code == 1 and "yetkisiz" in err, f"code={code} err={err!r}")
    code, out, err = run_cli([
        "promotion", "--case", case_p2, "--row-key", "fact", "--document", FACT_DOC,
        "--actor-user-id", "999999",
        "--approve", "--expected-hash", pending_sha_p2,
    ])
    check("P9b nonexistent actor -> the SAME fixed denial (existence-blind), exit 1",
          code == 1 and "yetkisiz" in err, f"code={code} err={err!r}")
    check("P9c denials produced ZERO journal changes (full row set identical)",
          full_journal_snapshot() == _journal_before_p9)

    # ============================================================
    # P10 - real junction escape under the real-PG environment.
    # ============================================================
    if _IS_WINDOWS:
        case_p10, dir_p10 = make_promotion_case("pa")
        seed_assignment(_ACTORS["lawyer"], case_p10, "lawyer")
        tl_p10 = dir_p10 / "timeline"
        outside_p10 = Path(tempfile.mkdtemp(prefix="vergi_promo_pg_outside_"))
        _outside_dirs.append(outside_p10)
        target_p10 = outside_p10 / "tl_target"
        shutil.copytree(tl_p10, target_p10)
        pending_sha_p10 = sha256_file(target_p10 / timeline_approval.CURRENT_PENDING_FILENAME)
        shutil.rmtree(tl_p10)
        make_junction(tl_p10, target_p10)
        _journal_before_p10 = full_journal_snapshot()
        principal_p10, repo_p10, conn_p10 = make_pg_principal_and_repo(_ACTORS["lawyer"])
        try:
            try:
                promo.approve_promotion_mutation(
                    "timeline", case_p10, pending_sha_p10,
                    principal=principal_p10, authz_repository=repo_p10, conn_factory=mutation_conn_factory,
                )
                check("P10a live junction escape refused under real PG", False, "no exception")
            except promo.PromotionNestedPathContainmentError:
                check("P10a live junction escape refused under real PG", True)
        finally:
            conn_p10.close()
        check("P10b escape refusal produced ZERO journal changes",
              full_journal_snapshot() == _journal_before_p10)
    else:
        skip("P10 Windows NTFS junction escape under real PG", "sys.platform != 'win32'")

    # ============================================================
    # P11 - REAL-PostgreSQL `_mark_completed` FAILURE: the writer's
    # filesystem effects fully succeed (canonical + bound success audit
    # + backup), then the journal's OWN `state='completed'` UPDATE is
    # made to fail AT THE DATABASE LEVEL - a disposable-DB-only BEFORE
    # UPDATE trigger that raises ONLY for this scenario's exact
    # resource_key + the 'completed' transition. NOTHING in the
    # production coordinator/facade/adapters is monkeypatched: the
    # genuine coordinator behavior is observed as-is (the raise happens
    # OUTSIDE run_mutation()'s writer try/except, so it must NOT be
    # mis-classified as a writer failure / reconciliation_required -
    # the row stays 'executing' with observed_post_hash NULL). After
    # the trigger is dropped (finally), the REAL merged production
    # registry reconciles the row: the promotion adapter independently
    # post-verifies via the deterministic canonical hash + exactly-one
    # fully-bound success audit -> real `completed` +
    # reconciled_completed_post_state_verified + cli_service
    # provenance, with the writer NEVER invoked a second time (audit
    # file count + canonical hash byte-invariant across the
    # reconciliation).
    #
    # BOTH families run for real: their audit binding contracts differ
    # (fact: source_pending_sha256 + const `decision`; timeline:
    # pending_sha256 + approved/rollback flags + the Slice 2
    # canonical_sha256 field), so a single family would not prove the
    # other family's adapter post-state bindings against a real
    # database.
    # ============================================================

    def _install_completion_block(resource_key):
        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE OR REPLACE FUNCTION mutation.row19c3b_s2_block_completion() "
                    "RETURNS trigger AS $$ BEGIN "
                    "IF NEW.state = 'completed' AND NEW.resource_key = '" + resource_key + "' THEN "
                    "RAISE EXCEPTION 'row19c3b_slice2 injected completion failure'; "
                    "END IF; RETURN NEW; END $$ LANGUAGE plpgsql"
                )
                cur.execute(
                    "CREATE TRIGGER row19c3b_s2_block_completion BEFORE UPDATE "
                    "ON mutation.mutation_journal FOR EACH ROW "
                    "EXECUTE FUNCTION mutation.row19c3b_s2_block_completion()"
                )
        finally:
            conn.close()

    def _drop_completion_block():
        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DROP TRIGGER IF EXISTS row19c3b_s2_block_completion ON mutation.mutation_journal"
                )
                cur.execute("DROP FUNCTION IF EXISTS mutation.row19c3b_s2_block_completion()")
        finally:
            conn.close()

    for _family, _tag in (("fact", "cf"), ("timeline", "ct")):
        case_p11, dir_p11 = make_promotion_case(_tag)
        seed_assignment(_ACTORS["lawyer"], case_p11, "lawyer")
        if _family == "fact":
            pending_p11 = dir_p11 / "documents" / FACT_DOC / "extractions" / fact_approval.CURRENT_PENDING_FILENAME
            canonical_p11 = pending_p11.parent / "facts.json"
            reviews_p11 = pending_p11.parent / "reviews"
            history_p11 = pending_p11.parent / "history"
            backup_prefix_p11 = "facts_before_promotion_"
            expected_p11 = fact_approval.compute_expected_canonical_sha256(pending_p11)
            doc_kwargs = {"document_id": FACT_DOC}
        else:
            tl = dir_p11 / "timeline"
            pending_p11 = tl / timeline_approval.CURRENT_PENDING_FILENAME
            canonical_p11 = tl / "timeline.json"
            reviews_p11 = tl / "reviews"
            history_p11 = tl / "history"
            backup_prefix_p11 = "timeline_before_promotion_"
            expected_p11 = timeline_approval.compute_expected_canonical_sha256(pending_p11)
            doc_kwargs = {}
        pending_sha_p11 = sha256_file(pending_p11)
        rk_p11 = f"case:{case_p11}"

        principal_p11, repo_p11, conn_p11 = make_pg_principal_and_repo(_ACTORS["lawyer"])
        _install_completion_block(rk_p11)
        try:
            try:
                promo.approve_promotion_mutation(
                    _family, case_p11, pending_sha_p11, **doc_kwargs,
                    principal=principal_p11, authz_repository=repo_p11,
                    conn_factory=mutation_conn_factory,
                )
                check(f"P11a[{_family}] injected completion failure propagates", False, "no exception raised")
            except Exception as p11_err:
                check(
                    f"P11a[{_family}] the DB-level completion failure propagates as the REAL "
                    "database error (never re-classified as a writer failure)",
                    isinstance(p11_err, psycopg.Error)
                    and "injected completion failure" in str(p11_err),
                    f"got {type(p11_err).__name__}: {p11_err!r}",
                )
        finally:
            _drop_completion_block()
            conn_p11.close()

        rows_p11 = journal_rows(rk_p11)
        check(
            f"P11b[{_family}] journal row stays 'executing' with observed_post_hash NULL and a "
            "real executing_at (NOT reconciliation_required, NOT completed, NOT failed)",
            len(rows_p11) == 1 and rows_p11[0]["state"] == "executing"
            and rows_p11[0]["observed_post_hash"] is None
            and rows_p11[0]["executing_at"] is not None,
            f"{rows_p11!r}",
        )
        _bound_audits_p11 = []
        for p in reviews_p11.glob("*.approval.json"):
            rec = json.loads(p.read_text(encoding="utf-8"))
            if rec.get("mutation_resource_key") == rk_p11:
                _bound_audits_p11.append(rec)
        check(
            f"P11c[{_family}] writer effects ARE fully durable: canonical == deterministic "
            "expected, exactly ONE bound success audit, and a canonical backup in history/",
            sha256_file(canonical_p11) == expected_p11
            and len(_bound_audits_p11) == 1
            and any(p.name.startswith(backup_prefix_p11) for p in history_p11.glob("*")),
            f"canonical={sha256_file(canonical_p11)!r} expected={expected_p11!r} "
            f"bound_audits={len(_bound_audits_p11)} history={[p.name for p in history_p11.glob('*')]!r}",
        )

        audit_count_before_recon = len(list(reviews_p11.glob("*.approval.json")))
        out_io, err_io = io.StringIO(), io.StringIO()
        rc = op.main(
            ["--journal-id", str(rows_p11[0]["id"]), "--apply", "--actor-ref", f"slice2-test-{RUN_TOKEN}"],
            conn_factory=mutation_conn_factory, stdout=out_io, stderr=err_io,
        )
        rows_p11 = journal_rows(rk_p11)
        check(
            f"P11d[{_family}] REAL merged-registry reconciliation resolves the stale-executing "
            "row to completed + reconciled_completed_post_state_verified + cli_service provenance "
            "+ observed_post_hash == deterministic canonical hash",
            rc == 0 and rows_p11[0]["state"] == "completed"
            and rows_p11[0]["resolution_code"] == "reconciled_completed_post_state_verified"
            and rows_p11[0]["observed_post_hash"] == expected_p11
            and rows_p11[0]["reconciled_by_actor_type"] == "cli_service"
            and rows_p11[0]["reconciled_by_actor_ref"] == f"slice2-test-{RUN_TOKEN}",
            f"rc={rc} rows={rows_p11!r} err={err_io.getvalue()!r}",
        )
        check(
            f"P11e[{_family}] the writer was NEVER invoked a second time (audit file count and "
            "canonical bytes are invariant across the reconciliation)",
            len(list(reviews_p11.glob("*.approval.json"))) == audit_count_before_recon
            and sha256_file(canonical_p11) == expected_p11,
        )

    _residue_conn = pg_connect()
    try:
        with _residue_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_trigger WHERE tgname = 'row19c3b_s2_block_completion'")
            (_trig_count,) = cur.fetchone()
            cur.execute("SELECT count(*) FROM pg_proc WHERE proname = 'row19c3b_s2_block_completion'")
            (_proc_count,) = cur.fetchone()
    finally:
        _residue_conn.close()
    check(
        "P11f no injected trigger/function residue remains in the database",
        _trig_count == 0 and _proc_count == 0,
        f"trigger={_trig_count} function={_proc_count}",
    )

finally:
    for link in _junction_links:
        try:
            if os.path.lexists(link):
                os.rmdir(link)
        except OSError as cleanup_error:
            print(f"CLEANUP WARNING: link {link}: {cleanup_error!r}")
    for _m, _orig in _original_cases_dirs:
        _m.CASES_DIR = _orig
    try:
        shutil.rmtree(_TMP_ROOT)
    except OSError as cleanup_error:
        print(f"CLEANUP WARNING: tmp root {_TMP_ROOT}: {cleanup_error!r}")
    for outside in _outside_dirs:
        try:
            if outside.exists():
                shutil.rmtree(outside)
        except OSError as cleanup_error:
            print(f"CLEANUP WARNING: outside dir {outside}: {cleanup_error!r}")

check(
    "FINAL: the REAL repository data/ tree is byte-for-byte UNCHANGED",
    snapshot_real_data_tree() == _real_data_before,
)
check("FINAL: tmp cases root fully removed", not _TMP_ROOT.exists())

summarize_and_exit()
