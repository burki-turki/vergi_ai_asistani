# ============================================================
# Row 19C-2c - REAL, END-TO-END PostgreSQL INTEGRATION PROOF for the
# PRODUCTION Row 18C drafting-request mutation path (`drafting_request_
# mutation_facade.apply_drafting_request_mutation()`, wired exactly as
# `ui.services.drafting_request.save_lawyer_input_from_form()` ->
# `ui/main.py`'s `drafting_request_confirm` route wires it).
#
# WHAT IS REAL HERE - mirrors `ui/tests/test_review_mutation_
# integration_postgres.py`'s own discipline exactly, for the THIRD
# production writer family this project's mutation-journal
# infrastructure is connected to:
#   - `ui.services.drafting_request_mutation_facade.
#     apply_drafting_request_mutation()` - the real production facade;
#   - `ui.services.mutation_lock.acquire_case_lock_session()`/
#     `release_lock_session()` - the REAL session-level
#     `pg_advisory_lock`/`pg_advisory_unlock`, never monkeypatched;
#   - `ui.services.mutation_coordinator.run_mutation()` - the real
#     coordinator, against the real `mutation.mutation_journal` table;
#   - `ui.services.mutation_registry.reconcile_and_apply_journal_entry()`
#     and the REAL production merged adapter registry (Layer A + Layer B
#     + Row 18C, via `ui.reconciliation_operator._default_registry_
#     factory()`'s own three-way merge, reproduced here by calling the
#     SAME three `build_production_registry()`/`register_into()`
#     functions it calls);
#   - `ui.services.drafting_request.save_lawyer_input()` - the REAL Row
#     18C writer, running its real freshness re-check, real backup, real
#     atomic write, real post-write schema/consistency validation, real
#     audit record;
#   - `psycopg` - the real production driver. No `psql`-subprocess shim
#     fallback: if `psycopg` is not importable, this file SKIPS loudly.
#
# WHAT IS NOT REAL:
#   1. IAM/authz: `authz_repository=` (via `resolve_repository()`) is an
#      in-memory fake (this file's subject is mutation integrity, not
#      IAM persistence).
#   2. The case tree: REAL, freshly-created SYNTHETIC case directories
#      living directly under the REAL `data/cases/` (Row 18C needs only
#      a `case.json` - no upstream fact/issue/timeline data at all,
#      since every scenario here uses `selected_issue_ids=None`),
#      created and removed per run - deliberately NOT an external
#      CASES_DIR-redirected tempdir (see this file's own case-directory
#      section for why: `to_repo_relative()`-recorded backup paths would
#      silently degrade to a placeholder outside `BASE_DIR`, defeating
#      the overwrite-scenario binding checks). The real repository's own
#      `data/` tree content is NEVER left modified after a run (proven
#      at the end, byte-for-byte, after every synthetic case directory
#      this suite created is removed).
#   3. ONE deliberately-injected fault, at a precisely-named boundary
#      (`_writer_fault`, a pass-through wrapper around the real
#      `drafting_request.save_lawyer_input`), for the reconciliation
#      scenarios that cannot otherwise be reached deterministically.
#
# SETUP (opt-in, never silently skipped): same convention as `test_
# review_mutation_integration_postgres.py` - `VERGI_TEST_PG_DSN` (a bare
# database NAME, applied against `db/migrations/0001..0004`) plus
# ordinary libpq `PGHOST`/`PGPORT`/`PGUSER`.
#
# Run: python -m ui.tests.test_drafting_request_mutation_integration_postgres
# ============================================================

import hashlib
import json
import os
import shutil
import sys
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
        f"--- test_drafting_request_mutation_integration_postgres: {passed} passed, "
        f"{failed} failed, {skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")

if not PG_DB:
    skip(
        "the entire real-PostgreSQL drafting-request mutation integration suite",
        "VERGI_TEST_PG_DSN is not set (no disposable database with migrations "
        "0001+0002+0003+0004 applied is configured for this run). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover - environment-dependent
    skip(
        "the entire real-PostgreSQL drafting-request mutation integration suite",
        f"VERGI_TEST_PG_DSN is set but `import psycopg` failed ({_psycopg_error!r}). "
        "NOT EXECUTED, not a pass",
    )
    summarize_and_exit()


from ui.services import authz as _authz                                  # noqa: E402
from ui.services import mutation_coordinator as mutcoord                 # noqa: E402
from ui.services import mutation_lock as _mutation_lock                  # noqa: E402
from ui.services import mutation_registry as mr                          # noqa: E402
from ui.services import paths as _paths                                  # noqa: E402
from ui.services import mutation_approval_adapters as _approval_adapters  # noqa: E402
from ui.services import review_mutation_adapters as _review_adapters     # noqa: E402
from ui.services import drafting_request_mutation_adapters as _adapters  # noqa: E402
from ui.services import drafting_request_mutation_facade as facade       # noqa: E402
from ui.services import drafting_request as draftreq                     # noqa: E402
from ui.services.common import DraftingRequestStaleInputError            # noqa: E402

from mutation_guard import RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED  # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")

ACTION_FAMILY = facade.ACTION_FAMILY


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


# ----------------------------------------------------------------
# Preflight - same discipline as test_review_mutation_integration_postgres.py.
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
                (_user_id, f"row19c2c-integration-actor-{_user_id}"),
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


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


# ----------------------------------------------------------------
# Merged production registry - Layer A + Layer B + Row 18C, reproducing
# EXACTLY what `ui.reconciliation_operator._default_registry_factory()`
# builds (same three functions, same order).
# ----------------------------------------------------------------

PRODUCTION_REGISTRY = _approval_adapters.build_production_registry()
PRODUCTION_REGISTRY = _review_adapters.register_into(PRODUCTION_REGISTRY)
PRODUCTION_REGISTRY = _adapters.register_into(PRODUCTION_REGISTRY)

check(
    "ROW 19C-3b SLICE 1: the REAL merged production registry covers 10 (Layer A) + 24 (Layer B - "
    "12 review_kinds x 2 channels, web + CLI) + 1 (Row 18C) = 35 routing keys - the number of "
    "LOGICAL Layer B review_kinds is still 12, unchanged; 24 is a channel-separated ADAPTER "
    "ROUTING-KEY count, not a doubling of logical families",
    len(PRODUCTION_REGISTRY.known_action_families()) == 35,
    f"got {sorted(PRODUCTION_REGISTRY.known_action_families())}",
)
check(
    "the REAL merged registry has an adapter registered for this file's own action_family",
    ACTION_FAMILY in PRODUCTION_REGISTRY.known_action_families(),
)


# ----------------------------------------------------------------
# REAL case directories, directly under the REAL `data/cases/` (never a
# CASES_DIR-redirected external tempdir) - a DELIBERATE departure from
# `test_review_mutation_integration_postgres.py`'s own tempdir-redirect
# pattern. Row 18C's writer records `history_backup_path` in its audit
# as a REPO-RELATIVE string (`ui.services.paths.to_repo_relative()`),
# and this integration test's own reconciliation-binding checks (both
# the facade's replay-verification AND the adapter's independent
# `_bindings_match()`) re-resolve that string via `BASE_DIR /
# recorded_backup_path` and verify containment under the REAL
# `history_dir` - `to_repo_relative()` itself is NEVER redirected by a
# CASES_DIR sweep (only `CASES_DIR` module attributes are), so a case
# tree living OUTSIDE `BASE_DIR` would make every backup path degrade to
# `to_repo_relative()`'s own documented "(repo dışında bir konum)"
# placeholder at WRITE time - silently defeating every overwrite-
# scenario binding check this file exists to prove, rather than
# testing production reality. Real case dirs (synthetic case_id,
# `case.json` only - no upstream fact/issue/timeline data, since every
# scenario here uses `selected_issue_ids=None`) are created directly
# under `real_paths.CASES_DIR` and REMOVED in `finally`, mirroring `ui/
# tests/test_drafting_request_mutation_facade_isolated.py`'s own
# already-proven pattern exactly.
# ----------------------------------------------------------------

RUN_TOKEN = uuid.uuid4().hex[:10]
_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))

_original_resolve_case_id = _paths.resolve_case_id
_original_list_case_ids = _paths.list_case_ids
_registered_case_ids = set()
_paths.resolve_case_id = lambda cid: (
    cid if cid in _registered_case_ids else _original_resolve_case_id(cid)
)
_paths.list_case_ids = lambda: _original_list_case_ids() + sorted(_registered_case_ids)

