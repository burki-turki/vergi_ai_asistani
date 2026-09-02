# ============================================================
# VERGİ AI - ISSUE SPOTTING APPROVAL V1
#
# AMAÇ
# ----
#
# Issue Spotting Engine V1 tarafından üretilmiş:
#
#   issue_spotting_<case_id>_v1.json.pending
#
# dosyasını human review sonrası:
#
#   issues.json
#
# canonical repository kaydına promote etmek.
#
#
# ÖNEMLİ SEMANTİK
# ----------------
#
# Issue analysis approval:
#
#   != issue candidate'ların doğrulanması
#   != legal conclusion üretimi
#   != case outcome belirlenmesi
#   != deadline determination
#
# Bir issue candidate'ın approval'ı yalnız:
#
#   "Bu adaylar, davada incelenmesi gereken noktalar
#    olarak canonical çalışma verisine kabul edilmiştir."
#
# anlamına gelir. Hiçbir issue'nun maddi olarak doğru
# olduğu, hukuki bir sonuca vardığı veya kesin bir süre
# belirlediği anlamına GELMEZ.
#
#
# GÜVENLİK
# --------
#
# - Varsayılan REVIEW modudur.
# - Mutation yalnız --approve ile yapılır.
# - Pending Issue Spotting Validator V1'den geçmelidir.
# - Pending semantic safety guard'dan geçmelidir.
# - Pending içerik değiştirilmeden canonical'a kopyalanır.
# - Canonical varsa backup alınır.
# - Atomic replace yapılır.
# - Post-write validator tekrar çalışır.
# - Pending SHA256 == canonical SHA256 olmalıdır.
# - Approval audit kaydı oluşturulur.
# - Başarısızlıkta rollback yapılır.
#
# ============================================================


import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path


from issue_spotting_validator import (
    FORBIDDEN_PHRASES,
    validate_issue_analysis,
)

from timeline_consolidation_policy import (
    normalize_text_tr,
)


# ============================================================
# VERSION
# ============================================================

ISSUE_SPOTTING_APPROVAL_VERSION = "1"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DATA_DIR = (
    BASE_DIR
    / "data"
)

CASES_DIR = (
    DATA_DIR
    / "cases"
)


# ============================================================
# DEFAULTS
# ============================================================

DEFAULT_CASE_ID = (
    "case_0001"
)


# ============================================================
# EXCEPTION
# ============================================================

class IssueSpottingApprovalError(
    Exception
):
    pass


# ============================================================
# PATH HELPERS
# ============================================================

def get_issues_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "issues"
    )


def get_pending_path(
    case_id,
):

    return (
        get_issues_dir(
            case_id
        )
        / (
            f"issue_spotting_{case_id}_v1.json.pending"
        )
    )


def get_canonical_path(
    case_id,
):

    return (
        get_issues_dir(
            case_id
        )
        / "issues.json"
    )


def get_reviews_dir(
    case_id,
):

    return (
        get_issues_dir(
            case_id
        )
        / "reviews"
    )


# ============================================================
# JSON
# ============================================================

def load_json(
    path,
):

    path = Path(
        path
    )

    if not path.exists():

        raise FileNotFoundError(
            f"Dosya bulunamadı:\n{path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(
            file
        )


