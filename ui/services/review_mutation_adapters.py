# ============================================================
# VERGİ AI - ROW 19C-2b: REVIEW MUTATION RECONCILIATION ADAPTERS
# (Layer B).
#
# One `ui.services.mutation_registry.ReconciliationAdapter` per
# `review_kind` (12 total), plus `build_production_registry()` /
# `register_into()` - the REAL Layer B `MutationAdapterRegistry`
# `ui/reconciliation_operator.py`'s own `_default_registry_factory()`
# folds together with Layer A's `mutation_approval_adapters.
# build_production_registry()` into ONE merged registry (see that
# module's own updated header comment).
#
# IMPORT TOPOLOGY: this module (unlike `review_mutation_facade.py`) DOES
# import `ui.services.review_registry` directly - a safe, one-way edge,
# since `review_registry.py` never imports this module (only `review_
# mutation_facade.py`, which itself never imports `review_registry` -
# see that module's own header comment for the full rationale). This
# mirrors the reason `review_registry.REVIEW_KIND_REGISTRY`'s metadata
# (module object, `record_type`, canonical field names, `REVIEWER_REF`)
# is reused here rather than re-derived a second time.
#
# INDEPENDENT EVIDENCE, NEVER CIRCULAR, NEVER SHARED WITH THE FACADE:
# `gather_evidence()` below never trusts the journal row's own
# `expected_post_hash`/`pre_hash` as proof of anything (see
# `ui.services.mutation_registry.ReconciliationEvidence`'s own
# docstring). It independently re-reads the ACTUAL canonical file's
# OWN target-record state and the ACTUAL audit directory - the SAME
# artefacts a human reviewer would look at - and reports what it
# genuinely finds. The manifest-scan and audit-binding logic below is a
# SEPARATE, INDEPENDENTLY-WRITTEN implementation from `review_mutation_
# facade.py`'s own (this module deliberately does NOT import either
# `_scan_review_directory`/`_compute_snapshot`/`_verify_completed_
# replay_audit_binding` from that module) - a bug in one must never be
# masked by the other reusing it, exactly the same principle `mutation_
# approval_adapters.py`'s own header comment states for Layer A. The
# only things imported from `review_mutation_facade.py` are pure,
# deterministic NAMING helpers with zero decision logic
# (`action_family_for`) - matching that SAME Layer A precedent exactly
# (`mutation_approval_adapters.py` imports `ROW_KEY_TO_MODULE_NAME`/
# `action_family_for` from `mutation_approval_facade.py`, but never its
# verification functions).
#
# AUDIT CARDINALITY (RECONCILIATION PHASE) - see `review_mutation_
# facade.py`'s own header comment, "AUDIT CARDINALITY": the SAME
# phase-dependent rule applies here as for a live completed-replay
# verification (never the admission-phase rule, since reconciliation is
# never invoked before a journal row already exists):
#   corrupt_audit_count == 0 AND matching_clean_candidate_count == 1
# is required before `post_state_verified=True` can ever be reported;
#   corrupt_audit_count == 0 AND matching_clean_candidate_count == 0
# (PLUS the target record's own canonical state reading `needs_review`)
# is required before `pre_state_confirmed_unchanged=True` can ever be
# reported. Any OTHER combination - a duplicate match, a family-wide
# corrupt candidate, a mismatched binding, or a canonical state that is
# neither `needs_review` nor the journal's own `target_state` - is
# reported as `ReconciliationEvidence(False, False)`, which `mutation_
# registry._decide_outcome()` resolves to `reconciliation_required` (or,
# for a `prepared`-origin row, `PreparedJournalUnresolvedError` - the
# row is left completely untouched) - NEVER upgraded to either proof by
# guessing.
#
# BINDING 8 (normalized review-note hash) - RECONCILIATION-SPECIFIC
# NOTE: unlike a LIVE request (which has its own freshly-computed
# `secondary_input_hash` to compare against directly - see `review_
# mutation_facade.py`'s own binding 8), a RECONCILIATION run has no
# live request at all; `mutation.mutation_journal` never stores
# `secondary_input_hash` as its own column (only folded into the
# opaque `request_fingerprint` digest - see `src/mutation_guard.py`'s
# own Row 19C-2b addition). Binding 8 is therefore verified here
# TRANSITIVELY, entirely through binding 14 (the recomputed request-
# fingerprint check, which hashes the audit's own `review_note` in
# exactly the same way) - there is no separate, additional binding-8
# check in `_bindings_match()` below beyond what binding 14 already
# proves; this is a deliberate consequence of the journal's own closed,
# free-text-free column set, not an oversight.
# ============================================================

from __future__ import annotations

import fnmatch
import hashlib
import json
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mutation_guard import MutationIntent, compute_request_fingerprint  # noqa: E402
import path_containment as _path_containment  # noqa: E402

from . import mutation_registry as mr
from . import paths as _paths
from . import review_registry as _review_registry
from .common import sha256_file
from .review_mutation_facade import (
    action_family_for,
    # ROW 19C-3b SLICE 1: two more pure, deterministic NAMING constants -
    # same "only naming helpers, zero decision logic borrowed" discipline
    # this module's own header comment already documents for
    # `action_family_for` itself. `_CHANNEL_CLI` names the exact suffix
    # `action_family_for()` appends for the CLI channel;
    # `_REVIEWER_REF_WEB`/`_REVIEWER_REF_CLI` are that module's OWN
    # mirrored copies of `review_registry.REVIEWER_REF`/
    # `LOCAL_CLI_REVIEWER_REF` (never re-mirrored a THIRD time here).
    _CHANNEL_CLI,
    _REVIEWER_REF_WEB,
    _REVIEWER_REF_CLI,
)


# ============================================================
# ROW 19C-3a SLICE 2 - NESTED PATH-CONTAINMENT, independently
# implemented in THIS file - never imported from, and never imported
# by, `review_mutation_facade.py`'s own copy (same non-masking
# principle this module's own header comment already states for the
# audit-binding logic).
#
# UNLIKE THE FACADE: every containment failure here resolves to the
# EXISTING `mr.ReconciliationEvidence(post_state_verified=False,
# pre_state_confirmed_unchanged=False)` dual-false shape via
# `_NestedPathContainmentSignal` - genuinely inconclusive evidence,
# never propagated past this module's own boundary.
# ============================================================


class _NestedPathContainmentSignal(Exception):
    """Internal-only signal used solely to unwind into `gather_
    evidence()`'s own dual-false return - never raised past this
    module's own boundary."""


def _resolve_case_root_real(anchor_module, case_id: str) -> Path:
    cases_dir = anchor_module.CASES_DIR
    try:
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise _NestedPathContainmentSignal(str(error)) from error


def _verify_nested(anchor_module, case_root_real: Path, case_id: str, raw_path) -> Path:
    cases_dir = anchor_module.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise _NestedPathContainmentSignal(str(error)) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise _NestedPathContainmentSignal(str(error)) from error


class UnexpectedResourceKeyShapeError(Exception):
    """Raised if a journal entry routed to one of these adapters
    somehow does not carry a `case:<case_id>` resource_key -
    structurally unreachable today (every Layer B review family always
    locks `case:<case_id>` - see `review_mutation_facade.apply_review_
    mutation()`), kept as a fail-closed backstop in the same spirit as
    `ui.services.mutation_registry.ResourceKeyMismatchError`, never as
    an expected branch."""


def _nonblank(value) -> bool:
    """Deliberately this module's OWN copy of the same rule `review_
    mutation_facade._nonblank()` applies - see this module's own header
    comment on why the two verification paths stay independent rather
    than sharing an implementation."""
    return isinstance(value, str) and bool(value.strip())


def _find_record(module, record_type: str, analysis: dict, record_id: str):
    """This module's OWN copy of `review_mutation_facade._find_record()`
    - independently written, not imported (see this module's own header
    comment)."""
    find_record_fn = getattr(module, "find_record", None)
    if find_record_fn is not None:
        return find_record_fn(analysis, record_type, record_id)
    if record_type == "candidate" and hasattr(module, "find_candidate"):
        return module.find_candidate(analysis, record_id)
    if hasattr(module, "find_suggestion"):
        return module.find_suggestion(analysis, record_id)
    return None


def _classify_entry_kind(name: str) -> str:
    if name.endswith(".review_audit.json"):
        return "audit"
    if name.endswith(".bak"):
        return "backup"
    return "unexpected"


class _AuditDirectoryScan:
    __slots__ = ("audit_records", "corrupt_audit_count")

    def __init__(self, audit_records, corrupt_audit_count):
        self.audit_records = audit_records
        self.corrupt_audit_count = corrupt_audit_count


_EMPTY_AUDIT_SCAN = _AuditDirectoryScan(audit_records=(), corrupt_audit_count=0)


def _scan_audit_directory(audit_dir: Path) -> _AuditDirectoryScan:
    """This module's OWN, independently-written scan - reconciliation
    only ever needs the AUDIT side (never the backup manifest, which
    exists only for the LIVE composite pre-state race check - see
    `review_mutation_facade.py`'s own header comment, "the user's
    point-3 list contains no backup binding"). Fail-closed on the SAME
    conditions as the facade's own scan (containment escape, non-
    regular-file entry, duplicate name, unreadable/vanished entry,
    unexpected entry name) - a corrupt-JSON `*.review_audit.json` file
    is tracked (`corrupt_audit_count`), never a scan abort."""
    audit_dir = Path(audit_dir)

    if not audit_dir.is_dir():
        return _EMPTY_AUDIT_SCAN

    seen_names = set()
    audit_records = []
    corrupt_count = 0

    try:
        entries = sorted(audit_dir.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise ReviewReconciliationScanError(f"{audit_dir}: dizin listelenemedi.") from error

    for entry in entries:
        name = entry.name

        if name in seen_names:
            raise ReviewReconciliationScanError(f"{audit_dir}: yinelenen dizin girişi adı: {name!r}")
        seen_names.add(name)

        # ROW 19C-3a SLICE 2 BACKUP-KIND CONTAINMENT REMEDIATION: entry
        # kind is classified with pure, filesystem-free string operations
        # only. An "unexpected" name is rejected immediately - no
        # containment check is meaningful for a name this scanner does
        # not recognize at all. BOTH "audit" and "backup" kinds then go
        # through the IDENTICAL containment + exact-parent-membership
        # proof BEFORE any is_file()/stat()/open() touches the entry -
        # closing a second ordering bug an independent review found
        # AFTER the first (see the FINAL NARROW REMEDIATION note this
        # replaces): the "backup" branch used to call `entry.is_file()`
        # on the RAW, unverified entry BEFORE containment was ever
        # checked. On Windows a directory-junction escape happened to
        # still abort the scan (a junction always fails `is_file()`), but
        # a live escaping SYMLINK to an external FILE transparently
        # passes `is_file()` - such an entry was silently ignored
        # (`continue`) without the escape ever being detected at all, not
        # merely mis-diagnosed.
        kind = _classify_entry_kind(name)
        if kind == "unexpected":
            raise ReviewReconciliationScanError(f"{audit_dir}: beklenmeyen dizin girişi: {name!r}")

        try:
            verified_path = _paths.verify_real_path_contained(entry, root=audit_dir)
        except _paths.PathContainmentError as error:
            raise ReviewReconciliationScanError(
                f"{audit_dir}: girişin containment doğrulaması başarısız: {name!r}"
            ) from error

        # ROW 19C-3a SLICE 2: EXACT expected-parent membership - see
        # `review_mutation_facade._scan_review_directory()`'s own
        # identical addition and its docstring for the full rationale
        # (closes the in-tree-alias case: an entry that legitimately
        # resolves INSIDE `audit_dir`'s own real form via `relative_to()`
        # but whose own immediate parent is NOT `audit_dir` itself).
        # Meaningful only because `audit_dir` here is, since this Slice,
        # always the CALLER's own case-root-verified real form. Applies
        # to BOTH kinds - a backup entry aliasing into a nested
        # descendant is exactly as much an escape as an audit entry
        # doing the same.
        if verified_path.parent != Path(audit_dir):
            raise ReviewReconciliationScanError(
                f"{audit_dir}: giriş beklenen dizinin DIŞINA çözümleniyor (in-tree alias): {name!r}"
            )

        if kind == "backup":
            # Safe (contained, correctly-parented) - but a backup entry's
            # CONTENT is never relevant to reconciliation (see this
            # function's own docstring, "the user's point-3 list contains
            # no backup binding"). A safe, regular-file backup entry is
            # silently ignored, exactly as before; a safe entry that is
            # NOT a regular file (e.g. a contained subdirectory literally
            # named "*.bak") still aborts the whole scan, preserving the
            # ORIGINAL pre-remediation outcome for that case - only NOW
            # the type check runs on the VERIFIED path, never the raw,
            # unverified entry.
            if not verified_path.is_file():
                raise ReviewReconciliationScanError(
                    f"{audit_dir}: beklenmeyen (dosya olmayan) dizin girişi: {name!r}"
                )
            continue

        # kind == "audit" - the ONLY entries this scanner actually reads.
        # ONLY NOW, on the VERIFIED, fully-resolved Path, is a type
        # check performed - preserves the ORIGINAL pre-remediation
        # outcome (a non-regular-file audit-named entry aborts the whole
        # scan) rather than silently falling through to `open()`'s own
        # `IsADirectoryError`, which the broad `except Exception` below
        # would otherwise have mis-tracked as merely "corrupt".
        if not verified_path.is_file():
            raise ReviewReconciliationScanError(
                f"{audit_dir}: beklenmeyen (dosya olmayan) dizin girişi: {name!r}"
            )

        try:
            with open(verified_path, "r", encoding="utf-8") as file:
                record = json.load(file)
            if not isinstance(record, dict):
                raise ValueError("audit record is not a JSON object")
        except Exception:
            corrupt_count += 1
            audit_records.append((name, None))
        else:
            audit_records.append((name, record))

    return _AuditDirectoryScan(audit_records=tuple(audit_records), corrupt_audit_count=corrupt_count)


class ReviewReconciliationScanError(Exception):
    """Raised for the SAME filesystem-level anomalies `review_mutation_
    facade.ReviewDirectoryScanError` raises for the live path - a
    reconciliation run over a directory in this state cannot produce
    reliable evidence at all; propagated as a genuine adapter-internal
    failure (per `ReconciliationAdapter.gather_evidence()`'s own
    Protocol docstring: "raising is reserved for a genuine adapter-
    internal bug" - an unresolvable filesystem anomaly qualifies)."""


def _record_bound_clean_matches_with_names(scan: _AuditDirectoryScan, *, case_id, record_type, record_id):
    return [
        (name, record) for name, record in scan.audit_records
        if record is not None
        and record.get("case_id") == case_id
        and record.get("record_type") == record_type
        and record.get("record_id") == record_id
    ]


class _UnroutableActionFamilyForReviewKindError(Exception):
    """Internal, never-expected-to-fire signal: `entry.action_family`
    does not EXACTLY equal either of THIS adapter's own two registered
    keys for its OWN `review_kind`. Structurally unreachable in
    practice - `MutationAdapterRegistry.get(action_family)` already did
    an EXACT dict-key lookup to find this very adapter instance, so
    `entry.action_family` can only ever be one of the two keys this
    adapter itself was registered under - but `gather_evidence()` below
    still checks explicitly and treats this as inconclusive (dual-false)
    rather than ever guessing, matching every other genuinely-impossible
    branch in this file."""


def _expected_reviewer_ref_for_action_family(action_family: str, *, review_kind: str) -> str:
    """ROW 19C-3b SLICE 1 - the immutable journal-to-channel binding.
    `action_family` is read from the JOURNAL (`entry.action_family`,
    populated once at `prepared`-row insert time and never mutated
    afterward) - never from the on-disk, forgeable domain audit record.

    EXACT EQUALITY against THIS adapter's own two computed keys for its
    own `review_kind` - deliberately NOT a generic `.endswith(".cli")`/
    prefix/2-element-membership heuristic (a membership check against a
    fixed 2-element set is exactly what would let a forged on-disk
    `reviewer_ref` swap between the two valid values and still pass; see
    this module's own `_bindings_match()` docstring). Each row has
    exactly ONE valid expected value, determined solely by which of the
    TWO EXACT keys `action_family_for(review_kind)` /
    `action_family_for(review_kind, channel="cli")` produces for THIS
    specific review_kind actually matches `entry.action_family`."""
    expected_web_key = action_family_for(review_kind)
    expected_cli_key = action_family_for(review_kind, channel=_CHANNEL_CLI)
    if action_family == expected_cli_key:
        return _REVIEWER_REF_CLI
    if action_family == expected_web_key:
        return _REVIEWER_REF_WEB
    raise _UnroutableActionFamilyForReviewKindError(
        f"action_family={action_family!r} matches NEITHER expected exact key for "
        f"review_kind={review_kind!r} ({expected_web_key!r} / {expected_cli_key!r})"
    )


def _bindings_match(record: dict, entry: mr.JournalEntrySnapshot, *, current_canonical_sha256: str, reviewer_ref: str) -> bool:
    """THE EXACT BINDINGS (reconciliation phase) - see this module's own
    header comment for binding 8's own transitive-via-14 note. Returns
    True only when ALL applicable bindings hold exactly; any missing,
    blank or mismatched value returns False (inconclusive), never
    raises."""

    if not _nonblank(record.get("mutation_idempotency_key")) or record.get("mutation_idempotency_key") != entry.idempotency_key:
        return False
    if not _nonblank(record.get("mutation_resource_key")) or record.get("mutation_resource_key") != entry.resource_key:
        return False
    if not entry.resource_key.startswith("case:") or not entry.resource_key[len("case:"):]:
        return False
    if record.get("record_id") != entry.target_ref:
        return False
    if not _nonblank(record.get("mutation_actor_ref")) or record.get("mutation_actor_ref") != entry.actor_label:
        return False
    if record.get("reviewer_ref") != reviewer_ref:
        return False
    if record.get("new_state") != entry.target_state:
        return False
    raw_note = record.get("review_note")
    if not isinstance(raw_note, str):
        return False
    if not _nonblank(record.get("pre_sha256")) or record.get("pre_sha256") != entry.pre_revision:
        return False
    if not _nonblank(record.get("post_sha256")) or record.get("post_sha256") != current_canonical_sha256:
        return False

    note_hash = hashlib.sha256(raw_note.encode("utf-8")).hexdigest()
    reconstructed = MutationIntent(
        actor_type="iam_user", actor_ref=record.get("mutation_actor_ref"),
        resource_key=entry.resource_key, action_family=entry.action_family,
        target_ref=entry.target_ref, target_state=entry.target_state,
        pre_hash=entry.pre_hash, pre_revision=entry.pre_revision,
        secondary_input_hash=note_hash,
    )
    try:
        recomputed_fingerprint = compute_request_fingerprint(reconstructed)
    except Exception:
        return False
    return recomputed_fingerprint == entry.request_fingerprint


class ReviewMutationReconciliationAdapter:
    """One instance per `review_kind` - all identifying metadata
    (`module`, `record_type`, `state_field`, `get_audit_dir_fn`) is
    resolved ONCE at construction time from `ui.services.review_registry.
    REVIEW_KIND_REGISTRY`/`get_field_names()` - `entry.action_family` is
    used by `MutationAdapterRegistry.get()` to ROUTE to the correct
    already-constructed instance (this SAME instance is now registered
    under BOTH the review_kind's web and CLI action_family keys - see
    `register_into()` below), and is ALSO re-inspected inside
    `gather_evidence()` itself (ROW 19C-3b SLICE 1) to derive the ONE
    expected `reviewer_ref` value for THIS specific row - see
    `_expected_reviewer_ref_for_action_family()`'s own docstring for why
    this is exact-equality-per-row, never fixed instance state. Stateless
    and side-effect-free beyond the read-only filesystem access
    `gather_evidence()`'s own contract requires."""

    def __init__(self, review_kind: str):
        entry = _review_registry.REVIEW_KIND_REGISTRY[review_kind]
        module = _review_registry._import_module(entry["module"])
        _array_field, _id_field, state_field = _review_registry.get_field_names(review_kind)

        self._review_kind = review_kind
        self._module = module
        self._record_type = entry["record_type"] if entry["record_type"] is not None else "suggestion"
        self._state_field = state_field
        # `entry["audit_dir_getter"]` names THIS backend's own,
        # differently-named audit-directory getter function - reused
        # directly from `REVIEW_KIND_REGISTRY`'s own metadata (single
        # source of truth, shared with `review_registry.apply_
        # transition()`'s identical need), never a second,
        # independently-maintained copy of the same mapping.
        self._get_audit_dir_fn = getattr(module, entry["audit_dir_getter"])
        # ROW 19C-3b SLICE 1: `self._reviewer_ref` (a single, fixed,
        # construction-time value) is REMOVED - it cannot correctly
        # serve BOTH the web and CLI action_family keys this SAME
        # instance is now registered under (see `register_into()`). The
        # expected value is now derived PER ROW, inside
        # `gather_evidence()`, from that row's own `entry.action_family`.
        # ROW 19C-3a SLICE 2: resolved INDEPENDENTLY from the facade's
        # own identical resolution in `review_registry.apply_
        # transition()` - both read the SAME `REVIEW_KIND_REGISTRY`
        # entry's `cases_dir_module_name()`, but each does its own
        # `_import_module()` call rather than sharing a resolved value,
        # preserving the existing independence discipline.
        self._cases_dir_anchor_module = _review_registry._import_module(
            _review_registry.cases_dir_module_name(review_kind),
        )

    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if not entry.resource_key.startswith("case:"):
            raise UnexpectedResourceKeyShapeError(
                f"journal_id={entry.journal_id}: expected a 'case:<case_id>' resource_key for a "
                f"Layer B review family, got {entry.resource_key!r}"
            )
        case_id = entry.resource_key[len("case:"):]
        record_id = entry.target_ref

        # ROW 19C-3a SLICE 2: case root, canonical, and audit_dir chains
        # are ALL verified before any `.exists()`/hash/scan reasoning -
        # a containment failure at any point resolves to the SAME
        # dual-false shape a genuinely missing/unreadable canonical or
        # audit record already produced before this Slice (Layer B
        # never treated a missing canonical as an affirmative "pre-state
        # unchanged" proof to begin with, unlike Layer A - so this
        # Slice closes the analogous gap without needing a NEW branch).
        try:
            case_root_real = _resolve_case_root_real(self._cases_dir_anchor_module, case_id)
            canonical_verified = _verify_nested(
                self._cases_dir_anchor_module, case_root_real, case_id, self._module.get_canonical_path(case_id),
            )
        except _NestedPathContainmentSignal:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        if not canonical_verified.is_file():
            # Layer B's canonical is expected to ALWAYS exist by the
            # time a journal row could exist at all (Layer A already
            # promoted it - a Layer B admission attempt against a
            # missing canonical is refused at the precondition stage,
            # before any journal row is ever written). A missing
            # canonical here is therefore genuinely anomalous, never a
            # legitimate "unchanged pre-state" signal the way Layer A's
            # absent-canonical case is - inconclusive, never either
            # proof.
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        current_canonical_sha256 = sha256_file(canonical_verified)
        if current_canonical_sha256 is None:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        try:
            analysis = json.loads(canonical_verified.read_text(encoding="utf-8"))
        except Exception:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        record = _find_record(self._module, self._record_type, analysis, record_id)
        if record is None:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        canonical_record_state = record.get(self._state_field)

        try:
            audit_dir_verified = _verify_nested(
                self._cases_dir_anchor_module, case_root_real, case_id, self._get_audit_dir_fn(case_id),
            )
        except _NestedPathContainmentSignal:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        try:
            scan = _scan_audit_directory(audit_dir_verified)
        except ReviewReconciliationScanError:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        clean_matches = _record_bound_clean_matches_with_names(
            scan, case_id=case_id, record_type=self._record_type, record_id=record_id,
        )

        # PRE-STATE (see this module's own header comment, "AUDIT
        # CARDINALITY (RECONCILIATION PHASE)").
        if canonical_record_state == "needs_review" and scan.corrupt_audit_count == 0 and len(clean_matches) == 0:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)

        # POST-STATE.
        if (
            canonical_record_state == entry.target_state
            and scan.corrupt_audit_count == 0
            and len(clean_matches) == 1
        ):
            _name, matched_record = clean_matches[0]
            # ROW 19C-3b SLICE 1: the expected reviewer_ref is derived
            # PER ROW from the journal's own (immutable) action_family -
            # never a fixed per-instance value. If `entry.action_family`
            # somehow matches neither of THIS review_kind's two exact
            # registered keys (structurally unreachable via
            # `MutationAdapterRegistry.get()`'s own exact-key routing -
            # see `_UnroutableActionFamilyForReviewKindError`'s
            # docstring), this is treated as inconclusive, never a match.
            try:
                expected_reviewer_ref = _expected_reviewer_ref_for_action_family(
                    entry.action_family, review_kind=self._review_kind,
                )
            except _UnroutableActionFamilyForReviewKindError:
                return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)
            if _bindings_match(
                matched_record, entry,
                current_canonical_sha256=current_canonical_sha256, reviewer_ref=expected_reviewer_ref,
            ):
                return mr.ReconciliationEvidence(
                    post_state_verified=True, pre_state_confirmed_unchanged=False,
                    observed_post_hash=current_canonical_sha256,
                )

        # Genuinely inconclusive for THIS specific journal entry -
        # never upgraded to either proof.
        return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    """Adds all 12 Layer B REVIEW KINDS to an EXISTING registry
    (immutable builder - returns a NEW registry, never mutates
    `registry` itself) - this is what lets `ui/reconciliation_operator.py`'s
    own `_default_registry_factory()` merge Layer A's and Layer B's
    adapters into ONE registry a human operator can reconcile ANY
    journal row through, regardless of family, without
    `MutationAdapterRegistry` itself needing a dedicated merge method.

    ROW 19C-3b SLICE 1: each of the 12 review_kinds is registered under
    TWO exact `action_family` ROUTING KEYS (web: `action_family_for(review_kind)`,
    CLI: `action_family_for(review_kind, channel="cli")`) - 24 routing
    keys total, pointing at the SAME single adapter INSTANCE per
    review_kind (one instance genuinely serves both channels, since
    `gather_evidence()` derives the expected `reviewer_ref` per row from
    `entry.action_family` - see `_expected_reviewer_ref_for_action_family()`).
    This does NOT change the number of LOGICAL review kinds (still 12) -
    it only doubles the number of RECONCILIATION ROUTING KEYS a human
    operator's journal row can resolve through. `MutationAdapterRegistry.
    with_adapter()` has no restriction on registering the same adapter
    object under two different keys (confirmed by reading its own
    implementation - it only rejects a literal duplicate KEY)."""
    for review_kind in _review_registry.REVIEW_KIND_REGISTRY:
        adapter = ReviewMutationReconciliationAdapter(review_kind)
        registry = registry.with_adapter(action_family_for(review_kind), adapter)
        registry = registry.with_adapter(
            action_family_for(review_kind, channel=_CHANNEL_CLI), adapter,
        )
    return registry


def build_production_registry() -> mr.MutationAdapterRegistry:
    """A STANDALONE registry containing ONLY the 12 Layer B adapters -
    used by this module's own isolated tests. Production callers
    (`ui/reconciliation_operator.py`) use `register_into()` instead, to
    fold these onto Layer A's own registry rather than replacing it."""
    return register_into(mr.MutationAdapterRegistry())
