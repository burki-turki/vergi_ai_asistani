# ============================================================
# VERGİ AI - ARGUMENT AGENT V1
#
# AMAÇ
# ----
#
# Argument Discovery V1'in ürettiği deterministik "eligible
# reference menu" (issue başına allowlist) üzerinden, LLM'i
# ÜÇ AYRI DOĞRULANMIŞ AŞAMADA çalıştırmak:
#
#   1. Issue  -> Claim signals
#   2. Claim  -> Counterargument signals   (yalnız VALIDATED
#                                            claim ID'leri
#                                            üzerinden)
#   3. Counterargument -> Rebuttal signals (yalnız VALIDATED
#                                            counterargument
#                                            ID'leri üzerinden)
#   4. Suggestion signals (tüm finalize edilmiş context ile)
#
# Bir sonraki aşama BİR ÖNCEKİ aşamanın doğrulanmamış/geçici
# LLM-içi ID'lerine ASLA dayanamaz - yalnız engine tarafından
# finalize edilmiş, stable ID'ler kullanılır.
#
#
# FREE-TEXT SAFETY (Row 13'e özgü - Row 9-12'den FARKLI)
# ---------------------------------------------------------
#
# Row 9-12'nin aksine, Row 13 contract'ı claim_text/
# counterargument_text/rebuttal_text/grounded_explanation için
# LLM-generated candidate text'e İZİN VERİR. Ancak bu metin:
#
#   - her zaman needs_review başlar,
#   - yalnız deklare edilen source_*_ids referanslarına dayanır,
#   - uzunluk sınırına tabidir,
#   - allowlist DIŞINDA bilinen bir canonical ID içeremez
#     (citation/metadata smuggling guard),
#   - içindeki HERHANGİ bir tırnak-içi alıntı, referans edilen
#     kaynaklarda BİREBİR bulunmalıdır (aksi halde tüm candidate
#     reddedilir),
#   - içindeki tarih/tutar benzeri token'lar referans edilen
#     kaynaklarda BİREBİR bulunmalıdır (aksi halde reddedilir).
#
# Agent hiçbir zaman: ID, count, hash, execution_state,
# depends_on_unconfirmed_evidence/authority, missing_legal_
# authority, review_state alanlarını SET EDEMEZ - bunlar
# yalnız deterministik engine tarafından hesaplanır/atanır.
#
#
# NETWORK SAFETY GATE (Row 9-12 ile birebir aynı desen)
# ---------------------------------------------------------
#
# Gerçek Anthropic API çağrısı için İKİ açık koşul gerekir:
# llm_client açıkça VERİLMEMİŞ olmalı VE network_allowed=True
# açıkça geçilmiş olmalı.
# ============================================================


import json
import os
import re


from issue_spotting_validator import FORBIDDEN_PHRASES

from timeline_consolidation_policy import normalize_text_tr

from argument_policy import (
    ARGUMENT_REASON_CODES,
    CLAIM_TYPES,
    COUNTER_TYPES,
    LEGAL_CLAIM_TYPES,
    LEGAL_COUNTER_TYPES,
    LEGAL_REBUTTAL_TYPES,
    MAX_ARGUMENT_TEXT_LENGTH,
    MAX_GROUNDED_EXPLANATION_LENGTH,
    REBUTTAL_TYPES,
    SUGGESTION_GROUNDING_SPEC,
    SUGGESTION_TYPES,
    classify_related_reference_ids,
    collect_citable_texts,
    compute_depends_on_unconfirmed_authority,
    compute_depends_on_unconfirmed_evidence,
    compute_missing_legal_authority,
    find_smuggled_ids,
    find_unsupported_numeric_tokens,
    find_unverified_quotes,
)


# ============================================================
# VERSION
# ============================================================

ARGUMENT_AGENT_VERSION = "1"

DEFAULT_AGENT_MODEL = "claude-sonnet-4-6"

MAX_ITEMS_PER_STAGE = 40

ALL_FORBIDDEN_PHRASES = tuple(FORBIDDEN_PHRASES)


REF_FIELDS = (
    "source_fact_ids",
    "source_evidence_candidate_ids",
    "source_legal_research_ids",
    "source_case_law_ids",
    "source_timeline_event_ids",
    "source_deadline_ids",
)


# ============================================================
# LLM SIGNAL - İZİN VERİLEN ALANLAR (AŞAMA BAŞINA)
# ============================================================

ALLOWED_CLAIM_KEYS = {
    "source_issue_id",
    "claim_type",
    "claim_text",
    "reason_code",
    "grounded_explanation",
} | set(REF_FIELDS)

ALLOWED_COUNTERARGUMENT_KEYS = {
    "source_claim_id",
    "counter_type",
    "counterargument_text",
    "reason_code",
    "grounded_explanation",
} | set(REF_FIELDS)

ALLOWED_REBUTTAL_KEYS = {
    "source_counterargument_id",
    "rebuttal_type",
    "rebuttal_text",
    "reason_code",
    "grounded_explanation",
} | set(REF_FIELDS)

ALLOWED_SUGGESTION_KEYS = {
    "source_issue_id",
    "suggestion_type",
    "source_claim_id",
    "source_counterargument_id",
    "related_reference_ids",
    "reason_code",
    "grounded_explanation",
}


# ============================================================
# EXCEPTION
# ============================================================

class ArgumentAgentError(Exception):
    pass


# ============================================================
# LLM CLIENT INTERFACE
# ============================================================

class AnthropicArgumentLLMClient:

    def __init__(self, model=None, api_key=None, max_tokens=2500):

        self.model = model or DEFAULT_AGENT_MODEL
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.max_tokens = max_tokens

    def generate(self, prompt):

        if not self.api_key:

            raise ArgumentAgentError(
                "ANTHROPIC_API_KEY bulunamadı. .env dosyasını kontrol et."
            )

        from anthropic import Anthropic

        client = Anthropic(api_key=self.api_key)

        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=build_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
        )

        text_parts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]

        result = "\n".join(text_parts).strip()

        if not result:

            raise ArgumentAgentError("LLM boş cevap döndürdü.")

        return result


class FakeArgumentLLMClient:

    # --------------------------------------------------------
    # Bu client GERÇEK BİR NETWORK ÇAĞRISI YAPMAZ.
    # --------------------------------------------------------

    def __init__(self, response_text=None, response_sequence=None, raise_error=None):

        self.response_text = (
            response_text if response_text is not None else "[]"
        )
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


# ============================================================
# SYSTEM PROMPT
# ============================================================

