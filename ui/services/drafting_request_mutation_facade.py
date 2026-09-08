# ============================================================
# VERGİ AI - ROW 19C-2c: DRAFTING-REQUEST MUTATION FACADE.
#
# The Row 18C analogue of `ui.services.mutation_approval_facade.
# approve_case_scoped_mutation()` / `ui.services.review_mutation_facade.
# apply_review_mutation()` - the bridge between `ui.services.
# drafting_request.save_lawyer_input_from_form()` (the Row 18C
# structured-lawyer-input web writer) and `ui.services.
# mutation_coordinator.run_mutation()`, connecting the THIRD real
# production writer family to Row 19C-1's mutation-journal
# infrastructure (the first was Row 19C-2a's Layer A approval facade,
# the second Row 19C-2b's Layer B review facade).
#
# IMPORT TOPOLOGY: `ui.services.drafting_request` imports THIS module
# (to delegate its own coordinated-mutation call to it) - this module
# NEVER imports `drafting_request` back, mirroring `review_mutation_
# facade.py` never importing `review_registry`. `ui.services.
# drafting_request_mutation_adapters` (a SEPARATE file, this same turn)
# is free to import whatever it independently needs; nothing in this
# module imports it either.
#
# WHY THE OUTER AUTHORIZATION STEP LIVES OUTSIDE `apply_drafting_
# request_mutation()` ITSELF - A DELIBERATE, REASONED DEVIATION FROM
# THE LAYER A/B SHAPE
# -------------------------------------------------------------------
# Layer A's and Layer B's facades each own BOTH the outer (pre-lock)
# and inner (under-lock) authorization check internally, in ONE public
# function, because neither family has any case-specific filesystem
# read of its own between "authorize" and "lock" - everything after
# authorization is either fixed (module imports) or already inside the
# locked/precondition path. Row 18C's caller does NOT have that luxury:
# `save_lawyer_input_from_form()` must read the case's OWN
# `issues.json` (via `validate_and_sort_selected_issue_ids()`) to
# validate `selected_issue_ids` membership, and it must do so on the
# ALREADY-AUTHORIZED case_id (an unauthorized caller must never trigger
# even a read of case-specific data) - but strictly BEFORE this
# module's own lock/precondition/write logic even begins (the Row
# 19C-2c approved contract: "Outer authz herhangi bir connection,
# path/hash okuması, lock veya journal SQL'inden önce çalışmalı").
#
# The ONLY way to satisfy BOTH "authorize before any case-specific
# read" AND "the caller needs to do a case-specific read before this
# module's own work begins" is to split what Layer A/B fold into one
# call: this module exposes `resolve_repository()` + `authorize_outer()`
# as their own small, explicit, separately-callable steps. `ui.
# services.drafting_request.save_lawyer_input_from_form()` calls both,
# FIRST, before touching `issues.json` or building the wrapper; it then
# passes the ALREADY-RESOLVED case_id and the ALREADY-OPEN repository
# into `apply_drafting_request_mutation()`, which performs its own
# INNER (under-lock, authoritative) re-check using that SAME
# repository - never opening a second IAM connection for it, exactly
# like Layer A/B's own single-repository-reuse discipline.
# `apply_drafting_request_mutation()` therefore NEVER opens or closes
# the IAM authz repository itself (unlike Layer A/B's own facades) -
# that lifetime belongs entirely to the caller of `authorize_outer()`,
# which must close it in its own `finally`.
#
# COMPOSITE PRE-STATE SNAPSHOT: CURRENT INPUT + AUDIT MANIFEST + HISTORY
# MANIFEST (never the current-file hash alone)
# -------------------------------------------------------------------
# The writer this facade wraps (`drafting_request.save_lawyer_input()`)
# has up to THREE durable effects on disk, confirmed by direct reading
# of that function: (1) `data/cases/<case_id>/drafting/inputs/
# lawyer_input.json` is mutated in place; (2) a NEW `lawyer_input_
# save_<ts>.audit.json` is created under `.../inputs/audit/`; (3) on an
# OVERWRITE only (never a first save), a NEW `lawyer_input_before_
# save_<ts>.json` history backup is created under `.../inputs/
# history/`. A current-file-hash-only pre-state is insufficient for the
# SAME reason Layer A's own composite snapshot exists: an out-of-band
# actor could restore the current file to an earlier, byte-identical
# state while leaving a stale/orphaned audit record behind that a naive
# check would never see.
#
# UNLIKE LAYER B, THIS FACADE DOES NOT COPY THE "ZERO PRE-EXISTING
# RECORD-BOUND AUDIT" ADMISSION RULE (Row 19C-2c approved contract,
# binding decision 2026-09-08) - historical audit/backup entries in
# this writer's `audit/`/`history/` directories are NORMAL and EXPECTED
# (every legitimate save produces one), unlike Layer B's per-record
# review trail, where a pre-existing audit for the SAME record signals
# a restore/re-review attack. The admission rule here is instead:
# historical entries are allowed, but a fail-closed, pre-journal-row
# check rejects the attempt if the audit directory contains ANY
# candidate (clean or corrupt) whose OWN `mutation_idempotency_key`
# field equals the PROPOSED mutation's idempotency key (see
# `_admission_check()`) - a defense-in-depth cross-check against a
# filesystem/journal inconsistency the journal's own uniqueness
# constraint cannot itself catch (it never saw that write).
#
# `ReviewPreconditionSnapshot`'s Layer B analogue here,
# `DraftingRequestPreconditionSnapshot`, is computed from THREE
# strictly READ-ONLY filesystem reads (`_scan_audit_directory()` +
# `_scan_history_directory()` + `drafting_request.compute_current_
# freshness_token()`) - NEITHER scan function ever calls `.mkdir()` or
# reserves/creates anything (Row 19C-2c approved contract, binding
# decision 3): if `audit/`/`history/` do not exist yet (a case with no
# prior save at all), each is represented as an EMPTY manifest, never
# an error. Directory creation stays exactly where it already lives -
# inside `drafting_request.save_lawyer_input()`'s own writer logic,
# reached only under the lock, only after the precondition has already
# passed.
#
# MANIFEST SCAN FAIL-CLOSED RULES - mirrors `review_mutation_facade.
# _scan_review_directory()`'s own discipline: every entry is realpath/
# containment-verified via `paths.verify_real_path_contained(entry,
# root=<the specific scanned dir>)`. ROW 19C-2c PATH CONTAINMENT
# REMEDIATION: this per-entry check is meaningful ONLY because the
# scanned directory ITSELF is, by this point, already a value produced
# by `_verify_nested_case_path()` (see that function's own header
# comment, further down this file) - `_scan_directory()` performs NO
# case-root verification of its own and must NEVER be called with a
# raw, unverified directory. A symlink/junction escape, a
# broken/looping link, a non-regular-file entry, a duplicate
# directory-entry name, or an entry that vanishes/becomes unreadable
# between listing and hashing ALL abort the ENTIRE scan
# (`DraftingRequestDirectoryScanError`). An entry whose name does not
# match the EXACT naming convention the one writer that populates that
# directory actually uses (confirmed by direct source read of
# `drafting_request._reserve_collision_safe_path()`'s own two call
# sites: `lawyer_input_save_<ts>.audit.json` for the audit directory,
# `lawyer_input_before_save_<ts>.json` for the history directory) is
# likewise an immediate, whole-scan abort ("unexpected entry") - never
# silently skipped.
#
# A `*.audit.json`-shaped entry that IS contained/readable/regular but
# whose CONTENT fails to parse as a JSON object is NOT a scan-level
# abort - it is tracked as a corrupt candidate (`corrupt_audit_count`),
# exactly like Layer B's own audit scan, so the admission/replay
# decision that consumes it can apply the correct fail-closed rule
# rather than the scan itself pre-deciding an outcome. History/backup
# entries carry no "corrupt" concept of their own (a backup file's role
# is a byte-for-byte historical copy, not an identity-bearing record) -
# only containment/naming/hashing apply to them.
#
# 12 EXACT SEMANTIC BINDINGS (safe-replay verification) - see this
# module's own `_verify_completed_replay_audit_binding()` for the full
# enumeration; independently re-implemented (never imported) by `ui.
# services.drafting_request_mutation_adapters` for reconciliation, per
# the SAME non-masking principle every prior layer's adapters module
# states for itself.
# ============================================================

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mutation_guard import MutationIntent, compute_idempotency_key, compute_request_fingerprint  # noqa: E402

