# ============================================================
# VERGİ AI - RISK / STRATEGY REVIEW V1 (LAYER B)
#
# AMAÇ: canonical risk_strategy.json içindeki BİREYSEL risk/
# strategy/suggestion kayıtlarının needs_review -> terminal state
# geçişini yönetmek. Pending package approval mekanizması DEĞİLDİR
# (bkz. risk_strategy_approval.py / Layer A - ayrı, bağımsız süreç).
#
# R1. identified/gap ayrımı OLMAKSIZIN bir strateji'nin adresslediği
#     TÜM risk'ler terminal (confirmed/rejected) olmadan strateji
#     terminal review edilemez.
# R2. Tüm addressed risk'ler rejected ise strateji yalnız dismissed
#     olabilir.
# R3. Tüm addressed risk'ler terminal VE en az biri confirmed ise
#     hem accepted_for_follow_up hem dismissed mümkündür (insan
#     seçer, sistem zorlamaz).
# R4. Otomatik cascade YOK - her geçiş ayrı, açık bir mutasyondur.
# R5. Audit, TÜM addressed risk'ler için parent_states_at_review_time
#     haritası taşır.
# R6. Suggestion review lifecycle'ı risk/strateji parent sırasından
#     tamamen bağımsızdır.
#
# Deterministik belirsizlik bayrakları (flags) bu modül tarafından
# ASLA silinmez/güncellenmez. Review, upstream veriyi verified veya
# hukuken kesin hale getirmez.
# ============================================================

import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path

from risk_strategy_validator import validate_risk_strategy_analysis
from risk_strategy_policy import render_strategy_description


RISK_STRATEGY_REVIEW_VERSION = "1"

STATE_FIELD_BY_TYPE = {
    "risk": "risk_review_state",
    "strategy": "strategy_review_state",
    "suggestion": "suggestion_review_state",
}

ID_FIELD_BY_TYPE = {
    "risk": "risk_id",
    "strategy": "strategy_id",
    "suggestion": "suggestion_id",
}

ARRAY_FIELD_BY_TYPE = {
    "risk": "risk_candidates",
    "strategy": "strategy_candidates",
    "suggestion": "risk_strategy_agent_suggestions",
}

ALLOWED_TARGETS_BY_TYPE = {
    "risk": {"confirmed", "rejected"},
    "strategy": {"accepted_for_follow_up", "dismissed"},
    "suggestion": {"accepted_for_follow_up", "dismissed"},
}


BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

CASES_DIR = DATA_DIR / "cases"


class RiskStrategyReviewError(Exception):
    pass


def get_risk_strategy_dir(case_id):

    return CASES_DIR / case_id / "risk_strategy"


def get_canonical_path(case_id):

    return get_risk_strategy_dir(case_id) / "risk_strategy.json"


def get_risk_strategy_review_audit_dir(case_id):

    return get_risk_strategy_dir(case_id) / "reviews" / "risk_strategy_reviews"


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


def backup_canonical(canonical_path, audit_dir):

    canonical_path = Path(canonical_path)

    audit_dir = Path(audit_dir)

    audit_dir.mkdir(parents=True, exist_ok=True)

    backup_path = audit_dir / ("risk_strategy.json.before_review_" + now_stamp() + ".bak")

    shutil.copy2(canonical_path, backup_path)

    return backup_path


def find_record(analysis, record_type, record_id):

    array_field = ARRAY_FIELD_BY_TYPE[record_type]

    id_field = ID_FIELD_BY_TYPE[record_type]

    for record in analysis.get(array_field, []):

        if record.get(id_field) == record_id:

            return record

    return None


def find_risk_by_id(analysis, risk_id):

    return find_record(analysis, "risk", risk_id)


# ============================================================
# MANY-TO-MANY PARENT DEPENDENCY GUARD (R1-R6)
# ============================================================

def get_parent_states(analysis, record_type, record):
    """
    strategy: TÜM addresses_risk_ids'in review_state'lerinin
    {risk_id: state} haritası. risk/suggestion: None (parent yok).
    """

    if record_type != "strategy":

        return None

    states = {}

    for risk_id in record.get("addresses_risk_ids", []):

        risk = find_risk_by_id(analysis, risk_id)

        if risk is None:

            raise RiskStrategyReviewError(
                f"Strategy '{record['strategy_id']}' için addressed risk "
                f"bulunamadı: {risk_id}"
            )

        states[risk_id] = risk["risk_review_state"]

    return states


