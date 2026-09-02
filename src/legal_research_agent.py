# ============================================================
# VERGİ AI - LEGAL RESEARCH AGENT V1
#
# AMAÇ
# ----
#
# Legal Research Policy/Engine V1 (deterministik katman)
# ÜZERİNE, LLM tabanlı EK araştırma önerileri (research
# candidate) üretmek.
#
#
# KRİTİK SINIR
# ------------
#
# Bu modül Legal Research Policy/Engine'in ve altındaki
# Legal Knowledge Engine'in (provision_repository +
# provision_version_policy + provision_policy) YERİNE GEÇMEZ.
#
#   - Formal/applicability/version çözümü YALNIZ deterministik
#     Legal Knowledge Engine tarafından yapılır. Agent bu
#     alanları (finding_status="resolved"/"resolved_version_
#     unknown", formal_result, applicability_result,
#     resolved_provision_ids) ASLA dolduramaz - finalize
#     bunları her zaman "agent_suggested" / null / boş olarak
#     sabitler.
#
#   - Bu Agent yalnız EK "research candidate" ÖNERİR: "bu
#     noktanın ayrıca araştırılması gerekebilir" türünde.
#
#   - Agent çıktısı:
#       != hükmün yürürlükte olduğunun kesinleşmesi
#       != applicability'nin kesinleşmesi
#       != case outcome
#       != kesin hukuki sonuç
#       != yeni bir citation/provision uydurma
#
#
# AGENT FREE-TEXT SAFETY (Row 9 V1.1 dersleri buraya taşındı)
# --------------------------------------------------------------
#
# LLM'e title/description/notes YAZDIRILMAZ. LLM yalnız
# yapılandırılmış bir sinyal üretir:
#
#   - reason_code          (sabit, küçük bir enum)
#   - source_issue_id      (yalnız verilen canonical issue
#                            listesinden)
#   - source_fact_ids / source_timeline_event_ids /
#     source_deadline_ids  (yalnız verilen canonical ID
#                            listelerinden)
#   - related_party_ids / related_dispute_item_ids
#   - confidence
#
# title ve description, bu sinyal doğrulandıktan SONRA,
# TAMAMEN deterministik bir template renderer tarafından,
# yalnız sabit Türkçe cümleler ve canonical veri kullanılarak
# üretilir. "title"/"description"/"notes" alanı içeren bir LLM
# çıktısı, bu alanların varlığı nedeniyle TAMAMEN REDDEDİLİR.
#
# Blocklist (FORBIDDEN_PHRASES) render edilmiş metin üzerinde
# EK bir savunma katmanıdır; ana mekanizma DEĞİLDİR.
#
#
# NETWORK SAFETY GATE (Row 9 V1.1 ile birebir aynı desen)
# -----------------------------------------------------------
#
# Gerçek Anthropic API çağrısı için İKİ açık koşul gerekir:
#
#   1. llm_client açıkça VERİLMEMİŞ olmalı (varsayılan client
#      kullanılacak), VE
#   2. network_allowed=True açıkça geçilmiş olmalı.
#
# Aksi halde AnthropicLegalResearchLLMClient HİÇ OLUŞTURULMAZ.
#
# FakeLegalResearchLLMClient hiçbir koşulda gerçek network
# çağrısı yapmaz; testler ve self-test bununla, offline
# çalışır.
# ============================================================


import json
import os
import re


from issue_spotting_validator import (
    FORBIDDEN_PHRASES,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)


# ============================================================
# VERSION
# ============================================================

LEGAL_RESEARCH_AGENT_VERSION = "1"

AGENT_TRIGGER_RULE_ID = "research_rule_agent_llm_v1"

DEFAULT_AGENT_MODEL = "claude-sonnet-4-6"

MAX_AGENT_CANDIDATES = 10


# ============================================================
# LLM CANDIDATE - İZİN VERİLEN ALANLAR
#
# Bu kümenin DIŞINDA bir alan (özellikle title/description/
# notes/finding_status/formal_result/applicability_result/
# resolved_provision_ids gibi deterministik-engine-only
# alanlar) içeren bir LLM çıktısı TAMAMEN REDDEDİLİR.
# ============================================================

ALLOWED_LLM_CANDIDATE_KEYS = {
    "reason_code",
    "source_issue_id",
    "source_fact_ids",
    "source_timeline_event_ids",
    "source_deadline_ids",
    "related_party_ids",
    "related_dispute_item_ids",
    "confidence",
}


# ============================================================
# EXCEPTION
# ============================================================

class LegalResearchAgentError(
    Exception
):
    pass


# ============================================================
# LLM CLIENT INTERFACE
# ============================================================

class AnthropicLegalResearchLLMClient:

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

            raise LegalResearchAgentError(
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

            raise LegalResearchAgentError(
                "LLM boş cevap döndürdü."
            )

        return result


class FakeLegalResearchLLMClient:

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

def _quote_fact_statements(
    fact_index,
    fact_ids,
    limit=2,
):

    quoted = []

    for fact_id in fact_ids[
        :limit
    ]:

        record = fact_index.get(
            fact_id
        )

        statement = (
            record[
                "fact"
            ].get(
                "statement"
            )
            if record
            else None
        )

        if statement:

            quoted.append(
                f"{fact_id}: \"{statement}\""
            )

        else:

            quoted.append(
                fact_id
            )

    return "; ".join(
        quoted
    )


def _join_all_sources(
    source_fact_ids,
    source_timeline_event_ids,
    source_deadline_ids,
):

    return ", ".join(
        source_fact_ids
        + source_timeline_event_ids
        + source_deadline_ids
    )


def render_citation_completeness_review(
    source_fact_ids,
    source_timeline_event_ids,
    source_deadline_ids,
    fact_index,
    event_index,
    deadline_index,
):

    title = (
        "Ek hukuki dayanak olup olmadığı ayrıca "
        "değerlendirilebilir"
    )

    body = (
        _quote_fact_statements(
            fact_index,
            source_fact_ids,
        )
        or _join_all_sources(
            source_fact_ids,
            source_timeline_event_ids,
            source_deadline_ids,
        )
    )

    description = (
        "Agent tarafından işaretlenen aşağıdaki canonical "
        "kayıtlarda, yapılandırılmış olarak çıkarılmamış "
        "ek hukuki dayanaklar bulunup bulunmadığının "
        f"ayrıca değerlendirilmesi önerilir. {body}"
    )

    return (
        title,
        description,
    )


def render_general_review_needed(
    source_fact_ids,
    source_timeline_event_ids,
    source_deadline_ids,
    fact_index,
    event_index,
    deadline_index,
):

    title = (
        "Ek hukuki araştırma gerekebilecek bir nokta "
        "tespit edildi"
    )

    description = (
        "Agent tarafından işaretlenen şu canonical "
        "kayıtların ayrıca hukuki açıdan araştırılması "
        "önerilir: "
        + _join_all_sources(
            source_fact_ids,
            source_timeline_event_ids,
            source_deadline_ids,
        )
        + "."
    )

    return (
        title,
        description,
    )


REASON_CODE_SPECS = {
    "citation_completeness_review": {
        "render":
            render_citation_completeness_review,
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
        "canonical bir issue candidate için EK hukuki "
        "araştırma signal'i öneren bir yardımcı "
        "bileşensin.\n\n"
        "KESİN SINIRLAR:\n"
        "1. Hiçbir serbest metin (başlık, açıklama, yorum, "
        "not) ÜRETMEZSİN. Yalnız yapılandırılmış alanlar "
        "döndürürsün: reason_code, source_issue_id, "
        "source_fact_ids, source_timeline_event_ids, "
        "source_deadline_ids, related_party_ids, "
        "related_dispute_item_ids, confidence. Bunların "
        "dışında (özellikle 'title', 'description', "
        "'notes', 'finding_status', 'formal_result', "
        "'applicability_result', 'resolved_provision_ids' "
        "gibi) HİÇBİR alan EKLEYEMEZSİN; eklersen "
        "candidate'ın TAMAMI reddedilir.\n"
        "2. Bir hükmün yürürlükte olduğunu, uygulanabilir "
        "olduğunu veya davanın sonucunu ASLA "
        "belirleyemezsin - bunlar yalnız deterministik "
        "Legal Knowledge Engine tarafından hesaplanır.\n"
        "3. Yeni bir citation/madde/kanun UYDURAMAZSIN.\n"
        "4. reason_code yalnızca şu sabit listeden biri "
        f"olabilir: {reason_code_list}.\n"
        "5. source_issue_id yalnızca sana verilen canonical "
        "issue listesindeki bir issue_id olabilir.\n"
        "6. source_fact_ids / source_timeline_event_ids / "
        "source_deadline_ids yalnızca sana verilen "
        "listelerdeki ID'ler olabilir.\n"
        "7. En az bir source_fact_ids / "
        "source_timeline_event_ids / source_deadline_ids "
        "değeri boş olmayan bir listede bulunmalıdır.\n"
        "8. Zaten deterministik olarak araştırılmış "
        "noktaları TEKRARLAMA.\n"
        "9. Yanıtın YALNIZCA bir JSON array olmalıdır; "
        "başka hiçbir metin veya markdown içermemelidir.\n"
        "10. Emin değilsen boş array döndür: []"
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


def summarize_facts(
    fact_index,
):

    return [
        {
            "fact_id":
                fact_id,

            "fact_kind":
                record[
                    "fact"
                ].get(
                    "fact_kind"
                ),

            "statement":
                record[
                    "fact"
                ].get(
                    "statement"
                ),
        }
        for fact_id, record
        in fact_index.items()
    ]


def summarize_events(
    event_index,
):

    return [
        {
            "event_id":
                event_id,

            "event_type":
                event.get(
                    "event_type"
                ),

            "date":
                event.get(
                    "date"
                ),
        }
        for event_id, event
        in event_index.items()
    ]


def summarize_deadlines(
    deadline_index,
):

    return [
        {
            "deadline_id":
                deadline_id,

            "calculation_state":
                deadline.get(
                    "calculation_state"
                ),
        }
        for deadline_id, deadline
        in deadline_index.items()
    ]


# ============================================================
# USER PROMPT
# ============================================================

def build_user_prompt(
    case_id,
    issue_index,
    fact_index,
    event_index,
    deadline_index,
    existing_research_titles,
):

    payload = {
        "case_id":
            case_id,

        "canonical_issues":
            summarize_issues(
                issue_index
            ),

        "canonical_facts":
            summarize_facts(
                fact_index
            ),

        "canonical_timeline_events":
            summarize_events(
                event_index
            ),

        "canonical_deadlines":
            summarize_deadlines(
                deadline_index
            ),

        "already_researched_titles":
            existing_research_titles,
    }

    return (
        "Aşağıdaki canonical veri üzerinden, deterministik "
        "Legal Knowledge Engine araştırmasının kapsamadığı "
        "EK research signal önerileri üret. Yalnız JSON "
        "array döndür.\n\n"
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

        raise LegalResearchAgentError(
            "LLM cevabı JSON array değil."
        )

    return parsed


# ============================================================
# CANDIDATE SHAPE + GROUNDING VALIDATION
# ============================================================

def validate_agent_candidate_shape(
    candidate,
    allowed_issue_ids,
    allowed_fact_ids,
    allowed_event_ids,
    allowed_deadline_ids,
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
            "(free-text/deterministic-only safety "
            f"ihlali): {sorted(forbidden_keys)}",
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

    source_fact_ids = candidate.get(
        "source_fact_ids",
        [],
    )

    source_timeline_event_ids = candidate.get(
        "source_timeline_event_ids",
        [],
    )

    source_deadline_ids = candidate.get(
        "source_deadline_ids",
        [],
    )

    for (
        label,
        values,
        allowed,
    ) in (
        (
            "source_fact_ids",
            source_fact_ids,
            allowed_fact_ids,
        ),
        (
            "source_timeline_event_ids",
            source_timeline_event_ids,
            allowed_event_ids,
        ),
        (
            "source_deadline_ids",
            source_deadline_ids,
            allowed_deadline_ids,
        ),
    ):

        if not isinstance(
            values,
            list,
        ):

            return (
                False,
                f"{label} list değil",
            )

        for value in values:

            if (
                not isinstance(
                    value,
                    str,
                )
                or value not in allowed
            ):

                return (
                    False,
                    f"{label} içinde canonical olmayan "
                    f"ID (grounding hatası): {value}",
                )

    total_sources = (
        len(
            source_fact_ids
        )
        + len(
            source_timeline_event_ids
        )
        + len(
            source_deadline_ids
        )
    )

    if total_sources == 0:

        return (
            False,
            "en az bir canonical kaynak gerekli",
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
    fact_index,
    event_index,
    deadline_index,
):

    finalized = []

    render_warnings = []

    next_index = start_index

    for candidate in accepted_raw:

        source_fact_ids = candidate.get(
            "source_fact_ids",
            [],
        )

        source_timeline_event_ids = candidate.get(
            "source_timeline_event_ids",
            [],
        )

        source_deadline_ids = candidate.get(
            "source_deadline_ids",
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
            source_fact_ids,
            source_timeline_event_ids,
            source_deadline_ids,
            fact_index,
            event_index,
            deadline_index,
        )

        combined = normalize_text_tr(
            f"{title} {description}"
        )

        if any(
            phrase in combined
            for phrase in FORBIDDEN_PHRASES
        ):

            render_warnings.append(
                "Render edilmiş agent research candidate "
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

            confidence = 0.5

        confidence = max(
            0.0,
            min(
                confidence,
                1.0,
            ),
        )

        finalized.append(
            {
                "research_id":
                    f"research_{next_index:03d}",

                "research_type":
                    "agent_suggestion",

                "source_issue_id":
                    candidate[
                        "source_issue_id"
                    ],

                "title":
                    title,

                "description":
                    description,

                "trigger_rule_id":
                    AGENT_TRIGGER_RULE_ID,

                "citation_refs": [],

                "resolved_provision_ids": [],

                "finding_status":
                    "agent_suggested",

                "formal_result":
                    None,

                "applicability_result":
                    None,

                "retrieval_query":
                    None,

                "source_fact_ids":
                    source_fact_ids,

                "source_timeline_event_ids":
                    source_timeline_event_ids,

                "source_deadline_ids":
                    source_deadline_ids,

                "related_party_ids":
                    candidate.get(
                        "related_party_ids",
                        [],
                    ),

                "related_dispute_item_ids":
                    candidate.get(
                        "related_dispute_item_ids",
                        [],
                    ),

                "confidence":
                    confidence,

                "requires_human_review":
                    True,

                "status":
                    "candidate",

                "notes":
                    (
                        "legal_research_agent V1 "
                        "tarafından deterministik "
                        f"template '{candidate['reason_code']}' "
                        "ile render edilmiştir; LLM bu "
                        "metni doğrudan üretmemiştir. Bu "
                        "kayıt bir provision resolution "
                        "değildir."
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
    fact_index,
    event_index,
    deadline_index,
    start_index,
    existing_titles=None,
    llm_client=None,
    network_allowed=False,
):

    warnings = []

    allowed_issue_ids = set(
        issue_index.keys()
    )

    allowed_fact_ids = set(
        fact_index.keys()
    )

    allowed_event_ids = set(
        event_index.keys()
    )

    allowed_deadline_ids = set(
        deadline_index.keys()
    )

    empty_stats = {
        "raw_candidate_count":
            0,

        "accepted_count":
            0,

        "rejected_count":
            0,
    }

    # ========================================================
    # NETWORK SAFETY GATE
    # ========================================================

    if llm_client is None:

        if not network_allowed:

            warnings.append(
                "Network access disabled "
                "(network_allowed=False, --allow-network "
                "verilmedi); Legal Research Agent atlandı, "
                "gerçek API çağrısı denenmedi."
            )

            return (
                [],
                warnings,
                empty_stats,
            )

        client = AnthropicLegalResearchLLMClient()

    else:

        client = llm_client

    prompt = (
        build_user_prompt(
            case_id=
                case_id,

            issue_index=
                issue_index,

            fact_index=
                fact_index,

            event_index=
                event_index,

            deadline_index=
                deadline_index,

            existing_research_titles=
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
            "Legal Research Agent LLM çağrısı başarısız "
            f"oldu; agent candidate üretilmedi: {error}"
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
            "Legal Research Agent cevabı parse edilemedi; "
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
                allowed_fact_ids,
                allowed_event_ids,
                allowed_deadline_ids,
            )
        )

        if ok:

            accepted_raw.append(
                candidate
            )

        else:

            rejected_count += 1

            warnings.append(
                "Legal Research Agent candidate "
                f"reddedildi ({reason})."
            )

    (
        finalized,
        render_warnings,
    ) = (
        render_and_finalize_agent_candidates(
            accepted_raw,
            start_index,
            fact_index,
            event_index,
            deadline_index,
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
#
# Gerçek API key veya network erişimi GEREKTİRMEZ.
# ============================================================

def run_self_test(
    case_id="case_0001",
):

    from timeline_validator import (
        load_canonical_fact_index,
    )

    from deadline_validator import (
        load_canonical_timeline,
    )

    from legal_research_validator import (
        load_canonical_deadline_index,
        load_canonical_issues,
    )

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - LEGAL RESEARCH AGENT V1"
    )

    print(
        "======================================"
    )

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = fact_context[
        "facts"
    ]

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    event_index = timeline_context[
        "events"
    ]

    (
        deadline_index,
        _deadline_ids,
        _deadline_path,
    ) = (
        load_canonical_deadline_index(
            case_id
        )
    )

    issue_context = (
        load_canonical_issues(
            case_id
        )
    )

    issue_index = issue_context[
        "issue_index"
    ]

    assert len(
        issue_index
    ) >= 1

    print(
        "T01 Canonical context load "
        "(issues/facts/timeline/deadlines):",
        "PASS"
    )

    real_issue_id = next(
        iter(
            issue_index.keys()
        )
    )

    real_fact_id = next(
        iter(
            fact_index.keys()
        )
    )

    # ========================================================
    # T02 VALID STRUCTURED SIGNAL ACCEPTED, TEXT RENDERED
    # DETERMINISTICALLY
    # ========================================================

    good_signal = {
        "reason_code":
            "citation_completeness_review",

        "source_issue_id":
            real_issue_id,

        "source_fact_ids": [
            real_fact_id
        ],

        "source_timeline_event_ids": [],

        "source_deadline_ids": [],

        "related_party_ids": [],

        "related_dispute_item_ids": [],

        "confidence":
            0.5,
    }

    client = FakeLegalResearchLLMClient(
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

        fact_index=
            fact_index,

        event_index=
            event_index,

        deadline_index=
            deadline_index,

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
        "research_id"
    ] == "research_100"

    assert finalized[
        0
    ][
        "research_type"
    ] == "agent_suggestion"

    assert finalized[
        0
    ][
        "finding_status"
    ] == "agent_suggested"

    assert finalized[
        0
    ][
        "formal_result"
    ] is None

    assert finalized[
        0
    ][
        "applicability_result"
    ] is None

    assert finalized[
        0
    ][
        "resolved_provision_ids"
    ] == []

    assert finalized[
        0
    ][
        "trigger_rule_id"
    ] == AGENT_TRIGGER_RULE_ID

    assert finalized[
        0
    ][
        "status"
    ] == "candidate"

    assert real_fact_id in (
        finalized[
            0
        ][
            "title"
        ]
        + finalized[
            0
        ][
            "description"
        ]
    )

    print(
        "T02 Valid structured signal accepted; "
        "deterministic-engine-only fields stay null/empty:",
        "PASS"
    )

    # ========================================================
    # T03 UNGROUNDED SOURCE_ISSUE_ID REJECTED
    # ========================================================

    ungrounded_issue = dict(
        good_signal
    )

    ungrounded_issue[
        "source_issue_id"
    ] = "issue_does_not_exist"

    client = FakeLegalResearchLLMClient(
        response_text=
            json.dumps(
                [
                    ungrounded_issue
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
        fact_index,
        event_index,
        deadline_index,
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
    # T04 UNGROUNDED FACT ID REJECTED
    # ========================================================

    ungrounded_fact = dict(
        good_signal
    )

    ungrounded_fact[
        "source_fact_ids"
    ] = [
        "fact_does_not_exist"
    ]

    client = FakeLegalResearchLLMClient(
        response_text=
            json.dumps(
                [
                    ungrounded_fact
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
        fact_index,
        event_index,
        deadline_index,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 0

    print(
        "T04 Ungrounded fact_id rejected:",
        "PASS"
    )

    # ========================================================
    # T05 FREE-TEXT / DETERMINISTIC-ONLY FIELD SMUGGLING
    # REJECTED
    #
    # LLM formal_result/finding_status/title vermeye
    # çalışırsa candidate tamamen reddedilir.
    # ========================================================

    smuggling_attempt = dict(
        good_signal
    )

    smuggling_attempt[
        "formal_result"
    ] = "valid"

    smuggling_attempt[
        "title"
    ] = "Bu madde kesin olarak yürürlüktedir"

    client = FakeLegalResearchLLMClient(
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
        fact_index,
        event_index,
        deadline_index,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 0

    assert any(
        "free-text/deterministic-only safety" in warning
        for warning in warnings
    )

    print(
        "T05 Deterministic-only field / free-text "
        "smuggling attempt rejected:",
        "PASS"
    )

    # ========================================================
    # T06 INVALID REASON CODE REJECTED
    # ========================================================

    bad_reason = dict(
        good_signal
    )

    bad_reason[
        "reason_code"
    ] = "not_a_real_reason_code"

    client = FakeLegalResearchLLMClient(
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
        fact_index,
        event_index,
        deadline_index,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 0

    print(
        "T06 Invalid reason_code rejected:",
        "PASS"
    )

    # ========================================================
    # T07 LLM CALL FAILURE -> FAIL CLOSED
    # ========================================================

    client = FakeLegalResearchLLMClient(
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
        fact_index,
        event_index,
        deadline_index,
        1,
        llm_client=
            client,
    )

    assert finalized == []

    assert len(
        warnings
    ) == 1

    print(
        "T07 LLM call failure fails closed:",
        "PASS"
    )

    # ========================================================
    # T08 UNPARSEABLE RESPONSE -> FAIL CLOSED
    # ========================================================

    client = FakeLegalResearchLLMClient(
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
        fact_index,
        event_index,
        deadline_index,
        1,
        llm_client=
            client,
    )

    assert finalized == []

    print(
        "T08 Unparseable response fails closed:",
        "PASS"
    )

    # ========================================================
    # T09 EMPTY ARRAY -> CLEAN NO-OP
    # ========================================================

    client = FakeLegalResearchLLMClient(
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
        fact_index,
        event_index,
        deadline_index,
        1,
        llm_client=
            client,
    )

    assert finalized == []

    assert warnings == []

    print(
        "T09 Empty array clean no-op:",
        "PASS"
    )

    # ========================================================
    # T10 NETWORK GATE: llm_client YOK + network_allowed
    # VARSAYILAN (False) -> gerçek client HİÇ OLUŞTURULMAZ
    # ========================================================

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        issue_index,
        fact_index,
        event_index,
        deadline_index,
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
        "T10 Network safety gate blocks real client "
        "by default:",
        "PASS"
    )

    print()

    print(
        "======================================"
    )

    print(
        " LEGAL RESEARCH AGENT V1: 10/10 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    run_self_test()
