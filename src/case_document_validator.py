# ============================================================
# VERGİ AI - CASE DOCUMENT VALIDATOR V1
#
# AMAÇ:
#
# Case Document Layer için:
#
# 1. case_document.schema.json doğrulaması
# 2. case.json <-> document.json çapraz bütünlüğü
# 3. document_id benzersizliği
# 4. case_id eşleşmesi
# 5. case_document_refs bütünlüğü
# 6. party referansları
# 7. document relation referansları
# 8. file metadata/path mantığı
# 9. processing state mantığı
# 10. verification mantığı
#
#
# ÖNEMLİ:
#
# V1 gerçek PDF dosyasının varlığını ZORUNLU tutmaz.
#
# Çünkü metadata kaydı fiziksel dosyadan önce oluşturulabilir.
# Fiziksel dosya doğrulaması Document Intake / Ingest
# aşamasında ayrı ele alınacaktır.
# ============================================================


import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


# ============================================================
# VERSION
# ============================================================

CASE_DOCUMENT_VALIDATOR_VERSION = "1"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

CASE_SCHEMA_PATH = DATA_DIR / "case.schema.json"

CASE_DOCUMENT_SCHEMA_PATH = DATA_DIR / "case_document.schema.json"

DEFAULT_CASE_DIR = (
    DATA_DIR
    / "cases"
    / "case_0001"
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


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_json_schema(
    data,
    schema,
    label,
):
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    errors = sorted(
        validator.iter_errors(data),
        key=lambda error: list(error.path),
    )

    messages = []

    for error in errors:
        path = ".".join(
            str(part)
            for part in error.path
        )

        if not path:
            path = "root"

        messages.append(
            f"{label}.{path}: {error.message}"
        )

    return messages


# ============================================================
# LOAD CASE DOCUMENTS
# ============================================================

def load_case_documents(
    case_dir,
):
    documents_dir = (
        case_dir
        / "documents"
    )

    if not documents_dir.exists():
        return []

    document_files = sorted(
        documents_dir.glob(
            "*/document.json"
        )
    )

    documents = []

    for document_path in document_files:
        data = load_json(
            document_path
        )

        documents.append(
            {
                "path": document_path,
                "data": data,
            }
        )

    return documents


# ============================================================
# UNIQUE DOCUMENT IDS
# ============================================================

def validate_unique_document_ids(
    documents,
):
    errors = []

    seen = {}

    for item in documents:
        document = item["data"]

        document_id = document.get(
            "document_id"
        )

        if document_id in seen:
            errors.append(
                "Tekrarlanan document_id: "
                f"{document_id} "
                f"({seen[document_id]} ve "
                f"{item['path']})"
            )

        else:
            seen[document_id] = (
                item["path"]
            )

    return errors


# ============================================================
# CASE ID
# ============================================================

def validate_case_ids(
    case_data,
    documents,
):
    errors = []

    case_id = case_data.get(
        "case_id"
    )

    for item in documents:
        document = item["data"]

        document_id = document.get(
            "document_id"
        )

        document_case_id = document.get(
            "case_id"
        )

        if document_case_id != case_id:
            errors.append(
                f"{document_id}: "
                f"case_id={document_case_id} "
                f"ancak ana case_id={case_id}"
            )

    return errors


# ============================================================
# CASE DOCUMENT REFERENCE INTEGRITY
# ============================================================

def validate_case_document_refs(
    case_data,
    documents,
):
    errors = []

    warnings = []

    case_refs = case_data.get(
        "case_document_refs",
        [],
    )

    referenced_ids = {
        ref.get("document_id")
        for ref in case_refs
    }

    physical_metadata_ids = {
        item["data"].get("document_id")
        for item in documents
    }

    # ========================================================
    # CASE REFERENCES WITHOUT DOCUMENT.JSON
    # ========================================================

    for document_id in sorted(
        referenced_ids
        - physical_metadata_ids
    ):
        errors.append(
            "case.json içinde referans verilen "
            "belge için document.json bulunamadı: "
            f"{document_id}"
        )

    # ========================================================
    # DOCUMENT.JSON WITHOUT CASE REFERENCE
    # ========================================================

    for document_id in sorted(
        physical_metadata_ids
        - referenced_ids
    ):
        warnings.append(
            "document.json mevcut ancak "
            "case.json.case_document_refs içinde "
            f"referans yok: {document_id}"
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# PARTY REFERENCES
# ============================================================

def validate_party_references(
    case_data,
    documents,
):
    errors = []

    parties = case_data.get(
        "parties",
        [],
    )

    party_ids = {
        party.get("party_id")
        for party in parties
    }

    for item in documents:
        document = item["data"]

        document_id = document.get(
            "document_id"
        )

        issuer_party_id = document.get(
            "issuer_party_id"
        )

        if (
            issuer_party_id is not None
            and issuer_party_id not in party_ids
        ):
            errors.append(
                f"{document_id}: "
                "issuer_party_id case.parties "
                "içinde bulunamadı: "
                f"{issuer_party_id}"
            )

        for recipient_party_id in document.get(
            "recipient_party_ids",
            [],
        ):
            if recipient_party_id not in party_ids:
                errors.append(
                    f"{document_id}: "
                    "recipient_party_id case.parties "
                    "içinde bulunamadı: "
                    f"{recipient_party_id}"
                )

    return errors


# ============================================================
# DOCUMENT RELATIONS
# ============================================================

def validate_document_relations(
    documents,
):
    errors = []

    warnings = []

    document_ids = {
        item["data"].get(
            "document_id"
        )
        for item in documents
    }

    for item in documents:
        document = item["data"]

        source_document_id = (
            document.get(
                "document_id"
            )
        )

        seen_relations = set()

        for relation in document.get(
            "relations",
            [],
        ):
            relation_type = relation.get(
                "type"
            )

            target_document_id = relation.get(
                "document_id"
            )

            # =================================================
            # SELF RELATION
            # =================================================

            if (
                target_document_id
                == source_document_id
            ):
                errors.append(
                    f"{source_document_id}: "
                    "belge kendisiyle relation "
                    "kuramaz."
                )

            # =================================================
            # TARGET EXISTS
            # =================================================

            if (
                target_document_id
                not in document_ids
            ):
                errors.append(
                    f"{source_document_id}: "
                    f"{relation_type} relation hedefi "
                    "bulunamadı: "
                    f"{target_document_id}"
                )

            # =================================================
            # DUPLICATE RELATION
            # =================================================

            relation_key = (
                relation_type,
                target_document_id,
            )

            if relation_key in seen_relations:
                warnings.append(
                    f"{source_document_id}: "
                    "tekrarlanan relation: "
                    f"{relation_type} -> "
                    f"{target_document_id}"
                )

            seen_relations.add(
                relation_key
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# FILE PATH LOGIC
# ============================================================

def validate_file_paths(
    case_data,
    documents,
):
    errors = []

    warnings = []

    case_id = case_data.get(
        "case_id"
    )

    for item in documents:
        document = item["data"]

        document_id = document.get(
            "document_id"
        )

        file_info = document.get(
            "file",
            {},
        )

        file_name = file_info.get(
            "file_name"
        )

        relative_path = file_info.get(
            "relative_path"
        )

        expected_relative_path = (
            f"cases/{case_id}/documents/"
            f"{document_id}/{file_name}"
        )

        normalized_relative_path = (
            relative_path.replace(
                "\\",
                "/",
            )
            if isinstance(
                relative_path,
                str,
            )
            else relative_path
        )

        if (
            normalized_relative_path
            != expected_relative_path
        ):
            errors.append(
                f"{document_id}: "
                "file.relative_path beklenen "
                "yapıyla eşleşmiyor. "
                f"Beklenen={expected_relative_path}, "
                f"Gerçek={relative_path}"
            )

        # ====================================================
        # PHYSICAL FILE
        #
        # V1'DE SADECE BİLGİ AMAÇLI.
        # DOSYA YOKSA HATA/UYARI ÜRETMİYORUZ.
        # ====================================================

    return (
        errors,
        warnings,
    )


# ============================================================
# DIRECTORY / DOCUMENT ID LOGIC
# ============================================================

def validate_directory_names(
    documents,
):
    errors = []

    for item in documents:
        document = item["data"]

        document_id = document.get(
            "document_id"
        )

        folder_name = (
            item["path"]
            .parent
            .name
        )

        if folder_name != document_id:
            errors.append(
                f"{document_id}: "
                "document.json klasörü ile "
                "document_id eşleşmiyor. "
                f"Klasör={folder_name}"
            )

    return errors


# ============================================================
# PROCESSING STATE
# ============================================================

def validate_processing_logic(
    documents,
):
    errors = []

    warnings = []

    for item in documents:
        document = item["data"]

        document_id = document.get(
            "document_id"
        )

        processing = document.get(
            "processing",
            {},
        )

        ingest_enabled = processing.get(
            "ingest_enabled"
        )

        ocr_required = processing.get(
            "ocr_required"
        )

        ocr_completed = processing.get(
            "ocr_completed"
        )

        extraction_status = processing.get(
            "text_extraction_status"
        )

        index_status = processing.get(
            "index_status"
        )

        extracted_text_path = processing.get(
            "extracted_text_path"
        )

        parser_version = processing.get(
            "parser_version"
        )

        # ====================================================
        # OCR
        # ====================================================

        if (
            ocr_required is False
            and ocr_completed is True
        ):
            warnings.append(
                f"{document_id}: "
                "ocr_required=false ancak "
                "ocr_completed=true."
            )

        # ====================================================
        # INDEXED WITHOUT TEXT
        # ====================================================

        if (
            index_status == "indexed"
            and extraction_status
            not in {
                "completed",
                "partial",
            }
        ):
            errors.append(
                f"{document_id}: "
                "index_status=indexed ancak "
                "text_extraction_status="
                f"{extraction_status}"
            )

        # ====================================================
        # TEXT PATH
        # ====================================================

        if (
            extraction_status
            in {
                "completed",
                "partial",
            }
            and not extracted_text_path
        ):
            warnings.append(
                f"{document_id}: "
                f"text_extraction_status="
                f"{extraction_status} ancak "
                "extracted_text_path boş."
            )

        # ====================================================
        # PARSER VERSION
        # ====================================================

        if (
            extraction_status
            in {
                "completed",
                "partial",
            }
            and not parser_version
        ):
            warnings.append(
                f"{document_id}: "
                "metin işlenmiş ancak "
                "parser_version boş."
            )

        # ====================================================
        # INGEST DISABLED BUT INDEXED
        # ====================================================

        if (
            ingest_enabled is False
            and index_status == "indexed"
        ):
            warnings.append(
                f"{document_id}: "
                "ingest_enabled=false ancak "
                "index_status=indexed."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# VERIFICATION LOGIC
# ============================================================

def validate_verification_logic(
    documents,
):
    errors = []

    warnings = []

    for item in documents:
        document = item["data"]

        document_id = document.get(
            "document_id"
        )

        document_state = document.get(
            "verification_state"
        )

        dates = document.get(
            "dates",
            [],
        )

        reference_numbers = document.get(
            "reference_numbers",
            [],
        )

        # ====================================================
        # VERIFIED DOCUMENT
        # ====================================================

        if document_state == "verified":

            verified_evidence_count = 0

            for date_item in dates:
                if (
                    date_item.get(
                        "verification_state"
                    )
                    == "verified"
                ):
                    verified_evidence_count += 1

            for reference_item in reference_numbers:
                if (
                    reference_item.get(
                        "verification_state"
                    )
                    == "verified"
                ):
                    verified_evidence_count += 1

            if verified_evidence_count == 0:
                warnings.append(
                    f"{document_id}: "
                    "document verification_state="
                    "verified ancak tarih veya "
                    "referans numarası seviyesinde "
                    "verified kayıt bulunmuyor."
                )

    return (
        errors,
        warnings,
    )


# ============================================================
# CASE REF / CATEGORY COMPATIBILITY
# ============================================================

def validate_reference_category_compatibility(
    case_data,
    documents,
):
    errors = []

    warnings = []

    document_map = {
        item["data"].get(
            "document_id"
        ): item["data"]
        for item in documents
    }

    compatibility = {

        "audit_report": {
            "audit",
        },

        "technical_report": {
            "audit",
            "expert",
        },

        "notice": {
            "administrative_action",
            "notification",
        },

        "payment_order": {
            "administrative_action",
            "notification",
        },

        "evidence": {
            "evidence",
            "financial",
            "correspondence",
        },

        "petition": {
            "litigation",
        },

        "defense": {
            "litigation",
        },

        "court_decision": {
            "litigation",
        },

        "expert_report": {
            "expert",
            "litigation",
        },

        "correspondence": {
            "correspondence",
        },

        "primary_action": {
            "administrative_action",
            "notification",
        },

        "other": {
            "administrative_action",
            "audit",
            "litigation",
            "evidence",
            "financial",
            "correspondence",
            "notification",
            "expert",
            "other",
        },
    }

    for ref in case_data.get(
        "case_document_refs",
        [],
    ):
        document_id = ref.get(
            "document_id"
        )

        relation_type = ref.get(
            "relation_type"
        )

        document = document_map.get(
            document_id
        )

        if document is None:
            continue

        document_category = (
            document.get(
                "document_category"
            )
        )

        allowed_categories = (
            compatibility.get(
                relation_type
            )
        )

        if (
            allowed_categories is not None
            and document_category
            not in allowed_categories
        ):
            warnings.append(
                f"{document_id}: "
                "case relation_type="
                f"{relation_type} ile "
                "document_category="
                f"{document_category} "
                "beklenen eşleşmede değil."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# CASE DOCUMENT COUNT
# ============================================================

def count_primary_documents(
    case_data,
):
    return sum(
        1
        for ref in case_data.get(
            "case_document_refs",
            [],
        )
        if ref.get(
            "primary"
        ) is True
    )


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_case_documents(
    case_dir=None,
    raise_on_error=True,
):
    if case_dir is None:
        case_dir = DEFAULT_CASE_DIR

    case_dir = Path(
        case_dir
    ).resolve()

    case_path = (
        case_dir
        / "case.json"
    )

    # ========================================================
    # REQUIRED FILES
    # ========================================================

    if not CASE_DOCUMENT_SCHEMA_PATH.exists():
        raise FileNotFoundError(
            "case_document.schema.json bulunamadı:\n"
            f"{CASE_DOCUMENT_SCHEMA_PATH}"
        )

    if not case_path.exists():
        raise FileNotFoundError(
            "case.json bulunamadı:\n"
            f"{case_path}"
        )

    # ========================================================
    # LOAD
    # ========================================================

    case_document_schema = load_json(
        CASE_DOCUMENT_SCHEMA_PATH
    )

    case_data = load_json(
        case_path
    )

    documents = load_case_documents(
        case_dir
    )

    errors = []

    warnings = []

    # ========================================================
    # NO DOCUMENTS
    # ========================================================

    if not documents:
        errors.append(
            "Case için hiçbir document.json bulunamadı."
        )

    # ========================================================
    # SCHEMA VALIDATION
    # ========================================================

    for item in documents:
        document = item["data"]

        document_id = (
            document.get(
                "document_id"
            )
            or item["path"].parent.name
        )

        errors.extend(
            validate_json_schema(
                document,
                case_document_schema,
                document_id,
            )
        )

    # Schema hatası varsa çapraz kontroller yanıltıcı olabilir.
    if errors:
        result = {
            "valid": False,
            "errors": errors,
            "warnings": warnings,
            "case_id": case_data.get(
                "case_id"
            ),
            "document_count": len(
                documents
            ),
        }

        if raise_on_error:
            raise ValueError(
                "\nCASE DOCUMENT VALIDATION HATASI\n"
                + "\n".join(
                    f"- {error}"
                    for error in errors
                )
            )

        return result

    # ========================================================
    # UNIQUE IDS
    # ========================================================

    errors.extend(
        validate_unique_document_ids(
            documents
        )
    )

    # ========================================================
    # CASE IDS
    # ========================================================

    errors.extend(
        validate_case_ids(
            case_data,
            documents,
        )
    )

    # ========================================================
    # CASE REFERENCES
    # ========================================================

    (
        ref_errors,
        ref_warnings,
    ) = validate_case_document_refs(
        case_data,
        documents,
    )

    errors.extend(
        ref_errors
    )

    warnings.extend(
        ref_warnings
    )

    # ========================================================
    # PARTY REFERENCES
    # ========================================================

    errors.extend(
        validate_party_references(
            case_data,
            documents,
        )
    )

    # ========================================================
    # DOCUMENT RELATIONS
    # ========================================================

    (
        relation_errors,
        relation_warnings,
    ) = validate_document_relations(
        documents
    )

    errors.extend(
        relation_errors
    )

    warnings.extend(
        relation_warnings
    )

    # ========================================================
    # FILE PATH
    # ========================================================

    (
        path_errors,
        path_warnings,
    ) = validate_file_paths(
        case_data,
        documents,
    )

    errors.extend(
        path_errors
    )

    warnings.extend(
        path_warnings
    )

    # ========================================================
    # DIRECTORY NAMES
    # ========================================================

    errors.extend(
        validate_directory_names(
            documents
        )
    )

    # ========================================================
    # PROCESSING
    # ========================================================

    (
        processing_errors,
        processing_warnings,
    ) = validate_processing_logic(
        documents
    )

    errors.extend(
        processing_errors
    )

    warnings.extend(
        processing_warnings
    )

    # ========================================================
    # VERIFICATION
    # ========================================================

    (
        verification_errors,
        verification_warnings,
    ) = validate_verification_logic(
        documents
    )

    errors.extend(
        verification_errors
    )

    warnings.extend(
        verification_warnings
    )

    # ========================================================
    # REF / CATEGORY COMPATIBILITY
    # ========================================================

    (
        category_errors,
        category_warnings,
    ) = validate_reference_category_compatibility(
        case_data,
        documents,
    )

    errors.extend(
        category_errors
    )

    warnings.extend(
        category_warnings
    )

    # ========================================================
    # RESULT
    # ========================================================

    valid = len(
        errors
    ) == 0

    result = {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "case_id": case_data.get(
            "case_id"
        ),
        "document_count": len(
            documents
        ),
        "case_document_ref_count": len(
            case_data.get(
                "case_document_refs",
                [],
            )
        ),
        "primary_document_count":
            count_primary_documents(
                case_data
            ),
    }

    if (
        not valid
        and raise_on_error
    ):
        raise ValueError(
            "\nCASE DOCUMENT VALIDATION HATASI\n"
            + "\n".join(
                f"- {error}"
                for error in errors
            )
        )

    return result


# ============================================================
# CLI
# ============================================================

def main():

    case_dir = (
        Path(
            sys.argv[1]
        )
        if len(sys.argv) > 1
        else DEFAULT_CASE_DIR
    )

    print()
    print(
        "======================================"
    )
    print(
        " VERGİ AI - CASE DOCUMENT VALIDATOR V1"
    )
    print(
        "======================================"
    )

    print()
    print(
        "Case directory:"
    )
    print(
        Path(case_dir).resolve()
    )

    try:
        result = validate_case_documents(
            case_dir=case_dir,
            raise_on_error=True,
        )

        print()
        print(
            "CASE DOCUMENT LAYER GEÇERLİ"
        )

        print(
            "Case ID:",
            result["case_id"],
        )

        print(
            "Document sayısı:",
            result["document_count"],
        )

        print(
            "Case document ref:",
            result[
                "case_document_ref_count"
            ],
        )

        print(
            "Primary document:",
            result[
                "primary_document_count"
            ],
        )

        if result["warnings"]:

            print()
            print(
                "UYARILAR:"
            )

            for warning in result[
                "warnings"
            ]:
                print(
                    "-",
                    warning,
                )

        else:

            print()
            print(
                "Uyarı yok."
            )

        print()
        print(
            "======================================"
        )
        print(
            " CASE DOCUMENT VALIDATOR V1: PASS"
        )
        print(
            "======================================"
        )

    except Exception as error:

        print()
        print(
            "CASE DOCUMENT LAYER GEÇERSİZ"
        )

        print(
            error
        )

        raise


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    main()