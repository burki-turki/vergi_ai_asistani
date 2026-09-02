# ============================================================
# VERGİ AI - EVIDENCE VALIDATOR V1
#
# AMAÇ:
#
# Evidence Engine çıktısını üç seviyede doğrulamak:
#
# 1. JSON Schema
# 2. Canonical issue / approved fact / active document çapraz
#    bütünlük ve semantic safety
# 3. Input manifest (analysis_metadata) hash tutarlılığı -
#    stale input downstream guard
#
#
# TEMEL PRENSİP
# -------------
#
# - evidence_coverage: HER canonical issue için TAM OLARAK BİR
#   kayıt. Bir evidence candidate DEĞİLDİR.
# - evidence_candidates: source_fact_id yalnız approved
#   (canonical facts.json) bir fact olabilir; source_document_id
#   fact'in KENDİ source_document_id'si olmalı VE active=true
#   canonical case document olmalıdır. source_location/
#   source_excerpt fact'in kendi source kaydıyla BİREBİR
#   eşleşmelidir (icat edilmiş/kaymış olamaz).
# - evidence_agent_suggestions: suggestion_type'a göre
#   conditional grounding (bkz. evidence_policy.
#   SUGGESTION_GROUNDING_SPEC) yeniden doğrulanır (defense in
#   depth - agent zaten kontrol etmiştir).
# - analysis_metadata'daki hash'ler GÜNCEL canonical
#   issues/facts/active-documents ile eşleşmiyorsa analiz
#   STALE sayılır ve validator FAIL döner (downstream
#   kullanım engellenir).
#
# TEST FIXTURE ISOLATION: self-test fixture'ları
# data/cases/<case_id>/evidence/ altına DEĞİL, işletim sistemi
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

from timeline_validator import (
    load_canonical_fact_index,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)

from evidence_policy import (
    COVERAGE_EXECUTION_STATES,
    SUGGESTION_GROUNDING_SPEC,
    ZERO_CANDIDATE_EXECUTION_STATES,
    ZERO_SUGGESTION_EXECUTION_STATES,
    load_active_case_documents_index,
    sha256_of,
)


# ============================================================
# VERSION
# ============================================================

EVIDENCE_VALIDATOR_VERSION = "1"

