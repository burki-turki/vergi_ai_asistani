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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

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
