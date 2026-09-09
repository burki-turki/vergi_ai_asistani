# ============================================================
# VERGİ AI - ROW 19C-3b SLICE 2: PROMOTION RECONCILIATION ADAPTERS.
#
# `promotion.fact` / `promotion.timeline` journal satırları için
# `ui.services.mutation_registry.ReconciliationAdapter` implementasyonu
# + `register_into()` (reconciliation operator'ün merged registry'sine
# DÖRDÜNCÜ kaynak olarak eklenir: 10 approval + 24 review + 1
# drafting_request + 2 promotion = 37 routing key).
#
# BAĞIMSIZ KANIT İLKESİ (Layer A/B/2c adapters ile aynı): bu modül
# `promotion_mutation_facade`'in doğrulama/karar fonksiyonlarını
# İMPORT ETMEZ (yalnız karar içermeyen `PROMOTION_ROW_KEY_TO_MODULE_
# NAME` + `promotion_action_family_for` sabit/format yardımcıları
# paylaşılır - Layer A'nın adapters<-facade tek yönlü kenarının
# birebir aynısı); containment/snapshot/audit-eşleşme mantığı burada
# BAĞIMSIZ ikinci implementasyondur - birindeki bug diğerini maskeleyemez.
#
# KARAR KURALI (Row 19C-3b Slice 2 onaylı reconciliation kontratı):
#   - POST-STATE yalnız ŞU İKİSİ BİRLİKTE doğruysa verified sayılır:
#       (1) diskteki canonical hash, DETERMİNİSTİK beklenen canonical
#           hash ile eşleşiyor (writer modülünün kendi
#           `compute_expected_canonical_sha256()` saf yardımcısı, şu
#           anki pending'den - bu yalnız pending hâlâ satırın kendi
#           `pre_revision`'ına hash'leniyorsa anlamlıdır ve öyle
#           olduğu ayrıca kontrol edilir);
#       (2) reviews dizininin İÇERİK taramasında TAM BİR adet
#           full-binding eşleşen SUCCESS audit var (idempotency/
#           resource/pending-hash-alanı/canonical_sha256 + aile
#           bayrakları; timeline ROLLBACK audit'i asla eşleşmez).
#     Audit yok/bozuk/birden çok eşleşme -> canonical doğru GÖRÜNSE
#     BİLE otomatik completed YOK; karar aşağıdaki pre-state kanıtına
#     düşer. Pre-proof da tutmuyorsa dual-false (satır operatör
#     incelemesine bloklu kalır - T2b/F3 sınıfının onaylı fail-closed
#     maliyeti). DÜRÜST KÖŞE NOTU (bu dosyanın ilk gerçek-PG koşusunda
#     ampirik olarak tespit edildi): zaten-promote-edilmiş bir
#     pending'in OVERWRITE yeniden-promosyonu bayt-İDEMPOTENTTİR
#     (build_canonical + tek-kaynak serializer mevcut canonical'ı
#     birebir yeniden üretir); böyle bir denemenin audit-crash'i
#     pending+canonical'ı istek-anı pre-state'iyle bayt-özdeş bırakır
#     ve composite pre-proof MEŞRU olarak tutar -> çözüm `failed`
#     (pre_state_confirmed_unchanged) olur, dual-false değil. Bu bir
#     güvenlik açığı değildir: hiçbir içerik kaybolmamış/değişmemiştir
#     ve completed ASLA otomatik verilmez (test_promotion_mutation_
#     integration_postgres.py P6d bu köşeyi ayrıca sabitler).
#   - PRE-STATE yalnız güncel composite snapshot (bağımsız yeniden
#     hesap) satırın kendi `pre_hash`'ine EŞİTSE confirmed-unchanged
#     sayılır -> `failed` çözümü.
#   - İkisi de kanıtlanamıyorsa dual-false: journal satırı DEĞİŞMEZ.
#   - Containment/parse anomalisi HER ZAMAN dual-false'a düşer
#     (adapter kanıt RAPORLAR, asla tahmin etmez).
#
# SNAPSHOT FORMÜLÜ: facade'in `_SNAPSHOT_VERSION`/payload formülünün
# BİLİNÇLİ bağımsız kopyası - drift, iki implementasyonu aynı girdide
# karşılaştıran izole canary testiyle yakalanır
# (test_promotion_mutation_facade_isolated.py).
# ============================================================

from __future__ import annotations

