# ============================================================
# VERGİ AI - ORCHESTRATOR ENGINE V1 (Row 17)
#
# Row 1-16'nın canonical çıktılarını OKUYUP (asla YAZMADAN,
# asla PENDING dosya okumadan) tek bir case_view.json'a
# birleştirir. Bu modül:
#   - YENİ hiçbir fact/deadline/mevzuat/olasılık İCAT ETMEZ,
#   - hiçbir upstream kaydı FİLTRELEMEZ/YENİDEN YORUMLAMAZ,
#   - yalnız var olan ID referanslarını issue etrafında
#     YENİDEN GRUPLAR (Prensip 1/2/7).
# ============================================================

import datetime

from orchestrator_discovery import load_all_source_scopes
from orchestrator_policy import (
    ORCHESTRATOR_SOURCE_REGISTRY,
    ORCHESTRATOR_OPTIONAL_SOURCES,
    ARTIFACT_STATE_PRESENT_VALID,
    CASE_VIEW_SCHEMA_VERSION,
    OPEN_ITEM_KIND_REQUIRES_HUMAN_REVIEW,
    OPEN_ITEM_KIND_NEEDS_REVIEW_STATE,
    OPEN_ITEM_KIND_QA_BLOCKED,
    OPEN_ITEM_KIND_QA_FAILED,
    group_by_issue_id,
    group_by_issue_id_membership,
)


def now_iso():

    return datetime.datetime.now().astimezone().isoformat()


V1_SCOPE_NOTES = [
    "v1 kapsam sınırı: risk_strategy.json.case_scope_coverage[] "
    "case_scope_panel'de temsil edilir ama issue_panel'e dahil "
    "değildir (source_issue_id taşımaz, source_case_scope taşır).",
    "v1 kapsam sınırı: drafting.json.draft_source_refs[] (bölüm-içi "
    "tekil atıf kayıtları) case_view'de temsil edilmez; yalnız "
    "section_id seviyesinde özet vardır.",
]


def _list_field(data, field):

    value = data.get(field) if isinstance(data, dict) else None

    return value if isinstance(value, list) else []


def build_case_view(case_id):

    scan_started_at = now_iso()

    sources = load_all_source_scopes(case_id)

    dependency_manifest = [
        {
            "artifact_ref": scope_id,
            "raw_byte_sha256": sources[scope_id]["raw_bytes_sha256"],
            "artifact_state": sources[scope_id]["artifact_state"],
        }
        for scope_id in ORCHESTRATOR_SOURCE_REGISTRY
    ]

    warnings = []
    notes = list(V1_SCOPE_NOTES)

    mandatory_missing = [
        scope_id for scope_id in ORCHESTRATOR_SOURCE_REGISTRY
        if scope_id not in ORCHESTRATOR_OPTIONAL_SOURCES
        and sources[scope_id]["artifact_state"] != ARTIFACT_STATE_PRESENT_VALID
    ]

    for scope_id in mandatory_missing:

        warnings.append(
            f"Zorunlu kaynak '{scope_id}' present_valid değil: "
            f"{sources[scope_id]['artifact_state']}"
        )

    generation_status = "failed" if mandatory_missing else "completed"

    case_data = sources["case"]["data"] or {}
    timeline_data = sources["timeline"]["data"] or {}
    deadline_data = sources["deadline"]["data"] or {}
    issues_data = sources["issues"]["data"] or {}
    research_data = sources["legal_research"]["data"] or {}
    case_law_data = sources["case_law"]["data"] or {}
    evidence_data = sources["evidence"]["data"] or {}
    arguments_data = sources["arguments"]["data"] or {}
    risk_strategy_data = sources["risk_strategy"]["data"] or {}
    drafting_data = sources["drafting"]["data"] or {}
    qa_data = sources["qa"]["data"] or {}

    evidence_source_state = sources["evidence"]["artifact_state"]
    qa_source_state = sources["qa"]["artifact_state"]

    # --------------------------------------------------------
    # case_summary
    # --------------------------------------------------------

    case_summary = {
        "source_state": sources["case"]["artifact_state"],
        "case_id": case_id,
        "title": case_data.get("title"),
        "reference_code": case_data.get("reference_code"),
        "case_type": case_data.get("case_type"),
        "case_status": case_data.get("case_status"),
        "stage": case_data.get("stage"),
    }

    # --------------------------------------------------------
    # timeline_summary
    # --------------------------------------------------------

    timeline_events = _list_field(timeline_data, "events")

    event_dates = sorted(
        e.get("date") for e in timeline_events
        if isinstance(e, dict) and e.get("date")
    )

    timeline_summary = {
        "source_state": sources["timeline"]["artifact_state"],
        "timeline_id": timeline_data.get("timeline_id"),
        "status": timeline_data.get("status"),
        "event_count": (
            len(timeline_events)
            if sources["timeline"]["artifact_state"] == ARTIFACT_STATE_PRESENT_VALID
            else None
        ),
        "earliest_event_date": event_dates[0] if event_dates else None,
        "latest_event_date": event_dates[-1] if event_dates else None,
    }

    # --------------------------------------------------------
    # deadline_panel - saf görüntüleme sıralaması (calculated_deadline
    # artan, null'lar sona) - hukuki bir öncelik İDDİASI DEĞİLDİR.
    # --------------------------------------------------------

    deadlines_raw = [d for d in _list_field(deadline_data, "deadlines") if isinstance(d, dict)]

    deadlines_sorted = sorted(
        deadlines_raw,
        key=lambda d: (d.get("calculated_deadline") is None, d.get("calculated_deadline") or ""),
    )

    deadline_panel = {
        "source_state": sources["deadline"]["artifact_state"],
        "deadline_analysis_id": deadline_data.get("deadline_analysis_id"),
        "deadlines": [
            {
                "deadline_id": d.get("deadline_id"),
                "deadline_type": d.get("deadline_type"),
                "calculation_state": d.get("calculation_state"),
                "calculated_deadline": d.get("calculated_deadline"),
                "expiry_state": d.get("expiry_state"),
                "requires_human_review": bool(d.get("requires_human_review")),
            }
            for d in deadlines_sorted
        ],
    }

    # --------------------------------------------------------
    # Issue-scoped kaynakların gruplanması (HAM veri, filtresiz)
    # --------------------------------------------------------

    issues = [i for i in _list_field(issues_data, "issues") if isinstance(i, dict) and i.get("issue_id")]

    research_candidates = _list_field(research_data, "research_candidates")
    research_by_issue, research_unlinked = group_by_issue_id(research_candidates)

    case_law_coverage = [c for c in _list_field(case_law_data, "case_law_coverage") if isinstance(c, dict)]
    case_law_coverage_by_issue = {
        c["source_issue_id"]: c for c in case_law_coverage if c.get("source_issue_id")
    }
    case_law_decisions = _list_field(case_law_data, "case_law_decisions")
    case_law_decisions_by_issue, case_law_decisions_unlinked = group_by_issue_id(case_law_decisions)

    evidence_coverage = [c for c in _list_field(evidence_data, "evidence_coverage") if isinstance(c, dict)]
    evidence_coverage_by_issue = {
        c["source_issue_id"]: c for c in evidence_coverage if c.get("source_issue_id")
    }
    evidence_candidates = _list_field(evidence_data, "evidence_candidates")
    evidence_candidates_by_issue, evidence_candidates_unlinked = group_by_issue_id(evidence_candidates)

    argument_coverage = [c for c in _list_field(arguments_data, "argument_coverage") if isinstance(c, dict)]
    argument_coverage_by_issue = {
        c["source_issue_id"]: c for c in argument_coverage if c.get("source_issue_id")
    }
    argument_claims = _list_field(arguments_data, "argument_claims")
    claims_by_issue, claims_unlinked = group_by_issue_id(argument_claims)
    argument_counterarguments = _list_field(arguments_data, "argument_counterarguments")
    counters_by_issue, counters_unlinked = group_by_issue_id(argument_counterarguments)
    argument_rebuttals = _list_field(arguments_data, "argument_rebuttals")
    rebuttals_by_issue, rebuttals_unlinked = group_by_issue_id(argument_rebuttals)

    risk_coverage = [c for c in _list_field(risk_strategy_data, "risk_coverage") if isinstance(c, dict)]
    risk_coverage_by_issue = {
        c["source_issue_id"]: c for c in risk_coverage if c.get("source_issue_id")
    }
    risk_candidates = _list_field(risk_strategy_data, "risk_candidates")
    risk_by_issue, risk_unlinked = group_by_issue_id(risk_candidates)

    risk_id_to_issue_id = {
        r["risk_id"]: r.get("source_issue_id")
        for r in risk_candidates if isinstance(r, dict) and r.get("risk_id")
    }

    # strategy_candidates'ın source_issue_id'si YOKTUR - yalnız
    # addresses_risk_ids taşır. Issue'ya, adreslediği risk(ler)in
    # source_issue_id'si ÜZERİNDEN dolaylı bağlanır. Bir strateji
    # birden fazla issue'nun riskini adresliyorsa, o issue'ların
    # HEPSİ altında görünür (drafting section'larındaki çoklu-
    # üyelikle AYNI ilke).

    strategy_candidates = _list_field(risk_strategy_data, "strategy_candidates")
    strategy_by_issue = {}
    strategy_unlinked = []

    for strategy in strategy_candidates:

        if not isinstance(strategy, dict):

            continue

        addressed_issue_ids = []

        for risk_id in (strategy.get("addresses_risk_ids") or []):

            issue_id = risk_id_to_issue_id.get(risk_id)

            if issue_id and issue_id not in addressed_issue_ids:

                addressed_issue_ids.append(issue_id)

        if not addressed_issue_ids:

            strategy_unlinked.append(strategy)
            continue

        for issue_id in addressed_issue_ids:

            strategy_by_issue.setdefault(issue_id, []).append(strategy)

    case_scope_coverage = [c for c in _list_field(risk_strategy_data, "case_scope_coverage") if isinstance(c, dict)]

    draft_coverage = [c for c in _list_field(drafting_data, "draft_coverage") if isinstance(c, dict)]
    draft_coverage_by_issue = {
        c["source_issue_id"]: c for c in draft_coverage if c.get("source_issue_id")
    }
    draft_sections = _list_field(drafting_data, "draft_sections")
    sections_by_issue, sections_unlinked = group_by_issue_id_membership(
        draft_sections, issue_field="source_issue_ids",
    )

    # ----------------------------------------------------------------
    # QA -> ISSUE LİNKAJ POLİTİKASI (kullanıcı kararı, 2026-09-04):
    #   - Bir qa_check_result, YALNIZ açık ve deterministik bir bağlantı
    #     (related_issue_id alanı dolu) varsa issue_panel'e eklenir.
    #   - Bağlantı kurulamıyorsa (related_issue_id boş/None) kayıt
    #     kaybolmaz - qa_health_panel'de (toplam sayaç) ve gerektiğinde
    #     scope-seviyeli open_items_panel'de GÖRÜNMEYE devam eder.
    #   - Metinden veya isim/kelime benzerliğinden ("bu check muhtemelen
    #     şu issue'yla ilgili görünüyor" gibi) issue ilişkisi ASLA
    #     tahmin/inference EDİLMEZ (Prensip 1/7 - agent/motor yeni bir
    #     bağlantı İCAT ETMEZ).
    #   - Row 16'nın qa_engine.py'si şu an related_issue_id'yi HİÇBİR
    #     check için doldurmuyor (bkz. Row 17 checkpoint notu) - bu
    #     yüzden bu grouping bugün için 0 eşleşme üretir; bu bir Row 17
    #     hatası DEĞİLDİR, upstream'in mevcut (kasıtlı, şimdilik
    #     yamanmayan) durumunun dürüst yansımasıdır.
    #   - İleride gerçek ihtiyaç doğar ve Row 16 için ayrı bir bakım
    #     yaması değerlendirilirse, olası alan TEKİL related_issue_id
    #     DEĞİL, ÇOĞUL related_issue_ids[] olmalıdır (bir check birden
    #     fazla issue'yu ilgilendirebilir) - bu durumda burada
    #     group_by_issue_id yerine group_by_issue_id_membership
    #     kullanılması gerekecektir.
    # ----------------------------------------------------------------

    qa_check_results = _list_field(qa_data, "qa_check_results")
    qa_by_issue, qa_unlinked = group_by_issue_id(qa_check_results, issue_field="related_issue_id")

    if research_unlinked:
        warnings.append(f"{len(research_unlinked)} research_candidate source_issue_id olmadan (unlinked, atlanmadı).")
    if case_law_decisions_unlinked:
        warnings.append(f"{len(case_law_decisions_unlinked)} case_law_decision source_issue_id olmadan (unlinked, atlanmadı).")
    if evidence_candidates_unlinked:
        warnings.append(f"{len(evidence_candidates_unlinked)} evidence_candidate source_issue_id olmadan (unlinked, atlanmadı).")
    if claims_unlinked or counters_unlinked or rebuttals_unlinked:
        warnings.append(
            f"{len(claims_unlinked)} claim / {len(counters_unlinked)} counterargument / "
            f"{len(rebuttals_unlinked)} rebuttal source_issue_id olmadan (unlinked, atlanmadı)."
        )
    if risk_unlinked:
        warnings.append(f"{len(risk_unlinked)} risk_candidate source_issue_id olmadan (unlinked, atlanmadı).")
    if strategy_unlinked:
        warnings.append(f"{len(strategy_unlinked)} strategy_candidate hiçbir çözülebilir issue'ya bağlanamadı (addresses_risk_ids boş veya bilinmeyen risk_id).")
    if sections_unlinked:
        warnings.append(f"{len(sections_unlinked)} draft_section source_issue_ids olmadan/boş (unlinked, atlanmadı).")
    if qa_unlinked:
        warnings.append(f"{len(qa_unlinked)} qa_check_result related_issue_id olmadan (scope-seviyeli check'ler için normal).")

    # --------------------------------------------------------
    # issue_panel
    # --------------------------------------------------------

    issue_panel = []

    for issue in issues:

        issue_id = issue["issue_id"]

        cl_cov = case_law_coverage_by_issue.get(issue_id)
        ev_cov = evidence_coverage_by_issue.get(issue_id)
        arg_cov = argument_coverage_by_issue.get(issue_id)
        risk_cov = risk_coverage_by_issue.get(issue_id)
        draft_cov = draft_coverage_by_issue.get(issue_id)

        ev_candidates_for_issue = [c for c in evidence_candidates_by_issue.get(issue_id, []) if isinstance(c, dict)]

        supports_ids = [
            c["candidate_id"] for c in ev_candidates_for_issue
            if c.get("relationship_candidate") == "supports" and c.get("candidate_id")
        ]
        contradicts_ids = [
            c["candidate_id"] for c in ev_candidates_for_issue
            if c.get("relationship_candidate") == "contradicts" and c.get("candidate_id")
        ]

        issue_panel.append({
            "issue_id": issue_id,
            "issue_type": issue.get("issue_type"),
            "title": issue.get("title"),
            "status": issue.get("status"),
            "requires_human_review": bool(issue.get("requires_human_review")),
            "source_fact_ids": list(issue.get("source_fact_ids") or []),
            "source_timeline_event_ids": list(issue.get("source_timeline_event_ids") or []),
            "source_deadline_ids": list(issue.get("source_deadline_ids") or []),
            "legal_research_ids": [
                r["research_id"] for r in research_by_issue.get(issue_id, [])
                if isinstance(r, dict) and r.get("research_id")
            ],
            "case_law": {
                "coverage_id": cl_cov.get("coverage_id") if cl_cov else None,
                "execution_state": cl_cov.get("execution_state") if cl_cov else None,
                "decision_ids": [
                    d["decision_id"] for d in case_law_decisions_by_issue.get(issue_id, [])
                    if isinstance(d, dict) and d.get("decision_id")
                ],
            },
            "evidence": {
                "source_state": evidence_source_state,
                "coverage_id": ev_cov.get("coverage_id") if ev_cov else None,
                "execution_state": ev_cov.get("execution_state") if ev_cov else None,
                "supports_candidate_ids": supports_ids,
                "contradicts_candidate_ids": contradicts_ids,
            },
            "arguments": {
                "coverage_id": arg_cov.get("coverage_id") if arg_cov else None,
                "execution_state": arg_cov.get("execution_state") if arg_cov else None,
                "claim_ids": [
                    c["claim_id"] for c in claims_by_issue.get(issue_id, [])
                    if isinstance(c, dict) and c.get("claim_id")
                ],
                "counterargument_ids": [
                    c["counterargument_id"] for c in counters_by_issue.get(issue_id, [])
                    if isinstance(c, dict) and c.get("counterargument_id")
                ],
                "rebuttal_ids": [
                    c["rebuttal_id"] for c in rebuttals_by_issue.get(issue_id, [])
                    if isinstance(c, dict) and c.get("rebuttal_id")
                ],
            },
            "risk_strategy": {
                "coverage_id": risk_cov.get("coverage_id") if risk_cov else None,
                "risk_execution_state": risk_cov.get("risk_execution_state") if risk_cov else None,
                "strategy_execution_state": risk_cov.get("strategy_execution_state") if risk_cov else None,
                "risk_ids": [
                    r["risk_id"] for r in risk_by_issue.get(issue_id, [])
                    if isinstance(r, dict) and r.get("risk_id")
                ],
                "strategy_ids": [
                    s["strategy_id"] for s in strategy_by_issue.get(issue_id, [])
                    if isinstance(s, dict) and s.get("strategy_id")
                ],
            },
            "drafting": {
                "coverage_id": draft_cov.get("coverage_id") if draft_cov else None,
                "execution_state": draft_cov.get("execution_state") if draft_cov else None,
                "section_ids": [
                    s["section_id"] for s in sections_by_issue.get(issue_id, [])
                    if isinstance(s, dict) and s.get("section_id")
                ],
            },
            "qa_related_check_result_ids": [
                c["check_result_id"] for c in qa_by_issue.get(issue_id, [])
                if isinstance(c, dict) and c.get("check_result_id")
            ],
        })

    # --------------------------------------------------------
    # evidence_panel (case-geneli özet)
    # --------------------------------------------------------

    if evidence_source_state == ARTIFACT_STATE_PRESENT_VALID:

        evidence_panel = {
            "source_state": evidence_source_state,
            "reason": None,
            "evidence_analysis_id": evidence_data.get("evidence_analysis_id"),
            "total_candidates": len(evidence_candidates),
            "supports_count": sum(
                1 for c in evidence_candidates
                if isinstance(c, dict) and c.get("relationship_candidate") == "supports"
            ),
            "contradicts_count": sum(
                1 for c in evidence_candidates
                if isinstance(c, dict) and c.get("relationship_candidate") == "contradicts"
            ),
            "needs_review_count": sum(
                1 for c in evidence_candidates
                if isinstance(c, dict) and c.get("review_state") == "needs_review"
            ),
        }

    else:

        reason = (
            "canonical evidence.json henüz oluşturulmadı (Row 12 offline baseline, "
            "yalnız pending mevcut)" if evidence_source_state == "absent"
            else f"evidence.json {evidence_source_state}"
        )

        evidence_panel = {
            "source_state": evidence_source_state, "reason": reason,
            "evidence_analysis_id": None, "total_candidates": 0,
            "supports_count": 0, "contradicts_count": 0, "needs_review_count": 0,
        }

    # --------------------------------------------------------
    # case_scope_panel
    # --------------------------------------------------------

    case_scope_panel = {
        "source_state": sources["risk_strategy"]["artifact_state"],
        "entries": [
            {
                "coverage_id": c.get("coverage_id"),
                "source_case_scope": c.get("source_case_scope"),
                "input_state": c.get("input_state"),
                "execution_state": c.get("execution_state"),
            }
            for c in case_scope_coverage
        ],
    }

    # --------------------------------------------------------
    # open_items_panel - YALNIZ var olan alanların yeniden
    # listelenmesi, YENİ bir sınıflandırma İCAT EDİLMEZ.
    # --------------------------------------------------------

    open_items = []

    def add_open_item(kind, scope, record_id, issue_id, reason_code):

        open_items.append({
            "item_kind": kind, "source_scope": scope,
            "source_record_id": record_id, "source_issue_id": issue_id,
            "reason_code": reason_code,
        })

    for issue in issues:

        if issue.get("requires_human_review"):

            add_open_item(
                OPEN_ITEM_KIND_REQUIRES_HUMAN_REVIEW, "issues",
                issue.get("issue_id"), issue.get("issue_id"), issue.get("status"),
            )

    for r in research_candidates:

        if isinstance(r, dict) and r.get("requires_human_review"):

            add_open_item(
                OPEN_ITEM_KIND_REQUIRES_HUMAN_REVIEW, "legal_research",
                r.get("research_id"), r.get("source_issue_id"), r.get("status"),
            )

    for c in case_law_coverage + case_law_decisions:

        if isinstance(c, dict) and c.get("requires_human_review"):

            add_open_item(
                OPEN_ITEM_KIND_REQUIRES_HUMAN_REVIEW, "case_law",
                c.get("coverage_id") or c.get("decision_id"),
                c.get("source_issue_id"), c.get("status"),
            )

    if evidence_source_state == ARTIFACT_STATE_PRESENT_VALID:

        for c in evidence_candidates:

            if isinstance(c, dict) and c.get("review_state") == "needs_review":

                add_open_item(
                    OPEN_ITEM_KIND_NEEDS_REVIEW_STATE, "evidence",
                    c.get("candidate_id"), c.get("source_issue_id"), c.get("reason_code"),
                )

    for c in argument_claims:

        if isinstance(c, dict) and c.get("claim_review_state") == "needs_review":

            add_open_item(
                OPEN_ITEM_KIND_NEEDS_REVIEW_STATE, "arguments",
                c.get("claim_id"), c.get("source_issue_id"), c.get("reason_code"),
            )

    for c in argument_counterarguments:

        if isinstance(c, dict) and c.get("counter_review_state") == "needs_review":

            add_open_item(
                OPEN_ITEM_KIND_NEEDS_REVIEW_STATE, "arguments",
                c.get("counterargument_id"), c.get("source_issue_id"), c.get("reason_code"),
            )

    for c in argument_rebuttals:

        if isinstance(c, dict) and c.get("rebuttal_review_state") == "needs_review":

            add_open_item(
                OPEN_ITEM_KIND_NEEDS_REVIEW_STATE, "arguments",
                c.get("rebuttal_id"), c.get("source_issue_id"), c.get("reason_code"),
            )

    for c in risk_candidates:

        if isinstance(c, dict) and c.get("risk_review_state") == "needs_review":

            add_open_item(
                OPEN_ITEM_KIND_NEEDS_REVIEW_STATE, "risk_strategy",
                c.get("risk_id"), c.get("source_issue_id"), c.get("reason_code"),
            )

    for s in strategy_candidates:

        if isinstance(s, dict) and s.get("strategy_review_state") == "needs_review":

            addressed = [
                risk_id_to_issue_id.get(rid) for rid in (s.get("addresses_risk_ids") or [])
            ]
            issue_id_for_item = next((i for i in addressed if i), None)

            add_open_item(
                OPEN_ITEM_KIND_NEEDS_REVIEW_STATE, "risk_strategy",
                s.get("strategy_id"), issue_id_for_item, s.get("reason_code"),
            )

    for s in draft_sections:

        if isinstance(s, dict) and s.get("section_review_state") == "needs_review":

            issue_ids = s.get("source_issue_ids") or []

            add_open_item(
                OPEN_ITEM_KIND_NEEDS_REVIEW_STATE, "drafting",
                s.get("section_id"), issue_ids[0] if issue_ids else None, None,
            )

    if qa_source_state == ARTIFACT_STATE_PRESENT_VALID:

        for c in qa_check_results:

            if not isinstance(c, dict):

                continue

            if c.get("qa_result") == "blocked":

                add_open_item(
                    OPEN_ITEM_KIND_QA_BLOCKED, "qa", c.get("check_result_id"),
                    c.get("related_issue_id"), c.get("reason_code"),
                )

            elif c.get("qa_result") == "failed":

                add_open_item(
                    OPEN_ITEM_KIND_QA_FAILED, "qa", c.get("check_result_id"),
                    c.get("related_issue_id"), c.get("reason_code"),
                )

        for s in _list_field(qa_data, "qa_agent_suggestions"):

            if isinstance(s, dict) and s.get("suggestion_review_state") == "needs_review":

                add_open_item(
                    OPEN_ITEM_KIND_NEEDS_REVIEW_STATE, "qa",
                    s.get("suggestion_id"), s.get("related_issue_id"), None,
                )

    # --------------------------------------------------------
    # qa_health_panel - qa.json'un KENDİ dağılımına GÜVENİLMEZ,
    # qa_check_results'tan BAĞIMSIZCA yeniden sayılır (Row 16
    # qa_validator'ın "kendi kendine yeniden hesapla" ilkesiyle
    # AYNI disiplin).
    # --------------------------------------------------------

    if qa_source_state == ARTIFACT_STATE_PRESENT_VALID:

        totals_by_result = {}
        totals_by_scope = {}

        for c in qa_check_results:

            if not isinstance(c, dict):

                continue

            result = c.get("qa_result")
            scope = c.get("scope_id")

            totals_by_result[result] = totals_by_result.get(result, 0) + 1

            if scope:

                totals_by_scope.setdefault(scope, {})
                totals_by_scope[scope][result] = totals_by_scope[scope].get(result, 0) + 1

        qa_health_panel = {
            "source_state": qa_source_state,
            "qa_analysis_id": qa_data.get("qa_analysis_id"),
            "qa_generation_status": qa_data.get("qa_generation_status"),
            "qa_agent_execution_status": qa_data.get("qa_agent_execution_status"),
            "totals_by_result": totals_by_result,
            "totals_by_scope": totals_by_scope,
        }

    else:

        qa_health_panel = {
            "source_state": qa_source_state,
            "qa_analysis_id": None, "qa_generation_status": None,
            "qa_agent_execution_status": None,
            "totals_by_result": {}, "totals_by_scope": {},
        }

    scan_completed_at = now_iso()

    return {
        "schema_version": CASE_VIEW_SCHEMA_VERSION,
        "case_view_id": f"case_view_{case_id}_v1",
        "case_id": case_id,
        "generation_status": generation_status,
        "generated_at": scan_completed_at,
        "analysis_metadata": {
            "dependency_manifest": dependency_manifest,
            "scan_started_at": scan_started_at,
            "scan_completed_at": scan_completed_at,
        },
        "case_summary": case_summary,
        "timeline_summary": timeline_summary,
        "deadline_panel": deadline_panel,
        "issue_panel": issue_panel,
        "evidence_panel": evidence_panel,
        "case_scope_panel": case_scope_panel,
        "open_items_panel": open_items,
        "qa_health_panel": qa_health_panel,
        "warnings": warnings,
        "notes": notes,
    }


