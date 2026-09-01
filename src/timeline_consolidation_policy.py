# ============================================================
# VERGİ AI - TIMELINE CONSOLIDATION POLICY V1
#
# AMAÇ:
#
# Farklı canonical fact'lerin aynı gerçek timeline olayını
# tekrar etmesi durumunda bunları deterministik olarak
# tek timeline event adayı altında birleştirmek.
#
#
# ÖRNEK:
#
# Dava dilekçesi:
#   "İhbarname 10.02.2026 tarihinde tebliğ edildi."
#
# İhbarname:
#   "İhbarname 10.02.2026 tarihinde tebliğ edildi."
#
#                    ↓
#
# TEK TIMELINE EVENT
#
# date:
#   2026-02-10
#
# event_type:
#   notification_date
#
# source_fact_ids:
#   [fact_dava_..., fact_ihbarname_...]
#
# source_document_ids:
#   [dava_dilekcesi_001, ihbarname_001]
#
#
# KRİTİK PRENSİPLER:
#
# 1. Kaynak fact'ler kaybolmaz.
#
# 2. Kaynak belgeler kaybolmaz.
#
# 3. Verification seviyesi yükseltilmez.
#
# 4. Aynı tarihte gerçekleşen farklı olaylar sırf tarihleri
#    aynı diye birleştirilmez.
#
# 5. Event identity:
#
#       date
#       + canonical event type
#       + subject document
#
#    üzerinden oluşturulur.
#
# 6. "Dava Tarihi" otomatik filing_date yapılmaz.
#
# 7. Türkçe karakter normalizasyonu deterministiktir.
# ============================================================


import unicodedata

from collections import OrderedDict


# ============================================================
# VERSION
# ============================================================

TIMELINE_CONSOLIDATION_POLICY_VERSION = "1"


# ============================================================
# EVENT TYPES
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
# DATE PRECISION
# ============================================================

DATE_PRECISION_RANK = {
    "exact": 5,
    "month": 4,
    "year": 3,
    "approximate": 2,
    "unknown": 1,
}


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text_tr(
    value,
):

    if value is None:

        return ""

    text = str(
        value
    )

    # --------------------------------------------------------
    # Unicode decomposition:
    #
    # Türkçe "İ" gibi karakterlerin combining mark
    # farklılıklarını ortadan kaldırır.
    # --------------------------------------------------------

    text = unicodedata.normalize(
        "NFKD",
        text,
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(
            character
        )
    )

    text = text.casefold()

    # --------------------------------------------------------
    # Türkçe dotless ı ve diğer karakterler.
    # --------------------------------------------------------

    translation = str.maketrans(
        {
            "ı": "i",
            "ş": "s",
            "ğ": "g",
            "ç": "c",
            "ö": "o",
            "ü": "u",
        }
    )

    text = text.translate(
        translation
    )

    return " ".join(
        text.split()
    )


# ============================================================
# UNIQUE
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
# DOCUMENT HELPERS
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


def document_is_type(
    document_index,
    document_id,
    document_type,
):

    actual = normalize_text_tr(
        get_document_type(
            document_index,
            document_id,
        )
    )

    expected = normalize_text_tr(
        document_type
    )

    return actual == expected


# ============================================================
# FACT RECORD
# ============================================================

def get_candidate_fact_record(
    candidate,
    fact_index,
):

    fact_id = candidate.get(
        "_fact_id"
    )

    if not fact_id:

        source_fact_ids = (
            candidate.get(
                "source_fact_ids",
                []
            )
        )

        if source_fact_ids:

            fact_id = (
                source_fact_ids[
                    0
                ]
            )

    if not fact_id:

        return None

    return fact_index.get(
        fact_id
    )


# ============================================================
# RELATED DOCUMENT IDS
# ============================================================

def get_fact_related_document_ids(
    candidate,
    fact_index,
):

    record = (
        get_candidate_fact_record(
            candidate,
            fact_index,
        )
    )

    if not record:

        return []

    fact = record.get(
        "fact",
        {}
    )

    return unique_strings(
        fact.get(
            "related_document_ids",
            [],
        )
    )


