# ============================================================
# VERGİ AI - ROW 19C-2b: REVIEW MUTATION FACADE (Layer B).
#
# The Layer B analogue of `ui.services.mutation_approval_facade.
# approve_case_scoped_mutation()` - the bridge between
# `ui.services.review_registry.apply_transition()` (Layer B, the 12
# review_kind record-level review transitions) and
# `ui.services.mutation_coordinator.run_mutation()`, connecting the
# SECOND real production writer family to Row 19C-1's mutation-journal
# infrastructure (the first was Row 19C-2a's Layer A approval facade).
#
# IMPORT TOPOLOGY (deliberately closed, no cycle): `review_registry.py`
# imports THIS module (to delegate `apply_transition()`'s coordinated
# path to it) - so THIS module must NEVER import `review_registry`
# back. Every piece of review_kind-specific metadata this facade needs
# (the backend module object, its `record_type`, its call shape, its
# canonical `state_field` name, its own domain exception class, its
# audit-directory getter, and the fixed `REVIEWER_REF` provenance
# label) is therefore passed in as a single, already-resolved
# `ReviewFamilyBinding` bundle BY THE CALLER - this module never
# re-derives any of it from a bare `review_kind` string, and never
# looks at `ui.services.review_registry.REVIEW_KIND_REGISTRY` itself.
# `ui.services.review_mutation_adapters` (a SEPARATE file, this same
# turn) is free to import `review_registry` directly instead - nothing
# in `review_registry` imports adapters, so that edge is a safe,
# one-way DAG.
#
# DUAL AUTHORIZATION - identical shape and rationale to
# `mutation_approval_facade.approve_case_scoped_mutation()`'s own
# header comment: an OUTER check runs before any journal/lock
# connection is opened (fail-fast/leak-prevention, zero cost/zero
# information for an unauthorized caller), an INNER check re-runs
# under the case lock as the AUTHORITATIVE decision
# (`run_mutation()`'s own step 2). Existence-blindness is preserved by
# construction (both go through the same `authorize_case_access()`);
# every path downstream is built from the RESOLVED case_id, never the
# raw caller-supplied string.
#
# COMPOSITE PRE-STATE SNAPSHOT: CANONICAL + AUDIT MANIFEST + BACKUP
# MANIFEST (never canonical hash alone)
# -------------------------------------------------------------------
# The writer this facade wraps
# (`<family>_review.apply_review_transition()`) has THREE durable
# effects on disk, all confirmed by direct reading of all 5 backends'
# own `backup_canonical()`/`write_review_audit()` functions:
#   1. the canonical file is mutated in place;
#   2. a NEW `*.review_audit.json` file is created;
#   3. a NEW `*.before_review_*.bak` file is created.
# ALL THREE land in the EXACT SAME directory -
# `<family_dir>/reviews/<family>_reviews/` (confirmed by direct read of
# every one of `evidence_review.backup_canonical`/`argument_review.
# backup_canonical`/`risk_strategy_review.backup_canonical`/
# `drafting_review.backup_canonical`/`qa_review.backup_canonical`: each
# one's `backup_path = audit_dir / (...)"` writes the backup INTO the
# very same `audit_dir` `write_review_audit()` also writes into - this
# is NOT the shallower Layer A `reviews/` directory one level up,
# which Layer B never touches at all). A canonical-hash-only pre-state
# is insufficient: canonical's own `review_state`/`suggestion_review_
# state` field can be restored to an EARLIER, byte-identical value by
# an out-of-band actor (a `history`/`.bak` restore, T15/T9-class
# tampering already named in Row 19A's threat model) WITHOUT touching
# the audit trail that already recorded a genuine prior review of the
# SAME record - the domain guard below (`previous_state == "needs_
# review"`) reads exactly that single, potentially-tampered field, so
# it alone cannot detect this. The audit/backup MANIFEST is the
# independent witness: an unexplained new/pre-existing audit or backup
# entry is caught even when canonical's own bytes look pristine.
#
# `ReviewPreconditionSnapshot` therefore covers, from ONE single scan
# of `reviews/<family>_reviews/` (`_scan_review_directory()`):
#   - canonical presence + sha256;
#   - a deterministic, sorted `(relative_name, content_sha256)`
#     manifest of every `*.review_audit.json` entry (count + digest);
#   - the SAME shape for every `*.before_review_*.bak` entry.
# Computed pre-lock (recorded as this attempt's `pre_hash` - filesystem
# EVIDENCE, never identity, per `src/mutation_guard.py`'s own Row
# 19C-2a correction) and re-computed under the case lock. A composite
# mismatch raises `common.ReviewPreconditionRaceDetectedError` (a
# `ReviewStaleViewError` SUBCLASS - every existing `except
# ReviewStaleViewError` handler, e.g. `ui/main.py`'s `review_confirm`
# route, keeps working completely unchanged).
#
# `atomic_write_json`'s own `<canonical_name>.tmp` residue (a crashed
# canonical write) lands in canonical's OWN parent directory, never in
# `reviews/<family>_reviews/` - structurally outside this scan's own
# root, so it can never be misclassified here at all; it is inert with
# respect to this facade (nothing globs `*.tmp`, and `os.replace()`'s
# own atomicity means canonical itself is never left half-written).
#
# MANIFEST SCAN FAIL-CLOSED RULES (`_scan_review_directory()`) - every
# entry is realpath/containment-verified via `paths.
# verify_real_path_contained(entry, root=audit_dir)` - deliberately
# scoped to `audit_dir`'s OWN resolved form (never the broader
# `paths.CASES_DIR`), so the identical check is meaningful and
# enforceable in BOTH the real production tree AND an isolated test's
# own `audit_dir_override` tempdir, with zero awareness of which mode
# is active. A symlink/junction escape, a broken/looping link, a
# non-regular-file entry (a stray subdirectory, a device file), a
# duplicate directory-entry name, or a file that vanishes/becomes
# unreadable between listing and hashing ALL abort the ENTIRE scan
# (`ReviewDirectoryScanError`) - none are silently skipped. An entry
# whose name matches NEITHER `*.review_audit.json` NOR `*.bak` is
# likewise an immediate, whole-scan abort ("unexpected entry") - this
# deliberately includes a stray `.tmp` file that somehow lands in this
# directory (it never does under this project's own writers, since
# `atomic_write_json`'s temp file always targets canonical's own
# parent, never `audit_dir` - see above) and any other unrecognized
# artefact. Named, accepted operational consequence: a single such
# stray entry blocks EVERY record's review in that family until an
# operator removes it - the fail-closed cost the user's own contract
# explicitly mandates, not a limitation to silently work around.
#
# A `*.review_audit.json`-named entry that IS a contained, readable,
# regular file but whose CONTENT fails to parse as a JSON object is
# NOT a scan-level abort - it is TRACKED as one more corrupt candidate
# (`corrupt_audit_count`, family-wide, see "AUDIT CARDINALITY" below)
# so the admission/replay decision that consumes it can apply the
# correct fail-closed rule, rather than the scan itself pre-deciding an
# outcome.
#
# PRE-EXISTING RECORD AUDIT ADMISSION GATE (before ANY journal row)
# -------------------------------------------------------------------
# Composite-digest equality (pre-lock == under-lock) alone proves only
# "nothing changed while this request waited for the lock" - it does
# NOT prove "zero pre-existing audit exists for this exact record",
# because a stale audit could already be present, identically, in BOTH
# reads (the restore/re-review attack: canonical rolled back to an
# EARLIER, byte-identical `needs_review` state that hides a genuine
# prior review). `precondition_callback` therefore ALSO asserts, as its
# own independent, ABSOLUTE (never delta) condition, under the lock:
#   record_bound_clean_match_count == 0 AND family_corrupt_count == 0
# - built by content-matching EVERY `*.review_audit.json` entry in the
# family's audit directory against `(case_id, record_type, record_id)`
# (never filename-prefiltered - a wrongly-named-but-content-matching
# file must never be silently ignored) PLUS the family-wide corrupt
# count from the same scan. ANY non-zero value on EITHER side refuses
# the request, fail-closed, with ZERO journal rows written and the
# writer NEVER invoked - exactly like `ReviewRecordNotFoundError`'s own
# precondition-level treatment.
#
# AUDIT CARDINALITY - PHASE-DEPENDENT THRESHOLDS (the SAME identity-
# matching algorithm, DIFFERENT acceptance rule per phase)
# -------------------------------------------------------------------
#   ADMISSION (this facade, before `_insert_prepared`/the writer):
#       corrupt_audit_count == 0 AND matching_clean_candidate_count == 0
#       is the ONLY successful starting condition - a pre-existing
#       clean match OR ANY corrupt audit anywhere in the family
#       directory refuses the mutation before it begins.
#   POST-WRITE VERIFICATION / COMPLETED REPLAY (this facade) and
#   RECONCILIATION (`ui.services.review_mutation_adapters`, a SEPARATE,
#   independently-implemented check - never imported from here, same
#   non-masking principle `mutation_approval_adapters.py`'s own header
#   states for Layer A):
#       corrupt_audit_count == 0 AND matching_clean_candidate_count == 1
#       is required before ANY of the 14 semantic bindings below are
#       even consulted. 0 matches, 2+ matches, or any family-wide
#       corrupt candidate are ALL inconclusive/ambiguous, fail-closed,
#       never resolved by picking one.
#
# GUARD-HOISTING (Row 19C-2b USER DECISION, applied here) - the SAME
# real, PUBLIC, pure backend functions (`find_record`/`find_candidate`/
# `find_suggestion`, `check_parent_dependency`, `check_stale_sources`)
# are called DIRECTLY, under the case lock, inside `precondition_
# callback` - never reimplemented/copied. This is what lets a common,
# benign domain rejection (record already reviewed by someone else a
# moment ago; a counterargument submitted before its claim resolved)
# stay a PRECONDITION-level failure (zero journal rows) instead of
# being swept into `mutation_coordinator.py`'s own unconditional "any
# writer exception -> reconciliation_required" rule, which would
# otherwise misclassify an everyday rejection as an admin-facing
# incident. The backend's OWN internal re-check of these SAME guards
# (unchanged, inside `apply_review_transition()` itself) remains
# reachable only via an out-of-band tamper DURING the held lock -
# genuinely rare, and correctly escalated to `reconciliation_required`
# in that case.
#
# REPLAY-SAFETY AUDIT-BINDING CHECK - 14 EXACT BINDINGS
# -------------------------------------------------------------------
# On a SAFE REPLAY (`MutationOutcome.replayed=True`), this module does
# not trust the journal's own stored `observed_post_hash` at face
# value. After locating the SINGLE clean, record-bound audit record
# (per the cardinality rule above), it independently verifies ALL of
# the following, exactly (a MISSING, BLANK, MALFORMED or MISMATCHED
# value on ANY of them is NEVER treated as automatic success):
#   1.  journal.idempotency_key      == audit.mutation_idempotency_key
#   2.  journal.resource_key         == audit.mutation_resource_key
#                                        == "case:<case_id>" (shape + eq)
#   3.  audit.case_id                == case_id
#   4.  audit.record_type            == binding.record_type
#   5.  journal.target_ref           == audit.record_id
#   6.  journal.actor_label          == audit.mutation_actor_ref
#       (`audit.reviewer_ref` is ALSO checked, SEPARATELY, against the
#       FIXED "local_lawyer_ui" sentinel - see review_registry.py's own
#       locked decision that `reviewer_ref` is provenance, never a
#       verified actor identity; it can never serve binding 6 itself)
#   7.  journal.target_state         == audit.new_state
#   8.  sha256(audit.review_note.encode("utf-8")).hexdigest()
#                                     == this call's own secondary_input_hash
#   9.  audit.pre_sha256             == journal.pre_revision
#   10. audit.post_sha256            == current canonical sha256
#   11. journal.observed_post_hash   == current canonical sha256
#       (completed-replay only - `observed_post_hash` is NULL by
#       construction for any row this check would otherwise reach)
#   12. the TARGET RECORD's own state field, read fresh from the
#       CURRENT canonical JSON (never inferred from the whole-file hash
#       alone) == journal.target_state
#   13. (implied by 3-9, still checked directly - never trusted only
#       transitively) - folded into the explicit checks above
#   14. mutation_guard.compute_request_fingerprint(reconstructed_intent)
#                                     == journal.request_fingerprint,
#       where `reconstructed_intent` is built PURELY from this audit
#       record's own content (case_id -> resource_key, record_id ->
#       target_ref, new_state -> target_state, pre_sha256 ->
#       pre_revision, mutation_actor_ref -> actor_ref, review_note ->
#       secondary_input_hash) PLUS `journal.pre_hash` (required so the
#       reconstructed `MutationIntent` is even STRUCTURALLY valid per
#       `src/mutation_guard.py`'s own both-or-neither pre_hash/
#       pre_revision rule - `pre_hash`'s VALUE never enters either
#       digest, it is supplied only to satisfy that structural
#       invariant).
# ============================================================

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mutation_guard import MutationIntent, compute_idempotency_key, compute_request_fingerprint  # noqa: E402
import path_containment as _path_containment  # noqa: E402

from . import authz as _authz
from . import mutation_coordinator as _mutation_coordinator
from . import mutation_lock as _mutation_lock
from . import paths as _paths
from .common import (
    ReviewPreconditionRaceDetectedError,
    ReviewRecordNotFoundError,
    ReviewStaleViewError,
    ReviewUiError,
    sha256_file,
)
# Reused by name, NEVER redefined - the SAME closed HTTP-409 contract
# label `ui.services.mutation_approval_facade.AuditBindingVerification
# FailedError`'s own docstring already commits to; `ui/main.py`'s
# `review_confirm` route maps this constant to the identical, existing
# `_ERROR_MESSAGES[mutfacade.MUTATION_REQUIRES_REVIEW]` text - no new
# user-facing string is ever introduced by Layer B.
from .mutation_approval_facade import MUTATION_REQUIRES_REVIEW  # noqa: F401

_logger = logging.getLogger("vergi_ai.review_mutation_facade")


def _log_critical_safely(message: str) -> None:
    """Identical in purpose to `mutation_approval_facade._log_critical_
    safely` - kept as this module's own copy so its cleanup logging has
    no dependency on that module for this purpose."""
    try:
        _logger.critical(message)
    except Exception:
        pass


_ACTION_FAMILY_PREFIX = "review."


def action_family_for(review_kind: str) -> str:
    """The ONE place this project's Layer B `action_family` string is
    derived from a `review_kind` - both this module's own
    `MutationIntent` construction AND
    `ui.services.review_mutation_adapters.build_production_registry()`
    call this, so the two can never drift apart. Deliberately
    NAMESPACED under `"review."`, distinct from Layer A's `"approval."`
    prefix (`mutation_approval_facade.action_family_for()`) - the two
    families can never collide in `mutation.mutation_journal`."""
    return f"{_ACTION_FAMILY_PREFIX}{review_kind}"


class ReviewDirectoryScanError(ReviewUiError):
    """Raised by `_scan_review_directory()` for any filesystem-level
    anomaly in `reviews/<family>_reviews/` that this module refuses to
    silently work around: a symlink/junction escape or broken link
    (`ui.services.paths.PathContainmentError`), a non-regular-file
    entry, a duplicate directory-entry name, an entry that vanishes or
    becomes unreadable between listing and hashing, or an entry whose
    name matches neither `*.review_audit.json` nor `*.bak`. NEVER
    raised for a `*.review_audit.json`-shaped file whose CONTENT merely
    fails to parse - that is tracked as a corrupt candidate instead
    (see this module's own header comment, "AUDIT CARDINALITY")."""


class ReviewAuditBindingVerificationFailedError(ReviewUiError):
    """The Layer B analogue of `mutation_approval_facade.
    AuditBindingVerificationFailedError` - see this module's own header
    comment ("REPLAY-SAFETY AUDIT-BINDING CHECK") for the full
    rationale. Raised on a safe replay whose independent audit-record
    corroboration failed - never on a fresh execution, whose own
    successful writer return is itself sufficient completion proof.
    Mapped by `ui/main.py` to the SAME closed `MUTATION_REQUIRES_
    REVIEW` (HTTP 409) contract Layer A's identically-named class
    already uses - this project's ONE shared, closed mutation-
    uncertainty contract, never a second, Layer-B-specific string."""

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


# ============================================================
# ROW 19C-3a SLICE 2 - NESTED PATH-CONTAINMENT (case root ->
# canonical/audit_dir chain), independently implemented in THIS file -
# never imported by, and never importing from, `mutation_approval_
# facade.py`/`mutation_approval_adapters.py`/`review_mutation_
# adapters.py`, each of which carries its OWN copy of the same shape.
#
# WHY: `_scan_review_directory()`'s existing per-entry check
# (`verify_real_path_contained(entry, root=audit_dir)`) is meaningful
# ONLY once `audit_dir` itself is proven to be genuinely, safely
# contained within the case directory - before this Slice, `audit_dir`
# reached that check completely unverified (only `audit_dir.is_dir()`
# gated it, which follows symlinks/junctions and cannot distinguish a
# genuine absence from a broken/looping escape). `_resolve_case_root_
# real()`/`_verify_nested()` below close that gap; `_scan_review_
# directory()` gains the SECOND, independent "exact expected-parent
# membership" check the case report's own advisory settled on (closes
# the in-tree-alias case: an entry that legitimately resolves INSIDE
# the case root, but under a DIFFERENT logical directory, several
# levels deep or otherwise).
#
# ANCHOR: `binding.cases_dir_anchor_module.CASES_DIR` - the module
# whose OWN `CASES_DIR` the review backend's own `get_canonical_path`/
# `get_*_review_audit_dir` getters are actually built from (11 of 12
# review_kinds: `binding.module` itself; `qa.suggestion`: `qa_approval`
# - see `review_registry.cases_dir_module_name()`'s own docstring).
# ============================================================


def _resolve_case_root_real(anchor_module, case_id: str) -> Path:
    cases_dir = anchor_module.CASES_DIR
    try:
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise ReviewDirectoryScanError(
            f"Case kök dizini containment doğrulamasından geçemedi: {case_id!r}"
        ) from error


def _verify_nested(anchor_module, case_root_real: Path, case_id: str, raw_path) -> Path:
    cases_dir = anchor_module.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise ReviewDirectoryScanError(
            f"{raw_path}: beklenen case dizini kapsamı ({case_root_raw}) dışında bir yol."
        ) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise ReviewDirectoryScanError(
            f"{raw_path}: path containment doğrulaması başarısız (case kökü dışına çözümleniyor, "
            "kırık/döngüsel bir symlink/junction içeriyor, veya mevcut bir dosyanın altına path "
            "üretilmeye çalışılıyor)."
        ) from error


class ReviewResolvedCaseIdMismatchError(ReviewUiError):
    """Fail-closed backstop: the INNER (under-lock) `authorize_case_
    access()` call returned a DIFFERENT resolved case_id than the OUTER
    (pre-lock) one did. Structurally unreachable (`paths.resolve_case_
    id()` is deterministic for a given tree, and both calls pass the
    same raw `case_id`), but never assumed from outside this module's
    own scope - mirrors `mutation_approval_facade.
    ResolvedCaseIdMismatchError` exactly, kept as an independent copy
    rather than an import (this module never imports that one - see
    this module's own import-topology comment)."""


# ============================================================
# ONE resolved bundle of everything this facade needs about ONE
# review_kind's backend shape - constructed ONCE by
# `ui.services.review_registry.apply_transition()` (which already owns
# `REVIEW_KIND_REGISTRY`) and passed in whole. This module NEVER
# imports `review_registry` and NEVER re-derives any of this from a
# bare `review_kind` string (see this module's own header comment).
# ============================================================


@dataclass(frozen=True)
class ReviewFamilyBinding:
    review_kind: str
    module: object
    record_type: str
    call_shape: str  # "with_record_type" | "qa_special"
    state_field: str
    domain_error_class: type
    get_audit_dir_fn: object  # callable(case_id) -> Path
    reviewer_ref: str
    # ROW 19C-3a SLICE 2: the ALREADY-IMPORTED module object whose OWN
    # `CASES_DIR` attribute anchors this review_kind's path-containment
    # verification - for 11 of 12 review_kinds this IS `module` itself;
    # `qa.suggestion` is the one exception (`qa_review.py` has no
    # `CASES_DIR` of its own - see `review_registry.cases_dir_module_
    # name()`'s own docstring). Resolved ONCE by `review_registry.
    # apply_transition()`, passed in whole - this module never re-
    # derives it from a bare `review_kind` string (same discipline every
    # other field on this dataclass already follows).
    cases_dir_anchor_module: object


# ============================================================
# MANIFEST SCAN - see this module's own header comment ("MANIFEST SCAN
# FAIL-CLOSED RULES", "AUDIT CARDINALITY").
# ============================================================


def _classify_entry_kind(name: str) -> str:
    if name.endswith(".review_audit.json"):
        return "audit"
    if name.endswith(".bak"):
        return "backup"
    return "unexpected"


@dataclass(frozen=True)
class _DirectoryScan:
    audit_manifest: tuple      # sorted tuple of (relative_name, content_sha256)
    backup_manifest: tuple     # sorted tuple of (relative_name, content_sha256)
    audit_records: tuple       # tuple of (relative_name, parsed_dict_or_None)
    corrupt_audit_count: int


_EMPTY_SCAN = _DirectoryScan(audit_manifest=(), backup_manifest=(), audit_records=(), corrupt_audit_count=0)


def _scan_review_directory(audit_dir: Path) -> _DirectoryScan:
    audit_dir = Path(audit_dir)

    if not audit_dir.is_dir():
        return _EMPTY_SCAN

    seen_names = set()
    audit_manifest = []
    backup_manifest = []
    audit_records = []
    corrupt_count = 0

    try:
        entries = sorted(audit_dir.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise ReviewDirectoryScanError(f"{audit_dir}: dizin listelenemedi.") from error

    for entry in entries:
        name = entry.name

        if name in seen_names:
            raise ReviewDirectoryScanError(f"{audit_dir}: yinelenen dizin girişi adı: {name!r}")
        seen_names.add(name)

        # ROW 19C-3a SLICE 2 FINAL NARROW REMEDIATION: only a pure,
        # filesystem-free NAME classification is allowed to run before
        # containment is proven. A nonmatching name is rejected right
        # here (cheap, safe - its content/type was never going to be
        # read either way). A MATCHING name (`.review_audit.json`/
        # `.bak`) does NOT yet get any `is_file()`/`stat()`/`open()`
        # touch - see below, AFTER containment - closing an ordering
        # bug an independent review found: `entry.is_file()` used to run
        # on the RAW, unverified entry before containment was checked at
        # all. On Windows this was doubly silent for a junction-based
        # escape specifically, since a directory-only NTFS junction
        # always fails `is_file()` - the OLD code's "not a file" branch
        # fired first and the containment check below was never even
        # reached for that entry, even though the FINAL exception class
        # happened to be the same either way.
        kind = _classify_entry_kind(name)
        if kind == "unexpected":
            raise ReviewDirectoryScanError(f"{audit_dir}: beklenmeyen dizin girişi: {name!r}")

        # Containment/symlink-junction check, scoped to `audit_dir`'s
        # OWN resolved form (see this module's own header comment on
        # why - meaningful and enforceable identically in production
        # and in an isolated test's own tempdir override). Runs on the
        # RAW `entry` (this is `verify_real_path_contained()`'s own
        # sanctioned resolution step, not a separate metadata touch),
        # strictly BEFORE any `is_file()`/`stat()`/`open()` elsewhere in
        # this loop.
        try:
            verified_path = _paths.verify_real_path_contained(entry, root=audit_dir)
        except _paths.PathContainmentError as error:
            raise ReviewDirectoryScanError(
                f"{audit_dir}: girişin containment doğrulaması başarısız: {name!r}"
            ) from error

        # ROW 19C-3a SLICE 2: EXACT expected-parent membership, a
        # SECOND, independent check beyond plain containment - closes
        # the in-tree-alias case (an entry that legitimately resolves
        # INSIDE `audit_dir`'s own real form via `relative_to()`, e.g. a
        # multi-level descendant through a subdirectory that should
        # never exist here, but whose own immediate parent is NOT
        # `audit_dir` itself). This check is meaningful only because
        # `audit_dir` here is, since this Slice, always the CALLER's
        # own case-root-verified real form (see `apply_review_
        # mutation()`'s own path derivation) - never a raw, unverified
        # join.
        if verified_path.parent != Path(audit_dir):
            raise ReviewDirectoryScanError(
                f"{audit_dir}: giriş beklenen dizinin DIŞINA çözümleniyor (in-tree alias): {name!r}"
            )

        # ONLY NOW, on the VERIFIED, fully-resolved Path, is a type
        # check performed - never on the raw, unverified `entry`.
        if not verified_path.is_file():
            raise ReviewDirectoryScanError(
                f"{audit_dir}: beklenmeyen (dosya olmayan) dizin girişi: {name!r}"
            )

        content_hash = sha256_file(verified_path)
        if content_hash is None:
            raise ReviewDirectoryScanError(
                f"{audit_dir}: giriş tarama sırasında kayboldu/okunamadı: {name!r}"
            )

        if kind == "backup":
            backup_manifest.append((name, content_hash))
            continue

        audit_manifest.append((name, content_hash))

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

    return _DirectoryScan(
        audit_manifest=tuple(sorted(audit_manifest)),
        backup_manifest=tuple(sorted(backup_manifest)),
        audit_records=tuple(audit_records),
        corrupt_audit_count=corrupt_count,
    )


def _record_bound_clean_matches(scan: _DirectoryScan, *, case_id: str, record_type: str, record_id: str) -> list:
    """Identity-ONLY candidate matching (never filename-prefiltered,
    never narrowed by actor/reviewer/target_state/note/idempotency/
    resource/hash) - see this module's own header comment, "PRE-
    EXISTING RECORD AUDIT ADMISSION GATE"."""
    return [
        record for _name, record in scan.audit_records
        if record is not None
        and record.get("case_id") == case_id
        and record.get("record_type") == record_type
        and record.get("record_id") == record_id
    ]


def _record_bound_match_with_name(scan: _DirectoryScan, *, case_id: str, record_type: str, record_id: str):
    """Same as `_record_bound_clean_matches()` but also returns the
    matching entry's own relative filename - used only for reporting
    `audit_path` back to the caller once cardinality has already been
    verified elsewhere."""
    return [
        (name, record) for name, record in scan.audit_records
        if record is not None
        and record.get("case_id") == case_id
        and record.get("record_type") == record_type
        and record.get("record_id") == record_id
    ]


# ============================================================
# COMPOSITE PRE-STATE SNAPSHOT
# ============================================================

SNAPSHOT_ABSENT = "__absent__"
SNAPSHOT_PRESENT = "__present__"
_SNAPSHOT_VERSION = "row19c2b.v1"


@dataclass(frozen=True)
class ReviewPreconditionSnapshot:
    canonical_presence: str
    canonical_sha256: str
    audit_manifest_count: int
    audit_manifest_digest: str
    backup_manifest_count: int
    backup_manifest_digest: str
    composite_digest: str


def _canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _compute_snapshot(canonical_path: Path, audit_dir: Path):
    """Returns `(ReviewPreconditionSnapshot, _DirectoryScan)` - the
    scan is returned alongside the snapshot so callers that already
    need to inspect its contents (the admission gate, replay
    verification) never re-scan the directory a second time for the
    exact same read."""
    canonical_path = Path(canonical_path)

    canonical_sha256 = sha256_file(canonical_path) or SNAPSHOT_ABSENT
    canonical_presence = SNAPSHOT_PRESENT if canonical_path.exists() else SNAPSHOT_ABSENT

    scan = _scan_review_directory(audit_dir)

    audit_manifest_digest = hashlib.sha256(_canonical_json(list(scan.audit_manifest))).hexdigest()
    backup_manifest_digest = hashlib.sha256(_canonical_json(list(scan.backup_manifest))).hexdigest()

    payload = _canonical_json({
        "snapshot_version": _SNAPSHOT_VERSION,
        "canonical_presence": canonical_presence,
        "canonical_sha256": canonical_sha256,
        "audit_manifest_count": len(scan.audit_manifest),
        "audit_manifest_digest": audit_manifest_digest,
        "backup_manifest_count": len(scan.backup_manifest),
        "backup_manifest_digest": backup_manifest_digest,
    })

    snapshot = ReviewPreconditionSnapshot(
        canonical_presence=canonical_presence,
        canonical_sha256=canonical_sha256,
        audit_manifest_count=len(scan.audit_manifest),
        audit_manifest_digest=audit_manifest_digest,
        backup_manifest_count=len(scan.backup_manifest),
        backup_manifest_digest=backup_manifest_digest,
        composite_digest=hashlib.sha256(payload).hexdigest(),
    )
    return snapshot, scan


# ============================================================
# GUARD-HOISTING - calls the SAME real, public backend functions
# directly (never reimplemented/copied). See this module's own header
# comment, "GUARD-HOISTING".
# ============================================================


def _find_record(module, record_type: str, analysis: dict, record_id: str):
    find_record_fn = getattr(module, "find_record", None)
    if find_record_fn is not None:
        return find_record_fn(analysis, record_type, record_id)
    if record_type == "candidate" and hasattr(module, "find_candidate"):
        return module.find_candidate(analysis, record_id)
    if hasattr(module, "find_suggestion"):
        return module.find_suggestion(analysis, record_id)
    raise ReviewDirectoryScanError(
        f"{module.__name__}: record_type={record_type!r} için bilinen bir find_* fonksiyonu yok."
    )


# ============================================================
# NORMALIZED NOTE HASH - the CALLER (review_registry.apply_transition())
# normalizes `review_note` EXACTLY ONCE (via its own `normalize_review_
# note()`) and passes the SAME normalized text both to this facade
# (for hashing) and, unchanged, all the way through to the writer -
# this function never re-normalizes anything, it only hashes what it
# is given.
# ============================================================


def note_hash_for(normalized_review_note: str) -> str:
    return hashlib.sha256(normalized_review_note.encode("utf-8")).hexdigest()


COMPLETED_JOURNAL_STATE = "completed"


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _verify_completed_replay_audit_binding(
    record: dict,
    *,
    journal_id: int,
    idempotency_key: str,
    resource_key: str,
    case_id: str,
    binding: ReviewFamilyBinding,
    record_id: str,
    actor_ref: str,
    target_state: str,
    note_hash: str,
    pre_revision: str,
    journal_pre_hash: str | None,
    request_fingerprint: str,
    observed_post_hash: str | None,
    current_canonical_sha256: str,
    canonical_record_state,
) -> None:
    """THE 14 EXACT BINDINGS - see this module's own header comment for
    the full rationale of each. `record` MUST already be the SINGLE
    clean, record-bound audit record the cardinality gate selected -
    this function performs NO candidate-set narrowing of its own."""

    def require(field_name, expected, description):
        recorded = record.get(field_name)
        if not _nonblank(recorded):
            raise ReviewAuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    f"audit record carries a missing/blank {field_name} ({recorded!r}) - an "
                    "unbound audit record is never accepted as corroboration"
                ),
            )
        if recorded != expected:
            raise ReviewAuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    f"audit record carries {field_name}={recorded!r}, which does NOT match "
                    f"this call's own {description} ({expected!r})"
                ),
            )

    # 1. idempotency key
    require("mutation_idempotency_key", idempotency_key, "journal idempotency_key")
    # 2. resource key (shape + equality)
    if not resource_key.startswith("case:") or not resource_key[len("case:"):]:
        raise ReviewAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=f"resource_key={resource_key!r} is not a well-formed case:<case_id> key",
        )
    require("mutation_resource_key", resource_key, "journal resource_key")
    # 3. case_id
    require("case_id", case_id, "case_id")
    # 4. record_type / review_kind
    require("record_type", binding.record_type, "expected record_type")
    # 5. record id
    require("record_id", record_id, "journal target_ref")
    # 6a. actor (real identity)
    require("mutation_actor_ref", actor_ref, "journal actor_label")
    # 6b. reviewer sentinel - fixed provenance label, NOT an identity binding
    require("reviewer_ref", binding.reviewer_ref, "the fixed Lawyer UI reviewer_ref sentinel")
    # 7. target state
    require("new_state", target_state, "journal target_state")
    # 8. normalized review note hash
    raw_note = record.get("review_note")
    if not isinstance(raw_note, str):
        raise ReviewAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason="audit record carries a missing/non-string review_note",
        )
    if hashlib.sha256(raw_note.encode("utf-8")).hexdigest() != note_hash:
        raise ReviewAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason="audit record's own review_note does not hash to this call's own secondary_input_hash",
        )
    # 9. pre SHA
    require("pre_sha256", pre_revision, "journal pre_revision")
    # 10. post SHA vs current canonical
    require("post_sha256", current_canonical_sha256, "CURRENT canonical artefact hash")
    # 11. completed-replay observed-post hash
    if not _nonblank(observed_post_hash):
        raise ReviewAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=f"journal row records a missing/blank observed_post_hash ({observed_post_hash!r})",
        )
    if observed_post_hash != current_canonical_sha256:
        raise ReviewAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                f"journal observed_post_hash={observed_post_hash!r} does not match the CURRENT "
                f"canonical artefact hash {current_canonical_sha256!r}"
            ),
        )
    # 12. canonical's OWN target-record state, read fresh - never
    # inferred from the whole-file hash alone.
    if canonical_record_state != target_state:
        raise ReviewAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                f"the target record's CURRENT canonical state ({canonical_record_state!r}) does "
                f"not match this journal row's own target_state ({target_state!r}) - the audit "
                "record's claim cannot be corroborated against canonical's own record"
            ),
        )
    # 14. recomputed request fingerprint (13 folded into the direct
    # checks above - never trusted only transitively). `pre_hash` is
    # the JOURNAL's own recorded value (`journal_pre_hash`) - required
    # only so `MutationIntent` is a STRUCTURALLY valid value object per
    # `src/mutation_guard.py`'s own both-or-neither pre_hash/pre_
    # revision rule (see `validate_intent()`); its VALUE never enters
    # either digest (`compute_idempotency_key`/`compute_request_
    # fingerprint` both exclude it via `_identity_fields()`), so using
    # the journal's own value here (rather than any other placeholder)
    # is correct AND harmless to the digest either way.
    reconstructed = MutationIntent(
        actor_type="iam_user", actor_ref=actor_ref,
        resource_key=resource_key, action_family=action_family_for(binding.review_kind),
        target_ref=record_id, target_state=target_state,
        pre_hash=journal_pre_hash, pre_revision=pre_revision,
        secondary_input_hash=note_hash,
    )
    recomputed_fingerprint = compute_request_fingerprint(reconstructed)
    if recomputed_fingerprint != request_fingerprint:
        raise ReviewAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                "the request_fingerprint recomputed purely from this audit record's own content "
                f"({recomputed_fingerprint!r}) does not match the journal row's own stored "
                f"request_fingerprint ({request_fingerprint!r})"
            ),
        )


