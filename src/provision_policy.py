# ============================================================
# VERGİ AI - PROVISION / APPLICABILITY POLICY V1
#
# AMAÇ:
#
# Document-level temporal durum ile
# provision-level hukuki durum ve
# fiili uygulanabilirliği birbirinden ayırmak.
#
#
# AYRILAN KAVRAMLAR:
#
# 1. DOCUMENT STATUS
#
#    Kanunun / belgenin genel hukuki durumu.
#
#
# 2. PROVISION FORMAL STATUS
#
#    Belirli:
#
#       madde
#       fıkra
#       bent
#
#    için hukuki/formal geçerlilik.
#
#
# 3. APPLICABILITY
#
#    Belirli bir:
#
#       başvuru
#       beyan
#       yararlanma
#       seçim
#       ödeme
#
#    imkanının belirli tarihte kullanılabilirliği.
#
#
# 4. SUBJECT PERIOD
#
#    Düzenlemenin hangi vergilendirme dönemlerini
#    kapsadığı.
#
#
# KRİTİK PRENSİP:
#
# formal_status = valid
#
# TEK BAŞINA:
#
# applicability = applicable
#
# DEMEK DEĞİLDİR.
#
#
# ÖRNEK:
#
# Kanun halen sistemde active olabilir.
#
# Madde formal olarak metinde mevcut olabilir.
#
# Ancak:
#
# 2016 yılında sona eren başvuru penceresi nedeniyle
# bugün yeni başvuru yapılamıyor olabilir.
#
#
# BİR DİĞER KRİTİK PRENSİP:
#
# Eski bir başvuru süresinin bulunması,
# sonradan uzatma olmadığını KANITLAMAZ.
#
# Bu nedenle:
#
# windows_complete = True
#
# ancak bütün değişiklikler / uzatmalar
# doğrulandığında kullanılabilir.
#
# ============================================================


from datetime import date
from datetime import datetime


# ============================================================
# ALLOWED VALUES
# ============================================================

TEMPORAL_MODES = {
    "neutral",
    "current",
    "historical_date"
}


QUESTION_SCOPES = {
    "neutral",
    "formal_status",
    "applicability",
    "both"
}


FORMAL_RESULTS = {
    "neutral",
    "valid",
    "invalid",
    "unknown"
}


APPLICABILITY_RESULTS = {
    "neutral",
    "applicable",
    "not_applicable",
    "unknown"
}


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_string(
    value
):

    if value is None:

        return None

    return str(
        value
    ).strip()


def normalize_lower(
    value
):

    normalized = normalize_string(
        value
    )

    if normalized is None:

        return None

    return normalized.lower()


# ============================================================
# DATE PARSER
# ============================================================

def parse_date(
    value
):

    if value is None:

        return None

    if isinstance(
        value,
        datetime
    ):

        return value.date()

    if isinstance(
        value,
        date
    ):

        return value

    value = str(
        value
    ).strip()

    if not value:

        return None

    try:

        return datetime.strptime(
            value,
            "%Y-%m-%d"
        ).date()

    except ValueError:

        return None


# ============================================================
# DATE OUTPUT
# ============================================================

def date_to_string(
    value
):

    parsed = parse_date(
        value
    )

    if parsed is None:

        return None

    return parsed.isoformat()


# ============================================================
# TEMPORAL TARGET DATE
# ============================================================

def resolve_target_date(
    temporal_mode,
    query_date=None,
    today=None
):

    temporal_mode = (
        normalize_lower(
            temporal_mode
        )
        or "neutral"
    )

    if temporal_mode not in TEMPORAL_MODES:

        raise ValueError(
            "Geçersiz temporal_mode: "
            f"{temporal_mode}"
        )

    # ========================================================
    # NEUTRAL
    # ========================================================

    if temporal_mode == "neutral":

        return None

    # ========================================================
    # CURRENT
    # ========================================================

    if temporal_mode == "current":

        if today is None:

            return date.today()

        parsed_today = parse_date(
            today
        )

        if parsed_today is None:

            raise ValueError(
                "Geçersiz today değeri: "
                f"{today}"
            )

        return parsed_today

    # ========================================================
    # HISTORICAL
    # ========================================================

    parsed_query_date = parse_date(
        query_date
    )

    if parsed_query_date is None:

        return None

    return parsed_query_date


