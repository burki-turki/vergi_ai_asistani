# ============================================================
# VERGİ AI - CASE LAW DISCOVERY V2
#
# AMAÇ
# ----
#
# Canonical issue + (varsa) canonical research candidate'lar
# için, mevcut retrieval altyapısını (query_parser + retriever)
# kullanarak emsal/yargı kararı araştırması yapmak.
#
# V2 DEĞİŞİKLİĞİ: COVERAGE İLE DECISION AYRIMI
# -----------------------------------------------
#
# V1'de "bulundu/bulunamadı" TEK bir kayıtla temsil
# ediliyordu; bu, bir issue için birden fazla karar
# bulunduğunda karar sayısını gizliyordu.
#
# V2'de:
#
#   - HER issue için TAM OLARAK BİR "coverage" kaydı
#     (execution_state + decision_count) üretilir.
#
#   - O coverage'a bağlı 0..N ayrı "decision" kaydı üretilir
#     (her biri canonical documents.json'a karşı AYRI AYRI
#     doğrulanmış, benzersiz bir "Yargı Kararı").
#
#   - Retrieval sıralaması hukuki üstünlük/emsal gücü olarak
#     YORUMLANMAZ; tüm grounded sonuçlar eşit muamele görür.
#
#   - Aynı source_document_id aynı issue için yalnız BİR
#     decision üretir (dedup).
#
#
# ZİNCİR
# ------
#
# canonical issue (+ varsa canonical research citation'ları)
#        ↓
# build_case_law_intent()               [case_law_policy.py]
#        ↓
# query_parser.parse_query_metadata()   [MEVCUT, DEĞİŞTİRİLMEDİ]
#        ↓
# retriever.retrieve_detailed(          [MEVCUT, DEĞİŞTİRİLMEDİ]
#     belge_turu="Yargı Kararı")
#        ↓
# TÜM sonuçlar belge_turu filtresi + document_id dedup
#        ↓
# HER benzersiz sonuç için evaluate_case_law_document()
# [case_law_policy.py - canonical documents.json'a karşı
#  AYRI AYRI doğrular]
#        ↓
# 1 coverage kaydı + 0..N decision kaydı
#
#
# FAIL-CLOSED - DÖRT AYRI COVERAGE DURUMU
# -------------------------------------------
#
# retrieval_not_run    : intent var, retrieval HENÜZ DENENMEDİ.
# retrieval_failed     : retrieval DENENDİ, teknik olarak çöktü.
# no_case_law_evidence : retrieval BAŞARIYLA çalıştı, grounded
#                        hiçbir "Yargı Kararı" yok
#                        (decision_count=0).
# retrieval_completed  : retrieval BAŞARIYLA çalıştı VE en az
#                        bir grounded karar bulundu
#                        (decision_count>=1).
#
# Bu dört durum birbirine dönüştürülemez.
# ============================================================


from case_law_policy import (
    CONFIDENCE_BY_EXECUTION_STATE,
    DECISION_CONFIDENCE,
    DISCLAIMER_NOTE,
    evaluate_case_law_document,
)


# ============================================================
# VERSION
# ============================================================

CASE_LAW_DISCOVERY_VERSION = "2"


# ============================================================
# HELPERS
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


def coverage_id_for_issue(
    issue,
):

    return f"coverage_{issue['issue_id']}"


# ============================================================
# COVERAGE RECORD
# ============================================================

COVERAGE_TITLES = {
    "retrieval_not_run": (
        "Issue için case-law araştırma intent'i oluştu; "
        "retrieval henüz çalıştırılmadı"
    ),

    "retrieval_failed": (
        "Case-law retrieval teknik olarak başarısız oldu"
    ),

    "no_case_law_evidence": (
        "Case-law araştırması çalıştı ancak grounded emsal "
        "karar bulunamadı"
    ),

    "retrieval_completed": (
        "Case-law araştırması tamamlandı; grounded karar(lar) "
        "bulundu"
    ),
}


def build_coverage_description(
    execution_state,
    query_text,
    decision_count=0,
    failure_reason=None,
):

    if execution_state == "retrieval_not_run":

        return (
            f"'{query_text}' konusunda bir case-law "
            "araştırma intent'i tespit edilmiştir; ancak "
            "network erişimi açık olmadığı için retrieval "
            "HENÜZ ÇALIŞTIRILMAMIŞTIR. Bu kayıt bir emsal "
            "kararın bulunduğunu veya bulunmadığını İDDİA "
            "ETMEZ."
        )

    if execution_state == "retrieval_failed":

        reason_note = (
            f" (failure_reason='{failure_reason}')"
            if failure_reason
            else ""
        )

        return (
            f"'{query_text}' konusunda case-law retrieval "
            "çalıştırılmaya çalışılmış ancak teknik bir "
            f"hata nedeniyle tamamlanamamıştır{reason_note}"
            ". Bu, emsal kararın var olmadığı anlamına "
            "GELMEZ."
        )

    if execution_state == "no_case_law_evidence":

        reason_note = (
            f" (retrieval_failure_reason='{failure_reason}')"
            if failure_reason
            else ""
        )

        return (
            f"'{query_text}' konusunda case-law araştırması "
            f"BAŞARIYLA çalıştırılmıştır{reason_note}; ancak "
            "mevcut Legal Knowledge Engine içinde "
            "belge_turu='Yargı Kararı' olan eşleşen bir "
            "kayıt bulunamamıştır. Bu, ilgili konuda emsal "
            "kararın var olmadığı anlamına GELMEZ; yalnızca "
            "mevcut canonical veri tabanında henüz "
            "bulunmadığını gösterir."
        )

    # retrieval_completed

    return (
        f"'{query_text}' konusunda case-law araştırması "
        f"BAŞARIYLA çalıştırılmış ve {decision_count} adet "
        "grounded karar bulunmuştur (bkz. "
        "case_law_decisions). Bu sayı ve bulunma sırası "
        "hiçbir hukuki üstünlük/emsal gücü ifade etmez; "
        "her karar ayrıca ve eşit şekilde değerlendirilmesi "
        "gereken bir adaydır."
    )


def build_coverage_record(
    issue,
    intent,
    execution_state,
    decision_count=0,
    failure_reason=None,
):

    query_text = intent[
        "query_text"
    ]

    description = (
        build_coverage_description(
            execution_state,
            query_text,
            decision_count,
            failure_reason,
        )
        + " "
        + DISCLAIMER_NOTE
    )

    return {
        "coverage_id":
            coverage_id_for_issue(
                issue
            ),

        "source_issue_id":
            issue[
                "issue_id"
            ],

        "execution_state":
            execution_state,

        "retrieval_query":
            query_text,

        "decision_count":
            decision_count,

        "trigger_rule_id":
            intent[
                "reason_code"
            ],

        "citation_refs":
            unique_strings(
                intent.get(
                    "citation_refs",
                    [],
                )
            ),

        "title":
            COVERAGE_TITLES[
                execution_state
            ],

        "description":
            description,

        "confidence":
            CONFIDENCE_BY_EXECUTION_STATE.get(
                execution_state,
                0.1,
            ),

        "requires_human_review":
            True,

        "notes":
            None,
    }


# ============================================================
# DECISION RECORD
# ============================================================

