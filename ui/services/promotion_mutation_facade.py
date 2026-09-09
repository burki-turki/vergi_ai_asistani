# ============================================================
# VERGİ AI - ROW 19C-3b SLICE 2: PROMOTION MUTATION FACADE.
#
# Fact (Row 6) ve Timeline (Row 7) canonical PROMOTION writer'larını
# (`src/fact_approval.promote()`, `src/timeline_approval.approve_
# pending()`) mutation coordinator/journal altyapısına bağlayan, AYRI
# ve BAĞIMSIZ facade. Mevcut LOCKED `mutation_approval_facade.py`
# (Layer A'nın exact-10 uniform kontratı) BİLİNÇLİ olarak
# GENİŞLETİLMEMİŞTİR - fact/timeline o kontratın her maddesini kırar
# (doküman-scoped hedef, `pending_path` alan writer imzaları, fact'te
# TRANSFORM canonical + `source_pending_sha256` alan adı, timeline'da
# farklı audit şekli). Repo emsali de budur: her yeni kontrat şekli
# kendi facade+adapters çiftini aldı (review_mutation_* 19C-2b,
# drafting_request_mutation_* 19C-2c).
#
# ACTION FAMILY'LER: `promotion.fact` / `promotion.timeline` - AYRI
# `promotion.` öneki, `approval.*` sınıflandırıcılarının (exact-10)
# hiçbirini bozmaz. Kanal ayrımı YOK (bu iki aile YALNIZ CLI'dan
# erişilebilir; web onay yüzeyi bilinçli kapsam dışı - Row 18a'nın
# `unsupported_pending_resolution` görünümü aynen durur).
#
# WRITER-ROOT KONTRATI (Row 19C-3b Slice 2 final path-handoff kararı):
#   - Writer containment kökü ÇAĞRI ANINDA writer modülünün KENDİ
#     `CASES_DIR` attribute'undan okunur (`fact_approval.CASES_DIR` /
#     `timeline_approval.CASES_DIR`), asla cache'lenmez/default-arg'a
#     bağlanmaz - mevcut per-module redirect test seam'i aynen çalışır.
#   - UI authz mevcut `ui.services.paths.CASES_DIR` üzerinden çalışmaya
#     devam eder (authorize_case_access -> resolve_case_id); writer
#     path doğrulaması için `paths.resolve_case_path()` KULLANILMAZ
#     (o fonksiyon UI köküne bağlıdır - bu, Slice 2'nin kapattığı
#     birinci path blocker'ıdır). Üretimde iki kök yapısal olarak aynı
#     gerçek dizine çözülür (her ikisi de Path(__file__)-anchored repo
#     kökü); eşitlik ENFORCE EDİLMEZ - Layer A facade'inin kendi
#     `_resolve_case_root_real()` emsaliyle aynı karar: authz "bu aktör
#     bu case'e dokunabilir mi"yi UI kökünde, containment "bu yollar
#     writer case dizini içinde mi"yi writer kökünde cevaplar; zorlama
#     containment'a garanti eklemez ve redirect seam'ini kırar. Kök
#     uyuşmazlığı her durumda journal/lock/writer/dosya-içeriği
#     erişimi BAŞLAMADAN generic containment hatası üretir (authz her
#     zaman önce koştuğu için existence-blind kalır).
#
# VERIFIED-PATH HANDOFF: pending/canonical/container/history/reviews
# zinciri pre-lock doğrulanır, kilit ALTINDA SIFIRDAN yeniden doğrulanır
# (çözümlenmiş-kimlik tuple'ı karşılaştırması dahil - kilit beklerken
# link swap'i yakalar), completed replay öncesinde ÜÇÜNCÜ kez taze
# doğrulanır. writer_callback'e geçen Path nesneleri, kilit-altı
# doğrulamada üretilen nesnelerin TA KENDİSİDİR (closure/box üzerinden)
# - hiçbir dalda raw/unverified path writer'a ulaşmaz. OS-level atomik
# path pinning İDDİA EDİLMEZ: kilit-altı doğrulama ile tekil os
# çağrıları arasındaki dar link-swap penceresi Row 19A'nın T15 kararı
# uyarınca Row 19D (OS ACL / service identity) borcudur.
#
# PRE-STATE: composite snapshot (pending sha + canonical var/yok +
# canonical sha) - Layer A ile aynı üçlü, kendi `_SNAPSHOT_VERSION`'ı
# ile. `pre_revision` = operatörün `--expected-hash` beyanı (pending
# sha). İkisi de kilit altında taze yeniden hesaplanır; composite farkı
# `PreconditionRaceDetectedError` (StaleViewError alt sınıfı), pending
# sha != expected `StaleViewError` üretir - her ikisi de `prepared`
# satırı YAZILMADAN.
#
# POST-STATE: her iki writer'ın canonical'ı pending'in DETERMİNİSTİK
# saf fonksiyonudur (fact: build_canonical sabit-notes dönüşümü;
# timeline: kimlik) - writer modüllerinin kendi
# `compute_expected_canonical_sha256()` yardımcıları (tek-kaynak
# serializer) kilit altında beklenen hash'i verir; writer döndükten
# sonra facade taze canonical hash'ini bu beklenenle EŞİTLİK
# kontrolünden geçirir (uyuşmazlık -> exception -> journal
# reconciliation_required; asla sessiz başarı).
#
# PROVENANCE: `PROMOTION_REVIEWER_REF` bu katmanın KENDİ kapalı,
# tek-değerli write-side sözlüğüdür - Layer B'nin `local_lawyer_ui`/
# `local_lawyer_cli` sözlüğü YENİDEN KULLANILMAZ. Gerçek aktör kimliği
# audit'lere `mutation_actor_ref` olarak ayrıca bağlanır (19C-2b
# emsali). Fact'in `--note`'u fingerprint-only `secondary_input_hash`
# olarak bağlanır (kimliğe girmez - aynı kimlik + farklı not, mevcut
# IdempotencyConflictError mekanizmasına düşer); timeline'ın not
# kavramı yoktur ve `note` timeline'da her I/O'dan önce reddedilir.
#
# REPLAY: completed replay, taze containment + journal
# `observed_post_hash` == taze canonical sha + reviews_dir İÇERİK
# taramasında TAM BİR adet full-binding eşleşen success audit
# (mutation_idempotency_key/mutation_resource_key/pending-hash-alanı/
# canonical_sha256 + aile bayrakları) gerektirir - eşleşme HER ZAMAN
# içerikten yapılır, addan/mtime'dan asla (fact'te aynı extraction'ın
# birden çok zaman damgalı audit'i meşru şekilde yan yana yaşar).
# ============================================================

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import sys
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
    PendingNotFoundError,
    PreconditionRaceDetectedError,
    StaleViewError,
    sha256_file,
)

