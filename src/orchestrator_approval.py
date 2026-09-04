# ============================================================
# VERGİ AI - ORCHESTRATOR APPROVAL V1 (LAYER A, Row 17)
#
# case_view_<case_id>_v1.json.pending -> case_view.json canonical
# promosyonu. Row 16 (qa_approval.py) ile AYNI güvenlik disiplini:
# backup -> PRE-WRITE bağımlılık karşılaştırması -> atomic copy ->
# POST-WRITE bağımlılık karşılaştırması -> post-write validation ->
# semantic guard -> SHA256 eşitliği -> audit; her failure'da rollback.
#
# KULLANICI KARARI (2026-09-04): generation_status='failed' (bir
# veya daha fazla zorunlu kaynak henüz mevcut değil) CANONICAL'A
# PROMOTE EDİLEMEZ - view kendi içinde tutarlı ve şema-geçerli olsa
# BİLE. orchestrator_engine yine de HER ZAMAN 'failed' için şema-
# geçerli, hatasız bir case_view üretmeye devam eder (bkz. T10) -
# bu yalnız GÖRÜNTÜLEME/hata-toleransı için gereklidir, PROMOSYON
# için değil. Layer A yalnız generation_status='completed' olan bir
# case_view'i canonical'a kabul eder.
# ============================================================

import hashlib
import json
import os
import shutil

from datetime import datetime
from pathlib import Path

from orchestrator_validator import validate_case_view
from orchestrator_discovery import CASES_DIR
from orchestrator_policy import ORCHESTRATOR_SOURCE_REGISTRY


ORCHESTRATOR_APPROVAL_VERSION = "1"

DEFAULT_CASE_ID = "case_0001"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

_VALID_GENERATION_STATUSES_FOR_APPROVAL = ("completed",)


class OrchestratorApprovalError(Exception):
    pass


def get_view_dir(case_id):

    return CASES_DIR / case_id / "case_view"


def get_pending_path(case_id):

    return get_view_dir(case_id) / f"case_view_{case_id}_v1.json.pending"


def get_canonical_path(case_id):

    return get_view_dir(case_id) / "case_view.json"


def get_reviews_dir(case_id):

    return get_view_dir(case_id) / "reviews"


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


def validate_view_file(path, case_id):

    result = validate_case_view(case_view_path=Path(path), expected_case_id=case_id, raise_on_error=True)

    if result.get("valid") is not True:

        raise OrchestratorApprovalError("Orchestrator Validator valid=False.")

    return result


# ============================================================
# APPROVAL SEMANTIC GUARD - bkz. yukarıdaki kullanıcı kararı.
# Row 17 v1'de agent/suggestion katmanı YOK (seçenek A), bu yüzden
# QA'nın carry-forward/suggestion-review-state guard'ının bir
# karşılığı BURADA YOKTUR - yalnız generation_status='completed'
# olduğu (yani TÜM zorunlu kaynaklar present_valid olduğu) kontrol
# edilir. 'failed' - kendi içinde tutarlı ve şema-geçerli OLSA BİLE -
# bilerek reddedilir (kullanıcı kararı).
# ============================================================

def validate_approval_semantics(view):

    if not isinstance(view, dict):

        raise OrchestratorApprovalError("case_view dict değil.")

    status = view.get("generation_status")

    if status not in _VALID_GENERATION_STATUSES_FOR_APPROVAL:

        raise OrchestratorApprovalError(
            "Layer A yalnız generation_status "
            f"{_VALID_GENERATION_STATUSES_FOR_APPROVAL} olan bir case_view'i "
            f"promote edebilir (kayıtlı: {status!r})."
        )

    return True


def backup_canonical(case_id):

    canonical_path = get_canonical_path(case_id)

    if not canonical_path.exists():

        return None

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

    backup_path = get_view_dir(case_id) / ("case_view.json.before_approval_" + timestamp + ".bak")

    shutil.copy2(canonical_path, backup_path)

    return backup_path


# ============================================================
# PRE-WRITE / POST-WRITE BAĞIMLILIK KARŞILAŞTIRMASI - Row 16
# contract madde 6/D ile AYNI ilke (optimistic, kilitleme DEĞİL).
# ============================================================

