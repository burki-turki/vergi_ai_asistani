# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION - RECONCILIATION ADAPTERS.
#
# Two independent adapters, one per action family ("rag_bundle.build",
# "rag_bundle.activate") - registered into `ui.reconciliation_
# operator.py`'s merged registry via `register_into()`. Imports the
# facade's own PURE, DECISION-FREE constants/recompute helpers
# (`RAG_BUNDLE_ARTIFACT_NAMES`, `_BUNDLE_VERSION_PATTERN`,
# `_bundle_version_for`, `_compute_source_digest`,
# `_compute_build_input_digest`, `_canonical_json_bytes`,
# `_build_audit_path`, `_activate_audit_dir`, `ACTIVATE_TARGET_REF_PREFIX`,
# `_pointer_composite_hash`, `_POINTER_ABSENT_SENTINEL`, `_index_root`,
# `_ingest_module`) exactly as `ui.services.promotion_mutation_adapters`
# reuses `promotion_mutation_facade.compute_expected_canonical_sha256`
# - but the CONTAINMENT SCANNING and the EVIDENCE DECISION itself are
# independently implemented here, never delegated to the facade - a bug
# in one must never mask a bug in the other. TARGETED F1/F4 REMEDIATION:
# this module does NOT call the facade's own `_build_audit_content_ok`/
# `_activate_audit_content_ok`/`_bundle_has_verified_build_audit`
# recompute-binding functions either (those embody the EVIDENCE
# DECISION, not a pure/decision-free helper) - this module implements
# its own, entirely independent copy of the same §4.2/§4.3 recompute
# bindings below.
#
# NEVER re-invokes build/embedding/network/the writer - every check
# below is read-only filesystem inspection plus pure hashing.
# ============================================================

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import path_containment as _path_containment  # noqa: E402

from . import rag_bundle_mutation_facade as _facade
from . import mutation_registry as mr

_DUAL_FALSE = mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resolve_index_root_real():
    try:
        return Path(_facade._index_root()).resolve(strict=True)
    except OSError:
        return None


def _bundle_dir_self_verifies(index_root_real: Path, bundle_version: str) -> bool:
    """Independent (from `rag_bundle_mutation_facade._verify_bundle_
    self_consistent`) re-implementation: containment, manifest self-hash,
    and all three artifact hashes. Returns True/False only - never
    raises for an ordinary verification failure."""
    if not _facade._BUNDLE_VERSION_PATTERN.match(bundle_version):
        return False
    try:
        bundle_dir = _path_containment.resolve_existing(index_root_real / bundle_version, root=index_root_real)
    except _path_containment.PathContainmentError:
        return False
    if bundle_dir.name != bundle_version or not bundle_dir.is_dir():
        return False
    try:
        manifest_path = _path_containment.resolve_existing(bundle_dir / "manifest.json", root=index_root_real)
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    except (_path_containment.PathContainmentError, OSError, ValueError, UnicodeDecodeError):
        return False
    if not isinstance(manifest, dict) or manifest.get("bundle_version") != bundle_version:
        return False
    identity_core = {key: value for key, value in manifest.items() if key != "bundle_version"}
    try:
        if _facade._bundle_version_for(identity_core) != bundle_version:
            return False
    except (TypeError, ValueError):
        return False
    artifacts_table = manifest.get("artifacts")
    if not isinstance(artifacts_table, dict) or set(artifacts_table.keys()) != set(_facade.RAG_BUNDLE_ARTIFACT_NAMES):
        return False
    for name in _facade.RAG_BUNDLE_ARTIFACT_NAMES:
        entry_info = artifacts_table.get(name)
        if not isinstance(entry_info, dict):
            return False
        try:
            artifact_real = _path_containment.resolve_existing(bundle_dir / name, root=index_root_real)
            raw = artifact_real.read_bytes()
        except (_path_containment.PathContainmentError, OSError):
            return False
        if _sha256_bytes(raw) != entry_info.get("sha256") or len(raw) != entry_info.get("size_bytes"):
            return False
    return True


def _scan_json_records(directory: Path, index_root_real: Path, suffix: str):
    """Containment-before-parse scan of every `*<suffix>` entry directly
    under `directory`. Returns (records, corrupt_count) - `records` is a
    list of (path, dict) for well-formed JSON objects; a containment
    failure on `directory` itself makes the scan return (None, None) (a
    root-level anomaly, distinct from an ordinary empty/absent
    directory)."""
    if not directory.is_dir():
        return [], 0
    try:
        entries = _path_containment.list_contained_dir(directory)
    except _path_containment.PathContainmentError:
        return None, None
    records = []
    corrupt = 0
    for entry in entries:
        if not entry.name.endswith(suffix):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=index_root_real)
        except _path_containment.PathContainmentError:
            corrupt += 1
            continue
        try:
            data = json.loads(resolved.read_bytes().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            corrupt += 1
            continue
        if not isinstance(data, dict):
            corrupt += 1
            continue
        records.append((resolved, data))
    return records, corrupt


def _build_audit_recompute_ok(index_root_real: Path, record: dict):
    """TARGETED F4 REMEDIATION: an INDEPENDENT (adapter-local, never
    calling into the facade's own `_build_audit_content_ok`) re-
    implementation of contract §4.2's five recompute bindings. Reuses
    ONLY the facade's pure, decision-free hash helpers
    (`_compute_build_input_digest`, `_bundle_version_for`) - the
    containment scan (`_scan_json_records` above) and the artifact
    self-verification (`_bundle_dir_self_verifies` above) are ALREADY
    this module's own independent implementations. Returns
    (ok, bundle_version_or_None, recomputed_input_digest_or_None)."""
    identity_payload = record.get("identity_payload")
    if not isinstance(identity_payload, dict):
        return False, None, None
    source_manifest = identity_payload.get("source_manifest")
    pipeline_config = identity_payload.get("pipeline_config")
    build_attempt = identity_payload.get("build_attempt")
    if not isinstance(build_attempt, int) or isinstance(build_attempt, bool):
        return False, None, None
    try:
        recomputed_input_digest = _facade._compute_build_input_digest(source_manifest, pipeline_config, build_attempt)
    except (TypeError, ValueError):
        return False, None, None
    if recomputed_input_digest != record.get("input_digest"):
        return False, None, None
    bundle_version = record.get("bundle_version")
    if not isinstance(bundle_version, str) or not _facade._BUNDLE_VERSION_PATTERN.match(bundle_version):
        return False, None, None
    if not _bundle_dir_self_verifies(index_root_real, bundle_version):
        return False, None, None
    try:
        manifest_path = _path_containment.resolve_existing(index_root_real / bundle_version / "manifest.json", root=index_root_real)
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (_path_containment.PathContainmentError, OSError, ValueError, UnicodeDecodeError):
        return False, None, None
    if record.get("manifest_sha256") != _sha256_bytes(manifest_bytes):
        return False, None, None
    identity_core = {key: value for key, value in manifest.items() if key != "bundle_version"}
    if _facade._bundle_version_for(identity_core) != bundle_version:
        return False, None, None
    if record.get("artifact_hashes") != manifest.get("artifacts"):
        return False, None, None
    if (
        identity_core.get("source_manifest") != source_manifest
        or identity_core.get("pipeline_config") != pipeline_config
        or identity_core.get("build_attempt") != build_attempt
    ):
        return False, None, None
    return True, bundle_version, recomputed_input_digest


def _bundle_has_verified_build_audit(index_root_real: Path, bundle_version: str) -> bool:
    """TARGETED F1 REMEDIATION addition: the ACTIVATE adapter's own
    build-audit GATE check (contract §4.4/§5.2 point 5) - an
    INDEPENDENT copy of the facade's own `_bundle_has_verified_build_
    audit`, never a call into it. Requires AT LEAST ONE fully recompute-
    verified build audit for `bundle_version`, with ZERO corrupt entries
    anywhere in the directory (fail-closed)."""
    audit_dir = index_root_real / "audit" / "build"
    records, corrupt = _scan_json_records(audit_dir, index_root_real, ".build_audit.json")
    if records is None or corrupt != 0:
        return False
    for _path, record in records:
        if record.get("bundle_version") != bundle_version:
            continue
        if record.get("action_family") != _facade.BUILD_ACTION_FAMILY or record.get("resource_key") != _facade.RESOURCE_KEY:
            continue
        ok, found_bundle_version, _digest = _build_audit_recompute_ok(index_root_real, record)
        if ok and found_bundle_version == bundle_version:
            return True
    return False


def _activate_audit_recompute_ok(index_root_real: Path, record: dict):
    """TARGETED F1/F4 REMEDIATION: an INDEPENDENT (adapter-local)
    re-implementation of contract §4.3's recompute bindings. Returns
    (ok, bundle_version_or_None, recomputed_input_digest_or_None)."""
    identity_payload = record.get("identity_payload")
    if not isinstance(identity_payload, dict):
        return False, None, None
    try:
        recomputed_input_digest = _sha256_bytes(_facade._canonical_json_bytes(identity_payload))
    except (TypeError, ValueError):
        return False, None, None
    if recomputed_input_digest != record.get("input_digest"):
        return False, None, None
    bundle_version = identity_payload.get("bundle_version")
    if not isinstance(bundle_version, str) or not _facade._BUNDLE_VERSION_PATTERN.match(bundle_version):
        return False, None, None
    if record.get("bundle_version") != bundle_version:
        return False, None, None
    if record.get("target_ref") != f"{_facade.ACTIVATE_TARGET_REF_PREFIX}{bundle_version}":
        return False, None, None
    if not _bundle_dir_self_verifies(index_root_real, bundle_version):
        return False, None, None
    try:
        manifest_path = _path_containment.resolve_existing(index_root_real / bundle_version / "manifest.json", root=index_root_real)
        manifest_bytes = manifest_path.read_bytes()
    except (_path_containment.PathContainmentError, OSError):
        return False, None, None
    if record.get("bundle_manifest_sha256") != _sha256_bytes(manifest_bytes):
        return False, None, None
    if identity_payload.get("bundle_manifest_sha256") != record.get("bundle_manifest_sha256"):
        return False, None, None
    return True, bundle_version, recomputed_input_digest


def _live_pointer_composite_hash_for_reconciliation(index_root):
    """TARGETED F1/F5.4 REMEDIATION: reuses the facade's own PURE
    `_pointer_composite_hash()` recompute helper (never its decision
    logic) - tolerant of a completely-missing `index/` root (which
    means "no pointer could possibly exist", the ABSENT sentinel, never
    an anomaly). Raises `_facade.RagBundleMutationError` for a genuine
    present-but-unreadable-pointer anomaly, exactly like the facade's
    own helper - callers here treat that as inconclusive (dual-false)."""
    try:
        index_root_real = Path(index_root).resolve(strict=True)
    except OSError:
        return _facade._POINTER_ABSENT_SENTINEL
    return _facade._pointer_composite_hash(index_root_real)


class BuildReconciliationAdapter:
    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if entry.resource_key != _facade.RESOURCE_KEY or entry.action_family != _facade.BUILD_ACTION_FAMILY:
            return _DUAL_FALSE

        # ---- POST-STATE: only attempted if index/ itself resolves -
        # an entirely-absent index/ directory means "definitely nothing
        # was ever published", which is a legitimate NOT-verified
        # post-state (never a containment anomaly) and falls straight
        # through to the pre-state check below, which does NOT depend
        # on index/ existing at all. ----
        index_root_real = _resolve_index_root_real()
        post_state_verified = False
        observed_post_hash = None
        if index_root_real is not None:
            audit_dir = index_root_real / "audit" / "build"
            records, corrupt = _scan_json_records(audit_dir, index_root_real, ".build_audit.json")
            if records is None:
                return _DUAL_FALSE  # root-level containment anomaly on an EXISTING index/ dir
            matches = [
                (path, record) for path, record in records
                if (
                    record.get("mutation_idempotency_key") == entry.idempotency_key
                    and record.get("mutation_resource_key") == entry.resource_key
                    and record.get("action_family") == _facade.BUILD_ACTION_FAMILY
                )
            ]
            # TARGETED F4 REMEDIATION: the old field-equality check
            # (`record.get("input_digest") == entry.pre_revision`) is
            # REPLACED by a full, independent recompute of the audit's
            # OWN five bindings (§4.2) - `recomputed_input_digest ==
            # audit.input_digest == entry.pre_revision` is now a
            # DIRECT, three-way equality, never inferred from field
            # equality alone.
            if corrupt == 0 and len(matches) == 1:
                _path, record = matches[0]
                ok, found_bundle_version, recomputed_input_digest = _build_audit_recompute_ok(index_root_real, record)
                if ok and recomputed_input_digest == entry.pre_revision:
                    post_state_verified = True
                    observed_post_hash = found_bundle_version

        if post_state_verified:
            return mr.ReconciliationEvidence(
                post_state_verified=True, pre_state_confirmed_unchanged=False,
                observed_post_hash=observed_post_hash,
            )

        # ---- PRE-STATE: live source_digest re-derivation, no
        # build_attempt recovery needed (see facade's own
        # _compute_source_digest() docstring for why this is safe) and
        # NO dependency on index/ existing at all (this proof is about
        # data/, not index/). ----
        if entry.pre_hash is not None:
            try:
                ingest = _facade._ingest_module()
                live_source_manifest = ingest.compute_source_manifest()
                live_pipeline_config = ingest.build_pipeline_config()
                live_source_digest = _facade._compute_source_digest(live_source_manifest, live_pipeline_config)
            except Exception:
                return _DUAL_FALSE
            if live_source_digest == entry.pre_hash:
                return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)

        return _DUAL_FALSE


class ActivateReconciliationAdapter:
    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if entry.resource_key != _facade.RESOURCE_KEY or entry.action_family != _facade.ACTIVATE_ACTION_FAMILY:
            return _DUAL_FALSE

        # ---- POST-STATE: only attempted if index/ itself resolves -
        # see BuildReconciliationAdapter's own comment on this. ----
        index_root_real = _resolve_index_root_real()
        post_state_verified = False
        observed_post_hash = None
        if index_root_real is not None:
            audit_dir = _facade._activate_audit_dir(index_root_real)
            records, corrupt = _scan_json_records(audit_dir, index_root_real, ".activate_audit.json")
            if records is None:
                return _DUAL_FALSE
            matches = [
                (path, record) for path, record in records
                if (
                    record.get("mutation_idempotency_key") == entry.idempotency_key
                    and record.get("mutation_resource_key") == entry.resource_key
                    and record.get("action_family") == _facade.ACTIVATE_ACTION_FAMILY
                )
            ]
            # TARGETED F1/F4 REMEDIATION: full independent recompute of
            # the audit's OWN §4.3 bindings, PLUS the pointer's exact
            # `previous_pointer_sha256 == entry.pre_hash` binding, PLUS
            # the build-audit GATE (a valid build audit must still exist
            # for this bundle_version) - none of these existed before.
            if corrupt == 0 and len(matches) == 1:
                _path, record = matches[0]
                ok, found_bundle_version, recomputed_input_digest = _activate_audit_recompute_ok(index_root_real, record)
                if (
                    ok
                    and recomputed_input_digest == entry.pre_revision
                    and record.get("previous_pointer_sha256") == entry.pre_hash
                ):
                    pointer_state, current_version = _facade._read_pointer_state(index_root_real)
                    if (
                        pointer_state == "version"
                        and current_version == found_bundle_version
                        and _bundle_has_verified_build_audit(index_root_real, found_bundle_version)
                    ):
                        post_state_verified = True
                        observed_post_hash = found_bundle_version

        if post_state_verified:
            return mr.ReconciliationEvidence(
                post_state_verified=True, pre_state_confirmed_unchanged=False,
                observed_post_hash=observed_post_hash,
            )

        # ---- PRE-STATE: TARGETED F1/F5.4 REMEDIATION - live pointer
        # COMPOSITE (raw-byte) re-derivation, replacing the old coarse
        # "none"/"corrupt"/version-string comparison (which could not
        # distinguish one corrupt pointer's content from a DIFFERENT
        # corrupt pointer's content - both compared equal as long as
        # entry.pre_hash was also the literal string "corrupt"). Uses
        # the RAW (possibly non-existent) index root - a completely
        # missing `index/` means "no pointer could possibly exist",
        # never an anomaly. ----
        if entry.pre_hash is not None:
            try:
                live_composite = _live_pointer_composite_hash_for_reconciliation(_facade._index_root())
            except _facade.RagBundleMutationError:
                return _DUAL_FALSE
            if live_composite == entry.pre_hash:
                return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)

        return _DUAL_FALSE


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    registry = registry.with_adapter(_facade.BUILD_ACTION_FAMILY, BuildReconciliationAdapter())
    registry = registry.with_adapter(_facade.ACTIVATE_ACTION_FAMILY, ActivateReconciliationAdapter())
    return registry
