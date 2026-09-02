# ============================================================
# VERGİ AI - CASE LAW AGENT V1
#
# AMAÇ
# ----
#
# Case Law Policy/Discovery V1 (deterministik katman) ÜZERİNE,
# LLM tabanlı EK case-law araştırma önerileri üretmek.
#
#
# KRİTİK SINIR
# ------------
#
# Bu modül Case Law Policy/Discovery'nin YERİNE GEÇMEZ.
#
#   - Bir mahkeme kararının var olduğunu, court_name/
#     decision_date/case_number/source_url'ini YALNIZ
#     deterministik retrieval + canonical documents.json
#     doğrulaması belirler (bkz. case_law_discovery.py). Bu
#     Agent bu alanları ASLA dolduramaz - finalize bunları
#     her zaman None/[] olarak sabitler.
#
#   - Bu Agent yalnız EK "case_law candidate" ÖNERİR: "bu
#     konuda ayrıca emsal araştırması yapılabilir" türünde.
#
#   - Agent çıktısı:
#       != gerçek bir mahkeme kararı
#       != bir emsalin uygulanabilir olduğunun kesinleşmesi
#       != case outcome tahmini
#       != yeni bir court_name/decision_number/case_number/
#          source URL uydurma
#
#
# FREE-TEXT SAFETY (Row 9/10 deseni)
# -------------------------------------
#
# LLM'e title/description/notes YAZDIRILMAZ. LLM yalnız
# yapılandırılmış bir sinyal üretir: reason_code,
# source_issue_id, source_research_ids, related_party_ids,
# related_dispute_item_ids, confidence. Bunların dışında
# (özellikle court_name/decision_date/case_number/source_url/
# grounded_document_ids/title/description gibi) HİÇBİR alan
# EKLEYEMEZ; eklerse candidate'ın TAMAMI reddedilir.
#
# title/description, kabul edilen sinyal doğrulandıktan
# SONRA, TAMAMEN deterministik bir template renderer
# tarafından üretilir.
#
#
# NETWORK SAFETY GATE (Row 9/10 ile birebir aynı desen)
# -----------------------------------------------------
#
# Gerçek Anthropic API çağrısı için İKİ açık koşul gerekir:
# llm_client açıkça VERİLMEMİŞ olmalı VE network_allowed=True
# açıkça geçilmiş olmalı. Aksi halde
# AnthropicCaseLawLLMClient HİÇ OLUŞTURULMAZ.
# ============================================================


import json
import os
import re


from issue_spotting_validator import (
    FORBIDDEN_PHRASES,
)

from case_law_policy import (
    CASE_LAW_FORBIDDEN_PHRASES,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)


# ============================================================
# VERSION
# ============================================================

CASE_LAW_AGENT_VERSION = "1"

AGENT_TRIGGER_RULE_ID = (
    "case_law_rule_agent_llm_v1"
)

DEFAULT_AGENT_MODEL = "claude-sonnet-4-6"

MAX_AGENT_CANDIDATES = 10

ALL_FORBIDDEN_PHRASES = (
    tuple(
        FORBIDDEN_PHRASES
    )
    + tuple(
        CASE_LAW_FORBIDDEN_PHRASES
    )
)


# ============================================================
# LLM CANDIDATE - İZİN VERİLEN ALANLAR
# ============================================================

ALLOWED_LLM_CANDIDATE_KEYS = {
    "reason_code",
    "source_issue_id",
    "source_research_ids",
    "related_party_ids",
    "related_dispute_item_ids",
    "confidence",
}


# ============================================================
# EXCEPTION
# ============================================================

class CaseLawAgentError(
    Exception
):
    pass


# ============================================================
# LLM CLIENT INTERFACE
# ============================================================

class AnthropicCaseLawLLMClient:

    def __init__(
        self,
        model=None,
        api_key=None,
        max_tokens=1500,
    ):

        self.model = (
            model
            or DEFAULT_AGENT_MODEL
        )

        self.api_key = (
            api_key
            or os.getenv(
                "ANTHROPIC_API_KEY"
            )
        )

        self.max_tokens = (
            max_tokens
        )

    def generate(
        self,
        prompt,
    ):

        if not self.api_key:

            raise CaseLawAgentError(
                "ANTHROPIC_API_KEY bulunamadı. "
                ".env dosyasını kontrol et."
            )

        from anthropic import Anthropic

        client = Anthropic(
            api_key=
                self.api_key
        )

        response = (
            client.messages.create(
                model=
                    self.model,

                max_tokens=
                    self.max_tokens,

                system=
                    build_system_prompt(),

                messages=[
                    {
                        "role":
                            "user",

                        "content":
                            prompt,
                    }
                ],
            )
        )

        text_parts = []

        for block in response.content:

            if getattr(
                block,
                "type",
                None,
            ) == "text":

                text_parts.append(
                    block.text
                )

        result = "\n".join(
            text_parts
        ).strip()

        if not result:

            raise CaseLawAgentError(
                "LLM boş cevap döndürdü."
            )

        return result


class FakeCaseLawLLMClient:

    # --------------------------------------------------------
    # Bu client GERÇEK BİR NETWORK ÇAĞRISI YAPMAZ.
    # --------------------------------------------------------

    def __init__(
        self,
        response_text=None,
        raise_error=None,
    ):

        self.response_text = (
            response_text
            if response_text is not None
            else "[]"
        )

        self.raise_error = (
            raise_error
        )

        self.last_prompt = None

        self.call_count = 0

    def generate(
        self,
        prompt,
    ):

        self.last_prompt = prompt

        self.call_count += 1

        if self.raise_error is not None:

            raise self.raise_error

        return self.response_text


# ============================================================
# REASON CODE SPECS
# ============================================================

def render_related_case_law_area_review(
    source_issue_id,
    source_research_ids,
):

    title = (
        "İlgili alanda ek emsal araştırması yapılabilir"
    )

    linked = (
        ", ".join(
            source_research_ids
        )
        if source_research_ids
        else source_issue_id
    )

    description = (
        "Agent tarafından işaretlenen "
        f"{source_issue_id} issue'sı (ilgili research "
        f"kayıtları: {linked}) ile bağlantılı alanda "
        "ek emsal/yargı kararı araştırması yapılmasının "
        "faydalı olabileceği değerlendirilmiştir."
    )

    return (
        title,
        description,
    )


def render_general_review_needed(
    source_issue_id,
    source_research_ids,
):

    title = (
        "Ek case-law araştırması gerekebilecek bir nokta "
        "tespit edildi"
    )

    description = (
        "Agent tarafından işaretlenen "
        f"{source_issue_id} issue'sı için ayrıca emsal "
        "araştırması yapılması önerilir."
    )

    return (
        title,
        description,
    )


REASON_CODE_SPECS = {
    "related_case_law_area_review": {
        "render":
            render_related_case_law_area_review,
    },

    "general_review_needed": {
        "render":
            render_general_review_needed,
    },
}


# ============================================================
# SYSTEM PROMPT
# ============================================================

def build_system_prompt():

    reason_code_list = ", ".join(
        sorted(
            REASON_CODE_SPECS.keys()
        )
    )

    return (
        "Sen bir vergi hukuku uyuşmazlık dosyasında, "
        "canonical bir issue/research candidate için EK "
        "case-law (emsal/yargı kararı) araştırma signal'i "
        "öneren bir yardımcı bileşensin.\n\n"
        "KESİN SINIRLAR:\n"
        "1. Hiçbir serbest metin (başlık, açıklama, yorum) "
        "ÜRETMEZSİN. Yalnız yapılandırılmış alanlar "
        "döndürürsün: reason_code, source_issue_id, "
        "source_research_ids, related_party_ids, "
        "related_dispute_item_ids, confidence.\n"
        "2. Bir mahkeme kararı UYDURAMAZSIN. court_name, "
        "decision_number, decision_date, case_number veya "
        "source URL gibi ALANLARI HİÇ ÜRETEMEZSİN; "
        "eklersen candidate'ın TAMAMI reddedilir.\n"
        "3. Bir emsalin uyuşmazlığa uygulanabilir olduğunu "
        "veya davanın sonucunu ASLA belirleyemezsin.\n"
        "4. reason_code yalnızca şu sabit listeden biri "
        f"olabilir: {reason_code_list}.\n"
        "5. source_issue_id yalnızca sana verilen canonical "
        "issue listesindeki bir issue_id olabilir.\n"
        "6. source_research_ids yalnızca sana verilen "
        "canonical research listesindeki ID'ler olabilir.\n"
        "7. Yanıtın YALNIZCA bir JSON array olmalıdır; "
        "başka hiçbir metin veya markdown içermemelidir.\n"
        "8. Emin değilsen boş array döndür: []"
    )


