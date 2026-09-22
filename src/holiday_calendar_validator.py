# ============================================================
# VERGİ AI - HOLIDAY CALENDAR VALIDATOR V1.
#
# AMAÇ:
#
# data/holiday_calendar/holiday_calendar.json içindeki resmi tatil
# takvimi registry'sini (`src/corpus_policy_validator.py`/
# `data/corpus_policy.schema.json` emsali - PILOT READINESS ADIM 5):
#
# 1. JSON Schema
# 2. years[] artan sıralı, year tekil
# 3. Her yıl içindeki holidays[].date'in yılı kendi year'ıyla eşleşmeli;
#    yıl içinde tarih tekil; artan sıralı
# 4. source_ref_index o yılın source_refs uzunluğu içinde
# 5. verified is True olan bir yıl en az 1 source_refs girdisi ve
#    boş-olmayan verification_ref taşımak ZORUNDA (identity kontrolü,
#    truthiness DEĞİL - manifest_validator'ın anonymization_applied is
#    True emsali, CLAUDE.md RAG Corpus Prerequisite §F)
# 6. half_day_policy == "not_decided" iken verified:true bir yılda
#    day_type == "half_day" girdisi varsa ERROR
#
# açısından doğrulamak.
#
#
# KRİTİK PRENSİP:
#
# Bu validator takvim İÇERİĞİNİN hukuken doğru olduğunu KANITLAMAZ.
#
# Yalnız artefaktın kendi içinde tutarlı, kapalı-sözlüklü ve JSON Schema
# ile drift'siz olmasını sağlar. `verified: true` yalnız "bir avukat bu
# yılın tatil listesini onayladı" der - resmi tatilin gerçekten doğru
# olduğunu KANITLAMAZ (bkz. Pilot Readiness Adım 5/6/7).
#
#
# BİLİNÇLİ SAPMA (deadline_rule_validator.py emsalinden):
#
# run_self_test() fixture'larını `data/`'nin altındaki kalıcı bir
# dizine DEĞİL, `tempfile.TemporaryDirectory()`'ye yazar - gerçek
# `data/` ağacına hiçbir self-test koşusu dokunmaz
# (`corpus_policy_validator.py`'nin bilinçli sapmasıyla AYNI desen).
#
#
# load_calendar() bu modülün İÇİNDE (run_self_test/main) ve bu modülü
# çağıran testlerde kullanılan, saf/yan etkisiz bir JSON yükleyicidir,
# kendi başına doğrulama YAPMAZ. `src/deadline_calculator.py` bu
# fonksiyonu İMPORT ETMEZ - yalnız `validate_holiday_calendar()`'ı
# import eder ve kendi `load_holiday_calendar()`'ı içinde KENDİ ham
# bayt okuma + `json.loads()` adımlarını taşır (bkz. o fonksiyonun
# docstring'i) - iki modül `HOLIDAY_CALENDAR_PATH`/
# `DEFAULT_HOLIDAY_CALENDAR_PATH` adında AYRI, birbirinden bağımsız
# module-level sabitler taşır (aynı üretim dosyasına işaret eder,
# `corpus_policy_validator.CORPUS_POLICY_PATH`'in tek-tanım deseninden
# BİLİNÇLİ bir sapma - ayrıntı için deadline_calculator.py'nin
# DEFAULT_HOLIDAY_CALENDAR_PATH yorumuna bkz.).
#
# JSON Schema `uniqueItems`/sıralama kısıtlarını (whole-object
# karşılaştırması) İFADE EDEMEZ - years[] artan sıra/tekillik,
# holidays[].date artan sıra/tekillik/yıl-eşleşmesi, source_ref_index
# sınırı ve "verified is True ⇒ source_refs>=1 ∧ nonblank
# verification_ref" identity kuralı BU MODÜLÜN kendi Python
# fonksiyonlarında uygulanır - şemanın kendisi bunları uygulayamaz.
# ============================================================


import argparse
import copy
import json
import sys
import tempfile

from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


# ============================================================
# VERSION
# ============================================================

HOLIDAY_CALENDAR_VALIDATOR_VERSION = "1"


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

HOLIDAY_CALENDAR_SCHEMA_PATH = (
    DATA_DIR
    / "holiday_calendar.schema.json"
)

HOLIDAY_CALENDAR_PATH = (
    DATA_DIR
    / "holiday_calendar"
    / "holiday_calendar.json"
)


# ============================================================
# EXCEPTION
# ============================================================

class HolidayCalendarValidationError(Exception):
    pass


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path):

    path = Path(path)

    if not path.exists():

        raise FileNotFoundError(
            f"JSON dosyası bulunamadı:\n{path}"
        )

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


