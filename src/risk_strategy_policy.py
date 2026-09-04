# ============================================================
# VERGİ AI - RISK / STRATEGY POLICY V1
#
# Saf deterministik sabitler, taksonomiler, parmak izi (fingerprint)
# ve bağımsız serbest-metin güvenlik primitifleri. Bu modül HİÇBİR
# LLM/network çağrısı yapmaz; agent veya validator'ın import ettiği
# ORTAK, düşük seviyeli katmandır.
# ============================================================

import hashlib
import json
import re

from timeline_consolidation_policy import normalize_text_tr as _canonical_normalize_text_tr
from issue_spotting_validator import FORBIDDEN_PHRASES as _ROW9_FORBIDDEN_PHRASES


# ============================================================
# CASE RISK SCOPES (TAM 7, SABİT)
# ============================================================

CASE_RISK_SCOPES = (
    "documentary_record",
    "fact_verification",
    "timeline_verification",
    "deadline_calculability",
    "legal_authority_coverage",
    "case_law_coverage",
    "procedural_posture",
)


# ============================================================
# EXECUTION STATES
# ============================================================

RISK_EXECUTION_STATES = {
    "analysis_not_run",
    "blocked_missing_input",
    "blocked_upstream_not_run",
    "analysis_failed",
    "no_risk_identified",
    "analysis_partial",
    "analysis_completed",
}

STRATEGY_EXECUTION_STATES = {
    "analysis_not_run",
    "blocked_missing_input",
    "blocked_upstream_not_run",
    "analysis_failed",
    "no_strategy_identified",
    "analysis_partial",
    "analysis_completed",
}

# Bu execution_state'lerde risk-üretim sayaçları (gap+identified)
# KESİN OLARAK sıfır olmalıdır.
ZERO_RISK_EXECUTION_STATES = {
    "analysis_not_run",
    "blocked_missing_input",
    "blocked_upstream_not_run",
    "analysis_failed",
    "no_risk_identified",
}

# analysis_partial ve analysis_completed'te identified/gap count > 0
# OLABİLİR (analysis_partial'da kabul edilen sayı 0 da olabilir - bu
# yüzden analysis_partial ZERO setine YOK, ama count>=0 serbesttir).

ZERO_STRATEGY_EXECUTION_STATES = {
    "analysis_not_run",
    "blocked_missing_input",
    "blocked_upstream_not_run",
    "analysis_failed",
    "no_strategy_identified",
}


# ============================================================
# RISK / STRATEGY TAKSONOMİLERİ
# ============================================================

RISK_KINDS = {"identified", "gap"}

RISK_TYPES = {
    "unverified_fact_dependency",
    "unverified_timeline_dependency",
    "deadline_calculation_blocked",
    "missing_legal_authority",
    "unconfirmed_case_law_authority",
    "unconfirmed_evidence_dependency",
    "unreviewed_argument_dependency",
    "no_confirmed_evidence_for_issue",
    "no_resolved_legal_authority_for_issue",
    "no_grounded_case_law_for_issue",
    "deadline_not_computable",
    "anchor_event_unverified",
    "no_confirmed_argument_for_issue",
}

# risk_type -> risk_kind eşlemesi (SABİT, agent bunu SEÇEMEZ, yalnız
# ALLOWLIST içindeki bir identified adayını seçebilir; gap türleri
# yalnız deterministik engine tarafından üretilir).
GAP_RISK_TYPES = {
    "no_confirmed_evidence_for_issue",
    "no_resolved_legal_authority_for_issue",
    "no_grounded_case_law_for_issue",
    "deadline_not_computable",
    "anchor_event_unverified",
    "no_confirmed_argument_for_issue",
}

IDENTIFIED_RISK_TYPES = RISK_TYPES - GAP_RISK_TYPES

ABSENCE_BASIS_VALUES = {
    "no_confirmed_evidence_for_issue",
    "no_resolved_legal_authority_for_issue",
    "no_grounded_case_law_for_issue",
    "deadline_not_computable",
    "anchor_event_unverified",
    "no_confirmed_argument_for_issue",
}

# absence_basis -> risk_type (1:1, gap risk türleri absence_basis ile
# aynı isim ailesini taşır).
ABSENCE_BASIS_TO_RISK_TYPE = {v: v for v in ABSENCE_BASIS_VALUES}

STRATEGY_ACTION_TYPES = {
    "commission_fact_verification",
    "commission_timeline_verification",
    "escalate_deadline_verification",
    "commission_additional_legal_research",
    "commission_additional_case_law_research",
    "commission_evidentiary_review",
    "commission_argument_review",
    "request_human_risk_assessment",
}

SUGGESTION_TYPES = {
    "missing_risk_grounding",
    "unaddressed_risk",
    "conflicting_strategy_prerequisite",
    "additional_analysis_needed",
    "risk_taxonomy_gap",
}

ARGUMENT_REASON_CODES = {
    "explicit_textual_match",
    "temporal_consistency",
    "party_attribution_match",
    "monetary_amount_match",
    "procedural_reference_match",
    "legal_authority_match",
    "general_contextual_relevance",
}

# Gap-risk / strateji için deterministik (agent'sız) reason_code'lar.
DETERMINISTIC_REASON_CODES = {
    "no_confirmed_evidence_for_issue": "deterministic_gap_no_confirmed_evidence",
    "no_resolved_legal_authority_for_issue": "deterministic_gap_no_resolved_legal_authority",
    "no_grounded_case_law_for_issue": "deterministic_gap_no_grounded_case_law",
    "deadline_not_computable": "deterministic_gap_deadline_not_computable",
    "anchor_event_unverified": "deterministic_gap_anchor_event_unverified",
    "no_confirmed_argument_for_issue": "deterministic_gap_no_confirmed_argument",
}

STRATEGY_REASON_CODE = "deterministic_strategy_template"


# ============================================================
# REFERENCE FIELDS (9 - dokuz source referans dizisi)
# ============================================================

REF_FIELDS = (
    "source_fact_ids",
    "source_claim_ids",
    "source_counterargument_ids",
    "source_rebuttal_ids",
    "source_evidence_candidate_ids",
    "source_legal_research_ids",
    "source_case_law_ids",
    "source_timeline_event_ids",
    "source_deadline_ids",
)

EMPTY_REF_SET = {field: [] for field in REF_FIELDS}


def reference_set_signature(record):

    return {
        field: sorted(record.get(field, []) or [])
        for field in REF_FIELDS
    }


def collect_ref_ids(record):

    ids = set()

    for field in REF_FIELDS:

        ids |= set(record.get(field, []) or [])

    return ids


# ============================================================
# JSON / HASH HELPERS
# ============================================================

def canonical_dumps(value):

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_of(value):

    return hashlib.sha256(
        canonical_dumps(value).encode("utf-8")
    ).hexdigest()


# ============================================================
# İKİ AYRI PARMAK İZİ AİLESİ (kasıtlı olarak birbirinden farklı,
# aynı helper'a birleştirilmedi):
#
#   DEDUP fingerprint  -> yalnız TEK BİR ÇALIŞTIRMA içinde "bu iki
#     aday aynı mantıksal şeyi mi temsil ediyor" sorusuna cevap
#     verir. Serbest metni (description/grounded_explanation) KASITLI
#     OLARAK DIŞLAR - aksi halde agent aynı riski yalnız farklı
#     cümlelerle iki kez üretip dedup'ı aşabilirdi.
#
#   CONTENT fingerprint -> Layer B carry-forward'ın "insan TAM OLARAK
#     NEYİ onayladı" sorusuna cevap verir. Serbest metni ZORUNLU
#     OLARAK DAHİL EDER - aksi halde bir önceki 'confirmed' durumu,
#     hiç görülmemiş yeni bir metne sessizce taşınabilir (Row 13
#     compute_claim_fingerprint emsaliyle aynı ilke).
#
# review_state/requires_human_review/status/timestamp gibi içerik
# DIŞI alanlar HİÇBİR ikisine de dahil edilmez.
# ============================================================

