# ============================================================
# VERGİ AI
# ADD IYUK M8/F3 DEADLINE LEGAL BASIS V1
#
# AMAÇ
# ----
#
# Deadline Engine için:
#
#   kanun_2577_m8_f3
#
# canonical provision'ını provisions.json'a eklemek
# ve deadline rule legal_basis_refs listesine:
#
#   IYUK_2577_m8_3
#
# referansını eklemek.
#
#
# KRİTİK GÜVENLİK
# ----------------
#
# Bu script:
#
# - deadline rule'u ACTIVE yapmaz.
# - calculation_enabled=True yapmaz.
# - mevcut kayıtların üzerine yazmaz.
# - backup alır.
# - schema validation yapar.
# - atomic write yapar.
# - post-write validation yapar.
# - hata halinde rollback uygular.
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

DEADLINE_RULES_PATH = (
    DATA_DIR
    / "deadline_rules"
    / "deadline_rules.json"
)

DEADLINE_RULE_SCHEMA_PATH = (
    DATA_DIR
    / "deadline_rule.schema.json"
)


# ============================================================
# IDS
# ============================================================

TARGET_PROVISION_ID = (
    "kanun_2577_m8_f3"
)

TARGET_PROVISION_VERSION_ID = (
    "kanun_2577_m8_f3_v1"
)

TARGET_RULE_ID = (
    "iyuk_tax_court_general_lawsuit_filing"
)

TARGET_LEGAL_BASIS_REF = (
    "IYUK_2577_m8_3"
)


# ============================================================
# SOURCES
# ============================================================

MEVZUAT_SOURCE_URL = (
    "https://www.mevzuat.gov.tr/"
    "MevzuatMetin/1.5.2577.pdf"
)

TBMM_SOURCE_URL = (
    "https://www5.tbmm.gov.tr/"
    "tutanaklar/KANUNLAR_KARARLAR/"
    "kanuntbmmc065/kanunmgkc065/"
    "kanunmgkc06502577.pdf"
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
            + ".before_iyuk_m8f3_"
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
    schema_path,
    label,
):

    schema = load_json(
        schema_path
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
        f"{label} schema validation FAIL:\n- "
        + "\n- ".join(
            messages
        )
    )


