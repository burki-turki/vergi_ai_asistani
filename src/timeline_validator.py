# ============================================================
# VERGİ AI - TIMELINE VALIDATOR V1
#
# AMAÇ:
#
# Case Timeline çıktısını iki seviyede doğrulamak:
#
# 1. JSON Schema doğrulaması
# 2. Case / Fact / Document çapraz bütünlük doğrulaması
#
#
# TEMEL PRENSİP:
#
# Timeline Agent'ın ürettiği bir event:
#
#   - canonical fact'e dayanmalı
#   - gerçek case document'a dayanmalı
#   - case içindeki party/dispute item ID'lerini kullanmalı
#   - kaynak fact ile kaynak document arasında bağ bulunmalı
#
#
# Timeline Validator:
#
#   HUKUKİ SÜRE HESAPLAMAZ.
#
#   Bir tarihin süre başlatıp başlatmadığına karar VERMEZ.
#
# Bu görev sonraki:
#
#   Deadline Engine
#
# katmanına aittir.
#
#
# ÖNEMLİ:
#
# deadline_relevant = true
#
# yalnız:
#
# "bu olay ileride süre hesabı açısından incelenmelidir"
#
# anlamındadır.
#
# "bu tarih kesin süre başlatır"
#
# anlamına GELMEZ.
# ============================================================


import argparse
import json
import sys

from collections import Counter
from datetime import date, datetime
from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


# ============================================================
# VERSION
# ============================================================

TIMELINE_VALIDATOR_VERSION = "1"


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

CASES_DIR = (
    DATA_DIR
    / "cases"
)

TIMELINE_SCHEMA_PATH = (
    DATA_DIR
    / "case_timeline.schema.json"
)

DEFAULT_CASE_ID = "case_0001"

DEFAULT_TIMELINE_PATH = (
    CASES_DIR
    / DEFAULT_CASE_ID
    / "timeline"
    / "timeline.json"
)


# ============================================================
# EXCEPTIONS
# ============================================================

class TimelineValidationError(
    Exception
):
    pass


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path):

    path = Path(
        path
    )

    if not path.exists():

        raise FileNotFoundError(
            f"JSON dosyası bulunamadı:\n{path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(
            file
        )


# ============================================================
# DATE HELPERS
# ============================================================

def parse_iso_date(
    value,
):

    if not isinstance(
        value,
        str,
    ):

        return None

    try:

        return date.fromisoformat(
            value
        )

    except ValueError:

        return None


def parse_iso_datetime(
    value,
):

    if not isinstance(
        value,
        str,
    ):

        return None

    try:

        return datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

    except ValueError:

        return None


# ============================================================
# CASE LOADING
# ============================================================

def load_case(
    case_id,
):

    case_path = (
        CASES_DIR
        / case_id
        / "case.json"
    )

    case_data = load_json(
        case_path
    )

    if (
        case_data.get(
            "case_id"
        )
        != case_id
    ):

        raise TimelineValidationError(
            "case.json içindeki case_id "
            "beklenen case_id ile uyuşmuyor.\n"
            f"Beklenen: {case_id}\n"
            f"Bulunan: {case_data.get('case_id')}"
        )

    return (
        case_data,
        case_path,
    )


# ============================================================
# CASE PARTY IDS
# ============================================================

def get_case_party_ids(
    case_data,
):

    result = set()

    for party in case_data.get(
        "parties",
        [],
    ):

        party_id = party.get(
            "party_id"
        )

        if party_id:

            result.add(
                party_id
            )

    return result


# ============================================================
# CASE DISPUTE ITEM IDS
# ============================================================

def get_case_dispute_item_ids(
    case_data,
):

    result = set()

    for item in case_data.get(
        "dispute_items",
        [],
    ):

        dispute_item_id = (
            item.get(
                "dispute_item_id"
            )
        )

        if dispute_item_id:

            result.add(
                dispute_item_id
            )

    return result


# ============================================================
# DOCUMENT INDEX
# ============================================================

