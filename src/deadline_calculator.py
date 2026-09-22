# ============================================================
# VERGİ AI - DEADLINE CALCULATOR V1
#
# AMAÇ
# ----
#
# Deadline Rule Selection Policy tarafından seçilen canonical
# deadline rule üzerinden deterministik süre hesabı yapmak.
#
#
# GÜVENLİK ZİNCİRİ
# ----------------
#
# canonical timeline event
#        ↓
# Deadline Rule Selection Policy
#        ↓
# active rule
#        ↓
# anchor verified + exact?
#        ↓
# historical legal basis verified?
#        ↓
# deterministic arithmetic
#        ↓
# judicial recess policy
#        ↓
# end-day / holiday policy
#        ↓
# deadline analysis
#        ↓
# Deadline Validator V1
#
#
# KRİTİK KURALLAR
# ----------------
#
# 1. Unverified anchor üzerinden deadline HESAPLANMAZ.
#
# 2. exact olmayan anchor tarihi üzerinden deadline HESAPLANMAZ.
#
# 3. Selected rule'un hukuki dayanakları anchor tarihi
#    itibarıyla historical_date modunda doğrulanmalıdır.
#
# 4. V1:
#
#       duration.unit = day
#       day_count_policy = calendar_days
#
#    destekler.
#
# 5. start_rule:
#
#       next_day
#       same_day
#
#    desteklenir.
#
# 6. end_day_policy:
#
#       exact_duration
#       next_business_day_if_holiday
#
#    desteklenir.
#
# 7. next_business_day_if_holiday için complete calendar
#    olmadan kesin deadline üretilmez.
#
# 8. İYUK m.8/3 + m.61/1:
#
#    provisional deadline 20 Temmuz - 31 Ağustos arasına
#    denk gelirse judicial recess applicability bilinmelidir.
#
#    True  -> 7 Eylül'e taşınır.
#    False -> recess adjustment yapılmaz.
#    None  -> needs_review.
#
# 9. Deadline V1 expiry_state:
#
#       not_evaluated
#
#    olarak kalır.
#
# 10. Bu motor active/expired kararı vermez.
#
# ============================================================


import argparse
import hashlib
import json
import sys
import tempfile

from datetime import (
    date,
    datetime,
    timedelta,
)

from pathlib import Path


from deadline_rule_selection_policy import (
    select_for_case_event,
)

from deadline_legal_basis_resolver import (
    resolve_ruleset_legal_basis,
)

from deadline_validator import (
    load_canonical_timeline,
    validate_deadline_analysis,
)

from holiday_calendar_validator import (
    validate_holiday_calendar,
)


# ============================================================
# VERSION
# ============================================================

DEADLINE_CALCULATOR_VERSION = "1"


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

DEFAULT_RULESET_PATH = (
    DATA_DIR
    / "deadline_rules"
    / "deadline_rules.json"
)

DEFAULT_PROVISIONS_PATH = (
    DATA_DIR
    / "provisions.json"
)

# PILOT READINESS ADIM 5: bağımsız-inceleme §5.2 düzeltmesi - bu sabit
# YALNIZ burada (`deadline_engine.py`'de DEĞİL) tanımlanır, çünkü
# `deadline_engine.py` bu modülü import eder (`:58`) ve tersi dairesel
# olurdu; `deadline_calculator.py`'nin KENDİ `main()`'i de (K6) bu
# sabite doğrudan erişebilmelidir. `DEFAULT_PROVISIONS_PATH` ile AYNI
# desen (tek tanım, `deadline_engine.py`/facade bunu HER ZAMAN
# `deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH` üzerinden, dotted
# attribute erişimiyle, çağrı anında okur - `from ... import ...` ile
# by-value KOPYALANMAZ, aksi halde test monkeypatch'i (`deadline_
# calculator.DEFAULT_HOLIDAY_CALENDAR_PATH = ...`) diğer modüllere
# görünmez kalırdı).
DEFAULT_HOLIDAY_CALENDAR_PATH = (
    DATA_DIR
    / "holiday_calendar"
    / "holiday_calendar.json"
)


# ============================================================
# IYUK JUDICIAL RECESS BASIS
# ============================================================

IYUK_RECESS_TRIGGER_REF = (
    "IYUK_2577_m8_3"
)

IYUK_RECESS_PERIOD_REF = (
    "IYUK_2577_m61_1"
)


# ============================================================
# EXCEPTION
# ============================================================

class DeadlineCalculatorError(
    Exception
):
    pass


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


# ============================================================
# DATE
# ============================================================

def parse_iso_date(
    value,
):

    if isinstance(
        value,
        date,
    ):

        return value

    if not isinstance(
        value,
        str,
    ):

        return None

    try:

        return date.fromisoformat(
            value.strip()
        )

    except ValueError:

        return None


# ============================================================
# HOLIDAYS
# ============================================================

def normalize_holiday_dates(
    values,
):

    if values is None:

        return set()

    result = set()

    for value in values:

        parsed = parse_iso_date(
            value
        )

        if parsed is None:

            raise DeadlineCalculatorError(
                "Geçersiz holiday date: "
                f"{value}"
            )

        result.add(
            parsed
        )

    return result


def is_non_working_day(
    target_date,
    holiday_dates,
):

    # Monday = 0
    # Saturday = 5
    # Sunday = 6

    if (
        target_date.weekday()
        >= 5
    ):

        return True

    if (
        target_date
        in holiday_dates
    ):

        return True

    return False


def move_to_next_business_day(
    target_date,
    holiday_dates,
):

    current = target_date

    # Fail-safe.
    for _ in range(
        370
    ):

        if not is_non_working_day(
            current,
            holiday_dates,
        ):

            return current

        current = (
            current
            + timedelta(
                days=1
            )
        )

    raise DeadlineCalculatorError(
        "Next business day resolution "
        "370 gün içinde tamamlanamadı."
    )


