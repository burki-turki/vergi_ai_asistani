# ============================================================
# VERGİ AI - RAG V3.5
#
# DOCUMENT TEMPORAL
# + DOCUMENT VERSION
# + PROVISION REPOSITORY
# + PROVISION VERSION POLICY
# + PROVISION POLICY
# + DETERMINISTIC LEGAL SAFETY
#
#
# V3.5 YENİ:
#
# Provision Repository artık birden fazla provision version
# döndürebilir.
#
# RAG artık:
#
# Provision Repository
#       ↓
# Provision Version Policy
#       ↓
# Provision Policy
#
# zincirini kullanır.
#
#
# KRİTİK:
#
# Tek provision version bulunması
#     !=
# hukuken valid olduğunun doğrulanması
#
#
# Provision Version Policy sonuçları:
#
# neutral
# selected
# unknown
# version_conflict
# version_unresolved
# no_valid_version
# mixed_provision_candidates
#
#
# WRONG VERSION > NO VERSION
# ============================================================


import json
import re

from anthropic import Anthropic


# ============================================================
# IMPORT COMPATIBILITY
# ============================================================

try:
    from .query_parser import parse_query_metadata
    from .retriever import retrieve_detailed
    from .temporal_policy import get_temporal_mode

    from .provision_repository import (
        resolve_provisions,
    )

    from .provision_version_policy import (
        select_provision_versions,
    )

    from .provision_policy import (
        evaluate_provision_policy,
    )

except ImportError:
    from query_parser import parse_query_metadata
    from retriever import retrieve_detailed
    from temporal_policy import get_temporal_mode

    from provision_repository import (
        resolve_provisions,
    )

    from provision_version_policy import (
        select_provision_versions,
    )

    from provision_policy import (
        evaluate_provision_policy,
    )


# ============================================================
# CONFIG
# ============================================================

RAG_VERSION = "3.5"

CLAUDE_MODEL = "claude-sonnet-4-6"

RETRIEVAL_TOP_K = 8
RERANK_TOP_K = 3

RERANK_DEBUG = False

client = Anthropic()


# ============================================================
# NORMALIZE
# ============================================================

def normalize(value):
    if value is None:
        return None

    value = str(
        value
    ).strip().lower()

    if not value:
        return None

    return value


# ============================================================
# HISTORY
# ============================================================

def format_history(
    history,
    max_messages=8,
):
    if not history:
        return ""

    selected = history[
        -max_messages:
    ]

    lines = []

    for message in selected:
        role = message.get(
            "role"
        )

        content = message.get(
            "content",
            "",
        )

        if role == "user":
            prefix = "Kullanıcı"

        elif role == "assistant":
            prefix = "Asistan"

        else:
            prefix = str(
                role
            )

        lines.append(
            f"{prefix}: {content}"
        )

    return "\n".join(
        lines
    )


# ============================================================
# QUERY REWRITE
# ============================================================

def rewrite_query(
    question,
    history=None,
):
    if not history:
        return question

    history_text = (
        format_history(
            history
        )
    )

    prompt = f"""
Sen bir Türk vergi hukuku bilgi erişim sisteminin
arama sorgusu dönüştürme bileşenisin.

Görevin:

Kullanıcının son sorusunu konuşma geçmişini dikkate alarak
tek başına anlaşılabilir bir hukuki arama sorgusuna dönüştürmek.

KURALLAR:

- Yeni hukuki bilgi üretme.
- Varsayım yapma.
- Kanun numarası uydurma.
- Madde numarası uydurma.
- Fıkra numarası uydurma.
- Bent numarası uydurma.
- Belge numarası uydurma.
- Tarih uydurma.
- Yürürlük tarihi uydurma.
- Geçerlilik dönemi uydurma.
- Version numarası uydurma.

- Önceki asistan cevabını hukuki kaynak kabul etme.

- Önceki kullanıcı mesajlarında açıkça verilmiş
  kanun/madde/fıkra/bent referanslarını takip sorusuna
  taşıyabilirsin.

- Son sorudaki temporal ifadeleri koru.

Örnek:

bugün
şu anda
halen
güncel
yürürlükte
2020 yılında
01.06.2021 tarihinde

- Kullanıcının sorusu zaten bağımsız anlaşılabiliyorsa
  aynen koru.

- Sadece arama sorgusunu yaz.
- Açıklama ekleme.

Konuşma:

{history_text}

Son kullanıcı sorusu:

{question}

Arama sorgusu:
"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    rewritten = (
        response.content[0]
        .text
        .strip()
    )

    return (
        rewritten
        or question
    )


# ============================================================
# EXPLICIT REFERENCE
# ============================================================

def has_explicit_reference(
    metadata,
):
    return any(
        [
            metadata.get(
                "kanun_no"
            ),
            metadata.get(
                "madde"
            ),
            metadata.get(
                "fikra"
            ),
            metadata.get(
                "bent"
            ),
        ]
    )


# ============================================================
# TEMPORAL CONTEXT
# ============================================================

def build_temporal_context(
    search_query,
):
    detected = get_temporal_mode(
        search_query
    )

    mode = detected.get(
        "mode",
        "neutral",
    )

    query_date = detected.get(
        "query_date"
    )

    if (
        query_date is not None
        and hasattr(
            query_date,
            "isoformat",
        )
    ):
        query_date_string = (
            query_date.isoformat()
        )

    elif query_date is not None:
        query_date_string = str(
            query_date
        )

    else:
        query_date_string = None

    return {
        "mode":
            mode,

        "query_date":
            query_date,

        "query_date_string":
            query_date_string,
    }


# ============================================================
# QUESTION SCOPE
# ============================================================

def classify_provision_question_scope(
    question,
):
    text = (
        normalize(
            question
        )
        or ""
    )

    formal_patterns = [
        "yürürlükte mi",
        "yürürlükten kaldır",
        "mülga mı",
        "mülga olmuş",
        "mülga edildi",
        "mülga edilmiş",
        "geçerli miydi",
        "geçerli mi",
        "formal olarak",
        "hukuken yürürlük",
    ]

    applicability_patterns = [
        "yararlanabilir",
        "yararlanabilir miyim",
        "yararlanılabilir",
        "yararlanmak",
        "yararlanma",
        "başvuru yap",
        "başvurabilir",
        "başvurulabilir",
        "başvuru süresi",
        "beyan edebilir",
        "beyan yapılabilir",
        "beyan süresi",
        "kullanabilir",
        "kullanılabilir",
        "uygulanabilir mi",
        "uygulanabilir miydi",
        "uygulama süresi",
        "başvuru açık",
        "süre açık",
    ]

    has_formal = any(
        pattern in text
        for pattern
        in formal_patterns
    )

    has_applicability = any(
        pattern in text
        for pattern
        in applicability_patterns
    )

    if (
        has_formal
        and has_applicability
    ):
        return "both"

    if has_formal:
        return "formal_status"

    if has_applicability:
        return "applicability"

    return "neutral"


# ============================================================
# DOCUMENT VERSION SUMMARY
# ============================================================

def build_version_summary(
    version_selection,
):
    if not isinstance(
        version_selection,
        dict,
    ):
        return {
            "selection_status":
                None,

            "failure_reason":
                None,

            "has_conflict":
                False,

            "groups":
                [],
        }

    groups = []

    for group in version_selection.get(
        "groups",
        [],
    ):
        groups.append(
            {
                "group_key":
                    group.get(
                        "group_key"
                    ),

                "status":
                    group.get(
                        "status"
                    ),

                "selected_document_ids":
                    group.get(
                        "selected_document_ids",
                        [],
                    ),

                "valid_document_ids":
                    group.get(
                        "valid_document_ids",
                        [],
                    ),

                "unknown_document_ids":
                    group.get(
                        "unknown_document_ids",
                        [],
                    ),

                "invalid_document_ids":
                    group.get(
                        "invalid_document_ids",
                        [],
                    ),

                "neutral_document_ids":
                    group.get(
                        "neutral_document_ids",
                        [],
                    ),

                "message":
                    group.get(
                        "message"
                    ),
            }
        )

    return {
        "selection_status":
            version_selection.get(
                "selection_status"
            ),

        "failure_reason":
            version_selection.get(
                "failure_reason"
            ),

        "has_conflict":
            version_selection.get(
                "has_conflict",
                False,
            ),

        "groups":
            groups,
    }


# ============================================================
# NEUTRAL REFERENCE EXISTS
# ============================================================

def neutral_reference_exists(
    search_query,
    metadata,
):
    if not has_explicit_reference(
        metadata
    ):
        return False

    detailed = retrieve_detailed(
        query=
            search_query,

        top_k=
            1,

        kanun_no=
            metadata.get(
                "kanun_no"
            ),

        madde=
            metadata.get(
                "madde"
            ),

        fikra=
            metadata.get(
                "fikra"
            ),

        bent=
            metadata.get(
                "bent"
            ),

        temporal_mode=
            "neutral",
    )

    return bool(
        detailed.get(
            "results",
            [],
        )
    )


# ============================================================
# DOCUMENT FAILURE RESOLUTION
# ============================================================

def resolve_failure_reason(
    search_query,
    metadata,
    temporal_context,
    retriever_failure_reason,
    version_selection,
):
    temporal_mode = (
        temporal_context.get(
            "mode"
        )
    )

    explicit_reference = (
        has_explicit_reference(
            metadata
        )
    )

    if isinstance(
        version_selection,
        dict,
    ):
        version_status = (
            version_selection.get(
                "selection_status"
            )
        )

        version_failure = (
            version_selection.get(
                "failure_reason"
            )
        )

    else:
        version_status = None
        version_failure = None

    if (
        version_failure
        == "version_conflict"
        or version_status
        == "version_conflict"
    ):
        return "version_conflict"

    if (
        version_failure
        == "version_unresolved"
        or version_status
        == "version_unresolved"
    ):
        return "version_unresolved"

    if (
        version_failure
        == "no_valid_version"
        or version_status
        == "no_valid_version"
    ):
        return "no_valid_version"

    if (
        explicit_reference
        and retriever_failure_reason
        == "metadata_not_found"
    ):
        return (
            "explicit_reference_not_found"
        )

    if (
        explicit_reference
        and temporal_mode
        != "neutral"
        and retriever_failure_reason
        in {
            "temporal_no_candidate",
            "no_candidate",
            "version_no_candidate",
        }
    ):
        if neutral_reference_exists(
            search_query=
                search_query,

            metadata=
                metadata,
        ):
            return (
                "temporal_mismatch"
            )

        return (
            "explicit_reference_not_found"
        )

    if (
        explicit_reference
        and retriever_failure_reason
        is not None
    ):
        return (
            "explicit_reference_not_found"
        )

    if (
        temporal_mode
        != "neutral"
        and retriever_failure_reason
        is not None
    ):
        return (
            "temporal_no_source"
        )

    return "no_source"


# ============================================================
# RETRIEVE CANDIDATES
# ============================================================

def retrieve_candidates(
    search_query,
    metadata,
    temporal_context,
):
    detailed = retrieve_detailed(
        query=
            search_query,

        top_k=
            RETRIEVAL_TOP_K,

        kanun_no=
            metadata.get(
                "kanun_no"
            ),

        madde=
            metadata.get(
                "madde"
            ),

        fikra=
            metadata.get(
                "fikra"
            ),

        bent=
            metadata.get(
                "bent"
            ),

        temporal_mode=
            temporal_context.get(
                "mode"
            ),

        query_date=
            temporal_context.get(
                "query_date"
            ),

        strict_temporal=
            False,
    )

    candidates = detailed.get(
        "results",
        [],
    )

    version_selection = (
        detailed.get(
            "version_selection",
            {},
        )
    )

    retriever_failure_reason = (
        detailed.get(
            "retrieval_failure_reason"
        )
    )

    if candidates:
        return {
            "candidates":
                candidates,

            "failure_reason":
                None,

            "retriever_failure_reason":
                None,

            "version_selection":
                version_selection,
        }

    failure_reason = (
        resolve_failure_reason(
            search_query=
                search_query,

            metadata=
                metadata,

            temporal_context=
                temporal_context,

            retriever_failure_reason=
                retriever_failure_reason,

            version_selection=
                version_selection,
        )
    )

    return {
        "candidates":
            [],

        "failure_reason":
            failure_reason,

        "retriever_failure_reason":
            retriever_failure_reason,

        "version_selection":
            version_selection,
    }


# ============================================================
# RERANK INPUT
# ============================================================

def build_rerank_candidates(
    candidates,
):
    blocks = []

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):
        block = f"""
ADAY {index}

Document ID:
{candidate.get("document_id")}

Belge Türü:
{candidate.get("belge_turu")}

Başlık:
{candidate.get("title")}

Kanun:
{candidate.get("kanun_no")}

Madde:
{candidate.get("madde")}

Fıkra:
{candidate.get("fikra")}

Bent:
{candidate.get("bent")}

Version:
{candidate.get("version")}

Version Selection:
{candidate.get("version_selection_status")}

Temporal Result:
{candidate.get("temporal_result")}

Authority:
{candidate.get("authority_level")}

Final Score:
{candidate.get("final_score")}

Metin:
{candidate.get("text")}
"""

        blocks.append(
            block.strip()
        )

    return "\n\n".join(
        blocks
    )


# ============================================================
# RERANK JSON
# ============================================================

def parse_rerank_json(
    raw_text,
):
    if raw_text is None:
        return None

    text = str(
        raw_text
    ).strip()

    if not text:
        return None

    try:
        parsed = json.loads(
            text
        )

        if isinstance(
            parsed,
            dict,
        ):
            return parsed

    except json.JSONDecodeError:
        pass

    fence_pattern = re.compile(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    fence_match = (
        fence_pattern.search(
            text
        )
    )

    if fence_match:
        candidate = (
            fence_match.group(
                1
            ).strip()
        )

        try:
            parsed = json.loads(
                candidate
            )

            if isinstance(
                parsed,
                dict,
            ):
                return parsed

        except json.JSONDecodeError:
            pass

    first_brace = text.find(
        "{"
    )

    last_brace = text.rfind(
        "}"
    )

    if (
        first_brace != -1
        and last_brace != -1
        and last_brace
        > first_brace
    ):
        candidate = text[
            first_brace:
            last_brace + 1
        ]

        try:
            parsed = json.loads(
                candidate
            )

            if isinstance(
                parsed,
                dict,
            ):
                return parsed

        except json.JSONDecodeError:
            pass

    return None


# ============================================================
# RANKING VALIDATION
# ============================================================

def extract_valid_ranking(
    parsed,
    candidate_count,
    top_k,
):
    if not isinstance(
        parsed,
        dict,
    ):
        return []

    ranking = parsed.get(
        "ranking"
    )

    if not isinstance(
        ranking,
        list,
    ):
        return []

    valid_positions = []

    seen = set()

    for value in ranking:
        if isinstance(
            value,
            bool,
        ):
            continue

        if not isinstance(
            value,
            int,
        ):
            continue

        if not (
            1
            <= value
            <= candidate_count
        ):
            continue

        if value in seen:
            continue

        seen.add(
            value
        )

        valid_positions.append(
            value
        )

        if len(
            valid_positions
        ) >= top_k:
            break

    return valid_positions


# ============================================================
# RERANK
# ============================================================

def rerank_candidates(
    question,
    candidates,
    top_k=RERANK_TOP_K,
):
    if not candidates:
        return []

    if len(
        candidates
    ) <= top_k:
        return candidates

    candidate_text = (
        build_rerank_candidates(
            candidates
        )
    )

    prompt = f"""
Sen bir Türk vergi hukuku RAG sisteminin
reranking bileşenisin.

Görevin yalnızca en ilgili kaynak chunklarını seçmektir.

KURALLAR:

1. Kanun/madde/fıkra/bent uyumu önceliklidir.
2. Version Policy tarafından elenmiş sürümü geri getirme.
3. Temporal result=valid bilgisini provision applicability
   kanıtı gibi yorumlama.
4. Kaynakta olmayan bilgi üretme.
5. Yalnızca geçerli JSON object döndür.
6. Markdown code fence kullanma.
7. Açıklama yazma.

Kullanıcı sorusu:

{question}

ADAYLAR:

{candidate_text}

Tam olarak şu şemada cevap ver:

{{
  "ranking": [1, 3, 2]
}}