def build_decision_record(
    issue,
    intent,
    case_law_info,
    coverage_id,
    retrieved_chunk_id=None,
):

    query_text = intent[
        "query_text"
    ]

    description = (
        f"'{query_text}' sorgusu ile yapılan case-law "
        f"araştırması sonucunda {case_law_info['document_id']} "
        "kaydı (belge_turu='Yargı Kararı') canonical "
        "documents.json içinde doğrulanmıştır. Mahkeme: "
        f"{case_law_info['court_name']}; esas/karar no: "
        f"{case_law_info['case_number']}; tarih: "
        f"{case_law_info['decision_date']}. Bu kaydın "
        "diğer olası kararlara göre bir önceliği/üstünlüğü "
        "YOKTUR. "
        + DISCLAIMER_NOTE
    )

    return {
        "source_issue_id":
            issue[
                "issue_id"
            ],

        "source_research_ids":
            unique_strings(
                intent.get(
                    "linked_research_ids",
                    [],
                )
            ),

        "source_coverage_id":
            coverage_id,

        "source_document_id":
            case_law_info[
                "document_id"
            ],

        "court_name":
            case_law_info[
                "court_name"
            ],

        "court_unit":
            case_law_info.get(
                "court_unit"
            ),

        "case_number":
            case_law_info[
                "case_number"
            ],

        "decision_number":
            case_law_info.get(
                "decision_number"
            ),

        "decision_date":
            case_law_info[
                "decision_date"
            ],

        "source_url":
            case_law_info[
                "source_url"
            ],

        "retrieved_chunk_id":
            retrieved_chunk_id,

        "applicability_result":
            "needs_review",

        "title":
            (
                "Case-law araştırması ile canonical bir "
                "Yargı Kararı kaydı doğrulandı"
            ),

        "description":
            description,

        "trigger_rule_id":
            intent[
                "reason_code"
            ],

        "confidence":
            DECISION_CONFIDENCE,

        "requires_human_review":
            True,

        "notes":
            None,
    }


# ============================================================
# RUN CASE LAW DISCOVERY (TEK ISSUE İÇİN)
#
# Döner: (coverage_record, [decision_record, ...], warnings)
# ============================================================

def run_case_law_discovery_for_issue(
    issue,
    intent,
    documents_index,
    retrieval_fn=None,
    network_allowed=False,
):

    warnings = []

    if not intent.get(
        "has_intent"
    ):

        return (
            None,
            [],
            warnings,
        )

    query_text = intent[
        "query_text"
    ]

    # ========================================================
    # NETWORK SAFETY GATE
    # ========================================================

    if retrieval_fn is None:

        if not network_allowed:

            warnings.append(
                "Network access disabled "
                "(network_allowed=False, --allow-network "
                "verilmedi); case-law discovery bu issue "
                "için ÇALIŞTIRILAMADI (coverage kaydı "
                "retrieval_not_run olarak üretiliyor): "
                f"{issue['issue_id']}"
            )

            return (
                build_coverage_record(
                    issue,
                    intent,
                    "retrieval_not_run",
                ),
                [],
                warnings,
            )

        try:

            from retriever import (
                retrieve_detailed as
                    real_retrieve_detailed,
            )

            retrieval_fn = (
                real_retrieve_detailed
            )

        except Exception as error:

            warnings.append(
                "Retriever import edilemedi; case-law "
                f"discovery teknik olarak başarısız: "
                f"{error}"
            )

            return (
                build_coverage_record(
                    issue,
                    intent,
                    "retrieval_failed",
                    failure_reason=
                        "retriever_unavailable",
                ),
                [],
                warnings,
            )

    # ========================================================
    # QUERY PARSER (PURE, NETWORK YOK)
    # ========================================================

    from query_parser import (
        parse_query_metadata,
    )

    metadata_hints = (
        parse_query_metadata(
            query_text
        )
    )

    # ========================================================
    # RETRIEVAL (FAIL-CLOSED) - belge_turu filtresi ile
    # ========================================================

    try:

        retrieval_result = (
            retrieval_fn(
                query=
                    query_text,

                kanun_no=
                    metadata_hints.get(
                        "kanun_no"
                    ),

                madde=
                    metadata_hints.get(
                        "madde"
                    ),

                fikra=
                    metadata_hints.get(
                        "fikra"
                    ),

                bent=
                    metadata_hints.get(
                        "bent"
                    ),

                belge_turu=
                    "Yargı Kararı",

                temporal_mode=
                    "neutral",

                query_date=
                    None,
            )
        )

    except Exception as error:

        warnings.append(
            "Case-law retrieval çağrısı teknik olarak "
            f"başarısız oldu (retrieval_failed): {error}"
        )

        return (
            build_coverage_record(
                issue,
                intent,
                "retrieval_failed",
                failure_reason=
                    "retrieval_call_failed",
            ),
            [],
            warnings,
        )

    if not isinstance(
        retrieval_result,
        dict,
    ):

        warnings.append(
            "Case-law retrieval sonucu beklenmeyen "
            f"formatta (retrieval_failed): "
            f"{issue['issue_id']}"
        )

        return (
            build_coverage_record(
                issue,
                intent,
                "retrieval_failed",
                failure_reason=
                    "invalid_retrieval_result",
            ),
            [],
            warnings,
        )

    results = (
        retrieval_result.get(
            "results",
            [],
        )
    )

    failure_reason = (
        retrieval_result.get(
            "retrieval_failure_reason"
        )
    )

    # ========================================================
    # BİRİNCİ FİLTRE: yalnız gerçekten "Yargı Kararı"
    # işaretli sonuçlar case-law adayı sayılır.
    # ========================================================

    case_law_results = [
        result
        for result in results
        if isinstance(
            result,
            dict,
        )
        and result.get(
            "belge_turu"
        )
        == "Yargı Kararı"
    ]

    if (
        failure_reason
        or not case_law_results
    ):

        return (
            build_coverage_record(
                issue,
                intent,
                "no_case_law_evidence",
                failure_reason=
                    failure_reason,
            ),
            [],
            warnings,
        )

    # ========================================================
    # İKİNCİ FİLTRE (ASIL DOĞRULAMA) + DEDUP: dönen HER
    # benzersiz document_id canonical documents.json'da
    # AYRICA belge_turu="Yargı Kararı" olarak teyit
    # edilmelidir. Court metadata YALNIZ buradan gelir.
    # Aynı document_id birden fazla chunk olarak dönerse
    # yalnız BİR decision üretilir (dedup). Sıralama hiçbir
    # hukuki üstünlük ifade etmeyecek şekilde korunur (yalnız
    # ilk görülen chunk_id referans için kullanılır).
    # ========================================================

    coverage_id = (
        coverage_id_for_issue(
            issue
        )
    )

    seen_document_ids = set()

    decisions = []

    for result in case_law_results:

        document_id = result.get(
            "document_id"
        )

        if (
            not document_id
            or document_id
            in seen_document_ids
        ):

            continue

        canonical_document = (
            documents_index.get(
                document_id
            )
        )

        case_law_info = (
            evaluate_case_law_document(
                canonical_document
            )
        )

        if case_law_info is None:

            # Bu belirli sonuç doğrulanamadı; DİĞER
            # sonuçların değerlendirilmesini engellemez
            # (fail-closed yalnız bu tek adayı eler).

            continue

        seen_document_ids.add(
            document_id
        )

        decisions.append(
            build_decision_record(
                issue,
                intent,
                case_law_info,
                coverage_id,
                retrieved_chunk_id=
                    result.get(
                        "chunk_id"
                    ),
            )
        )

    if not decisions:

        return (
            build_coverage_record(
                issue,
                intent,
                "no_case_law_evidence",
                failure_reason=
                    "no_result_verified_in_canonical_"
                    "manifest",
            ),
            [],
            warnings,
        )

    coverage = (
        build_coverage_record(
            issue,
            intent,
            "retrieval_completed",
            decision_count=
                len(
                    decisions
                ),
        )
    )

    return (
        coverage,
        decisions,
        warnings,
    )


# ============================================================
# RUN FOR ALL ISSUES
#
# Döner: (coverage_records[], decision_records[], warnings[])
# ============================================================

def run_case_law_discovery_for_issues(
    issues,
    build_intent_fn,
    documents_index,
    retrieval_fn=None,
    network_allowed=False,
):

    coverage_records = []

    decision_records = []

    warnings = []

    for issue in issues:

        intent = build_intent_fn(
            issue
        )

        (
            coverage,
            decisions,
            issue_warnings,
        ) = (
            run_case_law_discovery_for_issue(
                issue,
                intent,
                documents_index,
                retrieval_fn=
                    retrieval_fn,

                network_allowed=
                    network_allowed,
            )
        )

        warnings.extend(
            issue_warnings
        )

        if coverage is not None:

            coverage_records.append(
                coverage
            )

            decision_records.extend(
                decisions
            )

    return (
        coverage_records,
        decision_records,
        warnings,
    )
