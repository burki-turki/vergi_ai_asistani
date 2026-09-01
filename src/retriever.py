# ============================================================
# VERGİ AI - RETRIEVER V3.1
#
# METADATA-FIRST + TEMPORAL-FIRST + VERSION-AWARE
# LEGAL RETRIEVAL
#
# V3.1:
# - V6/V6.1 nested metadata uyumlu
# - Metadata-first retrieval
# - Temporal evaluation
# - Temporal filtering
# - Semantic scoring
# - Version Policy V1 entegrasyonu
# - Version conflict / unresolved fail-closed
# - Detailed diagnostics
# - Eski retrieve() API ile geriye dönük uyumluluk
#
#
# AKIŞ:
#
# Metadata filter
#       ↓
# Temporal evaluation/filter
#       ↓
# Semantic score
#       ↓
# VERSION POLICY
#       ↓
# top_k
#       ↓
# RAG
#
#
# KRİTİK:
#
# Version Policy TOP_K'dan ÖNCE çalışır.
#
# Çünkü:
#
# v1 → valid
# v2 → valid
#
# ise iki sürüm de görülmeli ve:
#
# version_conflict
#
# üretilmelidir.
#
# ============================================================

import os
import pickle

import faiss
import numpy as np

from dotenv import load_dotenv
from openai import OpenAI


# ============================================================
# IMPORT UYUMLULUĞU
# ============================================================

try:

    from .source_policy import (
        get_authority_level
    )

    from .temporal_policy import (
        get_temporal_mode,
        evaluate_temporal,
        calculate_temporal_score,
        should_keep_document
    )

    from .version_policy import (
        select_versions
    )

except ImportError:

    from source_policy import (
        get_authority_level
    )

    from temporal_policy import (
        get_temporal_mode,
        evaluate_temporal,
        calculate_temporal_score,
        should_keep_document
    )

    from version_policy import (
        select_versions
    )


# ============================================================
# VERSION
# ============================================================

RETRIEVER_VERSION = "3.1"


# ============================================================
# TEMEL AYARLAR
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

INDEX_DIR = os.path.join(
    BASE_DIR,
    "index"
)

FAISS_PATH = os.path.join(
    INDEX_DIR,
    "mevzuat.faiss"
)

DOCUMENTS_PATH = os.path.join(
    INDEX_DIR,
    "documents.pkl"
)

ENV_PATH = os.path.join(
    BASE_DIR,
    ".env"
)

EMBEDDING_MODEL = (
    "text-embedding-3-small"
)


# ============================================================
# ENV
# ============================================================

load_dotenv(
    ENV_PATH
)


# ============================================================
# OPENAI
# ============================================================

client = OpenAI()


# ============================================================
# INDEX YÜKLE
# ============================================================

def load_index():

    if not os.path.exists(
        FAISS_PATH
    ):

        raise FileNotFoundError(
            "FAISS index bulunamadı:\n"
            f"{FAISS_PATH}"
        )

    if not os.path.exists(
        DOCUMENTS_PATH
    ):

        raise FileNotFoundError(
            "documents.pkl bulunamadı:\n"
            f"{DOCUMENTS_PATH}"
        )

    loaded_index = faiss.read_index(
        FAISS_PATH
    )

    with open(
        DOCUMENTS_PATH,
        "rb"
    ) as file:

        loaded_documents = pickle.load(
            file
        )

    if loaded_index.ntotal != len(
        loaded_documents
    ):

        raise ValueError(
            "FAISS kayıt sayısı ile "
            "documents.pkl kayıt sayısı eşleşmiyor. "
            f"FAISS={loaded_index.ntotal}, "
            f"documents={len(loaded_documents)}"
        )

    return (
        loaded_index,
        loaded_documents
    )


# ============================================================
# GLOBAL INDEX
# ============================================================

index, documents = load_index()


# ============================================================
# DOCUMENT TEXT
# ============================================================

def get_document_text(
    document
):

    if not isinstance(
        document,
        dict
    ):

        return ""

    text = document.get(
        "text"
    )

    if text is None:

        text = document.get(
            "page_content"
        )

    if text is None:

        return ""

    return str(
        text
    )


# ============================================================
# DOCUMENT METADATA
# ============================================================

def get_document_metadata(
    document
):

    if not isinstance(
        document,
        dict
    ):

        return {}

    metadata = document.get(
        "metadata"
    )

    if isinstance(
        metadata,
        dict
    ):

        return metadata

    # --------------------------------------------------------
    # Eski flat yapı için geriye dönük uyumluluk
    # --------------------------------------------------------

    return document


# ============================================================
# METADATA VALUE
# ============================================================

def get_metadata_value(
    document,
    field
):

    metadata = get_document_metadata(
        document
    )

    return metadata.get(
        field
    )


# ============================================================
# QUERY EMBEDDING
# ============================================================

def create_query_embedding(
    query
):

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query
    )

    vector = np.array(
        [
            response.data[
                0
            ].embedding
        ],
        dtype="float32"
    )

    faiss.normalize_L2(
        vector
    )

    return vector


# ============================================================
# NORMALIZE
# ============================================================

def normalize_value(
    value
):

    if value is None:

        return None

    return str(
        value
    ).strip().lower()


# ============================================================
# QUERY DATE OUTPUT
# ============================================================

