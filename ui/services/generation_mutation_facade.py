# ============================================================
# VERGİ AI - ROW 19C-3c-i: DETERMINISTIC GENERATION MUTATION FACADE.
#
# Deadline (Row 8, `src/deadline_engine.run_engine()`) ve Timeline
# (Row 7, `src/timeline_engine.run_timeline_engine()`) pending-
# generation writer'larını mutation coordinator/journal altyapısına
# bağlayan, AYRI ve BAĞIMSIZ facade - Layer A (`mutation_approval_
# facade.py`), Layer B (`review_mutation_facade.py`), drafting-request
# ve promotion (`promotion_mutation_facade.py`) facade'lerinin HİÇBİRİ
# GENİŞLETİLMEMİŞTİR (repo emsali: her yeni kontrat şekli kendi
# facade+adapters çiftini alır). Bu facade en çok `promotion_mutation_
# facade.py`'ye benzer (CLI-only, HTTP route yok, dual authz, composite
# pre-state snapshot) ama YAPISAL OLARAK farklıdır: promotion bir
# PRE-EXISTING pending'i canonical'a PROMOTE eder (operatör
# `--expected-hash` ile pending'i işaret eder); generation ise YENİ bir
# pending ÜRETİR - işaret edilecek bir "önceki" pending YOKTUR.
# `pre_revision` bu yüzden operatör beyanı DEĞİL, facade'in canonical
# case içeriğinden BİZZAT hesapladığı `input_digest`'tir.
#
# ACTION FAMILY'LER: `generation.deadline` / `generation.timeline`.
# Kanal ayrımı YOK - bu iki aile YALNIZ CLI'dan erişilebilir
# (`python -m ui.cli_mutate generation ...`); web mutasyon yüzeyi
# YOKTUR (bilinçli kapsam dışı).
#
# DIGEST/IDENTITY MODELİ (Row 19C-3c-i DEADLINE REVISION-IDENTITY
# REMEDIATION - bkz. aşağıdaki "REMEDIATION NOTU"; bu, ORİJİNAL final
# scope kararının YERİNE GEÇEN, DÜZELTİLMİŞ kontrattır):
#   - `pre_revision` = `input_digest`:
#       * deadline için case.json + canonical timeline.json + (kilit
#         altında yakalanan) ruleset + provisions ham baytlarının
#         İÇERİK-ONLY hash'i (`_compute_deadline_input_digest`,
#         `digest_version="row19c3ci.deadline.v2"`). Ruleset/provisions
#         bu digest'e DAHİLDİR - case/timeline aynı kalsa bile ruleset
#         veya provisions içeriği değiştiğinde `input_digest` (ve
#         dolayısıyla `idempotency_key`) DEĞİŞİR; bu, kalıcı-UNIQUE
#         `idempotency_key`nin meşru bir yeniden-üretim denemesini
#         yanlışlıkla kalıcı olarak bloke ETMEMESİNİ sağlar (bkz.
#         REMEDIATION NOTU).
#       * timeline için taranan TÜM document.json + facts.json ham
#         baytlarının içerik-only hash'i - DEĞİŞMEDİ.
#       * `anchor_event_id` HİÇBİR ZAMAN digest'e girmez - yalnız
#         `target_ref`'e (`deadline.<anchor>.pending`) girer, böylece
#         aynı case içeriği üzerinde farklı anchor'lar BAĞIMSIZ
#         operasyon slotlarıdır (yanlış bir kalıcı IdempotencyConflict
#         üretilmez).
#   - `secondary_input_hash` = `generation_parameters_digest`:
#       * deadline için YALNIZ holiday_dates + calendar_complete +
#         judicial_recess_applicable'ın deterministik hash'i
#         (`_compute_deadline_generation_parameters_digest`,
#         `digest_version="row19c3ci.deadline_params.v2"`) - ruleset/
#         provisions ARTIK BU DİGEST'TE DEĞİLDİR (input_digest'e
#         TAŞINDI, bkz. REMEDIATION NOTU).
#       * timeline için HER ZAMAN `None` (timeline'ın böyle bir "tuning
#         parametresi" kavramı yoktur).
#   - Sonuç: aynı kimlik (aynı case/timeline/ruleset/provisions içeriği
#     + aynı anchor) + farklı generation_parameters_digest (farklı
#     holiday/calendar/recess) -> mevcut `IdempotencyConflictError`
#     mekanizmasına düşer (Row 19C-2b'nin `secondary_input_hash`
#     emsaliyle birebir aynı) - bu davranış DEĞİŞMEDİ.
#
# REMEDIATION NOTU (bu turda düzeltilen HIGH kusur): ORİJİNAL
# implementasyonda `input_digest` yalnız case.json+timeline.json'dan,
# `generation_parameters_digest` ise ruleset+provisions+holiday/
# calendar/recess'ten türetiliyordu. `idempotency_key`, `mutation_guard.
# _identity_fields()` uyarınca YALNIZ `pre_revision`'dan (input_digest)
# türer, `secondary_input_hash`'ten TÜREMEZ (yalnız
# `request_fingerprint`'e girer) - bu yüzden ruleset/provisions içeriği
# değişip case/timeline aynı kaldığında `idempotency_key` DEĞİŞMİYORDU;
# `mutation.mutation_journal.idempotency_key` KOŞULSUZ ve KALICI olarak
# UNIQUE olduğundan (`failed` dahil, `src/mutation_guard.py`), bu durum
# meşru bir ikinci generation denemesinin (aynı case/timeline, farklı/
# güncellenmiş ruleset veya provisions) yanlışlıkla kalıcı bir
# `IdempotencyConflictError`'a (fingerprint uyuşmazlığı - aynı key,
# farklı fingerprint) düşmesine yol açabiliyordu. Düzeltme: ruleset/
# provisions ham baytları artık `input_digest`'in (dolayısıyla
# `pre_revision`/`idempotency_key`'in) BİR PARÇASI; `generation_
# parameters_digest` artık YALNIZ holiday/calendar/recess'i taşır. Bu
# değişiklik yalnız bu iki fonksiyonun İÇ formülünü değiştirir - `_compute_
# generation_snapshot()`'ın composite `pre_hash` formülü (input_digest +
# pending presence/hash) ve `generation_mutation_adapters.py`'nin
# reconciliation mantığı DEĞİŞMEDİ (ikisi de `input_digest`'i HER ZAMAN
# journal satırının kendi kayıtlı `pre_revision`'ından OPAK bir string
# olarak alır, hiçbir zaman ham ruleset/provisions baytlarından YENİDEN
# TÜRETMEZ - bkz. bu dosyanın `_compute_generation_snapshot()`'ının
# kendi docstring'i). Non-generation ailelerin (approval/review/
# promotion/drafting_request) fingerprint/idempotency davranışı bu
# değişiklikten ETKİLENMEZ - `mutation_guard.py` bu turda
# DEĞİŞTİRİLMEDİ.
#   - KALICI-BAŞARISIZ-DENEME SONUCU (kullanıcıya açıkça bildirilir,
#     operasyonel bir sürpriz OLARAK DEĞİL): `idempotency_key` KOŞULSUZ
#     ve `mutation.mutation_journal`'ın TÜM geçmişi boyunca UNIQUE'tir
#     (`failed` dahil - `src/mutation_guard.py`, DEĞİŞTİRİLMEDİ). Bir
#     generation denemesi `reconciled_failed_*` olarak çözülürse, AYNI
#     actor + AYNI case/timeline/ruleset/provisions içeriği + AYNI
#     anchor/parametre kombinasyonu ile yeniden deneme KALICI OLARAK
#     `PriorAttemptFailedError` üretir - promotion'ın aksine (orada her
#     yeni pending üretimi `pre_revision`'ı doğal olarak tazeler),
#     generation'ın kendi `pre_revision`'ı İÇERİK-türevlidir: operatör
#     ya case/timeline/ruleset/provisions içeriğinde GERÇEK bir
#     değişiklik bekler, ya da farklı bir anchor/parametre
#     kombinasyonuyla dener - üçüncü bir kaçış yolu YOKTUR. Bu,
#     onaylanan (ve bu turda düzeltilen) identity modelinin doğrudan ve
#     BİLİNÇLİ bir sonucudur.
#
# GLOBAL KAYNAK SNAPSHOT (yalnız deadline; Row 19A'nın onaylı RAG-bundle
# "stale-sonuç kuralı"nın generation karşılığı):
#   1. Pre-lock: ruleset/provisions ham baytları best-effort okunur
#      (yalnız ön-gösterge; otoriter DEĞİLDİR).
#   2. Case kilidi alınır.
#   3. `precondition_callback` (kilit ALTINDA): ruleset/provisions
#      YENİDEN okunur - baytlar SADECE BELLEĞE (closure box) alınır,
#      HİÇBİR dosya YAZILMAZ, VE (REMEDIATION - bkz. yukarıdaki
#      "REMEDIATION NOTU") bu taze baytlar `ul_input_digest`'in
#      hesaplanmasına DOĞRUDAN girer (artık yalnız ayrı bir
#      `generation_parameters_digest` race-tespitinin girdisi
#      DEĞİLLER). Composite snapshot (input_digest'i İÇEREN)
#      pre-lock değeriyle karşılaştırılır (uyuşmazlık ->
#      `PreconditionRaceDetectedError`/`StaleViewError`, SIFIR journal
#      satırı) - ruleset/provisions kilit beklenirken değişirse bu TEK
#      karşılaştırma zaten yakalar; ayrı bir `generation_parameters_
#      digest` eşitlik kontrolüne artık GEREK YOKTUR (holiday_dates/
#      calendar_complete/judicial_recess_applicable saf çağıran
#      parametreleridir, dosyadan OKUNMAZ - kilit beklenirken
#      değişebilecek bir durumları yoktur).
#   4. `_insert_prepared` / `_mark_executing` (mevcut coordinator,
#      DEĞİŞTİRİLMEDİ).
#   5. `writer_callback` (kilit ALTINDA, `executing` sonrası): YALNIZ
#      BURADA yakalanan baytlar bir `TemporaryDirectory`'ye
#      materialize edilir, katı biçimde yeniden hash'lenip yakalanan
#      baytla EŞİTLENİR, `deadline_engine.run_engine()` bu temp
#      path'lerle çağrılır; `run_engine()`'e geçen `pre_commit_
#      callback` gerçek ÜRETİM ruleset/provisions dosyalarını BİR KEZ
#      DAHA (atomic write'tan HEMEN önce) okuyup yakalanan baytla
#      eşitler - farklıysa `GlobalResourceStaleError`, sıfır
#      değişiklik. TemporaryDirectory `finally` içinde HER KOŞULDA
#      temizlenir.
#   6. Bu protokol LİNEARİZE EDİLEBİLİR OLARAK İDDİA EDİLMEZ - `pre_
#      commit_callback`'in kendi kontrolü ile GERÇEK `os.replace()`
#      arasında kalan dar pencere, Row 19A'nın T15 kararı uyarınca Row
#      19D (OS ACL / service identity) borcu olarak AÇIKÇA KALIR; bu
#      dar pencere gelecekteki bir maintenance/global-coordination
#      turuna bırakılmıştır, Row 19D'ye DEĞİL "asla kapanmayacak"
#      olarak da SUNULMAZ.
#
# TIMELINE SABİT DOĞRULANMIŞ YOL-SETİ (fixed, containment-verified
# path-set handoff): `_scan_timeline_verified_inputs()` case kilidi
# ALTINDA `documents/` ağacını SEGMENT-SEGMENT tarar (üye-adı ->
# containment -> exact-parent -> is_dir/is_file sırasıyla, HERHANGİ bir
# ham `Path.glob()` KULLANILMADAN); kaçan/kırık/döngüsel HERHANGİ bir
# eşleşen-şekilli giriş TÜM taramayı fail-closed durdurur (sıfır journal
# satırı, sıfır writer çağrısı) - `path_containment.list_contained_dir()`
# BİLİNÇLİ olarak KULLANILMAZ (o fonksiyon güvensiz çocukları SESSİZCE
# atlar, bu taramanın gerektirdiği fail-closed semantiği SAĞLAMAZ). Bu
# tarama SONUCU (`document_paths`/`facts_paths`) case kilidi altında
# `timeline_validator.load_document_index()`/`load_canonical_fact_
# index()`'in YENİ `document_paths=`/`facts_paths=` override
# parametrelerine DOĞRUDAN geçirilir - yazar KENDİ raw glob'una ASLA
# geri düşmez (ayrı bir izole test, `Path.glob()`'u override
# verildiğinde çağrılırsa raise eden bir monkeypatch ile bunu KANITLAR).
# Case kilidi yalnız BU projenin meşru mutasyon yollarını durdurur -
# kilit BEKLENİRKEN bir yerel dosya sistemi aktörünün doğrudan içerik
# değişikliğini ÖNLEMEZ (Row 19A'nın T15 kararı, Row 19D borcu; bu
# facade bu pencereyi KAPATTIĞINI İDDİA ETMEZ).
#
# WRITER-ROOT KONTRATI: writer containment kökü ÇAĞRI ANINDA writer
# modülünün KENDİ `CASES_DIR` attribute'undan okunur (`deadline_engine.
# CASES_DIR` / `timeline_engine.CASES_DIR` / `deadline_validator.
# CASES_DIR`), asla cache'lenmez/default-arg'a bağlanmaz - promotion
# facade'inin AYNI kararı.
#
# POST-STATE: generation'ın pending çıktısı DETERMİNİSTİK DEĞİLDİR
# (`generated_at` her çalıştırmada değişir) - bu yüzden promotion'ın
# `compute_expected_canonical_sha256()` deseni burada YOKTUR/OLAMAZ.
# Yazarın KENDİ raporladığı `pending_sha256` (gerçek disk baytlarından,
# `deadline_engine.write_pending()`/`timeline_engine.write_pending()`
# içinde hesaplanır) TEK doğruluk kaynağıdır - facade bunu bağımsızca
# ÖNCEDEN HESAPLAYAMAZ, sadece yazarın raporunu `observed_post_hash`
# olarak taşır.
#
# AUDIT/REPLAY: her iki yazar da KENDİ `*.generation_audit.json`
# kaydını (case-scoped `generation_reviews/` dizini, `fact_approval.
# _write_audit_record_excl()` ile AYNI `O_CREAT|O_EXCL` + zaman damgalı
# taban ad deseni) yazarın KENDİ atomic-write+rollback sınırı İÇİNDE
# üretir. Completed safe-replay corroboration, taze containment +
# journal `observed_post_hash` == taze pending sha + `generation_
# reviews/` içerik taramasında TAM BİR adet full-binding eşleşen audit
# gerektirir - eşleşme HER ZAMAN içerikten yapılır, addan/mtime'dan
# asla.
#
# NOT (reconciliation adapter'la PAYLAŞILMAYAN mantık): bu facade'in
# KENDİ replay-corroboration fonksiyonu (`_verify_completed_generation_
# replay_binding`) yalnız `completed` durumundaki bir satırı YENİDEN
# DOĞRULAR (sonuç zaten BİLİNİYOR) - bu yüzden pre-state/post-state
# kanıtını AYRI hesaplamak ZORUNDA DEĞİLDİR (promotion'ın kendi replay
# fonksiyonuyla AYNI basitlik). Pre-state/post-state kanıtının TAMAMEN
# BAĞIMSIZ iki fonksiyona bölünmesi ZORUNLULUĞU YALNIZ `generation_
# mutation_adapters.py`'nin `gather_evidence()`'ına aittir - orada
# gerçek SONUÇ BİLİNMEZ (prepared/executing/reconciliation_required bir
# satır için); bu ayrım Row 19C-3c-i final erratum'unun konusudur, bu
# dosyanın konusu DEĞİLDİR.
# ============================================================

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mutation_guard import MutationIntent, compute_idempotency_key  # noqa: E402
import path_containment as _path_containment  # noqa: E402

from . import authz as _authz
from . import mutation_coordinator as _mutation_coordinator
from . import mutation_lock as _mutation_lock
from .common import (
    ApprovalUiError,
    PreconditionRaceDetectedError,
    StaleViewError,
    sha256_file,
)

# ----------------------------------------------------------------
# Kapalı row_key -> writer modülü eşlemesi. Layer A/promotion'ın kendi
# sözlüklerinden BİLİNÇLİ olarak AYRI (repo emsali - her kontrat şekli
# kendi kapalı eşlemesini taşır).
# ----------------------------------------------------------------

GENERATION_ROW_KEY_TO_MODULE_NAME = {
    "deadline": "deadline_engine",
    "timeline": "timeline_engine",
}

_ACTION_FAMILY_PREFIX = "generation."

_CASE_RESOURCE_KEY_PREFIX = "case:"

TARGET_STATE = "generated"

COMPLETED_JOURNAL_STATE = "completed"

_logger = logging.getLogger("vergi_ai.generation_mutation_facade")


def _log_critical_safely(message: str) -> None:
    """mutation_approval_facade/promotion_mutation_facade ile AYNI ilke:
    logging'in kendi hatası, aktif sonucu/istisnayı asla maskeleyemez."""
    try:
        _logger.critical(message)
    except Exception:
        pass


def generation_action_family_for(row_key: str) -> str:
    """`generation.<row_key>` - hem bu modülün MutationIntent'i hem
    `generation_mutation_adapters.register_into()` BU fonksiyonu
    çağırır; iki taraf farklı string'lere kayamaz."""
    return f"{_ACTION_FAMILY_PREFIX}{row_key}"


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ----------------------------------------------------------------
# Hata sınıfları - HEPSİ `ApprovalUiError` alt sınıfıdır, böylece
# `ui.cli_mutate._is_known_domain_error()` (ApprovalUiError'ı zaten
# tanır) SIFIR değişiklikle temiz tek-satır hata üretir.
# ----------------------------------------------------------------


class GenerationArgumentError(ApprovalUiError):
    """Kullanım-şekli/argüman sözleşmesi ihlali (timeline'da anchor/
    holiday/calendar/recess verilmiş, deadline'da anchor eksik, boş
    expected_input_digest, ...) - HERHANGİ bir DB/filesystem I/O'sundan
    ÖNCE fırlatılır."""


class GenerationInputContainmentError(ApprovalUiError):
    """Writer-root/nested/girdi-taraması containment doğrulaması
    başarısız (kaçan/kırık/döngüsel link, kök doğrulanamadı, in-tree
    alias, beklenen kapsam dışı yol, geçersiz segment adı). Yalnız
    writer çağrılmadan önce (pre-lock veya precondition) ya da replay
    corroboration sırasında fırlatılır."""


class GenerationSnapshotMaterializationError(ApprovalUiError):
    """Global kaynak (ruleset/provisions) snapshot'ının TemporaryDirectory'ye
    materialize edilmesi sırasında yeniden-hash bütünlük kontrolü
    başarısız - writer sınırı GEÇİLDİĞİ için coordinator bu istisnayı
    reconciliation_required'a çevirir."""


class GlobalResourceStaleError(ApprovalUiError):
    """`pre_commit_callback`'in son canlı kontrolü: gerçek üretim
    ruleset/provisions dosyaları, case kilidi altında yakalanan
    baytlardan atomic write'a kadar olan sürede DEĞİŞTİ. Writer sınırı
    GEÇİLDİĞİ için coordinator bu istisnayı reconciliation_required'a
    çevirir - asla sessiz başarı."""


class GenerationResolvedCaseIdMismatchError(ApprovalUiError):
    """İç (kilit-altı) authz'ın çözdüğü case_id, dış (pre-lock)
    authz'ınkinden farklı - Layer A/promotion'ın AYNI fail-closed
    backstop'u."""


class GenerationAuditBindingVerificationFailedError(ApprovalUiError):
    """Safe-replay corroboration başarısız - ne doğrulanmış başarı ne
    doğrulanmış başarısızlık; insan reconciliation'ı gerekir (Layer A/
    promotion'ın AuditBindingVerificationFailedError'ının generation
    karşılığı)."""

    def __init__(self, *, journal_id: int, idempotency_key: str, reason: str):
        self.journal_id = journal_id
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(
            f"journal_id={journal_id}: generation safe-replay audit-binding verification "
            f"failed (idempotency_key={idempotency_key!r}): {reason}"
        )


# ----------------------------------------------------------------
# Writer-root / nested containment - bu modülün KENDİ bağımsız
# kopyaları (19C-2c/19C-3b Slice 2 çift-bağımsız-helper emsali;
# adapters kendi kopyasını taşır, iki taraf birbirinden import ETMEZ).
# Yalnız karar içermeyen `src/path_containment.py` primitive'leri
# paylaşılır.
# ----------------------------------------------------------------


def _resolve_module_case_root_real(module, case_id: str) -> Path:
    """Modülün KENDİ `CASES_DIR`'ı ÇAĞRI ANINDA okunur (asla cache/
    default-arg); `case_id` segment-doğrulanır ve case kökü strict/
    containment çözülür. Hata her nedende aynı generic sınıfa düşer
    (existence-blind: authz zaten önce koşmuştur)."""
    cases_dir = module.CASES_DIR
    try:
        _path_containment.validate_segment(case_id)
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise GenerationInputContainmentError(
            "Generation case kökü containment doğrulamasından geçemedi."
        ) from error


def _verify_nested(module, case_root_real: Path, case_id: str, raw_path) -> Path:
    """Modül getter'ının RAW `/`-join çıktısını, relative parçaları raw
    path'in kendisinden alarak `resolve_for_create()` üzerinden
    doğrulanmış gerçek konuma çevirir (mevcut hedef -> tam çözülmüş;
    henüz-yok hedef -> en derin doğrulanmış gerçek ata üzerine
    doğrulanmış join)."""
    cases_dir = module.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise GenerationInputContainmentError(
            "Generation yolu beklenen case kapsamı dışında."
        ) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise GenerationInputContainmentError(
            "Generation yolu containment doğrulamasından geçemedi."
        ) from error


@dataclass(frozen=True)
class _GenerationPaths:
    """Bir generation attempt'inin ÜÇLÜ doğrulanmış Path paketi +
    çözümlenmiş-kimlik tuple'ı (pre-lock ve kilit-altı türetimlerin
    karşılaştırılması için)."""

    pending_path: Path
    history_dir: Path
    reviews_dir: Path

    @property
    def identity(self):
        return (str(self.pending_path), str(self.history_dir), str(self.reviews_dir))


def _derive_verified_generation_paths(module, case_root_real: Path, case_id: str) -> _GenerationPaths:
    return _GenerationPaths(
        pending_path=_verify_nested(module, case_root_real, case_id, module.get_pending_path(case_id)),
        history_dir=_verify_nested(module, case_root_real, case_id, module.get_history_dir(case_id)),
        reviews_dir=_verify_nested(module, case_root_real, case_id, module.get_reviews_dir(case_id)),
    )


# ----------------------------------------------------------------
# DEADLINE - case.json + canonical timeline.json ham baytları
# (deadline_validator'ın KENDİ sabit, tek-anlamlı yollarından; bu iki
# dosya birden çok olabilecek/glob gerektiren bir aile DEĞİLDİR - Row
# 19C-3c-i final scope raporunun "timeline'dan farklı, tekil yol"
# tespiti).
# ----------------------------------------------------------------


def _read_deadline_case_inputs(deadline_validator_module, case_root_real: Path, case_id: str):
    case_json_raw = deadline_validator_module.CASES_DIR / case_id / "case.json"
    timeline_json_raw = deadline_validator_module.CASES_DIR / case_id / "timeline" / "timeline.json"
    case_json_real = _verify_nested(deadline_validator_module, case_root_real, case_id, case_json_raw)
    timeline_json_real = _verify_nested(deadline_validator_module, case_root_real, case_id, timeline_json_raw)
    if not case_json_real.is_file():
        raise GenerationInputContainmentError("case.json güvenli-fakat-normal-dosya değil.")
    if not timeline_json_real.is_file():
        raise GenerationInputContainmentError("Canonical timeline.json güvenli-fakat-normal-dosya değil.")
    return case_json_real.read_bytes(), timeline_json_real.read_bytes()


def _read_global_resource_bytes(path: Path) -> bytes:
    """`ruleset_path`/`provisions_path` her zaman PRODUCTION SABİTLERİ
    (veya test-injection seam'i) - operatörden gelen keyfi bir path
    DEĞİLDİR (CLI'da `--ruleset` YOKTUR - bkz. Row 19C-3c-i final
    scope raporu). Bu yüzden burada bir kullanıcı-kontrollü segment
    containment doğrulaması söz konusu değildir; yalnız var/normal-dosya
    kontrolü yeterlidir."""
    path = Path(path)
    if not path.is_file():
        raise GenerationInputContainmentError(
            f"Global kaynak dosyası bulunamadı veya normal dosya değil: {path}"
        )
    return path.read_bytes()


