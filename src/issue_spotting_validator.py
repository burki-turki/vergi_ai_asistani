# ============================================================
# VERGİ AI - ISSUE SPOTTING VALIDATOR V1
#
# AMAÇ:
#
# Issue Spotting Engine çıktısını iki seviyede doğrulamak:
#
# 1. JSON Schema
# 2. Canonical fact / timeline / deadline çapraz bütünlük ve
#    semantic safety
#
#
# TEMEL PRENSİP:
#
# Bir issue candidate:
#
#   != verified fact
#   != legal conclusion
#   != case outcome
#   != guaranteed applicability
#   != deadline determination
#
#
# Bu nedenle:
#
# - status daima "candidate" olmalıdır (schema + validator
#   çift katmanlı kontrol).
# - description/title kesin hukuki sonuç ifadesi
#   içeremez (ör. "dava süresi geçmiştir").
# - her issue en az bir canonical kaynağa (fact/timeline
#   event/deadline) dayanmalıdır; kaynaksız issue üretilemez.
#
#
# DİĞER PRENSİPLER:
#
# - Issue Spotting Validator yeni hukuk kuralı oluşturmaz.
# - Süre hesabı yapmaz.
# - Canonical fact/timeline/deadline kaydını değiştirmez.
# - Verification seviyesini yükseltmez.
# ============================================================


import argparse
import json
import sys
import tempfile

from collections import Counter
from datetime import datetime
from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)

from timeline_validator import (
    load_canonical_fact_index,
)

from deadline_validator import (
    load_canonical_timeline,
    validate_deadline_analysis,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)

from issue_spotting_policy import (
    finalize_candidates,
    run_all_rules,
)


# ============================================================
# VERSION
# ============================================================

ISSUE_SPOTTING_VALIDATOR_VERSION = "1"


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

ISSUE_SPOTTING_SCHEMA_PATH = (
    DATA_DIR
    / "case_issue_spotting.schema.json"
)

DEFAULT_CASE_ID = "case_0001"


# ============================================================
# FORBIDDEN PHRASES
#
# Issue candidate description/title'ında kesin hukuki sonuç,
# case outcome veya deadline determination anlamına gelecek
# ifadeler yasaktır. Kaynak ne olursa olsun (deterministic
# rule veya ileride LLM) bu guard geçerlidir.
# ============================================================

FORBIDDEN_PHRASES = (
    "dava suresi gecmistir",
    "sure gecmistir",
    "zamanasimina ugramistir",
    "zamanasimi dolmustur",
    "hukuka aykiridir",
    "kesinlesmistir",
    "sure kacirilmistir",
    "davaci haklidir",
    "davaci haksizdir",
    "iptal edilmelidir",
    "reddedilmelidir",
    "kabul edilmelidir",
    "kesin son tarih",
    "son gun gecmistir",
)


# ============================================================
# EXCEPTIONS
# ============================================================

