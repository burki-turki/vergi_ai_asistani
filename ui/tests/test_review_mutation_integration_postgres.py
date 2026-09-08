# ============================================================
# Row 19C-2b - REAL, END-TO-END PostgreSQL INTEGRATION PROOF for the
# PRODUCTION Layer B review-mutation path (`review_mutation_facade.
# apply_review_mutation()`, wired exactly as `ui.services.review_
# registry.apply_transition()` -> `ui/main.py`'s `review_confirm` route
# wires it).
#
# WHAT IS REAL HERE - mirrors `ui/tests/test_mutation_approval_
# integration_postgres.py`'s own discipline exactly, for the SECOND
# production writer family this project's mutation-journal
# infrastructure is connected to:
#   - `ui.services.review_mutation_facade.apply_review_mutation()` -
#     the real production facade;
#   - `ui.services.mutation_lock.acquire_case_lock_session()`/
#     `release_lock_session()` - the REAL session-level
#     `pg_advisory_lock`/`pg_advisory_unlock`, never monkeypatched (this
#     is what makes the two-connection blocking proof meaningful);
#   - `ui.services.mutation_coordinator.run_mutation()` - the real
#     coordinator, against the real `mutation.mutation_journal` table;
#   - `ui.services.mutation_registry.reconcile_and_apply_journal_entry()`
#     and the REAL production Layer B adapter registry from
#     `ui.services.review_mutation_adapters.build_production_registry()`
#     - never a test-only adapter;
#   - `src/qa_review.py`'s REAL `apply_review_transition()` - a real
#     Layer B writer, running its real post-write `validate_qa_
#     analysis()`, real backup, real atomic canonical write, real audit
#     record;
#   - `qa_engine.build_qa_engine_output()` - the REAL, deterministic
#     (no LLM/agent) Row 16 engine, run against a re-identified COPY of
#     this repository's own real `case_0001` upstream data, so the real
#     validator genuinely accepts the fixture;
#   - `psycopg` - the real production driver. No `psql`-subprocess shim
#     fallback: if `psycopg` is not importable, this file SKIPS loudly.
#
# WHAT IS NOT REAL:
#   1. IAM/authz: `authz_repository=` is an in-memory fake (this file's
#      subject is mutation integrity, not IAM persistence).
#   2. The case tree: a REAL, independently re-identified COPY of
#      `data/cases/case_0001`, living under a fresh `tempfile.mkdtemp()`
#      - the real repository's own `data/` tree is NEVER read or
#      written during a scenario (proven at the end, byte-for-byte).
#   3. ONE deliberately-injected fault, at a precisely-named boundary
#      (`_writer_fault`, a pass-through wrapper around the real
#      `qa_review.apply_review_transition`), for the reconciliation
#      scenario that cannot otherwise be reached deterministically -
#      mirrors `test_mutation_approval_integration_postgres.py`'s own
#      `_writer_fault` exactly, adapted to `qa_review`'s own writer
#      signature (`(case_id, suggestion_id, target_state, reviewer_ref,
#      review_note, canonical_path=None, audit_dir=None, *, ...)`).
#
# SETUP (opt-in, never silently skipped): same convention as `test_
# mutation_approval_integration_postgres.py` - `VERGI_TEST_PG_DSN`
# (a bare database NAME, applied against `db/migrations/0001..0004`)
# plus ordinary libpq `PGHOST`/`PGPORT`/`PGUSER`.
#
# Run: python -m ui.tests.test_review_mutation_integration_postgres
# ============================================================

import json
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


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type as error:
        check(label, True)
        return error
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")
    return None


def summarize_and_exit():
    print(
        f"--- test_review_mutation_integration_postgres: {passed} passed, "
        f"{failed} failed, {skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")

if not PG_DB:
    skip(
        "the entire real-PostgreSQL review-mutation integration suite",
        "VERGI_TEST_PG_DSN is not set (no disposable database with migrations "
        "0001+0002+0003+0004 applied is configured for this run). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover - environment-dependent
    skip(
        "the entire real-PostgreSQL review-mutation integration suite",
        f"VERGI_TEST_PG_DSN is set but `import psycopg` failed ({_psycopg_error!r}). "
        "NOT EXECUTED, not a pass",
    )
    summarize_and_exit()


from ui.services import authz as _authz                                  # noqa: E402
from ui.services import mutation_coordinator as mutcoord                 # noqa: E402
from ui.services import mutation_lock as _mutation_lock                  # noqa: E402
from ui.services import mutation_registry as mr                          # noqa: E402
from ui.services import paths as _paths                                  # noqa: E402
from ui.services import review_mutation_adapters as _adapters            # noqa: E402
from ui.services import review_mutation_facade as facade                 # noqa: E402
from ui.services.common import ReviewStaleViewError                      # noqa: E402

import qa_review                                                          # noqa: E402
import qa_engine                                                          # noqa: E402
import qa_approval                                                        # noqa: E402
from mutation_guard import RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED  # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")

REVIEW_KIND = "qa.suggestion"
ACTION_FAMILY = facade.action_family_for(REVIEW_KIND)


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


# ----------------------------------------------------------------
# Preflight - same discipline as test_mutation_approval_integration_postgres.py.
# ----------------------------------------------------------------

_preflight = pg_connect()
try:
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'mutation' AND table_name IN ('mutation_journal', 'mutation_resources')"
        )
        (_table_count,) = cur.fetchone()
    check(
        "preflight: mutation.mutation_journal AND mutation.mutation_resources both exist (0002+0003 applied)",
        _table_count == 2, f"found {_table_count} of the 2 expected tables",
    )
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'mutation' AND table_name = 'mutation_journal' "
            "AND column_name IN ('reconciled_by_actor_type', 'reconciled_by_actor_ref', "
            "'request_fingerprint', 'actor_label')"
        )
        (_prov_count,) = cur.fetchone()
    check(
        "preflight: 0004's provenance columns AND the pre-existing request_fingerprint/actor_label columns all exist",
        _prov_count == 4, f"found {_prov_count} of the 4 expected columns",
    )
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run the integration scenarios against a half-migrated database.")
    summarize_and_exit()


_ACTOR_USER_IDS = (1, 2, 7)

_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for _user_id in _ACTOR_USER_IDS:
            cur.execute(
                "INSERT INTO iam.users (id, display_name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (_user_id, f"row19c2b-integration-actor-{_user_id}"),
            )
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('iam.users', 'id'), "
            "GREATEST((SELECT max(id) FROM iam.users), 1))"
        )
        cur.execute("SELECT count(*) FROM iam.users WHERE id = ANY(%s)", (list(_ACTOR_USER_IDS),))
        (_seeded_count,) = cur.fetchone()
finally:
    _seed.close()

check(
    "preflight: every actor this suite uses really exists in iam.users",
    _seeded_count == len(_ACTOR_USER_IDS),
    f"seeded {_seeded_count} of {len(_ACTOR_USER_IDS)} expected actor rows",
)

if failed:
    print("Actor seeding failed - refusing to run the integration scenarios.")
    summarize_and_exit()


_JOURNAL_COLUMNS = (
    "id, resource_key, action_family, actor_user_id, actor_label, target_ref, target_state, "
    "pre_hash, pre_revision, idempotency_key, request_fingerprint, state, failure_code, "
    "resolution_code, observed_post_hash, executing_at, resolved_at, "
    "reconciled_by_actor_type, reconciled_by_actor_ref"
)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_JOURNAL_COLUMNS} FROM mutation.mutation_journal "
                "WHERE resource_key = %s ORDER BY id",
                (resource_key,),
            )
            names = [d.name for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]
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


def lock_is_held_by_anyone(advisory_lock_id):
    return _count_advisory_locks(advisory_lock_id, granted=True) > 0


def wait_for_lock_waiter(advisory_lock_id, *, timeout_seconds=30.0, poll_seconds=0.1):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _count_advisory_locks(advisory_lock_id, granted=False) > 0:
            return True
        time.sleep(poll_seconds)
    return False


def make_directory_escape_link(link_path: Path, target_path: Path) -> None:
    """ROW 19C-3a SLICE 2 REAL-POSTGRES PATH-PROOF REMEDIATION: a REAL,
    platform-native directory-escape link - NTFS junction via
    `mklink /J` on Windows (needs neither elevation nor Developer Mode),
    a real POSIX symlink elsewhere - an independent copy of `ui/tests/
    test_mutation_approval_integration_postgres.py`'s own identically-
    purposed helper (this file's own test-only utility, never shared/
    imported). A failed link creation raises - never silently treated
    as a skip or a pass."""
    if sys.platform == "win32":
        # `capture_output=True, text=True` would decode stdout/stderr
        # using the console's own (here: Turkish, cp1254) codepage - a
        # genuine `mklink` failure can emit a localized error message
        # containing a byte that codepage cannot decode, crashing the
        # reader thread with a SECOND, unrelated UnicodeDecodeError that
        # masks the real one. Captured as raw bytes and decoded with
        # `errors="replace"` instead, so any real failure's message is
        # always readable.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            stdout_text = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
            stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            raise RuntimeError(f"mklink /J failed (rc={result.returncode}): {stdout_text!r} {stderr_text!r}")
    else:
        os.symlink(str(target_path), str(link_path))


def sha256_file(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


# ----------------------------------------------------------------
# Case fixture - a REAL, independently re-identified copy of case_0001,
# under a fresh tempdir, with a FRESH, real, deterministic QA analysis
# (qa_engine.build_qa_engine_output - no LLM/agent) plus one appended
# 'needs_review' suggestion. Mirrors test_mutation_approval_
# integration_postgres.py's own make_case() re-identification pattern.
# ----------------------------------------------------------------

RUN_TOKEN = uuid.uuid4().hex[:10]
_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))

PRODUCTION_REGISTRY = _adapters.build_production_registry()
check(
    "the REAL production Layer B adapter registry covers all 12 review_kind families",
    len(PRODUCTION_REGISTRY.known_action_families()) == 12,
    f"got {sorted(PRODUCTION_REGISTRY.known_action_families())}",
)
check(
    "the REAL production registry has an adapter registered for this file's own action_family",
    ACTION_FAMILY in PRODUCTION_REGISTRY.known_action_families(),
)


def discover_cases_dir_holders():
    """Same sweep `test_mutation_approval_integration_postgres.py` uses:
    `qa_engine`/`qa_validator` and their own transitive validator chain
    (issues/facts/timeline/deadline/...) each define their OWN module-
    level `CASES_DIR` constant, imported at THEIR own top level from
    `data/cases` directly (the "~30 files use paths.CASES_DIR directly"
    surface Row 19A's own opening gate names) - a hardcoded, guessed
    subset would silently miss one and let a real validator call read
    or write the REAL repository's own `data/cases/` tree."""
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


# `_TMP_CASES` deliberately mirrors the REAL repo layout exactly
# (`BASE_DIR/data/cases`, matching `qa_discovery.py`'s own
# `BASE_DIR`/`DATA_DIR`/`CASES_DIR` triple) rather than a flatter
# `_TMP_ROOT/cases` - see the `qa_validator.BASE_DIR` redirect below,
# which needs `<redirected BASE_DIR>/"data"/"cases"` to resolve to this
# exact directory.
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_review_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
_original_cases_dirs = [(m, m.CASES_DIR) for m in _cases_dir_holders]