def atomic_write_json(
    path,
    data,
):

    path = Path(
        path
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = (
        path.parent
        / (
            path.name
            + ".tmp"
        )
    )

    with open(
        temp_path,
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.write(
            "\n"
        )

        file.flush()

        os.fsync(
            file.fileno()
        )

    os.replace(
        temp_path,
        path,
    )


def atomic_copy_file(
    source_path,
    target_path,
):

    source_path = Path(
        source_path
    )

    target_path = Path(
        target_path
    )

    target_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = (
        target_path.parent
        / (
            target_path.name
            + ".tmp"
        )
    )

    with open(
        source_path,
        "rb",
    ) as source:

        with open(
            temp_path,
            "wb",
        ) as target:

            while True:

                chunk = source.read(
                    1024 * 1024
                )

                if not chunk:

                    break

                target.write(
                    chunk
                )

            target.flush()

            os.fsync(
                target.fileno()
            )

    os.replace(
        temp_path,
        target_path,
    )


# ============================================================
# SHA256
# ============================================================

def sha256_file(
    path,
):

    digest = hashlib.sha256()

    with open(
        path,
        "rb",
    ) as file:

        while True:

            chunk = file.read(
                1024 * 1024
            )

            if not chunk:

                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


# ============================================================
# ISSUE ANALYSIS VALIDATION
# ============================================================

def validate_issue_file(
    path,
    case_id,
):

    result = (
        validate_issue_analysis(
            issue_path=
                Path(
                    path
                ),

            expected_case_id=
                case_id,

            raise_on_error=
                True,
        )
    )

    if (
        result.get(
            "valid"
        )
        is not True
    ):

        raise IssueSpottingApprovalError(
            "Issue Spotting Validator valid=False."
        )

    return result


# ============================================================
# APPROVAL SEMANTIC GUARD
# ============================================================

def validate_approval_semantics(
    analysis,
):

    if not isinstance(
        analysis,
        dict,
    ):

        raise IssueSpottingApprovalError(
            "Issue analysis dict değil."
        )

    if (
        analysis.get(
            "status"
        )
        not in {
            "completed",
            "partial",
        }
    ):

        raise IssueSpottingApprovalError(
            "Approval için issue analysis status "
            "completed/partial olmalıdır."
        )

    issues = analysis.get(
        "issues"
    )

    if not isinstance(
        issues,
        list,
    ):

        raise IssueSpottingApprovalError(
            "issues alanı list değil."
        )

    for issue in issues:

        if not isinstance(
            issue,
            dict,
        ):

            raise IssueSpottingApprovalError(
                "Issue kaydı dict değil."
            )

        # ====================================================
        # CANDIDATE STATUS GUARD
        # ====================================================

        if (
            issue.get(
                "status"
            )
            != "candidate"
        ):

            raise IssueSpottingApprovalError(
                "Approval yalnız status='candidate' "
                "issue kayıtlarını kabul edebilir."
            )

        # ====================================================
        # FORBIDDEN PHRASE GUARD (DEFENSE IN DEPTH)
        # ====================================================

        combined = normalize_text_tr(
            " ".join(
                [
                    str(
                        issue.get(
                            "title",
                            "",
                        )
                    ),

                    str(
                        issue.get(
                            "description",
                            "",
                        )
                    ),
                ]
            )
        )

        for phrase in FORBIDDEN_PHRASES:

            if phrase in combined:

                raise IssueSpottingApprovalError(
                    "Approval kesin hukuki sonuç ifadesi "
                    f"içeren issue'yu kabul edemez: "
                    f"{issue.get('issue_id')}"
                )

    return True


# ============================================================
# BACKUP CANONICAL
# ============================================================

def backup_canonical(
    case_id,
):

    canonical_path = (
        get_canonical_path(
            case_id
        )
    )

    if not canonical_path.exists():

        return None

    timestamp = (
        datetime.now()
        .astimezone()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    backup_path = (
        get_issues_dir(
            case_id
        )
        / (
            "issues.json.before_approval_"
            + timestamp
            + ".bak"
        )
    )

    shutil.copy2(
        canonical_path,
        backup_path,
    )

    return backup_path


# ============================================================
# AUDIT
# ============================================================

def write_approval_audit(
    case_id,
    pending_path,
    canonical_path,
    pending_sha256,
    canonical_sha256,
    previous_canonical_backup,
    analysis,
):

    reviews_dir = (
        get_reviews_dir(
            case_id
        )
    )

    reviews_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    now = (
        datetime.now()
        .astimezone()
    )

    timestamp = (
        now.strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    audit_path = (
        reviews_dir
        / (
            "issue_spotting_"
            + case_id
            + "_v1_"
            + timestamp
            + ".approval.json"
        )
    )

    issues = analysis.get(
        "issues",
        [],
    )

    audit = {
        "audit_type":
            "issue_spotting_analysis_approval",

        "approval_version":
            ISSUE_SPOTTING_APPROVAL_VERSION,

        "approved_at":
            now.isoformat(),

        "case_id":
            case_id,

        "issue_analysis_id":
            analysis.get(
                "issue_analysis_id"
            ),

        "source_pending_path":
            str(
                pending_path
            ),

        "canonical_path":
            str(
                canonical_path
            ),

        "pending_sha256":
            pending_sha256,

        "canonical_sha256":
            canonical_sha256,

        "content_identical":
            (
                pending_sha256
                == canonical_sha256
            ),

        "previous_canonical_backup":
            (
                str(
                    previous_canonical_backup
                )
                if previous_canonical_backup
                else None
            ),

        "issue_count":
            len(
                issues
            ),

        "issue_summaries": [
            {
                "issue_id":
                    issue.get(
                        "issue_id"
                    ),

                "issue_type":
                    issue.get(
                        "issue_type"
                    ),

                "trigger_rule_id":
                    issue.get(
                        "trigger_rule_id"
                    ),

                "status":
                    issue.get(
                        "status"
                    ),
            }
            for issue
            in issues
        ],

        "approval_semantics":
            (
                "Bu approval issue analysis kaydını "
                "canonical repository'ye kabul eder. "
                "Hiçbir issue candidate'ın maddi olarak "
                "doğru olduğu, hukuki bir sonuca vardığı, "
                "davanın sonucunu belirlediği veya kesin "
                "bir süre tespit ettiği anlamına gelmez."
            ),
    }

    atomic_write_json(
        audit_path,
        audit,
    )

    return audit_path


# ============================================================
# LOAD + VALIDATE PENDING
# ============================================================

def inspect_pending(
    case_id,
):

    pending_path = (
        get_pending_path(
            case_id
        )
    )

    if not pending_path.exists():

        raise IssueSpottingApprovalError(
            "Pending issue analysis bulunamadı:\n"
            f"{pending_path}"
        )

    validation = (
        validate_issue_file(
            path=
                pending_path,

            case_id=
                case_id,
        )
    )

    analysis = (
        load_json(
            pending_path
        )
    )

    validate_approval_semantics(
        analysis
    )

    return (
        pending_path,
        validation,
        analysis,
    )


# ============================================================
# REVIEW
# ============================================================

def run_review(
    case_id,
):

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - ISSUE SPOTTING APPROVAL V1"
    )

    print(
        " MODE: REVIEW"
    )

    print(
        "======================================"
    )

    (
        pending_path,
        validation,
        analysis,
    ) = inspect_pending(
        case_id
    )

    print(
        "Pending validator:",
        "PASS"
    )

    print(
        "Approval semantic guard:",
        "PASS"
    )

    print()

    print(
        "Case:",
        analysis[
            "case_id"
        ]
    )

    print(
        "Analysis ID:",
        analysis[
            "issue_analysis_id"
        ]
    )

    print(
        "Status:",
        analysis[
            "status"
        ]
    )

    print(
        "Issue count:",
        len(
            analysis[
                "issues"
            ]
        )
    )

    print()

    for issue in analysis[
        "issues"
    ]:

        print(
            "Issue:",
            issue[
                "issue_id"
            ]
        )

        print(
            "- type:",
            issue[
                "issue_type"
            ]
        )

        print(
            "- rule:",
            issue[
                "trigger_rule_id"
            ]
        )

        print(
            "- title:",
            issue[
                "title"
            ]
        )

        print(
            "- status:",
            issue[
                "status"
            ]
        )

        print()

    print(
        "Pending:"
    )

    print(
        pending_path
    )

    print()

    print(
        "Canonical target:"
    )

    print(
        get_canonical_path(
            case_id
        )
    )

    print()

    print(
        "MUTATION:"
    )

    print(
        "- yapılmadı"
    )

    print()

    print(
        "ÖNEMLİ:"
    )

    print(
        "- Bu approval hiçbir issue'yu verified fact "
        "yapmaz."
    )

    print(
        "- Legal conclusion veya deadline determination "
        "üretmez."
    )

    print(
        "- Pending içerik canonical'a aynen alınacaktır."
    )

    print()

    print(
        "Onay için:"
    )

    print(
        "python src\\issue_spotting_approval.py --approve"
    )

    print()

    print(
        "======================================"
    )

    print(
        " ISSUE SPOTTING APPROVAL V1: READY"
    )

    print(
        "======================================"
    )


# ============================================================
# APPROVE
# ============================================================

def run_approve(
    case_id,
):

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - ISSUE SPOTTING APPROVAL V1"
    )

    print(
        " MODE: APPROVE"
    )

    print(
        "======================================"
    )

    (
        pending_path,
        validation,
        analysis,
    ) = inspect_pending(
        case_id
    )

    canonical_path = (
        get_canonical_path(
            case_id
        )
    )

    pending_sha256 = (
        sha256_file(
            pending_path
        )
    )

    # ========================================================
    # BACKUP OLD CANONICAL
    # ========================================================

    previous_canonical_backup = (
        backup_canonical(
            case_id
        )
    )

    if previous_canonical_backup:

        print(
            "Previous canonical backup:",
            previous_canonical_backup
        )

    else:

        print(
            "Previous canonical:",
            "NONE"
        )

    # ========================================================
    # PROMOTE
    # ========================================================

    try:

        atomic_copy_file(
            source_path=
                pending_path,

            target_path=
                canonical_path,
        )

        # ====================================================
        # POST-WRITE VALIDATION
        # ====================================================

        validate_issue_file(
            path=
                canonical_path,

            case_id=
                case_id,
        )

        canonical_analysis = (
            load_json(
                canonical_path
            )
        )

        validate_approval_semantics(
            canonical_analysis
        )

        # ====================================================
        # BYTE IDENTITY
        # ====================================================

        canonical_sha256 = (
            sha256_file(
                canonical_path
            )
        )

        if (
            pending_sha256
            != canonical_sha256
        ):

            raise IssueSpottingApprovalError(
                "Pending ve canonical SHA256 eşit değil."
            )

    except Exception:

        if canonical_path.exists():

            canonical_path.unlink()

        if (
            previous_canonical_backup
            is not None
            and previous_canonical_backup.exists()
        ):

            shutil.copy2(
                previous_canonical_backup,
                canonical_path,
            )

        print()

        print(
            "APPROVAL FAIL"
        )

        print(
            "Rollback uygulandı."
        )

        raise

    # ========================================================
    # AUDIT
    # ========================================================

    try:

        audit_path = (
            write_approval_audit(
                case_id=
                    case_id,

                pending_path=
                    pending_path,

                canonical_path=
                    canonical_path,

                pending_sha256=
                    pending_sha256,

                canonical_sha256=
                    canonical_sha256,

                previous_canonical_backup=
                    previous_canonical_backup,

                analysis=
                    canonical_analysis,
            )
        )

    except Exception:

        if canonical_path.exists():

            canonical_path.unlink()

        if (
            previous_canonical_backup
            is not None
            and previous_canonical_backup.exists()
        ):

            shutil.copy2(
                previous_canonical_backup,
                canonical_path,
            )

        print()

        print(
            "AUDIT FAIL"
        )

        print(
            "Canonical rollback uygulandı."
        )

        raise

    # ========================================================
    # OUTPUT
    # ========================================================

    print()

    print(
        "ISSUE ANALYSIS APPROVED"
    )

    print(
        "Case:",
        canonical_analysis[
            "case_id"
        ]
    )

    print(
        "Analysis ID:",
        canonical_analysis[
            "issue_analysis_id"
        ]
    )

    print()

    for issue in canonical_analysis[
        "issues"
    ]:

        print(
            "Issue:",
            issue[
                "issue_id"
            ]
        )

        print(
            "- type:",
            issue[
                "issue_type"
            ]
        )

        print(
            "- status:",
            issue[
                "status"
            ]
        )

        print()

    print(
        "Canonical:"
    )

    print(
        canonical_path
    )

    print()

    print(
        "Pending SHA256:",
        pending_sha256
    )

    print(
        "Canonical SHA256:",
        canonical_sha256
    )

    print(
        "Content identical:",
        (
            pending_sha256
            == canonical_sha256
        )
    )

    print()

    print(
        "Audit:"
    )

    print(
        audit_path
    )

    print()

    print(
        "SEMANTIC NOTE:"
    )

    print(
        "- Hiçbir issue verified fact DEĞİLDİR."
    )

    print(
        "- Legal conclusion veya deadline determination "
        "içermez."
    )

    print(
        "- Approval yalnız analysis kaydını canonical "
        "yaptı."
    )

    print()

    print(
        "======================================"
    )

    print(
        " ISSUE SPOTTING APPROVAL V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Issue Spotting Approval V1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=
            DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--approve",
        action="store_true",
    )

    args = parser.parse_args()

    if args.approve:

        run_approve(
            case_id=
                args.case_id
        )

    else:

        run_review(
            case_id=
                args.case_id
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print()

        print(
            "ERROR:"
        )

        print(
            error
        )

        print()

        print(
            "======================================"
        )

        print(
            " ISSUE SPOTTING APPROVAL V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )
