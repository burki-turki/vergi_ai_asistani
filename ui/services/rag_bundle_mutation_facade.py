# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION - BUILD/ACTIVATE MUTATION FACADE.
#
# Two action families on ONE global resource (`global:rag_index`):
#   - "rag_bundle.build"    -> publishes a NEW immutable bundle
#     directory `index/v_<64hex>/` (never overwrites an existing one -
#     see BundleVersionCollisionError).
#   - "rag_bundle.activate" -> atomically flips `index/current_version.
#     json` to point at an already-built, already-build-audited bundle.
#
# Reuses the EXISTING mutation coordinator/lock/journal core
# (ui.services.mutation_coordinator.run_mutation, ui.services.
# mutation_lock.acquire_global_lock_session) completely unchanged - this
# is the FIRST facade in this project to key a mutation on a
# `global:*` resource rather than a `case:*` one; `global:rag_index` was
# already seeded by db/migrations/0003_mutation_journal.sql, so no new
# lock-registry row is needed.
#
# INDEPENDENT ERROR HIERARCHY: this module does NOT import or extend
# `ui.services.common`'s `ApprovalUiError`/`ReviewUiError` (this
# Foundation has no web surface and no case-scoped concept at all) -
# every error class below is its own, freestanding hierarchy rooted at
# `RagBundleMutationError`. `ui.services.global_authz.
# GlobalResourceAccessDeniedError` is NOT wrapped - it propagates
# unchanged from `authorize_global_resource_access()`, exactly as
# `ui.services.authz.CaseAccessDeniedError` propagates unwrapped from
# every case-scoped facade.
#
# TWO SEPARATE DIGESTS, NEVER CONFLATED (binding design decision):
#   - `input_digest` (= MutationIntent.pre_hash/pre_revision, and what
#     `--expected-input-digest` confirms): sha256 over ONLY
#     {source_manifest, pipeline_config, build_attempt} - computable
#     BEFORE the expensive chunk/embed/FAISS-build step even runs, so
#     `preview_build()` can show it without ever touching faiss/numpy/
#     network. Re-derived fresh, under the lock, in `precondition_
#     callback` - any drift versus the frozen pre-lock value fails
#     closed with ZERO journal/bundle/staging/audit writes (contract
#     B's own binding "under the global lock: re-hash all source
#     inputs; compare; on drift, fail closed" requirement).
#   - `bundle_version` (= "v_" + sha256(canonical identity-core bytes),
#     contract A): computable ONLY AFTER the real build has produced
#     real `chunk_count`/`embedding_dimension`/artifact hashes - never
#     computed before the writer runs, never part of `input_digest`'s
#     own hashed payload (and `input_digest` is likewise EXCLUDED from
#     the identity-core `bundle_version` is derived from - see contract
#     A's own binding exclusion list). `MutationIntent.pre_hash` is set
#     to the SAME value as `pre_revision` (`input_digest`) - there is no
#     separate "prior artefact being overwritten" concept for a build
#     (each successful build PUBLISHES a brand-new, never-before-seen
#     bundle directory; it does not modify an existing one), so both
#     halves of `validate_intent()`'s both-or-neither pre_hash/
#     pre_revision rule carry the identical "what source state produced
#     this attempt" claim/evidence pair by construction.
#
# OUTSIDE-LOCK BUILD, FROZEN-BYTES WRITER (contract B, mirrors `ui.
# services.generation_mutation_facade`'s own precedent): PDF/chunk/
# embed/FAISS-index construction happens entirely in RAM, OUTSIDE the
# global lock and BEFORE any journal row exists - `src.ingest.
# build_bundle_snapshot()` writes NOTHING to disk. Its returned bytes
# are frozen into `identity_core`/`bundle_version`/`manifest_bytes`
# immediately; the writer_callback uses ONLY those frozen values -
# never re-derives them from a live re-read.
# ============================================================

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import path_containment as _path_containment  # noqa: E402
from mutation_guard import MutationIntent  # noqa: E402

from . import global_authz as _global_authz
from . import mutation_coordinator as _mutation_coordinator
from . import mutation_lock as _mutation_lock

RESOURCE_KEY = "global:rag_index"
CHANNEL = "local_maintenance_rag_bundle_cli"
ACTOR_TYPE = "cli_service"

BUILD_ACTION_FAMILY = "rag_bundle.build"
BUILD_TARGET_REF = "rag_index.bundle"
BUILD_TARGET_STATE = "published"

ACTIVATE_ACTION_FAMILY = "rag_bundle.activate"
# TARGETED F1 REMEDIATION: the activation target_ref is now PARAMETRIZED
# by the target bundle_version (mirrors the generation family's own
# `deadline.<anchor_event_id>.pending` precedent) - "rag_index.current_
# version" ALONE named the RESOURCE, never WHICH bundle was being
# activated, so a legitimate re-activation of a bundle that had already
# been activated once before (activate B -> rollback to A -> activate B
# again) collapsed onto the SAME idempotency_key/fingerprint as the
# first activation and returned a silent, success-shaped replay while
# the pointer stayed unchanged. See ACTIVATE_TARGET_REF_PREFIX below.
ACTIVATE_TARGET_REF_PREFIX = "rag_index.current_version."
ACTIVATE_TARGET_STATE = "active"
ACTIVATION_MANIFEST_VERSION = "ragbundle.activate.manifest.v1"

MANIFEST_VERSION = "rag_bundle_foundation.manifest.v1"
RAG_BUNDLE_ARTIFACT_NAMES = ("mevzuat.faiss", "documents.pkl", "config.json")
_BUNDLE_VERSION_PATTERN = re.compile(r"^v_[0-9a-f]{64}$")
_EXPECTED_CURRENT_VERSION_NONE = "none"
_EXPECTED_CURRENT_VERSION_CORRUPT = "corrupt"

# TARGETED F1/F5.4 REMEDIATION: a fixed sentinel digest standing in for
# "the pointer file does not exist" - so an ABSENT pointer and a
# PRESENT-but-differently-corrupt pointer never collide on the same
# `pre_hash` value (see `_pointer_composite_hash()` below).
_POINTER_ABSENT_SENTINEL = hashlib.sha256(b"RAG_POINTER_ABSENT\n").hexdigest()


class RagBundleMutationError(Exception):
    """Base class for every error this module raises directly (never
    for `ui.services.global_authz.GlobalResourceAccessDeniedError` or a
    `ui.services.mutation_coordinator` exception - both propagate
    unwrapped)."""


class RagBundleArgumentError(RagBundleMutationError):
    """A usage-shape problem, raised strictly before any authz
    repository/DB/filesystem/network access - mirrors every other
    facade's own pre-I/O argument-error class."""


class RagBundleStaleInputError(RagBundleMutationError):
    """`--expected-input-digest` does not match the freshly (pre-lock)
    computed `input_digest` - the build_apply is refused before any
    lock/journal/filesystem write."""


class SourceDriftDetectedError(RagBundleMutationError):
    """Under the global lock, the source inputs (documents.json +
    included PDFs) no longer hash to the SAME `input_digest` the
    pre-lock snapshot was frozen from - refused with ZERO journal/
    bundle/staging/audit writes (raised from `precondition_callback`,
    strictly before `_insert_prepared`)."""


class BundleVersionCollisionError(RagBundleMutationError):
    """A directory `index/v_<bundle_version>/` already exists whose own
    manifest/artifact bytes do NOT byte-for-byte match what this build
    just produced - refused, fail-closed; the pre-existing directory is
    NEVER overwritten."""


class BundleNotFoundError(RagBundleMutationError):
    """`--bundle-version` does not name a real, contained, self-
    consistent (manifest hash matches its own directory name) bundle
    directory under `index/`."""


class BundleNotBuildAuditedError(RagBundleMutationError):
    """The target bundle exists and hash-verifies, but carries no
    valid, fully-bound `rag_bundle.build` audit record - activation is
    refused (contract C: "refused if the target bundle lacks a valid,
    fully-bound build audit")."""


class AlreadyActiveError(RagBundleMutationError):
    """The target `--bundle-version` is already `index/current_version.
    json`'s own current value - activation is refused (contract C's
    own `AlreadyActive` precondition)."""


class StaleCurrentVersionError(RagBundleMutationError):
    """`--expected-current-version` does not match the live pointer's
    freshly (pre-lock) observed state (a real version string, the
    literal `"none"` for an absent pointer, or the literal `"corrupt"`
    for an unparseable one) - activation is refused before any lock/
    journal/pointer write. TARGETED F1 REMEDIATION: also raised when
    the pointer's raw-byte composite hash drifted under the lock even
    though the coarse state string did not (an additional byte-proof
    layer - see `_pointer_composite_hash()` - that does NOT replace the
    state-string check, it adds to it)."""


class BundleManifestDriftError(RagBundleMutationError):
    """TARGETED F2 REMEDIATION addition: under the global lock, the
    target bundle's own `manifest.json` no longer hashes to the SAME
    `bundle_manifest_sha256` the pre-lock snapshot was frozen from -
    refused with ZERO journal/pointer/audit writes (raised from
    `precondition_callback`, strictly before `_insert_prepared`)."""


class BuildReplayVerificationError(RagBundleMutationError):
    """TARGETED F3 REMEDIATION addition: a safe same-key/same-
    fingerprint `rag_bundle.build` replay's own corroboration (the
    published bundle directory fully re-verifies AND exactly one
    uncorrupted, independently recompute-verified build audit is bound
    to this attempt's own identity) failed - the replay is refused
    loudly rather than silently reporting success. NEVER triggers a
    rebuild/writer/network call; the journal row itself stays
    `completed` (this is a read-only corroboration failure, not a new
    mutation attempt) - resolving it is a fail-closed, out-of-band
    operator/reconciliation matter."""


class ActivationReplayVerificationError(RagBundleMutationError):
    """TARGETED F1/F3 REMEDIATION addition: a safe same-key/same-
    fingerprint `rag_bundle.activate` replay's own corroboration (the
    live pointer canonically points at the target bundle, the target
    bundle fully re-verifies, exactly one uncorrupted, independently
    recompute-verified activation audit is bound to this attempt's own
    identity, and that bundle carries a valid build audit) failed - the
    replay is refused loudly rather than silently reporting success.
    NEVER triggers a writer/pointer/audit/network call. The message
    always names the recovery path: re-run `preview_activate()` to see
    the CURRENT state, or - to genuinely re-attempt the exact same
    requested transition - declare a NEW `activation_attempt`."""


@dataclass(frozen=True)
class BuildResult:
    bundle_version: str
    bundle_dir: str
    manifest_path: str
    audit_path: str
    replayed: bool


@dataclass(frozen=True)
class ActivateResult:
    bundle_version: str
    previous_version: str | None
    pointer_path: str
    audit_path: str
    replayed: bool


def _ingest_module():
    import importlib

    return importlib.import_module("ingest")


def _index_root() -> Path:
    return Path(_ingest_module().INDEX_DIR)


def _canonical_json_bytes(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _validate_build_attempt(build_attempt) -> None:
    if not isinstance(build_attempt, int) or isinstance(build_attempt, bool) or build_attempt < 0:
        raise RagBundleArgumentError("build_attempt must be a non-negative integer")


def _validate_activation_attempt(activation_attempt) -> None:
    """TARGETED F1 REMEDIATION: the exact same shape rule as
    `_validate_build_attempt()` above (bool/negative/non-int rejected) -
    a deliberate, byte-for-byte mirror of that function, not a call to
    it, so each stays independently readable/testable."""
    if (
        not isinstance(activation_attempt, int)
        or isinstance(activation_attempt, bool)
        or activation_attempt < 0
    ):
        raise RagBundleArgumentError("activation_attempt must be a non-negative integer")


def _now_iso() -> str:
    """Wall-clock timestamp for audit records ONLY - never part of any
    identity/manifest hash (contract A/E's own binding exclusion)."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _compute_source_digest(source_manifest, pipeline_config) -> str:
    """Deliberately EXCLUDES `build_attempt` - unlike `input_digest`
    below, this is recomputable from LIVE source state alone, with no
    dependency on which attempt number produced a given journal row.
    This is what makes a `rag_bundle.build` reconciliation adapter able
    to prove "the source inputs are unchanged" (MutationIntent.pre_hash)
    WITHOUT ever needing to recover `build_attempt` for an attempt whose
    writer crashed before any audit record was ever written."""
    payload = {
        "kind": "rag_bundle_build_source.v1",
        "source_manifest": source_manifest,
        "pipeline_config": pipeline_config,
    }
    return _sha256_bytes(_canonical_json_bytes(payload))


def _compute_build_input_digest(source_manifest, pipeline_config, build_attempt: int) -> str:
    payload = {
        "kind": "rag_bundle_build_input.v1",
        "source_manifest": source_manifest,
        "pipeline_config": pipeline_config,
        "build_attempt": build_attempt,
    }
    return _sha256_bytes(_canonical_json_bytes(payload))


def _freeze_pre_build_state(build_attempt: int):
    """Pre-lock, read-only: source hashing ONLY - no faiss/numpy/
    network. Returns (source_manifest, pipeline_config, source_digest,
    input_digest)."""
    ingest = _ingest_module()
    source_manifest = ingest.compute_source_manifest()
    pipeline_config = ingest.build_pipeline_config()
    source_digest = _compute_source_digest(source_manifest, pipeline_config)
    input_digest = _compute_build_input_digest(source_manifest, pipeline_config, build_attempt)
    return source_manifest, pipeline_config, source_digest, input_digest


def preview_build(*, build_attempt: int = 0, principal, authz_repository) -> dict:
    _validate_build_attempt(build_attempt)
    _global_authz.authorize_global_resource_access(principal, "build", repository=authz_repository)

    source_manifest, pipeline_config, source_digest, input_digest = _freeze_pre_build_state(build_attempt)

    return {
        "resource_key": RESOURCE_KEY,
        "action_family": BUILD_ACTION_FAMILY,
        "target_ref": BUILD_TARGET_REF,
        "build_attempt": build_attempt,
        "source_document_count": len(source_manifest),
        "input_digest": input_digest,
    }


def _build_identity_core(source_manifest, pipeline_config, build_attempt, chunk_count, embedding_dimension, artifact_hashes):
    return {
        "manifest_version": MANIFEST_VERSION,
        "source_manifest": source_manifest,
        "pipeline_config": pipeline_config,
        "build_attempt": build_attempt,
        "chunk_count": chunk_count,
        "embedding_dimension": embedding_dimension,
        "artifacts": artifact_hashes,
    }


def _bundle_version_for(identity_core: dict) -> str:
    return "v_" + _sha256_bytes(_canonical_json_bytes(identity_core))


def _build_audit_path(index_root: Path, idempotency_key: str) -> Path:
    """TARGETED F4 REMEDIATION: keyed on `idempotency_key` (per-attempt),
    NOT `bundle_version` (which was a SHARED, single audit file two
    different attempts/actors that happen to publish the same bundle
    content could collide on - see the module header's "two-actor"
    scenario). Mirrors the activation side's own naming discipline
    exactly (`_activate_audit_dir()` below), which already got this
    right."""
    return index_root / "audit" / "build" / f"{idempotency_key}.build_audit.json"


def _activate_audit_dir(index_root: Path) -> Path:
    return index_root / "audit" / "activate"


def _manifest_bytes_for(index_root_real: Path, bundle_version: str) -> bytes:
    """Read-only: the EXACT on-disk bytes of `index/<bundle_version>/
    manifest.json`. Callers are expected to have already established
    the bundle's self-consistency (`_verify_bundle_self_consistent`) -
    this helper still resolves containment itself (never trusts an
    unverified path), since the narrow TOCTOU window between those two
    calls is exactly what re-calling this under the lock closes."""
    bundle_dir = _path_containment.resolve_existing(index_root_real / bundle_version, root=index_root_real)
    manifest_path = _path_containment.resolve_existing(bundle_dir / "manifest.json", root=index_root_real)
    return manifest_path.read_bytes()


def _pointer_composite_hash(index_root_real: Path) -> str:
    """TARGETED F1/F5.4 REMEDIATION: `MutationIntent.pre_hash`'s exact
    value for `rag_bundle.activate` - a fixed sentinel when the pointer
    file does not exist, otherwise the sha256 of its EXACT raw bytes
    (valid OR corrupt content alike - this binds the precise bad
    content too, so a corrupt-pointer-content SWAP between two reads is
    detectable, unlike the coarse "none"/"corrupt" STATE string alone).
    A present-but-unreadable/uncontained pointer is a genuine anomaly,
    never silently treated as absent - raises fail-closed; callers in
    the apply path let this propagate (zero writes), callers in the
    reconciliation adapter treat it as inconclusive (dual-false)."""
    pointer_path = index_root_real / "current_version.json"
    if not os.path.lexists(pointer_path):
        return _POINTER_ABSENT_SENTINEL
    try:
        verified = _path_containment.resolve_existing(pointer_path, root=index_root_real)
        raw = verified.read_bytes()
    except (_path_containment.PathContainmentError, OSError) as error:
        raise RagBundleMutationError(
            "current_version.json exists but could not be safely read (containment/OS anomaly) - "
            "refusing fail-closed rather than treating it as absent"
        ) from error
    return _sha256_bytes(raw)


def _activation_identity_payload(
    bundle_version: str, bundle_manifest_sha256: str, expected_current_bundle_version: str, activation_attempt: int,
) -> dict:
    """TARGETED F1 REMEDIATION - contract §2.2's exact five-field shape.
    CLI-declared + immutable-bundle-derived ONLY - never derived from
    the LIVE pointer's raw bytes (that stays `pre_hash`'s job via
    `_pointer_composite_hash()` above); deterministic and reproducible
    from the same inputs, which is exactly what makes a genuine replay
    safe and a legitimate re-activation (a NEW `activation_attempt`)
    reachable."""
    return {
        "manifest_version": ACTIVATION_MANIFEST_VERSION,
        "bundle_version": bundle_version,
        "bundle_manifest_sha256": bundle_manifest_sha256,
        "expected_current_bundle_version": expected_current_bundle_version,
        "activation_attempt": activation_attempt,
    }


def _compute_activation_input_digest(identity_payload: dict) -> str:
    return _sha256_bytes(_canonical_json_bytes(identity_payload))


def _verify_bundle_fully(index_root_real: Path, bundle_version: str) -> Path:
    """TARGETED F3 REMEDIATION addition: full replay-corroboration
    reverify - `_verify_bundle_self_consistent()` PLUS all three fixed
    artifacts' hash/size disk verification (the SAME discipline
    `rag_bundle_mutation_adapters._bundle_dir_self_verifies()`
    independently implements - a bug in one must never mask a bug in
    the other, so this is NOT a shared call, it is a second,
    independent implementation living in this module)."""
    bundle_dir = _verify_bundle_self_consistent(index_root_real, bundle_version)
    manifest_path = _path_containment.resolve_existing(bundle_dir / "manifest.json", root=index_root_real)
    try:
        manifest = json.loads(manifest_path.read_bytes().decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as error:
        raise BundleNotFoundError(f"index/{bundle_version}/manifest.json is unreadable on full reverify") from error
    artifacts_table = manifest.get("artifacts")
    if not isinstance(artifacts_table, dict) or set(artifacts_table.keys()) != set(RAG_BUNDLE_ARTIFACT_NAMES):
        raise BundleNotFoundError(f"index/{bundle_version}/manifest.json artifacts table is malformed")
    for name in RAG_BUNDLE_ARTIFACT_NAMES:
        entry_info = artifacts_table.get(name)
        try:
            artifact_real = _path_containment.resolve_existing(bundle_dir / name, root=index_root_real)
            raw = artifact_real.read_bytes()
        except (_path_containment.PathContainmentError, OSError) as error:
            raise BundleNotFoundError(f"index/{bundle_version}/{name} is missing/unreadable on full reverify") from error
        if not isinstance(entry_info, dict) or _sha256_bytes(raw) != entry_info.get("sha256") or len(raw) != entry_info.get("size_bytes"):
            raise BundleNotFoundError(f"index/{bundle_version}/{name} failed hash/size reverification")
    return bundle_dir


def _scan_audit_dir(directory: Path, index_root_real: Path, suffix: str):
    """Facade-LOCAL containment-before-parse scan (an INDEPENDENT
    implementation of the same discipline `rag_bundle_mutation_
    adapters._scan_json_records()` uses - never shared/imported, per
    this module's own "a bug in one must never mask a bug in the other"
    convention). Returns (records, corrupt_count); a containment
    failure on `directory` itself returns (None, None) (a root-level
    anomaly, distinct from an ordinary empty/absent directory)."""
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
            data = json.loads(resolved.read_bytes().decode("utf-8"))
        except (_path_containment.PathContainmentError, OSError, ValueError, UnicodeDecodeError):
            corrupt += 1
            continue
        if not isinstance(data, dict):
            corrupt += 1
            continue
        records.append((resolved, data))
    return records, corrupt


def _build_audit_content_ok(index_root_real: Path, record: dict):
    """TARGETED F4 REMEDIATION - contract §4.2's five recompute
    bindings, checked WITHOUT reference to any specific journal entry
    (callers that need entry-binding additionally compare the returned
    `recomputed_input_digest` to `entry.pre_revision` themselves).
    Returns (ok, bundle_version_or_None, recomputed_input_digest_or_None)."""
    identity_payload = record.get("identity_payload")
    if not isinstance(identity_payload, dict):
        return False, None, None
    source_manifest = identity_payload.get("source_manifest")
    pipeline_config = identity_payload.get("pipeline_config")
    build_attempt = identity_payload.get("build_attempt")
    if not isinstance(build_attempt, int) or isinstance(build_attempt, bool):
        return False, None, None
    try:
        recomputed_input_digest = _compute_build_input_digest(source_manifest, pipeline_config, build_attempt)
    except (TypeError, ValueError):
        return False, None, None
    if recomputed_input_digest != record.get("input_digest"):
        return False, None, None
    bundle_version = record.get("bundle_version")
    if not isinstance(bundle_version, str) or not _BUNDLE_VERSION_PATTERN.match(bundle_version):
        return False, None, None
    try:
        bundle_dir = _verify_bundle_fully(index_root_real, bundle_version)
    except RagBundleMutationError:
        return False, None, None
    try:
        manifest_path = _path_containment.resolve_existing(bundle_dir / "manifest.json", root=index_root_real)
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (_path_containment.PathContainmentError, OSError, ValueError, UnicodeDecodeError):
        return False, None, None
    if record.get("manifest_sha256") != _sha256_bytes(manifest_bytes):
        return False, None, None
    identity_core = {key: value for key, value in manifest.items() if key != "bundle_version"}
    if _bundle_version_for(identity_core) != bundle_version:
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
    """TARGETED F4 REMEDIATION: replaces the old `_find_build_audit()` -
    scans the WHOLE build-audit directory (audits are now keyed by
    idempotency_key, not bundle_version, since more than one PER-ACTOR
    audit may legitimately exist for the same published bundle content -
    see the module header's "two-actor" scenario) and requires AT LEAST
    ONE fully recompute-verified audit for `bundle_version`, with ZERO
    corrupt entries anywhere in the directory (fail-closed - a single
    corrupt/tampered neighbor audit blocks activation of every bundle,
    a deliberate, accepted cost matching this project's established
    Layer B "aile-genelinde bozuk aday" precedent)."""
    audit_dir = index_root_real / "audit" / "build"
    records, corrupt = _scan_audit_dir(audit_dir, index_root_real, ".build_audit.json")
    if records is None or corrupt != 0:
        return False
    for _path, record in records:
        if record.get("bundle_version") != bundle_version:
            continue
        if record.get("action_family") != BUILD_ACTION_FAMILY or record.get("resource_key") != RESOURCE_KEY:
            continue
        ok, found_bundle_version, _digest = _build_audit_content_ok(index_root_real, record)
        if ok and found_bundle_version == bundle_version:
            return True
    return False


def _activate_audit_content_ok(index_root_real: Path, record: dict):
    """TARGETED F4 REMEDIATION - contract §4.3's recompute bindings,
    checked WITHOUT reference to any specific journal entry (callers
    needing entry-binding additionally compare `recomputed_input_digest`
    to `entry.pre_revision`, and `record["previous_pointer_sha256"]` to
    `entry.pre_hash`, themselves). Returns (ok, bundle_version_or_None,
    recomputed_input_digest_or_None)."""
    identity_payload = record.get("identity_payload")
    if not isinstance(identity_payload, dict):
        return False, None, None
    try:
        recomputed_input_digest = _compute_activation_input_digest(identity_payload)
    except (TypeError, ValueError):
        return False, None, None
    if recomputed_input_digest != record.get("input_digest"):
        return False, None, None
    bundle_version = identity_payload.get("bundle_version")
    if not isinstance(bundle_version, str) or not _BUNDLE_VERSION_PATTERN.match(bundle_version):
        return False, None, None
    if record.get("bundle_version") != bundle_version:
        return False, None, None
    if record.get("target_ref") != f"{ACTIVATE_TARGET_REF_PREFIX}{bundle_version}":
        return False, None, None
    try:
        bundle_dir = _verify_bundle_fully(index_root_real, bundle_version)
    except RagBundleMutationError:
        return False, None, None
    try:
        manifest_path = _path_containment.resolve_existing(bundle_dir / "manifest.json", root=index_root_real)
        manifest_bytes = manifest_path.read_bytes()
    except (_path_containment.PathContainmentError, OSError):
        return False, None, None
    if record.get("bundle_manifest_sha256") != _sha256_bytes(manifest_bytes):
        return False, None, None
    if identity_payload.get("bundle_manifest_sha256") != record.get("bundle_manifest_sha256"):
        return False, None, None
    return True, bundle_version, recomputed_input_digest


def apply_build(
    expected_input_digest: str,
    *,
    allow_network: bool,
    build_attempt: int = 0,
    principal,
    authz_repository,
    conn_factory=None,
    snapshot_builder=None,
    embedding_client=None,
) -> BuildResult:
    _validate_build_attempt(build_attempt)
    if not isinstance(expected_input_digest, str) or not expected_input_digest:
        raise RagBundleArgumentError("expected_input_digest must be a non-empty string")
    if not allow_network:
        raise RagBundleArgumentError(
            "apply_build() requires allow_network=True unconditionally - there is no relaxed mode"
        )

    # Outer (pre-lock) authz - fail-fast, zero connection/lock/journal
    # access for a denied caller.
    _global_authz.authorize_global_resource_access(principal, "build", repository=authz_repository)

    source_manifest, pipeline_config, source_digest, input_digest = _freeze_pre_build_state(build_attempt)
    if input_digest != expected_input_digest:
        raise RagBundleStaleInputError(
            "expected_input_digest does not match the freshly computed input_digest - "
            "re-run preview_build() and retry with the new value"
        )

    intent = MutationIntent(
        actor_type=ACTOR_TYPE,
        actor_ref=str(getattr(principal, "user_id", "")) or "unknown",
        resource_key=RESOURCE_KEY,
        action_family=BUILD_ACTION_FAMILY,
        target_ref=BUILD_TARGET_REF,
        target_state=BUILD_TARGET_STATE,
        pre_hash=source_digest,
        pre_revision=input_digest,
    )

    conn_factory = _default_mutation_conn_factory if conn_factory is None else conn_factory

    # ---- BUILD-SKIP FAST PATH (Row 19A-compatible: NEVER authoritative
    # - purely an optimization to skip the expensive builder call ahead
    # of a KNOWN-safe replay; run_mutation()'s own kilit-altı idempotency
    # lookup is, unconditionally, the ONLY authoritative decision). A
    # pre-lock, best-effort peek at whether this exact idempotency_key
    # already has a `completed` row - if so, the builder is skipped
    # entirely and writer_callback becomes an unreachable, fail-closed
    # sentinel (defense in depth: if the peek was stale/wrong, run_
    # mutation() itself will simply proceed normally - the sentinel is
    # only ever reached if the coordinator's OWN authoritative check
    # somehow still invoked the writer after a skip, which would be a
    # genuine invariant violation). ----
    build_skipped = False
    try:
        idempotency_key_for_peek = _idempotency_key_of(intent)
        peek_conn = conn_factory()
        try:
            with peek_conn.cursor() as cur:
                # SAME SQL SHAPE ui.services.mutation_coordinator._idempotency_lookup()
                # itself issues (id, state, request_fingerprint, observed_post_hash,
                # failure_code, resolution_code) - a deliberate match, not a new query
                # shape, so this peek is exercised by the exact same fake-conn fixtures.
                cur.execute(
                    "SELECT id, state, request_fingerprint, observed_post_hash, failure_code, resolution_code "
                    "FROM mutation.mutation_journal WHERE idempotency_key = %s",
                    (idempotency_key_for_peek,),
                )
                row = cur.fetchone()
            build_skipped = row is not None and row[1] == "completed"
        finally:
            try:
                peek_conn.close()
            except Exception:
                pass
    except Exception:
        build_skipped = False

    ingest = _ingest_module()
    builder = ingest.build_bundle_snapshot if snapshot_builder is None else snapshot_builder

    if build_skipped:
        frozen_artifacts = None
        frozen_manifest_bytes = None
        bundle_version = None
    else:
        # ---- OUTSIDE THE LOCK, BEFORE any journal row: the real,
        # expensive full rebuild (PDF parse -> chunk -> embed -> FAISS),
        # entirely in RAM. Writes nothing under index/**. ----
        snapshot = builder(
            embedding_client=embedding_client, pdf_page_extractor=None, build_attempt=build_attempt,
        )

        artifacts = snapshot["artifacts"]
        if set(artifacts.keys()) != set(RAG_BUNDLE_ARTIFACT_NAMES):
            raise RagBundleMutationError(
                "snapshot_builder() did not return exactly the three fixed artifact names"
            )
        artifact_hashes = {
            name: {"sha256": _sha256_bytes(raw), "size_bytes": len(raw)}
            for name, raw in artifacts.items()
        }
        identity_core = _build_identity_core(
            snapshot["source_manifest"], snapshot["pipeline_config"], snapshot["build_attempt"],
            snapshot["chunk_count"], snapshot["embedding_dimension"], artifact_hashes,
        )
        bundle_version = _bundle_version_for(identity_core)
        manifest = dict(identity_core)
        manifest["bundle_version"] = bundle_version
        manifest_bytes = _canonical_json_bytes(manifest)

        # FROZEN now - the writer below uses ONLY these bytes, never a
        # live re-derivation.
        frozen_artifacts = dict(artifacts)
        frozen_manifest_bytes = manifest_bytes

    under_lock_box = {}

    def _authz_callback():
        # Inner, under-lock, AUTHORITATIVE re-check - a fresh repository
        # bound to the SAME lock-holding connection the caller supplies
        # via conn_factory below (see apply_build()'s own conn usage).
        _global_authz.authorize_global_resource_access(
            principal, "build", repository=under_lock_box["repository"],
        )

    def _precondition_callback():
        _fsm, _fpc, _fsd, fresh_input_digest = _freeze_pre_build_state(build_attempt)
        if fresh_input_digest != input_digest:
            raise SourceDriftDetectedError(
                "source inputs changed between the pre-lock snapshot and lock acquisition - "
                "zero bundle/staging/audit writes were made; retry"
            )

    def _writer_callback() -> _mutation_coordinator.WriterResult:
        if build_skipped:
            # UNREACHABLE under normal operation - the fast-path peek
            # found a `completed` row for this exact idempotency_key,
            # so run_mutation()'s own authoritative idempotency lookup
            # MUST have short-circuited to a safe replay before ever
            # invoking this callback. Reaching this line means that
            # peek was WRONG (a genuine invariant violation, e.g. the
            # row was reconciled away between the peek and the lock) -
            # fail closed rather than publish from frozen=None state.
            raise RagBundleMutationError(
                "invariant violation: writer_callback invoked after a build-skip fast-path hit - "
                "the coordinator's own authoritative idempotency lookup should have replayed instead"
            )

        index_root = _index_root()
        index_root.mkdir(parents=True, exist_ok=True)
        index_root_real = Path(index_root).resolve(strict=True)

        staging_name = f"b_{intent_idempotency_prefix()}"
        staging_dir = _path_containment.resolve_for_create(index_root_real, "staging", staging_name)
        staging_dir.mkdir(parents=True, exist_ok=True)

        first_publish = True
        try:
            for name in RAG_BUNDLE_ARTIFACT_NAMES:
                artifact_path = staging_dir / name
                _write_bytes_fsync(artifact_path, frozen_artifacts[name])
            manifest_path_staging = staging_dir / "manifest.json"
            _write_bytes_fsync(manifest_path_staging, frozen_manifest_bytes)

            # Re-verify by re-reading, strictly before publishing.
            for name in RAG_BUNDLE_ARTIFACT_NAMES:
                reread = (staging_dir / name).read_bytes()
                if reread != frozen_artifacts[name]:
                    raise RagBundleMutationError(f"staged artifact '{name}' failed re-read verification")
            if (staging_dir / "manifest.json").read_bytes() != frozen_manifest_bytes:
                raise RagBundleMutationError("staged manifest.json failed re-read verification")

            target_dir = index_root_real / bundle_version
            if os.path.lexists(target_dir):
                collision = _check_existing_bundle_matches(target_dir, index_root_real, frozen_manifest_bytes, frozen_artifacts)
                if not collision:
                    raise BundleVersionCollisionError(
                        f"index/{bundle_version}/ already exists with DIFFERENT manifest/artifact bytes"
                    )
                # Deterministic, identical-bytes republish: this exact
                # content was already published (by this or another
                # actor/attempt - TARGETED F4 REMEDIATION's "two-actor"
                # scenario) - `first_publish=False`, but THIS attempt
                # still writes its OWN per-idempotency-key audit below.
                first_publish = False
            else:
                os.replace(str(staging_dir), str(target_dir))
        finally:
            # Orphan staging directories are deliberately INERT in this
            # slice (contract B: "no delete/cleanup/GC surface of any
            # kind may be added") - a leftover `index/staging/b_.../`
            # after a collision or a failure below is accepted, disclosed
            # residue, never auto-removed here.
            pass

        # ---- TARGETED F4 REMEDIATION: per-idempotency-key, O_CREAT|
        # O_EXCL audit (never bundle_version-keyed, never a silent
        # "if not exists: skip") - every journal row that reaches this
        # point writes its OWN audit; a pre-existing file at this exact
        # path can only mean tamper/manual residue (the journal-gate/
        # PriorAttemptFailedError/replay-shortcircuit already make a
        # SECOND legitimate writer entry for the SAME idempotency_key
        # structurally impossible), so it is refused fail-closed rather
        # than accepted content-blind. ----
        idempotency_key = _idempotency_key_of(intent)
        audit_dir = index_root_real / "audit" / "build"
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_record = {
            "schema_version": 1,
            "action_family": BUILD_ACTION_FAMILY,
            "channel": CHANNEL,
            "resource_key": RESOURCE_KEY,
            "target_ref": BUILD_TARGET_REF,
            "target_state": BUILD_TARGET_STATE,
            "mutation_idempotency_key": idempotency_key,
            "mutation_resource_key": RESOURCE_KEY,
            "mutation_actor_ref": intent.actor_ref,
            "input_digest": input_digest,
            "identity_payload": {
                "kind": "rag_bundle_build_input.v1",
                "source_manifest": snapshot["source_manifest"],
                "pipeline_config": snapshot["pipeline_config"],
                "build_attempt": snapshot["build_attempt"],
            },
            "build_attempt": build_attempt,
            "bundle_version": bundle_version,
            "manifest_sha256": _sha256_bytes(frozen_manifest_bytes),
            "artifact_hashes": artifact_hashes,
            "staging_dir_name": staging_name,
            "first_publish": first_publish,
            "validation": {
                "artifacts_reverified": True,
                "manifest_reverified": True,
                "chunk_count": snapshot["chunk_count"],
                "embedding_dimension": snapshot["embedding_dimension"],
            },
            "generated_at": _now_iso(),
            "outcome": "published",
        }
        audit_bytes = _canonical_json_bytes(audit_record)
        audit_path = _build_audit_path(index_root_real, idempotency_key)
        try:
            fd = os.open(str(audit_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError as error:
            # Includes FileExistsError (a subclass of OSError) - the
            # `pass`-and-continue behavior this used to have is GONE
            # (F5.7 closure): the writer boundary was already crossed,
            # so this attempt becomes `reconciliation_required` rather
            # than silently reporting success over an unverified/
            # pre-existing file.
            raise RagBundleMutationError(
                f"failed to create the build audit file at {audit_path} (fail-closed)"
            ) from error
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(audit_bytes)
                file.flush()
                os.fsync(file.fileno())
        except Exception:
            try:
                audit_path.unlink()
            except OSError:
                import logging

                logging.getLogger("vergi_ai.rag_bundle_mutation_facade").critical(
                    f"partial build audit unlink FAILED for {audit_path} - a corrupt/partial audit "
                    "file may remain on disk; a future reconciliation/replay scan will treat this "
                    "directory as containing a corrupt entry until it is manually removed", exc_info=True,
                )
            raise

        return _mutation_coordinator.WriterResult(
            observed_post_hash=bundle_version,
            result=BuildResult(
                bundle_version=bundle_version,
                bundle_dir=str(index_root_real / bundle_version),
                manifest_path=str(index_root_real / bundle_version / "manifest.json"),
                audit_path=str(audit_path),
                replayed=False,
            ),
        )

    def intent_idempotency_prefix() -> str:
        return _idempotency_key_of(intent)[:24]

    conn_factory = _default_mutation_conn_factory if conn_factory is None else conn_factory
    conn = conn_factory()
    lock_held = False
    advisory_lock_id = None
    try:
        advisory_lock_id = _mutation_lock.acquire_global_lock_session(conn, RESOURCE_KEY)
        lock_held = True
        under_lock_box["repository"] = _global_authz.PostgresGlobalResourceAuthzRepository(conn)

        outcome = _mutation_coordinator.run_mutation(
            conn, intent,
            actor_user_id=getattr(principal, "user_id", None),
            authz_callback=_authz_callback,
            precondition_callback=_precondition_callback,
            writer_callback=_writer_callback,
        )
    finally:
        if lock_held:
            try:
                released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
                if not released:
                    import logging

                    logging.getLogger("vergi_ai.rag_bundle_mutation_facade").critical(
                        f"release_lock_session returned False for resource_key={RESOURCE_KEY!r}"
                    )
            except Exception:
                import logging

                logging.getLogger("vergi_ai.rag_bundle_mutation_facade").critical(
                    f"release_lock_session raised for resource_key={RESOURCE_KEY!r}", exc_info=True,
                )
        try:
            conn.close()
        except Exception:
            pass

    if outcome.replayed:
        return _verify_completed_build_replay(outcome, intent=intent, input_digest=input_digest)
    return outcome.result


def _idempotency_key_of(intent: MutationIntent) -> str:
    from mutation_guard import compute_idempotency_key

    return compute_idempotency_key(intent)


def _write_bytes_fsync(path: Path, raw: bytes) -> None:
    with open(path, "wb") as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())


def _check_existing_bundle_matches(target_dir: Path, index_root_real: Path, expected_manifest_bytes: bytes, expected_artifacts: dict) -> bool:
    try:
        verified_dir = _path_containment.resolve_existing(target_dir, root=index_root_real)
    except _path_containment.PathContainmentError:
        return False
    manifest_path = verified_dir / "manifest.json"
    try:
        existing_manifest = manifest_path.read_bytes()
    except OSError:
        return False
    if existing_manifest != expected_manifest_bytes:
        return False
    for name, raw in expected_artifacts.items():
        try:
            existing = (verified_dir / name).read_bytes()
        except OSError:
            return False
        if existing != raw:
            return False
    return True


def _verify_completed_build_replay(outcome, *, intent: MutationIntent, input_digest: str) -> BuildResult:
    """TARGETED F3 REMEDIATION - full replay corroboration (this
    docstring previously overclaimed a hash-self-verify this function's
    OLD body never actually performed; the claim below is now true of
    the CODE, not just the comment). A safe same-key/same-fingerprint
    replay NEVER re-invokes the writer/builder/network - this function
    reconstructs a `BuildResult` ONLY after independently proving:
    (1) `index/<observed_post_hash>/` fully reverifies (containment,
    manifest self-consistency, all three artifacts' hash/size);
    (2) exactly one uncorrupted build audit is bound to THIS intent's
    own idempotency identity (`mutation_idempotency_key`/
    `mutation_resource_key`/`action_family`), with zero corrupt entries
    anywhere in the build-audit directory; (3) that ONE audit's own
    `recomputed_input_digest == audit.input_digest == input_digest`
    (== `entry.pre_revision`, since `intent.pre_revision is input_
    digest` by construction) and its `bundle_version` matches
    `observed_post_hash`. ANY failure raises `BuildReplayVerificationError`
    loudly - never a silent success, never a rebuild."""
    observed_bundle_version = outcome.observed_post_hash
    if not isinstance(observed_bundle_version, str) or not _BUNDLE_VERSION_PATTERN.match(observed_bundle_version):
        raise BuildReplayVerificationError(
            f"observed_post_hash {observed_bundle_version!r} is not a well-shaped bundle_version - "
            "this replay cannot be corroborated"
        )
    index_root_real = Path(_index_root()).resolve(strict=True)
    try:
        _verify_bundle_fully(index_root_real, observed_bundle_version)
    except RagBundleMutationError as error:
        raise BuildReplayVerificationError(
            f"index/{observed_bundle_version}/ failed full reverification on replay"
        ) from error

    audit_dir = index_root_real / "audit" / "build"
    records, corrupt = _scan_audit_dir(audit_dir, index_root_real, ".build_audit.json")
    if records is None:
        raise BuildReplayVerificationError("the build-audit directory has a containment anomaly")
    idempotency_key = _idempotency_key_of(intent)
    matches = [
        (path, record) for path, record in records
        if (
            record.get("mutation_idempotency_key") == idempotency_key
            and record.get("mutation_resource_key") == RESOURCE_KEY
            and record.get("action_family") == BUILD_ACTION_FAMILY
        )
    ]
    if corrupt != 0 or len(matches) != 1:
        raise BuildReplayVerificationError(
            "expected exactly one uncorrupted build audit bound to this attempt's own idempotency "
            f"identity; found {len(matches)} matching (corrupt={corrupt})"
        )
    audit_path, record = matches[0]
    if record.get("bundle_version") != observed_bundle_version:
        raise BuildReplayVerificationError("the bound build audit's bundle_version does not match observed_post_hash")
    ok, found_bundle_version, recomputed_input_digest = _build_audit_content_ok(index_root_real, record)
    if not ok or found_bundle_version != observed_bundle_version or recomputed_input_digest != input_digest:
        raise BuildReplayVerificationError("the bound build audit failed independent recompute verification")

    verified_dir = _path_containment.resolve_existing(index_root_real / observed_bundle_version, root=index_root_real)
    return BuildResult(
        bundle_version=observed_bundle_version,
        bundle_dir=str(verified_dir),
        manifest_path=str(verified_dir / "manifest.json"),
        audit_path=str(audit_path),
        replayed=True,
    )


def _default_mutation_conn_factory():
    from . import db as _db

    return _db.get_session_lock_connection()


# ============================================================
# ACTIVATE
# ============================================================

def _read_pointer_state(index_root: Path):
    """Returns ("none", None) | ("corrupt", None) | ("version", "v_...")
    - read-only, containment-safe, never raises for a missing/corrupt
    pointer (that is a normal, expected observed state here, not a
    caller bug)."""
    pointer_path = index_root / "current_version.json"
    try:
        index_root_real = Path(index_root).resolve(strict=True)
    except OSError:
        return "none", None
    try:
        verified = _path_containment.resolve_existing(pointer_path, root=index_root_real)
    except _path_containment.PathContainmentError:
        return "none", None
    try:
        with open(verified, "r", encoding="utf-8") as file:
            data = json.load(file)
        current = data.get("current_version") if isinstance(data, dict) else None
        if not isinstance(current, str) or not _BUNDLE_VERSION_PATTERN.match(current):
            return "corrupt", None
        return "version", current
    except (OSError, ValueError):
        return "corrupt", None


def _verify_bundle_self_consistent(index_root_real: Path, bundle_version: str) -> Path:
    if not _BUNDLE_VERSION_PATTERN.match(bundle_version):
        raise RagBundleArgumentError("bundle_version must match ^v_[0-9a-f]{64}$")
    try:
        bundle_dir = _path_containment.resolve_existing(index_root_real / bundle_version, root=index_root_real)
    except _path_containment.PathContainmentError as error:
        raise BundleNotFoundError(f"index/{bundle_version}/ does not exist or is not contained") from error
    if bundle_dir.name != bundle_version or not bundle_dir.is_dir():
        raise BundleNotFoundError(f"index/{bundle_version}/ has an unexpected name/type")
    try:
        manifest_path = _path_containment.resolve_existing(bundle_dir / "manifest.json", root=index_root_real)
        with open(manifest_path, "r", encoding="utf-8") as file:
            manifest = json.load(file)
    except (_path_containment.PathContainmentError, OSError, ValueError) as error:
        raise BundleNotFoundError(f"index/{bundle_version}/manifest.json is missing/unreadable") from error
    if not isinstance(manifest, dict) or manifest.get("bundle_version") != bundle_version:
        raise BundleNotFoundError(f"index/{bundle_version}/manifest.json bundle_version mismatch")
    identity_core = {key: value for key, value in manifest.items() if key != "bundle_version"}
    if _bundle_version_for(identity_core) != bundle_version:
        raise BundleNotFoundError(f"index/{bundle_version}/manifest.json is not self-consistent")
    return bundle_dir


def preview_activate(bundle_version: str, *, activation_attempt: int = 0, principal, authz_repository) -> dict:
    _validate_activation_attempt(activation_attempt)
    _global_authz.authorize_global_resource_access(principal, "activate", repository=authz_repository)

    index_root_real = Path(_index_root())
    index_root_real.mkdir(parents=True, exist_ok=True)
    index_root_real = index_root_real.resolve(strict=True)

    _verify_bundle_self_consistent(index_root_real, bundle_version)
    bundle_manifest_sha256 = _sha256_bytes(_manifest_bytes_for(index_root_real, bundle_version))
    has_audit = _bundle_has_verified_build_audit(index_root_real, bundle_version)
    pointer_state, current_version = _read_pointer_state(index_root_real)
    observed = current_version if pointer_state == "version" else pointer_state

    # TARGETED F1 REMEDIATION: the digest shown here ASSUMES the
    # observed pointer state as `expected_current_bundle_version` - the
    # assumption is surfaced explicitly (never hidden) since the
    # operator's real `--apply` call may supply a DIFFERENT value.
    identity_payload = _activation_identity_payload(
        bundle_version, bundle_manifest_sha256, observed, activation_attempt,
    )
    activation_input_digest = _compute_activation_input_digest(identity_payload)

    return {
        "resource_key": RESOURCE_KEY,
        "action_family": ACTIVATE_ACTION_FAMILY,
        "target_ref": f"{ACTIVATE_TARGET_REF_PREFIX}{bundle_version}",
        "bundle_version": bundle_version,
        "bundle_manifest_sha256": bundle_manifest_sha256,
        "activation_attempt": activation_attempt,
        "has_build_audit": has_audit,
        "current_pointer_state": pointer_state,
        "current_version": current_version,
        "expected_current_bundle_version_assumption": observed,
        "activation_input_digest": activation_input_digest,
    }


def apply_activate(
    bundle_version: str,
    expected_current_version: str,
    *,
    activation_attempt: int = 0,
    principal,
    authz_repository,
    conn_factory=None,
) -> ActivateResult:
    _validate_activation_attempt(activation_attempt)
    if not isinstance(expected_current_version, str) or not expected_current_version:
        raise RagBundleArgumentError("expected_current_version must be a non-empty string")

    _global_authz.authorize_global_resource_access(principal, "activate", repository=authz_repository)

    index_root_real = Path(_index_root())
    index_root_real.mkdir(parents=True, exist_ok=True)
    index_root_real = index_root_real.resolve(strict=True)

    _verify_bundle_self_consistent(index_root_real, bundle_version)
    bundle_manifest_sha256 = _sha256_bytes(_manifest_bytes_for(index_root_real, bundle_version))
    if not _bundle_has_verified_build_audit(index_root_real, bundle_version):
        raise BundleNotBuildAuditedError(
            f"index/{bundle_version}/ has no valid, fully-bound rag_bundle.build audit - refusing to activate"
        )

    pointer_state, current_version = _read_pointer_state(index_root_real)
    observed = current_version if pointer_state == "version" else pointer_state
    if observed != expected_current_version:
        raise StaleCurrentVersionError(
            f"expected_current_version={expected_current_version!r} does not match the observed "
            f"pointer state {observed!r}"
        )
    if pointer_state == "version" and current_version == bundle_version:
        raise AlreadyActiveError(f"index/current_version.json already points at {bundle_version}")

    # TARGETED F1/F5.4 REMEDIATION: the raw-byte composite hash of the
    # LIVE pointer - `MutationIntent.pre_hash`'s exact value (never the
    # coarse "none"/"corrupt" state string alone).
    pointer_composite_hash = _pointer_composite_hash(index_root_real)

    identity_payload = _activation_identity_payload(
        bundle_version, bundle_manifest_sha256, expected_current_version, activation_attempt,
    )
    activation_input_digest = _compute_activation_input_digest(identity_payload)
    target_ref = f"{ACTIVATE_TARGET_REF_PREFIX}{bundle_version}"

    intent = MutationIntent(
        actor_type=ACTOR_TYPE,
        actor_ref=str(getattr(principal, "user_id", "")) or "unknown",
        resource_key=RESOURCE_KEY,
        action_family=ACTIVATE_ACTION_FAMILY,
        target_ref=target_ref,
        target_state=ACTIVATE_TARGET_STATE,
        pre_hash=pointer_composite_hash,
        pre_revision=activation_input_digest,
    )

    under_lock_box = {}

    def _authz_callback():
        _global_authz.authorize_global_resource_access(
            principal, "activate", repository=under_lock_box["repository"],
        )

    def _precondition_callback():
        _verify_bundle_self_consistent(index_root_real, bundle_version)
        # TARGETED F2 REMEDIATION addition: the target bundle's own
        # manifest content must not have drifted under the lock - a
        # SEPARATE, explicit byte-proof layer on top of self-
        # consistency (self-consistency alone only proves the bundle
        # NOW at this directory is internally coherent, never that it
        # is still the SAME bundle the pre-lock snapshot saw).
        fresh_manifest_bytes = _manifest_bytes_for(index_root_real, bundle_version)
        if _sha256_bytes(fresh_manifest_bytes) != bundle_manifest_sha256:
            raise BundleManifestDriftError(
                f"index/{bundle_version}/manifest.json changed between the pre-lock snapshot and "
                "lock acquisition - zero pointer/audit writes were made; re-run preview_activate()"
            )
        if not _bundle_has_verified_build_audit(index_root_real, bundle_version):
            raise BundleNotBuildAuditedError(
                f"index/{bundle_version}/ lost its build audit between preview and lock acquisition"
            )
        fresh_state, fresh_current = _read_pointer_state(index_root_real)
        fresh_observed = fresh_current if fresh_state == "version" else fresh_state
        if fresh_observed != expected_current_version:
            raise StaleCurrentVersionError(
                "pointer changed between the pre-lock check and lock acquisition - zero writes were made"
            )
        if fresh_state == "version" and fresh_current == bundle_version:
            raise AlreadyActiveError(f"index/current_version.json already points at {bundle_version}")
        # TARGETED F1/F5.4 REMEDIATION addition: the composite (raw-
        # byte) check does NOT replace the state-string check above -
        # it adds a byte-proof layer that also catches a corrupt-
        # content SWAP the coarse "corrupt"-vs-"corrupt" state string
        # alone could never distinguish.
        if _pointer_composite_hash(index_root_real) != pointer_composite_hash:
            raise StaleCurrentVersionError(
                "pointer content changed between the pre-lock check and lock acquisition (composite "
                "hash mismatch) - zero writes were made"
            )

    def _writer_callback() -> _mutation_coordinator.WriterResult:
        pointer_path = index_root_real / "current_version.json"

        # ---- W0 (TARGETED F2 REMEDIATION): previous-pointer read is
        # fail-closed - a present-but-UNREADABLE pointer must never be
        # silently treated as "absent" (that would make a later
        # rollback DELETE a pointer that was genuinely there before
        # this attempt started). ----
        if not os.path.lexists(pointer_path):
            previous_existed = False
            previous_bytes = None
        else:
            previous_existed = True
            try:
                verified_previous = _path_containment.resolve_existing(pointer_path, root=index_root_real)
                previous_bytes = verified_previous.read_bytes()
            except (_path_containment.PathContainmentError, OSError) as error:
                raise RagBundleMutationError(
                    "current_version.json exists but could not be read before activation - refusing "
                    "fail-closed (W0) rather than risk a later rollback silently deleting it"
                ) from error

        def _rollback_pointer():
            """W5 (TARGETED F2 REMEDIATION): rollback failure is now
            CRITICAL-logged (never a silent `except OSError: pass`) -
            mirrors this module's own `release_lock_session` logging
            pattern. A failed rollback leaves the pointer in the NEW
            state with no corroborated audit - a genuine dual-false
            corner the caller's own exception propagation (never
            swallowed here) still surfaces via reconciliation_required."""
            try:
                if not previous_existed:
                    if os.path.lexists(pointer_path):
                        os.remove(str(pointer_path))
                else:
                    rollback_temp = index_root_real / "current_version.json.rollback.tmp"
                    with open(rollback_temp, "wb") as file:
                        file.write(previous_bytes)
                        file.flush()
                        os.fsync(file.fileno())
                    os.replace(str(rollback_temp), str(pointer_path))
            except OSError:
                import logging

                logging.getLogger("vergi_ai.rag_bundle_mutation_facade").critical(
                    f"activation pointer ROLLBACK FAILED for resource_key={RESOURCE_KEY!r} - the "
                    "pointer may be left in the NEW state with no corroborated audit; operator "
                    "judgment required", exc_info=True,
                )

        # ---- W1 (TARGETED F2 REMEDIATION - the core fix): the audit
        # DIRECTORY is prepared BEFORE the pointer replace, and its
        # failure leaves the pointer COMPLETELY untouched (previously,
        # this mkdir ran AFTER the pointer replace and OUTSIDE the
        # rollback-protected block - an obstructed `index/audit/
        # activate` path left the pointer flipped with no way back). ----
        audit_dir = _activate_audit_dir(index_root_real)
        audit_dir.mkdir(parents=True, exist_ok=True)

        # ---- W2: pointer temp write + fsync + single atomic replace. ----
        payload = {"current_version": bundle_version}
        temp_path = index_root_real / "current_version.json.tmp"
        try:
            with open(temp_path, "wb") as file:
                file.write(_canonical_json_bytes(payload))
                file.flush()
                os.fsync(file.fileno())
            os.replace(str(temp_path), str(pointer_path))
        except Exception:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            raise

        idempotency_key = _idempotency_key_of(intent)
        audit_record = {
            "schema_version": 1,
            "action_family": ACTIVATE_ACTION_FAMILY,
            "channel": CHANNEL,
            "resource_key": RESOURCE_KEY,
            "target_ref": target_ref,
            "target_state": ACTIVATE_TARGET_STATE,
            "mutation_idempotency_key": idempotency_key,
            "mutation_resource_key": RESOURCE_KEY,
            "mutation_actor_ref": intent.actor_ref,
            "input_digest": activation_input_digest,
            "identity_payload": identity_payload,
            "bundle_version": bundle_version,
            "bundle_manifest_sha256": bundle_manifest_sha256,
            "expected_current_bundle_version": expected_current_version,
            "activation_attempt": activation_attempt,
            "previous_pointer_sha256": pointer_composite_hash,
            "generated_at": _now_iso(),
            "outcome": "activated",
        }
        audit_bytes = _canonical_json_bytes(audit_record)
        audit_path = audit_dir / f"{idempotency_key}.activate_audit.json"

        # ---- W3 (TARGETED F5.7 REMEDIATION - the `FileExistsError:
        # pass` content-blind swallow is GONE): a pre-existing file at
        # this EXACT path can only mean tamper/manual residue (the
        # journal-gate/PriorAttemptFailedError/replay-shortcircuit
        # already make a second legitimate writer entry for the SAME
        # idempotency_key structurally impossible) - refused fail-
        # closed, pointer rolled back, original exception raised. ----
        try:
            fd = os.open(str(audit_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError as error:
            _rollback_pointer()
            raise RagBundleMutationError(
                f"failed to create the activation audit file at {audit_path} (fail-closed)"
            ) from error

        # ---- W4: write/flush/fsync failure AFTER the fd was obtained -
        # (a) best-effort partial-file unlink, (b) pointer rollback,
        # (c) the ORIGINAL exception re-raised unchanged (an unlink
        # failure is only CRITICAL-logged, never allowed to mask it). ----
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(audit_bytes)
                file.flush()
                os.fsync(file.fileno())
        except Exception:
            try:
                audit_path.unlink()
            except OSError:
                import logging

                logging.getLogger("vergi_ai.rag_bundle_mutation_facade").critical(
                    f"partial activation audit unlink FAILED for {audit_path}", exc_info=True,
                )
            _rollback_pointer()
            raise

        return _mutation_coordinator.WriterResult(
            observed_post_hash=bundle_version,
            result=ActivateResult(
                bundle_version=bundle_version,
                previous_version=current_version,
                pointer_path=str(pointer_path),
                audit_path=str(audit_path),
                replayed=False,
            ),
        )

    conn_factory = _default_mutation_conn_factory if conn_factory is None else conn_factory
    conn = conn_factory()
    lock_held = False
    advisory_lock_id = None
    try:
        advisory_lock_id = _mutation_lock.acquire_global_lock_session(conn, RESOURCE_KEY)
        lock_held = True
        under_lock_box["repository"] = _global_authz.PostgresGlobalResourceAuthzRepository(conn)

        outcome = _mutation_coordinator.run_mutation(
            conn, intent,
            actor_user_id=getattr(principal, "user_id", None),
            authz_callback=_authz_callback,
            precondition_callback=_precondition_callback,
            writer_callback=_writer_callback,
        )
    finally:
        if lock_held:
            try:
                released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
                if not released:
                    import logging

                    logging.getLogger("vergi_ai.rag_bundle_mutation_facade").critical(
                        f"release_lock_session returned False for resource_key={RESOURCE_KEY!r}"
                    )
            except Exception:
                import logging

                logging.getLogger("vergi_ai.rag_bundle_mutation_facade").critical(
                    f"release_lock_session raised for resource_key={RESOURCE_KEY!r}", exc_info=True,
                )
        try:
            conn.close()
        except Exception:
            pass

    if outcome.replayed:
        return _verify_completed_activate_replay(
            outcome, intent=intent, index_root_real=index_root_real, bundle_version=bundle_version,
        )
    return outcome.result


_ACTIVATION_REPLAY_RECOVERY_HINT = (
    "re-run preview_activate() to see the CURRENT state; to genuinely re-apply this exact "
    "transition, declare a NEW activation_attempt (CLI: --activation-attempt N+1)"
)


def _verify_completed_activate_replay(
    outcome, *, intent: MutationIntent, index_root_real: Path, bundle_version: str,
) -> ActivateResult:
    """TARGETED F1/F3 REMEDIATION - full replay corroboration, replacing
    the OLD activate replay branch that constructed a success result
    WITHOUT checking anything at all (the second half of the F1 silent-
    no-op bug: even once the identity fix makes a genuine re-activation
    reach a NEW idempotency_key, THIS function is what makes the
    A(attempt=0)->B(attempt=0)->A->B(attempt=0) replay of the FIRST
    B-activation fail loudly instead of quietly reporting success while
    the pointer stays at A - see §2.3 requirement 1). NEVER triggers a
    writer/pointer/audit/network call."""
    observed = outcome.observed_post_hash
    if not isinstance(observed, str) or observed != bundle_version or not _BUNDLE_VERSION_PATTERN.match(observed):
        raise ActivationReplayVerificationError(
            f"observed_post_hash {observed!r} does not match the requested bundle_version "
            f"{bundle_version!r} - {_ACTIVATION_REPLAY_RECOVERY_HINT}"
        )

    pointer_path = index_root_real / "current_version.json"
    try:
        verified_pointer = _path_containment.resolve_existing(pointer_path, root=index_root_real)
        pointer_bytes = verified_pointer.read_bytes()
    except (_path_containment.PathContainmentError, OSError) as error:
        raise ActivationReplayVerificationError(
            f"the live pointer could not be read for replay corroboration - {_ACTIVATION_REPLAY_RECOVERY_HINT}"
        ) from error
    expected_pointer_bytes = _canonical_json_bytes({"current_version": bundle_version})
    if pointer_bytes != expected_pointer_bytes:
        raise ActivationReplayVerificationError(
            f"the live pointer does not byte-canonically point at {bundle_version!r} - this replay "
            f"cannot be corroborated. {_ACTIVATION_REPLAY_RECOVERY_HINT}"
        )

    try:
        _verify_bundle_fully(index_root_real, bundle_version)
    except RagBundleMutationError as error:
        raise ActivationReplayVerificationError(
            f"index/{bundle_version}/ failed full reverification on replay - {_ACTIVATION_REPLAY_RECOVERY_HINT}"
        ) from error

    audit_dir = _activate_audit_dir(index_root_real)
    records, corrupt = _scan_audit_dir(audit_dir, index_root_real, ".activate_audit.json")
    if records is None:
        raise ActivationReplayVerificationError(
            f"the activate-audit directory has a containment anomaly - {_ACTIVATION_REPLAY_RECOVERY_HINT}"
        )
    idempotency_key = _idempotency_key_of(intent)
    matches = [
        (path, record) for path, record in records
        if (
            record.get("mutation_idempotency_key") == idempotency_key
            and record.get("mutation_resource_key") == RESOURCE_KEY
            and record.get("action_family") == ACTIVATE_ACTION_FAMILY
        )
    ]
    if corrupt != 0 or len(matches) != 1:
        raise ActivationReplayVerificationError(
            "expected exactly one uncorrupted activation audit bound to this attempt's own "
            f"idempotency identity; found {len(matches)} matching (corrupt={corrupt}). "
            f"{_ACTIVATION_REPLAY_RECOVERY_HINT}"
        )
    audit_path, record = matches[0]
    ok, found_bundle_version, recomputed_input_digest = _activate_audit_content_ok(index_root_real, record)
    if (
        not ok
        or found_bundle_version != bundle_version
        or recomputed_input_digest != intent.pre_revision
        or record.get("previous_pointer_sha256") != intent.pre_hash
    ):
        raise ActivationReplayVerificationError(
            f"the bound activation audit failed independent recompute verification. {_ACTIVATION_REPLAY_RECOVERY_HINT}"
        )

    if not _bundle_has_verified_build_audit(index_root_real, bundle_version):
        raise ActivationReplayVerificationError(
            f"index/{bundle_version}/ no longer carries a valid, fully-bound build audit - "
            f"{_ACTIVATION_REPLAY_RECOVERY_HINT}"
        )

    recorded_expected = record.get("expected_current_bundle_version")
    previous_version = recorded_expected if isinstance(recorded_expected, str) and _BUNDLE_VERSION_PATTERN.match(recorded_expected) else None

    return ActivateResult(
        bundle_version=observed,
        previous_version=previous_version,
        pointer_path=str(pointer_path),
        audit_path=str(audit_path),
        replayed=True,
    )


def list_bundles(*, principal, authz_repository) -> dict:
    _global_authz.authorize_global_resource_access(principal, "inspect", repository=authz_repository)

    index_root = Path(_index_root())
    index_root.mkdir(parents=True, exist_ok=True)
    index_root_real = index_root.resolve(strict=True)

    pointer_state, current_version = _read_pointer_state(index_root_real)

    bundle_versions = []
    for entry in _path_containment.list_contained_dir(index_root_real):
        if not entry.is_dir():
            continue
        if not _BUNDLE_VERSION_PATTERN.match(entry.name):
            continue
        has_audit = _bundle_has_verified_build_audit(index_root_real, entry.name)
        bundle_versions.append({"bundle_version": entry.name, "has_build_audit": has_audit})
    bundle_versions.sort(key=lambda item: item["bundle_version"])

    return {
        "resource_key": RESOURCE_KEY,
        "current_pointer_state": pointer_state,
        "current_version": current_version,
        "bundles": bundle_versions,
    }
