# ============================================================
# VERGİ AI - FACT APPROVAL / PROMOTION V1
#
# AMAÇ:
#
# LLM tarafından üretilmiş ve validator'dan geçmiş
# *.json.pending extraction çıktısını insan onayı sonrasında
# canonical facts.json haline getirmek.
#
#
# PIPELINE:
#
# facts_llm_*.json.pending
#        ↓
# Case Fact Validator
#        ↓
# Human Review
#        ↓
# --approve
#        ↓
# mevcut facts.json -> history/
#        ↓
# yeni facts.json
#        ↓
# approval audit record
#
#
# KRİTİK PRENSİP:
#
# Approval:
#   extraction'ın kaynak belgeyi kabul edilebilir şekilde
#   temsil ettiğinin insan tarafından onaylanmasıdır.
#
# Approval:
#   maddi gerçeğin doğrulandığı anlamına GELMEZ.
#
# Bu nedenle fact verification_state değerleri değiştirilmez.
# ============================================================


import argparse
import hashlib
import json
import os
import shutil
import sys

from datetime import datetime
from pathlib import Path

from case_fact_validator import (
    validate_fact_extraction,
)

# ROW 19C-3b SLICE 2: yalnız karar içermeyen paylaşılan path primitive'i
# (Row 19C-3a Slice 1) - audit/backup dosya adlarının segment
# doğrulaması ve exact-parent membership'li create-chain çözümü için.
import path_containment


# ============================================================
# VERSION
# ============================================================

FACT_APPROVAL_VERSION = "1"


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

DEFAULT_PENDING_PATH = (
    DATA_DIR
    / "cases"
    / "case_0001"
    / "documents"
    / "vir_001"
    / "extractions"
    / "facts_llm_v1_1.json.pending"
)

# ============================================================
# ROW 19C-3b SLICE 2 - PROMOTION FACADE SURFACE (additive).
#
# `CASES_DIR`, bu modülün writer-containment seam'idir: promotion
# facade/adapter'ları (`ui/services/promotion_mutation_*.py`) bu
# attribute'u HER ÇAĞRIDA dinamik okur (asla cache'lemez) - test
# redirect sweep'leri (`_module.CASES_DIR = tmp`) bu yüzden aynen
# çalışır. `DATA_DIR` yalnız legacy preview yolunun (resolve_paths)
# kendi türetimi için kalır; verified_paths modunda hiçbir I/O
# DATA_DIR'dan türetilmez.
#
# `CURRENT_PENDING_FILENAME`, fact_extraction_engine.py'nin (Row 4,
# LOCKED) run_fact_extraction() çıktısının GÜNCEL sabit adına
# PİNLİDİR (src/fact_extraction_engine.py:3164 civarındaki inline
# literal: "facts_llm_v1_3.json.pending"). Bilinçli olarak glob YOK -
# engine versiyonu değişirse bu resolver fail-closed çözümsüz kalır
# (Row 18a'nın "hangi pending güncel?" itirazının onaylı mirası) ve
# bu sabit ayrı bir incelemeyle güncellenmek zorundadır. Diskteki
# ESKİ versiyon adlı pending'ler (v1, v1_1, v1_2, v1_2_1) bu yoldan
# ÇÖZÜLMEZ - güncel engine yeniden çalıştırılarak yeni pending
# üretilmesi gerekir.
# ============================================================

CASES_DIR = (
    DATA_DIR
    / "cases"
)

CURRENT_PENDING_FILENAME = "facts_llm_v1_3.json.pending"

CANONICAL_FILENAME = "facts.json"


def get_extractions_dir(case_id, document_id):
    """RAW candidate üretimi (güvenlik doğrulaması DEĞİL) - çağıran
    (promotion facade/adapter) bu ham yolu kendi bağımsız
    containment doğrulamasından geçirmek ZORUNDADIR."""
    return CASES_DIR / case_id / "documents" / document_id / "extractions"


def get_pending_path(case_id, document_id):
    return get_extractions_dir(case_id, document_id) / CURRENT_PENDING_FILENAME


def get_canonical_path(case_id, document_id):
    return get_extractions_dir(case_id, document_id) / CANONICAL_FILENAME


def get_history_dir(case_id, document_id):
    return get_extractions_dir(case_id, document_id) / "history"


