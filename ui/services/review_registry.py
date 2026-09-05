# ============================================================
# VERGİ AI - LAWYER UI, REVIEW REGISTRY (Row 18b, Layer B)
#
# 5 ailenin (evidence/argument/risk_strategy/drafting/qa) Layer B
# ("kayıt bazlı inceleme kararı": needs_review -> confirmed/rejected
# veya needs_review -> accepted_for_follow_up/dismissed) akışını TEK
# bir arayüz altında toplar. Bu modül var olan review modüllerinin
# (`src/*_review.py`) İÇ MANTIĞINI (parent-dependency, R1-R6,
# stale-source, previous_state kontrolü, backup/atomic-write/rollback)
# YENİDEN YAZMAZ/KOPYALAMAZ - yalnız onları çağırır. Backend bu
# kuralların TEK OTORİTESİ olarak kalır (kullanıcı kararı, 2026-09-04).
#
# 12 review_kind (doğrulanmış mapping, bkz. Row 18b kapsam turu):
#   evidence.candidate, evidence.suggestion,
#   argument.claim, argument.counterargument, argument.rebuttal,
#     argument.suggestion,
#   risk_strategy.risk, risk_strategy.strategy, risk_strategy.suggestion,
#   drafting.section, drafting.suggestion,
#   qa.suggestion (backend'de record_type PARAMETRESİ YOK - yapay bir
#     record_type İCAT EDİLMEZ, `call_shape="qa_special"` bu farkı
#     registry İÇİNDE gizler).
#
# HEDEF-DURUM SABİTLERİ HİÇBİR YERDE KOPYALANMAZ: `get_allowed_targets()`
# her çağrıda ilgili modülü import edip KENDİ gerçek sabitini (veya
# argument/risk_strategy/drafting için `ALLOWED_TARGETS_BY_TYPE[...]`,
# qa için `ALLOWED_TARGET_STATES`, evidence için
# `CANDIDATE_ALLOWED_TARGETS`/`SUGGESTION_ALLOWED_TARGETS`) CANLI olarak
# döndürür - ikinci bir elle yazılmış kopya YOKTUR (kullanıcı sınırı).
# Aynı ilke array/id/state alan adları için de geçerlidir: argument/
# risk_strategy/drafting KENDİ `ARRAY_FIELD_BY_TYPE`/`ID_FIELD_BY_TYPE`/
# `STATE_FIELD_BY_TYPE` sözlüklerini taşıdığı için bunlar da CANLI
# okunur, KOPYALANMAZ. Yalnız evidence/qa bu sözlükleri taşımadığı için
# (kaynak kodu okunarak doğrulandı - `find_candidate`/`find_suggestion`
# fonksiyon gövdelerinde hardcoded), bu ikisi için array/id/state alan
# adları registry'nin KENDİ sabit metadata'sı olarak tutulur; bu iki
# özel durum, ilgili modülün KENDİ `find_candidate`/`find_suggestion`
# fonksiyonuna karşı `test_review_service_isolated.py`'de tutarlılık
# testiyle doğrulanır (bkz. o dosyadaki "field metadata tutarlılığı"
# testleri).
#
# KİMLİK: `record_id` TEK BAŞINA asla registry/URL anahtarı DEĞİLDİR -
# 5 aileden 4'ünde ve QA'da `suggestion_id` alan adı TEKRARLANDIĞI için
# (bağımsız namespace'ler, çakışabilir) her yerde BİLEŞİK kimlik
# `(review_kind, record_id)` kullanılır; main.py'nin route şeması da
# `/cases/{case_id}/reviews/{review_kind}/{record_id}` biçimindedir.
#
# FORMDAN ASLA KABUL EDİLMEYEN DEĞERLER: modül adı, callable, canonical
# path, array/id/state alan adı, `reviewer_ref`. Bunların TAMAMI bu
# registry içinde SUNUCU TARAFINDA çözülür - main.py yalnız
# `review_kind` (sabit 12 değerlik allowlist), `record_id`,
# `target_state`, `review_note`, `expected_hash`, `csrf_token`'ı
# formdan/URL'den alır.
# ============================================================

import importlib
import json
from pathlib import Path

from . import paths
from .common import (
    ReviewUiError,
    UnknownReviewKindError,
    ReviewRecordNotFoundError,
    ReviewStaleViewError,
    ReviewLiveViewInvalidError,
    InvalidReviewNoteError,
    sha256_file,
)

