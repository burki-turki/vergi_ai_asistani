# ============================================================
# VERGİ AI - QA DISCOVERY V1 (Row 16)
#
# Deterministik, saf-okuma katmanı: case.json'dan belge üyeliğini
# türetir, 11 scope'un canonical yollarını çözer, ham-bayt/yapılandırılmış
# hash'leri üretir. HİÇBİR LLM/network çağrısı yapmaz, HİÇBİR dosya
# YAZMAZ.
# ============================================================

import json
from pathlib import Path

from qa_policy import sha256_of, sha256_of_bytes

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CASES_DIR = DATA_DIR / "cases"


def get_case_dir(case_id):

    return CASES_DIR / case_id


def get_case_json_path(case_id):

    return get_case_dir(case_id) / "case.json"


# ============================================================
# 11 SCOPE'UN CANONICAL YOLLARI (tek-dosyalı 9 scope için).
# documents/facts çok-dosyalı aile - ayrı fonksiyonlarla çözülür.
# ============================================================

SINGLE_FILE_SCOPE_PATHS = {
    "timeline": lambda case_id: CASES_DIR / case_id / "timeline" / "timeline.json",
    "deadline": lambda case_id: CASES_DIR / case_id / "deadlines" / "deadline.json",
    "issues": lambda case_id: CASES_DIR / case_id / "issues" / "issues.json",
    "legal_research": lambda case_id: CASES_DIR / case_id / "research" / "research.json",
    "case_law": lambda case_id: CASES_DIR / case_id / "case_law" / "case_law.json",
    "evidence": lambda case_id: CASES_DIR / case_id / "evidence" / "evidence.json",
    "arguments": lambda case_id: CASES_DIR / case_id / "arguments" / "arguments.json",
    "risk_strategy": lambda case_id: CASES_DIR / case_id / "risk_strategy" / "risk_strategy.json",
    "drafting": lambda case_id: CASES_DIR / case_id / "drafting" / "drafting.json",
}


def get_single_file_scope_path(scope_id, case_id):

    return SINGLE_FILE_SCOPE_PATHS[scope_id](case_id)


def get_document_path(case_id, document_id):

    return CASES_DIR / case_id / "documents" / document_id / "document.json"


def get_facts_path(case_id, document_id):

    return CASES_DIR / case_id / "documents" / document_id / "extractions" / "facts.json"


# ============================================================
# HAM-BAYT OKUMA (#1/#2/#3'ün paylaştığı tek gerçek kaynak)
# ============================================================

def read_artifact_bytes(path):
    """
    Döner: (raw_bytes | None, state) - state ∈ {"present", "absent", "unreadable"}.
    'unreadable' YALNIZ dosya VAR ama okunamıyorsa (izin/OS hatası) - bu,
    'absent' ile KARIŞTIRILMAZ (Row 16 contract, madde D).
    """

    if not path.exists():

        return None, "absent"

    try:

        return path.read_bytes(), "present"

    except OSError:

        return None, "unreadable"


def parse_json_bytes(raw_bytes):
    """
    Döner: (parsed | None, is_valid). raw_bytes None ise (present değilse)
    çağrılmamalıdır - çağıran taraf önkoşulu (#2=passed) kendisi kontrol eder.
    """

    if raw_bytes is None:

        return None, False

    try:

        return json.loads(raw_bytes.decode("utf-8")), True

    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):

        return None, False


# ============================================================
# BELGE ÜYELİĞİ - YALNIZ case.json.case_document_refs'ten türer
# (Row 16 contract, madde A/D: "başarıyla yüklenen dosyalardan
# TÜRETİLMEZ"). documents/*/document.json glob'u BURADA
# KULLANILMAZ - yalnız her ÜYENİN kendi artifact_state'ini
# kontrol etmek için AYRI AYRI kullanılır (qa_engine).
# ============================================================

def resolve_document_membership(case_id):
    """
    Döner:
      {
        "state": "resolved" | "blocked" | "failed",
        "document_ids": [str, ...] | None,
        "case_json_raw_sha256": str | None,
        "case_json_artifact_state": "present_valid"|"present_invalid"|"absent"|"unreadable",
        "reason": str,
      }
    'blocked' -> case.json okunamıyor. 'failed' -> case.json okunuyor
    ama case_document_refs kendi şemasına aykırı (liste değil/document_id
    alanı yok). Boş bir küme ASLA sessizce İCAT EDİLMEZ.
    """

    case_json_path = get_case_json_path(case_id)

    raw_bytes, byte_state = read_artifact_bytes(case_json_path)

    if byte_state != "present":

        return {
            "state": "blocked",
            "document_ids": None,
            "case_json_raw_sha256": None,
            "case_json_artifact_state": "absent" if byte_state == "absent" else "unreadable",
            "reason": f"case.json {byte_state}",
        }

    case_json_sha256 = sha256_of_bytes(raw_bytes)

    parsed, is_valid_json = parse_json_bytes(raw_bytes)

    if not is_valid_json:

        return {
            "state": "blocked",
            "document_ids": None,
            "case_json_raw_sha256": case_json_sha256,
            "case_json_artifact_state": "present_invalid",
            "reason": "case.json JSON olarak parse edilemiyor",
        }

    refs = parsed.get("case_document_refs")

    if not isinstance(refs, list):

        return {
            "state": "failed",
            "document_ids": None,
            "case_json_raw_sha256": case_json_sha256,
            "case_json_artifact_state": "present_invalid",
            "reason": "case_document_refs alanı liste değil veya eksik (Row 2 kontrat ihlali)",
        }

    document_ids = []

    for entry in refs:

        if not isinstance(entry, dict) or not entry.get("document_id"):

            return {
                "state": "failed",
                "document_ids": None,
                "case_json_raw_sha256": case_json_sha256,
                "case_json_artifact_state": "present_invalid",
                "reason": "case_document_refs içinde document_id alanı eksik bir kayıt var (Row 2 kontrat ihlali)",
            }

        document_ids.append(entry["document_id"])

    return {
        "state": "resolved",
        "document_ids": document_ids,
        "case_json_raw_sha256": case_json_sha256,
        "case_json_artifact_state": "present_valid",
        "reason": "case_document_refs başarıyla çözüldü",
    }