def get_reviews_dir(case_id, document_id):
    return get_extractions_dir(case_id, document_id) / "reviews"


# ============================================================
# JSON
# ============================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(file)


# ============================================================
# ROW 19C-3b SLICE 2 - TEK SERİALİZATION KAYNAĞI.
#
# `_canonical_json_bytes()` hem gerçek canonical writer'ın
# (`write_json_atomic`) hem `compute_expected_canonical_sha256()`'nın
# kullandığı TEK bayt üreticisidir - iki ayrı serileştirme formülü
# drift edemez. Bayt-uyumluluk notu: bu modülün eski `write_json_atomic`
# gövdesi text-mode (`open(..., "w", encoding="utf-8")`) yazıyordu ve
# Python text-mode'u her yapısal "\n"ı os.linesep'e çevirir (Windows'ta
# CRLF). `json.dumps` string DEĞERLERİ içindeki newline'ları zaten
# "\\n" olarak escape ettiği için literal "\n" YALNIZ indent yapısında
# geçer - aşağıdaki `.replace("\n", os.linesep)` bu yüzden eski
# text-mode çıktısıyla BAYT-BAYT aynı sonucu üretir (izole testte
# golden-bytes karşılaştırmasıyla kanıtlanır). Deterministiktir:
# timestamp/random/audit-metadata İÇERMEZ, dosya sistemine YAZMAZ.
# ============================================================

def _canonical_json_text(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    )


def _canonical_json_bytes(data):
    return _canonical_json_text(data).replace("\n", os.linesep).encode("utf-8")


def write_json_atomic(
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

    temp_path = path.with_name(
        path.name + ".tmp"
    )

    # ROW 19C-3b SLICE 2: aynı serileştirme, artık tek kaynaktan ve
    # binary modda (bkz. yukarıdaki blok yorumu - çıktı baytları eski
    # text-mode gövdeyle birebir aynıdır).
    with open(
        temp_path,
        "wb",
    ) as file:

        file.write(
            _canonical_json_bytes(data)
        )

    os.replace(
        temp_path,
        path,
    )


# ============================================================
# HASH
# ============================================================

def sha256_file(path):

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
# TIME
# ============================================================

def now_iso():

    return (
        datetime.now()
        .astimezone()
        .isoformat()
    )


def now_stamp():

    return (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )


# ============================================================
# CONTEXT PATHS
# ============================================================

def resolve_paths(
    pending_path,
    extraction,
):

    case_id = extraction.get(
        "case_id"
    )

    document_id = extraction.get(
        "source_document_id"
    )

    expected_extractions_dir = (
        DATA_DIR
        / "cases"
        / case_id
        / "documents"
        / document_id
        / "extractions"
    ).resolve()

    actual_extractions_dir = (
        Path(
            pending_path
        )
        .resolve()
        .parent
    )

    if (
        actual_extractions_dir
        != expected_extractions_dir
    ):

        raise ValueError(
            "Pending extraction yanlış klasörde.\n"
            f"Beklenen: {expected_extractions_dir}\n"
            f"Gerçek: {actual_extractions_dir}"
        )

    canonical_path = (
        expected_extractions_dir
        / "facts.json"
    )

    history_dir = (
        expected_extractions_dir
        / "history"
    )

    reviews_dir = (
        expected_extractions_dir
        / "reviews"
    )

    return {
        "extractions_dir":
            expected_extractions_dir,

        "canonical_path":
            canonical_path,

        "history_dir":
            history_dir,

        "reviews_dir":
            reviews_dir,
    }


# ============================================================
# PENDING VALIDATION
# ============================================================

def validate_pending(
    pending_path,
):

    pending_path = Path(
        pending_path
    ).resolve()

    if not pending_path.exists():

        raise FileNotFoundError(
            "Pending extraction bulunamadı:\n"
            f"{pending_path}"
        )

    if not pending_path.name.endswith(
        ".pending"
    ):

        raise ValueError(
            "Approval yalnızca .pending "
            "dosyaları üzerinde çalışabilir."
        )

    validation = (
        validate_fact_extraction(
            facts_path=pending_path,
            raise_on_error=True,
        )
    )

    extraction = load_json(
        pending_path
    )

    if (
        extraction.get(
            "status"
        )
        != "completed"
    ):

        raise ValueError(
            "Yalnızca status=completed "
            "extraction promote edilebilir."
        )

    facts = extraction.get(
        "facts",
        [],
    )

    if not facts:

        raise ValueError(
            "Fact bulunmayan extraction "
            "promote edilemez."
        )

    extractor = extraction.get(
        "extractor",
        {},
    )

    method = extractor.get(
        "method"
    )

    # --------------------------------------------------------
    # LLM kendi fact'ini verified yapamaz.
    # --------------------------------------------------------

    if method in {
        "llm",
        "hybrid",
    }:

        for fact in facts:

            if (
                fact.get(
                    "verification_state"
                )
                != "unverified"
            ):

                raise ValueError(
                    "LLM extraction içinde "
                    "verification_state=unverified "
                    "olmayan fact bulundu: "
                    f"{fact.get('fact_id')}"
                )

    return (
        extraction,
        validation,
    )


# ============================================================
# BACKUP CURRENT CANONICAL
# ============================================================

def backup_current_canonical(
    canonical_path,
    history_dir,
):

    canonical_path = Path(
        canonical_path
    )

    if not canonical_path.exists():

        return None

    history_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    current_hash = (
        sha256_file(
            canonical_path
        )
    )

    backup_name = (
        "facts_before_promotion_"
        f"{now_stamp()}_"
        f"{current_hash[:8]}.json"
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
# BUILD CANONICAL
# ============================================================

def build_canonical(
    extraction,
):

    canonical = json.loads(
        json.dumps(
            extraction,
            ensure_ascii=False,
        )
    )

    canonical[
        "notes"
    ] = (
        "Fact Approval / Promotion V1 ile "
        "human-reviewed canonical extraction "
        "olarak promote edilmiştir. "
        "Bu onay fact'lerin maddi gerçeklik bakımından "
        "verified olduğu anlamına gelmez; "
        "verification_state alanları ayrıca korunur."
    )

    return canonical


def compute_expected_canonical_sha256(pending_path):
    """ROW 19C-3b SLICE 2: pending içeriğinden, gerçek canonical
    writer'ın üreteceği baytların DETERMİNİSTİK beklenen sha256'sı.
    Saf okuma - dosya sistemine hiçbir şey yazmaz; `build_canonical()`
    tek sabit-literal `notes` ataması yapar (timestamp/random yok) ve
    serileştirme `write_json_atomic()` ile AYNI `_canonical_json_bytes`
    kaynağından gelir - bkz. o fonksiyonun kendi blok yorumu."""
    extraction = load_json(pending_path)
    return hashlib.sha256(
        _canonical_json_bytes(build_canonical(extraction))
    ).hexdigest()


# ============================================================
# APPROVAL RECORD
# ============================================================

def build_approval_record(
    extraction,
    pending_path,
    pending_hash,
    canonical_path,
    canonical_hash,
    reviewer_ref,
    review_note,
    backup_path,
    *,
    mutation_idempotency_key=None,
    mutation_resource_key=None,
    mutation_actor_ref=None,
):

    extraction_id = extraction.get(
        "extraction_id"
    )

    # ROW 19C-3b SLICE 2: üç additive, keyword-only mutation-binding
    # alanı (Row 19C-2a Step 5'in 10 aileye yaptığı AYNI desen +
    # Row 19C-2b'nin actor_ref eklemesi). `None` iken alan HİÇ
    # yazılmaz - eski kayıt şekli bayt-uyumlu korunur.
    record = {
        "schema_version":
            1,

        "approval_id":
            (
                "approval_"
                f"{extraction_id}_"
                f"{now_stamp()}"
            ),

        "approval_version":
            FACT_APPROVAL_VERSION,

        "decision":
            "approved_for_canonical_use",

        "approval_scope":
            "extraction_accuracy_review",

        "case_id":
            extraction.get(
                "case_id"
            ),

        "source_document_id":
            extraction.get(
                "source_document_id"
            ),

        "extraction_id":
            extraction_id,

        "fact_count":
            len(
                extraction.get(
                    "facts",
                    [],
                )
            ),

        "reviewer_ref":
            reviewer_ref,

        "reviewed_at":
            now_iso(),

        "review_note":
            review_note,

        "source_pending_file":
            str(
                pending_path
            ),

        "source_pending_sha256":
            pending_hash,

        "canonical_file":
            str(
                canonical_path
            ),

        "canonical_sha256":
            canonical_hash,

        "previous_canonical_backup":
            (
                str(
                    backup_path
                )
                if backup_path
                else None
            ),

        "verification_semantics":
            (
                "Approval extraction doğruluğunu "
                "temsil eder; fact verification_state "
                "değerlerini değiştirmez."
            )
    }

    if mutation_idempotency_key is not None:
        record["mutation_idempotency_key"] = mutation_idempotency_key
    if mutation_resource_key is not None:
        record["mutation_resource_key"] = mutation_resource_key
    if mutation_actor_ref is not None:
        record["mutation_actor_ref"] = mutation_actor_ref

    return record


# ============================================================
# ROW 19C-3b SLICE 2 - VERIFIED-PATH TOPOLOJİ KONTROLÜ + O_EXCL AUDIT
# ============================================================

_VERIFIED_PATHS_KEYS = frozenset(
    {"extractions_dir", "pending_path", "canonical_path", "history_dir", "reviews_dir"}
)


def _check_verified_paths_topology(pending_path, extraction, verified_paths):
    """`verified_paths` (promotion facade'in kilit ALTINDA doğruladığı
    Path paketi) verildiğinde: TÜM filesystem I/O bu değerlerden yürür;
    bu fonksiyon yazımdan ÖNCE, saf Path karşılaştırmalarıyla, paketin
    kendi içinde VE pending İÇERİĞİYLE tutarlı olduğunu fail-closed
    doğrular. `resolve_paths()`'in DATA_DIR-türetimi verified modda NE
    I/O NE de kontrol otoritesi olarak kullanılır (test redirect
    seam'i `CASES_DIR` üzerindedir - bkz. modül başındaki Slice 2
    bloğu); konum otoritesi facade'in containment zinciridir, burası
    onun üstüne bağımsız bir topoloji/içerik çapraz-kontrolüdür."""

    if set(verified_paths.keys()) != _VERIFIED_PATHS_KEYS:
        raise ValueError(
            "verified_paths anahtar seti tam olarak "
            f"{sorted(_VERIFIED_PATHS_KEYS)} olmalıdır."
        )

    extractions_dir = Path(verified_paths["extractions_dir"])
    vp_pending = Path(verified_paths["pending_path"])
    canonical_path = Path(verified_paths["canonical_path"])
    history_dir = Path(verified_paths["history_dir"])
    reviews_dir = Path(verified_paths["reviews_dir"])

    # YAPISAL kontrol seti (bilinçli): parent-eşitlikleri + LEAF ad
    # pinleri. Container/ata dizinlerin LİTERAL adları kontrol edilmez -
    # güvenli bir case-İÇİ alias/junction'ın çözülmüş gerçek hedefi
    # farklı bir ada sahip olabilir ve bu meşrudur (facade'in
    # containment zinciri konum otoritesidir; case_id/source_document_id
    # içerik bağlaması facade'in kendi çapraz-kontrolünde, pre-lock VE
    # kilit altında ayrıca yapılır). Leaf pinleri korunur: kendisi bir
    # link olan pending/canonical, çözümde adı değişeceği için burada
    # fail-closed reddedilir.
    failures = []
    if vp_pending != Path(pending_path):
        failures.append("pending_path argümanı ile verified_paths['pending_path'] farklı")
    if vp_pending.parent != extractions_dir:
        failures.append("pending, extractions_dir'in doğrudan çocuğu değil")
    if vp_pending.name != CURRENT_PENDING_FILENAME:
        failures.append("pending leaf adı pinli engine adıyla eşleşmiyor")
    if canonical_path.parent != extractions_dir or canonical_path.name != CANONICAL_FILENAME:
        failures.append("canonical_path topolojisi beklenen değil")
    if history_dir.parent != extractions_dir:
        failures.append("history_dir, extractions_dir'in doğrudan çocuğu değil")
    if reviews_dir.parent != extractions_dir:
        failures.append("reviews_dir, extractions_dir'in doğrudan çocuğu değil")
    if extraction.get("case_id") in (None, "") or extraction.get("source_document_id") in (None, ""):
        failures.append("pending içeriği case_id/source_document_id taşımıyor")

    if failures:
        raise ValueError(
            "verified_paths topoloji/içerik çapraz-kontrolü başarısız "
            "(hiçbir yazım yapılmadı): " + "; ".join(failures)
        )

    return {
        "extractions_dir": extractions_dir,
        "canonical_path": canonical_path,
        "history_dir": history_dir,
        "reviews_dir": reviews_dir,
    }


def _write_audit_record_excl(reviews_dir, extraction_id, approval_record):
    """ROW 19C-3b SLICE 2: sabit `<extraction_id>.approval.json` adının
    ÜZERİNE YAZMA sınıfını kapatır - zaman damgalı taban ad +
    `O_CREAT|O_EXCL` + sayısal sonek (18c emsali). Ad
    `path_containment.validate_segment()`'ten geçer ve
    `resolve_for_create()` exact-parent membership'i korur; eski
    (legacy) audit dosyaları asla ezilmez, yan yana yaşar - replay/
    reconciliation eşleşmesi HER ZAMAN içerikten yapılır, addan asla."""
    reviews_dir = Path(reviews_dir)
    reviews_dir.mkdir(parents=True, exist_ok=True)
    base = f"{extraction_id}_{now_stamp()}"
    suffix = 0
    while True:
        if suffix == 0:
            name = f"{base}.approval.json"
        else:
            name = f"{base}_{suffix}.approval.json"
        path_containment.validate_segment(name)
        candidate = path_containment.resolve_for_create(reviews_dir, name)
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            suffix += 1
            if suffix > 1000:
                raise RuntimeError(
                    "Approval audit dosya adı için 1000 denemede boş ad bulunamadı."
                )
            continue
        with os.fdopen(fd, "wb") as file:
            file.write(_canonical_json_bytes(approval_record))
        return candidate


# ============================================================
# REVIEW ONLY
# ============================================================

def review_pending(
    pending_path,
):

    extraction, validation = (
        validate_pending(
            pending_path
        )
    )

    paths = resolve_paths(
        pending_path,
        extraction,
    )

    pending_hash = sha256_file(
        pending_path
    )

    return {
        "extraction":
            extraction,

        "validation":
            validation,

        "paths":
            paths,

        "pending_hash":
            pending_hash,
    }


# ============================================================
# PROMOTION
# ============================================================

def promote(
    pending_path,
    reviewer_ref,
    review_note,
    *,
    verified_paths=None,
    mutation_idempotency_key=None,
    mutation_resource_key=None,
    mutation_actor_ref=None,
):
    # ROW 19C-3b SLICE 2: dört additive, keyword-only parametre.
    # `verified_paths=None` -> eski davranış (resolve_paths tabanlı)
    # AYNEN korunur. verified_paths verildiğinde (yalnız promotion
    # facade'i verir) TÜM filesystem I/O kilit-altı doğrulanmış bu
    # Path'lerden yürür; DATA_DIR-türetimi hiçbir amaçla kullanılmaz
    # (bkz. _check_verified_paths_topology docstring'i).

    pending_path = Path(
        pending_path
    )

    extraction, validation_pre = validate_pending(
        pending_path
    )

    pending_hash = sha256_file(
        pending_path
    )

    if verified_paths is None:

        paths = resolve_paths(
            pending_path,
            extraction,
        )

    else:

        paths = _check_verified_paths_topology(
            pending_path,
            extraction,
            verified_paths,
        )

    canonical_path = paths[
        "canonical_path"
    ]

    history_dir = paths[
        "history_dir"
    ]

    reviews_dir = paths[
        "reviews_dir"
    ]

    # ========================================================
    # BACKUP CURRENT FACTS.JSON
    # ========================================================

    backup_path = (
        backup_current_canonical(
            canonical_path,
            history_dir,
        )
    )

    # ========================================================
    # BUILD NEW CANONICAL
    # ========================================================

    canonical = build_canonical(
        extraction
    )

    write_json_atomic(
        canonical_path,
        canonical,
    )

    # ========================================================
    # VALIDATE CANONICAL AFTER WRITE
    # ========================================================

    try:

        validation = (
            validate_fact_extraction(
                facts_path=canonical_path,
                raise_on_error=True,
            )
        )

    except Exception:

        # ----------------------------------------------------
        # Rollback
        # ----------------------------------------------------

        if backup_path:

            shutil.copy2(
                backup_path,
                canonical_path,
            )

        else:

            if canonical_path.exists():

                canonical_path.unlink()

        raise

    canonical_hash = sha256_file(
        canonical_path
    )

    # ========================================================
    # AUDIT RECORD
    # ========================================================

    approval_record = (
        build_approval_record(
            extraction=extraction,
            pending_path=Path(
                pending_path
            ).resolve(),
            pending_hash=pending_hash,
            canonical_path=canonical_path,
            canonical_hash=canonical_hash,
            reviewer_ref=reviewer_ref,
            review_note=review_note,
            backup_path=backup_path,
            mutation_idempotency_key=mutation_idempotency_key,
            mutation_resource_key=mutation_resource_key,
            mutation_actor_ref=mutation_actor_ref,
        )
    )

    # ROW 19C-3b SLICE 2: sabit-adlı overwrite yerine zaman damgalı,
    # O_EXCL çakışma-korumalı ad - bkz. _write_audit_record_excl.
    approval_path = _write_audit_record_excl(
        reviews_dir,
        extraction[
            "extraction_id"
        ],
        approval_record,
    )

    return {
        "canonical_path":
            canonical_path,

        "backup_path":
            backup_path,

        "approval_path":
            approval_path,

        "validation":
            validation,

        "fact_count":
            len(
                canonical.get(
                    "facts",
                    [],
                )
            ),

        "extraction_id":
            canonical.get(
                "extraction_id"
            ),
    }


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Fact Approval / Promotion V1"
        )
    )

    parser.add_argument(
        "--pending",
        default=str(
            DEFAULT_PENDING_PATH
        ),
    )

    parser.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Pending extraction'ı canonical "
            "facts.json olarak promote eder."
        ),
    )

    parser.add_argument(
        "--reviewer",
        default="human_review",
    )

    parser.add_argument(
        "--note",
        default=(
            "Fact Extraction Engine V1.1 çıktısı "
            "insan tarafından incelendi."
        ),
    )

    args = parser.parse_args()

    if args.approve:

        # ROW 19C-3b SLICE 2: bu doğrudan CLI mutasyon yolu KAPALIDIR -
        # coordinator/journal/authz entegrasyonu yalnız ui.cli_mutate
        # promotion üzerindedir. promote() KENDİSİ dokunulmamıştır ve
        # facade'in çağırdığı gerçek writer olmaya devam eder - yalnız
        # BU executable giriş noktası reddedilir. Refusal, herhangi bir
        # pending okuması/validator çağrısından ÖNCE gelir (stdout boş
        # kalır); SystemExit(2) gerçek process exit code'u 2 üretir.
        print(
            "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3b).\n"
            "Gerçek onay için: python -m ui.cli_mutate promotion --row-key fact ...",
            file=sys.stderr,
        )
        raise SystemExit(2)

    pending_path = Path(
        args.pending
    )

    print()
    print(
        "======================================"
    )

    print(
        " VERGİ AI - FACT APPROVAL V1"
    )

    print(
        "======================================"
    )

    review = review_pending(
        pending_path
    )

    extraction = review[
        "extraction"
    ]

    print()
    print(
        "Extraction ID:",
        extraction[
            "extraction_id"
        ],
    )

    print(
        "Case ID:",
        extraction[
            "case_id"
        ],
    )

    print(
        "Source document:",
        extraction[
            "source_document_id"
        ],
    )

    print(
        "Fact sayısı:",
        len(
            extraction[
                "facts"
            ]
        ),
    )

    print(
        "Validator:",
        "PASS",
    )

    print(
        "SHA256:",
        review[
            "pending_hash"
        ],
    )

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
            "Onaylamak için:"
        )

        print(
            "python src\\fact_approval.py --approve"
        )

        print()
        print(
            "======================================"
        )

        print(
            " FACT APPROVAL V1: READY"
        )

        print(
            "======================================"
        )

        return

    # ROW 19C-3b SLICE 2: eski doğrudan-approve çıktısı bölümü
    # kaldırıldı - yukarıdaki refusal nedeniyle bu noktaya yalnız
    # preview akışı ulaşır ve preview kendi `return`'üyle biter.
    # Gerçek mutasyon yolu: python -m ui.cli_mutate promotion.


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    main()