# ============================================================
# PILOT READINESS ADIM 5 - isolated tests for the holiday-calendar
# DERIVATION/COMPUTATION layer of src/deadline_calculator.py:
# `derive_effective_holiday_calendar()`, `load_holiday_calendar()`,
# and `calculate_rule_deadline()`'s reordered, calendar-coverage-gated
# `next_business_day_if_holiday` logic (bağımsız inceleme §5.1'in
# döngüsellik çözümü).
#
# Bu dosya PURE'dür - hiçbir sentetik case dizini, hiçbir PostgreSQL,
# hiçbir mutation coordinator kullanmaz; yalnız deterministik
# hesaplama/türetme katmanını dener. Identity/replay/race senaryoları
# (S15-S22 - bkz. exact-scope taslağının test planı) YA
# `test_generation_mutation_facade_isolated.py`'de (I3/I4/K7/M
# senaryoları) YA DA bu dosyanın DIŞINDA test edilir; bu ayrım
# BİLİNÇLİDİR (bağımsız inceleme, "keep it pure - no case dir, no PG").
#
# Run: python -m ui.tests.test_deadline_calendar_derivation_isolated
# ============================================================

import copy
import hashlib
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import deadline_calculator as dc          # noqa: E402
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


# ----------------------------------------------------------------
# Production rule (read-only) - IYUK 30-day, next_business_day_if_holiday,
# recess-eligible. Matches deadline_calculator.py's own T01-T09.
# ----------------------------------------------------------------

RULE = dc.load_production_rule()

# A synthetic exact_duration rule (S14) - end_day_policy bypasses the
# calendar coverage gate ENTIRELY, even in an uncovered year.
EXACT_DURATION_RULE = copy.deepcopy(RULE)
EXACT_DURATION_RULE["end_day_policy"] = "exact_duration"


def _calendar(holiday_dates=None, covered_verified_years=None):
    return {
        "holiday_dates": set(holiday_dates or []),
        "covered_verified_years": set(covered_verified_years or []),
    }


# ================================================================
# S1-S9 - BINDING STOP-CONDITION SCENARIOS (exact-scope taslağının
# §5.1 test planı - registry üzerinden üretilen equivalents)
# ================================================================


def test_s1_covered_year_no_holidays_calculated():
    result = dc.calculate_rule_deadline(
        anchor_date="2026-02-10", rule=RULE,
        holiday_calendar=_calendar(covered_verified_years={2026}),
        judicial_recess_applicable=True,
    )
    check(
        "S1: covered year, no holidays -> calculated 2026-03-12",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2026-03-12",
        result,
    )


def test_s2_covered_year_with_holiday_shift():
    result = dc.calculate_rule_deadline(
        anchor_date="2026-02-10", rule=RULE,
        holiday_calendar=_calendar(holiday_dates={date(2026, 3, 12)}, covered_verified_years={2026}),
        judicial_recess_applicable=True,
    )
    check(
        "S2: covered year, 2026-03-12 marked holiday -> calculated 2026-03-13",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2026-03-13",
        result,
    )


def test_s3_same_year_not_verified_needs_review():
    result = dc.calculate_rule_deadline(
        anchor_date="2026-02-10", rule=RULE,
        holiday_calendar=_calendar(holiday_dates={date(2026, 3, 12)}, covered_verified_years=set()),
        judicial_recess_applicable=True,
    )
    check(
        "S3: SAME holiday content but 2026 NOT verified -> needs_review, calculated_deadline=None",
        result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None,
        result,
    )


def test_s4_year_absent_from_calendar_needs_review():
    result = dc.calculate_rule_deadline(
        anchor_date="2026-02-10", rule=RULE,
        holiday_calendar=_calendar(),  # 2026 not present at all
        judicial_recess_applicable=True,
    )
    check(
        "S4: 2026 entirely absent from covered_verified_years -> needs_review (same fail-closed "
        "path as S3 - §3.3: absence and unverified presence are the SAME path)",
        result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None,
        result,
    )


