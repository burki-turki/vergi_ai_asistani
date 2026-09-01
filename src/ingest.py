# ============================================================
# VERGİ AI - INGEST V6.1
#
# Incremental Legal Document Ingest
#
# V6.1:
# - Manifest validation
# - Legal PDF parsing
# - Legal hierarchy chunking
# - Incremental embedding cache
# - Content hash
# - Processing hash
# - Metadata hash
# - Metadata-only refresh
#
# Kritik amaç:
#
# PDF değişmediği halde sadece manifest metadata değişirse
# embedding API yeniden çağrılmaz.
#
# Değişiklik türleri:
#
# new
# content_changed
# processing_changed
# metadata_changed
# unchanged
# ============================================================

import os
import re
import json
import pickle
import hashlib

from pathlib import Path

import faiss
import numpy as np

from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader

from manifest_validator import (
    validate_manifest_file
)


# ============================================================
# VERSION
# ============================================================

DISPLAY_VERSION = "6.1"

# ------------------------------------------------------------
# V6.1 metadata-only bir geliştirmedir.
#
# Embedding/chunk pipeline V6 ile aynıdır.
# Bu nedenle mevcut V6 pipeline signature ile uyumluluğu
# koruyoruz ve gereksiz full re-embedding tetiklemiyoruz.
# ------------------------------------------------------------

PIPELINE_COMPAT_VERSION = "6"


# ============================================================
# PROJE YOLLARI
# ============================================================

BASE_DIR = (
    Path(
        __file__
    )
    .resolve()
    .parent
    .parent
)

DATA_DIR = (
    BASE_DIR
    / "data"
)

MEVZUAT_DIR = (
    DATA_DIR
    / "mevzuat"
)

MANIFEST_PATH = (
    DATA_DIR
    / "documents.json"
)

INDEX_DIR = (
    BASE_DIR
    / "index"
)

CACHE_DIR = (
    INDEX_DIR
    / "cache"
)

FAISS_PATH = (
    INDEX_DIR
    / "mevzuat.faiss"
)

DOCUMENTS_PATH = (
    INDEX_DIR
    / "documents.pkl"
)

CONFIG_PATH = (
    INDEX_DIR
    / "config.json"
)

STATE_PATH = (
    INDEX_DIR
    / "index_state.json"
)


# ============================================================
# ENV
# ============================================================

load_dotenv(
    BASE_DIR
    / ".env"
)


# ============================================================
# OPENAI
# ============================================================

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY"
)

if not OPENAI_API_KEY:

    raise RuntimeError(
        "OPENAI_API_KEY bulunamadı. "
        ".env dosyasını kontrol et."
    )


client = OpenAI(
    api_key=OPENAI_API_KEY
)


# ============================================================
# PIPELINE AYARLARI
# ============================================================

EMBEDDING_MODEL = (
    "text-embedding-3-small"
)

EMBEDDING_DIMENSION = 1536

CHUNK_SIZE = 1200

CHUNK_OVERLAP = 180

EMBEDDING_BATCH_SIZE = 100

CHUNK_STRATEGY_VERSION = (
    "legal_hierarchy_v3"
)

METADATA_SCHEMA_VERSION = 2


# ============================================================
# DIRECTORY INIT
# ============================================================

INDEX_DIR.mkdir(
    parents=True,
    exist_ok=True
)

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(
    path,
    default=None
):

    path = Path(
        path
    )

    if not path.exists():

        if default is not None:

            return default

        raise FileNotFoundError(
            f"JSON dosyası bulunamadı: {path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(
            file
        )


def save_json(
    path,
    data
):

    path = Path(
        path
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# HASH HELPER
# ============================================================

def hash_payload(
    payload
):

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":"
        )
    )

    return hashlib.sha256(
        serialized.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# FILE / CONTENT HASH
# ============================================================

def calculate_file_hash(
    file_path
):

    sha256 = hashlib.sha256()

    with open(
        file_path,
        "rb"
    ) as file:

        while True:

            block = file.read(
                1024 * 1024
            )

            if not block:

                break

            sha256.update(
                block
            )

    return sha256.hexdigest()


# ============================================================
# PIPELINE CONFIG
# ============================================================

def build_pipeline_config():

    # --------------------------------------------------------
    # Bu yapı V6 ile bilinçli olarak aynı tutuluyor.
    #
    # Böylece V6 → V6.1 geçişi sırf ingest kod versiyonu
    # değişti diye tüm embedding cache'i yakmaz.
    # --------------------------------------------------------

    return {

        "ingest_version":
            PIPELINE_COMPAT_VERSION,

        "embedding_model":
            EMBEDDING_MODEL,

        "embedding_dimension":
            EMBEDDING_DIMENSION,

        "chunk_size":
            CHUNK_SIZE,

        "chunk_overlap":
            CHUNK_OVERLAP,

        "chunk_strategy":
            CHUNK_STRATEGY_VERSION,

        "metadata_schema_version":
            METADATA_SCHEMA_VERSION
    }


def calculate_pipeline_signature(
    config
):

    return hash_payload(
        config
    )


# ============================================================
# DOCUMENT PROCESSING HASH
#
# Embedding / chunk sonucunu etkileyebilecek
# belge bazlı ingest ayarları.
# ============================================================

def build_processing_hash_payload(
    manifest_document
):

    ingest_config = (
        manifest_document.get(
            "ingest",
            {}
        )
        or {}
    )

    return {

        "parser":
            ingest_config.get(
                "parser"
            ),

        "chunk_strategy":
            ingest_config.get(
                "chunk_strategy"
            ),

        "ocr_required":
            ingest_config.get(
                "ocr_required",
                False
            )
    }


def calculate_processing_hash(
    manifest_document
):

    payload = (
        build_processing_hash_payload(
            manifest_document
        )
    )

    return hash_payload(
        payload
    )


# ============================================================
# DOCUMENT METADATA HASH
#
# Metni / embedding'i değiştirmeyen fakat
# retrieval ve cevap davranışını etkileyen alanlar.
# ============================================================

def build_metadata_hash_payload(
    manifest_document
):

    return {

        "file_name":
            manifest_document.get(
                "file_name"
            ),

        "active":
            manifest_document.get(
                "active"
            ),

        "belge_turu":
            manifest_document.get(
                "belge_turu"
            ),

        "title":
            manifest_document.get(
                "title"
            ),

        "short_title":
            manifest_document.get(
                "short_title"
            ),

        "kanun_no":
            manifest_document.get(
                "kanun_no"
            ),

        "document_number":
            manifest_document.get(
                "document_number"
            ),

        "kaynak_kurum":
            manifest_document.get(
                "kaynak_kurum"
            ),

        "official_source":
            manifest_document.get(
                "official_source"
            ),

        "source_url":
            manifest_document.get(
                "source_url"
            ),

        "resmi_gazete_tarihi":
            manifest_document.get(
                "resmi_gazete_tarihi"
            ),

        "resmi_gazete_sayisi":
            manifest_document.get(
                "resmi_gazete_sayisi"
            ),

        "yayin_tarihi":
            manifest_document.get(
                "yayin_tarihi"
            ),

        "yururluk_tarihi":
            manifest_document.get(
                "yururluk_tarihi"
            ),

        "gecerlilik_baslangici":
            manifest_document.get(
                "gecerlilik_baslangici"
            ),

        "gecerlilik_sonu":
            manifest_document.get(
                "gecerlilik_sonu"
            ),

        "mulga_tarihi":
            manifest_document.get(
                "mulga_tarihi"
            ),

        "status":
            manifest_document.get(
                "status"
            ),

        "version":
            manifest_document.get(
                "version"
            ),

        "previous_version":
            manifest_document.get(
                "previous_version"
            ),

        "next_version":
            manifest_document.get(
                "next_version"
            ),

        "supersedes":
            manifest_document.get(
                "supersedes"
            ),

        "superseded_by":
            manifest_document.get(
                "superseded_by"
            ),

        "jurisdiction":
            manifest_document.get(
                "jurisdiction"
            ),

        "language":
            manifest_document.get(
                "language"
            ),

        "tags":
            manifest_document.get(
                "tags",
                []
            ),

        "relations":
            manifest_document.get(
                "relations",
                []
            ),

        "notes":
            manifest_document.get(
                "notes"
            )
    }


def calculate_metadata_hash(
    manifest_document
):

    payload = (
        build_metadata_hash_payload(
            manifest_document
        )
    )

    return hash_payload(
        payload
    )


# ============================================================
# INDEX STATE
# ============================================================

def load_index_state():

    if not STATE_PATH.exists():

        return {

            "pipeline_signature":
                None,

            "documents":
                {}
        }

    return load_json(
        STATE_PATH,
        default={
            "pipeline_signature":
                None,

            "documents":
                {}
        }
    )


# ============================================================
# CACHE PATHS
# ============================================================

def get_cache_paths(
    document_id
):

    embeddings_path = (
        CACHE_DIR
        / f"{document_id}_embeddings.npy"
    )

    documents_path = (
        CACHE_DIR
        / f"{document_id}_documents.pkl"
    )

    return (
        embeddings_path,
        documents_path
    )


# ============================================================
# CACHE EXISTS
# ============================================================

def document_cache_exists(
    document_id
):

    embeddings_path, documents_path = (
        get_cache_paths(
            document_id
        )
    )

    return (
        embeddings_path.exists()
        and documents_path.exists()
    )


# ============================================================
# CACHE DELETE
# ============================================================

def delete_document_cache(
    document_id
):

    embeddings_path, documents_path = (
        get_cache_paths(
            document_id
        )
    )

    if embeddings_path.exists():

        embeddings_path.unlink()

    if documents_path.exists():

        documents_path.unlink()


# ============================================================
# CACHE DOCUMENTS ONLY LOAD
# ============================================================

def load_cached_documents_only(
    document_id
):

    _, documents_path = (
        get_cache_paths(
            document_id
        )
    )

    if not documents_path.exists():

        return []

    with open(
        documents_path,
        "rb"
    ) as file:

        return pickle.load(
            file
        )


# ============================================================
# LEGACY PROCESSING HASH INFERENCE
#
# V6 state içinde processing_hash yok.
# İlk V6.1 çalışmasında cache metadata'sından
# eski processing ayarlarını çıkarıyoruz.
# ============================================================

def infer_cached_processing_hash(
    document_id
):

    cached_documents = (
        load_cached_documents_only(
            document_id
        )
    )

    if not cached_documents:

        return None

    first_document = (
        cached_documents[
            0
        ]
    )

    if not isinstance(
        first_document,
        dict
    ):

        return None

    metadata = first_document.get(
        "metadata"
    )

    if not isinstance(
        metadata,
        dict
    ):

        return None

    payload = {

        "parser":
            metadata.get(
                "ingest_parser"
            ),

        "chunk_strategy":
            metadata.get(
                "chunk_strategy"
            ),

        "ocr_required":
            metadata.get(
                "ocr_required",
                False
            )
    }

    return hash_payload(
        payload
    )


# ============================================================
# PDF TEXT NORMALIZATION
# ============================================================

def normalize_pdf_text(
    text
):

    if not text:

        return ""

    text = text.replace(
        "\r\n",
        "\n"
    )

    text = text.replace(
        "\r",
        "\n"
    )

    text = text.replace(
        "\u00a0",
        " "
    )

    lines = []

    for line in text.split(
        "\n"
    ):

        cleaned = re.sub(
            r"[ \t]+",
            " ",
            line
        ).strip()

        lines.append(
            cleaned
        )

    normalized_lines = []

    previous_blank = False

    for line in lines:

        is_blank = (
            line == ""
        )

        if (
            is_blank
            and previous_blank
        ):

            continue

        normalized_lines.append(
            line
        )

        previous_blank = is_blank

    return "\n".join(
        normalized_lines
    ).strip()


# ============================================================
# PDF EXTRACTION
# ============================================================

def extract_pdf_pages(
    pdf_path
):

    reader = PdfReader(
        str(
            pdf_path
        )
    )

    pages = []

    for page_number, page in enumerate(
        reader.pages,
        start=1
    ):

        text = page.extract_text()

        if text is None:

            text = ""

        text = normalize_pdf_text(
            text
        )

        pages.append(
            {
                "page":
                    page_number,

                "text":
                    text
            }
        )

    return pages


# ============================================================
# LEGAL HEADER PATTERNS
# ============================================================

MADDE_PATTERN = re.compile(
    r"^\s*MADDE\s+(\d+)"
    r"(?:\s*[-–—])?",
    re.IGNORECASE
)

FIKRA_PATTERN = re.compile(
    r"^\s*\((\d+)\)\s+"
)

BENT_PATTERN = re.compile(
    r"^\s*([a-zçğıöşü])\)\s+",
    re.IGNORECASE
)


# ============================================================
# LEGAL SEGMENTATION
# ============================================================

def create_legal_segments(
    pages
):

    segments = []

    current_madde = None
    current_fikra = None
    current_bent = None

    current_lines = []

    segment_madde = None
    segment_fikra = None
    segment_bent = None
    segment_page = None


    def flush_segment():

        nonlocal current_lines

        nonlocal segment_madde
        nonlocal segment_fikra
        nonlocal segment_bent
        nonlocal segment_page

        if not current_lines:

            return

        text = "\n".join(
            current_lines
        ).strip()

        if not text:

            current_lines = []

            return

        segments.append(
            {
                "text":
                    text,

                "page":
                    segment_page,

                "madde":
                    segment_madde,

                "fikra":
                    segment_fikra,

                "bent":
                    segment_bent
            }
        )

        current_lines = []


    for page_data in pages:

        page_number = page_data[
            "page"
        ]

        text = page_data[
            "text"
        ]

        if not text:

            continue

        for raw_line in text.split(
            "\n"
        ):

            line = raw_line.strip()

            if not line:

                continue

            madde_match = (
                MADDE_PATTERN.match(
                    line
                )
            )

            fikra_match = (
                FIKRA_PATTERN.match(
                    line
                )
            )

            bent_match = (
                BENT_PATTERN.match(
                    line
                )
            )

            # =================================================
            # MADDE
            # =================================================

            if madde_match:

                flush_segment()

                current_madde = (
                    madde_match.group(
                        1
                    )
                )

                current_fikra = None
                current_bent = None

                segment_madde = (
                    current_madde
                )

                segment_fikra = None
                segment_bent = None

                segment_page = (
                    page_number
                )

                current_lines = [
                    line
                ]

                continue

            # =================================================
            # FIKRA
            # =================================================

            if (
                fikra_match
                and current_madde
                is not None
            ):

                flush_segment()

                current_fikra = (
                    fikra_match.group(
                        1
                    )
                )

                current_bent = None

                segment_madde = (
                    current_madde
                )

                segment_fikra = (
                    current_fikra
                )

                segment_bent = None

                segment_page = (
                    page_number
                )

                current_lines = [
                    line
                ]

                continue

            # =================================================
            # BENT
            # =================================================

            if (
                bent_match
                and current_madde
                is not None
            ):

                flush_segment()

                current_bent = (
                    bent_match
                    .group(
                        1
                    )
                    .lower()
                )

                segment_madde = (
                    current_madde
                )

                segment_fikra = (
                    current_fikra
                )

                segment_bent = (
                    current_bent
                )

                segment_page = (
                    page_number
                )

                current_lines = [
                    line
                ]

                continue

            # =================================================
            # NORMAL SATIR
            # =================================================

            if not current_lines:

                segment_madde = (
                    current_madde
                )

                segment_fikra = (
                    current_fikra
                )

                segment_bent = (
                    current_bent
                )

                segment_page = (
                    page_number
                )

            current_lines.append(
                line
            )

    flush_segment()

    return segments


# ============================================================
# OVERLAP
# ============================================================

def get_overlap_text(
    text,
    overlap_size
):

    if not text:

        return ""

    if len(
        text
    ) <= overlap_size:

        return text

    return text[
        -overlap_size:
    ]


# ============================================================
# SEGMENT → CHUNKS
# ============================================================

def split_segment_into_chunks(
    segment
):

    text = segment[
        "text"
    ].strip()

    if not text:

        return []

    if len(
        text
    ) <= CHUNK_SIZE:

        return [
            {
                "text":
                    text,

                "page":
                    segment.get(
                        "page"
                    ),

                "madde":
                    segment.get(
                        "madde"
                    ),

                "fikra":
                    segment.get(
                        "fikra"
                    ),

                "bent":
                    segment.get(
                        "bent"
                    )
            }
        ]

    paragraphs = [

        paragraph.strip()

        for paragraph
        in re.split(
            r"\n+",
            text
        )

        if paragraph.strip()
    ]

    chunks = []

    current = ""

    for paragraph in paragraphs:

        candidate = (
            paragraph

            if not current

            else (
                current
                + "\n"
                + paragraph
            )
        )

        if len(
            candidate
        ) <= CHUNK_SIZE:

            current = candidate

            continue

        if current:

            chunks.append(
                {
                    "text":
                        current.strip(),

                    "page":
                        segment.get(
                            "page"
                        ),

                    "madde":
                        segment.get(
                            "madde"
                        ),

                    "fikra":
                        segment.get(
                            "fikra"
                        ),

                    "bent":
                        segment.get(
                            "bent"
                        )
                }
            )

            overlap = (
                get_overlap_text(
                    current,
                    CHUNK_OVERLAP
                )
            )

            current = (
                overlap
                + "\n"
                + paragraph
            ).strip()

        else:

            # -------------------------------------------------
            # Çok uzun tek paragraf
            # -------------------------------------------------

            start = 0

            while start < len(
                paragraph
            ):

                end = (
                    start
                    + CHUNK_SIZE
                )

                piece = paragraph[
                    start:end
                ].strip()

                if piece:

                    chunks.append(
                        {
                            "text":
                                piece,

                            "page":
                                segment.get(
                                    "page"
                                ),

                            "madde":
                                segment.get(
                                    "madde"
                                ),

                            "fikra":
                                segment.get(
                                    "fikra"
                                ),

                            "bent":
                                segment.get(
                                    "bent"
                                )
                        }
                    )

                if end >= len(
                    paragraph
                ):

                    break

                start = max(
                    0,
                    end
                    - CHUNK_OVERLAP
                )

            current = ""

    if current:

        chunks.append(
            {
                "text":
                    current.strip(),

                "page":
                    segment.get(
                        "page"
                    ),

                "madde":
                    segment.get(
                        "madde"
                    ),

                "fikra":
                    segment.get(
                        "fikra"
                    ),

                "bent":
                    segment.get(
                        "bent"
                    )
            }
        )

    return chunks


# ============================================================
# BASE DOCUMENT METADATA
# ============================================================

def build_base_metadata(
    manifest_document,
    file_hash
):

    ingest_config = (
        manifest_document.get(
            "ingest",
            {}
        )
        or {}
    )

    return {

        # ----------------------------------------------------
        # Identity
        # ----------------------------------------------------

        "document_id":
            manifest_document.get(
                "document_id"
            ),

        "file_name":
            manifest_document.get(
                "file_name"
            ),

        "file_hash":
            file_hash,

        # ----------------------------------------------------
        # Document
        # ----------------------------------------------------

        "belge_turu":
            manifest_document.get(
                "belge_turu"
            ),

        "title":
            manifest_document.get(
                "title"
            ),

        "short_title":
            manifest_document.get(
                "short_title"
            ),

        "kanun_no":
            manifest_document.get(
                "kanun_no"
            ),

        "document_number":
            manifest_document.get(
                "document_number"
            ),

        # ----------------------------------------------------
        # Source
        # ----------------------------------------------------

        "kaynak_kurum":
            manifest_document.get(
                "kaynak_kurum"
            ),

        "official_source":
            manifest_document.get(
                "official_source",
                False
            ),

        "source_url":
            manifest_document.get(
                "source_url"
            ),

        # ----------------------------------------------------
        # Publication / temporal
        # ----------------------------------------------------

        "resmi_gazete_tarihi":
            manifest_document.get(
                "resmi_gazete_tarihi"
            ),

        "resmi_gazete_sayisi":
            manifest_document.get(
                "resmi_gazete_sayisi"
            ),

        "yayin_tarihi":
            manifest_document.get(
                "yayin_tarihi"
            ),

        "yururluk_tarihi":
            manifest_document.get(
                "yururluk_tarihi"
            ),

        "gecerlilik_baslangici":
            manifest_document.get(
                "gecerlilik_baslangici"
            ),

        "gecerlilik_sonu":
            manifest_document.get(
                "gecerlilik_sonu"
            ),

        "mulga_tarihi":
            manifest_document.get(
                "mulga_tarihi"
            ),

        # ----------------------------------------------------
        # Lifecycle
        # ----------------------------------------------------

        "active":
            manifest_document.get(
                "active",
                True
            ),

        "status":
            manifest_document.get(
                "status"
            ),

        "version":
            manifest_document.get(
                "version"
            ),

        "previous_version":
            manifest_document.get(
                "previous_version"
            ),

        "next_version":
            manifest_document.get(
                "next_version"
            ),

        "supersedes":
            manifest_document.get(
                "supersedes"
            ),

        "superseded_by":
            manifest_document.get(
                "superseded_by"
            ),

        # ----------------------------------------------------
        # Classification
        # ----------------------------------------------------

        "jurisdiction":
            manifest_document.get(
                "jurisdiction"
            ),

        "language":
            manifest_document.get(
                "language"
            ),

        "tags":
            manifest_document.get(
                "tags",
                []
            ),

        "relations":
            manifest_document.get(
                "relations",
                []
            ),

        "notes":
            manifest_document.get(
                "notes"
            ),

        # ----------------------------------------------------
        # Ingest metadata
        # ----------------------------------------------------

        "ingest_parser":
            ingest_config.get(
                "parser"
            ),

        "chunk_strategy":
            ingest_config.get(
                "chunk_strategy"
            ),

        "ocr_required":
            ingest_config.get(
                "ocr_required",
                False
            )
    }


# ============================================================
# BUILD DOCUMENT CHUNKS
# ============================================================

def build_document_chunks(
    manifest_document,
    file_hash
):

    file_name = manifest_document[
        "file_name"
    ]

    pdf_path = (
        MEVZUAT_DIR
        / file_name
    )

    ingest_config = (
        manifest_document.get(
            "ingest",
            {}
        )
        or {}
    )

    parser = ingest_config.get(
        "parser"
    )

    chunk_strategy = (
        ingest_config.get(
            "chunk_strategy"
        )
    )

    if parser != "legal_pdf":

        raise NotImplementedError(
            f"{manifest_document['document_id']}: "
            f"V6.1 parser={parser} "
            "için ingest uygulamıyor."
        )

    if (
        chunk_strategy
        != "legal_hierarchy"
    ):

        raise NotImplementedError(
            f"{manifest_document['document_id']}: "
            "V6.1 yalnızca "
            "chunk_strategy=legal_hierarchy "
            "destekliyor."
        )

    pages = extract_pdf_pages(
        pdf_path
    )

    segments = create_legal_segments(
        pages
    )

    chunks = []

    for segment in segments:

        chunks.extend(
            split_segment_into_chunks(
                segment
            )
        )

    base_metadata = (
        build_base_metadata(
            manifest_document,
            file_hash
        )
    )

    documents = []

    for chunk_number, chunk in enumerate(
        chunks,
        start=1
    ):

        metadata = dict(
            base_metadata
        )

        metadata.update(
            {
                "chunk_id":
                    (
                        f"{manifest_document['document_id']}"
                        f"_chunk_{chunk_number:05d}"
                    ),

                "chunk_index":
                    chunk_number - 1,

                "page":
                    chunk.get(
                        "page"
                    ),

                "madde":
                    chunk.get(
                        "madde"
                    ),

                "fikra":
                    chunk.get(
                        "fikra"
                    ),

                "bent":
                    chunk.get(
                        "bent"
                    ),

                "source":
                    file_name
            }
        )

        documents.append(
            {
                "text":
                    chunk[
                        "text"
                    ],

                "metadata":
                    metadata
            }
        )

    return documents


# ============================================================
# METADATA-ONLY REFRESH
# ============================================================

def refresh_cached_documents_metadata(
    cached_documents,
    manifest_document,
    file_hash
):

    base_metadata = (
        build_base_metadata(
            manifest_document,
            file_hash
        )
    )

    refreshed_documents = []

    file_name = manifest_document[
        "file_name"
    ]

    for item_index, item in enumerate(
        cached_documents
    ):

        if not isinstance(
            item,
            dict
        ):

            continue

        text = item.get(
            "text",
            ""
        )

        old_metadata = item.get(
            "metadata",
            {}
        )

        if not isinstance(
            old_metadata,
            dict
        ):

            old_metadata = {}

        # ----------------------------------------------------
        # Chunk-level metadata korunur.
        # Document-level metadata yeni manifestten gelir.
        # ----------------------------------------------------

        new_metadata = dict(
            base_metadata
        )

        new_metadata.update(
            {
                "chunk_id":
                    old_metadata.get(
                        "chunk_id",
                        (
                            f"{manifest_document['document_id']}"
                            f"_chunk_{item_index + 1:05d}"
                        )
                    ),

                "chunk_index":
                    old_metadata.get(
                        "chunk_index",
                        item_index
                    ),

                "page":
                    old_metadata.get(
                        "page"
                    ),

                "madde":
                    old_metadata.get(
                        "madde"
                    ),

                "fikra":
                    old_metadata.get(
                        "fikra"
                    ),

                "bent":
                    old_metadata.get(
                        "bent"
                    ),

                # file_name değişmişse eski source'u
                # korumuyoruz.
                "source":
                    file_name
            }
        )

        refreshed_documents.append(
            {
                "text":
                    text,

                "metadata":
                    new_metadata
            }
        )

    return refreshed_documents


# ============================================================
# EMBEDDINGS
# ============================================================

def create_embeddings(
    texts
):

    all_embeddings = []

    total = len(
        texts
    )

    for start in range(
        0,
        total,
        EMBEDDING_BATCH_SIZE
    ):

        end = min(
            start
            + EMBEDDING_BATCH_SIZE,
            total
        )

        batch = texts[
            start:end
        ]

        print(
            "Embedding: "
            f"{start + 1}-{end} / {total}"
        )

        response = (
            client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=batch
            )
        )

        batch_embeddings = [

            item.embedding

            for item
            in response.data
        ]

        all_embeddings.extend(
            batch_embeddings
        )

    matrix = np.array(
        all_embeddings,
        dtype="float32"
    )

    if (
        matrix.ndim != 2
        or matrix.shape[
            0
        ] != total
    ):

        raise RuntimeError(
            "Embedding matrisi beklenen "
            "boyutta üretilemedi."
        )

    faiss.normalize_L2(
        matrix
    )

    return matrix


# ============================================================
# CACHE SAVE
# ============================================================

def save_document_cache(
    document_id,
    embeddings,
    documents
):

    embeddings_path, documents_path = (
        get_cache_paths(
            document_id
        )
    )

    np.save(
        embeddings_path,
        embeddings
    )

    with open(
        documents_path,
        "wb"
    ) as file:

        pickle.dump(
            documents,
            file
        )


# ============================================================
# CACHE LOAD
# ============================================================

def load_document_cache(
    document_id
):

    embeddings_path, documents_path = (
        get_cache_paths(
            document_id
        )
    )

    embeddings = np.load(
        embeddings_path
    ).astype(
        "float32"
    )

    with open(
        documents_path,
        "rb"
    ) as file:

        documents = pickle.load(
            file
        )

    if (
        len(
            documents
        )
        != embeddings.shape[
            0
        ]
    ):

        raise RuntimeError(
            f"{document_id}: cache tutarsız. "
            "Embedding ve document sayıları farklı."
        )

    return (
        embeddings,
        documents
    )


# ============================================================
# INCLUDE DOCUMENT?
# ============================================================

def should_include_document(
    document
):

    if not document.get(
        "active",
        True
    ):

        return False

    ingest = (
        document.get(
            "ingest",
            {}
        )
        or {}
    )

    if not ingest.get(
        "enabled",
        True
    ):

        return False

    return True


