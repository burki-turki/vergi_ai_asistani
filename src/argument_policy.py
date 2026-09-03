# ============================================================
# VERGİ AI - ARGUMENT POLICY V1
#
# AMAÇ
# ----
#
# Row 13 (Argument Agent) için sabitler, kontrollü sözlükler
# (claim_type/counter_type/rebuttal_type/suggestion_type),
# upstream eligibility kuralları, deterministik gap-flag
# hesaplayıcıları, stable entity fingerprint ve metin-güvenlik
# (quote/citation-smuggling) yardımcıları.
#
# Bu modül LLM ÇAĞIRMAZ, network YAPMAZ. Yalnız canonical veri
# üzerinde saf fonksiyonlar içerir.
# ============================================================


import hashlib
import json
import re


# ============================================================
# VERSION
# ============================================================

ARGUMENT_POLICY_VERSION = "1"

AGENT_TRIGGER_RULE_ID = "argument_rule_agent_llm_v1"

DETERMINISTIC_TRIGGER_RULE_ID = "argument_rule_deterministic_allowlist_v1"


# ============================================================
# CONTROLLED VOCABULARIES
# ============================================================

CLAIM_TYPES = {
    "procedural_challenge",
    "substantive_legal_challenge",
    "factual_challenge",
    "evidentiary_insufficiency",
    "calculation_challenge",
    "limitation_or_deadline_challenge",
    "authority_or_jurisdiction_challenge",
    "penalty_specific_challenge",
}

COUNTER_TYPES = {
    "factual_denial",
    "legal_opposition",
    "procedural_compliance",
    "evidence_sufficiency",
    "calculation_defense",
    "timeliness_defense",
    "authority_or_jurisdiction_defense",
    "alternative_explanation",
    "authority_distinction",
}

REBUTTAL_TYPES = {
    "factual_refutation",
    "legal_refutation",
    "procedural_refutation",
    "evidentiary_refutation",
    "calculation_refutation",
    "timeliness_response",
    "authority_or_jurisdiction_response",
    "alternative_explanation_response",
    "authority_distinction_response",
}

# Argument türlerinin "temporal" (süre/zamanlama) argument olup
# olmadığını belirler - yalnız bu türler timeline/deadline
# grounding'i type-based guard'a tabidir (bkz. §8 contract).
TEMPORAL_CLAIM_TYPES = {"limitation_or_deadline_challenge"}
TEMPORAL_COUNTER_TYPES = {"timeliness_defense"}
TEMPORAL_REBUTTAL_TYPES = {"timeliness_response"}

# Argument türlerinin "legal/authority" argument olup olmadığını
# belirler - yalnız bu türlerde missing_legal_authority anlamlıdır.
LEGAL_CLAIM_TYPES = {
    "substantive_legal_challenge",
    "authority_or_jurisdiction_challenge",
    "penalty_specific_challenge",
}

LEGAL_COUNTER_TYPES = {
    "legal_opposition",
    "authority_or_jurisdiction_defense",
    "authority_distinction",
}

LEGAL_REBUTTAL_TYPES = {
    "legal_refutation",
    "authority_or_jurisdiction_response",
    "authority_distinction_response",
}

SUGGESTION_TYPES = {
    "missing_supporting_fact",
    "unresolved_counterargument",
    "conflicting_authority",
    "additional_research_needed",
    "argument_taxonomy_gap",
}

# ------------------------------------------------------------
# suggestion_type için conditional grounding (validator ile
# ortak referans - Row 12 evidence_policy deseniyle aynı
# yaklaşım).
# ------------------------------------------------------------

SUGGESTION_GROUNDING_SPEC = {
    "missing_supporting_fact": {
        "requires_claim": False,
        "requires_counterargument": False,
        "min_related_references": 0,
    },

    "unresolved_counterargument": {
        "requires_claim": True,
        "requires_counterargument": False,
        "min_related_references": 0,
    },

    "conflicting_authority": {
        "requires_claim": False,
        "requires_counterargument": False,
        "min_related_references": 2,
    },

    "additional_research_needed": {
        "requires_claim": False,
        "requires_counterargument": False,
        "min_related_references": 0,
    },

    "argument_taxonomy_gap": {
        "requires_claim": False,
        "requires_counterargument": False,
        "min_related_references": 0,
    },
}


# ============================================================
# REASON CODES (agent-selectable, controlled - free-text DEĞİL)
# ============================================================

ARGUMENT_REASON_CODES = {
    "explicit_textual_match",
    "temporal_consistency",
    "party_attribution_match",
    "monetary_amount_match",
    "procedural_reference_match",
    "legal_authority_match",
    "general_contextual_relevance",
}


# ============================================================
# EXECUTION STATES
# ============================================================

COVERAGE_EXECUTION_STATES = {
    "analysis_not_run",
    "analysis_completed",
    "analysis_partial",
    "blocked_missing_input",
    "analysis_failed",
}

# claim/counterargument/rebuttal sayıları bu durumlarda SIFIR
# olmalıdır (agent bu issue için hiç çalışmadı, çalışamadı ya
# da allowlist zaten boştu).
ZERO_CLAIM_EXECUTION_STATES = {
    "analysis_not_run",
    "blocked_missing_input",
    "analysis_failed",
}

# suggestion_count yalnız agent HİÇ ÇALIŞMADIYSA veya
# BAŞARISIZ olduysa sıfır olmalıdır. "blocked_missing_input"
# KASITLI OLARAK HARİÇ TUTULUR: agent, tam olarak eksik olan
# şeyi (ör. "missing_supporting_fact") işaret eden bir
# suggestion üretebilir - bu bir claim/counterargument/
# rebuttal DEĞİLDİR.
ZERO_SUGGESTION_EXECUTION_STATES = {
    "analysis_not_run",
    "analysis_failed",
}


# ============================================================
# TEXT LIMITS
# ============================================================

MAX_ARGUMENT_TEXT_LENGTH = 2000

MAX_GROUNDED_EXPLANATION_LENGTH = 1000


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
# STABLE ENTITY FINGERPRINT (SAFE REVIEW CARRY-FORWARD İÇİN)
#
# Bir claim/counterargument/rebuttal'ın "aynı" sayılması için:
# aynı parent(lar), aynı type, aynı text, aynı referans seti.
# LLM free-text'i TEK BAŞINA identity DEĞİLDİR - yalnız bu
# tam demetin bir parçasıdır.
# ============================================================

REF_FIELDS = (
    "source_fact_ids",
    "source_evidence_candidate_ids",
    "source_legal_research_ids",
    "source_case_law_ids",
    "source_timeline_event_ids",
    "source_deadline_ids",
)


def reference_set_signature(record):

    return {
        field: sorted(record.get(field, []) or [])
        for field in REF_FIELDS
    }


def compute_claim_fingerprint(claim):

    return sha256_of(
        {
            "kind": "claim",
            "source_issue_id": claim["source_issue_id"],
            "claim_type": claim["claim_type"],
            "claim_text": claim["claim_text"],
            "references": reference_set_signature(claim),
        }
    )


def compute_counterargument_fingerprint(counterargument):

    return sha256_of(
        {
            "kind": "counterargument",
            "source_claim_id": counterargument["source_claim_id"],
            "counter_type": counterargument["counter_type"],
            "counterargument_text": counterargument["counterargument_text"],
            "references": reference_set_signature(counterargument),
        }
    )


def compute_rebuttal_fingerprint(rebuttal):

    return sha256_of(
        {
            "kind": "rebuttal",
            "source_claim_id": rebuttal["source_claim_id"],
            "source_counterargument_id": rebuttal["source_counterargument_id"],
            "rebuttal_type": rebuttal["rebuttal_type"],
            "rebuttal_text": rebuttal["rebuttal_text"],
            "references": reference_set_signature(rebuttal),
        }
    )


# ============================================================
# CITABLE TEXT COLLECTION (QUOTE VERIFICATION İÇİN)
#
# Bir referans ID kümesinin "alıntılanabilir" canonical
# metinlerini toplar - fact statement/normalized_statement/
# source.text_excerpt, evidence source_excerpt, research
# title/description, case-law decision title/description.
# ============================================================