def compute_risk_dedup_fingerprint(risk):

    return sha256_of(
        {
            "kind": "risk_dedup",
            "risk_kind": risk["risk_kind"],
            "risk_type": risk["risk_type"],
            "source_issue_id": risk.get("source_issue_id"),
            "absence_basis": risk.get("absence_basis"),
            "references": reference_set_signature(risk),
        }
    )


def compute_risk_content_fingerprint(risk):

    return sha256_of(
        {
            "kind": "risk_content",
            "risk_kind": risk["risk_kind"],
            "risk_type": risk["risk_type"],
            "source_issue_id": risk.get("source_issue_id"),
            "absence_basis": risk.get("absence_basis"),
            "reason_code": risk.get("reason_code"),
            "risk_description": risk.get("risk_description"),
            "grounded_explanation": risk.get("grounded_explanation"),
            "references": reference_set_signature(risk),
            "flags": risk.get("flags", {}),
        }
    )


def compute_strategy_dedup_fingerprint(strategy):

    return sha256_of(
        {
            "kind": "strategy_dedup",
            "strategy_action_type": strategy["strategy_action_type"],
            "addressed_risk_dedup_fingerprints": sorted(
                strategy.get("_addressed_risk_dedup_fingerprints", [])
            ),
            "references": reference_set_signature(strategy),
        }
    )


def compute_strategy_content_fingerprint(strategy):

    return sha256_of(
        {
            "kind": "strategy_content",
            "strategy_action_type": strategy["strategy_action_type"],
            "strategy_description": strategy.get("strategy_description"),
            "grounded_explanation": strategy.get("grounded_explanation"),
            "depends_on_gap_only": strategy.get("depends_on_gap_only"),
            "references": reference_set_signature(strategy),
            "flags": strategy.get("flags", {}),
            # Addressed risklerin İÇERİK fingerprint'leri - yalnız
            # risk ID'lerine dayanmaz; bir addressed risk'in kendi
            # metni/kaynakları değişirse strateji de "değişmiş" sayılır.
            "addressed_risk_content_fingerprints": sorted(
                strategy.get("_addressed_risk_content_fingerprints", [])
            ),
        }
    )


def compute_suggestion_dedup_fingerprint(suggestion):

    return sha256_of(
        {
            "kind": "suggestion_dedup",
            "suggestion_type": suggestion["suggestion_type"],
            "source_issue_id": suggestion.get("source_issue_id"),
            "related_reference_ids": sorted(
                suggestion.get("related_reference_ids", []) or []
            ),
        }
    )


def compute_suggestion_content_fingerprint(suggestion):

    return sha256_of(
        {
            "kind": "suggestion_content",
            "suggestion_type": suggestion["suggestion_type"],
            "source_issue_id": suggestion.get("source_issue_id"),
            "related_reference_ids": sorted(
                suggestion.get("related_reference_ids", []) or []
            ),
            "reason_code": suggestion.get("reason_code"),
            "grounded_explanation": suggestion.get("grounded_explanation"),
        }
    )


# ============================================================
# DETERMİNİSTİK FLAG HESAPLAYICILAR (TAM 10)
# ============================================================

MAX_GROUNDED_EXPLANATION_LENGTH = 1000
MAX_RISK_DESCRIPTION_LENGTH = 2000
MAX_STRATEGY_DESCRIPTION_LENGTH = 2000


def compute_derived_from_unverified_fact(ref_set, fact_index):

    for fact_id in ref_set.get("source_fact_ids", []):

        record = fact_index.get(fact_id)

        if record is None:

            continue

        if record["fact"].get("verification_state") != "verified":

            return True

    return False


def compute_derived_from_unverified_timeline_event(ref_set, timeline_event_index):

    for event_id in ref_set.get("source_timeline_event_ids", []):

        event = timeline_event_index.get(event_id)

        if event is None:

            continue

        if event.get("verification_state") != "verified":

            return True

    return False