def build_system_prompt():

    return (
        "Sen bir vergi hukuku uyuşmazlık dosyasında, canonical "
        "issue/claim/counterargument context'i üzerinden "
        "DETERMİNİSTİK ALLOWLIST içinden seçim yaparak claim/"
        "counterargument/rebuttal/suggestion sinyali üreten bir "
        "yardımcı bileşensin.\n\n"
        "KESİN SINIRLAR:\n"
        "1. Yalnız sana verilen JSON şemasında izin verilen "
        "alanları döndürürsün. Başka HİÇBİR alan (özellikle ID, "
        "count, hash, execution_state, review_state, "
        "confidence, strength, admissibility, win_probability) "
        "EKLEYEMEZSİN; eklersen candidate TAMAMEN reddedilir.\n"
        "2. Referans dizilerin (source_fact_ids vb.) YALNIZ "
        "sana verilen allowlist içindeki ID'ler olabilir. Yeni "
        "bir fact/document/authority İCAT EDEMEZSİN.\n"
        "3. claim_text/counterargument_text/rebuttal_text/"
        "grounded_explanation İÇİNDE tırnak içinde alıntı "
        "kullanıyorsan, bu alıntı referans verdiğin kaynakta "
        "BİREBİR bulunmalıdır; emin değilsen alıntı kullanma.\n"
        "4. Metninde tarih/tutar geçiyorsa, bu değer referans "
        "verdiğin kaynakta BİREBİR bulunmalıdır.\n"
        "5. Metin içine bir document/candidate/research/karar "
        "ID'si GÖMEMEZSİN - kaynak gösterimi yalnız source_*_ids "
        "alanları üzerinden yapılır.\n"
        "6. Yanıtın YALNIZCA bir JSON array olmalıdır.\n"
        "7. Emin değilsen boş array döndür: []"
    )


# ============================================================
# RESPONSE PARSING
# ============================================================

