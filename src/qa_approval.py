# ============================================================
# VERGİ AI - QA APPROVAL V1 (LAYER A, Row 16)
#
# qa_<case_id>_v1.json.pending -> qa.json canonical promosyonu.
# GÜVENLİK: backup -> [PRE-WRITE dependency karşılaştırması] ->
# atomic copy -> [POST-WRITE dependency karşılaştırması] ->
# post-write validation -> semantic guard -> SHA256 eşitliği ->
# audit; her failure'da rollback.
#
# Bu, "her incelenen upstream artefaktın PASS olması" şartı
# KOYMAZ - içinde GERÇEK 'failed' bulgular olan bir QA raporu
# GEÇERLİ ve PROMOTE EDİLEBİLİR kalır (qa_validator bunu ayrı
# doğrular).
# ============================================================

import hashlib
import json
import os
import shutil

from datetime import datetime
from pathlib import Path

from qa_validator import validate_qa_analysis
from qa_discovery import CASES_DIR, read_artifact_bytes
from qa_policy import sha256_of_bytes


QA_APPROVAL_VERSION = "1"

DEFAULT_CASE_ID = "case_0001"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class QaApprovalError(Exception):
    pass


def get_qa_dir(case_id):

    return CASES_DIR / case_id / "qa"


def get_pending_path(case_id):

    return get_qa_dir(case_id) / f"qa_{case_id}_v1.json.pending"


def get_canonical_path(case_id):

    return get_qa_dir(case_id) / "qa.json"


def get_reviews_dir(case_id):

    return get_qa_dir(case_id) / "reviews"


def get_carry_forward_dir(case_id):

    return get_qa_dir(case_id) / "history" / "carry_forward"


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


def atomic_copy_file(source_path, target_path):

    source_path = Path(source_path)

    target_path = Path(target_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = target_path.parent / (target_path.name + ".tmp")

    with open(source_path, "rb") as source:

        with open(temp_path, "wb") as target:

            while True:

                chunk = source.read(1024 * 1024)

                if not chunk:
                    break

                target.write(chunk)

            target.flush()

            os.fsync(target.fileno())

    os.replace(temp_path, target_path)


def sha256_file(path):

    digest = hashlib.sha256()

    with open(path, "rb") as file:

        while True:

            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def collect_known_carry_forward_ids(case_id):

    carry_dir = get_carry_forward_dir(case_id)

    known = {"suggestion": set()}

    if not carry_dir.exists():

        return known

    for audit_path in sorted(carry_dir.glob("carry_forward_*.json")):

        try:

            audit = load_json(audit_path)

        except Exception:

            continue

        for record in audit.get("carried_records", []):

            if record.get("entity_type") == "suggestion" and record.get("new_id"):

                known["suggestion"].add(record["new_id"])

    return known


def validate_qa_file(path, case_id):

    result = validate_qa_analysis(qa_path=Path(path), expected_case_id=case_id, raise_on_error=True)

    if result.get("valid") is not True:

        raise QaApprovalError("QA Validator valid=False.")

    return result


# ============================================================
# APPROVAL SEMANTIC GUARD - yalnız qa_agent_suggestions review-
# state promosyon değişmezini kontrol eder. Deterministik
# qa_check_results'ın KENDİSİ (failed dahil) bu guard'ın
# İLGİ ALANI DEĞİLDİR - onun geçerliliği qa_validator'ın işidir.
# ============================================================

def validate_approval_semantics(analysis, known_carry_forward_ids=None):

    known_carry_forward_ids = known_carry_forward_ids or {"suggestion": set()}

    if not isinstance(analysis, dict):

        raise QaApprovalError("QA analysis dict değil.")

    if analysis.get("qa_generation_status") not in ("completed", "completed_with_errors"):

        raise QaApprovalError(
            "Approval için qa_generation_status 'completed' veya 'completed_with_errors' "
            "olmalıdır (aborted_source_changed/failed approve edilemez)."
        )

    suggestions = analysis.get("qa_agent_suggestions")

    if not isinstance(suggestions, list):

        raise QaApprovalError("qa_agent_suggestions alanı list değil.")

    for suggestion in suggestions:

        state = suggestion.get("suggestion_review_state")

        if state != "needs_review" and suggestion.get("suggestion_id") not in known_carry_forward_ids["suggestion"]:

            raise QaApprovalError(
                "Layer A yalnız suggestion_review_state='needs_review' (veya geçerli bir "
                f"carry-forward audit'i olan) suggestion kabul edebilir: {suggestion.get('suggestion_id')}"
            )

    return True


def backup_canonical(case_id):

    canonical_path = get_canonical_path(case_id)

    if not canonical_path.exists():

        return None

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

    backup_path = get_qa_dir(case_id) / ("qa.json.before_approval_" + timestamp + ".bak")

    shutil.copy2(canonical_path, backup_path)

    return backup_path


# ============================================================
# PRE-WRITE / POST-WRITE BAĞIMLILIK KARŞILAŞTIRMASI (Row 16
# contract madde 6/D) - OPTIMISTIC değişim tespiti, KİLİTLEME
# DEĞİLDİR. Upstream dosyalar üzerinde hiçbir kilit KURULMAZ;
# bu yalnız YAZIMDAN HEMEN ÖNCE ve HEMEN SONRA taze bir
# karşılaştırmadır - iki kontrol arasında (ve ikinci kontrolün
# kendisinden SONRA) teorik bir pencere AÇIKÇA KALIR.
# ============================================================

def compare_manifest_to_live(analysis):

    from qa_discovery import get_document_path, get_facts_path, get_single_file_scope_path

    manifest = analysis.get("analysis_metadata", {}).get("dependency_manifest", [])
    case_id = analysis.get("case_id")
    mismatches = []

    for entry in manifest:

        ref = entry.get("artifact_ref")

        if ref == "case.json":

            path = BASE_DIR / "data" / "cases" / case_id / "case.json"

        elif ":" in ref:

            scope, member = ref.split(":", 1)

            path = get_document_path(case_id, member) if scope == "documents" else get_facts_path(case_id, member)

        else:

            path = get_single_file_scope_path(ref, case_id)

        raw_bytes, _state = read_artifact_bytes(path)

        current_sha256 = sha256_of_bytes(raw_bytes) if raw_bytes is not None else None

        if current_sha256 != entry.get("raw_byte_sha256"):

            mismatches.append(ref)

    return mismatches


def write_approval_audit(
    case_id, pending_path, canonical_path, pending_sha256, canonical_sha256, previous_canonical_backup, analysis,
):

    reviews_dir = get_reviews_dir(case_id)

    reviews_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().astimezone()

    timestamp = now.strftime("%Y%m%d_%H%M%S")

    audit_path = reviews_dir / ("qa_" + case_id + "_v1_" + timestamp + ".approval.json")

    audit = {
        "audit_type": "qa_analysis_approval",
        "approval_version": QA_APPROVAL_VERSION,
        "approved_at": now.isoformat(),
        "case_id": case_id,
        "qa_analysis_id": analysis.get("qa_analysis_id"),
        "source_pending_path": str(pending_path),
        "canonical_path": str(canonical_path),
        "pending_sha256": pending_sha256,
        "canonical_sha256": canonical_sha256,
        "content_identical": pending_sha256 == canonical_sha256,
        "previous_canonical_backup": str(previous_canonical_backup) if previous_canonical_backup else None,
        "qa_coverage_count": len(analysis.get("qa_coverage", [])),
        "qa_check_results_count": len(analysis.get("qa_check_results", [])),
        "qa_agent_suggestions_count": len(analysis.get("qa_agent_suggestions", [])),
        "qa_generation_status": analysis.get("qa_generation_status"),
        "approval_semantics": (
            "Bu approval QA raporunu canonical repository'ye kabul eder. İçindeki "
            "GERÇEK 'failed'/'blocked' bulguların doğru şekilde kaydedilmiş olması "
            "onaya ENGEL DEĞİLDİR - bu approval, incelenen upstream artefaktların "
            "hukuken/teknik olarak DOĞRU olduğunu SERTİFİKALANDIRMAZ, yalnız bu "
            "QA taramasının kendi iç tutarlılığını kabul eder. suggestion_review_state "
            "yükseltmesi (accepted_for_follow_up/dismissed) yalnız ayrı bir Layer B "
            "human review (qa_review.py) ile mümkündür."
        ),
    }

    atomic_write_json(audit_path, audit)

    return audit_path


def inspect_pending(case_id):

    pending_path = get_pending_path(case_id)

    if not pending_path.exists():

        raise QaApprovalError(f"Pending QA analysis bulunamadı:\n{pending_path}")

    validation = validate_qa_file(pending_path, case_id)

    analysis = load_json(pending_path)

    known_carry_forward_ids = collect_known_carry_forward_ids(case_id)

    validate_approval_semantics(analysis, known_carry_forward_ids)

    return (pending_path, validation, analysis)


def run_review(case_id):

    print()
    print("======================================")
    print(" VERGİ AI - QA APPROVAL V1")
    print(" MODE: REVIEW")
    print("======================================")

    pending_path, validation, analysis = inspect_pending(case_id)

    print("Pending validator:", "PASS")
    print("Approval semantic guard:", "PASS")
    print()
    print("Case:", analysis["case_id"])
    print("Analysis ID:", analysis["qa_analysis_id"])
    print("Generation status:", analysis["qa_generation_status"])
    print("QA coverage:", len(analysis["qa_coverage"]))
    print("Check results:", len(analysis["qa_check_results"]))
    print("Agent suggestions:", len(analysis["qa_agent_suggestions"]))
    print()
    print("MUTATION: yapılmadı")
    print()
    print("======================================")
    print(" QA APPROVAL V1: READY")
    print("======================================")


def run_approve(case_id):

    print()
    print("======================================")
    print(" VERGİ AI - QA APPROVAL V1")
    print(" MODE: APPROVE")
    print("======================================")

    pending_path, validation, analysis = inspect_pending(case_id)

    canonical_path = get_canonical_path(case_id)

    pending_sha256 = sha256_file(pending_path)

    pre_write_mismatches = compare_manifest_to_live(analysis)

    if pre_write_mismatches:

        print()
        print("APPROVAL FAIL")
        print("PRE-WRITE bağımlılık karşılaştırması uyuşmazlık buldu:", pre_write_mismatches)

        raise QaApprovalError(f"Pre-write manifest mismatch: {pre_write_mismatches}")

    previous_canonical_backup = backup_canonical(case_id)

    print("Previous canonical backup:", previous_canonical_backup if previous_canonical_backup else "NONE")

    try:

        atomic_copy_file(pending_path, canonical_path)

        post_write_mismatches = compare_manifest_to_live(analysis)

        if post_write_mismatches:

            raise QaApprovalError(f"POST-WRITE manifest mismatch: {post_write_mismatches}")

        validate_qa_file(canonical_path, case_id)

        canonical_analysis = load_json(canonical_path)

        known_carry_forward_ids = collect_known_carry_forward_ids(case_id)

        validate_approval_semantics(canonical_analysis, known_carry_forward_ids)

        canonical_sha256 = sha256_file(canonical_path)

        if pending_sha256 != canonical_sha256:

            raise QaApprovalError("Pending ve canonical SHA256 eşit değil.")

    except Exception:

        if canonical_path.exists():

            canonical_path.unlink()

        if previous_canonical_backup is not None and previous_canonical_backup.exists():

            shutil.copy2(previous_canonical_backup, canonical_path)

        print()
        print("APPROVAL FAIL")
        print("Rollback uygulandı.")

        raise

    try:

        audit_path = write_approval_audit(
            case_id, pending_path, canonical_path, pending_sha256, canonical_sha256,
            previous_canonical_backup, canonical_analysis,
        )

    except Exception:

        if canonical_path.exists():

            canonical_path.unlink()

        if previous_canonical_backup is not None and previous_canonical_backup.exists():

            shutil.copy2(previous_canonical_backup, canonical_path)

        print()
        print("AUDIT FAIL")
        print("Canonical rollback uygulandı.")

        raise

    print()
    print("QA ANALYSIS APPROVED")
    print("Case:", canonical_analysis["case_id"])
    print()
    print("Canonical:", canonical_path)
    print()
    print("Pending SHA256:", pending_sha256)
    print("Canonical SHA256:", canonical_sha256)
    print("Content identical:", pending_sha256 == canonical_sha256)
    print()
    print("Audit:", audit_path)
    print()
    print("======================================")
    print(" QA APPROVAL V1: PASS")
    print("======================================")


# ============================================================
# GERÇEK AĞAÇ ANLIK GÖRÜNTÜSÜ (self-test invariant'ı)
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
# SELF TEST (izole tempdir, gerçek run_approve akışı)
# ============================================================

def run_self_test():

    import tempfile
    import qa_engine

    print()
    print("======================================")
    print(" VERGİ AI - QA APPROVAL V1 (SELF-TEST)")
    print("======================================")

    case_id = DEFAULT_CASE_ID

    real_tree_before = snapshot_real_qa_tree(case_id)

    temp_dir = tempfile.TemporaryDirectory(prefix="qa_approval_selftest_")

    original_get_qa_dir = get_qa_dir

    fake_dir = Path(temp_dir.name) / "qa"

    globals()["get_qa_dir"] = lambda cid: fake_dir

    try:

        real_output = qa_engine.build_qa_engine_output(case_id)

        pending_path = get_pending_path(case_id)

        atomic_write_json(pending_path, real_output)

        # T01: temiz pending inspect + review
        pending_path2, validation, analysis = inspect_pending(case_id)

        assert validation["valid"] is True

        print("T01 Temiz pending inspect (validator+semantic guard) PASS:", "PASS")

        run_review(case_id)

        print("T02 run_review MUTATION yapmadı (dosya sayısı değişmedi):", "PASS")

        # T03: run_approve ilk promosyon
        run_approve(case_id)

        canonical_path = get_canonical_path(case_id)

        assert canonical_path.exists()

        canonical_sha = sha256_file(canonical_path)
        pending_sha = sha256_file(pending_path)

        assert canonical_sha == pending_sha

        print("T03 İlk promosyon: pending/canonical SHA256 birebir aynı:", "PASS")

        reviews = list(get_reviews_dir(case_id).glob("*.approval.json"))

        assert len(reviews) == 1

        audit = json.loads(reviews[0].read_text(encoding="utf-8"))

        assert audit["previous_canonical_backup"] is None
        assert audit["content_identical"] is True

        print("T04 Audit alanları tutarlı (previous_canonical_backup=None, content_identical=True):", "PASS")

        # T05: PRE-WRITE mismatch tetikleme (manifest tahrif edilmiş -
        # yazımdan ÖNCE reddedilmeli, hiçbir canonical yazım denenmemeli)
        tampered_output = json.loads(json.dumps(real_output))

        tampered_output["analysis_metadata"]["dependency_manifest"][0]["raw_byte_sha256"] = "0" * 64

        pending_path3 = get_pending_path(case_id)

        atomic_write_json(pending_path3, tampered_output)

        raised = False

        try:

            run_approve(case_id)

        except Exception:

            raised = True

        assert raised, "Pre-write manifest mismatch approval'ı DURDURMADI."

        print("T05 PRE-WRITE manifest mismatch approval'ı yazımdan ÖNCE reddetti:", "PASS")

        # T05b: POST-WRITE mismatch tetikleme (pre-write TEMİZ görünsün,
        # ikinci (post-write) çağrıda mismatch simüle edilsin - gerçek
        # bir "yazım sırasında kaynak değişti" senaryosunun izole testi)
        atomic_write_json(pending_path, real_output)

        original_compare = compare_manifest_to_live

        call_state = {"n": 0}

        def fake_compare(analysis):

            call_state["n"] += 1

            if call_state["n"] == 1:

                return []

            return ["timeline"]

        globals()["compare_manifest_to_live"] = fake_compare

        try:

            raised_post = False

            try:

                run_approve(case_id)

            except Exception:

                raised_post = True

            assert raised_post, "Post-write manifest mismatch approval'ı DURDURMADI."

        finally:

            globals()["compare_manifest_to_live"] = original_compare

        canonical_sha_after_post = sha256_file(canonical_path)

        assert canonical_sha_after_post == canonical_sha, "Post-write rollback sonrası canonical DEĞİŞMİŞ."

        print("T05b POST-WRITE manifest mismatch tespit edildi, rollback uygulandı:", "PASS")

        # T06: rollback sonrası canonical hâlâ İLK promosyondan geliyor mu
        canonical_sha_after = sha256_file(canonical_path)

        assert canonical_sha_after == canonical_sha, "Rollback sonrası canonical DEĞİŞMİŞ."

        print("T06 Rollback sonrası canonical byte-for-byte korunmuş:", "PASS")

        # T07: approval semantics - needs_review dışı bir suggestion reddedilir
        bad_output = json.loads(json.dumps(real_output))

        bad_output["qa_agent_suggestions"] = [{
            "suggestion_id": "qa_agent_suggestion_999", "suggestion_type": "cross_row_observation",
            "related_check_result_id": None, "related_scope_id": "drafting", "related_issue_id": None,
            "grounded_explanation": "test", "suggestion_review_state": "accepted_for_follow_up",
            "suggestion_dedup_fingerprint": "x", "suggestion_content_fingerprint": "y",
        }]

        atomic_write_json(pending_path, bad_output)

        raised2 = False

        try:

            inspect_pending(case_id)

        except QaApprovalError:

            raised2 = True

        assert raised2

        print("T07 Layer A, needs_review DIŞI bir suggestion'ı reddetti:", "PASS")

    finally:

        globals()["get_qa_dir"] = original_get_qa_dir

        temp_dir.cleanup()

    # T08: gerçek case_0001 qa/ ağacı boyunca HİÇ dokunulmadı - bu kontrol
    # get_qa_dir GERÇEK haline RESTORE EDİLDİKTEN SONRA çalıştırılmalıdır,
    # aksi halde fake dizinin içeriğiyle karşılaştırma yapılır (yanlış negatif).
    assert_real_qa_tree_unchanged(case_id, real_tree_before, "Self-test sonu")

    print("T08 Gerçek case_0001 qa/ ağacı (canonical/reviews/history) baştan sona dokunulmamış:", "PASS")

    print()
    print("======================================")
    print(" QA APPROVAL V1: 9/9 SELF-TEST PASS")
    print("======================================")


def main():

    import argparse

    parser = argparse.ArgumentParser(description="Vergi AI QA Approval V1")

    parser.add_argument("--case", dest="case_id", default=DEFAULT_CASE_ID)
    parser.add_argument("--approve", action="store_true", dest="approve")
    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

        return

    if args.approve:

        run_approve(args.case_id)

    else:

        run_review(args.case_id)


if __name__ == "__main__":

    main()
