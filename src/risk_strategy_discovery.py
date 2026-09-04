# ============================================================
# VERGİ AI - RISK / STRATEGY DISCOVERY V1
#
# AMAÇ: Deterministik eligibility/allowlist katmanı. Agent'a
# SUNULACAK menüyü ve gap-risk üretimi için gereken upstream
# execution-state gözlemlerini (proof-of-looking) üretir.
#
# Bu modül hiçbir LLM/network çağrısı yapmaz. Rows 9-13'ün MEVCUT
# canonical-only loader'larını yeniden kullanır - kendi kopyasını
# üretmez.
# ============================================================

from pathlib import Path

from legal_research_validator import load_canonical_issues
from legal_research_policy import FINDING_STATUS_RESOLVED
from timeline_validator import load_canonical_fact_index
from case_document_validator import load_case_documents

from argument_discovery import (
    load_canonical_evidence_optional,
    load_canonical_legal_research_optional,
    load_canonical_case_law_optional,
    load_canonical_timeline_optional,
    load_canonical_deadline_optional,
)

from argument_discovery import CASES_DIR

from risk_strategy_policy import REF_FIELDS, EMPTY_REF_SET


# ============================================================
# NOT-RUN / ATTEMPTED-NO-RESULT / RESOLVED BUCKET SÖZLÜKLERİ
# (Row 14 madde A "proof-of-looking" - gerçek upstream execution
# alanları üzerinden, dosya varlığı/hash/count YETERLİ DEĞİL)
# ============================================================

LEGAL_RESEARCH_RESOLVED = set(FINDING_STATUS_RESOLVED)

LEGAL_RESEARCH_NOT_RUN = {
    "retrieval_not_run",
    "retrieval_failed",
    "no_research_evidence",
}

LEGAL_RESEARCH_ATTEMPTED_NO_RESULT = {
    "not_found",
    "unparseable_citation",
    "ambiguous",
    "version_conflict",
    "version_unresolved",
    "no_valid_version",
    "mixed_provision_candidates",
    "agent_suggested",
}

CASE_LAW_RESOLVED = {"retrieval_completed"}

CASE_LAW_NOT_RUN = {"retrieval_not_run", "retrieval_failed"}

CASE_LAW_ATTEMPTED_NO_RESULT = {"no_case_law_evidence"}

EVIDENCE_RESOLVED = {"analysis_completed", "analysis_partial"}

EVIDENCE_NOT_RUN = {"analysis_not_run", "blocked_missing_input", "analysis_failed"}

ARGUMENTS_RESOLVED = {"analysis_completed", "analysis_partial"}

ARGUMENTS_NOT_RUN = {"analysis_not_run", "blocked_missing_input", "analysis_failed"}

TIMELINE_DENY_STATES = {"rejected"}

DEADLINE_IDENTIFIED_ELIGIBLE_STATES = {"calculated"}

DEADLINE_GAP_ELIGIBLE_STATES = {
    "blocked_unverified_anchor",
    "blocked_missing_rule",
    "blocked_ambiguous_rule",
    "needs_review",
}

DEADLINE_DENY_STATES = {"not_applicable"}


# ============================================================
# YENİ LOADER: arguments.json (Row 13) - CANONICAL-ONLY
# ============================================================

def get_canonical_arguments_path(case_id):

    return CASES_DIR / case_id / "arguments" / "arguments.json"


def load_canonical_arguments_optional(case_id):
    """
    Yalnız canonical arguments.json okunur. Pending dosya BU
    FONKSİYON TARAFINDAN HİÇ OKUNMAZ.
    """

    from timeline_validator import load_json

    path = get_canonical_arguments_path(case_id)

    if not path.exists():

        return ([], {}, [], {}, [], {}, {}, path)

    analysis = load_json(path)

    coverage = analysis.get("argument_coverage", [])

    claims = analysis.get("argument_claims", [])

    counters = analysis.get("argument_counterarguments", [])

    rebuttals = analysis.get("argument_rebuttals", [])

    claim_index = {
        c["claim_id"]: c for c in claims if isinstance(c, dict) and c.get("claim_id")
    }

    counter_index = {
        c["counterargument_id"]: c
        for c in counters
        if isinstance(c, dict) and c.get("counterargument_id")
    }

    rebuttal_index = {
        r["rebuttal_id"]: r
        for r in rebuttals
        if isinstance(r, dict) and r.get("rebuttal_id")
    }

    coverage_by_issue = {
        c["source_issue_id"]: c
        for c in coverage
        if isinstance(c, dict) and c.get("source_issue_id")
    }

    return (
        claims,
        claim_index,
        counters,
        counter_index,
        rebuttals,
        rebuttal_index,
        coverage_by_issue,
        path,
    )


# ============================================================
# ACTIVE DOCUMENTS INDEX (Row 3, canonical document.json)
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
# PER-ISSUE UPSTREAM SNAPSHOT + ELIGIBLE ID'LER
# ============================================================

def _observation(states_counter):

    return {
        "observed_states": dict(states_counter),
        "record_count": sum(states_counter.values()),
    }


def build_issue_risk_context(
    issue,
    fact_index,
    active_documents_index,
    evidence_candidate_index,
    evidence_coverage_by_issue,
    research_index,
    case_law_decision_index,
    case_law_coverage_by_issue,
    timeline_event_index,
    deadline_index,
    claim_index,
    counter_index,
    rebuttal_index,
    argument_coverage_by_issue,
):
    """
    Tek bir issue için: (a) identified-risk grounding için ELIGIBLE
    ID listeleri, (b) gap-risk üretimi için upstream_execution_snapshot
    ve tetiklenebilir absence_basis kümesi.

    Döner: dict (menu).
    """

    warnings = []

    issue_id = issue["issue_id"]

    # ---- FACTS (yalnız approved + active document) ----

    eligible_fact_ids = []

    unverified_fact_seen = False

    for fact_id in issue.get("source_fact_ids", []):

        record = fact_index.get(fact_id)

        if record is None:

            warnings.append(
                f"Issue {issue_id}: fact_id '{fact_id}' approved "
                "facts.json içinde bulunamadı."
            )

            continue

        source_document_id = record["source_document_id"]

        if source_document_id not in active_documents_index:

            warnings.append(
                f"Issue {issue_id}: fact_id '{fact_id}' belgesi "
                f"'{source_document_id}' active=true canonical "
                "document olarak bulunamadı."
            )

            continue

        eligible_fact_ids.append(fact_id)

        if record["fact"].get("verification_state") != "verified":

            unverified_fact_seen = True

    has_minimum_grounding = bool(eligible_fact_ids)

    # ---- TIMELINE ----

    eligible_timeline_event_ids = []

    for event_id in issue.get("source_timeline_event_ids", []):

        event = timeline_event_index.get(event_id)

        if event is None:
            continue

        if event.get("verification_state") in TIMELINE_DENY_STATES:
            continue

        eligible_timeline_event_ids.append(event_id)

    # ---- DEADLINE (identified-grounding icin yalniz 'calculated') ----

    eligible_deadline_ids = []

    gap_eligible_deadline_ids = []

    for deadline_id in issue.get("source_deadline_ids", []):

        deadline = deadline_index.get(deadline_id)

        if deadline is None:
            continue

        state = deadline.get("calculation_state")

        if state in DEADLINE_DENY_STATES:
            continue

        if state in DEADLINE_IDENTIFIED_ELIGIBLE_STATES:

            eligible_deadline_ids.append(deadline_id)

        elif state in DEADLINE_GAP_ELIGIBLE_STATES:

            gap_eligible_deadline_ids.append(deadline_id)

    # ---- EVIDENCE (issue'ya ait candidate'lar) ----

    issue_evidence_candidates = [
        c for c in evidence_candidate_index.values()
        if c.get("source_issue_id") == issue_id
    ]

    eligible_evidence_candidate_ids = [
        c["candidate_id"] for c in issue_evidence_candidates
        if c.get("review_state") in ("needs_review", "confirmed")
    ]

    confirmed_evidence_count = sum(
        1 for c in issue_evidence_candidates
        if c.get("review_state") == "confirmed"
    )

    evidence_coverage = evidence_coverage_by_issue.get(issue_id)

    evidence_exec_state = (
        evidence_coverage.get("execution_state") if evidence_coverage else None
    )

    # ---- LEGAL RESEARCH (issue'ya ait candidate'lar) ----

    issue_research_candidates = [
        r for r in research_index.values()
        if r.get("source_issue_id") == issue_id
    ]

    eligible_legal_research_ids = [
        r["research_id"] for r in issue_research_candidates
        if r.get("finding_status") in LEGAL_RESEARCH_RESOLVED
    ]

    research_states = [
        r.get("finding_status") for r in issue_research_candidates
    ]

    research_attempted_no_result = any(
        s in LEGAL_RESEARCH_ATTEMPTED_NO_RESULT for s in research_states
    )

    research_all_not_run = bool(research_states) and all(
        s in LEGAL_RESEARCH_NOT_RUN for s in research_states
    )

    research_none_missing = not research_states

    # ---- CASE LAW (issue'ya ait decision'lar + coverage) ----

    issue_case_law_decisions = [
        d for d in case_law_decision_index.values()
        if d.get("source_issue_id") == issue_id
    ]

    eligible_case_law_ids = [
        d["decision_id"] for d in issue_case_law_decisions
    ]

    case_law_coverage = case_law_coverage_by_issue.get(issue_id)

    case_law_exec_state = (
        case_law_coverage.get("execution_state") if case_law_coverage else None
    )

    # ---- ARGUMENTS (Row 13, parent-chain'e duyarlı) ----

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
            counter.get("counter_review_state") == "confirmed"
            and claim_confirmed(parent_claim_id)
        )

        return (True, confirmed)

    issue_claim_ids = [
        c["claim_id"] for c in claim_index.values()
        if c.get("source_issue_id") == issue_id
        and c.get("claim_review_state") != "rejected"
    ]

    issue_counter_ids = []

    confirmed_argument_seen = False

    for counter in counter_index.values():

        if counter.get("source_issue_id") != issue_id:
            continue

        usable, confirmed = counter_usable(counter["counterargument_id"])

        if usable:

            issue_counter_ids.append(counter["counterargument_id"])

        if confirmed:

            confirmed_argument_seen = True

    for claim_id in issue_claim_ids:

        if claim_confirmed(claim_id):

            confirmed_argument_seen = True

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

    issue_rebuttal_ids = [
        r["rebuttal_id"] for r in rebuttal_index.values()
        if r.get("source_issue_id") == issue_id
        and rebuttal_usable(r)
    ]

    argument_coverage = argument_coverage_by_issue.get(issue_id)

    argument_exec_state = (
        argument_coverage.get("execution_state") if argument_coverage else None
    )

    has_any_argument = bool(issue_claim_ids or issue_counter_ids or issue_rebuttal_ids)

    # ---- ALLOWLIST COUNT ----

    allowlist_count = len(
        set(eligible_fact_ids)
        | set(eligible_timeline_event_ids)
        | set(eligible_deadline_ids)
        | set(eligible_evidence_candidate_ids)
        | set(eligible_legal_research_ids)
        | set(eligible_case_law_ids)
        | set(issue_claim_ids)
        | set(issue_counter_ids)
        | set(issue_rebuttal_ids)
    )

    # ---- UPSTREAM EXECUTION SNAPSHOT (proof-of-looking) ----

    def _states_counter(values):

        counter = {}

        for v in values:

            if v is None:
                continue

            counter[v] = counter.get(v, 0) + 1

        return counter

    snapshot = {
        "documents": None,
        "facts": _observation(
            _states_counter(
                fact_index[f]["fact"].get("verification_state")
                for f in eligible_fact_ids
            )
        ) if eligible_fact_ids else None,
        "timeline": _observation(
            _states_counter(
                timeline_event_index.get(e, {}).get("verification_state")
                for e in issue.get("source_timeline_event_ids", [])
            )
        ) if issue.get("source_timeline_event_ids") else None,
        "deadline": _observation(
            _states_counter(
                deadline_index.get(d, {}).get("calculation_state")
                for d in issue.get("source_deadline_ids", [])
            )
        ) if issue.get("source_deadline_ids") else None,
        "evidence": _observation({evidence_exec_state: 1}) if evidence_exec_state else None,
        "legal_research": _observation(_states_counter(research_states)) if research_states else None,
        "case_law": _observation({case_law_exec_state: 1}) if case_law_exec_state else None,
        "arguments": _observation({argument_exec_state: 1}) if argument_exec_state else None,
    }

    # ---- GAP ELIGIBILITY (hangi absence_basis tetiklenebilir) ----

    gap_eligibility = {}

    # no_confirmed_evidence_for_issue
    if evidence_exec_state in EVIDENCE_RESOLVED and issue_evidence_candidates and confirmed_evidence_count == 0:

        gap_eligibility["no_confirmed_evidence_for_issue"] = {
            "source_evidence_candidate_ids": [
                c["candidate_id"] for c in issue_evidence_candidates
            ],
        }

    # no_resolved_legal_authority_for_issue
    if (
        research_attempted_no_result
        and not eligible_legal_research_ids
    ):

        gap_eligibility["no_resolved_legal_authority_for_issue"] = {
            "source_legal_research_ids": [
                r["research_id"] for r in issue_research_candidates
            ],
        }

    # no_grounded_case_law_for_issue
    if case_law_exec_state in CASE_LAW_ATTEMPTED_NO_RESULT:

        gap_eligibility["no_grounded_case_law_for_issue"] = {
            "source_case_law_ids": [],
        }

    # deadline_not_computable / anchor_event_unverified
    for deadline_id in gap_eligible_deadline_ids:

        deadline = deadline_index[deadline_id]

        if deadline.get("calculation_state") == "blocked_unverified_anchor":

            gap_eligibility.setdefault(
                "anchor_event_unverified", {"source_deadline_ids": []},
            )["source_deadline_ids"].append(deadline_id)

            anchor_event_id = deadline.get("anchor_event_id")

            if anchor_event_id:

                gap_eligibility["anchor_event_unverified"].setdefault(
                    "source_timeline_event_ids", []
                ).append(anchor_event_id)

        else:

            gap_eligibility.setdefault(
                "deadline_not_computable", {"source_deadline_ids": []},
            )["source_deadline_ids"].append(deadline_id)

    # no_confirmed_argument_for_issue
    if argument_exec_state in ARGUMENTS_RESOLVED and has_any_argument and not confirmed_argument_seen:

        gap_eligibility["no_confirmed_argument_for_issue"] = {
            "source_claim_ids": list(issue_claim_ids),
            "source_counterargument_ids": list(issue_counter_ids),
            "source_rebuttal_ids": list(issue_rebuttal_ids),
        }

    # ---- BLOCKED-UPSTREAM DETECTION (bilgi amaçlı) ----

    upstream_not_run_aspects = []

    if evidence_exec_state in EVIDENCE_NOT_RUN or evidence_exec_state is None:
        upstream_not_run_aspects.append("evidence")

    if research_all_not_run or research_none_missing:
        upstream_not_run_aspects.append("legal_research")

    if case_law_exec_state in CASE_LAW_NOT_RUN or case_law_exec_state is None:
        upstream_not_run_aspects.append("case_law")

    if argument_exec_state in ARGUMENTS_NOT_RUN or argument_exec_state is None:
        upstream_not_run_aspects.append("arguments")

    menu = {
        "issue_id": issue_id,
        "has_minimum_grounding": has_minimum_grounding,
        "unverified_fact_seen": unverified_fact_seen,
        "eligible_fact_ids": eligible_fact_ids,
        "eligible_timeline_event_ids": eligible_timeline_event_ids,
        "eligible_deadline_ids": eligible_deadline_ids,
        "gap_eligible_deadline_ids": gap_eligible_deadline_ids,
        "eligible_evidence_candidate_ids": eligible_evidence_candidate_ids,
        "eligible_legal_research_ids": eligible_legal_research_ids,
        "eligible_case_law_ids": eligible_case_law_ids,
        "eligible_claim_ids": issue_claim_ids,
        "eligible_counterargument_ids": issue_counter_ids,
        "eligible_rebuttal_ids": issue_rebuttal_ids,
        "allowlist_count": allowlist_count,
        "upstream_execution_snapshot": snapshot,
        "gap_eligibility": gap_eligibility,
        "upstream_not_run_aspects": upstream_not_run_aspects,
    }

    return (menu, warnings)


