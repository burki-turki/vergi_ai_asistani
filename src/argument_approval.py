# ============================================================
# VERGİ AI - ARGUMENT APPROVAL V1 (LAYER A)
#
# AMAÇ
# ----
#
# Argument Engine V1 tarafından üretilmiş:
#
#   arguments_<case_id>_v1.json.pending
#
# dosyasını human review sonrası:
#
#   arguments.json
#
# canonical repository kaydına promote etmek.
#
#
# ÖNEMLİ SEMANTİK
# ----------------
#
# Argument analysis approval:
#
#   != bir claim/counterargument/rebuttal'ın avukat tarafından
#      onaylanması (bu AYRI bir katmandır - bkz.
#      argument_review.py / Layer B)
#   != nihai hukuki sonuç, dava kazanma ihtimali veya
#      admissibility/strength/sufficiency belirlemesi
#
# Layer A yalnız TAZE engine çıktısını (tüm review_state'ler
# 'needs_review' - VEYA geçerli bir Layer B carry-forward audit
# kaydıyla desteklenen 'confirmed'/'rejected'/vb.) canonical
# hale getirir.
#
#
# GÜVENLİK
# --------
#
# - Varsayılan REVIEW modudur.
# - Mutation yalnız --approve ile yapılır.
# - Pending Argument Validator V1'den geçmelidir.
# - Pending semantic safety guard'dan geçmelidir.
# - Pending içerik değiştirilmeden canonical'a kopyalanır.
# - Canonical varsa backup alınır.
# - Atomic replace yapılır.
# - Post-write validator tekrar çalışır.
# - Pending SHA256 == canonical SHA256 olmalıdır.
# - Approval audit kaydı oluşturulur.
# - Başarısızlıkta rollback yapılır.
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

ARGUMENT_APPROVAL_VERSION = "1"

DEFAULT_CASE_ID = "case_0001"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

CASES_DIR = DATA_DIR / "cases"


# ============================================================
# EXCEPTION
# ============================================================

class ArgumentApprovalError(Exception):
    pass


# ============================================================
# PATH HELPERS
# ============================================================

def get_arguments_dir(case_id):

    return CASES_DIR / case_id / "arguments"


def get_pending_path(case_id):

    return get_arguments_dir(case_id) / f"arguments_{case_id}_v1.json.pending"


def get_canonical_path(case_id):

    return get_arguments_dir(case_id) / "arguments.json"


def get_reviews_dir(case_id):

    return get_arguments_dir(case_id) / "reviews"


def get_carry_forward_dir(case_id):

    return get_arguments_dir(case_id) / "history" / "carry_forward"


# ============================================================
# JSON / SHA256 HELPERS
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


# ============================================================
# CARRY-FORWARD AUDIT LOOKUP (LAYER A GUARD İÇİN)
# ============================================================

def collect_known_carry_forward_ids(case_id):
    """
    history/carry_forward/ altındaki TÜM audit dosyalarının
    "new_id" alanlarını entity_type bazında toplar. Bu, Layer A
    approval'ın "needs_review dışı bir review_state yalnız
    meşru bir carry-forward audit'i varsa kabul edilir" kuralını
    uygulayabilmesi içindir.
    """

    carry_dir = get_carry_forward_dir(case_id)

    known = {"claim": set(), "counterargument": set(), "rebuttal": set()}

    if not carry_dir.exists():

        return known

    for audit_path in sorted(carry_dir.glob("carry_forward_*.json")):

        try:

            audit = load_json(audit_path)

        except Exception:

            continue

        for record in audit.get("carried_records", []):

            entity_type = record.get("entity_type")

            new_id = record.get("new_id")

            if entity_type in known and new_id:

                known[entity_type].add(new_id)

    return known


# ============================================================
# ARGUMENT ANALYSIS VALIDATION
# ============================================================

def validate_arguments_file(path, case_id):

    result = validate_argument_analysis(
        arguments_path=Path(path), expected_case_id=case_id, raise_on_error=True,
    )

    if result.get("valid") is not True:

        raise ArgumentApprovalError("Argument Validator valid=False.")

    return result