# ============================================================
# PROVISION ID
# ============================================================

def get_provision_id(
    provision
):

    if not isinstance(
        provision,
        dict
    ):

        return None

    return normalize_string(
        provision.get(
            "provision_id"
        )
    )


# ============================================================
# FORMAL METADATA
#
# ÖNERİLEN YAPI:
#
# "formal": {
#
#     "verified": true,
#
#     "status": "active",
#
#     "valid_from": "2016-08-19",
#
#     "valid_through": null,
#
#     "repeal_effective_date": null
# }
#
#
# valid_through:
#
# Son geçerli gün.
#
#
# repeal_effective_date:
#
# Bu tarihten itibaren artık geçerli değil.
#
# ============================================================

def get_formal_metadata(
    provision
):

    if not isinstance(
        provision,
        dict
    ):

        return {}

    formal = provision.get(
        "formal"
    )

    if isinstance(
        formal,
        dict
    ):

        return formal

    return {}


# ============================================================
# APPLICABILITY METADATA
#
# ÖNERİLEN YAPI:
#
# "applicability": {
#
#     "windows_complete": true,
#
#     "windows_complete_verified": true,
#
#     "windows": [
#
#         {
#             "window_id": "original",
#
#             "type": "application",
#
#             "start": "2016-08-19",
#
#             "end": "2016-10-31",
#
#             "verified": true
#         }
#     ]
# }
#
#
# KRİTİK:
#
# windows_complete=True
#
# tek başına yeterli değildir.
#
# windows_complete_verified=True
#
# de gereklidir.
#
#
# Ayrıca bütün window kayıtlarının
# verified=True olması gerekir.
#
# ============================================================

def get_applicability_metadata(
    provision
):

    if not isinstance(
        provision,
        dict
    ):

        return {}

    applicability = provision.get(
        "applicability"
    )

    if isinstance(
        applicability,
        dict
    ):

        return applicability

    return {}


# ============================================================
# DATE WINDOW CHECK
#
# start ve end INCLUSIVE kabul edilir.
# ============================================================

def date_is_inside_window(
    target_date,
    start_date,
    end_date
):

    if target_date is None:

        return False

    if (
        start_date is not None
        and target_date < start_date
    ):

        return False

    if (
        end_date is not None
        and target_date > end_date
    ):

        return False

    return True


# ============================================================
# FORMAL STATUS EVALUATION
# ============================================================

def evaluate_formal_status(
    provision,
    temporal_mode="neutral",
    query_date=None,
    today=None
):

    temporal_mode = (
        normalize_lower(
            temporal_mode
        )
        or "neutral"
    )

    # ========================================================
    # NEUTRAL
    # ========================================================

    if temporal_mode == "neutral":

        return {

            "result":
                "neutral",

            "target_date":
                None,

            "verified":
                False,

            "status":
                None,

            "reason":
                (
                    "Neutral sorgu: provision-level "
                    "formal temporal değerlendirme yapılmadı."
                )
        }

    target_date = resolve_target_date(
        temporal_mode=
            temporal_mode,

        query_date=
            query_date,

        today=
            today
    )

    # ========================================================
    # DATE UNKNOWN
    # ========================================================

    if target_date is None:

        return {

            "result":
                "unknown",

            "target_date":
                None,

            "verified":
                False,

            "status":
                None,

            "reason":
                (
                    "Formal değerlendirme için hedef tarih "
                    "belirlenemedi."
                )
        }

    formal = get_formal_metadata(
        provision
    )

    verified = (
        formal.get(
            "verified"
        )
        is True
    )

    status = normalize_lower(
        formal.get(
            "status"
        )
    )

    valid_from = parse_date(
        formal.get(
            "valid_from"
        )
    )

    valid_through = parse_date(
        formal.get(
            "valid_through"
        )
    )

    repeal_effective_date = parse_date(
        formal.get(
            "repeal_effective_date"
        )
    )

    # ========================================================
    # FORMAL DATA NOT VERIFIED
    # ========================================================

    if not verified:

        return {

            "result":
                "unknown",

            "target_date":
                target_date.isoformat(),

            "verified":
                False,

            "status":
                status,

            "reason":
                (
                    "Provision-level formal metadata "
                    "doğrulanmış değil."
                )
        }

    # ========================================================
    # BEFORE VALID FROM
    # ========================================================

    if (
        valid_from is not None
        and target_date < valid_from
    ):

        return {

            "result":
                "invalid",

            "target_date":
                target_date.isoformat(),

            "verified":
                True,

            "status":
                status,

            "reason":
                (
                    "Hedef tarih provision valid_from "
                    "tarihinden önce."
                )
        }

    # ========================================================
    # AFTER VALID THROUGH
    # ========================================================

    if (
        valid_through is not None
        and target_date > valid_through
    ):

        return {

            "result":
                "invalid",

            "target_date":
                target_date.isoformat(),

            "verified":
                True,

            "status":
                status,

            "reason":
                (
                    "Hedef tarih provision valid_through "
                    "tarihinden sonra."
                )
        }

    # ========================================================
    # REPEAL EFFECTIVE DATE
    #
    # Bu tarih ve sonrası INVALID.
    # ========================================================

    if (
        repeal_effective_date is not None
        and target_date
        >= repeal_effective_date
    ):

        return {

            "result":
                "invalid",

            "target_date":
                target_date.isoformat(),

            "verified":
                True,

            "status":
                status,

            "reason":
                (
                    "Hedef tarih doğrulanmış "
                    "repeal_effective_date tarihinde "
                    "veya sonrasında."
                )
        }

    # ========================================================
    # ACTIVE-LIKE STATUS
    # ========================================================

    if status in {
        "active",
        "amended",
        "partially_repealed"
    }:

        # ----------------------------------------------------
        # Bir başlangıç tarihi veya başka temporal sınır
        # olmadan sadece status alanına güvenmek istemiyoruz.
        # ----------------------------------------------------

        if (
            valid_from is None
            and valid_through is None
            and repeal_effective_date is None
        ):

            return {

                "result":
                    "unknown",

                "target_date":
                    target_date.isoformat(),

                "verified":
                    True,

                "status":
                    status,

                "reason":
                    (
                        "Formal status doğrulanmış ancak "
                        "provision temporal sınırları yok."
                    )
            }

        return {

            "result":
                "valid",

            "target_date":
                target_date.isoformat(),

            "verified":
                True,

            "status":
                status,

            "reason":
                (
                    "Hedef tarih doğrulanmış provision "
                    "formal validity aralığında."
                )
        }

    # ========================================================
    # REPEALED STATUS
    #
    # Repeal tarihi biliniyorsa yukarıdaki kontrol
    # zaten hedef tarihi ayırmıştır.
    #
    # Hedef repeal tarihinden önceyse ve valid_from da
    # destekliyorsa VALID olabilir.
    # ========================================================

    if status in {
        "repealed",
        "historical"
    }:

        if repeal_effective_date is None:

            return {

                "result":
                    "unknown",

                "target_date":
                    target_date.isoformat(),

                "verified":
                    True,

                "status":
                    status,

                "reason":
                    (
                        "Provision repealed/historical olarak "
                        "işaretli ancak repeal tarihi yok."
                    )
            }

        if (
            valid_from is None
            or target_date >= valid_from
        ):

            return {

                "result":
                    "valid",

                "target_date":
                    target_date.isoformat(),

                "verified":
                    True,

                "status":
                    status,

                "reason":
                    (
                        "Hedef tarih doğrulanmış repeal "
                        "tarihinden önce."
                    )
            }

    # ========================================================
    # UNKNOWN STATUS
    # ========================================================

    return {

        "result":
            "unknown",

        "target_date":
            target_date.isoformat(),

        "verified":
            True,

        "status":
            status,

        "reason":
            (
                "Provision formal status güvenilir biçimde "
                "yorumlanamadı."
            )
    }


# ============================================================
# VERIFIED WINDOWS
# ============================================================

def get_verified_windows(
    provision
):

    applicability = (
        get_applicability_metadata(
            provision
        )
    )

    windows = applicability.get(
        "windows",
        []
    )

    if not isinstance(
        windows,
        list
    ):

        return []

    verified_windows = []

    for window in windows:

        if not isinstance(
            window,
            dict
        ):

            continue

        if window.get(
            "verified"
        ) is not True:

            continue

        verified_windows.append(
            window
        )

    return verified_windows


# ============================================================
# ALL WINDOWS VERIFIED?
# ============================================================

def all_windows_are_verified(
    provision
):

    applicability = (
        get_applicability_metadata(
            provision
        )
    )

    windows = applicability.get(
        "windows",
        []
    )

    if not isinstance(
        windows,
        list
    ):

        return False

    if not windows:

        return False

    for window in windows:

        if not isinstance(
            window,
            dict
        ):

            return False

        if window.get(
            "verified"
        ) is not True:

            return False

    return True


# ============================================================
# APPLICABILITY EVALUATION
# ============================================================

def evaluate_applicability(
    provision,
    temporal_mode="neutral",
    query_date=None,
    today=None
):

    temporal_mode = (
        normalize_lower(
            temporal_mode
        )
        or "neutral"
    )

    # ========================================================
    # NEUTRAL
    # ========================================================

    if temporal_mode == "neutral":

        return {

            "result":
                "neutral",

            "target_date":
                None,

            "matched_window_ids":
                [],

            "windows_complete":
                False,

            "reason":
                (
                    "Neutral sorgu: applicability "
                    "değerlendirmesi yapılmadı."
                )
        }

    target_date = resolve_target_date(
        temporal_mode=
            temporal_mode,

        query_date=
            query_date,

        today=
            today
    )

    if target_date is None:

        return {

            "result":
                "unknown",

            "target_date":
                None,

            "matched_window_ids":
                [],

            "windows_complete":
                False,

            "reason":
                (
                    "Applicability değerlendirmesi için "
                    "hedef tarih belirlenemedi."
                )
        }

    applicability = (
        get_applicability_metadata(
            provision
        )
    )

    windows = applicability.get(
        "windows",
        []
    )

    if not isinstance(
        windows,
        list
    ):

        windows = []

    verified_windows = (
        get_verified_windows(
            provision
        )
    )

    windows_complete = (
        applicability.get(
            "windows_complete"
        )
        is True
    )

    windows_complete_verified = (
        applicability.get(
            "windows_complete_verified"
        )
        is True
    )

    all_verified = (
        all_windows_are_verified(
            provision
        )
    )

    # ========================================================
    # MATCH VERIFIED WINDOWS
    # ========================================================

    matched_window_ids = []

    for window in verified_windows:

        start_date = parse_date(
            window.get(
                "start"
            )
        )

        end_date = parse_date(
            window.get(
                "end"
            )
        )

        # ----------------------------------------------------
        # Window tarihleri tamamen boşsa
        # doğrulanmış olsa bile kullanmayız.
        # ----------------------------------------------------

        if (
            start_date is None
            and end_date is None
        ):

            continue

        if date_is_inside_window(
            target_date=
                target_date,

            start_date=
                start_date,

            end_date=
                end_date
        ):

            matched_window_ids.append(
                normalize_string(
                    window.get(
                        "window_id"
                    )
                )
                or "unnamed_window"
            )

    # ========================================================
    # VERIFIED MATCH
    #
    # Completeness gerekmez.
    #
    # Çünkü doğrulanmış bir pencerenin içinde olduğumuzu
    # biliyoruz.
    # ========================================================

    if matched_window_ids:

        return {

            "result":
                "applicable",

            "target_date":
                target_date.isoformat(),

            "matched_window_ids":
                matched_window_ids,

            "windows_complete":
                (
                    windows_complete
                    and windows_complete_verified
                    and all_verified
                ),

            "reason":
                (
                    "Hedef tarih doğrulanmış bir "
                    "applicability window içinde."
                )
        }

    # ========================================================
    # OUTSIDE ALL VERIFIED WINDOWS
    #
    # Burada NOT_APPLICABLE diyebilmek için:
    #
    # - windows_complete=True
    # - windows_complete_verified=True
    # - tüm window kayıtları verified=True
    #
    # zorunludur.
    #
    # Çünkü sonradan süre uzatımı varsa ve biz bilmiyorsak:
    #
    # "not applicable"
    #
    # demek yanlış olabilir.
    # ========================================================

    if (
        windows
        and windows_complete
        and windows_complete_verified
        and all_verified
    ):

        return {

            "result":
                "not_applicable",

            "target_date":
                target_date.isoformat(),

            "matched_window_ids":
                [],

            "windows_complete":
                True,

            "reason":
                (
                    "Hedef tarih doğrulanmış ve tam olduğu "
                    "doğrulanan applicability windows "
                    "dışında."
                )
        }

    # ========================================================
    # UNKNOWN
    # ========================================================

    return {

        "result":
            "unknown",

        "target_date":
            target_date.isoformat(),

        "matched_window_ids":
            [],

        "windows_complete":
            False,

        "reason":
            (
                "Hedef tarih doğrulanmış bir window içinde değil; "
                "ancak bütün application/extension windows "
                "doğrulanmış olmadığı için not_applicable "
                "sonucu verilemez."
            )
    }


# ============================================================
# DECISION RESULT
#
# Formal ve applicability sonuçlarını tek bir değerde
# kaybetmeden özetler.
# ============================================================

def build_decision_result(
    question_scope,
    formal_result,
    applicability_result
):

    if question_scope == "neutral":

        return "neutral"

    if question_scope == "formal_status":

        return (
            "formal_"
            f"{formal_result}"
        )

    if question_scope == "applicability":

        return (
            "applicability_"
            f"{applicability_result}"
        )

    if question_scope == "both":

        return (
            "formal_"
            f"{formal_result}"
            "__applicability_"
            f"{applicability_result}"
        )

    return "unknown"


# ============================================================
# MAIN POLICY
# ============================================================

def evaluate_provision_policy(
    provision,
    temporal_mode="neutral",
    query_date=None,
    today=None,
    question_scope="both"
):

    temporal_mode = (
        normalize_lower(
            temporal_mode
        )
        or "neutral"
    )

    question_scope = (
        normalize_lower(
            question_scope
        )
        or "both"
    )

    if temporal_mode not in TEMPORAL_MODES:

        raise ValueError(
            "Geçersiz temporal_mode: "
            f"{temporal_mode}"
        )

    if question_scope not in QUESTION_SCOPES:

        raise ValueError(
            "Geçersiz question_scope: "
            f"{question_scope}"
        )

    formal = evaluate_formal_status(
        provision=
            provision,

        temporal_mode=
            temporal_mode,

        query_date=
            query_date,

        today=
            today
    )

    applicability = evaluate_applicability(
        provision=
            provision,

        temporal_mode=
            temporal_mode,

        query_date=
            query_date,

        today=
            today
    )

    decision_result = (
        build_decision_result(
            question_scope=
                question_scope,

            formal_result=
                formal.get(
                    "result"
                ),

            applicability_result=
                applicability.get(
                    "result"
                )
        )
    )

    target_date = (
        formal.get(
            "target_date"
        )
        or applicability.get(
            "target_date"
        )
    )

    return {

        "provision_id":
            get_provision_id(
                provision
            ),

        "question_scope":
            question_scope,

        "temporal_mode":
            temporal_mode,

        "target_date":
            target_date,

        "formal":
            formal,

        "applicability":
            applicability,

        "decision_result":
            decision_result
    }


# ============================================================
# SYNTHETIC BASE PROVISION
#
# BU VERİ GERÇEK 6736 VERİSİ DEĞİLDİR.
#
# Yalnızca policy testidir.
# ============================================================

def make_synthetic_provision():

    return {

        "provision_id":
            "TEST1000_m5_f3",

        "document_id":
            "TEST1000",

        "madde":
            "5",

        "fikra":
            "3",

        "bent":
            None,

        "formal": {

            "verified":
                True,

            "status":
                "active",

            "valid_from":
                "2016-08-19",

            "valid_through":
                None,

            "repeal_effective_date":
                None
        },

        "applicability": {

            "windows_complete":
                True,

            "windows_complete_verified":
                True,

            "windows": [

                {
                    "window_id":
                        "original_application",

                    "type":
                        "application",

                    "start":
                        "2016-08-19",

                    "end":
                        "2016-10-31",

                    "verified":
                        True
                }
            ]
        },

        "subject_periods": [

            {
                "start":
                    "2011-01-01",

                "end":
                    "2015-12-31",

                "verified":
                    True
            }
        ]
    }


# ============================================================
# ASSERT
# ============================================================

def assert_equal(
    actual,
    expected,
    message
):

    if actual != expected:

        raise AssertionError(
            f"{message} | "
            f"beklenen={expected}, "
            f"gerçek={actual}"
        )


# ============================================================
# P01
#
# Neutral.
# ============================================================

