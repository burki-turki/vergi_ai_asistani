# ============================================================
# VERGİ AI - DEADLINE ENGINE V1
#
# AMAÇ
# ----
#
# Canonical case + canonical timeline + active deadline rule
# üzerinden Deadline Calculator V1'i çalıştırmak ve sonucu:
#
#     data/cases/<case_id>/deadlines/
#     deadline_<case_id>_v1.json.pending
#
# olarak üretmek.
#
#
# MİMARİ
# -------
#
# canonical timeline
#        ↓
# Deadline Rule Selection Policy
#        ↓
# Deadline Calculator V1
#        ↓
# Deadline Validator V1
#        ↓
# *.json.pending
#        ↓
# human approval
#        ↓
# canonical deadline.json
#
#
# KRİTİK GÜVENLİK
# ----------------
#
# - Engine canonical deadline.json dosyasına YAZMAZ.
# - Yalnız pending üretir.
# - Unverified anchor üzerinden calculated deadline üretemez.
# - Validator PASS olmadan pending yazılmaz.
# - Post-write validator tekrar çalıştırılır.
# - Önceki pending varsa sessizce ezilmez; history'ye alınır.
# - Validator fixture dosyalarına dokunulmaz.
#
# ============================================================


import argparse
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path


from deadline_calculator import (
    build_case_deadline_analysis,
    validate_analysis_object,
)

from deadline_validator import (
    validate_deadline_analysis,
)


# ============================================================
# VERSION
# ============================================================

DEADLINE_ENGINE_VERSION = "1"


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

DEFAULT_RULESET_PATH = (
    DATA_DIR
    / "deadline_rules"
    / "deadline_rules.json"
)


# ============================================================
# DEFAULT PRODUCTION CASE
# ============================================================

DEFAULT_CASE_ID = (
    "case_0001"
)

DEFAULT_ANCHOR_EVENT_ID = (
    "timeline_event_003"
)


# ============================================================
# EXCEPTION
# ============================================================

class DeadlineEngineError(
    Exception
):
    pass


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
            f"JSON dosyası bulunamadı:\n{path}"
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


# ============================================================
# CASE PATHS
# ============================================================

def get_case_deadline_dir(
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
        get_case_deadline_dir(
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
        get_case_deadline_dir(
            case_id
        )
        / "deadline.json"
    )


def get_history_dir(
    case_id,
):

    return (
        get_case_deadline_dir(
            case_id
        )
        / "history"
    )


# ============================================================
# PREVIOUS PENDING PRESERVATION
# ============================================================

def preserve_previous_pending(
    case_id,
    pending_path,
):

    pending_path = Path(
        pending_path
    )

    if not pending_path.exists():

        return None

    history_dir = (
        get_history_dir(
            case_id
        )
    )

    history_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        datetime.now()
        .astimezone()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    history_path = (
        history_dir
        / (
            "deadline_pending_before_engine_"
            + timestamp
            + ".json.pending"
        )
    )

    shutil.move(
        str(
            pending_path
        ),
        str(
            history_path
        ),
    )

    return history_path


# ============================================================
# ANALYSIS SAFETY
# ============================================================

def validate_engine_output_semantics(
    analysis,
):

    if not isinstance(
        analysis,
        dict,
    ):

        raise DeadlineEngineError(
            "Deadline analysis dict değil."
        )

    deadlines = (
        analysis.get(
            "deadlines"
        )
    )

    if not isinstance(
        deadlines,
        list,
    ):

        raise DeadlineEngineError(
            "deadlines alanı list değil."
        )

    if len(
        deadlines
    ) == 0:

        raise DeadlineEngineError(
            "Deadline Engine boş deadline listesi üretti."
        )

    for deadline in deadlines:

        if not isinstance(
            deadline,
            dict,
        ):

            raise DeadlineEngineError(
                "Deadline kaydı dict değil."
            )

        calculation_state = (
            deadline.get(
                "calculation_state"
            )
        )

        calculated_deadline = (
            deadline.get(
                "calculated_deadline"
            )
        )

        anchor_verification = (
            deadline.get(
                "anchor_verification_state"
            )
        )

        # ====================================================
        # SECONDARY UNVERIFIED ANCHOR GUARD
        # ====================================================

        if (
            anchor_verification
            != "verified"
            and calculated_deadline
            is not None
        ):

            raise DeadlineEngineError(
                "Unverified anchor üzerinden "
                "calculated_deadline üretildi."
            )

        if (
            anchor_verification
            != "verified"
            and calculation_state
            == "calculated"
        ):

            raise DeadlineEngineError(
                "Unverified anchor üzerinden "
                "calculation_state='calculated' üretildi."
            )

        # ====================================================
        # BLOCKED STATES MUST NOT CONTAIN DEADLINE
        # ====================================================

        if (
            calculation_state
            in {
                "blocked_unverified_anchor",
                "blocked_missing_rule",
                "blocked_ambiguous_rule",
                "needs_review",
                "not_applicable",
            }
            and calculated_deadline
            is not None
        ):

            raise DeadlineEngineError(
                f"{calculation_state} durumunda "
                "calculated_deadline null olmalıdır."
            )


# ============================================================
# BUILD
# ============================================================

def build_deadline_engine_output(
    case_id,
    anchor_event_id,
    ruleset_path,
    holiday_dates=None,
    calendar_complete=False,
    judicial_recess_applicable=None,
):

    analysis = (
        build_case_deadline_analysis(
            case_id=
                case_id,

            anchor_event_id=
                anchor_event_id,

            ruleset_path=
                ruleset_path,

            holiday_dates=
                holiday_dates,

            calendar_complete=
                calendar_complete,

            judicial_recess_applicable=
                judicial_recess_applicable,
        )
    )

    # --------------------------------------------------------
    # Engine canonical output ID.
    # --------------------------------------------------------

    analysis[
        "deadline_analysis_id"
    ] = (
        f"deadline_{case_id}_v1"
    )

    analysis[
        "notes"
    ] = (
        "Deadline Engine V1 production candidate. "
        "Bu çıktı pending durumundadır ve human approval "
        "olmadan canonical deadline repository'ye alınmaz."
    )

    validate_engine_output_semantics(
        analysis
    )

    return analysis


# ============================================================
# WRITE PENDING
# ============================================================

def write_pending(
    case_id,
    analysis,
):

    deadline_dir = (
        get_case_deadline_dir(
            case_id
        )
    )

    deadline_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pending_path = (
        get_pending_path(
            case_id
        )
    )

    canonical_path = (
        get_canonical_path(
            case_id
        )
    )

    # ========================================================
    # CANONICAL FILE IS NEVER MODIFIED HERE
    # ========================================================

    canonical_exists_before = (
        canonical_path.exists()
    )

    previous_pending_history = (
        preserve_previous_pending(
            case_id=
                case_id,

            pending_path=
                pending_path,
        )
    )

    try:

        atomic_write_json(
            pending_path,
            analysis,
        )

        # ====================================================
        # POST-WRITE DEADLINE VALIDATOR
        # ====================================================

        validation = (
            validate_deadline_analysis(
                deadline_path=
                    pending_path,

                expected_case_id=
                    case_id,

                raise_on_error=
                    True,
            )
        )

        if (
            validation.get(
                "valid"
            )
            is not True
        ):

            raise DeadlineEngineError(
                "Post-write Deadline Validator valid=False."
            )

        # ====================================================
        # RELOAD + SEMANTIC GUARD
        # ====================================================

        written = load_json(
            pending_path
        )

        validate_engine_output_semantics(
            written
        )

        # ====================================================
        # CANONICAL MUTATION GUARD
        # ====================================================

        if (
            canonical_exists_before
            != canonical_path.exists()
        ):

            raise DeadlineEngineError(
                "Deadline Engine canonical deadline.json "
                "durumunu değiştirdi."
            )

        return (
            pending_path,
            validation,
            previous_pending_history,
        )

    except Exception:

        if pending_path.exists():

            pending_path.unlink()

        # ----------------------------------------------------
        # Önceki pending varsa geri getir.
        # ----------------------------------------------------

        if (
            previous_pending_history
            is not None
            and previous_pending_history.exists()
        ):

            shutil.move(
                str(
                    previous_pending_history
                ),
                str(
                    pending_path
                ),
            )

        raise


# ============================================================
# ENGINE
# ============================================================

def run_engine(
    case_id,
    anchor_event_id,
    ruleset_path,
    holiday_dates=None,
    calendar_complete=False,
    judicial_recess_applicable=None,
):

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE ENGINE V1"
    )

    print(
        "======================================"
    )

    # ========================================================
    # BUILD
    # ========================================================

    analysis = (
        build_deadline_engine_output(
            case_id=
                case_id,

            anchor_event_id=
                anchor_event_id,

            ruleset_path=
                ruleset_path,

            holiday_dates=
                holiday_dates,

            calendar_complete=
                calendar_complete,

            judicial_recess_applicable=
                judicial_recess_applicable,
        )
    )

    # ========================================================
    # PRE-WRITE FULL VALIDATOR
    # ========================================================

    pre_validation = (
        validate_analysis_object(
            analysis=
                analysis,

            case_id=
                case_id,
        )
    )

    if (
        pre_validation.get(
            "valid"
        )
        is not True
    ):

        raise DeadlineEngineError(
            "Pre-write Deadline Validator FAIL."
        )

    print(
        "Pre-write validator:",
        "PASS"
    )

    # ========================================================
    # WRITE
    # ========================================================

    (
        pending_path,
        post_validation,
        previous_pending_history,
    ) = write_pending(
        case_id=
            case_id,

        analysis=
            analysis,
    )

    print(
        "Post-write validator:",
        "PASS"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    deadlines = (
        analysis[
            "deadlines"
        ]
    )

    print()

    print(
        "Case:",
        analysis[
            "case_id"
        ]
    )

    print(
        "Deadline analysis ID:",
        analysis[
            "deadline_analysis_id"
        ]
    )

    print(
        "Deadline count:",
        len(
            deadlines
        )
    )

    print(
        "Status:",
        analysis[
            "status"
        ]
    )

    print()

    for deadline in deadlines:

        print(
            "Deadline:",
            deadline[
                "deadline_id"
            ]
        )

        print(
            "- type:",
            deadline[
                "deadline_type"
            ]
        )

        print(
            "- anchor event:",
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
            "- legal basis:",
            len(
                deadline.get(
                    "legal_basis_refs",
                    []
                )
            )
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
            "- expiry state:",
            deadline[
                "expiry_state"
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

    if previous_pending_history:

        print()

        print(
            "Previous pending archived:"
        )

        print(
            previous_pending_history
        )

    print()

    print(
        "Canonical deadline.json:"
    )

    print(
        "DEĞİŞTİRİLMEDİ"
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE ENGINE V1: PASS"
    )

    print(
        "======================================"
    )

    return analysis


# ============================================================
# CLI HELPERS
# ============================================================

def parse_judicial_recess(
    value,
):

    if value == "yes":

        return True

    if value == "no":

        return False

    return None


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Deadline Engine V1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=
            DEFAULT_CASE_ID,
    )

    parser.add_argument(
        "--anchor",
        dest="anchor_event_id",
        default=
            DEFAULT_ANCHOR_EVENT_ID,
    )

    parser.add_argument(
        "--ruleset",
        dest="ruleset_path",
        default=str(
            DEFAULT_RULESET_PATH
        ),
    )

    parser.add_argument(
        "--holiday",
        action="append",
        default=[],
    )

    parser.add_argument(
        "--calendar-complete",
        action="store_true",
    )

    parser.add_argument(
        "--judicial-recess-applicable",
        choices=[
            "yes",
            "no",
            "unknown",
        ],
        default="unknown",
    )

    args = parser.parse_args()

    judicial_recess_applicable = (
        parse_judicial_recess(
            args.judicial_recess_applicable
        )
    )

    run_engine(
        case_id=
            args.case_id,

        anchor_event_id=
            args.anchor_event_id,

        ruleset_path=
            Path(
                args.ruleset_path
            ),

        holiday_dates=
            args.holiday,

        calendar_complete=
            args.calendar_complete,

        judicial_recess_applicable=
            judicial_recess_applicable,
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
            " DEADLINE ENGINE V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )