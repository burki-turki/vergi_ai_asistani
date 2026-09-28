# ============================================================
# PILOT READINESS ADIM 6 - AVUKAT ALTIN ÖRNEK DİFERANSİYEL TESTİ
# src/deadline_calculator.py ISOLATED, READ-ONLY GOLDEN TESTS.
#
# Bu modül, avukatın doldurduğu "Avukat Doğrulama Paketi (DRAFT-4)"
# belgesindeki 12 sentetik senaryoyu (Bölüm 4-B, S01-S12), dinî bayram
# ek senaryosunu (Bölüm 4-C, S13) ve avukatın kendi eklediği riskli
# senaryoyu (Bölüm 4-D, A-1) - toplam 14 satırı - GERÇEK, üretim
# `deadline_calculator` zincirine karşı mekanik olarak karşılaştırır.
#
# PROVENANCE NOTU (kullanıcı kararı - bu turda yeniden teyit
# İSTENMEMİŞTİR; DRAFT-4 avukat tarafından incelenmiş/onaylanmış
# hukuki girdi olarak kabul edilmiştir):
#
#   DRAFT-4 kaynak belgesi (repo DIŞINDA saklanır, git'e ASLA girmez):
#     burki_avukat_dogrulama_paketi_DRAFT4_DOLDURULABILIR (1).docx
#     SHA-256:
#       dcf4df690bf8298830a3e19b9041d148cb331ccd198f16bceb73129cf186ecd1
#
#   İmzalı resmî tatil takvimi doğrulaması (repo İÇİNDE, canonical
#   `data/holiday_calendar/holiday_calendar.json` -> verifications[]):
#     verification_ref:
#       HC-LAWYER-VERIFY-v1-2024-2035-fb79b85fcf114c95
#
# İKİ BAĞLAYICI YORUM KURALI (kullanıcı kararı):
#
#   (1) S05 - YARIM GÜN. DRAFT-4 SORU 3.4 "süre o gün dolar" demiş ve
#       S05 satırına 28.10.2026 yazmıştır. Buna karşılık 26.09.2026
#       tarihli, DAHA SONRAKİ ve e-imzalı takvim doğrulaması yarım gün
#       politikası olarak `needs_review_if_deadline_day` KABUL etmiştir.
#       Sonraki tarihli imzalı politika ÜSTÜNDÜR: beklenen sonuç kesin
#       bir tarih DEĞİL, fail-closed `needs_review` +
#       `holiday_calendar_half_day_deadline_requires_review`tir.
#       28.10.2026 yalnız insan onayına sunulacak değer olarak burada
#       kayıt altına alınır (aşağıdaki `lawyer_note`).
#
#   (2) S11 - CUMARTESİ. DRAFT-4 tablosu 07.09.2030 yazmıştır, ancak o
#       gün CUMARTESİdir. Avukatın KENDİ onayladığı SORU 5.4 kuralı
#       ("7 Eylül Cumartesi, Pazar veya tam gün resmî tatile rastlarsa
#       İYUK m.8/2 devreye girer ve süre tatili izleyen ilk çalışma
#       gününün sonuna kadar uzar") uygulanır: beklenen sonuç
#       09.09.2030 PAZARTESİdir. Tablodaki 07.09.2030 KULLANILMAZ.
#
# Bu dosya SALT-OKUNURDUR: hiçbir case dizini, PostgreSQL bağlantısı,
# mutation coordinator, ağ/API çağrısı veya gerçek müvekkil verisi
# KULLANILMAZ. Tüm senaryolar sentetiktir (uydurma tebliğ tarihleri).
# `data/` ağacının bayt-değişmezliği koşu başında ve sonunda ayrıca
# doğrulanır. Hiçbir senaryo skip/xfail/karantina DEĞİLDİR - 14/14
# gerçekten çalışır.
#
# Run: python ui/tests/test_deadline_lawyer_golden_examples_isolated.py
# ============================================================

import hashlib
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import deadline_calculator as dc                       # noqa: E402

REAL_DATA_DIR = REPO_ROOT / "data"

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


def _snapshot_data_tree():
    out = {}
    for path in REAL_DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(REAL_DATA_DIR))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            except OSError:
                out[str(path.relative_to(REAL_DATA_DIR))] = "<unreadable>"
    return out


# ----------------------------------------------------------------
# Üretim girdileri (salt-okunur): gerçek İYUK kuralı + gerçek,
# avukat-doğrulamalı resmî tatil takvimi.
# ----------------------------------------------------------------

RULE = dc.load_production_rule()

# DRAFT-4 Bölüm 4-A: "Belge türü hepsinde vergi/ceza ihbarnamesidir."
# Mali tatil (5604 m.1/7) istisna listesinde OLMAYAN, kapsam içi bir
# vergi türü; S07/S08/S11'in avukat gerekçeleri mali tatilin GERÇEKTEN
# uygulanmasına dayanır. Diğer 11 senaryoda sayım penceresi mali tatile
# hiç dokunmadığı için bu bağlam tamamen moot'tur (bkz.
# `calculate_rule_deadline()` docstring'i).
KDV_CONTEXT = {
    "tax_types": {"kdv"},
    "issuing_authorities": set(),
}

CALCULATED = "calculated"
NEEDS_REVIEW = "needs_review"
HALF_DAY_REASON = "holiday_calendar_half_day_deadline_requires_review"


# ----------------------------------------------------------------
# DRAFT-4'ün 14 altın örneği.
#
#   case_id        : DRAFT-4'teki satır kimliği
#   anchor         : tebliğ tarihi (DRAFT-4'ten birebir)
#   expect_state   : beklenen calculation_state
#   expect_date    : beklenen calculated_deadline (None ise tarih yok)
#   expect_reason  : beklenen reason (None ise reason kontrol edilmez)
#   lawyer_note    : avukatın gerekçesinin özeti / sapma kaydı
# ----------------------------------------------------------------

SCENARIOS = [
    {
        "case_id": "S01",
        "anchor": "2026-02-10",
        "expect_state": CALCULATED,
        "expect_date": "2026-03-12",
        "expect_reason": None,
        "lawyer_note": "İYUK m.7/1 - düz 30 gün, son gün Perşembe, tatil yok.",
    },
    {
        "case_id": "S02",
        "anchor": "2026-01-15",
        "expect_state": CALCULATED,
        "expect_date": "2026-02-16",
        "expect_reason": None,
        "lawyer_note": "İYUK m.8/2 - ham son gün 14.02.2026 Cumartesi, ilk iş günü Pazartesi.",
    },
    {
        "case_id": "S03",
        "anchor": "2026-01-16",
        "expect_state": CALCULATED,
        "expect_date": "2026-02-16",
        "expect_reason": None,
        "lawyer_note": "İYUK m.8/2 - ham son gün 15.02.2026 Pazar, ilk iş günü Pazartesi.",
    },
    {
        "case_id": "S04",
        "anchor": "2026-12-02",
        "expect_state": CALCULATED,
        "expect_date": "2027-01-04",
        "expect_reason": None,
        "lawyer_note": "İYUK m.7+m.8/2 - ham son gün 01.01.2027 Yılbaşı, ilk iş günü 04.01.2027.",
    },
    {
        "case_id": "S05",
        "anchor": "2026-09-28",
        "expect_state": NEEDS_REVIEW,
        "expect_date": None,
        "expect_reason": HALF_DAY_REASON,
        "lawyer_note": (
            "YORUM KURALI (1): ham son gün 28.10.2026 yalnız YARIM GÜN tatil. "
            "DRAFT-4 SORU 3.4 'süre o gün dolar' + tabloda 28.10.2026 yazmıştır; "
            "ancak 26.09.2026 tarihli İMZALI politika needs_review_if_deadline_day "
            "olduğu ve SONRAKİ tarihli imzalı karar üstün olduğu için yazılım kesin "
            "tarih ÜRETMEZ. 28.10.2026 insan onayına sunulacak değerdir."
        ),
    },
    {
        "case_id": "S06",
        "anchor": "2026-09-29",
        "expect_state": CALCULATED,
        "expect_date": "2026-10-30",
        "expect_reason": None,
        "lawyer_note": (
            "İYUK m.8/2 - ham son gün 29.10.2026 Cumhuriyet Bayramı TAM GÜN, "
            "ilk iş günü 30.10.2026 Cuma."
        ),
    },
    {
        "case_id": "S07",
        "anchor": "2026-06-19",
        "expect_state": CALCULATED,
        "expect_date": "2026-09-07",
        "expect_reason": None,
        "lawyer_note": (
            "5604 m.1/3 mali tatil duraklaması + İYUK m.8/3 - süre 01-20.07.2026 "
            "boyunca işlemez, 21.07'de devam eder, ham son gün çalışmaya ara verme "
            "dönemine rastlar, 07.09.2026'ya uzar."
        ),
    },
    {
        "case_id": "S08",
        "anchor": "2026-06-20",
        "expect_state": CALCULATED,
        "expect_date": "2026-09-07",
        "expect_reason": None,
        "lawyer_note": (
            "S07 ile aynı mekanizma, bir gün kaymış tebliğ - mali tatil duraklaması "
            "+ İYUK m.8/3 -> 07.09.2026."
        ),
    },
    {
        "case_id": "S09",
        "anchor": "2026-08-01",
        "expect_state": CALCULATED,
        "expect_date": "2026-09-07",
        "expect_reason": None,
        "lawyer_note": (
            "İYUK m.8/3 - ham son gün 31.08.2026 çalışmaya ara verme döneminin "
            "İÇİNDE, süre 07.09.2026'ya uzar."
        ),
    },
    {
        "case_id": "S10",
        "anchor": "2026-08-02",
        "expect_state": CALCULATED,
        "expect_date": "2026-09-01",
        "expect_reason": None,
        "lawyer_note": (
            "SORU 5.2'nin ayrımı - ham son gün 01.09.2026 çalışmaya ara verme "
            "döneminin DIŞINDA, m.8/3 uzatması UYGULANMAZ."
        ),
    },
    {
        "case_id": "S11",
        "anchor": "2030-07-01",
        "expect_state": CALCULATED,
        "expect_date": "2030-09-09",
        "expect_reason": None,
        "lawyer_note": (
            "YORUM KURALI (2): mali tatil duraklaması + İYUK m.8/3 uzatması ham "
            "07.09.2030'u verir, ancak o gün CUMARTESİdir. Avukatın onayladığı SORU "
            "5.4 kuralı gereği m.8/2 devreye girer ve son gün 09.09.2030 "
            "PAZARTESİdir. DRAFT-4 tablosundaki 07.09.2030 KULLANILMAZ."
        ),
    },
    {
        "case_id": "S12",
        "anchor": "2028-01-30",
        "expect_state": CALCULATED,
        "expect_date": "2028-02-29",
        "expect_reason": None,
        "lawyer_note": (
            "Artık yıl - ham son gün 29.02.2028 Salı; 2028 Ramazan Bayramı "
            "26-28 Şubat olduğundan 29 Şubat çalışma günüdür."
        ),
    },
    {
        "case_id": "S13",
        "anchor": "2032-12-03",
        "expect_state": CALCULATED,
        "expect_date": "2033-01-05",
        "expect_reason": None,
        "lawyer_note": (
            "Bölüm 4-C dinî bayram senaryosu - ham son gün 02.01.2033 Pazar/Ramazan "
            "Bayramı 1. Gün; 03-04.01 de tam gün tatil olduğundan ilk çalışma günü "
            "05.01.2033 Çarşamba."
        ),
    },
    {
        "case_id": "A-1",
        "anchor": "2029-03-22",
        "expect_state": CALCULATED,
        "expect_date": "2029-04-30",
        "expect_reason": None,
        "lawyer_note": (
            "Avukatın kendi eklediği riskli senaryo (Bölüm 4-D) - ham son gün "
            "21.04.2029 Cumartesi; 22 Pazar, 23 Nisan tam gün ulusal bayram "
            "(arefe yarım günü TAM GÜN bayram bastırır), 24-27 Nisan Kurban "
            "Bayramı, 28-29 hafta sonu -> ilk çalışma günü 30.04.2029 Pazartesi."
        ),
    },
]


# ================================================================
# 0) ÖN KOŞULLAR - bu testin anlamlı olması için üretim girdilerinin
#    beklenen durumda olduğunun kanıtı (tautolojik geçişi önler).
# ================================================================

def test_preconditions():
    calendar = dc.load_holiday_calendar()

    check(
        "ÖN KOŞUL: üretim takvimi 2024-2035'in 12 yılını da avukat-doğrulamalı "
        "olarak kapsıyor (HC-LAWYER-VERIFY-v1-2024-2035-fb79b85fcf114c95)",
        calendar["covered_verified_years"] == set(range(2024, 2036)),
        calendar["covered_verified_years"],
    )
    check(
        "ÖN KOŞUL: üretim kuralı İYUK çalışmaya ara verme dayanağını taşıyor "
        "(S07-S11 bu olmadan anlamsız olurdu)",
        dc.rule_has_iyuk_recess_basis(RULE) is True,
        RULE.get("legal_basis_refs"),
    )
    check(
        "ÖN KOŞUL: üretim kuralı 5604 mali tatil dayanağını taşıyor "
        "(S07/S08/S11 bu olmadan anlamsız olurdu)",
        dc.rule_has_mali_tatil_basis(RULE) is True,
        RULE.get("legal_basis_refs"),
    )
    check(
        "ÖN KOŞUL: S05'in ham son günü (2026-10-28) üretim takviminde GERÇEKTEN "
        "yalnız-yarım-gün - imzalı needs_review_if_deadline_day politikası canlı",
        date(2026, 10, 28) not in calendar["holiday_dates"],
        "2026-10-28 tam-gün tatil kümesinde görünüyor; yarım gün dalı tetiklenmez",
    )
    return calendar


# ================================================================
# 1) 14 ALTIN ÖRNEK - DİFERANSİYEL KARŞILAŞTIRMA
# ================================================================

def test_golden_examples(calendar):
    for sc in SCENARIOS:
        case_id = sc["case_id"]

        result = dc.calculate_rule_deadline(
            anchor_date=sc["anchor"],
            rule=RULE,
            holiday_calendar=calendar,
            # Kullanıcı sözleşmesi: S07-S11 için AÇIKÇA True. Diğer
            # senaryolarda ham son gün çalışmaya ara verme döneminin
            # dışında kaldığı için bu parametre hiç tüketilmez (moot),
            # tekdüzelik için yine de True geçilir.
            judicial_recess_applicable=True,
            case_tax_context=KDV_CONTEXT,
        )

        got_state = result.get("calculation_state")
        got_date = result.get("calculated_deadline")
        got_reason = result.get("reason")

        state_ok = got_state == sc["expect_state"]
        date_ok = got_date == sc["expect_date"]
        reason_ok = (
            sc["expect_reason"] is None
            or got_reason == sc["expect_reason"]
        )

        detail = (
            "\n        BEKLENEN: state=%r date=%r reason=%r"
            "\n        GÖZLENEN: state=%r date=%r reason=%r"
            "\n        anchor=%s  judicial_recess_applied=%r  mali_tatil_applied=%r"
            "\n        holiday_adjustment_applied=%r  base_deadline=%r  provisional=%r"
            "\n        AVUKAT GEREKÇESİ: %s"
            % (
                sc["expect_state"], sc["expect_date"], sc["expect_reason"],
                got_state, got_date, got_reason,
                sc["anchor"],
                result.get("judicial_recess_applied"),
                result.get("mali_tatil_applied"),
                result.get("holiday_adjustment_applied"),
                result.get("base_deadline"),
                result.get("provisional_deadline"),
                sc["lawyer_note"],
            )
        )

        check(
            "ALTIN ÖRNEK %s: anchor=%s -> beklenen %s"
            % (
                case_id,
                sc["anchor"],
                sc["expect_date"] if sc["expect_date"] else
                "%s/%s" % (sc["expect_state"], sc["expect_reason"]),
            ),
            state_ok and date_ok and reason_ok,
            detail,
        )


# ================================================================
# 2) MEKANİZMA KANITI - beklenen tarihlerin DOĞRU SEBEPLE elde
#    edildiğinin kanıtı (aynı tarihe yanlış yoldan varmayı yakalar).
# ================================================================

def test_mechanism_attribution(calendar):
    def run(anchor):
        return dc.calculate_rule_deadline(
            anchor_date=anchor, rule=RULE, holiday_calendar=calendar,
            judicial_recess_applicable=True, case_tax_context=KDV_CONTEXT,
        )

    for case_id, anchor in (("S07", "2026-06-19"), ("S08", "2026-06-20"),
                            ("S11", "2030-07-01")):
        r = run(anchor)
        check(
            "MEKANİZMA %s: mali tatil GERÇEKTEN uygulandı (mali_tatil_applied=True)"
            % case_id,
            r.get("mali_tatil_applied") is True,
            r,
        )

    for case_id, anchor in (("S07", "2026-06-19"), ("S08", "2026-06-20"),
                            ("S09", "2026-08-01"), ("S11", "2030-07-01")):
        r = run(anchor)
        check(
            "MEKANİZMA %s: İYUK m.8/3 çalışmaya ara verme uzatması GERÇEKTEN "
            "uygulandı (judicial_recess_applied=True)" % case_id,
            r.get("judicial_recess_applied") is True,
            r,
        )

    r10 = run("2026-08-02")
    check(
        "MEKANİZMA S10: ham son gün dönem DIŞINDA olduğu için m.8/3 uzatması "
        "UYGULANMADI (judicial_recess_applied=False) - SORU 5.2'nin ayrımı",
        r10.get("judicial_recess_applied") is False,
        r10,
    )

    r11 = run("2030-07-01")
    check(
        "MEKANİZMA S11: uzatılmış 07.09.2030 Cumartesi olduğu için m.8/2 kaydırması "
        "GERÇEKTEN uygulandı (holiday_adjustment_applied=True, provisional=2030-09-07)",
        r11.get("holiday_adjustment_applied") is True
        and r11.get("provisional_deadline") == "2030-09-07",
        r11,
    )

    for case_id, anchor in (("S02", "2026-01-15"), ("S04", "2026-12-02"),
                            ("S06", "2026-09-29"), ("S13", "2032-12-03"),
                            ("A-1", "2029-03-22")):
        r = run(anchor)
        check(
            "MEKANİZMA %s: hafta sonu/tatil kaydırması GERÇEKTEN uygulandı "
            "(holiday_adjustment_applied=True)" % case_id,
            r.get("holiday_adjustment_applied") is True,
            r,
        )

    r01 = run("2026-02-10")
    check(
        "MEKANİZMA S01: hiçbir uzatma/kaydırma uygulanmadı - düz 30 gün "
        "(recess=False, mali_tatil=False, holiday_adjustment=False)",
        r01.get("judicial_recess_applied") is False
        and r01.get("mali_tatil_applied") is False
        and r01.get("holiday_adjustment_applied") is False,
        r01,
    )


# ================================================================
# 3) DETERMİNİZM - aynı girdi iki kez, birebir aynı çıktı
# ================================================================

def test_determinism(calendar):
    for sc in SCENARIOS:
        a = dc.calculate_rule_deadline(
            anchor_date=sc["anchor"], rule=RULE, holiday_calendar=calendar,
            judicial_recess_applicable=True, case_tax_context=KDV_CONTEXT,
        )
        b = dc.calculate_rule_deadline(
            anchor_date=sc["anchor"], rule=RULE, holiday_calendar=calendar,
            judicial_recess_applicable=True, case_tax_context=KDV_CONTEXT,
        )
        check(
            "DETERMİNİZM %s: aynı girdi -> birebir aynı sonuç" % sc["case_id"],
            a == b,
            (a, b),
        )


# ================================================================
# DATA-TREE INVARIANCE
# ================================================================

def run_self_test():
    before_data_snapshot = _snapshot_data_tree()

    calendar = test_preconditions()
    test_golden_examples(calendar)
    test_mechanism_attribution(calendar)
    test_determinism(calendar)

    after_data_snapshot = _snapshot_data_tree()
    check(
        "bu test modülü: gerçek data/ ağacı tüm koşu boyunca bayt-değişmez "
        "(SALT-OKUNUR - case dizini yok, PostgreSQL yok, ağ yok, yazma yok)",
        before_data_snapshot == after_data_snapshot,
    )

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
