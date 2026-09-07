# ============================================================
# VERGİ AI - ROW 19C-2a STEP 6: APPROVAL RECONCILIATION ADAPTERS.
#
# One `ui.services.mutation_registry.ReconciliationAdapter` per
# case-scoped approval family, plus `build_production_registry()` -
# the REAL `MutationAdapterRegistry` `ui/reconciliation_operator.py`'s
# `_default_registry_factory()` forward-referenced (Row 19C-2a Step 4)
# and now, finally, provides for real.
#
# INDEPENDENT EVIDENCE, NEVER CIRCULAR: `gather_evidence()` below never
# trusts the journal row's OWN `expected_post_hash`/`pre_hash` as if
# they were proof of anything (see `ui.services.mutation_registry.
# ReconciliationEvidence`'s own docstring: "NEVER derived from the
# journal row's own expected_post_hash - that would be circular"). It
# independently re-reads the ACTUAL canonical file on disk and the
# ACTUAL latest audit record next to it - the SAME two artefacts a
# human reviewer would look at - and reports what it genuinely finds:
#
#   - the canonical file does not exist at all -> the pre-state (no
#     canonical artefact) is PROVEN unchanged (`pre_state_confirmed_
#     unchanged=True`), and the post-state is certainly NOT reached
#     (`post_state_verified=False`) - this is the ONE combination that
#     legitimately resolves a `prepared`-origin row (see
#     `ui.services.mutation_registry._decide_outcome()`'s own
#     `prepared` branch) and, for an `executing`/`reconciliation_
#     required`-origin row, resolves cleanly to `failed`
#     (`RESOLUTION_CODE_FAILED_PRE_STATE_UNCHANGED`);
#   - the canonical file exists AND ALL FOUR of the bindings below hold
#     EXACTLY -> that audit record is independent, domain-level proof
#     that THIS EXACT attempt is what produced the canonical file
#     currently on disk (`post_state_verified=True`,
#     `observed_post_hash` = that file's own freshly-computed sha256);
#   - anything else is genuinely INCONCLUSIVE for THIS SPECIFIC attempt
#     - the canonical file's current state cannot be independently
#     attributed to it one way or the other (it may have been produced
#     by an earlier, unrelated approval of the same family) - reported
#     as `ReconciliationEvidence(False, False)`, which
#     `_decide_outcome()` resolves to `reconciliation_required` for an
#     `executing`/`reconciliation_required`-origin row, or - Row 19C-1
#     FINAL PREPARED-INCONCLUSIVE SEMANTICS CORRECTION -
#     `PreparedJournalUnresolvedError` (row left untouched) for a
#     `prepared`-origin one. NEVER guessed at more confidently than
#     that.
#
# THE EXACT BINDINGS (`_audit_binding_matches()` below) - ALL of them
# required, every one an EXACT comparison, and a MISSING or EMPTY/BLANK
# value on ANY of them is inconclusive, NEVER an automatic
# `post_state_verified=True`.
#
# WHY THIS SET DIFFERS BY ONE FROM THE FACADE'S FIVE: the facade
# (`ui.services.mutation_approval_facade._verify_completed_replay_audit_
# binding`) additionally checks `journal.observed_post_hash == current
# canonical SHA-256`. That binding is meaningful there and ONLY there,
# because it runs against a `completed` row - the one state in which
# `observed_post_hash` has actually been written. This module runs
# against `prepared`/`executing`/`reconciliation_required` rows, whose
# `observed_post_hash` is NULL by construction (only `_mark_completed`
# or a prior reconciliation ever sets it), so requiring it here would
# make every genuine reconciliation inconclusive. Binding 5 below, by
# contrast, IS available on an unresolved row (`pre_revision` is
# written by the original INSERT) and is therefore checked:
#   1. JOURNAL IDEMPOTENCY KEY - the audit record's
#      `mutation_idempotency_key` (Row 19C-2a's additive audit field -
#      see every `src/*_approval.py`'s own `write_approval_audit()`)
#      == this journal entry's own `idempotency_key` column (carried on
#      `JournalEntrySnapshot`).
#   2. RESOURCE KEY - the audit record's `mutation_resource_key`
#      (Row 19C-2a's second additive audit field) == this journal
#      entry's own `resource_key` (`case:<case_id>`). Binding 1 alone
#      would otherwise be satisfiable by an audit record written for a
#      DIFFERENT case that carried the same key.
#   3. CURRENT CANONICAL HASH - the canonical artefact must exist right
#      now and hash to a real value (already established before these
#      bindings are consulted; a vanished canonical file is handled by
#      the pre-state branch above instead).
#   4. AUDIT CANONICAL HASH - the audit record's own `canonical_sha256`
#      (a field all 10 families already wrote long before Row 19C-2a)
#      == binding 3's freshly-computed hash. This is what proves the
#      artefact ON DISK RIGHT NOW is still the exact artefact that
#      audit record attests to, rather than a later, unrelated
#      overwrite that merely left the older audit file as the newest.
#   5. AUDIT PENDING HASH - the audit record's own `pending_sha256`
#      (likewise a long-standing field in all 10 families) ==
#      `entry.pre_revision`, this journal row's OWN claimed pre-state.
#      The audit record must attest to the SAME PENDING document the
#      row was about to promote. See `_audit_binding_matches()`'s own
#      comment for why this is checked DIRECTLY rather than left to
#      binding 1 to carry transitively.
#
# This is intentionally the SAME binding rule
# `ui.services.mutation_approval_facade._verify_completed_replay_audit_
# binding()` applies for its REQUEST-TIME safe-replay check - but this
# is a SEPARATE,
# INDEPENDENT implementation (this module deliberately does NOT import
# that function, even though it is public, and vice versa): the
# facade's check runs synchronously, inline with a live request, over a
# SINGLE known-idempotency_key lookup, and RAISES on failure; this
# module's adapters run later, out of band, driven by a human operator
# (`ui/reconciliation_operator.py`) or a future automated sweep, over
# an arbitrary unresolved journal row, and REPORT evidence rather than
# raising. Keeping them independent means a bug in one is never masked
# by reusing the same code path in the other.
# ============================================================

from __future__ import annotations

import importlib
import json
from pathlib import Path

from . import mutation_registry as mr
from .common import find_latest_audit, sha256_file
from .mutation_approval_facade import ROW_KEY_TO_MODULE_NAME, action_family_for


class UnexpectedResourceKeyShapeError(Exception):
    """Raised if a journal entry routed to one of these adapters
    somehow does not carry a `case:<case_id>` resource_key -
    structurally unreachable today (every case-scoped approval family
    always locks `case:<case_id>` - see `ui.services.
    mutation_approval_facade.approve_case_scoped_mutation()`), kept as
    a fail-closed backstop in the same spirit as `ui.services.
    mutation_registry.ResourceKeyMismatchError`, never as an expected
    branch."""


def _nonblank(value) -> bool:
    """A binding value counts as PRESENT only if it is a genuinely
    non-blank string. `None` (an approval written before Row 19C-2a's
    own audit-binding wiring existed, or a direct CLI run of one of the
    10 approval modules), `""` and whitespace-only are ALL rejected -
    see this module's own header comment: a missing or empty binding is
    never automatic proof of anything.

    Deliberately this module's OWN copy of the same rule
    `ui.services.mutation_approval_facade._nonblank()` applies - see
    this module's header comment on why the two verification paths stay
    independent rather than sharing an implementation."""
    return isinstance(value, str) and bool(value.strip())


def _audit_binding_matches(record: dict, entry: mr.JournalEntrySnapshot, current_canonical_sha256: str) -> bool:
    """THE EXACT BINDINGS - see this module's own header comment.
    Returns True only when ALL of them hold exactly; any missing,
    blank or mismatched value returns False (inconclusive), never
    raises."""

    # 1. Journal idempotency key.
    recorded_key = record.get("mutation_idempotency_key")
    if not _nonblank(recorded_key) or recorded_key != entry.idempotency_key:
        return False

    # 2. Resource key (`case:<case_id>`).
    recorded_resource_key = record.get("mutation_resource_key")
    if not _nonblank(recorded_resource_key) or recorded_resource_key != entry.resource_key:
        return False

    # 3. Current canonical hash - established by the caller before this
    #    function is reached (a vanished canonical file never gets
    #    here; see `gather_evidence()`'s own pre-state branch).
    if not _nonblank(current_canonical_sha256):
        return False

    # 4. Audit canonical hash == the CURRENT canonical file's hash.
    recorded_canonical_sha256 = record.get("canonical_sha256")
    if not _nonblank(recorded_canonical_sha256) or recorded_canonical_sha256 != current_canonical_sha256:
        return False

    # 5. Audit pending hash == this journal row's OWN `pre_revision`
    #    (ROW 19C-2a FINAL AUDIT REMEDIATION). The audit record must
    #    attest to the SAME PENDING document the journal row was about
    #    to promote. Checked DIRECTLY, never left to binding 1 to carry
    #    transitively: `idempotency_key` does cover `pre_revision` (see
    #    src/mutation_guard.py's `_identity_fields()`), but that only
    #    holds if the key was honestly derived, and it can never catch
    #    an HONEST recorder inconsistency - a writer that journaled one
    #    pending hash and audited another. A row whose own
    #    `pre_revision` is NULL/blank cannot satisfy this binding and
    #    is therefore inconclusive, never auto-verified.
    if not _nonblank(entry.pre_revision):
        return False
    recorded_pending_sha256 = record.get("pending_sha256")
    if not _nonblank(recorded_pending_sha256) or recorded_pending_sha256 != entry.pre_revision:
        return False

    return True


