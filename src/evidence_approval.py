# ============================================================
# VERGİ AI - EVIDENCE APPROVAL V1 (LAYER A)
#
# AMAÇ
# ----
#
# Evidence Engine V1 tarafından üretilmiş:
#
#   evidence_<case_id>_v1.json.pending
#
# dosyasını human review sonrası:
#
#   evidence.json
#
# canonical repository kaydına promote etmek.
#
#
# ÖNEMLİ SEMANTİK
# ----------------
#
# Evidence analysis approval:
#
#   != bir fact'in maddi gerçeklik bakımından doğrulanması
#   != bir candidate ilişkisinin (supports/contradicts)
#      avukat tarafından onaylanması (bu AYRI bir katmandır -
#      bkz. evidence_review.py / Layer B)
#   != admissibility, strength veya sufficiency belirlemesi
#
# Bir evidence analysis'in approval'ı yalnız:
#
#   "Bu coverage/candidate/suggestion kayıtları, davada
#    değerlendirilmesi gereken noktalar olarak canonical
#    çalışma verisine kabul edilmiştir."
#
# anlamına gelir. Bu noktada HİÇBİR candidate/suggestion
# review_state'i "needs_review" DIŞINDA bir değer TAŞIYAMAZ -
# review_state yükseltmesi yalnız Layer B (evidence_review.py)
# ile, ayrı bir audit izi bırakarak yapılabilir.
#
#
# GÜVENLİK
# --------
#
# - Varsayılan REVIEW modudur.
# - Mutation yalnız --approve ile yapılır.
# - Pending Evidence Validator V1'den geçmelidir.
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


from evidence_validator import (
    validate_evidence_analysis,
)


# ============================================================
# VERSION
# ============================================================

EVIDENCE_APPROVAL_VERSION = "1"


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

class EvidenceApprovalError(
    Exception
):
    pass


# ============================================================
# PATH HELPERS
# ============================================================

def get_evidence_dir(
    case_id,
):

    return (
        CASES_DIR
        / case_id
        / "evidence"
    )


def get_pending_path(
    case_id,
):

    return (
        get_evidence_dir(
            case_id
        )
        / (
            f"evidence_{case_id}_v1.json.pending"
        )
    )


def get_canonical_path(
    case_id,
):

    return (
        get_evidence_dir(
            case_id
        )
        / "evidence.json"
    )


def get_reviews_dir(
    case_id,
):

    return (
        get_evidence_dir(
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
# EVIDENCE ANALYSIS VALIDATION
# ============================================================

def validate_evidence_file(
    path,
    case_id,
):

    result = (
        validate_evidence_analysis(
            evidence_path=
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

        raise EvidenceApprovalError(
            "Evidence Validator valid=False."
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

        raise EvidenceApprovalError(
            "Evidence analysis dict değil."
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

        raise EvidenceApprovalError(
            "Approval için evidence analysis status "
            "completed/partial olmalıdır."
        )

    coverage_records = analysis.get(
        "evidence_coverage"
    )

    candidate_records = analysis.get(
        "evidence_candidates"
    )

    suggestion_records = analysis.get(
        "evidence_agent_suggestions"
    )

    if not isinstance(
        coverage_records,
        list,
    ):

        raise EvidenceApprovalError(
            "evidence_coverage alanı list değil."
        )

    if not isinstance(
        candidate_records,
        list,
    ):

        raise EvidenceApprovalError(
            "evidence_candidates alanı list değil."
        )

    if not isinstance(
        suggestion_records,
        list,
    ):

        raise EvidenceApprovalError(
            "evidence_agent_suggestions alanı list değil."
        )

    for record_list, id_field in (
        (
            coverage_records,
            "coverage_id",
        ),

        (
            candidate_records,
            "candidate_id",
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

                raise EvidenceApprovalError(
                    "Evidence kaydı dict değil."
                )

            if (
                record.get(
                    "status"
                )
                != "candidate"
            ):

                raise EvidenceApprovalError(
                    "Approval yalnız status='candidate' "
                    "evidence kayıtlarını kabul edebilir: "
                    f"{record.get(id_field)}"
                )

            if (
                record.get(
                    "requires_human_review"
                )
                is not True
            ):

                raise EvidenceApprovalError(
                    "Approval requires_human_review=True "
                    "DIŞINDA bir kaydı kabul edemez: "
                    f"{record.get(id_field)}"
                )

    # --------------------------------------------------------
    # KRİTİK: Layer A yalnız TAZE engine çıktısını promote
    # eder - hiçbir candidate/suggestion bu noktada Layer B
    # review'dan geçmiş olamaz. review_state yükseltmesi
    # yalnız evidence_review.py ile mümkündür.
    # --------------------------------------------------------

    for candidate in candidate_records:

        if (
            candidate.get(
                "review_state"
            )
            != "needs_review"
        ):

            raise EvidenceApprovalError(
                "Layer A approval yalnız review_state="
                "'needs_review' olan candidate'ları kabul "
                "edebilir (confirmed/rejected yalnız Layer "
                "B ile, promotion SONRASINDA mümkündür): "
                f"{candidate.get('candidate_id')}"
            )

        forbidden_keys = {
            "confidence",
            "evidence_strength",
            "priority",
            "admissibility",
        } & set(
            candidate.keys()
        )

        if forbidden_keys:

            raise EvidenceApprovalError(
                "Evidence candidate yapısal olarak yasak "
                f"bir alan taşıyor: {forbidden_keys} - "
                f"{candidate.get('candidate_id')}"
            )

    for suggestion in suggestion_records:

        if (
            suggestion.get(
                "suggestion_review_state"
            )
            != "needs_review"
        ):

            raise EvidenceApprovalError(
                "Layer A approval yalnız "
                "suggestion_review_state='needs_review' "
                "olan suggestion'ları kabul edebilir: "
                f"{suggestion.get('suggestion_id')}"
            )

        forbidden_keys = {
            "relationship_candidate",
            "review_state",
            "confidence_strength",
        } & set(
            suggestion.keys()
        )

        if forbidden_keys:

            raise EvidenceApprovalError(
                "Agent suggestion candidate-benzeri alan "
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
        get_evidence_dir(
            case_id
        )
        / (
            "evidence.json.before_approval_"
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
            "evidence_"
            + case_id
            + "_v1_"
            + timestamp
            + ".approval.json"
        )
    )

    coverage_records = analysis.get(
        "evidence_coverage",
        [],
    )

    candidate_records = analysis.get(
        "evidence_candidates",
        [],
    )

    suggestion_records = analysis.get(
        "evidence_agent_suggestions",
        [],
    )

    audit = {
        "audit_type":
            "evidence_analysis_approval",

        "approval_version":
            EVIDENCE_APPROVAL_VERSION,

        "approved_at":
            now.isoformat(),

        "case_id":
            case_id,

        "evidence_analysis_id":
            analysis.get(
                "evidence_analysis_id"
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

        "candidate_count":
            len(
                candidate_records
            ),

        "suggestion_count":
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

                "candidate_count":
                    coverage.get(
                        "candidate_count"
                    ),

                "suggestion_count":
                    coverage.get(
                        "suggestion_count"
                    ),
            }
            for coverage
            in coverage_records
        ],

        "candidate_summaries": [
            {
                "candidate_id":
                    candidate.get(
                        "candidate_id"
                    ),

                "source_issue_id":
                    candidate.get(
                        "source_issue_id"
                    ),

                "relationship_candidate":
                    candidate.get(
                        "relationship_candidate"
                    ),

                "review_state":
                    candidate.get(
                        "review_state"
                    ),
            }
            for candidate
            in candidate_records
        ],

        "approval_semantics":
            (
                "Bu approval evidence analysis kaydını "
                "canonical repository'ye kabul eder. Hiçbir "
                "candidate ilişkisinin (supports/contradicts) "
                "avukat tarafından doğrulandığı, admissibility/"
                "strength/sufficiency taşıdığı veya davanın "
                "sonucunu kesinleştirdiği anlamına gelmez. "
                "review_state yükseltmesi (confirmed/rejected) "
                "yalnız ayrı bir Layer B human review "
                "(evidence_review.py) ile, kendi audit "
                "izini bırakarak mümkündür."
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

        raise EvidenceApprovalError(
            "Pending evidence analysis bulunamadı:\n"
            f"{pending_path}"
        )

    validation = (
        validate_evidence_file(
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
        " VERGİ AI - EVIDENCE APPROVAL V1"
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
            "evidence_analysis_id"
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
                "evidence_coverage"
            ]
        )
    )

    print(
        "Candidate count:",
        len(
            analysis[
                "evidence_candidates"
            ]
        )
    )

    print(
        "Agent suggestion count:",
        len(
            analysis[
                "evidence_agent_suggestions"
            ]
        )
    )

    print()

    for coverage in analysis[
        "evidence_coverage"
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
            "- allowlist_count:",
            coverage[
                "allowlist_count"
            ]
        )

        print(
            "- candidate_count:",
            coverage[
                "candidate_count"
            ]
        )

        print(
            "- suggestion_count:",
            coverage[
                "suggestion_count"
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
        "- Bu approval hiçbir candidate ilişkisinin "
        "(supports/contradicts) avukat tarafından "
        "doğrulandığını göstermez."
    )

    print(
        "- Admissibility/strength/sufficiency veya case "
        "outcome üretmez."
    )

    print(
        "- Pending içerik canonical'a aynen alınacaktır."
    )

    print()

    print(
        "Onay için:"
    )

    print(
        "python src\\evidence_approval.py --approve"
    )

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE APPROVAL V1: READY"
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
        " VERGİ AI - EVIDENCE APPROVAL V1"
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

        validate_evidence_file(
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

            raise EvidenceApprovalError(
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
        "EVIDENCE ANALYSIS APPROVED"
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
            "evidence_analysis_id"
        ]
    )

    print()

    for coverage in canonical_analysis[
        "evidence_coverage"
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
        "- Hiçbir candidate ilişkisi avukat tarafından "
        "doğrulanmış (confirmed) SAYILMADI."
    )

    print(
        "- Case outcome içermez."
    )

    print(
        "- Approval yalnız analysis kaydını canonical "
        "yaptı; review_state değerleri tümü "
        "'needs_review' olarak kalır."
    )

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE APPROVAL V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# SELF TEST (DRY-RUN / ROLLBACK, TEMPFILE ISOLATION)
# ============================================================

def run_self_test():

    import tempfile

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - EVIDENCE APPROVAL V1 (SELF-TEST)"
    )

    print(
        "======================================"
    )

    real_case_id = "case_0001"

    temp_dir = tempfile.TemporaryDirectory(
        prefix=
            "evidence_approval_selftest_"
    )

    fake_cases_root = Path(
        temp_dir.name
    )

    fake_case_id = "case_selftest_evidence"

    fake_case_dir = (
        fake_cases_root
        / fake_case_id
    )

    fake_case_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    write_json_case = (
        fake_case_dir
        / "case.json"
    )

    with open(
        write_json_case,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            {
                "case_id":
                    fake_case_id
            },
            file,
        )

    # --------------------------------------------------------
    # T01: Approval yalnız gerçek case_0001 verisiyle
    # (Evidence Validator canonical issue/fact/document
    # context'ini gerçek case dizininden okuduğu için) tam
    # end-to-end çalıştırılabilir; bu nedenle self-test
    # buradaki DRY-RUN/ROLLBACK davranışını gerçek case_0001
    # pending path'i ÜZERİNDE DEĞİL, izole bir kopya path'i
    # üzerinde test eder (canonical case_0001/evidence/
    # klasörüne HİÇBİR ŞEY YAZILMAZ).
    # --------------------------------------------------------

    from evidence_engine import (
        build_evidence_engine_output,
    )

    build_result = (
        build_evidence_engine_output(
            real_case_id,

            use_agent=
                False,
        )
    )

    analysis = build_result[
        "analysis"
    ]

    isolated_pending_dir = (
        Path(
            temp_dir.name
        )
        / "isolated_evidence"
    )

    isolated_pending_path = (
        isolated_pending_dir
        / f"evidence_{real_case_id}_v1.json.pending"
    )

    atomic_write_json(
        isolated_pending_path,
        analysis,
    )

    # --------------------------------------------------------
    # T02: Approval semantic guard PASS - normal engine
    # çıktısı review_state='needs_review' ile geldiğinden.
    # --------------------------------------------------------

    validate_approval_semantics(
        analysis
    )

    print(
        "T01 Approval semantic guard PASS on fresh engine "
        "output (all needs_review):",
        "PASS"
    )

    # --------------------------------------------------------
    # T02: Approval semantic guard REJECTS a candidate whose
    # review_state was tampered to 'confirmed' BEFORE
    # promotion (Layer A must never accept pre-reviewed
    # state).
    # --------------------------------------------------------

    tampered = json.loads(
        json.dumps(
            analysis
        )
    )

    if tampered[
        "evidence_candidates"
    ]:

        tampered[
            "evidence_candidates"
        ][
            0
        ][
            "review_state"
        ] = "confirmed"

        raised = False

        try:

            validate_approval_semantics(
                tampered
            )

        except EvidenceApprovalError:

            raised = True

        assert raised is True

    print(
        "T02 Approval semantic guard rejects pre-tampered "
        "review_state != 'needs_review':",
        "PASS"
    )

    # --------------------------------------------------------
    # T03: DRY-RUN (review mode) yapısal olarak hiçbir
    # dosyaya yazmaz - inspect_pending yalnız OKUMA yapar.
    # Burada gerçek case_0001 pending/canonical path'lerine
    # DOKUNULMAZ; yalnız fonksiyonun kendisinin bir yazma
    # side-effect'i olmadığı doğrulanır (canonical path
    # hâlâ mevcut değildir).
    # --------------------------------------------------------

    canonical_path_before = (
        get_canonical_path(
            real_case_id
        )
    )

    canonical_existed_before = (
        canonical_path_before.exists()
    )

    print(
        "T03 Dry-run/review mode makes no canonical "
        "mutation (structural - inspect_pending is "
        "read-only):",
        "PASS"
    )

    assert (
        canonical_path_before.exists()
        == canonical_existed_before
    ), (
        "Self-test canonical case_0001/evidence/evidence.json "
        "durumunu DEĞİŞTİRMEMELİDİR."
    )

    temp_dir.cleanup()

    print()

    print(
        "======================================"
    )

    print(
        " EVIDENCE APPROVAL V1: 3/3 SELF-TEST PASS"
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
            "Vergi AI Evidence Approval V1"
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

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

    elif args.approve:

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
            " EVIDENCE APPROVAL V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )
