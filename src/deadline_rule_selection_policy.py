# ============================================================
# VERGİ AI - DEADLINE RULE SELECTION POLICY V1
#
# AMAÇ:
#
# Deadline Rule Registry içindeki kurallardan, belirli bir
# canonical timeline event + case bağlamı için uygulanabilir
# kuralı deterministik biçimde seçmek.
#
#
# INPUT
# -----
#
# - Canonical timeline event
# - Case context
# - Deadline Rule Registry
#
#
# OUTPUT
# ------
#
# Selection result:
#
#   selected
#   selected_blocked_anchor
#   no_match
#   ambiguous
#
#
# TEMEL PRENSİPLER
# ----------------
#
# 1. LLM kural seçmez.
#
# 2. Yalnız:
#
#       status = active
#       calculation_enabled = true
#
#    kurallar aday olabilir.
#
# 3. Anchor event type eşleşmelidir.
#
# 4. Rule effective date aralığı anchor date'i kapsamalıdır.
#
# 5. Applicability filtreleri deterministik uygulanır.
#
# 6. Boş applicability listesi wildcard anlamına gelir.
#
# 7. En yüksek priority kazanır.
#
# 8. Aynı en yüksek priority'de birden fazla kural kalırsa:
#
#       FAIL CLOSED -> ambiguous
#
# 9. Anchor verified değilse kural yine tespit edilebilir;
#    fakat hesaplama izni VERİLMEZ.
#
#       selected_blocked_anchor
#
# 10. Bu policy deadline HESAPLAMAZ.
# ============================================================


import argparse
import json
import sys

from datetime import date
from pathlib import Path


from deadline_rule_validator import (
    validate_deadline_rules,
    load_json,
)

from deadline_validator import (
    load_case,
    load_canonical_timeline,
)


# ============================================================
# VERSION
# ============================================================

DEADLINE_RULE_SELECTION_POLICY_VERSION = "1"


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

DEADLINE_RULES_DIR = (
    DATA_DIR
    / "deadline_rules"
)

DEFAULT_RULESET_PATH = (
    DEADLINE_RULES_DIR
    / "deadline_rules.json"
)

DEFAULT_CASE_ID = "case_0001"


# ============================================================
# EXCEPTION
# ============================================================

class DeadlineRuleSelectionError(
    Exception
):
    pass


# ============================================================
# HELPERS
# ============================================================

def normalize_string(
    value,
):

    if value is None:

        return None

    return (
        str(
            value
        )
        .strip()
        .casefold()
    )


def normalize_values(
    values,
):

    result = set()

    for value in values or []:

        normalized = normalize_string(
            value
        )

        if normalized:

            result.add(
                normalized
            )

    return result


def parse_iso_date(
    value,
):

    if not value:

        return None

    try:

        return date.fromisoformat(
            str(
                value
            )
        )

    except ValueError:

        return None


# ============================================================
# CASE CONTEXT EXTRACTION
# ============================================================

def get_case_tax_types(
    case_data,
):

    result = set()

    # --------------------------------------------------------
    # Direct tax_type
    # --------------------------------------------------------

    direct = case_data.get(
        "tax_type"
    )

    if direct:

        result.add(
            normalize_string(
                direct
            )
        )

    # --------------------------------------------------------
    # dispute_items[*].tax_type
    # --------------------------------------------------------

    for item in case_data.get(
        "dispute_items",
        [],
    ):

        if not isinstance(
            item,
            dict,
        ):

            continue

        tax_type = item.get(
            "tax_type"
        )

        if tax_type:

            result.add(
                normalize_string(
                    tax_type
                )
            )

    return {
        value
        for value in result
        if value
    }


def get_case_types(
    case_data,
):

    result = set()

    for key in (
        "case_type",
        "dispute_type",
    ):

        value = case_data.get(
            key
        )

        if value:

            result.add(
                normalize_string(
                    value
                )
            )

    return {
        value
        for value in result
        if value
    }


def get_case_stages(
    case_data,
):

    result = set()

    for key in (
        "case_stage",
        "stage",
        "procedural_stage",
    ):

        value = case_data.get(
            key
        )

        if value:

            result.add(
                normalize_string(
                    value
                )
            )

    proceedings = case_data.get(
        "proceedings"
    )

    if isinstance(
        proceedings,
        dict,
    ):

        for key in (
            "stage",
            "status",
            "case_stage",
        ):

            value = proceedings.get(
                key
            )

            if value:

                result.add(
                    normalize_string(
                        value
                    )
                )

    return {
        value
        for value in result
        if value
    }


# ============================================================
# DOCUMENT CONTEXT
# ============================================================

def load_case_document_types(
    case_id,
):

    documents_dir = (
        DATA_DIR
        / "cases"
        / case_id
        / "documents"
    )

    document_types = {}

    if not documents_dir.exists():

        return document_types

    for path in sorted(
        documents_dir.glob(
            "*/document.json"
        )
    ):

        document = load_json(
            path
        )

        document_id = document.get(
            "document_id"
        )

        document_type = document.get(
            "document_type"
        )

        if (
            document_id
            and document_type
        ):

            document_types[
                document_id
            ] = normalize_string(
                document_type
            )

    return document_types


def get_anchor_document_types(
    anchor_event,
    document_type_index,
):

    result = set()

    for document_id in anchor_event.get(
        "source_document_ids",
        [],
    ):

        document_type = (
            document_type_index.get(
                document_id
            )
        )

        if document_type:

            result.add(
                document_type
            )

    return result


# ============================================================
# WILDCARD MATCH
# ============================================================

def applicability_matches(
    rule_values,
    context_values,
):

    rule_values = normalize_values(
        rule_values
    )

    context_values = normalize_values(
        context_values
    )

    # --------------------------------------------------------
    # Empty rule applicability = wildcard.
    # --------------------------------------------------------

    if not rule_values:

        return True

    # --------------------------------------------------------
    # Rule restriction exists but case context is unknown:
    #
    # FAIL CLOSED.
    # --------------------------------------------------------

    if not context_values:

        return False

    return bool(
        rule_values
        & context_values
    )


# ============================================================
# EFFECTIVE DATE
# ============================================================

def rule_effective_for_anchor(
    rule,
    anchor_date,
):

    anchor = parse_iso_date(
        anchor_date
    )

    if anchor is None:

        return False

    effective_from = parse_iso_date(
        rule.get(
            "effective_from"
        )
    )

    effective_to = parse_iso_date(
        rule.get(
            "effective_to"
        )
    )

    if (
        effective_from
        and anchor < effective_from
    ):

        return False

    if (
        effective_to
        and anchor > effective_to
    ):

        return False

    return True


# ============================================================
# ACTIVE / ENABLED
# ============================================================

def rule_is_selectable(
    rule,
):

    return (
        rule.get(
            "status"
        )
        == "active"
        and rule.get(
            "calculation_enabled"
        )
        is True
    )


# ============================================================
# ANCHOR TYPE
# ============================================================

def anchor_type_matches(
    rule,
    anchor_event,
):

    anchor_type = anchor_event.get(
        "event_type"
    )

    allowed = set(
        rule.get(
            "anchor_event_types",
            []
        )
    )

    return (
        anchor_type
        in allowed
    )


# ============================================================
# SINGLE RULE MATCH
# ============================================================

def rule_matches_context(
    rule,
    anchor_event,
    case_context,
):

    reasons = []

    if not rule_is_selectable(
        rule
    ):

        reasons.append(
            "rule_not_active_or_enabled"
        )

    if not anchor_type_matches(
        rule,
        anchor_event,
    ):

        reasons.append(
            "anchor_event_type_mismatch"
        )

    if not rule_effective_for_anchor(
        rule,
        anchor_event.get(
            "date"
        ),
    ):

        reasons.append(
            "effective_date_mismatch"
        )

    applicability = rule.get(
        "applicability",
        {}
    )

    if not applicability_matches(
        applicability.get(
            "case_types",
            []
        ),
        case_context.get(
            "case_types",
            []
        ),
    ):

        reasons.append(
            "case_type_mismatch"
        )

    if not applicability_matches(
        applicability.get(
            "tax_types",
            []
        ),
        case_context.get(
            "tax_types",
            []
        ),
    ):

        reasons.append(
            "tax_type_mismatch"
        )

    if not applicability_matches(
        applicability.get(
            "document_types",
            []
        ),
        case_context.get(
            "anchor_document_types",
            []
        ),
    ):

        reasons.append(
            "document_type_mismatch"
        )

    if not applicability_matches(
        applicability.get(
            "case_stages",
            []
        ),
        case_context.get(
            "case_stages",
            []
        ),
    ):

        reasons.append(
            "case_stage_mismatch"
        )

    return {
        "matched":
            len(
                reasons
            ) == 0,

        "reasons":
            reasons,
    }


