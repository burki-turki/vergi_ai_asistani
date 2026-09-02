# ============================================================
# VERGİ AI - LEGAL RESEARCH ISSUE-DRIVEN DISCOVERY V1
#
# AMAÇ
# ----
#
# Açık (explicit) bir citation taşımayan canonical issue
# candidate'lar için, mevcut retrieval altyapısını (query_parser
# + retriever) kullanarak Legal Knowledge Engine içinde
# issue-driven araştırma yapmak.
#
#
# ZİNCİR
# ------
#
# canonical issue (explicit citation YOK)
#        ↓
# build_research_intent()               [deterministik, LLM yok]
#        ↓
# query_parser.parse_query_metadata()   [MEVCUT, DEĞİŞTİRİLMEDİ]
#        ↓
# retriever.retrieve_detailed()         [MEVCUT, DEĞİŞTİRİLMEDİ]
#        ↓
# resolve_provision_locator()           [legal_research_policy.py,
#                                         explicit-citation path ile
#                                         AYNI fonksiyon - tekrar
#                                         implement edilmez]
#        ↓
# research candidate (issue_driven_discovery)
#
#
# TEMEL PRENSİP
# -------------
#
# - build_research_intent() yalnız DETERMİNİSTİK keyword/topic
#   eşleşmesi yapar (timeline event_type / issue_type tabanlı).
#   LLM KULLANMAZ.
#
# - query_parser.py ve retriever.py YENİDEN İMPLEMENT EDİLMEZ;
#   olduğu gibi çağrılır.
#
# - retriever.py modül import zamanında FAISS index + OpenAI
#   client kurar (gerçek network/dosya bağımlılığı). Bu yüzden
#   BURADA modül seviyesinde import EDİLMEZ; yalnız gerçekten
#   network_allowed=True olduğunda, fonksiyon içinde LAZY
#   import edilir.
#
# - retrieval_fn injectable'dır: testler gerçek retriever
#   yerine FakeRetrievalClient enjekte eder (network'e hiç
#   dokunmadan).
#
#
# FAIL-CLOSED
# -----------
#
# - network_allowed=False VE retrieval_fn verilmemişse:
#   discovery hiç denenmez (retriever import edilmez).
#
# - Retrieval hiçbir sonuç döndürmezse veya
#   retrieval_failure_reason set edilmişse:
#   finding_status="no_research_evidence" (fail-closed;
#   LLM bilgisi hukuki kaynak yerine KULLANILMAZ).
#
# - Retrieval bir chunk döndürse bile, o chunk'ın
#   madde/fikra/bent'i provision_repository +
#   provision_version_policy + provision_policy üzerinden
#   AYRICA çözümlenir; retriever'ın kendi (belge seviyesi)
#   version kararı tek başına yeterli sayılmaz.
# ============================================================


from legal_research_policy import (
    FINDING_STATUS_RESOLVED,
    CONFIDENCE_BY_FINDING_STATUS,
    DISCLAIMER_NOTE,
    get_document_short_title,
    resolve_provision_locator,
)


# ============================================================
# VERSION
# ============================================================

LEGAL_RESEARCH_DISCOVERY_VERSION = "1"

DISCOVERY_TRIGGER_RULE_ID = (
    "research_rule_issue_driven_discovery_v1"
)


# ============================================================
# DETERMINISTIC RESEARCH INTENT MAPPING
#
# LLM KULLANMAZ. timeline event_type / issue_type -> sabit
# Türkçe arama sorgusu eşlemesidir (timeline_engine.py'nin
# classify_event_type() işlevine benzer, deterministik
# keyword-tabanlı bir eşleme).
# ============================================================

EVENT_TYPE_RESEARCH_INTENT = {
    "notification_date": (
        "event_type_notification_date",
        "tebliğ tarihinin idari yargıda dava açma süresine "
        "etkisi",
    ),

    "filing_date": (
        "event_type_filing_date",
        "vergi mahkemesinde dava açma süresinin başlangıcı",
    ),

    "administrative_application_date": (
        "event_type_administrative_application_date",
        "idari başvurunun dava açma süresine etkisi",
    ),

    "administrative_decision_date": (
        "event_type_administrative_decision_date",
        "idari kararın dava açma süresine etkisi",
    ),

    "court_decision_date": (
        "event_type_court_decision_date",
        "mahkeme kararına karşı kanun yoluna başvuru süresi",
    ),

    "appeal_date": (
        "event_type_appeal_date",
        "istinaf veya temyiz başvuru süresi",
    ),
}

ISSUE_TYPE_RESEARCH_INTENT_FALLBACK = {
    "deadline_risk": (
        "issue_type_deadline_risk",
        "vergi mahkemesinde dava açma süresi",
    ),

    "verification_gap": (
        "issue_type_verification_gap",
        "tebliğ tarihinin ispatı ve süreye etkisi",
    ),
}


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


# ============================================================
# BUILD RESEARCH INTENT (DETERMİNİSTİK, LLM YOK)
# ============================================================

def build_research_intent(
    issue,
    event_index,
):

    for event_id in issue.get(
        "source_timeline_event_ids",
        [],
    ):

        event = event_index.get(
            event_id
        )

        if not event:

            continue

        mapping = (
            EVENT_TYPE_RESEARCH_INTENT.get(
                event.get(
                    "event_type"
                )
            )
        )

        if mapping:

            reason_code, query_text = mapping

            return {
                "has_intent":
                    True,

                "reason_code":
                    reason_code,

                "query_text":
                    query_text,
            }

    mapping = (
        ISSUE_TYPE_RESEARCH_INTENT_FALLBACK.get(
            issue.get(
                "issue_type"
            )
        )
    )

    if mapping:

        reason_code, query_text = mapping

        return {
            "has_intent":
                True,

            "reason_code":
                reason_code,

            "query_text":
                query_text,
        }

    return {
        "has_intent":
            False,

        "reason_code":
            None,

        "query_text":
            None,
    }


# ============================================================
# CANDIDATE BUILDERS
# ============================================================

EXECUTION_STATE_TITLES = {
    "retrieval_not_run": (
        "Issue için araştırma intent'i oluştu; retrieval "
        "henüz çalıştırılmadı"
    ),

    "retrieval_failed": (
        "Issue-driven retrieval teknik olarak başarısız "
        "oldu"
    ),

    "no_research_evidence": (
        "Issue-driven araştırma çalıştı ancak kaynak "
        "bulunamadı"
    ),
}


def build_execution_state_description(
    finding_status,
    query_text,
    failure_reason=None,
):

    if finding_status == "retrieval_not_run":

        return (
            f"'{query_text}' konusunda bir araştırma "
            "intent'i (research intent) tespit "
            "edilmiştir; ancak network erişimi açık "
            "olmadığı (network_allowed=False / "
            "--allow-network verilmedi) için retrieval "
            "HENÜZ ÇALIŞTIRILMAMIŞTIR. Bu kayıt bir "
            "kaynağın bulunduğunu veya bulunmadığını "
            "İDDİA ETMEZ; yalnızca bu issue için ileride "
            "retrieval çalıştırılması gerektiğini "
            "işaretler."
        )

    if finding_status == "retrieval_failed":

        reason_note = (
            f" (failure_reason='{failure_reason}')"
            if failure_reason
            else ""
        )

        return (
            f"'{query_text}' konusunda issue-driven "
            "retrieval çalıştırılmaya çalışılmış ancak "
            f"teknik bir hata nedeniyle tamamlanamamıştır"
            f"{reason_note}. Bu, kaynağın var olmadığı "
            "veya bulunmadığı anlamına GELMEZ; yalnızca "
            "retrieval'ın teknik olarak başarısız "
            "olduğunu gösterir. Retrieval'ın yeniden "
            "denenmesi önerilir."
        )

    # no_research_evidence

    reason_note = (
        f" (retrieval_failure_reason='{failure_reason}')"
        if failure_reason
        else ""
    )

    return (
        f"'{query_text}' konusunda issue-driven "
        f"araştırma BAŞARIYLA çalıştırılmıştır"
        f"{reason_note}; ancak mevcut Legal Knowledge "
        "Engine içinde eşleşen bir kaynak/provizyon "
        "bulunamamıştır. Bu, ilgili hükmün bulunmadığı "
        "veya geçersiz olduğu anlamına GELMEZ; yalnızca "
        "bu konunun henüz Legal Knowledge Engine'e "
        "eklenmediğini veya mevcut kayıtlarla "
        "eşleşmediğini gösterir. LLM bilgisi hukuki "
        "kaynak yerine kullanılmamıştır."
    )


def build_execution_state_candidate(
    issue,
    query_text,
    finding_status,
    failure_reason=None,
):

    # --------------------------------------------------------
    # Üç durum da AYRI, birbirine dönüştürülemez anlamlar
    # taşır (bkz. legal_research_policy.py
    # EXECUTION_STATE_FINDING_STATUSES). Hiçbiri
    # resolved_provision_ids/formal_result/
    # applicability_result taşımaz - bu bir coverage
    # kaydıdır, bir çözüm değil.
    # --------------------------------------------------------

    description = (
        build_execution_state_description(
            finding_status,
            query_text,
            failure_reason,
        )
        + " "
        + DISCLAIMER_NOTE
    )

    return {
        "research_type":
            "issue_driven_discovery",

        "source_issue_id":
            issue[
                "issue_id"
            ],

        "title":
            EXECUTION_STATE_TITLES[
                finding_status
            ],

        "description":
            description,

        "trigger_rule_id":
            DISCOVERY_TRIGGER_RULE_ID,

        "citation_refs": [],

        "resolved_provision_ids": [],

        "finding_status":
            finding_status,

        "formal_result":
            None,

        "applicability_result":
            None,

        "retrieval_query":
            query_text,

        "source_fact_ids": [],

        "source_timeline_event_ids":
            unique_strings(
                issue.get(
                    "source_timeline_event_ids",
                    [],
                )
            ),

        "source_deadline_ids": [],

        "related_party_ids": [],

        "related_dispute_item_ids": [],

        "confidence":
            CONFIDENCE_BY_FINDING_STATUS.get(
                finding_status,
                0.1,
            ),

        "requires_human_review":
            True,

        "notes":
            None,
    }


def build_discovery_candidate(
    issue,
    query_text,
    citation_display,
    locator_result,
    documents_index,
):

    finding_status = locator_result[
        "finding_status"
    ]

    formal_dict = locator_result[
        "formal"
    ]

    applicability_dict = locator_result[
        "applicability"
    ]

    formal_result = (
        formal_dict[
            "result"
        ]
        if formal_dict
        else None
    )

    applicability_result = (
        applicability_dict[
            "result"
        ]
        if applicability_dict
        else None
    )

    if finding_status in FINDING_STATUS_RESOLVED:

        provision = locator_result[
            "selected_provision"
        ]

        short_title = (
            get_document_short_title(
                documents_index,
                provision.get(
                    "document_id"
                ),
            )
        )

        title = (
            "Issue-driven araştırma ile Legal Knowledge "
            "Engine'de kaynak bulundu"
        )

        body = (
            f"'{query_text}' sorgusu ile yapılan "
            "issue-driven araştırma sonucunda "
            f"{provision.get('provision_id')} "
            f"({short_title}) bulunmuştur. Deterministik "
            "Legal Knowledge Engine bulgusu: "
            f"formal_result='{formal_result}' "
            f"({formal_dict['reason']}), "
            f"applicability_result='{applicability_result}' "
            f"({applicability_dict['reason']})."
        )

    else:

        title = (
            "Issue-driven araştırma bir kaynak buldu ancak "
            "çözümleyemedi"
        )

        body = (
            f"'{query_text}' sorgusu ile yapılan "
            "issue-driven araştırma bir kaynağa "
            f"({citation_display}) ulaştı; ancak sürüm/"
            "uygulanabilirlik belirsizliği nedeniyle "
            f"çözümlenemedi (finding_status="
            f"'{finding_status}')."
        )

    description = (
        body
        + " "
        + DISCLAIMER_NOTE
    )

    return {
        "research_type":
            "issue_driven_discovery",

        "source_issue_id":
            issue[
                "issue_id"
            ],

        "title":
            title,

        "description":
            description,

        "trigger_rule_id":
            DISCOVERY_TRIGGER_RULE_ID,

        "citation_refs": [
            citation_display
        ],

        "resolved_provision_ids":
            locator_result[
                "resolved_provision_ids"
            ],

        "finding_status":
            finding_status,

        "formal_result":
            formal_result,

        "applicability_result":
            applicability_result,

        "retrieval_query":
            query_text,

        "source_fact_ids": [],

        "source_timeline_event_ids":
            unique_strings(
                issue.get(
                    "source_timeline_event_ids",
                    [],
                )
            ),

        "source_deadline_ids": [],

        "related_party_ids": [],

        "related_dispute_item_ids": [],

        "confidence":
            CONFIDENCE_BY_FINDING_STATUS.get(
                finding_status,
                0.3,
            ),

        "requires_human_review":
            True,

        "notes":
            None,
    }


# ============================================================
# RUN ISSUE-DRIVEN DISCOVERY (TEK ISSUE İÇİN)
# ============================================================