# ============================================================
# HOLIDAY CALENDAR REGISTRY - PILOT READINESS ADIM 5.
#
# `calculate_rule_deadline()` artık elle beyan edilen `holiday_dates`/
# `calendar_complete` yerine, BURADA türetilmiş bir `holiday_calendar`
# yapısı (`{"holiday_dates": set(date), "covered_verified_years":
# set(int)}`) alır. Bu ayrım BİLİNÇLİDİR (bağımsız inceleme §5.1):
# türetme (bu fonksiyonlar) `final_deadline`'dan TAMAMEN BAĞIMSIZDIR -
# yalnız `verified is True` olan yılların birleşimidir. Kapsam kontrolü
# (`[anchor.year, final.year]` aralığının TAMAMEN kapsanıp
# kapsanmadığı) `calculate_rule_deadline()`'ın KENDİ İÇİNDE, kaydırma
# ÇALIŞTIKTAN SONRA yapılır - döngüsellik burada değil, orada çözülür.
# ============================================================

def derive_effective_holiday_calendar(
    calendar_document,
):
    """Saf fonksiyon - zaten `validate_holiday_calendar(raise_on_error=
    True)` ile doğrulanmış bir takvim belgesi bekler (doğrulamayı
    KENDİSİ yapmaz). `covered_verified_years`, `verified is True` olan
    HER yılın kendisidir (final.year'a bağlı DEĞİLDİR - bağımsız
    inceleme §5.1'in döngüsellik çözümü). `holiday_dates`, o yılların
    `full_day` tatilleri VE (`half_day_policy == 'counts_as_holiday'`
    ise) `half_day` tatillerinin BİRLEŞİMİDİR."""

    half_day_policy = calendar_document.get(
        "half_day_policy"
    )

    covered_verified_years = set()

    holiday_dates = set()

    for year_entry in (
        calendar_document.get(
            "years"
        )
        or []
    ):

        if not isinstance(
            year_entry,
            dict,
        ):

            continue

        if (
            year_entry.get(
                "verified"
            )
            is not True
        ):

            continue

        year_value = year_entry.get(
            "year"
        )

        covered_verified_years.add(
            year_value
        )

        for holiday in (
            year_entry.get(
                "holidays"
            )
            or []
        ):

            if not isinstance(
                holiday,
                dict,
            ):

                continue

            day_type = holiday.get(
                "day_type"
            )

            counts_as_holiday = (
                day_type
                == "full_day"

                or
                (
                    day_type
                    == "half_day"
                    and half_day_policy
                    == "counts_as_holiday"
                )
            )

            if not counts_as_holiday:

                continue

            parsed = parse_iso_date(
                holiday.get(
                    "date"
                )
            )

            if parsed is not None:

                holiday_dates.add(
                    parsed
                )

    return {
        "holiday_dates":
            holiday_dates,

        "covered_verified_years":
            covered_verified_years,
    }


def load_holiday_calendar(
    path=None,
):
    """Fail-closed yükleyici (`corpus_policy_validator.load_policy()` +
    `validate_corpus_policy(raise_on_error=True)` deseni birebir):
    ham baytları okur, `holiday_calendar_validator.validate_holiday_
    calendar()` (`raise_on_error=True`) ile doğrular, SONRA türetir.
    `path=None` -> bu modülün KENDİ `DEFAULT_HOLIDAY_CALENDAR_PATH`
    sabitine (bare-name lookup - aynı modül içinde olduğu için test
    monkeypatch'i `deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH`
    üzerinden burada da görünür kalır). Dönüş: `derive_effective_
    holiday_calendar()`'ın ürettiği iki küme + `calendar_id`/
    `calendar_version`/`source_sha256` (audit/identity amaçlı, saf
    hesaplama tarafından KULLANILMAZ)."""

    effective_path = (
        Path(
            path
        )
        if path is not None
        else DEFAULT_HOLIDAY_CALENDAR_PATH
    )

    if not effective_path.exists():

        raise FileNotFoundError(
            "Holiday calendar dosyası bulunamadı:\n"
            f"{effective_path}"
        )

    raw_bytes = effective_path.read_bytes()

    try:

        document = json.loads(
            raw_bytes.decode(
                "utf-8"
            )
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as error:

        raise DeadlineCalculatorError(
            "Holiday calendar dosyası geçerli JSON değil: "
            f"{effective_path}"
        ) from error

    try:

        validate_holiday_calendar(
            calendar=
                document,

            raise_on_error=
                True,
        )

    except Exception as error:

        raise DeadlineCalculatorError(
            "Holiday calendar doğrulanamadı: "
            f"{effective_path}: {error}"
        ) from error

    derived = derive_effective_holiday_calendar(
        document
    )

    return {
        "holiday_dates":
            derived[
                "holiday_dates"
            ],

        "covered_verified_years":
            derived[
                "covered_verified_years"
            ],

        "calendar_id":
            document.get(
                "calendar_id"
            ),

        "calendar_version":
            document.get(
                "calendar_version"
            ),

        "source_sha256":
            hashlib.sha256(
                raw_bytes
            ).hexdigest(),
    }


# ============================================================
# JUDICIAL RECESS
# ============================================================

def is_within_iyuk_judicial_recess(
    target_date,
):

    start = date(
        target_date.year,
        7,
        20,
    )

    end = date(
        target_date.year,
        8,
        31,
    )

    return (
        start
        <= target_date
        <= end
    )


def iyuk_recess_extended_deadline(
    year,
):

    # Çalışmaya ara verme 31 Ağustos sonunda biter.
    #
    # Bitişi izleyen tarih 1 Eylül'dür.
    # Bu tarihten itibaren 7 günlük uzama:
    #
    # 1,2,3,4,5,6,7 Eylül
    #
    # Son tarih = 7 Eylül.

    return date(
        year,
        9,
        7,
    )


# ============================================================
# RULE HELPERS
# ============================================================

def get_duration_day_type(
    rule,
):

    policy = rule.get(
        "day_count_policy"
    )

    if (
        policy
        == "calendar_days"
    ):

        return "calendar"

    if (
        policy
        == "business_days"
    ):

        return "business"

    return "not_applicable"


def rule_has_iyuk_recess_basis(
    rule,
):

    refs = rule.get(
        "legal_basis_refs",
        []
    )

    if not isinstance(
        refs,
        list,
    ):

        return False

    return (
        IYUK_RECESS_TRIGGER_REF
        in refs

        and

        IYUK_RECESS_PERIOD_REF
        in refs
    )


# ============================================================
# CORE ARITHMETIC
# ============================================================

def calculate_rule_deadline(
    anchor_date,
    rule,
    *,
    holiday_calendar,
    judicial_recess_applicable=None,
):
    """PILOT READINESS ADIM 5 (K4/C1): elle beyan edilen `holiday_dates`/
    `calendar_complete` parametreleri TAMAMEN KALKTI - `holiday_calendar`
    ZORUNLUDUR (keyword-only, default YOK - fail-closed-by-construction),
    `deadline_calculator.load_holiday_calendar()`'ın türettiği
    `{"holiday_dates": set(date), "covered_verified_years": set(int)}`
    yapısını bekler. Bağımsız inceleme §5.1'in döngüsellik çözümü:
    kapsam kontrolü (`[anchor.year, final.year]`'ın TAMAMEN
    `covered_verified_years` içinde olması) kaydırma
    (`move_to_next_business_day`) ÇALIŞTIKTAN SONRA yapılır - hiçbir
    ara "calculated" durumu hiçbir çağırana SIZMAZ (fonksiyon dönmeden
    ÖNCE karar verilir)."""

    anchor = parse_iso_date(
        anchor_date
    )

    if anchor is None:

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                None,

            "judicial_recess_applied":
                False,

            "holiday_adjustment_applied":
                False,

            "reason":
                "anchor_date geçerli ISO date değil.",
        }

    if not isinstance(
        rule,
        dict,
    ):

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                None,

            "judicial_recess_applied":
                False,

            "holiday_adjustment_applied":
                False,

            "reason":
                "Deadline rule geçerli dict değil.",
        }

    # ========================================================
    # RULE STATE
    # ========================================================

    if (
        rule.get(
            "status"
        )
        != "active"
    ):

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                None,

            "judicial_recess_applied":
                False,

            "holiday_adjustment_applied":
                False,

            "reason":
                "Rule active değil.",
        }

    if (
        rule.get(
            "calculation_enabled"
        )
        is not True
    ):

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                None,

            "judicial_recess_applied":
                False,

            "holiday_adjustment_applied":
                False,

            "reason":
                "Rule calculation_enabled=True değil.",
        }

    # ========================================================
    # DURATION
    # ========================================================

    duration = rule.get(
        "duration",
        {}
    )

    if not isinstance(
        duration,
        dict,
    ):

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                None,

            "judicial_recess_applied":
                False,

            "holiday_adjustment_applied":
                False,

            "reason":
                "Rule duration geçerli değil.",
        }

    duration_value = duration.get(
        "value"
    )

    duration_unit = duration.get(
        "unit"
    )

    if (
        not isinstance(
            duration_value,
            int,
        )
        or duration_value < 0
    ):

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                None,

            "judicial_recess_applied":
                False,

            "holiday_adjustment_applied":
                False,

            "reason":
                "Desteklenmeyen duration.value.",
        }

    if (
        duration_unit
        != "day"
    ):

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                None,

            "judicial_recess_applied":
                False,

            "holiday_adjustment_applied":
                False,

            "reason":
                (
                    "Deadline Calculator V1 yalnız "
                    "duration.unit='day' destekler."
                ),
        }

    # ========================================================
    # DAY COUNT POLICY
    # ========================================================

    if (
        rule.get(
            "day_count_policy"
        )
        != "calendar_days"
    ):

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                None,

            "judicial_recess_applied":
                False,

            "holiday_adjustment_applied":
                False,

            "reason":
                (
                    "Deadline Calculator V1 yalnız "
                    "calendar_days policy destekler."
                ),
        }

    # ========================================================
    # START RULE
    # ========================================================

    start_rule = rule.get(
        "start_rule"
    )

    if (
        start_rule
        == "next_day"
    ):

        # Day 1 = anchor + 1
        # Day N = anchor + N

        base_deadline = (
            anchor
            + timedelta(
                days=duration_value
            )
        )

    elif (
        start_rule
        == "same_day"
    ):

        if (
            duration_value
            == 0
        ):

            base_deadline = anchor

        else:

            base_deadline = (
                anchor
                + timedelta(
                    days=
                        duration_value
                        - 1
                )
            )

    else:

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                None,

            "judicial_recess_applied":
                False,

            "holiday_adjustment_applied":
                False,

            "reason":
                (
                    "Desteklenmeyen start_rule: "
                    f"{start_rule}"
                ),
        }

    provisional_deadline = (
        base_deadline
    )

    judicial_recess_applied = False

    # ========================================================
    # IYUK JUDICIAL RECESS
    # ========================================================

    if (
        rule_has_iyuk_recess_basis(
            rule
        )
        and is_within_iyuk_judicial_recess(
            provisional_deadline
        )
    ):

        # ----------------------------------------------------
        # Somut mahkeme bakımından m.61/1 istisnası
        # bulunup bulunmadığı bilinmeden otomatik uzatma YOK.
        # ----------------------------------------------------

        if (
            judicial_recess_applicable
            is None
        ):

            return {
                "calculation_state":
                    "needs_review",

                "calculated_deadline":
                    None,

                "base_deadline":
                    base_deadline.isoformat(),

                "judicial_recess_applied":
                    False,

                "holiday_adjustment_applied":
                    False,

                "reason":
                    (
                        "Base deadline İYUK çalışmaya ara "
                        "verme dönemine rastlıyor ancak "
                        "judicial_recess_applicable "
                        "belirlenmemiş."
                    ),
            }

        if (
            judicial_recess_applicable
            is True
        ):

            provisional_deadline = (
                iyuk_recess_extended_deadline(
                    provisional_deadline.year
                )
            )

            judicial_recess_applied = True

        # False ise base deadline korunur.

    # ========================================================
    # END DAY POLICY
    # ========================================================

    end_day_policy = rule.get(
        "end_day_policy"
    )

    holiday_adjustment_applied = False

    effective_holiday_calendar = (
        holiday_calendar
        if holiday_calendar is not None
        else {
            "holiday_dates": set(),
            "covered_verified_years": set(),
        }
    )

    holidays = normalize_holiday_dates(
        effective_holiday_calendar.get(
            "holiday_dates"
        )
    )

    covered_verified_years = set(
        effective_holiday_calendar.get(
            "covered_verified_years"
        )
        or set()
    )

    if (
        end_day_policy
        == "exact_duration"
    ):

        final_deadline = (
            provisional_deadline
        )

    elif (
        end_day_policy
        == "next_business_day_if_holiday"
    ):

        # ----------------------------------------------------
        # PILOT READINESS ADIM 5 (bağımsız inceleme §5.1 - döngüsellik
        # çözümü): SIRA KASITLI OLARAK DEĞİŞTİ. Kaydırma ÖNCE
        # çalıştırılır (final_deadline burada belirlenir), kapsam
        # kontrolü SONRA yapılır - çünkü "[anchor.year, final.year]
        # aralığı tamamen doğrulanmış mı" sorusu final.year'ı
        # GEREKTİRİR ve final.year yalnız kaydırma TAMAMLANDIKTAN
        # SONRA bilinir. Bu, motor-seviyesi bir post-check (önce
        # "calculated" döndürüp sonra "needs_review"a düşürmek)
        # DEĞİLDİR - karar bu fonksiyon DÖNMEDEN ÖNCE, TEK bir yerde
        # verilir; hiçbir ara "calculated" durumu hiçbir çağırana
        # SIZMAZ (Prensip 9, fail-closed).
        # ----------------------------------------------------

        final_deadline = (
            move_to_next_business_day(
                provisional_deadline,
                holidays,
            )
        )

        provisional_holiday_adjustment_applied = (
            final_deadline
            != provisional_deadline
        )

        uncovered_years = sorted(
            year
            for year in range(
                anchor.year,
                final_deadline.year
                + 1,
            )
            if year
            not in covered_verified_years
        )

        if uncovered_years:

            return {
                "calculation_state":
                    "needs_review",

                "calculated_deadline":
                    None,

                "base_deadline":
                    base_deadline.isoformat(),

                "provisional_deadline":
                    provisional_deadline.isoformat(),

                "judicial_recess_applied":
                    judicial_recess_applied,

                "holiday_adjustment_applied":
                    False,

                "reason":
                    (
                        "end_day_policy="
                        "'next_business_day_if_holiday' ancak "
                        "şu yıl(lar) resmi tatil takviminde "
                        "'verified' olarak işaretlenmemiş: "
                        f"{uncovered_years}."
                    ),
            }

        holiday_adjustment_applied = (
            provisional_holiday_adjustment_applied
        )

    else:

        return {
            "calculation_state":
                "needs_review",

            "calculated_deadline":
                None,

            "base_deadline":
                base_deadline.isoformat(),

            "provisional_deadline":
                provisional_deadline.isoformat(),

            "judicial_recess_applied":
                judicial_recess_applied,

            "holiday_adjustment_applied":
                False,

            "reason":
                (
                    "Desteklenmeyen end_day_policy: "
                    f"{end_day_policy}"
                ),
        }

    # ========================================================
    # CALCULATED
    # ========================================================

    return {
        "calculation_state":
            "calculated",

        "calculated_deadline":
            final_deadline.isoformat(),

        "base_deadline":
            base_deadline.isoformat(),

        "provisional_deadline":
            provisional_deadline.isoformat(),

        "judicial_recess_applied":
            judicial_recess_applied,

        "holiday_adjustment_applied":
            holiday_adjustment_applied,

        "reason":
            "Deterministik deadline hesabı tamamlandı.",
    }