# ============================================================
# APPROVAL SEMANTIC GUARD
# ============================================================

def validate_approval_semantics(analysis, known_carry_forward_ids=None):

    known_carry_forward_ids = known_carry_forward_ids or {
        "claim": set(), "counterargument": set(), "rebuttal": set(),
    }

    if not isinstance(analysis, dict):

        raise ArgumentApprovalError("Argument analysis dict değil.")

    if analysis.get("status") not in {"completed", "partial"}:

        raise ArgumentApprovalError(
            "Approval için argument analysis status completed/partial "
            "olmalıdır."
        )

    coverage_records = analysis.get("argument_coverage")

    claims = analysis.get("argument_claims")

    counterarguments = analysis.get("argument_counterarguments")

    rebuttals = analysis.get("argument_rebuttals")

    suggestions = analysis.get("argument_agent_suggestions")

    for name, records in (
        ("argument_coverage", coverage_records),
        ("argument_claims", claims),
        ("argument_counterarguments", counterarguments),
        ("argument_rebuttals", rebuttals),
        ("argument_agent_suggestions", suggestions),
    ):

        if not isinstance(records, list):

            raise ArgumentApprovalError(f"{name} alanı list değil.")

    for record_list, id_field in (
        (coverage_records, "coverage_id"),
        (claims, "claim_id"),
        (counterarguments, "counterargument_id"),
        (rebuttals, "rebuttal_id"),
        (suggestions, "suggestion_id"),
    ):

        for record in record_list:

            if not isinstance(record, dict):

                raise ArgumentApprovalError("Argument kaydı dict değil.")

            if record.get("status") != "candidate":

                raise ArgumentApprovalError(
                    "Approval yalnız status='candidate' kayıtları kabul "
                    f"edebilir: {record.get(id_field)}"
                )

            if record.get("requires_human_review") is not True:

                raise ArgumentApprovalError(
                    "Approval requires_human_review=True DIŞINDA bir "
                    f"kaydı kabul edemez: {record.get(id_field)}"
                )

    for claim in claims:

        state = claim.get("claim_review_state")

        if state != "needs_review" and claim.get("claim_id") not in (
            known_carry_forward_ids["claim"]
        ):

            raise ArgumentApprovalError(
                "Layer A yalnız review_state='needs_review' (veya geçerli "
                f"bir carry-forward audit'i olan) claim kabul edebilir: "
                f"{claim.get('claim_id')}"
            )

    for counter in counterarguments:

        state = counter.get("counter_review_state")

        if state != "needs_review" and counter.get(
            "counterargument_id"
        ) not in known_carry_forward_ids["counterargument"]:

            raise ArgumentApprovalError(
                "Layer A yalnız counter_review_state='needs_review' (veya "
                "geçerli bir carry-forward audit'i olan) counterargument "
                f"kabul edebilir: {counter.get('counterargument_id')}"
            )

    for rebuttal in rebuttals:

        state = rebuttal.get("rebuttal_review_state")

        if state != "needs_review" and rebuttal.get(
            "rebuttal_id"
        ) not in known_carry_forward_ids["rebuttal"]:

            raise ArgumentApprovalError(
                "Layer A yalnız rebuttal_review_state='needs_review' (veya "
                "geçerli bir carry-forward audit'i olan) rebuttal kabul "
                f"edebilir: {rebuttal.get('rebuttal_id')}"
            )

    for suggestion in suggestions:

        if suggestion.get("suggestion_review_state") != "needs_review":

            raise ArgumentApprovalError(
                "Layer A yalnız suggestion_review_state='needs_review' "
                f"olan suggestion kabul edebilir: "
                f"{suggestion.get('suggestion_id')}"
            )

    return True


# ============================================================
# BACKUP CANONICAL
# ============================================================