_created_case_dirs = []


def make_case(base_name):
    case_id = f"{base_name}_{RUN_TOKEN}"
    case_dir = _paths.CASES_DIR / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text(json.dumps({"case_id": case_id}), encoding="utf-8")
    _created_case_dirs.append(case_dir)
    _registered_case_ids.add(case_id)
    return {
        "case_id": case_id,
        "resource_key": _mutation_lock.case_resource_key(case_id),
    }


def make_principal_and_repo(case_id, *, user_id=1, session_id=100, assigned=True, role="lawyer"):
    principal = _authz.Principal(user_id=user_id, session_id=session_id, role_version_at_issue=1)
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[session_id] = _authz.SessionRecord(user_id=user_id, current_authz_version=1, disabled=False)
    if assigned:
        repo.assignments[(user_id, case_id)] = _authz.CaseAssignmentRecord(role=role)
    return principal, repo


_EMPTY_LI = {
    "draft_intent_type": None, "appeal_level": None, "selected_issue_ids": None,
    "selected_source_ids": dict(draftreq._EMPTY_SELECTED_SOURCE_IDS),
    "request_input": None, "lawyer_provided_text": None,
}


def make_wrapper(case_id, text, saved_at="2026-01-01T00:00:00+00:00"):
    li = dict(_EMPTY_LI)
    li["lawyer_provided_text"] = text
    normalized = draftreq.normalize_lawyer_input(li)
    return {
        "schema_version": 1, "case_id": case_id, "saved_at": saved_at,
        "source": "local_lawyer_ui_submission",
        "lawyer_input_hash": draftreq.compute_lawyer_input_hash(normalized),
        "lawyer_input": normalized,
    }


def confirm(fixture, principal, repo, wrapper, expected_hash):
    resolved_case_id = facade.authorize_outer(principal, fixture["case_id"], repo)
    return facade.apply_drafting_request_mutation(
        resolved_case_id, wrapper, expected_hash,
        principal=principal, repository=repo, conn_factory=pg_connect,
    )


_REAL_SAVE_LAWYER_INPUT = draftreq.save_lawyer_input
writer_state = {"calls": 0, "fault": None}


def _writer_fault(
    case_id, wrapper, expected_current_input_hash,
    *, current_path_override=None, audit_dir_override=None, history_dir_override=None,
    mutation_idempotency_key=None, mutation_resource_key=None, mutation_actor_ref=None,
):
    writer_state["calls"] += 1
    fault = writer_state["fault"]
    if fault == "before":
        raise RuntimeError("INJECTED FAULT (before): simulating a failure before the real writer ran at all")
    result = _REAL_SAVE_LAWYER_INPUT(
        case_id, wrapper, expected_current_input_hash,
        current_path_override=current_path_override, audit_dir_override=audit_dir_override,
        history_dir_override=history_dir_override,
        mutation_idempotency_key=mutation_idempotency_key,
        mutation_resource_key=mutation_resource_key, mutation_actor_ref=mutation_actor_ref,
    )
    if fault == "after":
        raise RuntimeError(
            "INJECTED FAULT (after): the REAL drafting_request.save_lawyer_input() completed in full "
            "(real atomic write + real audit record), and the call then failed to return cleanly"
        )
    return result


draftreq.save_lawyer_input = _writer_fault


