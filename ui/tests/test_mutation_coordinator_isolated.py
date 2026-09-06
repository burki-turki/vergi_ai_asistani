# ============================================================
# Row 19C-1 - isolated (fake-connection) tests for
# ui/services/mutation_coordinator.py's `run_mutation()` and
# `is_stale_executing()`.
#
# This file proves the COORDINATOR'S OWN ORDERING/GATING/CLASSIFICATION
# LOGIC against an in-memory fake `mutation.mutation_journal` table
# satisfying the same minimal DB-API-2.0 shape psycopg would - no
# psycopg, no real PostgreSQL needed. It does NOT prove the real SQL
# text is valid PostgreSQL (that is proven separately, against a real,
# disposable PostgreSQL instance, in ui/tests/test_mutation_journal_postgres.py
# and ui/tests/test_iam_migrations_isolated.py) nor does it invoke
# `mutation_lock.py` at all (`run_mutation()` itself never acquires/
# releases the lock - that is the CALLER's job, per its own docstring -
# so there is nothing lock-related to fake here).
#
# Row 19C-1 TARGETED CONTRACT REMEDIATION: the fake models
# 0003_mutation_journal.sql's UNCONDITIONAL `UNIQUE(idempotency_key)`
# table constraint - unique across the table's ENTIRE history, in
# EVERY state including `failed`, never a partial index scoped to
# "live" rows only. An earlier draft of both this migration and this
# test file modeled a PARTIAL unique index instead (unique only among
# non-`failed` rows), which let a caller retry after a `failed` attempt
# by opening a brand-new row under the SAME idempotency_key - that
# design was REJECTED by the approved contract: `idempotency_key`
# identifies one permanent operation slot whose outcome, `failed`
# included, is fixed forever once a row exists. A retry now requires a
# genuinely NEW `MutationIntent` (e.g. a freshly re-read pre_hash) that
# hashes to a DIFFERENT idempotency_key - see
# `mc.PriorAttemptFailedError`'s own docstring and section 5 below.
#
# Run: python -m ui.tests.test_mutation_coordinator_isolated
# ============================================================

