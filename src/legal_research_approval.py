# ============================================================
# VERGİ AI - LEGAL RESEARCH APPROVAL V1
#
# AMAÇ
# ----
#
# Legal Research Engine V1 tarafından üretilmiş:
#
#   legal_research_<case_id>_v1.json.pending
#
# dosyasını human review sonrası:
#
#   research.json
#
# canonical repository kaydına promote etmek.
#
#
# ÖNEMLİ SEMANTİK
# ----------------
#
# Research analysis approval:
#
#   != bir hükmün yürürlükte olduğunun kesinleşmesi
#   != applicability'nin kesinleşmesi
#   != case outcome belirlenmesi
#   != kesin hukuki sonuç
#
# Bir research candidate'ın approval'ı yalnız:
#
#   "Bu araştırma adayları, davada değerlendirilmesi gereken
#    hukuki dayanak/nokta olarak canonical çalışma verisine
#    kabul edilmiştir."
#
# anlamına gelir.
#
#
# GÜVENLİK
# --------
#
# - Varsayılan REVIEW modudur.
# - Mutation yalnız --approve ile yapılır.
# - Pending Legal Research Validator V1'den geçmelidir.
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


from legal_research_validator import (
    validate_research_analysis,
)


# ============================================================
# VERSION
# ============================================================

LEGAL_RESEARCH_APPROVAL_VERSION = "1"


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

class LegalResearchApprovalError(
    Exception
):
    pass


# ============================================================
# PATH HELPERS
# ============================================================

def get_research_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "research"
    )


def get_pending_path(
    case_id,
):

    return (
        get_research_dir(
            case_id
        )
        / (
            f"legal_research_{case_id}_v1.json.pending"
        )
    )


def get_canonical_path(
    case_id,
):

    return (
        get_research_dir(
            case_id
        )
        / "research.json"
    )


def get_reviews_dir(
    case_id,
):

    return (
        get_research_dir(
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
# RESEARCH ANALYSIS VALIDATION
# ============================================================

def validate_research_file(
    path,
    case_id,
):

    result = (
        validate_research_analysis(
            research_path=
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

        raise LegalResearchApprovalError(
            "Legal Research Validator valid=False."
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

        raise LegalResearchApprovalError(
            "Research analysis dict değil."
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

        raise LegalResearchApprovalError(
            "Approval için research analysis status "
            "completed/partial olmalıdır."
        )

    research_candidates = analysis.get(
        "research_candidates"
    )

    if not isinstance(
        research_candidates,
        list,
    ):

        raise LegalResearchApprovalError(
            "research_candidates alanı list değil."
        )

    for research in research_candidates:

        if not isinstance(
            research,
            dict,
        ):

            raise LegalResearchApprovalError(
                "Research kaydı dict değil."
            )

        if (
            research.get(
                "status"
            )
            != "candidate"
        ):

            raise LegalResearchApprovalError(
                "Approval yalnız status='candidate' "
                "research kayıtlarını kabul edebilir."
            )

        if (
            research.get(
                "research_type"
            )
            == "agent_suggestion"
            and (
                research.get(
                    "formal_result"
                )
                is not None
                or research.get(
                    "applicability_result"
                )
                is not None
                or research.get(
                    "resolved_provision_ids"
                )
            )
        ):

            raise LegalResearchApprovalError(
                "Agent-sourced research candidate "
                "formal_result/applicability_result/"
                "resolved_provision_ids taşıyamaz: "
                f"{research.get('research_id')}"
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
        get_research_dir(
            case_id
        )
        / (
            "research.json.before_approval_"
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
            "legal_research_"
            + case_id
            + "_v1_"
            + timestamp
            + ".approval.json"
        )
    )

    research_candidates = analysis.get(
        "research_candidates",
        [],
    )

    audit = {
        "audit_type":
            "legal_research_analysis_approval",

        "approval_version":
            LEGAL_RESEARCH_APPROVAL_VERSION,

        "approved_at":
            now.isoformat(),

        "case_id":
            case_id,

        "research_analysis_id":
            analysis.get(
                "research_analysis_id"
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

        "research_candidate_count":
            len(
                research_candidates
            ),

        "research_summaries": [
            {
                "research_id":
                    research.get(
                        "research_id"
                    ),

                "source_issue_id":
                    research.get(
                        "source_issue_id"
                    ),

                "finding_status":
                    research.get(
                        "finding_status"
                    ),

                "trigger_rule_id":
                    research.get(
                        "trigger_rule_id"
                    ),

                "status":
                    research.get(
                        "status"
                    ),
            }
            for research
            in research_candidates
        ],

        "approval_semantics":
            (
                "Bu approval research analysis kaydını "
                "canonical repository'ye kabul eder. "
                "Hiçbir research candidate'ın bir hükmün "
                "yürürlükte olduğunu, uygulanabilir "
                "olduğunu, davanın sonucunu veya kesin bir "
                "hukuki sonucu kesinleştirdiği anlamına "
                "gelmez."
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

        raise LegalResearchApprovalError(
            "Pending research analysis bulunamadı:\n"
            f"{pending_path}"
        )

    validation = (
        validate_research_file(
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
        " VERGİ AI - LEGAL RESEARCH APPROVAL V1"
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
            "research_analysis_id"
        ]
    )

    print(
        "Status:",
        analysis[
            "status"
        ]
    )

    print(
        "Research candidate count:",
        len(
            analysis[
                "research_candidates"
            ]
        )
    )

    print()

    for research in analysis[
        "research_candidates"
    ]:

        print(
            "Research:",
            research[
                "research_id"
            ]
        )

        print(
            "- issue:",
            research[
                "source_issue_id"
            ]
        )

        print(
            "- finding_status:",
            research[
                "finding_status"
            ]
        )

        print(
            "- trigger:",
            research[
                "trigger_rule_id"
            ]
        )

        print(
            "- status:",
            research[
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
        "- Bu approval hiçbir hükmün yürürlükte olduğunu "
        "kesinleştirmez."
    )

    print(
        "- Applicability veya case outcome üretmez."
    )

    print(
        "- Pending içerik canonical'a aynen alınacaktır."
    )

    print()

    print(
        "Onay için:"
    )

    print(
        "python src\\legal_research_approval.py --approve"
    )

    print()

    print(
        "======================================"
    )

    print(
        " LEGAL RESEARCH APPROVAL V1: READY"
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
        " VERGİ AI - LEGAL RESEARCH APPROVAL V1"
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

    try:

        atomic_copy_file(
            source_path=
                pending_path,

            target_path=
                canonical_path,
        )

        validate_research_file(
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

        canonical_sha256 = (
            sha256_file(
                canonical_path
            )
        )

        if (
            pending_sha256
            != canonical_sha256
        ):

            raise LegalResearchApprovalError(
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

    print()

    print(
        "RESEARCH ANALYSIS APPROVED"
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
            "research_analysis_id"
        ]
    )

    print()

    for research in canonical_analysis[
        "research_candidates"
    ]:

        print(
            "Research:",
            research[
                "research_id"
            ]
        )

        print(
            "- issue:",
            research[
                "source_issue_id"
            ]
        )

        print(
            "- status:",
            research[
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
        "- Hiçbir hükmün yürürlükte olduğu "
        "KESİNLEŞMEDİ."
    )

    print(
        "- Applicability veya case outcome içermez."
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
        " LEGAL RESEARCH APPROVAL V1: PASS"
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
            "Vergi AI Legal Research Approval V1"
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
            " LEGAL RESEARCH APPROVAL V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )
