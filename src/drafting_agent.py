# ============================================================
# VERGİ AI - DRAFTING AGENT V1
#
# AMAÇ: LLM'i yalnız DETERMİNİSTİK allowlist içinden kaynak SEÇİMİNE,
# izin verilen paraphrase/section metni üretimine ve izole suggestion
# önerisine sınırlar. Agent coverage/selection_scope/execution_state/
# block_reason/hash/fingerprint/review_state ÜRETEMEZ - bunlar
# TAMAMEN deterministik motora/validator'a aittir.
#
# Bu modül GERÇEK bir network çağrısı YAPMAZ - gerçek çağrı yalnız
# AnthropicDraftingLLMClient.generate()'in İLK satırında, --with-agent
# VE --allow-network ikisi birden doğruyken denenir.
# ============================================================

import json
import os

from drafting_policy import (
    REF_FIELDS,
    SECTION_TYPES,
    RENDERING_MODES,
    SUGGESTION_TYPES,
    REASON_CODES,
    REQUEST_AUTHORITY_REQUIRED_SECTION_TYPES,
    check_forbidden_phrases_context,
    find_id_reference_issues,
    find_unverified_quotes,
    find_unsupported_numeric_tokens,
    find_refs_missing_hedge,
    is_ref_direct,
    compute_request_authorization,
    is_valid_request_input,
    has_valid_lawyer_text,
    collect_citable_texts,
)


MAX_ITEMS_PER_STAGE = 50

MAX_SECTION_TEXT_LENGTH = 4000

MAX_GROUNDED_EXPLANATION_LENGTH = 1000


# ============================================================
# FAKE / REAL LLM CLIENT
# ============================================================

class FakeDraftingLLMClient:

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


class AnthropicDraftingLLMClient:

    def __init__(self):

        self._client = None

    def generate(self, prompt):

        api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:

            raise RuntimeError(
                "ANTHROPIC_API_KEY tanımlı değil - gerçek Drafting Agent "
                "çağrısı yapılamaz (fail-closed, network denenmeden)."
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
# STAGE 1: SECTION ADAYI (yalnız SEÇİLMİŞ, uygun kaynağı olan issue'lar)
# ============================================================

ALLOWED_SECTION_KEYS = {"source_issue_id", "section_type", "section_text", "refs"}

ALLOWED_REF_KEYS = {"source_field", "source_id", "rendering_mode", "claim_span"}


def build_section_prompt(allowlist_by_issue, selected_issue_ids, section_types_requested):

    payload = []

    for issue_id in (selected_issue_ids or []):

        menu = allowlist_by_issue.get(issue_id)

        if menu is None or not menu["has_any_eligible_source"]:
            continue

        payload.append(
            {
                "issue_id": issue_id,
                "allowed_section_types": sorted(section_types_requested),
                "eligible_fact_ids": menu["eligible_fact_ids"],
                "direct_fact_ids": menu["direct_fact_ids"],
                "eligible_timeline_event_ids": menu["eligible_timeline_event_ids"],
                "eligible_deadline_ids": menu["eligible_deadline_ids"],
                "eligible_legal_research_ids": menu["eligible_legal_research_ids"],
                "eligible_case_law_ids": menu["eligible_case_law_ids"],
                "eligible_evidence_candidate_ids": menu["eligible_evidence_candidate_ids"],
                "eligible_claim_ids": menu["eligible_claim_ids"],
                "eligible_counterargument_ids": menu["eligible_counterargument_ids"],
                "eligible_rebuttal_ids": menu["eligible_rebuttal_ids"],
                "eligible_risk_ids": menu["eligible_risk_ids"],
                "eligible_strategy_ids": menu["eligible_strategy_ids"],
            }
        )

    return json.dumps(payload, ensure_ascii=False)


def _menu_field_for_source_field(menu, source_field):

    mapping = {
        "source_fact_ids": set(menu["eligible_fact_ids"]),
        "source_timeline_event_ids": set(menu["eligible_timeline_event_ids"]),
        "source_deadline_ids": set(menu["eligible_deadline_ids"]),
        "source_legal_research_ids": set(menu["eligible_legal_research_ids"]),
        "source_case_law_ids": set(menu["eligible_case_law_ids"]),
        "source_evidence_candidate_ids": set(menu["eligible_evidence_candidate_ids"]),
        "source_claim_ids": set(menu["eligible_claim_ids"]),
        "source_counterargument_ids": set(menu["eligible_counterargument_ids"]),
        "source_rebuttal_ids": set(menu["eligible_rebuttal_ids"]),
        "source_risk_ids": set(menu["eligible_risk_ids"]),
        "source_strategy_ids": set(menu["eligible_strategy_ids"]),
    }

    return mapping.get(source_field, set())


def validate_ref_shape(ref, menu):

    if not isinstance(ref, dict):

        return "ref dict değil"

    forbidden = set(ref.keys()) - ALLOWED_REF_KEYS

    if forbidden:

        return f"ref izin verilmeyen alan(lar): {sorted(forbidden)}"

    source_field = ref.get("source_field")

    if source_field not in REF_FIELDS:

        return f"geçersiz source_field: {source_field}"

    rendering_mode = ref.get("rendering_mode")

    if rendering_mode not in RENDERING_MODES:

        return f"geçersiz rendering_mode: {rendering_mode}"

    if rendering_mode == "direct_quote" and source_field != "source_fact_ids":

        return "direct_quote yalnız source_fact_ids için izinlidir (doğrulanabilir tam metin yok)"

    source_id = ref.get("source_id")

    allowed_ids = _menu_field_for_source_field(menu, source_field)

    if source_id not in allowed_ids:

        return f"allowlist dışı referans ({source_field}): {source_id} (agent allowlist escape denemesi)"

    if rendering_mode == "direct_quote" and source_id not in menu.get("direct_fact_ids", []):

        return f"direct_quote yalnız verified fact için izinlidir: {source_id}"

    return None


def validate_section_shape(item, allowlist_by_issue, section_types_requested):

    if not isinstance(item, dict):

        return (False, None, None, "candidate dict değil")

    forbidden = set(item.keys()) - ALLOWED_SECTION_KEYS

    if forbidden:

        return (False, item.get("source_issue_id"), None, f"izin verilmeyen alan(lar): {sorted(forbidden)}")

    issue_id = item.get("source_issue_id")

    menu = allowlist_by_issue.get(issue_id)

    if menu is None or not menu["has_any_eligible_source"]:

        return (False, issue_id, None, f"source_issue_id allowlist'te yok: {issue_id}")

    section_type = item.get("section_type")

    if section_type not in section_types_requested:

        return (False, issue_id, None, f"izin verilmeyen/istenmeyen section_type: {section_type}")

    refs = item.get("refs")

    if not isinstance(refs, list) or not refs:

        return (False, issue_id, None, "en az bir geçerli kaynak referansı (refs) zorunludur")

    for ref in refs:

        error = validate_ref_shape(ref, menu)

        if error:

            return (False, issue_id, None, error)

    return (True, issue_id, {"menu": menu, "refs": refs}, None)


def run_section_stage(
    raw_items, allowlist_by_issue, section_types_requested, fact_index,
    all_known_ids, lawyer_provided_text, direct_argument_ids, start_index,
    request_input=None, direct_lookup=None,
):

    direct_lookup = direct_lookup or {}

    warnings = []

    accepted = []

    seen_keys = set()

    per_issue = {}

    for item in raw_items[:MAX_ITEMS_PER_STAGE]:

        ok, issue_id, resolved, reason = validate_section_shape(
            item, allowlist_by_issue, section_types_requested,
        )

        bucket = per_issue.setdefault(issue_id, {"raw": 0, "rejected": 0})

        bucket["raw"] += 1

        if not ok:

            bucket["rejected"] += 1

            warnings.append(f"Section adayı reddedildi ({reason}).")

            continue

        refs = resolved["refs"]

        section_type = item["section_type"]

        declared_ids = {ref["source_id"] for ref in refs}

        fact_ids_in_refs = [ref["source_id"] for ref in refs if ref["source_field"] == "source_fact_ids"]

        citable_texts = collect_citable_texts(fact_index, fact_ids_in_refs)

        section_text = item.get("section_text")

        if not isinstance(section_text, str) or not section_text.strip():

            bucket["rejected"] += 1

            warnings.append("Section adayı reddedildi (section_text boş).")

            continue

        if len(section_text) > MAX_SECTION_TEXT_LENGTH:

            bucket["rejected"] += 1

            warnings.append("Section adayı reddedildi (section_text uzunluk sınırını aşıyor).")

            continue

        # ---- Q1 (dayanak var mı?) vs Q2 (avukat ÜRETİMİ istedi mi?) -
        # KARIŞTIRILMAZ (remediation madde 3). Confirmed argüman TEK
        # BAŞINA Q2'ye asla EVET veremez. ----

        is_grounded_advocacy = (
            has_valid_lawyer_text(lawyer_provided_text)
            or is_valid_request_input(request_input)
            or any(ref["source_id"] in direct_argument_ids for ref in refs)
        )

        request_authorized = compute_request_authorization(request_input, lawyer_provided_text)

        forbidden_errors = check_forbidden_phrases_context(
            issue_id, section_text, section_type, is_grounded_advocacy,
        )

        if forbidden_errors:

            bucket["rejected"] += 1

            warnings.append(f"Section adayı reddedildi ({forbidden_errors[0]}).")

            continue

        id_issues = find_id_reference_issues(section_text, declared_ids, all_known_ids)

        if id_issues["fabricated"]:

            bucket["rejected"] += 1

            warnings.append(
                f"Section adayı reddedildi (canonical'da HİÇ var olmayan, uydurma ID "
                f"içeriyor: {id_issues['fabricated']})."
            )

            continue

        if id_issues["smuggled"]:

            bucket["rejected"] += 1

            warnings.append(
                f"Section adayı reddedildi (gerçek ama başka issue'ya ait veya bu kayıt "
                f"için beyan edilmemiş ID içeriyor: {id_issues['smuggled']})."
            )

            continue

        unverified_quotes = find_unverified_quotes(section_text, citable_texts)

        if unverified_quotes:

            bucket["rejected"] += 1

            warnings.append(f"Section adayı reddedildi (doğrulanamayan alıntı: {unverified_quotes}).")

            continue

        unsupported = find_unsupported_numeric_tokens(section_text, citable_texts)

        if unsupported:

            bucket["rejected"] += 1

            warnings.append(f"Section adayı reddedildi (desteklenmeyen tarih/tutar/süre/yıl: {unsupported}).")

            continue

        if section_type in REQUEST_AUTHORITY_REQUIRED_SECTION_TYPES and not request_authorized:

            bucket["rejected"] += 1

            warnings.append(
                "Section adayı reddedildi (talep yetkisi yok: yalnız request_input "
                "veya lawyer_provided_text bir 'request' section'ının ÜRETİMİNİ "
                "yetkilendirebilir - confirmed argüman/risk/strateji TEK BAŞINA "
                "yeterli değildir)."
            )

            continue

        # ---- BELİRSİZLİK SUNUMU: flagged (direct OLMAYAN) her ref,
        # kendi claim_span'i içinde AÇIK bir belirsizlik ifadesi taşımalı
        # (madde F/C - flag tek başına yeterli değil). ----

        flagged_refs = [
            ref for ref in refs if not is_ref_direct(ref, [issue_id], direct_lookup)
        ]

        missing_hedge = find_refs_missing_hedge(section_text, flagged_refs)

        if missing_hedge:

            bucket["rejected"] += 1

            warnings.append(
                f"Section adayı reddedildi (flagged kaynak(lar) için claim_span "
                f"içinde belirsizlik ifadesi eksik/geçersiz: {missing_hedge})."
            )

            continue

        dedup_key = (issue_id, section_type, tuple(sorted(declared_ids)))

        if dedup_key in seen_keys:

            bucket["rejected"] += 1

            warnings.append("Duplicate section adayı atlandı (dedup).")

            continue

        seen_keys.add(dedup_key)

        accepted.append((item, refs, issue_id))

    finalized_sections = []

    finalized_refs = []

    for index, (item, refs, issue_id) in enumerate(accepted, start=start_index):

        section_id = f"draft_section_{index:03d}"

        finalized_sections.append(
            {
                "section_id": section_id,
                "source_issue_ids": [issue_id],
                "section_type": item["section_type"],
                "section_text": item["section_text"],
                "contains_unreviewed_source": None,  # engine tarafından doldurulur
                "section_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
                "submission_status": "draft_only",
            }
        )

        for ref_index, ref in enumerate(refs, start=1):

            finalized_refs.append(
                {
                    "source_ref_id": f"{section_id}_ref_{ref_index:03d}",
                    "section_id": section_id,
                    "claim_span": ref.get("claim_span"),
                    "source_field": ref["source_field"],
                    "source_id": ref["source_id"],
                    "rendering_mode": ref["rendering_mode"],
                }
            )

    return (finalized_sections, finalized_refs, warnings, per_issue)


# ============================================================
# STAGE 2: SUGGESTIONS
# ============================================================

ALLOWED_SUGGESTION_KEYS = {
    "suggestion_type", "source_issue_id", "related_reference_ids", "reason_code",
    "grounded_explanation",
}


def build_suggestion_prompt(issue_ids, finalized_sections):

    payload = {
        "issues": sorted(issue_ids),
        "section_ids": [s["section_id"] for s in finalized_sections],
        "allowed_suggestion_types": sorted(SUGGESTION_TYPES),
    }

    return json.dumps(payload, ensure_ascii=False)


def validate_suggestion_shape(item, issue_ids, known_reference_ids):

    if not isinstance(item, dict):

        return (False, None, "candidate dict değil")

    forbidden = set(item.keys()) - ALLOWED_SUGGESTION_KEYS

    if forbidden:

        return (False, None, f"izin verilmeyen alan(lar): {sorted(forbidden)}")

    suggestion_type = item.get("suggestion_type")

    if suggestion_type not in SUGGESTION_TYPES:

        return (False, None, f"geçersiz suggestion_type: {suggestion_type}")

    issue_id = item.get("source_issue_id")

    if issue_id is not None and issue_id not in issue_ids:

        return (False, None, f"bilinmeyen source_issue_id: {issue_id}")

    reason_code = item.get("reason_code")

    if reason_code not in REASON_CODES:

        return (False, None, f"geçersiz reason_code: {reason_code}")

    related_reference_ids = item.get("related_reference_ids", [])

    if not isinstance(related_reference_ids, list):

        return (False, None, "related_reference_ids liste olmalı")

    for ref_id in related_reference_ids:

        if ref_id not in known_reference_ids:

            return (False, None, f"bilinmeyen related_reference_id: {ref_id}")

    return (True, issue_id, None)


def run_suggestion_stage(raw_items, issue_ids, known_reference_ids, start_index, fact_index=None):
    """
    Suggestion'lar AYRI bir dizide olması nedeniyle güvenlik kontrollerinden
    MUAF DEĞİLDİR (remediation madde 2/E) - section'larla AYNI tam bağımsız
    text-safety battery'sini uygular: forbidden-phrase + ID-smuggling +
    doğrulanamayan alıntı + desteklenmeyen tarih/tutar/süre/yıl.
    """

    fact_index = fact_index or {}

    warnings = []

    accepted = []

    for item in raw_items[:MAX_ITEMS_PER_STAGE]:

        ok, issue_id, reason = validate_suggestion_shape(item, issue_ids, known_reference_ids)

        if not ok:

            warnings.append(f"Suggestion adayı reddedildi ({reason}).")

            continue

        grounded_explanation = item.get("grounded_explanation")

        if not isinstance(grounded_explanation, str) or not grounded_explanation.strip():

            warnings.append("Suggestion adayı reddedildi (grounded_explanation boş).")

            continue

        if len(grounded_explanation) > MAX_GROUNDED_EXPLANATION_LENGTH:

            warnings.append("Suggestion adayı reddedildi (grounded_explanation uzunluk sınırını aşıyor).")

            continue

        forbidden_errors = check_forbidden_phrases_context(
            issue_id, grounded_explanation, "argument_summary", False,
        )

        if forbidden_errors:

            warnings.append(f"Suggestion adayı reddedildi ({forbidden_errors[0]}).")

            continue

        related_reference_ids = item.get("related_reference_ids", [])

        fact_ids_in_refs = [r for r in related_reference_ids if r in fact_index]

        citable_texts = collect_citable_texts(fact_index, fact_ids_in_refs)

        id_issues = find_id_reference_issues(grounded_explanation, related_reference_ids, known_reference_ids)

        if id_issues["fabricated"]:

            warnings.append(
                f"Suggestion adayı reddedildi (canonical'da HİÇ var olmayan, uydurma ID "
                f"içeriyor: {id_issues['fabricated']})."
            )

            continue

        if id_issues["smuggled"]:

            warnings.append(
                f"Suggestion adayı reddedildi (gerçek ama başka issue'ya ait veya bu kayıt "
                f"için beyan edilmemiş ID içeriyor: {id_issues['smuggled']})."
            )

            continue

        unverified_quotes = find_unverified_quotes(grounded_explanation, citable_texts)

        if unverified_quotes:

            warnings.append(f"Suggestion adayı reddedildi (doğrulanamayan alıntı: {unverified_quotes}).")

            continue

        unsupported = find_unsupported_numeric_tokens(grounded_explanation, citable_texts)

        if unsupported:

            warnings.append(
                f"Suggestion adayı reddedildi (desteklenmeyen tarih/tutar/süre/yıl: {unsupported})."
            )

            continue

        accepted.append((item, issue_id))

    finalized = []

    for index, (item, issue_id) in enumerate(accepted, start=start_index):

        finalized.append(
            {
                "suggestion_id": f"drafting_suggestion_{index:03d}",
                "source_issue_id": issue_id,
                "related_reference_ids": list(item.get("related_reference_ids", [])),
                "suggestion_type": item["suggestion_type"],
                "reason_code": item["reason_code"],
                "grounded_explanation": item["grounded_explanation"],
                "suggestion_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
            }
        )

    return (finalized, warnings)


if __name__ == "__main__":

    print("drafting_agent.py - self-test yok, bkz. drafting_validator.py/drafting_engine.py")