# ============================================================
# DEPENDENCY INJECTION - mirrors `mutation_approval_facade.py`'s own
# `_default_authz_repository`/`_resolve_authz_repository`/`_default_
# conn_factory` shape exactly.
# ============================================================


def _default_authz_repository():
    from . import db as _db  # lazy import (psycopg)
    conn = _db.get_connection()
    return _authz.PostgresAuthzRepository(conn), conn.close


def _resolve_authz_repository(authz_repository):
    if authz_repository is not None:
        return authz_repository, lambda: None
    return _default_authz_repository()


def _default_conn_factory():
    from . import db as _db  # lazy import
    return _db.get_session_lock_connection()


@dataclass(frozen=True)
class ReviewMutationResult:
    """Deliberately narrower than `review_registry.apply_transition()`'s
    own pre-Row-19C-2b return dict - `ui.services.review_registry.
    apply_transition()` combines this with its own already-resolved
    `entry`/`REVIEWER_REF` metadata to reconstruct the EXACT SAME
    response shape callers already receive today (`canonical_path`,
    `audit_path`, `post_sha256`, `previous_state`, `new_state`) - see
    that function's own docstring."""

    review_kind: str
    canonical_path: Path
    canonical_hash: str | None
    audit_path: Path | None
    previous_state: str | None
    new_state: str
    journal_id: int
    replayed: bool


