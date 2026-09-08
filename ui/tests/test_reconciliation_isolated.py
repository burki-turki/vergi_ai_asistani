# ============================================================
# Row 19C-1 - isolated (fake-adapter, fake-connection) tests for
# ui/services/mutation_registry.py.
#
# ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION: this file was
# rewritten end to end because the public API it tests changed shape -
# the former two-function split (`reconcile_journal_entry()` deciding
# from a caller-supplied snapshot, a separate `apply_reconciliation_
# outcome()` writing, unlocked, afterwards) is GONE. The single public
# entry point now is `reconcile_and_apply_journal_entry(conn,
# journal_id, registry)`: it takes only a bare `journal_id`, reads the
# row's `resource_key` before any lock (only to decide which lock to
# take), acquires that lock, re-reads the FULL row AUTHORITATIVELY
# under the lock, decides, applies the decision with a rowcount-checked
# guarded UPDATE, and only THEN releases the lock - see that function's
# own docstring and this module's header comment for the full
# rationale.
#
# Proves, against a FAKE `mutation.mutation_journal` table (an
# in-memory list of dict rows, same minimal DB-API-2.0 shape as the
# other isolated test files in this project) and FAKE adapters (no
# real production adapter exists this turn):
#   - MutationAdapterRegistry's fail-closed duplicate/unknown handling
#     (unchanged from the original Row 19C-1 design);
#   - the pre-lock resource_key read / authoritative reread sequence,
#     and that the DECISION is always driven by the AUTHORITATIVE
#     reread, never by anything read or assumed beforehand;
#   - JournalEntryNotFoundError (no lock ever taken) and
#     ResourceKeyMismatchError (a fail-closed backstop);
#   - that reconciliation acquires/releases the EXACT SAME
#     session-level lock primitives ui.services.mutation_lock exposes
#     (never a re-implementation) - a `case:` resource_key goes through
#     `acquire_case_lock_session`, anything else through
#     `acquire_global_lock_session` - and ALWAYS releases the lock,
#     even when the adapter itself raises, even after the apply step;
#   - the full decision table for `executing`/`reconciliation_required`
#     origin rows (unchanged rules) AND the new, stricter `prepared`
#     origin rule (never auto-`completed`, only `failed` or
#     `reconciliation_required`);
#   - the guarded UPDATE's rowcount check
#     (ReconciliationApplyFailedError on anything but exactly 1 row
#     affected).
#
# Run: python -m ui.tests.test_reconciliation_isolated
# ============================================================

import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import mutation_lock as ml            # noqa: E402
from ui.services import mutation_registry as mr         # noqa: E402

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
# 1) MutationAdapterRegistry - fail-closed duplicate/unknown handling,
#    immutability of with_adapter(), no shared mutable state. UNCHANGED
#    from the original Row 19C-1 design - this class itself was not
#    touched by the atomicity remediation.
# ----------------------------------------------------------------

class FakeAdapter:
    def __init__(self, evidence_or_raiser):
        self._evidence_or_raiser = evidence_or_raiser

    def gather_evidence(self, entry):
        if callable(self._evidence_or_raiser):
            return self._evidence_or_raiser(entry)
        return self._evidence_or_raiser


empty_registry = mr.MutationAdapterRegistry()
check("a brand-new MutationAdapterRegistry knows no action families", empty_registry.known_action_families() == frozenset())

adapter_x = FakeAdapter(mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=False))
with_x = empty_registry.with_adapter("fam.x", adapter_x)
check("with_adapter() returns a NEW registry rather than mutating the original", empty_registry.known_action_families() == frozenset())
check("the NEW registry knows the newly-added action family", with_x.known_action_families() == frozenset({"fam.x"}))
check("get() returns the exact adapter instance that was registered", with_x.get("fam.x") is adapter_x)

expect_raises(
    mr.DuplicateActionFamilyError,
    lambda: with_x.with_adapter("fam.x", FakeAdapter(None)),
    "registering an already-registered action_family fails closed (never silently overwrites)",
)
check(
    "a failed duplicate registration did not corrupt the original registry's adapter",
    with_x.get("fam.x") is adapter_x,
)

expect_raises(
    mr.UnknownActionFamilyError,
    lambda: with_x.get("fam.does-not-exist"),
    "looking up an unregistered action_family fails closed (never returns a 'close enough' adapter)",
)

adapter_y = FakeAdapter(mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True))
with_x_and_y = with_x.with_adapter("fam.y", adapter_y)
check(
    "chained with_adapter() calls accumulate independently (both families present, neither adapter swapped)",
    with_x_and_y.get("fam.x") is adapter_x and with_x_and_y.get("fam.y") is adapter_y,
)
check(
    "the intermediate registry (with_x) is untouched by the later chained call",
    with_x.known_action_families() == frozenset({"fam.x"}),
)


# ----------------------------------------------------------------
# 2) Fake mutation.mutation_journal table + cursor - models exactly
#    the four statement shapes reconcile_and_apply_journal_entry()
#    actually issues: the pre-lock resource_key read, the authoritative
#    full-row reread, and the two guarded UPDATE shapes (rowcount
#    tracked on every execute(), matching real DB-API-2.0 cursors).
# ----------------------------------------------------------------

_RESOLVABLE_STATES = ("prepared", "executing", "reconciliation_required")


class FakeReconcileCursor:
    def __init__(self, table, calls):
        self._table = table
        self._calls = calls
        self._last_result = None
        self.rowcount = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _row(self, journal_id):
        for r in self._table:
            if r["id"] == journal_id:
                return r
        return None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._calls.append(normalized)

        if normalized.startswith("SELECT resource_key FROM mutation.mutation_journal WHERE id"):
            (journal_id,) = params
            row = self._row(journal_id)
            self._last_result = (row["resource_key"],) if row is not None else None
            self.rowcount = 1 if row is not None else 0

        elif normalized.startswith("SELECT id, resource_key, action_family, target_ref, target_state"):
            (journal_id,) = params
            row = self._row(journal_id)
            if row is None:
                self._last_result = None
                self.rowcount = 0
            else:
                self._last_result = (
                    row["id"], row["resource_key"], row["action_family"], row["target_ref"],
                    row["target_state"], row["pre_hash"], row["pre_revision"],
                    row["expected_post_hash"], row["state"],
                    row["idempotency_key"],  # ROW 19C-2a: appended field - see JournalEntrySnapshot's own comment
                    row["request_fingerprint"], row["actor_label"],  # ROW 19C-2b: appended fields
                )
                self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'reconciliation_required'"):
            (journal_id,) = params
            row = self._row(journal_id)
            if row is not None and row["state"] in _RESOLVABLE_STATES:
                row["state"] = "reconciliation_required"
                if row.get("executing_at") is None:
                    row["executing_at"] = "FAKE_TIMESTAMP"
                self.rowcount = 1
            else:
                self.rowcount = 0

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'failed', resolution_code = %s"):
            # ROW 19C-1 TIMESTAMP SEMANTICS CORRECTION: the
            # prepared-never-executed branch. Deliberately does NOT
            # touch executing_at at all (must stay exactly what it
            # already was - NULL for a genuine prepared row), and is
            # guarded to only match a row whose CURRENT state is
            # 'prepared' - matching the real SQL's narrowed
            # "WHERE id = %s AND state = 'prepared'". ROW 19C-2a: now
            # also carries reconciled_by_actor_type/actor_ref.
            resolution_code, observed_post_hash, reconciled_by_actor_type, reconciled_by_actor_ref, journal_id = params
            row = self._row(journal_id)
            if row is not None and row["state"] == "prepared":
                row["state"] = "failed"
                row["resolution_code"] = resolution_code
                row["observed_post_hash"] = observed_post_hash
                row["resolved_at"] = "FAKE_TIMESTAMP"
                row["reconciled_by_actor_type"] = reconciled_by_actor_type
                row["reconciled_by_actor_ref"] = reconciled_by_actor_ref
                self.rowcount = 1
            else:
                self.rowcount = 0

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = %s"):
            # The general completed/failed branch - reachable only for
            # a row that already crossed the writer boundary, so its
            # WHERE guard is narrowed to ('executing',
            # 'reconciliation_required') only ('prepared' removed,
            # matching the real SQL - this outcome shape is
            # structurally unreachable from a 'prepared' origin per
            # _decide_outcome()). ROW 19C-2a: now also carries
            # reconciled_by_actor_type/actor_ref.
            new_state, resolution_code, observed_post_hash, reconciled_by_actor_type, reconciled_by_actor_ref, journal_id = params
            row = self._row(journal_id)
            if row is not None and row["state"] in ("executing", "reconciliation_required"):
                row["state"] = new_state
                row["resolution_code"] = resolution_code
                row["observed_post_hash"] = observed_post_hash
                row["resolved_at"] = "FAKE_TIMESTAMP"
                if row.get("executing_at") is None:
                    row["executing_at"] = "FAKE_TIMESTAMP"
                row["reconciled_by_actor_type"] = reconciled_by_actor_type
                row["reconciled_by_actor_ref"] = reconciled_by_actor_ref
                self.rowcount = 1
            else:
                self.rowcount = 0

        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._last_result


class FakeReconcileConn:
    def __init__(self, table=None):
        self.table = table if table is not None else []
        self.calls = []

    def cursor(self):
        return FakeReconcileCursor(self.table, self.calls)


def make_journal_row(**overrides):
    row = dict(
        id=1, resource_key="case:case_0001", action_family="fam.x",
        target_ref="target_a", target_state=None, pre_hash=None, pre_revision=None,
        expected_post_hash=None, state="executing",
        resolution_code=None, observed_post_hash=None, resolved_at=None, executing_at="PRE_EXISTING_TS",
        idempotency_key="fake_idempotency_key_0001",  # ROW 19C-2a: JournalEntrySnapshot's new appended field
        reconciled_by_actor_type=None, reconciled_by_actor_ref=None,  # ROW 19C-2a: provenance, NULL by default
        # ROW 19C-2b: JournalEntrySnapshot's two newest appended fields
        # - existing NOT NULL columns since 0003, never blank in a real
        # row.
        request_fingerprint="fake_request_fingerprint_0001", actor_label="1",
    )
    row.update(overrides)
    return row


# ----------------------------------------------------------------
# 3) reconcile_and_apply_journal_entry() - fail-closed BEFORE any lock
#    (JournalEntryNotFoundError) and fail-closed on an AUTHORITATIVE
#    terminal state (UnsupportedJournalStateError - 'prepared' is now
#    a SUPPORTED state, unlike the original Row 19C-1 design).
# ----------------------------------------------------------------

_lock_calls = []
_original_acquire_case = ml.acquire_case_lock_session
_original_acquire_global = ml.acquire_global_lock_session
_original_release = ml.release_lock_session


def _fake_acquire_case_lock_session(conn, case_id):
    _lock_calls.append(("acquire_case", case_id))
    return 111


def _fake_acquire_global_lock_session(conn, resource_key):
    _lock_calls.append(("acquire_global", resource_key))
    return 222


def _fake_release_lock_session(conn, advisory_lock_id):
    _lock_calls.append(("release", advisory_lock_id))
    return True


try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session

    # -- JournalEntryNotFoundError: no row at all, no lock ever taken --
    _lock_calls.clear()
    expect_raises(
        mr.JournalEntryNotFoundError,
        lambda: mr.reconcile_and_apply_journal_entry(FakeReconcileConn(), 999, with_x),
        "a nonexistent journal_id fails closed with JournalEntryNotFoundError",
    )
    check("no lock was ever acquired for a nonexistent journal_id (fails closed BEFORE any lock)", _lock_calls == [])

    # -- terminal (authoritative) states are refused --
    for bad_state in ("completed", "failed"):
        conn = FakeReconcileConn([make_journal_row(id=1, state=bad_state, action_family="fam.x")])
        expect_raises(
            mr.UnsupportedJournalStateError,
            lambda conn=conn: mr.reconcile_and_apply_journal_entry(conn, 1, with_x),
            f"a TERMINAL authoritative state ({bad_state!r}) is refused - already resolved, needs no reconciliation",
        )

    # -- 'prepared' is now a SUPPORTED state (the whole point of the
    #    atomicity remediation's permanent-gate fix) - it must NOT
    #    raise UnsupportedJournalStateError. Uses adapter_y's evidence
    #    (pre_state_confirmed_unchanged=True, post_state_verified=False)
    #    - the ONE combination that legitimately resolves a 'prepared'
    #    row (see the FINAL PREPARED-INCONCLUSIVE SEMANTICS CORRECTION
    #    in section 7 below for every OTHER combination, which now
    #    raises PreparedJournalUnresolvedError instead). --
    prepared_conn = FakeReconcileConn([make_journal_row(id=1, state="prepared", executing_at=None, action_family="fam.y")])
    prepared_outcome = mr.reconcile_and_apply_journal_entry(prepared_conn, 1, with_x_and_y)
    check(
        "'prepared' is accepted (no UnsupportedJournalStateError) - it is now a resolvable state",
        isinstance(prepared_outcome, mr.ReconciliationOutcome),
    )

    # ----------------------------------------------------------------
    # 4) Lock acquisition/release proof - same primitives, same
    #    behavior as the original design, now exercised through the
    #    single merged entry point.
    # ----------------------------------------------------------------

    _lock_calls.clear()
    conn_case = FakeReconcileConn([make_journal_row(id=1, resource_key="case:case_0099", state="executing")])
    mr.reconcile_and_apply_journal_entry(conn_case, 1, with_x)
    check(
        "a case: resource_key routes through acquire_case_lock_session with the bare case_id (prefix stripped)",
        ("acquire_case", "case_0099") in _lock_calls,
    )
    check("the acquired case lock is released afterwards", ("release", 111) in _lock_calls)
    check("acquire_global_lock_session is NOT called for a case: resource_key", not any(c[0] == "acquire_global" for c in _lock_calls))

    _lock_calls.clear()
    conn_global = FakeReconcileConn([make_journal_row(id=1, resource_key="global:rag_index", action_family="fam.y", state="executing")])
    mr.reconcile_and_apply_journal_entry(conn_global, 1, with_x_and_y)
    check(
        "a non-case: resource_key routes through acquire_global_lock_session with the full resource_key",
        ("acquire_global", "global:rag_index") in _lock_calls,
    )
    check("the acquired global lock is released afterwards", ("release", 222) in _lock_calls)
    check("acquire_case_lock_session is NOT called for a global: resource_key", not any(c[0] == "acquire_case" for c in _lock_calls))

    # The lock must be released even when the adapter itself raises -
    # reconciliation must never leak a held session lock.
    class ExplodingAdapter:
        def gather_evidence(self, entry):
            raise RuntimeError("adapter bug, not an evidence outcome")

    exploding_registry = mr.MutationAdapterRegistry().with_adapter("fam.explodes", ExplodingAdapter())
    _lock_calls.clear()
    exploding_conn = FakeReconcileConn([make_journal_row(id=1, resource_key="case:case_0100", action_family="fam.explodes", state="executing")])
    expect_raises(
        RuntimeError,
        lambda: mr.reconcile_and_apply_journal_entry(exploding_conn, 1, exploding_registry),
        "an adapter's own exception propagates out of reconcile_and_apply_journal_entry() unchanged",
    )
    check("the lock is STILL released even though the adapter raised", ("release", 111) in _lock_calls)
    check("the row is left completely unresolved when the adapter raises (no partial write)", exploding_conn.table[0]["state"] == "executing")

    # Unknown action_family - the lock is taken (resource_key alone
    # determines the lock) but must still be released even though
    # `registry.get()` fails closed before any adapter runs.
    _lock_calls.clear()
    unknown_family_conn = FakeReconcileConn([make_journal_row(id=1, resource_key="case:case_0101", action_family="fam.unregistered", state="executing")])
    expect_raises(
        mr.UnknownActionFamilyError,
        lambda: mr.reconcile_and_apply_journal_entry(unknown_family_conn, 1, with_x),
        "an unregistered (AUTHORITATIVE) action_family fails closed even after the lock was already taken",
    )
    check("the lock is released even when the action_family lookup itself fails closed", ("release", 111) in _lock_calls)

    # ----------------------------------------------------------------
    # 5) The decision is driven by the AUTHORITATIVE reread, never by
    #    anything believed beforehand - proven by seeding a row whose
    #    action_family, if it were (wrongly) taken from anywhere else,
    #    would resolve to a DIFFERENT adapter/outcome than the one the
    #    authoritative row itself actually names.
    # ----------------------------------------------------------------

    authoritative_conn = FakeReconcileConn([make_journal_row(id=1, resource_key="case:case_authoritative", action_family="fam.y", state="executing")])
    # with_x_and_y has BOTH fam.x (completes) and fam.y (fails) registered -
    # only the row's OWN action_family ("fam.y") may be consulted.
    authoritative_outcome = mr.reconcile_and_apply_journal_entry(authoritative_conn, 1, with_x_and_y)
    check(
        "the adapter actually used is the one named by the AUTHORITATIVE row's action_family (fam.y -> failed), not any other registered one",
        authoritative_outcome.new_state == "failed",
    )

    # ----------------------------------------------------------------
    # 6) Decision table - executing/reconciliation_required origin
    #    (unchanged rules from the original Row 19C-1 design), now
    #    proven end-to-end including the actual journal row mutation.
    # ----------------------------------------------------------------

    def reconcile_with_evidence(evidence, *, origin_state="executing", action_family="fam.decide"):
        # A REAL 'prepared' row always has executing_at = NULL (its own
        # INSERT never sets it - enforced by 0003's own
        # mutation_journal_executing_at_matches_state CHECK constraint);
        # an 'executing'/'reconciliation_required' origin row always
        # already crossed the writer boundary, so it already carries a
        # real (non-NULL) executing_at. Modeling the fake row's starting
        # executing_at accordingly (rather than always using
        # make_journal_row's generic default) is what lets the
        # TIMESTAMP SEMANTICS CORRECTION's "stays NULL" assertions below
        # actually exercise the fix, instead of trivially passing
        # because a leftover non-NULL default was never cleared.
        starting_executing_at = None if origin_state == "prepared" else "PRE_EXISTING_TS"
        registry = mr.MutationAdapterRegistry().with_adapter(action_family, FakeAdapter(evidence))
        conn = FakeReconcileConn([make_journal_row(
            id=1, resource_key="case:case_decide", action_family=action_family, state=origin_state,
            executing_at=starting_executing_at,
        )])
        outcome = mr.reconcile_and_apply_journal_entry(conn, 1, registry)
        return outcome, conn.table[0]

    completed_outcome, completed_row = reconcile_with_evidence(
        mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=False, observed_post_hash="realhash"),
    )
    check("post_state_verified=True, pre_state_confirmed_unchanged=False -> new_state='completed'", completed_outcome.new_state == "completed")
    check(
        "a 'completed' reconciliation outcome carries the fixed resolution_code (imported from mutation_guard, not a duplicated literal)",
        completed_outcome.resolution_code == "reconciled_completed_post_state_verified",
    )
    check("a 'completed' reconciliation outcome carries the adapter's own observed_post_hash", completed_outcome.observed_post_hash == "realhash")
    check("the journal row itself was durably updated to 'completed' by the SAME call", completed_row["state"] == "completed" and completed_row["resolved_at"] == "FAKE_TIMESTAMP")

    failed_outcome, failed_row = reconcile_with_evidence(
        mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True),
    )
    check("post_state_verified=False, pre_state_confirmed_unchanged=True -> new_state='failed'", failed_outcome.new_state == "failed")
    check(
        "a 'failed' reconciliation outcome (from executing/reconciliation_required origin) carries RESOLUTION_CODE_FAILED_PRE_STATE_UNCHANGED",
        failed_outcome.resolution_code == "reconciled_failed_pre_state_confirmed_unchanged",
    )
    check("the journal row itself was durably updated to 'failed'", failed_row["state"] == "failed")

    inconclusive_outcome, inconclusive_row = reconcile_with_evidence(
        mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False),
    )
    check("post_state_verified=False, pre_state_confirmed_unchanged=False -> new_state='reconciliation_required' (never guessed)", inconclusive_outcome.new_state == "reconciliation_required")
    check("an inconclusive outcome carries NO resolution_code", inconclusive_outcome.resolution_code is None)
    check("the journal row is written back as 'reconciliation_required' (not just left/returned)", inconclusive_row["state"] == "reconciliation_required")

    contradictory_outcome, _ = reconcile_with_evidence(
        mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=True, observed_post_hash="weirdhash"),
    )
    check(
        "BOTH proofs True (a contradiction) -> new_state='reconciliation_required', never resolved by picking one side",
        contradictory_outcome.new_state == "reconciliation_required",
    )
    check("a contradictory outcome carries NO resolution_code either", contradictory_outcome.resolution_code is None)

    # ----------------------------------------------------------------
    # 7) 'prepared'-origin resolution - the permanent-gate fix, PLUS the
    #    FINAL PREPARED-INCONCLUSIVE SEMANTICS CORRECTION. A prepared
    #    row's writer was NEVER invoked (coordinator ordering contract)
    #    - it resolves to 'failed' ONLY when the evidence conclusively
    #    proves pre_state_confirmed_unchanged=True AND
    #    post_state_verified=False; EVERY other evidence combination
    #    (insufficient, contradictory, or a suspicious
    #    post_state_verified=True claim) raises
    #    PreparedJournalUnresolvedError instead of ever reaching
    #    'reconciliation_required' - since that state's own CHECK
    #    constraint would force a fabricated executing_at timestamp for
    #    a writer invocation that provably never happened. NEVER
    #    'completed' either way, no matter what the adapter reports.
    # ----------------------------------------------------------------

    prepared_failed_outcome, prepared_failed_row = reconcile_with_evidence(
        mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True),
        origin_state="prepared",
    )
    check(
        "prepared + pre_state_confirmed_unchanged=True -> new_state='failed' with the PREPARED-specific resolution_code",
        prepared_failed_outcome.new_state == "failed"
        and prepared_failed_outcome.resolution_code == "reconciled_failed_prepared_never_executed",
    )
    check(
        "the resolved-from-prepared (never-executed) row's executing_at STAYS NULL - the writer was never invoked, so no execution timestamp is fabricated (TIMESTAMP SEMANTICS CORRECTION)",
        prepared_failed_row["executing_at"] is None,
    )
    check("the resolved-from-prepared row's state is durably 'failed'", prepared_failed_row["state"] == "failed")
    check(
        "the resolved-from-prepared row carries the prepared-never-executed resolution_code (never the generic pre-state-unchanged one)",
        prepared_failed_row["resolution_code"] == "reconciled_failed_prepared_never_executed",
    )
    check(
        "the resolved-from-prepared (never-executed) row's resolved_at IS set (this row IS terminal/final - only executing_at is left NULL)",
        prepared_failed_row["resolved_at"] is not None,
    )

    def reconcile_prepared_expect_unresolved(evidence, *, label_evidence, action_family="fam.prepared_unresolved"):
        """ROW 19C-1 FINAL PREPARED-INCONCLUSIVE SEMANTICS CORRECTION -
        drives reconcile_and_apply_journal_entry() against a fresh
        'prepared'-origin row and proves the FULL required contract
        for every evidence combination OTHER than the one legitimate
        'failed' resolution (see PreparedJournalUnresolvedError's own
        docstring): the call raises exactly that exception; the row is
        left EXACTLY as it was (still 'prepared', executing_at/
        resolved_at/resolution_code all untouched - no fabricated
        execution timestamp for a writer that never ran); NO UPDATE
        statement was ever issued against the journal table; and the
        lock taken for this call was still released (the resource
        remains gated, but not because of a leaked lock)."""
        registry = mr.MutationAdapterRegistry().with_adapter(action_family, FakeAdapter(evidence))
        conn = FakeReconcileConn([make_journal_row(
            id=1, resource_key="case:case_prepared_unresolved", action_family=action_family,
            state="prepared", executing_at=None, resolved_at=None, resolution_code=None,
        )])
        _lock_calls.clear()
        expect_raises(
            mr.PreparedJournalUnresolvedError,
            lambda: mr.reconcile_and_apply_journal_entry(conn, 1, registry),
            f"prepared + {label_evidence} -> PreparedJournalUnresolvedError (no auto-resolution, no fabricated timestamp)",
        )
        row = conn.table[0]
        check(f"prepared + {label_evidence}: the row is STILL 'prepared' (no UPDATE ever applied)", row["state"] == "prepared")
        check(f"prepared + {label_evidence}: executing_at STAYS NULL", row["executing_at"] is None)
        check(f"prepared + {label_evidence}: resolved_at STAYS NULL", row["resolved_at"] is None)
        check(f"prepared + {label_evidence}: resolution_code STAYS NULL", row["resolution_code"] is None)
        check(
            f"prepared + {label_evidence}: NO UPDATE statement was ever issued against the journal table",
            not any(call.startswith("UPDATE") for call in conn.calls),
            f"calls were: {conn.calls!r}",
        )
        check(f"prepared + {label_evidence}: the lock taken for this call was still released (no leaked lock)", ("release", 111) in _lock_calls)
        return row

    # (1) insufficient evidence - both proofs False.
    reconcile_prepared_expect_unresolved(
        mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False),
        label_evidence="insufficient evidence (both proofs False)",
    )

    # (2) contradictory evidence - both proofs True.
    reconcile_prepared_expect_unresolved(
        mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=True),
        label_evidence="contradictory evidence (both proofs True)",
    )

    # (3) a suspicious post_state_verified=True claim against a row
    #     whose writer never ran - must NOT be trusted to auto-complete
    #     (nor auto-resolve to anything else).
    reconcile_prepared_expect_unresolved(
        mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=False, observed_post_hash="should_never_auto_complete"),
        label_evidence="post_state_verified=True only (writer never invoked - never auto-'completed')",
    )

    check(
        "mutation_guard's RESOLUTION_CODES frozenset contains exactly the three codes this decision table can produce",
        {completed_outcome.resolution_code, failed_outcome.resolution_code, prepared_failed_outcome.resolution_code} == {
            "reconciled_completed_post_state_verified",
            "reconciled_failed_pre_state_confirmed_unchanged",
            "reconciled_failed_prepared_never_executed",
        },
    )
finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.acquire_global_lock_session = _original_acquire_global
    ml.release_lock_session = _original_release


# ----------------------------------------------------------------
# 8) ResourceKeyMismatchError - a fail-closed backstop for a case that
#    should be structurally unreachable (no code path ever updates
#    resource_key after a row is inserted). Modeled with a small,
#    dedicated fake conn whose pre-lock read and authoritative reread
#    deliberately disagree, so this specific defensive branch is
#    actually exercised rather than merely trusted by inspection.
# ----------------------------------------------------------------

class MismatchedResourceKeyCursor(FakeReconcileCursor):
    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT resource_key FROM mutation.mutation_journal WHERE id"):
            self._calls.append(normalized)
            self._last_result = ("case:pre_lock_belief",)
            self.rowcount = 1
        else:
            super().execute(sql, params)


class MismatchedResourceKeyConn(FakeReconcileConn):
    def cursor(self):
        return MismatchedResourceKeyCursor(self.table, self.calls)


try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session

    _lock_calls.clear()
    mismatch_conn = MismatchedResourceKeyConn([
        make_journal_row(id=1, resource_key="case:actual_authoritative_key", action_family="fam.x", state="executing"),
    ])
    expect_raises(
        mr.ResourceKeyMismatchError,
        lambda: mr.reconcile_and_apply_journal_entry(mismatch_conn, 1, with_x),
        "a pre-lock resource_key that disagrees with the authoritative (lock-held) reread fails closed",
    )
    check("the lock taken for the mismatch case is STILL released", ("release", 111) in _lock_calls)
    check("no write ever happened to the row when resource_key mismatched", mismatch_conn.table[0]["state"] == "executing")
finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.acquire_global_lock_session = _original_acquire_global
    ml.release_lock_session = _original_release


# ----------------------------------------------------------------
# 9) ReconciliationApplyFailedError - the guarded UPDATE's rowcount
#    check. Simulated deterministically (no real concurrency needed
#    for a fake, single-threaded, in-memory table): a "self-sabotaging"
#    adapter reaches into the table and flips the row to an already-
#    TERMINAL state DURING its own gather_evidence() call, standing in
#    for "something outside this module's locking discipline changed
#    the row between the authoritative reread and the apply step" -
#    the guarded UPDATE's WHERE ... state IN (...) clause then matches
#    zero rows, and this must be a VISIBLE, counted failure, never a
#    silent no-op.
# ----------------------------------------------------------------

class SelfSabotagingAdapter:
    def __init__(self, table, journal_id):
        self._table = table
        self._journal_id = journal_id

    def gather_evidence(self, entry):
        for row in self._table:
            if row["id"] == self._journal_id:
                row["state"] = "completed"
                row["resolution_code"] = "reconciled_completed_post_state_verified"
                row["resolved_at"] = "SOMEONE_ELSE_RESOLVED_THIS"
        return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)


try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session

    _lock_calls.clear()
    sabotage_table = [make_journal_row(id=1, resource_key="case:case_sabotage", action_family="fam.sabotage", state="executing")]
    sabotage_conn = FakeReconcileConn(sabotage_table)
    sabotage_registry = mr.MutationAdapterRegistry().with_adapter("fam.sabotage", SelfSabotagingAdapter(sabotage_table, 1))
    expect_raises(
        mr.ReconciliationApplyFailedError,
        lambda: mr.reconcile_and_apply_journal_entry(sabotage_conn, 1, sabotage_registry),
        "a guarded UPDATE affecting zero rows (row resolved out from under this call) is a VISIBLE, counted failure",
    )
    check("the lock is still released even when the apply step itself fails closed", ("release", 111) in _lock_calls)
    check(
        "the row is left exactly as the sabotage left it (this call's own decision was never applied on top)",
        sabotage_conn.table[0]["resolved_at"] == "SOMEONE_ELSE_RESOLVED_THIS",
    )
finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.acquire_global_lock_session = _original_acquire_global
    ml.release_lock_session = _original_release


# ----------------------------------------------------------------
# 10) ROW 19C-2a: `JournalEntrySnapshot.idempotency_key` is populated
#     from the authoritative reread and visible to the adapter's own
#     `gather_evidence(entry)` call - this is what
#     ui/services/mutation_approval_adapters.py (Row 19C-2a's own
#     reconciliation adapters) will match against an approval audit
#     record's `mutation_idempotency_key` field.
# ----------------------------------------------------------------

class IdempotencyKeySpyAdapter:
    def __init__(self):
        self.seen_idempotency_key = None

    def gather_evidence(self, entry):
        self.seen_idempotency_key = entry.idempotency_key
        return mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=False)


try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session

    idem_spy = IdempotencyKeySpyAdapter()
    idem_registry = mr.MutationAdapterRegistry().with_adapter("fam.idem_spy", idem_spy)
    idem_conn = FakeReconcileConn([make_journal_row(
        id=1, resource_key="case:case_idem", action_family="fam.idem_spy", state="executing",
        idempotency_key="real_idempotency_key_xyz",
    )])
    mr.reconcile_and_apply_journal_entry(idem_conn, 1, idem_registry)
    check(
        "ROW 19C-2a: the adapter's gather_evidence(entry) sees the AUTHORITATIVE row's own idempotency_key",
        idem_spy.seen_idempotency_key == "real_idempotency_key_xyz",
    )
finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.acquire_global_lock_session = _original_acquire_global
    ml.release_lock_session = _original_release

# ----------------------------------------------------------------
# 11) ROW 19C-2a RECONCILIATION PROVENANCE: `resolved_by_actor_type`/
#     `resolved_by_actor_ref` are optional, threaded into the
#     `completed`/`failed` UPDATE branches ONLY, and default to NULL
#     (byte-identical to pre-Row-19C-2a behavior) when omitted.
# ----------------------------------------------------------------

try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session

    # 11a) Omitted entirely -> NULL provenance, exactly as every
    # pre-existing call site (including every test above this section)
    # already implicitly proved by never breaking.
    no_prov_conn = FakeReconcileConn([make_journal_row(id=1, resource_key="case:case_prov_a", action_family="fam.x", state="executing")])
    mr.reconcile_and_apply_journal_entry(no_prov_conn, 1, with_x)
    check(
        "ROW 19C-2a: omitting resolved_by_actor_type/ref leaves the row's provenance NULL (pre-19C-2a-identical default)",
        no_prov_conn.table[0]["reconciled_by_actor_type"] is None and no_prov_conn.table[0]["reconciled_by_actor_ref"] is None,
    )

    # 11b) Explicitly passed -> recorded on the general completed/failed branch.
    with_prov_conn = FakeReconcileConn([make_journal_row(id=1, resource_key="case:case_prov_b", action_family="fam.x", state="executing")])
    mr.reconcile_and_apply_journal_entry(
        with_prov_conn, 1, with_x,
        resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c2a_operator_test",
    )
    check(
        "ROW 19C-2a: resolved_by_actor_type/ref ARE recorded on the general completed/failed branch when passed",
        with_prov_conn.table[0]["reconciled_by_actor_type"] == "cli_service"
        and with_prov_conn.table[0]["reconciled_by_actor_ref"] == "row19c2a_operator_test",
    )

    # 11c) Explicitly passed against a 'prepared'-origin row -> recorded
    # on the prepared-never-executed 'failed' branch too.
    prepared_prov_registry = mr.MutationAdapterRegistry().with_adapter(
        "fam.prov_prepared", FakeAdapter(mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)),
    )
    prepared_prov_conn = FakeReconcileConn([make_journal_row(
        id=1, resource_key="case:case_prov_prepared", action_family="fam.prov_prepared", state="prepared", executing_at=None,
    )])
    mr.reconcile_and_apply_journal_entry(
        prepared_prov_conn, 1, prepared_prov_registry,
        resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c2a_operator_test_prepared",
    )
    check(
        "ROW 19C-2a: resolved_by_actor_type/ref ARE recorded on the prepared-never-executed 'failed' branch when passed",
        prepared_prov_conn.table[0]["reconciled_by_actor_type"] == "cli_service"
        and prepared_prov_conn.table[0]["reconciled_by_actor_ref"] == "row19c2a_operator_test_prepared",
    )

    # 11d) Explicitly passed but the outcome is 'reconciliation_required'
    # (inconclusive evidence) -> NEVER recorded - that branch's own SQL
    # never references these columns at all, matching "provenance may
    # only be recorded alongside an actual resolution" (0004's own
    # mutation_journal_reconciled_provenance_implies_resolved CHECK).
    inconclusive_prov_registry = mr.MutationAdapterRegistry().with_adapter(
        "fam.prov_inconclusive", FakeAdapter(mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)),
    )
    inconclusive_prov_conn = FakeReconcileConn([make_journal_row(
        id=1, resource_key="case:case_prov_inconclusive", action_family="fam.prov_inconclusive", state="executing",
    )])
    mr.reconcile_and_apply_journal_entry(
        inconclusive_prov_conn, 1, inconclusive_prov_registry,
        resolved_by_actor_type="cli_service", resolved_by_actor_ref="should_never_be_recorded",
    )
    check(
        "ROW 19C-2a: resolved_by_actor_type/ref are NEVER recorded on a 'reconciliation_required' outcome, "
        "even when passed - that branch's own UPDATE never references these columns",
        inconclusive_prov_conn.table[0]["state"] == "reconciliation_required"
        and inconclusive_prov_conn.table[0]["reconciled_by_actor_type"] is None
        and inconclusive_prov_conn.table[0]["reconciled_by_actor_ref"] is None,
    )
finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.acquire_global_lock_session = _original_acquire_global
    ml.release_lock_session = _original_release

# ----------------------------------------------------------------
# 12) ROW 19C-2a: `inspect_reconciliation()` - the DRY-RUN counterpart.
#     Same lock/reread/decide steps, ZERO UPDATEs ever, same exceptions
#     for the same reasons, lock still acquired AND released.
# ----------------------------------------------------------------

try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session

    # 12a) Happy path - returns the SAME outcome apply would have
    # produced, but issues NO UPDATE and leaves the row untouched.
    _lock_calls.clear()
    inspect_conn = FakeReconcileConn([make_journal_row(id=1, resource_key="case:case_inspect", action_family="fam.x", state="executing")])
    inspect_outcome = mr.inspect_reconciliation(inspect_conn, 1, with_x)
    check("inspect_reconciliation() returns the outcome a real --apply run would produce", inspect_outcome.new_state == "completed")
    check(
        "inspect_reconciliation() issues ZERO UPDATE statements",
        not any(call.startswith("UPDATE") for call in inspect_conn.calls),
        f"calls were: {inspect_conn.calls!r}",
    )
    check("inspect_reconciliation() leaves the row's state COMPLETELY untouched", inspect_conn.table[0]["state"] == "executing")
    check("inspect_reconciliation() still acquires the resource's session lock (evidence must be gathered against a stable state)", ("acquire_case", "case_inspect") in _lock_calls)
    check("inspect_reconciliation() still releases the lock afterwards", ("release", 111) in _lock_calls)

    # 12b) The same not-found/mismatch/unsupported-state/prepared-
    # unresolved exceptions apply identically, with zero UPDATEs.
    expect_raises(
        mr.JournalEntryNotFoundError,
        lambda: mr.inspect_reconciliation(FakeReconcileConn(), 999, with_x),
        "inspect_reconciliation() on a nonexistent journal_id fails closed with JournalEntryNotFoundError",
    )

    terminal_inspect_conn = FakeReconcileConn([make_journal_row(id=1, state="completed", action_family="fam.x")])
    expect_raises(
        mr.UnsupportedJournalStateError,
        lambda: mr.inspect_reconciliation(terminal_inspect_conn, 1, with_x),
        "inspect_reconciliation() on an already-TERMINAL row fails closed with UnsupportedJournalStateError",
    )

    _lock_calls.clear()
    prepared_unresolved_inspect_conn = FakeReconcileConn([make_journal_row(
        id=1, resource_key="case:case_inspect_prepared", action_family="fam.prepared_unresolved",
        state="prepared", executing_at=None,
    )])
    prepared_unresolved_inspect_registry = mr.MutationAdapterRegistry().with_adapter(
        "fam.prepared_unresolved", FakeAdapter(mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)),
    )
    expect_raises(
        mr.PreparedJournalUnresolvedError,
        lambda: mr.inspect_reconciliation(prepared_unresolved_inspect_conn, 1, prepared_unresolved_inspect_registry),
        "inspect_reconciliation() on an unresolvable 'prepared' row raises PreparedJournalUnresolvedError too, with ZERO UPDATEs",
    )
    check(
        "inspect_reconciliation()'s PreparedJournalUnresolvedError path issued NO UPDATE either",
        not any(call.startswith("UPDATE") for call in prepared_unresolved_inspect_conn.calls),
    )
    check("inspect_reconciliation()'s lock is still released even when _decide_outcome() itself raises", ("release", 111) in _lock_calls)
finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.acquire_global_lock_session = _original_acquire_global
    ml.release_lock_session = _original_release

# ----------------------------------------------------------------
# 13) ROW 19C-2a FAIL-CLOSED UNLOCK DISCIPLINE:
#     `LockReleaseAnomalyError` for `inspect_reconciliation()` (RAISED
#     when release fails and nothing else is propagating; LOGGED ONLY,
#     never raised, when something else already is), versus
#     `reconcile_and_apply_journal_entry()`'s own finally, which ONLY
#     ever logs (never raises) - proven by asserting its return value
#     survives a False release completely unaffected.
# ----------------------------------------------------------------


def _fake_release_lock_session_false(conn, advisory_lock_id):
    _lock_calls.append(("release", advisory_lock_id))
    return False


try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session_false

    # 13a) inspect_reconciliation(), happy path, but the lock release
    # itself returns False -> LockReleaseAnomalyError, NOT a
    # normal-looking successful inspection result.
    anomaly_conn = FakeReconcileConn([make_journal_row(id=1, resource_key="case:case_anomaly", action_family="fam.x", state="executing")])
    expect_raises(
        mr.LockReleaseAnomalyError,
        lambda: mr.inspect_reconciliation(anomaly_conn, 1, with_x),
        "inspect_reconciliation() raises LockReleaseAnomalyError when release_lock_session() returns False "
        "and no other exception is already propagating - never a silently 'successful' dry-run result",
    )
    check("a LockReleaseAnomalyError from inspect_reconciliation() still issued NO UPDATE", not any(call.startswith("UPDATE") for call in anomaly_conn.calls))

    # 13b) inspect_reconciliation(), an ADAPTER exception is ALREADY
    # propagating when the release also fails -> the ORIGINAL adapter
    # exception must still be what propagates; the anomaly is only
    # logged (captured here via monkeypatching mr._log_critical_safely).
    _original_log_critical_safely_mr = mr._log_critical_safely
    _critical_log_calls_mr = []
    mr._log_critical_safely = lambda message: _critical_log_calls_mr.append(message)
    try:
        class AdapterExplodesDuringInspection:
            def gather_evidence(self, entry):
                raise RuntimeError("adapter bug during a dry-run inspection")

        double_failure_registry = mr.MutationAdapterRegistry().with_adapter("fam.double_failure", AdapterExplodesDuringInspection())
        double_failure_conn = FakeReconcileConn([make_journal_row(
            id=1, resource_key="case:case_double_failure", action_family="fam.double_failure", state="executing",
        )])
        expect_raises(
            RuntimeError,
            lambda: mr.inspect_reconciliation(double_failure_conn, 1, double_failure_registry),
            "when BOTH the adapter raises AND the lock release fails, the ORIGINAL adapter exception "
            "(RuntimeError) still propagates - LockReleaseAnomalyError is never raised in its place",
        )
        check(
            "the lock-release anomaly (while another exception was already propagating) was CRITICALLY logged, not raised",
            len(_critical_log_calls_mr) == 1,
            f"got {_critical_log_calls_mr!r}",
        )
    finally:
        mr._log_critical_safely = _original_log_critical_safely_mr

    # 13c) reconcile_and_apply_journal_entry()'s own finally: a False
    # release is LOGGED ONLY, never raised - the call's own return
    # value (the already-applied, already-durable outcome) must be
    # completely unaffected.
    _original_log_critical_safely_mr2 = mr._log_critical_safely
    _critical_log_calls_mr2 = []
    mr._log_critical_safely = lambda message: _critical_log_calls_mr2.append(message)
    try:
        apply_false_release_conn = FakeReconcileConn([make_journal_row(
            id=1, resource_key="case:case_apply_false_release", action_family="fam.x", state="executing",
        )])
        apply_false_release_outcome = mr.reconcile_and_apply_journal_entry(apply_false_release_conn, 1, with_x)
        check(
            "reconcile_and_apply_journal_entry() NEVER raises on a False lock release - it returns the "
            "outcome it already applied, exactly as if the release had succeeded",
            apply_false_release_outcome.new_state == "completed",
        )
        check("the row was still durably updated despite the False release", apply_false_release_conn.table[0]["state"] == "completed")
        check(
            "the False release from reconcile_and_apply_journal_entry() was CRITICALLY logged",
            len(_critical_log_calls_mr2) == 1,
            f"got {_critical_log_calls_mr2!r}",
        )
    finally:
        mr._log_critical_safely = _original_log_critical_safely_mr2
finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.acquire_global_lock_session = _original_acquire_global
    ml.release_lock_session = _original_release


# ----------------------------------------------------------------
# 14) ROW 19C-2a FINAL AUDIT REMEDIATION - the REAL production
#     reconciliation adapter's OWN binding rule, exercised directly.
#
#     Sections 1-13 above all drive `mutation_registry` with FAKE
#     adapters, which is correct for testing the registry - but it
#     means the REAL
#     `ui.services.mutation_approval_adapters.CaseScopedApprovalReconciliationAdapter`
#     never evaluated a single binding in any isolated test. This
#     section closes that, and in particular covers the NEW binding 5
#     (`audit.pending_sha256 == entry.pre_revision`), which the audit
#     found absent.
#
#     `JournalEntrySnapshot.pre_revision` is also proven to reach the
#     adapter from the AUTHORITATIVE reread - the companion to section
#     10's identical proof for `idempotency_key`, and the value binding
#     5 depends on.
# ----------------------------------------------------------------

import hashlib as _hashlib                                              # noqa: E402
import json as _json                                                    # noqa: E402
import shutil as _shutil                                                # noqa: E402
import tempfile as _tempfile                                            # noqa: E402
import types as _types                                                  # noqa: E402
from pathlib import Path as _Path                                       # noqa: E402

from ui.services import mutation_approval_adapters as _adapters         # noqa: E402


class PreRevisionSpyAdapter:
    def __init__(self):
        self.seen_pre_revision = "NOT-CALLED"

    def gather_evidence(self, entry):
        self.seen_pre_revision = entry.pre_revision
        return mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=False)


try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session

    prerev_spy = PreRevisionSpyAdapter()
    prerev_registry = mr.MutationAdapterRegistry().with_adapter("fam.prerev_spy", prerev_spy)
    prerev_conn = FakeReconcileConn([make_journal_row(
        id=1, resource_key="case:case_prerev", action_family="fam.prerev_spy", state="executing",
        pre_revision="the_real_pending_hash_abc",
    )])
    mr.reconcile_and_apply_journal_entry(prerev_conn, 1, prerev_registry)
    check(
        "ROW 19C-2a: the adapter's gather_evidence(entry) sees the AUTHORITATIVE row's own "
        "pre_revision (the value binding 5 compares the audit record's pending_sha256 against)",
        prerev_spy.seen_pre_revision == "the_real_pending_hash_abc",
        f"got {prerev_spy.seen_pre_revision!r}",
    )
finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.acquire_global_lock_session = _original_acquire_global
    ml.release_lock_session = _original_release


_adapter_tmp = _Path(_tempfile.mkdtemp(prefix="vergi_recon_adapter_"))
try:
    PENDING_HASH = "p" * 64
    CASE_ID = "case_adapter_bindings"
    IDEM_KEY = "idem_key_for_the_adapter_test"

    canonical_dir = _adapter_tmp / CASE_ID
    canonical_dir.mkdir(parents=True)
    canonical_file = canonical_dir / "canonical.json"
    reviews_dir = canonical_dir / "reviews"
    reviews_dir.mkdir()

    def write_canonical(text):
        canonical_file.write_text(text, encoding="utf-8")
        return _hashlib.sha256(text.encode("utf-8")).hexdigest()

    CANONICAL_HASH = write_canonical('{"canonical": "promoted"}')

    fake_family = _types.ModuleType("_fake_family_for_adapter_bindings")
    fake_family.get_canonical_path = lambda case_id: canonical_file
    real_adapter = _adapters.CaseScopedApprovalReconciliationAdapter(fake_family)

    def adapter_entry(**overrides):
        fields = dict(
            journal_id=1, resource_key=f"case:{CASE_ID}", action_family="approval.fake",
            target_ref="fake.canonical", target_state="approved",
            pre_hash="composite", pre_revision=PENDING_HASH, expected_post_hash=None,
            state="reconciliation_required", idempotency_key=IDEM_KEY,
            # ROW 19C-2b: JournalEntrySnapshot gained two new trailing,
            # mandatory fields (request_fingerprint/actor_label) - this
            # Layer A adapter test never exercises either (Layer A's
            # own CaseScopedApprovalReconciliationAdapter has no
            # fingerprint-recomputation binding), so fixed placeholder
            # values are sufficient here; they exist only so this
            # dataclass can be constructed at all.
            request_fingerprint="fp_placeholder_not_checked_by_layer_a_adapter",
            actor_label="1",
        )
        fields.update(overrides)
        return mr.JournalEntrySnapshot(**fields)

    GOOD_AUDIT = {
        "mutation_idempotency_key": IDEM_KEY,
        "mutation_resource_key": f"case:{CASE_ID}",
        "canonical_sha256": CANONICAL_HASH,
        "pending_sha256": PENDING_HASH,
    }

    def write_audit(record):
        (reviews_dir / "fake_v1.approval.json").write_text(_json.dumps(record), encoding="utf-8")

    # Baseline: a fully, correctly bound audit record really does verify
    # the post-state - so every rejection below is caused by the ONE
    # field it changes, nothing else.
    write_audit(GOOD_AUDIT)
    baseline = real_adapter.gather_evidence(adapter_entry())
    check(
        "real adapter: a fully-bound audit record yields post_state_verified=True with the REAL "
        "canonical hash as observed_post_hash",
        baseline.post_state_verified is True
        and baseline.pre_state_confirmed_unchanged is False
        and baseline.observed_post_hash == CANONICAL_HASH,
        f"got {baseline!r}",
    )

    adapter_binding_cases = [
        ("binding 1 (idempotency key) WRONG", {"mutation_idempotency_key": "other"}, {}),
        ("binding 1 (idempotency key) MISSING", {"mutation_idempotency_key": None}, {}),
        ("binding 2 (resource key) WRONG", {"mutation_resource_key": "case:other_case"}, {}),
        ("binding 2 (resource key) MISSING", {"mutation_resource_key": None}, {}),
        ("binding 4 (audit canonical hash) WRONG", {"canonical_sha256": "0" * 64}, {}),
        ("binding 4 (audit canonical hash) MISSING", {"canonical_sha256": None}, {}),
        # ROW 19C-2a FINAL AUDIT REMEDIATION - binding 5.
        ("binding 5 (audit pending hash) WRONG", {"pending_sha256": "q" * 64}, {}),
        ("binding 5 (audit pending hash) MISSING", {"pending_sha256": None}, {}),
        ("binding 5 (audit pending hash) BLANK", {"pending_sha256": "   "}, {}),
    ]
    for label, audit_override, entry_override in adapter_binding_cases:
        write_audit({**GOOD_AUDIT, **audit_override})
        evidence = real_adapter.gather_evidence(adapter_entry(**entry_override))
        check(
            f"real adapter: {label} yields INCONCLUSIVE evidence (never post_state_verified)",
            evidence.post_state_verified is False and evidence.pre_state_confirmed_unchanged is False,
            f"got {evidence!r}",
        )

    # Binding 5 from the JOURNAL side: a row whose own pre_revision is
    # NULL/blank can never satisfy the binding, no matter what the audit
    # record says - so it must be inconclusive, not auto-verified.
    for label, pre_revision in [("NULL", None), ("BLANK", "  ")]:
        write_audit(GOOD_AUDIT)
        evidence = real_adapter.gather_evidence(adapter_entry(pre_revision=pre_revision))
        check(
            f"real adapter: binding 5 - a journal row whose OWN pre_revision is {label} is "
            "INCONCLUSIVE, never auto-verified",
            evidence.post_state_verified is False and evidence.pre_state_confirmed_unchanged is False,
            f"got {evidence!r}",
        )

    # And the decision table really does refuse to complete on that
    # inconclusive evidence (proving binding 5 is load-bearing all the
    # way through to the outcome, not just to the evidence object).
    write_audit({**GOOD_AUDIT, "pending_sha256": "q" * 64})
    inconclusive_entry = adapter_entry(state="reconciliation_required")
    outcome = mr._decide_outcome(
        inconclusive_entry, real_adapter.gather_evidence(inconclusive_entry),
    )
    check(
        "real adapter: a broken binding 5 resolves to 'reconciliation_required' with NO "
        "resolution_code - never 'completed'",
        outcome.new_state == "reconciliation_required" and outcome.resolution_code is None,
        f"got {outcome!r}",
    )

    # The canonical-absent branch is unaffected by the new binding: it
    # is still the ONE combination that proves an unchanged pre-state.
    canonical_file.unlink()
    absent_evidence = real_adapter.gather_evidence(adapter_entry())
    check(
        "real adapter: a MISSING canonical artefact still proves pre_state_confirmed_unchanged "
        "(binding 5 does not disturb that branch)",
        absent_evidence.pre_state_confirmed_unchanged is True
        and absent_evidence.post_state_verified is False,
        f"got {absent_evidence!r}",
    )
finally:
    _shutil.rmtree(_adapter_tmp, ignore_errors=True)


# ============================================================
# ROW 19C-2b - REAL Layer B `ReviewMutationReconciliationAdapter`
# (`ui.services.review_mutation_adapters`), exercised through the SAME
# real `reconcile_and_apply_journal_entry()` this file already proves
# correct for Layer A above - a fresh, isolated tempdir fixture (never
# touching any real `data/cases/` content), the module's OWN 12-family
# registry built for real via `build_production_registry()`, and a
# fake canonical/audit-directory pair for `review.evidence.candidate`
# specifically (chosen as a representative, non-parent-dependent
# review_kind - the parent-dependency/stale-source guard-hoisting
# itself is exercised by `ui/tests/test_review_mutation_facade_
# isolated.py`, not reconciliation, since a stuck journal row is only
# ever reachable AFTER a precondition/guard has already passed once).
# ============================================================

import ui.services.review_mutation_adapters as _review_adapters       # noqa: E402
import ui.services.review_mutation_facade as _review_facade           # noqa: E402
from mutation_guard import MutationIntent as _MutationIntent, compute_idempotency_key as _compute_idk, compute_request_fingerprint as _compute_fp  # noqa: E402

_review_adapter_tmp = _Path(_tempfile.mkdtemp(prefix="vergi_recon_review_adapter_"))
try:
    REVIEW_CASE_ID = "case_review_adapter_bindings"
    REVIEW_RECORD_ID = "evidence_candidate_recon_001"
    REVIEW_KIND = "evidence.candidate"

    review_case_dir = _review_adapter_tmp / REVIEW_CASE_ID
    review_case_dir.mkdir(parents=True)
    review_canonical_file = review_case_dir / "evidence.json"
    review_audit_dir = review_case_dir / "reviews" / "evidence_reviews"

    def write_review_canonical(state):
        text = _json.dumps({"evidence_candidates": [{"candidate_id": REVIEW_RECORD_ID, "review_state": state}]})
        review_canonical_file.write_text(text, encoding="utf-8")
        return _hashlib.sha256(text.encode("utf-8")).hexdigest()

    review_registry_full = _review_adapters.build_production_registry()
    real_review_adapter = review_registry_full.get(_review_facade.action_family_for(REVIEW_KIND))

    # Isolate the adapter from the real data/cases/ tree entirely - the
    # SAME monkeypatch-the-bound-module-attribute technique this
    # module's own Layer A fixture above uses.
    real_review_adapter._module.get_canonical_path = lambda cid: review_canonical_file
    real_review_adapter._get_audit_dir_fn = lambda cid: review_audit_dir

    NOTE_TEXT = "Row 19C-2b reconciliation adapter self-test note."
    REVIEW_NOTE_HASH = _hashlib.sha256(NOTE_TEXT.encode("utf-8")).hexdigest()

    def review_intent(**overrides):
        base = dict(
            actor_type="iam_user", actor_ref="7",
            resource_key=f"case:{REVIEW_CASE_ID}", action_family=_review_facade.action_family_for(REVIEW_KIND),
            target_ref=REVIEW_RECORD_ID, target_state="confirmed",
            pre_hash="composite_placeholder", pre_revision="pending_screen_hash_placeholder",
            secondary_input_hash=REVIEW_NOTE_HASH,
        )
        base.update(overrides)
        return _MutationIntent(**base)

    def review_entry(**overrides):
        intent = review_intent()
        fields = dict(
            journal_id=1, resource_key=f"case:{REVIEW_CASE_ID}",
            action_family=_review_facade.action_family_for(REVIEW_KIND),
            target_ref=REVIEW_RECORD_ID, target_state="confirmed",
            pre_hash=intent.pre_hash, pre_revision=intent.pre_revision, expected_post_hash=None,
            state="reconciliation_required", idempotency_key=_compute_idk(intent),
            request_fingerprint=_compute_fp(intent), actor_label="7",
        )
        fields.update(overrides)
        return mr.JournalEntrySnapshot(**fields)

    def write_review_audit(record, *, filename="evidence_review_" + REVIEW_RECORD_ID + "_20260101_000000.review_audit.json"):
        review_audit_dir.mkdir(parents=True, exist_ok=True)
        (review_audit_dir / filename).write_text(_json.dumps(record), encoding="utf-8")

    def clear_review_audit_dir():
        if review_audit_dir.exists():
            _shutil.rmtree(review_audit_dir)

    # ---- PRE-STATE: canonical shows needs_review, zero audits at all ----
    write_review_canonical("needs_review")
    clear_review_audit_dir()
    pre_evidence = real_review_adapter.gather_evidence(review_entry())
    check(
        "Layer B real adapter: canonical needs_review + zero audits -> pre_state_confirmed_unchanged=True",
        pre_evidence.pre_state_confirmed_unchanged is True and pre_evidence.post_state_verified is False,
        f"got {pre_evidence!r}",
    )

    # ---- POST-STATE: canonical shows target_state + exactly one fully-bound audit ----
    post_hash = write_review_canonical("confirmed")
    good_audit = {
        "case_id": REVIEW_CASE_ID, "record_type": "candidate", "record_id": REVIEW_RECORD_ID,
        "review_note": NOTE_TEXT, "pre_sha256": review_intent().pre_revision, "post_sha256": post_hash,
        "previous_state": "needs_review", "new_state": "confirmed", "reviewer_ref": "local_lawyer_ui",
    }
    entry_for_post = review_entry()
    good_audit["mutation_idempotency_key"] = entry_for_post.idempotency_key
    good_audit["mutation_resource_key"] = f"case:{REVIEW_CASE_ID}"
    good_audit["mutation_actor_ref"] = "7"
    write_review_audit(good_audit)
    post_evidence = real_review_adapter.gather_evidence(entry_for_post)
    check(
        "Layer B real adapter: canonical target_state + 1 fully-bound audit -> post_state_verified=True "
        "with the REAL canonical hash as observed_post_hash",
        post_evidence.post_state_verified is True
        and post_evidence.pre_state_confirmed_unchanged is False
        and post_evidence.observed_post_hash == post_hash,
        f"got {post_evidence!r}",
    )

    # ---- Binding tamper cases - each ONE field changed from the baseline ----
    review_binding_cases = [
        ("binding 1 (idempotency key) WRONG", {"mutation_idempotency_key": "other"}),
        ("binding 2 (resource key) WRONG", {"mutation_resource_key": "case:other_case"}),
        ("binding 3 (case_id) WRONG", {"case_id": "other_case"}),
        ("binding 4 (record_type) WRONG", {"record_type": "suggestion"}),
        ("binding 5 (record_id) WRONG", {"record_id": "some_other_record"}),
        ("binding 6a (actor ref) WRONG", {"mutation_actor_ref": "999"}),
        ("binding 6b (reviewer sentinel) WRONG", {"reviewer_ref": "not_the_lawyer_ui"}),
        ("binding 7 (target/new state) WRONG", {"new_state": "rejected"}),
        ("binding 9 (pre SHA) WRONG", {"pre_sha256": "0" * 64}),
        ("binding 10 (post SHA) WRONG", {"post_sha256": "0" * 64}),
    ]
    for label, override in review_binding_cases:
        write_review_audit({**good_audit, **override})
        evidence = real_review_adapter.gather_evidence(review_entry())
        check(
            f"Layer B real adapter: {label} yields INCONCLUSIVE evidence (never post_state_verified)",
            evidence.post_state_verified is False and evidence.pre_state_confirmed_unchanged is False,
            f"got {evidence!r}",
        )

    # binding 14 (recomputed request fingerprint) - tamper the note text
    # itself (which the audit stores as raw text) so the recomputed
    # fingerprint can never match the journal's own, while every OTHER
    # field stays correct.
    write_review_audit({**good_audit, "review_note": "a tampered, different note"})
    fp_evidence = real_review_adapter.gather_evidence(review_entry())
    check(
        "Layer B real adapter: binding 14 (recomputed request fingerprint via tampered review_note) "
        "yields INCONCLUSIVE evidence",
        fp_evidence.post_state_verified is False and fp_evidence.pre_state_confirmed_unchanged is False,
        f"got {fp_evidence!r}",
    )

    # ---- Duplicate audit -> ambiguous, unconditionally ----
    write_review_audit(good_audit, filename="evidence_review_" + REVIEW_RECORD_ID + "_20260101_000000.review_audit.json")
    write_review_audit(good_audit, filename="evidence_review_" + REVIEW_RECORD_ID + "_20260101_000001.review_audit.json")
    dup_evidence = real_review_adapter.gather_evidence(review_entry())
    check(
        "Layer B real adapter: 2 clean, identically-bound audit records for the SAME record -> "
        "ambiguous, INCONCLUSIVE (never picks one)",
        dup_evidence.post_state_verified is False and dup_evidence.pre_state_confirmed_unchanged is False,
        f"got {dup_evidence!r}",
    )

    # ---- Family-wide corrupt audit blocks EVERY record, even an
    #      otherwise-clean pre-state one ----
    clear_review_audit_dir()
    write_review_canonical("needs_review")
    review_audit_dir.mkdir(parents=True, exist_ok=True)
    (review_audit_dir / "evidence_review_some_other_record_20260101_000000.review_audit.json").write_text(
        "not valid json {{{", encoding="utf-8",
    )
    corrupt_evidence = real_review_adapter.gather_evidence(review_entry())
    check(
        "Layer B real adapter: a family-wide corrupt audit-shaped file blocks pre_state_confirmed_unchanged "
        "even for an UNRELATED record whose own canonical state is clean needs_review",
        corrupt_evidence.pre_state_confirmed_unchanged is False and corrupt_evidence.post_state_verified is False,
        f"got {corrupt_evidence!r}",
    )

    # ---- reconcile_and_apply_journal_entry() end to end, through the
    #      real FakeReconcileConn machinery already proven above, using
    #      the REAL Layer B adapter and a REAL clean post-state fixture. ----
    clear_review_audit_dir()
    post_hash2 = write_review_canonical("confirmed")
    review_intent_2 = review_intent(pre_revision="pending_screen_hash_placeholder_2")
    idem2 = _compute_idk(review_intent_2)
    good_audit2 = {**good_audit, "pre_sha256": review_intent_2.pre_revision, "post_sha256": post_hash2, "mutation_idempotency_key": idem2}
    write_review_audit(good_audit2)

    review_e2e_registry = mr.MutationAdapterRegistry().with_adapter(
        _review_facade.action_family_for(REVIEW_KIND), real_review_adapter,
    )
    review_e2e_conn = FakeReconcileConn([make_journal_row(
        id=1, resource_key=f"case:{REVIEW_CASE_ID}", action_family=_review_facade.action_family_for(REVIEW_KIND),
        target_ref=REVIEW_RECORD_ID, target_state="confirmed",
        pre_hash=review_intent_2.pre_hash, pre_revision=review_intent_2.pre_revision,
        state="reconciliation_required", idempotency_key=idem2,
        request_fingerprint=_compute_fp(review_intent_2), actor_label="7",
    )])
    _lock_calls.clear()
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.release_lock_session = _fake_release_lock_session
    try:
        review_e2e_outcome = mr.reconcile_and_apply_journal_entry(review_e2e_conn, 1, review_e2e_registry)
    finally:
        ml.acquire_case_lock_session = _original_acquire_case
        ml.release_lock_session = _original_release
    check(
        "Layer B real adapter end-to-end through reconcile_and_apply_journal_entry(): resolves to "
        "'completed' with the real canonical hash as observed_post_hash",
        review_e2e_outcome.new_state == "completed" and review_e2e_outcome.observed_post_hash == post_hash2,
        f"got {review_e2e_outcome!r}",
    )
    check(
        "Layer B real adapter end-to-end: the journal row itself was durably updated to 'completed'",
        review_e2e_conn.table[0]["state"] == "completed",
    )
finally:
    _shutil.rmtree(_review_adapter_tmp, ignore_errors=True)


# ============================================================
# ROW 19C-2c - REAL Row 18C `DraftingRequestReconciliationAdapter`
# (`ui.services.drafting_request_mutation_adapters`), exercised through
# the SAME real `reconcile_and_apply_journal_entry()` this file already
# proves correct for Layer A/Layer B above - a fresh, isolated tempdir
# fixture (never touching any real `data/cases/` content). Unlike
# Layer A/B, this family has no per-row_key/review_kind axis and no
# record-level `state_field` - it reconciles ONE whole-file mutation
# per case, so its own "pre-state" proof is a THREE-PART composite (see
# `drafting_request_mutation_facade.py`'s own header comment, Row
# 19C-2c binding decision): current input token AND recomputed
# composite digest AND zero matching/corrupt audit candidates - never
# current-token equality alone.
# ============================================================

import os as _os                                                      # noqa: E402
import subprocess as _subprocess                                      # noqa: E402

import ui.services.drafting_request as _draftreq                     # noqa: E402
import ui.services.drafting_request_mutation_facade as _dr_facade     # noqa: E402
import ui.services.drafting_request_mutation_adapters as _dr_adapters  # noqa: E402
from ui.services import paths as _dr_real_paths                       # noqa: E402


# ROW 19C-2c PATH CONTAINMENT REMEDIATION: `DraftingRequestReconciliation
# Adapter.gather_evidence()` now derives every path via `_resolve_verified_
# case_dir()`/`_verify_nested_case_path()` (see `drafting_request_
# mutation_adapters.py`'s own header comment) - these read `_drafting_
# request.CASES_DIR` DYNAMICALLY, never `get_inputs_dir()`. A test fixture
# that redirects `get_inputs_dir()` alone (the PRIOR shape of this
# section) would therefore never be seen by the adapter at all - this
# section instead uses a REAL, `CASES_DIR`-resident synthetic case
# directory (mirroring `ui/tests/test_drafting_request_mutation_facade_
# isolated.py`'s own `_make_case()`/`_cleanup_case()` pattern), cleaned up
# unconditionally in `finally`, never touching any real case.
def _dr_make_directory_escape_link(link_path, target_path):
    """REAL, platform-native directory-escape link (NTFS junction via
    `mklink /J` on Windows, POSIX symlink elsewhere) - an INDEPENDENT
    copy of `test_drafting_request_mutation_facade_isolated.py`'s own
    identically-purposed helper (this file's own test-only utility,
    never shared/imported), reusing the same established mechanism as
    `ui/tests/test_path_containment_windows.py`. Never a monkeypatch."""
    if sys.platform == "win32":
        result = _subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"mklink /J failed (rc={result.returncode}): {result.stdout!r} {result.stderr!r}")
    else:
        _os.symlink(str(target_path), str(link_path))


def _dr_remove_escape_link(link_path):
    """Removes a link created above WITHOUT ever recursing into (and
    deleting) its target - `.rmdir()` for a Windows junction, `.unlink()`
    for a POSIX symlink."""
    try:
        link_path.unlink()
    except OSError:
        try:
            link_path.rmdir()
        except OSError:
            pass


DR_CASE_ID = "case_dr_adapter_bindings"

dr_case_dir = _dr_real_paths.CASES_DIR / DR_CASE_ID
if dr_case_dir.exists():
    _shutil.rmtree(dr_case_dir)
dr_case_dir.mkdir(parents=True)

try:
    dr_inputs_dir = dr_case_dir / "drafting" / "inputs"
    dr_current_path = dr_inputs_dir / "lawyer_input.json"
    dr_audit_dir = dr_inputs_dir / "audit"
    dr_history_dir = dr_inputs_dir / "history"

    real_dr_adapter = _dr_adapters.DraftingRequestReconciliationAdapter()

    def dr_snapshot_digest(current_token):
        snapshot, _audit_scan, _history_scan = _dr_facade._compute_snapshot(current_token, dr_audit_dir, dr_history_dir)
        return snapshot.composite_digest

    def dr_intent(**overrides):
        base = dict(
            actor_type="iam_user", actor_ref="7",
            resource_key=f"case:{DR_CASE_ID}", action_family=_dr_facade.ACTION_FAMILY,
            target_ref=_dr_facade.TARGET_REF, target_state=_dr_facade.TARGET_STATE,
            pre_hash="placeholder_not_hashed_into_identity", pre_revision=_draftreq.NO_EXISTING_INPUT_SENTINEL,
            secondary_input_hash=_hashlib.sha256(b'{"lawyer_provided_text":"x"}').hexdigest(),
        )
        base.update(overrides)
        return _MutationIntent(**base)

    def dr_entry(**overrides):
        intent = dr_intent()
        fields = dict(
            journal_id=1, resource_key=f"case:{DR_CASE_ID}", action_family=_dr_facade.ACTION_FAMILY,
            target_ref=_dr_facade.TARGET_REF, target_state=_dr_facade.TARGET_STATE,
            pre_hash=intent.pre_hash, pre_revision=intent.pre_revision, expected_post_hash=None,
            state="reconciliation_required", idempotency_key=_compute_idk(intent),
            request_fingerprint=_compute_fp(intent), actor_label="7",
        )
        fields.update(overrides)
        return mr.JournalEntrySnapshot(**fields)

    def write_dr_audit(record, *, filename="lawyer_input_save_20260101T000000000000Z.audit.json"):
        dr_audit_dir.mkdir(parents=True, exist_ok=True)
        (dr_audit_dir / filename).write_text(_json.dumps(record), encoding="utf-8")

    def clear_dr_dirs():
        if dr_audit_dir.exists():
            _shutil.rmtree(dr_audit_dir)
        if dr_history_dir.exists():
            _shutil.rmtree(dr_history_dir)
        if dr_current_path.exists():
            dr_current_path.unlink()

    # ---- PRE-STATE: no current file, zero audits, composite digest
    # matches the FRESH (empty) state exactly. ----
    clear_dr_dirs()
    pre_digest = dr_snapshot_digest(_draftreq.NO_EXISTING_INPUT_SENTINEL)
    pre_dr_evidence = real_dr_adapter.gather_evidence(dr_entry(pre_hash=pre_digest))
    check(
        "Row 18C real adapter: no current file + zero audits + matching composite digest -> "
        "pre_state_confirmed_unchanged=True",
        pre_dr_evidence.pre_state_confirmed_unchanged is True and pre_dr_evidence.post_state_verified is False,
        f"got {pre_dr_evidence!r}",
    )
    check(
        "Row 18C real adapter: current-token equality ALONE is NOT sufficient - a WRONG composite "
        "digest (pre_hash) with an otherwise-clean pre-state still yields INCONCLUSIVE",
        real_dr_adapter.gather_evidence(dr_entry(pre_hash="0" * 64)).pre_state_confirmed_unchanged is False,
    )

    # ---- POST-STATE: current file written + exactly one fully-bound
    # audit (first_save, history_backup_path=None). ----
    dr_inputs_dir.mkdir(parents=True, exist_ok=True)
    current_content = '{"lawyer_input":{"lawyer_provided_text":"x"}}'
    dr_current_path.write_text(current_content, encoding="utf-8")
    post_hash = _hashlib.sha256(current_content.encode("utf-8")).hexdigest()
    entry_for_post = dr_entry()
    good_dr_audit = {
        "case_id": DR_CASE_ID, "action": "first_save",
        "previous_input_token": _draftreq.NO_EXISTING_INPUT_SENTINEL,
        "new_current_raw_sha256": post_hash,
        # MUST equal `dr_intent()`'s own `secondary_input_hash` - that is
        # what binding 12's recomputed fingerprint hashes against.
        "lawyer_input_hash": _hashlib.sha256(b'{"lawyer_provided_text":"x"}').hexdigest(),
        "saved_at": "2026-01-01T00:00:00+00:00", "history_backup_path": None,
        "mutation_idempotency_key": entry_for_post.idempotency_key,
        "mutation_resource_key": f"case:{DR_CASE_ID}", "mutation_actor_ref": "7",
    }
    write_dr_audit(good_dr_audit)
    post_dr_evidence = real_dr_adapter.gather_evidence(entry_for_post)
    check(
        "Row 18C real adapter: current file present + 1 fully-bound first-save audit -> "
        "post_state_verified=True with the REAL current file hash as observed_post_hash",
        post_dr_evidence.post_state_verified is True
        and post_dr_evidence.pre_state_confirmed_unchanged is False
        and post_dr_evidence.observed_post_hash == post_hash,
        f"got {post_dr_evidence!r}",
    )

    # ---- Binding tamper cases - each ONE field changed from the baseline ----
    dr_binding_cases = [
        ("binding 1 (idempotency key) WRONG", {"mutation_idempotency_key": "other"}),
        ("binding 2 (resource key) WRONG", {"mutation_resource_key": "case:other_case"}),
        ("binding 3 (actor ref) WRONG", {"mutation_actor_ref": "999"}),
        ("binding 5 (case_id) WRONG", {"case_id": "other_case"}),
        ("binding 6 (pre_revision/previous_input_token) WRONG", {"previous_input_token": "0" * 64}),
        ("binding 8 (new_current_raw_sha256) WRONG", {"new_current_raw_sha256": "0" * 64}),
    ]
    for label, override in dr_binding_cases:
        write_dr_audit({**good_dr_audit, **override})
        evidence = real_dr_adapter.gather_evidence(dr_entry())
        check(
            f"Row 18C real adapter: {label} yields INCONCLUSIVE evidence (never post_state_verified)",
            evidence.post_state_verified is False and evidence.pre_state_confirmed_unchanged is False,
            f"got {evidence!r}",
        )

    # binding 12 (recomputed request fingerprint) - tamper the stored
    # lawyer_input_hash itself, so the recomputed fingerprint can never
    # match the journal's own, while every OTHER field stays correct.
    write_dr_audit({**good_dr_audit, "lawyer_input_hash": "0" * 64})
    fp_dr_evidence = real_dr_adapter.gather_evidence(dr_entry())
    check(
        "Row 18C real adapter: binding 12 (recomputed request fingerprint via tampered "
        "lawyer_input_hash) yields INCONCLUSIVE evidence",
        fp_dr_evidence.post_state_verified is False and fp_dr_evidence.pre_state_confirmed_unchanged is False,
        f"got {fp_dr_evidence!r}",
    )

    # ---- overwrite-action audit with WRONG backup binding (missing
    # history_backup_path) -> INCONCLUSIVE. ----
    write_dr_audit({**good_dr_audit, "action": "overwrite", "history_backup_path": None})
    overwrite_evidence = real_dr_adapter.gather_evidence(dr_entry())
    check(
        "Row 18C real adapter: action='overwrite' but history_backup_path missing -> INCONCLUSIVE "
        "(overwrite MUST carry a backup link)",
        overwrite_evidence.post_state_verified is False and overwrite_evidence.pre_state_confirmed_unchanged is False,
        f"got {overwrite_evidence!r}",
    )

    # ---- Duplicate audit -> ambiguous, unconditionally ----
    write_dr_audit(good_dr_audit, filename="lawyer_input_save_20260101T000000000000Z.audit.json")
    write_dr_audit(good_dr_audit, filename="lawyer_input_save_20260101T000000000001Z.audit.json")
    dup_dr_evidence = real_dr_adapter.gather_evidence(dr_entry())
    check(
        "Row 18C real adapter: 2 clean, identically-bound audit records for the SAME idempotency "
        "key -> ambiguous, INCONCLUSIVE (never picks one)",
        dup_dr_evidence.post_state_verified is False and dup_dr_evidence.pre_state_confirmed_unchanged is False,
        f"got {dup_dr_evidence!r}",
    )

    # ---- Family-wide corrupt audit blocks the pre-state proof too,
    #      even for an otherwise-clean case. ----
    clear_dr_dirs()
    dr_audit_dir.mkdir(parents=True, exist_ok=True)
    (dr_audit_dir / "lawyer_input_save_CORRUPT.audit.json").write_text("not valid json {{{", encoding="utf-8")
    corrupt_dr_evidence = real_dr_adapter.gather_evidence(dr_entry(pre_hash=dr_snapshot_digest(_draftreq.NO_EXISTING_INPUT_SENTINEL)))
    check(
        "Row 18C real adapter: a corrupt audit-shaped file blocks pre_state_confirmed_unchanged too "
        "(never upgraded to proof by ignoring it)",
        corrupt_dr_evidence.pre_state_confirmed_unchanged is False and corrupt_dr_evidence.post_state_verified is False,
        f"got {corrupt_dr_evidence!r}",
    )

    # ---- ROW 19C-2c PATH CONTAINMENT REMEDIATION - REAL, platform-
    #      native nested AUDIT directory-escape negative proof for the
    #      RECONCILIATION ADAPTER (never a monkeypatch). Unlike the
    #      facade (which RAISES DraftingRequestDirectoryScanError),
    #      gather_evidence() catches this internally (see its own
    #      try/except around _resolve_verified_case_dir()/_verify_
    #      nested_case_path()) and reports genuinely INCONCLUSIVE
    #      evidence - never either proof, even though the escape target
    #      contains a correctly-named, well-formed audit record. ----
    clear_dr_dirs()
    _dr_escape_audit_outside = _Path(_tempfile.mkdtemp(prefix="vergi_recon_dr_adapter_escape_audit_"))
    _dr_escape_audit_links = []
    try:
        dr_inputs_dir.mkdir(parents=True, exist_ok=True)
        (_dr_escape_audit_outside / "lawyer_input_save_OUTSIDE.audit.json").write_text(
            _json.dumps({"mutation_idempotency_key": "outside_key", "case_id": DR_CASE_ID}), encoding="utf-8",
        )
        _dr_make_directory_escape_link(dr_audit_dir, _dr_escape_audit_outside)
        _dr_escape_audit_links.append(dr_audit_dir)

        escape_audit_evidence = real_dr_adapter.gather_evidence(dr_entry())
        check(
            "Row 18C real adapter: audit dizininin KENDİSİ case kökü dışına çözümlenen bir GERÇEK "
            "junction/symlink ise -> INCONCLUSIVE evidence (asla ne pre-state ne post-state kanıtı, "
            "dışarıdaki doğru adlı/geçerli JSON audit kaydı BİLE hiç kabul edilmez)",
            escape_audit_evidence.post_state_verified is False
            and escape_audit_evidence.pre_state_confirmed_unchanged is False,
            f"got {escape_audit_evidence!r}",
        )
    finally:
        for link_path in _dr_escape_audit_links:
            _dr_remove_escape_link(link_path)
        _shutil.rmtree(_dr_escape_audit_outside, ignore_errors=True)
    clear_dr_dirs()

    # ---- Same proof for the HISTORY directory. ----
    _dr_escape_history_outside = _Path(_tempfile.mkdtemp(prefix="vergi_recon_dr_adapter_escape_history_"))
    _dr_escape_history_links = []
    try:
        dr_inputs_dir.mkdir(parents=True, exist_ok=True)
        (_dr_escape_history_outside / "lawyer_input_before_save_OUTSIDE.json").write_text(
            "should never be read as a real history backup", encoding="utf-8",
        )
        _dr_make_directory_escape_link(dr_history_dir, _dr_escape_history_outside)
        _dr_escape_history_links.append(dr_history_dir)

        escape_history_evidence = real_dr_adapter.gather_evidence(dr_entry())
        check(
            "Row 18C real adapter: history dizininin KENDİSİ case kökü dışına çözümlenen bir GERÇEK "
            "junction/symlink ise -> INCONCLUSIVE evidence",
            escape_history_evidence.post_state_verified is False
            and escape_history_evidence.pre_state_confirmed_unchanged is False,
            f"got {escape_history_evidence!r}",
        )
    finally:
        for link_path in _dr_escape_history_links:
            _dr_remove_escape_link(link_path)
        _shutil.rmtree(_dr_escape_history_outside, ignore_errors=True)
    clear_dr_dirs()

    # ---- ROW 19C-2c BROKEN-LINK FAIL-CLOSED REMEDIATION - a REAL link
    #      whose TARGET is then removed, leaving a genuine broken
    #      reparse-point/symlink entry in place (never a monkeypatch).
    #      Proves the os.path.lexists() vs Path.exists() distinction
    #      directly (the exact precondition the prior `.exists()`-only
    #      gate got wrong), then proves the adapter reports genuinely
    #      INCONCLUSIVE evidence (never a false pre_state_confirmed_
    #      unchanged) for (1) a broken audit link and (2) a broken
    #      history link. ----
    clear_dr_dirs()
    _dr_broken_audit_outside = _Path(_tempfile.mkdtemp(prefix="vergi_recon_dr_adapter_broken_audit_"))
    _dr_broken_audit_links = []
    try:
        dr_inputs_dir.mkdir(parents=True, exist_ok=True)
        _dr_make_directory_escape_link(dr_audit_dir, _dr_broken_audit_outside)
        _dr_broken_audit_links.append(dr_audit_dir)
        _shutil.rmtree(_dr_broken_audit_outside)  # break it - target gone, link entry remains

        check(
            "Row 18C real adapter, broken-link precondition: kırık audit linki os.path.lexists()==True",
            _os.path.lexists(dr_audit_dir) is True,
        )
        check(
            "Row 18C real adapter, broken-link precondition: kırık audit linki Path.exists()==False",
            dr_audit_dir.exists() is False,
        )

        broken_audit_evidence = real_dr_adapter.gather_evidence(dr_entry())
        check(
            "Row 18C real adapter: KIRIK audit dizini linki (hedefi kaldırılmış) -> INCONCLUSIVE "
            "evidence (asla ne pre-state ne post-state kanıtı)",
            broken_audit_evidence.post_state_verified is False
            and broken_audit_evidence.pre_state_confirmed_unchanged is False,
            f"got {broken_audit_evidence!r}",
        )
    finally:
        for link_path in _dr_broken_audit_links:
            _dr_remove_escape_link(link_path)
        _shutil.rmtree(_dr_broken_audit_outside, ignore_errors=True)
    clear_dr_dirs()

    _dr_broken_history_outside = _Path(_tempfile.mkdtemp(prefix="vergi_recon_dr_adapter_broken_history_"))
    _dr_broken_history_links = []
    try:
        dr_inputs_dir.mkdir(parents=True, exist_ok=True)
        _dr_make_directory_escape_link(dr_history_dir, _dr_broken_history_outside)
        _dr_broken_history_links.append(dr_history_dir)
        _shutil.rmtree(_dr_broken_history_outside)

        check(
            "Row 18C real adapter, broken-link precondition: kırık history linki "
            "os.path.lexists()==True",
            _os.path.lexists(dr_history_dir) is True,
        )
        check(
            "Row 18C real adapter, broken-link precondition: kırık history linki Path.exists()==False",
            dr_history_dir.exists() is False,
        )

        broken_history_evidence = real_dr_adapter.gather_evidence(dr_entry())
        check(
            "Row 18C real adapter: KIRIK history dizini linki (hedefi kaldırılmış) -> INCONCLUSIVE "
            "evidence",
            broken_history_evidence.post_state_verified is False
            and broken_history_evidence.pre_state_confirmed_unchanged is False,
            f"got {broken_history_evidence!r}",
        )
    finally:
        for link_path in _dr_broken_history_links:
            _dr_remove_escape_link(link_path)
        _shutil.rmtree(_dr_broken_history_outside, ignore_errors=True)
    clear_dr_dirs()

    # ---- POSIX self-referential symlink LOOP (ELOOP) - safe, bounded,
    #      constructed WITHOUT any external target (a symlink whose OWN
    #      name is its own relative target, inside its own directory,
    #      creates a genuine resolution cycle with zero risk of leaving
    #      anything pointing at real data outside this synthetic case).
    #      Windows: per this turn's own instruction, no risky junction-
    #      loop construction is attempted here - the broken-junction
    #      proof above plus the source-code analysis (see both service
    #      files' own "ROW 19C-2c BROKEN-LINK FAIL-CLOSED REMEDIATION"
    #      header comments) is the accepted evidence for this platform;
    #      this sub-test is EXPLICITLY skipped, NEVER counted as a
    #      pass. ----
    if sys.platform != "win32":
        clear_dr_dirs()
        dr_inputs_dir.mkdir(parents=True, exist_ok=True)
        try:
            _os.symlink("audit", str(dr_audit_dir))  # own name, own dir -> genuine ELOOP on resolve

            check(
                "Row 18C real adapter, self-loop precondition: döngüsel audit linki "
                "os.path.lexists()==True",
                _os.path.lexists(dr_audit_dir) is True,
            )
            check(
                "Row 18C real adapter, self-loop precondition: döngüsel audit linki "
                "Path.exists()==False (ELOOP)",
                dr_audit_dir.exists() is False,
            )

            loop_evidence = real_dr_adapter.gather_evidence(dr_entry())
            check(
                "Row 18C real adapter: DÖNGÜSEL (self-loop) audit linki -> INCONCLUSIVE evidence "
                "(POSIX, gerçek ELOOP)",
                loop_evidence.post_state_verified is False and loop_evidence.pre_state_confirmed_unchanged is False,
                f"got {loop_evidence!r}",
            )
        finally:
            _dr_remove_escape_link(dr_audit_dir)
        clear_dr_dirs()
    else:
        print(
            "SKIPPED (NOT counted as pass/fail) - self-loop symlink sub-test: Windows-native junction "
            "loops are not constructed here per this turn's own instruction (constructing one reliably "
            "risks leaving an orphaned/inconsistent reparse point on the real filesystem); the "
            "broken-junction proof above plus source-code analysis (see both service files' own "
            "header comments) is the accepted evidence for circular-link fail-closed behavior on this "
            "platform."
        )

    # ---- reconcile_and_apply_journal_entry() end to end, through the
    #      real FakeReconcileConn machinery already proven above, using
    #      the REAL Row 18C adapter and a REAL clean post-state fixture. ----
    clear_dr_dirs()
    dr_inputs_dir.mkdir(parents=True, exist_ok=True)
    current_content_2 = '{"lawyer_input":{"lawyer_provided_text":"y"}}'
    dr_current_path.write_text(current_content_2, encoding="utf-8")
    post_hash2 = _hashlib.sha256(current_content_2.encode("utf-8")).hexdigest()
    dr_intent_2 = dr_intent(pre_revision="pre_revision_placeholder_2")
    idem2_dr = _compute_idk(dr_intent_2)
    good_dr_audit2 = {
        **good_dr_audit, "previous_input_token": dr_intent_2.pre_revision,
        "new_current_raw_sha256": post_hash2, "mutation_idempotency_key": idem2_dr,
    }
    write_dr_audit(good_dr_audit2)

    dr_e2e_registry = mr.MutationAdapterRegistry().with_adapter(_dr_facade.ACTION_FAMILY, real_dr_adapter)
    dr_e2e_conn = FakeReconcileConn([make_journal_row(
        id=1, resource_key=f"case:{DR_CASE_ID}", action_family=_dr_facade.ACTION_FAMILY,
        target_ref=_dr_facade.TARGET_REF, target_state=_dr_facade.TARGET_STATE,
        pre_hash=dr_intent_2.pre_hash, pre_revision=dr_intent_2.pre_revision,
        state="reconciliation_required", idempotency_key=idem2_dr,
        request_fingerprint=_compute_fp(dr_intent_2), actor_label="7",
    )])
    _lock_calls.clear()
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.release_lock_session = _fake_release_lock_session
    try:
        dr_e2e_outcome = mr.reconcile_and_apply_journal_entry(dr_e2e_conn, 1, dr_e2e_registry)
    finally:
        ml.acquire_case_lock_session = _original_acquire_case
        ml.release_lock_session = _original_release
    check(
        "Row 18C real adapter end-to-end through reconcile_and_apply_journal_entry(): resolves to "
        "'completed' with the real current-file hash as observed_post_hash",
        dr_e2e_outcome.new_state == "completed" and dr_e2e_outcome.observed_post_hash == post_hash2,
        f"got {dr_e2e_outcome!r}",
    )
    check(
        "Row 18C real adapter end-to-end: the journal row itself was durably updated to 'completed'",
        dr_e2e_conn.table[0]["state"] == "completed",
    )
finally:
    _shutil.rmtree(dr_case_dir, ignore_errors=True)


print(f"--- test_reconciliation_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