# ============================================================
# SOURCE DOCUMENT ID
# ============================================================

def get_candidate_source_document_id(
    candidate,
    fact_index,
):

    record = (
        get_candidate_fact_record(
            candidate,
            fact_index,
        )
    )

    if record:

        source_document_id = (
            record.get(
                "source_document_id"
            )
        )

        if source_document_id:

            return source_document_id

    source_document_ids = (
        candidate.get(
            "source_document_ids",
            []
        )
    )

    if source_document_ids:

        return source_document_ids[
            0
        ]

    return None


# ============================================================
# FIND DOCUMENT BY TYPE
# ============================================================

def find_document_by_type(
    document_ids,
    document_index,
    document_type,
):

    for document_id in document_ids:

        if document_is_type(
            document_index,
            document_id,
            document_type,
        ):

            return document_id

    return None


# ============================================================
# SUBJECT DOCUMENT RESOLUTION
# ============================================================

def infer_subject_document_id(
    candidate,
    fact_index,
    document_index,
):

    source_document_id = (
        get_candidate_source_document_id(
            candidate,
            fact_index,
        )
    )

    related_document_ids = (
        get_fact_related_document_ids(
            candidate,
            fact_index,
        )
    )

    date_label = normalize_text_tr(
        candidate.get(
            "_date_label"
        )
    )

    statement = normalize_text_tr(
        candidate.get(
            "statement"
        )
    )

    combined = (
        date_label
        + " "
        + statement
    )

    # ========================================================
    # VERGİ İNCELEME RAPORU
    # ========================================================

    if (
        "vergi inceleme raporu"
        in combined
        or "rapor tarihi"
        in date_label
    ):

        if (
            source_document_id
            and document_is_type(
                document_index,
                source_document_id,
                "vergi_inceleme_raporu",
            )
        ):

            return source_document_id

        related_match = (
            find_document_by_type(
                related_document_ids,
                document_index,
                "vergi_inceleme_raporu",
            )
        )

        if related_match:

            return related_match

    # ========================================================
    # İHBARNAME
    # ========================================================

    if (
        "ihbarname"
        in combined
        or "teblig"
        in combined
    ):

        if (
            source_document_id
            and document_is_type(
                document_index,
                source_document_id,
                "vergi_ceza_ihbarnamesi",
            )
        ):

            return source_document_id

        related_match = (
            find_document_by_type(
                related_document_ids,
                document_index,
                "vergi_ceza_ihbarnamesi",
            )
        )

        if related_match:

            return related_match

    # ========================================================
    # DAVA DİLEKÇESİ
    # ========================================================

    if (
        "dava tarihi"
        in combined
    ):

        return source_document_id

    # ========================================================
    # FALLBACK
    #
    # Aynı olayın subject'ini tahmin etmiyoruz.
    # Source document güvenli fallback'tir.
    # ========================================================

    return source_document_id


# ============================================================
# CANONICAL EVENT TYPE
# ============================================================

def canonicalize_event_type(
    candidate,
    fact_index,
    document_index,
):

    current_type = candidate.get(
        "event_type"
    )

    date_label = normalize_text_tr(
        candidate.get(
            "_date_label"
        )
    )

    statement = normalize_text_tr(
        candidate.get(
            "statement"
        )
    )

    combined = (
        date_label
        + " "
        + statement
    )

    # ========================================================
    # NOTIFICATION
    # ========================================================

    if (
        "teblig"
        in combined
    ):

        return "notification_date"

    # ========================================================
    # REPORT
    # ========================================================

    if (
        "vergi inceleme raporu tarihi"
        in date_label
        or "rapor tarihi"
        in date_label
    ):

        return "report_date"

    # ========================================================
    # DAVA TARİHİ
    #
    # Çok önemli:
    #
    # Dava Tarihi
    #     !=
    # filing_date
    # ========================================================

    if (
        "dava tarihi"
        in date_label
    ):

        return "document_date"

    # ========================================================
    # İHBARNAME / BELGE TARİHİ
    # ========================================================

    if (
        "ihbarname tarihi"
        in date_label
        or "duzenleme tarihi"
        in date_label
        or "belge tarihi"
        in date_label
    ):

        return "document_date"

    # ========================================================
    # CURRENT TYPE
    # ========================================================

    return current_type