def query_date_to_string(
    query_date
):

    if query_date is None:

        return None

    if hasattr(
        query_date,
        "isoformat"
    ):

        return query_date.isoformat()

    return str(
        query_date
    )


# ============================================================
# TEMPORAL CONTEXT
# ============================================================

def resolve_temporal_context(
    query,
    temporal_mode=None,
    query_date=None
):

    # ========================================================
    # Manuel mode verilmediyse sorudan çıkar
    # ========================================================

    if temporal_mode is None:

        detected = get_temporal_mode(
            query
        )

        temporal_mode = detected.get(
            "mode",
            "neutral"
        )

        if query_date is None:

            query_date = detected.get(
                "query_date"
            )

    # ========================================================
    # Manuel date var ama mode neutral ise
    # historical_date yap
    # ========================================================

    if (
        query_date is not None
        and temporal_mode == "neutral"
    ):

        temporal_mode = (
            "historical_date"
        )

    if temporal_mode is None:

        temporal_mode = "neutral"

    return {

        "mode":
            temporal_mode,

        "query_date":
            query_date
    }


# ============================================================
# METADATA MATCH
# ============================================================

def metadata_matches(
    document,
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None
):

    filters = {

        "kanun_no":
            kanun_no,

        "madde":
            madde,

        "fikra":
            fikra,

        "bent":
            bent,

        "belge_turu":
            belge_turu
    }

    for field, expected in filters.items():

        if expected is None:

            continue

        actual = get_metadata_value(
            document,
            field
        )

        if normalize_value(
            actual
        ) != normalize_value(
            expected
        ):

            return False

    return True


# ============================================================
# METADATA SCORE
# ============================================================

def calculate_metadata_score(
    document,
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None
):

    filters = [

        (
            "kanun_no",
            kanun_no
        ),

        (
            "madde",
            madde
        ),

        (
            "fikra",
            fikra
        ),

        (
            "bent",
            bent
        ),

        (
            "belge_turu",
            belge_turu
        )
    ]

    matched = 0.0
    total = 0.0

    for field, expected in filters:

        if expected is None:

            continue

        total += 1.0

        actual = get_metadata_value(
            document,
            field
        )

        if normalize_value(
            actual
        ) == normalize_value(
            expected
        ):

            matched += 1.0

    if total == 0:

        return 0.0

    return (
        matched
        / total
    )


# ============================================================
# AUTHORITY SCORE
# ============================================================

def calculate_authority_score(
    belge_turu
):

    authority_level = (
        get_authority_level(
            belge_turu
        )
    )

    if authority_level is None:

        authority_level = 0

    authority_score = (
        float(
            authority_level
        )
        / 100.0
    )

    return (
        authority_level,
        authority_score
    )


# ============================================================
# DOCUMENT TEMPORAL RESULT
# ============================================================

def get_document_temporal_result(
    document,
    temporal_mode,
    query_date=None,
    today=None
):

    metadata = get_document_metadata(
        document
    )

    return evaluate_temporal(
        document=metadata,
        mode=temporal_mode,
        query_date=query_date,
        today=today
    )


# ============================================================
# FINAL SCORE
# ============================================================

def calculate_final_score(
    semantic_score,
    authority_score,
    metadata_score,
    temporal_score
):

    # ========================================================
    # V3.1 WEIGHTS
    #
    # V3 ile aynı tutuluyor.
    # Version Policy ayrı karar katmanıdır.
    # ========================================================

    semantic_weight = 0.60

    authority_weight = 0.15

    metadata_weight = 0.10

    temporal_weight = 0.15

    return (
        semantic_score
        * semantic_weight

        +

        authority_score
        * authority_weight

        +

        metadata_score
        * metadata_weight

        +

        temporal_score
        * temporal_weight
    )


# ============================================================
# RESULT BUILDER
# ============================================================

def build_result(
    document,
    semantic_score,
    temporal_mode="neutral",
    query_date=None,
    today=None,
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None
):

    metadata = get_document_metadata(
        document
    )

    text = get_document_text(
        document
    )

    actual_belge_turu = metadata.get(
        "belge_turu"
    )

    # ========================================================
    # AUTHORITY
    # ========================================================

    authority_level, authority_score = (
        calculate_authority_score(
            actual_belge_turu
        )
    )

    # ========================================================
    # METADATA
    # ========================================================

    metadata_score = (
        calculate_metadata_score(
            document=document,
            kanun_no=kanun_no,
            madde=madde,
            fikra=fikra,
            bent=bent,
            belge_turu=belge_turu
        )
    )

    # ========================================================
    # TEMPORAL
    # ========================================================

    temporal_result = (
        get_document_temporal_result(
            document=document,
            temporal_mode=temporal_mode,
            query_date=query_date,
            today=today
        )
    )

    temporal_score = (
        calculate_temporal_score(
            temporal_result
        )
    )

    # ========================================================
    # FINAL SCORE
    # ========================================================

    final_score = (
        calculate_final_score(
            semantic_score=
                semantic_score,

            authority_score=
                authority_score,

            metadata_score=
                metadata_score,

            temporal_score=
                temporal_score
        )
    )

    # ========================================================
    # RESULT
    # ========================================================

    result = {

        "text":
            text,

        "metadata":
            metadata,

        # ----------------------------------------------------
        # Kimlik
        # ----------------------------------------------------

        "document_id":
            metadata.get(
                "document_id"
            ),

        "file_name":
            metadata.get(
                "file_name"
            ),

        "source":
            metadata.get(
                "source"
            ),

        "chunk_id":
            metadata.get(
                "chunk_id"
            ),

        "chunk_index":
            metadata.get(
                "chunk_index"
            ),

        # ----------------------------------------------------
        # Belge
        # ----------------------------------------------------

        "belge_turu":
            metadata.get(
                "belge_turu"
            ),

        "title":
            metadata.get(
                "title"
            ),

        "short_title":
            metadata.get(
                "short_title"
            ),

        "kanun_no":
            metadata.get(
                "kanun_no"
            ),

        "document_number":
            metadata.get(
                "document_number"
            ),

        # ----------------------------------------------------
        # Hukuki konum
        # ----------------------------------------------------

        "madde":
            metadata.get(
                "madde"
            ),

        "fikra":
            metadata.get(
                "fikra"
            ),

        "bent":
            metadata.get(
                "bent"
            ),

        "page":
            metadata.get(
                "page"
            ),

        # ----------------------------------------------------
        # Kaynak
        # ----------------------------------------------------

        "kaynak_kurum":
            metadata.get(
                "kaynak_kurum"
            ),

        "official_source":
            metadata.get(
                "official_source"
            ),

        "source_url":
            metadata.get(
                "source_url"
            ),

        # ----------------------------------------------------
        # Lifecycle
        # ----------------------------------------------------

        "active":
            metadata.get(
                "active"
            ),

        "status":
            metadata.get(
                "status"
            ),

        "version":
            metadata.get(
                "version"
            ),

        "previous_version":
            metadata.get(
                "previous_version"
            ),

        "next_version":
            metadata.get(
                "next_version"
            ),

        "supersedes":
            metadata.get(
                "supersedes"
            ),

        "superseded_by":
            metadata.get(
                "superseded_by"
            ),

        # ----------------------------------------------------
        # Tarihler
        # ----------------------------------------------------

        "resmi_gazete_tarihi":
            metadata.get(
                "resmi_gazete_tarihi"
            ),

        "resmi_gazete_sayisi":
            metadata.get(
                "resmi_gazete_sayisi"
            ),

        "yayin_tarihi":
            metadata.get(
                "yayin_tarihi"
            ),

        "yururluk_tarihi":
            metadata.get(
                "yururluk_tarihi"
            ),

        "gecerlilik_baslangici":
            metadata.get(
                "gecerlilik_baslangici"
            ),

        "gecerlilik_sonu":
            metadata.get(
                "gecerlilik_sonu"
            ),

        "mulga_tarihi":
            metadata.get(
                "mulga_tarihi"
            ),

        # ----------------------------------------------------
        # Genel metadata
        # ----------------------------------------------------

        "jurisdiction":
            metadata.get(
                "jurisdiction"
            ),

        "language":
            metadata.get(
                "language"
            ),

        "tags":
            metadata.get(
                "tags",
                []
            ),

        "relations":
            metadata.get(
                "relations",
                []
            ),

        "notes":
            metadata.get(
                "notes"
            ),

        # ----------------------------------------------------
        # Temporal output
        # ----------------------------------------------------

        "temporal_mode":
            temporal_mode,

        "query_date":
            query_date_to_string(
                query_date
            ),

        "temporal_result":
            temporal_result,

        "temporal_score":
            float(
                temporal_score
            ),

        # ----------------------------------------------------
        # Version output
        #
        # Version Policy çalışınca güncellenecek.
        # ----------------------------------------------------

        "version_selection_status":
            None,

        "version_group_status":
            None,

        # ----------------------------------------------------
        # Score
        # ----------------------------------------------------

        "semantic_score":
            float(
                semantic_score
            ),

        "metadata_score":
            float(
                metadata_score
            ),

        "authority_level":
            authority_level,

        "authority_score":
            float(
                authority_score
            ),

        "final_score":
            float(
                final_score
            )
    }

    return result


# ============================================================
# METADATA FILTER VAR MI?
# ============================================================

def has_metadata_filter(
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None
):

    return any(

        value is not None

        for value in [

            kanun_no,

            madde,

            fikra,

            bent,

            belge_turu
        ]
    )


# ============================================================
# METADATA CANDIDATE IDS
# ============================================================

def find_metadata_candidate_ids(
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None
):

    matching_ids = []

    for document_index, document in enumerate(
        documents
    ):

        if metadata_matches(
            document=document,
            kanun_no=kanun_no,
            madde=madde,
            fikra=fikra,
            bent=bent,
            belge_turu=belge_turu
        ):

            matching_ids.append(
                document_index
            )

    return matching_ids


# ============================================================
# TEMPORAL FILTER IDS
# ============================================================

def filter_candidate_ids_temporally(
    candidate_ids,
    temporal_mode,
    query_date=None,
    today=None,
    strict_temporal=False
):

    # ========================================================
    # Neutral:
    #
    # Temporal eleme yok.
    # ========================================================

    if temporal_mode == "neutral":

        return candidate_ids

    filtered_ids = []

    for document_index in candidate_ids:

        document = documents[
            document_index
        ]

        temporal_result = (
            get_document_temporal_result(
                document=document,
                temporal_mode=temporal_mode,
                query_date=query_date,
                today=today
            )
        )

        if should_keep_document(
            temporal_result=temporal_result,
            strict=strict_temporal
        ):

            filtered_ids.append(
                document_index
            )

    return filtered_ids