import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
SRC_DIR = REPO_ROOT / "src"
for p in (REPO_ROOT, SRC_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from mutation_guard import MutationIntent  # noqa: E402
from ui.services import mutation_coordinator as mc  # noqa: E402

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
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")


# ----------------------------------------------------------------
# Fake mutation.mutation_journal - an in-memory list of dict rows,
# with the SAME unconditional-uniqueness rule 0003 enforces at the DB
# level (UNIQUE(idempotency_key), across ALL states, no exceptions),
# and the same fixed SQL-shape dispatch pattern this project's other
# isolated test files use (normalize whitespace, then match by
# statement prefix).
# ----------------------------------------------------------------

class FakeIntegrityError(Exception):
    """Stands in for psycopg.errors.UniqueViolation - run_mutation()
    itself never catches this (a real duplicate-row condition should
    never arise given `_idempotency_lookup`'s own unconditional,
    all-state check running before any INSERT is attempted; if it
    somehow did - e.g. a genuine concurrent race between two callers
    that both passed the lookup before either inserted - letting it
    propagate uncaught is the correct, fail-closed behavior, not a bug
    to paper over here)."""


class FakeJournalCursor:
    def __init__(self, table, calls):
        self._table = table
        self._calls = calls
        self._last_result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._calls.append(normalized.split()[0])

        if normalized.startswith("SELECT 1 FROM mutation.mutation_journal"):
            (resource_key,) = params
            hit = any(
                r["resource_key"] == resource_key
                and r["state"] in ("prepared", "executing", "reconciliation_required")
                for r in self._table
            )
            self._last_result = (1,) if hit else None

        elif normalized.startswith("SELECT id, state, request_fingerprint, observed_post_hash"):
            # Unconditional, ALL-state lookup - never filters by state.
            # Since INSERT (below) also enforces unconditional
            # uniqueness, there is NEVER more than one match here.
            (idempotency_key,) = params
            matches = [r for r in self._table if r["idempotency_key"] == idempotency_key]
            if not matches:
                self._last_result = None
            else:
                r = matches[0]
                self._last_result = (
                    r["id"], r["state"], r["request_fingerprint"], r["observed_post_hash"],
                    r["failure_code"], r["resolution_code"],
                )

        elif normalized.startswith("INSERT INTO mutation.mutation_journal"):
            (
                resource_key, action_family, actor_user_id, actor_label, target_ref, target_state,
                pre_hash, pre_revision, idempotency_key, request_fingerprint,
            ) = params
            # UNCONDITIONAL uniqueness - ANY existing row with this
            # idempotency_key, in ANY state (failed included), conflicts.
            conflict = any(r["idempotency_key"] == idempotency_key for r in self._table)
            if conflict:
                raise FakeIntegrityError(
                    f"duplicate key value violates unique constraint "
                    f"\"mutation_journal_idempotency_key_uniq\": idempotency_key={idempotency_key!r}"
                )
            new_id = len(self._table) + 1
            self._table.append({
                "id": new_id,
                "resource_key": resource_key,
                "action_family": action_family,
                "actor_user_id": actor_user_id,
                "actor_label": actor_label,
                "target_ref": target_ref,
                "target_state": target_state,
                "pre_hash": pre_hash,
                "pre_revision": pre_revision,
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "state": "prepared",
                "failure_code": None,
                "resolution_code": None,
                "executing_at": None,
                "resolved_at": None,
                "observed_post_hash": None,
            })
            self._last_result = (new_id,)

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'executing'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "executing"
            self._row(journal_id)["executing_at"] = "FAKE_TIMESTAMP"

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'completed'"):
            observed_post_hash, journal_id = params
            row = self._row(journal_id)
            row["state"] = "completed"
            row["observed_post_hash"] = observed_post_hash
            row["resolved_at"] = "FAKE_TIMESTAMP"

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'reconciliation_required'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "reconciliation_required"

        else:
            # Row 19C-1 TARGETED CONTRACT REMEDIATION: there is
            # deliberately NO "UPDATE ... SET state = 'failed'" branch
            # here any more - run_mutation() itself never writes
            # `failed` directly (authz/precondition denials now create
            # NO journal row at all, and a writer exception always
            # becomes `reconciliation_required`, never `failed`). If
            # this module regresses and starts emitting that SQL again,
            # this is the trip-wire that catches it.
            raise AssertionError(f"unexpected SQL: {sql}")

    def _row(self, journal_id):
        for r in self._table:
            if r["id"] == journal_id:
                return r
        raise AssertionError(f"no fake journal row with id={journal_id}")

    def fetchone(self):
        return self._last_result


class FakeJournalConn:
    def __init__(self, table=None):
        self.table = table if table is not None else []
        self.calls = []

    def cursor(self):
        return FakeJournalCursor(self.table, self.calls)


def make_intent(**overrides):
    fields = dict(
        actor_type="iam_user",
        actor_ref="42",
        resource_key="case:case_0001",
        action_family="fam.test_action",
        target_ref="target_a",
    )
    fields.update(overrides)
    return MutationIntent(**fields)


def make_callbacks(authz_calls=None, precondition_calls=None, writer_calls=None,
                    authz_raises=None, precondition_raises=None, writer_raises=None,
                    writer_result=None):
    authz_calls = authz_calls if authz_calls is not None else []
    precondition_calls = precondition_calls if precondition_calls is not None else []
    writer_calls = writer_calls if writer_calls is not None else []

    def authz():
        authz_calls.append(True)
        if authz_raises is not None:
            raise authz_raises

    def precondition():
        precondition_calls.append(True)
        if precondition_raises is not None:
            raise precondition_raises

    def writer():
        writer_calls.append(True)
        if writer_raises is not None:
            raise writer_raises
        return writer_result if writer_result is not None else mc.WriterResult(observed_post_hash="posthash", result="ok")

    return authz, precondition, writer, authz_calls, precondition_calls, writer_calls


def make_failed_row(*, row_id, resource_key, idempotency_key, request_fingerprint,
                     failure_code="precondition_failed", resolution_code=None):
    """Directly seeds a TERMINAL `failed` journal row into a fake
    table, standing in for a row a PRIOR (already-concluded) attempt
    left behind - `run_mutation()` itself never writes `failed`
    directly any more (see the dispatch trip-wire above), so tests
    that need to exercise the "a failed row already exists" branch
    must seed one this way rather than trying to produce it by calling
    `run_mutation()`."""
    return {
        "id": row_id, "resource_key": resource_key, "action_family": "fam.test_action",
        "actor_user_id": 1, "actor_label": "1", "target_ref": "t", "target_state": None,
        "pre_hash": None, "pre_revision": None, "idempotency_key": idempotency_key,
        "request_fingerprint": request_fingerprint, "state": "failed",
        "failure_code": failure_code, "resolution_code": resolution_code,
        "executing_at": "x", "resolved_at": "FAKE_TIMESTAMP", "observed_post_hash": None,
    }


# ----------------------------------------------------------------
# 1) Happy path - full ordering: gate-check, all-state idempotency
#    lookup, authz, precondition, insert-prepared, executing, writer,
#    completed.
# ----------------------------------------------------------------

conn = FakeJournalConn()
intent = make_intent()
authz, precondition, writer, authz_calls, precondition_calls, writer_calls = make_callbacks()

outcome = mc.run_mutation(
    conn, intent, actor_user_id=42,
    authz_callback=authz, precondition_callback=precondition, writer_callback=writer,
)

check("happy path returns state='completed'", outcome.state == "completed")
check("happy path returns replayed=False (writer really ran)", outcome.replayed is False)
check("happy path returns the writer's own observed_post_hash", outcome.observed_post_hash == "posthash")
check("happy path returns the writer's own result payload", outcome.result == "ok")
check("happy path called authz exactly once", authz_calls == [True])
check("happy path called precondition exactly once", precondition_calls == [True])
check("happy path called writer exactly once", writer_calls == [True])
check("happy path's journal row ends in state='completed'", conn.table[0]["state"] == "completed")
check("happy path's journal row got a prepared->executing->completed durable trail (resolved_at set)", conn.table[0]["resolved_at"] == "FAKE_TIMESTAMP")

call_order = [c for c in conn.calls if c in ("SELECT", "INSERT", "UPDATE")]
check(
    "SQL call order is gate-check, all-state idempotency-lookup, insert-prepared, then updates (executing, completed)",
    call_order == ["SELECT", "SELECT", "INSERT", "UPDATE", "UPDATE"],
    f"got {call_order!r}",
)

# ----------------------------------------------------------------
# 2) ResourceGatedError - an unresolved row already exists for this
#    resource_key. Authz/precondition/writer must NEVER be invoked,
#    and NO new row may be inserted.
# ----------------------------------------------------------------

gated_conn = FakeJournalConn(table=[{
    "id": 1, "resource_key": "case:case_0002", "action_family": "fam.other",
    "actor_user_id": 1, "actor_label": "1", "target_ref": "t", "target_state": None,
    "pre_hash": None, "pre_revision": None, "idempotency_key": "existing_unresolved_key",
    "request_fingerprint": "fp", "state": "executing", "failure_code": None,
    "resolution_code": None, "executing_at": "x", "resolved_at": None, "observed_post_hash": None,
}])
authz2, precondition2, writer2, authz_calls2, precondition_calls2, writer_calls2 = make_callbacks()
expect_raises(
    mc.ResourceGatedError,
    lambda: mc.run_mutation(
        gated_conn, make_intent(resource_key="case:case_0002", target_ref="unrelated_target"),
        actor_user_id=1, authz_callback=authz2, precondition_callback=precondition2, writer_callback=writer2,
    ),
    "an unresolved journal entry for the resource gates a brand-new, UNRELATED mutation attempt",
)
check("ResourceGatedError path never called authz", authz_calls2 == [])
check("ResourceGatedError path never called precondition", precondition_calls2 == [])
check("ResourceGatedError path never called the writer", writer_calls2 == [])
check("ResourceGatedError path inserted NO new journal row", len(gated_conn.table) == 1)

# ----------------------------------------------------------------
# 3) IdempotencyConflictError - an existing row exists for this
#    idempotency_key with a DIFFERENT request_fingerprint. This section
#    proves it against a `completed` existing row; section 6 below
#    proves the same rule against a `failed` existing row (state is
#    irrelevant to this check under the unconditional contract).
# ----------------------------------------------------------------

conflict_conn = FakeJournalConn()
intent_a = make_intent(resource_key="case:case_0003", target_ref="t3", target_state="confirmed")
authz3a, precondition3a, writer3a, *_ = make_callbacks()
outcome_a = mc.run_mutation(
    conflict_conn, intent_a, actor_user_id=1,
    authz_callback=authz3a, precondition_callback=precondition3a, writer_callback=writer3a,
)
check("setup: first request on case_0003 completed", outcome_a.state == "completed")

intent_b = make_intent(resource_key="case:case_0003", target_ref="t3", target_state="rejected")  # same slot, different outcome
authz3b, precondition3b, writer3b, authz_calls3b, precondition_calls3b, writer_calls3b = make_callbacks()
expect_raises(
    mc.IdempotencyConflictError,
    lambda: mc.run_mutation(
        conflict_conn, intent_b, actor_user_id=1,
        authz_callback=authz3b, precondition_callback=precondition3b, writer_callback=writer3b,
    ),
    "same idempotency slot, different target_state (different request_fingerprint), against a COMPLETED row, fails closed",
)
check("IdempotencyConflictError (vs completed) path never called authz", authz_calls3b == [])
check("IdempotencyConflictError (vs completed) path never called precondition", precondition_calls3b == [])
check("IdempotencyConflictError (vs completed) path never called the writer", writer_calls3b == [])
check("IdempotencyConflictError (vs completed) path inserted NO new journal row", len(conflict_conn.table) == 1)

# ----------------------------------------------------------------
# 4) Safe replay - existing row, same idempotency_key AND same
#    request_fingerprint, already `completed`. Writer must NOT be
#    re-invoked; the stored outcome is returned as-is.
# ----------------------------------------------------------------

replay_conn = FakeJournalConn()
intent_c = make_intent(resource_key="case:case_0004", target_ref="t4")
authz4a, precondition4a, writer4a, *_ = make_callbacks(writer_result=mc.WriterResult(observed_post_hash="hash_v1", result="first_result"))
first_outcome = mc.run_mutation(
    replay_conn, intent_c, actor_user_id=7,
    authz_callback=authz4a, precondition_callback=precondition4a, writer_callback=writer4a,
)
check("setup: first request on case_0004 completed with hash_v1", first_outcome.observed_post_hash == "hash_v1")

authz4b, precondition4b, writer4b, authz_calls4b, precondition_calls4b, writer_calls4b = make_callbacks(
    writer_result=mc.WriterResult(observed_post_hash="hash_v2_should_never_be_seen", result="second_result"),
)
replay_outcome = mc.run_mutation(
    replay_conn, intent_c, actor_user_id=7,  # byte-identical intent -> identical idempotency_key AND fingerprint
    authz_callback=authz4b, precondition_callback=precondition4b, writer_callback=writer4b,
)
check("safe replay returns replayed=True", replay_outcome.replayed is True)
check("safe replay returns state='completed' without re-running anything", replay_outcome.state == "completed")
check("safe replay returns the ORIGINAL observed_post_hash, not a freshly recomputed one", replay_outcome.observed_post_hash == "hash_v1")
check("safe replay never invoked authz a second time", authz_calls4b == [])
check("safe replay never invoked precondition a second time", precondition_calls4b == [])
check("safe replay NEVER RE-INVOKED THE WRITER", writer_calls4b == [])
check("safe replay inserted NO new journal row", len(replay_conn.table) == 1)

# ----------------------------------------------------------------
# 5) PriorAttemptFailedError - a TERMINAL `failed` row already exists
#    for this EXACT idempotency_key with the SAME request_fingerprint.
#    Row 19C-1 TARGETED CONTRACT REMEDIATION: this is now a PERMANENT,
#    deterministic outcome - NO new journal row is ever created, and
#    authz/precondition/writer are NEVER invoked. To genuinely seed a
#    `failed` row under an intent's OWN real idempotency_key (rather
#    than a made-up literal), we compute it the same way
#    run_mutation() does, via the public helpers.
# ----------------------------------------------------------------

from mutation_guard import compute_idempotency_key, compute_request_fingerprint  # noqa: E402

intent_d = make_intent(resource_key="case:case_0005", target_ref="t5")
real_key_d = compute_idempotency_key(intent_d)
real_fp_d = compute_request_fingerprint(intent_d)

failed_retry_conn = FakeJournalConn(table=[
    make_failed_row(
        row_id=1, resource_key="case:case_0005", idempotency_key=real_key_d,
        request_fingerprint=real_fp_d, failure_code="precondition_failed", resolution_code=None,
    ),
])
authz5, precondition5, writer5, authz_calls5, precondition_calls5, writer_calls5 = make_callbacks()
expect_raises(
    mc.PriorAttemptFailedError,
    lambda: mc.run_mutation(
        failed_retry_conn, intent_d, actor_user_id=3,  # SAME intent -> SAME key AND SAME fingerprint as the seeded failed row
        authz_callback=authz5, precondition_callback=precondition5, writer_callback=writer5,
    ),
    "a prior TERMINAL failed row for the identical idempotency slot is deterministically re-reported, never retried",
)
check("PriorAttemptFailedError path never called authz", authz_calls5 == [])
check("PriorAttemptFailedError path never called precondition", precondition_calls5 == [])
check("PriorAttemptFailedError path NEVER called the writer", writer_calls5 == [])
check("PriorAttemptFailedError path inserted NO new journal row (still exactly 1 row)", len(failed_retry_conn.table) == 1)
check("the pre-existing failed row is completely untouched", failed_retry_conn.table[0]["state"] == "failed")


def _get_prior_attempt_error():
    try:
        mc.run_mutation(
            failed_retry_conn, intent_d, actor_user_id=3,
            authz_callback=authz5, precondition_callback=precondition5, writer_callback=writer5,
        )
    except mc.PriorAttemptFailedError as error:
        return error
    raise AssertionError("expected PriorAttemptFailedError")


prior_error = _get_prior_attempt_error()
check("PriorAttemptFailedError carries the ORIGINAL row's journal_id", prior_error.journal_id == 1)
check("PriorAttemptFailedError carries the ORIGINAL row's failure_code", prior_error.failure_code == "precondition_failed")
check("PriorAttemptFailedError carries the ORIGINAL row's resolution_code (None here)", prior_error.resolution_code is None)

# ----------------------------------------------------------------
# 6) A prior `failed` row for the same idempotency_key but a
#    DIFFERENT request_fingerprint fails closed as IdempotencyConflictError
#    (checked BEFORE the failed-state branch) - never PriorAttemptFailedError,
#    since the two requests do not even agree on what outcome they want.
# ----------------------------------------------------------------

intent_e_first = make_intent(resource_key="case:case_0006", target_ref="t6", target_state="confirmed")
real_key_e = compute_idempotency_key(intent_e_first)  # target_state excluded -> identity is stable across confirmed/rejected
real_fp_e_confirmed = compute_request_fingerprint(intent_e_first)

failed_diff_fp_conn = FakeJournalConn(table=[
    make_failed_row(
        row_id=1, resource_key="case:case_0006", idempotency_key=real_key_e,
        request_fingerprint=real_fp_e_confirmed, failure_code="authz_denied", resolution_code=None,
    ),
])
intent_e_second = make_intent(resource_key="case:case_0006", target_ref="t6", target_state="rejected")  # same slot, different fingerprint
check(
    "sanity: intent_e_first and intent_e_second share an idempotency_key but differ in fingerprint",
    compute_idempotency_key(intent_e_second) == real_key_e
    and compute_request_fingerprint(intent_e_second) != real_fp_e_confirmed,
)
authz6, precondition6, writer6, authz_calls6, precondition_calls6, writer_calls6 = make_callbacks()
expect_raises(
    mc.IdempotencyConflictError,
    lambda: mc.run_mutation(
        failed_diff_fp_conn, intent_e_second, actor_user_id=1,
        authz_callback=authz6, precondition_callback=precondition6, writer_callback=writer6,
    ),
    "failed record + same idempotency_key + DIFFERENT fingerprint -> IdempotencyConflictError, not PriorAttemptFailedError",
)
check("IdempotencyConflictError (vs failed row) path never called authz", authz_calls6 == [])
check("IdempotencyConflictError (vs failed row) path never called precondition", precondition_calls6 == [])
check("IdempotencyConflictError (vs failed row) path never called the writer", writer_calls6 == [])
check("IdempotencyConflictError (vs failed row) path inserted NO new journal row", len(failed_diff_fp_conn.table) == 1)

# ----------------------------------------------------------------
# 7) Unconditional uniqueness at the INSERT layer itself: even with no
#    prior lookup involved, attempting to insert a SECOND row sharing
#    an idempotency_key with an EXISTING `failed` row must be rejected
#    (this is the fake's model of 0003's plain UNIQUE(idempotency_key)
#    table constraint - the authoritative real-database proof of this
#    lives in ui/tests/test_iam_migrations_isolated.py and/or
#    ui/tests/test_mutation_journal_postgres.py, run against real
#    PostgreSQL; this is a fast, in-memory corroboration of the same
#    rule at the dispatch-simulation level).
# ----------------------------------------------------------------

insert_race_conn = FakeJournalConn(table=[
    make_failed_row(row_id=1, resource_key="case:case_0007", idempotency_key="shared_key_0007", request_fingerprint="fp7"),
])
try:
    mc._insert_prepared(
        insert_race_conn, make_intent(resource_key="case:case_0007", target_ref="t7"),
        actor_user_id=1, idempotency_key="shared_key_0007", request_fingerprint="fp7",
    )
    check("a second INSERT sharing an idempotency_key with an existing FAILED row is rejected", False, "no exception raised")
except FakeIntegrityError:
    check("a second INSERT sharing an idempotency_key with an existing FAILED row is rejected", True)
check("the rejected INSERT left the table with exactly the original 1 row", len(insert_race_conn.table) == 1)

# ----------------------------------------------------------------
# 8) authz_callback raises -> NO journal row is created at all (authz
#    denial is not a mutation-journal concern under the corrected
#    ordering); precondition/writer never run; caller's own exception
#    type/instance propagates unchanged.
# ----------------------------------------------------------------

authz_fail_conn = FakeJournalConn()
intent_f = make_intent(resource_key="case:case_0008", target_ref="t8")


class MyAuthzError(Exception):
    pass


_sentinel_authz_error = MyAuthzError("no you don't")
authz8, precondition8, writer8, authz_calls8, precondition_calls8, writer_calls8 = make_callbacks(authz_raises=_sentinel_authz_error)
try:
    mc.run_mutation(
        authz_fail_conn, intent_f, actor_user_id=9,
        authz_callback=authz8, precondition_callback=precondition8, writer_callback=writer8,
    )
    check("authz_callback's own exception instance propagates unchanged", False, "no exception raised")
except MyAuthzError as caught:
    check("authz_callback's own exception instance propagates unchanged", caught is _sentinel_authz_error)

check("authz-denial path never called precondition", precondition_calls8 == [])
check("authz-denial path never called the writer", writer_calls8 == [])
check("authz-denial path created NO journal row at all", len(authz_fail_conn.table) == 0)

# ----------------------------------------------------------------
# 9) precondition_callback raises -> NO journal row is created at all
#    (same reasoning as authz denial); writer never runs; authz WAS
#    called first (it runs before precondition in the authoritative
#    order).
# ----------------------------------------------------------------

precond_fail_conn = FakeJournalConn()
intent_g = make_intent(resource_key="case:case_0009", target_ref="t9")
authz9, precondition9, writer9, authz_calls9, precondition_calls9, writer_calls9 = make_callbacks(
    precondition_raises=RuntimeError("stale pre_hash"),
)
expect_raises(
    RuntimeError,
    lambda: mc.run_mutation(
        precond_fail_conn, intent_g, actor_user_id=9,
        authz_callback=authz9, precondition_callback=precondition9, writer_callback=writer9,
    ),
    "precondition_callback's exception propagates",
)
check("precondition-failure path DID call authz first", authz_calls9 == [True])
check("precondition-failure path never called the writer", writer_calls9 == [])
check("precondition-failure path created NO journal row at all", len(precond_fail_conn.table) == 0)

# ----------------------------------------------------------------
# 10) writer_callback raises an ORDINARY exception -> journal row
#     becomes 'reconciliation_required', NEVER 'failed', and stays
#     UNRESOLVED (resolved_at NOT set) - this is the row a future
#     reconciliation pass must find.
# ----------------------------------------------------------------

ambiguous_conn = FakeJournalConn()
intent_h = make_intent(resource_key="case:case_0010", target_ref="t10")
authz10, precondition10, writer10, authz_calls10, precondition_calls10, writer_calls10 = make_callbacks(
    writer_raises=OSError("disk write timed out - unknown whether the file changed"),
)
expect_raises(
    OSError,
    lambda: mc.run_mutation(
        ambiguous_conn, intent_h, actor_user_id=9,
        authz_callback=authz10, precondition_callback=precondition10, writer_callback=writer10,
    ),
    "an ordinary writer exception propagates",
)
check(
    "an ordinary writer exception -> state='reconciliation_required'",
    ambiguous_conn.table[0]["state"] == "reconciliation_required",
)
check("reconciliation_required row is NEVER marked with a failure_code", ambiguous_conn.table[0]["failure_code"] is None)
check("reconciliation_required row stays UNRESOLVED (resolved_at is None)", ambiguous_conn.table[0]["resolved_at"] is None)

authz10b, precondition10b, writer10b, *_ = make_callbacks()
expect_raises(
    mc.ResourceGatedError,
    lambda: mc.run_mutation(
        ambiguous_conn, make_intent(resource_key="case:case_0010", target_ref="t10_other"), actor_user_id=9,
        authz_callback=authz10b, precondition_callback=precondition10b, writer_callback=writer10b,
    ),
    "a follow-up mutation on the SAME resource_key is refused while reconciliation_required is unresolved",
)

# ----------------------------------------------------------------
# 11) A writer exception's class/name is NEVER evidence, however
#     "reassuring" it sounds - even an exception type that superficially
#     resembles the REMOVED `WriterProvenNoMutationError` escape hatch
#     still becomes 'reconciliation_required', identically to any
#     ordinary exception. This is the mandatory
#     "exception özel isim/sınıf taşıması sonucu değiştirmiyor" proof.
# ----------------------------------------------------------------

check("WriterProvenNoMutationError has been REMOVED from this module entirely", not hasattr(mc, "WriterProvenNoMutationError"))


class SuspiciouslyReassuringWriterException(Exception):
    """A writer exception class deliberately named/shaped to LOOK like
    proof of safety (e.g. what a writer author might invent believing
    the coordinator special-cases it). It carries an
    `observed_pre_state_unchanged` attribute set to True, exactly the
    kind of self-declared "proof" the approved contract says must
    NEVER be trusted - the coordinator must not special-case ANY
    exception's type, name, or attributes."""

    def __init__(self, message):
        super().__init__(message)
        self.observed_pre_state_unchanged = True  # a writer's own say-so - must be ignored


suspicious_conn = FakeJournalConn()
intent_i = make_intent(resource_key="case:case_0011", target_ref="t11")
authz11, precondition11, writer11, authz_calls11, precondition_calls11, writer_calls11 = make_callbacks(
    writer_raises=SuspiciouslyReassuringWriterException("trust me, nothing changed"),
)
expect_raises(
    SuspiciouslyReassuringWriterException,
    lambda: mc.run_mutation(
        suspicious_conn, intent_i, actor_user_id=9,
        authz_callback=authz11, precondition_callback=precondition11, writer_callback=writer11,
    ),
    "a specially-named/shaped writer exception still propagates unchanged",
)
check(
    "a specially-named/shaped writer exception STILL becomes 'reconciliation_required', never 'failed'",
    suspicious_conn.table[0]["state"] == "reconciliation_required",
)
check("the specially-shaped exception's row carries NO failure_code either", suspicious_conn.table[0]["failure_code"] is None)
check("the specially-shaped exception's row stays UNRESOLVED (resolved_at is None)", suspicious_conn.table[0]["resolved_at"] is None)

# ----------------------------------------------------------------
# 12) ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION - coordinator
#     durability tests. Production behavior is UNCHANGED by this
#     remediation (run_mutation() itself was not touched) - these
#     tests exist because an independent review specifically asked for
#     them to be proven, not assumed.
#
# 12a) The writer succeeding is not the end of the story: if the
#      coordinator's OWN _mark_completed UPDATE itself fails (e.g. a
#      real connection drop right after a successful write), that
#      exception must propagate visibly - never swallowed - and the
#      row must stay 'executing' (unresolved), never silently flipped
#      to 'completed' OR guessed at as 'failed'.
# ----------------------------------------------------------------


class MarkCompletedFailsCursor(FakeJournalCursor):
    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("UPDATE mutation.mutation_journal SET state = 'completed'"):
            self._calls.append(normalized.split()[0])
            raise FakeIntegrityError("simulated connection loss while durably recording completion")
        super().execute(sql, params)


class MarkCompletedFailsConn(FakeJournalConn):
    def cursor(self):
        return MarkCompletedFailsCursor(self.table, self.calls)


mark_completed_fails_conn = MarkCompletedFailsConn()
intent_12a = make_intent(resource_key="case:case_0012a", target_ref="t12a")
authz12a, precondition12a, writer12a, *_ = make_callbacks()

lock_released_12a = []
try:
    try:
        mc.run_mutation(
            mark_completed_fails_conn, intent_12a, actor_user_id=1,
            authz_callback=authz12a, precondition_callback=precondition12a, writer_callback=writer12a,
        )
        check("an exception from the coordinator's own _mark_completed UPDATE propagates (unreachable line)", False, "no exception was raised")
    except FakeIntegrityError:
        check("an exception raised while durably recording 'completed' (writer already succeeded) propagates visibly, never swallowed", True)
finally:
    # run_mutation() never touches the lock itself (the CALLER's job -
    # see its own docstring) - this stands in for the caller's own
    # `finally: release_lock_session(...)`, proving that shape still
    # runs correctly around a run_mutation() call that raised.
    lock_released_12a.append(True)

check(
    "the row is left 'executing' (unresolved) when _mark_completed's own UPDATE fails - NEVER 'completed', NEVER guessed at as 'failed'",
    mark_completed_fails_conn.table[0]["state"] == "executing",
)
check("the caller's own finally block still runs (the lock would still be released) around a run_mutation() call that raised", lock_released_12a == [True])

# ----------------------------------------------------------------
# 12b) A writer that raises a BaseException subclass which is NOT an
#      Exception subclass (e.g. a deliberately unusual signal type)
#      must NEVER be caught by run_mutation()'s own `except Exception:`
#      around the writer call - Python's own exception hierarchy
#      already guarantees this, but this proves the coordinator does
#      not additionally, redundantly widen that catch to BaseException
#      (which would be a real regression: it would let
#      _mark_reconciliation_required run, and would swallow a signal
#      the caller very much needs to see). The row must stay
#      'executing' (unresolved) and no further UPDATE may be issued at
#      all.
# ----------------------------------------------------------------


class UnclassifiableSignal(BaseException):
    """Deliberately a direct BaseException subclass, NOT an Exception
    subclass - `except Exception:` must never catch this."""


base_exc_conn = FakeJournalConn()
intent_12b = make_intent(resource_key="case:case_0012b", target_ref="t12b")
authz12b, precondition12b, _writer12b, authz_calls12b, precondition_calls12b, _writer_calls12b = make_callbacks()


def writer_raises_base_exception():
    raise UnclassifiableSignal("not an Exception subclass at all")


lock_released_12b = []
try:
    try:
        mc.run_mutation(
            base_exc_conn, intent_12b, actor_user_id=1,
            authz_callback=authz12b, precondition_callback=precondition12b, writer_callback=writer_raises_base_exception,
        )
        check("a BaseException-only writer exception propagates (unreachable line)", False, "no exception was raised")
    except UnclassifiableSignal:
        check("a writer exception that is a BaseException but NOT an Exception subclass is NEVER swallowed by `except Exception:`", True)
finally:
    lock_released_12b.append(True)

check("authz and precondition still ran exactly once each before the writer raised", authz_calls12b == [True] and precondition_calls12b == [True])
check(
    "the row stays 'executing' (unresolved) when the writer raises a bare BaseException - _mark_reconciliation_required is never reached",
    base_exc_conn.table[0]["state"] == "executing",
)
check(
    "no UPDATE beyond the prepared->executing transition was ever issued (the writer's BaseException skipped _mark_reconciliation_required entirely)",
    base_exc_conn.calls.count("UPDATE") == 1,
)
check("the caller's own finally block still runs around a run_mutation() call that raised a bare BaseException", lock_released_12b == [True])

# ----------------------------------------------------------------
# 13) is_stale_executing() - pure, never mutates anything.
# ----------------------------------------------------------------

check("is_stale_executing: well within the default 5-minute threshold -> not stale", mc.is_stale_executing(1000.0, now=1100.0) is False)
check("is_stale_executing: past the default 5-minute threshold -> stale", mc.is_stale_executing(1000.0, now=1000.0 + 301) is True)
check("is_stale_executing: exactly at the threshold -> not stale (strictly greater-than)", mc.is_stale_executing(1000.0, now=1300.0) is False)
check("is_stale_executing: custom threshold_seconds is honored", mc.is_stale_executing(1000.0, now=1005.0, threshold_seconds=3) is True)
check("is_stale_executing defaults `now` to the real clock when omitted (no crash, returns a bool)", isinstance(mc.is_stale_executing(0.0), bool))

print(f"--- test_mutation_coordinator_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
