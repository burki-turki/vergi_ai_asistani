# ============================================================
# VERGİ AI - CASE VALIDATOR V1
#
# AMAÇ:
#
# case.schema.json:
#   → yapısal / JSON Schema doğrulaması
#
# case_validator.py:
#   → semantik / veri bütünlüğü doğrulaması
#
#
# KONTROLLER:
#
# 1. JSON Schema
# 2. Unique entity IDs
# 3. Case document reference uniqueness
# 4. Source document cross references
# 5. Period date logic
# 6. Administrative action date logic
# 7. Event date precision logic
# 8. Proceeding date / status logic
# 9. Monetary consistency
# 10. Party / client-side consistency
# 11. Case stage / proceeding consistency
# 12. Related case logic
# 13. Verification state / evidence consistency
#
#
# KRİTİK PRENSİP:
#
# CASE FACT
#     !=
# AI ANALYSIS
#
# Bu validator yalnızca uyuşmazlık veri modelini doğrular.
# Hukuki değerlendirme üretmez.
# ============================================================


import os
import sys
import json

from datetime import date
from decimal import Decimal, InvalidOperation

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


# ============================================================
# VERSION
# ============================================================

CASE_VALIDATOR_VERSION = "1"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data",
)

CASE_SCHEMA_PATH = os.path.join(
    DATA_DIR,
    "case.schema.json",
)

DEFAULT_CASE_PATH = os.path.join(
    DATA_DIR,
    "cases",
    "case_0001",
    "case.json",
)


# ============================================================
# JSON LOAD
# ============================================================

def load_json(path):
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(
            file
        )


# ============================================================
# DATE
# ============================================================

def parse_date(value):
    if value is None:
        return None

    return date.fromisoformat(
        value
    )


# ============================================================
# DECIMAL
# ============================================================

def parse_money_amount(
    money,
):
    if money is None:
        return None

    amount = money.get(
        "amount"
    )

    if amount is None:
        return None

    try:
        return Decimal(
            str(
                amount
            )
        )

    except InvalidOperation:
        return None


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_schema(
    case_data,
    schema,
):
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    errors = sorted(
        validator.iter_errors(
            case_data
        ),
        key=lambda error:
            list(
                error.path
            ),
    )

    messages = []

    for error in errors:
        path = ".".join(
            str(item)
            for item
            in error.path
        )

        if not path:
            path = "root"

        messages.append(
            f"{path}: {error.message}"
        )

    return messages


# ============================================================
# UNIQUE IDS
# ============================================================

def validate_unique_ids(
    case_data,
):
    errors = []

    collections = [
        (
            "parties",
            "party_id",
        ),

        (
            "dispute_items",
            "dispute_item_id",
        ),

        (
            "administrative_actions",
            "action_id",
        ),

        (
            "events",
            "event_id",
        ),

        (
            "proceedings",
            "proceeding_id",
        ),
    ]

    for (
        collection_name,
        id_field,
    ) in collections:

        seen = set()

        for item in case_data.get(
            collection_name,
            [],
        ):
            item_id = item.get(
                id_field
            )

            if item_id in seen:
                errors.append(
                    f"{collection_name}: "
                    f"tekrarlanan {id_field}: "
                    f"{item_id}"
                )

            seen.add(
                item_id
            )

    return errors


# ============================================================
# CASE DOCUMENT REFERENCES
# ============================================================

