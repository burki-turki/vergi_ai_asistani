# ============================================================
# VERGİ AI - LEGAL RESEARCH VALIDATOR V1
#
# AMAÇ:
#
# Legal Research Engine çıktısını iki seviyede doğrulamak:
#
# 1. JSON Schema
# 2. Canonical issue / fact / timeline / deadline / provision
#    çapraz bütünlük ve semantic safety
#
#
# TEMEL PRENSİP:
#
# Bir research candidate:
#
#   != hükmün yürürlükte olduğunun kesinleşmesi
#   != applicability'nin kesinleşmesi
#   != case outcome
#   != kesin hukuki sonuç
#
# Bu nedenle:
#
# - status daima "candidate" olmalıdır (schema + validator).
# - title/description kesin hukuki sonuç ifadesi içeremez.
# - her research candidate canonical bir issue'ya (source_issue_id)
#   ve en az bir canonical alt-kaynağa (fact/timeline/deadline)
#   veya en az bir citation_ref'e dayanmalıdır.
# - resolved_provision_ids yalnız gerçekten canonical
#   provisions.json içinde var olan provision_id'ler olabilir.
#
# TEST FIXTURE ISOLATION: self-test fixture'ları
# data/cases/<case_id>/research/ altına DEĞİL, işletim sistemi
# geçici dizinine yazılır (Row 9 düzeltmesinden alınan ders).
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
)

from issue_spotting_validator import (
    FORBIDDEN_PHRASES,
    load_canonical_deadline_optional,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)

from legal_research_policy import (
    EXECUTION_STATE_FINDING_STATUSES,
    FINDING_STATUS_RESOLVED,
    get_all_provision_ids,
)


# ============================================================
# VERSION
# ============================================================

LEGAL_RESEARCH_VALIDATOR_VERSION = "1"


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

LEGAL_RESEARCH_SCHEMA_PATH = (
    DATA_DIR
    / "case_legal_research.schema.json"
)

DEFAULT_CASE_ID = "case_0001"


# ============================================================
# EXCEPTIONS
# ============================================================

class LegalResearchValidationError(
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

        raise LegalResearchValidationError(
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
# CANONICAL ISSUES (ROW 9 OUTPUT)
# ============================================================

def get_issues_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "issues"
    )


def get_canonical_issues_path(
    case_id,
):

    return (
        get_issues_dir(
            case_id
        )
        / "issues.json"
    )


def load_canonical_issues(
    case_id,
):

    issues_path = (
        get_canonical_issues_path(
            case_id
        )
    )

    issue_analysis = load_json(
        issues_path
    )

    if (
        issue_analysis.get(
            "case_id"
        )
        != case_id
    ):

        raise LegalResearchValidationError(
            "Canonical issues.json case_id uyuşmazlığı."
        )

    issues = issue_analysis.get(
        "issues",
        [],
    )

    issue_index = {}

    for issue in issues:

        issue_id = issue.get(
            "issue_id"
        )

        if not issue_id:

            raise LegalResearchValidationError(
                "Canonical issue kaydında issue_id yok."
            )

        if issue_id in issue_index:

            raise LegalResearchValidationError(
                "Canonical issues.json duplicate "
                f"issue_id: {issue_id}"
            )

        issue_index[
            issue_id
        ] = issue

    return {
        "issues":
            issues,

        "issue_index":
            issue_index,

        "issues_path":
            issues_path,
    }


# ============================================================
# CANONICAL DEADLINE INDEX
# ============================================================

def load_canonical_deadline_index(
    case_id,
):

    (
        deadlines,
        deadline_ids,
        deadline_path,
    ) = (
        load_canonical_deadline_optional(
            case_id
        )
    )

    deadline_index = {
        deadline.get(
            "deadline_id"
        ): deadline
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
        deadline_index,
        deadline_ids,
        deadline_path,
    )


# ============================================================
# GET PATHS
# ============================================================

def get_research_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "research"
    )


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_schema(
    research_analysis,
):

    schema = load_json(
        LEGAL_RESEARCH_SCHEMA_PATH
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
            research_analysis
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
# UNIQUE RESEARCH IDS
# ============================================================

def validate_unique_research_ids(
    research_candidates,
):

    errors = []

    research_ids = [
        item.get(
            "research_id"
        )
        for item in research_candidates
        if isinstance(
            item,
            dict,
        )
        and item.get(
            "research_id"
        )
    ]

    counts = Counter(
        research_ids
    )

    for (
        research_id,
        count,
    ) in counts.items():

        if count > 1:

            errors.append(
                f"Duplicate research_id: {research_id}"
            )

    return errors


# ============================================================
# FORBIDDEN PHRASE GUARD
# ============================================================

def validate_forbidden_phrases(
    research,
):

    errors = []

    research_id = research.get(
        "research_id"
    )

    combined = normalize_text_tr(
        " ".join(
            [
                str(
                    research.get(
                        "title",
                        "",
                    )
                ),

                str(
                    research.get(
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
                f"{research_id}: title/description kesin "
                "hukuki sonuç ifadesi içeriyor "
                f"('{phrase}')."
            )

    return errors


# ============================================================
# STATUS GUARD
# ============================================================

def validate_candidate_status(
    research,
):

    errors = []

    research_id = research.get(
        "research_id"
    )

    if (
        research.get(
            "status"
        )
        != "candidate"
    ):

        errors.append(
            f"{research_id}: status='candidate' olmalıdır."
        )

    return errors


# ============================================================
# SOURCE / GROUNDING INTEGRITY
# ============================================================

def validate_sources(
    research,
    issue_index,
    fact_index,
    event_index,
    deadline_ids,
    all_provision_ids,
):

    errors = []

    research_id = research.get(
        "research_id"
    )

    source_issue_id = research.get(
        "source_issue_id"
    )

    if source_issue_id not in issue_index:

        errors.append(
            f"{research_id}: source_issue_id canonical "
            f"issues.json içinde bulunamadı: "
            f"{source_issue_id}"
        )

    for fact_id in research.get(
        "source_fact_ids",
        [],
    ):

        if fact_id not in fact_index:

            errors.append(
                f"{research_id}: source_fact_id canonical "
                f"fact repository içinde bulunamadı: "
                f"{fact_id}"
            )

    for event_id in research.get(
        "source_timeline_event_ids",
        [],
    ):

        if event_id not in event_index:

            errors.append(
                f"{research_id}: source_timeline_event_id "
                "canonical timeline içinde bulunamadı: "
                f"{event_id}"
            )

    for deadline_id in research.get(
        "source_deadline_ids",
        [],
    ):

        if deadline_id not in deadline_ids:

            errors.append(
                f"{research_id}: source_deadline_id "
                "canonical deadline analysis içinde "
                f"bulunamadı: {deadline_id}"
            )

    for provision_id in research.get(
        "resolved_provision_ids",
        [],
    ):

        if provision_id not in all_provision_ids:

            errors.append(
                f"{research_id}: resolved_provision_id "
                "canonical provisions.json içinde "
                f"bulunamadı (hayali provision): "
                f"{provision_id}"
            )

    # ========================================================
    # Execution-state kayıtları (retrieval_not_run /
    # retrieval_failed / no_research_evidence) tanım gereği
    # kaynaksız olabilir (source_issue_id zaten yukarıda
    # ayrıca doğrulanmıştır - coverage kaydının kendisi
    # meşrudur).
    # ========================================================

    if (
        research.get(
            "finding_status"
        )
        not in EXECUTION_STATE_FINDING_STATUSES
        and not research.get(
            "citation_refs"
        )
        and not research.get(
            "source_fact_ids"
        )
        and not research.get(
            "source_timeline_event_ids"
        )
        and not research.get(
            "source_deadline_ids"
        )
    ):

        errors.append(
            f"{research_id}: en az bir citation_ref veya "
            "canonical kaynağa dayanmalıdır."
        )

    return errors


# ============================================================
# FINDING STATUS <-> RESULT CONSISTENCY
# ============================================================

def validate_finding_consistency(
    research,
):

    errors = []

    research_id = research.get(
        "research_id"
    )

    finding_status = research.get(
        "finding_status"
    )

    formal_result = research.get(
        "formal_result"
    )

    applicability_result = research.get(
        "applicability_result"
    )

    resolved_provision_ids = research.get(
        "resolved_provision_ids",
        [],
    )

    if (
        finding_status
        not in FINDING_STATUS_RESOLVED
        and (
            formal_result is not None
            or applicability_result
            is not None
        )
    ):

        errors.append(
            f"{research_id}: finding_status="
            f"'{finding_status}' iken formal_result/"
            "applicability_result null olmayan bir "
            "değer taşıyor. formal_result/"
            "applicability_result yalnız "
            "provision_resolved/"
            "provision_resolved_version_unknown "
            "durumunda dolu olabilir."
        )

    if (
        finding_status
        in FINDING_STATUS_RESOLVED
        and not resolved_provision_ids
    ):

        errors.append(
            f"{research_id}: finding_status="
            f"'{finding_status}' iken "
            "resolved_provision_ids boş olamaz."
        )

    if (
        finding_status
        not in FINDING_STATUS_RESOLVED
        and resolved_provision_ids
    ):

        errors.append(
            f"{research_id}: finding_status="
            f"'{finding_status}' iken "
            "resolved_provision_ids boş olmalıdır. "
            "(finding_status='provision_resolved' "
            "DIŞINDA hiçbir durum bir provision'ı "
            "'çözülmüş' olarak işaretleyemez.)"
        )

    return errors


# ============================================================
# RESEARCH TYPE <-> RETRIEVAL QUERY CONSISTENCY
# ============================================================

def validate_research_type_consistency(
    research,
):

    errors = []

    research_id = research.get(
        "research_id"
    )

    research_type = research.get(
        "research_type"
    )

    retrieval_query = research.get(
        "retrieval_query"
    )

    if (
        research_type
        == "issue_driven_discovery"
        and not (
            isinstance(
                retrieval_query,
                str,
            )
            and retrieval_query.strip()
        )
    ):

        errors.append(
            f"{research_id}: research_type="
            "'issue_driven_discovery' iken retrieval_query "
            "boş olamaz (deterministik research intent "
            "kaydedilmelidir)."
        )

    if (
        research_type
        != "issue_driven_discovery"
        and retrieval_query is not None
    ):

        errors.append(
            f"{research_id}: research_type="
            f"'{research_type}' iken retrieval_query "
            "null olmalıdır (yalnız issue_driven_discovery "
            "için doldurulur)."
        )

    return errors


# ============================================================
# CASE ID
# ============================================================

def validate_case_id(
    research_analysis,
    expected_case_id,
):

    errors = []

    found = research_analysis.get(
        "case_id"
    )

    if found != expected_case_id:

        errors.append(
            "Research analysis case_id uyuşmazlığı. "
            f"Beklenen={expected_case_id}, "
            f"Bulunan={found}"
        )

    return errors


def validate_generated_at(
    research_analysis,
):

    errors = []

    generated_at = research_analysis.get(
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

def validate_research_analysis(
    research_path,
    expected_case_id=None,
    raise_on_error=False,
):

    research_path = Path(
        research_path
    )

    research_analysis = load_json(
        research_path
    )

    case_id = (
        expected_case_id
        or research_analysis.get(
            "case_id"
        )
    )

    if not case_id:

        raise LegalResearchValidationError(
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
        deadline_index,
        deadline_ids,
        _deadline_path,
    ) = (
        load_canonical_deadline_index(
            case_id
        )
    )

    issue_context = (
        load_canonical_issues(
            case_id
        )
    )

    issue_index = issue_context[
        "issue_index"
    ]

    all_provision_ids = (
        get_all_provision_ids()
    )

    errors = []

    warnings = []

    # ========================================================
    # SCHEMA
    # ========================================================

    errors.extend(
        validate_schema(
            research_analysis
        )
    )

    # ========================================================
    # TOP LEVEL
    # ========================================================

    errors.extend(
        validate_case_id(
            research_analysis,
            case_id,
        )
    )

    errors.extend(
        validate_generated_at(
            research_analysis
        )
    )

    research_candidates = (
        research_analysis.get(
            "research_candidates",
            [],
        )
    )

    if not isinstance(
        research_candidates,
        list,
    ):

        research_candidates = []

    # ========================================================
    # UNIQUE IDS
    # ========================================================

    errors.extend(
        validate_unique_research_ids(
            research_candidates
        )
    )

    # ========================================================
    # RESEARCH CANDIDATES
    # ========================================================

    unused_party_ids = (
        {
            party_id
            for party_id in case_party_ids
        }
    )

    for research in research_candidates:

        if not isinstance(
            research,
            dict,
        ):

            continue

        errors.extend(
            validate_candidate_status(
                research
            )
        )

        errors.extend(
            validate_forbidden_phrases(
                research
            )
        )

        errors.extend(
            validate_sources(
                research,
                issue_index,
                fact_index,
                event_index,
                deadline_ids,
                all_provision_ids,
            )
        )

        errors.extend(
            validate_finding_consistency(
                research
            )
        )

        errors.extend(
            validate_research_type_consistency(
                research
            )
        )

        for party_id in research.get(
            "related_party_ids",
            [],
        ):

            if party_id not in case_party_ids:

                errors.append(
                    f"{research.get('research_id')}: "
                    "related_party_id case içinde "
                    f"bulunamadı: {party_id}"
                )

        for dispute_item_id in research.get(
            "related_dispute_item_ids",
            [],
        ):

            if (
                dispute_item_id
                not in case_dispute_item_ids
            ):

                errors.append(
                    f"{research.get('research_id')}: "
                    "related_dispute_item_id case içinde "
                    f"bulunamadı: {dispute_item_id}"
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
            LEGAL_RESEARCH_VALIDATOR_VERSION,

        "research_path":
            str(
                research_path
            ),

        "case_id":
            case_id,

        "case_path":
            str(
                case_path
            ),

        "issue_count":
            len(
                issue_index
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

        "provision_count":
            len(
                all_provision_ids
            ),

        "research_candidate_count":
            len(
                research_candidates
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

        raise LegalResearchValidationError(
            "LEGAL RESEARCH VALIDATOR V1: FAIL\n\n- "
            + "\n- ".join(
                errors
            )
        )

    return result


# ============================================================
# DEMO RESEARCH ANALYSIS (SELF-TEST)
# ============================================================

def build_demo_research_analysis(
    case_id,
):

    from legal_research_policy import (
        finalize_candidates,
        load_legal_documents_index,
        run_all_rules,
    )

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = fact_context[
        "facts"
    ]

    (
        deadline_index,
        _deadline_ids,
        _deadline_path,
    ) = (
        load_canonical_deadline_index(
            case_id
        )
    )

    issue_context = (
        load_canonical_issues(
            case_id
        )
    )

    issues = issue_context[
        "issues"
    ]

    documents_index = (
        load_legal_documents_index()
    )

    raw_candidates = (
        run_all_rules(
            issues=
                issues,

            fact_index=
                fact_index,

            deadline_index=
                deadline_index,

            documents_index=
                documents_index,
        )
    )

    research_candidates = (
        finalize_candidates(
            raw_candidates
        )
    )

    return {
        "schema_version":
            1,

        "research_analysis_id":
            f"legal_research_{case_id}_demo_v1",

        "case_id":
            case_id,

        "status":
            "completed",

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "research_candidates":
            research_candidates,

        "warnings": [],

        "notes":
            (
                "Legal Research Validator V1 self-test "
                "fixture. Deterministik Legal Knowledge "
                "Engine (provision_repository + "
                "provision_version_policy + "
                "provision_policy) üzerinden üretilmiştir."
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
        " VERGİ AI - LEGAL RESEARCH VALIDATOR V1"
    )

    print(
        "======================================"
    )

    # ========================================================
    # T01 SCHEMA LOAD
    # ========================================================

    assert (
        LEGAL_RESEARCH_SCHEMA_PATH.exists()
    )

    load_json(
        LEGAL_RESEARCH_SCHEMA_PATH
    )

    print(
        "T01 Legal research schema load:",
        "PASS"
    )

    # ========================================================
    # T02 CANONICAL CONTEXT LOAD (facts/timeline/issues)
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

    issue_context = (
        load_canonical_issues(
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
            issue_context[
                "issue_index"
            ]
        )
        >= 1
    )

    print(
        "T02 Canonical fact/timeline/issue load:",
        "PASS"
    )

    # ========================================================
    # T03 DEMO BUILD
    # ========================================================

    demo = (
        build_demo_research_analysis(
            case_id
        )
    )

    assert (
        len(
            demo[
                "research_candidates"
            ]
        )
        >= 1
    )

    for research in demo[
        "research_candidates"
    ]:

        assert (
            research[
                "status"
            ]
            == "candidate"
        )

    print(
        "T03 Deterministic research candidate build:",
        "PASS"
    )

    # ========================================================
    # TEST FIXTURE ISOLATION
    #
    # OS geçici dizini kullanılır; case_0001/research/
    # altına YAZILMAZ.
    # ========================================================

    temp_dir = (
        tempfile.TemporaryDirectory(
            prefix=
                "legal_research_validator_selftest_"
        )
    )

    research_dir = Path(
        temp_dir.name
    )

    # ========================================================
    # T04 VALID RESEARCH ANALYSIS
    # ========================================================

    valid_path = (
        research_dir
        / "legal_research_validator_v1_test.json"
    )

    write_json(
        valid_path,
        demo,
    )

    result = (
        validate_research_analysis(
            research_path=
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
        "T04 Valid research analysis:",
        "PASS"
    )

    # ========================================================
    # T05 UNKNOWN SOURCE ISSUE ID
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "research_candidates"
    ][
        0
    ][
        "source_issue_id"
    ] = "issue_does_not_exist"

    broken_path = (
        research_dir
        / "legal_research_validator_v1_unknown_issue.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_research_analysis(
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
        "T05 Unknown source_issue_id blocked:",
        "PASS"
    )

    # ========================================================
    # T06 HALLUCINATED PROVISION ID
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "research_candidates"
    ][
        0
    ][
        "resolved_provision_ids"
    ] = [
        "kanun_9999_m1_f1_does_not_exist"
    ]

    broken[
        "research_candidates"
    ][
        0
    ][
        "finding_status"
    ] = "provision_resolved"

    broken_path = (
        research_dir
        / "legal_research_validator_v1_fake_provision.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_research_analysis(
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
        "T06 Hallucinated provision_id blocked:",
        "PASS"
    )

    # ========================================================
    # T07 DUPLICATE RESEARCH ID
    # ========================================================

    broken = clone_json(
        demo
    )

    if (
        len(
            broken[
                "research_candidates"
            ]
        )
        >= 2
    ):

        broken[
            "research_candidates"
        ][
            1
        ][
            "research_id"
        ] = broken[
            "research_candidates"
        ][
            0
        ][
            "research_id"
        ]

    else:

        duplicate = clone_json(
            broken[
                "research_candidates"
            ][
                0
            ]
        )

        broken[
            "research_candidates"
        ].append(
            duplicate
        )

    broken_path = (
        research_dir
        / "legal_research_validator_v1_duplicate.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_research_analysis(
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
        "T07 Duplicate research_id blocked:",
        "PASS"
    )

    # ========================================================
    # T08 NON-CANDIDATE STATUS BLOCKED
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "research_candidates"
    ][
        0
    ][
        "status"
    ] = "confirmed"

    broken_path = (
        research_dir
        / "legal_research_validator_v1_status.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_research_analysis(
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
        "T08 Non-candidate status blocked:",
        "PASS"
    )

    # ========================================================
    # T09 FORBIDDEN PHRASE BLOCKED
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "research_candidates"
    ][
        0
    ][
        "description"
    ] = "Bu hüküm kesinlikle hukuka aykırıdır."

    broken_path = (
        research_dir
        / "legal_research_validator_v1_forbidden.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_research_analysis(
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
        "T09 Forbidden legal-conclusion phrase blocked:",
        "PASS"
    )

    # ========================================================
    # T10 FINDING/RESULT CONSISTENCY BLOCKED
    #
    # not_found iken formal_result set edilmiş olamaz.
    # ========================================================

    broken = clone_json(
        demo
    )

    not_found_candidates = [
        research
        for research in broken[
            "research_candidates"
        ]
        if research[
            "finding_status"
        ]
        == "not_found"
    ]

    assert (
        len(
            not_found_candidates
        )
        >= 1
    ), (
        "Self-test case_0001 verisinde en az bir "
        "not_found beklenir (KDVK/VUK provisions.json'da "
        "yok)."
    )

    not_found_candidates[
        0
    ][
        "formal_result"
    ] = "valid"

    broken_path = (
        research_dir
        / "legal_research_validator_v1_inconsistent.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_research_analysis(
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
        "T10 finding_status/result consistency guard:",
        "PASS"
    )

    # ========================================================
    # T11 VALID ISSUE-DRIVEN DISCOVERY COVERAGE CANDIDATE
    # ACCEPTED (retrieval_not_run)
    #
    # legal_research_discovery.build_execution_state_candidate()
    # gerçek (network gerektirmeyen, salt deterministik) bir
    # fonksiyondur; burada issue_001 için sentetik bir
    # "retrieval henüz çalıştırılmadı" coverage kaydı üretip
    # validator'ın bunu kabul ettiğini doğrular.
    # ========================================================

    from legal_research_discovery import (
        build_execution_state_candidate,
    )

    demo_with_discovery = clone_json(
        demo
    )

    discovery_raw = (
        build_execution_state_candidate(
            issue=
                {
                    "issue_id":
                        "issue_001",

                    "source_timeline_event_ids": [
                        "timeline_event_003"
                    ],
                },

            query_text=
                "tebliğ tarihinin ispatı ve süreye "
                "etkisi",

            finding_status=
                "retrieval_not_run",
        )
    )

    discovery_raw[
        "research_id"
    ] = "research_900"

    discovery_raw[
        "status"
    ] = "candidate"

    demo_with_discovery[
        "research_candidates"
    ].append(
        discovery_raw
    )

    discovery_path = (
        research_dir
        / "legal_research_validator_v1_discovery.json"
    )

    write_json(
        discovery_path,
        demo_with_discovery,
    )

    discovery_result = (
        validate_research_analysis(
            discovery_path,
            case_id,
        )
    )

    if not discovery_result[
        "valid"
    ]:

        print()

        for error in discovery_result[
            "errors"
        ]:

            print(
                "-",
                error,
            )

    assert (
        discovery_result[
            "valid"
        ]
        is True
    )

    print(
        "T11 Valid issue_driven_discovery "
        "(retrieval_not_run) coverage candidate "
        "accepted:",
        "PASS"
    )

    # ========================================================
    # T11B EXECUTION-STATE DISTINCTNESS
    #
    # retrieval_not_run / retrieval_failed /
    # no_research_evidence birbirinden farklı, birbirine
    # dönüştürülemez üç kayıt üretir - hiçbiri diğerinin
    # metnini veya anlamını taşımaz.
    # ========================================================

    execution_state_candidates = {}

    for status in (
        "retrieval_not_run",
        "retrieval_failed",
        "no_research_evidence",
    ):

        execution_state_candidates[
            status
        ] = (
            build_execution_state_candidate(
                issue=
                    {
                        "issue_id":
                            "issue_001",

                        "source_timeline_event_ids": [
                            "timeline_event_003"
                        ],
                    },

                query_text=
                    "tebliğ tarihinin ispatı ve "
                    "süreye etkisi",

                finding_status=
                    status,

                failure_reason=
                    (
                        "simulated_failure"
                        if status
                        == "retrieval_failed"
                        else None
                    ),
            )
        )

    assert (
        len(
            {
                candidate[
                    "title"
                ]
                for candidate
                in execution_state_candidates.values()
            }
        )
        == 3
    ), "Üç execution-state farklı title üretmeli."

    for (
        status,
        candidate,
    ) in execution_state_candidates.items():

        assert (
            candidate[
                "finding_status"
            ]
            == status
        )

        assert (
            candidate[
                "resolved_provision_ids"
            ]
            == []
        )

        assert (
            candidate[
                "formal_result"
            ]
            is None
        )

        assert (
            candidate[
                "applicability_result"
            ]
            is None
        )

        assert (
            candidate[
                "requires_human_review"
            ]
            is True
        )

        candidate[
            "research_id"
        ] = f"research_9{list(execution_state_candidates).index(status)}"

        candidate[
            "status"
        ] = "candidate"

        each_path = (
            research_dir
            / f"legal_research_validator_v1_{status}.json"
        )

        each_analysis = clone_json(
            demo
        )

        each_analysis[
            "research_candidates"
        ].append(
            candidate
        )

        write_json(
            each_path,
            each_analysis,
        )

        each_result = (
            validate_research_analysis(
                each_path,
                case_id,
            )
        )

        if not each_result[
            "valid"
        ]:

            print()

            for error in each_result[
                "errors"
            ]:

                print(
                    "-",
                    error,
                )

        assert (
            each_result[
                "valid"
            ]
            is True
        )

    print(
        "T11B Execution states are distinct "
        "(retrieval_not_run != retrieval_failed != "
        "no_research_evidence), each independently "
        "valid:",
        "PASS"
    )

    # ========================================================
    # T12 RETRIEVAL_QUERY / RESEARCH_TYPE CONSISTENCY BLOCKED
    # ========================================================

    broken = clone_json(
        demo_with_discovery
    )

    for research in broken[
        "research_candidates"
    ]:

        if (
            research[
                "research_id"
            ]
            == "research_900"
        ):

            research[
                "retrieval_query"
            ] = None

    broken_path = (
        research_dir
        / "legal_research_validator_v1_retrieval_query.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_research_analysis(
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
        "T12 research_type/retrieval_query "
        "consistency guard:",
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
        "Canonical issue count:",
        len(
            issue_context[
                "issue_index"
            ]
        ),
    )

    print(
        "Demo research candidate count:",
        len(
            demo[
                "research_candidates"
            ]
        ),
    )

    for research in demo[
        "research_candidates"
    ]:

        print(
            "-",
            research[
                "research_id"
            ],
            "|",
            "issue=" + research[
                "source_issue_id"
            ],
            "|",
            research[
                "finding_status"
            ],
            "|",
            research[
                "trigger_rule_id"
            ],
        )

    print()

    print(
        "======================================"
    )

    print(
        " LEGAL RESEARCH VALIDATOR V1: 13/13 PASS"
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
            "Vergi AI Legal Research Validator V1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--research",
        dest="research_path",
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
        or args.research_path is None
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
        " VERGİ AI - LEGAL RESEARCH VALIDATOR V1"
    )

    print(
        "======================================"
    )

    try:

        result = (
            validate_research_analysis(
                research_path=
                    Path(
                        args.research_path
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
            " LEGAL RESEARCH VALIDATOR V1: FAIL"
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
        "Research candidate count:",
        result[
            "research_candidate_count"
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
            " LEGAL RESEARCH VALIDATOR V1: PASS"
        )

    else:

        print(
            " LEGAL RESEARCH VALIDATOR V1: FAIL"
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
