# ============================================================
# VERGİ AI - RISK / STRATEGY VALIDATOR V1
#
# Üç seviye doğrulama:
#  1. JSON Schema
#  2. Canonical issue/approved fact/(varsa) evidence-research-
#     case_law-timeline-deadline-arguments çapraz bütünlük, same-
#     issue-scope, absence_basis/gap-eligibility bağımsız yeniden
#     hesaplama, deterministik bayrak bağımsız yeniden hesaplama
#  3. analysis_metadata (9 hash) stale-input guard
#
# Validator argument_agent.py/risk_strategy_agent.py'nin
# check_text_safety() sarmalayıcısını İMPORT ETMEZ - agent'tan
# bağımsız kendi text-safety battery'sini kullanır (Row 13 C1
# dersi, baştan uygulanmış).
# ============================================================

import argparse
import json
import sys
import tempfile

from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from legal_research_validator import load_canonical_issues
from timeline_validator import load_canonical_fact_index

from argument_discovery import (
    load_canonical_evidence_optional,
    load_canonical_legal_research_optional,
    load_canonical_case_law_optional,
    load_canonical_timeline_optional,
    load_canonical_deadline_optional,
)

from risk_strategy_discovery import (
    build_active_documents_index,
    build_allowlists_for_issues,
    build_case_scope_snapshots,
    load_canonical_arguments_optional,
)

from risk_strategy_policy import (
    CASE_RISK_SCOPES,
    RISK_EXECUTION_STATES,
    STRATEGY_EXECUTION_STATES,
    ZERO_RISK_EXECUTION_STATES,
    ZERO_STRATEGY_EXECUTION_STATES,
    RISK_TYPES,
    GAP_RISK_TYPES,
    IDENTIFIED_RISK_TYPES,
    ABSENCE_BASIS_VALUES,
    STRATEGY_ACTION_TYPES,
    SUGGESTION_TYPES,
    REF_FIELDS,
    DETERMINISTIC_FLAG_NAMES,
    MAX_GROUNDED_EXPLANATION_LENGTH,
    MAX_RISK_DESCRIPTION_LENGTH,
    MAX_STRATEGY_DESCRIPTION_LENGTH,
    sha256_of,
    compute_all_flags,
    compute_risk_dedup_fingerprint,
    compute_strategy_dedup_fingerprint,
    find_smuggled_ids,
    find_unverified_quotes,
    find_unsupported_numeric_tokens,
    collect_citable_texts,
    collect_ref_ids,
    normalize_text_tr,
    check_forbidden_phrases,
    render_gap_risk_description,
    render_identified_risk_description,
    render_strategy_description,
)


RISK_STRATEGY_VALIDATOR_VERSION = "1"

RISK_STRATEGY_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "case_risk_strategy.schema.json"
)


def load_json(path):

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


def write_json(path, data):

    path = Path(path)

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:

        json.dump(data, file, ensure_ascii=False, indent=2)


def clone_json(data):

    return json.loads(json.dumps(data))


def parse_iso_datetime(value):

    if not isinstance(value, str):
        return None

    try:

        from datetime import datetime

        datetime.fromisoformat(value)

        return value

    except ValueError:

        return None


# ============================================================
# SCHEMA
# ============================================================

def validate_schema(analysis):

    schema = load_json(RISK_STRATEGY_SCHEMA_PATH)

    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    errors = []

    for error in sorted(validator.iter_errors(analysis), key=str):

        path = ".".join(str(part) for part in error.absolute_path)

        errors.append(f"{path}: {error.message}" if path else error.message)

    return errors


def validate_case_id(analysis, expected_case_id):

    errors = []

    if analysis.get("case_id") != expected_case_id:

        errors.append(
            "Risk/Strategy analysis case_id uyuşmazlığı. Beklenen="
            f"{expected_case_id}, Bulunan={analysis.get('case_id')}"
        )

    return errors


def validate_generated_at(analysis):

    errors = []

    if parse_iso_datetime(analysis.get("generated_at")) is None:

        errors.append(f"generated_at geçerli ISO date-time değil: {analysis.get('generated_at')}")

    return errors


# ============================================================
# TEXT SAFETY (BAĞIMSIZ, agent MODÜLÜ İMPORT EDİLMEZ)
# ============================================================

MAX_LENGTH_BY_FIELD = {
    "risk_description": MAX_RISK_DESCRIPTION_LENGTH,
    "strategy_description": MAX_STRATEGY_DESCRIPTION_LENGTH,
    "grounded_explanation": MAX_GROUNDED_EXPLANATION_LENGTH,
}


# check_forbidden_phrases: risk_strategy_policy.py'den DOĞRUDAN import
# edilir (yukarıda) - burada YENİDEN TANIMLANMAZ. Bu, agent'ın yüksek
# seviyeli check_text_safety() sarmalayıcısının çağrılması DEĞİLDİR;
# yalnız paylaşılan, saf, ORTAK politika sabiti (ALL_FORBIDDEN_PHRASES)
# ve fonksiyonu reuse edilir - Row 13'ün find_smuggled_ids/
# find_unverified_quotes gibi diğer primitiflerinin zaten agent_policy'den
# ortak import edilmesiyle AYNI, önceden onaylanmış desen.


def check_independent_text_safety(
    record_id, field_label, text, max_length, declared_ids, known_reference_ids, citable_texts,
):

    errors = []

    errors.extend(check_forbidden_phrases(record_id, text))

    if text is None:

        return errors

    if not isinstance(text, str) or not text.strip():

        errors.append(f"{record_id}: {field_label} boş olamaz.")

        return errors

    if len(text) > max_length:

        errors.append(f"{record_id}: {field_label} uzunluk sınırını aşıyor.")

        return errors

    smuggled = find_smuggled_ids(text, declared_ids, known_reference_ids)

    if smuggled:

        errors.append(
            f"{record_id}: {field_label} içine bilinmeyen/deklare "
            f"edilmemiş ID gömülü: {smuggled}"
        )

    unverified_quotes = find_unverified_quotes(text, citable_texts)

    if unverified_quotes:

        errors.append(
            f"{record_id}: {field_label} içindeki alıntı referans "
            f"kaynaklarda birebir doğrulanamadı: {unverified_quotes}"
        )

    unsupported = find_unsupported_numeric_tokens(text, citable_texts)

    if unsupported:

        errors.append(
            f"{record_id}: {field_label} içindeki tarih/tutar/süre/yıl "
            f"referans kaynaklarda birebir bulunamadı (unsupported): {unsupported}"
        )

    return errors


# ============================================================
# ANALYSIS METADATA / STALE INPUT GUARD
# ============================================================

def validate_analysis_metadata(analysis_metadata, current_hashes):

    errors = []

    def check(field, recorded, current, exists):

        if not exists:

            if recorded is not None:

                errors.append(f"analysis_metadata.{field}: kaynak yok ama hash null değil.")

            return

        if recorded is None:

            errors.append(f"analysis_metadata.{field}: kaynak var ama hash null.")

            return

        if recorded != current:

            errors.append(
                f"STALE analysis_metadata.{field}: kayıtlı hash güncel "
                "canonical veriyle eşleşmiyor."
            )

    for field, (recorded, current, exists) in current_hashes.items():

        check(field, recorded, current, exists)

    return errors


# ============================================================
# RISK COVERAGE
# ============================================================