# ============================================================
# PROVISION
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
                "8",

            "fikra":
                "3",

            "bent":
                None,
        },

        "formal": {
            "verified":
                True,

            "status":
                "active",

            "valid_from":
                "1982-01-20",

            "valid_through":
                None,

            "repeal_effective_date":
                None,

            "evidence": [
                {
                    "evidence_id":
                        "ev_2577_m8_f3_original_statute",

                    "kind":
                        "statute_text",

                    "source_document_id":
                        "kanun_2577",

                    "source_url":
                        TBMM_SOURCE_URL,

                    "citation":
                        (
                            "2577 sayılı İdari "
                            "Yargılama Usulü Kanunu "
                            "m.8/3"
                        ),

                    "verified":
                        True,

                    "notes":
                        (
                            "2577 sayılı Kanunun "
                            "yayımlanan kanun metnindeki "
                            "çalışmaya ara verme süresi "
                            "hükmü."
                        ),
                },
                {
                    "evidence_id":
                        "ev_2577_m8_f3_current_consolidated",

                    "kind":
                        "consolidated_legislation",

                    "source_document_id":
                        "kanun_2577",

                    "source_url":
                        MEVZUAT_SOURCE_URL,

                    "citation":
                        (
                            "2577 sayılı İdari "
                            "Yargılama Usulü Kanunu "
                            "m.8/3 - güncel konsolide mevzuat"
                        ),

                    "verified":
                        True,

                    "notes":
                        (
                            "Güncel konsolide hüküm kontrolü."
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
                    "Çalışmaya ara verme kuralının "
                    "somut olaya uygulanabilirliği "
                    "Deadline Calculator Policy "
                    "tarafından ayrıca değerlendirilecektir."
                ),
        },

        "subject_periods":
            [],

        "relations":
            [],

        "notes":
            (
                "İYUK m.8/3. Bu Kanunda yazılı "
                "sürelerin bitişinin çalışmaya ara "
                "verme dönemine rastlamasına ilişkin "
                "deadline extension provision'ı."
            ),
    }


# ============================================================
# FIND RULE
# ============================================================

def find_target_rule(
    ruleset,
):

    matches = [
        rule
        for rule
        in ruleset.get(
            "rules",
            []
        )
        if (
            isinstance(
                rule,
                dict,
            )
            and rule.get(
                "rule_id"
            )
            == TARGET_RULE_ID
        )
    ]

    if len(
        matches
    ) != 1:

        raise RuntimeError(
            "Target deadline rule tam olarak "
            "bir kez bulunmalı.\n"
            f"Bulunan: {len(matches)}"
        )

    return matches[
        0
    ]


# ============================================================
# MAIN
# ============================================================

def run():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - ADD IYUK M8/F3 BASIS V1"
    )

    print(
        "======================================"
    )

    provisions_manifest = (
        load_json(
            PROVISIONS_PATH
        )
    )

    deadline_rules = (
        load_json(
            DEADLINE_RULES_PATH
        )
    )

    # ========================================================
    # CURRENT COUNTS
    # ========================================================

    provisions = (
        provisions_manifest.get(
            "provisions",
            []
        )
    )

    if not isinstance(
        provisions,
        list,
    ):

        raise RuntimeError(
            "provisions alanı list değil."
        )

    before_provision_count = len(
        provisions
    )

    # ========================================================
    # DOCUMENT EXISTENCE SAFETY
    # ========================================================

    iyuk_existing = any(
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
    )

    if not iyuk_existing:

        raise RuntimeError(
            "kanun_2577 provision ailesi bulunamadı."
        )

    # ========================================================
    # DUPLICATE SAFETY
    # ========================================================

    existing_provision_ids = {
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

    provision_exists = (
        TARGET_PROVISION_ID
        in existing_provision_ids
    )

    version_exists = (
        TARGET_PROVISION_VERSION_ID
        in existing_version_ids
    )

    target_rule = (
        find_target_rule(
            deadline_rules
        )
    )

    legal_basis_refs = (
        target_rule.get(
            "legal_basis_refs",
            []
        )
    )

    if not isinstance(
        legal_basis_refs,
        list,
    ):

        raise RuntimeError(
            "legal_basis_refs list değil."
        )

    ref_exists = (
        TARGET_LEGAL_BASIS_REF
        in legal_basis_refs
    )

    # ========================================================
    # IDEMPOTENT COMPLETE STATE
    # ========================================================

    if (
        provision_exists
        and version_exists
        and ref_exists
    ):

        print()

        print(
            "IYUK m.8/3 provision ve deadline "
            "legal basis ref zaten mevcut."
        )

        print()

        print(
            "Değişiklik yapılmadı."
        )

        print()

        print(
            "======================================"
        )

        print(
            " ADD IYUK M8/F3 BASIS V1: ALREADY PRESENT"
        )

        print(
            "======================================"
        )

        return

    # ========================================================
    # PARTIAL STATE FAIL-CLOSED
    # ========================================================

    if (
        provision_exists
        or version_exists
        or ref_exists
    ):

        raise RuntimeError(
            "Partial IYUK m.8/3 state bulundu.\n"
            "Otomatik overwrite yapılmadı.\n"
            f"Provision exists: {provision_exists}\n"
            f"Version exists: {version_exists}\n"
            f"Rule ref exists: {ref_exists}"
        )

    # ========================================================
    # RULE MUST STILL BE DRAFT
    # ========================================================

    if (
        target_rule.get(
            "status"
        )
        != "draft"
    ):

        raise RuntimeError(
            "Deadline rule draft değil. "
            "Güvenlik nedeniyle işlem durduruldu."
        )

    if (
        target_rule.get(
            "calculation_enabled"
        )
        is not False
    ):

        raise RuntimeError(
            "calculation_enabled false değil. "
            "Güvenlik nedeniyle işlem durduruldu."
        )

    # ========================================================
    # DEEP COPY
    # ========================================================

    new_provisions_manifest = (
        json.loads(
            json.dumps(
                provisions_manifest,
                ensure_ascii=False,
            )
        )
    )

    new_deadline_rules = (
        json.loads(
            json.dumps(
                deadline_rules,
                ensure_ascii=False,
            )
        )
    )

    # ========================================================
    # ADD PROVISION
    # ========================================================

    new_provisions_manifest[
        "provisions"
    ].append(
        build_provision()
    )

    # ========================================================
    # ADD LEGAL BASIS REF
    # ========================================================

    new_target_rule = (
        find_target_rule(
            new_deadline_rules
        )
    )

    new_target_rule[
        "legal_basis_refs"
    ].append(
        TARGET_LEGAL_BASIS_REF
    )

    # ========================================================
    # SAFETY: RULE MUST REMAIN DRAFT
    # ========================================================

    assert (
        new_target_rule[
            "status"
        ]
        == "draft"
    )

    assert (
        new_target_rule[
            "calculation_enabled"
        ]
        is False
    )

    # ========================================================
    # PRE-WRITE SCHEMA VALIDATION
    # ========================================================

    validate_schema(
        new_provisions_manifest,
        PROVISIONS_SCHEMA_PATH,
        "provisions.json",
    )

    print(
        "Provisions schema:",
        "PASS"
    )

    validate_schema(
        new_deadline_rules,
        DEADLINE_RULE_SCHEMA_PATH,
        "deadline_rules.json",
    )

    print(
        "Deadline rules schema:",
        "PASS"
    )

    # ========================================================
    # BACKUP
    # ========================================================

    provisions_backup = (
        backup_file(
            PROVISIONS_PATH
        )
    )

    rules_backup = (
        backup_file(
            DEADLINE_RULES_PATH
        )
    )

    print()

    print(
        "Backup provisions:",
        provisions_backup
    )

    print(
        "Backup deadline rules:",
        rules_backup
    )

    # ========================================================
    # WRITE + POST VALIDATE + ROLLBACK
    # ========================================================

    try:

        atomic_write_json(
            PROVISIONS_PATH,
            new_provisions_manifest,
        )

        atomic_write_json(
            DEADLINE_RULES_PATH,
            new_deadline_rules,
        )

        written_provisions = (
            load_json(
                PROVISIONS_PATH
            )
        )

        written_rules = (
            load_json(
                DEADLINE_RULES_PATH
            )
        )

        validate_schema(
            written_provisions,
            PROVISIONS_SCHEMA_PATH,
            "provisions.json post-write",
        )

        validate_schema(
            written_rules,
            DEADLINE_RULE_SCHEMA_PATH,
            "deadline_rules.json post-write",
        )

    except Exception:

        shutil.copy2(
            provisions_backup,
            PROVISIONS_PATH,
        )

        shutil.copy2(
            rules_backup,
            DEADLINE_RULES_PATH,
        )

        print()

        print(
            "POST-WRITE VALIDATION FAIL"
        )

        print(
            "Rollback uygulandı."
        )

        raise

    # ========================================================
    # POST STATE
    # ========================================================

    after_provision_count = len(
        written_provisions[
            "provisions"
        ]
    )

    written_target_rule = (
        find_target_rule(
            written_rules
        )
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

    print()

    print(
        "LEGAL BASIS REF EKLENDİ:"
    )

    print(
        "-",
        TARGET_LEGAL_BASIS_REF
    )

    print()

    print(
        "Provision count:",
        before_provision_count,
        "->",
        after_provision_count,
    )

    print()

    print(
        "Deadline rule:"
    )

    print(
        "- status:",
        written_target_rule[
            "status"
        ]
    )

    print(
        "- calculation_enabled:",
        written_target_rule[
            "calculation_enabled"
        ]
    )

    print(
        "- legal basis count:",
        len(
            written_target_rule[
                "legal_basis_refs"
            ]
        )
    )

    print()

    print(
        "GÜVENLİK:"
    )

    print(
        "- rule halen draft"
    )

    print(
        "- hesaplama halen kapalı"
    )

    print()

    print(
        "======================================"
    )

    print(
        " ADD IYUK M8/F3 BASIS V1: PASS"
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
            " ADD IYUK M8/F3 BASIS V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )