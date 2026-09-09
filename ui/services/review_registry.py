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
from . import review_mutation_facade as _review_mutation_facade
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
# ROW 19C-2b: this module's OWN `_default_authz_repository()` -
# formerly `apply_transition()`'s own fallback whenever a caller (in
# production) passed `authz_repository=None` - is REMOVED.
# `apply_transition()` no longer calls `authz.authorize_case_access()`
# itself at all (it now delegates the ENTIRE mutation, authz included,
# to `review_mutation_facade.apply_review_mutation()` - see that
# function's own docstring) - so the fallback that actually applies
# now, whenever `authz_repository=None` reaches the facade, is THAT
# module's OWN `_default_authz_repository()` (mirrors Row 19C-2a Step 7's
# identical removal of `approval_registry.py`'s own copy - see that
# module's own header comment for the full rationale: a duplicated,
# potentially-diverging SECOND authz call site is exactly what this
# avoids). A test that used to monkeypatch `review_registry._default_
# authz_repository` to affect `apply_transition()`'s production-default
# authz repository must instead monkeypatch `ui.services.review_
# mutation_facade._default_authz_repository` from this same commit
# onward - mirrors `ui/tests/test_routes.py`'s own identical migration
# for Layer A (Row 19C-2a Step 8).
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

# ROW 19C-2b: `audit_dir_getter`/`domain_error_class` are ADDITIVE
# per-entry metadata for the new coordinated mutation path
# (`review_mutation_facade.py`). `audit_dir_getter` names each
# backend's OWN, differently-named audit-directory getter function
# (`get_evidence_review_audit_dir`, `get_argument_review_audit_dir`,
# ...) - kaynak kodu okunarak doğrulandı, HİÇBİR ortak string şablonu
# İCAT EDİLMEDİ. `domain_error_class` is the ALREADY-imported (see
# above) real exception class each backend raises - reused directly,
# never re-derived from a name string. Both fields are keyed per
# review_kind (repeating the same value across review_kinds that share
# one module) - matching this registry's EXISTING style for
# `validator_module`/`validator_fn` above.
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
        "audit_dir_getter": "get_evidence_review_audit_dir",
        "domain_error_class": EvidenceReviewError,
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
        "audit_dir_getter": "get_evidence_review_audit_dir",
        "domain_error_class": EvidenceReviewError,
    },
    "argument.claim": {
        "review_kind": "argument.claim", "row_no": 13,
        "label": "Argument Agent - Claim (Layer B)",
        "module": "argument_review",
        "validator_module": "argument_validator",
        "validator_fn": "validate_argument_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "claim", "call_shape": "with_record_type",
        "audit_dir_getter": "get_argument_review_audit_dir",
        "domain_error_class": ArgumentReviewError,
    },
    "argument.counterargument": {
        "review_kind": "argument.counterargument", "row_no": 13,
        "label": "Argument Agent - Counterargument (Layer B)",
        "module": "argument_review",
        "validator_module": "argument_validator",
        "validator_fn": "validate_argument_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "counterargument", "call_shape": "with_record_type",
        "audit_dir_getter": "get_argument_review_audit_dir",
        "domain_error_class": ArgumentReviewError,
    },
    "argument.rebuttal": {
        "review_kind": "argument.rebuttal", "row_no": 13,
        "label": "Argument Agent - Rebuttal (Layer B)",
        "module": "argument_review",
        "validator_module": "argument_validator",
        "validator_fn": "validate_argument_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "rebuttal", "call_shape": "with_record_type",
        "audit_dir_getter": "get_argument_review_audit_dir",
        "domain_error_class": ArgumentReviewError,
    },
    "argument.suggestion": {
        "review_kind": "argument.suggestion", "row_no": 13,
        "label": "Argument Agent - Suggestion (Layer B)",
        "module": "argument_review",
        "validator_module": "argument_validator",
        "validator_fn": "validate_argument_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "suggestion", "call_shape": "with_record_type",
        "audit_dir_getter": "get_argument_review_audit_dir",
        "domain_error_class": ArgumentReviewError,
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
        "audit_dir_getter": "get_risk_strategy_review_audit_dir",
        "domain_error_class": RiskStrategyReviewError,
    },
    "risk_strategy.strategy": {
        "review_kind": "risk_strategy.strategy", "row_no": 14,
        "label": "Risk / Strategy Agent - Strategy (Layer B)",
        "module": "risk_strategy_review",
        "validator_module": "risk_strategy_validator",
        "validator_fn": "validate_risk_strategy_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "strategy", "call_shape": "with_record_type",
        "audit_dir_getter": "get_risk_strategy_review_audit_dir",
        "domain_error_class": RiskStrategyReviewError,
    },
    "risk_strategy.suggestion": {
        "review_kind": "risk_strategy.suggestion", "row_no": 14,
        "label": "Risk / Strategy Agent - Suggestion (Layer B)",
        "module": "risk_strategy_review",
        "validator_module": "risk_strategy_validator",
        "validator_fn": "validate_risk_strategy_analysis",
        "validator_path_kw": "arguments_path",
        "record_type": "suggestion", "call_shape": "with_record_type",
        "audit_dir_getter": "get_risk_strategy_review_audit_dir",
        "domain_error_class": RiskStrategyReviewError,
    },
    "drafting.section": {
        "review_kind": "drafting.section", "row_no": 15,
        "label": "Drafting Agent - Section (Layer B)",
        "module": "drafting_review",
        "validator_module": "drafting_validator",
        "validator_fn": "validate_drafting_analysis",
        "validator_path_kw": "drafting_path",
        "record_type": "section", "call_shape": "with_record_type",
        "audit_dir_getter": "get_drafting_review_audit_dir",
        "domain_error_class": DraftingReviewError,
    },
    "drafting.suggestion": {
        "review_kind": "drafting.suggestion", "row_no": 15,
        "label": "Drafting Agent - Suggestion (Layer B)",
        "module": "drafting_review",
        "validator_module": "drafting_validator",
        "validator_fn": "validate_drafting_analysis",
        "validator_path_kw": "drafting_path",
        "record_type": "suggestion", "call_shape": "with_record_type",
        "audit_dir_getter": "get_drafting_review_audit_dir",
        "domain_error_class": DraftingReviewError,
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
        "audit_dir_getter": "get_qa_review_audit_dir",
        "domain_error_class": QaReviewError,
        # ROW 19C-3a SLICE 2: `qa_review.py` has NO `CASES_DIR` attribute
        # of its own (verified by direct reading) - it imports
        # `get_qa_dir`/`get_canonical_path` as FUNCTIONS from
        # `qa_approval`, never binding `CASES_DIR` itself. The path-
        # containment anchor for THIS review_kind must therefore be
        # `qa_approval` (which DOES have one - `from qa_discovery import
        # CASES_DIR`, a real, patchable module attribute despite being
        # imported by value, same shape `orchestrator_approval.py` uses)
        # - NOT `qa_review` (this entry's own `"module"` value). This is
        # the ONE entry needing this override; the other 11 default to
        # their own `"module"` (see `cases_dir_module_name()` below) -
        # this field is consulted ONLY for path-root anchor selection,
        # never for authz/action-family/audit/idempotency.
        "cases_dir_module": "qa_approval",
    },
}