def build_allowlists_for_issues(
    issues,
    fact_index,
    active_documents_index,
    evidence_candidate_index,
    evidence_coverage_by_issue,
    research_index,
    case_law_decision_index,
    case_law_coverage_by_issue,
    timeline_event_index,
    deadline_index,
    claim_index,
    counter_index,
    rebuttal_index,
    argument_coverage_by_issue,
):

    allowlist_by_issue = {}

    warnings = []

    for issue in issues:

        menu, issue_warnings = build_issue_risk_context(
            issue,
            fact_index,
            active_documents_index,
            evidence_candidate_index,
            evidence_coverage_by_issue,
            research_index,
            case_law_decision_index,
            case_law_coverage_by_issue,
            timeline_event_index,
            deadline_index,
            claim_index,
            counter_index,
            rebuttal_index,
            argument_coverage_by_issue,
        )

        allowlist_by_issue[issue["issue_id"]] = menu

        warnings.extend(issue_warnings)

    return (allowlist_by_issue, warnings)


# ============================================================
# CASE-SCOPE (GLOBAL, 7 SABİT SCOPE) SNAPSHOT
# ============================================================

def build_case_scope_snapshots(
    evidence_exists,
    evidence_coverage_by_issue,
    evidence_candidate_index,
    research_exists,
    research_index,
    case_law_exists,
    case_law_coverage_by_issue,
    case_law_decision_index,
    timeline_exists,
    timeline_event_index,
    deadline_exists,
    deadline_index,
):
    """
    7 sabit case_scope için (input_state, upstream_execution_snapshot,
    depends_on_input_hash_fields) üretir. Risk ÜRETMEZ - yalnız
    muhasebe.
    """

    def obs_from_values(values):

        counter = {}

        for v in values:

            if v is None:
                continue

            counter[v] = counter.get(v, 0) + 1

        return {"observed_states": counter, "record_count": sum(counter.values())}

    scopes = {}

    # documentary_record
    scopes["documentary_record"] = {
        "input_state": "canonical_input_present" if evidence_exists else "no_canonical_input",
        "snapshot_key": "evidence",
        "snapshot": (
            obs_from_values(
                c.get("execution_state") for c in evidence_coverage_by_issue.values()
            )
            if evidence_exists else None
        ),
        "depends_on_input_hash_fields": ["evidence_input_hash"],
    }

    # fact_verification
    scopes["fact_verification"] = {
        "input_state": "canonical_input_present",
        "snapshot_key": "facts",
        "snapshot": None,
        "depends_on_input_hash_fields": ["facts_input_hash"],
    }

    # timeline_verification
    scopes["timeline_verification"] = {
        "input_state": "canonical_input_present" if timeline_exists else "no_canonical_input",
        "snapshot_key": "timeline",
        "snapshot": (
            obs_from_values(
                e.get("verification_state") for e in timeline_event_index.values()
            )
            if timeline_exists else None
        ),
        "depends_on_input_hash_fields": ["timeline_input_hash"],
    }

    # deadline_calculability
    scopes["deadline_calculability"] = {
        "input_state": "canonical_input_present" if deadline_exists else "no_canonical_input",
        "snapshot_key": "deadline",
        "snapshot": (
            obs_from_values(
                d.get("calculation_state") for d in deadline_index.values()
            )
            if deadline_exists else None
        ),
        "depends_on_input_hash_fields": ["deadline_input_hash"],
    }

    # legal_authority_coverage
    scopes["legal_authority_coverage"] = {
        "input_state": "canonical_input_present" if research_exists else "no_canonical_input",
        "snapshot_key": "legal_research",
        "snapshot": (
            obs_from_values(
                r.get("finding_status") for r in research_index.values()
            )
            if research_exists else None
        ),
        "depends_on_input_hash_fields": ["legal_research_input_hash"],
    }

    # case_law_coverage
    scopes["case_law_coverage"] = {
        "input_state": "canonical_input_present" if case_law_exists else "no_canonical_input",
        "snapshot_key": "case_law",
        "snapshot": (
            obs_from_values(
                c.get("execution_state") for c in case_law_coverage_by_issue.values()
            )
            if case_law_exists else None
        ),
        "depends_on_input_hash_fields": ["case_law_input_hash"],
    }

    # procedural_posture
    scopes["procedural_posture"] = {
        "input_state": (
            "canonical_input_present" if (timeline_exists or deadline_exists) else "no_canonical_input"
        ),
        "snapshot_key": None,
        "snapshot": None,
        "depends_on_input_hash_fields": ["timeline_input_hash", "deadline_input_hash"],
    }

    return scopes
