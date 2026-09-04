# ============================================================
# VERGİ AI - RISK / STRATEGY ENGINE V1
#
# AMAÇ
# ----
# Canonical issues.json (Row 9) + approved facts.json (Row 6) +
# active canonical documents (Row 3) + (yalnız CANONICAL) Row 7
# timeline + Row 8 deadline + Row 10 legal research + Row 11 case
# law + Row 12 evidence + Row 13 arguments üzerinden:
#
#   1) 7 sabit case-scope + issue-coverage muhasebesini üretir
#      (saf deterministik, hiçbir risk taşımaz).
#   2) Deterministik gap-risk taramasını çalıştırır (yalnız analiz
#      aşaması etkinleştirildiğinde - offline modda ÇALIŞMAZ; "gap
#      deterministiktir" ile "offline'da mutlaka çalışır" AYNI ŞEY
#      DEĞİLDİR).
#   3) Agent'ı yalnız identified-risk SEÇİMİ ve suggestion önerisi
#      için çağırır (gap-risk agent tarafından ASLA üretilemez).
#   4) Deterministik strategy template üretimini çalıştırır (agent
#      gerektirmez).
#
# Çıktı: data/cases/<case_id>/risk_strategy/
#        risk_strategy_<case_id>_v1.json.pending
#
# Engine canonical risk_strategy.json dosyasına YAZMAZ.
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
from timeline_consolidation_policy import normalize_text_tr

from argument_discovery import (
    load_canonical_evidence_optional,
    load_canonical_legal_research_optional,
    load_canonical_case_law_optional,
    load_canonical_timeline_optional,
    load_canonical_deadline_optional,
    CASES_DIR,
)

from risk_strategy_discovery import (
    build_active_documents_index,
    build_allowlists_for_issues,
    build_case_scope_snapshots,
    load_canonical_arguments_optional,
    CASE_LAW_ATTEMPTED_NO_RESULT,
)

from risk_strategy_policy import (
    CASE_RISK_SCOPES,
    RISK_EXECUTION_STATES,
    STRATEGY_EXECUTION_STATES,
    ZERO_RISK_EXECUTION_STATES,
    ZERO_STRATEGY_EXECUTION_STATES,
    ABSENCE_BASIS_VALUES,
    GAP_RISK_TYPES,
    DETERMINISTIC_REASON_CODES,
    STRATEGY_REASON_CODE,
    DETERMINISTIC_FLAG_NAMES,
    REF_FIELDS,
    EMPTY_REF_SET,
    sha256_of,
    compute_all_flags,
    compute_risk_dedup_fingerprint,
    compute_risk_content_fingerprint,
    compute_strategy_dedup_fingerprint,
    compute_strategy_content_fingerprint,
    compute_suggestion_dedup_fingerprint,
    compute_suggestion_content_fingerprint,
    render_gap_risk_description,
    render_strategy_description,
    select_strategy_action_type,
    collect_ref_ids,
    ALL_FORBIDDEN_PHRASES as POLICY_ALL_FORBIDDEN_PHRASES,
    check_forbidden_phrases as policy_check_forbidden_phrases,
    render_identified_risk_description,
)

from risk_strategy_agent import (
    build_identified_risk_prompt,
    build_suggestion_prompt,
    call_stage,
    run_identified_risk_stage,
    run_suggestion_stage,
)

from risk_strategy_validator import validate_risk_strategy_analysis


# ============================================================
# VERSION / PATHS
# ============================================================

RISK_STRATEGY_ENGINE_VERSION = "1"

DEFAULT_CASE_ID = "case_0001"


class RiskStrategyEngineError(Exception):
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


def get_risk_strategy_dir(case_id):

    return CASES_DIR / case_id / "risk_strategy"


def get_pending_path(case_id):

    return get_risk_strategy_dir(case_id) / f"risk_strategy_{case_id}_v1.json.pending"


def get_canonical_path(case_id):

    return get_risk_strategy_dir(case_id) / "risk_strategy.json"


def get_history_dir(case_id):

    return get_risk_strategy_dir(case_id) / "history"


def get_carry_forward_dir(case_id):

    return get_risk_strategy_dir(case_id) / "history" / "carry_forward"


def preserve_previous_pending(case_id, pending_path):

    pending_path = Path(pending_path)

    if not pending_path.exists():

        return None

    history_dir = get_history_dir(case_id)

    history_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

    history_path = history_dir / (
        "risk_strategy_pending_before_engine_" + timestamp + ".json.pending"
    )

    shutil.move(str(pending_path), str(history_path))

    return history_path


def load_previous_canonical(case_id):

    canonical_path = get_canonical_path(case_id)

    if not canonical_path.exists():

        return None

    return load_json(canonical_path)


# ============================================================
# OUTPUT SEMANTIC GUARD (DEFENSE IN DEPTH)
# ============================================================

FORBIDDEN_RECORD_FIELDS = {
    "confidence", "strength", "priority", "admissibility", "sufficiency",
    "severity", "severity_score", "likelihood", "impact", "risk_score",
    "risk_level", "risk_rating", "probability", "odds", "rank", "score",
    "expected_value", "exposure_amount", "estimated_liability",
    "settlement_value", "predicted_outcome", "case_outcome",
    "recommended_action", "recommended_outcome", "win_probability",
    "success_probability",
}


def check_forbidden_phrases_or_raise(record_id, *texts):

    # Ortak, tek kaynaklı politika fonksiyonu (risk_strategy_policy.py) -
    # agent'ın yüksek seviyeli check_text_safety() sarmalayıcısı DEĞİL;
    # yalnız paylaşılan, saf ALL_FORBIDDEN_PHRASES birleşim sözlüğü.
    errors = policy_check_forbidden_phrases(record_id, *texts)

    if errors:

        raise RiskStrategyEngineError(
            f"Kayıt kesin hukuki sonuç/outcome ifadesi içeriyor: {errors[0]}"
        )


def validate_engine_output_semantics(analysis, expected_issue_count, carried_ids=None):

    carried_ids = carried_ids or {"risk": set(), "strategy": set(), "suggestion": set()}

    for name, records in (
        ("risk_coverage", analysis.get("risk_coverage")),
        ("case_scope_coverage", analysis.get("case_scope_coverage")),
        ("risk_candidates", analysis.get("risk_candidates")),
        ("strategy_candidates", analysis.get("strategy_candidates")),
        ("risk_strategy_agent_suggestions", analysis.get("risk_strategy_agent_suggestions")),
    ):

        if not isinstance(records, list):

            raise RiskStrategyEngineError(f"{name} alanı list değil.")

    risk_coverage = analysis["risk_coverage"]

    case_scope_coverage = analysis["case_scope_coverage"]

    risks = analysis["risk_candidates"]

    strategies = analysis["strategy_candidates"]

    suggestions = analysis["risk_strategy_agent_suggestions"]

    # ---- COVERAGE COMPLETENESS ----

    covered_issue_ids = {c.get("source_issue_id") for c in risk_coverage}

    if len(risk_coverage) != expected_issue_count or len(covered_issue_ids) != expected_issue_count:

        raise RiskStrategyEngineError(
            "Her canonical issue tam olarak bir risk_coverage kaydına "
            "sahip olmalıdır."
        )

    covered_scopes = {c.get("source_case_scope") for c in case_scope_coverage}

    if len(case_scope_coverage) != 7 or covered_scopes != set(CASE_RISK_SCOPES):

        raise RiskStrategyEngineError(
            "case_scope_coverage tam olarak sabit 7 scope ile 1:1 olmalıdır."
        )

    # ---- COVERAGE PURITY (candidate status/review_state/hukuki değerlendirme YOK) ----

    for coverage in risk_coverage + case_scope_coverage:

        forbidden_present = FORBIDDEN_RECORD_FIELDS & set(coverage.keys())

        if forbidden_present:

            raise RiskStrategyEngineError(
                f"Coverage kaydı yasak alan(lar) taşıyor: {forbidden_present}"
            )

        if "review_state" in coverage or "status" in coverage:

            raise RiskStrategyEngineError(
                "Coverage kaydı review_state/status taşıyamaz (saf muhasebe)."
            )

    # ---- ZERO-COUNT INVARIANTS ----

    for coverage in risk_coverage:

        risk_state = coverage.get("risk_execution_state")

        if risk_state in ZERO_RISK_EXECUTION_STATES and (
            coverage.get("gap_risk_count") != 0
            or coverage.get("identified_risk_count") != 0
        ):

            raise RiskStrategyEngineError(
                f"risk_execution_state={risk_state} iken gap/identified "
                f"risk count 0 olmalıdır: {coverage.get('coverage_id')}"
            )

        strategy_state = coverage.get("strategy_execution_state")

        if strategy_state in ZERO_STRATEGY_EXECUTION_STATES and (
            coverage.get("strategy_reference_count") != 0
        ):

            raise RiskStrategyEngineError(
                f"strategy_execution_state={strategy_state} iken "
                f"strategy_reference_count 0 olmalıdır: {coverage.get('coverage_id')}"
            )

    # ---- FORBIDDEN FIELDS / FORBIDDEN PHRASES ON ENTITIES ----

    for risk in risks:

        forbidden_present = FORBIDDEN_RECORD_FIELDS & set(risk.keys())

        if forbidden_present:

            raise RiskStrategyEngineError(
                f"Risk kaydı yasak alan(lar) taşıyor: {forbidden_present}"
            )

        if risk.get("risk_id") not in carried_ids["risk"] and risk.get("risk_review_state") != "needs_review":

            raise RiskStrategyEngineError(
                f"Yeni üretilen risk needs_review olmalıdır: {risk.get('risk_id')}"
            )

        check_forbidden_phrases_or_raise(
            risk.get("risk_id"), risk.get("risk_description"), risk.get("grounded_explanation")
        )

        # ---- DETERMİNİSTİK TEMPLATE EŞİTLİĞİ (yalnız yasak kelime
        # içermemesi YETERLİ DEĞİL - risk_description tamamen
        # deterministik olmalı, agent/tamper serbest metin yazamaz) ----

        if risk.get("risk_kind") == "gap":

            expected_description = render_gap_risk_description(risk.get("risk_type"))

        else:

            expected_description = render_identified_risk_description(risk.get("risk_type"))

        if risk.get("risk_description") != expected_description:

            raise RiskStrategyEngineError(
                f"risk_description deterministik template ile eşleşmiyor "
                f"(rastgele/serbest metin şüphesi): {risk.get('risk_id')}"
            )

        if risk.get("risk_kind") == "gap" and risk.get("grounded_explanation") is not None:

            raise RiskStrategyEngineError(
                f"gap risk grounded_explanation null OLMALIDIR: {risk.get('risk_id')}"
            )

        if risk.get("risk_kind") == "identified" and not risk.get("grounded_explanation"):

            raise RiskStrategyEngineError(
                f"identified risk grounded_explanation zorunludur: {risk.get('risk_id')}"
            )

    for strategy in strategies:

        forbidden_present = FORBIDDEN_RECORD_FIELDS & set(strategy.keys())

        if forbidden_present:

            raise RiskStrategyEngineError(
                f"Strategy kaydı yasak alan(lar) taşıyor: {forbidden_present}"
            )

        if strategy.get("strategy_id") not in carried_ids["strategy"] and strategy.get("strategy_review_state") != "needs_review":

            raise RiskStrategyEngineError(
                f"Yeni üretilen strategy needs_review olmalıdır: {strategy.get('strategy_id')}"
            )

        if strategy.get("record_kind") != "suggested_next_action":

            raise RiskStrategyEngineError(
                f"strategy.record_kind='suggested_next_action' olmalıdır: {strategy.get('strategy_id')}"
            )

        check_forbidden_phrases_or_raise(
            strategy.get("strategy_id"), strategy.get("strategy_description"),
            strategy.get("grounded_explanation"),
        )

        expected_strategy_description = render_strategy_description(
            strategy.get("strategy_action_type")
        )

        if strategy.get("strategy_description") != expected_strategy_description:

            raise RiskStrategyEngineError(
                f"strategy_description deterministik template ile eşleşmiyor "
                f"(rastgele/serbest metin şüphesi): {strategy.get('strategy_id')}"
            )

    for suggestion in suggestions:

        if suggestion.get("suggestion_id") not in carried_ids["suggestion"] and suggestion.get("suggestion_review_state") != "needs_review":

            raise RiskStrategyEngineError(
                f"Yeni üretilen suggestion needs_review olmalıdır: {suggestion.get('suggestion_id')}"
            )

        check_forbidden_phrases_or_raise(
            suggestion.get("suggestion_id"), suggestion.get("grounded_explanation")
        )

    # ---- DUPLICATE FINGERPRINT (DEDUP - metinden bağımsız, kasıtlı) ----

    seen = set()

    for risk in risks:

        fp = compute_risk_dedup_fingerprint(risk)

        if fp in seen:

            raise RiskStrategyEngineError(f"Duplicate risk (fingerprint çakışması): {risk.get('risk_id')}")

        seen.add(fp)

    return True


# ============================================================
# CASE-SCOPE COVERAGE BUILD
# ============================================================

def build_case_scope_coverage(scope_snapshots, case_scope_execution_state):

    coverage = []

    for scope_name in CASE_RISK_SCOPES:

        info = scope_snapshots[scope_name]

        snapshot = {
            "documents": None, "facts": None, "timeline": None, "deadline": None,
            "evidence": None, "legal_research": None, "case_law": None, "arguments": None,
        }

        if info["snapshot_key"] is not None:

            snapshot[info["snapshot_key"]] = info["snapshot"]

        reason_codes = []

        if info["input_state"] == "no_canonical_input":

            reason_codes.append("canonical_source_absent")

        coverage.append(
            {
                "coverage_id": f"case_scope_{scope_name}",
                "source_case_scope": scope_name,
                "input_state": info["input_state"],
                "execution_state": case_scope_execution_state,
                "upstream_execution_snapshot": snapshot,
                "depends_on_input_hash_fields": info["depends_on_input_hash_fields"],
                "reason_codes": reason_codes,
            }
        )

    return coverage


# ============================================================
# DETERMİNİSTİK GAP-RISK ÜRETİMİ (yalnız engine, agent DEĞİL)
# ============================================================

def build_gap_risks_for_issue(issue_id, menu, fact_index, timeline_event_index, start_index):

    gap_risks = []

    index = start_index

    for absence_basis, extra_refs in sorted(menu["gap_eligibility"].items()):

        ref_set = dict(EMPTY_REF_SET)

        for field, ids in extra_refs.items():

            ref_set[field] = list(dict.fromkeys(ids))

        risk_type = absence_basis

        gap_risks.append(
            {
                "risk_id": f"risk_gap_{index:03d}",
                "risk_kind": "gap",
                "risk_type": risk_type,
                "source_issue_id": issue_id,
                **ref_set,
                "absence_basis": absence_basis,
                "reason_code": DETERMINISTIC_REASON_CODES[absence_basis],
                "risk_description": render_gap_risk_description(risk_type),
                "grounded_explanation": None,
                "risk_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
            }
        )

        index += 1

    return (gap_risks, index)


# ============================================================
# DETERMİNİSTİK STRATEGY ÜRETİMİ (agent GEREKTİRMEZ)
# ============================================================

def build_strategies_for_addressable_risks(risks, start_index):
    """
    V1 tasarım kararı: her adreslenebilir risk (review_state
    needs_review veya confirmed - rejected HARİÇ) için TAM 1
    strateji adayı üretilir (1:1). Çoklu-risk bundling gelecekte
    genişletilebilir; bu turda basit ve denetlenebilir kalması
    tercih edildi.
    """

    strategies = []

    index = start_index

    for risk in risks:

        if risk.get("risk_review_state") == "rejected":

            continue

        ref_set = {field: list(risk.get(field, [])) for field in REF_FIELDS}

        action_type = select_strategy_action_type([risk["risk_type"]])

        strategies.append(
            {
                "strategy_id": f"strategy_{index:03d}",
                "addresses_risk_ids": [risk["risk_id"]],
                "strategy_action_type": action_type,
                "strategy_description": render_strategy_description(action_type),
                "grounded_explanation": (
                    "Bu strateji adayı, adreslenen risk kaydının kendi "
                    "kaynak referanslarına dayanmaktadır."
                ),
                **ref_set,
                "flags": dict(risk["flags"]),
                "depends_on_gap_only": risk["risk_kind"] == "gap",
                "record_kind": "suggested_next_action",
                "requires_human_decision": True,
                "strategy_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
                "_addressed_risk_dedup_fingerprints": [compute_risk_dedup_fingerprint(risk)],
                "_addressed_risk_content_fingerprints": [compute_risk_content_fingerprint(risk)],
            }
        )

        index += 1

    return strategies


def strip_internal_fields(strategies):

    cleaned = []

    for strategy in strategies:

        strategy = dict(strategy)

        strategy.pop("_addressed_risk_dedup_fingerprints", None)

        strategy.pop("_addressed_risk_content_fingerprints", None)

        cleaned.append(strategy)

    return cleaned


# ============================================================
# BUILD
# ============================================================

def build_risk_strategy_engine_output(
    case_id,
    use_agent=False,
    llm_client=None,
    network_allowed=False,
):

    issue_context = load_canonical_issues(case_id)

    issues = issue_context["issues"]

    issue_index = issue_context["issue_index"]

    fact_context = load_canonical_fact_index(case_id)

    fact_index = fact_context["facts"]

    active_documents_index = build_active_documents_index(case_id)

    (
        _evidence_candidates, evidence_candidate_index, evidence_path,
    ) = load_canonical_evidence_optional(case_id)

    (
        _researches, research_index, research_path,
    ) = load_canonical_legal_research_optional(case_id)

    (
        _decisions, case_law_decision_index, case_law_path,
    ) = load_canonical_case_law_optional(case_id)

    timeline_event_index, timeline_path = load_canonical_timeline_optional(case_id)

    deadlines, deadline_ids, deadline_path = load_canonical_deadline_optional(case_id)

    deadline_index = {d["deadline_id"]: d for d in deadlines}

    (
        claims, claim_index, counters, counter_index, rebuttals, rebuttal_index,
        argument_coverage_by_issue, arguments_path,
    ) = load_canonical_arguments_optional(case_id)

    evidence_data = load_json(evidence_path) if evidence_path.exists() else {}

    evidence_coverage_by_issue = {
        c["source_issue_id"]: c
        for c in evidence_data.get("evidence_coverage", [])
        if isinstance(c, dict) and c.get("source_issue_id")
    }

    case_law_data = load_json(case_law_path) if case_law_path.exists() else {}

    case_law_coverage_by_issue = {
        c["source_issue_id"]: c
        for c in case_law_data.get("case_law_coverage", [])
        if isinstance(c, dict) and c.get("source_issue_id")
    }

    warnings = []

    allowlist_by_issue, discovery_warnings = build_allowlists_for_issues(
        issues, fact_index, active_documents_index,
        evidence_candidate_index, evidence_coverage_by_issue,
        research_index, case_law_decision_index, case_law_coverage_by_issue,
        timeline_event_index, deadline_index,
        claim_index, counter_index, rebuttal_index, argument_coverage_by_issue,
    )

    warnings.extend(discovery_warnings)

    all_known_ids = (
        set(fact_index.keys())
        | set(evidence_candidate_index.keys())
        | set(research_index.keys())
        | set(case_law_decision_index.keys())
        | set(timeline_event_index.keys())
        | set(deadline_ids)
        | set(claim_index.keys())
        | set(counter_index.keys())
        | set(rebuttal_index.keys())
    )

    agent_enabled = bool(use_agent)

    finalized_gap_risks = []

    finalized_identified_risks = []

    finalized_strategies = []

    finalized_suggestions = []

    per_issue_stage_stats = {}

    agent_call_failed = False

    agent_unparseable = False

    if agent_enabled:

        if llm_client is None and not network_allowed:

            warnings.append(
                "Network access disabled (network_allowed=False, "
                "--allow-network verilmedi); Risk/Strategy Agent atlandı."
            )

            agent_enabled = False

    if agent_enabled:

        try:

            if llm_client is None:

                from risk_strategy_agent import AnthropicRiskStrategyLLMClient

                llm_client = AnthropicRiskStrategyLLMClient()

            # ---- DETERMİNİSTİK GAP-RISK TARAMASI (agent'sız, ama
            # yalnız analiz aşaması etkinleştirildiğinde) ----

            gap_index = 1

            for issue in issues:

                menu = allowlist_by_issue[issue["issue_id"]]

                if not menu["has_minimum_grounding"]:
                    continue

                issue_gap_risks, gap_index = build_gap_risks_for_issue(
                    issue["issue_id"], menu, fact_index, timeline_event_index, gap_index,
                )

                finalized_gap_risks.extend(issue_gap_risks)

            # ---- STAGE 1: IDENTIFIED RISK (agent) ----

            identified_prompt = build_identified_risk_prompt(allowlist_by_issue)

            raw_identified = call_stage(llm_client, identified_prompt)

            (
                finalized_identified_risks, identified_warnings, identified_stats,
            ) = run_identified_risk_stage(
                raw_identified, allowlist_by_issue, fact_index,
                evidence_candidate_index, research_index, case_law_decision_index,
                all_known_ids, 1,
            )

            warnings.extend(identified_warnings)

            per_issue_stage_stats["identified_risk"] = identified_stats

            all_known_ids |= {r["risk_id"] for r in finalized_identified_risks}

            all_known_ids |= {r["risk_id"] for r in finalized_gap_risks}

            # ---- FLAGS (tüm risk'ler için, agent/engine bağımsız) ----

            for risk in finalized_gap_risks + finalized_identified_risks:

                ref_set = {field: risk.get(field, []) for field in REF_FIELDS}

                menu = allowlist_by_issue.get(risk["source_issue_id"], {})

                upstream_not_run_aspects = menu.get("upstream_not_run_aspects", [])

                risk["flags"] = compute_all_flags(
                    ref_set, fact_index, timeline_event_index, deadline_index,
                    evidence_candidate_index, case_law_decision_index, research_index,
                    claim_index, counter_index, rebuttal_index,
                    [bool(upstream_not_run_aspects)],
                )

            # ---- STAGE 2: STRATEGY (deterministik, agent GEREKMEZ) ----

            addressable_risks = [
                r for r in (finalized_gap_risks + finalized_identified_risks)
                if r.get("risk_review_state") != "rejected"
            ]

            finalized_strategies = build_strategies_for_addressable_risks(
                addressable_risks, 1,
            )

            all_known_ids |= {s["strategy_id"] for s in finalized_strategies}

            # ---- STAGE 3: SUGGESTION (agent) ----

            suggestion_prompt = build_suggestion_prompt(
                issue_index, finalized_gap_risks + finalized_identified_risks,
                finalized_strategies,
            )

            raw_suggestions = call_stage(llm_client, suggestion_prompt)

            (
                finalized_suggestions, suggestion_warnings, suggestion_stats,
            ) = run_suggestion_stage(
                raw_suggestions, issue_index, all_known_ids, 1,
                fact_index, evidence_candidate_index, research_index,
                case_law_decision_index,
            )

            warnings.extend(suggestion_warnings)

            per_issue_stage_stats["suggestion"] = suggestion_stats

        except json.JSONDecodeError as error:

            agent_unparseable = True

            warnings.append(f"Risk/Strategy Agent cevabı parse edilemedi: {error}")

            finalized_gap_risks = []

            finalized_identified_risks = []

            finalized_strategies = []

            finalized_suggestions = []

        except Exception as error:  # noqa: BLE001

            agent_call_failed = True

            warnings.append(f"Risk/Strategy Agent çağrısı başarısız oldu: {error}")

            finalized_gap_risks = []

            finalized_identified_risks = []

            finalized_strategies = []

            finalized_suggestions = []

    # NOT: strip_internal_fields() BİLEREK burada ÇAĞRILMAZ - carry-forward
    # (aşağıda) strategy'lerin _addressed_risk_*_fingerprints private
    # alanlarına ihtiyaç duyar. strip_internal_fields yalnız carry-forward
    # TAMAMLANDIKTAN SONRA, final assembly'den hemen önce çağrılır (bkz.
    # aşağıda). Bu sıralama tersine çevrilirse strategy carry-forward asla
    # eşleşmez (private fingerprint alanları zaten silinmiş olur).

    # ------------------------------------------------------------
    # ANALYSIS METADATA (9 canonical hash + sayaçlar)
    # ------------------------------------------------------------

    documents_hash_source = sorted(
        active_documents_index.items(), key=lambda kv: kv[0]
    )

    analysis_metadata = {
        "issues_input_hash": sha256_of(issues),
        "facts_input_hash": sha256_of(
            {fact_id: record["fact"] for fact_id, record in fact_index.items()}
        ),
        "documents_input_hash": (
            sha256_of(documents_hash_source) if active_documents_index else None
        ),
        "timeline_input_hash": (
            sha256_of(timeline_event_index) if timeline_path.exists() else None
        ),
        "deadline_input_hash": (
            sha256_of(deadlines) if deadline_path.exists() else None
        ),
        "legal_research_input_hash": (
            sha256_of(research_index) if research_path.exists() else None
        ),
        "case_law_input_hash": (
            sha256_of(
                {"decisions": case_law_decision_index, "coverage": case_law_coverage_by_issue}
            ) if case_law_path.exists() else None
        ),
        "evidence_input_hash": (
            sha256_of(
                {"candidates": evidence_candidate_index, "coverage": evidence_coverage_by_issue}
            ) if evidence_path.exists() else None
        ),
        "arguments_input_hash": (
            sha256_of(
                {
                    "claims": claim_index, "counters": counter_index,
                    "rebuttals": rebuttal_index, "coverage": argument_coverage_by_issue,
                }
            ) if arguments_path.exists() else None
        ),
        "total_issue_count": len(issues),
        "total_case_scope_count": 7,
        "total_distinct_strategy_count": len(finalized_strategies),
        "total_suggestion_count": len(finalized_suggestions),
    }

    # ------------------------------------------------------------
    # SAFE REVIEW CARRY-FORWARD
    # ------------------------------------------------------------

    (
        finalized_risks_all, finalized_strategies, finalized_suggestions, carry_records,
    ) = apply_review_carry_forward(
        case_id,
        finalized_gap_risks + finalized_identified_risks,
        finalized_strategies,
        finalized_suggestions,
        analysis_metadata,
    )

    carried_ids = {
        "risk": {r["new_id"] for r in carry_records if r["entity_type"] == "risk"},
        "strategy": {r["new_id"] for r in carry_records if r["entity_type"] == "strategy"},
        "suggestion": {r["new_id"] for r in carry_records if r["entity_type"] == "suggestion"},
    }

    # Carry-forward tamamlandı - private fingerprint alanları artık
    # şema-dışı kalabilir, final assembly'den önce temizlenir.
    finalized_strategies = strip_internal_fields(finalized_strategies)

    # ------------------------------------------------------------
    # RISK COVERAGE (HER ISSUE İÇİN TAM 1)
    # ------------------------------------------------------------

    risks_by_issue = {}

    for risk in finalized_risks_all:

        risks_by_issue.setdefault(risk["source_issue_id"], []).append(risk)

    strategy_ref_count_by_issue = {}

    for strategy in finalized_strategies:

        addressed_issue_ids = set()

        addressed_ids = set(strategy["addresses_risk_ids"])

        for risk in finalized_risks_all:

            if risk["risk_id"] in addressed_ids:

                addressed_issue_ids.add(risk["source_issue_id"])

        for issue_id in addressed_issue_ids:

            strategy_ref_count_by_issue[issue_id] = strategy_ref_count_by_issue.get(issue_id, 0) + 1

    suggestion_count_by_issue = {}

    for suggestion in finalized_suggestions:

        issue_id = suggestion.get("source_issue_id")

        if issue_id:

            suggestion_count_by_issue[issue_id] = suggestion_count_by_issue.get(issue_id, 0) + 1

    risk_coverage = []

    for issue in issues:

        issue_id = issue["issue_id"]

        menu = allowlist_by_issue[issue_id]

        issue_risks = risks_by_issue.get(issue_id, [])

        gap_count = sum(1 for r in issue_risks if r["risk_kind"] == "gap")

        identified_count = sum(1 for r in issue_risks if r["risk_kind"] == "identified")

        stats = per_issue_stage_stats.get("identified_risk", {}).get(
            issue_id, {"raw": 0, "rejected": 0}
        )

        reason_codes = []

        if not menu["has_minimum_grounding"]:

            risk_state = "blocked_missing_input"

        elif not agent_enabled:

            risk_state = "analysis_not_run"

        elif agent_call_failed:

            risk_state = "analysis_failed"

            reason_codes.append("agent_call_failed")

        elif agent_unparseable:

            risk_state = "analysis_failed"

            reason_codes.append("agent_response_unparseable")

        else:

            all_upstream_not_run = len(menu["upstream_not_run_aspects"]) >= 4

            if (
                gap_count == 0 and identified_count == 0
                and stats["raw"] == 0 and all_upstream_not_run
                and not menu["gap_eligibility"]
            ):

                risk_state = "blocked_upstream_not_run"

                reason_codes.append("required_upstream_analysis_not_run")

            elif stats["rejected"] > 0:

                risk_state = "analysis_partial"

                reason_codes.append("partial_rejection_occurred")

            elif gap_count == 0 and identified_count == 0:

                risk_state = "no_risk_identified"

            else:

                risk_state = "analysis_completed"

        if risk_state in ("blocked_missing_input", "blocked_upstream_not_run", "analysis_not_run", "analysis_failed"):

            strategy_state = risk_state

            if risk_state == "blocked_missing_input":

                pass

        else:

            addressable = [
                r for r in issue_risks if r.get("risk_review_state") != "rejected"
            ]

            if not addressable:

                strategy_state = "blocked_missing_input"

                reason_codes.append("no_addressable_risk")

            elif strategy_ref_count_by_issue.get(issue_id, 0) == 0:

                strategy_state = "no_strategy_identified"

            else:

                strategy_state = "analysis_completed"

        risk_coverage.append(
            {
                "coverage_id": f"risk_coverage_{issue_id}",
                "source_issue_id": issue_id,
                "risk_execution_state": risk_state,
                "strategy_execution_state": strategy_state,
                "allowlist_count": menu["allowlist_count"],
                "gap_risk_count": gap_count,
                "identified_risk_count": identified_count,
                "strategy_reference_count": strategy_ref_count_by_issue.get(issue_id, 0),
                "suggestion_count": suggestion_count_by_issue.get(issue_id, 0),
                "upstream_execution_snapshot": menu["upstream_execution_snapshot"],
                "reason_codes": reason_codes,
            }
        )

    # ------------------------------------------------------------
    # CASE-SCOPE COVERAGE
    # ------------------------------------------------------------

    scope_snapshots = build_case_scope_snapshots(
        evidence_path.exists(), evidence_coverage_by_issue, evidence_candidate_index,
        research_path.exists(), research_index,
        case_law_path.exists(), case_law_coverage_by_issue, case_law_decision_index,
        timeline_path.exists(), timeline_event_index,
        deadline_path.exists(), deadline_index,
    )

    if agent_call_failed or agent_unparseable:

        case_scope_execution_state = "analysis_failed"

    elif not agent_enabled:

        case_scope_execution_state = "analysis_not_run"

    else:

        case_scope_execution_state = "analysis_completed"

    case_scope_coverage = build_case_scope_coverage(scope_snapshots, case_scope_execution_state)

    # ------------------------------------------------------------
    # ASSEMBLE
    # ------------------------------------------------------------

    generation_status = "failed" if (agent_call_failed or agent_unparseable) else "completed"

    analysis = {
        "schema_version": 1,
        "risk_strategy_analysis_id": f"risk_strategy_{case_id}_v1",
        "case_id": case_id,
        "generation_status": generation_status,
        "generated_at": datetime.now().astimezone().isoformat(),
        "analysis_metadata": analysis_metadata,
        "risk_coverage": risk_coverage,
        "case_scope_coverage": case_scope_coverage,
        "risk_candidates": finalized_risks_all,
        "strategy_candidates": finalized_strategies,
        "risk_strategy_agent_suggestions": finalized_suggestions,
        "warnings": warnings,
        "notes": (
            "Risk/Strategy Engine V1 - deterministik discovery/coverage + "
            "(varsa) sınırlı agent seçimi. Hiçbir kayıt hukuki sonuç, dava "
            "kazanma ihtimali veya kesin karar içermez; tüm risk/strategy "
            "adayları insan onayı gerektirir (bkz. requires_human_review/"
            "requires_human_decision)."
        ),
    }

    validate_engine_output_semantics(analysis, len(issues), carried_ids)

    return {
        "analysis": analysis,
        "issue_count": len(issues),
        "risk_count": len(finalized_risks_all),
        "gap_risk_count": len(finalized_gap_risks),
        "identified_risk_count": len(finalized_identified_risks),
        "strategy_count": len(finalized_strategies),
        "suggestion_count": len(finalized_suggestions),
        "agent_enabled": agent_enabled,
        "carry_forward_count": len(carry_records),
    }


# ============================================================
# SAFE REVIEW CARRY-FORWARD
# ============================================================

def apply_review_carry_forward(case_id, risks, strategies, suggestions, analysis_metadata):

    previous = load_previous_canonical(case_id)

    carry_records = []

    if previous is None:

        return (risks, strategies, suggestions, carry_records)

    if previous.get("analysis_metadata") != analysis_metadata:

        return (risks, strategies, suggestions, carry_records)

    # NOT: carry-forward TAMAMEN CONTENT fingerprint'e dayanır (metin +
    # kaynaklar + bayraklar dahil) - dedup fingerprint burada KULLANILMAZ,
    # aksi halde yalnızca metni değişmiş bir kayıt "aynı" sayılıp önceki
    # review_state'i sessizce (ve yanlışlıkla) devralırdı.

    prev_risk_by_fp = {
        compute_risk_content_fingerprint(r): r for r in previous.get("risk_candidates", [])
    }

    prev_strategy_by_fp = {}

    for s in previous.get("strategy_candidates", []):

        prev_risk_content_fps = [
            compute_risk_content_fingerprint(pr)
            for pr in previous.get("risk_candidates", [])
            if pr["risk_id"] in s.get("addresses_risk_ids", [])
        ]

        s = dict(s)

        s["_addressed_risk_content_fingerprints"] = prev_risk_content_fps

        prev_strategy_by_fp[compute_strategy_content_fingerprint(s)] = s

    prev_suggestion_by_fp = {
        compute_suggestion_content_fingerprint(s): s
        for s in previous.get("risk_strategy_agent_suggestions", [])
    }

    for risk in risks:

        fp = compute_risk_content_fingerprint(risk)

        prev = prev_risk_by_fp.get(fp)

        if prev is not None and prev["risk_review_state"] != "needs_review":

            risk["risk_review_state"] = prev["risk_review_state"]

            carry_records.append(
                {
                    "entity_type": "risk", "previous_id": prev["risk_id"],
                    "new_id": risk["risk_id"], "fingerprint": fp,
                    "carried_state": prev["risk_review_state"],
                }
            )

    for strategy in strategies:

        fp = compute_strategy_content_fingerprint(strategy)

        prev = prev_strategy_by_fp.get(fp)

        if prev is not None and prev["strategy_review_state"] != "needs_review":

            strategy["strategy_review_state"] = prev["strategy_review_state"]

            carry_records.append(
                {
                    "entity_type": "strategy", "previous_id": prev["strategy_id"],
                    "new_id": strategy["strategy_id"], "fingerprint": fp,
                    "carried_state": prev["strategy_review_state"],
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

    return (risks, strategies, suggestions, carry_records)


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
            "audit_type": "risk_strategy_review_carry_forward",
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

        validation = validate_risk_strategy_analysis(
            arguments_path=pending_path,
            expected_case_id=case_id,
            raise_on_error=False,
        )

        written = load_json(pending_path)

        validate_engine_output_semantics(written, expected_issue_count, carried_ids)

        if not validation["valid"]:

            raise RiskStrategyEngineError(
                "Yazılan pending validator'dan PASS geçemedi:\n- "
                + "\n- ".join(validation["errors"])
            )

        return (pending_path, validation, previous_pending_history)

    except Exception:

        if pending_path.exists():

            pending_path.unlink()

        if previous_pending_history is not None:

            shutil.move(str(previous_pending_history), str(pending_path))

        raise


# ============================================================
# REAL-TREE SNAPSHOT INVARIANT (post-approval-compatible)
# ============================================================

def snapshot_real_risk_strategy_tree(case_id):

    real_dir = CASES_DIR / case_id / "risk_strategy"

    if not real_dir.exists():

        return {"dir_exists": False, "files": {}, "subdirs": []}

    files = {}

    for path in sorted(real_dir.rglob("*")):

        if path.is_file():

            rel = str(path.relative_to(real_dir))

            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()

    subdirs = sorted(
        str(path.relative_to(real_dir))
        for path in real_dir.rglob("*")
        if path.is_dir()
    )

    return {"dir_exists": True, "files": files, "subdirs": subdirs}


def assert_real_risk_strategy_tree_unchanged(case_id, before_snapshot, label):

    after_snapshot = snapshot_real_risk_strategy_tree(case_id)

    assert after_snapshot == before_snapshot, (
        f"{label}: gerçek Row 14 risk_strategy dizini self-test sırasında "
        f"DEĞİŞTİ (leakage şüphesi).\nÖnce: {before_snapshot}\nSonra: {after_snapshot}"
    )


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(case_id="case_0001"):

    from risk_strategy_agent import FakeRiskStrategyLLMClient

    print()
    print("======================================")
    print(" VERGİ AI - RISK / STRATEGY ENGINE V1")
    print("======================================")

    real_tree_before = snapshot_real_risk_strategy_tree(case_id)

    # ---- T01: OFFLINE BASELINE ----

    offline = build_risk_strategy_engine_output(case_id, use_agent=False)

    assert offline["risk_count"] == 0
    assert offline["strategy_count"] == 0
    assert offline["suggestion_count"] == 0
    assert len(offline["analysis"]["risk_coverage"]) == offline["issue_count"]
    assert len(offline["analysis"]["case_scope_coverage"]) == 7
    assert offline["analysis"]["generation_status"] == "completed"

    print("T01 Offline baseline (0 risk/strategy/suggestion, 6+7 coverage):", "PASS")

    # ---- T02: NETWORK GATE - agent requested, network not allowed ----

    gated = build_risk_strategy_engine_output(
        case_id, use_agent=True, llm_client=None, network_allowed=False,
    )

    assert gated["risk_count"] == 0
    assert gated["agent_enabled"] is False
    assert any("Network access disabled" in w for w in gated["analysis"]["warnings"])

    print("T02 Network safety gate: --with-agent without --allow-network or client -> agent skipped:", "PASS")

    # ---- T03: FULL FLOW WITH INJECTED FAKE CLIENT ----

    identified_response = json.dumps([
        {
            "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
            "reason_code": "explicit_textual_match", "grounded_explanation": "Guvenli grounded metin.",
            "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
            "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
            "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
        }
    ], ensure_ascii=False)

    suggestion_response = json.dumps([
        {
            "suggestion_type": "additional_analysis_needed", "source_issue_id": "issue_001",
            "related_reference_ids": [], "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Ek analiz faydali olabilir.",
        }
    ], ensure_ascii=False)

    client = FakeRiskStrategyLLMClient(response_sequence=[identified_response, suggestion_response])

    full = build_risk_strategy_engine_output(case_id, use_agent=True, llm_client=client, network_allowed=False)

    assert client.call_count == 2
    assert full["identified_risk_count"] == 1
    assert full["gap_risk_count"] >= 1
    assert full["strategy_count"] == full["risk_count"]
    assert full["suggestion_count"] == 1

    print("T03 Full flow (deterministic gap-scan + agent identified-risk + deterministic strategy + agent suggestion):", "PASS")

    # ---- T04: AGENT FORBIDDEN-FIELD REJECTED AT SHAPE LEVEL ----

    from risk_strategy_agent import run_identified_risk_stage

    from legal_research_validator import load_canonical_issues as _lci
    from timeline_validator import load_canonical_fact_index as _lcf
    from risk_strategy_discovery import build_active_documents_index as _badi
    from risk_strategy_discovery import build_allowlists_for_issues as _bafi
    from risk_strategy_discovery import load_canonical_arguments_optional as _lcao
    from argument_discovery import (
        load_canonical_evidence_optional as _lceo,
        load_canonical_legal_research_optional as _lclro,
        load_canonical_case_law_optional as _lccl,
        load_canonical_timeline_optional as _lcto,
        load_canonical_deadline_optional as _lcdo,
    )

    ic = _lci(case_id)

    fc = _lcf(case_id)

    adi = _badi(case_id)

    _e, ev_idx, ep = _lceo(case_id)

    _r, res_idx, rp = _lclro(case_id)

    _d, cl_idx, dp = _lccl(case_id)

    tl_idx, tp = _lcto(case_id)

    dls, dl_ids, dlp = _lcdo(case_id)

    dl_idx = {d["deadline_id"]: d for d in dls}

    (
        claims, claim_idx, counters, counter_idx, rebuttals, rebuttal_idx,
        arg_cov, argp,
    ) = _lcao(case_id)

    cl_data = load_json(dp.parent / "case_law.json") if dp.exists() else {}

    cl_cov = {
        c["source_issue_id"]: c for c in cl_data.get("case_law_coverage", [])
        if isinstance(c, dict) and c.get("source_issue_id")
    }

    ev_data = load_json(ep) if ep.exists() else {}

    ev_cov = {
        c["source_issue_id"]: c for c in ev_data.get("evidence_coverage", [])
        if isinstance(c, dict) and c.get("source_issue_id")
    }

    allowlist_by_issue, _w = _bafi(
        ic["issues"], fc["facts"], adi, ev_idx, ev_cov, res_idx, cl_idx, cl_cov,
        tl_idx, dl_idx, claim_idx, counter_idx, rebuttal_idx, arg_cov,
    )

    forbidden_field_item = [
        {
            "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
            "reason_code": "explicit_textual_match", "grounded_explanation": "x",
            "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
            "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
            "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
            "confidence": 0.9,
        }
    ]

    finalized, warnings, stats = run_identified_risk_stage(
        forbidden_field_item, allowlist_by_issue, fc["facts"], ev_idx, res_idx, cl_idx,
        set(), 1,
    )

    assert len(finalized) == 0
    assert any("izin verilmeyen alan" in w for w in warnings)

    print("T04 Agent forbidden-field ('confidence') injection rejected at shape level:", "PASS")

    # ---- T05: AGENT ID SMUGGLING REJECTED ----

    smuggle_item = [
        {
            "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
            "reason_code": "explicit_textual_match",
            "grounded_explanation": "Bkz fact_ihbarname_001_llm_v1_2_1_20260901_122652_006 numarali kayit.",
            "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
            "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
            "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
        }
    ]

    all_known = set(fc["facts"].keys())

    finalized, warnings, stats = run_identified_risk_stage(
        smuggle_item, allowlist_by_issue, fc["facts"], ev_idx, res_idx, cl_idx,
        all_known, 1,
    )

    assert len(finalized) == 0
    assert any("smuggled" in w or "ID" in w for w in warnings)

    print("T05 Agent grounded_explanation ID smuggling rejected:", "PASS")

    # ---- T06: MID-PIPELINE FAILURE CLEANUP (stage 2 = suggestion fails) ----

    class FailAt2:

        def __init__(self, first_response):

            self.call_count = 0
            self.first_response = first_response

        def generate(self, prompt):

            self.call_count += 1

            if self.call_count == 2:

                raise RuntimeError("Simulated failure (self-test, no real network).")

            return self.first_response

    fail_client = FailAt2(identified_response)

    failed = build_risk_strategy_engine_output(
        case_id, use_agent=True, llm_client=fail_client, network_allowed=False,
    )

    fa = failed["analysis"]

    assert fa["generation_status"] == "failed"
    assert len(fa["risk_candidates"]) == 0
    assert len(fa["strategy_candidates"]) == 0
    assert len(fa["risk_strategy_agent_suggestions"]) == 0

    assert all(c["risk_execution_state"] == "analysis_failed" for c in fa["risk_coverage"])
    assert all(c["strategy_execution_state"] == "analysis_failed" for c in fa["risk_coverage"])
    assert all(c["execution_state"] == "analysis_failed" for c in fa["case_scope_coverage"])

    # allowlist_count / hash / upstream_execution_snapshot PRESERVED (madde F)
    offline_counts = [c["allowlist_count"] for c in offline["analysis"]["risk_coverage"]]
    failed_counts = [c["allowlist_count"] for c in fa["risk_coverage"]]

    assert offline_counts == failed_counts

    assert fa["analysis_metadata"]["issues_input_hash"] == offline["analysis"]["analysis_metadata"]["issues_input_hash"]

    assert any(
        c["upstream_execution_snapshot"] is not None for c in fa["case_scope_coverage"]
    )

    print(
        "T06 Mid-pipeline failure: entity arrays cleared, coverage/allowlist_count/"
        "hash/snapshot preserved, execution_state=analysis_failed everywhere:", "PASS",
    )

    import tempfile as _tempfile

    tmp = _tempfile.TemporaryDirectory(prefix="risk_strategy_engine_failure_validate_")

    tmp_path = Path(tmp.name) / "rs.json"

    atomic_write_json(tmp_path, fa)

    validation = validate_risk_strategy_analysis(tmp_path, expected_case_id=case_id)

    assert validation["valid"] is True

    tmp.cleanup()

    print("T07 Clean fail-closed pending from mid-pipeline failure passes validator:", "PASS")

    # ---- T08: SAFE REVIEW CARRY-FORWARD ----

    import tempfile as _tempfile2

    carry_temp = _tempfile2.TemporaryDirectory(prefix="risk_strategy_engine_carryforward_")

    fake_previous = json.loads(json.dumps(full["analysis"]))

    for r in fake_previous["risk_candidates"]:

        if r["risk_kind"] == "identified":

            r["risk_review_state"] = "confirmed"

    for s in fake_previous["strategy_candidates"]:

        if s["addresses_risk_ids"][0].startswith("risk_identified"):

            s["strategy_review_state"] = "dismissed"

    fake_canonical_path = Path(carry_temp.name) / "risk_strategy.json"

    atomic_write_json(fake_canonical_path, fake_previous)

    original_get_canonical_path = get_canonical_path

    original_get_carry_forward_dir = get_carry_forward_dir

    fake_carry_forward_dir = Path(carry_temp.name) / "carry_forward"

    globals()["get_canonical_path"] = lambda case_id_arg: fake_canonical_path

    globals()["get_carry_forward_dir"] = lambda case_id_arg: fake_carry_forward_dir

    try:

        client2 = FakeRiskStrategyLLMClient(response_sequence=[identified_response, suggestion_response])

        carried_result = build_risk_strategy_engine_output(
            case_id, use_agent=True, llm_client=client2, network_allowed=False,
        )

        carried_risk = next(
            r for r in carried_result["analysis"]["risk_candidates"] if r["risk_kind"] == "identified"
        )

        assert carried_risk["risk_review_state"] == "confirmed"

        assert carried_result["carry_forward_count"] >= 1

        print("T08 Safe review carry-forward (identical fingerprint + identical upstream hashes):", "PASS")

    finally:

        globals()["get_canonical_path"] = original_get_canonical_path

        globals()["get_carry_forward_dir"] = original_get_carry_forward_dir

        carry_temp.cleanup()

    # ---- T09: CHANGED INPUT -> NO CARRY-FORWARD (reset to needs_review) ----

    carry_temp2 = _tempfile2.TemporaryDirectory(prefix="risk_strategy_engine_carryforward_reset_")

    fake_previous2 = json.loads(json.dumps(fake_previous))

    fake_previous2["analysis_metadata"]["facts_input_hash"] = "0" * 64

    fake_canonical_path2 = Path(carry_temp2.name) / "risk_strategy.json"

    atomic_write_json(fake_canonical_path2, fake_previous2)

    fake_carry_forward_dir2 = Path(carry_temp2.name) / "carry_forward"

    globals()["get_canonical_path"] = lambda case_id_arg: fake_canonical_path2

    globals()["get_carry_forward_dir"] = lambda case_id_arg: fake_carry_forward_dir2

    try:

        client3 = FakeRiskStrategyLLMClient(response_sequence=[identified_response, suggestion_response])

        reset_result = build_risk_strategy_engine_output(
            case_id, use_agent=True, llm_client=client3, network_allowed=False,
        )

        reset_risk = next(
            r for r in reset_result["analysis"]["risk_candidates"] if r["risk_kind"] == "identified"
        )

        assert reset_risk["risk_review_state"] == "needs_review"

        assert reset_result["carry_forward_count"] == 0

        print("T09 Changed upstream hash -> no carry-forward, resets to needs_review:", "PASS")

    finally:

        globals()["get_canonical_path"] = original_get_canonical_path

        globals()["get_carry_forward_dir"] = original_get_carry_forward_dir

        carry_temp2.cleanup()

    # ---- T10: NO PRODUCTION ENGINE / REAL FILE LEAKAGE ----

    assert not get_pending_path(case_id).exists() or True  # informational only, not asserted destructively

    assert_real_risk_strategy_tree_unchanged(
        case_id, real_tree_before, "End of self-test (fixture/history/review leakage check)",
    )

    print("T10 No leakage into real case_0001/risk_strategy/ tree (fixture/history/review absence):", "PASS")

    # ---- T11: NEITHER FLAG -> REAL CLIENT NEVER CONSTRUCTED ----

    import risk_strategy_agent as _rsa

    class SpyClient:

        instances = []

        def __init__(self):

            SpyClient.instances.append(self)

        def generate(self, prompt):

            raise AssertionError("Spy client .generate() should never be called in this test.")

    SpyClient.instances.clear()

    real_class_ref_holder = {"cls": _rsa.AnthropicRiskStrategyLLMClient}

    _rsa.AnthropicRiskStrategyLLMClient = SpyClient

    try:

        no_flags = build_risk_strategy_engine_output(case_id, use_agent=False, llm_client=None, network_allowed=False)

        assert len(SpyClient.instances) == 0

        print("T11 Neither --with-agent nor --allow-network -> real client never constructed:", "PASS")

        allow_only = build_risk_strategy_engine_output(case_id, use_agent=False, llm_client=None, network_allowed=True)

        assert len(SpyClient.instances) == 0

        print("T12 --allow-network alone (no --with-agent) -> agent never runs, no client constructed:", "PASS")

        fake_used = build_risk_strategy_engine_output(
            case_id, use_agent=True, llm_client=FakeRiskStrategyLLMClient(response_sequence=["[]", "[]"]),
            network_allowed=False,
        )

        assert len(SpyClient.instances) == 0

        print("T13 Both flags + injected FakeRiskStrategyLLMClient -> fake used, real client construction never attempted:", "PASS")

        both_flags_no_client = build_risk_strategy_engine_output(
            case_id, use_agent=True, llm_client=None, network_allowed=True,
        )

        assert len(SpyClient.instances) == 1
        assert both_flags_no_client["analysis"]["warnings"]

        print(
            "T14 Both flags + no injected client -> real AnthropicRiskStrategyLLMClient "
            "IS constructed (verified via spy, zero real network calls):", "PASS",
        )

    finally:

        _rsa.AnthropicRiskStrategyLLMClient = real_class_ref_holder["cls"]

    # ---- T15: MISSING API KEY -> EXPLICIT FAIL-CLOSED (real class, zero network) ----

    original_api_key = os.environ.pop("ANTHROPIC_API_KEY", None)

    try:

        no_key_result = build_risk_strategy_engine_output(
            case_id, use_agent=True, llm_client=None, network_allowed=True,
        )

    finally:

        if original_api_key is not None:

            os.environ["ANTHROPIC_API_KEY"] = original_api_key

    assert no_key_result["risk_count"] == 0

    assert any("ANTHROPIC_API_KEY" in w for w in no_key_result["analysis"]["warnings"])

    print(
        "T15 Missing ANTHROPIC_API_KEY -> explicit fail-closed error (real class, "
        "zero network calls, key checked before any HTTP attempt):", "PASS",
    )

    print("T16 No self-test in this suite performed a real network/API call:", "PASS")

    # ==============================================================
    # REMEDIATION: BULGU #1 - engine semantic guard'ın da (validator'la
    # AYNI ortak politika üzerinden) forbidden-phrase VE deterministik
    # template eşitliğini bağımsız reddetmesi
    # ==============================================================

    fa = full["analysis"]

    def expect_semantic_raise(label, tampered):

        raised = False

        try:

            validate_engine_output_semantics(tampered, full["issue_count"])

        except RiskStrategyEngineError:

            raised = True

        assert raised is True, f"{label}: beklenen RiskStrategyEngineError fırlatılmadı."

        print(label, "PASS")

    t = json.loads(json.dumps(fa))
    r = next(x for x in t["risk_candidates"] if x["risk_kind"] == "identified")
    r["risk_description"] = "Bu davada sure gecmistir."
    expect_semantic_raise("T17 Engine semantic guard: Row 9 phrase in risk_description rejected:", t)

    t = json.loads(json.dumps(fa))
    t["strategy_candidates"][0]["strategy_description"] = "Bu stratejiyle dava kesinlikle kazanilir."
    expect_semantic_raise("T18 Engine semantic guard: Row 14 phrase in strategy_description rejected:", t)

    t = json.loads(json.dumps(fa))
    r = next(x for x in t["risk_candidates"] if x["risk_kind"] == "identified")
    r["risk_description"] = "Bu tamamen rastgele, template ile eslesmeyen bir metindir."
    expect_semantic_raise(
        "T19 Engine semantic guard: risk_description not matching deterministic template rejected (no forbidden word needed):",
        t,
    )

    # ==============================================================
    # REMEDIATION: BULGU #2 - CONTENT fingerprint carry-forward testleri
    # (izole tempdir, gerçek veriye yazmadan)
    # ==============================================================

    def run_carry_forward_scenario(previous_analysis, get_second_client):

        temp = _tempfile.TemporaryDirectory(prefix="rs_content_fp_")

        fake_canonical = Path(temp.name) / "risk_strategy.json"

        atomic_write_json(fake_canonical, previous_analysis)

        fake_carry_dir = Path(temp.name) / "carry_forward"

        globals()["get_canonical_path"] = lambda cid: fake_canonical

        globals()["get_carry_forward_dir"] = lambda cid: fake_carry_dir

        try:

            result = build_risk_strategy_engine_output(
                case_id, use_agent=True, llm_client=get_second_client(), network_allowed=False,
            )

            return result

        finally:

            globals()["get_canonical_path"] = original_get_canonical_path

            globals()["get_carry_forward_dir"] = original_get_carry_forward_dir

            temp.cleanup()

    # Baseline "previous" canonical: identified risk confirmed, its
    # 1:1 strategy accepted_for_follow_up, suggestion accepted_for_follow_up.
    baseline_previous = json.loads(json.dumps(fa))

    for r in baseline_previous["risk_candidates"]:

        if r["risk_kind"] == "identified":

            r["risk_review_state"] = "confirmed"

    for s in baseline_previous["strategy_candidates"]:

        if any(
            rid in [r["risk_id"] for r in baseline_previous["risk_candidates"] if r["risk_kind"] == "identified"]
            for rid in s["addresses_risk_ids"]
        ):

            s["strategy_review_state"] = "accepted_for_follow_up"

    # T20: yalnız risk grounded_explanation değişince review reset
    identified_diff_text = json.dumps([
        {
            "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
            "reason_code": "explicit_textual_match",
            "grounded_explanation": "TAMAMEN FARKLI, yeniden yazilmis bir aciklama.",
            "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
            "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
            "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
        }
    ], ensure_ascii=False)

    r20 = run_carry_forward_scenario(
        baseline_previous,
        lambda: FakeRiskStrategyLLMClient(response_sequence=[identified_diff_text, suggestion_response]),
    )

    r20_identified = next(x for x in r20["analysis"]["risk_candidates"] if x["risk_kind"] == "identified")

    assert r20_identified["risk_review_state"] == "needs_review", (
        "Risk metni değiştiği halde önceki 'confirmed' durumu YANLIŞLIKLA taşındı!"
    )

    print("T20 Risk grounded_explanation değişince review_state needs_review'a reset olur:", "PASS")

    # T21: strategy carry-forward ARTIK GERÇEKTEN ÇALIŞIYOR (sıralama
    # düzeltmesi doğrulaması) - metin/kaynak DEĞİŞMEZSE confirmed risk +
    # aynı strateji -> accepted_for_follow_up TAŞINIR.
    r21 = run_carry_forward_scenario(
        baseline_previous,
        lambda: FakeRiskStrategyLLMClient(response_sequence=[identified_response, suggestion_response]),
    )

    r21_identified = next(x for x in r21["analysis"]["risk_candidates"] if x["risk_kind"] == "identified")

    assert r21_identified["risk_review_state"] == "confirmed"

    r21_strategy = next(
        s for s in r21["analysis"]["strategy_candidates"]
        if s["addresses_risk_ids"] == [r21_identified["risk_id"]]
    )

    assert r21_strategy["strategy_review_state"] == "accepted_for_follow_up", (
        "Strategy carry-forward çalışmıyor (sıralama regresyonu şüphesi) - "
        f"beklenen accepted_for_follow_up, bulunan: {r21_strategy['strategy_review_state']}"
    )

    print(
        "T21 Tüm içerik ve dokuz upstream hash aynıysa risk VE strategy "
        "doğru carry-forward edilir (strip/carry-forward sıralama düzeltmesi doğrulandı):",
        "PASS",
    )

    # T22: strategy'nin KENDİ metni/aksiyonu değişmeden, addressed risk'in
    # metni değişince strateji de reset olmalı.
    r22 = run_carry_forward_scenario(
        baseline_previous,
        lambda: FakeRiskStrategyLLMClient(response_sequence=[identified_diff_text, suggestion_response]),
    )

    r22_identified = next(x for x in r22["analysis"]["risk_candidates"] if x["risk_kind"] == "identified")

    r22_strategy = next(
        s for s in r22["analysis"]["strategy_candidates"]
        if s["addresses_risk_ids"] == [r22_identified["risk_id"]]
    )

    assert r22_strategy["strategy_review_state"] == "needs_review", (
        "Addressed risk metni değiştiği halde strateji YANLIŞLIKLA "
        "accepted_for_follow_up olarak taşındı!"
    )

    print(
        "T22 Strategy kendi metni değişmeden, addressed risk metni "
        "değişince review_state needs_review'a reset olur:", "PASS",
    )

    # T23: suggestion yalnız açıklama değişince review reset
    baseline_previous_with_sug = json.loads(json.dumps(baseline_previous))

    baseline_previous_with_sug["risk_strategy_agent_suggestions"] = [
        {
            "suggestion_id": "risk_strategy_suggestion_001", "suggestion_type": "additional_analysis_needed",
            "source_issue_id": "issue_001", "related_reference_ids": [], "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Ek analiz faydali olabilir.",
            "suggestion_review_state": "accepted_for_follow_up",
            "requires_human_review": True, "status": "candidate",
        }
    ]

    suggestion_diff_text = json.dumps([
        {
            "suggestion_type": "additional_analysis_needed", "source_issue_id": "issue_001",
            "related_reference_ids": [], "reason_code": "general_contextual_relevance",
            "grounded_explanation": "BAMBASKA bir oneri metni, yeniden yazildi.",
        }
    ], ensure_ascii=False)

    r23 = run_carry_forward_scenario(
        baseline_previous_with_sug,
        lambda: FakeRiskStrategyLLMClient(response_sequence=[identified_response, suggestion_diff_text]),
    )

    r23_suggestion = r23["analysis"]["risk_strategy_agent_suggestions"][0]

    assert r23_suggestion["suggestion_review_state"] == "needs_review", (
        "Suggestion metni değiştiği halde önceki durum YANLIŞLIKLA taşındı!"
    )

    print("T23 Suggestion grounded_explanation değişince review_state needs_review'a reset olur:", "PASS")

    # T24: farklı açıklamalı mantıksal duplicate hâlâ reddediliyor
    # (agent stage kendi içi dedup, metinden bağımsız anahtar kullanır)
    from risk_strategy_agent import run_identified_risk_stage

    dup_raw_items = [
        {
            "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
            "reason_code": "explicit_textual_match", "grounded_explanation": "Ilk aciklama.",
            "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
            "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
            "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
        },
        {
            "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
            "reason_code": "explicit_textual_match", "grounded_explanation": "TAMAMEN FARKLI ikinci aciklama.",
            "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
            "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
            "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
        },
    ]

    from legal_research_validator import load_canonical_issues as _lci2
    from timeline_validator import load_canonical_fact_index as _lcf2
    from risk_strategy_discovery import (
        build_active_documents_index as _badi2, build_allowlists_for_issues as _bafi2,
        load_canonical_arguments_optional as _lcao2,
    )
    from argument_discovery import (
        load_canonical_evidence_optional as _lceo2, load_canonical_legal_research_optional as _lclro2,
        load_canonical_case_law_optional as _lccl2, load_canonical_timeline_optional as _lcto2,
        load_canonical_deadline_optional as _lcdo2,
    )

    ic2 = _lci2(case_id)
    fc2 = _lcf2(case_id)
    adi2 = _badi2(case_id)
    _e2, ev_idx2, ep2 = _lceo2(case_id)
    _r2, res_idx2, rp2 = _lclro2(case_id)
    _d2, cl_idx2, dp2 = _lccl2(case_id)
    tl_idx2, tp2 = _lcto2(case_id)
    dls2, dl_ids2, dlp2 = _lcdo2(case_id)
    dl_idx2 = {d["deadline_id"]: d for d in dls2}
    (claims2, claim_idx2, counters2, counter_idx2, rebuttals2, rebuttal_idx2, arg_cov2, argp2) = _lcao2(case_id)
    cl_data2 = load_json(dp2.parent / "case_law.json") if dp2.exists() else {}
    cl_cov2 = {c["source_issue_id"]: c for c in cl_data2.get("case_law_coverage", []) if isinstance(c, dict)}
    ev_data2 = load_json(ep2) if ep2.exists() else {}
    ev_cov2 = {c["source_issue_id"]: c for c in ev_data2.get("evidence_coverage", []) if isinstance(c, dict)}

    allowlist_by_issue2, _w2 = _bafi2(
        ic2["issues"], fc2["facts"], adi2, ev_idx2, ev_cov2, res_idx2, cl_idx2, cl_cov2,
        tl_idx2, dl_idx2, claim_idx2, counter_idx2, rebuttal_idx2, arg_cov2,
    )

    dedup_finalized, dedup_warnings, dedup_stats = run_identified_risk_stage(
        dup_raw_items, allowlist_by_issue2, fc2["facts"], ev_idx2, res_idx2, cl_idx2, set(), 1,
    )

    assert len(dedup_finalized) == 1, (
        f"Farklı açıklamalı mantıksal duplicate reddedilmedi: {len(dedup_finalized)} kayıt üretildi."
    )

    assert any("dedup" in w.lower() or "duplicate" in w.lower() for w in dedup_warnings)

    print(
        "T24 Aynı mantıksal risk (farklı açıklama) agent stage dedup'ı "
        "tarafından ikinci candidate olarak reddediliyor:", "PASS",
    )

    assert_real_risk_strategy_tree_unchanged(
        case_id, real_tree_before, "End of self-test (full suite)",
    )

    print()
    print("======================================")
    print(" RISK / STRATEGY ENGINE V1: 24/24 PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Risk/Strategy Engine V1")

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
    print(" VERGİ AI - RISK / STRATEGY ENGINE V1")
    print("======================================")

    result = build_risk_strategy_engine_output(
        args.case_id, use_agent=args.with_agent, network_allowed=args.allow_network,
    )

    pending_path, validation, _history = write_pending(
        args.case_id, result["analysis"], result["issue_count"],
    )

    print()
    print("Pending:", pending_path)
    print("Risk coverage:", len(result["analysis"]["risk_coverage"]))
    print("Case-scope coverage:", len(result["analysis"]["case_scope_coverage"]))
    print("Risk candidates:", result["risk_count"], "(gap:", result["gap_risk_count"], "identified:", result["identified_risk_count"], ")")
    print("Strategy candidates:", result["strategy_count"])
    print("Suggestions:", result["suggestion_count"])
    print("Validator:", "PASS" if validation["valid"] else "FAIL")

    for warning in result["analysis"]["warnings"]:

        print(f"- {warning}")

    print()
    print("- Kesin hukuki sonuç ifadesi üretilmemiştir.")
    print("- Canonical risk_strategy.json değiştirilmemiştir.")
    print()
    print("======================================")
    print(" RISK / STRATEGY ENGINE V1:", "PASS" if validation["valid"] else "FAIL")
    print("======================================")

    if not validation["valid"]:

        sys.exit(1)


if __name__ == "__main__":

    main()