class IssueSpottingValidationError(
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

        raise IssueSpottingValidationError(
            "case.json case_id uyuşmazlığı.\n"
            f"Beklenen: {case_id}\n"
            f"Bulunan: {case_data.get('case_id')}"
        )

    return (
        case_data,
        case_path,
    )


def get_case_party_ids(
    case_data,
):

    return {
        party.get(
            "party_id"
        )
        for party in case_data.get(
            "parties",
            [],
        )
        if party.get(
            "party_id"
        )
    }


def get_case_dispute_item_ids(
    case_data,
):

    return {
        item.get(
            "dispute_item_id"
        )
        for item in case_data.get(
            "dispute_items",
            [],
        )
        if item.get(
            "dispute_item_id"
        )
    }


# ============================================================
# CANONICAL DEADLINE (OPTIONAL)
# ============================================================

def load_canonical_deadline_optional(
    case_id,
):

    deadline_path = (
        CASES_DIR
        / case_id
        / "deadlines"
        / "deadline.json"
    )

    if not deadline_path.exists():

        return (
            [],
            set(),
            deadline_path,
        )

    validation = (
        validate_deadline_analysis(
            deadline_path=
                deadline_path,

            expected_case_id=
                case_id,

            raise_on_error=
                False,
        )
    )

    if not validation[
        "valid"
    ]:

        raise IssueSpottingValidationError(
            "Canonical deadline analysis geçerli değil:\n- "
            + "\n- ".join(
                validation[
                    "errors"
                ]
            )
        )

    deadline_analysis = load_json(
        deadline_path
    )

    deadlines = deadline_analysis.get(
        "deadlines",
        [],
    )

    deadline_ids = {
        deadline.get(
            "deadline_id"
        )
        for deadline in deadlines
        if isinstance(
            deadline,
            dict,
        )
        and deadline.get(
            "deadline_id"
        )
    }

    return (
        deadlines,
        deadline_ids,
        deadline_path,
    )


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_schema(
    issue_analysis,
):

    schema = load_json(
        ISSUE_SPOTTING_SCHEMA_PATH
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
            issue_analysis
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
# UNIQUE ISSUE IDS
# ============================================================

def validate_unique_issue_ids(
    issues,
):

    errors = []

    issue_ids = [
        item.get(
            "issue_id"
        )
        for item in issues
        if isinstance(
            item,
            dict,
        )
        and item.get(
            "issue_id"
        )
    ]

    counts = Counter(
        issue_ids
    )

    for (
        issue_id,
        count,
    ) in counts.items():

        if count > 1:

            errors.append(
                f"Duplicate issue_id: {issue_id}"
            )

    return errors


# ============================================================
# FORBIDDEN PHRASE GUARD
# ============================================================

def validate_forbidden_phrases(
    issue,
):

    errors = []

    issue_id = issue.get(
        "issue_id"
    )

    combined = normalize_text_tr(
        " ".join(
            [
                str(
                    issue.get(
                        "title",
                        "",
                    )
                ),

                str(
                    issue.get(
                        "description",
                        "",
                    )
                ),
            ]
        )
    )

    for phrase in FORBIDDEN_PHRASES:

        if phrase in combined:

            errors.append(
                f"{issue_id}: title/description kesin "
                "hukuki sonuç ifadesi içeriyor "
                f"('{phrase}'). Issue candidate legal "
                "conclusion veya case outcome olamaz."
            )

    return errors


# ============================================================
# STATUS GUARD
# ============================================================

def validate_candidate_status(
    issue,
):

    errors = []

    issue_id = issue.get(
        "issue_id"
    )

    if (
        issue.get(
            "status"
        )
        != "candidate"
    ):

        errors.append(
            f"{issue_id}: status='candidate' olmalıdır. "
            "Issue Spotting V1 verified fact veya legal "
            "conclusion üretemez."
        )

    return errors


# ============================================================
# SOURCE REFERENCE INTEGRITY
# ============================================================

def validate_sources(
    issue,
    fact_index,
    event_index,
    deadline_ids,
):

    errors = []

    issue_id = issue.get(
        "issue_id"
    )

    source_fact_ids = issue.get(
        "source_fact_ids",
        [],
    )

    source_timeline_event_ids = issue.get(
        "source_timeline_event_ids",
        [],
    )

    source_deadline_ids = issue.get(
        "source_deadline_ids",
        [],
    )

    total_sources = (
        len(
            source_fact_ids
        )
        + len(
            source_timeline_event_ids
        )
        + len(
            source_deadline_ids
        )
    )

    if total_sources == 0:

        errors.append(
            f"{issue_id}: en az bir canonical kaynağa "
            "(source_fact_ids / "
            "source_timeline_event_ids / "
            "source_deadline_ids) dayanmalıdır."
        )

    for fact_id in source_fact_ids:

        if fact_id not in fact_index:

            errors.append(
                f"{issue_id}: source_fact_id canonical "
                f"fact repository içinde bulunamadı: "
                f"{fact_id}"
            )

    for event_id in source_timeline_event_ids:

        if event_id not in event_index:

            errors.append(
                f"{issue_id}: source_timeline_event_id "
                "canonical timeline içinde bulunamadı: "
                f"{event_id}"
            )

    for deadline_id in source_deadline_ids:

        if deadline_id not in deadline_ids:

            errors.append(
                f"{issue_id}: source_deadline_id canonical "
                f"deadline analysis içinde bulunamadı: "
                f"{deadline_id}"
            )

    return errors


# ============================================================
# RELATED ID INTEGRITY
# ============================================================

def validate_related_ids(
    issue,
    case_party_ids,
    case_dispute_item_ids,
):

    errors = []

    issue_id = issue.get(
        "issue_id"
    )

    for party_id in issue.get(
        "related_party_ids",
        [],
    ):

        if party_id not in case_party_ids:

            errors.append(
                f"{issue_id}: related_party_id case içinde "
                f"bulunamadı: {party_id}"
            )

    for dispute_item_id in issue.get(
        "related_dispute_item_ids",
        [],
    ):

        if (
            dispute_item_id
            not in case_dispute_item_ids
        ):

            errors.append(
                f"{issue_id}: related_dispute_item_id case "
                f"içinde bulunamadı: {dispute_item_id}"
            )

    return errors


# ============================================================
# CASE ID
# ============================================================

def validate_case_id(
    issue_analysis,
    expected_case_id,
):

    errors = []

    found = issue_analysis.get(
        "case_id"
    )

    if found != expected_case_id:

        errors.append(
            "Issue analysis case_id uyuşmazlığı. "
            f"Beklenen={expected_case_id}, "
            f"Bulunan={found}"
        )

    return errors


# ============================================================
# GENERATED AT
# ============================================================

def validate_generated_at(
    issue_analysis,
):

    errors = []

    generated_at = issue_analysis.get(
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
# MAIN VALIDATION
# ============================================================

def validate_issue_analysis(
    issue_path,
    expected_case_id=None,
    raise_on_error=False,
):

    issue_path = Path(
        issue_path
    )

    issue_analysis = load_json(
        issue_path
    )

    case_id = (
        expected_case_id
        or issue_analysis.get(
            "case_id"
        )
    )

    if not case_id:

        raise IssueSpottingValidationError(
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

    case_party_ids = (
        get_case_party_ids(
            case_data
        )
    )

    case_dispute_item_ids = (
        get_case_dispute_item_ids(
            case_data
        )
    )

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = fact_context[
        "facts"
    ]

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    event_index = timeline_context[
        "events"
    ]

    (
        _deadlines,
        deadline_ids,
        deadline_path,
    ) = (
        load_canonical_deadline_optional(
            case_id
        )
    )

    errors = []

    warnings = []

    # ========================================================
    # SCHEMA
    # ========================================================

    errors.extend(
        validate_schema(
            issue_analysis
        )
    )

    # ========================================================
    # TOP LEVEL
    # ========================================================

    errors.extend(
        validate_case_id(
            issue_analysis,
            case_id,
        )
    )

    errors.extend(
        validate_generated_at(
            issue_analysis
        )
    )

    issues = issue_analysis.get(
        "issues",
        [],
    )

    if not isinstance(
        issues,
        list,
    ):

        issues = []

    # ========================================================
    # UNIQUE IDS
    # ========================================================

    errors.extend(
        validate_unique_issue_ids(
            issues
        )
    )

    # ========================================================
    # ISSUES
    # ========================================================

    for issue in issues:

        if not isinstance(
            issue,
            dict,
        ):

            continue

        errors.extend(
            validate_candidate_status(
                issue
            )
        )

        errors.extend(
            validate_forbidden_phrases(
                issue
            )
        )

        errors.extend(
            validate_sources(
                issue,
                fact_index,
                event_index,
                deadline_ids,
            )
        )

        errors.extend(
            validate_related_ids(
                issue,
                case_party_ids,
                case_dispute_item_ids,
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

    result = {
        "valid":
            len(
                errors
            ) == 0,

        "validator_version":
            ISSUE_SPOTTING_VALIDATOR_VERSION,

        "issue_path":
            str(
                issue_path
            ),

        "case_id":
            case_id,

        "case_path":
            str(
                case_path
            ),

        "deadline_path":
            (
                str(
                    deadline_path
                )
                if deadline_path.exists()
                else None
            ),

        "fact_count":
            len(
                fact_index
            ),

        "timeline_event_count":
            len(
                event_index
            ),

        "deadline_count":
            len(
                deadline_ids
            ),

        "issue_count":
            len(
                issues
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

        raise IssueSpottingValidationError(
            "ISSUE SPOTTING VALIDATOR V1: FAIL\n\n- "
            + "\n- ".join(
                errors
            )
        )

    return result


# ============================================================
# DEMO ISSUE ANALYSIS (SELF-TEST)
# ============================================================

def build_demo_issue_analysis(
    case_id,
):

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = fact_context[
        "facts"
    ]

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    event_index = timeline_context[
        "events"
    ]

    timeline_events = list(
        event_index.values()
    )

    (
        deadlines,
        _deadline_ids,
        _deadline_path,
    ) = (
        load_canonical_deadline_optional(
            case_id
        )
    )

    raw_candidates = (
        run_all_rules(
            fact_index=
                fact_index,

            timeline_events=
                timeline_events,

            event_index=
                event_index,

            deadlines=
                deadlines,
        )
    )

    issues = (
        finalize_candidates(
            raw_candidates
        )
    )

    return {
        "schema_version":
            1,

        "issue_analysis_id":
            f"issue_spotting_{case_id}_demo_v1",

        "case_id":
            case_id,

        "status":
            "completed",

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "issues":
            issues,

        "warnings": [],

        "notes":
            (
                "Issue Spotting Validator V1 self-test "
                "fixture. Deterministik kurallarla "
                "üretilmiştir; verified fact, legal "
                "conclusion veya deadline determination "
                "içermez."
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
        " VERGİ AI - ISSUE SPOTTING VALIDATOR V1"
    )

    print(
        "======================================"
    )

    # ========================================================
    # T01 SCHEMA LOAD
    # ========================================================

    assert (
        ISSUE_SPOTTING_SCHEMA_PATH.exists()
    )

    load_json(
        ISSUE_SPOTTING_SCHEMA_PATH
    )

    print(
        "T01 Issue spotting schema load:",
        "PASS"
    )

    # ========================================================
    # T02 CANONICAL CONTEXT LOAD
    # ========================================================

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    assert (
        len(
            fact_context[
                "facts"
            ]
        )
        >= 1
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
        "T02 Canonical fact/timeline load:",
        "PASS"
    )

    # ========================================================
    # T03 DEMO BUILD
    # ========================================================

    demo = (
        build_demo_issue_analysis(
            case_id
        )
    )

    assert (
        len(
            demo[
                "issues"
            ]
        )
        >= 1
    )

    for issue in demo[
        "issues"
    ]:

        assert (
            issue[
                "status"
            ]
            == "candidate"
        )

    print(
        "T03 Deterministic issue candidate build:",
        "PASS"
    )

    # ========================================================
    # TEST FIXTURE ISOLATION
    #
    # Self-test fixture'ları production/demo case dizinine
    # (data/cases/<case_id>/issues/) YAZILMAZ. Gerçek işletim
    # sistemi geçici dizini kullanılır ve fonksiyon sonunda
    # otomatik temizlenir. case_0001/issues/ altında yalnız
    # gerçek Issue Spotting Engine/Approval artefaktları
    # (pending / canonical / reviews / history) bulunur.
    # ========================================================

    temp_dir = (
        tempfile.TemporaryDirectory(
            prefix=
                "issue_spotting_validator_selftest_"
        )
    )

    issues_dir = Path(
        temp_dir.name
    )

    # ========================================================
    # T04 VALID ISSUE ANALYSIS
    # ========================================================

    valid_path = (
        issues_dir
        / "issue_spotting_validator_v1_test.json"
    )

    write_json(
        valid_path,
        demo,
    )

    result = (
        validate_issue_analysis(
            issue_path=
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
        "T04 Valid issue analysis:",
        "PASS"
    )

    # ========================================================
    # T05 UNKNOWN SOURCE FACT
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "issues"
    ][
        0
    ][
        "source_fact_ids"
    ] = [
        "fact_does_not_exist"
    ]

    broken_path = (
        issues_dir
        / "issue_spotting_validator_v1_unknown_fact.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_issue_analysis(
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
        "T05 Unknown source fact blocked:",
        "PASS"
    )

    # ========================================================
    # T06 DUPLICATE ISSUE ID
    # ========================================================

    broken = clone_json(
        demo
    )

    if (
        len(
            broken[
                "issues"
            ]
        )
        >= 2
    ):

        broken[
            "issues"
        ][
            1
        ][
            "issue_id"
        ] = broken[
            "issues"
        ][
            0
        ][
            "issue_id"
        ]

    else:

        duplicate = clone_json(
            broken[
                "issues"
            ][
                0
            ]
        )

        broken[
            "issues"
        ].append(
            duplicate
        )

    broken_path = (
        issues_dir
        / "issue_spotting_validator_v1_duplicate.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_issue_analysis(
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
        "T06 Duplicate issue_id blocked:",
        "PASS"
    )

    # ========================================================
    # T07 NON-CANDIDATE STATUS BLOCKED BY SCHEMA
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "issues"
    ][
        0
    ][
        "status"
    ] = "confirmed"

    broken_path = (
        issues_dir
        / "issue_spotting_validator_v1_status.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_issue_analysis(
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
        "T07 Non-candidate status blocked:",
        "PASS"
    )

    # ========================================================
    # T08 FORBIDDEN PHRASE BLOCKED
    #
    # Kullanıcının verdiği örnek: "Dava süresi geçmiştir."
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "issues"
    ][
        0
    ][
        "description"
    ] = (
        "Dava süresi geçmiştir."
    )

    broken_path = (
        issues_dir
        / "issue_spotting_validator_v1_forbidden_phrase.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_issue_analysis(
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
        "T08 Forbidden legal-conclusion phrase blocked:",
        "PASS"
    )

    # ========================================================
    # T09 EMPTY SOURCES BLOCKED
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "issues"
    ][
        0
    ][
        "source_fact_ids"
    ] = []

    broken[
        "issues"
    ][
        0
    ][
        "source_timeline_event_ids"
    ] = []

    broken[
        "issues"
    ][
        0
    ][
        "source_deadline_ids"
    ] = []

    broken_path = (
        issues_dir
        / "issue_spotting_validator_v1_empty_sources.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_issue_analysis(
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
        "T09 Empty source references blocked:",
        "PASS"
    )

    # ========================================================
    # T10 MISSING REQUIRED FIELD (SCHEMA)
    # ========================================================

    broken = clone_json(
        demo
    )

    del broken[
        "issues"
    ][
        0
    ][
        "trigger_rule_id"
    ]

    broken_path = (
        issues_dir
        / "issue_spotting_validator_v1_missing_field.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_issue_analysis(
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
        "T10 Missing required field blocked:",
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
        "Canonical fact count:",
        len(
            fact_context[
                "facts"
            ]
        ),
    )

    print(
        "Canonical timeline event count:",
        len(
            timeline_context[
                "events"
            ]
        ),
    )

    print(
        "Demo issue count:",
        len(
            demo[
                "issues"
            ]
        ),
    )

    for issue in demo[
        "issues"
    ]:

        print(
            "-",
            issue[
                "issue_id"
            ],
            "|",
            issue[
                "issue_type"
            ],
            "|",
            issue[
                "trigger_rule_id"
            ],
        )

    print()

    print(
        "======================================"
    )

    print(
        " ISSUE SPOTTING VALIDATOR V1: 10/10 PASS"
    )

    print(
        "======================================"
    )

    temp_dir.cleanup()


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Issue Spotting Validator V1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--issues",
        dest="issue_path",
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
        or args.issue_path is None
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
        " VERGİ AI - ISSUE SPOTTING VALIDATOR V1"
    )

    print(
        "======================================"
    )

    try:

        result = (
            validate_issue_analysis(
                issue_path=
                    Path(
                        args.issue_path
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
            " ISSUE SPOTTING VALIDATOR V1: FAIL"
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
        "Issue count:",
        result[
            "issue_count"
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
            " ISSUE SPOTTING VALIDATOR V1: PASS"
        )

    else:

        print(
            " ISSUE SPOTTING VALIDATOR V1: FAIL"
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
