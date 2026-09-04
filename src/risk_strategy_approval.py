# ============================================================
# VERGİ AI - RISK / STRATEGY APPROVAL V1 (LAYER A)
#
# AMAÇ: risk_strategy_<case_id>_v1.json.pending dosyasını human
# review sonrası risk_strategy.json canonical repository kaydına
# promote etmek.
#
# Risk/Strategy analysis approval:
#   != bir risk/strategy'nin avukat tarafından onaylanması (AYRI
#      katman - bkz. risk_strategy_review.py / Layer B)
#   != nihai hukuki sonuç, dava kazanma ihtimali veya
#      severity/likelihood/win_probability belirlemesi
#
# GÜVENLİK: backup -> byte-level atomic copy -> post-write
# validation -> semantic guard -> SHA256 eşitliği -> audit;
# her failure'da rollback.
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


RISK_STRATEGY_APPROVAL_VERSION = "1"

DEFAULT_CASE_ID = "case_0001"

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"

CASES_DIR = DATA_DIR / "cases"


class RiskStrategyApprovalError(Exception):
    pass


def get_risk_strategy_dir(case_id):

    return CASES_DIR / case_id / "risk_strategy"


def get_pending_path(case_id):

    return get_risk_strategy_dir(case_id) / f"risk_strategy_{case_id}_v1.json.pending"


def get_canonical_path(case_id):

    return get_risk_strategy_dir(case_id) / "risk_strategy.json"


def get_reviews_dir(case_id):

    return get_risk_strategy_dir(case_id) / "reviews"


def get_carry_forward_dir(case_id):

    return get_risk_strategy_dir(case_id) / "history" / "carry_forward"


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

    known = {"risk": set(), "strategy": set(), "suggestion": set()}

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


def validate_risk_strategy_file(path, case_id):

    result = validate_risk_strategy_analysis(
        arguments_path=Path(path), expected_case_id=case_id, raise_on_error=True,
    )

    if result.get("valid") is not True:

        raise RiskStrategyApprovalError("Risk/Strategy Validator valid=False.")

    return result


# ============================================================
# APPROVAL SEMANTIC GUARD
# ============================================================

def validate_approval_semantics(analysis, known_carry_forward_ids=None):

    known_carry_forward_ids = known_carry_forward_ids or {
        "risk": set(), "strategy": set(), "suggestion": set(),
    }

    if not isinstance(analysis, dict):

        raise RiskStrategyApprovalError("Risk/Strategy analysis dict değil.")

    if analysis.get("generation_status") != "completed":

        raise RiskStrategyApprovalError(
            "Approval için generation_status='completed' olmalıdır "
            "(failed bir generation approve edilemez)."
        )

    risks = analysis.get("risk_candidates")

    strategies = analysis.get("strategy_candidates")

    suggestions = analysis.get("risk_strategy_agent_suggestions")

    for name, records in (
        ("risk_candidates", risks),
        ("strategy_candidates", strategies),
        ("risk_strategy_agent_suggestions", suggestions),
    ):

        if not isinstance(records, list):

            raise RiskStrategyApprovalError(f"{name} alanı list değil.")

    for record_list, id_field in (
        (risks, "risk_id"), (strategies, "strategy_id"), (suggestions, "suggestion_id"),
    ):

        for record in record_list:

            if not isinstance(record, dict):

                raise RiskStrategyApprovalError("Kayıt dict değil.")

            if record.get("status") != "candidate":

                raise RiskStrategyApprovalError(
                    f"Approval yalnız status='candidate' kabul edebilir: {record.get(id_field)}"
                )

            if record.get("requires_human_review") is not True:

                raise RiskStrategyApprovalError(
                    f"Approval requires_human_review=True DIŞINDA bir kaydı kabul edemez: {record.get(id_field)}"
                )

    for risk in risks:

        state = risk.get("risk_review_state")

        if state != "needs_review" and risk.get("risk_id") not in known_carry_forward_ids["risk"]:

            raise RiskStrategyApprovalError(
                "Layer A yalnız risk_review_state='needs_review' (veya geçerli "
                f"bir carry-forward audit'i olan) risk kabul edebilir: {risk.get('risk_id')}"
            )

    for strategy in strategies:

        state = strategy.get("strategy_review_state")

        if state != "needs_review" and strategy.get("strategy_id") not in known_carry_forward_ids["strategy"]:

            raise RiskStrategyApprovalError(
                "Layer A yalnız strategy_review_state='needs_review' (veya geçerli "
                f"bir carry-forward audit'i olan) strategy kabul edebilir: {strategy.get('strategy_id')}"
            )

        if strategy.get("record_kind") != "suggested_next_action":

            raise RiskStrategyApprovalError(
                f"strategy.record_kind='suggested_next_action' olmalıdır: {strategy.get('strategy_id')}"
            )

    for suggestion in suggestions:

        if suggestion.get("suggestion_review_state") != "needs_review":

            raise RiskStrategyApprovalError(
                "Layer A yalnız suggestion_review_state='needs_review' olan "
                f"suggestion kabul edebilir: {suggestion.get('suggestion_id')}"
            )

    return True


def backup_canonical(case_id):

    canonical_path = get_canonical_path(case_id)

    if not canonical_path.exists():

        return None

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")

    backup_path = get_risk_strategy_dir(case_id) / (
        "risk_strategy.json.before_approval_" + timestamp + ".bak"
    )

    shutil.copy2(canonical_path, backup_path)

    return backup_path


def write_approval_audit(
    case_id, pending_path, canonical_path, pending_sha256, canonical_sha256,
    previous_canonical_backup, analysis,
):

    reviews_dir = get_reviews_dir(case_id)

    reviews_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().astimezone()

    timestamp = now.strftime("%Y%m%d_%H%M%S")

    audit_path = reviews_dir / (
        "risk_strategy_" + case_id + "_v1_" + timestamp + ".approval.json"
    )

    audit = {
        "audit_type": "risk_strategy_analysis_approval",
        "approval_version": RISK_STRATEGY_APPROVAL_VERSION,
        "approved_at": now.isoformat(),
        "case_id": case_id,
        "risk_strategy_analysis_id": analysis.get("risk_strategy_analysis_id"),
        "source_pending_path": str(pending_path),
        "canonical_path": str(canonical_path),
        "pending_sha256": pending_sha256,
        "canonical_sha256": canonical_sha256,
        "content_identical": pending_sha256 == canonical_sha256,
        "previous_canonical_backup": (
            str(previous_canonical_backup) if previous_canonical_backup else None
        ),
        "risk_coverage_count": len(analysis.get("risk_coverage", [])),
        "case_scope_coverage_count": len(analysis.get("case_scope_coverage", [])),
        "risk_count": len(analysis.get("risk_candidates", [])),
        "strategy_count": len(analysis.get("strategy_candidates", [])),
        "suggestion_count": len(analysis.get("risk_strategy_agent_suggestions", [])),
        "approval_semantics": (
            "Bu approval risk/strategy analysis kaydını canonical "
            "repository'ye kabul eder. Hiçbir risk/strategy'nin avukat "
            "tarafından doğrulandığı, nihai hukuki sonuç, dava kazanma "
            "ihtimali veya severity/likelihood/win_probability taşıdığı "
            "anlamına gelmez. review_state yükseltmesi (confirmed/rejected/"
            "accepted_for_follow_up/dismissed) yalnız ayrı bir Layer B "
            "human review (risk_strategy_review.py) ile mümkündür."
        ),
    }

    atomic_write_json(audit_path, audit)

    return audit_path


def inspect_pending(case_id):

    pending_path = get_pending_path(case_id)

    if not pending_path.exists():

        raise RiskStrategyApprovalError(f"Pending risk/strategy analysis bulunamadı:\n{pending_path}")

    validation = validate_risk_strategy_file(pending_path, case_id)

    analysis = load_json(pending_path)

    known_carry_forward_ids = collect_known_carry_forward_ids(case_id)

    validate_approval_semantics(analysis, known_carry_forward_ids)

    return (pending_path, validation, analysis)


def run_review(case_id):

    print()
    print("======================================")
    print(" VERGİ AI - RISK / STRATEGY APPROVAL V1")
    print(" MODE: REVIEW")
    print("======================================")

    pending_path, validation, analysis = inspect_pending(case_id)

    print("Pending validator:", "PASS")
    print("Approval semantic guard:", "PASS")
    print()
    print("Case:", analysis["case_id"])
    print("Analysis ID:", analysis["risk_strategy_analysis_id"])
    print("Generation status:", analysis["generation_status"])
    print("Risk coverage:", len(analysis["risk_coverage"]))
    print("Case-scope coverage:", len(analysis["case_scope_coverage"]))
    print("Risk count:", len(analysis["risk_candidates"]))
    print("Strategy count:", len(analysis["strategy_candidates"]))
    print("Suggestion count:", len(analysis["risk_strategy_agent_suggestions"]))
    print()
    print("MUTATION: yapılmadı")
    print()
    print("Onay için: python src\\risk_strategy_approval.py --approve")
    print()
    print("======================================")
    print(" RISK / STRATEGY APPROVAL V1: READY")
    print("======================================")


def run_approve(case_id):

    print()
    print("======================================")
    print(" VERGİ AI - RISK / STRATEGY APPROVAL V1")
    print(" MODE: APPROVE")
    print("======================================")

    pending_path, validation, analysis = inspect_pending(case_id)

    canonical_path = get_canonical_path(case_id)

    pending_sha256 = sha256_file(pending_path)

    previous_canonical_backup = backup_canonical(case_id)

    print(
        "Previous canonical backup:",
        previous_canonical_backup if previous_canonical_backup else "NONE",
    )

    try:

        atomic_copy_file(pending_path, canonical_path)

        validate_risk_strategy_file(canonical_path, case_id)

        canonical_analysis = load_json(canonical_path)

        known_carry_forward_ids = collect_known_carry_forward_ids(case_id)

        validate_approval_semantics(canonical_analysis, known_carry_forward_ids)

        canonical_sha256 = sha256_file(canonical_path)

        if pending_sha256 != canonical_sha256:

            raise RiskStrategyApprovalError("Pending ve canonical SHA256 eşit değil.")

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
            case_id, pending_path, canonical_path, pending_sha256,
            canonical_sha256, previous_canonical_backup, canonical_analysis,
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
    print("RISK / STRATEGY ANALYSIS APPROVED")
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
    print("SEMANTIC NOTE:")
    print("- Hiçbir risk/strategy avukat tarafından doğrulanmış SAYILMADI.")
    print("- Nihai hukuki sonuç/case outcome içermez.")
    print()
    print("======================================")
    print(" RISK / STRATEGY APPROVAL V1: PASS")
    print("======================================")


# ============================================================
# REAL TREE SNAPSHOT (POST-APPROVAL SELF-TEST INVARIANT)
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
# SELF TEST (izole tempdir, gerçek run_approve akışı)
# ============================================================

