# ============================================================
# VERGİ AI - MUTATION GUARD (Row 19C-1)
#
# Pure value objects/validators shared by CLI and web mutation call
# sites (both current and future — Row 19C-1 does NOT wire any real
# writer to this module yet). This module:
#
#   - carries NO UI dependency (`ui.*` is never imported here) and NO
#     `src/*` domain dependency either — it sits BELOW both, so either
#     side can import it without a circular or layering violation;
#   - performs NO file, database or network I/O of any kind — it is
#     100% deterministic, pure Python;
#   - defines the ONE canonical `MutationIntent` shape and the two
#     deterministic digests derived from it (`idempotency_key` and
#     `request_fingerprint`) that `ui/services/mutation_coordinator.py`
#     and `ui/services/mutation_registry.py` both key off of — neither
#     of those modules re-derives or duplicates this logic.
#
# WHY TWO DIGESTS, NOT ONE
# -------------------------
# `idempotency_key` = sha256(actor_type, actor_ref, resource_key,
#   action_family, target_ref, pre_hash, pre_revision) — the identity
#   of "one logical operation slot": the same actor performing the
#   same action on the same target from the same observed pre-state.
#   A caller that legitimately retries the EXACT same request (e.g. a
#   network retry re-submitting an unchanged form) always recomputes
#   the SAME idempotency_key.
#
# `request_fingerprint` = sha256(everything idempotency_key covers,
#   PLUS target_state) — the identity of "this exact requested
#   outcome". Two requests can share an idempotency_key while
#   disagreeing on `target_state` (e.g. one caller means "confirm",
#   another means "reject", for the same record from the same
#   pre-state) — that specific case is exactly what the coordinator's
#   "same key, different fingerprint -> fail-closed" rule exists to
#   catch (see ui/services/mutation_coordinator.py). A same-key,
#   same-fingerprint replay is safe (identical intended outcome) and
#   may return the stored result without re-invoking the writer.
#
# WHAT NEVER GOES INTO EITHER DIGEST (OR ANYWHERE IN THIS MODULE)
# -----------------------------------------------------------------
# `MutationIntent`'s field set is deliberately narrow and closed —
# there is no "raw request", "note", "body" or similar free-text
# field anywhere on it, BY CONSTRUCTION, not by convention. A caller
# cannot accidentally fingerprint a legal document's free text, a
# token, a cookie or a secret, because there is no field to put it in.
# Validation error messages below only ever name a field, never echo
# a rejected value's content.
# ============================================================

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


class InvalidMutationIntentError(Exception):
    """Raised by `validate_intent()` (and, transitively, by
    `compute_idempotency_key`/`compute_request_fingerprint`, which
    both validate before hashing) when a `MutationIntent` is
    structurally invalid. The message names the offending field only —
    never the value itself, since a caller could (in principle, this
    round aside) pass an oversized or malformed field here."""


# ----------------------------------------------------------------
# Fixed vocabularies. Extending these is expected as real writers are
# connected in later Row 19C-2+ turns (each such change is its own
# reviewed, additive edit) — but the vocabularies themselves must
# always stay CLOSED allowlists, never free text, matching this
# project's existing closed-reason_code convention
# (iam.security_events, db/migrations/0001_iam_schema.sql).
# ----------------------------------------------------------------

ALLOWED_ACTOR_TYPES = frozenset({
    "iam_user",     # a resolved iam.users.id — the Row 19B web/session identity model
    "cli_service",  # the approved Row 19C CLI identity model — a named, non-session service actor
})