# ============================================================
# SELF TEST
# ============================================================

def run_self_test():

    import json
    from pathlib import Path
    from jsonschema import Draft202012Validator, FormatChecker

    print()
    print("======================================")
    print(" VERGİ AI - ORCHESTRATOR ENGINE V1 (SELF-TEST)")
    print("======================================")

    case_id = "case_0001"

    base_dir = Path(__file__).resolve().parent.parent
    schema = json.loads((base_dir / "data" / "case_view.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # T01: case_0001 üzerinde gerçek build - şema geçerli olmalı
    view = build_case_view(case_id)

    errors = list(validator.iter_errors(view))

    assert not errors, "Schema errors:\n" + "\n".join(
        f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors
    )

    print("T01 case_0001 gerçek build şema-geçerli:", "PASS")

    # T02: case_0001'in tüm zorunlu kaynakları present_valid olduğu
    # için generation_status='completed' olmalı (evidence hariç).
    assert view["generation_status"] == "completed"

    print("T02 Tüm zorunlu kaynaklar mevcutken generation_status='completed':", "PASS")

    # T03: issue_panel uzunluğu gerçek issues.json ile birebir
    # eşleşmeli (filtre/atlama YOK).
    issues_path = base_dir / "data" / "cases" / case_id / "issues" / "issues.json"
    real_issues = json.loads(issues_path.read_text(encoding="utf-8"))["issues"]

    assert len(view["issue_panel"]) == len(real_issues)

    print(f"T03 issue_panel uzunluğu gerçek issues.json ile eşleşiyor ({len(real_issues)}):", "PASS")

    # T04: evidence.json henüz canonical değil (Row 12) -
    # evidence_panel bunu 'absent' + neden ile doğru yansıtmalı,
    # hata FIRLATMAMALI.
    evidence_path = base_dir / "data" / "cases" / case_id / "evidence" / "evidence.json"

    assert not evidence_path.exists(), "Test varsayımı geçersiz: canonical evidence.json artık var."
    assert view["evidence_panel"]["source_state"] == "absent"
    assert view["evidence_panel"]["reason"] is not None

    print("T04 Eksik canonical evidence.json 'absent' + neden ile doğru yansıtıldı:", "PASS")

    # T05: qa_health_panel, qa.json'un GERÇEK check_result sayısıyla
    # (bağımsızca yeniden sayılmış) birebir eşleşmeli.
    qa_path = base_dir / "data" / "cases" / case_id / "qa" / "qa.json"
    real_qa = json.loads(qa_path.read_text(encoding="utf-8"))
    real_total = len(real_qa["qa_check_results"])

    view_total = sum(view["qa_health_panel"]["totals_by_result"].values())

    assert view_total == real_total == 83

    print(f"T05 qa_health_panel toplamı gerçek qa.json ile eşleşiyor ({real_total}):", "PASS")

    # T06: her issue_panel_entry.qa_related_check_result_ids GERÇEKTEN
    # qa.json'da var olan, related_issue_id'si o issue'ya eşit
    # check_result_id'ler olmalı (uydurma/yanlış eşleşme YOK).
    real_check_by_id = {c["check_result_id"]: c for c in real_qa["qa_check_results"]}

    checked = 0

    for entry in view["issue_panel"]:

        for check_result_id in entry["qa_related_check_result_ids"]:

            assert check_result_id in real_check_by_id, f"Uydurma check_result_id: {check_result_id}"
            assert real_check_by_id[check_result_id]["related_issue_id"] == entry["issue_id"]

            checked += 1

    print(f"T06 {checked} qa_related_check_result_id referansı gerçek qa.json'a karşı doğrulandı:", "PASS")

    # T07: strategy_candidates'ın issue'ya addresses_risk_ids ÜZERİNDEN
    # doğru bağlandığını kontrol et (en az bir risk/strategy varsa).
    risk_strategy_path = base_dir / "data" / "cases" / case_id / "risk_strategy" / "risk_strategy.json"
    real_rs = json.loads(risk_strategy_path.read_text(encoding="utf-8"))

    real_risk_to_issue = {
        r["risk_id"]: r.get("source_issue_id")
        for r in real_rs.get("risk_candidates", []) if isinstance(r, dict) and r.get("risk_id")
    }

    for entry in view["issue_panel"]:

        for strategy_id in entry["risk_strategy"]["strategy_ids"]:

            real_strategy = next(
                s for s in real_rs.get("strategy_candidates", [])
                if isinstance(s, dict) and s.get("strategy_id") == strategy_id
            )

            addressed_issues = {
                real_risk_to_issue.get(rid) for rid in (real_strategy.get("addresses_risk_ids") or [])
            }

            assert entry["issue_id"] in addressed_issues, (
                f"strategy {strategy_id} yanlış issue'ya ({entry['issue_id']}) bağlandı, "
                f"gerçek addressed_issues={addressed_issues}"
            )

    print("T07 strategy->issue (addresses_risk_ids üzerinden dolaylı) bağlantısı doğrulandı:", "PASS")

    # T08: draft_sections çoklu-üyelik - bir section birden fazla
    # issue_panel_entry altında görünüyorsa, bu section'ın GERÇEKTEN
    # source_issue_ids'inde o issue'ların HEPSİ olmalı.
    drafting_path = base_dir / "data" / "cases" / case_id / "drafting" / "drafting.json"
    real_drafting = json.loads(drafting_path.read_text(encoding="utf-8"))
    real_section_by_id = {
        s["section_id"]: s for s in real_drafting.get("draft_sections", [])
        if isinstance(s, dict) and s.get("section_id")
    }

    section_to_issue_entries = {}

    for entry in view["issue_panel"]:

        for section_id in entry["drafting"]["section_ids"]:

            section_to_issue_entries.setdefault(section_id, []).append(entry["issue_id"])

    for section_id, issue_ids_seen in section_to_issue_entries.items():

        real_section = real_section_by_id[section_id]

        assert set(issue_ids_seen) <= set(real_section.get("source_issue_ids") or []), (
            f"section {section_id} view'da olmayan bir issue'ya bağlanmış."
        )

    print("T08 draft_section çoklu-üyelik referansları gerçek source_issue_ids ile tutarlı:", "PASS")

    # T09: build_case_view HİÇBİR dosya YAZMADI (read-only garanti) -
    # data/cases/case_0001 ağacının dosya sayısı/hash'i değişmedi.

    def snapshot(case_dir):

        return {
            str(p.relative_to(case_dir)): p.stat().st_mtime_ns
            for p in sorted(case_dir.rglob("*")) if p.is_file()
        }

    case_dir = base_dir / "data" / "cases" / case_id

    before = snapshot(case_dir)
    build_case_view(case_id)
    after = snapshot(case_dir)

    assert before == after, "build_case_view case_0001 ağacını DEĞİŞTİRDİ (read-only ihlali)."

    print("T09 build_case_view read-only (case_0001 ağacına hiç dokunmadı):", "PASS")

    # T10: mandatory kaynak eksik senaryosu - var olmayan bir case_id
    # generation_status='failed' vermeli ve şema-geçerli, boş-ama-
    # tutarlı bir case_view üretmeli (hata FIRLATMAMALI).
    fake_view = build_case_view("case_9999_does_not_exist")

    fake_errors = list(validator.iter_errors(fake_view))

    assert not fake_errors, "Eksik case_id senaryosunda şema hatası:\n" + "\n".join(
        f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in fake_errors
    )
    assert fake_view["generation_status"] == "failed"
    assert fake_view["issue_panel"] == []
    assert fake_view["case_summary"]["source_state"] == "absent"

    print("T10 Var olmayan case_id için şema-geçerli 'failed' case_view üretildi (hata fırlatmadı):", "PASS")

    print()
    print("======================================")
    print(" ORCHESTRATOR ENGINE V1: 10/10 SELF-TEST PASS")
    print("======================================")


if __name__ == "__main__":

    import sys

    if "--self-test" in sys.argv:

        run_self_test()

    else:

        print("orchestrator_engine.py - bkz. --self-test.")
