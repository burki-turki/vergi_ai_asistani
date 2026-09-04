# ============================================================
# VERGİ AI - QA AGENT V1 (Row 16)
#
# Opsiyonel LLM katmanı. YALNIZ qa_agent_suggestions'a yazar -
# HİÇBİR deterministik qa_check_results kaydı, sayaç, review
# kararı veya upstream veri ÜRETEMEZ/DEĞİŞTİREMEZ. Network
# varsayılan KAPALI; gerçek LLM çağrısı yalnız --with-agent +
# --allow-network ile (Row 9-15 deseniyle birebir aynı).
# ============================================================

import itertools
import json
import os

from qa_policy import (
    QA_SUGGESTION_TYPES, check_qa_suggestion_text_safety,
    find_qa_suggestion_id_issues, sha256_of,
)


MAX_SUGGESTIONS = 20
MAX_EXPLANATION_LENGTH = 1000


class FakeQaLLMClient:

    # Bu client GERÇEK BİR NETWORK ÇAĞRISI YAPMAZ.

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


class AnthropicQaLLMClient:

    def __init__(self):

        self._client = None

    def generate(self, prompt):

        api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not api_key:

            raise RuntimeError(
                "ANTHROPIC_API_KEY tanımlı değil - gerçek QA Agent çağrısı "
                "yapılamaz (fail-closed, network denenmeden)."
            )

        import anthropic

        if self._client is None:

            self._client = anthropic.Anthropic(api_key=api_key)

        response = self._client.messages.create(
            model="claude-sonnet-5",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text


def build_agent_prompt(qa_check_results):
    """
    Yalnız failed/error/blocked sonuçları (agent'a gösterilecek
    ALLOWLIST) prompt'a dahil edilir - agent'ın referans
    edebileceği check_result_id kümesi BUNLARLA SINIRLIDIR.
    """

    interesting = [
        r for r in qa_check_results
        if r["qa_result"] in ("failed", "error", "blocked")
    ]

    menu = [
        {
            "check_result_id": r["check_result_id"],
            "check_id": r["check_id"],
            "scope_id": r["scope_id"],
            "member_id": r["member_id"],
            "related_issue_id": r["related_issue_id"],
            "qa_result": r["qa_result"],
            "reason_code": r["reason_code"],
        }
        for r in interesting
    ]

    return json.dumps({
        "instruction": (
            "Aşağıdaki deterministik QA bulgularını incele. Yalnız "
            "check_result_id'si bu listede olan kayıtlara atıfta bulunarak, "
            "izole bir semantik gözlem önerisi üretebilirsin. Yeni bir "
            "check_result_id İCAT ETME, herhangi bir sayı/sonuç/karar "
            "ÜRETME."
        ),
        "allowed_check_results": menu,
    }, ensure_ascii=False)


def _dedup_fingerprint(suggestion):

    return sha256_of({
        "kind": "qa_suggestion_dedup",
        "suggestion_type": suggestion["suggestion_type"],
        "related_check_result_id": suggestion.get("related_check_result_id"),
        "related_scope_id": suggestion["related_scope_id"],
    })


def _content_fingerprint(suggestion):

    return sha256_of({
        "kind": "qa_suggestion_content",
        "suggestion_type": suggestion["suggestion_type"],
        "related_check_result_id": suggestion.get("related_check_result_id"),
        "related_scope_id": suggestion["related_scope_id"],
        "related_issue_id": suggestion.get("related_issue_id"),
        "grounded_explanation": suggestion["grounded_explanation"],
    })


def run_agent_stage(raw_items, qa_check_results, start_index=1):
    """
    raw_items: agent'ın (veya bir saldırganın) ürettiği ham JSON öğeleri.
    Döner: (finalized_suggestions, warnings).
    """

    allowed_ids = {r["check_result_id"] for r in qa_check_results}
    allowed_scope_ids = {r["scope_id"] for r in qa_check_results}

    warnings = []
    accepted = []

    for item in raw_items[:MAX_SUGGESTIONS]:

        if not isinstance(item, dict):

            warnings.append("Suggestion adayı reddedildi (dict değil).")

            continue

        suggestion_type = item.get("suggestion_type")

        if suggestion_type not in QA_SUGGESTION_TYPES:

            warnings.append(f"Suggestion adayı reddedildi (geçersiz suggestion_type: {suggestion_type}).")

            continue

        related_check_result_id = item.get("related_check_result_id")

        if related_check_result_id is not None and related_check_result_id not in allowed_ids:

            warnings.append(
                f"Suggestion adayı reddedildi (bilinmeyen/uydurma related_check_result_id: {related_check_result_id})."
            )

            continue

        related_scope_id = item.get("related_scope_id")

        if related_scope_id not in allowed_scope_ids:

            warnings.append(f"Suggestion adayı reddedildi (geçersiz related_scope_id: {related_scope_id}).")

            continue

        explanation = item.get("grounded_explanation")

        if not isinstance(explanation, str) or not explanation.strip():

            warnings.append("Suggestion adayı reddedildi (grounded_explanation boş).")

            continue

        if len(explanation) > MAX_EXPLANATION_LENGTH:

            warnings.append("Suggestion adayı reddedildi (grounded_explanation uzunluk sınırını aşıyor).")

            continue

        forbidden_errors = check_qa_suggestion_text_safety("qa_suggestion", explanation)

        if forbidden_errors:

            warnings.append(f"Suggestion adayı reddedildi ({forbidden_errors[0]}).")

            continue

        id_issues = find_qa_suggestion_id_issues(
            explanation,
            declared_ids={related_check_result_id} if related_check_result_id else set(),
            all_known_ids=allowed_ids,
        )

        if id_issues["fabricated"]:

            warnings.append(
                f"Suggestion adayı reddedildi (canonical'da hiç var olmayan, uydurma ID içeriyor: {id_issues['fabricated']})."
            )

            continue

        if id_issues["smuggled"]:

            warnings.append(
                f"Suggestion adayı reddedildi (beyan edilmemiş check_result_id içeriyor: {id_issues['smuggled']})."
            )

            continue

        accepted.append(item)

    finalized = []
    counter = itertools.count(start_index)

    for item in accepted:

        suggestion = {
            "suggestion_id": f"qa_agent_suggestion_{next(counter):03d}",
            "suggestion_type": item["suggestion_type"],
            "related_check_result_id": item.get("related_check_result_id"),
            "related_scope_id": item["related_scope_id"],
            "related_issue_id": item.get("related_issue_id"),
            "grounded_explanation": item["grounded_explanation"],
            "suggestion_review_state": "needs_review",
        }

        suggestion["suggestion_dedup_fingerprint"] = _dedup_fingerprint(suggestion)
        suggestion["suggestion_content_fingerprint"] = _content_fingerprint(suggestion)

        finalized.append(suggestion)

    return finalized, warnings


def call_stage(llm_client, prompt):

    raw_text = llm_client.generate(prompt)

    try:

        parsed = json.loads(raw_text)

    except (json.JSONDecodeError, ValueError):

        return None

    if not isinstance(parsed, list):

        return None

    return parsed


def run_self_test():

    print()
    print("======================================")
    print(" VERGİ AI - QA AGENT V1 (SELF-TEST)")
    print("======================================")

    check_results = [
        {"check_result_id": "qa_check_result_001", "check_id": "artifact_presence", "scope_id": "evidence",
         "member_id": None, "related_issue_id": None, "qa_result": "blocked", "reason_code": "prerequisite_unmet"},
        {"check_result_id": "qa_check_result_002", "check_id": "stale_input_hash_consistency", "scope_id": "drafting",
         "member_id": None, "related_issue_id": None, "qa_result": "passed", "reason_code": "hash_comparison_result"},
    ]

    # T01: geçerli, izlenebilir bir suggestion kabul edilir
    good_item = [{
        "suggestion_type": "needs_deeper_human_review",
        "related_check_result_id": "qa_check_result_001", "related_scope_id": "evidence",
        "related_issue_id": None, "grounded_explanation": "Bu bulgunun ileride tekrar incelenmesi faydali olabilir.",
    }]

    fin1, warns1 = run_agent_stage(good_item, check_results)

    assert len(fin1) == 1 and not warns1

    print("T01 Geçerli, izlenebilir suggestion kabul edildi:", "PASS")

    # T02: uydurma (ghost) check_result_id reddedilir
    ghost_item = [{
        "suggestion_type": "needs_deeper_human_review",
        "related_check_result_id": "qa_check_result_UYDURMA_999", "related_scope_id": "evidence",
        "related_issue_id": None, "grounded_explanation": "Bu bulgu incelenmeli.",
    }]

    fin2, warns2 = run_agent_stage(ghost_item, check_results)

    assert len(fin2) == 0 and any("uydurma" in w for w in warns2)

    print("T02 Uydurma related_check_result_id reddedildi:", "PASS")

    # T03: metinde ghost-ID İÇEREN (ama alan olarak related_check_result_id doğru) suggestion reddedilir
    ghost_text_item = [{
        "suggestion_type": "cross_row_observation",
        "related_check_result_id": "qa_check_result_001", "related_scope_id": "evidence",
        "related_issue_id": None,
        "grounded_explanation": "Bkz qa_check_result_UYDURMA_777 numarali kayit da ilgili olabilir.",
    }]

    fin3, warns3 = run_agent_stage(ghost_text_item, check_results)

    assert len(fin3) == 0 and any("uydurma" in w for w in warns3)

    print("T03 Serbest metindeki uydurma ID reddedildi:", "PASS")

    # T04: dava sonucu garantisi içeren metin reddedilir
    outcome_item = [{
        "suggestion_type": "possible_semantic_inconsistency",
        "related_check_result_id": "qa_check_result_002", "related_scope_id": "drafting",
        "related_issue_id": None, "grounded_explanation": "Bu dava kesinlikle kazanilacaktir.",
    }]

    fin4, warns4 = run_agent_stage(outcome_item, check_results)

    assert len(fin4) == 0

    print("T04 Dava sonucu garantisi içeren metin reddedildi:", "PASS")

    # T05: geçersiz suggestion_type reddedilir
    bad_type_item = [{
        "suggestion_type": "not_a_real_type",
        "related_check_result_id": "qa_check_result_001", "related_scope_id": "evidence",
        "related_issue_id": None, "grounded_explanation": "test",
    }]

    fin5, warns5 = run_agent_stage(bad_type_item, check_results)

    assert len(fin5) == 0

    print("T05 Geçersiz suggestion_type reddedildi:", "PASS")

    # T06: dedup/content fingerprint hesaplanıyor ve farklı
    assert fin1[0]["suggestion_dedup_fingerprint"] != fin1[0]["suggestion_content_fingerprint"]

    print("T06 Dedup ve content fingerprint ayrı ve hesaplanmış:", "PASS")

    # T07: FakeQaLLMClient gerçek network çağrısı yapmaz, call_stage ile uçtan uca
    fake_client = FakeQaLLMClient(response_text=json.dumps(good_item, ensure_ascii=False))

    prompt = build_agent_prompt(check_results)

    raw = call_stage(fake_client, prompt)

    fin7, warns7 = run_agent_stage(raw, check_results)

    assert len(fin7) == 1 and fake_client.call_count == 1

    print("T07 FakeQaLLMClient uçtan uca (build_agent_prompt->call_stage->run_agent_stage) çalıştı:", "PASS")

    print()
    print("======================================")
    print(" QA AGENT V1: 7/7 SELF-TEST PASS")
    print("======================================")


if __name__ == "__main__":

    import sys

    if "--self-test" in sys.argv:

        run_self_test()

    else:

        print("qa_agent.py - bkz. --self-test.")
