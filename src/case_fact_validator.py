# ============================================================
# VERGİ AI - CASE FACT VALIDATOR V1
#
# AMAÇ:
#
# Fact Extraction Layer için:
#
# 1. case_fact_extraction.schema.json doğrulaması
# 2. case_id çapraz doğrulaması
# 3. source_document_id doğrulaması
# 4. extraction dosya yolu / belge eşleşmesi
# 5. unique fact_id kontrolü
# 6. party referansları
# 7. dispute item referansları
# 8. document referansları
# 9. structured_value bütünlüğü
# 10. fact_kind / structured_value uyumu
# 11. source locator / evidence mantığı
# 12. verification mantığı
# 13. extractor / status mantığı
#
#
# KRİTİK PRENSİP:
#
# BELGEDEKİ İDDİA
#       !=
# DOĞRULANMIŞ MADDİ GERÇEK
#
# confidence:
#     extraction doğruluğu / model güveni
#
# verification_state:
#     olgunun doğrulanma durumu
#
# Bu validator hukuki değerlendirme üretmez.
# ============================================================


import json
import sys
from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


# ============================================================
# VERSION
# ============================================================

CASE_FACT_VALIDATOR_VERSION = "1"


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

FACT_SCHEMA_PATH = (
    DATA_DIR
    / "case_fact_extraction.schema.json"
)

DEFAULT_FACTS_PATH = (
    DATA_DIR
    / "cases"
    / "case_0001"
    / "documents"
    / "vir_001"
    / "extractions"
    / "facts.json"
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

def validate_schema(
    data,
    schema,
):
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    errors = sorted(
        validator.iter_errors(data),
        key=lambda error: list(
            error.path
        ),
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
            f"{path}: {error.message}"
        )

    return messages


# ============================================================
# PATH RESOLUTION
# ============================================================

def resolve_context_paths(
    facts_path,
):
    facts_path = Path(
        facts_path
    ).resolve()

    # Beklenen:
    #
    # case_0001/
    #   documents/
    #     vir_001/
    #       extractions/
    #         facts.json

    extractions_dir = facts_path.parent

    document_dir = (
        extractions_dir.parent
    )

    documents_dir = (
        document_dir.parent
    )

    case_dir = (
        documents_dir.parent
    )

    case_path = (
        case_dir
        / "case.json"
    )

    source_document_path = (
        document_dir
        / "document.json"
    )

    return {
        "facts_path":
            facts_path,

        "extractions_dir":
            extractions_dir,

        "document_dir":
            document_dir,

        "documents_dir":
            documents_dir,

        "case_dir":
            case_dir,

        "case_path":
            case_path,

        "source_document_path":
            source_document_path,
    }


# ============================================================
# LOAD CASE DOCUMENTS
# ============================================================

def load_case_documents(
    documents_dir,
):
    documents = {}

    if not documents_dir.exists():
        return documents

    for path in sorted(
        documents_dir.glob(
            "*/document.json"
        )
    ):
        data = load_json(
            path
        )

        document_id = data.get(
            "document_id"
        )

        if document_id:
            documents[
                document_id
            ] = {
                "data": data,
                "path": path,
            }

    return documents


# ============================================================
# UNIQUE FACT IDS
# ============================================================

def validate_unique_fact_ids(
    extraction,
):
    errors = []

    seen = set()

    for fact in extraction.get(
        "facts",
        [],
    ):
        fact_id = fact.get(
            "fact_id"
        )

        if fact_id in seen:
            errors.append(
                "Tekrarlanan fact_id: "
                f"{fact_id}"
            )

        seen.add(
            fact_id
        )

    return errors


# ============================================================
# CASE / DOCUMENT CONTEXT
# ============================================================

def validate_context(
    extraction,
    case_data,
    source_document,
    paths,
):
    errors = []

    extraction_case_id = (
        extraction.get(
            "case_id"
        )
    )

    case_id = case_data.get(
        "case_id"
    )

    source_document_id = (
        extraction.get(
            "source_document_id"
        )
    )

    actual_document_id = (
        source_document.get(
            "document_id"
        )
    )

    source_document_case_id = (
        source_document.get(
            "case_id"
        )
    )

    folder_document_id = (
        paths[
            "document_dir"
        ].name
    )

    # ========================================================
    # CASE ID
    # ========================================================

    if extraction_case_id != case_id:
        errors.append(
            "facts.json case_id ile "
            "case.json case_id eşleşmiyor. "
            f"Extraction={extraction_case_id}, "
            f"Case={case_id}"
        )

    # ========================================================
    # SOURCE DOCUMENT ID
    # ========================================================

    if (
        source_document_id
        != actual_document_id
    ):
        errors.append(
            "facts.json source_document_id ile "
            "document.json document_id eşleşmiyor. "
            f"Extraction={source_document_id}, "
            f"Document={actual_document_id}"
        )

    # ========================================================
    # DOCUMENT CASE ID
    # ========================================================

    if (
        source_document_case_id
        != case_id
    ):
        errors.append(
            f"{actual_document_id}: "
            "document.case_id ile "
            "case.case_id eşleşmiyor."
        )

    # ========================================================
    # FOLDER NAME
    # ========================================================

    if (
        folder_document_id
        != source_document_id
    ):
        errors.append(
            "Extraction klasörü ile "
            "source_document_id eşleşmiyor. "
            f"Klasör={folder_document_id}, "
            f"Source={source_document_id}"
        )

    return errors


# ============================================================
# CASE REFERENCE SETS
# ============================================================

def build_reference_sets(
    case_data,
    documents,
):
    party_ids = {
        party.get(
            "party_id"
        )
        for party in case_data.get(
            "parties",
            [],
        )
    }

    dispute_item_ids = {
        item.get(
            "dispute_item_id"
        )
        for item in case_data.get(
            "dispute_items",
            [],
        )
    }

    case_document_ids = set(
        documents.keys()
    )

    return {
        "party_ids":
            party_ids,

        "dispute_item_ids":
            dispute_item_ids,

        "document_ids":
            case_document_ids,
    }


# ============================================================
# FACT CROSS REFERENCES
# ============================================================

def validate_fact_references(
    extraction,
    reference_sets,
):
    errors = []

    party_ids = reference_sets[
        "party_ids"
    ]

    dispute_item_ids = reference_sets[
        "dispute_item_ids"
    ]

    document_ids = reference_sets[
        "document_ids"
    ]

    for fact in extraction.get(
        "facts",
        [],
    ):

        fact_id = fact.get(
            "fact_id"
        )

        # ====================================================
        # ATTRIBUTED PARTY
        # ====================================================

        attributed_party_id = (
            fact.get(
                "attributed_party_id"
            )
        )

        if (
            attributed_party_id is not None
            and attributed_party_id
            not in party_ids
        ):
            errors.append(
                f"{fact_id}: "
                "attributed_party_id "
                "case.parties içinde yok: "
                f"{attributed_party_id}"
            )

        # ====================================================
        # RELATED PARTIES
        # ====================================================

        for party_id in fact.get(
            "related_party_ids",
            [],
        ):

            if party_id not in party_ids:
                errors.append(
                    f"{fact_id}: "
                    "related_party_id "
                    "case.parties içinde yok: "
                    f"{party_id}"
                )

        # ====================================================
        # RELATED DISPUTE ITEMS
        # ====================================================

        for dispute_item_id in fact.get(
            "related_dispute_item_ids",
            [],
        ):

            if (
                dispute_item_id
                not in dispute_item_ids
            ):
                errors.append(
                    f"{fact_id}: "
                    "related_dispute_item_id "
                    "case.dispute_items içinde yok: "
                    f"{dispute_item_id}"
                )

        # ====================================================
        # RELATED DOCUMENTS
        # ====================================================

        for document_id in fact.get(
            "related_document_ids",
            [],
        ):

            if document_id not in document_ids:
                errors.append(
                    f"{fact_id}: "
                    "related_document_id "
                    "case documents içinde yok: "
                    f"{document_id}"
                )

    return errors


# ============================================================
# STRUCTURED VALUE HELPERS
# ============================================================

VALUE_FIELDS = {
    "string":
        "string_value",

    "number":
        "number_value",

    "date":
        "date_value",

    "money":
        "money_value",

    "reference":
        "reference_value",
}


ALL_VALUE_FIELDS = {
    "string_value",
    "number_value",
    "date_value",
    "money_value",
    "reference_value",
}


def validate_structured_value(
    fact_id,
    index,
    value,
):
    errors = []

    value_type = value.get(
        "value_type"
    )

    expected_field = (
        VALUE_FIELDS.get(
            value_type
        )
    )

    if expected_field is None:
        return errors

    # ========================================================
    # EXPECTED VALUE MUST EXIST
    # ========================================================

    if value.get(
        expected_field
    ) is None:

        errors.append(
            f"{fact_id}: "
            f"structured_values[{index}] "
            f"value_type={value_type} ancak "
            f"{expected_field}=null."
        )

    # ========================================================
    # OTHER VALUE FIELDS MUST BE NULL
    # ========================================================

    for field in ALL_VALUE_FIELDS:

        if field == expected_field:
            continue

        if value.get(
            field
        ) is not None:

            errors.append(
                f"{fact_id}: "
                f"structured_values[{index}] "
                f"value_type={value_type} ancak "
                f"{field} de dolu."
            )

    return errors


# ============================================================
# STRUCTURED VALUE LOGIC
# ============================================================

def validate_structured_values(
    extraction,
):
    errors = []

    warnings = []

    for fact in extraction.get(
        "facts",
        [],
    ):

        fact_id = fact.get(
            "fact_id"
        )

        fact_kind = fact.get(
            "fact_kind"
        )

        values = fact.get(
            "structured_values",
            [],
        )

        value_types = []

        for index, value in enumerate(
            values
        ):
            value_types.append(
                value.get(
                    "value_type"
                )
            )

            errors.extend(
                validate_structured_value(
                    fact_id,
                    index,
                    value,
                )
            )

        # ====================================================
        # MONETARY FACT
        # ====================================================

        if (
            fact_kind == "monetary_fact"
            and "money"
            not in value_types
        ):
            errors.append(
                f"{fact_id}: "
                "fact_kind=monetary_fact ancak "
                "money structured_value yok."
            )

        # ====================================================
        # DATE FACT
        # ====================================================

        if (
            fact_kind == "date_fact"
            and "date"
            not in value_types
        ):
            errors.append(
                f"{fact_id}: "
                "fact_kind=date_fact ancak "
                "date structured_value yok."
            )

        # ====================================================
        # LEGAL REFERENCE
        # ====================================================

        if (
            fact_kind == "legal_reference"
            and "reference"
            not in value_types
        ):
            errors.append(
                f"{fact_id}: "
                "fact_kind=legal_reference ancak "
                "reference structured_value yok."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# SOURCE LOCATOR
# ============================================================

def source_has_locator(
    source,
):
    if not source:
        return False

    for field in (
        "page",
        "section",
        "paragraph",
        "text_excerpt",
    ):
        value = source.get(
            field
        )

        if value not in (
            None,
            "",
        ):
            return True

    return False


def validate_source_locators(
    extraction,
    source_document,
):
    errors = []

    warnings = []

    page_count = (
        source_document
        .get(
            "file",
            {},
        )
        .get(
            "page_count"
        )
    )

    for fact in extraction.get(
        "facts",
        [],
    ):

        fact_id = fact.get(
            "fact_id"
        )

        basis = fact.get(
            "extraction_basis"
        )

        source = fact.get(
            "source",
            {},
        )

        page = source.get(
            "page"
        )

        text_excerpt = source.get(
            "text_excerpt"
        )

        # ====================================================
        # PAGE RANGE
        # ====================================================

        if (
            page is not None
            and page_count is not None
            and page > page_count
        ):
            errors.append(
                f"{fact_id}: "
                f"source.page={page} ancak "
                f"belge page_count={page_count}."
            )

        # ====================================================
        # EXPLICIT TEXT
        # ====================================================

        if (
            basis == "explicit_text"
            and not text_excerpt
        ):
            errors.append(
                f"{fact_id}: "
                "extraction_basis=explicit_text ancak "
                "source.text_excerpt boş."
            )

        # ====================================================
        # TABLE
        # ====================================================

        if (
            basis == "table"
            and not source_has_locator(
                source
            )
        ):
            errors.append(
                f"{fact_id}: "
                "extraction_basis=table ancak "
                "kaynak konumu belirtilmemiş."
            )

        # ====================================================
        # DERIVED
        # ====================================================

        if (
            basis == "derived"
            and not source_has_locator(
                source
            )
        ):
            warnings.append(
                f"{fact_id}: "
                "extraction_basis=derived ancak "
                "kaynak locator bulunmuyor."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# VERIFICATION LOGIC
# ============================================================

def validate_verification_logic(
    extraction,
):
    errors = []

    warnings = []

    for fact in extraction.get(
        "facts",
        [],
    ):

        fact_id = fact.get(
            "fact_id"
        )

        state = fact.get(
            "verification_state"
        )

        source = fact.get(
            "source",
            {},
        )

        # ====================================================
        # VERIFIED FACT MUST BE TRACEABLE
        # ====================================================

        if (
            state == "verified"
            and not source_has_locator(
                source
            )
        ):
            errors.append(
                f"{fact_id}: "
                "verification_state=verified ancak "
                "kaynak locator bulunmuyor."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# EXTRACTION STATUS / EXTRACTOR LOGIC
# ============================================================

def validate_extractor_logic(
    extraction,
):
    errors = []

    warnings = []

    status = extraction.get(
        "status"
    )

    facts = extraction.get(
        "facts",
        [],
    )

    extractor = extraction.get(
        "extractor",
        {},
    )

    method = extractor.get(
        "method"
    )

    provider = extractor.get(
        "provider"
    )

    model = extractor.get(
        "model"
    )

    prompt_version = extractor.get(
        "prompt_version"
    )

    # ========================================================
    # COMPLETED MUST CONTAIN FACTS
    # ========================================================

    if (
        status == "completed"
        and not facts
    ):
        errors.append(
            "status=completed ancak facts boş."
        )

    # ========================================================
    # FAILED WITH FACTS
    # ========================================================

    if (
        status == "failed"
        and facts
    ):
        warnings.append(
            "status=failed ancak facts içinde "
            "kayıt bulunuyor."
        )

    # ========================================================
    # LLM REPRODUCIBILITY
    # ========================================================

    if method in {
        "llm",
        "hybrid",
    }:

        if not provider:
            errors.append(
                f"extractor.method={method} ancak "
                "provider boş."
            )

        if not model:
            errors.append(
                f"extractor.method={method} ancak "
                "model boş."
            )

        if not prompt_version:
            errors.append(
                f"extractor.method={method} ancak "
                "prompt_version boş."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# DUPLICATE STRUCTURED REFERENCES
# ============================================================

def validate_fact_internal_duplicates(
    extraction,
):
    warnings = []

    for fact in extraction.get(
        "facts",
        [],
    ):

        fact_id = fact.get(
            "fact_id"
        )

        values = fact.get(
            "structured_values",
            [],
        )

        seen = set()

        for value in values:

            value_type = value.get(
                "value_type"
            )

            target_field = (
                VALUE_FIELDS.get(
                    value_type
                )
            )

            if not target_field:
                continue

            raw_value = value.get(
                target_field
            )

            if isinstance(
                raw_value,
                dict,
            ):
                normalized_value = json.dumps(
                    raw_value,
                    sort_keys=True,
                    ensure_ascii=False,
                )

            else:
                normalized_value = str(
                    raw_value
                )

            key = (
                value_type,
                value.get(
                    "label"
                ),
                normalized_value,
            )

            if key in seen:
                warnings.append(
                    f"{fact_id}: "
                    "aynı structured_value "
                    "birden fazla kez tanımlanmış."
                )

            seen.add(
                key
            )

    return warnings


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_fact_extraction(
    facts_path=None,
    raise_on_error=True,
):

    if facts_path is None:
        facts_path = (
            DEFAULT_FACTS_PATH
        )

    facts_path = Path(
        facts_path
    ).resolve()

    # ========================================================
    # FILES EXIST
    # ========================================================

    if not FACT_SCHEMA_PATH.exists():

        raise FileNotFoundError(
            "case_fact_extraction.schema.json "
            "bulunamadı:\n"
            f"{FACT_SCHEMA_PATH}"
        )

    if not facts_path.exists():

        raise FileNotFoundError(
            "facts.json bulunamadı:\n"
            f"{facts_path}"
        )

    paths = resolve_context_paths(
        facts_path
    )

    if not paths[
        "case_path"
    ].exists():

        raise FileNotFoundError(
            "case.json bulunamadı:\n"
            f"{paths['case_path']}"
        )

    if not paths[
        "source_document_path"
    ].exists():

        raise FileNotFoundError(
            "Kaynak document.json bulunamadı:\n"
            f"{paths['source_document_path']}"
        )

    # ========================================================
    # LOAD
    # ========================================================

    schema = load_json(
        FACT_SCHEMA_PATH
    )

    extraction = load_json(
        facts_path
    )

    case_data = load_json(
        paths[
            "case_path"
        ]
    )

    source_document = load_json(
        paths[
            "source_document_path"
        ]
    )

    documents = load_case_documents(
        paths[
            "documents_dir"
        ]
    )

    errors = []

    warnings = []

    # ========================================================
    # 1. SCHEMA
    # ========================================================

    errors.extend(
        validate_schema(
            extraction,
            schema,
        )
    )

    # Schema hatalıysa semantik kontroller güvenilir değildir.
    if errors:

        result = {
            "valid":
                False,

            "errors":
                errors,

            "warnings":
                warnings,

            "extraction_id":
                extraction.get(
                    "extraction_id"
                ),

            "fact_count":
                len(
                    extraction.get(
                        "facts",
                        [],
                    )
                ),
        }

        if raise_on_error:

            raise ValueError(
                "\nCASE FACT VALIDATION HATASI\n"
                + "\n".join(
                    f"- {error}"
                    for error in errors
                )
            )

        return result

    # ========================================================
    # 2. CONTEXT
    # ========================================================

    errors.extend(
        validate_context(
            extraction,
            case_data,
            source_document,
            paths,
        )
    )

    # ========================================================
    # 3. UNIQUE FACT IDS
    # ========================================================

    errors.extend(
        validate_unique_fact_ids(
            extraction
        )
    )

    # ========================================================
    # 4. REFERENCE SETS
    # ========================================================

    reference_sets = (
        build_reference_sets(
            case_data,
            documents,
        )
    )

    # ========================================================
    # 5. CROSS REFERENCES
    # ========================================================

    errors.extend(
        validate_fact_references(
            extraction,
            reference_sets,
        )
    )

    # ========================================================
    # 6. STRUCTURED VALUES
    # ========================================================

    (
        structured_errors,
        structured_warnings,
    ) = validate_structured_values(
        extraction
    )

    errors.extend(
        structured_errors
    )

    warnings.extend(
        structured_warnings
    )

    # ========================================================
    # 7. SOURCE LOCATORS
    # ========================================================

    (
        locator_errors,
        locator_warnings,
    ) = validate_source_locators(
        extraction,
        source_document,
    )

    errors.extend(
        locator_errors
    )

    warnings.extend(
        locator_warnings
    )

    # ========================================================
    # 8. VERIFICATION
    # ========================================================

    (
        verification_errors,
        verification_warnings,
    ) = validate_verification_logic(
        extraction
    )

    errors.extend(
        verification_errors
    )

    warnings.extend(
        verification_warnings
    )

    # ========================================================
    # 9. EXTRACTOR / STATUS
    # ========================================================

    (
        extractor_errors,
        extractor_warnings,
    ) = validate_extractor_logic(
        extraction
    )

    errors.extend(
        extractor_errors
    )

    warnings.extend(
        extractor_warnings
    )

    # ========================================================
    # 10. INTERNAL DUPLICATES
    # ========================================================

    warnings.extend(
        validate_fact_internal_duplicates(
            extraction
        )
    )

    # ========================================================
    # RESULT
    # ========================================================

    valid = (
        len(
            errors
        )
        == 0
    )

    result = {
        "valid":
            valid,

        "errors":
            errors,

        "warnings":
            warnings,

        "extraction_id":
            extraction.get(
                "extraction_id"
            ),

        "case_id":
            extraction.get(
                "case_id"
            ),

        "source_document_id":
            extraction.get(
                "source_document_id"
            ),

        "status":
            extraction.get(
                "status"
            ),

        "fact_count":
            len(
                extraction.get(
                    "facts",
                    [],
                )
            ),
    }

    if (
        not valid
        and raise_on_error
    ):

        raise ValueError(
            "\nCASE FACT VALIDATION HATASI\n"
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

    facts_path = (
        Path(
            sys.argv[1]
        )
        if len(sys.argv) > 1
        else DEFAULT_FACTS_PATH
    )

    print()
    print(
        "======================================"
    )

    print(
        " VERGİ AI - CASE FACT VALIDATOR V1"
    )

    print(
        "======================================"
    )

    print()
    print(
        "Extraction:"
    )

    print(
        Path(
            facts_path
        ).resolve()
    )

    try:

        result = validate_fact_extraction(
            facts_path=facts_path,
            raise_on_error=True,
        )

        print()
        print(
            "FACT EXTRACTION GEÇERLİ"
        )

        print(
            "Extraction ID:",
            result[
                "extraction_id"
            ],
        )

        print(
            "Case ID:",
            result[
                "case_id"
            ],
        )

        print(
            "Source document:",
            result[
                "source_document_id"
            ],
        )

        print(
            "Status:",
            result[
                "status"
            ],
        )

        print(
            "Fact sayısı:",
            result[
                "fact_count"
            ],
        )

        if result[
            "warnings"
        ]:

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
            " CASE FACT VALIDATOR V1: PASS"
        )

        print(
            "======================================"
        )

    except Exception as error:

        print()
        print(
            "FACT EXTRACTION GEÇERSİZ"
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