# ============================================================
# BELİRLİ CANDIDATE IDS SEMANTIC SCORE
#
# V3.1 değişikliği:
#
# top_k=None verildiğinde TÜM candidate'ları score eder.
#
# Version Policy'nin tüm hukuki sürümleri görebilmesi için
# Version Selection'dan önce top_k kırpılmaz.
# ============================================================

def score_candidate_ids(
    query,
    candidate_ids,
    top_k=None,
    temporal_mode="neutral",
    query_date=None,
    today=None,
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None
):

    if not candidate_ids:

        return []

    query_vector = create_query_embedding(
        query
    )

    query_array = query_vector[
        0
    ]

    scored_results = []

    for document_index in candidate_ids:

        vector = index.reconstruct(
            int(
                document_index
            )
        )

        vector = np.asarray(
            vector,
            dtype="float32"
        )

        vector_norm = np.linalg.norm(
            vector
        )

        if vector_norm > 0:

            vector = (
                vector
                / vector_norm
            )

        semantic_score = float(
            np.dot(
                query_array,
                vector
            )
        )

        document = documents[
            document_index
        ]

        result = build_result(
            document=document,
            semantic_score=semantic_score,
            temporal_mode=temporal_mode,
            query_date=query_date,
            today=today,
            kanun_no=kanun_no,
            madde=madde,
            fikra=fikra,
            bent=bent,
            belge_turu=belge_turu
        )

        scored_results.append(
            result
        )

    scored_results.sort(
        key=lambda item:
            item[
                "final_score"
            ],
        reverse=True
    )

    if top_k is None:

        return scored_results

    return scored_results[
        :top_k
    ]


# ============================================================
# VERSION GROUP STATUS MAP
# ============================================================

def build_version_group_status_map(
    version_result
):

    mapping = {}

    for group in version_result.get(
        "groups",
        []
    ):

        group_status = group.get(
            "status"
        )

        document_ids = set()

        for field in [

            "selected_document_ids",
            "valid_document_ids",
            "unknown_document_ids",
            "invalid_document_ids",
            "neutral_document_ids"
        ]:

            values = group.get(
                field,
                []
            )

            if values:

                document_ids.update(
                    values
                )

        for document_id in document_ids:

            mapping[
                document_id
            ] = group_status

    return mapping


# ============================================================
# VERSION POLICY APPLY
# ============================================================

def apply_version_policy(
    candidates,
    temporal_mode
):

    # ========================================================
    # Version Policy bağımsız modülümüz çalışır.
    # ========================================================

    version_result = select_versions(
        candidates=
            candidates,

        temporal_mode=
            temporal_mode
    )

    selected_candidates = (
        version_result.get(
            "candidates",
            []
        )
    )

    overall_status = (
        version_result.get(
            "selection_status"
        )
    )

    group_status_map = (
        build_version_group_status_map(
            version_result
        )
    )

    # ========================================================
    # Sonuçlara diagnostic metadata ekle.
    # ========================================================

    for candidate in selected_candidates:

        candidate[
            "version_selection_status"
        ] = overall_status

        candidate[
            "version_group_status"
        ] = group_status_map.get(
            candidate.get(
                "document_id"
            )
        )

    return version_result


# ============================================================
# EMPTY VERSION DIAGNOSTICS
# ============================================================

def empty_version_diagnostics(
    temporal_mode,
    selection_status="not_applied",
    failure_reason=None
):

    return {

        "candidates":
            [],

        "temporal_mode":
            temporal_mode,

        "selection_status":
            selection_status,

        "failure_reason":
            failure_reason,

        "has_conflict":
            False,

        "groups":
            []
    }


# ============================================================
# DETAILED RESPONSE BUILDER
# ============================================================

def build_detailed_response(
    results,
    temporal_mode,
    query_date=None,
    retrieval_failure_reason=None,
    version_selection=None
):

    if version_selection is None:

        version_selection = (
            empty_version_diagnostics(
                temporal_mode=
                    temporal_mode
            )
        )

    return {

        "results":
            results,

        "temporal": {

            "mode":
                temporal_mode,

            "query_date":
                query_date_to_string(
                    query_date
                )
        },

        "version_selection":
            version_selection,

        "retrieval_failure_reason":
            retrieval_failure_reason
    }


# ============================================================
# METADATA-FIRST DETAILED RETRIEVAL
# ============================================================

