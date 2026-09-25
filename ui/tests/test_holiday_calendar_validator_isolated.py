# ============================================================
# PILOT READINESS ADIM 5 - isolated tests for
# src/holiday_calendar_validator.py: kalıcı, non-tautological kanıt
# evi.
#
# Bu dosya holiday_calendar_validator.py'nin KENDİ run_self_test()'inden
# (T01-T22, modülün kendi içinde) AYRIDIR - bu dosya modülün public
# API'sini `ui/tests/` katmanından, repo'nun standart check()-sayaçlı
# konvansiyonuyla (`test_corpus_policy_validator_isolated.py` deseni),
# tempdir-izoleli olarak dener; hiçbir gerçek data/ ağacına yazmaz.
#
# Run: python -m ui.tests.test_holiday_calendar_validator_isolated
# ============================================================

import copy
import hashlib
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import deadline_calculator as dc          # noqa: E402  (D.11 only: load_holiday_calendar gate)
import holiday_calendar_validator as hcv  # noqa: E402

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {type(error).__name__}: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")


REAL_DATA_DIR = REPO_ROOT / "data"


def _snapshot_data_tree():
    out = {}
    for path in REAL_DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(REAL_DATA_DIR))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(REAL_DATA_DIR))] = "<unreadable>"
    return out


# ================================================================
# SCHEMA VALID/INVALID
# ================================================================


def test_valid_fixture_schema_and_business_rules_pass():
    fixture = hcv.create_valid_fixture()
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("valid fixture: schema+business-rules pass", result["valid"] is True, result["errors"])
    check("valid fixture: errors list empty", result["errors"] == [])


def test_real_committed_calendar_validates_cleanly():
    result = hcv.validate_holiday_calendar()
    check("real committed holiday_calendar.json: valid", result["valid"] is True, result["errors"])
    check(
        "real committed holiday_calendar.json: calendar_id matches",
        result["calendar_id"] == "tr_official_holiday_calendar_v1",
    )
    check(
        "real committed holiday_calendar.json: year_count == 12 (2024-2035 inclusive)",
        result["year_count"] == 12,
        result["year_count"],
    )
    check(
        "real committed holiday_calendar.json: verified_year_count == 0 (PILOT READINESS ADIM 5 "
        "K3 - bilerek hiçbir resmi tatil tarihi önerilmemiştir, hepsi avukata bırakılmıştır)",
        result["verified_year_count"] == 0,
        result["verified_year_count"],
    )


def test_missing_required_top_level_field_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    del fixture["calendar_version"]
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("missing required top-level field (calendar_version) rejected", result["valid"] is False)


def test_wrong_schema_version_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["schema_version"] = 2
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("wrong schema_version rejected", result["valid"] is False)


def test_wrong_calendar_id_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["calendar_id"] = "not_the_real_id"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("wrong calendar_id (schema const) rejected", result["valid"] is False)


def test_wrong_jurisdiction_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["jurisdiction"] = "US"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("wrong jurisdiction (schema const) rejected", result["valid"] is False)


def test_calendar_version_below_minimum_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["calendar_version"] = 0
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("calendar_version < 1 rejected", result["valid"] is False)


# ================================================================
# additionalProperties: false (root + nested)
# ================================================================


def test_unknown_root_field_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["unknown_field"] = "nope"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("unknown root field rejected", result["valid"] is False)


def test_unknown_year_entry_field_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["unknown_field"] = "nope"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("unknown year_entry field rejected", result["valid"] is False)


def test_unknown_holiday_entry_field_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["holidays"][0]["unknown_field"] = "nope"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("unknown holiday_entry field rejected", result["valid"] is False)


def test_unknown_source_ref_field_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["source_refs"][0]["unknown_field"] = "nope"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("unknown source_ref field rejected", result["valid"] is False)


def test_unknown_weekend_policy_field_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["weekend_policy"]["unknown_field"] = "nope"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("unknown weekend_policy field rejected", result["valid"] is False)


def test_unknown_governance_field_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["governance"]["unknown_field"] = "nope"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("unknown governance field rejected", result["valid"] is False)


# ================================================================
# ENUM / CONST VALUES
# ================================================================


def test_unknown_holiday_kind_value_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["holidays"][0]["kind"] = "invented"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("unknown holidays[].kind value rejected", result["valid"] is False)


def test_unknown_day_type_value_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["holidays"][0]["day_type"] = "invented"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("unknown holidays[].day_type value rejected", result["valid"] is False)


def test_unknown_half_day_policy_value_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["half_day_policy"] = "invented"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("unknown half_day_policy value rejected", result["valid"] is False)


def test_weekend_policy_non_working_weekdays_wrong_const_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["weekend_policy"]["non_working_weekdays"] = [0, 6]
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("weekend_policy.non_working_weekdays != [5,6] rejected", result["valid"] is False)


def test_year_out_of_schema_range_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["year"] = 1800
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("year below schema minimum (1900) rejected", result["valid"] is False)


# ================================================================
# ORDERING / UNIQUENESS (§5.4 GAP - explicitly required)
# ================================================================


def test_years_not_ascending_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"] = list(reversed(fixture["years"]))
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("years[] not in ascending order rejected", result["valid"] is False)


def test_duplicate_year_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"].append(copy.deepcopy(fixture["years"][0]))
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("duplicate years[].year rejected", result["valid"] is False)


def test_holidays_within_year_not_ascending_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["holidays"].append({
        "date": "2026-01-01", "name": "Earlier, appended after", "kind": "national",
        "day_type": "full_day", "source_ref_index": 0, "notes": None,
    })
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("holidays[] within a year not in ascending order rejected", result["valid"] is False)


def test_duplicate_holiday_date_within_year_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["holidays"].append(copy.deepcopy(fixture["years"][0]["holidays"][0]))
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("duplicate holiday date within the same year rejected", result["valid"] is False)


def test_holiday_date_year_mismatch_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["holidays"][0]["date"] = "2025-03-12"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("holiday date whose year != the enclosing year_entry.year rejected", result["valid"] is False)


# ================================================================
# source_ref_index BOUNDS
# ================================================================


def test_source_ref_index_out_of_bounds_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["holidays"][0]["source_ref_index"] = 99
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("source_ref_index out of bounds rejected", result["valid"] is False)


def test_source_ref_index_negative_rejected_by_schema():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["holidays"][0]["source_ref_index"] = -1
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("negative source_ref_index rejected (schema minimum:0)", result["valid"] is False)


# ================================================================
# verified=True IDENTITY (source_refs>=1, nonblank verification_ref)
# ================================================================


def test_verified_without_source_refs_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["source_refs"] = []
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("verified=true with empty source_refs rejected", result["valid"] is False)


def test_verified_with_null_verification_ref_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["verification_ref"] = None
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("verified=true with verification_ref=null rejected (identity, not truthiness)", result["valid"] is False)


def test_verified_with_whitespace_only_verification_ref_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["years"][0]["verification_ref"] = "   \t  "
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check(
        "verified=true with whitespace-only verification_ref rejected (identity, not truthiness)",
        result["valid"] is False,
    )


def test_unverified_year_with_no_source_refs_is_fine():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    # years[1] is already verified=false with empty source_refs/None ref.
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check(
        "an unverified (verified=false) year with empty source_refs/null verification_ref is "
        "ALLOWED (provenance identity check applies only to verified=true years)",
        result["valid"] is True,
        result["errors"],
    )


# ================================================================
# half_day_policy CONSISTENCY
# ================================================================


def test_half_day_under_not_decided_policy_in_verified_year_rejected():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    check("fixture precondition: half_day_policy is not_decided", fixture["half_day_policy"] == "not_decided")
    fixture["years"][0]["holidays"][0]["day_type"] = "half_day"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("half_day entry in a verified year under half_day_policy='not_decided' rejected", result["valid"] is False)


def test_half_day_under_counts_as_holiday_policy_allowed():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["half_day_policy"] = "counts_as_holiday"
    fixture["years"][0]["holidays"][0]["day_type"] = "half_day"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check("half_day entry in a verified year under half_day_policy='counts_as_holiday' allowed", result["valid"] is True, result["errors"])


def test_half_day_in_unverified_year_under_not_decided_policy_allowed():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    check("fixture precondition: half_day_policy is not_decided", fixture["half_day_policy"] == "not_decided")
    fixture["years"][1]["verified"] = False
    # source_ref_index bounds are enforced REGARDLESS of `verified` (a
    # separate, unconditional structural rule) - a source_refs entry is
    # supplied here purely so THIS probe isolates the half_day_policy
    # rule alone, without incidentally tripping the index-bounds rule.
    fixture["years"][1]["source_refs"] = [
        {"source_kind": "probe", "citation": "unverified-year probe citation", "url": None},
    ]
    fixture["years"][1]["holidays"] = [{
        "date": "2027-05-01", "name": "Unverified half-day probe", "kind": "national",
        "day_type": "half_day", "source_ref_index": 0, "notes": None,
    }]
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check(
        "half_day entry in an UNVERIFIED year under half_day_policy='not_decided' is allowed "
        "(business rule applies only to verified=true years)",
        result["valid"] is True,
        result["errors"],
    )


# ================================================================
# PHASE A (REV4.1 kanıt kapanışı) - observances[] / canonical
# registry / verified-year completeness / yeni half_day_policy
# değeri. Bu testler, ui/tests katmanının BAĞIMSIZ perspektifinden
# temsili bir kapsamdır - src/holiday_calendar_validator.py'nin
# KENDİ run_self_test()'indeki T23-T51 setinin birebir tekrarı
# DEĞİLDİR.
#
# F2 REMEDIATION (Phase A bağımsız incelemesi): bu dosyanın önceki
# üç negatif observance testi VACUOUS idi - `create_valid_fixture()`
# yılı `verified:true` olduğu için tek bir observance eklenmesi
# tamlık kontrolünü tetikliyor ve fixture mutasyondan bağımsız
# olarak geçersiz oluyordu (registry kontrolü devre dışı bırakılsa
# bile testler PASS kalıyordu). Artık her test: (1) UNVERIFIED,
# yapısal olarak geçerli, tek girdili minimal bir baseline'ın
# `errors == []` verdiğini, (2) YALNIZ hedef alan mutasyona
# uğratıldığında SPESİFİK hata mesajının üretildiğini, (3) hedef
# validator (`validate_observance_registry_consistency`) devre dışı
# bırakılınca mutasyonlu fixture'ın KABUL edildiğini (yani testin
# gerçekten o kontrole dayandığını - başka bir hata onu ayakta
# tutmuyor), (4) mutasyon geri alınınca geçerliliğin döndüğünü
# doğrular. Unverified baseline, `half_day_policy=not_decided` +
# half_day confound'unu da yapısal olarak ortadan kaldırır; politika
# ayrıca açıkça `needs_review_if_deadline_day` yapılır.
# ================================================================


def _observance(observance_id, kind, day_type, legal_basis_ref, block_index=None):
    return {
        "observance_id": observance_id,
        "kind": kind,
        "day_type": day_type,
        "legal_basis_ref": legal_basis_ref,
        "block_index": block_index,
    }


def _registry_observance(observance_id, block_index=None):
    reg = hcv.CANONICAL_OBSERVANCE_REGISTRY[observance_id]
    return _observance(observance_id, reg["kind"], reg["day_type"], reg["legal_basis_ref"], block_index)


def _holiday_entry(date_value, name, observances, source_ref_index=0):
    day_types = {o["day_type"] for o in observances}
    kinds = {o["kind"] for o in observances}
    return {
        "date": date_value,
        "name": name,
        "kind": "national" if "national" in kinds else "religious",
        "day_type": "full_day" if "full_day" in day_types else "half_day",
        "source_ref_index": source_ref_index,
        "notes": None,
        "observances": observances,
    }


def _minimal_unverified_observance_fixture(entry, half_day_policy="needs_review_if_deadline_day"):
    """F2: yapısal olarak GEÇERLİ, UNVERIFIED, tek girdili observances[]
    fixture'ı. Unverified olduğu için verified-kapılı tamlık ve
    half_day_policy kontrolleri tetiklenmez -> baseline 0 hata; yalnız
    koşulsuz registry/derivation kontrolleri canlıdır."""
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["half_day_policy"] = half_day_policy
    fixture["years"][0]["verified"] = False
    fixture["years"][0]["verification_ref"] = None
    fixture["years"][0]["holidays"] = [entry]
    return fixture


def _synthetic_full_observance_year(year, ramazan_block_starts=("02-10",), kurban_block_starts=("06-10",),
                                    verified=True):
    """Tam bir observances[] yılı: 8 sabit gözlem DOĞRU ay-günde; dinî
    bloklar SENTETİK, sabit tarihlerle çakışmayan başlangıçlardan
    ardışık günlerde. Test fixture'ıdır - gerçek tatil verisi DEĞİLDİR
    (Prensip 18); production takvime hiçbir tarih yazılmaz."""
    holidays = []
    for oid, reg in hcv.CANONICAL_OBSERVANCE_REGISTRY.items():
        if reg["family"] is None:
            holidays.append(_holiday_entry(f"{year}-{reg['fixed_month_day']}", oid, [_registry_observance(oid)]))
    for family, starts in (("ramazan", ramazan_block_starts), ("kurban", kurban_block_starts)):
        for block_index, start in enumerate(starts, start=1):
            start_date = date.fromisoformat(f"{year}-{start}")
            for oid in hcv.CANONICAL_OBSERVANCE_FAMILY_IDS[family]:
                offset = hcv.CANONICAL_OBSERVANCE_REGISTRY[oid]["sequence_position"]
                holidays.append(_holiday_entry((start_date + timedelta(days=offset)).isoformat(),
                                               f"{oid} b{block_index}", [_registry_observance(oid, block_index)]))
    holidays.sort(key=lambda h: h["date"])
    return {
        "year": year,
        "verified": verified,
        "verification_ref": (f"fixture_verification_ref_{year}" if verified else None),
        "source_refs": [{"source_kind": "fixture", "citation": f"Fixture citation {year}.", "url": None}],
        "holidays": holidays,
    }


def _calendar_with_years(year_entries, half_day_policy="needs_review_if_deadline_day"):
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["half_day_policy"] = half_day_policy
    fixture["years"] = year_entries
    return fixture


def _errors_containing(result, fragment):
    return [error for error in result["errors"] if fragment in error]


def _with_registry_check_neutered(fn):
    """D.12 mutation seam: `validate_observance_registry_consistency`
    devre dışı; `finally` ile KOŞULSUZ geri yüklenir."""
    original = hcv.validate_observance_registry_consistency
    try:
        hcv.validate_observance_registry_consistency = lambda calendar: []
        return fn()
    finally:
        hcv.validate_observance_registry_consistency = original


def _non_vacuous_registry_negative(label, baseline, mutate, expected_fragment):
    """F2 ortak deseni: baseline 0 hata -> tek mutasyon -> spesifik hata ->
    registry kontrolü devre dışıyken KABUL (teeth kanıtı) -> revert PASS."""
    base_result = hcv.validate_holiday_calendar(calendar=baseline)
    check(f"{label}: unmutated baseline is fully valid (errors == [])",
          base_result["valid"] is True and base_result["errors"] == [], base_result["errors"])
    mutated = copy.deepcopy(baseline)
    mutate(mutated)
    result = hcv.validate_holiday_calendar(calendar=mutated)
    check(f"{label}: mutation rejected with the specific registry/derivation message",
          result["valid"] is False and len(_errors_containing(result, expected_fragment)) == 1,
          result["errors"])
    neutered = _with_registry_check_neutered(lambda: hcv.validate_holiday_calendar(calendar=mutated))
    check(f"{label}: NON-VACUOUS - with validate_observance_registry_consistency neutered the mutated "
          "fixture is ACCEPTED (no unrelated error would keep this test passing)",
          neutered["valid"] is True and neutered["errors"] == [], neutered["errors"])
    reverted_result = hcv.validate_holiday_calendar(calendar=baseline)
    check(f"{label}: reverting the mutation restores validity",
          reverted_result["valid"] is True and reverted_result["errors"] == [], reverted_result["errors"])


def test_observance_registry_cross_check_rejects_wrong_kind():
    baseline = _minimal_unverified_observance_fixture(
        _holiday_entry("2026-01-01", "Yılbaşı", [_registry_observance("yilbasi")]))

    def mutate(fixture):
        fixture["years"][0]["holidays"][0]["observances"][0]["kind"] = "religious"

    _non_vacuous_registry_negative(
        "F2 wrong observance kind", baseline, mutate,
        "yilbasi: kind='religious' != registry expected 'national'")


def test_observance_block_index_null_required_for_national_rejected():
    baseline = _minimal_unverified_observance_fixture(
        _holiday_entry("2026-01-01", "Yılbaşı", [_registry_observance("yilbasi")]))

    def mutate(fixture):
        fixture["years"][0]["holidays"][0]["observances"][0]["block_index"] = 1

    _non_vacuous_registry_negative(
        "F2 national block_index must be null", baseline, mutate,
        "yilbasi: block_index must be null for a national observance, got 1")


def test_top_level_day_type_inconsistent_with_observances_rejected():
    baseline = _minimal_unverified_observance_fixture(
        _holiday_entry("2026-10-28", "Cumhuriyet Bayramı Arefesi",
                       [_registry_observance("cumhuriyet_bayrami_arefe")]))

    def mutate(fixture):
        fixture["years"][0]["holidays"][0]["day_type"] = "full_day"  # inconsistent - actual is half_day

    _non_vacuous_registry_negative(
        "F2 top-level day_type inconsistent with observances[]", baseline, mutate,
        "top-level day_type='full_day' inconsistent with observances[] merge (derived='half_day')")


# ================================================================
# F1 REMEDIATION REGRESSIONS (D.1-D.11) - cross-entry duplicate,
# multi-block completeness, REV4.1 exact block-count contract, and
# the deadline load gate. Positive controls first so the negatives
# below cannot pass for an unrelated reason.
# ================================================================


def test_f1_synthetic_full_year_positive_controls():
    result_2026 = hcv.validate_holiday_calendar(calendar=_calendar_with_years([_synthetic_full_observance_year(2026)]))
    check("F1 positive control: synthetic complete verified 2026 (1 ramazan + 1 kurban block) is valid",
          result_2026["valid"] is True and result_2026["errors"] == [], result_2026["errors"])
    result_2033 = hcv.validate_holiday_calendar(calendar=_calendar_with_years(
        [_synthetic_full_observance_year(2033, ramazan_block_starts=("02-10", "12-10"))]))
    check("D.5/D.9/D.3: verified 2033 with TWO complete ramazan blocks (same observance_ids in different "
          "block_index) is valid",
          result_2033["valid"] is True and result_2033["errors"] == [], result_2033["errors"])


def test_f1_national_cross_entry_duplicate_rejected():
    year_entry = _synthetic_full_observance_year(2026)
    year_entry["holidays"].append(_holiday_entry("2026-03-03", "hayalet Zafer Bayramı",
                                                 [_registry_observance("zafer_bayrami")]))
    year_entry["holidays"].sort(key=lambda h: h["date"])
    fragment = "national observance 'zafer_bayrami' occurs 2 times across entries (dates ['2026-03-03', '2026-08-30'])"
    verified_result = hcv.validate_holiday_calendar(calendar=_calendar_with_years([year_entry]))
    check("D.1: verified 2026 with zafer_bayrami at 2026-08-30 AND phantom 2026-03-03 rejected with the "
          "cross-entry duplicate message (reported exactly once)",
          verified_result["valid"] is False and len(_errors_containing(verified_result, fragment)) == 1,
          verified_result["errors"])
    check("D.1: completeness additionally flags the phantom occurrence's wrong month-day",
          len(_errors_containing(verified_result, "'zafer_bayrami' expected at 2026-08-30, found at '2026-03-03'")) == 1,
          verified_result["errors"])
    unverified_entry = copy.deepcopy(year_entry)
    unverified_entry["verified"] = False
    unverified_entry["verification_ref"] = None
    unverified_result = hcv.validate_holiday_calendar(calendar=_calendar_with_years([unverified_entry]))
    check("D.1: the SAME duplicate is rejected in an UNVERIFIED year too (structural, unconditional)",
          unverified_result["valid"] is False and len(_errors_containing(unverified_result, fragment)) == 1,
          unverified_result["errors"])


def test_f1_religious_same_block_cross_entry_duplicate_rejected():
    year_entry = _synthetic_full_observance_year(2026)  # kurban block 1: 06-10..06-14
    year_entry["holidays"].append(_holiday_entry("2026-06-20", "hayalet Kurban 4. Gün",
                                                 [_registry_observance("kurban_bayrami_gun4", 1)]))
    year_entry["holidays"].sort(key=lambda h: h["date"])
    result = hcv.validate_holiday_calendar(calendar=_calendar_with_years([year_entry]))
    fragment = ("kurban block 1: religious observance 'kurban_bayrami_gun4' occurs 2 times across entries "
                "(dates ['2026-06-14', '2026-06-20'])")
    check("D.2: kurban_bayrami_gun4 twice within block 1 (two dates) rejected with the per-block duplicate message",
          result["valid"] is False and len(_errors_containing(result, fragment)) == 1, result["errors"])


def test_f1_two_block_year_incomplete_block_not_masked():
    year_entry = _synthetic_full_observance_year(2033, ramazan_block_starts=("02-10", "12-10"))
    year_entry["holidays"] = [h for h in year_entry["holidays"] if h["date"] != "2033-02-13"]  # drop block-1 gun3
    result = hcv.validate_holiday_calendar(calendar=_calendar_with_years([year_entry]))
    check("D.4: 2033 ramazan block 1 missing gun3 while block 2 is complete -> rejected (block 2 does not mask block 1)",
          result["valid"] is False
          and len(_errors_containing(result, "ramazan block 1 is missing 'ramazan_bayrami_gun3' (sequence_position 3)")) == 1,
          result["errors"])
    check("D.4: the complete block 2 itself produces no missing-member error",
          _errors_containing(result, "ramazan block 2 is missing") == [], result["errors"])


def test_f1_missing_whole_family_rejected():
    no_ramazan = hcv.validate_holiday_calendar(calendar=_calendar_with_years(
        [_synthetic_full_observance_year(2026, ramazan_block_starts=())]))
    check("D.6: verified 2026 with NO ramazan block rejected (contract: exactly 1)",
          no_ramazan["valid"] is False
          and len(_errors_containing(no_ramazan, "ramazan expected exactly 1 block(s) per REV4.1 contract, found 0 []")) == 1,
          no_ramazan["errors"])
    no_kurban = hcv.validate_holiday_calendar(calendar=_calendar_with_years(
        [_synthetic_full_observance_year(2026, kurban_block_starts=())]))
    check("D.7: verified 2026 with NO kurban block rejected (contract: exactly 1)",
          no_kurban["valid"] is False
          and len(_errors_containing(no_kurban, "kurban expected exactly 1 block(s) per REV4.1 contract, found 0 []")) == 1,
          no_kurban["errors"])


def test_f1_exact_block_count_contract():
    one_block_2033 = hcv.validate_holiday_calendar(calendar=_calendar_with_years(
        [_synthetic_full_observance_year(2033)]))
    check("D.8: 2033 with only ONE ramazan block rejected (contract: exactly 2)",
          one_block_2033["valid"] is False
          and len(_errors_containing(one_block_2033, "ramazan expected exactly 2 block(s) per REV4.1 contract, found 1 [1]")) == 1,
          one_block_2033["errors"])
    two_blocks_2026 = hcv.validate_holiday_calendar(calendar=_calendar_with_years(
        [_synthetic_full_observance_year(2026, ramazan_block_starts=("02-10", "12-10"))]))
    check("D.10: 2026 with TWO ramazan blocks rejected (contract: exactly 1)",
          two_blocks_2026["valid"] is False
          and len(_errors_containing(two_blocks_2026, "ramazan expected exactly 1 block(s) per REV4.1 contract, found 2 [1, 2]")) == 1,
          two_blocks_2026["errors"])
    check("contract table: exactly 12 supported years 2024-2035, ramazan 2033 == 2, every other cell == 1",
          hcv.REV41_BLOCK_COUNT_SUPPORTED_YEARS == tuple(range(2024, 2036))
          and hcv.REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT["ramazan"][2033] == 2
          and all(v == 1 for y, v in hcv.REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT["ramazan"].items() if y != 2033)
          and all(v == 1 for v in hcv.REV41_EXPECTED_RELIGIOUS_BLOCK_COUNT["kurban"].values()))


def test_f1_year_outside_contract_range_fail_closed():
    verified_2036 = hcv.validate_holiday_calendar(calendar=_calendar_with_years(
        [_synthetic_full_observance_year(2036)]))
    check("verified observances[] year 2036 (outside 2024-2035) refused fail-closed - no silent block-count guess",
          verified_2036["valid"] is False
          and len(_errors_containing(verified_2036, "no exact religious block-count contract for year 2036")) == 1,
          verified_2036["errors"])
    unverified_2036 = hcv.validate_holiday_calendar(calendar=_calendar_with_years(
        [_synthetic_full_observance_year(2036, verified=False)]))
    check("UNVERIFIED observances[] year 2036 accepted (the contract gate is verified-only)",
          unverified_2036["valid"] is True and unverified_2036["errors"] == [], unverified_2036["errors"])


def test_f1_phantom_duplicate_never_reaches_deadline_holiday_dates():
    """D.11: the phantom duplicate is rejected by the validator, so
    deadline_calculator.load_holiday_calendar() (validate-then-derive)
    raises and holiday_dates is never derived from it."""
    clean_entry = _synthetic_full_observance_year(2026)
    phantom_entry = copy.deepcopy(clean_entry)
    phantom_entry["holidays"].append(_holiday_entry("2026-03-03", "hayalet Zafer Bayramı",
                                                    [_registry_observance("zafer_bayrami")]))
    phantom_entry["holidays"].sort(key=lambda h: h["date"])
    with tempfile.TemporaryDirectory() as tmp:
        clean_path = Path(tmp) / "clean_calendar.json"
        phantom_path = Path(tmp) / "phantom_calendar.json"
        clean_path.write_text(json.dumps(_calendar_with_years([clean_entry]), ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        phantom_path.write_text(json.dumps(_calendar_with_years([phantom_entry]), ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        loaded_clean = dc.load_holiday_calendar(clean_path)
        check("D.11 positive control: the clean synthetic calendar loads through deadline_calculator and derives "
              "2026-08-30 into holiday_dates",
              date(2026, 8, 30) in loaded_clean["holiday_dates"] and date(2026, 3, 3) not in loaded_clean["holiday_dates"]
              and loaded_clean["covered_verified_years"] == {2026})
        raised = None
        try:
            dc.load_holiday_calendar(phantom_path)
        except dc.DeadlineCalculatorError as error:
            raised = error
        except Exception as error:  # noqa: BLE001 - report the unexpected type as a failure
            check("D.11: phantom calendar raises DeadlineCalculatorError (not another type)", False,
                  f"unexpected {type(error).__name__}: {error!r}")
            return
        check("D.11: phantom-duplicate calendar is REFUSED by deadline_calculator.load_holiday_calendar()",
              raised is not None)
        check("D.11: the refusal carries the cross-entry duplicate message (not merely a schema error)",
              raised is not None and "national observance 'zafer_bayrami' occurs 2 times across entries" in str(raised),
              str(raised)[:300] if raised is not None else "no exception")


def test_half_day_under_needs_review_if_deadline_day_policy_allowed():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["half_day_policy"] = "needs_review_if_deadline_day"
    fixture["years"][0]["holidays"][0]["day_type"] = "half_day"
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check(
        "half_day entry in a verified year under half_day_policy='needs_review_if_deadline_day' allowed",
        result["valid"] is True, result["errors"],
    )


# ================================================================
# DISK LOAD / MISSING FILE / raise_on_error
# ================================================================


def test_disk_loaded_fixture_validates():
    fixture = hcv.create_valid_fixture()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "disk_fixture.json"
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(fixture, file, ensure_ascii=False)
        loaded = hcv.load_calendar(tmp_path)
        result = hcv.validate_holiday_calendar(calendar=loaded)
        check("disk-loaded fixture (tempdir-isolated) validates", result["valid"] is True, result["errors"])


def test_missing_calendar_file_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        missing_path = Path(tmp) / "does_not_exist.json"
        expect_raises(
            FileNotFoundError,
            lambda: hcv.load_calendar(missing_path),
            "missing calendar file fails closed (FileNotFoundError)",
        )


def test_raise_on_error_raises_typed_exception():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["schema_version"] = 2
    expect_raises(
        hcv.HolidayCalendarValidationError,
        lambda: hcv.validate_holiday_calendar(calendar=fixture, raise_on_error=True),
        "raise_on_error=True raises HolidayCalendarValidationError",
    )


def test_raise_on_error_false_does_not_raise():
    fixture = copy.deepcopy(hcv.create_valid_fixture())
    fixture["schema_version"] = 2
    result = hcv.validate_holiday_calendar(calendar=fixture, raise_on_error=False)
    check("raise_on_error=False (default) returns a result dict instead of raising", result["valid"] is False)


# ================================================================
# INDEPENDENT, HAND-WRITTEN GOLDEN FIXTURE (totoloji kırıcı)
# ================================================================


def test_independent_hand_written_golden_fixture_validates():
    golden = {
        "schema_version": 1,
        "calendar_id": "tr_official_holiday_calendar_v1",
        "calendar_version": 3,
        "effective_from": "2030-06-15",
        "jurisdiction": "TR",
        "weekend_policy": {"non_working_weekdays": [5, 6], "notes": "independent golden fixture"},
        "half_day_policy": "counts_as_working_day",
        "years": [
            {
                "year": 2030, "verified": True, "verification_ref": "golden_ref_2030",
                "source_refs": [
                    {"source_kind": "golden", "citation": "golden citation A", "url": None},
                    {"source_kind": "golden", "citation": "golden citation B", "url": "https://example.invalid"},
                ],
                "holidays": [
                    {
                        "date": "2030-04-23", "name": "Golden holiday A", "kind": "national",
                        "day_type": "full_day", "source_ref_index": 0, "notes": None,
                    },
                    {
                        "date": "2030-10-29", "name": "Golden holiday B", "kind": "national",
                        "day_type": "half_day", "source_ref_index": 1, "notes": "half day, counted as working"
                    },
                ],
            },
            {
                "year": 2031, "verified": False, "verification_ref": None,
                "source_refs": [], "holidays": [],
            },
        ],
        "governance": {
            "change_approval": "golden", "verification_authority": "golden", "notes": None,
        },
        "notes": None,
    }
    result = hcv.validate_holiday_calendar(calendar=golden)
    check(
        "independent, hand-written golden fixture (not derived from create_valid_fixture()) "
        "validates cleanly",
        result["valid"] is True,
        result["errors"],
    )
    check("golden fixture: year_count == 2", result["year_count"] == 2)
    check("golden fixture: verified_year_count == 1", result["verified_year_count"] == 1)


def test_golden_fixture_and_create_valid_fixture_are_genuinely_different_objects():
    golden_years = {2030, 2031}
    fixture_years = {entry["year"] for entry in hcv.create_valid_fixture()["years"]}
    check(
        "the golden fixture's year set is genuinely disjoint from create_valid_fixture()'s "
        "(proves the golden fixture is NOT structurally derived from the same source)",
        golden_years.isdisjoint(fixture_years),
        f"golden={golden_years!r} fixture={fixture_years!r}",
    )


# ================================================================
# DATA-TREE INVARIANCE
# ================================================================


def test_module_self_test_does_not_touch_real_data_tree():
    before = _snapshot_data_tree()
    hcv.run_self_test()
    after = _snapshot_data_tree()
    check("holiday_calendar_validator.run_self_test() leaves the real data/ tree byte-unchanged", before == after)


def run_self_test():
    before_data_snapshot = _snapshot_data_tree()

    test_valid_fixture_schema_and_business_rules_pass()
    test_real_committed_calendar_validates_cleanly()
    test_missing_required_top_level_field_rejected()
    test_wrong_schema_version_rejected()
    test_wrong_calendar_id_rejected()
    test_wrong_jurisdiction_rejected()
    test_calendar_version_below_minimum_rejected()

    test_unknown_root_field_rejected()
    test_unknown_year_entry_field_rejected()
    test_unknown_holiday_entry_field_rejected()
    test_unknown_source_ref_field_rejected()
    test_unknown_weekend_policy_field_rejected()
    test_unknown_governance_field_rejected()

    test_unknown_holiday_kind_value_rejected()
    test_unknown_day_type_value_rejected()
    test_unknown_half_day_policy_value_rejected()
    test_weekend_policy_non_working_weekdays_wrong_const_rejected()
    test_year_out_of_schema_range_rejected()

    test_years_not_ascending_rejected()
    test_duplicate_year_rejected()
    test_holidays_within_year_not_ascending_rejected()
    test_duplicate_holiday_date_within_year_rejected()
    test_holiday_date_year_mismatch_rejected()

    test_source_ref_index_out_of_bounds_rejected()
    test_source_ref_index_negative_rejected_by_schema()

    test_verified_without_source_refs_rejected()
    test_verified_with_null_verification_ref_rejected()
    test_verified_with_whitespace_only_verification_ref_rejected()
    test_unverified_year_with_no_source_refs_is_fine()

    test_half_day_under_not_decided_policy_in_verified_year_rejected()
    test_half_day_under_counts_as_holiday_policy_allowed()
    test_half_day_in_unverified_year_under_not_decided_policy_allowed()

    test_observance_registry_cross_check_rejects_wrong_kind()
    test_observance_block_index_null_required_for_national_rejected()
    test_top_level_day_type_inconsistent_with_observances_rejected()
    test_half_day_under_needs_review_if_deadline_day_policy_allowed()

    test_f1_synthetic_full_year_positive_controls()
    test_f1_national_cross_entry_duplicate_rejected()
    test_f1_religious_same_block_cross_entry_duplicate_rejected()
    test_f1_two_block_year_incomplete_block_not_masked()
    test_f1_missing_whole_family_rejected()
    test_f1_exact_block_count_contract()
    test_f1_year_outside_contract_range_fail_closed()
    test_f1_phantom_duplicate_never_reaches_deadline_holiday_dates()

    test_disk_loaded_fixture_validates()
    test_missing_calendar_file_fails_closed()
    test_raise_on_error_raises_typed_exception()
    test_raise_on_error_false_does_not_raise()

    test_independent_hand_written_golden_fixture_validates()
    test_golden_fixture_and_create_valid_fixture_are_genuinely_different_objects()

    test_module_self_test_does_not_touch_real_data_tree()

    after_data_snapshot = _snapshot_data_tree()
    check(
        "this entire test module: real data/ tree byte-unchanged across the full run",
        before_data_snapshot == after_data_snapshot,
    )

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