from . import authz as _authz
from . import mutation_coordinator as _mutation_coordinator
from . import mutation_lock as _mutation_lock
from . import paths as _paths
from .common import (
    DraftingRequestPreconditionRaceDetectedError,
    DraftingRequestStaleInputError,
    DraftingRequestUiError,
    sha256_file,
)
# Reused by name, NEVER redefined - the SAME closed HTTP-409 contract
# label `mutation_approval_facade.MUTATION_REQUIRES_REVIEW` already
# owns; `ui/main.py` maps this constant to the identical, existing
# `_ERROR_MESSAGES[mutfacade.MUTATION_REQUIRES_REVIEW]` text - no new
# user-facing string is ever introduced by Row 18C's own integration.
from .mutation_approval_facade import MUTATION_REQUIRES_REVIEW  # noqa: F401

_logger = logging.getLogger("vergi_ai.drafting_request_mutation_facade")


def _log_critical_safely(message: str) -> None:
    """Identical in purpose to every other facade's own copy of this
    helper - kept as this module's own copy so its cleanup logging has
    no dependency on any other facade module for this purpose."""
    try:
        _logger.critical(message)
    except Exception:
        pass


ACTION_FAMILY = "drafting_request.save"
TARGET_REF = "drafting_request.lawyer_input"
TARGET_STATE = "saved"

_CASE_RESOURCE_KEY_PREFIX = "case:"


class DraftingRequestDirectoryScanError(DraftingRequestUiError):
    """Raised by `_scan_audit_directory()`/`_scan_history_directory()`
    for any filesystem-level anomaly this module refuses to silently
    work around: a symlink/junction escape or broken link
    (`ui.services.paths.PathContainmentError`), a non-regular-file
    entry, a duplicate directory-entry name, an entry that vanishes or
    becomes unreadable between listing and hashing, or an entry whose
    name does not match the exact naming convention the one writer that
    populates that directory actually uses. NEVER raised for an
    `*.audit.json`-shaped file whose CONTENT merely fails to parse -
    that is tracked as a corrupt candidate instead (see this module's
    own header comment)."""


class DraftingRequestAuditBindingVerificationFailedError(DraftingRequestUiError):
    """The Row 18C analogue of `mutation_approval_facade.
    AuditBindingVerificationFailedError` / `review_mutation_facade.
    ReviewAuditBindingVerificationFailedError` - see this module's own
    header comment for the full rationale. Raised on a safe replay
    whose independent audit-record corroboration failed - never on a
    fresh execution, whose own successful writer return is itself
    sufficient completion proof. Mapped by `ui/main.py` to the SAME
    closed `MUTATION_REQUIRES_REVIEW` (HTTP 409) contract Layer A/B's
    identically-named classes already use - this project's ONE shared,
    closed mutation-uncertainty contract, never a third, Row-18C-
    specific string."""

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


class DraftingRequestResolvedCaseIdMismatchError(DraftingRequestUiError):
    """Fail-closed backstop: the INNER (under-lock) `authorize_case_
    access()` call returned a DIFFERENT resolved case_id than the OUTER
    (pre-lock) `authorize_outer()` call did. Structurally unreachable
    (`ui.services.paths.resolve_case_id()` is deterministic for a given
    tree, and both calls pass the same raw `case_id`), but never
    assumed from outside this module's own scope - mirrors `mutation_
    approval_facade.ResolvedCaseIdMismatchError` / `review_mutation_
    facade.ReviewResolvedCaseIdMismatchError` exactly, kept as an
    independent copy rather than an import."""


# ============================================================
# ROW 19C-2c PATH CONTAINMENT REMEDIATION (targeted re-review finding,
# Medium contract violation) - NESTED symlink/junction escape.
# -------------------------------------------------------------------
# `paths.verify_real_path_contained(entry, root=audit_dir)` alone is
# NOT sufficient: if `audit_dir` (or `history_dir`, or the parent chain
# of `lawyer_input.json`) is ITSELF a symlink/NTFS junction escaping
# `CASES_DIR`, every entry under it resolves "contained" relative to
# that wrong, already-escaped root - the per-entry check in `_scan_
# directory()` below was never wrong on its own, but every ORIGINAL
# call site handed it an UNVERIFIED `directory`. The fix is to verify
# the DIRECTORY ITSELF - and every intermediate segment leading to it -
# against the CASE ROOT, before it is ever listed/opened, never relying
# on a path being safe merely because it is its own `root=`.
#
# `_resolve_verified_case_dir()` anchors the check to `drafting_
# request.CASES_DIR`, read DYNAMICALLY at call time - deliberately NOT
# `ui.services.paths.CASES_DIR` directly (this module never imports
# `paths.CASES_DIR` as a bound name and never will). In production the
# two are the identical object (`drafting_request.py` imports `CASES_
# DIR` BY VALUE from `ui.services.paths` at its own top level), but a
# test that redirects `drafting_request.CASES_DIR` (as `ui/tests/test_
# drafting_request_service_isolated.py` already does, a file this
# remediation does not touch) must see this facade's own containment
# checks agree with what `drafting_request.get_inputs_dir()`/`save_
# lawyer_input()` themselves actually touch, never diverge from it -
# `ui.services.paths.verify_real_path_contained()` itself is reused
# AS-IS either way (never reimplemented), only the `root=`/anchor value
# differs from `paths.py`'s own default.
#
# `_verify_nested_case_path()` then walks EVERY intermediate segment
# (`drafting`, `drafting/inputs`, `drafting/inputs/audit`, etc.) from
# that verified case root, re-verifying containment at EACH level that
# ACTUALLY EXISTS - catching an escape at ANY depth, not just the final
# leaf - and stops, fail-closed BEFORE any read, the instant one is
# found. A directory that has never been created at all (the case has
# no saved input/audit/history yet) is not a security concern - there
# is nothing there to escape through - so a missing segment simply
# yields the plain, not-yet-existing intended path, unresolved, exactly
# like `ui.services.paths.resolve_case_path()`'s own established
# "not-yet-existing leaf: verify the parent only" scope boundary
# (reused here as the same design principle, though this module keeps
# its own copy rather than calling that function directly - `resolve_
# case_path()` is hard-anchored to `paths.CASES_DIR`/`paths.resolve_
# case_id()`, which would NOT track a test's `drafting_request.CASES_
# DIR` redirect the way this module's own writer paths must). Neither
# helper ever creates a directory or file - both are read-only queries
# (`os.path.lexists()`, `Path.resolve(strict=True)` inside `verify_
# real_path_contained()`) - Row 19C-2c binding decision 3 (pre-lock
# snapshot must stay strictly read-only) is unaffected.
#
# ROW 19C-2c BROKEN-LINK FAIL-CLOSED REMEDIATION (targeted re-review
# finding, High severity blocker): "a segment has genuinely never been
# created" and "a symlink/junction entry exists here but its target
# cannot be resolved (deleted, or a resolution loop)" are NOT the same
# thing, and `Path.exists()` cannot tell them apart - it FOLLOWS the
# link and returns `False` for BOTH a truly-absent segment AND a
# present-but-broken/looping one (confirmed empirically on this
# project's target platform: a real NTFS junction whose target was
# deleted reports `exists()=False`, `is_dir()=False`, `is_symlink()=
# False` - junctions are never detected by `is_symlink()` here, this
# project's own established finding - yet `os.path.lexists()=True`, a
# real reparse-point entry is still on disk at that name). The PRIOR
# fix gated on `candidate.exists()` alone, which silently treated a
# broken/looping link exactly like "nothing here yet" - skipping
# `verify_real_path_contained()` (whose own `Path.resolve(strict=True)`
# correctly fails closed on both a broken target and an ELOOP resolution
# cycle, WHEN ACTUALLY CALLED) entirely for this one input class. The
# fix below gates on `os.path.lexists()` instead - "is there a
# filesystem entry (of ANY kind, resolving or not) at this exact name"
# - so a broken or looping link is ALWAYS routed into `verify_real_
# path_contained()`, never silently treated as absent; only a segment
# with NO entry at all (regular or reparse point) is treated as
# not-yet-existing.
# ============================================================


def _resolve_verified_case_dir(case_id: str) -> Path:
    from . import drafting_request as _drafting_request  # lazy, one-way (avoids any import cycle)
    cases_root = _drafting_request.CASES_DIR
    try:
        return _paths.verify_real_path_contained(cases_root / case_id, root=cases_root)
    except _paths.PathContainmentError as error:
        raise DraftingRequestDirectoryScanError(
            f"case dizininin kendisi containment doğrulamasından geçemedi: {case_id!r}"
        ) from error


def _verify_nested_case_path(case_dir_real: Path, *relative_parts: str) -> Path:
    current = case_dir_real
    remaining = list(relative_parts)
    while remaining:
        part = remaining.pop(0)
        candidate = current / part
        # `os.path.lexists()`, NEVER `candidate.exists()` - see this
        # module's own "ROW 19C-2c BROKEN-LINK FAIL-CLOSED REMEDIATION"
        # header comment above. `lexists()` reports True for a symlink/
        # junction entry REGARDLESS of whether its target resolves - a
        # broken or looping link is therefore NEVER treated as "not yet
        # existing"; only a segment with no filesystem entry at all is.
        if not os.path.lexists(candidate):
            return candidate.joinpath(*remaining) if remaining else candidate
        try:
            current = _paths.verify_real_path_contained(candidate, root=case_dir_real)
        except _paths.PathContainmentError as error:
            raise DraftingRequestDirectoryScanError(
                f"{candidate}: containment doğrulaması başarısız (case kökü dışına çözümleniyor "
                "veya çözümlenemiyor - kırık ya da döngüsel bir symlink/junction dahil)."
            ) from error
    return current


