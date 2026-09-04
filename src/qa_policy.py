# ============================================================
# VERGİ AI - QA POLICY V1 (Row 16)
#
# Saf deterministik sabitler, taksonomiler ve düşük seviyeli
# primitifler. Bu modül HİÇBİR dosya I/O'su, LLM/network çağrısı
# yapmaz; qa_discovery/qa_agent/qa_engine/qa_validator'ın import
# ettiği ORTAK katmandır.
#
# KAYIT DONDURULDU (ROW 16 — FIXED REGISTRY turlarında kesinleşti):
#   11 scope, 12 check_id. Bu modül bu iki listeyi SABİT tutar;
#   yeni scope/check İCAT ETMEZ.
# ============================================================

import hashlib
import json
import re
import re


# ============================================================
# 11 SABİT SCOPE (Row 16 contract - değiştirilemez)
# ============================================================

QA_SCOPE_REGISTRY = (
    "documents",
    "facts",
    "timeline",
    "deadline",
    "issues",
    "legal_research",
    "case_law",
    "evidence",
    "arguments",
    "risk_strategy",
    "drafting",
)

# Yalnız 'evidence' opsiyoneldir (Row 12 checkpoint: canonical evidence.json
# henüz OLUŞTURULMAMIŞ olabilir - bu KASITLI bir durumdur, kontrat ihlali
# DEĞİLDİR). Diğer 10 scope zorunludur.
QA_OPTIONAL_SCOPES = frozenset({"evidence"})

# documents/facts çok-dosyalı aile; diğer 9 tek-dosyalı.
QA_MULTI_FILE_SCOPES = frozenset({"documents", "facts"})


# ============================================================
# 12 SABİT CHECK_ID (Row 16 contract - değiştirilemez, ROW 16 —
# FIXED REGISTRY turunda donduruldu)
# ============================================================

QA_CHECK_REGISTRY = (
    "artifact_presence",
    "raw_byte_readability",
    "json_validity",
    "document_membership_enumerable",
    "document_metadata_present_and_valid",
    "fact_extraction_present_and_valid",
    "row_schema_and_reference_validity",
    "stale_input_hash_consistency",
    "coverage_completeness_and_1to1",
    "coverage_execution_state_accounted_for",
    "pending_human_review_backlog_count",
    "forbidden_phrase_and_outcome_guarantee_absence",
)

CHECK_VERSION = "1"

# instance_mode: 'scope' (member_id=None) veya 'document_member'
# (member_id=document_id). SABİTTİR - üyelik çözülemediğinde
# DEĞİŞMEZ, yalnız o instance'lar hiç üretilemez (qa_discovery).
CHECK_INSTANCE_MODE = {
    "artifact_presence": "mixed",  # documents/facts=document_member, diğerleri=scope
    "raw_byte_readability": "mixed",
    "json_validity": "mixed",
    "document_membership_enumerable": "scope",
    "document_metadata_present_and_valid": "scope",
    "fact_extraction_present_and_valid": "document_member",
    "row_schema_and_reference_validity": "scope",
    "stale_input_hash_consistency": "scope",
    "coverage_completeness_and_1to1": "scope",
    "coverage_execution_state_accounted_for": "scope",
    "pending_human_review_backlog_count": "scope",
    "forbidden_phrase_and_outcome_guarantee_absence": "scope",
}

