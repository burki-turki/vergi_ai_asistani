# ============================================================
# VERGİ AI - MUTATION RECONCILIATION ADAPTER REGISTRY (Row 19C-1,
# ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION)
#
# Defines the Protocol every action-specific "reconciliation adapter"
# must satisfy, plus a small, explicit registry mapping
# `action_family` -> adapter instance. Row 19C-1 registers NO
# production adapter here - every production writer (approval_
# registry.case_scoped_approve, review_registry.apply_transition,
# drafting_request.save_lawyer_input, and all CLI-only entry points)
# stays entirely unconnected to this module this turn; only FAKE
# adapters exist, in ui/tests/test_reconciliation_isolated.py.
#
# DESIGN CONSTRAINTS (all per this turn's approved contract):
#   - No global mutable registration and no import-time side effect:
#     importing this module registers NOTHING. A registry is built
#     explicitly by the caller via `MutationAdapterRegistry(...)` /
#     `.with_adapter(...)`, constructor-injected - never a decorator
#     or a module-level dict mutated by other modules importing this
#     one.
#   - Duplicate action_family registration and an unknown action_family
#     lookup are BOTH fail-closed (raise), never silently overwritten
#     or silently treated as "nothing to reconcile".
#
# ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION - WHAT CHANGED AND WHY
# ----------------------------------------------------------------
# An independent, read-only review found this module's ORIGINAL two-
# function split (`reconcile_journal_entry()` deciding, a SEPARATE
# `apply_reconciliation_outcome()` writing) unsafe in three ways, all
# fixed here:
#   1. `reconcile_journal_entry()` trusted a caller-supplied
#      `JournalEntrySnapshot` as its decision input, never re-reading
#      the row from the database itself - a caller with a stale or
#      simply wrong snapshot could steer a real decision.
#   2. The lock was RELEASED at the end of `reconcile_journal_entry()`,
#      before the caller ever called `apply_reconciliation_outcome()` -
#      leaving a real, unlocked window between "decide" and "write"
#      during which another session could act on the same row.
#   3. `apply_reconciliation_outcome()`'s guarded UPDATE never checked
#      `cur.rowcount` - a zero-row UPDATE (the row was no longer in a
#      resolvable state by the time the UPDATE ran) was silently
#      indistinguishable from success.
#
# The single public entry point below,
# `reconcile_and_apply_journal_entry()`, replaces BOTH former public
# functions and closes all three gaps at once:
#   - it takes only a bare `journal_id` (never a caller-supplied
#     snapshot as a decision input) and re-reads the row from the
#     database ITSELF, authoritatively, AFTER the lock is held;
#   - decision and write happen inside ONE call, under the SAME held
#     lock, released only in a `finally` AFTER the write - there is no
#     public, lock-free way to reach either the decision or the write
#     step in isolation any more;
#   - the guarded UPDATE's `cur.rowcount` is checked and a rowcount
#     other than exactly 1 raises `ReconciliationApplyFailedError`
#     rather than being treated as a silent no-op.
#
# It also closes the separate "a crash between `prepared`'s own commit
# and the `executing` transition permanently blocks this resource"
# gap: `prepared` is now a THIRD supported state (see
# `_SUPPORTED_UNRESOLVED_STATES` below) - resolved to `failed` ONLY
# when the SAME adapter evidence proves the pre-state was never
# touched (the writer, by the coordinator's own ordering contract, was
# never even invoked for a row that never left `prepared`). A
# `prepared` row is NEVER auto-completed, and (ROW 19C-1 FINAL
# PREPARED-INCONCLUSIVE SEMANTICS CORRECTION) is also never moved to
# `reconciliation_required` - doing so would require fabricating an
# `executing_at` timestamp for a writer invocation that provably never
# happened (0003_mutation_journal.sql's own CHECK constraint requires
# `executing_at IS NOT NULL` for that state unconditionally). Every
# OTHER evidence combination against a `prepared`-origin row instead
# raises `PreparedJournalUnresolvedError`, leaving the row completely
# untouched (still `prepared`, no UPDATE issued at all) - the resource
# stays gated and reconciliation may be retried later with stronger
# evidence - see `_decide_outcome()`'s own comment.
#
# `reconcile_and_apply_journal_entry()`:
#   - reads `resource_key` for `journal_id` BEFORE taking any lock
#     (fail-closed immediately if the row does not even exist yet) -
#     this pre-lock read exists ONLY to decide WHICH lock to take
#     (`case:` -> `acquire_case_lock_session`, anything else ->
#     `acquire_global_lock_session`), never as a decision input;
#   - acquires that SAME session-level resource lock the coordinator
#     itself uses (ui.services.mutation_lock.acquire_case_lock_session /
#     acquire_global_lock_session - never re-implemented here);
#   - re-reads the FULL row authoritatively, under the lock, by
#     `journal_id` - fails closed if the row is gone, and fails closed
#     (`ResourceKeyMismatchError`) if its `resource_key` now differs
#     from the pre-lock read (structurally unreachable today - no code
#     path ever updates `resource_key` - but never assumed from
#     outside this module's own scope);
#   - only ever acts on journal rows in a SUPPORTED unresolved state
#     (`prepared`, `executing`, or `reconciliation_required` - NEVER a
#     terminal `completed`/`failed` row, which needs no reconciliation
#     and must not receive it);
#   - resolves the adapter using the AUTHORITATIVE `action_family` just
#     read (never one the caller might have assumed) and asks it for
#     domain evidence;
#   - converts that evidence into exactly one outcome (see
#     `_decide_outcome()`), applies it with the SAME lock still held,
#     and only THEN releases the lock;
#   - never stores free text or a raw exception - only fixed codes and
#     the same identity/resource/hash/timestamp shape the coordinator
#     itself writes.
# ============================================================

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mutation_guard import (  # noqa: E402
    RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
    RESOLUTION_CODE_FAILED_PRE_STATE_UNCHANGED,
    RESOLUTION_CODE_FAILED_PREPARED_NEVER_EXECUTED,
)

from . import mutation_lock as _mutation_lock


class UnknownActionFamilyError(Exception):
    """Raised when `MutationAdapterRegistry.get(action_family)` is
    called with an `action_family` no adapter was registered for -
    fail-closed: reconciliation for an unrecognized action family MUST
    stop here, never guess at a "close enough" adapter."""


class DuplicateActionFamilyError(Exception):
    """Raised by `MutationAdapterRegistry.with_adapter()` when
    `action_family` is already registered - silently overwriting a
    registered adapter would let a later, unrelated import shadow an
    earlier, deliberate registration without anyone noticing."""


@dataclass(frozen=True)
class JournalEntrySnapshot:
    """The read-only slice of one `mutation.mutation_journal` row that
    a reconciliation adapter needs - deliberately narrower than the
    full row (no internal ids beyond what is needed, no free text
    ever, since there is none in the table to begin with)."""

    journal_id: int
    resource_key: str
    action_family: str
    target_ref: str
    target_state: str | None
    pre_hash: str | None
    pre_revision: str | None
    expected_post_hash: str | None
    state: str


@dataclass(frozen=True)
class ReconciliationEvidence:
    """What an adapter reports back, after independently inspecting
    the actual domain artefact/audit trail - NEVER derived from the
    journal row's own `expected_post_hash` (that would be circular;
    the whole point is independent verification)."""

    # Exactly one of the two proofs below may be conclusively true;
    # both False means "inconclusive" (-> reconciliation_required).
    post_state_verified: bool
    pre_state_confirmed_unchanged: bool
    observed_post_hash: str | None = None


class ReconciliationAdapter(Protocol):
    """One adapter per `action_family`. Implemented entirely OUTSIDE
    this module (a real one is Row 19C-2+ scope, connected to one
    actual production writer's own domain validator/audit trail) -
    this module only defines the shape and orchestrates against it."""

    def gather_evidence(self, entry: JournalEntrySnapshot) -> ReconciliationEvidence:
        """MUST perform no file/DB mutation of any kind - reconciliation
        evidence-gathering is read-only, by contract. Must not raise
        for a merely-inconclusive case (return
        ReconciliationEvidence(False, False, ...) instead) - raising is
        reserved for a genuine adapter-internal bug."""
        ...