def retrieve_with_metadata_detailed(
    query,
    top_k,
    temporal_mode="neutral",
    query_date=None,
    today=None,
    strict_temporal=False,
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None
):

    # ========================================================
    # 1. METADATA-FIRST
    # ========================================================

    matching_ids = (
        find_metadata_candidate_ids(
            kanun_no=kanun_no,
            madde=madde,
            fikra=fikra,
            bent=bent,
            belge_turu=belge_turu
        )
    )

    if not matching_ids:

        return build_detailed_response(
            results=[],
            temporal_mode=temporal_mode,
            query_date=query_date,
            retrieval_failure_reason=
                "metadata_not_found",
            version_selection=
                empty_version_diagnostics(
                    temporal_mode=
                        temporal_mode,
                    selection_status=
                        "no_candidate",
                    failure_reason=
                        "no_candidate"
                )
        )

    # ========================================================
    # 2. TEMPORAL FILTER
    #
    # invalid elenir.
    #
    # strict_temporal=False:
    #   valid + unknown kalabilir.
    #
    # strict_temporal=True:
    #   yalnızca policy'nin izin verdiği temporal sonuçlar.
    # ========================================================

    temporal_ids = (
        filter_candidate_ids_temporally(
            candidate_ids=
                matching_ids,

            temporal_mode=
                temporal_mode,

            query_date=
                query_date,

            today=
                today,

            strict_temporal=
                strict_temporal
        )
    )

    if not temporal_ids:

        return build_detailed_response(
            results=[],
            temporal_mode=temporal_mode,
            query_date=query_date,
            retrieval_failure_reason=
                "temporal_no_candidate",
            version_selection=
                empty_version_diagnostics(
                    temporal_mode=
                        temporal_mode,
                    selection_status=
                        "no_candidate",
                    failure_reason=
                        "no_candidate"
                )
        )

    # ========================================================
    # 3. SEMANTIC SCORE
    #
    # DİKKAT:
    #
    # top_k uygulanmıyor.
    #
    # Tüm temporal-eligible version chunkları
    # Version Policy'ye gönderiliyor.
    # ========================================================

    scored_results = (
        score_candidate_ids(
            query=query,
            candidate_ids=temporal_ids,
            top_k=None,
            temporal_mode=temporal_mode,
            query_date=query_date,
            today=today,
            kanun_no=kanun_no,
            madde=madde,
            fikra=fikra,
            bent=bent,
            belge_turu=belge_turu
        )
    )

    # ========================================================
    # 4. VERSION SELECTION
    # ========================================================

    version_result = (
        apply_version_policy(
            candidates=
                scored_results,

            temporal_mode=
                temporal_mode
        )
    )

    version_candidates = (
        version_result.get(
            "candidates",
            []
        )
    )

    # ========================================================
    # 5. VERSION FAILURE
    # ========================================================

    if not version_candidates:

        version_failure_reason = (
            version_result.get(
                "failure_reason"
            )
        )

        if version_failure_reason:

            failure_reason = (
                version_failure_reason
            )

        else:

            failure_reason = (
                "version_no_candidate"
            )

        return build_detailed_response(
            results=[],
            temporal_mode=temporal_mode,
            query_date=query_date,
            retrieval_failure_reason=
                failure_reason,
            version_selection=
                version_result
        )

    # ========================================================
    # 6. FINAL RANK
    #
    # Version Selection sonrası tekrar final_score sıralaması.
    # ========================================================

    version_candidates.sort(
        key=lambda item:
            item.get(
                "final_score",
                0
            ),
        reverse=True
    )

    final_results = (
        version_candidates[
            :top_k
        ]
    )

    return build_detailed_response(
        results=
            final_results,

        temporal_mode=
            temporal_mode,

        query_date=
            query_date,

        retrieval_failure_reason=
            None,

        version_selection=
            version_result
    )


# ============================================================
# GERİYE DÖNÜK UYUMLU METADATA RETRIEVAL
# ============================================================

def retrieve_with_metadata(
    query,
    top_k,
    temporal_mode="neutral",
    query_date=None,
    today=None,
    strict_temporal=False,
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None
):

    detailed = (
        retrieve_with_metadata_detailed(
            query=query,
            top_k=top_k,
            temporal_mode=temporal_mode,
            query_date=query_date,
            today=today,
            strict_temporal=strict_temporal,
            kanun_no=kanun_no,
            madde=madde,
            fikra=fikra,
            bent=bent,
            belge_turu=belge_turu
        )
    )

    return detailed.get(
        "results",
        []
    )


# ============================================================
# TEMPORAL-FIRST GENERAL DETAILED RETRIEVAL
# ============================================================