# ============================================================
# CHANGE STATUS
# ============================================================

def get_document_change_status(
    document,
    current_file_hash,
    current_processing_hash,
    current_metadata_hash,
    old_state,
    force_rebuild
):

    document_id = document[
        "document_id"
    ]

    previous = (
        old_state
        .get(
            "documents",
            {}
        )
        .get(
            document_id
        )
    )

    # ========================================================
    # GLOBAL PIPELINE CHANGE
    # ========================================================

    if force_rebuild:

        return (
            "processing_changed"
        )

    # ========================================================
    # NEW
    # ========================================================

    if previous is None:

        return "new"

    # ========================================================
    # CACHE MISSING
    # ========================================================

    if not document_cache_exists(
        document_id
    ):

        return (
            "content_changed"
        )

    # ========================================================
    # CONTENT HASH
    #
    # V6 uyumluluğu:
    # önce content_hash,
    # yoksa legacy file_hash
    # ========================================================

    previous_content_hash = (
        previous.get(
            "content_hash"
        )
        or previous.get(
            "file_hash"
        )
    )

    if (
        previous_content_hash
        != current_file_hash
    ):

        return (
            "content_changed"
        )

    # ========================================================
    # PROCESSING HASH
    # ========================================================

    previous_processing_hash = (
        previous.get(
            "processing_hash"
        )
    )

    # --------------------------------------------------------
    # V6 migration
    # --------------------------------------------------------

    if previous_processing_hash is None:

        previous_processing_hash = (
            infer_cached_processing_hash(
                document_id
            )
        )

    # --------------------------------------------------------
    # Processing config bilinmiyorsa güvenli olan
    # yeniden işlemektir.
    # --------------------------------------------------------

    if previous_processing_hash is None:

        return (
            "processing_changed"
        )

    if (
        previous_processing_hash
        != current_processing_hash
    ):

        return (
            "processing_changed"
        )

    # ========================================================
    # METADATA HASH
    # ========================================================

    previous_metadata_hash = (
        previous.get(
            "metadata_hash"
        )
    )

    # --------------------------------------------------------
    # V6 state metadata_hash içermiyordu.
    #
    # Bu nedenle ilk V6.1 çalışmasında
    # tek seferlik metadata refresh yapıyoruz.
    # --------------------------------------------------------

    if previous_metadata_hash is None:

        return (
            "metadata_changed"
        )

    if (
        previous_metadata_hash
        != current_metadata_hash
    ):

        return (
            "metadata_changed"
        )

    return "unchanged"


# ============================================================
# GLOBAL FAISS
# ============================================================

def build_global_index(
    all_embeddings
):

    if not all_embeddings:

        return faiss.IndexFlatIP(
            EMBEDDING_DIMENSION
        )

    matrix = np.vstack(
        all_embeddings
    ).astype(
        "float32"
    )

    if matrix.shape[
        1
    ] != EMBEDDING_DIMENSION:

        raise RuntimeError(
            "Embedding dimension uyuşmuyor. "
            f"Beklenen={EMBEDDING_DIMENSION}, "
            f"Gerçek={matrix.shape[1]}"
        )

    faiss.normalize_L2(
        matrix
    )

    index = faiss.IndexFlatIP(
        matrix.shape[
            1
        ]
    )

    index.add(
        matrix
    )

    return index


# ============================================================
# GLOBAL INDEX SAVE
# ============================================================

def save_global_index(
    index,
    documents,
    pipeline_config,
    pipeline_signature
):

    faiss.write_index(
        index,
        str(
            FAISS_PATH
        )
    )

    with open(
        DOCUMENTS_PATH,
        "wb"
    ) as file:

        pickle.dump(
            documents,
            file
        )

    config_to_save = dict(
        pipeline_config
    )

    config_to_save[
        "runtime_ingest_version"
    ] = DISPLAY_VERSION

    config_to_save[
        "pipeline_signature"
    ] = pipeline_signature

    config_to_save[
        "total_chunks"
    ] = len(
        documents
    )

    save_json(
        CONFIG_PATH,
        config_to_save
    )


# ============================================================
# MAIN INGEST
# ============================================================

def run_ingest():

    print(
        "\n======================================"
    )

    print(
        f" VERGİ AI - INGEST V{DISPLAY_VERSION}"
    )

    print(
        "======================================"
    )

    # ========================================================
    # 1. MANIFEST VALIDATION
    # ========================================================

    print(
        "\nManifest doğrulanıyor..."
    )

    validation_result = (
        validate_manifest_file(
            raise_on_error=True
        )
    )

    print(
        "Manifest doğrulandı."
    )

    if validation_result.get(
        "warnings"
    ):

        print(
            "\nManifest uyarıları:"
        )

        for warning in (
            validation_result[
                "warnings"
            ]
        ):

            print(
                "-",
                warning
            )

    # ========================================================
    # 2. MANIFEST LOAD
    # ========================================================

    manifest = load_json(
        MANIFEST_PATH
    )

    manifest_documents = (
        manifest.get(
            "documents",
            []
        )
    )

    print(
        "\nManifest belge sayısı:",
        len(
            manifest_documents
        )
    )

    # ========================================================
    # 3. GLOBAL PIPELINE
    # ========================================================

    pipeline_config = (
        build_pipeline_config()
    )

    pipeline_signature = (
        calculate_pipeline_signature(
            pipeline_config
        )
    )

    old_state = (
        load_index_state()
    )

    old_signature = (
        old_state.get(
            "pipeline_signature"
        )
    )

    force_rebuild = (
        old_signature
        != pipeline_signature
    )

    if force_rebuild:

        print(
            "\nPipeline değişikliği algılandı."
        )

        print(
            "Chunk / embedding cache "
            "yeniden oluşturulacak."
        )

    else:

        print(
            "\nPipeline değişmedi."
        )

    # ========================================================
    # 4. INCLUDED DOCUMENTS
    # ========================================================

    included_documents = [

        document

        for document
        in manifest_documents

        if should_include_document(
            document
        )
    ]

    active_ids = {

        document[
            "document_id"
        ]

        for document
        in included_documents
    }

    # ========================================================
    # 5. REMOVED / PASSIVE
    # ========================================================

    previous_ids = set(
        old_state
        .get(
            "documents",
            {}
        )
        .keys()
    )

    removed_or_passive_ids = (
        previous_ids
        - active_ids
    )

    for document_id in sorted(
        removed_or_passive_ids
    ):

        print(
            "\nPASİF / KALDIRILDI:",
            document_id
        )

        delete_document_cache(
            document_id
        )

    # ========================================================
    # 6. DOCUMENT PROCESS
    # ========================================================

    new_state_documents = {}

    global_embeddings = []

    global_documents = []

    for document in included_documents:

        document_id = document[
            "document_id"
        ]

        file_name = document[
            "file_name"
        ]

        file_path = (
            MEVZUAT_DIR
            / file_name
        )

        print(
            "\n--------------------------------------"
        )

        print(
            "Belge:",
            document_id
        )

        print(
            "Dosya:",
            file_name
        )

        if not file_path.exists():

            raise FileNotFoundError(
                f"Dosya bulunamadı: {file_path}"
            )

        # ====================================================
        # CURRENT HASHES
        # ====================================================

        current_file_hash = (
            calculate_file_hash(
                file_path
            )
        )

        current_processing_hash = (
            calculate_processing_hash(
                document
            )
        )

        current_metadata_hash = (
            calculate_metadata_hash(
                document
            )
        )

        change_status = (
            get_document_change_status(
                document=
                    document,

                current_file_hash=
                    current_file_hash,

                current_processing_hash=
                    current_processing_hash,

                current_metadata_hash=
                    current_metadata_hash,

                old_state=
                    old_state,

                force_rebuild=
                    force_rebuild
            )
        )

        # ====================================================
        # UNCHANGED
        # ====================================================

        if change_status == "unchanged":

            print(
                f"DEĞİŞMEDİ: {document_id}"
            )

            print(
                "Embedding cache kullanılıyor."
            )

            (
                embeddings,
                cached_documents
            ) = load_document_cache(
                document_id
            )

        # ====================================================
        # METADATA-ONLY CHANGE
        # ====================================================

        elif (
            change_status
            == "metadata_changed"
        ):

            print(
                f"SADECE METADATA DEĞİŞTİ: "
                f"{document_id}"
            )

            print(
                "Embedding cache korunuyor."
            )

            print(
                "Manifest metadata chunklara "
                "yeniden uygulanıyor..."
            )

            (
                embeddings,
                cached_documents
            ) = load_document_cache(
                document_id
            )

            cached_documents = (
                refresh_cached_documents_metadata(
                    cached_documents=
                        cached_documents,

                    manifest_document=
                        document,

                    file_hash=
                        current_file_hash
                )
            )

            if len(
                cached_documents
            ) != embeddings.shape[
                0
            ]:

                raise RuntimeError(
                    f"{document_id}: metadata refresh sonrası "
                    "chunk ve embedding sayısı uyuşmuyor."
                )

            save_document_cache(
                document_id=
                    document_id,

                embeddings=
                    embeddings,

                documents=
                    cached_documents
            )

            print(
                "Metadata cache güncellendi."
            )

            print(
                "Yeni embedding üretilmedi."
            )

        # ====================================================
        # NEW / CONTENT / PROCESSING CHANGE
        # ====================================================

        else:

            if change_status == "new":

                print(
                    f"YENİ BELGE: "
                    f"{document_id}"
                )

            elif (
                change_status
                == "content_changed"
            ):

                print(
                    f"BELGE İÇERİĞİ DEĞİŞTİ: "
                    f"{document_id}"
                )

            elif (
                change_status
                == "processing_changed"
            ):

                print(
                    f"PROCESSING AYARI DEĞİŞTİ: "
                    f"{document_id}"
                )

            print(
                "PDF yeniden işleniyor..."
            )

            chunk_documents = (
                build_document_chunks(
                    manifest_document=
                        document,

                    file_hash=
                        current_file_hash
                )
            )

            print(
                "Chunk sayısı:",
                len(
                    chunk_documents
                )
            )

            if not chunk_documents:

                raise RuntimeError(
                    f"{document_id}: "
                    "hiç chunk üretilemedi."
                )

            texts = [

                item[
                    "text"
                ]

                for item
                in chunk_documents
            ]

            embeddings = (
                create_embeddings(
                    texts
                )
            )

            cached_documents = (
                chunk_documents
            )

            save_document_cache(
                document_id=
                    document_id,

                embeddings=
                    embeddings,

                documents=
                    cached_documents
            )

            print(
                "Belge cache kaydedildi."
            )

        # ====================================================
        # GLOBAL MERGE
        # ====================================================

        global_embeddings.append(
            embeddings
        )

        global_documents.extend(
            cached_documents
        )

        # ====================================================
        # NEW STATE
        # ====================================================

        new_state_documents[
            document_id
        ] = {

            "file_name":
                file_name,

            # Legacy compatibility
            "file_hash":
                current_file_hash,

            # Explicit V6.1 terminology
            "content_hash":
                current_file_hash,

            "processing_hash":
                current_processing_hash,

            "metadata_hash":
                current_metadata_hash,

            "version":
                document.get(
                    "version"
                ),

            "active":
                document.get(
                    "active",
                    True
                ),

            "status":
                document.get(
                    "status"
                ),

            "ingest_enabled":
                (
                    document
                    .get(
                        "ingest",
                        {}
                    )
                    .get(
                        "enabled",
                        True
                    )
                ),

            "chunk_count":
                len(
                    cached_documents
                ),

            "last_change_type":
                change_status
        }

    # ========================================================
    # 7. GLOBAL INDEX
    # ========================================================

    print(
        "\n======================================"
    )

    print(
        " GLOBAL INDEX OLUŞTURULUYOR"
    )

    print(
        "======================================"
    )

    global_index = (
        build_global_index(
            global_embeddings
        )
    )

    save_global_index(
        index=
            global_index,

        documents=
            global_documents,

        pipeline_config=
            pipeline_config,

        pipeline_signature=
            pipeline_signature
    )

    # ========================================================
    # 8. STATE SAVE
    # ========================================================

    new_state = {

        "runtime_ingest_version":
            DISPLAY_VERSION,

        "pipeline_signature":
            pipeline_signature,

        "pipeline":
            pipeline_config,

        "documents":
            new_state_documents
    }

    save_json(
        STATE_PATH,
        new_state
    )

    # ========================================================
    # 9. SUMMARY
    # ========================================================

    print(
        "\n======================================"
    )

    print(
        " INGEST TAMAMLANDI"
    )

    print(
        "======================================"
    )

    print(
        "Aktif belge:",
        len(
            included_documents
        )
    )

    print(
        "Toplam chunk:",
        len(
            global_documents
        )
    )

    print(
        "FAISS kayıt:",
        global_index.ntotal
    )

    print(
        "Embedding dimension:",
        global_index.d
    )

    print(
        "\nDosyalar:"
    )

    print(
        "-",
        FAISS_PATH
    )

    print(
        "-",
        DOCUMENTS_PATH
    )

    print(
        "-",
        CONFIG_PATH
    )

    print(
        "-",
        STATE_PATH
    )

    print(
        "\nPipeline signature:"
    )

    print(
        pipeline_signature
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_ingest()