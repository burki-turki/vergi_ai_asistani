# ============================================================
# VERGİ AI
# ADD IYUK M61/F1 PROVISION V1
#
# AMAÇ
# ----
#
# İYUK m.8/3 kapsamındaki çalışmaya ara verme hesabının
# dönemsel dayanağı olan:
#
#     kanun_2577_m61_f1
#
# canonical provision version'ını Legal Knowledge Engine'e
# eklemek.
#
#
# ÖNEMLİ
# -------
#
# Bu script:
#
# - deadline rule'u değiştirmez
# - calculation_enabled durumuna dokunmaz
# - legal_basis_refs listesine henüz ref eklemez
# - provisions.json backup alır
# - schema validation yapar
# - atomic write yapar
# - post-write validate eder
# - hata halinde rollback uygular
#
# ============================================================


import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


# ============================================================
# VERSION
# ============================================================

SCRIPT_VERSION = "1"


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

PROVISIONS_PATH = (
    DATA_DIR
    / "provisions.json"
)

PROVISIONS_SCHEMA_PATH = (
    DATA_DIR
    / "provisions.schema.json"
)


# ============================================================
# TARGET
# ============================================================

TARGET_PROVISION_ID = (
    "kanun_2577_m61_f1"
)

TARGET_PROVISION_VERSION_ID = (
    "kanun_2577_m61_f1_v1"
)


# ============================================================
# SOURCES
# ============================================================

MEVZUAT_SOURCE_URL = (
    "https://www.mevzuat.gov.tr/"
    "MevzuatMetin/1.5.2577.pdf"
)

TBMM_6494_SOURCE_URL = (
    "https://cdn.tbmm.gov.tr/"
    "KKBSPublicFile/D24/Y3/T1/KanunMetni/"
    "ba728d4d-08d9-46a8-9fb8-3e2464dd21f1.html"
)

TBMM_6723_SOURCE_URL = (
    "https://cdn.tbmm.gov.tr/"
    "KKBSPublicFile/D26/Y1/T1/KanunMetni/"
    "81724b0e-e747-4f29-885a-7db9cb1b2324.html"
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
# BACKUP
# ============================================================

def backup_file(
    path,
):

    path = Path(
        path
    )

    timestamp = (
        datetime.now()
        .astimezone()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    backup_path = (
        path.parent
        / (
            path.name
            + ".before_iyuk_m61f1_"
            + timestamp
            + ".bak"
        )
    )

    shutil.copy2(
        path,
        backup_path,
    )

    return backup_path


# ============================================================
# SCHEMA VALIDATION
# ============================================================

def validate_schema(
    data,
):

    schema = load_json(
        PROVISIONS_SCHEMA_PATH
    )

    validator = (
        Draft202012Validator(
            schema,
            format_checker=
                FormatChecker(),
        )
    )

    errors = sorted(
        validator.iter_errors(
            data
        ),
        key=lambda error:
            list(
                error.absolute_path
            ),
    )

    if not errors:

        return

    messages = []

    for error in errors:

        location = ".".join(
            str(part)
            for part
            in error.absolute_path
        )

        if not location:

            location = "$"

        messages.append(
            f"{location}: {error.message}"
        )

    raise RuntimeError(
        "provisions.json schema validation FAIL:\n- "
        + "\n- ".join(
            messages
        )
    )


# ============================================================
# BUILD PROVISION
# ============================================================

def build_provision():

    return {
        "provision_id":
            TARGET_PROVISION_ID,

        "provision_version_id":
            TARGET_PROVISION_VERSION_ID,

        "document_id":
            "kanun_2577",

        "enabled":
            True,

        "verification_state":
            "verified",

        "locator": {
            "madde":
                "61",

            "fikra":
                "1",

            "bent":
                None,
        },

        "formal": {
            "verified":
                True,

            "status":
                "active",

            # ------------------------------------------------
            # Current full fıkra version:
            #
            # İlk cümledeki 20 Temmuz - 31 Ağustos düzeni
            # 6494/18 ile 2013'te düzenlenmiştir.
            #
            # Fıkranın ikinci cümlesi ise 6723/14 ile
            # 23.07.2016 tarihinde değiştirilmiştir.
            #
            # Dolayısıyla CURRENT tam fıkra version'ı
            # 23.07.2016'dan itibaren modellenmektedir.
            # ------------------------------------------------

            "valid_from":
                "2016-07-23",

            "valid_through":
                None,

            "repeal_effective_date":
                None,

            "evidence": [
                {
                    "evidence_id":
                        "ev_2577_m61_f1_6494_m18",

                    "kind":
                        "amending_law",

                    "source_document_id":
                        None,

                    "source_url":
                        TBMM_6494_SOURCE_URL,

                    "citation":
                        (
                            "6494 sayılı Kanun m.18; "
                            "2577 sayılı Kanun m.61/1 "
                            "birinci cümlesinin yeniden "
                            "düzenlenmesi"
                        ),

                    "verified":
                        True,

                    "notes":
                        (
                            "Bölge idare, idare ve vergi "
                            "mahkemelerinin çalışmaya ara verme "
                            "döneminin 20 Temmuz - 31 Ağustos "
                            "olduğunu düzenleyen değişiklik."
                        ),
                },
                {
                    "evidence_id":
                        "ev_2577_m61_f1_6723_m14",

                    "kind":
                        "amending_law",

                    "source_document_id":
                        None,

                    "source_url":
                        TBMM_6723_SOURCE_URL,

                    "citation":
                        (
                            "6723 sayılı Kanun m.14; "
                            "2577 sayılı Kanun m.61/1 "
                            "ikinci cümlesinin değiştirilmesi"
                        ),

                    "verified":
                        True,

                    "notes":
                        (
                            "Çalışmaya ara vermeden "
                            "yararlanamayan bazı idari yargı "
                            "mercilerine ilişkin mevcut "
                            "istisna metninin dayanağı."
                        ),
                },
                {
                    "evidence_id":
                        "ev_2577_m61_f1_current_consolidated",

                    "kind":
                        "consolidated_legislation",

                    "source_document_id":
                        "kanun_2577",

                    "source_url":
                        MEVZUAT_SOURCE_URL,

                    "citation":
                        (
                            "2577 sayılı İdari Yargılama "
                            "Usulü Kanunu m.61/1 - "
                            "güncel konsolide mevzuat"
                        ),

                    "verified":
                        True,

                    "notes":
                        (
                            "Current provision text için "
                            "konsolide mevzuat kontrolü."
                        ),
                },
            ],
        },

        "applicability": {
            "windows_complete":
                False,

            "windows_complete_verified":
                False,

            "completion_evidence":
                [],

            "windows":
                [],

            "notes":
                (
                    "m.61/1 yalnız dönem tarihlerini değil, "
                    "çalışmaya ara vermeden yararlanamayan "
                    "bazı idari yargı mercilerine ilişkin "
                    "istisnayı da içerir. Bu nedenle somut "
                    "mahkeme bakımından judicial-recess "
                    "applicability ayrıca deterministik "
                    "olarak çözülmelidir."
                ),
        },

        "subject_periods":
            [],

        "relations":
            [],

        "notes":
            (
                "İYUK m.61/1 current provision version. "
                "Deadline Calculator'ın m.8/3 kapsamındaki "
                "çalışmaya ara verme düzeltmesinde kullanılacak "
                "canonical dönem ve istisna dayanağıdır."
            ),
    }


# ============================================================
# MAIN
# ============================================================

def run():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - ADD IYUK M61/F1 PROVISION V1"
    )

    print(
        "======================================"
    )

    manifest = load_json(
        PROVISIONS_PATH
    )

    if (
        manifest.get(
            "schema_version"
        )
        != 1
    ):

        raise RuntimeError(
            "provisions.json schema_version != 1"
        )

    provisions = manifest.get(
        "provisions",
        []
    )

    if not isinstance(
        provisions,
        list,
    ):

        raise RuntimeError(
            "provisions alanı list değil."
        )

    # ========================================================
    # KANUN 2577 EXISTS
    # ========================================================

    if not any(
        (
            isinstance(
                provision,
                dict,
            )
            and provision.get(
                "document_id"
            )
            == "kanun_2577"
        )
        for provision
        in provisions
    ):

        raise RuntimeError(
            "kanun_2577 provision ailesi bulunamadı."
        )

    # ========================================================
    # DUPLICATE / IDEMPOTENT
    # ========================================================

    existing_ids = {
        provision.get(
            "provision_id"
        )
        for provision
        in provisions
        if isinstance(
            provision,
            dict,
        )
    }

    existing_version_ids = {
        provision.get(
            "provision_version_id"
        )
        for provision
        in provisions
        if isinstance(
            provision,
            dict,
        )
    }

    id_exists = (
        TARGET_PROVISION_ID
        in existing_ids
    )

    version_exists = (
        TARGET_PROVISION_VERSION_ID
        in existing_version_ids
    )

    if (
        id_exists
        and version_exists
    ):

        print()

        print(
            "IYUK m.61/1 provision zaten mevcut."
        )

        print(
            "Değişiklik yapılmadı."
        )

        print()

        print(
            "======================================"
        )

        print(
            " ADD IYUK M61/F1 PROVISION V1: ALREADY PRESENT"
        )

        print(
            "======================================"
        )

        return

    if (
        id_exists
        or version_exists
    ):

        raise RuntimeError(
            "Partial/duplicate m.61/1 state bulundu.\n"
            "Güvenlik nedeniyle overwrite yapılmadı.\n"
            f"Provision ID exists: {id_exists}\n"
            f"Version ID exists: {version_exists}"
        )

    before_count = len(
        provisions
    )

    # ========================================================
    # DEEP COPY + ADD
    # ========================================================

    candidate = json.loads(
        json.dumps(
            manifest,
            ensure_ascii=False,
        )
    )

    candidate[
        "provisions"
    ].append(
        build_provision()
    )

    # ========================================================
    # PRE-WRITE VALIDATION
    # ========================================================

    validate_schema(
        candidate
    )

    print(
        "Provisions schema:",
        "PASS"
    )

    # ========================================================
    # BACKUP
    # ========================================================

    backup_path = backup_file(
        PROVISIONS_PATH
    )

    print()

    print(
        "Backup:",
        backup_path
    )

    # ========================================================
    # WRITE + POST VALIDATE + ROLLBACK
    # ========================================================

    try:

        atomic_write_json(
            PROVISIONS_PATH,
            candidate,
        )

        written = load_json(
            PROVISIONS_PATH
        )

        validate_schema(
            written
        )

        matching = [
            provision
            for provision
            in written.get(
                "provisions",
                []
            )
            if (
                isinstance(
                    provision,
                    dict,
                )
                and provision.get(
                    "provision_id"
                )
                == TARGET_PROVISION_ID
            )
        ]

        if len(
            matching
        ) != 1:

            raise RuntimeError(
                "Post-write target provision "
                "tam olarak bir kez bulunmadı."
            )

        provision = matching[
            0
        ]

        if (
            provision.get(
                "verification_state"
            )
            != "verified"
        ):

            raise RuntimeError(
                "Post-write verification_state "
                "verified değil."
            )

        formal = provision.get(
            "formal",
            {}
        )

        if (
            formal.get(
                "verified"
            )
            is not True
        ):

            raise RuntimeError(
                "Post-write formal.verified True değil."
            )

        if (
            formal.get(
                "status"
            )
            != "active"
        ):

            raise RuntimeError(
                "Post-write formal.status active değil."
            )

    except Exception:

        shutil.copy2(
            backup_path,
            PROVISIONS_PATH,
        )

        print()

        print(
            "WRITE / POST VALIDATION FAIL"
        )

        print(
            "Rollback uygulandı."
        )

        raise

    after_count = len(
        written[
            "provisions"
        ]
    )

    # ========================================================
    # OUTPUT
    # ========================================================

    print()

    print(
        "PROVISION EKLENDİ:"
    )

    print(
        "-",
        TARGET_PROVISION_ID
    )

    print(
        "- version:",
        TARGET_PROVISION_VERSION_ID
    )

    print(
        "- locator:",
        {
            "madde":
                "61",

            "fikra":
                "1",

            "bent":
                None,
        }
    )

    print(
        "- verification_state: verified"
    )

    print(
        "- formal.status: active"
    )

    print(
        "- formal.valid_from: 2016-07-23"
    )

    print()

    print(
        "Provision count:",
        before_count,
        "->",
        after_count,
    )

    print()

    print(
        "NOT:"
    )

    print(
        "- deadline rule değiştirilmedi"
    )

    print(
        "- legal_basis_refs değiştirilmedi"
    )

    print(
        "- calculator henüz çalıştırılmadı"
    )

    print()

    print(
        "======================================"
    )

    print(
        " ADD IYUK M61/F1 PROVISION V1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        run()

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
            " ADD IYUK M61/F1 PROVISION V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )