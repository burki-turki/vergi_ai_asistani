# ============================================================
# VERGİ AI - DRAFTING DISCOVERY V1
#
# AMAÇ: Deterministik eligibility/allowlist katmanı. Row 4/6-14'ün
# MEVCUT canonical-only loader'larını yeniden kullanır - kendi
# kopyasını üretmez (Prensip 10). Row 15'in tek yeni loader'ı, Row
# 14'ün henüz bir dış loader'ı olmadığı için buradadır (Row 14
# dosyaları DEĞİŞTİRİLMEDİ, yalnız kendi canonical dosyasını okuyan
# BAĞIMSIZ bir fonksiyon eklendi).
# ============================================================

from pathlib import Path

from legal_research_validator import load_canonical_issues
from timeline_validator import load_canonical_fact_index, load_json
from case_document_validator import load_case_documents

from argument_discovery import (
    load_canonical_evidence_optional,
    load_canonical_legal_research_optional,
    load_canonical_case_law_optional,
    load_canonical_timeline_optional,
    load_canonical_deadline_optional,
    CASES_DIR,
)

from risk_strategy_discovery import load_canonical_arguments_optional

from drafting_policy import BLOCK_REASONS


# ============================================================
# YENİ LOADER: risk_strategy.json (Row 14) - CANONICAL-ONLY
# ============================================================

def get_canonical_risk_strategy_path(case_id):

    return CASES_DIR / case_id / "risk_strategy" / "risk_strategy.json"


def load_canonical_risk_strategy_optional(case_id):
    """
    Yalnız canonical risk_strategy.json okunur. Pending dosya BU
    FONKSİYON TARAFINDAN HİÇ OKUNMAZ.
    """

    path = get_canonical_risk_strategy_path(case_id)

    if not path.exists():

        return ({}, {}, {}, path)

    analysis = load_json(path)

    risk_index = {
        r["risk_id"]: r for r in analysis.get("risk_candidates", [])
        if isinstance(r, dict) and r.get("risk_id")
    }

    strategy_index = {
        s["strategy_id"]: s for s in analysis.get("strategy_candidates", [])
        if isinstance(s, dict) and s.get("strategy_id")
    }

    return (risk_index, strategy_index, analysis, path)


# ============================================================
# ACTIVE DOCUMENTS INDEX (Row 3)
# ============================================================

def build_active_documents_index(case_id):

    case_dir = CASES_DIR / case_id

    documents = load_case_documents(case_dir)

    index = {}

    for item in documents:

        data = item["data"]

        if not isinstance(data, dict):
            continue

        if data.get("active") is not True:
            continue

        document_id = data.get("document_id")

        if document_id:

            index[document_id] = data

    return index


# ============================================================
# LEGAL RESEARCH KAPALI ALLOWLIST (Addendum madde 2)
# ============================================================

def legal_research_grounding_class(research):
    """
    Döner: ("direct"|"flagged"|"deny", flag_reason|None).

    Hard-deny önceliklidir; version-unknown etiketi invalid/
    not_applicable sonucunu ASLA aşamaz. agent_suggested her zaman
    deny'dir (grounding değildir - yalnız ayrı bir öneri notu olabilir).
    """

    finding_status = research.get("finding_status")

    if finding_status == "agent_suggested":

        return ("deny", "agent_suggested_not_grounding")

    if finding_status not in ("provision_resolved", "provision_resolved_version_unknown"):

        return ("deny", "unresolved_finding_status")

    formal_result = research.get("formal_result")

    applicability_result = research.get("applicability_result")

    if formal_result != "valid":

        return ("deny", "formal_result_not_valid")

    if applicability_result not in ("applicable", "unknown"):

        return ("deny", "applicability_result_denied")

    if finding_status == "provision_resolved_version_unknown":

        return ("flagged", "version_unknown_and_applicability_uncertain")

    if applicability_result == "unknown":

        return ("flagged", "applicability_not_evaluated")

    return ("flagged", "applicable_temporal_window_only")


# ============================================================
# PER-ISSUE ELIGIBILITY (11 referans alanı)
# ============================================================

def _observation(states_counter):

    return {"observed_states": dict(states_counter), "record_count": sum(states_counter.values())}


def _states_counter(values):

    counter = {}

    for v in values:

        if v is None:
            continue

        counter[v] = counter.get(v, 0) + 1

    return counter


