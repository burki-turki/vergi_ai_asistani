# ============================================================
# VERGİ AI - DEADLINE APPROVAL V1
#
# AMAÇ
# ----
#
# Deadline Engine V1 tarafından üretilmiş:
#
#   deadline_<case_id>_v1.json.pending
#
# dosyasını human review sonrası:
#
#   deadline.json
#
# canonical repository kaydına promote etmek.
#
#
# ÖNEMLİ SEMANTİK
# ----------------
#
# Deadline analysis approval:
#
#   != anchor event verification
#   != tebliğ tarihinin doğrulanması
#   != deadline'ın hukuken kesinleşmesi
#
# Örneğin:
#
#   blocked_unverified_anchor
#
# durumundaki bir pending kaydın approval'ı yalnız:
#
#   "Sistem, doğrulanmamış anchor nedeniyle hesap yapmamakta
#    doğru davranmıştır."
#
# anlamına gelir.
#
#
# GÜVENLİK
# --------
#
# - Varsayılan REVIEW modudur.
# - Mutation yalnız --approve ile yapılır.
# - Pending Deadline Validator V1'den geçmelidir.
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


from deadline_validator import (
    validate_deadline_analysis,
)


# ============================================================
# VERSION
# ============================================================

DEADLINE_APPROVAL_VERSION = "1"


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

class DeadlineApprovalError(
    Exception
):
    pass


# ============================================================
# PATH HELPERS
# ============================================================

def get_deadline_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "deadlines"
    )


def get_pending_path(
    case_id,
):

    return (
        get_deadline_dir(
            case_id
        )
        / (
            f"deadline_{case_id}_v1.json.pending"
        )
    )


def get_canonical_path(
    case_id,
):

    return (
        get_deadline_dir(
            case_id
        )
        / "deadline.json"
    )


def get_reviews_dir(
    case_id,
):

    return (
        get_deadline_dir(
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
# DEADLINE VALIDATION
# ============================================================

def validate_deadline_file(
    path,
    case_id,
):

    result = (
        validate_deadline_analysis(
            deadline_path=
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

        raise DeadlineApprovalError(
            "Deadline Validator valid=False."
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

        raise DeadlineApprovalError(
            "Deadline analysis dict değil."
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

        raise DeadlineApprovalError(
            "Approval için deadline analysis "
            "status completed/partial olmalıdır."
        )

    deadlines = analysis.get(
        "deadlines"
    )

    if (
        not isinstance(
            deadlines,
            list,
        )
        or len(
            deadlines
        )
        == 0
    ):

        raise DeadlineApprovalError(
            "Approval için en az bir deadline kaydı gerekir."
        )

    for deadline in deadlines:

        if not isinstance(
            deadline,
            dict,
        ):

            raise DeadlineApprovalError(
                "Deadline kaydı dict değil."
            )

        state = deadline.get(
            "calculation_state"
        )

        calculated_deadline = deadline.get(
            "calculated_deadline"
        )

        anchor_verification = deadline.get(
            "anchor_verification_state"
        )

        requires_human_review = deadline.get(
            "requires_human_review"
        )

        # ====================================================
        # UNVERIFIED ANCHOR SAFETY
        # ====================================================

        if (
            anchor_verification
            != "verified"
            and state
            == "calculated"
        ):

            raise DeadlineApprovalError(
                "Unverified anchor üzerinden calculated "
                "deadline approval edilemez."
            )

        if (
            anchor_verification
            != "verified"
            and calculated_deadline
            is not None
        ):

            raise DeadlineApprovalError(
                "Unverified anchor deadline value içeriyor."
            )

        # ====================================================
        # BLOCKED UNVERIFIED ANCHOR
        # ====================================================

        if (
            state
            == "blocked_unverified_anchor"
        ):

            if calculated_deadline is not None:

                raise DeadlineApprovalError(
                    "blocked_unverified_anchor için "
                    "calculated_deadline null olmalıdır."
                )

            if (
                requires_human_review
                is not True
            ):

                raise DeadlineApprovalError(
                    "blocked_unverified_anchor için "
                    "requires_human_review=True olmalıdır."
                )

        # ====================================================
        # OTHER FAIL-CLOSED STATES
        # ====================================================

        if (
            state
            in {
                "blocked_missing_rule",
                "blocked_ambiguous_rule",
                "needs_review",
                "not_applicable",
            }
            and calculated_deadline
            is not None
        ):

            raise DeadlineApprovalError(
                f"{state} durumunda calculated_deadline "
                "null olmalıdır."
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
        get_deadline_dir(
            case_id
        )
        / (
            "deadline.json.before_approval_"
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
            "deadline_"
            + case_id
            + "_v1_"
            + timestamp
            + ".approval.json"
        )
    )

    deadlines = analysis.get(
        "deadlines",
        []
    )

    audit = {
        "audit_type":
            "deadline_analysis_approval",

        "approval_version":
            DEADLINE_APPROVAL_VERSION,

        "approved_at":
            now.isoformat(),

        "case_id":
            case_id,

        "deadline_analysis_id":
            analysis.get(
                "deadline_analysis_id"
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

        "deadline_count":
            len(
                deadlines
            ),

        "deadline_states": [
            {
                "deadline_id":
                    deadline.get(
                        "deadline_id"
                    ),

                "anchor_event_id":
                    deadline.get(
                        "anchor_event_id"
                    ),

                "anchor_verification_state":
                    deadline.get(
                        "anchor_verification_state"
                    ),

                "rule_id":
                    deadline.get(
                        "rule_id"
                    ),

                "calculation_state":
                    deadline.get(
                        "calculation_state"
                    ),

                "calculated_deadline":
                    deadline.get(
                        "calculated_deadline"
                    ),

                "requires_human_review":
                    deadline.get(
                        "requires_human_review"
                    ),
            }
            for deadline
            in deadlines
        ],

        "approval_semantics":
            (
                "Bu approval deadline analysis kaydını "
                "canonical repository'ye kabul eder. "
                "Anchor event verification değildir ve "
                "hesaplanmamış bir deadline'ı hesaplanmış "
                "hale getirmez."
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

        raise DeadlineApprovalError(
            "Pending deadline analysis bulunamadı:\n"
            f"{pending_path}"
        )

    validation = (
        validate_deadline_file(
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
        " VERGİ AI - DEADLINE APPROVAL V1"
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
            "deadline_analysis_id"
        ]
    )

    print(
        "Status:",
        analysis[
            "status"
        ]
    )

    print(
        "Deadline count:",
        len(
            analysis[
                "deadlines"
            ]
        )
    )

    print()

    for deadline in analysis[
        "deadlines"
    ]:

        print(
            "Deadline:",
            deadline[
                "deadline_id"
            ]
        )

        print(
            "- anchor:",
            deadline[
                "anchor_event_id"
            ]
        )

        print(
            "- anchor date:",
            deadline[
                "anchor_date"
            ]
        )

        print(
            "- anchor verification:",
            deadline[
                "anchor_verification_state"
            ]
        )

        print(
            "- rule:",
            deadline[
                "rule_id"
            ]
        )

        print(
            "- calculation state:",
            deadline[
                "calculation_state"
            ]
        )

        print(
            "- calculated deadline:",
            deadline[
                "calculated_deadline"
            ]
        )

        print(
            "- human review:",
            deadline[
                "requires_human_review"
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
        "- Bu approval anchor event'i verified yapmaz."
    )

    print(
        "- calculated_deadline üretmez veya değiştirmez."
    )

    print(
        "- Pending içerik canonical'a aynen alınacaktır."
    )

    print()

    print(
        "Onay için:"
    )

    print(
        "python src\\deadline_approval.py --approve"
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE APPROVAL V1: READY"
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
        " VERGİ AI - DEADLINE APPROVAL V1"
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

        post_validation = (
            validate_deadline_file(
                path=
                    canonical_path,

                case_id=
                    case_id,
            )
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

            raise DeadlineApprovalError(
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

        # Audit olmadan approval tamamlanmış sayılmaz.

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
        "DEADLINE ANALYSIS APPROVED"
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
            "deadline_analysis_id"
        ]
    )

    print()

    for deadline in canonical_analysis[
        "deadlines"
    ]:

        print(
            "Deadline:",
            deadline[
                "deadline_id"
            ]
        )

        print(
            "- anchor event:",
            deadline[
                "anchor_event_id"
            ]
        )

        print(
            "- anchor verification:",
            deadline[
                "anchor_verification_state"
            ]
        )

        print(
            "- rule:",
            deadline[
                "rule_id"
            ]
        )

        print(
            "- calculation state:",
            deadline[
                "calculation_state"
            ]
        )

        print(
            "- calculated deadline:",
            deadline[
                "calculated_deadline"
            ]
        )

        print(
            "- human review:",
            deadline[
                "requires_human_review"
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
        "- Anchor verification DEĞİŞMEDİ."
    )

    print(
        "- Deadline calculation state DEĞİŞMEDİ."
    )

    print(
        "- Approval yalnız analysis kaydını canonical yaptı."
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE APPROVAL V1: PASS"
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
            "Vergi AI Deadline Approval V1"
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
            " DEADLINE APPROVAL V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )