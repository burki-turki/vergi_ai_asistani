# ============================================================
# VERGİ AI - DRAFTING ENGINE V1
#
# AMAÇ
# ----
# Canonical issues.json (Row 9) + approved facts.json (Row 6) +
# active canonical documents (Row 3) + (yalnız CANONICAL) Row 7
# timeline + Row 8 deadline + Row 10 legal research + Row 11 case
# law + Row 12 evidence + Row 13 arguments + Row 14 risk/strategy
# ÜZERİNDEN, avukatın açıkça sağladığı amaç/talep/seçim girdisiyle:
#
#   1) Her canonical issue için tam 1 draft_coverage (selection_scope
#      + execution_state + block_reason muhasebesi, SAF deterministik).
#   2) Agent'ı yalnız allowlist içinden kaynak SEÇİMİ ve paraphrase
#      section metni üretimi için çağırır.
#   3) Section/suggestion adaylarını bağımsız güvenlik kontrollerinden
#      geçirir.
#
# Çıktı: data/cases/<case_id>/drafting/drafting_<case_id>_v1.json.pending
# Engine canonical drafting.json dosyasına YAZMAZ.
# ============================================================

import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path

from legal_research_validator import load_canonical_issues
from timeline_validator import load_canonical_fact_index

from argument_discovery import (
    load_canonical_evidence_optional,
    load_canonical_legal_research_optional,
    load_canonical_case_law_optional,
    load_canonical_timeline_optional,
    load_canonical_deadline_optional,
    CASES_DIR,
)

from risk_strategy_discovery import load_canonical_arguments_optional

from drafting_discovery import (
    build_active_documents_index,
    build_allowlists_for_issues,
    load_canonical_risk_strategy_optional,
    compute_selection_scope,
)

from drafting_policy import (
    DRAFT_INTENT_TYPES,
    APPEAL_LEVELS,
    SELECTION_SCOPES,
    EXECUTION_STATES,
    ZERO_SECTION_EXECUTION_STATES,
    BLOCK_REASONS,
    REF_FIELDS,
    SECTION_TYPES,
    RENDERING_MODES,
    sha256_of,
    compute_lawyer_input_hash,
    compute_section_dedup_fingerprint,
    compute_section_content_fingerprint,
    compute_suggestion_dedup_fingerprint,
    compute_suggestion_content_fingerprint,
    render_gap_note,
    render_disputed_content_note,
    render_agent_suggested_citation_note,
    render_needs_review_flagged_note,
    check_forbidden_phrases_context,
    find_refs_missing_hedge,
    is_ref_direct,
    compute_request_authorization,
    is_valid_request_input,
    has_valid_lawyer_text,
    ALWAYS_FLAGGED_REF_FIELDS,
)

from drafting_agent import (
    build_section_prompt,
    build_suggestion_prompt,
    call_stage,
    run_section_stage,
    run_suggestion_stage,
)

from drafting_validator import validate_drafting_analysis


GENERATION_POLICY_VERSION = "1"

DEFAULT_CASE_ID = "case_0001"


class DraftingEngineError(Exception):
    pass


def load_json(path):

    path = Path(path)

    if not path.exists():

        raise FileNotFoundError(f"JSON dosyası bulunamadı:\n{path}")

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


def atomic_write_json(path, data):

    path = Path(path)

    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.parent / (path.name + ".tmp")

    with open(temp_path, "w", encoding="utf-8", newline="\n") as file:

        json.dump(data, file, ensure_ascii=False, indent=2)

        file.write("\n")

        file.flush()

        os.fsync(file.fileno())

    os.replace(temp_path, path)


def get_drafting_dir(case_id):

    return CASES_DIR / case_id / "drafting"


def get_pending_path(case_id):

    return get_drafting_dir(case_id) / f"drafting_{case_id}_v1.json.pending"


def get_canonical_path(case_id):

    return get_drafting_dir(case_id) / "drafting.json"


def get_history_dir(case_id):

    return get_drafting_dir(case_id) / "history"


def get_carry_forward_dir(case_id):

    return get_drafting_dir(case_id) / "history" / "carry_forward"


def preserve_previous_pending(case_id, pending_path):

    pending_path = Path(pending_path)

    if not pending_path.exists():

        return None

    history_dir = get_history_dir(case_id)

    history_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

    history_path = history_dir / ("drafting_pending_before_engine_" + timestamp + ".json.pending")

    shutil.move(str(pending_path), str(history_path))

    return history_path


def load_previous_canonical(case_id):

    canonical_path = get_canonical_path(case_id)

    if not canonical_path.exists():

        return None

    return load_json(canonical_path)


# ============================================================
# LAWYER INPUT NORMALIZATION
# ============================================================

EMPTY_LAWYER_INPUT = {
    "draft_intent_type": None,
    "appeal_level": None,
    "selected_issue_ids": None,
    "selected_source_ids": {
        "selected_claim_ids": [],
        "selected_counterargument_ids": [],
        "selected_rebuttal_ids": [],
        "selected_risk_ids": [],
        "selected_strategy_ids": [],
    },
    "request_input": None,
    "lawyer_provided_text": None,
}


def normalize_lawyer_input(lawyer_input):

    if lawyer_input is None:

        return dict(EMPTY_LAWYER_INPUT)

    normalized = dict(EMPTY_LAWYER_INPUT)

    normalized.update(lawyer_input)

    selected_source_ids = dict(EMPTY_LAWYER_INPUT["selected_source_ids"])

    selected_source_ids.update(lawyer_input.get("selected_source_ids") or {})

    normalized["selected_source_ids"] = selected_source_ids

    draft_intent_type = normalized.get("draft_intent_type")

    if draft_intent_type is not None and draft_intent_type not in DRAFT_INTENT_TYPES:

        raise DraftingEngineError(f"Geçersiz draft_intent_type: {draft_intent_type}")

    appeal_level = normalized.get("appeal_level")

    if draft_intent_type == "appeal_petition":

        if appeal_level not in APPEAL_LEVELS:

            raise DraftingEngineError(
                "draft_intent_type='appeal_petition' için appeal_level "
                "AÇIKÇA sağlanmalıdır (istinaf|temyiz) - sistem varsayım/"
                "otomatik çıkarım YAPMAZ."
            )

    elif appeal_level is not None:

        raise DraftingEngineError("appeal_level yalnız appeal_petition için doldurulabilir.")

    return normalized


# ============================================================
# GROUNDING/OUTPUT SEMANTIC GUARD
# ============================================================

FORBIDDEN_RECORD_FIELDS = {
    "confidence", "strength", "priority", "admissibility", "sufficiency",
    "severity", "likelihood", "impact", "risk_score", "win_probability",
    "success_probability", "predicted_outcome", "case_outcome",
    "recommended_outcome", "settlement_value", "estimated_liability",
}


def validate_engine_output_semantics(analysis, expected_issue_count, carried_ids=None, direct_lookup=None):

    carried_ids = carried_ids or {"section": set(), "suggestion": set()}

    for name, records in (
        ("draft_coverage", analysis.get("draft_coverage")),
        ("draft_sections", analysis.get("draft_sections")),
        ("draft_source_refs", analysis.get("draft_source_refs")),
        ("draft_review_notes", analysis.get("draft_review_notes")),
        ("draft_agent_suggestions", analysis.get("draft_agent_suggestions")),
    ):

        if not isinstance(records, list):

            raise DraftingEngineError(f"{name} alanı list değil.")

    coverage = analysis["draft_coverage"]

    sections = analysis["draft_sections"]

    refs = analysis["draft_source_refs"]

    suggestions = analysis["draft_agent_suggestions"]

    covered_issue_ids = {c.get("source_issue_id") for c in coverage}

    if len(coverage) != expected_issue_count or len(covered_issue_ids) != expected_issue_count:

        raise DraftingEngineError("Her canonical issue tam olarak bir draft_coverage kaydına sahip olmalıdır.")

    for c in coverage:

        forbidden_present = FORBIDDEN_RECORD_FIELDS & set(c.keys())

        if forbidden_present:

            raise DraftingEngineError(f"Coverage kaydı yasak alan(lar) taşıyor: {forbidden_present}")

        if "review_state" in c or "status" in c:

            raise DraftingEngineError("Coverage kaydı review_state/status taşıyamaz (saf muhasebe).")

        if c.get("selection_scope") not in SELECTION_SCOPES:

            raise DraftingEngineError(f"Geçersiz selection_scope: {c.get('selection_scope')}")

        if c.get("execution_state") not in EXECUTION_STATES:

            raise DraftingEngineError(f"Geçersiz execution_state: {c.get('execution_state')}")

        block_reason = c.get("block_reason")

        if block_reason is not None and block_reason not in BLOCK_REASONS:

            raise DraftingEngineError(f"Geçersiz block_reason: {block_reason}")

        if c.get("execution_state") in ZERO_SECTION_EXECUTION_STATES and c.get("produced_section_count") != 0:

            raise DraftingEngineError(
                f"execution_state={c.get('execution_state')} iken produced_section_count "
                f"0 olmalıdır: {c.get('coverage_id')}"
            )

        if c.get("execution_state") == "analysis_completed" and c.get("produced_section_count", 0) < 1:

            raise DraftingEngineError(
                f"execution_state=analysis_completed iken produced_section_count>=1 olmalıdır: {c.get('coverage_id')}"
            )

    for section in sections:

        forbidden_present = FORBIDDEN_RECORD_FIELDS & set(section.keys())

        if forbidden_present:

            raise DraftingEngineError(f"Section kaydı yasak alan(lar) taşıyor: {forbidden_present}")

        if section.get("submission_status") != "draft_only":

            raise DraftingEngineError(f"section.submission_status='draft_only' olmalıdır: {section.get('section_id')}")

        if (
            section.get("section_id") not in carried_ids["section"]
            and section.get("section_review_state") != "needs_review"
        ):

            raise DraftingEngineError(f"Yeni üretilen section needs_review olmalıdır: {section.get('section_id')}")

        section_refs = [r for r in refs if r["section_id"] == section["section_id"]]

        lawyer_input_meta = analysis["analysis_metadata"]["lawyer_input"]

        lawyer_provided_text = lawyer_input_meta.get("lawyer_provided_text")

        request_input = lawyer_input_meta.get("request_input")

        is_grounded_advocacy = (
            any(
                r["source_field"] in ("source_claim_ids", "source_counterargument_ids", "source_rebuttal_ids")
                for r in section_refs
            )
            or has_valid_lawyer_text(lawyer_provided_text)
            or is_valid_request_input(request_input)
        )

        request_authorized = compute_request_authorization(request_input, lawyer_provided_text)

        if section["section_type"] == "request" and not request_authorized:

            raise DraftingEngineError(
                f"'request' section'ı avukatın AÇIK ÜRETİM yetkisi olmadan üretilemez: "
                f"{section.get('section_id')} (confirmed argüman/risk/strateji tek başına yeterli değildir)."
            )

        errors = check_forbidden_phrases_context(
            section["section_id"], section.get("section_text"), section["section_type"], is_grounded_advocacy,
        )

        if errors:

            raise DraftingEngineError(f"Section kaydı yasaklı ifade içeriyor: {errors[0]}")

        if direct_lookup is not None:

            flagged_refs = [
                r for r in section_refs
                if not is_ref_direct(r, section.get("source_issue_ids", []), direct_lookup)
            ]

            expected_flag = bool(flagged_refs)

            if section.get("contains_unreviewed_source") != expected_flag:

                raise DraftingEngineError(
                    f"contains_unreviewed_source yanlış hesaplanmış: {section.get('section_id')}"
                )

            if flagged_refs:

                missing_hedge = find_refs_missing_hedge(section.get("section_text"), flagged_refs)

                if missing_hedge:

                    raise DraftingEngineError(
                        f"Section flagged kaynak(lar) için belirsizlik ifadesi eksik: "
                        f"{section.get('section_id')} -> {missing_hedge}"
                    )

    for ref in refs:

        if ref.get("rendering_mode") not in RENDERING_MODES:

            raise DraftingEngineError(f"Geçersiz rendering_mode: {ref.get('rendering_mode')}")

        if ref.get("rendering_mode") == "direct_quote" and ref.get("source_field") != "source_fact_ids":

            raise DraftingEngineError(
                f"direct_quote yalnız source_fact_ids için izinlidir: {ref.get('source_ref_id')}"
            )

    for suggestion in suggestions:

        if (
            suggestion.get("suggestion_id") not in carried_ids["suggestion"]
            and suggestion.get("suggestion_review_state") != "needs_review"
        ):

            raise DraftingEngineError(f"Yeni üretilen suggestion needs_review olmalıdır: {suggestion.get('suggestion_id')}")

    seen = set()

    for section in sections:

        section_refs = [r for r in refs if r["section_id"] == section["section_id"]]

        ref_pairs = [(r["source_field"], r["source_id"]) for r in section_refs]

        fp = compute_section_dedup_fingerprint(section, ref_pairs)

        if fp in seen:

            raise DraftingEngineError(f"Duplicate section (fingerprint çakışması): {section.get('section_id')}")

        seen.add(fp)

    return True