# ============================================================
# MANIFEST SCANS - two independent scan functions (audit vs history),
# each strictly READ-ONLY (never `.mkdir()`s, never reserves/creates
# anything - Row 19C-2c approved contract, binding decision 3). BOTH
# ONLY EVER receive a `directory` that has ALREADY been produced by
# `_verify_nested_case_path()` above - see that function's own header
# comment; `_scan_directory()` itself performs no case-root containment
# check of its own (its per-entry `root=directory` check below is
# meaningful and correct ONLY because of that precondition).
# ============================================================


def _classify_audit_entry(name: str) -> str:
    if name.startswith("lawyer_input_save_") and name.endswith(".audit.json"):
        return "audit"
    return "unexpected"


def _classify_history_entry(name: str) -> str:
    if name.startswith("lawyer_input_before_save_") and name.endswith(".json"):
        return "history"
    return "unexpected"


@dataclass(frozen=True)
class _DirectoryScan:
    manifest: tuple          # sorted tuple of (relative_name, content_sha256)
    records: tuple           # tuple of (relative_name, parsed_dict_or_None) - audit scan only
    corrupt_count: int       # audit scan only; always 0 for the history scan


_EMPTY_SCAN = _DirectoryScan(manifest=(), records=(), corrupt_count=0)


def _scan_directory(directory: Path, *, classify, parse_content: bool) -> _DirectoryScan:
    """Shared scan core for BOTH the audit and history directories -
    READ-ONLY: if `directory` does not exist, returns the empty scan
    without ever creating it. `classify` decides "expected-for-this-
    directory" vs "unexpected" per entry name; `parse_content` is True
    only for the audit scan (history entries carry no corrupt concept
    of their own - see this module's own header comment)."""
    directory = Path(directory)

    if not directory.is_dir():
        return _EMPTY_SCAN

    seen_names = set()
    manifest = []
    records = []
    corrupt_count = 0

    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise DraftingRequestDirectoryScanError(f"{directory}: dizin listelenemedi.") from error

    for entry in entries:
        name = entry.name

        if name in seen_names:
            raise DraftingRequestDirectoryScanError(f"{directory}: yinelenen dizin girişi adı: {name!r}")
        seen_names.add(name)

        if not entry.is_file():
            raise DraftingRequestDirectoryScanError(
                f"{directory}: beklenmeyen (dosya olmayan) dizin girişi: {name!r}"
            )

        if classify(name) == "unexpected":
            raise DraftingRequestDirectoryScanError(f"{directory}: beklenmeyen dizin girişi: {name!r}")

        try:
            verified_path = _paths.verify_real_path_contained(entry, root=directory)
        except _paths.PathContainmentError as error:
            raise DraftingRequestDirectoryScanError(
                f"{directory}: girişin containment doğrulaması başarısız: {name!r}"
            ) from error

        content_hash = sha256_file(verified_path)
        if content_hash is None:
            raise DraftingRequestDirectoryScanError(
                f"{directory}: giriş tarama sırasında kayboldu/okunamadı: {name!r}"
            )

        manifest.append((name, content_hash))

        if parse_content:
            try:
                with open(verified_path, "r", encoding="utf-8") as file:
                    record = json.load(file)
                if not isinstance(record, dict):
                    raise ValueError("audit record is not a JSON object")
            except Exception:
                corrupt_count += 1
                records.append((name, None))
            else:
                records.append((name, record))

    return _DirectoryScan(
        manifest=tuple(sorted(manifest)), records=tuple(records), corrupt_count=corrupt_count,
    )


def _scan_audit_directory(audit_dir: Path) -> _DirectoryScan:
    return _scan_directory(audit_dir, classify=_classify_audit_entry, parse_content=True)


def _scan_history_directory(history_dir: Path) -> _DirectoryScan:
    return _scan_directory(history_dir, classify=_classify_history_entry, parse_content=False)


def _matching_audit_candidates(scan: _DirectoryScan, *, mutation_idempotency_key: str) -> list:
    """Identity-ONLY candidate matching (never filename-prefiltered) -
    see this module's own header comment, "UNLIKE LAYER B..."."""
    return [
        (name, record) for name, record in scan.records
        if record is not None and record.get("mutation_idempotency_key") == mutation_idempotency_key
    ]


# ============================================================
# COMPOSITE PRE-STATE SNAPSHOT
# ============================================================

_SNAPSHOT_VERSION = "row19c2c.drafting_request.v1"


@dataclass(frozen=True)
class DraftingRequestPreconditionSnapshot:
    current_input_token: str
    audit_manifest_count: int
    audit_manifest_digest: str
    history_manifest_count: int
    history_manifest_digest: str
    composite_digest: str


def _canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _compute_snapshot(current_input_token: str, audit_dir: Path, history_dir: Path):
    """Returns `(DraftingRequestPreconditionSnapshot, audit_scan,
    history_scan)` - the two scans are returned alongside the snapshot
    so callers that already need to inspect their contents (the
    admission gate, replay verification) never re-scan either directory
    a second time for the exact same read. STRICTLY READ-ONLY - see
    `_scan_directory()`'s own docstring."""
    audit_scan = _scan_audit_directory(audit_dir)
    history_scan = _scan_history_directory(history_dir)

    audit_manifest_digest = hashlib.sha256(_canonical_json(list(audit_scan.manifest))).hexdigest()
    history_manifest_digest = hashlib.sha256(_canonical_json(list(history_scan.manifest))).hexdigest()

    payload = _canonical_json({
        "snapshot_version": _SNAPSHOT_VERSION,
        "current_input_token": current_input_token,
        "audit_manifest_count": len(audit_scan.manifest),
        "audit_manifest_digest": audit_manifest_digest,
        "history_manifest_count": len(history_scan.manifest),
        "history_manifest_digest": history_manifest_digest,
    })

    snapshot = DraftingRequestPreconditionSnapshot(
        current_input_token=current_input_token,
        audit_manifest_count=len(audit_scan.manifest),
        audit_manifest_digest=audit_manifest_digest,
        history_manifest_count=len(history_scan.manifest),
        history_manifest_digest=history_manifest_digest,
        composite_digest=hashlib.sha256(payload).hexdigest(),
    )
    return snapshot, audit_scan, history_scan


# ============================================================
# DEPENDENCY INJECTION - mirrors every other facade's own
# `_default_authz_repository`/`_resolve_authz_repository`/`_default_
# conn_factory` shape exactly (each layer keeps its OWN independent
# copy - never shared/imported across facades).
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


def resolve_repository(authz_repository=None):
    """Returns `(repository, close)` - `close` MUST be invoked by the
    caller, exactly once, in its own `finally`, once BOTH `authorize_
    outer()` and `apply_drafting_request_mutation()` are done. Unlike
    every other facade in this project, `apply_drafting_request_
    mutation()` itself NEVER opens or closes this repository - see this
    module's own header comment, "WHY THE OUTER AUTHORIZATION STEP
    LIVES OUTSIDE...", for why its lifetime spans two separate calls
    here."""
    return _resolve_authz_repository(authz_repository)


def authorize_outer(principal, case_id, repository):
    """THE OUTER (pre-lock) authorization check - see this module's own
    header comment for why this is a separate, explicit step here
    rather than folded into `apply_drafting_request_mutation()` the way
    every other facade in this project does it. MUST be the very first
    thing `ui.services.drafting_request.save_lawyer_input_from_form()`
    does with a real `case_id` - before `issues.json` is ever read,
    before the wrapper is built, before any lock/connection/journal SQL
    of any kind. Returns the resolved, filesystem-safe case_id."""
    return _authz.authorize_case_access(principal, case_id, "mutate", repository=repository)


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
    actor_ref: str,
    pre_revision: str,
    journal_pre_hash: str | None,
    request_fingerprint: str,
    observed_post_hash: str | None,
    current_raw_sha256: str,
    action: str,
    history_dir: Path,
) -> Path | None:
    """THE 12 EXACT BINDINGS - see this module's own header comment.
    `record` MUST already be the SINGLE clean, idempotency-key-bound
    audit record the cardinality gate selected - this function performs
    NO candidate-set narrowing of its own. `history_dir` MUST already
    be a case-root-verified real Path (see this module's own "ROW
    19C-2c PATH CONTAINMENT REMEDIATION" header comment) - this
    function applies only the SECOND containment layer (direct,
    correctly-named membership) on top of it, never the case-root
    layer itself. Returns the two-layer-verified real backup Path on
    a successful overwrite binding, or `None` for a first-save (never
    an unverified, raw `BASE_DIR / recorded_backup_path` join) - the
    caller reuses this return value directly rather than recomputing
    it."""

    def require(field_name, expected, description):
        recorded = record.get(field_name)
        if not _nonblank(recorded):
            raise DraftingRequestAuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    f"audit record carries a missing/blank {field_name} ({recorded!r}) - an "
                    "unbound audit record is never accepted as corroboration"
                ),
            )
        if recorded != expected:
            raise DraftingRequestAuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    f"audit record carries {field_name}={recorded!r}, which does NOT match "
                    f"this call's own {description} ({expected!r})"
                ),
            )

    # 1. idempotency key
    require("mutation_idempotency_key", idempotency_key, "journal idempotency_key")
    # 2. resource key (shape + equality)
    if not resource_key.startswith(_CASE_RESOURCE_KEY_PREFIX) or not resource_key[len(_CASE_RESOURCE_KEY_PREFIX):]:
        raise DraftingRequestAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=f"resource_key={resource_key!r} is not a well-formed case:<case_id> key",
        )
    require("mutation_resource_key", resource_key, "journal resource_key")
    # 3. actor (real identity)
    require("mutation_actor_ref", actor_ref, "journal actor_label")
    # 4. action/target - fixed constants, verified directly (no audit
    #    field needed - ACTION_FAMILY/TARGET_REF/TARGET_STATE never vary).
    #    (Nothing to check against the audit record here - this binding
    #    is enforced structurally, by this module never constructing an
    #    intent with any other value - see `apply_drafting_request_
    #    mutation()` below.)
    # 5. case_id
    require("case_id", case_id, "case_id")
    # 6. pre_revision <-> audit previous_input_token
    require("previous_input_token", pre_revision, "journal pre_revision")
    # 7. secondary_input_hash (folded into request_fingerprint) <->
    #    audit lawyer_input_hash - checked via binding 12's recomputed
    #    fingerprint below, using this SAME field's value.
    # 8. audit new_current_raw_sha256 <-> CURRENT lawyer_input.json hash
    require("new_current_raw_sha256", current_raw_sha256, "CURRENT lawyer_input.json hash")
    # 9. completed-replay observed-post hash
    if not _nonblank(observed_post_hash):
        raise DraftingRequestAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=f"journal row records a missing/blank observed_post_hash ({observed_post_hash!r})",
        )
    if observed_post_hash != current_raw_sha256:
        raise DraftingRequestAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                f"journal observed_post_hash={observed_post_hash!r} does not match the CURRENT "
                f"lawyer_input.json hash {current_raw_sha256!r}"
            ),
        )
    # 10/11. audit/history backup link. ROW 19C-2c PATH CONTAINMENT
    # REMEDIATION: `history_dir` (the caller's own parameter) MUST
    # already be a case-root-verified real Path (produced by `_verify_
    # nested_case_path()`) - this function never re-derives or re-
    # verifies the case root itself, it only applies the SECOND layer
    # (expected audit/history directory MEMBERSHIP: a DIRECT child,
    # correctly named, per `_classify_history_entry()` - the SAME rule
    # a legitimately-scanned entry must satisfy) on top of that
    # already-verified root.
    recorded_backup_path = record.get("history_backup_path")
    verified_backup_path = None
    if action == "first_save":
        if recorded_backup_path is not None:
            raise DraftingRequestAuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    f"audit record's own action is 'first_save' but history_backup_path is "
                    f"{recorded_backup_path!r} (must be exactly None for a first save)"
                ),
            )
    else:
        if not _nonblank(recorded_backup_path):
            raise DraftingRequestAuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    f"audit record's own action is {action!r} but history_backup_path is missing/"
                    f"blank ({recorded_backup_path!r}) - an overwrite MUST carry a backup link"
                ),
            )
        backup_path = (_paths.BASE_DIR / recorded_backup_path).resolve()
        try:
            verified_backup_path = _paths.verify_real_path_contained(backup_path, root=history_dir)
        except _paths.PathContainmentError as error:
            raise DraftingRequestAuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=f"audit record's history_backup_path is not contained under {history_dir}",
            ) from error
        if verified_backup_path.parent != history_dir or _classify_history_entry(verified_backup_path.name) != "history":
            raise DraftingRequestAuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    "audit record's history_backup_path does not name a DIRECT, correctly-named "
                    f"member of the verified history directory {history_dir}"
                ),
            )
        backup_hash = sha256_file(verified_backup_path)
        if backup_hash is None or backup_hash != pre_revision:
            raise DraftingRequestAuditBindingVerificationFailedError(
                journal_id=journal_id, idempotency_key=idempotency_key,
                reason=(
                    "the backup file's own raw content hash does not match this journal row's "
                    f"pre_revision ({pre_revision!r})"
                ),
            )
    # 12. recomputed request fingerprint (folds in binding 7).
    raw_note_hash = record.get("lawyer_input_hash")
    reconstructed = MutationIntent(
        actor_type="iam_user", actor_ref=actor_ref,
        resource_key=resource_key, action_family=ACTION_FAMILY,
        target_ref=TARGET_REF, target_state=TARGET_STATE,
        pre_hash=journal_pre_hash, pre_revision=pre_revision,
        secondary_input_hash=raw_note_hash,
    )
    recomputed_fingerprint = compute_request_fingerprint(reconstructed)
    if recomputed_fingerprint != request_fingerprint:
        raise DraftingRequestAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key,
            reason=(
                "the request_fingerprint recomputed purely from this audit record's own content "
                f"({recomputed_fingerprint!r}) does not match the journal row's own stored "
                f"request_fingerprint ({request_fingerprint!r})"
            ),
        )

    return verified_backup_path