def build_issue_drafting_context(
    issue,
    fact_index,
    active_documents_index,
    evidence_candidate_index,
    evidence_exists,
    research_index,
    case_law_decision_index,
    timeline_event_index,
    deadline_index,
    claim_index,
    counter_index,
    rebuttal_index,
    risk_index,
    strategy_index,
    risk_strategy_exists,
):

    warnings = []

    issue_id = issue["issue_id"]

    # ---- FACTS ----

    eligible_fact_ids = []

    direct_fact_ids = []

    for fact_id in issue.get("source_fact_ids", []):

        record = fact_index.get(fact_id)

        if record is None:

            warnings.append(f"Issue {issue_id}: fact_id '{fact_id}' bulunamadı.")

            continue

        source_document_id = record["source_document_id"]

        if source_document_id not in active_documents_index:

            warnings.append(
                f"Issue {issue_id}: fact_id '{fact_id}' belgesi active değil."
            )

            continue

        eligible_fact_ids.append(fact_id)

        if record["fact"].get("verification_state") == "verified":

            direct_fact_ids.append(fact_id)

    # ---- TIMELINE (hard-deny: disputed, rejected) ----

    eligible_timeline_event_ids = []

    direct_timeline_event_ids = []

    denied_timeline_events = []

    for event_id in issue.get("source_timeline_event_ids", []):

        event = timeline_event_index.get(event_id)

        if event is None:
            continue

        state = event.get("verification_state")

        if state in ("disputed", "rejected"):

            denied_timeline_events.append({"source_id": event_id, "state": state})

            continue

        eligible_timeline_event_ids.append(event_id)

        if state == "verified":

            direct_timeline_event_ids.append(event_id)

    # ---- DEADLINE (hard-deny: not_applicable) ----

    eligible_deadline_ids = []

    direct_deadline_ids = []

    for deadline_id in issue.get("source_deadline_ids", []):

        deadline = deadline_index.get(deadline_id)

        if deadline is None:
            continue

        state = deadline.get("calculation_state")

        if state == "not_applicable":
            continue

        eligible_deadline_ids.append(deadline_id)

        if state == "calculated":

            direct_deadline_ids.append(deadline_id)

    # ---- LEGAL RESEARCH (kapalı allowlist) ----

    issue_research = [
        r for r in research_index.values() if r.get("source_issue_id") == issue_id
    ]

    eligible_legal_research_ids = []

    research_flag_reasons = {}

    agent_suggested_research_ids = []

    for research in issue_research:

        klass, reason = legal_research_grounding_class(research)

        if klass == "deny":

            if research.get("finding_status") == "agent_suggested":

                agent_suggested_research_ids.append(research["research_id"])

            continue

        eligible_legal_research_ids.append(research["research_id"])

        research_flag_reasons[research["research_id"]] = reason

    # ---- CASE LAW (applicability_result null/unknown/needs_review hepsi
    # flagged - HİÇBİRİ hard-deny değildir, HİÇBİRİ "confirmed applicable"
    # değildir - Addendum madde 5) ----

    eligible_case_law_ids = [
        d["decision_id"] for d in case_law_decision_index.values()
        if d.get("source_issue_id") == issue_id
    ]

    # ---- EVIDENCE (opsiyonel - yalnız canonical dosya varsa) ----

    eligible_evidence_candidate_ids = []

    direct_evidence_candidate_ids = []

    if evidence_exists:

        for candidate in evidence_candidate_index.values():

            if candidate.get("source_issue_id") != issue_id:
                continue

            state = candidate.get("review_state")

            if state == "rejected":
                continue

            eligible_evidence_candidate_ids.append(candidate["candidate_id"])

            if state == "confirmed":

                direct_evidence_candidate_ids.append(candidate["candidate_id"])

    # ---- ARGUMENTS (rejected-ata zinciri hard-deny) ----

    def claim_confirmed(claim_id):

        claim = claim_index.get(claim_id)

        return claim is not None and claim.get("claim_review_state") == "confirmed"

    def counter_usable(counter_id):

        counter = counter_index.get(counter_id)

        if counter is None:
            return (False, False)

        if counter.get("counter_review_state") == "rejected":
            return (False, False)

        parent_claim_id = counter.get("source_claim_id")

        parent_claim = claim_index.get(parent_claim_id)

        if parent_claim is not None and parent_claim.get("claim_review_state") == "rejected":
            return (False, False)

        confirmed = (
            counter.get("counter_review_state") == "confirmed" and claim_confirmed(parent_claim_id)
        )

        return (True, confirmed)

    def rebuttal_usable(rebuttal):

        if rebuttal.get("rebuttal_review_state") == "rejected":
            return False

        parent_counter_id = rebuttal.get("source_counterargument_id")

        parent_counter = counter_index.get(parent_counter_id)

        if parent_counter is not None and parent_counter.get("counter_review_state") == "rejected":
            return False

        parent_claim_id = (
            parent_counter.get("source_claim_id") if parent_counter is not None else None
        )

        parent_claim = claim_index.get(parent_claim_id)

        if parent_claim is not None and parent_claim.get("claim_review_state") == "rejected":
            return False

        return True

    eligible_claim_ids = [
        c["claim_id"] for c in claim_index.values()
        if c.get("source_issue_id") == issue_id and c.get("claim_review_state") != "rejected"
    ]

    direct_claim_ids = [c for c in eligible_claim_ids if claim_confirmed(c)]

    eligible_counterargument_ids = []

    direct_counterargument_ids = []

    for counter in counter_index.values():

        if counter.get("source_issue_id") != issue_id:
            continue

        usable, confirmed = counter_usable(counter["counterargument_id"])

        if usable:

            eligible_counterargument_ids.append(counter["counterargument_id"])

            if confirmed:

                direct_counterargument_ids.append(counter["counterargument_id"])

    eligible_rebuttal_ids = [
        r["rebuttal_id"] for r in rebuttal_index.values()
        if r.get("source_issue_id") == issue_id and rebuttal_usable(r)
    ]

    direct_rebuttal_ids = [
        r for r in eligible_rebuttal_ids
        if rebuttal_index[r].get("rebuttal_review_state") == "confirmed"
    ]

    has_confirmed_argument = bool(direct_claim_ids or direct_counterargument_ids or direct_rebuttal_ids)

    # ---- RISK / STRATEGY (opsiyonel, ASLA "direct" değildir - her
    # zaman flagged notla sunulur, Addendum §4/consolidated §7) ----

    eligible_risk_ids = []

    if risk_strategy_exists:

        eligible_risk_ids = [
            r["risk_id"] for r in risk_index.values()
            if r.get("source_issue_id") == issue_id and r.get("risk_review_state") != "rejected"
        ]

    eligible_strategy_ids = []

    if risk_strategy_exists:

        for strategy in strategy_index.values():

            if strategy.get("strategy_review_state") == "dismissed":
                continue

            addressed_issue_ids = {
                r.get("source_issue_id") for r in risk_index.values()
                if r.get("risk_id") in strategy.get("addresses_risk_ids", [])
            }

            if issue_id in addressed_issue_ids:

                eligible_strategy_ids.append(strategy["strategy_id"])

    # ---- ALLOWLIST COUNT ----

    allowlist_count = len(
        set(eligible_fact_ids) | set(eligible_timeline_event_ids) | set(eligible_deadline_ids)
        | set(eligible_legal_research_ids) | set(eligible_case_law_ids)
        | set(eligible_evidence_candidate_ids) | set(eligible_claim_ids)
        | set(eligible_counterargument_ids) | set(eligible_rebuttal_ids)
        | set(eligible_risk_ids) | set(eligible_strategy_ids)
    )

    # ---- UPSTREAM EXECUTION SNAPSHOT (9 anahtar, proof-of-looking) ----

    snapshot = {
        "documents": None,
        "facts": (
            _observation(_states_counter(
                fact_index[f]["fact"].get("verification_state") for f in eligible_fact_ids
            )) if eligible_fact_ids else None
        ),
        "timeline": (
            _observation(_states_counter(
                timeline_event_index.get(e, {}).get("verification_state")
                for e in issue.get("source_timeline_event_ids", [])
            )) if issue.get("source_timeline_event_ids") else None
        ),
        "deadline": (
            _observation(_states_counter(
                deadline_index.get(d, {}).get("calculation_state")
                for d in issue.get("source_deadline_ids", [])
            )) if issue.get("source_deadline_ids") else None
        ),
        "evidence": (
            _observation(_states_counter(
                c.get("review_state") for c in evidence_candidate_index.values()
                if c.get("source_issue_id") == issue_id
            )) if evidence_exists and any(
                c.get("source_issue_id") == issue_id for c in evidence_candidate_index.values()
            ) else None
        ),
        "legal_research": (
            _observation(_states_counter(r.get("finding_status") for r in issue_research))
            if issue_research else None
        ),
        "case_law": (
            _observation(_states_counter(
                d.get("applicability_result") for d in case_law_decision_index.values()
                if d.get("source_issue_id") == issue_id
            )) if eligible_case_law_ids else None
        ),
        "arguments": (
            _observation(_states_counter(
                [claim_index[c].get("claim_review_state") for c in eligible_claim_ids]
                + [counter_index[c].get("counter_review_state") for c in eligible_counterargument_ids]
                + [rebuttal_index[r].get("rebuttal_review_state") for r in eligible_rebuttal_ids]
            )) if (eligible_claim_ids or eligible_counterargument_ids or eligible_rebuttal_ids) else None
        ),
        "risk_strategy": (
            _observation(_states_counter(
                [risk_index[r].get("risk_review_state") for r in eligible_risk_ids]
                + [strategy_index[s].get("strategy_review_state") for s in eligible_strategy_ids]
            )) if (eligible_risk_ids or eligible_strategy_ids) else None
        ),
    }

    has_any_eligible_source = allowlist_count > 0

    menu = {
        "issue_id": issue_id,
        "has_any_eligible_source": has_any_eligible_source,
        "eligible_fact_ids": eligible_fact_ids,
        "direct_fact_ids": direct_fact_ids,
        "eligible_timeline_event_ids": eligible_timeline_event_ids,
        "direct_timeline_event_ids": direct_timeline_event_ids,
        "eligible_deadline_ids": eligible_deadline_ids,
        "direct_deadline_ids": direct_deadline_ids,
        "eligible_legal_research_ids": eligible_legal_research_ids,
        "eligible_case_law_ids": eligible_case_law_ids,
        "eligible_evidence_candidate_ids": eligible_evidence_candidate_ids,
        "direct_evidence_candidate_ids": direct_evidence_candidate_ids,
        "eligible_claim_ids": eligible_claim_ids,
        "direct_claim_ids": direct_claim_ids,
        "eligible_counterargument_ids": eligible_counterargument_ids,
        "direct_counterargument_ids": direct_counterargument_ids,
        "eligible_rebuttal_ids": eligible_rebuttal_ids,
        "direct_rebuttal_ids": direct_rebuttal_ids,
        "has_confirmed_argument": has_confirmed_argument,
        "eligible_risk_ids": eligible_risk_ids,
        "eligible_strategy_ids": eligible_strategy_ids,
        "allowlist_count": allowlist_count,
        "upstream_execution_snapshot": snapshot,
        "denied_timeline_events": denied_timeline_events,
        "agent_suggested_research_ids": agent_suggested_research_ids,
    }

    return (menu, warnings)


def build_allowlists_for_issues(
    issues, fact_index, active_documents_index, evidence_candidate_index, evidence_exists,
    research_index, case_law_decision_index, timeline_event_index, deadline_index,
    claim_index, counter_index, rebuttal_index, risk_index, strategy_index, risk_strategy_exists,
):

    allowlist_by_issue = {}

    warnings = []

    for issue in issues:

        menu, issue_warnings = build_issue_drafting_context(
            issue, fact_index, active_documents_index, evidence_candidate_index, evidence_exists,
            research_index, case_law_decision_index, timeline_event_index, deadline_index,
            claim_index, counter_index, rebuttal_index, risk_index, strategy_index, risk_strategy_exists,
        )

        allowlist_by_issue[issue["issue_id"]] = menu

        warnings.extend(issue_warnings)

    return (allowlist_by_issue, warnings)


# ============================================================
# SELECTION SCOPE (madde A - üç değer, kısmi seçimlere de uygulanır)
# ============================================================

def compute_selection_scope(issue_id, selected_issue_ids):

    if selected_issue_ids is None:

        return "selection_not_provided"

    if issue_id in selected_issue_ids:

        return "selected"

    return "not_selected_by_lawyer"