def check_parent_dependency(analysis, record_type, record, target_state):

    if record_type != "strategy":

        return None

    parent_states = get_parent_states(analysis, record_type, record)

    values = list(parent_states.values())

    if any(v == "needs_review" for v in values):

        return (
            "Strategy review'u REDDEDİLDİ: addressed risk'lerden en az "
            "biri hâlâ 'needs_review' (R1 - tüm addressed risk'ler "
            f"terminal olmalı). Durumlar: {parent_states}"
        )

    all_rejected = bool(values) and all(v == "rejected" for v in values)

    if all_rejected and target_state != "dismissed":

        return (
            "Strategy review'u REDDEDİLDİ: tüm addressed risk'ler "
            f"'rejected' iken strateji yalnız 'dismissed' olabilir (R2). "
            f"Durumlar: {parent_states}"
        )

    return None


# ============================================================
# AUDIT
# ============================================================

def write_review_audit(
    audit_dir, case_id, risk_strategy_analysis_id, record_type, record_id,
    previous_state, new_state, parent_states, reviewer_ref, review_note,
    pre_sha256, post_sha256, backup_path,
):

    audit_dir = Path(audit_dir)

    audit_dir.mkdir(parents=True, exist_ok=True)

    audit_path = audit_dir / (
        "risk_strategy_review_" + record_id + "_" + now_stamp() + ".review_audit.json"
    )

    audit = {
        "audit_type": f"risk_strategy_{record_type}_review",
        "review_version": RISK_STRATEGY_REVIEW_VERSION,
        "case_id": case_id,
        "risk_strategy_analysis_id": risk_strategy_analysis_id,
        "record_type": record_type,
        "record_id": record_id,
        "previous_state": previous_state,
        "new_state": new_state,
        "parent_states_at_review_time": parent_states,
        "reviewer_ref": reviewer_ref,
        "reviewed_at": now_iso(),
        "review_note": review_note,
        "pre_sha256": pre_sha256,
        "post_sha256": post_sha256,
        "canonical_backup": str(backup_path),
        "review_semantics": (
            "'confirmed' bir risk'in avukat tarafından geçerli/gerçek "
            "kabul edildiğini gösterir; 'accepted_for_follow_up' bir "
            "stratejinin insan tarafından sonraki adım olarak kabul "
            "edildiğini gösterir - hiçbiri nihai hukuki sonuç, dava "
            "kazanma ihtimali veya kesin bir karar DEĞİLDİR. Bu review "
            "deterministik belirsizlik bayraklarını (flags) SİLMEZ/"
            "GÜNCELLEMEZ ve upstream veriyi doğrulanmış hale getirmez."
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

        raise RiskStrategyReviewError(f"Geçersiz record_type: {record_type}")

    if target_state not in ALLOWED_TARGETS_BY_TYPE[record_type]:

        raise RiskStrategyReviewError(
            f"{record_type} için geçersiz hedef durum: {target_state} "
            f"(izin verilen: {sorted(ALLOWED_TARGETS_BY_TYPE[record_type])})"
        )

    canonical_path = Path(
        canonical_path if canonical_path is not None else get_canonical_path(case_id)
    )

    audit_dir = Path(
        audit_dir if audit_dir is not None else get_risk_strategy_review_audit_dir(case_id)
    )

    if not canonical_path.exists():

        raise RiskStrategyReviewError(f"Canonical risk_strategy.json bulunamadı:\n{canonical_path}")

    pre_sha256 = sha256_file(canonical_path)

    analysis = load_json(canonical_path)

    record = find_record(analysis, record_type, record_id)

    if record is None:

        raise RiskStrategyReviewError(f"{record_type} bulunamadı: {record_id}")

    state_field = STATE_FIELD_BY_TYPE[record_type]

    previous_state = record.get(state_field)

    if previous_state != "needs_review":

        raise RiskStrategyReviewError(
            f"{record_type} '{record_id}' için geçiş yalnız 'needs_review' "
            f"kaynak durumundan başlayabilir (mevcut durum: '{previous_state}')."
        )

    parent_error = check_parent_dependency(analysis, record_type, record, target_state)

    if parent_error:

        raise RiskStrategyReviewError(parent_error)

    parent_states = get_parent_states(analysis, record_type, record)

    backup_path = backup_canonical(canonical_path, audit_dir)

    try:

        record[state_field] = target_state

        atomic_write_json(canonical_path, analysis)

        validation = validate_risk_strategy_analysis(
            arguments_path=canonical_path, expected_case_id=case_id, raise_on_error=True,
        )

        if validation.get("valid") is not True:

            raise RiskStrategyReviewError("Post-review Risk/Strategy Validator valid=False.")

        post_sha256 = sha256_file(canonical_path)

        audit_path = write_review_audit(
            audit_dir, case_id, analysis.get("risk_strategy_analysis_id"),
            record_type, record_id, previous_state, target_state, parent_states,
            reviewer_ref, review_note, pre_sha256, post_sha256, backup_path,
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
        "parent_states": parent_states,
        "validation": validation,
    }


# ============================================================
# REAL TREE SNAPSHOT INVARIANT
# ============================================================

def snapshot_real_risk_strategy_tree(case_id):

    real_dir = CASES_DIR / case_id / "risk_strategy"

    if not real_dir.exists():

        return {"dir_exists": False, "files": {}, "subdirs": []}

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

    return {"dir_exists": True, "files": files, "subdirs": subdirs}


def assert_real_risk_strategy_tree_unchanged(case_id, before_snapshot, label):

    after_snapshot = snapshot_real_risk_strategy_tree(case_id)

    assert after_snapshot == before_snapshot, (
        f"{label}: gerçek Row 14 risk_strategy dizini self-test sırasında "
        f"DEĞİŞTİ (leakage şüphesi).\nÖnce: {before_snapshot}\nSonra: {after_snapshot}"
    )


# ============================================================
# SELF TEST (izole tempdir - carbon copy + synthetic fixtures)
# ============================================================

def _recompute_coverage(base, risks, strategies, suggestions):
    """
    Fixture-only yardımcı: risk_coverage'ın gap/identified/strategy_
    reference/suggestion count'larını ve execution_state'lerini,
    verilen risks/strategies/suggestions dizilerinden bağımsız olarak
    yeniden hesaplar - böylece self-test fixture'ları validator'ın
    ZERO-count invariant'larını ihlal etmez. Bu, üretim engine
    mantığının bir KOPYASI değil, yalnız test fixture'ının kendi
    içinde tutarlı olmasını sağlayan basit bir muhasebedir.
    """

    risks_by_issue = {}

    for r in risks:

        risks_by_issue.setdefault(r["source_issue_id"], []).append(r)

    strategy_ref_count = {}

    for s in strategies:

        addressed_issue_ids = {
            r["source_issue_id"] for r in risks if r["risk_id"] in s["addresses_risk_ids"]
        }

        for issue_id in addressed_issue_ids:

            strategy_ref_count[issue_id] = strategy_ref_count.get(issue_id, 0) + 1

    suggestion_count = {}

    for s in suggestions:

        if s.get("source_issue_id"):

            suggestion_count[s["source_issue_id"]] = suggestion_count.get(s["source_issue_id"], 0) + 1

    for coverage in base["risk_coverage"]:

        issue_id = coverage["source_issue_id"]

        issue_risks = risks_by_issue.get(issue_id, [])

        gap_count = sum(1 for r in issue_risks if r["risk_kind"] == "gap")

        identified_count = sum(1 for r in issue_risks if r["risk_kind"] == "identified")

        coverage["gap_risk_count"] = gap_count

        coverage["identified_risk_count"] = identified_count

        coverage["risk_execution_state"] = (
            "analysis_completed" if (gap_count or identified_count) else "analysis_not_run"
        )

        ref_count = strategy_ref_count.get(issue_id, 0)

        coverage["strategy_reference_count"] = ref_count

        coverage["strategy_execution_state"] = (
            "analysis_completed" if ref_count else (
                "blocked_missing_input" if (gap_count or identified_count) else "analysis_not_run"
            )
        )

        coverage["reason_codes"] = (
            [] if (gap_count or identified_count) else coverage.get("reason_codes", [])
        )

        coverage["suggestion_count"] = suggestion_count.get(issue_id, 0)

    return base


def run_self_test():

    import tempfile

    from risk_strategy_agent import FakeRiskStrategyLLMClient
    from risk_strategy_engine import build_risk_strategy_engine_output

    print()
    print("======================================")
    print(" VERGİ AI - RISK / STRATEGY REVIEW V1 (SELF-TEST)")
    print("======================================")

    case_id = "case_0001"

    real_tree_before = snapshot_real_risk_strategy_tree(case_id)

    temp_dir = tempfile.TemporaryDirectory(prefix="risk_strategy_review_selftest_")

    canonical_path = Path(temp_dir.name) / "risk_strategy.json"

    audit_dir = Path(temp_dir.name) / "reviews" / "risk_strategy_reviews"

    # ---- Gerçek case_0001 verisinden, gerçekten üretilebilen risk/
    # strategy adaylarını Fake client ile bir kez üretiyoruz - böylece
    # tüm self-test fixture'ları GERÇEK canonical referanslara dayanır. ----

    identified_response = json.dumps([
        {
            "source_issue_id": "issue_001", "risk_type": "unverified_fact_dependency",
            "reason_code": "explicit_textual_match", "grounded_explanation": "Test guvenli metin.",
            "source_fact_ids": ["fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003"],
            "source_claim_ids": [], "source_counterargument_ids": [], "source_rebuttal_ids": [],
            "source_evidence_candidate_ids": [], "source_legal_research_ids": [], "source_case_law_ids": [],
            "source_timeline_event_ids": [], "source_deadline_ids": [],
        }
    ], ensure_ascii=False)

    client = FakeRiskStrategyLLMClient(response_sequence=[identified_response, "[]"])

    real_result = build_risk_strategy_engine_output(
        case_id, use_agent=True, llm_client=client, network_allowed=False,
    )

    real_analysis = real_result["analysis"]

    risk_by_id = {r["risk_id"]: r for r in real_analysis["risk_candidates"]}

    # risk_gap_001..005 (issue_002..006) + risk_identified_001 (issue_001)
    # ve bunlara 1:1 karşılık gelen strategy_001..006 gerçek engine
    # çıktısında zaten mevcut.

    def write_fixture(risks, strategies, suggestions=None):

        base = json.loads(json.dumps(real_analysis))

        base["risk_candidates"] = risks

        base["strategy_candidates"] = strategies

        base["risk_strategy_agent_suggestions"] = suggestions or []

        base = _recompute_coverage(base, risks, strategies, suggestions or [])

        atomic_write_json(canonical_path, base)

        return base

    def reset_review_state(record, field, state="needs_review"):

        record = json.loads(json.dumps(record))

        record[field] = state

        return record

    try:

        # ---- T01: strategy blocked while gap parent needs_review ----

        r1 = reset_review_state(risk_by_id["risk_gap_001"], "risk_review_state")

        s1 = next(
            json.loads(json.dumps(s)) for s in real_analysis["strategy_candidates"]
            if s["addresses_risk_ids"] == ["risk_gap_001"]
        )

        s1["strategy_review_state"] = "needs_review"

        write_fixture([r1], [s1])

        raised = False

        try:

            apply_review_transition(
                case_id, "strategy", "strategy_001", "accepted_for_follow_up",
                "reviewer_a", "note", canonical_path=canonical_path, audit_dir=audit_dir,
            )

        except RiskStrategyReviewError:

            raised = True

        assert raised is True

        print("T01 Strategy review blocked while parent risk is needs_review (R1, gap-parent included):", "PASS")

        # ---- T02: risk confirmed (no parent dependency) ----

        result_r1 = apply_review_transition(
            case_id, "risk", "risk_gap_001", "confirmed", "reviewer_a", "note",
            canonical_path=canonical_path, audit_dir=audit_dir,
        )

        assert result_r1["new_state"] == "confirmed"

        print("T02 Risk confirmed (no parent dependency):", "PASS")

        # ---- T03: strategy accepted_for_follow_up once parent risk confirmed ----

        result_s1 = apply_review_transition(
            case_id, "strategy", "strategy_001", "accepted_for_follow_up", "reviewer_a", "note",
            canonical_path=canonical_path, audit_dir=audit_dir,
        )

        assert result_s1["new_state"] == "accepted_for_follow_up"

        print("T03 Strategy accepted_for_follow_up once parent risk is terminal+confirmed (R3):", "PASS")

        # ---- T04: audit fields ----

        audit = load_json(result_s1["audit_path"])

        assert audit["reviewer_ref"] == "reviewer_a"
        assert audit["previous_state"] == "needs_review"
        assert audit["new_state"] == "accepted_for_follow_up"
        assert audit["pre_sha256"] == result_s1["pre_sha256"]
        assert audit["post_sha256"] == result_s1["post_sha256"]
        assert audit["parent_states_at_review_time"] == {"risk_gap_001": "confirmed"}

        print("T04 Review audit fields (reviewer_ref/previous_state/new_state/pre-post SHA256/parent_states_at_review_time):", "PASS")

        # ---- T05: re-transition from terminal rejected ----

        raised = False

        try:

            apply_review_transition(
                case_id, "risk", "risk_gap_001", "rejected", "reviewer_b", "note",
                canonical_path=canonical_path, audit_dir=audit_dir,
            )

        except RiskStrategyReviewError:

            raised = True

        assert raised is True

        print("T05 Re-transition from terminal state rejected:", "PASS")

        # ---- T06: suggestion independent, no parent ----

        sug = {
            "suggestion_id": "risk_strategy_suggestion_001", "suggestion_type": "additional_analysis_needed",
            "source_issue_id": "issue_001", "related_reference_ids": [], "reason_code": "general_contextual_relevance",
            "grounded_explanation": "Test guvenli suggestion metni.", "suggestion_review_state": "needs_review",
            "requires_human_review": True, "status": "candidate",
        }

        write_fixture(
            [json.loads(json.dumps(r1)) | {"risk_review_state": "confirmed"}],
            [json.loads(json.dumps(s1)) | {"strategy_review_state": "accepted_for_follow_up"}],
            [sug],
        )

        result_sug = apply_review_transition(
            case_id, "suggestion", "risk_strategy_suggestion_001", "accepted_for_follow_up",
            "reviewer_a", "note", canonical_path=canonical_path, audit_dir=audit_dir,
        )

        assert result_sug["new_state"] == "accepted_for_follow_up"
        assert result_sug["parent_states"] is None

        print("T06 Suggestion accepted_for_follow_up (independent, no parent - R6):", "PASS")

        # ---- T07: all (multiple) parents rejected -> strategy only dismissed ----

        r_id_a, r_id_b = "risk_gap_002", "risk_gap_003"

        ra = reset_review_state(risk_by_id[r_id_a], "risk_review_state")

        rb = reset_review_state(risk_by_id[r_id_b], "risk_review_state")

        multi_strategy = {
            "strategy_id": "strategy_multi_001",
            "addresses_risk_ids": [r_id_a, r_id_b],
            "strategy_action_type": "request_human_risk_assessment",
            "strategy_description": render_strategy_description("request_human_risk_assessment"),
            "grounded_explanation": "Iki gap risk birlikte adreslenmektedir.",
            "source_fact_ids": [], "source_claim_ids": [], "source_counterargument_ids": [],
            "source_rebuttal_ids": [], "source_evidence_candidate_ids": [], "source_legal_research_ids": [],
            "source_case_law_ids": [],
            "source_timeline_event_ids": list(set(ra.get("source_timeline_event_ids", []) + rb.get("source_timeline_event_ids", []))),
            "source_deadline_ids": list(set(ra.get("source_deadline_ids", []) + rb.get("source_deadline_ids", []))),
            "flags": dict(ra["flags"]),
            "depends_on_gap_only": True,
            "record_kind": "suggested_next_action",
            "requires_human_decision": True,
            "strategy_review_state": "needs_review",
            "requires_human_review": True,
            "status": "candidate",
        }

        write_fixture([ra, rb], [multi_strategy])

        apply_review_transition(case_id, "risk", r_id_a, "rejected", "r", "n", canonical_path=canonical_path, audit_dir=audit_dir)
        apply_review_transition(case_id, "risk", r_id_b, "rejected", "r", "n", canonical_path=canonical_path, audit_dir=audit_dir)

        raised = False

        try:

            apply_review_transition(
                case_id, "strategy", "strategy_multi_001", "accepted_for_follow_up", "r", "n",
                canonical_path=canonical_path, audit_dir=audit_dir,
            )

        except RiskStrategyReviewError:

            raised = True

        assert raised is True

        result_dismiss = apply_review_transition(
            case_id, "strategy", "strategy_multi_001", "dismissed", "r", "n",
            canonical_path=canonical_path, audit_dir=audit_dir,
        )

        assert result_dismiss["new_state"] == "dismissed"

        print("T07 All (multiple) parents rejected -> accepted_for_follow_up forbidden, dismissed allowed (R2):", "PASS")

        # ---- T08: mixed confirmed+rejected parents -> both targets allowed ----

        r_id_c, r_id_d = "risk_gap_004", "risk_identified_001"

        rc = reset_review_state(risk_by_id[r_id_c], "risk_review_state")

        rd = reset_review_state(risk_by_id[r_id_d], "risk_review_state")

        multi_strategy2 = dict(multi_strategy)

        multi_strategy2["strategy_id"] = "strategy_multi_002"

        multi_strategy2["addresses_risk_ids"] = [r_id_c, r_id_d]

        multi_strategy2["depends_on_gap_only"] = False

        multi_strategy2["source_fact_ids"] = list(rd.get("source_fact_ids", []))

        multi_strategy2["source_timeline_event_ids"] = list(rc.get("source_timeline_event_ids", []))

        multi_strategy2["source_deadline_ids"] = list(rc.get("source_deadline_ids", []))

        multi_strategy2["strategy_review_state"] = "needs_review"

        write_fixture([rc, rd], [multi_strategy2])

        apply_review_transition(case_id, "risk", r_id_c, "confirmed", "r", "n", canonical_path=canonical_path, audit_dir=audit_dir)
        apply_review_transition(case_id, "risk", r_id_d, "rejected", "r", "n", canonical_path=canonical_path, audit_dir=audit_dir)

        result_mixed = apply_review_transition(
            case_id, "strategy", "strategy_multi_002", "accepted_for_follow_up", "r", "n",
            canonical_path=canonical_path, audit_dir=audit_dir,
        )

        assert result_mixed["new_state"] == "accepted_for_follow_up"

        print("T08 Mixed confirmed+rejected parents -> accepted_for_follow_up permitted (R3, human choice):", "PASS")

        # ---- T09: no automatic cascade ----

        final_analysis = load_json(canonical_path)

        rc_final = find_risk_by_id(final_analysis, r_id_c)

        assert rc_final["risk_review_state"] == "confirmed"

        rd_final = find_risk_by_id(final_analysis, r_id_d)

        assert rd_final["risk_review_state"] == "rejected"

        print("T09 No automatic cascade (parent transitions do not implicitly change unrelated records):", "PASS")

        # ---- T10: 3+ parent risks, spanning MULTIPLE issues (002/003/004) - R1-R3 ----

        r_id_e, r_id_f, r_id_g = "risk_gap_001", "risk_gap_002", "risk_gap_003"

        re_ = reset_review_state(risk_by_id[r_id_e], "risk_review_state")
        rf_ = reset_review_state(risk_by_id[r_id_f], "risk_review_state")
        rg_ = reset_review_state(risk_by_id[r_id_g], "risk_review_state")

        assert len({re_["source_issue_id"], rf_["source_issue_id"], rg_["source_issue_id"]}) == 3, (
            "Test fixture 3 farklı issue'ya yayılmıyor - test geçersiz."
        )

        multi_strategy3 = dict(multi_strategy)

        multi_strategy3["strategy_id"] = "strategy_multi_003"

        multi_strategy3["addresses_risk_ids"] = [r_id_e, r_id_f, r_id_g]

        multi_strategy3["source_deadline_ids"] = list(set(
            re_.get("source_deadline_ids", []) + rf_.get("source_deadline_ids", []) + rg_.get("source_deadline_ids", [])
        ))

        multi_strategy3["source_timeline_event_ids"] = list(set(
            re_.get("source_timeline_event_ids", []) + rf_.get("source_timeline_event_ids", []) + rg_.get("source_timeline_event_ids", [])
        ))

        multi_strategy3["source_legal_research_ids"] = []

        multi_strategy3["strategy_review_state"] = "needs_review"

        write_fixture([re_, rf_, rg_], [multi_strategy3])

        # R1: hiçbiri terminal değilken review reddedilir
        raised = False
        try:
            apply_review_transition(
                case_id, "strategy", "strategy_multi_003", "dismissed", "r", "n",
                canonical_path=canonical_path, audit_dir=audit_dir,
            )
        except RiskStrategyReviewError:
            raised = True
        assert raised is True

        # Yalnız 2/3 terminal - hâlâ reddedilmeli
        apply_review_transition(case_id, "risk", r_id_e, "confirmed", "r", "n", canonical_path=canonical_path, audit_dir=audit_dir)
        apply_review_transition(case_id, "risk", r_id_f, "rejected", "r", "n", canonical_path=canonical_path, audit_dir=audit_dir)

        raised = False
        try:
            apply_review_transition(
                case_id, "strategy", "strategy_multi_003", "accepted_for_follow_up", "r", "n",
                canonical_path=canonical_path, audit_dir=audit_dir,
            )
        except RiskStrategyReviewError:
            raised = True
        assert raised is True, "3. parent (r_id_g) hâlâ needs_review iken review İZİN VERİLMEMELİ (R1)."

        # 3/3 terminal, en az biri confirmed -> her iki hedef de mümkün (R3)
        apply_review_transition(case_id, "risk", r_id_g, "confirmed", "r", "n", canonical_path=canonical_path, audit_dir=audit_dir)

        result_multi3 = apply_review_transition(
            case_id, "strategy", "strategy_multi_003", "accepted_for_follow_up", "r", "n",
            canonical_path=canonical_path, audit_dir=audit_dir,
        )

        assert result_multi3["new_state"] == "accepted_for_follow_up"

        assert result_multi3["parent_states"] == {
            r_id_e: "confirmed", r_id_f: "rejected", r_id_g: "confirmed",
        }

        print(
            "T10 3+ parent risk, 3 farklı issue'ya yayılan strateji: R1 "
            "(kısmi terminal reddi) ve R3 (tam terminal + karışık "
            "confirmed/rejected -> izin) doğru çalışıyor:", "PASS",
        )

    finally:

        temp_dir.cleanup()

    assert_real_risk_strategy_tree_unchanged(case_id, real_tree_before, "End of self-test")

    print("T11 Real canonical case_0001/risk_strategy/ untouched:", "PASS")

    print()
    print("======================================")
    print(" RISK / STRATEGY REVIEW V1: 11/11 SELF-TEST PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Risk/Strategy Review V1 (Layer B)")

    parser.add_argument("--case", dest="case_id", default="case_0001")

    parser.add_argument("--record-type", choices=["risk", "strategy", "suggestion"])

    parser.add_argument("--record-id")

    parser.add_argument("--action", choices=["confirm", "reject", "accept_follow_up", "dismiss"])

    parser.add_argument("--reviewer", default=None)

    parser.add_argument("--note", default=None)

    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

        return

    action_to_state = {
        "confirm": "confirmed", "reject": "rejected",
        "accept_follow_up": "accepted_for_follow_up", "dismiss": "dismissed",
    }

    if not (args.record_type and args.record_id and args.action):

        print("Kullanım: --record-type --record-id --action [--reviewer] [--note]")

        return

    result = apply_review_transition(
        args.case_id, args.record_type, args.record_id, action_to_state[args.action],
        args.reviewer, args.note,
    )

    print("OK:", args.record_type, args.record_id, "->", result["new_state"])
    print("Audit:", result["audit_path"])


if __name__ == "__main__":

    main()