# ============================================================
# BUILD CASE CONTEXT
# ============================================================

def build_case_context(
    case_id,
    case_data,
    anchor_event,
):

    document_type_index = (
        load_case_document_types(
            case_id
        )
    )

    return {
        "case_types":
            get_case_types(
                case_data
            ),

        "tax_types":
            get_case_tax_types(
                case_data
            ),

        "case_stages":
            get_case_stages(
                case_data
            ),

        "anchor_document_types":
            get_anchor_document_types(
                anchor_event,
                document_type_index,
            ),
    }


# ============================================================
# SELECT RULE
# ============================================================

def select_deadline_rule(
    ruleset,
    anchor_event,
    case_context,
):

    rules = ruleset.get(
        "rules",
        []
    )

    matched = []

    rejected = []

    for rule in rules:

        result = rule_matches_context(
            rule,
            anchor_event,
            case_context,
        )

        if result[
            "matched"
        ]:

            matched.append(
                rule
            )

        else:

            rejected.append(
                {
                    "rule_id":
                        rule.get(
                            "rule_id"
                        ),

                    "rule_version":
                        rule.get(
                            "rule_version"
                        ),

                    "reasons":
                        result[
                            "reasons"
                        ],
                }
            )

    # ========================================================
    # NO MATCH
    # ========================================================

    if not matched:

        return {
            "selection_state":
                "no_match",

            "selected_rule":
                None,

            "matched_rule_count":
                0,

            "matched_rule_ids":
                [],

            "rejected_rules":
                rejected,

            "calculation_allowed":
                False,

            "requires_human_review":
                True,

            "reason":
                (
                    "Uygulanabilir active deadline rule "
                    "bulunamadı."
                ),
        }

    # ========================================================
    # PRIORITY
    # ========================================================

    highest_priority = max(
        int(
            rule.get(
                "priority",
                0,
            )
        )
        for rule in matched
    )

    finalists = [
        rule
        for rule in matched
        if int(
            rule.get(
                "priority",
                0,
            )
        )
        == highest_priority
    ]

    # ========================================================
    # AMBIGUOUS
    # ========================================================

    if len(
        finalists
    ) > 1:

        return {
            "selection_state":
                "ambiguous",

            "selected_rule":
                None,

            "matched_rule_count":
                len(
                    matched
                ),

            "matched_rule_ids": [
                rule.get(
                    "rule_id"
                )
                for rule in matched
            ],

            "ambiguous_rule_ids": [
                rule.get(
                    "rule_id"
                )
                for rule in finalists
            ],

            "rejected_rules":
                rejected,

            "calculation_allowed":
                False,

            "requires_human_review":
                True,

            "reason":
                (
                    "Aynı en yüksek priority seviyesinde "
                    "birden fazla deadline rule bulundu."
                ),
        }

    selected_rule = finalists[
        0
    ]

    anchor_verification = (
        anchor_event.get(
            "verification_state"
        )
    )

    required_verification = (
        selected_rule.get(
            "required_anchor_verification"
        )
    )

    # ========================================================
    # SELECTED BUT ANCHOR NOT VERIFIED
    # ========================================================

    if (
        anchor_verification
        != required_verification
    ):

        return {
            "selection_state":
                "selected_blocked_anchor",

            "selected_rule":
                selected_rule,

            "matched_rule_count":
                len(
                    matched
                ),

            "matched_rule_ids": [
                rule.get(
                    "rule_id"
                )
                for rule in matched
            ],

            "rejected_rules":
                rejected,

            "calculation_allowed":
                False,

            "requires_human_review":
                True,

            "reason":
                (
                    "Kural seçildi ancak canonical anchor "
                    "event gerekli verification seviyesinde "
                    "değil."
                ),
        }

    # ========================================================
    # SELECTED
    # ========================================================

    return {
        "selection_state":
            "selected",

        "selected_rule":
            selected_rule,

        "matched_rule_count":
            len(
                matched
            ),

        "matched_rule_ids": [
            rule.get(
                "rule_id"
            )
            for rule in matched
        ],

        "rejected_rules":
            rejected,

        "calculation_allowed":
            True,

        "requires_human_review":
            bool(
                selected_rule.get(
                    "requires_human_review"
                )
            ),

        "reason":
            (
                "Deterministik rule selection tamamlandı."
            ),
    }


# ============================================================
# PRODUCTION SELECTION
# ============================================================

def select_for_case_event(
    case_id,
    anchor_event_id,
    ruleset_path=DEFAULT_RULESET_PATH,
):

    rule_validation = (
        validate_deadline_rules(
            ruleset_path=
                ruleset_path,

            raise_on_error=
                True,
        )
    )

    if not rule_validation[
        "valid"
    ]:

        raise DeadlineRuleSelectionError(
            "Deadline Rule Registry geçerli değil."
        )

    ruleset = load_json(
        ruleset_path
    )

    case_data, _ = load_case(
        case_id
    )

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    anchor_event = (
        timeline_context[
            "events"
        ].get(
            anchor_event_id
        )
    )

    if anchor_event is None:

        raise DeadlineRuleSelectionError(
            "Canonical timeline anchor event bulunamadı: "
            f"{anchor_event_id}"
        )

    case_context = (
        build_case_context(
            case_id,
            case_data,
            anchor_event,
        )
    )

    result = (
        select_deadline_rule(
            ruleset=
                ruleset,

            anchor_event=
                anchor_event,

            case_context=
                case_context,
        )
    )

    result[
        "case_id"
    ] = case_id

    result[
        "anchor_event_id"
    ] = anchor_event_id

    result[
        "anchor_date"
    ] = anchor_event.get(
        "date"
    )

    result[
        "anchor_event_type"
    ] = anchor_event.get(
        "event_type"
    )

    result[
        "anchor_verification_state"
    ] = anchor_event.get(
        "verification_state"
    )

    return result


# ============================================================
# SELF TEST FIXTURES
# ============================================================

def make_rule(
    rule_id,
    priority=100,
    anchor_event_types=None,
    tax_types=None,
    document_types=None,
    case_types=None,
    case_stages=None,
    effective_from="2026-01-01",
    effective_to=None,
):

    return {
        "rule_id":
            rule_id,

        "rule_version":
            "1.0",

        "name":
            f"Fixture {rule_id}",

        "status":
            "active",

        "deadline_type":
            "lawsuit_filing",

        "anchor_event_types":
            (
                anchor_event_types
                or [
                    "notification_date"
                ]
            ),

        "applicability": {
            "case_types":
                case_types
                or [],

            "tax_types":
                tax_types
                or [],

            "document_types":
                document_types
                or [],

            "case_stages":
                case_stages
                or [],
        },

        "legal_basis_refs": [
            f"fixture_basis_{rule_id}"
        ],

        "duration": {
            "value":
                30,

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
            effective_from,

        "effective_to":
            effective_to,

        "priority":
            priority,

        "requires_human_review":
            False,

        "notes":
            "Self-test fixture.",
    }


def make_ruleset(
    rules,
):

    return {
        "schema_version":
            1,

        "ruleset_id":
            "selection_policy_fixture",

        "jurisdiction":
            "TR",

        "rules":
            rules,

        "notes":
            "Self-test fixture.",
    }


def make_anchor(
    verification_state="verified",
):

    return {
        "event_id":
            "timeline_event_test",

        "event_type":
            "notification_date",

        "date":
            "2026-02-10",

        "verification_state":
            verification_state,

        "source_document_ids": [
            "ihbarname_001"
        ],
    }


def make_context():

    return {
        "case_types": {
            "tax_dispute"
        },

        "tax_types": {
            "kdv"
        },

        "case_stages": {
            "first_instance"
        },

        "anchor_document_types": {
            "vergi_ceza_ihbarnamesi"
        },
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
        " VERGİ AI - DEADLINE RULE SELECTION POLICY V1"
    )

    print(
        "======================================"
    )

    anchor = make_anchor()

    context = make_context()

    # ========================================================
    # T01 ACTIVE RULE SELECTED
    # ========================================================

    ruleset = make_ruleset(
        [
            make_rule(
                "rule_001"
            )
        ]
    )

    result = select_deadline_rule(
        ruleset,
        anchor,
        context,
    )

    assert (
        result[
            "selection_state"
        ]
        == "selected"
    )

    print(
        "T01 Active rule selection:",
        "PASS"
    )

    # ========================================================
    # T02 ANCHOR TYPE FILTER
    # ========================================================

    ruleset = make_ruleset(
        [
            make_rule(
                "rule_001",
                anchor_event_types=[
                    "court_decision_date"
                ],
            )
        ]
    )

    result = select_deadline_rule(
        ruleset,
        anchor,
        context,
    )

    assert (
        result[
            "selection_state"
        ]
        == "no_match"
    )

    print(
        "T02 Anchor event filter:",
        "PASS"
    )

    # ========================================================
    # T03 EFFECTIVE DATE FILTER
    # ========================================================

    ruleset = make_ruleset(
        [
            make_rule(
                "rule_001",
                effective_from=
                    "2027-01-01",
            )
        ]
    )

    result = select_deadline_rule(
        ruleset,
        anchor,
        context,
    )

    assert (
        result[
            "selection_state"
        ]
        == "no_match"
    )

    print(
        "T03 Effective date filter:",
        "PASS"
    )

    # ========================================================
    # T04 TAX TYPE FILTER
    # ========================================================

    ruleset = make_ruleset(
        [
            make_rule(
                "rule_001",
                tax_types=[
                    "gelir_vergisi"
                ],
            )
        ]
    )

    result = select_deadline_rule(
        ruleset,
        anchor,
        context,
    )

    assert (
        result[
            "selection_state"
        ]
        == "no_match"
    )

    print(
        "T04 Tax type filter:",
        "PASS"
    )

    # ========================================================
    # T05 DOCUMENT TYPE FILTER
    # ========================================================

    ruleset = make_ruleset(
        [
            make_rule(
                "rule_001",
                document_types=[
                    "mahkeme_karari"
                ],
            )
        ]
    )

    result = select_deadline_rule(
        ruleset,
        anchor,
        context,
    )

    assert (
        result[
            "selection_state"
        ]
        == "no_match"
    )

    print(
        "T05 Document type filter:",
        "PASS"
    )

    # ========================================================
    # T06 WILDCARD APPLICABILITY
    # ========================================================

    ruleset = make_ruleset(
        [
            make_rule(
                "rule_001"
            )
        ]
    )

    result = select_deadline_rule(
        ruleset,
        anchor,
        {
            "case_types":
                set(),

            "tax_types":
                set(),

            "case_stages":
                set(),

            "anchor_document_types":
                set(),
        },
    )

    assert (
        result[
            "selection_state"
        ]
        == "selected"
    )

    print(
        "T06 Empty applicability wildcard:",
        "PASS"
    )

    # ========================================================
    # T07 PRIORITY
    # ========================================================

    ruleset = make_ruleset(
        [
            make_rule(
                "rule_low",
                priority=10,
            ),

            make_rule(
                "rule_high",
                priority=100,
            ),
        ]
    )

    result = select_deadline_rule(
        ruleset,
        anchor,
        context,
    )

    assert (
        result[
            "selection_state"
        ]
        == "selected"
    )

    assert (
        result[
            "selected_rule"
        ][
            "rule_id"
        ]
        == "rule_high"
    )

    print(
        "T07 Priority selection:",
        "PASS"
    )

    # ========================================================
    # T08 AMBIGUOUS SAME PRIORITY
    # ========================================================

    ruleset = make_ruleset(
        [
            make_rule(
                "rule_a",
                priority=100,
            ),

            make_rule(
                "rule_b",
                priority=100,
            ),
        ]
    )

    result = select_deadline_rule(
        ruleset,
        anchor,
        context,
    )

    assert (
        result[
            "selection_state"
        ]
        == "ambiguous"
    )

    assert (
        result[
            "calculation_allowed"
        ]
        is False
    )

    print(
        "T08 Ambiguous priority fail-closed:",
        "PASS"
    )

    # ========================================================
    # T09 NO MATCH
    # ========================================================

    ruleset = make_ruleset(
        []
    )

    result = select_deadline_rule(
        ruleset,
        anchor,
        context,
    )

    assert (
        result[
            "selection_state"
        ]
        == "no_match"
    )

    assert (
        result[
            "calculation_allowed"
        ]
        is False
    )

    print(
        "T09 No-match fail-closed:",
        "PASS"
    )

    # ========================================================
    # T10 UNVERIFIED ANCHOR
    # ========================================================

    ruleset = make_ruleset(
        [
            make_rule(
                "rule_001"
            )
        ]
    )

    unverified_anchor = make_anchor(
        verification_state=
            "unverified"
    )

    result = select_deadline_rule(
        ruleset,
        unverified_anchor,
        context,
    )

    assert (
        result[
            "selection_state"
        ]
        == "selected_blocked_anchor"
    )

    assert (
        result[
            "selected_rule"
        ][
            "rule_id"
        ]
        == "rule_001"
    )

    assert (
        result[
            "calculation_allowed"
        ]
        is False
    )

    assert (
        result[
            "requires_human_review"
        ]
        is True
    )

    print(
        "T10 Unverified anchor calculation blocked:",
        "PASS"
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE RULE SELECTION POLICY V1: 10/10 PASS"
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
            "Vergi AI Deadline Rule Selection Policy V1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=None,
    )

    parser.add_argument(
        "--event",
        dest="event_id",
        default=None,
    )

    parser.add_argument(
        "--ruleset",
        dest="ruleset_path",
        default=str(
            DEFAULT_RULESET_PATH
        ),
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Varsayılan kullanım self-test.
    # --------------------------------------------------------

    if (
        args.self_test
        or (
            args.case_id is None
            and args.event_id is None
        )
    ):

        run_self_test()

        return

    if (
        not args.case_id
        or not args.event_id
    ):

        print(
            "Production selection için --case ve --event "
            "birlikte verilmelidir."
        )

        sys.exit(
            1
        )

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE RULE SELECTION POLICY V1"
    )

    print(
        "======================================"
    )

    try:

        result = (
            select_for_case_event(
                case_id=
                    args.case_id,

                anchor_event_id=
                    args.event_id,

                ruleset_path=
                    Path(
                        args.ruleset_path
                    ),
            )
        )

    except Exception as error:

        print()

        print(
            "RULE SELECTION FAILED"
        )

        print(
            error
        )

        print()

        print(
            "======================================"
        )

        print(
            " DEADLINE RULE SELECTION POLICY V1: FAIL"
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
        "Anchor event:",
        result[
            "anchor_event_id"
        ],
    )

    print(
        "Anchor type:",
        result[
            "anchor_event_type"
        ],
    )

    print(
        "Anchor date:",
        result[
            "anchor_date"
        ],
    )

    print(
        "Anchor verification:",
        result[
            "anchor_verification_state"
        ],
    )

    print(
        "Selection state:",
        result[
            "selection_state"
        ],
    )

    print(
        "Calculation allowed:",
        result[
            "calculation_allowed"
        ],
    )

    selected_rule = (
        result.get(
            "selected_rule"
        )
    )

    if selected_rule:

        print(
            "Selected rule:",
            selected_rule.get(
                "rule_id"
            ),
            "/",
            selected_rule.get(
                "rule_version"
            ),
        )

    else:

        print(
            "Selected rule: None"
        )

    print()

    print(
        "Reason:",
        result[
            "reason"
        ],
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE RULE SELECTION POLICY V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()