class MutationAdapterRegistry:
    """Explicit, constructor-injected mapping of `action_family` ->
    `ReconciliationAdapter`. No module-level/global mutable state -
    every instance starts empty; `with_adapter()` returns a NEW
    registry (does not mutate `self`), so a registry can be built up
    once, explicitly, and then treated as immutable."""

    def __init__(self, adapters: dict[str, ReconciliationAdapter] | None = None):
        self._adapters: dict[str, ReconciliationAdapter] = dict(adapters or {})

    def with_adapter(self, action_family: str, adapter: ReconciliationAdapter) -> "MutationAdapterRegistry":
        if action_family in self._adapters:
            raise DuplicateActionFamilyError(
                f"action_family={action_family!r} is already registered - refusing to silently overwrite it"
            )
        return MutationAdapterRegistry({**self._adapters, action_family: adapter})

    def get(self, action_family: str) -> ReconciliationAdapter:
        adapter = self._adapters.get(action_family)
        if adapter is None:
            raise UnknownActionFamilyError(
                f"no reconciliation adapter registered for action_family={action_family!r}"
            )
        return adapter

    def known_action_families(self) -> frozenset[str]:
        return frozenset(self._adapters)


_SUPPORTED_UNRESOLVED_STATES = frozenset({"prepared", "executing", "reconciliation_required"})


@dataclass(frozen=True)
class ReconciliationOutcome:
    """The result of one `reconcile_journal_entry()` call - mirrors
    exactly the columns `ui.services.mutation_coordinator` itself
    would write for `completed`/`failed`, so the caller can apply this
    outcome to the journal row with the SAME write path the
    coordinator uses (this module does not perform the DB write
    itself - see the module docstring: it hands back a decision, the
    caller commits it, keeping this core testable with fake adapters
    and no database at all)."""

    new_state: str  # 'completed' | 'failed' | 'reconciliation_required'
    resolution_code: str | None
    observed_post_hash: str | None


class UnsupportedJournalStateError(Exception):
    """Raised when `reconcile_and_apply_journal_entry()` is asked to
    act on a journal row whose AUTHORITATIVE, lock-held `state` is not
    one of the three supported unresolved states (`prepared`,
    `executing`, `reconciliation_required`) - in particular, a
    TERMINAL state (`completed`/`failed`) that has already been
    resolved does not need, and must not receive, reconciliation.
    Checked against the freshly-reread row, never against anything a
    caller might have believed beforehand."""


class JournalEntryNotFoundError(Exception):
    """Raised when no `mutation.mutation_journal` row exists for the
    given `journal_id` - checked both BEFORE any lock is acquired (the
    pre-lock resource_key read finds nothing, so there is nothing to
    lock for) and, again, AFTER the lock is held (in case the row
    vanished between those two reads - no code path in this project
    ever deletes a journal row, but this function does not assume that
    from outside its own scope; fail-closed either way)."""


class ResourceKeyMismatchError(Exception):
    """Raised when the AUTHORITATIVE, lock-held reread of a journal
    row's `resource_key` does not match the `resource_key` read BEFORE
    the lock was acquired (that earlier read exists ONLY to decide
    which lock to take). No code path anywhere in this project ever
    updates `resource_key` after a row is inserted, so this should be
    structurally unreachable - it exists purely as a fail-closed
    backstop, in the same spirit as
    `ui.services.mutation_lock.UnknownMutationResourceError`, never as
    an expected branch."""


class ReconciliationApplyFailedError(Exception):
    """Raised when the guarded UPDATE that applies a reconciliation
    outcome affects a `cur.rowcount` other than exactly 1 - NEVER
    treated as a silent success or a harmless no-op. This UPDATE runs
    while this process still holds the SAME session-level resource
    lock acquired for this row's `resource_key`, immediately after
    re-reading that row's own current state under that same lock - so
    a rowcount of zero here means the row was changed by something
    outside this module's own locking discipline between that
    authoritative reread and this UPDATE (there is no code path in
    this project that should be able to do that, but this is the
    fail-closed backstop for if it ever somehow happens - e.g. an
    out-of-band manual UPDATE bypassing the advisory lock entirely,
    which PostgreSQL's advisory locks do not themselves prevent, since
    they are cooperative, not mandatory). The row's own state is left
    exactly as that failed UPDATE left it (its original, unresolved
    value - the UPDATE affected zero rows, so it changed nothing), and
    the lock is still released via the caller's `finally`."""


