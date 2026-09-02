# ============================================================
# VERGİ AI - EVIDENCE POLICY V1
#
# AMAÇ
# ----
#
# Canonical issue candidate'lar (issues.json) + approved
# canonical fact'ler (*/extractions/facts.json) + canonical
# case document kayıtları (*/document.json) üzerinden, her
# issue için deterministik bir ATOMİK ALLOWLIST üretmek:
#
#   (issue_id, fact_id, document_id, source_location, ...)
#
# Bu modül hiçbir supports/contradicts İLİŞKİSİ ÖNERMEZ - bu
# yalnız Agent'ın (evidence_agent.py) allowlist içinden yaptığı
# bir SEÇİMDİR. Policy/Discovery yalnız "hangi (issue, fact,
# document) üçlüleri değerlendirmeye uygundur" sorusunu
# deterministik olarak yanıtlar.
#
#
# TEMEL PRENSİP
# -------------
#
# - Yalnız approved (canonical facts.json) fact'ler kullanılır.
# - Yalnız active=true canonical case document kayıtları
#   kullanılır.
# - source_location, ilgili fact'in KENDİ canonical source
#   locator'ının birebir kopyasıdır - icat edilmez.
# - Bu modül bir delil UYDURMAZ; yalnız zaten var olan
#   approved fact + active document ikilisini işaretler.
# ============================================================


import hashlib
import json

from pathlib import Path


from case_document_validator import (
    load_case_documents,
)


# ============================================================
# VERSION
# ============================================================

EVIDENCE_POLICY_VERSION = "1"

AGENT_TRIGGER_RULE_ID = (
    "evidence_rule_agent_llm_v1"
)

DETERMINISTIC_TRIGGER_RULE_ID = (
    "evidence_rule_deterministic_allowlist_v1"
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DATA_DIR = (
    BASE_DIR
    / "data"
)

CASES_DIR = (
    DATA_DIR
    / "cases"
)


# ============================================================
# COVERAGE EXECUTION STATES
#
# Beş ayrı, birbirine dönüştürülemez durum. Row 10/11'in
# retrieval tabanlı execution_state'inden FARKLI olarak, burada
# hiçbir ağ/retrieval bağımlılığı yoktur - tek değişken Agent'ın
# çalıştırılıp çalıştırılmadığı ve (çalıştıysa) cevabının
# şekil/grounding açısından tam mı kısmi mi kabul edildiğidir.
# ============================================================

COVERAGE_EXECUTION_STATES = {
    "analysis_not_run",
    "analysis_completed",
    "analysis_partial",
    "blocked_missing_input",
    "analysis_failed",
}

# Bu durumlarda candidate_count SIFIR OLMALIDIR (agent hiç
# çalışmadı, hiç çalışamadı veya allowlist zaten boştu).
ZERO_CANDIDATE_EXECUTION_STATES = {
    "analysis_not_run",
    "blocked_missing_input",
    "analysis_failed",
}

# Bu durumlarda suggestion_count de SIFIR OLMALIDIR.
# "blocked_missing_input" KASITLI OLARAK HARİÇ TUTULUR: Agent,
# tam olarak eksik olan şeyi (ör. "missing_document") işaret
# eden bir suggestion üretebilir - bu candidate DEĞİLDİR.
ZERO_SUGGESTION_EXECUTION_STATES = {
    "analysis_not_run",
    "analysis_failed",
}

CONFIDENCE_BY_EXECUTION_STATE = {
    "analysis_completed":
        0.3,

    "analysis_partial":
        0.2,

    "blocked_missing_input":
        0.1,

    "analysis_failed":
        0.1,

    "analysis_not_run":
        0.1,
}

AGENT_SUGGESTION_DEFAULT_CONFIDENCE = 0.3


# ============================================================
# SUGGESTION TYPE CONDITIONAL GROUNDING SPEC
#
# Her suggestion_type için hangi alanların zorunlu olduğunu
# (validator VE agent tarafından ortak referans için) tanımlar.
# Bu bir JSON-schema conditional DEĞİLDİR (repository geleneği:
# şema düz kalır, conditional business rule validator'da
# uygulanır - bkz. Row 9-11 decision/candidate grounding
# kontrolleri).
# ============================================================

SUGGESTION_GROUNDING_SPEC = {
    "missing_document": {
        "requires_fact":
            False,

        "requires_document":
            False,

        "forbids_document":
            True,

        "min_related_references":
            0,
    },

    "fact_evidence_gap": {
        "requires_fact":
            True,

        "requires_document":
            False,

        "forbids_document":
            False,

        "min_related_references":
            0,
    },

    "fact_review_needed": {
        "requires_fact":
            True,

        "requires_document":
            False,

        "forbids_document":
            False,

        "min_related_references":
            0,
    },

    "missing_source_location": {
        "requires_fact":
            True,

        "requires_document":
            True,

        "forbids_document":
            False,

        "min_related_references":
            0,
    },

    "unresolved_conflict": {
        "requires_fact":
            False,

        "requires_document":
            False,

        "forbids_document":
            False,

        "min_related_references":
            2,
    },

    "additional_verification": {
        "requires_fact":
            False,

        "requires_document":
            False,

        "forbids_document":
            False,

        "min_related_references":
            1,
    },
}


# ============================================================
# DISCLAIMER
# ============================================================

DISCLAIMER_NOTE = (
    "Bu kayıt, belgeyle grounded bir fact'in canonical issue "
    "ile ilişkisine dair bir ADAYDIR. Fact Extraction/Approval "
    "katmanını tekrar değerlendirmez, taraf lehine kesin "
    "hukuki sonuç üretmez; admissibility, strength, "
    "sufficiency veya davanın kazanılma ihtimali DEĞİLDİR."
)


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(
    path,
):

    path = Path(
        path
    )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(
            file
        )


def canonical_dumps(
    value,
):

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_of(
    value,
):

    return (
        hashlib.sha256(
            canonical_dumps(
                value
            ).encode(
                "utf-8"
            )
        )
        .hexdigest()
    )


# ============================================================
# ACTIVE CANONICAL CASE DOCUMENTS (Row 3 Case Document Layer'ı
# TEKRAR İMPLEMENT ETMEZ - `case_document_validator.
# load_case_documents` ÇAĞRILIR)
# ============================================================

def load_active_case_documents_index(
    case_id,
):

    case_dir = (
        CASES_DIR
        / case_id
    )

    documents = load_case_documents(
        case_dir
    )

    index = {}

    for item in documents:

        data = item[
            "data"
        ]

        document_id = data.get(
            "document_id"
        )

        if not document_id:

            continue

        if data.get(
            "active"
        ) is not True:

            continue

        index[
            document_id
        ] = data

    return index


def load_all_case_documents_index(
    case_id,
):

    case_dir = (
        CASES_DIR
        / case_id
    )

    documents = load_case_documents(
        case_dir
    )

    index = {}

    for item in documents:

        data = item[
            "data"
        ]

        document_id = data.get(
            "document_id"
        )

        if document_id:

            index[
                document_id
            ] = data

    return index


# ============================================================
# CANDIDATE REASON CODES - DETERMİNİSTİK RENDER
#
# Agent yalnız bir reason_code SEÇER; kısa grounded_explanation
# metni bu template'lerle deterministik olarak üretilir - LLM
# serbest metin YAZMAZ (Row 9-11 free-text safety deseni).
# ============================================================

def render_explicit_textual_match(
    fact_statement,
    relationship,
):

    verb = (
        "destekler"
        if relationship == "supports"
        else "zayıflatır/karşı olgusal içerik sağlar"
    )

    return (
        "Fact'in metni ile issue bağlamı arasında açık bir "
        f"metinsel örtüşme bulunmaktadır; bu fact issue'yu "
        f"{verb}."
    )


def render_temporal_consistency(
    fact_statement,
    relationship,
):

    verb = (
        "tutarlıdır"
        if relationship == "supports"
        else "çelişmektedir"
    )

    return (
        "Fact'teki tarih/zamanlama unsuru, issue'nun "
        f"bağlamıyla {verb}."
    )


def render_party_attribution_match(
    fact_statement,
    relationship,
):

    verb = (
        "destekler"
        if relationship == "supports"
        else "zayıflatır"
    )

    return (
        "Fact'in atfedildiği taraf/aktör, issue'nun taraf "
        f"bağlamıyla örtüşmektedir; bu durum issue'yu {verb}."
    )


def render_monetary_amount_match(
    fact_statement,
    relationship,
):

    verb = (
        "destekler"
        if relationship == "supports"
        else "zayıflatır"
    )

    return (
        "Fact'teki parasal/tutar unsuru issue bağlamındaki "
        f"iddiayı {verb}."
    )


def render_procedural_reference_match(
    fact_statement,
    relationship,
):

    verb = (
        "destekler"
        if relationship == "supports"
        else "zayıflatır"
    )

    return (
        "Fact'teki usuli/prosedürel unsur (tebliğ, süre, "
        f"başvuru vb.) issue bağlamını {verb}."
    )


def render_general_contextual_relevance(
    fact_statement,
    relationship,
):

    verb = (
        "destekleyici"
        if relationship == "supports"
        else "zayıflatıcı/karşı"
    )

    return (
        "Fact, issue ile genel bağlamsal ilgisi nedeniyle "
        f"{verb} bir unsur olarak değerlendirilmiştir."
    )


CANDIDATE_REASON_CODE_RENDERERS = {
    "explicit_textual_match":
        render_explicit_textual_match,

    "temporal_consistency":
        render_temporal_consistency,

    "party_attribution_match":
        render_party_attribution_match,

    "monetary_amount_match":
        render_monetary_amount_match,

    "procedural_reference_match":
        render_procedural_reference_match,

    "general_contextual_relevance":
        render_general_contextual_relevance,
}


# ============================================================
# SUGGESTION TITLE/DESCRIPTION - DETERMİNİSTİK RENDER
# ============================================================

SUGGESTION_TITLES = {
    "missing_document": (
        "Issue için ek bir belgenin sisteme kazandırılması "
        "gerekebilir"
    ),

    "fact_evidence_gap": (
        "Fact için delil kanıtlama boşluğu tespit edildi"
    ),

    "unresolved_conflict": (
        "Fact/candidate'lar arasında çözülmemiş bir çelişki "
        "bulunmaktadır"
    ),

    "missing_source_location": (
        "Fact-belge ilişkisi için kaynak konumu eksik"
    ),

    "fact_review_needed": (
        "Fact'in ayrıca insan incelemesine ihtiyacı "
        "olabilir"
    ),

    "additional_verification": (
        "Ek doğrulama yapılması önerilir"
    ),
}


def render_suggestion_description(
    suggestion_type,
    source_issue_id,
    source_fact_id,
    related_reference_ids,
):

    base = (
        f"Agent tarafından issue '{source_issue_id}' için "
        f"'{suggestion_type}' türünde bir öneri "
        "işaretlenmiştir."
    )

    if source_fact_id:

        base += (
            f" İlgili fact: {source_fact_id}."
        )

    if related_reference_ids:

        base += (
            " İlgili referanslar: "
            + ", ".join(
                related_reference_ids
            )
            + "."
        )

    return (
        base
        + " Bu bir gerçek delil DEĞİLDİR; upstream mutation "
        "yapmaz, yalnız insan incelemesi için işaretlenmiştir."
    )


# ============================================================
# FINALIZE - COVERAGE / CANDIDATES / SUGGESTIONS
# ============================================================

def coverage_id_for_issue(
    issue,
):

    return f"coverage_{issue['issue_id']}"


def finalize_coverage(
    coverage_records,
):

    finalized = []

    for record in coverage_records:

        coverage = dict(
            record
        )

        coverage[
            "status"
        ] = "candidate"

        coverage[
            "requires_human_review"
        ] = True

        finalized.append(
            coverage
        )

    return finalized


def finalize_candidates(
    candidate_records,
    start_index=1,
):

    finalized = []

    for index, record in enumerate(
        candidate_records,
        start=start_index,
    ):

        candidate = dict(
            record
        )

        candidate[
            "candidate_id"
        ] = f"evidence_candidate_{index:03d}"

        candidate[
            "status"
        ] = "candidate"

        candidate[
            "requires_human_review"
        ] = True

        candidate.setdefault(
            "review_state",
            "needs_review",
        )

        finalized.append(
            candidate
        )

    return finalized


def finalize_agent_suggestions(
    suggestion_records,
    start_index=1,
):

    finalized = []

    for index, record in enumerate(
        suggestion_records,
        start=start_index,
    ):

        suggestion = dict(
            record
        )

        suggestion[
            "suggestion_id"
        ] = f"evidence_suggestion_{index:03d}"

        suggestion[
            "status"
        ] = "candidate"

        suggestion[
            "requires_human_review"
        ] = True

        suggestion.setdefault(
            "suggestion_review_state",
            "needs_review",
        )

        finalized.append(
            suggestion
        )

    return finalized
