# ============================================================
# VERGİ AI - MUTATION COORDINATOR CORE (Row 19C-1)
#
# Orchestrates ui.services.mutation_lock's session-level lock
# primitives and the mutation.mutation_journal state machine around a
# caller-supplied writer callback. This module owns ZERO raw lock SQL
# itself (`mutation_lock.py` remains the single low-level lock
# implementation owner, per the approved plan) and performs the
# file/DB mutation for NO real production writer this turn -
# `run_mutation()` is exercised only against fake writer/authz/
# precondition callbacks in ui/tests/test_mutation_coordinator_isolated.py
# and ui/tests/test_mutation_journal_postgres.py. Connecting a real
# writer (approval_registry.case_scoped_approve,
# review_registry.apply_transition, drafting_request.save_lawyer_input,
# or any CLI entry point) is explicitly Row 19C-2+ scope.
#
# AUTHORITATIVE ORDER (Row 19C-1 TARGETED CONTRACT REMEDIATION - this
# order, and every rule below it, supersedes this module's own first
# draft; see each step's comment for why):
#   1. Acquire the SESSION-level resource lock (the CALLER's job -
#      mutation_lock.acquire_case_lock_session/acquire_global_lock_session,
#      never pg_advisory_xact_lock, which is Row 19B's IAM-only,
#      unrelated lock path - `run_mutation()` itself never acquires or
#      releases this lock; see its own docstring).
#   2. Under that lock, the unresolved-journal gate
#      (`_journal_gate_check`) - is ANY prepared/executing/
#      reconciliation_required row already open for this resource_key?
#   3. The ALL-STATE idempotency lookup (`_idempotency_lookup`) -
#      `idempotency_key` is UNCONDITIONALLY unique across this table's
#      ENTIRE history (0003_mutation_journal.sql's plain
#      `UNIQUE(idempotency_key)` table constraint - never a partial
#      index scoped to "live" rows only), so there is NEVER more than
#      one row, in ANY state including `failed`, for a given key. A
#      caller MAY also run a cheap pre-lock version of steps 2-3 as a
#      fast-reject optimization, but `run_mutation()` itself never
#      trusts anything computed before the lock was acquired.
#   4. `authz_callback()`.
#   5. `precondition_callback()` (expected pre-hash/revision/freshness).
#   6. ONLY if BOTH 4 and 5 succeed: persist a `prepared` journal row -
#      its own, immediately-durable write (this connection is
#      autocommit, see ui.services.db.get_session_lock_connection). A
#      denial from EITHER callback creates NO journal row at all - an
#      authz/precondition rejection is not a mutation ATTEMPT in this
#      journal's sense; it is the security-event layer's concern (or a
#      future one), never `mutation.mutation_journal`'s.
#   7. Immediately before invoking the writer callback, persist
#      `executing` - also its own immediately-durable write.
#   8. Invoke the writer callback OUTSIDE any Postgres transaction
#      (this coordinator's connection is autocommit throughout - there
#      is no ambient transaction to be "outside" of, by construction),
#      while the session lock is still held.
#   9. On a PROVEN post-state (the writer reports one - see
#      `WriterResult`), persist `completed`. On ANY exception from the
#      writer - whatever its type, class name, or message - persist
#      `reconciliation_required`, NEVER `failed`: an exception raised
#      by the writer is not evidence of anything about the file's
#      actual state, and this module never treats it as such. The
#      ONLY way an attempt that reached the writer boundary can ever
#      become `failed` is LATER, out-of-band, when
#      ui.services.mutation_registry.reconcile_journal_entry() (acting
#      under the SAME resource lock) obtains independent domain-
#      validator/hash/audit evidence that the pre-state was preserved
#      (`pre_state_confirmed_unchanged`) - never from inspecting the
#      writer's own raised exception.
#  10. Always release the lock and close the connection, in `finally`
#      blocks, however step 8 turned out - that is the CALLER's
#      responsibility (see `run_mutation()`'s own docstring); this
#      module never acquires or releases the lock itself.
#
# IDEMPOTENCY (full contract - see `_idempotency_lookup`/`run_mutation`
# for the code): same `idempotency_key`, ANY existing row, in ANY
# state, with a DIFFERENT `request_fingerprint` is ALWAYS fail-closed
# (`IdempotencyConflictError`) - state is irrelevant to this check.
# Same `idempotency_key` + SAME `request_fingerprint` against an
# EXISTING row:
#   - `completed`   -> safe replay: the stored result is returned,
#                      the writer is NEVER re-invoked.
#   - `prepared`/`executing`/`reconciliation_required`
#                   -> refused as unresolved/in-progress (in practice
#                      always already caught by the resource-level
#                      `_journal_gate_check` first, since this
#                      idempotency_key's own resource_key is
#                      necessarily the same one being gated - this
#                      branch exists for completeness/defense in depth,
#                      not because it is the common path); the writer
#                      is NEVER invoked.
#   - `failed`      -> a TERMINAL, PERMANENT outcome for this exact
#                      idempotency_key: `PriorAttemptFailedError` is
#                      raised, deterministically carrying that row's
#                      own `journal_id`/`failure_code`/`resolution_code`
#                      - NO new journal row is ever created for this
#                      key again, and the writer is NEVER invoked. A
#                      client that wants to retry a failed operation
#                      MUST produce a NEW `MutationIntent` whose
#                      identity fields differ (e.g. a freshly re-read
#                      `pre_hash`/`pre_revision`) so it hashes to a
#                      DIFFERENT `idempotency_key` - this module never
#                      manufactures a retry on the caller's behalf.
# ============================================================

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mutation_guard import (  # noqa: E402
    MutationIntent,
    compute_idempotency_key,
    compute_request_fingerprint,
    validate_intent,
)