import fnmatch
import hashlib
import importlib
import json
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import path_containment as _path_containment  # noqa: E402

from . import mutation_registry as mr
from .common import sha256_file
from .promotion_mutation_facade import (
    PROMOTION_ROW_KEY_TO_MODULE_NAME,
    promotion_action_family_for,
)


class NestedPathContainmentError(Exception):
    """Internal-only: containment helper'larından `gather_evidence()`'ın
    dual-false dönüşüne unwind sinyali - modül sınırını asla aşmaz."""


class UnexpectedResourceKeyShapeError(Exception):
    """`case:<case_id>` olmayan resource_key ile bu adapter'lara
    yönlenen satır - yapısal olarak ulaşılmaz backstop (Layer A
    adapter'ının aynı sınıfıyla aynı ruh)."""


_DUAL_FALSE = mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

# Facade formülünün BAĞIMSIZ kopyası - bkz. modül başlığı.
_SNAPSHOT_ABSENT = "__absent__"
_SNAPSHOT_PRESENT = "__present__"
_SNAPSHOT_VERSION = "row19c3b_slice2.v1"

_PENDING_HASH_AUDIT_FIELD = {
    "fact": "source_pending_sha256",
    "timeline": "pending_sha256",
}


def _compute_promotion_composite(pending_path: Path, canonical_path: Path) -> str:
    pending_sha256 = sha256_file(pending_path) or _SNAPSHOT_ABSENT
    canonical_presence = _SNAPSHOT_PRESENT if Path(canonical_path).exists() else _SNAPSHOT_ABSENT
    canonical_sha256 = sha256_file(canonical_path) or _SNAPSHOT_ABSENT
    payload = json.dumps(
        {
            "snapshot_version": _SNAPSHOT_VERSION,
            "pending_sha256": pending_sha256,
            "canonical_presence": canonical_presence,
            "canonical_sha256": canonical_sha256,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _resolve_case_root_real(module, case_id: str) -> Path:
    """Writer modülünün KENDİ `CASES_DIR`'ı çağrı anında okunur -
    facade'in helper'ının bağımsız kopyası."""
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


def _scan_audits(case_root_real: Path, reviews_dir_verified: Path):
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
        if not fnmatch.fnmatch(entry.name, "*.approval.json"):
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


def _audit_record_matches(row_key: str, record: dict, entry: mr.JournalEntrySnapshot,
                          current_canonical_sha256: str) -> bool:
    """TAM bağlama - facade'in `_audit_record_matches`'inin bağımsız
    kopyası; eksik/boş/uyumsuz HERHANGİ bir değer False."""
    if not _nonblank(record.get("mutation_idempotency_key")) or record.get("mutation_idempotency_key") != entry.idempotency_key:
        return False
    if not _nonblank(record.get("mutation_resource_key")) or record.get("mutation_resource_key") != entry.resource_key:
        return False
    if not _nonblank(entry.pre_revision):
        return False
    pending_field = _PENDING_HASH_AUDIT_FIELD[row_key]
    if not _nonblank(record.get(pending_field)) or record.get(pending_field) != entry.pre_revision:
        return False
    if not _nonblank(record.get("canonical_sha256")) or record.get("canonical_sha256") != current_canonical_sha256:
        return False
    if row_key == "fact":
        if record.get("decision") != "approved_for_canonical_use":
            return False
    else:
        if record.get("approved") is not True or record.get("rollback") is not False:
            return False
    return True


class PromotionReconciliationAdapter:
    """`promotion.fact` / `promotion.timeline` için tek adapter sınıfı -
    row_key + writer modülü construction'da sabitlenir. Salt-okunur;
    hiçbir file/DB mutasyonu yapmaz (Protocol kontratı)."""

    def __init__(self, module, row_key: str):
        self._module = module
        self._row_key = row_key

    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if not entry.resource_key.startswith("case:"):
            raise UnexpectedResourceKeyShapeError(
                f"journal_id={entry.journal_id}: expected 'case:<case_id>', got {entry.resource_key!r}"
            )
        case_id = entry.resource_key[len("case:"):]

        # target_ref'ten hedef çözümü - malformed target_ref bir veri
        # anomalisidir: dual-false (adapter bug'ı değil, kanıtsızlık).
        document_id = None
        if self._row_key == "fact":
            target_ref = entry.target_ref or ""
            if not (target_ref.startswith("fact.") and target_ref.endswith(".canonical")):
                return _DUAL_FALSE
            document_id = target_ref[len("fact."):-len(".canonical")]
            if not document_id:
                return _DUAL_FALSE
        else:
            if entry.target_ref != "timeline.canonical":
                return _DUAL_FALSE

        module = self._module
        try:
            case_root_real = _resolve_case_root_real(module, case_id)
            if self._row_key == "fact":
                _path_containment.validate_segment(document_id)
                raw_pending = module.get_pending_path(case_id, document_id)
                raw_canonical = module.get_canonical_path(case_id, document_id)
                raw_reviews = module.get_reviews_dir(case_id, document_id)
            else:
                raw_pending = module.get_pending_path(case_id)
                raw_canonical = module.get_canonical_path(case_id)
                raw_reviews = module.get_reviews_dir(case_id)
            pending_verified = _verify_nested(module, case_root_real, case_id, raw_pending)
            canonical_verified = _verify_nested(module, case_root_real, case_id, raw_canonical)
            reviews_verified = _verify_nested(module, case_root_real, case_id, raw_reviews)
        except (NestedPathContainmentError, _path_containment.PathContainmentError):
            return _DUAL_FALSE

        current_pending_sha = sha256_file(pending_verified)
        current_canonical_sha = sha256_file(canonical_verified)

        # ---- POST-STATE kanıtı (iki koşul BİRLİKTE). Kurulamazsa
        # dual-false'a KISA DEVRE YAPILMAZ - aşağıdaki, audit'ten
        # tamamen BAĞIMSIZ pre-state composite kanıtı yine denenir.
        # (Promotion idempotent içerik üretir: "canonical zaten
        # beklenen içerikte" durumu, canonical'ın DAHA ÖNCEKİ meşru bir
        # promotion'dan kalmış olmasıyla ayırt edilemez - bu yüzden
        # completed YALNIZ tam-bir bound audit ile verilir; ama aynı
        # durumda composite == pre_hash tutuyorsa pending+canonical'ın
        # istek anındakiyle AYNEN aynı olduğu kanıtlanmıştır ve doğru
        # çözüm `failed`dir - T1b sınırının gerçek durumu.) Yalnız
        # containment/scan ANOMALİSİ doğrudan dual-false'tur.
        if current_canonical_sha is not None:
            deterministic_ok = False
            if (
                _nonblank(entry.pre_revision)
                and current_pending_sha == entry.pre_revision
            ):
                try:
                    expected = module.compute_expected_canonical_sha256(pending_verified)
                except Exception:
                    expected = None
                deterministic_ok = expected is not None and expected == current_canonical_sha
            if deterministic_ok:
                try:
                    entries = _scan_audits(case_root_real, reviews_verified)
                except NestedPathContainmentError:
                    return _DUAL_FALSE
                if not any(record is None for _path, record in entries):
                    matches = [
                        (path, record) for path, record in entries
                        if _audit_record_matches(self._row_key, record, entry, current_canonical_sha)
                    ]
                    if len(matches) == 1:
                        return mr.ReconciliationEvidence(
                            post_state_verified=True,
                            pre_state_confirmed_unchanged=False,
                            observed_post_hash=current_canonical_sha,
                        )
                # Parse edilemeyen aday VEYA 0/>1 eşleşme: canonical
                # deterministik doğru GÖRÜNSE bile otomatik completed
                # YOK - pre-state kanıtına düşülür.

        # ---- PRE-STATE kanıtı: güncel composite == satırın pre_hash'i. ----
        if _nonblank(entry.pre_hash):
            current_composite = _compute_promotion_composite(pending_verified, canonical_verified)
            if current_composite == entry.pre_hash:
                return mr.ReconciliationEvidence(
                    post_state_verified=False, pre_state_confirmed_unchanged=True,
                )

        return _DUAL_FALSE


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    """İki promotion ailesini var olan bir registry'ye ekler -
    `reconciliation_operator._default_registry_factory()`'nin DÖRDÜNCÜ
    kaynağı. Action-family string'leri facade'in kendi
    `promotion_action_family_for()`'undan gelir - drift imkânsız."""
    for row_key, module_name in PROMOTION_ROW_KEY_TO_MODULE_NAME.items():
        module = importlib.import_module(module_name)
        registry = registry.with_adapter(
            promotion_action_family_for(row_key),
            PromotionReconciliationAdapter(module, row_key),
        )
    return registry
