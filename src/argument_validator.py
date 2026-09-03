# ============================================================
# VERGİ AI - ARGUMENT VALIDATOR V1
#
# AMAÇ:
#
# Argument Engine çıktısını üç seviyede doğrulamak:
#
# 1. JSON Schema
# 2. Canonical issue/approved fact/(varsa) evidence-research-
#    case_law-timeline-deadline çapraz bütünlük, topology ve
#    same-issue-scope semantic safety
# 3. Input manifest (analysis_metadata) hash tutarlılığı -
#    stale input downstream guard
#
# TEST FIXTURE ISOLATION: self-test fixture'ları
# data/cases/<case_id>/arguments/ altına DEĞİL, işletim
# sistemi geçici dizinine yazılır.
# ============================================================


import argparse
import json
import sys
import tempfile

from collections import Counter
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from issue_spotting_validator import FORBIDDEN_PHRASES

from legal_research_validator import load_canonical_issues

from legal_research_policy import FINDING_STATUS_RESOLVED

from timeline_validator import load_canonical_fact_index

from timeline_consolidation_policy import normalize_text_tr

from argument_policy import (
    CLAIM_TYPES,
    COUNTER_TYPES,
    COVERAGE_EXECUTION_STATES,
    LEGAL_CLAIM_TYPES,
    LEGAL_COUNTER_TYPES,
    LEGAL_REBUTTAL_TYPES,
    MAX_GROUNDED_EXPLANATION_LENGTH,
    REBUTTAL_TYPES,
    SUGGESTION_GROUNDING_SPEC,
    ZERO_CLAIM_EXECUTION_STATES,
    ZERO_SUGGESTION_EXECUTION_STATES,
    classify_related_reference_ids,
    collect_citable_texts,
    compute_claim_fingerprint,
    compute_counterargument_fingerprint,
    compute_depends_on_unconfirmed_authority,
    compute_depends_on_unconfirmed_evidence,
    compute_missing_legal_authority,
    compute_rebuttal_fingerprint,
    find_smuggled_ids,
    find_unsupported_numeric_tokens,
    find_unverified_quotes,
    sha256_of,
)

from argument_discovery import (
    build_allowlists_for_issues,
    load_canonical_case_law_optional,
    load_canonical_deadline_optional,
    load_canonical_evidence_optional,
    load_canonical_legal_research_optional,
    load_canonical_timeline_optional,
)


# ============================================================
# VERSION
# ============================================================

ARGUMENT_VALIDATOR_VERSION = "1"

ALL_FORBIDDEN_PHRASES = tuple(FORBIDDEN_PHRASES)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

CASES_DIR = DATA_DIR / "cases"

ARGUMENT_SCHEMA_PATH = DATA_DIR / "case_arguments.schema.json"

DEFAULT_CASE_ID = "case_0001"


# ============================================================
# EXCEPTIONS
# ============================================================

class ArgumentValidationError(Exception):
    pass


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path):

    path = Path(path)

    if not path.exists():

        raise FileNotFoundError(f"JSON dosyası bulunamadı:\n{path}")

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


def write_json(path, data):

    path = Path(path)

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:

        json.dump(data, file, ensure_ascii=False, indent=2)


def parse_iso_datetime(value):

    if not isinstance(value, str):

        return None

    try:

        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    except ValueError:

        return None


def clone_json(value):

    return json.loads(json.dumps(value, ensure_ascii=False))


# ============================================================
# CASE
# ============================================================

def load_case(case_id):

    case_path = CASES_DIR / case_id / "case.json"

    case_data = load_json(case_path)

    if case_data.get("case_id") != case_id:

        raise ArgumentValidationError(
            "case.json case_id uyuşmazlığı.\n"
            f"Beklenen: {case_id}\nBulunan: {case_data.get('case_id')}"
        )

    return (case_data, case_path)


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_schema(analysis):

    schema = load_json(ARGUMENT_SCHEMA_PATH)

    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    errors = sorted(
        validator.iter_errors(analysis),
        key=lambda error: list(error.absolute_path),
    )

    messages = []

    for error in errors:

        path = ".".join(str(part) for part in error.absolute_path)

        messages.append(f"{path}: {error.message}" if path else error.message)

    return messages


# ============================================================
# FORBIDDEN PHRASE / STATUS GUARDS
# ============================================================

def check_forbidden_phrases(record_id, *texts):

    errors = []

    combined = normalize_text_tr(" ".join(text or "" for text in texts))

    for phrase in ALL_FORBIDDEN_PHRASES:

        if phrase in combined:

            errors.append(
                f"{record_id}: metin kesin hukuki sonuç/outcome ifadesi "
                f"içeriyor ('{phrase}')."
            )

    return errors


def check_candidate_status(record_id, record):

    errors = []

    if record.get("status") != "candidate":

        errors.append(f"{record_id}: status='candidate' olmalıdır.")

    if record.get("requires_human_review") is not True:

        errors.append(
            f"{record_id}: requires_human_review=True olmalıdır."
        )

    return errors


# ============================================================
# INDEPENDENT FREE-TEXT SAFETY BATTERY (validator-local,
# argument_agent.py / check_text_safety() İMPORT ETMEZ - aynı
# düşük seviyeli argument_policy fonksiyonlarını kendi bağımsız
# orkestrasyonuyla çağırır. claim_text/counterargument_text/
# rebuttal_text/grounded_explanation (claim, counterargument,
# rebuttal, suggestion) alanlarının TÜMÜNE aynı şekilde
# uygulanır - agent ve validator birbirinden bağımsız iki
# defense-in-depth katmanı olarak kalır.)
# ============================================================

def check_independent_text_safety(
    record_id,
    field_label,
    text,
    max_length,
    declared_ids,
    known_reference_ids,
    citable_texts,
):

    errors = []

    errors.extend(check_forbidden_phrases(record_id, text))

    if not isinstance(text, str) or not text.strip():

        errors.append(f"{record_id}: {field_label} boş olamaz.")

        return errors

    if len(text) > max_length:

        errors.append(
            f"{record_id}: {field_label} uzunluk sınırını aşıyor."
        )

        return errors

    smuggled = find_smuggled_ids(text, declared_ids, known_reference_ids)

    if smuggled:

        errors.append(
            f"{record_id}: {field_label} içine bilinmeyen/deklare "
            f"edilmemiş ID gömülü: {smuggled}"
        )

    unverified_quotes = find_unverified_quotes(text, citable_texts)

    if unverified_quotes:

        errors.append(
            f"{record_id}: {field_label} içindeki alıntı referans "
            f"kaynaklarda birebir doğrulanamadı: {unverified_quotes}"
        )

    unsupported = find_unsupported_numeric_tokens(text, citable_texts)

    if unsupported:

        errors.append(
            f"{record_id}: {field_label} içindeki tarih/tutar referans "
            "kaynaklarda birebir bulunamadı (unsupported): "
            f"{unsupported}"
        )

    return errors


# ============================================================
# ANALYSIS METADATA / STALE INPUT GUARD
# ============================================================