# `failure_code`: set only for a `failed` journal row. Under the Row
# 19C-1 TARGETED CONTRACT REMEDIATION, a `failed` journal row can only
# ever be produced two ways: (1) the coordinator's own idempotency
# lookup finds a PRIOR `failed` row for this exact idempotency_key and
# deterministically re-reports it (no new row, writer never called —
# see `PriorAttemptFailedError` in mutation_coordinator.py), which
# simply carries forward the ORIGINAL failed row's own failure_code;
# or (2) an out-of-band reconciliation adapter, running under the same
# resource lock, proves with real evidence (domain validator/hash/
# audit) that the pre-state was preserved (either after an earlier
# `reconciliation_required` outcome, or — Row 19C-1 RECONCILIATION
# ATOMICITY REMEDIATION — directly from a `prepared` row stuck by a
# crash between its own commit and the `executing` transition; see
# ui/services/mutation_registry.py). A writer's own exception is NEVER
# proof of anything and never by itself produces `failed` — every
# exception raised after the writer boundary is crossed becomes
# `reconciliation_required`, unconditionally, regardless of the
# exception's class or message (see mutation_coordinator.py's
# ordering contract). There is deliberately no
# "writer_raised_before_executing"-style code here: the writer is
# never invoked before `executing` is persisted, so no such case
# exists to name.
#
# RESERVED / CURRENTLY UNUSED — ROW 19C-1 RECONCILIATION ATOMICITY
# REMEDIATION NOTE: none of the three codes below is written by any
# code path in this project today. `run_mutation()` never persists a
# `failed` row of its own (an authz/precondition denial creates NO
# journal row at all — see mutation_coordinator.py's own header — and
# an idempotency conflict is likewise refused before any row is
# written), and reconciliation's own `failed` outcomes use
# `RESOLUTION_CODE_FAILED_PRE_STATE_UNCHANGED` /
# `RESOLUTION_CODE_FAILED_PREPARED_NEVER_EXECUTED` below, not a
# `failure_code`. This vocabulary is kept, explicitly documented as
# RESERVED FOR A FUTURE PRODUCER (e.g. a later Row 19C-2+ turn that
# connects a real writer and decides some failure classes should be
# journaled as `failed` with a `failure_code` directly, rather than via
# reconciliation) — never removed silently and never given an invented
# call site just to make it "used". Do not read the mere presence of a
# code here as evidence that anything in this codebase currently
# produces it.
FAILURE_CODES = frozenset({
    "authz_denied",
    "precondition_failed",
    "idempotency_conflict",
})

# `resolution_code`: set only by reconciliation (ui/services/
# mutation_registry.py), explaining how an unresolved
# (`prepared`/`executing`/`reconciliation_required`) journal entry was
# resolved — never set by the coordinator's own first pass. Named
# constants (not just membership in the frozenset below) so
# `mutation_registry.py` never needs to hardcode either string as a
# literal.
RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED = "reconciled_completed_post_state_verified"
RESOLUTION_CODE_FAILED_PRE_STATE_UNCHANGED = "reconciled_failed_pre_state_confirmed_unchanged"

# ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION addition: distinct
# from RESOLUTION_CODE_FAILED_PRE_STATE_UNCHANGED above so an auditor
# reading `resolution_code` can tell the two `failed` provenances
# apart — this one is used ONLY when the row being resolved was still
# `prepared` (the writer boundary was NEVER crossed at all — see
# mutation_coordinator.py's ordering contract), never for a row that
# reached `executing`/`reconciliation_required` first.
RESOLUTION_CODE_FAILED_PREPARED_NEVER_EXECUTED = "reconciled_failed_prepared_never_executed"

RESOLUTION_CODES = frozenset({
    RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
    RESOLUTION_CODE_FAILED_PRE_STATE_UNCHANGED,
    RESOLUTION_CODE_FAILED_PREPARED_NEVER_EXECUTED,
})

_REQUIRED_STRING_FIELDS = ("actor_type", "actor_ref", "resource_key", "action_family", "target_ref")
_OPTIONAL_STRING_FIELDS = ("target_state", "pre_hash", "pre_revision")


