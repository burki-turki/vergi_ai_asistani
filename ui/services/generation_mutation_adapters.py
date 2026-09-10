# ============================================================
# VERGİ AI - ROW 19C-3c-i: DETERMINISTIC GENERATION RECONCILIATION
# ADAPTERS.
#
# `generation.deadline` / `generation.timeline` journal satırları için
# `ui.services.mutation_registry.ReconciliationAdapter` implementasyonu
# + `register_into()` (reconciliation operator'ün merged registry'sine
# BEŞİNCİ kaynak olarak eklenir: 10 approval + 24 review + 1
# drafting_request + 2 promotion + 2 generation = 39 routing key).
#
# BAĞIMSIZ KANIT İLKESİ (Layer A/B/promotion adapters ile aynı): bu
# modül `generation_mutation_facade`'in doğrulama/karar fonksiyonlarını
# İMPORT ETMEZ (yalnız karar içermeyen `GENERATION_ROW_KEY_TO_MODULE_
# NAME` + `generation_action_family_for` sabit/format yardımcıları
# paylaşılır - Layer A/promotion'ın adapters<-facade tek yönlü
# kenarının birebir aynısı); containment/snapshot/audit-eşleşme mantığı
# burada BAĞIMSIZ ikinci implementasyondur - birindeki bug diğerini
# maskeleyemez.
#
# ROW 19C-3c-i FINAL ERRATUM - PRE-STATE VE POST-STATE KANITI TAMAMEN
# BAĞIMSIZ HESAPLANIR (bu adapter'ın var oluş nedeni)
# -------------------------------------------------------------------
# Generation'ın pending çıktısı DETERMİNİSTİK DEĞİLDİR (`generated_at`)
# - bu yüzden promotion'ın "canonical zaten deterministik doğru
# İÇERİKTE" post-state kısayolu burada YOKTUR/OLAMAZ; post-state
# YALNIZ tam-bağlama eşleşen bir success audit ile kurulabilir.
# Bu asimetri, pre-state ve post-state kanıtının birbirini
# MASKELEMEMESİNİ ÖZELLİKLE KRİTİK kılar: bir ilk-yazma (first-write)
# denemesi hiçbir şey üretmeden çökerse, pending hem ÖNCESİNDE hem
# ŞİMDİ yoktur - doğru kanıt post=False (üretilmiş bir şey YOK) AMA
# pre=True (hiçbir şey DEĞİŞMEDİ, hâlâ yok) olmalıdır; bu ikisi
# `_compute_pre_state_proof()`/`_compute_post_state_proof()` adlı İKİ
# TAMAMEN AYRI fonksiyonla hesaplanır - hiçbiri diğerinin sonucuna
# veya erken-çıkışına bakmaz, hiçbiri diğerini kısa devre yapmaz.
# `_compute_pre_state_proof()` HİÇBİR ZAMAN JSON parse etmez, audit
# taramaz veya girdi dosyası (case/timeline/ruleset/provisions) okumaz
# - YALNIZ journal satırının KENDİ kayıtlı `pre_revision`'ı (=input_
# digest, YENİDEN HESAPLANMAZ) + mevcut pending'in containment-
# doğrulanmış ham-bayt varlığı/hash'i. `_compute_post_state_proof()`
# HİÇBİR ZAMAN pre-state kanıtına bakmaz - yalnız pending varlığı +
# audit taraması + tam-bağlama eşleşmesi. Bir JSONDecodeError/parse
# hatası (audit taramasında) BU FONKSİYONUN KENDİ SINIRI İÇİNDE
# yakalanır ve yalnız post=False üretir - pre-state fonksiyonuna ASLA
# SIZMAZ (zaten pre-state fonksiyonu audit dosyalarına hiç bakmaz).
#
# KARAR KURALI:
#   - PRE-STATE: `entry.pre_hash` + `entry.pre_revision` mevcutsa VE
#     candidate composite (yalnız `entry.pre_revision` + mevcut pending
#     presence/hash'ten - `_SNAPSHOT_VERSION` facade'in formülüyle
#     BİREBİR eşleşir) `entry.pre_hash`'e eşitse `confirmed_unchanged=
#     True`; aksi halde False (asla exception, asla tahmin).
#   - POST-STATE: pending mevcut/normal-dosya DEĞİLSE False; audit
#     taraması containment hatası VERİRSE False; parse edilemeyen
#     HERHANGİ bir aday varsa False; tam-bağlama eşleşen audit sayısı
#     tam 1 DEĞİLSE False; hepsi tutuyorsa True (observed_post_hash =
#     mevcut pending sha256).
#   - `gather_evidence()` bu iki BAĞIMSIZ sonucu BİRLEŞTİRİR - hiçbir
#     dal diğerini normal akışta ETKİLEMEZ. Containment/parse
#     anomalisi kendi fonksiyonunun sınırı içinde dual-false'a düşer;
#     `UnexpectedResourceKeyShapeError` yalnız GERÇEKTEN ulaşılamaz bir
#     yapısal durumda (bu registry'nin KENDİ routing'i zaten `case:`
#     resource_key'i garantiler) fırlatılır - adapter-içi programlama
#     hatası sınıfı, kanıt eksikliği DEĞİL.
#
# SNAPSHOT FORMÜLÜ: facade'in `generation_mutation_facade._SNAPSHOT_
# VERSION`/payload formülünün BİLİNÇLİ bağımsız kopyası - drift, iki
# implementasyonu aynı girdide karşılaştıran izole canary testiyle
# yakalanır (test_generation_mutation_facade_isolated.py). Formül
# BİLİNÇLİ olarak `generation_parameters_digest`'i İÇERMEZ - bkz.
# `generation_mutation_facade._compute_generation_snapshot()`'ın kendi
# docstring'i: reconciliation anında artık mevcut olmayabilecek
# orijinal ruleset/provisions baytlarına asla dayanamaz.
#
# ROW 19C-3c-i DEADLINE REVISION-IDENTITY REMEDIATION - bu dosya
# FONKSİYONEL olarak DEĞİŞMEDİ: `entry.pre_revision` bu modülde HER
# ZAMAN journal'ın kendi kayıtlı, OPAK bir string'i olarak kullanılır
# (`_compute_pre_state_proof()` onu ASLA case/timeline/ruleset/
# provisions ham baytlarından yeniden inşa etmeye ÇALIŞMAZ) - facade'in
# `_compute_deadline_input_digest()`'inin artık ruleset/provisions'ı DA
# içermesi (bkz. `generation_mutation_facade.py`'nin kendi
# "REMEDIATION NOTU") bu yüzden bu dosyanın pre-state/post-state
# kanıt mantığını hiçbir şekilde ETKİLEMEZ - yalnız journal'a
# YAZILACAK `pre_revision` DEĞERİNİN kendisi (facade tarafında)
# değişti, bu değerin BURADA nasıl KULLANILDIĞI değişmedi.
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
from .generation_mutation_facade import (
    GENERATION_ROW_KEY_TO_MODULE_NAME,
    generation_action_family_for,
)


class NestedPathContainmentError(Exception):
    """Internal-only: containment helper'larından `gather_evidence()`'ın
    dual-false dönüşüne unwind sinyali - modül sınırını asla aşmaz."""


class UnexpectedResourceKeyShapeError(Exception):
    """`case:<case_id>` olmayan resource_key ile bu adapter'lara
    yönlenen satır - yapısal olarak ulaşılmaz backstop (Layer A/
    promotion adapter'larının AYNI sınıfıyla aynı ruh)."""


_DUAL_FALSE = mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

# Facade formülünün BAĞIMSIZ kopyası - bkz. modül başlığı. Facade'in
# KENDİ `_SNAPSHOT_VERSION`'ıyla (generation_mutation_facade.py)
# BİREBİR aynı string olmak ZORUNDADIR - izole canary testi bunu ayrıca
# kanıtlar.
_SNAPSHOT_ABSENT = "__absent__"
_SNAPSHOT_PRESENT = "__present__"
_SNAPSHOT_VERSION = "row19c3ci.generation.v1"


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


def _audit_record_matches(record: dict, *, idempotency_key: str, resource_key: str, action_family: str, pending_sha256: str) -> bool:
    """TAM bağlama - facade'in `_audit_record_matches`'inin bağımsız
    kopyası; eksik/boş/uyumsuz HERHANGİ bir değer False."""
    if not _nonblank(record.get("mutation_idempotency_key")) or record.get("mutation_idempotency_key") != idempotency_key:
        return False
    if not _nonblank(record.get("mutation_resource_key")) or record.get("mutation_resource_key") != resource_key:
        return False
    if record.get("action_family") != action_family:
        return False
    if not _nonblank(record.get("pending_sha256")) or record.get("pending_sha256") != pending_sha256:
        return False
    if record.get("outcome") != "generated":
        return False
    return True


def _compute_candidate_pre_hash(input_digest: str, pending_presence: str, pending_sha256: str) -> str:
    """`generation_mutation_facade._compute_generation_snapshot()`'ın
    composite formülünün BAĞIMSIZ kopyası - `_SNAPSHOT_VERSION` string'i
    HER İKİ modülde de BİREBİR aynı olmak zorundadır (drift canary
    testi)."""
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
    if row_key == "deadline":
        return target_ref.startswith("deadline.") and target_ref.endswith(".pending")
    return target_ref == "timeline.pending"


class GenerationReconciliationAdapter:
    """`generation.deadline` / `generation.timeline` için tek adapter
    sınıfı - row_key + writer modülü construction'da sabitlenir.
    Salt-okunur; hiçbir file/DB mutasyonu yapmaz (Protocol kontratı)."""

    def __init__(self, module, row_key: str):
        self._module = module
        self._row_key = row_key

    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if not entry.resource_key.startswith("case:"):
            raise UnexpectedResourceKeyShapeError(
                f"journal_id={entry.journal_id}: expected 'case:<case_id>', got {entry.resource_key!r}"
            )
        case_id = entry.resource_key[len("case:"):]

        # Malformed target_ref bir veri anomalisidir: dual-false (adapter
        # bug'ı DEĞİL, kanıtsızlık).
        if not _target_ref_matches_row_key(self._row_key, entry.target_ref):
            return _DUAL_FALSE

        module = self._module
        try:
            case_root_real = _resolve_case_root_real(module, case_id)
            pending_verified = _verify_nested(module, case_root_real, case_id, module.get_pending_path(case_id))
            reviews_verified = _verify_nested(module, case_root_real, case_id, module.get_reviews_dir(case_id))
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
        """BAĞIMSIZ: JSON ASLA parse edilmez, audit dizini ASLA
        taranmaz, HİÇBİR girdi dosyası (case/timeline/ruleset/
        provisions) OKUNMAZ. Yalnız `entry.pre_revision` (=kayıtlı
        input_digest, YENİDEN HESAPLANMAZ) + mevcut pending'in
        containment-doğrulanmış ham-bayt varlığı/hash'i."""
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
        """BAĞIMSIZ: pre-state kanıtına/sonucuna ASLA bakmaz. Bir
        JSONDecodeError/parse hatası (audit taramasında) bu fonksiyonun
        KENDİ sınırı içinde yakalanır ve yalnız `verified=False` üretir
        - hiçbir zaman exception olarak dışarı sızmaz, hiçbir zaman
        pre-state kanıtını ETKİLEMEZ."""
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
                pending_sha256=current_sha,
            )
        ]
        if len(matches) != 1:
            return _PostStateProof(verified=False, observed_post_hash=None)
        return _PostStateProof(verified=True, observed_post_hash=current_sha)


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    """İki generation ailesini var olan bir registry'ye ekler -
    `reconciliation_operator._default_registry_factory()`'nin BEŞİNCİ
    kaynağı. Action-family string'leri facade'in kendi `generation_
    action_family_for()`'undan gelir - drift imkânsız."""
    for row_key, module_name in GENERATION_ROW_KEY_TO_MODULE_NAME.items():
        module = importlib.import_module(module_name)
        registry = registry.with_adapter(
            generation_action_family_for(row_key),
            GenerationReconciliationAdapter(module, row_key),
        )
    return registry