# ============================================================
# CONTEXT SUMMARIES
# ============================================================

def summarize_issues(
    issue_index,
):

    return [
        {
            "issue_id":
                issue_id,

            "issue_type":
                issue.get(
                    "issue_type"
                ),

            "title":
                issue.get(
                    "title"
                ),
        }
        for issue_id, issue
        in issue_index.items()
    ]


def summarize_researches(
    research_index,
):

    return [
        {
            "research_id":
                research_id,

            "source_issue_id":
                research.get(
                    "source_issue_id"
                ),

            "finding_status":
                research.get(
                    "finding_status"
                ),

            "citation_refs":
                research.get(
                    "citation_refs"
                ),
        }
        for research_id, research
        in research_index.items()
    ]


# ============================================================
# USER PROMPT
# ============================================================

def build_user_prompt(
    case_id,
    issue_index,
    research_index,
    existing_titles,
):

    payload = {
        "case_id":
            case_id,

        "canonical_issues":
            summarize_issues(
                issue_index
            ),

        "canonical_research":
            summarize_researches(
                research_index
            ),

        "already_covered_titles":
            existing_titles,
    }

    return (
        "Aşağıdaki canonical veri üzerinden, deterministik "
        "case-law araştırmasının kapsamadığı EK research "
        "signal önerileri üret. Yalnız JSON array "
        "döndür.\n\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


# ============================================================
# RESPONSE PARSING
# ============================================================

def parse_agent_response(
    text,
):

    cleaned = text.strip()

    fence_match = re.search(
        r"```(?:json)?\s*(.*?)```",
        cleaned,
        flags=(
            re.DOTALL
            | re.IGNORECASE
        ),
    )

    if fence_match:

        cleaned = (
            fence_match
            .group(1)
            .strip()
        )

    parsed = json.loads(
        cleaned
    )

    if not isinstance(
        parsed,
        list,
    ):

        raise CaseLawAgentError(
            "LLM cevabı JSON array değil."
        )

    return parsed


# ============================================================
# CANDIDATE SHAPE + GROUNDING VALIDATION
# ============================================================

def validate_agent_candidate_shape(
    candidate,
    allowed_issue_ids,
    allowed_research_ids,
):

    if not isinstance(
        candidate,
        dict,
    ):

        return (
            False,
            "candidate dict değil",
        )

    forbidden_keys = (
        set(
            candidate.keys()
        )
        - ALLOWED_LLM_CANDIDATE_KEYS
    )

    if forbidden_keys:

        return (
            False,
            "izin verilmeyen alan(lar) içeriyor "
            "(free-text/court-metadata safety ihlali): "
            f"{sorted(forbidden_keys)}",
        )

    reason_code = candidate.get(
        "reason_code"
    )

    if reason_code not in REASON_CODE_SPECS:

        return (
            False,
            f"geçersiz reason_code: {reason_code}",
        )

    source_issue_id = candidate.get(
        "source_issue_id"
    )

    if source_issue_id not in allowed_issue_ids:

        return (
            False,
            "source_issue_id canonical issues.json "
            f"içinde bulunamadı (grounding hatası): "
            f"{source_issue_id}",
        )

    source_research_ids = candidate.get(
        "source_research_ids",
        [],
    )

    if not isinstance(
        source_research_ids,
        list,
    ):

        return (
            False,
            "source_research_ids list değil",
        )

    for research_id in source_research_ids:

        if (
            not isinstance(
                research_id,
                str,
            )
            or research_id
            not in allowed_research_ids
        ):

            return (
                False,
                "source_research_ids içinde canonical "
                "olmayan ID (grounding hatası): "
                f"{research_id}",
            )

    return (
        True,
        None,
    )


# ============================================================
# RENDER + FINALIZE ACCEPTED CANDIDATES
# ============================================================

def render_and_finalize_agent_candidates(
    accepted_raw,
    start_index,
):

    finalized = []

    render_warnings = []

    next_index = start_index

    for candidate in accepted_raw:

        source_issue_id = candidate[
            "source_issue_id"
        ]

        source_research_ids = candidate.get(
            "source_research_ids",
            [],
        )

        render = REASON_CODE_SPECS[
            candidate[
                "reason_code"
            ]
        ][
            "render"
        ]

        title, description = render(
            source_issue_id,
            source_research_ids,
        )

        combined = normalize_text_tr(
            f"{title} {description}"
        )

        if any(
            phrase in combined
            for phrase in ALL_FORBIDDEN_PHRASES
        ):

            render_warnings.append(
                "Render edilmiş agent case-law candidate "
                "metni blocklist'e takıldı (beklenmeyen "
                "durum); candidate atlandı."
            )

            continue

        try:

            confidence = float(
                candidate.get(
                    "confidence"
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            confidence = 0.3

        confidence = max(
            0.0,
            min(
                confidence,
                1.0,
            ),
        )

        finalized.append(
            {
                "suggestion_id":
                    f"case_law_suggestion_{next_index:03d}",

                "source_issue_id":
                    source_issue_id,

                "source_research_ids":
                    source_research_ids,

                "reason_code":
                    candidate[
                        "reason_code"
                    ],

                "title":
                    title,

                "description":
                    description,

                "trigger_rule_id":
                    AGENT_TRIGGER_RULE_ID,

                "confidence":
                    confidence,

                "requires_human_review":
                    True,

                "status":
                    "candidate",

                "notes":
                    (
                        "case_law_agent V1 tarafından "
                        "deterministik template ile render "
                        "edilmiştir; LLM bu metni doğrudan "
                        "üretmemiştir. Bu bir agent "
                        "suggestion'dır - court metadata "
                        "taşımaz, mahkeme kararı içermez, "
                        "grounded bir decision DEĞİLDİR."
                    ),
            }
        )

        next_index += 1

    return (
        finalized,
        render_warnings,
    )


# ============================================================
# ORCHESTRATOR
# ============================================================

def generate_agent_candidates(
    case_id,
    issue_index,
    research_index,
    start_index,
    existing_titles=None,
    llm_client=None,
    network_allowed=False,
):

    warnings = []

    allowed_issue_ids = set(
        issue_index.keys()
    )

    allowed_research_ids = set(
        research_index.keys()
    )

    empty_stats = {
        "raw_candidate_count":
            0,

        "accepted_count":
            0,

        "rejected_count":
            0,
    }

    if llm_client is None:

        if not network_allowed:

            warnings.append(
                "Network access disabled "
                "(network_allowed=False, --allow-network "
                "verilmedi); Case Law Agent atlandı, "
                "gerçek API çağrısı denenmedi."
            )

            return (
                [],
                warnings,
                empty_stats,
            )

        client = AnthropicCaseLawLLMClient()

    else:

        client = llm_client

    prompt = (
        build_user_prompt(
            case_id=
                case_id,

            issue_index=
                issue_index,

            research_index=
                research_index,

            existing_titles=
                existing_titles
                or [],
        )
    )

    try:

        raw_text = client.generate(
            prompt
        )

    except Exception as error:

        warnings.append(
            "Case Law Agent LLM çağrısı başarısız oldu; "
            f"agent candidate üretilmedi: {error}"
        )

        return (
            [],
            warnings,
            empty_stats,
        )

    try:

        raw_candidates = (
            parse_agent_response(
                raw_text
            )
        )

    except Exception as error:

        warnings.append(
            "Case Law Agent cevabı parse edilemedi; "
            f"agent candidate üretilmedi: {error}"
        )

        return (
            [],
            warnings,
            empty_stats,
        )

    raw_candidates = raw_candidates[
        :MAX_AGENT_CANDIDATES
    ]

    accepted_raw = []

    rejected_count = 0

    for candidate in raw_candidates:

        (
            ok,
            reason,
        ) = (
            validate_agent_candidate_shape(
                candidate,
                allowed_issue_ids,
                allowed_research_ids,
            )
        )

        if ok:

            accepted_raw.append(
                candidate
            )

        else:

            rejected_count += 1

            warnings.append(
                "Case Law Agent candidate reddedildi "
                f"({reason})."
            )

    (
        finalized,
        render_warnings,
    ) = (
        render_and_finalize_agent_candidates(
            accepted_raw,
            start_index,
        )
    )

    warnings.extend(
        render_warnings
    )

    return (
        finalized,
        warnings,
        {
            "raw_candidate_count":
                len(
                    raw_candidates
                ),

            "accepted_count":
                len(
                    finalized
                ),

            "rejected_count":
                rejected_count
                + (
                    len(
                        accepted_raw
                    )
                    - len(
                        finalized
                    )
                ),
        },
    )


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(
    case_id="case_0001",
):

    from legal_research_validator import (
        load_canonical_issues,
    )

    from case_law_validator import (
        load_canonical_research,
    )

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - CASE LAW AGENT V1"
    )

    print(
        "======================================"
    )

    issue_context = (
        load_canonical_issues(
            case_id
        )
    )

    issue_index = issue_context[
        "issue_index"
    ]

    (
        _researches,
        research_index,
        _research_path,
    ) = (
        load_canonical_research(
            case_id
        )
    )

    assert len(
        issue_index
    ) >= 1

    print(
        "T01 Canonical issue/research context load:",
        "PASS"
    )

    real_issue_id = next(
        iter(
            issue_index.keys()
        )
    )

    real_research_id = next(
        iter(
            research_index.keys()
        ),
        None,
    )

    # ========================================================
    # T02 VALID STRUCTURED SIGNAL ACCEPTED
    # ========================================================

    good_signal = {
        "reason_code":
            "related_case_law_area_review",

        "source_issue_id":
            real_issue_id,

        "source_research_ids":
            (
                [
                    real_research_id
                ]
                if real_research_id
                else []
            ),

        "related_party_ids": [],

        "related_dispute_item_ids": [],

        "confidence":
            0.4,
    }

    client = FakeCaseLawLLMClient(
        response_text=
            json.dumps(
                [
                    good_signal
                ],
                ensure_ascii=False,
            )
    )

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id=
            case_id,

        issue_index=
            issue_index,

        research_index=
            research_index,

        start_index=
            100,

        llm_client=
            client,
    )

    assert client.call_count == 1

    assert stats[
        "accepted_count"
    ] == 1

    assert finalized[
        0
    ][
        "suggestion_id"
    ] == "case_law_suggestion_100"

    assert finalized[
        0
    ][
        "reason_code"
    ] == "related_case_law_area_review"

    assert (
        "court_name"
        not in finalized[
            0
        ]
    )

    assert (
        "grounded_document_ids"
        not in finalized[
            0
        ]
    )

    assert (
        "source_document_id"
        not in finalized[
            0
        ]
    )

    assert finalized[
        0
    ][
        "requires_human_review"
    ] is True

    print(
        "T02 Valid structured signal accepted; agent "
        "suggestion carries NO court metadata field "
        "at all (structural, not just null):",
        "PASS"
    )

    # ========================================================
    # T03 UNGROUNDED SOURCE_ISSUE_ID REJECTED
    # ========================================================

    ungrounded = dict(
        good_signal
    )

    ungrounded[
        "source_issue_id"
    ] = "issue_does_not_exist"

    client = FakeCaseLawLLMClient(
        response_text=
            json.dumps(
                [
                    ungrounded
                ],
                ensure_ascii=False,
            )
    )

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        issue_index,
        research_index,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 0

    assert any(
        "grounding" in warning
        for warning in warnings
    )

    print(
        "T03 Ungrounded source_issue_id rejected:",
        "PASS"
    )

    # ========================================================
    # T04 COURT METADATA SMUGGLING ATTEMPT REJECTED
    #
    # LLM court_name/decision_date/case_number/source_url
    # üretmeye çalışırsa candidate TAMAMEN reddedilir.
    # ========================================================

    smuggling_attempt = dict(
        good_signal
    )

    smuggling_attempt[
        "court_name"
    ] = "Uydurma Danıştay Dairesi"

    smuggling_attempt[
        "decision_number"
    ] = "2020/1234"

    client = FakeCaseLawLLMClient(
        response_text=
            json.dumps(
                [
                    smuggling_attempt
                ],
                ensure_ascii=False,
            )
    )

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        issue_index,
        research_index,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 0

    assert any(
        "court-metadata safety" in warning
        for warning in warnings
    )

    print(
        "T04 Court metadata smuggling attempt rejected "
        "(structural, not blocklist):",
        "PASS"
    )

    # ========================================================
    # T05 INVALID REASON CODE REJECTED
    # ========================================================

    bad_reason = dict(
        good_signal
    )

    bad_reason[
        "reason_code"
    ] = "not_a_real_reason_code"

    client = FakeCaseLawLLMClient(
        response_text=
            json.dumps(
                [
                    bad_reason
                ],
                ensure_ascii=False,
            )
    )

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        issue_index,
        research_index,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 0

    print(
        "T05 Invalid reason_code rejected:",
        "PASS"
    )

    # ========================================================
    # T06 LLM CALL FAILURE -> FAIL CLOSED
    # ========================================================

    client = FakeCaseLawLLMClient(
        raise_error=
            RuntimeError(
                "simulated network failure"
            )
    )

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        issue_index,
        research_index,
        1,
        llm_client=
            client,
    )

    assert finalized == []

    assert len(
        warnings
    ) == 1

    print(
        "T06 LLM call failure fails closed:",
        "PASS"
    )

    # ========================================================
    # T07 UNPARSEABLE RESPONSE -> FAIL CLOSED
    # ========================================================

    client = FakeCaseLawLLMClient(
        response_text=
            "bu bir JSON değildir."
    )

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        issue_index,
        research_index,
        1,
        llm_client=
            client,
    )

    assert finalized == []

    print(
        "T07 Unparseable response fails closed:",
        "PASS"
    )

    # ========================================================
    # T08 EMPTY ARRAY -> CLEAN NO-OP
    # ========================================================

    client = FakeCaseLawLLMClient(
        response_text=
            "[]"
    )

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        issue_index,
        research_index,
        1,
        llm_client=
            client,
    )

    assert finalized == []

    assert warnings == []

    print(
        "T08 Empty array clean no-op:",
        "PASS"
    )

    # ========================================================
    # T09 NETWORK GATE: llm_client YOK + network_allowed
    # VARSAYILAN (False) -> gerçek client HİÇ OLUŞTURULMAZ
    # ========================================================

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        issue_index,
        research_index,
        1,
        llm_client=
            None,
    )

    assert finalized == []

    assert len(
        warnings
    ) == 1

    assert (
        "Network access disabled"
        in warnings[
            0
        ]
    )

    print(
        "T09 Network safety gate blocks real client "
        "by default:",
        "PASS"
    )

    print()

    print(
        "======================================"
    )

    print(
        " CASE LAW AGENT V1: 9/9 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    run_self_test()