# ============================================================
# 5 GERÇEK domain hata sınıfı (allowlist) - main.py'nin FastAPI
# importu OLMADAN da (bu modül saf Python, `test_review_service_
# isolated.py` tarafından FastAPI'siz test edilir) sınıflandırma
# yapılabilmesi için BURADA, tek yerde tutulur; main.py bunu
# BURADAN import eder (ikinci bir tanım/kopya YOK). `services/
# paths.py` bu noktaya kadar zaten `src/`'yi sys.path'e eklemiş olur.
# ============================================================

from evidence_review import EvidenceReviewError
from argument_review import ArgumentReviewError
from risk_strategy_review import RiskStrategyReviewError
from drafting_review import DraftingReviewError
from qa_review import QaReviewError

DOMAIN_REVIEW_ERROR_TYPES = (
    EvidenceReviewError,
    ArgumentReviewError,
    RiskStrategyReviewError,
    DraftingReviewError,
    QaReviewError,
)


def is_domain_review_error(exc):
    """True yalnız `exc`, 5 GERÇEK, doğrulanmış domain hata sınıfından
    (`DOMAIN_REVIEW_ERROR_TYPES`) biriyse - main.py bu ayrıma göre
    mesajı OLDUĞU GİBİ mi gösterecek yoksa generic mi kalacak karar
    verir (kullanıcı kararı, 2026-09-04)."""

    return isinstance(exc, DOMAIN_REVIEW_ERROR_TYPES)


REVIEW_NOTE_MAX_LENGTH = 2000


# ============================================================
# 12 review_kind REGISTRY - yalnız modül/validator adları + (varsa)
# `record_type` + `call_shape`. evidence/qa için array/id/state alan
# adları da burada (bkz. modül docstring'i - bu iki modül kendi
# BY_TYPE sözlüklerini taşımaz). Hedef-durum sabiti BURADA ASLA
# TUTULMAZ - her zaman `get_allowed_targets()` ile canlı okunur.
# ============================================================