def load_calendar(path=None):
    """Saf, yan etkisiz yükleyici - şema/iş-kuralı doğrulaması YAPMAZ.
    `path=None` iken gerçek, repo-committed HOLIDAY_CALENDAR_PATH'i
    yükler - bu modülün HOLIDAY_CALENDAR_PATH sabiti test amaçlı
    monkeypatch edilebilir (diğer src/*.py modüllerinin DATA_DIR/
    CASES_DIR sabitleriyle AYNI, yerleşik konvansiyon)."""

    return load_json(path or HOLIDAY_CALENDAR_PATH)


# ============================================================
# SCHEMA
# ============================================================

def validate_schema(calendar):

    schema = load_json(HOLIDAY_CALENDAR_SCHEMA_PATH)

    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    errors = sorted(
        validator.iter_errors(calendar),
        key=lambda error: list(error.absolute_path),
    )

    messages = []

    for error in errors:

        path = ".".join(
            str(part) for part in error.absolute_path
        )

        if path:

            messages.append(f"{path}: {error.message}")

        else:

            messages.append(error.message)

    return messages


# ============================================================
# YEAR ORDERING / UNIQUENESS
# ============================================================

def validate_year_ordering_and_uniqueness(calendar):

    errors = []

    years = calendar.get("years") or []

    seen = set()

    previous_year = None

    for entry in years:

        if not isinstance(entry, dict):

            continue

        year = entry.get("year")

        if year in seen:

            errors.append(
                f"years: duplicate year: {year}"
            )

        seen.add(year)

        if (
            previous_year is not None
            and isinstance(year, int)
            and isinstance(previous_year, int)
            and year <= previous_year
        ):

            errors.append(
                "years: artan sırada değil "
                f"({previous_year} sonrası {year})"
            )

        if isinstance(year, int):

            previous_year = year

    return errors


# ============================================================
# HOLIDAY DATE / YEAR MATCH, ORDERING, UNIQUENESS
# ============================================================

def validate_holiday_ordering_and_year_match(calendar):

    errors = []

    for entry in calendar.get("years") or []:

        if not isinstance(entry, dict):

            continue

        year = entry.get("year")

        holidays = entry.get("holidays") or []

        seen_dates = set()

        previous_date = None

        for holiday in holidays:

            if not isinstance(holiday, dict):

                continue

            date_value = holiday.get("date")

            if not isinstance(date_value, str):

                continue

            if date_value in seen_dates:

                errors.append(
                    f"years[year={year}].holidays: duplicate date: "
                    f"{date_value}"
                )

            seen_dates.add(date_value)

            if (
                previous_date is not None
                and date_value <= previous_date
            ):

                errors.append(
                    f"years[year={year}].holidays: artan sırada değil "
                    f"({previous_date} sonrası {date_value})"
                )

            previous_date = date_value

            date_year = date_value.split("-", 1)[0]

            if (
                isinstance(year, int)
                and date_year != str(year)
            ):

                errors.append(
                    f"years[year={year}].holidays: {date_value} yılı "
                    f"kendi year alanıyla ({year}) eşleşmiyor"
                )

    return errors


# ============================================================
# source_ref_index BOUNDS
# ============================================================

def validate_source_ref_index_bounds(calendar):

    errors = []

    for entry in calendar.get("years") or []:

        if not isinstance(entry, dict):

            continue

        year = entry.get("year")

        source_ref_count = len(entry.get("source_refs") or [])

        for holiday in entry.get("holidays") or []:

            if not isinstance(holiday, dict):

                continue

            index = holiday.get("source_ref_index")

            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index >= source_ref_count
            ):

                errors.append(
                    f"years[year={year}].holidays: source_ref_index="
                    f"{index!r} o yılın source_refs uzunluğu "
                    f"({source_ref_count}) içinde değil"
                )

    return errors


# ============================================================
# VERIFIED YEAR IDENTITY: source_refs>=1 AND nonblank
# verification_ref (identity kontrolü, truthiness DEĞİL)
# ============================================================

def validate_verified_year_provenance(calendar):

    errors = []

    for entry in calendar.get("years") or []:

        if not isinstance(entry, dict):

            continue

        if entry.get("verified") is not True:

            continue

        year = entry.get("year")

        source_refs = entry.get("source_refs") or []

        verification_ref = entry.get("verification_ref")

        if len(source_refs) < 1:

            errors.append(
                f"years[year={year}]: verified=true ama source_refs "
                "boş - doğrulama kaynağı yok."
            )

        if (
            not isinstance(verification_ref, str)
            or not verification_ref.strip()
        ):

            errors.append(
                f"years[year={year}]: verified=true ama "
                "verification_ref boş/whitespace/non-string."
            )

    return errors