# Her check_id'nin uygulandığı scope kümesi (Row 16 — FINAL SOURCE-FIELD
# MAPPING VERIFICATION turunda doğrudan şema/kod okumasıyla doğrulandı).
CHECK_APPLICABLE_SCOPES = {
    "artifact_presence": QA_SCOPE_REGISTRY,
    "raw_byte_readability": QA_SCOPE_REGISTRY,
    "json_validity": QA_SCOPE_REGISTRY,
    "document_membership_enumerable": ("documents",),
    "document_metadata_present_and_valid": ("documents",),
    "fact_extraction_present_and_valid": ("facts",),
    "row_schema_and_reference_validity": (
        "timeline", "deadline", "issues", "legal_research", "case_law",
        "evidence", "arguments", "risk_strategy", "drafting",
    ),
    # legal_research/case_law: data/case_legal_research.schema.json ve
    # data/case_case_law.schema.json'da analysis_metadata YOK (doğrudan
    # doğrulandı) - bu iki scope bu check'e DAHİL DEĞİLDİR.
    "stale_input_hash_consistency": ("evidence", "arguments", "risk_strategy", "drafting"),
    # legal_research: research_candidates[] var, ayrı bir coverage dizisi
    # YOK (doğrudan doğrulandı) - bu check'e DAHİL DEĞİLDİR.
    "coverage_completeness_and_1to1": ("case_law", "evidence", "arguments", "risk_strategy", "drafting"),
    "coverage_execution_state_accounted_for": (
        "legal_research", "deadline", "case_law", "evidence", "arguments",
        "risk_strategy", "drafting",
    ),
    "pending_human_review_backlog_count": (
        "evidence", "arguments", "risk_strategy", "drafting", "case_law",
    ),
    "forbidden_phrase_and_outcome_guarantee_absence": ("drafting", "risk_strategy", "arguments"),
}

QA_SUGGESTION_TYPES = (
    "possible_semantic_inconsistency",
    "unexplained_state_pattern",
    "needs_deeper_human_review",
    "cross_row_observation",
)

SUGGESTION_REVIEW_STATES = ("needs_review", "accepted_for_follow_up", "dismissed")


# ============================================================
# JSON / HASH HELPERS (Row 13-15 ile birebir aynı desen)
# ============================================================

def canonical_dumps(value):

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_of(value):

    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


def sha256_of_bytes(raw_bytes):

    return hashlib.sha256(raw_bytes).hexdigest()


# ============================================================
# RISK/STRATEGY CASE-SCOPE SABİT KÜMESİ (Row 14'ten AYNEN
# import edilir - risk_strategy_policy.py:22-30, MUTATE EDİLMEZ)
# ============================================================

from risk_strategy_policy import CASE_RISK_SCOPES  # noqa: E402


# ============================================================
# #11 pending_human_review_backlog_count İÇİN KAYNAK EŞLEMESİ
# (Row 16 — FINAL SOURCE-FIELD MAPPING VERIFICATION turunda
# doğrudan şema okumasıyla doğrulandı). case_law YOK - şemasında
# hiçbir review_state/suggestion_review_state alanı YOK, yalnız
# requires_human_review=const true var (bu bir lifecycle DEĞİLDİR).
# ============================================================

PENDING_REVIEW_SOURCE_MAP = {
    "evidence": (
        ("evidence_candidates", "review_state"),
        ("evidence_agent_suggestions", "suggestion_review_state"),
    ),
    "arguments": (
        ("argument_claims", "claim_review_state"),
        ("argument_counterarguments", "counter_review_state"),
        ("argument_rebuttals", "rebuttal_review_state"),
        ("argument_agent_suggestions", "suggestion_review_state"),
    ),
    "risk_strategy": (
        ("risk_candidates", "risk_review_state"),
        ("strategy_candidates", "strategy_review_state"),
        ("risk_strategy_agent_suggestions", "suggestion_review_state"),
    ),
    "drafting": (
        ("draft_sections", "section_review_state"),
        ("draft_agent_suggestions", "suggestion_review_state"),
    ),
    # "case_law" KASITLI OLARAK BURADA YOK - #11 bu scope için
    # not_applicable döner (qa_engine), reason_code="no_review_lifecycle_field_in_schema".
}

PENDING_VALUE = "needs_review"


# ============================================================
# #10 coverage_execution_state_accounted_for İÇİN KAYNAK EŞLEMESİ
# (field_name diversity KORUNUR - hiçbir alan başka bir isimle
# ZORLANMAZ). risk_strategy İKİ AYRI eksen taşır (aynı kayıtta).
# ============================================================

EXECUTION_STATE_SOURCE_MAP = {
    "legal_research": ("research_candidates", "finding_status", None),
    "deadline": ("deadlines", "calculation_state", None),
    "case_law": ("case_law_coverage", "execution_state", None),
    "evidence": ("evidence_coverage", "execution_state", None),
    "arguments": ("argument_coverage", "execution_state", None),
    "drafting": ("draft_coverage", "execution_state", None),
    # risk_strategy: TEK bir (array, field) çifti YETERSİZ - iki AYRI
    # issue-seviyesi eksen (risk_coverage üzerinde) + case-scope ekseni
    # (case_scope_coverage üzerinde) qa_engine'de AYRI AYRI işlenir.
    "risk_strategy": None,
}


# ============================================================
# METİN-GÜVENLİK PRİMİTİFLERİ - HER SATIRIN KENDİ DÜŞÜK SEVİYELİ
# fonksiyonu import edilir, CROSS-IMPORT/BİRLEŞTİRME YAPILMAZ
# (Row 15'in kendi disipliniyle aynı ilke).
# ============================================================

from drafting_policy import (  # noqa: E402
    check_forbidden_phrases_context as drafting_check_forbidden_phrases_context,
)
from risk_strategy_policy import (  # noqa: E402
    check_forbidden_phrases as risk_strategy_check_forbidden_phrases,
)
from argument_validator import (  # noqa: E402
    check_forbidden_phrases as argument_check_forbidden_phrases,
)
from timeline_consolidation_policy import normalize_text_tr  # noqa: E402


TEXT_SAFETY_CHECKERS = {
    "drafting": drafting_check_forbidden_phrases_context,
    "risk_strategy": risk_strategy_check_forbidden_phrases,
    "arguments": argument_check_forbidden_phrases,
}


# ============================================================
# QA'NIN KENDİ AGENT SUGGESTION SERBEST METNİ İÇİN (qa_agent.py)
# outcome-guarantee + forbidden-phrase kontrolü - Row 15'in KENDİ
# fonksiyonunu aynen kullanır (yeni bir sözlük İCAT EDİLMEZ).
# ============================================================

def check_qa_suggestion_text_safety(record_id, text):

    return drafting_check_forbidden_phrases_context(
        record_id, text, "facts_summary", False,
    )


# ============================================================
# QA'YA ÖZGÜ ID-BİÇİMİ TESPİTİ - Row 15'in ID_SHAPE_PATTERN'i
# (drafting_policy.py) yalnız Row 1-15'in upstream ID prefix'lerini
# tanır (fact_, timeline_event_, ..., draft_section_); qa_check_result_
# ve qa_agent_suggestion_ bu listede YOKTUR ve Row 15 LOCKED olduğu
# için bu listeye EKLENEMEZ. Bu yüzden QA kendi DAR, kendi prefix
# ailesine özgü bir ID-biçimi regex'i ve üç-kategori sınıflandırmasını
# (declared/smuggled/fabricated) - Row 15'in find_id_reference_issues
# ile AYNI ilkeyle - KENDİ dosyasında tanımlar.
# ============================================================

QA_ID_SHAPE_PATTERN = re.compile(r"\bqa_check_result_[A-Za-z0-9_]+\b")


def find_qa_suggestion_id_issues(text, declared_ids, all_known_ids):

    if not text:

        return {"fabricated": [], "smuggled": []}

    declared = set(declared_ids)
    fabricated = []
    smuggled = []
    seen = set()

    for match in QA_ID_SHAPE_PATTERN.finditer(text):

        token = match.group(0)

        if token in seen:

            continue

        seen.add(token)

        if token in declared:

            continue

        if token in all_known_ids:

            smuggled.append(token)

        else:

            fabricated.append(token)

    return {"fabricated": fabricated, "smuggled": smuggled}


if __name__ == "__main__":

    print("qa_policy.py - saf modül, self-test yok.")