@dataclass(frozen=True)
class MutationIntent:
    """The one canonical description of "what mutation is being
    attempted" — everything `ui/services/mutation_coordinator.py` and
    `ui/services/mutation_registry.py` need to gate, journal and (on
    reconciliation) re-derive an idempotency decision, and NOTHING
    else. Every field is a short identifier/code/hash string; there is
    intentionally no field for free text, a request body, a token, a
    cookie or a secret of any kind.

    actor_type / actor_ref: see ALLOWED_ACTOR_TYPES. `actor_ref` is a
        short, stable identifier for the actor (e.g. the IAM user id
        as a string, or a fixed CLI service-account name under the
        approved CLI identity model) — never a display name and never
        anything derived from user-entered text.
    resource_key: the exact `mutation.mutation_resources.resource_key`
        this mutation will lock (e.g. "case:case_0001", "global:
        rag_index") — already fully resolved; this module does not
        build or validate case_id/resource_key shapes itself (that
        stays `ui.services.paths.resolve_case_id()` /
        `ui.services.mutation_lock.case_resource_key()`'s job).
    action_family: a short, stable label for which production
        mutation family this is (e.g. "evidence.layer_a_promote") —
        a fixed code the caller defines, not free text.
    target_ref: a short, stable identifier for what is being mutated
        within the resource (e.g. a case-relative canonical path
        string, or a `(review_kind, record_id)` pair rendered as
        text) — never raw file content.
    target_state: optional short code for the requested end state
        (e.g. "confirmed", "rejected") — None when the action has no
        such notion (e.g. a pending-generation run).
    pre_hash / pre_revision: optional short strings describing the
        expected pre-mutation state (typically a sha256 hex digest of
        the artefact being mutated, or a revision/version marker) —
        both None is valid and means "no prior artefact existed yet"
        (first-write case), matching this project's existing
        `NO_EXISTING_INPUT_SENTINEL`-style pattern
        (ui/services/drafting_request.py) rather than inventing a
        second one here.
    """

    actor_type: str
    actor_ref: str
    resource_key: str
    action_family: str
    target_ref: str
    target_state: str | None = None
    pre_hash: str | None = None
    pre_revision: str | None = None


def validate_intent(intent: MutationIntent) -> None:
    """Fail-closed structural validation. Raises
    `InvalidMutationIntentError` naming the first offending field —
    never logs or echoes any field's actual value."""

    if not isinstance(intent, MutationIntent):
        raise InvalidMutationIntentError("intent must be a MutationIntent instance")

    for field_name in _REQUIRED_STRING_FIELDS:
        value = getattr(intent, field_name)
        if not isinstance(value, str) or not value:
            raise InvalidMutationIntentError(f"{field_name} must be a non-empty string")

    for field_name in _OPTIONAL_STRING_FIELDS:
        value = getattr(intent, field_name)
        if value is not None and (not isinstance(value, str) or not value):
            raise InvalidMutationIntentError(
                f"{field_name} must be None or a non-empty string, never an empty string"
            )

    if intent.actor_type not in ALLOWED_ACTOR_TYPES:
        raise InvalidMutationIntentError("actor_type is not one of the allowed actor types")

    if (intent.pre_hash is None) != (intent.pre_revision is None):
        # Either both describe a known prior state, or neither does —
        # a half-specified pre-state is treated as a caller bug, not
        # silently accepted as "first write".
        raise InvalidMutationIntentError(
            "pre_hash and pre_revision must be both None (first write) or both set"
        )


def _canonical_json(fields: dict) -> bytes:
    """Deterministic, canonical serialization: sorted keys, no
    whitespace, ASCII-escaped — the same MutationIntent always
    produces byte-identical input to sha256, on any platform, any
    Python version, any dict insertion order."""
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _identity_fields(intent: MutationIntent) -> dict:
    return {
        "actor_type": intent.actor_type,
        "actor_ref": intent.actor_ref,
        "resource_key": intent.resource_key,
        "action_family": intent.action_family,
        "target_ref": intent.target_ref,
        "pre_hash": intent.pre_hash,
        "pre_revision": intent.pre_revision,
    }


def compute_idempotency_key(intent: MutationIntent) -> str:
    """sha256 hex digest over the operation-SLOT identity (everything
    except `target_state`) — see the module docstring for the full
    rationale. Validates `intent` first (fail-closed)."""
    validate_intent(intent)
    return hashlib.sha256(_canonical_json(_identity_fields(intent))).hexdigest()


def compute_request_fingerprint(intent: MutationIntent) -> str:
    """sha256 hex digest over the FULL requested outcome (the slot
    identity plus `target_state`) — see the module docstring. Two
    intents that differ ONLY in a field not carried on MutationIntent
    at all (there are none, by construction) can never produce
    different fingerprints for "the same" request; two intents that
    differ in `target_state` always do."""
    validate_intent(intent)
    fields = _identity_fields(intent)
    fields["target_state"] = intent.target_state
    return hashlib.sha256(_canonical_json(fields)).hexdigest()