def compute_deadline_calculation_blocked(ref_set, deadline_index):

    for deadline_id in ref_set.get("source_deadline_ids", []):

        deadline = deadline_index.get(deadline_id)

        if deadline is None:

            continue

        if deadline.get("calculation_state") != "calculated":

            return True

    return False


def compute_deadline_expiry_not_evaluated(ref_set, deadline_index):

    for deadline_id in ref_set.get("source_deadline_ids", []):

        deadline = deadline_index.get(deadline_id)

        if deadline is None:

            continue

        if deadline.get("expiry_state") == "not_evaluated":

            return True

    return False


def compute_depends_on_unconfirmed_evidence(ref_set, evidence_candidate_index):

    for candidate_id in ref_set.get("source_evidence_candidate_ids", []):

        candidate = evidence_candidate_index.get(candidate_id)

        if candidate is not None and candidate.get("review_state") == "needs_review":

            return True

    return False


def compute_depends_on_unconfirmed_authority(ref_set, case_law_decision_index):

    for decision_id in ref_set.get("source_case_law_ids", []):

        decision = case_law_decision_index.get(decision_id)

        if decision is None:

            continue

        # Şema yalnız "unknown"/"needs_review"/null'a izin verir - hiçbir
        # zaman "applicable"/"confirmed" değeri yoktur (Row 13 A2 dersi).
        if decision.get("applicability_result") in ("unknown", "needs_review", None):

            return True

    return False


def compute_depends_on_unreviewed_argument(ref_set, claim_index, counter_index, rebuttal_index):

    for claim_id in ref_set.get("source_claim_ids", []):

        claim = claim_index.get(claim_id)

        if claim is not None and claim.get("claim_review_state") == "needs_review":

            return True

    for counter_id in ref_set.get("source_counterargument_ids", []):

        counter = counter_index.get(counter_id)

        if counter is not None and counter.get("counter_review_state") == "needs_review":

            return True

    for rebuttal_id in ref_set.get("source_rebuttal_ids", []):

        rebuttal = rebuttal_index.get(rebuttal_id)

        if rebuttal is not None and rebuttal.get("rebuttal_review_state") == "needs_review":

            return True

    return False


def compute_depends_on_unresolved_authority_version(ref_set, research_index):

    for research_id in ref_set.get("source_legal_research_ids", []):

        research = research_index.get(research_id)

        if research is not None and research.get("finding_status") == "provision_resolved_version_unknown":

            return True

    return False


def compute_missing_legal_authority(ref_set):

    return not (
        ref_set.get("source_legal_research_ids")
        or ref_set.get("source_case_law_ids")
    )


def compute_upstream_analysis_not_run(upstream_not_run_flags):
    """
    upstream_not_run_flags: bir kaydın referans verdiği kaynaklardan
    herhangi birinin GERÇEK upstream execution/finding durumunun
    *_not_run/*_failed/dosya-yok olduğunu gösteren bool listesi.
    """

    return any(upstream_not_run_flags)


def compute_all_flags(
    ref_set,
    fact_index,
    timeline_event_index,
    deadline_index,
    evidence_candidate_index,
    case_law_decision_index,
    research_index,
    claim_index,
    counter_index,
    rebuttal_index,
    upstream_not_run_flags,
):

    return {
        "derived_from_unverified_fact": compute_derived_from_unverified_fact(
            ref_set, fact_index
        ),
        "derived_from_unverified_timeline_event": compute_derived_from_unverified_timeline_event(
            ref_set, timeline_event_index
        ),
        "deadline_calculation_blocked": compute_deadline_calculation_blocked(
            ref_set, deadline_index
        ),
        "deadline_expiry_not_evaluated": compute_deadline_expiry_not_evaluated(
            ref_set, deadline_index
        ),
        "depends_on_unconfirmed_evidence": compute_depends_on_unconfirmed_evidence(
            ref_set, evidence_candidate_index
        ),
        "depends_on_unconfirmed_authority": compute_depends_on_unconfirmed_authority(
            ref_set, case_law_decision_index
        ),
        "depends_on_unreviewed_argument": compute_depends_on_unreviewed_argument(
            ref_set, claim_index, counter_index, rebuttal_index
        ),
        "depends_on_unresolved_authority_version": compute_depends_on_unresolved_authority_version(
            ref_set, research_index
        ),
        "missing_legal_authority": compute_missing_legal_authority(ref_set),
        "upstream_analysis_not_run": compute_upstream_analysis_not_run(
            upstream_not_run_flags
        ),
    }


DETERMINISTIC_FLAG_NAMES = (
    "derived_from_unverified_fact",
    "derived_from_unverified_timeline_event",
    "deadline_calculation_blocked",
    "deadline_expiry_not_evaluated",
    "depends_on_unconfirmed_evidence",
    "depends_on_unconfirmed_authority",
    "depends_on_unreviewed_argument",
    "depends_on_unresolved_authority_version",
    "missing_legal_authority",
    "upstream_analysis_not_run",
)


# ============================================================
# DETERMİNİSTİK TEMPLATE RENDER (risk/strategy ANA METNİ)
# ============================================================

GAP_RISK_TEMPLATES = {
    "no_confirmed_evidence_for_issue": (
        "Bu issue için canonical evidence.json içinde onaylanmış "
        "(confirmed) hiçbir delil kaydı bulunmamaktadır."
    ),
    "no_resolved_legal_authority_for_issue": (
        "Bu issue için canonical research.json içinde çözümlenmiş "
        "(resolved) hiçbir hukuki dayanak bulunmamaktadır."
    ),
    "no_grounded_case_law_for_issue": (
        "Bu issue için canonical case_law.json içinde somut "
        "uyuşmazlığa dayandırılmış hiçbir içtihat kararı bulunmamaktadır."
    ),
    "deadline_not_computable": (
        "Bu issue ile ilişkili deadline hesabı, canonical deadline.json "
        "içindeki calculation_state nedeniyle tamamlanamamıştır."
    ),
    "anchor_event_unverified": (
        "Bu issue ile ilişkili deadline'ın anchor event'i canonical "
        "timeline.json içinde doğrulanmış (verified) durumda değildir."
    ),
    "no_confirmed_argument_for_issue": (
        "Bu issue için canonical arguments.json içinde onaylanmış "
        "(confirmed) hiçbir claim/counterargument/rebuttal bulunmamaktadır."
    ),
}


def render_gap_risk_description(risk_type):

    template = GAP_RISK_TEMPLATES.get(risk_type)

    if template is None:

        raise ValueError(f"Bilinmeyen gap risk_type: {risk_type}")

    return template


IDENTIFIED_RISK_TEMPLATE = (
    "Bu issue için agent tarafından seçilen kaynaklara dayanan bir "
    "risk sinyali tespit edilmiştir (risk_type={risk_type})."
)


def render_identified_risk_description(risk_type):

    return IDENTIFIED_RISK_TEMPLATE.format(risk_type=risk_type)


STRATEGY_ACTION_TYPE_BY_RISK_TYPE = {
    "unverified_fact_dependency": "commission_fact_verification",
    "unverified_timeline_dependency": "commission_timeline_verification",
    "deadline_calculation_blocked": "escalate_deadline_verification",
    "deadline_not_computable": "escalate_deadline_verification",
    "anchor_event_unverified": "escalate_deadline_verification",
    "missing_legal_authority": "commission_additional_legal_research",
    "no_resolved_legal_authority_for_issue": "commission_additional_legal_research",
    "unconfirmed_case_law_authority": "commission_additional_case_law_research",
    "no_grounded_case_law_for_issue": "commission_additional_case_law_research",
    "unconfirmed_evidence_dependency": "commission_evidentiary_review",
    "no_confirmed_evidence_for_issue": "commission_evidentiary_review",
    "unreviewed_argument_dependency": "commission_argument_review",
    "no_confirmed_argument_for_issue": "commission_argument_review",
}

DEFAULT_STRATEGY_ACTION_TYPE = "request_human_risk_assessment"


def select_strategy_action_type(risk_types):

    for risk_type in risk_types:

        action = STRATEGY_ACTION_TYPE_BY_RISK_TYPE.get(risk_type)

        if action is not None:

            return action

    return DEFAULT_STRATEGY_ACTION_TYPE


STRATEGY_TEMPLATE = (
    "Adreslenen risk(ler) için önerilen sonraki adım: {action_label}. "
    "Bu bir hukuki tavsiye veya kesin karar değildir; insan kararı "
    "gerektiren bir aday sonraki-adımdır."
)

STRATEGY_ACTION_LABELS = {
    "commission_fact_verification": "olgu doğrulamasının görevlendirilmesi",
    "commission_timeline_verification": "zaman çizelgesi doğrulamasının görevlendirilmesi",
    "escalate_deadline_verification": "süre/anchor doğrulamasının önceliklendirilmesi",
    "commission_additional_legal_research": "ek hukuki araştırma görevlendirilmesi",
    "commission_additional_case_law_research": "ek içtihat araştırması görevlendirilmesi",
    "commission_evidentiary_review": "delil incelemesinin görevlendirilmesi",
    "commission_argument_review": "argüman incelemesinin görevlendirilmesi",
    "request_human_risk_assessment": "insan tarafından genel risk değerlendirmesi talep edilmesi",
}


def render_strategy_description(strategy_action_type):

    label = STRATEGY_ACTION_LABELS.get(strategy_action_type, strategy_action_type)

    return STRATEGY_TEMPLATE.format(action_label=label)


# ============================================================
# TEXT SAFETY PRIMİTİFLERİ (agent VE validator BAĞIMSIZ kullanır)
# ============================================================

FORBIDDEN_PHRASE_FRAGMENTS = (
    "kazanma ihtimali",
    "kazanma olasiligi",
    "kazanma sansi",
    "yuzde ihtimalle",
    "dava kazanilir",
    "dava kaybedilir",
    "kesin olarak kazanilacaktir",
    "kesin sonuc",
    "hukuki garanti",
    "garanti edilir",
    "kesinlikle kazanilir",
    "sonuc tahmini",
    "basari orani",
    "risk skoru",
)

# "Değerlendirilemedi/doğrulanamadı" tarzı kontrollü belirsizlik
# ifadeleri BİLEREK bu listeye dahil EDİLMEMİŞTİR (yanlış pozitif
# olmaması için) - Row 14-only netleştirme.

# ============================================================
# BİRLEŞİK (UNION) FORBIDDEN-PHRASE POLİTİKASI
#
# Row 9'un (issue_spotting_validator.FORBIDDEN_PHRASES) orijinal
# prosedürel/deadline-kesinliği ifadeleri İLE Row 14'ün kazanma-
# ihtimali/kesinlik/garanti ifadelerinin (FORBIDDEN_PHRASE_FRAGMENTS)
# BİRLEŞİMİ - tek, değişmez, otoriter sözlük. Row 9'un kendi sabiti/
# dosyası MUTATE EDİLMEZ, yalnız import edilip birleştirilir.
#
# Agent (risk_strategy_agent.py), engine semantic guard
# (risk_strategy_engine.py) ve independent validator
# (risk_strategy_validator.py) AYNI bu sabiti ve AYNI
# check_forbidden_phrases() fonksiyonunu kullanır - üç ayrı kopya
# YOKTUR, tek kaynak vardır (agent'ın YÜKSEK seviyeli
# check_text_safety() sarmalayıcısı DEĞİL, bu ORTAK, saf, düşük
# seviyeli politika fonksiyonu; validator bu şekilde agent'ın kendi
# kararına değil, yalnız paylaşılan DETERMİNİSTİK VERİYE bağımlı
# kalır - bağımsızlık korunur).
# ============================================================

ALL_FORBIDDEN_PHRASES = tuple(
    sorted(set(_ROW9_FORBIDDEN_PHRASES) | set(FORBIDDEN_PHRASE_FRAGMENTS))
)

ID_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{6,}")

QUOTE_PATTERN = re.compile(r"[\"“”]([^\"“”]{3,})[\"“”]")

DATE_TOKEN_PATTERN = re.compile(
    r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"
)

AMOUNT_TOKEN_PATTERN = re.compile(
    r"\b\d[\d.,]{2,}\s?(?:TL|TRY|USD|EUR)\b"
)

# Row 14-local hardening (C2 bulgusu, Row 13'e geriye dönük
# uygulanmadı - yalnız burada, Row 14'te geçerli).
DURATION_TOKEN_PATTERN = re.compile(
    r"\b\d{1,4}\s?(?:gün|gun|hafta|ay|yıl|yil)\b",
    re.IGNORECASE,
)

BARE_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


# Row 9/13 ile BİREBİR AYNI kanonik Türkçe normalizasyon (NFKD +
# combining-mark temizliği + casefold + dotless-ı vb. çeviri +
# whitespace collapse) - yerel/farklı bir normalizasyon YENİDEN
# UYGULANMAZ, tek kaynaktan reuse edilir.
normalize_text_tr = _canonical_normalize_text_tr


def check_forbidden_phrases(record_id, *texts):

    errors = []

    combined = normalize_text_tr(" ".join(text or "" for text in texts))

    for phrase in ALL_FORBIDDEN_PHRASES:

        if normalize_text_tr(phrase) in combined:

            errors.append(
                f"{record_id}: metin kesin hukuki sonuç/outcome ifadesi "
                f"içeriyor ('{phrase}')."
            )

    return errors


def extract_quoted_spans(text):

    return [match.group(1) for match in QUOTE_PATTERN.finditer(text)]


def find_unverified_quotes(text, citable_texts):

    unverified = []

    for span in extract_quoted_spans(text):

        if not any(span in source for source in citable_texts):

            unverified.append(span)

    return unverified


def find_smuggled_ids(text, declared_ids, all_known_ids):

    declared = set(declared_ids)

    smuggled = []

    for token in ID_TOKEN_PATTERN.findall(text):

        if token in all_known_ids and token not in declared:

            smuggled.append(token)

    return smuggled


def find_unsupported_numeric_tokens(text, citable_texts):

    unsupported = []

    for pattern in (
        DATE_TOKEN_PATTERN,
        AMOUNT_TOKEN_PATTERN,
        DURATION_TOKEN_PATTERN,
        BARE_YEAR_PATTERN,
    ):

        for match in pattern.finditer(text):

            token = match.group(0)

            if not any(token in source for source in citable_texts):

                unsupported.append(token)

    return unsupported


def collect_citable_texts(
    reference_set,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
):

    texts = []

    for fact_id in reference_set.get("source_fact_ids", []):

        record = fact_index.get(fact_id)

        if record is None:
            continue

        fact = record["fact"]

        for value in (
            fact.get("statement"),
            fact.get("normalized_statement"),
            (fact.get("source") or {}).get("text_excerpt"),
        ):

            if isinstance(value, str) and value:
                texts.append(value)

    for candidate_id in reference_set.get("source_evidence_candidate_ids", []):

        candidate = evidence_candidate_index.get(candidate_id)

        if candidate is None:
            continue

        for value in (
            candidate.get("source_excerpt"),
            candidate.get("grounded_explanation"),
        ):

            if isinstance(value, str) and value:
                texts.append(value)

    for research_id in reference_set.get("source_legal_research_ids", []):

        research = research_index.get(research_id)

        if research is None:
            continue

        for value in (research.get("title"), research.get("description")):

            if isinstance(value, str) and value:
                texts.append(value)

    for decision_id in reference_set.get("source_case_law_ids", []):

        decision = case_law_decision_index.get(decision_id)

        if decision is None:
            continue

        for value in (decision.get("title"), decision.get("description")):

            if isinstance(value, str) and value:
                texts.append(value)

    return texts


if __name__ == "__main__":

    # Import-time yan etki yok; modül yalnız içe aktarıldığında
    # kullanılır (Prensip: __main__ koruması, Backlog maddesiyle
    # tutarlı - bkz. CLAUDE.md §6).
    print("risk_strategy_policy.py - saf modül, self-test yok.")