ALL_FORBIDDEN_PHRASES = tuple(
    FORBIDDEN_PHRASES
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

EVIDENCE_SCHEMA_PATH = (
    DATA_DIR
    / "case_evidence.schema.json"
)

DEFAULT_CASE_ID = "case_0001"


# ============================================================
# EXCEPTIONS
# ============================================================

class EvidenceValidationError(
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

        raise EvidenceValidationError(
            "case.json case_id uyuşmazlığı.\n"
            f"Beklenen: {case_id}\n"
            f"Bulunan: {case_data.get('case_id')}"
        )

    return (
        case_data,
        case_path,
    )


# ============================================================
# EVIDENCE PATHS
# ============================================================

def get_evidence_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "evidence"
    )


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_schema(
    evidence_analysis,
):

    schema = load_json(
        EVIDENCE_SCHEMA_PATH
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
            evidence_analysis
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
# FORBIDDEN PHRASE GUARD
# ============================================================

def check_forbidden_phrases(
    record_id,
    *texts,
):

    errors = []

    combined = normalize_text_tr(
        " ".join(
            text or ""
            for text in texts
        )
    )

    for phrase in ALL_FORBIDDEN_PHRASES:

        if phrase in combined:

            errors.append(
                f"{record_id}: metin kesin hukuki sonuç/"
                f"admissibility ifadesi içeriyor ('{phrase}')."
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
# ANALYSIS METADATA / STALE INPUT GUARD
# ============================================================

def validate_analysis_metadata(
    analysis_metadata,
    issues,
    fact_index,
    active_documents_index,
):

    errors = []

    if not isinstance(
        analysis_metadata,
        dict,
    ):

        return [
            "analysis_metadata dict değil."
        ]

    current_hashes = {
        "issues_input_hash":
            sha256_of(
                issues
            ),

        "facts_input_hash":
            sha256_of(
                {
                    fact_id: record[
                        "fact"
                    ]
                    for fact_id, record
                    in fact_index.items()
                }
            ),

        "documents_input_hash":
            sha256_of(
                active_documents_index
            ),
    }

    for field, current_value in current_hashes.items():

        recorded_value = analysis_metadata.get(
            field
        )

        if recorded_value != current_value:

            errors.append(
                f"analysis_metadata.{field} güncel canonical "
                "veriyle eşleşmiyor (STALE INPUT - bu analiz "
                "downstream'de kullanılamaz). Kayıtlı="
                f"{recorded_value!r}, Güncel={current_value!r}"
            )

    return errors


# ============================================================
# COVERAGE VALIDATION
# ============================================================

def validate_coverage(
    coverage_records,
    issue_index,
    candidate_count_by_issue,
    suggestion_count_by_issue,
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

    for coverage_id, count in Counter(
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

        candidate_count = record.get(
            "candidate_count"
        )

        actual_candidate_count = (
            candidate_count_by_issue.get(
                source_issue_id,
                0,
            )
        )

        if candidate_count != actual_candidate_count:

            errors.append(
                f"{coverage_id}: candidate_count="
                f"{candidate_count} ancak fiilen bağlı "
                f"candidate sayısı={actual_candidate_count}."
            )

        suggestion_count = record.get(
            "suggestion_count"
        )

        actual_suggestion_count = (
            suggestion_count_by_issue.get(
                source_issue_id,
                0,
            )
        )

        if suggestion_count != actual_suggestion_count:

            errors.append(
                f"{coverage_id}: suggestion_count="
                f"{suggestion_count} ancak fiilen bağlı "
                f"suggestion sayısı="
                f"{actual_suggestion_count}."
            )

        if (
            execution_state
            in ZERO_CANDIDATE_EXECUTION_STATES
            and candidate_count != 0
        ):

            errors.append(
                f"{coverage_id}: execution_state="
                f"'{execution_state}' iken candidate_count "
                "0 olmalıdır."
            )

        if (
            execution_state
            in ZERO_SUGGESTION_EXECUTION_STATES
            and suggestion_count != 0
        ):

            errors.append(
                f"{coverage_id}: execution_state="
                f"'{execution_state}' iken suggestion_count "
                "0 olmalıdır."
            )

        if (
            execution_state
            in (
                "analysis_partial",
                "analysis_failed",
            )
            and not record.get(
                "reason_codes"
            )
        ):

            errors.append(
                f"{coverage_id}: execution_state="
                f"'{execution_state}' iken reason_codes "
                "boş olamaz."
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
# CANDIDATE VALIDATION
# ============================================================

def validate_candidates(
    candidate_records,
    issue_index,
    fact_index,
    active_documents_index,
):

    errors = []

    ids = [
        record.get(
            "candidate_id"
        )
        for record in candidate_records
        if isinstance(
            record,
            dict,
        )
    ]

    for candidate_id, count in Counter(
        ids
    ).items():

        if count > 1:

            errors.append(
                f"Duplicate candidate_id: {candidate_id}"
            )

    seen_dedup_keys = set()

    for record in candidate_records:

        if not isinstance(
            record,
            dict,
        ):

            continue

        candidate_id = record.get(
            "candidate_id"
        )

        source_issue_id = record.get(
            "source_issue_id"
        )

        if source_issue_id not in issue_index:

            errors.append(
                f"{candidate_id}: source_issue_id canonical "
                f"issues.json içinde bulunamadı: "
                f"{source_issue_id}"
            )

        source_fact_id = record.get(
            "source_fact_id"
        )

        fact_record = fact_index.get(
            source_fact_id
        )

        if fact_record is None:

            errors.append(
                f"{candidate_id}: source_fact_id approved "
                f"(canonical) facts.json içinde bulunamadı "
                f"(hayali/unapproved fact): {source_fact_id}"
            )

        source_document_id = record.get(
            "source_document_id"
        )

        if (
            fact_record is not None
            and fact_record[
                "source_document_id"
            ]
            != source_document_id
        ):

            errors.append(
                f"{candidate_id}: source_document_id "
                f"'{source_document_id}' fact "
                f"'{source_fact_id}'in KENDİ belgesi "
                f"({fact_record['source_document_id']}) "
                "ile eşleşmiyor (allowlist escape)."
            )

        if source_document_id not in active_documents_index:

            errors.append(
                f"{candidate_id}: source_document_id active "
                "canonical case document olarak bulunamadı: "
                f"{source_document_id}"
            )

        if fact_record is not None:

            expected_source = (
                fact_record[
                    "fact"
                ].get(
                    "source",
                    {},
                )
                or {}
            )

            expected_location = {
                "page":
                    expected_source.get(
                        "page"
                    ),

                "section":
                    expected_source.get(
                        "section"
                    ),

                "paragraph":
                    expected_source.get(
                        "paragraph"
                    ),

                "text_excerpt":
                    expected_source.get(
                        "text_excerpt"
                    ),
            }

            actual_location = record.get(
                "source_location"
            )

            if actual_location != expected_location:

                errors.append(
                    f"{candidate_id}: source_location fact "
                    f"'{source_fact_id}'in kendi canonical "
                    "source kaydıyla birebir eşleşmiyor "
                    "(icat edilmiş/kaymış konum). Beklenen="
                    f"{expected_location!r}, Bulunan="
                    f"{actual_location!r}"
                )

            expected_excerpt = expected_source.get(
                "text_excerpt"
            )

            actual_excerpt = record.get(
                "source_excerpt"
            )

            if actual_excerpt != expected_excerpt:

                errors.append(
                    f"{candidate_id}: source_excerpt fact "
                    f"'{source_fact_id}'in "
                    "source.text_excerpt alanıyla birebir "
                    f"eşleşmiyor. Beklenen="
                    f"{expected_excerpt!r}, Bulunan="
                    f"{actual_excerpt!r}"
                )

        relationship_candidate = record.get(
            "relationship_candidate"
        )

        if relationship_candidate not in (
            "supports",
            "contradicts",
        ):

            errors.append(
                f"{candidate_id}: geçersiz "
                f"relationship_candidate: "
                f"{relationship_candidate}"
            )

        dedup_key = (
            source_issue_id,
            source_fact_id,
            source_document_id,
            relationship_candidate,
        )

        if dedup_key in seen_dedup_keys:

            errors.append(
                f"{candidate_id}: (issue, fact, document, "
                f"relationship) DUPLICATE: {dedup_key}"
            )

        seen_dedup_keys.add(
            dedup_key
        )

        errors.extend(
            check_candidate_status(
                candidate_id,
                record,
            )
        )

        errors.extend(
            check_forbidden_phrases(
                candidate_id,
                record.get(
                    "grounded_explanation"
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
    fact_index,
    active_documents_index,
    candidate_ids,
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

    for suggestion_id, count in Counter(
        ids
    ).items():

        if count > 1:

            errors.append(
                f"Duplicate suggestion_id: {suggestion_id}"
            )

    known_reference_ids = (
        set(
            fact_index.keys()
        )
        | set(
            active_documents_index.keys()
        )
        | set(
            candidate_ids
        )
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
                f"{suggestion_id}: source_issue_id canonical "
                "issues.json içinde bulunamadı: "
                f"{source_issue_id}"
            )

        suggestion_type = record.get(
            "suggestion_type"
        )

        spec = SUGGESTION_GROUNDING_SPEC.get(
            suggestion_type
        )

        if spec is None:

            errors.append(
                f"{suggestion_id}: geçersiz suggestion_type: "
                f"{suggestion_type}"
            )

            continue

        source_fact_id = record.get(
            "source_fact_id"
        )

        source_document_id = record.get(
            "source_document_id"
        )

        related_reference_ids = record.get(
            "related_reference_ids",
            [],
        )

        if (
            spec[
                "requires_fact"
            ]
            and not source_fact_id
        ):

            errors.append(
                f"{suggestion_id}: suggestion_type="
                f"'{suggestion_type}' için source_fact_id "
                "zorunludur."
            )

        if (
            spec[
                "requires_document"
            ]
            and not source_document_id
        ):

            errors.append(
                f"{suggestion_id}: suggestion_type="
                f"'{suggestion_type}' için "
                "source_document_id zorunludur."
            )

        if (
            spec[
                "forbids_document"
            ]
            and source_document_id
        ):

            errors.append(
                f"{suggestion_id}: suggestion_type="
                f"'{suggestion_type}' source_document_id "
                "İÇEREMEZ."
            )

        if (
            len(
                related_reference_ids
            )
            < spec[
                "min_related_references"
            ]
        ):

            errors.append(
                f"{suggestion_id}: suggestion_type="
                f"'{suggestion_type}' en az "
                f"{spec['min_related_references']} "
                "related_reference_ids gerektirir."
            )

        if (
            source_fact_id
            and source_fact_id not in fact_index
        ):

            errors.append(
                f"{suggestion_id}: source_fact_id approved "
                f"facts.json içinde bulunamadı: "
                f"{source_fact_id}"
            )

        if (
            source_document_id
            and source_document_id
            not in active_documents_index
        ):

            errors.append(
                f"{suggestion_id}: source_document_id "
                "active canonical case document olarak "
                f"bulunamadı: {source_document_id}"
            )

        for reference_id in related_reference_ids:

            if reference_id not in known_reference_ids:

                errors.append(
                    f"{suggestion_id}: related_reference_ids "
                    "içinde bilinmeyen bir referans "
                    f"(grounding hatası): {reference_id}"
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
    evidence_analysis,
    expected_case_id,
):

    errors = []

    found = evidence_analysis.get(
        "case_id"
    )

    if found != expected_case_id:

        errors.append(
            "Evidence analysis case_id uyuşmazlığı. "
            f"Beklenen={expected_case_id}, Bulunan={found}"
        )

    return errors


def validate_generated_at(
    evidence_analysis,
):

    errors = []

    generated_at = evidence_analysis.get(
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

def validate_evidence_analysis(
    evidence_path,
    expected_case_id=None,
    raise_on_error=False,
):

    evidence_path = Path(
        evidence_path
    )

    evidence_analysis = load_json(
        evidence_path
    )

    case_id = (
        expected_case_id
        or evidence_analysis.get(
            "case_id"
        )
    )

    if not case_id:

        raise EvidenceValidationError(
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

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = fact_context[
        "facts"
    ]

    active_documents_index = (
        load_active_case_documents_index(
            case_id
        )
    )

    errors = []

    warnings = []

    errors.extend(
        validate_schema(
            evidence_analysis
        )
    )

    errors.extend(
        validate_case_id(
            evidence_analysis,
            case_id,
        )
    )

    errors.extend(
        validate_generated_at(
            evidence_analysis
        )
    )

    errors.extend(
        validate_analysis_metadata(
            evidence_analysis.get(
                "analysis_metadata"
            ),

            issue_context[
                "issues"
            ],

            fact_index,

            active_documents_index,
        )
    )

    coverage_records = (
        evidence_analysis.get(
            "evidence_coverage",
            [],
        )
    )

    candidate_records = (
        evidence_analysis.get(
            "evidence_candidates",
            [],
        )
    )

    suggestion_records = (
        evidence_analysis.get(
            "evidence_agent_suggestions",
            [],
        )
    )

    if not isinstance(
        coverage_records,
        list,
    ):

        coverage_records = []

    if not isinstance(
        candidate_records,
        list,
    ):

        candidate_records = []

    if not isinstance(
        suggestion_records,
        list,
    ):

        suggestion_records = []

    candidate_count_by_issue = Counter(
        record.get(
            "source_issue_id"
        )
        for record in candidate_records
        if isinstance(
            record,
            dict,
        )
    )

    suggestion_count_by_issue = Counter(
        record.get(
            "source_issue_id"
        )
        for record in suggestion_records
        if isinstance(
            record,
            dict,
        )
    )

    candidate_ids = [
        record.get(
            "candidate_id"
        )
        for record in candidate_records
        if isinstance(
            record,
            dict,
        )
        and record.get(
            "candidate_id"
        )
    ]

    errors.extend(
        validate_coverage(
            coverage_records,
            issue_index,
            candidate_count_by_issue,
            suggestion_count_by_issue,
        )
    )

    errors.extend(
        validate_candidates(
            candidate_records,
            issue_index,
            fact_index,
            active_documents_index,
        )
    )

    errors.extend(
        validate_agent_suggestions(
            suggestion_records,
            issue_index,
            fact_index,
            active_documents_index,
            candidate_ids,
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
            EVIDENCE_VALIDATOR_VERSION,

        "evidence_path":
            str(
                evidence_path
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

        "active_document_count":
            len(
                active_documents_index
            ),

        "coverage_count":
            len(
                coverage_records
            ),

        "candidate_count":
            len(
                candidate_records
            ),

        "suggestion_count":
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

        raise EvidenceValidationError(
            "EVIDENCE VALIDATOR V1: FAIL\n\n- "
            + "\n- ".join(
                errors
            )
        )

    return result


# ============================================================
# DEMO EVIDENCE ANALYSIS (SELF-TEST) - lazy import to avoid
# circular import (evidence_engine imports this module for
# validate_evidence_analysis).
# ============================================================

def build_demo_evidence_analysis(
    case_id,
    use_agent=False,
    llm_client=None,
    network_allowed=False,
):

    from evidence_engine import (
        build_evidence_engine_output,
    )

    build_result = (
        build_evidence_engine_output(
            case_id,
            use_agent=
                use_agent,

            llm_client=
                llm_client,

            network_allowed=
                network_allowed,
        )
    )

    return build_result[
        "analysis"
    ]


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(
    case_id,
):

    from evidence_agent import (
        FakeEvidenceLLMClient,
    )

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - EVIDENCE VALIDATOR V1"
    )

    print(
        "======================================"
    )

    # ========================================================
    # T01 SCHEMA LOAD
    # ========================================================

    assert EVIDENCE_SCHEMA_PATH.exists()

    load_json(
        EVIDENCE_SCHEMA_PATH
    )

    print(
        "T01 Evidence schema load:",
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

    fact_context = (
        load_canonical_fact_index(
            case_id
        )
    )

    active_documents_index = (
        load_active_case_documents_index(
            case_id
        )
    )

    assert len(
        issue_context[
            "issue_index"
        ]
    ) >= 1

    assert len(
        fact_context[
            "facts"
        ]
    ) >= 1

    assert len(
        active_documents_index
    ) >= 1

    print(
        "T02 Canonical issue/fact/document context load:",
        "PASS"
    )

    temp_dir = (
        tempfile.TemporaryDirectory(
            prefix=
                "evidence_validator_selftest_"
        )
    )

    evidence_dir = Path(
        temp_dir.name
    )

    # ========================================================
    # T03 OFFLINE BASELINE: agent off -> 1 coverage/issue,
    # execution_state analysis_not_run OR blocked_missing_input
    # (allowlist_count'a bağlı), 0 candidate, 0 suggestion
    # ========================================================

    demo = (
        build_demo_evidence_analysis(
            case_id,

            use_agent=
                False,
        )
    )

    assert (
        len(
            demo[
                "evidence_coverage"
            ]
        )
        == len(
            issue_context[
                "issue_index"
            ]
        )
    )

    assert (
        len(
            demo[
                "evidence_candidates"
            ]
        )
        == 0
    )

    assert (
        len(
            demo[
                "evidence_agent_suggestions"
            ]
        )
        == 0
    )

    for coverage in demo[
        "evidence_coverage"
    ]:

        assert coverage[
            "execution_state"
        ] in (
            "analysis_not_run",
            "blocked_missing_input",
        )

        assert coverage[
            "candidate_count"
        ] == 0

        assert coverage[
            "suggestion_count"
        ] == 0

    baseline_path = (
        evidence_dir
        / "evidence_validator_v1_baseline.json"
    )

    write_json(
        baseline_path,
        demo,
    )

    baseline_result = (
        validate_evidence_analysis(
            evidence_path=
                baseline_path,

            expected_case_id=
                case_id,

            raise_on_error=
                False,
        )
    )

    if not baseline_result[
        "valid"
    ]:

        print()

        for error in baseline_result[
            "errors"
        ]:

            print(
                "-",
                error,
            )

    assert baseline_result[
        "valid"
    ] is True

    print(
        "T03 Offline baseline (agent off, coverage "
        "completeness, 0 candidate/suggestion):",
        "PASS"
    )

    # ========================================================
    # PICK TWO REAL ALLOWLIST ENTRIES FROM CASE_0001 FOR
    # GROUNDED CANDIDATE TESTS
    # ========================================================

    from evidence_discovery import (
        build_allowlist_for_issues,
    )

    (
        allowlist_by_issue,
        _warnings,
    ) = build_allowlist_for_issues(
        issue_context[
            "issues"
        ],

        fact_context[
            "facts"
        ],

        active_documents_index,
    )

    non_empty_issue_ids = [
        issue_id
        for issue_id, entries
        in allowlist_by_issue.items()
        if entries
    ]

    assert len(
        non_empty_issue_ids
    ) >= 2, (
        "Test için en az 2 non-empty allowlist issue'su "
        "gerekir."
    )

    entry_a = allowlist_by_issue[
        non_empty_issue_ids[
            0
        ]
    ][
        0
    ]

    entry_b = allowlist_by_issue[
        non_empty_issue_ids[
            1
        ]
    ][
        0
    ]

    # ========================================================
    # T04/T05 GROUNDED SUPPORTS + CONTRADICTS CANDIDATE
    # ========================================================

    good_response = json.dumps(
        {
            "candidates": [
                {
                    "source_issue_id":
                        entry_a[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry_a[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry_a[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "supports",

                    "reason_code":
                        "explicit_textual_match",
                },

                {
                    "source_issue_id":
                        entry_b[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry_b[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry_b[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "contradicts",

                    "reason_code":
                        "general_contextual_relevance",
                },
            ],

            "suggestions": [],
        },
        ensure_ascii=False,
    )

    client = FakeEvidenceLLMClient(
        response_text=
            good_response
    )

    demo_two_candidates = (
        build_demo_evidence_analysis(
            case_id,

            use_agent=
                True,

            llm_client=
                client,
        )
    )

    assert (
        len(
            demo_two_candidates[
                "evidence_candidates"
            ]
        )
        == 2
    )

    supports = [
        c
        for c in demo_two_candidates[
            "evidence_candidates"
        ]
        if c[
            "relationship_candidate"
        ]
        == "supports"
    ]

    contradicts = [
        c
        for c in demo_two_candidates[
            "evidence_candidates"
        ]
        if c[
            "relationship_candidate"
        ]
        == "contradicts"
    ]

    assert len(
        supports
    ) == 1

    assert len(
        contradicts
    ) == 1

    assert "confidence" not in supports[
        0
    ]

    two_path = (
        evidence_dir
        / "evidence_validator_v1_two_candidates.json"
    )

    write_json(
        two_path,
        demo_two_candidates,
    )

    two_result = (
        validate_evidence_analysis(
            two_path,
            case_id,
        )
    )

    if not two_result[
        "valid"
    ]:

        print()

        for error in two_result[
            "errors"
        ]:

            print(
                "-",
                error,
            )

    assert two_result[
        "valid"
    ] is True

    print(
        "T04/T05 Grounded supports + contradicts candidate "
        "(no confidence field):",
        "PASS"
    )

    # ========================================================
    # T06 DUPLICATE REJECTION
    # ========================================================

    duplicate_response = json.dumps(
        {
            "candidates": [
                {
                    "source_issue_id":
                        entry_a[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry_a[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry_a[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "supports",

                    "reason_code":
                        "explicit_textual_match",
                },

                {
                    "source_issue_id":
                        entry_a[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry_a[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry_a[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "supports",

                    "reason_code":
                        "temporal_consistency",
                },
            ],

            "suggestions": [],
        },
        ensure_ascii=False,
    )

    client = FakeEvidenceLLMClient(
        response_text=
            duplicate_response
    )

    demo_dup = (
        build_demo_evidence_analysis(
            case_id,

            use_agent=
                True,

            llm_client=
                client,
        )
    )

    assert (
        len(
            demo_dup[
                "evidence_candidates"
            ]
        )
        == 1
    ), "Duplicate (issue,fact,document,relationship) dedup edilmeli."

    print(
        "T06 Duplicate (issue, fact, document, relationship) "
        "rejected (dedup):",
        "PASS"
    )

    # ========================================================
    # T07 INVALID FACT (allowlist escape - ghost fact_id)
    # ========================================================

    invalid_fact_response = json.dumps(
        {
            "candidates": [
                {
                    "source_issue_id":
                        entry_a[
                            "issue_id"
                        ],

                    "source_fact_id":
                        "fact_does_not_exist_ghost",

                    "source_document_id":
                        entry_a[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "supports",

                    "reason_code":
                        "explicit_textual_match",
                },
            ],

            "suggestions": [],
        },
        ensure_ascii=False,
    )

    client = FakeEvidenceLLMClient(
        response_text=
            invalid_fact_response
    )

    demo_invalid_fact = (
        build_demo_evidence_analysis(
            case_id,

            use_agent=
                True,

            llm_client=
                client,
        )
    )

    assert (
        len(
            demo_invalid_fact[
                "evidence_candidates"
            ]
        )
        == 0
    )

    print(
        "T07 Invalid/ghost fact_id rejected (allowlist "
        "escape):",
        "PASS"
    )

    # ========================================================
    # T08 GHOST DOCUMENT (fact/document mismatch)
    # ========================================================

    other_document_id = next(
        (
            document_id
            for document_id
            in active_documents_index.keys()
            if document_id
            != entry_a[
                "document_id"
            ]
        ),
        None,
    )

    if other_document_id:

        mismatched_response = json.dumps(
            {
                "candidates": [
                    {
                        "source_issue_id":
                            entry_a[
                                "issue_id"
                            ],

                        "source_fact_id":
                            entry_a[
                                "fact_id"
                            ],

                        "source_document_id":
                            other_document_id,

                        "relationship_candidate":
                            "supports",

                        "reason_code":
                            "explicit_textual_match",
                    },
                ],

                "suggestions": [],
            },
            ensure_ascii=False,
        )

        client = FakeEvidenceLLMClient(
            response_text=
                mismatched_response
        )

        demo_ghost_document = (
            build_demo_evidence_analysis(
                case_id,

                use_agent=
                    True,

                llm_client=
                    client,
            )
        )

        assert (
            len(
                demo_ghost_document[
                    "evidence_candidates"
                ]
            )
            == 0
        )

    print(
        "T08 Fact/document mismatch (ghost pairing) "
        "rejected:",
        "PASS"
    )

    # ========================================================
    # T09 CONFIDENCE-FIELD SMUGGLING REJECTED (LLM tries to
    # add confidence directly to candidate signal)
    # ========================================================

    confidence_smuggling_response = json.dumps(
        {
            "candidates": [
                {
                    "source_issue_id":
                        entry_a[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry_a[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry_a[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "supports",

                    "reason_code":
                        "explicit_textual_match",

                    "confidence":
                        0.99,
                },
            ],

            "suggestions": [],
        },
        ensure_ascii=False,
    )

    client = FakeEvidenceLLMClient(
        response_text=
            confidence_smuggling_response
    )

    demo_confidence = (
        build_demo_evidence_analysis(
            case_id,

            use_agent=
                True,

            llm_client=
                client,
        )
    )

    assert (
        len(
            demo_confidence[
                "evidence_candidates"
            ]
        )
        == 0
    )

    print(
        "T09 Confidence-field smuggling rejected "
        "(structural, agent cannot set confidence):",
        "PASS"
    )

    # ========================================================
    # T10 INVENTED SOURCE_LOCATION SMUGGLING REJECTED
    # ========================================================

    location_smuggling_response = json.dumps(
        {
            "candidates": [
                {
                    "source_issue_id":
                        entry_a[
                            "issue_id"
                        ],

                    "source_fact_id":
                        entry_a[
                            "fact_id"
                        ],

                    "source_document_id":
                        entry_a[
                            "document_id"
                        ],

                    "relationship_candidate":
                        "supports",

                    "reason_code":
                        "explicit_textual_match",

                    "source_location": {
                        "page": 1,
                        "section": "Uydurma",
                        "paragraph": None,
                        "text_excerpt": "Uydurma alıntı",
                    },
                },
            ],

            "suggestions": [],
        },
        ensure_ascii=False,
    )

    client = FakeEvidenceLLMClient(
        response_text=
            location_smuggling_response
    )

    demo_location = (
        build_demo_evidence_analysis(
            case_id,

            use_agent=
                True,

            llm_client=
                client,
        )
    )

    assert (
        len(
            demo_location[
                "evidence_candidates"
            ]
        )
        == 0
    )

    print(
        "T10 Invented source_location smuggling rejected "
        "(structural):",
        "PASS"
    )

    # ========================================================
    # T11 MISMATCHED EXCERPT (VALIDATOR-LEVEL TAMPER TEST)
    # ========================================================

    tampered = clone_json(
        demo_two_candidates
    )

    tampered[
        "evidence_candidates"
    ][
        0
    ][
        "source_excerpt"
    ] = "Bu alıntı fact ile eşleşmiyor."

    tampered_path = (
        evidence_dir
        / "evidence_validator_v1_mismatched_excerpt.json"
    )

    write_json(
        tampered_path,
        tampered,
    )

    tampered_result = (
        validate_evidence_analysis(
            tampered_path,
            case_id,
        )
    )

    assert tampered_result[
        "valid"
    ] is False

    print(
        "T11 Mismatched source_excerpt blocked (validator-"
        "level tamper detection):",
        "PASS"
    )

    # ========================================================
    # T12 ALLOWLIST ESCAPE (VALIDATOR-LEVEL TAMPER TEST) -
    # source_document_id changed post-generation to another
    # active document that is NOT the fact's own document.
    # ========================================================

    if other_document_id:

        tampered = clone_json(
            demo_two_candidates
        )

        tampered[
            "evidence_candidates"
        ][
            0
        ][
            "source_document_id"
        ] = other_document_id

        tampered_path = (
            evidence_dir
            / "evidence_validator_v1_allowlist_escape.json"
        )

        write_json(
            tampered_path,
            tampered,
        )

        tampered_result = (
            validate_evidence_analysis(
                tampered_path,
                case_id,
            )
        )

        assert tampered_result[
            "valid"
        ] is False

    print(
        "T12 Allowlist escape (fact/document re-pairing "
        "post-generation) blocked:",
        "PASS"
    )

    # ========================================================
    # T13 METADATA SMUGGLING VIA SCHEMA (extra 'confidence' "
    # key injected directly into a candidate dict)
    # ========================================================

    tampered = clone_json(
        demo_two_candidates
    )

    tampered[
        "evidence_candidates"
    ][
        0
    ][
        "confidence"
    ] = 0.9

    tampered_path = (
        evidence_dir
        / "evidence_validator_v1_confidence_injection.json"
    )

    write_json(
        tampered_path,
        tampered,
    )

    tampered_result = (
        validate_evidence_analysis(
            tampered_path,
            case_id,
        )
    )

    assert tampered_result[
        "valid"
    ] is False

    print(
        "T13 Confidence field injection on candidate "
        "rejected (schema additionalProperties=false):",
        "PASS"
    )

    # ========================================================
    # T14 SUGGESTION-TO-CANDIDATE ESCALATION REJECTED
    # (relationship_candidate injected into a suggestion)
    # ========================================================

    good_suggestion_response = json.dumps(
        {
            "candidates": [],

            "suggestions": [
                {
                    "source_issue_id":
                        entry_a[
                            "issue_id"
                        ],

                    "suggestion_type":
                        "additional_verification",

                    "source_fact_id":
                        entry_a[
                            "fact_id"
                        ],

                    "source_document_id":
                        None,

                    "related_reference_ids": [
                        entry_a[
                            "fact_id"
                        ]
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )

    client = FakeEvidenceLLMClient(
        response_text=
            good_suggestion_response
    )

    demo_suggestion = (
        build_demo_evidence_analysis(
            case_id,

            use_agent=
                True,

            llm_client=
                client,
        )
    )

    assert (
        len(
            demo_suggestion[
                "evidence_agent_suggestions"
            ]
        )
        == 1
    )

    tampered = clone_json(
        demo_suggestion
    )

    tampered[
        "evidence_agent_suggestions"
    ][
        0
    ][
        "relationship_candidate"
    ] = "supports"

    tampered_path = (
        evidence_dir
        / "evidence_validator_v1_escalation.json"
    )

    write_json(
        tampered_path,
        tampered,
    )

    tampered_result = (
        validate_evidence_analysis(
            tampered_path,
            case_id,
        )
    )

    assert tampered_result[
        "valid"
    ] is False

    print(
        "T14 Suggestion-to-candidate escalation "
        "(relationship_candidate injection) rejected:",
        "PASS"
    )

    # ========================================================
    # T15 COUNT MISMATCH
    # ========================================================

    tampered = clone_json(
        demo_two_candidates
    )

    for coverage in tampered[
        "evidence_coverage"
    ]:

        if (
            coverage[
                "source_issue_id"
            ]
            == entry_a[
                "issue_id"
            ]
        ):

            coverage[
                "candidate_count"
            ] = 999

    tampered_path = (
        evidence_dir
        / "evidence_validator_v1_count_mismatch.json"
    )

    write_json(
        tampered_path,
        tampered,
    )

    tampered_result = (
        validate_evidence_analysis(
            tampered_path,
            case_id,
        )
    )

    assert tampered_result[
        "valid"
    ] is False

    print(
        "T15 candidate_count mismatch vs actual array "
        "blocked:",
        "PASS"
    )

    # ========================================================
    # T16 EXECUTION-STATE CONSISTENCY (analysis_not_run ile
    # candidate_count>0 çelişkisi)
    # ========================================================

    tampered = clone_json(
        demo
    )

    tampered[
        "evidence_coverage"
    ][
        0
    ][
        "execution_state"
    ] = "analysis_not_run"

    tampered[
        "evidence_coverage"
    ][
        0
    ][
        "candidate_count"
    ] = 1

    tampered_path = (
        evidence_dir
        / "evidence_validator_v1_state_consistency.json"
    )

    write_json(
        tampered_path,
        tampered,
    )

    tampered_result = (
        validate_evidence_analysis(
            tampered_path,
            case_id,
        )
    )

    assert tampered_result[
        "valid"
    ] is False

    print(
        "T16 execution_state='analysis_not_run' with "
        "candidate_count>0 blocked (state consistency):",
        "PASS"
    )

    # ========================================================
    # T17 COVERAGE COMPLETENESS (missing coverage record)
    # ========================================================

    tampered = clone_json(
        demo
    )

    tampered[
        "evidence_coverage"
    ].pop()

    tampered_path = (
        evidence_dir
        / "evidence_validator_v1_missing_coverage.json"
    )

    write_json(
        tampered_path,
        tampered,
    )

    tampered_result = (
        validate_evidence_analysis(
            tampered_path,
            case_id,
        )
    )

    assert tampered_result[
        "valid"
    ] is False

    print(
        "T17 Coverage completeness (missing coverage "
        "record) blocked:",
        "PASS"
    )

    # ========================================================
    # T18 INPUT HASH STALE DETECTION
    # ========================================================

    tampered = clone_json(
        demo
    )

    tampered[
        "analysis_metadata"
    ][
        "facts_input_hash"
    ] = "0" * 64

    tampered_path = (
        evidence_dir
        / "evidence_validator_v1_stale.json"
    )

    write_json(
        tampered_path,
        tampered,
    )

    tampered_result = (
        validate_evidence_analysis(
            tampered_path,
            case_id,
        )
    )

    assert tampered_result[
        "valid"
    ] is False

    assert any(
        "STALE" in error
        for error in tampered_result[
            "errors"
        ]
    )

    print(
        "T18 Stale input_hash (facts changed since "
        "generation) blocked:",
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
        "Approved fact count:",
        len(
            fact_context[
                "facts"
            ]
        ),
    )

    print(
        "Active document count:",
        len(
            active_documents_index
        ),
    )

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE VALIDATOR V1: 18/18 PASS"
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
            "Vergi AI Evidence Validator V1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--evidence",
        dest="evidence_path",
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
        or args.evidence_path is None
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
        " VERGİ AI - EVIDENCE VALIDATOR V1"
    )

    print(
        "======================================"
    )

    try:

        result = (
            validate_evidence_analysis(
                evidence_path=
                    Path(
                        args.evidence_path
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
            " EVIDENCE VALIDATOR V1: FAIL"
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
        "Candidate count:",
        result[
            "candidate_count"
        ],
    )

    print(
        "Suggestion count:",
        result[
            "suggestion_count"
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

    print()

    print(
        "======================================"
    )

    if result[
        "valid"
    ]:

        print(
            " EVIDENCE VALIDATOR V1: PASS"
        )

    else:

        print(
            " EVIDENCE VALIDATOR V1: FAIL"
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
