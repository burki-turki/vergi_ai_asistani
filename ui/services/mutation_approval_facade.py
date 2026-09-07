# ============================================================
# VERGİ AI - ROW 19C-2a STEP 6: APPROVAL MUTATION FACADE.
#
# The bridge between ui.services.approval_registry.case_scoped_approve()
# (Layer A, the 10 case-scoped approval families) and
# ui.services.mutation_coordinator.run_mutation() - the FIRST real
# production writer this project's mutation-journal infrastructure
# (Row 19C-1's coordinator/journal, Row 19C-2a's authz-first/rowcount/
# reconciliation-provenance hardening) is ever connected to. Row 19C-1
# exercised `run_mutation()` only against FAKE callbacks
# (ui/tests/test_mutation_coordinator_isolated.py,
# ui/tests/test_mutation_journal_postgres.py) - connecting a real
# writer was explicitly deferred, and this module is that connection.
#
# THIS STEP (Row 19C-2a Step 6) DELIBERATELY DOES NOT TOUCH:
#   - ui/services/approval_registry.py's own `case_scoped_approve()`
#     call site - Row 19C-2a Step 7 wires that; this module is fully
#     self-contained and independently testable NOW, before that
#     wiring lands (`approve_case_scoped_mutation()` below has the
#     same (row_key, case_id, expected_hash, principal) shape
#     `case_scoped_approve()` already takes, specifically so Step 7 is
#     a small, mechanical replacement rather than a redesign);
#   - the 10 src/*_approval.py modules' own `run_approve()`/
#     `write_approval_audit()` logic (Row 19C-2a Step 5 - already
#     landed; this module calls `run_approve(case_id,
#     mutation_idempotency_key=...)` exactly as that step's own new
#     keyword-only parameter was designed to be called);
#   - `ui.services.mutation_approval_adapters` (a SEPARATE file, this
#     same step) - the reconciliation-time adapters a human operator's
#     `ui/reconciliation_operator.py --apply` run would use LATER, out
#     of band, for a row this module left `executing`/
#     `reconciliation_required`. This module's own
#     `AuditBindingVerificationFailedError` (see below) is a
#     REQUEST-TIME safety check on a SAFE REPLAY, never a substitute
#     for that out-of-band reconciliation.
#
# DUAL AUTHORIZATION - THE OUTER (PRE-CONNECTION) AND INNER
# (UNDER-LOCK) CHECKS, AND WHY BOTH EXIST
# -------------------------------------------------------------------
# `authorize_case_access()` runs TWICE per production approval, against
# the SAME repository, for two DIFFERENT and non-substitutable reasons:
#
#   OUTER (`_authorize_outer()` below, the FIRST thing this function
#   does after resolving `row_key`): runs BEFORE a journal/lock
#   connection is opened, BEFORE the session-level resource lock is
#   even requested, BEFORE any filesystem hash is read, and therefore
#   necessarily BEFORE any `mutation.mutation_journal` gate/idempotency
#   SQL. Its job is to make an UNAUTHORIZED caller cost NOTHING and
#   REVEAL NOTHING: no connection, no lock wait (an unauthorized caller
#   must never be able to queue behind - or, worse, hold up - a
#   legitimate mutation's lock by spraying requests), no artefact hash
#   read, no journal row, no journal query. Proven directly by
#   `ui/tests/test_mutation_approval_facade_isolated.py`'s own
#   outer-denial checks (zero conn_factory calls, zero lock calls, zero
#   sha256 reads, zero SQL).
#
#   INNER (`authz_callback`, invoked by `run_mutation()` as step 2 of
#   its own AUTHORITATIVE ORDER - strictly after the lock is held and
#   strictly BEFORE the journal gate/idempotency SQL): the
#   AUTHORITATIVE check. The outer one is, by construction, a pre-lock
#   read of mutable IAM state - a role revocation, session revocation
#   or assignment change committed WHILE this request waited for the
#   case lock would make it stale. Re-running it under the lock is what
#   makes the decision that actually gates the writer a lock-held one,
#   in exactly the same spirit as this module's own under-lock
#   precondition re-check (below). The outer check is therefore a
#   fail-fast/leak-prevention filter and NEVER a substitute for it.
#
# Existence-blindness (Row 19B's own security property: an attacker
# must not learn whether a case_id exists at all before being
# authorized to touch it) is preserved by BOTH checks, because BOTH go
# through `authorize_case_access()` - which folds "malformed case_id",
# "no such case directory" and "a real case_id you are not assigned to"
# into the SAME `CaseAccessDeniedError`. This module never calls
# `ui.services.paths.resolve_case_id()` itself, at any point; the only
# filesystem-safe `case_id` it ever uses is the RESOLVED value
# `authorize_case_access()` returns.
#
# Because the OUTER check already returns that resolved, filesystem-
# safe `case_id`, everything downstream is built from it and never from
# the raw caller-supplied string:
#   - the lock's `resource_key` is `case:<resolved_case_id>`
#     (`mutation_lock.case_resource_key()` - pure string formatting, no
#     filesystem I/O), so the value that becomes a
#     `mutation.mutation_resources` key and a `mutation_journal.
#     resource_key` is always an already-authorized one;
#   - the `MutationIntent`'s `target_ref` is a fixed, family-scoped
#     LOGICAL label (`f"{row_key}.canonical"`), never a real filesystem
#     path;
#   - `authz_callback` (the INNER check) re-resolves the same value and
#     fails closed if it somehow differs (`ResolvedCaseIdMismatchError`
#     - structurally unreachable, since `resolve_case_id()` is
#     deterministic for a given tree, but never assumed from outside
#     this module's own scope).
#
# PRE-STATE SNAPSHOT: COMPOSITE `pre_hash`, CLAIMED `pre_revision`
# -------------------------------------------------------------------
# `pre_revision` is the REQUEST's own claim: the caller-supplied
# `expected_hash` (the PENDING file's hash as of the review screen
# render being confirmed), verbatim. It is part of mutation IDENTITY
# (see `src/mutation_guard.py`'s `_identity_fields()`), so an honest
# retry of the same request always recomputes the same
# `idempotency_key`.
#
# `pre_hash` is FILESYSTEM EVIDENCE: a deterministic COMPOSITE digest
# over the three things that together describe this family's real
# pre-mutation state on disk (`_compute_precondition_snapshot()`):
#   1. the pending file's SHA-256 (or a fixed absence marker),
#   2. whether the canonical artefact exists at all,
#   3. the canonical artefact's SHA-256 (or a fixed absence marker).
# A plain pending-hash check alone is NOT sufficient for this family:
# `run_approve()` OVERWRITES the canonical artefact, so a concurrent
# writer that changed only the CANONICAL side (e.g. a different
# family's promotion, a restore from `history/`, or an out-of-band
# edit) would be completely invisible to a pending-only comparison,
# and this approval would silently overwrite it.
#
# The snapshot is computed TWICE: once pre-lock (right after the OUTER
# authz, to be recorded as this attempt's `pre_hash`) and again from
# the filesystem UNDER the lock, after the INNER authz, and only when a
# NEW mutation is actually needed (`precondition_callback` - which
# `run_mutation()` reaches only after its own idempotency lookup found
# no existing row, i.e. never on a replay). Under the lock:
#   - a CHANGED composite digest raises `common.PreconditionRace
#     DetectedError` (a `StaleViewError` SUBCLASS - see its own
#     docstring: every existing `except StaleViewError` handler keeps
#     working unchanged) - something really did change while this
#     request waited for the lock;
#   - a pending SHA-256 that does not match `pre_revision` raises the
#     plain `StaleViewError` this project already used here.
# In BOTH cases the raise happens inside `precondition_callback`, i.e.
# at step 5 of `run_mutation()`'s AUTHORITATIVE ORDER - strictly BEFORE
# step 6 (`_insert_prepared`) - so ZERO `prepared` journal rows are
# written and the writer is NEVER invoked.
#
# Crucially, `pre_hash` is deliberately NOT part of either digest
# (`src/mutation_guard.py`'s own ROW 19C-2a correction): two concurrent
# identical requests must not take DIFFERENT idempotency keys merely
# because one of them read the filesystem after the other had already
# mutated it. So the composite snapshot is RECORDED and RE-VERIFIED
# evidence, never identity.
#
# REPLAY-SAFETY AUDIT-BINDING CHECK - FIVE EXACT BINDINGS (see
# src/mutation_guard.py's own module docstring, which already commits
# to this module's name for exactly this purpose)
# -------------------------------------------------------------------
# On a SAFE REPLAY (`MutationOutcome.replayed=True` - same
# idempotency_key/request_fingerprint as an existing `completed` row;
# `run_mutation()` does NOT re-invoke the writer in this case), this
# module does not simply trust the journal's own stored
# `observed_post_hash` at face value. It independently re-reads the
# CURRENT canonical file and its own LATEST audit record and verifies
# FIVE equalities, ALL of them EXACTLY
# (`_verify_completed_replay_audit_binding()`):
#
#   1. JOURNAL IDEMPOTENCY KEY -
#      `journal.idempotency_key == audit.mutation_idempotency_key`.
#      The left side is recomputed here from this call's own
#      `MutationIntent`; that recomputation is a pure function of the
#      intent (`mutation_guard.compute_idempotency_key()`), so it
#      produces the IDENTICAL value `run_mutation()` computed
#      internally - no coordination between the two is needed or
#      assumed.
#   2. RESOURCE KEY -
#      `journal.resource_key == audit.mutation_resource_key ==
#      case:<case_id>`. All three legs are checked: the audit field
#      must equal this attempt's resource_key (without which binding 1
#      alone could be satisfied by an audit record written for a
#      DIFFERENT case that happened to carry the same key), AND that
#      resource_key must really be a well-formed `case:<case_id>` key
#      rather than merely equal to whatever the audit record carries.
#   3. JOURNAL POST-STATE HASH -
#      `journal.observed_post_hash == current canonical SHA-256`. The
#      canonical artefact must exist right now (a `completed` row whose
#      artefact has since vanished is NOT a corroborated success) AND
#      the journal's own recorded post-state hash must match it. This
#      is what makes the value this module hands back to its caller -
#      and therefore the hash the lawyer's success page displays -
#      something THIS request actually verified, rather than an
#      inherited journal claim carried through blindly.
#   4. AUDIT CANONICAL HASH -
#      `audit.canonical_sha256 == current canonical SHA-256` (a field
#      every one of the 10 families already wrote long before Row
#      19C-2a). This proves the artefact ON DISK RIGHT NOW is still the
#      exact artefact that audit record attests to - not a later,
#      unrelated overwrite that merely left the old audit file as the
#      newest one.
#   5. AUDIT PENDING HASH -
#      `audit.pending_sha256 == journal/request pre_revision`. The
#      audit record must attest to the SAME PENDING document this
#      request claims as its pre-state. Checked DIRECTLY, never left to
#      binding 1 to carry transitively: `idempotency_key` does cover
#      `pre_revision` (see `src/mutation_guard.py`'s
#      `_identity_fields()`), but a transitive guarantee only holds if
#      the key was honestly derived, and it can never catch an HONEST
#      recorder inconsistency - a writer that journaled one pending
#      hash and audited another.
#
# A MISSING, EMPTY/BLANK, MALFORMED or MISMATCHED value for ANY of the
# five is NEVER treated as an automatic success (nor as an automatic
# failure). `None`, `""` and whitespace-only are all rejected
# explicitly, so an approval written before Row 19C-2a's own wiring
# existed (both new audit fields `None`) can never satisfy this check
# by accident.
#
# The helper is PRIVATE and additionally CLOSED at the parameter level:
# it requires a `journal_state` argument that must be exactly
# `COMPLETED_JOURNAL_STATE`. The "this can only be a completed replay"
# precondition used to hold only because its single call site sat
# behind `if outcome.replayed:`; it is now structurally enforced inside
# the helper, so no future call site can reach this logic for a row
# that was never actually completed.
#
# Any failure raises `AuditBindingVerificationFailedError`, mapped by
# `ui/main.py` to the SAME closed `MUTATION_REQUIRES_REVIEW` (HTTP 409)
# contract `mutation_coordinator.JournalCompletionUncertainError`'s own
# docstring already names - NEVER reported as a plain success, and
# NEVER as a plain failure either (the underlying mutation may well
# have genuinely succeeded; only the independent corroboration could
# not be completed). A human operator resolves the underlying
# ambiguity out of band via `ui/reconciliation_operator.py`, backed by
# a REAL `ui.services.mutation_approval_adapters` adapter's own
# independent evidence-gathering - this check is a REQUEST-TIME safety
# net, never a substitute for that reconciliation.
# ============================================================

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mutation_guard import MutationIntent, compute_idempotency_key  # noqa: E402

from . import authz as _authz
from . import mutation_coordinator as _mutation_coordinator
from . import mutation_lock as _mutation_lock
from .common import (
    PendingNotFoundError,
    PreconditionRaceDetectedError,
    StaleViewError,
    find_latest_audit,
    sha256_file,
)

# ROW 19C-2a: the row_key -> module_name mapping for all 10 case-scoped
# approval families - PUBLIC (no leading underscore) and re-exported
# specifically so `ui.services.mutation_approval_adapters` (a SEPARATE
# file, built in this same step) can register its own reconciliation
# adapter for the EXACT SAME set of `action_family` strings this module
# uses, without either module importing `ui.services.approval_registry`
# (which will, per Row 19C-2a Step 7, import THIS module - importing it
# back here would be a circular import) and without silently drifting
# apart from a second, independently-maintained copy of this mapping.
# Deliberately matches `ui.services.approval_registry.CASE_SCOPED_ROWS`'s
# own `key`/`module` pairs exactly (verified against that file, Row
# 19C-2a Step 7 does not change it) - this is NOT a new naming decision,
# just this module's own copy of an already-established one, scoped to
# exactly what THIS module needs (row_key -> module_name; row_no/label
# stay approval_registry.py's own concern, never duplicated here).
ROW_KEY_TO_MODULE_NAME = {
    "deadline": "deadline_approval",
    "issue_spotting": "issue_spotting_approval",
    "legal_research": "legal_research_approval",
    "case_law": "case_law_approval",
    "evidence": "evidence_approval",
    "arguments": "argument_approval",
    "risk_strategy": "risk_strategy_approval",
    "drafting": "drafting_approval",
    "qa": "qa_approval",
    "case_view": "orchestrator_approval",
}

_ACTION_FAMILY_PREFIX = "approval."

# The `case:` resource-key prefix `ui.services.mutation_lock.
# case_resource_key()` produces. Kept here as this module's own named
# constant purely so binding 2b (see
# `_verify_completed_replay_audit_binding`) can assert the SHAPE of a
# resource_key rather than only its equality with an audit field -
# `mutation_lock` exposes the builder, not the prefix.
_CASE_RESOURCE_KEY_PREFIX = "case:"

_logger = logging.getLogger("vergi_ai.mutation_approval_facade")


def _log_critical_safely(message: str) -> None:
    """Identical in purpose to `ui.services.mutation_coordinator.
    _log_critical_safely` / `ui.services.mutation_registry.
    _log_critical_safely` - a logging call that itself raises must
    NEVER be allowed to replace an already-propagating exception or, in
    a `finally` block, to silently discard one. Kept as this module's
    own copy so its cleanup logging has no dependency on either of
    those modules for this purpose."""
    try:
        _logger.critical(message)
    except Exception:
        pass


def action_family_for(row_key: str) -> str:
    """The ONE place this project's `action_family` string is derived
    from a case-scoped approval `row_key` - both this module's own
    `MutationIntent` construction below AND
    `ui.services.mutation_approval_adapters.build_production_registry()`
    call this, so the two can never drift apart into registering under
    different strings for the same family."""
    return f"{_ACTION_FAMILY_PREFIX}{row_key}"


# ROW 19C-2a: mirrors mutation_coordinator.py's own
# JournalCompletionUncertainError docstring - this closed HTTP-mapping
# label is shared by BOTH that exception class's own ambiguous-outcome
# case (the writer succeeded but the 'completed' transition itself
# could not be durably recorded) and this module's own
# AuditBindingVerificationFailedError (a safe replay whose claimed
# 'completed' outcome could not be independently corroborated). Row
# 19C-2a Step 7 (ui/main.py) maps ANY exception carrying this same
# closed contract to the SAME HTTP 409 response - never a message
# implying definite success OR definite failure.
MUTATION_REQUIRES_REVIEW = "MUTATION_REQUIRES_REVIEW"


class AuditBindingVerificationFailedError(Exception):
    """See this module's own header comment ("REPLAY-SAFETY AUDIT-
    BINDING CHECK - FOUR EXACT BINDINGS") for the full rationale.
    Raised ONLY on a safe replay (`MutationOutcome.replayed=True`)
    whose independent audit-record corroboration failed - never on a
    fresh (non-replayed) execution, whose own successful writer return
    is itself sufficient completion proof (see
    `mutation_coordinator.WriterResult`'s own docstring)."""

    def __init__(self, *, journal_id: int, idempotency_key: str, reason: str):
        self.journal_id = journal_id
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(
            f"journal_id={journal_id}: safe-replay audit-binding verification failed "
            f"(idempotency_key={idempotency_key!r}): {reason} - this outcome requires human "
            "reconciliation (see ui/reconciliation_operator.py); it is neither a confirmed "
            "success nor a confirmed failure"
        )


class ResolvedCaseIdMismatchError(Exception):
    """Fail-closed backstop: the INNER (under-lock)
    `authorize_case_access()` call returned a DIFFERENT resolved
    case_id than the OUTER (pre-lock) one did - meaning the
    `resource_key` this request already LOCKED, and the `pre_hash`
    snapshot it already recorded, describe a different case than the
    one the authoritative check just approved. Structurally unreachable
    (`ui.services.paths.resolve_case_id()` is deterministic for a given
    tree, and both calls pass the same raw `case_id`), but never
    assumed from outside this module's own scope - in the same spirit
    as `ui.services.mutation_registry.ResourceKeyMismatchError`. Raised
    from inside `authz_callback`, i.e. at step 2 of `run_mutation()`'s
    AUTHORITATIVE ORDER, so no journal row is created and the writer is
    never invoked."""


# ROW 19C-2a: fixed absence markers for the composite pre-state
# snapshot (see `_compute_precondition_snapshot()`). Deliberately
# constants, never `None` folded into the digest input, so "the file is
# absent" and "the file's hash is literally the string 'absent'" can
# never collide: a real sha256 hex digest is 64 lowercase hex chars and
# can never equal either of these sentinels.
SNAPSHOT_ABSENT = "__absent__"
SNAPSHOT_PRESENT = "__present__"

# Bumping this invalidates every stored `pre_hash` comparison against a
# snapshot computed by an older version of this function - it is part
# of the digest input specifically so a future change to WHAT the
# snapshot covers can never be silently mistaken for "nothing changed".
_SNAPSHOT_VERSION = "row19c2a.v1"


@dataclass(frozen=True)
class PreconditionSnapshot:
    """The three filesystem facts that together describe one
    case-scoped approval family's real pre-mutation state, plus the
    single deterministic digest over them that becomes this attempt's
    `MutationIntent.pre_hash`. Every field is either a sha256 hex
    digest or one of the two fixed sentinels above - never a path,
    never file content."""

    pending_sha256: str          # a real digest, or SNAPSHOT_ABSENT
    canonical_presence: str      # SNAPSHOT_PRESENT or SNAPSHOT_ABSENT
    canonical_sha256: str        # a real digest, or SNAPSHOT_ABSENT
    composite_digest: str

    @property
    def pending_exists(self) -> bool:
        return self.pending_sha256 != SNAPSHOT_ABSENT


def _compute_precondition_snapshot(pending_path: Path, canonical_path: Path) -> PreconditionSnapshot:
    """Pure-read, deterministic. Called TWICE per fresh mutation: once
    pre-lock (recorded as `pre_hash`) and once under the lock (compared
    against it) - see this module's own header comment ("PRE-STATE
    SNAPSHOT").

    The canonical side is recorded as TWO independent facts (presence,
    then hash) on purpose. They are two separate filesystem reads, so a
    file deleted between them yields the genuinely-odd pair
    (`SNAPSHOT_PRESENT`, `SNAPSHOT_ABSENT`) - which is recorded
    FAITHFULLY rather than smoothed over. That pair simply makes the
    composite digest differ from the other computation's, which is
    exactly the right outcome: something really was changing underneath
    this request, and `PreconditionRaceDetectedError` is precisely the
    fail-closed answer to that.

    Serialization matches `src/mutation_guard.py`'s own
    `_canonical_json()` discipline exactly (sorted keys, no whitespace,
    ASCII-escaped) so the same three facts always produce a
    byte-identical digest input on any platform or Python version."""
    pending_sha256 = sha256_file(pending_path) or SNAPSHOT_ABSENT
    canonical_presence = SNAPSHOT_PRESENT if Path(canonical_path).exists() else SNAPSHOT_ABSENT
    canonical_sha256 = sha256_file(canonical_path) or SNAPSHOT_ABSENT

    payload = json.dumps(
        {
            "snapshot_version": _SNAPSHOT_VERSION,
            "pending_sha256": pending_sha256,
            "canonical_presence": canonical_presence,
            "canonical_sha256": canonical_sha256,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")

    return PreconditionSnapshot(
        pending_sha256=pending_sha256,
        canonical_presence=canonical_presence,
        canonical_sha256=canonical_sha256,
        composite_digest=hashlib.sha256(payload).hexdigest(),
    )


def _default_authz_repository():
    """Returns `(repository, close)`. `close` is a zero-argument
    callable the caller MUST invoke in a `finally` once BOTH the outer
    and inner authorization checks are done - this module opens ONE
    IAM connection per approval request and reuses it for both, rather
    than opening (and, as this function's pre-Row-19C-2a version did,
    leaking) a second one for the second check."""
    from . import db as _db  # lazy import (psycopg)
    conn = _db.get_connection()
    return _authz.PostgresAuthzRepository(conn), conn.close


def _resolve_authz_repository(authz_repository):
    """Normalizes the injected-vs-default repository choice into the
    same `(repository, close)` pair. An INJECTED repository (tests, and
    any caller that already owns a connection) is never closed by this
    module - its lifetime belongs to whoever created it."""
    if authz_repository is not None:
        return authz_repository, lambda: None
    return _default_authz_repository()


def _default_conn_factory():
    """Lazy-imported (never at this module's top level) so importing
    `ui.services.mutation_approval_facade` never itself requires
    psycopg - matches `ui.services.db`'s own lazy-import discipline and
    `ui.reconciliation_operator._default_conn_factory`'s identical
    reasoning. Returns the SAME autocommit, session-lock-capable
    connection shape `ui.services.mutation_coordinator` requires."""
    from . import db as _db  # lazy import

    return _db.get_session_lock_connection()


def _read_latest_audit_record(reviews_dir: Path) -> tuple[Path | None, dict | None, str | None]:
    """Returns (audit_path, record, error_reason). `error_reason` is
    None on a clean read (`audit_path`/`record` both non-None only in
    that case), a human-readable string on ANY failure (no audit file
    found at all, or one exists but could not be read/parsed) - never
    raises itself, since both callers (the replay-verification check
    and the writer-side audit_path lookup) need to keep going and
    decide what to do with a missing/bad audit record themselves."""
    audit_path = find_latest_audit(reviews_dir)
    if audit_path is None:
        return None, None, f"no audit record found under {reviews_dir}"
    try:
        with open(audit_path, "r", encoding="utf-8") as file:
            record = json.load(file)
    except Exception as error:
        return audit_path, None, f"audit record at {audit_path} could not be read/parsed: {error!r}"
    if not isinstance(record, dict):
        # Valid JSON, but not an object (a list, a bare string, ...) -
        # it carries no bindings at all. Classified as a read failure
        # rather than being handed on to the binding checks, where
        # `record.get(...)` would raise an unrelated `AttributeError`
        # and escape this module's own closed error contract.
        return audit_path, None, (
            f"audit record at {audit_path} is valid JSON but not a JSON object "
            f"(got {type(record).__name__}), so it carries no audit bindings at all"
        )
    return audit_path, record, None


def _nonblank(value) -> bool:
    """A binding value counts as PRESENT only if it is a genuinely
    non-blank string. `None` (an approval written before Row 19C-2a's
    own wiring existed, or a direct CLI run), `""` and whitespace-only
    are ALL rejected - see this module's own header comment: a missing
    or empty binding is never an automatic success."""
    return isinstance(value, str) and bool(value.strip())


COMPLETED_JOURNAL_STATE = "completed"


def _verify_completed_replay_audit_binding(
    canonical_path: Path,
    *,
    journal_state: str,
    journal_id: int,
    idempotency_key: str,
    resource_key: str,
    observed_post_hash: str | None,
    pre_revision: str | None,
) -> str:
    """THE FIVE EXACT BINDINGS check - see this module's own header
    comment for the full rationale of each. Returns the freshly
    computed CURRENT canonical sha256 on success; raises
    `AuditBindingVerificationFailedError` on ANY missing, blank,
    malformed or mismatched value.

    PRIVATE, and additionally CLOSED at the parameter level: the
    mandatory `journal_state` argument must be exactly
    `COMPLETED_JOURNAL_STATE`. A safe replay is the ONLY situation in
    which this corroboration is meaningful (a fresh execution's own
    successful writer return is already sufficient proof - see
    `mutation_coordinator.WriterResult`), and `run_mutation()` only
    ever reports `replayed=True` for an EXISTING `completed` row. That
    precondition previously held merely because the single call site
    was guarded by `if outcome.replayed:`; it is now enforced HERE, in
    the helper itself, so no future call site can reach this logic for
    a row that was never actually completed.

    Deliberately NOT imported by
    `ui.services.mutation_approval_adapters`, which independently
    implements the bindings IT can meaningfully evaluate, for the
    reason that module's own header comment gives (a bug in one must
    never be masked by the other reusing it)."""

    if journal_state != COMPLETED_JOURNAL_STATE:
        raise AuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                f"this corroboration is only defined for a {COMPLETED_JOURNAL_STATE!r} journal row "
                f"(a safe replay), but it was called for state {journal_state!r}"
            ),
        )

    canonical_path = Path(canonical_path)

    # ---- Binding 3a: the canonical artefact must exist right now. ----
    current_canonical_sha256 = sha256_file(canonical_path)
    if current_canonical_sha256 is None:
        raise AuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                f"the canonical artefact at {canonical_path} does not exist right now, so a "
                f"{COMPLETED_JOURNAL_STATE!r} journal outcome cannot be corroborated against it"
            ),
        )

    # ---- Binding 3b: the JOURNAL's OWN recorded post-state hash must
    # match that freshly-computed value. Without this, the hash this
    # module hands back to its caller - and therefore the hash the
    # lawyer's success page displays - would be a value nothing in this
    # request ever verified. ----
    if not _nonblank(observed_post_hash):
        raise AuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                f"the journal row records a missing/blank observed_post_hash "
                f"({observed_post_hash!r}) for a {COMPLETED_JOURNAL_STATE!r} row, so its claimed "
                "post-state cannot be corroborated against the artefact on disk"
            ),
        )
    if observed_post_hash != current_canonical_sha256:
        raise AuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                f"the journal row records observed_post_hash={observed_post_hash!r}, but the "
                f"canonical artefact at {canonical_path} hashes to {current_canonical_sha256!r} "
                "right now - the artefact on disk is not the one this journal row attests to"
            ),
        )

    # ---- Binding 2b: `resource_key` must really be this project's
    # `case:<case_id>` shape, not merely equal to whatever the audit
    # record happens to carry. ----
    if not resource_key.startswith(_CASE_RESOURCE_KEY_PREFIX) or not resource_key[len(_CASE_RESOURCE_KEY_PREFIX):]:
        raise AuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                f"resource_key={resource_key!r} is not a well-formed "
                f"{_CASE_RESOURCE_KEY_PREFIX}<case_id> key for a case-scoped approval family"
            ),
        )

    reviews_dir = canonical_path.parent / "reviews"
    audit_path, record, error_reason = _read_latest_audit_record(reviews_dir)
    if error_reason is not None:
        raise AuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key, reason=error_reason,
        )

    def require(field_name, expected, description):
        """ONE place for the missing/blank-then-mismatch pair, so no
        binding below can accidentally check only one of the two."""
        recorded = record.get(field_name)
        if not _nonblank(recorded):
            raise AuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    f"latest audit record at {audit_path} carries a missing/blank {field_name} "
                    f"({recorded!r}) - an unbound audit record is never accepted as corroboration"
                ),
            )
        if recorded != expected:
            raise AuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    f"latest audit record at {audit_path} carries {field_name}={recorded!r}, which "
                    f"does NOT match this call's own {description} ({expected!r})"
                ),
            )

    # ---- Binding 1: journal idempotency key. ----
    require("mutation_idempotency_key", idempotency_key, "journal idempotency_key")

    # ---- Binding 2a: journal resource key. ----
    require("mutation_resource_key", resource_key, "journal resource_key")

    # ---- Binding 4: the audit record's own canonical hash. ----
    require("canonical_sha256", current_canonical_sha256, "CURRENT canonical artefact hash")

    # ---- Binding 5: the audit record must attest to the SAME PENDING
    # document this request claims as its pre-state. Checked DIRECTLY
    # rather than relying on `idempotency_key` transitively covering
    # `pre_revision` (it does - see src/mutation_guard.py's
    # `_identity_fields()` - but a transitive guarantee only holds if
    # the key was honestly derived, and it can never catch an HONEST
    # recorder inconsistency, e.g. a writer that journaled one pending
    # hash and audited another). ----
    if not _nonblank(pre_revision):
        raise AuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                f"this request carries a missing/blank pre_revision ({pre_revision!r}), so the audit "
                "record's own pending_sha256 cannot be corroborated against it"
            ),
        )
    require("pending_sha256", pre_revision, "pre_revision (the claimed pending document hash)")

    return current_canonical_sha256


@dataclass(frozen=True)
class CaseScopedApprovalResult:
    """Deliberately narrower than `approval_registry.case_scoped_approve()`'s
    own pre-Row-19C-2a return dict - this module does not own (and must
    not duplicate) `approval_registry.CASE_SCOPED_ROWS_BY_KEY`'s own
    row_no/label metadata (see this module's own header comment on
    avoiding a circular import). Row 19C-2a Step 7's own
    `case_scoped_approve()` combines `row_key` here with its own
    `CASE_SCOPED_ROWS_BY_KEY[row_key]` lookup to reconstruct the exact
    same response shape callers already receive today."""

    row_key: str
    canonical_path: Path
    canonical_hash: str | None
    audit_path: Path | None
    stdout: str
    journal_id: int
    replayed: bool


def approve_case_scoped_mutation(
    row_key: str,
    case_id: str,
    expected_hash: str,
    *,
    principal,
    authz_repository=None,
    conn_factory=None,
) -> CaseScopedApprovalResult:
    """The Row 19C-2a REPLACEMENT for directly calling
    `module.run_approve(case_id)` from `approval_registry.
    case_scoped_approve()` (Row 19C-2a Step 7 wires that call site -
    NOT this step). Runs the approval as ONE coordinated, journaled,
    idempotent mutation via `ui.services.mutation_coordinator.
    run_mutation()`, under the SAME session-level `case:<case_id>` lock
    every other file-write mutation on this case uses (Row 19A design
    decision - one lock per case, not one per family; unchanged here).

    ORDER (see this module's own header comment for the full rationale
    of each step):
      1. Resolve `row_key` -> family module (fail-closed `KeyError`).
      2. OUTER `authorize_case_access()` - BEFORE any journal/lock
         connection is opened, BEFORE the lock is requested, BEFORE any
         artefact hash is read, BEFORE any journal SQL.
      3. Derive `resource_key`/pending/canonical paths from the
         RESOLVED case_id, then compute the PRE-LOCK composite
         pre-state snapshot (recorded as `pre_hash`).
      4. Open the journal connection and acquire the session-level
         `case:<case_id>` lock.
      5. `run_mutation()` - INNER (authoritative) authz, journal gate,
         idempotency lookup, under-lock precondition re-verification,
         then (only for a genuinely new mutation) `prepared` ->
         `executing` -> writer -> `completed`.
      6. On a safe REPLAY only: the FOUR EXACT audit bindings.
      7. Release the lock, close the journal connection, and close the
         IAM authz connection if (and only if) this module opened it.

    Raises, UNCHANGED in type/message, everything
    `case_scoped_approve()` already raises today for the SAME reasons
    (`PendingNotFoundError`, `StaleViewError`,
    `authz.CaseAccessDeniedError`) - a drop-in replacement, not a
    behavior change for existing callers. ADDITIONALLY raises:
      - `common.PreconditionRaceDetectedError` - a `StaleViewError`
        SUBCLASS, so an existing `except StaleViewError` handler keeps
        working unchanged (see its own docstring);
      - whatever `ui.services.mutation_coordinator.run_mutation()`
        itself raises (`ResourceGatedError`,
        `IdempotencyConflictError`, `PriorAttemptFailedError`,
        `JournalExecutingTransitionFailedError`,
        `JournalCompletionUncertainError`);
      - this module's own `AuditBindingVerificationFailedError`
        (safe-replay corroboration failure) and
        `ResolvedCaseIdMismatchError` (fail-closed backstop).
    NONE of these are caught or reclassified here; the caller
    (`ui/main.py`) decides the HTTP mapping."""

    if row_key not in ROW_KEY_TO_MODULE_NAME:
        raise KeyError(f"row_key={row_key!r} is not a known case-scoped approval family")

    import importlib
    module = importlib.import_module(ROW_KEY_TO_MODULE_NAME[row_key])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        # ============================================================
        # OUTER AUTHORIZATION - step 1 of the dual-authz contract (see
        # this module's own header comment). NOTHING mutation-related
        # has happened yet at this point: no journal/lock connection
        # has been opened (`conn_factory()` is called further down), no
        # session lock has been requested, no artefact hash has been
        # read, and therefore no `mutation.mutation_journal` gate/
        # idempotency SQL can possibly have run. A denial here raises
        # `CaseAccessDeniedError` straight out of this function with
        # ZERO of those four things having occurred.
        # ============================================================
        outer_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )

        # Every value below is derived from the RESOLVED, already-
        # authorized case_id - never the raw caller-supplied string.
        resource_key = _mutation_lock.case_resource_key(outer_resolved_case_id)
        pending_path = module.get_pending_path(outer_resolved_case_id)
        canonical_path = module.get_canonical_path(outer_resolved_case_id)

        # PRE-LOCK composite snapshot - recorded as this attempt's
        # `pre_hash` and re-verified under the lock (see this module's
        # own header comment, "PRE-STATE SNAPSHOT"). Read AFTER the
        # outer authz has already succeeded, never before it.
        pre_lock_snapshot = _compute_precondition_snapshot(pending_path, canonical_path)

        intent = MutationIntent(
            actor_type="iam_user",
            actor_ref=str(principal.user_id),
            resource_key=resource_key,
            action_family=action_family_for(row_key),
            target_ref=f"{row_key}.canonical",
            target_state="approved",
            # FILESYSTEM EVIDENCE (composite) - recorded and
            # re-verified, deliberately NOT part of mutation identity.
            pre_hash=pre_lock_snapshot.composite_digest,
            # The REQUEST's own claim - part of mutation identity, so
            # an honest retry always recomputes the same key even if
            # the filesystem has moved on.
            pre_revision=expected_hash,
        )
        # Pure function of `intent` alone (see mutation_guard.py's own
        # docstring) - `run_mutation()` independently recomputes the
        # IDENTICAL value internally; calling it here too, ourselves,
        # requires no coordination and cannot drift from that internal
        # value. This is what lets `writer_callback` (below) pass a real
        # `mutation_idempotency_key`/`mutation_resource_key` into
        # `module.run_approve()` (Row 19C-2a's own keyword-only audit-
        # binding parameters) WITHOUT `run_mutation()` itself ever
        # exposing that internal value through its callback signatures
        # (which take no arguments).
        idempotency_key_for_audit = compute_idempotency_key(intent)

        def authz_callback() -> None:
            # ========================================================
            # INNER (AUTHORITATIVE) AUTHORIZATION - step 2 of the
            # dual-authz contract. `run_mutation()` invokes this as the
            # FIRST thing it does, with the resource lock already held
            # and strictly BEFORE any journal gate/idempotency SQL. The
            # outer check above was necessarily a pre-lock read of
            # mutable IAM state; this one is the decision that actually
            # gates the writer.
            # ========================================================
            inner_resolved_case_id = _authz.authorize_case_access(
                principal, case_id, "mutate", repository=repository,
            )
            if inner_resolved_case_id != outer_resolved_case_id:
                raise ResolvedCaseIdMismatchError(
                    f"outer (pre-lock) authorization resolved case_id={outer_resolved_case_id!r} "
                    f"but the inner (under-lock) authorization resolved {inner_resolved_case_id!r} - "
                    "the already-locked resource_key and the recorded pre_hash snapshot describe a "
                    "different case than the authoritative check just approved; refusing to proceed"
                )

        def precondition_callback() -> None:
            # Reached ONLY when a genuinely NEW mutation is needed:
            # `run_mutation()` calls this at step 5 of its own
            # AUTHORITATIVE ORDER - after the inner authz (step 2), the
            # journal gate (step 3) and the idempotency lookup (step 4,
            # which returns/raises for every replay, conflict and prior
            # failure without ever reaching here), and strictly BEFORE
            # step 6 persists a `prepared` row. So every raise below
            # leaves ZERO journal rows and never invokes the writer.
            if not pending_path.exists():
                raise PendingNotFoundError(f"Pending bulunamadı: {pending_path}")

            under_lock_snapshot = _compute_precondition_snapshot(pending_path, canonical_path)

            if under_lock_snapshot.composite_digest != pre_lock_snapshot.composite_digest:
                raise PreconditionRaceDetectedError(
                    "Bu onay isteği case kilidini beklerken ilgili dosyalar DEĞİŞTİ "
                    "(pending veya canonical durumu artık aynı değil; kilit öncesi snapshot: "
                    f"pending={pre_lock_snapshot.pending_sha256}, "
                    f"canonical={pre_lock_snapshot.canonical_presence}/{pre_lock_snapshot.canonical_sha256}; "
                    f"kilit altındaki snapshot: pending={under_lock_snapshot.pending_sha256}, "
                    f"canonical={under_lock_snapshot.canonical_presence}/{under_lock_snapshot.canonical_sha256}). "
                    "Onay iptal edildi, HİÇBİR değişiklik yapılmadı - lütfen sayfayı yenileyip tekrar deneyin."
                )

            if under_lock_snapshot.pending_sha256 != expected_hash:
                raise StaleViewError(
                    "Bu review ekranı açıldıktan sonra pending dosya değişti "
                    f"(o zamanki hash: {expected_hash}, şimdiki: {under_lock_snapshot.pending_sha256}). "
                    "Onay iptal edildi - lütfen sayfayı yenileyip tekrar deneyin."
                )

        def writer_callback() -> _mutation_coordinator.WriterResult:
            stdout_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture):
                module.run_approve(
                    outer_resolved_case_id,
                    mutation_idempotency_key=idempotency_key_for_audit,
                    mutation_resource_key=resource_key,
                )
            observed_post_hash = sha256_file(canonical_path)
            return _mutation_coordinator.WriterResult(
                observed_post_hash=observed_post_hash, result=stdout_capture.getvalue(),
            )

        conn_factory = conn_factory or _default_conn_factory
        conn = conn_factory()
        advisory_lock_id = _mutation_lock.acquire_case_lock_session(conn, outer_resolved_case_id)
        try:
            outcome = _mutation_coordinator.run_mutation(
                conn, intent,
                actor_user_id=principal.user_id,
                authz_callback=authz_callback,
                precondition_callback=precondition_callback,
                writer_callback=writer_callback,
            )

            reviews_dir = canonical_path.parent / "reviews"

            if outcome.replayed:
                # See this module's own header comment ("FIVE EXACT
                # BINDINGS") - independent corroboration is required
                # ONLY on a replay (the writer was NOT re-invoked; a
                # fresh execution's own successful writer return is
                # already sufficient proof on its own).
                #
                # The returned value is the FRESHLY COMPUTED, JUST-
                # VERIFIED canonical hash and it is what this function
                # reports as `canonical_hash` below. It is deliberately
                # NOT discarded in favour of the journal's own stored
                # `observed_post_hash`: binding 3b has just proven the
                # two are equal, so reporting the verified one is both
                # equivalent AND the only one this request actually
                # checked - a hash the lawyer's success page names must
                # never be a value nothing here corroborated.
                verified_canonical_hash = _verify_completed_replay_audit_binding(
                    canonical_path,
                    journal_state=outcome.state,
                    journal_id=outcome.journal_id,
                    idempotency_key=idempotency_key_for_audit,
                    resource_key=resource_key,
                    observed_post_hash=outcome.observed_post_hash,
                    pre_revision=intent.pre_revision,
                )
                stdout_text = ""
            else:
                stdout_text: str = outcome.result  # the stdout writer_callback captured, verbatim
                # A FRESH execution's `observed_post_hash` was computed
                # by `writer_callback` itself, moments earlier, from the
                # artefact the real writer had just finished writing -
                # so it is already a just-verified value from THIS
                # request, not an inherited journal claim.
                verified_canonical_hash = outcome.observed_post_hash

            audit_path = find_latest_audit(reviews_dir)

            return CaseScopedApprovalResult(
                row_key=row_key,
                canonical_path=canonical_path,
                canonical_hash=verified_canonical_hash,
                audit_path=audit_path,
                stdout=stdout_text,
                journal_id=outcome.journal_id,
                replayed=outcome.replayed,
            )
        finally:
            # ============================================================
            # CLEANUP THAT CAN NEVER MASK THE OUTCOME (ROW 19C-2a FINAL
            # AUDIT REMEDIATION).
            #
            # By the time this runs, whatever `run_mutation()` returned
            # or raised is ALREADY the final, durable (or cleanly-denied)
            # outcome of this call - a `completed` journal row is
            # committed on this autocommit connection and is not going
            # to be un-committed by anything here. So NOTHING in this
            # block may propagate: an exception raised from a `finally`
            # REPLACES whatever was already in flight, which would mean
            # either (a) reporting a redacted failure for an approval
            # that genuinely succeeded and is journaled `completed`, or
            # (b) silently swallowing a real primary exception. Both are
            # misreports of a legal mutation's true outcome, so both are
            # structurally prevented rather than merely avoided.
            #
            # Previously ONLY the `released is False` RETURN was
            # handled. `release_lock_session()` executes real SQL
            # (`SELECT pg_advisory_unlock(...)`) and can therefore also
            # RAISE - e.g. on a connection that died between the commit
            # and this cleanup - and that raise both masked the outcome
            # AND skipped `conn.close()` entirely. Three separate
            # guards now close that:
            #   1. the release call is wrapped, so a raise is logged and
            #      dropped, never propagated;
            #   2. the `False` return keeps its EXISTING, documented
            #      visible-but-non-raising behavior (see
            #      `mutation_lock.release_lock_session`'s own contract
            #      and `mutation_registry.reconcile_and_apply_journal_
            #      entry`'s matching discipline) - unchanged;
            #   3. `conn.close()` lives in its OWN nested `finally`, so
            #      it runs in every one of those paths, and its own
            #      failure is likewise logged and dropped.
            # Every log goes through `_log_critical_safely`, which
            # cannot raise either.
            # ============================================================
            try:
                try:
                    released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
                except Exception as release_error:
                    _log_critical_safely(
                        f"CRITICAL: approve_case_scoped_mutation() RAISED while releasing the session "
                        f"lock for resource_key={resource_key!r} "
                        f"(advisory_lock_id={advisory_lock_id!r}): {release_error!r} - this process may "
                        "still hold the resource's advisory lock. The approval outcome itself is "
                        "ALREADY final and is being reported unchanged; investigate this out of band"
                    )
                else:
                    if not released:
                        _log_critical_safely(
                            f"CRITICAL: approve_case_scoped_mutation() failed to release the session "
                            f"lock for resource_key={resource_key!r} "
                            f"(advisory_lock_id={advisory_lock_id!r}) - this process may still hold "
                            "the resource's advisory lock; investigate out of band"
                        )
            finally:
                try:
                    conn.close()
                except Exception as close_error:
                    _log_critical_safely(
                        f"CRITICAL: approve_case_scoped_mutation() failed to close its journal/lock "
                        f"connection for resource_key={resource_key!r}: {close_error!r} - the approval "
                        "outcome itself is unaffected and is being reported unchanged; investigate "
                        "this out of band"
                    )
    finally:
        # Closes ONLY a repository connection THIS module opened
        # itself (see `_resolve_authz_repository()`) - an injected one
        # is left entirely alone. Wrapped so a failure here can never
        # replace an exception already propagating from the block above.
        try:
            close_repository()
        except Exception as error:
            _log_critical_safely(
                f"CRITICAL: approve_case_scoped_mutation() failed to close its own IAM authz "
                f"connection ({error!r}) - investigate out of band; the approval outcome itself is "
                "unaffected and is being reported unchanged"
            )