class PreparedJournalUnresolvedError(Exception):
    """ROW 19C-1 FINAL PREPARED-INCONCLUSIVE SEMANTICS CORRECTION -
    raised by `_decide_outcome()` when reconciling a `prepared`-origin
    row (the writer was NEVER invoked for it - see
    `_SUPPORTED_UNRESOLVED_STATES`/`_decide_outcome()`'s own docstring)
    and the adapter's evidence does NOT conclusively prove
    `pre_state_confirmed_unchanged=True` AND `post_state_verified=
    False` - the ONE combination that legitimately resolves a
    `prepared` row, to `failed` (`RESOLUTION_CODE_FAILED_PREPARED_
    NEVER_EXECUTED`). Every other combination - insufficient evidence
    (both proofs False), a contradiction (both proofs True), or a
    suspicious `post_state_verified=True` claim against a row whose
    writer never ran - used to fall through to `reconciliation_
    required`, but that state's own CHECK constraint requires
    `executing_at IS NOT NULL` unconditionally, which forced that path
    to fabricate an execution timestamp for an execution that provably
    never happened - exactly the same category of falsehood the
    earlier `prepared -> failed-never-executed` timestamp correction
    already eliminated for the `failed` outcome. This exception
    extends that same principle to its logical conclusion: not just
    "the wrong outcome must never fabricate a timestamp" but "no
    outcome may be manufactured at all" for a row whose writer never
    ran and whose evidence does not conclusively clear it.

    Raised from inside `_decide_outcome()`, i.e. BEFORE
    `_apply_outcome_under_lock()` is ever called - so no UPDATE is
    issued, the row is left EXACTLY as it was (still `prepared`,
    `executing_at`/`resolved_at`/`resolution_code` all untouched), and
    `reconcile_and_apply_journal_entry()`'s own `finally` still
    releases the session lock normally, exactly as for any other
    exception raised between acquiring the lock and applying an
    outcome. The resource remains gated (`mutation_coordinator.py`'s
    own gate for a `prepared` row is unchanged by this correction)
    until a LATER reconciliation attempt, with stronger adapter
    evidence, proves the pre-state one way or the other."""