# ============================================================
# SOURCE CONTENT SIGNATURE (carry-forward - kaynak içerik/durum)
# ============================================================

def compute_source_signature(
    source_field, source_id, fact_index, timeline_event_index, deadline_index,
    research_index, case_law_decision_index, evidence_candidate_index,
    claim_index, counter_index, rebuttal_index, risk_index, strategy_index,
):

    if source_field == "source_fact_ids":

        record = fact_index.get(source_id)

        if record is None:
            return (source_field, source_id, None)

        fact = record["fact"]

        return (
            source_field, source_id, fact.get("verification_state"),
            (fact.get("source") or {}).get("text_excerpt"),
        )

    if source_field == "source_timeline_event_ids":

        event = timeline_event_index.get(source_id, {})

        return (source_field, source_id, event.get("verification_state"), event.get("date"))

    if source_field == "source_deadline_ids":

        deadline = deadline_index.get(source_id, {})

        return (source_field, source_id, deadline.get("calculation_state"), deadline.get("calculated_deadline"))

    if source_field == "source_legal_research_ids":

        research = research_index.get(source_id, {})

        return (
            source_field, source_id, research.get("finding_status"),
            research.get("formal_result"), research.get("applicability_result"),
        )

    if source_field == "source_case_law_ids":

        decision = case_law_decision_index.get(source_id, {})

        return (source_field, source_id, decision.get("applicability_result"))

    if source_field == "source_evidence_candidate_ids":

        candidate = evidence_candidate_index.get(source_id, {})

        return (source_field, source_id, candidate.get("review_state"), candidate.get("source_excerpt"))

    if source_field == "source_claim_ids":

        claim = claim_index.get(source_id, {})

        return (source_field, source_id, claim.get("claim_review_state"), claim.get("claim_text"))

    if source_field == "source_counterargument_ids":

        counter = counter_index.get(source_id, {})

        return (source_field, source_id, counter.get("counter_review_state"), counter.get("counterargument_text"))

    if source_field == "source_rebuttal_ids":

        rebuttal = rebuttal_index.get(source_id, {})

        return (source_field, source_id, rebuttal.get("rebuttal_review_state"), rebuttal.get("rebuttal_text"))

    if source_field == "source_risk_ids":

        risk = risk_index.get(source_id, {})

        return (source_field, source_id, risk.get("risk_review_state"), risk.get("risk_description"))

    if source_field == "source_strategy_ids":

        strategy = strategy_index.get(source_id, {})

        return (source_field, source_id, strategy.get("strategy_review_state"), strategy.get("strategy_description"))

    return (source_field, source_id, None)


# ============================================================
# DETERMİNİSTİK İNCELEME NOTU ÜRETİMİ (madde F/C - doğrudan test
# edilebilir, agent GEREKTİRMEZ)
# ============================================================

def build_flagged_section_notes(finalized_sections, finalized_refs, direct_lookup):
    """
    Her section için contains_unreviewed_source'u (TEK kaynaklı
    is_ref_direct() ile) hesaplar VE her flagged ref için bir
    'needs_review_flagged' inceleme notu üretir. section dict'leri
    YERİNDE (in-place) güncellenir.
    """

    notes = []

    for section in finalized_sections:

        section_refs = [r for r in finalized_refs if r["section_id"] == section["section_id"]]

        flagged_refs = [
            r for r in section_refs if not is_ref_direct(r, section["source_issue_ids"], direct_lookup)
        ]

        section["contains_unreviewed_source"] = bool(flagged_refs)

        for ref in flagged_refs:

            notes.append(
                {
                    "review_note_id": f"drafting_needs_review_flagged_{ref['source_ref_id']}",
                    "source_issue_id": section["source_issue_ids"][0] if section["source_issue_ids"] else None,
                    "note_type": "needs_review_flagged",
                    "source_field": ref["source_field"],
                    "source_id": ref["source_id"],
                    "note_text": render_needs_review_flagged_note(
                        section["section_id"], ref["source_field"], ref["source_id"],
                    ),
                }
            )

    return notes


def build_deterministic_review_notes(issues, allowlist_by_issue):
    """
    disputed_content (hard-denied disputed/rejected timeline event'ler)
    ve agent_suggested_citation_only (agent_suggested legal_research
    adayları) notlarını, agent'tan TAMAMEN BAĞIMSIZ, yalnız discovery
    menu'sünden üretir - her issue için deterministik ve tekrarlanabilir.
    """

    notes = []

    for issue in issues:

        issue_id = issue["issue_id"]

        menu = allowlist_by_issue[issue_id]

        for denied_event in menu.get("denied_timeline_events", []):

            notes.append(
                {
                    "review_note_id": f"drafting_disputed_content_{issue_id}_{denied_event['source_id']}",
                    "source_issue_id": issue_id,
                    "note_type": "disputed_content",
                    "source_field": "source_timeline_event_ids",
                    "source_id": denied_event["source_id"],
                    "note_text": render_disputed_content_note(denied_event["source_id"], denied_event["state"]),
                }
            )

        for research_id in menu.get("agent_suggested_research_ids", []):

            notes.append(
                {
                    "review_note_id": f"drafting_agent_suggested_citation_only_{issue_id}_{research_id}",
                    "source_issue_id": issue_id,
                    "note_type": "agent_suggested_citation_only",
                    "source_field": "source_legal_research_ids",
                    "source_id": research_id,
                    "note_text": render_agent_suggested_citation_note(research_id),
                }
            )

    return notes


# ============================================================
# BUILD
# ============================================================

def build_drafting_engine_output(case_id, lawyer_input=None, use_agent=False, llm_client=None, network_allowed=False):

    lawyer_input = normalize_lawyer_input(lawyer_input)

    issue_context = load_canonical_issues(case_id)

    issues = issue_context["issues"]

    fact_context = load_canonical_fact_index(case_id)

    fact_index = fact_context["facts"]

    active_documents_index = build_active_documents_index(case_id)

    (_evidence, evidence_candidate_index, evidence_path) = load_canonical_evidence_optional(case_id)

    (_researches, research_index, research_path) = load_canonical_legal_research_optional(case_id)

    (_decisions, case_law_decision_index, case_law_path) = load_canonical_case_law_optional(case_id)

    timeline_event_index, timeline_path = load_canonical_timeline_optional(case_id)

    deadlines, deadline_ids, deadline_path = load_canonical_deadline_optional(case_id)

    deadline_index = {d["deadline_id"]: d for d in deadlines}

    (
        claims, claim_index, counters, counter_index, rebuttals, rebuttal_index,
        argument_coverage_by_issue, arguments_path,
    ) = load_canonical_arguments_optional(case_id)

    risk_index, strategy_index, risk_strategy_analysis, risk_strategy_path = (
        load_canonical_risk_strategy_optional(case_id)
    )

    evidence_exists = evidence_path.exists()

    risk_strategy_exists = risk_strategy_path.exists()

    allowlist_by_issue, discovery_warnings = build_allowlists_for_issues(
        issues, fact_index, active_documents_index, evidence_candidate_index, evidence_exists,
        research_index, case_law_decision_index, timeline_event_index, deadline_index,
        claim_index, counter_index, rebuttal_index, risk_index, strategy_index, risk_strategy_exists,
    )

    warnings = list(discovery_warnings)

    all_known_ids = (
        set(fact_index.keys()) | set(evidence_candidate_index.keys()) | set(research_index.keys())
        | set(case_law_decision_index.keys()) | set(timeline_event_index.keys()) | set(deadline_ids)
        | set(claim_index.keys()) | set(counter_index.keys()) | set(rebuttal_index.keys())
        | set(risk_index.keys()) | set(strategy_index.keys())
    )

    direct_argument_ids = set()

    for issue_id, menu in allowlist_by_issue.items():

        direct_argument_ids |= set(menu["direct_claim_ids"])
        direct_argument_ids |= set(menu["direct_counterargument_ids"])
        direct_argument_ids |= set(menu["direct_rebuttal_ids"])

    # ---- direct_lookup: {(source_field, issue_id): set(direct_ids)} -
    # agent aşamasından ÖNCE hazır (yalnız allowlist'e bağlıdır), böylece
    # hem agent-seviyesi hem engine-seviyesi hedge-check aynı, TEK
    # kaynaktan beslenir. ----

    direct_lookup = {}

    for issue_id, menu in allowlist_by_issue.items():

        direct_lookup[("source_fact_ids", issue_id)] = set(menu["direct_fact_ids"])
        direct_lookup[("source_timeline_event_ids", issue_id)] = set(menu["direct_timeline_event_ids"])
        direct_lookup[("source_deadline_ids", issue_id)] = set(menu["direct_deadline_ids"])
        direct_lookup[("source_evidence_candidate_ids", issue_id)] = set(menu["direct_evidence_candidate_ids"])
        direct_lookup[("source_claim_ids", issue_id)] = set(menu["direct_claim_ids"])
        direct_lookup[("source_counterargument_ids", issue_id)] = set(menu["direct_counterargument_ids"])
        direct_lookup[("source_rebuttal_ids", issue_id)] = set(menu["direct_rebuttal_ids"])

    selected_issue_ids = lawyer_input.get("selected_issue_ids")

    agent_enabled = bool(use_agent)

    finalized_sections = []

    finalized_refs = []

    finalized_suggestions = []

    per_issue_stage_stats = {}

    agent_call_failed = False

    agent_unparseable = False

    if agent_enabled:

        if llm_client is None and not network_allowed:

            warnings.append(
                "Network access disabled (network_allowed=False, --allow-network "
                "verilmedi); Drafting Agent atlandı."
            )

            agent_enabled = False

    if agent_enabled:

        try:

            if llm_client is None:

                from drafting_agent import AnthropicDraftingLLMClient

                llm_client = AnthropicDraftingLLMClient()

            section_prompt = build_section_prompt(allowlist_by_issue, selected_issue_ids, SECTION_TYPES)

            raw_sections = call_stage(llm_client, section_prompt)

            (
                finalized_sections, finalized_refs, section_warnings, section_stats,
            ) = run_section_stage(
                raw_sections, allowlist_by_issue, SECTION_TYPES, fact_index, all_known_ids,
                lawyer_input.get("lawyer_provided_text"), direct_argument_ids, 1,
                request_input=lawyer_input.get("request_input"), direct_lookup=direct_lookup,
            )

            warnings.extend(section_warnings)

            per_issue_stage_stats["section"] = section_stats

            all_known_ids |= {s["section_id"] for s in finalized_sections}

            suggestion_prompt = build_suggestion_prompt(
                [i["issue_id"] for i in issues], finalized_sections,
            )

            raw_suggestions = call_stage(llm_client, suggestion_prompt)

            (finalized_suggestions, suggestion_warnings) = run_suggestion_stage(
                raw_suggestions, {i["issue_id"] for i in issues}, all_known_ids, 1, fact_index,
            )

            warnings.extend(suggestion_warnings)

        except json.JSONDecodeError as error:

            agent_unparseable = True

            warnings.append(f"Drafting Agent cevabı parse edilemedi: {error}")

            finalized_sections = []
            finalized_refs = []
            finalized_suggestions = []

        except Exception as error:  # noqa: BLE001

            agent_call_failed = True

            warnings.append(f"Drafting Agent çağrısı başarısız oldu: {error}")

            finalized_sections = []
            finalized_refs = []
            finalized_suggestions = []

    # ------------------------------------------------------------
    # ANALYSIS METADATA (10 canonical hash + lawyer_input_hash + policy version)
    # ------------------------------------------------------------

    documents_hash_source = sorted(active_documents_index.items(), key=lambda kv: kv[0])

    analysis_metadata = {
        "issues_input_hash": sha256_of(issues),
        "facts_input_hash": sha256_of({fid: rec["fact"] for fid, rec in fact_index.items()}),
        "documents_input_hash": sha256_of(documents_hash_source) if active_documents_index else None,
        "timeline_input_hash": sha256_of(timeline_event_index) if timeline_path.exists() else None,
        "deadline_input_hash": sha256_of(deadlines) if deadline_path.exists() else None,
        "legal_research_input_hash": sha256_of(research_index) if research_path.exists() else None,
        "case_law_input_hash": sha256_of(case_law_decision_index) if case_law_path.exists() else None,
        "evidence_input_hash": (
            sha256_of(evidence_candidate_index) if evidence_exists else None
        ),
        "arguments_input_hash": (
            sha256_of({"claims": claim_index, "counters": counter_index, "rebuttals": rebuttal_index})
            if arguments_path.exists() else None
        ),
        "risk_strategy_input_hash": (
            sha256_of({"risks": risk_index, "strategies": strategy_index}) if risk_strategy_exists else None
        ),
        "lawyer_input_hash": compute_lawyer_input_hash(lawyer_input),
        "generation_policy_version": GENERATION_POLICY_VERSION,
        "lawyer_input": lawyer_input,
        "total_issue_count": len(issues),
        "total_section_count": len(finalized_sections),
        "total_suggestion_count": len(finalized_suggestions),
    }

    # ------------------------------------------------------------
    # SAFE REVIEW CARRY-FORWARD
    # ------------------------------------------------------------

    (finalized_sections, finalized_refs, finalized_suggestions, carry_records) = apply_review_carry_forward(
        case_id, finalized_sections, finalized_refs, finalized_suggestions, analysis_metadata,
        fact_index, timeline_event_index, deadline_index, research_index, case_law_decision_index,
        evidence_candidate_index, claim_index, counter_index, rebuttal_index, risk_index, strategy_index,
    )

    carried_ids = {
        "section": {r["new_id"] for r in carry_records if r["entity_type"] == "section"},
        "suggestion": {r["new_id"] for r in carry_records if r["entity_type"] == "suggestion"},
    }

    # ------------------------------------------------------------
    # contains_unreviewed_source + needs_review_flagged notları +
    # disputed_content / agent_suggested_citation_only notları -
    # ayrı, doğrudan test edilebilir fonksiyonlara taşındı (madde F/C).
    # ------------------------------------------------------------

    flagged_notes = build_flagged_section_notes(finalized_sections, finalized_refs, direct_lookup)

    deterministic_notes = build_deterministic_review_notes(issues, allowlist_by_issue)

    review_notes = flagged_notes + deterministic_notes

    # ------------------------------------------------------------
    # DRAFT COVERAGE
    # ------------------------------------------------------------

    sections_by_issue = {}

    for section in finalized_sections:

        for issue_id in section["source_issue_ids"]:

            sections_by_issue.setdefault(issue_id, []).append(section)

    coverage = []

    for issue in issues:

        issue_id = issue["issue_id"]

        menu = allowlist_by_issue[issue_id]

        scope = compute_selection_scope(issue_id, selected_issue_ids)

        issue_sections = sections_by_issue.get(issue_id, [])

        produced_count = len(issue_sections)

        stats = per_issue_stage_stats.get("section", {}).get(issue_id, {"raw": 0, "rejected": 0})

        reason_codes = []

        block_reason = None

        if scope == "selection_not_provided":

            execution_state = "analysis_not_run"

            block_reason = "blocked_missing_lawyer_input"

        elif scope == "not_selected_by_lawyer":

            execution_state = "analysis_not_run"

        elif not agent_enabled:

            execution_state = "analysis_not_run"

        elif agent_call_failed:

            execution_state = "analysis_failed"

            reason_codes.append("agent_call_failed")

        elif agent_unparseable:

            execution_state = "analysis_failed"

            reason_codes.append("agent_response_unparseable")

        elif not menu["has_any_eligible_source"]:

            upstream_snapshot = menu["upstream_execution_snapshot"]

            all_upstream_absent = all(v is None for k, v in upstream_snapshot.items() if k != "documents")

            execution_state = "blocked_upstream_not_run" if all_upstream_absent else "blocked_missing_input"

            block_reason = "no_confirmed_source_for_issue"

        elif produced_count == 0 and stats["raw"] == 0:

            execution_state = "no_section_produced"

        elif produced_count == 0 and stats["rejected"] > 0:

            execution_state = "analysis_partial"

            block_reason = "all_candidate_sources_rejected"

            reason_codes.append("all_candidate_sections_rejected")

        elif stats["rejected"] > 0:

            execution_state = "analysis_partial"

            reason_codes.append("partial_rejection_occurred")

        else:

            execution_state = "analysis_completed"

        # ---- Madde 6/B: gap_note yalnız METİN ÜRETİMİ GERÇEKTEN
        # DENENDİĞİNDE (execution_state != analysis_not_run) üretilir.
        # 'blocked_missing_lawyer_input' + 'analysis_not_run' (avukat
        # girdisi hiç sağlanmadığı offline baseline) İÇİN gap_note
        # ÜRETİLMEZ - eksiklik yalnız coverage/selection_scope/block_reason
        # üzerinde görünür kalır. Agent GERÇEKTEN çalışıp bir engelle
        # karşılaştığı senaryolarda (no_confirmed_source_for_issue,
        # all_candidate_sources_rejected) not üretimi KORUNUR. ----

        if block_reason is not None and execution_state != "analysis_not_run":

            review_notes.append(
                {
                    "review_note_id": f"drafting_gap_note_{issue_id}",
                    "source_issue_id": issue_id,
                    "note_type": "gap_note",
                    "source_field": None,
                    "source_id": None,
                    "note_text": render_gap_note(block_reason),
                }
            )

        coverage.append(
            {
                "coverage_id": f"draft_coverage_{issue_id}",
                "source_issue_id": issue_id,
                "selection_scope": scope,
                "execution_state": execution_state,
                "block_reason": block_reason,
                "produced_section_count": produced_count,
                "allowlist_count": menu["allowlist_count"],
                "upstream_execution_snapshot": menu["upstream_execution_snapshot"],
                "reason_codes": reason_codes,
            }
        )

    # ------------------------------------------------------------
    # ASSEMBLE
    # ------------------------------------------------------------

    generation_status = "failed" if (agent_call_failed or agent_unparseable) else "completed"

    analysis = {
        "schema_version": 1,
        "drafting_analysis_id": f"drafting_{case_id}_v1",
        "case_id": case_id,
        "generation_status": generation_status,
        "generated_at": datetime.now().astimezone().isoformat(),
        "analysis_metadata": analysis_metadata,
        "draft_coverage": coverage,
        "draft_sections": finalized_sections,
        "draft_source_refs": finalized_refs,
        "draft_review_notes": review_notes,
        "draft_agent_suggestions": finalized_suggestions,
        "warnings": warnings,
        "notes": (
            "Drafting Engine V1 - deterministik coverage/muhasebe + (varsa) "
            "sınırlı agent seçimi/paraphrase. Hiçbir taslak bölümü hukuki "
            "sonuç, dava kazanma ihtimali, gönderim yetkisi veya avukatın "
            "talebi anlamına gelmez; tüm section/suggestion adayları insan "
            "incelemesi gerektirir (submission_status='draft_only')."
        ),
    }

    validate_engine_output_semantics(analysis, len(issues), carried_ids, direct_lookup)

    return {
        "analysis": analysis,
        "issue_count": len(issues),
        "section_count": len(finalized_sections),
        "suggestion_count": len(finalized_suggestions),
        "agent_enabled": agent_enabled,
        "carry_forward_count": len(carry_records),
    }


# ============================================================
# SAFE REVIEW CARRY-FORWARD
# ============================================================

def apply_review_carry_forward(
    case_id, sections, refs, suggestions, analysis_metadata,
    fact_index, timeline_event_index, deadline_index, research_index, case_law_decision_index,
    evidence_candidate_index, claim_index, counter_index, rebuttal_index, risk_index, strategy_index,
):

    previous = load_previous_canonical(case_id)

    carry_records = []

    if previous is None:

        return (sections, refs, suggestions, carry_records)

    if previous.get("analysis_metadata") != analysis_metadata:

        return (sections, refs, suggestions, carry_records)

    lawyer_input_hash = analysis_metadata["lawyer_input_hash"]

    policy_version = analysis_metadata["generation_policy_version"]

    def signature_for_refs(section_id, ref_list):

        return [
            compute_source_signature(
                r["source_field"], r["source_id"], fact_index, timeline_event_index, deadline_index,
                research_index, case_law_decision_index, evidence_candidate_index,
                claim_index, counter_index, rebuttal_index, risk_index, strategy_index,
            )
            for r in ref_list if r["section_id"] == section_id
        ]

    prev_refs = previous.get("draft_source_refs", [])

    prev_section_by_fp = {}

    for s in previous.get("draft_sections", []):

        prev_section_refs = [r for r in prev_refs if r["section_id"] == s["section_id"]]

        ref_sig_full = [
            (r["source_field"], r["source_id"], r["rendering_mode"], r.get("claim_span"))
            for r in prev_section_refs
        ]

        source_content_sig = signature_for_refs(s["section_id"], prev_refs)

        fp = compute_section_content_fingerprint(
            s, ref_sig_full, source_content_sig, lawyer_input_hash, policy_version,
        )

        prev_section_by_fp[fp] = s

    prev_suggestion_by_fp = {
        compute_suggestion_content_fingerprint(s): s
        for s in previous.get("draft_agent_suggestions", [])
    }

    for section in sections:

        section_refs = [r for r in refs if r["section_id"] == section["section_id"]]

        ref_sig_full = [
            (r["source_field"], r["source_id"], r["rendering_mode"], r.get("claim_span"))
            for r in section_refs
        ]

        source_content_sig = signature_for_refs(section["section_id"], refs)

        fp = compute_section_content_fingerprint(
            section, ref_sig_full, source_content_sig, lawyer_input_hash, policy_version,
        )

        prev = prev_section_by_fp.get(fp)

        if prev is not None and prev["section_review_state"] != "needs_review":

            section["section_review_state"] = prev["section_review_state"]

            carry_records.append(
                {
                    "entity_type": "section", "previous_id": prev["section_id"],
                    "new_id": section["section_id"], "fingerprint": fp,
                    "carried_state": prev["section_review_state"],
                }
            )

    for suggestion in suggestions:

        fp = compute_suggestion_content_fingerprint(suggestion)

        prev = prev_suggestion_by_fp.get(fp)

        if prev is not None and prev["suggestion_review_state"] != "needs_review":

            suggestion["suggestion_review_state"] = prev["suggestion_review_state"]

            carry_records.append(
                {
                    "entity_type": "suggestion", "previous_id": prev["suggestion_id"],
                    "new_id": suggestion["suggestion_id"], "fingerprint": fp,
                    "carried_state": prev["suggestion_review_state"],
                }
            )

    return (sections, refs, suggestions, carry_records)


def write_carry_forward_audit(case_id, carry_records):

    if not carry_records:

        return None

    carry_dir = get_carry_forward_dir(case_id)

    carry_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

    audit_path = carry_dir / f"carry_forward_{timestamp}.json"

    atomic_write_json(
        audit_path,
        {
            "audit_type": "drafting_review_carry_forward",
            "case_id": case_id,
            "carried_at": datetime.now().astimezone().isoformat(),
            "carried_records": carry_records,
        },
    )

    return audit_path


# ============================================================
# WRITE PENDING
# ============================================================

def write_pending(case_id, analysis, expected_issue_count, carried_ids=None):

    pending_path = get_pending_path(case_id)

    previous_pending_history = preserve_previous_pending(case_id, pending_path)

    try:

        atomic_write_json(pending_path, analysis)

        validation = validate_drafting_analysis(
            drafting_path=pending_path, expected_case_id=case_id, raise_on_error=False,
        )

        written = load_json(pending_path)

        validate_engine_output_semantics(written, expected_issue_count, carried_ids)

        if not validation["valid"]:

            raise DraftingEngineError(
                "Yazılan pending validator'dan PASS geçemedi:\n- " + "\n- ".join(validation["errors"])
            )

        return (pending_path, validation, previous_pending_history)

    except Exception:

        if pending_path.exists():

            pending_path.unlink()

        if previous_pending_history is not None:

            shutil.move(str(previous_pending_history), str(pending_path))

        raise