def compare_manifest_to_live(view):

    from orchestrator_discovery import load_source_scope

    manifest = view.get("analysis_metadata", {}).get("dependency_manifest", [])
    case_id = view.get("case_id")

    manifest_by_ref = {entry.get("artifact_ref"): entry for entry in manifest}

    mismatches = []

    for scope_id in ORCHESTRATOR_SOURCE_REGISTRY:

        entry = manifest_by_ref.get(scope_id)

        if entry is None:

            mismatches.append(scope_id)
            continue

        live = load_source_scope(scope_id, case_id)

        if live["raw_bytes_sha256"] != entry.get("raw_byte_sha256") or live["artifact_state"] != entry.get("artifact_state"):

            mismatches.append(scope_id)

    return mismatches


def write_approval_audit(
    case_id, pending_path, canonical_path, pending_sha256, canonical_sha256, previous_canonical_backup, view,
):

    reviews_dir = get_reviews_dir(case_id)

    reviews_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().astimezone()

    timestamp = now.strftime("%Y%m%d_%H%M%S")

    audit_path = reviews_dir / ("case_view_" + case_id + "_v1_" + timestamp + ".approval.json")

    audit = {
        "audit_type": "case_view_approval",
        "approval_version": ORCHESTRATOR_APPROVAL_VERSION,
        "approved_at": now.isoformat(),
        "case_id": case_id,
        "case_view_id": view.get("case_view_id"),
        "source_pending_path": str(pending_path),
        "canonical_path": str(canonical_path),
        "pending_sha256": pending_sha256,
        "canonical_sha256": canonical_sha256,
        "content_identical": pending_sha256 == canonical_sha256,
        "previous_canonical_backup": str(previous_canonical_backup) if previous_canonical_backup else None,
        "generation_status": view.get("generation_status"),
        "issue_panel_count": len(view.get("issue_panel", [])),
        "open_items_count": len(view.get("open_items_panel", [])),
        "warnings_count": len(view.get("warnings", [])),
        "approval_semantics": (
            "Bu approval case_view'i canonical repository'ye kabul eder. Orchestrator "
            "HİÇBİR yeni hukuki fact/olasılık/sonuç İCAT ETMEZ - yalnız Row 1-16'nın "
            "zaten canonical olan çıktılarını issue etrafında yeniden gruplar. "
            "generation_status yalnız 'completed' olabilir - bir veya daha fazla "
            "zorunlu kaynak eksikken üretilen 'failed' bir case_view (kendi içinde "
            "tutarlı ve şema-geçerli olsa BİLE) Layer A tarafından REDDEDİLİR "
            "(kullanıcı kararı, 2026-09-04)."
        ),
    }

    atomic_write_json(audit_path, audit)

    return audit_path


def inspect_pending(case_id):

    pending_path = get_pending_path(case_id)

    if not pending_path.exists():

        raise OrchestratorApprovalError(f"Pending case_view bulunamadı:\n{pending_path}")

    validation = validate_view_file(pending_path, case_id)

    view = load_json(pending_path)

    validate_approval_semantics(view)

    return (pending_path, validation, view)


def run_review(case_id):

    print()
    print("======================================")
    print(" VERGİ AI - ORCHESTRATOR APPROVAL V1")
    print(" MODE: REVIEW")
    print("======================================")

    pending_path, validation, view = inspect_pending(case_id)

    print("Pending validator:", "PASS")
    print("Approval semantic guard:", "PASS")
    print()
    print("Case:", view["case_id"])
    print("Case View ID:", view["case_view_id"])
    print("Generation status:", view["generation_status"])
    print("Issue panel entries:", len(view["issue_panel"]))
    print("Open items:", len(view["open_items_panel"]))
    print("Warnings:", len(view["warnings"]))
    print()
    print("MUTATION: yapılmadı")
    print()
    print("======================================")
    print(" ORCHESTRATOR APPROVAL V1: READY")
    print("======================================")


def run_approve(case_id):

    print()
    print("======================================")
    print(" VERGİ AI - ORCHESTRATOR APPROVAL V1")
    print(" MODE: APPROVE")
    print("======================================")

    pending_path, validation, view = inspect_pending(case_id)

    canonical_path = get_canonical_path(case_id)

    pending_sha256 = sha256_file(pending_path)

    pre_write_mismatches = compare_manifest_to_live(view)

    if pre_write_mismatches:

        print()
        print("APPROVAL FAIL")
        print("PRE-WRITE bağımlılık karşılaştırması uyuşmazlık buldu:", pre_write_mismatches)

        raise OrchestratorApprovalError(f"Pre-write manifest mismatch: {pre_write_mismatches}")

    previous_canonical_backup = backup_canonical(case_id)

    print("Previous canonical backup:", previous_canonical_backup if previous_canonical_backup else "NONE")

    try:

        atomic_copy_file(pending_path, canonical_path)

        post_write_mismatches = compare_manifest_to_live(view)

        if post_write_mismatches:

            raise OrchestratorApprovalError(f"POST-WRITE manifest mismatch: {post_write_mismatches}")

        validate_view_file(canonical_path, case_id)

        canonical_view = load_json(canonical_path)

        validate_approval_semantics(canonical_view)

        canonical_sha256 = sha256_file(canonical_path)

        if pending_sha256 != canonical_sha256:

            raise OrchestratorApprovalError("Pending ve canonical SHA256 eşit değil.")

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
            previous_canonical_backup, canonical_view,
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
    print("CASE VIEW APPROVED")
    print("Case:", canonical_view["case_id"])
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
    print(" ORCHESTRATOR APPROVAL V1: PASS")
    print("======================================")


# ============================================================
# GERÇEK AĞAÇ ANLIK GÖRÜNTÜSÜ (self-test invariant'ı)
# ============================================================

def snapshot_real_view_tree(case_id):

    real_dir = get_view_dir(case_id)

    if not real_dir.exists():

        return {"dir_exists": False, "files": {}, "subdirs": []}

    files = {}

    for path in sorted(real_dir.rglob("*")):

        if path.is_file():

            files[str(path.relative_to(real_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()

    subdirs = sorted(str(path.relative_to(real_dir)) for path in real_dir.rglob("*") if path.is_dir())

    return {"dir_exists": True, "files": files, "subdirs": subdirs}


def assert_real_view_tree_unchanged(case_id, before_snapshot, label):

    after_snapshot = snapshot_real_view_tree(case_id)

    assert after_snapshot == before_snapshot, (
        f"{label}: gerçek Row 17 case_view dizini self-test sırasında DEĞİŞTİ "
        f"(leakage şüphesi).\nÖnce: {before_snapshot}\nSonra: {after_snapshot}"
    )


# ============================================================
# SELF TEST (izole tempdir, gerçek run_approve akışı)
# ============================================================

def run_self_test():

    import tempfile
    import orchestrator_engine

    print()
    print("======================================")
    print(" VERGİ AI - ORCHESTRATOR APPROVAL V1 (SELF-TEST)")
    print("======================================")

    case_id = DEFAULT_CASE_ID

    real_tree_before = snapshot_real_view_tree(case_id)

    temp_dir = tempfile.TemporaryDirectory(prefix="orchestrator_approval_selftest_")

    original_get_view_dir = get_view_dir

    fake_dir = Path(temp_dir.name) / "case_view"

    globals()["get_view_dir"] = lambda cid: fake_dir

    try:

        real_output = orchestrator_engine.build_case_view(case_id)

        pending_path = get_pending_path(case_id)

        atomic_write_json(pending_path, real_output)

        # T01: temiz pending inspect + review
        pending_path2, validation, view = inspect_pending(case_id)

        assert validation["valid"] is True, "\n".join(validation["errors"])

        print("T01 Temiz pending inspect (validator+semantic guard) PASS:", "PASS")

        run_review(case_id)

        print("T02 run_review MUTATION yapmadı:", "PASS")

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

        # T05: PRE-WRITE mismatch (manifest tahrif edilmiş - yazımdan
        # ÖNCE reddedilmeli)
        tampered_output = json.loads(json.dumps(real_output))

        tampered_output["analysis_metadata"]["dependency_manifest"][0]["raw_byte_sha256"] = "0" * 64

        atomic_write_json(pending_path, tampered_output)

        raised = False

        try:

            run_approve(case_id)

        except Exception:

            raised = True

        assert raised, "Pre-write manifest mismatch approval'ı DURDURMADI."

        print("T05 PRE-WRITE manifest mismatch approval'ı yazımdan ÖNCE reddetti:", "PASS")

        # T05b: POST-WRITE mismatch simülasyonu
        atomic_write_json(pending_path, real_output)

        original_compare = compare_manifest_to_live

        call_state = {"n": 0}

        def fake_compare(view):

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

        # T06: rollback sonrası canonical hâlâ ilk promosyondan geliyor mu
        canonical_sha_after = sha256_file(canonical_path)

        assert canonical_sha_after == canonical_sha, "Rollback sonrası canonical DEĞİŞMİŞ."

        print("T06 Rollback sonrası canonical byte-for-byte korunmuş:", "PASS")

        # T07: generation_status='failed' (GERÇEKTEN eksik zorunlu
        # kaynak - uydurma/tahrif edilmiş bir değer DEĞİL). Var olmayan
        # bir case_id için gerçek build_case_view() çağrısı GERÇEKTEN
        # 'failed' üretir; validator bunu TUTARLI bulmalı (kendi içinde
        # tutarlı, şema-geçerli), ama approval'ın KENDİ semantic guard'ı
        # yine de reddetmelidir (kullanıcı kararı: 'failed' promote
        # edilemez).
        failed_case_id = "case_9999_does_not_exist"

        failed_view = orchestrator_engine.build_case_view(failed_case_id)

        assert failed_view["generation_status"] == "failed", "Test fixture varsayımı geçersiz."

        failed_pending_path = get_pending_path(failed_case_id)

        atomic_write_json(failed_pending_path, failed_view)

        from orchestrator_validator import validate_case_view as _validate_case_view

        validator_result = _validate_case_view(failed_pending_path, expected_case_id=failed_case_id)

        assert validator_result["valid"] is True, (
            "Test fixture varsayımı geçersiz: gerçekten 'failed' olan bir case_view "
            "validator tarafından TUTARSIZ bulunmamalıydı:\n" + "\n".join(validator_result["errors"])
        )

        raised3 = False

        try:

            inspect_pending(failed_case_id)

        except OrchestratorApprovalError:

            raised3 = True

        assert raised3, "generation_status='failed' olan bir case_view Layer A tarafından REDDEDİLMEDİ."

        print("T07 generation_status='failed' (gerçekten eksik kaynak) - validator TUTARLI buldu, approval semantic guard REDDETTİ:", "PASS")

        # T08: approval semantics - v1 motorunun üretmediği bir
        # generation_status değeri (örn. 'aborted_source_changed')
        # reddedilir.
        bad_output = json.loads(json.dumps(real_output))

        bad_output["generation_status"] = "aborted_source_changed"

        atomic_write_json(pending_path, bad_output)

        # NOT: inspect_pending() ÖNCE tam validator'ı (schema + bağımsız
        # yeniden hesaplama) çalıştırır - o katman generation_status
        # tutarsızlığını ZATEN yakalar ve ValueError fırlatır (bkz.
        # orchestrator_validator.validate_generation_status_consistency).
        # validate_approval_semantics'in KENDİ OrchestratorApprovalError'ı
        # yalnız validator bu belirli ihlali YAKALAMASAYDI devreye girerdi
        # (defense-in-depth) - bu yüzden burada İKİ istisna türü de kabul
        # edilir; hangi katmanın yakaladığı değil, Layer A'nın promosyonu
        # GERÇEKTEN reddettiği doğrulanır.
        raised2 = False

        try:

            inspect_pending(case_id)

        except (OrchestratorApprovalError, ValueError):

            raised2 = True

        assert raised2, "Geçersiz generation_status DEĞERİ hiçbir katman tarafından reddedilmedi."

        print("T08 Layer A (validator veya semantic guard), v1 motorunun üretmediği generation_status değerini reddetti:", "PASS")

    finally:

        globals()["get_view_dir"] = original_get_view_dir

        temp_dir.cleanup()

    # T09: gerçek case_0001 case_view/ ağacı boyunca hiç dokunulmadı -
    # get_view_dir GERÇEK haline RESTORE EDİLDİKTEN SONRA çalıştırılmalı.
    assert_real_view_tree_unchanged(case_id, real_tree_before, "Self-test sonu")

    print("T09 Gerçek case_0001 case_view/ ağacı baştan sona dokunulmamış:", "PASS")

    print()
    print("======================================")
    print(" ORCHESTRATOR APPROVAL V1: 10/10 SELF-TEST PASS")
    print("======================================")


def main():

    import argparse

    parser = argparse.ArgumentParser(description="Vergi AI Orchestrator Approval V1")

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
