# ============================================================
# VERGİ AI
# ADD IYUK 2577 DEADLINE PROVISIONS V1
#
# AMAÇ
# ----
# 2577 sayılı İdari Yargılama Usulü Kanununu ve
# Deadline Engine V1 için gerekli dört provision'ı mevcut
# Legal Knowledge Engine manifestlerine güvenli biçimde eklemek.
#
# EKLENEN DOCUMENT
# ----------------
# kanun_2577
#
# EKLENEN PROVISIONS
# ------------------
# kanun_2577_m7_f1
# kanun_2577_m7_f2_b
# kanun_2577_m8_f1
# kanun_2577_m8_f2
#
# GÜVENLİK
# --------
# - Mevcut kayıtlar korunur.
# - Duplicate ID varsa üzerine yazılmaz.
# - Önce JSON Schema validation yapılır.
# - Yazımdan önce backup alınır.
# - Atomic write kullanılır.
# - UTF-8 BOM oluşturulmaz.
# ============================================================

import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


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

DOCUMENTS_PATH = (
    DATA_DIR
    / "documents.json"
)

PROVISIONS_PATH = (
    DATA_DIR
    / "provisions.json"
)

DOCUMENTS_SCHEMA_PATH = (
    DATA_DIR
    / "documents.schema.json"
)

PROVISIONS_SCHEMA_PATH = (
    DATA_DIR
    / "provisions.schema.json"
)


# ============================================================
# OFFICIAL / LEGAL SOURCES
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

