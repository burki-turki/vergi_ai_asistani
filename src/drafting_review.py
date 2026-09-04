# ============================================================
# VERGİ AI - DRAFTING REVIEW V1 (LAYER B)
#
# AMAÇ: canonical drafting.json içindeki BİREYSEL section/suggestion
# kayıtlarının needs_review -> terminal state geçişini yönetmek.
# Pending package approval mekanizması DEĞİLDİR (bkz. drafting_approval.py
# / Layer A - ayrı, bağımsız süreç).
#
# Section/suggestion arasında bir ebeveyn-hiyerarşisi YOKTUR (Row 13/14'ün
# claim/counterargument/rebuttal veya risk/strategy zinciri gibi değil).
# Ama section'ı CONFIRM etmeden önce, o section'ın TÜM draft_source_refs
# kaynaklarının O ANKİ (confirm-zamanı) durumu YENİDEN kontrol edilir -
# herhangi biri artık hard-deny ise section 'stale_source_now_denied'
# ile REDDEDİLİR (needs_review'a düşürülüp kullanılabilir bırakılmaz).
# ============================================================

import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path

from drafting_validator import validate_drafting_analysis
from timeline_validator import load_canonical_fact_index, load_json as _tv_load_json

from argument_discovery import (
    load_canonical_evidence_optional,
    load_canonical_legal_research_optional,
    load_canonical_case_law_optional,
    load_canonical_timeline_optional,
    load_canonical_deadline_optional,
)

from risk_strategy_discovery import load_canonical_arguments_optional
from drafting_discovery import (
    load_canonical_risk_strategy_optional,
    legal_research_grounding_class,
    build_active_documents_index,
)


DRAFTING_REVIEW_VERSION = "1"

STATE_FIELD_BY_TYPE = {"section": "section_review_state", "suggestion": "suggestion_review_state"}

ID_FIELD_BY_TYPE = {"section": "section_id", "suggestion": "suggestion_id"}

ARRAY_FIELD_BY_TYPE = {"section": "draft_sections", "suggestion": "draft_agent_suggestions"}

ALLOWED_TARGETS_BY_TYPE = {
    "section": {"confirmed", "rejected"},
    "suggestion": {"accepted_for_follow_up", "dismissed"},
}


BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

CASES_DIR = DATA_DIR / "cases"


class DraftingReviewError(Exception):
    pass


def get_drafting_dir(case_id):

    return CASES_DIR / case_id / "drafting"


def get_canonical_path(case_id):

    return get_drafting_dir(case_id) / "drafting.json"


def get_drafting_review_audit_dir(case_id):

    return get_drafting_dir(case_id) / "reviews" / "drafting_reviews"


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

    backup_path = audit_dir / ("drafting.json.before_review_" + now_stamp() + ".bak")

    shutil.copy2(canonical_path, backup_path)

    return backup_path


def find_record(analysis, record_type, record_id):

    array_field = ARRAY_FIELD_BY_TYPE[record_type]

    id_field = ID_FIELD_BY_TYPE[record_type]

    for record in analysis.get(array_field, []):

        if record.get(id_field) == record_id:

            return record

    return None


# ============================================================
# STALE-SOURCE RE-CHECK (Confirm anında kaynak uygunluğu yeniden
# değerlendirilir - yalnız needs_review'a düşürülüp bırakılmaz)
# ============================================================

