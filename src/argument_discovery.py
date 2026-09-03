# ============================================================
# VERGİ AI - ARGUMENT DISCOVERY V1
#
# AMAÇ
# ----
#
# Canonical issue + approved canonical fact (Row 6) + (varsa,
# yalnız CANONICAL - asla pending) Row 12 evidence + Row 10
# legal research + Row 11 case law + Row 7 timeline + Row 8
# deadline üzerinden, HER issue için deterministik bir "eligible
# reference menu" (allowlist) üretmek.
#
# Bu allowlist kombinatoryal bir üçlü DEĞİLDİR (Row 12'den
# farklı): claim/counterargument/rebuttal keyfi bir alt-küme
# referans birleşimi olabileceğinden, deterministik katman
# yalnız "bu issue'da hangi ID'ler grounding için UYGUNDUR"
# menüsünü hazırlar; Agent bu menüden bir alt-küme SEÇER.
#
#
# UPSTREAM ELIGIBILITY (mandatory/optional/prohibited)
# ------------------------------------------------------
#
# - facts:          MANDATORY, yalnız approved canonical
#                    facts.json (Row 6).
# - issues:         MANDATORY, canonical issues.json (Row 9).
# - evidence:       OPTIONAL, YALNIZ canonical evidence.json
#                    (Row 12) - PENDING DOSYA ASLA OKUNMAZ.
#                    rejected candidate'lar eligible listeye
#                    hiç girmez (hard exclude).
# - legal research: OPTIONAL, yalnız finding_status
#                    FINDING_STATUS_RESOLVED ailesinde olan
#                    research candidate'lar (Row 10).
# - case law:       OPTIONAL, yalnız case_law_decisions[]
#                    (Row 11) - coverage/suggestion GROUNDING
#                    OLAMAZ.
# - timeline:       OPTIONAL, yalnız issue'nun KENDİ
#                    source_timeline_event_ids'i ile sınırlı
#                    (Row 9 zaten bu linkaji taşır).
# - deadline:       OPTIONAL, yalnız issue'nun KENDİ
#                    source_deadline_ids'i ile sınırlı.
# ============================================================


from pathlib import Path


# ============================================================
# VERSION
# ============================================================

ARGUMENT_DISCOVERY_VERSION = "1"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

CASES_DIR = DATA_DIR / "cases"


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path):

    import json

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


# ============================================================
# OPTIONAL UPSTREAM READERS (CANONICAL-ONLY, ASLA PENDING)
# ============================================================

def get_canonical_evidence_path(case_id):

    return CASES_DIR / case_id / "evidence" / "evidence.json"


def load_canonical_evidence_optional(case_id):
    """
    Yalnız canonical evidence.json okunur. Pending dosya
    (evidence_<case_id>_v1.json.pending) BU FONKSİYON
    TARAFINDAN HİÇ OKUNMAZ - dosya adı literal olarak
    "evidence.json" DEĞİLSE (yani pending suffix'i taşıyorsa)
    load edilmez.
    """

    path = get_canonical_evidence_path(case_id)

    if not path.exists():

        return ([], {}, path)

    analysis = load_json(path)

    candidates = analysis.get("evidence_candidates", [])

    index = {
        candidate["candidate_id"]: candidate
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("candidate_id")
    }

    return (candidates, index, path)


def get_canonical_case_law_path(case_id):

    return CASES_DIR / case_id / "case_law" / "case_law.json"


def load_canonical_case_law_optional(case_id):

    path = get_canonical_case_law_path(case_id)

    if not path.exists():

        return ([], {}, path)

    analysis = load_json(path)

    decisions = analysis.get("case_law_decisions", [])

    index = {
        decision["decision_id"]: decision
        for decision in decisions
        if isinstance(decision, dict) and decision.get("decision_id")
    }

    return (decisions, index, path)


def load_canonical_timeline_optional(case_id):

    from deadline_validator import load_canonical_timeline

    path = CASES_DIR / case_id / "timeline" / "timeline.json"

    if not path.exists():

        return ({}, path)

    context = load_canonical_timeline(case_id)

    return (context["events"], path)


def load_canonical_deadline_optional(case_id):

    from issue_spotting_validator import (
        load_canonical_deadline_optional as _load,
    )

    deadlines, deadline_ids, path = _load(case_id)

    return (deadlines, deadline_ids, path)


def load_canonical_legal_research_optional(case_id):

    from case_law_validator import load_canonical_research

    researches, research_index, path = load_canonical_research(case_id)

    return (researches, research_index, path)


# ============================================================
# ELIGIBLE REFERENCE MENU (PER ISSUE)
# ============================================================

