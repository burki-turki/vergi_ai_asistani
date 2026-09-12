# ============================================================
# ROW 19C-3c-iv SLICE 1 - REAL, END-TO-END PostgreSQL INTEGRATION PROOF
# for the case-scoped, deterministic+agent (retrieval/discovery
# deferred) legal_research/case_law generation mutation path
# (ui/services/legal_research_case_law_mutation_facade.py +
# legal_research_case_law_mutation_adapters.py + the ui.cli_mutate
# `generation` subcommand's two new row-keys + the merged
# ui/reconciliation_operator.py registry, 47 routing keys).
#
# WHAT IS REAL HERE: `ui.cli_mutate.main()` itself, `ui.services.
# cli_authz.CliActorAuthzRepository` against REAL iam rows, the real
# `mutation.mutation_journal`, real `pg_advisory_lock` session locking
# (including a genuine two-connection lock-serialization proof via
# PostgreSQL's OWN `pg_locks` view), the REAL `src/legal_research_
# engine.py`/`src/case_law_engine.py` writers, and the REAL merged
# reconciliation registry.
#
# WHAT IS NOT REAL: the case tree (re-identified copies of data/cases/
# case_0001 under a fresh tempdir); the LLM client for agent-mode
# scenarios (an explicit, in-process `llm_client=` test seam passed
# DIRECTLY to `preview_generation()`/`apply_generation()` - NEVER
# through the CLI, which never exposes this parameter); for ONE
# scenario only (H-series), the GLOBAL `documents.json`/`provisions.
# json` roots are redirected to a fresh tempdir copy (never the real
# repository files, which are read-only elsewhere in this suite and
# never touched at all). Retrieval/discovery is NEVER triggered
# anywhere in this file (no --with-discovery flag exists on the CLI;
# `use_discovery=False`/`retrieval_fn=None` are hardwired facade
# constants). The repository's own data/ tree is NEVER written, proven
# byte-for-byte at the end.
#
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_legal_research_case_law_mutation_integration_postgres.py
# ============================================================

import io
import hashlib
import json
import os
import shutil
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
        f"--- test_legal_research_case_law_mutation_integration_postgres: {passed} passed, "
        f"{failed} failed, {skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip(
        "the entire real-PostgreSQL legal_research/case_law integration suite",
        "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip(
        "the entire real-PostgreSQL legal_research/case_law integration suite",
        f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                     # noqa: E402
import ui.reconciliation_operator as op                                 # noqa: E402
from ui.services import cli_authz as _cli_authz                         # noqa: E402
from ui.services import mutation_lock as _mutation_lock                 # noqa: E402
from ui.services import legal_research_case_law_mutation_facade as lrc  # noqa: E402
from ui.services import legal_research_case_law_mutation_adapters as ada  # noqa: E402
from ui.services import paths as _paths                                 # noqa: E402
from ui.services.common import sha256_file                              # noqa: E402

import legal_research_engine as lre                                     # noqa: E402
import case_law_engine as cle                                            # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, resource_key, action_family, actor_user_id, target_ref, target_state, "
                "state, pre_revision, idempotency_key, observed_post_hash, resolution_code, "
                "reconciled_by_actor_type, reconciled_by_actor_ref FROM mutation.mutation_journal "
                "WHERE resource_key = %s ORDER BY id",
                (resource_key,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _count_advisory_locks(advisory_lock_id, *, granted):
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

_ACTORS = {"lawyer": 601, "analyst": 602}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"row19c3civ-lrcl-actor-{user_id}"),
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


_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_lrcl_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
check(
    "the CASES_DIR redirect sweep found ui.services.paths AND legal_research_engine AND "
    "case_law_engine",
    all(
        any(getattr(m, "__name__", "") == name for m in _cases_dir_holders)
        for name in ("ui.services.paths", "legal_research_engine", "case_law_engine")
    ),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

_real_data_before = snapshot_real_data_tree()

RUN_TOKEN = uuid.uuid4().hex[:8]


def make_generation_case(tag):
    case_id = f"lrclpg{RUN_TOKEN}{tag}"
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
    for family_dir_name in ("research", "case_law"):
        family_dir = dst / family_dir_name
        if not family_dir.exists():
            continue
        for stale in family_dir.glob("*.pending"):
            stale.unlink()
        for stale_dir_name in ("history", "generation_reviews"):
            stale_dir = family_dir / stale_dir_name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
    return case_id, dst


def authz_conn_factory():
    return psycopg.connect(dbname=PG_DB)


def mutation_conn_factory():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def run_cli(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_mutate.main(
        argv, authz_conn_factory=authz_conn_factory, mutation_conn_factory=mutation_conn_factory,
        stdout=stdout, stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def preview_input_digest(case_id, row_key, *, with_agent=False, actor_user_id=None):
    args = [
        "generation", "--case", case_id, "--row-key", row_key,
        "--actor-user-id", str(actor_user_id if actor_user_id is not None else _ACTORS["lawyer"]),
    ]
    if with_agent:
        args.append("--with-agent")
    code, out, err = run_cli(args)
    if code != 0:
        raise AssertionError(f"preview failed: code={code} out={out!r} err={err!r}")
    for line in out.splitlines():
        if line.startswith("input_digest="):
            return line[len("input_digest="):]
    raise AssertionError(f"input_digest= not found in preview output: {out!r}")


try:
    # ============================================================
    # B1 - legal_research fresh deterministic generation, END-TO-END
    #      through the real CLI.
    # ============================================================
    case_b1, dir_b1 = make_generation_case("b1")
    seed_assignment(_ACTORS["lawyer"], case_b1, "lawyer")

    digest_b1 = preview_input_digest(case_b1, "legal_research")
    code, out, err = run_cli([
        "generation", "--case", case_b1, "--row-key", "legal_research",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_b1,
    ])
    check("B1a CLI legal_research apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    pending_path_b1 = lre.get_pending_path(case_b1)
    check("B1b the REAL pending file was written", pending_path_b1.is_file())
    rows_b1 = journal_rows(f"case:{case_b1}")
    check(
        "B1c exactly one REAL journal row, state='completed', action_family='generation.legal_research'",
        len(rows_b1) == 1 and rows_b1[0]["state"] == "completed"
        and rows_b1[0]["action_family"] == "generation.legal_research"
        and rows_b1[0]["target_ref"] == "legal_research.pending"
        and rows_b1[0]["target_state"] == "generated",
        f"rows={rows_b1}",
    )
    check(
        "B1d journal row's observed_post_hash matches the REAL on-disk pending bytes",
        rows_b1[0]["observed_post_hash"] == sha256_file(pending_path_b1),
    )
    check(
        "B1e a real *.generation_audit.json audit file exists under generation_reviews/",
        any(lre.get_reviews_dir(case_b1).glob("*.generation_audit.json")),
    )

    # ============================================================
    # B2 - case_law fresh deterministic generation, END-TO-END through
    #      the real CLI.
    # ============================================================
    case_b2, dir_b2 = make_generation_case("b2")
    seed_assignment(_ACTORS["lawyer"], case_b2, "lawyer")

    digest_b2 = preview_input_digest(case_b2, "case_law")
    code, out, err = run_cli([
        "generation", "--case", case_b2, "--row-key", "case_law",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_b2,
    ])
    check("B2a CLI case_law apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    pending_path_b2 = cle.get_pending_path(case_b2)
    check("B2b the REAL pending file was written", pending_path_b2.is_file())
    rows_b2 = journal_rows(f"case:{case_b2}")
    check(
        "B2c exactly one REAL journal row, state='completed', action_family='generation.case_law'",
        len(rows_b2) == 1 and rows_b2[0]["state"] == "completed"
        and rows_b2[0]["action_family"] == "generation.case_law"
        and rows_b2[0]["target_ref"] == "case_law.pending",
        f"rows={rows_b2}",
    )

    # ============================================================
    # B3 - SAFE REPLAY via the real CLI.
    # ============================================================
    pending_bytes_b1_before_replay = pending_path_b1.read_bytes()
    code, out, err = run_cli([
        "generation", "--case", case_b1, "--row-key", "legal_research",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_b1,
    ])
    check("B3a a real CLI replay of the SAME apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    check("B3b replayed=True was reported by the CLI", "replayed=True" in out, f"out={out!r}")
    check(
        "B3c pending bytes BYTE-IDENTICAL to before the replay (writer NOT re-invoked)",
        pending_path_b1.read_bytes() == pending_bytes_b1_before_replay,
    )
    check("B3d still exactly ONE journal row for this resource_key", len(journal_rows(f"case:{case_b1}")) == 1)

    # ============================================================
    # B4 - STALE INPUT_DIGEST rejection: mutate a case-scoped manifest
    #      input after preview, apply with the now-stale
    #      expected_input_digest -> clean domain error, zero NEW journal
    #      rows. (This family has NO extra generation parameter of its
    #      own - unlike deadline's --calendar-complete - so a genuine
    #      "same identity, different fingerprint" conflict is
    #      structurally unreachable via the public API; this stale-
    #      digest scenario is the realistic equivalent.)
    # ============================================================
    case_b4, dir_b4 = make_generation_case("b4")
    seed_assignment(_ACTORS["lawyer"], case_b4, "lawyer")
    digest_b4 = preview_input_digest(case_b4, "legal_research")
    timeline_path_b4 = dir_b4 / "timeline" / "timeline.json"
    original_timeline_bytes_b4 = timeline_path_b4.read_bytes()
    mutated_b4 = json.loads(original_timeline_bytes_b4.decode("utf-8"))
    mutated_b4["_test_mutation_marker"] = "stale-digest-test"
    timeline_path_b4.write_text(json.dumps(mutated_b4), encoding="utf-8")
    code, out, err = run_cli([
        "generation", "--case", case_b4, "--row-key", "legal_research",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_b4,
    ])
    check("B4a stale-digest apply exits non-zero (domain error)", code != 0, f"code={code} out={out!r} err={err!r}")
    check("B4b zero journal rows created for the stale attempt", journal_rows(f"case:{case_b4}") == [])
    timeline_path_b4.write_bytes(original_timeline_bytes_b4)

    # ============================================================
    # B5 - NETWORK GATE, via the real CLI, pure usage-shape rejections
    #      BEFORE any connection.
    # ============================================================
    code, out, err = run_cli([
        "generation", "--case", case_b1, "--row-key", "legal_research",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--allow-network",
    ])
    check("B5a --allow-network alone (no --with-agent) rejected with usage error", code == 2, f"code={code} err={err!r}")
    code, out, err = run_cli([
        "generation", "--case", case_b1, "--row-key", "case_law",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--document", "some_doc",
    ])
    check("B5b --document rejected for --row-key case_law", code == 2, f"code={code} err={err!r}")
    code, out, err = run_cli([
        "generation", "--case", case_b1, "--row-key", "legal_research",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--anchor", "timeline_event_003",
    ])
    check("B5c --anchor rejected for --row-key legal_research", code == 2, f"code={code} err={err!r}")

    # ============================================================
    # B6 - ANALYST: preview allowed, apply denied (existence-blind);
    #      a nonexistent actor gets the IDENTICAL denial.
    # ============================================================
    case_b6, dir_b6 = make_generation_case("b6")
    seed_assignment(_ACTORS["lawyer"], case_b6, "lawyer")
    seed_assignment(_ACTORS["analyst"], case_b6, "analyst")
    digest_b6 = preview_input_digest(case_b6, "legal_research", actor_user_id=_ACTORS["analyst"])
    check("B6a analyst preview succeeded (read capability)", isinstance(digest_b6, str) and len(digest_b6) == 64)
    code, out, err = run_cli([
        "generation", "--case", case_b6, "--row-key", "legal_research",
        "--actor-user-id", str(_ACTORS["analyst"]), "--apply", "--expected-input-digest", digest_b6,
    ])
    check("B6b analyst apply denied (existence-blind authz denial)", code != 0, f"code={code} out={out!r} err={err!r}")
    code, out, err = run_cli([
        "generation", "--case", case_b6, "--row-key", "legal_research",
        "--actor-user-id", "999999", "--apply", "--expected-input-digest", digest_b6,
    ])
    check(
        "B6c a nonexistent actor apply -> the SAME fixed denial (existence-blind), exit != 0",
        code != 0, f"code={code} out={out!r} err={err!r}",
    )
    check("B6d zero journal rows for both denied attempts", journal_rows(f"case:{case_b6}") == [])

    # ============================================================
    # B7 - WRITER CRASH -> reconciliation_required, then REAL
    #      reconciliation through ui.reconciliation_operator's ACTUAL
    #      production registry resolves it to 'failed' with real
    #      provenance (the pending was genuinely never created - pre-
    #      state unchanged). Calls the facade DIRECTLY (not via
    #      cli_mutate.main()), mirroring generation_mutation_
    #      integration_postgres.py's own G5 pattern exactly:
    #      `LegalResearchEngineError` is the writer's OWN raw internal-
    #      guard exception, NOT a recognized clean-exit-code domain
    #      error for this CLI.
    # ============================================================
    case_b7, dir_b7 = make_generation_case("b7")
    seed_assignment(_ACTORS["lawyer"], case_b7, "lawyer")
    digest_b7 = preview_input_digest(case_b7, "legal_research")

    _original_validate_b7 = lre.validate_research_analysis

    def _exploding_validate_b7(**kwargs):
        raise lre.LegalResearchEngineError("ROW 19C-3c-iv B7: simulated post-write writer crash")

    authz_conn_b7 = authz_conn_factory()
    try:
        principal_b7 = _cli_authz.build_cli_principal(authz_conn_b7, _ACTORS["lawyer"])
        repo_b7 = _cli_authz.CliActorAuthzRepository(authz_conn_b7)
        lre.validate_research_analysis = _exploding_validate_b7
        try:
            lrc.apply_generation(
                "legal_research", case_b7, digest_b7,
                principal=principal_b7, authz_repository=repo_b7, conn_factory=mutation_conn_factory,
            )
        except lre.LegalResearchEngineError:
            check("B7a the simulated writer crash propagates as the writer's own raw exception", True)
        else:
            check("B7a the simulated writer crash propagates as the writer's own raw exception", False, "no exception raised")
        finally:
            lre.validate_research_analysis = _original_validate_b7
    finally:
        authz_conn_b7.close()
    rows_b7 = journal_rows(f"case:{case_b7}")
    check(
        "B7b the journal row is 'reconciliation_required' - the writer boundary was crossed and "
        "this coordinator NEVER guesses 'failed' for a writer exception",
        len(rows_b7) == 1 and rows_b7[0]["state"] == "reconciliation_required",
        f"rows={rows_b7}",
    )
    check(
        "B7c despite the crash, the writer's OWN rollback left NO pending file behind",
        not lre.get_pending_path(case_b7).exists(),
    )

    real_registry = op._default_registry_factory()
    check(
        "B7d the REAL production registry (47 routing keys) includes generation.legal_research "
        "and generation.case_law",
        {"generation.legal_research", "generation.case_law"} <= real_registry.known_action_families(),
    )
    from ui.services import mutation_registry as mr  # noqa: E402
    reconcile_conn_b7 = mutation_conn_factory()
    try:
        outcome_b7 = mr.reconcile_and_apply_journal_entry(
            reconcile_conn_b7, rows_b7[0]["id"], real_registry,
            resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c3civ_pg_test",
        )
    finally:
        reconcile_conn_b7.close()
    check(
        "B7e reconciliation resolves to 'failed' with resolution_code="
        "'reconciled_failed_pre_state_confirmed_unchanged'",
        outcome_b7.new_state == "failed"
        and outcome_b7.resolution_code == "reconciled_failed_pre_state_confirmed_unchanged",
        f"got {outcome_b7!r}",
    )
    rows_b7_after = journal_rows(f"case:{case_b7}")
    check(
        "B7f the journal row was durably updated to 'failed' with the REAL reconciler provenance",
        rows_b7_after[0]["state"] == "failed"
        and rows_b7_after[0]["reconciled_by_actor_type"] == "cli_service"
        and rows_b7_after[0]["reconciled_by_actor_ref"] == "row19c3civ_pg_test",
        f"rows={rows_b7_after}",
    )
    code, out, err = run_cli([
        "generation", "--case", case_b7, "--row-key", "legal_research",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_b7,
    ])
    check(
        "B7g a retry with the IDENTICAL identity after a reconciled 'failed' resolution is "
        "PERMANENTLY refused (PriorAttemptFailedError)",
        code == 1 and "PriorAttemptFailedError" in err,
        f"code={code} out={out!r} err={err!r}",
    )

    # ============================================================
    # B8 - TWO REAL CONNECTIONS, ONE REAL CASE LOCK - PostgreSQL's OWN
    #      pg_locks reports a genuinely WAITING advisory lock while
    #      session B is blocked on the SAME case's session lock a
    #      real apply_generation() call would take.
    # ============================================================
    case_b8, dir_b8 = make_generation_case("b8")
    seed_assignment(_ACTORS["lawyer"], case_b8, "lawyer")
    digest_b8 = preview_input_digest(case_b8, "legal_research")

    holder_conn_b8 = pg_connect()
    holder_lock_id_b8 = _mutation_lock.acquire_case_lock_session(holder_conn_b8, case_b8)
    check("B8a connection A really acquired the case lock", isinstance(holder_lock_id_b8, int))

    blocked_result_b8 = {}

    def _run_blocked_apply_b8():
        authz_conn_worker = authz_conn_factory()
        try:
            principal_worker = _cli_authz.build_cli_principal(authz_conn_worker, _ACTORS["lawyer"])
            repo_worker = _cli_authz.CliActorAuthzRepository(authz_conn_worker)
            try:
                blocked_result_b8["result"] = lrc.apply_generation(
                    "legal_research", case_b8, digest_b8,
                    principal=principal_worker, authz_repository=repo_worker,
                    conn_factory=mutation_conn_factory,
                )
            except BaseException as error:  # noqa: BLE001
                blocked_result_b8["error"] = error
        finally:
            authz_conn_worker.close()

    worker_b8 = threading.Thread(target=_run_blocked_apply_b8, daemon=True)
    worker_b8.start()

    observed_waiter_b8 = wait_for_lock_waiter(holder_lock_id_b8)
    check(
        "B8b PostgreSQL's OWN pg_locks reports a genuinely WAITING (not granted) advisory lock "
        "for this case - session B is really blocked",
        observed_waiter_b8,
    )
    check(
        "B8c the second real connection is STILL BLOCKED on the real case lock",
        worker_b8.is_alive() and "result" not in blocked_result_b8 and "error" not in blocked_result_b8,
        f"blocked_result={blocked_result_b8!r}",
    )
    check("B8d while blocked, it has written NOTHING to the real journal", journal_rows(f"case:{case_b8}") == [])

    released_b8 = _mutation_lock.release_lock_session(holder_conn_b8, holder_lock_id_b8)
    check("B8e connection A's real lock release reported success", released_b8 is True)
    holder_conn_b8.close()

    worker_b8.join(timeout=90)
    check("B8f once A released, the blocked request completed", not worker_b8.is_alive())
    check(
        "B8g the previously-blocked request succeeded on its own connection",
        "error" not in blocked_result_b8 and blocked_result_b8.get("result") is not None,
        f"blocked_result={blocked_result_b8!r}",
    )
    check(
        "B8h it then really journaled 'completed' exactly once",
        len(journal_rows(f"case:{case_b8}")) == 1
        and journal_rows(f"case:{case_b8}")[0]["state"] == "completed",
    )

    # ============================================================
    # B9 - GLOBAL-RESOURCE REVISION IDENTITY: a `provisions.json`
    #      revision change (injected TEST copy under a redirected
    #      DATA_DIR/BASE_DIR - NEVER the real production data/
    #      provisions.json, which is neither read nor written by this
    #      scenario) produces a genuinely NEW input_digest, and the
    #      resulting SECOND generation attempt is verified, by REAL SQL
    #      against mutation.mutation_journal, to be a genuinely SEPARATE
    #      row with a DIFFERENT idempotency_key, reaching 'completed' -
    #      never an IdempotencyConflictError. Calls the facade DIRECTLY
    #      (BASE_DIR/DATA_DIR redirection has no CLI flag).
    # ============================================================
    _tmp_globalres_root_b9 = Path(tempfile.mkdtemp(prefix="vergi_lrcl_pgint_globalres_"))
    _tmp_globalres_data_b9 = _tmp_globalres_root_b9 / "data"
    _tmp_globalres_data_b9.mkdir(parents=True)
    _real_documents_bytes_b9 = (REPO_ROOT / "data" / "documents.json").read_bytes()
    _real_provisions_bytes_b9 = (REPO_ROOT / "data" / "provisions.json").read_bytes()
    (_tmp_globalres_data_b9 / "documents.json").write_bytes(_real_documents_bytes_b9)
    (_tmp_globalres_data_b9 / "provisions.json").write_bytes(_real_provisions_bytes_b9)

    _original_lre_base_dir = lre.BASE_DIR
    _original_lre_data_dir = lre.DATA_DIR
    try:
        lre.BASE_DIR = _tmp_globalres_root_b9
        lre.DATA_DIR = _tmp_globalres_data_b9

        case_b9, dir_b9 = make_generation_case("b9")
        seed_assignment(_ACTORS["lawyer"], case_b9, "lawyer")

        authz_conn_b9 = authz_conn_factory()
        try:
            principal_b9 = _cli_authz.build_cli_principal(authz_conn_b9, _ACTORS["lawyer"])
            repo_b9 = _cli_authz.CliActorAuthzRepository(authz_conn_b9)

            preview_b9a = lrc.preview_generation(
                "legal_research", case_b9, principal=principal_b9, authz_repository=repo_b9,
            )
            result_b9a = lrc.apply_generation(
                "legal_research", case_b9, preview_b9a["input_digest"],
                principal=principal_b9, authz_repository=repo_b9, conn_factory=mutation_conn_factory,
            )
            check(
                "B9a first (revision-1 provisions.json) legal_research apply completes, "
                "replayed=False",
                result_b9a.replayed is False and result_b9a.pending_path.is_file(),
                f"got {result_b9a!r}",
            )

            (_tmp_globalres_data_b9 / "provisions.json").write_bytes(_real_provisions_bytes_b9 + b"\n")

            preview_b9b = lrc.preview_generation(
                "legal_research", case_b9, principal=principal_b9, authz_repository=repo_b9,
            )
            check(
                "B9b the provisions.json revision change produces a genuinely DIFFERENT "
                "input_digest",
                preview_b9b["input_digest"] != preview_b9a["input_digest"],
                f"got before={preview_b9a['input_digest']!r} after={preview_b9b['input_digest']!r}",
            )
            result_b9b = lrc.apply_generation(
                "legal_research", case_b9, preview_b9b["input_digest"],
                principal=principal_b9, authz_repository=repo_b9, conn_factory=mutation_conn_factory,
            )
            check(
                "B9c the revision-revised SECOND generation completes successfully "
                "(replayed=False) - NEVER an IdempotencyConflictError",
                result_b9b.replayed is False and result_b9b.pending_path.is_file(),
                f"got {result_b9b!r}",
            )
        finally:
            authz_conn_b9.close()

        rows_b9 = journal_rows(f"case:{case_b9}")
        check(
            "B9d REAL SQL: exactly TWO journal rows exist for case_b9's resource_key",
            len(rows_b9) == 2, f"rows={rows_b9}",
        )
        check(
            "B9e REAL SQL: the two rows carry DIFFERENT idempotency_key values",
            rows_b9[0]["idempotency_key"] != rows_b9[1]["idempotency_key"],
            f"rows={rows_b9}",
        )
        check(
            "B9f REAL SQL: BOTH journal rows genuinely reached 'completed'",
            all(row["state"] == "completed" for row in rows_b9), f"rows={rows_b9}",
        )
    finally:
        lre.BASE_DIR = _original_lre_base_dir
        lre.DATA_DIR = _original_lre_data_dir
        shutil.rmtree(_tmp_globalres_root_b9, ignore_errors=True)

    # ============================================================
    # B10 - AGENT MODE with an in-process fake-client TEST SEAM, called
    #       DIRECTLY through the facade (never through the CLI, which
    #       has no llm_client parameter at all) - proves preview/apply
    #       produce the SAME identity, preview never calls the fake
    #       client, and the real journal/audit reflect agent mode
    #       correctly (the actual agent layer may itself decide there is
    #       nothing to research and never call the fake client at all -
    #       proven separately by the isolated engine test suites; this
    #       scenario proves the COORDINATED wiring, not the agent's own
    #       internal decision to call the LLM).
    # ============================================================
    class _FakeAgentLLMClient:
        def __init__(self, payload_text="[]"):
            self._payload_text = payload_text
            self.create_calls = 0

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                self._outer.create_calls += 1
                block = type("Block", (), {"type": "text", "text": self._outer._payload_text})()
                return type("Response", (), {"content": [block]})()

        @property
        def messages(self):
            return self._Messages(self)

    case_b10, dir_b10 = make_generation_case("b10")
    seed_assignment(_ACTORS["lawyer"], case_b10, "lawyer")

    authz_conn_b10 = authz_conn_factory()
    try:
        principal_b10 = _cli_authz.build_cli_principal(authz_conn_b10, _ACTORS["lawyer"])
        repository_b10 = _cli_authz.CliActorAuthzRepository(authz_conn_b10)

        fake_client_b10 = _FakeAgentLLMClient()
        preview_b10 = lrc.preview_generation(
            "legal_research", case_b10, with_agent=True, llm_client=fake_client_b10,
            principal=principal_b10, authz_repository=repository_b10,
        )
        check(
            "B10a preview with fake client: model_id sentinel, engine_version/"
            "prompt_agent_version REAL",
            preview_b10["model_id"] == "external_injected_client"
            and preview_b10["engine_version"] == lre.LEGAL_RESEARCH_ENGINE_VERSION,
        )
        check("B10b preview NEVER invoked the fake client's .messages.create()", fake_client_b10.create_calls == 0)

        result_b10 = lrc.apply_generation(
            "legal_research", case_b10, preview_b10["input_digest"],
            with_agent=True, allow_network=True, llm_client=fake_client_b10,
            principal=principal_b10, authz_repository=repository_b10, conn_factory=mutation_conn_factory,
        )
        check(
            "B10c apply with the SAME fake client succeeds using preview's own input_digest",
            result_b10.pending_sha256 is not None,
        )
        rows_b10 = journal_rows(f"case:{case_b10}")
        check(
            "B10d journal row reflects agent mode via the audit",
            len(rows_b10) == 1 and rows_b10[0]["state"] == "completed",
        )
        audit_files_b10 = list(lre.get_reviews_dir(case_b10).glob("*.generation_audit.json"))
        check("B10e exactly one real audit file written", len(audit_files_b10) == 1)
        audit_record_b10 = json.loads(audit_files_b10[0].read_text(encoding="utf-8"))
        check(
            "B10f real audit record: generation_mode=agent, model_id sentinel, engine_version REAL",
            audit_record_b10["generation_mode"] == "agent"
            and audit_record_b10["model_id"] == "external_injected_client"
            and audit_record_b10["engine_version"] == lre.LEGAL_RESEARCH_ENGINE_VERSION,
        )
        check(
            "B10g mutation_actor_ref bound to the real IAM actor id (never the channel sentinel)",
            audit_record_b10["mutation_actor_ref"] == str(_ACTORS["lawyer"]),
        )
        check(
            "B10h channel sentinel is exactly local_lawyer_legal_research_case_law_cli",
            audit_record_b10["channel"] == "local_lawyer_legal_research_case_law_cli",
        )

        current_sha_b10 = sha256_file(lre.get_pending_path(case_b10))
        adapter_b10 = ada.LegalResearchCaseLawReconciliationAdapter(lre, "legal_research")
        matches_b10 = ada._audit_record_matches(
            audit_record_b10, "legal_research",
            idempotency_key=rows_b10[0]["idempotency_key"], resource_key=f"case:{case_b10}",
            action_family="generation.legal_research", target_ref="legal_research.pending",
            target_state="generated", actor_label=str(_ACTORS["lawyer"]), pending_sha256=current_sha_b10,
            expected_case_id=case_b10,
        )
        check("B10i adapter independently re-verifies the real agent-mode audit record end to end", matches_b10)
    finally:
        authz_conn_b10.close()

    # ============================================================
    # B11 - RECONCILIATION via gather_evidence() on the REAL completed
    #       B1 row, WITHOUT re-invoking anything.
    # ============================================================
    entry_b11 = mr.JournalEntrySnapshot(
        journal_id=rows_b1[0]["id"], resource_key=rows_b1[0]["resource_key"],
        action_family=rows_b1[0]["action_family"], target_ref=rows_b1[0]["target_ref"],
        target_state=rows_b1[0]["target_state"], pre_hash=None,
        pre_revision=rows_b1[0]["pre_revision"], expected_post_hash=rows_b1[0]["observed_post_hash"],
        state=rows_b1[0]["state"], idempotency_key=rows_b1[0]["idempotency_key"],
        request_fingerprint="unused-in-this-adapter", actor_label=str(_ACTORS["lawyer"]),
    )
    adapter_b11 = ada.LegalResearchCaseLawReconciliationAdapter(lre, "legal_research")
    evidence_b11 = adapter_b11.gather_evidence(entry_b11)
    check(
        "B11 gather_evidence() on the real completed B1 row: post_state_verified=True",
        evidence_b11.post_state_verified is True, f"evidence={evidence_b11}",
    )
    check(
        "B11b gather_evidence() observed_post_hash matches the real on-disk pending",
        evidence_b11.observed_post_hash == sha256_file(pending_path_b1),
    )

    # ============================================================
    # B12 - RECONCILIATION merged registry - 49 routing keys, real
    #       operator-factory construction (no fake injection).
    # ============================================================
    merged_registry_b12 = op._default_registry_factory()
    check(
        "B12 merged reconciliation registry has exactly 49 routing keys (10 approval + 24 review "
        "+ 1 drafting_request + 2 promotion + 2 deterministic-generation + 5 agent-generation + 1 "
        "fact-extraction-generation + 2 legal-research/case-law-generation + 2 "
        "rag-bundle-build/activate)",
        len(merged_registry_b12.known_action_families()) == 49,
        f"got {len(merged_registry_b12.known_action_families())}",
    )

    # ============================================================
    # JOURNAL INVARIANCE.
    # ============================================================
    check(
        "this run's own case_b1 resource_key carries exactly the ONE row this suite created for it",
        len(journal_rows(f"case:{case_b1}")) == 1,
    )
    check(
        "this run's own case_b7 resource_key carries exactly the ONE row this suite created for "
        "it, and it ended in the terminal 'failed' state",
        len(journal_rows(f"case:{case_b7}")) == 1 and journal_rows(f"case:{case_b7}")[0]["state"] == "failed",
    )
    check(
        "this run's own case_b6 resource_key carries ZERO rows (both attempts were authz-denied "
        "before any journal row could be created)",
        len(journal_rows(f"case:{case_b6}")) == 0,
    )
finally:
    for _m in _cases_dir_holders:
        _m.CASES_DIR = Path(_REAL_CASES_ROOT)
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

_real_data_after = snapshot_real_data_tree()
check(
    "the REAL data/ tree is byte-for-byte UNCHANGED before vs after this entire test file",
    _real_data_before == _real_data_after,
    f"diff keys: {set(_real_data_before) ^ set(_real_data_after)}",
)

summarize_and_exit()