def cases_dir_module_name(review_kind):
    """The module name whose OWN `CASES_DIR` attribute anchors path-
    containment verification for `review_kind` - `entry["cases_dir_
    module"]` when explicitly set (today: only `qa.suggestion`),
    otherwise `entry["module"]` itself (the same module the review
    backend's own `get_canonical_path`/`get_*_review_audit_dir` getters
    already live on). A pure, additive metadata lookup - never consulted
    for authz/action-family/audit/idempotency, only for choosing which
    module's `CASES_DIR` to read."""

    entry = _get_entry(review_kind)

    return entry.get("cases_dir_module", entry["module"])


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
# UYGULAMAZ. `reviewer_ref` SUNUCU TARAFINDA, KAPALI bir vocabulary'den
# seçilir - DOĞRULANMIŞ bir kişi kimliği DEĞİLDİR, yalnız bu isteğin
# HANGİ KANALDAN (web Lawyer UI mi, `ui.cli_mutate` mi) geldiğini
# gösteren bir PROVENANCE etiketidir; formdan/URL'den/başka bir client
# girdisinden ASLA alınmaz (kullanıcı kararı, 2026-09-04; Row 19C-3b
# Slice 1'de KAPALI 2-değerli vocabulary'e genişletildi - bkz. aşağıdaki
# ROW 19C-3b bölümü). `canonical_path_override`/`audit_dir_override`
# YALNIZ izole testler içindir - main.py bu iki parametreyi ASLA GEÇMEZ
# (production'da her zaman None, gerçek per-case path'ler kullanılır) -
# HTTP isteğinden gelen hiçbir path burada ASLA kabul edilmez.
# ============================================================

REVIEWER_REF = "local_lawyer_ui"

# ============================================================
# ROW 19C-3b SLICE 1 - reviewer_ref KAPALI VOCABULARY.
#
# `ui.cli_mutate`'in Layer B review CLI dispatcher'ı, aynı
# `apply_transition()`'ı web route'unun (`ui/main.py`) kullandığı
# ŞEKİLDE çağırır - tek fark, `reviewer_ref=LOCAL_CLI_REVIEWER_REF`
# geçmesidir (web hiçbir zaman bu keyword'ü geçmez, varsayılan
# `REVIEWER_REF`'i kullanmaya devam eder - bu yüzden bu ekleme web
# yolu için BYTE-FOR-BYTE davranış değişikliği YARATMAZ).
#
# Bu iki sabit DIŞINDA HİÇBİR string kabul edilmez - `apply_transition()`
# aşağıda, principal kontrolünden HEMEN SONRA, HERHANGİ bir DB/
# filesystem/lock/journal erişiminden ÖNCE bunu doğrular. Bu asla bir
# kullanıcı/domain reddi DEĞİLDİR - `ui/main.py` ve `ui/cli_mutate.py`
# HER İKİSİ de yalnız bu iki sabitten BİRİNİ geçer; başka bir değerin
# buraya ulaşması yalnız bir ÇAĞIRAN HATASI (programming error) olabilir,
# bu yüzden `InvalidReviewerRefError` `ValueError`'dan türetilir (bu
# dosyanın `ReviewUiError` ailesinden DEĞİL - o aile yalnız normal
# kullanımla ulaşılabilir, GERÇEK domain reddi için ayrılmıştır).
# ============================================================

LOCAL_CLI_REVIEWER_REF = "local_lawyer_cli"

ALLOWED_REVIEWER_REFS = frozenset({REVIEWER_REF, LOCAL_CLI_REVIEWER_REF})


class InvalidReviewerRefError(ValueError):
    """Raised by `apply_transition()` when `reviewer_ref` is not exactly
    one of `ALLOWED_REVIEWER_REFS`. Reachable ONLY by a caller bug -
    `ui/main.py` and `ui/cli_mutate.py` each ever pass exactly one fixed
    constant, never a derived or user-supplied string - never a
    legitimate domain rejection an end-user action could trigger."""


def apply_transition(
    review_kind, case_id, record_id, target_state, review_note, expected_hash,
    canonical_path_override=None, audit_dir_override=None,
    *, principal=None, authz_repository=None, conn_factory=None,
    reviewer_ref=REVIEWER_REF,
):
    """Row 19B: `principal` is REQUIRED for real callers (kept as a
    keyword with no default sentinel error message deliberately, so
    the very first line below fails loudly and immediately if a
    caller forgets it - never silently mutates as an unauthenticated
    principal).

    ROW 19C-2b: this function no longer runs its own authz/hash-
    freshness/writer-invocation logic - it delegates the ENTIRE
    mutation (Row 19C-1's journal/coordinator infrastructure, dual
    authz, composite canonical+audit+backup pre-state snapshot, the
    pre-existing-record-audit admission gate, and the 12 review_kind
    transition tables) to `ui.services.review_mutation_facade.
    apply_review_mutation()` - mirrors `ui.services.approval_registry.
    case_scoped_approve()`'s own Row 19C-2a Step 7 delegation to
    `mutation_approval_facade.approve_case_scoped_mutation()` exactly.
    This function's own remaining job is exactly two things: (1)
    resolve `review_kind` into a `ReviewFamilyBinding` bundle (the
    module object, `record_type`, `call_shape`, `state_field`, the
    real domain exception class, the audit-directory getter, and the
    caller-selected, closed-vocabulary `reviewer_ref` - all already-
    resolved `REVIEW_KIND_REGISTRY` metadata this module already owns,
    per this module's own header comment on why the facade itself never
    imports this registry); (2) normalize `review_note` EXACTLY ONCE
    (`normalize_review_note()` below) and pass the SAME normalized text
    both to the facade (for hashing into `secondary_input_hash`) and,
    unchanged, all the way to the writer - no second, independent
    normalization ever happens. `target_state` is still validated
    against `get_allowed_targets()` HERE, before the facade is ever
    reached, for a fast, zero-lock rejection of a structurally invalid
    target - the facade's own `precondition_callback` does not
    re-derive the allowed-targets set.

    ROW 19C-3b SLICE 1: `reviewer_ref` is an additive, keyword-only
    parameter defaulting to `REVIEWER_REF` - every existing caller
    (`ui/main.py`, every pre-Slice-1 test) never passes it and gets the
    IDENTICAL default, so the web path's behavior is byte-for-byte
    unchanged. It is validated against the closed `ALLOWED_REVIEWER_REFS`
    vocabulary as the FIRST check this function performs (before even
    `_get_entry(review_kind)`) - see `InvalidReviewerRefError`'s own
    docstring for why this is a programmer-error class, not a domain
    rejection.

    `canonical_path_override`/`audit_dir_override`/`conn_factory` are
    TEST-ONLY dependency injection, threaded straight through to the
    facade unchanged - production callers (`ui/main.py`, `ui/cli_mutate.py`)
    NEVER pass any of the three; the facade's own production-default
    path always derives canonical/audit paths from the case-lock-resolved
    case_id and opens a real session-lock connection."""

    if principal is None:
        raise TypeError("apply_transition() requires principal= (Row 19B authorization)")

    if reviewer_ref not in ALLOWED_REVIEWER_REFS:
        raise InvalidReviewerRefError(
            f"reviewer_ref={reviewer_ref!r} is not one of the allowed values "
            f"{sorted(ALLOWED_REVIEWER_REFS)!r} - this is a caller bug, never a valid request"
        )

    entry = _get_entry(review_kind)

    trimmed_note = normalize_review_note(review_note)

    allowed_targets = get_allowed_targets(review_kind)

    if target_state not in allowed_targets:

        raise ReviewUiError(
            f"Geçersiz hedef durum: {target_state!r} "
            f"(izin verilen: {sorted(allowed_targets)})."
        )

    module = _import_module(entry["module"])
    cases_dir_anchor_module = _import_module(cases_dir_module_name(review_kind))

    binding = _review_mutation_facade.ReviewFamilyBinding(
        review_kind=review_kind,
        module=module,
        record_type=entry["record_type"] if entry["record_type"] is not None else "suggestion",
        call_shape=entry["call_shape"],
        state_field=get_field_names(review_kind)[2],
        domain_error_class=entry["domain_error_class"],
        get_audit_dir_fn=getattr(module, entry["audit_dir_getter"]),
        reviewer_ref=reviewer_ref,
        cases_dir_anchor_module=cases_dir_anchor_module,
    )

    result = _review_mutation_facade.apply_review_mutation(
        review_kind, case_id, record_id, target_state, trimmed_note, expected_hash,
        binding,
        principal=principal,
        authz_repository=authz_repository,
        conn_factory=conn_factory,
        canonical_path_override=canonical_path_override,
        audit_dir_override=audit_dir_override,
    )

    return {
        "canonical_path": result.canonical_path,
        "audit_path": result.audit_path,
        "post_sha256": result.canonical_hash,
        "previous_state": result.previous_state,
        "new_state": result.new_state,
        # ROW 19C-2b: additive, non-breaking fields - no existing
        # caller reads these two keys (main.py's own `review_confirm`
        # route only ever reads `result["audit_path"]`/
        # `result["previous_state"]`/`result["new_state"]`/
        # `result["post_sha256"]`), kept for observability/future use -
        # mirrors `approval_registry.case_scoped_approve()`'s own
        # identical additive fields.
        "journal_id": result.journal_id,
        "replayed": result.replayed,
    }


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