def test_neutral():

    provision = (
        make_synthetic_provision()
    )

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "neutral",

        question_scope=
            "both"
    )

    assert_equal(
        result[
            "formal"
        ][
            "result"
        ],
        "neutral",
        "Formal neutral"
    )

    assert_equal(
        result[
            "applicability"
        ][
            "result"
        ],
        "neutral",
        "Applicability neutral"
    )


# ============================================================
# P02
#
# Formal valid today.
# ============================================================

def test_formal_valid():

    provision = (
        make_synthetic_provision()
    )

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "current",

        today=
            "2026-08-31",

        question_scope=
            "formal_status"
    )

    assert_equal(
        result[
            "formal"
        ][
            "result"
        ],
        "valid",
        "Formal valid"
    )


# ============================================================
# P03
#
# Before provision valid_from.
# ============================================================

def test_formal_before_start():

    provision = (
        make_synthetic_provision()
    )

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "historical_date",

        query_date=
            "2015-01-01",

        question_scope=
            "formal_status"
    )

    assert_equal(
        result[
            "formal"
        ][
            "result"
        ],
        "invalid",
        "Formal before start"
    )


# ============================================================
# P04
#
# Applicability window içinde.
# ============================================================

def test_applicable_inside_window():

    provision = (
        make_synthetic_provision()
    )

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "historical_date",

        query_date=
            "2016-09-15",

        question_scope=
            "applicability"
    )

    assert_equal(
        result[
            "applicability"
        ][
            "result"
        ],
        "applicable",
        "Inside application window"
    )


# ============================================================
# P05
#
# Tam ve doğrulanmış windows dışı.
#
# NOT_APPLICABLE denebilir.
# ============================================================

def test_not_applicable_complete_windows():

    provision = (
        make_synthetic_provision()
    )

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "historical_date",

        query_date=
            "2020-01-01",

        question_scope=
            "applicability"
    )

    assert_equal(
        result[
            "applicability"
        ][
            "result"
        ],
        "not_applicable",
        "Outside complete windows"
    )


# ============================================================
# P06
#
# Aynı eski window var.
#
# AMA:
#
# bütün değişiklik/uzatma pencerelerinin
# doğrulandığını bilmiyoruz.
#
# Bu nedenle NOT_APPLICABLE DİYEMEYİZ.
# ============================================================

def test_incomplete_windows_unknown():

    provision = (
        make_synthetic_provision()
    )

    provision[
        "applicability"
    ][
        "windows_complete_verified"
    ] = False

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "historical_date",

        query_date=
            "2020-01-01",

        question_scope=
            "applicability"
    )

    assert_equal(
        result[
            "applicability"
        ][
            "result"
        ],
        "unknown",
        "Incomplete windows must be unknown"
    )


# ============================================================
# P07
#
# null repeal + unverified formal status
#
# "mülga değildir" denemez.
# ============================================================

def test_null_repeal_not_proof():

    provision = (
        make_synthetic_provision()
    )

    provision[
        "formal"
    ] = {

        "verified":
            False,

        "status":
            "active",

        "valid_from":
            "2016-08-19",

        "valid_through":
            None,

        "repeal_effective_date":
            None
    }

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "current",

        today=
            "2026-08-31",

        question_scope=
            "formal_status"
    )

    assert_equal(
        result[
            "formal"
        ][
            "result"
        ],
        "unknown",
        "Null repeal cannot prove active provision"
    )


# ============================================================
# P08
#
# ASIL AYRIM:
#
# FORMAL VALID
#
# ama
#
# APPLICABILITY NOT_APPLICABLE
# ============================================================

def test_formal_valid_but_not_applicable():

    provision = (
        make_synthetic_provision()
    )

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "historical_date",

        query_date=
            "2020-01-01",

        question_scope=
            "both"
    )

    assert_equal(
        result[
            "formal"
        ][
            "result"
        ],
        "valid",
        "Formal result"
    )

    assert_equal(
        result[
            "applicability"
        ][
            "result"
        ],
        "not_applicable",
        "Applicability result"
    )

    assert_equal(
        result[
            "decision_result"
        ],
        (
            "formal_valid"
            "__applicability_not_applicable"
        ),
        "Combined decision"
    )