def snapshot_real_data_tree():
    """A byte-level manifest of this repository's real `data/` tree -
    used to prove at the end that no scenario ever touched it."""
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
    # SCENARIO 1 - FRESH FIRST-SAVE, FULL PRODUCTION STACK.
    # ============================================================

    fx1 = make_case("case_pgint_fresh")
    principal1, repo1 = make_principal_and_repo(fx1["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    wrapper1 = make_wrapper(fx1["case_id"], "scenario 1 - fresh first-save")
    result1 = confirm(fx1, principal1, repo1, wrapper1, draftreq.NO_EXISTING_INPUT_SENTINEL)

    check("scenario 1: replayed=False", result1.replayed is False)
    check("scenario 1: the REAL writer was invoked exactly once", writer_state["calls"] == 1)
    check("scenario 1: history_backup_path is None (first save)", result1.history_backup_path is None)
    current_path1 = draftreq.get_current_input_path(fx1["case_id"])
    check(
        "scenario 1: the REAL current file now exists with the submitted content",
        json.loads(current_path1.read_text(encoding="utf-8"))["lawyer_input"]["lawyer_provided_text"]
        == "scenario 1 - fresh first-save",
    )
    rows1 = journal_rows(fx1["resource_key"])
    check(
        "scenario 1: exactly one REAL journal row exists in the database, state='completed'",
        len(rows1) == 1 and rows1[0]["state"] == "completed",
        f"rows={rows1}",
    )
    check("scenario 1: the journal row's action_family is drafting_request.save", rows1[0]["action_family"] == ACTION_FAMILY)
    check(
        "scenario 1: the journal row's observed_post_hash equals the REAL current file's own hash",
        rows1[0]["observed_post_hash"] == sha256_file(current_path1),
    )
    check(
        "scenario 1: 0004's reconciliation-provenance columns are NULL for a directly-completed row",
        rows1[0]["reconciled_by_actor_type"] is None and rows1[0]["reconciled_by_actor_ref"] is None,
    )

    # ============================================================
    # SCENARIO 2 - SAFE REPLAY (double-click/network retry: SAME
    # identity, SAME normalized content).
    # ============================================================

    writer_state["calls"] = 0
    wrapper1_retry = make_wrapper(fx1["case_id"], "scenario 1 - fresh first-save")
    result2 = confirm(fx1, principal1, repo1, wrapper1_retry, draftreq.NO_EXISTING_INPUT_SENTINEL)
    check("scenario 2: replayed=True", result2.replayed is True)
    check("scenario 2: the REAL writer was NOT re-invoked", writer_state["calls"] == 0)
    check("scenario 2: the SAME real journal row was reused", result2.journal_id == result1.journal_id)
    check("scenario 2: no SECOND journal row was created in the real database", len(journal_rows(fx1["resource_key"])) == 1)
    check(
        "scenario 2: the replay is deterministic - reconstructed wrapper matches the real file",
        result2.wrapper.get("lawyer_input_hash") == wrapper1["lawyer_input_hash"],
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
    wrapper3 = make_wrapper(fx3["case_id"], "scenario 3 - lock serialization")

    def run_blocked_confirm():
        try:
            blocked_result["result"] = confirm(fx3, principal3, repo3, wrapper3, draftreq.NO_EXISTING_INPUT_SENTINEL)
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
    # SCENARIO 4 - IDENTITY/FINGERPRINT CONFLICT: same identity (same
    # actor/resource/target/pre_revision), DIFFERENT content ->
    # IdempotencyConflictError, ZERO new journal rows, ZERO writer
    # invocation for this attempt.
    # ============================================================

    fx4 = make_case("case_pgint_fpconflict")
    principal4, repo4 = make_principal_and_repo(fx4["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    wrapper4a = make_wrapper(fx4["case_id"], "the FIRST content")
    confirm(fx4, principal4, repo4, wrapper4a, draftreq.NO_EXISTING_INPUT_SENTINEL)
    check("scenario 4 preflight: the first confirm really completed", journal_rows(fx4["resource_key"])[0]["state"] == "completed")
    writer_state["calls"] = 0

    wrapper4b = make_wrapper(fx4["case_id"], "a COMPLETELY different content")
    expect_raises(
        mutcoord.IdempotencyConflictError,
        # SAME identity (same actor/resource/target/pre_revision -
        # deliberately still the ORIGINAL pre-mutation sentinel, so
        # identity matches the ALREADY-COMPLETED row exactly), DIFFERENT
        # content (-> different secondary_input_hash -> different
        # fingerprint) - exactly the fingerprint-only conflict this
        # scenario proves.
        lambda: confirm(fx4, principal4, repo4, wrapper4b, draftreq.NO_EXISTING_INPUT_SENTINEL),
        "scenario 4: same identity + different content -> IdempotencyConflictError (real database)",
    )
    check("scenario 4: the writer was NOT invoked for the conflicting attempt", writer_state["calls"] == 0)
    check("scenario 4: still exactly ONE real journal row for this resource", len(journal_rows(fx4["resource_key"])) == 1)

    # ============================================================
    # SCENARIO 5a - WRITER CRASH ON FIRST-SAVE (post-writer fault) ->
    # 'reconciliation_required'.
    # ============================================================

    fx5a = make_case("case_pgint_reconcile_first")
    principal5a, repo5a = make_principal_and_repo(fx5a["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = "after"

    wrapper5a = make_wrapper(fx5a["case_id"], "scenario 5a - first-save crash")
    try:
        expect_raises(
            RuntimeError,
            lambda: confirm(fx5a, principal5a, repo5a, wrapper5a, draftreq.NO_EXISTING_INPUT_SENTINEL),
            "scenario 5a: the post-writer fault propagates out of the facade unchanged",
        )
    finally:
        writer_state["fault"] = None

    rows5a = journal_rows(fx5a["resource_key"])
    check(
        "scenario 5a: the row is 'reconciliation_required' even though the real writer DID succeed",
        len(rows5a) == 1 and rows5a[0]["state"] == "reconciliation_required",
        f"rows={[(r['id'], r['state']) for r in rows5a]}",
    )
    current_path5a = draftreq.get_current_input_path(fx5a["case_id"])
    check(
        "scenario 5a: the REAL current file really was written by the real writer (first-save)",
        current_path5a.exists()
        and json.loads(current_path5a.read_text(encoding="utf-8"))["lawyer_input"]["lawyer_provided_text"]
        == "scenario 5a - first-save crash",
    )

    # ============================================================
    # SCENARIO 5b - WRITER CRASH ON OVERWRITE (post-writer fault) ->
    # 'reconciliation_required'.
    # ============================================================

    fx5b = make_case("case_pgint_reconcile_overwrite")
    principal5b, repo5b = make_principal_and_repo(fx5b["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    wrapper5b_first = make_wrapper(fx5b["case_id"], "scenario 5b - initial save")
    confirm(fx5b, principal5b, repo5b, wrapper5b_first, draftreq.NO_EXISTING_INPUT_SENTINEL)
    token_after_5b_first = draftreq.compute_current_freshness_token(fx5b["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = "after"

    wrapper5b_second = make_wrapper(fx5b["case_id"], "scenario 5b - overwrite crash")
    try:
        expect_raises(
            RuntimeError,
            lambda: confirm(fx5b, principal5b, repo5b, wrapper5b_second, token_after_5b_first),
            "scenario 5b: the post-writer fault propagates out of the facade unchanged (overwrite)",
        )
    finally:
        writer_state["fault"] = None

    rows5b = journal_rows(fx5b["resource_key"])
    check(
        "scenario 5b: exactly two real journal rows (first-save completed + overwrite reconciliation_required)",
        len(rows5b) == 2 and rows5b[0]["state"] == "completed" and rows5b[1]["state"] == "reconciliation_required",
        f"rows={[(r['id'], r['state']) for r in rows5b]}",
    )
    current_path5b = draftreq.get_current_input_path(fx5b["case_id"])
    check(
        "scenario 5b: the REAL current file really was overwritten by the real writer",
        json.loads(current_path5b.read_text(encoding="utf-8"))["lawyer_input"]["lawyer_provided_text"]
        == "scenario 5b - overwrite crash",
    )
    check(
        "scenario 5b: a REAL history backup was really created for the overwrite",
        len(list(draftreq.get_input_history_dir(fx5b["case_id"]).glob("*.json"))) == 1,
    )

    # ============================================================
    # SCENARIO 6a - RECONCILIATION of 5a (first-save-origin stuck row)
    # via the REAL merged production adapter registry, WITH provenance.
    # ============================================================

    recon_conn_a = pg_connect()
    try:
        dry_run6a = mr.inspect_reconciliation(recon_conn_a, rows5a[0]["id"], PRODUCTION_REGISTRY)
        check(
            "scenario 6a: the DRY-RUN inspection (REAL adapter, real evidence) resolves to 'completed' "
            "via post-state verification",
            dry_run6a.new_state == "completed" and dry_run6a.resolution_code == RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
            f"dry_run={dry_run6a!r}",
        )
        check(
            "scenario 6a: the dry run issued ZERO UPDATEs (the row is still unresolved)",
            journal_rows(fx5a["resource_key"])[0]["state"] == "reconciliation_required",
        )
        applied6a = mr.reconcile_and_apply_journal_entry(
            recon_conn_a, rows5a[0]["id"], PRODUCTION_REGISTRY,
            resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c2c-integration-test",
        )
        check("scenario 6a: the REAL --apply reconciliation resolved the row to 'completed'", applied6a.new_state == "completed")
    finally:
        recon_conn_a.close()

    rows6a_after = journal_rows(fx5a["resource_key"])
    check(
        "scenario 6a: the real database row is now 'completed' with the RECONCILED resolution_code",
        rows6a_after[0]["state"] == "completed"
        and rows6a_after[0]["resolution_code"] == RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
        f"row={rows6a_after[0]!r}",
    )
    check(
        "scenario 6a: 0004's reconciliation provenance really was recorded on the resolved row",
        rows6a_after[0]["reconciled_by_actor_type"] == "cli_service"
        and rows6a_after[0]["reconciled_by_actor_ref"] == "row19c2c-integration-test",
    )
    check(
        "scenario 6a: the reconciled observed_post_hash equals the REAL current file's own current hash",
        rows6a_after[0]["observed_post_hash"] == sha256_file(current_path5a),
    )
    check("scenario 6a: reconciliation did NOT re-invoke the writer (evidence-gathering is read-only)", writer_state["calls"] == 1)

    # ============================================================
    # SCENARIO 6b - RECONCILIATION of 5b (overwrite-origin stuck row).
    # ============================================================

    writer_state["calls"] = 1  # scenario 5b's own writer call count baseline
    recon_conn_b = pg_connect()
    try:
        dry_run6b = mr.inspect_reconciliation(recon_conn_b, rows5b[1]["id"], PRODUCTION_REGISTRY)
        check(
            "scenario 6b: the DRY-RUN inspection (overwrite-origin row) resolves to 'completed'",
            dry_run6b.new_state == "completed" and dry_run6b.resolution_code == RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
            f"dry_run={dry_run6b!r}",
        )
        applied6b = mr.reconcile_and_apply_journal_entry(
            recon_conn_b, rows5b[1]["id"], PRODUCTION_REGISTRY,
            resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c2c-integration-test",
        )
        check("scenario 6b: the REAL --apply reconciliation resolved the overwrite-origin row to 'completed'", applied6b.new_state == "completed")
    finally:
        recon_conn_b.close()

    rows6b_after = journal_rows(fx5b["resource_key"])
    check(
        "scenario 6b: BOTH real database rows for this resource are now terminal ('completed')",
        all(r["state"] == "completed" for r in rows6b_after),
        f"rows={[(r['id'], r['state']) for r in rows6b_after]}",
    )
    check(
        "scenario 6b: the resource is no longer gated - both rows reached a terminal state",
        all(r["state"] not in ("prepared", "executing", "reconciliation_required") for r in rows6b_after),
    )

finally:
    draftreq.save_lawyer_input = _REAL_SAVE_LAWYER_INPUT
    _paths.resolve_case_id = _original_resolve_case_id
    _paths.list_case_ids = _original_list_case_ids
    for _case_dir in _created_case_dirs:
        if _case_dir.exists():
            shutil.rmtree(_case_dir)

check(
    "teardown: drafting_request.save_lawyer_input is the genuine production function again",
    draftreq.save_lawyer_input is _REAL_SAVE_LAWYER_INPUT,
)
check(
    "teardown: paths.resolve_case_id/list_case_ids restored to the real production functions",
    _paths.resolve_case_id is _original_resolve_case_id and _paths.list_case_ids is _original_list_case_ids,
)
check(
    "teardown: every synthetic case directory this suite created was removed",
    all(not _case_dir.exists() for _case_dir in _created_case_dirs),
)

if _real_data_before is not None:
    _real_data_after = snapshot_real_data_tree()
    check(
        "this repository's REAL data/ tree is byte-for-byte UNCHANGED by this entire suite",
        _real_data_before == _real_data_after,
        f"diff_count={len(set(_real_data_before) ^ set(_real_data_after))}",
    )

summarize_and_exit()
