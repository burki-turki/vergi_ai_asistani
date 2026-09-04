# ============================================================
# VERGİ AI - QA ENGINE V1 (Row 16)
#
# 11 scope / 12 check_id'nin deterministik yürütücüsü. Agent
# YALNIZ ayrı, izole bir aşamada (run_agent_stage) çağrılır ve
# yalnız qa_agent_suggestions'a yazar - hiçbir deterministik
# check_result'a DOKUNAMAZ.
# ============================================================

import hashlib
import itertools
import json
from datetime import datetime
from pathlib import Path

from qa_policy import (
    QA_SCOPE_REGISTRY, QA_CHECK_REGISTRY, QA_OPTIONAL_SCOPES, QA_MULTI_FILE_SCOPES,
    CHECK_VERSION, CHECK_APPLICABLE_SCOPES, CASE_RISK_SCOPES,
    PENDING_REVIEW_SOURCE_MAP, PENDING_VALUE, EXECUTION_STATE_SOURCE_MAP,
    TEXT_SAFETY_CHECKERS, sha256_of, sha256_of_bytes,
)
from qa_discovery import (
    BASE_DIR, CASES_DIR, get_case_json_path, get_single_file_scope_path,
    get_document_path, get_facts_path, read_artifact_bytes, parse_json_bytes,
    resolve_document_membership, load_full_upstream_context, load_json_if_exists,
    build_coverage_by_issue,
)


def get_qa_dir(case_id):

    return CASES_DIR / case_id / "qa"


def get_qa_pending_path(case_id):

    return get_qa_dir(case_id) / f"qa_{case_id}_v1.json.pending"


def get_qa_canonical_path(case_id):

    return get_qa_dir(case_id) / "qa.json"


def now_iso():

    return datetime.now().astimezone().isoformat()


def next_id(counter, prefix):

    value = next(counter)

    return f"{prefix}_{value:03d}"


# ============================================================
# HAM-BAYT TARAMA - 11 scope + case.json (dependency manifest)
# ============================================================

def scan_artifact(path):

    raw_bytes, byte_state = read_artifact_bytes(path)

    if byte_state == "absent":

        return {"raw_bytes": None, "sha256": None, "json_valid": False, "parsed": None, "state": "absent"}

    if byte_state == "unreadable":

        return {"raw_bytes": None, "sha256": None, "json_valid": False, "parsed": None, "state": "unreadable"}

    parsed, is_valid = parse_json_bytes(raw_bytes)

    return {
        "raw_bytes": raw_bytes,
        "sha256": sha256_of_bytes(raw_bytes),
        "json_valid": is_valid,
        "parsed": parsed if is_valid else None,
        "state": "present_valid" if is_valid else "present_invalid",
    }


def scan_all_artifacts(case_id, document_ids):
    """
    document_ids: resolve_document_membership()'ten gelen liste, VEYA None
    (üyelik çözülemedi - bu durumda documents/facts için HİÇBİR üye
    taranmaz, yalnız case.json'un kendisi taranır - bu ZATEN ayrıca
    resolve_document_membership içinde yapılmıştır).
    """

    scans = {}

    scans["case.json"] = scan_artifact(get_case_json_path(case_id))

    for scope_id in QA_SCOPE_REGISTRY:

        if scope_id in QA_MULTI_FILE_SCOPES:

            continue

        scans[scope_id] = scan_artifact(get_single_file_scope_path(scope_id, case_id))

    if document_ids is not None:

        for document_id in document_ids:

            scans[("documents", document_id)] = scan_artifact(get_document_path(case_id, document_id))
            scans[("facts", document_id)] = scan_artifact(get_facts_path(case_id, document_id))

    return scans


def build_manifest_snapshot(scans):
    """
    (key -> {"sha256":..., "state":...}) sözlüğü - karşılaştırma için
    yalnız hash+state taşınır (ham bayt taşınmaz).
    """

    return {
        str(key): {"sha256": scan["sha256"], "state": scan["state"]}
        for key, scan in scans.items()
    }


def compare_manifests(before, after):

    changed = []

    all_keys = set(before.keys()) | set(after.keys())

    for key in sorted(all_keys):

        if before.get(key) != after.get(key):

            changed.append(key)

    return {"consistent": len(changed) == 0, "changed_refs": changed}


# ============================================================
# ORTAK KONTROL SONUCU OLUŞTURUCU
# ============================================================

class QaResultBuilder:

    def __init__(self):

        self._counter = itertools.count(1)
        self.results = []

    def add(self, check_id, scope_id, qa_result, evidence, reason_code,
            member_id=None, related_issue_id=None, path=None, sha256_at_scan=None):

        result_id = next_id(self._counter, "qa_check_result")

        self.results.append({
            "check_result_id": result_id,
            "check_id": check_id,
            "check_version": CHECK_VERSION,
            "scope_id": scope_id,
            "member_id": member_id,
            "related_issue_id": related_issue_id,
            "qa_result": qa_result,
            "evidence": evidence,
            "reason_code": reason_code,
            "artifact_locator": {
                "scope_id": scope_id,
                "path": str(path) if path is not None else None,
                "raw_byte_sha256_at_scan": sha256_at_scan,
            },
        })

        return result_id


# ============================================================
# #1 / #2 / #3 - artifact_presence / raw_byte_readability / json_validity
# ============================================================

def artifact_state_of(scan):

    if scan["state"] == "absent":

        return "absent"

    if scan["state"] == "unreadable":

        return "unreadable"

    return scan["state"]  # "present_valid" | "present_invalid"


def run_presence_readability_validity_checks(builder, case_id, scans, document_ids):

    for scope_id in QA_SCOPE_REGISTRY:

        required = scope_id not in QA_OPTIONAL_SCOPES

        if scope_id in QA_MULTI_FILE_SCOPES:

            if document_ids is None:

                continue  # üyelik çözülemedi - #1/#2/#3'ün document_member instance'ları hiç üretilmez

            for document_id in document_ids:

                scan = scans[(scope_id, document_id)]
                path = get_document_path(case_id, document_id) if scope_id == "documents" else get_facts_path(case_id, document_id)

                _emit_1_2_3(builder, scope_id, scan, required=True, member_id=document_id, path=path)

            continue

        scan = scans[scope_id]
        path = get_single_file_scope_path(scope_id, case_id)

        _emit_1_2_3(builder, scope_id, scan, required=required, member_id=None, path=path)


def _emit_1_2_3(builder, scope_id, scan, required, member_id, path):

    absent = scan["state"] == "absent"

    if absent:

        presence_result = "passed" if not required else "failed"
        presence_reason = "artifact_absent_optional" if not required else "artifact_absent_required"

    else:

        presence_result = "passed"
        presence_reason = "artifact_present"

    builder.add(
        "artifact_presence", scope_id, presence_result,
        {"artifact_state": scan["state"], "required": required},
        presence_reason, member_id=member_id, path=path, sha256_at_scan=scan["sha256"],
    )

    if absent:

        builder.add(
            "raw_byte_readability", scope_id, "blocked",
            {"reason": "artifact_absent"}, "prerequisite_unmet",
            member_id=member_id, path=path,
        )
        builder.add(
            "json_validity", scope_id, "blocked",
            {"reason": "artifact_absent"}, "prerequisite_unmet",
            member_id=member_id, path=path,
        )

        return

    if scan["state"] == "unreadable":

        builder.add(
            "raw_byte_readability", scope_id, "failed",
            {"reason": "os_level_read_error"}, "artifact_unreadable",
            member_id=member_id, path=path,
        )
        builder.add(
            "json_validity", scope_id, "blocked",
            {"reason": "raw_byte_readability_failed"}, "prerequisite_unmet",
            member_id=member_id, path=path,
        )

        return

    builder.add(
        "raw_byte_readability", scope_id, "passed",
        {}, "artifact_readable", member_id=member_id, path=path, sha256_at_scan=scan["sha256"],
    )

    json_ok = scan["json_valid"]

    builder.add(
        "json_validity", scope_id, "passed" if json_ok else "failed",
        {} if json_ok else {"reason": "json_or_utf8_invalid"},
        "json_valid" if json_ok else "malformed_json",
        member_id=member_id, path=path, sha256_at_scan=scan["sha256"],
    )


# ============================================================
# #4 - document_membership_enumerable (scope-level, yalnız 'documents')
# ============================================================

def run_membership_check(builder, membership):

    if membership["state"] == "resolved":

        builder.add(
            "document_membership_enumerable", "documents", "passed",
            {"document_ids": membership["document_ids"]}, "membership_resolved",
        )

        return

    if membership["state"] == "blocked":

        builder.add(
            "document_membership_enumerable", "documents", "blocked",
            {"reason": membership["reason"]}, "prerequisite_unmet",
        )

        return

    builder.add(
        "document_membership_enumerable", "documents", "failed",
        {"reason": membership["reason"]}, "membership_unresolvable",
    )


# ============================================================
# #5 - document_metadata_present_and_valid (scope-level)
# ============================================================

def run_document_metadata_check(builder, case_id, membership):

    if membership["state"] != "resolved":

        builder.add(
            "document_metadata_present_and_valid", "documents", "blocked",
            {"reason": "document_membership_enumerable_not_passed"}, "prerequisite_unmet",
        )

        return

    from case_document_validator import validate_case_documents

    case_dir = CASES_DIR / case_id

    try:

        result = validate_case_documents(case_dir=case_dir, raise_on_error=False)

    except Exception as error:  # noqa: BLE001 - checker'ın kendi arızası, scan'i ÇÖKERTMEZ

        builder.add(
            "document_metadata_present_and_valid", "documents", "error",
            {"error_class": type(error).__name__, "error_message": str(error)},
            "checker_runtime_error",
        )

        return

    builder.add(
        "document_metadata_present_and_valid", "documents",
        "passed" if result.get("valid") else "failed",
        {"errors": result.get("errors", [])}, "row_validator_result",
    )


# ============================================================
# #6 - fact_extraction_present_and_valid (document_member-level)
# ============================================================

def run_fact_extraction_checks(builder, case_id, membership, scans):

    if membership["state"] != "resolved":

        return  # instance uzayı tanımsız - hiçbir member üretilmez

    from case_fact_validator import validate_fact_extraction

    for document_id in membership["document_ids"]:

        facts_scan = scans[("facts", document_id)]
        facts_path = get_facts_path(case_id, document_id)

        if facts_scan["state"] == "absent":

            builder.add(
                "fact_extraction_present_and_valid", "facts", "blocked",
                {"reason": "facts_json_absent"}, "prerequisite_unmet",
                member_id=document_id, path=facts_path,
            )

            continue

        if facts_scan["state"] in ("unreadable", "present_invalid"):

            builder.add(
                "fact_extraction_present_and_valid", "facts", "blocked",
                {"reason": facts_scan["state"]}, "prerequisite_unmet",
                member_id=document_id, path=facts_path, sha256_at_scan=facts_scan["sha256"],
            )

            continue

        try:

            result = validate_fact_extraction(facts_path=facts_path, raise_on_error=False)

        except Exception as error:  # noqa: BLE001

            builder.add(
                "fact_extraction_present_and_valid", "facts", "error",
                {"error_class": type(error).__name__, "error_message": str(error)},
                "checker_runtime_error", member_id=document_id, path=facts_path,
                sha256_at_scan=facts_scan["sha256"],
            )

            continue

        builder.add(
            "fact_extraction_present_and_valid", "facts",
            "passed" if result.get("valid") else "failed",
            {"errors": result.get("errors", [])}, "row_validator_result",
            member_id=document_id, path=facts_path, sha256_at_scan=facts_scan["sha256"],
        )


# ============================================================
# #7 - row_schema_and_reference_validity (9 tek-dosyalı scope)
# ============================================================

def run_row_schema_validity_checks(builder, case_id, scans):

    from timeline_validator import validate_timeline
    from deadline_validator import validate_deadline_analysis
    from issue_spotting_validator import validate_issue_analysis
    from legal_research_validator import validate_research_analysis
    from case_law_validator import validate_case_law_analysis
    from evidence_validator import validate_evidence_analysis
    from argument_validator import validate_argument_analysis
    from risk_strategy_validator import validate_risk_strategy_analysis
    from drafting_validator import validate_drafting_analysis

    callables = {
        "timeline": validate_timeline,
        "deadline": validate_deadline_analysis,
        "issues": validate_issue_analysis,
        "legal_research": validate_research_analysis,
        "case_law": validate_case_law_analysis,
        "evidence": validate_evidence_analysis,
        "arguments": validate_argument_analysis,
        "risk_strategy": validate_risk_strategy_analysis,
        "drafting": validate_drafting_analysis,
    }

    for scope_id in CHECK_APPLICABLE_SCOPES["row_schema_and_reference_validity"]:

        scan = scans[scope_id]
        path = get_single_file_scope_path(scope_id, case_id)

        if scan["state"] != "present_valid":

            builder.add(
                "row_schema_and_reference_validity", scope_id, "blocked",
                {"reason": f"json_validity={scan['state']}"}, "prerequisite_unmet",
                path=path, sha256_at_scan=scan["sha256"],
            )

            continue

        try:

            result = callables[scope_id](path, expected_case_id=case_id, raise_on_error=False)

        except Exception as error:  # noqa: BLE001

            builder.add(
                "row_schema_and_reference_validity", scope_id, "error",
                {"error_class": type(error).__name__, "error_message": str(error)},
                "checker_runtime_error", path=path, sha256_at_scan=scan["sha256"],
            )

            continue

        builder.add(
            "row_schema_and_reference_validity", scope_id,
            "passed" if result.get("valid") else "failed",
            {"errors": result.get("errors", [])}, "row_validator_result",
            path=path, sha256_at_scan=scan["sha256"],
        )


# ============================================================
# #8 - stale_input_hash_consistency (absence-aware, per-input,
# HER satırın KENDİ doğrulanmış formülü - hiçbiri ORTAK bir
# formülle DEĞİŞTİRİLMEDİ; her yorum satırı doğrulama kaynağını gösterir)
# ============================================================

def _documents_hash_drafting_style(ctx):
    # drafting_validator.py / risk_strategy_validator.py: sorted(items)
    adi = ctx["active_documents_index"]
    return (sha256_of(sorted(adi.items())) if adi else None, True)


def _documents_hash_evidence_style(ctx):
    # evidence_validator.py:438-441: RAW dict, sorted() DEĞİL
    return (sha256_of(ctx["active_documents_index"]), True)


def build_stale_hash_formulas():

    def issues_full(ctx):
        return (sha256_of(ctx["issues"]), True)

    def facts_std(ctx):
        return (sha256_of({fid: rec["fact"] for fid, rec in ctx["fact_index"].items()}), True)

    def timeline_full(ctx):
        return (sha256_of(ctx["timeline_event_index"]) if ctx["timeline_path"].exists() else None, ctx["timeline_path"].exists())

    def deadline_full_records(ctx):
        return (sha256_of(ctx["deadlines"]) if ctx["deadline_path"].exists() else None, ctx["deadline_path"].exists())

    def deadline_ids_only(ctx):
        return (sha256_of(sorted(ctx["deadline_ids"])) if ctx["deadline_path"].exists() else None, ctx["deadline_path"].exists())

    def legal_research_raw(ctx):
        return (sha256_of(ctx["research_index"]) if ctx["research_path"].exists() else None, ctx["research_path"].exists())

    def case_law_raw(ctx):
        return (sha256_of(ctx["case_law_decision_index"]) if ctx["case_law_path"].exists() else None, ctx["case_law_path"].exists())

    def case_law_with_coverage(ctx):
        exists = ctx["case_law_path"].exists()
        value = sha256_of({"decisions": ctx["case_law_decision_index"], "coverage": ctx["case_law_coverage_by_issue"]}) if exists else None
        return (value, exists)

    def evidence_raw(ctx):
        return (sha256_of(ctx["evidence_candidate_index"]) if ctx["evidence_path"].exists() else None, ctx["evidence_path"].exists())

    def evidence_with_coverage(ctx):
        exists = ctx["evidence_path"].exists()
        value = sha256_of({"candidates": ctx["evidence_candidate_index"], "coverage": ctx["evidence_coverage_by_issue"]}) if exists else None
        return (value, exists)

    def arguments_raw(ctx):
        exists = ctx["arguments_path"].exists()
        value = sha256_of({
            "claims": ctx["claim_index"], "counters": ctx["counter_index"], "rebuttals": ctx["rebuttal_index"],
        }) if exists else None
        return (value, exists)

    def arguments_with_coverage(ctx):
        exists = ctx["arguments_path"].exists()
        value = sha256_of({
            "claims": ctx["claim_index"], "counters": ctx["counter_index"], "rebuttals": ctx["rebuttal_index"],
            "coverage": ctx["argument_coverage_by_issue"],
        }) if exists else None
        return (value, exists)

    def risk_strategy_raw(ctx):
        exists = ctx["risk_strategy_path"].exists()
        value = sha256_of({"risks": ctx["risk_index"], "strategies": ctx["strategy_index"]}) if exists else None
        return (value, exists)

    return {
        # evidence_validator.py:421-441 - yalnız 3 alan
        "evidence": {
            "issues_input_hash": issues_full,
            "facts_input_hash": facts_std,
            "documents_input_hash": _documents_hash_evidence_style,
        },
        # argument_validator.py:361-410 - documents YOK, deadline=ID-only
        "arguments": {
            "issues_input_hash": issues_full,
            "facts_input_hash": facts_std,
            "evidence_input_hash": evidence_raw,
            "legal_research_input_hash": legal_research_raw,
            "case_law_input_hash": case_law_raw,
            "timeline_input_hash": timeline_full,
            "deadline_input_hash": deadline_ids_only,
        },
        # risk_strategy_validator.py:1100-1141
        "risk_strategy": {
            "issues_input_hash": issues_full,
            "facts_input_hash": facts_std,
            "documents_input_hash": _documents_hash_drafting_style,
            "timeline_input_hash": timeline_full,
            "deadline_input_hash": deadline_full_records,
            "legal_research_input_hash": legal_research_raw,
            "case_law_input_hash": case_law_with_coverage,
            "evidence_input_hash": evidence_with_coverage,
            "arguments_input_hash": arguments_with_coverage,
        },
        # drafting_validator.py:821-865 (Row 15 turlarında birebir doğrulandı)
        "drafting": {
            "issues_input_hash": issues_full,
            "facts_input_hash": facts_std,
            "documents_input_hash": _documents_hash_drafting_style,
            "timeline_input_hash": timeline_full,
            "deadline_input_hash": deadline_full_records,
            "legal_research_input_hash": legal_research_raw,
            "case_law_input_hash": case_law_raw,
            "evidence_input_hash": evidence_raw,
            "arguments_input_hash": arguments_raw,
            "risk_strategy_input_hash": risk_strategy_raw,
        },
    }