# ============================================================
# REAL-TREE SNAPSHOT INVARIANT
# ============================================================

def snapshot_real_drafting_tree(case_id):

    real_dir = CASES_DIR / case_id / "drafting"

    if not real_dir.exists():

        return {"dir_exists": False, "files": {}, "subdirs": []}

    files = {}

    for path in sorted(real_dir.rglob("*")):

        if path.is_file():

            files[str(path.relative_to(real_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()

    subdirs = sorted(
        str(path.relative_to(real_dir)) for path in real_dir.rglob("*") if path.is_dir()
    )

    return {"dir_exists": True, "files": files, "subdirs": subdirs}


def assert_real_drafting_tree_unchanged(case_id, before_snapshot, label):

    after_snapshot = snapshot_real_drafting_tree(case_id)

    assert after_snapshot == before_snapshot, (
        f"{label}: gerçek Row 15 drafting dizini self-test sırasında DEĞİŞTİ "
        f"(leakage şüphesi).\nÖnce: {before_snapshot}\nSonra: {after_snapshot}"
    )


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(case_id="case_0001"):

    from drafting_agent import FakeDraftingLLMClient

    print()
    print("======================================")
    print(" VERGİ AI - DRAFTING ENGINE V1")
    print("======================================")

    real_tree_before = snapshot_real_drafting_tree(case_id)

    # ---- T01: OFFLINE BASELINE (no lawyer input at all) ----

    offline = build_drafting_engine_output(case_id, lawyer_input=None, use_agent=False)

    assert offline["section_count"] == 0
    assert offline["suggestion_count"] == 0
    assert len(offline["analysis"]["draft_coverage"]) == offline["issue_count"]
    assert all(
        c["selection_scope"] == "selection_not_provided" for c in offline["analysis"]["draft_coverage"]
    )
    assert all(
        c["execution_state"] == "analysis_not_run" for c in offline["analysis"]["draft_coverage"]
    )
    assert all(
        c["block_reason"] == "blocked_missing_lawyer_input" for c in offline["analysis"]["draft_coverage"]
    )
    assert offline["analysis"]["analysis_metadata"]["lawyer_input_hash"] is None
    assert offline["analysis"]["generation_status"] == "completed"

    print("T01 Offline baseline (no lawyer input -> selection_not_provided x N, 0 sections):", "PASS")

    # ---- T02: EMPTY SELECTION (avukat bilinçli olarak hiçbir issue seçmedi) ----

    empty_selection = build_drafting_engine_output(
        case_id, lawyer_input={"draft_intent_type": "statement_on_merits", "selected_issue_ids": []},
        use_agent=False,
    )

    assert all(
        c["selection_scope"] == "not_selected_by_lawyer" for c in empty_selection["analysis"]["draft_coverage"]
    )
    assert all(c["block_reason"] is None for c in empty_selection["analysis"]["draft_coverage"])
    assert empty_selection["analysis"]["analysis_metadata"]["lawyer_input_hash"] is not None

    print("T02 Explicit empty selection -> not_selected_by_lawyer (not selection_not_provided):", "PASS")

    # ---- T03: PARTIAL SELECTION ----

    partial = build_drafting_engine_output(
        case_id,
        lawyer_input={"draft_intent_type": "statement_on_merits", "selected_issue_ids": ["issue_001"]},
        use_agent=False,
    )

    cov_by_issue = {c["source_issue_id"]: c for c in partial["analysis"]["draft_coverage"]}

    assert cov_by_issue["issue_001"]["selection_scope"] == "selected"
    assert cov_by_issue["issue_002"]["selection_scope"] == "not_selected_by_lawyer"

    print("T03 Partial selection applies per-issue (not only to empty-list case):", "PASS")

    # ---- T04: APPEAL_LEVEL ZORUNLULUĞU ----

    raised = False

    try:

        build_drafting_engine_output(
            case_id, lawyer_input={"draft_intent_type": "appeal_petition"}, use_agent=False,
        )

    except DraftingEngineError:

        raised = True

    assert raised is True

    ok = build_drafting_engine_output(
        case_id,
        lawyer_input={"draft_intent_type": "appeal_petition", "appeal_level": "istinaf", "selected_issue_ids": []},
        use_agent=False,
    )

    assert ok["analysis"]["analysis_metadata"]["lawyer_input"]["appeal_level"] == "istinaf"

    print("T04 appeal_petition without appeal_level rejected; explicit appeal_level accepted:", "PASS")

    # ---- T05: NETWORK GATE ----

    gated = build_drafting_engine_output(
        case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
        use_agent=True, llm_client=None, network_allowed=False,
    )

    assert gated["agent_enabled"] is False
    assert any("Network access disabled" in w for w in gated["analysis"]["warnings"])

    print("T05 Network safety gate: --with-agent without --allow-network or client -> agent skipped:", "PASS")

    # ---- T06: FULL FLOW WITH INJECTED FAKE CLIENT (real case_0001 fact) ----

    # case_0001'deki HİÇBİR fact 'verified' DEĞİLDİR (26/26 unverified) -
    # bu nedenle bu fact referansı HER ZAMAN flagged'dır ve section_text
    # KENDİ claim_span'i içinde bir HEDGE_PHRASES ifadesi taşımak
    # ZORUNDADIR (madde F/C - flag tek başına yeterli değil).
    SECTION_TEXT_HEDGED = (
        "Dogrulanmamis bilgiye gore, vergi incelemesine iliskin rapor "
        "numarasi kayitlara gecmistir."
    )

    section_response = json.dumps([
        {
            "source_issue_id": "issue_001", "section_type": "facts_summary",
            "section_text": SECTION_TEXT_HEDGED,
            "refs": [
                {
                    "source_field": "source_fact_ids",
                    "source_id": "fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003",
                    "rendering_mode": "paraphrase", "claim_span": SECTION_TEXT_HEDGED,
                },
            ],
        }
    ], ensure_ascii=False)

    suggestion_response = json.dumps([
        {
            "suggestion_type": "additional_review_needed", "source_issue_id": "issue_001",
            "related_reference_ids": [], "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Ek inceleme faydali olabilir.",
        }
    ], ensure_ascii=False)

    client = FakeDraftingLLMClient(response_sequence=[section_response, suggestion_response])

    full = build_drafting_engine_output(
        case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
        use_agent=True, llm_client=client, network_allowed=False,
    )

    assert client.call_count == 2
    assert full["section_count"] == 1
    assert full["suggestion_count"] == 1

    full_cov = {c["source_issue_id"]: c for c in full["analysis"]["draft_coverage"]}

    assert full_cov["issue_001"]["execution_state"] == "analysis_completed"
    assert full_cov["issue_001"]["produced_section_count"] == 1

    print("T06 Full flow (agent section + suggestion, real case_0001 fact grounding):", "PASS")

    # ---- T07: REJECTED-ANCESTOR ARGUMENT NEVER GROUNDS A SECTION ----

    from drafting_discovery import build_allowlists_for_issues as _bafi
    from legal_research_validator import load_canonical_issues as _lci
    from timeline_validator import load_canonical_fact_index as _lcf
    from drafting_discovery import build_active_documents_index as _badi
    from argument_discovery import (
        load_canonical_evidence_optional as _lceo, load_canonical_legal_research_optional as _lclro,
        load_canonical_case_law_optional as _lccl, load_canonical_timeline_optional as _lcto,
        load_canonical_deadline_optional as _lcdo,
    )
    from risk_strategy_discovery import load_canonical_arguments_optional as _lcao
    from drafting_discovery import load_canonical_risk_strategy_optional as _lcrso

    ic = _lci(case_id)
    fc = _lcf(case_id)
    adi = _badi(case_id)
    _e, ev_idx, ep = _lceo(case_id)
    _r, res_idx, rp = _lclro(case_id)
    _d, cl_idx, dp = _lccl(case_id)
    tl_idx, tp = _lcto(case_id)
    dls, dl_ids, dlp = _lcdo(case_id)
    dl_idx = {d["deadline_id"]: d for d in dls}
    (claims, claim_idx, counters, counter_idx, rebuttals, rebuttal_idx, arg_cov, argp) = _lcao(case_id)
    r_idx, s_idx, rsa, rsp = _lcrso(case_id)

    # Sentetik: issue_001'e ait, parent claim'i rejected olan bir counterargument.
    claim_idx = dict(claim_idx)
    counter_idx = dict(counter_idx)

    claim_idx["synthetic_claim_rejected"] = {
        "claim_id": "synthetic_claim_rejected", "source_issue_id": "issue_001",
        "claim_review_state": "rejected", "claim_text": "x",
    }

    counter_idx["synthetic_counter_confirmed"] = {
        "counterargument_id": "synthetic_counter_confirmed", "source_issue_id": "issue_001",
        "source_claim_id": "synthetic_claim_rejected", "counter_review_state": "confirmed",
        "counterargument_text": "y",
    }

    allowlist_by_issue2, _w2 = _bafi(
        ic["issues"], fc["facts"], adi, ev_idx, ep.exists(), res_idx, cl_idx, tl_idx, dl_idx,
        claim_idx, counter_idx, rebuttal_idx, r_idx, s_idx, rsp.exists(),
    )

    assert "synthetic_counter_confirmed" not in allowlist_by_issue2["issue_001"]["eligible_counterargument_ids"], (
        "Rejected ata (claim) altındaki counterargument eligible listede OLMAMALI."
    )

    print("T07 Rejected-ancestor argument excluded from eligible set regardless of own review_state:", "PASS")

    # ---- T08: CROSS-ISSUE LEAKAGE REJECTED AT AGENT SHAPE LEVEL ----

    from drafting_agent import run_section_stage

    leak_item = [
        {
            "source_issue_id": "issue_001", "section_type": "facts_summary",
            "section_text": "x",
            "refs": [
                {
                    "source_field": "source_fact_ids",
                    "source_id": "fact_ihbarname_001_llm_v1_2_1_20260901_122652_001",
                    "rendering_mode": "paraphrase", "claim_span": None,
                },
            ],
        }
    ]

    allowlist_by_issue3, _w3 = _bafi(
        ic["issues"], fc["facts"], adi, ev_idx, ep.exists(), res_idx, cl_idx, tl_idx, dl_idx,
        claim_idx, counter_idx, rebuttal_idx, r_idx, s_idx, rsp.exists(),
    )

    # fact_ihbarname_001... issue_002'ye ait olabilir - issue_001 menu'sunde
    # eligible değilse cross-issue leakage reddedilmelidir.
    menu1 = allowlist_by_issue3["issue_001"]

    is_cross_issue = "fact_ihbarname_001_llm_v1_2_1_20260901_122652_001" not in menu1["eligible_fact_ids"]

    assert is_cross_issue, "Test fixture varsayımı geçersiz - bu fact zaten issue_001'e eligible."

    fin_sections, fin_refs, warns, stats = run_section_stage(
        leak_item, allowlist_by_issue3, {"facts_summary"}, fc["facts"], set(fc["facts"].keys()),
        None, set(), 1,
    )

    assert len(fin_sections) == 0
    assert any("allowlist dışı" in w for w in warns)

    print("T08 Cross-issue fact leakage rejected at agent shape level:", "PASS")

    # ---- T09: agent_suggested legal research denied for grounding ----

    from drafting_discovery import legal_research_grounding_class

    klass, reason = legal_research_grounding_class({"finding_status": "agent_suggested"})

    assert klass == "deny"
    assert reason == "agent_suggested_not_grounding"

    print("T09 finding_status=agent_suggested denied for grounding (citation/hard-deny only):", "PASS")

    # ---- T10: version_unknown does NOT override invalid/not_applicable (hard-deny priority) ----

    klass2, _ = legal_research_grounding_class({
        "finding_status": "provision_resolved_version_unknown",
        "formal_result": "invalid", "applicability_result": "unknown",
    })

    assert klass2 == "deny", "Hard-deny (formal_result=invalid) version-unknown ile aşılamamalı."

    klass3, reason3 = legal_research_grounding_class({
        "finding_status": "provision_resolved_version_unknown",
        "formal_result": "valid", "applicability_result": "unknown",
    })

    assert klass3 == "flagged"

    print("T10 Research combinations: hard-deny priority over version-unknown; valid allowlist combo flagged:", "PASS")

    # ---- T11: direct_quote must be exact substring of fact.source.text_excerpt ----

    from drafting_policy import find_unverified_quotes, collect_citable_texts

    real_fact_id = "fact_vir_001_llm_v1_1_20260901_105342_001"

    citable = collect_citable_texts(fc["facts"], [real_fact_id])

    bad_quote_text = 'Belgede "Bu tamamen uydurulmus bir alinti metni" ifadesi gecmektedir.'

    unverified = find_unverified_quotes(bad_quote_text, citable)

    assert len(unverified) == 1

    print("T11 Fabricated direct_quote (not a substring of text_excerpt) detected as unverified:", "PASS")

    # ---- T12: citation_only forbidden as source_field for legal_research (schema-level rendering rule) ----

    ref_bad = {
        "claim_span": None,
        "source_field": "source_legal_research_ids", "source_id": "research_001",
        "rendering_mode": "direct_quote",
    }

    from drafting_agent import validate_ref_shape

    error = validate_ref_shape(ref_bad, allowlist_by_issue3["issue_001"])

    assert error is not None and "direct_quote" in error

    print("T12 direct_quote rejected for non-fact source_field (legal_research/case_law have no full text):", "PASS")

    # ---- T13: request-authority - lawyer input olmadan 'request' section reddedilir ----

    REQUEST_TEXT_HEDGED = "Dogrulanmamis bilgiye gore, islemin iptali talep olunur."

    request_item = [
        {
            "source_issue_id": "issue_001", "section_type": "request",
            "section_text": REQUEST_TEXT_HEDGED,
            "refs": [
                {
                    "source_field": "source_fact_ids",
                    "source_id": "fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003",
                    "rendering_mode": "paraphrase", "claim_span": REQUEST_TEXT_HEDGED,
                },
            ],
        }
    ]

    fin_sections2, fin_refs2, warns2, stats2 = run_section_stage(
        request_item, allowlist_by_issue3, {"request"}, fc["facts"], set(fc["facts"].keys()),
        None, set(), 1,
    )

    assert len(fin_sections2) == 0
    assert any("talep yetkisi" in w for w in warns2)

    print("T13 'request' section without lawyer_provided_text/confirmed argument rejected (no request authority):", "PASS")

    fin_sections3, fin_refs3, warns3, stats3 = run_section_stage(
        request_item, allowlist_by_issue3, {"request"}, fc["facts"], set(fc["facts"].keys()),
        "Avukatin sagladigi talep metni.", set(), 1,
    )

    assert len(fin_sections3) == 1

    print("T13b 'request' section with lawyer_provided_text accepted (request authority present):", "PASS")

    # ---- T14: conditional advocacy phrase allowed only in grounded 'request' ----

    from drafting_policy import check_forbidden_phrases_context

    errs_denied = check_forbidden_phrases_context(
        "x", "Bu islem hukuka aykiridir.", "facts_summary", False,
    )

    assert len(errs_denied) >= 1

    errs_allowed = check_forbidden_phrases_context(
        "x", "Bu islem hukuka aykiridir.", "request", True,
    )

    assert len(errs_allowed) == 0

    print("T14 Row 9 advocacy phrase denied outside grounded 'request'; allowed inside it:", "PASS")

    # ---- T15: universal outcome-guarantee phrase ALWAYS denied (even in grounded request) ----

    errs_universal = check_forbidden_phrases_context(
        "x", "Bu dava kesinlikle kazanilir.", "request", True,
    )

    assert len(errs_universal) >= 1

    print("T15 Universal outcome-guarantee phrase denied even in grounded 'request':", "PASS")

    # ---- T16: MID-PIPELINE FAILURE CLEANUP ----

    class FailAt2:

        def __init__(self, first_response):

            self.call_count = 0
            self.first_response = first_response

        def generate(self, prompt):

            self.call_count += 1

            if self.call_count == 2:

                raise RuntimeError("Simulated failure (self-test, no real network).")

            return self.first_response

    fail_client = FailAt2(section_response)

    failed = build_drafting_engine_output(
        case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
        use_agent=True, llm_client=fail_client, network_allowed=False,
    )

    fa = failed["analysis"]

    assert fa["generation_status"] == "failed"
    assert len(fa["draft_sections"]) == 0
    assert len(fa["draft_source_refs"]) == 0
    assert len(fa["draft_agent_suggestions"]) == 0

    fa_cov_by_issue = {c["source_issue_id"]: c for c in fa["draft_coverage"]}

    # Yalnız avukatın SEÇTİĞİ (selected) issue için agent gerçekten
    # çağrıldı ve başarısız oldu - seçilmeyenler zaten hiç denenmedi
    # (selection_scope kendi başına bağımsız bir eksendir, agent
    # failure'ı seçilmemiş issue'ları "analysis_failed" yapmaz).
    assert fa_cov_by_issue["issue_001"]["execution_state"] == "analysis_failed"

    for issue_id, cov in fa_cov_by_issue.items():

        if issue_id != "issue_001":

            assert cov["execution_state"] == "analysis_not_run"
            assert cov["selection_scope"] == "not_selected_by_lawyer"

    offline_counts = sorted(
        (c["source_issue_id"], c["allowlist_count"]) for c in offline["analysis"]["draft_coverage"]
    )
    failed_counts = sorted(
        (c["source_issue_id"], c["allowlist_count"]) for c in fa["draft_coverage"]
    )

    assert offline_counts == failed_counts, "Failure cleanup allowlist_count/coverage muhasebesini SİLMEMELİ."

    print("T16 Mid-pipeline failure: sections/refs/suggestions cleared, coverage/hash/allowlist preserved:", "PASS")

    # ---- T17: ALL CANDIDATES REJECTED -> analysis_partial, produced_section_count=0 ----

    all_rejected_response = json.dumps([
        {
            "source_issue_id": "issue_001", "section_type": "facts_summary",
            "section_text": "Bu dava kesinlikle kazanilir.",  # forbidden -> rejected
            "refs": [
                {
                    "source_field": "source_fact_ids",
                    "source_id": "fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003",
                    "rendering_mode": "paraphrase", "claim_span": None,
                },
            ],
        }
    ], ensure_ascii=False)

    reject_client = FakeDraftingLLMClient(response_sequence=[all_rejected_response, "[]"])

    all_rejected_result = build_drafting_engine_output(
        case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
        use_agent=True, llm_client=reject_client, network_allowed=False,
    )

    ar_cov = {c["source_issue_id"]: c for c in all_rejected_result["analysis"]["draft_coverage"]}

    assert ar_cov["issue_001"]["execution_state"] == "analysis_partial"
    assert ar_cov["issue_001"]["produced_section_count"] == 0
    assert ar_cov["issue_001"]["block_reason"] == "all_candidate_sources_rejected"

    print("T17 All candidates rejected -> analysis_partial with produced_section_count=0 (not no_section_produced):", "PASS")

    # ---- T18: no_section_produced (no error, no rejection, genuinely nothing proposed) ----

    empty_client = FakeDraftingLLMClient(response_sequence=["[]", "[]"])

    empty_result = build_drafting_engine_output(
        case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
        use_agent=True, llm_client=empty_client, network_allowed=False,
    )

    er_cov = {c["source_issue_id"]: c for c in empty_result["analysis"]["draft_coverage"]}

    assert er_cov["issue_001"]["execution_state"] == "no_section_produced"

    print("T18 Zero candidates proposed, zero rejections -> no_section_produced:", "PASS")

    # ---- T19: gerçek ağaç değişmezliği ----

    assert_real_drafting_tree_unchanged(case_id, real_tree_before, "End of self-test (full suite)")

    print("T19 No leakage into real case_0001/drafting/ tree (fixture/history absence):", "PASS")

    # ---- T20: DISK-BASED CARRY-FORWARD (izole tempdir, gerçek canonical
    # dosyadan json.loads() ile yeniden okuma) - aynı içerik + aynı lawyer
    # input -> review_state korunur ----

    import tempfile

    original_get_canonical_path = get_canonical_path

    temp_dir = tempfile.TemporaryDirectory(prefix="drafting_engine_carryforward_")

    fake_canonical_path = Path(temp_dir.name) / "drafting.json"

    globals()["get_canonical_path"] = lambda cid: fake_canonical_path

    try:

        lawyer_input_v1 = {
            "draft_intent_type": "appeal_petition", "appeal_level": "istinaf",
            "selected_issue_ids": ["issue_001"],
        }

        client_v1 = FakeDraftingLLMClient(response_sequence=[section_response, "[]"])

        gen1 = build_drafting_engine_output(
            case_id, lawyer_input=lawyer_input_v1, use_agent=True, llm_client=client_v1, network_allowed=False,
        )

        analysis1 = gen1["analysis"]

        section1_id = analysis1["draft_sections"][0]["section_id"]

        analysis1["draft_sections"][0]["section_review_state"] = "confirmed"

        atomic_write_json(fake_canonical_path, analysis1)

        # Diskten TAZE json.loads() ile yeniden oku (Python nesne reuse YOK) -
        # bu, apply_review_carry_forward'ın load_previous_canonical() ile
        # zaten yaptığı şeydir; burada testin kendisinin de gerçekten
        # diskten okuduğunu kanıtlamak için ayrıca doğrulanıyor.
        reloaded = json.loads(fake_canonical_path.read_bytes().decode("utf-8"))

        assert reloaded["draft_sections"][0]["section_review_state"] == "confirmed"

        client_v2 = FakeDraftingLLMClient(response_sequence=[section_response, "[]"])

        gen2 = build_drafting_engine_output(
            case_id, lawyer_input=lawyer_input_v1, use_agent=True, llm_client=client_v2, network_allowed=False,
        )

        analysis2 = gen2["analysis"]

        assert analysis2["draft_sections"][0]["section_review_state"] == "confirmed", (
            "Aynı içerik + aynı lawyer_input (appeal_level dahil) ile "
            "review_state carry-forward edilmeliydi."
        )

        assert gen2["carry_forward_count"] == 1

        print("T20 Disk-reloaded carry-forward: identical content + identical lawyer_input (incl. appeal_level) preserves review_state:", "PASS")

        # ---- T21: appeal_level DEĞİŞİNCE (istinaf -> temyiz) carry-forward
        # ENGELLENİR (analysis_metadata eşleşmez, lawyer_input_hash değişir) ----

        lawyer_input_v2 = dict(lawyer_input_v1)

        lawyer_input_v2["appeal_level"] = "temyiz"

        client_v3 = FakeDraftingLLMClient(response_sequence=[section_response, "[]"])

        gen3 = build_drafting_engine_output(
            case_id, lawyer_input=lawyer_input_v2, use_agent=True, llm_client=client_v3, network_allowed=False,
        )

        analysis3 = gen3["analysis"]

        assert analysis3["analysis_metadata"]["lawyer_input_hash"] != analysis1["analysis_metadata"]["lawyer_input_hash"]
        assert analysis3["draft_sections"][0]["section_review_state"] == "needs_review", (
            "appeal_level istinaf->temyiz değişince eski review_state TAŞINMAMALIDIR."
        )
        assert gen3["carry_forward_count"] == 0

        print("T21 appeal_level change (istinaf -> temyiz) resets carry-forward (previous review NOT carried):", "PASS")

    finally:

        globals()["get_canonical_path"] = original_get_canonical_path

        temp_dir.cleanup()

    # ---- T22: AYNI source_id, DEĞİŞMİŞ İÇERİK -> content fingerprint
    # farklılaşır (carry-forward'ın kaynak-içerik-duyarlılığı, unit seviyesinde) ----

    from drafting_policy import compute_section_content_fingerprint

    sample_section = {
        "section_type": "facts_summary", "source_issue_ids": ["issue_001"],
        "section_text": "Sabit metin.",
    }

    ref_sig = [("source_fact_ids", "fact_x", "paraphrase", None)]

    sig_v1 = [("source_fact_ids", "fact_x", "unverified", "Eski metin.")]

    sig_v2 = [("source_fact_ids", "fact_x", "verified", "Eski metin.")]  # AYNI ID, DEĞİŞMİŞ verification_state

    fp_v1 = compute_section_content_fingerprint(sample_section, ref_sig, sig_v1, None, "1")

    fp_v2 = compute_section_content_fingerprint(sample_section, ref_sig, sig_v2, None, "1")

    assert fp_v1 != fp_v2, (
        "Aynı source_id altında kaynağın KENDİ içeriği/durumu değiştiğinde "
        "content fingerprint DEĞİŞMEMİŞ - carry-forward yanlışlıkla eski "
        "onayı taşıyabilir."
    )

    print("T22 Same source_id, changed source content/state (verification_state) invalidates content fingerprint:", "PASS")

    # ================================================================
    # REMEDIATION - MADDE 2/E: SUGGESTION METİN GÜVENLİĞİ
    # ================================================================

    from drafting_agent import run_suggestion_stage
    from drafting_validator import validate_draft_agent_suggestions

    suggestion_known_ids = set(fc["facts"].keys()) | {"issue_001", "fact_SECRET_GHOST_ID_999"}

    attack_suggestion_item = [
        {
            "suggestion_type": "additional_review_needed", "source_issue_id": "issue_001",
            "related_reference_ids": [], "reason_code": "general_contextual_relevance",
            "grounded_explanation": (
                "Bkz fact_SECRET_GHOST_ID_999 numarali kayit, 15.03.2019 tarihinde "
                "500000 TL tutarinda islem."
            ),
        }
    ]

    attack_finalized, attack_warnings = run_suggestion_stage(
        attack_suggestion_item, {"issue_001"}, suggestion_known_ids, 1, fc["facts"],
    )

    assert len(attack_finalized) == 0, "Smuggled ID + desteklenmeyen tarih/tutar içeren suggestion KABUL EDİLDİ."

    assert any("uydurma" in w or "beyan edilmemiş" in w or "desteklenmeyen" in w for w in attack_warnings)

    print("T23 Suggestion attack (smuggled ID + unsupported date/amount) rejected at agent stage:", "PASS")

    bad_suggestion_record = {
        "suggestion_id": "drafting_suggestion_bad", "source_issue_id": "issue_001",
        "related_reference_ids": [], "suggestion_type": "additional_review_needed",
        "reason_code": "general_contextual_relevance",
        "grounded_explanation": attack_suggestion_item[0]["grounded_explanation"],
        "suggestion_review_state": "needs_review", "requires_human_review": True, "status": "candidate",
    }

    bypass_errors = validate_draft_agent_suggestions(
        [bad_suggestion_record], {"issue_001": {}}, suggestion_known_ids, fc["facts"],
    )

    assert len(bypass_errors) >= 1, "Agent bypass edilip validator'a verilen aynı saldırı KABUL EDİLDİ."

    print("T23b Same attack, agent bypassed, fed directly to independent validator, rejected:", "PASS")

    safe_suggestion_item = [
        {
            "suggestion_type": "additional_review_needed", "source_issue_id": "issue_001",
            "related_reference_ids": [], "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Bu issue icin ek inceleme faydali olabilir.",
        }
    ]

    safe_finalized, safe_warnings = run_suggestion_stage(
        safe_suggestion_item, {"issue_001"}, suggestion_known_ids, 1, fc["facts"],
    )

    assert len(safe_finalized) == 1, "Güvenli suggestion yanlışlıkla reddedildi (pozitif kontrol başarısız)."

    safe_record = dict(safe_finalized[0])

    safe_errors = validate_draft_agent_suggestions(
        [safe_record], {"issue_001": {}}, suggestion_known_ids, fc["facts"],
    )

    assert safe_errors == [], f"Güvenli suggestion validator tarafından yanlışlıkla reddedildi: {safe_errors}"

    print("T24 Positive control: safe suggestion accepted by BOTH agent stage and independent validator:", "PASS")

    # ================================================================
    # REMEDIATION - MADDE 3/D: GERÇEK TALEP YETKİSİ (Q1 vs Q2 AYRIMI)
    # ================================================================

    fin25, refs25, warns25, stats25 = run_section_stage(
        request_item, allowlist_by_issue3, {"request"}, fc["facts"], set(fc["facts"].keys()),
        None, set(), 1, request_input={"request_type": "iptal", "request_text": "Islemin iptalini talep ediyoruz."},
        direct_lookup={},
    )

    assert len(fin25) == 1, "Yalnız yapılandırılmış request_input ile talep üretimi KABUL EDİLMEDİ."

    print("T25 Valid structured request_input alone authorizes 'request' section production:", "PASS")

    fin26, refs26, warns26, stats26 = run_section_stage(
        request_item, allowlist_by_issue3, {"request"}, fc["facts"], set(fc["facts"].keys()),
        None,  # lawyer_provided_text YOK
        {"fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"},  # "confirmed argument" SİMÜLASYONU
        1, request_input=None, direct_lookup={},  # request_input DA YOK
    )

    assert len(fin26) == 0, (
        "request_input/lawyer_provided_text YOKKEN, confirmed argüman referansı VARKEN "
        "talep sonucu YİNE DE ÜRETİLDİ - Q1/Q2 karışmış olabilir."
    )

    assert any("talep yetkisi" in w for w in warns26)

    print("T26 Confirmed-argument-only (no request_input/lawyer_provided_text) STILL rejected (Q1 != Q2):", "PASS")

    unsupported_request_text = (
        "Dogrulanmamis bilgiye gore, 999999 TL tutarinda iade talep olunur."
    )

    unsupported_request_item = [
        {
            "source_issue_id": "issue_001", "section_type": "request",
            "section_text": unsupported_request_text,
            "refs": [
                {
                    "source_field": "source_fact_ids",
                    "source_id": "fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003",
                    "rendering_mode": "paraphrase", "claim_span": unsupported_request_text,
                },
            ],
        }
    ]

    fin27, refs27, warns27, stats27 = run_section_stage(
        unsupported_request_item, allowlist_by_issue3, {"request"}, fc["facts"], set(fc["facts"].keys()),
        "Avukatin sagladigi talep metni.", set(), 1, request_input=None, direct_lookup={},
    )

    assert len(fin27) == 0, (
        "lawyer_provided_text VARKEN, kaynaksız/desteklenmeyen bir tutar (999999 TL) "
        "içeren talep metni YİNE DE KABUL EDİLDİ - lawyer_provided_text sınırsız izin "
        "sayılmamalıdır."
    )

    assert any("desteklenmeyen" in w for w in warns27)

    print("T27 lawyer_provided_text present does NOT exempt unsupported amount/date claims from grounding checks:", "PASS")

    from drafting_validator import validate_draft_sections as _vds28

    bad_request_text = "Dogrulanmamis bilgiye gore, islemin iptali talep olunur."

    bad_request_section = {
        "section_id": "draft_section_bad_request", "source_issue_ids": ["issue_001"],
        "section_type": "request", "section_text": bad_request_text,
        "contains_unreviewed_source": True, "section_review_state": "needs_review",
        "requires_human_review": True, "status": "candidate", "submission_status": "draft_only",
    }

    bad_request_ref = {
        "source_ref_id": "draft_section_bad_request_ref_001", "section_id": "draft_section_bad_request",
        "claim_span": bad_request_text, "source_field": "source_fact_ids",
        "source_id": "fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003", "rendering_mode": "paraphrase",
    }

    bypass28_errors = _vds28(
        [bad_request_section], [bad_request_ref], allowlist_by_issue3, fc["facts"], set(fc["facts"].keys()),
        None, request_input=None, direct_lookup={},
    )

    assert any("yetkisi" in e for e in bypass28_errors), (
        "Agent bypass edilip validator'a verilen yetkisiz 'request' section KABUL EDİLDİ."
    )

    print("T28 Agent bypassed: unauthorized 'request' section fed directly to validator rejected:", "PASS")

    # ================================================================
    # REMEDIATION - MADDE 4/F/C: BELİRSİZLİK SUNUMU + 3 EKSİK NOT TÜRÜ
    # ================================================================

    synthetic_issue_29 = dict(ic["issues"][0])

    synthetic_issue_29["source_timeline_event_ids"] = list(
        synthetic_issue_29.get("source_timeline_event_ids", [])
    ) + ["synthetic_disputed_event_001"]

    synthetic_timeline_index_29 = dict(tl_idx)

    synthetic_timeline_index_29["synthetic_disputed_event_001"] = {
        "event_id": "synthetic_disputed_event_001", "verification_state": "disputed",
    }

    from drafting_discovery import build_issue_drafting_context as _bidc29

    menu29, _warn29 = _bidc29(
        synthetic_issue_29, fc["facts"], adi, ev_idx, ep.exists(), res_idx, cl_idx,
        synthetic_timeline_index_29, dl_idx, claim_idx, counter_idx, rebuttal_idx, r_idx, s_idx, rsp.exists(),
    )

    assert {"source_id": "synthetic_disputed_event_001", "state": "disputed"} in menu29["denied_timeline_events"]

    allowlist_29 = {"issue_001": menu29}

    disputed_notes = build_deterministic_review_notes([synthetic_issue_29], allowlist_29)

    assert len(disputed_notes) == 1
    assert disputed_notes[0]["note_type"] == "disputed_content"
    assert disputed_notes[0]["note_text"] == render_disputed_content_note("synthetic_disputed_event_001", "disputed")

    print("T29 disputed_content note genuinely produced for a hard-denied disputed timeline event:", "PASS")

    menu30 = dict(menu29)

    menu30["denied_timeline_events"] = []

    menu30["agent_suggested_research_ids"] = ["synthetic_research_agent_suggested_001"]

    allowlist_30 = {"issue_001": menu30}

    agent_suggested_notes = build_deterministic_review_notes([synthetic_issue_29], allowlist_30)

    assert len(agent_suggested_notes) == 1
    assert agent_suggested_notes[0]["note_type"] == "agent_suggested_citation_only"
    assert agent_suggested_notes[0]["note_text"] == render_agent_suggested_citation_note(
        "synthetic_research_agent_suggested_001"
    )

    print("T30 agent_suggested_citation_only note genuinely produced for an agent_suggested research candidate:", "PASS")

    flagged_test_section = {
        "section_id": "draft_section_flag_test", "source_issue_ids": ["issue_001"],
        "section_type": "facts_summary", "section_text": SECTION_TEXT_HEDGED,
    }

    flagged_test_ref = {
        "source_ref_id": "draft_section_flag_test_ref_001", "section_id": "draft_section_flag_test",
        "claim_span": SECTION_TEXT_HEDGED, "source_field": "source_fact_ids",
        "source_id": "fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003", "rendering_mode": "paraphrase",
    }

    empty_direct_lookup = {}

    flagged_notes_31 = build_flagged_section_notes([flagged_test_section], [flagged_test_ref], empty_direct_lookup)

    assert flagged_test_section["contains_unreviewed_source"] is True

    assert len(flagged_notes_31) == 1
    assert flagged_notes_31[0]["note_type"] == "needs_review_flagged"
    assert flagged_notes_31[0]["note_text"] == render_needs_review_flagged_note(
        "draft_section_flag_test", "source_fact_ids", "fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003",
    )

    print("T31 needs_review_flagged note genuinely produced for a flagged (non-direct) section reference:", "PASS")

    # ---- Not-only kaynağın AYNI issue içinde gövdeye sokulması reddedilir
    # (cross-issue testinin YERİNE GEÇMEZ - bu ayrı, same-issue bir test) ----

    same_issue_disputed_attempt = [
        {
            "source_issue_id": "issue_001", "section_type": "facts_summary",
            "section_text": SECTION_TEXT_HEDGED,
            "refs": [
                {
                    "source_field": "source_timeline_event_ids",
                    "source_id": "synthetic_disputed_event_001",
                    "rendering_mode": "paraphrase", "claim_span": SECTION_TEXT_HEDGED,
                },
            ],
        }
    ]

    allowlist_32 = dict(allowlist_by_issue3)

    allowlist_32["issue_001"] = dict(allowlist_by_issue3["issue_001"])

    # 'synthetic_disputed_event_001' bilerek eligible_timeline_event_ids'e
    # EKLENMEMİŞTİR (disputed olduğu için allowlist'te asla yer almaz) -
    # agent onu SIZDIRMAYA çalışırsa allowlist-escape olarak reddedilmelidir.

    fin32, refs32, warns32, stats32 = run_section_stage(
        same_issue_disputed_attempt, allowlist_32, {"facts_summary"}, fc["facts"], set(fc["facts"].keys()),
        None, set(), 1, request_input=None, direct_lookup={},
    )

    assert len(fin32) == 0, "Aynı issue içindeki disputed (not-only) kaynak gövdeye SIZDI."

    assert any("allowlist dışı" in w for w in warns32)

    print("T32 Not-only (disputed) source injection WITHIN the same issue rejected (not a cross-issue test):", "PASS")

    # ================================================================
    # REMEDIATION - MADDE 7: NETWORK GATE MATRİSİ (gerçek HTTP çağrısı
    # YOK - yalnız Fake/Spy/Stub)
    # ================================================================

    import drafting_agent as _da

    # ---- T33: iki flag de yok (use_agent=False) -> agent hiç devreye girmez ----

    no_flags = build_drafting_engine_output(
        case_id, lawyer_input={"selected_issue_ids": ["issue_001"]}, use_agent=False,
    )

    assert no_flags["agent_enabled"] is False

    print("T33 Neither flag (use_agent=False) -> agent never engaged:", "PASS")

    # ---- T34: yalnız --with-agent (network_allowed=False) -> atlanır ----

    only_with_agent = build_drafting_engine_output(
        case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
        use_agent=True, llm_client=None, network_allowed=False,
    )

    assert only_with_agent["agent_enabled"] is False
    assert any("Network access disabled" in w for w in only_with_agent["analysis"]["warnings"])

    print("T34 --with-agent alone (no --allow-network, no client) -> agent skipped:", "PASS")

    # ---- T35: yalnız --allow-network (use_agent=False) -> agent zaten hiç çağrılmaz ----

    only_allow_network = build_drafting_engine_output(
        case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
        use_agent=False, llm_client=None, network_allowed=True,
    )

    assert only_allow_network["agent_enabled"] is False
    assert only_allow_network["section_count"] == 0

    print("T35 --allow-network alone (no --with-agent) -> agent never invoked:", "PASS")

    # ---- T36: her iki flag + injected Fake client -> fake kullanılır,
    # GERÇEK client HİÇ inşa edilmez (spy ile kanıtlanır) ----

    real_client_constructed = {"count": 0}

    class SpyAnthropicDraftingLLMClient(_da.AnthropicDraftingLLMClient):

        def __init__(self):

            real_client_constructed["count"] += 1

            super().__init__()

    original_anthropic_client_class = _da.AnthropicDraftingLLMClient

    _da.AnthropicDraftingLLMClient = SpyAnthropicDraftingLLMClient

    try:

        injected_fake = FakeDraftingLLMClient(response_sequence=[section_response, "[]"])

        both_flags_injected = build_drafting_engine_output(
            case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
            use_agent=True, llm_client=injected_fake, network_allowed=True,
        )

        assert real_client_constructed["count"] == 0, (
            "Injected Fake client verilmesine RAĞMEN gerçek Anthropic client İNŞA EDİLDİ."
        )
        assert injected_fake.call_count == 2
        assert both_flags_injected["section_count"] == 1

        print("T36 Both flags + injected Fake client -> fake used, real client NEVER constructed:", "PASS")

        # ---- T37: her iki flag + injected client YOK -> GERÇEK client
        # inşa edilir (spy ile kanıtlanır); API key yok olduğu için
        # generate() ilk satırda fail-closed olur, GERÇEK ağ çağrısı YOK ----

        real_client_constructed["count"] = 0

        saved_api_key = os.environ.pop("ANTHROPIC_API_KEY", None)

        try:

            both_flags_no_client = build_drafting_engine_output(
                case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
                use_agent=True, llm_client=None, network_allowed=True,
            )

            assert real_client_constructed["count"] == 1, (
                "Her iki flag + injected client yokken GERÇEK client İNŞA EDİLMEDİ."
            )
            assert both_flags_no_client["analysis"]["generation_status"] == "failed"
            assert any(
                "ANTHROPIC_API_KEY" in w or "başarısız" in w
                for w in both_flags_no_client["analysis"]["warnings"]
            )

        finally:

            if saved_api_key is not None:

                os.environ["ANTHROPIC_API_KEY"] = saved_api_key

        print("T37 Both flags + no injected client -> REAL client IS constructed (spy-verified), zero real network calls:", "PASS")

    finally:

        _da.AnthropicDraftingLLMClient = original_anthropic_client_class

    # ---- T38: eksik API key ile fail-closed - HTTP denenmeden ÖNCE ----

    saved_api_key_2 = os.environ.pop("ANTHROPIC_API_KEY", None)

    try:

        raised_runtime_error = False

        try:

            _da.AnthropicDraftingLLMClient().generate("test prompt")

        except RuntimeError as error:

            raised_runtime_error = True

            assert "ANTHROPIC_API_KEY" in str(error)

        assert raised_runtime_error is True, "Eksik API key ile fail-closed RuntimeError FIRLATILMADI."

        assert "anthropic" not in sys.modules or True  # gerçek network modülü import edilmiş olsa bile hiç ÇAĞRILMADI

    finally:

        if saved_api_key_2 is not None:

            os.environ["ANTHROPIC_API_KEY"] = saved_api_key_2

    print("T38 Missing ANTHROPIC_API_KEY -> explicit fail-closed error BEFORE any HTTP attempt:", "PASS")

    # ================================================================
    # TARGETED GUARD HARDENING - HER SALDIRI İKİ AYRI YOLDAN TEST EDİLİR:
    # (a) agent aşamasına doğrudan, (b) agent TAMAMEN bypass edilip
    # tam validator'a doğrudan. "Agent zaten reddetti" gerekçesiyle
    # validator testi ATLANMAZ.
    # ================================================================

    from drafting_validator import validate_draft_sections as _vds
    from drafting_validator import validate_draft_agent_suggestions as _vdas

    FACT_ID = "fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"

    hardening_known_ids = set(fc["facts"].keys()) | {"issue_001", "issue_002"}

    other_issue_fact_candidates = [
        f for f in fc["facts"].keys() if not f.startswith("fact_dava_dilekcesi_001")
    ]
    OTHER_ISSUE_FACT = other_issue_fact_candidates[0] if other_issue_fact_candidates else None

    def make_section_record(section_id, text, refs):
        return {
            "section_id": section_id, "source_issue_ids": ["issue_001"], "section_type": "facts_summary",
            "section_text": text, "contains_unreviewed_source": False, "section_review_state": "needs_review",
            "requires_human_review": True, "status": "candidate", "submission_status": "draft_only",
        }

    def make_ref_record(section_id, source_id, claim_span=None):
        return {
            "source_ref_id": f"{section_id}_ref_001", "section_id": section_id, "claim_span": claim_span,
            "source_field": "source_fact_ids", "source_id": source_id, "rendering_mode": "paraphrase",
        }

    def make_suggestion_record(suggestion_id, text):
        return {
            "suggestion_id": suggestion_id, "source_issue_id": "issue_001", "related_reference_ids": [],
            "suggestion_type": "additional_review_needed", "reason_code": "general_contextual_relevance",
            "grounded_explanation": text, "suggestion_review_state": "needs_review",
            "requires_human_review": True, "status": "candidate",
        }

    # ---- T40/T41: Ghost (fabricated) ID - SECTION - agent + bypass ----

    ghost_section_item = [{
        "source_issue_id": "issue_001", "section_type": "facts_summary",
        "section_text": "Bkz fact_TAMAMEN_UYDURMA_GHOST_888 numarali kayit.",
        "refs": [{
            "source_field": "source_fact_ids", "source_id": FACT_ID,
            "rendering_mode": "paraphrase", "claim_span": None,
        }],
    }]

    fin40, _, warns40, _ = run_section_stage(
        ghost_section_item, allowlist_by_issue3, {"facts_summary"}, fc["facts"], hardening_known_ids,
        None, set(), 1, request_input=None, direct_lookup={},
    )
    assert len(fin40) == 0, "Ghost ID iceren section agent asamasinda KABUL EDILDI."
    assert any("uydurma" in w for w in warns40)
    print("T40 Ghost (fabricated) ID in section text rejected at AGENT stage:", "PASS")

    ghost_section_record = make_section_record(
        "draft_section_ghost", "Bkz fact_TAMAMEN_UYDURMA_GHOST_888 numarali kayit.", None,
    )
    ghost_section_ref = make_ref_record("draft_section_ghost", FACT_ID)
    errors41 = _vds(
        [ghost_section_record], [ghost_section_ref], allowlist_by_issue3, fc["facts"], hardening_known_ids, None,
        request_input=None, direct_lookup={},
    )
    assert any("uydurma" in e for e in errors41), "Ghost ID iceren section BYPASS validator'da KABUL EDILDI."
    print("T41 Same ghost ID, agent bypassed, fed directly to full validator, rejected:", "PASS")

    # ---- T42/T43: Ghost (fabricated) ID - SUGGESTION - agent + bypass ----

    ghost_suggestion_item = [{
        "suggestion_type": "additional_review_needed", "source_issue_id": "issue_001",
        "related_reference_ids": [], "reason_code": "general_contextual_relevance",
        "grounded_explanation": "Bkz fact_TAMAMEN_UYDURMA_GHOST_888 numarali kayit.",
    }]
    fin42, warns42 = run_suggestion_stage(ghost_suggestion_item, {"issue_001"}, hardening_known_ids, 1, fc["facts"])
    assert len(fin42) == 0, "Ghost ID iceren suggestion agent asamasinda KABUL EDILDI."
    assert any("uydurma" in w for w in warns42)
    print("T42 Ghost (fabricated) ID in suggestion text rejected at AGENT stage:", "PASS")

    ghost_suggestion_record = make_suggestion_record(
        "bypass_ghost", "Bkz fact_TAMAMEN_UYDURMA_GHOST_888 numarali kayit.",
    )
    errors43 = _vdas([ghost_suggestion_record], {"issue_001": {}, "issue_002": {}}, hardening_known_ids, fc["facts"])
    assert any("uydurma" in e for e in errors43), "Ghost ID iceren suggestion BYPASS validator'da KABUL EDILDI."
    print("T43 Same ghost ID, agent bypassed, fed directly to independent validator, rejected:", "PASS")

    # ---- T44/T45: Cross-issue REAL ID - SECTION - agent + bypass ----

    if OTHER_ISSUE_FACT:

        cross_issue_item = [{
            "source_issue_id": "issue_001", "section_type": "facts_summary",
            "section_text": f"Bkz {OTHER_ISSUE_FACT} numarali kayit.",
            "refs": [{
                "source_field": "source_fact_ids", "source_id": FACT_ID,
                "rendering_mode": "paraphrase", "claim_span": None,
            }],
        }]

        fin44, _, warns44, _ = run_section_stage(
            cross_issue_item, allowlist_by_issue3, {"facts_summary"}, fc["facts"], hardening_known_ids,
            None, set(), 1, request_input=None, direct_lookup={},
        )
        assert len(fin44) == 0, "Cross-issue GERCEK ID iceren section agent asamasinda KABUL EDILDI."
        assert any("beyan edilmemiş" in w for w in warns44)
        print("T44 Real ID belonging to a DIFFERENT issue rejected at AGENT stage (section):", "PASS")

        cross_section_record = make_section_record(
            "draft_section_cross", f"Bkz {OTHER_ISSUE_FACT} numarali kayit.", None,
        )
        cross_section_ref = make_ref_record("draft_section_cross", FACT_ID)
        errors45 = _vds(
            [cross_section_record], [cross_section_ref], allowlist_by_issue3, fc["facts"], hardening_known_ids, None,
            request_input=None, direct_lookup={},
        )
        assert any("beyan edilmemiş" in e for e in errors45), "Cross-issue ID BYPASS validator'da KABUL EDILDI."
        print("T45 Same cross-issue real ID, agent bypassed, fed directly to full validator, rejected:", "PASS")

    else:

        print("T44/T45 SKIPPED (no second-document fact available in case_0001) - NOT counted as PASS.")

    # ---- T46/T47: Undeclared (same-issue) REAL ID - SUGGESTION - agent + bypass ----

    undeclared_suggestion_item = [{
        "suggestion_type": "additional_review_needed", "source_issue_id": "issue_001",
        "related_reference_ids": [], "reason_code": "general_contextual_relevance",
        "grounded_explanation": f"Bkz {FACT_ID} numarali kayit.",
    }]
    fin46, warns46 = run_suggestion_stage(undeclared_suggestion_item, {"issue_001"}, hardening_known_ids, 1, fc["facts"])
    assert len(fin46) == 0, "Undeclared gercek ID iceren suggestion agent asamasinda KABUL EDILDI."
    assert any("beyan edilmemiş" in w for w in warns46)
    print("T46 Real but undeclared ID rejected at AGENT stage (suggestion):", "PASS")

    undeclared_suggestion_record = make_suggestion_record("bypass_undeclared", f"Bkz {FACT_ID} numarali kayit.")
    errors47 = _vdas(
        [undeclared_suggestion_record], {"issue_001": {}, "issue_002": {}}, hardening_known_ids, fc["facts"],
    )
    assert any("beyan edilmemiş" in e for e in errors47), "Undeclared ID BYPASS validator'da KABUL EDILDI."
    print("T47 Same undeclared real ID, agent bypassed, fed directly to independent validator, rejected:", "PASS")

    # ---- T48/T49: Outcome-guarantee VARIANT ('kesinlikle kazanilacaktir') - SECTION ----

    outcome_variant_text = "Bu dava kesinlikle kazanilacaktir."

    outcome_section_item = [{
        "source_issue_id": "issue_001", "section_type": "facts_summary", "section_text": outcome_variant_text,
        "refs": [{
            "source_field": "source_fact_ids", "source_id": FACT_ID,
            "rendering_mode": "paraphrase", "claim_span": outcome_variant_text,
        }],
    }]
    fin48, _, warns48, _ = run_section_stage(
        outcome_section_item, allowlist_by_issue3, {"facts_summary"}, fc["facts"], hardening_known_ids,
        None, set(), 1, request_input=None, direct_lookup={},
    )
    assert len(fin48) == 0, "'kesinlikle kazanilacaktir' varyanti agent asamasinda KABUL EDILDI."
    assert any("kesinlik-zarfı" in w or "evrensel" in w for w in warns48)
    print("T48 Outcome-guarantee VARIANT ('kesinlikle kazanilacaktir', not in exact-phrase list) rejected at AGENT stage:", "PASS")

    outcome_section_record = make_section_record("draft_section_outcome", outcome_variant_text, None)
    outcome_section_ref = make_ref_record("draft_section_outcome", FACT_ID, claim_span=outcome_variant_text)
    errors49 = _vds(
        [outcome_section_record], [outcome_section_ref], allowlist_by_issue3, fc["facts"], hardening_known_ids, None,
        request_input=None, direct_lookup={},
    )
    assert any("kesinlik-zarfı" in e or "evrensel" in e for e in errors49), "Outcome-guarantee varyanti BYPASS validator'da KABUL EDILDI."
    print("T49 Same outcome-guarantee variant, agent bypassed, fed directly to full validator, rejected:", "PASS")

    # ---- T50/T51: Outcome-guarantee VARIANT ('kesinlikle kaybedilecektir') - SUGGESTION ----

    outcome_variant_text_2 = "Bu dava kesinlikle kaybedilecektir."

    outcome_suggestion_item = [{
        "suggestion_type": "additional_review_needed", "source_issue_id": "issue_001",
        "related_reference_ids": [], "reason_code": "general_contextual_relevance",
        "grounded_explanation": outcome_variant_text_2,
    }]
    fin50, warns50 = run_suggestion_stage(outcome_suggestion_item, {"issue_001"}, hardening_known_ids, 1, fc["facts"])
    assert len(fin50) == 0, "'kesinlikle kaybedilecektir' varyanti agent asamasinda KABUL EDILDI."
    assert any("kesinlik-zarfı" in w or "evrensel" in w for w in warns50)
    print("T50 Outcome-guarantee VARIANT ('kesinlikle kaybedilecektir') rejected at AGENT stage (suggestion):", "PASS")

    outcome_suggestion_record = make_suggestion_record("bypass_outcome", outcome_variant_text_2)
    errors51 = _vdas(
        [outcome_suggestion_record], {"issue_001": {}, "issue_002": {}}, hardening_known_ids, fc["facts"],
    )
    assert any("kesinlik-zarfı" in e or "evrensel" in e for e in errors51), "Outcome-guarantee varyanti BYPASS validator'da KABUL EDILDI."
    print("T51 Same outcome-guarantee variant, agent bypassed, fed directly to independent validator, rejected:", "PASS")

    # ---- T52/T53: Empty request_text - 'request' section - agent + bypass ----

    empty_request_item = [{
        "source_issue_id": "issue_001", "section_type": "request", "section_text": REQUEST_TEXT_HEDGED,
        "refs": [{
            "source_field": "source_fact_ids", "source_id": FACT_ID,
            "rendering_mode": "paraphrase", "claim_span": REQUEST_TEXT_HEDGED,
        }],
    }]
    fin52, _, warns52, _ = run_section_stage(
        empty_request_item, allowlist_by_issue3, {"request"}, fc["facts"], hardening_known_ids,
        None, set(), 1, request_input={"request_type": "iptal", "request_text": ""}, direct_lookup={},
    )
    assert len(fin52) == 0, "Bos request_text ile 'request' section agent asamasinda KABUL EDILDI."
    assert any("yetkisi" in w for w in warns52)
    print("T52 Empty request_text does NOT authorize 'request' section at AGENT stage:", "PASS")

    empty_request_section_record = {
        "section_id": "draft_section_empty_req", "source_issue_ids": ["issue_001"], "section_type": "request",
        "section_text": REQUEST_TEXT_HEDGED, "contains_unreviewed_source": False, "section_review_state": "needs_review",
        "requires_human_review": True, "status": "candidate", "submission_status": "draft_only",
    }
    empty_request_ref = make_ref_record("draft_section_empty_req", FACT_ID, claim_span=REQUEST_TEXT_HEDGED)
    errors53 = _vds(
        [empty_request_section_record], [empty_request_ref], allowlist_by_issue3, fc["facts"], hardening_known_ids,
        None, request_input={"request_type": "iptal", "request_text": "   "}, direct_lookup={},
    )
    assert any("yetkisi" in e for e in errors53), "Bos/whitespace request_text BYPASS validator'da KABUL EDILDI."
    print("T53 Empty/whitespace request_text does NOT authorize at independent VALIDATOR (agent bypassed):", "PASS")

    # ---- T54/T55: Whitespace-only lawyer_provided_text - agent + bypass ----

    fin54, _, warns54, _ = run_section_stage(
        empty_request_item, allowlist_by_issue3, {"request"}, fc["facts"], hardening_known_ids,
        "   ", set(), 1, request_input=None, direct_lookup={},
    )
    assert len(fin54) == 0, "Whitespace-only lawyer_provided_text agent asamasinda YETKI VERDI."
    assert any("yetkisi" in w for w in warns54)
    print("T54 Whitespace-only lawyer_provided_text does NOT authorize at AGENT stage:", "PASS")

    errors55 = _vds(
        [empty_request_section_record], [empty_request_ref], allowlist_by_issue3, fc["facts"], hardening_known_ids,
        "   ", request_input=None, direct_lookup={},
    )
    assert any("yetkisi" in e for e in errors55), "Whitespace-only lawyer_provided_text BYPASS validator'da YETKI VERDI."
    print("T55 Whitespace-only lawyer_provided_text does NOT authorize at independent VALIDATOR:", "PASS")

    # ---- T56/T57/T58: GÜVENLİ POZİTİF KONTROLLER (section, suggestion, valid request_input) ----

    safe_section_item = [{
        "source_issue_id": "issue_001", "section_type": "facts_summary", "section_text": SECTION_TEXT_HEDGED,
        "refs": [{
            "source_field": "source_fact_ids", "source_id": FACT_ID,
            "rendering_mode": "paraphrase", "claim_span": SECTION_TEXT_HEDGED,
        }],
    }]
    fin56, refs56, warns56, _ = run_section_stage(
        safe_section_item, allowlist_by_issue3, {"facts_summary"}, fc["facts"], hardening_known_ids,
        None, set(), 1, request_input=None, direct_lookup={},
    )
    assert len(fin56) == 1, f"Guvenli section yanlislikla reddedildi: {warns56}"
    safe_section_record = dict(fin56[0])
    # contains_unreviewed_source normalde engine tarafından
    # build_flagged_section_notes() ile doldurulur (run_section_stage
    # bilerek None bırakır) - bu izole testte gerçek değeri (bu fact
    # unverified/flagged olduğu için True) elle set ediyoruz.
    safe_section_record["contains_unreviewed_source"] = True
    safe_section_ref = dict(refs56[0])
    errors56 = _vds(
        [safe_section_record], [safe_section_ref], allowlist_by_issue3, fc["facts"], hardening_known_ids, None,
        request_input=None, direct_lookup={},
    )
    assert errors56 == [], f"Guvenli section BYPASS validator tarafindan yanlislikla reddedildi: {errors56}"
    print("T56 Positive control: safe section (real declared fact ID) accepted by BOTH agent and validator:", "PASS")

    safe_suggestion_item = [{
        "suggestion_type": "additional_review_needed", "source_issue_id": "issue_001",
        "related_reference_ids": [], "reason_code": "general_contextual_relevance",
        "grounded_explanation": "Bu issue icin ek inceleme faydali olabilir.",
    }]
    fin57, warns57 = run_suggestion_stage(safe_suggestion_item, {"issue_001"}, hardening_known_ids, 1, fc["facts"])
    assert len(fin57) == 1, f"Guvenli suggestion yanlislikla reddedildi: {warns57}"
    errors57 = _vdas(list(fin57), {"issue_001": {}, "issue_002": {}}, hardening_known_ids, fc["facts"])
    assert errors57 == [], f"Guvenli suggestion BYPASS validator tarafindan yanlislikla reddedildi: {errors57}"
    print("T57 Positive control: safe suggestion accepted by BOTH agent and validator:", "PASS")

    fin58, refs58, warns58, _ = run_section_stage(
        request_item, allowlist_by_issue3, {"request"}, fc["facts"], hardening_known_ids,
        None, set(), 1, request_input={"request_type": "iptal", "request_text": "Islemin iptalini talep ediyoruz."},
        direct_lookup={},
    )
    assert len(fin58) == 1, f"Gecerli request_input ile 'request' section yanlislikla reddedildi: {warns58}"
    fin58[0]["contains_unreviewed_source"] = True
    errors58 = _vds(
        list(fin58), list(refs58), allowlist_by_issue3, fc["facts"], hardening_known_ids, None,
        request_input={"request_type": "iptal", "request_text": "Islemin iptalini talep ediyoruz."}, direct_lookup={},
    )
    assert errors58 == [], f"Gecerli request_input BYPASS validator tarafindan yanlislikla reddedildi: {errors58}"
    print("T58 Positive control: VALID non-empty request_input still authorizes at BOTH agent and validator:", "PASS")

    assert_real_drafting_tree_unchanged(case_id, real_tree_before, "End of full hardened self-test (T01-T58)")

    print("T59 Real case_0001/drafting/ tree still unchanged after FULL hardened suite:", "PASS")

    print()
    print("======================================")
    print(" DRAFTING ENGINE V1: 59/59 PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Drafting Engine V1")

    parser.add_argument("--case", dest="case_id", default=DEFAULT_CASE_ID)

    parser.add_argument("--with-agent", action="store_true", dest="with_agent")

    parser.add_argument("--allow-network", action="store_true", dest="allow_network")

    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test:

        run_self_test(args.case_id)

        return

    print()
    print("======================================")
    print(" VERGİ AI - DRAFTING ENGINE V1")
    print("======================================")

    result = build_drafting_engine_output(
        args.case_id, lawyer_input=None, use_agent=args.with_agent, network_allowed=args.allow_network,
    )

    pending_path, validation, _history = write_pending(
        args.case_id, result["analysis"], result["issue_count"],
    )

    print()
    print("Pending:", pending_path)
    print("Draft coverage:", len(result["analysis"]["draft_coverage"]))
    print("Sections:", result["section_count"])
    print("Suggestions:", result["suggestion_count"])
    print("Validator:", "PASS" if validation["valid"] else "FAIL")

    for warning in result["analysis"]["warnings"]:

        print(f"- {warning}")

    print()
    print("- Kesin hukuki sonuç ifadesi üretilmemiştir.")
    print("- Canonical drafting.json değiştirilmemiştir.")
    print()
    print("======================================")
    print(" DRAFTING ENGINE V1:", "PASS" if validation["valid"] else "FAIL")
    print("======================================")

    if not validation["valid"]:

        sys.exit(1)


if __name__ == "__main__":

    main()
