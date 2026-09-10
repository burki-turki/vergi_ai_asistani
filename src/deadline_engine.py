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


import hashlib
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

import path_containment


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
# ROW 19C-3c-i - GENERATION MUTATION BINDING
# ============================================================

GENERATION_ACTION_FAMILY = "generation.deadline"

GENERATION_AUDIT_SCHEMA_VERSION = "1"


def get_reviews_dir(
    case_id,
):

    return (
        get_case_deadline_dir(
            case_id
        )
        / "generation_reviews"
    )


def get_target_ref(
    anchor_event_id,
):

    return f"deadline.{anchor_event_id}.pending"


def now_stamp():

    return (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )


def sha256_bytes(data):

    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(data):

    text = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    )

    return text.replace(
        "\n",
        os.linesep,
    ).encode("utf-8")


def _write_generation_audit_record_excl(
    reviews_dir,
    anchor_event_id,
    audit_record,
):
    """`fact_approval._write_audit_record_excl()` ile AYNI desen -
    zaman damgalı taban ad + `O_CREAT|O_EXCL` + sayısal sonek; sabit
    adın ÜZERİNE YAZMA sınıfı kapatılır, replay/reconciliation
    eşleşmesi HER ZAMAN içerikten yapılır, addan asla."""

    reviews_dir = Path(reviews_dir)

    reviews_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    base = f"deadline_{anchor_event_id}_{now_stamp()}"

    suffix = 0

    while True:

        if suffix == 0:
            name = f"{base}.generation_audit.json"
        else:
            name = f"{base}_{suffix}.generation_audit.json"

        path_containment.validate_segment(name)

        candidate = path_containment.resolve_for_create(
            reviews_dir,
            name,
        )

        try:
            fd = os.open(
                candidate,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            suffix += 1
            if suffix > 1000:
                raise RuntimeError(
                    "Generation audit dosya adı için 1000 denemede "
                    "boş ad bulunamadı."
                )
            continue

        with os.fdopen(fd, "wb") as file:
            file.write(_canonical_json_bytes(audit_record))

        return candidate


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
    *,
    provisions_path=None,
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

            provisions_path=
                provisions_path,
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
    *,
    anchor_event_id=None,
    input_digest=None,
    generation_parameters_digest=None,
    mutation_idempotency_key=None,
    mutation_resource_key=None,
    mutation_actor_ref=None,
    pre_commit_callback=None,
):

    mutation_binding_provided = (
        mutation_idempotency_key is not None
    )

    if mutation_binding_provided:

        if (
            anchor_event_id is None
            or input_digest is None
            or generation_parameters_digest is None
            or mutation_resource_key is None
            or mutation_actor_ref is None
        ):

            raise DeadlineEngineError(
                "mutation_idempotency_key verildiğinde "
                "anchor_event_id/input_digest/"
                "generation_parameters_digest/mutation_resource_key/"
                "mutation_actor_ref de verilmelidir (kısmi "
                "mutation-binding kabul edilmez)."
            )

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

        if pre_commit_callback is not None:

            pre_commit_callback()

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
        # RELOAD + SEMANTIC GUARD (GERÇEK DİSK BAYTLARINDAN)
        # ====================================================

        pending_raw_bytes = pending_path.read_bytes()

        pending_sha256 = sha256_bytes(pending_raw_bytes)

        written = json.loads(
            pending_raw_bytes.decode("utf-8")
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

        # ====================================================
        # GENERATION AUDIT RECORD (yalnız coordinator-mode'da)
        # ====================================================

        audit_path = None

        first_write = (
            previous_pending_history
            is None
        )

        if mutation_binding_provided:

            history_backup_path = None

            history_backup_sha256 = None

            if not first_write:

                history_backup_path = str(
                    previous_pending_history
                )

                history_backup_sha256 = sha256_bytes(
                    previous_pending_history.read_bytes()
                )

            audit_record = {
                "schema_version": GENERATION_AUDIT_SCHEMA_VERSION,
                "case_id": case_id,
                "target_ref": get_target_ref(anchor_event_id),
                "target_state": "generated",
                "action_family": GENERATION_ACTION_FAMILY,
                "mutation_idempotency_key": mutation_idempotency_key,
                "mutation_resource_key": mutation_resource_key,
                "mutation_actor_ref": mutation_actor_ref,
                "input_digest": input_digest,
                "generation_parameters_digest": generation_parameters_digest,
                "first_write": first_write,
                "history_backup_path": history_backup_path,
                "history_backup_sha256": history_backup_sha256,
                "pending_sha256": pending_sha256,
                "generated_at": written.get("generated_at"),
                "outcome": "generated",
                "written_at": (
                    datetime.now()
                    .astimezone()
                    .isoformat()
                ),
            }

            audit_path = _write_generation_audit_record_excl(
                reviews_dir=get_reviews_dir(case_id),
                anchor_event_id=anchor_event_id,
                audit_record=audit_record,
            )

        return {
            "pending_path": pending_path,
            "validation": validation,
            "previous_pending_history": previous_pending_history,
            "pending_sha256": pending_sha256,
            "audit_path": audit_path,
            "first_write": first_write,
        }

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
    *,
    provisions_path=None,
    input_digest=None,
    generation_parameters_digest=None,
    mutation_idempotency_key=None,
    mutation_resource_key=None,
    mutation_actor_ref=None,
    pre_commit_callback=None,
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

            provisions_path=
                provisions_path,
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

    write_result = write_pending(
        case_id=
            case_id,

        analysis=
            analysis,

        anchor_event_id=
            anchor_event_id,

        input_digest=
            input_digest,

        generation_parameters_digest=
            generation_parameters_digest,

        mutation_idempotency_key=
            mutation_idempotency_key,

        mutation_resource_key=
            mutation_resource_key,

        mutation_actor_ref=
            mutation_actor_ref,

        pre_commit_callback=
            pre_commit_callback,
    )

    pending_path = write_result["pending_path"]

    post_validation = write_result["validation"]

    previous_pending_history = write_result["previous_pending_history"]

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

    return {
        "analysis": analysis,
        "pending_path": pending_path,
        "validation": post_validation,
        "previous_pending_history": previous_pending_history,
        "pending_sha256": write_result["pending_sha256"],
        "audit_path": write_result["audit_path"],
        "first_write": write_result["first_write"],
    }


# ============================================================
# CLI
#
# ROW 19C-3c-i: bu doğrudan mutasyon CLI yolu DEVRE DIŞI bırakıldı.
# `run_engine()`'in kendisi DEĞİŞMEDİ ve tam olarak fonksiyoneldir -
# yalnız `ui.services.generation_mutation_facade` üzerinden (mutation
# coordinator/journal altyapısına bağlı olarak) çağrılabilir. Bu
# dosyada önceden var olan koşulsuz mutasyon dışında korunması gereken
# bir preview/self-test dalı YOKTU (bkz. Row 19C-3c-i final scope
# raporu) - bu yüzden kapama argparse'ı hiç kurmadan doğrudan
# reddeder. Eski `parse_judicial_recess()` yardımcı fonksiyonu, tek
# çağıranı (bu `main()`) kapatıldığı için gerçekten ölü koda
# dönüştüğünden kaldırılmıştır.
# ============================================================

_LEGACY_CLI_REFUSAL_MESSAGE = (
    "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3b).\n"
    "Gerçek üretim için: python -m ui.cli_mutate generation "
    "<preview|apply> --row-key deadline ..."
)


def main():

    print(
        _LEGACY_CLI_REFUSAL_MESSAGE,
        file=sys.stderr,
    )

    raise SystemExit(2)


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