def apply_review_mutation(
    review_kind: str,
    case_id: str,
    record_id: str,
    target_state: str,
    normalized_review_note: str,
    expected_hash: str,
    binding: ReviewFamilyBinding,
    *,
    principal,
    authz_repository=None,
    conn_factory=None,
    canonical_path_override=None,
    audit_dir_override=None,
) -> ReviewMutationResult:
    """The Row 19C-2b coordinated, journaled, idempotent entry point for
    ONE Layer B record-level review transition, under the SAME
    session-level `case:<case_id>` lock every other file-write mutation
    on this case uses (Row 19A design decision - one lock per case, not
    one per family/record).

    `normalized_review_note` MUST already be the output of `review_
    registry.normalize_review_note()` - normalized EXACTLY ONCE by the
    caller and passed through, unchanged, both here (for hashing) and,
    separately, all the way to the writer - this function never
    re-normalizes it.

    `canonical_path_override`/`audit_dir_override` are TEST-ONLY
    dependency injection, threaded straight through to the writer and
    used, in place of `binding.module.get_canonical_path(case_id)`/
    `binding.get_audit_dir_fn(case_id)`, for every path this function
    itself touches too (the composite snapshot, the admission gate, the
    replay-verification scan) - production callers (`review_registry.
    apply_transition()`, called from `ui/main.py`) NEVER pass either;
    the production-default path always derives both from the RESOLVED,
    already-authorized `case_id`.

    ORDER (mirrors `mutation_approval_facade.approve_case_scoped_
    mutation()`'s own docstring exactly):
      1. OUTER `authorize_case_access()` - before any journal/lock
         connection, before the lock is requested, before any artefact
         hash is read, before any journal SQL.
      2. Derive `resource_key`/canonical/audit paths from the RESOLVED
         case_id, then compute the PRE-LOCK composite snapshot
         (recorded as `pre_hash`).
      3. Open the journal connection, acquire the session-level lock.
      4. `run_mutation()` - INNER (authoritative) authz, journal gate,
         idempotency lookup, under-lock precondition re-verification
         (domain guards, composite-race check, plain stale-hash check,
         admission gate), then (only for a genuinely new mutation)
         `prepared` -> `executing` -> writer -> `completed`.
      5. On a safe REPLAY only: the 14 exact audit bindings.
      6. Release the lock, close the journal connection, close the IAM
         authz connection if this module opened it.

    Raises: `ReviewRecordNotFoundError`, `ReviewStaleViewError`,
    `ReviewPreconditionRaceDetectedError` (a `ReviewStaleViewError`
    subclass), `binding.domain_error_class` (a real, hoisted domain
    rejection), `authz.CaseAccessDeniedError`; ADDITIONALLY whatever
    `ui.services.mutation_coordinator.run_mutation()` itself raises
    (`ResourceGatedError`, `IdempotencyConflictError`,
    `PriorAttemptFailedError`, `JournalExecutingTransitionFailedError`,
    `JournalCompletionUncertainError`); and this module's own
    `ReviewAuditBindingVerificationFailedError`/`ReviewResolvedCaseId
    MismatchError`. NONE of these are caught or reclassified here - the
    caller (`ui/main.py`) decides the HTTP mapping."""

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        # ============================================================
        # OUTER AUTHORIZATION - see this module's own header comment.
        # ============================================================
        outer_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )

        resource_key = _mutation_lock.case_resource_key(outer_resolved_case_id)

        # ROW 19C-3a SLICE 2 - PRE-LOCK NESTED PATH-CONTAINMENT
        # VERIFICATION, non-override branch ONLY: `canonical_path_
        # override`/`audit_dir_override` are TEST-ONLY (see this
        # function's own docstring - production, via `review_registry.
        # apply_transition()`, NEVER passes either) and bypass
        # verification entirely, exactly as before this Slice. The
        # non-override derivation now re-derives each RAW path through
        # the shared `path_containment` primitive, anchored to `binding.
        # cases_dir_anchor_module.CASES_DIR`, rather than trusting the
        # raw `/`-joined path the backend's own getter returned. Runs
        # AFTER outer authz, still entirely before any journal/lock
        # connection is opened.
        pre_lock_case_root_real = None

        def _lazy_pre_lock_case_root_real():
            nonlocal pre_lock_case_root_real
            if pre_lock_case_root_real is None:
                pre_lock_case_root_real = _resolve_case_root_real(
                    binding.cases_dir_anchor_module, outer_resolved_case_id,
                )
            return pre_lock_case_root_real

        if canonical_path_override is not None:
            canonical_path = Path(canonical_path_override)
        else:
            canonical_path = _verify_nested(
                binding.cases_dir_anchor_module, _lazy_pre_lock_case_root_real(), outer_resolved_case_id,
                binding.module.get_canonical_path(outer_resolved_case_id),
            )

        if audit_dir_override is not None:
            audit_dir = Path(audit_dir_override)
        else:
            audit_dir = _verify_nested(
                binding.cases_dir_anchor_module, _lazy_pre_lock_case_root_real(), outer_resolved_case_id,
                binding.get_audit_dir_fn(outer_resolved_case_id),
            )

        # PRE-LOCK composite snapshot - recorded as this attempt's
        # `pre_hash`, re-verified under the lock. Read AFTER the outer
        # authz has already succeeded, never before it.
        pre_lock_snapshot, _pre_lock_scan = _compute_snapshot(canonical_path, audit_dir)

        note_hash = note_hash_for(normalized_review_note)

        intent = MutationIntent(
            actor_type="iam_user",
            actor_ref=str(principal.user_id),
            resource_key=resource_key,
            action_family=action_family_for(review_kind),
            target_ref=record_id,
            target_state=target_state,
            # FILESYSTEM EVIDENCE (composite) - recorded and
            # re-verified, deliberately NOT part of mutation identity.
            pre_hash=pre_lock_snapshot.composite_digest,
            # The REQUEST's own claim - part of mutation identity.
            pre_revision=expected_hash,
            # Part of the request's own OUTCOME identity (fingerprint
            # only, never idempotency) - see src/mutation_guard.py's
            # own Row 19C-2b addition.
            secondary_input_hash=note_hash,
        )
        idempotency_key_for_audit = compute_idempotency_key(intent)
        request_fingerprint_for_audit = compute_request_fingerprint(intent)

        def authz_callback() -> None:
            # INNER (AUTHORITATIVE) AUTHORIZATION - see this module's
            # own header comment.
            inner_resolved_case_id = _authz.authorize_case_access(
                principal, case_id, "mutate", repository=repository,
            )
            if inner_resolved_case_id != outer_resolved_case_id:
                raise ReviewResolvedCaseIdMismatchError(
                    f"outer (pre-lock) authorization resolved case_id={outer_resolved_case_id!r} "
                    f"but the inner (under-lock) authorization resolved {inner_resolved_case_id!r} - "
                    "refusing to proceed"
                )

        def precondition_callback() -> None:
            nonlocal canonical_path, audit_dir

            # ROW 19C-3a SLICE 2 - FRESH, INDEPENDENT under-lock nested
            # path-containment re-verification (non-override branch
            # only) - re-derived from scratch, never reusing the
            # pre-lock verified Path objects, so a symlink/junction
            # swapped WHILE this request waited for the case lock is
            # caught here (an outright escape raises directly from
            # `_verify_nested()`; a resolved location that CHANGED but
            # remains safely contained raises the identity-mismatch
            # `ReviewPreconditionRaceDetectedError` below - both leave
            # zero journal rows). From this point on, `canonical_path`/
            # `audit_dir` are the FRESHEST verified values -
            # `writer_callback` (below) reads these SAME closure
            # variables when it builds `writer_kwargs`, so the writer
            # receives the freshest verified Paths with zero additional
            # plumbing (unlike Layer A, `apply_review_transition()`
            # ALREADY accepts and uses whatever `canonical_path=`/
            # `audit_dir=` it is handed - confirmed by direct reading).
            if canonical_path_override is None or audit_dir_override is None:
                under_lock_case_root_real = _resolve_case_root_real(
                    binding.cases_dir_anchor_module, outer_resolved_case_id,
                )
                if canonical_path_override is None:
                    fresh_canonical_path = _verify_nested(
                        binding.cases_dir_anchor_module, under_lock_case_root_real, outer_resolved_case_id,
                        binding.module.get_canonical_path(outer_resolved_case_id),
                    )
                    if str(fresh_canonical_path) != str(canonical_path):
                        raise ReviewPreconditionRaceDetectedError(
                            "Bu inceleme isteği case kilidini beklerken canonical dosyanın "
                            "çözümlenmiş (gerçek) konumu DEĞİŞTİ (symlink/junction swap veya "
                            "benzeri bir durum). İşlem iptal edildi, HİÇBİR değişiklik yapılmadı - "
                            "lütfen sayfayı yenileyip tekrar deneyin."
                        )
                    canonical_path = fresh_canonical_path
                if audit_dir_override is None:
                    fresh_audit_dir = _verify_nested(
                        binding.cases_dir_anchor_module, under_lock_case_root_real, outer_resolved_case_id,
                        binding.get_audit_dir_fn(outer_resolved_case_id),
                    )
                    if str(fresh_audit_dir) != str(audit_dir):
                        raise ReviewPreconditionRaceDetectedError(
                            "Bu inceleme isteği case kilidini beklerken audit dizininin "
                            "çözümlenmiş (gerçek) konumu DEĞİŞTİ (symlink/junction swap veya "
                            "benzeri bir durum). İşlem iptal edildi, HİÇBİR değişiklik yapılmadı - "
                            "lütfen sayfayı yenileyip tekrar deneyin."
                        )
                    audit_dir = fresh_audit_dir

            # Reached ONLY when a genuinely NEW mutation is needed (see
            # `run_mutation()`'s own AUTHORITATIVE ORDER) - so every
            # raise below leaves ZERO journal rows and never invokes
            # the writer.
            if not canonical_path.exists():
                raise ReviewRecordNotFoundError(f"Canonical dosya bulunamadı: {canonical_path}")

            try:
                with open(canonical_path, "r", encoding="utf-8") as file:
                    analysis = json.load(file)
            except Exception as error:
                raise ReviewRecordNotFoundError(
                    f"Canonical dosya okunamadı/ayrıştırılamadı: {canonical_path}"
                ) from error

            # GUARD-HOISTING - the SAME real, public backend functions,
            # called directly (never reimplemented) - see this module's
            # own header comment.
            record = _find_record(binding.module, binding.record_type, analysis, record_id)
            if record is None or record.get(binding.state_field) != "needs_review":
                raise ReviewRecordNotFoundError(
                    f"{review_kind}/{record_id}: needs_review durumunda bulunamadı."
                )

            check_parent_dependency_fn = getattr(binding.module, "check_parent_dependency", None)
            if check_parent_dependency_fn is not None:
                parent_error = check_parent_dependency_fn(analysis, binding.record_type, record, target_state)
                if parent_error:
                    raise binding.domain_error_class(parent_error)

            if binding.record_type == "section" and target_state == "confirmed":
                check_stale_sources_fn = getattr(binding.module, "check_stale_sources", None)
                if check_stale_sources_fn is not None:
                    stale = check_stale_sources_fn(outer_resolved_case_id, analysis, record)
                    if stale:
                        raise binding.domain_error_class(
                            f"Section '{record_id}' CONFIRM edilemedi: aşağıdaki kaynak(lar) "
                            f"artık hard-deny/kullanılamaz durumda (stale_source_now_denied): {stale}"
                        )

            # COMPOSITE RACE CHECK - see this module's own header
            # comment.
            under_lock_snapshot, under_lock_scan = _compute_snapshot(canonical_path, audit_dir)

            if under_lock_snapshot.composite_digest != pre_lock_snapshot.composite_digest:
                raise ReviewPreconditionRaceDetectedError(
                    "Bu inceleme isteği case kilidini beklerken ilgili dosyalar DEĞİŞTİ "
                    "(canonical veya audit/backup dizini artık aynı değil). Onay iptal edildi, "
                    "HİÇBİR değişiklik yapılmadı - lütfen sayfayı yenileyip tekrar deneyin."
                )

            if under_lock_snapshot.canonical_sha256 != expected_hash:
                raise ReviewStaleViewError(
                    "Bu inceleme ekranı açıldıktan sonra canonical dosya değişti "
                    f"(o zamanki hash: {expected_hash}, şimdiki: {under_lock_snapshot.canonical_sha256}). "
                    "İşlem iptal edildi - lütfen sayfayı yenileyip tekrar deneyin."
                )

            # PRE-EXISTING RECORD AUDIT ADMISSION GATE - see this
            # module's own header comment.
            clean_matches = _record_bound_clean_matches(
                under_lock_scan, case_id=outer_resolved_case_id,
                record_type=binding.record_type, record_id=record_id,
            )
            if under_lock_scan.corrupt_audit_count != 0 or len(clean_matches) != 0:
                raise ReviewPreconditionRaceDetectedError(
                    "Bu kayıt için beklenmedik (önceden mevcut veya bozuk) bir audit kaydı "
                    "bulundu - onay iptal edildi, hiçbir değişiklik yapılmadı. Lütfen sayfayı "
                    "yenileyip tekrar deneyin; sorun devam ederse sistem yöneticisiyle iletişime "
                    "geçin."
                )

        def writer_callback() -> _mutation_coordinator.WriterResult:
            actor_ref = str(principal.user_id)
            writer_kwargs = dict(
                canonical_path=canonical_path, audit_dir=audit_dir,
                mutation_idempotency_key=idempotency_key_for_audit,
                mutation_resource_key=resource_key,
                mutation_actor_ref=actor_ref,
            )
            if binding.call_shape == "qa_special":
                writer_result = binding.module.apply_review_transition(
                    outer_resolved_case_id, record_id, target_state,
                    binding.reviewer_ref, normalized_review_note,
                    **writer_kwargs,
                )
            else:
                writer_result = binding.module.apply_review_transition(
                    outer_resolved_case_id, binding.record_type, record_id, target_state,
                    binding.reviewer_ref, normalized_review_note,
                    **writer_kwargs,
                )
            # The writer's own return dict already carries
            # `post_sha256` - computed by the writer itself, moments
            # earlier, from the artefact it had just finished writing.
            observed_post_hash = writer_result.get("post_sha256") or sha256_file(canonical_path)
            return _mutation_coordinator.WriterResult(
                observed_post_hash=observed_post_hash, result=writer_result,
            )

        resolved_conn_factory = conn_factory or _default_conn_factory
        conn = resolved_conn_factory()
        advisory_lock_id = _mutation_lock.acquire_case_lock_session(conn, outer_resolved_case_id)
        try:
            outcome = _mutation_coordinator.run_mutation(
                conn, intent,
                actor_user_id=principal.user_id,
                authz_callback=authz_callback,
                precondition_callback=precondition_callback,
                writer_callback=writer_callback,
            )

            if outcome.replayed:
                # ROW 19C-3a SLICE 2 - FRESH replay-time nested path-
                # containment re-verification (non-override branch
                # only). `precondition_callback` is NEVER invoked for a
                # replayed outcome (`run_mutation()`'s own idempotency
                # lookup short-circuits before reaching it) - so
                # `canonical_path`/`audit_dir` here are STILL the
                # ORIGINAL pre-lock-verified values, never re-verified
                # since. Any containment failure from here on (chain- OR
                # entry-level, via `_compute_snapshot()`'s own `_scan_
                # review_directory()` call) is folded into the SAME
                # closed `ReviewAuditBindingVerificationFailedError`/
                # `MUTATION_REQUIRES_REVIEW` contract every other
                # "succeeded but could not be independently
                # corroborated" outcome already uses - never a plain,
                # misleading failure for an already-`completed` mutation.
                try:
                    if canonical_path_override is None or audit_dir_override is None:
                        replay_case_root_real = _resolve_case_root_real(
                            binding.cases_dir_anchor_module, outer_resolved_case_id,
                        )
                        if canonical_path_override is None:
                            canonical_path = _verify_nested(
                                binding.cases_dir_anchor_module, replay_case_root_real, outer_resolved_case_id,
                                binding.module.get_canonical_path(outer_resolved_case_id),
                            )
                        if audit_dir_override is None:
                            audit_dir = _verify_nested(
                                binding.cases_dir_anchor_module, replay_case_root_real, outer_resolved_case_id,
                                binding.get_audit_dir_fn(outer_resolved_case_id),
                            )

                    # See this module's own header comment ("REPLAY-
                    # SAFETY AUDIT-BINDING CHECK") - independent
                    # corroboration is required ONLY on a replay (the
                    # writer was NOT re-invoked).
                    _post_snapshot, post_scan = _compute_snapshot(canonical_path, audit_dir)
                except ReviewDirectoryScanError as error:
                    raise ReviewAuditBindingVerificationFailedError(
                        journal_id=outcome.journal_id, idempotency_key=idempotency_key_for_audit,
                        reason=(
                            "a nested path-containment failure (chain- or entry-level) occurred "
                            f"during replay corroboration: {error}"
                        ),
                    ) from error
                matches = _record_bound_match_with_name(
                    post_scan, case_id=outer_resolved_case_id,
                    record_type=binding.record_type, record_id=record_id,
                )
                if post_scan.corrupt_audit_count != 0 or len(matches) != 1:
                    raise ReviewAuditBindingVerificationFailedError(
                        journal_id=outcome.journal_id, idempotency_key=idempotency_key_for_audit,
                        reason=(
                            "expected exactly one clean, record-bound audit record for replay "
                            f"verification; found {len(matches)} clean match(es) and "
                            f"{post_scan.corrupt_audit_count} corrupt candidate(s)"
                        ),
                    )
                audit_name, audit_record = matches[0]

                current_canonical_sha256 = sha256_file(canonical_path)
                if current_canonical_sha256 is None:
                    raise ReviewAuditBindingVerificationFailedError(
                        journal_id=outcome.journal_id, idempotency_key=idempotency_key_for_audit,
                        reason=f"canonical artefact at {canonical_path} does not exist right now",
                    )

                analysis_now = json.loads(canonical_path.read_text(encoding="utf-8"))
                record_now = _find_record(binding.module, binding.record_type, analysis_now, record_id)
                canonical_record_state = record_now.get(binding.state_field) if record_now is not None else None

                _verify_completed_replay_audit_binding(
                    audit_record,
                    journal_id=outcome.journal_id,
                    idempotency_key=idempotency_key_for_audit,
                    resource_key=resource_key,
                    case_id=outer_resolved_case_id,
                    binding=binding,
                    record_id=record_id,
                    actor_ref=str(principal.user_id),
                    target_state=target_state,
                    note_hash=note_hash,
                    pre_revision=expected_hash,
                    journal_pre_hash=intent.pre_hash,
                    request_fingerprint=request_fingerprint_for_audit,
                    observed_post_hash=outcome.observed_post_hash,
                    current_canonical_sha256=current_canonical_sha256,
                    canonical_record_state=canonical_record_state,
                )

                verified_canonical_hash = current_canonical_sha256
                previous_state = audit_record.get("previous_state")
                new_state = audit_record.get("new_state", target_state)
                audit_path = audit_dir / audit_name
            else:
                # A FRESH execution's own successful writer return is
                # itself sufficient completion proof - see
                # `mutation_coordinator.WriterResult`'s own docstring.
                writer_result = outcome.result
                verified_canonical_hash = outcome.observed_post_hash
                previous_state = writer_result.get("previous_state")
                new_state = writer_result.get("new_state", target_state)
                audit_path = writer_result.get("audit_path")

            return ReviewMutationResult(
                review_kind=review_kind,
                canonical_path=canonical_path,
                canonical_hash=verified_canonical_hash,
                audit_path=audit_path,
                previous_state=previous_state,
                new_state=new_state,
                journal_id=outcome.journal_id,
                replayed=outcome.replayed,
            )
        finally:
            # CLEANUP THAT CAN NEVER MASK THE OUTCOME - mirrors
            # `mutation_approval_facade.approve_case_scoped_mutation()`'s
            # own final cleanup discipline exactly.
            try:
                try:
                    released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
                except Exception as release_error:
                    _log_critical_safely(
                        f"CRITICAL: apply_review_mutation() RAISED while releasing the session "
                        f"lock for resource_key={resource_key!r} (advisory_lock_id="
                        f"{advisory_lock_id!r}): {release_error!r} - this process may still hold "
                        "the resource's advisory lock; investigate out of band"
                    )
                else:
                    if not released:
                        _log_critical_safely(
                            f"CRITICAL: apply_review_mutation() failed to release the session lock "
                            f"for resource_key={resource_key!r} (advisory_lock_id={advisory_lock_id!r}) "
                            "- this process may still hold the resource's advisory lock; investigate "
                            "out of band"
                        )
            finally:
                try:
                    conn.close()
                except Exception as close_error:
                    _log_critical_safely(
                        f"CRITICAL: apply_review_mutation() failed to close its journal/lock "
                        f"connection for resource_key={resource_key!r}: {close_error!r} - the "
                        "mutation outcome itself is unaffected and is being reported unchanged; "
                        "investigate this out of band"
                    )
    finally:
        try:
            close_repository()
        except Exception as error:
            _log_critical_safely(
                f"CRITICAL: apply_review_mutation() failed to close its own IAM authz connection "
                f"({error!r}) - investigate out of band; the mutation outcome itself is unaffected "
                "and is being reported unchanged"
            )