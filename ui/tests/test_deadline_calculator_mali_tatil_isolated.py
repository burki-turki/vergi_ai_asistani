# ============================================================
# PILOT READINESS ADIM 7 - MALİ TATİL (5604 sayılı Kanun m.1)
# src/deadline_calculator.py ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator. Bu dosya
# `deadline_calculator.py`'nin KENDİ gömülü `run_self_test()`'inin
# (T07c-T07l) sağladığı kapsamı YİNELEMEK için değil, mali tatil
# mekanizmasının (a) saf yardımcı fonksiyonlarını izole olarak, (b)
# GERÇEK, üretim `data/deadline_rules/deadline_rules.json` +
# `data/provisions.json` içeriğine karşı `calculate_rule_deadline()`
# seviyesinde, ve (c) GERÇEK `case_0001` verisi üzerinden
# `build_deadline_record()`/case.json okuma zincirinin uçtan uca
# çalıştığını KALICI, bağımsız bir regresyon paketi olarak
# doğrulamak için vardır.
#
# Gerçek `data/cases/case_0001` ağacına HİÇ DOKUNULMAZ - yalnız
# `deadline_validator.CASES_DIR` geçici bir kopyaya yönlendirilir
# (`ui/tests/test_deadline_engine_isolated.py` ile AYNI desen).
#
# Run: python ui/tests/test_deadline_calculator_mali_tatil_isolated.py
# ============================================================

import copy
import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import deadline_calculator as dc                     # noqa: E402
import deadline_validator                            # noqa: E402
import deadline_rule_selection_policy as rsp         # noqa: E402
import provision_manifest_validator as pmv           # noqa: E402
import deadline_legal_basis_resolver as lbr          # noqa: E402

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


REAL_CASE_0001 = REPO_ROOT / "data" / "cases" / "case_0001"
CASE_ID = "case_0001"
ANCHOR_EVENT_ID = "timeline_event_003"

COVERED_2026 = {
    "holiday_dates": set(),
    "covered_verified_years": {2026, 2027},
}

KDV_CONTEXT = {
    "tax_types": {"kdv"},
    "issuing_authorities": set(),
}


# ============================================================
# 1) PURE HELPER FUNCTIONS
# ============================================================

check(
    "rule_has_mali_tatil_basis(): True when the ref is present",
    dc.rule_has_mali_tatil_basis(
        {"legal_basis_refs": ["IYUK_2577_m7_1", "KANUN_5604_m1"]}
    ),
)
check(
    "rule_has_mali_tatil_basis(): False when the ref is absent",
    dc.rule_has_mali_tatil_basis({"legal_basis_refs": ["IYUK_2577_m7_1"]}) is False,
)
check(
    "rule_has_mali_tatil_basis(): False when legal_basis_refs is missing entirely",
    dc.rule_has_mali_tatil_basis({}) is False,
)

check(
    "classify_mali_tatil_tax_type(): empty/None -> unrecognized",
    dc.classify_mali_tatil_tax_type(None) == ("unrecognized", None),
)
check(
    "classify_mali_tatil_tax_type(): KDV -> included",
    dc.classify_mali_tatil_tax_type({"kdv"}) == ("included", None),
)
check(
    "classify_mali_tatil_tax_type(): ÖTV -> excluded",
    dc.classify_mali_tatil_tax_type({"özel tüketim vergisi"}) == ("excluded", "özel tüketim vergisi"),
)
check(
    "classify_mali_tatil_tax_type(): unknown free-text tax name -> unrecognized (no silent guessing)",
    dc.classify_mali_tatil_tax_type({"bilinmeyen bir vergi türü"})[0] == "unrecognized",
)
check(
    "classify_mali_tatil_tax_type(): mixed excluded+included -> mixed",
    dc.classify_mali_tatil_tax_type({"kdv", "bsmv"}) == ("mixed", None),
)

check(
    "classify_mali_tatil_authority(): empty -> not_excluded (never blocks on its own)",
    dc.classify_mali_tatil_authority(None) == ("not_excluded", None),
)
check(
    "classify_mali_tatil_authority(): unrecognized free text -> not_excluded (never blocks)",
    dc.classify_mali_tatil_authority({"bilinmeyen bir kurum adı"}) == ("not_excluded", None),
)
check(
    "classify_mali_tatil_authority(): 'gümrük' keyword -> excluded",
    dc.classify_mali_tatil_authority({"istanbul gümrük müdürlüğü"}) == ("excluded", "gümrük"),
)
check(
    "classify_mali_tatil_authority(): 'belediye' keyword -> excluded",
    dc.classify_mali_tatil_authority({"kadıköy belediyesi"}) == ("excluded", "belediye"),
)
check(
    "classify_mali_tatil_authority(): 'vergi dairesi' does NOT match any excluded keyword",
    dc.classify_mali_tatil_authority({"büyük mükellefler vergi dairesi başkanlığı"})
    == ("not_excluded", None),
)

check(
    "mali_tatil_window_for_year(): normal year (June 30 is a weekday) -> 1-20 Temmuz",
    dc.mali_tatil_window_for_year(2026, set()) == (date(2026, 7, 1), date(2026, 7, 20)),
)
check(
    "mali_tatil_window_for_year(): 2029 (30 June is a Saturday) -> start shifts to 3 Temmuz, end unchanged",
    dc.mali_tatil_window_for_year(2029, set()) == (date(2029, 7, 3), date(2029, 7, 20)),
)
check(
    "is_within_mali_tatil(): 10 Temmuz 2026 is within the window",
    dc.is_within_mali_tatil(date(2026, 7, 10), set()) is True,
)
check(
    "is_within_mali_tatil(): 21 Temmuz 2026 is NOT within the window (window is exclusive of the end+1)",
    dc.is_within_mali_tatil(date(2026, 7, 21), set()) is False,
)
check(
    "is_mali_tatil_relevant(): anchor+30 window overlapping July is relevant",
    dc.is_mali_tatil_relevant(date(2026, 6, 15), 30, set()) is True,
)
check(
    "is_mali_tatil_relevant(): anchor+30 window entirely after mali tatil ends is NOT relevant",
    dc.is_mali_tatil_relevant(date(2026, 7, 21), 30, set()) is False,
)
check(
    "is_mali_tatil_relevant(): anchor+30 window entirely before mali tatil starts is NOT relevant",
    dc.is_mali_tatil_relevant(date(2026, 1, 1), 30, set()) is False,
)

check(
    "apply_mali_tatil_pause_resume(): hand-verified pause/resume (2026-06-15 + 30 -> 2026-08-04), "
    "grace_floor_applied=False (result is well past the 21-25 Temmuz grace window)",
    dc.apply_mali_tatil_pause_resume(date(2026, 6, 15), 30, set()) == (date(2026, 8, 4), False),
)
check(
    "apply_mali_tatil_pause_resume(): m.1/6 five-day grace floor triggers (2026-06-01 + 30 -> floored "
    "to 2026-07-25), grace_floor_applied=True",
    dc.apply_mali_tatil_pause_resume(date(2026, 6, 1), 30, set()) == (date(2026, 7, 25), True),
)
check(
    "apply_mali_tatil_pause_resume(): fıkra 5 - anchor itself inside mali tatil counts from the day "
    "after mali tatil ends (2026-08-19), grace_floor_applied=False (result is past the grace window)",
    dc.apply_mali_tatil_pause_resume(date(2026, 7, 10), 30, set()) == (date(2026, 8, 19), False),
)

check(
    "get_case_issuing_authorities(): reads administrative_actions[*].issuing_authority, normalized",
    dc.get_case_issuing_authorities(
        {
            "administrative_actions": [
                {"issuing_authority": "  Büyük Mükellefler Vergi Dairesi Başkanlığı  "},
                {"issuing_authority": None},
                "not_a_dict",
            ]
        }
    )
    == {"büyük mükellefler vergi dairesi başkanlığı".casefold()},
)
check(
    "get_case_issuing_authorities(): missing administrative_actions -> empty set, no crash",
    dc.get_case_issuing_authorities({}) == set(),
)


# ============================================================
# 2) calculate_rule_deadline() AGAINST THE REAL PRODUCTION RULE
# ============================================================

rule = dc.load_production_rule()

check(
    "Production rule carries exactly 7 legal_basis_refs, including the mali tatil ref",
    len(rule.get("legal_basis_refs", [])) == 7
    and dc.MALI_TATIL_TRIGGER_REF in rule["legal_basis_refs"],
)

result = dc.calculate_rule_deadline(
    anchor_date="2026-06-15", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=False, case_tax_context=KDV_CONTEXT,
)
check(
    "Real rule: pause/resume (KDV, included) reaches calculated with the hand-verified date",
    result["calculation_state"] == "calculated" and result["calculated_deadline"] == "2026-08-04"
    and result["mali_tatil_applied"] is True,
    detail=str(result),
)

result = dc.calculate_rule_deadline(
    anchor_date="2026-06-15", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=False,
    case_tax_context={"tax_types": {"ötv"}, "issuing_authorities": set()},
)
check(
    "Real rule: ÖTV exclusion (m.1/7) -> mali tatil NOT applied, naive calendar-day result used",
    result["mali_tatil_applied"] is False
    and result["mali_tatil_exclusion_reason"] == "tax_type_excluded:ötv"
    and result["calculated_deadline"] == "2026-07-15",
    detail=str(result),
)

result = dc.calculate_rule_deadline(
    anchor_date="2026-06-15", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=False,
    case_tax_context={"tax_types": {"kdv"}, "issuing_authorities": {"ankara gümrük müdürlüğü"}},
)
check(
    "Real rule: gümrük authority exclusion overrides an otherwise-included tax_type",
    result["mali_tatil_applied"] is False
    and result["mali_tatil_exclusion_reason"] == "issuing_authority_excluded:gümrük",
    detail=str(result),
)

result = dc.calculate_rule_deadline(
    anchor_date="2026-06-15", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=False, case_tax_context=None,
)
check(
    "Real rule: missing case_tax_context entirely, in a mali-tatil-relevant window -> needs_review, "
    "no calculated_deadline (no silent 'assume included')",
    result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None,
    detail=str(result),
)

result = dc.calculate_rule_deadline(
    anchor_date="2026-06-15", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=False,
    case_tax_context={"tax_types": {"kdv", "özel tüketim vergisi"}, "issuing_authorities": set()},
)
check(
    "Real rule: mixed excluded+included tax_types -> needs_review (cannot pick a single dispute's scope)",
    result["calculation_state"] == "needs_review",
    detail=str(result),
)

# Non-leakage: a rule that does NOT carry the exact mali tatil ref must behave IDENTICALLY to
# how the whole engine behaved before this feature existed - no case_tax_context needed at all.
rule_without_ref = copy.deepcopy(rule)
rule_without_ref["legal_basis_refs"] = [
    ref for ref in rule_without_ref["legal_basis_refs"] if ref != dc.MALI_TATIL_TRIGGER_REF
]
result = dc.calculate_rule_deadline(
    anchor_date="2026-06-25", rule=rule_without_ref, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=True,
)
check(
    "Non-leakage: a rule WITHOUT the mali tatil ref reproduces the pre-Adım-7 recess-only result "
    "(base=2026-07-25, calculated=2026-09-07) with zero mali tatil interference",
    result["base_deadline"] == "2026-07-25"
    and result["calculated_deadline"] == "2026-09-07"
    and result["mali_tatil_applied"] is False
    and result["mali_tatil_exclusion_reason"] == "rule_lacks_legal_basis",
    detail=str(result),
)

rule_unknown_ref = copy.deepcopy(rule)
rule_unknown_ref["legal_basis_refs"] = [
    (ref if ref != dc.MALI_TATIL_TRIGGER_REF else "KANUN_9999_m1")
    for ref in rule_unknown_ref["legal_basis_refs"]
]
result = dc.calculate_rule_deadline(
    anchor_date="2026-06-25", rule=rule_unknown_ref, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=True,
)
check(
    "Non-leakage: a rule carrying an unrelated/unknown ref (not the real 5604 ref) also stays inert",
    result["calculated_deadline"] == "2026-09-07" and result["mali_tatil_applied"] is False,
    detail=str(result),
)


# ============================================================
# 2b) INDEPENDENT REVIEW REMEDIATION - COMBINED MALİ TATİL + ADLİ TATİL
#     PATH. anchor=2026-06-25 with a KNOWN, in-scope KDV context, on the
#     REAL production rule: the counting window crosses mali tatil
#     (1-20 Temmuz), so pause/resume shifts the provisional deadline to
#     mid-August; THAT date lands within the İYUK adli tatil window
#     (20 Temmuz-31 Ağustos), so judicial recess extension ALSO fires,
#     landing on the fixed 7 Eylül. Both mechanisms are asserted via
#     their OWN independent flags (mali_tatil_applied/
#     judicial_recess_applied), not just the final date - proving they
#     both genuinely ran, not that one silently short-circuited the
#     other.
# ============================================================

result = dc.calculate_rule_deadline(
    anchor_date="2026-06-25", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=True, case_tax_context=KDV_CONTEXT,
)
check(
    "Combined path: mali tatil pause/resume AND judicial recess extension BOTH fire on the same "
    "calculation, reaching the expected final date 2026-09-07",
    result["calculation_state"] == "calculated"
    and result["calculated_deadline"] == "2026-09-07"
    and result["mali_tatil_applied"] is True
    and result["judicial_recess_applied"] is True,
    detail=str(result),
)
check(
    "Combined path: base_deadline (naive calendar arithmetic, mali-tatil-unaware) is untouched "
    "at 2026-07-25 - only provisional/calculated reflect the mali tatil adjustment",
    result["base_deadline"] == "2026-07-25",
    detail=str(result),
)


# ============================================================
# 2c) INDEPENDENT REVIEW REMEDIATION (legal-alignment correction) -
#     "gecikme faizi"/"gecikme zammı" are NO LONGER auto-included. 5604
#     m.1/2-b's TEXT names ONLY "gecikme faizlerinin ödeme süresi"
#     ("gecikme zammı" does not appear in that fıkra's text at all - no
#     textual basis is invented for it); m.1/2-b's own mechanism (a
#     SEVEN-day extension if the last day falls within mali tatil -
#     m.1/2's "yedi gün" wording is UNCHANGED since 2007, unlike fıkra
#     6's five-day rule which WAS amended by 6661 sayılı Kanun) is, in
#     any case, DIFFERENT from fıkra 3's pause/resume mechanism that
#     Deadline Calculator V1 computes. Without lawyer confirmation that
#     either category is governed by fıkra 3 at all, BOTH must be
#     classified "unrecognized" -> fail-closed needs_review, NOT
#     silently treated as in-scope.
# ============================================================

check(
    "'gecikme faizi' is no longer in the included alias set",
    "gecikme faizi" not in dc.MALI_TATIL_INCLUDED_TAX_TYPES,
)
check(
    "'gecikme zammı' is no longer in the included alias set",
    "gecikme zammı" not in dc.MALI_TATIL_INCLUDED_TAX_TYPES,
)

result = dc.calculate_rule_deadline(
    anchor_date="2026-06-15", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=False,
    case_tax_context={"tax_types": {"gecikme faizi"}, "issuing_authorities": set()},
)
check(
    "Negative test: tax_type='gecikme faizi' -> needs_review, fail-closed (named in m.1/2-b's own "
    "text, but that fıkra's mechanism is different from fıkra 3's pause/resume; no lawyer "
    "confirmation that fıkra 3 governs this category)",
    result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None,
    detail=str(result),
)

result = dc.calculate_rule_deadline(
    anchor_date="2026-06-15", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=False,
    case_tax_context={"tax_types": {"gecikme zammı"}, "issuing_authorities": set()},
)
check(
    "Negative test: tax_type='gecikme zammı' -> needs_review, fail-closed ('gecikme zammı' does "
    "not appear in 5604 m.1/2-b's text at all - no textual basis is invented for it either way)",
    result["calculation_state"] == "needs_review" and result["calculated_deadline"] is None,
    detail=str(result),
)


# ============================================================
# 2d) LEGAL ALIGNMENT AUDIT REMEDIATION - MANDATORY SCENARIOS A-F (per
#     lawyer's opinion). Some of these are ALREADY covered above under
#     different labels (A = the "Combined path" check in section 2b;
#     C's core exclusion behavior = section 2's "gümrük authority
#     exclusion" check) - this section adds the REMAINING scenarios and
#     restates A/C explicitly with the exact numbers from the legal
#     opinion, as independent, standalone regression coverage.
# ============================================================

# --- Test A: 25 Haziran tebliğ + kapsam içi vergi + recess=True ---
# Mali tatil ara sonucu (pre-recess) 14 Ağustos; adli tatil sonrası
# final 7 Eylül.
mali_tatil_only_result, _grace_flag = dc.apply_mali_tatil_pause_resume(
    date(2026, 6, 25), 30, set()
)
check(
    "Test A precondition: mali tatil ONLY (pre-recess) intermediate result is 2026-08-14",
    mali_tatil_only_result.isoformat() == "2026-08-14",
    detail=str(mali_tatil_only_result),
)
result_a = dc.calculate_rule_deadline(
    anchor_date="2026-06-25", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=True, case_tax_context=KDV_CONTEXT,
)
check(
    "Test A: anchor=2026-06-25, in-scope tax, recess=True -> final 2026-09-07 "
    "(mali tatil ara sonucu 14 Ağustos, doğrulandı yukarıda)",
    result_a["calculation_state"] == "calculated" and result_a["calculated_deadline"] == "2026-09-07",
    detail=str(result_a),
)

# --- Test B: actual delivery WITHIN mali tatil (fıkra 5) ---
result_b = dc.calculate_rule_deadline(
    anchor_date="2026-07-10", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=True, case_tax_context=KDV_CONTEXT,
)
check(
    "Test B: tebliğ mali tatil İÇİNDE (10 Temmuz) + in-scope tax + recess=True -> final 2026-09-07 "
    "(fıkra 5: ilk sayılan gün mali tatilin bitimini izleyen 21 Temmuz'dur)",
    result_b["calculation_state"] == "calculated" and result_b["calculated_deadline"] == "2026-09-07"
    and result_b["mali_tatil_applied"] is True and result_b["judicial_recess_applied"] is True,
    detail=str(result_b),
)

# --- Test C: m.1/7 out-of-scope tax + recess=True (mali_tatil_applied=False,
#     judicial_recess_applied=True COEXIST in the same record). ---
result_c = dc.calculate_rule_deadline(
    anchor_date="2026-06-25", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=True,
    case_tax_context={"tax_types": {"ötv"}, "issuing_authorities": set()},
)
check(
    "Test C: m.1/7-excluded tax (ÖTV) + recess=True -> mali_tatil_applied=False AND "
    "judicial_recess_applied=True coexist; final 2026-09-07 (İYUK m.8/3 applies independently "
    "of mali tatil m.1/7 exclusion)",
    result_c["calculation_state"] == "calculated" and result_c["calculated_deadline"] == "2026-09-07"
    and result_c["mali_tatil_applied"] is False and result_c["judicial_recess_applied"] is True,
    detail=str(result_c),
)

# --- Test D: çalışmaya ara vermeyen mahkeme (recess=False), sonuç YALNIZ
#     m.1/6'nın 5 günlük asgari süresine dayanıyor -> needs_review. ---
result_d = dc.calculate_rule_deadline(
    anchor_date="2026-06-01", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=False, case_tax_context=KDV_CONTEXT,
)
check(
    "Test D: çalışmaya ara vermeyen mahkeme (recess=False) + sonuç yalnız m.1/6'nın beş günlük "
    "asgari süresine dayanıyor -> fail-closed needs_review (avukat teyidi olmadan bu tek "
    "mekanizmaya güvenilmiyor)",
    result_d["calculation_state"] == "needs_review" and result_d["calculated_deadline"] is None
    and result_d["mali_tatil_applied"] is True,
    detail=str(result_d),
)
check(
    "Test D: reason code explicitly names the grace-floor-without-recess-confirmation condition",
    "mali_tatil_grace_floor_unconfirmed_without_recess" in (result_d.get("reason") or ""),
    detail=str(result_d.get("reason")),
)

# --- Test E: adli tatil uygulanabilirliği bilinmiyor (None) ve sonucu
#     değiştiriyor -> needs_review. ---
result_e = dc.calculate_rule_deadline(
    anchor_date="2026-06-25", rule=rule, holiday_calendar=COVERED_2026,
    judicial_recess_applicable=None, case_tax_context=KDV_CONTEXT,
)
check(
    "Test E: mali-tatil-relevant result + judicial_recess_applicable=None -> needs_review "
    "(existing recess-ambiguity behavior, unaffected by this turn's changes)",
    result_e["calculation_state"] == "needs_review" and result_e["calculated_deadline"] is None,
    detail=str(result_e),
)

# --- Test F: İYUK m.8/2 - 7 Eylül resmî tatile/hafta sonuna denk gelirse
#     izleyen ilk çalışma gününe (8 Eylül) kayar, mali tatil + adli tatil
#     BİRLEŞİK sonucunun üzerinde de. ---
result_f = dc.calculate_rule_deadline(
    anchor_date="2026-06-25", rule=rule,
    holiday_calendar={
        "holiday_dates": {date(2026, 9, 7)},
        "covered_verified_years": {2026, 2027},
    },
    judicial_recess_applicable=True, case_tax_context=KDV_CONTEXT,
)
check(
    "Test F: 7 Eylül itself marked as a holiday, on the COMBINED mali tatil + adli tatil path, "
    "shifts forward to 2026-09-08 via the existing weekend/holiday-shift infrastructure",
    result_f["calculated_deadline"] == "2026-09-08" and result_f["holiday_adjustment_applied"] is True,
    detail=str(result_f),
)


# ============================================================
# 3) LEGAL KNOWLEDGE ENGINE - provisions.json/documents.json cross-check
#    stays valid, and the new ref resolves with activation_eligible=True
#    (this is the exact regression the pre-implementation verification
#    step was designed to prevent: an unverified ref silently making
#    EVERY deadline calculation for the production rule fall to
#    needs_review, not just mali-tatil-relevant ones).
# ============================================================

provision_check = pmv.validate_provisions_file(raise_on_error=False)
check(
    "provisions.json/documents.json cross-validation (schema + document_id references) still passes",
    provision_check["valid"] is True,
    detail=str(provision_check.get("errors")),
)

