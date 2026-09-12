# ============================================================
# VERGİ AI - ROW 19C-3c-iv SLICE 1: DETERMINISTIC + AGENT LEGAL
# RESEARCH / CASE LAW RECONCILIATION ADAPTERS.
#
# `generation.legal_research` / `generation.case_law` journal satırları
# için `ui.services.mutation_registry.ReconciliationAdapter`
# implementasyonu + `register_into()` (reconciliation operator'ün
# merged registry'sine SEKİZİNCİ kaynak olarak eklenir: 10 approval +
# 24 review + 1 drafting_request + 2 promotion + 2 deterministic-
# generation + 5 agent-generation + 1 fact-extraction-generation + 2
# legal-research/case-law-generation = 47 routing key).
#
# BAĞIMSIZ KANIT İLKESİ (önceki tüm adapters ile AYNI): bu modül
# `legal_research_case_law_mutation_facade`'in doğrulama/karar
# fonksiyonlarını İMPORT ETMEZ (yalnız karar içermeyen `LEGAL_RESEARCH_
# CASE_LAW_ROW_KEY_TO_MODULE_NAME` + `FAMILY_INPUT_SPECS` +
# `legal_research_case_law_action_family_for()` sabit/format
# yardımcıları paylaşılır); containment/manifest/audit-eşleşme mantığı
# burada BAĞIMSIZ İKİNCİ implementasyondur - birindeki bug diğerini
# MASKELEYEMEZ.
#
# TRANSİTİF KABUL YOK: `_audit_record_matches()` audit kaydındaki HER
# güvenlik/provenance alanını DOĞRUDAN kendi exact değeriyle doğrular.
# `identity_payload` KENDİ bağımsız canonical serializer'la YENİDEN
# hash'lenir ve HEM `audit.input_digest`'e HEM `entry.pre_revision`'a
# DOĞRUDAN eşit olmak ZORUNDADIR (fact_extraction/erratum §E.3
# sertleştirmesiyle AYNI, dolaylı idempotency_key-üzerinden bağlamanın
# ÖTESİNDE açık bir ek savunma katmanı). `identity_payload["case_id"]`
# ayrıca `entry.resource_key`'den türetilen case_id'ye BİREBİR eşit
# olmak ZORUNDADIR.
#
# PRE-STATE/POST-STATE TAMAMEN BAĞIMSIZ: generation'ın pending çıktısı
# DETERMİNİSTİK DEĞİLDİR (`research_analysis_id`/`case_law_analysis_id`/
# `generated_at`) - post-state YALNIZ tam-bağlama eşleşen bir success
# audit ile kurulabilir. `_compute_pre_state_proof()` HİÇBİR ZAMAN JSON
# parse etmez, audit taramaz veya girdi dosyası okumaz - YALNIZ `entry.
# pre_hash`/`entry.pre_revision` (opak, YENİDEN HESAPLANMAZ) + mevcut
# pending'in containment-doğrulanmış ham-bayt varlığı/hash'i. `_compute_
# post_state_proof()` HİÇBİR ZAMAN pre-state kanıtına bakmaz.
# ============================================================

from __future__ import annotations

import fnmatch
import hashlib
import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import path_containment as _path_containment  # noqa: E402

from . import mutation_registry as mr
from .common import sha256_file
from .legal_research_case_law_mutation_facade import (
    FAMILY_INPUT_SPECS,
    LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME,
    legal_research_case_law_action_family_for,
)


class NestedPathContainmentError(Exception):
    """Internal-only: containment helper'larından `gather_evidence()`'ın
    dual-false dönüşüne unwind sinyali - modül sınırını asla aşmaz."""


class UnexpectedResourceKeyShapeError(Exception):
    """`case:<case_id>` olmayan resource_key ile bu adapter'lara
    yönlenen satır - yapısal olarak ulaşılmaz backstop."""


_DUAL_FALSE = mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

# Facade formülünün BAĞIMSIZ kopyası - facade'in KENDİ `_SNAPSHOT_
# VERSION`/`_MANIFEST_VERSION_BY_ROW_KEY` ile BİREBİR aynı string'ler
# olmak ZORUNDADIR (izole canary testi bunu ayrıca kanıtlar).
_SNAPSHOT_ABSENT = "__absent__"
_SNAPSHOT_PRESENT = "__present__"
_SNAPSHOT_VERSION = "row19c3civ.legal_research_case_law.snapshot.v1"

_MANIFEST_VERSION_BY_ROW_KEY = {
    "legal_research": "row19c3civ.legal_research.manifest.v1",
    "case_law": "row19c3civ.case_law.manifest.v1",
}

_CHANNEL = "local_lawyer_legal_research_case_law_cli"

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


def _validate_identity_payload_shape(identity_payload, row_key: str, expected_case_id: str) -> bool:
    """Şekil/schema doğrulaması - bağımsız kod, facade ile PAYLAŞILMAZ.
    Herhangi bir ihlal (duplicate container, duplicate path, bilinmeyen
    alan/state, malformed hash, case_id uyuşmazlığı) False döner - bu
    TEK BAŞINA fail-closed bir "bu kayıt eşleşmiyor" sonucudur, TÜM
    taramayı poison ETMEZ (containment-unsafe/unparseable dosyanın TÜM
    taramayı durdurduğu ayrı kuraldan BİLİNÇLİ olarak FARKLIDIR)."""
    if not isinstance(identity_payload, dict):
        return False
    if set(identity_payload.keys()) != {
        "manifest_version", "case_id", "manifest", "generation_mode", "model_id",
        "engine_version", "prompt_agent_version",
    }:
        return False
    if identity_payload.get("manifest_version") != _MANIFEST_VERSION_BY_ROW_KEY.get(row_key):
        return False
    if identity_payload.get("case_id") != expected_case_id:
        return False
    if identity_payload.get("generation_mode") not in ("deterministic", "agent"):
        return False
    if not _nonblank(identity_payload.get("model_id")):
        return False
    if not _nonblank(identity_payload.get("engine_version")):
        return False
    if not _nonblank(identity_payload.get("prompt_agent_version")):
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


def _audit_record_matches(
    record: dict, row_key: str, *,
    idempotency_key: str, resource_key: str, action_family: str, target_ref: str,
    target_state: str, actor_label: str, pending_sha256: str, expected_case_id: str,
) -> bool:
    """TAM bağlama - eksik/boş/uyumsuz HERHANGİ bir değer False (asla
    otomatik kanıt, asla transitif kabul)."""
    if record.get("schema_version") != "1":
        return False
    if record.get("case_id") != expected_case_id:
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
        if not _nonblank(history_backup_path) or not _is_sha256_hex(history_backup_sha256):
            return False
        # Backup dosyası GERÇEKTEN mevcut, containment-doğrulanmış ve
        # raw-byte hash'i eşleşir olmak ZORUNDADIR - rollback backup'ı
        # geri taşımışsa (yani artık o konumda YOK) bu adım False döner.
        try:
            backup_path = Path(history_backup_path)
            if not backup_path.is_file():
                return False
            actual_backup_sha256 = hashlib.sha256(backup_path.read_bytes()).hexdigest()
        except OSError:
            return False
        if actual_backup_sha256 != history_backup_sha256:
            return False

    identity_payload = record.get("identity_payload")
    if not _validate_identity_payload_shape(identity_payload, row_key, expected_case_id):
        return False

    recomputed_input_digest = hashlib.sha256(_canonical_identity_bytes(identity_payload)).hexdigest()
    if recomputed_input_digest != record.get("input_digest"):
        return False

    # ERRATUM §E.3-STYLE SERTLEŞTİRME (fact_extraction ile AYNI ilke):
    # journal'ın KENDİ değiştirilemez pre_revision kolonuna DOĞRUDAN
    # eşitlik, dolaylı (idempotency_key-üzerinden) korumanın YERİNE
    # DEĞİL, ONA EK. Bu kontrol `gather_evidence()`'ın kendi çağrısında
    # `entry_pre_revision` argümanı ile bağlanır (bkz. aşağıdaki çağıran).

    if record.get("generation_mode") != identity_payload.get("generation_mode"):
        return False
    if record.get("model_id") != identity_payload.get("model_id"):
        return False
    if record.get("engine_version") != identity_payload.get("engine_version"):
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


class LegalResearchCaseLawReconciliationAdapter:
    """`generation.<row_key>` (legal_research/case_law) için tek
    adapter sınıfı - row_key + writer modülü construction'da
    sabitlenir. Salt-okunur; hiçbir file/DB mutasyonu yapmaz (Protocol
    kontratı)."""

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
        post_state_proof = self._compute_post_state_proof(
            entry, case_root_real, pending_verified, reviews_verified, case_id,
        )

        return mr.ReconciliationEvidence(
            post_state_verified=post_state_proof.verified,
            pre_state_confirmed_unchanged=pre_state_proof.confirmed_unchanged,
            observed_post_hash=post_state_proof.observed_post_hash,
        )

    def _compute_pre_state_proof(self, entry: mr.JournalEntrySnapshot, pending_verified: Path) -> _PreStateProof:
        """BAĞIMSIZ: JSON ASLA parse edilmez, audit dizini ASLA
        taranmaz, HİÇBİR girdi dosyası OKUNMAZ. Yalnız `entry.pre_
        revision` (opak, YENİDEN HESAPLANMAZ) + mevcut pending'in
        containment-doğrulanmış ham-bayt varlığı/hash'i."""
        if not _nonblank(entry.pre_hash) or not _nonblank(entry.pre_revision):
            return _PreStateProof(confirmed_unchanged=False)
        current_sha = sha256_file(pending_verified)
        current_presence = _SNAPSHOT_PRESENT if current_sha is not None else _SNAPSHOT_ABSENT
        current_pending_sha256 = current_sha if current_sha is not None else _SNAPSHOT_ABSENT
        candidate = _compute_candidate_pre_hash(entry.pre_revision, current_presence, current_pending_sha256)
        return _PreStateProof(confirmed_unchanged=(candidate == entry.pre_hash))

    def _compute_post_state_proof(
        self, entry: mr.JournalEntrySnapshot, case_root_real: Path, pending_verified: Path,
        reviews_verified: Path, case_id: str,
    ) -> _PostStateProof:
        """BAĞIMSIZ: pre-state kanıtına/sonucuna ASLA bakmaz. Bir
        JSONDecodeError/parse hatası (audit taramasında) bu fonksiyonun
        KENDİ sınırı içinde yakalanır ve yalnız `verified=False` üretir."""
        current_sha = sha256_file(pending_verified)
        if current_sha is None:
            return _PostStateProof(verified=False, observed_post_hash=None)

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
                expected_case_id=case_id,
            )
            and hashlib.sha256(
                _canonical_identity_bytes(record.get("identity_payload"))
            ).hexdigest() == entry.pre_revision
        ]
        if len(matches) != 1:
            return _PostStateProof(verified=False, observed_post_hash=None)
        return _PostStateProof(verified=True, observed_post_hash=current_sha)


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    """legal_research/case_law ailelerini var olan bir registry'ye
    ekler - `reconciliation_operator._default_registry_factory()`'nin
    SEKİZİNCİ kaynağı. Action-family string'leri facade'in kendi `legal_
    research_case_law_action_family_for()`'undan gelir - drift
    imkânsız."""
    for row_key, module_name in LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME.items():
        module = importlib.import_module(module_name)
        registry = registry.with_adapter(
            legal_research_case_law_action_family_for(row_key),
            LegalResearchCaseLawReconciliationAdapter(module, row_key),
        )
    return registry