def classify_related_reference_ids(
    related_reference_ids,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
):
    """
    Suggestion'ların `related_reference_ids` alanı (karışık
    tür: fact/evidence/research/case_law ID'leri) içinden yalnız
    facts/evidence/research/case_law'a ait olanları,
    collect_citable_texts()'in beklediği reference_set şekline
    dönüştürür (claim/counterargument/rebuttal ID'leri burada
    sınıflandırılmaz - onların citable metni ayrıca eklenir).
    """

    ref_set = {field: [] for field in REF_FIELDS}

    for reference_id in related_reference_ids:

        if reference_id in fact_index:

            ref_set["source_fact_ids"].append(reference_id)

        elif reference_id in evidence_candidate_index:

            ref_set["source_evidence_candidate_ids"].append(reference_id)

        elif reference_id in research_index:

            ref_set["source_legal_research_ids"].append(reference_id)

        elif reference_id in case_law_decision_index:

            ref_set["source_case_law_ids"].append(reference_id)

    return ref_set


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

    for candidate_id in reference_set.get(
        "source_evidence_candidate_ids", []
    ):

        candidate = evidence_candidate_index.get(candidate_id)

        if candidate is None:
            continue

        for value in (
            candidate.get("source_excerpt"),
            candidate.get("grounded_explanation"),
        ):

            if isinstance(value, str) and value:
                texts.append(value)

    for research_id in reference_set.get(
        "source_legal_research_ids", []
    ):

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


QUOTE_PATTERN = re.compile(
    r"[\"“”]([^\"“”]{3,})[\"“”]"
)


def extract_quoted_spans(text):

    return [
        match.group(1)
        for match in QUOTE_PATTERN.finditer(text)
    ]


def find_unverified_quotes(text, citable_texts):

    unverified = []

    for span in extract_quoted_spans(text):

        if not any(span in source for source in citable_texts):

            unverified.append(span)

    return unverified


# ============================================================
# CITATION-ID SMUGGLING GUARD
#
# Text içinde, deklare edilen referans setinde OLMAYAN bilinen
# bir canonical ID (fact_id/document_id/candidate_id/research_id/
# decision_id) geçiyorsa bu bir metadata-smuggling denemesidir.
# ============================================================

ID_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{6,}")


def find_smuggled_ids(text, declared_ids, all_known_ids):

    declared = set(declared_ids)

    smuggled = []

    for token in ID_TOKEN_PATTERN.findall(text):

        if token in all_known_ids and token not in declared:

            smuggled.append(token)

    return smuggled


# ============================================================
# UNSUPPORTED DATE/AMOUNT GUARD
#
# Text içindeki tarih/tutar benzeri token'lar, referans edilen
# kaynakların metinlerinde BİREBİR geçmiyorsa "unsupported"
# sayılır (hallucinated tarih/tutar).
# ============================================================

DATE_TOKEN_PATTERN = re.compile(
    r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"
)

AMOUNT_TOKEN_PATTERN = re.compile(
    r"\b\d[\d.,]{2,}\s?(?:TL|TRY|USD|EUR)\b"
)


def find_unsupported_numeric_tokens(text, citable_texts):

    unsupported = []

    for pattern in (DATE_TOKEN_PATTERN, AMOUNT_TOKEN_PATTERN):

        for match in pattern.finditer(text):

            token = match.group(0)

            if not any(token in source for source in citable_texts):

                unsupported.append(token)

    return unsupported


# ============================================================
# DETERMINISTIC GAP FLAGS
# ============================================================

def compute_depends_on_unconfirmed_evidence(
    reference_set,
    evidence_candidate_index,
):

    for candidate_id in reference_set.get(
        "source_evidence_candidate_ids", []
    ):

        candidate = evidence_candidate_index.get(candidate_id)

        if (
            candidate is not None
            and candidate.get("review_state") == "needs_review"
        ):

            return True

    return False


def compute_depends_on_unconfirmed_authority(
    reference_set,
    case_law_decision_index,
):

    for decision_id in reference_set.get("source_case_law_ids", []):

        decision = case_law_decision_index.get(decision_id)

        if decision is None:

            continue

        # Şema (case_case_law.schema.json) applicability_result için
        # yalnız "unknown", "needs_review" veya null'a izin verir - hiçbir
        # zaman "applicable"/"confirmed" değeri yoktur. null, en az
        # "unknown" kadar doğrulanmamıştır (hiç değerlendirilmemiş
        # olabilir); onaylanmış uygulanabilirlik olarak yorumlanamaz.
        if decision.get("applicability_result") in (
            "unknown",
            "needs_review",
            None,
        ):

            return True

    return False


def compute_missing_legal_authority(
    reference_set,
    argument_type,
    legal_type_set,
):

    if argument_type not in legal_type_set:

        return False

    return not (
        reference_set.get("source_legal_research_ids")
        or reference_set.get("source_case_law_ids")
    )
