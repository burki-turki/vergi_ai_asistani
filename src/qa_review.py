# ============================================================
# VERGİ AI - QA REVIEW V1 (LAYER B, Row 16)
#
# YALNIZ qa_agent_suggestions[].suggestion_review_state geçişini
# yapar: needs_review -> accepted_for_follow_up | dismissed.
# Bu, HİÇBİR deterministik qa_check_results kaydını DEĞİŞTİRMEZ
# ve HİÇBİR upstream veriye MUTATION UYGULAMAZ - Layer B'nin
# ilgi alanı KESİN OLARAK suggestion review lifecycle'ı ile
# SINIRLIDIR (Row 16 contract, madde 3/7).
# ============================================================

import hashlib
import json
import shutil

from datetime import datetime
from pathlib import Path

from qa_approval import get_qa_dir, get_canonical_path
from qa_validator import validate_qa_analysis


QA_REVIEW_VERSION = "1"

ALLOWED_TARGET_STATES = {"accepted_for_follow_up", "dismissed"}


class QaReviewError(Exception):
    pass


def get_qa_review_audit_dir(case_id):

    return get_qa_dir(case_id) / "reviews" / "qa_reviews"


def load_json(path):

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


def atomic_write_json(path, data):

    import os

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

    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def backup_canonical(canonical_path, audit_dir):

    audit_dir = Path(audit_dir)

    audit_dir.mkdir(parents=True, exist_ok=True)

    backup_path = audit_dir / (Path(canonical_path).name + ".before_review_" + now_stamp() + ".bak")

    shutil.copy2(canonical_path, backup_path)

    return backup_path


def find_suggestion(analysis, suggestion_id):

    for record in analysis.get("qa_agent_suggestions", []):

        if record.get("suggestion_id") == suggestion_id:

            return record

    return None


def write_review_audit(
    audit_dir, case_id, qa_analysis_id, suggestion_id, previous_state, new_state,
    reviewer_ref, review_note, pre_sha256, post_sha256, backup_path,
):

    audit_dir = Path(audit_dir)

    audit_dir.mkdir(parents=True, exist_ok=True)

    audit_path = audit_dir / ("qa_review_" + suggestion_id + "_" + now_stamp() + ".review_audit.json")

    audit = {
        "audit_type": "qa_suggestion_review",
        "review_version": QA_REVIEW_VERSION,
        "case_id": case_id,
        "qa_analysis_id": qa_analysis_id,
        "record_type": "suggestion",
        "record_id": suggestion_id,
        "previous_state": previous_state,
        "new_state": new_state,
        "reviewer_ref": reviewer_ref,
        "reviewed_at": now_iso(),
        "review_note": review_note,
        "pre_sha256": pre_sha256,
        "post_sha256": post_sha256,
        "canonical_backup": str(backup_path),
        "review_semantics": (
            "Bu geçiş yalnız bir QA agent suggestion'ının insan tarafından "
            "incelendiğini gösterir. Hiçbir deterministik qa_check_results "
            "kaydını DEĞİŞTİRMEZ, hiçbir ihlali 'çözüldü' İLAN ETMEZ, hiçbir "
            "upstream veriye MUTATION UYGULAMAZ."
        ),
    }

    atomic_write_json(audit_path, audit)

    return audit_path