def load_document_index(
    case_id,
):

    documents_dir = (
        CASES_DIR
        / case_id
        / "documents"
    )

    if not documents_dir.exists():

        raise FileNotFoundError(
            "Case documents klasörü bulunamadı:\n"
            f"{documents_dir}"
        )

    documents = {}

    for document_path in sorted(
        documents_dir.glob(
            "*/document.json"
        )
    ):

        document = load_json(
            document_path
        )

        document_id = (
            document.get(
                "document_id"
            )
        )

        if not document_id:

            raise TimelineValidationError(
                "document.json içinde document_id yok:\n"
                f"{document_path}"
            )

        if (
            document.get(
                "case_id"
            )
            != case_id
        ):

            raise TimelineValidationError(
                "Document case_id uyuşmazlığı:\n"
                f"{document_path}"
            )

        if document_id in documents:

            raise TimelineValidationError(
                "Duplicate document_id bulundu: "
                f"{document_id}"
            )

        documents[
            document_id
        ] = {
            "data":
                document,

            "path":
                document_path,
        }

    return documents


# ============================================================
# CANONICAL FACT INDEX
# ============================================================

def load_canonical_fact_index(
    case_id,
):

    documents_dir = (
        CASES_DIR
        / case_id
        / "documents"
    )

    if not documents_dir.exists():

        raise FileNotFoundError(
            "Case documents klasörü bulunamadı:\n"
            f"{documents_dir}"
        )

    facts = {}

    extraction_ids = set()

    canonical_files = []

    for facts_path in sorted(
        documents_dir.glob(
            "*/extractions/facts.json"
        )
    ):

        extraction = load_json(
            facts_path
        )

        if (
            extraction.get(
                "case_id"
            )
            != case_id
        ):

            raise TimelineValidationError(
                "Canonical fact extraction case_id uyuşmazlığı:\n"
                f"{facts_path}"
            )

        source_document_id = (
            extraction.get(
                "source_document_id"
            )
        )

        extraction_id = (
            extraction.get(
                "extraction_id"
            )
        )

        if extraction_id:

            if extraction_id in extraction_ids:

                raise TimelineValidationError(
                    "Duplicate canonical extraction_id bulundu: "
                    f"{extraction_id}"
                )

            extraction_ids.add(
                extraction_id
            )

        canonical_files.append(
            facts_path
        )

        for fact in extraction.get(
            "facts",
            [],
        ):

            fact_id = (
                fact.get(
                    "fact_id"
                )
            )

            if not fact_id:

                raise TimelineValidationError(
                    "Canonical fact içinde fact_id yok:\n"
                    f"{facts_path}"
                )

            if fact_id in facts:

                raise TimelineValidationError(
                    "Duplicate canonical fact_id bulundu: "
                    f"{fact_id}"
                )

            facts[
                fact_id
            ] = {
                "fact":
                    fact,

                "source_document_id":
                    source_document_id,

                "extraction_id":
                    extraction_id,

                "facts_path":
                    facts_path,
            }

    return {
        "facts":
            facts,

        "canonical_files":
            canonical_files,

        "extraction_ids":
            extraction_ids,
    }


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_schema(
    timeline,
):

    schema = load_json(
        TIMELINE_SCHEMA_PATH
    )

    validator = (
        Draft202012Validator(
            schema,
            format_checker=
                FormatChecker(),
        )
    )

    errors = sorted(
        validator.iter_errors(
            timeline
        ),
        key=lambda error:
            list(
                error.absolute_path
            ),
    )

    messages = []

    for error in errors:

        path = ".".join(
            str(part)
            for part
            in error.absolute_path
        )

        if path:

            message = (
                f"{path}: "
                f"{error.message}"
            )

        else:

            message = error.message

        messages.append(
            message
        )

    return messages


# ============================================================
# EVENT ID CHECK
# ============================================================

def validate_unique_event_ids(
    events,
):

    errors = []

    event_ids = [
        event.get(
            "event_id"
        )
        for event in events
        if event.get(
            "event_id"
        )
    ]

    counts = Counter(
        event_ids
    )

    duplicates = sorted(
        event_id
        for event_id, count
        in counts.items()
        if count > 1
    )

    for event_id in duplicates:

        errors.append(
            "Duplicate timeline event_id: "
            f"{event_id}"
        )

    return errors


# ============================================================
# SOURCE FACT VALIDATION
# ============================================================

def validate_source_facts(
    event,
    fact_index,
):

    errors = []

    event_id = event.get(
        "event_id"
    )

    for fact_id in event.get(
        "source_fact_ids",
        [],
    ):

        if fact_id not in fact_index:

            errors.append(
                f"{event_id}: source_fact_id "
                f"canonical repository içinde bulunamadı: "
                f"{fact_id}"
            )

    return errors


# ============================================================
# SOURCE DOCUMENT VALIDATION
# ============================================================

def validate_source_documents(
    event,
    document_index,
):

    errors = []

    event_id = event.get(
        "event_id"
    )

    for document_id in event.get(
        "source_document_ids",
        [],
    ):

        if document_id not in document_index:

            errors.append(
                f"{event_id}: source_document_id "
                f"case documents içinde bulunamadı: "
                f"{document_id}"
            )

    return errors


# ============================================================
# PARTY VALIDATION
# ============================================================

def validate_party_ids(
    event,
    party_ids,
):

    errors = []

    event_id = event.get(
        "event_id"
    )

    for party_id in event.get(
        "related_party_ids",
        [],
    ):

        if party_id not in party_ids:

            errors.append(
                f"{event_id}: related_party_id "
                f"case içinde bulunamadı: "
                f"{party_id}"
            )

    return errors


# ============================================================
# DISPUTE ITEM VALIDATION
# ============================================================

def validate_dispute_item_ids(
    event,
    dispute_item_ids,
):

    errors = []

    event_id = event.get(
        "event_id"
    )

    for dispute_item_id in event.get(
        "related_dispute_item_ids",
        [],
    ):

        if (
            dispute_item_id
            not in dispute_item_ids
        ):

            errors.append(
                f"{event_id}: related_dispute_item_id "
                f"case içinde bulunamadı: "
                f"{dispute_item_id}"
            )

    return errors


# ============================================================
# FACT ↔ DOCUMENT CROSS CHECK
# ============================================================

def validate_fact_document_integrity(
    event,
    fact_index,
):

    errors = []

    event_id = event.get(
        "event_id"
    )

    event_document_ids = set(
        event.get(
            "source_document_ids",
            [],
        )
    )

    for fact_id in event.get(
        "source_fact_ids",
        [],
    ):

        record = fact_index.get(
            fact_id
        )

        if not record:

            continue

        canonical_source_document_id = (
            record.get(
                "source_document_id"
            )
        )

        if (
            canonical_source_document_id
            and canonical_source_document_id
            not in event_document_ids
        ):

            errors.append(
                f"{event_id}: source_fact_id "
                f"{fact_id} canonical olarak "
                f"{canonical_source_document_id} belgesinden geliyor "
                "ancak bu belge event.source_document_ids "
                "içinde bulunmuyor."
            )

    return errors


# ============================================================
# DATE ↔ FACT CROSS CHECK
# ============================================================

def extract_date_values_from_fact(
    fact,
):

    dates = set()

    for value in fact.get(
        "structured_values",
        [],
    ):

        if (
            value.get(
                "value_type"
            )
            != "date"
        ):

            continue

        date_value = (
            value.get(
                "date_value"
            )
        )

        if date_value:

            dates.add(
                date_value
            )

    return dates


def validate_event_date_support(
    event,
    fact_index,
):

    errors = []

    warnings = []

    event_id = event.get(
        "event_id"
    )

    event_date = event.get(
        "date"
    )

    supported_dates = set()

    source_fact_count = 0

    for fact_id in event.get(
        "source_fact_ids",
        [],
    ):

        record = fact_index.get(
            fact_id
        )

        if not record:

            continue

        source_fact_count += 1

        fact = record[
            "fact"
        ]

        supported_dates.update(
            extract_date_values_from_fact(
                fact
            )
        )

    # --------------------------------------------------------
    # Timeline event'in tarihi canonical fact'in structured
    # date alanlarından birinde bulunmalı.
    #
    # V1 için deterministik exact support istiyoruz.
    # --------------------------------------------------------

    if (
        source_fact_count > 0
        and event_date
        not in supported_dates
    ):

        errors.append(
            f"{event_id}: event.date "
            f"{event_date} hiçbir source fact structured date "
            "değeri tarafından desteklenmiyor."
        )

    if not supported_dates:

        warnings.append(
            f"{event_id}: source fact'lerde structured date "
            "değeri bulunamadı."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# VERIFICATION PROPAGATION
# ============================================================

VERIFICATION_RANK = {
    "verified":
        5,

    "partially_verified":
        4,

    "unverified":
        3,

    "disputed":
        2,

    "rejected":
        1,
}


def get_fact_verification_states(
    event,
    fact_index,
):

    states = []

    for fact_id in event.get(
        "source_fact_ids",
        [],
    ):

        record = fact_index.get(
            fact_id
        )

        if not record:

            continue

        fact = record[
            "fact"
        ]

        state = fact.get(
            "verification_state"
        )

        if state:

            states.append(
                state
            )

    return states


def validate_verification_state(
    event,
    fact_index,
):

    errors = []

    warnings = []

    event_id = event.get(
        "event_id"
    )

    event_state = event.get(
        "verification_state"
    )

    source_states = (
        get_fact_verification_states(
            event,
            fact_index,
        )
    )

    if not source_states:

        return (
            errors,
            warnings,
        )

    # --------------------------------------------------------
    # Timeline event, kaynak fact'lerden daha güçlü bir
    # verification seviyesi kazanamaz.
    #
    # Örnek:
    #
    # source fact = unverified
    # event       = verified
    #
    # YASAK.
    # --------------------------------------------------------

    known_source_ranks = [
        VERIFICATION_RANK[
            state
        ]
        for state in source_states
        if state in VERIFICATION_RANK
    ]

    if (
        event_state
        in VERIFICATION_RANK
        and known_source_ranks
    ):

        event_rank = (
            VERIFICATION_RANK[
                event_state
            ]
        )

        strongest_allowed_rank = min(
            known_source_ranks
        )

        if (
            event_rank
            >
            strongest_allowed_rank
        ):

            errors.append(
                f"{event_id}: timeline verification_state "
                f"'{event_state}' kaynak fact'lerden daha güçlü. "
                f"Kaynak states: {sorted(set(source_states))}"
            )

    # --------------------------------------------------------
    # Deadline açısından önemli fakat verified olmayan tarih
    # mutlaka görünür warning üretmeli.
    # --------------------------------------------------------

    if (
        event.get(
            "deadline_relevant"
        )
        is True
        and event_state
        != "verified"
    ):

        warnings.append(
            f"{event_id}: deadline_relevant=True ancak "
            f"verification_state='{event_state}'. "
            "Deadline Engine bu tarihi kesin doğrulanmış "
            "tarih olarak kullanmamalıdır."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# DEADLINE RELEVANCE RULES
# ============================================================

POTENTIALLY_DEADLINE_RELEVANT_TYPES = {
    "notification_date",
    "filing_date",
    "administrative_application_date",
    "administrative_decision_date",
    "court_decision_date",
    "appeal_date",
}


def validate_deadline_relevance(
    event,
):

    warnings = []

    event_id = event.get(
        "event_id"
    )

    event_type = event.get(
        "event_type"
    )

    deadline_relevant = event.get(
        "deadline_relevant"
    )

    if (
        event_type
        in POTENTIALLY_DEADLINE_RELEVANT_TYPES
        and deadline_relevant is False
    ):

        warnings.append(
            f"{event_id}: event_type='{event_type}' "
            "potansiyel olarak süre açısından önemlidir ancak "
            "deadline_relevant=False."
        )

    return warnings


# ============================================================
# DATE PRECISION
# ============================================================

def validate_date_precision(
    event,
):

    errors = []

    warnings = []

    event_id = event.get(
        "event_id"
    )

    event_date = event.get(
        "date"
    )

    date_precision = event.get(
        "date_precision"
    )

    parsed_date = parse_iso_date(
        event_date
    )

    if parsed_date is None:

        errors.append(
            f"{event_id}: geçersiz ISO date: "
            f"{event_date}"
        )

        return (
            errors,
            warnings,
        )

    # --------------------------------------------------------
    # Schema V1 event.date alanını tam ISO date olarak
    # zorunlu tutuyor.
    #
    # precision month/year/approximate ise tarih temsilidir,
    # gerçek gün kesinliği değildir.
    # --------------------------------------------------------

    if (
        date_precision
        in {
            "month",
            "year",
            "approximate",
            "unknown",
        }
    ):

        warnings.append(
            f"{event_id}: date_precision='{date_precision}'. "
            f"event.date={event_date} temsilî olabilir; "
            "Deadline Engine bunu exact tarih olarak "
            "kullanmamalıdır."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# CHRONOLOGY
# ============================================================

def validate_chronological_order(
    events,
):

    errors = []

    previous_date = None
    previous_event_id = None

    for event in events:

        current_date = parse_iso_date(
            event.get(
                "date"
            )
        )

        if current_date is None:

            continue

        if (
            previous_date is not None
            and current_date < previous_date
        ):

            errors.append(
                "Timeline events kronolojik sırada değil: "
                f"{event.get('event_id')} ({current_date}) "
                f"< {previous_event_id} ({previous_date})"
            )

        previous_date = (
            current_date
        )

        previous_event_id = (
            event.get(
                "event_id"
            )
        )

    return errors


# ============================================================
# GENERATED AT
# ============================================================

def validate_generated_at(
    timeline,
):

    errors = []

    generated_at = timeline.get(
        "generated_at"
    )

    if (
        parse_iso_datetime(
            generated_at
        )
        is None
    ):

        errors.append(
            "generated_at geçerli ISO date-time değil: "
            f"{generated_at}"
        )

    return errors


# ============================================================
# CASE ID
# ============================================================

def validate_case_id(
    timeline,
    expected_case_id,
):

    errors = []

    timeline_case_id = (
        timeline.get(
            "case_id"
        )
    )

    if (
        timeline_case_id
        != expected_case_id
    ):

        errors.append(
            "Timeline case_id uyuşmazlığı. "
            f"Beklenen={expected_case_id}, "
            f"Bulunan={timeline_case_id}"
        )

    return errors


# ============================================================
# EVENT SOURCE PRESENCE
# ============================================================

def validate_event_source_presence(
    event,
):

    errors = []

    event_id = event.get(
        "event_id"
    )

    source_fact_ids = event.get(
        "source_fact_ids",
        [],
    )

    source_document_ids = event.get(
        "source_document_ids",
        [],
    )

    if not source_fact_ids:

        errors.append(
            f"{event_id}: source_fact_ids boş olamaz."
        )

    if not source_document_ids:

        errors.append(
            f"{event_id}: source_document_ids boş olamaz."
        )

    return errors


# ============================================================
# EVENT STATEMENT
# ============================================================

OVERCLAIM_PHRASES = (
    "kesin olarak",
    "kesinlikle",
    "şüphesiz",
    "dava süresi dolmuştur",
    "süre kaçırılmıştır",
    "süre başlamıştır",
    "süre sona ermiştir",
    "zamanaşımı gerçekleşmiştir",
    "hukuka aykırıdır",
    "hukuka uygundur",
)


def validate_statement_safety(
    event,
):

    warnings = []

    event_id = event.get(
        "event_id"
    )

    statement = str(
        event.get(
            "statement"
        )
        or ""
    ).casefold()

    for phrase in OVERCLAIM_PHRASES:

        if (
            phrase.casefold()
            in statement
        ):

            warnings.append(
                f"{event_id}: statement olası hukuki/epistemik "
                f"overclaim içeriyor: '{phrase}'"
            )

    return warnings


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_timeline(
    timeline_path,
    expected_case_id=None,
    raise_on_error=False,
):

    timeline_path = Path(
        timeline_path
    )

    timeline = load_json(
        timeline_path
    )

    case_id = (
        expected_case_id
        or timeline.get(
            "case_id"
        )
    )

    if not case_id:

        raise TimelineValidationError(
            "case_id belirlenemedi."
        )

    # ========================================================
    # LOAD CONTEXT
    # ========================================================

    case_data, case_path = (
        load_case(
            case_id
        )
    )

    document_index = (
        load_document_index(
            case_id
        )
    )

    canonical = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = canonical[
        "facts"
    ]

    party_ids = (
        get_case_party_ids(
            case_data
        )
    )

    dispute_item_ids = (
        get_case_dispute_item_ids(
            case_data
        )
    )

    errors = []

    warnings = []

    # ========================================================
    # SCHEMA
    # ========================================================

    schema_errors = (
        validate_schema(
            timeline
        )
    )

    errors.extend(
        schema_errors
    )

    # Schema hatalıysa semantic alanlara erişim yine
    # kontrollü yapılabilir; validator mümkün olduğunca
    # toplu hata raporu üretir.

    # ========================================================
    # TOP LEVEL
    # ========================================================

    errors.extend(
        validate_case_id(
            timeline,
            case_id,
        )
    )

    errors.extend(
        validate_generated_at(
            timeline
        )
    )

    events = timeline.get(
        "events",
        [],
    )

    if not isinstance(
        events,
        list,
    ):

        events = []

    # ========================================================
    # UNIQUE EVENT IDS
    # ========================================================

    errors.extend(
        validate_unique_event_ids(
            events
        )
    )

    # ========================================================
    # EVENTS
    # ========================================================

    for event in events:

        if not isinstance(
            event,
            dict,
        ):

            continue

        errors.extend(
            validate_event_source_presence(
                event
            )
        )

        errors.extend(
            validate_source_facts(
                event,
                fact_index,
            )
        )

        errors.extend(
            validate_source_documents(
                event,
                document_index,
            )
        )

        errors.extend(
            validate_party_ids(
                event,
                party_ids,
            )
        )

        errors.extend(
            validate_dispute_item_ids(
                event,
                dispute_item_ids,
            )
        )

        errors.extend(
            validate_fact_document_integrity(
                event,
                fact_index,
            )
        )

        (
            date_errors,
            date_warnings,
        ) = (
            validate_event_date_support(
                event,
                fact_index,
            )
        )

        errors.extend(
            date_errors
        )

        warnings.extend(
            date_warnings
        )

        (
            verification_errors,
            verification_warnings,
        ) = (
            validate_verification_state(
                event,
                fact_index,
            )
        )

        errors.extend(
            verification_errors
        )

        warnings.extend(
            verification_warnings
        )

        warnings.extend(
            validate_deadline_relevance(
                event
            )
        )

        (
            precision_errors,
            precision_warnings,
        ) = (
            validate_date_precision(
                event
            )
        )

        errors.extend(
            precision_errors
        )

        warnings.extend(
            precision_warnings
        )

        warnings.extend(
            validate_statement_safety(
                event
            )
        )

    # ========================================================
    # CHRONOLOGY
    # ========================================================

    errors.extend(
        validate_chronological_order(
            events
        )
    )

    # ========================================================
    # UNIQUE WARNING / ERROR TEXT
    # ========================================================

    errors = list(
        dict.fromkeys(
            errors
        )
    )

    warnings = list(
        dict.fromkeys(
            warnings
        )
    )

    result = {
        "valid":
            len(errors) == 0,

        "validator_version":
            TIMELINE_VALIDATOR_VERSION,

        "timeline_path":
            str(
                timeline_path
            ),

        "case_id":
            case_id,

        "case_path":
            str(
                case_path
            ),

        "event_count":
            len(
                events
            ),

        "canonical_fact_count":
            len(
                fact_index
            ),

        "document_count":
            len(
                document_index
            ),

        "errors":
            errors,

        "warnings":
            warnings,
    }

    if (
        raise_on_error
        and errors
    ):

        message_lines = [
            "TIMELINE VALIDATOR V1: FAIL",
            "",
        ]

        for error in errors:

            message_lines.append(
                f"- {error}"
            )

        raise TimelineValidationError(
            "\n".join(
                message_lines
            )
        )

    return result


# ============================================================
# TEST FIXTURE GENERATOR
# ============================================================

def create_demo_timeline(
    case_id,
):

    canonical = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = canonical[
        "facts"
    ]

    # --------------------------------------------------------
    # Fact repository'den date structured value taşıyan
    # canonical fact'leri bul.
    # --------------------------------------------------------

    candidates = []

    for (
        fact_id,
        record,
    ) in fact_index.items():

        fact = record[
            "fact"
        ]

        dates = (
            extract_date_values_from_fact(
                fact
            )
        )

        for date_value in dates:

            candidates.append(
                {
                    "date":
                        date_value,

                    "fact_id":
                        fact_id,

                    "document_id":
                        record[
                            "source_document_id"
                        ],

                    "fact":
                        fact,
                }
            )

    candidates.sort(
        key=lambda item:
            (
                item[
                    "date"
                ],
                item[
                    "fact_id"
                ],
            )
    )

    events = []

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):

        fact = candidate[
            "fact"
        ]

        fact_kind = fact.get(
            "fact_kind"
        )

        statement = fact.get(
            "statement"
        )

        event_type = "other"

        statement_lower = str(
            statement
            or ""
        ).casefold()

        if (
            "tebliğ"
            in statement_lower
        ):

            event_type = (
                "notification_date"
            )

        elif (
            "dava tarihi"
            in statement_lower
        ):

            event_type = (
                "filing_date"
            )

        elif (
            "rapor"
            in statement_lower
        ):

            event_type = (
                "report_date"
            )

        elif (
            "ihbarname"
            in statement_lower
        ):

            event_type = (
                "document_date"
            )

        elif (
            fact_kind
            == "date_fact"
        ):

            event_type = (
                "document_date"
            )

        deadline_relevant = (
            event_type
            in POTENTIALLY_DEADLINE_RELEVANT_TYPES
        )

        events.append(
            {
                "event_id":
                    f"timeline_event_{index:03d}",

                "event_type":
                    event_type,

                "date":
                    candidate[
                        "date"
                    ],

                "date_precision":
                    "exact",

                "statement":
                    statement,

                "source_fact_ids": [
                    candidate[
                        "fact_id"
                    ]
                ],

                "source_document_ids": [
                    candidate[
                        "document_id"
                    ]
                ],

                "related_party_ids":
                    fact.get(
                        "related_party_ids",
                        [],
                    ),

                "related_dispute_item_ids":
                    fact.get(
                        "related_dispute_item_ids",
                        [],
                    ),

                "verification_state":
                    fact.get(
                        "verification_state",
                        "unverified",
                    ),

                "confidence":
                    fact.get(
                        "confidence",
                        0.5,
                    ),

                "deadline_relevant":
                    deadline_relevant,

                "notes":
                    (
                        "Timeline Validator V1 test fixture "
                        "generator tarafından canonical fact "
                        "üzerinden oluşturulmuştur."
                    ),
            }
        )

    return {
        "schema_version":
            1,

        "timeline_id":
            f"timeline_{case_id}_demo_v1",

        "case_id":
            case_id,

        "status":
            (
                "completed"
                if events
                else "failed"
            ),

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "events":
            events,

        "warnings":
            [],

        "notes":
            (
                "Timeline Validator V1 için otomatik "
                "oluşturulmuş test fixture'ıdır."
            ),
    }


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(
    case_id,
):

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - TIMELINE VALIDATOR V1"
    )

    print(
        "======================================"
    )

    # ========================================================
    # T01 SCHEMA FILE
    # ========================================================

    assert (
        TIMELINE_SCHEMA_PATH.exists()
    )

    load_json(
        TIMELINE_SCHEMA_PATH
    )

    print(
        "T01 Timeline schema load:",
        "PASS"
    )

    # ========================================================
    # T02 CASE LOAD
    # ========================================================

    case_data, _ = (
        load_case(
            case_id
        )
    )

    assert (
        case_data.get(
            "case_id"
        )
        == case_id
    )

    print(
        "T02 Case load:",
        "PASS"
    )

    # ========================================================
    # T03 DOCUMENT INDEX
    # ========================================================

    document_index = (
        load_document_index(
            case_id
        )
    )

    assert (
        len(
            document_index
        )
        >= 1
    )

    print(
        "T03 Document index:",
        "PASS"
    )

    # ========================================================
    # T04 CANONICAL FACT INDEX
    # ========================================================

    canonical = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = canonical[
        "facts"
    ]

    assert (
        len(
            fact_index
        )
        >= 1
    )

    print(
        "T04 Canonical fact index:",
        "PASS"
    )

    # ========================================================
    # T05 DEMO TIMELINE
    # ========================================================

    timeline = (
        create_demo_timeline(
            case_id
        )
    )

    assert (
        timeline[
            "case_id"
        ]
        == case_id
    )

    assert (
        len(
            timeline[
                "events"
            ]
        )
        >= 1
    )

    print(
        "T05 Demo timeline build:",
        "PASS"
    )

    # ========================================================
    # WRITE TEMP TEST FILE
    # ========================================================

    timeline_dir = (
        CASES_DIR
        / case_id
        / "timeline"
    )

    timeline_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    test_path = (
        timeline_dir
        / "timeline_validator_v1_test.json"
    )

    write_json(
        test_path,
        timeline,
    )

    # ========================================================
    # T06 VALID TIMELINE
    # ========================================================

    result = (
        validate_timeline(
            timeline_path=test_path,
            expected_case_id=case_id,
            raise_on_error=False,
        )
    )

    if not result[
        "valid"
    ]:

        print()

        print(
            "T06 errors:"
        )

        for error in result[
            "errors"
        ]:

            print(
                "-",
                error,
            )

    assert (
        result[
            "valid"
        ]
        is True
    )

    print(
        "T06 Valid timeline:",
        "PASS"
    )

    # ========================================================
    # T07 UNKNOWN FACT BLOCK
    # ========================================================

    broken_fact = json.loads(
        json.dumps(
            timeline
        )
    )

    broken_fact[
        "events"
    ][
        0
    ][
        "source_fact_ids"
    ] = [
        "fact_does_not_exist"
    ]

    broken_path = (
        timeline_dir
        / "timeline_validator_v1_broken_fact.json"
    )

    write_json(
        broken_path,
        broken_fact,
    )

    broken_result = (
        validate_timeline(
            timeline_path=
                broken_path,

            expected_case_id=
                case_id,

            raise_on_error=
                False,
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T07 Unknown fact blocked:",
        "PASS"
    )

    # ========================================================
    # T08 UNKNOWN DOCUMENT BLOCK
    # ========================================================

    broken_document = json.loads(
        json.dumps(
            timeline
        )
    )

    broken_document[
        "events"
    ][
        0
    ][
        "source_document_ids"
    ] = [
        "document_does_not_exist"
    ]

    broken_document_path = (
        timeline_dir
        / "timeline_validator_v1_broken_document.json"
    )

    write_json(
        broken_document_path,
        broken_document,
    )

    broken_document_result = (
        validate_timeline(
            timeline_path=
                broken_document_path,

            expected_case_id=
                case_id,

            raise_on_error=
                False,
        )
    )

    assert (
        broken_document_result[
            "valid"
        ]
        is False
    )

    print(
        "T08 Unknown document blocked:",
        "PASS"
    )

    # ========================================================
    # T09 DATE SUPPORT BLOCK
    # ========================================================

    broken_date = json.loads(
        json.dumps(
            timeline
        )
    )

    broken_date[
        "events"
    ][
        0
    ][
        "date"
    ] = "2099-12-31"

    broken_date_path = (
        timeline_dir
        / "timeline_validator_v1_broken_date.json"
    )

    write_json(
        broken_date_path,
        broken_date,
    )

    broken_date_result = (
        validate_timeline(
            timeline_path=
                broken_date_path,

            expected_case_id=
                case_id,

            raise_on_error=
                False,
        )
    )

    assert (
        broken_date_result[
            "valid"
        ]
        is False
    )

    print(
        "T09 Unsupported date blocked:",
        "PASS"
    )

    # ========================================================
    # T10 VERIFICATION ESCALATION BLOCK
    # ========================================================

    verification_test = json.loads(
        json.dumps(
            timeline
        )
    )

    verification_test[
        "events"
    ][
        0
    ][
        "verification_state"
    ] = "verified"

    verification_path = (
        timeline_dir
        / "timeline_validator_v1_broken_verification.json"
    )

    write_json(
        verification_path,
        verification_test,
    )

    verification_result = (
        validate_timeline(
            timeline_path=
                verification_path,

            expected_case_id=
                case_id,

            raise_on_error=
                False,
        )
    )

    assert (
        verification_result[
            "valid"
        ]
        is False
    )

    print(
        "T10 Verification escalation blocked:",
        "PASS"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()

    print(
        "Case:",
        case_id,
    )

    print(
        "Canonical fact:",
        len(
            fact_index
        ),
    )

    print(
        "Document:",
        len(
            document_index
        ),
    )

    print(
        "Demo timeline event:",
        len(
            timeline[
                "events"
            ]
        ),
    )

    print(
        "Warnings:",
        len(
            result[
                "warnings"
            ]
        ),
    )

    if result[
        "warnings"
    ]:

        for warning in result[
            "warnings"
        ]:

            print(
                "-",
                warning,
            )

    print()

    print(
        "======================================"
    )

    print(
        " TIMELINE VALIDATOR V1: 10/10 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# WRITE JSON
# ============================================================

def write_json(
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

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Timeline Validator V1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--timeline",
        dest="timeline_path",
        default=None,
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Varsayılan kullanım:
    #
    # python src\timeline_validator.py
    #
    # doğrudan self-test çalıştırır.
    # --------------------------------------------------------

    if (
        args.self_test
        or args.timeline_path is None
    ):

        run_self_test(
            args.case_id
        )

        return

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - TIMELINE VALIDATOR V1"
    )

    print(
        "======================================"
    )

    result = (
        validate_timeline(
            timeline_path=
                Path(
                    args.timeline_path
                ),

            expected_case_id=
                args.case_id,

            raise_on_error=
                False,
        )
    )

    print()

    print(
        "Case:",
        result[
            "case_id"
        ],
    )

    print(
        "Event:",
        result[
            "event_count"
        ],
    )

    print(
        "Canonical fact:",
        result[
            "canonical_fact_count"
        ],
    )

    print(
        "Document:",
        result[
            "document_count"
        ],
    )

    if result[
        "errors"
    ]:

        print()

        print(
            "Errors:"
        )

        for error in result[
            "errors"
        ]:

            print(
                "-",
                error,
            )

    if result[
        "warnings"
    ]:

        print()

        print(
            "Warnings:"
        )

        for warning in result[
            "warnings"
        ]:

            print(
                "-",
                warning,
            )

    print()

    print(
        "======================================"
    )

    if result[
        "valid"
    ]:

        print(
            " TIMELINE VALIDATOR V1: PASS"
        )

    else:

        print(
            " TIMELINE VALIDATOR V1: FAIL"
        )

        sys.exit(
            1
        )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()