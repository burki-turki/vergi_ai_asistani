# ============================================================
# VERGİ AI - EVIDENCE AGENT V1
#
# AMAÇ
# ----
#
# Evidence Discovery V1'in ürettiği deterministik ALLOWLIST
# ((issue, fact, document) üçlüleri) üzerinden, LLM'in
# YALNIZCA bu allowlist içinden supports/contradicts ilişkisi
# SEÇMESİNİ ve izin verilen suggestion türlerini ÖNERMESİNİ
# sağlamak.
#
#
# KRİTİK SINIR
# ------------
#
# Agent şunları ASLA üretemez/değiştiremez:
#
#   - issue/fact/document/source-location (yalnız allowlist'ten
#     SEÇİLİR; allowlist deterministik engine tarafından
#     üretilir)
#   - authoritative issue veya fact metni
#   - document metadata
#   - source excerpt (yalnız allowlist'teki değer deterministik
#     olarak kopyalanır)
#   - candidate/suggestion ID, count, hash, execution_state,
#     review audit
#   - confirmed/rejected/accepted_for_follow_up/dismissed
#     review state (Agent yalnız 'needs_review' üretebilir)
#   - confidence/evidence-strength/admissibility/outcome alanı
#     (evidence_candidate şemasında bu alanlar YAPISAL OLARAK
#     TANIMLI DEĞİLDİR)
#
#
# FREE-TEXT SAFETY (Row 9/10/11 deseni)
# --------------------------------------
#
# LLM'e title/description/grounded_explanation YAZDIRILMAZ.
# LLM yalnız yapılandırılmış sinyaller üretir:
#
#   candidate sinyali: source_issue_id, source_fact_id,
#   source_document_id, relationship_candidate, reason_code
#
#   suggestion sinyali: source_issue_id, suggestion_type,
#   source_fact_id, source_document_id, related_reference_ids
#
# Bunların dışında HİÇBİR alan EKLEYEMEZ; eklerse ilgili
# candidate/suggestion'ın TAMAMI reddedilir. title/description/
# grounded_explanation, kabul edilen sinyal doğrulandıktan
# SONRA tamamen deterministik template renderer'lar tarafından
# üretilir.
#
#
# NETWORK SAFETY GATE (Row 9/10/11 ile birebir aynı desen)
# -----------------------------------------------------------
#
# Gerçek Anthropic API çağrısı için İKİ açık koşul gerekir:
# llm_client açıkça VERİLMEMİŞ olmalı VE network_allowed=True
# açıkça geçilmiş olmalı.
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

from evidence_policy import (
    AGENT_SUGGESTION_DEFAULT_CONFIDENCE,
    AGENT_TRIGGER_RULE_ID,
    CANDIDATE_REASON_CODE_RENDERERS,
    SUGGESTION_GROUNDING_SPEC,
    SUGGESTION_TITLES,
    render_suggestion_description,
)


# ============================================================
# VERSION
# ============================================================

EVIDENCE_AGENT_VERSION = "1"

DEFAULT_AGENT_MODEL = "claude-sonnet-4-6"

MAX_AGENT_CANDIDATES = 40

MAX_AGENT_SUGGESTIONS = 20

ALL_FORBIDDEN_PHRASES = tuple(
    FORBIDDEN_PHRASES
)


# ============================================================
# LLM SIGNAL - İZİN VERİLEN ALANLAR
# ============================================================

ALLOWED_LLM_CANDIDATE_KEYS = {
    "source_issue_id",
    "source_fact_id",
    "source_document_id",
    "relationship_candidate",
    "reason_code",
}

ALLOWED_LLM_SUGGESTION_KEYS = {
    "source_issue_id",
    "suggestion_type",
    "source_fact_id",
    "source_document_id",
    "related_reference_ids",
}

RELATIONSHIP_VALUES = {
    "supports",
    "contradicts",
}


# ============================================================
# EXCEPTION
# ============================================================

class EvidenceAgentError(
    Exception
):
    pass


# ============================================================
# LLM CLIENT INTERFACE
# ============================================================

class AnthropicEvidenceLLMClient:

    def __init__(
        self,
        model=None,
        api_key=None,
        max_tokens=2000,
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

            raise EvidenceAgentError(
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

            raise EvidenceAgentError(
                "LLM boş cevap döndürdü."
            )

        return result


class FakeEvidenceLLMClient:

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
            else json.dumps(
                {
                    "candidates": [],
                    "suggestions": [],
                }
            )
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
# SYSTEM PROMPT
# ============================================================

def build_system_prompt():

    reason_code_list = ", ".join(
        sorted(
            CANDIDATE_REASON_CODE_RENDERERS.keys()
        )
    )

    suggestion_type_list = ", ".join(
        sorted(
            SUGGESTION_GROUNDING_SPEC.keys()
        )
    )

    return (
        "Sen bir vergi hukuku uyuşmazlık dosyasında, "
        "canonical bir issue için, sana verilen DETERMİNİSTİK "
        "ALLOWLIST içinden delil ilişkisi seçen bir yardımcı "
        "bileşensin.\n\n"
        "KESİN SINIRLAR:\n"
        "1. Hiçbir serbest metin (başlık, açıklama, "
        "gerekçe metni) ÜRETMEZSİN. Yalnız yapılandırılmış "
        "alanlar döndürürsün.\n"
        "2. Bir candidate seçimi için YALNIZ şu alanları "
        "döndürebilirsin: source_issue_id, source_fact_id, "
        "source_document_id, relationship_candidate, "
        "reason_code. Başka HİÇBİR alan (confidence, title, "
        "description, source_location, source_excerpt dahil) "
        "EKLEYEMEZSİN; eklersen candidate TAMAMEN "
        "reddedilir.\n"
        "3. (source_issue_id, source_fact_id, "
        "source_document_id) üçlüsü YALNIZ sana verilen "
        "allowlist'te bulunan bir kayıt olabilir. Yeni bir "
        "issue/fact/document İCAT EDEMEZSİN.\n"
        "4. relationship_candidate yalnız 'supports' veya "
        "'contradicts' olabilir.\n"
        f"5. reason_code yalnız şu sabit listeden biri "
        f"olabilir: {reason_code_list}.\n"
        "6. Bir suggestion için YALNIZ şu alanları "
        "döndürebilirsin: source_issue_id, suggestion_type, "
        "source_fact_id, source_document_id, "
        "related_reference_ids.\n"
        f"7. suggestion_type yalnız şu sabit listeden biri "
        f"olabilir: {suggestion_type_list}.\n"
        "8. Bir suggestion gerçek delil DEĞİLDİR; canonical "
        "metadata üretemezsin, mevcut bir candidate'ı "
        "onaylayamaz/reddedemezsin.\n"
        "9. Yanıtın YALNIZCA şu şekilde bir JSON object "
        'olmalıdır: {"candidates": [...], "suggestions": '
        '[...]}; başka hiçbir metin veya markdown '
        "içermemelidir.\n"
        "10. Emin değilsen ilgili diziyi boş bırak."
    )


# ============================================================
# USER PROMPT
# ============================================================

def summarize_allowlist(
    allowlist_by_issue,
):

    summary = []

    for issue_id, entries in allowlist_by_issue.items():

        for entry in entries:

            summary.append(
                {
                    "source_issue_id":
                        entry[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry[
                            "document_id"
                        ],

                    "issue_text":
                        entry[
                            "issue_text"
                        ],

                    "fact_text":
                        entry[
                            "fact_text"
                        ],

                    "source_excerpt":
                        entry[
                            "source_excerpt"
                        ],
                }
            )

    return summary


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


def build_user_prompt(
    case_id,
    issue_index,
    allowlist_by_issue,
):

    payload = {
        "case_id":
            case_id,

        "canonical_issues":
            summarize_issues(
                issue_index
            ),

        "allowlist":
            summarize_allowlist(
                allowlist_by_issue
            ),
    }

    return (
        "Aşağıdaki canonical issue listesi ve deterministik "
        "allowlist üzerinden delil ilişkisi seçimleri ve/veya "
        "suggestion önerileri üret. Allowlist'i olmayan "
        "issue'lar için de (allowlist boşsa) 'missing_document' "
        "veya 'fact_evidence_gap' türünde suggestion "
        "önerebilirsin. Yalnız belirtilen JSON object'i "
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
        dict,
    ):

        raise EvidenceAgentError(
            "LLM cevabı JSON object değil."
        )

    candidates = parsed.get(
        "candidates",
        [],
    )

    suggestions = parsed.get(
        "suggestions",
        [],
    )

    if not isinstance(
        candidates,
        list,
    ) or not isinstance(
        suggestions,
        list,
    ):

        raise EvidenceAgentError(
            "LLM cevabındaki 'candidates'/'suggestions' "
            "alanları list değil."
        )

    return (
        candidates,
        suggestions,
    )


# ============================================================
# CANDIDATE SHAPE + GROUNDING VALIDATION
# ============================================================

def find_allowlist_entry(
    allowlist_by_issue,
    source_issue_id,
    source_fact_id,
    source_document_id,
):

    for entry in allowlist_by_issue.get(
        source_issue_id,
        [],
    ):

        if (
            entry[
                "fact_id"
            ]
            == source_fact_id
            and entry[
                "document_id"
            ]
            == source_document_id
        ):

            return entry

    return None


def validate_agent_candidate_shape(
    candidate,
    allowlist_by_issue,
):

    if not isinstance(
        candidate,
        dict,
    ):

        return (
            False,
            None,
            None,
            "candidate dict değil",
        )

    source_issue_id = candidate.get(
        "source_issue_id"
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
            source_issue_id,
            None,
            "izin verilmeyen alan(lar) içeriyor "
            "(free-text/confidence-strength safety "
            f"ihlali): {sorted(forbidden_keys)}",
        )

    relationship_candidate = candidate.get(
        "relationship_candidate"
    )

    if relationship_candidate not in RELATIONSHIP_VALUES:

        return (
            False,
            source_issue_id,
            None,
            "geçersiz relationship_candidate: "
            f"{relationship_candidate}",
        )

    reason_code = candidate.get(
        "reason_code"
    )

    if reason_code not in CANDIDATE_REASON_CODE_RENDERERS:

        return (
            False,
            source_issue_id,
            None,
            f"geçersiz reason_code: {reason_code}",
        )

    entry = find_allowlist_entry(
        allowlist_by_issue,
        source_issue_id,
        candidate.get(
            "source_fact_id"
        ),
        candidate.get(
            "source_document_id"
        ),
    )

    if entry is None:

        return (
            False,
            source_issue_id,
            None,
            "(source_issue_id, source_fact_id, "
            "source_document_id) allowlist'te bulunamadı "
            "(grounding hatası): "
            f"{source_issue_id}/"
            f"{candidate.get('source_fact_id')}/"
            f"{candidate.get('source_document_id')}",
        )

    return (
        True,
        source_issue_id,
        entry,
        None,
    )


def validate_agent_suggestion_shape(
    suggestion,
    issue_index,
    fact_index,
    active_documents_index,
    known_reference_ids,
):

    if not isinstance(
        suggestion,
        dict,
    ):

        return (
            False,
            None,
            "suggestion dict değil",
        )

    source_issue_id = suggestion.get(
        "source_issue_id"
    )

    forbidden_keys = (
        set(
            suggestion.keys()
        )
        - ALLOWED_LLM_SUGGESTION_KEYS
    )

    if forbidden_keys:

        return (
            False,
            source_issue_id,
            "izin verilmeyen alan(lar) içeriyor "
            "(canonical metadata smuggling ihlali): "
            f"{sorted(forbidden_keys)}",
        )

    if source_issue_id not in issue_index:

        return (
            False,
            source_issue_id,
            "source_issue_id canonical issues.json içinde "
            f"bulunamadı: {source_issue_id}",
        )

    suggestion_type = suggestion.get(
        "suggestion_type"
    )

    spec = SUGGESTION_GROUNDING_SPEC.get(
        suggestion_type
    )

    if spec is None:

        return (
            False,
            source_issue_id,
            f"geçersiz suggestion_type: {suggestion_type}",
        )

    source_fact_id = suggestion.get(
        "source_fact_id"
    )

    source_document_id = suggestion.get(
        "source_document_id"
    )

    related_reference_ids = suggestion.get(
        "related_reference_ids",
        [],
    )

    if not isinstance(
        related_reference_ids,
        list,
    ):

        return (
            False,
            source_issue_id,
            "related_reference_ids list değil",
        )

    if (
        spec[
            "requires_fact"
        ]
        and not source_fact_id
    ):

        return (
            False,
            source_issue_id,
            f"suggestion_type='{suggestion_type}' için "
            "source_fact_id zorunludur",
        )

    if (
        spec[
            "requires_document"
        ]
        and not source_document_id
    ):

        return (
            False,
            source_issue_id,
            f"suggestion_type='{suggestion_type}' için "
            "source_document_id zorunludur",
        )

    if (
        spec[
            "forbids_document"
        ]
        and source_document_id
    ):

        return (
            False,
            source_issue_id,
            f"suggestion_type='{suggestion_type}' "
            "source_document_id İÇEREMEZ (tam olarak "
            "eksik olan şey bir belgedir)",
        )

    if (
        len(
            related_reference_ids
        )
        < spec[
            "min_related_references"
        ]
    ):

        return (
            False,
            source_issue_id,
            f"suggestion_type='{suggestion_type}' en az "
            f"{spec['min_related_references']} "
            "related_reference_ids gerektirir",
        )

    if (
        source_fact_id
        and source_fact_id not in fact_index
    ):

        return (
            False,
            source_issue_id,
            "source_fact_id canonical (approved) facts.json "
            f"içinde bulunamadı: {source_fact_id}",
        )

    if (
        source_document_id
        and source_document_id
        not in active_documents_index
    ):

        return (
            False,
            source_issue_id,
            "source_document_id active canonical case "
            f"document olarak bulunamadı: "
            f"{source_document_id}",
        )

    for reference_id in related_reference_ids:

        if (
            not isinstance(
                reference_id,
                str,
            )
            or reference_id
            not in known_reference_ids
        ):

            return (
                False,
                source_issue_id,
                "related_reference_ids içinde canonical "
                "olmayan/bilinmeyen bir referans "
                f"(grounding hatası): {reference_id}",
            )

    return (
        True,
        source_issue_id,
        None,
    )


# ============================================================
# RENDER + FINALIZE ACCEPTED CANDIDATES/SUGGESTIONS
# ============================================================

def render_and_finalize_candidates(
    accepted,
    start_index,
):

    finalized = []

    render_warnings = []

    next_index = start_index

    for candidate, entry in accepted:

        relationship = candidate[
            "relationship_candidate"
        ]

        reason_code = candidate[
            "reason_code"
        ]

        renderer = CANDIDATE_REASON_CODE_RENDERERS[
            reason_code
        ]

        grounded_explanation = renderer(
            entry[
                "fact_text"
            ].get(
                "statement"
            ),
            relationship,
        )

        combined = normalize_text_tr(
            grounded_explanation
        )

        if any(
            phrase in combined
            for phrase in ALL_FORBIDDEN_PHRASES
        ):

            render_warnings.append(
                "Render edilmiş evidence candidate metni "
                "blocklist'e takıldı (beklenmeyen durum); "
                "candidate atlandı."
            )

            continue

        finalized.append(
            {
                "candidate_id":
                    f"evidence_candidate_{next_index:03d}",

                "source_issue_id":
                    entry[
                        "issue_id"
                    ],

                "source_fact_id":
                    entry[
                        "fact_id"
                    ],

                "source_document_id":
                    entry[
                        "document_id"
                    ],

                "source_location":
                    entry[
                        "source_location"
                    ],

                "source_excerpt":
                    entry[
                        "source_excerpt"
                    ],

                "relationship_candidate":
                    relationship,

                "reason_code":
                    reason_code,

                "grounded_explanation":
                    grounded_explanation,

                "review_state":
                    "needs_review",

                "requires_human_review":
                    True,

                "status":
                    "candidate",

                "notes":
                    (
                        "evidence_agent V1 tarafından "
                        "deterministik allowlist'ten seçilmiş "
                        "ve deterministik template ile render "
                        "edilmiştir; LLM serbest metin "
                        "yazmamıştır."
                    ),
            }
        )

        next_index += 1

    return (
        finalized,
        render_warnings,
    )


def render_and_finalize_suggestions(
    accepted,
    start_index,
):

    finalized = []

    next_index = start_index

    for suggestion in accepted:

        suggestion_type = suggestion[
            "suggestion_type"
        ]

        source_fact_id = suggestion.get(
            "source_fact_id"
        )

        related_reference_ids = suggestion.get(
            "related_reference_ids",
            [],
        )

        description = render_suggestion_description(
            suggestion_type,
            suggestion[
                "source_issue_id"
            ],
            source_fact_id,
            related_reference_ids,
        )

        finalized.append(
            {
                "suggestion_id":
                    f"evidence_suggestion_{next_index:03d}",

                "source_issue_id":
                    suggestion[
                        "source_issue_id"
                    ],

                "suggestion_type":
                    suggestion_type,

                "source_fact_id":
                    source_fact_id,

                "source_document_id":
                    suggestion.get(
                        "source_document_id"
                    ),

                "related_reference_ids":
                    related_reference_ids,

                "reason_code":
                    f"agent_suggested_{suggestion_type}",

                "title":
                    SUGGESTION_TITLES[
                        suggestion_type
                    ],

                "description":
                    description,

                "trigger_rule_id":
                    AGENT_TRIGGER_RULE_ID,

                "confidence":
                    AGENT_SUGGESTION_DEFAULT_CONFIDENCE,

                "suggestion_review_state":
                    "needs_review",

                "requires_human_review":
                    True,

                "status":
                    "candidate",

                "notes":
                    (
                        "evidence_agent V1 tarafından "
                        "deterministik template ile render "
                        "edilmiştir; gerçek delil DEĞİLDİR."
                    ),
            }
        )

        next_index += 1

    return finalized


# ============================================================
# ORCHESTRATOR
# ============================================================

def generate_agent_output(
    case_id,
    issue_index,
    allowlist_by_issue,
    fact_index,
    active_documents_index,
    candidate_start_index=1,
    suggestion_start_index=1,
    llm_client=None,
    network_allowed=False,
):

    warnings = []

    empty_result = {
        "candidates": [],
        "suggestions": [],
        "warnings": warnings,
        "call_failed": False,
        "unparseable": False,
        "per_issue": {},
    }

    if llm_client is None:

        if not network_allowed:

            warnings.append(
                "Network access disabled "
                "(network_allowed=False, --allow-network "
                "verilmedi); Evidence Agent atlandı, gerçek "
                "API çağrısı denenmedi."
            )

            return empty_result

        client = AnthropicEvidenceLLMClient()

    else:

        client = llm_client

    prompt = build_user_prompt(
        case_id,
        issue_index,
        allowlist_by_issue,
    )

    try:

        raw_text = client.generate(
            prompt
        )

    except Exception as error:

        warnings.append(
            "Evidence Agent LLM çağrısı başarısız oldu: "
            f"{error}"
        )

        empty_result[
            "call_failed"
        ] = True

        return empty_result

    try:

        (
            raw_candidates,
            raw_suggestions,
        ) = parse_agent_response(
            raw_text
        )

    except Exception as error:

        warnings.append(
            "Evidence Agent cevabı parse edilemedi: "
            f"{error}"
        )

        empty_result[
            "unparseable"
        ] = True

        return empty_result

    raw_candidates = raw_candidates[
        :MAX_AGENT_CANDIDATES
    ]

    raw_suggestions = raw_suggestions[
        :MAX_AGENT_SUGGESTIONS
    ]

    per_issue = {}

    def ensure_issue_bucket(
        issue_id,
    ):

        if issue_id is None:

            return None

        return per_issue.setdefault(
            issue_id,
            {
                "raw_candidate_count":
                    0,

                "rejected_candidate_count":
                    0,

                "raw_suggestion_count":
                    0,

                "rejected_suggestion_count":
                    0,
            },
        )

    accepted_candidates = []

    seen_candidate_keys = set()

    for candidate in raw_candidates:

        source_issue_id = (
            candidate.get(
                "source_issue_id"
            )
            if isinstance(
                candidate,
                dict,
            )
            else None
        )

        bucket = ensure_issue_bucket(
            source_issue_id
        )

        if bucket is not None:

            bucket[
                "raw_candidate_count"
            ] += 1

        (
            ok,
            resolved_issue_id,
            entry,
            reason,
        ) = validate_agent_candidate_shape(
            candidate,
            allowlist_by_issue,
        )

        if not ok:

            warnings.append(
                f"Evidence candidate reddedildi ({reason})."
            )

            target_bucket = (
                ensure_issue_bucket(
                    resolved_issue_id
                )
                or bucket
            )

            if target_bucket is not None:

                target_bucket[
                    "rejected_candidate_count"
                ] += 1

            continue

        dedup_key = (
            entry[
                "issue_id"
            ],

            entry[
                "fact_id"
            ],

            entry[
                "document_id"
            ],

            candidate[
                "relationship_candidate"
            ],
        )

        if dedup_key in seen_candidate_keys:

            warnings.append(
                "Duplicate evidence candidate atlandı "
                f"(dedup): {dedup_key}"
            )

            bucket[
                "rejected_candidate_count"
            ] += 1

            continue

        seen_candidate_keys.add(
            dedup_key
        )

        accepted_candidates.append(
            (
                candidate,
                entry,
            )
        )

    (
        finalized_candidates,
        render_warnings,
    ) = render_and_finalize_candidates(
        accepted_candidates,
        candidate_start_index,
    )

    warnings.extend(
        render_warnings
    )

    known_reference_ids = (
        set(
            fact_index.keys()
        )
        | set(
            active_documents_index.keys()
        )
        | {
            candidate[
                "candidate_id"
            ]
            for candidate
            in finalized_candidates
        }
    )

    accepted_suggestions = []

    for suggestion in raw_suggestions:

        source_issue_id = (
            suggestion.get(
                "source_issue_id"
            )
            if isinstance(
                suggestion,
                dict,
            )
            else None
        )

        bucket = ensure_issue_bucket(
            source_issue_id
        )

        if bucket is not None:

            bucket[
                "raw_suggestion_count"
            ] += 1

        (
            ok,
            resolved_issue_id,
            reason,
        ) = validate_agent_suggestion_shape(
            suggestion,
            issue_index,
            fact_index,
            active_documents_index,
            known_reference_ids,
        )

        if not ok:

            warnings.append(
                f"Evidence suggestion reddedildi ({reason})."
            )

            target_bucket = (
                ensure_issue_bucket(
                    resolved_issue_id
                )
                or bucket
            )

            if target_bucket is not None:

                target_bucket[
                    "rejected_suggestion_count"
                ] += 1

            continue

        accepted_suggestions.append(
            suggestion
        )

    finalized_suggestions = (
        render_and_finalize_suggestions(
            accepted_suggestions,
            suggestion_start_index,
        )
    )

    return {
        "candidates":
            finalized_candidates,

        "suggestions":
            finalized_suggestions,

        "warnings":
            warnings,

        "call_failed":
            False,

        "unparseable":
            False,

        "per_issue":
            per_issue,
    }


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(
    case_id="case_0001",
):

    from legal_research_validator import (
        load_canonical_issues,
    )

    from timeline_validator import (
        load_canonical_fact_index,
    )

    from evidence_policy import (
        load_active_case_documents_index,
    )

    from evidence_discovery import (
        build_allowlist_for_issues,
    )

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - EVIDENCE AGENT V1"
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

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = fact_context[
        "facts"
    ]

    active_documents_index = (
        load_active_case_documents_index(
            case_id
        )
    )

    (
        allowlist_by_issue,
        _warnings,
    ) = build_allowlist_for_issues(
        issue_context[
            "issues"
        ],

        fact_index,

        active_documents_index,
    )

    non_empty_issue_ids = [
        issue_id
        for issue_id, entries
        in allowlist_by_issue.items()
        if entries
    ]

    assert len(
        non_empty_issue_ids
    ) >= 1

    entry_a = allowlist_by_issue[
        non_empty_issue_ids[
            0
        ]
    ][
        0
    ]

    print(
        "T01 Canonical issue/fact/document context + "
        "allowlist load:",
        "PASS"
    )

    def run(
        candidates=None,
        suggestions=None,
        raise_error=None,
        response_override=None,
    ):

        if response_override is not None:

            response_text = response_override

        else:

            response_text = json.dumps(
                {
                    "candidates":
                        candidates
                        or [],

                    "suggestions":
                        suggestions
                        or [],
                },
                ensure_ascii=False,
            )

        client = FakeEvidenceLLMClient(
            response_text=
                response_text,

            raise_error=
                raise_error,
        )

        result = generate_agent_output(
            case_id=
                case_id,

            issue_index=
                issue_index,

            allowlist_by_issue=
                allowlist_by_issue,

            fact_index=
                fact_index,

            active_documents_index=
                active_documents_index,

            candidate_start_index=
                1,

            suggestion_start_index=
                1,

            llm_client=
                client,

            network_allowed=
                False,
        )

        return (
            result,
            client,
        )

    good_candidate = {
        "source_issue_id":
            entry_a[
                "issue_id"
            ],

        "source_fact_id":
            entry_a[
                "fact_id"
            ],

        "source_document_id":
            entry_a[
                "document_id"
            ],

        "relationship_candidate":
            "supports",

        "reason_code":
            "explicit_textual_match",
    }

    # ========================================================
    # T02 VALID CANDIDATE ACCEPTED (SUPPORTS)
    # ========================================================

    result, client = run(
        candidates=[
            good_candidate
        ],
    )

    assert client.call_count == 1

    assert len(
        result[
            "candidates"
        ]
    ) == 1

    assert result[
        "candidates"
    ][
        0
    ][
        "relationship_candidate"
    ] == "supports"

    assert "confidence" not in result[
        "candidates"
    ][
        0
    ]

    assert result[
        "candidates"
    ][
        0
    ][
        "review_state"
    ] == "needs_review"

    print(
        "T02 Valid candidate accepted (supports, no "
        "confidence field, review_state=needs_review):",
        "PASS"
    )

    # ========================================================
    # T03 VALID CANDIDATE ACCEPTED (CONTRADICTS)
    # ========================================================

    contradicts_candidate = dict(
        good_candidate
    )

    contradicts_candidate[
        "relationship_candidate"
    ] = "contradicts"

    result, _client = run(
        candidates=[
            contradicts_candidate
        ],
    )

    assert len(
        result[
            "candidates"
        ]
    ) == 1

    assert result[
        "candidates"
    ][
        0
    ][
        "relationship_candidate"
    ] == "contradicts"

    print(
        "T03 Valid candidate accepted (contradicts):",
        "PASS"
    )

    # ========================================================
    # T04 UNGROUNDED FACT/DOCUMENT REJECTED
    # ========================================================

    ungrounded = dict(
        good_candidate
    )

    ungrounded[
        "source_fact_id"
    ] = "fact_ghost_does_not_exist"

    result, _client = run(
        candidates=[
            ungrounded
        ],
    )

    assert result[
        "candidates"
    ] == []

    assert any(
        "grounding" in warning
        for warning in result[
            "warnings"
        ]
    )

    print(
        "T04 Ungrounded (issue,fact,document) triple "
        "rejected:",
        "PASS"
    )

    # ========================================================
    # T05 CONFIDENCE SMUGGLING REJECTED
    # ========================================================

    smuggling = dict(
        good_candidate
    )

    smuggling[
        "confidence"
    ] = 0.9

    result, _client = run(
        candidates=[
            smuggling
        ],
    )

    assert result[
        "candidates"
    ] == []

    assert any(
        "safety" in warning
        for warning in result[
            "warnings"
        ]
    )

    print(
        "T05 Confidence field smuggling rejected "
        "(structural):",
        "PASS"
    )

    # ========================================================
    # T06 INVALID RELATIONSHIP_CANDIDATE REJECTED
    # ========================================================

    bad_relationship = dict(
        good_candidate
    )

    bad_relationship[
        "relationship_candidate"
    ] = "is_related_to"

    result, _client = run(
        candidates=[
            bad_relationship
        ],
    )

    assert result[
        "candidates"
    ] == []

    print(
        "T06 Invalid relationship_candidate rejected:",
        "PASS"
    )

    # ========================================================
    # T07 INVALID REASON_CODE REJECTED
    # ========================================================

    bad_reason = dict(
        good_candidate
    )

    bad_reason[
        "reason_code"
    ] = "not_a_real_reason_code"

    result, _client = run(
        candidates=[
            bad_reason
        ],
    )

    assert result[
        "candidates"
    ] == []

    print(
        "T07 Invalid reason_code rejected:",
        "PASS"
    )

    # ========================================================
    # T08 DEDUP WITHIN SINGLE AGENT CALL
    # ========================================================

    result, _client = run(
        candidates=[
            good_candidate,
            dict(
                good_candidate
            ),
        ],
    )

    assert len(
        result[
            "candidates"
        ]
    ) == 1

    print(
        "T08 Duplicate candidate within same call "
        "deduplicated:",
        "PASS"
    )

    # ========================================================
    # T09-T14 SUGGESTION CONDITIONAL GROUNDING (VALID CASES)
    # ========================================================

    other_document_id = next(
        iter(
            active_documents_index.keys()
        )
    )

    valid_suggestions = {
        "missing_document": {
            "source_issue_id":
                entry_a[
                    "issue_id"
                ],

            "suggestion_type":
                "missing_document",

            "source_fact_id":
                None,

            "source_document_id":
                None,

            "related_reference_ids": [],
        },

        "fact_evidence_gap": {
            "source_issue_id":
                entry_a[
                    "issue_id"
                ],

            "suggestion_type":
                "fact_evidence_gap",

            "source_fact_id":
                entry_a[
                    "fact_id"
                ],

            "source_document_id":
                None,

            "related_reference_ids": [],
        },

        "fact_review_needed": {
            "source_issue_id":
                entry_a[
                    "issue_id"
                ],

            "suggestion_type":
                "fact_review_needed",

            "source_fact_id":
                entry_a[
                    "fact_id"
                ],

            "source_document_id":
                None,

            "related_reference_ids": [],
        },

        "missing_source_location": {
            "source_issue_id":
                entry_a[
                    "issue_id"
                ],

            "suggestion_type":
                "missing_source_location",

            "source_fact_id":
                entry_a[
                    "fact_id"
                ],

            "source_document_id":
                entry_a[
                    "document_id"
                ],

            "related_reference_ids": [],
        },

        "unresolved_conflict": {
            "source_issue_id":
                entry_a[
                    "issue_id"
                ],

            "suggestion_type":
                "unresolved_conflict",

            "source_fact_id":
                None,

            "source_document_id":
                None,

            "related_reference_ids": [
                entry_a[
                    "fact_id"
                ],

                other_document_id,
            ],
        },

        "additional_verification": {
            "source_issue_id":
                entry_a[
                    "issue_id"
                ],

            "suggestion_type":
                "additional_verification",

            "source_fact_id":
                None,

            "source_document_id":
                None,

            "related_reference_ids": [
                entry_a[
                    "fact_id"
                ],
            ],
        },
    }

    for suggestion_type, payload in valid_suggestions.items():

        result, _client = run(
            suggestions=[
                payload
            ],
        )

        assert len(
            result[
                "suggestions"
            ]
        ) == 1, (
            f"suggestion_type={suggestion_type} kabul "
            f"edilmedi: {result['warnings']}"
        )

        assert result[
            "suggestions"
        ][
            0
        ][
            "suggestion_review_state"
        ] == "needs_review"

    print(
        "T09 All 6 suggestion_type conditional-grounding "
        "valid cases accepted:",
        "PASS"
    )

    # ========================================================
    # T10 SUGGESTION MISSING REQUIRED FACT REJECTED
    # ========================================================

    invalid = dict(
        valid_suggestions[
            "fact_evidence_gap"
        ]
    )

    invalid[
        "source_fact_id"
    ] = None

    result, _client = run(
        suggestions=[
            invalid
        ],
    )

    assert result[
        "suggestions"
    ] == []

    print(
        "T10 Suggestion missing required source_fact_id "
        "rejected (fact_evidence_gap):",
        "PASS"
    )

    # ========================================================
    # T11 SUGGESTION FORBIDDEN DOCUMENT REJECTED
    # (missing_document with a document attached)
    # ========================================================

    invalid = dict(
        valid_suggestions[
            "missing_document"
        ]
    )

    invalid[
        "source_document_id"
    ] = entry_a[
        "document_id"
    ]

    result, _client = run(
        suggestions=[
            invalid
        ],
    )

    assert result[
        "suggestions"
    ] == []

    print(
        "T11 Suggestion forbidden source_document_id "
        "rejected (missing_document):",
        "PASS"
    )

    # ========================================================
    # T12 SUGGESTION INSUFFICIENT RELATED REFERENCES REJECTED
    # ========================================================

    invalid = dict(
        valid_suggestions[
            "unresolved_conflict"
        ]
    )

    invalid[
        "related_reference_ids"
    ] = [
        entry_a[
            "fact_id"
        ]
    ]

    result, _client = run(
        suggestions=[
            invalid
        ],
    )

    assert result[
        "suggestions"
    ] == []

    print(
        "T12 Suggestion with insufficient "
        "related_reference_ids rejected "
        "(unresolved_conflict needs >= 2):",
        "PASS"
    )

    # ========================================================
    # T13 INVALID SUGGESTION_TYPE REJECTED
    # ========================================================

    invalid = dict(
        valid_suggestions[
            "additional_verification"
        ]
    )

    invalid[
        "suggestion_type"
    ] = "not_a_real_type"

    result, _client = run(
        suggestions=[
            invalid
        ],
    )

    assert result[
        "suggestions"
    ] == []

    print(
        "T13 Invalid suggestion_type rejected:",
        "PASS"
    )

    # ========================================================
    # T14 SUGGESTION METADATA SMUGGLING REJECTED
    # ========================================================

    invalid = dict(
        valid_suggestions[
            "additional_verification"
        ]
    )

    invalid[
        "reason_code"
    ] = "agent_invented_reason"

    result, _client = run(
        suggestions=[
            invalid
        ],
    )

    assert result[
        "suggestions"
    ] == []

    print(
        "T14 Suggestion with unexpected field "
        "(reason_code not agent-settable) rejected:",
        "PASS"
    )

    # ========================================================
    # T15 LLM CALL FAILURE -> FAIL CLOSED
    # ========================================================

    result, _client = run(
        raise_error=
            RuntimeError(
                "simulated network failure"
            ),
    )

    assert result[
        "candidates"
    ] == []

    assert result[
        "suggestions"
    ] == []

    assert result[
        "call_failed"
    ] is True

    print(
        "T15 LLM call failure fails closed "
        "(call_failed=True):",
        "PASS"
    )

    # ========================================================
    # T16 UNPARSEABLE RESPONSE -> FAIL CLOSED
    # ========================================================

    result, _client = run(
        response_override=
            "bu bir JSON değildir.",
    )

    assert result[
        "candidates"
    ] == []

    assert result[
        "unparseable"
    ] is True

    print(
        "T16 Unparseable response fails closed "
        "(unparseable=True):",
        "PASS"
    )

    # ========================================================
    # T17 EMPTY ARRAYS -> CLEAN NO-OP
    # ========================================================

    result, _client = run()

    assert result[
        "candidates"
    ] == []

    assert result[
        "suggestions"
    ] == []

    assert result[
        "warnings"
    ] == []

    print(
        "T17 Empty candidates/suggestions clean no-op:",
        "PASS"
    )

    # ========================================================
    # T18 NETWORK GATE: llm_client YOK + network_allowed
    # VARSAYILAN (False) -> gerçek client HİÇ OLUŞTURULMAZ
    # ========================================================

    result = generate_agent_output(
        case_id=
            case_id,

        issue_index=
            issue_index,

        allowlist_by_issue=
            allowlist_by_issue,

        fact_index=
            fact_index,

        active_documents_index=
            active_documents_index,

        llm_client=
            None,

        network_allowed=
            False,
    )

    assert result[
        "candidates"
    ] == []

    assert result[
        "suggestions"
    ] == []

    assert len(
        result[
            "warnings"
        ]
    ) == 1

    assert (
        "Network access disabled"
        in result[
            "warnings"
        ][
            0
        ]
    )

    print(
        "T18 Network safety gate blocks real client by "
        "default:",
        "PASS"
    )

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE AGENT V1: 18/18 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":

    run_self_test()