# ----------------------------------------------------------------
# Kapalı row_key -> writer modülü eşlemesi. Layer A'nın
# `ROW_KEY_TO_MODULE_NAME`'inden BİLİNÇLİ olarak ayrıdır (o sözlük
# `CASE_SCOPED_ROWS` ile exact-10 driftsizliğini kontrat ilan eder);
# `promotion_mutation_adapters.register_into()` bu sözlüğü ve
# `promotion_action_family_for()`'u import eder - tek yönlü kenar,
# Layer A adapters<-facade deseninin birebir aynısı.
# ----------------------------------------------------------------

PROMOTION_ROW_KEY_TO_MODULE_NAME = {
    "fact": "fact_approval",
    "timeline": "timeline_approval",
}

_ACTION_FAMILY_PREFIX = "promotion."

_CASE_RESOURCE_KEY_PREFIX = "case:"

TARGET_STATE = "approved"

# Bu katmanın KENDİ kapalı, tek-değerli reviewer provenance sözlüğü -
# asla kullanıcı girdisi, asla Layer B sözlüğünün yeniden kullanımı.
PROMOTION_REVIEWER_REF = "local_lawyer_promotion_cli"

# `--note` verilmediğinde fact writer'ına geçen SABİT, deterministik
# varsayılan not (secondary_input_hash bu durumda None kalır - "not
# verilmedi" her zaman aynı kimlik/fingerprint'i üretir).
FACT_DEFAULT_REVIEW_NOTE = (
    "Fact extraction çıktısı insan tarafından incelendi (promotion CLI onayı)."
)

_logger = logging.getLogger("vergi_ai.promotion_mutation_facade")


def _log_critical_safely(message: str) -> None:
    """mutation_approval_facade/mutation_coordinator ile aynı ilke:
    logging'in kendi hatası, aktif sonucu/istisnayı asla maskeleyemez."""
    try:
        _logger.critical(message)
    except Exception:
        pass


def promotion_action_family_for(row_key: str) -> str:
    """`promotion.<row_key>` - hem bu modülün MutationIntent'i hem
    `promotion_mutation_adapters.register_into()` BU fonksiyonu çağırır;
    iki taraf farklı string'lere kayamaz."""
    return f"{_ACTION_FAMILY_PREFIX}{row_key}"


# ----------------------------------------------------------------
# Hata sınıfları - HEPSİ `ApprovalUiError` alt sınıfıdır, böylece
# `ui.cli_mutate._is_known_domain_error()` (ApprovalUiError'ı zaten
# tanır) SIFIR değişiklikle temiz tek-satır hata üretir.
# ----------------------------------------------------------------


class PromotionArgumentError(ApprovalUiError):
    """Kullanım-şekli/argüman sözleşmesi ihlali (fact'te document
    eksik, timeline'da document/note verilmiş, boş expected_hash, boş
    not, ...) - HERHANGİ bir DB/filesystem I/O'sundan ÖNCE fırlatılır."""


class PromotionNestedPathContainmentError(ApprovalUiError):
    """Writer-root/nested containment doğrulaması başarısız (kaçan/
    kırık/döngüsel link, kök doğrulanamadı, in-tree alias, beklenen
    kapsam dışı yol). Yalnız writer çağrılmadan önce (pre-lock veya
    precondition) ya da replay corroboration sırasında fırlatılır."""


class PromotionContentMismatchError(ApprovalUiError):
    """Pending İÇERİĞİ (case_id / source_document_id) istek
    argümanlarıyla eşleşmiyor veya pending JSON olarak okunamıyor -
    fail-closed, sıfır journal satırı."""