def is_source_still_eligible(case_id, source_field, source_id):

    if source_field == "source_fact_ids":

        fact_context = load_canonical_fact_index(case_id)

        record = fact_context["facts"].get(source_id)

        if record is None:

            return False

        # Madde 5/A düzeltmesi: fact'in KENDİSİ var olması yetmez - bağlı
        # belgenin GÜNCEL active=true durumu da doğrulanmalıdır (yalnız
        # kaynak yok oldu senaryosu değil, belge inactive oldu senaryosu
        # da bu dedike helper'ın KENDİSİ tarafından yakalanmalıdır).
        active_documents_index = build_active_documents_index(case_id)

        return record["source_document_id"] in active_documents_index

    if source_field == "source_timeline_event_ids":

        timeline_event_index, _p = load_canonical_timeline_optional(case_id)

        event = timeline_event_index.get(source_id)

        return event is not None and event.get("verification_state") not in ("disputed", "rejected")

    if source_field == "source_deadline_ids":

        deadlines, _ids, _p = load_canonical_deadline_optional(case_id)

        deadline = next((d for d in deadlines if d["deadline_id"] == source_id), None)

        return deadline is not None and deadline.get("calculation_state") != "not_applicable"

    if source_field == "source_legal_research_ids":

        _r, research_index, _p = load_canonical_legal_research_optional(case_id)

        research = research_index.get(source_id)

        if research is None:

            return False

        klass, _reason = legal_research_grounding_class(research)

        return klass != "deny"

    if source_field == "source_case_law_ids":

        _d, case_law_decision_index, _p = load_canonical_case_law_optional(case_id)

        return source_id in case_law_decision_index

    if source_field == "source_evidence_candidate_ids":

        _e, evidence_candidate_index, path = load_canonical_evidence_optional(case_id)

        if not path.exists():

            return False

        candidate = evidence_candidate_index.get(source_id)

        return candidate is not None and candidate.get("review_state") != "rejected"

    if source_field in ("source_claim_ids", "source_counterargument_ids", "source_rebuttal_ids"):

        (claims, claim_index, counters, counter_index, rebuttals, rebuttal_index, _cov, path) = (
            load_canonical_arguments_optional(case_id)
        )

        if not path.exists():

            return False

        if source_field == "source_claim_ids":

            claim = claim_index.get(source_id)

            return claim is not None and claim.get("claim_review_state") != "rejected"

        if source_field == "source_counterargument_ids":

            counter = counter_index.get(source_id)

            if counter is None or counter.get("counter_review_state") == "rejected":

                return False

            parent_claim = claim_index.get(counter.get("source_claim_id"))

            return not (parent_claim is not None and parent_claim.get("claim_review_state") == "rejected")

        rebuttal = rebuttal_index.get(source_id)

        if rebuttal is None or rebuttal.get("rebuttal_review_state") == "rejected":

            return False

        parent_counter = counter_index.get(rebuttal.get("source_counterargument_id"))

        if parent_counter is not None and parent_counter.get("counter_review_state") == "rejected":

            return False

        parent_claim = claim_index.get(parent_counter.get("source_claim_id")) if parent_counter else None

        return not (parent_claim is not None and parent_claim.get("claim_review_state") == "rejected")

    if source_field in ("source_risk_ids", "source_strategy_ids"):

        risk_index, strategy_index, _rsa, path = load_canonical_risk_strategy_optional(case_id)

        if not path.exists():

            return False

        if source_field == "source_risk_ids":

            risk = risk_index.get(source_id)

            return risk is not None and risk.get("risk_review_state") != "rejected"

        strategy = strategy_index.get(source_id)

        return strategy is not None and strategy.get("strategy_review_state") != "dismissed"

    return False


def check_stale_sources(case_id, analysis, section):

    refs = [
        r for r in analysis.get("draft_source_refs", []) if r["section_id"] == section["section_id"]
    ]

    stale = []

    for ref in refs:

        if not is_source_still_eligible(case_id, ref["source_field"], ref["source_id"]):

            stale.append((ref["source_field"], ref["source_id"]))

    return stale


# ============================================================
# AUDIT
# ============================================================