# ============================================================
# CANONICAL TIMELINE EVENT
# ============================================================

def get_canonical_anchor_event(
    case_id,
    anchor_event_id,
):

    context = (
        load_canonical_timeline(
            case_id
        )
    )

    events = context.get(
        "events",
        {}
    )

    if isinstance(
        events,
        dict,
    ):

        event = events.get(
            anchor_event_id
        )

        if event is not None:

            return event

    if isinstance(
        events,
        list,
    ):

        for event in events:

            if (
                isinstance(
                    event,
                    dict,
                )
                and event.get(
                    "event_id"
                )
                == anchor_event_id
            ):

                return event

    raise DeadlineCalculatorError(
        "Canonical timeline anchor event bulunamadı: "
        f"{anchor_event_id}"
    )


# ============================================================
# HISTORICAL LEGAL BASIS
# ============================================================

def verify_rule_legal_basis_for_date(
    rule_id,
    anchor_date,
    ruleset_path,
    *,
    provisions_path=None,
):

    result = (
        resolve_ruleset_legal_basis(
            ruleset_path=
                ruleset_path,

            manifest_path=
                DEFAULT_PROVISIONS_PATH
                if provisions_path is None
                else provisions_path,

            temporal_mode=
                "historical_date",

            query_date=
                anchor_date,
        )
    )

    matches = [
        rule_result
        for rule_result
        in result.get(
            "rules",
            []
        )
        if (
            rule_result.get(
                "rule_id"
            )
            == rule_id
        )
    ]

    if len(
        matches
    ) != 1:

        return {
            "valid":
                False,

            "reason":
                "Historical legal basis target rule bulunamadı.",

            "rule_result":
                None,
        }

    rule_result = (
        matches[
            0
        ]
    )

    valid = (
        rule_result.get(
            "all_resolved"
        )
        is True

        and

        rule_result.get(
            "all_basis_verified"
        )
        is True

        and

        rule_result.get(
            "activation_eligible"
        )
        is True
    )

    return {
        "valid":
            valid,

        "reason":
            (
                "Historical legal basis verified."
                if valid
                else
                "Historical legal basis verification blocked."
            ),

        "rule_result":
            rule_result,
    }


# ============================================================
# SAFE FALLBACK RULE DATA
# ============================================================

def fallback_duration():

    return {
        "value":
            0,

        "unit":
            "day",

        "day_type":
            "not_applicable",
    }


# ============================================================
# DEADLINE RECORD
# ============================================================

def build_deadline_record(
    case_id,
    anchor_event,
    selection,
    ruleset_path,
    *,
    holiday_calendar,
    judicial_recess_applicable=None,
    provisions_path=None,
):

    selection_state = (
        selection.get(
            "selection_state"
        )
    )

    selected_rule = (
        selection.get(
            "selected_rule"
        )
    )

    anchor_event_id = (
        anchor_event.get(
            "event_id"
        )
    )

    anchor_date = (
        anchor_event.get(
            "date"
        )
    )

    anchor_verification = (
        anchor_event.get(
            "verification_state"
        )
    )

    anchor_precision = (
        anchor_event.get(
            "date_precision"
        )
    )

    confidence = float(
        anchor_event.get(
            "confidence",
            0.5,
        )
    )

    # ========================================================
    # NO SELECTED RULE
    # ========================================================

    if not isinstance(
        selected_rule,
        dict,
    ):

        if (
            "ambiguous"
            in str(
                selection_state
            )
        ):

            calculation_state = (
                "blocked_ambiguous_rule"
            )

        elif (
            selection_state
            == "no_match"
        ):

            calculation_state = (
                "blocked_missing_rule"
            )

        else:

            calculation_state = (
                "needs_review"
            )

        return {
            "deadline_id":
                "deadline_001",

            "deadline_type":
                "other",

            "description":
                "Deadline rule çözümlenemedi.",

            "anchor_event_id":
                anchor_event_id,

            "anchor_date":
                anchor_date,

            "anchor_verification_state":
                anchor_verification,

            "rule_id":
                "unresolved_deadline_rule",

            "legal_basis_refs":
                [],

            "duration":
                fallback_duration(),

            "start_rule":
                "unknown",

            "calculation_state":
                calculation_state,

            "calculated_deadline":
                None,

            "expiry_state":
                "not_evaluated",

            "confidence":
                confidence,

            "requires_human_review":
                True,

            "notes":
                selection.get(
                    "reason"
                )
                or "Deadline rule selection çözümlenemedi.",
        }

    # ========================================================
    # RULE DATA
    # ========================================================

    rule_id = (
        selected_rule.get(
            "rule_id"
        )
    )

    legal_basis_refs = (
        selected_rule.get(
            "legal_basis_refs",
            []
        )
    )

    duration = (
        selected_rule.get(
            "duration",
            {}
        )
    )

    output_duration = {
        "value":
            duration.get(
                "value",
                0,
            ),

        "unit":
            duration.get(
                "unit",
                "day",
            ),

        "day_type":
            get_duration_day_type(
                selected_rule
            ),
    }

    base_record = {
        "deadline_id":
            "deadline_001",

        "deadline_type":
            selected_rule.get(
                "deadline_type",
                "other",
            ),

        "description":
            selected_rule.get(
                "name"
            )
            or "Deadline candidate.",

        "anchor_event_id":
            anchor_event_id,

        "anchor_date":
            anchor_date,

        "anchor_verification_state":
            anchor_verification,

        "rule_id":
            rule_id,

        "legal_basis_refs":
            list(
                legal_basis_refs
            ),

        "duration":
            output_duration,

        "start_rule":
            selected_rule.get(
                "start_rule",
                "unknown",
            ),

        "expiry_state":
            "not_evaluated",

        "confidence":
            confidence,

        "requires_human_review":
            (
                selected_rule.get(
                    "requires_human_review"
                )
                is True
            ),
    }

    # ========================================================
    # UNVERIFIED ANCHOR
    # ========================================================

    if (
        anchor_verification
        != "verified"
        or selection_state
        == "selected_blocked_anchor"
    ):

        base_record.update(
            {
                "calculation_state":
                    "blocked_unverified_anchor",

                "calculated_deadline":
                    None,

                "requires_human_review":
                    True,

                "notes":
                    (
                        "Canonical anchor event verified "
                        "olmadığı için deadline hesaplanmadı."
                    ),
            }
        )

        return base_record

    # ========================================================
    # DATE PRECISION
    # ========================================================

    if (
        anchor_precision
        != "exact"
    ):

        base_record.update(
            {
                "calculation_state":
                    "needs_review",

                "calculated_deadline":
                    None,

                "requires_human_review":
                    True,

                "notes":
                    (
                        "Canonical anchor event date_precision "
                        "exact olmadığı için kesin deadline "
                        "hesaplanmadı."
                    ),
            }
        )

        return base_record

    # ========================================================
    # SELECTION MUST ALLOW CALCULATION
    # ========================================================

    if (
        selection_state
        != "selected"
        or selection.get(
            "calculation_allowed"
        )
        is not True
    ):

        base_record.update(
            {
                "calculation_state":
                    "needs_review",

                "calculated_deadline":
                    None,

                "requires_human_review":
                    True,

                "notes":
                    (
                        "Deadline Rule Selection Policy "
                        "calculation_allowed=True üretmedi."
                    ),
            }
        )

        return base_record

    # ========================================================
    # HISTORICAL LEGAL BASIS CHECK
    # ========================================================

    basis_check = (
        verify_rule_legal_basis_for_date(
            rule_id=
                rule_id,

            anchor_date=
                anchor_date,

            ruleset_path=
                ruleset_path,

            provisions_path=
                provisions_path,
        )
    )

    if (
        basis_check[
            "valid"
        ]
        is not True
    ):

        base_record.update(
            {
                "calculation_state":
                    "needs_review",

                "calculated_deadline":
                    None,

                "requires_human_review":
                    True,

                "notes":
                    (
                        "Anchor tarihi itibarıyla canonical "
                        "hukuki dayanak verification "
                        "tamamlanamadı."
                    ),
            }
        )

        return base_record

    # ========================================================
    # CALCULATE
    # ========================================================

    calculation = (
        calculate_rule_deadline(
            anchor_date=
                anchor_date,

            rule=
                selected_rule,

            holiday_calendar=
                holiday_calendar,

            judicial_recess_applicable=
                judicial_recess_applicable,
        )
    )

    calculation_state = (
        calculation[
            "calculation_state"
        ]
    )

    calculated_deadline = (
        calculation[
            "calculated_deadline"
        ]
    )

    requires_review = (
        selected_rule.get(
            "requires_human_review"
        )
        is True
        or calculation_state
        != "calculated"
    )

    notes = [
        calculation.get(
            "reason"
        )
    ]

    if calculation.get(
        "base_deadline"
    ):

        notes.append(
            "base_deadline="
            + calculation[
                "base_deadline"
            ]
        )

    if calculation.get(
        "judicial_recess_applied"
    ):

        notes.append(
            "judicial_recess_adjustment=applied"
        )

    if calculation.get(
        "holiday_adjustment_applied"
    ):

        notes.append(
            "holiday_adjustment=applied"
        )

    if (
        isinstance(
            holiday_calendar,
            dict,
        )
        and holiday_calendar.get(
            "calendar_id"
        )
        and holiday_calendar.get(
            "source_sha256"
        )
    ):

        # PILOT READINESS ADIM 5 (§4-E) - kayıt-düzeyi takvim revizyon
        # etiketi. `calculation_state`'ten BAĞIMSIZ olarak eklenir (bu
        # kaydın HANGİ takvim revizyonuna karşı hesaplandığı, sonuç
        # `needs_review` olsa bile audit amaçlı görünür kalmalıdır).
        # `holiday_calendar` yalnız `derive_effective_holiday_calendar()`
        # çıktısıysa (self-test'lerdeki gibi) bu iki alan YOKTUR -
        # etiket sessizce atlanır (yeni bir zorunluluk İCAT EDİLMEZ).

        notes.append(
            "holiday_calendar="
            + str(
                holiday_calendar[
                    "calendar_id"
                ]
            )
            + "@"
            + str(
                holiday_calendar[
                    "source_sha256"
                ]
            )[
                :16
            ]
        )

    base_record.update(
        {
            "calculation_state":
                calculation_state,

            "calculated_deadline":
                calculated_deadline,

            "requires_human_review":
                requires_review,

            "notes":
                " | ".join(
                    item
                    for item in notes
                    if item
                ),
        }
    )

    return base_record