class PromotionResolvedCaseIdMismatchError(ApprovalUiError):
    """İç (kilit-altı) authz'ın çözdüğü case_id, dış (pre-lock)
    authz'ınkinden farklı - Layer A'nın ResolvedCaseIdMismatchError'ı
    ile aynı fail-closed backstop."""


class PromotionWriterPostStateMismatchError(ApprovalUiError):
    """Writer döndü ama diskteki canonical hash deterministik beklenen
    hash'le (veya writer'ın kendi bildirdiği hash'le) eşleşmiyor -
    writer sınırı GEÇİLDİĞİ için coordinator bu istisnayı
    reconciliation_required'a çevirir; asla sessiz başarı."""


class PromotionAuditBindingVerificationFailedError(ApprovalUiError):
    """Safe-replay corroboration başarısız - ne doğrulanmış başarı ne
    doğrulanmış başarısızlık; insan reconciliation'ı gerekir (Layer A
    AuditBindingVerificationFailedError'ının promotion karşılığı)."""

    def __init__(self, *, journal_id: int, idempotency_key: str, reason: str):
        self.journal_id = journal_id
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(
            f"journal_id={journal_id}: promotion safe-replay audit-binding verification failed "
            f"(idempotency_key={idempotency_key!r}): {reason}"
        )


# ----------------------------------------------------------------
# Composite pre-state snapshot - Layer A ile aynı üç alan, bu Slice'ın
# KENDİ versiyon etiketi. Formül `promotion_mutation_adapters.py`
# tarafından BAĞIMSIZ olarak yeniden implement edilir (drift-canary
# testi iki implementasyonun aynı girdide aynı digest'i ürettiğini
# ayrıca kanıtlar).
# ----------------------------------------------------------------

SNAPSHOT_ABSENT = "__absent__"
SNAPSHOT_PRESENT = "__present__"
_SNAPSHOT_VERSION = "row19c3b_slice2.v1"


@dataclass(frozen=True)
class PromotionPreconditionSnapshot:
    pending_sha256: str
    canonical_presence: str
    canonical_sha256: str
    composite_digest: str


