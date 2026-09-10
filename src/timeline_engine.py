# ============================================================
# VERGİ AI - TIMELINE ENGINE V1.1
#
# AMAÇ:
#
# Canonical Fact Repository içindeki tarih taşıyan fact'leri
# deterministik timeline event'lerine dönüştürmek ve
# Timeline Consolidation Policy V1 ile aynı olaya ilişkin
# tekrarları güvenli biçimde birleştirmek.
#
#
# INPUT
# -----
#
# Canonical:
#
#   data/cases/<case_id>/documents/
#       */extractions/facts.json
#
#
# OUTPUT
# ------
#
#   data/cases/<case_id>/timeline/
#       timeline_v1_1.json.pending
#
#
# PIPELINE
# --------
#
# Canonical Facts
#      ↓
# Structured Date Discovery
#      ↓
# Raw Timeline Candidates
#      ↓
# Timeline Consolidation Policy V1
#      ↓
# Consolidated Timeline Events
#      ↓
# Verification Propagation
#      ↓
# Deadline-Relevance Marking
#      ↓
# Chronological Sort
#      ↓
# Timeline Validator V1
#      ↓
# Pending Timeline
#
#
# TEMEL PRENSİPLER
# ----------------
#
# 1. Yeni tarih üretilmez.
#
# 2. Yalnız canonical fact'lerde bulunan structured date
#    değerleri kullanılabilir.
#
# 3. Aynı olay farklı belgelerde tekrar edilmişse kaynaklar
#    korunarak tek timeline event oluşturulur.
#
# 4. Aynı tarihte gerçekleşen farklı olaylar sırf tarihleri
#    aynı diye birleştirilmez.
#
# 5. Verification seviyesi yükseltilmez.
#
# 6. "Dava Tarihi" tek başına filing_date değildir.
#
# 7. Timeline Engine hukuki süre HESAPLAMAZ.
#
# 8. deadline_relevant=True yalnız Deadline Engine'in
#    incelemesi gereken event anlamına gelir.
# ============================================================


import hashlib
import json
import os
import re
import shutil
import sys

from datetime import datetime
from pathlib import Path


from timeline_validator import (
    load_canonical_fact_index,
    load_document_index,
    validate_timeline,
)

from timeline_consolidation_policy import (
    TIMELINE_CONSOLIDATION_POLICY_VERSION,
    consolidate_candidates,
    normalize_text_tr,
)

import path_containment


# ============================================================
# VERSION
# ============================================================

TIMELINE_ENGINE_VERSION = "1.1"

TIMELINE_POLICY_VERSION = "1.1"


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

DEFAULT_CASE_ID = "case_0001"

CANONICAL_PENDING_FILENAME = "timeline_v1_1.json.pending"


# ============================================================
# ROW 19C-3c-i - GENERATION MUTATION BINDING
# ============================================================

GENERATION_ACTION_FAMILY = "generation.timeline"

GENERATION_AUDIT_SCHEMA_VERSION = "1"


class TimelineEngineError(Exception):
    pass


def get_case_timeline_dir(case_id):

    return CASES_DIR / case_id / "timeline"


def get_pending_path(case_id):

    return get_case_timeline_dir(case_id) / CANONICAL_PENDING_FILENAME


def get_history_dir(case_id):

    return get_case_timeline_dir(case_id) / "history"


def get_reviews_dir(case_id):

    return get_case_timeline_dir(case_id) / "generation_reviews"


def get_target_ref():
    """Timeline generation case-scopludur (deadline'ın aksine anchor-bazlı
    DEĞİLDİR) - tek bir case için tek bir operasyon slotu."""

    return "timeline.pending"


# ============================================================
# DEADLINE RELEVANT TYPES
# ============================================================

DEADLINE_RELEVANT_TYPES = {
    "notification_date",
    "filing_date",
    "administrative_application_date",
    "administrative_decision_date",
    "court_decision_date",
    "appeal_date",
}


# ============================================================
# FILING SUPPORT PHRASES
# ============================================================

EXPLICIT_FILING_PHRASES = (
    "mahkemeye sunulmustur",
    "mahkemeye sunuldu",
    "mahkemeye verilmistir",
    "mahkemeye verildi",
    "dava acilmistir",
    "dava acildi",
    "tevdi edilmistir",
    "esas kaydina alinmistir",
)


# ============================================================
# HELPERS
# ============================================================

def unique_strings(
    values,
):

    result = []

    for value in values:

        if (
            isinstance(
                value,
                str,
            )
            and value
            and value not in result
        ):

            result.append(
                value
            )

    return result


# ============================================================
# STRUCTURED DATE DISCOVERY
# ============================================================

def extract_structured_dates(
    fact,
):

    results = []

    for value in fact.get(
        "structured_values",
        [],
    ):

        if not isinstance(
            value,
            dict,
        ):

            continue

        if (
            value.get(
                "value_type"
            )
            != "date"
        ):

            continue

        date_value = (
            value.get(
                "date_value"
            )
        )

        if not date_value:

            continue

        results.append(
            {
                "date":
                    date_value,

                "label":
                    value.get(
                        "label"
                    ),
            }
        )

    return results


# ============================================================
# DOCUMENT TYPE
# ============================================================

def get_document_type(
    document_index,
    document_id,
):

    record = document_index.get(
        document_id
    )

    if not record:

        return None

    return (
        record.get(
            "data",
            {}
        ).get(
            "document_type"
        )
    )


def get_document_category(
    document_index,
    document_id,
):

    record = document_index.get(
        document_id
    )

    if not record:

        return None

    return (
        record.get(
            "data",
            {}
        ).get(
            "document_category"
        )
    )


# ============================================================
# EXPLICIT FILING SUPPORT
# ============================================================

def has_explicit_filing_support(
    fact,
):

    source = fact.get(
        "source",
        {},
    )

    if not isinstance(
        source,
        dict,
    ):

        source = {}

    combined = " ".join(
        [
            str(
                fact.get(
                    "statement",
                    ""
                )
            ),

            str(
                source.get(
                    "text_excerpt",
                    ""
                )
            ),
        ]
    )

    normalized = normalize_text_tr(
        combined
    )

    return any(
        phrase in normalized
        for phrase in EXPLICIT_FILING_PHRASES
    )


# ============================================================
# RAW EVENT CLASSIFICATION
# ============================================================

def classify_event_type(
    fact,
    date_label,
    document_type,
    document_category,
):

    statement = normalize_text_tr(
        fact.get(
            "statement"
        )
    )

    label = normalize_text_tr(
        date_label
    )

    document_type_normalized = (
        normalize_text_tr(
            document_type
        )
    )

    document_category_normalized = (
        normalize_text_tr(
            document_category
        )
    )

    combined = (
        label
        + " "
        + statement
    )


    # ========================================================
    # NOTIFICATION DATE
    # ========================================================

    if (
        "teblig"
        in combined
        or "notification"
        in combined
    ):

        return "notification_date"


    # ========================================================
    # COURT DECISION
    # ========================================================

    if (
        "mahkeme karari"
        in combined
        or "court decision"
        in combined
    ):

        return "court_decision_date"


    # ========================================================
    # ADMINISTRATIVE DECISION
    # ========================================================

    if (
        "idari karar"
        in combined
        or "administrative decision"
        in combined
    ):

        return "administrative_decision_date"


    # ========================================================
    # ADMINISTRATIVE APPLICATION
    # ========================================================

    if (
        "basvuru tarihi"
        in combined
        or "idari basvuru"
        in combined
    ):

        return "administrative_application_date"


    # ========================================================
    # APPEAL
    # ========================================================

    if (
        (
            "istinaf"
            in combined
            or "temyiz"
            in combined
            or "appeal"
            in combined
        )
        and "tarih"
        in combined
    ):

        return "appeal_date"


    # ========================================================
    # FILING DATE
    #
    # "Dava Tarihi" yeterli değildir.
    #
    # Kaynakta mahkemeye sunma / dava açma gibi açık
    # filing olayı bulunmalıdır.
    # ========================================================

    if (
        document_type_normalized
        in {
            "dava_dilekcesi",
            "cevap_dilekcesi",
            "istinaf_dilekcesi",
            "temyiz_dilekcesi",
        }
        and has_explicit_filing_support(
            fact
        )
    ):

        return "filing_date"


    # ========================================================
    # REPORT DATE
    # ========================================================

    if (
        "vergi inceleme raporu tarihi"
        in combined
        or "rapor tarihi"
        in combined
    ):

        return "report_date"

    if (
        document_type_normalized
        == "vergi_inceleme_raporu"
        and (
            "tarih"
            in combined
            or "rapor"
            in combined
        )
    ):

        return "report_date"


    # ========================================================
    # ASSESSMENT DATE
    # ========================================================

    if (
        "tarh tarihi"
        in combined
        or "assessment date"
        in combined
    ):

        return "assessment_date"


    # ========================================================
    # PENALTY DATE
    # ========================================================

    if (
        "ceza tarihi"
        in combined
        or "penalty date"
        in combined
    ):

        return "penalty_date"


    # ========================================================
    # PAYMENT DATE
    # ========================================================

    if (
        "odeme tarihi"
        in combined
        or "payment date"
        in combined
    ):

        return "payment_date"


    # ========================================================
    # DOCUMENT DATE
    # ========================================================

    if (
        "duzenleme tarihi"
        in combined
        or "belge tarihi"
        in combined
        or "dava tarihi"
        in combined
        or "ihbarname tarihi"
        in combined
    ):

        return "document_date"


    # ========================================================
    # SAFE FALLBACK
    # ========================================================

    if document_category_normalized:

        return "document_date"

    return "other"