# ============================================================
# P09
#
# EXTENSION WINDOW
#
# Çok kritik ürün testi.
#
# Orijinal süre bitmiş olsa bile
# sonradan doğrulanmış extension varsa
# sistem onu görebilmeli.
# ============================================================

def test_extension_window():

    provision = (
        make_synthetic_provision()
    )

    provision[
        "applicability"
    ][
        "windows"
    ].append(
        {
            "window_id":
                "extension_1",

            "type":
                "application_extension",

            "start":
                "2016-11-01",

            "end":
                "2016-11-25",

            "verified":
                True
        }
    )

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "historical_date",

        query_date=
            "2016-11-10",

        question_scope=
            "applicability"
    )

    assert_equal(
        result[
            "applicability"
        ][
            "result"
        ],
        "applicable",
        "Extension window"
    )

    assert_equal(
        result[
            "applicability"
        ][
            "matched_window_ids"
        ],
        [
            "extension_1"
        ],
        "Extension window id"
    )


# ============================================================
# P10
#
# UNVERIFIED EXTENSION
#
# Orijinal window bitmiş.
#
# Ama doğrulanmamış bir extension kaydı mevcut.
#
# Sistem NOT_APPLICABLE dememeli.
# ============================================================

def test_unverified_extension_blocks_negative_claim():

    provision = (
        make_synthetic_provision()
    )

    provision[
        "applicability"
    ][
        "windows"
    ].append(
        {
            "window_id":
                "possible_extension",

            "type":
                "application_extension",

            "start":
                "2016-11-01",

            "end":
                "2016-11-25",

            "verified":
                False
        }
    )

    result = evaluate_provision_policy(
        provision=
            provision,

        temporal_mode=
            "historical_date",

        query_date=
            "2020-01-01",

        question_scope=
            "applicability"
    )

    assert_equal(
        result[
            "applicability"
        ][
            "result"
        ],
        "unknown",
        (
            "Unverified extension must block "
            "not_applicable conclusion"
        )
    )


# ============================================================
# RUN TESTS
# ============================================================

def run_tests():

    tests = [

        (
            "P01",
            "Neutral provision evaluation",
            test_neutral
        ),

        (
            "P02",
            "Formal valid",
            test_formal_valid
        ),

        (
            "P03",
            "Formal before start invalid",
            test_formal_before_start
        ),

        (
            "P04",
            "Inside applicability window",
            test_applicable_inside_window
        ),

        (
            "P05",
            "Outside complete windows not applicable",
            test_not_applicable_complete_windows
        ),

        (
            "P06",
            "Incomplete windows unknown",
            test_incomplete_windows_unknown
        ),

        (
            "P07",
            "Null repeal not proof",
            test_null_repeal_not_proof
        ),

        (
            "P08",
            "Formal valid but not applicable",
            test_formal_valid_but_not_applicable
        ),

        (
            "P09",
            "Verified extension window",
            test_extension_window
        ),

        (
            "P10",
            "Unverified extension blocks negative claim",
            test_unverified_extension_blocks_negative_claim
        )
    ]

    print(
        "\n======================================"
    )

    print(
        " VERGİ AI - PROVISION POLICY V1 TEST"
    )

    print(
        "======================================"
    )

    results = []

    for (
        test_id,
        test_name,
        test_function
    ) in tests:

        try:

            test_function()

            passed = True

            error = None

        except Exception as exception:

            passed = False

            error = str(
                exception
            )

        results.append(
            {
                "id":
                    test_id,

                "name":
                    test_name,

                "passed":
                    passed,

                "error":
                    error
            }
        )

        print(
            f"{test_id}:",
            (
                "PASS"
                if passed
                else "FAIL"
            ),
            "-",
            test_name
        )

        if error:

            print(
                "   ",
                error
            )

    passed_count = sum(

        1

        for result
        in results

        if result[
            "passed"
        ]
    )

    failed_count = (
        len(
            results
        )
        - passed_count
    )

    print(
        "\n======================================"
    )

    print(
        " TEST ÖZETİ"
    )

    print(
        "======================================"
    )

    print(
        "Toplam test:",
        len(
            results
        )
    )

    print(
        "PASS:",
        passed_count
    )

    print(
        "FAIL:",
        failed_count
    )

    print(
        "======================================"
    )

    if failed_count:

        raise RuntimeError(
            "Provision Policy testlerinden "
            "en az biri başarısız."
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_tests()