# ============================================================
# VERGİ AI - ROW 19C-2c: DRAFTING-REQUEST RECONCILIATION ADAPTER.
#
# ONE `ui.services.mutation_registry.ReconciliationAdapter` for
# `action_family="drafting_request.save"` - the REAL `MutationAdapter
# Registry` `ui/reconciliation_operator.py`'s own `_default_registry_
# factory()` folds together with Layer A's `mutation_approval_adapters.
# build_production_registry()` and Layer B's `review_mutation_adapters.
# register_into()` into ONE merged registry (see that module's own
# updated header comment).
#
# IMPORT TOPOLOGY: this module (unlike `drafting_request_mutation_
# facade.py`) is free to import `ui.services.drafting_request` directly
# - a safe, one-way edge (`drafting_request.py` never imports this
# module).
#
# INDEPENDENT EVIDENCE, NEVER CIRCULAR, NEVER SHARED WITH THE FACADE:
# `gather_evidence()` below never trusts the journal row's own
# `expected_post_hash`/`pre_hash` as proof of anything. It independently
# re-reads the ACTUAL `lawyer_input.json` file and the ACTUAL audit/
# history directories - the SAME artefacts a human reviewer would look
# at - and reports what it genuinely finds. The manifest-scan and
# audit-binding logic below is a SEPARATE, INDEPENDENTLY-WRITTEN
# implementation from `drafting_request_mutation_facade.py`'s own (this
# module deliberately does NOT import `_scan_audit_directory`/`_scan_
# history_directory`/`_compute_snapshot`/`_verify_completed_replay_
# audit_binding` from that module) - a bug in one must never be masked
# by the other reusing it, exactly the same principle every other
# layer's adapters module states for itself.
#
# ROW 19C-2c BINDING DECISION (approved contract, 2026-09-08):
# `pre_state_confirmed_unchanged=True` may be reported ONLY when ALL
# THREE of the following hold, together - a current-file-token match
# ALONE is never sufficient:
#   1. the recomputed composite snapshot digest == `entry.pre_hash`;
#   2. the current input token == `entry.pre_revision`;
#   3. zero matching (idempotency-key-bound) audit candidates AND zero
#      corrupt audit candidates in the audit directory.
# `post_state_verified=True` requires the current file to exist, EXACTLY
# ONE clean audit candidate bound to `entry.idempotency_key` (zero
# corrupt candidates anywhere in the directory), and the 11 (of the
# facade's own 12 - see `_bindings_match()`'s own docstring for exactly
# which one is structurally inapplicable here, and why) independently-
# implemented bindings `_bindings_match()` below checks to ALL hold.
#
# ROW 19C-2c PATH CONTAINMENT REMEDIATION: `gather_evidence()` below
# derives `current_path`/`audit_dir`/`history_dir` via this module's OWN
# `_resolve_verified_case_dir()`/`_verify_nested_case_path()` (never a
# raw `drafting_request.get_inputs_dir(case_id)` join) - see those two
# functions' own header comment for the full rationale (a directory that
# is itself an escaping symlink/junction must never be trusted merely
# because per-entry checks pass relative to it).
# ============================================================

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mutation_guard import MutationIntent, compute_request_fingerprint  # noqa: E402

from . import mutation_registry as mr
from . import paths as _paths
from .common import sha256_file
from .drafting_request_mutation_facade import ACTION_FAMILY, TARGET_REF, TARGET_STATE


class UnexpectedResourceKeyShapeError(Exception):
    """Raised if a journal entry routed to this adapter somehow does
    not carry a `case:<case_id>` resource_key - structurally
    unreachable today (this family always locks `case:<case_id>` - see
    `drafting_request_mutation_facade.apply_drafting_request_mutation()`),
    kept as a fail-closed backstop in the same spirit as
    `ui.services.mutation_registry.ResourceKeyMismatchError`."""


class DraftingRequestReconciliationScanError(Exception):
    """Raised for the SAME filesystem-level anomalies `drafting_
    request_mutation_facade.DraftingRequestDirectoryScanError` raises
    for the live path - a reconciliation run over a directory in this
    state cannot produce reliable evidence at all; propagated as a
    genuine adapter-internal failure (per `ReconciliationAdapter.
    gather_evidence()`'s own Protocol docstring)."""


def _nonblank(value) -> bool:
    """Deliberately this module's OWN copy of the same rule the facade
    applies - see this module's own header comment on why the two
    verification paths stay independent rather than sharing an
    implementation."""
    return isinstance(value, str) and bool(value.strip())


# ============================================================
# ROW 19C-2c PATH CONTAINMENT REMEDIATION - this module's OWN,
# INDEPENDENTLY-WRITTEN copy of the SAME two helpers `drafting_
# request_mutation_facade.py` uses (never imported from there - see
# this module's own header comment, "INDEPENDENT EVIDENCE..." - a bug
# in one path-safety implementation must never be masked by the other
# reusing it). `paths.verify_real_path_contained(entry, root=audit_dir)`
# alone is NOT sufficient if `audit_dir` (or `history_dir`, or the
# parent chain of `lawyer_input.json`) is ITSELF a symlink/NTFS
# junction escaping `CASES_DIR` - every entry under it would then
# resolve "contained" relative to that already-escaped root. These two
# helpers verify the DIRECTORY ITSELF (and every intermediate segment
# leading to it) against the case root FIRST, before any scan/read.
#
# ROW 19C-2c BROKEN-LINK FAIL-CLOSED REMEDIATION (targeted re-review
# finding, High severity blocker): a symlink/junction entry whose
# target cannot be resolved (deleted, or a resolution loop) is NOT the
# same thing as "no filesystem entry here at all", and `Path.exists()`
# cannot tell them apart - it FOLLOWS the link and returns `False` for
# BOTH. `os.path.lexists()` is used instead below - it reports True for
# ANY filesystem entry at that exact name, resolving or not - so a
# broken/looping link is ALWAYS routed into `verify_real_path_
# contained()` (whose own `Path.resolve(strict=True)` already fails
# closed correctly on both a broken target and an ELOOP cycle, WHEN
# ACTUALLY CALLED), never silently treated as "not yet existing". This
# is this module's OWN, independently-written copy of the SAME fix
# `drafting_request_mutation_facade.py` applies - see that module's own
# header comment (above its `_verify_nested_case_path()`) for the full
# empirical rationale; never imported from there, same non-masking
# principle as the rest of this module.
# ============================================================