def validate_analysis_metadata(
    analysis_metadata,
    issues,
    fact_index,
    evidence_candidate_index,
    evidence_exists,
    research_index,
    research_exists,
    case_law_decision_index,
    case_law_exists,
    timeline_event_index,
    timeline_exists,
    deadline_ids,
    deadline_exists,
):

    errors = []

    if not isinstance(analysis_metadata, dict):

        return ["analysis_metadata dict değil."]

    def check(field, recorded_value, exists, current_value):

        if not exists:

            if recorded_value is not None:

                errors.append(
                    f"analysis_metadata.{field} canonical kaynak mevcut "
                    "değilken null olmayan bir değer taşıyor."
                )

            return

        if recorded_value != current_value:

            errors.append(
                f"analysis_metadata.{field} güncel canonical veriyle "
                "eşleşmiyor (STALE INPUT - bu analiz downstream'de "
                f"kullanılamaz). Kayıtlı={recorded_value!r}, "
                f"Güncel={current_value!r}"
            )

    check(
        "issues_input_hash",
        analysis_metadata.get("issues_input_hash"),
        True,
        sha256_of(issues),
    )

    check(
        "facts_input_hash",
        analysis_metadata.get("facts_input_hash"),
        True,
        sha256_of(
            {fact_id: record["fact"] for fact_id, record in fact_index.items()}
        ),
    )

    check(
        "evidence_input_hash",
        analysis_metadata.get("evidence_input_hash"),
        evidence_exists,
        sha256_of(evidence_candidate_index),
    )

    check(
        "legal_research_input_hash",
        analysis_metadata.get("legal_research_input_hash"),
        research_exists,
        sha256_of(research_index),
    )

    check(
        "case_law_input_hash",
        analysis_metadata.get("case_law_input_hash"),
        case_law_exists,
        sha256_of(case_law_decision_index),
    )

    check(
        "timeline_input_hash",
        analysis_metadata.get("timeline_input_hash"),
        timeline_exists,
        sha256_of(timeline_event_index),
    )

    check(
        "deadline_input_hash",
        analysis_metadata.get("deadline_input_hash"),
        deadline_exists,
        sha256_of(sorted(deadline_ids)),
    )

    return errors


# ============================================================
# COVERAGE VALIDATION
# ============================================================

def validate_coverage(
    coverage_records,
    issue_index,
    claim_count_by_issue,
    counter_count_by_issue,
    rebuttal_count_by_issue,
    suggestion_count_by_issue,
    allowlist_by_issue,
):

    errors = []

    ids = [r.get("coverage_id") for r in coverage_records if isinstance(r, dict)]

    for coverage_id, count in Counter(ids).items():

        if count > 1:

            errors.append(f"Duplicate coverage_id: {coverage_id}")

    covered_issue_ids = []

    for record in coverage_records:

        if not isinstance(record, dict):

            continue

        coverage_id = record.get("coverage_id")

        source_issue_id = record.get("source_issue_id")

        covered_issue_ids.append(source_issue_id)

        if source_issue_id not in issue_index:

            errors.append(
                f"{coverage_id}: source_issue_id canonical issues.json "
                f"içinde bulunamadı: {source_issue_id}"
            )

        execution_state = record.get("execution_state")

        if execution_state not in COVERAGE_EXECUTION_STATES:

            errors.append(
                f"{coverage_id}: geçersiz execution_state: {execution_state}"
            )

        for count_field, actual_map in (
            ("claim_count", claim_count_by_issue),
            ("counterargument_count", counter_count_by_issue),
            ("rebuttal_count", rebuttal_count_by_issue),
            ("suggestion_count", suggestion_count_by_issue),
        ):

            recorded = record.get(count_field)

            actual = actual_map.get(source_issue_id, 0)

            if recorded != actual:

                errors.append(
                    f"{coverage_id}: {count_field}={recorded} ancak fiilen "
                    f"bağlı sayı={actual}."
                )

        # ----------------------------------------------------------
        # allowlist_count: pending/canonical içindeki değere GÜVENME.
        # Aynı deterministik allowlist üretim kuralları (canonical
        # issue + approved fact + active canonical document +
        # fact.source/source_location, (varsa) canonical evidence/
        # research/case_law/timeline/deadline) engine ile BİREBİR
        # AYNI saf fonksiyon (argument_discovery.
        # build_allowlists_for_issues) çağrılarak yeniden hesaplanır
        # ve karşılaştırılır. Uyuşmazlık validator hatasıdır.
        # ----------------------------------------------------------

        recorded_allowlist_count = record.get("allowlist_count")

        menu = allowlist_by_issue.get(source_issue_id)

        expected_allowlist_count = (
            menu["allowlist_count"] if menu is not None else None
        )

        if recorded_allowlist_count != expected_allowlist_count:

            errors.append(
                f"{coverage_id}: allowlist_count={recorded_allowlist_count} "
                "ancak canonical girdilerden bağımsız olarak yeniden "
                f"hesaplanan gerçek değer={expected_allowlist_count}."
            )

        if execution_state in ZERO_CLAIM_EXECUTION_STATES and (
            record.get("claim_count") != 0
            or record.get("counterargument_count") != 0
            or record.get("rebuttal_count") != 0
        ):

            errors.append(
                f"{coverage_id}: execution_state='{execution_state}' iken "
                "claim/counterargument/rebuttal count 0 olmalıdır."
            )

        if (
            execution_state in ZERO_SUGGESTION_EXECUTION_STATES
            and record.get("suggestion_count") != 0
        ):

            errors.append(
                f"{coverage_id}: execution_state='{execution_state}' iken "
                "suggestion_count 0 olmalıdır."
            )

        if execution_state in ("analysis_partial", "analysis_failed") and not record.get(
            "reason_codes"
        ):

            errors.append(
                f"{coverage_id}: execution_state='{execution_state}' iken "
                "reason_codes boş olamaz."
            )

        errors.extend(check_candidate_status(coverage_id, record))

    issue_id_counts = Counter(covered_issue_ids)

    for issue_id in issue_index.keys():

        count = issue_id_counts.get(issue_id, 0)

        if count != 1:

            errors.append(
                f"Issue '{issue_id}' için coverage kaydı sayısı {count} - "
                "tam olarak 1 olmalıdır."
            )

    return errors


# ============================================================
# REFERENCE SET GROUNDING (ORTAK - claim/counter/rebuttal)
# ============================================================

REF_FIELDS = (
    "source_fact_ids",
    "source_evidence_candidate_ids",
    "source_legal_research_ids",
    "source_case_law_ids",
    "source_timeline_event_ids",
    "source_deadline_ids",
)

# claim_text/counterargument_text/rebuttal_text şema maxLength'i (2000) -
# grounded_explanation'ın MAX_GROUNDED_EXPLANATION_LENGTH'inden (1000)
# farklıdır, bkz. case_arguments.schema.json.
MAX_ENTITY_TEXT_LENGTH = 2000


def validate_reference_set(
    record_id,
    issue_id,
    record,
    issue,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
    timeline_event_index,
    deadline_ids,
):

    errors = []

    issue_fact_ids = set(issue.get("source_fact_ids", []))

    for fact_id in record.get("source_fact_ids", []):

        if fact_id not in fact_index:

            errors.append(
                f"{record_id}: source_fact_id approved facts.json içinde "
                f"bulunamadı (hayali fact): {fact_id}"
            )

        elif fact_id not in issue_fact_ids:

            errors.append(
                f"{record_id}: fact '{fact_id}' bu issue'nun kendi "
                "linkajında değil (cross-issue leakage)."
            )

    for candidate_id in record.get("source_evidence_candidate_ids", []):

        candidate = evidence_candidate_index.get(candidate_id)

        if candidate is None:

            errors.append(
                f"{record_id}: source_evidence_candidate_id canonical "
                f"evidence.json içinde bulunamadı: {candidate_id}"
            )

        elif candidate.get("review_state") == "rejected":

            errors.append(
                f"{record_id}: rejected evidence candidate grounding "
                f"olarak kullanılamaz: {candidate_id}"
            )

        elif candidate.get("source_issue_id") != issue_id:

            errors.append(
                f"{record_id}: evidence candidate '{candidate_id}' başka "
                f"bir issue'ya ait (cross-issue leakage)."
            )

    for research_id in record.get("source_legal_research_ids", []):

        research = research_index.get(research_id)

        if research is None:

            errors.append(
                f"{record_id}: source_legal_research_id canonical "
                f"research.json içinde bulunamadı: {research_id}"
            )

        elif research.get("finding_status") not in FINDING_STATUS_RESOLVED:

            errors.append(
                f"{record_id}: research '{research_id}' resolved "
                "finding_status ailesinde değil - grounding olamaz."
            )

        elif research.get("source_issue_id") != issue_id:

            errors.append(
                f"{record_id}: research '{research_id}' başka bir "
                "issue'ya ait (cross-issue leakage)."
            )

    for decision_id in record.get("source_case_law_ids", []):

        decision = case_law_decision_index.get(decision_id)

        if decision is None:

            errors.append(
                f"{record_id}: source_case_law_id canonical case_law.json "
                f"içinde bulunamadı (hayali karar): {decision_id}"
            )

        elif decision.get("source_issue_id") != issue_id:

            errors.append(
                f"{record_id}: case law decision '{decision_id}' başka "
                "bir issue'ya ait (cross-issue leakage)."
            )

    issue_timeline_ids = set(issue.get("source_timeline_event_ids", []))

    for event_id in record.get("source_timeline_event_ids", []):

        if event_id not in timeline_event_index:

            errors.append(
                f"{record_id}: source_timeline_event_id canonical "
                f"timeline.json içinde bulunamadı: {event_id}"
            )

        elif event_id not in issue_timeline_ids:

            errors.append(
                f"{record_id}: timeline event '{event_id}' bu issue'nun "
                "kendi linkajında değil (cross-issue leakage)."
            )

    issue_deadline_ids = set(issue.get("source_deadline_ids", []))

    for deadline_id in record.get("source_deadline_ids", []):

        if deadline_id not in deadline_ids:

            errors.append(
                f"{record_id}: source_deadline_id canonical deadline.json "
                f"içinde bulunamadı: {deadline_id}"
            )

        elif deadline_id not in issue_deadline_ids:

            errors.append(
                f"{record_id}: deadline '{deadline_id}' bu issue'nun "
                "kendi linkajında değil (cross-issue leakage)."
            )

    return errors


