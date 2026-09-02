# ============================================================
# VERGİ AI - CASE LAW APPROVAL V1
#
# AMAÇ
# ----
#
# Case Law Engine V1 tarafından üretilmiş:
#
#   case_law_<case_id>_v1.json.pending
#
# dosyasını human review sonrası:
#
#   case_law.json
#
# canonical repository kaydına promote etmek.
#
#
# ÖNEMLİ SEMANTİK
# ----------------
#
# Case law analysis approval:
#
#   != gerçek bir mahkeme kararının doğrulanması
#   != bir emsalin uyuşmazlığa uygulanabilir olduğunun
#      kesinleşmesi
#   != case outcome belirlenmesi
#
# Bir case-law candidate'ın approval'ı yalnız:
#
#   "Bu araştırma adayları/coverage kayıtları, davada
#    değerlendirilmesi gereken noktalar olarak canonical
#    çalışma verisine kabul edilmiştir."
#
# anlamına gelir.
#
#
# GÜVENLİK
# --------
#
# - Varsayılan REVIEW modudur.
# - Mutation yalnız --approve ile yapılır.
# - Pending Case Law Validator V1'den geçmelidir.
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


from case_law_validator import (
    validate_case_law_analysis,
)


# ============================================================
# VERSION
# ============================================================

CASE_LAW_APPROVAL_VERSION = "1"


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

class CaseLawApprovalError(
    Exception
):
    pass


# ============================================================
# PATH HELPERS
# ============================================================

def get_case_law_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "case_law"
    )


def get_pending_path(
    case_id,
):

    return (
        get_case_law_dir(
            case_id
        )
        / (
            f"case_law_{case_id}_v1.json.pending"
        )
    )


def get_canonical_path(
    case_id,
):

    return (
        get_case_law_dir(
            case_id
        )
        / "case_law.json"
    )


def get_reviews_dir(
    case_id,
):

    return (
        get_case_law_dir(
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
# CASE LAW ANALYSIS VALIDATION
# ============================================================

def validate_case_law_file(
    path,
    case_id,
):

    result = (
        validate_case_law_analysis(
            case_law_path=
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

        raise CaseLawApprovalError(
            "Case Law Validator valid=False."
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

        raise CaseLawApprovalError(
            "Case law analysis dict değil."
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

        raise CaseLawApprovalError(
            "Approval için case law analysis status "
            "completed/partial olmalıdır."
        )

    coverage_records = analysis.get(
        "case_law_coverage"
    )

    decision_records = analysis.get(
        "case_law_decisions"
    )

    suggestion_records = analysis.get(
        "case_law_agent_suggestions"
    )

    if not isinstance(
        coverage_records,
        list,
    ):

        raise CaseLawApprovalError(
            "case_law_coverage alanı list değil."
        )

    if not isinstance(
        decision_records,
        list,
    ):

        raise CaseLawApprovalError(
            "case_law_decisions alanı list değil."
        )

    if not isinstance(
        suggestion_records,
        list,
    ):

        raise CaseLawApprovalError(
            "case_law_agent_suggestions alanı list değil."
        )

    for record_list, id_field in (
        (
            coverage_records,
            "coverage_id",
        ),

        (
            decision_records,
            "decision_id",
        ),

        (
            suggestion_records,
            "suggestion_id",
        ),
    ):

        for record in record_list:

            if not isinstance(
                record,
                dict,
            ):

                raise CaseLawApprovalError(
                    "Case law kaydı dict değil."
                )

            if (
                record.get(
                    "status"
                )
                != "candidate"
            ):

                raise CaseLawApprovalError(
                    "Approval yalnız status='candidate' "
                    "case law kayıtlarını kabul edebilir: "
                    f"{record.get(id_field)}"
                )

            if (
                record.get(
                    "requires_human_review"
                )
                is not True
            ):

                raise CaseLawApprovalError(
                    "Approval requires_human_review=True "
                    "DIŞINDA bir kaydı kabul edemez: "
                    f"{record.get(id_field)}"
                )

    for suggestion in suggestion_records:

        forbidden_keys = {
            "court_name",
            "court_unit",
            "case_number",
            "decision_number",
            "decision_date",
            "source_url",
            "source_document_id",
        } & set(
            suggestion.keys()
        )

        if forbidden_keys:

            raise CaseLawApprovalError(
                "Agent suggestion court metadata alanı "
                f"taşıyor: {forbidden_keys} - "
                f"{suggestion.get('suggestion_id')}"
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
        get_case_law_dir(
            case_id
        )
        / (
            "case_law.json.before_approval_"
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
            "case_law_"
            + case_id
            + "_v1_"
            + timestamp
            + ".approval.json"
        )
    )

    coverage_records = analysis.get(
        "case_law_coverage",
        [],
    )

    decision_records = analysis.get(
        "case_law_decisions",
        [],
    )

    suggestion_records = analysis.get(
        "case_law_agent_suggestions",
        [],
    )

    audit = {
        "audit_type":
            "case_law_analysis_approval",

        "approval_version":
            CASE_LAW_APPROVAL_VERSION,

        "approved_at":
            now.isoformat(),

        "case_id":
            case_id,

        "case_law_analysis_id":
            analysis.get(
                "case_law_analysis_id"
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

        "coverage_count":
            len(
                coverage_records
            ),

        "decision_count":
            len(
                decision_records
            ),

        "agent_suggestion_count":
            len(
                suggestion_records
            ),

        "coverage_summaries": [
            {
                "coverage_id":
                    coverage.get(
                        "coverage_id"
                    ),

                "source_issue_id":
                    coverage.get(
                        "source_issue_id"
                    ),

                "execution_state":
                    coverage.get(
                        "execution_state"
                    ),

                "decision_count":
                    coverage.get(
                        "decision_count"
                    ),

                "trigger_rule_id":
                    coverage.get(
                        "trigger_rule_id"
                    ),
            }
            for coverage
            in coverage_records
        ],

        "decision_summaries": [
            {
                "decision_id":
                    decision.get(
                        "decision_id"
                    ),

                "source_issue_id":
                    decision.get(
                        "source_issue_id"
                    ),

                "source_document_id":
                    decision.get(
                        "source_document_id"
                    ),

                "court_name":
                    decision.get(
                        "court_name"
                    ),
            }
            for decision
            in decision_records
        ],

        "approval_semantics":
            (
                "Bu approval case law analysis kaydını "
                "canonical repository'ye kabul eder. "
                "Hiçbir case-law candidate'ın gerçek bir "
                "mahkeme kararı olduğunu (belge_turu="
                "'Yargı Kararı' + canonical documents.json "
                "grounding hariç), bir emsalin "
                "uyuşmazlığa uygulanabilir olduğunu veya "
                "davanın sonucunu kesinleştirdiği anlamına "
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

        raise CaseLawApprovalError(
            "Pending case law analysis bulunamadı:\n"
            f"{pending_path}"
        )

    validation = (
        validate_case_law_file(
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
        " VERGİ AI - CASE LAW APPROVAL V1"
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
            "case_law_analysis_id"
        ]
    )

    print(
        "Status:",
        analysis[
            "status"
        ]
    )

    print(
        "Coverage count:",
        len(
            analysis[
                "case_law_coverage"
            ]
        )
    )

    print(
        "Decision count:",
        len(
            analysis[
                "case_law_decisions"
            ]
        )
    )

    print(
        "Agent suggestion count:",
        len(
            analysis[
                "case_law_agent_suggestions"
            ]
        )
    )

    print()

    for coverage in analysis[
        "case_law_coverage"
    ]:

        print(
            "Coverage:",
            coverage[
                "coverage_id"
            ]
        )

        print(
            "- issue:",
            coverage[
                "source_issue_id"
            ]
        )

        print(
            "- execution_state:",
            coverage[
                "execution_state"
            ]
        )

        print(
            "- decision_count:",
            coverage[
                "decision_count"
            ]
        )

        print(
            "- status:",
            coverage[
                "status"
            ]
        )

        print()

    for decision in analysis[
        "case_law_decisions"
    ]:

        print(
            "Decision:",
            decision[
                "decision_id"
            ]
        )

        print(
            "- issue:",
            decision[
                "source_issue_id"
            ]
        )

        print(
            "- source_document_id:",
            decision[
                "source_document_id"
            ]
        )

        print(
            "- court_name:",
            decision[
                "court_name"
            ]
        )

        print(
            "- status:",
            decision[
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
        "- Bu approval hiçbir mahkeme kararının "
        "doğrulandığını kesinleştirmez (yalnızca "
        "documents.json grounding zaten var olan "
        "kayıtlar için geçerlidir)."
    )

    print(
        "- Bir emsalin uygulanabilirliğini veya case "
        "outcome'u üretmez."
    )

    print(
        "- Pending içerik canonical'a aynen alınacaktır."
    )

    print()

    print(
        "Onay için:"
    )

    print(
        "python src\\case_law_approval.py --approve"
    )

    print()

    print(
        "======================================"
    )

    print(
        " CASE LAW APPROVAL V1: READY"
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
        " VERGİ AI - CASE LAW APPROVAL V1"
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

        validate_case_law_file(
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

            raise CaseLawApprovalError(
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
        "CASE LAW ANALYSIS APPROVED"
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
            "case_law_analysis_id"
        ]
    )

    print()

    for coverage in canonical_analysis[
        "case_law_coverage"
    ]:

        print(
            "Coverage:",
            coverage[
                "coverage_id"
            ]
        )

        print(
            "- issue:",
            coverage[
                "source_issue_id"
            ]
        )

        print(
            "- execution_state:",
            coverage[
                "execution_state"
            ]
        )

        print(
            "- status:",
            coverage[
                "status"
            ]
        )

        print()

    for decision in canonical_analysis[
        "case_law_decisions"
    ]:

        print(
            "Decision:",
            decision[
                "decision_id"
            ]
        )

        print(
            "- issue:",
            decision[
                "source_issue_id"
            ]
        )

        print(
            "- source_document_id:",
            decision[
                "source_document_id"
            ]
        )

        print(
            "- status:",
            decision[
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
        "- Hiçbir mahkeme kararının uyuşmazlığa "
        "uygulanabilir olduğu KESİNLEŞMEDİ."
    )

    print(
        "- Case outcome içermez."
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
        " CASE LAW APPROVAL V1: PASS"
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
            "Vergi AI Case Law Approval V1"
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
            " CASE LAW APPROVAL V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )
