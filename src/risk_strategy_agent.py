# ============================================================
# VERGİ AI - RISK / STRATEGY AGENT V1
#
# AMAÇ: LLM'i yalnız DETERMİNİSTİK allowlist içinden identified-risk
# adayı SEÇİMİNE ve suggestion önerisine sınırlar. Agent gap-risk
# ÜRETEMEZ (gap yalnız deterministik engine'e aittir). Ana metinler
# (risk_description/strategy_description) DETERMİNİSTİK TEMPLATE
# ile üretilir - agent yalnız grounded_explanation gibi sınırlı
# serbest-metin alanlarını doldurur, o da ağır bir bağımsız
# text-safety battery'sinden geçer.
#
# Bu modül GERÇEK bir network çağrısı YAPMAZ - gerçek çağrı yalnız
# AnthropicRiskStrategyLLMClient.generate()'in İLK satırında,
# --with-agent VE --allow-network ikisi birden doğruyken denenir.
# ============================================================

import json
import os

from risk_strategy_policy import (
    REF_FIELDS,
    IDENTIFIED_RISK_TYPES,
    ARGUMENT_REASON_CODES,
    SUGGESTION_TYPES,
    MAX_GROUNDED_EXPLANATION_LENGTH,
    render_identified_risk_description,
    collect_citable_texts,
    check_forbidden_phrases,
    find_smuggled_ids,
    find_unverified_quotes,
    find_unsupported_numeric_tokens,
    collect_ref_ids,
)


MAX_ITEMS_PER_STAGE = 50


# ============================================================
# FAKE / REAL LLM CLIENT
# ============================================================

class FakeRiskStrategyLLMClient:

    # --------------------------------------------------------
    # Bu client GERÇEK BİR NETWORK ÇAĞRISI YAPMAZ.
    # --------------------------------------------------------

    def __init__(self, response_text=None, response_sequence=None, raise_error=None):

        self.response_text = response_text if response_text is not None else "[]"
        self.response_sequence = response_sequence
        self.raise_error = raise_error
        self.last_prompt = None
        self.call_count = 0

    def generate(self, prompt):

        self.last_prompt = prompt
        self.call_count += 1

        if self.raise_error is not None:

            raise self.raise_error

        if self.response_sequence is not None:

            index = min(self.call_count - 1, len(self.response_sequence) - 1)

            return self.response_sequence[index]

        return self.response_text


class AnthropicRiskStrategyLLMClient:

    def __init__(self):

        self._client = None

    def generate(self, prompt):

        api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:

            raise RuntimeError(
                "ANTHROPIC_API_KEY tanımlı değil - gerçek Risk/Strategy "
                "Agent çağrısı yapılamaz (fail-closed, network denenmeden)."
            )

        # Lazy import - yalnız gerçek bir çağrı denendiğinde.
        import anthropic

        if self._client is None:

            self._client = anthropic.Anthropic(api_key=api_key)

        response = self._client.messages.create(
            model="claude-sonnet-5",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text


def call_stage(llm_client, prompt):

    raw_text = llm_client.generate(prompt)

    return parse_agent_array_response(raw_text)


def parse_agent_array_response(raw_text):

    parsed = json.loads(raw_text)

    if not isinstance(parsed, list):

        raise json.JSONDecodeError("Agent cevabı bir JSON array değil.", raw_text, 0)

    return parsed


# ============================================================
# SHARED TEXT-SAFETY CHECK (AGENT TARAFI)
# ============================================================

def check_text_safety(text, max_length, declared_ref_ids, citable_texts, all_known_ids):

    if not isinstance(text, str) or not text.strip():

        return "metin boş olamaz"

    if len(text) > max_length:

        return "metin uzunluk sınırını aşıyor"

    forbidden = check_forbidden_phrases("_", text)

    if forbidden:

        return "forbidden phrase içeriyor"

    smuggled = find_smuggled_ids(text, declared_ref_ids, all_known_ids)

    if smuggled:

        return f"smuggled ID içeriyor: {smuggled}"

    unverified_quotes = find_unverified_quotes(text, citable_texts)

    if unverified_quotes:

        return f"doğrulanamayan alıntı içeriyor: {unverified_quotes}"

    unsupported = find_unsupported_numeric_tokens(text, citable_texts)

    if unsupported:

        return f"desteklenmeyen tarih/tutar/süre/yıl içeriyor: {unsupported}"

    return None


# ============================================================
# STAGE 1: IDENTIFIED RISK
# ============================================================

ALLOWED_IDENTIFIED_RISK_KEYS = {
    "source_issue_id",
    "risk_type",
    "reason_code",
    "grounded_explanation",
} | set(REF_FIELDS)


def build_identified_risk_prompt(allowlist_by_issue):

    payload = []

    for issue_id, menu in allowlist_by_issue.items():

        if not menu["has_minimum_grounding"]:
            continue

        payload.append(
            {
                "issue_id": issue_id,
                "eligible_fact_ids": menu["eligible_fact_ids"],
                "eligible_evidence_candidate_ids": menu["eligible_evidence_candidate_ids"],
                "eligible_legal_research_ids": menu["eligible_legal_research_ids"],
                "eligible_case_law_ids": menu["eligible_case_law_ids"],
                "eligible_timeline_event_ids": menu["eligible_timeline_event_ids"],
                "eligible_deadline_ids": menu["eligible_deadline_ids"],
                "eligible_claim_ids": menu["eligible_claim_ids"],
                "eligible_counterargument_ids": menu["eligible_counterargument_ids"],
                "eligible_rebuttal_ids": menu["eligible_rebuttal_ids"],
                "allowed_risk_types": sorted(IDENTIFIED_RISK_TYPES),
            }
        )

    return json.dumps(payload, ensure_ascii=False)


def extract_ref_set(item):

    return {field: list(item.get(field) or []) for field in REF_FIELDS}


def validate_ref_set_against_menu(ref_set, menu):

    menu_by_field = {
        "source_fact_ids": set(menu["eligible_fact_ids"]),
        "source_evidence_candidate_ids": set(menu["eligible_evidence_candidate_ids"]),
        "source_legal_research_ids": set(menu["eligible_legal_research_ids"]),
        "source_case_law_ids": set(menu["eligible_case_law_ids"]),
        "source_timeline_event_ids": set(menu["eligible_timeline_event_ids"]),
        "source_deadline_ids": set(menu["eligible_deadline_ids"]),
        "source_claim_ids": set(menu["eligible_claim_ids"]),
        "source_counterargument_ids": set(menu["eligible_counterargument_ids"]),
        "source_rebuttal_ids": set(menu["eligible_rebuttal_ids"]),
    }

    for field, allowed_ids in menu_by_field.items():

        for ref_id in ref_set.get(field, []):

            if ref_id not in allowed_ids:

                return (
                    f"allowlist dışı referans ({field}): {ref_id} "
                    "(agent allowlist escape denemesi)"
                )

    return None


def validate_identified_risk_shape(item, allowlist_by_issue):

    if not isinstance(item, dict):

        return (False, None, None, "candidate dict değil")

    forbidden = set(item.keys()) - ALLOWED_IDENTIFIED_RISK_KEYS

    if forbidden:

        return (
            False, item.get("source_issue_id"), None,
            f"izin verilmeyen alan(lar): {sorted(forbidden)}",
        )

    issue_id = item.get("source_issue_id")

    menu = allowlist_by_issue.get(issue_id)

    if menu is None or not menu["has_minimum_grounding"]:

        return (False, issue_id, None, f"source_issue_id allowlist'te yok: {issue_id}")

    risk_type = item.get("risk_type")

    if risk_type not in IDENTIFIED_RISK_TYPES:

        return (False, issue_id, None, f"geçersiz/izin verilmeyen risk_type: {risk_type}")

    reason_code = item.get("reason_code")

    if reason_code not in ARGUMENT_REASON_CODES:

        return (False, issue_id, None, f"geçersiz reason_code: {reason_code}")

    ref_set = extract_ref_set(item)

    escape_error = validate_ref_set_against_menu(ref_set, menu)

    if escape_error:

        return (False, issue_id, None, escape_error)

    if not collect_ref_ids(ref_set):

        return (
            False, issue_id, None,
            "minimum grounding ihlali: en az bir geçerli kaynak zorunlu",
        )

    return (True, issue_id, {"ref_set": ref_set, "menu": menu}, None)


def run_identified_risk_stage(
    raw_items,
    allowlist_by_issue,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
    all_known_ids,
    start_index,
):

    warnings = []

    accepted = []

    seen_keys = set()

    per_issue = {}

    for item in raw_items[:MAX_ITEMS_PER_STAGE]:

        ok, issue_id, resolved, reason = validate_identified_risk_shape(
            item, allowlist_by_issue
        )

        bucket = per_issue.setdefault(issue_id, {"raw": 0, "rejected": 0})

        bucket["raw"] += 1

        if not ok:

            bucket["rejected"] += 1

            warnings.append(f"Identified risk signal reddedildi ({reason}).")

            continue

        ref_set = resolved["ref_set"]

        citable_texts = collect_citable_texts(
            ref_set, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index,
        )

        declared_ids = collect_ref_ids(ref_set)

        text_error = check_text_safety(
            item.get("grounded_explanation"),
            MAX_GROUNDED_EXPLANATION_LENGTH,
            declared_ids,
            citable_texts,
            all_known_ids,
        )

        if text_error:

            bucket["rejected"] += 1

            warnings.append(f"Identified risk signal reddedildi ({text_error}).")

            continue

        dedup_key = (
            issue_id,
            item["risk_type"],
            tuple(sorted(declared_ids)),
        )

        if dedup_key in seen_keys:

            bucket["rejected"] += 1

            warnings.append("Duplicate identified risk signal atlandı (dedup).")

            continue

        seen_keys.add(dedup_key)

        accepted.append((item, ref_set, issue_id))

    finalized = []

    for index, (item, ref_set, issue_id) in enumerate(accepted, start=start_index):

        finalized.append(
            {
                "risk_id": f"risk_identified_{index:03d}",
                "risk_kind": "identified",
                "risk_type": item["risk_type"],
                "source_issue_id": issue_id,
                **ref_set,
                "absence_basis": None,
                "reason_code": item["reason_code"],
                "risk_description": render_identified_risk_description(item["risk_type"]),
                "grounded_explanation": item["grounded_explanation"],
                "risk_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
            }
        )

    return (finalized, warnings, per_issue)


# ============================================================
# STAGE 3: SUGGESTIONS
# ============================================================

ALLOWED_SUGGESTION_KEYS = {
    "suggestion_type",
    "source_issue_id",
    "related_reference_ids",
    "reason_code",
    "grounded_explanation",
}


def build_suggestion_prompt(issue_index, finalized_risks, finalized_strategies):

    payload = {
        "issues": sorted(issue_index.keys()),
        "risk_ids": [r["risk_id"] for r in finalized_risks],
        "strategy_ids": [s["strategy_id"] for s in finalized_strategies],
        "allowed_suggestion_types": sorted(SUGGESTION_TYPES),
    }

    return json.dumps(payload, ensure_ascii=False)


def validate_suggestion_shape(item, issue_index, known_reference_ids):

    if not isinstance(item, dict):

        return (False, None, "candidate dict değil")

    forbidden = set(item.keys()) - ALLOWED_SUGGESTION_KEYS

    if forbidden:

        return (False, None, f"izin verilmeyen alan(lar): {sorted(forbidden)}")

    suggestion_type = item.get("suggestion_type")

    if suggestion_type not in SUGGESTION_TYPES:

        return (False, None, f"geçersiz suggestion_type: {suggestion_type}")

    issue_id = item.get("source_issue_id")

    if issue_id is not None and issue_id not in issue_index:

        return (False, None, f"bilinmeyen source_issue_id: {issue_id}")

    reason_code = item.get("reason_code")

    if reason_code not in ARGUMENT_REASON_CODES:

        return (False, None, f"geçersiz reason_code: {reason_code}")

    related_reference_ids = item.get("related_reference_ids", [])

    if not isinstance(related_reference_ids, list):

        return (False, None, "related_reference_ids liste olmalı")

    for ref_id in related_reference_ids:

        if ref_id not in known_reference_ids:

            return (False, None, f"bilinmeyen related_reference_id: {ref_id}")

    return (True, issue_id, None)


def run_suggestion_stage(
    raw_items,
    issue_index,
    known_reference_ids,
    start_index,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
):

    warnings = []

    accepted = []

    per_issue = {}

    for item in raw_items[:MAX_ITEMS_PER_STAGE]:

        ok, issue_id, reason = validate_suggestion_shape(
            item, issue_index, known_reference_ids
        )

        bucket = per_issue.setdefault(issue_id, {"raw": 0, "rejected": 0})

        bucket["raw"] += 1

        if not ok:

            bucket["rejected"] += 1

            warnings.append(f"Suggestion signal reddedildi ({reason}).")

            continue

        grounded_explanation = item.get("grounded_explanation")

        related_reference_ids = item.get("related_reference_ids", [])

        classified_ref_set = {
            "source_fact_ids": [r for r in related_reference_ids if r in fact_index],
            "source_evidence_candidate_ids": [
                r for r in related_reference_ids if r in evidence_candidate_index
            ],
            "source_legal_research_ids": [
                r for r in related_reference_ids if r in research_index
            ],
            "source_case_law_ids": [
                r for r in related_reference_ids if r in case_law_decision_index
            ],
        }

        citable_texts = collect_citable_texts(
            classified_ref_set, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index,
        )

        text_error = check_text_safety(
            grounded_explanation,
            MAX_GROUNDED_EXPLANATION_LENGTH,
            set(related_reference_ids),
            citable_texts,
            known_reference_ids,
        )

        if text_error:

            bucket["rejected"] += 1

            warnings.append(f"Suggestion signal reddedildi ({text_error}).")

            continue

        accepted.append((item, issue_id))

    finalized = []

    for index, (item, issue_id) in enumerate(accepted, start=start_index):

        finalized.append(
            {
                "suggestion_id": f"risk_strategy_suggestion_{index:03d}",
                "suggestion_type": item["suggestion_type"],
                "source_issue_id": issue_id,
                "related_reference_ids": list(item.get("related_reference_ids", [])),
                "reason_code": item["reason_code"],
                "grounded_explanation": item["grounded_explanation"],
                "suggestion_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
            }
        )

    return (finalized, warnings, per_issue)


if __name__ == "__main__":

    print("risk_strategy_agent.py - self-test yok, bkz. risk_strategy_validator.py/risk_strategy_engine.py")