class CaseScopedApprovalReconciliationAdapter:
    """One instance per case-scoped approval family - `module` is
    fixed at construction time (that is what distinguishes one
    registered instance from another; `entry.action_family` is used
    only by `MutationAdapterRegistry.get()` to ROUTE to the correct
    already-constructed instance, never re-inspected here to decide
    which module to use). Stateless and side-effect-free beyond the
    read-only filesystem access `gather_evidence()`'s own contract
    requires (see `ui.services.mutation_registry.ReconciliationAdapter`'s
    own Protocol docstring: "MUST perform no file/DB mutation of any
    kind")."""

    def __init__(self, module):
        self._module = module

    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if not entry.resource_key.startswith("case:"):
            raise UnexpectedResourceKeyShapeError(
                f"journal_id={entry.journal_id}: expected a 'case:<case_id>' resource_key for a "
                f"case-scoped approval family, got {entry.resource_key!r}"
            )
        case_id = entry.resource_key[len("case:"):]

        canonical_path = self._module.get_canonical_path(case_id)
        if not canonical_path.exists():
            # The writer boundary may or may not have been crossed
            # (that distinction is `_decide_outcome()`'s own job, not
            # this adapter's) - what THIS adapter can independently
            # prove is simply that no canonical artefact exists, i.e.
            # the pre-state (no canonical file) is unchanged.
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)

        # Binding 3 (see this module's own header comment): the
        # canonical artefact's hash RIGHT NOW. Computed once and reused
        # for both the binding check and the reported
        # `observed_post_hash`, so the value proven is exactly the value
        # reported. `None` here would mean the file vanished between
        # the `.exists()` check above and this read - genuinely
        # inconclusive, never either proof.
        current_canonical_sha256 = sha256_file(canonical_path)
        if current_canonical_sha256 is None:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        reviews_dir = canonical_path.parent / "reviews"
        audit_path = find_latest_audit(reviews_dir)
        if audit_path is None:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        try:
            with open(audit_path, "r", encoding="utf-8") as file:
                record = json.load(file)
        except Exception:
            # An unreadable/corrupt audit record is exactly as
            # inconclusive, for THIS attempt, as no record at all -
            # never treated as either proof.
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        if not isinstance(record, dict):
            # A syntactically-valid JSON document that is not an object
            # (a list, a bare string, ...) carries no bindings at all -
            # inconclusive, exactly like an unreadable one.
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        if _audit_binding_matches(record, entry, current_canonical_sha256):
            return mr.ReconciliationEvidence(
                post_state_verified=True, pre_state_confirmed_unchanged=False,
                observed_post_hash=current_canonical_sha256,
            )

        # The canonical file exists, but at least one of the four
        # bindings does not hold exactly: the latest audit record
        # belongs to a DIFFERENT attempt or a different case, carries a
        # missing/blank binding (e.g. an approval written before Row
        # 19C-2a's own wiring existed), or attests to a canonical hash
        # that no longer matches what is on disk. Genuinely
        # inconclusive for THIS journal entry specifically - never
        # upgraded to either proof.
        return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)


def build_production_registry() -> mr.MutationAdapterRegistry:
    """The REAL registry `ui/reconciliation_operator.py`'s own
    `_default_registry_factory()` (Row 19C-2a Step 4) forward-referenced
    by name - one `CaseScopedApprovalReconciliationAdapter` per
    case-scoped approval family, registered under the EXACT SAME
    `action_family` string `ui.services.mutation_approval_facade.
    approve_case_scoped_mutation()` uses to build each family's
    `MutationIntent` (both call the shared `action_family_for()`
    helper - see that module's own comment on why this mapping is
    defined there, not duplicated here)."""
    registry = mr.MutationAdapterRegistry()
    for row_key, module_name in ROW_KEY_TO_MODULE_NAME.items():
        module = importlib.import_module(module_name)
        registry = registry.with_adapter(
            action_family_for(row_key), CaseScopedApprovalReconciliationAdapter(module),
        )
    return registry
