# ============================================================
# VERGİ AI - PHASE B (COMMIT A): QA / CASE-VIEW COORDINATED PENDING
# GENERATION RECONCILIATION ADAPTERS.
#
# `generation.qa` / `generation.case_view` journal satırları için
# `ui.services.mutation_registry.ReconciliationAdapter` implementasyonu
# + `register_into()` (reconciliation operator'ün merged registry'sine
# ONBİRİNCİ kaynak olarak eklenir: 10 approval + 24 review + 1
# drafting_request + 2 promotion + 2 deterministic generation + 5 agent
# generation + 1 fact_extraction generation + 2 legal_research/case_law
# generation + 2 rag_bundle + 1 fact verification + 2 qa/case_view
# generation = 52 routing key).
#
# BAĞIMSIZ KANIT İLKESİ: bu modül facade'in doğrulama/karar
# fonksiyonlarını İMPORT ETMEZ (yalnız karar içermeyen
# `QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME` +
# `FAMILY_DIR_BY_ROW_KEY` + `FAMILY_INPUT_SPECS` + action-family format
# yardımcısı paylaşılır); containment/manifest/audit-eşleşme mantığı
# burada BAĞIMSIZ İKİNCİ implementasyondur.
#
# PORTABLE HISTORY BACKUP (kullanıcı kararı, Phase B Commit A madde 4):
# audit'in `history_backup_path` alanı repo-göreli canonical
# locator'dır (`data/cases/<case_id>/<qa|case_view>/history/<ad>`),
# MUTLAK yol DEĞİL. Adapter bu değeri (a) exact metin şekliyle (case_id
# ve aile dizini dahil) ve (b) yalnız BAĞIMSIZCA doğrulanmış history
# dizini altında, DOSYA ADIYLA çözerek bağlar - audit'teki metnin kendisi
# asla bir filesystem yolu olarak kullanılmaz (carry-forward binding
# deseni).
#
# PRE-STATE/POST-STATE TAMAMEN BAĞIMSIZ: pre-state YALNIZ
# `entry.pre_hash`/`entry.pre_revision` (opak) + mevcut pending'in
# containment-doğrulanmış ham-bayt varlığı/hash'i; JSON parse etmez,
# audit taramaz. Post-state YALNIZ tam-bağlama eşleşen TEK bir success
# audit ile kurulur; pre-state kanıtına ASLA bakmaz.
# ============================================================

from __future__ import annotations

import fnmatch
import hashlib
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import path_containment as _path_containment  # noqa: E402

from . import mutation_registry as mr
from .common import sha256_file
from .qa_case_view_generation_mutation_facade import (
    FAMILY_DIR_BY_ROW_KEY,
    FAMILY_INPUT_SPECS,
    QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME,
    qa_case_view_generation_action_family_for,
)


class NestedPathContainmentError(Exception):
    """Internal-only: containment helper'larından `gather_evidence()`'ın
    dual-false dönüşüne unwind sinyali - modül sınırını asla aşmaz."""


class UnexpectedResourceKeyShapeError(Exception):
    """`case:<case_id>` olmayan resource_key ile bu adapter'lara
    yönlenen satır - yapısal olarak ulaşılmaz backstop."""


_DUAL_FALSE = mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

# Facade formülünün BAĞIMSIZ kopyası - facade'in KENDİ `_SNAPSHOT_
# VERSION`/`_MANIFEST_VERSION` ile BİREBİR aynı string olmak ZORUNDADIR
# (izole canary testi bunu ayrıca kanıtlar).
_SNAPSHOT_ABSENT = "__absent__"
_SNAPSHOT_PRESENT = "__present__"
_SNAPSHOT_VERSION = "phaseb.qa_case_view_generation.snapshot.v1"
_MANIFEST_VERSION = "phaseb.qa_case_view_generation.v1"

_CHANNEL = "local_lawyer_generation_cli"
_GENERATION_MODE = "deterministic"
_MODEL_ID = "deterministic_no_model"
_PROMPT_AGENT_VERSION = "n/a"
_LOCATOR_PREFIX = "data/cases"

_ALLOWED_STATES = frozenset({"present", "empty", "missing"})

_SHA256_HEX_LEN = 64


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256_hex(value) -> bool:
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LEN:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _resolve_case_root_real(module, case_id: str) -> Path:
    cases_dir = module.CASES_DIR
    try:
        _path_containment.validate_segment(case_id)
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise NestedPathContainmentError(str(error)) from error


def _verify_nested(module, case_root_real: Path, case_id: str, raw_path) -> Path:
    cases_dir = module.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise NestedPathContainmentError(str(error)) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise NestedPathContainmentError(str(error)) from error


def _derive_reviews_dir(module, case_root_real: Path, case_id: str) -> Path:
    return _verify_nested(module, case_root_real, case_id, module.get_reviews_dir(case_id))


def _derive_pending_path(module, case_root_real: Path, case_id: str) -> Path:
    return _verify_nested(module, case_root_real, case_id, module.get_pending_path(case_id))


def _derive_history_dir(module, case_root_real: Path, case_id: str) -> Path:
    return _verify_nested(module, case_root_real, case_id, module.get_history_dir(case_id))


def _scan_generation_audits(case_root_real: Path, reviews_dir_verified: Path):
    """Containment-before-stat audit taraması - facade'inkinin bağımsız
    kopyası. Kaçan/kırık/alias giriş TÜM taramayı durdurur (raise);
    parse edilemeyen giriş `(path, None)` döner."""
    if not reviews_dir_verified.is_dir():
        return []
    try:
        raw_entries = sorted(reviews_dir_verified.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise NestedPathContainmentError(str(error)) from error
    results = []
    for entry in raw_entries:
        if not fnmatch.fnmatch(entry.name, "*.generation_audit.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise NestedPathContainmentError(str(error)) from error
        if resolved.parent != reviews_dir_verified:
            raise NestedPathContainmentError(f"in-tree alias: {entry.name!r}")
        try:
            with open(resolved, "r", encoding="utf-8") as file:
                record = json.load(file)
            if not isinstance(record, dict):
                record = None
        except Exception:
            record = None
        results.append((resolved, record))
    return results


def _compute_candidate_pre_hash(input_digest: str, pending_presence: str, pending_sha256: str) -> str:
    payload = json.dumps(
        {
            "snapshot_version": _SNAPSHOT_VERSION,
            "input_digest": input_digest,
            "pending_presence": pending_presence,
            "pending_sha256": pending_sha256,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_identity_bytes(identity_payload) -> bytes:
    return json.dumps(
        identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _validate_identity_payload_shape(identity_payload, row_key: str) -> bool:
    """Şekil/schema doğrulaması - bağımsız kod. Herhangi bir ihlal False
    döner (tek kaydın eşleşmemesi; TÜM taramayı poison ETMEZ)."""
    if not isinstance(identity_payload, dict):
        return False
    if set(identity_payload.keys()) != {
        "manifest_version", "manifest", "generation_mode", "model_id", "prompt_agent_version",
    }:
        return False
    if identity_payload.get("manifest_version") != _MANIFEST_VERSION:
        return False
    # SALT deterministik aile - agent sentinel'leri KABUL EDİLMEZ.
    if identity_payload.get("generation_mode") != _GENERATION_MODE:
        return False
    if identity_payload.get("model_id") != _MODEL_ID:
        return False
    if identity_payload.get("prompt_agent_version") != _PROMPT_AGENT_VERSION:
        return False

    manifest = identity_payload.get("manifest")
    if not isinstance(manifest, list):
        return False

    expected_names = {name for name, _kind, _extra in FAMILY_INPUT_SPECS[row_key]}
    if len(manifest) != len(expected_names):
        return False

    seen_names = set()
    for container in manifest:
        if not isinstance(container, dict):
            return False
        if set(container.keys()) != {"logical_name", "state", "files"}:
            return False
        logical_name = container.get("logical_name")
        if logical_name not in expected_names or logical_name in seen_names:
            return False
        seen_names.add(logical_name)
        state = container.get("state")
        if state not in _ALLOWED_STATES:
            return False
        files = container.get("files")
        if not isinstance(files, list):
            return False
        if state != "present" and files:
            return False
        if state == "present" and not files:
            return False
        seen_paths = set()
        for file_entry in files:
            if not isinstance(file_entry, dict):
                return False
            if set(file_entry.keys()) != {"logical_relative_path", "sha256"}:
                return False
            rel_path = file_entry.get("logical_relative_path")
            sha = file_entry.get("sha256")
            if not _nonblank(rel_path) or rel_path in seen_paths:
                return False
            seen_paths.add(rel_path)
            if not _is_sha256_hex(sha):
                return False

    if seen_names != expected_names:
        return False

    return True


def _verify_history_backup_binding(
    history_backup_path, expected_sha256, *, history_dir_verified: Path, case_id: str, row_key: str,
) -> bool:
    """`history_backup_path` repo-göreli canonical locator olmak
    ZORUNDADIR: exact metin `data/cases/<case_id>/<family_dir>/history/
    <ad>` (POSIX ayraçlı, mutlak/sürücü/UNC/`..`/ters-bölü YOK). Dosya
    YALNIZ bağımsızca doğrulanmış `history_dir_verified` altında, ADIYLA
    çözülür (audit'teki metin filesystem yolu olarak KULLANILMAZ);
    exact-parent, normal-dosya ve ham-bayt hash eşitliği doğrulanır."""
    if not _nonblank(history_backup_path) or not _is_sha256_hex(expected_sha256):
        return False
    if "\\" in history_backup_path or ":" in history_backup_path or history_backup_path.startswith("/"):
        return False
    parts = history_backup_path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    expected_prefix = _LOCATOR_PREFIX.split("/") + [case_id, FAMILY_DIR_BY_ROW_KEY[row_key], "history"]
    if len(parts) != len(expected_prefix) + 1 or parts[:-1] != expected_prefix:
        return False
    candidate_name = PurePosixPath(history_backup_path).name
    if not candidate_name or candidate_name != parts[-1]:
        return False
    try:
        _path_containment.validate_segment(candidate_name)
    except (TypeError, ValueError, _path_containment.PathContainmentError):
        return False

    try:
        resolved = _path_containment.resolve_existing(
            history_dir_verified / candidate_name, root=history_dir_verified,
        )
    except _path_containment.PathContainmentError:
        return False

    if resolved.parent != history_dir_verified:
        return False

    try:
        if not resolved.is_file():
            return False
        raw_bytes = resolved.read_bytes()
    except OSError:
        return False

    return hashlib.sha256(raw_bytes).hexdigest() == expected_sha256


def _audit_record_matches(
    record: dict, row_key: str, *,
    idempotency_key: str, resource_key: str, action_family: str, target_ref: str,
    target_state: str, actor_label: str, pending_sha256: str,
    history_dir_verified: Path | None,
) -> bool:
    """TAM bağlama - eksik/boş/uyumsuz HERHANGİ bir değer False (asla
    otomatik kanıt, asla transitif kabul)."""
    if record.get("schema_version") != "1":
        return False
    case_id = resource_key[len("case:"):]
    if record.get("case_id") != case_id:
        return False
    if record.get("target_ref") != target_ref:
        return False
    if record.get("target_state") != target_state:
        return False
    if record.get("action_family") != action_family:
        return False
    if record.get("channel") != _CHANNEL:
        return False
    if not _nonblank(record.get("mutation_actor_ref")) or record.get("mutation_actor_ref") != actor_label:
        return False
    if not _nonblank(record.get("mutation_idempotency_key")) or record.get("mutation_idempotency_key") != idempotency_key:
        return False
    if not _nonblank(record.get("mutation_resource_key")) or record.get("mutation_resource_key") != resource_key:
        return False
    if record.get("generation_parameters_digest") is not None:
        return False
    if not _nonblank(record.get("pending_sha256")) or record.get("pending_sha256") != pending_sha256:
        return False
    if record.get("outcome") != "generated":
        return False
    if not isinstance(record.get("first_write"), bool):
        return False

    first_write = record["first_write"]
    history_backup_path = record.get("history_backup_path")
    history_backup_sha256 = record.get("history_backup_sha256")

    if first_write:
        if history_backup_path is not None or history_backup_sha256 is not None:
            return False
    else:
        if history_dir_verified is None:
            # Verified history root could not be derived - fail-closed,
            # never trust the audit-provided text as a substitute root.
            return False
        if not _verify_history_backup_binding(
            history_backup_path, history_backup_sha256,
            history_dir_verified=history_dir_verified, case_id=case_id, row_key=row_key,
        ):
            return False

    identity_payload = record.get("identity_payload")
    if not _validate_identity_payload_shape(identity_payload, row_key):
        return False

    recomputed_input_digest = hashlib.sha256(_canonical_identity_bytes(identity_payload)).hexdigest()
    if recomputed_input_digest != record.get("input_digest"):
        return False

    if record.get("generation_mode") != identity_payload.get("generation_mode"):
        return False
    if record.get("model_id") != identity_payload.get("model_id"):
        return False
    if record.get("prompt_agent_version") != identity_payload.get("prompt_agent_version"):
        return False

    return True


@dataclass(frozen=True)
class _PreStateProof:
    confirmed_unchanged: bool


@dataclass(frozen=True)
class _PostStateProof:
    verified: bool
    observed_post_hash: str | None


def _target_ref_matches_row_key(row_key: str, target_ref) -> bool:
    if not isinstance(target_ref, str) or not target_ref:
        return False
    return target_ref == f"{row_key}.pending"


class QaCaseViewGenerationReconciliationAdapter:
    """`generation.qa` / `generation.case_view` için tek adapter sınıfı -
    row_key + writer modülü construction'da sabitlenir. Salt-okunur;
    hiçbir file/DB mutasyonu yapmaz (Protocol kontratı); builder/writer
    ASLA yeniden çağrılmaz."""

    def __init__(self, module, row_key: str):
        self._module = module
        self._row_key = row_key

    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if not entry.resource_key.startswith("case:"):
            raise UnexpectedResourceKeyShapeError(
                f"journal_id={entry.journal_id}: expected 'case:<case_id>', got {entry.resource_key!r}"
            )
        case_id = entry.resource_key[len("case:"):]

        if not _target_ref_matches_row_key(self._row_key, entry.target_ref):
            return _DUAL_FALSE

        module = self._module
        try:
            case_root_real = _resolve_case_root_real(module, case_id)
            pending_verified = _derive_pending_path(module, case_root_real, case_id)
            reviews_verified = _derive_reviews_dir(module, case_root_real, case_id)
        except (NestedPathContainmentError, _path_containment.PathContainmentError):
            return _DUAL_FALSE

        pre_state_proof = self._compute_pre_state_proof(entry, pending_verified)
        post_state_proof = self._compute_post_state_proof(entry, case_root_real, pending_verified, reviews_verified)

        return mr.ReconciliationEvidence(
            post_state_verified=post_state_proof.verified,
            pre_state_confirmed_unchanged=pre_state_proof.confirmed_unchanged,
            observed_post_hash=post_state_proof.observed_post_hash,
        )

    def _compute_pre_state_proof(self, entry: mr.JournalEntrySnapshot, pending_verified: Path) -> _PreStateProof:
        if not _nonblank(entry.pre_hash) or not _nonblank(entry.pre_revision):
            return _PreStateProof(confirmed_unchanged=False)
        current_sha = sha256_file(pending_verified)
        current_presence = _SNAPSHOT_PRESENT if current_sha is not None else _SNAPSHOT_ABSENT
        current_pending_sha256 = current_sha if current_sha is not None else _SNAPSHOT_ABSENT
        candidate = _compute_candidate_pre_hash(entry.pre_revision, current_presence, current_pending_sha256)
        return _PreStateProof(confirmed_unchanged=(candidate == entry.pre_hash))

    def _compute_post_state_proof(
        self, entry: mr.JournalEntrySnapshot, case_root_real: Path, pending_verified: Path, reviews_verified: Path,
    ) -> _PostStateProof:
        current_sha = sha256_file(pending_verified)
        if current_sha is None:
            return _PostStateProof(verified=False, observed_post_hash=None)

        case_id = entry.resource_key[len("case:"):]
        try:
            history_dir_verified = _derive_history_dir(self._module, case_root_real, case_id)
        except NestedPathContainmentError:
            history_dir_verified = None

        try:
            entries = _scan_generation_audits(case_root_real, reviews_verified)
        except NestedPathContainmentError:
            return _PostStateProof(verified=False, observed_post_hash=None)
        if any(record is None for _path, record in entries):
            return _PostStateProof(verified=False, observed_post_hash=None)
        matches = [
            (path, record) for path, record in entries
            if _audit_record_matches(
                record, self._row_key,
                idempotency_key=entry.idempotency_key,
                resource_key=entry.resource_key,
                action_family=entry.action_family,
                target_ref=entry.target_ref,
                target_state=entry.target_state,
                actor_label=entry.actor_label,
                pending_sha256=current_sha,
                history_dir_verified=history_dir_verified,
            )
        ]
        if len(matches) != 1:
            return _PostStateProof(verified=False, observed_post_hash=None)
        return _PostStateProof(verified=True, observed_post_hash=current_sha)


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    """İki qa/case_view generation ailesini var olan bir registry'ye
    ekler - `reconciliation_operator._default_registry_factory()`'nin
    ONBİRİNCİ kaynağı. Action-family string'leri facade'in kendi
    `qa_case_view_generation_action_family_for()`'undan gelir."""
    for row_key, module_name in QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME.items():
        module = importlib.import_module(module_name)
        registry = registry.with_adapter(
            qa_case_view_generation_action_family_for(row_key),
            QaCaseViewGenerationReconciliationAdapter(module, row_key),
        )
    return registry
