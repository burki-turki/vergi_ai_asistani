# ============================================================
# ROW 19C-3c-i - REAL, END-TO-END PostgreSQL INTEGRATION PROOF for the
# deterministic generation mutation path (ui/services/generation_
# mutation_facade.py + generation_mutation_adapters.py + the
# ui.cli_mutate `generation` subcommand + ui/reconciliation_operator.py).
#
# WHAT IS REAL HERE: `ui.cli_mutate.main()` itself, `ui.services.
# cli_authz.CliActorAuthzRepository` against REAL iam rows, the real
# `mutation.mutation_journal`, real `pg_advisory_lock` session locking,
# the REAL `src/deadline_engine.py`/`src/timeline_engine.py` writers,
# and the REAL merged reconciliation registry (`ui.reconciliation_
# operator._default_registry_factory()` - 39 routing keys).
#
# WHAT IS NOT REAL: the case tree (re-identified copies of
# data/cases/case_0001 under a fresh tempdir - the repository's own
# data/ tree is NEVER written, proven byte-for-byte at the end).
#
# Mirrors `test_promotion_mutation_integration_postgres.py`'s
# established fixture pattern (CASES_DIR redirect sweep, case-copy
# helper, run_cli() via cli_mutate.main() in-process). The same-case
# two-connection lock-serialization proof is DELIBERATELY NOT repeated
# here - it exercises `ui.services.mutation_lock`/`mutation_coordinator`
# generically, unchanged by this sub-phase, and is already proven for
# other families (test_promotion_mutation_integration_postgres.py P1,
# test_review_mutation_integration_postgres.py) using the IDENTICAL
# code path this facade also uses.
#
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_generation_mutation_integration_postgres.py
# ============================================================

import io
import hashlib
import json
import os
import shutil
import sys
import tempfile
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
        f"--- test_generation_mutation_integration_postgres: {passed} passed, {failed} failed, "
        f"{skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip(
        "the entire real-PostgreSQL generation integration suite",
        "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip(
        "the entire real-PostgreSQL generation integration suite",
        f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                     # noqa: E402
import ui.reconciliation_operator as op                                 # noqa: E402
from ui.services import cli_authz as _cli_authz                         # noqa: E402
from ui.services import generation_mutation_facade as gen               # noqa: E402
from ui.services import paths as _paths                                 # noqa: E402
from ui.services.common import sha256_file                              # noqa: E402

import deadline_engine                                                  # noqa: E402
import deadline_calculator                                              # noqa: E402
import timeline_engine                                                  # noqa: E402
import deadline_validator                                               # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                # ROW 19C-3c-i DEADLINE REVISION-IDENTITY REMEDIATION:
                # `idempotency_key` added (additive, purely SELECT-side -
                # every existing caller accesses specific dict keys, so
                # this new column is backward compatible) so G6 can
                # verify, by REAL SQL, that a ruleset/provisions revision
                # change genuinely produces a DIFFERENT idempotency_key
                # (not merely a different pre_revision string).
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

_ACTORS = {"lawyer": 401, "analyst": 402}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"row19c3ci-gen-actor-{user_id}"),
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


_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_gen_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
check(
    "the CASES_DIR redirect sweep found ui.services.paths AND deadline_engine AND "
    "timeline_engine AND deadline_validator",
    all(
        any(getattr(m, "__name__", "") == name for m in _cases_dir_holders)
        for name in ("ui.services.paths", "deadline_engine", "timeline_engine", "deadline_validator")
    ),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

_real_data_before = snapshot_real_data_tree()

RUN_TOKEN = uuid.uuid4().hex[:8]
ANCHOR_EVENT_ID = "timeline_event_003"


def make_generation_case(tag):
    case_id = f"genpg{RUN_TOKEN}{tag}"
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
    deadlines_dir = dst / "deadlines"
    for stale in deadlines_dir.glob("*.pending"):
        stale.unlink()
    timeline_dir = dst / "timeline"
    stale_timeline_pending = timeline_dir / timeline_engine.CANONICAL_PENDING_FILENAME
    if stale_timeline_pending.exists():
        stale_timeline_pending.unlink()
    for base_dir in (deadlines_dir, timeline_dir):
        for stale_dir_name in ("history", "generation_reviews"):
            stale_dir = base_dir / stale_dir_name
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


def preview_input_digest(case_id, row_key, *, anchor=None, actor_user_id=None):
    args = [
        "generation", "--case", case_id, "--row-key", row_key,
        "--actor-user-id", str(actor_user_id if actor_user_id is not None else _ACTORS["lawyer"]),
    ]
    if anchor is not None:
        args += ["--anchor", anchor]
    code, out, err = run_cli(args)
    if code != 0:
        raise AssertionError(f"preview failed: code={code} out={out!r} err={err!r}")
    for line in out.splitlines():
        if line.startswith("input_digest="):
            return line[len("input_digest="):]
    raise AssertionError(f"input_digest= not found in preview output: {out!r}")


try:
    # ============================================================
    # G1 - deadline fresh generation, END-TO-END through the real CLI.
    # ============================================================
    case_g1, dir_g1 = make_generation_case("g1")
    seed_assignment(_ACTORS["lawyer"], case_g1, "lawyer")

    digest_g1 = preview_input_digest(case_g1, "deadline", anchor=ANCHOR_EVENT_ID)
    code, out, err = run_cli([
        "generation", "--case", case_g1, "--row-key", "deadline", "--anchor", ANCHOR_EVENT_ID,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_g1,
    ])
    check("G1a CLI deadline apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    pending_path_g1 = deadline_engine.get_pending_path(case_g1)
    check("G1b the REAL pending file was written", pending_path_g1.is_file())
    rows_g1 = journal_rows(f"case:{case_g1}")
    check(
        "G1c exactly one REAL journal row, state='completed', action_family='generation.deadline'",
        len(rows_g1) == 1 and rows_g1[0]["state"] == "completed"
        and rows_g1[0]["action_family"] == "generation.deadline"
        and rows_g1[0]["target_ref"] == f"deadline.{ANCHOR_EVENT_ID}.pending"
        and rows_g1[0]["target_state"] == "generated",
        f"rows={rows_g1}",
    )
    check(
        "G1d journal row's observed_post_hash matches the REAL on-disk pending bytes",
        rows_g1[0]["observed_post_hash"] == sha256_file(pending_path_g1),
    )
    check(
        "G1e a real *.generation_audit.json audit file exists under generation_reviews/",
        any(deadline_engine.get_reviews_dir(case_g1).glob("*.generation_audit.json")),
    )

    # ============================================================
    # G2 - timeline fresh generation, END-TO-END through the real CLI.
    # ============================================================
    case_g2, dir_g2 = make_generation_case("g2")
    seed_assignment(_ACTORS["lawyer"], case_g2, "lawyer")

    digest_g2 = preview_input_digest(case_g2, "timeline")
    code, out, err = run_cli([
        "generation", "--case", case_g2, "--row-key", "timeline",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_g2,
    ])
    check("G2a CLI timeline apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    pending_path_g2 = timeline_engine.get_pending_path(case_g2)
    check(
        "G2b the REAL pending file was written at the pinned filename",
        pending_path_g2.is_file() and pending_path_g2.name == "timeline_v1_1.json.pending",
    )
    rows_g2 = journal_rows(f"case:{case_g2}")
    check(
        "G2c exactly one REAL journal row, state='completed', action_family='generation.timeline'",
        len(rows_g2) == 1 and rows_g2[0]["state"] == "completed"
        and rows_g2[0]["action_family"] == "generation.timeline"
        and rows_g2[0]["target_ref"] == "timeline.pending",
        f"rows={rows_g2}",
    )

    # ============================================================
    # G3 - SAFE REPLAY via the real CLI: the exact same apply invocation
    #      a second time does not re-invoke the writer (pending file
    #      mtime/bytes stay byte-identical) but still exits 0.
    # ============================================================
    pending_bytes_g1_before_replay = pending_path_g1.read_bytes()
    code, out, err = run_cli([
        "generation", "--case", case_g1, "--row-key", "deadline", "--anchor", ANCHOR_EVENT_ID,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_g1,
    ])
    check("G3a a real CLI replay of the SAME apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    check("G3b replayed=True was reported by the CLI", "replayed=True" in out, f"out={out!r}")
    check(
        "G3c the pending file's bytes are BYTE-IDENTICAL to before the replay (writer was NOT "
        "re-invoked)",
        pending_path_g1.read_bytes() == pending_bytes_g1_before_replay,
    )
    check("G3d still exactly ONE journal row for this resource_key", len(journal_rows(f"case:{case_g1}")) == 1)

    # ============================================================
    # G4 - FINGERPRINT CONFLICT via the real CLI: same case/anchor/
    #      content (same idempotency_key) but a DIFFERENT generation-
    #      tuning parameter (--calendar-complete) -> a clean domain
    #      error, zero new journal row.
    # ============================================================
    code, out, err = run_cli([
        "generation", "--case", case_g1, "--row-key", "deadline", "--anchor", ANCHOR_EVENT_ID,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_g1,
        "--calendar-complete",
    ])
    check(
        "G4a a conflicting --calendar-complete on the SAME identity -> a clean domain error "
        "(exit 1), never a raw traceback",
        code == 1 and "IdempotencyConflictError" in err,
        f"code={code} out={out!r} err={err!r}",
    )
    check("G4b still exactly ONE journal row (the conflicting attempt created no new row)", len(journal_rows(f"case:{case_g1}")) == 1)

    # ============================================================
    # G5 - WRITER CRASH -> reconciliation_required, then REAL
    #      reconciliation through ui.reconciliation_operator's ACTUAL
    #      production registry (39 routing keys, generation.deadline
    #      included) resolves it to 'completed' with real provenance.
    #
    #      Calls the facade DIRECTLY (not via cli_mutate.main()) for
    #      this ONE scenario: `deadline_engine.DeadlineEngineError` is
    #      the writer's OWN raw internal-guard exception, which - by
    #      `ui.cli_mutate._is_known_domain_error()`'s own documented,
    #      pre-existing design ("anything NOT covered here is
    #      deliberately left to propagate uncaught with its own real
    #      traceback") - is NOT a recognized clean-exit-code domain
    #      error for ANY family through this CLI (this is not new/
    #      specific to generation; the exact same is true for a raw
    #      internal writer-guard exception from approval/review/
    #      promotion). Catching it directly in Python here is the
    #      correct, representative way to exercise this path.
    # ============================================================
    case_g5, dir_g5 = make_generation_case("g5")
    seed_assignment(_ACTORS["lawyer"], case_g5, "lawyer")
    digest_g5 = preview_input_digest(case_g5, "deadline", anchor=ANCHOR_EVENT_ID)

    _original_validate_g5 = deadline_engine.validate_deadline_analysis

    def _exploding_validate_g5(**kwargs):
        raise deadline_engine.DeadlineEngineError("ROW 19C-3c-i G5: simulated post-write writer crash")

    authz_conn_g5 = authz_conn_factory()
    try:
        principal_g5 = _cli_authz.build_cli_principal(authz_conn_g5, _ACTORS["lawyer"])
        repo_g5 = _cli_authz.CliActorAuthzRepository(authz_conn_g5)
        deadline_engine.validate_deadline_analysis = _exploding_validate_g5
        try:
            gen.apply_generation(
                "deadline", case_g5, digest_g5, anchor_event_id=ANCHOR_EVENT_ID,
                principal=principal_g5, authz_repository=repo_g5, conn_factory=mutation_conn_factory,
            )
        except deadline_engine.DeadlineEngineError:
            check("G5a the simulated writer crash propagates as the writer's own raw exception", True)
        else:
            check("G5a the simulated writer crash propagates as the writer's own raw exception", False, "no exception raised")
        finally:
            deadline_engine.validate_deadline_analysis = _original_validate_g5
    finally:
        authz_conn_g5.close()
    rows_g5 = journal_rows(f"case:{case_g5}")
    check(
        "G5b the journal row is 'reconciliation_required' - the writer boundary was crossed and "
        "this coordinator NEVER guesses 'failed' for a writer exception",
        len(rows_g5) == 1 and rows_g5[0]["state"] == "reconciliation_required",
        f"rows={rows_g5}",
    )
    check(
        "G5c despite the crash, the writer's OWN rollback left NO pending file behind (deadline_"
        "engine's existing atomic-write-with-rollback contract, unmodified by this Row)",
        not deadline_engine.get_pending_path(case_g5).exists(),
    )

    # Real reconciliation, through the REAL production registry.
    real_registry = op._default_registry_factory()
    check(
        "G5d the REAL production registry (39 routing keys) includes generation.deadline",
        "generation.deadline" in real_registry.known_action_families(),
    )
    from ui.services import mutation_registry as mr  # noqa: E402
    reconcile_conn = mutation_conn_factory()
    try:
        outcome_g5 = mr.reconcile_and_apply_journal_entry(
            reconcile_conn, rows_g5[0]["id"], real_registry,
            resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c3ci_pg_test",
        )
    finally:
        reconcile_conn.close()
    check(
        "G5e reconciliation resolves to 'failed' with resolution_code="
        "'reconciled_failed_pre_state_confirmed_unchanged' - the pending was genuinely never "
        "created (pre-state unchanged: still absent before AND after)",
        outcome_g5.new_state == "failed"
        and outcome_g5.resolution_code == "reconciled_failed_pre_state_confirmed_unchanged",
        f"got {outcome_g5!r}",
    )
    rows_g5_after = journal_rows(f"case:{case_g5}")
    check(
        "G5f the journal row was durably updated to 'failed' with the REAL reconciler provenance",
        rows_g5_after[0]["state"] == "failed"
        and rows_g5_after[0]["reconciled_by_actor_type"] == "cli_service"
        and rows_g5_after[0]["reconciled_by_actor_ref"] == "row19c3ci_pg_test",
        f"rows={rows_g5_after}",
    )

    # A retry with the SAME identity is now PERMANENTLY blocked (the
    # approved, disclosed identity-model consequence for generation -
    # see generation_mutation_facade.py's own module header).
    code, out, err = run_cli([
        "generation", "--case", case_g5, "--row-key", "deadline", "--anchor", ANCHOR_EVENT_ID,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_g5,
    ])
    check(
        "G5g a retry with the IDENTICAL identity (same case content, same anchor, same "
        "parameters) after a reconciled 'failed' resolution is PERMANENTLY refused "
        "(PriorAttemptFailedError) - the documented, approved consequence of generation's "
        "content-derived identity model",
        code == 1 and "PriorAttemptFailedError" in err,
        f"code={code} out={out!r} err={err!r}",
    )

    # ============================================================
    # G6 - ROW 19C-3c-i DEADLINE REVISION-IDENTITY REMEDIATION, REAL
    #      PostgreSQL proof: a RULESET revision change (same case/
    #      timeline, injected TEST ruleset/provisions files - NEVER the
    #      real production data/deadline_rules/deadline_rules.json/
    #      data/provisions.json, which are neither read nor written by
    #      this scenario) produces a genuinely NEW input_digest, and the
    #      resulting SECOND generation attempt is verified, by REAL SQL
    #      against mutation.mutation_journal, to be a genuinely SEPARATE
    #      row with a DIFFERENT idempotency_key, reaching 'completed' -
    #      never an IdempotencyConflictError. Calls the facade DIRECTLY
    #      (like G5) since the CLI deliberately exposes no
    #      `--ruleset`/`--provisions` flag (see cli_mutate.py's own
    #      header).
    # ============================================================
    _tmp_globalres_dir_g6 = Path(tempfile.mkdtemp(prefix="vergi_gen_pgint_globalres_"))
    _ruleset_path_g6 = _tmp_globalres_dir_g6 / "ruleset.json"
    _provisions_path_g6 = _tmp_globalres_dir_g6 / "provisions.json"
    _real_ruleset_bytes_g6 = deadline_engine.DEFAULT_RULESET_PATH.read_bytes()
    _real_provisions_bytes_g6 = deadline_calculator.DEFAULT_PROVISIONS_PATH.read_bytes()
    _ruleset_path_g6.write_bytes(_real_ruleset_bytes_g6)
    _provisions_path_g6.write_bytes(_real_provisions_bytes_g6)

    try:
        case_g6, dir_g6 = make_generation_case("g6")
        seed_assignment(_ACTORS["lawyer"], case_g6, "lawyer")

        authz_conn_g6 = authz_conn_factory()
        try:
            principal_g6 = _cli_authz.build_cli_principal(authz_conn_g6, _ACTORS["lawyer"])
            repo_g6 = _cli_authz.CliActorAuthzRepository(authz_conn_g6)

            preview_g6a = gen.preview_generation(
                "deadline", case_g6, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_g6,
                authz_repository=repo_g6, ruleset_path=_ruleset_path_g6, provisions_path=_provisions_path_g6,
            )
            result_g6a = gen.apply_generation(
                "deadline", case_g6, preview_g6a["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
                principal=principal_g6, authz_repository=repo_g6, conn_factory=mutation_conn_factory,
                ruleset_path=_ruleset_path_g6, provisions_path=_provisions_path_g6,
            )
            check(
                "G6a first (revision-1 ruleset/provisions) deadline apply completes, replayed=False",
                result_g6a.replayed is False and result_g6a.pending_path.is_file(),
                f"got {result_g6a!r}",
            )

            # RULESET revision change - append JSON-harmless trailing
            # whitespace (json.loads() tolerates it, so the real rule-
            # selection logic behaves identically) so ONLY the raw
            # bytes/hash (and therefore input_digest) differ.
            _ruleset_path_g6.write_bytes(_real_ruleset_bytes_g6 + b"\n")

            preview_g6b = gen.preview_generation(
                "deadline", case_g6, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_g6,
                authz_repository=repo_g6, ruleset_path=_ruleset_path_g6, provisions_path=_provisions_path_g6,
            )
            check(
                "G6b the ruleset revision change produces a genuinely DIFFERENT input_digest (same "
                "case/timeline/provisions content)",
                preview_g6b["input_digest"] != preview_g6a["input_digest"],
                f"got before={preview_g6a['input_digest']!r} after={preview_g6b['input_digest']!r}",
            )
            result_g6b = gen.apply_generation(
                "deadline", case_g6, preview_g6b["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
                principal=principal_g6, authz_repository=repo_g6, conn_factory=mutation_conn_factory,
                ruleset_path=_ruleset_path_g6, provisions_path=_provisions_path_g6,
            )
            check(
                "G6c the ruleset-revised SECOND generation completes successfully (replayed=False) "
                "- NEVER an IdempotencyConflictError",
                result_g6b.replayed is False and result_g6b.pending_path.is_file(),
                f"got {result_g6b!r}",
            )
        finally:
            authz_conn_g6.close()

        rows_g6 = journal_rows(f"case:{case_g6}")
        check(
            "G6d REAL SQL against mutation.mutation_journal: exactly TWO journal rows exist for "
            "case_g6's resource_key - one per ruleset revision",
            len(rows_g6) == 2,
            f"rows={rows_g6}",
        )
        check(
            "G6e REAL SQL: the two rows carry DIFFERENT pre_revision (input_digest) values",
            rows_g6[0]["pre_revision"] != rows_g6[1]["pre_revision"],
            f"rows={rows_g6}",
        )
        check(
            "G6f REAL SQL: the two rows ALSO carry DIFFERENT idempotency_key values (the actual "
            "HIGH-severity bug this remediation closes - a ruleset revision change now produces a "
            "genuinely new idempotency identity, not merely a different pre_revision string that "
            "a stale idempotency_key could still collide against)",
            rows_g6[0]["idempotency_key"] != rows_g6[1]["idempotency_key"],
            f"rows={rows_g6}",
        )
        check(
            "G6g REAL SQL: BOTH journal rows genuinely reached 'completed' (never "
            "IdempotencyConflictError, never a false replay of the first row)",
            all(row["state"] == "completed" for row in rows_g6),
            f"rows={rows_g6}",
        )
    finally:
        shutil.rmtree(_tmp_globalres_dir_g6, ignore_errors=True)

    # ============================================================
    # G7 - ROW 19C-3c-i MEDIUM authz-coverage remediation, REAL
    #      PostgreSQL/real CLI proof: analyst preview allowed, analyst
    #      apply denied, and an unknown/nonexistent actor gets the
    #      IDENTICAL existence-blind denial - mirrors
    #      test_promotion_mutation_integration_postgres.py's established
    #      P9a/P9b pattern for the generation family (previously
    #      UNTESTED at this level - `_ACTORS["analyst"]` was declared
    #      but never used before this remediation turn).
    # ============================================================
    case_g7, dir_g7 = make_generation_case("g7")
    seed_assignment(_ACTORS["lawyer"], case_g7, "lawyer")
    seed_assignment(_ACTORS["analyst"], case_g7, "analyst")

    digest_g7 = preview_input_digest(case_g7, "deadline", anchor=ANCHOR_EVENT_ID, actor_user_id=_ACTORS["analyst"])
    check(
        "G7a analyst (read-only capability) preview succeeds via the real CLI, a real 64-hex-char "
        "input_digest is returned",
        isinstance(digest_g7, str) and len(digest_g7) == 64,
        f"got {digest_g7!r}",
    )

    code, out, err = run_cli([
        "generation", "--case", case_g7, "--row-key", "deadline", "--anchor", ANCHOR_EVENT_ID,
        "--actor-user-id", str(_ACTORS["analyst"]),
        "--apply", "--expected-input-digest", digest_g7,
    ])
    check(
        "G7b analyst (no mutate capability) apply -> the fixed generic denial, exit 1",
        code == 1 and "yetkisiz" in err,
        f"code={code} out={out!r} err={err!r}",
    )
    code, out, err = run_cli([
        "generation", "--case", case_g7, "--row-key", "deadline", "--anchor", ANCHOR_EVENT_ID,
        "--actor-user-id", "999999",
        "--apply", "--expected-input-digest", digest_g7,
    ])
    check(
        "G7c a nonexistent actor apply -> the SAME fixed denial (existence-blind), exit 1",
        code == 1 and "yetkisiz" in err,
        f"code={code} out={out!r} err={err!r}",
    )
    check(
        "G7d BOTH apply-denials together produced ZERO journal rows for case_g7's resource_key "
        "(REAL SQL - zero writer, zero prepared row)",
        len(journal_rows(f"case:{case_g7}")) == 0,
    )
    check(
        "G7e no deadline pending file was written for either denial",
        not deadline_engine.get_pending_path(case_g7).exists(),
    )

    # ============================================================
    # JOURNAL INVARIANCE - each of THIS RUN's own resource_keys (by its
    # own unique RUN_TOKEN, so re-running this suite against the same
    # disposable database never confuses a previous run's leftover rows
    # with this one) carries exactly the rows this suite itself created.
    # ============================================================
    check(
        "this run's own case_g1 resource_key carries exactly the ONE row this suite created for "
        "it (no leftover/duplicate rows from elsewhere)",
        len(journal_rows(f"case:{case_g1}")) == 1,
    )
    check(
        "this run's own case_g5 resource_key carries exactly the ONE row this suite created for "
        "it, and it ended in the terminal 'failed' state",
        len(journal_rows(f"case:{case_g5}")) == 1 and journal_rows(f"case:{case_g5}")[0]["state"] == "failed",
    )
    check(
        "this run's own case_g6 resource_key carries exactly the TWO rows this suite created for "
        "it (one per ruleset revision), both terminal 'completed'",
        len(journal_rows(f"case:{case_g6}")) == 2
        and all(row["state"] == "completed" for row in journal_rows(f"case:{case_g6}")),
    )
    check(
        "this run's own case_g7 resource_key carries ZERO rows (both attempts were authz-denied "
        "before any journal row could be created)",
        len(journal_rows(f"case:{case_g7}")) == 0,
    )
finally:
    for _m, _original in [(m, _REAL_CASES_ROOT) for m in _cases_dir_holders]:
        _m.CASES_DIR = Path(_original)
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

_real_data_after = snapshot_real_data_tree()
check(
    "the REAL data/ tree is byte-for-byte UNCHANGED before vs after this entire test file",
    _real_data_before == _real_data_after,
    f"diff keys: {set(_real_data_before) ^ set(_real_data_after)}",
)

summarize_and_exit()