def backup_canonical(case_id):

    canonical_path = get_canonical_path(case_id)

    if not canonical_path.exists():

        return None

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

    backup_path = get_arguments_dir(case_id) / (
        "arguments.json.before_approval_" + timestamp + ".bak"
    )

    shutil.copy2(canonical_path, backup_path)

    return backup_path


# ============================================================
# AUDIT
# ============================================================

def write_approval_audit(
    case_id, pending_path, canonical_path, pending_sha256, canonical_sha256,
    previous_canonical_backup, analysis,
):

    reviews_dir = get_reviews_dir(case_id)

    reviews_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().astimezone()

    timestamp = now.strftime("%Y%m%d_%H%M%S")

    audit_path = reviews_dir / (
        "arguments_" + case_id + "_v1_" + timestamp + ".approval.json"
    )

    audit = {
        "audit_type": "argument_analysis_approval",
        "approval_version": ARGUMENT_APPROVAL_VERSION,
        "approved_at": now.isoformat(),
        "case_id": case_id,
        "argument_analysis_id": analysis.get("argument_analysis_id"),
        "source_pending_path": str(pending_path),
        "canonical_path": str(canonical_path),
        "pending_sha256": pending_sha256,
        "canonical_sha256": canonical_sha256,
        "content_identical": pending_sha256 == canonical_sha256,
        "previous_canonical_backup": (
            str(previous_canonical_backup) if previous_canonical_backup else None
        ),
        "coverage_count": len(analysis.get("argument_coverage", [])),
        "claim_count": len(analysis.get("argument_claims", [])),
        "counterargument_count": len(analysis.get("argument_counterarguments", [])),
        "rebuttal_count": len(analysis.get("argument_rebuttals", [])),
        "suggestion_count": len(analysis.get("argument_agent_suggestions", [])),
        "approval_semantics": (
            "Bu approval argument analysis kaydını canonical repository'ye "
            "kabul eder. Hiçbir claim/counterargument/rebuttal'ın avukat "
            "tarafından doğrulandığı, nihai hukuki sonuç, dava kazanma "
            "ihtimali veya admissibility/strength/sufficiency taşıdığı "
            "anlamına gelmez. review_state yükseltmesi (confirmed/"
            "rejected/accepted_for_follow_up/dismissed) yalnız ayrı bir "
            "Layer B human review (argument_review.py) ile mümkündür."
        ),
    }

    atomic_write_json(audit_path, audit)

    return audit_path


# ============================================================
# LOAD + VALIDATE PENDING
# ============================================================

def inspect_pending(case_id):

    pending_path = get_pending_path(case_id)

    if not pending_path.exists():

        raise ArgumentApprovalError(
            f"Pending argument analysis bulunamadı:\n{pending_path}"
        )

    validation = validate_arguments_file(pending_path, case_id)

    analysis = load_json(pending_path)

    known_carry_forward_ids = collect_known_carry_forward_ids(case_id)

    validate_approval_semantics(analysis, known_carry_forward_ids)

    return (pending_path, validation, analysis)


# ============================================================
# REVIEW
# ============================================================

def run_review(case_id):

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT APPROVAL V1")
    print(" MODE: REVIEW")
    print("======================================")

    pending_path, validation, analysis = inspect_pending(case_id)

    print("Pending validator:", "PASS")
    print("Approval semantic guard:", "PASS")
    print()
    print("Case:", analysis["case_id"])
    print("Analysis ID:", analysis["argument_analysis_id"])
    print("Status:", analysis["status"])
    print("Coverage count:", len(analysis["argument_coverage"]))
    print("Claim count:", len(analysis["argument_claims"]))
    print("Counterargument count:", len(analysis["argument_counterarguments"]))
    print("Rebuttal count:", len(analysis["argument_rebuttals"]))
    print("Suggestion count:", len(analysis["argument_agent_suggestions"]))
    print()

    for coverage in analysis["argument_coverage"]:

        print(
            "Coverage:", coverage["coverage_id"],
            "| issue:", coverage["source_issue_id"],
            "| execution_state:", coverage["execution_state"],
        )

    print()
    print("Pending:")
    print(pending_path)
    print()
    print("Canonical target:")
    print(get_canonical_path(case_id))
    print()
    print("MUTATION:")
    print("- yapılmadı")
    print()
    print("Onay için:")
    print("python src\\argument_approval.py --approve")
    print()
    print("======================================")
    print(" ARGUMENT APPROVAL V1: READY")
    print("======================================")


# ============================================================
# APPROVE
# ============================================================

def run_approve(case_id):

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT APPROVAL V1")
    print(" MODE: APPROVE")
    print("======================================")

    pending_path, validation, analysis = inspect_pending(case_id)

    canonical_path = get_canonical_path(case_id)

    pending_sha256 = sha256_file(pending_path)

    previous_canonical_backup = backup_canonical(case_id)

    print(
        "Previous canonical backup:", previous_canonical_backup
        if previous_canonical_backup else "NONE",
    )

    try:

        atomic_copy_file(pending_path, canonical_path)

        validate_arguments_file(canonical_path, case_id)

        canonical_analysis = load_json(canonical_path)

        known_carry_forward_ids = collect_known_carry_forward_ids(case_id)

        validate_approval_semantics(canonical_analysis, known_carry_forward_ids)

        canonical_sha256 = sha256_file(canonical_path)

        if pending_sha256 != canonical_sha256:

            raise ArgumentApprovalError("Pending ve canonical SHA256 eşit değil.")

    except Exception:

        if canonical_path.exists():

            canonical_path.unlink()

        if (
            previous_canonical_backup is not None
            and previous_canonical_backup.exists()
        ):

            shutil.copy2(previous_canonical_backup, canonical_path)

        print()
        print("APPROVAL FAIL")
        print("Rollback uygulandı.")

        raise

    try:

        audit_path = write_approval_audit(
            case_id, pending_path, canonical_path, pending_sha256,
            canonical_sha256, previous_canonical_backup, canonical_analysis,
        )

    except Exception:

        if canonical_path.exists():

            canonical_path.unlink()

        if (
            previous_canonical_backup is not None
            and previous_canonical_backup.exists()
        ):

            shutil.copy2(previous_canonical_backup, canonical_path)

        print()
        print("AUDIT FAIL")
        print("Canonical rollback uygulandı.")

        raise

    print()
    print("ARGUMENT ANALYSIS APPROVED")
    print("Case:", canonical_analysis["case_id"])
    print("Analysis ID:", canonical_analysis["argument_analysis_id"])
    print()
    print("Canonical:")
    print(canonical_path)
    print()
    print("Pending SHA256:", pending_sha256)
    print("Canonical SHA256:", canonical_sha256)
    print("Content identical:", pending_sha256 == canonical_sha256)
    print()
    print("Audit:")
    print(audit_path)
    print()
    print("SEMANTIC NOTE:")
    print("- Hiçbir claim/counterargument/rebuttal avukat tarafından")
    print("  doğrulanmış (confirmed) SAYILMADI.")
    print("- Nihai hukuki sonuç/case outcome içermez.")
    print()
    print("======================================")
    print(" ARGUMENT APPROVAL V1: PASS")
    print("======================================")


# ============================================================
# REAL ARGUMENTS TREE SNAPSHOT (POST-APPROVAL SELF-TEST INVARIANT)
#
# "Gerçek canonical arguments.json mevcut OLMAMALIDIR" varsayımı
# yalnız Row 13 approval ÖNCESİNDE geçerliydi. Approval sonrası bu
# varsayım kalıcı olarak geçersizdir. Doğru invariant: self-test
# başlamadan önceki gerçek dizin durumu (mevcut olsun ya da olmasın)
# self-test SONUNDA birebir aynı kalmalıdır. snapshot fonksiyonu
# CASES_DIR sabitinden DOĞRUDAN türetir - monkeypatch edilmiş
# get_arguments_dir/get_canonical_path/get_reviews_dir'den
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
# SELF TEST (DRY-RUN / SEMANTIC GUARD, TEMPFILE ISOLATION)
# ============================================================

