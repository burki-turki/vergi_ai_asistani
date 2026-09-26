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
# 7. (PILOT READINESS ADIM 6) verified:true her yıl, takvimin kendi
#    verifications[] dizisindeki bir avukat doğrulama kaydına
#    (HC-LAWYER-VERIFY-v1, imzalı dosya SHA-256'ına yapısal bağlı)
#    çözülmeli; kapsam/karar/politika/digest bağları tutmalı
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
import hashlib
import json
import re
import sys
import tempfile

from datetime import date, timedelta
from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


# ============================================================
# VERSION
# ============================================================

HOLIDAY_CALENDAR_VALIDATOR_VERSION = "3"


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
# CANONICAL OBSERVANCE REGISTRY - PHASE A (REV4.1 kanit kapanisi).
#
# Bu registry, `observances[]` modelinin TEK anlamsal dogruluk
# kaynagidir - `data/holiday_calendar.schema.json`'daki
# `observance_id` enum'u yalniz SEKIL (hangi 17 deger gecerli)
# doğrular; bir observance_id'nin KENDI kind/day_type/
# legal_basis_ref/family/sequence_position'i JSON Schema'nin
# ifade edemedigi bir cross-field kuraldir (bu dosyanin kendi
# header yorumunun zaten belirttigi ilke), bu yuzden burada,
# Python seviyesinde, TEK bir yerde tutulur.
#
# REV4.1 tasarım paketindeki `canonical_registry.py`'nin (bagimsiz
# incelemeden LOCK-READY gecmis) FIXED_REGISTRY + RELIGIOUS_REGISTRY
# sozluklerinin production'a tasinmis halidir - degerler BIREBIR
# aynidir, yalniz bu dosyanin kendi konvansiyonuna (module-level
# sabit + fonksiyonlar) tasinmistir. Ayri bir dosya/registry
# ACILMAMISTIR - tek tuketici bu modul oldugu icin (Phase B'de bir
# "builder" script'i YOKTUR, veri elle/avukat onayiyla girilir).
# ============================================================

CANONICAL_OBSERVANCE_REGISTRY = {

    # --- 8 sabit (gunes takvimi) ulusal gozlem ---
    "yilbasi": {
        "kind": "national", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/C",
        "fixed_month_day": "01-01", "family": None, "sequence_position": None,
    },
    "ulusal_egemenlik_cocuk_bayrami": {
        "kind": "national", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/A.1",
        "fixed_month_day": "04-23", "family": None, "sequence_position": None,
    },
    "emek_dayanisma_gunu": {
        "kind": "national", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/C",
        "fixed_month_day": "05-01", "family": None, "sequence_position": None,
    },
    "ataturk_anma_genclik_spor_bayrami": {
        "kind": "national", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/A.2",
        "fixed_month_day": "05-19", "family": None, "sequence_position": None,
    },
    "demokrasi_milli_birlik_gunu": {
        "kind": "national", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/C",
        "fixed_month_day": "07-15", "family": None, "sequence_position": None,
    },
    "zafer_bayrami": {
        "kind": "national", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/A.3",
        "fixed_month_day": "08-30", "family": None, "sequence_position": None,
    },
    "cumhuriyet_bayrami_arefe": {
        "kind": "national", "day_type": "half_day",
        "legal_basis_ref": "2429 sayılı Kanun m.1",
        "fixed_month_day": "10-28", "family": None, "sequence_position": None,
    },
    "cumhuriyet_bayrami": {
        "kind": "national", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.1",
        "fixed_month_day": "10-29", "family": None, "sequence_position": None,
    },

    # --- 9 dini (kamer takvimi) gozlem, iki aile ---
    "ramazan_bayrami_arefe": {
        "kind": "religious", "day_type": "half_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/B.1",
        "fixed_month_day": None, "family": "ramazan", "sequence_position": 0,
    },
    "ramazan_bayrami_gun1": {
        "kind": "religious", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/B.1",
        "fixed_month_day": None, "family": "ramazan", "sequence_position": 1,
    },
    "ramazan_bayrami_gun2": {
        "kind": "religious", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/B.1",
        "fixed_month_day": None, "family": "ramazan", "sequence_position": 2,
    },
    "ramazan_bayrami_gun3": {
        "kind": "religious", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/B.1",
        "fixed_month_day": None, "family": "ramazan", "sequence_position": 3,
    },
    "kurban_bayrami_arefe": {
        "kind": "religious", "day_type": "half_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/B.2",
        "fixed_month_day": None, "family": "kurban", "sequence_position": 0,
    },
    "kurban_bayrami_gun1": {
        "kind": "religious", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/B.2",
        "fixed_month_day": None, "family": "kurban", "sequence_position": 1,
    },
    "kurban_bayrami_gun2": {
        "kind": "religious", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/B.2",
        "fixed_month_day": None, "family": "kurban", "sequence_position": 2,
    },
    "kurban_bayrami_gun3": {
        "kind": "religious", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/B.2",
        "fixed_month_day": None, "family": "kurban", "sequence_position": 3,
    },
    "kurban_bayrami_gun4": {
        "kind": "religious", "day_type": "full_day",
        "legal_basis_ref": "2429 sayılı Kanun m.2/B.2",
        "fixed_month_day": None, "family": "kurban", "sequence_position": 4,
    },
}

assert len(CANONICAL_OBSERVANCE_REGISTRY) == 17

CANONICAL_OBSERVANCE_FAMILY_IDS = {
    "ramazan": sorted(
        (oid for oid, reg in CANONICAL_OBSERVANCE_REGISTRY.items() if reg["family"] == "ramazan"),
        key=lambda oid: CANONICAL_OBSERVANCE_REGISTRY[oid]["sequence_position"],
    ),
    "kurban": sorted(
        (oid for oid, reg in CANONICAL_OBSERVANCE_REGISTRY.items() if reg["family"] == "kurban"),
        key=lambda oid: CANONICAL_OBSERVANCE_REGISTRY[oid]["sequence_position"],
    ),
}


# ============================================================
# REV4.1 EXACT RELIGIOUS BLOCK-COUNT CONTRACT - F1 REMEDIATION
# (Phase A bağımsız incelemesi, C.14 / çok-bloklu tamlık).
#
# Kaynak: REV4.1 tasarım paketi `canonical_registry.py`
# `EXPECTED_BLOCK_COUNT` (bağımsız incelemeden LOCK-READY geçmiş,
# paketin kendi astronomik kaynak gözlemlerine karşı doğrulanmış).
# Değerler BİREBİR taşınmıştır: 2024-2035 destek yıllarında Ramazan
# Bayramı normalde 1 blok, 2033'te 2 blok; Kurban Bayramı her yıl
# 1 blok. Bu tablo YALNIZ destek yılları için tanımlıdır - aralık
# DIŞINDAKİ, `verified:true` olup observances[] kullanan bir yıl
# için sessiz tahmin YAPILMAZ; `validate_verified_year_observance_
# completeness` fail-closed hata üretir. Tabloyu genişletmek avukat
# doğrulamalı girdi gerektirir (Pilot Readiness Adım 6).
# ============================================================

REV41_BLOCK_COUNT_SUPPORTED_YEARS = (
    2024, 2025, 2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035,
)

REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT = {
    "ramazan": {
        2024: 1, 2025: 1, 2026: 1, 2027: 1, 2028: 1, 2029: 1,
        2030: 1, 2031: 1, 2032: 1, 2033: 2, 2034: 1, 2035: 1,
    },
    "kurban": {
        2024: 1, 2025: 1, 2026: 1, 2027: 1, 2028: 1, 2029: 1,
        2030: 1, 2031: 1, 2032: 1, 2033: 1, 2034: 1, 2035: 1,
    },
}

assert len(REV41_BLOCK_COUNT_SUPPORTED_YEARS) == 12
assert set(REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT) == set(CANONICAL_OBSERVANCE_FAMILY_IDS)
assert all(
    tuple(sorted(table)) == REV41_BLOCK_COUNT_SUPPORTED_YEARS
    for table in REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT.values()
)
assert REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT["ramazan"][2033] == 2


# ============================================================
# OBSERVANCE REGISTRY CROSS-CHECK + DERIVED-FIELD CONSISTENCY -
# PHASE A (REV4.1 kanit kapanisi). Koşulsuz: bir yılın verified
# durumundan bağımsız olarak, var olan HERHANGİ bir observances[]
# girdisi her zaman kayıt/registry/block_index/derivation
# disiplinine uymak ZORUNDADIR (yarım-doğru veri, çalışma-halinde
# olsa bile, HİÇBİR ZAMAN kabul edilmez - `validate_year_ordering_
# and_uniqueness` / `validate_holiday_ordering_and_year_match` ile
# AYNI, bu dosyanın zaten var olan koşulsuz-kontrol desenidir).
# ============================================================

def validate_observance_registry_consistency(calendar):

    errors = []

    for year_entry in calendar.get("years") or []:

        if not isinstance(year_entry, dict):

            continue

        year = year_entry.get("year")

        block_members = {}  # (family, block_index) -> {sequence_position: [(date, oid), ...]}

        # F1 REMEDIATION (Phase A bağımsız incelemesi, C.14 cross-entry
        # duplicate fail-open): yıl-içi occurrence sayaçları. Ulusal
        # anahtar = observance_id (yılda TAM 1 kez); dinî anahtar =
        # (family, block_index, observance_id) (aynı blok içinde TAM 1
        # kez - aynı id'nin FARKLI block_index değerlerinde bulunması
        # meşrudur, ör. 2033'ün iki Ramazan bloğu). KOŞULSUZ: bir
        # cross-entry duplicate yapısal kusurdur, yıl verified:false
        # olsa bile reddedilir. Hiçbir sözlük last-wins ÜZERİNE YAZMAZ.

        national_occurrences = {}  # observance_id -> [date, ...]

        religious_occurrences = {}  # (family, block_index, observance_id) -> [date, ...]

        for holiday in year_entry.get("holidays") or []:

            if not isinstance(holiday, dict):

                continue

            date_value = holiday.get("date")

            observances = holiday.get("observances")

            if not observances:

                continue

            oid_list = [o.get("observance_id") for o in observances if isinstance(o, dict)]

            if len(oid_list) != len(set(oid_list)):

                errors.append(
                    f"years[year={year}].holidays[date={date_value}]: "
                    f"duplicate observance_id within same entry ({oid_list})"
                )

            for observance in observances:

                if not isinstance(observance, dict):

                    continue

                oid = observance.get("observance_id")

                reg = CANONICAL_OBSERVANCE_REGISTRY.get(oid)

                if reg is None:

                    # schema enum zaten reddeder - burada yalnizca
                    # defense-in-depth (fail-fast bloğu atlanmışsa).
                    errors.append(
                        f"years[year={year}].holidays[date={date_value}]: "
                        f"unknown observance_id {oid!r}"
                    )
                    continue

                if observance.get("kind") != reg["kind"]:

                    errors.append(
                        f"years[year={year}].holidays[date={date_value}]/{oid}: "
                        f"kind={observance.get('kind')!r} != registry expected {reg['kind']!r}"
                    )

                if observance.get("day_type") != reg["day_type"]:

                    errors.append(
                        f"years[year={year}].holidays[date={date_value}]/{oid}: "
                        f"day_type={observance.get('day_type')!r} != registry expected {reg['day_type']!r}"
                    )

                if observance.get("legal_basis_ref") != reg["legal_basis_ref"]:

                    errors.append(
                        f"years[year={year}].holidays[date={date_value}]/{oid}: "
                        f"legal_basis_ref={observance.get('legal_basis_ref')!r} != registry expected"
                    )

                block_index = observance.get("block_index")

                if reg["family"] is None:

                    national_occurrences.setdefault(oid, []).append(date_value)

                    if block_index is not None:

                        errors.append(
                            f"years[year={year}].holidays[date={date_value}]/{oid}: "
                            f"block_index must be null for a national observance, got {block_index!r}"
                        )

                else:

                    is_positive_int = (
                        isinstance(block_index, int)
                        and not isinstance(block_index, bool)
                        and block_index >= 1
                    )

                    if not is_positive_int:

                        errors.append(
                            f"years[year={year}].holidays[date={date_value}]/{oid}: "
                            f"block_index must be a positive integer for a religious observance, "
                            f"got {block_index!r}"
                        )

                    else:

                        key = (reg["family"], block_index)

                        block_members.setdefault(key, {}).setdefault(
                            reg["sequence_position"], []
                        ).append((date_value, oid))

                        religious_occurrences.setdefault(
                            (reg["family"], block_index, oid), []
                        ).append(date_value)

            # --- top-level day_type / kind derivation consistency ---
            # `name` KASITLI OLARAK burada DENETLENMEZ - production'da
            # `name` avukat tarafından girilen, insan-okur bir Turkce
            # tatil adıdır (ör. "Kurban Bayramı 4. Gün"), REV4.1'in
            # proposal-generator'ının kendi ic-kullanim observance_id
            # join stringiyle (`"kurban_bayrami_gun4 + ..."`) BİREBİR
            # eşleşmesi ZORUNLU DEĞİLDİR - bu bilinçli bir Phase A
            # gevşetmesidir (bkz. entegrasyon raporu Bölüm E).
            #
            # `day_type`/`kind` İSE mekanik olarak türetilmiş KALMAK
            # ZORUNDADIR: `derive_effective_holiday_calendar()`
            # (src/deadline_calculator.py) VE bu dosyanın KENDİ
            # `validate_half_day_policy_consistency()`'si HÂLÂ düz
            # (flat) `day_type` alanını okur - bu iki tüketicinin doğru
            # çalışması için üst-seviye alan HER ZAMAN observances[]
            # birleşimiyle (full_day kazanır) tutarlı KALMALIDIR.

            observance_day_types = {
                o.get("day_type") for o in observances if isinstance(o, dict)
            }

            derived_day_type = (
                "full_day" if "full_day" in observance_day_types else "half_day"
            )

            if holiday.get("day_type") != derived_day_type:

                errors.append(
                    f"years[year={year}].holidays[date={date_value}]: "
                    f"top-level day_type={holiday.get('day_type')!r} inconsistent with "
                    f"observances[] merge (derived={derived_day_type!r})"
                )

            observance_kinds = {
                o.get("kind") for o in observances if isinstance(o, dict)
            }

            derived_kind = "national" if "national" in observance_kinds else "religious"

            if holiday.get("kind") != derived_kind:

                errors.append(
                    f"years[year={year}].holidays[date={date_value}]: "
                    f"top-level kind={holiday.get('kind')!r} inconsistent with "
                    f"observances[] merge (derived={derived_kind!r})"
                )

        # --- F1 REMEDIATION: cross-entry duplicate observance identities ---
        # Deterministik: aile/observance_id sırasına göre, tarih listesi
        # sıralı. Ulusal: yılda tam 1 kez. Dinî: (family, block_index)
        # başına tam 1 kez. Bu, aşağıdaki completeness kontrolünün
        # ">1 occurrence" durumunu YENİDEN raporlamadığı TEK yerdir
        # (iki fonksiyon örtüşmeyen sorumluluklar taşır).

        for oid, dates in sorted(national_occurrences.items()):

            if len(dates) > 1:

                errors.append(
                    f"years[year={year}]: national observance {oid!r} occurs {len(dates)} times "
                    f"across entries (dates {sorted(dates, key=str)}) - must occur exactly once per year"
                )

        for (family, block_index, oid), dates in sorted(religious_occurrences.items()):

            if len(dates) > 1:

                errors.append(
                    f"years[year={year}]: {family} block {block_index}: religious observance {oid!r} "
                    f"occurs {len(dates)} times across entries (dates {sorted(dates, key=str)}) "
                    "- must occur exactly once per block"
                )

        # --- block_index contiguity per (family, block_index) within this year ---
        # Koşulsuz genel kural: HANGİ block_index'ler kullanılıyorsa,
        # o küme her aile için 1..N (N = kullanılan farklı blok sayısı)
        # boşluksuz olmak ZORUNDADIR. Belirli bir yıl için "tam olarak
        # kaç blok olmalı" sorusu bu koşulsuz kontrolün işi DEĞİLDİR -
        # o, yalnız verified yıllar için, REV4.1'in doğrulanmış exact
        # block-count sözleşmesiyle (`REV41_EXPECTED_RELIGIOUS_BLOCK_
        # COUNT`) `validate_verified_year_observance_completeness`
        # içinde uygulanır (F1 remediasyonu).

        block_indices_by_family = {}

        for (family, block_index) in block_members.keys():

            block_indices_by_family.setdefault(family, set()).add(block_index)

        for family, indices in block_indices_by_family.items():

            sorted_indices = sorted(indices)

            if sorted_indices != list(range(1, len(sorted_indices) + 1)):

                errors.append(
                    f"years[year={year}]: {family} block_index values not a contiguous "
                    f"1..N sequence: {sorted_indices}"
                )

        # --- within each block: present members must be in exact,
        #     1-day-apart sequence_position order (missing members are
        #     a COMPLETENESS concern, handled separately and only for
        #     verified years by validate_verified_year_observance_
        #     completeness - a partial, in-progress block is not
        #     itself an ordering error as long as what IS present is
        #     correctly ordered). ---

        for (family, block_index), positions in block_members.items():

            # F1 REMEDIATION: birden fazla üyeli (duplicate) pozisyonlar
            # yukarıda zaten cross-entry duplicate olarak raporlandı;
            # ardışık-gün kontrolü yalnız TEK üyeli komşu pozisyonlar
            # arasında yapılır - bir duplicate, bloğun geri kalanının
            # kontrolünü ASLA bastırmaz.

            ordered_present = sorted(
                (position, members[0])
                for position, members in positions.items()
                if len(members) == 1
            )

            for i in range(1, len(ordered_present)):

                prev_pos, (prev_date, prev_oid) = ordered_present[i - 1]

                cur_pos, (cur_date, cur_oid) = ordered_present[i]

                if prev_pos + 1 != cur_pos:

                    continue  # a gap - a completeness concern, not an ordering error here

                try:

                    delta = (
                        date.fromisoformat(cur_date) - date.fromisoformat(prev_date)
                    ).days

                except (TypeError, ValueError):

                    continue  # malformed date - already reported by validate_schema

                if delta != 1:

                    errors.append(
                        f"years[year={year}]: {family} block {block_index}: {cur_oid} "
                        f"({cur_date}) is {delta} day(s) after {prev_oid} ({prev_date}) "
                        "- expected exactly 1 day after, in sequence_position order"
                    )

    return errors