from . import mutation_lock as _mutation_lock  # noqa: E402

DEFAULT_STALE_EXECUTING_AFTER_SECONDS = 300  # 5 minutes - configurable per call, never auto-resolves anything


class MutationCoordinatorError(Exception):
    """Base class for this module's own errors (distinct from the
    caller-supplied authz/precondition callbacks' own exception types,
    which `run_mutation()` deliberately does not catch or reclassify -
    see `run_mutation()`'s docstring)."""


class ResourceGatedError(MutationCoordinatorError):
    """Raised when an unresolved (`prepared`/`executing`/
    `reconciliation_required`) journal entry already exists for this
    resource_key - a NEW mutation on that resource is refused,
    fail-closed, without ever invoking the writer callback."""


class IdempotencyConflictError(MutationCoordinatorError):
    """Raised when a journal row already exists for this
    `idempotency_key` - in ANY state, `failed` included, since
    `idempotency_key` is unconditionally unique across this table's
    entire history - with a DIFFERENT `request_fingerprint`. Refused,
    fail-closed, without ever invoking the writer callback."""


class PriorAttemptFailedError(MutationCoordinatorError):
    """Raised when this EXACT `idempotency_key` already has a
    TERMINAL `failed` row on record (necessarily with the SAME
    `request_fingerprint` - a different fingerprint raises
    `IdempotencyConflictError` instead, checked first). This is a
    deterministic, permanent outcome for that idempotency_key: no new
    journal row is created, and the writer callback is NEVER invoked.
    A caller that wants to retry must construct a NEW `MutationIntent`
    whose identity fields differ enough to hash to a different
    `idempotency_key` (see `src/mutation_guard.py`) - this module never
    retries on the caller's behalf and never reuses a `failed` row's
    key for a fresh attempt."""

    def __init__(self, *, journal_id: int, failure_code: str | None, resolution_code: str | None):
        self.journal_id = journal_id
        self.failure_code = failure_code
        self.resolution_code = resolution_code
        super().__init__(
            f"idempotency_key already has a TERMINAL 'failed' result (journal_id={journal_id}, "
            f"failure_code={failure_code!r}, resolution_code={resolution_code!r}) - "
            "the client must generate a NEW idempotency key to retry; this attempt was NOT re-invoked"
        )


@dataclass(frozen=True)
class WriterResult:
    """What a writer callback must return on success. `observed_post_hash`
    may be None only when the domain has no meaningful post-mutation
    hash (rare) - even then, the writer's mere successful return is
    itself the completion proof for THIS call (unlike reconciliation,
    which never accepts an observed hash alone as authoritative - see
    ui.services.mutation_registry); `result` is whatever the writer
    itself would normally have returned to ITS OWN caller (opaque to
    this module, replayed verbatim on a safe same-key/same-fingerprint
    replay)."""

    observed_post_hash: str | None
    result: object = None