# ============================================================
# half_day_policy == "not_decided" BLOCKS verified half_day
# ============================================================

def validate_half_day_policy_consistency(calendar):

    errors = []

    half_day_policy = calendar.get("half_day_policy")

    if half_day_policy != "not_decided":

        return errors

    for entry in calendar.get("years") or []:

        if not isinstance(entry, dict):

            continue

        if entry.get("verified") is not True:

            continue

        year = entry.get("year")

        for holiday in entry.get("holidays") or []:

            if not isinstance(holiday, dict):

                continue

            if holiday.get("day_type") == "half_day":

                errors.append(
                    f"years[year={year}]: half_day_policy="
                    "'not_decided' iken verified=true bir yılda "
                    "day_type='half_day' girdisi var "
                    f"({holiday.get('date')!r}) - politika kararı "
                    "alınmadan yarım gün doğrulanmış sayılamaz."
                )

    return errors


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_holiday_calendar(calendar=None, raise_on_error=False):

    if calendar is None:

        calendar = load_calendar()

    errors = []

    warnings = []

    # ========================================================
    # SCHEMA
    # ========================================================

    errors.extend(validate_schema(calendar))

    # Schema başarısızsa (örn. gerekli anahtar eksik) iç tutarlılık
    # kontrolleri KeyError riski taşır - corpus_policy_validator.py'nin
    # KENDİ validate_corpus_policy() emsaliyle AYNI fail-fast deseni.
    if not errors:

        errors.extend(validate_year_ordering_and_uniqueness(calendar))

        errors.extend(validate_holiday_ordering_and_year_match(calendar))

        errors.extend(validate_source_ref_index_bounds(calendar))

        errors.extend(validate_verified_year_provenance(calendar))

        errors.extend(validate_half_day_policy_consistency(calendar))

    errors = list(dict.fromkeys(errors))

    warnings = list(dict.fromkeys(warnings))

    valid = len(errors) == 0

    verified_year_count = len(
        [
            entry
            for entry in (calendar.get("years") or [])
            if isinstance(entry, dict) and entry.get("verified") is True
        ]
    )

    result = {
        "valid": valid,
        "validator_version": HOLIDAY_CALENDAR_VALIDATOR_VERSION,
        "calendar_id": calendar.get("calendar_id"),
        "calendar_version": calendar.get("calendar_version"),
        "year_count": len(calendar.get("years") or []),
        "verified_year_count": verified_year_count,
        "errors": errors,
        "warnings": warnings,
    }

    if raise_on_error and errors:

        raise HolidayCalendarValidationError(
            "HOLIDAY CALENDAR VALIDATOR V1: FAIL\n\n- "
            + "\n- ".join(errors)
        )

    return result


# ============================================================
# TEST FIXTURE
# ============================================================

def create_valid_fixture():

    return {
        "schema_version": 1,
        "calendar_id": "tr_official_holiday_calendar_v1",
        "calendar_version": 1,
        "effective_from": "2026-01-01",
        "jurisdiction": "TR",
        "weekend_policy": {
            "non_working_weekdays": [5, 6],
            "notes": None,
        },
        "half_day_policy": "not_decided",
        "years": [
            {
                "year": 2026,
                "verified": True,
                "verification_ref": "fixture_verification_ref_2026",
                "source_refs": [
                    {
                        "source_kind": "fixture",
                        "citation": "Fixture citation 2026.",
                        "url": None,
                    },
                ],
                "holidays": [
                    {
                        "date": "2026-03-12",
                        "name": "Fixture Holiday 2026-03-12",
                        "kind": "national",
                        "day_type": "full_day",
                        "source_ref_index": 0,
                        "notes": None,
                    },
                ],
            },
            {
                "year": 2027,
                "verified": False,
                "verification_ref": None,
                "source_refs": [],
                "holidays": [],
            },
        ],
        "governance": {
            "change_approval": "Fixture change approval rule.",
            "verification_authority": "Fixture verification authority.",
            "notes": None,
        },
        "notes": "Holiday Calendar Validator V1 self-test fixture. Gerçek resmi tatil takvimi değildir.",
    }


# ============================================================
# SELF TEST
# ============================================================