def run_issue_driven_discovery(
    issue,
    research_intent,
    documents_index,
    retrieval_fn=None,
    network_allowed=False,
    temporal_mode="neutral",
    query_date=None,
):

    warnings = []

    if not research_intent.get(
        "has_intent"
    ):

        return (
            None,
            warnings,
        )

    query_text = research_intent[
        "query_text"
    ]

    # ========================================================
    # NETWORK SAFETY GATE
    #
    # retrieval_fn açıkça verilmediyse (gerçek retriever
    # kullanılacaksa) network_allowed=True OLMADAN retriever
    # modülü dahi import EDİLMEZ.
    # ========================================================

    if retrieval_fn is None:

        if not network_allowed:

            warnings.append(
                "Network access disabled "
                "(network_allowed=False, --allow-network "
                "verilmedi); issue-driven discovery bu "
                "issue için ÇALIŞTIRILAMADI (coverage "
                "kaydı retrieval_not_run olarak "
                f"üretiliyor): {issue['issue_id']}"
            )

            return (
                build_execution_state_candidate(
                    issue,
                    query_text,
                    "retrieval_not_run",
                ),
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
                "Retriever import edilemedi; issue-driven "
                f"discovery teknik olarak başarısız: "
                f"{error}"
            )

            return (
                build_execution_state_candidate(
                    issue,
                    query_text,
                    "retrieval_failed",
                    failure_reason=
                        "retriever_unavailable",
                ),
                warnings,
            )

    # ========================================================
    # QUERY PARSER (PURE, NETWORK YOK) - HER ZAMAN GERÇEĞİ
    # KULLANILIR.
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
    # RETRIEVAL (FAIL-CLOSED)
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

                temporal_mode=
                    temporal_mode,

                query_date=
                    query_date,
            )
        )

    except Exception as error:

        warnings.append(
            "Retrieval çağrısı teknik olarak başarısız "
            f"oldu (retrieval_failed): {error}"
        )

        return (
            build_execution_state_candidate(
                issue,
                query_text,
                "retrieval_failed",
                failure_reason=
                    "retrieval_call_failed",
            ),
            warnings,
        )

    if not isinstance(
        retrieval_result,
        dict,
    ):

        warnings.append(
            "Retrieval sonucu beklenmeyen formatta "
            f"(retrieval_failed): {issue['issue_id']}"
        )

        return (
            build_execution_state_candidate(
                issue,
                query_text,
                "retrieval_failed",
                failure_reason=
                    "invalid_retrieval_result",
            ),
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

    if (
        failure_reason
        or not results
    ):

        # ----------------------------------------------------
        # Retrieval BAŞARIYLA çalıştı, yalnız sonuç yok -
        # bu no_research_evidence'dır (retrieval_not_run/
        # retrieval_failed İLE KARIŞTIRILMAZ).
        # ----------------------------------------------------

        return (
            build_execution_state_candidate(
                issue,
                query_text,
                "no_research_evidence",
                failure_reason=
                    failure_reason,
            ),
            warnings,
        )

    # ========================================================
    # TOP RESULT -> PROVISION-LEVEL RESOLUTION
    #
    # retriever'ın kendi (belge seviyesi) version kararı TEK
    # BAŞINA yeterli sayılmaz; madde/fikra/bent AYRICA
    # provision_repository + provision_version_policy +
    # provision_policy üzerinden çözülür (aynı fonksiyon,
    # explicit citation path ile PAYLAŞILIR).
    # ========================================================

    top = results[
        0
    ]

    document_id = top.get(
        "document_id"
    )

    madde = top.get(
        "madde"
    )

    fikra = top.get(
        "fikra"
    )

    bent = top.get(
        "bent"
    )

    locator_result = (
        resolve_provision_locator(
            document_id=
                document_id,

            madde=
                madde,

            fikra=
                fikra,

            bent=
                bent,

            temporal_mode=
                temporal_mode,

            query_date=
                query_date,
        )
    )

    citation_display = (
        str(
            document_id
        )
        + (
            f"_m{madde}"
            if madde
            else ""
        )
        + (
            f"_f{fikra}"
            if fikra
            else ""
        )
        + (
            f"_b{bent}"
            if bent
            else ""
        )
    )

    candidate = (
        build_discovery_candidate(
            issue,
            query_text,
            citation_display,
            locator_result,
            documents_index,
        )
    )

    return (
        candidate,
        warnings,
    )


# ============================================================
# RUN FOR ALL ISSUES LACKING EXPLICIT CITATION EVIDENCE
# ============================================================

def run_discovery_for_uncovered_issues(
    issues,
    covered_issue_ids,
    event_index,
    documents_index,
    retrieval_fn=None,
    network_allowed=False,
):

    candidates = []

    warnings = []

    for issue in issues:

        issue_id = issue[
            "issue_id"
        ]

        if issue_id in covered_issue_ids:

            continue

        research_intent = (
            build_research_intent(
                issue,
                event_index,
            )
        )

        (
            candidate,
            candidate_warnings,
        ) = (
            run_issue_driven_discovery(
                issue,
                research_intent,
                documents_index,
                retrieval_fn=
                    retrieval_fn,

                network_allowed=
                    network_allowed,
            )
        )

        warnings.extend(
            candidate_warnings
        )

        if candidate is not None:

            candidates.append(
                candidate
            )

    return (
        candidates,
        warnings,
    )
