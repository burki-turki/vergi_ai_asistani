# ============================================================
# ROW 19C-3b SLICE 1 - REAL, END-TO-END PostgreSQL INTEGRATION PROOF
# for `ui.cli_mutate`.
#
# WHAT IS REAL HERE: `ui.cli_mutate.main()` itself (the actual CLI entry
# point, argv-to-exit-code, unmodified), `ui.services.cli_authz.
# CliActorAuthzRepository` against REAL `iam.users`/`iam.case_
# assignments`/`iam.user_roles` rows (not `InMemoryAuthzRepository` -
# this file's whole purpose is to prove the CLI's OWN new authz
# repository against a real database, which no pre-existing file does),
# `ui.services.approval_registry.case_scoped_approve()` /
# `ui.services.review_registry.apply_transition()` (the SAME production
# functions the web routes call), the real `mutation.mutation_journal`
# table, real `pg_advisory_lock` session-level locking, and real
# `src/deadline_approval.py`/`src/qa_review.py` writers.
#
# WHAT IS NOT REAL: the case tree (a re-identified copy of `data/
# cases/case_0001`, mirroring every other PG integration test's own
# `make_case()` pattern - the real repository's own `data/` tree is
# NEVER read/written by any scenario, proven at the end).
#
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_cli_mutate_integration_postgres.py
# ============================================================

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
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
    print(f"--- test_cli_mutate_integration_postgres: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")

if not PG_DB:
    skip(
        "the entire real-PostgreSQL ui.cli_mutate integration suite",
        "VERGI_TEST_PG_DSN is not set (no disposable database with migrations "
        "0001+0002+0003+0004 applied is configured for this run). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover - environment-dependent
    skip(
        "the entire real-PostgreSQL ui.cli_mutate integration suite",
        f"VERGI_TEST_PG_DSN is set but `import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                        # noqa: E402
from ui.services import authz as _authz                   # noqa: E402
from ui.services import mutation_lock as _mutation_lock   # noqa: E402
from ui.services.common import sha256_file                # noqa: E402
from ui.services import paths as _paths                   # noqa: E402

import deadline_approval                                  # noqa: E402
import qa_review                                           # noqa: E402
import qa_approval                                          # noqa: E402
import qa_engine                                             # noqa: E402
import qa_validator                                            # noqa: E402
# ROW 19C-3b SLICE 2: imported so the CASES_DIR redirect sweep below
# also covers the two promotion writer modules (their new module-level
# CASES_DIR is the promotion facade/adapters' dynamic containment seam).
import fact_approval                                        # noqa: E402
import timeline_approval                                     # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, resource_key, action_family, actor_user_id, actor_label, target_ref, "
                "target_state, state, observed_post_hash FROM mutation.mutation_journal "
                "WHERE resource_key = %s ORDER BY id",
                (resource_key,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


# ----------------------------------------------------------------
# Preflight: migrations 0001-0004 present.
# ----------------------------------------------------------------

_preflight = pg_connect()
try:
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('iam.users'), to_regclass('mutation.mutation_resources'), "
            "to_regclass('mutation.mutation_journal')"
        )
        row = cur.fetchone()
    check("preflight: iam.users/mutation.mutation_resources/mutation.mutation_journal all exist", all(row))
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run against a half-migrated database.")
    summarize_and_exit()


# ----------------------------------------------------------------
# Real iam.users rows for every actor this file uses.
# ----------------------------------------------------------------

_ACTOR_USER_IDS = (101, 102, 103, 104, 105)

_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTOR_USER_IDS:
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"row19c3b-cli-actor-{user_id}"),
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
# Case fixtures - REAL, independently re-identified copies of case_0001,
# under a fresh tempdir, for BOTH the approval family (deadline) and the
# review family (qa.suggestion) used by this file's scenarios.
# ----------------------------------------------------------------

RUN_TOKEN = uuid.uuid4().hex[:10]
_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))


def snapshot_real_data_tree():
    real_data_dir = REPO_ROOT / "data"
    out = {}
    for path in real_data_dir.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(real_data_dir))] = path.stat().st_size, path.read_bytes()
            except OSError:
                pass
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


_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_cli_mutate_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
_original_cases_dirs = [(m, m.CASES_DIR) for m in _cases_dir_holders]
check(
    "the CASES_DIR redirect sweep found ui.services.paths (the shared authz path-resolution choke point)",
    any(getattr(m, "__name__", "") == "ui.services.paths" for m in _cases_dir_holders),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

_original_qa_validator_base_dir = qa_validator.BASE_DIR
qa_validator.BASE_DIR = _TMP_ROOT

_real_data_before = snapshot_real_data_tree()


# ============================================================
# ROW 19C-3b SLICE 1 - LEGACY CLI MUTATION BYPASS, REAL-PostgreSQL
# JOURNAL INVARIANCE (persistent). All 15 legacy `src/*.py` mutation
# entry points must refuse via a genuine OS subprocess exit code 2
# WITHOUT ever creating a `mutation.mutation_journal` row for ANY
# resource/action-family - proven against this SAME real, disposable
# PostgreSQL database (`VERGI_TEST_PG_DSN`, inherited by each
# subprocess through the default, unmodified environment) that
# scenarios 1-5 below use for their OWN real mutations. No production
# writer/facade function is monkeypatched anywhere in this section -
# every invocation is a genuine, separate OS process
# (`subprocess.run()`, never `shell=True`) running the REAL
# `src/<module>.py` file unmodified, with an explicit `cwd=REPO_ROOT`
# and a bounded timeout. Placed BEFORE scenarios 1-5 so its own
# before/after journal window is not mixed with their real mutations.
# ============================================================

_LEGACY_CLI_REFUSAL_MESSAGE = "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3b)."

LEGACY_MUTATION_MATRIX = [
    # Layer A (10).
    ("deadline_approval", ["--case", "case_0001", "--approve"]),
    ("issue_spotting_approval", ["--case", "case_0001", "--approve"]),
    ("legal_research_approval", ["--case", "case_0001", "--approve"]),
    ("case_law_approval", ["--case", "case_0001", "--approve"]),
    ("evidence_approval", ["--case", "case_0001", "--approve"]),
    ("argument_approval", ["--case", "case_0001", "--approve"]),
    ("risk_strategy_approval", ["--case", "case_0001", "--approve"]),
    ("drafting_approval", ["--case", "case_0001", "--approve"]),
    ("qa_approval", ["--case", "case_0001", "--approve"]),
    ("orchestrator_approval", ["--case", "case_0001", "--approve"]),
    # Layer B (5).
    ("evidence_review", ["--case", "case_0001", "--confirm", "row19c3b_pg_nonexistent_candidate_id"]),
    ("argument_review", [
        "--case", "case_0001", "--record-type", "claim",
        "--record-id", "row19c3b_pg_nonexistent_claim_id", "--action", "confirm",
    ]),
    ("risk_strategy_review", [
        "--case", "case_0001", "--record-type", "risk",
        "--record-id", "row19c3b_pg_nonexistent_risk_id", "--action", "confirm",
    ]),
    ("drafting_review", [
        "--case", "case_0001", "--record-type", "section",
        "--record-id", "row19c3b_pg_nonexistent_section_id", "--action", "confirm",
    ]),
    ("qa_review", [
        "--case", "case_0001", "--suggestion-id", "row19c3b_pg_nonexistent_suggestion_id",
        "--target-state", "accepted_for_follow_up",
    ]),
    # ROW 19C-3b SLICE 2 - the two fact/timeline canonical PROMOTION bypasses.
    ("fact_approval", ["--approve"]),
    ("timeline_approval", ["--pending", "row19c3b_pg_slice2_nonexistent.pending", "--approve"]),
]
check(
    "LEGACY_MUTATION_MATRIX (real-PostgreSQL journal invariance section) covers all 17 legacy "
    "mutation entry points (10 Layer A + 5 Layer B + 2 promotion)",
    len(LEGACY_MUTATION_MATRIX) == 17,
)

# ROW 19C-3b SLICE 1 - EVIDENCE REVIEW FULL FLAG COVERAGE (real-
# PostgreSQL environment): `evidence_review.py` exposes FOUR independent
# public mutation flags (`--confirm`, `--reject`, `--accept-follow-up`,
# `--dismiss`), but LEGACY_MUTATION_MATRIX above only ever exercises
# `--confirm`. All four route to the SAME Row 19C-3b refusal branch, but
# each is exercised here as its own separate, real OS subprocess against
# this SAME real, disposable PostgreSQL database - proving none of the
# three untested flags somehow reaches the real writer or creates a real
# journal row either. This is 3 ADDITIONAL scenarios, not 3 additional
# legacy MODULES.
EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX = [
    ("evidence_review", ["--case", "case_0001", "--reject", "row19c3b_pg_nonexistent_candidate_id_reject"]),
    ("evidence_review", ["--case", "case_0001", "--accept-follow-up", "row19c3b_pg_nonexistent_suggestion_id_acceptfu"]),
    ("evidence_review", ["--case", "case_0001", "--dismiss", "row19c3b_pg_nonexistent_suggestion_id_dismiss"]),
]
check(
    "EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX (real-PostgreSQL environment) covers the 3 remaining "
    "evidence_review public mutation flags (--reject/--accept-follow-up/--dismiss) not already "
    "exercised by LEGACY_MUTATION_MATRIX's own --confirm invocation",
    len(EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX) == 3,
)
check(
    "LEGACY_MUTATION_MATRIX (17 legacy executables) + EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX (3 "
    "additional evidence_review flag variants) = 20 total refusal subprocess scenarios in this "
    "section - NOT 20 distinct legacy modules (evidence_review itself contributes 4 of the 20)",
    len(LEGACY_MUTATION_MATRIX) + len(EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX) == 20,
)


def _full_journal_snapshot():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, resource_key, action_family, actor_user_id, actor_label, target_ref, "
                "target_state, state, idempotency_key, request_fingerprint, observed_post_hash, "
                "failure_code, resolution_code FROM mutation.mutation_journal ORDER BY id"
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _journal_row_count():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM mutation.mutation_journal")
            (n,) = cur.fetchone()
            return n
    finally:
        conn.close()


_legacy_data_snapshot_before = snapshot_real_data_tree()
_legacy_journal_snapshot_before = _full_journal_snapshot()
_legacy_journal_count_before = _journal_row_count()

# ROW 19C-3b SLICE 1 LEGACY SUBPROCESS ENCODING REMEDIATION: an explicit,
# deterministic child environment - a full copy of the parent's own
# `os.environ` (so VERGI_TEST_PG_DSN and every other PostgreSQL DSN
# variable this same process needs survive unchanged into the child)
# with only `PYTHONIOENCODING=utf-8` added/overridden, pinning the
# child's OWN stdout/stderr encoding to UTF-8 regardless of the PARENT
# process's ambient locale (cp1254 on this Turkish-locale machine). The
# parent's global `os.environ` is NEVER mutated (`os.environ.copy()`
# only, passed via `env=`). Built once, reused read-only by every
# iteration below - nothing in this loop ever mutates it.
_legacy_child_env = os.environ.copy()
_legacy_child_env["PYTHONIOENCODING"] = "utf-8"

for _legacy_module_name, _legacy_mutation_args in LEGACY_MUTATION_MATRIX + EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX:
    _legacy_script_path = SRC_DIR / f"{_legacy_module_name}.py"
    check(
        f"{_legacy_module_name}: the real script file exists on disk and is the one actually "
        f"invoked ({_legacy_script_path})",
        _legacy_script_path.is_file(),
        f"resolved path: {_legacy_script_path}",
    )
    # Raw bytes still captured (never `text=True` -
    # `subprocess.run(text=True)`'s own internal reader threads would
    # decode using the PARENT process's own locale-preferred encoding,
    # ignoring `env=` entirely), but now decoded STRICTLY
    # (`errors="strict"`, the default - no `errors="replace"`): since
    # `_legacy_child_env` guarantees the child emits valid UTF-8, a
    # strict-decode failure is itself a genuine signal something is
    # wrong, rather than silently substituting U+FFFD replacement
    # characters that could quietly weaken the exact message-equality
    # assertions below.
    _legacy_completed = subprocess.run(
        [sys.executable, str(_legacy_script_path), *_legacy_mutation_args],
        cwd=str(REPO_ROOT), capture_output=True, timeout=90, env=_legacy_child_env,
    )
    _legacy_result = types.SimpleNamespace(
        returncode=_legacy_completed.returncode,
        stdout=_legacy_completed.stdout.decode("utf-8") if _legacy_completed.stdout else "",
        stderr=_legacy_completed.stderr.decode("utf-8") if _legacy_completed.stderr else "",
    )
    check(
        f"{_legacy_module_name} (real-PostgreSQL environment): real OS subprocess returncode is "
        "exactly 2 (the genuine process exit code SystemExit(2) produces)",
        _legacy_result.returncode == 2,
        f"got returncode={_legacy_result.returncode!r} stdout={_legacy_result.stdout!r} "
        f"stderr={_legacy_result.stderr!r}",
    )
    check(
        f"{_legacy_module_name} (real-PostgreSQL environment): the fixed Row 19C-3b refusal "
        "message appears in stderr",
        _LEGACY_CLI_REFUSAL_MESSAGE in _legacy_result.stderr,
        f"stderr={_legacy_result.stderr!r}",
    )
    check(
        f"{_legacy_module_name} (real-PostgreSQL environment): stderr contains no 'Traceback' - "
        "a clean, deliberate SystemExit(2), never an unhandled exception escaping",
        "Traceback" not in _legacy_result.stderr,
        f"stderr={_legacy_result.stderr!r}",
    )
    check(
        f"{_legacy_module_name} (real-PostgreSQL environment): stdout is completely empty - no "
        "unexpected domain-writer success output",
        _legacy_result.stdout == "",
        f"stdout={_legacy_result.stdout!r}",
    )

_legacy_journal_snapshot_after = _full_journal_snapshot()
_legacy_journal_count_after = _journal_row_count()
_legacy_data_snapshot_after = snapshot_real_data_tree()

check(
    "all 20 legacy mutation bypass scenarios (17 legacy executables + 3 additional evidence_"
    "review flag variants), real-PostgreSQL environment: mutation.mutation_journal row COUNT is "
    "unchanged before vs after (a direct SELECT count(*) against the real database, not a "
    "restatement of the full-row-set check below)",
    _legacy_journal_count_before == _legacy_journal_count_after,
    f"before={_legacy_journal_count_before} after={_legacy_journal_count_after}",
)
check(
    "all 20 legacy mutation bypass scenarios (17 legacy executables + 3 additional evidence_"
    "review flag variants), real-PostgreSQL environment: the FULL mutation.mutation_journal row "
    "set (every column, every row, real SQL SELECT) is IDENTICAL before vs after - no row was "
    "created for ANY resource_key/action_family, not merely 'the count matches'",
    _legacy_journal_snapshot_before == _legacy_journal_snapshot_after,
    f"before={_legacy_journal_snapshot_before!r} after={_legacy_journal_snapshot_after!r}",
)
check(
    "all 20 legacy mutation bypass scenarios (17 legacy executables + 3 additional evidence_"
    "review flag variants), real-PostgreSQL environment: the REAL data/ tree is byte-for-byte "
    "UNCHANGED",
    _legacy_data_snapshot_before == _legacy_data_snapshot_after,
    f"changed/added/removed keys: "
    f"{sorted(set(_legacy_data_snapshot_before) ^ set(_legacy_data_snapshot_after))}",
)


_SUGGESTION_ID = "qa_agent_suggestion_cli_pgint_001"


def make_deadline_case(base_name):
    case_id = f"{base_name}_{RUN_TOKEN}"
    destination = _TMP_CASES / case_id
    shutil.copytree(_REAL_CASES_ROOT / "case_0001", destination)
    for path in destination.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "case_0001" in text:
            path.write_text(text.replace("case_0001", case_id), encoding="utf-8")
    for path in sorted(destination.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if "case_0001" in path.name:
            path.rename(path.with_name(path.name.replace("case_0001", case_id)))

    pending_path = deadline_approval.get_pending_path(case_id)
    canonical_path = deadline_approval.get_canonical_path(case_id)
    if canonical_path.exists():
        canonical_path.unlink()
    reviews_dir = deadline_approval.get_reviews_dir(case_id)
    if reviews_dir.is_dir():
        shutil.rmtree(reviews_dir)

    return {
        "case_id": case_id,
        "resource_key": _mutation_lock.case_resource_key(case_id),
        "pending_path": pending_path,
        "canonical_path": canonical_path,
        "expected_hash": sha256_file(pending_path),
    }


def make_qa_case(base_name):
    case_id = f"{base_name}_{RUN_TOKEN}"
    destination = _TMP_CASES / case_id
    shutil.copytree(_REAL_CASES_ROOT / "case_0001", destination)
    for path in destination.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "case_0001" in text:
            path.write_text(text.replace("case_0001", case_id), encoding="utf-8")
    for path in sorted(destination.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if "case_0001" in path.name:
            path.rename(path.with_name(path.name.replace("case_0001", case_id)))

    real_output = qa_engine.build_qa_engine_output(case_id)
    real_output["qa_agent_suggestions"] = [{
        "suggestion_id": _SUGGESTION_ID, "suggestion_type": "needs_deeper_human_review",
        "related_check_result_id": real_output["qa_check_results"][0]["check_result_id"],
        "related_scope_id": real_output["qa_check_results"][0]["scope_id"],
        "related_issue_id": None, "grounded_explanation": "Row 19C-3b CLI real-PostgreSQL integration test.",
        "suggestion_review_state": "needs_review",
        "suggestion_dedup_fingerprint": f"dedup_{case_id}",
        "suggestion_content_fingerprint": f"content_{case_id}",
    }]
    canonical_path = qa_review.get_canonical_path(case_id)
    reviews_dir = qa_review.get_qa_review_audit_dir(case_id)
    if reviews_dir.is_dir():
        shutil.rmtree(reviews_dir)
    qa_review.atomic_write_json(canonical_path, real_output)

    return {
        "case_id": case_id,
        "resource_key": _mutation_lock.case_resource_key(case_id),
        "canonical_path": canonical_path,
        "expected_hash": sha256_file(canonical_path),
    }


def run_cli(argv):
    """Runs the REAL `ui.cli_mutate.main()` against real PostgreSQL end
    to end - both the authz connection and the mutation connection are
    real `pg_connect()`-shaped connections (never a fake)."""
    import io
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_mutate.main(argv, authz_conn_factory=pg_connect, mutation_conn_factory=pg_connect, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


try:
    # ============================================================
    # SCENARIO 1 - REAL approval CLI mutation, preview then apply.
    # ============================================================

    fx1 = make_deadline_case("case_cli_approval_fresh")
    seed_assignment(101, fx1["case_id"], "lawyer")

    code, out, err = run_cli(["approval", "--case", fx1["case_id"], "--row-key", "deadline", "--actor-user-id", "101"])
    check("scenario 1 preview: exit 0", code == cli_mutate.EXIT_OK, f"err={err}")
    check("scenario 1 preview: prints the real pending hash", fx1["expected_hash"] in out, f"out={out}")

    code, out, err = run_cli([
        "approval", "--case", fx1["case_id"], "--row-key", "deadline", "--actor-user-id", "101",
        "--approve", "--expected-hash", fx1["expected_hash"],
    ])
    check("scenario 1 apply: exit 0", code == cli_mutate.EXIT_OK, f"err={err}")
    check("scenario 1 apply: the REAL canonical file was written", fx1["canonical_path"].exists())
    rows1 = journal_rows(fx1["resource_key"])
    check("scenario 1: exactly one REAL journal row, state='completed'", len(rows1) == 1 and rows1[0]["state"] == "completed", f"rows={rows1}")
    check("scenario 1: journal row's action_family is 'approval.deadline'", rows1[0]["action_family"] == "approval.deadline")
    check("scenario 1: journal row's actor_user_id is the REAL --actor-user-id (101)", rows1[0]["actor_user_id"] == 101)
    check("scenario 1: journal row's actor_label is '101' (str(user_id))", rows1[0]["actor_label"] == "101")

    # ============================================================
    # SCENARIO 2 - REAL review CLI mutation (CLI channel), preview
    # then apply - proves action_family suffix + reviewer_ref + real
    # actor binding, all against a real database.
    # ============================================================

    fx2 = make_qa_case("case_cli_review_fresh")
    seed_assignment(102, fx2["case_id"], "lawyer")

    code, out, err = run_cli([
        "review", "--case", fx2["case_id"], "--review-kind", "qa.suggestion", "--record-id", _SUGGESTION_ID,
        "--actor-user-id", "102",
    ])
    check("scenario 2 preview: exit 0", code == cli_mutate.EXIT_OK, f"err={err}")
    check("scenario 2 preview: prints the real canonical hash", fx2["expected_hash"] in out, f"out={out}")

    code, out, err = run_cli([
        "review", "--case", fx2["case_id"], "--review-kind", "qa.suggestion", "--record-id", _SUGGESTION_ID,
        "--actor-user-id", "102", "--apply", "--target-state", "accepted_for_follow_up",
        "--note", "Row 19C-3b real CLI channel note", "--expected-hash", fx2["expected_hash"],
    ])
    check("scenario 2 apply: exit 0", code == cli_mutate.EXIT_OK, f"err={err}")
    rows2 = journal_rows(fx2["resource_key"])
    check("scenario 2: exactly one REAL journal row, state='completed'", len(rows2) == 1 and rows2[0]["state"] == "completed", f"rows={rows2}")
    check(
        "scenario 2: journal row's action_family carries the '.cli' suffix (real CLI-channel proof)",
        rows2[0]["action_family"] == "review.qa.suggestion.cli",
    )
    check("scenario 2: journal row's actor_user_id/actor_label bind the REAL actor (102)", rows2[0]["actor_user_id"] == 102 and rows2[0]["actor_label"] == "102")
    audit_files2 = list(qa_review.get_qa_review_audit_dir(fx2["case_id"]).glob("*.review_audit.json"))
    check("scenario 2: exactly one REAL audit file was written", len(audit_files2) == 1)
    audit2 = json.loads(audit_files2[0].read_text(encoding="utf-8"))
    check("scenario 2: the REAL audit record's reviewer_ref is 'local_lawyer_cli'", audit2["reviewer_ref"] == "local_lawyer_cli")
    check("scenario 2: the REAL audit record's mutation_actor_ref is '102'", audit2["mutation_actor_ref"] == "102")

    # ============================================================
    # SCENARIO 3 - OUTER AUTHZ DENIAL (unassigned actor) -> ZERO
    # journal row, ZERO lock, existence-blind vs. a nonexistent actor.
    # ============================================================

    fx3 = make_deadline_case("case_cli_unassigned")
    # actor 103 exists in iam.users but has NO case_assignments row for fx3.

    code, out, err = run_cli([
        "approval", "--case", fx3["case_id"], "--row-key", "deadline", "--actor-user-id", "103",
        "--approve", "--expected-hash", fx3["expected_hash"],
    ])
    check("scenario 3: unassigned real actor -> exit 1 (domain error)", code == cli_mutate.EXIT_DOMAIN_ERROR)
    check("scenario 3: unassigned real actor -> the fixed generic denial message", out == "" and err.strip() == cli_mutate._AUTHZ_DENIAL_MESSAGE)
    check("scenario 3: ZERO real journal rows were created for this resource_key", journal_rows(fx3["resource_key"]) == [])
    check("scenario 3: the REAL canonical file was NEVER written", not fx3["canonical_path"].exists())

    code_nx, out_nx, err_nx = run_cli([
        "approval", "--case", fx3["case_id"], "--row-key", "deadline", "--actor-user-id", "999999",
        "--approve", "--expected-hash", fx3["expected_hash"],
    ])
    check(
        "scenario 3: a NONEXISTENT actor produces the IDENTICAL exit code and message as an "
        "unassigned-but-real actor (existence-blind, against a REAL database)",
        code_nx == code and err_nx.strip() == err.strip(),
    )

    # ============================================================
    # SCENARIO 4 - SAME-CASE LOCK SERIALIZATION, via a real
    # cli_mutate.main() invocation blocked behind a REAL held
    # pg_advisory_lock on the SAME resource_key.
    # ============================================================

    fx4 = make_deadline_case("case_cli_lockblock")
    seed_assignment(104, fx4["case_id"], "lawyer")

    holder_conn4 = pg_connect()
    holder_lock_id4 = _mutation_lock.acquire_case_lock_session(holder_conn4, fx4["case_id"])
    check("scenario 4: connection A really acquired the case lock", isinstance(holder_lock_id4, int))

    blocked = {}

    def run_blocked_cli():
        blocked["result"] = run_cli([
            "approval", "--case", fx4["case_id"], "--row-key", "deadline", "--actor-user-id", "104",
            "--approve", "--expected-hash", fx4["expected_hash"],
        ])

    worker4 = threading.Thread(target=run_blocked_cli, daemon=True)
    worker4.start()

    def wait_for_waiter(advisory_lock_id, timeout=15.0):
        deadline_t = time.monotonic() + timeout
        conn = pg_connect()
        try:
            while time.monotonic() < deadline_t:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=%s AND NOT granted",
                        (advisory_lock_id,),
                    )
                    (n,) = cur.fetchone()
                if n > 0:
                    return True
                time.sleep(0.1)
            return False
        finally:
            conn.close()

    check("scenario 4: PostgreSQL's OWN pg_locks reports a genuinely WAITING advisory lock", wait_for_waiter(holder_lock_id4))
    check("scenario 4: the blocked CLI invocation is STILL RUNNING (thread alive)", worker4.is_alive())

    _mutation_lock.release_lock_session(holder_conn4, holder_lock_id4)
    holder_conn4.close()
    worker4.join(timeout=15.0)
    check("scenario 4: the blocked CLI invocation completed after the lock was released", not worker4.is_alive())
    code4, out4, err4 = blocked.get("result", (None, "", ""))
    check("scenario 4: the previously-blocked CLI invocation eventually succeeded (exit 0)", code4 == cli_mutate.EXIT_OK, f"err={err4}")

    # ============================================================
    # SCENARIO 5 - INNER AUTHZ REVOCATION MID-LOCK-WAIT: the case
    # assignment is revoked (via a REAL third connection) WHILE a CLI
    # attempt is blocked waiting for the case lock - the facade's OWN
    # inner (under-lock, authoritative) authorize_case_access() call
    # must catch this, even though the OUTER (pre-lock) check already
    # passed.
    # ============================================================

    fx5 = make_deadline_case("case_cli_inner_revoke")
    seed_assignment(105, fx5["case_id"], "lawyer")

    holder_conn5 = pg_connect()
    holder_lock_id5 = _mutation_lock.acquire_case_lock_session(holder_conn5, fx5["case_id"])

    blocked5 = {}

    def run_blocked_cli5():
        blocked5["result"] = run_cli([
            "approval", "--case", fx5["case_id"], "--row-key", "deadline", "--actor-user-id", "105",
            "--approve", "--expected-hash", fx5["expected_hash"],
        ])

    worker5 = threading.Thread(target=run_blocked_cli5, daemon=True)
    worker5.start()
    check("scenario 5: the second real connection is genuinely waiting on the case lock", wait_for_waiter(holder_lock_id5))

    # Revoke WHILE the CLI attempt is still blocked - its OUTER check
    # already ran and passed (that happened before it ever tried to
    # acquire the lock); only the INNER, under-lock check can still see
    # this revocation.
    revoke_assignment(105, fx5["case_id"])

    _mutation_lock.release_lock_session(holder_conn5, holder_lock_id5)
    holder_conn5.close()
    worker5.join(timeout=15.0)
    code5, out5, err5 = blocked5.get("result", (None, "", ""))
    check(
        "scenario 5: the INNER (under-lock) authz check catches the mid-wait revocation -> "
        "exit 1, generic denial, ZERO mutation",
        code5 == cli_mutate.EXIT_DOMAIN_ERROR and err5.strip() == cli_mutate._AUTHZ_DENIAL_MESSAGE,
        f"code={code5} err={err5}",
    )
    check("scenario 5: ZERO real journal rows were created (the outer pre_hash snapshot never became a prepared row)", journal_rows(fx5["resource_key"]) == [])
    check("scenario 5: the REAL canonical file was NEVER written", not fx5["canonical_path"].exists())

finally:
    for _m, _original in _original_cases_dirs:
        _m.CASES_DIR = _original
    qa_validator.BASE_DIR = _original_qa_validator_base_dir
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

_real_data_after = snapshot_real_data_tree()
check(
    "this repository's REAL data/ tree is byte-for-byte UNCHANGED by this entire suite",
    _real_data_before == _real_data_after,
    f"diff_count={len(set(_real_data_before) ^ set(_real_data_after))}",
)

summarize_and_exit()
