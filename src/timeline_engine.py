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


import argparse
import json
import re

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
):

    canonical = (
        load_canonical_fact_index(
            case_id
        )
    )

    fact_index = canonical[
        "facts"
    ]

    document_index = (
        load_document_index(
            case_id
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
):

    (
        raw_candidates,
        fact_index,
        document_index,
    ) = (
        build_raw_event_candidates(
            case_id
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
# WRITE JSON
# ============================================================

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
            case_id
        )
    )

    timeline = (
        build_result[
            "timeline"
        ]
    )

    output_path = (
        case_dir
        / "timeline"
        / "timeline_v1_1.json.pending"
    )

    write_json(
        output_path,
        timeline,
    )

    validation = (
        validate_timeline(
            timeline_path=
                output_path,

            expected_case_id=
                case_id,

            raise_on_error=
                True,
        )
    )

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
    }


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Timeline Engine V1.1"
        )
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default=DEFAULT_CASE_ID,
    )

    args = parser.parse_args()

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - TIMELINE ENGINE V1.1"
    )

    print(
        "======================================"
    )

    print()

    print(
        "Timeline oluşturuluyor..."
    )

    print(
        "Engine:",
        TIMELINE_ENGINE_VERSION,
    )

    print(
        "Timeline policy:",
        TIMELINE_POLICY_VERSION,
    )

    print(
        "Consolidation policy:",
        TIMELINE_CONSOLIDATION_POLICY_VERSION,
    )

    print(
        "Case:",
        args.case_id,
    )

    result = (
        run_timeline_engine(
            args.case_id
        )
    )

    timeline = (
        result[
            "timeline"
        ]
    )

    summary = (
        result[
            "summary"
        ]
    )

    validation = (
        result[
            "validation"
        ]
    )

    print()

    print(
        "TIMELINE OLUŞTURULDU"
    )

    print(
        "Timeline ID:",
        timeline[
            "timeline_id"
        ],
    )

    print(
        "Raw candidate:",
        result[
            "raw_candidate_count"
        ],
    )

    print(
        "Consolidated event:",
        result[
            "consolidated_candidate_count"
        ],
    )

    print(
        "Final event:",
        summary[
            "event_count"
        ],
    )

    print(
        "Status:",
        timeline[
            "status"
        ],
    )

    print(
        "Validator:",
        (
            "PASS"
            if validation[
                "valid"
            ]
            else "FAIL"
        ),
    )

    print()

    print(
        "Event types:",
        summary[
            "event_types"
        ],
    )

    print(
        "Verification:",
        summary[
            "verification"
        ],
    )

    print(
        "Deadline relevant:",
        summary[
            "deadline_relevant"
        ],
    )

    print(
        "Canonical fact support:",
        summary[
            "source_fact_support"
        ],
    )

    print()

    print(
        "Chronology:"
    )

    for event in timeline[
        "events"
    ]:

        print()

        print(
            "-",
            event[
                "date"
            ],
            "|",
            event[
                "event_type"
            ],
            "|",
            event[
                "verification_state"
            ],
        )

        print(
            "  Statement:",
            event[
                "statement"
            ],
        )

        print(
            "  Facts:",
            event[
                "source_fact_ids"
            ],
        )

        print(
            "  Documents:",
            event[
                "source_document_ids"
            ],
        )

    print()

    print(
        "Pending output:"
    )

    print(
        result[
            "output_path"
        ]
    )

    if timeline.get(
        "warnings"
    ):

        print()

        print(
            "Engine warnings:"
        )

        for warning in timeline[
            "warnings"
        ]:

            print(
                "-",
                warning,
            )

    if validation.get(
        "warnings"
    ):

        print()

        print(
            "Validator warnings:"
        )

        for warning in validation[
            "warnings"
        ]:

            print(
                "-",
                warning,
            )

    print()

    print(
        "SAFETY CHECKS:"
    )

    print(
        "- Timeline yalnız canonical facts kullanır."
    )

    print(
        "- Multi-source fact desteği consolidation sırasında korunur."
    )

    print(
        "- Verification seviyesi yükseltilmez."
    )

    print(
        "- Dava Tarihi tek başına filing_date değildir."
    )

    print(
        "- Hukuki süre hesabı yapılmaz."
    )

    print()

    print(
        "======================================"
    )

    print(
        " TIMELINE ENGINE V1.1: PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()