def _read_resource_key_only(conn, journal_id: int) -> str | None:
    """The PRE-LOCK read: fetches ONLY `resource_key`, and ONLY to
    decide which lock `reconcile_and_apply_journal_entry()` must take.
    Never used as a decision input - see that function's own docstring
    and this module's header comment."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT resource_key FROM mutation.mutation_journal WHERE id = %s",
            (journal_id,),
        )
        row = cur.fetchone()
    return None if row is None else row[0]


def _read_authoritative_entry(conn, journal_id: int) -> JournalEntrySnapshot | None:
    """The AUTHORITATIVE, lock-held read: fetches the full row shape a
    `ReconciliationAdapter` needs, by `journal_id`, fresh - called only
    AFTER `reconcile_and_apply_journal_entry()` already holds the
    resource's session lock. This is the ONLY source of truth for the
    decision that follows; no caller-supplied value is ever
    substituted for any part of it."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, resource_key, action_family, target_ref, target_state, "
            "pre_hash, pre_revision, expected_post_hash, state "
            "FROM mutation.mutation_journal WHERE id = %s",
            (journal_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return JournalEntrySnapshot(*row)


def _acquire_resource_lock_for(conn, resource_key: str) -> int:
    if resource_key.startswith("case:"):
        case_id = resource_key[len("case:"):]
        return _mutation_lock.acquire_case_lock_session(conn, case_id)
    return _mutation_lock.acquire_global_lock_session(conn, resource_key)


def _decide_outcome(entry: JournalEntrySnapshot, evidence: ReconciliationEvidence) -> ReconciliationOutcome:
    """Pure decision table - no I/O, no lock awareness (the caller
    already holds the lock and already fetched `entry`/`evidence`
    authoritatively). Split out from `reconcile_and_apply_journal_entry()`
    only so the `prepared`-origin branch and the
    `executing`/`reconciliation_required`-origin branch can each be
    read as their own small, complete rule instead of one tangled
    conditional."""

    if entry.state == "prepared":
        # The writer boundary was NEVER crossed for this row (see
        # mutation_coordinator.py's own ordering contract: the writer
        # callback is invoked only AFTER `executing` is durably
        # written) - so `completed` can NEVER be granted here, no
        # matter what the adapter reports. Only a PROVEN-unchanged
        # pre-state resolves it, and only to `failed` (this row never
        # even attempted anything, so "failed" here means "this
        # attempt is permanently abandoned, and nothing happened",
        # exactly like any other `failed` row). A `post_state_verified`
        # claim against a row whose writer never ran is itself
        # suspicious/contradictory - treated the same as "insufficient
        # evidence", never trusted to auto-complete.
        if evidence.pre_state_confirmed_unchanged and not evidence.post_state_verified:
            return ReconciliationOutcome(
                "failed", RESOLUTION_CODE_FAILED_PREPARED_NEVER_EXECUTED, evidence.observed_post_hash,
            )
        # ROW 19C-1 FINAL PREPARED-INCONCLUSIVE SEMANTICS CORRECTION:
        # every OTHER evidence combination against a `prepared`-origin
        # row (insufficient - both proofs False; contradictory - both
        # proofs True; or a suspicious post_state_verified=True claim
        # against a row whose writer never ran) used to fall through
        # to `reconciliation_required` - but that state's own CHECK
        # constraint requires `executing_at IS NOT NULL`
        # unconditionally, which forced this branch to fabricate an
        # execution timestamp via `COALESCE(executing_at, now())` for a
        # writer invocation that provably never happened. Raising here
        # instead means the caller never reaches
        # `_apply_outcome_under_lock()` at all for this row: no UPDATE
        # is issued, the row is left EXACTLY as `prepared`
        # (`executing_at`/`resolved_at`/`resolution_code` untouched),
        # and `reconcile_and_apply_journal_entry()`'s own `finally`
        # still releases the lock normally - see
        # `PreparedJournalUnresolvedError`'s own docstring.
        raise PreparedJournalUnresolvedError(
            f"journal_id={entry.journal_id}: 'prepared'-origin row's adapter evidence "
            f"(post_state_verified={evidence.post_state_verified!r}, "
            f"pre_state_confirmed_unchanged={evidence.pre_state_confirmed_unchanged!r}) does not "
            "conclusively prove the pre-state was unchanged - the ONLY combination that legitimately "
            "resolves a row whose writer was never invoked. Refusing to fabricate a resolution or an "
            "execution timestamp; the row is left exactly as 'prepared', completely unresolved, no "
            "UPDATE issued - retry reconciliation later with stronger evidence."
        )

    # entry.state in ('executing', 'reconciliation_required') - the
    # writer boundary WAS crossed; unchanged decision table from the
    # original Row 19C-1 design.
    if evidence.post_state_verified and evidence.pre_state_confirmed_unchanged:
        # An adapter reporting BOTH proofs true is a contradiction
        # (both "the new state was reached" and "nothing changed"
        # cannot both be conclusively true) - treated as
        # inconclusive/divergent, never resolved by picking one.
        return ReconciliationOutcome("reconciliation_required", None, evidence.observed_post_hash)

    if evidence.post_state_verified:
        return ReconciliationOutcome(
            "completed", RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED, evidence.observed_post_hash,
        )

    if evidence.pre_state_confirmed_unchanged:
        return ReconciliationOutcome(
            "failed", RESOLUTION_CODE_FAILED_PRE_STATE_UNCHANGED, evidence.observed_post_hash,
        )

    return ReconciliationOutcome("reconciliation_required", None, evidence.observed_post_hash)


def _apply_outcome_under_lock(conn, journal_id: int, outcome: ReconciliationOutcome) -> None:
    """PRIVATE - deliberately not exported. Must be called ONLY while
    the caller (`reconcile_and_apply_journal_entry()`) still holds the
    SAME session-level resource lock it acquired for this row - there
    is no supported, lock-free way to apply a `ReconciliationOutcome`
    (see this module's own header comment on why the original public
    `apply_reconciliation_outcome()` was removed).

    Guards each UPDATE to exactly the origin state(s) `_decide_outcome()`
    can legitimately produce that outcome from. `prepared` is one of
    the three states `reconcile_and_apply_journal_entry()` may
    authoritatively read (see `_SUPPORTED_UNRESOLVED_STATES`), but
    (ROW 19C-1 FINAL PREPARED-INCONCLUSIVE SEMANTICS CORRECTION) this
    function itself is now reached for a `prepared`-origin row ONLY
    via the dedicated prepared-never-executed branch below -
    `_decide_outcome()` raises `PreparedJournalUnresolvedError` for
    every other `prepared`-origin evidence combination, before this
    function is ever called at all.

    ROW 19C-1 TIMESTAMP SEMANTICS CORRECTION - `executing_at` records
    WHEN THE WRITER WAS ACTUALLY INVOKED, never a reconciliation
    bookkeeping timestamp. This function has THREE distinct branches,
    not two, specifically so it never fabricates one:
      - `reconciliation_required`: `executing_at` is backfilled via
        `COALESCE(executing_at, now())` - this row's outcome remains
        genuinely AMBIGUOUS (nothing was proven either way),
        0003_mutation_journal.sql's own CHECK constraint requires
        `executing_at IS NOT NULL` for this state unconditionally, and
        this timestamp is understood as "when this ambiguous row was
        last touched", not a claim about writer execution. The WHERE
        guard is `state IN ('executing', 'reconciliation_required')`
        ONLY (ROW 19C-1 FINAL PREPARED-INCONCLUSIVE SEMANTICS
        CORRECTION: `'prepared'` was removed from this list - a
        `prepared`-origin row can no longer reach this branch at all;
        `_decide_outcome()` now raises `PreparedJournalUnresolvedError`
        instead of ever producing a `reconciliation_required` outcome
        for one, specifically so this exact fabrication never happens
        for a row whose writer was never invoked).
      - `failed` with `resolution_code ==
        RESOLUTION_CODE_FAILED_PREPARED_NEVER_EXECUTED` (reachable
        ONLY from an authoritative `prepared` origin - see
        `_decide_outcome()`): `executing_at` is NEVER touched here and
        stays exactly what it already was - NULL, since a `prepared`
        row's own INSERT never sets it. The WHERE guard is narrowed to
        `state = 'prepared'` (not the general three-state list) since
        this specific outcome is structurally only ever produced for a
        `prepared`-origin row; 0003's own
        `mutation_journal_executing_at_matches_state` and
        `mutation_journal_prepared_never_executed_code_is_exclusive`
        CHECK constraints both enforce this at the database level too,
        independent of this function ever getting it right.
      - `completed`, or `failed` with any OTHER resolution_code (a row
        that DID cross the writer boundary - originates from
        `executing`/`reconciliation_required` only, per
        `_decide_outcome()`): `executing_at` is backfilled via
        `COALESCE(...)` exactly as before - defensive-in-depth only,
        since a row reaching this branch already has one set (it
        already passed through `_mark_executing()`).

    Deliberately SEPARATE from `ui.services.mutation_coordinator`'s own
    `_mark_completed`/`_mark_reconciliation_required`: those write the
    COORDINATOR's OWN, directly-proven outcomes (no `resolution_code`
    - a `completed` row from `run_mutation()` itself was never
    reconciled, it was proven by its own writer's success); a
    RECONCILED outcome always carries a `resolution_code` (for
    `completed`/`failed`) and NEVER sets `failure_code` - two
    different, non-overlapping provenances for a terminal state, by
    design (see 0003_mutation_journal.sql's column comments).

    Requires `cur.rowcount == 1` - anything else raises
    `ReconciliationApplyFailedError` (see that class's own docstring)
    rather than being treated as a silent success or no-op."""
    with conn.cursor() as cur:
        if outcome.new_state == "reconciliation_required":
            cur.execute(
                "UPDATE mutation.mutation_journal SET state = 'reconciliation_required', "
                "executing_at = COALESCE(executing_at, now()) "
                "WHERE id = %s AND state IN ('executing', 'reconciliation_required')",
                (journal_id,),
            )
        elif outcome.new_state == "failed" and outcome.resolution_code == RESOLUTION_CODE_FAILED_PREPARED_NEVER_EXECUTED:
            # The writer was NEVER invoked for this row - executing_at
            # must stay exactly what it already is (NULL). No
            # COALESCE, no fabricated timestamp: a legal/security
            # journal must never record an execution timestamp for an
            # execution that never happened. The WHERE guard is
            # deliberately narrower than the other branches (`state =
            # 'prepared'` only) - this outcome is only ever legitimately
            # produced against a 'prepared' authoritative row (see
            # _decide_outcome()); if it is ever somehow produced against
            # anything else, this guard's rowcount will correctly be 0,
            # raising ReconciliationApplyFailedError below rather than
            # silently applying a contradictory combination.
            cur.execute(
                "UPDATE mutation.mutation_journal "
                "SET state = 'failed', resolution_code = %s, observed_post_hash = %s, resolved_at = now() "
                "WHERE id = %s AND state = 'prepared'",
                (outcome.resolution_code, outcome.observed_post_hash, journal_id),
            )
        elif outcome.new_state in ("completed", "failed"):
            # Reachable only for a row that already crossed the writer
            # boundary (originates from 'executing'/
            # 'reconciliation_required' - never 'prepared', per
            # _decide_outcome()) - executing_at is already set on any
            # such row; COALESCE is defensive-in-depth only, never
            # expected to actually fabricate anything here.
            cur.execute(
                "UPDATE mutation.mutation_journal "
                "SET state = %s, resolution_code = %s, observed_post_hash = %s, resolved_at = now(), "
                "    executing_at = COALESCE(executing_at, now()) "
                "WHERE id = %s AND state IN ('executing', 'reconciliation_required')",
                (outcome.new_state, outcome.resolution_code, outcome.observed_post_hash, journal_id),
            )
        else:
            raise ValueError(f"unexpected ReconciliationOutcome.new_state: {outcome.new_state!r}")

        if cur.rowcount != 1:
            raise ReconciliationApplyFailedError(
                f"reconciliation UPDATE for journal_id={journal_id} affected {cur.rowcount} row(s) "
                "(expected exactly 1) - refusing to treat this as success; the row's state is left "
                "exactly as it was before this UPDATE"
            )


def reconcile_and_apply_journal_entry(
    conn,
    journal_id: int,
    registry: MutationAdapterRegistry,
) -> ReconciliationOutcome:
    """The ONE public reconciliation entry point - acquires the lock,
    authoritatively re-reads the row, decides, applies the decision,
    and only then releases the lock, ALL under one call. There is no
    supported way to do only part of this (see this module's own
    header comment for why the original decide-only/apply-only public
    split was removed).

    Order (mirrors `ui.services.mutation_coordinator`'s own lock
    discipline exactly - reconciliation is not a special, unlocked
    back door):
      1. Read `resource_key` for `journal_id`, with NO lock held yet -
         fail closed (`JournalEntryNotFoundError`) if the row does not
         exist at all. This read exists ONLY to decide which lock to
         take next; nothing else about it is ever trusted.
      2. Acquire the SAME session-level resource lock a normal
         mutation on that `resource_key` would take (a `case:` key
         goes through `acquire_case_lock_session`, anything else
         through `acquire_global_lock_session` - this module does not
         reimplement either).
      3. Under that lock, re-read the FULL row AUTHORITATIVELY by
         `journal_id` - fail closed (`JournalEntryNotFoundError`) if it
         is now gone, and fail closed (`ResourceKeyMismatchError`) if
         its `resource_key` differs from step 1's (structurally
         unreachable today, checked anyway).
      4. Fail closed (`UnsupportedJournalStateError`) if the
         AUTHORITATIVE state is not `prepared`, `executing`, or
         `reconciliation_required` - a terminal row needs no
         reconciliation.
      5. Resolve the adapter using the AUTHORITATIVE `action_family`
         (never anything a caller might have assumed) and ask it for
         evidence.
      6. Convert that evidence into exactly one outcome (see
         `_decide_outcome()` - `prepared` has its own, stricter rule:
         it resolves ONLY to `failed` (a PROVEN-unchanged pre-state),
         NEVER `completed`, and - ROW 19C-1 FINAL PREPARED-
         INCONCLUSIVE SEMANTICS CORRECTION - NEVER `reconciliation_
         required` either any more; every other evidence combination
         instead raises `PreparedJournalUnresolvedError` here, before
         step 7 is ever reached, since its writer was never even
         invoked).
      7. Apply that outcome with the SAME lock STILL held (see
         `_apply_outcome_under_lock()`) - the guarded UPDATE's
         `cur.rowcount` must be exactly 1 or this raises
         `ReconciliationApplyFailedError`. Because this connection is
         the session-lock connection (autocommit - see
         `ui.services.db.get_session_lock_connection()`), this single
         UPDATE statement is itself the unit of durability: there is
         no multi-statement client-side transaction spanning steps 3-7
         to explicitly roll back, and there does not need to be - a
         raise from the adapter (step 5/6, before any UPDATE ever
         runs) or from the UPDATE statement itself (step 7) leaves the
         row exactly as step 3 found it, unresolved, with nothing
         partially written. ROW 19C-1 FINAL PREPARED-INCONCLUSIVE SEMANTICS
      CORRECTION: for a `prepared`-origin row, step 6 itself
      (`_decide_outcome()`) raises `PreparedJournalUnresolvedError`
      instead of returning an outcome whenever the evidence does not
      conclusively prove `pre_state_confirmed_unchanged=True` AND
      `post_state_verified=False` - so step 7 (`_apply_outcome_under_
      lock()`) is never even reached in that case: no UPDATE is
      issued, the row is left exactly as step 3 found it (`prepared`,
      `executing_at`/`resolved_at`/`resolution_code` all untouched),
      and the resource remains gated.
      8. Release the lock, always, via `finally` - only after step 7
         (or after step 6's raise, when reached instead of step 7),
         never before.
    """

    pre_lock_resource_key = _read_resource_key_only(conn, journal_id)
    if pre_lock_resource_key is None:
        raise JournalEntryNotFoundError(
            f"no mutation.mutation_journal row exists for journal_id={journal_id}"
        )

    advisory_lock_id = _acquire_resource_lock_for(conn, pre_lock_resource_key)
    try:
        entry = _read_authoritative_entry(conn, journal_id)
        if entry is None:
            raise JournalEntryNotFoundError(
                f"journal_id={journal_id} existed before the lock was acquired but is gone now "
                "(no code path in this project deletes journal rows - fail-closed regardless)"
            )
        if entry.resource_key != pre_lock_resource_key:
            raise ResourceKeyMismatchError(
                f"journal_id={journal_id}: pre-lock resource_key={pre_lock_resource_key!r} != "
                f"authoritative (lock-held) resource_key={entry.resource_key!r}"
            )
        if entry.state not in _SUPPORTED_UNRESOLVED_STATES:
            raise UnsupportedJournalStateError(
                f"reconciliation only supports states {sorted(_SUPPORTED_UNRESOLVED_STATES)}, "
                f"got AUTHORITATIVE state {entry.state!r} for journal_id={journal_id}"
            )

        adapter = registry.get(entry.action_family)
        evidence = adapter.gather_evidence(entry)
        outcome = _decide_outcome(entry, evidence)

        _apply_outcome_under_lock(conn, journal_id, outcome)
        return outcome
    finally:
        _mutation_lock.release_lock_session(conn, advisory_lock_id)