def validate_case_document_refs(
    case_data,
):
    errors = []

    warnings = []

    refs = case_data.get(
        "case_document_refs",
        [],
    )

    seen_document_ids = set()

    primary_count = 0

    for ref in refs:
        document_id = ref.get(
            "document_id"
        )

        if document_id in seen_document_ids:
            errors.append(
                "case_document_refs: "
                "aynı document_id birden fazla kez "
                f"tanımlanmış: {document_id}"
            )

        seen_document_ids.add(
            document_id
        )

        if ref.get(
            "primary"
        ) is True:
            primary_count += 1

    if refs and primary_count == 0:
        warnings.append(
            "case_document_refs mevcut ancak "
            "primary=true belge bulunmuyor."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# DOCUMENT ID SET
# ============================================================

def get_case_document_ids(
    case_data,
):
    return {
        ref.get(
            "document_id"
        )
        for ref in case_data.get(
            "case_document_refs",
            [],
        )
    }


# ============================================================
# SOURCE DOCUMENT CROSS REFERENCES
# ============================================================

def validate_source_document_references(
    case_data,
):
    errors = []

    known_documents = (
        get_case_document_ids(
            case_data
        )
    )

    # ========================================================
    # DISPUTE ITEMS
    # ========================================================

    for item in case_data.get(
        "dispute_items",
        [],
    ):
        item_id = item.get(
            "dispute_item_id"
        )

        for document_id in item.get(
            "source_document_ids",
            [],
        ):
            if document_id not in known_documents:
                errors.append(
                    f"{item_id}: "
                    "source_document_id "
                    "case_document_refs içinde yok: "
                    f"{document_id}"
                )

    # ========================================================
    # ADMINISTRATIVE ACTIONS
    # ========================================================

    for action in case_data.get(
        "administrative_actions",
        [],
    ):
        action_id = action.get(
            "action_id"
        )

        document_id = action.get(
            "source_document_id"
        )

        if (
            document_id is not None
            and document_id not in known_documents
        ):
            errors.append(
                f"{action_id}: "
                "source_document_id "
                "case_document_refs içinde yok: "
                f"{document_id}"
            )

    # ========================================================
    # EVENTS
    # ========================================================

    for event in case_data.get(
        "events",
        [],
    ):
        event_id = event.get(
            "event_id"
        )

        for document_id in event.get(
            "source_document_ids",
            [],
        ):
            if document_id not in known_documents:
                errors.append(
                    f"{event_id}: "
                    "source_document_id "
                    "case_document_refs içinde yok: "
                    f"{document_id}"
                )

    # ========================================================
    # PROCEEDINGS
    # ========================================================

    for proceeding in case_data.get(
        "proceedings",
        [],
    ):
        proceeding_id = proceeding.get(
            "proceeding_id"
        )

        for document_id in proceeding.get(
            "source_document_ids",
            [],
        ):
            if document_id not in known_documents:
                errors.append(
                    f"{proceeding_id}: "
                    "source_document_id "
                    "case_document_refs içinde yok: "
                    f"{document_id}"
                )

    return errors


# ============================================================
# PERIOD LOGIC
# ============================================================

def validate_periods(
    case_data,
):
    errors = []

    warnings = []

    for item in case_data.get(
        "dispute_items",
        [],
    ):
        item_id = item.get(
            "dispute_item_id"
        )

        period = item.get(
            "period",
            {},
        )

        try:
            start = parse_date(
                period.get(
                    "start_date"
                )
            )

            end = parse_date(
                period.get(
                    "end_date"
                )
            )

        except ValueError as error:
            errors.append(
                f"{item_id}: "
                f"geçersiz dönem tarihi: {error}"
            )

            continue

        if (
            start is not None
            and end is not None
            and start > end
        ):
            errors.append(
                f"{item_id}: "
                "period.start_date, "
                "period.end_date tarihinden "
                "sonra olamaz."
            )

        kind = period.get(
            "kind"
        )

        # ====================================================
        # SINGLE DATE
        # ====================================================

        if (
            kind == "single_date"
            and start is not None
            and end is not None
            and start != end
        ):
            warnings.append(
                f"{item_id}: "
                "period.kind=single_date ancak "
                "başlangıç ve bitiş tarihleri farklı."
            )

        # ====================================================
        # MONTH
        # ====================================================

        if (
            kind == "month"
            and start is not None
            and end is not None
        ):
            if (
                start.year != end.year
                or start.month != end.month
            ):
                warnings.append(
                    f"{item_id}: "
                    "period.kind=month ancak "
                    "başlangıç ve bitiş aynı ay içinde değil."
                )

        # ====================================================
        # YEAR
        # ====================================================

        if (
            kind == "year"
            and start is not None
            and end is not None
            and start.year != end.year
        ):
            warnings.append(
                f"{item_id}: "
                "period.kind=year ancak "
                "başlangıç ve bitiş aynı yıl içinde değil."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# ADMINISTRATIVE ACTION DATE LOGIC
# ============================================================

def validate_administrative_actions(
    case_data,
):
    errors = []

    warnings = []

    for action in case_data.get(
        "administrative_actions",
        [],
    ):
        action_id = action.get(
            "action_id"
        )

        try:
            action_date = parse_date(
                action.get(
                    "action_date"
                )
            )

            notification_date = parse_date(
                action.get(
                    "notification_date"
                )
            )

        except ValueError as error:
            errors.append(
                f"{action_id}: "
                f"geçersiz tarih: {error}"
            )

            continue

        if (
            action_date is not None
            and notification_date is not None
            and notification_date < action_date
        ):
            errors.append(
                f"{action_id}: "
                "notification_date, action_date "
                "tarihinden önce olamaz."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# EVENT DATE LOGIC
# ============================================================

def validate_events(
    case_data,
):
    errors = []

    warnings = []

    for event in case_data.get(
        "events",
        [],
    ):
        event_id = event.get(
            "event_id"
        )

        event_date = event.get(
            "event_date"
        )

        precision = event.get(
            "date_precision"
        )

        # ====================================================
        # DATE PARSE
        # ====================================================

        try:
            parsed_date = parse_date(
                event_date
            )

        except ValueError as error:
            errors.append(
                f"{event_id}: "
                f"geçersiz event_date: {error}"
            )

            continue

        # ====================================================
        # EXACT DATE
        # ====================================================

        if (
            precision == "exact"
            and parsed_date is None
        ):
            errors.append(
                f"{event_id}: "
                "date_precision=exact ancak "
                "event_date boş."
            )

        # ====================================================
        # UNKNOWN
        # ====================================================

        if (
            precision == "unknown"
            and parsed_date is not None
        ):
            warnings.append(
                f"{event_id}: "
                "date_precision=unknown ancak "
                "event_date girilmiş."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# PROCEEDING LOGIC
# ============================================================

def validate_proceedings(
    case_data,
):
    errors = []

    warnings = []

    for proceeding in case_data.get(
        "proceedings",
        [],
    ):
        proceeding_id = proceeding.get(
            "proceeding_id"
        )

        status = proceeding.get(
            "status"
        )

        decision_number = proceeding.get(
            "decision_number"
        )

        try:
            filing_date = parse_date(
                proceeding.get(
                    "filing_date"
                )
            )

            decision_date = parse_date(
                proceeding.get(
                    "decision_date"
                )
            )

        except ValueError as error:
            errors.append(
                f"{proceeding_id}: "
                f"geçersiz tarih: {error}"
            )

            continue

        # ====================================================
        # DECISION BEFORE FILING
        # ====================================================

        if (
            filing_date is not None
            and decision_date is not None
            and decision_date < filing_date
        ):
            errors.append(
                f"{proceeding_id}: "
                "decision_date, filing_date "
                "tarihinden önce olamaz."
            )

        # ====================================================
        # PENDING + DECISION DATE
        # ====================================================

        if (
            status == "pending"
            and decision_date is not None
        ):
            warnings.append(
                f"{proceeding_id}: "
                "status=pending ancak "
                "decision_date girilmiş."
            )

        # ====================================================
        # DECIDED WITHOUT DECISION DATE
        # ====================================================

        if (
            status in {
                "decided",
                "appealed",
                "finalized",
                "closed",
            }
            and decision_date is None
        ):
            warnings.append(
                f"{proceeding_id}: "
                f"status={status} ancak "
                "decision_date boş."
            )

        # ====================================================
        # DECISION NUMBER WITHOUT DATE
        # ====================================================

        if (
            decision_number is not None
            and decision_date is None
        ):
            warnings.append(
                f"{proceeding_id}: "
                "decision_number var ancak "
                "decision_date boş."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# MONEY LOGIC
# ============================================================

def validate_money_logic(
    case_data,
):
    errors = []

    warnings = []

    for item in case_data.get(
        "dispute_items",
        [],
    ):
        item_id = item.get(
            "dispute_item_id"
        )

        principal_money = item.get(
            "principal_tax"
        )

        penalty_money = item.get(
            "penalty_amount"
        )

        total_money = item.get(
            "total_amount"
        )

        principal = parse_money_amount(
            principal_money
        )

        penalty = parse_money_amount(
            penalty_money
        )

        total = parse_money_amount(
            total_money
        )

        # ====================================================
        # NEGATIVE VALUES
        # ====================================================

        for (
            label,
            amount,
        ) in [
            (
                "principal_tax",
                principal,
            ),
            (
                "penalty_amount",
                penalty,
            ),
            (
                "total_amount",
                total,
            ),
        ]:
            if (
                amount is not None
                and amount < 0
            ):
                warnings.append(
                    f"{item_id}: "
                    f"{label} negatif."
                )

        # ====================================================
        # TOTAL CONSISTENCY
        # ====================================================

        if (
            principal_money is not None
            and penalty_money is not None
            and total_money is not None
        ):
            principal_currency = (
                principal_money.get(
                    "currency"
                )
            )

            penalty_currency = (
                penalty_money.get(
                    "currency"
                )
            )

            total_currency = (
                total_money.get(
                    "currency"
                )
            )

            currencies = {
                principal_currency,
                penalty_currency,
                total_currency,
            }

            if len(
                currencies
            ) != 1:
                errors.append(
                    f"{item_id}: "
                    "principal_tax, penalty_amount ve "
                    "total_amount para birimleri farklı."
                )

            elif (
                principal is not None
                and penalty is not None
                and total is not None
            ):
                expected_total = (
                    principal
                    + penalty
                )

                if expected_total != total:
                    errors.append(
                        f"{item_id}: "
                        "total_amount tutarsız. "
                        f"Beklenen={expected_total}, "
                        f"gerçek={total}"
                    )

    return (
        errors,
        warnings,
    )


# ============================================================
# PARTY / CLIENT LOGIC
# ============================================================

def validate_party_logic(
    case_data,
):
    errors = []

    warnings = []

    parties = case_data.get(
        "parties",
        [],
    )

    client_side = case_data.get(
        "client_side"
    )

    roles = {
        party.get(
            "role"
        )
        for party in parties
    }

    # ========================================================
    # CLIENT SIDE
    # ========================================================

    if (
        client_side in {
            "taxpayer",
            "tax_responsible",
            "administration",
            "third_party",
        }
        and client_side not in roles
    ):
        errors.append(
            "client_side="
            f"{client_side} ancak parties içinde "
            "bu role sahip taraf bulunmuyor."
        )

    # ========================================================
    # ADMINISTRATION
    # ========================================================

    if (
        client_side != "administration"
        and "administration"
        not in roles
    ):
        warnings.append(
            "Uyuşmazlık dosyasında administration "
            "rolünde taraf bulunmuyor."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# CASE STAGE LOGIC
# ============================================================

def validate_case_stage_logic(
    case_data,
):
    errors = []

    warnings = []

    stage = case_data.get(
        "stage"
    )

    case_status = case_data.get(
        "case_status"
    )

    proceedings = case_data.get(
        "proceedings",
        [],
    )

    proceeding_levels = {
        proceeding.get(
            "level"
        )
        for proceeding in proceedings
    }

    # ========================================================
    # FIRST INSTANCE
    # ========================================================

    if (
        stage == "first_instance"
        and "first_instance"
        not in proceeding_levels
    ):
        warnings.append(
            "stage=first_instance ancak "
            "first_instance proceeding bulunmuyor."
        )

    # ========================================================
    # APPEAL
    # ========================================================

    if (
        stage == "appeal"
        and "appeal"
        not in proceeding_levels
    ):
        warnings.append(
            "stage=appeal ancak "
            "appeal proceeding bulunmuyor."
        )

    # ========================================================
    # CASSATION
    # ========================================================

    if (
        stage == "cassation"
        and "cassation"
        not in proceeding_levels
    ):
        warnings.append(
            "stage=cassation ancak "
            "cassation proceeding bulunmuyor."
        )

    # ========================================================
    # CLOSED
    # ========================================================

    if (
        stage == "closed"
        and case_status not in {
            "closed",
            "archived",
            "finalized",
        }
    ):
        warnings.append(
            "stage=closed ancak case_status "
            f"{case_status}."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# RELATED CASE LOGIC
# ============================================================

def validate_related_cases(
    case_data,
):
    errors = []

    warnings = []

    case_id = case_data.get(
        "case_id"
    )

    seen = set()

    for relation in case_data.get(
        "related_cases",
        [],
    ):
        relation_type = relation.get(
            "type"
        )

        target_case_id = relation.get(
            "case_id"
        )

        if target_case_id == case_id:
            errors.append(
                f"{case_id}: "
                "related_cases kendisini hedefleyemez."
            )

        relation_key = (
            relation_type,
            target_case_id,
        )

        if relation_key in seen:
            warnings.append(
                f"{case_id}: "
                "aynı case relation birden fazla kez "
                f"tanımlanmış: "
                f"{relation_type} -> {target_case_id}"
            )

        seen.add(
            relation_key
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# VERIFICATION / EVIDENCE LOGIC
# ============================================================

def validate_verification_logic(
    case_data,
):
    errors = []

    warnings = []

    # ========================================================
    # DISPUTE ITEMS
    # ========================================================

    for item in case_data.get(
        "dispute_items",
        [],
    ):
        item_id = item.get(
            "dispute_item_id"
        )

        state = item.get(
            "verification_state"
        )

        sources = item.get(
            "source_document_ids",
            [],
        )

        if (
            state == "verified"
            and not sources
        ):
            errors.append(
                f"{item_id}: "
                "verification_state=verified ancak "
                "source_document_ids boş."
            )

    # ========================================================
    # ACTIONS
    # ========================================================

    for action in case_data.get(
        "administrative_actions",
        [],
    ):
        action_id = action.get(
            "action_id"
        )

        state = action.get(
            "verification_state"
        )

        source_document_id = (
            action.get(
                "source_document_id"
            )
        )

        if (
            state == "verified"
            and not source_document_id
        ):
            errors.append(
                f"{action_id}: "
                "verification_state=verified ancak "
                "source_document_id boş."
            )

    # ========================================================
    # EVENTS
    # ========================================================

    for event in case_data.get(
        "events",
        [],
    ):
        event_id = event.get(
            "event_id"
        )

        state = event.get(
            "verification_state"
        )

        sources = event.get(
            "source_document_ids",
            [],
        )

        if (
            state == "verified"
            and not sources
        ):
            errors.append(
                f"{event_id}: "
                "verification_state=verified ancak "
                "source_document_ids boş."
            )

    return (
        errors,
        warnings,
    )


# ============================================================
# MAIN VALIDATOR
# ============================================================

def validate_case_file(
    case_path=None,
    raise_on_error=True,
):
    if case_path is None:
        case_path = DEFAULT_CASE_PATH

    case_path = os.path.abspath(
        case_path
    )

    # ========================================================
    # FILES EXIST
    # ========================================================

    if not os.path.exists(
        CASE_SCHEMA_PATH
    ):
        raise FileNotFoundError(
            "case.schema.json bulunamadı:\n"
            f"{CASE_SCHEMA_PATH}"
        )

    if not os.path.exists(
        case_path
    ):
        raise FileNotFoundError(
            "case.json bulunamadı:\n"
            f"{case_path}"
        )

    schema = load_json(
        CASE_SCHEMA_PATH
    )

    case_data = load_json(
        case_path
    )

    errors = []

    warnings = []

    # ========================================================
    # 1. SCHEMA
    # ========================================================

    errors.extend(
        validate_schema(
            case_data,
            schema,
        )
    )

    # Schema başarısızsa semantic validation güvenilir değil.
    if errors:
        if raise_on_error:
            raise ValueError(
                "\nCASE VALIDATION HATASI\n"
                + "\n".join(
                    f"- {error}"
                    for error
                    in errors
                )
            )

        return {
            "valid":
                False,

            "errors":
                errors,

            "warnings":
                warnings,

            "case_id":
                case_data.get(
                    "case_id"
                ),
        }

    # ========================================================
    # 2. UNIQUE IDS
    # ========================================================

    errors.extend(
        validate_unique_ids(
            case_data
        )
    )

    # ========================================================
    # 3. CASE DOCUMENT REFS
    # ========================================================

    (
        document_ref_errors,
        document_ref_warnings,
    ) = validate_case_document_refs(
        case_data
    )

    errors.extend(
        document_ref_errors
    )

    warnings.extend(
        document_ref_warnings
    )

    # ========================================================
    # 4. SOURCE DOCUMENT CROSS REFERENCES
    # ========================================================

    errors.extend(
        validate_source_document_references(
            case_data
        )
    )

    # ========================================================
    # 5. PERIODS
    # ========================================================

    (
        period_errors,
        period_warnings,
    ) = validate_periods(
        case_data
    )

    errors.extend(
        period_errors
    )

    warnings.extend(
        period_warnings
    )

    # ========================================================
    # 6. ADMINISTRATIVE ACTIONS
    # ========================================================

    (
        action_errors,
        action_warnings,
    ) = validate_administrative_actions(
        case_data
    )

    errors.extend(
        action_errors
    )

    warnings.extend(
        action_warnings
    )

    # ========================================================
    # 7. EVENTS
    # ========================================================

    (
        event_errors,
        event_warnings,
    ) = validate_events(
        case_data
    )

    errors.extend(
        event_errors
    )

    warnings.extend(
        event_warnings
    )

    # ========================================================
    # 8. PROCEEDINGS
    # ========================================================

    (
        proceeding_errors,
        proceeding_warnings,
    ) = validate_proceedings(
        case_data
    )

    errors.extend(
        proceeding_errors
    )

    warnings.extend(
        proceeding_warnings
    )

    # ========================================================
    # 9. MONEY
    # ========================================================

    (
        money_errors,
        money_warnings,
    ) = validate_money_logic(
        case_data
    )

    errors.extend(
        money_errors
    )

    warnings.extend(
        money_warnings
    )

    # ========================================================
    # 10. PARTY LOGIC
    # ========================================================

    (
        party_errors,
        party_warnings,
    ) = validate_party_logic(
        case_data
    )

    errors.extend(
        party_errors
    )

    warnings.extend(
        party_warnings
    )

    # ========================================================
    # 11. CASE STAGE
    # ========================================================

    (
        stage_errors,
        stage_warnings,
    ) = validate_case_stage_logic(
        case_data
    )

    errors.extend(
        stage_errors
    )

    warnings.extend(
        stage_warnings
    )

    # ========================================================
    # 12. RELATED CASES
    # ========================================================

    (
        relation_errors,
        relation_warnings,
    ) = validate_related_cases(
        case_data
    )

    errors.extend(
        relation_errors
    )

    warnings.extend(
        relation_warnings
    )

    # ========================================================
    # 13. VERIFICATION
    # ========================================================

    (
        verification_errors,
        verification_warnings,
    ) = validate_verification_logic(
        case_data
    )

    errors.extend(
        verification_errors
    )

    warnings.extend(
        verification_warnings
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

    if (
        not valid
        and raise_on_error
    ):
        raise ValueError(
            "\nCASE VALIDATION HATASI\n"
            + "\n".join(
                f"- {error}"
                for error
                in errors
            )
        )

    return {
        "valid":
            valid,

        "errors":
            errors,

        "warnings":
            warnings,

        "case_id":
            case_data.get(
                "case_id"
            ),

        "party_count":
            len(
                case_data.get(
                    "parties",
                    [],
                )
            ),

        "dispute_item_count":
            len(
                case_data.get(
                    "dispute_items",
                    [],
                )
            ),

        "action_count":
            len(
                case_data.get(
                    "administrative_actions",
                    [],
                )
            ),

        "event_count":
            len(
                case_data.get(
                    "events",
                    [],
                )
            ),

        "proceeding_count":
            len(
                case_data.get(
                    "proceedings",
                    [],
                )
            ),

        "document_ref_count":
            len(
                case_data.get(
                    "case_document_refs",
                    [],
                )
            ),
    }


# ============================================================
# CLI
# ============================================================

def main():
    case_path = (
        sys.argv[1]
        if len(
            sys.argv
        ) > 1
        else DEFAULT_CASE_PATH
    )

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - CASE VALIDATOR V1"
    )

    print(
        "======================================"
    )

    print(
        "\nCase:"
    )

    print(
        os.path.abspath(
            case_path
        )
    )

    try:
        result = validate_case_file(
            case_path=
                case_path,

            raise_on_error=
                True,
        )

        print(
            "\nCASE GEÇERLİ"
        )

        print(
            "Case ID:",
            result[
                "case_id"
            ]
        )

        print(
            "Taraf sayısı:",
            result[
                "party_count"
            ]
        )

        print(
            "Uyuşmazlık kalemi:",
            result[
                "dispute_item_count"
            ]
        )

        print(
            "İdari işlem:",
            result[
                "action_count"
            ]
        )

        print(
            "Olay:",
            result[
                "event_count"
            ]
        )

        print(
            "Yargılama:",
            result[
                "proceeding_count"
            ]
        )

        print(
            "Dosya referansı:",
            result[
                "document_ref_count"
            ]
        )

        if result[
            "warnings"
        ]:
            print(
                "\nUYARILAR:"
            )

            for warning in result[
                "warnings"
            ]:
                print(
                    "-",
                    warning
                )

        else:
            print(
                "\nUyarı yok."
            )

        print(
            "\n======================================"
        )

        print(
            " CASE VALIDATOR V1: PASS"
        )

        print(
            "======================================"
        )

    except Exception as error:
        print(
            "\nCASE GEÇERSİZ"
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