def apply_review_transition(case_id, suggestion_id, target_state, reviewer_ref, review_note,
                             canonical_path=None, audit_dir=None):

    if target_state not in ALLOWED_TARGET_STATES:

        raise QaReviewError(f"Geçersiz hedef durum: {target_state} (izin verilen: {sorted(ALLOWED_TARGET_STATES)})")

    canonical_path = Path(canonical_path if canonical_path is not None else get_canonical_path(case_id))

    audit_dir = Path(audit_dir if audit_dir is not None else get_qa_review_audit_dir(case_id))

    if not canonical_path.exists():

        raise QaReviewError(f"Canonical qa.json bulunamadı:\n{canonical_path}")

    pre_sha256 = sha256_file(canonical_path)

    analysis = load_json(canonical_path)

    record = find_suggestion(analysis, suggestion_id)

    if record is None:

        raise QaReviewError(f"suggestion bulunamadı: {suggestion_id}")

    previous_state = record.get("suggestion_review_state")

    if previous_state != "needs_review":

        raise QaReviewError(
            f"suggestion '{suggestion_id}' için geçiş yalnız 'needs_review' kaynak "
            f"durumundan başlayabilir (mevcut durum: '{previous_state}')."
        )

    deterministic_snapshot_before = json.dumps(analysis.get("qa_check_results", []), sort_keys=True)

    backup_path = backup_canonical(canonical_path, audit_dir)

    try:

        record["suggestion_review_state"] = target_state

        atomic_write_json(canonical_path, analysis)

        deterministic_snapshot_after = json.dumps(
            load_json(canonical_path).get("qa_check_results", []), sort_keys=True,
        )

        if deterministic_snapshot_before != deterministic_snapshot_after:

            raise QaReviewError(
                "İÇ TUTARLILIK İHLALİ: qa_check_results Layer B review sırasında DEĞİŞTİ "
                "(bu ASLA olmamalıydı - Layer B yalnız suggestion review_state'ine dokunur)."
            )

        validation = validate_qa_analysis(qa_path=canonical_path, expected_case_id=case_id, raise_on_error=True)

        if validation.get("valid") is not True:

            raise QaReviewError("Post-review QA Validator valid=False.")

        post_sha256 = sha256_file(canonical_path)

        audit_path = write_review_audit(
            audit_dir, case_id, analysis.get("qa_analysis_id"), suggestion_id,
            previous_state, target_state, reviewer_ref, review_note, pre_sha256, post_sha256, backup_path,
        )

    except Exception:

        shutil.copy2(backup_path, canonical_path)

        raise

    return {
        "canonical_path": canonical_path, "backup_path": backup_path, "audit_path": audit_path,
        "pre_sha256": pre_sha256, "post_sha256": post_sha256,
        "previous_state": previous_state, "new_state": target_state, "validation": validation,
    }


# ============================================================
# REAL TREE SNAPSHOT INVARIANT
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


def assert_real_qa_tree_unchanged(case_id, before_snapshot, label):

    after_snapshot = snapshot_real_qa_tree(case_id)

    assert after_snapshot == before_snapshot, (
        f"{label}: gerçek Row 16 qa dizini self-test sırasında DEĞİŞTİ "
        f"(leakage şüphesi).\nÖnce: {before_snapshot}\nSonra: {after_snapshot}"
    )


# ============================================================
# SELF TEST
# ============================================================

