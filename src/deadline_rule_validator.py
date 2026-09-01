# ============================================================
# VERGİ AI - DEADLINE RULE VALIDATOR V1
#
# AMAÇ:
#
# Deadline Rule Registry içindeki kuralları:
#
# 1. JSON Schema
# 2. Semantic integrity
# 3. Version / temporal consistency
# 4. Calculation safety
#
# açısından doğrulamak.
#
#
# KRİTİK PRENSİPLER
# ------------------
#
# - Draft hukuk kuralı hesaplama yapamaz.
#
# - Deprecated hukuk kuralı hesaplama yapamaz.
#
# - Active + calculation_enabled kuralın
#   legal_basis_refs alanı boş olamaz.
#
# - Placeholder legal reference ile aktif hesap yapılamaz.
#
# - Aynı rule_id + rule_version duplicate olamaz.
#
# - Aynı rule_id'nin active versiyonlarının geçerlilik
#   tarihleri çakışamaz.
#
# - required_anchor_verification her zaman "verified"
#   olmalıdır.
#
# - Custom hesap politikaları human review gerektirir.
#
#
# NOT:
#
# Bu validator hukuki kuralın maddi olarak doğru olduğunu
# KANITLAMAZ.
#
# Yalnız kural registry'sinin güvenli ve tutarlı olmasını
# sağlar.
#
# Gerçek hukuk kaynağı çözümlemesi ileride Legal Knowledge
# Engine ile ayrıca yapılacaktır.
# ============================================================


import argparse
import json
import sys

from collections import Counter
from datetime import date
from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


# ============================================================
# VERSION
# ============================================================

DEADLINE_RULE_VALIDATOR_VERSION = "1"


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

DEADLINE_RULE_SCHEMA_PATH = (
    DATA_DIR
    / "deadline_rule.schema.json"
)

DEADLINE_RULES_DIR = (
    DATA_DIR
    / "deadline_rules"
)

DEFAULT_RULESET_PATH = (
    DEADLINE_RULES_DIR
    / "deadline_rules.json"
)


# ============================================================
# EXCEPTION
# ============================================================

class DeadlineRuleValidationError(
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
# DATE
# ============================================================

def parse_date(
    value,
):

    if value is None:

        return None

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


# ============================================================
# SCHEMA
# ============================================================

def validate_schema(
    ruleset,
):

    schema = load_json(
        DEADLINE_RULE_SCHEMA_PATH
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
            ruleset
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
# PLACEHOLDER LEGAL REFERENCES
# ============================================================

PLACEHOLDER_PREFIXES = (
    "test",
    "todo",
    "pending",
    "unknown",
    "placeholder",
    "dummy",
    "temp",
)


def is_placeholder_legal_ref(
    value,
):

    if not isinstance(
        value,
        str,
    ):

        return True

    normalized = (
        value
        .strip()
        .casefold()
    )

    if not normalized:

        return True

    return any(
        normalized.startswith(
            prefix
        )
        for prefix in PLACEHOLDER_PREFIXES
    )


# ============================================================
# UNIQUE RULE VERSION
# ============================================================

def validate_unique_rule_versions(
    rules,
):

    errors = []

    keys = []

    for rule in rules:

        if not isinstance(
            rule,
            dict,
        ):

            continue

        rule_id = rule.get(
            "rule_id"
        )

        rule_version = rule.get(
            "rule_version"
        )

        if (
            rule_id
            and rule_version
        ):

            keys.append(
                (
                    rule_id,
                    rule_version,
                )
            )

    counts = Counter(
        keys
    )

    for (
        rule_id,
        rule_version,
    ), count in counts.items():

        if count > 1:

            errors.append(
                "Duplicate rule_id + rule_version: "
                f"{rule_id} / {rule_version}"
            )

    return errors


# ============================================================
# EFFECTIVE DATE RANGE
# ============================================================

def validate_effective_range(
    rule,
):

    errors = []

    warnings = []

    rule_id = rule.get(
        "rule_id"
    )

    effective_from = parse_date(
        rule.get(
            "effective_from"
        )
    )

    effective_to = parse_date(
        rule.get(
            "effective_to"
        )
    )

    if (
        effective_from
        and effective_to
        and effective_from > effective_to
    ):

        errors.append(
            f"{rule_id}: effective_from "
            "effective_to tarihinden sonra olamaz."
        )

    if (
        rule.get(
            "status"
        )
        == "active"
        and effective_from is None
    ):

        warnings.append(
            f"{rule_id}: active rule için "
            "effective_from belirtilmemiş. "
            "Temporal applicability ayrıca "
            "insan tarafından kontrol edilmelidir."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# LEGAL BASIS
# ============================================================

def validate_legal_basis(
    rule,
):

    errors = []

    rule_id = rule.get(
        "rule_id"
    )

    status = rule.get(
        "status"
    )

    calculation_enabled = (
        rule.get(
            "calculation_enabled"
        )
    )

    legal_basis_refs = (
        rule.get(
            "legal_basis_refs",
            []
        )
    )

    # --------------------------------------------------------
    # Active + enabled hukuk kuralı kaynaksız çalışamaz.
    # --------------------------------------------------------

    if (
        status == "active"
        and calculation_enabled is True
        and not legal_basis_refs
    ):

        errors.append(
            f"{rule_id}: active ve calculation_enabled "
            "kural en az bir legal_basis_ref içermelidir."
        )

    # --------------------------------------------------------
    # Placeholder ref ile aktif hesap yasak.
    # --------------------------------------------------------

    if (
        status == "active"
        and calculation_enabled is True
    ):

        for legal_ref in legal_basis_refs:

            if is_placeholder_legal_ref(
                legal_ref
            ):

                errors.append(
                    f"{rule_id}: aktif hesap kuralında "
                    "placeholder legal_basis_ref "
                    f"kullanılamaz: {legal_ref}"
                )

    return errors


# ============================================================
# RULE STATUS / CALCULATION
# ============================================================

def validate_calculation_status(
    rule,
):

    errors = []

    rule_id = rule.get(
        "rule_id"
    )

    status = rule.get(
        "status"
    )

    calculation_enabled = (
        rule.get(
            "calculation_enabled"
        )
    )

    if (
        calculation_enabled is True
        and status != "active"
    ):

        errors.append(
            f"{rule_id}: calculation_enabled=True "
            "yalnız status='active' kuralda kullanılabilir. "
            f"Bulunan status='{status}'."
        )

    return errors


# ============================================================
# ANCHOR VERIFICATION
# ============================================================

def validate_anchor_verification(
    rule,
):

    errors = []

    rule_id = rule.get(
        "rule_id"
    )

    required = rule.get(
        "required_anchor_verification"
    )

    if required != "verified":

        errors.append(
            f"{rule_id}: "
            "required_anchor_verification='verified' "
            "olmalıdır."
        )

    return errors


# ============================================================
# DURATION / DAY COUNT POLICY
# ============================================================

def validate_duration_policy(
    rule,
):

    errors = []

    warnings = []

    rule_id = rule.get(
        "rule_id"
    )

    duration = rule.get(
        "duration",
        {}
    )

    if not isinstance(
        duration,
        dict,
    ):

        return (
            errors,
            warnings,
        )

    unit = duration.get(
        "unit"
    )

    value = duration.get(
        "value"
    )

    day_count_policy = (
        rule.get(
            "day_count_policy"
        )
    )

    # ========================================================
    # CALENDAR DAYS
    # ========================================================

    if (
        day_count_policy
        == "calendar_days"
        and unit != "day"
    ):

        errors.append(
            f"{rule_id}: day_count_policy='calendar_days' "
            "ise duration.unit='day' olmalıdır."
        )

    # ========================================================
    # BUSINESS DAYS
    # ========================================================

    if (
        day_count_policy
        == "business_days"
        and unit != "day"
    ):

        errors.append(
            f"{rule_id}: day_count_policy='business_days' "
            "ise duration.unit='day' olmalıdır."
        )

    # ========================================================
    # CALENDAR MONTH
    # ========================================================

    if (
        day_count_policy
        == "calendar_month"
        and unit != "month"
    ):

        errors.append(
            f"{rule_id}: day_count_policy='calendar_month' "
            "ise duration.unit='month' olmalıdır."
        )

    # ========================================================
    # CALENDAR YEAR
    # ========================================================

    if (
        day_count_policy
        == "calendar_year"
        and unit != "year"
    ):

        errors.append(
            f"{rule_id}: day_count_policy='calendar_year' "
            "ise duration.unit='year' olmalıdır."
        )

    # ========================================================
    # ZERO DURATION
    # ========================================================

    if (
        isinstance(
            value,
            int,
        )
        and value == 0
        and rule.get(
            "calculation_enabled"
        )
        is True
    ):

        warnings.append(
            f"{rule_id}: aktif hesap kuralında "
            "duration.value=0. Hukuki kural "
            "ayrıca kontrol edilmelidir."
        )

    return (
        errors,
        warnings,
    )


# ============================================================
# CUSTOM POLICY
# ============================================================

def validate_custom_policy_review(
    rule,
):

    errors = []

    rule_id = rule.get(
        "rule_id"
    )

    requires_human_review = (
        rule.get(
            "requires_human_review"
        )
    )

    custom_used = (
        rule.get(
            "start_rule"
        )
        == "custom"
        or rule.get(
            "day_count_policy"
        )
        == "custom"
        or rule.get(
            "end_day_policy"
        )
        == "custom"
    )

    if (
        custom_used
        and requires_human_review
        is not True
    ):

        errors.append(
            f"{rule_id}: custom deadline policy "
            "requires_human_review=True olmalıdır."
        )

    return errors


# ============================================================
# ACTIVE CALCULATION REVIEW
# ============================================================

def validate_active_rule_review(
    rule,
):

    warnings = []

    rule_id = rule.get(
        "rule_id"
    )

    if (
        rule.get(
            "status"
        )
        == "active"
        and rule.get(
            "calculation_enabled"
        )
        is True
        and rule.get(
            "requires_human_review"
        )
        is True
    ):

        warnings.append(
            f"{rule_id}: hesaplama aktif ancak "
            "requires_human_review=True. "
            "Hesap sonucu otomatik kesinleştirilmemelidir."
        )

    return warnings


# ============================================================
# DATE RANGE OVERLAP
# ============================================================

def ranges_overlap(
    start_a,
    end_a,
    start_b,
    end_b,
):

    # None:
    #
    # effective_from None -> geçmişe açık
    # effective_to   None -> geleceğe açık

    minimum = date.min
    maximum = date.max

    start_a = (
        start_a
        or minimum
    )

    end_a = (
        end_a
        or maximum
    )

    start_b = (
        start_b
        or minimum
    )

    end_b = (
        end_b
        or maximum
    )

    return (
        start_a <= end_b
        and start_b <= end_a
    )


# ============================================================
# ACTIVE VERSION OVERLAP
# ============================================================

def validate_active_version_overlap(
    rules,
):

    errors = []

    grouped = {}

    for rule in rules:

        if not isinstance(
            rule,
            dict,
        ):

            continue

        if (
            rule.get(
                "status"
            )
            != "active"
        ):

            continue

        rule_id = rule.get(
            "rule_id"
        )

        if not rule_id:

            continue

        grouped.setdefault(
            rule_id,
            []
        ).append(
            rule
        )

    for (
        rule_id,
        versions,
    ) in grouped.items():

        for index_a in range(
            len(
                versions
            )
        ):

            for index_b in range(
                index_a + 1,
                len(
                    versions
                ),
            ):

                rule_a = versions[
                    index_a
                ]

                rule_b = versions[
                    index_b
                ]

                start_a = parse_date(
                    rule_a.get(
                        "effective_from"
                    )
                )

                end_a = parse_date(
                    rule_a.get(
                        "effective_to"
                    )
                )

                start_b = parse_date(
                    rule_b.get(
                        "effective_from"
                    )
                )

                end_b = parse_date(
                    rule_b.get(
                        "effective_to"
                    )
                )

                if ranges_overlap(
                    start_a,
                    end_a,
                    start_b,
                    end_b,
                ):

                    errors.append(
                        (
                            f"{rule_id}: active rule "
                            "versiyonlarının geçerlilik "
                            "aralıkları çakışıyor: "
                            f"{rule_a.get('rule_version')} "
                            "ve "
                            f"{rule_b.get('rule_version')}"
                        )
                    )

    return errors


# ============================================================
# EXACT ACTIVE RULE DUPLICATION
# ============================================================

def applicability_signature(
    rule,
):

    applicability = rule.get(
        "applicability",
        {}
    )

    def normalized_list(
        key,
    ):

        values = applicability.get(
            key,
            []
        )

        return tuple(
            sorted(
                str(
                    value
                )
                for value in values
            )
        )

    return (
        rule.get(
            "deadline_type"
        ),

        tuple(
            sorted(
                rule.get(
                    "anchor_event_types",
                    []
                )
            )
        ),

        normalized_list(
            "case_types"
        ),

        normalized_list(
            "tax_types"
        ),

        normalized_list(
            "document_types"
        ),

        normalized_list(
            "case_stages"
        ),

        rule.get(
            "priority"
        ),
    )


def validate_ambiguous_active_rules(
    rules,
):

    warnings = []

    active_rules = [
        rule
        for rule in rules
        if (
            isinstance(
                rule,
                dict,
            )
            and rule.get(
                "status"
            )
            == "active"
            and rule.get(
                "calculation_enabled"
            )
            is True
        )
    ]

    for index_a in range(
        len(
            active_rules
        )
    ):

        for index_b in range(
            index_a + 1,
            len(
                active_rules
            ),
        ):

            rule_a = active_rules[
                index_a
            ]

            rule_b = active_rules[
                index_b
            ]

            if (
                rule_a.get(
                    "rule_id"
                )
                == rule_b.get(
                    "rule_id"
                )
            ):

                continue

            if (
                applicability_signature(
                    rule_a
                )
                != applicability_signature(
                    rule_b
                )
            ):

                continue

            start_a = parse_date(
                rule_a.get(
                    "effective_from"
                )
            )

            end_a = parse_date(
                rule_a.get(
                    "effective_to"
                )
            )

            start_b = parse_date(
                rule_b.get(
                    "effective_from"
                )
            )

            end_b = parse_date(
                rule_b.get(
                    "effective_to"
                )
            )

            if ranges_overlap(
                start_a,
                end_a,
                start_b,
                end_b,
            ):

                warnings.append(
                    (
                        "İki farklı active rule aynı "
                        "applicability + priority alanını "
                        "paylaşıyor. Rule selection sırasında "
                        "ambiguity oluşabilir: "
                        f"{rule_a.get('rule_id')} / "
                        f"{rule_b.get('rule_id')}"
                    )
                )

    return warnings


# ============================================================
# RULE VALIDATION
# ============================================================

def validate_single_rule(
    rule,
):

    errors = []

    warnings = []

    if not isinstance(
        rule,
        dict,
    ):

        return (
            errors,
            warnings,
        )

    (
        effective_errors,
        effective_warnings,
    ) = validate_effective_range(
        rule
    )

    errors.extend(
        effective_errors
    )

    warnings.extend(
        effective_warnings
    )

    errors.extend(
        validate_legal_basis(
            rule
        )
    )

    errors.extend(
        validate_calculation_status(
            rule
        )
    )

    errors.extend(
        validate_anchor_verification(
            rule
        )
    )

    (
        duration_errors,
        duration_warnings,
    ) = validate_duration_policy(
        rule
    )

    errors.extend(
        duration_errors
    )

    warnings.extend(
        duration_warnings
    )

    errors.extend(
        validate_custom_policy_review(
            rule
        )
    )

    warnings.extend(
        validate_active_rule_review(
            rule
        )
    )

    return (
        errors,
        warnings,
    )


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_deadline_rules(
    ruleset_path,
    raise_on_error=False,
):

    ruleset_path = Path(
        ruleset_path
    )

    ruleset = load_json(
        ruleset_path
    )

    errors = []

    warnings = []

    # ========================================================
    # SCHEMA
    # ========================================================

    errors.extend(
        validate_schema(
            ruleset
        )
    )

    rules = ruleset.get(
        "rules",
        []
    )

    if not isinstance(
        rules,
        list,
    ):

        rules = []

    # ========================================================
    # UNIQUE RULE VERSION
    # ========================================================

    errors.extend(
        validate_unique_rule_versions(
            rules
        )
    )

    # ========================================================
    # EACH RULE
    # ========================================================

    for rule in rules:

        (
            rule_errors,
            rule_warnings,
        ) = validate_single_rule(
            rule
        )

        errors.extend(
            rule_errors
        )

        warnings.extend(
            rule_warnings
        )

    # ========================================================
    # TEMPORAL VERSION OVERLAP
    # ========================================================

    errors.extend(
        validate_active_version_overlap(
            rules
        )
    )

    # ========================================================
    # AMBIGUOUS DIFFERENT RULES
    # ========================================================

    warnings.extend(
        validate_ambiguous_active_rules(
            rules
        )
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

    status_counts = {}

    enabled_count = 0

    for rule in rules:

        if not isinstance(
            rule,
            dict,
        ):

            continue

        status = rule.get(
            "status"
        )

        status_counts[
            status
        ] = (
            status_counts.get(
                status,
                0,
            )
            + 1
        )

        if rule.get(
            "calculation_enabled"
        ) is True:

            enabled_count += 1

    result = {
        "valid":
            len(
                errors
            ) == 0,

        "validator_version":
            DEADLINE_RULE_VALIDATOR_VERSION,

        "ruleset_path":
            str(
                ruleset_path
            ),

        "ruleset_id":
            ruleset.get(
                "ruleset_id"
            ),

        "jurisdiction":
            ruleset.get(
                "jurisdiction"
            ),

        "rule_count":
            len(
                rules
            ),

        "status_counts":
            status_counts,

        "calculation_enabled_count":
            enabled_count,

        "errors":
            errors,

        "warnings":
            warnings,
    }

    if (
        raise_on_error
        and errors
    ):

        raise DeadlineRuleValidationError(
            "DEADLINE RULE VALIDATOR V1: FAIL\n\n- "
            + "\n- ".join(
                errors
            )
        )

    return result


# ============================================================
# TEST FIXTURE
# ============================================================

def create_valid_fixture():

    return {
        "schema_version":
            1,

        "ruleset_id":
            "deadline_rules_validator_fixture_v1",

        "jurisdiction":
            "TR",

        "rules": [
            {
                "rule_id":
                    "fixture_rule_001",

                "rule_version":
                    "1.0",

                "name":
                    "Deadline Rule Validator Fixture",

                "status":
                    "active",

                "deadline_type":
                    "other",

                "anchor_event_types": [
                    "notification_date"
                ],

                "applicability": {
                    "case_types": [],

                    "tax_types": [],

                    "document_types": [],

                    "case_stages": [],
                },

                "legal_basis_refs": [
                    "fixture_legal_ref_001"
                ],

                "duration": {
                    "value":
                        1,

                    "unit":
                        "day",
                },

                "start_rule":
                    "next_day",

                "day_count_policy":
                    "calendar_days",

                "end_day_policy":
                    "exact_duration",

                "required_anchor_verification":
                    "verified",

                "calculation_enabled":
                    True,

                "effective_from":
                    "2026-01-01",

                "effective_to":
                    None,

                "priority":
                    100,

                "requires_human_review":
                    False,

                "notes":
                    (
                        "Validator fixture'dır. "
                        "Gerçek hukuk kuralı değildir."
                    ),
            }
        ],

        "notes":
            (
                "Deadline Rule Validator V1 self-test fixture."
            ),
    }


# ============================================================
# SELF TEST
# ============================================================

def run_self_test():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE RULE VALIDATOR V1"
    )

    print(
        "======================================"
    )

    # ========================================================
    # T01 SCHEMA
    # ========================================================

    assert (
        DEADLINE_RULE_SCHEMA_PATH.exists()
    )

    load_json(
        DEADLINE_RULE_SCHEMA_PATH
    )

    print(
        "T01 Deadline rule schema load:",
        "PASS"
    )

    test_dir = (
        DEADLINE_RULES_DIR
        / "validator_tests"
    )

    test_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ========================================================
    # T02 VALID ACTIVE RULE
    # ========================================================

    fixture = create_valid_fixture()

    valid_path = (
        test_dir
        / "deadline_rule_validator_v1_valid.json"
    )

    write_json(
        valid_path,
        fixture,
    )

    result = (
        validate_deadline_rules(
            valid_path
        )
    )

    if not result[
        "valid"
    ]:

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
        "T02 Valid active rule:",
        "PASS"
    )

    # ========================================================
    # T03 DUPLICATE ID + VERSION
    # ========================================================

    broken = clone_json(
        fixture
    )

    broken[
        "rules"
    ].append(
        clone_json(
            broken[
                "rules"
            ][
                0
            ]
        )
    )

    path = (
        test_dir
        / "deadline_rule_validator_v1_duplicate.json"
    )

    write_json(
        path,
        broken,
    )

    broken_result = (
        validate_deadline_rules(
            path
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T03 Duplicate rule version blocked:",
        "PASS"
    )

    # ========================================================
    # T04 MISSING LEGAL BASIS
    # ========================================================

    broken = clone_json(
        fixture
    )

    broken[
        "rules"
    ][
        0
    ][
        "legal_basis_refs"
    ] = []

    path = (
        test_dir
        / "deadline_rule_validator_v1_missing_basis.json"
    )

    write_json(
        path,
        broken,
    )

    broken_result = (
        validate_deadline_rules(
            path
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T04 Missing legal basis blocked:",
        "PASS"
    )

    # ========================================================
    # T05 PLACEHOLDER LEGAL BASIS
    # ========================================================

    broken = clone_json(
        fixture
    )

    broken[
        "rules"
    ][
        0
    ][
        "legal_basis_refs"
    ] = [
        "PENDING_RULE"
    ]

    path = (
        test_dir
        / "deadline_rule_validator_v1_placeholder_basis.json"
    )

    write_json(
        path,
        broken,
    )

    broken_result = (
        validate_deadline_rules(
            path
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T05 Placeholder legal basis blocked:",
        "PASS"
    )

    # ========================================================
    # T06 INVALID EFFECTIVE RANGE
    # ========================================================

    broken = clone_json(
        fixture
    )

    broken[
        "rules"
    ][
        0
    ][
        "effective_from"
    ] = "2026-12-31"

    broken[
        "rules"
    ][
        0
    ][
        "effective_to"
    ] = "2026-01-01"

    path = (
        test_dir
        / "deadline_rule_validator_v1_effective_range.json"
    )

    write_json(
        path,
        broken,
    )

    broken_result = (
        validate_deadline_rules(
            path
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T06 Invalid effective range blocked:",
        "PASS"
    )

    # ========================================================
    # T07 OVERLAPPING ACTIVE VERSIONS
    # ========================================================

    broken = clone_json(
        fixture
    )

    second = clone_json(
        broken[
            "rules"
        ][
            0
        ]
    )

    second[
        "rule_version"
    ] = "2.0"

    second[
        "effective_from"
    ] = "2026-06-01"

    broken[
        "rules"
    ].append(
        second
    )

    path = (
        test_dir
        / "deadline_rule_validator_v1_overlap.json"
    )

    write_json(
        path,
        broken,
    )

    broken_result = (
        validate_deadline_rules(
            path
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T07 Active version overlap blocked:",
        "PASS"
    )

    # ========================================================
    # T08 DRAFT CALCULATION
    # ========================================================

    broken = clone_json(
        fixture
    )

    broken[
        "rules"
    ][
        0
    ][
        "status"
    ] = "draft"

    broken[
        "rules"
    ][
        0
    ][
        "calculation_enabled"
    ] = True

    path = (
        test_dir
        / "deadline_rule_validator_v1_draft_enabled.json"
    )

    write_json(
        path,
        broken,
    )

    broken_result = (
        validate_deadline_rules(
            path
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T08 Draft calculation blocked:",
        "PASS"
    )

    # ========================================================
    # T09 DURATION POLICY MISMATCH
    # ========================================================

    broken = clone_json(
        fixture
    )

    broken[
        "rules"
    ][
        0
    ][
        "day_count_policy"
    ] = "calendar_month"

    broken[
        "rules"
    ][
        0
    ][
        "duration"
    ][
        "unit"
    ] = "day"

    path = (
        test_dir
        / "deadline_rule_validator_v1_duration_policy.json"
    )

    write_json(
        path,
        broken,
    )

    broken_result = (
        validate_deadline_rules(
            path
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T09 Duration policy mismatch blocked:",
        "PASS"
    )

    # ========================================================
    # T10 CUSTOM WITHOUT HUMAN REVIEW
    # ========================================================

    broken = clone_json(
        fixture
    )

    broken[
        "rules"
    ][
        0
    ][
        "start_rule"
    ] = "custom"

    broken[
        "rules"
    ][
        0
    ][
        "requires_human_review"
    ] = False

    path = (
        test_dir
        / "deadline_rule_validator_v1_custom_review.json"
    )

    write_json(
        path,
        broken,
    )

    broken_result = (
        validate_deadline_rules(
            path
        )
    )

    assert (
        broken_result[
            "valid"
        ]
        is False
    )

    print(
        "T10 Custom human review guard:",
        "PASS"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()

    print(
        "Ruleset:",
        result[
            "ruleset_id"
        ],
    )

    print(
        "Jurisdiction:",
        result[
            "jurisdiction"
        ],
    )

    print(
        "Rule:",
        result[
            "rule_count"
        ],
    )

    print(
        "Status:",
        result[
            "status_counts"
        ],
    )

    print(
        "Calculation enabled:",
        result[
            "calculation_enabled_count"
        ],
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE RULE VALIDATOR V1: 10/10 PASS"
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
            "Vergi AI Deadline Rule Validator V1"
        )
    )

    parser.add_argument(
        "--ruleset",
        dest="ruleset_path",
        default=None,
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    args = parser.parse_args()

    if (
        args.self_test
        or args.ruleset_path is None
    ):

        run_self_test()

        return

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE RULE VALIDATOR V1"
    )

    print(
        "======================================"
    )

    try:

        result = (
            validate_deadline_rules(
                ruleset_path=
                    Path(
                        args.ruleset_path
                    ),

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
            " DEADLINE RULE VALIDATOR V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )

    print()

    print(
        "Ruleset:",
        result[
            "ruleset_id"
        ],
    )

    print(
        "Jurisdiction:",
        result[
            "jurisdiction"
        ],
    )

    print(
        "Rule:",
        result[
            "rule_count"
        ],
    )

    print(
        "Status:",
        result[
            "status_counts"
        ],
    )

    print(
        "Calculation enabled:",
        result[
            "calculation_enabled_count"
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
            " DEADLINE RULE VALIDATOR V1: PASS"
        )

    else:

        print(
            " DEADLINE RULE VALIDATOR V1: FAIL"
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