def _resolve_verified_case_dir(case_id: str) -> Path:
    from . import drafting_request as _drafting_request  # lazy, one-way
    cases_root = _drafting_request.CASES_DIR
    try:
        return _paths.verify_real_path_contained(cases_root / case_id, root=cases_root)
    except _paths.PathContainmentError as error:
        raise DraftingRequestReconciliationScanError(
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
        # header comment above.
        if not os.path.lexists(candidate):
            return candidate.joinpath(*remaining) if remaining else candidate
        try:
            current = _paths.verify_real_path_contained(candidate, root=case_dir_real)
        except _paths.PathContainmentError as error:
            raise DraftingRequestReconciliationScanError(
                f"{candidate}: containment doğrulaması başarısız (case kökü dışına çözümleniyor "
                "veya çözümlenemiyor - kırık ya da döngüsel bir symlink/junction dahil)."
            ) from error
    return current


def _classify_audit_entry(name: str) -> str:
    if name.startswith("lawyer_input_save_") and name.endswith(".audit.json"):
        return "audit"
    return "unexpected"


class _AuditDirectoryScan:
    __slots__ = ("manifest", "records", "corrupt_count")

    def __init__(self, manifest, records, corrupt_count):
        self.manifest = manifest
        self.records = records
        self.corrupt_count = corrupt_count


_EMPTY_AUDIT_SCAN = _AuditDirectoryScan(manifest=(), records=(), corrupt_count=0)


def _canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _scan_audit_directory(audit_dir: Path) -> _AuditDirectoryScan:
    """This module's OWN, independently-written scan (never imports
    the facade's own `_scan_audit_directory()`) - fail-closed on the
    SAME conditions (containment escape, non-regular-file entry,
    duplicate name, unreadable/vanished entry, unexpected entry name);
    a corrupt-JSON `.audit.json` file is tracked (`corrupt_count`),
    never a scan abort."""
    audit_dir = Path(audit_dir)

    if not audit_dir.is_dir():
        return _EMPTY_AUDIT_SCAN

    seen_names = set()
    manifest = []
    records = []
    corrupt_count = 0

    try:
        entries = sorted(audit_dir.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise DraftingRequestReconciliationScanError(f"{audit_dir}: dizin listelenemedi.") from error

    for entry in entries:
        name = entry.name

        if name in seen_names:
            raise DraftingRequestReconciliationScanError(f"{audit_dir}: yinelenen dizin girişi adı: {name!r}")
        seen_names.add(name)

        if not entry.is_file():
            raise DraftingRequestReconciliationScanError(
                f"{audit_dir}: beklenmeyen (dosya olmayan) dizin girişi: {name!r}"
            )

        if _classify_audit_entry(name) == "unexpected":
            raise DraftingRequestReconciliationScanError(f"{audit_dir}: beklenmeyen dizin girişi: {name!r}")

        try:
            verified_path = _paths.verify_real_path_contained(entry, root=audit_dir)
        except _paths.PathContainmentError as error:
            raise DraftingRequestReconciliationScanError(
                f"{audit_dir}: girişin containment doğrulaması başarısız: {name!r}"
            ) from error

        content_hash = sha256_file(verified_path)
        if content_hash is None:
            raise DraftingRequestReconciliationScanError(
                f"{audit_dir}: giriş tarama sırasında kayboldu/okunamadı: {name!r}"
            )

        manifest.append((name, content_hash))

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

    return _AuditDirectoryScan(manifest=tuple(sorted(manifest)), records=tuple(records), corrupt_count=corrupt_count)


def _matching_candidates(scan: _AuditDirectoryScan, *, mutation_idempotency_key: str):
    return [
        (name, record) for name, record in scan.records
        if record is not None and record.get("mutation_idempotency_key") == mutation_idempotency_key
    ]


def _classify_history_entry(name: str) -> str:
    if name.startswith("lawyer_input_before_save_") and name.endswith(".json"):
        return "history"
    return "unexpected"


def _bindings_match(record: dict, entry: mr.JournalEntrySnapshot, *, current_raw_sha256: str, history_dir: Path) -> bool:
    """11 OF THE 12 EXACT BINDINGS (reconciliation phase) -
    independently implemented, never imported from the facade. Returns
    True only when ALL applicable bindings hold exactly; any missing,
    blank or mismatched value returns False (inconclusive), never
    raises.

    Binding 9 (`journal.observed_post_hash == current_raw_sha256`, the
    "completed-replay observed-post hash" check - see `drafting_
    request_mutation_facade._verify_completed_replay_audit_binding()`'s
    own numbered list) is DELIBERATELY ABSENT here, not an oversight:
    `entry.observed_post_hash` is structurally `NULL` for every row
    this adapter is ever invoked on (a row still `prepared`/`executing`/
    `reconciliation_required` never had a `completed` transition record
    one) - reconciliation's whole job is to DETERMINE what that value
    should become, never to verify against one that does not yet exist.
    This binding is meaningful ONLY on the facade's own safe-replay
    path (an ALREADY-`completed` row), where a real `observed_post_
    hash` genuinely exists to corroborate against.

    `history_dir` MUST already be a case-root-verified real Path (see
    this module's own header comment, "ROW 19C-2c PATH CONTAINMENT
    REMEDIATION") - this function applies only the SECOND containment
    layer (direct, correctly-named membership) on top of it."""

    if entry.action_family != ACTION_FAMILY or entry.target_ref != TARGET_REF or entry.target_state != TARGET_STATE:
        return False
    if not _nonblank(record.get("mutation_idempotency_key")) or record.get("mutation_idempotency_key") != entry.idempotency_key:
        return False
    if not entry.resource_key.startswith("case:") or not entry.resource_key[len("case:"):]:
        return False
    if not _nonblank(record.get("mutation_resource_key")) or record.get("mutation_resource_key") != entry.resource_key:
        return False
    if not _nonblank(record.get("mutation_actor_ref")) or record.get("mutation_actor_ref") != entry.actor_label:
        return False
    case_id = entry.resource_key[len("case:"):]
    if record.get("case_id") != case_id:
        return False
    if not _nonblank(record.get("previous_input_token")) or record.get("previous_input_token") != entry.pre_revision:
        return False
    if not _nonblank(record.get("new_current_raw_sha256")) or record.get("new_current_raw_sha256") != current_raw_sha256:
        return False

    action = record.get("action")
    recorded_backup_path = record.get("history_backup_path")
    if action == "first_save":
        if recorded_backup_path is not None:
            return False
    elif action == "overwrite":
        if not _nonblank(recorded_backup_path):
            return False
        try:
            backup_path = (_paths.BASE_DIR / recorded_backup_path).resolve()
            verified_backup_path = _paths.verify_real_path_contained(backup_path, root=history_dir)
        except Exception:
            return False
        if verified_backup_path.parent != history_dir or _classify_history_entry(verified_backup_path.name) != "history":
            return False
        backup_hash = sha256_file(verified_backup_path)
        if backup_hash is None or backup_hash != entry.pre_revision:
            return False
    else:
        return False

    raw_note_hash = record.get("lawyer_input_hash")
    reconstructed = MutationIntent(
        actor_type="iam_user", actor_ref=record.get("mutation_actor_ref"),
        resource_key=entry.resource_key, action_family=entry.action_family,
        target_ref=entry.target_ref, target_state=entry.target_state,
        pre_hash=entry.pre_hash, pre_revision=entry.pre_revision,
        secondary_input_hash=raw_note_hash,
    )
    try:
        recomputed_fingerprint = compute_request_fingerprint(reconstructed)
    except Exception:
        return False
    return recomputed_fingerprint == entry.request_fingerprint


class DraftingRequestReconciliationAdapter:
    """The SINGLE adapter for `action_family="drafting_request.save"` -
    this family has no per-review_kind/per-row_key axis (unlike Layer
    A/B), so unlike those two adapter modules, this one needs no
    per-instance metadata resolution at all beyond the fixed module-
    level `ACTION_FAMILY`/`TARGET_REF`/`TARGET_STATE` constants already
    imported from the facade (pure naming, zero decision logic - the
    SAME kind of import Layer A/B's own adapters already make from
    their facades)."""

    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if not entry.resource_key.startswith("case:"):
            raise UnexpectedResourceKeyShapeError(
                f"journal_id={entry.journal_id}: expected a 'case:<case_id>' resource_key for the "
                f"drafting-request family, got {entry.resource_key!r}"
            )
        case_id = entry.resource_key[len("case:"):]

        from . import drafting_request as _drafting_request  # lazy, one-way

        # ROW 19C-2c PATH CONTAINMENT REMEDIATION: case-root-verified,
        # not a raw `get_inputs_dir(case_id)` join - see this module's
        # own header comment, above `_resolve_verified_case_dir()`. A
        # genuine escape here propagates as `DraftingRequestReconciliation
        # ScanError`, exactly like any other filesystem-level scan
        # anomaly this adapter treats as `gather_evidence()`-internal
        # (caught below, never upgraded to either proof).
        try:
            case_dir_real = _resolve_verified_case_dir(case_id)
            current_path = _verify_nested_case_path(
                case_dir_real, "drafting", "inputs", _drafting_request.CURRENT_FILENAME,
            )
            audit_dir = _verify_nested_case_path(case_dir_real, "drafting", "inputs", "audit")
            history_dir = _verify_nested_case_path(case_dir_real, "drafting", "inputs", "history")
        except DraftingRequestReconciliationScanError:
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        current_raw_sha256 = sha256_file(current_path)
        current_input_token = current_raw_sha256 or _drafting_request.NO_EXISTING_INPUT_SENTINEL

        try:
            audit_scan = _scan_audit_directory(audit_dir)
        except DraftingRequestReconciliationScanError:
            # A filesystem-level anomaly in the audit directory makes
            # this journal entry's evidence unreliable - genuinely
            # inconclusive, never either proof.
            return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

        matches = _matching_candidates(audit_scan, mutation_idempotency_key=entry.idempotency_key)

        # PRE-STATE: all three conditions per the Row 19C-2c binding
        # decision (see this module's own header comment) - never
        # current-token equality alone.
        if (
            current_input_token == entry.pre_revision
            and audit_scan.corrupt_count == 0
            and len(matches) == 0
        ):
            # Recompute the FULL composite digest (independently, not
            # imported from the facade) and require it to equal
            # `entry.pre_hash` too.
            audit_manifest_digest = hashlib.sha256(_canonical_json(list(audit_scan.manifest))).hexdigest()
            history_manifest = self._history_manifest(history_dir)
            if history_manifest is not None:
                history_manifest_digest = hashlib.sha256(_canonical_json(list(history_manifest))).hexdigest()
                payload = _canonical_json({
                    "snapshot_version": "row19c2c.drafting_request.v1",
                    "current_input_token": current_input_token,
                    "audit_manifest_count": len(audit_scan.manifest),
                    "audit_manifest_digest": audit_manifest_digest,
                    "history_manifest_count": len(history_manifest),
                    "history_manifest_digest": history_manifest_digest,
                })
                composite_digest = hashlib.sha256(payload).hexdigest()
                if composite_digest == entry.pre_hash:
                    return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)

        # POST-STATE.
        if current_raw_sha256 is not None and audit_scan.corrupt_count == 0 and len(matches) == 1:
            _name, matched_record = matches[0]
            if _bindings_match(
                matched_record, entry, current_raw_sha256=current_raw_sha256, history_dir=history_dir,
            ):
                return mr.ReconciliationEvidence(
                    post_state_verified=True, pre_state_confirmed_unchanged=False,
                    observed_post_hash=current_raw_sha256,
                )

        # Genuinely inconclusive for THIS specific journal entry - never
        # upgraded to either proof.
        return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

    @staticmethod
    def _history_manifest(history_dir: Path):
        """Returns a sorted `(relative_name, content_sha256)` tuple, or
        `None` on a filesystem-level anomaly (containment escape,
        unreadable entry, unexpected entry) - inconclusive for the
        caller, never a scan abort surfaced here (the pre-state branch
        already gates on this via `is not None`)."""
        history_dir = Path(history_dir)

        if not history_dir.is_dir():
            return ()

        try:
            entries = sorted(history_dir.iterdir(), key=lambda p: p.name)
        except OSError:
            return None

        manifest = []
        seen_names = set()
        for entry in entries:
            name = entry.name
            if name in seen_names:
                return None
            seen_names.add(name)
            if not entry.is_file():
                return None
            if not (name.startswith("lawyer_input_before_save_") and name.endswith(".json")):
                return None
            try:
                verified_path = _paths.verify_real_path_contained(entry, root=history_dir)
            except _paths.PathContainmentError:
                return None
            content_hash = sha256_file(verified_path)
            if content_hash is None:
                return None
            manifest.append((name, content_hash))

        return tuple(sorted(manifest))


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    """Adds the ONE drafting-request adapter to an EXISTING registry
    (immutable builder - returns a NEW registry, never mutates
    `registry` itself) - this is what lets `ui/reconciliation_
    operator.py`'s own `_default_registry_factory()` merge Layer A's,
    Layer B's and Row 18C's adapters into ONE registry a human operator
    can reconcile ANY journal row through, regardless of family."""
    return registry.with_adapter(ACTION_FAMILY, DraftingRequestReconciliationAdapter())


def build_production_registry() -> mr.MutationAdapterRegistry:
    """A STANDALONE registry containing ONLY this one adapter - used by
    this module's own isolated tests. Production callers (`ui/
    reconciliation_operator.py`) use `register_into()` instead."""
    return register_into(mr.MutationAdapterRegistry())
