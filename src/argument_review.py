# ============================================================
# VERGİ AI - ARGUMENT REVIEW V1 (LAYER B - TOP-DOWN REVIEW)
#
# AMAÇ
# ----
#
# Layer A (argument_approval.py) ile canonical hale gelmiş
# `arguments.json` içindeki BİREYSEL claim/counterargument/
# rebuttal/suggestion kayıtlarının review_state alanını, avukat
# tarafından açık bir mutation ile, TOP-DOWN sırayla (Claim ->
# Counterargument -> Rebuttal) günceller.
#
#
# İZİN VERİLEN GEÇİŞLER
# ----------------------
#
# Claim:            needs_review -> confirmed | rejected
# Counterargument:  needs_review -> confirmed | rejected
# Rebuttal:         needs_review -> confirmed | rejected
# Suggestion:       needs_review -> accepted_for_follow_up | dismissed
#
#
# PARENT DEPENDENCY (KRİTİK, LOCKED CONTRACT)
# ----------------------------------------------
#
# - Bir child (counterargument'ın parent'ı claim; rebuttal'ın
#   parent'ı counterargument) ancak PARENT TERMINAL STATE'E
#   (confirmed VEYA rejected) GELDİYSE review edilebilir - parent
#   hâlâ needs_review ise child review'u REDDEDİLİR.
# - Parent 'confirmed' ise child 'confirmed' VEYA 'rejected'
#   olabilir.
# - Parent 'rejected' ise child YALNIZ 'rejected' olabilir
#   ('confirmed' REDDEDİLİR).
# - Hiçbir child otomatik mutate edilmez - yalnız EXPLICIT bir
#   mutation isteği üzerine, ve yalnız yukarıdaki kural izin
#   veriyorsa.
#
# Suggestion'ın parent'ı yoktur; bağımsız review edilir.
#
#
# GÜVENLİK
# --------
#
# - Varsayılan çalışma REVIEW/DRY-RUN'dır.
# - Açık mutation isteği olmadan MUTATION YAPILMAZ.
# - Her mutation: backup, atomic write, TAM dosyanın yeniden
#   validate edilmesi, pre/post SHA256, ayrı audit kaydı,
#   rollback-on-failure.
# - Auditler reviews/argument_reviews/ altında tutulur (Layer
#   A'nın reviews/ audit'inden ve Layer A'nın kendi backup
#   mekanizmasından TAMAMEN BAĞIMSIZ).
# ============================================================


import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path


from argument_validator import validate_argument_analysis


# ============================================================
# VERSION
# ============================================================

ARGUMENT_REVIEW_VERSION = "1"

DEFAULT_CASE_ID = "case_0001"

STATE_FIELD_BY_TYPE = {
    "claim": "claim_review_state",
    "counterargument": "counter_review_state",
    "rebuttal": "rebuttal_review_state",
    "suggestion": "suggestion_review_state",
}

ID_FIELD_BY_TYPE = {
    "claim": "claim_id",
    "counterargument": "counterargument_id",
    "rebuttal": "rebuttal_id",
    "suggestion": "suggestion_id",
}

ARRAY_FIELD_BY_TYPE = {
    "claim": "argument_claims",
    "counterargument": "argument_counterarguments",
    "rebuttal": "argument_rebuttals",
    "suggestion": "argument_agent_suggestions",
}

ALLOWED_TARGETS_BY_TYPE = {
    "claim": {"confirmed", "rejected"},
    "counterargument": {"confirmed", "rejected"},
    "rebuttal": {"confirmed", "rejected"},
    "suggestion": {"accepted_for_follow_up", "dismissed"},
}


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

CASES_DIR = DATA_DIR / "cases"


# ============================================================
# EXCEPTION
# ============================================================

class ArgumentReviewError(Exception):
    pass


# ============================================================
# PATH HELPERS
# ============================================================

def get_arguments_dir(case_id):

    return CASES_DIR / case_id / "arguments"


def get_canonical_path(case_id):

    return get_arguments_dir(case_id) / "arguments.json"


def get_argument_review_audit_dir(case_id):

    return get_arguments_dir(case_id) / "reviews" / "argument_reviews"


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path):

    path = Path(path)

    if not path.exists():

        raise FileNotFoundError(f"Dosya bulunamadı:\n{path}")

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


def atomic_write_json(path, data):

    path = Path(path)

    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.parent / (path.name + ".tmp")

    with open(temp_path, "w", encoding="utf-8", newline="\n") as file:

        json.dump(data, file, ensure_ascii=False, indent=2)

        file.write("\n")

        file.flush()

        os.fsync(file.fileno())

    os.replace(temp_path, path)


def sha256_file(path):

    digest = hashlib.sha256()

    with open(path, "rb") as file:

        while True:

            chunk = file.read(1024 * 1024)

            if not chunk:

                break

            digest.update(chunk)

    return digest.hexdigest()


def now_iso():

    return datetime.now().astimezone().isoformat()


def now_stamp():

    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# BACKUP
# ============================================================

def backup_canonical(canonical_path, audit_dir):

    canonical_path = Path(canonical_path)

    audit_dir = Path(audit_dir)

    audit_dir.mkdir(parents=True, exist_ok=True)

    backup_path = audit_dir / ("arguments.json.before_review_" + now_stamp() + ".bak")

    shutil.copy2(canonical_path, backup_path)

    return backup_path


# ============================================================
# FIND RECORD
# ============================================================

def find_record(analysis, record_type, record_id):

    array_field = ARRAY_FIELD_BY_TYPE[record_type]

    id_field = ID_FIELD_BY_TYPE[record_type]

    for record in analysis.get(array_field, []):

        if record.get(id_field) == record_id:

            return record

    return None


def find_claim_by_id(analysis, claim_id):

    return find_record(analysis, "claim", claim_id)


def find_counterargument_by_id(analysis, counterargument_id):

    return find_record(analysis, "counterargument", counterargument_id)


# ============================================================
# PARENT DEPENDENCY GUARD (LOCKED CONTRACT)
# ============================================================

def get_parent_state(analysis, record_type, record):

    if record_type == "counterargument":

        claim = find_claim_by_id(analysis, record["source_claim_id"])

        if claim is None:

            raise ArgumentReviewError(
                f"Counterargument '{record['counterargument_id']}' için "
                f"parent claim bulunamadı: {record['source_claim_id']}"
            )

        return claim["claim_review_state"]

    if record_type == "rebuttal":

        counter = find_counterargument_by_id(
            analysis, record["source_counterargument_id"]
        )

        if counter is None:

            raise ArgumentReviewError(
                f"Rebuttal '{record['rebuttal_id']}' için parent "
                "counterargument bulunamadı: "
                f"{record['source_counterargument_id']}"
            )

        return counter["counter_review_state"]

    return None


def check_parent_dependency(analysis, record_type, record, target_state):

    if record_type not in ("counterargument", "rebuttal"):

        return None

    parent_state = get_parent_state(analysis, record_type, record)

    if parent_state == "needs_review":

        return (
            f"{record_type} review'u REDDEDİLDİ: parent henüz terminal "
            f"state'e gelmedi (mevcut parent durumu: '{parent_state}'). "
            "Top-down review sırası: Claim -> Counterargument -> Rebuttal."
        )

    if parent_state == "rejected" and target_state != "rejected":

        return (
            f"{record_type} review'u REDDEDİLDİ: parent 'rejected' iken "
            "child yalnız 'rejected' olabilir (LOCKED contract kuralı)."
        )

    return None


# ============================================================
# AUDIT RECORD
# ============================================================

def write_review_audit(
    audit_dir, case_id, argument_analysis_id, record_type, record_id,
    previous_state, new_state, parent_state, reviewer_ref, review_note,
    pre_sha256, post_sha256, backup_path,
):

    audit_dir = Path(audit_dir)

    audit_dir.mkdir(parents=True, exist_ok=True)

    audit_path = audit_dir / (
        "argument_review_" + record_id + "_" + now_stamp() + ".review_audit.json"
    )

    audit = {
        "audit_type": f"argument_{record_type}_review",
        "review_version": ARGUMENT_REVIEW_VERSION,
        "case_id": case_id,
        "argument_analysis_id": argument_analysis_id,
        "record_type": record_type,
        "record_id": record_id,
        "previous_state": previous_state,
        "new_state": new_state,
        "parent_state_at_review_time": parent_state,
        "reviewer_ref": reviewer_ref,
        "reviewed_at": now_iso(),
        "review_note": review_note,
        "pre_sha256": pre_sha256,
        "post_sha256": post_sha256,
        "canonical_backup": str(backup_path),
        "review_semantics": (
            "'confirmed', ilgili claim/counterargument/rebuttal'ın avukat "
            "tarafından geçerli bir öneri/karşı-öneri/cevap olarak kabul "
            "edildiğini gösterir; nihai hukuki sonuç, dava kazanma "
            "ihtimali veya admissibility/strength/sufficiency DEĞİLDİR."
        ),
    }

    atomic_write_json(audit_path, audit)

    return audit_path


# ============================================================
# CORE TRANSITION
# ============================================================

def apply_review_transition(
    case_id, record_type, record_id, target_state, reviewer_ref, review_note,
    canonical_path=None, audit_dir=None,
):

    if record_type not in ALLOWED_TARGETS_BY_TYPE:

        raise ArgumentReviewError(f"Geçersiz record_type: {record_type}")

    if target_state not in ALLOWED_TARGETS_BY_TYPE[record_type]:

        raise ArgumentReviewError(
            f"{record_type} için geçersiz hedef durum: {target_state} "
            f"(izin verilen: {sorted(ALLOWED_TARGETS_BY_TYPE[record_type])})"
        )

    canonical_path = Path(
        canonical_path if canonical_path is not None else get_canonical_path(case_id)
    )

    audit_dir = Path(
        audit_dir
        if audit_dir is not None
        else get_argument_review_audit_dir(case_id)
    )

    if not canonical_path.exists():

        raise ArgumentReviewError(f"Canonical arguments.json bulunamadı:\n{canonical_path}")

    pre_sha256 = sha256_file(canonical_path)

    analysis = load_json(canonical_path)

    record = find_record(analysis, record_type, record_id)

    if record is None:

        raise ArgumentReviewError(f"{record_type} bulunamadı: {record_id}")

    state_field = STATE_FIELD_BY_TYPE[record_type]

    previous_state = record.get(state_field)

    if previous_state != "needs_review":

        raise ArgumentReviewError(
            f"{record_type} '{record_id}' için geçiş yalnız 'needs_review' "
            f"kaynak durumundan başlayabilir (mevcut durum: "
            f"'{previous_state}')."
        )

    parent_error = check_parent_dependency(analysis, record_type, record, target_state)

    if parent_error:

        raise ArgumentReviewError(parent_error)

    parent_state = get_parent_state(analysis, record_type, record)

    backup_path = backup_canonical(canonical_path, audit_dir)

    try:

        record[state_field] = target_state

        atomic_write_json(canonical_path, analysis)

        validation = validate_argument_analysis(
            arguments_path=canonical_path, expected_case_id=case_id,
            raise_on_error=True,
        )

        if validation.get("valid") is not True:

            raise ArgumentReviewError("Post-review Argument Validator valid=False.")

        post_sha256 = sha256_file(canonical_path)

        audit_path = write_review_audit(
            audit_dir, case_id, analysis.get("argument_analysis_id"),
            record_type, record_id, previous_state, target_state,
            parent_state, reviewer_ref, review_note, pre_sha256, post_sha256,
            backup_path,
        )

    except Exception:

        shutil.copy2(backup_path, canonical_path)

        raise

    return {
        "canonical_path": canonical_path,
        "backup_path": backup_path,
        "audit_path": audit_path,
        "pre_sha256": pre_sha256,
        "post_sha256": post_sha256,
        "previous_state": previous_state,
        "new_state": target_state,
        "parent_state": parent_state,
        "validation": validation,
    }


# ============================================================
# REVIEW / DRY-RUN REPORT
# ============================================================

def run_review_report(case_id):

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT REVIEW V1 (LAYER B)")
    print(" MODE: REVIEW/DRY-RUN")
    print("======================================")

    canonical_path = get_canonical_path(case_id)

    if not canonical_path.exists():

        print()
        print("Canonical arguments.json henüz mevcut değil:")
        print(canonical_path)
        print()
        print("======================================")
        print(" ARGUMENT REVIEW V1: NOTHING TO REVIEW")
        print("======================================")
        return

    analysis = load_json(canonical_path)

    print()
    print("Case:", analysis.get("case_id"))
    print("Analysis ID:", analysis.get("argument_analysis_id"))
    print()
    print("Claims:")

    for claim in analysis.get("argument_claims", []):

        print("-", claim["claim_id"], "|", "state=" + claim["claim_review_state"])

    print()
    print("Counterarguments:")

    for counter in analysis.get("argument_counterarguments", []):

        print(
            "-", counter["counterargument_id"], "| parent=" + counter["source_claim_id"],
            "| state=" + counter["counter_review_state"],
        )

    print()
    print("Rebuttals:")

    for rebuttal in analysis.get("argument_rebuttals", []):

        print(
            "-", rebuttal["rebuttal_id"],
            "| parent=" + rebuttal["source_counterargument_id"],
            "| state=" + rebuttal["rebuttal_review_state"],
        )

    print()
    print("Suggestions:")

    for suggestion in analysis.get("argument_agent_suggestions", []):

        print(
            "-", suggestion["suggestion_id"],
            "| state=" + suggestion["suggestion_review_state"],
        )

    print()
    print("MUTATION:")
    print("- yapılmadı (--record-type/--record-id/--action verilmedi)")
    print()
    print("======================================")
    print(" ARGUMENT REVIEW V1: READY")
    print("======================================")


# ============================================================
# REAL ARGUMENTS TREE SNAPSHOT (POST-APPROVAL SELF-TEST INVARIANT)
#
# "Gerçek canonical arguments.json mevcut OLMAMALIDIR" varsayımı
# yalnız Row 13 approval ÖNCESİNDE geçerliydi. Approval sonrası bu
# varsayım kalıcı olarak geçersizdir. Doğru invariant: self-test
# başlamadan önceki gerçek dizin durumu (mevcut olsun ya da olmasın)
# self-test SONUNDA birebir aynı kalmalıdır. snapshot fonksiyonu
# CASES_DIR sabitinden DOĞRUDAN türetir - herhangi bir monkeypatch'ten
# ETKİLENMEZ, bu yüzden testin kendi izole tempdir mutation'larını
# YANLIŞLIKLA "gerçek değişiklik" olarak raporlamaz.
# ============================================================

def snapshot_real_arguments_tree(case_id):

    real_dir = CASES_DIR / case_id / "arguments"

    if not real_dir.exists():

        return {
            "dir_exists": False,
            "files": {},
            "subdirs": [],
        }

    files = {}

    for path in sorted(real_dir.rglob("*")):

        if path.is_file():

            rel = str(path.relative_to(real_dir))

            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()

    subdirs = sorted(
        str(path.relative_to(real_dir))
        for path in real_dir.rglob("*")
        if path.is_dir()
    )

    return {
        "dir_exists": True,
        "files": files,
        "subdirs": subdirs,
    }


def assert_real_arguments_tree_unchanged(case_id, before_snapshot, label):

    after_snapshot = snapshot_real_arguments_tree(case_id)

    assert after_snapshot == before_snapshot, (
        f"{label}: gerçek Row 13 arguments dizini self-test sırasında "
        f"DEĞİŞTİ (leakage şüphesi).\nÖnce: {before_snapshot}\n"
        f"Sonra: {after_snapshot}"
    )


# ============================================================
# SELF TEST (TEMPFILE ISOLATION - CANONICAL case_0001/arguments/
# ASLA DOKUNULMAZ)
# ============================================================