# ============================================================
# TÜM UPSTREAM BAĞLAMI - #8/#9/#10 için gerekli TÜM canonical
# veriyi TEK SEFERDE, mevcut LOCKED loader'ları AYNEN kullanarak
# yükler. Hiçbir loader modifiye edilmez.
# ============================================================

def load_full_upstream_context(case_id):

    from legal_research_validator import load_canonical_issues
    from timeline_validator import load_canonical_fact_index
    from drafting_discovery import (
        build_active_documents_index,
        load_canonical_evidence_optional,
        load_canonical_legal_research_optional,
        load_canonical_case_law_optional,
        load_canonical_timeline_optional,
        load_canonical_deadline_optional,
    )
    from risk_strategy_discovery import load_canonical_arguments_optional
    from drafting_discovery import load_canonical_risk_strategy_optional

    ctx = {}

    ctx["issue_context"] = load_canonical_issues(case_id)
    ctx["issues"] = ctx["issue_context"]["issues"]
    ctx["issues_path"] = CASES_DIR / case_id / "issues" / "issues.json"

    ctx["fact_context"] = load_canonical_fact_index(case_id)
    ctx["fact_index"] = ctx["fact_context"]["facts"]

    ctx["active_documents_index"] = build_active_documents_index(case_id)

    _e, ctx["evidence_candidate_index"], ctx["evidence_path"] = load_canonical_evidence_optional(case_id)
    _r, ctx["research_index"], ctx["research_path"] = load_canonical_legal_research_optional(case_id)
    _d, ctx["case_law_decision_index"], ctx["case_law_path"] = load_canonical_case_law_optional(case_id)
    ctx["timeline_event_index"], ctx["timeline_path"] = load_canonical_timeline_optional(case_id)

    deadlines, deadline_ids, deadline_path = load_canonical_deadline_optional(case_id)
    ctx["deadlines"] = deadlines
    ctx["deadline_ids"] = deadline_ids
    ctx["deadline_path"] = deadline_path

    (
        claims, claim_index, counters, counter_index, rebuttals, rebuttal_index,
        argument_coverage_by_issue, arguments_path,
    ) = load_canonical_arguments_optional(case_id)

    ctx["claim_index"] = claim_index
    ctx["counter_index"] = counter_index
    ctx["rebuttal_index"] = rebuttal_index
    ctx["argument_coverage_by_issue"] = argument_coverage_by_issue
    ctx["arguments_path"] = arguments_path

    risk_index, strategy_index, risk_strategy_analysis, risk_strategy_path = (
        load_canonical_risk_strategy_optional(case_id)
    )
    ctx["risk_index"] = risk_index
    ctx["strategy_index"] = strategy_index
    ctx["risk_strategy_path"] = risk_strategy_path

    ctx["evidence_data"] = load_json_if_exists(ctx["evidence_path"])
    ctx["evidence_coverage_by_issue"] = build_coverage_by_issue(ctx["evidence_data"], "evidence_coverage")

    ctx["case_law_data"] = load_json_if_exists(ctx["case_law_path"])
    ctx["case_law_coverage_by_issue"] = build_coverage_by_issue(ctx["case_law_data"], "case_law_coverage")

    return ctx


def load_json_if_exists(path):

    if not path.exists():

        return {}

    try:

        return json.loads(path.read_text(encoding="utf-8"))

    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OSError):

        return {}


def build_coverage_by_issue(raw_data, coverage_field):
    """
    risk_strategy_validator.py:1071-1081 ile BİREBİR aynı desen -
    yalnız o dosyanın validate_risk_strategy_analysis'inde kullanılan
    yardımcı sözlüğün Row 16 tarafından bağımsız yeniden üretimi.
    """

    return {
        record["source_issue_id"]: record
        for record in raw_data.get(coverage_field, [])
        if isinstance(record, dict) and record.get("source_issue_id")
    }


if __name__ == "__main__":

    print("qa_discovery.py - saf okuma modülü, self-test yok.")