STALE_HASH_FORMULAS = build_stale_hash_formulas()


def run_stale_input_hash_checks(builder, scans, ctx):

    for scope_id in CHECK_APPLICABLE_SCOPES["stale_input_hash_consistency"]:

        scan = scans[scope_id]

        if scan["state"] != "present_valid":

            builder.add(
                "stale_input_hash_consistency", scope_id, "blocked",
                {"reason": f"downstream json_validity={scan['state']}"}, "prerequisite_unmet",
                sha256_at_scan=scan["sha256"],
            )

            continue

        recorded_meta = (scan["parsed"] or {}).get("analysis_metadata")

        if not isinstance(recorded_meta, dict):

            builder.add(
                "stale_input_hash_consistency", scope_id, "blocked",
                {"reason": "analysis_metadata_missing_or_invalid"}, "prerequisite_unmet",
                sha256_at_scan=scan["sha256"],
            )

            continue

        per_input = {}
        worst = "passed"

        for field_name, formula in STALE_HASH_FORMULAS[scope_id].items():

            current_value, upstream_exists = formula(ctx)
            recorded_value = recorded_meta.get(field_name)

            if not upstream_exists:

                if recorded_value is None:

                    outcome = "passed"

                else:

                    outcome = "failed"

            else:

                if current_value is not None and recorded_value == current_value:

                    outcome = "passed"

                else:

                    outcome = "failed"

            per_input[field_name] = {
                "recorded": recorded_value, "current": current_value,
                "upstream_exists": upstream_exists, "outcome": outcome,
            }

            if outcome == "failed":

                worst = "failed"

            elif outcome == "blocked" and worst != "failed":

                worst = "blocked"

        builder.add(
            "stale_input_hash_consistency", scope_id, worst,
            {"per_input_results": per_input}, "hash_comparison_result",
            sha256_at_scan=scan["sha256"],
        )


# ============================================================
# #9 - coverage_completeness_and_1to1
# ============================================================

COVERAGE_ARRAY_FIELD = {
    "case_law": "case_law_coverage",
    "evidence": "evidence_coverage",
    "arguments": "argument_coverage",
    "drafting": "draft_coverage",
}


def run_coverage_completeness_checks(builder, scans, ctx):

    issue_ids = {issue["issue_id"] for issue in ctx["issues"]}

    for scope_id in CHECK_APPLICABLE_SCOPES["coverage_completeness_and_1to1"]:

        scan = scans[scope_id]

        if scan["state"] != "present_valid":

            builder.add(
                "coverage_completeness_and_1to1", scope_id, "blocked",
                {"reason": f"json_validity={scan['state']}"}, "prerequisite_unmet",
                sha256_at_scan=scan["sha256"],
            )

            continue

        data = scan["parsed"] or {}

        if scope_id == "risk_strategy":

            risk_coverage_ids = {r.get("source_issue_id") for r in data.get("risk_coverage", []) if isinstance(r, dict)}
            case_scope_ids = {r.get("source_case_scope") for r in data.get("case_scope_coverage", []) if isinstance(r, dict)}

            risk_ok = risk_coverage_ids == issue_ids
            case_scope_ok = case_scope_ids == set(CASE_RISK_SCOPES)

            evidence = {
                "risk_coverage_comparison": {
                    "expected": sorted(issue_ids), "actual": sorted(risk_coverage_ids), "match": risk_ok,
                },
                "case_scope_coverage_comparison": {
                    "expected": sorted(CASE_RISK_SCOPES), "actual": sorted(case_scope_ids), "match": case_scope_ok,
                },
            }

            builder.add(
                "coverage_completeness_and_1to1", scope_id,
                "passed" if (risk_ok and case_scope_ok) else "failed",
                evidence, "coverage_1to1_result", sha256_at_scan=scan["sha256"],
            )

            continue

        array_field = COVERAGE_ARRAY_FIELD[scope_id]
        actual_ids = {r.get("source_issue_id") for r in data.get(array_field, []) if isinstance(r, dict)}
        match = actual_ids == issue_ids

        builder.add(
            "coverage_completeness_and_1to1", scope_id,
            "passed" if match else "failed",
            {"expected": sorted(issue_ids), "actual": sorted(actual_ids), "match": match},
            "coverage_1to1_result", sha256_at_scan=scan["sha256"],
        )


# ============================================================
# #10 - coverage_execution_state_accounted_for
# ============================================================

def _distribution(records, field_name):

    dist = {}

    for record in records:

        if not isinstance(record, dict):

            continue

        value = record.get(field_name)
        dist[value] = dist.get(value, 0) + 1

    return dist