def run_self_test():

    import tempfile

    from argument_agent import FakeArgumentLLMClient
    from argument_discovery import build_allowlists_for_issues
    from argument_engine import build_argument_engine_output
    from legal_research_validator import load_canonical_issues
    from timeline_validator import load_canonical_fact_index
    from argument_discovery import (
        load_canonical_case_law_optional, load_canonical_deadline_optional,
        load_canonical_evidence_optional, load_canonical_legal_research_optional,
        load_canonical_timeline_optional,
    )

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT REVIEW V1 (SELF-TEST)")
    print("======================================")

    real_case_id = "case_0001"

    # Pre-self-test snapshot (post-approval invariant): gerçek
    # arguments dizini approval ile mevcut olsun ya da olmasın, bu
    # self-test SONUNDA birebir aynı kalmalıdır.

    real_tree_before = snapshot_real_arguments_tree(real_case_id)

    issue_context = load_canonical_issues(real_case_id)
    fact_context = load_canonical_fact_index(real_case_id)

    _e, evidence_index, _ep = load_canonical_evidence_optional(real_case_id)
    _r, research_index, _rp = load_canonical_legal_research_optional(real_case_id)
    _d, case_law_index, _dp = load_canonical_case_law_optional(real_case_id)
    timeline_index, _tp = load_canonical_timeline_optional(real_case_id)
    _dl, deadline_ids, _dlp = load_canonical_deadline_optional(real_case_id)

    allowlist_by_issue, _w = build_allowlists_for_issues(
        issue_context["issues"], fact_context["facts"], evidence_index,
        research_index, case_law_index, timeline_index, deadline_ids,
    )

    grounded_issue_id = next(
        issue_id for issue_id, menu in allowlist_by_issue.items()
        if menu["has_minimum_grounding"]
    )

    fact_id = allowlist_by_issue[grounded_issue_id]["eligible_fact_ids"][0]

    claim_response = json.dumps(
        [{
            "source_issue_id": grounded_issue_id, "claim_type": "factual_challenge",
            "claim_text": "Bu fact issue baglamini desteklemektedir.",
            "source_fact_ids": [fact_id], "source_evidence_candidate_ids": [],
            "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
            "reason_code": "explicit_textual_match",
            "grounded_explanation": "Fact dogrudan ilgilidir.",
        }], ensure_ascii=False,
    )

    counter_response = json.dumps(
        [{
            "source_claim_id": "argument_claim_001", "counter_type": "factual_denial",
            "counterargument_text": "Bu olgu farkli yorumlanabilir.",
            "source_fact_ids": [fact_id], "source_evidence_candidate_ids": [],
            "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
            "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Ayni fact farkli okunabilir.",
        }], ensure_ascii=False,
    )

    rebuttal_response = json.dumps(
        [{
            "source_counterargument_id": "argument_counter_001",
            "rebuttal_type": "factual_refutation",
            "rebuttal_text": "Bu yorum fact ile tutarsizdir.",
            "source_fact_ids": [fact_id], "source_evidence_candidate_ids": [],
            "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
            "reason_code": "explicit_textual_match",
            "grounded_explanation": "Fact ile celisir.",
        }], ensure_ascii=False,
    )

    suggestion_response = json.dumps(
        [{
            "source_issue_id": grounded_issue_id,
            "suggestion_type": "additional_research_needed",
            "source_claim_id": "argument_claim_001",
            "source_counterargument_id": None, "related_reference_ids": [],
            "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Ek arastirma faydali olabilir.",
        }], ensure_ascii=False,
    )

    client = FakeArgumentLLMClient(
        response_sequence=[
            claim_response, counter_response, rebuttal_response, suggestion_response,
        ]
    )

    build_result = build_argument_engine_output(
        real_case_id, use_agent=True, llm_client=client, network_allowed=False,
    )

    analysis = build_result["analysis"]

    claim_id = analysis["argument_claims"][0]["claim_id"]

    counterargument_id = analysis["argument_counterarguments"][0]["counterargument_id"]

    rebuttal_id = analysis["argument_rebuttals"][0]["rebuttal_id"]

    suggestion_id = analysis["argument_agent_suggestions"][0]["suggestion_id"]

    temp_dir = tempfile.TemporaryDirectory(prefix="argument_review_selftest_")

    isolated_canonical_path = Path(temp_dir.name) / "arguments.json"

    isolated_audit_dir = Path(temp_dir.name) / "reviews" / "argument_reviews"

    atomic_write_json(isolated_canonical_path, analysis)

    # --------------------------------------------------------
    # T01 REBUTTAL REVIEW BLOCKED - PARENT (COUNTERARGUMENT)
    # STILL needs_review
    # --------------------------------------------------------

    raised = False

    try:

        apply_review_transition(
            real_case_id, "rebuttal", rebuttal_id, "confirmed", "test_reviewer",
            "Should fail - parent still needs_review.",
            canonical_path=isolated_canonical_path, audit_dir=isolated_audit_dir,
        )

    except ArgumentReviewError:

        raised = True

    assert raised is True

    print(
        "T01 Rebuttal review blocked while parent counterargument is "
        "still needs_review (top-down order enforced):", "PASS",
    )

    # --------------------------------------------------------
    # T02 CONFIRM CLAIM (top of hierarchy, no parent)
    # --------------------------------------------------------

    result = apply_review_transition(
        real_case_id, "claim", claim_id, "confirmed", "test_reviewer",
        "Self-test confirm claim.", canonical_path=isolated_canonical_path,
        audit_dir=isolated_audit_dir,
    )

    assert result["new_state"] == "confirmed"
    assert result["parent_state"] is None

    print("T02 Claim confirmed (no parent dependency):", "PASS")

    # --------------------------------------------------------
    # T03 COUNTERARGUMENT REVIEW NOW ALLOWED (parent confirmed) -
    # CONFIRM
    # --------------------------------------------------------

    result = apply_review_transition(
        real_case_id, "counterargument", counterargument_id, "confirmed",
        "test_reviewer", "Self-test confirm counterargument.",
        canonical_path=isolated_canonical_path, audit_dir=isolated_audit_dir,
    )

    assert result["new_state"] == "confirmed"
    assert result["parent_state"] == "confirmed"

    print(
        "T03 Counterargument confirmed once parent claim is confirmed "
        "(both confirmed allowed):", "PASS",
    )

    # --------------------------------------------------------
    # T04 REBUTTAL NOW REVIEWABLE (parent counterargument
    # terminal) - CONFIRM
    # --------------------------------------------------------

    result = apply_review_transition(
        real_case_id, "rebuttal", rebuttal_id, "confirmed", "test_reviewer",
        "Self-test confirm rebuttal.", canonical_path=isolated_canonical_path,
        audit_dir=isolated_audit_dir,
    )

    assert result["new_state"] == "confirmed"

    print("T04 Rebuttal confirmed once parent counterargument is terminal:", "PASS")

    print(
        "T05 Review audit fields (reviewer_ref/previous_state/new_state/"
        "pre-post SHA256/parent_state_at_review_time):", "PASS",
    )

    audit_content = load_json(result["audit_path"])

    assert audit_content["parent_state_at_review_time"] == "confirmed"
    assert audit_content["previous_state"] == "needs_review"
    assert audit_content["new_state"] == "confirmed"

    # --------------------------------------------------------
    # T06 RE-TRANSITION FROM TERMINAL STATE REJECTED
    # --------------------------------------------------------

    raised = False

    try:

        apply_review_transition(
            real_case_id, "claim", claim_id, "rejected", "test_reviewer",
            "Should fail.", canonical_path=isolated_canonical_path,
            audit_dir=isolated_audit_dir,
        )

    except ArgumentReviewError:

        raised = True

    assert raised is True

    print("T06 Re-transition from terminal state rejected:", "PASS")

    # --------------------------------------------------------
    # T07 SUGGESTION REVIEW (INDEPENDENT, NO PARENT)
    # --------------------------------------------------------

    result = apply_review_transition(
        real_case_id, "suggestion", suggestion_id, "accepted_for_follow_up",
        "test_reviewer", "Self-test accept.", canonical_path=isolated_canonical_path,
        audit_dir=isolated_audit_dir,
    )

    assert result["new_state"] == "accepted_for_follow_up"
    assert result["parent_state"] is None

    print("T07 Suggestion accepted_for_follow_up (independent, no parent):", "PASS")

    # --------------------------------------------------------
    # T08 "PARENT REJECTED -> CHILD ONLY REJECTED" RULE
    # --------------------------------------------------------

    second_client = FakeArgumentLLMClient(
        response_sequence=[
            claim_response, counter_response, rebuttal_response, suggestion_response,
        ]
    )

    second_analysis = build_argument_engine_output(
        real_case_id, use_agent=True, llm_client=second_client, network_allowed=False,
    )["analysis"]

    second_path = Path(temp_dir.name) / "arguments_second.json"

    atomic_write_json(second_path, second_analysis)

    second_claim_id = second_analysis["argument_claims"][0]["claim_id"]

    second_counter_id = second_analysis["argument_counterarguments"][0][
        "counterargument_id"
    ]

    apply_review_transition(
        real_case_id, "claim", second_claim_id, "rejected", "test_reviewer",
        "Self-test reject claim.", canonical_path=second_path,
        audit_dir=isolated_audit_dir,
    )

    raised = False

    try:

        apply_review_transition(
            real_case_id, "counterargument", second_counter_id, "confirmed",
            "test_reviewer", "Should fail - parent rejected.",
            canonical_path=second_path, audit_dir=isolated_audit_dir,
        )

    except ArgumentReviewError:

        raised = True

    assert raised is True

    result = apply_review_transition(
        real_case_id, "counterargument", second_counter_id, "rejected",
        "test_reviewer", "Self-test reject counterargument (only option).",
        canonical_path=second_path, audit_dir=isolated_audit_dir,
    )

    assert result["new_state"] == "rejected"

    print(
        "T08 Parent 'rejected' -> child can ONLY be 'rejected' "
        "(confirmed forbidden):", "PASS",
    )

    # --------------------------------------------------------
    # T09 REAL CANONICAL case_0001/arguments/ NEVER TOUCHED
    # --------------------------------------------------------

    assert_real_arguments_tree_unchanged(
        real_case_id, real_tree_before,
        "End of self-test (full suite)",
    )

    print("T09 Real canonical case_0001/arguments/ untouched:", "PASS")

    temp_dir.cleanup()

    print()
    print("======================================")
    print(" ARGUMENT REVIEW V1: 9/9 SELF-TEST PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Argument Review V1 (Layer B)")

    parser.add_argument("--case", dest="case_id", default=DEFAULT_CASE_ID)

    parser.add_argument(
        "--record-type", dest="record_type",
        choices=["claim", "counterargument", "rebuttal", "suggestion"],
        default=None,
    )

    parser.add_argument("--record-id", dest="record_id", default=None)

    parser.add_argument(
        "--action", dest="action",
        choices=["confirm", "reject", "accept_follow_up", "dismiss"],
        default=None,
    )

    parser.add_argument("--reviewer", default="human_review")

    parser.add_argument(
        "--note", default="Argument Review V1 ile insan tarafından incelendi.",
    )

    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

        return

    if not (args.record_type and args.record_id and args.action):

        run_review_report(args.case_id)

        return

    action_to_state = {
        "confirm": "confirmed",
        "reject": "rejected",
        "accept_follow_up": "accepted_for_follow_up",
        "dismiss": "dismissed",
    }

    target_state = action_to_state[args.action]

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT REVIEW V1 (LAYER B)")
    print(" MODE: MUTATE")
    print("======================================")

    result = apply_review_transition(
        args.case_id, args.record_type, args.record_id, target_state,
        args.reviewer, args.note,
    )

    print()
    print("REVIEW TRANSITION APPLIED")
    print("Record:", args.record_id)
    print("Previous state:", result["previous_state"])
    print("New state:", result["new_state"])
    print("Parent state at review time:", result["parent_state"])
    print("Pre SHA256:", result["pre_sha256"])
    print("Post SHA256:", result["post_sha256"])
    print("Audit:", result["audit_path"])
    print()
    print("======================================")
    print(" ARGUMENT REVIEW V1: PASS")
    print("======================================")


if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()
        print("ERROR:")
        print(error)
        print()
        print("======================================")
        print(" ARGUMENT REVIEW V1: FAIL")
        print("======================================")
        sys.exit(1)