# ============================================================
# CASE ANALYSIS
# ============================================================

def build_case_deadline_analysis(
    case_id,
    anchor_event_id,
    ruleset_path=DEFAULT_RULESET_PATH,
    judicial_recess_applicable=None,
    *,
    provisions_path=None,
    holiday_calendar=None,
    holiday_calendar_path=None,
):
    """PILOT READINESS ADIM 5: `holiday_dates`/`calendar_complete`
    parametreleri TAMAMEN KALKTI. `holiday_calendar` ZATEN türetilmiş
    bir yapı olarak verilebilir (çağıran - ör. `deadline_engine.
    run_engine()` - kendi audit metadata'sı için zaten yüklediyse,
    dosyayı İKİNCİ KEZ yüklemeden yeniden kullanabilir); `None` ise
    `holiday_calendar_path`'ten (`None` -> üretim `DEFAULT_HOLIDAY_
    CALENDAR_PATH`) `load_holiday_calendar()` ile YÜKLENİR+DOĞRULANIR
    (fail-closed - dosya eksik/bozuk/geçersizse burada raise eder)."""

    effective_holiday_calendar = (
        holiday_calendar
        if holiday_calendar is not None
        else load_holiday_calendar(
            holiday_calendar_path
        )
    )

    anchor_event = (
        get_canonical_anchor_event(
            case_id,
            anchor_event_id,
        )
    )

    selection = (
        select_for_case_event(
            case_id=
                case_id,

            anchor_event_id=
                anchor_event_id,

            ruleset_path=
                Path(
                    ruleset_path
                ),
        )
    )

    deadline = (
        build_deadline_record(
            case_id=
                case_id,

            anchor_event=
                anchor_event,

            selection=
                selection,

            ruleset_path=
                Path(
                    ruleset_path
                ),

            holiday_calendar=
                effective_holiday_calendar,

            judicial_recess_applicable=
                judicial_recess_applicable,

            provisions_path=
                provisions_path,
        )
    )

    warnings = []

    state = deadline[
        "calculation_state"
    ]

    if (
        state
        == "blocked_unverified_anchor"
    ):

        warnings.append(
            (
                "Canonical anchor event doğrulanmadığı "
                "için kesin son tarih üretilmedi."
            )
        )

    elif (
        state
        == "blocked_missing_rule"
    ):

        warnings.append(
            "Uygulanabilir deadline rule bulunamadı."
        )

    elif (
        state
        == "blocked_ambiguous_rule"
    ):

        warnings.append(
            "Birden fazla deadline rule arasında belirsizlik var."
        )

    elif (
        state
        == "needs_review"
    ):

        warnings.append(
            (
                "Deadline hesabı deterministic olarak "
                "tamamlanamadı; human review gerekli."
            )
        )

    return {
        "schema_version":
            1,

        "deadline_analysis_id":
            (
                f"deadline_{case_id}_"
                f"{anchor_event_id}_v1"
            ),

        "case_id":
            case_id,

        "status":
            "completed",

        "generated_at":
            (
                datetime.now()
                .astimezone()
                .isoformat()
            ),

        "deadlines": [
            deadline
        ],

        "warnings":
            warnings,

        "notes":
            (
                "Deadline Calculator V1. "
                "Expiry değerlendirmesi yapılmamıştır."
            ),
    }


# ============================================================
# FULL VALIDATION
# ============================================================

def validate_analysis_object(
    analysis,
    case_id,
):

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            delete=False,
        ) as temp:

            json.dump(
                analysis,
                temp,
                ensure_ascii=False,
                indent=2,
            )

            temp.write(
                "\n"
            )

            temp_path = Path(
                temp.name
            )

        result = (
            validate_deadline_analysis(
                deadline_path=
                    temp_path,

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

            raise DeadlineCalculatorError(
                "Deadline Validator valid=False döndürdü."
            )

        return result

    finally:

        if (
            temp_path is not None
            and temp_path.exists()
        ):

            temp_path.unlink()


# ============================================================
# PRODUCTION RULE
# ============================================================

def load_production_rule():

    ruleset = load_json(
        DEFAULT_RULESET_PATH
    )

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
            == "iyuk_tax_court_general_lawsuit_filing"
        )
    ]

    if len(
        matches
    ) != 1:

        raise DeadlineCalculatorError(
            "Production IYUK deadline rule bulunamadı."
        )

    return matches[
        0
    ]


# ============================================================
# SELF TEST
# ============================================================

def run_self_test():

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE CALCULATOR V1"
    )

    print(
        "======================================"
    )

    rule = (
        load_production_rule()
    )

    # ========================================================
    # T01 ACTIVE RULE
    # ========================================================

    assert (
        rule.get(
            "status"
        )
        == "active"
    )

    assert (
        rule.get(
            "calculation_enabled"
        )
        is True
    )

    assert (
        len(
            rule.get(
                "legal_basis_refs",
                []
            )
        )
        == 6
    )

    print(
        "T01 Production rule ready:",
        "PASS"
    )

    # ========================================================
    # T02 SIMPLE 30-DAY CALCULATION
    #
    # 10.02 + 30 calendar days = 12.03
    # ========================================================

    covered_2026_only = {
        "holiday_dates": set(),
        "covered_verified_years": {2026},
    }

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-02-10",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                True,
        )
    )

    assert (
        result[
            "calculation_state"
        ]
        == "calculated"
    )

    assert (
        result[
            "calculated_deadline"
        ]
        == "2026-03-12"
    )

    print(
        "T02 30-day next-day calculation (registry-derived holiday_calendar):",
        "PASS"
    )

    # ========================================================
    # T03 WEEKEND ADJUSTMENT
    #
    # 15.01 + 30 = 14.02.2026 Saturday
    # -> 16.02.2026 Monday
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-01-15",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                True,
        )
    )

    assert (
        result[
            "calculated_deadline"
        ]
        == "2026-02-16"
    )

    assert (
        result[
            "holiday_adjustment_applied"
        ]
        is True
    )

    print(
        "T03 Weekend adjustment:",
        "PASS"
    )

    # ========================================================
    # T04 EXPLICIT HOLIDAY ADJUSTMENT (registry-derived holiday_dates)
    #
    # Base = 12.03.2026
    # Synthetic holiday = 12.03
    # -> 13.03
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-02-10",

            rule=
                rule,

            holiday_calendar={
                "holiday_dates": {
                    date(
                        2026,
                        3,
                        12,
                    ),
                },

                "covered_verified_years":
                    {2026},
            },

            judicial_recess_applicable=
                True,
        )
    )

    assert (
        result[
            "calculated_deadline"
        ]
        == "2026-03-13"
    )

    print(
        "T04 Explicit registry holiday adjustment:",
        "PASS"
    )

    # ========================================================
    # T05 JUDICIAL RECESS
    #
    # 25.06 + 30 = 25.07
    # Judicial recess -> 07.09
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-25",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                True,
        )
    )

    assert (
        result[
            "base_deadline"
        ]
        == "2026-07-25"
    )

    assert (
        result[
            "judicial_recess_applied"
        ]
        is True
    )

    assert (
        result[
            "calculated_deadline"
        ]
        == "2026-09-07"
    )

    print(
        "T05 IYUK judicial recess adjustment:",
        "PASS"
    )

    # ========================================================
    # T06 UNKNOWN RECESS APPLICABILITY FAIL-CLOSED - recess
    # ambiguity is checked BEFORE the calendar-coverage gate, so an
    # empty/uncovered calendar here does not change the outcome.
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-25",

            rule=
                rule,

            holiday_calendar={
                "holiday_dates": set(),
                "covered_verified_years": set(),
            },

            judicial_recess_applicable=
                None,
        )
    )

    assert (
        result[
            "calculation_state"
        ]
        == "needs_review"
    )

    assert (
        result[
            "calculated_deadline"
        ]
        is None
    )

    print(
        "T06 Judicial recess ambiguity blocked:",
        "PASS"
    )

    # ========================================================
    # T07 UNCOVERED (NOT verified) CALENDAR YEAR FAIL-CLOSED - PILOT
    # READINESS ADIM 5: this replaces the old elle-beyan
    # `calendar_complete=False` scenario with the registry-derived
    # equivalent (2026 genuinely present in `years[]` but not
    # `verified: True` -> not in `covered_verified_years`).
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-02-10",

            rule=
                rule,

            holiday_calendar={
                "holiday_dates": set(),
                "covered_verified_years": set(),
            },

            judicial_recess_applicable=
                True,
        )
    )

    assert (
        result[
            "calculation_state"
        ]
        == "needs_review"
    )

    assert (
        result[
            "calculated_deadline"
        ]
        is None
    )

    print(
        "T07 Uncovered (unverified) calendar year blocked:",
        "PASS"
    )

    # ========================================================
    # T07b COVERAGE CROSSING - a REAL holiday shift pushes the final
    # date into a year that is NOT covered (§5.1 of the independent
    # scope review): anchor 2026-12-01 (+30 -> 2026-12-31), 2026-12-31
    # marked as a verified full_day holiday -> shift would land on
    # 2027-01-01, but 2027 is NOT covered -> needs_review, NEVER a
    # silently-shifted "calculated" result.
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-12-01",

            rule=
                rule,

            holiday_calendar={
                "holiday_dates": {
                    date(
                        2026,
                        12,
                        31,
                    ),
                },

                "covered_verified_years":
                    {2026},
            },

            judicial_recess_applicable=
                False,
        )
    )

    assert (
        result[
            "calculation_state"
        ]
        == "needs_review"
    )

    assert (
        result[
            "calculated_deadline"
        ]
        is None
    )

    print(
        "T07b Holiday shift crossing into an uncovered year blocked:",
        "PASS"
    )

    # ========================================================
    # T08 HISTORICAL LEGAL BASIS
    # ========================================================

    basis = (
        verify_rule_legal_basis_for_date(
            rule_id=
                rule[
                    "rule_id"
                ],

            anchor_date=
                "2026-02-10",

            ruleset_path=
                DEFAULT_RULESET_PATH,
        )
    )

    assert (
        basis[
            "valid"
        ]
        is True
    )

    assert (
        basis[
            "rule_result"
        ].get(
            "legal_basis_count"
        )
        == 6
    )

    print(
        "T08 Historical legal basis:",
        "PASS"
    )

    # ========================================================
    # T09 REAL CASE RULE SELECTION
    # ========================================================

    selection = (
        select_for_case_event(
            case_id=
                "case_0001",

            anchor_event_id=
                "timeline_event_003",

            ruleset_path=
                DEFAULT_RULESET_PATH,
        )
    )

    assert (
        selection.get(
            "selection_state"
        )
        == "selected_blocked_anchor"
    )

    assert (
        selection.get(
            "calculation_allowed"
        )
        is False
    )

    print(
        "T09 Production unverified anchor selection:",
        "PASS"
    )

    # ========================================================
    # T10 REAL CASE ANALYSIS
    # ========================================================

    analysis = (
        build_case_deadline_analysis(
            case_id=
                "case_0001",

            anchor_event_id=
                "timeline_event_003",

            ruleset_path=
                DEFAULT_RULESET_PATH,
        )
    )

    deadline = (
        analysis[
            "deadlines"
        ][
            0
        ]
    )

    assert (
        deadline[
            "calculation_state"
        ]
        == "blocked_unverified_anchor"
    )

    assert (
        deadline[
            "calculated_deadline"
        ]
        is None
    )

    assert (
        deadline[
            "requires_human_review"
        ]
        is True
    )

    print(
        "T10 Production calculation blocked:",
        "PASS"
    )

    # ========================================================
    # T11 FULL DEADLINE VALIDATOR
    # ========================================================

    validation = (
        validate_analysis_object(
            analysis=
                analysis,

            case_id=
                "case_0001",
        )
    )

    assert (
        validation[
            "valid"
        ]
        is True
    )

    print(
        "T11 Deadline Validator integration:",
        "PASS"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()

    print(
        "Production case:",
        analysis[
            "case_id"
        ]
    )

    print(
        "Anchor event:",
        deadline[
            "anchor_event_id"
        ]
    )

    print(
        "Anchor date:",
        deadline[
            "anchor_date"
        ]
    )

    print(
        "Anchor verification:",
        deadline[
            "anchor_verification_state"
        ]
    )

    print(
        "Rule:",
        deadline[
            "rule_id"
        ]
    )

    print(
        "Legal basis:",
        len(
            deadline[
                "legal_basis_refs"
            ]
        )
    )

    print(
        "Calculation state:",
        deadline[
            "calculation_state"
        ]
    )

    print(
        "Calculated deadline:",
        deadline[
            "calculated_deadline"
        ]
    )

    print(
        "Human review:",
        deadline[
            "requires_human_review"
        ]
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE CALCULATOR V1: 12/12 PASS"
    )

    print(
        "======================================"
    )


# ============================================================
# CLI
# ============================================================

def parse_judicial_recess_arg(
    value,
):

    if (
        value
        == "yes"
    ):

        return True

    if (
        value
        == "no"
    ):

        return False

    return None


def main():

    parser = argparse.ArgumentParser(
        description=(
            "Vergi AI Deadline Calculator V1"
        )
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
    )

    parser.add_argument(
        "--case",
        dest="case_id",
        default="case_0001",
    )

    parser.add_argument(
        "--anchor",
        dest="anchor_event_id",
        default="timeline_event_003",
    )

    parser.add_argument(
        "--ruleset",
        dest="ruleset_path",
        default=str(
            DEFAULT_RULESET_PATH
        ),
    )

    parser.add_argument(
        "--judicial-recess-applicable",
        choices=[
            "yes",
            "no",
            "unknown",
        ],
        default="unknown",
    )

    args = parser.parse_args()

    if args.self_test:

        run_self_test()

        return

    # PILOT READINESS ADIM 5 (K6): `--holiday`/`--calendar-complete`
    # elle beyan bayrakları TAMAMEN KALDIRILDI - bu salt-okunur teşhis
    # CLI'ı (bir mutasyon yolu DEĞİLDİR, `validate_analysis_object()`
    # yalnız `tempfile.NamedTemporaryFile`'a yazar) artık ZORUNLU
    # olarak üretim `DEFAULT_HOLIDAY_CALENDAR_PATH` registry'sini
    # kullanır - `build_case_deadline_analysis()`'in kendi
    # `holiday_calendar_path=None` varsayılanı bunu otomatik sağlar.

    judicial_recess_applicable = (
        parse_judicial_recess_arg(
            args.judicial_recess_applicable
        )
    )

    analysis = (
        build_case_deadline_analysis(
            case_id=
                args.case_id,

            anchor_event_id=
                args.anchor_event_id,

            ruleset_path=
                Path(
                    args.ruleset_path
                ),

            judicial_recess_applicable=
                judicial_recess_applicable,
        )
    )

    validation = (
        validate_analysis_object(
            analysis=
                analysis,

            case_id=
                args.case_id,
        )
    )

    print()

    print(
        "======================================"
    )

    print(
        " VERGİ AI - DEADLINE CALCULATOR V1"
    )

    print(
        "======================================"
    )

    print()

    print(
        "Validator:",
        (
            "PASS"
            if validation.get(
                "valid"
            )
            else "FAIL"
        )
    )

    print()

    print(
        json.dumps(
            analysis,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()

    print(
        "======================================"
    )

    print(
        " DEADLINE CALCULATOR V1: PASS"
    )

    print(
        "======================================"
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
            " DEADLINE CALCULATOR V1: FAIL"
        )

        print(
            "======================================"
        )

        sys.exit(
            1
        )