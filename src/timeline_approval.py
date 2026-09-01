# ============================================================
# VERGİ AI - TIMELINE APPROVAL V1
#
# AMAÇ:
#
# Timeline Engine tarafından oluşturulan:
#
#   timeline_v1_1.json.pending
#
# dosyasını kontrollü review + promotion sürecinden geçirerek:
#
#   timeline.json
#
# canonical timeline haline getirmek.
#
#
# TEMEL PRENSİPLER
# ----------------
#
# 1. Yalnız .pending dosyalar approve edilebilir.
#
# 2. Pending timeline önce Timeline Validator V1 ile
#    doğrulanır.
#
# 3. Review mode hiçbir dosyayı değiştirmez.
#
# 4. Approval sırasında mevcut canonical timeline varsa
#    history klasörüne alınır.
#
# 5. Canonical yazım atomic yapılır.
#
# 6. Promotion sonrası canonical timeline tekrar validate edilir.
#
# 7. Validation fail olursa rollback yapılır.
#
# 8. Approval verification_state'i DEĞİŞTİRMEZ.
#
#    Approval:
#
#       "bu timeline canonical çalışma verisidir"
#
#    anlamına gelir.
#
#    Approval:
#
#       "bu tarihler maddi olarak doğrulanmıştır"
#
#    anlamına GELMEZ.
#
# 9. SHA256 ve audit record tutulur.
# ============================================================


import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path


from timeline_validator import (
    validate_timeline,
)


# ============================================================
# VERSION
# ============================================================

TIMELINE_APPROVAL_VERSION = "1"


# ============================================================
# HELPERS
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


def write_json(
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

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
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
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

        file.flush()

        os.fsync(
            file.fileno()
        )

    os.replace(
        temp_path,
        path,
    )


# ============================================================
# SHA256
# ============================================================

def file_sha256(
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
# TIMESTAMP
# ============================================================

def timestamp_for_filename():

    return (
        datetime.now()
        .astimezone()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )


def timestamp_iso():

    return (
        datetime.now()
        .astimezone()
        .isoformat()
    )


# ============================================================
# PATH RULES
# ============================================================

def validate_pending_path(
    pending_path,
):

    pending_path = Path(
        pending_path
    )

    if not pending_path.exists():

        raise FileNotFoundError(
            f"Pending timeline bulunamadı:\n{pending_path}"
        )

    if not pending_path.is_file():

        raise ValueError(
            f"Pending path dosya değil:\n{pending_path}"
        )

    if not pending_path.name.endswith(
        ".pending"
    ):

        raise ValueError(
            "Yalnız .pending uzantılı timeline "
            "dosyaları approve edilebilir."
        )

    return pending_path


def canonical_path_from_pending(
    pending_path,
):

    # --------------------------------------------------------
    # Her timeline versiyonunun canonical hedefi:
    #
    # timeline/
    #     timeline.json
    # --------------------------------------------------------

    return (
        pending_path.parent
        / "timeline.json"
    )


def history_dir_from_pending(
    pending_path,
):

    return (
        pending_path.parent
        / "history"
    )


def reviews_dir_from_pending(
    pending_path,
):

    return (
        pending_path.parent
        / "reviews"
    )


# ============================================================
# PENDING SEMANTIC CHECKS
# ============================================================

def validate_pending_semantics(
    timeline,
):

    errors = []

    status = timeline.get(
        "status"
    )

    events = timeline.get(
        "events",
        []
    )

    if status != "completed":

        errors.append(
            "Timeline status='completed' olmalıdır. "
            f"Bulunan: {status}"
        )

    if not isinstance(
        events,
        list,
    ):

        errors.append(
            "Timeline events array olmalıdır."
        )

    elif len(
        events
    ) == 0:

        errors.append(
            "Completed timeline en az bir event içermelidir."
        )

    return errors


# ============================================================
# REVIEW
# ============================================================

def review_pending(
    pending_path,
):

    pending_path = (
        validate_pending_path(
            pending_path
        )
    )

    timeline = load_json(
        pending_path
    )

    case_id = timeline.get(
        "case_id"
    )

    if not case_id:

        raise ValueError(
            "Pending timeline içinde case_id yok."
        )

    validation = (
        validate_timeline(
            timeline_path=
                pending_path,

            expected_case_id=
                case_id,

            raise_on_error=
                False,
        )
    )

    semantic_errors = (
        validate_pending_semantics(
            timeline
        )
    )

    errors = list(
        validation.get(
            "errors",
            []
        )
    )

    errors.extend(
        semantic_errors
    )

    errors = list(
        dict.fromkeys(
            errors
        )
    )

    warnings = list(
        validation.get(
            "warnings",
            []
        )
    )

    sha256 = (
        file_sha256(
            pending_path
        )
    )

    return {
        "ready":
            len(
                errors
            ) == 0,

        "timeline":
            timeline,

        "pending_path":
            pending_path,

        "canonical_path":
            canonical_path_from_pending(
                pending_path
            ),

        "sha256":
            sha256,

        "errors":
            errors,

        "warnings":
            warnings,

        "validation":
            validation,
    }


# ============================================================
# BACKUP
# ============================================================

def backup_existing_canonical(
    canonical_path,
    history_dir,
):

    canonical_path = Path(
        canonical_path
    )

    history_dir = Path(
        history_dir
    )

    if not canonical_path.exists():

        return None

    history_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    current_hash = (
        file_sha256(
            canonical_path
        )
    )

    backup_name = (
        "timeline_before_promotion_"
        + timestamp_for_filename()
        + "_"
        + current_hash[
            :8
        ]
        + ".json"
    )

    backup_path = (
        history_dir
        / backup_name
    )

    shutil.copy2(
        canonical_path,
        backup_path,
    )

    return backup_path


# ============================================================
# AUDIT RECORD
# ============================================================

def build_audit_record(
    review,
    approved,
    backup_path=None,
    rollback=False,
):

    timeline = review[
        "timeline"
    ]

    events = timeline.get(
        "events",
        []
    )

    verification_states = {}

    event_types = {}

    for event in events:

        state = event.get(
            "verification_state"
        )

        verification_states[
            state
        ] = (
            verification_states.get(
                state,
                0,
            )
            + 1
        )

        event_type = event.get(
            "event_type"
        )

        event_types[
            event_type
        ] = (
            event_types.get(
                event_type,
                0,
            )
            + 1
        )

    return {
        "approval_schema_version":
            1,

        "approval_version":
            TIMELINE_APPROVAL_VERSION,

        "timeline_id":
            timeline.get(
                "timeline_id"
            ),

        "case_id":
            timeline.get(
                "case_id"
            ),

        "pending_file":
            str(
                review[
                    "pending_path"
                ]
            ),

        "canonical_file":
            str(
                review[
                    "canonical_path"
                ]
            ),

        "pending_sha256":
            review[
                "sha256"
            ],

        "approved":
            approved,

        "approved_at":
            (
                timestamp_iso()
                if approved
                else None
            ),

        "rollback":
            rollback,

        "backup_file":
            (
                str(
                    backup_path
                )
                if backup_path
                else None
            ),

        "event_count":
            len(
                events
            ),

        "event_types":
            event_types,

        "verification_states":
            verification_states,

        "warnings":
            review.get(
                "warnings",
                []
            ),

        "notes":
            (
                "Timeline approval canonical promotion "
                "işlemidir. Timeline event'lerinin maddi "
                "doğruluğunu veya verification_state "
                "seviyesini değiştirmez."
            ),
    }


def write_audit_record(
    pending_path,
    audit_record,
):

    reviews_dir = (
        reviews_dir_from_pending(
            pending_path
        )
    )

    reviews_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timeline_id = (
        audit_record.get(
            "timeline_id"
        )
        or "timeline"
    )

    filename = (
        timeline_id
        + "_"
        + timestamp_for_filename()
        + ".approval.json"
    )

    audit_path = (
        reviews_dir
        / filename
    )

    write_json(
        audit_path,
        audit_record,
    )

    return audit_path


# ============================================================
# PROMOTION
# ============================================================

def approve_pending(
    pending_path,
):

    review = (
        review_pending(
            pending_path
        )
    )

    if not review[
        "ready"
    ]:

        raise RuntimeError(
            "Pending timeline approval için READY değil."
        )

    pending_path = review[
        "pending_path"
    ]

    canonical_path = review[
        "canonical_path"
    ]

    history_dir = (
        history_dir_from_pending(
            pending_path
        )
    )

    timeline = review[
        "timeline"
    ]

    backup_path = None

    canonical_previously_existed = (
        canonical_path.exists()
    )

    # ========================================================
    # BACKUP
    # ========================================================

    if canonical_previously_existed:

        backup_path = (
            backup_existing_canonical(
                canonical_path,
                history_dir,
            )
        )

    # ========================================================
    # PROMOTE
    # ========================================================

    try:

        atomic_write_json(
            canonical_path,
            timeline,
        )

        # ====================================================
        # POST-PROMOTION VALIDATION
        # ====================================================

        post_validation = (
            validate_timeline(
                timeline_path=
                    canonical_path,

                expected_case_id=
                    timeline[
                        "case_id"
                    ],

                raise_on_error=
                    False,
            )
        )

        semantic_errors = (
            validate_pending_semantics(
                timeline
            )
        )

        post_errors = list(
            post_validation.get(
                "errors",
                []
            )
        )

        post_errors.extend(
            semantic_errors
        )

        if post_errors:

            raise RuntimeError(
                "Canonical timeline promotion sonrası "
                "validation başarısız:\n- "
                + "\n- ".join(
                    post_errors
                )
            )

    except Exception:

        # ====================================================
        # ROLLBACK
        # ====================================================

        if (
            backup_path
            and backup_path.exists()
        ):

            shutil.copy2(
                backup_path,
                canonical_path,
            )

        elif (
            not canonical_previously_existed
            and canonical_path.exists()
        ):

            canonical_path.unlink()

        rollback_audit = (
            build_audit_record(
                review=
                    review,

                approved=
                    False,

                backup_path=
                    backup_path,

                rollback=
                    True,
            )
        )

        write_audit_record(
            pending_path,
            rollback_audit,
        )

        raise

    # ========================================================
    # AUDIT
    # ========================================================

    audit_record = (
        build_audit_record(
            review=
                review,

            approved=
                True,

            backup_path=
                backup_path,

            rollback=
                False,
        )
    )

    audit_path = (
        write_audit_record(
            pending_path,
            audit_record,
        )
    )

    canonical_hash = (
        file_sha256(
            canonical_path
        )
    )

    return {
        "review":
            review,

        "canonical_path":
            canonical_path,

        "canonical_sha256":
            canonical_hash,

        "backup_path":
            backup_path,

        "audit_path":
            audit_path,
    }


# ============================================================
# PRINT REVIEW
# ============================================================

def print_review(
    review,
):

    timeline = review[
        "timeline"
    ]

    print()

    print(
        "Timeline ID:",
        timeline.get(
            "timeline_id"
        ),
    )

    print(
        "Case ID:",
        timeline.get(
            "case_id"
        ),
    )

    print(
        "Event sayısı:",
        len(
            timeline.get(
                "events",
                []
            )
        ),
    )

    print(
        "Status:",
        timeline.get(
            "status"
        ),
    )

    print(
        "SHA256:",
        review[
            "sha256"
        ],
    )

    print(
        "Validator:",
        (
            "PASS"
            if not review[
                "validation"
            ].get(
                "errors"
            )
            else "FAIL"
        ),
    )

    if review[
        "warnings"
    ]:

        print()

        print(
            "Warnings:"
        )

        for warning in review[
            "warnings"
        ]:

            print(
                "-",
                warning,
            )

    if review[
        "errors"
    ]:

        print()

        print(
            "Errors:"
        )

        for error in review[
            "errors"
        ]:

            print(
                "-",
                error,
            )


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Timeline Approval V1"
        )
    )

    parser.add_argument(
        "--pending",
        required=True,
        help=(
            "Approve edilecek .pending timeline dosyası"
        ),
    )

    parser.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Review sonrası canonical promotion yap"
        ),
    )

    args = parser.parse_args()

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - TIMELINE APPROVAL V1"
    )

    print(
        "======================================"
    )

    try:

        review = (
            review_pending(
                args.pending
            )
        )

    except Exception as error:

        print()

        print(
            "TIMELINE REVIEW FAILED"
        )

        print(
            error
        )

        print()

        print(
            "======================================"
        )

        print(
            " TIMELINE APPROVAL V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )

    print_review(
        review
    )

    if not review[
        "ready"
    ]:

        print()

        print(
            "Promotion yapılamaz."
        )

        print()

        print(
            "======================================"
        )

        print(
            " TIMELINE APPROVAL V1: NOT READY"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )

    # ========================================================
    # REVIEW MODE
    # ========================================================

    if not args.approve:

        print()

        print(
            "REVIEW MODE"
        )

        print(
            "Promotion yapılmadı."
        )

        print()

        print(
            "NOT:"
        )

        print(
            "Approval event verification_state "
            "değerlerini değiştirmez."
        )

        print()

        print(
            "======================================"
        )

        print(
            " TIMELINE APPROVAL V1: READY"
        )

        print(
            "======================================"
        )

        return

    # ========================================================
    # APPROVE
    # ========================================================

    try:

        result = (
            approve_pending(
                args.pending
            )
        )

    except Exception as error:

        print()

        print(
            "PROMOTION FAILED"
        )

        print(
            error
        )

        print()

        print(
            "Rollback uygulandı."
        )

        print()

        print(
            "======================================"
        )

        print(
            " TIMELINE APPROVAL V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )

    print()

    print(
        "PROMOTION TAMAMLANDI"
    )

    print()

    print(
        "Canonical:"
    )

    print(
        result[
            "canonical_path"
        ]
    )

    print()

    print(
        "Canonical SHA256:"
    )

    print(
        result[
            "canonical_sha256"
        ]
    )

    if result[
        "backup_path"
    ]:

        print()

        print(
            "Previous canonical backup:"
        )

        print(
            result[
                "backup_path"
            ]
        )

    print()

    print(
        "Audit record:"
    )

    print(
        result[
            "audit_path"
        ]
    )

    print()

    print(
        "NOT:"
    )

    print(
        "Timeline canonical hale geldi; "
        "event verification_state değerleri "
        "aynen korunmuştur."
    )

    print()

    print(
        "======================================"
    )

    print(
        " TIMELINE APPROVAL V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()