# ============================================================
# VERIFICATION CONSOLIDATION
# ============================================================

def consolidate_verification_states(
    states,
):

    states = [
        state
        for state in states
        if state
    ]

    if not states:

        return "unverified"

    unique = set(
        states
    )

    if len(
        unique
    ) == 1:

        return states[
            0
        ]

    # --------------------------------------------------------
    # Rejected/disputed kaynak varsa event'i daha güçlü
    # hale getiremeyiz.
    # --------------------------------------------------------

    if (
        "rejected"
        in unique
        or "disputed"
        in unique
    ):

        return "disputed"

    # --------------------------------------------------------
    # Bütün kaynaklar verified ise verified.
    # --------------------------------------------------------

    if unique == {
        "verified"
    }:

        return "verified"

    # --------------------------------------------------------
    # Unverified kaynak varsa verified'a yükseltme yok.
    # --------------------------------------------------------

    if "unverified" in unique:

        return "unverified"

    # --------------------------------------------------------
    # verified + partially_verified
    # --------------------------------------------------------

    if "partially_verified" in unique:

        return "partially_verified"

    return "unverified"


# ============================================================
# DATE PRECISION CONSOLIDATION
# ============================================================

def consolidate_date_precision(
    values,
):

    values = [
        value
        for value in values
        if value
    ]

    if not values:

        return "unknown"

    return min(
        values,
        key=lambda value:
            DATE_PRECISION_RANK.get(
                value,
                0,
            ),
    )


# ============================================================
# CONFIDENCE
# ============================================================

def consolidate_confidence(
    values,
):

    numbers = []

    for value in values:

        try:

            number = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            continue

        numbers.append(
            max(
                0.0,
                min(
                    number,
                    1.0,
                ),
            )
        )

    if not numbers:

        return 0.5

    # --------------------------------------------------------
    # Birden fazla kaynak var diye confidence yapay biçimde
    # yükseltilmez.
    #
    # Conservative minimum kullanıyoruz.
    # --------------------------------------------------------

    return min(
        numbers
    )


# ============================================================
# PRIMARY CANDIDATE
# ============================================================

def choose_primary_candidate(
    candidates,
    subject_document_id,
):

    def score(
        candidate,
    ):

        source_document_ids = (
            candidate.get(
                "source_document_ids",
                []
            )
        )

        source_bonus = (
            10
            if subject_document_id
            in source_document_ids
            else 0
        )

        try:

            confidence = float(
                candidate.get(
                    "confidence",
                    0.0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            confidence = 0.0

        return (
            source_bonus,
            confidence,
        )

    return max(
        candidates,
        key=score,
    )


# ============================================================
# NOTES
# ============================================================

def build_consolidated_notes(
    candidates,
    primary,
):

    notes = []

    primary_note = (
        primary.get(
            "notes"
        )
    )

    if (
        isinstance(
            primary_note,
            str,
        )
        and primary_note.strip()
    ):

        notes.append(
            primary_note.strip()
        )

    if len(
        candidates
    ) > 1:

        notes.append(
            (
                f"{len(candidates)} canonical fact "
                "aynı timeline olayını desteklediği için "
                "Timeline Consolidation Policy V1 "
                "tarafından tek event altında "
                "birleştirilmiştir."
            )
        )

    if not notes:

        return None

    return " ".join(
        notes
    )


# ============================================================
# EVENT IDENTITY
# ============================================================

def build_event_identity(
    candidate,
    fact_index,
    document_index,
):

    canonical_event_type = (
        canonicalize_event_type(
            candidate,
            fact_index,
            document_index,
        )
    )

    subject_document_id = (
        infer_subject_document_id(
            candidate,
            fact_index,
            document_index,
        )
    )

    return (
        candidate.get(
            "date"
        ),
        canonical_event_type,
        subject_document_id,
    )


# ============================================================
# CONSOLIDATE GROUP
# ============================================================

def consolidate_group(
    candidates,
    fact_index,
    document_index,
):

    first = candidates[
        0
    ]

    event_type = (
        canonicalize_event_type(
            first,
            fact_index,
            document_index,
        )
    )

    subject_document_id = (
        infer_subject_document_id(
            first,
            fact_index,
            document_index,
        )
    )

    primary = (
        choose_primary_candidate(
            candidates,
            subject_document_id,
        )
    )

    source_fact_ids = []

    source_document_ids = []

    related_party_ids = []

    related_dispute_item_ids = []

    verification_states = []

    confidences = []

    date_precisions = []

    for candidate in candidates:

        source_fact_ids.extend(
            candidate.get(
                "source_fact_ids",
                [],
            )
        )

        source_document_ids.extend(
            candidate.get(
                "source_document_ids",
                [],
            )
        )

        related_party_ids.extend(
            candidate.get(
                "related_party_ids",
                [],
            )
        )

        related_dispute_item_ids.extend(
            candidate.get(
                "related_dispute_item_ids",
                [],
            )
        )

        verification_states.append(
            candidate.get(
                "verification_state"
            )
        )

        confidences.append(
            candidate.get(
                "confidence"
            )
        )

        date_precisions.append(
            candidate.get(
                "date_precision"
            )
        )

    return {
        "date":
            first.get(
                "date"
            ),

        "event_type":
            event_type,

        "date_precision":
            consolidate_date_precision(
                date_precisions
            ),

        "statement":
            primary.get(
                "statement"
            ),

        "source_fact_ids":
            unique_strings(
                source_fact_ids
            ),

        "source_document_ids":
            unique_strings(
                source_document_ids
            ),

        "related_party_ids":
            unique_strings(
                related_party_ids
            ),

        "related_dispute_item_ids":
            unique_strings(
                related_dispute_item_ids
            ),

        "verification_state":
            consolidate_verification_states(
                verification_states
            ),

        "confidence":
            consolidate_confidence(
                confidences
            ),

        "deadline_relevant":
            event_type
            in DEADLINE_RELEVANT_TYPES,

        "notes":
            build_consolidated_notes(
                candidates,
                primary,
            ),

        "_subject_document_id":
            subject_document_id,

        "_support_count":
            len(
                candidates
            ),
    }


# ============================================================
# CONSOLIDATE
# ============================================================

def consolidate_candidates(
    candidates,
    fact_index,
    document_index,
):

    groups = OrderedDict()

    for candidate in candidates:

        identity = (
            build_event_identity(
                candidate,
                fact_index,
                document_index,
            )
        )

        if identity not in groups:

            groups[
                identity
            ] = []

        groups[
            identity
        ].append(
            candidate
        )

    consolidated = []

    for candidates_in_group in (
        groups.values()
    ):

        consolidated.append(
            consolidate_group(
                candidates_in_group,
                fact_index,
                document_index,
            )
        )

    consolidated.sort(
        key=lambda item:
            (
                item.get(
                    "date"
                )
                or "",

                item.get(
                    "event_type"
                )
                or "",

                item.get(
                    "_subject_document_id"
                )
                or "",
            )
    )

    return consolidated


# ============================================================
# SELF TEST FIXTURES
# ============================================================

def build_test_context():

    document_index = {
        "vir_001": {
            "data": {
                "document_type":
                    "vergi_inceleme_raporu"
            }
        },

        "ihbarname_001": {
            "data": {
                "document_type":
                    "vergi_ceza_ihbarnamesi"
            }
        },

        "dava_dilekcesi_001": {
            "data": {
                "document_type":
                    "dava_dilekcesi"
            }
        },
    }

    fact_index = {
        "f_report_dava": {
            "source_document_id":
                "dava_dilekcesi_001",

            "fact": {
                "related_document_ids": [
                    "vir_001"
                ]
            },
        },

        "f_report_ihbar": {
            "source_document_id":
                "ihbarname_001",

            "fact": {
                "related_document_ids": [
                    "vir_001"
                ]
            },
        },

        "f_report_vir": {
            "source_document_id":
                "vir_001",

            "fact": {
                "related_document_ids":
                    []
            },
        },

        "f_issue_dava": {
            "source_document_id":
                "dava_dilekcesi_001",

            "fact": {
                "related_document_ids": [
                    "ihbarname_001"
                ]
            },
        },

        "f_issue_ihbar": {
            "source_document_id":
                "ihbarname_001",

            "fact": {
                "related_document_ids":
                    []
            },
        },

        "f_notice_dava": {
            "source_document_id":
                "dava_dilekcesi_001",

            "fact": {
                "related_document_ids": [
                    "ihbarname_001"
                ]
            },
        },

        "f_notice_ihbar": {
            "source_document_id":
                "ihbarname_001",

            "fact": {
                "related_document_ids":
                    []
            },
        },

        "f_dava_date": {
            "source_document_id":
                "dava_dilekcesi_001",

            "fact": {
                "related_document_ids":
                    []
            },
        },
    }

    candidates = [
        {
            "date":
                "2026-01-20",

            "event_type":
                "document_date",

            "date_precision":
                "exact",

            "statement":
                (
                    "Davacı, ihbarnamenin "
                    "20.01.2026 tarihli Vergi "
                    "İnceleme Raporuna dayandığını "
                    "beyan etmektedir."
                ),

            "source_fact_ids": [
                "f_report_dava"
            ],

            "source_document_ids": [
                "dava_dilekcesi_001"
            ],

            "related_party_ids":
                [],

            "related_dispute_item_ids":
                [],

            "verification_state":
                "unverified",

            "confidence":
                0.97,

            "deadline_relevant":
                False,

            "notes":
                None,

            "_fact_id":
                "f_report_dava",

            "_date_label":
                "Vergi İnceleme Raporu Tarihi",
        },

        {
            "date":
                "2026-01-20",

            "event_type":
                "document_date",

            "date_precision":
                "exact",

            "statement":
                (
                    "İhbarname 20.01.2026 tarihli "
                    "Vergi İnceleme Raporuna "
                    "dayanmaktadır."
                ),

            "source_fact_ids": [
                "f_report_ihbar"
            ],

            "source_document_ids": [
                "ihbarname_001"
            ],

            "related_party_ids":
                [],

            "related_dispute_item_ids":
                [],

            "verification_state":
                "unverified",

            "confidence":
                0.99,

            "deadline_relevant":
                False,

            "notes":
                None,

            "_fact_id":
                "f_report_ihbar",

            "_date_label":
                "Vergi İnceleme Raporu Tarihi",
        },

        {
            "date":
                "2026-01-20",

            "event_type":
                "report_date",

            "date_precision":
                "exact",

            "statement":
                (
                    "Vergi İnceleme Raporu "
                    "20.01.2026 tarihinde düzenlenmiştir."
                ),

            "source_fact_ids": [
                "f_report_vir"
            ],

            "source_document_ids": [
                "vir_001"
            ],

            "related_party_ids":
                [],

            "related_dispute_item_ids":
                [],

            "verification_state":
                "unverified",

            "confidence":
                0.99,

            "deadline_relevant":
                False,

            "notes":
                None,

            "_fact_id":
                "f_report_vir",

            "_date_label":
                "Rapor Tarihi",
        },

        {
            "date":
                "2026-02-05",

            "event_type":
                "document_date",

            "date_precision":
                "exact",

            "statement":
                (
                    "Davacı IHB-DEMO-2026-001 "
                    "sayılı ihbarnameye ilişkin "
                    "iptal talebinde bulunmaktadır."
                ),

            "source_fact_ids": [
                "f_issue_dava"
            ],

            "source_document_ids": [
                "dava_dilekcesi_001"
            ],

            "related_party_ids":
                [],

            "related_dispute_item_ids":
                [],

            "verification_state":
                "unverified",

            "confidence":
                0.99,

            "deadline_relevant":
                False,

            "notes":
                None,

            "_fact_id":
                "f_issue_dava",

            "_date_label":
                "İhbarname Tarihi",
        },

        {
            "date":
                "2026-02-05",

            "event_type":
                "document_date",

            "date_precision":
                "exact",

            "statement":
                (
                    "Vergi ve ceza ihbarnamesi "
                    "05.02.2026 tarihinde düzenlenmiştir."
                ),

            "source_fact_ids": [
                "f_issue_ihbar"
            ],

            "source_document_ids": [
                "ihbarname_001"
            ],

            "related_party_ids":
                [],

            "related_dispute_item_ids":
                [],

            "verification_state":
                "unverified",

            "confidence":
                0.99,

            "deadline_relevant":
                False,

            "notes":
                None,

            "_fact_id":
                "f_issue_ihbar",

            "_date_label":
                "Düzenleme Tarihi",
        },

        {
            "date":
                "2026-02-10",

            "event_type":
                "notification_date",

            "date_precision":
                "exact",

            "statement":
                (
                    "Davacı ihbarnamenin "
                    "10.02.2026 tarihinde tebliğ "
                    "edildiğini beyan etmektedir."
                ),

            "source_fact_ids": [
                "f_notice_dava"
            ],

            "source_document_ids": [
                "dava_dilekcesi_001"
            ],

            "related_party_ids":
                [],

            "related_dispute_item_ids":
                [],

            "verification_state":
                "unverified",

            "confidence":
                0.97,

            "deadline_relevant":
                True,

            "notes":
                None,

            "_fact_id":
                "f_notice_dava",

            "_date_label":
                "Tebliğ Tarihi",
        },

        {
            "date":
                "2026-02-10",

            "event_type":
                "notification_date",

            "date_precision":
                "exact",

            "statement":
                (
                    "İhbarnamede 10.02.2026 tarihinde "
                    "tebliğ edildiği belirtilmektedir."
                ),

            "source_fact_ids": [
                "f_notice_ihbar"
            ],

            "source_document_ids": [
                "ihbarname_001"
            ],

            "related_party_ids":
                [],

            "related_dispute_item_ids":
                [],

            "verification_state":
                "unverified",

            "confidence":
                0.95,

            "deadline_relevant":
                True,

            "notes":
                None,

            "_fact_id":
                "f_notice_ihbar",

            "_date_label":
                "Tebliğ Tarihi",
        },

        {
            "date":
                "2026-03-05",

            "event_type":
                "document_date",

            "date_precision":
                "exact",

            "statement":
                (
                    "Dava dilekçesinde dava tarihi "
                    "05.03.2026 olarak belirtilmiştir."
                ),

            "source_fact_ids": [
                "f_dava_date"
            ],

            "source_document_ids": [
                "dava_dilekcesi_001"
            ],

            "related_party_ids":
                [],

            "related_dispute_item_ids":
                [],

            "verification_state":
                "unverified",

            "confidence":
                0.99,

            "deadline_relevant":
                False,

            "notes":
                None,

            "_fact_id":
                "f_dava_date",

            "_date_label":
                "Dava Tarihi",
        },
    ]

    return (
        candidates,
        fact_index,
        document_index,
    )


# ============================================================
# SELF TEST
# ============================================================

def run_self_test():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - TIMELINE CONSOLIDATION POLICY V1"
    )

    print(
        "======================================"
    )

    (
        candidates,
        fact_index,
        document_index,
    ) = build_test_context()

    # ========================================================
    # T01 TURKISH NORMALIZATION
    # ========================================================

    normalized = normalize_text_tr(
        "Vergi İnceleme Raporu Tarihi"
    )

    assert (
        "vergi inceleme raporu tarihi"
        in normalized
    )

    print(
        "T01 Turkish normalization:",
        "PASS"
    )

    # ========================================================
    # T02 REPORT TYPE NORMALIZATION
    # ========================================================

    report_type = (
        canonicalize_event_type(
            candidates[
                0
            ],
            fact_index,
            document_index,
        )
    )

    assert (
        report_type
        == "report_date"
    )

    print(
        "T02 Report event normalization:",
        "PASS"
    )

    # ========================================================
    # T03 SUBJECT DOCUMENT
    # ========================================================

    subject = (
        infer_subject_document_id(
            candidates[
                0
            ],
            fact_index,
            document_index,
        )
    )

    assert (
        subject
        == "vir_001"
    )

    print(
        "T03 Subject document resolution:",
        "PASS"
    )

    # ========================================================
    # CONSOLIDATE
    # ========================================================

    consolidated = (
        consolidate_candidates(
            candidates,
            fact_index,
            document_index,
        )
    )

    # ========================================================
    # T04 8 -> 4
    # ========================================================

    assert (
        len(
            consolidated
        )
        == 4
    )

    print(
        "T04 Event consolidation 8 -> 4:",
        "PASS"
    )

    # ========================================================
    # T05 REPORT SUPPORT
    # ========================================================

    report_event = next(
        event
        for event in consolidated
        if (
            event[
                "date"
            ]
            == "2026-01-20"
            and event[
                "event_type"
            ]
            == "report_date"
        )
    )

    assert (
        len(
            report_event[
                "source_fact_ids"
            ]
        )
        == 3
    )

    assert set(
        report_event[
            "source_document_ids"
        ]
    ) == {
        "vir_001",
        "ihbarname_001",
        "dava_dilekcesi_001",
    }

    print(
        "T05 Multi-source preservation:",
        "PASS"
    )

    # ========================================================
    # T06 NOTIFICATION CONSOLIDATION
    # ========================================================

    notification = next(
        event
        for event in consolidated
        if event[
            "event_type"
        ]
        == "notification_date"
    )

    assert (
        len(
            notification[
                "source_fact_ids"
            ]
        )
        == 2
    )

    assert (
        notification[
            "deadline_relevant"
        ]
        is True
    )

    print(
        "T06 Notification consolidation:",
        "PASS"
    )

    # ========================================================
    # T07 DAVA DATE SAFETY
    # ========================================================

    dava_event = next(
        event
        for event in consolidated
        if event[
            "date"
        ]
        == "2026-03-05"
    )

    assert (
        dava_event[
            "event_type"
        ]
        == "document_date"
    )

    assert (
        dava_event[
            "event_type"
        ]
        != "filing_date"
    )

    print(
        "T07 Filing overclaim blocked:",
        "PASS"
    )

    # ========================================================
    # T08 VERIFICATION / CONFIDENCE
    # ========================================================

    assert (
        notification[
            "verification_state"
        ]
        == "unverified"
    )

    assert (
        notification[
            "confidence"
        ]
        == 0.95
    )

    print(
        "T08 Conservative propagation:",
        "PASS"
    )

    print()

    print(
        "Before:",
        len(
            candidates
        ),
    )

    print(
        "After:",
        len(
            consolidated
        ),
    )

    print()

    for event in consolidated:

        print(
            "-",
            event[
                "date"
            ],
            "|",
            event[
                "event_type"
            ],
            "| subject=",
            event[
                "_subject_document_id"
            ],
            "| support=",
            event[
                "_support_count"
            ],
        )

    print()

    print(
        "======================================"
    )

    print(
        " TIMELINE CONSOLIDATION POLICY V1: 8/8 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_self_test()