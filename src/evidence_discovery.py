# ============================================================
# VERGİ AI - EVIDENCE DISCOVERY V1
#
# AMAÇ
# ----
#
# Canonical issue + approved canonical fact (Row 6) + active
# canonical case document (Row 3) kayıtları üzerinden, HER
# issue için deterministik bir ATOMİK ALLOWLIST üretmek.
#
# Bu modül hiçbir supports/contradicts İLİŞKİSİ ÖNERMEZ; yalnız
# Agent'ın (evidence_agent.py) seçim yapabileceği, zaten
# grounded (issue, fact, document) üçlülerini listeler.
#
#
# ZİNCİR
# ------
#
# canonical issue.source_fact_ids
#        ↓
# timeline_validator.load_canonical_fact_index()  [MEVCUT]
#        ↓ (yalnız approved fact)
# case_document_validator.load_case_documents()   [MEVCUT]
#        ↓ (yalnız active=true document)
# 1 allowlist kaydı / (issue, fact) çifti
#        ↓
# 1 coverage kaydı / issue (execution_state HENÜZ agent
# çalışmadan önce yalnız "blocked_missing_input" veya
# "allowlist var" ayrımını yapar - agent sonrası
# evidence_engine.py execution_state'i finalize eder)
#
#
# FAIL-CLOSED
# -----------
#
# Bir issue'nun source_fact_ids'i boşsa, hiçbiri approved
# fact'e çözülemiyorsa veya hiçbirinin belgesi active
# değilse -> allowlist_count=0 -> execution_state
# BLOCKED_MISSING_INPUT (agent hiç çağrılmaz).
# ============================================================


import copy


# ============================================================
# VERSION
# ============================================================

EVIDENCE_DISCOVERY_VERSION = "1"


# ============================================================
# COVERAGE TITLES (execution_state başına deterministik)
# ============================================================

COVERAGE_TITLES = {
    "blocked_missing_input": (
        "Issue için değerlendirilebilir approved fact/active "
        "document bulunamadı"
    ),

    "analysis_not_run": (
        "Issue için evidence allowlist'i oluştu; Agent henüz "
        "çalıştırılmadı"
    ),

    "analysis_completed": (
        "Issue için evidence analizi tamamlandı"
    ),

    "analysis_partial": (
        "Issue için evidence analizi kısmen tamamlandı"
    ),

    "analysis_failed": (
        "Issue için evidence analizi teknik olarak "
        "başarısız oldu"
    ),
}


def build_coverage_description(
    execution_state,
    allowlist_count,
    candidate_count,
    suggestion_count,
    reason_codes,
):

    from evidence_policy import (
        DISCLAIMER_NOTE,
    )

    if execution_state == "blocked_missing_input":

        return (
            "Bu issue için resolve edilebilen approved fact "
            "+ active canonical document ikilisi "
            "bulunamamıştır (allowlist_count=0); Agent bu "
            "issue için HİÇ ÇAĞRILMAMIŞTIR. Bu, issue'nun "
            "geçersiz olduğu anlamına GELMEZ; yalnızca "
            "mevcut approved fact/document verisiyle "
            "değerlendirilebilir bir eşleşme kurulamadığını "
            "gösterir. "
            + DISCLAIMER_NOTE
        )

    if execution_state == "analysis_not_run":

        return (
            f"Bu issue için {allowlist_count} adet "
            "deterministik allowlist kaydı oluşmuştur; "
            "ancak Evidence Agent (LLM) HENÜZ "
            "ÇALIŞTIRILMAMIŞTIR. Bu kayıt hiçbir "
            "supports/contradicts ilişkisinin var olduğunu "
            "veya olmadığını İDDİA ETMEZ. "
            + DISCLAIMER_NOTE
        )

    if execution_state == "analysis_failed":

        return (
            f"Bu issue için {allowlist_count} adet allowlist "
            "kaydı vardı; Evidence Agent çağrısı teknik "
            f"olarak başarısız oldu (reason_codes="
            f"{reason_codes}). Bu, delilin var olmadığı "
            "anlamına GELMEZ. "
            + DISCLAIMER_NOTE
        )

    if execution_state == "analysis_partial":

        return (
            f"Bu issue için {allowlist_count} adet allowlist "
            "kaydı değerlendirildi; Agent cevabının bir "
            "bölümü şekil/grounding hatası nedeniyle "
            f"reddedildi (reason_codes={reason_codes}). "
            f"Kabul edilen {candidate_count} candidate ve "
            f"{suggestion_count} suggestion ile kısmi bir "
            "sonuç üretilmiştir. "
            + DISCLAIMER_NOTE
        )

    # analysis_completed

    return (
        f"Bu issue için {allowlist_count} adet allowlist "
        "kaydının TAMAMI Agent tarafından hatasız "
        f"değerlendirilmiştir; {candidate_count} adet "
        f"evidence candidate ve {suggestion_count} adet "
        "suggestion üretilmiştir (candidate_count=0 olması "
        "GEÇERLİDİR - Agent hiçbir grounded ilişki "
        "bulmamış olabilir). "
        + DISCLAIMER_NOTE
    )


def build_coverage_record(
    issue,
    execution_state,
    allowlist_count,
    candidate_count=0,
    suggestion_count=0,
    reason_codes=None,
):

    from evidence_policy import (
        CONFIDENCE_BY_EXECUTION_STATE,
        DETERMINISTIC_TRIGGER_RULE_ID,
        coverage_id_for_issue,
    )

    reason_codes = list(
        reason_codes
        or []
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

        "allowlist_count":
            allowlist_count,

        "candidate_count":
            candidate_count,

        "suggestion_count":
            suggestion_count,

        "reason_codes":
            reason_codes,

        "trigger_rule_id":
            DETERMINISTIC_TRIGGER_RULE_ID,

        "title":
            COVERAGE_TITLES[
                execution_state
            ],

        "description":
            build_coverage_description(
                execution_state,
                allowlist_count,
                candidate_count,
                suggestion_count,
                reason_codes,
            ),

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
# ALLOWLIST BUILDING (TEK ISSUE İÇİN)
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


def build_allowlist_for_issue(
    issue,
    fact_index,
    active_documents_index,
):

    warnings = []

    entries = []

    fact_ids = unique_strings(
        issue.get(
            "source_fact_ids",
            [],
        )
    )

    if not fact_ids:

        warnings.append(
            "Issue "
            f"{issue['issue_id']} için source_fact_ids "
            "boş; allowlist üretilemedi "
            "(blocked_missing_input)."
        )

        return (
            entries,
            warnings,
        )

    for fact_id in fact_ids:

        fact_record = fact_index.get(
            fact_id
        )

        if fact_record is None:

            warnings.append(
                f"Issue {issue['issue_id']}: fact_id "
                f"'{fact_id}' canonical (approved) "
                "facts.json içinde bulunamadı; bu fact "
                "allowlist'e alınmadı."
            )

            continue

        fact = fact_record[
            "fact"
        ]

        source_document_id = fact_record[
            "source_document_id"
        ]

        document = active_documents_index.get(
            source_document_id
        )

        if document is None:

            warnings.append(
                f"Issue {issue['issue_id']}: fact_id "
                f"'{fact_id}' belgesi "
                f"'{source_document_id}' active=true "
                "canonical case document olarak "
                "bulunamadı; bu fact allowlist'e alınmadı."
            )

            continue

        source = fact.get(
            "source",
            {},
        ) or {}

        entries.append(
            {
                "issue_id":
                    issue[
                        "issue_id"
                    ],

                "fact_id":
                    fact_id,

                "document_id":
                    source_document_id,

                "source_location":
                    copy.deepcopy(
                        {
                            "page":
                                source.get(
                                    "page"
                                ),

                            "section":
                                source.get(
                                    "section"
                                ),

                            "paragraph":
                                source.get(
                                    "paragraph"
                                ),

                            "text_excerpt":
                                source.get(
                                    "text_excerpt"
                                ),
                        }
                    ),

                "source_excerpt":
                    source.get(
                        "text_excerpt"
                    ),

                "issue_text": {
                    "issue_id":
                        issue[
                            "issue_id"
                        ],

                    "issue_type":
                        issue.get(
                            "issue_type"
                        ),

                    "title":
                        issue.get(
                            "title"
                        ),

                    "description":
                        issue.get(
                            "description"
                        ),
                },

                "fact_text": {
                    "fact_id":
                        fact_id,

                    "fact_kind":
                        fact.get(
                            "fact_kind"
                        ),

                    "statement":
                        fact.get(
                            "statement"
                        ),

                    "normalized_statement":
                        fact.get(
                            "normalized_statement"
                        ),
                },
            }
        )

    return (
        entries,
        warnings,
    )


def build_allowlist_for_issues(
    issues,
    fact_index,
    active_documents_index,
):

    allowlist_by_issue = {}

    warnings = []

    for issue in issues:

        (
            entries,
            issue_warnings,
        ) = build_allowlist_for_issue(
            issue,
            fact_index,
            active_documents_index,
        )

        allowlist_by_issue[
            issue[
                "issue_id"
            ]
        ] = entries

        warnings.extend(
            issue_warnings
        )

    return (
        allowlist_by_issue,
        warnings,
    )