def run_self_test():

    import tempfile

    print()
    print("======================================")
    print(" VERGİ AI - RISK / STRATEGY APPROVAL V1 (SELF-TEST)")
    print("======================================")

    case_id = DEFAULT_CASE_ID

    real_tree_before = snapshot_real_risk_strategy_tree(case_id)

    temp_dir = tempfile.TemporaryDirectory(prefix="risk_strategy_approval_selftest_")

    original_get_risk_strategy_dir = get_risk_strategy_dir

    fake_dir = Path(temp_dir.name) / "risk_strategy"

    globals()["get_risk_strategy_dir"] = lambda cid: fake_dir

    try:

        from risk_strategy_engine import build_risk_strategy_engine_output

        result = build_risk_strategy_engine_output(case_id, use_agent=False)

        analysis = dict(result["analysis"])

        pending_path = get_pending_path(case_id)

        atomic_write_json(pending_path, analysis)

        assert pending_path.exists()

        print("T01 Isolated tempdir pending write:", "PASS")

        # ---- T02: run_review does not mutate ----

        run_review(case_id)

        assert not get_canonical_path(case_id).exists()

        print("T02 Review mode does not create canonical:", "PASS")

        # ---- T03: run_approve real flow ----

        run_approve(case_id)

        canonical_path = get_canonical_path(case_id)

        assert canonical_path.exists()

        pending_sha = sha256_file(pending_path)

        canonical_sha = sha256_file(canonical_path)

        assert pending_sha == canonical_sha

        print("T03 Approve produces byte-identical canonical:", "PASS")

        reviews = list(get_reviews_dir(case_id).glob("*.approval.json"))

        assert len(reviews) == 1

        audit = load_json(reviews[0])

        assert audit["pending_sha256"] == pending_sha
        assert audit["canonical_sha256"] == canonical_sha
        assert audit["content_identical"] is True

        print("T04 Approval audit written and correct:", "PASS")

        # ---- T05: re-approve without change - backup created ----

        run_approve(case_id)

        backups = list(get_risk_strategy_dir(case_id).glob("*.before_approval_*.bak"))

        assert len(backups) == 1

        print("T05 Existing canonical backed up before re-approval overwrite:", "PASS")

        # ---- T06/T07: injected POST-WRITE validation failure -> rollback,
        # canonical restored byte-for-byte to its PRIOR content ----

        canonical_sha_before = sha256_file(canonical_path)

        canonical_bytes_before = canonical_path.read_bytes()

        distinct_analysis = json.loads(json.dumps(analysis))

        distinct_analysis["notes"] = (
            "DISTINCT MARKER - should NEVER survive into canonical if "
            "rollback works correctly."
        )

        atomic_write_json(pending_path, distinct_analysis)

        call_count = {"n": 0}

        original_validate_risk_strategy_file = validate_risk_strategy_file

        def flaky_validate_risk_strategy_file(path, case_id_arg):

            call_count["n"] += 1

            if call_count["n"] == 2:

                raise RiskStrategyApprovalError(
                    "Injected failure for rollback test (post-write "
                    "canonical-side re-validation)."
                )

            return original_validate_risk_strategy_file(path, case_id_arg)

        globals()["validate_risk_strategy_file"] = flaky_validate_risk_strategy_file

        try:

            raised = False

            try:

                run_approve(case_id)

            except Exception:

                raised = True

            assert raised is True

        finally:

            globals()["validate_risk_strategy_file"] = original_validate_risk_strategy_file

        canonical_sha_after = sha256_file(canonical_path)

        assert canonical_sha_after == canonical_sha_before

        assert canonical_path.read_bytes() == canonical_bytes_before

        assert b"DISTINCT MARKER" not in canonical_path.read_bytes()

        print("T06 Post-write validator failure triggers rollback:", "PASS")
        print("T07 Rollback restores previous canonical content byte-for-byte:", "PASS")

        # restore pending to the clean analysis for tidiness (not asserted)
        atomic_write_json(pending_path, analysis)

    finally:

        globals()["get_risk_strategy_dir"] = original_get_risk_strategy_dir

        temp_dir.cleanup()

    assert_real_risk_strategy_tree_unchanged(
        DEFAULT_CASE_ID, real_tree_before, "End of self-test",
    )

    print("T08 Real case_0001 canonical/reviews/history untouched throughout:", "PASS")

    print()
    print("======================================")
    print(" RISK / STRATEGY APPROVAL V1: 8/8 SELF-TEST PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(description="Vergi AI Risk/Strategy Approval V1")

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
