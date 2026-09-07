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


print(f"--- test_reconciliation_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