def write_review_audit(
    audit_dir, case_id, drafting_analysis_id, record_type, record_id, previous_state, new_state,
    reviewer_ref, review_note, pre_sha256, post_sha256, backup_path,
):

    audit_dir = Path(audit_dir)

    audit_dir.mkdir(parents=True, exist_ok=True)

    audit_path = audit_dir / ("drafting_review_" + record_id + "_" + now_stamp() + ".review_audit.json")

    audit = {
        "audit_type": f"drafting_{record_type}_review",
        "review_version": DRAFTING_REVIEW_VERSION,
        "case_id": case_id,
        "drafting_analysis_id": drafting_analysis_id,
        "record_type": record_type,
        "record_id": record_id,
        "previous_state": previous_state,
        "new_state": new_state,
        "reviewer_ref": reviewer_ref,
        "reviewed_at": now_iso(),
        "review_note": review_note,
        "pre_sha256": pre_sha256,
        "post_sha256": post_sha256,
        "canonical_backup": str(backup_path),
        "review_semantics": (
            "'confirmed' bir section'ın avukat tarafından hukuki içerik "
            "olarak incelendiğini gösterir - kanıtlanmış olgu, kesin hukuki "
            "sonuç veya gönderim yetkisi DEĞİLDİR. submission_status HER "
            "ZAMAN 'draft_only' kalır."
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

        raise DraftingReviewError(f"Geçersiz record_type: {record_type}")

    if target_state not in ALLOWED_TARGETS_BY_TYPE[record_type]:

        raise DraftingReviewError(
            f"{record_type} için geçersiz hedef durum: {target_state} "
            f"(izin verilen: {sorted(ALLOWED_TARGETS_BY_TYPE[record_type])})"
        )

    canonical_path = Path(canonical_path if canonical_path is not None else get_canonical_path(case_id))

    audit_dir = Path(audit_dir if audit_dir is not None else get_drafting_review_audit_dir(case_id))

    if not canonical_path.exists():

        raise DraftingReviewError(f"Canonical drafting.json bulunamadı:\n{canonical_path}")

    pre_sha256 = sha256_file(canonical_path)

    analysis = load_json(canonical_path)

    record = find_record(analysis, record_type, record_id)

    if record is None:

        raise DraftingReviewError(f"{record_type} bulunamadı: {record_id}")

    state_field = STATE_FIELD_BY_TYPE[record_type]

    previous_state = record.get(state_field)

    if previous_state != "needs_review":

        raise DraftingReviewError(
            f"{record_type} '{record_id}' için geçiş yalnız 'needs_review' kaynak "
            f"durumundan başlayabilir (mevcut durum: '{previous_state}')."
        )

    if record_type == "section" and target_state == "confirmed":

        stale = check_stale_sources(case_id, analysis, record)

        if stale:

            raise DraftingReviewError(
                f"Section '{record_id}' CONFIRM edilemedi: aşağıdaki kaynak(lar) "
                f"artık hard-deny/kullanılamaz durumda (stale_source_now_denied): {stale}"
            )

    backup_path = backup_canonical(canonical_path, audit_dir)

    try:

        record[state_field] = target_state

        atomic_write_json(canonical_path, analysis)

        validation = validate_drafting_analysis(
            drafting_path=canonical_path, expected_case_id=case_id, raise_on_error=True,
        )

        if validation.get("valid") is not True:

            raise DraftingReviewError("Post-review Drafting Validator valid=False.")

        post_sha256 = sha256_file(canonical_path)

        audit_path = write_review_audit(
            audit_dir, case_id, analysis.get("drafting_analysis_id"), record_type, record_id,
            previous_state, target_state, reviewer_ref, review_note, pre_sha256, post_sha256, backup_path,
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
        "validation": validation,
    }


# ============================================================
# REAL TREE SNAPSHOT INVARIANT
# ============================================================

def snapshot_real_drafting_tree(case_id):

    real_dir = CASES_DIR / case_id / "drafting"

    if not real_dir.exists():

        return {"dir_exists": False, "files": {}, "subdirs": []}

    files = {}

    for path in sorted(real_dir.rglob("*")):

        if path.is_file():

            files[str(path.relative_to(real_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()

    subdirs = sorted(str(path.relative_to(real_dir)) for path in real_dir.rglob("*") if path.is_dir())

    return {"dir_exists": True, "files": files, "subdirs": subdirs}


def assert_real_drafting_tree_unchanged(case_id, before_snapshot, label):

    after_snapshot = snapshot_real_drafting_tree(case_id)

    assert after_snapshot == before_snapshot, (
        f"{label}: gerçek Row 15 drafting dizini self-test sırasında DEĞİŞTİ "
        f"(leakage şüphesi).\nÖnce: {before_snapshot}\nSonra: {after_snapshot}"
    )


# ============================================================
# SELF TEST (izole tempdir)
# ============================================================

def run_self_test():

    import tempfile

    from drafting_agent import FakeDraftingLLMClient
    from drafting_engine import build_drafting_engine_output

    print()
    print("======================================")
    print(" VERGİ AI - DRAFTING REVIEW V1 (SELF-TEST)")
    print("======================================")

    case_id = "case_0001"

    real_tree_before = snapshot_real_drafting_tree(case_id)

    temp_dir = tempfile.TemporaryDirectory(prefix="drafting_review_selftest_")

    canonical_path = Path(temp_dir.name) / "drafting.json"

    audit_dir = Path(temp_dir.name) / "reviews" / "drafting_reviews"

    # case_0001'deki fact 'unverified'dır (26/26) - flagged bir referans
    # için claim_span İÇİNDE bir HEDGE_PHRASES ifadesi ZORUNLUDUR (madde F/C).
    SECTION_TEXT_HEDGED = (
        "Dogrulanmamis bilgiye gore, vergi incelemesine iliskin rapor "
        "numarasi kayitlara gecmistir."
    )

    section_response = json.dumps([
        {
            "source_issue_id": "issue_001", "section_type": "facts_summary",
            "section_text": SECTION_TEXT_HEDGED,
            "refs": [
                {
                    "source_field": "source_fact_ids",
                    "source_id": "fact_dava_dilekcesi_001_llm_v1_3_20260901_130225_003",
                    "rendering_mode": "paraphrase", "claim_span": SECTION_TEXT_HEDGED,
                },
            ],
        }
    ], ensure_ascii=False)

    client = FakeDraftingLLMClient(response_sequence=[section_response, "[]"])

    real_result = build_drafting_engine_output(
        case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
        use_agent=True, llm_client=client, network_allowed=False,
    )

    real_analysis = real_result["analysis"]

    atomic_write_json(canonical_path, real_analysis)

    try:

        section_id = real_analysis["draft_sections"][0]["section_id"]

        result1 = apply_review_transition(
            case_id, "section", section_id, "confirmed", "reviewer_a", "note",
            canonical_path=canonical_path, audit_dir=audit_dir,
        )

        assert result1["new_state"] == "confirmed"

        print("T01 Section confirmed via real Layer B transition (no stale sources):", "PASS")

        raised = False

        try:

            apply_review_transition(
                case_id, "section", section_id, "rejected", "reviewer_b", "note",
                canonical_path=canonical_path, audit_dir=audit_dir,
            )

        except DraftingReviewError:

            raised = True

        assert raised is True

        print("T02 Re-transition from terminal state rejected:", "PASS")

        audit = load_json(result1["audit_path"])

        assert audit["reviewer_ref"] == "reviewer_a"
        assert audit["previous_state"] == "needs_review"
        assert audit["new_state"] == "confirmed"
        assert audit["pre_sha256"] == result1["pre_sha256"]
        assert audit["post_sha256"] == result1["post_sha256"]

        print("T03 Review audit fields (reviewer_ref/previous_state/new_state/pre-post SHA256):", "PASS")

        # ---- T04: suggestion independent lifecycle ----

        sug_analysis = json.loads(json.dumps(real_analysis))

        sug_analysis["draft_agent_suggestions"] = [
            {
                "suggestion_id": "drafting_suggestion_001", "source_issue_id": "issue_001",
                "related_reference_ids": [], "suggestion_type": "additional_review_needed",
                "reason_code": "general_contextual_relevance", "grounded_explanation": "Ek inceleme faydali olabilir.",
                "suggestion_review_state": "needs_review", "requires_human_review": True, "status": "candidate",
            }
        ]

        atomic_write_json(canonical_path, sug_analysis)

        result_sug = apply_review_transition(
            case_id, "suggestion", "drafting_suggestion_001", "accepted_for_follow_up", "reviewer_a", "note",
            canonical_path=canonical_path, audit_dir=audit_dir,
        )

        assert result_sug["new_state"] == "accepted_for_follow_up"

        print("T04 Suggestion accepted_for_follow_up (independent lifecycle, no parent):", "PASS")

        # ---- T05: STALE-SOURCE REJECTION AT CONFIRM TIME ----

        stale_analysis = json.loads(json.dumps(real_analysis))

        stale_analysis["draft_sections"][0]["section_id"] = "draft_section_stale_test"

        stale_analysis["draft_source_refs"][0]["section_id"] = "draft_section_stale_test"

        # var olmayan bir fact_id'ye referans - artık "hard-deny" (yok) sayılmalı
        stale_analysis["draft_source_refs"][0]["source_id"] = "fact_does_not_exist_anymore_999"

        atomic_write_json(canonical_path, stale_analysis)

        raised2 = False

        try:

            apply_review_transition(
                case_id, "section", "draft_section_stale_test", "confirmed", "reviewer_a", "note",
                canonical_path=canonical_path, audit_dir=audit_dir,
            )

        except DraftingReviewError as error:

            raised2 = True

            assert "stale_source_now_denied" in str(error)

        assert raised2 is True

        print("T05 Stale/now-hard-denied source blocks section confirmation at review time:", "PASS")

        # ================================================================
        # REMEDIATION - MADDE 5/A: is_source_still_eligible FACT DALININ
        # GERÇEK fact->document BAĞLANTISINI VE GÜNCEL active=true
        # KOŞULUNU DOĞRULAMASI (yalnız stale-hash/allowlist backstop'una
        # değil, DEDİKE helper'ın KENDİSİNE dayanan doğrudan kanıt)
        # ================================================================

        active_doc_client = FakeDraftingLLMClient(response_sequence=[section_response, "[]"])

        active_doc_result = build_drafting_engine_output(
            case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
            use_agent=True, llm_client=active_doc_client, network_allowed=False,
        )

        active_doc_analysis = active_doc_result["analysis"]

        active_doc_section_id = active_doc_analysis["draft_sections"][0]["section_id"]

        atomic_write_json(canonical_path, active_doc_analysis)

        # ---- T06: belge GERÇEKTEN active=true iken onay ÇALIŞMALI (kontrol) ----

        result_active = apply_review_transition(
            case_id, "section", active_doc_section_id, "confirmed", "reviewer_a", "note",
            canonical_path=canonical_path, audit_dir=audit_dir,
        )

        assert result_active["new_state"] == "confirmed"

        print("T06 Valid confirm succeeds while linked document is genuinely active=true (control):", "PASS")

        # reset for the actual inactive-document test - taze bir engine
        # koşusu (fixture ID uyumsuzluğu/stale not eşleşmesi riskini
        # tamamen ortadan kaldırır)
        active_doc_client2 = FakeDraftingLLMClient(response_sequence=[section_response, "[]"])

        active_doc_result2 = build_drafting_engine_output(
            case_id, lawyer_input={"selected_issue_ids": ["issue_001"]},
            use_agent=True, llm_client=active_doc_client2, network_allowed=False,
        )

        active_doc_analysis2 = active_doc_result2["analysis"]

        active_doc_section_id2 = active_doc_analysis2["draft_sections"][0]["section_id"]

        atomic_write_json(canonical_path, active_doc_analysis2)

        canonical_bytes_before_inactive_attempt = canonical_path.read_bytes()

        canonical_sha_before_inactive_attempt = sha256_file(canonical_path)

        audit_files_before = set(audit_dir.glob("*.review_audit.json")) if audit_dir.exists() else set()

        backup_files_before = set(audit_dir.glob("*.bak")) if audit_dir.exists() else set()

        original_review_baidx = build_active_documents_index

        def fake_active_documents_index_no_doc(cid):

            real_index = original_review_baidx(cid)

            filtered = dict(real_index)

            filtered.pop("dava_dilekcesi_001", None)

            return filtered

        globals()["build_active_documents_index"] = fake_active_documents_index_no_doc

        try:

            raised3 = False

            try:

                apply_review_transition(
                    case_id, "section", active_doc_section_id2, "confirmed", "reviewer_a", "note",
                    canonical_path=canonical_path, audit_dir=audit_dir,
                )

            except DraftingReviewError as error:

                raised3 = True

                assert "stale_source_now_denied" in str(error)

        finally:

            globals()["build_active_documents_index"] = original_review_baidx

        assert raised3 is True, (
            "is_source_still_eligible belge active=false olduğunda onayı ENGELLEMEDİ "
            "(dedike helper hâlâ eksik olabilir)."
        )

        print("T07 Confirm PRE-WRITE rejected when linked document is active=false (dedicated helper, not just backstop):", "PASS")

        canonical_bytes_after_inactive_attempt = canonical_path.read_bytes()

        assert canonical_bytes_after_inactive_attempt == canonical_bytes_before_inactive_attempt, (
            "Başarısız (inactive-document) onay denemesi canonical BAYTLARINI değiştirdi."
        )

        reloaded_after_fail = json.loads(canonical_path.read_text(encoding="utf-8"))

        failed_section = next(
            s for s in reloaded_after_fail["draft_sections"] if s["section_id"] == active_doc_section_id2
        )

        assert failed_section["section_review_state"] == "needs_review", (
            "Başarısız onay denemesi sonrası review_state DEĞİŞMİŞ."
        )

        print("T08 Canonical fixture bytes and review_state UNCHANGED after failed pre-write rejection:", "PASS")

        audit_files_after = set(audit_dir.glob("*.review_audit.json")) if audit_dir.exists() else set()

        backup_files_after = set(audit_dir.glob("*.bak")) if audit_dir.exists() else set()

        assert audit_files_after == audit_files_before, (
            "Başarısız onay için YİNE DE bir başarı audit'i oluşturuldu."
        )

        assert backup_files_after == backup_files_before, (
            "Başarısız onay denemesi (pre-write reddedildiği için) BİLE bir backup dosyası oluşturmamalıydı "
            "(check_stale_sources, backup_canonical'DAN ÖNCE çalışır)."
        )

        print("T09 No success audit AND no backup file created for the rejected (pre-write) approval attempt:", "PASS")

    finally:

        temp_dir.cleanup()

    assert_real_drafting_tree_unchanged(case_id, real_tree_before, "End of self-test")

    print("T10 Real canonical case_0001/drafting/ untouched:", "PASS")

    print()
    print("======================================")
    print(" DRAFTING REVIEW V1: 10/10 SELF-TEST PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Drafting Review V1 (Layer B)")

    parser.add_argument("--case", dest="case_id", default="case_0001")

    parser.add_argument("--record-type", choices=["section", "suggestion"])

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
        args.case_id, args.record_type, args.record_id, action_to_state[args.action], args.reviewer, args.note,
    )

    print("OK:", args.record_type, args.record_id, "->", result["new_state"])
    print("Audit:", result["audit_path"])


if __name__ == "__main__":

    main()