def validate_risk_coverage(coverage_records, issue_index, allowlist_by_issue, risks):

    errors = []

    gap_count_by_issue = Counter(
        r["source_issue_id"] for r in risks if r.get("risk_kind") == "gap"
    )

    identified_count_by_issue = Counter(
        r["source_issue_id"] for r in risks if r.get("risk_kind") == "identified"
    )

    covered_issue_ids = set()

    for coverage in coverage_records:

        coverage_id = coverage.get("coverage_id")

        issue_id = coverage.get("source_issue_id")

        if issue_id not in issue_index:

            errors.append(f"{coverage_id}: source_issue_id bilinmeyen: {issue_id}")

            continue

        covered_issue_ids.add(issue_id)

        menu = allowlist_by_issue.get(issue_id, {})

        expected_allowlist_count = menu.get("allowlist_count", 0)

        if coverage.get("allowlist_count") != expected_allowlist_count:

            errors.append(
                f"{coverage_id}: allowlist_count yanlış (bağımsız yeniden "
                f"hesaplanan={expected_allowlist_count}, "
                f"kayıtlı={coverage.get('allowlist_count')})."
            )

        expected_gap = gap_count_by_issue.get(issue_id, 0)

        if coverage.get("gap_risk_count") != expected_gap:

            errors.append(f"{coverage_id}: gap_risk_count yanlış.")

        expected_identified = identified_count_by_issue.get(issue_id, 0)

        if coverage.get("identified_risk_count") != expected_identified:

            errors.append(f"{coverage_id}: identified_risk_count yanlış.")

        risk_state = coverage.get("risk_execution_state")

        if risk_state not in RISK_EXECUTION_STATES:

            errors.append(f"{coverage_id}: geçersiz risk_execution_state: {risk_state}")

        elif risk_state in ZERO_RISK_EXECUTION_STATES and (expected_gap != 0 or expected_identified != 0):

            errors.append(f"{coverage_id}: risk_execution_state={risk_state} iken risk count 0 olmalıdır.")

        strategy_state = coverage.get("strategy_execution_state")

        if strategy_state not in STRATEGY_EXECUTION_STATES:

            errors.append(f"{coverage_id}: geçersiz strategy_execution_state: {strategy_state}")

        elif strategy_state in ZERO_STRATEGY_EXECUTION_STATES and coverage.get("strategy_reference_count") != 0:

            errors.append(f"{coverage_id}: strategy_execution_state={strategy_state} iken strategy_reference_count 0 olmalıdır.")

        if not menu.get("has_minimum_grounding", False) and risk_state != "blocked_missing_input":

            errors.append(f"{coverage_id}: min. grounding yokken risk_execution_state blocked_missing_input olmalıdır.")

    for issue_id in issue_index:

        if issue_id not in covered_issue_ids:

            errors.append(f"Issue '{issue_id}' için risk_coverage kaydı eksik.")

    if len(coverage_records) != len(issue_index):

        errors.append(
            f"risk_coverage sayısı ({len(coverage_records)}) canonical issue "
            f"sayısıyla ({len(issue_index)}) eşleşmiyor."
        )

    return errors


# ============================================================
# CASE-SCOPE COVERAGE
# ============================================================

def validate_case_scope_coverage(coverage_records, scope_snapshots):

    errors = []

    covered_scopes = set()

    if len(coverage_records) != 7:

        errors.append(f"case_scope_coverage tam olarak 7 olmalıdır (bulunan={len(coverage_records)}).")

    for coverage in coverage_records:

        scope = coverage.get("source_case_scope")

        coverage_id = coverage.get("coverage_id")

        if scope not in CASE_RISK_SCOPES:

            errors.append(f"{coverage_id}: geçersiz source_case_scope: {scope}")

            continue

        covered_scopes.add(scope)

        expected = scope_snapshots.get(scope, {})

        if coverage.get("input_state") != expected.get("input_state"):

            errors.append(
                f"{coverage_id}: input_state yanlış (bağımsız="
                f"{expected.get('input_state')}, kayıtlı={coverage.get('input_state')})."
            )

        if sorted(coverage.get("depends_on_input_hash_fields", [])) != sorted(
            expected.get("depends_on_input_hash_fields", [])
        ):

            errors.append(f"{coverage_id}: depends_on_input_hash_fields yanlış.")

        for forbidden_field in (
            "review_state", "status", "confidence", "title", "requires_human_review",
        ):

            if forbidden_field in coverage:

                errors.append(f"{coverage_id}: coverage saf muhasebedir, '{forbidden_field}' taşıyamaz.")

    if covered_scopes != set(CASE_RISK_SCOPES):

        errors.append("case_scope_coverage tam 7 sabit scope ile 1:1 eşleşmiyor.")

    return errors


# ============================================================
# REFERENCE SET GROUNDING (ORTAK - risk/strategy)
# ============================================================

def validate_reference_set(
    record_id, issue_id, record, issue, fact_index, evidence_candidate_index,
    research_index, case_law_decision_index, timeline_event_index, deadline_ids,
    claim_index, counter_index, rebuttal_index,
):

    errors = []

    issue_fact_ids = set(issue.get("source_fact_ids", [])) if issue else set()

    for fact_id in record.get("source_fact_ids", []):

        if fact_id not in fact_index:

            errors.append(f"{record_id}: source_fact_id approved facts.json içinde bulunamadı: {fact_id}")

        elif issue is not None and fact_id not in issue_fact_ids:

            errors.append(f"{record_id}: fact '{fact_id}' bu issue'nun kendi linkajında değil (cross-issue leakage).")

    for candidate_id in record.get("source_evidence_candidate_ids", []):

        candidate = evidence_candidate_index.get(candidate_id)

        if candidate is None:

            errors.append(f"{record_id}: source_evidence_candidate_id bulunamadı: {candidate_id}")

        elif candidate.get("review_state") == "rejected":

            errors.append(f"{record_id}: rejected evidence candidate grounding olarak kullanılamaz: {candidate_id}")

        elif issue_id is not None and candidate.get("source_issue_id") != issue_id:

            errors.append(f"{record_id}: evidence candidate '{candidate_id}' başka bir issue'ya ait (cross-issue leakage).")

    for research_id in record.get("source_legal_research_ids", []):

        research = research_index.get(research_id)

        if research is None:

            errors.append(f"{record_id}: source_legal_research_id bulunamadı: {research_id}")

        elif issue_id is not None and research.get("source_issue_id") != issue_id:

            errors.append(f"{record_id}: research '{research_id}' başka bir issue'ya ait (cross-issue leakage).")

    for decision_id in record.get("source_case_law_ids", []):

        decision = case_law_decision_index.get(decision_id)

        if decision is None:

            errors.append(f"{record_id}: source_case_law_id bulunamadı: {decision_id}")

        elif issue_id is not None and decision.get("source_issue_id") != issue_id:

            errors.append(f"{record_id}: case law decision '{decision_id}' başka bir issue'ya ait (cross-issue leakage).")

    issue_timeline_ids = set(issue.get("source_timeline_event_ids", [])) if issue else None

    for event_id in record.get("source_timeline_event_ids", []):

        if event_id not in timeline_event_index:

            errors.append(f"{record_id}: source_timeline_event_id bulunamadı: {event_id}")

        elif issue_timeline_ids is not None and event_id not in issue_timeline_ids:

            errors.append(f"{record_id}: timeline event '{event_id}' bu issue'nun linkajında değil (cross-issue leakage).")

    issue_deadline_ids = set(issue.get("source_deadline_ids", [])) if issue else None

    for deadline_id in record.get("source_deadline_ids", []):

        if deadline_id not in deadline_ids:

            errors.append(f"{record_id}: source_deadline_id bulunamadı: {deadline_id}")

        elif issue_deadline_ids is not None and deadline_id not in issue_deadline_ids:

            errors.append(f"{record_id}: deadline '{deadline_id}' bu issue'nun linkajında değil (cross-issue leakage).")

    for claim_id in record.get("source_claim_ids", []):

        claim = claim_index.get(claim_id)

        if claim is None:

            errors.append(f"{record_id}: source_claim_id bulunamadı: {claim_id}")

        elif claim.get("claim_review_state") == "rejected":

            errors.append(f"{record_id}: rejected claim grounding olarak kullanılamaz: {claim_id}")

        elif issue_id is not None and claim.get("source_issue_id") != issue_id:

            errors.append(f"{record_id}: claim '{claim_id}' başka bir issue'ya ait (cross-issue leakage).")

    for counter_id in record.get("source_counterargument_ids", []):

        counter = counter_index.get(counter_id)

        if counter is None:

            errors.append(f"{record_id}: source_counterargument_id bulunamadı: {counter_id}")

            continue

        parent_claim = claim_index.get(counter.get("source_claim_id"))

        if (
            counter.get("counter_review_state") == "rejected"
            or (parent_claim is not None and parent_claim.get("claim_review_state") == "rejected")
        ):

            errors.append(
                f"{record_id}: rejected counterargument (veya rejected-parent "
                f"alt-ağacı) grounding olarak kullanılamaz: {counter_id}"
            )

        elif issue_id is not None and counter.get("source_issue_id") != issue_id:

            errors.append(f"{record_id}: counterargument '{counter_id}' başka bir issue'ya ait (cross-issue leakage).")

    for rebuttal_id in record.get("source_rebuttal_ids", []):

        rebuttal = rebuttal_index.get(rebuttal_id)

        if rebuttal is None:

            errors.append(f"{record_id}: source_rebuttal_id bulunamadı: {rebuttal_id}")

            continue

        parent_counter = counter_index.get(rebuttal.get("source_counterargument_id"))

        parent_claim = (
            claim_index.get(parent_counter.get("source_claim_id"))
            if parent_counter is not None else None
        )

        if (
            rebuttal.get("rebuttal_review_state") == "rejected"
            or (parent_counter is not None and parent_counter.get("counter_review_state") == "rejected")
            or (parent_claim is not None and parent_claim.get("claim_review_state") == "rejected")
        ):

            errors.append(
                f"{record_id}: rejected rebuttal (veya rejected-parent alt-ağacı) "
                f"grounding olarak kullanılamaz: {rebuttal_id}"
            )

        elif issue_id is not None and rebuttal.get("source_issue_id") != issue_id:

            errors.append(f"{record_id}: rebuttal '{rebuttal_id}' başka bir issue'ya ait (cross-issue leakage).")

    return errors


# ============================================================
# RISK CANDIDATES
# ============================================================

def validate_risk_candidates(
    risks, issue_index, allowlist_by_issue, fact_index, evidence_candidate_index,
    research_index, case_law_decision_index, timeline_event_index, deadline_ids,
    claim_index, counter_index, rebuttal_index, deadline_index, known_reference_ids,
):

    errors = []

    ids = [r.get("risk_id") for r in risks if isinstance(r, dict)]

    for risk_id, count in Counter(ids).items():

        if count > 1:

            errors.append(f"Duplicate risk_id: {risk_id}")

    seen_fingerprints = set()

    for risk in risks:

        if not isinstance(risk, dict):
            continue

        risk_id = risk.get("risk_id")

        issue_id = risk.get("source_issue_id")

        issue = issue_index.get(issue_id)

        if issue is None:

            errors.append(f"{risk_id}: source_issue_id canonical issues.json içinde bulunamadı: {issue_id}")

            continue

        menu = allowlist_by_issue.get(issue_id, {})

        risk_kind = risk.get("risk_kind")

        risk_type = risk.get("risk_type")

        if risk_kind == "gap":

            if risk_type not in GAP_RISK_TYPES:

                errors.append(f"{risk_id}: gap risk için geçersiz risk_type: {risk_type}")

            if risk.get("grounded_explanation") is not None:

                errors.append(f"{risk_id}: gap risk grounded_explanation null OLMALIDIR.")

            absence_basis = risk.get("absence_basis")

            if absence_basis not in ABSENCE_BASIS_VALUES:

                errors.append(f"{risk_id}: geçersiz absence_basis: {absence_basis}")

            elif absence_basis not in menu.get("gap_eligibility", {}):

                errors.append(
                    f"{risk_id}: absence_basis='{absence_basis}' bu issue "
                    "için bağımsız discovery'de tetiklenebilir DEĞİL "
                    "(proof-of-looking ihlali şüphesi)."
                )

        elif risk_kind == "identified":

            if risk_type not in IDENTIFIED_RISK_TYPES:

                errors.append(f"{risk_id}: identified risk için geçersiz risk_type: {risk_type}")

            if risk.get("absence_basis") is not None:

                errors.append(f"{risk_id}: identified risk absence_basis null OLMALIDIR.")

            if not risk.get("grounded_explanation"):

                errors.append(f"{risk_id}: identified risk grounded_explanation zorunludur.")

            if not collect_ref_ids(risk):

                errors.append(f"{risk_id}: en az bir geçerli grounded kaynak zorunlu.")

        else:

            errors.append(f"{risk_id}: geçersiz risk_kind: {risk_kind}")

        errors.extend(
            validate_reference_set(
                risk_id, issue_id, risk, issue, fact_index, evidence_candidate_index,
                research_index, case_law_decision_index, timeline_event_index,
                deadline_ids, claim_index, counter_index, rebuttal_index,
            )
        )

        expected_flags = compute_all_flags(
            {field: risk.get(field, []) for field in REF_FIELDS},
            fact_index, timeline_event_index, deadline_index,
            evidence_candidate_index, case_law_decision_index, research_index,
            claim_index, counter_index, rebuttal_index,
            [bool(menu.get("upstream_not_run_aspects"))],
        )

        if risk.get("flags") != expected_flags:

            errors.append(f"{risk_id}: deterministik bayraklar bağımsız yeniden hesaplamayla eşleşmiyor.")

        if risk.get("risk_review_state") not in ("needs_review", "confirmed", "rejected"):

            errors.append(f"{risk_id}: geçersiz risk_review_state.")

        if risk.get("requires_human_review") is not True:

            errors.append(f"{risk_id}: requires_human_review=True olmalıdır.")

        if risk.get("status") != "candidate":

            errors.append(f"{risk_id}: status='candidate' olmalıdır.")

        # ---- DETERMİNİSTİK TEMPLATE EŞİTLİĞİ (yalnız yasak kelime
        # içermemesi YETERLİ DEĞİL) ----

        if risk_kind == "gap" and risk_type in GAP_RISK_TYPES:

            expected_description = render_gap_risk_description(risk_type)

        elif risk_kind == "identified":

            expected_description = render_identified_risk_description(risk_type)

        else:

            expected_description = None

        if expected_description is not None and risk.get("risk_description") != expected_description:

            errors.append(
                f"{risk_id}: risk_description deterministik template ile "
                "eşleşmiyor (rastgele/serbest metin şüphesi)."
            )

        fp = compute_risk_dedup_fingerprint(risk)

        if fp in seen_fingerprints:

            errors.append(f"{risk_id}: duplicate risk (fingerprint çakışması).")

        seen_fingerprints.add(fp)

        declared_ids = collect_ref_ids(risk)

        citable_texts = collect_citable_texts(
            risk, fact_index, evidence_candidate_index, research_index, case_law_decision_index,
        )

        errors.extend(
            check_independent_text_safety(
                risk_id, "risk_description", risk.get("risk_description"),
                MAX_RISK_DESCRIPTION_LENGTH, declared_ids, known_reference_ids, citable_texts,
            )
        )

        errors.extend(
            check_independent_text_safety(
                risk_id, "grounded_explanation", risk.get("grounded_explanation"),
                MAX_GROUNDED_EXPLANATION_LENGTH, declared_ids, known_reference_ids, citable_texts,
            )
        )

    return errors


# ============================================================
# STRATEGY CANDIDATES
# ============================================================

def validate_strategy_candidates(
    strategies, risk_by_id, fact_index, evidence_candidate_index, research_index,
    case_law_decision_index, timeline_event_index, deadline_ids, claim_index,
    counter_index, rebuttal_index, known_reference_ids,
):

    errors = []

    ids = [s.get("strategy_id") for s in strategies if isinstance(s, dict)]

    for strategy_id, count in Counter(ids).items():

        if count > 1:

            errors.append(f"Duplicate strategy_id: {strategy_id}")

    seen_fingerprints = set()

    for strategy in strategies:

        if not isinstance(strategy, dict):
            continue

        strategy_id = strategy.get("strategy_id")

        addresses_risk_ids = strategy.get("addresses_risk_ids", [])

        if not addresses_risk_ids:

            errors.append(f"{strategy_id}: addresses_risk_ids en az 1 eleman içermeli.")

        if len(addresses_risk_ids) != len(set(addresses_risk_ids)):

            errors.append(f"{strategy_id}: addresses_risk_ids yinelenen ID içeriyor.")

        addressed_risks = []

        rejected_basis_used = False

        for risk_id in addresses_risk_ids:

            risk = risk_by_id.get(risk_id)

            if risk is None:

                errors.append(f"{strategy_id}: addresses_risk_ids içinde bilinmeyen risk: {risk_id}")

                continue

            addressed_risks.append(risk)

        # ---- SOURCE-SUBSET INVARIANT (bypass-prevention, bağımsız) ----

        allowed_union = {field: set() for field in REF_FIELDS}

        for risk in addressed_risks:

            for field in REF_FIELDS:

                allowed_union[field] |= set(risk.get(field, []))

        for field in REF_FIELDS:

            declared = set(strategy.get(field, []))

            if not declared.issubset(allowed_union[field]):

                errors.append(
                    f"{strategy_id}: {field} adreslenen risklerin kaynak "
                    "birleşiminin alt-kümesi DEĞİL (bypass şüphesi)."
                )

        # ---- depends_on_gap_only bağımsız doğrulama ----

        expected_gap_only = bool(addressed_risks) and all(
            r.get("risk_kind") == "gap" for r in addressed_risks
        )

        if strategy.get("depends_on_gap_only") != expected_gap_only:

            errors.append(f"{strategy_id}: depends_on_gap_only bağımsız hesaplamayla eşleşmiyor.")

        if strategy.get("strategy_action_type") not in STRATEGY_ACTION_TYPES:

            errors.append(f"{strategy_id}: geçersiz strategy_action_type.")

        else:

            expected_strategy_description = render_strategy_description(
                strategy.get("strategy_action_type")
            )

            if strategy.get("strategy_description") != expected_strategy_description:

                errors.append(
                    f"{strategy_id}: strategy_description deterministik "
                    "template ile eşleşmiyor (rastgele/serbest metin şüphesi)."
                )

        if strategy.get("record_kind") != "suggested_next_action":

            errors.append(f"{strategy_id}: record_kind='suggested_next_action' olmalıdır.")

        if strategy.get("requires_human_decision") is not True:

            errors.append(f"{strategy_id}: requires_human_decision=True olmalıdır.")

        if strategy.get("requires_human_review") is not True:

            errors.append(f"{strategy_id}: requires_human_review=True olmalıdır.")

        if strategy.get("status") != "candidate":

            errors.append(f"{strategy_id}: status='candidate' olmalıdır.")

        if strategy.get("strategy_review_state") not in (
            "needs_review", "accepted_for_follow_up", "dismissed",
        ):

            errors.append(f"{strategy_id}: geçersiz strategy_review_state.")

        errors.extend(
            validate_reference_set(
                strategy_id, None, strategy, None, fact_index, evidence_candidate_index,
                research_index, case_law_decision_index, timeline_event_index,
                deadline_ids, claim_index, counter_index, rebuttal_index,
            )
        )

        declared_ids = collect_ref_ids(strategy)

        citable_texts = collect_citable_texts(
            strategy, fact_index, evidence_candidate_index, research_index, case_law_decision_index,
        )

        errors.extend(
            check_independent_text_safety(
                strategy_id, "strategy_description", strategy.get("strategy_description"),
                MAX_STRATEGY_DESCRIPTION_LENGTH, declared_ids, known_reference_ids, citable_texts,
            )
        )

        errors.extend(
            check_independent_text_safety(
                strategy_id, "grounded_explanation", strategy.get("grounded_explanation"),
                MAX_GROUNDED_EXPLANATION_LENGTH, declared_ids, known_reference_ids, citable_texts,
            )
        )

        temp_strategy = dict(strategy)

        temp_strategy["_addressed_risk_dedup_fingerprints"] = [
            compute_risk_dedup_fingerprint(r) for r in addressed_risks
        ]

        fp = compute_strategy_dedup_fingerprint(temp_strategy)

        if fp in seen_fingerprints:

            errors.append(f"{strategy_id}: duplicate strategy (fingerprint çakışması).")

        seen_fingerprints.add(fp)

    return errors


# ============================================================
# AGENT SUGGESTIONS
# ============================================================

def validate_agent_suggestions(suggestions, issue_index, known_reference_ids, fact_index,
                                evidence_candidate_index, research_index, case_law_decision_index):

    errors = []

    ids = [s.get("suggestion_id") for s in suggestions if isinstance(s, dict)]

    for suggestion_id, count in Counter(ids).items():

        if count > 1:

            errors.append(f"Duplicate suggestion_id: {suggestion_id}")

    for suggestion in suggestions:

        if not isinstance(suggestion, dict):
            continue

        suggestion_id = suggestion.get("suggestion_id")

        issue_id = suggestion.get("source_issue_id")

        if issue_id is not None and issue_id not in issue_index:

            errors.append(f"{suggestion_id}: bilinmeyen source_issue_id: {issue_id}")

        if suggestion.get("suggestion_type") not in SUGGESTION_TYPES:

            errors.append(f"{suggestion_id}: geçersiz suggestion_type.")

        related_reference_ids = suggestion.get("related_reference_ids", [])

        for ref_id in related_reference_ids:

            if ref_id not in known_reference_ids:

                errors.append(f"{suggestion_id}: related_reference_ids içinde bilinmeyen referans: {ref_id}")

        if suggestion.get("requires_human_review") is not True:

            errors.append(f"{suggestion_id}: requires_human_review=True olmalıdır.")

        if suggestion.get("status") != "candidate":

            errors.append(f"{suggestion_id}: status='candidate' olmalıdır.")

        classified_ref_set = {
            "source_fact_ids": [r for r in related_reference_ids if r in fact_index],
            "source_evidence_candidate_ids": [r for r in related_reference_ids if r in evidence_candidate_index],
            "source_legal_research_ids": [r for r in related_reference_ids if r in research_index],
            "source_case_law_ids": [r for r in related_reference_ids if r in case_law_decision_index],
        }

        citable_texts = collect_citable_texts(
            classified_ref_set, fact_index, evidence_candidate_index, research_index, case_law_decision_index,
        )

        errors.extend(
            check_independent_text_safety(
                suggestion_id, "grounded_explanation", suggestion.get("grounded_explanation"),
                MAX_GROUNDED_EXPLANATION_LENGTH, set(related_reference_ids), known_reference_ids, citable_texts,
            )
        )

    return errors


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_risk_strategy_analysis(arguments_path, expected_case_id=None, raise_on_error=False):

    arguments_path = Path(arguments_path)

    analysis = load_json(arguments_path)

    errors = []

    errors.extend(validate_schema(analysis))

    case_id = expected_case_id or analysis.get("case_id")

    errors.extend(validate_case_id(analysis, case_id))

    errors.extend(validate_generated_at(analysis))

    issue_context = load_canonical_issues(case_id)

    issue_index = issue_context["issue_index"]

    fact_context = load_canonical_fact_index(case_id)

    fact_index = fact_context["facts"]

    active_documents_index = build_active_documents_index(case_id)

    _e, evidence_candidate_index, evidence_path = load_canonical_evidence_optional(case_id)

    _r, research_index, research_path = load_canonical_legal_research_optional(case_id)

    _d, case_law_decision_index, case_law_path = load_canonical_case_law_optional(case_id)

    timeline_event_index, timeline_path = load_canonical_timeline_optional(case_id)

    deadlines, deadline_ids, deadline_path = load_canonical_deadline_optional(case_id)

    deadline_index = {d["deadline_id"]: d for d in deadlines}

    (
        claims, claim_index, counters, counter_index, rebuttals, rebuttal_index,
        argument_coverage_by_issue, arguments_path_,
    ) = load_canonical_arguments_optional(case_id)

    evidence_data = load_json(evidence_path) if evidence_path.exists() else {}

    evidence_coverage_by_issue = {
        c["source_issue_id"]: c for c in evidence_data.get("evidence_coverage", [])
        if isinstance(c, dict) and c.get("source_issue_id")
    }

    case_law_data = load_json(case_law_path) if case_law_path.exists() else {}

    case_law_coverage_by_issue = {
        c["source_issue_id"]: c for c in case_law_data.get("case_law_coverage", [])
        if isinstance(c, dict) and c.get("source_issue_id")
    }

    allowlist_by_issue, _w = build_allowlists_for_issues(
        issue_context["issues"], fact_index, active_documents_index,
        evidence_candidate_index, evidence_coverage_by_issue, research_index,
        case_law_decision_index, case_law_coverage_by_issue, timeline_event_index,
        deadline_index, claim_index, counter_index, rebuttal_index, argument_coverage_by_issue,
    )

    scope_snapshots = build_case_scope_snapshots(
        evidence_path.exists(), evidence_coverage_by_issue, evidence_candidate_index,
        research_path.exists(), research_index,
        case_law_path.exists(), case_law_coverage_by_issue, case_law_decision_index,
        timeline_path.exists(), timeline_event_index,
        deadline_path.exists(), deadline_index,
    )

    documents_hash_source = sorted(active_documents_index.items(), key=lambda kv: kv[0])

    current_hashes = {
        "issues_input_hash": (
            analysis.get("analysis_metadata", {}).get("issues_input_hash"),
            sha256_of(issue_context["issues"]), True,
        ),
        "facts_input_hash": (
            analysis.get("analysis_metadata", {}).get("facts_input_hash"),
            sha256_of({fid: rec["fact"] for fid, rec in fact_index.items()}), True,
        ),
        "documents_input_hash": (
            analysis.get("analysis_metadata", {}).get("documents_input_hash"),
            sha256_of(documents_hash_source) if active_documents_index else None,
            bool(active_documents_index),
        ),
        "timeline_input_hash": (
            analysis.get("analysis_metadata", {}).get("timeline_input_hash"),
            sha256_of(timeline_event_index) if timeline_path.exists() else None,
            timeline_path.exists(),
        ),
        "deadline_input_hash": (
            analysis.get("analysis_metadata", {}).get("deadline_input_hash"),
            sha256_of(deadlines) if deadline_path.exists() else None,
            deadline_path.exists(),
        ),
        "legal_research_input_hash": (
            analysis.get("analysis_metadata", {}).get("legal_research_input_hash"),
            sha256_of(research_index) if research_path.exists() else None,
            research_path.exists(),
        ),
        "case_law_input_hash": (
            analysis.get("analysis_metadata", {}).get("case_law_input_hash"),
            sha256_of({"decisions": case_law_decision_index, "coverage": case_law_coverage_by_issue}) if case_law_path.exists() else None,
            case_law_path.exists(),
        ),
        "evidence_input_hash": (
            analysis.get("analysis_metadata", {}).get("evidence_input_hash"),
            sha256_of({"candidates": evidence_candidate_index, "coverage": evidence_coverage_by_issue}) if evidence_path.exists() else None,
            evidence_path.exists(),
        ),
        "arguments_input_hash": (
            analysis.get("analysis_metadata", {}).get("arguments_input_hash"),
            sha256_of({"claims": claim_index, "counters": counter_index, "rebuttals": rebuttal_index, "coverage": argument_coverage_by_issue}) if arguments_path_.exists() else None,
            arguments_path_.exists(),
        ),
    }

    errors.extend(validate_analysis_metadata(analysis.get("analysis_metadata", {}), current_hashes))

    risk_coverage = analysis.get("risk_coverage", [])

    case_scope_coverage = analysis.get("case_scope_coverage", [])

    risks = analysis.get("risk_candidates", [])

    strategies = analysis.get("strategy_candidates", [])

    suggestions = analysis.get("risk_strategy_agent_suggestions", [])

    known_reference_ids = (
        set(fact_index.keys()) | set(evidence_candidate_index.keys())
        | set(research_index.keys()) | set(case_law_decision_index.keys())
        | set(timeline_event_index.keys()) | set(deadline_ids)
        | set(claim_index.keys()) | set(counter_index.keys()) | set(rebuttal_index.keys())
        | {r.get("risk_id") for r in risks if isinstance(r, dict)}
        | {s.get("strategy_id") for s in strategies if isinstance(s, dict)}
    )

    errors.extend(validate_risk_coverage(risk_coverage, issue_index, allowlist_by_issue, risks))

    errors.extend(validate_case_scope_coverage(case_scope_coverage, scope_snapshots))

    errors.extend(
        validate_risk_candidates(
            risks, issue_index, allowlist_by_issue, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index, timeline_event_index, deadline_ids,
            claim_index, counter_index, rebuttal_index, deadline_index, known_reference_ids,
        )
    )

    risk_by_id = {r["risk_id"]: r for r in risks if isinstance(r, dict) and r.get("risk_id")}

    errors.extend(
        validate_strategy_candidates(
            strategies, risk_by_id, fact_index, evidence_candidate_index, research_index,
            case_law_decision_index, timeline_event_index, deadline_ids, claim_index,
            counter_index, rebuttal_index, known_reference_ids,
        )
    )

    errors.extend(
        validate_agent_suggestions(
            suggestions, issue_index, known_reference_ids, fact_index,
            evidence_candidate_index, research_index, case_law_decision_index,
        )
    )

    errors = list(dict.fromkeys(errors))

    result = {
        "valid": len(errors) == 0,
        "errors": errors,
        "case_id": case_id,
        "coverage_count": len(risk_coverage),
        "risk_count": len(risks),
        "strategy_count": len(strategies),
        "suggestion_count": len(suggestions),
    }

    if raise_on_error and not result["valid"]:

        raise ValueError("Risk/Strategy validation failed:\n- " + "\n- ".join(errors))

    return result


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(case_id="case_0001"):

    from risk_strategy_agent import FakeRiskStrategyLLMClient
    from risk_strategy_engine import build_risk_strategy_engine_output

    print()
    print("======================================")
    print(" VERGİ AI - RISK / STRATEGY VALIDATOR V1")
    print("======================================")

    assert RISK_STRATEGY_SCHEMA_PATH.exists()

    load_json(RISK_STRATEGY_SCHEMA_PATH)

    print("T01 Schema load:", "PASS")

    issue_context = load_canonical_issues(case_id)

    fact_context = load_canonical_fact_index(case_id)

    print("T02 Canonical issue/fact context load:", "PASS")

    temp_dir = tempfile.TemporaryDirectory(prefix="risk_strategy_validator_selftest_")

    work_dir = Path(temp_dir.name)

    def write_and_validate(analysis, name):

        path = work_dir / name

        write_json(path, analysis)

        return validate_risk_strategy_analysis(path, case_id)

    # ---- T03: OFFLINE BASELINE (6 issue + 7 scope completeness) ----

    offline = build_risk_strategy_engine_output(case_id, use_agent=False)["analysis"]

    assert len(offline["risk_coverage"]) == len(issue_context["issue_index"])
    assert len(offline["case_scope_coverage"]) == 7
    assert len(offline["risk_candidates"]) == 0
    assert len(offline["strategy_candidates"]) == 0
    assert len(offline["risk_strategy_agent_suggestions"]) == 0

    for coverage in offline["risk_coverage"]:

        assert coverage["risk_execution_state"] in ("analysis_not_run", "blocked_missing_input")
        assert coverage["strategy_execution_state"] in ("analysis_not_run", "blocked_missing_input")

    baseline_result = write_and_validate(offline, "baseline.json")

    if not baseline_result["valid"]:

        for e in baseline_result["errors"]:
            print("-", e)

    assert baseline_result["valid"] is True

    print("T03 Offline baseline (6 issue + 7 scope completeness):", "PASS")

    # ---- T04: GROUNDED IDENTIFIED RISK + DETERMINISTIC DEADLINE GAP ----

    identified_response = json.dumps([
        {
            "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
            "reason_code": "explicit_textual_match", "grounded_explanation": "Bu kayit dogrulanmamis facta dayanir.",
            "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
            "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
            "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
        }
    ], ensure_ascii=False)

    client = FakeRiskStrategyLLMClient(response_sequence=[identified_response, "[]"])

    full = build_risk_strategy_engine_output(case_id, use_agent=True, llm_client=client, network_allowed=False)["analysis"]

    assert any(r["risk_kind"] == "identified" for r in full["risk_candidates"])
    assert any(r["risk_kind"] == "gap" and r["risk_type"] == "anchor_event_unverified" for r in full["risk_candidates"])

    full_result = write_and_validate(full, "full.json")

    if not full_result["valid"]:

        for e in full_result["errors"]:
            print("-", e)

    assert full_result["valid"] is True

    print("T04 Grounded identified risk + deterministic deadline gap accepted:", "PASS")

    risk_by_id = {r["risk_id"]: r for r in full["risk_candidates"]}

    strategy_by_id = {s["strategy_id"]: s for s in full["strategy_candidates"]}

    # ---- T05: MISSING EVIDENCE -> NO RISK (fabricated gap rejected) ----

    tampered = json.loads(json.dumps(full))

    fake_gap = {
        "risk_id": "risk_gap_fake_evidence", "risk_kind": "gap",
        "risk_type": "no_confirmed_evidence_for_issue", "source_issue_id": "issue_001",
        "source_fact_ids": [], "source_claim_ids": [], "source_counterargument_ids": [],
        "source_rebuttal_ids": [], "source_evidence_candidate_ids": [], "source_legal_research_ids": [],
        "source_case_law_ids": [], "source_timeline_event_ids": [], "source_deadline_ids": [],
        "absence_basis": "no_confirmed_evidence_for_issue",
        "reason_code": "deterministic_gap_no_confirmed_evidence",
        "risk_description": "x", "grounded_explanation": None,
        "risk_review_state": "needs_review", "requires_human_review": True, "status": "candidate",
        "flags": {name: False for name in DETERMINISTIC_FLAG_NAMES},
    }

    tampered["risk_candidates"].append(fake_gap)

    result = write_and_validate(tampered, "fake_evidence_gap.json")

    assert result["valid"] is False
    assert any("proof-of-looking" in e for e in result["errors"])

    print("T05 Missing evidence (no_canonical_input) -> fabricated gap risk rejected:", "PASS")

    # ---- T06: retrieval_not_run case-law -> NO RISK (fabricated gap rejected) ----

    tampered = json.loads(json.dumps(full))

    fake_gap2 = dict(fake_gap)

    fake_gap2["risk_id"] = "risk_gap_fake_caselaw"

    fake_gap2["risk_type"] = "no_grounded_case_law_for_issue"

    fake_gap2["absence_basis"] = "no_grounded_case_law_for_issue"

    fake_gap2["reason_code"] = "deterministic_gap_no_grounded_case_law"

    tampered["risk_candidates"].append(fake_gap2)

    result = write_and_validate(tampered, "fake_caselaw_gap.json")

    assert result["valid"] is False
    assert any("proof-of-looking" in e for e in result["errors"])

    print("T06 retrieval_not_run case-law -> fabricated gap risk rejected:", "PASS")

    # ---- T07: GROUNDED STRATEGY + SOURCE-SUBSET GUARD ----

    some_strategy_id = next(iter(strategy_by_id))

    tampered = json.loads(json.dumps(full))

    for s in tampered["strategy_candidates"]:

        if s["strategy_id"] == some_strategy_id:

            s["source_fact_ids"] = ["fact_ghost_zzz"]

    result = write_and_validate(tampered, "strategy_bypass.json")

    assert result["valid"] is False
    assert any("bypass" in e for e in result["errors"])

    print("T07 Strategy source-subset guard (bypass attempt) rejected:", "PASS")

    # ---- T08: CROSS-ISSUE / GHOST REFERENCE REJECTION ----

    other_fact_id = "fact_ihbarname_001_llm_v1_2_1_20260901_122652_006"

    tampered = json.loads(json.dumps(full))

    for r in tampered["risk_candidates"]:

        if r["risk_kind"] == "identified":

            r["source_fact_ids"] = [other_fact_id]

    result = write_and_validate(tampered, "cross_issue.json")

    assert result["valid"] is False
    assert any("cross-issue leakage" in e for e in result["errors"])

    print("T08 Cross-issue real canonical fact rejected:", "PASS")

    tampered = json.loads(json.dumps(full))

    for r in tampered["risk_candidates"]:

        if r["risk_kind"] == "identified":

            r["source_fact_ids"] = ["fact_ghost_xxx"]

    result = write_and_validate(tampered, "ghost.json")

    assert result["valid"] is False
    assert any("bulunamadı" in e for e in result["errors"])

    print("T09 Ghost fact reference rejected:", "PASS")

    # ---- T10: DETERMINISTIC FLAGS INDEPENDENT RECOMPUTATION ----

    tampered = json.loads(json.dumps(full))

    for r in tampered["risk_candidates"]:

        if r["risk_kind"] == "identified":

            r["flags"]["missing_legal_authority"] = not r["flags"]["missing_legal_authority"]

    result = write_and_validate(tampered, "flags.json")

    assert result["valid"] is False
    assert any("bayraklar" in e for e in result["errors"])

    print("T10 Deterministic flags independently recomputed and cross-checked:", "PASS")

    # ---- T11: NINE HASHES + STALE DETECTION ----

    metadata = full["analysis_metadata"]

    for field in (
        "issues_input_hash", "facts_input_hash", "documents_input_hash",
        "timeline_input_hash", "deadline_input_hash", "legal_research_input_hash",
        "case_law_input_hash", "evidence_input_hash", "arguments_input_hash",
    ):

        assert field in metadata

    assert metadata["evidence_input_hash"] is None

    for field in (
        "issues_input_hash", "facts_input_hash", "documents_input_hash",
        "timeline_input_hash", "deadline_input_hash", "legal_research_input_hash",
        "case_law_input_hash", "arguments_input_hash",
    ):

        assert metadata[field] is not None

    print("T11 Nine input hashes present with correct null/non-null pattern:", "PASS")

    tampered = json.loads(json.dumps(full))

    tampered["analysis_metadata"]["facts_input_hash"] = "0" * 64

    result = write_and_validate(tampered, "stale.json")

    assert result["valid"] is False
    assert any("STALE" in e for e in result["errors"])

    print("T12 Stale input_hash detection:", "PASS")

    # ---- T13: DEDUP / FINGERPRINT ----

    tampered = json.loads(json.dumps(full))

    duplicate = json.loads(json.dumps(tampered["risk_candidates"][0]))

    duplicate["risk_id"] = "risk_duplicate_999"

    tampered["risk_candidates"].append(duplicate)

    result = write_and_validate(tampered, "dup.json")

    assert result["valid"] is False
    assert any("duplicate" in e.lower() or "fingerprint" in e.lower() for e in result["errors"])

    print("T13 Duplicate risk (fingerprint çakışması) rejected:", "PASS")

    # ---- T14: AGENT-LEVEL FORBIDDEN-FIELD / ID SMUGGLING (validator independent re-check) ----

    tampered = json.loads(json.dumps(full))

    for r in tampered["risk_candidates"]:

        if r["risk_kind"] == "identified":

            r["grounded_explanation"] = f"Bkz {other_fact_id} numarali kayit."

    result = write_and_validate(tampered, "smuggle.json")

    assert result["valid"] is False
    assert any("gömülü" in e for e in result["errors"])

    print("T14 Smuggled ghost ID in grounded_explanation rejected (independent battery):", "PASS")

    # ---- T15: DURATION / BARE-YEAR GUARDS (Row 14-local hardening) ----

    tampered = json.loads(json.dumps(full))

    for r in tampered["risk_candidates"]:

        if r["risk_kind"] == "identified":

            r["grounded_explanation"] = "Bu durum 30 gun icinde tekrar degerlendirilmelidir."

    result = write_and_validate(tampered, "duration.json")

    assert result["valid"] is False
    assert any("unsupported" in e for e in result["errors"])

    print("T15 Unsupported duration token ('30 gün') rejected:", "PASS")

    tampered = json.loads(json.dumps(full))

    for r in tampered["risk_candidates"]:

        if r["risk_kind"] == "identified":

            r["grounded_explanation"] = "Bu olay 2024 yilinda meydana gelmis olabilir."

    result = write_and_validate(tampered, "bareyear.json")

    assert result["valid"] is False
    assert any("unsupported" in e for e in result["errors"])

    print("T16 Unsupported bare year ('2024') rejected:", "PASS")

    # ---- T17: SUGGESTION STRUCTURAL ISOLATION ----

    suggestion_response = json.dumps([
        {
            "suggestion_type": "additional_analysis_needed", "source_issue_id": "issue_001",
            "related_reference_ids": [], "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Bu issue icin ek analiz faydali olabilir.",
        }
    ], ensure_ascii=False)

    client2 = FakeRiskStrategyLLMClient(response_sequence=[identified_response, suggestion_response])

    with_suggestion = build_risk_strategy_engine_output(
        case_id, use_agent=True, llm_client=client2, network_allowed=False,
    )["analysis"]

    assert len(with_suggestion["risk_strategy_agent_suggestions"]) == 1

    suggestion = with_suggestion["risk_strategy_agent_suggestions"][0]

    forbidden_suggestion_fields = {
        "source_fact_ids", "source_document_id", "risk_review_state", "strategy_review_state",
    }

    assert not (forbidden_suggestion_fields & set(suggestion.keys()))

    result = write_and_validate(with_suggestion, "suggestion.json")

    assert result["valid"] is True

    print("T17 Suggestion structurally isolated (no fact/document grounding fields) and accepted:", "PASS")

    tampered = json.loads(json.dumps(with_suggestion))

    tampered["risk_strategy_agent_suggestions"][0]["related_reference_ids"] = ["fact_ghost_xxx"]

    result = write_and_validate(tampered, "suggestion_ghost.json")

    assert result["valid"] is False

    print("T18 Suggestion with unknown related_reference_id rejected:", "PASS")

    # ==============================================================
    # REMEDIATION: BULGU #1 - BİRLEŞİK FORBIDDEN-PHRASE POLİTİKASI
    # (hem Row 9 hem Row 14 sözlüğü, 5 alan, Türkçe normalizasyon,
    # agent-bypass tamper + pozitif kontrol)
    # ==============================================================

    row9_phrase_text = "Bu davada sure gecmistir."

    row14_phrase_text = "Bu stratejiyle dava kesinlikle kazanilir."

    row14_phrase_text_tr_diacritics = "BU STRATEJİYLE DAVA KESİNLİKLE KAZANILIR."

    safe_uncertainty_text = (
        "Bu husus mevcut canonical veriyle değerlendirilemedi; "
        "insan incelemesi gereklidir."
    )

    # T19-T20: risk_description - hem Row 9 hem Row 14 sözlüğü
    tampered = json.loads(json.dumps(full))
    identified = next(r for r in tampered["risk_candidates"] if r["risk_kind"] == "identified")
    identified["risk_description"] = row9_phrase_text
    result = write_and_validate(tampered, "risk_desc_row9.json")
    assert result["valid"] is False
    print("T19 risk_description with Row 9 phrase ('süre geçmiştir') rejected:", "PASS")

    tampered = json.loads(json.dumps(full))
    identified = next(r for r in tampered["risk_candidates"] if r["risk_kind"] == "identified")
    identified["risk_description"] = row14_phrase_text
    result = write_and_validate(tampered, "risk_desc_row14.json")
    assert result["valid"] is False
    print("T20 risk_description with Row 14 phrase ('kesinlikle kazanılır') rejected:", "PASS")

    # T21: identified risk grounded_explanation - Row 14 phrase
    tampered = json.loads(json.dumps(full))
    identified = next(r for r in tampered["risk_candidates"] if r["risk_kind"] == "identified")
    identified["grounded_explanation"] = row14_phrase_text
    result = write_and_validate(tampered, "risk_ge_row14.json")
    assert result["valid"] is False
    print("T21 identified risk grounded_explanation with Row 14 phrase rejected:", "PASS")

    # T22-T23: strategy_description - hem Row 9 hem Row 14 sözlüğü
    tampered = json.loads(json.dumps(full))
    tampered["strategy_candidates"][0]["strategy_description"] = row9_phrase_text
    result = write_and_validate(tampered, "strategy_desc_row9.json")
    assert result["valid"] is False
    print("T22 strategy_description with Row 9 phrase rejected:", "PASS")

    tampered = json.loads(json.dumps(full))
    tampered["strategy_candidates"][0]["strategy_description"] = row14_phrase_text
    result = write_and_validate(tampered, "strategy_desc_row14.json")
    assert result["valid"] is False
    print("T23 strategy_description with Row 14 phrase rejected:", "PASS")

    # T24: strategy grounded_explanation - Türkçe büyük harf + diyakritik varyant
    tampered = json.loads(json.dumps(full))
    tampered["strategy_candidates"][0]["grounded_explanation"] = row14_phrase_text_tr_diacritics
    result = write_and_validate(tampered, "strategy_ge_diacritics.json")
    assert result["valid"] is False
    print("T24 strategy grounded_explanation with Turkish-diacritic/uppercase forbidden phrase rejected (normalize_text_tr robustness):", "PASS")

    # T25: suggestion grounded_explanation - Row 9 phrase
    tampered = json.loads(json.dumps(with_suggestion))
    tampered["risk_strategy_agent_suggestions"][0]["grounded_explanation"] = row9_phrase_text
    result = write_and_validate(tampered, "suggestion_ge_row9.json")
    assert result["valid"] is False
    print("T25 suggestion grounded_explanation with Row 9 phrase rejected:", "PASS")

    # T26: POZİTİF KONTROL - kontrollü belirsizlik ifadesi (yanlış pozitif olmamalı)
    tampered = json.loads(json.dumps(full))
    identified = next(r for r in tampered["risk_candidates"] if r["risk_kind"] == "identified")
    identified["grounded_explanation"] = safe_uncertainty_text
    result = write_and_validate(tampered, "safe_uncertainty.json")
    if not result["valid"]:
        for e in result["errors"]:
            print("-", e)
    assert result["valid"] is True
    print("T26 Controlled-uncertainty language ('değerlendirilemedi') NOT falsely rejected (positive control):", "PASS")

    # T27: agent bypass edilerek doğrudan validator'a verilen bozuk kayıt
    # (T19-T26'nın tamamı zaten agent'ı hiç çağırmadan doğrudan pending
    # JSON'ı tamper edip validator'a veriyor - agent bypass senaryosunun
    # ta kendisi. Burada ayrıca AÇIKÇA doğrulanıyor.)
    tampered = json.loads(json.dumps(offline))
    tampered["risk_candidates"] = [
        {
            "risk_id": "risk_bypass_001", "risk_kind": "gap", "risk_type": "deadline_not_computable",
            "source_issue_id": "issue_002", "source_fact_ids": [], "source_claim_ids": [],
            "source_counterargument_ids": [], "source_rebuttal_ids": [], "source_evidence_candidate_ids": [],
            "source_legal_research_ids": [], "source_case_law_ids": [], "source_timeline_event_ids": [],
            "source_deadline_ids": [], "absence_basis": "deadline_not_computable",
            "reason_code": "deterministic_gap_deadline_not_computable",
            "risk_description": row14_phrase_text, "grounded_explanation": None,
            "risk_review_state": "needs_review", "requires_human_review": True, "status": "candidate",
            "flags": {name: False for name in DETERMINISTIC_FLAG_NAMES},
        }
    ]
    result = write_and_validate(tampered, "agent_bypass.json")
    assert result["valid"] is False
    print("T27 Agent tamamen bypass edilip doğrudan validator'a verilen bozuk kayıt reddedildi:", "PASS")

    # ==============================================================
    # REMEDIATION madde 3: provision_resolved_version_unknown senaryosu
    # ==============================================================

    from risk_strategy_discovery import build_issue_risk_context

    synth_fact_index = fact_context["facts"]

    synth_active_documents_index = build_active_documents_index(case_id)

    synth_issue = {
        "issue_id": "issue_001", "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
        "source_timeline_event_ids": [], "source_deadline_ids": [],
    }

    synth_research_index = {
        "r_vunknown": {
            "research_id": "r_vunknown", "source_issue_id": "issue_001",
            "finding_status": "provision_resolved_version_unknown",
        },
    }

    menu, _w = build_issue_risk_context(
        synth_issue, synth_fact_index, synth_active_documents_index, {}, {}, synth_research_index,
        {}, {}, {}, {}, {}, {}, {}, {},
    )

    assert "r_vunknown" in menu["eligible_legal_research_ids"]

    print("T28 provision_resolved_version_unknown research allowlist'e alınır:", "PASS")

    identified_with_research = json.dumps([
        {
            "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
            "reason_code": "explicit_textual_match", "grounded_explanation": "Guvenli metin.",
            "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
            "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
            "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
        }
    ], ensure_ascii=False)

    # Bu kısım yalnız flag-hesaplama davranışını doğrudan (engine
    # çağırmadan) doğruluyor: gerçek case_0001 research.json'ında
    # provision_resolved_version_unknown YOK, bu yüzden flag hesabı
    # policy fonksiyonu üzerinden izole test ediliyor.
    from risk_strategy_policy import compute_depends_on_unresolved_authority_version

    ref_set_with_research = {"source_legal_research_ids": ["r_vunknown"]}

    flag_value = compute_depends_on_unresolved_authority_version(
        ref_set_with_research, synth_research_index,
    )

    assert flag_value is True

    print("T29 provision_resolved_version_unknown -> depends_on_unresolved_authority_version=True:", "PASS")

    # Validator: flag yanlış (False) olarak kaydedilirse reddedilmeli
    tampered = json.loads(json.dumps(full))
    identified = next(r for r in tampered["risk_candidates"] if r["risk_kind"] == "identified")
    identified["source_legal_research_ids"] = []  # zaten yok ama flag'i manuel bozuyoruz
    identified["flags"] = dict(identified["flags"])
    identified["flags"]["depends_on_unresolved_authority_version"] = True  # yanlış - gerçek discovery bunu False bulmalı
    result = write_and_validate(tampered, "version_flag_wrong.json")
    assert result["valid"] is False
    print("T30 Yanlış depends_on_unresolved_authority_version bağımsız yeniden hesaplamayla reddedilir:", "PASS")

    temp_dir.cleanup()

    print()
    print("Case:", case_id)
    print("Canonical issue count:", len(issue_context["issue_index"]))
    print()
    print("======================================")
    print(" RISK / STRATEGY VALIDATOR V1: 30/30 PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Risk/Strategy Validator V1")

    parser.add_argument("--case", dest="case_id", default="case_0001")

    parser.add_argument("--risk-strategy", dest="risk_strategy_path", default=None)

    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test or args.risk_strategy_path is None:

        run_self_test(args.case_id)

        return

    print()
    print("======================================")
    print(" VERGİ AI - RISK / STRATEGY VALIDATOR V1")
    print("======================================")

    try:

        result = validate_risk_strategy_analysis(
            arguments_path=Path(args.risk_strategy_path),
            expected_case_id=args.case_id,
            raise_on_error=False,
        )

    except Exception as error:

        print()
        print("VALIDATION ERROR")
        print(error)
        print()
        print("======================================")
        print(" RISK / STRATEGY VALIDATOR V1: FAIL")
        print("======================================")
        sys.exit(1)

    print()
    print("Case:", result["case_id"])
    print("Coverage count:", result["coverage_count"])
    print("Risk count:", result["risk_count"])

    if result["errors"]:

        print()
        print("Errors:")

        for error in result["errors"]:

            print("-", error)

    print()
    print("======================================")

    if result["valid"]:

        print(" RISK / STRATEGY VALIDATOR V1: PASS")

    else:

        print(" RISK / STRATEGY VALIDATOR V1: FAIL")
        sys.exit(1)

    print("======================================")


if __name__ == "__main__":

    main()