def build_issue_allowlist(
    issue,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
    timeline_event_index,
    deadline_ids,
):

    from legal_research_policy import FINDING_STATUS_RESOLVED

    issue_id = issue["issue_id"]

    warnings = []

    # --------------------------------------------------------
    # FACTS - yalnız issue'nun kendi source_fact_ids'i, yalnız
    # approved (canonical) facts.json'da bulunanlar.
    # --------------------------------------------------------

    eligible_fact_ids = []

    for fact_id in issue.get("source_fact_ids", []):

        if fact_id in fact_index:

            eligible_fact_ids.append(fact_id)

        else:

            warnings.append(
                f"Issue {issue_id}: fact_id '{fact_id}' "
                "approved facts.json içinde bulunamadı; "
                "allowlist'e alınmadı."
            )

    # --------------------------------------------------------
    # EVIDENCE - yalnız bu issue'ya ait, rejected OLMAYAN
    # canonical evidence candidate'lar.
    # --------------------------------------------------------

    eligible_evidence_candidate_ids = [
        candidate_id
        for candidate_id, candidate in evidence_candidate_index.items()
        if candidate.get("source_issue_id") == issue_id
        and candidate.get("review_state") != "rejected"
    ]

    # --------------------------------------------------------
    # LEGAL RESEARCH - yalnız bu issue'ya ait, finding_status
    # RESOLVED ailesinde olan research candidate'lar.
    # --------------------------------------------------------

    eligible_legal_research_ids = [
        research_id
        for research_id, research in research_index.items()
        if research.get("source_issue_id") == issue_id
        and research.get("finding_status") in FINDING_STATUS_RESOLVED
    ]

    # --------------------------------------------------------
    # CASE LAW - yalnız bu issue'ya ait grounded decision'lar.
    # --------------------------------------------------------

    eligible_case_law_ids = [
        decision_id
        for decision_id, decision in case_law_decision_index.items()
        if decision.get("source_issue_id") == issue_id
    ]

    # --------------------------------------------------------
    # TIMELINE - yalnız issue'nun KENDİ linkajı, yalnız
    # canonical timeline'da hâlâ mevcut olanlar.
    # --------------------------------------------------------

    eligible_timeline_event_ids = [
        event_id
        for event_id in issue.get("source_timeline_event_ids", [])
        if event_id in timeline_event_index
    ]

    # --------------------------------------------------------
    # DEADLINE - yalnız issue'nun KENDİ linkajı, yalnız
    # canonical deadline'da hâlâ mevcut olanlar.
    # --------------------------------------------------------

    eligible_deadline_ids = [
        deadline_id
        for deadline_id in issue.get("source_deadline_ids", [])
        if deadline_id in deadline_ids
    ]

    allowlist_count = (
        len(eligible_fact_ids)
        + len(eligible_evidence_candidate_ids)
        + len(eligible_legal_research_ids)
        + len(eligible_case_law_ids)
        + len(eligible_timeline_event_ids)
        + len(eligible_deadline_ids)
    )

    menu = {
        "issue_id": issue_id,
        "issue_text": {
            "issue_id": issue_id,
            "issue_type": issue.get("issue_type"),
            "title": issue.get("title"),
            "description": issue.get("description"),
        },
        "eligible_fact_ids": eligible_fact_ids,
        "eligible_evidence_candidate_ids": eligible_evidence_candidate_ids,
        "eligible_legal_research_ids": eligible_legal_research_ids,
        "eligible_case_law_ids": eligible_case_law_ids,
        "eligible_timeline_event_ids": eligible_timeline_event_ids,
        "eligible_deadline_ids": eligible_deadline_ids,
        # minimum grounding: en az bir approved fact ZORUNLU.
        "has_minimum_grounding": len(eligible_fact_ids) >= 1,
        "allowlist_count": allowlist_count,
    }

    return (menu, warnings)


def build_allowlists_for_issues(
    issues,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
    timeline_event_index,
    deadline_ids,
):

    allowlist_by_issue = {}

    warnings = []

    for issue in issues:

        menu, issue_warnings = build_issue_allowlist(
            issue,
            fact_index,
            evidence_candidate_index,
            research_index,
            case_law_decision_index,
            timeline_event_index,
            deadline_ids,
        )

        allowlist_by_issue[issue["issue_id"]] = menu

        warnings.extend(issue_warnings)

    return (allowlist_by_issue, warnings)


# ============================================================
# COVERAGE RECORD
# ============================================================

def coverage_id_for_issue(issue):

    return f"coverage_{issue['issue_id']}"


def build_coverage_record(
    issue,
    execution_state,
    allowlist_count,
    claim_count=0,
    counterargument_count=0,
    rebuttal_count=0,
    suggestion_count=0,
    reason_codes=None,
):

    from argument_policy import DETERMINISTIC_TRIGGER_RULE_ID

    return {
        "coverage_id": coverage_id_for_issue(issue),
        "source_issue_id": issue["issue_id"],
        "execution_state": execution_state,
        "allowlist_count": allowlist_count,
        "claim_count": claim_count,
        "counterargument_count": counterargument_count,
        "rebuttal_count": rebuttal_count,
        "suggestion_count": suggestion_count,
        "reason_codes": list(reason_codes or []),
        "trigger_rule_id": DETERMINISTIC_TRIGGER_RULE_ID,
        "requires_human_review": True,
        "status": "candidate",
    }