def test_s5_anchor_near_year_boundary_only_first_year_covered():
    # 2026-12-20 + 30 = 2027-01-19 (crosses into 2027).
    result = dc.calculate_rule_deadline(
        anchor_date="2026-12-20", rule=RULE,
        holiday_calendar=_calendar(covered_verified_years={2026}),
        judicial_recess_applicable=True,
    )
    check(
        "S5: anchor+30 crosses into 2027, only 2026 verified -> needs_review",
        result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None,
        result,
    )


def test_s6_anchor_near_year_boundary_both_years_covered():
    result = dc.calculate_rule_deadline(
        anchor_date="2026-12-20", rule=RULE,
        holiday_calendar=_calendar(covered_verified_years={2026, 2027}),
        judicial_recess_applicable=True,
    )
    check(
        "S6: anchor+30 crosses into 2027, BOTH 2026 and 2027 verified -> calculated 2027-01-19",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2027-01-19",
        result,
    )


def test_s7_half_day_under_not_decided_policy_rejected_by_validator():
    # calculate_rule_deadline() itself does not know about half_day_policy
    # semantics (that belongs to derive_effective_holiday_calendar()) -
    # S7 is properly a VALIDATOR-layer scenario (§2.3 rule 8).
    fixture = hcv.create_valid_fixture()
    fixture["years"][0]["holidays"][0]["day_type"] = "half_day"
    check("fixture precondition: half_day_policy is not_decided", fixture["half_day_policy"] == "not_decided")
    result = hcv.validate_holiday_calendar(calendar=fixture)
    check(
        "S7: half_day entry in a verified year under half_day_policy='not_decided' -> validator "
        "ERROR (§2.3 rule 8)",
        result["valid"] is False,
        result["errors"],
    )


def test_s8_half_day_under_counts_as_working_day_not_counted_as_holiday():
    document = {
        "schema_version": 1, "calendar_id": "tr_official_holiday_calendar_v1", "calendar_version": 1,
        "effective_from": "2026-01-01", "jurisdiction": "TR",
        "weekend_policy": {"non_working_weekdays": [5, 6], "notes": None},
        "half_day_policy": "counts_as_working_day",
        "years": [{
            "year": 2026, "verified": True, "verification_ref": "s8_ref",
            "source_refs": [{"source_kind": "s8", "citation": "s8 citation", "url": None}],
            "holidays": [{
                "date": "2026-03-12", "name": "S8 half-day probe", "kind": "national",
                "day_type": "half_day", "source_ref_index": 0, "notes": None,
            }],
        }],
        "governance": {"change_approval": "s8", "verification_authority": "s8", "notes": None},
        "notes": None,
    }
    hcv.attach_fixture_verification(document, seed="s8")  # ADIM 6: verified yıl kayda bağlanır
    schema_check = hcv.validate_holiday_calendar(calendar=document)
    check("S8 fixture precondition: schema-valid", schema_check["valid"] is True, schema_check["errors"])
    derived = dc.derive_effective_holiday_calendar(document)
    check(
        "S8: half_day + half_day_policy='counts_as_working_day' -> the date is NOT in holiday_dates "
        "(not counted as a holiday for shifting purposes)",
        date(2026, 3, 12) not in derived["holiday_dates"],
        derived,
    )
    result = dc.calculate_rule_deadline(
        anchor_date="2026-02-10", rule=RULE, holiday_calendar=derived, judicial_recess_applicable=True,
    )
    check(
        "S8b: end-to-end - the half-day-as-working-day date does not trigger a shift -> "
        "calculated 2026-03-12 (unshifted)",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2026-03-12",
        result,
    )


def test_s9_production_calendar_full_coverage_calculated():
    # PILOT READINESS ADIM 6: üretim takvimi artık 2024-2035 için imzalı
    # avukat doğrulamasıyla (HC-LAWYER-VERIFY-v1) verified=true - Adım 5'in
    # "her senaryo needs_review" placeholder davranışı TERSİNE döndü. Her
    # beklenen tarih elle doğrulandı (hafta içi, tatil değil); mali tatil
    # penceresine (1-20 Temmuz) veya adli tatile dokunan anchor'lar bilinçli
    # olarak SEÇİLMEDİ - bu test yalnız takvim kapısını izole eder.
    loaded = dc.load_holiday_calendar()  # real, committed production calendar (read-only)
    check(
        "S9 precondition: the real production calendar covers 2024-2035 (12 lawyer-verified years)",
        loaded["covered_verified_years"] == set(range(2024, 2036)),
        loaded["covered_verified_years"],
    )
    expected = {
        "2026-02-10": "2026-03-12",  # Thursday, no holiday
        "2024-01-01": "2024-01-31",  # Wednesday, no holiday (anchor itself Yılbaşı - anchor day is not counted)
        "2035-12-01": "2035-12-31",  # Monday, no holiday
        "2026-12-20": "2027-01-19",  # crosses into 2027 - both years covered
    }
    for anchor, expected_deadline in expected.items():
        result = dc.calculate_rule_deadline(
            anchor_date=anchor, rule=RULE, holiday_calendar=loaded, judicial_recess_applicable=True,
        )
        check(
            f"S9: production calendar (lawyer-verified 2024-2035) -> calculated {expected_deadline} for "
            f"anchor={anchor}",
            result["calculation_state"] == "calculated" and result["calculated_deadline"] == expected_deadline,
            result,
        )


def test_s16_production_half_day_only_final_day_needs_review():
    # Lawyer's policy needs_review_if_deadline_day is LIVE: 2026-09-28 + 30 =
    # 2026-10-28 (Cumhuriyet Bayramı arefesi, yalnız yarım gün) -> fail-closed
    # needs_review with the fixed reason literal, never a silent date.
    loaded = dc.load_holiday_calendar()
    result = dc.calculate_rule_deadline(
        anchor_date="2026-09-28", rule=RULE, holiday_calendar=loaded, judicial_recess_applicable=True,
    )
    check(
        "S16: production calendar - final day 2026-10-28 is half-day-only -> needs_review, reason "
        "holiday_calendar_half_day_deadline_requires_review, calculated_deadline=None",
        result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None
        and result["reason"] == "holiday_calendar_half_day_deadline_requires_review",
        result,
    )


def test_s17_production_collision_dates_full_day_wins_and_shift():
    # 2027-05-19 = Kurban Bayramı 4. Gün / Atatürk'ü Anma (full+full collision) ->
    # shifted to 2027-05-20 (Thursday). 2029-04-23 = Ulusal Egemenlik (full) /
    # Kurban arefesi (half) -> full day wins; then Kurban 1-4 (24-27 Nisan,
    # Tue-Fri) + weekend -> 2029-04-30 (Monday).
    loaded = dc.load_holiday_calendar()
    result = dc.calculate_rule_deadline(
        anchor_date="2027-04-19", rule=RULE, holiday_calendar=loaded, judicial_recess_applicable=True,
    )
    check(
        "S17a: production calendar - base 2027-05-19 (full+full collision) -> calculated 2027-05-20, "
        "holiday_adjustment_applied=True",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2027-05-20"
        and result["holiday_adjustment_applied"] is True,
        result,
    )
    result = dc.calculate_rule_deadline(
        anchor_date="2029-03-24", rule=RULE, holiday_calendar=loaded, judicial_recess_applicable=True,
    )
    check(
        "S17b: production calendar - base 2029-04-23 (full+half collision, full wins) -> shifted "
        "across Kurban 1-4 and the weekend -> calculated 2029-04-30 (never needs_review for the "
        "half-day arefe on a collision date)",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2029-04-30",
        result,
    )


def test_s18_production_full_day_holiday_shifts():
    loaded = dc.load_holiday_calendar()
    result = dc.calculate_rule_deadline(
        anchor_date="2026-03-24", rule=RULE, holiday_calendar=loaded, judicial_recess_applicable=True,
    )
    check(
        "S18a: production calendar - base 2026-04-23 (Ulusal Egemenlik, Thursday) -> calculated 2026-04-24",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2026-04-24",
        result,
    )
    result = dc.calculate_rule_deadline(
        anchor_date="2026-04-27", rule=RULE, holiday_calendar=loaded, judicial_recess_applicable=True,
    )
    check(
        "S18b: production calendar - base 2026-05-27 (Kurban 1. Gün) -> Kurban 2/3 (Thu/Fri), Kurban 4 + "
        "weekend (Sat/Sun) -> calculated 2026-06-01 (Monday)",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2026-06-01",
        result,
    )


def test_s19_production_cross_year_shift_both_years_verified():
    loaded = dc.load_holiday_calendar()
    result = dc.calculate_rule_deadline(
        anchor_date="2033-12-02", rule=RULE, holiday_calendar=loaded, judicial_recess_applicable=True,
    )
    check(
        "S19: production calendar - base 2034-01-01 (Sunday + Yılbaşı) -> calculated 2034-01-02 "
        "(2033 AND 2034 both lawyer-verified; shift may cross the year boundary)",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2034-01-02",
        result,
    )


# ================================================================
# §5.1 GAP (independent scope review) - HOLIDAY SHIFT CROSSING INTO
# AN UNCOVERED YEAR. This is the scenario the independent review
# EXPLICITLY required: a REAL holiday shift (not merely a duration
# that happens to cross a year boundary) pushes final_deadline into a
# year that is NOT covered.
# ================================================================


def test_coverage_crossing_shift_into_uncovered_year_needs_review():
    # anchor 2026-12-01 (+30 -> 2026-12-31); 2026-12-31 marked as a
    # verified full_day holiday; the shift would land on 2027-01-01,
    # but 2027 is NOT covered -> needs_review, NEVER a silently-shifted
    # "calculated" result.
    result = dc.calculate_rule_deadline(
        anchor_date="2026-12-01", rule=RULE,
        holiday_calendar=_calendar(holiday_dates={date(2026, 12, 31)}, covered_verified_years={2026}),
        judicial_recess_applicable=False,
    )
    check(
        "coverage-crossing: a genuine holiday shift (2026-12-31 marked holiday) pushes the final "
        "date into 2027 (NOT covered) -> needs_review, calculated_deadline=None (never a leaked "
        "'calculated' result)",
        result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None,
        result,
    )


def test_coverage_crossing_shift_into_covered_year_calculated():
    # Same shape, but 2027 IS verified this time -> the shift is
    # allowed to actually complete as "calculated".
    result = dc.calculate_rule_deadline(
        anchor_date="2026-12-01", rule=RULE,
        holiday_calendar=_calendar(holiday_dates={date(2026, 12, 31)}, covered_verified_years={2026, 2027}),
        judicial_recess_applicable=False,
    )
    check(
        "coverage-crossing (POSITIVE control): SAME shift shape but 2027 verified too -> "
        "calculated 2027-01-01",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2027-01-01",
        result,
    )


def test_coverage_crossing_multi_year_chain_all_must_be_covered():
    # A chain of consecutive holidays pushing the shift several days
    # forward, potentially spanning 3 calendar years if placed at a
    # year boundary - every touched year must be covered.
    result = dc.calculate_rule_deadline(
        anchor_date="2025-12-29", rule=RULE,  # +30 = 2026-01-28 (no boundary cross by duration alone)
        holiday_calendar=_calendar(covered_verified_years={2025, 2026}),
        judicial_recess_applicable=False,
    )
    check(
        "multi-year coverage: anchor in 2025, base_deadline in 2026, both years verified -> "
        "calculated",
        result["calculation_state"] == "calculated",
        result,
    )
    # Now remove 2025 from coverage - anchor.year itself must ALSO be
    # covered (bağımsız inceleme §5.1: "anchor.year'ın da istenmesi
    # bilinçli olarak fazladan-temkinlidir").
    result_missing_anchor_year = dc.calculate_rule_deadline(
        anchor_date="2025-12-29", rule=RULE,
        holiday_calendar=_calendar(covered_verified_years={2026}),
        judicial_recess_applicable=False,
    )
    check(
        "anchor.year itself must be covered even if it is never touched by the shift - removing "
        "2025 from coverage (while keeping 2026) -> needs_review",
        result_missing_anchor_year["calculation_state"] == "needs_review"
        and result_missing_anchor_year["calculated_deadline"] is None,
        result_missing_anchor_year,
    )


# ================================================================
# S10-S14 - SEQUENCE INVARIANTS (this slice must NOT change the
# judicial-recess / weekend ordering - regression proofs)
# ================================================================


def test_s10_judicial_recess_extension_unaffected():
    # PILOT READINESS ADIM 7: anchor "2026-06-25"ten "2026-07-21"e
    # taşındı - üretim kuralı artık mali tatil (5604 sayılı Kanun m.1)
    # referansını da taşıdığından, eski anchor'ın sayım penceresi
    # (26.06-25.07) mali tatile (1-20 Temmuz) dokunuyordu; bu test
    # `case_tax_context` vermediğinden bu artık fail-closed
    # needs_review üretirdi. Yeni anchor (21 Temmuz, mali tatilin
    # BİTİMİNDEN SONRA) sayım penceresini (22 Temmuz-20 Ağustos)
    # mali tatilden TAMAMEN izole eder - bu test yalnız İYUK adli
    # tatilini test etmeye devam eder, `deadline_calculator.py`'nin
    # kendi self-test'indeki T05 ile AYNI gerekçe/desen (ampirik
    # olarak doğrulandı: calculated_deadline SONUCU DEĞİŞMEDİ, yalnız
    # base_deadline - naif 30 günlük hesabın kendisi - değişti).
    result = dc.calculate_rule_deadline(
        anchor_date="2026-07-21", rule=RULE,
        holiday_calendar=_calendar(covered_verified_years={2026}),
        judicial_recess_applicable=True,
    )
    check(
        "S10: judicial recess extension (base 2026-08-20 -> 2026-09-07) unaffected by this slice",
        result["base_deadline"] == "2026-08-20" and result["calculated_deadline"] == "2026-09-07"
        and result["judicial_recess_applied"] is True,
        result,
    )


def test_s11_recess_ambiguity_precedes_calendar_gate():
    # judicial_recess_applicable=None with an EMPTY/uncovered calendar -
    # the recess ambiguity check must fire FIRST (same needs_review
    # state, but via a DIFFERENT code path - proven by the fact that
    # even a garbage calendar does not change the outcome).
    result = dc.calculate_rule_deadline(
        anchor_date="2026-06-25", rule=RULE,
        holiday_calendar=_calendar(),  # deliberately empty/uncovered
        judicial_recess_applicable=None,
    )
    check(
        "S11: judicial_recess_applicable=None -> needs_review REGARDLESS of calendar coverage "
        "(recess ambiguity check precedes the calendar-coverage gate)",
        result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None,
        result,
    )


def test_s12_recess_extension_date_itself_a_holiday():
    # 7 Eylül'ün kendisi tatil ise, ilk sonraki iş gününe (8 Eylül,
    # Salı) kaydırılmalı - kaydırma EN SONDA çalışır.
    # PILOT READINESS ADIM 7: anchor S10 ile AYNI gerekçeyle
    # "2026-07-21"e taşındı (mali tatilden izole - bkz. S10'un yorumu).
    # calculated_deadline SONUCU DEĞİŞMEDİ (ampirik doğrulandı).
    result = dc.calculate_rule_deadline(
        anchor_date="2026-07-21", rule=RULE,
        holiday_calendar=_calendar(holiday_dates={date(2026, 9, 7)}, covered_verified_years={2026}),
        judicial_recess_applicable=True,
    )
    check(
        "S12: 7 Eylül (recess-extended deadline) itself marked as a holiday -> shifted forward to "
        "8 Eylül",
        result["calculated_deadline"] == "2026-09-08",
        result,
    )


def test_s13_weekend_shift_unaffected():
    result = dc.calculate_rule_deadline(
        anchor_date="2026-01-15", rule=RULE,
        holiday_calendar=_calendar(covered_verified_years={2026}),
        judicial_recess_applicable=True,
    )
    check(
        "S13: weekend shift (2026-02-14 Saturday -> 2026-02-16 Monday) unaffected by this slice",
        result["calculated_deadline"] == "2026-02-16" and result["holiday_adjustment_applied"] is True,
        result,
    )


def test_s14_exact_duration_bypasses_calendar_entirely():
    # end_day_policy='exact_duration' skips the calendar gate ENTIRELY -
    # even a completely empty/uncovered calendar produces a calculated
    # result (matches :839-846's unconditional bypass).
    result = dc.calculate_rule_deadline(
        anchor_date="2026-02-10", rule=EXACT_DURATION_RULE,
        holiday_calendar=_calendar(),  # deliberately empty/uncovered
        judicial_recess_applicable=True,
    )
    check(
        "S14: end_day_policy='exact_duration' -> calculated even with an EMPTY/uncovered calendar "
        "(the calendar gate never runs for this policy)",
        result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2026-03-12",
        result,
    )


def test_holiday_calendar_none_defaults_to_fail_closed_empty():
    # calculate_rule_deadline() accepts holiday_calendar=None (a caller
    # bug/oversight) and falls back to an empty/uncovered structure -
    # fail-closed, never a silent AttributeError or a permissive default.
    result = dc.calculate_rule_deadline(
        anchor_date="2026-02-10", rule=RULE, holiday_calendar=None, judicial_recess_applicable=True,
    )
    check(
        "holiday_calendar=None -> fail-closed empty/uncovered fallback -> needs_review, never a "
        "crash or a permissive 'calculated'",
        result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None,
        result,
    )


# ================================================================
# derive_effective_holiday_calendar() - PURE FUNCTION UNIT TESTS
# ================================================================


def test_derive_excludes_unverified_years():
    document = {
        "half_day_policy": "not_decided",
        "years": [
            {"year": 2025, "verified": False, "holidays": [
                {"date": "2025-01-01", "day_type": "full_day"},
            ]},
            {"year": 2026, "verified": True, "holidays": [
                {"date": "2026-01-01", "day_type": "full_day"},
            ]},
        ],
    }
    derived = dc.derive_effective_holiday_calendar(document)
    check(
        "derive: only the verified=true year's holidays/year are included",
        derived["covered_verified_years"] == {2026} and derived["holiday_dates"] == {date(2026, 1, 1)},
        derived,
    )


def test_derive_full_day_always_counts_half_day_policy_independent():
    document = {
        "half_day_policy": "not_decided",
        "years": [
            {"year": 2026, "verified": True, "holidays": [
                {"date": "2026-01-01", "day_type": "full_day"},
            ]},
        ],
    }
    derived = dc.derive_effective_holiday_calendar(document)
    check("derive: full_day always counts regardless of half_day_policy", date(2026, 1, 1) in derived["holiday_dates"])


def test_derive_empty_years_produces_empty_sets():
    derived = dc.derive_effective_holiday_calendar({"half_day_policy": "not_decided", "years": []})
    check(
        "derive: empty years[] -> both sets empty (not None, not an error)",
        derived["covered_verified_years"] == set() and derived["holiday_dates"] == set(),
        derived,
    )


def test_derive_malformed_date_skipped_not_crashed():
    document = {
        "half_day_policy": "not_decided",
        "years": [{"year": 2026, "verified": True, "holidays": [
            {"date": "not-a-real-date", "day_type": "full_day"},
            {"date": "2026-06-15", "day_type": "full_day"},
        ]}],
    }
    derived = dc.derive_effective_holiday_calendar(document)
    check(
        "derive: a malformed date entry is silently skipped (never crashes), the valid sibling "
        "entry still survives",
        derived["holiday_dates"] == {date(2026, 6, 15)},
        derived,
    )


def test_derive_half_day_only_dates_empty_under_existing_three_policies():
    for policy in ("not_decided", "counts_as_holiday", "counts_as_working_day"):
        document = {
            "half_day_policy": policy,
            "years": [
                {"year": 2026, "verified": True, "holidays": [
                    {"date": "2026-10-28", "day_type": "half_day"},
                ]},
            ],
        }
        derived = dc.derive_effective_holiday_calendar(document)
        check(
            f"derive: half_day_only_dates stays empty under half_day_policy={policy!r} "
            "(byte/semantic-unchanged proof)",
            derived["half_day_only_dates"] == set(),
            derived,
        )


def test_derive_half_day_only_dates_populated_under_needs_review_policy():
    document = {
        "half_day_policy": "needs_review_if_deadline_day",
        "years": [
            {"year": 2026, "verified": True, "holidays": [
                {"date": "2026-10-28", "day_type": "half_day"},
            ]},
        ],
    }
    derived = dc.derive_effective_holiday_calendar(document)
    check(
        "derive: half_day_only_dates populated under half_day_policy='needs_review_if_deadline_day'",
        derived["half_day_only_dates"] == {date(2026, 10, 28)},
        derived,
    )


def test_derive_observances_full_day_wins_merge_excludes_half_day_only():
    document = {
        "half_day_policy": "needs_review_if_deadline_day",
        "years": [
            {"year": 2029, "verified": True, "holidays": [
                {
                    "date": "2029-04-23", "day_type": "full_day",
                    "observances": [
                        {"observance_id": "kurban_bayrami_arefe", "day_type": "half_day"},
                        {"observance_id": "ulusal_egemenlik_cocuk_bayrami", "day_type": "full_day"},
                    ],
                },
            ]},
        ],
    }
    derived = dc.derive_effective_holiday_calendar(document)
    check(
        "derive: observances[] full_day+half_day collision merges to full_day "
        "(full_day wins) -> holiday_dates, NOT half_day_only_dates",
        date(2029, 4, 23) in derived["holiday_dates"]
        and date(2029, 4, 23) not in derived["half_day_only_dates"],
        derived,
    )


def test_s15_needs_review_if_deadline_day_genuine_half_day_final_needs_review():
    holiday_calendar = _calendar(covered_verified_years={2026})
    holiday_calendar["half_day_only_dates"] = {date(2026, 10, 28)}
    result = dc.calculate_rule_deadline(
        anchor_date="2026-09-28", rule=RULE,
        holiday_calendar=holiday_calendar,
        judicial_recess_applicable=True,
    )
    check(
        "S15: needs_review_if_deadline_day - genuine half-day-only final date -> needs_review, "
        "fixed reason holiday_calendar_half_day_deadline_requires_review",
        result["calculation_state"] == "needs_review"
        and result["calculated_deadline"] is None
        and result["reason"] == "holiday_calendar_half_day_deadline_requires_review",
        result,
    )


# ================================================================
# load_holiday_calendar() - integration of load+validate+derive
# ================================================================


def test_load_holiday_calendar_default_reads_real_production_file():
    loaded = dc.load_holiday_calendar()
    check(
        "load_holiday_calendar(): calendar_id matches the real production registry",
        loaded["calendar_id"] == "tr_official_holiday_calendar_v1",
        loaded,
    )
    check("load_holiday_calendar(): calendar_version is a positive int", isinstance(loaded["calendar_version"], int) and loaded["calendar_version"] >= 1)
    check("load_holiday_calendar(): source_sha256 is a 64-char hex digest", isinstance(loaded["source_sha256"], str) and len(loaded["source_sha256"]) == 64)


def test_load_holiday_calendar_missing_file_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        missing_path = Path(tmp) / "does_not_exist.json"
        expect_raises(
            FileNotFoundError,
            lambda: dc.load_holiday_calendar(missing_path),
            "load_holiday_calendar(): missing file -> FileNotFoundError, fail-closed",
        )


def test_load_holiday_calendar_invalid_content_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        invalid_path = Path(tmp) / "invalid.json"
        invalid_path.write_text('{"not": "a valid calendar"}', encoding="utf-8")
        expect_raises(
            dc.DeadlineCalculatorError,
            lambda: dc.load_holiday_calendar(invalid_path),
            "load_holiday_calendar(): schema-invalid content -> DeadlineCalculatorError, fail-closed",
        )


def test_load_holiday_calendar_corrupt_json_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        corrupt_path = Path(tmp) / "corrupt.json"
        corrupt_path.write_text("{ not json at all", encoding="utf-8")
        expect_raises(
            dc.DeadlineCalculatorError,
            lambda: dc.load_holiday_calendar(corrupt_path),
            "load_holiday_calendar(): corrupt (non-JSON) content -> DeadlineCalculatorError, fail-closed",
        )


def test_load_holiday_calendar_valid_disk_fixture_round_trips():
    fixture = hcv.create_valid_fixture()
    with tempfile.TemporaryDirectory() as tmp:
        fixture_path = Path(tmp) / "fixture.json"
        import json as _json
        fixture_path.write_text(_json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        loaded = dc.load_holiday_calendar(fixture_path)
        check(
            "load_holiday_calendar(): a valid disk fixture round-trips to the expected derived "
            "structure",
            loaded["covered_verified_years"] == {2026}
            and loaded["holiday_dates"] == {date(2026, 3, 12)}
            and loaded["calendar_version"] == 1,
            loaded,
        )


# ================================================================
# DATA-TREE INVARIANCE
# ================================================================


def run_self_test():
    before_data_snapshot = _snapshot_data_tree()

    test_s1_covered_year_no_holidays_calculated()
    test_s2_covered_year_with_holiday_shift()
    test_s3_same_year_not_verified_needs_review()
    test_s4_year_absent_from_calendar_needs_review()
    test_s5_anchor_near_year_boundary_only_first_year_covered()
    test_s6_anchor_near_year_boundary_both_years_covered()
    test_s7_half_day_under_not_decided_policy_rejected_by_validator()
    test_s8_half_day_under_counts_as_working_day_not_counted_as_holiday()
    test_s9_production_calendar_full_coverage_calculated()
    test_s16_production_half_day_only_final_day_needs_review()
    test_s17_production_collision_dates_full_day_wins_and_shift()
    test_s18_production_full_day_holiday_shifts()
    test_s19_production_cross_year_shift_both_years_verified()

    test_coverage_crossing_shift_into_uncovered_year_needs_review()
    test_coverage_crossing_shift_into_covered_year_calculated()
    test_coverage_crossing_multi_year_chain_all_must_be_covered()

    test_s10_judicial_recess_extension_unaffected()
    test_s11_recess_ambiguity_precedes_calendar_gate()
    test_s12_recess_extension_date_itself_a_holiday()
    test_s13_weekend_shift_unaffected()
    test_s14_exact_duration_bypasses_calendar_entirely()
    test_holiday_calendar_none_defaults_to_fail_closed_empty()

    test_derive_excludes_unverified_years()
    test_derive_half_day_only_dates_empty_under_existing_three_policies()
    test_derive_half_day_only_dates_populated_under_needs_review_policy()
    test_derive_observances_full_day_wins_merge_excludes_half_day_only()
    test_s15_needs_review_if_deadline_day_genuine_half_day_final_needs_review()
    test_derive_full_day_always_counts_half_day_policy_independent()
    test_derive_empty_years_produces_empty_sets()
    test_derive_malformed_date_skipped_not_crashed()

    test_load_holiday_calendar_default_reads_real_production_file()
    test_load_holiday_calendar_missing_file_fails_closed()
    test_load_holiday_calendar_invalid_content_fails_closed()
    test_load_holiday_calendar_corrupt_json_fails_closed()
    test_load_holiday_calendar_valid_disk_fixture_round_trips()

    after_data_snapshot = _snapshot_data_tree()
    check(
        "this entire test module: real data/ tree byte-unchanged across the full run (PURE - "
        "no case dir, no PostgreSQL, no writes anywhere)",
        before_data_snapshot == after_data_snapshot,
    )

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
