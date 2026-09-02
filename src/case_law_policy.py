# ============================================================
# VERGİ AI - CASE LAW POLICY V1
#
# AMAÇ
# ----
#
# Canonical issue candidate'lar (issues.json) ve canonical
# legal research candidate'lar (research.json) için, mevcut
# retrieval altyapısı (query_parser + retriever) üzerinden
# emsal/yargı kararı (case law) ARAŞTIRMA candidate'ları
# üretmek.
#
#
# TEMEL PRENSİP
# -------------
#
# Bu modül bir mahkeme kararı UYDURMAZ. court_name/
# decision_date/case_number/source_url alanları YALNIZ
# canonical documents.json içindeki, belge_turu="Yargı Kararı"
# olarak doğrulanmış gerçek bir kayıttan gelebilir
# (bkz. `evaluate_case_law_document`). Retrieval hiçbir şey
# bulamazsa veya bulduğu şey "Yargı Kararı" değilse, kayıt
# fail-closed bir execution-state taşır (bkz.
# `case_law_discovery.py`).
#
#
# CASE LAW CANDIDATE NE DEĞİLDİR
# --------------------------------
#
#   != gerçek bir mahkeme kararı
#   != bir emsalin uyuşmazlığa uygulanabilir olduğunun
#      kesinleşmesi ("applicability" yalnız unknown/needs_review
#      olabilir - bkz. schema)
#   != case outcome ("bu emsal davayı kazandırır" gibi bir
#      ifade üretilemez)
#   != yerleşik içtihat iddiası
#
#
# ARAŞTIRMA INTENT ÖNCELİĞİ (DETERMİNİSTİK, LLM YOK)
# -----------------------------------------------------
#
# 1. Eğer issue için canonical research.json içinde en az bir
#    citation_ref (resolved olsun olmasın) varsa, arama sorgusu
#    o citation'lar üzerinden kurulur (RULE_CITATION_BASED).
#
# 2. Aksi halde, Legal Research Discovery V1'in issue
#    topic/event_type eşlemesi (`legal_research_discovery
#    .build_research_intent`) yeniden kullanılır ve case-law'a
#    özgü bir ek ifadeyle genişletilir (RULE_TOPIC_BASED).
#    Bu fonksiyon TEKRAR İMPLEMENT EDİLMEZ, olduğu gibi
#    çağrılır.
# ============================================================


import json

from pathlib import Path


from legal_research_discovery import (
    build_research_intent as
        build_legal_research_topic_intent,
)


# ============================================================
# VERSION
# ============================================================

CASE_LAW_POLICY_VERSION = "2"

RULE_CITATION_BASED = (
    "case_law_rule_citation_based_v1"
)

RULE_TOPIC_BASED = (
    "case_law_rule_topic_based_v1"
)

AGENT_TRIGGER_RULE_ID = (
    "case_law_rule_agent_llm_v1"
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

LEGAL_DOCUMENTS_PATH = (
    DATA_DIR
    / "documents.json"
)


# ============================================================
# COVERAGE EXECUTION STATES
#
# Bir coverage kaydının dört ayrı, birbirine dönüştürülemez
# durumu. "retrieval_completed" KARAR SAYISINI TEMSİL ETMEZ -
# yalnız retrieval'in başarıyla çalıştığını ve en az bir
# grounded karar bulunduğunu gösterir (sayı decision_count'ta).
# ============================================================

COVERAGE_EXECUTION_STATES = {
    "retrieval_not_run",
    "retrieval_failed",
    "no_case_law_evidence",
    "retrieval_completed",
}

# Bu durumlarda decision_count SIFIR OLMALIDIR (henüz veya hiç
# grounded karar yok).
ZERO_DECISION_EXECUTION_STATES = {
    "retrieval_not_run",
    "retrieval_failed",
    "no_case_law_evidence",
}


# ============================================================
# CONFIDENCE
#
# Grounded bir decision dahi düşük bir confidence taşır (0.5)
# çünkü applicability HİÇBİR ZAMAN belirlenmez - bu yalnız
# "ilgili olabilecek bir karar var, incele" demektir. Karar
# sayısı/sıralaması confidence'ı ETKİLEMEZ (retrieval sırası
# hukuki üstünlük değildir).
# ============================================================

CONFIDENCE_BY_EXECUTION_STATE = {
    "retrieval_completed":
        0.3,

    "no_case_law_evidence":
        0.2,

    "retrieval_failed":
        0.1,

    "retrieval_not_run":
        0.1,
}

DECISION_CONFIDENCE = 0.5

AGENT_SUGGESTION_DEFAULT_CONFIDENCE = 0.3


# ============================================================
# CASE-LAW SPECIFIC BLOCKLIST (EK SAVUNMA KATMANI)
#
# issue_spotting_validator.FORBIDDEN_PHRASES (Row 9, LOCKED)
# zaten uygulanır; bu liste yalnız case-law'a özgü kesin
# sonuç ifadelerini EKLER. Bu da ana güvenlik mekanizması
# DEĞİLDİR - ana mekanizma court metadata'nın yalnız
# canonical documents.json'dan gelebilmesidir (yapısal).
# ============================================================

CASE_LAW_FORBIDDEN_PHRASES = (
    "bu emsal davayi kazandirir",
    "yerlesik ictihat budur",
    "emsal teskil eder",
    "ictihat bu yondedir",
    "kesin olarak uygulanir",
    "bu karar davayi kazandirir",
    "mahkeme boyle karar verecektir",
    "davayi kaybedersiniz",
    "davayi kazanirsiniz",
)


# ============================================================
# DISCLAIMER
# ============================================================

DISCLAIMER_NOTE = (
    "Bu kayıt bir mahkeme kararının uyuşmazlığa uygulanabilir "
    "olduğunu KESİNLEŞTİRMEZ; case outcome tahmini veya "
    "yerleşik içtihat iddiası içermez. Bulunan (varsa) "
    "kararın somut olaya uygulanabilirliği yalnız insan "
    "hukuki değerlendirmesiyle belirlenebilir; "
    "applicability_result bu nedenle yalnız "
    "'unknown'/'needs_review' olabilir."
)


# ============================================================
# LEGAL DOCUMENTS MANIFEST (documents.json) - YALNIZ OKUMA
# ============================================================

def load_legal_documents_index():

    if not LEGAL_DOCUMENTS_PATH.exists():

        return {}

    with open(
        LEGAL_DOCUMENTS_PATH,
        "r",
        encoding="utf-8",
    ) as file:

        manifest = json.load(
            file
        )

    index = {}

    for document in manifest.get(
        "documents",
        [],
    ):

        document_id = document.get(
            "document_id"
        )

        if document_id:

            index[
                document_id
            ] = document

    return index


# ============================================================
# EVALUATE CASE LAW DOCUMENT
#
# TEK gerçek doğrulama noktası: bir retrieval sonucunun
# gerçekten canonical bir "Yargı Kararı" kaydına karşılık
# gelip gelmediğini kontrol eder. Court metadata YALNIZ
# buradan döner.
# ============================================================

def evaluate_case_law_document(
    document,
):

    if (
        not isinstance(
            document,
            dict,
        )
        or document.get(
            "belge_turu"
        )
        != "Yargı Kararı"
    ):

        return None

    return {
        "document_id":
            document.get(
                "document_id"
            ),

        "court_name":
            document.get(
                "kaynak_kurum"
            ),

        # ----------------------------------------------------
        # court_unit (daire/kurul) ve decision_number (karar
        # no, esas no'dan AYRI) için documents.schema.json'da
        # şu an özel bir alan tanımlı değildir. Belgede bu
        # bilgi yoksa TAHMİN EDİLMEZ; None kalır. İleride
        # documents.json'a "daire"/"karar_no" gibi alanlar
        # eklenirse buradan otomatik okunur.
        # ----------------------------------------------------

        "court_unit":
            document.get(
                "daire"
            ),

        "decision_number":
            document.get(
                "karar_no"
            ),

        "decision_date":
            (
                document.get(
                    "karar_tarihi"
                )
                or document.get(
                    "resmi_gazete_tarihi"
                )
            ),

        "case_number":
            document.get(
                "document_number"
            ),

        "source_url":
            document.get(
                "source_url"
            ),
    }


# ============================================================
# BUILD CASE LAW RESEARCH INTENT (DETERMİNİSTİK, LLM YOK)
# ============================================================

def unique_strings(
    values,
):

    result = []

    for value in values:

        if (
            isinstance(
                value,
                str,
            )
            and value
            and value not in result
        ):

            result.append(
                value
            )

    return result


def build_case_law_intent(
    issue,
    researches_for_issue,
    event_index,
):

    # ========================================================
    # 1. CITATION-BASED (öncelikli)
    #
    # research.json'daki HERHANGİ bir citation_ref (resolved
    # olsun olmasın - "not_found" olması citation'ın var
    # olmadığı anlamına gelmez, yalnız Legal Knowledge
    # Engine'de henüz eklenmediği anlamına gelir).
    # ========================================================

    citation_refs = []

    linked_research_ids = []

    for research in researches_for_issue:

        refs = research.get(
            "citation_refs",
            [],
        )

        if refs:

            citation_refs.extend(
                refs
            )

            linked_research_ids.append(
                research[
                    "research_id"
                ]
            )

    citation_refs = unique_strings(
        citation_refs
    )

    if citation_refs:

        query_text = (
            ", ".join(
                citation_refs[
                    :2
                ]
            )
            + " maddesinin uygulanmasına ilişkin "
            "yargı kararı"
        )

        return {
            "has_intent":
                True,

            "reason_code":
                RULE_CITATION_BASED,

            "query_text":
                query_text,

            "citation_refs":
                citation_refs,

            "linked_research_ids":
                linked_research_ids,
        }

    # ========================================================
    # 2. TOPIC-BASED FALLBACK
    #
    # Legal Research Discovery V1'in mevcut deterministik
    # event_type/issue_type eşlemesi TEKRAR İMPLEMENT
    # EDİLMEDEN yeniden kullanılır.
    # ========================================================

    base_intent = (
        build_legal_research_topic_intent(
            issue,
            event_index,
        )
    )

    if not base_intent.get(
        "has_intent"
    ):

        return {
            "has_intent":
                False,

            "reason_code":
                None,

            "query_text":
                None,

            "citation_refs": [],

            "linked_research_ids": [],
        }

    query_text = (
        base_intent[
            "query_text"
        ]
        + " hakkında emsal yargı kararı"
    )

    return {
        "has_intent":
            True,

        "reason_code":
            RULE_TOPIC_BASED
            + "__"
            + base_intent[
                "reason_code"
            ],

        "query_text":
            query_text,

        "citation_refs": [],

        "linked_research_ids": [],
    }


# ============================================================
# FINALIZE - COVERAGE / DECISIONS / AGENT SUGGESTIONS
#
# Her biri kendi ID alanını atar ve status="candidate" +
# requires_human_review=True sabitler. Coverage ile decision
# AYNI semantik nesne gibi davranmaz - ayrı finalize
# fonksiyonları, ayrı ID uzayları.
# ============================================================

def finalize_coverage(
    coverage_records,
):

    # --------------------------------------------------------
    # coverage_id, build_coverage_record() tarafından issue_id
    # üzerinden DETERMİNİSTİK olarak zaten atanmıştır (1
    # issue = 1 coverage_id, sıralamaya bağlı değildir - bu,
    # decisions'ın source_coverage_id ile coverage'a
    # sıralamadan bağımsız referans verebilmesini sağlar).
    # Burada yalnız status/requires_human_review normalize
    # edilir.
    # --------------------------------------------------------

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


def finalize_decisions(
    decision_records,
    start_index=1,
):

    finalized = []

    for index, record in enumerate(
        decision_records,
        start=start_index,
    ):

        decision = dict(
            record
        )

        decision[
            "decision_id"
        ] = f"case_law_decision_{index:03d}"

        decision[
            "status"
        ] = "candidate"

        decision[
            "requires_human_review"
        ] = True

        decision[
            "provenance_status"
        ] = "verified_against_canonical_documents"

        finalized.append(
            decision
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
        ] = f"case_law_suggestion_{index:03d}"

        suggestion[
            "status"
        ] = "candidate"

        suggestion[
            "requires_human_review"
        ] = True

        finalized.append(
            suggestion
        )

    return finalized