def run_self_test():

    import tempfile
    import qa_engine
    import qa_approval

    print()
    print("======================================")
    print(" VERGİ AI - QA REVIEW V1 (SELF-TEST)")
    print("======================================")

    case_id = "case_0001"

    real_tree_before = snapshot_real_qa_tree(case_id)

    temp_dir = tempfile.TemporaryDirectory(prefix="qa_review_selftest_")

    fake_dir = Path(temp_dir.name) / "qa"

    original_get_qa_dir_approval = qa_approval.get_qa_dir

    qa_approval.get_qa_dir = lambda cid: fake_dir

    globals()["get_qa_dir"] = lambda cid: fake_dir

    try:

        real_output = qa_engine.build_qa_engine_output(case_id)

        real_output["qa_agent_suggestions"] = [{
            "suggestion_id": "qa_agent_suggestion_001", "suggestion_type": "needs_deeper_human_review",
            "related_check_result_id": real_output["qa_check_results"][0]["check_result_id"],
            "related_scope_id": real_output["qa_check_results"][0]["scope_id"],
            "related_issue_id": None, "grounded_explanation": "Test amaçlı bir gözlem.",
            "suggestion_review_state": "needs_review",
            "suggestion_dedup_fingerprint": "dedup_test_001",
            "suggestion_content_fingerprint": "content_test_001",
        }]

        pending_path = qa_approval.get_pending_path(case_id)

        qa_approval.atomic_write_json(pending_path, real_output)

        qa_approval.run_approve(case_id)

        canonical_path = get_canonical_path(case_id)

        pre_sha = sha256_file(canonical_path)

        # T01: needs_review DIŞI bir kaynak durumdan geçiş reddedilir
        raised = False

        try:

            apply_review_transition(case_id, "qa_agent_suggestion_001", "confirmed", "test_reviewer", "not")

        except QaReviewError:

            raised = True

        assert raised, "Geçersiz hedef state ('confirmed') reddedilmedi."

        print("T01 Geçersiz hedef durum (confirmed) reddedildi:", "PASS")

        # T02: gerçek geçiş - accepted_for_follow_up
        result = apply_review_transition(
            case_id, "qa_agent_suggestion_001", "accepted_for_follow_up", "test_reviewer", "izlemeye alındı",
        )

        assert result["new_state"] == "accepted_for_follow_up"

        print("T02 needs_review -> accepted_for_follow_up geçişi başarılı:", "PASS")

        # T03: canonical DİSKTEN yeniden okunup değişikliğin GERÇEKTEN
        # kalıcı olduğu doğrulanır (bellekte tutulan referansa güvenilmez)
        reloaded = json.loads(canonical_path.read_text(encoding="utf-8"))

        assert reloaded["qa_agent_suggestions"][0]["suggestion_review_state"] == "accepted_for_follow_up"

        print("T03 Disk'ten yeniden okuma ile review_state kalıcılığı doğrulandı:", "PASS")

        # T04: deterministik qa_check_results BİREBİR aynı kaldı
        assert reloaded["qa_check_results"] == real_output["qa_check_results"]

        print("T04 qa_check_results Layer B review sırasında DEĞİŞMEDİ:", "PASS")

        # T05: aynı suggestion'a İKİNCİ kez geçiş denemesi reddedilir
        # (artık needs_review DEĞİL)
        raised2 = False

        try:

            apply_review_transition(case_id, "qa_agent_suggestion_001", "dismissed", "test_reviewer", "tekrar")

        except QaReviewError:

            raised2 = True

        assert raised2, "Zaten terminal durumdaki suggestion tekrar review edildi."

        print("T05 Terminal durumdaki suggestion tekrar review edilemedi:", "PASS")

        # T06: post-review validator PASS (audit dosyası oluştu)
        review_audit_dir = get_qa_review_audit_dir(case_id)

        audits = list(review_audit_dir.glob("*.review_audit.json"))

        assert len(audits) == 1

        print("T06 Layer B audit kaydı oluşturuldu, post-review validator PASS:", "PASS")

        # T07: bilinmeyen suggestion_id reddedilir
        raised3 = False

        try:

            apply_review_transition(case_id, "qa_agent_suggestion_999", "dismissed", "x", "y")

        except QaReviewError:

            raised3 = True

        assert raised3

        print("T07 Bilinmeyen suggestion_id reddedildi:", "PASS")

    finally:

        qa_approval.get_qa_dir = original_get_qa_dir_approval

        globals()["get_qa_dir"] = original_get_qa_dir_approval

        temp_dir.cleanup()

    assert_real_qa_tree_unchanged(case_id, real_tree_before, "Self-test sonu")

    print("T08 Gerçek case_0001 qa/ ağacı baştan sona dokunulmamış:", "PASS")

    print()
    print("======================================")
    print(" QA REVIEW V1: 8/8 SELF-TEST PASS")
    print("======================================")


def main():

    import argparse

    parser = argparse.ArgumentParser(description="Vergi AI QA Review V1")

    parser.add_argument("--case", dest="case_id", default="case_0001")
    parser.add_argument("--suggestion-id", dest="suggestion_id")
    parser.add_argument("--target-state", dest="target_state", choices=sorted(ALLOWED_TARGET_STATES))
    parser.add_argument("--reviewer", dest="reviewer_ref", default="unknown")
    parser.add_argument("--note", dest="review_note", default="")
    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

        return

    if not args.suggestion_id or not args.target_state:

        raise SystemExit("--suggestion-id ve --target-state zorunludur.")

    result = apply_review_transition(
        args.case_id, args.suggestion_id, args.target_state, args.reviewer_ref, args.review_note,
    )

    print("QA REVIEW: PASS")
    print(result)


if __name__ == "__main__":

    main()
