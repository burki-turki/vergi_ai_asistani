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


class DeadlinePendingContractError(
    DeadlineApprovalError
):
    """ADIM 7 / SLICE 2 - legacy (Slice 2 ÖNCESİ üretilmiş) bir pending
    deadline paketinin promosyonu. SABİT mesaj; testte pinlenir. Ham
    dosya yolu / serbest metin SIZDIRMAZ."""

    def __init__(
        self,
    ):

        super().__init__(
            PENDING_CONTRACT_REFUSAL_MESSAGE
        )


PENDING_CONTRACT_REFUSAL_MESSAGE = (
    "Bu pending deadline paketi ADIM 7 / SLICE 2 öncesinde üretilmiş: "
    "kayıtlarında stopping_event_status ve/veya "
    "stopping_event_attestation_ref anahtarları eksik ya da geçersiz. "
    "Eksik bir stopping-event beyanı ASLA 'durdurucu olay yok' anlamına "
    "GELMEZ, bu yüzden bu paket canonical'a promote EDİLEMEZ. "
    "Pending'i güncel motorla yeniden üretin "
    "(python -m ui.cli_mutate generation --row-key deadline ... --apply "
    "--attempt N+1) ve yeniden onaylayın. Hiçbir değişiklik yapılmadı."
)


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
# ADIM 7 / SLICE 2 - PENDING PROMOTION CONTRACT (fail-closed)
# ============================================================

STOPPING_EVENT_STATUS_ENUM = (
    "none",
    "present",
    "unknown",
)


def check_pending_promotion_contract_object(
    analysis,
):
    """SAF, I/O'suz. `analysis` bir deadline paketi dict'idir.

    HER `deadlines[*]` kaydı için:
      1. `stopping_event_status` anahtarı FİZİKSEL olarak mevcut
         (`in` kontrolü - `.get()` DEĞİL, çünkü `None` değerli bir
         anahtar ile HİÇ OLMAYAN anahtar farklı şeylerdir),
      2. `stopping_event_attestation_ref` anahtarı FİZİKSEL olarak
         mevcut (değeri `None` OLABİLİR, anahtar eksik OLAMAZ),
      3. status değeri üç enum değerinden biri,
      4. ref değeri `str` veya `None`.

    Herhangi biri sağlanmazsa `DeadlinePendingContractError`. İKİ
    anahtar da AYRI AYRI kontrol edilir - yalnız birini kontrol etmek
    sözleşme ihlalidir."""

    # FAIL-CLOSED, İSTİSNASIZ. Yapısal olarak yorumlanamayan bir belge
    # de REDDEDİLİR - "anlayamadım, geçireyim" davranışı YOKTUR.
    if not isinstance(
        analysis,
        dict,
    ):

        raise DeadlinePendingContractError()

    records = analysis.get(
        "deadlines"
    )

    if not isinstance(
        records,
        list,
    ):

        raise DeadlinePendingContractError()

    for record in records:

        if not isinstance(
            record,
            dict,
        ):

            raise DeadlinePendingContractError()

        if (
            "stopping_event_status"
            not in record
        ):

            raise DeadlinePendingContractError()

        if (
            "stopping_event_attestation_ref"
            not in record
        ):

            raise DeadlinePendingContractError()

        if (
            record[
                "stopping_event_status"
            ]
            not in STOPPING_EVENT_STATUS_ENUM
        ):

            raise DeadlinePendingContractError()

        ref = record[
            "stopping_event_attestation_ref"
        ]

        if (
            ref is not None
            and not isinstance(
                ref,
                str,
            )
        ):

            raise DeadlinePendingContractError()

    return True


def check_pending_promotion_contract(
    pending_path,
    case_id,
):
    """ADIM 7 / SLICE 2 - Layer A facade'in `precondition_callback`'i
    tarafından DUCK-TYPED olarak çözülen public hook.

    ÇAĞRI ANI KRİTİKTİR: `run_mutation()`'ın AUTHORITATIVE ORDER'ında
    adım 5'te, `_insert_prepared` (adım 6) ÖNCESİNDE çalışır. Buradan
    fırlayan her istisna => SIFIR journal satırı, writer HİÇ
    çağrılmaz, canonical/backup/audit yazımı SIFIR.

    Bunu writer sınırının (`run_approve`) İÇİNE koymak KASITLI olarak
    REDDEDİLDİ: oradan fırlayan bir istisna `reconciliation_required`
    satırı bırakır; `mutation_approval_adapters` canonical MEVCUTKEN
    `pre_state_confirmed_unchanged=True` dönen bir dala SAHİP DEĞİLDİR
    (yalnız `post=True` ya da dual-false), dolayısıyla satır
    `reconciliation_operator` ile ÇÖZÜLEMEZ ve
    `mutation_coordinator._journal_gate_check` o case'in TÜM
    mutasyonlarını KALICI olarak bloke ederdi.

    KAPSAM - SEKİZ KOŞULUN TAMAMI, İSTİSNASIZ FAIL-CLOSED:
      (1) root dict değil,
      (2) `deadlines` yok veya list değil,
      (3) kayıt validator/şema sözleşmesini geçmiyor,
      (4) `stopping_event_status` anahtarı fiziksel olarak yok,
      (5) `stopping_event_attestation_ref` anahtarı fiziksel olarak yok,
      (6) status enum dışında,
      (7) ref tipi/biçimi geçersiz,
      (8) diğer deadline semantic-validator kuralları başarısız.

    (1)(2)(4)(5)(6)(7) -> `DeadlinePendingContractError` (sabit mesaj).
    (3)(8) -> `deadline_validator` zincirinin KENDİ hata sınıfı
    (`DeadlineValidationError` / `DeadlineApprovalError`) - detayı
    kaybetmemek için sarmalanMAZ.

    HER İKİ SINIF DA precondition sınırında fırlar: sıfır prepared
    journal satırı, writer HİÇ çağrılmaz, sıfır canonical/backup/audit,
    `reconciliation_required` OLUŞMAZ ve case kalıcı olarak
    KİLİTLENMEZ.

    SIRA (önemli): önce SAF yapısal + stopping kontrolü, SONRA tam
    validator. Gerekçe mekanik: `deadline_validator` kök nesnenin dict
    olduğunu VARSAYAR (`validate_case_id()` doğrudan `.get()` çağırır),
    bu yüzden root'u dict OLMAYAN bir belgeyi ona vermek TİPSİZ bir
    `AttributeError` üretir - fail-closed ama sınıflandırılamaz bir
    çökme. Yapısal kontrolü öne almak, (1)(2) için TEMİZ ve testte
    PİNLENEBİLİR bir `DeadlinePendingContractError` verir; (3)(8) ise
    ardından gelen gerçek validator zincirinden kendi zengin hata
    mesajıyla gelir."""

    try:
        analysis = load_json(
            pending_path
        )

    except Exception as error:

        # Hiç JSON olmayan bir pending de yapısal bir sözleşme
        # ihlalidir - tipsiz bir JSONDecodeError'ın dışarı kaçmasına
        # izin verilmez.
        raise DeadlinePendingContractError() from error

    check_pending_promotion_contract_object(
        analysis
    )

    validate_deadline_file(
        pending_path,
        case_id,
    )

    return True


# ============================================================
# APPROVAL SEMANTIC GUARD
# ============================================================

def validate_approval_semantics(
    analysis,
):

    # ADIM 7 / SLICE 2 NOTU: promosyon sözleşmesi kontrolü BİLİNÇLİ
    # olarak BURAYA KONMADI. Bu fonksiyon `inspect_pending()` üzerinden
    # UI'ın SALT-GÖRÜNTÜLEME yolunda da çalışır; buraya konsaydı legacy
    # bir pending avukatın ekranında HİÇ GÖRÜNTÜLENEMEZDİ (yalnız genel
    # bir hata sayfası). Kapı bunun yerine (a) facade'in
    # `precondition_callback`'inde - `check_pending_promotion_contract()`,
    # sıfır journal satırı - ve (b) `run_approve()`'un en başında,
    # herhangi bir I/O'dan önce uygulanır.

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
    mutation_idempotency_key=None,
    mutation_resource_key=None,
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

        # ROW 19C-2a: bound to the mutation-coordinator idempotency_key
        # of the run_mutation() attempt this approval was written under
        # (None for any approval NOT routed through the coordinator -
        # e.g. every approval before Row 19C-2a's own wiring, or a
        # direct CLI run of this file) - lets a reconciliation adapter
        # match this audit record back to its own mutation.mutation_
        # journal row via that row's own idempotency_key column (see
        # ui.services.mutation_registry.JournalEntrySnapshot).
        "mutation_idempotency_key":
            mutation_idempotency_key,

        # ROW 19C-2a: bound to the mutation-coordinator resource_key
        # (`case:<case_id>`) of the run_mutation() attempt this approval
        # was written under (None for any approval NOT routed through
        # the coordinator). Recorded ALONGSIDE mutation_idempotency_key
        # above because that key ALONE does not pin WHICH resource this
        # record belongs to - a reconciliation adapter (and the
        # request-time safe-replay check in
        # ui.services.mutation_approval_facade) verifies BOTH exactly.
        "mutation_resource_key":
            mutation_resource_key,

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
    *,
    mutation_idempotency_key=None,
    mutation_resource_key=None,
):
    # ROW 19C-2a AUDIT BINDING: both parameters are KEYWORD-ONLY (the
    # bare `*` above) so a positional caller can never accidentally
    # bind a case_id-shaped value to either of them, and so all 10
    # case-scoped approval families carry the IDENTICAL signature. Both
    # default to None, which preserves this function's exact
    # pre-Row-19C-2a behavior and CLI output for every caller that
    # never passes them (`python src/..._approval.py --approve`
    # included). When supplied - only ever by ui.services.
    # mutation_approval_facade.approve_case_scoped_mutation(), which
    # always passes BOTH together - they are threaded, unchanged, into
    # write_approval_audit() and become two additive fields on the
    # approval audit record.

    # ADIM 7 / SLICE 2 - promosyon sözleşmesi, writer sınırındaki
    # İKİNCİ (defense-in-depth) kapı. Koordineli yolda buraya asla
    # ulaşılmaz: facade'in `precondition_callback`'i aynı kontrolü
    # SIFIR journal satırıyla daha önce yapar. Bu kontrol, bu
    # fonksiyonu DOĞRUDAN çağıran (coordinator-sarmalı OLMAYAN, yani
    # hiçbir journal satırı üretmeyen) bir Python çağıranı için
    # vardır. Her türlü I/O'dan ÖNCE çalışır: sıfır backup, sıfır
    # canonical yazımı, sıfır audit.
    check_pending_promotion_contract(
        get_pending_path(
            case_id
        ),
        case_id,
    )

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

                mutation_idempotency_key=
                    mutation_idempotency_key,

                mutation_resource_key=
                    mutation_resource_key,
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

        # ROW 19C-3b SLICE 1: this direct CLI mutation path is CLOSED -
        # coordinator/journal/authz integration lives only in
        # ui.cli_mutate now. run_approve() ITSELF is untouched and
        # remains the real writer every facade calls - only THIS
        # executable entry point is refused. SystemExit (a BaseException,
        # never caught by this file's own `except Exception:` __main__
        # wrapper) propagates straight to the interpreter, so the real
        # OS process exit code is exactly 2 - never 0, never a bare
        # `return`.
        print(
            "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3b).\n"
            "Gerçek onay/inceleme için: python -m ui.cli_mutate <approval|review> ...",
            file=sys.stderr,
        )
        raise SystemExit(2)

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