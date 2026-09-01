# ============================================================
# VERGİ AI - DEADLINE VALIDATOR V1
#
# AMAÇ:
#
# Deadline Engine çıktısını iki seviyede doğrulamak:
#
# 1. JSON Schema
# 2. Canonical Timeline / semantic safety
#
#
# TEMEL PRENSİP:
#
# Deadline hesabı yalnız güvenilir bir timeline event'e
# dayanabilir.
#
#
# ÖRNEK:
#
# Canonical timeline:
#
#   event_type = notification_date
#   date = 2026-02-10
#   verification_state = unverified
#
# Deadline çıktısı:
#
#   ❌ calculated
#   ❌ 2026-03-12 kesin son tarih
#
# yerine:
#
#   ✅ blocked_unverified_anchor
#   ✅ calculated_deadline = null
#   ✅ requires_human_review = true
#
#
# DİĞER PRENSİPLER:
#
# - Deadline Validator yeni hukuk kuralı oluşturmaz.
# - Süre hesabı yapmaz.
# - Rule seçmez.
# - Canonical timeline event'i değiştirmez.
# - Verification seviyesini yükseltmez.
# - Expired/active kararı V1'de verilmez.
# ============================================================


import argparse
import json
import sys

from collections import Counter
from datetime import datetime
from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)

from timeline_validator import (
    validate_timeline,
)


# ============================================================
# VERSION
# ============================================================

DEADLINE_VALIDATOR_VERSION = "1"


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

DEADLINE_SCHEMA_PATH = (
    DATA_DIR
    / "case_deadline.schema.json"
)

DEFAULT_CASE_ID = "case_0001"

DEFAULT_DEADLINE_PATH = (
    CASES_DIR
    / DEFAULT_CASE_ID
    / "deadlines"
    / "deadlines.json"
)


# ============================================================
# EXCEPTIONS
# ============================================================

class DeadlineValidationError(
    Exception
):
    pass


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(
    path,
):

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
# DATE / DATETIME
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

        return datetime.strptime(
            value,
            "%Y-%m-%d",
        ).date()

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
# CASE
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

        raise DeadlineValidationError(
            "case.json case_id uyuşmazlığı.\n"
            f"Beklenen: {case_id}\n"
            f"Bulunan: {case_data.get('case_id')}"
        )

    return (
        case_data,
        case_path,
    )


# ============================================================
# CANONICAL TIMELINE
# ============================================================

def load_canonical_timeline(
    case_id,
):

    timeline_path = (
        CASES_DIR
        / case_id
        / "timeline"
        / "timeline.json"
    )

    timeline = load_json(
        timeline_path
    )

    if (
        timeline.get(
            "case_id"
        )
        != case_id
    ):

        raise DeadlineValidationError(
            "Canonical timeline case_id uyuşmazlığı."
        )

    # --------------------------------------------------------
    # Canonical timeline kendi validator'ünden de geçmeli.
    # --------------------------------------------------------

    validation = (
        validate_timeline(
            timeline_path=
                timeline_path,

            expected_case_id=
                case_id,

            raise_on_error=
                False,
        )
    )

    if not validation[
        "valid"
    ]:

        raise DeadlineValidationError(
            "Canonical timeline geçerli değil:\n- "
            + "\n- ".join(
                validation[
                    "errors"
                ]
            )
        )

    event_index = {}

    for event in timeline.get(
        "events",
        [],
    ):

        event_id = event.get(
            "event_id"
        )

        if not event_id:

            raise DeadlineValidationError(
                "Canonical timeline event içinde "
                "event_id bulunamadı."
            )

        if event_id in event_index:

            raise DeadlineValidationError(
                "Canonical timeline duplicate event_id: "
                f"{event_id}"
            )

        event_index[
            event_id
        ] = event

    return {
        "timeline":
            timeline,

        "timeline_path":
            timeline_path,

        "events":
            event_index,

        "validation":
            validation,
    }


# ============================================================
# JSON SCHEMA
# ============================================================

def validate_schema(
    deadline_analysis,
):

    schema = load_json(
        DEADLINE_SCHEMA_PATH
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
            deadline_analysis
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

            messages.append(
                f"{path}: {error.message}"
            )

        else:

            messages.append(
                error.message
            )

    return messages


# ============================================================
# UNIQUE DEADLINE IDS
# ============================================================

def validate_unique_deadline_ids(
    deadlines,
):

    errors = []

    deadline_ids = [
        item.get(
            "deadline_id"
        )
        for item in deadlines
        if isinstance(
            item,
            dict,
        )
        and item.get(
            "deadline_id"
        )
    ]

    counts = Counter(
        deadline_ids
    )

    for (
        deadline_id,
        count,
    ) in counts.items():

        if count > 1:

            errors.append(
                "Duplicate deadline_id: "
                f"{deadline_id}"
            )

    return errors


# ============================================================
# ANCHOR EVENT
# ============================================================

def validate_anchor_event(
    deadline,
    event_index,
):

    errors = []

    warnings = []

    deadline_id = deadline.get(
        "deadline_id"
    )

    anchor_event_id = deadline.get(
        "anchor_event_id"
    )

    event = event_index.get(
        anchor_event_id
    )

    if event is None:

        errors.append(
            f"{deadline_id}: anchor_event_id "
            f"canonical timeline içinde bulunamadı: "
            f"{anchor_event_id}"
        )

        return (
            errors,
            warnings,
            None,
        )

    # ========================================================
    # ANCHOR DATE
    # ========================================================

    anchor_date = deadline.get(
        "anchor_date"
    )

    event_date = event.get(
        "date"
    )

    if (
        anchor_date
        != event_date
    ):

        errors.append(
            f"{deadline_id}: anchor_date canonical "
            "timeline event tarihiyle uyuşmuyor. "
            f"Deadline={anchor_date}, "
            f"Timeline={event_date}"
        )

    # ========================================================
    # VERIFICATION STATE
    # ========================================================

    deadline_verification = (
        deadline.get(
            "anchor_verification_state"
        )
    )

    event_verification = (
        event.get(
            "verification_state"
        )
    )

    if (
        deadline_verification
        != event_verification
    ):

        errors.append(
            f"{deadline_id}: anchor_verification_state "
            "canonical timeline event ile birebir "
            "eşleşmelidir. "
            f"Deadline={deadline_verification}, "
            f"Timeline={event_verification}"
        )

    # ========================================================
    # DEADLINE RELEVANCE
    # ========================================================

    if (
        event.get(
            "deadline_relevant"
        )
        is not True
    ):

        warnings.append(
            f"{deadline_id}: anchor event "
            "deadline_relevant=True olarak işaretli değil."
        )

    return (
        errors,
        warnings,
        event,
    )


# ============================================================
# CALCULATION STATE
# ============================================================

def validate_calculation_state(
    deadline,
    anchor_event,
):

    errors = []

    warnings = []

    deadline_id = deadline.get(
        "deadline_id"
    )

    calculation_state = (
        deadline.get(
            "calculation_state"
        )
    )

    calculated_deadline = (
        deadline.get(
            "calculated_deadline"
        )
    )

    requires_human_review = (
        deadline.get(
            "requires_human_review"
        )
    )

    anchor_verification = (
        deadline.get(
            "anchor_verification_state"
        )
    )

    # ========================================================
    # CALCULATED
    # ========================================================

    if calculation_state == "calculated":

        # ----------------------------------------------------
        # EN KRİTİK GÜVENLİK KURALI
        # ----------------------------------------------------

        if anchor_verification != "verified":

            errors.append(
                f"{deadline_id}: calculation_state='calculated' "
                "olamaz çünkü anchor event verified değil. "
                f"anchor_verification_state="
                f"'{anchor_verification}'"
            )

        if (
            anchor_event
            and anchor_event.get(
                "date_precision"
            )
            != "exact"
        ):

            errors.append(
                f"{deadline_id}: calculated deadline için "
                "anchor event date_precision='exact' olmalıdır."
            )

        if calculated_deadline is None:

            errors.append(
                f"{deadline_id}: calculation_state='calculated' "
                "iken calculated_deadline null olamaz."
            )

        if (
            deadline.get(
                "start_rule"
            )
            == "unknown"
        ):

            errors.append(
                f"{deadline_id}: calculated deadline için "
                "start_rule='unknown' olamaz."
            )

        if not deadline.get(
            "legal_basis_refs"
        ):

            errors.append(
                f"{deadline_id}: calculated deadline için "
                "en az bir legal_basis_ref gereklidir."
            )

    # ========================================================
    # BLOCKED UNVERIFIED ANCHOR
    # ========================================================

    elif (
        calculation_state
        == "blocked_unverified_anchor"
    ):

        if anchor_verification == "verified":

            errors.append(
                f"{deadline_id}: anchor verified olduğu halde "
                "calculation_state="
                "'blocked_unverified_anchor' olamaz."
            )

        if calculated_deadline is not None:

            errors.append(
                f"{deadline_id}: "
                "blocked_unverified_anchor durumunda "
                "calculated_deadline null olmalıdır."
            )

        if requires_human_review is not True:

            errors.append(
                f"{deadline_id}: "
                "blocked_unverified_anchor durumunda "
                "requires_human_review=True olmalıdır."
            )

    # ========================================================
    # BLOCKED MISSING RULE
    # ========================================================

    elif (
        calculation_state
        == "blocked_missing_rule"
    ):

        if calculated_deadline is not None:

            errors.append(
                f"{deadline_id}: blocked_missing_rule "
                "durumunda calculated_deadline null olmalıdır."
            )

        if requires_human_review is not True:

            errors.append(
                f"{deadline_id}: blocked_missing_rule "
                "durumunda requires_human_review=True "
                "olmalıdır."
            )

    # ========================================================
    # BLOCKED AMBIGUOUS RULE
    # ========================================================

    elif (
        calculation_state
        == "blocked_ambiguous_rule"
    ):

        if calculated_deadline is not None:

            errors.append(
                f"{deadline_id}: blocked_ambiguous_rule "
                "durumunda calculated_deadline null olmalıdır."
            )

        if requires_human_review is not True:

            errors.append(
                f"{deadline_id}: blocked_ambiguous_rule "
                "durumunda requires_human_review=True "
                "olmalıdır."
            )

    # ========================================================
    # NEEDS REVIEW
    # ========================================================

    elif calculation_state == "needs_review":

        if requires_human_review is not True:

            errors.append(
                f"{deadline_id}: needs_review durumunda "
                "requires_human_review=True olmalıdır."
            )

        # V1 güvenlik politikası:
        #
        # uncertain hesap sonucu canonical deadline alanına
        # yazılmaz.

        if calculated_deadline is not None:

            errors.append(
                f"{deadline_id}: V1'de needs_review "
                "durumunda calculated_deadline null olmalıdır."
            )

    # ========================================================
    # NOT APPLICABLE
    # ========================================================

    elif calculation_state == "not_applicable":

        if calculated_deadline is not None:

            errors.append(
                f"{deadline_id}: not_applicable durumunda "
                "calculated_deadline null olmalıdır."
            )

    # ========================================================
    # UNVERIFIED ANCHOR GUARD
    #
    # State adı ne olursa olsun ikinci bir güvenlik katmanı.
    # ========================================================

    if (
        anchor_verification
        != "verified"
        and calculation_state
        == "calculated"
    ):

        errors.append(
            f"{deadline_id}: unverified/partially verified/"
            "disputed/rejected anchor üzerinden kesin "
            "deadline üretimi yasaktır."
        )

    # ========================================================
    # DATE PRECISION
    # ========================================================

    if (
        anchor_event
        and anchor_event.get(
            "date_precision"
        )
        != "exact"
        and calculation_state
        == "calculated"
    ):

        errors.append(
            f"{deadline_id}: exact olmayan anchor tarihi "
            "üzerinden kesin deadline üretilemez."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# CALCULATED DEADLINE FORMAT
# ============================================================

def validate_calculated_deadline_date(
    deadline,
):

    errors = []

    deadline_id = deadline.get(
        "deadline_id"
    )

    calculated_deadline = (
        deadline.get(
            "calculated_deadline"
        )
    )

    if calculated_deadline is None:

        return errors

    if (
        parse_iso_date(
            calculated_deadline
        )
        is None
    ):

        errors.append(
            f"{deadline_id}: calculated_deadline "
            "geçerli ISO date değil: "
            f"{calculated_deadline}"
        )

    return errors


# ============================================================
# EXPIRY STATE
# ============================================================

def validate_expiry_state(
    deadline,
):

    errors = []

    warnings = []

    deadline_id = deadline.get(
        "deadline_id"
    )

    expiry_state = deadline.get(
        "expiry_state"
    )

    calculation_state = deadline.get(
        "calculation_state"
    )

    # --------------------------------------------------------
    # Hesaplanmamış deadline aktif/expired olamaz.
    # --------------------------------------------------------

    if (
        calculation_state
        != "calculated"
        and expiry_state
        in {
            "active",
            "expired",
        }
    ):

        errors.append(
            f"{deadline_id}: hesaplanmamış deadline için "
            f"expiry_state='{expiry_state}' olamaz."
        )

    # --------------------------------------------------------
    # V1 schema'da evaluation_date/as_of_date yok.
    #
    # Bu nedenle "bugün itibarıyla expired" gibi karar
    # yeniden üretilebilir değildir.
    #
    # V1'de active/expired kullanımı bloklanır.
    # --------------------------------------------------------

    if expiry_state in {
        "active",
        "expired",
    }:

        errors.append(
            f"{deadline_id}: Deadline V1'de "
            f"expiry_state='{expiry_state}' kullanılamaz. "
            "Expiry değerlendirmesi için gelecekte açık "
            "evaluation/as_of tarihi gereklidir."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# DURATION
# ============================================================

def validate_duration(
    deadline,
):

    errors = []

    warnings = []

    deadline_id = deadline.get(
        "deadline_id"
    )

    duration = deadline.get(
        "duration"
    )

    if not isinstance(
        duration,
        dict,
    ):

        return (
            errors,
            warnings,
        )

    value = duration.get(
        "value"
    )

    unit = duration.get(
        "unit"
    )

    day_type = duration.get(
        "day_type"
    )

    if (
        isinstance(
            value,
            int,
        )
        and value == 0
        and deadline.get(
            "calculation_state"
        )
        == "calculated"
    ):

        warnings.append(
            f"{deadline_id}: calculated deadline "
            "duration.value=0. Rule doğruluğu ayrıca "
            "kontrol edilmelidir."
        )

    if (
        unit != "day"
        and day_type
        == "business"
    ):

        warnings.append(
            f"{deadline_id}: day_type='business' ancak "
            f"duration.unit='{unit}'. Rule semantiği "
            "kontrol edilmelidir."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# TOP LEVEL STATUS
# ============================================================

def validate_analysis_status(
    deadline_analysis,
):

    errors = []

    status = deadline_analysis.get(
        "status"
    )

    deadlines = deadline_analysis.get(
        "deadlines"
    )

    if not isinstance(
        deadlines,
        list,
    ):

        return errors

    if (
        status == "completed"
        and len(
            deadlines
        ) == 0
    ):

        errors.append(
            "status='completed' deadline analysis "
            "en az bir deadline candidate içermelidir."
        )

    return errors


# ============================================================
# GENERATED AT
# ============================================================

def validate_generated_at(
    deadline_analysis,
):

    errors = []

    generated_at = (
        deadline_analysis.get(
            "generated_at"
        )
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
    deadline_analysis,
    expected_case_id,
):

    errors = []

    found = deadline_analysis.get(
        "case_id"
    )

    if found != expected_case_id:

        errors.append(
            "Deadline analysis case_id uyuşmazlığı. "
            f"Beklenen={expected_case_id}, "
            f"Bulunan={found}"
        )

    return errors


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_deadline_analysis(
    deadline_path,
    expected_case_id=None,
    raise_on_error=False,
):

    deadline_path = Path(
        deadline_path
    )

    deadline_analysis = load_json(
        deadline_path
    )

    case_id = (
        expected_case_id
        or deadline_analysis.get(
            "case_id"
        )
    )

    if not case_id:

        raise DeadlineValidationError(
            "case_id belirlenemedi."
        )

    # ========================================================
    # CONTEXT
    # ========================================================

    case_data, case_path = (
        load_case(
            case_id
        )
    )

    canonical_timeline = (
        load_canonical_timeline(
            case_id
        )
    )

    event_index = (
        canonical_timeline[
            "events"
        ]
    )

    errors = []

    warnings = []

    # ========================================================
    # SCHEMA
    # ========================================================

    errors.extend(
        validate_schema(
            deadline_analysis
        )
    )

    # ========================================================
    # TOP LEVEL
    # ========================================================

    errors.extend(
        validate_case_id(
            deadline_analysis,
            case_id,
        )
    )

    errors.extend(
        validate_generated_at(
            deadline_analysis
        )
    )

    errors.extend(
        validate_analysis_status(
            deadline_analysis
        )
    )

    deadlines = deadline_analysis.get(
        "deadlines",
        [],
    )

    if not isinstance(
        deadlines,
        list,
    ):

        deadlines = []

    # ========================================================
    # UNIQUE IDS
    # ========================================================

    errors.extend(
        validate_unique_deadline_ids(
            deadlines
        )
    )

    # ========================================================
    # DEADLINES
    # ========================================================

    for deadline in deadlines:

        if not isinstance(
            deadline,
            dict,
        ):

            continue

        (
            anchor_errors,
            anchor_warnings,
            anchor_event,
        ) = (
            validate_anchor_event(
                deadline,
                event_index,
            )
        )

        errors.extend(
            anchor_errors
        )

        warnings.extend(
            anchor_warnings
        )

        (
            calculation_errors,
            calculation_warnings,
        ) = (
            validate_calculation_state(
                deadline,
                anchor_event,
            )
        )

        errors.extend(
            calculation_errors
        )

        warnings.extend(
            calculation_warnings
        )

        errors.extend(
            validate_calculated_deadline_date(
                deadline
            )
        )

        (
            expiry_errors,
            expiry_warnings,
        ) = (
            validate_expiry_state(
                deadline
            )
        )

        errors.extend(
            expiry_errors
        )

        warnings.extend(
            expiry_warnings
        )

        (
            duration_errors,
            duration_warnings,
        ) = (
            validate_duration(
                deadline
            )
        )

        errors.extend(
            duration_errors
        )

        warnings.extend(
            duration_warnings
        )

    # ========================================================
    # DEDUP
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
            len(
                errors
            ) == 0,

        "validator_version":
            DEADLINE_VALIDATOR_VERSION,

        "deadline_path":
            str(
                deadline_path
            ),

        "case_id":
            case_id,

        "case_path":
            str(
                case_path
            ),

        "timeline_path":
            str(
                canonical_timeline[
                    "timeline_path"
                ]
            ),

        "timeline_event_count":
            len(
                event_index
            ),

        "deadline_count":
            len(
                deadlines
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

        raise DeadlineValidationError(
            "DEADLINE VALIDATOR V1: FAIL\n\n- "
            + "\n- ".join(
                errors
            )
        )

    return result


# ============================================================
# DEMO DEADLINE
# ============================================================

def create_demo_deadline_analysis(
    case_id,
):

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    events = list(
        timeline_context[
            "events"
        ].values()
    )

    # --------------------------------------------------------
    # Deadline-relevant canonical event seç.
    # case_0001 için:
    #
    # notification_date 2026-02-10
    # unverified
    # --------------------------------------------------------

    anchor_event = next(
        (
            event
            for event in events
            if event.get(
                "deadline_relevant"
            )
            is True
        ),
        None,
    )

    if anchor_event is None:

        raise DeadlineValidationError(
            "Self-test için deadline_relevant "
            "canonical timeline event bulunamadı."
        )

    anchor_state = anchor_event.get(
        "verification_state"
    )

    # --------------------------------------------------------
    # Anchor verified değilse hesap BLOKLANIR.
    # --------------------------------------------------------

    if anchor_state == "verified":

        calculation_state = (
            "needs_review"
        )

    else:

        calculation_state = (
            "blocked_unverified_anchor"
        )

    return {
        "schema_version":
            1,

        "deadline_analysis_id":
            f"deadline_{case_id}_demo_v1",

        "case_id":
            case_id,

        "status":
            "completed",

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "deadlines": [
            {
                "deadline_id":
                    "deadline_001",

                "deadline_type":
                    "lawsuit_filing",

                "description":
                    (
                        "İhbarname tebliğine bağlı olası "
                        "dava açma süresi adayı."
                    ),

                "anchor_event_id":
                    anchor_event[
                        "event_id"
                    ],

                "anchor_date":
                    anchor_event[
                        "date"
                    ],

                "anchor_verification_state":
                    anchor_state,

                "rule_id":
                    "rule_pending_tax_lawsuit_filing_v1",

                "legal_basis_refs":
                    [],

                "duration": {
                    "value":
                        30,

                    "unit":
                        "day",

                    "day_type":
                        "calendar",
                },

                "start_rule":
                    "next_day",

                "calculation_state":
                    calculation_state,

                "calculated_deadline":
                    None,

                "expiry_state":
                    "not_evaluated",

                "confidence":
                    float(
                        anchor_event.get(
                            "confidence",
                            0.5,
                        )
                    ),

                "requires_human_review":
                    True,

                "notes":
                    (
                        "Canonical anchor event verified "
                        "olmadığı için kesin deadline "
                        "hesaplanmamıştır."
                    ),
            }
        ],

        "warnings": [
            (
                "Canonical anchor event doğrulanmadığı için "
                "kesin son tarih üretilmemiştir."
            )
        ],

        "notes":
            (
                "Deadline Validator V1 self-test fixture. "
                "Hukuki süre hesabı yapılmamıştır."
            ),
    }


# ============================================================
# JSON DEEP COPY
# ============================================================

def clone_json(
    value,
):

    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
        )
    )


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
        " VERGİ AI - DEADLINE VALIDATOR V1"
    )

    print(
        "======================================"
    )

    # ========================================================
    # T01 SCHEMA LOAD
    # ========================================================

    assert (
        DEADLINE_SCHEMA_PATH.exists()
    )

    load_json(
        DEADLINE_SCHEMA_PATH
    )

    print(
        "T01 Deadline schema load:",
        "PASS"
    )

    # ========================================================
    # T02 CANONICAL TIMELINE
    # ========================================================

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    assert (
        len(
            timeline_context[
                "events"
            ]
        )
        >= 1
    )

    print(
        "T02 Canonical timeline load:",
        "PASS"
    )

    # ========================================================
    # T03 DEMO BUILD
    # ========================================================

    demo = (
        create_demo_deadline_analysis(
            case_id
        )
    )

    assert (
        len(
            demo[
                "deadlines"
            ]
        )
        == 1
    )

    print(
        "T03 Safe deadline candidate build:",
        "PASS"
    )

    deadline_dir = (
        CASES_DIR
        / case_id
        / "deadlines"
    )

    deadline_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ========================================================
    # T04 VALID BLOCKED DEADLINE
    # ========================================================

    valid_path = (
        deadline_dir
        / "deadline_validator_v1_test.json"
    )

    write_json(
        valid_path,
        demo,
    )

    result = (
        validate_deadline_analysis(
            deadline_path=
                valid_path,

            expected_case_id=
                case_id,

            raise_on_error=
                False,
        )
    )

    if not result[
        "valid"
    ]:

        print()

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
        "T04 Safe blocked deadline:",
        "PASS"
    )

    # ========================================================
    # T05 UNKNOWN ANCHOR
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "deadlines"
    ][
        0
    ][
        "anchor_event_id"
    ] = "timeline_event_does_not_exist"

    broken_path = (
        deadline_dir
        / "deadline_validator_v1_unknown_anchor.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_deadline_analysis(
            broken_path,
            case_id,
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T05 Unknown anchor blocked:",
        "PASS"
    )

    # ========================================================
    # T06 ANCHOR DATE MISMATCH
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "deadlines"
    ][
        0
    ][
        "anchor_date"
    ] = "2099-12-31"

    broken_path = (
        deadline_dir
        / "deadline_validator_v1_anchor_date.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_deadline_analysis(
            broken_path,
            case_id,
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T06 Anchor date mismatch blocked:",
        "PASS"
    )

    # ========================================================
    # T07 VERIFICATION MISMATCH
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "deadlines"
    ][
        0
    ][
        "anchor_verification_state"
    ] = "verified"

    broken_path = (
        deadline_dir
        / "deadline_validator_v1_verification.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_deadline_analysis(
            broken_path,
            case_id,
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T07 Verification mismatch blocked:",
        "PASS"
    )

    # ========================================================
    # T08 UNVERIFIED -> CALCULATED BLOCK
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "deadlines"
    ][
        0
    ][
        "calculation_state"
    ] = "calculated"

    broken[
        "deadlines"
    ][
        0
    ][
        "calculated_deadline"
    ] = "2026-03-12"

    broken[
        "deadlines"
    ][
        0
    ][
        "legal_basis_refs"
    ] = [
        "TEST_RULE"
    ]

    broken_path = (
        deadline_dir
        / "deadline_validator_v1_unverified_calculated.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_deadline_analysis(
            broken_path,
            case_id,
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T08 Unverified calculation blocked:",
        "PASS"
    )

    # ========================================================
    # T09 BLOCKED + DEADLINE VALUE
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "deadlines"
    ][
        0
    ][
        "calculated_deadline"
    ] = "2026-03-12"

    broken_path = (
        deadline_dir
        / "deadline_validator_v1_blocked_date.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_deadline_analysis(
            broken_path,
            case_id,
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T09 Blocked deadline value blocked:",
        "PASS"
    )

    # ========================================================
    # T10 HUMAN REVIEW REQUIRED
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "deadlines"
    ][
        0
    ][
        "requires_human_review"
    ] = False

    broken_path = (
        deadline_dir
        / "deadline_validator_v1_human_review.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_deadline_analysis(
            broken_path,
            case_id,
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T10 Human review guard:",
        "PASS"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    anchor = (
        demo[
            "deadlines"
        ][
            0
        ]
    )

    print()

    print(
        "Case:",
        case_id,
    )

    print(
        "Canonical timeline event:",
        len(
            timeline_context[
                "events"
            ]
        ),
    )

    print(
        "Anchor event:",
        anchor[
            "anchor_event_id"
        ],
    )

    print(
        "Anchor date:",
        anchor[
            "anchor_date"
        ],
    )

    print(
        "Anchor verification:",
        anchor[
            "anchor_verification_state"
        ],
    )

    print(
        "Calculation state:",
        anchor[
            "calculation_state"
        ],
    )

    print(
        "Calculated deadline:",
        anchor[
            "calculated_deadline"
        ],
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE VALIDATOR V1: 10/10 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Deadline Validator V1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--deadline",
        dest="deadline_path",
        default=None,
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Varsayılan:
    #
    # python src\deadline_validator.py
    #
    # self-test çalıştırır.
    # --------------------------------------------------------

    if (
        args.self_test
        or args.deadline_path is None
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
        " VERGİ AI - DEADLINE VALIDATOR V1"
    )

    print(
        "======================================"
    )

    try:

        result = (
            validate_deadline_analysis(
                deadline_path=
                    Path(
                        args.deadline_path
                    ),

                expected_case_id=
                    args.case_id,

                raise_on_error=
                    False,
            )
        )

    except Exception as error:

        print()

        print(
            "VALIDATION ERROR"
        )

        print(
            error
        )

        print()

        print(
            "======================================"
        )

        print(
            " DEADLINE VALIDATOR V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )

    print()

    print(
        "Case:",
        result[
            "case_id"
        ],
    )

    print(
        "Canonical timeline event:",
        result[
            "timeline_event_count"
        ],
    )

    print(
        "Deadline:",
        result[
            "deadline_count"
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
            " DEADLINE VALIDATOR V1: PASS"
        )

    else:

        print(
            " DEADLINE VALIDATOR V1: FAIL"
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