def _compute_promotion_snapshot(pending_path: Path, canonical_path: Path) -> PromotionPreconditionSnapshot:
    pending_sha256 = sha256_file(pending_path) or SNAPSHOT_ABSENT
    canonical_presence = SNAPSHOT_PRESENT if Path(canonical_path).exists() else SNAPSHOT_ABSENT
    canonical_sha256 = sha256_file(canonical_path) or SNAPSHOT_ABSENT
    payload = json.dumps(
        {
            "snapshot_version": _SNAPSHOT_VERSION,
            "pending_sha256": pending_sha256,
            "canonical_presence": canonical_presence,
            "canonical_sha256": canonical_sha256,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return PromotionPreconditionSnapshot(
        pending_sha256=pending_sha256,
        canonical_presence=canonical_presence,
        canonical_sha256=canonical_sha256,
        composite_digest=hashlib.sha256(payload).hexdigest(),
    )


# ----------------------------------------------------------------
# Writer-root / nested containment - bu modülün KENDİ bağımsız
# kopyaları (19C-2c çift-bağımsız-helper emsali; adapters kendi
# kopyalarını taşır, iki taraf birbirinden import ETMEZ). Yalnız karar
# içermeyen `src/path_containment.py` primitive'leri paylaşılır.
# ----------------------------------------------------------------


def _resolve_writer_case_root_real(module, case_id: str) -> Path:
    """Writer modülünün KENDİ `CASES_DIR`'ı ÇAĞRI ANINDA okunur (asla
    cache/default-arg); `case_id` segment-doğrulanır ve case kökü
    strict/containment çözülür. Hata her nedende aynı generic sınıfa
    düşer (existence-blind: authz zaten önce koşmuştur)."""
    cases_dir = module.CASES_DIR
    try:
        _path_containment.validate_segment(case_id)
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise PromotionNestedPathContainmentError(
            "Promotion writer case kökü containment doğrulamasından geçemedi."
        ) from error


def _verify_nested_writer(module, case_root_real: Path, case_id: str, raw_path) -> Path:
    """Writer getter'ının RAW `/`-join çıktısını, relative parçaları
    raw path'in kendisinden alarak `resolve_for_create()` üzerinden
    doğrulanmış gerçek konuma çevirir (mevcut hedef -> tam çözülmüş;
    henüz-yok hedef -> en derin doğrulanmış gerçek ata üzerine
    doğrulanmış join)."""
    cases_dir = module.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise PromotionNestedPathContainmentError(
            "Promotion writer yolu beklenen case kapsamı dışında."
        ) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise PromotionNestedPathContainmentError(
            "Promotion writer yolu containment doğrulamasından geçemedi."
        ) from error


def _verify_document_dir(module, case_root_real: Path, case_id: str, document_id: str) -> Path:
    """Fact ailesi: `documents/<document_id>` üyeliği - segment
    doğrulaması + containment + exact-parent membership."""
    try:
        _path_containment.validate_segment(document_id)
        documents_dir_real = _path_containment.resolve_existing(
            case_root_real / "documents", root=case_root_real,
        )
        doc_dir_real = _path_containment.resolve_existing(
            documents_dir_real / document_id, root=case_root_real,
        )
    except _path_containment.PathContainmentError as error:
        raise PromotionNestedPathContainmentError(
            "Promotion doküman dizini containment doğrulamasından geçemedi."
        ) from error
    if doc_dir_real.parent != documents_dir_real:
        raise PromotionNestedPathContainmentError(
            "Promotion doküman dizini beklenen parent'ın doğrudan çocuğu değil (in-tree alias)."
        )
    if not doc_dir_real.is_dir():
        raise PromotionNestedPathContainmentError(
            "Promotion doküman girdisi bir dizin değil."
        )
    return doc_dir_real


@dataclass(frozen=True)
class _PromotionPaths:
    """Bir promotion attempt'inin BEŞLİ doğrulanmış Path paketi +
    çözümlenmiş-kimlik tuple'ı (pre-lock ve kilit-altı türetimlerin
    karşılaştırılması için)."""

    container_dir: Path   # fact: extractions_dir / timeline: timeline_dir
    pending_path: Path
    canonical_path: Path
    history_dir: Path
    reviews_dir: Path

    @property
    def identity(self):
        return (
            str(self.container_dir), str(self.pending_path), str(self.canonical_path),
            str(self.history_dir), str(self.reviews_dir),
        )


def _derive_verified_paths(module, row_key: str, case_root_real: Path, case_id: str, document_id) -> _PromotionPaths:
    if row_key == "fact":
        _verify_document_dir(module, case_root_real, case_id, document_id)
        raw_container = module.get_extractions_dir(case_id, document_id)
        raw_pending = module.get_pending_path(case_id, document_id)
        raw_canonical = module.get_canonical_path(case_id, document_id)
        raw_history = module.get_history_dir(case_id, document_id)
        raw_reviews = module.get_reviews_dir(case_id, document_id)
    else:
        raw_container = module.get_timeline_dir(case_id)
        raw_pending = module.get_pending_path(case_id)
        raw_canonical = module.get_canonical_path(case_id)
        raw_history = module.get_history_dir(case_id)
        raw_reviews = module.get_reviews_dir(case_id)

    return _PromotionPaths(
        container_dir=_verify_nested_writer(module, case_root_real, case_id, raw_container),
        pending_path=_verify_nested_writer(module, case_root_real, case_id, raw_pending),
        canonical_path=_verify_nested_writer(module, case_root_real, case_id, raw_canonical),
        history_dir=_verify_nested_writer(module, case_root_real, case_id, raw_history),
        reviews_dir=_verify_nested_writer(module, case_root_real, case_id, raw_reviews),
    )


def _cross_check_pending_content(row_key: str, resolved_case_id: str, document_id, pending_verified: Path) -> None:
    """Pending İÇERİĞİ ile istek argümanlarının çapraz kontrolü -
    pre-lock VE kilit altında ayrı ayrı çağrılır; okunamayan/uyumsuz
    pending fail-closed reddedilir (sıfır journal satırı)."""
    try:
        with open(pending_verified, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("pending JSON bir nesne değil")
    except Exception as error:
        raise PromotionContentMismatchError(
            "Pending dosyası içerik çapraz-kontrolü için okunamadı/ayrıştırılamadı."
        ) from error
    if data.get("case_id") != resolved_case_id:
        raise PromotionContentMismatchError(
            "Pending içindeki case_id, istekteki case ile eşleşmiyor."
        )
    if row_key == "fact" and data.get("source_document_id") != document_id:
        raise PromotionContentMismatchError(
            "Pending içindeki source_document_id, istekteki document ile eşleşmiyor."
        )


# ----------------------------------------------------------------
# Audit içerik-eşleşmesi (yalnız completed replay corroboration'ı bu
# modülde kullanır; reconciliation adapters kendi BAĞIMSIZ kopyasını
# taşır).
# ----------------------------------------------------------------

_PENDING_HASH_AUDIT_FIELD = {
    "fact": "source_pending_sha256",
    "timeline": "pending_sha256",
}


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _audit_record_matches(row_key: str, record: dict, *, idempotency_key: str,
                          resource_key: str, pre_revision, canonical_sha256: str) -> bool:
    """TAM bağlama kuralı - eksik/boş/uyumsuz HERHANGİ bir değer False
    (asla otomatik kanıt). Aile bayrakları: fact audit'i sabit
    `decision`, timeline audit'i `approved=True and rollback=False`
    taşımak zorundadır (timeline ROLLBACK audit'leri mutation-binding
    alanlarını taşısa bile success evidence olarak ASLA eşleşmez)."""
    if not _nonblank(record.get("mutation_idempotency_key")) or record.get("mutation_idempotency_key") != idempotency_key:
        return False
    if not _nonblank(record.get("mutation_resource_key")) or record.get("mutation_resource_key") != resource_key:
        return False
    if not _nonblank(pre_revision):
        return False
    pending_field = _PENDING_HASH_AUDIT_FIELD[row_key]
    if not _nonblank(record.get(pending_field)) or record.get(pending_field) != pre_revision:
        return False
    if not _nonblank(record.get("canonical_sha256")) or record.get("canonical_sha256") != canonical_sha256:
        return False
    if row_key == "fact":
        if record.get("decision") != "approved_for_canonical_use":
            return False
    else:
        if record.get("approved") is not True or record.get("rollback") is not False:
            return False
    return True


def _scan_promotion_audits(case_root_real: Path, reviews_dir_verified: Path):
    """`*.approval.json` girişlerinin containment-before-stat taraması:
    ad sınıflandırması ÖNCE (saf string), eşleşen HER giriş için
    containment + exact-parent membership HERHANGİ bir stat/open/
    JSON-read'den ÖNCE. Kaçan/kırık/alias giriş TÜM taramayı
    fail-closed durdurur; parse edilemeyen giriş `(path, None)` olarak
    döner (çağıran karar verir). reviews_dir yoksa boş liste."""
    import fnmatch

    if not reviews_dir_verified.is_dir():
        return []
    try:
        raw_entries = sorted(reviews_dir_verified.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise PromotionNestedPathContainmentError(
            "Promotion reviews dizini listelenemedi."
        ) from error
    results = []
    for entry in raw_entries:
        if not fnmatch.fnmatch(entry.name, "*.approval.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise PromotionNestedPathContainmentError(
                "Promotion audit girişi containment doğrulamasından geçemedi."
            ) from error
        if resolved.parent != reviews_dir_verified:
            raise PromotionNestedPathContainmentError(
                "Promotion audit girişi beklenen dizinin dışına çözülüyor (in-tree alias)."
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


COMPLETED_JOURNAL_STATE = "completed"


def _verify_completed_promotion_replay_binding(
    row_key: str,
    paths: _PromotionPaths,
    case_root_real: Path,
    *,
    journal_state: str,
    journal_id: int,
    idempotency_key: str,
    resource_key: str,
    observed_post_hash,
    pre_revision,
):
    """Completed safe-replay corroboration. Başarıda (taze canonical
    sha, eşleşen audit path) döner; HER eksik/boş/uyumsuz değerde
    `PromotionAuditBindingVerificationFailedError` fırlatır. Parametre
    seviyesinde KAPALI: journal_state tam olarak 'completed' olmalıdır."""

    def fail(reason):
        raise PromotionAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key, reason=reason,
        )

    if journal_state != COMPLETED_JOURNAL_STATE:
        fail(f"bu corroboration yalnız 'completed' satır için tanımlıdır (state={journal_state!r})")

    current_canonical_sha256 = sha256_file(paths.canonical_path)
    if current_canonical_sha256 is None:
        fail(f"canonical artefakt şu an mevcut değil: {paths.canonical_path}")
    if not _nonblank(observed_post_hash):
        fail(f"journal satırı boş/eksik observed_post_hash taşıyor ({observed_post_hash!r})")
    if observed_post_hash != current_canonical_sha256:
        fail(
            f"journal observed_post_hash={observed_post_hash!r} ile diskteki canonical "
            f"({current_canonical_sha256!r}) eşleşmiyor"
        )
    if not resource_key.startswith(_CASE_RESOURCE_KEY_PREFIX) or not resource_key[len(_CASE_RESOURCE_KEY_PREFIX):]:
        fail(f"resource_key={resource_key!r} geçerli bir case:<case_id> anahtarı değil")

    entries = _scan_promotion_audits(case_root_real, paths.reviews_dir)
    unparseable = [path for path, record in entries if record is None]
    if unparseable:
        fail(
            f"reviews dizininde parse edilemeyen {len(unparseable)} adet *.approval.json var - "
            "içerik-bağlama güvenle yapılamaz"
        )
    matches = [
        (path, record) for path, record in entries
        if _audit_record_matches(
            row_key, record,
            idempotency_key=idempotency_key, resource_key=resource_key,
            pre_revision=pre_revision, canonical_sha256=current_canonical_sha256,
        )
    ]
    if len(matches) != 1:
        fail(
            f"tam-bağlama eşleşen success audit sayısı {len(matches)} (tam 1 olmalı) - "
            "bu completed satır bağımsızca doğrulanamadı"
        )
    return current_canonical_sha256, matches[0][0]


# ----------------------------------------------------------------
# Authz repo / journal conn kurulumu - Layer A facade'inin kendi
# desenlerinin bağımsız kopyaları (lazy psycopg import disiplini aynı).
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


def _check_argument_shapes(row_key: str, document_id, note, expected_hash=None, *, for_apply: bool):
    if row_key not in PROMOTION_ROW_KEY_TO_MODULE_NAME:
        raise KeyError(f"row_key={row_key!r} is not a known promotion family")
    if row_key == "timeline":
        if document_id is not None:
            raise PromotionArgumentError(
                "timeline promotion'ı document parametresi KABUL ETMEZ (I/O öncesi red)."
            )
        if note is not None:
            raise PromotionArgumentError(
                "timeline promotion'ı note parametresi KABUL ETMEZ (I/O öncesi red)."
            )
    else:
        if for_apply and (not isinstance(document_id, str) or not document_id.strip()):
            raise PromotionArgumentError(
                "fact promotion apply için document ZORUNLUDUR (I/O öncesi red)."
            )
        if document_id is not None and (not isinstance(document_id, str) or not document_id.strip()):
            raise PromotionArgumentError("document boş olamaz.")
        if note is not None and (not isinstance(note, str) or not note.strip()):
            raise PromotionArgumentError("note verildiyse boş/yalnız-boşluk olamaz.")
    if for_apply and (not isinstance(expected_hash, str) or not expected_hash.strip()):
        raise PromotionArgumentError("expected_hash apply için zorunlu, boş olamaz.")


def _normalized_note(note):
    """(writer'a geçecek not metni, secondary_input_hash) çifti.
    None -> sabit varsayılan not + None hash (kimlik/fingerprint
    değişmez); verilmiş not -> whitespace-normalize edilmiş metnin
    sha256'sı fingerprint-only olarak bağlanır."""
    if note is None:
        return FACT_DEFAULT_REVIEW_NOTE, None
    normalized = " ".join(note.split())
    return note, hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------
# PREVIEW (salt-okunur)
# ----------------------------------------------------------------


def preview_promotion(row_key: str, case_id: str, *, document_id=None, principal, authz_repository=None):
    """Salt-okunur preview. SIRA: dış 'read' authz HER filesystem
    probundan/enumeration'dan ÖNCE koşar (bilinmeyen case/document
    varlığı authz öncesi sızmaz). Fact + document verilmemiş ->
    pending'i olan dokümanların containment-güvenli enumerasyonu;
    aksi halde tekil hedefin pending hash'i + validator hazırlık
    sinyali döner."""
    import importlib

    _check_argument_shapes(row_key, document_id, None, for_apply=False)
    module = importlib.import_module(PROMOTION_ROW_KEY_TO_MODULE_NAME[row_key])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "read", repository=repository,
        )

        case_root_real = _resolve_writer_case_root_real(module, resolved_case_id)

        if row_key == "fact" and document_id is None:
            # Enumeration: documents/ altındaki GÜVENLİ doğrudan
            # çocuklar (unsafe çocuk sessizce atlanır -
            # list_contained_dir disipliniyle aynı kural); güvenli bir
            # dokümanın pending ZİNCİRİ bozuksa bu fail-closed raise
            # olur, sessiz atlama değil.
            documents = []
            try:
                documents_dir_real = _path_containment.resolve_existing(
                    case_root_real / "documents", root=case_root_real,
                )
            except _path_containment.PathContainmentError:
                return {"mode": "enumeration", "row_key": row_key, "case_id": resolved_case_id, "documents": []}
            for child in sorted(documents_dir_real.iterdir(), key=lambda p: p.name):
                try:
                    child_real = _path_containment.resolve_existing(child, root=case_root_real)
                except _path_containment.PathContainmentError:
                    continue
                if child_real.parent != documents_dir_real or not child_real.is_dir():
                    continue
                doc_id = child.name
                try:
                    _path_containment.validate_segment(doc_id)
                except _path_containment.PathContainmentError:
                    continue
                paths = _derive_verified_paths(module, "fact", case_root_real, resolved_case_id, doc_id)
                if not paths.pending_path.is_file():
                    continue
                documents.append({
                    "document_id": doc_id,
                    "pending_hash": sha256_file(paths.pending_path),
                    "canonical_exists": paths.canonical_path.is_file(),
                    "canonical_sha256": sha256_file(paths.canonical_path),
                })
            return {"mode": "enumeration", "row_key": row_key, "case_id": resolved_case_id, "documents": documents}

        paths = _derive_verified_paths(module, row_key, case_root_real, resolved_case_id, document_id)
        if not paths.pending_path.is_file():
            raise PendingNotFoundError(f"Pending bulunamadı: {paths.pending_path}")
        _cross_check_pending_content(row_key, resolved_case_id, document_id, paths.pending_path)

        # Gerçek validator - salt-okunur hazırlık sinyali.
        if row_key == "fact":
            try:
                module.validate_pending(paths.pending_path)
                validation_ready = True
            except Exception:
                validation_ready = False
        else:
            review = module.review_pending(paths.pending_path)
            validation_ready = bool(review["ready"])

        return {
            "mode": "single",
            "row_key": row_key,
            "case_id": resolved_case_id,
            "document_id": document_id,
            "pending_path": paths.pending_path,
            "pending_hash": sha256_file(paths.pending_path),
            "canonical_exists": paths.canonical_path.is_file(),
            "canonical_sha256": sha256_file(paths.canonical_path),
            "validation_ready": validation_ready,
        }
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(
                f"WARNING: preview_promotion authz repository close failed: {close_error!r}"
            )


# ----------------------------------------------------------------
# APPLY (koordine, journal'lı, idempotent mutasyon)
# ----------------------------------------------------------------


@dataclass(frozen=True)
class PromotionApprovalResult:
    row_key: str
    document_id: str | None
    canonical_path: Path
    canonical_hash: str | None
    audit_path: Path | None
    stdout: str
    journal_id: int
    replayed: bool


def approve_promotion_mutation(
    row_key: str,
    case_id: str,
    expected_hash: str,
    *,
    document_id=None,
    note=None,
    principal,
    authz_repository=None,
    conn_factory=None,
) -> PromotionApprovalResult:
    """SIRA (Layer A facade'inin kanıtlanmış düzeninin promotion
    karşılığı): (1) argüman şekilleri (saf, I/O'suz); (2) DIŞ
    authorize_case_access('mutate') - hiçbir journal/lock bağlantısı,
    hiçbir artefakt hash'i, hiçbir enumeration ondan önce; (3) writer
    dinamik kökünden pre-lock containment + içerik çapraz-kontrolü +
    composite snapshot; (4) conn + case lock; (5) run_mutation: İÇ
    otoriter authz -> journal gate -> idempotency -> precondition
    (SIFIRDAN kilit-altı yeniden doğrulama; her red sıfır journal
    satırı) -> writer (kilit-altı doğrulanmış Path NESNELERİYLE); (6)
    replay'de tam corroboration; (7) maskelemeyen temizlik."""
    import importlib

    _check_argument_shapes(row_key, document_id, note, expected_hash, for_apply=True)
    module = importlib.import_module(PROMOTION_ROW_KEY_TO_MODULE_NAME[row_key])

    if row_key == "fact":
        effective_note, secondary_input_hash = _normalized_note(note)
    else:
        effective_note, secondary_input_hash = None, None

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        outer_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )

        resource_key = _mutation_lock.case_resource_key(outer_resolved_case_id)

        pre_case_root = _resolve_writer_case_root_real(module, outer_resolved_case_id)
        pre_paths = _derive_verified_paths(module, row_key, pre_case_root, outer_resolved_case_id, document_id)
        if not pre_paths.pending_path.is_file():
            raise PendingNotFoundError(f"Pending bulunamadı: {pre_paths.pending_path}")
        _cross_check_pending_content(row_key, outer_resolved_case_id, document_id, pre_paths.pending_path)

        pre_snapshot = _compute_promotion_snapshot(pre_paths.pending_path, pre_paths.canonical_path)

        if row_key == "fact":
            target_ref = f"fact.{document_id}.canonical"
        else:
            target_ref = "timeline.canonical"

        intent = MutationIntent(
            actor_type="iam_user",
            actor_ref=str(principal.user_id),
            resource_key=resource_key,
            action_family=promotion_action_family_for(row_key),
            target_ref=target_ref,
            target_state=TARGET_STATE,
            pre_hash=pre_snapshot.composite_digest,
            pre_revision=expected_hash,
            secondary_input_hash=secondary_input_hash,
        )
        idempotency_key_for_audit = compute_idempotency_key(intent)

        # Kilit-altı türetimlerin writer_callback'e AYNI NESNELER olarak
        # taşınması için box'lar (facade 19C-3a Slice 2'nin nonlocal
        # rebind deseninin closure karşılığı).
        under_lock_box = {}
        writer_outcome_box = {}

        def authz_callback() -> None:
            inner_resolved_case_id = _authz.authorize_case_access(
                principal, case_id, "mutate", repository=repository,
            )
            if inner_resolved_case_id != outer_resolved_case_id:
                raise PromotionResolvedCaseIdMismatchError(
                    f"outer authz {outer_resolved_case_id!r} çözdü, inner authz "
                    f"{inner_resolved_case_id!r} - kilitlenen resource ile otoriter karar farklı case'i "
                    "tarif ediyor; reddedildi."
                )

        def precondition_callback() -> None:
            # SIFIRDAN, kilit-altı taze türetim: kök attribute'u YENİDEN
            # okunur, zincir YENİDEN doğrulanır - kilit beklerken swap
            # edilen junction/symlink burada yakalanır.
            ul_case_root = _resolve_writer_case_root_real(module, outer_resolved_case_id)
            ul_paths = _derive_verified_paths(module, row_key, ul_case_root, outer_resolved_case_id, document_id)
            if ul_paths.identity != pre_paths.identity:
                raise PreconditionRaceDetectedError(
                    "Bu promotion isteği case kilidini beklerken ilgili dizin/dosyaların çözümlenmiş "
                    "(gerçek) konumu DEĞİŞTİ (link swap veya benzeri). Onay iptal edildi, HİÇBİR "
                    "değişiklik yapılmadı."
                )
            if not ul_paths.pending_path.is_file():
                raise PendingNotFoundError(f"Pending bulunamadı: {ul_paths.pending_path}")
            ul_snapshot = _compute_promotion_snapshot(ul_paths.pending_path, ul_paths.canonical_path)
            if ul_snapshot.composite_digest != pre_snapshot.composite_digest:
                raise PreconditionRaceDetectedError(
                    "Bu promotion isteği case kilidini beklerken pending/canonical durumu DEĞİŞTİ. "
                    "Onay iptal edildi, HİÇBİR değişiklik yapılmadı."
                )
            if ul_snapshot.pending_sha256 != expected_hash:
                raise StaleViewError(
                    "Preview alındıktan sonra pending dosya değişti "
                    f"(beklenen: {expected_hash}, şimdiki: {ul_snapshot.pending_sha256}). Onay iptal edildi."
                )
            _cross_check_pending_content(row_key, outer_resolved_case_id, document_id, ul_paths.pending_path)
            # Deterministik beklenen canonical hash - kilit altında,
            # doğrulanmış pending'den (writer sonrası eşitlik assert'i
            # için).
            under_lock_box["expected_canonical"] = module.compute_expected_canonical_sha256(ul_paths.pending_path)
            under_lock_box["paths"] = ul_paths
            under_lock_box["case_root"] = ul_case_root

        def writer_callback() -> _mutation_coordinator.WriterResult:
            ul = under_lock_box["paths"]
            stdout_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture):
                if row_key == "fact":
                    writer_result = module.promote(
                        pending_path=ul.pending_path,
                        reviewer_ref=PROMOTION_REVIEWER_REF,
                        review_note=effective_note,
                        verified_paths={
                            "extractions_dir": ul.container_dir,
                            "pending_path": ul.pending_path,
                            "canonical_path": ul.canonical_path,
                            "history_dir": ul.history_dir,
                            "reviews_dir": ul.reviews_dir,
                        },
                        mutation_idempotency_key=idempotency_key_for_audit,
                        mutation_resource_key=resource_key,
                        mutation_actor_ref=str(principal.user_id),
                    )
                    audit_path = writer_result["approval_path"]
                    writer_reported_hash = None
                else:
                    writer_result = module.approve_pending(
                        pending_path=ul.pending_path,
                        verified_paths={
                            "timeline_dir": ul.container_dir,
                            "pending_path": ul.pending_path,
                            "canonical_path": ul.canonical_path,
                            "history_dir": ul.history_dir,
                            "reviews_dir": ul.reviews_dir,
                        },
                        mutation_idempotency_key=idempotency_key_for_audit,
                        mutation_resource_key=resource_key,
                        mutation_actor_ref=str(principal.user_id),
                    )
                    audit_path = writer_result["audit_path"]
                    writer_reported_hash = writer_result.get("canonical_sha256")

            observed = sha256_file(ul.canonical_path)
            expected = under_lock_box["expected_canonical"]
            if observed is None or observed != expected:
                raise PromotionWriterPostStateMismatchError(
                    f"Writer döndü ama canonical hash beklenen deterministik değerle eşleşmiyor "
                    f"(beklenen={expected!r}, gözlenen={observed!r}) - reconciliation gerekir."
                )
            if writer_reported_hash is not None and writer_reported_hash != observed:
                raise PromotionWriterPostStateMismatchError(
                    f"Writer'ın bildirdiği canonical hash ({writer_reported_hash!r}) diskle "
                    f"({observed!r}) eşleşmiyor - reconciliation gerekir."
                )
            writer_outcome_box["audit_path"] = audit_path
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
                    replay_case_root = _resolve_writer_case_root_real(module, outer_resolved_case_id)
                    replay_paths = _derive_verified_paths(
                        module, row_key, replay_case_root, outer_resolved_case_id, document_id,
                    )
                    verified_canonical_hash, audit_path = _verify_completed_promotion_replay_binding(
                        row_key, replay_paths, replay_case_root,
                        journal_state=outcome.state,
                        journal_id=outcome.journal_id,
                        idempotency_key=idempotency_key_for_audit,
                        resource_key=resource_key,
                        observed_post_hash=outcome.observed_post_hash,
                        pre_revision=intent.pre_revision,
                    )
                except PromotionNestedPathContainmentError as error:
                    raise PromotionAuditBindingVerificationFailedError(
                        journal_id=outcome.journal_id, idempotency_key=idempotency_key_for_audit,
                        reason=f"replay corroboration sırasında containment hatası: {error}",
                    ) from error
                stdout_text = ""
                canonical_path_result = replay_paths.canonical_path
            else:
                verified_canonical_hash = outcome.observed_post_hash
                stdout_text = outcome.result
                audit_path = writer_outcome_box.get("audit_path")
                canonical_path_result = under_lock_box["paths"].canonical_path

            return PromotionApprovalResult(
                row_key=row_key,
                document_id=document_id,
                canonical_path=canonical_path_result,
                canonical_hash=verified_canonical_hash,
                audit_path=audit_path,
                stdout=stdout_text,
                journal_id=outcome.journal_id,
                replayed=outcome.replayed,
            )
        finally:
            # Maskelemeyen temizlik - Layer A facade'inin 19C-2a FINAL
            # AUDIT REMEDIATION deseni birebir: release'in raise'i
            # loglanır ve düşürülür; False dönüşü görünür kalır;
            # conn.close kendi iç finally'sinde her koşulda koşar.
            try:
                try:
                    released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
                except Exception as release_error:
                    _log_critical_safely(
                        f"CRITICAL: approve_promotion_mutation() lock release RAISED for "
                        f"resource_key={resource_key!r} (advisory_lock_id={advisory_lock_id!r}): "
                        f"{release_error!r} - outcome unchanged, investigate out of band"
                    )
                else:
                    if not released:
                        _log_critical_safely(
                            f"CRITICAL: approve_promotion_mutation() release_lock_session returned False "
                            f"for resource_key={resource_key!r} (advisory_lock_id={advisory_lock_id!r}) - "
                            "outcome unchanged, investigate out of band"
                        )
            finally:
                try:
                    conn.close()
                except Exception as close_error:
                    _log_critical_safely(
                        f"CRITICAL: approve_promotion_mutation() journal connection close failed: "
                        f"{close_error!r} - outcome unchanged"
                    )
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(
                f"WARNING: approve_promotion_mutation authz repository close failed: {close_error!r}"
            )