En fazla {top_k} aday yaz.
"""

    try:
        response = client.messages.create(
            model=
                CLAUDE_MODEL,

            max_tokens=
                200,

            messages=[
                {
                    "role":
                        "user",

                    "content":
                        prompt,
                }
            ],
        )

        raw = (
            response.content[0]
            .text
            .strip()
        )

        parsed = (
            parse_rerank_json(
                raw
            )
        )

        ranking = (
            extract_valid_ranking(
                parsed=
                    parsed,

                candidate_count=
                    len(
                        candidates
                    ),

                top_k=
                    top_k,
            )
        )

        selected = []

        for position in ranking:
            selected.append(
                candidates[
                    position - 1
                ]
            )

        if selected:
            return selected

        if RERANK_DEBUG:
            print(
                "\nReranker debug:"
            )

            print(
                "Geçerli ranking alınamadı."
            )

            print(
                raw
            )

    except Exception as error:
        if RERANK_DEBUG:
            print(
                "\nReranker debug:"
            )

            print(
                repr(
                    error
                )
            )

    return candidates[
        :top_k
    ]


# ============================================================
# UNIQUE DOCUMENT IDS
# ============================================================

def get_unique_document_ids(
    sources,
):
    result = []

    for source in sources:
        document_id = source.get(
            "document_id"
        )

        if (
            document_id
            and document_id
            not in result
        ):
            result.append(
                document_id
            )

    return result


# ============================================================
# PROVISION REPOSITORY SUMMARY
# ============================================================

def build_provision_resolution_summary(
    resolution,
):
    if not isinstance(
        resolution,
        dict,
    ):
        return {}

    candidates = (
        resolution.get(
            "candidates",
            [],
        )
    )

    return {
        "status":
            resolution.get(
                "status"
            ),

        "match_type":
            resolution.get(
                "match_type"
            ),

        "score":
            resolution.get(
                "score"
            ),

        "provision_id":
            resolution.get(
                "provision_id"
            ),

        "candidate_version_ids": [
            candidate.get(
                "provision_version_id"
            )
            for candidate
            in candidates
        ],
    }


# ============================================================
# PROVISION VERSION SUMMARY
# ============================================================

def build_provision_version_summary(
    selection,
):
    if not isinstance(
        selection,
        dict,
    ):
        return {}

    return {
        "policy_version":
            selection.get(
                "policy_version"
            ),

        "temporal_mode":
            selection.get(
                "temporal_mode"
            ),

        "query_date":
            selection.get(
                "query_date"
            ),

        "provision_id":
            selection.get(
                "provision_id"
            ),

        "selection_status":
            selection.get(
                "selection_status"
            ),

        "failure_reason":
            selection.get(
                "failure_reason"
            ),

        "selected_provision_version_ids":
            selection.get(
                "selected_provision_version_ids",
                [],
            ),

        "valid_provision_version_ids":
            selection.get(
                "valid_provision_version_ids",
                [],
            ),

        "unknown_provision_version_ids":
            selection.get(
                "unknown_provision_version_ids",
                [],
            ),

        "invalid_provision_version_ids":
            selection.get(
                "invalid_provision_version_ids",
                [],
            ),

        "neutral_provision_version_ids":
            selection.get(
                "neutral_provision_version_ids",
                [],
            ),

        "candidate_count":
            selection.get(
                "candidate_count",
                0,
            ),
    }


# ============================================================
# PROVISION CONTEXT V2
#
# Repository
#     ↓
# Provision Version Policy
#     ↓
# Provision Policy
# ============================================================

def build_provision_context(
    question,
    metadata,
    sources,
    temporal_context,
):
    question_scope = (
        classify_provision_question_scope(
            question
        )
    )

    if not metadata.get(
        "madde"
    ):
        return {
            "status":
                "not_requested",

            "question_scope":
                question_scope,

            "resolution":
                {},

            "version_selection":
                {},

            "policy":
                None,

            "failure_reason":
                None,
        }

    document_ids = (
        get_unique_document_ids(
            sources
        )
    )

    if not document_ids:
        return {
            "status":
                "not_found",

            "question_scope":
                question_scope,

            "resolution":
                {},

            "version_selection":
                {},

            "policy":
                None,

            "failure_reason":
                "document_id_not_available",
        }

    if len(
        document_ids
    ) > 1:
        return {
            "status":
                "ambiguous",

            "question_scope":
                question_scope,

            "resolution": {
                "document_ids":
                    document_ids,
            },

            "version_selection":
                {},

            "policy":
                None,

            "failure_reason":
                "multiple_document_candidates",
        }

    document_id = (
        document_ids[
            0
        ]
    )

    # ========================================================
    # REPOSITORY
    # ========================================================

    resolution = resolve_provisions(
        document_id=
            document_id,

        madde=
            metadata.get(
                "madde"
            ),

        fikra=
            metadata.get(
                "fikra"
            ),

        bent=
            metadata.get(
                "bent"
            ),
    )

    resolution_summary = (
        build_provision_resolution_summary(
            resolution
        )
    )

    if (
        resolution.get(
            "status"
        )
        != "resolved"
    ):
        return {
            "status":
                resolution.get(
                    "status"
                ),

            "question_scope":
                question_scope,

            "resolution":
                resolution_summary,

            "version_selection":
                {},

            "policy":
                None,

            "failure_reason":
                (
                    "provision_"
                    f"{resolution.get('status')}"
                ),
        }

    candidates = resolution.get(
        "candidates",
        [],
    )

    # ========================================================
    # PROVISION VERSION POLICY
    # ========================================================

    version_selection = (
        select_provision_versions(
            candidates=
                candidates,

            temporal_mode=
                temporal_context.get(
                    "mode",
                    "neutral",
                ),

            query_date=
                temporal_context.get(
                    "query_date"
                ),
        )
    )

    version_summary = (
        build_provision_version_summary(
            version_selection
        )
    )

    version_status = (
        version_selection.get(
            "selection_status"
        )
    )

    # ========================================================
    # FAIL-CLOSED VERSION STATES
    # ========================================================

    if version_status in {
        "version_conflict",
        "version_unresolved",
        "no_valid_version",
        "mixed_provision_candidates",
        "no_candidates",
    }:
        return {
            "status":
                version_status,

            "question_scope":
                question_scope,

            "resolution":
                resolution_summary,

            "version_selection":
                version_summary,

            "policy":
                None,

            "failure_reason":
                (
                    "provision_"
                    f"{version_status}"
                ),
        }

    selected_candidates = (
        version_selection.get(
            "selected_candidates",
            [],
        )
    )

    # ========================================================
    # NEUTRAL MODE
    #
    # Birden fazla version varsa içerik sorusunda
    # rastgele version seçmiyoruz.
    #
    # Ancak scope=neutral olduğundan deterministic formal /
    # applicability sonucu da gerekmez.
    # ========================================================

    if (
        version_status
        == "neutral"
        and len(
            selected_candidates
        ) > 1
    ):
        if question_scope == "neutral":
            return {
                "status":
                    "resolved",

                "question_scope":
                    question_scope,

                "resolution":
                    resolution_summary,

                "version_selection":
                    version_summary,

                "provision_version_id":
                    None,

                "verification_state":
                    None,

                "policy":
                    None,

                "failure_reason":
                    None,
            }

        return {
            "status":
                "version_unresolved",

            "question_scope":
                question_scope,

            "resolution":
                resolution_summary,

            "version_selection":
                version_summary,

            "policy":
                None,

            "failure_reason":
                "provision_version_unresolved",
        }

    # ========================================================
    # SUCCESS SHOULD HAVE ONE VERSION
    # ========================================================

    if len(
        selected_candidates
    ) != 1:
        return {
            "status":
                "version_unresolved",

            "question_scope":
                question_scope,

            "resolution":
                resolution_summary,

            "version_selection":
                version_summary,

            "policy":
                None,

            "failure_reason":
                "provision_version_unresolved",
        }

    provision = (
        selected_candidates[
            0
        ]
    )

    # ========================================================
    # PROVISION POLICY
    # ========================================================

    policy = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            temporal_context.get(
                "mode"
            ),

        query_date=
            temporal_context.get(
                "query_date"
            ),

        question_scope=
            question_scope,
    )

    return {
        "status":
            "resolved",

        "question_scope":
            question_scope,

        "resolution":
            resolution_summary,

        "version_selection":
            version_summary,

        "provision_version_id":
            provision.get(
                "provision_version_id"
            ),

        "verification_state":
            provision.get(
                "verification_state"
            ),

        "policy":
            policy,

        "failure_reason":
            None,
    }


# ============================================================
# PROVISION POLICY INSTRUCTION
# ============================================================

def build_provision_instruction(
    provision_context,
):
    if not provision_context:
        return ""

    status = (
        provision_context.get(
            "status"
        )
    )

    scope = (
        provision_context.get(
            "question_scope"
        )
    )

    policy = (
        provision_context.get(
            "policy"
        )
    )

    version_selection = (
        provision_context.get(
            "version_selection",
            {},
        )
    )

    provision_version_status = (
        version_selection.get(
            "selection_status"
        )
    )

    if status != "resolved":
        if scope == "neutral":
            return ""

        return f"""
PROVISION POLICY:

Provision-level resolution güvenilir biçimde tamamlanamadı.

Resolution status:
{status}

Provision version status:
{provision_version_status}

Bu nedenle provision-level yürürlük veya applicability hakkında
kesin sonuç üretme.
"""

    if not policy:
        return ""

    formal_result = (
        policy.get(
            "formal",
            {},
        ).get(
            "result"
        )
    )

    applicability_result = (
        policy.get(
            "applicability",
            {},
        ).get(
            "result"
        )
    )

    target_date = (
        policy.get(
            "target_date"
        )
    )

    matched_windows = (
        policy.get(
            "applicability",
            {},
        ).get(
            "matched_window_ids",
            [],
        )
    )

    return f"""
PROVISION POLICY — AUTHORITATIVE STRUCTURED RESULT

Provision version selection:
{provision_version_status}

Question scope:
{scope}

Target date:
{target_date}

Formal result:
{formal_result}

Applicability result:
{applicability_result}

Matched applicability windows:
{matched_windows}

KURALLAR:

- provision version status=unknown ise,
  sürüm VALID olarak doğrulanmıştır deme.

- formal_result ile applicability_result'i karıştırma.

- applicability=not_applicable:
  provision mülgadır anlamına gelmez.

- formal=unknown:
  provision'ın formal yürürlük durumunun doğrulanmadığını ifade eder.

- applicability=applicable:
  yalnızca zaman penceresi bakımından applicable demektir.
"""


# ============================================================
# DETERMINISTIC PROVISION ANSWER
# ============================================================

def build_deterministic_provision_answer(
    question,
    provision_context,
    sources,
):
    if not provision_context:
        return None

    scope = (
        provision_context.get(
            "question_scope"
        )
    )

    if scope == "neutral":
        return None

    status = (
        provision_context.get(
            "status"
        )
    )

    version_selection = (
        provision_context.get(
            "version_selection",
            {},
        )
    )

    version_status = (
        version_selection.get(
            "selection_status"
        )
    )

    # ========================================================
    # PROVISION VERSION FAIL-CLOSED
    # ========================================================

    if status != "resolved":
        if status == "version_conflict":
            return (
                "Sorulan hüküm için sorgu tarihi bakımından "
                "birden fazla temporal-valid provision sürümü "
                "bulundu. Yanlış hukuki sürüm kullanmamak için "
                "sistem otomatik provision sürümü seçmedi."
            )

        if status == "version_unresolved":
            return (
                "Sorulan hüküm için birden fazla provision sürümü "
                "bulundu; ancak mevcut formal/temporal metadata "
                "hangi sürümün doğru olduğunu güvenilir biçimde "
                "belirlemeye yeterli değil. Sistem version numarası "
                "veya manifest sırasına göre tahmin yapmadı."
            )

        if status == "no_valid_version":
            return (
                "Sorulan tarih bakımından mevcut provision "
                "sürümleri arasında formal olarak geçerli olduğu "
                "doğrulanabilen bir sürüm bulunamadı. Yanlış sürümle "
                "hukuki sonuç üretmemek için cevap fail-closed "
                "bırakıldı."
            )

        if status == "mixed_provision_candidates":
            return (
                "Provision adayları aynı hukuki hükme ait değil. "
                "Bu veri bütünlüğü problemi nedeniyle sistem "
                "provision-level sonuç üretmedi."
            )

        return (
            "Belge düzeyinde kaynaklar bulundu; ancak sorulan "
            "hüküm için provision-level kayıt güvenilir biçimde "
            "çözümlenemedi. Bu nedenle hükmün formal yürürlük veya "
            "uygulanabilirlik durumu hakkında kesin sonuç "
            "verilemiyor."
        )

    policy = (
        provision_context.get(
            "policy"
        )
    )

    if not policy:
        return None

    formal = policy.get(
        "formal",
        {},
    )

    applicability = (
        policy.get(
            "applicability",
            {},
        )
    )

    formal_result = (
        formal.get(
            "result"
        )
    )

    applicability_result = (
        applicability.get(
            "result"
        )
    )

    target_date = (
        policy.get(
            "target_date"
        )
    )

    matched_windows = (
        applicability.get(
            "matched_window_ids",
            [],
        )
    )

    first_source = (
        sources[0]
        if sources
        else {}
    )

    kanun_no = (
        first_source.get(
            "kanun_no"
        )
    )

    madde = (
        first_source.get(
            "madde"
        )
    )

    fikra = (
        first_source.get(
            "fikra"
        )
    )

    document_status = (
        first_source.get(
            "status"
        )
    )

    document_temporal = (
        first_source.get(
            "temporal_result"
        )
    )

    legal_reference = (
        f"{kanun_no} sayılı Kanun"
        if kanun_no
        else "İlgili kanun"
    )

    if madde:
        legal_reference += (
            f" m.{madde}"
        )

    if fikra:
        legal_reference += (
            f"/{fikra}"
        )

    # ========================================================
    # APPLICABILITY
    # ========================================================

    if scope == "applicability":
        if applicability_result == "applicable":
            window_text = (
                ", ".join(
                    matched_windows
                )
                if matched_windows
                else (
                    "doğrulanmış "
                    "applicability window"
                )
            )

            return (
                "## Sonuç\n\n"
                f"**{target_date} tarihi bakımından "
                f"{legal_reference} kapsamındaki "
                "başvuru/yararlanma zaman penceresi "
                "`applicable` olarak doğrulanmıştır.**\n\n"
                "Provision Policy, sorgu tarihinin doğrulanmış "
                "şu pencere içinde olduğunu tespit etti:\n\n"
                f"**{window_text}**\n\n"
                "Bu sonuç yalnızca **zaman penceresi bakımından "
                "uygulanabilirliği** ifade eder. Mükellefin diğer "
                "maddi ve hukuki şartları taşıdığını tek başına "
                "kanıtlamaz.\n\n"
                "## Formal yürürlük ayrımı\n\n"
                f"Provision version selection: "
                f"**{version_status}**\n\n"
                "Provision-level formal sonuç:\n\n"
                f"**{formal_result}**\n\n"
                "Belge düzeyindeki kayıt:\n\n"
                f"- document status: `{document_status}`\n"
                f"- document temporal result: "
                f"`{document_temporal}`\n\n"
                "Dolayısıyla başvuru zamanının açık olması ile "
                "hükmün formal yürürlük statüsü ayrı "
                "değerlendirilmiştir."
            )

        if (
            applicability_result
            == "not_applicable"
        ):
            return (
                "## Sonuç\n\n"
                f"**{target_date} tarihi bakımından "
                f"{legal_reference} kapsamındaki yeni "
                "başvuru/yararlanma zaman penceresi "
                "`not_applicable` olarak doğrulanmıştır.**\n\n"
                "Bu sonuç, Provision Policy'nin yalnızca "
                "doğrulanmış applicability windows'a değil, "
                "ayrıca bu pencere zincirinin **complete ve "
                "verified** olduğu bilgisine dayanır.\n\n"
                "Başka bir ifadeyle sorgu tarihi, doğrulanmış "
                "başvuru ve süre uzatımı pencerelerinin "
                "dışındadır.\n\n"
                "## Önemli ayrım\n\n"
                "Bu sonuç:\n\n"
                f'**"{legal_reference} mülgadır"**\n\n'
                "anlamına gelmez.\n\n"
                f"Provision version selection: "
                f"**{version_status}**\n\n"
                "Provision-level formal sonuç ayrıca:\n\n"
                f"**{formal_result}**\n\n"
                "olarak tutulmaktadır.\n\n"
                "Belge düzeyindeki kayıt ise:\n\n"
                f"- document status: `{document_status}`\n"
                f"- document temporal result: "
                f"`{document_temporal}`\n\n"
                "şeklindedir.\n\n"
                "Dolayısıyla sistem **başvuru süresi sona ermiş** "
                "ile **hüküm yürürlükten kaldırılmış** sonuçlarını "
                "birbirinden ayırmaktadır."
            )

        return (
            "## Sonuç\n\n"
            f"{target_date} tarihi bakımından "
            f"{legal_reference} için provision-level "
            "applicability sonucu **`unknown`** durumundadır.\n\n"
            "Mevcut doğrulanmış veri, bu tarihte "
            "başvuru/yararlanma imkanının açık veya kapalı "
            "olduğunu kesin biçimde belirlemeye yeterli değildir."
        )

    # ========================================================
    # FORMAL
    # ========================================================

    if scope == "formal_status":
        if formal_result == "valid":
            return (
                "## Sonuç\n\n"
                f"Provision Policy'ye göre "
                f"**{legal_reference}**, {target_date} tarihi "
                "bakımından provision-level formal olarak "
                "**`valid`** durumundadır.\n\n"
                f"Provision version selection: "
                f"**{version_status}**\n\n"
                "Applicability sonucu ayrıca:\n\n"
                f"**{applicability_result}**"
            )

        if formal_result == "invalid":
            return (
                "## Sonuç\n\n"
                f"Provision Policy'ye göre "
                f"**{legal_reference}**, {target_date} tarihi "
                "bakımından provision-level formal olarak "
                "**`invalid`** durumundadır.\n\n"
                f"Provision version selection: "
                f"**{version_status}**\n\n"
                "Applicability sonucu ayrıca:\n\n"
                f"**{applicability_result}**"
            )

        return (
            "## Sonuç\n\n"
            f"**{legal_reference} için {target_date} tarihi "
            "bakımından provision-level formal yürürlük durumu "
            "henüz doğrulanmış değildir.**\n\n"
            f"Provision version selection: "
            f"**{version_status}**\n\n"
            "Provision Policy sonucu:\n\n"
            "**formal = `unknown`**\n\n"
            "Belge düzeyinde:\n\n"
            f"- document status: `{document_status}`\n"
            f"- document temporal result: "
            f"`{document_temporal}`\n\n"
            "bilgileri mevcut olsa da bunlar tek başına "
            "sorulan madde/fıkranın formal olarak yürürlükte "
            "veya mülga olduğunu kanıtlamaz.\n\n"
            "Applicability sonucu ayrıca:\n\n"
            f"**{applicability_result}**"
        )

    # ========================================================
    # BOTH
    # ========================================================

    if scope == "both":
        return (
            "## Sonuç\n\n"
            f"{legal_reference} için {target_date} tarihi "
            "bakımından iki ayrı hukuki sonuç hesaplandı:\n\n"
            f"- **Provision version:** `{version_status}`\n"
            f"- **Formal durum:** `{formal_result}`\n"
            f"- **Applicability:** `{applicability_result}`\n\n"
            "Bu sonuçlar bilinçli olarak birbirinden ayrı "
            "tutulmaktadır."
        )

    return None


# ============================================================
# DOCUMENT-LEVEL STATUS GUARD
# ============================================================

def is_provision_formal_status_question(
    question,
):
    return (
        classify_provision_question_scope(
            question
        )
        in {
            "formal_status",
            "both",
        }
    )


def build_provision_status_guard_answer(
    question,
    sources,
):
    if not (
        is_provision_formal_status_question(
            question
        )
    ):
        return None

    if not sources:
        return None

    verified_repeal_dates = [
        source.get(
            "mulga_tarihi"
        )
        for source in sources
        if source.get(
            "mulga_tarihi"
        )
    ]

    if verified_repeal_dates:
        return None

    first_source = sources[
        0
    ]

    kanun_no = first_source.get(
        "kanun_no"
    )

    madde = first_source.get(
        "madde"
    )

    fikra = first_source.get(
        "fikra"
    )

    document_status = (
        first_source.get(
            "status"
        )
    )

    temporal_result = (
        first_source.get(
            "temporal_result"
        )
    )

    return (
        "## Sonuç\n\n"
        "Mevcut kaynakta belge düzeyinde:\n\n"
        f"- status = `{document_status}`\n"
        f"- temporal_result = `{temporal_result}`\n\n"
        f"Ancak {kanun_no} sayılı Kanunun madde {madde}, "
        f"fıkra {fikra} için doğrulanmış hüküm düzeyi "
        "mülga/geçerlilik sonu kaydı bulunmadığından yalnızca "
        "document-level metadata kullanılarak kesin provision "
        "formal sonucu üretilemez.\n\n"
        "`mulga_tarihi = None` yalnızca sistemde doğrulanmış "
        "bir mülga tarihi bulunmadığını ifade eder; hükmün "
        "kesin biçimde yürürlükte olduğunu kanıtlamaz."
    )


# ============================================================
# RAG CONTEXT
# ============================================================

def build_context(
    sources,
):
    blocks = []

    for index, source in enumerate(
        sources,
        start=1,
    ):
        block = f"""
Kaynak {index}

Document ID:
{source.get("document_id")}

Belge Türü:
{source.get("belge_turu")}

Başlık:
{source.get("title")}

Kanun:
{source.get("kanun_no")}

Madde:
{source.get("madde")}

Fıkra:
{source.get("fikra")}

Bent:
{source.get("bent")}

Status:
{source.get("status")}

Version:
{source.get("version")}

Version Selection:
{source.get("version_selection_status")}

Temporal Mode:
{source.get("temporal_mode")}

Query Date:
{source.get("query_date")}

Temporal Result:
{source.get("temporal_result")}

Yürürlük Tarihi:
{source.get("yururluk_tarihi")}

Mülga Tarihi:
{source.get("mulga_tarihi")}

Authority:
{source.get("authority_level")}

Metin:
{source.get("text")}
"""

        blocks.append(
            block.strip()
        )

    return (
        "\n\n"
        "========================================"
        "\n\n"
    ).join(
        blocks
    )


# ============================================================
# DOCUMENT VERSION INSTRUCTION
# ============================================================

def build_version_instruction(
    version_summary,
):
    status = (
        version_summary.get(
            "selection_status"
        )
    )

    if status == "neutral":
        return """
DOCUMENT VERSION KURALI:

Temporal document version selection uygulanmadı.

Version numarası yüksek diye
"en güncel sürüm" sonucu çıkarma.
"""

    if status == "selected":
        return """
DOCUMENT VERSION KURALI:

Document Version Policy tek uygun document version seçti.

Yalnızca seçili kaynakları kullan.

Document version seçilmiş olması,
provision version veya applicability kanıtı değildir.
"""

    if status == "unknown":
        return """
DOCUMENT VERSION KURALI:

Tek temporal-unknown document version kullanılabilir durumda.

Doğru tarihsel sürüm olduğunun kesin doğrulandığını söyleme.
"""

    return """
DOCUMENT VERSION KURALI:

Version numarası veya document_id üzerinden
hukuki geçerlilik çıkarımı yapma.
"""


# ============================================================
# TEMPORAL INSTRUCTION
# ============================================================

def build_temporal_instruction(
    temporal_context,
):
    mode = temporal_context.get(
        "mode"
    )

    query_date = (
        temporal_context.get(
            "query_date_string"
        )
    )

    if mode == "neutral":
        return """
TEMPORAL KURAL:

Bu sorgu document-level temporal seçim gerektirmiyor.

Gereksiz yürürlük çıkarımı yapma.
"""

    if mode == "current":
        return """
TEMPORAL KURAL:

Document temporal result yalnızca DOCUMENT LEVEL bilgisidir.

Provision version, provision formal status ve applicability
ayrı Policy katmanlarından gelir.
"""

    if mode == "historical_date":
        return f"""
TEMPORAL KURAL:

Sorgu tarihi: {query_date}

Document temporal result yalnızca DOCUMENT LEVEL bilgisidir.

Provision version, provision formal status ve applicability
ayrı değerlendirilmelidir.
"""

    return ""


# ============================================================
# LLM ANSWER
# ============================================================

def generate_answer(
    question,
    context,
    temporal_context,
    version_summary,
    provision_context=None,
):
    temporal_instruction = (
        build_temporal_instruction(
            temporal_context
        )
    )

    version_instruction = (
        build_version_instruction(
            version_summary
        )
    )

    provision_instruction = (
        build_provision_instruction(
            provision_context
        )
    )

    prompt = f"""
Sen yalnızca verilen hukuki kaynaklara ve yapılandırılmış Policy
sonuçlarına dayanarak cevap veren bir Türk vergi hukuku bilgi
asistanısın.

Kullanıcı sorusu:

{question}

KAYNAKLAR:

{context}

{temporal_instruction}

{version_instruction}

{provision_instruction}

============================================================
KURALLAR
============================================================

1. Kaynaklarda bulunmayan hukuki bilgi üretme.

2. Model genel bilgisini kaynak boşluklarını doldurmak için kullanma.

3. Document version ile provision version'ı karıştırma.

4. Document temporal result ile provision-level formal result'i
   karıştırma.

5. Provision formal result ile applicability result'i karıştırma.

6. Applicability not_applicable:
   provision mülga demek değildir.

7. Applicability applicable:
   mükellefin bütün maddi şartları sağladığı anlamına gelmez.

8. mulga_tarihi=None:
   "kesinlikle mülga değildir" anlamına gelmez.

9. Provision Version Policy sonucu varsa onunla çelişme.

10. Provision Policy sonucu varsa onunla çelişme.

11. Version numarası yüksek diye sürüm seçme.

12. Kaynak yetersizse açıkça belirt.

Önce kısa sonuç ver.
Ardından hukuki açıklamayı yap.
"""

    response = (
        client.messages.create(
            model=
                CLAUDE_MODEL,

            max_tokens=
                1600,

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

    return (
        response.content[0]
        .text
        .strip()
    )


# ============================================================
# SOURCE SUMMARY
# ============================================================

def build_source_summary(
    sources,
):
    result = []

    fields = [
        "document_id",
        "chunk_id",
        "belge_turu",
        "title",
        "short_title",
        "kanun_no",
        "document_number",
        "madde",
        "fikra",
        "bent",
        "page",
        "source",
        "kaynak_kurum",
        "official_source",
        "source_url",
        "status",
        "version",
        "previous_version",
        "next_version",
        "version_selection_status",
        "version_group_status",
        "resmi_gazete_tarihi",
        "resmi_gazete_sayisi",
        "yayin_tarihi",
        "yururluk_tarihi",
        "gecerlilik_baslangici",
        "gecerlilik_sonu",
        "mulga_tarihi",
        "temporal_mode",
        "query_date",
        "temporal_result",
        "temporal_score",
        "authority_level",
        "semantic_score",
        "metadata_score",
        "final_score",
    ]

    for source in sources:
        item = {}

        for field in fields:
            item[
                field
            ] = source.get(
                field
            )

        result.append(
            item
        )

    return result


# ============================================================
# NO DOCUMENT SOURCE ANSWER
# ============================================================

def build_no_source_answer(
    failure_reason,
    temporal_context,
    version_summary=None,
):
    temporal_mode = (
        temporal_context.get(
            "mode"
        )
    )

    query_date = (
        temporal_context.get(
            "query_date_string"
        )
    )

    if failure_reason == "version_conflict":
        return (
            "Aynı hukuki belge için sorgulanan zaman bakımından "
            "birden fazla temporal-valid sürüm tespit edildi. "
            "Yanlış hukuki sürüm kullanma riskini önlemek amacıyla "
            "sistem otomatik sürüm seçimi yapmadı."
        )

    if failure_reason == "version_unresolved":
        return (
            "Aynı hukuki belge için birden fazla sürüm bulundu; "
            "ancak mevcut temporal metadata hangi sürümün doğru "
            "olduğunu güvenilir biçimde belirlemeye yeterli değil. "
            "Bu nedenle sistem tahmin yaparak bir sürüm seçmedi."
        )

    if failure_reason == "no_valid_version":
        if (
            temporal_mode
            == "historical_date"
            and query_date
        ):
            return (
                "Mevcut indekslenmiş belge sürümleri arasında "
                f"{query_date} tarihinde temporal olarak geçerli "
                "olduğu doğrulanabilen bir sürüm bulunamadı."
            )

        return (
            "Mevcut indekslenmiş belge sürümleri arasında "
            "uygun temporal sürüm bulunamadı."
        )

    if failure_reason == "temporal_mismatch":
        return (
            "İndekste hukuki referansla eşleşen kaynak bulunuyor; "
            "ancak sorgulanan tarih bakımından uygun document-level "
            "temporal kaynak doğrulanamadı."
        )

    if (
        failure_reason
        == "explicit_reference_not_found"
    ):
        return (
            "Mevcut indekslenmiş kaynaklarda bu açık hukuki "
            "referansı karşılayan kaynak bulunamadı."
        )

    return (
        "Mevcut indekslenmiş kaynaklarda soruyu karşılayan "
        "yeterli kaynak bulunamadı."
    )


# ============================================================
# MAIN
# ============================================================

def answer_question(
    question,
    history=None,
):
    # ========================================================
    # 1. QUERY REWRITE
    # ========================================================

    search_query = rewrite_query(
        question=
            question,

        history=
            history,
    )

    # ========================================================
    # 2. QUERY METADATA
    # ========================================================

    metadata = parse_query_metadata(
        search_query
    )

    # ========================================================
    # 3. TEMPORAL
    # ========================================================

    temporal_context = (
        build_temporal_context(
            search_query
        )
    )

    # ========================================================
    # 4. DOCUMENT RETRIEVAL
    # ========================================================

    retrieval = retrieve_candidates(
        search_query=
            search_query,

        metadata=
            metadata,

        temporal_context=
            temporal_context,
    )

    candidates = (
        retrieval.get(
            "candidates",
            [],
        )
    )

    failure_reason = (
        retrieval.get(
            "failure_reason"
        )
    )

    retriever_failure_reason = (
        retrieval.get(
            "retriever_failure_reason"
        )
    )

    raw_version_selection = (
        retrieval.get(
            "version_selection",
            {},
        )
    )

    version_summary = (
        build_version_summary(
            raw_version_selection
        )
    )

    # ========================================================
    # 5. NO DOCUMENT SOURCE
    # ========================================================

    if not candidates:
        return {
            "answer":
                build_no_source_answer(
                    failure_reason=
                        failure_reason,

                    temporal_context=
                        temporal_context,

                    version_summary=
                        version_summary,
                ),

            "sources":
                [],

            "search_query":
                search_query,

            "metadata":
                metadata,

            "temporal": {
                "mode":
                    temporal_context.get(
                        "mode"
                    ),

                "query_date":
                    temporal_context.get(
                        "query_date_string"
                    ),

                "scope":
                    "document",
            },

            "version_selection":
                version_summary,

            "provision": {
                "status":
                    "not_evaluated",

                "question_scope":
                    classify_provision_question_scope(
                        search_query
                    ),

                "resolution":
                    {},

                "version_selection":
                    {},

                "policy":
                    None,

                "failure_reason":
                    "no_document_source",
            },

            "retrieval_failure_reason":
                failure_reason,

            "retriever_failure_reason":
                retriever_failure_reason,
        }

    # ========================================================
    # 6. RERANK
    # ========================================================

    reranked_sources = (
        rerank_candidates(
            question=
                search_query,

            candidates=
                candidates,

            top_k=
                RERANK_TOP_K,
        )
    )

    # ========================================================
    # 7. PROVISION REPOSITORY
    #    + PROVISION VERSION POLICY
    #    + PROVISION POLICY
    # ========================================================

    provision_context = (
        build_provision_context(
            question=
                search_query,

            metadata=
                metadata,

            sources=
                reranked_sources,

            temporal_context=
                temporal_context,
        )
    )

    # ========================================================
    # 8. CONTEXT
    # ========================================================

    context = build_context(
        reranked_sources
    )

    # ========================================================
    # 9. DETERMINISTIC PROVISION ANSWER
    # ========================================================

    answer = (
        build_deterministic_provision_answer(
            question=
                search_query,

            provision_context=
                provision_context,

            sources=
                reranked_sources,
        )
    )

    # ========================================================
    # 10. DOCUMENT-LEVEL SAFETY FALLBACK
    # ========================================================

    if answer is None:
        answer = (
            build_provision_status_guard_answer(
                question=
                    search_query,

                sources=
                    reranked_sources,
            )
        )

    # ========================================================
    # 11. NORMAL RAG
    # ========================================================

    if answer is None:
        answer = generate_answer(
            question=
                question,

            context=
                context,

            temporal_context=
                temporal_context,

            version_summary=
                version_summary,

            provision_context=
                provision_context,
        )

    # ========================================================
    # 12. RESPONSE
    # ========================================================

    return {
        "answer":
            answer,

        "sources":
            build_source_summary(
                reranked_sources
            ),

        "search_query":
            search_query,

        "metadata":
            metadata,

        "temporal": {
            "mode":
                temporal_context.get(
                    "mode"
                ),

            "query_date":
                temporal_context.get(
                    "query_date_string"
                ),

            "scope":
                "document",
        },

        "version_selection":
            version_summary,

        "provision":
            provision_context,

        "retrieval_failure_reason":
            None,

        "retriever_failure_reason":
            None,
    }


# ============================================================
# MANUAL TEST
# ============================================================

if __name__ == "__main__":
    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - RAG V3.5 TEST"
    )

    print(
        "======================================"
    )

    questions = [
        (
            "6736 sayılı Kanunun 5. maddesinin "
            "3. fıkrasındaki KDV artırımından "
            "10.11.2016 tarihinde yararlanılabilir miydi?"
        ),

        (
            "6736 sayılı Kanunun 5. maddesinin "
            "3. fıkrasındaki KDV artırımından "
            "2020 yılında yararlanılabilir miydi?"
        ),

        (
            "6736 sayılı Kanunun 5. maddesinin "
            "3. fıkrası 2020 yılında mülga mıydı?"
        ),
    ]

    for number, question in enumerate(
        questions,
        start=1,
    ):
        print(
            "\n\n======================================"
        )

        print(
            f" TEST {number}"
        )

        print(
            "======================================"
        )

        print(
            "\nSORU:"
        )

        print(
            question
        )

        result = answer_question(
            question=
                question,

            history=
                [],
        )

        print(
            "\nPROVISION:"
        )

        print(
            json.dumps(
                result.get(
                    "provision"
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

        print(
            "\nCEVAP:"
        )

        print(
            result.get(
                "answer"
            )
        )

    print(
        "\n======================================"
    )

    print(
        " RAG V3.5 TEST TAMAMLANDI"
    )

    print(
        "======================================"
    )