@dataclass(frozen=True)
class DraftingRequestMutationResult:
    """Deliberately narrower than `save_lawyer_input_from_form()`'s own
    pre-Row-19C-2c return dict; that function reconstructs the exact
    same public shape (the full saved wrapper) from this result plus
    (on a replay) the single matching audit record - see that
    function's own docstring."""

    wrapper: dict
    audit_path: Path | None
    history_backup_path: Path | None
    journal_id: int
    replayed: bool


def apply_drafting_request_mutation(
    case_id: str,
    wrapper: dict,
    expected_current_input_hash: str,
    *,
    principal,
    repository,
    conn_factory=None,
) -> DraftingRequestMutationResult:
    """The Row 19C-2c coordinated, journaled, idempotent entry point for
    ONE Row 18C structured-lawyer-input save, under the SAME
    session-level `case:<case_id>` lock every other file-write mutation
    on this case uses (Row 19A design decision - one lock per case, not
    one per family).

    `case_id` MUST already be the OUTER-resolved, filesystem-safe value
    `authorize_outer()` returned - this function's own INNER authz
    re-check re-resolves the SAME raw string and fails closed
    (`DraftingRequestResolvedCaseIdMismatchError`) if it somehow
    differs. `repository` MUST already be open (from `resolve_
    repository()`) - this function NEVER opens or closes it (see this
    module's own header comment).

    `wrapper` MUST already be the fully-built, schema-and-consistency-
    validated wrapper `save_lawyer_input_from_form()` constructs before
    calling this function - `wrapper["lawyer_input_hash"]` (== `drafting_
    policy.compute_lawyer_input_hash(wrapper["lawyer_input"])`, the ONE
    content-normalization/hashing source this integration uses) becomes
    `secondary_input_hash` directly, unchanged.

    Every filesystem path this function touches (the current input
    file, the audit directory, the history directory) is derived from
    `case_id` via `_resolve_verified_case_dir()` + `_verify_nested_
    case_path()` - see those functions' own header comment ("ROW
    19C-2c PATH CONTAINMENT REMEDIATION") - never a raw, unverified
    `drafting_request.get_inputs_dir(case_id)` join. There is
    deliberately no test-only path-override parameter any more: every
    caller, test or production, reaches these paths through the SAME
    containment-verified derivation, anchored to `drafting_request.
    CASES_DIR` (read dynamically, so a test that redirects it - as
    `ui/tests/test_drafting_request_service_isolated.py` already does -
    is still fully covered).

    ORDER:
      1. Resolve and containment-verify the case directory, then the
         current-input/audit/history paths under it, compute the
         CURRENT input token, then the PRE-LOCK composite snapshot
         (recorded as `pre_hash`) - all STRICTLY READ-ONLY.
      2. Open the journal connection, acquire the session-level lock.
      3. `run_mutation()` - INNER (authoritative) authz, journal gate,
         idempotency lookup, under-lock precondition re-verification
         (fresh containment re-verification, composite-race check,
         plain stale-hash check, admission gate), then (only for a
         genuinely new mutation) `prepared` -> `executing` -> writer ->
         `completed`.
      4. On a safe REPLAY only: fresh containment re-verification, then
         the 12 exact audit bindings.
      5. Release the lock, close the journal connection. The IAM authz
         repository is NEVER closed here - see this module's own header
         comment.

    Raises: `DraftingRequestStaleInputError`, `DraftingRequest
    PreconditionRaceDetectedError` (a `DraftingRequestStaleInputError`
    subclass), `DraftingRequestResolvedCaseIdMismatchError`,
    `DraftingRequestDirectoryScanError` (including a case-root or
    nested audit/history/current-input containment failure - see the
    Row 19C-2c path containment remediation above),
    `authz.CaseAccessDeniedError`; ADDITIONALLY whatever `ui.services.
    mutation_coordinator.run_mutation()` itself raises
    (`ResourceGatedError`, `IdempotencyConflictError`,
    `PriorAttemptFailedError`, `JournalExecutingTransitionFailedError`,
    `JournalCompletionUncertainError`); and this module's own
    `DraftingRequestAuditBindingVerificationFailedError`. NONE of these
    are caught or reclassified here - the caller (`ui/main.py`) decides
    the HTTP mapping."""

    from . import drafting_request as _drafting_request  # lazy, one-way (avoids any import cycle)

    case_dir_real = _resolve_verified_case_dir(case_id)

    current_path = _verify_nested_case_path(case_dir_real, "drafting", "inputs", _drafting_request.CURRENT_FILENAME)
    audit_dir = _verify_nested_case_path(case_dir_real, "drafting", "inputs", "audit")
    history_dir = _verify_nested_case_path(case_dir_real, "drafting", "inputs", "history")

    resource_key = _mutation_lock.case_resource_key(case_id)

    current_input_token = sha256_file(current_path) or _drafting_request.NO_EXISTING_INPUT_SENTINEL

    # PRE-LOCK composite snapshot - recorded as this attempt's
    # `pre_hash`, re-verified under the lock. Read AFTER the outer authz
    # has already succeeded (the caller's own responsibility), never
    # before it.
    pre_lock_snapshot, _pre_audit_scan, _pre_history_scan = _compute_snapshot(
        current_input_token, audit_dir, history_dir,
    )

    actor_ref = str(principal.user_id)

    intent = MutationIntent(
        actor_type="iam_user",
        actor_ref=actor_ref,
        resource_key=resource_key,
        action_family=ACTION_FAMILY,
        target_ref=TARGET_REF,
        target_state=TARGET_STATE,
        # FILESYSTEM EVIDENCE (composite) - recorded and re-verified,
        # deliberately NOT part of mutation identity.
        pre_hash=pre_lock_snapshot.composite_digest,
        # The REQUEST's own claim - part of mutation identity.
        pre_revision=expected_current_input_hash,
        # Part of the request's own OUTCOME identity (fingerprint only,
        # never idempotency) - the ONE content-normalization/hashing
        # source this integration uses (drafting_policy.compute_lawyer_
        # input_hash, already computed by the caller into
        # wrapper["lawyer_input_hash"]).
        secondary_input_hash=wrapper.get("lawyer_input_hash"),
    )
    idempotency_key_for_audit = compute_idempotency_key(intent)
    request_fingerprint_for_audit = compute_request_fingerprint(intent)

    def authz_callback() -> None:
        # INNER (AUTHORITATIVE) AUTHORIZATION - re-resolves the SAME
        # raw case_id using the SAME already-open repository the outer
        # check used.
        inner_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )
        if inner_resolved_case_id != case_id:
            raise DraftingRequestResolvedCaseIdMismatchError(
                f"outer (pre-lock) authorization resolved case_id={case_id!r} but the inner "
                f"(under-lock) authorization resolved {inner_resolved_case_id!r} - refusing to proceed"
            )

    def precondition_callback() -> None:
        # Reached ONLY when a genuinely NEW mutation is needed - so
        # every raise below leaves ZERO journal rows and never invokes
        # the writer. ROW 19C-2c PATH CONTAINMENT REMEDIATION: the case
        # root and every nested path are FRESHLY re-verified here, under
        # the lock, exactly like `current_input_token`'s own value is -
        # a nested audit/history/current-input escape introduced WHILE
        # this request waited for the lock is caught HERE, fail-closed,
        # either directly (`DraftingRequestDirectoryScanError` from a
        # genuine escape) or via the composite-digest mismatch below (a
        # legitimate, non-escaping change to the same real directory).
        under_lock_case_dir_real = _resolve_verified_case_dir(case_id)
        under_lock_current_path = _verify_nested_case_path(
            under_lock_case_dir_real, "drafting", "inputs", _drafting_request.CURRENT_FILENAME,
        )
        under_lock_audit_dir = _verify_nested_case_path(under_lock_case_dir_real, "drafting", "inputs", "audit")
        under_lock_history_dir = _verify_nested_case_path(under_lock_case_dir_real, "drafting", "inputs", "history")

        under_lock_current_token = sha256_file(under_lock_current_path) or _drafting_request.NO_EXISTING_INPUT_SENTINEL
        under_lock_snapshot, under_lock_audit_scan, _under_lock_history_scan = _compute_snapshot(
            under_lock_current_token, under_lock_audit_dir, under_lock_history_dir,
        )

        if under_lock_snapshot.composite_digest != pre_lock_snapshot.composite_digest:
            raise DraftingRequestPreconditionRaceDetectedError(
                "Bu kaydetme isteği case kilidini beklerken ilgili dosyalar DEĞİŞTİ (girdi veya "
                "audit/geçmiş dizini artık aynı değil). Kaydetme iptal edildi, HİÇBİR değişiklik "
                "yapılmadı - lütfen sayfayı yenileyip tekrar deneyin."
            )

        if under_lock_snapshot.current_input_token != expected_current_input_hash:
            raise DraftingRequestStaleInputError(
                "Girdi bu ekran açıldıktan sonra değişti (o zamanki hash: "
                f"{expected_current_input_hash}, şimdiki: {under_lock_snapshot.current_input_token}). "
                "Kaydetme iptal edildi - lütfen sayfayı yenileyip tekrar deneyin."
            )

        # PRE-EXISTING AUDIT ADMISSION GATE - see this module's own
        # header comment, "UNLIKE LAYER B...". Historical entries are
        # normal; only a candidate (clean OR corrupt) bound to THIS
        # exact proposed idempotency key is rejected.
        matches = _matching_audit_candidates(
            under_lock_audit_scan, mutation_idempotency_key=idempotency_key_for_audit,
        )
        if under_lock_audit_scan.corrupt_count != 0 or len(matches) != 0:
            raise DraftingRequestPreconditionRaceDetectedError(
                "Bu kaydetme denemesiyle aynı kimliğe (idempotency) sahip beklenmedik (önceden "
                "mevcut veya bozuk) bir audit kaydı bulundu - kaydetme iptal edildi, hiçbir "
                "değişiklik yapılmadı. Lütfen sayfayı yenileyip tekrar deneyin; sorun devam ederse "
                "sistem yöneticisiyle iletişime geçin."
            )

    def writer_callback() -> _mutation_coordinator.WriterResult:
        writer_result = _drafting_request.save_lawyer_input(
            case_id, wrapper, expected_current_input_hash,
            current_path_override=current_path, audit_dir_override=audit_dir, history_dir_override=history_dir,
            mutation_idempotency_key=idempotency_key_for_audit,
            mutation_resource_key=resource_key,
            mutation_actor_ref=actor_ref,
        )
        observed_post_hash = sha256_file(current_path)
        return _mutation_coordinator.WriterResult(
            observed_post_hash=observed_post_hash, result=writer_result,
        )

    resolved_conn_factory = conn_factory or _default_conn_factory
    conn = resolved_conn_factory()
    advisory_lock_id = _mutation_lock.acquire_case_lock_session(conn, case_id)
    try:
        outcome = _mutation_coordinator.run_mutation(
            conn, intent,
            actor_user_id=principal.user_id,
            authz_callback=authz_callback,
            precondition_callback=precondition_callback,
            writer_callback=writer_callback,
        )

        if outcome.replayed:
            # See this module's own header comment ("12 EXACT SEMANTIC
            # BINDINGS") - independent corroboration is required ONLY
            # on a replay (the writer was NOT re-invoked). ROW 19C-2c
            # PATH CONTAINMENT REMEDIATION: `run_mutation()` returns a
            # replay BEFORE `precondition_callback()` is ever called
            # (see `mutation_coordinator.py`'s own idempotency-lookup
            # short-circuit), so this is the FIRST re-verification since
            # the pre-lock one for a replayed attempt - freshly re-
            # resolved here, under the lock, rather than trusting the
            # pre-lock `audit_dir`/`history_dir`/`current_path` values.
            post_case_dir_real = _resolve_verified_case_dir(case_id)
            post_current_path = _verify_nested_case_path(
                post_case_dir_real, "drafting", "inputs", _drafting_request.CURRENT_FILENAME,
            )
            post_audit_dir = _verify_nested_case_path(post_case_dir_real, "drafting", "inputs", "audit")
            post_history_dir = _verify_nested_case_path(post_case_dir_real, "drafting", "inputs", "history")

            _post_snapshot, post_audit_scan, _post_history_scan = _compute_snapshot(
                sha256_file(post_current_path) or _drafting_request.NO_EXISTING_INPUT_SENTINEL,
                post_audit_dir, post_history_dir,
            )
            matches = _matching_audit_candidates(
                post_audit_scan, mutation_idempotency_key=idempotency_key_for_audit,
            )
            if post_audit_scan.corrupt_count != 0 or len(matches) != 1:
                raise DraftingRequestAuditBindingVerificationFailedError(
                    journal_id=outcome.journal_id, idempotency_key=idempotency_key_for_audit,
                    reason=(
                        "expected exactly one clean, idempotency-key-bound audit record for replay "
                        f"verification; found {len(matches)} clean match(es) and "
                        f"{post_audit_scan.corrupt_count} corrupt candidate(s)"
                    ),
                )
            audit_name, audit_record = matches[0]

            current_raw_sha256 = sha256_file(post_current_path)
            if current_raw_sha256 is None:
                raise DraftingRequestAuditBindingVerificationFailedError(
                    journal_id=outcome.journal_id, idempotency_key=idempotency_key_for_audit,
                    reason=f"lawyer_input.json at {post_current_path} does not exist right now",
                )

            verified_backup_path = _verify_completed_replay_audit_binding(
                audit_record,
                journal_id=outcome.journal_id,
                idempotency_key=idempotency_key_for_audit,
                resource_key=resource_key,
                case_id=case_id,
                actor_ref=actor_ref,
                pre_revision=expected_current_input_hash,
                journal_pre_hash=intent.pre_hash,
                request_fingerprint=request_fingerprint_for_audit,
                observed_post_hash=outcome.observed_post_hash,
                current_raw_sha256=current_raw_sha256,
                action=audit_record.get("action"),
                history_dir=post_history_dir,
            )

            # Reconstruct the SAME public wrapper shape a fresh save
            # returns, from the CURRENT (just re-verified) file content
            # - never re-derived from a fresh write, since the writer
            # was not re-invoked.
            reconstructed_wrapper = _drafting_request._load_json_file(post_current_path)
            result = DraftingRequestMutationResult(
                wrapper=reconstructed_wrapper,
                audit_path=post_audit_dir / audit_name,
                # ROW 19C-2c PATH CONTAINMENT REMEDIATION: NEVER
                # recomputed as a raw, unverified `BASE_DIR /
                # recorded_backup_path` join here - `_verify_completed_
                # replay_audit_binding()` above ALREADY produced (and
                # two-layer-verified) this exact value as part of
                # binding 10/11; reused directly, never re-derived.
                history_backup_path=verified_backup_path,
                journal_id=outcome.journal_id,
                replayed=True,
            )
        else:
            # A FRESH execution's own successful writer return is
            # itself sufficient completion proof.
            writer_result = outcome.result
            result = DraftingRequestMutationResult(
                wrapper=writer_result["wrapper"],
                audit_path=writer_result["audit_path"],
                history_backup_path=writer_result["history_backup_path"],
                journal_id=outcome.journal_id,
                replayed=False,
            )

        return result
    finally:
        # CLEANUP THAT CAN NEVER MASK THE OUTCOME - mirrors every other
        # facade's own final cleanup discipline exactly. The IAM authz
        # `repository` itself is NEVER closed here (see this module's
        # own header comment) - only the journal/lock connection.
        try:
            try:
                released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
            except Exception as release_error:
                _log_critical_safely(
                    f"CRITICAL: apply_drafting_request_mutation() RAISED while releasing the "
                    f"session lock for resource_key={resource_key!r} (advisory_lock_id="
                    f"{advisory_lock_id!r}): {release_error!r} - this process may still hold "
                    "the resource's advisory lock; investigate out of band"
                )
            else:
                if not released:
                    _log_critical_safely(
                        f"CRITICAL: apply_drafting_request_mutation() failed to release the session "
                        f"lock for resource_key={resource_key!r} (advisory_lock_id={advisory_lock_id!r}) "
                        "- this process may still hold the resource's advisory lock; investigate "
                        "out of band"
                    )
        finally:
            try:
                conn.close()
            except Exception as close_error:
                _log_critical_safely(
                    f"CRITICAL: apply_drafting_request_mutation() failed to close its journal/lock "
                    f"connection for resource_key={resource_key!r}: {close_error!r} - the mutation "
                    "outcome itself is unaffected and is being reported unchanged; investigate this "
                    "out of band"
                )