def load_json(path):

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Dosya bulunamadı:\n{path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(file)


def atomic_write_json(
    path,
    data,
):

    path = Path(path)

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

        file.write("\n")

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

def backup_file(path):

    path = Path(path)

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
            + ".before_iyuk_2577_"
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

def validate_against_schema(
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

        if location:

            messages.append(
                f"{location}: "
                f"{error.message}"
            )

        else:

            messages.append(
                error.message
            )

    raise RuntimeError(
        f"{label} schema validation FAIL:\n- "
        + "\n- ".join(messages)
    )


# ============================================================
# EVIDENCE BUILDERS
# ============================================================

def build_formal_evidence(
    provision_key,
    citation,
):

    return [
        {
            "evidence_id":
                f"ev_{provision_key}_original_statute",

            "kind":
                "statute_text",

            "source_document_id":
                "kanun_2577",

            "source_url":
                TBMM_SOURCE_URL,

            "citation":
                citation,

            "verified":
                True,

            "notes":
                (
                    "2577 sayılı Kanunun yayımlanan "
                    "kanun metnindeki hüküm."
                ),
        },
        {
            "evidence_id":
                f"ev_{provision_key}_current_consolidated",

            "kind":
                "consolidated_legislation",

            "source_document_id":
                "kanun_2577",

            "source_url":
                MEVZUAT_SOURCE_URL,

            "citation":
                (
                    citation
                    + " - güncel konsolide mevzuat"
                ),

            "verified":
                True,

            "notes":
                (
                    "Mevzuat Bilgi Sistemi güncel "
                    "konsolide metin kontrolü."
                ),
        },
    ]


# ============================================================
# DOCUMENT
# ============================================================

def build_document():

    return {
        "document_id":
            "kanun_2577",

        "file_name":
            "2577.pdf",

        "active":
            True,

        "belge_turu":
            "Kanun",

        "title":
            "İdari Yargılama Usulü Kanunu",

        "short_title":
            "2577 sayılı İYUK",

        "kanun_no":
            "2577",

        "document_number":
            "2577",

        "kaynak_kurum":
            "T.C. Cumhurbaşkanlığı Mevzuat Bilgi Sistemi",

        "official_source":
            True,

        "source_url":
            MEVZUAT_SOURCE_URL,

        "resmi_gazete_tarihi":
            "1982-01-20",

        "resmi_gazete_sayisi":
            "17580",

        "yayin_tarihi":
            "1982-01-20",

        "yururluk_tarihi":
            "1982-01-20",

        "gecerlilik_baslangici":
            "1982-01-20",

        "gecerlilik_sonu":
            None,

        "mulga_tarihi":
            None,

        "status":
            "active",

        "version":
            "1",

        "previous_version":
            None,

        "next_version":
            None,

        "supersedes":
            None,

        "superseded_by":
            None,

        "jurisdiction":
            "TR",

        "language":
            "tr",

        "tags": [
            "idari_yargi",
            "vergi_davasi",
            "dava_acma_suresi",
            "sureler",
            "iyuk",
        ],

        "relations":
            [],

        "ingest": {
            # Fiziksel PDF henüz proje data/source alanına
            # alınmadığı için güvenli biçimde kapalı.
            #
            # Provision Repository elle doğrulanmış
            # canonical provision kayıtlarını yine kullanabilir.
            "enabled":
                False,

            "parser":
                "legal_pdf",

            "chunk_strategy":
                "legal_hierarchy",

            "ocr_required":
                False,
        },

        "notes":
            (
                "2577 sayılı İdari Yargılama Usulü Kanunu. "
                "Deadline Engine V1 için m.7/1, m.7/2-b, "
                "m.8/1 ve m.8/2 provision kayıtları "
                "canonical Legal Knowledge Engine'e "
                "eklenmiştir. Fiziksel PDF ingest işlemi "
                "ayrı adımda yapılacaktır."
            ),
    }


# ============================================================
# PROVISION BASE
# ============================================================

def build_provision(
    provision_id,
    provision_version_id,
    madde,
    fikra,
    bent,
    citation,
    notes,
):

    evidence_key = (
        provision_id
        .replace(
            "kanun_",
            ""
        )
    )

    return {
        "provision_id":
            provision_id,

        "provision_version_id":
            provision_version_id,

        "document_id":
            "kanun_2577",

        "enabled":
            True,

        "verification_state":
            "verified",

        "locator": {
            "madde":
                madde,

            "fikra":
                fikra,

            "bent":
                bent,
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

            "evidence":
                build_formal_evidence(
                    evidence_key,
                    citation,
                ),
        },

        "applicability": {
            # Provision metni/formal yürürlük
            # doğrulanmıştır; tüm olası özel-kanun
            # istisnaları burada modellenmemektedir.
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
                    "Provision-level tüm özel uygulama "
                    "pencereleri exhaustively modellenmemiştir. "
                    "Deadline Rule Selection Policy özel kanun "
                    "ve case applicability kontrollerini ayrıca "
                    "uygulamalıdır."
                ),
        },

        "subject_periods":
            [],

        "relations":
            [],

        "notes":
            notes,
    }


# ============================================================
# PROVISIONS
# ============================================================

def build_provisions():

    return [
        build_provision(
            provision_id=
                "kanun_2577_m7_f1",

            provision_version_id=
                "kanun_2577_m7_f1_v1",

            madde=
                "7",

            fikra=
                "1",

            bent=
                None,

            citation=
                (
                    "2577 sayılı İdari Yargılama "
                    "Usulü Kanunu m.7/1"
                ),

            notes=
                (
                    "Özel kanunda ayrı süre bulunmayan "
                    "hallerde vergi mahkemelerinde genel "
                    "dava açma süresine ilişkin provision."
                ),
        ),

        build_provision(
            provision_id=
                "kanun_2577_m7_f2_b",

            provision_version_id=
                "kanun_2577_m7_f2_b_v1",

            madde=
                "7",

            fikra=
                "2",

            bent=
                "b",

            citation=
                (
                    "2577 sayılı İdari Yargılama "
                    "Usulü Kanunu m.7/2-b"
                ),

            notes=
                (
                    "Vergi, resim, harç ve benzeri mali "
                    "yükümlülükler ile zam ve cezalarından "
                    "doğan uyuşmazlıklarda dava süresinin "
                    "başlangıç olaylarına ilişkin provision."
                ),
        ),

        build_provision(
            provision_id=
                "kanun_2577_m8_f1",

            provision_version_id=
                "kanun_2577_m8_f1_v1",

            madde=
                "8",

            fikra=
                "1",

            bent=
                None,

            citation=
                (
                    "2577 sayılı İdari Yargılama "
                    "Usulü Kanunu m.8/1"
                ),

            notes=
                (
                    "Sürelerin tebliğ, yayın veya ilan "
                    "tarihini izleyen günden itibaren "
                    "işlemeye başlamasına ilişkin "
                    "genel süre provision'ı."
                ),
        ),

        build_provision(
            provision_id=
                "kanun_2577_m8_f2",

            provision_version_id=
                "kanun_2577_m8_f2_v1",

            madde=
                "8",

            fikra=
                "2",

            bent=
                None,

            citation=
                (
                    "2577 sayılı İdari Yargılama "
                    "Usulü Kanunu m.8/2"
                ),

            notes=
                (
                    "Tatil günlerinin süre hesabına "
                    "dahil edilmesi ve son günün tatil "
                    "gününe rastlaması durumuna ilişkin "
                    "provision."
                ),
        ),
    ]


# ============================================================
# DUPLICATE CHECK
# ============================================================

def existing_document_ids(
    documents_manifest,
):

    return {
        document.get(
            "document_id"
        )
        for document
        in documents_manifest.get(
            "documents",
            []
        )
        if isinstance(
            document,
            dict,
        )
    }


def existing_provision_ids(
    provisions_manifest,
):

    return {
        provision.get(
            "provision_id"
        )
        for provision
        in provisions_manifest.get(
            "provisions",
            []
        )
        if isinstance(
            provision,
            dict,
        )
    }


def existing_provision_version_ids(
    provisions_manifest,
):

    return {
        provision.get(
            "provision_version_id"
        )
        for provision
        in provisions_manifest.get(
            "provisions",
            []
        )
        if isinstance(
            provision,
            dict,
        )
    }


# ============================================================
# MAIN UPDATE
# ============================================================

def run():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - ADD IYUK 2577 PROVISIONS V1"
    )

    print(
        "======================================"
    )

    documents_manifest = load_json(
        DOCUMENTS_PATH
    )

    provisions_manifest = load_json(
        PROVISIONS_PATH
    )

    if (
        documents_manifest.get(
            "schema_version"
        )
        != 1
    ):

        raise RuntimeError(
            "documents.json schema_version != 1"
        )

    if (
        provisions_manifest.get(
            "schema_version"
        )
        != 1
    ):

        raise RuntimeError(
            "provisions.json schema_version != 1"
        )

    document = build_document()

    provisions = build_provisions()

    document_ids = (
        existing_document_ids(
            documents_manifest
        )
    )

    provision_ids = (
        existing_provision_ids(
            provisions_manifest
        )
    )

    provision_version_ids = (
        existing_provision_version_ids(
            provisions_manifest
        )
    )

    target_document_id = (
        document[
            "document_id"
        ]
    )

    target_provision_ids = {
        provision[
            "provision_id"
        ]
        for provision
        in provisions
    }

    target_version_ids = {
        provision[
            "provision_version_id"
        ]
        for provision
        in provisions
    }

    # ========================================================
    # IDEMPOTENT / PARTIAL STATE SAFETY
    # ========================================================

    document_exists = (
        target_document_id
        in document_ids
    )

    existing_targets = (
        target_provision_ids
        & provision_ids
    )

    existing_target_versions = (
        target_version_ids
        & provision_version_ids
    )

    if (
        document_exists
        and existing_targets
        == target_provision_ids
        and existing_target_versions
        == target_version_ids
    ):

        print()

        print(
            "IYUK 2577 document ve dört provision "
            "zaten mevcut."
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
            " ADD IYUK 2577 PROVISIONS V1: ALREADY PRESENT"
        )

        print(
            "======================================"
        )

        return

    if (
        document_exists
        or existing_targets
        or existing_target_versions
    ):

        raise RuntimeError(
            "Partial/duplicate IYUK 2577 kaydı bulundu.\n"
            "Güvenlik nedeniyle otomatik overwrite yapılmadı.\n"
            f"Document exists: {document_exists}\n"
            f"Provision duplicates: "
            f"{sorted(existing_targets)}\n"
            f"Version duplicates: "
            f"{sorted(existing_target_versions)}"
        )

    before_document_count = len(
        documents_manifest.get(
            "documents",
            []
        )
    )

    before_provision_count = len(
        provisions_manifest.get(
            "provisions",
            []
        )
    )

    # ========================================================
    # BUILD NEW MANIFESTS IN MEMORY
    # ========================================================

    new_documents = json.loads(
        json.dumps(
            documents_manifest,
            ensure_ascii=False,
        )
    )

    new_provisions = json.loads(
        json.dumps(
            provisions_manifest,
            ensure_ascii=False,
        )
    )

    new_documents[
        "documents"
    ].append(
        document
    )

    new_provisions[
        "provisions"
    ].extend(
        provisions
    )

    # ========================================================
    # SCHEMA VALIDATION BEFORE WRITE
    # ========================================================

    validate_against_schema(
        new_documents,
        DOCUMENTS_SCHEMA_PATH,
        "documents.json",
    )

    print(
        "Documents schema:",
        "PASS"
    )

    validate_against_schema(
        new_provisions,
        PROVISIONS_SCHEMA_PATH,
        "provisions.json",
    )

    print(
        "Provisions schema:",
        "PASS"
    )

    # ========================================================
    # BACKUP
    # ========================================================

    documents_backup = backup_file(
        DOCUMENTS_PATH
    )

    provisions_backup = backup_file(
        PROVISIONS_PATH
    )

    print()

    print(
        "Backup documents:",
        documents_backup
    )

    print(
        "Backup provisions:",
        provisions_backup
    )

    # ========================================================
    # WRITE
    # ========================================================

    try:

        atomic_write_json(
            DOCUMENTS_PATH,
            new_documents,
        )

        atomic_write_json(
            PROVISIONS_PATH,
            new_provisions,
        )

        # ====================================================
        # POST-WRITE VALIDATION
        # ====================================================

        written_documents = load_json(
            DOCUMENTS_PATH
        )

        written_provisions = load_json(
            PROVISIONS_PATH
        )

        validate_against_schema(
            written_documents,
            DOCUMENTS_SCHEMA_PATH,
            "documents.json post-write",
        )

        validate_against_schema(
            written_provisions,
            PROVISIONS_SCHEMA_PATH,
            "provisions.json post-write",
        )

    except Exception:

        shutil.copy2(
            documents_backup,
            DOCUMENTS_PATH,
        )

        shutil.copy2(
            provisions_backup,
            PROVISIONS_PATH,
        )

        print()

        print(
            "WRITE/VALIDATION FAIL"
        )

        print(
            "Rollback uygulandı."
        )

        raise

    after_document_count = len(
        new_documents[
            "documents"
        ]
    )

    after_provision_count = len(
        new_provisions[
            "provisions"
        ]
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()

    print(
        "DOCUMENT EKLENDİ:"
    )

    print(
        "- kanun_2577"
    )

    print()

    print(
        "PROVISIONS EKLENDİ:"
    )

    for provision in provisions:

        print(
            "-",
            provision[
                "provision_id"
            ],
            "| locator=",
            provision[
                "locator"
            ],
        )

    print()

    print(
        "Document count:",
        before_document_count,
        "->",
        after_document_count,
    )

    print(
        "Provision count:",
        before_provision_count,
        "->",
        after_provision_count,
    )

    print()

    print(
        "Verification:"
    )

    print(
        "- provision verification_state = verified"
    )

    print(
        "- formal.verified = true"
    )

    print(
        "- verified evidence = present"
    )

    print()

    print(
        "Ingest:"
    )

    print(
        "- kanun_2577 ingest.enabled = false"
    )

    print(
        "- fiziksel PDF ingest ayrı adımda yapılacak"
    )

    print()

    print(
        "======================================"
    )

    print(
        " ADD IYUK 2577 PROVISIONS V1: PASS"
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
            " ADD IYUK 2577 PROVISIONS V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(1)