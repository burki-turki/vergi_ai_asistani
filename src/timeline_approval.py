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

# ROW 19C-3b SLICE 2: yalnız karar içermeyen paylaşılan path primitive'i
# (Row 19C-3a Slice 1) - audit dosya adlarının segment doğrulaması ve
# exact-parent membership'li create-chain çözümü için.
import path_containment


# ============================================================
# VERSION
# ============================================================

TIMELINE_APPROVAL_VERSION = "1"


# ============================================================
# ROW 19C-3b SLICE 2 - PROMOTION FACADE SURFACE (additive).
#
# Bu modülün bugüne kadar HİÇBİR modül-seviyesi kökü yoktu (her yol
# `--pending` argümanından türetiliyordu - sıfır containment). Aşağıdaki
# sabitler timeline_engine.py'nin (Row 7, LOCKED) kendi türetiminin
# (src/timeline_engine.py:111-126) birebir aynasıdır. `CASES_DIR`
# promotion facade/adapter'larının writer-containment seam'idir: HER
# ÇAĞRIDA dinamik okunur, asla cache'lenmez - test redirect sweep'leri
# (`_module.CASES_DIR = tmp`) aynen çalışır.
#
# `CURRENT_PENDING_FILENAME`, timeline_engine.run_timeline_engine()
# çıktısının GÜNCEL sabit adına PİNLİDİR
# (src/timeline_engine.py:1370: "timeline_v1_1.json.pending").
# Bilinçli olarak glob YOK - eski `timeline_v1.json.pending` gibi
# tarihsel adlar bu yoldan ÇÖZÜLMEZ (Row 18a itirazının onaylı mirası).
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

CURRENT_PENDING_FILENAME = "timeline_v1_1.json.pending"

CANONICAL_FILENAME = "timeline.json"


def get_timeline_dir(case_id):
    """RAW candidate üretimi (güvenlik doğrulaması DEĞİL) - çağıran
    (promotion facade/adapter) bu ham yolu kendi bağımsız
    containment doğrulamasından geçirmek ZORUNDADIR."""
    return CASES_DIR / case_id / "timeline"


def get_pending_path(case_id):
    return get_timeline_dir(case_id) / CURRENT_PENDING_FILENAME


def get_canonical_path(case_id):
    return get_timeline_dir(case_id) / CANONICAL_FILENAME


def get_history_dir(case_id):
    return get_timeline_dir(case_id) / "history"


def get_reviews_dir(case_id):
    return get_timeline_dir(case_id) / "reviews"


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


# ============================================================
# ROW 19C-3b SLICE 2 - TEK SERİALİZATION KAYNAĞI.
#
# `_canonical_json_bytes()` hem gerçek canonical writer'ın
# (`atomic_write_json`) hem `compute_expected_canonical_sha256()`'nın
# kullandığı TEK bayt üreticisidir. Bayt-uyumluluk: eski text-mode
# gövde yapısal "\n"ları os.linesep'e çeviriyordu (Windows'ta CRLF);
# `json.dumps` string değerlerindeki newline'ları zaten "\\n" olarak
# escape ettiği için aşağıdaki `.replace` eski çıktıyla BAYT-BAYT aynı
# sonucu üretir (izole testte golden-bytes karşılaştırmasıyla
# kanıtlanır). Deterministiktir: timestamp/random/audit-metadata
# İÇERMEZ, dosya sistemine YAZMAZ.
# ============================================================

def _canonical_json_text(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    )


def _canonical_json_bytes(data):
    return _canonical_json_text(data).replace("\n", os.linesep).encode("utf-8")