@dataclass(frozen=True)
class MutationOutcome:
    journal_id: int
    state: str  # 'completed' - the only state run_mutation() itself ever returns (else it raises)
    result: object
    observed_post_hash: str | None
    replayed: bool  # True if the writer was NOT re-invoked (safe same-key/same-fingerprint replay)


def _journal_gate_check(conn, resource_key: str) -> None:
    """Authoritative post-lock check: does an unresolved journal entry
    already exist for this resource_key? A caller MAY have already run
    a cheap version of this before taking the lock as a fast-reject
    optimization - that earlier result is NEVER trusted here; this
    query always re-runs for real, lock held."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM mutation.mutation_journal "
            "WHERE resource_key = %s "
            "AND state IN ('prepared', 'executing', 'reconciliation_required') "
            "LIMIT 1",
            (resource_key,),
        )
        row = cur.fetchone()
    if row is not None:
        raise ResourceGatedError(
            f"resource_key={resource_key!r} has an unresolved mutation journal entry; refusing a new mutation"
        )


def _idempotency_lookup(conn, idempotency_key: str):
    """Returns None if NO prior journal row exists for this
    `idempotency_key` at all. Otherwise returns that row's
    (id, state, request_fingerprint, observed_post_hash, failure_code,
    resolution_code) - the caller decides what to do (safe replay /
    fail-closed conflict / terminal-failure error / unresolved-block).
    Covers ALL states unconditionally: `idempotency_key` is
    UNCONDITIONALLY unique across `mutation.mutation_journal`'s ENTIRE
    history (0003's plain `UNIQUE(idempotency_key)` table constraint,
    never a partial index) - there is NEVER more than one row for a
    given key, so a plain `fetchone()` is always unambiguous, `failed`
    rows included."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, state, request_fingerprint, observed_post_hash, failure_code, resolution_code "
            "FROM mutation.mutation_journal WHERE idempotency_key = %s",
            (idempotency_key,),
        )
        return cur.fetchone()


def _insert_prepared(conn, intent: MutationIntent, *, actor_user_id, idempotency_key, request_fingerprint) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO mutation.mutation_journal ("
            "  resource_key, action_family, actor_user_id, actor_label, target_ref, target_state,"
            "  pre_hash, pre_revision, idempotency_key, request_fingerprint, state"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'prepared') "
            "RETURNING id",
            (
                intent.resource_key, intent.action_family, actor_user_id, intent.actor_ref,
                intent.target_ref, intent.target_state, intent.pre_hash, intent.pre_revision,
                idempotency_key, request_fingerprint,
            ),
        )
        (journal_id,) = cur.fetchone()
    return journal_id


def _mark_executing(conn, journal_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE mutation.mutation_journal SET state = 'executing', executing_at = now() WHERE id = %s",
            (journal_id,),
        )


def _mark_completed(conn, journal_id: int, observed_post_hash) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE mutation.mutation_journal "
            "SET state = 'completed', observed_post_hash = %s, resolved_at = now() WHERE id = %s",
            (observed_post_hash, journal_id),
        )


def _mark_reconciliation_required(conn, journal_id: int) -> None:
    # No resolved_at - 0003's own CHECK constraint requires
    # resolved_at IS NULL for this state, matching the fact that
    # nothing has actually been resolved yet.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE mutation.mutation_journal SET state = 'reconciliation_required' WHERE id = %s",
            (journal_id,),
        )


def run_mutation(
    conn,
    intent: MutationIntent,
    *,
    actor_user_id: int | None,
    authz_callback: Callable[[], None],
    precondition_callback: Callable[[], None],
    writer_callback: Callable[[], WriterResult],
) -> MutationOutcome:
    """Runs one coordinated, journaled, idempotent mutation attempt.

    `conn` MUST already hold the session-level resource lock for
    `intent.resource_key` (i.e. the caller already called
    `mutation_lock.acquire_case_lock_session`/`acquire_global_lock_session`
    on it) - `run_mutation()` does not acquire or release the lock
    itself (that stays the CALLER's responsibility, so a caller can
    hold the same lock across several coordinator calls if it ever
    needs to - Row 19C-1 does not require that shape yet, but nothing
    here forecloses it).

    `authz_callback` and `precondition_callback` are called AFTER the
    (already-held) lock and AFTER the journal-gate/idempotency checks
    below, but BEFORE any journal row for this attempt is created at
    all. `run_mutation()` does not catch, suppress, or reclassify
    whatever either one raises - the caller's own exception instance/
    type/message reaches its own caller completely unchanged - and it
    writes NOTHING to `mutation.mutation_journal` for that denial: an
    authz/precondition rejection never becomes a mutation attempt row
    in this journal's sense (see this module's own header comment).

    A `prepared` row is created ONLY once both callbacks have already
    succeeded, and `writer_callback` is invoked only after that row's
    `prepared` -> `executing` transition is durably recorded. ANY
    exception from `writer_callback` - regardless of its type, class
    name, or message, which are NEVER treated as evidence of anything -
    is classified `reconciliation_required` (never `failed`): by the
    time `executing` was written, this module cannot itself prove
    whether the writer's own file mutation took effect before it
    raised, so it never guesses. The caller's original exception is
    re-raised unchanged. The ONLY path back to `failed` for a row that
    ever reached `executing` is later, independent reconciliation with
    real domain evidence (`ui.services.mutation_registry`) - never
    anything decided here.
    """

    validate_intent(intent)
    idempotency_key = compute_idempotency_key(intent)
    request_fingerprint = compute_request_fingerprint(intent)

    _journal_gate_check(conn, intent.resource_key)

    existing = _idempotency_lookup(conn, idempotency_key)
    if existing is not None:
        existing_id, existing_state, existing_fingerprint, existing_post_hash, existing_failure_code, existing_resolution_code = existing
        if existing_fingerprint != request_fingerprint:
            raise IdempotencyConflictError(
                f"idempotency_key={idempotency_key!r} already exists with a different request_fingerprint "
                f"(journal_id={existing_id}, state={existing_state!r}) - refusing to proceed"
            )
        if existing_state == "completed":
            return MutationOutcome(existing_id, "completed", None, existing_post_hash, replayed=True)
        if existing_state == "failed":
            # Terminal and PERMANENT for this exact idempotency_key -
            # never re-attempted, never given a new row. See
            # PriorAttemptFailedError's own docstring.
            raise PriorAttemptFailedError(
                journal_id=existing_id, failure_code=existing_failure_code, resolution_code=existing_resolution_code,
            )
        # existing_state in ('prepared', 'executing', 'reconciliation_required'):
        # already unresolved - in practice ALWAYS already caught by
        # `_journal_gate_check` above (this idempotency_key's own
        # resource_key is necessarily the one just gated), kept here
        # for completeness/defense in depth rather than as the common
        # path - see this module's own header comment.
        raise ResourceGatedError(
            f"idempotency_key={idempotency_key!r} already has an UNRESOLVED ({existing_state}) journal entry "
            f"(journal_id={existing_id}) - refusing a duplicate/concurrent attempt"
        )

    authz_callback()
    precondition_callback()

    journal_id = _insert_prepared(
        conn, intent, actor_user_id=actor_user_id,
        idempotency_key=idempotency_key, request_fingerprint=request_fingerprint,
    )

    _mark_executing(conn, journal_id)

    try:
        writer_result = writer_callback()
    except Exception:
        # ANY exception here - whatever its type/class/message - is
        # never evidence of anything about the file's actual state.
        # Never guess `failed` here; only reconciliation, backed by
        # real domain evidence, may resolve this.
        _mark_reconciliation_required(conn, journal_id)
        raise

    _mark_completed(conn, journal_id, writer_result.observed_post_hash)
    return MutationOutcome(journal_id, "completed", writer_result.result, writer_result.observed_post_hash, replayed=False)


def is_stale_executing(executing_at_epoch_seconds: float, *, now=None, threshold_seconds: int = DEFAULT_STALE_EXECUTING_AFTER_SECONDS) -> bool:
    """Pure helper: has an `executing` row been running longer than
    `threshold_seconds`? This NEVER changes the row's state by itself
    - staleness only marks a row as ELIGIBLE for reconciliation
    (ui.services.mutation_registry); the resource stays gated
    (`_journal_gate_check` above) until reconciliation actually
    resolves it, stale or not."""
    now = time.time() if now is None else now
    return (now - executing_at_epoch_seconds) > threshold_seconds