# ============================================================
# VERIFIED YEAR OBSERVANCE COMPLETENESS - PHASE A (REV4.1 kanit
# kapanisi). GATED: yalnız `verified is True` OLAN VE observances[]
# modelini EN AZ BİR holiday girdisinde kullanan yıllar için çalışır
# (`validate_verified_year_provenance` ile AYNI "yalnız verified"
# gate deseni). Saf-legacy (observances[] hiç kullanmayan) verified
# bir yıl bu kontrolün KAPSAMI DIŞINDADIR - mevcut legacy structural
# kontroller (year/date ordering, source_ref_index, vb.) onu zaten
# kapsar; bu yeni kontrol yalnız observances[] modelini BENİMSEMİŞ
# yıllara EK bir tamlık şartı getirir.
#
# F1 REMEDIATION (Phase A bağımsız incelemesi, çok-bloklu tamlık
# fail-open): eski `seen_oids[oid]` last-wins sözlüğü KALDIRILDI - o
# sözlük iki bloklu bir yılda (ör. 2033 Ramazan) blok 2'nin blok 1'in
# eksiğini MASKELEMESİNE yol açıyordu. Artık her sabit gözlem için
# occurrence LİSTESİ, her (family, block_index) için sequence_position
# -> occurrence LİSTESİ tutulur; tamlık HER blok için AYRI AYRI
# değerlendirilir. Sorumluluk ayrımı: ">1 occurrence" (duplicate)
# `validate_observance_registry_consistency` tarafından KOŞULSUZ
# raporlanır ve burada YENİDEN raporlanmaz; bu fonksiyon eksik (0)
# üyeyi, her occurrence'ın doğru ay-gününü, aile başına en az bir tam
# blok şartını ve REV4.1'in exact block-count sözleşmesini
# (`REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT`, yalnız 2024-2035; aralık
# dışı verified yıl fail-closed hata) uygular.
# ============================================================

def validate_verified_year_observance_completeness(calendar):

    errors = []

    for year_entry in calendar.get("years") or []:

        if not isinstance(year_entry, dict):

            continue

        if year_entry.get("verified") is not True:

            continue

        year = year_entry.get("year")

        holidays = year_entry.get("holidays") or []

        uses_observances = any(
            isinstance(h, dict) and h.get("observances")
            for h in holidays
        )

        if not uses_observances:

            continue

        fixed_occurrences = {}  # observance_id -> [date, ...]

        block_positions = {}  # (family, block_index) -> {sequence_position: [date, ...]}

        for holiday in holidays:

            if not isinstance(holiday, dict):

                continue

            date_value = holiday.get("date")

            for observance in holiday.get("observances") or []:

                if not isinstance(observance, dict):

                    continue

                oid = observance.get("observance_id")

                reg = CANONICAL_OBSERVANCE_REGISTRY.get(oid)

                if reg is None:

                    continue  # unknown id - registry-consistency (and schema) report it

                if reg["family"] is None:

                    fixed_occurrences.setdefault(oid, []).append(date_value)

                    continue

                block_index = observance.get("block_index")

                is_positive_int = (
                    isinstance(block_index, int)
                    and not isinstance(block_index, bool)
                    and block_index >= 1
                )

                if not is_positive_int:

                    continue  # malformed block_index - registry-consistency reports it

                block_positions.setdefault(
                    (reg["family"], block_index), {}
                ).setdefault(reg["sequence_position"], []).append(date_value)

        # --- 8 fixed: present (0 -> missing) and EVERY occurrence at the
        #     correct month-day. ">1 occurrence" is registry-consistency's
        #     responsibility and is NOT re-reported here. ---

        for oid, reg in CANONICAL_OBSERVANCE_REGISTRY.items():

            if reg["family"] is not None:

                continue

            occurrences = fixed_occurrences.get(oid) or []

            if not occurrences:

                errors.append(
                    f"years[year={year}] (verified): missing fixed observance {oid!r}"
                )
                continue

            expected_date = f"{year}-{reg['fixed_month_day']}"

            for actual_date in occurrences:

                if actual_date != expected_date:

                    errors.append(
                        f"years[year={year}] (verified): {oid!r} expected at {expected_date}, "
                        f"found at {actual_date!r}"
                    )

        # --- REV4.1 exact block-count contract: defined ONLY for the
        #     supported years; a verified observances[]-using year outside
        #     the contract is refused (no silent guess). ---

        year_in_contract = year in REV41_BLOCK_COUNT_SUPPORTED_YEARS

        if not year_in_contract:

            errors.append(
                f"years[year={year}] (verified): no exact religious block-count contract for "
                f"year {year!r} (REV4.1 contract covers "
                f"{REV41_BLOCK_COUNT_SUPPORTED_YEARS[0]}-{REV41_BLOCK_COUNT_SUPPORTED_YEARS[-1]} only) "
                "- refusing to guess; extend the contract with lawyer-verified input"
            )

        # --- religious: per-block completeness (EVERY block, each
        #     canonical member present - a complete block can never mask
        #     an incomplete sibling), then exact block count per family ---

        for family, family_ids in CANONICAL_OBSERVANCE_FAMILY_IDS.items():

            block_indices = sorted(
                block_index
                for (block_family, block_index) in block_positions.keys()
                if block_family == family
            )

            for block_index in block_indices:

                positions = block_positions[(family, block_index)]

                for oid in family_ids:

                    reg = CANONICAL_OBSERVANCE_REGISTRY[oid]

                    if not positions.get(reg["sequence_position"]):

                        errors.append(
                            f"years[year={year}] (verified): {family} block {block_index} "
                            f"is missing {oid!r} (sequence_position {reg['sequence_position']})"
                        )

            if year_in_contract:

                expected_count = REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT[family][year]

                if len(block_indices) != expected_count:

                    errors.append(
                        f"years[year={year}] (verified): {family} expected exactly "
                        f"{expected_count} block(s) per REV4.1 contract, found "
                        f"{len(block_indices)} {block_indices}"
                    )

    return errors


# ============================================================
# LAWYER VERIFICATION RECORD BINDING - PILOT READINESS ADIM 6
# (avukat doğrulaması, belge sürümü HC-LAWYER-VERIFY-v1).
#
# Bir yılın `verified: true` olması TEK BAŞINA yeterli DEĞİLDİR: her
# verified yılın `verification_ref`'i, takvimin KENDİ `verifications[]`
# dizisindeki TAM BİR kayda çözülmek ZORUNDADIR ve o kayıt:
#
#   1. `verification_ref` biçimi HC-LAWYER-VERIFY-v1-<from>-<to>-<sha16>;
#      <sha16> == signed_artifact.sha256[:16] (imzalı dosyaya yapısal
#      bağ), <from>/<to> == scope.year_from/year_to;
#   2. yılı kapsar: year ∈ scope.accepted_years VE
#      scope.year_decisions[<year>] == "KABUL";
#   3. kullanılabilir bir nihai karar taşır (KABUL / KISMEN_KABUL);
#   4. takvimin `half_day_policy`'si (not_decided DEĞİLSE) kaydın
#      `half_day_policy_decision`'ıyla BİREBİR aynıdır;
#   5. `verified_content_digest`, o kayda bağlı verified yılların
#      (`year` + `holidays[]` OLDUĞU GİBİ) canonical JSON SHA-256'ıyla
#      BİREBİR aynıdır - KAPSAM kontrolü: doğrulanmış bir yılda tek bir
#      tarih/ad/gün-türü/gözlem değişikliği bile kaydı geçersiz kılar
#      (fail-closed; yeniden avukat doğrulaması gerekir).
#
# İmzalı dosyanın KENDİSİ repoda TUTULMAZ (git'e girmez; sertifika
# içeriği hiçbir yere yazılmaz) - yalnız SHA-256/boyut/dosya adı
# kaydedilir. Fiziksel bayt doğrulaması (`verify_signed_artifact()`)
# YALNIZ bir dosya yolu VERİLDİĞİNDE yapılır (CLI
# `--verify-signed-artifact` veya `validate_holiday_calendar(signed_
# artifact_paths=...)`); runtime yüklemesi (`deadline_calculator.
# load_holiday_calendar()`) git-governed kayıt + yukarıdaki yapısal
# bağlara dayanır. Ortam-değişkenli bir aç/kapa anahtarı YOKTUR.
# ============================================================

VERIFICATION_REF_PATTERN = re.compile(
    r"^HC-LAWYER-VERIFY-v1-(?P<year_from>[0-9]{4})-(?P<year_to>[0-9]{4})-(?P<sha16>[0-9a-f]{16})$"
)

USABLE_FINAL_DECISIONS = frozenset({"KABUL", "KISMEN_KABUL"})

DECIDED_HALF_DAY_POLICIES = frozenset(
    {
        "counts_as_holiday",
        "counts_as_working_day",
        "needs_review_if_deadline_day",
    }
)


def _canonical_json_bytes(payload):

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _years_bound_to_record(calendar, verification_ref):
    """Kayda BAĞLI yıllar: `verified is True` VE `verification_ref ==
    ref` (identity, truthiness DEĞİL)."""

    return [
        entry
        for entry in (calendar.get("years") or [])
        if isinstance(entry, dict)
        and entry.get("verified") is True
        and entry.get("verification_ref") == verification_ref
    ]


def compute_verified_content_digest(calendar, verification_ref):
    """Saf, deterministik: kayda bağlı verified yılların `year` +
    `holidays[]` (olduğu gibi - tarih/ad/tür/gözlem/not dahil)
    canonical JSON (sort_keys, kompakt ayraç, UTF-8) SHA-256'ı. Yıllar
    `year`'a göre sıralanır. `source_refs` BİLİNÇLİ olarak dışarıdadır
    (bir atıf metni/URL düzeltmesi yeniden avukat imzası gerektirmez;
    tatil İÇERİĞİ gerektirir)."""

    payload = [
        {
            "year": entry.get("year"),
            "holidays": entry.get("holidays") or [],
        }
        for entry in sorted(
            _years_bound_to_record(calendar, verification_ref),
            key=lambda entry: (
                not isinstance(entry.get("year"), int),
                entry.get("year") if isinstance(entry.get("year"), int) else 0,
            ),
        )
    ]

    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _records_by_ref(calendar):

    by_ref = {}

    for record in (calendar.get("verifications") or []):

        if not isinstance(record, dict):

            continue

        by_ref.setdefault(record.get("verification_ref"), []).append(record)

    return by_ref


def validate_verification_records(calendar):
    """Kayıt-seviyesi, yıldan bağımsız cross-field kurallar (şema alan
    ŞEKİLLERİNİ zaten doğrular): duplicate ref, ref biçimi + sha16 bağı,
    ref yıl aralığı == scope, accepted_years ⊆ [from, to] ve her kabul
    edilen yıl için year_decisions == KABUL, kullanılabilir nihai karar
    (yalnız bağlı yıl varsa ERROR, yoksa WARNING), digest eşitliği.
    Dönüş: (errors, warnings)."""

    errors = []

    warnings = []

    for ref, records in _records_by_ref(calendar).items():

        if len(records) > 1:

            errors.append(
                f"verifications: duplicate verification_ref {ref!r} ({len(records)} records)"
            )

        record = records[0]

        match = VERIFICATION_REF_PATTERN.match(ref) if isinstance(ref, str) else None

        if match is None:

            errors.append(
                f"verifications[{ref!r}]: verification_ref does not match "
                "HC-LAWYER-VERIFY-v1-<from>-<to>-<sha16>"
            )

            continue

        artifact = record.get("signed_artifact") or {}

        sha256 = artifact.get("sha256")

        if not isinstance(sha256, str) or sha256[:16] != match.group("sha16"):

            errors.append(
                f"verifications[{ref!r}]: ref suffix {match.group('sha16')!r} != "
                f"signed_artifact.sha256[:16] ({str(sha256)[:16]!r})"
            )

        scope = record.get("scope") or {}

        year_from = scope.get("year_from")

        year_to = scope.get("year_to")

        if (int(match.group("year_from")), int(match.group("year_to"))) != (year_from, year_to):

            errors.append(
                f"verifications[{ref!r}]: ref year range "
                f"{match.group('year_from')}-{match.group('year_to')} != "
                f"scope.year_from/year_to ({year_from!r}-{year_to!r})"
            )

        if isinstance(year_from, int) and isinstance(year_to, int) and year_from > year_to:

            errors.append(
                f"verifications[{ref!r}]: scope.year_from ({year_from}) > scope.year_to ({year_to})"
            )

        accepted_years = scope.get("accepted_years") or []

        if len(set(accepted_years)) != len(accepted_years):

            errors.append(
                f"verifications[{ref!r}]: duplicate year in scope.accepted_years"
            )

        year_decisions = scope.get("year_decisions") or {}

        for year in accepted_years:

            in_range = (
                isinstance(year_from, int)
                and isinstance(year_to, int)
                and isinstance(year, int)
                and year_from <= year <= year_to
            )

            if not in_range:

                errors.append(
                    f"verifications[{ref!r}]: accepted year {year!r} outside "
                    f"scope.year_from/year_to ({year_from!r}-{year_to!r})"
                )

            if year_decisions.get(str(year)) != "KABUL":

                errors.append(
                    f"verifications[{ref!r}]: accepted year {year!r} has "
                    f"year_decisions={year_decisions.get(str(year))!r} (KABUL required)"
                )

        bound_years = _years_bound_to_record(calendar, ref)

        if scope.get("final_decision") not in USABLE_FINAL_DECISIONS:

            message = (
                f"verifications[{ref!r}]: final_decision={scope.get('final_decision')!r} "
                "is not usable (KABUL or KISMEN_KABUL required)"
            )

            if bound_years:

                errors.append(message)

            else:

                warnings.append(message + " - no verified year references it")

        if not bound_years:

            warnings.append(
                f"verifications[{ref!r}]: no verified year references this record"
            )

        expected_digest = compute_verified_content_digest(calendar, ref)

        recorded_digest = record.get("verified_content_digest")

        if recorded_digest != expected_digest:

            errors.append(
                f"verifications[{ref!r}]: verified_content_digest mismatch "
                f"(recorded {str(recorded_digest)[:16]!r}..., recomputed "
                f"{expected_digest[:16]!r}...) - verified year content differs from "
                "what the lawyer verified; re-verification required"
            )

    return errors, warnings


def validate_verified_year_verification_binding(calendar):
    """Yıl-seviyesi bağ: her `verified is True` yıl, tam bir kayda
    çözülmeli, o kaydın kabul kapsamında olmalı (accepted_years +
    year_decisions[year]==KABUL), kaydın nihai kararı kullanılabilir
    olmalı ve takvim politikası (kararlıysa) kaydın kararıyla
    eşleşmelidir. Kayıt YOKSA yıl doğrulanmış SAYILMAZ (fail-closed)."""

    errors = []

    by_ref = _records_by_ref(calendar)

    half_day_policy = calendar.get("half_day_policy")

    for entry in (calendar.get("years") or []):

        if not isinstance(entry, dict):

            continue

        if entry.get("verified") is not True:

            continue

        year = entry.get("year")

        ref = entry.get("verification_ref")

        records = by_ref.get(ref) or []

        if not records:

            errors.append(
                f"years[year={year}]: verified=true ama verification_ref {ref!r} "
                "takvimin verifications[] dizisindeki hiçbir kayda çözülmüyor "
                "(avukat doğrulama kaydı yok - yıl doğrulanmış sayılmaz)"
            )

            continue

        record = records[0]

        scope = record.get("scope") or {}

        if year not in (scope.get("accepted_years") or []):

            errors.append(
                f"years[year={year}]: yıl, {ref!r} kaydının scope.accepted_years "
                "kapsamında değil"
            )

        year_decision = (scope.get("year_decisions") or {}).get(str(year))

        if year_decision != "KABUL":

            errors.append(
                f"years[year={year}]: {ref!r} kaydının year_decisions[{year}]="
                f"{year_decision!r} (KABUL gerekir)"
            )

        if scope.get("final_decision") not in USABLE_FINAL_DECISIONS:

            errors.append(
                f"years[year={year}]: {ref!r} kaydının final_decision="
                f"{scope.get('final_decision')!r} kullanılabilir değil "
                "(KABUL/KISMEN_KABUL gerekir)"
            )

        decision = scope.get("half_day_policy_decision")

        if half_day_policy != "not_decided" and half_day_policy != decision:

            errors.append(
                f"years[year={year}]: takvim half_day_policy={half_day_policy!r} != "
                f"{ref!r} kaydının half_day_policy_decision={decision!r} "
                "(avukatın karar verdiği politikadan sapma)"
            )

    return errors


def verify_signed_artifact(record, artifact_path):
    """Fiziksel bayt doğrulaması: imzalı dosyanın TAMAMININ SHA-256'ı ve
    boyutu kayıtla karşılaştırılır. Dosya yalnız OKUNUR ve hash'lenir -
    içeriği ayrıştırılmaz, hiçbir yere kopyalanmaz/yazılmaz. `ok` yalnız
    hash VE boyut birlikte eşleşince True."""

    artifact = (record or {}).get("signed_artifact") or {}

    ref = (record or {}).get("verification_ref")

    result = {
        "verification_ref": ref,
        "artifact_path": str(artifact_path),
        "expected_sha256": artifact.get("sha256"),
        "computed_sha256": None,
        "expected_size_bytes": artifact.get("size_bytes"),
        "computed_size_bytes": None,
        "ok": False,
        "errors": [],
    }

    path = Path(artifact_path)

    if not path.is_file():

        result["errors"].append(
            f"signed artifact for {ref!r} not found or not a regular file: {path}"
        )

        return result

    try:

        digest = hashlib.sha256()

        size = 0

        with open(path, "rb") as handle:

            for chunk in iter(lambda: handle.read(1 << 20), b""):

                digest.update(chunk)

                size += len(chunk)

    except OSError as error:

        result["errors"].append(
            f"signed artifact for {ref!r} unreadable: {path}: {error}"
        )

        return result

    result["computed_sha256"] = digest.hexdigest()

    result["computed_size_bytes"] = size

    if result["computed_sha256"] != result["expected_sha256"]:

        result["errors"].append(
            f"signed artifact SHA-256 mismatch for {ref!r}: expected "
            f"{result['expected_sha256']}, computed {result['computed_sha256']}"
        )

    if size != result["expected_size_bytes"]:

        result["errors"].append(
            f"signed artifact size mismatch for {ref!r}: expected "
            f"{result['expected_size_bytes']!r} bytes, computed {size}"
        )

    result["ok"] = not result["errors"]

    return result


def _validate_signed_artifact_paths(calendar, signed_artifact_paths):

    errors = []

    checks = []

    by_ref = _records_by_ref(calendar)

    for ref, path in (signed_artifact_paths or {}).items():

        records = by_ref.get(ref) or []

        if not records:

            errors.append(
                f"signed artifact path supplied for unknown verification_ref {ref!r}"
            )

            continue

        check = verify_signed_artifact(records[0], path)

        checks.append(check)

        errors.extend(check["errors"])

    return errors, checks


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_holiday_calendar(
    calendar=None,
    raise_on_error=False,
    *,
    signed_artifact_paths=None,
):
    """`signed_artifact_paths`: opsiyonel {verification_ref: path}. Verilirse
    ilgili kaydın imzalı dosyası fiziksel olarak hash'lenip karşılaştırılır
    (bkz. `verify_signed_artifact()`); verilmezse yalnız git-governed kayıt +
    yapısal bağlar doğrulanır. Ortam değişkeninden OKUNMAZ."""

    if calendar is None:

        calendar = load_calendar()

    errors = []

    warnings = []

    signed_artifact_checks = []

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

        errors.extend(validate_observance_registry_consistency(calendar))

        errors.extend(validate_verified_year_observance_completeness(calendar))

        # PILOT READINESS ADIM 6 - avukat doğrulama kaydı bağlama.
        record_errors, record_warnings = validate_verification_records(calendar)

        errors.extend(record_errors)

        warnings.extend(record_warnings)

        errors.extend(validate_verified_year_verification_binding(calendar))

        artifact_errors, signed_artifact_checks = _validate_signed_artifact_paths(
            calendar, signed_artifact_paths
        )

        errors.extend(artifact_errors)

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
        "verification_record_count": len(
            [r for r in (calendar.get("verifications") or []) if isinstance(r, dict)]
        ),
        "signed_artifact_checks": signed_artifact_checks,
        "errors": errors,
        "warnings": warnings,
    }

    if raise_on_error and errors:

        raise HolidayCalendarValidationError(
            "HOLIDAY CALENDAR VALIDATOR V3: FAIL\n\n- "
            + "\n- ".join(errors)
        )

    return result


# ============================================================
# TEST FIXTURE
# ============================================================

def create_valid_fixture():

    calendar = {
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

    # ADIM 6: verified 2026 sentetik bir avukat doğrulama kaydına bağlanır
    # (yapısal biçim gerçek kayıtla aynı; gerçek imza DEĞİL - Prensip 18).
    attach_fixture_verification(calendar, seed="create_valid_fixture")

    return calendar


# ============================================================
# TEST-ONLY VERIFICATION-RECORD FIXTURE HELPERS (Adım 6 binding).
#
# Gerçek imzalı bir avukat dosyası YOKTUR: `signed_artifact.sha256`
# yalnız `seed`'in SHA-256'ıdır (yapısal biçim doğru, gerçek imza
# DEĞİL). Prensip 18: bu kayıtlar üretim takvimine ASLA yazılmaz;
# yalnız in-memory/tempdir fixture'larında yaşar.
# ============================================================

def make_fixture_verification_record(
    years,
    *,
    seed,
    half_day_policy_decision="needs_review_if_deadline_day",
    verified_content_digest="0" * 64,
):

    years = sorted(set(int(year) for year in years))

    year_from, year_to = (years[0], years[-1]) if years else (2026, 2026)

    sha256 = hashlib.sha256(
        f"fixture-signed-artifact:{seed}".encode("utf-8")
    ).hexdigest()

    return {
        "verification_ref": f"HC-LAWYER-VERIFY-v1-{year_from}-{year_to}-{sha256[:16]}",
        "document_version": "HC-LAWYER-VERIFY-v1",
        "signed_artifact": {
            "filename": f"fixture_{seed}.udf",
            "format": "udf",
            "sha256": sha256,
            "size_bytes": 1,
            "signature_method": "guvenli_elektronik_imza",
            "signature_timestamp": "2026-01-01T00:00:00+03:00",
            "signature_timestamp_source": "uyap_screen_operator_observation",
            "signature_count_observed": 1,
            "hash_computed_at": "2026-01-01T00:00:00Z",
            "stored_in_repository": False,
        },
        "lawyer": {
            "full_name": "Fixture Lawyer",
            "bar": "Fixture Bar",
            "bar_registration_no": None,
        },
        "review_date": "2026-01-01",
        "scope": {
            "year_from": year_from,
            "year_to": year_to,
            "accepted_years": years,
            "year_decisions": {str(year): "KABUL" for year in years},
            "conflict_decision": "KABUL",
            "half_day_policy_decision": half_day_policy_decision,
            "final_decision": "KABUL",
            "corrections": [],
        },
        "referenced_source_artifacts": [],
        "verified_content_digest": verified_content_digest,
        "notes": (
            "TEST FIXTURE - sentetik doğrulama kaydı; gerçek avukat imzası "
            "DEĞİLDİR (Prensip 18)."
        ),
    }


def attach_fixture_verification(
    calendar,
    *,
    seed="fixture",
    half_day_policy_decision=None,
):
    """TEST-ONLY: takvimin TÜM verified yıllarını kapsayan TEK sentetik
    kayıt üretir, her verified yılın `verification_ref`'ini ona bağlar,
    digest'i hesaplar ve `calendar["verifications"]`'ı bu tek kayıtla
    DEĞİŞTİRİR. Dönüş: ref (verified yıl yoksa None; verifications=[])."""

    verified_years = [
        entry["year"]
        for entry in (calendar.get("years") or [])
        if isinstance(entry, dict) and entry.get("verified") is True
    ]

    if not verified_years:

        calendar["verifications"] = []

        return None

    if half_day_policy_decision is None:

        policy = calendar.get("half_day_policy")

        half_day_policy_decision = (
            policy
            if policy in DECIDED_HALF_DAY_POLICIES
            else "needs_review_if_deadline_day"
        )

    record = make_fixture_verification_record(
        verified_years,
        seed=seed,
        half_day_policy_decision=half_day_policy_decision,
    )

    ref = record["verification_ref"]

    for entry in calendar["years"]:

        if isinstance(entry, dict) and entry.get("verified") is True:

            entry["verification_ref"] = ref

    calendar["verifications"] = [record]

    record["verified_content_digest"] = compute_verified_content_digest(calendar, ref)

    return ref


def refresh_fixture_verification(calendar):
    """TEST-ONLY: bir fixture'ın holidays/half_day_policy'si test amaçlı
    DEĞİŞTİRİLDİKTEN sonra her kaydın digest'ini yeniden hesaplar ve
    (takvim politikası kararlıysa) `half_day_policy_decision`'ı ona
    eşitler - "avukat bu yeni içeriği de onayladı" simülasyonu. ÜRETİM
    yolunda böyle bir çağrı YOKTUR; üretim kaydı statik/git-governed'dır."""

    policy = calendar.get("half_day_policy")

    for record in (calendar.get("verifications") or []):

        if not isinstance(record, dict):

            continue

        if policy in DECIDED_HALF_DAY_POLICIES:

            record.setdefault("scope", {})["half_day_policy_decision"] = policy

        record["verified_content_digest"] = compute_verified_content_digest(
            calendar, record.get("verification_ref")
        )

    return calendar


# ============================================================
# SELF TEST
# ============================================================

def run_self_test():

    print()
    print("======================================")
    print(" VERGİ AI - HOLIDAY CALENDAR VALIDATOR V3")
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

    refresh_fixture_verification(allowed)  # ADIM 6: içerik değişti -> simüle yeniden doğrulama

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
    # PHASE A (REV4.1 kanit kapanisi) - observances[] / canonical
    # registry / verified-year completeness self-testleri.
    # ========================================================

    def _obs(oid, block_index=None):

        reg = CANONICAL_OBSERVANCE_REGISTRY[oid]

        return {
            "observance_id": oid,
            "kind": reg["kind"],
            "day_type": reg["day_type"],
            "legal_basis_ref": reg["legal_basis_ref"],
            "block_index": block_index,
        }

    def _derive_top_level(observances):

        day_types = {o["day_type"] for o in observances}

        kinds = {o["kind"] for o in observances}

        return (
            "full_day" if "full_day" in day_types else "half_day",
            "national" if "national" in kinds else "religious",
        )

    def _holiday_entry(date_value, name, observances, source_ref_index=0):

        day_type, kind = _derive_top_level(observances)

        return {
            "date": date_value,
            "name": name,
            "kind": kind,
            "day_type": day_type,
            "source_ref_index": source_ref_index,
            "notes": None,
            "observances": observances,
        }

    def _complete_2026_holidays():

        return [
            _holiday_entry("2026-01-01", "Yılbaşı", [_obs("yilbasi")]),
            _holiday_entry("2026-03-19", "Ramazan Bayramı Arefesi", [_obs("ramazan_bayrami_arefe", 1)]),
            _holiday_entry("2026-03-20", "Ramazan Bayramı 1. Gün", [_obs("ramazan_bayrami_gun1", 1)]),
            _holiday_entry("2026-03-21", "Ramazan Bayramı 2. Gün", [_obs("ramazan_bayrami_gun2", 1)]),
            _holiday_entry("2026-03-22", "Ramazan Bayramı 3. Gün", [_obs("ramazan_bayrami_gun3", 1)]),
            _holiday_entry("2026-04-23", "Ulusal Egemenlik ve Çocuk Bayramı", [_obs("ulusal_egemenlik_cocuk_bayrami")]),
            _holiday_entry("2026-05-01", "Emek ve Dayanışma Günü", [_obs("emek_dayanisma_gunu")]),
            _holiday_entry("2026-05-19", "Atatürk'ü Anma Gençlik ve Spor Bayramı", [_obs("ataturk_anma_genclik_spor_bayrami")]),
            _holiday_entry("2026-05-26", "Kurban Bayramı Arefesi", [_obs("kurban_bayrami_arefe", 1)]),
            _holiday_entry("2026-05-27", "Kurban Bayramı 1. Gün", [_obs("kurban_bayrami_gun1", 1)]),
            _holiday_entry("2026-05-28", "Kurban Bayramı 2. Gün", [_obs("kurban_bayrami_gun2", 1)]),
            _holiday_entry("2026-05-29", "Kurban Bayramı 3. Gün", [_obs("kurban_bayrami_gun3", 1)]),
            _holiday_entry("2026-05-30", "Kurban Bayramı 4. Gün", [_obs("kurban_bayrami_gun4", 1)]),
            _holiday_entry("2026-07-15", "Demokrasi ve Milli Birlik Günü", [_obs("demokrasi_milli_birlik_gunu")]),
            _holiday_entry("2026-08-30", "Zafer Bayramı", [_obs("zafer_bayrami")]),
            _holiday_entry("2026-10-28", "Cumhuriyet Bayramı Arefesi", [_obs("cumhuriyet_bayrami_arefe")]),
            _holiday_entry("2026-10-29", "Cumhuriyet Bayramı", [_obs("cumhuriyet_bayrami")]),
        ]

    def _observance_calendar(verified, holidays, half_day_policy="needs_review_if_deadline_day"):

        calendar = create_valid_fixture()

        calendar["half_day_policy"] = half_day_policy

        calendar["years"] = [
            {
                "year": 2026,
                "verified": verified,
                "verification_ref": ("phase_a_fixture_verification_ref_2026" if verified else None),
                "source_refs": [
                    {"source_kind": "fixture", "citation": "Phase A fixture citation.", "url": None}
                ],
                "holidays": holidays,
            },
        ]

        attach_fixture_verification(calendar, seed="phase_a_observance_calendar")

        return calendar

    # T23 POSITIVE CONTROL: fully correct, COMPLETE 2026 observances[]
    # fixture, unverified - registry/ordering checks must ALL pass, no
    # completeness requirement fires (year not verified).

    complete_holidays = _complete_2026_holidays()

    good_calendar = _observance_calendar(verified=False, holidays=complete_holidays)

    result = validate_holiday_calendar(calendar=good_calendar)

    if not result["valid"]:

        for error in result["errors"]:

            print("-", error)

    assert result["valid"] is True

    print("T23 Complete, correct observances[] fixture (unverified year): PASS")

    # T24 POSITIVE CONTROL: SAME complete fixture, verified=True - full
    # completeness check must ALSO pass (all 17 present, correct blocks).

    verified_good_calendar = _observance_calendar(verified=True, holidays=complete_holidays)

    result = validate_holiday_calendar(calendar=verified_good_calendar)

    if not result["valid"]:

        for error in result["errors"]:

            print("-", error)

    assert result["valid"] is True

    print("T24 Complete, correct observances[] fixture (verified year): PASS")

    # T25 wrong kind on an observance REJECTED

    broken_holidays = copy.deepcopy(complete_holidays)

    broken_holidays[0]["observances"][0]["kind"] = "religious"

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T25 Wrong observance kind (registry cross-check) blocked: PASS")

    # T26 wrong day_type on an observance REJECTED

    broken_holidays = copy.deepcopy(complete_holidays)

    broken_holidays[1]["observances"][0]["day_type"] = "full_day"

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T26 Wrong observance day_type (registry cross-check) blocked: PASS")

    # T27 wrong legal_basis_ref on an observance REJECTED

    broken_holidays = copy.deepcopy(complete_holidays)

    broken_holidays[0]["observances"][0]["legal_basis_ref"] = "uydurma referans"

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T27 Wrong observance legal_basis_ref (registry cross-check) blocked: PASS")

    # T28 national observance with non-null block_index REJECTED

    broken_holidays = copy.deepcopy(complete_holidays)

    broken_holidays[0]["observances"][0]["block_index"] = 1

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T28 National observance with non-null block_index blocked: PASS")

    # T29 religious observance with block_index=None REJECTED

    broken_holidays = copy.deepcopy(complete_holidays)

    broken_holidays[1]["observances"][0]["block_index"] = None

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T29 Religious observance with block_index=null blocked: PASS")

    # T30 block_index contiguity gap (1 -> 3, skipping 2) REJECTED

    broken_holidays = copy.deepcopy(complete_holidays)

    for holiday in broken_holidays:

        for observance in holiday["observances"]:

            if observance["observance_id"].startswith("ramazan_bayrami"):

                observance["block_index"] = 3

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T30 block_index contiguity gap (1->3) blocked: PASS")

    # T31 block sequence day-gap (gun2 moved 2 days later) REJECTED

    broken_holidays = copy.deepcopy(complete_holidays)

    for holiday in broken_holidays:

        if holiday["date"] == "2026-03-21":

            holiday["date"] = "2026-03-23"

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T31 Block sequence day-gap (not exactly 1 day apart) blocked: PASS")

    # T32 top-level day_type inconsistent with observances[] REJECTED

    broken_holidays = copy.deepcopy(complete_holidays)

    broken_holidays[1]["day_type"] = "full_day"  # arefe entry, actually half_day

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T32 Top-level day_type inconsistent with observances[] blocked: PASS")

    # T33 top-level kind inconsistent with observances[] REJECTED

    broken_holidays = copy.deepcopy(complete_holidays)

    broken_holidays[1]["kind"] = "national"  # ramazan arefe, actually religious

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T33 Top-level kind inconsistent with observances[] blocked: PASS")

    # T34 verified year: missing fixed observance (yilbasi entry removed) REJECTED

    incomplete_holidays = [h for h in complete_holidays if h["date"] != "2026-01-01"]

    result = validate_holiday_calendar(calendar=_observance_calendar(True, incomplete_holidays))

    assert result["valid"] is False

    print("T34 Verified year missing a fixed observance blocked: PASS")

    # T35 verified year: incomplete religious block (kurban gun4 removed) REJECTED

    incomplete_holidays = [h for h in complete_holidays if h["date"] != "2026-05-30"]

    result = validate_holiday_calendar(calendar=_observance_calendar(True, incomplete_holidays))

    assert result["valid"] is False

    print("T35 Verified year with incomplete religious block blocked: PASS")

    # T36 UNVERIFIED year with a partial (in-progress) religious block is
    # FINE - completeness is not required until verified=True (only
    # registry/ordering checks apply, and the partial block's PRESENT
    # members are still correctly sequenced).

    partial_holidays = [h for h in complete_holidays if h["date"] != "2026-05-30"]

    result = validate_holiday_calendar(calendar=_observance_calendar(False, partial_holidays))

    if not result["valid"]:

        for error in result["errors"]:

            print("-", error)

    assert result["valid"] is True

    print("T36 Unverified year with in-progress partial religious block allowed: PASS")

    # T37 half_day_policy == "needs_review_if_deadline_day" (NEW 4th enum
    # value): half_day entries in a verified year are ALLOWED (mirrors
    # T15b's "counts_as_holiday" positive control, for the new value).

    result = validate_holiday_calendar(
        calendar=_observance_calendar(True, complete_holidays, half_day_policy="needs_review_if_deadline_day")
    )

    if not result["valid"]:

        for error in result["errors"]:

            print("-", error)

    assert result["valid"] is True

    print("T37 half_day entries under half_day_policy='needs_review_if_deadline_day' (verified year) allowed: PASS")

    # T38 schema-level: unknown observance_id value REJECTED (enum, root
    # additionalProperties:false chain already covers unknown NESTED
    # fields - this checks the observance_id ENUM specifically).

    broken_holidays = copy.deepcopy(complete_holidays)

    broken_holidays[0]["observances"][0]["observance_id"] = "uydurma_gozlem"

    result = validate_holiday_calendar(calendar=_observance_calendar(False, broken_holidays))

    assert result["valid"] is False

    print("T38 Unknown observance_id (schema enum) blocked: PASS")

    # ========================================================
    # F1 REMEDIATION (Phase A bağımsız incelemesi, C.14) -
    # cross-entry duplicate + çok-bloklu tamlık + REV4.1 exact
    # block-count sözleşmesi. Her negatif test SPESİFİK hata
    # mesajını pinler; pozitif kontroller (T42/T43/T50) aynı
    # helper'ların geçerli fixture ürettiğini kanıtlar - negatifler
    # bu yüzden vacuous DEĞİLDİR.
    # ========================================================

    def _has_error(result, fragment):

        return any(fragment in error for error in result["errors"])

    def _synthetic_complete_holidays(year, ramazan_block_starts=("02-10",), kurban_block_starts=("06-10",)):
        """Tam bir observances[] yılı: 8 sabit gözlem DOĞRU ay-günde;
        dinî bloklar SENTETİK, sabit tarihlerle çakışmayan başlangıç
        günlerinden itibaren ardışık günlerde. Test fixture'ıdır -
        gerçek tatil verisi DEĞİLDİR (Prensip 18)."""

        holidays = []

        for oid, reg in CANONICAL_OBSERVANCE_REGISTRY.items():

            if reg["family"] is None:

                holidays.append(_holiday_entry(f"{year}-{reg['fixed_month_day']}", oid, [_obs(oid)]))

        for family, starts in (("ramazan", ramazan_block_starts), ("kurban", kurban_block_starts)):

            for block_index, start in enumerate(starts, start=1):

                start_date = date.fromisoformat(f"{year}-{start}")

                for oid in CANONICAL_OBSERVANCE_FAMILY_IDS[family]:

                    offset = CANONICAL_OBSERVANCE_REGISTRY[oid]["sequence_position"]

                    holidays.append(
                        _holiday_entry(
                            (start_date + timedelta(days=offset)).isoformat(),
                            f"{oid} b{block_index}",
                            [_obs(oid, block_index)],
                        )
                    )

        holidays.sort(key=lambda h: h["date"])

        return holidays

    def _observance_calendar_for_year(year, verified, holidays, half_day_policy="needs_review_if_deadline_day"):

        calendar = create_valid_fixture()

        calendar["half_day_policy"] = half_day_policy

        calendar["years"] = [
            {
                "year": year,
                "verified": verified,
                "verification_ref": (f"phase_a_fixture_verification_ref_{year}" if verified else None),
                "source_refs": [
                    {"source_kind": "fixture", "citation": "Phase A fixture citation.", "url": None}
                ],
                "holidays": holidays,
            },
        ]

        attach_fixture_verification(calendar, seed=f"phase_a_observance_calendar_{year}")

        return calendar

    # T39 cross-entry duplicate NATIONAL observance, UNVERIFIED year ->
    # REJECTED (koşulsuz: verified olmasa da yapısal kusur).

    dup_national = copy.deepcopy(complete_holidays)

    dup_national.append(_holiday_entry("2026-03-03", "hayalet Zafer Bayramı", [_obs("zafer_bayrami")]))

    dup_national.sort(key=lambda h: h["date"])

    result = validate_holiday_calendar(calendar=_observance_calendar(False, dup_national))

    assert result["valid"] is False

    assert _has_error(result, "national observance 'zafer_bayrami' occurs 2 times across entries")

    assert _has_error(result, "['2026-03-03', '2026-08-30']")

    print("T39 Cross-entry duplicate national observance (unverified year) blocked: PASS")

    # T40 same fixture, VERIFIED year -> REJECTED; the ">1" message is
    # emitted EXACTLY once (registry-consistency owns it; completeness
    # reports only the wrong month-day of the phantom occurrence).

    result = validate_holiday_calendar(calendar=_observance_calendar(True, dup_national))

    assert result["valid"] is False

    assert sum("occurs 2 times across entries" in error for error in result["errors"]) == 1

    assert _has_error(result, "'zafer_bayrami' expected at 2026-08-30, found at '2026-03-03'")

    print("T40 Cross-entry duplicate national observance (verified year) blocked, reported once: PASS")

    # T41 cross-entry duplicate RELIGIOUS member in the SAME block
    # (kurban_bayrami_gun4 block 1 at 2026-05-20 AND 2026-05-30) -> REJECTED.

    dup_religious = copy.deepcopy(complete_holidays)

    dup_religious.append(_holiday_entry("2026-05-20", "hayalet K4", [_obs("kurban_bayrami_gun4", 1)]))

    dup_religious.sort(key=lambda h: h["date"])

    result = validate_holiday_calendar(calendar=_observance_calendar(False, dup_religious))

    assert result["valid"] is False

    assert _has_error(
        result,
        "kurban block 1: religious observance 'kurban_bayrami_gun4' occurs 2 times across entries",
    )

    print("T41 Cross-entry duplicate religious member within one block blocked: PASS")

    # T42 POSITIVE CONTROL for the synthetic helper: verified 2026, one
    # ramazan + one kurban block -> valid (so T45-T48 negatives are not
    # vacuous).

    result = validate_holiday_calendar(calendar=_observance_calendar_for_year(2026, True, _synthetic_complete_holidays(2026)))

    if not result["valid"]:

        for error in result["errors"]:

            print("-", error)

    assert result["valid"] is True

    print("T42 Synthetic complete 2026 (1 ramazan + 1 kurban block, verified) accepted: PASS")

    # T43 POSITIVE: 2033 with TWO complete ramazan blocks (block_index 1
    # and 2; same observance_ids in different blocks are LEGITIMATE) ->
    # valid under the REV4.1 contract (2033 ramazan == 2).

    holidays_2033 = _synthetic_complete_holidays(2033, ramazan_block_starts=("02-10", "12-10"))

    result = validate_holiday_calendar(calendar=_observance_calendar_for_year(2033, True, holidays_2033))

    if not result["valid"]:

        for error in result["errors"]:

            print("-", error)

    assert result["valid"] is True

    print("T43 2033 with two complete ramazan blocks (same ids, different block_index) accepted: PASS")

    # T44 2033: block 1 missing gun3, block 2 complete -> REJECTED (block 2
    # can no longer mask block 1).

    incomplete_2033 = [h for h in holidays_2033 if h["date"] != "2033-02-13"]

    result = validate_holiday_calendar(calendar=_observance_calendar_for_year(2033, True, incomplete_2033))

    assert result["valid"] is False

    assert _has_error(result, "ramazan block 1 is missing 'ramazan_bayrami_gun3' (sequence_position 3)")

    print("T44 Two-block year with block 1 incomplete and block 2 complete blocked: PASS")

    # T45 verified 2026 with ZERO ramazan blocks -> REJECTED.

    result = validate_holiday_calendar(
        calendar=_observance_calendar_for_year(2026, True, _synthetic_complete_holidays(2026, ramazan_block_starts=()))
    )

    assert result["valid"] is False

    assert _has_error(result, "ramazan expected exactly 1 block(s) per REV4.1 contract, found 0 []")

    print("T45 Verified year with no ramazan block blocked: PASS")

    # T46 verified 2026 with ZERO kurban blocks -> REJECTED.

    result = validate_holiday_calendar(
        calendar=_observance_calendar_for_year(2026, True, _synthetic_complete_holidays(2026, kurban_block_starts=()))
    )

    assert result["valid"] is False

    assert _has_error(result, "kurban expected exactly 1 block(s) per REV4.1 contract, found 0 []")

    print("T46 Verified year with no kurban block blocked: PASS")

    # T47 2033 with only ONE ramazan block -> REJECTED (contract says 2).

    result = validate_holiday_calendar(
        calendar=_observance_calendar_for_year(2033, True, _synthetic_complete_holidays(2033))
    )

    assert result["valid"] is False

    assert _has_error(result, "ramazan expected exactly 2 block(s) per REV4.1 contract, found 1 [1]")

    print("T47 2033 with a single ramazan block blocked: PASS")

    # T48 2026 with TWO ramazan blocks -> REJECTED (contract says 1).

    result = validate_holiday_calendar(
        calendar=_observance_calendar_for_year(2026, True, _synthetic_complete_holidays(2026, ramazan_block_starts=("02-10", "12-10")))
    )

    assert result["valid"] is False

    assert _has_error(result, "ramazan expected exactly 1 block(s) per REV4.1 contract, found 2 [1, 2]")

    print("T48 2026 with two ramazan blocks blocked: PASS")

    # T49 verified 2036 (outside the 2024-2035 contract), otherwise
    # complete -> REJECTED fail-closed (no silent guess).

    result = validate_holiday_calendar(
        calendar=_observance_calendar_for_year(2036, True, _synthetic_complete_holidays(2036))
    )

    assert result["valid"] is False

    assert _has_error(result, "no exact religious block-count contract for year 2036")

    print("T49 Verified observances[] year outside the REV4.1 contract range refused: PASS")

    # T50 UNVERIFIED 2036, same data -> ACCEPTED (contract gate is
    # verified-only; in-progress data outside the range is not blocked).

    result = validate_holiday_calendar(
        calendar=_observance_calendar_for_year(2036, False, _synthetic_complete_holidays(2036))
    )

    if not result["valid"]:

        for error in result["errors"]:

            print("-", error)

    assert result["valid"] is True

    print("T50 Unverified observances[] year outside the contract range accepted: PASS")

    # T51 a duplicate at one sequence_position does NOT suppress the
    # adjacency check elsewhere in the same block: duplicate gun4 (pos 4)
    # AND gun2 (pos 2) moved 5 days late -> BOTH errors reported.

    dup_plus_gap = copy.deepcopy(complete_holidays)

    dup_plus_gap.append(_holiday_entry("2026-05-20", "hayalet K4", [_obs("kurban_bayrami_gun4", 1)]))

    for holiday in dup_plus_gap:

        if holiday["date"] == "2026-05-28":

            holiday["date"] = "2026-06-02"

    dup_plus_gap.sort(key=lambda h: h["date"])

    result = validate_holiday_calendar(calendar=_observance_calendar(False, dup_plus_gap))

    assert result["valid"] is False

    assert _has_error(result, "kurban block 1: religious observance 'kurban_bayrami_gun4' occurs 2 times")

    assert _has_error(result, "kurban block 1: kurban_bayrami_gun2 (2026-06-02) is 6 day(s) after kurban_bayrami_gun1 (2026-05-27)")

    print("T51 Duplicate member does not suppress the block adjacency check: PASS")

    # ========================================================
    # PILOT READINESS ADIM 6 - avukat doğrulama kaydı (verifications[])
    # bağlama self-testleri. Fixture'lar sentetik kayıt taşır (Prensip
    # 18); üretim takvimi yalnız SALT-OKUNUR doğrulanır (T63).
    # ========================================================

    def _has_error(result, fragment):

        return any(fragment in error for error in result["errors"])

    # T52 create_valid_fixture() exactly ONE record; the verified year's
    # ref matches the HC-LAWYER-VERIFY-v1 pattern AND resolves to it.

    fixture = create_valid_fixture()

    assert len(fixture["verifications"]) == 1

    fixture_ref = fixture["years"][0]["verification_ref"]

    assert VERIFICATION_REF_PATTERN.match(fixture_ref) is not None

    assert fixture["verifications"][0]["verification_ref"] == fixture_ref

    result = validate_holiday_calendar(calendar=fixture)

    assert result["valid"] is True, result["errors"]

    assert result["verification_record_count"] == 1

    print("T52 Fixture carries one bound verification record (pattern + resolution): PASS")

    # T53 verified year whose ref resolves to NO record -> REJECTED
    # (fail-closed: a verified year without a lawyer record does not
    # count as verified).

    broken = copy.deepcopy(fixture)

    broken["verifications"] = []

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    assert _has_error(result, "hiçbir kayda çözülmüyor")

    print("T53 Verified year without a verification record blocked: PASS")

    # T54 content tamper in a verified year (name changed, digest NOT
    # refreshed) -> REJECTED with the digest-mismatch message.

    broken = copy.deepcopy(fixture)

    broken["years"][0]["holidays"][0]["name"] = "Tampered after lawyer verification"

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    assert _has_error(result, "verified_content_digest mismatch")

    print("T54 Verified-year content tamper without re-verification blocked (digest): PASS")

    # T55 POSITIVE CONTROL: same change with refresh_fixture_verification()
    # (simulated re-verification) -> valid again - proves T54 fired on
    # the digest rule and nothing else.

    refreshed = refresh_fixture_verification(copy.deepcopy(broken))

    result = validate_holiday_calendar(calendar=refreshed)

    assert result["valid"] is True, result["errors"]

    print("T55 Same content after simulated re-verification accepted (digest positive control): PASS")

    # T56 ref suffix != signed_artifact.sha256[:16] -> REJECTED.

    broken = copy.deepcopy(fixture)

    sha = broken["verifications"][0]["signed_artifact"]["sha256"]

    broken["verifications"][0]["signed_artifact"]["sha256"] = ("f" if sha[0] != "f" else "0") + sha[1:]

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    assert _has_error(result, "!= signed_artifact.sha256[:16]")

    print("T56 verification_ref suffix not bound to signed_artifact.sha256 blocked: PASS")

    # T57 verified year removed from scope.accepted_years -> REJECTED.

    broken = copy.deepcopy(fixture)

    broken["verifications"][0]["scope"]["accepted_years"] = []

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    assert _has_error(result, "scope.accepted_years kapsamında değil")

    print("T57 Verified year outside the record's accepted_years blocked: PASS")

    # T58 year_decisions[year] != KABUL -> REJECTED (both record-level
    # and year-level rules fire).

    broken = copy.deepcopy(fixture)

    broken["verifications"][0]["scope"]["year_decisions"] = {"2026": "DUZELTME"}

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    assert _has_error(result, "(KABUL gerekir)")

    print("T58 Verified year with a non-KABUL year decision blocked: PASS")

    # T59 final_decision RED / DUZELTMEYLE_KABUL -> REJECTED; KISMEN_KABUL
    # (with the year explicitly accepted) -> ACCEPTED.

    for decision in ("RED", "DUZELTMEYLE_KABUL"):

        broken = copy.deepcopy(fixture)

        broken["verifications"][0]["scope"]["final_decision"] = decision

        result = validate_holiday_calendar(calendar=broken)

        assert result["valid"] is False, decision

        assert _has_error(result, "kullanılabilir değil")

    partial = copy.deepcopy(fixture)

    partial["verifications"][0]["scope"]["final_decision"] = "KISMEN_KABUL"

    result = validate_holiday_calendar(calendar=partial)

    assert result["valid"] is True, result["errors"]

    print("T59 RED/DUZELTMEYLE_KABUL blocked, KISMEN_KABUL with the year accepted allowed: PASS")

    # T60 half_day_policy mismatch: calendar decided a policy DIFFERENT
    # from the lawyer's decision -> REJECTED; calendar not_decided ->
    # mismatch rule skipped (rule 6 owns the not_decided case).

    broken = copy.deepcopy(fixture)

    broken["half_day_policy"] = "counts_as_working_day"

    assert broken["verifications"][0]["scope"]["half_day_policy_decision"] == "needs_review_if_deadline_day"

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    assert _has_error(result, "avukatın karar verdiği politikadan sapma")

    assert fixture["half_day_policy"] == "not_decided"

    result = validate_holiday_calendar(calendar=fixture)

    assert result["valid"] is True, result["errors"]

    print("T60 Calendar half_day_policy deviating from the lawyer's decision blocked: PASS")

    # T61 duplicate verification_ref across records -> REJECTED.

    broken = copy.deepcopy(fixture)

    broken["verifications"].append(copy.deepcopy(broken["verifications"][0]))

    result = validate_holiday_calendar(calendar=broken)

    assert result["valid"] is False

    assert _has_error(result, "duplicate verification_ref")

    print("T61 Duplicate verification_ref across records blocked: PASS")

    # T62 physical signed-artifact check: a temp file whose bytes hash to
    # the record's sha256 -> ok; tampered bytes -> not ok and
    # validate_holiday_calendar(signed_artifact_paths=...) FAILS; unknown
    # ref path -> FAIL. Tempdir-isolated; nothing under data/ is touched.

    with tempfile.TemporaryDirectory() as tmp:

        artifact_bytes = b"fixture signed artifact bytes\n"

        bound = copy.deepcopy(fixture)

        record = bound["verifications"][0]

        record["signed_artifact"]["sha256"] = hashlib.sha256(artifact_bytes).hexdigest()

        record["signed_artifact"]["size_bytes"] = len(artifact_bytes)

        new_ref = (
            "HC-LAWYER-VERIFY-v1-2026-2026-"
            + record["signed_artifact"]["sha256"][:16]
        )

        record["verification_ref"] = new_ref

        bound["years"][0]["verification_ref"] = new_ref

        refresh_fixture_verification(bound)

        good_path = Path(tmp) / "good.udf"

        good_path.write_bytes(artifact_bytes)

        tampered_path = Path(tmp) / "tampered.udf"

        tampered_path.write_bytes(artifact_bytes + b"x")

        good = verify_signed_artifact(record, good_path)

        assert good["ok"] is True, good

        assert good["computed_sha256"] == record["signed_artifact"]["sha256"]

        tampered = verify_signed_artifact(record, tampered_path)

        assert tampered["ok"] is False

        assert any("SHA-256 mismatch" in error for error in tampered["errors"])

        missing = verify_signed_artifact(record, Path(tmp) / "missing.udf")

        assert missing["ok"] is False

        result = validate_holiday_calendar(calendar=bound, signed_artifact_paths={new_ref: good_path})

        assert result["valid"] is True, result["errors"]

        assert len(result["signed_artifact_checks"]) == 1 and result["signed_artifact_checks"][0]["ok"] is True

        result = validate_holiday_calendar(calendar=bound, signed_artifact_paths={new_ref: tampered_path})

        assert result["valid"] is False

        assert _has_error(result, "SHA-256 mismatch")

        result = validate_holiday_calendar(
            calendar=bound, signed_artifact_paths={"HC-LAWYER-VERIFY-v1-2026-2026-0000000000000000": good_path}
        )

        assert result["valid"] is False

        assert _has_error(result, "unknown verification_ref")

    print("T62 Physical signed-artifact SHA-256/size check (good/tampered/missing/unknown-ref): PASS")

    # T63 REAL committed calendar (read-only): every verified year resolves
    # to a pattern-conformant record, and the record count is consistent.

    real_calendar = load_calendar()

    real_by_ref = {r["verification_ref"]: r for r in real_calendar.get("verifications") or []}

    for entry in real_calendar["years"]:

        if entry.get("verified") is True:

            assert entry["verification_ref"] in real_by_ref, entry["year"]

            assert VERIFICATION_REF_PATTERN.match(entry["verification_ref"]) is not None

    assert real_result["verification_record_count"] == len(real_by_ref)

    print("T63 Real committed calendar: every verified year resolves to a conformant record: PASS")

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print("Calendar:", real_result["calendar_id"])
    print("Year count:", real_result["year_count"])
    print("Verified year count:", real_result["verified_year_count"])
    print()
    print("======================================")
    print(" HOLIDAY CALENDAR VALIDATOR V3: 67/67 PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Vergi AI Holiday Calendar Validator V3"
    )

    parser.add_argument(
        "--calendar",
        dest="calendar_path",
        default=None,
        help="Doğrulanacak takvim dosyası (varsayılan: üretim registry'si)",
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    parser.add_argument(
        "--verify-signed-artifact",
        dest="signed_artifact_path",
        default=None,
        help=(
            "İmzalı avukat doğrulama dosyasının (repo DIŞI, git'e girmez) yolu; "
            "tamamının SHA-256'ı ve boyutu takvimdeki kayıtla karşılaştırılır. "
            "Dosya yalnız okunur/hash'lenir, kopyalanmaz."
        ),
    )

    parser.add_argument(
        "--verification-ref",
        dest="verification_ref",
        default=None,
        help=(
            "Fiziksel kontrolün bağlanacağı verification_ref; takvimde TEK kayıt "
            "varsa atlanabilir."
        ),
    )

    args = parser.parse_args()

    if args.self_test or (
        args.calendar_path is None and args.signed_artifact_path is None
    ):

        run_self_test()

        return

    print()
    print("======================================")
    print(" VERGİ AI - HOLIDAY CALENDAR VALIDATOR V3")
    print("======================================")

    try:

        calendar = load_calendar(
            Path(args.calendar_path) if args.calendar_path else None
        )

        signed_artifact_paths = None

        if args.signed_artifact_path is not None:

            refs = [
                record.get("verification_ref")
                for record in (calendar.get("verifications") or [])
                if isinstance(record, dict)
            ]

            ref = args.verification_ref

            if ref is None:

                if len(refs) != 1:

                    raise HolidayCalendarValidationError(
                        "--verify-signed-artifact için --verification-ref gerekli: "
                        f"takvimde {len(refs)} kayıt var ({refs})"
                    )

                ref = refs[0]

            signed_artifact_paths = {ref: Path(args.signed_artifact_path)}

        result = validate_holiday_calendar(
            calendar=calendar,
            raise_on_error=False,
            signed_artifact_paths=signed_artifact_paths,
        )

    except Exception as error:

        print()
        print("VALIDATION ERROR")
        print(error)
        print()
        print("======================================")
        print(" HOLIDAY CALENDAR VALIDATOR V3: FAIL")
        print("======================================")

        sys.exit(1)

    print()
    print("Calendar:", result["calendar_id"])
    print("Calendar version:", result["calendar_version"])
    print("Year count:", result["year_count"])
    print("Verified year count:", result["verified_year_count"])
    print("Verification record count:", result["verification_record_count"])

    for record in (calendar.get("verifications") or []):

        if not isinstance(record, dict):

            continue

        artifact = record.get("signed_artifact") or {}

        scope = record.get("scope") or {}

        print(
            "  record:", record.get("verification_ref"),
            "| years", scope.get("year_from"), "-", scope.get("year_to"),
            "| final_decision", scope.get("final_decision"),
            "| half_day_policy_decision", scope.get("half_day_policy_decision"),
            "| signed_artifact", artifact.get("filename"),
            "sha256", artifact.get("sha256"),
        )

    for check in result["signed_artifact_checks"]:

        print()
        print("Signed artifact check:", check["verification_ref"])
        print("  path:", check["artifact_path"])
        print("  expected sha256:", check["expected_sha256"])
        print("  computed sha256:", check["computed_sha256"])
        print("  expected size:", check["expected_size_bytes"], "computed size:", check["computed_size_bytes"])
        print("  ok:", check["ok"])

    if result["warnings"]:

        print()
        print("Warnings:")

        for warning in result["warnings"]:

            print("-", warning)

    if result["errors"]:

        print()
        print("Errors:")

        for error in result["errors"]:

            print("-", error)

    print()
    print("======================================")

    if result["valid"]:

        print(" HOLIDAY CALENDAR VALIDATOR V3: PASS")

    else:

        print(" HOLIDAY CALENDAR VALIDATOR V3: FAIL")

        sys.exit(1)

    print("======================================")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()