REVIEW_KIND_REGISTRY = {
    "evidence.candidate": {
        "review_kind": "evidence.candidate", "row_no": 12,
        "label": "Evidence Agent - Candidate (Layer B)",
        "module": "evidence_review",
        "validator_module": "evidence_validator",
        "validator_fn": "validate_evidence_analysis",
        "validator_path_kw": "evidence_path",
        "record_type": "candidate", "call_shape": "with_record_type",
        "array_field": "evidence_candidates", "id_field": "candidate_id",
        "state_field": "review_state",
    },
    "evidence.suggestion": {
        "review_kind": "evidence.suggestion", "row_no": 12,
        "label": "Evidence Agent - Suggestion (Layer B)",
        "module": "evidence_review",
        "validator_module": "evidence_validator",
        "validator_fn": "validate_evidence_analysis",
        "validator_path_kw": "evidence_path",
        "record_type": "suggestion", "call_shape": "with_record_type",
        "array_field": "evidence_agent_suggestions", "id_field": "suggestion_id",
        "state_field": "suggestion_review_state",
    },
    "argument.claim": {
        "review_kind": "argument.claim", "row_no": 13,
        "label": "Argument Agent - Claim (Layer B)",
        "module": "argument_review",
        "validator_module": "argument_validator",
        "validator_fn": "validate_argument_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "claim", "call_shape": "with_record_type",
    },
    "argument.counterargument": {
        "review_kind": "argument.counterargument", "row_no": 13,
        "label": "Argument Agent - Counterargument (Layer B)",
        "module": "argument_review",
        "validator_module": "argument_validator",
        "validator_fn": "validate_argument_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "counterargument", "call_shape": "with_record_type",
    },
    "argument.rebuttal": {
        "review_kind": "argument.rebuttal", "row_no": 13,
        "label": "Argument Agent - Rebuttal (Layer B)",
        "module": "argument_review",
        "validator_module": "argument_validator",
        "validator_fn": "validate_argument_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "rebuttal", "call_shape": "with_record_type",
    },
    "argument.suggestion": {
        "review_kind": "argument.suggestion", "row_no": 13,
        "label": "Argument Agent - Suggestion (Layer B)",
        "module": "argument_review",
        "validator_module": "argument_validator",
        "validator_fn": "validate_argument_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "suggestion", "call_shape": "with_record_type",
    },
    "risk_strategy.risk": {
        "review_kind": "risk_strategy.risk", "row_no": 14,
        "label": "Risk / Strategy Agent - Risk (Layer B)",
        "module": "risk_strategy_review",
        "validator_module": "risk_strategy_validator",
        "validator_fn": "validate_risk_strategy_analysis",
        # NOT: gerçek fonksiyonun path kwarg adı `arguments_path`dır
        # (kaynak kodda böyle - muhtemelen argument_validator'dan
        # kopya-miras bir isimlendirme artığı). Burada İCAT EDİLMEDİ,
        # `src/risk_strategy_validator.py` okunarak doğrulandı.
        "validator_path_kw": "arguments_path",
        "record_type": "risk", "call_shape": "with_record_type",
    },
    "risk_strategy.strategy": {
        "review_kind": "risk_strategy.strategy", "row_no": 14,
        "label": "Risk / Strategy Agent - Strategy (Layer B)",
        "module": "risk_strategy_review",
        "validator_module": "risk_strategy_validator",
        "validator_fn": "validate_risk_strategy_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "strategy", "call_shape": "with_record_type",
    },
    "risk_strategy.suggestion": {
        "review_kind": "risk_strategy.suggestion", "row_no": 14,
        "label": "Risk / Strategy Agent - Suggestion (Layer B)",
        "module": "risk_strategy_review",
        "validator_module": "risk_strategy_validator",
        "validator_fn": "validate_risk_strategy_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "suggestion", "call_shape": "with_record_type",
    },
    "drafting.section": {
        "review_kind": "drafting.section", "row_no": 15,
        "label": "Drafting Agent - Section (Layer B)",
        "module": "drafting_review",
        "validator_module": "drafting_validator",
        "validator_fn": "validate_drafting_analysis",
        "validator_path_kw": "drafting_path",
        "record_type": "section", "call_shape": "with_record_type",
    },
    "drafting.suggestion": {
        "review_kind": "drafting.suggestion", "row_no": 15,
        "label": "Drafting Agent - Suggestion (Layer B)",
        "module": "drafting_review",
        "validator_module": "drafting_validator",
        "validator_fn": "validate_drafting_analysis",
        "validator_path_kw": "drafting_path",
        "record_type": "suggestion", "call_shape": "with_record_type",
    },
    "qa.suggestion": {
        "review_kind": "qa.suggestion", "row_no": 16,
        "label": "QA Agent - Suggestion (Layer B)",
        "module": "qa_review",
        "validator_module": "qa_validator",
        "validator_fn": "validate_qa_analysis",
        "validator_path_kw": "qa_path",
        # Backend `qa_review.apply_review_transition`'ın imzasında
        # `record_type` PARAMETRESİ YOKTUR (yalnız `suggestion_id`
        # pozisyonel alır) - yapay bir `record_type` İCAT EDİLMEZ.
        "record_type": None, "call_shape": "qa_special",
        "array_field": "qa_agent_suggestions", "id_field": "suggestion_id",
        "state_field": "suggestion_review_state",
    },
}


def _get_entry(review_kind):

    entry = REVIEW_KIND_REGISTRY.get(review_kind)

    if entry is None:

        raise UnknownReviewKindError(f"Bilinmeyen review_kind: {review_kind!r}")

    return entry


def _import_module(name):

    return importlib.import_module(name)


# ============================================================
# ALAN ADLARI - argument/risk_strategy/drafting için CANLI modül
# sabitlerinden okunur (KOPYA YOK); evidence/qa için registry'nin
# kendi (koddan doğrulanmış) sabit metadata'sı kullanılır (bu iki
# modül BY_TYPE sözlüğü TAŞIMAZ).
# ============================================================

def get_field_names(review_kind):

    entry = _get_entry(review_kind)
    module = _import_module(entry["module"])

    array_by_type = getattr(module, "ARRAY_FIELD_BY_TYPE", None)

    if array_by_type is not None:

        record_type = entry["record_type"]

        return (
            array_by_type[record_type],
            module.ID_FIELD_BY_TYPE[record_type],
            module.STATE_FIELD_BY_TYPE[record_type],
        )

    return entry["array_field"], entry["id_field"], entry["state_field"]


# ============================================================
# HEDEF-DURUM ALLOWLIST'İ - HİÇBİR ZAMAN KOPYALANMAZ, her çağrıda
# ilgili modülün KENDİ gerçek sabit nesnesi (aynı `set` referansı)
# döndürülür.
# ============================================================

def get_allowed_targets(review_kind):

    entry = _get_entry(review_kind)
    module = _import_module(entry["module"])

    if entry["call_shape"] == "qa_special":

        return module.ALLOWED_TARGET_STATES

    allowed_by_type = getattr(module, "ALLOWED_TARGETS_BY_TYPE", None)

    if allowed_by_type is not None:

        return allowed_by_type[entry["record_type"]]

    if entry["record_type"] == "candidate":

        return module.CANDIDATE_ALLOWED_TARGETS

    return module.SUGGESTION_ALLOWED_TARGETS


def get_canonical_path(review_kind, case_id):

    entry = _get_entry(review_kind)
    module = _import_module(entry["module"])

    # `qa_review.get_canonical_path` KENDİ tanımı değildir - modül
    # `from qa_approval import get_canonical_path` ile onu KENDİ
    # namespace'ine import eder (kaynak kodu okunarak doğrulandı); bu
    # yüzden `module.get_canonical_path(case_id)` HER 5 modül için de
    # tekdüze çalışır - registry burada modüller arası bu farkı
    # AYRICA ele almaz.
    return module.get_canonical_path(case_id)


# ============================================================
# review_note DOĞRULAMASI - backend `apply_review_transition` bu
# alanı HİÇBİR ŞEKİLDE doğrulamaz (serbest metin, avukatın kendi
# notu) - kontrol TAMAMEN bu fonksiyonda, main.py'nin route'u bunu
# ÇAĞIRARAK uygular (ikinci bir elle yazılmış kopya YOK). İçerik
# güvenliği/yasaklı ifade kontrolü KASITLI olarak UYGULANMAZ
# (kullanıcı kararı, 2026-09-04).
# ============================================================

def normalize_review_note(raw_note):

    if not isinstance(raw_note, str):

        raise InvalidReviewNoteError("review_note bir metin olmalı.")

    trimmed = raw_note.strip()

    if not trimmed:

        raise InvalidReviewNoteError("İnceleme notu boş olamaz.")

    if len(trimmed) > REVIEW_NOTE_MAX_LENGTH:

        raise InvalidReviewNoteError(
            f"İnceleme notu en fazla {REVIEW_NOTE_MAX_LENGTH} karakter olabilir "
            f"(gönderilen: {len(trimmed)} karakter)."
        )

    return trimmed


# ============================================================
# FAIL-CLOSED CANONICAL YÜKLEME - 18a'nın `live_view.py` desenindeki
# AYNI ilke: canonical dosya VARSA, ilgili ailenin KENDİ gerçek
# validator fonksiyonu (`raise_on_error=False`) ÖNCE çalıştırılır;
# valid=False ise `ReviewLiveViewInvalidError` fail-closed fırlatılır
# - hiçbir kayıt ASLA doğrulanmadan listelenmez/render edilmez.
# Canonical dosya HENÜZ YOKSA (Layer A promote edilmemiş - evidence
# case_0001 için şu an bu durumda) bu bir HATA DEĞİLDİR, yalnız
# "henüz canonical yok" bilgisidir (Layer A'daki `canonical_exists`
# ile AYNI ilke).
# ============================================================

def _load_and_validate_canonical(review_kind, case_id):
    """
    REMEDIASYON (2026-09-05, targeted route-test isolation turu):
    gerçek validator fonksiyonları (`evidence_validator.validate_evidence_analysis`
    vb.) `raise_on_error=False` ile çağrılsa BİLE, kendi ÖN KOŞUL
    yüklemelerinde (ör. `load_case`/`load_canonical_issues` - case'in
    kendi `case.json`/`issues.json` gibi yukarı akış dosyalarını
    okuma) `raise_on_error` bayrağından TAMAMEN BAĞIMSIZ olarak ham
    `FileNotFoundError`/`json.JSONDecodeError` vb. fırlatabiliyor
    (kaynak kodu okunarak doğrulandı - `raise_on_error` yalnız
    TOPLANMIŞ şema/semantik hata listesinin sonda raise edilip
    edilmeyeceğini kontrol ediyor, ön koşul yükleme hatalarını DEĞİL).
    Bu, `list_reviewable`/`get_review_record`'ın (dolayısıyla
    `reviews_list`/`review_detail_page` route'larının) BEKLENMEYEN bir
    exception ile çökebileceği anlamına geliyordu - fail-closed
    prensibi bunu KAPSAMIYORDU. Düzeltme: bu fonksiyonun YAPTIĞI HER
    ŞEY (dosya okuma + validator çağrısı) TEK bir korumalı blokta -
    HERHANGİ bir beklenmeyen exception, backend'in İÇ MANTIĞI
    DEĞİŞTİRİLMEDEN, buradaki ZATEN VAR OLAN fail-closed sözleşmesine
    (`ReviewLiveViewInvalidError`) dönüştürülür. Gerçek hata yalnız bu
    exception'ın `str()`'ine (main.py'de yalnız loglanır, tarayıcıya
    ASLA gösterilmez) yansır.
    """

    entry = _get_entry(review_kind)
    module = _import_module(entry["module"])

    canonical_path = module.get_canonical_path(case_id)

    if not canonical_path.exists():

        return None, canonical_path

    try:

        with open(canonical_path, "r", encoding="utf-8") as file:

            analysis = json.load(file)

        validator_module = _import_module(entry["validator_module"])
        validator_fn = getattr(validator_module, entry["validator_fn"])

        kwargs = {
            entry["validator_path_kw"]: canonical_path,
            "expected_case_id": case_id,
            "raise_on_error": False,
        }

        result = validator_fn(**kwargs)

    except Exception as error:

        raise ReviewLiveViewInvalidError(
            f"{review_kind}: canonical dosyası okunurken/doğrulanırken "
            f"beklenmeyen bir hata oluştu ({type(error).__name__}: {error}) "
            "- fail-closed, render EDİLMEDİ."
        ) from error

    if not result.get("valid"):

        raise ReviewLiveViewInvalidError(
            f"{review_kind} canonical dosyası kendi doğrulamasından GEÇEMEDİ "
            f"({len(result.get('errors', []))} hata) - fail-closed, render "
            "EDİLMEDİ:\n"
            + "\n".join(f"- {e}" for e in result.get("errors", [])[:20])
        )

    return analysis, canonical_path


def list_reviewable(review_kind, case_id):
    """
    Döner: {
      "canonical_exists": bool,
      "canonical_path": Path,
      "canonical_hash": str | None,   # yalnız canonical_exists=True ise
      "items": [record dict, ...],    # yalnız state_field == "needs_review"
      "id_field": str | None,
      "state_field": str | None,
    }
    Şemaya göre GEÇERLİ fakat GERÇEKTEN boş bir array (ör. Drafting/QA
    case_0001 için) `items=[]` olarak döner - bu bir HATA DEĞİLDİR,
    "incelenecek kayıt yok" durumudur.
    """

    case_id = paths.resolve_case_id(case_id)
    entry = _get_entry(review_kind)

    analysis, canonical_path = _load_and_validate_canonical(review_kind, case_id)

    if analysis is None:

        return {
            "canonical_exists": False, "canonical_path": canonical_path,
            "canonical_hash": None, "items": [],
            "id_field": None, "state_field": None,
        }

    array_field, id_field, state_field = get_field_names(review_kind)

    records = analysis.get(array_field, [])

    if not isinstance(records, list):

        # Şemaya göre bu alan zaten yukarıdaki validator tarafından
        # yakalanmış OLMALIYDI - savunma derinliği amaçlı burada da
        # fail-closed (eksik/bozuk array asla sessizce boşa çevrilmez).
        raise ReviewLiveViewInvalidError(
            f"{review_kind}: '{array_field}' alanı liste değil - fail-closed."
        )

    items = [r for r in records if isinstance(r, dict) and r.get(state_field) == "needs_review"]

    return {
        "canonical_exists": True, "canonical_path": canonical_path,
        "canonical_hash": sha256_file(canonical_path),
        "items": items, "id_field": id_field, "state_field": state_field,
    }


def get_review_record(review_kind, case_id, record_id):
    """
    SALT OKUNUR. `record_id` yalnız `list_reviewable()`'ın GERÇEKTEN
    döndürdüğü, hâlâ `needs_review` durumundaki bir kayıtla eşleşiyorsa
    kabul edilir - zaten terminal duruma geçmiş veya hiç var olmamış
    bir `record_id` ASLA render edilmez (path/ID traversal değil ama
    AYNI ilke: yalnız gerçek adaylarla eşleşen kimlikler kabul edilir).
    """

    listing = list_reviewable(review_kind, case_id)

    if not listing["canonical_exists"]:

        raise ReviewRecordNotFoundError(
            f"{review_kind}: canonical dosya henüz mevcut değil."
        )

    id_field = listing["id_field"]

    record = next((r for r in listing["items"] if r.get(id_field) == record_id), None)

    if record is None:

        raise ReviewRecordNotFoundError(
            f"{review_kind}/{record_id}: needs_review durumunda bulunamadı."
        )

    return {
        "record": record, "canonical_path": listing["canonical_path"],
        "canonical_hash": listing["canonical_hash"],
    }


# ============================================================
# MUTASYON - gerçek `apply_review_transition`'ı ÇAĞIRIR, İÇ MANTIĞINI
# (parent-dependency/R1-R6/stale-source/previous_state) YENİDEN
# UYGULAMAZ. `reviewer_ref` SUNUCU TARAFINDA SABİTTİR
# ("local_lawyer_ui") - DOĞRULANMIŞ bir kişi kimliği DEĞİLDİR, yalnız
# bu isteğin Lawyer UI'dan geldiğini gösteren bir PROVENANCE
# etiketidir; formdan/URL'den/başka bir client girdisinden ASLA
# alınmaz (kullanıcı kararı, 2026-09-04). `canonical_path_override`/
# `audit_dir_override` YALNIZ izole testler içindir - main.py bu iki
# parametreyi ASLA GEÇMEZ (production'da her zaman None, gerçek
# per-case path'ler kullanılır) - HTTP isteğinden gelen hiçbir path
# burada ASLA kabul edilmez.
# ============================================================

REVIEWER_REF = "local_lawyer_ui"


def apply_transition(
    review_kind, case_id, record_id, target_state, review_note, expected_hash,
    canonical_path_override=None, audit_dir_override=None,
):

    case_id = paths.resolve_case_id(case_id)
    entry = _get_entry(review_kind)

    trimmed_note = normalize_review_note(review_note)

    allowed_targets = get_allowed_targets(review_kind)

    if target_state not in allowed_targets:

        raise ReviewUiError(
            f"Geçersiz hedef durum: {target_state!r} "
            f"(izin verilen: {sorted(allowed_targets)})."
        )

    module = _import_module(entry["module"])

    canonical_path = (
        canonical_path_override
        if canonical_path_override is not None
        else module.get_canonical_path(case_id)
    )

    if not canonical_path.exists():

        raise ReviewRecordNotFoundError(f"Canonical dosya bulunamadı: {canonical_path}")

    current_hash = sha256_file(canonical_path)

    if current_hash != expected_hash:

        raise ReviewStaleViewError(
            "Bu inceleme ekranı açıldıktan sonra canonical dosya değişti "
            f"(o zamanki hash: {expected_hash}, şimdiki: {current_hash}). "
            "İşlem iptal edildi - lütfen sayfayı yenileyip tekrar deneyin."
        )

    call_kwargs = {}

    if canonical_path_override is not None:

        call_kwargs["canonical_path"] = canonical_path_override

    if audit_dir_override is not None:

        call_kwargs["audit_dir"] = audit_dir_override

    if entry["call_shape"] == "qa_special":

        result = module.apply_review_transition(
            case_id, record_id, target_state, REVIEWER_REF, trimmed_note,
            **call_kwargs,
        )

    else:

        result = module.apply_review_transition(
            case_id, entry["record_type"], record_id, target_state,
            REVIEWER_REF, trimmed_note, **call_kwargs,
        )

    return result


# ============================================================
# TÜM CASE İÇİN İNCELEME DURUMU ÖZETİ (İncelemeler listesi ekranı)
# ============================================================

def full_case_review_status(case_id):

    case_id = paths.resolve_case_id(case_id)

    rows = []

    for review_kind, entry in REVIEW_KIND_REGISTRY.items():

        try:

            listing = list_reviewable(review_kind, case_id)

        except ReviewLiveViewInvalidError:

            # Tarayıcıya YALNIZ genel/sabit bir durum gösterilir - bu
            # istisnanın `str()` içeriği main.py'de YALNIZ loglanır,
            # burada/şablonda ASLA render edilmez.
            rows.append({
                "review_kind": review_kind, "row_no": entry["row_no"],
                "label": entry["label"], "kind": "invalid",
                "pending_count": 0, "items": [],
            })
            continue

        rows.append({
            "review_kind": review_kind, "row_no": entry["row_no"],
            "label": entry["label"], "kind": "reviewable",
            "canonical_exists": listing["canonical_exists"],
            "pending_count": len(listing["items"]),
            "items": listing["items"], "id_field": listing["id_field"],
        })

    rows.sort(key=lambda r: (r["row_no"], r["review_kind"]))

    return rows
