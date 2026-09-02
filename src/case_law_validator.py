# ============================================================
# VERGİ AI - CASE LAW VALIDATOR V2
#
# AMAÇ:
#
# Case Law Engine çıktısını iki seviyede doğrulamak:
#
# 1. JSON Schema
# 2. Canonical issue / research / documents çapraz bütünlük ve
#    semantic safety
#
#
# TEMEL PRENSİP (V2 - COVERAGE / DECISION AYRIMI)
# --------------------------------------------------
#
# - case_law_coverage: HER canonical issue için TAM OLARAK
#   BİR kayıt. Bir karar candidate'ı DEĞİLDİR, court metadata
#   TAŞIYAMAZ (şema düzeyinde böyle bir alan yoktur).
#
# - case_law_decisions: Bir issue için 0..N kayıt. Her biri
#   canonical documents.json'da belge_turu="Yargı Kararı"
#   olarak doğrulanmış GERÇEK bir karara grounded olmalıdır.
#   court_name/court_unit/case_number/decision_number/
#   decision_date/source_url alanları canonical kayıtla
#   BİREBİR eşleşmelidir (uydurma/kaymış metadata FAIL olur).
#   Aynı source_document_id aynı issue altında yalnız BİR kez
#   görünebilir (dedup).
#
# - case_law_agent_suggestions: LLM önerileri. Şema düzeyinde
#   court metadata alanı hiç TANIMLI DEĞİLDİR.
#
# - applicability_result yalnız null/'unknown'/'needs_review'
#   olabilir - asla 'applicable'/'not_applicable' değil.
#
# TEST FIXTURE ISOLATION: self-test fixture'ları
# data/cases/<case_id>/case_law/ altına DEĞİL, işletim sistemi
# geçici dizinine yazılır.
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

from issue_spotting_validator import (
    FORBIDDEN_PHRASES,
)

from legal_research_validator import (
    load_canonical_issues,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)

from case_law_policy import (
    CASE_LAW_FORBIDDEN_PHRASES,
    COVERAGE_EXECUTION_STATES,
    ZERO_DECISION_EXECUTION_STATES,
    load_legal_documents_index,
)


# ============================================================
# VERSION
# ============================================================

CASE_LAW_VALIDATOR_VERSION = "2"

ALL_FORBIDDEN_PHRASES = (
    tuple(
        FORBIDDEN_PHRASES
    )
    + tuple(
        CASE_LAW_FORBIDDEN_PHRASES
    )
)


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

CASE_LAW_SCHEMA_PATH = (
    DATA_DIR
    / "case_case_law.schema.json"
)

DEFAULT_CASE_ID = "case_0001"


# ============================================================
# EXCEPTIONS
# ============================================================

class CaseLawValidationError(
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

        raise CaseLawValidationError(
            "case.json case_id uyuşmazlığı.\n"
            f"Beklenen: {case_id}\n"
            f"Bulunan: {case_data.get('case_id')}"
        )

    return (
        case_data,
        case_path,
    )


# ============================================================
# CANONICAL RESEARCH (ROW 10 OUTPUT)
# ============================================================

def get_research_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "research"
    )


def get_canonical_research_path(
    case_id,
):

    return (
        get_research_dir(
            case_id
        )
        / "research.json"
    )


def load_canonical_research(
    case_id,
):

    research_path = (
        get_canonical_research_path(
            case_id
        )
    )

    if not research_path.exists():

        return (
            [],
            {},
            research_path,
        )

    research_analysis = load_json(
        research_path
    )

    if (
        research_analysis.get(
            "case_id"
        )
        != case_id
    ):

        raise CaseLawValidationError(
            "Canonical research.json case_id uyuşmazlığı."
        )

    researches = research_analysis.get(
        "research_candidates",
        [],
    )

    research_index = {}

    for research in researches:

        research_id = research.get(
            "research_id"
        )

        if not research_id:

            raise CaseLawValidationError(
                "Canonical research kaydında research_id "
                "yok."
            )

        if research_id in research_index:

            raise CaseLawValidationError(
                "Canonical research.json duplicate "
                f"research_id: {research_id}"
            )

        research_index[
            research_id
        ] = research

    return (
        researches,
        research_index,
        research_path,
    )


# ============================================================
# GET CASE LAW PATHS
# ============================================================

def get_case_law_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "case_law"
    )


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_schema(
    case_law_analysis,
):

    schema = load_json(
        CASE_LAW_SCHEMA_PATH
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
            case_law_analysis
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
# FORBIDDEN PHRASE GUARD (SHARED + CASE-LAW SPECIFIC)
# ============================================================

def check_forbidden_phrases(
    record_id,
    title,
    description,
):

    errors = []

    combined = normalize_text_tr(
        f"{title or ''} {description or ''}"
    )

    for phrase in ALL_FORBIDDEN_PHRASES:

        if phrase in combined:

            errors.append(
                f"{record_id}: title/description kesin "
                "hukuki sonuç/case outcome ifadesi "
                f"içeriyor ('{phrase}')."
            )

    return errors


# ============================================================
# STATUS / REQUIRES_HUMAN_REVIEW GUARD
# ============================================================

def check_candidate_status(
    record_id,
    record,
):

    errors = []

    if (
        record.get(
            "status"
        )
        != "candidate"
    ):

        errors.append(
            f"{record_id}: status='candidate' olmalıdır."
        )

    if (
        record.get(
            "requires_human_review"
        )
        is not True
    ):

        errors.append(
            f"{record_id}: requires_human_review=True "
            "olmalıdır (istisnasız)."
        )

    return errors


# ============================================================
# COVERAGE VALIDATION
# ============================================================

def validate_coverage(
    coverage_records,
    issue_index,
    decision_count_by_coverage_id,
):

    errors = []

    ids = [
        record.get(
            "coverage_id"
        )
        for record in coverage_records
        if isinstance(
            record,
            dict,
        )
    ]

    for (
        coverage_id,
        count,
    ) in Counter(
        ids
    ).items():

        if count > 1:

            errors.append(
                f"Duplicate coverage_id: {coverage_id}"
            )

    covered_issue_ids = []

    for record in coverage_records:

        if not isinstance(
            record,
            dict,
        ):

            continue

        coverage_id = record.get(
            "coverage_id"
        )

        source_issue_id = record.get(
            "source_issue_id"
        )

        covered_issue_ids.append(
            source_issue_id
        )

        if source_issue_id not in issue_index:

            errors.append(
                f"{coverage_id}: source_issue_id canonical "
                f"issues.json içinde bulunamadı: "
                f"{source_issue_id}"
            )

        execution_state = record.get(
            "execution_state"
        )

        if execution_state not in COVERAGE_EXECUTION_STATES:

            errors.append(
                f"{coverage_id}: geçersiz execution_state: "
                f"{execution_state}"
            )

        decision_count = record.get(
            "decision_count"
        )

        actual_linked = (
            decision_count_by_coverage_id.get(
                coverage_id,
                0,
            )
        )

        if decision_count != actual_linked:

            errors.append(
                f"{coverage_id}: decision_count="
                f"{decision_count} ancak fiilen bağlı "
                f"decision sayısı={actual_linked}."
            )

        if (
            execution_state
            in ZERO_DECISION_EXECUTION_STATES
            and decision_count != 0
        ):

            errors.append(
                f"{coverage_id}: execution_state="
                f"'{execution_state}' iken decision_count "
                "0 olmalıdır."
            )

        if (
            execution_state
            == "retrieval_completed"
            and decision_count < 1
        ):

            errors.append(
                f"{coverage_id}: execution_state="
                "'retrieval_completed' iken decision_count "
                ">= 1 olmalıdır."
            )

        retrieval_query = record.get(
            "retrieval_query"
        )

        if not (
            isinstance(
                retrieval_query,
                str,
            )
            and retrieval_query.strip()
        ):

            errors.append(
                f"{coverage_id}: retrieval_query boş "
                "olamaz (coverage her zaman bir research "
                "intent'ine dayanır)."
            )

        errors.extend(
            check_candidate_status(
                coverage_id,
                record,
            )
        )

        errors.extend(
            check_forbidden_phrases(
                coverage_id,
                record.get(
                    "title"
                ),

                record.get(
                    "description"
                ),
            )
        )

    # ========================================================
    # COMPLETENESS: her canonical issue tam olarak 1 coverage
    # ========================================================

    issue_id_counts = Counter(
        covered_issue_ids
    )

    for issue_id in issue_index.keys():

        count = issue_id_counts.get(
            issue_id,
            0,
        )

        if count != 1:

            errors.append(
                f"Issue '{issue_id}' için coverage kaydı "
                f"sayısı {count} - tam olarak 1 olmalıdır."
            )

    return errors


# ============================================================
# DECISION VALIDATION
# ============================================================

def validate_decisions(
    decision_records,
    issue_index,
    research_index,
    coverage_by_id,
    documents_index,
):

    errors = []

    ids = [
        record.get(
            "decision_id"
        )
        for record in decision_records
        if isinstance(
            record,
            dict,
        )
    ]

    for (
        decision_id,
        count,
    ) in Counter(
        ids
    ).items():

        if count > 1:

            errors.append(
                f"Duplicate decision_id: {decision_id}"
            )

    seen_document_ids_by_issue = {}

    for record in decision_records:

        if not isinstance(
            record,
            dict,
        ):

            continue

        decision_id = record.get(
            "decision_id"
        )

        source_issue_id = record.get(
            "source_issue_id"
        )

        if source_issue_id not in issue_index:

            errors.append(
                f"{decision_id}: source_issue_id canonical "
                f"issues.json içinde bulunamadı: "
                f"{source_issue_id}"
            )

        for research_id in record.get(
            "source_research_ids",
            [],
        ):

            if research_id not in research_index:

                errors.append(
                    f"{decision_id}: source_research_id "
                    "canonical research.json içinde "
                    f"bulunamadı: {research_id}"
                )

        source_coverage_id = record.get(
            "source_coverage_id"
        )

        coverage = coverage_by_id.get(
            source_coverage_id
        )

        if coverage is None:

            errors.append(
                f"{decision_id}: source_coverage_id "
                f"bulunamadı: {source_coverage_id}"
            )

        elif (
            coverage.get(
                "source_issue_id"
            )
            != source_issue_id
        ):

            errors.append(
                f"{decision_id}: source_coverage_id "
                f"'{source_coverage_id}' başka bir issue'ya "
                "ait "
                f"({coverage.get('source_issue_id')} != "
                f"{source_issue_id})."
            )

        # ====================================================
        # DEDUP: aynı issue altında aynı source_document_id
        # yalnız bir kez görünebilir.
        # ====================================================

        source_document_id = record.get(
            "source_document_id"
        )

        key = (
            source_issue_id,
            source_document_id,
        )

        seen_document_ids_by_issue.setdefault(
            source_issue_id,
            set(),
        )

        if (
            source_document_id
            in seen_document_ids_by_issue[
                source_issue_id
            ]
        ):

            errors.append(
                f"{decision_id}: source_document_id "
                f"'{source_document_id}' aynı issue "
                f"'{source_issue_id}' altında DUPLICATE "
                "(dedup ihlali)."
            )

        seen_document_ids_by_issue[
            source_issue_id
        ].add(
            source_document_id
        )

        # ====================================================
        # GROUNDING: source_document_id gerçek bir "Yargı
        # Kararı" olmalı; metadata canonical kayıtla birebir
        # eşleşmeli veya kaynakta yoksa null olmalı.
        # ====================================================

        document = documents_index.get(
            source_document_id
        )

        if document is None:

            errors.append(
                f"{decision_id}: source_document_id "
                "canonical documents.json içinde "
                f"bulunamadı (hayali document): "
                f"{source_document_id}"
            )

        elif (
            document.get(
                "belge_turu"
            )
            != "Yargı Kararı"
        ):

            errors.append(
                f"{decision_id}: source_document_id "
                f"'{source_document_id}' documents.json "
                "içinde belge_turu='Yargı Kararı' değil."
            )

        else:

            expected = {
                "court_name":
                    document.get(
                        "kaynak_kurum"
                    ),

                "court_unit":
                    document.get(
                        "daire"
                    ),

                "case_number":
                    document.get(
                        "document_number"
                    ),

                "decision_number":
                    document.get(
                        "karar_no"
                    ),

                "decision_date":
                    (
                        document.get(
                            "karar_tarihi"
                        )
                        or document.get(
                            "resmi_gazete_tarihi"
                        )
                    ),

                "source_url":
                    document.get(
                        "source_url"
                    ),
            }

            for (
                field,
                expected_value,
            ) in expected.items():

                actual_value = record.get(
                    field
                )

                if actual_value != expected_value:

                    errors.append(
                        f"{decision_id}: {field} "
                        "canonical documents.json "
                        "kaydıyla eşleşmiyor (beklenen="
                        f"{expected_value!r}, bulunan="
                        f"{actual_value!r})."
                    )

        if (
            record.get(
                "provenance_status"
            )
            != "verified_against_canonical_documents"
        ):

            errors.append(
                f"{decision_id}: provenance_status "
                "'verified_against_canonical_documents' "
                "olmalıdır."
            )

        if (
            record.get(
                "applicability_result"
            )
            not in (
                None,
                "unknown",
                "needs_review",
            )
        ):

            errors.append(
                f"{decision_id}: applicability_result "
                "yalnız null/'unknown'/'needs_review' "
                "olabilir (asla 'applicable')."
            )

        errors.extend(
            check_candidate_status(
                decision_id,
                record,
            )
        )

        errors.extend(
            check_forbidden_phrases(
                decision_id,
                record.get(
                    "title"
                ),

                record.get(
                    "description"
                ),
            )
        )

    return errors


# ============================================================
# AGENT SUGGESTION VALIDATION
# ============================================================

def validate_agent_suggestions(
    suggestion_records,
    issue_index,
    research_index,
):

    errors = []

    ids = [
        record.get(
            "suggestion_id"
        )
        for record in suggestion_records
        if isinstance(
            record,
            dict,
        )
    ]

    for (
        suggestion_id,
        count,
    ) in Counter(
        ids
    ).items():

        if count > 1:

            errors.append(
                f"Duplicate suggestion_id: {suggestion_id}"
            )

    for record in suggestion_records:

        if not isinstance(
            record,
            dict,
        ):

            continue

        suggestion_id = record.get(
            "suggestion_id"
        )

        source_issue_id = record.get(
            "source_issue_id"
        )

        if source_issue_id not in issue_index:

            errors.append(
                f"{suggestion_id}: source_issue_id "
                "canonical issues.json içinde bulunamadı: "
                f"{source_issue_id}"
            )

        for research_id in record.get(
            "source_research_ids",
            [],
        ):

            if research_id not in research_index:

                errors.append(
                    f"{suggestion_id}: source_research_id "
                    "canonical research.json içinde "
                    f"bulunamadı: {research_id}"
                )

        errors.extend(
            check_candidate_status(
                suggestion_id,
                record,
            )
        )

        errors.extend(
            check_forbidden_phrases(
                suggestion_id,
                record.get(
                    "title"
                ),

                record.get(
                    "description"
                ),
            )
        )

    return errors


# ============================================================
# CASE ID / GENERATED AT
# ============================================================

def validate_case_id(
    case_law_analysis,
    expected_case_id,
):

    errors = []

    found = case_law_analysis.get(
        "case_id"
    )

    if found != expected_case_id:

        errors.append(
            "Case law analysis case_id uyuşmazlığı. "
            f"Beklenen={expected_case_id}, "
            f"Bulunan={found}"
        )

    return errors


def validate_generated_at(
    case_law_analysis,
):

    errors = []

    generated_at = case_law_analysis.get(
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

def validate_case_law_analysis(
    case_law_path,
    expected_case_id=None,
    raise_on_error=False,
):

    case_law_path = Path(
        case_law_path
    )

    case_law_analysis = load_json(
        case_law_path
    )

    case_id = (
        expected_case_id
        or case_law_analysis.get(
            "case_id"
        )
    )

    if not case_id:

        raise CaseLawValidationError(
            "case_id belirlenemedi."
        )

    case_data, case_path = (
        load_case(
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

    (
        _researches,
        research_index,
        research_path,
    ) = (
        load_canonical_research(
            case_id
        )
    )

    documents_index = (
        load_legal_documents_index()
    )

    errors = []

    warnings = []

    errors.extend(
        validate_schema(
            case_law_analysis
        )
    )

    errors.extend(
        validate_case_id(
            case_law_analysis,
            case_id,
        )
    )

    errors.extend(
        validate_generated_at(
            case_law_analysis
        )
    )

    coverage_records = (
        case_law_analysis.get(
            "case_law_coverage",
            [],
        )
    )

    decision_records = (
        case_law_analysis.get(
            "case_law_decisions",
            [],
        )
    )

    suggestion_records = (
        case_law_analysis.get(
            "case_law_agent_suggestions",
            [],
        )
    )

    if not isinstance(
        coverage_records,
        list,
    ):

        coverage_records = []

    if not isinstance(
        decision_records,
        list,
    ):

        decision_records = []

    if not isinstance(
        suggestion_records,
        list,
    ):

        suggestion_records = []

    coverage_by_id = {
        record.get(
            "coverage_id"
        ): record
        for record in coverage_records
        if isinstance(
            record,
            dict,
        )
        and record.get(
            "coverage_id"
        )
    }

    decision_count_by_coverage_id = (
        Counter(
            record.get(
                "source_coverage_id"
            )
            for record in decision_records
            if isinstance(
                record,
                dict,
            )
        )
    )

    errors.extend(
        validate_coverage(
            coverage_records,
            issue_index,
            decision_count_by_coverage_id,
        )
    )

    errors.extend(
        validate_decisions(
            decision_records,
            issue_index,
            research_index,
            coverage_by_id,
            documents_index,
        )
    )

    errors.extend(
        validate_agent_suggestions(
            suggestion_records,
            issue_index,
            research_index,
        )
    )

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
            CASE_LAW_VALIDATOR_VERSION,

        "case_law_path":
            str(
                case_law_path
            ),

        "case_id":
            case_id,

        "case_path":
            str(
                case_path
            ),

        "research_path":
            (
                str(
                    research_path
                )
                if research_path.exists()
                else None
            ),

        "issue_count":
            len(
                issue_index
            ),

        "research_count":
            len(
                research_index
            ),

        "document_count":
            len(
                documents_index
            ),

        "coverage_count":
            len(
                coverage_records
            ),

        "decision_count":
            len(
                decision_records
            ),

        "agent_suggestion_count":
            len(
                suggestion_records
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

        raise CaseLawValidationError(
            "CASE LAW VALIDATOR V2: FAIL\n\n- "
            + "\n- ".join(
                errors
            )
        )

    return result


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
# DEMO CASE LAW ANALYSIS (SELF-TEST)
# ============================================================

def build_demo_case_law_analysis(
    case_id,
    retrieval_fn=None,
    network_allowed=False,
):

    from deadline_validator import (
        load_canonical_timeline,
    )

    from case_law_policy import (
        build_case_law_intent,
        finalize_coverage,
        finalize_decisions,
    )

    from case_law_discovery import (
        run_case_law_discovery_for_issues,
    )

    issue_context = (
        load_canonical_issues(
            case_id
        )
    )

    issues = issue_context[
        "issues"
    ]

    (
        researches,
        _research_index,
        _research_path,
    ) = (
        load_canonical_research(
            case_id
        )
    )

    researches_by_issue = {}

    for research in researches:

        researches_by_issue.setdefault(
            research[
                "source_issue_id"
            ],
            [],
        ).append(
            research
        )

    timeline_context = (
        load_canonical_timeline(
            case_id
        )
    )

    event_index = timeline_context[
        "events"
    ]

    documents_index = (
        load_legal_documents_index()
    )

    def build_intent_fn(
        issue,
    ):

        return (
            build_case_law_intent(
                issue,
                researches_by_issue.get(
                    issue[
                        "issue_id"
                    ],
                    [],
                ),
                event_index,
            )
        )

    (
        raw_coverage,
        raw_decisions,
        discovery_warnings,
    ) = (
        run_case_law_discovery_for_issues(
            issues=
                issues,

            build_intent_fn=
                build_intent_fn,

            documents_index=
                documents_index,

            retrieval_fn=
                retrieval_fn,

            network_allowed=
                network_allowed,
        )
    )

    coverage_records = (
        finalize_coverage(
            raw_coverage
        )
    )

    decision_records = (
        finalize_decisions(
            raw_decisions
        )
    )

    return {
        "schema_version":
            2,

        "case_law_analysis_id":
            f"case_law_{case_id}_demo_v1",

        "case_id":
            case_id,

        "status":
            "completed",

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "case_law_coverage":
            coverage_records,

        "case_law_decisions":
            decision_records,

        "case_law_agent_suggestions": [],

        "warnings":
            discovery_warnings,

        "notes":
            (
                "Case Law Validator V2 self-test fixture."
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
        " VERGİ AI - CASE LAW VALIDATOR V2"
    )

    print(
        "======================================"
    )

    # ========================================================
    # T01 SCHEMA LOAD
    # ========================================================

    assert (
        CASE_LAW_SCHEMA_PATH.exists()
    )

    load_json(
        CASE_LAW_SCHEMA_PATH
    )

    print(
        "T01 Case law schema load:",
        "PASS"
    )

    # ========================================================
    # T02 CANONICAL CONTEXT LOAD
    # ========================================================

    issue_context = (
        load_canonical_issues(
            case_id
        )
    )

    (
        _researches,
        research_index,
        research_path,
    ) = (
        load_canonical_research(
            case_id
        )
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
        "T02 Canonical issue/research load:",
        "PASS"
    )

    # ========================================================
    # T03/T12: NETWORK OFF -> 1 COVERAGE PER ISSUE, 0
    # DECISION (COVERAGE COMPLETENESS)
    # ========================================================

    demo = (
        build_demo_case_law_analysis(
            case_id,

            retrieval_fn=
                None,

            network_allowed=
                False,
        )
    )

    assert (
        len(
            demo[
                "case_law_coverage"
            ]
        )
        == len(
            issue_context[
                "issue_index"
            ]
        )
    ), (
        "Her canonical issue için tam olarak bir coverage "
        "kaydı beklenir."
    )

    assert (
        len(
            demo[
                "case_law_decisions"
            ]
        )
        == 0
    )

    for coverage in demo[
        "case_law_coverage"
    ]:

        assert (
            coverage[
                "status"
            ]
            == "candidate"
        )

        assert (
            coverage[
                "requires_human_review"
            ]
            is True
        )

        assert (
            coverage[
                "execution_state"
            ]
            == "retrieval_not_run"
        )

        assert (
            coverage[
                "decision_count"
            ]
            == 0
        )

    print(
        "T03 Network off -> 1 coverage/issue "
        "(retrieval_not_run), 0 decisions "
        "(T12 completeness dahil):",
        "PASS"
    )

    temp_dir = (
        tempfile.TemporaryDirectory(
            prefix=
                "case_law_validator_selftest_"
        )
    )

    case_law_dir = Path(
        temp_dir.name
    )

    # ========================================================
    # T04 VALID CASE LAW ANALYSIS
    # ========================================================

    valid_path = (
        case_law_dir
        / "case_law_validator_v2_test.json"
    )

    write_json(
        valid_path,
        demo,
    )

    result = (
        validate_case_law_analysis(
            case_law_path=
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
        "T04 Valid case law analysis (retrieval_not_run "
        "state):",
        "PASS"
    )

    # ========================================================
    # T05/T14: 1 GROUNDED DECISION -> 1 coverage +
    # 1 decision
    # ========================================================

    synthetic_docs = {
        "yargi_test_001": {
            "document_id":
                "yargi_test_001",

            "belge_turu":
                "Yargı Kararı",

            "kaynak_kurum":
                "Danıştay Dördüncü Dairesi",

            "karar_tarihi":
                "2019-03-12",

            "document_number":
                "2018/1000 E, 2019/500 K",

            "source_url":
                "https://example.invalid/karar-1",
        }
    }

    def retrieval_one_found(
        query,
        kanun_no=None,
        madde=None,
        fikra=None,
        bent=None,
        belge_turu=None,
        temporal_mode=None,
        query_date=None,
    ):

        # ----------------------------------------------------
        # Yalnız issue_002'nin citation-based sorgusuyla
        # eşleşir (IYUK_2577_m7_1 ilk citation'dır); diğer
        # issue'lar için boş döner. Bu, testin "TEK bir
        # issue 1 karar bulur" senaryosunu net bir şekilde
        # izole etmesini sağlar (retrieval_fn gerçekte sorgu
        # içeriğine duyarlı olmalıdır - burada da öyle
        # davranır).
        # ----------------------------------------------------

        if "IYUK_2577_m7_1" not in query:

            return {
                "results": [],

                "retrieval_failure_reason":
                    None,
            }

        return {
            "results": [
                {
                    "document_id":
                        "yargi_test_001",

                    "belge_turu":
                        "Yargı Kararı",

                    "chunk_id":
                        "chunk_1",
                }
            ],

            "retrieval_failure_reason":
                None,
        }

    original_loader = (
        globals()[
            "load_legal_documents_index"
        ]
    )

    globals()[
        "load_legal_documents_index"
    ] = (
        lambda: synthetic_docs
    )

    try:

        demo_one_decision = (
            build_demo_case_law_analysis(
                case_id,

                retrieval_fn=
                    retrieval_one_found,

                network_allowed=
                    True,
            )
        )

        found_coverage = [
            record
            for record in demo_one_decision[
                "case_law_coverage"
            ]
            if record[
                "execution_state"
            ]
            == "retrieval_completed"
        ]

        assert (
            len(
                found_coverage
            )
            == 1
        )

        assert (
            found_coverage[
                0
            ][
                "decision_count"
            ]
            == 1
        )

        assert (
            len(
                demo_one_decision[
                    "case_law_decisions"
                ]
            )
            == 1
        )

        one_path = (
            case_law_dir
            / "case_law_validator_v2_one_decision.json"
        )

        write_json(
            one_path,
            demo_one_decision,
        )

        one_result = (
            validate_case_law_analysis(
                one_path,
                case_id,
            )
        )

        if not one_result[
            "valid"
        ]:

            print()

            for error in one_result[
                "errors"
            ]:

                print(
                    "-",
                    error,
                )

        assert (
            one_result[
                "valid"
            ]
            is True
        )

        decision = demo_one_decision[
            "case_law_decisions"
        ][
            0
        ]

        assert (
            decision[
                "court_name"
            ]
            == "Danıştay Dördüncü Dairesi"
        )

        assert (
            decision[
                "court_unit"
            ]
            is None
        ), "documents.json'da 'daire' alanı yok -> null"

        assert (
            decision[
                "applicability_result"
            ]
            == "needs_review"
        )

        assert (
            decision[
                "provenance_status"
            ]
            == "verified_against_canonical_documents"
        )

    finally:

        globals()[
            "load_legal_documents_index"
        ] = (
            original_loader
        )

    print(
        "T05 One grounded decision -> 1 coverage "
        "(retrieval_completed, decision_count=1) + "
        "1 decision; unavailable metadata stays null "
        "(T09/T14 dahil):",
        "PASS"
    )

    # ========================================================
    # T06/T13: 3 FARKLI GROUNDED KARAR -> 1 coverage +
    # 3 decision, DEDUP TEST'İ İLE BİRLİKTE (aynı
    # document_id 2 kez dönerse tek decision kalır)
    # ========================================================

    synthetic_docs_three = {
        "yargi_test_001": synthetic_docs[
            "yargi_test_001"
        ],

        "yargi_test_002": {
            "document_id":
                "yargi_test_002",

            "belge_turu":
                "Yargı Kararı",

            "kaynak_kurum":
                "Danıştay Üçüncü Dairesi",

            "karar_tarihi":
                "2020-06-01",

            "document_number":
                "2019/50 E, 2020/60 K",

            "source_url":
                "https://example.invalid/karar-2",
        },

        "yargi_test_003": {
            "document_id":
                "yargi_test_003",

            "belge_turu":
                "Yargı Kararı",

            "kaynak_kurum":
                "Vergi Mahkemesi",

            "karar_tarihi":
                "2021-01-15",

            "document_number":
                "2020/10 E, 2021/20 K",

            "source_url":
                "https://example.invalid/karar-3",
        },
    }

    def retrieval_three_found_with_duplicate(
        query,
        kanun_no=None,
        madde=None,
        fikra=None,
        bent=None,
        belge_turu=None,
        temporal_mode=None,
        query_date=None,
    ):

        # Yalnız issue_002'nin sorgusuyla eşleşir (bkz.
        # retrieval_one_found açıklaması) - tek bir issue'nun
        # 3 karar bulduğu senaryoyu izole eder.

        if "IYUK_2577_m7_1" not in query:

            return {
                "results": [],

                "retrieval_failure_reason":
                    None,
            }

        return {
            "results": [
                {
                    "document_id":
                        "yargi_test_001",

                    "belge_turu":
                        "Yargı Kararı",

                    "chunk_id":
                        "chunk_1a",
                },

                # ---- AYNI document_id TEKRAR (dedup testi)
                {
                    "document_id":
                        "yargi_test_001",

                    "belge_turu":
                        "Yargı Kararı",

                    "chunk_id":
                        "chunk_1b",
                },

                {
                    "document_id":
                        "yargi_test_002",

                    "belge_turu":
                        "Yargı Kararı",

                    "chunk_id":
                        "chunk_2",
                },

                {
                    "document_id":
                        "yargi_test_003",

                    "belge_turu":
                        "Yargı Kararı",

                    "chunk_id":
                        "chunk_3",
                },
            ],

            "retrieval_failure_reason":
                None,
        }

    globals()[
        "load_legal_documents_index"
    ] = (
        lambda: synthetic_docs_three
    )

    try:

        demo_three = (
            build_demo_case_law_analysis(
                case_id,

                retrieval_fn=
                    retrieval_three_found_with_duplicate,

                network_allowed=
                    True,
            )
        )

        found_coverage = [
            record
            for record in demo_three[
                "case_law_coverage"
            ]
            if record[
                "execution_state"
            ]
            == "retrieval_completed"
        ]

        assert (
            len(
                found_coverage
            )
            == 1
        ), (
            "Yalnız bir issue'nun 3 karar bulması "
            "beklenir (research citation'a sahip ilk "
            "issue)."
        )

        assert (
            found_coverage[
                0
            ][
                "decision_count"
            ]
            == 3
        ), "Duplicate document_id dedupe edilmeli (2->1)."

        matching_decisions = [
            decision
            for decision in demo_three[
                "case_law_decisions"
            ]
            if decision[
                "source_coverage_id"
            ]
            == found_coverage[
                0
            ][
                "coverage_id"
            ]
        ]

        assert (
            len(
                matching_decisions
            )
            == 3
        )

        document_ids = [
            decision[
                "source_document_id"
            ]
            for decision in matching_decisions
        ]

        assert (
            len(
                document_ids
            )
            == len(
                set(
                    document_ids
                )
            )
        ), "Aynı issue altında duplicate document_id olamaz."

        three_path = (
            case_law_dir
            / "case_law_validator_v2_three_decisions.json"
        )

        write_json(
            three_path,
            demo_three,
        )

        three_result = (
            validate_case_law_analysis(
                three_path,
                case_id,
            )
        )

        if not three_result[
            "valid"
        ]:

            print()

            for error in three_result[
                "errors"
            ]:

                print(
                    "-",
                    error,
                )

        assert (
            three_result[
                "valid"
            ]
            is True
        )

    finally:

        globals()[
            "load_legal_documents_index"
        ] = (
            original_loader
        )

    print(
        "T06 Three grounded decisions from one issue "
        "(with a duplicate chunk) -> 1 coverage "
        "(decision_count=3) + exactly 3 deduplicated "
        "decisions (T13 dahil):",
        "PASS"
    )

    # ========================================================
    # T07 RETRIEVAL EXCEPTION -> retrieval_failed
    # ========================================================

    def retrieval_crash(
        query,
        kanun_no=None,
        madde=None,
        fikra=None,
        bent=None,
        belge_turu=None,
        temporal_mode=None,
        query_date=None,
    ):

        raise RuntimeError(
            "simulated crash"
        )

    demo_crash = (
        build_demo_case_law_analysis(
            case_id,

            retrieval_fn=
                retrieval_crash,

            network_allowed=
                True,
        )
    )

    assert all(
        record[
            "execution_state"
        ]
        == "retrieval_failed"
        for record in demo_crash[
            "case_law_coverage"
        ]
    )

    assert (
        len(
            demo_crash[
                "case_law_decisions"
            ]
        )
        == 0
    )

    print(
        "T07 Retrieval exception -> retrieval_failed, "
        "0 decisions:",
        "PASS"
    )

    # ========================================================
    # T08 RETRIEVAL SUCCEEDS, EMPTY -> no_case_law_evidence
    # ========================================================

    def retrieval_empty(
        query,
        kanun_no=None,
        madde=None,
        fikra=None,
        bent=None,
        belge_turu=None,
        temporal_mode=None,
        query_date=None,
    ):

        return {
            "results": [],

            "retrieval_failure_reason":
                None,
        }

    demo_empty = (
        build_demo_case_law_analysis(
            case_id,

            retrieval_fn=
                retrieval_empty,

            network_allowed=
                True,
        )
    )

    assert all(
        record[
            "execution_state"
        ]
        == "no_case_law_evidence"
        for record in demo_empty[
            "case_law_coverage"
        ]
    )

    assert (
        len(
            demo_empty[
                "case_law_decisions"
            ]
        )
        == 0
    )

    print(
        "T08 Retrieval succeeds with 0 results -> "
        "no_case_law_evidence:",
        "PASS"
    )

    # ========================================================
    # T09 UNKNOWN SOURCE ISSUE ID
    # ========================================================

    broken = clone_json(
        demo
    )

    broken[
        "case_law_coverage"
    ][
        0
    ][
        "source_issue_id"
    ] = "issue_does_not_exist"

    broken_path = (
        case_law_dir
        / "case_law_validator_v2_unknown_issue.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_case_law_analysis(
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
        "T09 Unknown source_issue_id blocked:",
        "PASS"
    )

    # ========================================================
    # T07-EXTRA (as T10) HALLUCINATED DECISION DOCUMENT
    # ========================================================

    broken = clone_json(
        demo
    )

    first_issue_id = broken[
        "case_law_coverage"
    ][
        0
    ][
        "source_issue_id"
    ]

    broken[
        "case_law_coverage"
    ][
        0
    ][
        "execution_state"
    ] = "retrieval_completed"

    broken[
        "case_law_coverage"
    ][
        0
    ][
        "decision_count"
    ] = 1

    hallucinated_decision = {
        "decision_id":
            "case_law_decision_900",

        "source_issue_id":
            first_issue_id,

        "source_research_ids": [],

        "source_coverage_id":
            broken[
                "case_law_coverage"
            ][
                0
            ][
                "coverage_id"
            ],

        "source_document_id":
            "yargitay_9999_hayali",

        "court_name":
            "Uydurma Mahkeme",

        "court_unit":
            None,

        "case_number":
            "2020/1",

        "decision_number":
            None,

        "decision_date":
            "2020-01-01",

        "source_url":
            None,

        "retrieved_chunk_id":
            None,

        "provenance_status":
            "verified_against_canonical_documents",

        "applicability_result":
            "needs_review",

        "title":
            "Test",

        "description":
            "Test decision.",

        "trigger_rule_id":
            "test_rule",

        "confidence":
            0.5,

        "requires_human_review":
            True,

        "status":
            "candidate",

        "notes":
            None,
    }

    broken[
        "case_law_decisions"
    ].append(
        hallucinated_decision
    )

    broken_path = (
        case_law_dir
        / "case_law_validator_v2_hallucinated.json"
    )

    write_json(
        broken_path,
        broken,
    )

    broken_result = (
        validate_case_law_analysis(
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
        "T10 Hallucinated decision document blocked:",
        "PASS"
    )

    # ========================================================
    # T11 CANONICAL METADATA MISMATCH -> FAIL
    # ========================================================

    globals()[
        "load_legal_documents_index"
    ] = (
        lambda: synthetic_docs
    )

    try:

        demo_mismatch = clone_json(
            demo_one_decision
        )

        demo_mismatch[
            "case_law_decisions"
        ][
            0
        ][
            "court_name"
        ] = "Yanlış Mahkeme Adı"

        mismatch_path = (
            case_law_dir
            / "case_law_validator_v2_mismatch.json"
        )

        write_json(
            mismatch_path,
            demo_mismatch,
        )

        mismatch_result = (
            validate_case_law_analysis(
                mismatch_path,
                case_id,
            )
        )

        assert (
            mismatch_result[
                "valid"
            ]
            is False
        )

    finally:

        globals()[
            "load_legal_documents_index"
        ] = (
            original_loader
        )

    print(
        "T11 court_name mismatch vs canonical documents.json "
        "blocked:",
        "PASS"
    )

    # ========================================================
    # T12 (bkz. T03) - zaten yukarıda coverage completeness
    # olarak test edildi.
    #
    # T13 (bkz. T06) - zaten yukarıda 3-decision testi
    # olarak test edildi.
    # ========================================================

    # ========================================================
    # T14 (FINAL VALIDATOR PASS) - APPLICABILITY='applicable'
    # SCHEMA SEVİYESİNDE REDDİ
    # ========================================================

    globals()[
        "load_legal_documents_index"
    ] = (
        lambda: synthetic_docs
    )

    try:

        broken = clone_json(
            demo_one_decision
        )

        broken[
            "case_law_decisions"
        ][
            0
        ][
            "applicability_result"
        ] = "applicable"

        applicability_path = (
            case_law_dir
            / "case_law_validator_v2_applicability.json"
        )

        write_json(
            applicability_path,
            broken,
        )

        applicability_result = (
            validate_case_law_analysis(
                applicability_path,
                case_id,
            )
        )

        assert (
            applicability_result[
                "valid"
            ]
            is False
        )

    finally:

        globals()[
            "load_legal_documents_index"
        ] = (
            original_loader
        )

    print(
        "T14 applicability_result='applicable' rejected "
        "(schema-level, never allowed):",
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
        "Canonical research count:",
        len(
            research_index
        ),
    )

    print(
        "Demo coverage count (network off):",
        len(
            demo[
                "case_law_coverage"
            ]
        ),
    )

    for coverage in demo[
        "case_law_coverage"
    ]:

        print(
            "-",
            coverage[
                "coverage_id"
            ],
            "|",
            "issue=" + coverage[
                "source_issue_id"
            ],
            "|",
            coverage[
                "execution_state"
            ],
            "|",
            "decisions=" + str(
                coverage[
                    "decision_count"
                ]
            ),
        )

    print()

    print(
        "======================================"
    )

    print(
        " CASE LAW VALIDATOR V2: 14/14 PASS"
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
            "Vergi AI Case Law Validator V2"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--case-law",
        dest="case_law_path",
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
        or args.case_law_path is None
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
        " VERGİ AI - CASE LAW VALIDATOR V2"
    )

    print(
        "======================================"
    )

    try:

        result = (
            validate_case_law_analysis(
                case_law_path=
                    Path(
                        args.case_law_path
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
            " CASE LAW VALIDATOR V2: FAIL"
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
        "Coverage count:",
        result[
            "coverage_count"
        ],
    )

    print(
        "Decision count:",
        result[
            "decision_count"
        ],
    )

    print(
        "Agent suggestion count:",
        result[
            "agent_suggestion_count"
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
            " CASE LAW VALIDATOR V2: PASS"
        )

    else:

        print(
            " CASE LAW VALIDATOR V2: FAIL"
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