# ============================================================
# DATE PRECISION
# ============================================================

def determine_date_precision(
    date_value,
):

    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}",
        str(
            date_value
        ),
    ):

        return "exact"

    return "unknown"


# ============================================================
# VERIFICATION PROPAGATION
# ============================================================

def propagate_verification_state(
    fact,
):

    allowed = {
        "unverified",
        "partially_verified",
        "verified",
        "disputed",
        "rejected",
    }

    state = fact.get(
        "verification_state"
    )

    if state in allowed:

        return state

    return "unverified"


# ============================================================
# CONFIDENCE PROPAGATION
# ============================================================

def propagate_confidence(
    fact,
):

    value = fact.get(
        "confidence"
    )

    try:

        number = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return 0.5

    return max(
        0.0,
        min(
            number,
            1.0,
        ),
    )


# ============================================================
# EVENT STATEMENT
# ============================================================

def build_event_statement(
    fact,
):

    statement = fact.get(
        "statement"
    )

    if (
        isinstance(
            statement,
            str,
        )
        and statement.strip()
    ):

        return statement.strip()

    return (
        "Canonical fact'ten oluşturulmuş timeline olayı."
    )


# ============================================================
# EVENT NOTES
# ============================================================

def build_event_notes(
    fact,
    date_label,
    event_type,
):

    notes = []

    if date_label:

        notes.append(
            f"Structured date label: {date_label}."
        )

    fact_note = fact.get(
        "notes"
    )

    if (
        isinstance(
            fact_note,
            str,
        )
        and fact_note.strip()
    ):

        notes.append(
            fact_note.strip()
        )

    if (
        event_type
        == "document_date"
        and "dava tarihi"
        in normalize_text_tr(
            date_label
        )
    ):

        notes.append(
            "Bu tarih yalnız dava dilekçesinde belirtilen "
            "dava tarihidir; filing_date olarak "
            "yorumlanmamıştır."
        )

    if not notes:

        return None

    return " ".join(
        notes
    )


# ============================================================
# RAW EVENT CANDIDATES
# ============================================================

def build_raw_event_candidates(
    case_id,
    *,
    document_paths=None,
    facts_paths=None,
):

    canonical = (
        load_canonical_fact_index(
            case_id,
            facts_paths=facts_paths,
        )
    )

    fact_index = canonical[
        "facts"
    ]

    document_index = (
        load_document_index(
            case_id,
            document_paths=document_paths,
        )
    )

    candidates = []

    for (
        fact_id,
        record,
    ) in fact_index.items():

        fact = record[
            "fact"
        ]

        source_document_id = (
            record[
                "source_document_id"
            ]
        )

        structured_dates = (
            extract_structured_dates(
                fact
            )
        )

        if not structured_dates:

            continue

        document_type = (
            get_document_type(
                document_index,
                source_document_id,
            )
        )

        document_category = (
            get_document_category(
                document_index,
                source_document_id,
            )
        )

        for date_record in structured_dates:

            date_value = (
                date_record[
                    "date"
                ]
            )

            date_label = (
                date_record[
                    "label"
                ]
            )

            event_type = (
                classify_event_type(
                    fact=
                        fact,

                    date_label=
                        date_label,

                    document_type=
                        document_type,

                    document_category=
                        document_category,
                )
            )

            related_party_ids = (
                unique_strings(
                    fact.get(
                        "related_party_ids",
                        [],
                    )
                )
            )

            attributed_party_id = (
                fact.get(
                    "attributed_party_id"
                )
            )

            if (
                attributed_party_id
                and attributed_party_id
                not in related_party_ids
            ):

                related_party_ids.append(
                    attributed_party_id
                )

            candidates.append(
                {
                    "date":
                        date_value,

                    "event_type":
                        event_type,

                    "date_precision":
                        determine_date_precision(
                            date_value
                        ),

                    "statement":
                        build_event_statement(
                            fact
                        ),

                    "source_fact_ids": [
                        fact_id
                    ],

                    "source_document_ids": [
                        source_document_id
                    ],

                    "related_party_ids":
                        related_party_ids,

                    "related_dispute_item_ids":
                        unique_strings(
                            fact.get(
                                "related_dispute_item_ids",
                                [],
                            )
                        ),

                    "verification_state":
                        propagate_verification_state(
                            fact
                        ),

                    "confidence":
                        propagate_confidence(
                            fact
                        ),

                    "deadline_relevant":
                        event_type
                        in DEADLINE_RELEVANT_TYPES,

                    "notes":
                        build_event_notes(
                            fact,
                            date_label,
                            event_type,
                        ),

                    # -----------------------------------------
                    # INTERNAL FIELDS
                    #
                    # Consolidation Policy kullanır.
                    # Final schema'ya yazılmaz.
                    # -----------------------------------------

                    "_fact_id":
                        fact_id,

                    "_date_label":
                        date_label,
                }
            )

    return (
        candidates,
        fact_index,
        document_index,
    )


# ============================================================
# ASSIGN FINAL EVENT IDS
# ============================================================

def build_final_events(
    consolidated_candidates,
):

    events = []

    for index, candidate in enumerate(
        consolidated_candidates,
        start=1,
    ):

        event = {
            "event_id":
                f"timeline_event_{index:03d}",

            "event_type":
                candidate[
                    "event_type"
                ],

            "date":
                candidate[
                    "date"
                ],

            "date_precision":
                candidate[
                    "date_precision"
                ],

            "statement":
                candidate[
                    "statement"
                ],

            "source_fact_ids":
                candidate[
                    "source_fact_ids"
                ],

            "source_document_ids":
                candidate[
                    "source_document_ids"
                ],

            "related_party_ids":
                candidate[
                    "related_party_ids"
                ],

            "related_dispute_item_ids":
                candidate[
                    "related_dispute_item_ids"
                ],

            "verification_state":
                candidate[
                    "verification_state"
                ],

            "confidence":
                candidate[
                    "confidence"
                ],

            "deadline_relevant":
                candidate[
                    "deadline_relevant"
                ],

            "notes":
                candidate[
                    "notes"
                ],
        }

        events.append(
            event
        )

    return events


# ============================================================
# ENGINE WARNINGS
# ============================================================

def build_engine_warnings(
    events,
):

    warnings = []

    for event in events:

        if (
            event.get(
                "deadline_relevant"
            )
            is True
            and event.get(
                "verification_state"
            )
            != "verified"
        ):

            warnings.append(
                (
                    f"{event['event_id']}: "
                    f"{event['event_type']} "
                    f"{event['date']} deadline açısından "
                    "potansiyel olarak önemlidir ancak "
                    f"verification_state="
                    f"'{event['verification_state']}'."
                )
            )

        if (
            event.get(
                "event_type"
            )
            == "document_date"
            and "dava tarihi"
            in normalize_text_tr(
                event.get(
                    "statement"
                )
            )
        ):

            warnings.append(
                (
                    f"{event['event_id']}: "
                    "Dava dilekçesinde belirtilen tarih "
                    "filing_date olarak yorumlanmamıştır."
                )
            )

    return unique_strings(
        warnings
    )


# ============================================================
# BUILD TIMELINE
# ============================================================

def build_timeline(
    case_id,
    *,
    document_paths=None,
    facts_paths=None,
):

    (
        raw_candidates,
        fact_index,
        document_index,
    ) = (
        build_raw_event_candidates(
            case_id,
            document_paths=document_paths,
            facts_paths=facts_paths,
        )
    )

    consolidated_candidates = (
        consolidate_candidates(
            candidates=
                raw_candidates,

            fact_index=
                fact_index,

            document_index=
                document_index,
        )
    )

    events = (
        build_final_events(
            consolidated_candidates
        )
    )

    warnings = (
        build_engine_warnings(
            events
        )
    )

    status = (
        "completed"
        if events
        else "failed"
    )

    timeline = {
        "schema_version":
            1,

        "timeline_id":
            f"timeline_{case_id}_v1_1",

        "case_id":
            case_id,

        "status":
            status,

        "generated_at":
            datetime.now()
            .astimezone()
            .isoformat(),

        "events":
            events,

        "warnings":
            warnings,

        "notes":
            (
                "Timeline Engine V1.1 tarafından yalnız "
                "canonical Fact Repository içindeki structured "
                "date değerlerinden deterministik olarak "
                "oluşturulmuştur. Aynı timeline olayını "
                "destekleyen canonical fact'ler Timeline "
                "Consolidation Policy V1 ile kaynakları "
                "korunarak birleştirilmiştir. Hukuki süre "
                "hesabı yapılmamıştır."
            ),
    }

    return {
        "timeline":
            timeline,

        "raw_candidate_count":
            len(
                raw_candidates
            ),

        "consolidated_candidate_count":
            len(
                consolidated_candidates
            ),

        "fact_count":
            len(
                fact_index
            ),

        "document_count":
            len(
                document_index
            ),
    }


# ============================================================
# WRITE JSON (ATOMIC)
#
# ROW 19C-3c-i: eski `write_json()` (plain `open()` + `json.dump`,
# ne atomic write ne history ne rollback) kaldırıldı - bu, coordinator
# entegrasyonundan BAĞIMSIZ, önceden var olan bir güvenlik açığıydı
# (bkz. CLAUDE.md Prensip 9/13, Row 19C-3c-i final scope raporu).
# `deadline_engine.atomic_write_json()` ile AYNI desen - iki modül
# arasında kasıtlı, bilinçli duplikasyon (repo konvansiyonu, bkz.
# CASES_DIR'in her modülde ayrı tanımlanması).
# ============================================================

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


def now_stamp():

    return (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
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

    timestamp = now_stamp()

    history_path = (
        history_dir
        / (
            "timeline_pending_before_engine_"
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
# GENERATION AUDIT RECORD (ROW 19C-3c-i)
#
# `fact_approval._write_audit_record_excl()` ile AYNI desen: zaman
# damgalı taban ad + `O_CREAT|O_EXCL` + sayısal sonek - sabit adın
# ÜZERİNE YAZMA sınıfı kapatılır; replay/reconciliation eşleşmesi HER
# ZAMAN içerikten yapılır, addan asla.
# ============================================================

def _write_generation_audit_record_excl(
    reviews_dir,
    audit_record,
):

    reviews_dir = Path(reviews_dir)
    reviews_dir.mkdir(parents=True, exist_ok=True)

    base = f"timeline_{now_stamp()}"

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
# WRITE PENDING (ATOMIC + HISTORY + ROLLBACK + AUDIT)
# ============================================================

def write_pending(
    case_id,
    timeline,
    *,
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
            input_digest is None
            or mutation_resource_key is None
            or mutation_actor_ref is None
        ):

            raise TimelineEngineError(
                "mutation_idempotency_key verildiğinde input_digest/"
                "mutation_resource_key/mutation_actor_ref de "
                "verilmelidir (kısmi mutation-binding kabul edilmez)."
            )

    timeline_dir = get_case_timeline_dir(case_id)

    timeline_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pending_path = get_pending_path(case_id)

    previous_pending_history = preserve_previous_pending(
        case_id=case_id,
        pending_path=pending_path,
    )

    try:

        if pre_commit_callback is not None:

            pre_commit_callback()

        atomic_write_json(
            pending_path,
            timeline,
        )

        # ====================================================
        # POST-WRITE TIMELINE VALIDATOR
        # ====================================================

        validation = validate_timeline(
            timeline_path=pending_path,
            expected_case_id=case_id,
            raise_on_error=True,
        )

        if validation.get("valid") is not True:

            raise TimelineEngineError(
                "Post-write Timeline Validator valid=False."
            )

        # ====================================================
        # RELOAD (GERÇEK DİSK BAYTLARINDAN HASH)
        # ====================================================

        pending_raw_bytes = pending_path.read_bytes()

        pending_sha256 = sha256_bytes(pending_raw_bytes)

        written = json.loads(pending_raw_bytes.decode("utf-8"))

        generated_at = written.get("generated_at")

        # ====================================================
        # GENERATION AUDIT RECORD (yalnız coordinator-mode'da)
        # ====================================================

        audit_path = None

        first_write = previous_pending_history is None

        if mutation_binding_provided:

            history_backup_path = None

            history_backup_sha256 = None

            if not first_write:

                history_backup_path = str(previous_pending_history)

                history_backup_sha256 = sha256_bytes(
                    previous_pending_history.read_bytes()
                )

            audit_record = {
                "schema_version": GENERATION_AUDIT_SCHEMA_VERSION,
                "case_id": case_id,
                "target_ref": get_target_ref(),
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
                "generated_at": generated_at,
                "outcome": "generated",
                "written_at": (
                    datetime.now()
                    .astimezone()
                    .isoformat()
                ),
            }

            audit_path = _write_generation_audit_record_excl(
                reviews_dir=get_reviews_dir(case_id),
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

        if (
            previous_pending_history is not None
            and previous_pending_history.exists()
        ):

            shutil.move(
                str(previous_pending_history),
                str(pending_path),
            )

        raise


# ============================================================
# SUMMARY
# ============================================================

def summarize_timeline(
    timeline,
):

    event_types = {}

    verification = {}

    deadline_relevant = 0

    source_fact_support = 0

    source_document_support = 0

    for event in timeline.get(
        "events",
        [],
    ):

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

        state = event.get(
            "verification_state"
        )

        verification[
            state
        ] = (
            verification.get(
                state,
                0,
            )
            + 1
        )

        if event.get(
            "deadline_relevant"
        ):

            deadline_relevant += 1

        source_fact_support += len(
            event.get(
                "source_fact_ids",
                [],
            )
        )

        source_document_support += len(
            event.get(
                "source_document_ids",
                [],
            )
        )

    return {
        "event_count":
            len(
                timeline.get(
                    "events",
                    [],
                )
            ),

        "event_types":
            event_types,

        "verification":
            verification,

        "deadline_relevant":
            deadline_relevant,

        "source_fact_support":
            source_fact_support,

        "source_document_support":
            source_document_support,
    }


# ============================================================
# RUN ENGINE
# ============================================================

def run_timeline_engine(
    case_id,
    *,
    document_paths=None,
    facts_paths=None,
    input_digest=None,
    generation_parameters_digest=None,
    mutation_idempotency_key=None,
    mutation_resource_key=None,
    mutation_actor_ref=None,
    pre_commit_callback=None,
):

    case_dir = (
        CASES_DIR
        / case_id
    )

    if not case_dir.exists():

        raise FileNotFoundError(
            f"Case bulunamadı:\n{case_dir}"
        )

    build_result = (
        build_timeline(
            case_id,
            document_paths=document_paths,
            facts_paths=facts_paths,
        )
    )

    timeline = (
        build_result[
            "timeline"
        ]
    )

    write_result = write_pending(
        case_id=case_id,
        timeline=timeline,
        input_digest=input_digest,
        generation_parameters_digest=generation_parameters_digest,
        mutation_idempotency_key=mutation_idempotency_key,
        mutation_resource_key=mutation_resource_key,
        mutation_actor_ref=mutation_actor_ref,
        pre_commit_callback=pre_commit_callback,
    )

    output_path = write_result["pending_path"]

    validation = write_result["validation"]

    summary = (
        summarize_timeline(
            timeline
        )
    )

    return {
        "timeline":
            timeline,

        "output_path":
            output_path,

        "validation":
            validation,

        "summary":
            summary,

        "raw_candidate_count":
            build_result[
                "raw_candidate_count"
            ],

        "consolidated_candidate_count":
            build_result[
                "consolidated_candidate_count"
            ],

        "fact_count":
            build_result[
                "fact_count"
            ],

        "document_count":
            build_result[
                "document_count"
            ],

        "previous_pending_history":
            write_result["previous_pending_history"],

        "audit_path":
            write_result["audit_path"],

        "first_write":
            write_result["first_write"],

        "pending_sha256":
            write_result["pending_sha256"],
    }


# ============================================================
# CLI
#
# ROW 19C-3c-i: bu doğrudan mutasyon CLI yolu DEVRE DIŞI bırakıldı.
# `run_timeline_engine()`'in kendisi DEĞİŞMEDİ ve tam olarak
# fonksiyoneldir - yalnız `ui.services.generation_mutation_facade`
# üzerinden (mutation coordinator/journal altyapısına bağlı olarak)
# çağrılabilir. Bu dosyada önceden var olan koşulsuz mutasyon dışında
# korunması gereken bir preview/self-test dalı YOKTU (bkz. Row 19C-3c-i
# final scope raporu) - bu yüzden kapama argparse'ı hiç kurmadan
# doğrudan reddeder.
# ============================================================

_LEGACY_CLI_REFUSAL_MESSAGE = (
    "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3b).\n"
    "Gerçek üretim için: python -m ui.cli_mutate generation "
    "<preview|apply> --row-key timeline ..."
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

    main()