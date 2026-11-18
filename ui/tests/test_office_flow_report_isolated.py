# ============================================================
# BÜRO MODELİ / T1 - ui/services/office_flow_report.py İZOLE TESTİ
#
# Pilot Hesap Raporu + karşılaştırma + bayatlık (GEÇERSİZ) damgası.
#   - UYUMLU YALNIZ üç değer de eşitse (anchor tarihi, durum `calculated`,
#     son gün); hesaplanamayan/belirsiz sistem sonucu UYUSMAZLIK (fail-closed)
#   - rapor sabit cümleleri (hukuki karar değil / kapatma doğruluk değildir)
#   - "doğru bulundu" iddiası HİÇBİR durumda yok
# ============================================================

import json
import shutil
import sys
import tempfile
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

passed = 0
failed = 0
skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def summarize_and_exit():
    print(f"--- test_office_flow_report_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import office_flow_records as R  # noqa: E402
from ui.services import office_flow_report as REP  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vergi_t1_report_"))

READING = {"tebligat_tarihi": "2026-02-10", "sayfa": 1, "kor_son_gun": "2026-03-12", "adli_tatil": "no",
           "stopping_event_status": "none", "stopping_event_ref": "BEYAN-T1"}


def deadline_doc(**item):
    base = {"anchor_date": "2026-02-10", "calculation_state": "calculated", "calculated_deadline": "2026-03-12",
            "rule_id": "iyuk_tax_court_general_lawsuit_filing", "requires_human_review": False}
    base.update(item)
    return {"deadlines": [base]}


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except R.OfficeFlowError as error:
        return error.code
    return None


try:
    # ---------------------------------------------------------------- özet
    system = REP.summarize_pending_deadline(deadline_doc())
    check("a pending deadline with exactly one entry is summarised",
          system.anchor_date == "2026-02-10" and system.calculation_state == "calculated" and system.calculated_deadline == "2026-03-12")
    for label, doc in (("no deadlines key", {}), ("empty list", {"deadlines": []}), ("two deadlines", {"deadlines": [{}, {}]}),
                       ("a non-dict entry", {"deadlines": ["x"]}), ("a non-dict document", [])):
        check(f"summarize_pending_deadline refuses an unexpected shape ({label}) -> SISTEM_HESAPLAMADI",
              code_of(REP.summarize_pending_deadline, doc) == "SISTEM_HESAPLAMADI")
    bad_file = TMP / "kotu.json"
    bad_file.write_text("{bozuk", encoding="utf-8")
    check("an unreadable pending file -> SISTEM_HESAPLAMADI", code_of(REP.read_pending_summary, bad_file) == "SISTEM_HESAPLAMADI"
          and code_of(REP.read_pending_summary, TMP / "yok.json") == "SISTEM_HESAPLAMADI")
    good_file = TMP / "iyi.json"
    good_file.write_text(json.dumps(deadline_doc()), encoding="utf-8")
    check("a readable pending file is summarised", REP.read_pending_summary(good_file).calculated_deadline == "2026-03-12")

    # ---------------------------------------------------------------- karşılaştırma
    c = REP.compare(READING, system)
    check("compare: date, state and last day all equal -> UYUMLU", c.sonuc == "UYUMLU" and c.tarih_uyumu and c.son_gun_uyumu and c.neden is None)
    c = REP.compare(READING, REP.summarize_pending_deadline(deadline_doc(calculated_deadline="2026-03-13")))
    check("compare: the system last day differs by one day -> UYUSMAZLIK / SON_GUN_FARKLI",
          c.sonuc == "UYUSMAZLIK" and c.son_gun_uyumu is False and c.tarih_uyumu is True and c.neden == "SON_GUN_FARKLI")
    c = REP.compare(READING, REP.summarize_pending_deadline(deadline_doc(anchor_date="2026-02-11")))
    check("compare: the system anchor differs from the lawyer's independent date -> UYUSMAZLIK / ANCHOR_FARKLI",
          c.sonuc == "UYUSMAZLIK" and c.tarih_uyumu is False and c.neden == "ANCHOR_FARKLI")
    for state in ("needs_review", "blocked_unverified_anchor", "not_calculated", None):
        c = REP.compare(READING, REP.summarize_pending_deadline(deadline_doc(calculation_state=state, calculated_deadline=None)))
        check(f"compare: system state {state!r} (nothing calculated) -> UYUSMAZLIK / SISTEM_HESAPLAMADI, never UYUMLU",
              c.sonuc == "UYUSMAZLIK" and c.neden == "SISTEM_HESAPLAMADI" and c.son_gun_uyumu is None)
    c = REP.compare(READING, REP.summarize_pending_deadline(deadline_doc(calculation_state="needs_review", calculated_deadline="2026-03-12")))
    check("compare: a date next to a needs_review state still cannot be UYUMLU", c.sonuc == "UYUSMAZLIK")
    c = REP.compare(READING, REP.summarize_pending_deadline(deadline_doc(calculated_deadline=None)))
    check("compare: `calculated` WITHOUT a date cannot be UYUMLU", c.sonuc == "UYUSMAZLIK")
    c = REP.compare(READING, REP.summarize_pending_deadline(deadline_doc(anchor_date="2026-02-11", calculated_deadline="2026-03-13")))
    check("compare: both different -> UYUSMAZLIK", c.sonuc == "UYUSMAZLIK")

    # ---------------------------------------------------------------- rapor metni
    ok = REP.build_report_text(reading=READING, system=system, comparison=REP.compare(READING, system), state="UYUMLU_RAPOR_KONTROLU",
                               canonical_report="ONAYLI RAPOR SATIRI\n", kontrol_turu="ILK_KONTROL")
    check("the report states its purpose, the lawyer's blind values (Turkish dates), the system result and the comparison",
          "karşılaştırabilmesi" in ok and "10.02.2026" in ok and "12.03.2026" in ok and "KARŞILAŞTIRMA" in ok and "UYUMLU" in ok)
    check("the report carries the two fixed sentences (not a legal decision; closing is not proof)",
          REP.NOT_LEGAL_SENTENCE in ok and "İncelemenin kapatılması, hesabın doğru bulunduğu anlamına gelmez." in ok)
    check("the report appends the approved result's report and the control kind", "ONAYLI RAPOR SATIRI" in ok and "ILK_KONTROL" in ok)
    negative = "İncelemenin kapatılması, hesabın doğru bulunduğu anlamına gelmez."
    check("outside the fixed negative sentence the word 'doğru' (correct) appears NOWHERE in an UYUMLU report: no claim of correctness",
          "doğru" not in ok.replace(negative, "").lower())
    mismatch = REP.build_report_text(
        reading=READING, system=REP.summarize_pending_deadline(deadline_doc(calculated_deadline="2026-03-13")),
        comparison=REP.Comparison("UYUSMAZLIK", True, False, "SON_GUN_FARKLI"), state="UYUSMAZLIK_INCELEME_ACIK")
    check("an UYUSMAZLIK report says no final approval is given and the difference is reviewed on the office device",
          "UYUSMAZLIK" in mismatch and "Nihai onay verilmez" in mismatch and "FARKLI" in mismatch)
    f3 = REP.build_report_text(reading=READING, system=None, comparison=REP.Comparison("UYUSMAZLIK", False, None, "TARIH_FARKLI"),
                               state="UYUSMAZLIK_INCELEME_ACIK", f3_date_mismatch="2026-02-15")
    check("outside the fixed negative sentence the word 'doğru' appears nowhere in the UYUSMAZLIK / F3 reports either",
          "doğru" not in mismatch.replace(negative, "").lower() and "doğru" not in f3.replace(negative, "").lower())
    check("an F3 date-mismatch report shows both dates and says NO calculation was made",
          "15.02.2026" in f3 and "10.02.2026" in f3 and "Hesap yapılmadı." in f3 and "SİSTEMİN SONUCU" not in f3)

    # ---------------------------------------------------------------- yazım / damga
    run_id = R.new_run_id()
    (TMP / "ofis").mkdir()
    R.ensure_office_infra(TMP / "ofis")
    paths = R.build_run_paths(TMP / "ofis", TMP / "vakalar", "abc123", run_id)
    R.create_owned_dir(paths.run_dir, run_id=run_id, kind="run_dir")
    REP.write_report(paths, ok)
    check("the first report write creates the file", REP.read_report(paths) == ok)
    REP.write_report(paths, ok + "ek\n")
    check("a later update replaces it atomically (working record)", REP.read_report(paths) == ok + "ek\n" and not (paths.run_dir / "pilot_hesap_raporu.txt.tmp").exists())
    REP.stamp_report_invalid(paths)
    stamped = REP.read_report(paths)
    check("stamping marks the report GEÇERSİZ at the very top and keeps the original text below",
          stamped.startswith(REP.STALE_BANNER) and ok in stamped)
    REP.stamp_report_invalid(paths)
    check("stamping is idempotent (one banner only)", REP.read_report(paths).count(REP.STALE_BANNER) == 1)
    check("reading a missing report -> DOSYA_ISLEMI_BASARISIZ", code_of(REP.read_report, R.build_run_paths(TMP / "ofis", TMP / "vakalar", "abc123", R.new_run_id())) == "DOSYA_ISLEMI_BASARISIZ")
    check("is_stale returns changed input NAMES only", REP.is_stale({"a": "h1", "b": "h2"}, {"a": "h1", "b": "h9"}) == ["b"]
          and REP.is_stale({"a": "h1"}, {"a": "h1"}) == [])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