def validate_flags(
    record_id,
    record,
    argument_type_field,
    legal_type_set,
    evidence_candidate_index,
    case_law_decision_index,
):

    errors = []

    expected_evidence_flag = compute_depends_on_unconfirmed_evidence(
        record, evidence_candidate_index
    )

    if record.get("depends_on_unconfirmed_evidence") != expected_evidence_flag:

        errors.append(
            f"{record_id}: depends_on_unconfirmed_evidence yanlış "
            f"hesaplanmış (beklenen={expected_evidence_flag})."
        )

    expected_authority_flag = compute_depends_on_unconfirmed_authority(
        record, case_law_decision_index
    )

    if record.get("depends_on_unconfirmed_authority") != expected_authority_flag:

        errors.append(
            f"{record_id}: depends_on_unconfirmed_authority yanlış "
            f"hesaplanmış (beklenen={expected_authority_flag})."
        )

    expected_missing_authority = compute_missing_legal_authority(
        record, record.get(argument_type_field), legal_type_set
    )

    if record.get("missing_legal_authority") != expected_missing_authority:

        errors.append(
            f"{record_id}: missing_legal_authority yanlış hesaplanmış "
            f"(beklenen={expected_missing_authority})."
        )

    return errors


# ============================================================
# CLAIM VALIDATION
# ============================================================

def validate_claims(
    claims,
    issue_index,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
    timeline_event_index,
    deadline_ids,
    known_reference_ids,
):

    errors = []

    ids = [c.get("claim_id") for c in claims if isinstance(c, dict)]

    for claim_id, count in Counter(ids).items():

        if count > 1:

            errors.append(f"Duplicate claim_id: {claim_id}")

    seen_fingerprints = set()

    for claim in claims:

        if not isinstance(claim, dict):

            continue

        claim_id = claim.get("claim_id")

        issue_id = claim.get("source_issue_id")

        issue = issue_index.get(issue_id)

        if issue is None:

            errors.append(
                f"{claim_id}: source_issue_id canonical issues.json "
                f"içinde bulunamadı: {issue_id}"
            )

            continue

        if claim.get("claim_type") not in CLAIM_TYPES:

            errors.append(f"{claim_id}: geçersiz claim_type.")

        if not claim.get("source_fact_ids"):

            errors.append(
                f"{claim_id}: minimum grounding ihlali - en az bir "
                "source_fact_id zorunlu."
            )

        errors.extend(
            validate_reference_set(
                claim_id, issue_id, claim, issue, fact_index,
                evidence_candidate_index, research_index,
                case_law_decision_index, timeline_event_index, deadline_ids,
            )
        )

        errors.extend(
            validate_flags(
                claim_id, claim, "claim_type", LEGAL_CLAIM_TYPES,
                evidence_candidate_index, case_law_decision_index,
            )
        )

        fingerprint = compute_claim_fingerprint(claim)

        if fingerprint in seen_fingerprints:

            errors.append(f"{claim_id}: duplicate claim (fingerprint çakışması).")

        seen_fingerprints.add(fingerprint)

        errors.extend(check_candidate_status(claim_id, claim))

        declared_ids = set()

        for field in REF_FIELDS:

            declared_ids |= set(claim.get(field) or [])

        citable_texts = collect_citable_texts(
            claim, fact_index, evidence_candidate_index, research_index,
            case_law_decision_index,
        )

        errors.extend(
            check_independent_text_safety(
                claim_id, "claim_text", claim.get("claim_text"),
                MAX_ENTITY_TEXT_LENGTH, declared_ids, known_reference_ids,
                citable_texts,
            )
        )

        errors.extend(
            check_independent_text_safety(
                claim_id, "grounded_explanation",
                claim.get("grounded_explanation"),
                MAX_GROUNDED_EXPLANATION_LENGTH, declared_ids,
                known_reference_ids, citable_texts,
            )
        )

    return errors


# ============================================================
# COUNTERARGUMENT VALIDATION
# ============================================================

def validate_counterarguments(
    counterarguments,
    claim_by_id,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
    timeline_event_index,
    deadline_ids,
    issue_index,
    known_reference_ids,
):

    errors = []

    ids = [
        c.get("counterargument_id")
        for c in counterarguments
        if isinstance(c, dict)
    ]

    for counterargument_id, count in Counter(ids).items():

        if count > 1:

            errors.append(f"Duplicate counterargument_id: {counterargument_id}")

    seen_fingerprints = set()

    for counter in counterarguments:

        if not isinstance(counter, dict):

            continue

        counterargument_id = counter.get("counterargument_id")

        claim_id = counter.get("source_claim_id")

        claim = claim_by_id.get(claim_id)

        if claim is None:

            errors.append(
                f"{counterargument_id}: source_claim_id bilinmiyor: "
                f"{claim_id}"
            )

            continue

        issue_id = counter.get("source_issue_id")

        if issue_id != claim.get("source_issue_id"):

            errors.append(
                f"{counterargument_id}: source_issue_id claim'in kendi "
                "issue'sı ile eşleşmiyor (same-issue-scope ihlali)."
            )

        issue = issue_index.get(issue_id)

        if issue is None:

            errors.append(
                f"{counterargument_id}: source_issue_id canonical "
                f"issues.json içinde bulunamadı: {issue_id}"
            )

            continue

        if counter.get("counter_type") not in COUNTER_TYPES:

            errors.append(f"{counterargument_id}: geçersiz counter_type.")

        has_any_ref = any(
            counter.get(field) for field in REF_FIELDS
        )

        if not has_any_ref:

            errors.append(
                f"{counterargument_id}: canonical grounding yok - en az "
                "bir referans zorunlu."
            )

        errors.extend(
            validate_reference_set(
                counterargument_id, issue_id, counter, issue, fact_index,
                evidence_candidate_index, research_index,
                case_law_decision_index, timeline_event_index, deadline_ids,
            )
        )

        errors.extend(
            validate_flags(
                counterargument_id, counter, "counter_type",
                LEGAL_COUNTER_TYPES, evidence_candidate_index,
                case_law_decision_index,
            )
        )

        fingerprint = compute_counterargument_fingerprint(counter)

        if fingerprint in seen_fingerprints:

            errors.append(
                f"{counterargument_id}: duplicate counterargument "
                "(fingerprint çakışması)."
            )

        seen_fingerprints.add(fingerprint)

        errors.extend(check_candidate_status(counterargument_id, counter))

        declared_ids = set()

        for field in REF_FIELDS:

            declared_ids |= set(counter.get(field) or [])

        citable_texts = collect_citable_texts(
            counter, fact_index, evidence_candidate_index, research_index,
            case_law_decision_index,
        )

        errors.extend(
            check_independent_text_safety(
                counterargument_id, "counterargument_text",
                counter.get("counterargument_text"),
                MAX_ENTITY_TEXT_LENGTH, declared_ids, known_reference_ids,
                citable_texts,
            )
        )

        errors.extend(
            check_independent_text_safety(
                counterargument_id, "grounded_explanation",
                counter.get("grounded_explanation"),
                MAX_GROUNDED_EXPLANATION_LENGTH, declared_ids,
                known_reference_ids, citable_texts,
            )
        )

    return errors


# ============================================================
# REBUTTAL VALIDATION
# ============================================================

def validate_rebuttals(
    rebuttals,
    counter_by_id,
    fact_index,
    evidence_candidate_index,
    research_index,
    case_law_decision_index,
    timeline_event_index,
    deadline_ids,
    issue_index,
    known_reference_ids,
):

    errors = []

    ids = [r.get("rebuttal_id") for r in rebuttals if isinstance(r, dict)]

    for rebuttal_id, count in Counter(ids).items():

        if count > 1:

            errors.append(f"Duplicate rebuttal_id: {rebuttal_id}")

    seen_fingerprints = set()

    for rebuttal in rebuttals:

        if not isinstance(rebuttal, dict):

            continue

        rebuttal_id = rebuttal.get("rebuttal_id")

        counterargument_id = rebuttal.get("source_counterargument_id")

        counter = counter_by_id.get(counterargument_id)

        if counter is None:

            errors.append(
                f"{rebuttal_id}: source_counterargument_id bilinmiyor: "
                f"{counterargument_id}"
            )

            continue

        if rebuttal.get("source_claim_id") != counter.get("source_claim_id"):

            errors.append(
                f"{rebuttal_id}: source_claim_id, referans verdiği "
                "counterargument'ın gerçek claim'i ile eşleşmiyor "
                "(wrong-claim topology ihlali)."
            )

        issue_id = rebuttal.get("source_issue_id")

        if issue_id != counter.get("source_issue_id"):

            errors.append(
                f"{rebuttal_id}: source_issue_id counterargument'ın "
                "kendi issue'sı ile eşleşmiyor (same-issue-scope ihlali)."
            )

        issue = issue_index.get(issue_id)

        if issue is None:

            errors.append(
                f"{rebuttal_id}: source_issue_id canonical issues.json "
                f"içinde bulunamadı: {issue_id}"
            )

            continue

        if rebuttal.get("rebuttal_type") not in REBUTTAL_TYPES:

            errors.append(f"{rebuttal_id}: geçersiz rebuttal_type.")

        has_any_ref = any(rebuttal.get(field) for field in REF_FIELDS)

        if not has_any_ref:

            errors.append(
                f"{rebuttal_id}: canonical grounding yok - en az bir "
                "referans zorunlu."
            )

        errors.extend(
            validate_reference_set(
                rebuttal_id, issue_id, rebuttal, issue, fact_index,
                evidence_candidate_index, research_index,
                case_law_decision_index, timeline_event_index, deadline_ids,
            )
        )

        errors.extend(
            validate_flags(
                rebuttal_id, rebuttal, "rebuttal_type", LEGAL_REBUTTAL_TYPES,
                evidence_candidate_index, case_law_decision_index,
            )
        )

        fingerprint = compute_rebuttal_fingerprint(rebuttal)

        if fingerprint in seen_fingerprints:

            errors.append(
                f"{rebuttal_id}: duplicate rebuttal (fingerprint çakışması)."
            )

        seen_fingerprints.add(fingerprint)

        errors.extend(check_candidate_status(rebuttal_id, rebuttal))

        declared_ids = set()

        for field in REF_FIELDS:

            declared_ids |= set(rebuttal.get(field) or [])

        citable_texts = collect_citable_texts(
            rebuttal, fact_index, evidence_candidate_index, research_index,
            case_law_decision_index,
        )

        errors.extend(
            check_independent_text_safety(
                rebuttal_id, "rebuttal_text",
                rebuttal.get("rebuttal_text"),
                MAX_ENTITY_TEXT_LENGTH, declared_ids, known_reference_ids,
                citable_texts,
            )
        )

        errors.extend(
            check_independent_text_safety(
                rebuttal_id, "grounded_explanation",
                rebuttal.get("grounded_explanation"),
                MAX_GROUNDED_EXPLANATION_LENGTH, declared_ids,
                known_reference_ids, citable_texts,
            )
        )

    return errors


# ============================================================
# AGENT SUGGESTION VALIDATION
# ============================================================

def validate_agent_suggestions(
    suggestions, issue_index, claim_by_id, counter_by_id, known_reference_ids,
    fact_index, evidence_candidate_index, research_index,
    case_law_decision_index,
):

    errors = []

    ids = [s.get("suggestion_id") for s in suggestions if isinstance(s, dict)]

    for suggestion_id, count in Counter(ids).items():

        if count > 1:

            errors.append(f"Duplicate suggestion_id: {suggestion_id}")

    for suggestion in suggestions:

        if not isinstance(suggestion, dict):

            continue

        suggestion_id = suggestion.get("suggestion_id")

        issue_id = suggestion.get("source_issue_id")

        if issue_id not in issue_index:

            errors.append(
                f"{suggestion_id}: source_issue_id canonical issues.json "
                f"içinde bulunamadı: {issue_id}"
            )

        suggestion_type = suggestion.get("suggestion_type")

        spec = SUGGESTION_GROUNDING_SPEC.get(suggestion_type)

        if spec is None:

            errors.append(f"{suggestion_id}: geçersiz suggestion_type.")

            continue

        claim_id = suggestion.get("source_claim_id")

        counterargument_id = suggestion.get("source_counterargument_id")

        if spec["requires_claim"] and claim_id not in claim_by_id:

            errors.append(
                f"{suggestion_id}: suggestion_type='{suggestion_type}' "
                "için geçerli source_claim_id zorunlu."
            )

        if claim_id is not None and claim_id not in claim_by_id:

            errors.append(f"{suggestion_id}: bilinmeyen source_claim_id.")

        if (
            spec["requires_counterargument"]
            and counterargument_id not in counter_by_id
        ):

            errors.append(
                f"{suggestion_id}: suggestion_type='{suggestion_type}' "
                "için geçerli source_counterargument_id zorunlu."
            )

        if (
            counterargument_id is not None
            and counterargument_id not in counter_by_id
        ):

            errors.append(
                f"{suggestion_id}: bilinmeyen source_counterargument_id."
            )

        related_reference_ids = suggestion.get("related_reference_ids", [])

        if len(related_reference_ids) < spec["min_related_references"]:

            errors.append(
                f"{suggestion_id}: suggestion_type='{suggestion_type}' en "
                f"az {spec['min_related_references']} related_reference_ids "
                "gerektirir."
            )

        for reference_id in related_reference_ids:

            if reference_id not in known_reference_ids:

                errors.append(
                    f"{suggestion_id}: related_reference_ids içinde "
                    f"bilinmeyen referans: {reference_id}"
                )

        errors.extend(check_candidate_status(suggestion_id, suggestion))

        # --------------------------------------------------------
        # SUGGESTION FREE-TEXT SAFETY - INDEPENDENT RE-CHECK
        # (Finding 2 remediation, now unified with claim/counter-
        # argument/rebuttal via check_independent_text_safety - Row
        # 13 corrective maintenance C1). Bu, argument_agent.py'nin
        # check_text_safety() sarmalayıcısını ÇAĞIRMAZ; aynı düşük
        # seviyeli argument_policy fonksiyonlarını DOĞRUDAN, kendi
        # bağımsız orkestrasyonuyla kullanır - agent stage filtresi
        # ile validator birbirinden bağımsız defense-in-depth
        # sağlar.
        # --------------------------------------------------------

        grounded_explanation = suggestion.get("grounded_explanation")

        declared_ids = set(related_reference_ids)

        if claim_id:

            declared_ids.add(claim_id)

        if counterargument_id:

            declared_ids.add(counterargument_id)

        classified_ref_set = classify_related_reference_ids(
            related_reference_ids, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index,
        )

        citable_texts = collect_citable_texts(
            classified_ref_set, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index,
        )

        referenced_claim = claim_by_id.get(claim_id)

        if referenced_claim is not None:

            citable_texts.append(referenced_claim["claim_text"])

        referenced_counter = counter_by_id.get(counterargument_id)

        if referenced_counter is not None:

            citable_texts.append(
                referenced_counter["counterargument_text"]
            )

        errors.extend(
            check_independent_text_safety(
                suggestion_id, "grounded_explanation", grounded_explanation,
                MAX_GROUNDED_EXPLANATION_LENGTH, declared_ids,
                known_reference_ids, citable_texts,
            )
        )

    return errors


# ============================================================
# CASE ID / GENERATED AT
# ============================================================

def validate_case_id(analysis, expected_case_id):

    errors = []

    found = analysis.get("case_id")

    if found != expected_case_id:

        errors.append(
            "Argument analysis case_id uyuşmazlığı. Beklenen="
            f"{expected_case_id}, Bulunan={found}"
        )

    return errors


def validate_generated_at(analysis):

    errors = []

    if parse_iso_datetime(analysis.get("generated_at")) is None:

        errors.append(
            f"generated_at geçerli ISO date-time değil: "
            f"{analysis.get('generated_at')}"
        )

    return errors


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_argument_analysis(
    arguments_path, expected_case_id=None, raise_on_error=False
):

    arguments_path = Path(arguments_path)

    analysis = load_json(arguments_path)

    case_id = expected_case_id or analysis.get("case_id")

    if not case_id:

        raise ArgumentValidationError("case_id belirlenemedi.")

    case_data, case_path = load_case(case_id)

    issue_context = load_canonical_issues(case_id)

    issue_index = issue_context["issue_index"]

    fact_context = load_canonical_fact_index(case_id)

    fact_index = fact_context["facts"]

    (
        _evidence_candidates,
        evidence_candidate_index,
        evidence_path,
    ) = load_canonical_evidence_optional(case_id)

    (
        _researches,
        research_index,
        research_path,
    ) = load_canonical_legal_research_optional(case_id)

    (
        _decisions,
        case_law_decision_index,
        case_law_path,
    ) = load_canonical_case_law_optional(case_id)

    timeline_event_index, timeline_path = load_canonical_timeline_optional(case_id)

    _deadlines, deadline_ids, deadline_path = load_canonical_deadline_optional(
        case_id
    )

    allowlist_by_issue, _discovery_warnings = build_allowlists_for_issues(
        issue_context["issues"], fact_index, evidence_candidate_index,
        research_index, case_law_decision_index, timeline_event_index,
        deadline_ids,
    )

    errors = []

    warnings = []

    errors.extend(validate_schema(analysis))

    errors.extend(validate_case_id(analysis, case_id))

    errors.extend(validate_generated_at(analysis))

    errors.extend(
        validate_analysis_metadata(
            analysis.get("analysis_metadata"),
            issue_context["issues"],
            fact_index,
            evidence_candidate_index,
            evidence_path.exists(),
            research_index,
            research_path.exists(),
            case_law_decision_index,
            case_law_path.exists(),
            timeline_event_index,
            timeline_path.exists(),
            deadline_ids,
            deadline_path.exists(),
        )
    )

    coverage_records = analysis.get("argument_coverage", [])

    claims = analysis.get("argument_claims", [])

    counterarguments = analysis.get("argument_counterarguments", [])

    rebuttals = analysis.get("argument_rebuttals", [])

    suggestions = analysis.get("argument_agent_suggestions", [])

    if not isinstance(coverage_records, list):
        coverage_records = []

    if not isinstance(claims, list):
        claims = []

    if not isinstance(counterarguments, list):
        counterarguments = []

    if not isinstance(rebuttals, list):
        rebuttals = []

    if not isinstance(suggestions, list):
        suggestions = []

    claim_by_id = {
        c["claim_id"]: c for c in claims if isinstance(c, dict) and c.get("claim_id")
    }

    counter_by_id = {
        c["counterargument_id"]: c
        for c in counterarguments
        if isinstance(c, dict) and c.get("counterargument_id")
    }

    claim_count_by_issue = Counter(
        c.get("source_issue_id") for c in claims if isinstance(c, dict)
    )

    counter_count_by_issue = Counter(
        c.get("source_issue_id") for c in counterarguments if isinstance(c, dict)
    )

    rebuttal_count_by_issue = Counter(
        r.get("source_issue_id") for r in rebuttals if isinstance(r, dict)
    )

    suggestion_count_by_issue = Counter(
        s.get("source_issue_id") for s in suggestions if isinstance(s, dict)
    )

    known_reference_ids = (
        set(fact_index.keys())
        | set(evidence_candidate_index.keys())
        | set(research_index.keys())
        | set(case_law_decision_index.keys())
        | set(timeline_event_index.keys())
        | set(deadline_ids)
        | set(claim_by_id.keys())
        | set(counter_by_id.keys())
        | {r.get("rebuttal_id") for r in rebuttals if isinstance(r, dict)}
    )

    errors.extend(
        validate_coverage(
            coverage_records, issue_index, claim_count_by_issue,
            counter_count_by_issue, rebuttal_count_by_issue,
            suggestion_count_by_issue, allowlist_by_issue,
        )
    )

    errors.extend(
        validate_claims(
            claims, issue_index, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index, timeline_event_index,
            deadline_ids, known_reference_ids,
        )
    )

    errors.extend(
        validate_counterarguments(
            counterarguments, claim_by_id, fact_index,
            evidence_candidate_index, research_index,
            case_law_decision_index, timeline_event_index, deadline_ids,
            issue_index, known_reference_ids,
        )
    )

    errors.extend(
        validate_rebuttals(
            rebuttals, counter_by_id, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index, timeline_event_index,
            deadline_ids, issue_index, known_reference_ids,
        )
    )

    errors.extend(
        validate_agent_suggestions(
            suggestions, issue_index, claim_by_id, counter_by_id,
            known_reference_ids, fact_index, evidence_candidate_index,
            research_index, case_law_decision_index,
        )
    )

    errors = list(dict.fromkeys(errors))

    warnings = list(dict.fromkeys(warnings))

    result = {
        "valid": len(errors) == 0,
        "validator_version": ARGUMENT_VALIDATOR_VERSION,
        "arguments_path": str(arguments_path),
        "case_id": case_id,
        "case_path": str(case_path),
        "issue_count": len(issue_index),
        "coverage_count": len(coverage_records),
        "claim_count": len(claims),
        "counterargument_count": len(counterarguments),
        "rebuttal_count": len(rebuttals),
        "suggestion_count": len(suggestions),
        "errors": errors,
        "warnings": warnings,
    }

    if raise_on_error and errors:

        raise ArgumentValidationError(
            "ARGUMENT VALIDATOR V1: FAIL\n\n- " + "\n- ".join(errors)
        )

    return result


# ============================================================
# DEMO ARGUMENT ANALYSIS (SELF-TEST) - lazy import (circular)
# ============================================================

def build_demo_argument_analysis(
    case_id, use_agent=False, llm_client=None, network_allowed=False
):

    from argument_engine import build_argument_engine_output

    build_result = build_argument_engine_output(
        case_id, use_agent=use_agent, llm_client=llm_client,
        network_allowed=network_allowed,
    )

    return build_result["analysis"]


# ============================================================
# SELF TEST
# ============================================================

def run_self_test(case_id):

    from argument_agent import FakeArgumentLLMClient
    from argument_discovery import build_allowlists_for_issues

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT VALIDATOR V1")
    print("======================================")

    assert ARGUMENT_SCHEMA_PATH.exists()

    load_json(ARGUMENT_SCHEMA_PATH)

    print("T01 Argument schema load:", "PASS")

    issue_context = load_canonical_issues(case_id)

    fact_context = load_canonical_fact_index(case_id)

    print("T02 Canonical issue/fact context load:", "PASS")

    temp_dir = tempfile.TemporaryDirectory(prefix="argument_validator_selftest_")

    arguments_dir = Path(temp_dir.name)

    # ------------------------------------------------------------
    # T03 OFFLINE BASELINE
    # ------------------------------------------------------------

    demo = build_demo_argument_analysis(case_id, use_agent=False)

    assert len(demo["argument_coverage"]) == len(issue_context["issue_index"])
    assert len(demo["argument_claims"]) == 0
    assert len(demo["argument_counterarguments"]) == 0
    assert len(demo["argument_rebuttals"]) == 0
    assert len(demo["argument_agent_suggestions"]) == 0

    for coverage in demo["argument_coverage"]:

        assert coverage["execution_state"] in (
            "analysis_not_run", "blocked_missing_input",
        )

    baseline_path = arguments_dir / "argument_validator_v1_baseline.json"

    write_json(baseline_path, demo)

    baseline_result = validate_argument_analysis(baseline_path, case_id)

    if not baseline_result["valid"]:

        for error in baseline_result["errors"]:

            print("-", error)

    assert baseline_result["valid"] is True

    print("T03 Offline baseline (coverage completeness, 0/0/0/0):", "PASS")

    # ------------------------------------------------------------
    # BUILD REAL ALLOWLIST FOR GROUNDED TESTS
    # ------------------------------------------------------------

    from argument_discovery import (
        load_canonical_case_law_optional,
        load_canonical_deadline_optional,
        load_canonical_evidence_optional,
        load_canonical_legal_research_optional,
        load_canonical_timeline_optional,
    )

    _e, evidence_index, _ep = load_canonical_evidence_optional(case_id)
    _r, research_index, _rp = load_canonical_legal_research_optional(case_id)
    _d, case_law_index, _dp = load_canonical_case_law_optional(case_id)
    timeline_index, _tp = load_canonical_timeline_optional(case_id)
    _dl, deadline_ids, _dlp = load_canonical_deadline_optional(case_id)

    allowlist_by_issue, _w = build_allowlists_for_issues(
        issue_context["issues"], fact_context["facts"], evidence_index,
        research_index, case_law_index, timeline_index, deadline_ids,
    )

    grounded_issue_id = next(
        issue_id
        for issue_id, menu in allowlist_by_issue.items()
        if menu["has_minimum_grounding"]
    )

    grounded_fact_id = allowlist_by_issue[grounded_issue_id]["eligible_fact_ids"][0]

    # ------------------------------------------------------------
    # T04 GROUNDED CLAIM
    # ------------------------------------------------------------

    claim_response = json.dumps(
        [
            {
                "source_issue_id": grounded_issue_id,
                "claim_type": "factual_challenge",
                "claim_text": "Bu olgu dosyadaki fact ile örtüşmektedir.",
                "source_fact_ids": [grounded_fact_id],
                "source_evidence_candidate_ids": [],
                "source_legal_research_ids": [],
                "source_case_law_ids": [],
                "source_timeline_event_ids": [],
                "source_deadline_ids": [],
                "reason_code": "explicit_textual_match",
                "grounded_explanation": "Fact doğrudan bu iddiayı destekler.",
            }
        ],
        ensure_ascii=False,
    )

    client = FakeArgumentLLMClient(response_text=claim_response)

    demo_claim = build_demo_argument_analysis(case_id, use_agent=True, llm_client=client)

    assert len(demo_claim["argument_claims"]) == 1

    claim_path = arguments_dir / "argument_validator_v1_claim.json"

    write_json(claim_path, demo_claim)

    claim_result = validate_argument_analysis(claim_path, case_id)

    if not claim_result["valid"]:

        for error in claim_result["errors"]:

            print("-", error)

    assert claim_result["valid"] is True

    print("T04 Grounded claim accepted end-to-end:", "PASS")

    # ------------------------------------------------------------
    # T05 GHOST FACT ID REJECTED (VALIDATOR-LEVEL TAMPER)
    # ------------------------------------------------------------

    tampered = clone_json(demo_claim)

    tampered["argument_claims"][0]["source_fact_ids"] = ["fact_ghost_xxx"]

    tampered_path = arguments_dir / "argument_validator_v1_ghost_fact.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False

    print("T05 Ghost fact_id blocked (validator-level tamper):", "PASS")

    # ------------------------------------------------------------
    # T06 STALE INPUT DETECTION
    # ------------------------------------------------------------

    tampered = clone_json(demo_claim)

    tampered["analysis_metadata"]["facts_input_hash"] = "0" * 64

    tampered_path = arguments_dir / "argument_validator_v1_stale.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False
    assert any("STALE" in e for e in tampered_result["errors"])

    print("T06 Stale input_hash detection:", "PASS")

    # ------------------------------------------------------------
    # T07 COUNT MISMATCH
    # ------------------------------------------------------------

    tampered = clone_json(demo_claim)

    for coverage in tampered["argument_coverage"]:

        if coverage["source_issue_id"] == grounded_issue_id:

            coverage["claim_count"] = 999

    tampered_path = arguments_dir / "argument_validator_v1_count_mismatch.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False

    print("T07 Coverage count mismatch blocked:", "PASS")

    # ------------------------------------------------------------
    # T08 COVERAGE COMPLETENESS (missing record)
    # ------------------------------------------------------------

    tampered = clone_json(demo)

    tampered["argument_coverage"].pop()

    tampered_path = arguments_dir / "argument_validator_v1_missing_coverage.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False

    print("T08 Coverage completeness (missing record) blocked:", "PASS")

    # ------------------------------------------------------------
    # T09 ALLOWLIST_COUNT: CORRECT VALUE ACCEPTED (independently
    # recomputed via the SAME pure helper the engine uses)
    # ------------------------------------------------------------

    independent_allowlist_by_issue, _w = build_allowlists_for_issues(
        issue_context["issues"], fact_context["facts"], evidence_index,
        research_index, case_law_index, timeline_index, deadline_ids,
    )

    for coverage in demo["argument_coverage"]:

        expected = independent_allowlist_by_issue[
            coverage["source_issue_id"]
        ]["allowlist_count"]

        assert coverage["allowlist_count"] == expected

    print(
        "T09 Correct allowlist_count independently recomputed and "
        "accepted:", "PASS",
    )

    # ------------------------------------------------------------
    # T10 ALLOWLIST_COUNT: WRONG (INFLATED) VALUE BLOCKED
    # ------------------------------------------------------------

    tampered = clone_json(demo)

    tampered["argument_coverage"][0]["allowlist_count"] += 5

    tampered_path = arguments_dir / "argument_validator_v1_allowlist_wrong.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False
    assert any("allowlist_count" in e for e in tampered_result["errors"])

    print("T10 Inflated allowlist_count blocked (not trusted):", "PASS")

    # ------------------------------------------------------------
    # T11 UNRESOLVABLE FACT / REJECTED EVIDENCE EXCLUDED FROM
    # allowlist_count (direct unit test of the shared deterministic
    # helper, synthetic data only, no case_0001 mutation)
    # ------------------------------------------------------------

    synthetic_issue = {
        "issue_id": "issue_synthetic_001",
        "issue_type": "verification_gap",
        "title": "t",
        "description": "t",
        "source_fact_ids": ["fact_ghost_unresolvable", "fact_real_001"],
        "source_timeline_event_ids": [],
        "source_deadline_ids": [],
    }

    synthetic_fact_index = {
        "fact_real_001": {
            "fact": {"fact_id": "fact_real_001", "statement": "x"},
            "source_document_id": "doc_001",
        }
    }

    synthetic_evidence_index = {
        "ev_rejected": {
            "candidate_id": "ev_rejected",
            "source_issue_id": "issue_synthetic_001",
            "review_state": "rejected",
        },
        "ev_needs_review": {
            "candidate_id": "ev_needs_review",
            "source_issue_id": "issue_synthetic_001",
            "review_state": "needs_review",
        },
    }

    from argument_discovery import build_issue_allowlist

    synthetic_menu, synthetic_warnings = build_issue_allowlist(
        synthetic_issue, synthetic_fact_index, synthetic_evidence_index,
        {}, {}, {}, set(),
    )

    assert synthetic_menu["eligible_fact_ids"] == ["fact_real_001"], (
        "Unresolvable (ghost) fact_id allowlist'e dahil edilmemelidir."
    )

    assert synthetic_menu["eligible_evidence_candidate_ids"] == [
        "ev_needs_review"
    ], "Rejected evidence candidate allowlist'e dahil edilmemelidir."

    assert synthetic_menu["allowlist_count"] == 2, (
        "allowlist_count yalnız gerçekten resolve edilen/rejected "
        "olmayan kayıtları saymalıdır (1 fact + 1 needs_review "
        "evidence = 2)."
    )

    print(
        "T11 Unresolvable fact / rejected evidence excluded from "
        "allowlist_count (synthetic, isolated):", "PASS",
    )

    # ------------------------------------------------------------
    # T12 CROSS-ISSUE ALLOWLIST_COUNT SWAP REJECTED (coverage for
    # issue A carries a DIFFERENT issue's allowlist_count)
    # ------------------------------------------------------------

    issue_ids_sorted = sorted(independent_allowlist_by_issue.keys())

    issue_a, issue_b = issue_ids_sorted[0], issue_ids_sorted[1]

    count_a = independent_allowlist_by_issue[issue_a]["allowlist_count"]

    count_b = independent_allowlist_by_issue[issue_b]["allowlist_count"]

    if count_a != count_b:

        tampered = clone_json(demo)

        for coverage in tampered["argument_coverage"]:

            if coverage["source_issue_id"] == issue_a:

                coverage["allowlist_count"] = count_b

        tampered_path = (
            arguments_dir / "argument_validator_v1_allowlist_swap.json"
        )

        write_json(tampered_path, tampered)

        tampered_result = validate_argument_analysis(tampered_path, case_id)

        assert tampered_result["valid"] is False

    print(
        "T12 Cross-issue allowlist_count swap rejected (each issue's "
        "own recomputed value enforced):", "PASS",
    )

    # ------------------------------------------------------------
    # SUGGESTION FREE-TEXT SAFETY - INDEPENDENT VALIDATOR-LEVEL
    # RE-CHECK (Finding 2 remediation, defense in depth: these
    # tamper the FINALIZED analysis AFTER agent-stage acceptance,
    # so only the validator's OWN independent guard can catch them)
    # ------------------------------------------------------------

    suggestion_response = json.dumps(
        [
            {
                "source_issue_id": grounded_issue_id,
                "suggestion_type": "missing_supporting_fact",
                "source_claim_id": None,
                "source_counterargument_id": None,
                "related_reference_ids": [grounded_fact_id],
                "reason_code": "general_contextual_relevance",
                "grounded_explanation": (
                    "Bu issue icin ek destekleyici fact aranmalidir."
                ),
            }
        ],
        ensure_ascii=False,
    )

    client_with_suggestion = FakeArgumentLLMClient(
        response_sequence=["[]", "[]", "[]", suggestion_response]
    )

    demo_with_suggestion = build_demo_argument_analysis(
        case_id, use_agent=True, llm_client=client_with_suggestion,
    )

    assert len(demo_with_suggestion["argument_agent_suggestions"]) == 1

    suggestion_path = arguments_dir / "argument_validator_v1_suggestion.json"

    write_json(suggestion_path, demo_with_suggestion)

    suggestion_result = validate_argument_analysis(suggestion_path, case_id)

    if not suggestion_result["valid"]:

        for error in suggestion_result["errors"]:

            print("-", error)

    assert suggestion_result["valid"] is True

    print("T13 Safe, grounded suggestion accepted end-to-end:", "PASS")

    # ---- T14: ghost fact ID smuggled into grounded_explanation
    # (post-hoc tamper) -> validator FAIL ----

    other_fact_id_for_validator = next(
        fact_id
        for issue_id, menu in allowlist_by_issue.items()
        if issue_id != grounded_issue_id
        for fact_id in menu["eligible_fact_ids"]
        if fact_id not in allowlist_by_issue[grounded_issue_id]["eligible_fact_ids"]
    )

    tampered = clone_json(demo_with_suggestion)

    tampered["argument_agent_suggestions"][0]["grounded_explanation"] = (
        f"Bkz. {other_fact_id_for_validator} numarali kayit."
    )

    tampered_path = arguments_dir / "argument_validator_v1_suggestion_smuggle.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False

    print(
        "T14 Suggestion grounded_explanation with smuggled ghost ID "
        "blocked (independent validator-level re-check):", "PASS",
    )

    # ---- T15: fabricated date (post-hoc tamper) -> validator FAIL ----

    tampered = clone_json(demo_with_suggestion)

    tampered["argument_agent_suggestions"][0]["grounded_explanation"] = (
        "Bu olay 01.01.1999 tarihinde meydana gelmis olabilir."
    )

    tampered_path = arguments_dir / "argument_validator_v1_suggestion_date.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False

    print(
        "T15 Suggestion grounded_explanation with fabricated date "
        "blocked (independent validator-level re-check):", "PASS",
    )

    # ---- T16: unverified quote (post-hoc tamper) -> validator FAIL ----

    tampered = clone_json(demo_with_suggestion)

    tampered["argument_agent_suggestions"][0]["grounded_explanation"] = (
        'Belgede "bu tamamen uydurma bir ifade" gecmektedir.'
    )

    tampered_path = arguments_dir / "argument_validator_v1_suggestion_quote.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False

    print(
        "T16 Suggestion grounded_explanation with unverified quote "
        "blocked (independent validator-level re-check):", "PASS",
    )

    # ---- T17: forbidden certainty/outcome phrase (post-hoc tamper)
    # -> validator FAIL ----

    tampered = clone_json(demo_with_suggestion)

    tampered["argument_agent_suggestions"][0]["grounded_explanation"] = (
        "Bu konuda ek arastirma yapilmazsa dava iptal edilmelidir."
    )

    tampered_path = arguments_dir / "argument_validator_v1_suggestion_phrase.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False

    print(
        "T17 Suggestion grounded_explanation with forbidden "
        "certainty/outcome phrase blocked:", "PASS",
    )

    # ==============================================================
    # ROW 13 CORRECTIVE MAINTENANCE (CLAUDE.md §9 açık-bug istisnası)
    # ==============================================================

    # ------------------------------------------------------------
    # T18 A2: applicability_result=null FAIL-OPEN FIX (pure function
    # unit test, isolated synthetic data - case_0001'i mutasyona
    # UĞRATMAZ)
    # ------------------------------------------------------------

    for applicability_value in ("unknown", "needs_review", None):

        synthetic_case_law_index = {
            "decision_synthetic_001": {
                "decision_id": "decision_synthetic_001",
                "applicability_result": applicability_value,
            }
        }

        flag_result = compute_depends_on_unconfirmed_authority(
            {"source_case_law_ids": ["decision_synthetic_001"]},
            synthetic_case_law_index,
        )

        assert flag_result is True, (
            f"applicability_result={applicability_value!r} "
            "depends_on_unconfirmed_authority=True üretmelidir."
        )

    # Canonical decision bulunamıyorsa (ghost decision_id) mevcut
    # fail-closed davranış (False) korunmalıdır - değişmedi.
    assert compute_depends_on_unconfirmed_authority(
        {"source_case_law_ids": ["decision_ghost_xxx"]}, {}
    ) is False

    # case_0001 baseline: canonical case_law.json'da 0 decision var -
    # bu düzeltme mevcut canonical veriyi ETKİLEMEZ.
    assert len(case_law_index) == 0
    assert compute_depends_on_unconfirmed_authority(
        {"source_case_law_ids": []}, case_law_index
    ) is False

    print(
        "T18 A2 applicability_result=unknown/needs_review/null hepsi "
        "unconfirmed authority olarak işaretleniyor (fail-open "
        "düzeltildi; case_0001 0-decision baseline değişmedi):", "PASS",
    )

    # ------------------------------------------------------------
    # T19 A6: SAME-ISSUE FACT VALIDATION (independent validator-level
    # re-check - agent allowlist filtresi BYPASS edilerek doğrudan
    # validator'a verilen cross-issue tamper)
    # ------------------------------------------------------------

    tampered = clone_json(demo_claim)

    tampered["argument_claims"][0]["source_fact_ids"] = [
        other_fact_id_for_validator
    ]

    tampered_path = (
        arguments_dir / "argument_validator_v1_cross_issue_fact.json"
    )

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False
    assert any(
        "cross-issue leakage" in e for e in tampered_result["errors"]
    )

    print(
        "T19 Cross-issue real canonical fact blocked (independent "
        "validator-level same-issue check, agent-bypass tamper):",
        "PASS",
    )

    # ------------------------------------------------------------
    # C1 SETUP: SAFE CLAIM -> COUNTERARGUMENT -> REBUTTAL CHAIN
    # (end-to-end, agent-generated, tüm üç entity türü için de
    # grounded/safe metin - independent validator battery'nin
    # meşru içeriği reddetmediğini kanıtlar)
    # ------------------------------------------------------------

    counter_response = json.dumps(
        [
            {
                "source_claim_id": "argument_claim_001",
                "counter_type": "factual_denial",
                "counterargument_text": (
                    "Karsi taraf bu olgunun varligini reddetmektedir."
                ),
                "source_fact_ids": [grounded_fact_id],
                "source_evidence_candidate_ids": [],
                "source_legal_research_ids": [],
                "source_case_law_ids": [],
                "source_timeline_event_ids": [],
                "source_deadline_ids": [],
                "reason_code": "explicit_textual_match",
                "grounded_explanation": (
                    "Bu karsi iddia da ayni fact kaydina dayanmaktadir."
                ),
            }
        ],
        ensure_ascii=False,
    )

    rebuttal_response = json.dumps(
        [
            {
                "source_counterargument_id": "argument_counter_001",
                "rebuttal_type": "factual_refutation",
                "rebuttal_text": (
                    "Bu itiraz, dosyadaki fact kaydiyla dogrudan cakismaktadir."
                ),
                "source_fact_ids": [grounded_fact_id],
                "source_evidence_candidate_ids": [],
                "source_legal_research_ids": [],
                "source_case_law_ids": [],
                "source_timeline_event_ids": [],
                "source_deadline_ids": [],
                "reason_code": "explicit_textual_match",
                "grounded_explanation": (
                    "Fact kaydi bu cevabi dogrudan desteklemektedir."
                ),
            }
        ],
        ensure_ascii=False,
    )

    client_with_chain = FakeArgumentLLMClient(
        response_sequence=[
            claim_response, counter_response, rebuttal_response, "[]",
        ]
    )

    demo_chain = build_demo_argument_analysis(
        case_id, use_agent=True, llm_client=client_with_chain,
    )

    assert len(demo_chain["argument_claims"]) == 1
    assert len(demo_chain["argument_counterarguments"]) == 1
    assert len(demo_chain["argument_rebuttals"]) == 1

    chain_path = arguments_dir / "argument_validator_v1_chain.json"

    write_json(chain_path, demo_chain)

    chain_result = validate_argument_analysis(chain_path, case_id)

    if not chain_result["valid"]:

        for error in chain_result["errors"]:

            print("-", error)

    assert chain_result["valid"] is True

    print(
        "T20 Safe grounded claim/counterargument/rebuttal chain "
        "accepted end-to-end (independent battery does not "
        "over-block legitimate text):", "PASS",
    )

    # ------------------------------------------------------------
    # T21 C1: CLAIM ghost-ID smuggling in grounded_explanation ->
    # independent validator-level battery FAIL (agent-bypass tamper)
    # ------------------------------------------------------------

    tampered = clone_json(demo_chain)

    tampered["argument_claims"][0]["grounded_explanation"] = (
        f"Bkz. {other_fact_id_for_validator} numarali kayit."
    )

    tampered_path = arguments_dir / "argument_validator_v1_claim_smuggle.json"

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False
    assert any("gömülü" in e for e in tampered_result["errors"])

    print(
        "T21 Claim grounded_explanation with smuggled ghost ID "
        "blocked (independent validator-level re-check):", "PASS",
    )

    # ------------------------------------------------------------
    # T22 C1: COUNTERARGUMENT unsupported date/amount ->
    # independent validator-level battery FAIL (agent-bypass tamper)
    # ------------------------------------------------------------

    tampered = clone_json(demo_chain)

    tampered["argument_counterarguments"][0]["counterargument_text"] = (
        "Bu odeme 22.11.2030 tarihinde 500000 TL olarak yapilmistir."
    )

    tampered_path = (
        arguments_dir / "argument_validator_v1_counter_unsupported.json"
    )

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False
    assert any("unsupported" in e for e in tampered_result["errors"])

    print(
        "T22 Counterargument text with fabricated/unsupported "
        "date+amount blocked (independent validator-level re-check):",
        "PASS",
    )

    # ------------------------------------------------------------
    # T23 C1: REBUTTAL unverifiable quote -> independent
    # validator-level battery FAIL (agent-bypass tamper)
    # ------------------------------------------------------------

    tampered = clone_json(demo_chain)

    tampered["argument_rebuttals"][0]["rebuttal_text"] = (
        'Belgede "bu tamamen uydurma bir ifadedir" gecmektedir.'
    )

    tampered_path = (
        arguments_dir / "argument_validator_v1_rebuttal_quote.json"
    )

    write_json(tampered_path, tampered)

    tampered_result = validate_argument_analysis(tampered_path, case_id)

    assert tampered_result["valid"] is False
    assert any("alıntı" in e for e in tampered_result["errors"])

    print(
        "T23 Rebuttal text with unverifiable quote blocked "
        "(independent validator-level re-check):", "PASS",
    )

    print()
    print("Case:", case_id)
    print("Canonical issue count:", len(issue_context["issue_index"]))
    print()
    print("======================================")
    print(" ARGUMENT VALIDATOR V1: 23/23 PASS")
    print("======================================")

    temp_dir.cleanup()


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Argument Validator V1")

    parser.add_argument("--case", dest="case_id", default=DEFAULT_CASE_ID)

    parser.add_argument("--arguments", dest="arguments_path", default=None)

    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test or args.arguments_path is None:

        run_self_test(args.case_id)

        return

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT VALIDATOR V1")
    print("======================================")

    try:

        result = validate_argument_analysis(
            arguments_path=Path(args.arguments_path),
            expected_case_id=args.case_id,
            raise_on_error=False,
        )

    except Exception as error:

        print()
        print("VALIDATION ERROR")
        print(error)
        print()
        print("======================================")
        print(" ARGUMENT VALIDATOR V1: FAIL")
        print("======================================")
        sys.exit(1)

    print()
    print("Case:", result["case_id"])
    print("Coverage count:", result["coverage_count"])
    print("Claim count:", result["claim_count"])

    if result["errors"]:

        print()
        print("Errors:")

        for error in result["errors"]:

            print("-", error)

    print()
    print("======================================")

    if result["valid"]:

        print(" ARGUMENT VALIDATOR V1: PASS")

    else:

        print(" ARGUMENT VALIDATOR V1: FAIL")
        sys.exit(1)

    print("======================================")


if __name__ == "__main__":

    main()