def compute_expected_canonical_sha256(pending_path):
    """ROW 19C-3b SLICE 2: pending içeriğinden, gerçek canonical
    writer'ın üreteceği baytların DETERMİNİSTİK beklenen sha256'sı.
    Saf okuma - hiçbir şey yazmaz. Timeline'ın canonical'ı pending
    timeline nesnesinin KENDİSİDİR (approve_pending, review'daki
    nesneyi verbatim yazar) - dönüşüm kimliktir, serileştirme
    `atomic_write_json` ile AYNI `_canonical_json_bytes` kaynağından
    gelir."""
    timeline = load_json(pending_path)
    return hashlib.sha256(
        _canonical_json_bytes(timeline)
    ).hexdigest()


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

    # ROW 19C-3b SLICE 2: aynı serileştirme, artık tek kaynaktan ve
    # binary modda (bkz. yukarıdaki blok yorumu - çıktı baytları eski
    # text-mode gövdeyle birebir aynıdır). flush+fsync korunur.
    with open(
        temp_path,
        "wb",
    ) as file:

        file.write(
            _canonical_json_bytes(data)
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
    *,
    canonical_sha256=None,
    mutation_idempotency_key=None,
    mutation_resource_key=None,
    mutation_actor_ref=None,
):
    # ROW 19C-3b SLICE 2: dört additive, keyword-only alan. `canonical_
    # sha256` yalnız SUCCESS audit'inde dolu gelir (rollback audit'i
    # post-state kanıtı TAŞIMAZ ve success evidence olarak asla kabul
    # edilmez); üç mutation-binding alanı HEM success HEM rollback
    # audit'ine akar. `None` iken alan HİÇ yazılmaz - eski kayıt şekli
    # bayt-uyumlu korunur.

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

    record = {
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

    if canonical_sha256 is not None:
        record["canonical_sha256"] = canonical_sha256
    if mutation_idempotency_key is not None:
        record["mutation_idempotency_key"] = mutation_idempotency_key
    if mutation_resource_key is not None:
        record["mutation_resource_key"] = mutation_resource_key
    if mutation_actor_ref is not None:
        record["mutation_actor_ref"] = mutation_actor_ref

    return record


def write_audit_record(
    pending_path,
    audit_record,
    *,
    reviews_dir=None,
):
    # ROW 19C-3b SLICE 2: `reviews_dir` additive keyword-only override -
    # promotion facade'i kilit-altı DOĞRULANMIŞ dizini geçirir; `None`
    # (legacy) eski pending-kardeş türetimini korur. Yazım artık her iki
    # modda da: ad `path_containment.validate_segment()`'ten geçer,
    # `resolve_for_create()` exact-parent membership'i korur ve
    # `O_CREAT|O_EXCL` + sayısal sonek aynı-saniye çakışmasında sessiz
    # üzerine-yazmayı İMKÂNSIZ kılar (eski `write_json` non-atomic yolu
    # audit için kullanılmaz).

    if reviews_dir is None:

        reviews_dir = (
            reviews_dir_from_pending(
                pending_path
            )
        )

    reviews_dir = Path(
        reviews_dir
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

    base = (
        timeline_id
        + "_"
        + timestamp_for_filename()
    )

    suffix = 0

    while True:

        if suffix == 0:
            filename = base + ".approval.json"
        else:
            filename = base + f"_{suffix}.approval.json"

        path_containment.validate_segment(filename)

        audit_path = path_containment.resolve_for_create(
            reviews_dir,
            filename,
        )

        try:
            fd = os.open(
                audit_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            suffix += 1
            if suffix > 1000:
                raise RuntimeError(
                    "Timeline audit dosya adı için 1000 denemede boş ad bulunamadı."
                )
            continue

        with os.fdopen(fd, "wb") as file:
            file.write(
                _canonical_json_bytes(audit_record)
            )

        return audit_path


# ============================================================
# ROW 19C-3b SLICE 2 - VERIFIED-PATH TOPOLOJİ KONTROLÜ
# ============================================================

_VERIFIED_PATHS_KEYS = frozenset(
    {"timeline_dir", "pending_path", "canonical_path", "history_dir", "reviews_dir"}
)


def _check_verified_paths_topology(pending_path, timeline, verified_paths):
    """`verified_paths` (promotion facade'in kilit ALTINDA doğruladığı
    Path paketi) verildiğinde: TÜM filesystem I/O bu değerlerden yürür;
    doğrulanmış pending'in KARDEŞ türetimleri (canonical/history/
    reviews) canlı-escape/broken/looping link olabileceği için kardeş
    türetim TEK BAŞINA asla yeterli sayılmaz. Bu fonksiyon yazımdan
    ÖNCE, saf Path karşılaştırmalarıyla paketin kendi içinde VE pending
    İÇERİĞİYLE tutarlı olduğunu fail-closed doğrular; raw
    `*_from_pending()` türetimleri verified modda yalnız burada,
    topoloji çapraz-kontrolü olarak kullanılır - I/O için asla."""

    if set(verified_paths.keys()) != _VERIFIED_PATHS_KEYS:
        raise ValueError(
            "verified_paths anahtar seti tam olarak "
            f"{sorted(_VERIFIED_PATHS_KEYS)} olmalıdır."
        )

    timeline_dir = Path(verified_paths["timeline_dir"])
    vp_pending = Path(verified_paths["pending_path"])
    canonical_path = Path(verified_paths["canonical_path"])
    history_dir = Path(verified_paths["history_dir"])
    reviews_dir = Path(verified_paths["reviews_dir"])

    # YAPISAL kontrol seti (bilinçli): parent-eşitlikleri + LEAF ad
    # pinleri. Container/ata dizinlerin LİTERAL adları kontrol edilmez -
    # güvenli bir case-İÇİ alias/junction'ın çözülmüş gerçek hedefi
    # farklı ada sahip olabilir ve bu meşrudur (facade'in containment
    # zinciri konum otoritesidir; case_id içerik bağlaması facade'in
    # kendi çapraz-kontrolünde ayrıca yapılır). Leaf pinleri korunur:
    # kendisi bir link olan pending/canonical fail-closed reddedilir.
    failures = []
    if vp_pending != Path(pending_path):
        failures.append("pending_path argümanı ile verified_paths['pending_path'] farklı")
    if vp_pending.parent != timeline_dir:
        failures.append("pending, timeline_dir'in doğrudan çocuğu değil")
    if vp_pending.name != CURRENT_PENDING_FILENAME:
        failures.append("pending leaf adı pinli engine adıyla eşleşmiyor")
    if canonical_path.parent != timeline_dir or canonical_path.name != CANONICAL_FILENAME:
        failures.append("canonical_path topolojisi beklenen değil")
    if history_dir.parent != timeline_dir:
        failures.append("history_dir, timeline_dir'in doğrudan çocuğu değil")
    if reviews_dir.parent != timeline_dir:
        failures.append("reviews_dir, timeline_dir'in doğrudan çocuğu değil")
    if timeline.get("case_id") in (None, ""):
        failures.append("pending timeline case_id taşımıyor")

    if failures:
        raise ValueError(
            "verified_paths topoloji/içerik çapraz-kontrolü başarısız "
            "(hiçbir yazım yapılmadı): " + "; ".join(failures)
        )

    return {
        "timeline_dir": timeline_dir,
        "canonical_path": canonical_path,
        "history_dir": history_dir,
        "reviews_dir": reviews_dir,
    }


# ============================================================
# PROMOTION
# ============================================================

def approve_pending(
    pending_path,
    *,
    verified_paths=None,
    mutation_idempotency_key=None,
    mutation_resource_key=None,
    mutation_actor_ref=None,
):
    # ROW 19C-3b SLICE 2: dört additive, keyword-only parametre.
    # `verified_paths=None` -> eski davranış (pending-kardeş türetimi)
    # AYNEN korunur. verified_paths verildiğinde tüm stat/hash/copy/
    # write/rollback/audit I/O'su kilit-altı doğrulanmış bu Path'lerden
    # yürür (bkz. _check_verified_paths_topology docstring'i).

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

    timeline = review[
        "timeline"
    ]

    if verified_paths is None:

        canonical_path = review[
            "canonical_path"
        ]

        history_dir = (
            history_dir_from_pending(
                pending_path
            )
        )

        audit_reviews_dir = None

    else:

        checked = _check_verified_paths_topology(
            pending_path,
            timeline,
            verified_paths,
        )

        canonical_path = checked["canonical_path"]
        history_dir = checked["history_dir"]
        audit_reviews_dir = checked["reviews_dir"]

        # Audit dosya adının değişken parçası (timeline_id) pending
        # İÇERİĞİNDEN gelir - herhangi bir yazımdan ÖNCE fail-closed
        # doğrulanır ki audit adımı yazım-sonrası sürprizle patlamasın.
        path_containment.validate_segment(
            (timeline.get("timeline_id") or "timeline")
        )

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

                # ROW 19C-3b SLICE 2: mutation-binding alanları rollback
                # audit'ine DE akar (reconciliation adapter'ı rollback
                # izini bu attempt'e bağlayabilsin diye); canonical_
                # sha256 rollback'te BİLİNÇLİ olarak yazılmaz - rollback
                # audit'i asla success evidence değildir.
                mutation_idempotency_key=mutation_idempotency_key,
                mutation_resource_key=mutation_resource_key,
                mutation_actor_ref=mutation_actor_ref,
            )
        )

        write_audit_record(
            pending_path,
            rollback_audit,
            reviews_dir=audit_reviews_dir,
        )

        raise

    # ========================================================
    # AUDIT
    # ========================================================

    # ROW 19C-3b SLICE 2: canonical hash artık audit YAZILMADAN ÖNCE
    # hesaplanır ve success audit'inin kendisine (`canonical_sha256`)
    # yazılır - audit kaydı post-state kanıtını bağımsız taşır (Row
    # 19C-3b Slice 2 reconciliation kontratının timeline çözümü).
    canonical_hash = (
        file_sha256(
            canonical_path
        )
    )

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

            canonical_sha256=canonical_hash,
            mutation_idempotency_key=mutation_idempotency_key,
            mutation_resource_key=mutation_resource_key,
            mutation_actor_ref=mutation_actor_ref,
        )
    )

    audit_path = (
        write_audit_record(
            pending_path,
            audit_record,
            reviews_dir=audit_reviews_dir,
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

    if args.approve:

        # ROW 19C-3b SLICE 2: bu doğrudan CLI mutasyon yolu KAPALIDIR -
        # coordinator/journal/authz entegrasyonu yalnız ui.cli_mutate
        # promotion üzerindedir. approve_pending() KENDİSİ dokunulmamış
        # writer olarak kalır - yalnız BU executable giriş noktası
        # reddedilir. Refusal, pending okuması/validator çağrısından
        # ÖNCE gelir (stdout boş kalır); SystemExit(2) gerçek process
        # exit code'u 2 üretir.
        print(
            "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3b).\n"
            "Gerçek onay için: python -m ui.cli_mutate promotion --row-key timeline ...",
            file=sys.stderr,
        )
        raise SystemExit(2)

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

    # ROW 19C-3b SLICE 2: eski doğrudan-approve çıktısı bölümü
    # kaldırıldı - yukarıdaki refusal nedeniyle bu noktaya yalnız
    # preview akışı ulaşır ve preview kendi `return`'üyle biter.
    # Gerçek mutasyon yolu: python -m ui.cli_mutate promotion.


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()