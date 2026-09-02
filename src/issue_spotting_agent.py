# ============================================================
# VERGİ AI - ISSUE SPOTTING AGENT V1.1
#
# AMAÇ
# ----
#
# Issue Spotting Policy/Engine V1 (deterministik katman)
# ÜZERİNE, LLM tabanlı EK issue candidate önerileri üretmek.
#
#
# KRİTİK SINIR
# ------------
#
# Bu modül Issue Spotting Policy/Engine V1'in yerine GEÇMEZ.
#
#   - Deterministic Policy/Engine: source of truth ve safety
#     boundary'dir. Bu modül onu DEĞİŞTİRMEZ, sarmalamaz,
#     sonuçlarını override ETMEZ.
#
#   - Bu Agent yalnız EK "issue candidate" ÖNERİR.
#
#   - Agent çıktısı:
#       != verified fact
#       != legal conclusion
#       != deadline sonucu
#       != applicability kesinleşmesi
#       != case outcome tahmini
#
#
# V1.1 DEĞİŞİKLİĞİ - AGENT FREE-TEXT SAFETY
# -------------------------------------------
#
# V1'de LLM title/description serbest metnini DOĞRUDAN
# üretiyordu. Grounding kontrolü kaynak ID'lerin gerçek
# olmasını garanti ediyordu, ama LLM'in o gerçek kaynaklar
# hakkında YAZDIĞI METNİN İÇERİĞİNİ (ör. "hukuka aykırıdır")
# yapısal olarak engellemiyordu; yalnız blocklist buna karşı
# koyuyordu ve blocklist tek başına yeterli bir güvenlik
# mekanizması DEĞİLDİR.
#
# V1.1'de LLM'e title/description YAZDIRILMAZ. LLM yalnız
# YAPILANDIRILMIŞ bir "issue signal" üretir:
#
#   - issue_type      (sabit enum)
#   - reason_code      (sabit, küçük bir enum - REASON_CODE_SPECS)
#   - source_fact_ids / source_timeline_event_ids /
#     source_deadline_ids (yalnız verilen canonical ID
#     listelerinden)
#   - related_party_ids / related_dispute_item_ids
#   - confidence
#
# title ve description, bu yapılandırılmış sinyal
# doğrulandıktan (schema + grounding) SONRA, TAMAMEN
# deterministik bir TEMPLATE RENDERER (render_issue_text)
# tarafından, yalnız sabit Türkçe şablon cümleleri ve
# canonical veri alanları (ID, tarih, event_type, fact
# statement'ı gibi) kullanılarak üretilir.
#
# SONUÇ: LLM canonical candidate'a hiçbir serbest metin
# karakteri YAZAMAZ. "title" veya "description" (veya "notes")
# alanı içeren bir LLM çıktısı, bu alanların varlığı nedeniyle
# TAMAMEN REDDEDİLİR (bkz. validate_agent_candidate_shape).
#
# Blocklist (FORBIDDEN_PHRASES) hâlâ, render edilmiş metin
# üzerinde EK bir savunma katmanı olarak çalışır; ama artık
# ana güvenlik mekanizması DEĞİLDİR - ana mekanizma yapısal
# şema kısıtlamasıdır.
#
#
# V1.1 DEĞİŞİKLİĞİ - NETWORK SAFETY GATE
# -----------------------------------------
#
# Gerçek Anthropic API çağrısı yapılabilmesi için artık İKİ
# açık koşul birden gerekir:
#
#   1. Çağıran taraf açıkça bir llm_client VERMEMİŞ olmalı
#      (yani varsayılan client kullanılacak), VE
#   2. network_allowed=True açıkça geçilmiş olmalı.
#
# network_allowed=False (varsayılan) olduğunda ve llm_client
# verilmediğinde, AnthropicIssueLLMClient HİÇ
# OLUŞTURULMAZ - gerçek bir network denemesi dahi yapılmaz.
#
# Bir çağıran taraf (ör. testler) açıkça bir llm_client
# (FakeIssueLLMClient gibi) verirse, bu client kullanılır;
# FakeIssueLLMClient hiçbir koşulda gerçek network çağrısı
# yapmaz (bkz. sınıf tanımı).
#
#
# TEST EDİLEBİLİRLİK
# -------------------
#
# FakeIssueLLMClient ile API key olmadan, network'e hiç
# dokunmadan, deterministic/tekrarlanabilir synthetic testler
# çalıştırılabilir (bkz. run_self_test()).
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

ISSUE_SPOTTING_AGENT_VERSION = "1.1"

AGENT_TRIGGER_RULE_ID = "issue_rule_agent_llm_v1"

DEFAULT_AGENT_MODEL = "claude-sonnet-4-6"

MAX_AGENT_CANDIDATES = 10


# ============================================================
# ALLOWED ISSUE TYPES
#
# case_issue_spotting.schema.json ile birebir aynı enum.
# ============================================================

ALLOWED_ISSUE_TYPES = {
    "verification_gap",
    "deadline_risk",
    "legal_basis_reference",
    "procedural_risk",
    "other",
}


# ============================================================
# LLM CANDIDATE - İZİN VERİLEN ALANLAR
#
# Bu kümenin DIŞINDA bir alan (özellikle title/description/
# notes gibi serbest metin alanları) içeren bir LLM çıktısı
# TAMAMEN REDDEDİLİR.
# ============================================================

ALLOWED_LLM_CANDIDATE_KEYS = {
    "issue_type",
    "reason_code",
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

class IssueSpottingAgentError(
    Exception
):
    pass


# ============================================================
# LLM CLIENT INTERFACE
#
# generate(prompt: str) -> str
# ============================================================

class AnthropicIssueLLMClient:

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

            raise IssueSpottingAgentError(
                "ANTHROPIC_API_KEY bulunamadı. "
                ".env dosyasını kontrol et."
            )

        # ----------------------------------------------------
        # Bağımlılık ve gerçek network çağrısı yalnız bu
        # metot GERÇEKTEN çağrıldığında devreye girer.
        # ----------------------------------------------------

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

            raise IssueSpottingAgentError(
                "LLM boş cevap döndürdü."
            )

        return result


class FakeIssueLLMClient:

    # --------------------------------------------------------
    # Bu client GERÇEK BİR NETWORK ÇAĞRISI YAPMAZ. Yalnız
    # kurucuda verilen sabit metni döndürür veya verilen
    # hatayı fırlatır. Testler ve --allow-network verilmeyen
    # CLI çalıştırmaları için güvenlidir.
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
#
# LLM yalnız bu sabit listeden bir reason_code seçebilir.
# Her reason_code, hangi issue_type değerleriyle uyumlu
# olduğunu ve title/description'ın NASIL render edileceğini
# (yalnız canonical veriden, LLM metni OLMADAN) tanımlar.
# ============================================================

def _fact_statement(
    fact_index,
    fact_id,
):

    record = fact_index.get(
        fact_id
    )

    if not record:

        return None

    return record[
        "fact"
    ].get(
        "statement"
    )


def _quote_fact_statements(
    fact_index,
    fact_ids,
    limit=2,
):

    quoted = []

    for fact_id in fact_ids[
        :limit
    ]:

        statement = (
            _fact_statement(
                fact_index,
                fact_id,
            )
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


def _describe_events(
    event_index,
    event_ids,
    limit=2,
):

    described = []

    for event_id in event_ids[
        :limit
    ]:

        event = event_index.get(
            event_id
        )

        if event:

            described.append(
                f"{event_id} "
                f"({event.get('event_type')}, "
                f"{event.get('date')})"
            )

        else:

            described.append(
                event_id
            )

    return "; ".join(
        described
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


def render_cross_fact_consistency_review(
    source_fact_ids,
    source_timeline_event_ids,
    source_deadline_ids,
    fact_index,
    event_index,
    deadline_index,
):

    title = (
        "İlişkili canonical fact kayıtları arasındaki "
        "tutarlılık ayrıca doğrulanabilir"
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
        "fact kayıtları arasındaki tutarlılığın ayrıca "
        f"değerlendirilmesi önerilir. {body}"
    )

    return (
        title,
        description,
    )


def render_authority_scope_review(
    source_fact_ids,
    source_timeline_event_ids,
    source_deadline_ids,
    fact_index,
    event_index,
    deadline_index,
):

    title = (
        "İlgili işlemi gerçekleştiren makamın yetki "
        "kapsamı ayrıca değerlendirilebilir"
    )

    description = (
        "Agent tarafından işaretlenen canonical kayıtlara "
        "göre, ilgili işlemi gerçekleştiren makamın yetki "
        "kapsamının ayrıca doğrulanması önerilir. Kaynak "
        "kayıtlar: "
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


def render_temporal_consistency_review(
    source_fact_ids,
    source_timeline_event_ids,
    source_deadline_ids,
    fact_index,
    event_index,
    deadline_index,
):

    title = (
        "İlgili olaylar arasındaki tarihsel tutarlılık "
        "ayrıca değerlendirilebilir"
    )

    body = (
        _describe_events(
            event_index,
            source_timeline_event_ids,
        )
        or _join_all_sources(
            source_fact_ids,
            source_timeline_event_ids,
            source_deadline_ids,
        )
    )

    description = (
        "Agent tarafından işaretlenen aşağıdaki timeline "
        "olayları arasındaki tarihsel tutarlılığın ayrıca "
        f"değerlendirilmesi önerilir: {body}."
    )

    return (
        title,
        description,
    )


def render_amount_consistency_review(
    source_fact_ids,
    source_timeline_event_ids,
    source_deadline_ids,
    fact_index,
    event_index,
    deadline_index,
):

    title = (
        "Belirtilen tutarlar arasındaki tutarlılık "
        "ayrıca doğrulanabilir"
    )

    description = (
        "Agent tarafından işaretlenen canonical fact "
        "kayıtlarındaki tutarların birbiriyle "
        "tutarlılığının ayrıca doğrulanması önerilir. "
        "Kaynak fact kayıtları: "
        + ", ".join(
            source_fact_ids
        )
        + "."
    )

    return (
        title,
        description,
    )


def render_procedural_completeness_review(
    source_fact_ids,
    source_timeline_event_ids,
    source_deadline_ids,
    fact_index,
    event_index,
    deadline_index,
):

    title = (
        "İlgili işlem sürecinin usul yönünden eksiksizliği "
        "ayrıca değerlendirilebilir"
    )

    description = (
        "Agent tarafından işaretlenen canonical kayıtlara "
        "göre, ilgili işlem sürecinin usul yönünden "
        "eksiksiz olup olmadığının ayrıca "
        "değerlendirilmesi önerilir. Kaynak kayıtlar: "
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


def render_general_review_needed(
    source_fact_ids,
    source_timeline_event_ids,
    source_deadline_ids,
    fact_index,
    event_index,
    deadline_index,
):

    title = (
        "Ek inceleme gerekebilecek bir nokta tespit edildi"
    )

    description = (
        "Agent tarafından işaretlenen şu canonical "
        "kayıtların ayrıca değerlendirilmesi önerilir: "
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
    "cross_fact_consistency_review": {
        "allowed_issue_types": {
            "verification_gap",
            "procedural_risk",
            "other",
        },

        "render":
            render_cross_fact_consistency_review,
    },

    "authority_scope_review": {
        "allowed_issue_types": {
            "procedural_risk",
            "legal_basis_reference",
            "other",
        },

        "render":
            render_authority_scope_review,
    },

    "temporal_consistency_review": {
        "allowed_issue_types": {
            "verification_gap",
            "deadline_risk",
            "other",
        },

        "render":
            render_temporal_consistency_review,
    },

    "amount_consistency_review": {
        "allowed_issue_types": {
            "procedural_risk",
            "other",
        },

        "render":
            render_amount_consistency_review,
    },

    "procedural_completeness_review": {
        "allowed_issue_types": {
            "procedural_risk",
            "other",
        },

        "render":
            render_procedural_completeness_review,
    },

    "general_review_needed": {
        "allowed_issue_types": {
            "verification_gap",
            "deadline_risk",
            "legal_basis_reference",
            "procedural_risk",
            "other",
        },

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
        "Sen bir vergi hukuku uyuşmazlık dosyasında EK "
        "issue signal öneren bir yardımcı bileşensin.\n\n"
        "KESİN SINIRLAR:\n"
        "1. Hiçbir serbest metin (başlık, açıklama, yorum, "
        "not) ÜRETMEZSİN. Yalnız yapılandırılmış alanlar "
        "döndürürsün: issue_type, reason_code, "
        "source_fact_ids, source_timeline_event_ids, "
        "source_deadline_ids, related_party_ids, "
        "related_dispute_item_ids, confidence. Bunların "
        "dışında (özellikle 'title', 'description', "
        "'notes' gibi) HİÇBİR alan EKLEYEMEZSİN; eklersen "
        "candidate'ın TAMAMI reddedilir.\n"
        "2. issue_type yalnızca şunlardan biri olabilir: "
        "verification_gap, deadline_risk, "
        "legal_basis_reference, procedural_risk, other.\n"
        "3. reason_code yalnızca şu sabit listeden biri "
        f"olabilir: {reason_code_list}.\n"
        "4. Yalnızca sana verilen fact_id / "
        "timeline_event_id / deadline_id listelerindeki "
        "ID'leri kullanabilirsin. Listede olmayan bir ID "
        "UYDURAMAZSIN.\n"
        "5. En az bir source_fact_ids / "
        "source_timeline_event_ids / source_deadline_ids "
        "değeri boş olmayan bir listede bulunmalıdır.\n"
        "6. Zaten deterministik kurallarla tespit edilmiş "
        "noktaları TEKRARLAMA; yalnızca onların "
        "kapsamadığı EK noktaları öner.\n"
        "7. Yanıtın YALNIZCA bir JSON array olmalıdır; "
        "başka hiçbir metin, açıklama veya markdown "
        "içermemelidir.\n"
        "8. Emin değilsen veya uygun bir aday yoksa boş "
        "array döndür: []\n\n"
        "ÖRNEK GEÇERLİ ÇIKTI:\n"
        "[{\"issue_type\": \"procedural_risk\", "
        "\"reason_code\": "
        "\"cross_fact_consistency_review\", "
        "\"source_fact_ids\": [\"<verilen "
        "listeden bir fact_id>\"], "
        "\"source_timeline_event_ids\": [], "
        "\"source_deadline_ids\": [], "
        "\"related_party_ids\": [], "
        "\"related_dispute_item_ids\": [], "
        "\"confidence\": 0.6}]"
    )


# ============================================================
# FACT / EVENT / DEADLINE SUMMARIES (GROUNDING CONTEXT)
# ============================================================

def summarize_facts(
    fact_index,
):

    summaries = []

    for fact_id, record in fact_index.items():

        fact = record[
            "fact"
        ]

        summaries.append(
            {
                "fact_id":
                    fact_id,

                "fact_kind":
                    fact.get(
                        "fact_kind"
                    ),

                "statement":
                    fact.get(
                        "statement"
                    ),

                "verification_state":
                    fact.get(
                        "verification_state"
                    ),
            }
        )

    return summaries


def summarize_events(
    event_index,
):

    summaries = []

    for event_id, event in event_index.items():

        summaries.append(
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

                "verification_state":
                    event.get(
                        "verification_state"
                    ),

                "deadline_relevant":
                    event.get(
                        "deadline_relevant"
                    ),
            }
        )

    return summaries


def summarize_deadlines(
    deadlines,
):

    summaries = []

    for deadline in deadlines:

        summaries.append(
            {
                "deadline_id":
                    deadline.get(
                        "deadline_id"
                    ),

                "calculation_state":
                    deadline.get(
                        "calculation_state"
                    ),

                "anchor_event_id":
                    deadline.get(
                        "anchor_event_id"
                    ),

                "anchor_verification_state":
                    deadline.get(
                        "anchor_verification_state"
                    ),
            }
        )

    return summaries


# ============================================================
# USER PROMPT
# ============================================================

def build_user_prompt(
    case_id,
    fact_summaries,
    event_summaries,
    deadline_summaries,
    existing_titles,
):

    payload = {
        "case_id":
            case_id,

        "canonical_facts":
            fact_summaries,

        "canonical_timeline_events":
            event_summaries,

        "canonical_deadlines":
            deadline_summaries,

        "already_identified_issue_titles":
            existing_titles,
    }

    return (
        "Aşağıdaki canonical veri üzerinden, deterministik "
        "kuralların ürettiği başlıklara ek olabilecek issue "
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

        raise IssueSpottingAgentError(
            "LLM cevabı JSON array değil."
        )

    return parsed


# ============================================================
# CANDIDATE SHAPE + GROUNDING VALIDATION
#
# Bu, engine'in pending'e yazmadan önce çalıştırdığı tam
# Issue Spotting Validator V1'in YERİNE GEÇMEZ; ona ek,
# ön-eleme amaçlı bir kapıdır.
#
# BURADA "title"/"description"/"notes" gibi serbest metin
# alanları TAMAMEN YASAKTIR - varlıkları tek başına
# candidate'ı reddettirir (free-text safety, bkz. modül
# başlığı).
# ============================================================

def validate_agent_candidate_shape(
    candidate,
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

    # ========================================================
    # STRUCTURAL ALLOW-LIST (ASIL GÜVENLİK MEKANİZMASI)
    # ========================================================

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
            "(free-text safety ihlali): "
            f"{sorted(forbidden_keys)}",
        )

    issue_type = candidate.get(
        "issue_type"
    )

    if issue_type not in ALLOWED_ISSUE_TYPES:

        return (
            False,
            f"geçersiz issue_type: {issue_type}",
        )

    reason_code = candidate.get(
        "reason_code"
    )

    spec = REASON_CODE_SPECS.get(
        reason_code
    )

    if spec is None:

        return (
            False,
            f"geçersiz reason_code: {reason_code}",
        )

    if (
        issue_type
        not in spec[
            "allowed_issue_types"
        ]
    ):

        return (
            False,
            f"reason_code '{reason_code}' issue_type "
            f"'{issue_type}' ile uyumlu değil",
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
#
# title/description burada, LLM'den GELMEDEN, yalnız sabit
# şablonlar (REASON_CODE_SPECS[...]["render"]) ve canonical
# veri kullanılarak üretilir.
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

        # ====================================================
        # BLOCKLIST - EK SAVUNMA KATMANI
        #
        # Render deterministik olduğu için normalde asla
        # tetiklenmemesi beklenir; yine de defense-in-depth
        # olarak kontrol edilir.
        # ====================================================

        combined = normalize_text_tr(
            f"{title} {description}"
        )

        if any(
            phrase in combined
            for phrase in FORBIDDEN_PHRASES
        ):

            render_warnings.append(
                "Render edilmiş agent candidate metni "
                "blocklist'e takıldı (beklenmeyen durum); "
                "candidate atlandı."
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
                "issue_id":
                    f"issue_{next_index:03d}",

                "issue_type":
                    candidate[
                        "issue_type"
                    ],

                "title":
                    title,

                "description":
                    description,

                "trigger_rule_id":
                    AGENT_TRIGGER_RULE_ID,

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

                # ----------------------------------------
                # LLM'den ALINMAZ; her zaman sabit.
                # ----------------------------------------

                "requires_human_review":
                    True,

                "status":
                    "candidate",

                "notes":
                    (
                        "issue_spotting_agent V1.1 "
                        "tarafından deterministik template "
                        f"'{candidate['reason_code']}' ile "
                        "render edilmiştir; LLM bu metni "
                        "doğrudan üretmemiştir."
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
    fact_index,
    event_index,
    deadlines,
    start_index,
    existing_titles=None,
    llm_client=None,
    network_allowed=False,
):

    warnings = []

    allowed_fact_ids = set(
        fact_index.keys()
    )

    allowed_event_ids = set(
        event_index.keys()
    )

    deadline_index = {
        deadline.get(
            "deadline_id"
        ): deadline
        for deadline in deadlines
        if isinstance(
            deadline,
            dict,
        )
        and deadline.get(
            "deadline_id"
        )
    }

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
    #
    # llm_client açıkça verilmediyse (yani varsayılan gerçek
    # client kullanılacaksa) network_allowed=True OLMADAN
    # AnthropicIssueLLMClient dahi OLUŞTURULMAZ. Gerçek bir
    # network denemesi bu noktadan sonra hiç yapılmaz.
    # ========================================================

    if llm_client is None:

        if not network_allowed:

            warnings.append(
                "Network access disabled "
                "(network_allowed=False, --allow-network "
                "verilmedi); Issue Spotting Agent atlandı, "
                "gerçek API çağrısı denenmedi."
            )

            return (
                [],
                warnings,
                empty_stats,
            )

        client = AnthropicIssueLLMClient()

    else:

        client = llm_client

    prompt = (
        build_user_prompt(
            case_id=
                case_id,

            fact_summaries=
                summarize_facts(
                    fact_index
                ),

            event_summaries=
                summarize_events(
                    event_index
                ),

            deadline_summaries=
                summarize_deadlines(
                    deadlines
                ),

            existing_titles=
                existing_titles
                or [],
        )
    )

    # ========================================================
    # FAIL-CLOSED: LLM ÇAĞRISI
    # ========================================================

    try:

        raw_text = client.generate(
            prompt
        )

    except Exception as error:

        warnings.append(
            "Issue Spotting Agent LLM çağrısı başarısız "
            f"oldu; agent candidate üretilmedi: {error}"
        )

        return (
            [],
            warnings,
            empty_stats,
        )

    # ========================================================
    # FAIL-CLOSED: PARSE
    # ========================================================

    try:

        raw_candidates = (
            parse_agent_response(
                raw_text
            )
        )

    except Exception as error:

        warnings.append(
            "Issue Spotting Agent cevabı parse edilemedi; "
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

    # ========================================================
    # PER-CANDIDATE VALIDATION (FAIL-CLOSED, İZOLE)
    # ========================================================

    accepted_raw = []

    rejected_count = 0

    for candidate in raw_candidates:

        (
            ok,
            reason,
        ) = (
            validate_agent_candidate_shape(
                candidate,
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
                "Issue Spotting Agent candidate reddedildi "
                f"({reason})."
            )

    # ========================================================
    # DETERMINISTIC RENDER
    # ========================================================

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
# Gerçek API key veya network erişimi GEREKTİRMEZ. Tüm
# senaryolar FakeIssueLLMClient (network'e hiç dokunmaz) ile,
# canonical case_0001 verisine karşı deterministik olarak
# çalışır.
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

    from issue_spotting_validator import (
        load_canonical_deadline_optional,
    )

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - ISSUE SPOTTING AGENT V1.1"
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
        deadlines,
        _deadline_ids,
        _deadline_path,
    ) = (
        load_canonical_deadline_optional(
            case_id
        )
    )

    assert len(
        fact_index
    ) >= 1

    print(
        "T01 Canonical context load:",
        "PASS"
    )

    real_fact_id = next(
        iter(
            fact_index.keys()
        )
    )

    real_event_id = next(
        iter(
            event_index.keys()
        )
    )

    # ========================================================
    # T02 VALID STRUCTURED SIGNAL ACCEPTED, TEXT RENDERED
    # DETERMINISTICALLY
    # ========================================================

    good_signal = {
        "issue_type":
            "procedural_risk",

        "reason_code":
            "cross_fact_consistency_review",

        "source_fact_ids": [
            real_fact_id
        ],

        "source_timeline_event_ids": [],

        "source_deadline_ids": [],

        "related_party_ids": [],

        "related_dispute_item_ids": [],

        "confidence":
            0.6,
    }

    client = FakeIssueLLMClient(
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

        fact_index=
            fact_index,

        event_index=
            event_index,

        deadlines=
            deadlines,

        start_index=
            7,

        llm_client=
            client,
    )

    assert client.call_count == 1

    assert stats[
        "accepted_count"
    ] == 1

    assert stats[
        "rejected_count"
    ] == 0

    assert finalized[
        0
    ][
        "issue_id"
    ] == "issue_007"

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

    assert finalized[
        0
    ][
        "requires_human_review"
    ] is True

    assert real_fact_id in finalized[
        0
    ][
        "title"
    ] + finalized[
        0
    ][
        "description"
    ]

    print(
        "T02 Valid structured signal accepted, "
        "text rendered deterministically:",
        "PASS"
    )

    # ========================================================
    # T03 UNGROUNDED (HALLUCINATED) FACT ID REJECTED
    # ========================================================

    ungrounded = dict(
        good_signal
    )

    ungrounded[
        "source_fact_ids"
    ] = [
        "fact_does_not_exist_in_canonical_repository"
    ]

    client = FakeIssueLLMClient(
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
        fact_index,
        event_index,
        deadlines,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 0

    assert stats[
        "rejected_count"
    ] == 1

    assert any(
        "grounding" in warning
        for warning in warnings
    )

    print(
        "T03 Ungrounded (hallucinated) ID rejected:",
        "PASS"
    )

    # ========================================================
    # T04 LLM ATTEMPTS TO SMUGGLE FREE-TEXT CONCLUSION VIA
    # A "title"/"description" FIELD -> WHOLE CANDIDATE
    # REJECTED, TEXT NEVER REACHES CANONICAL CANDIDATE
    #
    # Bu, kullanıcının açıkça istediği A) senaryosunun
    # doğrudan kanıtıdır: grounded source olsa bile, LLM'in
    # kendi yazdığı "hukuka aykırıdır" metni candidate'a
    # asla giremez.
    # ========================================================

    smuggling_attempt = dict(
        good_signal
    )

    smuggling_attempt[
        "title"
    ] = "İşlem hukuka aykırıdır"

    smuggling_attempt[
        "description"
    ] = (
        "Dava süresi geçmiştir ve mükellef davayı kazanır."
    )

    client = FakeIssueLLMClient(
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
        fact_index,
        event_index,
        deadlines,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 0

    assert stats[
        "rejected_count"
    ] == 1

    assert any(
        "free-text safety" in warning
        for warning in warnings
    )

    print(
        "T04 Free-text conclusion smuggling attempt "
        "rejected (structural, not blocklist):",
        "PASS"
    )

    # ========================================================
    # T05 INVALID ISSUE TYPE REJECTED
    # ========================================================

    bad_type = dict(
        good_signal
    )

    bad_type[
        "issue_type"
    ] = "case_outcome_prediction"

    client = FakeIssueLLMClient(
        response_text=
            json.dumps(
                [
                    bad_type
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
        fact_index,
        event_index,
        deadlines,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 0

    print(
        "T05 Invalid issue_type rejected:",
        "PASS"
    )

    # ========================================================
    # T06 INVALID / INCOMPATIBLE REASON CODE REJECTED
    # ========================================================

    bad_reason = dict(
        good_signal
    )

    bad_reason[
        "reason_code"
    ] = "not_a_real_reason_code"

    client = FakeIssueLLMClient(
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
        fact_index,
        event_index,
        deadlines,
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
    # T07 LLM CALL FAILURE -> FAIL CLOSED, NO CRASH
    # ========================================================

    client = FakeIssueLLMClient(
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
        fact_index,
        event_index,
        deadlines,
        1,
        llm_client=
            client,
    )

    assert finalized == []

    assert stats[
        "accepted_count"
    ] == 0

    assert len(
        warnings
    ) == 1

    print(
        "T07 LLM call failure fails closed:",
        "PASS"
    )

    # ========================================================
    # T08 UNPARSEABLE RESPONSE -> FAIL CLOSED, NO CRASH
    # ========================================================

    client = FakeIssueLLMClient(
        response_text=
            "bu bir JSON değildir, düz metindir."
    )

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        fact_index,
        event_index,
        deadlines,
        1,
        llm_client=
            client,
    )

    assert finalized == []

    print(
        "T08 Unparseable (malformed) response "
        "fails closed:",
        "PASS"
    )

    # ========================================================
    # T09 EMPTY ARRAY -> CLEAN NO-OP
    # ========================================================

    client = FakeIssueLLMClient(
        response_text=
            "[]"
    )

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        fact_index,
        event_index,
        deadlines,
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
    # T10 MIXED BATCH: ISOLATION
    # ========================================================

    client = FakeIssueLLMClient(
        response_text=
            json.dumps(
                [
                    good_signal,
                    ungrounded,
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
        fact_index,
        event_index,
        deadlines,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 1

    assert stats[
        "rejected_count"
    ] == 1

    print(
        "T10 Mixed batch isolation "
        "(good kept, bad rejected):",
        "PASS"
    )

    # ========================================================
    # T11 NETWORK GATE: llm_client YOK + network_allowed
    # VARSAYILAN (False) -> AnthropicIssueLLMClient HİÇ
    # OLUŞTURULMAZ, 0 candidate, tek bir gate uyarısı
    # ========================================================

    (
        finalized,
        warnings,
        stats,
    ) = generate_agent_candidates(
        case_id,
        fact_index,
        event_index,
        deadlines,
        1,
        llm_client=
            None,
    )

    assert finalized == []

    assert stats == {
        "raw_candidate_count":
            0,

        "accepted_count":
            0,

        "rejected_count":
            0,
    }

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
        "T11 Network safety gate blocks real client "
        "by default (no client constructed):",
        "PASS"
    )

    # ========================================================
    # T12 TIMELINE-EVENT-GROUNDED SIGNAL
    # ========================================================

    event_grounded = dict(
        good_signal
    )

    event_grounded[
        "issue_type"
    ] = "deadline_risk"

    event_grounded[
        "reason_code"
    ] = "temporal_consistency_review"

    event_grounded[
        "source_fact_ids"
    ] = []

    event_grounded[
        "source_timeline_event_ids"
    ] = [
        real_event_id
    ]

    client = FakeIssueLLMClient(
        response_text=
            json.dumps(
                [
                    event_grounded
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
        fact_index,
        event_index,
        deadlines,
        1,
        llm_client=
            client,
    )

    assert stats[
        "accepted_count"
    ] == 1

    assert real_event_id in finalized[
        0
    ][
        "description"
    ]

    print(
        "T12 Timeline-event-grounded signal accepted, "
        "event data rendered from canonical context:",
        "PASS"
    )

    print()

    print(
        "======================================"
    )

    print(
        " ISSUE SPOTTING AGENT V1.1: 12/12 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    run_self_test()