def parse_agent_array_response(text):

    cleaned = text.strip()

    fence_match = re.search(
        r"```(?:json)?\s*(.*?)```",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if fence_match:

        cleaned = fence_match.group(1).strip()

    parsed = json.loads(cleaned)

    if not isinstance(parsed, list):

        raise ArgumentAgentError("LLM cevabı JSON array değil.")

    return parsed


def call_stage(llm_client, prompt):

    raw_text = llm_client.generate(prompt)

    return parse_agent_array_response(raw_text)


# ============================================================
# SHARED TEXT-SAFETY CHECK
# ============================================================

def check_text_safety(
    text,
    max_length,
    declared_ref_ids,
    citable_texts,
    all_known_ids,
):

    if not isinstance(text, str) or not text.strip():

        return "metin boş"

    if len(text) > max_length:

        return f"metin uzunluk sınırını aşıyor (>{max_length})"

    combined = normalize_text_tr(text)

    for phrase in ALL_FORBIDDEN_PHRASES:

        if phrase in combined:

            return f"kesin hukuki sonuç ifadesi içeriyor ('{phrase}')"

    smuggled = find_smuggled_ids(text, declared_ref_ids, all_known_ids)

    if smuggled:

        return f"metin içine bilinmeyen/deklare edilmemiş ID gömülü: {smuggled}"

    unverified_quotes = find_unverified_quotes(text, citable_texts)

    if unverified_quotes:

        return (
            "metindeki alıntı referans kaynaklarda birebir "
            f"doğrulanamadı: {unverified_quotes}"
        )

    unsupported = find_unsupported_numeric_tokens(text, citable_texts)

    if unsupported:

        return (
            "metindeki tarih/tutar referans kaynaklarda birebir "
            f"bulunamadı (unsupported): {unsupported}"
        )

    return None


def collect_ref_ids(record):

    result = []

    for field in REF_FIELDS:

        result.extend(record.get(field, []) or [])

    return result


def empty_ref_set():

    return {field: [] for field in REF_FIELDS}


def extract_ref_set(item):

    return {field: list(item.get(field, []) or []) for field in REF_FIELDS}


def validate_ref_set_against_menu(ref_set, menu):

    menu_map = {
        "source_fact_ids": "eligible_fact_ids",
        "source_evidence_candidate_ids": "eligible_evidence_candidate_ids",
        "source_legal_research_ids": "eligible_legal_research_ids",
        "source_case_law_ids": "eligible_case_law_ids",
        "source_timeline_event_ids": "eligible_timeline_event_ids",
        "source_deadline_ids": "eligible_deadline_ids",
    }

    for field, menu_field in menu_map.items():

        allowed = set(menu.get(menu_field, []))

        for value in ref_set.get(field, []):

            if value not in allowed:

                return (
                    f"'{value}' issue '{menu['issue_id']}' allowlist'inde "
                    f"({menu_field}) bulunamadı (allowlist escape/"
                    "cross-issue leakage)"
                )

    return None


# ============================================================
# STAGE 1: CLAIM
# ============================================================

def build_claim_prompt(allowlist_by_issue, fact_index):

    payload = []

    for issue_id, menu in allowlist_by_issue.items():

        if not menu["has_minimum_grounding"]:

            continue

        payload.append(
            {
                "source_issue_id": issue_id,
                "issue_text": menu["issue_text"],
                "eligible_fact_ids": menu["eligible_fact_ids"],
                "eligible_fact_statements": {
                    fact_id: fact_index[fact_id]["fact"].get("statement")
                    for fact_id in menu["eligible_fact_ids"]
                },
                "eligible_evidence_candidate_ids": menu[
                    "eligible_evidence_candidate_ids"
                ],
                "eligible_legal_research_ids": menu[
                    "eligible_legal_research_ids"
                ],
                "eligible_case_law_ids": menu["eligible_case_law_ids"],
                "eligible_timeline_event_ids": menu[
                    "eligible_timeline_event_ids"
                ],
                "eligible_deadline_ids": menu["eligible_deadline_ids"],
            }
        )

    return (
        "Aşağıdaki canonical issue'lar ve her biri için allowlist "
        "üzerinden CLAIM sinyalleri üret. Yalnız JSON array "
        "döndür.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def validate_claim_shape(item, allowlist_by_issue, all_known_ids):

    if not isinstance(item, dict):

        return (False, None, None, "candidate dict değil")

    forbidden = set(item.keys()) - ALLOWED_CLAIM_KEYS

    if forbidden:

        return (
            False,
            item.get("source_issue_id"),
            None,
            f"izin verilmeyen alan(lar): {sorted(forbidden)}",
        )

    issue_id = item.get("source_issue_id")

    menu = allowlist_by_issue.get(issue_id)

    if menu is None:

        return (
            False,
            issue_id,
            None,
            f"source_issue_id allowlist'te yok: {issue_id}",
        )

    claim_type = item.get("claim_type")

    if claim_type not in CLAIM_TYPES:

        return (False, issue_id, None, f"geçersiz claim_type: {claim_type}")

    reason_code = item.get("reason_code")

    if reason_code not in ARGUMENT_REASON_CODES:

        return (False, issue_id, None, f"geçersiz reason_code: {reason_code}")

    ref_set = extract_ref_set(item)

    escape_error = validate_ref_set_against_menu(ref_set, menu)

    if escape_error:

        return (False, issue_id, None, escape_error)

    if not ref_set["source_fact_ids"]:

        return (
            False,
            issue_id,
            None,
            "minimum grounding ihlali: en az bir source_fact_id zorunlu",
        )

    return (True, issue_id, {"ref_set": ref_set, "menu": menu}, None)


def run_claim_stage(
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

        issue_id = item.get("source_issue_id") if isinstance(item, dict) else None

        bucket = per_issue.setdefault(
            issue_id, {"raw": 0, "rejected": 0}
        )

        bucket["raw"] += 1

        ok, resolved_issue_id, resolved, reason = validate_claim_shape(
            item, allowlist_by_issue, all_known_ids
        )

        if resolved_issue_id is not None:

            bucket = per_issue.setdefault(
                resolved_issue_id, {"raw": 0, "rejected": 0}
            )

        if not ok:

            bucket["rejected"] += 1

            warnings.append(f"Claim signal reddedildi ({reason}).")

            continue

        ref_set = resolved["ref_set"]

        citable_texts = collect_citable_texts(
            ref_set,
            fact_index,
            evidence_candidate_index,
            research_index,
            case_law_decision_index,
        )

        declared_ids = collect_ref_ids({**ref_set})

        text_error = check_text_safety(
            item.get("claim_text"),
            MAX_ARGUMENT_TEXT_LENGTH,
            declared_ids,
            citable_texts,
            all_known_ids,
        )

        if text_error is None:

            text_error = check_text_safety(
                item.get("grounded_explanation"),
                MAX_GROUNDED_EXPLANATION_LENGTH,
                declared_ids,
                citable_texts,
                all_known_ids,
            )

        if text_error:

            bucket["rejected"] += 1

            warnings.append(f"Claim signal reddedildi ({text_error}).")

            continue

        dedup_key = (
            issue_id,
            item["claim_type"],
            item["claim_text"],
            tuple(sorted(declared_ids)),
        )

        if dedup_key in seen_keys:

            bucket["rejected"] += 1

            warnings.append("Duplicate claim signal atlandı (dedup).")

            continue

        seen_keys.add(dedup_key)

        accepted.append((item, ref_set, issue_id))

    finalized = []

    for index, (item, ref_set, issue_id) in enumerate(accepted, start=start_index):

        depends_on_unconfirmed_evidence = compute_depends_on_unconfirmed_evidence(
            ref_set, evidence_candidate_index
        )

        depends_on_unconfirmed_authority = compute_depends_on_unconfirmed_authority(
            ref_set, case_law_decision_index
        )

        missing_legal_authority = compute_missing_legal_authority(
            ref_set, item["claim_type"], LEGAL_CLAIM_TYPES
        )

        finalized.append(
            {
                "claim_id": f"argument_claim_{index:03d}",
                "source_issue_id": issue_id,
                "claim_type": item["claim_type"],
                "claim_text": item["claim_text"],
                **ref_set,
                "depends_on_unconfirmed_evidence": depends_on_unconfirmed_evidence,
                "depends_on_unconfirmed_authority": depends_on_unconfirmed_authority,
                "missing_legal_authority": missing_legal_authority,
                "reason_code": item["reason_code"],
                "grounded_explanation": item["grounded_explanation"],
                "claim_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
            }
        )

    return (finalized, warnings, per_issue)


# ============================================================
# STAGE 2: COUNTERARGUMENT
# ============================================================

def build_counterargument_prompt(finalized_claims, allowlist_by_issue):

    payload = []

    for claim in finalized_claims:

        menu = allowlist_by_issue[claim["source_issue_id"]]

        payload.append(
            {
                "claim_id": claim["claim_id"],
                "claim_type": claim["claim_type"],
                "claim_text": claim["claim_text"],
                "source_issue_id": claim["source_issue_id"],
                "eligible_fact_ids": menu["eligible_fact_ids"],
                "eligible_evidence_candidate_ids": menu[
                    "eligible_evidence_candidate_ids"
                ],
                "eligible_legal_research_ids": menu[
                    "eligible_legal_research_ids"
                ],
                "eligible_case_law_ids": menu["eligible_case_law_ids"],
                "eligible_timeline_event_ids": menu[
                    "eligible_timeline_event_ids"
                ],
                "eligible_deadline_ids": menu["eligible_deadline_ids"],
            }
        )

    return (
        "Aşağıdaki VALIDATED claim'ler için, aynı issue allowlist'i "
        "içinden COUNTERARGUMENT sinyalleri üret. Yalnız JSON array "
        "döndür.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def validate_counterargument_shape(item, claim_by_id, allowlist_by_issue):

    if not isinstance(item, dict):

        return (False, None, None, "candidate dict değil")

    forbidden = set(item.keys()) - ALLOWED_COUNTERARGUMENT_KEYS

    if forbidden:

        return (
            False,
            None,
            None,
            f"izin verilmeyen alan(lar): {sorted(forbidden)}",
        )

    claim_id = item.get("source_claim_id")

    claim = claim_by_id.get(claim_id)

    if claim is None:

        return (
            False,
            None,
            None,
            f"source_claim_id VALIDATED claim setinde yok: {claim_id}",
        )

    issue_id = claim["source_issue_id"]

    counter_type = item.get("counter_type")

    if counter_type not in COUNTER_TYPES:

        return (
            False,
            issue_id,
            None,
            f"geçersiz counter_type: {counter_type}",
        )

    reason_code = item.get("reason_code")

    if reason_code not in ARGUMENT_REASON_CODES:

        return (False, issue_id, None, f"geçersiz reason_code: {reason_code}")

    menu = allowlist_by_issue[issue_id]

    ref_set = extract_ref_set(item)

    escape_error = validate_ref_set_against_menu(ref_set, menu)

    if escape_error:

        return (False, issue_id, None, escape_error)

    if not collect_ref_ids(ref_set):

        return (
            False,
            issue_id,
            None,
            "canonical grounding yok (en az bir referans zorunlu) - "
            "unresolved_counterargument suggestion'a yönlendirilmeli",
        )

    return (
        True,
        issue_id,
        {"ref_set": ref_set, "menu": menu, "claim": claim},
        None,
    )


def run_counterargument_stage(
    raw_items,
    finalized_claims,
    allowlist_by_issue,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
    all_known_ids,
    start_index,
):

    claim_by_id = {claim["claim_id"]: claim for claim in finalized_claims}

    warnings = []

    accepted = []

    seen_keys = set()

    per_issue = {}

    for item in raw_items[:MAX_ITEMS_PER_STAGE]:

        ok, issue_id, resolved, reason = validate_counterargument_shape(
            item, claim_by_id, allowlist_by_issue
        )

        bucket = per_issue.setdefault(issue_id, {"raw": 0, "rejected": 0})

        bucket["raw"] += 1

        if not ok:

            bucket["rejected"] += 1

            warnings.append(f"Counterargument signal reddedildi ({reason}).")

            continue

        ref_set = resolved["ref_set"]

        claim = resolved["claim"]

        citable_texts = collect_citable_texts(
            ref_set,
            fact_index,
            evidence_candidate_index,
            research_index,
            case_law_decision_index,
        )

        declared_ids = collect_ref_ids(ref_set)

        text_error = check_text_safety(
            item.get("counterargument_text"),
            MAX_ARGUMENT_TEXT_LENGTH,
            declared_ids,
            citable_texts,
            all_known_ids,
        ) or check_text_safety(
            item.get("grounded_explanation"),
            MAX_GROUNDED_EXPLANATION_LENGTH,
            declared_ids,
            citable_texts,
            all_known_ids,
        )

        if text_error:

            bucket["rejected"] += 1

            warnings.append(f"Counterargument signal reddedildi ({text_error}).")

            continue

        dedup_key = (
            claim["claim_id"],
            item["counter_type"],
            item["counterargument_text"],
            tuple(sorted(declared_ids)),
        )

        if dedup_key in seen_keys:

            bucket["rejected"] += 1

            warnings.append("Duplicate counterargument signal atlandı (dedup).")

            continue

        seen_keys.add(dedup_key)

        accepted.append((item, ref_set, claim))

    finalized = []

    for index, (item, ref_set, claim) in enumerate(accepted, start=start_index):

        depends_on_unconfirmed_evidence = compute_depends_on_unconfirmed_evidence(
            ref_set, evidence_candidate_index
        )

        depends_on_unconfirmed_authority = compute_depends_on_unconfirmed_authority(
            ref_set, case_law_decision_index
        )

        missing_legal_authority = compute_missing_legal_authority(
            ref_set, item["counter_type"], LEGAL_COUNTER_TYPES
        )

        finalized.append(
            {
                "counterargument_id": f"argument_counter_{index:03d}",
                "source_claim_id": claim["claim_id"],
                "source_issue_id": claim["source_issue_id"],
                "counter_type": item["counter_type"],
                "counterargument_text": item["counterargument_text"],
                **ref_set,
                "depends_on_unconfirmed_evidence": depends_on_unconfirmed_evidence,
                "depends_on_unconfirmed_authority": depends_on_unconfirmed_authority,
                "missing_legal_authority": missing_legal_authority,
                "reason_code": item["reason_code"],
                "grounded_explanation": item["grounded_explanation"],
                "counter_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
            }
        )

    return (finalized, warnings, per_issue)


# ============================================================
# STAGE 3: REBUTTAL
# ============================================================

def build_rebuttal_prompt(finalized_counterarguments, allowlist_by_issue):

    payload = []

    for counter in finalized_counterarguments:

        menu = allowlist_by_issue[counter["source_issue_id"]]

        payload.append(
            {
                "counterargument_id": counter["counterargument_id"],
                "counter_type": counter["counter_type"],
                "counterargument_text": counter["counterargument_text"],
                "source_claim_id": counter["source_claim_id"],
                "source_issue_id": counter["source_issue_id"],
                "eligible_fact_ids": menu["eligible_fact_ids"],
                "eligible_evidence_candidate_ids": menu[
                    "eligible_evidence_candidate_ids"
                ],
                "eligible_legal_research_ids": menu[
                    "eligible_legal_research_ids"
                ],
                "eligible_case_law_ids": menu["eligible_case_law_ids"],
                "eligible_timeline_event_ids": menu[
                    "eligible_timeline_event_ids"
                ],
                "eligible_deadline_ids": menu["eligible_deadline_ids"],
            }
        )

    return (
        "Aşağıdaki VALIDATED counterargument'lar için, aynı issue "
        "allowlist'i içinden REBUTTAL sinyalleri üret. Yalnız JSON "
        "array döndür.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def validate_rebuttal_shape(item, counter_by_id, allowlist_by_issue):

    if not isinstance(item, dict):

        return (False, None, None, "candidate dict değil")

    forbidden = set(item.keys()) - ALLOWED_REBUTTAL_KEYS

    if forbidden:

        return (
            False,
            None,
            None,
            f"izin verilmeyen alan(lar): {sorted(forbidden)}",
        )

    counterargument_id = item.get("source_counterargument_id")

    counter = counter_by_id.get(counterargument_id)

    if counter is None:

        return (
            False,
            None,
            None,
            "source_counterargument_id VALIDATED counterargument "
            f"setinde yok: {counterargument_id}",
        )

    issue_id = counter["source_issue_id"]

    rebuttal_type = item.get("rebuttal_type")

    if rebuttal_type not in REBUTTAL_TYPES:

        return (
            False,
            issue_id,
            None,
            f"geçersiz rebuttal_type: {rebuttal_type}",
        )

    reason_code = item.get("reason_code")

    if reason_code not in ARGUMENT_REASON_CODES:

        return (False, issue_id, None, f"geçersiz reason_code: {reason_code}")

    menu = allowlist_by_issue[issue_id]

    ref_set = extract_ref_set(item)

    escape_error = validate_ref_set_against_menu(ref_set, menu)

    if escape_error:

        return (False, issue_id, None, escape_error)

    if not collect_ref_ids(ref_set):

        return (
            False,
            issue_id,
            None,
            "canonical grounding yok (en az bir referans zorunlu)",
        )

    return (
        True,
        issue_id,
        {"ref_set": ref_set, "menu": menu, "counter": counter},
        None,
    )


def run_rebuttal_stage(
    raw_items,
    finalized_counterarguments,
    allowlist_by_issue,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
    all_known_ids,
    start_index,
):

    counter_by_id = {
        counter["counterargument_id"]: counter
        for counter in finalized_counterarguments
    }

    warnings = []

    accepted = []

    seen_keys = set()

    per_issue = {}

    for item in raw_items[:MAX_ITEMS_PER_STAGE]:

        ok, issue_id, resolved, reason = validate_rebuttal_shape(
            item, counter_by_id, allowlist_by_issue
        )

        bucket = per_issue.setdefault(issue_id, {"raw": 0, "rejected": 0})

        bucket["raw"] += 1

        if not ok:

            bucket["rejected"] += 1

            warnings.append(f"Rebuttal signal reddedildi ({reason}).")

            continue

        ref_set = resolved["ref_set"]

        counter = resolved["counter"]

        citable_texts = collect_citable_texts(
            ref_set,
            fact_index,
            evidence_candidate_index,
            research_index,
            case_law_decision_index,
        )

        declared_ids = collect_ref_ids(ref_set)

        text_error = check_text_safety(
            item.get("rebuttal_text"),
            MAX_ARGUMENT_TEXT_LENGTH,
            declared_ids,
            citable_texts,
            all_known_ids,
        ) or check_text_safety(
            item.get("grounded_explanation"),
            MAX_GROUNDED_EXPLANATION_LENGTH,
            declared_ids,
            citable_texts,
            all_known_ids,
        )

        if text_error:

            bucket["rejected"] += 1

            warnings.append(f"Rebuttal signal reddedildi ({text_error}).")

            continue

        dedup_key = (
            counter["counterargument_id"],
            item["rebuttal_type"],
            item["rebuttal_text"],
            tuple(sorted(declared_ids)),
        )

        if dedup_key in seen_keys:

            bucket["rejected"] += 1

            warnings.append("Duplicate rebuttal signal atlandı (dedup).")

            continue

        seen_keys.add(dedup_key)

        accepted.append((item, ref_set, counter))

    finalized = []

    for index, (item, ref_set, counter) in enumerate(accepted, start=start_index):

        depends_on_unconfirmed_evidence = compute_depends_on_unconfirmed_evidence(
            ref_set, evidence_candidate_index
        )

        depends_on_unconfirmed_authority = compute_depends_on_unconfirmed_authority(
            ref_set, case_law_decision_index
        )

        missing_legal_authority = compute_missing_legal_authority(
            ref_set, item["rebuttal_type"], LEGAL_REBUTTAL_TYPES
        )

        finalized.append(
            {
                "rebuttal_id": f"argument_rebuttal_{index:03d}",
                "source_claim_id": counter["source_claim_id"],
                "source_counterargument_id": counter["counterargument_id"],
                "source_issue_id": counter["source_issue_id"],
                "rebuttal_type": item["rebuttal_type"],
                "rebuttal_text": item["rebuttal_text"],
                **ref_set,
                "depends_on_unconfirmed_evidence": depends_on_unconfirmed_evidence,
                "depends_on_unconfirmed_authority": depends_on_unconfirmed_authority,
                "missing_legal_authority": missing_legal_authority,
                "reason_code": item["reason_code"],
                "grounded_explanation": item["grounded_explanation"],
                "rebuttal_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
            }
        )

    return (finalized, warnings, per_issue)


# ============================================================
# STAGE 4: SUGGESTIONS
# ============================================================

def build_suggestion_prompt(issue_index, finalized_claims, finalized_counterarguments):

    return (
        "Aşağıdaki canonical issue/claim/counterargument context'i "
        "üzerinden argument_agent_suggestions sinyalleri üret. "
        "Yalnız JSON array döndür.\n\n"
        + json.dumps(
            {
                "canonical_issues": [
                    {"issue_id": issue_id, "title": issue.get("title")}
                    for issue_id, issue in issue_index.items()
                ],
                "finalized_claims": [
                    {
                        "claim_id": claim["claim_id"],
                        "source_issue_id": claim["source_issue_id"],
                        "claim_type": claim["claim_type"],
                    }
                    for claim in finalized_claims
                ],
                "finalized_counterarguments": [
                    {
                        "counterargument_id": counter["counterargument_id"],
                        "source_claim_id": counter["source_claim_id"],
                    }
                    for counter in finalized_counterarguments
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def validate_suggestion_shape(
    item,
    issue_index,
    claim_by_id,
    counter_by_id,
    known_reference_ids,
):

    if not isinstance(item, dict):

        return (False, None, "candidate dict değil")

    forbidden = set(item.keys()) - ALLOWED_SUGGESTION_KEYS

    if forbidden:

        return (
            False,
            None,
            f"izin verilmeyen alan(lar): {sorted(forbidden)}",
        )

    issue_id = item.get("source_issue_id")

    if issue_id not in issue_index:

        return (False, issue_id, f"source_issue_id bilinmiyor: {issue_id}")

    suggestion_type = item.get("suggestion_type")

    spec = SUGGESTION_GROUNDING_SPEC.get(suggestion_type)

    if spec is None:

        return (
            False,
            issue_id,
            f"geçersiz suggestion_type: {suggestion_type}",
        )

    reason_code = item.get("reason_code")

    if reason_code not in ARGUMENT_REASON_CODES:

        return (False, issue_id, f"geçersiz reason_code: {reason_code}")

    claim_id = item.get("source_claim_id")

    counterargument_id = item.get("source_counterargument_id")

    if spec["requires_claim"] and claim_id not in claim_by_id:

        return (
            False,
            issue_id,
            f"suggestion_type='{suggestion_type}' için geçerli "
            "source_claim_id zorunludur",
        )

    if claim_id is not None and claim_id not in claim_by_id:

        return (False, issue_id, f"bilinmeyen source_claim_id: {claim_id}")

    if (
        spec["requires_counterargument"]
        and counterargument_id not in counter_by_id
    ):

        return (
            False,
            issue_id,
            f"suggestion_type='{suggestion_type}' için geçerli "
            "source_counterargument_id zorunludur",
        )

    if (
        counterargument_id is not None
        and counterargument_id not in counter_by_id
    ):

        return (
            False,
            issue_id,
            f"bilinmeyen source_counterargument_id: {counterargument_id}",
        )

    related_reference_ids = item.get("related_reference_ids", [])

    if not isinstance(related_reference_ids, list):

        return (False, issue_id, "related_reference_ids list değil")

    if len(related_reference_ids) < spec["min_related_references"]:

        return (
            False,
            issue_id,
            f"suggestion_type='{suggestion_type}' en az "
            f"{spec['min_related_references']} related_reference_ids "
            "gerektirir",
        )

    for reference_id in related_reference_ids:

        if reference_id not in known_reference_ids:

            return (
                False,
                issue_id,
                f"related_reference_ids içinde bilinmeyen referans: "
                f"{reference_id}",
            )

    return (True, issue_id, None)


def run_suggestion_stage(
    raw_items,
    issue_index,
    finalized_claims,
    finalized_counterarguments,
    known_reference_ids,
    start_index,
    fact_index=None,
    evidence_candidate_index=None,
    research_index=None,
    case_law_decision_index=None,
):

    fact_index = fact_index or {}

    evidence_candidate_index = evidence_candidate_index or {}

    research_index = research_index or {}

    case_law_decision_index = case_law_decision_index or {}

    claim_by_id = {claim["claim_id"]: claim for claim in finalized_claims}

    counter_by_id = {
        counter["counterargument_id"]: counter
        for counter in finalized_counterarguments
    }

    warnings = []

    accepted = []

    per_issue = {}

    for item in raw_items[:MAX_ITEMS_PER_STAGE]:

        ok, issue_id, reason = validate_suggestion_shape(
            item, issue_index, claim_by_id, counter_by_id, known_reference_ids
        )

        bucket = per_issue.setdefault(issue_id, {"raw": 0, "rejected": 0})

        bucket["raw"] += 1

        if not ok:

            bucket["rejected"] += 1

            warnings.append(f"Suggestion signal reddedildi ({reason}).")

            continue

        # ----------------------------------------------------------
        # SUGGESTION FREE-TEXT SAFETY (Finding 2 remediation):
        # grounded_explanation, claim/counterargument/rebuttal
        # text'leriyle AYNI guard setinden geçmelidir - forbidden
        # phrase, citation/metadata-ID-smuggling, unverified quote,
        # unsupported date/amount, uzunluk/boşluk. Suggestion yapısal
        # olarak fact/document grounding alanı KAZANMAZ (yeni şema
        # alanı yok); yalnız zaten var olan related_reference_ids/
        # source_claim_id/source_counterargument_id deterministik
        # context'i "declared" ve "citable" kümeleri oluşturmak için
        # kullanılır.
        # ----------------------------------------------------------

        related_reference_ids = item.get("related_reference_ids", []) or []

        declared_ids = set(related_reference_ids)

        if item.get("source_claim_id"):

            declared_ids.add(item["source_claim_id"])

        if item.get("source_counterargument_id"):

            declared_ids.add(item["source_counterargument_id"])

        classified_ref_set = classify_related_reference_ids(
            related_reference_ids, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index,
        )

        citable_texts = collect_citable_texts(
            classified_ref_set, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index,
        )

        referenced_claim = claim_by_id.get(item.get("source_claim_id"))

        if referenced_claim is not None:

            citable_texts.append(referenced_claim["claim_text"])

        referenced_counter = counter_by_id.get(
            item.get("source_counterargument_id")
        )

        if referenced_counter is not None:

            citable_texts.append(referenced_counter["counterargument_text"])

        text_error = check_text_safety(
            item.get("grounded_explanation"), MAX_GROUNDED_EXPLANATION_LENGTH,
            declared_ids, citable_texts, known_reference_ids,
        )

        if text_error:

            bucket["rejected"] += 1

            warnings.append(f"Suggestion signal reddedildi ({text_error}).")

            continue

        accepted.append(item)

    finalized = []

    for index, item in enumerate(accepted, start=start_index):

        finalized.append(
            {
                "suggestion_id": f"argument_suggestion_{index:03d}",
                "source_issue_id": item["source_issue_id"],
                "suggestion_type": item["suggestion_type"],
                "source_claim_id": item.get("source_claim_id"),
                "source_counterargument_id": item.get(
                    "source_counterargument_id"
                ),
                "related_reference_ids": item.get("related_reference_ids", []),
                "reason_code": item["reason_code"],
                "grounded_explanation": item["grounded_explanation"],
                "suggestion_review_state": "needs_review",
                "requires_human_review": True,
                "status": "candidate",
            }
        )

    return (finalized, warnings, per_issue)


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(case_id="case_0001"):

    from legal_research_validator import load_canonical_issues
    from timeline_validator import load_canonical_fact_index
    from argument_discovery import (
        build_allowlists_for_issues,
        load_canonical_case_law_optional,
        load_canonical_deadline_optional,
        load_canonical_evidence_optional,
        load_canonical_legal_research_optional,
        load_canonical_timeline_optional,
    )

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT AGENT V1")
    print("======================================")

    issue_context = load_canonical_issues(case_id)
    issue_index = issue_context["issue_index"]
    fact_context = load_canonical_fact_index(case_id)
    fact_index = fact_context["facts"]

    _e, evidence_index, _ep = load_canonical_evidence_optional(case_id)
    _r, research_index, _rp = load_canonical_legal_research_optional(case_id)
    _d, case_law_index, _dp = load_canonical_case_law_optional(case_id)
    timeline_index, _tp = load_canonical_timeline_optional(case_id)
    _dl, deadline_ids, _dlp = load_canonical_deadline_optional(case_id)

    allowlist_by_issue, _w = build_allowlists_for_issues(
        issue_context["issues"], fact_index, evidence_index, research_index,
        case_law_index, timeline_index, deadline_ids,
    )

    grounded_issue_id = next(
        issue_id
        for issue_id, menu in allowlist_by_issue.items()
        if menu["has_minimum_grounding"]
    )

    fact_id = allowlist_by_issue[grounded_issue_id]["eligible_fact_ids"][0]

    grounded_fact_set = set(allowlist_by_issue[grounded_issue_id]["eligible_fact_ids"])

    other_issue_id, other_fact_id = next(
        (issue_id, candidate_fact_id)
        for issue_id, menu in allowlist_by_issue.items()
        if menu["has_minimum_grounding"] and issue_id != grounded_issue_id
        for candidate_fact_id in menu["eligible_fact_ids"]
        if candidate_fact_id not in grounded_fact_set
    )

    all_known_ids = (
        set(fact_index.keys()) | set(evidence_index.keys())
        | set(research_index.keys()) | set(case_law_index.keys())
        | set(timeline_index.keys()) | set(deadline_ids)
    )

    print("T01 Canonical context + allowlist load:", "PASS")

    good_claim_signal = {
        "source_issue_id": grounded_issue_id,
        "claim_type": "factual_challenge",
        "claim_text": "Bu fact issue bağlamını desteklemektedir.",
        "source_fact_ids": [fact_id],
        "source_evidence_candidate_ids": [],
        "source_legal_research_ids": [],
        "source_case_law_ids": [],
        "source_timeline_event_ids": [],
        "source_deadline_ids": [],
        "reason_code": "explicit_textual_match",
        "grounded_explanation": "Fact metni doğrudan issue ile ilgilidir.",
    }

    # T02 grounded claim accepted
    finalized, warnings, _stats = run_claim_stage(
        [good_claim_signal], allowlist_by_issue, fact_index, evidence_index,
        research_index, case_law_index, all_known_ids, 1,
    )

    assert len(finalized) == 1
    assert finalized[0]["claim_id"] == "argument_claim_001"
    assert finalized[0]["claim_review_state"] == "needs_review"
    assert "confidence" not in finalized[0]

    print("T02 Grounded claim accepted:", "PASS")

    # T03 minimum grounding violation (no facts)
    no_fact_signal = dict(good_claim_signal)
    no_fact_signal["source_fact_ids"] = []

    finalized2, warnings2, _s = run_claim_stage(
        [no_fact_signal], allowlist_by_issue, fact_index, evidence_index,
        research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized2 == []
    assert any("minimum grounding" in w for w in warnings2)

    print("T03 Claim with zero facts rejected (minimum grounding):", "PASS")

    # T04 cross-issue leakage rejected
    leaky_signal = dict(good_claim_signal)
    leaky_signal["source_fact_ids"] = [other_fact_id]

    finalized3, warnings3, _s = run_claim_stage(
        [leaky_signal], allowlist_by_issue, fact_index, evidence_index,
        research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized3 == []
    assert any("allowlist escape" in w or "leakage" in w for w in warnings3)

    print("T04 Cross-issue fact leakage rejected:", "PASS")

    # T05 unknown claim_type rejected
    bad_type_signal = dict(good_claim_signal)
    bad_type_signal["claim_type"] = "mixed"

    finalized4, _w4, _s = run_claim_stage(
        [bad_type_signal], allowlist_by_issue, fact_index, evidence_index,
        research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized4 == []

    print("T05 Unknown claim_type rejected:", "PASS")

    # T06 confidence smuggling rejected
    smuggling_signal = dict(good_claim_signal)
    smuggling_signal["confidence"] = 0.9

    finalized5, warnings5, _s = run_claim_stage(
        [smuggling_signal], allowlist_by_issue, fact_index, evidence_index,
        research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized5 == []
    assert any("izin verilmeyen" in w for w in warnings5)

    print("T06 Confidence-field smuggling rejected:", "PASS")

    # T07 dedup within stage
    finalized6, _w6, _s = run_claim_stage(
        [good_claim_signal, dict(good_claim_signal)], allowlist_by_issue,
        fact_index, evidence_index, research_index, case_law_index,
        all_known_ids, 1,
    )

    assert len(finalized6) == 1

    print("T07 Duplicate claim signal deduplicated:", "PASS")

    # T08 quote verification failure
    quote_signal = dict(good_claim_signal)
    quote_signal["claim_text"] = 'Belgede "bu tamamen uydurma bir alinti" yazmaktadir.'

    finalized7, warnings7, _s = run_claim_stage(
        [quote_signal], allowlist_by_issue, fact_index, evidence_index,
        research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized7 == []
    assert any("alıntı" in w for w in warnings7)

    print("T08 Unverified quote rejected:", "PASS")

    # T09 unsupported date rejected
    date_signal = dict(good_claim_signal)
    date_signal["claim_text"] = "Bu olay 01.01.1999 tarihinde gerceklesmistir."

    finalized8, warnings8, _s = run_claim_stage(
        [date_signal], allowlist_by_issue, fact_index, evidence_index,
        research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized8 == []
    assert any("unsupported" in w for w in warnings8)

    print("T09 Unsupported date token rejected:", "PASS")

    # T10 ID-smuggling in text rejected
    id_smuggling_signal = dict(good_claim_signal)
    id_smuggling_signal["claim_text"] = f"Bkz. {other_fact_id} numarali kayit."

    finalized9, warnings9, _s = run_claim_stage(
        [id_smuggling_signal], allowlist_by_issue, fact_index, evidence_index,
        research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized9 == []
    assert any("gömülü" in w for w in warnings9)

    print("T10 Citation-ID smuggling in claim_text rejected:", "PASS")

    # ---- STAGE 2: COUNTERARGUMENT ----

    good_counter_signal = {
        "source_claim_id": "argument_claim_001",
        "counter_type": "factual_denial",
        "counterargument_text": "Bu olgu farkli yorumlanabilir.",
        "source_fact_ids": [fact_id],
        "source_evidence_candidate_ids": [],
        "source_legal_research_ids": [],
        "source_case_law_ids": [],
        "source_timeline_event_ids": [],
        "source_deadline_ids": [],
        "reason_code": "general_contextual_relevance",
        "grounded_explanation": "Ayni fact farkli okunabilir.",
    }

    finalized_counter, warnings_c, _s = run_counterargument_stage(
        [good_counter_signal], finalized, allowlist_by_issue, fact_index,
        evidence_index, research_index, case_law_index, all_known_ids, 1,
    )

    assert len(finalized_counter) == 1
    assert finalized_counter[0]["counter_review_state"] == "needs_review"
    assert finalized_counter[0]["source_issue_id"] == grounded_issue_id

    print("T11 Grounded counterargument accepted:", "PASS")

    # T12 unknown source_claim_id rejected (invalid parent topology)
    bad_parent_signal = dict(good_counter_signal)
    bad_parent_signal["source_claim_id"] = "argument_claim_does_not_exist"

    finalized_c2, warnings_c2, _s = run_counterargument_stage(
        [bad_parent_signal], finalized, allowlist_by_issue, fact_index,
        evidence_index, research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized_c2 == []
    assert any("bilinmiyor" in w for w in warnings_c2) or any(
        "yok" in w for w in warnings_c2
    )

    print("T12 Unknown source_claim_id rejected (invalid parent topology):", "PASS")

    # T13 zero grounding counterargument rejected
    empty_ref_signal = dict(good_counter_signal)
    for field in REF_FIELDS:
        empty_ref_signal[field] = []

    finalized_c3, warnings_c3, _s = run_counterargument_stage(
        [empty_ref_signal], finalized, allowlist_by_issue, fact_index,
        evidence_index, research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized_c3 == []
    assert any("canonical grounding yok" in w for w in warnings_c3)

    print("T13 Zero-grounding counterargument rejected:", "PASS")

    # ---- STAGE 3: REBUTTAL ----

    good_rebuttal_signal = {
        "source_counterargument_id": "argument_counter_001",
        "rebuttal_type": "factual_refutation",
        "rebuttal_text": "Bu yorum dosyadaki fact ile tutarsizdir.",
        "source_fact_ids": [fact_id],
        "source_evidence_candidate_ids": [],
        "source_legal_research_ids": [],
        "source_case_law_ids": [],
        "source_timeline_event_ids": [],
        "source_deadline_ids": [],
        "reason_code": "explicit_textual_match",
        "grounded_explanation": "Fact metniyle celisir.",
    }

    finalized_rebuttal, warnings_r, _s = run_rebuttal_stage(
        [good_rebuttal_signal], finalized_counter, allowlist_by_issue,
        fact_index, evidence_index, research_index, case_law_index,
        all_known_ids, 1,
    )

    assert len(finalized_rebuttal) == 1
    assert finalized_rebuttal[0]["source_claim_id"] == "argument_claim_001"
    assert finalized_rebuttal[0]["rebuttal_review_state"] == "needs_review"

    print("T14 Grounded rebuttal accepted (claim_id derived from parent):", "PASS")

    # T15 unknown source_counterargument_id rejected
    bad_counter_ref = dict(good_rebuttal_signal)
    bad_counter_ref["source_counterargument_id"] = "argument_counter_does_not_exist"

    finalized_r2, warnings_r2, _s = run_rebuttal_stage(
        [bad_counter_ref], finalized_counter, allowlist_by_issue, fact_index,
        evidence_index, research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized_r2 == []

    print("T15 Unknown source_counterargument_id rejected:", "PASS")

    # ---- DETERMINISTIC FLAGS ----

    synthetic_evidence_index = {
        "ev_needs_review": {
            "candidate_id": "ev_needs_review", "source_issue_id": grounded_issue_id,
            "review_state": "needs_review", "source_excerpt": None,
        },
        "ev_confirmed": {
            "candidate_id": "ev_confirmed", "source_issue_id": grounded_issue_id,
            "review_state": "confirmed", "source_excerpt": None,
        },
    }

    ref_set_needs_review = {
        "source_fact_ids": [], "source_evidence_candidate_ids": ["ev_needs_review"],
        "source_legal_research_ids": [], "source_case_law_ids": [],
        "source_timeline_event_ids": [], "source_deadline_ids": [],
    }

    assert compute_depends_on_unconfirmed_evidence(
        ref_set_needs_review, synthetic_evidence_index
    ) is True

    ref_set_confirmed = dict(ref_set_needs_review)
    ref_set_confirmed["source_evidence_candidate_ids"] = ["ev_confirmed"]

    assert compute_depends_on_unconfirmed_evidence(
        ref_set_confirmed, synthetic_evidence_index
    ) is False

    print("T16 needs_review evidence -> depends_on_unconfirmed_evidence=True:", "PASS")

    synthetic_case_law_index = {
        "cl_needs_review": {"decision_id": "cl_needs_review", "applicability_result": "needs_review"},
        "cl_unknown": {"decision_id": "cl_unknown", "applicability_result": "unknown"},
    }

    ref_set_authority = {
        "source_fact_ids": [], "source_evidence_candidate_ids": [],
        "source_legal_research_ids": [], "source_case_law_ids": ["cl_needs_review"],
        "source_timeline_event_ids": [], "source_deadline_ids": [],
    }

    assert compute_depends_on_unconfirmed_authority(
        ref_set_authority, synthetic_case_law_index
    ) is True

    print("T17 case-law applicability needs_review -> depends_on_unconfirmed_authority=True:", "PASS")

    empty_authority_ref_set = {
        "source_fact_ids": ["x"], "source_evidence_candidate_ids": [],
        "source_legal_research_ids": [], "source_case_law_ids": [],
        "source_timeline_event_ids": [], "source_deadline_ids": [],
    }

    assert compute_missing_legal_authority(
        empty_authority_ref_set, "substantive_legal_challenge", LEGAL_CLAIM_TYPES
    ) is True

    assert compute_missing_legal_authority(
        empty_authority_ref_set, "factual_challenge", LEGAL_CLAIM_TYPES
    ) is False

    print("T18 missing_legal_authority computed only for legal-type claims:", "PASS")

    # ---- SUGGESTIONS ----

    suggestion_signals = [
        {
            "source_issue_id": grounded_issue_id,
            "suggestion_type": "missing_supporting_fact",
            "source_claim_id": None,
            "source_counterargument_id": None,
            "related_reference_ids": [],
            "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Ek fact gerekebilir.",
        },
        {
            "source_issue_id": grounded_issue_id,
            "suggestion_type": "unresolved_counterargument",
            "source_claim_id": "argument_claim_001",
            "source_counterargument_id": None,
            "related_reference_ids": [],
            "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Cozulmemis bir itiraz olabilir.",
        },
        {
            "source_issue_id": grounded_issue_id,
            "suggestion_type": "argument_taxonomy_gap",
            "source_claim_id": None,
            "source_counterargument_id": None,
            "related_reference_ids": [],
            "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Siniflandirilamayan bir nokta var.",
        },
    ]

    finalized_sugg, warnings_s, _s = run_suggestion_stage(
        suggestion_signals, issue_index, finalized, finalized_counter,
        all_known_ids | {"argument_claim_001"}, 1,
    )

    assert len(finalized_sugg) == 3

    print("T19 Suggestion conditional grounding (multiple types) accepted:", "PASS")

    # T20 unresolved_counterargument without claim rejected
    bad_suggestion = dict(suggestion_signals[1])
    bad_suggestion["source_claim_id"] = None

    finalized_sugg2, warnings_s2, _s = run_suggestion_stage(
        [bad_suggestion], issue_index, finalized, finalized_counter,
        all_known_ids, 1,
    )

    assert finalized_sugg2 == []

    print("T20 unresolved_counterargument without source_claim_id rejected:", "PASS")

    # T21 agent trying to emit review-state fields rejected (structural)
    review_state_smuggling = dict(good_claim_signal)
    review_state_smuggling["claim_review_state"] = "confirmed"

    finalized10, warnings10, _s = run_claim_stage(
        [review_state_smuggling], allowlist_by_issue, fact_index, evidence_index,
        research_index, case_law_index, all_known_ids, 1,
    )

    assert finalized10 == []

    print("T21 Agent attempt to emit claim_review_state='confirmed' rejected:", "PASS")

    # ------------------------------------------------------------
    # SUGGESTION FREE-TEXT SAFETY (Finding 2 remediation) - T22-T26
    # ------------------------------------------------------------

    base_safe_suggestion = {
        "source_issue_id": grounded_issue_id,
        "suggestion_type": "missing_supporting_fact",
        "source_claim_id": None,
        "source_counterargument_id": None,
        "related_reference_ids": [],
        "reason_code": "general_contextual_relevance",
        "grounded_explanation": "Bu issue icin ek destekleyici fact aranmalidir.",
    }

    def run_one_suggestion(payload):

        return run_suggestion_stage(
            [payload], issue_index, finalized, finalized_counter,
            all_known_ids | {"argument_claim_001"}, 1,
            fact_index=fact_index, evidence_candidate_index=evidence_index,
            research_index=research_index, case_law_decision_index=case_law_index,
        )

    # ---- T22: ghost/other-issue fact ID smuggled into
    # grounded_explanation (real ID, but NOT declared) -> reject ----

    smuggled_suggestion = dict(base_safe_suggestion)

    smuggled_suggestion["grounded_explanation"] = (
        f"Bkz. {other_fact_id} numarali kayit ile ilgili boslugu."
    )

    finalized_s22, warnings_s22, _s = run_one_suggestion(smuggled_suggestion)

    assert finalized_s22 == []
    assert any("gömülü" in w or "smuggl" in w for w in warnings_s22)

    print(
        "T22 Suggestion grounded_explanation with a real-but-"
        "undeclared (ghost) fact ID rejected (smuggling guard):",
        "PASS",
    )

    # ---- T23: fabricated date rejected ----

    date_suggestion = dict(base_safe_suggestion)

    date_suggestion["grounded_explanation"] = (
        "Bu olay 01.01.1999 tarihinde meydana gelmis olabilir."
    )

    finalized_s23, warnings_s23, _s = run_one_suggestion(date_suggestion)

    assert finalized_s23 == []
    assert any("unsupported" in w for w in warnings_s23)

    print("T23 Suggestion with fabricated/unsupported date rejected:", "PASS")

    # ---- T24: unverified quote rejected ----

    quote_suggestion = dict(base_safe_suggestion)

    quote_suggestion["grounded_explanation"] = (
        'Belgede "bu tamamen uydurma bir ifade" gecmektedir.'
    )

    finalized_s24, warnings_s24, _s = run_one_suggestion(quote_suggestion)

    assert finalized_s24 == []
    assert any("alıntı" in w for w in warnings_s24)

    print("T24 Suggestion with an unverified quote rejected:", "PASS")

    # ---- T25: forbidden certainty/outcome phrase rejected ----

    outcome_suggestion = dict(base_safe_suggestion)

    outcome_suggestion["grounded_explanation"] = (
        "Bu konuda ek arastirma yapilmazsa dava iptal edilmelidir."
    )

    finalized_s25, warnings_s25, _s = run_one_suggestion(outcome_suggestion)

    assert finalized_s25 == []
    assert any(
        "hukuki sonuç" in w or "kesin" in w for w in warnings_s25
    )

    print(
        "T25 Suggestion with forbidden certainty/outcome phrase "
        "rejected:",
        "PASS",
    )

    # ---- T26: safe, grounded suggestion explanation accepted ----

    grounded_suggestion = dict(base_safe_suggestion)

    grounded_suggestion["related_reference_ids"] = [fact_id]

    finalized_s26, warnings_s26, _s = run_one_suggestion(grounded_suggestion)

    assert len(finalized_s26) == 1
    assert finalized_s26[0]["suggestion_review_state"] == "needs_review"

    print(
        "T26 Safe, grounded suggestion explanation (no smuggling/"
        "quote/date/phrase violation) accepted:",
        "PASS",
    )

    print()
    print("======================================")
    print(" ARGUMENT AGENT V1: 26/26 PASS")
    print("======================================")


if __name__ == "__main__":

    run_self_test()