def retrieve_temporal_first_detailed(
    query,
    top_k,
    temporal_mode,
    query_date=None,
    today=None,
    strict_temporal=False
):

    # ========================================================
    # Tüm chunklar aday.
    #
    # Büyük data setinde ileride optimize edeceğiz.
    # ========================================================

    candidate_ids = list(
        range(
            len(
                documents
            )
        )
    )

    # ========================================================
    # TEMPORAL FILTER
    # ========================================================

    candidate_ids = (
        filter_candidate_ids_temporally(
            candidate_ids=
                candidate_ids,

            temporal_mode=
                temporal_mode,

            query_date=
                query_date,

            today=
                today,

            strict_temporal=
                strict_temporal
        )
    )

    if not candidate_ids:

        return build_detailed_response(
            results=[],
            temporal_mode=temporal_mode,
            query_date=query_date,
            retrieval_failure_reason=
                "temporal_no_candidate",
            version_selection=
                empty_version_diagnostics(
                    temporal_mode=
                        temporal_mode,
                    selection_status=
                        "no_candidate",
                    failure_reason=
                        "no_candidate"
                )
        )

    # ========================================================
    # SEMANTIC SCORE
    #
    # Version conflict kaçırmamak için burada da
    # top_k öncesi score ediyoruz.
    #
    # Büyük index aşamasında candidate preselection
    # ekleyeceğiz.
    # ========================================================

    scored_results = (
        score_candidate_ids(
            query=query,
            candidate_ids=candidate_ids,
            top_k=None,
            temporal_mode=temporal_mode,
            query_date=query_date,
            today=today
        )
    )

    # ========================================================
    # VERSION
    # ========================================================

    version_result = (
        apply_version_policy(
            candidates=
                scored_results,

            temporal_mode=
                temporal_mode
        )
    )

    selected = version_result.get(
        "candidates",
        []
    )

    if not selected:

        failure_reason = (
            version_result.get(
                "failure_reason"
            )
            or "version_no_candidate"
        )

        return build_detailed_response(
            results=[],
            temporal_mode=temporal_mode,
            query_date=query_date,
            retrieval_failure_reason=
                failure_reason,
            version_selection=
                version_result
        )

    selected.sort(
        key=lambda item:
            item.get(
                "final_score",
                0
            ),
        reverse=True
    )

    return build_detailed_response(
        results=
            selected[
                :top_k
            ],

        temporal_mode=
            temporal_mode,

        query_date=
            query_date,

        retrieval_failure_reason=
            None,

        version_selection=
            version_result
    )


# ============================================================
# GERİYE DÖNÜK UYUMLU TEMPORAL FIRST
# ============================================================

def retrieve_temporal_first(
    query,
    top_k,
    temporal_mode,
    query_date=None,
    today=None,
    strict_temporal=False
):

    detailed = (
        retrieve_temporal_first_detailed(
            query=query,
            top_k=top_k,
            temporal_mode=temporal_mode,
            query_date=query_date,
            today=today,
            strict_temporal=strict_temporal
        )
    )

    return detailed.get(
        "results",
        []
    )


# ============================================================
# NORMAL SEMANTIC RETRIEVAL
#
# Neutral soru.
#
# Version Policy V1 neutral modda seçim yapmadığı için
# mevcut semantic davranışı korunuyor.
# ============================================================

def retrieve_semantic(
    query,
    top_k
):

    if index.ntotal == 0:

        return []

    query_vector = create_query_embedding(
        query
    )

    candidate_count = min(
        max(
            top_k * 10,
            50
        ),
        index.ntotal
    )

    scores, indices = index.search(
        query_vector,
        candidate_count
    )

    results = []

    for score, index_id in zip(
        scores[
            0
        ],
        indices[
            0
        ]
    ):

        if index_id < 0:

            continue

        document = documents[
            int(
                index_id
            )
        ]

        result = build_result(
            document=document,
            semantic_score=float(
                score
            ),
            temporal_mode="neutral"
        )

        result[
            "version_selection_status"
        ] = "neutral"

        result[
            "version_group_status"
        ] = "neutral"

        results.append(
            result
        )

    results.sort(
        key=lambda item:
            item[
                "final_score"
            ],
        reverse=True
    )

    return results[
        :top_k
    ]


# ============================================================
# NORMAL SEMANTIC DETAILED
# ============================================================

def retrieve_semantic_detailed(
    query,
    top_k
):

    results = retrieve_semantic(
        query=query,
        top_k=top_k
    )

    version_selection = (
        empty_version_diagnostics(
            temporal_mode="neutral",
            selection_status="neutral"
        )
    )

    version_selection[
        "candidates"
    ] = results

    return build_detailed_response(
        results=results,
        temporal_mode="neutral",
        query_date=None,
        retrieval_failure_reason=
            (
                None
                if results
                else "no_candidate"
            ),
        version_selection=
            version_selection
    )


# ============================================================
# ANA DETAILED RETRIEVE
#
# YENİ API:
#
# retrieve_detailed(...)
#
# {
#   "results": [...],
#   "temporal": {...},
#   "version_selection": {...},
#   "retrieval_failure_reason": ...
# }
#
#
# RAG'ın sonraki sürümünde bunu kullanacağız.
# ============================================================

def retrieve_detailed(
    query,
    top_k=5,
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None,
    temporal_mode=None,
    query_date=None,
    today=None,
    strict_temporal=False
):

    if not query:

        return build_detailed_response(
            results=[],
            temporal_mode="neutral",
            query_date=None,
            retrieval_failure_reason=
                "empty_query",
            version_selection=
                empty_version_diagnostics(
                    temporal_mode="neutral",
                    selection_status=
                        "no_candidate",
                    failure_reason=
                        "no_candidate"
                )
        )

    # ========================================================
    # TEMPORAL MODE
    # ========================================================

    temporal_context = (
        resolve_temporal_context(
            query=query,
            temporal_mode=temporal_mode,
            query_date=query_date
        )
    )

    resolved_mode = (
        temporal_context[
            "mode"
        ]
    )

    resolved_date = (
        temporal_context[
            "query_date"
        ]
    )

    # ========================================================
    # METADATA REFERENCE
    #
    # Metadata
    #   ↓
    # Temporal
    #   ↓
    # Semantic
    #   ↓
    # Version
    # ========================================================

    if has_metadata_filter(
        kanun_no=kanun_no,
        madde=madde,
        fikra=fikra,
        bent=bent,
        belge_turu=belge_turu
    ):

        return (
            retrieve_with_metadata_detailed(
                query=query,
                top_k=top_k,
                temporal_mode=
                    resolved_mode,
                query_date=
                    resolved_date,
                today=today,
                strict_temporal=
                    strict_temporal,
                kanun_no=kanun_no,
                madde=madde,
                fikra=fikra,
                bent=bent,
                belge_turu=belge_turu
            )
        )

    # ========================================================
    # TEMPORAL GENERAL QUERY
    # ========================================================

    if resolved_mode != "neutral":

        return (
            retrieve_temporal_first_detailed(
                query=query,
                top_k=top_k,
                temporal_mode=
                    resolved_mode,
                query_date=
                    resolved_date,
                today=today,
                strict_temporal=
                    strict_temporal
            )
        )

    # ========================================================
    # NORMAL NEUTRAL SEMANTIC
    # ========================================================

    return retrieve_semantic_detailed(
        query=query,
        top_k=top_k
    )


# ============================================================
# ESKİ ANA RETRIEVE API
#
# Geriye dönük uyumluluk:
#
# Eski:
#
# results = retrieve(...)
#
# yine LIST döndürür.
#
# Böylece mevcut RAG V3.1 ve evaluation dosyası
# hemen kırılmaz.
#
# Diagnostic gerektiğinde:
#
# retrieve_detailed(...)
#
# kullanılacak.
# ============================================================

def retrieve(
    query,
    top_k=5,
    kanun_no=None,
    madde=None,
    fikra=None,
    bent=None,
    belge_turu=None,
    temporal_mode=None,
    query_date=None,
    today=None,
    strict_temporal=False
):

    detailed = retrieve_detailed(
        query=query,
        top_k=top_k,
        kanun_no=kanun_no,
        madde=madde,
        fikra=fikra,
        bent=bent,
        belge_turu=belge_turu,
        temporal_mode=temporal_mode,
        query_date=query_date,
        today=today,
        strict_temporal=strict_temporal
    )

    return detailed.get(
        "results",
        []
    )


# ============================================================
# TEST PRINT
# ============================================================

def print_results(
    results
):

    print(
        "Sonuç sayısı:",
        len(
            results
        )
    )

    for result in results:

        print(
            result.get(
                "kanun_no"
            ),
            "/",
            result.get(
                "madde"
            ),
            "/",
            result.get(
                "fikra"
            ),
            "/",
            result.get(
                "bent"
            ),
            "| document:",
            result.get(
                "document_id"
            ),
            "| version:",
            result.get(
                "version"
            ),
            "| temporal:",
            result.get(
                "temporal_result"
            ),
            "| version_status:",
            result.get(
                "version_selection_status"
            ),
            "| group_status:",
            result.get(
                "version_group_status"
            ),
            "| score:",
            round(
                result.get(
                    "final_score",
                    0
                ),
                4
            )
        )


# ============================================================
# SYNTHETIC VERSION INTEGRATION HELPER
#
# Gerçek mevzuat değildir.
# Retriever → Version Policy bağlantısını test eder.
# ============================================================