check(
    "the CASES_DIR redirect sweep found the real production modules to redirect "
    "(qa_review/qa_engine + their transitive validator chain)",
    len(_cases_dir_holders) >= 3
    and any(getattr(m, "__name__", "") == "qa_approval" for m in _cases_dir_holders)
    and any(getattr(m, "__name__", "") == "ui.services.paths" for m in _cases_dir_holders),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
print(f"redirecting CASES_DIR for {len(_cases_dir_holders)} loaded module(s) -> {_TMP_CASES}")

for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

# `qa_validator.py` is the ONE module in this project's validator chain
# that does NOT hold its own `CASES_DIR` attribute at all - it imports
# `BASE_DIR` BY VALUE from `qa_discovery` (`from qa_discovery import
# BASE_DIR, ...`) at ITS OWN import time and hardcodes `BASE_DIR /
# "data" / "cases" / <case_id> / "case.json"` inline, INSIDE its stale-
# snapshot manifest comparison (verified by reading `src/qa_validator.py`
# directly - line 17's import, line 80's inline construction). Since
# `from X import Y` snapshots `X.Y`'s value into the IMPORTING module's
# own namespace, redirecting `qa_discovery.CASES_DIR` (done above) has
# NO effect on `qa_validator`'s own, already-bound `BASE_DIR` name - a
# SEPARATE, explicit redirect of `qa_validator.BASE_DIR` itself is
# required, or this specific stale-snapshot check would keep reading
# `case.json` from the REAL repository's own `data/cases/<case_id>/`
# (which does not exist for this file's synthetic case_id at all).
import qa_validator  # noqa: E402
_original_qa_validator_base_dir = qa_validator.BASE_DIR
qa_validator.BASE_DIR = _TMP_ROOT

_SUGGESTION_ID = "qa_agent_suggestion_pgint_001"


def make_case(base_name):
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
        "related_issue_id": None, "grounded_explanation": "Row 19C-2b real-PostgreSQL integration test.",
        "suggestion_review_state": "needs_review",
        "suggestion_dedup_fingerprint": "dedup_pgint_001",
        "suggestion_content_fingerprint": "content_pgint_001",
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


def make_principal_and_repo(case_id, *, user_id=1, session_id=100, assigned=True, role="lawyer"):
    principal = _authz.Principal(user_id=user_id, session_id=session_id, role_version_at_issue=1)
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[session_id] = _authz.SessionRecord(user_id=user_id, current_authz_version=1, disabled=False)
    if assigned:
        repo.assignments[(user_id, case_id)] = _authz.CaseAssignmentRecord(role=role)
    return principal, repo


def qa_binding():
    return facade.ReviewFamilyBinding(
        review_kind=REVIEW_KIND, module=qa_review, record_type="suggestion", call_shape="qa_special",
        state_field="suggestion_review_state", domain_error_class=qa_review.QaReviewError,
        get_audit_dir_fn=qa_review.get_qa_review_audit_dir, reviewer_ref="local_lawyer_ui",
        # ROW 19C-3a SLICE 2: `qa_review.py` has no `CASES_DIR` of its
        # own - `qa_approval` is the correct anchor (matches `review_
        # registry.REVIEW_KIND_REGISTRY["qa.suggestion"]["cases_dir_
        # module"]` exactly). `qa_approval` is already one of the 18
        # modules this file's own CASES_DIR redirect sweep covers.
        cases_dir_anchor_module=qa_approval,
    )


def confirm(fixture, principal, repo, *, target_state="accepted_for_follow_up", note="pgint note", expected_hash=None):
    return facade.apply_review_mutation(
        REVIEW_KIND, fixture["case_id"], _SUGGESTION_ID, target_state, note,
        expected_hash if expected_hash is not None else fixture["expected_hash"],
        qa_binding(), principal=principal, authz_repository=repo, conn_factory=pg_connect,
    )


_REAL_APPLY_REVIEW_TRANSITION = qa_review.apply_review_transition
writer_state = {"calls": 0, "fault": None}


def _writer_fault(case_id, suggestion_id, target_state, reviewer_ref, review_note, canonical_path=None, audit_dir=None, **kwargs):
    writer_state["calls"] += 1
    fault = writer_state["fault"]
    if fault == "before":
        raise RuntimeError("INJECTED FAULT (before): simulating a failure before the real writer ran at all")
    result = _REAL_APPLY_REVIEW_TRANSITION(
        case_id, suggestion_id, target_state, reviewer_ref, review_note,
        canonical_path=canonical_path, audit_dir=audit_dir, **kwargs,
    )
    if fault == "after":
        raise RuntimeError(
            "INJECTED FAULT (after): the REAL qa_review.apply_review_transition() completed in full "
            "(real canonical write + real audit record), and the call then failed to return cleanly"
        )
    return result


qa_review.apply_review_transition = _writer_fault


def snapshot_real_data_tree():
    """A byte-level manifest of this repository's real `data/` tree
    (not just CASES_DIR itself) - used to prove at the end that no
    scenario ever touched it, mirroring `test_mutation_approval_
    integration_postgres.py`'s own identical proof."""
    manifest = {}
    data_dir = _REAL_CASES_ROOT.parent
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            try:
                manifest[str(path)] = (path.stat().st_size, sha256_file(path))
            except OSError:
                manifest[str(path)] = ("unreadable", None)
    return manifest


_real_data_before = None
try:
    _real_data_before = snapshot_real_data_tree()

    # ============================================================
    # SCENARIO 1 - FRESH MUTATION, FULL PRODUCTION STACK.
    # ============================================================

    fx1 = make_case("case_pgint_fresh")
    principal1, repo1 = make_principal_and_repo(fx1["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    result1 = confirm(fx1, principal1, repo1)

    check("scenario 1: replayed=False", result1.replayed is False)
    check("scenario 1: the REAL writer was invoked exactly once", writer_state["calls"] == 1)
    check(
        "scenario 1: the REAL canonical artefact now shows the target state",
        json.loads(fx1["canonical_path"].read_text(encoding="utf-8"))["qa_agent_suggestions"][0]["suggestion_review_state"]
        == "accepted_for_follow_up",
    )
    rows1 = journal_rows(fx1["resource_key"])
    check(
        "scenario 1: exactly one REAL journal row exists in the database, state='completed'",
        len(rows1) == 1 and rows1[0]["state"] == "completed",
        f"rows={rows1}",
    )
    check("scenario 1: the journal row's action_family is review.qa.suggestion", rows1[0]["action_family"] == ACTION_FAMILY)
    check(
        "scenario 1: the journal row's observed_post_hash equals the REAL canonical file's own hash",
        rows1[0]["observed_post_hash"] == sha256_file(fx1["canonical_path"]),
    )
    check(
        "scenario 1: 0004's reconciliation-provenance columns are NULL for a directly-completed row "
        "(never reconciled, so nothing to attribute)",
        rows1[0]["reconciled_by_actor_type"] is None and rows1[0]["reconciled_by_actor_ref"] is None,
    )

    # ============================================================
    # SCENARIO 2 - SAFE REPLAY.
    # ============================================================

    writer_state["calls"] = 0
    result2 = confirm(fx1, principal1, repo1)
    check("scenario 2: replayed=True", result2.replayed is True)
    check("scenario 2: the REAL writer was NOT re-invoked", writer_state["calls"] == 0)
    check("scenario 2: the SAME real journal row was reused", result2.journal_id == result1.journal_id)
    check("scenario 2: no SECOND journal row was created in the real database", len(journal_rows(fx1["resource_key"])) == 1)
    check(
        "scenario 2: the replay is deterministic - same journal_id, same canonical_hash",
        result2.journal_id == result1.journal_id and result2.canonical_hash == result1.canonical_hash,
    )

    # ============================================================
    # SCENARIO 3 - TWO REAL CONNECTIONS, ONE REAL CASE LOCK.
    # ============================================================

    fx3 = make_case("case_pgint_lockblock")
    principal3, repo3 = make_principal_and_repo(fx3["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    holder_conn = pg_connect()
    holder_lock_id = _mutation_lock.acquire_case_lock_session(holder_conn, fx3["case_id"])
    check("scenario 3: connection A really acquired the case lock", isinstance(holder_lock_id, int))

    blocked_result = {}

    def run_blocked_confirm():
        try:
            blocked_result["result"] = confirm(fx3, principal3, repo3)
        except BaseException as error:
            blocked_result["error"] = error

    worker = threading.Thread(target=run_blocked_confirm, daemon=True)
    worker.start()

    observed_waiter = wait_for_lock_waiter(holder_lock_id)
    check(
        "scenario 3: PostgreSQL's OWN pg_locks reports a genuinely WAITING advisory lock on this case",
        observed_waiter,
    )
    check(
        "scenario 3: the second real connection is STILL BLOCKED on the real case lock",
        worker.is_alive() and "result" not in blocked_result and "error" not in blocked_result,
        f"blocked_result={blocked_result!r}",
    )
    check(
        "scenario 3: while blocked, it has written NOTHING to the real journal",
        journal_rows(fx3["resource_key"]) == [],
    )
    check("scenario 3: the REAL writer has not been invoked while blocked", writer_state["calls"] == 0)

    released = _mutation_lock.release_lock_session(holder_conn, holder_lock_id)
    check("scenario 3: connection A's real lock release reported success", released is True)
    holder_conn.close()

    worker.join(timeout=90)
    check("scenario 3: once A released, the blocked request completed", not worker.is_alive())
    check(
        "scenario 3: the previously-blocked request succeeded on its own connection",
        "error" not in blocked_result and blocked_result.get("result") is not None,
        f"blocked_result={blocked_result!r}",
    )
    if blocked_result.get("result") is not None:
        check(
            "scenario 3: it then really journaled 'completed' with the writer invoked exactly once",
            len(journal_rows(fx3["resource_key"])) == 1
            and journal_rows(fx3["resource_key"])[0]["state"] == "completed"
            and writer_state["calls"] == 1,
        )

    # ============================================================
    # SCENARIO 4 - IDENTITY/FINGERPRINT CONFLICT: same identity
    # (same actor/resource/target/pre_revision), DIFFERENT note ->
    # IdempotencyConflictError, ZERO new journal rows, ZERO writer
    # invocation for this attempt.
    # ============================================================

    fx4 = make_case("case_pgint_fpconflict")
    principal4, repo4 = make_principal_and_repo(fx4["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    confirm(fx4, principal4, repo4, note="the FIRST note")
    check("scenario 4 preflight: the first confirm really completed", journal_rows(fx4["resource_key"])[0]["state"] == "completed")
    writer_state["calls"] = 0

    expect_raises(
        mutcoord.IdempotencyConflictError,
        # same target_state as scenario's own default target ("accepted_for_follow_up") is now
        # STALE (the record is no longer needs_review) - use the SAME expected_hash (pre_revision,
        # part of identity) but a DIFFERENT note, which is exactly the fingerprint-only conflict
        # this scenario proves; expected_hash is deliberately the ORIGINAL pre-mutation hash so
        # identity matches the ALREADY-COMPLETED row exactly.
        lambda: confirm(fx4, principal4, repo4, note="a COMPLETELY different note"),
        "scenario 4: same identity + different note -> IdempotencyConflictError (real database)",
    )
    check("scenario 4: the writer was NOT invoked for the conflicting attempt", writer_state["calls"] == 0)
    check("scenario 4: still exactly ONE real journal row for this resource", len(journal_rows(fx4["resource_key"])) == 1)

    # ============================================================
    # SCENARIO 5 - WRITER CRASH (post-writer fault) -> 'reconciliation_required'.
    # ============================================================

    fx5 = make_case("case_pgint_reconcile")
    principal5, repo5 = make_principal_and_repo(fx5["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = "after"

    try:
        expect_raises(
            RuntimeError,
            lambda: confirm(fx5, principal5, repo5),
            "scenario 5: the post-writer fault propagates out of the facade unchanged",
        )
    finally:
        writer_state["fault"] = None

    rows5 = journal_rows(fx5["resource_key"])
    check(
        "scenario 5: the row is 'reconciliation_required' even though the real writer DID succeed",
        len(rows5) == 1 and rows5[0]["state"] == "reconciliation_required",
        f"rows={[(r['id'], r['state']) for r in rows5]}",
    )
    check(
        "scenario 5: the REAL canonical artefact really was flipped by the real writer",
        json.loads(fx5["canonical_path"].read_text(encoding="utf-8"))["qa_agent_suggestions"][0]["suggestion_review_state"]
        == "accepted_for_follow_up",
    )

    # ============================================================
    # SCENARIO 6 - RECONCILIATION via the REAL Layer B production
    # adapter registry, resolving scenario 5's stuck row, WITH
    # provenance.
    # ============================================================

    recon_conn = pg_connect()
    try:
        dry_run6 = mr.inspect_reconciliation(recon_conn, rows5[0]["id"], PRODUCTION_REGISTRY)
        check(
            "scenario 6: the DRY-RUN inspection (REAL Layer B adapter, real evidence) resolves to "
            "'completed' via post-state verification",
            dry_run6.new_state == "completed" and dry_run6.resolution_code == RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
            f"dry_run={dry_run6!r}",
        )
        check(
            "scenario 6: the dry run issued ZERO UPDATEs (the row is still unresolved)",
            journal_rows(fx5["resource_key"])[0]["state"] == "reconciliation_required",
        )
        applied6 = mr.reconcile_and_apply_journal_entry(
            recon_conn, rows5[0]["id"], PRODUCTION_REGISTRY,
            resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c2b-integration-test",
        )
        check("scenario 6: the REAL --apply reconciliation resolved the row to 'completed'", applied6.new_state == "completed")
    finally:
        recon_conn.close()

    rows6_after = journal_rows(fx5["resource_key"])
    check(
        "scenario 6: the real database row is now 'completed' with the RECONCILED resolution_code",
        rows6_after[0]["state"] == "completed"
        and rows6_after[0]["resolution_code"] == RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
        f"row={rows6_after[0]!r}",
    )
    check(
        "scenario 6: 0004's reconciliation provenance really was recorded on the resolved row",
        rows6_after[0]["reconciled_by_actor_type"] == "cli_service"
        and rows6_after[0]["reconciled_by_actor_ref"] == "row19c2b-integration-test",
    )
    check(
        "scenario 6: the reconciled observed_post_hash equals the REAL canonical file's own current hash",
        rows6_after[0]["observed_post_hash"] == sha256_file(fx5["canonical_path"]),
    )
    check(
        "scenario 6: reconciliation did NOT re-invoke the writer (evidence-gathering is read-only)",
        writer_state["calls"] == 1,
    )
    check(
        "scenario 6: the resource is no longer gated - the row reached a terminal state",
        all(r["state"] not in ("prepared", "executing", "reconciliation_required") for r in rows6_after),
    )

    # ================================================================
    # ROW 19C-3a SLICE 2 REAL-POSTGRES PATH-PROOF REMEDIATION
    #
    # SCENARIO B1 - PRE-LOCK AUDIT-DIRECTORY ESCAPE, against the REAL
    # production `review_registry.apply_transition()` -> facade ->
    # coordinator path, a REAL disposable PostgreSQL journal, and a REAL
    # NTFS junction (never monkeypatched/mocked). `qa_review.get_qa_
    # review_audit_dir()` (the real, unmocked audit-dir getter for
    # `qa.suggestion` - anchored to `qa_approval.CASES_DIR`, the ONE
    # registry exception) is made a live junction pointing OUTSIDE the
    # case root, with a forged, perfectly-shaped audit record planted
    # inside - proving the REAL facade raises `ReviewDirectoryScanError`
    # BEFORE any journal/lock connection is opened, the real journal has
    # ZERO rows, the writer never ran, and the forged content was never
    # read (byte-identical before/after).
    # ================================================================

    fx_b1 = make_case("case_b1_prelock_escape")
    principal_b1, repo_b1 = make_principal_and_repo(fx_b1["case_id"], user_id=21, session_id=2100)
    writer_state["calls"] = 0
    writer_state["fault"] = None

    audit_dir_b1 = qa_review.get_qa_review_audit_dir(fx_b1["case_id"])
    audit_dir_b1.parent.mkdir(parents=True, exist_ok=True)  # `mklink /J` requires the immediate parent to exist
    outside_root_b1 = Path(tempfile.mkdtemp(prefix="vergi_review_pgint_b1_outside_"))
    try:
        canonical_before_b1 = sha256_file(fx_b1["canonical_path"])
        forged_audit_b1 = {
            "case_id": fx_b1["case_id"], "record_type": "suggestion", "record_id": _SUGGESTION_ID,
            "new_state": "accepted_for_follow_up", "previous_state": "needs_review",
            "reviewer_ref": "local_lawyer_ui", "review_note": "forged - must never be trusted",
            "pre_sha256": fx_b1["expected_hash"], "post_sha256": fx_b1["expected_hash"],
            "mutation_idempotency_key": "forged", "mutation_resource_key": fx_b1["resource_key"],
            "mutation_actor_ref": "999",
        }
        spy_path_b1 = outside_root_b1 / "forged.review_audit.json"
        spy_path_b1.write_text(json.dumps(forged_audit_b1), encoding="utf-8")
        spy_before_b1 = sha256_file(spy_path_b1)

        make_directory_escape_link(audit_dir_b1, outside_root_b1)
        check(
            "B1 precondition: the qa.suggestion audit_dir is genuinely a live junction/symlink "
            "pointing outside the case root",
            os.path.lexists(audit_dir_b1),
        )

        conn_calls_b1 = []

        def _counting_conn_factory_b1():
            conn_calls_b1.append(1)
            return pg_connect()

        b1_error = None
        try:
            facade.apply_review_mutation(
                REVIEW_KIND, fx_b1["case_id"], _SUGGESTION_ID, "accepted_for_follow_up", "b1 note",
                fx_b1["expected_hash"], qa_binding(),
                principal=principal_b1, authz_repository=repo_b1, conn_factory=_counting_conn_factory_b1,
            )
        except BaseException as error:
            b1_error = error

        check(
            "B1: the REAL production facade raised ReviewDirectoryScanError for the live escaping "
            "audit_dir junction",
            isinstance(b1_error, facade.ReviewDirectoryScanError),
            f"got {b1_error!r}",
        )
        check(
            "B1: ZERO journal/lock connections were opened at all (pre-lock failure)",
            conn_calls_b1 == [],
        )
        check(
            "B1: the REAL database has EXACTLY ZERO journal rows for this resource_key",
            journal_rows(fx_b1["resource_key"]) == [],
            f"got {journal_rows(fx_b1['resource_key'])!r}",
        )
        check(
            "B1: PostgreSQL's OWN pg_locks shows no lock was ever requested for this resource",
            lock_is_held_by_anyone(advisory_lock_id_for(fx_b1["resource_key"])) is False,
        )
        check("B1: the REAL qa_review writer was never invoked", writer_state["calls"] == 0)
        check(
            "B1: the canonical artefact is byte-unchanged",
            sha256_file(fx_b1["canonical_path"]) == canonical_before_b1,
        )
        check(
            "B1: the forged audit record planted OUTSIDE the case root was never read/modified "
            "(byte-identical) - it never influenced this rejection",
            sha256_file(spy_path_b1) == spy_before_b1,
        )
    finally:
        if os.path.lexists(audit_dir_b1):
            os.rmdir(audit_dir_b1)  # removes the junction/symlink LINK only, never the target's content
        shutil.rmtree(outside_root_b1, ignore_errors=True)

    # ================================================================
    # SCENARIO B2 - UNDER-LOCK AUDIT-DIRECTORY SWAP, against TWO REAL
    # PostgreSQL connections. Connection A holds the REAL
    # `case:<case_id>` advisory lock; a second, fully independent real
    # connection driving the REAL facade genuinely BLOCKS on it (server-
    # observed via `pg_locks`). WHILE B waits, the (not-yet-existing,
    # therefore safe at B's own pre-lock read) `qa_review_audit_dir` is
    # turned into a live junction pointing OUTSIDE the case root. When A
    # releases, B's FRESH under-lock re-verification must catch the
    # escape - the writer must never run, and the real journal must show
    # ZERO rows. No HTTP route test needed - the service/domain
    # exception itself is the proof.
    # ================================================================

    fx_b2 = make_case("case_b2_underlock_swap")
    principal_b2, repo_b2 = make_principal_and_repo(fx_b2["case_id"], user_id=22, session_id=2200)
    writer_state["calls"] = 0
    writer_state["fault"] = None

    audit_dir_b2 = qa_review.get_qa_review_audit_dir(fx_b2["case_id"])
    audit_dir_b2.parent.mkdir(parents=True, exist_ok=True)  # `mklink /J` requires the immediate parent to exist
    outside_root_b2 = Path(tempfile.mkdtemp(prefix="vergi_review_pgint_b2_outside_"))
    holder_conn_b2 = None
    try:
        holder_conn_b2 = pg_connect()
        holder_lock_id_b2 = _mutation_lock.acquire_case_lock_session(holder_conn_b2, fx_b2["case_id"])
        check(
            "B2: connection A really acquired the REAL case lock (a real advisory_lock_id was assigned)",
            isinstance(holder_lock_id_b2, int),
        )

        blocked_result_b2 = {}

        def _run_blocked_b2():
            try:
                blocked_result_b2["result"] = confirm(fx_b2, principal_b2, repo_b2)
            except BaseException as error:
                blocked_result_b2["error"] = error

        worker_b2 = threading.Thread(target=_run_blocked_b2, daemon=True)
        worker_b2.start()

        observed_waiter_b2 = wait_for_lock_waiter(holder_lock_id_b2)
        check(
            "B2: PostgreSQL's OWN pg_locks reports a genuinely WAITING (not granted) advisory lock "
            "for this case - session B is really blocked",
            observed_waiter_b2,
            f"no NOT-granted advisory lock appeared for advisory_lock_id={holder_lock_id_b2}",
        )
        check(
            "B2: while B waits, it has written NOTHING to the real journal yet",
            journal_rows(fx_b2["resource_key"]) == [],
        )

        # WHILE B waits (proven blocked above), swap the (not-yet-
        # existing, hence safe at B's own pre-lock read) audit_dir to a
        # live escaping junction with a forged matching entry inside.
        forged_audit_b2 = {
            "case_id": fx_b2["case_id"], "record_type": "suggestion", "record_id": _SUGGESTION_ID,
            "new_state": "accepted_for_follow_up", "previous_state": "needs_review",
            "reviewer_ref": "local_lawyer_ui", "review_note": "forged - must never be trusted",
            "pre_sha256": fx_b2["expected_hash"], "post_sha256": fx_b2["expected_hash"],
            "mutation_idempotency_key": "forged", "mutation_resource_key": fx_b2["resource_key"],
            "mutation_actor_ref": "999",
        }
        (outside_root_b2 / "forged.review_audit.json").write_text(json.dumps(forged_audit_b2), encoding="utf-8")
        outside_spy_before_b2 = sha256_file(outside_root_b2 / "forged.review_audit.json")
        make_directory_escape_link(audit_dir_b2, outside_root_b2)
        check(
            "B2 precondition: qa_review_audit_dir is genuinely a live junction/symlink pointing "
            "outside the case root, created WHILE session B was still blocked",
            os.path.lexists(audit_dir_b2),
        )

        released_b2 = _mutation_lock.release_lock_session(holder_conn_b2, holder_lock_id_b2)
        check("B2: connection A's real lock release reported success", released_b2 is True)
        holder_conn_b2.close()
        holder_conn_b2 = None

        worker_b2.join(timeout=90)
        check("B2: once A released, the previously-blocked request completed (thread finished)", not worker_b2.is_alive())
        check(
            "B2: the FRESH under-lock re-verification rejected B with ReviewDirectoryScanError - "
            "the escape introduced while waiting was caught, never silently accepted",
            isinstance(blocked_result_b2.get("error"), facade.ReviewDirectoryScanError),
            f"got {blocked_result_b2!r}",
        )
        check("B2: the REAL qa_review writer was NEVER invoked", writer_state["calls"] == 0)
        check(
            "B2: the REAL database has EXACTLY ZERO journal rows for this resource_key",
            journal_rows(fx_b2["resource_key"]) == [],
            f"got {journal_rows(fx_b2['resource_key'])!r}",
        )
        check(
            "B2: the canonical artefact is byte-unchanged (still needs_review)",
            sha256_file(fx_b2["canonical_path"]) == fx_b2["expected_hash"],
        )
        check(
            "B2: the forged audit content planted OUTSIDE the case root was never read (byte-identical)",
            sha256_file(outside_root_b2 / "forged.review_audit.json") == outside_spy_before_b2,
        )
    finally:
        if holder_conn_b2 is not None:
            try:
                _mutation_lock.release_lock_session(holder_conn_b2, holder_lock_id_b2)
            except Exception:
                pass
            holder_conn_b2.close()
        if os.path.lexists(audit_dir_b2):
            os.rmdir(audit_dir_b2)
        shutil.rmtree(outside_root_b2, ignore_errors=True)

finally:
    qa_review.apply_review_transition = _REAL_APPLY_REVIEW_TRANSITION
    for _m, _original in _original_cases_dirs:
        _m.CASES_DIR = _original
    qa_validator.BASE_DIR = _original_qa_validator_base_dir
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

check(
    "teardown: qa_review.apply_review_transition is the genuine production function again",
    qa_review.apply_review_transition is _REAL_APPLY_REVIEW_TRANSITION,
)
check(
    "teardown: every redirected CASES_DIR was restored to the real cases root",
    all(Path(os.path.realpath(str(m.CASES_DIR))) == _REAL_CASES_ROOT for m in _cases_dir_holders),
)
check(
    "teardown: qa_validator.BASE_DIR was restored to the real repository root",
    qa_validator.BASE_DIR == _original_qa_validator_base_dir,
)
check("teardown: the temporary case tree was removed", not _TMP_ROOT.exists())

if _real_data_before is not None:
    _real_data_after = snapshot_real_data_tree()
    check(
        "this repository's REAL data/ tree is byte-for-byte UNCHANGED by this entire suite",
        _real_data_before == _real_data_after,
        f"diff_count={len(set(_real_data_before) ^ set(_real_data_after))}",
    )

summarize_and_exit()
