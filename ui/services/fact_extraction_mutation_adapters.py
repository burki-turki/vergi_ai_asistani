# ============================================================
# VERGİ AI - ROW 19C-3c-iii: FACT EXTRACTION GENERATION RECONCILIATION
# ADAPTERS.
#
# `generation.fact_extraction` journal satırları için `ui.services.
# mutation_registry.ReconciliationAdapter` implementasyonu +
# `register_into()` (reconciliation operator'ün merged registry'sine
# YEDİNCİ kaynak olarak eklenir: 10 approval + 24 review + 1
# drafting_request + 2 promotion + 2 (deterministic) generation + 5
# (agent) generation + 1 fact_extraction generation = 45 routing key).
#
# BAĞIMSIZ KANIT İLKESİ (Layer A/B/promotion/generation/agent-generation
# adapters ile AYNI): bu modül `fact_extraction_mutation_facade`'in
# doğrulama/karar fonksiyonlarını İMPORT ETMEZ (yalnız karar içermeyen
# `FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME` + `fact_extraction_action_
# family_for()`/`fact_extraction_target_ref_for()` sabit/format
# yardımcıları paylaşılır); containment/manifest/audit-eşleşme mantığı
# burada BAĞIMSIZ İKİNCİ implementasyondur - birindeki bug diğerini
# MASKELEYEMEZ.
#
# DOCUMENT-SCOPED TARGET_REF PARSING (beş/iki aileden AYRI - hiçbirinde
# yoktu): bu ailenin `target_ref`'i case-scoped `<row_key>.pending`
# DEĞİL, document-scoped `fact.<document_id>.pending`'tir - adapter
# `entry.target_ref`'ten `document_id`'yi PARSE EDER (fail-closed:
# beklenen `fact.` prefix'i/`.pending` suffix'i yoksa VEYA orta segment
# `path_containment.validate_segment()`'ten geçemiyorsa dual-false).
# Parse edilen document_id ÜÇ YÖNLÜ bağlanır: `entry.target_ref`'ten
# türetilen değer == `audit["document_id"]` == `identity_payload[
# "document_id"]` - üçü de eşleşmezse post-proof reddedilir.
#
# TRANSİTİF KABUL YOK + ERRATUM §E.3 SERTLEŞTİRMESİ: `_audit_record_
# matches()` audit kaydındaki HER güvenlik/provenance alanını DOĞRUDAN
# kendi exact değeriyle doğrular. `identity_payload` KENDİ bağımsız
# canonical serializer'la YENİDEN hash'lenir ve HEM `audit.input_digest`
# HEM `entry.pre_revision`'a (journal'ın DEĞİŞTİRİLEMEZ, DB-otoriter
# kolonu) DOĞRUDAN eşit olmak ZORUNDADIR - beş/iki ailenin precedent
# adapter'ının yalnız DOLAYLI (idempotency_key üzerinden) bıraktığı bağı,
# bu aile AÇIK, literal bir kontrole dönüştürür (bkz. erratum §E.3/§B.4).
#
# PRE-STATE/POST-STATE TAMAMEN BAĞIMSIZ: generation'ın pending çıktısı
# DETERMİNİSTİK DEĞİLDİR - post-state YALNIZ tam-bağlama eşleşen bir
# success audit ile kurulabilir. `_compute_pre_state_proof()` HİÇBİR
# ZAMAN JSON parse etmez, audit taramaz veya girdi dosyası okumaz -
# YALNIZ `entry.pre_hash`/`entry.pre_revision` (opak, YENİDEN
# HESAPLANMAZ) + mevcut pending'in containment-doğrulanmış ham-bayt
# varlığı/hash'i. `_compute_post_state_proof()` HİÇBİR ZAMAN pre-state
# kanıtına bakmaz.
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
from .fact_extraction_mutation_facade import (
    FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME,
    fact_extraction_action_family_for,
)


class NestedPathContainmentError(Exception):
    """Internal-only: containment helper'larından `gather_evidence()`'ın
    dual-false dönüşüne unwind sinyali - modül sınırını asla aşmaz."""


class UnexpectedResourceKeyShapeError(Exception):
    """`case:<case_id>` olmayan resource_key ile bu adapter'a
    yönlenen satır - yapısal olarak ulaşılmaz backstop."""


_DUAL_FALSE = mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

# Facade formülünün BAĞIMSIZ kopyası - facade'in KENDİ `_SNAPSHOT_
# VERSION`/`_MANIFEST_VERSION` ile BİREBİR aynı string olmak ZORUNDADIR
# (izole canary testi bunu ayrıca kanıtlar). Facade'in kendisinden
# FARKLI, bilinçli olarak AYRIŞTIRILMIŞ iki literal (precedent'in
# kafa-karıştırıcı aynı-değer seçimi TEKRARLANMAZ).
_SNAPSHOT_ABSENT = "__absent__"
_SNAPSHOT_PRESENT = "__present__"
_SNAPSHOT_VERSION = "row19c3ciii.fact_extraction.snapshot.v1"
_MANIFEST_VERSION = "row19c3ciii.fact_extraction.manifest.v1"

_CHANNEL = "local_lawyer_fact_extraction_cli"

_TARGET_REF_PREFIX = "fact."
_TARGET_REF_SUFFIX = ".pending"

_ALLOWED_STATES = frozenset({"present", "empty", "missing"})

_EXPECTED_MANIFEST_NAMES = frozenset({"case", "case_documents", "target_document", "target_document_text"})

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


def _parse_document_id_from_target_ref(target_ref) -> str | None:
    """`fact.<document_id>.pending` -> `<document_id>`, fail-closed
    (`None`) eğer prefix/suffix eşleşmiyorsa, orta segment boşsa VEYA
    `path_containment.validate_segment()`'ten geçemiyorsa. Sabit-uzunluk
    prefix/suffix dilimlemesi kullanılır (naif `.split(".")` DEĞİL) -
    document_id'nin kendisi bir nokta İÇERSE bile doğru parse edilir."""
    if not isinstance(target_ref, str):
        return None
    if not target_ref.startswith(_TARGET_REF_PREFIX) or not target_ref.endswith(_TARGET_REF_SUFFIX):
        return None
    middle = target_ref[len(_TARGET_REF_PREFIX):-len(_TARGET_REF_SUFFIX)]
    if not middle:
        return None
    try:
        _path_containment.validate_segment(middle)
    except _path_containment.PathContainmentError:
        return None
    return middle


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


def _derive_reviews_dir(module, case_root_real: Path, case_id: str, document_id: str) -> Path:
    return _verify_nested(module, case_root_real, case_id, module.get_reviews_dir(case_id, document_id))


def _derive_pending_path(module, case_root_real: Path, case_id: str, document_id: str) -> Path:
    return _verify_nested(module, case_root_real, case_id, module.get_pending_path(case_id, document_id))


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


def _validate_identity_payload_shape(identity_payload) -> bool:
    """Şekil/schema doğrulaması - bağımsız kod, facade ile PAYLAŞILMAZ.
    Herhangi bir ihlal False döner - bu TEK BAŞINA fail-closed bir "bu
    kayıt eşleşmiyor" sonucudur, TÜM taramayı poison ETMEZ (containment-
    unsafe/unparseable dosyanın TÜM taramayı durdurduğu ayrı kuraldan
    BİLİNÇLİ olarak FARKLIDIR)."""
    if not isinstance(identity_payload, dict):
        return False
    if set(identity_payload.keys()) != {
        "manifest_version", "document_id", "manifest", "generation_mode", "model_id",
        "engine_version", "prompt_agent_version",
    }:
        return False
    if identity_payload.get("manifest_version") != _MANIFEST_VERSION:
        return False
    # Bu ailede DETERMİNİSTİK MOD YOKTUR - yalnız "agent" geçerlidir
    # (beş/iki ailenin precedent'inde "deterministic"/"agent" ikisi de
    # geçerliyken, burada TEK bir geçerli değer vardır).
    if identity_payload.get("generation_mode") != "agent":
        return False
    if not _nonblank(identity_payload.get("document_id")):
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
    if len(manifest) != len(_EXPECTED_MANIFEST_NAMES):
        return False

    seen_names = set()
    for container in manifest:
        if not isinstance(container, dict):
            return False
        if set(container.keys()) != {"logical_name", "state", "files"}:
            return False
        logical_name = container.get("logical_name")
        if logical_name not in _EXPECTED_MANIFEST_NAMES or logical_name in seen_names:
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

    if seen_names != _EXPECTED_MANIFEST_NAMES:
        return False

    return True


def _audit_record_matches(
    record: dict, *,
    idempotency_key: str, resource_key: str, action_family: str, document_id: str,
    target_ref: str, target_state: str, actor_label: str, pending_sha256: str,
    entry_pre_revision,
) -> bool:
    """TAM bağlama - eksik/boş/uyumsuz HERHANGİ bir değer False (asla
    otomatik kanıt, asla transitif kabul)."""
    if record.get("schema_version") != "1":
        return False
    if record.get("case_id") != resource_key[len("case:"):]:
        return False
    if record.get("document_id") != document_id:
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
        # Backup dosyası GERÇEKTEN mevcut, ve raw-byte hash'i eşleşir
        # olmak ZORUNDADIR - rollback backup'ı geri taşımışsa (yani
        # artık o konumda YOK) bu adım False döner.
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
    if not _validate_identity_payload_shape(identity_payload):
        return False

    # ÜÇ YÖNLÜ document_id bağlanması: parse edilen (`document_id`
    # parametresi, entry.target_ref'ten) == audit["document_id"]
    # (yukarıda zaten kontrol edildi) == identity_payload["document_id"].
    if identity_payload.get("document_id") != document_id:
        return False

    recomputed_input_digest = hashlib.sha256(_canonical_identity_bytes(identity_payload)).hexdigest()
    if recomputed_input_digest != record.get("input_digest"):
        return False

    # ERRATUM §E.3 SERTLEŞTİRMESİ: precedent'in yalnız DOLAYLI (idempotency_
    # key üzerinden) bıraktığı bağı burada AÇIK, literal bir kontrole
    # dönüştürür - journal'ın KENDİ değiştirilemez pre_revision kolonuna
    # DOĞRUDAN eşitlik, dolaylı korumanın YERİNE değil, ONA EK.
    if recomputed_input_digest != entry_pre_revision:
        return False

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


class FactExtractionReconciliationAdapter:
    """`generation.fact_extraction` için adapter. Salt-okunur; hiçbir
    file/DB mutasyonu yapmaz (Protocol kontratı)."""

    def __init__(self, module):
        self._module = module

    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if not entry.resource_key.startswith("case:"):
            raise UnexpectedResourceKeyShapeError(
                f"journal_id={entry.journal_id}: expected 'case:<case_id>', got {entry.resource_key!r}"
            )
        case_id = entry.resource_key[len("case:"):]

        document_id = _parse_document_id_from_target_ref(entry.target_ref)
        if document_id is None:
            return _DUAL_FALSE

        module = self._module
        try:
            case_root_real = _resolve_case_root_real(module, case_id)
            pending_verified = _derive_pending_path(module, case_root_real, case_id, document_id)
            reviews_verified = _derive_reviews_dir(module, case_root_real, case_id, document_id)
        except (NestedPathContainmentError, _path_containment.PathContainmentError):
            return _DUAL_FALSE

        pre_state_proof = self._compute_pre_state_proof(entry, pending_verified)
        post_state_proof = self._compute_post_state_proof(
            entry, case_root_real, pending_verified, reviews_verified, document_id,
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
        reviews_verified: Path, document_id: str,
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
                record,
                idempotency_key=entry.idempotency_key,
                resource_key=entry.resource_key,
                action_family=entry.action_family,
                document_id=document_id,
                target_ref=entry.target_ref,
                target_state=entry.target_state,
                actor_label=entry.actor_label,
                pending_sha256=current_sha,
                entry_pre_revision=entry.pre_revision,
            )
        ]
        if len(matches) != 1:
            return _PostStateProof(verified=False, observed_post_hash=None)
        return _PostStateProof(verified=True, observed_post_hash=current_sha)


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    """`generation.fact_extraction` ailesini var olan bir registry'ye
    ekler - `reconciliation_operator._default_registry_factory()`'nin
    YEDİNCİ kaynağı. Action-family string'i facade'in kendi `fact_
    extraction_action_family_for()`'undan gelir - drift imkânsız."""
    module = importlib.import_module(FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME["fact_extraction"])
    return registry.with_adapter(
        fact_extraction_action_family_for("fact_extraction"),
        FactExtractionReconciliationAdapter(module),
    )