resolution = lbr.resolve_ruleset_legal_basis(
    ruleset_path=dc.DEFAULT_RULESET_PATH,
    manifest_path=dc.DEFAULT_PROVISIONS_PATH,
    temporal_mode="current",
)
rule_result = next(
    r for r in resolution["rules"] if r["rule_id"] == "iyuk_tax_court_general_lawsuit_filing"
)
check(
    "The whole production rule's legal basis remains fully verified/activation_eligible "
    "AFTER adding the mali tatil ref (not just the new ref in isolation)",
    rule_result.get("all_resolved") is True
    and rule_result.get("all_basis_verified") is True
    and rule_result.get("activation_eligible") is True
    and rule_result.get("legal_basis_count") == 7,
    detail=str(rule_result),
)


# ============================================================
# 4) END-TO-END VIA build_deadline_record() ON THE REAL, UNMODIFIED
#    case_0001 case.json (real dispute_item.tax_type='KDV') - proves the
#    case.json -> tax_context wiring (load_case -> get_case_tax_types/
#    get_case_issuing_authorities) is ACTUALLY invoked on real
#    production-shaped data, not just on hand-built synthetic dicts.
#
#    `anchor_event`/`selection` are hand-constructed here (verified,
#    exact, July-adjacent) rather than produced via
#    `select_for_case_event()`/`load_canonical_timeline()` - satisfying
#    the FULL timeline/fact cross-validation chain (structured-date
#    support, verification-state-vs-source-facts consistency,
#    chronological ordering of sibling events) to get a genuinely
#    verified July anchor is a SEPARATE, already-covered concern
#    (Fact Verification Workflow, LOCKED); this test targets ONLY
#    `build_deadline_record()`'s own case.json-loading wiring, which is
#    what Pilot Readiness Adım 7 actually changed. `case_id`/
#    `anchor_event_id`/`selected_rule` are the SAME real values
#    `build_case_deadline_analysis()` would normally supply.
# ============================================================

_tmp_root = Path(tempfile.mkdtemp(prefix="vergi_mali_tatil_isolated_"))
_tmp_cases = _tmp_root / "cases"
_tmp_cases.mkdir(parents=True)

_original_cases_dir = deadline_validator.CASES_DIR

try:
    case_dir = _tmp_cases / CASE_ID
    shutil.copytree(REAL_CASE_0001, case_dir)

    deadline_validator.CASES_DIR = _tmp_cases

    anchor_event = {
        "event_id": ANCHOR_EVENT_ID,
        "event_type": "notification_date",
        "date": "2026-06-15",
        "date_precision": "exact",
        "verification_state": "verified",
        "confidence": 0.95,
    }

    selection = {
        "selection_state": "selected",
        "calculation_allowed": True,
        "selected_rule": rule,
    }

    # `dc.load_holiday_calendar()` (üretim `holiday_calendar.json`) HENÜZ
    # HİÇBİR yılı `verified:true` içermez (Adım 5 checkpoint - Adım 6
    # avukat doğrulamasını bekliyor); bu test yalnız mali tatil
    # (Adım 7) wiring'ini izole etmek istediği için, Adım 5'in AYRI
    # "uncovered years" kapısına takılmamak amacıyla synthetic,
    # 2026/2027 için `verified:true` sayılan bir takvim kullanılır -
    # diğer tüm testlerde de zaten kullanılan AYNI `COVERED_2026`.

    deadline_record = dc.build_deadline_record(
        case_id=CASE_ID, anchor_event=anchor_event, selection=selection,
        ruleset_path=dc.DEFAULT_RULESET_PATH, holiday_calendar=COVERED_2026,
        judicial_recess_applicable=False,
    )
    check(
        "End-to-end (real case_0001 copy, real case.json dispute_item.tax_type='KDV'): "
        "build_deadline_record() reaches 'calculated' WITHOUT any test manually constructing "
        "case_tax_context - the wiring inside build_deadline_record() itself loaded case.json "
        "and classified KDV as included",
        deadline_record["calculation_state"] == "calculated"
        and deadline_record["calculated_deadline"] == "2026-08-04",
        detail=str(deadline_record),
    )
    check(
        "End-to-end: the final schema-validated record notes mali tatil adjustment "
        "(internal-only 'mali_tatil_applied' key correctly reflected into the public 'notes' field)",
        "mali_tatil_adjustment=applied" in (deadline_record.get("notes") or ""),
        detail=str(deadline_record.get("notes")),
    )

    # Now flip the real case_0001 copy's dispute_item to an excluded tax type and confirm
    # the SAME end-to-end wiring correctly withholds mali tatil.
    case_json_path = case_dir / "case.json"
    with open(case_json_path, "r", encoding="utf-8") as f:
        case_data = json.load(f)
    for item in case_data.get("dispute_items", []):
        item["tax_type"] = "Özel Tüketim Vergisi"
    with open(case_json_path, "w", encoding="utf-8") as f:
        json.dump(case_data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    deadline_record_otv = dc.build_deadline_record(
        case_id=CASE_ID, anchor_event=anchor_event, selection=selection,
        ruleset_path=dc.DEFAULT_RULESET_PATH, holiday_calendar=COVERED_2026,
        judicial_recess_applicable=False,
    )
    check(
        "End-to-end: flipping the real case.json dispute_item to 'Özel Tüketim Vergisi' "
        "correctly withholds mali tatil via the SAME real-file wiring (naive calendar-day result)",
        deadline_record_otv["calculation_state"] == "calculated"
        and deadline_record_otv["calculated_deadline"] == "2026-07-15",
        detail=str(deadline_record_otv),
    )
finally:
    deadline_validator.CASES_DIR = _original_cases_dir
    shutil.rmtree(_tmp_root, ignore_errors=True)


# ============================================================
# 5) INDEPENDENT REVIEW REMEDIATION - UNICODE END-TO-END SCENARIOS
#    (a)-(e), via the REAL build_deadline_record() -> load_case() ->
#    get_case_tax_types_for_mali_tatil()/get_case_issuing_authorities()
#    wiring on a REAL case_0001-shaped case.json - not direct,
#    hand-built dict calls to classify_mali_tatil_*(). Each scenario
#    gets its OWN fresh case_0001 copy to avoid coupling with section
#    4's mutations.
# ============================================================

_unicode_anchor_event = {
    "event_id": ANCHOR_EVENT_ID, "event_type": "notification_date",
    "date": "2026-06-15", "date_precision": "exact",
    "verification_state": "verified", "confidence": 0.95,
}
_unicode_selection = {
    "selection_state": "selected", "calculation_allowed": True, "selected_rule": rule,
}


def _run_unicode_scenario(tax_type=None, issuing_authority=None):
    """Fresh, fully isolated case_0001 copy (own tempdir, own CASES_DIR
    redirect, cleaned up before returning) - the copied case.json keeps
    its OWN, unchanged `case_id` ('case_0001') so `deadline_validator.
    load_case()`'s internal case_id cross-check never trips; only the
    directory's PARENT (CASES_DIR) changes per scenario."""
    tmp_root = Path(tempfile.mkdtemp(prefix="vergi_mali_tatil_unicode_isolated_"))
    tmp_cases = tmp_root / "cases"
    tmp_cases.mkdir(parents=True)
    case_dir = tmp_cases / CASE_ID
    shutil.copytree(REAL_CASE_0001, case_dir)

    if tax_type is not None:
        case_json_path = case_dir / "case.json"
        with open(case_json_path, "r", encoding="utf-8") as f:
            case_data = json.load(f)
        for item in case_data.get("dispute_items", []):
            item["tax_type"] = tax_type
        with open(case_json_path, "w", encoding="utf-8") as f:
            json.dump(case_data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    if issuing_authority is not None:
        case_json_path = case_dir / "case.json"
        with open(case_json_path, "r", encoding="utf-8") as f:
            case_data = json.load(f)
        actions = case_data.setdefault("administrative_actions", [])
        actions.append(
            {
                "action_id": "action_mali_tatil_unicode_probe",
                "action_category": "assessment",
                "action_type": "probe",
                "issuing_authority": issuing_authority,
                "action_date": None,
                "notification_date": None,
                "source_document_id": None,
                "verification_state": "unverified",
                "notes": None,
            }
        )
        with open(case_json_path, "w", encoding="utf-8") as f:
            json.dump(case_data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    original_cases_dir = deadline_validator.CASES_DIR
    try:
        deadline_validator.CASES_DIR = tmp_cases
        return dc.build_deadline_record(
            case_id=CASE_ID, anchor_event=_unicode_anchor_event, selection=_unicode_selection,
            ruleset_path=dc.DEFAULT_RULESET_PATH, holiday_calendar=COVERED_2026,
            judicial_recess_applicable=False,
        )
    finally:
        deadline_validator.CASES_DIR = original_cases_dir
        shutil.rmtree(tmp_root, ignore_errors=True)


# (a) issuing_authority = "Ankara İl Özel İdaresi" (capital İ), tax_type = KDV (included)
#     -> issuing_authority_excluded MUST win; mali tatil NOT applied.
record_a = _run_unicode_scenario(tax_type="KDV", issuing_authority="Ankara İl Özel İdaresi")
check(
    "(a) End-to-end: issuing_authority='Ankara İl Özel İdaresi' (capital İ) via real "
    "case.json -> issuing_authority_excluded, mali tatil NOT applied, naive calendar result",
    record_a["calculation_state"] == "calculated" and record_a["calculated_deadline"] == "2026-07-15",
    detail=str(record_a),
)

# (b) SAME authority, plain lowercase spelling -> SAME result.
record_b = _run_unicode_scenario(tax_type="KDV", issuing_authority="Ankara il özel idaresi")
check(
    "(b) End-to-end: issuing_authority='Ankara il özel idaresi' (plain lowercase) produces "
    "the IDENTICAL result as (a) - capital-İ spelling does not change the outcome",
    record_b["calculation_state"] == record_a["calculation_state"]
    and record_b["calculated_deadline"] == record_a["calculated_deadline"] == "2026-07-15",
    detail=str(record_b),
)

# (c) tax_type = "Özel İletişim Vergisi" (capital İ) -> tax_type_excluded.
record_c = _run_unicode_scenario(tax_type="Özel İletişim Vergisi")
check(
    "(c) End-to-end: tax_type='Özel İletişim Vergisi' (capital İ) via real case.json -> "
    "tax_type_excluded, mali tatil NOT applied, naive calendar result "
    "(BEFORE the fix this would have been misclassified 'unrecognized' -> needs_review)",
    record_c["calculation_state"] == "calculated" and record_c["calculated_deadline"] == "2026-07-15",
    detail=str(record_c),
)

# (d) tax_type = "Veraset ve İntikal Vergisi" (capital İ) -> must NOT be unrecognized;
#     must be classified included and mali tatil applied (2026-08-04, same as KDV).
record_d = _run_unicode_scenario(tax_type="Veraset ve İntikal Vergisi")
check(
    "(d) End-to-end: tax_type='Veraset ve İntikal Vergisi' (capital İ) via real case.json -> "
    "correctly classified INCLUDED (not unrecognized), mali tatil applied -> 2026-08-04 "
    "(BEFORE the fix this would have been misclassified 'unrecognized' -> needs_review)",
    record_d["calculation_state"] == "calculated" and record_d["calculated_deadline"] == "2026-08-04",
    detail=str(record_d),
)
check(
    "(d) mali_tatil_applied note confirms the pause/resume mechanism genuinely fired",
    "mali_tatil_adjustment=applied" in (record_d.get("notes") or ""),
    detail=str(record_d.get("notes")),
)

# (e) missing/unknown tax_type -> STILL needs_review/fail-closed via the real wiring
#     (the Unicode fix must not accidentally make an unrecognized value permissive).
record_e = _run_unicode_scenario(tax_type="Tamamen Bilinmeyen Bir Vergi Türü XYZ")
check(
    "(e) End-to-end: a genuinely unknown tax_type still correctly fails closed to "
    "needs_review via the real wiring - the Unicode fix did not loosen unrelated matching",
    record_e["calculation_state"] == "needs_review" and record_e["calculated_deadline"] is None,
    detail=str(record_e),
)


# ============================================================
# 6) INDEPENDENT REVIEW REMEDIATION - PROOF THAT OTHER DEADLINE
#    CLASSIFICATIONS' NORMALIZATION BEHAVIOR IS UNCHANGED. The mali
#    tatil fix introduced a NEW, narrow `_normalize_mali_tatil_text()`
#    used ONLY for mali tatil tax_type/issuing_authority matching; the
#    SHARED `deadline_rule_selection_policy.normalize_string()` (used
#    for rule-selection's own applicability.tax_types filtering) was
#    NOT touched. This is proven two ways: (1) the shared function's
#    own Unicode behavior is unchanged (still exhibits the well-known
#    İ-casefold quirk - i.e. this repo-wide function was NOT patched),
#    and (2) end-to-end rule SELECTION (a completely separate call
#    path from mali tatil classification) still works correctly for
#    the real, unmodified case_0001.
# ============================================================

check(
    "The SHARED normalize_string() (deadline_rule_selection_policy.py) was NOT modified - it "
    "still exhibits the standard Python casefold 'İ' -> 'i'+U+0307 behavior, proving the mali "
    "tatil fix is scoped to its OWN new function, not a repo-wide behavior change",
    rsp.normalize_string("İ") == "i̇",
    detail=repr(rsp.normalize_string("İ")),
)

selection_check = rsp.select_for_case_event(
    case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID, ruleset_path=dc.DEFAULT_RULESET_PATH,
)
check(
    "Rule SELECTION (deadline_rule_selection_policy.select_for_case_event(), a separate call "
    "path that also reads dispute_item.tax_type via the untouched get_case_tax_types()) still "
    "works correctly end-to-end on the real, unmodified case_0001 after the mali tatil fix",
    selection_check.get("selection_state") == "selected_blocked_anchor"
    and selection_check.get("calculation_allowed") is False,
    detail=str(selection_check),
)


print(f"--- test_deadline_calculator_mali_tatil_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