def make_synthetic_result(
    document_id,
    version,
    temporal_result,
    final_score
):

    return {

        "document_id":
            document_id,

        "belge_turu":
            "Kanun",

        "kanun_no":
            "TEST1000",

        "document_number":
            "TEST1000",

        "version":
            version,

        "temporal_result":
            temporal_result,

        "final_score":
            final_score,

        "text":
            "Sentetik version integration testi.",

        "metadata": {

            "document_id":
                document_id,

            "belge_turu":
                "Kanun",

            "kanun_no":
                "TEST1000",

            "document_number":
                "TEST1000",

            "version":
                version,

            "temporal_result":
                temporal_result
        }
    }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - RETRIEVER V3.1 TEST"
    )

    print(
        "======================================"
    )

    # ========================================================
    # TEST 1 - NEUTRAL
    # ========================================================

    query_1 = (
        "6736 sayılı Kanunun "
        "5. maddesinin 3. fıkrası ne diyor?"
    )

    detailed_1 = retrieve_detailed(
        query=query_1,
        top_k=5,
        kanun_no="6736",
        madde="5",
        fikra="3"
    )

    print(
        "\n--------------------------------------"
    )

    print(
        "TEST 1 - NORMAL / NEUTRAL"
    )

    print_results(
        detailed_1[
            "results"
        ]
    )

    print(
        "Selection status:",
        detailed_1[
            "version_selection"
        ].get(
            "selection_status"
        )
    )

    print(
        "Failure:",
        detailed_1.get(
            "retrieval_failure_reason"
        )
    )

    # ========================================================
    # TEST 2 - CURRENT
    #
    # DİKKAT:
    #
    # Manifest artık gerçek metadata:
    #
    # status=active
    # yururluk_tarihi=2016-08-19
    #
    # Dolayısıyla eski V3 yorumundaki
    # "current sonuç 0" beklentisi artık YOK.
    # ========================================================

    query_2 = (
        "6736 sayılı Kanunun "
        "5. maddesinin 3. fıkrası "
        "bugün yürürlükte mi?"
    )

    detailed_2 = retrieve_detailed(
        query=query_2,
        top_k=5,
        kanun_no="6736",
        madde="5",
        fikra="3"
    )

    print(
        "\n--------------------------------------"
    )

    print(
        "TEST 2 - CURRENT"
    )

    print_results(
        detailed_2[
            "results"
        ]
    )

    print(
        "Temporal:",
        detailed_2.get(
            "temporal"
        )
    )

    print(
        "Selection status:",
        detailed_2[
            "version_selection"
        ].get(
            "selection_status"
        )
    )

    print(
        "Failure:",
        detailed_2.get(
            "retrieval_failure_reason"
        )
    )

    # ========================================================
    # TEST 3 - HISTORICAL 2020
    #
    # Document-level temporal policy şu anda
    # yürürlük tarihi 2016-08-19 ve son tarih yok
    # bilgisine göre değerlendirme yapar.
    #
    # Bu FORMAL DOCUMENT TEMPORAL katmanıdır.
    #
    # 5/3 hükmünden bugün/2020'de fiilen
    # yararlanılabilirlik konusu daha sonra
    # provision/applicability katmanında çözülecek.
    # ========================================================

    query_3 = (
        "6736 sayılı Kanunun "
        "5. maddesinin 3. fıkrası "
        "2020 yılında geçerli miydi?"
    )

    detailed_3 = retrieve_detailed(
        query=query_3,
        top_k=5,
        kanun_no="6736",
        madde="5",
        fikra="3"
    )

    print(
        "\n--------------------------------------"
    )

    print(
        "TEST 3 - HISTORICAL DATE"
    )

    print_results(
        detailed_3[
            "results"
        ]
    )

    print(
        "Temporal:",
        detailed_3.get(
            "temporal"
        )
    )

    print(
        "Selection status:",
        detailed_3[
            "version_selection"
        ].get(
            "selection_status"
        )
    )

    print(
        "Failure:",
        detailed_3.get(
            "retrieval_failure_reason"
        )
    )

    # ========================================================
    # TEST 4 - SYNTHETIC SINGLE VALID VERSION
    # ========================================================

    synthetic_valid = [

        make_synthetic_result(
            document_id=
                "test_v1",
            version="1",
            temporal_result="valid",
            final_score=0.80
        ),

        make_synthetic_result(
            document_id=
                "test_v2",
            version="2",
            temporal_result="invalid",
            final_score=0.95
        )
    ]

    synthetic_valid_result = (
        apply_version_policy(
            candidates=
                synthetic_valid,

            temporal_mode=
                "historical_date"
        )
    )

    print(
        "\n--------------------------------------"
    )

    print(
        "TEST 4 - SYNTHETIC SINGLE VALID"
    )

    print(
        "Selection status:",
        synthetic_valid_result.get(
            "selection_status"
        )
    )

    print(
        "Failure:",
        synthetic_valid_result.get(
            "failure_reason"
        )
    )

    print(
        "Selected:",
        [

            item.get(
                "document_id"
            )

            for item in synthetic_valid_result.get(
                "candidates",
                []
            )
        ]
    )

    # ========================================================
    # TEST 5 - SYNTHETIC VERSION CONFLICT
    # ========================================================

    synthetic_conflict = [

        make_synthetic_result(
            document_id=
                "test_v1",
            version="1",
            temporal_result="valid",
            final_score=0.80
        ),

        make_synthetic_result(
            document_id=
                "test_v2",
            version="2",
            temporal_result="valid",
            final_score=0.90
        )
    ]

    synthetic_conflict_result = (
        apply_version_policy(
            candidates=
                synthetic_conflict,

            temporal_mode=
                "historical_date"
        )
    )

    print(
        "\n--------------------------------------"
    )

    print(
        "TEST 5 - SYNTHETIC VERSION CONFLICT"
    )

    print(
        "Selection status:",
        synthetic_conflict_result.get(
            "selection_status"
        )
    )

    print(
        "Failure:",
        synthetic_conflict_result.get(
            "failure_reason"
        )
    )

    print(
        "Selected chunk:",
        len(
            synthetic_conflict_result.get(
                "candidates",
                []
            )
        )
    )

    # ========================================================
    # TEST 6 - SYNTHETIC UNKNOWN UNRESOLVED
    # ========================================================

    synthetic_unknown = [

        make_synthetic_result(
            document_id=
                "test_v1",
            version="1",
            temporal_result="unknown",
            final_score=0.80
        ),

        make_synthetic_result(
            document_id=
                "test_v2",
            version="2",
            temporal_result="unknown",
            final_score=0.90
        )
    ]

    synthetic_unknown_result = (
        apply_version_policy(
            candidates=
                synthetic_unknown,

            temporal_mode=
                "historical_date"
        )
    )

    print(
        "\n--------------------------------------"
    )

    print(
        "TEST 6 - SYNTHETIC UNKNOWN UNRESOLVED"
    )

    print(
        "Selection status:",
        synthetic_unknown_result.get(
            "selection_status"
        )
    )

    print(
        "Failure:",
        synthetic_unknown_result.get(
            "failure_reason"
        )
    )

    print(
        "Selected chunk:",
        len(
            synthetic_unknown_result.get(
                "candidates",
                []
            )
        )
    )

    print(
        "\n======================================"
    )

    print(
        " RETRIEVER V3.1 TEST TAMAMLANDI"
    )

    print(
        "======================================"
    )