def run_execution_state_checks(builder, scans):

    for scope_id in CHECK_APPLICABLE_SCOPES["coverage_execution_state_accounted_for"]:

        scan = scans[scope_id]

        if scan["state"] != "present_valid":

            builder.add(
                "coverage_execution_state_accounted_for", scope_id, "blocked",
                {"reason": f"json_validity={scan['state']}"}, "prerequisite_unmet",
                sha256_at_scan=scan["sha256"],
            )

            continue

        data = scan["parsed"] or {}

        if scope_id == "risk_strategy":

            risk_dist = _distribution(data.get("risk_coverage", []), "risk_execution_state")
            strategy_dist = _distribution(data.get("risk_coverage", []), "strategy_execution_state")
            case_scope_dist = _distribution(data.get("case_scope_coverage", []), "execution_state")

            builder.add(
                "coverage_execution_state_accounted_for", scope_id, "passed",
                {
                    "risk_execution_state_distribution": risk_dist,
                    "strategy_execution_state_distribution": strategy_dist,
                    "case_scope_execution_state_distribution": case_scope_dist,
                },
                "state_distribution_recorded", sha256_at_scan=scan["sha256"],
            )

            continue

        array_field, field_name, _ = EXECUTION_STATE_SOURCE_MAP[scope_id]
        dist = _distribution(data.get(array_field, []), field_name)

        builder.add(
            "coverage_execution_state_accounted_for", scope_id, "passed",
            {f"{field_name}_distribution": dist}, "state_distribution_recorded",
            sha256_at_scan=scan["sha256"],
        )


# ============================================================
# #11 - pending_human_review_backlog_count
# ============================================================

from qa_policy import PENDING_REVIEW_SOURCE_MAP as _PRSM  # re-export alias for clarity


def run_pending_review_backlog_checks(builder, scans):

    for scope_id in CHECK_APPLICABLE_SCOPES["pending_human_review_backlog_count"]:

        if scope_id == "case_law":

            builder.add(
                "pending_human_review_backlog_count", scope_id, "not_applicable",
                {"reason": "case_law schema requires_human_review=const true taşır, ama needs_review-style bir lifecycle alanı YOK"},
                "no_review_lifecycle_field_in_schema",
            )

            continue

        scan = scans[scope_id]

        if scan["state"] != "present_valid":

            builder.add(
                "pending_human_review_backlog_count", scope_id, "blocked",
                {"reason": f"json_validity={scan['state']}"}, "prerequisite_unmet",
                sha256_at_scan=scan["sha256"],
            )

            continue

        data = scan["parsed"] or {}
        per_entity_counts = {}

        for array_field, field_name in PENDING_REVIEW_SOURCE_MAP[scope_id]:

            count = sum(
                1 for r in data.get(array_field, [])
                if isinstance(r, dict) and r.get(field_name) == PENDING_VALUE
            )
            per_entity_counts[f"{array_field}.{field_name}"] = count

        builder.add(
            "pending_human_review_backlog_count", scope_id, "passed",
            {"per_entity_counts": per_entity_counts}, "count_computed",
            sha256_at_scan=scan["sha256"],
        )


# ============================================================
# #12 - forbidden_phrase_and_outcome_guarantee_absence
# ============================================================

FREE_TEXT_SOURCE_MAP = {
    "drafting": (("draft_sections", "section_id", "section_text"), ("draft_agent_suggestions", "suggestion_id", "grounded_explanation")),
    "risk_strategy": (
        ("risk_candidates", "risk_id", "risk_description"),
        ("strategy_candidates", "strategy_id", "strategy_description"),
        ("risk_strategy_agent_suggestions", "suggestion_id", "grounded_explanation"),
    ),
    "arguments": (
        ("argument_claims", "claim_id", "claim_text"),
        ("argument_counterarguments", "counterargument_id", "counterargument_text"),
        ("argument_rebuttals", "rebuttal_id", "rebuttal_text"),
        ("argument_agent_suggestions", "suggestion_id", "grounded_explanation"),
    ),
}


def run_forbidden_phrase_checks(builder, scans):

    for scope_id in CHECK_APPLICABLE_SCOPES["forbidden_phrase_and_outcome_guarantee_absence"]:

        scan = scans[scope_id]

        if scan["state"] != "present_valid":

            builder.add(
                "forbidden_phrase_and_outcome_guarantee_absence", scope_id, "blocked",
                {"reason": f"json_validity={scan['state']}"}, "prerequisite_unmet",
                sha256_at_scan=scan["sha256"],
            )

            continue

        data = scan["parsed"] or {}
        checker = TEXT_SAFETY_CHECKERS[scope_id]
        per_entity_findings = []
        total_entities = 0

        for array_field, id_field, text_field in FREE_TEXT_SOURCE_MAP[scope_id]:

            for record in data.get(array_field, []):

                if not isinstance(record, dict):

                    continue

                text = record.get(text_field)

                if not isinstance(text, str) or not text.strip():

                    continue

                total_entities += 1
                entity_id = record.get(id_field, "?")

                if scope_id == "drafting":

                    errors = checker(entity_id, text, "facts_summary", False)

                else:

                    errors = checker(entity_id, text)

                if errors:

                    per_entity_findings.append({"entity_id": entity_id, "field": text_field, "errors": errors})

        if total_entities == 0:

            builder.add(
                "forbidden_phrase_and_outcome_guarantee_absence", scope_id, "not_applicable",
                {"reason": "no_free_text_entities_present"}, "no_applicable_entities",
                sha256_at_scan=scan["sha256"],
            )

            continue

        builder.add(
            "forbidden_phrase_and_outcome_guarantee_absence", scope_id,
            "passed" if not per_entity_findings else "failed",
            {"entities_checked": total_entities, "per_entity_findings": per_entity_findings},
            "text_safety_result", sha256_at_scan=scan["sha256"],
        )


# ============================================================
# ANA ORKESTRASYON
# ============================================================

def build_qa_engine_output(case_id):

    scan_started_at = now_iso()

    membership_pre_1 = resolve_document_membership(case_id)
    membership_pre_2 = resolve_document_membership(case_id)

    pre_scan_consistent = membership_pre_1.get("document_ids") == membership_pre_2.get("document_ids")

    membership = membership_pre_2
    document_ids = membership["document_ids"] if membership["state"] == "resolved" else None

    scans_start = scan_all_artifacts(case_id, document_ids)
    manifest_start = build_manifest_snapshot(scans_start)

    builder = QaResultBuilder()
    warnings = []

    run_presence_readability_validity_checks(builder, case_id, scans_start, document_ids)
    run_membership_check(builder, membership)
    run_document_metadata_check(builder, case_id, membership)
    run_fact_extraction_checks(builder, case_id, membership, scans_start)
    run_row_schema_validity_checks(builder, case_id, scans_start)

    ctx = load_full_upstream_context(case_id)

    run_stale_input_hash_checks(builder, scans_start, ctx)
    run_coverage_completeness_checks(builder, scans_start, ctx)
    run_execution_state_checks(builder, scans_start)
    run_pending_review_backlog_checks(builder, scans_start)
    run_forbidden_phrase_checks(builder, scans_start)

    scan_completed_at_probe = now_iso()

    membership_post = resolve_document_membership(case_id)
    document_ids_post = membership_post["document_ids"] if membership_post["state"] == "resolved" else None
    scans_end = scan_all_artifacts(case_id, document_ids_post if document_ids_post is not None else document_ids)
    manifest_end = build_manifest_snapshot(scans_end)

    post_scan_comparison = compare_manifests(manifest_start, manifest_end)

    aborted = not post_scan_comparison["consistent"]

    if aborted:

        warnings.append(
            f"Tarama sırasında kaynak değişimi tespit edildi: {post_scan_comparison['changed_refs']}"
        )

    error_count = sum(1 for r in builder.results if r["qa_result"] == "error")

    if aborted:

        qa_generation_status = "aborted_source_changed"

    elif error_count > 0:

        qa_generation_status = "completed_with_errors"

    else:

        qa_generation_status = "completed"

    coverage = []

    for scope_id in QA_SCOPE_REGISTRY:

        required = scope_id not in QA_OPTIONAL_SCOPES

        if scope_id in QA_MULTI_FILE_SCOPES:

            if membership["state"] != "resolved":

                coverage.append({
                    "scope_id": scope_id, "artifact_state": "absent" if membership["state"] == "blocked" else "present_invalid",
                    "required": required, "member_enumeration_state": "unresolvable",
                    "expected_member_count": None,
                })

            else:

                overall_state = "present_valid"

                for document_id in membership["document_ids"]:

                    m_scan = scans_start[(scope_id, document_id)]

                    if artifact_state_of(m_scan) != "present_valid":

                        overall_state = "present_invalid"

                        break

                coverage.append({
                    "scope_id": scope_id, "artifact_state": overall_state,
                    "required": required, "member_enumeration_state": "resolved",
                    "expected_member_count": len(membership["document_ids"]),
                })

            continue

        scan = scans_start[scope_id]

        coverage.append({
            "scope_id": scope_id, "artifact_state": artifact_state_of(scan),
            "required": required, "member_enumeration_state": "not_applicable_single_file",
            "expected_member_count": None,
        })

    dependency_manifest = []

    for key, scan in scans_start.items():

        ref = key if isinstance(key, str) else f"{key[0]}:{key[1]}"

        dependency_manifest.append({
            "artifact_ref": ref, "raw_byte_sha256": scan["sha256"],
            "artifact_state": artifact_state_of(scan), "is_membership_source": ref == "case.json",
        })

    analysis = {
        "schema_version": 1,
        "qa_analysis_id": f"qa_{case_id}_v1",
        "case_id": case_id,
        "qa_generation_status": qa_generation_status,
        "qa_agent_execution_status": "not_requested",
        "generated_at": now_iso(),
        "analysis_metadata": {
            "dependency_manifest": dependency_manifest,
            "check_registry_version": "1",
            "scan_started_at": scan_started_at,
            "scan_completed_at": scan_completed_at_probe,
            "pre_scan_manifest_comparison": {
                "consistent": pre_scan_consistent,
                "changed_refs": [] if pre_scan_consistent else ["documents (membership)"],
            },
            "post_scan_manifest_comparison": post_scan_comparison,
        },
        "qa_coverage": coverage,
        "qa_check_results": builder.results,
        "qa_agent_suggestions": [],
        "warnings": warnings,
        "notes": [
            "legal_research ve case_law icin KENDI uretim zamanindaki girdi tazeligi dogrulanamaz "
            "(bu iki semada analysis_metadata yok); yalniz GUNCEL iceriklerinin sonraki satirlarca "
            "dogru hash'lendigi dogrulanabilir.",
        ],
    }

    return analysis


# ============================================================
# SELF TEST
# ============================================================

def snapshot_real_qa_tree(case_id):

    real_dir = get_qa_dir(case_id)

    if not real_dir.exists():

        return {"dir_exists": False, "files": {}, "subdirs": []}

    files = {}

    for path in sorted(real_dir.rglob("*")):

        if path.is_file():

            files[str(path.relative_to(real_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()

    subdirs = sorted(str(path.relative_to(real_dir)) for path in real_dir.rglob("*") if path.is_dir())

    return {"dir_exists": True, "files": files, "subdirs": subdirs}


def assert_real_qa_tree_unchanged(case_id, before, label):

    after = snapshot_real_qa_tree(case_id)

    assert after == before, f"{label}: gerçek qa/ ağacı DEĞİŞTİ.\nÖnce: {before}\nSonra: {after}"


def run_self_test():

    import tempfile

    print()
    print("======================================")
    print(" VERGİ AI - QA ENGINE V1")
    print("======================================")

    case_id = "case_0001"

    real_tree_before = snapshot_real_qa_tree(case_id)

    # ---- T01: gerçek case_0001 üzerinde tam koşu (11 scope / 12 check_id) ----

    result = build_qa_engine_output(case_id)

    assert result["qa_generation_status"] == "completed"
    assert len(result["qa_coverage"]) == 11
    assert {c["scope_id"] for c in result["qa_coverage"]} == set(QA_SCOPE_REGISTRY)

    print("T01 Gerçek case_0001 üzerinde tam koşu - 11/11 scope, generation_status=completed:", "PASS")

    # ---- T02: #9/#10 risk_strategy'nin İKİ ayrı ekseni AYRI raporlanıyor ----

    rs_completeness = [
        r for r in result["qa_check_results"]
        if r["check_id"] == "coverage_completeness_and_1to1" and r["scope_id"] == "risk_strategy"
    ]
    assert len(rs_completeness) == 1
    assert "risk_coverage_comparison" in rs_completeness[0]["evidence"]
    assert "case_scope_coverage_comparison" in rs_completeness[0]["evidence"]

    rs_state = [
        r for r in result["qa_check_results"]
        if r["check_id"] == "coverage_execution_state_accounted_for" and r["scope_id"] == "risk_strategy"
    ]
    assert len(rs_state) == 1
    ev = rs_state[0]["evidence"]
    assert "risk_execution_state_distribution" in ev
    assert "strategy_execution_state_distribution" in ev
    assert "case_scope_execution_state_distribution" in ev

    print("T02 risk_strategy #9/#10 - risk/strategy/case_scope eksenleri AYRI raporlanıyor:", "PASS")

    # ---- T03: #11 case_law -> not_applicable, gerekçeli ----

    case_law_backlog = [
        r for r in result["qa_check_results"]
        if r["check_id"] == "pending_human_review_backlog_count" and r["scope_id"] == "case_law"
    ]
    assert len(case_law_backlog) == 1
    assert case_law_backlog[0]["qa_result"] == "not_applicable"
    assert case_law_backlog[0]["reason_code"] == "no_review_lifecycle_field_in_schema"

    print("T03 case_law #11 -> not_applicable (no_review_lifecycle_field_in_schema):", "PASS")

    # ---- T04: evidence.json YOK -> blocked zinciri (fabricated değil) ----

    evidence_checks = [r for r in result["qa_check_results"] if r["scope_id"] == "evidence"]
    non_presence = [r for r in evidence_checks if r["check_id"] != "artifact_presence"]

    assert all(r["qa_result"] == "blocked" for r in non_presence), \
        "evidence yokken bağımlı check'lerin TÜMÜ blocked olmalı."

    presence = [r for r in evidence_checks if r["check_id"] == "artifact_presence"][0]
    assert presence["qa_result"] == "passed" and presence["evidence"]["required"] is False

    print("T04 evidence.json yokluğu doğru sınıflandırıldı (absent+optional=passed, bağımlılar=blocked):", "PASS")

    # ---- T05: scan_artifact - senkron sentetik dosya senaryoları ----

    with tempfile.TemporaryDirectory(prefix="qa_engine_selftest_") as td:

        valid_path = Path(td) / "valid.json"
        valid_path.write_text('{"a": 1}', encoding="utf-8")

        malformed_path = Path(td) / "malformed.json"
        malformed_path.write_bytes(b"{not valid json")

        absent_path = Path(td) / "does_not_exist.json"

        v = scan_artifact(valid_path)
        assert v["state"] == "present_valid" and v["parsed"] == {"a": 1}

        m = scan_artifact(malformed_path)
        assert m["state"] == "present_invalid" and m["parsed"] is None

        a = scan_artifact(absent_path)
        assert a["state"] == "absent" and a["sha256"] is None

        print("T05 scan_artifact: valid/malformed/absent senaryoları doğru sınıflandırıldı:", "PASS")

        # ---- T06: _emit_1_2_3 - malformed JSON -> #3 failed, bağımlı YOK ----

        builder = QaResultBuilder()

        _emit_1_2_3(builder, "timeline", m, required=True, member_id=None, path=malformed_path)

        by_check = {r["check_id"]: r for r in builder.results}

        assert by_check["artifact_presence"]["qa_result"] == "passed"
        assert by_check["raw_byte_readability"]["qa_result"] == "passed"
        assert by_check["json_validity"]["qa_result"] == "failed"
        assert by_check["json_validity"]["reason_code"] == "malformed_json"

        print("T06 Okunabilir-ama-bozuk JSON: json_validity=failed (checker hatası DEĞİL):", "PASS")

        # ---- T07: _emit_1_2_3 - absent+required -> presence=failed, bağımlılar=blocked ----

        builder2 = QaResultBuilder()

        _emit_1_2_3(builder2, "issues", a, required=True, member_id=None, path=absent_path)

        by_check2 = {r["check_id"]: r for r in builder2.results}

        assert by_check2["artifact_presence"]["qa_result"] == "failed"
        assert by_check2["artifact_presence"]["reason_code"] == "artifact_absent_required"
        assert by_check2["raw_byte_readability"]["qa_result"] == "blocked"
        assert by_check2["json_validity"]["qa_result"] == "blocked"

        print("T07 Eksik ZORUNLU artefakt: presence=failed, bağımlı check'ler=blocked:", "PASS")

    # ---- T08: resolve_document_membership - case.json yok/bozuk/geçerli ----

    import qa_discovery

    original_cases_dir = qa_discovery.CASES_DIR

    with tempfile.TemporaryDirectory(prefix="qa_engine_membership_selftest_") as td:

        fake_cases_dir = Path(td)

        qa_discovery.CASES_DIR = fake_cases_dir

        try:

            m1 = qa_discovery.resolve_document_membership("fixture_case")

            assert m1["state"] == "blocked", "case.json yokken 'blocked' bekleniyordu."

            case_dir = fake_cases_dir / "fixture_case"
            case_dir.mkdir(parents=True)

            (case_dir / "case.json").write_bytes(b"{not valid")

            m2 = qa_discovery.resolve_document_membership("fixture_case")

            assert m2["state"] == "blocked", "case.json bozukken 'blocked' bekleniyordu."

            (case_dir / "case.json").write_text(json.dumps({"case_document_refs": "not_a_list"}), encoding="utf-8")

            m3 = qa_discovery.resolve_document_membership("fixture_case")

            assert m3["state"] == "failed", "case_document_refs liste değilken 'failed' bekleniyordu."

            (case_dir / "case.json").write_text(
                json.dumps({"case_document_refs": [{"document_id": "doc_a"}, {"document_id": "doc_b"}]}),
                encoding="utf-8",
            )

            m4 = qa_discovery.resolve_document_membership("fixture_case")

            assert m4["state"] == "resolved" and m4["document_ids"] == ["doc_a", "doc_b"]

            print("T08 resolve_document_membership: blocked/blocked/failed/resolved senaryoları doğru:", "PASS")

        finally:

            qa_discovery.CASES_DIR = original_cases_dir

    # ---- T09: compare_manifests - tarama sırasında kaynak değişimi tespiti ----

    before_manifest = {"timeline": {"sha256": "aaa", "state": "present_valid"}}
    after_same = {"timeline": {"sha256": "aaa", "state": "present_valid"}}
    after_changed = {"timeline": {"sha256": "bbb", "state": "present_valid"}}

    assert compare_manifests(before_manifest, after_same)["consistent"] is True
    assert compare_manifests(before_manifest, after_changed)["consistent"] is False
    assert compare_manifests(before_manifest, after_changed)["changed_refs"] == ["timeline"]

    print("T09 compare_manifests: değişmeyen/değişen anlık görüntüler doğru ayırt ediliyor:", "PASS")

    # ---- T10: run_coverage_completeness_checks - sentetik eksik issue tespiti ----

    synthetic_ctx = {"issues": [{"issue_id": "issue_001"}, {"issue_id": "issue_002"}]}

    synthetic_scans = {
        "drafting": {
            "state": "present_valid", "sha256": "x",
            "parsed": {"draft_coverage": [{"source_issue_id": "issue_001"}]},  # issue_002 EKSİK
        },
    }

    builder3 = QaResultBuilder()

    import types

    fake_registry_scopes = ("drafting",)

    original_scopes = CHECK_APPLICABLE_SCOPES["coverage_completeness_and_1to1"]

    CHECK_APPLICABLE_SCOPES["coverage_completeness_and_1to1"] = fake_registry_scopes

    try:

        run_coverage_completeness_checks(builder3, synthetic_scans, synthetic_ctx)

    finally:

        CHECK_APPLICABLE_SCOPES["coverage_completeness_and_1to1"] = original_scopes

    assert builder3.results[0]["qa_result"] == "failed"
    assert builder3.results[0]["evidence"]["match"] is False

    print("T10 coverage_completeness_and_1to1: eksik issue coverage'ı doğru tespit etti (sentetik):", "PASS")

    # ---- T11: run_forbidden_phrase_checks - 0 entity -> not_applicable (fabrike passed DEĞİL) ----

    synthetic_scans2 = {"drafting": {"state": "present_valid", "sha256": "y", "parsed": {"draft_sections": [], "draft_agent_suggestions": []}}}

    builder4 = QaResultBuilder()

    original_scopes2 = CHECK_APPLICABLE_SCOPES["forbidden_phrase_and_outcome_guarantee_absence"]

    CHECK_APPLICABLE_SCOPES["forbidden_phrase_and_outcome_guarantee_absence"] = ("drafting",)

    try:

        run_forbidden_phrase_checks(builder4, synthetic_scans2)

    finally:

        CHECK_APPLICABLE_SCOPES["forbidden_phrase_and_outcome_guarantee_absence"] = original_scopes2

    assert builder4.results[0]["qa_result"] == "not_applicable"
    assert builder4.results[0]["reason_code"] == "no_applicable_entities"

    print("T11 forbidden_phrase check: 0 entity -> not_applicable (fabrike 'passed' DEĞİL):", "PASS")

    # ---- T12: checker exception -> error sonucu (scan ÇÖKMEZ) ----

    import case_document_validator as _cdv

    original_validate_case_documents = _cdv.validate_case_documents

    def _raise(*args, **kwargs):

        raise RuntimeError("simulated checker crash")

    _cdv.validate_case_documents = _raise

    try:

        builder5 = QaResultBuilder()

        membership_ok = {"state": "resolved", "document_ids": ["dava_dilekcesi_001"]}

        run_document_metadata_check(builder5, case_id, membership_ok)

        assert builder5.results[0]["qa_result"] == "error"
        assert builder5.results[0]["reason_code"] == "checker_runtime_error"
        assert builder5.results[0]["evidence"]["error_class"] == "RuntimeError"

    finally:

        _cdv.validate_case_documents = original_validate_case_documents

    print("T12 Checker'ın kendi exception'ı -> error sonucu (scan ÇÖKMEDİ):", "PASS")

    # ---- T13: gerçek case_0001/qa/ ağacı bu self-test boyunca hiç oluşmadı ----

    assert_real_qa_tree_unchanged(case_id, real_tree_before, "Self-test sonu")

    print("T13 Gerçek case_0001/qa/ ağacı self-test boyunca hiç oluşmadı:", "PASS")

    print()
    print("======================================")
    print(" QA ENGINE V1: 13/13 PASS")
    print("======================================")


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(description="Vergi AI QA Engine V1")
    parser.add_argument("--case", dest="case_id", default="case_0001")
    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

    else:

        result = build_qa_engine_output(args.case_id)
        print(json.dumps(result, ensure_ascii=False, indent=1))