def run_self_test():

    print()
    print("======================================")
    print(" VERGİ AI - HOLIDAY CALENDAR VALIDATOR V1")
    print("======================================")

    # ========================================================
    # T01 SCHEMA FILE EXISTS
    # ========================================================

    assert HOLIDAY_CALENDAR_SCHEMA_PATH.exists()

    load_json(HOLIDAY_CALENDAR_SCHEMA_PATH)

    print("T01 Holiday calendar schema load: PASS")

    # ========================================================
    # T02 VALID FIXTURE (in-memory)
    # ========================================================

    fixture = create_valid_fixture()

    result = validate_holiday_calendar(calendar=fixture)

    if not result["valid"]:

        for error in result["errors"]:

            print("-", error)

    assert result["valid"] is True

    print("T02 Valid fixture calendar: PASS")

    # ========================================================
    # T03 INDEPENDENT GOLDEN FIXTURE (totoloji kırıcı - fixture'ın
    # kendi yapısına GÜVENMEYEN, elle yazılmış, tamamen boş-yıllı
    # minimal ikinci bir fixture).
    # ========================================================

    golden = {
        "schema_version": 1,
        "calendar_id": "tr_official_holiday_calendar_v1",
        "calendar_version": 1,
        "effective_from": "2024-01-01",
        "jurisdiction": "TR",
        "weekend_policy": {"non_working_weekdays": [5, 6], "notes": None},
        "half_day_policy": "counts_as_working_day",
        "years": [],
        "governance": {
            "change_approval": "golden",
            "verification_authority": "golden",
            "notes": None,
        },
        "notes": None,
    }

    golden_result = validate_holiday_calendar(calendar=golden)

    assert golden_result["valid"] is True, golden_result["errors"]

    print("T03 Independent golden fixture (empty years[]): PASS")

    # ========================================================
    # T04 REAL, REPO-COMMITTED CALENDAR VALIDATES CLEANLY
    # ========================================================

    real_result = validate_holiday_calendar()

    if not real_result["valid"]:

        for error in real_result["errors"]:

            print("-", error)

    assert real_result["valid"] is True

    print("T04 Real committed holiday_calendar.json: PASS")

    # ========================================================
    # T05 HOLIDAY DATE / YEAR MISMATCH REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["holidays"][0]["date"] = "2025-03-12"

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T05 Holiday date/year mismatch blocked: PASS")

    # ========================================================
    # T06 DUPLICATE year REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"].append(copy.deepcopy(broken["years"][0]))

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T06 Duplicate years[].year blocked: PASS")

    # ========================================================
    # T07 DUPLICATE holiday date (within a year) REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["holidays"].append(
        copy.deepcopy(broken["years"][0]["holidays"][0])
    )

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T07 Duplicate holiday date within a year blocked: PASS")

    # ========================================================
    # T08 verified=true WITHOUT source_refs REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["source_refs"] = []

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T08 verified=true without source_refs blocked: PASS")

    # ========================================================
    # T09 verified=true WITH blank verification_ref REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["verification_ref"] = "   "

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T09 verified=true with blank verification_ref blocked: PASS")

    # ========================================================
    # T09b verified=true WITH verification_ref=None REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["verification_ref"] = None

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T09b verified=true with verification_ref=null blocked: PASS")

    # ========================================================
    # T10 weekend_policy != [5, 6] REJECTED (schema const)
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["weekend_policy"]["non_working_weekdays"] = [6, 0]

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T10 weekend_policy.non_working_weekdays != [5,6] blocked: PASS")

    # ========================================================
    # T11 UNKNOWN kind / day_type REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["holidays"][0]["kind"] = "made_up_kind"

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T11 Unknown holiday kind blocked: PASS")

    broken = copy.deepcopy(fixture)

    broken["years"][0]["holidays"][0]["day_type"] = "made_up_day_type"

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T11b Unknown holiday day_type blocked: PASS")

    # ========================================================
    # T12 additionalProperties:false AT ROOT
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["unknown_top_level_field"] = "nope"

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T12 Unknown top-level field blocked (root additionalProperties:false): PASS")

    # ========================================================
    # T13 additionalProperties:false INSIDE year_entry / holiday_entry
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["unknown_nested_field"] = "nope"

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T13a Unknown nested field blocked (year_entry additionalProperties:false): PASS")

    broken = copy.deepcopy(fixture)

    broken["years"][0]["holidays"][0]["unknown_nested_field"] = "nope"

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T13b Unknown nested field blocked (holiday_entry additionalProperties:false): PASS")

    # ========================================================
    # T14 source_ref_index OUT OF BOUNDS REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["holidays"][0]["source_ref_index"] = 5

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T14 source_ref_index out of bounds blocked: PASS")

    # ========================================================
    # T15 half_day + not_decided REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["holidays"][0]["day_type"] = "half_day"

    assert broken["half_day_policy"] == "not_decided"

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T15 half_day entry under half_day_policy='not_decided' (verified year) blocked: PASS")

    # ========================================================
    # T15b half_day + counts_as_holiday POSITIVE CONTROL (allowed)
    # ========================================================

    allowed = copy.deepcopy(fixture)

    allowed["half_day_policy"] = "counts_as_holiday"

    allowed["years"][0]["holidays"][0]["day_type"] = "half_day"

    result = validate_holiday_calendar(calendar=allowed)

    assert result["valid"] is True, result["errors"]

    print("T15b half_day entry under half_day_policy='counts_as_holiday' (verified year) allowed: PASS")

    # ========================================================
    # T16 schema_version != 1 REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["schema_version"] = 2

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T16 schema_version != 1 blocked: PASS")

    # ========================================================
    # T17 calendar_version < 1 REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["calendar_version"] = 0

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T17 calendar_version < 1 blocked: PASS")

    # ========================================================
    # T18 years[] NOT ASCENDING REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"] = list(reversed(broken["years"]))

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T18 years[] not ascending blocked: PASS")

    # ========================================================
    # T19 holidays[] (within a year) NOT ASCENDING REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["years"][0]["holidays"].append(
        {
            "date": "2026-01-01",
            "name": "Earlier date, appended after",
            "kind": "national",
            "day_type": "full_day",
            "source_ref_index": 0,
            "notes": None,
        }
    )

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    print("T19 holidays[] (within a year) not ascending blocked: PASS")

    # ========================================================
    # T20 DISK LOAD PATH - tempdir-isolated, real data/ untouched
    # ========================================================

    with tempfile.TemporaryDirectory() as tmp:

        tmp_path = Path(tmp) / "disk_fixture_holiday_calendar.json"

        with open(tmp_path, "w", encoding="utf-8") as file:

            json.dump(fixture, file, ensure_ascii=False)

        loaded = load_calendar(tmp_path)

        disk_result = validate_holiday_calendar(calendar=loaded)

        assert disk_result["valid"] is True, disk_result["errors"]

    print("T20 Disk-loaded fixture (tempdir-isolated) validates: PASS")

    # ========================================================
    # T21 MISSING CALENDAR FILE FAILS CLOSED
    # ========================================================

    with tempfile.TemporaryDirectory() as tmp:

        missing_path = Path(tmp) / "does_not_exist.json"

        try:

            load_calendar(missing_path)

            raised = False

        except FileNotFoundError:

            raised = True

        assert raised is True

    print("T21 Missing calendar file fails closed (FileNotFoundError): PASS")

    # ========================================================
    # T22 raise_on_error=True RAISES HolidayCalendarValidationError
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["schema_version"] = 2

    try:

        validate_holiday_calendar(calendar=broken, raise_on_error=True)

        raised = False

    except HolidayCalendarValidationError:

        raised = True

    assert raised is True

    print("T22 raise_on_error=True raises HolidayCalendarValidationError: PASS")

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print("Calendar:", real_result["calendar_id"])
    print("Year count:", real_result["year_count"])
    print("Verified year count:", real_result["verified_year_count"])
    print()
    print("======================================")
    print(" HOLIDAY CALENDAR VALIDATOR V1: 26/26 PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Vergi AI Holiday Calendar Validator V1"
    )

    parser.add_argument(
        "--calendar",
        dest="calendar_path",
        default=None,
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    args = parser.parse_args()

    if args.self_test or args.calendar_path is None:

        run_self_test()

        return

    print()
    print("======================================")
    print(" VERGİ AI - HOLIDAY CALENDAR VALIDATOR V1")
    print("======================================")

    try:

        calendar = load_calendar(Path(args.calendar_path))

        result = validate_holiday_calendar(calendar=calendar, raise_on_error=False)

    except Exception as error:

        print()
        print("VALIDATION ERROR")
        print(error)
        print()
        print("======================================")
        print(" HOLIDAY CALENDAR VALIDATOR V1: FAIL")
        print("======================================")

        sys.exit(1)

    print()
    print("Calendar:", result["calendar_id"])
    print("Year count:", result["year_count"])
    print("Verified year count:", result["verified_year_count"])

    if result["errors"]:

        print()
        print("Errors:")

        for error in result["errors"]:

            print("-", error)

    print()
    print("======================================")

    if result["valid"]:

        print(" HOLIDAY CALENDAR VALIDATOR V1: PASS")

    else:

        print(" HOLIDAY CALENDAR VALIDATOR V1: FAIL")

        sys.exit(1)

    print("======================================")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()