def _compute_deadline_input_digest(
    case_json_bytes: bytes, timeline_json_bytes: bytes, ruleset_bytes: bytes, provisions_bytes: bytes,
) -> str:
    """REMEDIATION (bkz. modül header'ının "REMEDIATION NOTU"):
    ruleset/provisions ham baytları ARTIK bu digest'in (dolayısıyla
    `pre_revision`/`idempotency_key`'in) bir PARÇASI - `digest_version`
    bu yüzden `v1`'den `v2`'ye yükseltildi (eski formülle sessizce
    karışmasın diye). `entry.pre_revision` reconciliation'da HER ZAMAN
    journal'dan OPAK bir string olarak okunur - bu fonksiyon
    reconciliation zamanında ASLA yeniden çağrılmaz (bkz. `generation_
    mutation_adapters.py`'nin kendi header'ı, DEĞİŞMEDİ)."""
    payload = json.dumps(
        {
            "digest_version": "row19c3ci.deadline.v2",
            "case_json_sha256": hashlib.sha256(case_json_bytes).hexdigest(),
            "timeline_json_sha256": hashlib.sha256(timeline_json_bytes).hexdigest(),
            "ruleset_snapshot_sha256": hashlib.sha256(ruleset_bytes).hexdigest(),
            "provisions_snapshot_sha256": hashlib.sha256(provisions_bytes).hexdigest(),
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compute_deadline_generation_parameters_digest(
    holiday_dates, calendar_complete, judicial_recess_applicable,
) -> str:
    """REMEDIATION: ruleset/provisions ham baytları ARTIK bu digest'te
    DEĞİLDİR (`_compute_deadline_input_digest`'e TAŞINDI) - bu fonksiyon
    artık SAF olarak çağıranın kendi (dosyadan OKUNMAYAN) parametre
    argümanlarının bir fonksiyonudur, hiçbir I/O gerektirmez.
    `digest_version` bu yüzden `v1`'den `v2`'ye yükseltildi."""
    normalized_holidays = sorted(set(holiday_dates or []))
    payload = json.dumps(
        {
            "digest_version": "row19c3ci.deadline_params.v2",
            "holiday_dates": normalized_holidays,
            "calendar_complete": bool(calendar_complete),
            "judicial_recess_applicable": judicial_recess_applicable,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ----------------------------------------------------------------
# TIMELINE - sabit, containment-verified path-set taraması (fail-closed,
# `list_contained_dir()` KULLANILMAZ - bkz. modül header'ı).
# ----------------------------------------------------------------


def _scan_timeline_verified_inputs(case_root_real: Path, case_id: str):
    """`documents/*/document.json` + `documents/*/extractions/facts.json`
    eşdeğerini SEGMENT-SEGMENT, fail-closed tarar. Dönüş: (document_paths,
    facts_paths) - her ikisi de sıralı, containment-doğrulanmış,
    gerçek `Path` listeleri."""

    try:
        documents_dir_real = _path_containment.resolve_existing(
            case_root_real / "documents", root=case_root_real,
        )
    except _path_containment.PathContainmentError as error:
        raise GenerationInputContainmentError(
            "Timeline generation: case documents klasörü containment doğrulamasından geçemedi "
            "(veya bulunamadı)."
        ) from error

    try:
        raw_entries = sorted(documents_dir_real.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise GenerationInputContainmentError(
            "Timeline generation: documents dizini listelenemedi."
        ) from error

    document_paths = []
    facts_paths = []

    for entry in raw_entries:
        name = entry.name

        try:
            _path_containment.validate_segment(name)
        except _path_containment.PathContainmentError as error:
            raise GenerationInputContainmentError(
                f"documents/ altında geçersiz segment adı: {name!r}"
            ) from error

        try:
            entry_real = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise GenerationInputContainmentError(
                f"documents/{name} containment doğrulamasından geçemedi "
                "(kaçan/kırık/döngüsel giriş)."
            ) from error

        if entry_real.parent != documents_dir_real:
            raise GenerationInputContainmentError(
                f"documents/{name} beklenen dizinin doğrudan çocuğu değil (in-tree alias)."
            )

        if not entry_real.is_dir():
            # Güvenli-fakat-eşleşmeyen decoy (orijinal "*/document.json"
            # glob semantiğiyle AYNI - bir dizin olmayan üst-seviye giriş
            # asla eşleşmezdi).
            continue

        document_json_raw = entry_real / "document.json"
        if os.path.lexists(document_json_raw):
            try:
                document_json_real = _path_containment.resolve_existing(
                    document_json_raw, root=case_root_real,
                )
            except _path_containment.PathContainmentError as error:
                raise GenerationInputContainmentError(
                    f"documents/{name}/document.json containment doğrulamasından geçemedi."
                ) from error
            if document_json_real.parent != entry_real:
                raise GenerationInputContainmentError(
                    f"documents/{name}/document.json beklenen dizinin doğrudan çocuğu değil."
                )
            if not document_json_real.is_file():
                raise GenerationInputContainmentError(
                    f"documents/{name}/document.json güvenli-fakat-normal-dosya değil."
                )
            document_paths.append(document_json_real)
        # else: genuinely absent leaf -> normal absence (orijinal glob'un
        # bu giriş için hiç eşleşme üretmemesiyle AYNI).

        extractions_raw = entry_real / "extractions"
        if os.path.lexists(extractions_raw):
            try:
                extractions_real = _path_containment.resolve_existing(
                    extractions_raw, root=case_root_real,
                )
            except _path_containment.PathContainmentError as error:
                raise GenerationInputContainmentError(
                    f"documents/{name}/extractions containment doğrulamasından geçemedi "
                    "(kaçan/kırık/döngüsel giriş)."
                ) from error
            if extractions_real.parent != entry_real:
                raise GenerationInputContainmentError(
                    f"documents/{name}/extractions beklenen dizinin doğrudan çocuğu değil."
                )
            if not extractions_real.is_dir():
                continue
            facts_json_raw = extractions_real / "facts.json"
            if os.path.lexists(facts_json_raw):
                try:
                    facts_json_real = _path_containment.resolve_existing(
                        facts_json_raw, root=case_root_real,
                    )
                except _path_containment.PathContainmentError as error:
                    raise GenerationInputContainmentError(
                        f"documents/{name}/extractions/facts.json containment doğrulamasından "
                        "geçemedi."
                    ) from error
                if facts_json_real.parent != extractions_real:
                    raise GenerationInputContainmentError(
                        f"documents/{name}/extractions/facts.json beklenen dizinin doğrudan "
                        "çocuğu değil."
                    )
                if not facts_json_real.is_file():
                    raise GenerationInputContainmentError(
                        f"documents/{name}/extractions/facts.json güvenli-fakat-normal-dosya "
                        "değil."
                    )
                facts_paths.append(facts_json_real)
            # else: genuinely absent -> normal absence.

    if len(set(document_paths)) != len(document_paths):
        raise GenerationInputContainmentError(
            "documents/*/document.json taramasında duplicate/alias çözümlenmiş yol tespit edildi."
        )
    if len(set(facts_paths)) != len(facts_paths):
        raise GenerationInputContainmentError(
            "documents/*/extractions/facts.json taramasında duplicate/alias çözümlenmiş yol "
            "tespit edildi."
        )

    return sorted(document_paths), sorted(facts_paths)


def _compute_timeline_input_digest(document_paths, facts_paths) -> str:
    document_hashes = sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in document_paths)
    facts_hashes = sorted(hashlib.sha256(path.read_bytes()).hexdigest() for path in facts_paths)
    payload = json.dumps(
        {
            "digest_version": "row19c3ci.timeline.v1",
            "document_sha256_list": document_hashes,
            "facts_sha256_list": facts_hashes,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ----------------------------------------------------------------
# Composite pre-state snapshot (kendi versiyon etiketi - Layer A/
# promotion/Layer B'nin ÜÇÜNÜN de kendi ayrı sürüm etiketi vardır).
# Formül `generation_mutation_adapters.py` tarafından BAĞIMSIZ olarak
# yeniden implement edilmez (bkz. o modülün kendi header'ı - erratum'un
# pre-state/post-state ayrımı zaten bu formülden BAĞIMSIZ, kendi
# kanıtını taşır).
# ----------------------------------------------------------------

SNAPSHOT_ABSENT = "__absent__"
SNAPSHOT_PRESENT = "__present__"
_SNAPSHOT_VERSION = "row19c3ci.generation.v1"


@dataclass(frozen=True)
class GenerationPreconditionSnapshot:
    input_digest: str
    pending_presence: str
    pending_sha256: str
    composite_digest: str


def _compute_generation_snapshot(input_digest: str, pending_path: Path) -> GenerationPreconditionSnapshot:
    """BİLİNÇLİ OLARAK yalnız `input_digest` + pending presence/hash'e
    dayanır - bu formülün KENDİSİ Row 19C-3c-i DEADLINE REVISION-
    IDENTITY REMEDIATION turunda DEĞİŞMEDİ (yalnız `input_digest`'in
    YUKARI AKIŞTA neyi temsil ettiği değişti - artık deadline için
    ruleset/provisions'ı da İÇERİR, bkz. `_compute_deadline_input_
    digest()`'in kendi docstring'i). `generation_mutation_adapters.py`'
    nin reconciliation sırasında bu composite `pre_hash`'i YENİDEN İNŞA
    EDEBİLMESİ için, formül YALNIZ journal satırının KENDİ kayıtlı
    `pre_revision`'ından (input_digest - OPAK bir string, asla yeniden
    hesaplanmaz) ve case kilidi beklenmeden ÖNCE bile canlı okunabilen
    pending dosyasından türetilebilir olmalıdır - reconciliation anında
    artık mevcut olmayabilecek ORİJİNAL ruleset/provisions baytlarına
    ASLA dayanamaz (ve dayanmaz: `input_digest` reconciliation'da
    HERHANGİ bir dosyadan değil, doğrudan journal'ın kendi kayıtlı
    değerinden okunur). `generation_parameters_digest` (holiday_dates/
    calendar_complete/judicial_recess_applicable) BU FORMÜLE KASITLI
    OLARAK DAHİL DEĞİLDİR - REMEDIATION SONRASI bu artık ayrı bir race-
    tespiti de GEREKTİRMEZ (saf çağıran parametreleridir, dosyadan
    okunmaz - bkz. `precondition_callback`'in kendi yorumu); yalnız
    `MutationIntent.secondary_input_hash` üzerinden `request_
    fingerprint`'e girmeye devam eder (aynı kimlik + farklı parametre ->
    mevcut `IdempotencyConflictError`)."""
    pending_sha = sha256_file(pending_path)
    pending_presence = SNAPSHOT_PRESENT if pending_sha is not None else SNAPSHOT_ABSENT
    pending_sha256 = pending_sha if pending_sha is not None else SNAPSHOT_ABSENT
    payload = json.dumps(
        {
            "snapshot_version": _SNAPSHOT_VERSION,
            "input_digest": input_digest,
            "pending_presence": pending_presence,
            "pending_sha256": pending_sha256,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return GenerationPreconditionSnapshot(
        input_digest=input_digest,
        pending_presence=pending_presence,
        pending_sha256=pending_sha256,
        composite_digest=hashlib.sha256(payload).hexdigest(),
    )


# ----------------------------------------------------------------
# Audit içerik-eşleşmesi (yalnız completed replay corroboration'ı bu
# modülde kullanır; `generation_mutation_adapters.py` kendi BAĞIMSIZ
# kopyasını taşır).
# ----------------------------------------------------------------


def _scan_generation_audits(case_root_real: Path, reviews_dir_verified: Path):
    """`*.generation_audit.json` girişlerinin containment-before-stat
    taraması: ad sınıflandırması ÖNCE (saf string), eşleşen HER giriş
    için containment + exact-parent membership HERHANGİ bir stat/open/
    JSON-read'den ÖNCE. Kaçan/kırık/alias giriş TÜM taramayı
    fail-closed durdurur; parse edilemeyen giriş `(path, None)` olarak
    döner (çağıran karar verir). reviews_dir yoksa boş liste."""
    if not reviews_dir_verified.is_dir():
        return []
    try:
        raw_entries = sorted(reviews_dir_verified.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise GenerationInputContainmentError(
            "Generation reviews dizini listelenemedi."
        ) from error
    results = []
    for entry in raw_entries:
        if not fnmatch.fnmatch(entry.name, "*.generation_audit.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise GenerationInputContainmentError(
                "Generation audit girişi containment doğrulamasından geçemedi."
            ) from error
        if resolved.parent != reviews_dir_verified:
            raise GenerationInputContainmentError(
                "Generation audit girişi beklenen dizinin dışına çözülüyor (in-tree alias)."
            )
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
    """TAM bağlama kuralı - eksik/boş/uyumsuz HERHANGİ bir değer False
    (asla otomatik kanıt)."""
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


def _verify_completed_generation_replay_binding(
    paths: _GenerationPaths,
    case_root_real: Path,
    *,
    action_family: str,
    journal_state: str,
    journal_id: int,
    idempotency_key: str,
    resource_key: str,
    observed_post_hash,
):
    """Completed safe-replay corroboration. Başarıda (taze pending sha,
    eşleşen audit path) döner; HER eksik/boş/uyumsuz değerde
    `GenerationAuditBindingVerificationFailedError` fırlatır. Parametre
    seviyesinde KAPALI: journal_state tam olarak 'completed' olmalıdır."""

    def fail(reason):
        raise GenerationAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key, reason=reason,
        )

    if journal_state != COMPLETED_JOURNAL_STATE:
        fail(f"bu corroboration yalnız 'completed' satır için tanımlıdır (state={journal_state!r})")

    current_pending_sha256 = sha256_file(paths.pending_path)
    if current_pending_sha256 is None:
        fail(f"pending artefakt şu an mevcut değil: {paths.pending_path}")
    if not _nonblank(observed_post_hash):
        fail(f"journal satırı boş/eksik observed_post_hash taşıyor ({observed_post_hash!r})")
    if observed_post_hash != current_pending_sha256:
        fail(
            f"journal observed_post_hash={observed_post_hash!r} ile diskteki pending "
            f"({current_pending_sha256!r}) eşleşmiyor"
        )
    if not resource_key.startswith(_CASE_RESOURCE_KEY_PREFIX) or not resource_key[len(_CASE_RESOURCE_KEY_PREFIX):]:
        fail(f"resource_key={resource_key!r} geçerli bir case:<case_id> anahtarı değil")

    entries = _scan_generation_audits(case_root_real, paths.reviews_dir)
    unparseable = [path for path, record in entries if record is None]
    if unparseable:
        fail(
            f"reviews dizininde parse edilemeyen {len(unparseable)} adet *.generation_audit.json "
            "var - içerik-bağlama güvenle yapılamaz"
        )
    matches = [
        (path, record) for path, record in entries
        if _audit_record_matches(
            record, idempotency_key=idempotency_key, resource_key=resource_key,
            action_family=action_family, pending_sha256=current_pending_sha256,
        )
    ]
    if len(matches) != 1:
        fail(
            f"tam-bağlama eşleşen success audit sayısı {len(matches)} (tam 1 olmalı) - "
            "bu completed satır bağımsızca doğrulanamadı"
        )
    return current_pending_sha256, matches[0][0]


# ----------------------------------------------------------------
# Authz repo / journal conn kurulumu - Layer A/promotion facade'lerinin
# kendi desenlerinin bağımsız kopyaları (lazy psycopg import disiplini
# aynı).
# ----------------------------------------------------------------


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


# ----------------------------------------------------------------
# Argüman şekil kuralları - her I/O'dan önce.
# ----------------------------------------------------------------


def _check_argument_shapes(
    row_key: str,
    anchor_event_id,
    holiday_dates,
    calendar_complete,
    judicial_recess_applicable,
    expected_input_digest=None,
    *,
    for_apply: bool,
):
    if row_key not in GENERATION_ROW_KEY_TO_MODULE_NAME:
        raise KeyError(f"row_key={row_key!r} is not a known generation family")

    if row_key == "timeline":
        if anchor_event_id is not None:
            raise GenerationArgumentError(
                "timeline generation'ı anchor_event_id parametresi KABUL ETMEZ (I/O öncesi red)."
            )
        if holiday_dates is not None and len(holiday_dates) > 0:
            raise GenerationArgumentError(
                "timeline generation'ı holiday_dates parametresi KABUL ETMEZ (I/O öncesi red)."
            )
        if calendar_complete:
            raise GenerationArgumentError(
                "timeline generation'ı calendar_complete parametresi KABUL ETMEZ (I/O öncesi red)."
            )
        if judicial_recess_applicable is not None:
            raise GenerationArgumentError(
                "timeline generation'ı judicial_recess_applicable parametresi KABUL ETMEZ "
                "(I/O öncesi red)."
            )
    else:
        if not isinstance(anchor_event_id, str) or not anchor_event_id.strip():
            raise GenerationArgumentError(
                "deadline generation'ı için anchor_event_id ZORUNLUDUR, boş olamaz."
            )

    if for_apply and (not isinstance(expected_input_digest, str) or not expected_input_digest.strip()):
        raise GenerationArgumentError("expected_input_digest apply için zorunlu, boş olamaz.")


# ----------------------------------------------------------------
# PREVIEW (salt-okunur)
# ----------------------------------------------------------------


def preview_generation(
    row_key: str,
    case_id: str,
    *,
    anchor_event_id=None,
    principal,
    authz_repository=None,
    ruleset_path=None,
    provisions_path=None,
):
    """Salt-okunur preview. SIRA: dış 'read' authz HER filesystem
    probundan ÖNCE koşar. Deadline+timeline için case içeriğinden
    `input_digest` hesaplanır ve gösterilir - REMEDIATION (bkz. modül
    header'ının "REMEDIATION NOTU"): deadline için `input_digest` ARTIK
    ruleset/provisions ham baytlarını da İÇERİR, bu yüzden preview de
    bunları apply ile AYNI `effective_ruleset_path`/`effective_
    provisions_path` çözümüyle okur (holiday/calendar/recess yine
    BURADA gerekmez - bunlar yalnız apply anındaki generation_
    parameters_digest'e girer, preview'ın işi DEĞİLDİR)."""
    import importlib

    _check_argument_shapes(row_key, anchor_event_id, None, False, None, for_apply=False)
    module = importlib.import_module(GENERATION_ROW_KEY_TO_MODULE_NAME[row_key])

    if row_key == "deadline":
        effective_ruleset_path = Path(ruleset_path) if ruleset_path is not None else module.DEFAULT_RULESET_PATH
        if provisions_path is not None:
            effective_provisions_path = Path(provisions_path)
        else:
            deadline_calculator = importlib.import_module("deadline_calculator")
            effective_provisions_path = deadline_calculator.DEFAULT_PROVISIONS_PATH

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "read", repository=repository,
        )

        case_root_real = _resolve_module_case_root_real(module, resolved_case_id)
        paths = _derive_verified_generation_paths(module, case_root_real, resolved_case_id)

        if row_key == "deadline":
            deadline_validator = importlib.import_module("deadline_validator")
            dv_case_root_real = _resolve_module_case_root_real(deadline_validator, resolved_case_id)
            case_bytes, timeline_bytes = _read_deadline_case_inputs(
                deadline_validator, dv_case_root_real, resolved_case_id,
            )
            ruleset_bytes = _read_global_resource_bytes(effective_ruleset_path)
            provisions_bytes = _read_global_resource_bytes(effective_provisions_path)
            input_digest = _compute_deadline_input_digest(case_bytes, timeline_bytes, ruleset_bytes, provisions_bytes)
            target_ref = module.get_target_ref(anchor_event_id)
        else:
            document_paths, facts_paths = _scan_timeline_verified_inputs(case_root_real, resolved_case_id)
            input_digest = _compute_timeline_input_digest(document_paths, facts_paths)
            target_ref = module.get_target_ref()

        return {
            "row_key": row_key,
            "case_id": resolved_case_id,
            "anchor_event_id": anchor_event_id,
            "target_ref": target_ref,
            "input_digest": input_digest,
            "pending_exists": paths.pending_path.is_file(),
            "pending_sha256": sha256_file(paths.pending_path),
        }
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(
                f"WARNING: preview_generation authz repository close failed: {close_error!r}"
            )


# ----------------------------------------------------------------
# APPLY (koordine, journal'lı, idempotent mutasyon)
# ----------------------------------------------------------------


@dataclass(frozen=True)
class GenerationApplyResult:
    row_key: str
    case_id: str
    anchor_event_id: str | None
    pending_path: Path
    pending_sha256: str | None
    audit_path: Path | None
    stdout: str
    journal_id: int
    replayed: bool


def apply_generation(
    row_key: str,
    case_id: str,
    expected_input_digest: str,
    *,
    anchor_event_id=None,
    holiday_dates=None,
    calendar_complete=False,
    judicial_recess_applicable=None,
    principal,
    authz_repository=None,
    conn_factory=None,
    ruleset_path=None,
    provisions_path=None,
) -> GenerationApplyResult:
    """SIRA (Layer A/promotion facade'lerinin kanıtlanmış düzeninin
    generation karşılığı): (1) argüman şekilleri (saf, I/O'suz); (2) DIŞ
    authorize_case_access('mutate') - hiçbir journal/lock bağlantısı,
    hiçbir artefakt hash'i ondan önce; (3) writer dinamik kökünden
    pre-lock containment + input_digest hesaplama + composite snapshot
    + expected_input_digest karşılaştırması; (4) conn + case lock; (5)
    run_mutation: İÇ otoriter authz -> journal gate -> idempotency ->
    precondition (SIFIRDAN kilit-altı yeniden doğrulama; her red sıfır
    journal satırı) -> writer (kilit-altı doğrulanmış girdi
    NESNELERİYLE, deadline için TemporaryDirectory-materialize edilmiş
    global kaynak snapshot'ıyla); (6) replay'de tam corroboration; (7)
    maskelemeyen temizlik."""
    import importlib

    _check_argument_shapes(
        row_key, anchor_event_id, holiday_dates, calendar_complete, judicial_recess_applicable,
        expected_input_digest, for_apply=True,
    )
    module = importlib.import_module(GENERATION_ROW_KEY_TO_MODULE_NAME[row_key])
    deadline_validator = importlib.import_module("deadline_validator") if row_key == "deadline" else None

    effective_holiday_dates = list(holiday_dates or [])

    if row_key == "deadline":
        effective_ruleset_path = Path(ruleset_path) if ruleset_path is not None else module.DEFAULT_RULESET_PATH
        if provisions_path is not None:
            effective_provisions_path = Path(provisions_path)
        else:
            deadline_calculator = importlib.import_module("deadline_calculator")
            effective_provisions_path = deadline_calculator.DEFAULT_PROVISIONS_PATH
    else:
        effective_ruleset_path = None
        effective_provisions_path = None

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        outer_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )

        resource_key = _mutation_lock.case_resource_key(outer_resolved_case_id)

        pre_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
        pre_paths = _derive_verified_generation_paths(module, pre_case_root, outer_resolved_case_id)

        if row_key == "deadline":
            dv_case_root = _resolve_module_case_root_real(deadline_validator, outer_resolved_case_id)
            case_bytes, timeline_bytes = _read_deadline_case_inputs(
                deadline_validator, dv_case_root, outer_resolved_case_id,
            )
            ruleset_bytes = _read_global_resource_bytes(effective_ruleset_path)
            provisions_bytes = _read_global_resource_bytes(effective_provisions_path)
            # REMEDIATION - bkz. modül header'ının "REMEDIATION NOTU":
            # ruleset/provisions ham baytları ARTIK input_digest'in bir
            # parçası (idempotency identity buradan türer); generation_
            # parameters_digest ARTIK yalnız holiday/calendar/recess'i
            # taşır (dosyadan hiçbir şey OKUMAZ, saf bir fonksiyondur).
            input_digest = _compute_deadline_input_digest(case_bytes, timeline_bytes, ruleset_bytes, provisions_bytes)
            generation_parameters_digest = _compute_deadline_generation_parameters_digest(
                effective_holiday_dates, calendar_complete, judicial_recess_applicable,
            )
            target_ref = module.get_target_ref(anchor_event_id)
        else:
            document_paths, facts_paths = _scan_timeline_verified_inputs(pre_case_root, outer_resolved_case_id)
            input_digest = _compute_timeline_input_digest(document_paths, facts_paths)
            generation_parameters_digest = None
            target_ref = module.get_target_ref()

        if input_digest != expected_input_digest:
            raise StaleViewError(
                "Preview alındıktan sonra girdi içeriği DEĞİŞTİ "
                f"(beklenen input_digest: {expected_input_digest}, şimdiki: {input_digest}). "
                "İşlem iptal edildi, HİÇBİR değişiklik yapılmadı."
            )

        pre_snapshot = _compute_generation_snapshot(input_digest, pre_paths.pending_path)

        intent = MutationIntent(
            actor_type="iam_user",
            actor_ref=str(principal.user_id),
            resource_key=resource_key,
            action_family=generation_action_family_for(row_key),
            target_ref=target_ref,
            target_state=TARGET_STATE,
            pre_hash=pre_snapshot.composite_digest,
            pre_revision=input_digest,
            secondary_input_hash=generation_parameters_digest,
        )
        idempotency_key_for_audit = compute_idempotency_key(intent)

        # Kilit-altı türetimlerin writer_callback'e AYNI NESNELER olarak
        # taşınması için box'lar (facade'lerin nonlocal-rebind
        # desenlerinin closure karşılığı).
        under_lock_box = {}
        writer_outcome_box = {}

        def authz_callback() -> None:
            inner_resolved_case_id = _authz.authorize_case_access(
                principal, case_id, "mutate", repository=repository,
            )
            if inner_resolved_case_id != outer_resolved_case_id:
                raise GenerationResolvedCaseIdMismatchError(
                    f"outer authz {outer_resolved_case_id!r} çözdü, inner authz "
                    f"{inner_resolved_case_id!r} - kilitlenen resource ile otoriter karar farklı "
                    "case'i tarif ediyor; reddedildi."
                )

        def precondition_callback() -> None:
            # SIFIRDAN, kilit-altı taze türetim: kök attribute'u YENİDEN
            # okunur, girdi YENİDEN taranır/hash'lenir - kilit beklerken
            # değişen içerik/link swap burada yakalanır. Global kaynak
            # (ruleset/provisions) baytları BURADA SADECE BELLEĞE alınır
            # - HİÇBİR dosya YAZILMAZ (bkz. modül header'ı, "GLOBAL
            # KAYNAK SNAPSHOT" adım 3).
            ul_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
            ul_paths = _derive_verified_generation_paths(module, ul_case_root, outer_resolved_case_id)
            if ul_paths.identity != pre_paths.identity:
                raise PreconditionRaceDetectedError(
                    "Bu generation isteği case kilidini beklerken ilgili dizin/dosyaların "
                    "çözümlenmiş (gerçek) konumu DEĞİŞTİ (link swap veya benzeri). İşlem iptal "
                    "edildi, HİÇBİR değişiklik yapılmadı."
                )

            if row_key == "deadline":
                ul_dv_case_root = _resolve_module_case_root_real(deadline_validator, outer_resolved_case_id)
                ul_case_bytes, ul_timeline_bytes = _read_deadline_case_inputs(
                    deadline_validator, ul_dv_case_root, outer_resolved_case_id,
                )
                ul_ruleset_bytes = _read_global_resource_bytes(effective_ruleset_path)
                ul_provisions_bytes = _read_global_resource_bytes(effective_provisions_path)
                under_lock_box["ruleset_bytes"] = ul_ruleset_bytes
                under_lock_box["provisions_bytes"] = ul_provisions_bytes

                # REMEDIATION (bkz. modül header'ının "REMEDIATION
                # NOTU"): ruleset/provisions ham baytları ARTIK
                # `ul_input_digest`'in kendisine girer - kilit beklenirken
                # bunların DEĞİŞMESİ, aşağıdaki composite `pre_hash`
                # karşılaştırmasında (`ul_snapshot.composite_digest !=
                # pre_snapshot.composite_digest`) DOĞRUDAN yakalanır; ayrı
                # bir `generation_parameters_digest` eşitlik kontrolüne
                # ARTIK GEREK YOKTUR - holiday_dates/calendar_complete/
                # judicial_recess_applicable bu çağrı içinde SABİT (yerel
                # closure değişkeni, dosyadan OKUNMAZ), bu yüzden onların
                # kendi digest'i asla kilit-bekleme sırasında
                # DEĞİŞEMEZ/RACE'e giremez.
                ul_input_digest = _compute_deadline_input_digest(
                    ul_case_bytes, ul_timeline_bytes, ul_ruleset_bytes, ul_provisions_bytes,
                )
            else:
                ul_document_paths, ul_facts_paths = _scan_timeline_verified_inputs(
                    ul_case_root, outer_resolved_case_id,
                )
                ul_input_digest = _compute_timeline_input_digest(ul_document_paths, ul_facts_paths)
                under_lock_box["document_paths"] = ul_document_paths
                under_lock_box["facts_paths"] = ul_facts_paths

            ul_snapshot = _compute_generation_snapshot(ul_input_digest, ul_paths.pending_path)
            if ul_snapshot.composite_digest != pre_snapshot.composite_digest:
                raise PreconditionRaceDetectedError(
                    "Bu generation isteği case kilidini beklerken girdi/pending durumu DEĞİŞTİ. "
                    "İşlem iptal edildi, HİÇBİR değişiklik yapılmadı."
                )
            if ul_snapshot.input_digest != intent.pre_revision:
                raise StaleViewError(
                    "Preview alındıktan sonra girdi içeriği değişti. İşlem iptal edildi."
                )

            under_lock_box["paths"] = ul_paths
            under_lock_box["case_root"] = ul_case_root

        def writer_callback() -> _mutation_coordinator.WriterResult:
            ul = under_lock_box["paths"]
            stdout_capture = io.StringIO()

            if row_key == "deadline":
                with tempfile.TemporaryDirectory(prefix="vergi_generation_deadline_") as temp_dir:
                    temp_dir_path = Path(temp_dir)
                    temp_ruleset_path = temp_dir_path / "ruleset.json"
                    temp_provisions_path = temp_dir_path / "provisions.json"

                    captured_ruleset_bytes = under_lock_box["ruleset_bytes"]
                    captured_provisions_bytes = under_lock_box["provisions_bytes"]

                    temp_ruleset_path.write_bytes(captured_ruleset_bytes)
                    temp_provisions_path.write_bytes(captured_provisions_bytes)

                    if hashlib.sha256(temp_ruleset_path.read_bytes()).hexdigest() != hashlib.sha256(captured_ruleset_bytes).hexdigest():
                        raise GenerationSnapshotMaterializationError(
                            "Ruleset snapshot materialization bütünlük kontrolünden geçemedi."
                        )
                    if hashlib.sha256(temp_provisions_path.read_bytes()).hexdigest() != hashlib.sha256(captured_provisions_bytes).hexdigest():
                        raise GenerationSnapshotMaterializationError(
                            "Provisions snapshot materialization bütünlük kontrolünden geçemedi."
                        )

                    def pre_commit_callback() -> None:
                        live_ruleset_bytes = _read_global_resource_bytes(effective_ruleset_path)
                        live_provisions_bytes = _read_global_resource_bytes(effective_provisions_path)
                        if live_ruleset_bytes != captured_ruleset_bytes or live_provisions_bytes != captured_provisions_bytes:
                            raise GlobalResourceStaleError(
                                "Ruleset/provisions dosyaları generation sırasında DEĞİŞTİ. "
                                "İşlem iptal edildi."
                            )

                    with contextlib.redirect_stdout(stdout_capture):
                        engine_result = module.run_engine(
                            case_id=outer_resolved_case_id,
                            anchor_event_id=anchor_event_id,
                            ruleset_path=temp_ruleset_path,
                            holiday_dates=effective_holiday_dates,
                            calendar_complete=calendar_complete,
                            judicial_recess_applicable=judicial_recess_applicable,
                            provisions_path=temp_provisions_path,
                            input_digest=input_digest,
                            generation_parameters_digest=generation_parameters_digest,
                            mutation_idempotency_key=idempotency_key_for_audit,
                            mutation_resource_key=resource_key,
                            mutation_actor_ref=str(principal.user_id),
                            pre_commit_callback=pre_commit_callback,
                        )
            else:
                with contextlib.redirect_stdout(stdout_capture):
                    engine_result = module.run_timeline_engine(
                        case_id=outer_resolved_case_id,
                        document_paths=under_lock_box["document_paths"],
                        facts_paths=under_lock_box["facts_paths"],
                        input_digest=input_digest,
                        generation_parameters_digest=None,
                        mutation_idempotency_key=idempotency_key_for_audit,
                        mutation_resource_key=resource_key,
                        mutation_actor_ref=str(principal.user_id),
                    )

            observed = engine_result["pending_sha256"]
            writer_outcome_box["audit_path"] = engine_result["audit_path"]
            return _mutation_coordinator.WriterResult(
                observed_post_hash=observed, result=stdout_capture.getvalue(),
            )

        conn = (conn_factory or _default_conn_factory)()
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
                # TAZE, replay-anı yeniden doğrulama - precondition
                # replay'de HİÇ çağrılmadığı için buradaki zincir bu
                # outcome'un kendi ilk (ve tek) doğrulamasıdır.
                try:
                    replay_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
                    replay_paths = _derive_verified_generation_paths(
                        module, replay_case_root, outer_resolved_case_id,
                    )
                    verified_pending_hash, audit_path = _verify_completed_generation_replay_binding(
                        replay_paths, replay_case_root,
                        action_family=intent.action_family,
                        journal_state=outcome.state,
                        journal_id=outcome.journal_id,
                        idempotency_key=idempotency_key_for_audit,
                        resource_key=resource_key,
                        observed_post_hash=outcome.observed_post_hash,
                    )
                except GenerationInputContainmentError as error:
                    raise GenerationAuditBindingVerificationFailedError(
                        journal_id=outcome.journal_id, idempotency_key=idempotency_key_for_audit,
                        reason=f"replay corroboration sırasında containment hatası: {error}",
                    ) from error
                stdout_text = ""
                pending_path_result = replay_paths.pending_path
            else:
                verified_pending_hash = outcome.observed_post_hash
                stdout_text = outcome.result
                audit_path = writer_outcome_box.get("audit_path")
                pending_path_result = under_lock_box["paths"].pending_path

            return GenerationApplyResult(
                row_key=row_key,
                case_id=outer_resolved_case_id,
                anchor_event_id=anchor_event_id,
                pending_path=pending_path_result,
                pending_sha256=verified_pending_hash,
                audit_path=audit_path,
                stdout=stdout_text,
                journal_id=outcome.journal_id,
                replayed=outcome.replayed,
            )
        finally:
            # Maskelemeyen temizlik - Layer A/promotion facade'lerinin
            # AYNI deseni: release'in raise'i loglanır ve düşürülür;
            # False dönüşü görünür kalır; conn.close kendi iç
            # finally'sinde her koşulda koşar.
            try:
                try:
                    released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
                except Exception as release_error:
                    _log_critical_safely(
                        f"CRITICAL: apply_generation() lock release RAISED for "
                        f"resource_key={resource_key!r} (advisory_lock_id={advisory_lock_id!r}): "
                        f"{release_error!r} - outcome unchanged, investigate out of band"
                    )
                else:
                    if not released:
                        _log_critical_safely(
                            f"CRITICAL: apply_generation() release_lock_session returned False "
                            f"for resource_key={resource_key!r} (advisory_lock_id={advisory_lock_id!r}) "
                            "- outcome unchanged, investigate out of band"
                        )
            finally:
                try:
                    conn.close()
                except Exception as close_error:
                    _log_critical_safely(
                        f"CRITICAL: apply_generation() journal connection close failed: "
                        f"{close_error!r} - outcome unchanged"
                    )
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(
                f"WARNING: apply_generation authz repository close failed: {close_error!r}"
            )
