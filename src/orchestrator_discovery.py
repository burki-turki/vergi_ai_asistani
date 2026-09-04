# ============================================================
# VERGİ AI - ORCHESTRATOR DISCOVERY V1 (Row 17)
#
# Deterministik, saf-okuma katmanı: Row 17'nin okuduğu 11 sabit
# kaynağın (case, timeline, deadline, issues, legal_research,
# case_law, evidence, arguments, risk_strategy, drafting, qa)
# canonical yollarını çözer ve ham-bayt okuma/JSON parse için
# Row 16'nın (qa_discovery.py) ZATEN VAR OLAN, test edilmiş
# primitiflerini AYNEN kullanır (Prensip 10 - yeniden yazılmaz).
#
# BİLİNÇLİ TASARIM KARARI: Row 13-15'in "eligibility allowlist"
# loader'ları (argument_discovery.py, drafting_discovery.py)
# BURADA KULLANILMAZ - onlar Row 13-15'in KENDİ amacına (agent
# grounding menüsü) özgü filtreleme/şekillendirme mantığı taşır.
# Row 17 yalnız HAM, TAM, FİLTRELENMEMİŞ canonical veriyi okur;
# gruplama/birleştirme mantığı orchestrator_engine.py'dedir.
# ============================================================

from pathlib import Path

from qa_policy import sha256_of_bytes
from qa_discovery import (  # noqa: F401
    BASE_DIR,
    DATA_DIR,
    CASES_DIR,
    read_artifact_bytes,
    parse_json_bytes,
)

from orchestrator_policy import (
    ORCHESTRATOR_SOURCE_REGISTRY,
    ARTIFACT_STATE_PRESENT_VALID,
    ARTIFACT_STATE_PRESENT_INVALID,
    ARTIFACT_STATE_ABSENT,
    ARTIFACT_STATE_UNREADABLE,
)


# ============================================================
# 11 SABİT KAYNAĞIN CANONICAL YOLLARI - qa_discovery.py'nin
# SINGLE_FILE_SCOPE_PATHS'i (9 kaynak) + Row 17'ye özgü iki YENİ
# yol ("case", "qa" - qa_discovery bunları upstream olarak
# OKUMAZ, çünkü QA kendi çıktısını kendi girdisi yapmaz; Row 17
# ise her ikisini de birleştirilmiş görünüme dahil eder).
# ============================================================

def get_case_json_path(case_id):

    return CASES_DIR / case_id / "case.json"


def get_qa_json_path(case_id):

    return CASES_DIR / case_id / "qa" / "qa.json"


SOURCE_SCOPE_PATHS = {
    "case": get_case_json_path,
    "timeline": lambda case_id: CASES_DIR / case_id / "timeline" / "timeline.json",
    "deadline": lambda case_id: CASES_DIR / case_id / "deadlines" / "deadline.json",
    "issues": lambda case_id: CASES_DIR / case_id / "issues" / "issues.json",
    "legal_research": lambda case_id: CASES_DIR / case_id / "research" / "research.json",
    "case_law": lambda case_id: CASES_DIR / case_id / "case_law" / "case_law.json",
    "evidence": lambda case_id: CASES_DIR / case_id / "evidence" / "evidence.json",
    "arguments": lambda case_id: CASES_DIR / case_id / "arguments" / "arguments.json",
    "risk_strategy": lambda case_id: CASES_DIR / case_id / "risk_strategy" / "risk_strategy.json",
    "drafting": lambda case_id: CASES_DIR / case_id / "drafting" / "drafting.json",
    "qa": get_qa_json_path,
}

assert set(SOURCE_SCOPE_PATHS) == set(ORCHESTRATOR_SOURCE_REGISTRY), (
    "SOURCE_SCOPE_PATHS ve ORCHESTRATOR_SOURCE_REGISTRY birbirinden SAPTI."
)


def get_source_path(scope_id, case_id):

    return SOURCE_SCOPE_PATHS[scope_id](case_id)


# ============================================================
# TEK BİR KAYNAĞIN TAM, HAM OKUMASI - qa_discovery'nin
# read_artifact_bytes/parse_json_bytes'ı ile BİREBİR aynı
# state taksonomisi (present_valid/present_invalid/absent/
# unreadable). Bu fonksiyon HİÇBİR alanı FİLTRELEMEZ/SEÇMEZ -
# tüm .get() bazlı alan çıkarımı orchestrator_engine.py'dedir.
# ============================================================

def load_source_scope(scope_id, case_id):
    """
    Döner:
      {
        "scope_id": str,
        "path": Path,
        "artifact_state": "present_valid"|"present_invalid"|"absent"|"unreadable",
        "raw_bytes_sha256": str | None,
        "data": dict | None,   # yalnız present_valid ise dolu
      }
    """

    path = get_source_path(scope_id, case_id)

    raw_bytes, byte_state = read_artifact_bytes(path)

    if byte_state == "absent":

        return {
            "scope_id": scope_id, "path": path,
            "artifact_state": ARTIFACT_STATE_ABSENT,
            "raw_bytes_sha256": None, "data": None,
        }

    if byte_state == "unreadable":

        return {
            "scope_id": scope_id, "path": path,
            "artifact_state": ARTIFACT_STATE_UNREADABLE,
            "raw_bytes_sha256": None, "data": None,
        }

    sha256_value = sha256_of_bytes(raw_bytes)

    parsed, is_valid_json = parse_json_bytes(raw_bytes)

    if not is_valid_json or not isinstance(parsed, dict):

        return {
            "scope_id": scope_id, "path": path,
            "artifact_state": ARTIFACT_STATE_PRESENT_INVALID,
            "raw_bytes_sha256": sha256_value, "data": None,
        }

    return {
        "scope_id": scope_id, "path": path,
        "artifact_state": ARTIFACT_STATE_PRESENT_VALID,
        "raw_bytes_sha256": sha256_value, "data": parsed,
    }


def load_all_source_scopes(case_id):
    """
    11 kaynağın TAMAMINI tek seferde yükler. Döner:
      {scope_id: load_source_scope(...) sonucu, ...}
    Hiçbir kaynak eksik BIRAKILMAZ - 'evidence' dahil (opsiyonel
    olması yalnız validator/approval seviyesinde "absent kabul
    edilebilir" anlamına gelir, discovery seviyesinde HER ZAMAN
    denenir).
    """

    return {
        scope_id: load_source_scope(scope_id, case_id)
        for scope_id in ORCHESTRATOR_SOURCE_REGISTRY
    }


if __name__ == "__main__":

    print("orchestrator_discovery.py - saf okuma modülü, self-test yok.")
