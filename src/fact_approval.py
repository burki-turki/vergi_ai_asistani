# ============================================================
# VERGİ AI - FACT APPROVAL / PROMOTION V1
#
# AMAÇ:
#
# LLM tarafından üretilmiş ve validator'dan geçmiş
# *.json.pending extraction çıktısını insan onayı sonrasında
# canonical facts.json haline getirmek.
#
#
# PIPELINE:
#
# facts_llm_*.json.pending
#        ↓
# Case Fact Validator
#        ↓
# Human Review
#        ↓
# --approve
#        ↓
# mevcut facts.json -> history/
#        ↓
# yeni facts.json
#        ↓
# approval audit record
#
#
# KRİTİK PRENSİP:
#
# Approval:
#   extraction'ın kaynak belgeyi kabul edilebilir şekilde
#   temsil ettiğinin insan tarafından onaylanmasıdır.
#
# Approval:
#   maddi gerçeğin doğrulandığı anlamına GELMEZ.
#
# Bu nedenle fact verification_state değerleri değiştirilmez.
# ============================================================


import argparse
import hashlib
import json
import os
import shutil

from datetime import datetime
from pathlib import Path

from case_fact_validator import (
    validate_fact_extraction,
)


# ============================================================
# VERSION
# ============================================================

FACT_APPROVAL_VERSION = "1"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DATA_DIR = (
    BASE_DIR
    / "data"
)

DEFAULT_PENDING_PATH = (
    DATA_DIR
    / "cases"
    / "case_0001"
    / "documents"
    / "vir_001"
    / "extractions"
    / "facts_llm_v1_1.json.pending"
)


# ============================================================
# JSON
# ============================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(file)


def write_json_atomic(
    path,
    data,
):

    path = Path(
        path
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = path.with_name(
        path.name + ".tmp"
    )

    with open(
        temp_path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    os.replace(
        temp_path,
        path,
    )


# ============================================================
# HASH
# ============================================================

def sha256_file(path):

    digest = hashlib.sha256()

    with open(
        path,
        "rb",
    ) as file:

        while True:

            chunk = file.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


# ============================================================
# TIME
# ============================================================

def now_iso():

    return (
        datetime.now()
        .astimezone()
        .isoformat()
    )


def now_stamp():

    return (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )


# ============================================================
# CONTEXT PATHS
# ============================================================

def resolve_paths(
    pending_path,
    extraction,
):

    case_id = extraction.get(
        "case_id"
    )

    document_id = extraction.get(
        "source_document_id"
    )

    expected_extractions_dir = (
        DATA_DIR
        / "cases"
        / case_id
        / "documents"
        / document_id
        / "extractions"
    ).resolve()

    actual_extractions_dir = (
        Path(
            pending_path
        )
        .resolve()
        .parent
    )

    if (
        actual_extractions_dir
        != expected_extractions_dir
    ):

        raise ValueError(
            "Pending extraction yanlış klasörde.\n"
            f"Beklenen: {expected_extractions_dir}\n"
            f"Gerçek: {actual_extractions_dir}"
        )

    canonical_path = (
        expected_extractions_dir
        / "facts.json"
    )

    history_dir = (
        expected_extractions_dir
        / "history"
    )

    reviews_dir = (
        expected_extractions_dir
        / "reviews"
    )

    return {
        "extractions_dir":
            expected_extractions_dir,

        "canonical_path":
            canonical_path,

        "history_dir":
            history_dir,

        "reviews_dir":
            reviews_dir,
    }


# ============================================================
# PENDING VALIDATION
# ============================================================

def validate_pending(
    pending_path,
):

    pending_path = Path(
        pending_path
    ).resolve()

    if not pending_path.exists():

        raise FileNotFoundError(
            "Pending extraction bulunamadı:\n"
            f"{pending_path}"
        )

    if not pending_path.name.endswith(
        ".pending"
    ):

        raise ValueError(
            "Approval yalnızca .pending "
            "dosyaları üzerinde çalışabilir."
        )

    validation = (
        validate_fact_extraction(
            facts_path=pending_path,
            raise_on_error=True,
        )
    )

    extraction = load_json(
        pending_path
    )

    if (
        extraction.get(
            "status"
        )
        != "completed"
    ):

        raise ValueError(
            "Yalnızca status=completed "
            "extraction promote edilebilir."
        )

    facts = extraction.get(
        "facts",
        [],
    )

    if not facts:

        raise ValueError(
            "Fact bulunmayan extraction "
            "promote edilemez."
        )

    extractor = extraction.get(
        "extractor",
        {},
    )

    method = extractor.get(
        "method"
    )

    # --------------------------------------------------------
    # LLM kendi fact'ini verified yapamaz.
    # --------------------------------------------------------

    if method in {
        "llm",
        "hybrid",
    }:

        for fact in facts:

            if (
                fact.get(
                    "verification_state"
                )
                != "unverified"
            ):

                raise ValueError(
                    "LLM extraction içinde "
                    "verification_state=unverified "
                    "olmayan fact bulundu: "
                    f"{fact.get('fact_id')}"
                )

    return (
        extraction,
        validation,
    )


# ============================================================
# BACKUP CURRENT CANONICAL
# ============================================================

def backup_current_canonical(
    canonical_path,
    history_dir,
):

    canonical_path = Path(
        canonical_path
    )

    if not canonical_path.exists():

        return None

    history_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    current_hash = (
        sha256_file(
            canonical_path
        )
    )

    backup_name = (
        "facts_before_promotion_"
        f"{now_stamp()}_"
        f"{current_hash[:8]}.json"
    )

    backup_path = (
        history_dir
        / backup_name
    )

    shutil.copy2(
        canonical_path,
        backup_path,
    )

    return backup_path


# ============================================================
# BUILD CANONICAL
# ============================================================

def build_canonical(
    extraction,
):

    canonical = json.loads(
        json.dumps(
            extraction,
            ensure_ascii=False,
        )
    )

    canonical[
        "notes"
    ] = (
        "Fact Approval / Promotion V1 ile "
        "human-reviewed canonical extraction "
        "olarak promote edilmiştir. "
        "Bu onay fact'lerin maddi gerçeklik bakımından "
        "verified olduğu anlamına gelmez; "
        "verification_state alanları ayrıca korunur."
    )

    return canonical


# ============================================================
# APPROVAL RECORD
# ============================================================

def build_approval_record(
    extraction,
    pending_path,
    pending_hash,
    canonical_path,
    canonical_hash,
    reviewer_ref,
    review_note,
    backup_path,
):

    extraction_id = extraction.get(
        "extraction_id"
    )

    return {
        "schema_version":
            1,

        "approval_id":
            (
                "approval_"
                f"{extraction_id}_"
                f"{now_stamp()}"
            ),

        "approval_version":
            FACT_APPROVAL_VERSION,

        "decision":
            "approved_for_canonical_use",

        "approval_scope":
            "extraction_accuracy_review",

        "case_id":
            extraction.get(
                "case_id"
            ),

        "source_document_id":
            extraction.get(
                "source_document_id"
            ),

        "extraction_id":
            extraction_id,

        "fact_count":
            len(
                extraction.get(
                    "facts",
                    [],
                )
            ),

        "reviewer_ref":
            reviewer_ref,

        "reviewed_at":
            now_iso(),

        "review_note":
            review_note,

        "source_pending_file":
            str(
                pending_path
            ),

        "source_pending_sha256":
            pending_hash,

        "canonical_file":
            str(
                canonical_path
            ),

        "canonical_sha256":
            canonical_hash,

        "previous_canonical_backup":
            (
                str(
                    backup_path
                )
                if backup_path
                else None
            ),

        "verification_semantics":
            (
                "Approval extraction doğruluğunu "
                "temsil eder; fact verification_state "
                "değerlerini değiştirmez."
            )
    }


# ============================================================
# REVIEW ONLY
# ============================================================

def review_pending(
    pending_path,
):

    extraction, validation = (
        validate_pending(
            pending_path
        )
    )

    paths = resolve_paths(
        pending_path,
        extraction,
    )

    pending_hash = sha256_file(
        pending_path
    )

    return {
        "extraction":
            extraction,

        "validation":
            validation,

        "paths":
            paths,

        "pending_hash":
            pending_hash,
    }


# ============================================================
# PROMOTION
# ============================================================

def promote(
    pending_path,
    reviewer_ref,
    review_note,
):

    review = review_pending(
        pending_path
    )

    extraction = review[
        "extraction"
    ]

    paths = review[
        "paths"
    ]

    pending_hash = review[
        "pending_hash"
    ]

    canonical_path = paths[
        "canonical_path"
    ]

    history_dir = paths[
        "history_dir"
    ]

    reviews_dir = paths[
        "reviews_dir"
    ]

    # ========================================================
    # BACKUP CURRENT FACTS.JSON
    # ========================================================

    backup_path = (
        backup_current_canonical(
            canonical_path,
            history_dir,
        )
    )

    # ========================================================
    # BUILD NEW CANONICAL
    # ========================================================

    canonical = build_canonical(
        extraction
    )

    write_json_atomic(
        canonical_path,
        canonical,
    )

    # ========================================================
    # VALIDATE CANONICAL AFTER WRITE
    # ========================================================

    try:

        validation = (
            validate_fact_extraction(
                facts_path=canonical_path,
                raise_on_error=True,
            )
        )

    except Exception:

        # ----------------------------------------------------
        # Rollback
        # ----------------------------------------------------

        if backup_path:

            shutil.copy2(
                backup_path,
                canonical_path,
            )

        else:

            if canonical_path.exists():

                canonical_path.unlink()

        raise

    canonical_hash = sha256_file(
        canonical_path
    )

    # ========================================================
    # AUDIT RECORD
    # ========================================================

    approval_record = (
        build_approval_record(
            extraction=extraction,
            pending_path=Path(
                pending_path
            ).resolve(),
            pending_hash=pending_hash,
            canonical_path=canonical_path,
            canonical_hash=canonical_hash,
            reviewer_ref=reviewer_ref,
            review_note=review_note,
            backup_path=backup_path,
        )
    )

    reviews_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    approval_path = (
        reviews_dir
        / (
            extraction[
                "extraction_id"
            ]
            + ".approval.json"
        )
    )

    write_json_atomic(
        approval_path,
        approval_record,
    )

    return {
        "canonical_path":
            canonical_path,

        "backup_path":
            backup_path,

        "approval_path":
            approval_path,

        "validation":
            validation,

        "fact_count":
            len(
                canonical.get(
                    "facts",
                    [],
                )
            ),

        "extraction_id":
            canonical.get(
                "extraction_id"
            ),
    }


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Fact Approval / Promotion V1"
        )
    )

    parser.add_argument(
        "--pending",
        default=str(
            DEFAULT_PENDING_PATH
        ),
    )

    parser.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Pending extraction'ı canonical "
            "facts.json olarak promote eder."
        ),
    )

    parser.add_argument(
        "--reviewer",
        default="human_review",
    )

    parser.add_argument(
        "--note",
        default=(
            "Fact Extraction Engine V1.1 çıktısı "
            "insan tarafından incelendi."
        ),
    )

    args = parser.parse_args()

    pending_path = Path(
        args.pending
    )

    print()
    print(
        "======================================"
    )

    print(
        " VERGİ AI - FACT APPROVAL V1"
    )

    print(
        "======================================"
    )

    review = review_pending(
        pending_path
    )

    extraction = review[
        "extraction"
    ]

    print()
    print(
        "Extraction ID:",
        extraction[
            "extraction_id"
        ],
    )

    print(
        "Case ID:",
        extraction[
            "case_id"
        ],
    )

    print(
        "Source document:",
        extraction[
            "source_document_id"
        ],
    )

    print(
        "Fact sayısı:",
        len(
            extraction[
                "facts"
            ]
        ),
    )

    print(
        "Validator:",
        "PASS",
    )

    print(
        "SHA256:",
        review[
            "pending_hash"
        ],
    )

    if not args.approve:

        print()
        print(
            "REVIEW MODE"
        )

        print(
            "Promotion yapılmadı."
        )

        print()
        print(
            "Onaylamak için:"
        )

        print(
            "python src\\fact_approval.py --approve"
        )

        print()
        print(
            "======================================"
        )

        print(
            " FACT APPROVAL V1: READY"
        )

        print(
            "======================================"
        )

        return

    # ========================================================
    # APPROVE
    # ========================================================

    result = promote(
        pending_path=pending_path,
        reviewer_ref=args.reviewer,
        review_note=args.note,
    )

    print()
    print(
        "PROMOTION TAMAMLANDI"
    )

    print(
        "Extraction ID:",
        result[
            "extraction_id"
        ],
    )

    print(
        "Fact sayısı:",
        result[
            "fact_count"
        ],
    )

    print(
        "Canonical validator:",
        "PASS",
    )

    print()
    print(
        "Canonical:"
    )

    print(
        result[
            "canonical_path"
        ]
    )

    if result[
        "backup_path"
    ]:

        print()
        print(
            "Önceki canonical arşivlendi:"
        )

        print(
            result[
                "backup_path"
            ]
        )

    print()
    print(
        "Approval audit:"
    )

    print(
        result[
            "approval_path"
        ]
    )

    print()
    print(
        "NOT:"
    )

    print(
        "Fact'lerin verification_state "
        "değerleri değiştirilmedi."
    )

    print(
        "Approval yalnızca extraction'ın "
        "canonical kullanımını onayladı."
    )

    print()
    print(
        "======================================"
    )

    print(
        " FACT APPROVAL V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    main()