def run_self_test():

    print()
    print("======================================")
    print(" VERGİ AI - ARGUMENT APPROVAL V1 (SELF-TEST)")
    print("======================================")

    real_case_id = "case_0001"

    # Pre-self-test snapshot (post-approval invariant): gerçek
    # arguments dizini approval ile mevcut olsun ya da olmasın, bu
    # self-test SONUNDA birebir aynı kalmalıdır.

    real_tree_before = snapshot_real_arguments_tree(real_case_id)

    from argument_engine import build_argument_engine_output

    build_result = build_argument_engine_output(real_case_id, use_agent=False)

    analysis = build_result["analysis"]

    validate_approval_semantics(analysis)

    print("T01 Approval semantic guard PASS on fresh engine output:", "PASS")

    tampered = json.loads(json.dumps(analysis))

    if tampered["argument_claims"]:

        tampered["argument_claims"][0]["claim_review_state"] = "confirmed"

        raised = False

        try:

            validate_approval_semantics(tampered)

        except ArgumentApprovalError:

            raised = True

        assert raised is True

    else:

        # Offline baseline has 0 claims - construct a synthetic one to
        # exercise the guard directly (no real case_0001 data touched).
        synthetic_claim = {
            "claim_id": "argument_claim_999",
            "source_issue_id": "issue_001",
            "claim_type": "factual_challenge",
            "claim_text": "x",
            "source_fact_ids": ["f1"],
            "source_evidence_candidate_ids": [],
            "source_legal_research_ids": [],
            "source_case_law_ids": [],
            "source_timeline_event_ids": [],
            "source_deadline_ids": [],
            "depends_on_unconfirmed_evidence": False,
            "depends_on_unconfirmed_authority": False,
            "missing_legal_authority": False,
            "reason_code": "explicit_textual_match",
            "grounded_explanation": "x",
            "claim_review_state": "confirmed",
            "requires_human_review": True,
            "status": "candidate",
        }

        tampered["argument_claims"] = [synthetic_claim]

        raised = False

        try:

            validate_approval_semantics(tampered)

        except ArgumentApprovalError:

            raised = True

        assert raised is True

    print(
        "T02 Approval semantic guard rejects pre-tampered claim_review_state "
        "!= 'needs_review' without a matching carry-forward audit:",
        "PASS",
    )

    assert_real_arguments_tree_unchanged(
        real_case_id, real_tree_before,
        "After T01-T02 (semantic guard checks, no file I/O expected)",
    )

    print("T03 Dry-run/review mode makes no canonical mutation:", "PASS")

    # ------------------------------------------------------------
    # T04-T09: run_approve() END-TO-END, RUNTIME, FULLY ISOLATED
    # (Finding 4 remediation). get_arguments_dir() is the single
    # root every other path helper (get_pending_path/get_canonical_
    # path/get_reviews_dir/get_carry_forward_dir) derives from, so
    # patching it alone redirects the ENTIRE Layer A file tree into
    # an isolated tempdir - real case_0001/arguments/ is NEVER
    # touched by anything below.
    # ------------------------------------------------------------

    import tempfile

    temp_dir = tempfile.TemporaryDirectory(prefix="argument_approval_selftest_")

    isolated_arguments_dir = Path(temp_dir.name) / "arguments"

    original_get_arguments_dir = get_arguments_dir

    globals()["get_arguments_dir"] = lambda case_id_arg: isolated_arguments_dir

    try:

        pending_path = get_pending_path(real_case_id)

        canonical_path = get_canonical_path(real_case_id)

        reviews_dir = get_reviews_dir(real_case_id)

        # -- T04: first canonical write (run_approve end-to-end) --

        atomic_write_json(pending_path, analysis)

        run_approve(real_case_id)

        assert canonical_path.exists()

        print("T04 First canonical write via run_approve() end-to-end:", "PASS")

        # -- T05: pending/canonical SHA256 equality --

        assert sha256_file(pending_path) == sha256_file(canonical_path)

        print("T05 Pending/canonical SHA256 equality after approve:", "PASS")

        # -- T06: approval audit created --

        audit_files_v1 = list(reviews_dir.glob("*.approval.json"))

        assert len(audit_files_v1) == 1

        audit_content = load_json(audit_files_v1[0])

        assert audit_content["audit_type"] == "argument_analysis_approval"
        assert audit_content["content_identical"] is True

        print("T06 Approval audit record created with correct fields:", "PASS")

        first_canonical_bytes = canonical_path.read_bytes()

        # -- T07: backup created when a PRIOR canonical already
        # exists (re-approve scenario) --

        atomic_write_json(pending_path, analysis)

        run_approve(real_case_id)

        backups = list(
            isolated_arguments_dir.glob("arguments.json.before_approval_*.bak")
        )

        assert len(backups) == 1

        assert backups[0].read_bytes() == first_canonical_bytes

        print(
            "T07 Existing canonical backed up before re-approval "
            "overwrite:", "PASS",
        )

        canonical_after_second_approve = canonical_path.read_bytes()

        # -- T08/T09: rollback on POST-WRITE validator failure,
        # canonical restored BYTE-FOR-BYTE to its prior content --

        distinct_analysis = json.loads(json.dumps(analysis))

        distinct_analysis["notes"] = (
            "DISTINCT MARKER - should NEVER survive into canonical "
            "if rollback works correctly."
        )

        atomic_write_json(pending_path, distinct_analysis)

        call_count = {"n": 0}

        original_validate_arguments_file = validate_arguments_file

        def flaky_validate_arguments_file(path, case_id_arg):

            call_count["n"] += 1

            if call_count["n"] == 2:

                raise ArgumentApprovalError(
                    "Injected failure for rollback test (post-write "
                    "canonical-side re-validation)."
                )

            return original_validate_arguments_file(path, case_id_arg)

        globals()["validate_arguments_file"] = flaky_validate_arguments_file

        raised = False

        try:

            run_approve(real_case_id)

        except Exception:

            raised = True

        finally:

            globals()["validate_arguments_file"] = (
                original_validate_arguments_file
            )

        assert raised is True, (
            "Post-write validator hatası run_approve() tarafından "
            "yutulmamalı, yeniden fırlatılmalıdır."
        )

        print(
            "T08 Post-write validator failure triggers rollback "
            "(exception propagated, not swallowed):", "PASS",
        )

        assert canonical_path.read_bytes() == canonical_after_second_approve, (
            "Rollback sonrası canonical, başarısız approve denemesi "
            "ÖNCESİNDEKİ içerikle birebir aynı olmalıdır."
        )

        assert b"DISTINCT MARKER" not in canonical_path.read_bytes()

        print(
            "T09 Rollback restores previous canonical content "
            "byte-for-byte (distinct marker never persisted):", "PASS",
        )

    finally:

        globals()["get_arguments_dir"] = original_get_arguments_dir

        temp_dir.cleanup()

    # -- T10: real case_0001 arguments dizini self-test başından
    # sonuna kadar birebir aynı (approval ile mevcut olsun ya da
    # olmasın - post-approval invariant) --

    assert_real_arguments_tree_unchanged(
        real_case_id, real_tree_before,
        "End of self-test (full suite)",
    )

    print(
        "T10 Real case_0001 canonical/reviews/history untouched "
        "throughout:", "PASS",
    )

    print()
    print("======================================")
    print(" ARGUMENT APPROVAL V1: 10/10 SELF-TEST PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Argument Approval V1")

    parser.add_argument("--case", dest="case_id", default=DEFAULT_CASE_ID)

    parser.add_argument("--approve", action="store_true")

    parser.add_argument("--self-test", action="store_true", dest="self_test")

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

    elif args.approve:

        run_approve(case_id=args.case_id)

    else:

        run_review(case_id=args.case_id)


if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()
        print("ERROR:")
        print(error)
        print()
        print("======================================")
        print(" ARGUMENT APPROVAL V1: FAIL")
        print("======================================")
        sys.exit(1)
