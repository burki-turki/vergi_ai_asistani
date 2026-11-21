# ============================================================
# KOL A / DİLİM 1 - İKİNCİ DALGA SÜRE KURALLARI (TASLAK AŞAMASI)
# AVUKAT ALTIN ÖRNEK DİFERANSİYEL TESTİ - ISOLATED, READ-ONLY.
#
# Bu modül, `data/deadline_rules/deadline_rules.json`'a TASLAK olarak
# yazılan üç kuralı, avukatın ikinci dalga formundaki kurgusal örneklere
# karşı GERÇEK üretim zinciriyle (`deadline_rule_selection_policy`,
# `deadline_legal_basis_resolver`, `deadline_calculator`) sınar:
#
#   - ödeme emrine karşı dava ............ form satırı 1, örnek 1-6
#   - haciz / e-hacze karşı dava ......... form satırı 10, örnek 127-131
#   - gıyapta uygulanan ihtiyati hacze
#     karşı dava ......................... form satırı 8, örnek 107-121
#
# PROVENANCE (repo DIŞINDA saklanır, git'e ASLA girmez):
#   "Vergi Davası Süre Kurallarının Genişletilmesi — Avukat Soru Formu,
#   İkinci Dalga, Sürüm 2, 12 Ekim 2026" (doldurulmuş dosya)
#   SHA-256: 1b59885846a7677dd4f4f03be85b2b42c16bcb900d808a76d885d66f84b669f8
#   ve 26/10/2026 tarihli teyit belgesi. Bu girdi bu test yazılırken
#   LEGAL_APPROVED olarak KAYDA ALINMAMIŞTIR; kurallar TASLAKTIR.
#
# NE KANITLANIR
#   (0) ön koşullar: registry geçerli; üç kayıt beklenen parametreleri
#       taşır; üretim takvimi 2024-2035'i kapsar;
#   (1) TASLAKLAR NORMAL KULLANIMDA ETKİN DEĞİLDİR: üretim kaydıyla
#       seçim no_match, kayıt blocked_missing_rule, hesaplayıcı
#       needs_review - üç kural, dört belge türü için ayrı ayrı;
#   (2) 26 altın örnek: kaydın YALNIZ BELLEKTE etkinleştirilmiş kopyası
#       (yalnız status/calculation_enabled değişir) avukatın yazdığı
#       tarihi verir;
#   (3) mekanizma: mali tatil / adli tatil / hafta sonu-resmî tatil
#       bayrakları avukatın açıklamasıyla aynıdır (doğru tarihe yanlış
#       yoldan varmayı yakalar);
#   (3b) mali tatil ara tarihleri: mali tatil içeren beş örnekte
#       avukatın açıklamasında yazdığı, adli tatil uzamasından ÖNCEKİ
#       bitiş tarihi (27.07, 04.08 x3, 08.08) hesaplayıcının ara
#       sonucuyla aynıdır - beş örneğin hepsi 7 Eylül'de bittiği için
#       yalnız son güne bakmak mali tatildeki duraklama hesabını sınamaz;
#   (4) ayırt edicilik: süre, mali tatil dayanağı, adli tatil dayanağı
#       veya adli tatil beyanı değişince sonuç da değişir;
#   (5) seçim: bellekte etkinleştirilmiş kayıtla her kural yalnız kendi
#       belge türünde seçilir, ihbarname çapası mevcut İYUK kuralında
#       kalır, iki türlü çapa ambiguous, 2018 öncesi çapa effective_from
#       ile reddedilir; bankaya veya üçüncü şahsa yapılan bildirim olarak
#       türlenmiş bir belge (6183 m.79 "haciz bildirisi") ve eski genel
#       adlar HİÇBİR kuralı seçmez;
#   (6) dayanak: üretim hükümleriyle 6183 m.58/1 ve m.15/1 bloklu,
#       haciz kuralının dayanakları tamamen doğrulanmış; geçici dizindeki
#       "doğrulanmış" kopyayla üçü de uygun, 2018 öncesinde değil;
#   (7) uçtan uca (geçici dizin): belge kaydı -> belge türü -> seçim ->
#       dayanak doğrulaması -> durdurucu işlem kapısı -> mali tatil
#       bağlamı -> son gün; ayrıca "kural etkin ama hüküm doğrulanmamış"
#       durumunda tarih ÜRETİLMEDİĞİ.
#
# NE KANITLANMAZ (bu testin geçmesi aşağıdakileri GÖSTERMEZ)
#   (a) BELGE İÇERİĞİ DENETLENMEZ. Seçim yalnız belge türü etiketine
#       bakar. Bankaya veya üçüncü şahsa yapılmış bir haciz bildirisi
#       yanlışlıkla `borcluya_haciz_bildirimi` / `borcluya_e_haciz_
#       bildirimi` etiketiyle kaydedilirse kural SEÇİLİR ve süre yanlış
#       belgeden başlar; (5)'teki "SINIR" kontrolü bunu açıkça gösterir.
#       Aynı şey borçlunun huzurunda uygulanan ihtiyati haczin
#       `ihtiyati_haciz_giyapta_tebligi` etiketiyle kaydedilmesi için de
#       geçerlidir. Etiketin doğruluğu giriş adımının ve girişi yapan
#       kişinin beyanının işidir; bu belge türleri için giriş yolu henüz
#       YOKTUR.
#   (b) MALİ TATİL KARARININ DAYANDIĞI BİLGİNİN DOĞRULUĞU DENETLENMEZ.
#       Kol A mali tatil Dilim A'dan beri bu üç kural
#       (`mali_tatil_receivable_basis = "action_document_receivables"`)
#       mali tatil kararını dosya genelindeki vergi türünden DEĞİL, çapa
#       olayının dava konusu işlem belgesine bağlı, teyitli uyuşmazlık
#       kalemlerinden ve o belgenin teyitli idari işlem kaydındaki
#       alacaklı idareden verir (avukat cevabı 3.1-3.3, 4.1-4.2); bağ,
#       teyit veya idare eksikse Temmuz'a değen sürede kesin tarih
#       vermez. Bu test avukatın örneklerini, işlem belgesine bağlı ve
#       teyitli tek bir kapsam içi kalem ("gelir vergisi") ile teyitli
#       bir vergi dairesi işlem kaydı kuran sentetik bir kurguyla
#       çalıştırır; adım adım sözleşme ayrı modülde sınanır
#       (test_deadline_mali_tatil_receivable_link_isolated). Kalan
#       sınırlar: `verification_state == "verified"` genel bir doğrulama
#       işaretidir; kalemin türünün ödeme emrinin veya haczin KENDİSİNDEN
#       teyit edildiğini ve bağ listesinin TAM olduğunu göstermez (K3).
#       Yanlış belgeye bağlanmış ve verified işaretlenmiş bir kalem yine
#       yanlış sonuç verebilir; eksik bağ koruması bunu yalnız dosyada
#       bağsız farklı türde bir kalem varsa yakalar. Kalemlerin belge ve
#       sayfasıyla girilmesi ve avukatın "bağ tam" teyidi Dilim B'nin
#       işidir; o gelene kadar bu kurallar gerçek dosyada Temmuz'a değen
#       sürelerde kesin tarih üretemez. "vergi dairesi" tanıması (K5),
#       bağın yalnız Temmuz penceresinde aranması (K6) ve fer'i / ceza
#       kalemleri (K4) avukata sorulacak açık konulardır.
#   (c) 5604 m.1'deki asgari beş günlük süre kuralı avukatın bu
#       örneklerinde hiç devreye girmez; burada sınanmaz (mevcut
#       test_deadline_calculator_mali_tatil_isolated sınar).
#   (d) GERÇEK olgu -> zaman çizelgesi -> süre zinciri bu belge türleriyle
#       çalıştırılmamıştır; (7)'de çapa olayı elle yazılmış bir sözlüktür.
#       YANLIŞ BELGEYE BAĞLANMA RİSKİ - ÜÇ KURALIN ÜÇÜ İÇİN DE GEÇERLİDİR:
#       aynı dosyada bir vergi/ceza ihbarnamesi ile birlikte bu üç belge
#       türünden biri varsa, etiketinde veya metninde "tebliğ" ya da
#       "ihbarname" geçen bir tebliğ olayı, kaynak belgenin kendi türüne
#       bakılmaksızın ihbarnameye bağlanabilir
#       (`timeline_consolidation_policy`, ~412-416 ve ~456-484). O zaman
#       üç kuralın hiçbiri değil, genel 30 günlük İYUK kuralı seçilir:
#         - ödeme emri: 15 gün yerine 30 gün sayılır; son gün GEÇ çıkar;
#         - gıyapta uygulanan ihtiyati hacze karşı dava: ikinci bağımsız
#           incelemenin YALNIZ hesaplayıcıda ölçtüğüne göre denenen 6
#           örneğin 4'ünde tarih değişir (3'ü daha GEÇ, 1'i daha erken);
#         - borçluya haciz / e-haciz bildirimi: iki kuralın süresi (30
#           gün) ve dayanak listesi birebir aynı olduğundan tarih ve
#           dayanaklar değişmez; kayda yalnız YANLIŞ kural kimliği yazılır.
#       Bağlama mantığı kod OKUNARAK biliniyor; gerçek olgu -> zaman
#       çizelgesi zinciri ÇALIŞTIRILMAMIŞTIR. Bu risk bu belge türleri
#       için giriş ekranı açılmadan ÖNCE incelenecek maddedir.
#   (e) Avukat girdisi LEGAL_APPROVED olarak kayda alınmamıştır; iki 6183
#       hükmü doğrulanmamıştır; resmî kapılar bu aşamada koşulmamıştır.
#
# Bu dosya SALT-OKUNURDUR: gerçek case dizini, PostgreSQL, mutation
# coordinator, ağ/API çağrısı veya gerçek müvekkil verisi KULLANILMAZ.
# Tüm tarihler avukatın KURGUSAL örnekleridir. Geçici dosyalar yalnız
# işletim sisteminin geçici dizinine yazılır ve koşu sonunda silinir.
# Gerçek `data/` ağacının bayt-değişmezliği başta ve sonda doğrulanır.
#
# Run: python ui/tests/test_deadline_rule_wave2_golden_examples_isolated.py
# ============================================================

import copy
import hashlib
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

import deadline_calculator as dc                       # noqa: E402
import deadline_legal_basis_resolver as resolver       # noqa: E402
import deadline_rule_selection_policy as selection     # noqa: E402
import deadline_rule_validator as rule_validator       # noqa: E402
import deadline_validator                               # noqa: E402

REAL_DATA_DIR = REPO_ROOT / "data"
RULESET_PATH = REAL_DATA_DIR / "deadline_rules" / "deadline_rules.json"
PROVISIONS_PATH = REAL_DATA_DIR / "provisions.json"

LAWYER_FORM_SHA256 = "1b59885846a7677dd4f4f03be85b2b42c16bcb900d808a76d885d66f84b669f8"

IYUK_RULE_ID = "iyuk_tax_court_general_lawsuit_filing"
PAYMENT_ORDER = "aatuhk_6183_payment_order_lawsuit_filing"
SEIZURE = "iyuk_seizure_and_e_seizure_lawsuit_filing"
PRECAUTIONARY = "aatuhk_6183_precautionary_seizure_in_absentia_lawsuit_filing"

MALI_REF = "KANUN_5604_m1"
RECESS_REFS = ("IYUK_2577_m8_3", "IYUK_2577_m61_1")
COMMON_REFS = [
    "IYUK_2577_m8_1",
    "IYUK_2577_m8_2",
    "IYUK_2577_m8_3",
    "IYUK_2577_m61_1",
    "KANUN_5604_m1",
]

RULE_SPECS = {
    PAYMENT_ORDER: {
        "label": "ödeme emri",
        "days": 15,
        "document_types": ["odeme_emri"],
        "refs": ["AATUHK_6183_m58_1"] + COMMON_REFS,
        "effective_from": "2018-01-01",
        "unverified_ref": "AATUHK_6183_m58_1",
        "example_count": 6,
    },
    SEIZURE: {
        "label": "haciz / e-haciz",
        "days": 30,
        "document_types": ["borcluya_haciz_bildirimi", "borcluya_e_haciz_bildirimi"],
        "refs": ["IYUK_2577_m7_1", "IYUK_2577_m7_2_b"] + COMMON_REFS,
        "effective_from": None,
        "unverified_ref": None,
        "example_count": 5,
    },
    PRECAUTIONARY: {
        "label": "gıyapta ihtiyati haciz",
        "days": 15,
        "document_types": ["ihtiyati_haciz_giyapta_tebligi"],
        "refs": ["AATUHK_6183_m15_1"] + COMMON_REFS,
        "effective_from": "2018-01-01",
        "unverified_ref": "AATUHK_6183_m15_1",
        "example_count": 15,
    },
}

DRAFT_NOTES_PREFIX = "TASLAK — ETKİN DEĞİL (LEGAL_APPROVED kaydı yok). "

# Avukatın örnekleri mali tatilin uygulandığı durumlarda kapsam içi bir
# vergi türü varsayar (116-118 açıkça "gelir vergisi alacağı" der). Kol A
# mali tatil Dilim A'dan beri bu üç kural mali tatil kararını dava konusu
# işlem belgesine bağlı alacaklardan verir; örnekler bu yüzden çapa
# belgesine ("synthetic_doc_001") bağlı, teyitli tek bir "gelir vergisi"
# kalemi ve aynı belgeye ait, teyitli bir vergi dairesi işlem kaydı kuran
# sentetik bir kurguyla çalıştırılır. Mali tatile hiç dokunmayan
# örneklerde bu bağlam tümüyle etkisizdir (K6).
LINKED_DOCUMENT_ID = "synthetic_doc_001"
LINKED_TAX_TYPES = ("gelir vergisi",)
LINKED_AUTHORITY = "Kurgusal Vergi Dairesi Müdürlüğü"

CALCULATED = "calculated"
NEEDS_REVIEW = "needs_review"

# ----------------------------------------------------------------
# AVUKATIN 26 ALTIN ÖRNEĞİ (formun 4. bölümünden birebir).
#
#   no      : formdaki örnek numarası
#   rule    : örneğin ait olduğu kural
#   anchor  : tebliğ tarihi (formdaki "Tebliğ veya olay tarihi")
#   expect  : avukatın yazdığı son gün
#   mali    : avukat mali tatilde durma olduğunu söylüyor mu
#   adli    : avukat adli tatil uzaması olduğunu söylüyor mu
#   tatil   : son gün hafta sonu / resmî tatil / dinî bayram nedeniyle
#             kaydırıldı mı (adli tatille ulaşılan 7 Eylül'ün ayrıca
#             kaydırılması dahil; adli tatil uzamasının KENDİSİ değil)
#   effect  : formdaki "Tatil / mali tatil / adli tatil etkisi" sütunu
# ----------------------------------------------------------------

EXAMPLES = [
    # --- ödeme emrine karşı dava (form satırı 1) ---
    (1, PAYMENT_ORDER, "2026-02-10", "2026-02-25", False, False, False,
     "Uzatma etkisi yok. Mali tatil ve adli tatil uygulanmaz."),
    (2, PAYMENT_ORDER, "2026-01-16", "2026-02-02", False, False, True,
     "Hafta sonu etkisi var. Mali tatil ve adli tatil uygulanmaz."),
    (3, PAYMENT_ORDER, "2026-04-08", "2026-04-24", False, False, True,
     "Resmî tatil etkisi var. Mali tatil ve adli tatil uygulanmaz."),
    (4, PAYMENT_ORDER, "2026-08-01", "2026-09-07", False, True, False,
     "Adli tatil etkisi var. Olağan son gün ayrıca Pazar’dır. Mali tatil etkisi yoktur."),
    (5, PAYMENT_ORDER, "2026-08-31", "2026-09-15", False, False, False,
     "Uzatma etkisi yok. Tebliğ adli tatilde yapılmıştır; son gün adli tatil dışındadır. "
     "Mali tatil etkisi yoktur."),
    (6, PAYMENT_ORDER, "2026-06-22", "2026-09-07", True, True, False,
     "Mali tatil ve adli tatil etkisi var."),
    # --- gıyapta uygulanan ihtiyati hacze karşı dava (form satırı 8) ---
    (107, PRECAUTIONARY, "2026-02-10", "2026-02-25", False, False, False,
     "Son güne etkisi yok"),
    (108, PRECAUTIONARY, "2026-01-16", "2026-02-02", False, False, True,
     "Hafta sonu."),
    (109, PRECAUTIONARY, "2026-04-08", "2026-04-24", False, False, True,
     "23 Nisan genel tatili."),
    (110, PRECAUTIONARY, "2026-08-03", "2026-09-07", False, True, False,
     "Adli tatil."),
    (111, PRECAUTIONARY, "2026-08-31", "2026-09-15", False, False, False,
     "Adli tatil uzaması yok."),
    (112, PRECAUTIONARY, "2026-01-16", "2026-02-02", False, False, True,
     "Hafta sonu"),
    (113, PRECAUTIONARY, "2026-02-07", "2026-02-23", False, False, True,
     "Hafta sonu."),
    (114, PRECAUTIONARY, "2026-04-16", "2026-05-04", False, False, True,
     "Resmî tatil ve hafta sonu."),
    (115, PRECAUTIONARY, "2026-03-05", "2026-03-23", False, False, True,
     "Dinî bayram."),
    (116, PRECAUTIONARY, "2026-06-30", "2026-09-07", True, True, False,
     "Mali tatil ve adli tatil."),
    (117, PRECAUTIONARY, "2026-07-06", "2026-09-07", True, True, False,
     "Mali tatil ve adli tatil."),
    (118, PRECAUTIONARY, "2026-07-17", "2026-09-07", True, True, False,
     "Mali tatil ve adli tatil."),
    (119, PRECAUTIONARY, "2026-08-16", "2026-09-07", False, True, False,
     "Adli tatil."),
    (120, PRECAUTIONARY, "2026-08-17", "2026-09-01", False, False, False,
     "Adli tatil uzaması yok"),
    (121, PRECAUTIONARY, "2025-08-01", "2025-09-08", False, True, True,
     "Adli tatil ve hafta sonu"),
    # --- haciz / e-hacze karşı dava (form satırı 10) ---
    (127, SEIZURE, "2026-02-10", "2026-03-12", False, False, False,
     "Hayır. Son günü etkileyen tatil bulunmuyor."),
    (128, SEIZURE, "2026-01-02", "2026-02-02", False, False, True,
     "Evet — hafta sonu."),
    (129, SEIZURE, "2026-03-24", "2026-04-24", False, False, True,
     "Evet — resmî tatil."),
    (130, SEIZURE, "2026-07-31", "2026-09-07", False, True, False,
     "Evet — adli tatil. Otuzuncu gün ayrıca pazar ve resmî tatildir."),
    (131, SEIZURE, "2026-06-19", "2026-09-07", True, True, False,
     "Evet — mali tatil ve ardından adli tatil."),
]

# ----------------------------------------------------------------
# MALİ TATİL ARA TARİHLERİ (formun "Kısa açıklama" sütunundan).
#
# Mali tatil içeren beş örneğin hepsi sonunda adli tatile düşer ve
# 7 Eylül'de biter; bu yüzden yalnız son güne bakan bir test mali
# tatildeki duraklama/devam hesabının doğru yapıldığını GÖSTERMEZ.
# Avukat her örnekte, adli tatil uzamasından ÖNCE sürenin hangi gün
# tamamlanacağını da yazmıştır; o tarih burada ayrıca sınanır.
#
#   no -> (avukatın ara tarihi, avukatın açıklamasından ilgili cümle)
# ----------------------------------------------------------------

MALI_INTERMEDIATE = {
    6: ("2026-07-27",
        "21 Temmuz’da yeniden başlayan kalan 7 gün, 27.07.2026’da tamamlanır"),
    116: ("2026-08-04",
          "15 günün tamamı 21 Temmuz–4 Ağustos arasında sayılır"),
    117: ("2026-08-04",
          "21 Temmuz birinci, 4 Ağustos on beşinci gündür"),
    118: ("2026-08-04",
          "4 Ağustos’ta tamamlanacak süre adli tatil nedeniyle 7 Eylül’e uzar"),
    131: ("2026-08-08",
          "Kalan 19 gün, 21 Temmuz–8 Ağustos arasında tamamlanır"),
}

# Borçluya DEĞİL, bankaya veya üçüncü şahsa yapılan bildirimi anlatan
# belge türü adları (6183 m.79 "haciz bildirisi") ile kayıttan çıkarılan
# eski genel adlar. Bunların HİÇBİRİ bir kuralı seçmemelidir.
NOT_DEBTOR_NOTICE_TYPES = [
    "haciz_bildirisi",
    "ucuncu_sahsa_haciz_bildirisi",
    "bankaya_haciz_bildirisi",
    "bankaya_e_haciz_bildirisi",
    "haciz_bildirimi",
    "e_haciz_bildirimi",
]

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


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rule_by_id(ruleset, rule_id):
    matches = [r for r in ruleset["rules"] if r.get("rule_id") == rule_id]
    return matches[0] if len(matches) == 1 else None


def _activated(rule):
    """Kaydın YALNIZ BELLEKTE etkinleştirilmiş kopyası: status ve
    calculation_enabled dışında hiçbir alan değişmez."""
    clone = copy.deepcopy(rule)
    clone["status"] = "active"
    clone["calculation_enabled"] = True
    return clone


def _activated_ruleset(ruleset):
    clone = copy.deepcopy(ruleset)
    for rule_id in RULE_SPECS:
        rule = _rule_by_id(clone, rule_id)
        rule["status"] = "active"
        rule["calculation_enabled"] = True
    return clone


def _anchor(date="2026-02-10", document_ids=("synthetic_doc_001",), verification="verified"):
    return {
        "event_id": "timeline_event_synthetic",
        "event_type": "notification_date",
        "date": date,
        "date_precision": "exact",
        "verification_state": verification,
        "confidence": 0.95,
        "source_document_ids": list(document_ids),
    }


def _context(document_types):
    return {
        "case_types": set(),
        "tax_types": {"gelir vergisi"},
        "case_stages": set(),
        "anchor_document_types": set(document_types),
    }


def _linked_case(tax_types=LINKED_TAX_TYPES):
    """Çapa belgesine bağlı, teyitli kalem(ler) + aynı belgeye ait teyitli
    vergi dairesi işlem kaydı (sentetik; gerçek veri yok)."""
    return {
        "case_id": "synthetic_case_wave2",
        "dispute_items": [
            {
                "dispute_item_id": "synthetic_item_%03d" % index,
                "tax_type": tax_type,
                "source_document_ids": [LINKED_DOCUMENT_ID],
                "verification_state": "verified",
            }
            for index, tax_type in enumerate(tax_types, 1)
        ],
        "administrative_actions": [
            {
                "action_id": "synthetic_action_001",
                "action_category": "payment_order",
                "issuing_authority": LINKED_AUTHORITY,
                "source_document_id": LINKED_DOCUMENT_ID,
                "verification_state": "verified",
            }
        ],
    }


def _receivable_context(rule, tax_types=LINKED_TAX_TYPES):
    """`build_deadline_record()`'un ürettiği hazır sonuç nesnesinin AYNISI:
    gerçek değerlendirici, sentetik bağlı kurguyla çağrılır."""
    return dc.evaluate_mali_tatil_action_document_receivables(
        _linked_case(tax_types),
        _anchor(),
        rule,
        {LINKED_DOCUMENT_ID: rule["applicability"]["document_types"][0]},
    )


def _calc(rule, anchor, *, recess=True, tax=None):
    return dc.calculate_rule_deadline(
        anchor_date=anchor,
        rule=rule,
        holiday_calendar=CALENDAR,
        judicial_recess_applicable=recess,
        case_tax_context=_receivable_context(
            rule, LINKED_TAX_TYPES if tax is None else tax,
        ),
    )


CALENDAR = None


# ================================================================
# (0) ÖN KOŞULLAR
# ================================================================

def test_preconditions(ruleset):
    result = rule_validator.validate_deadline_rules(
        ruleset_path=RULESET_PATH, raise_on_error=False,
    )
    check(
        "(0) gerçek registry deadline_rule_validator'dan geçer (errors=[])",
        result["valid"] is True and result["errors"] == [],
        result["errors"],
    )
    check(
        "(0) üretim takvimi 2024-2035'in 12 yılını da kapsıyor (örnekler 2025-2026)",
        CALENDAR["covered_verified_years"] == set(range(2024, 2036)),
        CALENDAR["covered_verified_years"],
    )
    check(
        "(0) örnek listesi: 26 örnek, numaralar tekil",
        len(EXAMPLES) == 26 and len({e[0] for e in EXAMPLES}) == 26,
    )
    for rule_id, spec in RULE_SPECS.items():
        label = spec["label"]
        rule = _rule_by_id(ruleset, rule_id)
        check(f"(0) {label}: kayıt registry'de tam bir kez bulunur", rule is not None)
        if rule is None:
            continue
        check(
            f"(0) {label}: örnek sayısı {spec['example_count']}",
            len([e for e in EXAMPLES if e[1] == rule_id]) == spec["example_count"],
        )
        check(
            f"(0) {label}: {spec['days']} takvim günü, tebliği izleyen gün, "
            "son gün tatilse izleyen çalışma günü",
            rule["duration"] == {"value": spec["days"], "unit": "day"}
            and rule["start_rule"] == "next_day"
            and rule["day_count_policy"] == "calendar_days"
            and rule["end_day_policy"] == "next_business_day_if_holiday",
            rule,
        )
        check(
            f"(0) {label}: çapa notification_date, belge türleri {spec['document_types']}",
            rule["anchor_event_types"] == ["notification_date"]
            and rule["applicability"]["document_types"] == spec["document_types"]
            and rule["applicability"]["case_types"] == []
            and rule["applicability"]["tax_types"] == []
            and rule["applicability"]["case_stages"] == [],
            rule["applicability"],
        )
        check(
            f"(0) {label}: dayanak listesi beklenen dar listeye birebir eşit",
            rule["legal_basis_refs"] == spec["refs"],
            rule["legal_basis_refs"],
        )
        check(
            f"(0) {label}: effective_from={spec['effective_from']!r}, effective_to boş",
            rule["effective_from"] == spec["effective_from"] and rule["effective_to"] is None,
            (rule["effective_from"], rule["effective_to"]),
        )
        check(
            f"(0) {label}: doğrulanmış çapa şart, insan incelemesi şart, priority=100",
            rule["required_anchor_verification"] == "verified"
            and rule["requires_human_review"] is True
            and rule["priority"] == 100,
        )
        check(
            f"(0) {label}: mali tatil dayanağı İYUK adli tatil dayanaklarıyla BİRLİKTE (§13.2)",
            dc.rule_has_mali_tatil_basis(rule) is True
            and dc.rule_has_iyuk_recess_basis(rule) is True,
            rule["legal_basis_refs"],
        )
        check(
            f"(0) {label}: notlar TASLAK / LEGAL_APPROVED kaydı yok uyarısıyla başlar ve "
            "avukat formunun özetini taşır",
            isinstance(rule["notes"], str)
            and rule["notes"].startswith(DRAFT_NOTES_PREFIX)
            and LAWYER_FORM_SHA256 in rule["notes"],
        )
        linked = _receivable_context(rule)
        check(
            f"(0) {label}: kural işlem belgesine bağlı alacak modundadır; örnek kurgusu "
            "(bağlı, teyitli gelir vergisi + vergi dairesi) mali tatili uygulatır",
            rule.get("mali_tatil_receivable_basis") == "action_document_receivables"
            and linked["outcome"] == "apply"
            and linked["action_document_id"] == LINKED_DOCUMENT_ID,
            (linked["outcome"], linked["reason_code"]),
        )


# ================================================================
# (1) TASLAKLAR NORMAL KULLANIMDA ETKİN DEĞİLDİR
# ================================================================

def test_drafts_inactive_in_normal_use(ruleset):
    result = rule_validator.validate_deadline_rules(
        ruleset_path=RULESET_PATH, raise_on_error=False,
    )
    check(
        "(1) registry: 4 kural, 1 active + 3 draft, hesaplaması açık yalnız 1 kural",
        result["rule_count"] == 4
        and result["status_counts"] == {"active": 1, "draft": 3}
        and result["calculation_enabled_count"] == 1,
        result,
    )
    selectable = [r["rule_id"] for r in ruleset["rules"] if selection.rule_is_selectable(r)]
    check(
        "(1) seçilebilir tek kural mevcut İYUK kuralıdır",
        selectable == [IYUK_RULE_ID],
        selectable,
    )

    for rule_id, spec in RULE_SPECS.items():
        label = spec["label"]
        rule = _rule_by_id(ruleset, rule_id)
        check(
            f"(1) {label}: status=draft ve calculation_enabled=false",
            rule is not None
            and rule["status"] == "draft"
            and rule["calculation_enabled"] is False,
        )
        if rule is None:
            continue

        direct = _calc(rule, "2026-02-10")
        check(
            f"(1) {label}: hesaplayıcı taslak kayıtla tarih ÜRETMEZ "
            "(needs_review, 'Rule active değil.')",
            direct["calculation_state"] == NEEDS_REVIEW
            and direct["calculated_deadline"] is None
            and direct["reason"] == "Rule active değil.",
            direct,
        )
        half = copy.deepcopy(rule)
        half["status"] = "active"
        half_result = _calc(half, "2026-02-10")
        check(
            f"(1) {label}: yalnız status değişse bile calculation_enabled=false tarih ÜRETMEZ",
            half_result["calculation_state"] == NEEDS_REVIEW
            and half_result["calculated_deadline"] is None,
            half_result,
        )

        for document_type in spec["document_types"]:
            sel = selection.select_deadline_rule(
                ruleset, _anchor(), _context([document_type]),
            )
            check(
                f"(1) {label} / {document_type}: seçim no_match, hesap izni yok",
                sel["selection_state"] == "no_match"
                and sel["selected_rule"] is None
                and sel["calculation_allowed"] is False
                and sel["requires_human_review"] is True,
                {k: sel.get(k) for k in ("selection_state", "reason")},
            )
            rejected = {r["rule_id"]: r["reasons"] for r in sel["rejected_rules"]}
            check(
                f"(1) {label} / {document_type}: kendi kuralının TEK red nedeni taslak olması",
                rejected.get(rule_id) == ["rule_not_active_or_enabled"],
                rejected,
            )
            record = dc.build_deadline_record(
                case_id="synthetic_case_wave2",
                anchor_event=_anchor(),
                selection=sel,
                ruleset_path=RULESET_PATH,
                holiday_calendar=CALENDAR,
                judicial_recess_applicable=True,
                stopping_event_status="none",
                stopping_event_attestation_ref=None,
            )
            check(
                f"(1) {label} / {document_type}: kayıt blocked_missing_rule, tarih yok, "
                "taslak kural kayda sızmaz",
                record["calculation_state"] == "blocked_missing_rule"
                and record["calculated_deadline"] is None
                and record["requires_human_review"] is True
                and record["rule_id"] == "unresolved_deadline_rule"
                and record["legal_basis_refs"] == [],
                {k: record.get(k) for k in ("calculation_state", "rule_id", "calculated_deadline")},
            )

    ihbarname = selection.select_deadline_rule(
        ruleset, _anchor(), _context(["vergi_ceza_ihbarnamesi"]),
    )
    rejected = {r["rule_id"]: r["reasons"] for r in ihbarname["rejected_rules"]}
    check(
        "(1) gerileme: ihbarname çapası mevcut İYUK kuralını seçer; üç taslak da reddedilir",
        ihbarname["selection_state"] == "selected"
        and ihbarname["selected_rule"]["rule_id"] == IYUK_RULE_ID
        and all("rule_not_active_or_enabled" in rejected.get(r, []) for r in RULE_SPECS),
        rejected,
    )


# ================================================================
# (2) + (3) ALTIN ÖRNEKLER VE MEKANİZMA
# ================================================================

def test_golden_examples(ruleset):
    per_rule = {rule_id: [0, 0] for rule_id in RULE_SPECS}
    for no, rule_id, anchor, expect, mali, adli, tatil, effect in EXAMPLES:
        label = RULE_SPECS[rule_id]["label"]
        rule = _activated(_rule_by_id(ruleset, rule_id))
        result = _calc(rule, anchor)
        got_state = result.get("calculation_state")
        got_date = result.get("calculated_deadline")
        ok = got_state == CALCULATED and got_date == expect
        per_rule[rule_id][0] += 1
        per_rule[rule_id][1] += 1 if ok else 0
        detail = (
            "\n        BEKLENEN: %s  GÖZLENEN: state=%r date=%r reason=%r"
            "\n        mali=%r adli=%r tatil=%r base=%r provisional=%r"
            "\n        AVUKAT: %s"
            % (
                expect, got_state, got_date, result.get("reason"),
                result.get("mali_tatil_applied"),
                result.get("judicial_recess_applied"),
                result.get("holiday_adjustment_applied"),
                result.get("base_deadline"),
                result.get("provisional_deadline"),
                effect,
            )
        )
        check(
            "(2) ALTIN ÖRNEK %d [%s]: tebliğ %s -> son gün %s" % (no, label, anchor, expect),
            ok,
            detail,
        )
        check(
            "(3) MEKANİZMA %d [%s]: mali tatil=%s, adli tatil=%s, tatil kaydırması=%s"
            % (no, label, mali, adli, tatil),
            result.get("mali_tatil_applied") is mali
            and result.get("judicial_recess_applied") is adli
            and result.get("holiday_adjustment_applied") is tatil,
            detail,
        )
    for rule_id, (total, matched) in per_rule.items():
        spec = RULE_SPECS[rule_id]
        check(
            "(2) KURAL ÖZETİ [%s]: avukat örneklerinin TAMAMI tutuyor (%d/%d)"
            % (spec["label"], matched, total),
            total == spec["example_count"] and matched == total,
            (matched, total),
        )


# ================================================================
# (3b) MALİ TATİL ARA TARİHLERİ
# ================================================================

def test_mali_tatil_intermediate_dates(ruleset):
    by_no = {e[0]: e for e in EXAMPLES}
    mali_numbers = sorted(e[0] for e in EXAMPLES if e[4])
    check(
        "(3b) ara tarih tablosu mali tatil içeren beş örneğin TAMAMINI kapsar "
        "(6, 116, 117, 118, 131)",
        mali_numbers == sorted(MALI_INTERMEDIATE) == [6, 116, 117, 118, 131],
        (mali_numbers, sorted(MALI_INTERMEDIATE)),
    )
    for no, (intermediate, sentence) in sorted(MALI_INTERMEDIATE.items()):
        _no, rule_id, anchor, expect, _mali, _adli, _tatil, _effect = by_no[no]
        label = RULE_SPECS[rule_id]["label"]
        rule = _activated(_rule_by_id(ruleset, rule_id))
        # Adli tatil uzaması kapatıldığında (mahkeme yararlanmıyor)
        # hesaplayıcının mali tatil SONRASI ara sonucu, hafta sonu/tatil
        # kaydırmasından ÖNCEKİ değer olan `provisional_deadline`
        # alanında görünür. Avukatın "tamamlanır" dediği gün budur.
        without_recess = _calc(rule, anchor, recess=False)
        with_recess = _calc(rule, anchor, recess=True)
        detail = (
            "\n        AVUKAT: %s"
            "\n        adli tatilsiz: state=%r base=%r provisional=%r final=%r mali=%r adli=%r"
            "\n        adli tatilli : provisional=%r final=%r adli=%r"
            % (
                sentence,
                without_recess.get("calculation_state"),
                without_recess.get("base_deadline"),
                without_recess.get("provisional_deadline"),
                without_recess.get("calculated_deadline"),
                without_recess.get("mali_tatil_applied"),
                without_recess.get("judicial_recess_applied"),
                with_recess.get("provisional_deadline"),
                with_recess.get("calculated_deadline"),
                with_recess.get("judicial_recess_applied"),
            )
        )
        check(
            "(3b) ARA TARİH %d [%s]: tebliğ %s -> mali tatil sonrası süre %s günü tamamlanır"
            % (no, label, anchor, intermediate),
            without_recess.get("calculation_state") == CALCULATED
            and without_recess.get("mali_tatil_applied") is True
            and without_recess.get("judicial_recess_applied") is False
            and without_recess.get("provisional_deadline") == intermediate,
            detail,
        )
        check(
            "(3b) ARA TARİH %d [%s]: bu gün mali tatilsiz ham sayımın bitişinden FARKLIDIR "
            "(duraklama gerçekten uygulanmıştır)" % (no, label),
            without_recess.get("base_deadline") not in (None, intermediate),
            detail,
        )
        year, month, day = (int(part) for part in intermediate.split("-"))
        check(
            "(3b) ARA TARİH %d [%s]: %s çalışmaya ara verme dönemindedir; adli tatil "
            "uzamasıyla son gün %s olur" % (no, label, intermediate, expect),
            dc.is_within_iyuk_judicial_recess(date(year, month, day)) is True
            and with_recess.get("judicial_recess_applied") is True
            and with_recess.get("calculated_deadline") == expect,
            detail,
        )


# ================================================================
# (4) AYIRT EDİCİLİK - parametre değişince sonuç da değişir
# ================================================================

def test_discrimination(ruleset):
    for rule_id, spec in RULE_SPECS.items():
        label = spec["label"]
        base = _activated(_rule_by_id(ruleset, rule_id))
        examples = [e for e in EXAMPLES if e[1] == rule_id]

        for delta in (-1, 1):
            mutant = copy.deepcopy(base)
            mutant["duration"]["value"] = spec["days"] + delta
            differing = [
                e[0] for e in examples
                if _calc(mutant, e[2]).get("calculated_deadline") != e[3]
            ]
            plain = [e[0] for e in examples if not (e[4] or e[5] or e[6])]
            check(
                f"(4) {label}: süre {spec['days'] + delta} gün olsaydı tatilsiz örneklerin "
                "tamamı tutmazdı",
                len(plain) > 0 and all(no in differing for no in plain),
                {"tatilsiz": plain, "farklı": differing},
            )

        no_mali = copy.deepcopy(base)
        no_mali["legal_basis_refs"] = [r for r in no_mali["legal_basis_refs"] if r != MALI_REF]
        mali_examples = [e for e in examples if e[4]]
        mali_results = [(e[0], e[3], _calc(no_mali, e[2])) for e in mali_examples]
        check(
            f"(4) {label}: mali tatil dayanağı olmasaydı mali tatil HİÇ uygulanmazdı",
            len(mali_results) > 0
            and all(r.get("mali_tatil_applied") is False for (_no, _exp, r) in mali_results),
            [(no, r.get("mali_tatil_applied")) for (no, _exp, r) in mali_results],
        )
        check(
            f"(4) {label}: mali tatil dayanağı olmasaydı mali tatil örneklerinden en az biri "
            "farklı tarih verirdi",
            any(r.get("calculated_deadline") != exp for (_no, exp, r) in mali_results),
            [(no, exp, r.get("calculated_deadline")) for (no, exp, r) in mali_results],
        )

        no_recess = copy.deepcopy(base)
        no_recess["legal_basis_refs"] = [
            r for r in no_recess["legal_basis_refs"] if r not in RECESS_REFS
        ]
        adli_examples = [e for e in examples if e[5]]
        check(
            f"(4) {label}: adli tatil dayanağı olmasaydı adli tatil örneklerinin tamamı tutmazdı",
            len(adli_examples) > 0
            and all(
                _calc(no_recess, e[2]).get("calculated_deadline") != e[3]
                for e in adli_examples
            ),
            [(e[0], _calc(no_recess, e[2]).get("calculated_deadline")) for e in adli_examples],
        )
        check(
            f"(4) {label}: mahkeme adli tatilden yararlanmıyorsa (False) adli tatil örnekleri "
            "7 Eylül'e uzamaz",
            all(
                _calc(base, e[2], recess=False).get("judicial_recess_applied") is False
                and _calc(base, e[2], recess=False).get("calculated_deadline") != e[3]
                for e in adli_examples
            ),
        )
        check(
            f"(4) {label}: adli tatil beyanı bilinmiyorsa (None) adli tatil örneklerinde "
            "tarih ÜRETİLMEZ (needs_review)",
            all(
                _calc(base, e[2], recess=None).get("calculation_state") == NEEDS_REVIEW
                and _calc(base, e[2], recess=None).get("calculated_deadline") is None
                for e in adli_examples
            ),
        )
        # Kol A mali tatil Dilim A: ayrım, dava konusu işlem belgesine
        # BAĞLI ve teyitli kalemin vergi türüyle kurulur.
        excluded = ("ötv",)
        unknown = ("bilinmeyen vergi",)
        check(
            f"(4) {label}: 5604 m.1/7 istisnasındaki vergi türünde (ÖTV) mali tatil uygulanmaz",
            all(_calc(base, e[2], tax=excluded).get("mali_tatil_applied") is False
                for e in mali_examples),
        )
        check(
            f"(4) {label}: tanınmayan vergi türünde mali tatile dokunan örnekte tarih ÜRETİLMEZ",
            all(
                _calc(base, e[2], tax=unknown).get("calculation_state") == NEEDS_REVIEW
                and _calc(base, e[2], tax=unknown).get("calculated_deadline") is None
                for e in mali_examples
            ),
        )


# ================================================================
# (5) SEÇİM - bellekte etkinleştirilmiş kayıtla
# ================================================================

def test_selection_when_activated(ruleset):
    active = _activated_ruleset(ruleset)
    check(
        "(5) bellekteki kopyada yalnız üç kuralın status/calculation_enabled alanı değişti",
        all(
            {k: v for k, v in a.items() if k not in ("status", "calculation_enabled")}
            == {k: v for k, v in b.items() if k not in ("status", "calculation_enabled")}
            for a, b in zip(active["rules"], ruleset["rules"])
        )
        and _rule_by_id(active, IYUK_RULE_ID) == _rule_by_id(ruleset, IYUK_RULE_ID),
    )

    for rule_id, spec in RULE_SPECS.items():
        for document_type in spec["document_types"]:
            sel = selection.select_deadline_rule(active, _anchor(), _context([document_type]))
            check(
                f"(5) {document_type}: yalnız kendi kuralı seçilir ({spec['label']})",
                sel["selection_state"] == "selected"
                and sel["selected_rule"]["rule_id"] == rule_id
                and sel["matched_rule_ids"] == [rule_id]
                and sel["calculation_allowed"] is True
                and sel["requires_human_review"] is True,
                {k: sel.get(k) for k in ("selection_state", "matched_rule_ids")},
            )

    ihbarname = selection.select_deadline_rule(
        active, _anchor(), _context(["vergi_ceza_ihbarnamesi"]),
    )
    check(
        "(5) gerileme: ihbarname çapası etkinleştirme sonrasında da YALNIZ İYUK kuralını seçer",
        ihbarname["selection_state"] == "selected"
        and ihbarname["matched_rule_ids"] == [IYUK_RULE_ID],
        ihbarname.get("matched_rule_ids"),
    )

    for pair, expected in (
        (["odeme_emri", "vergi_ceza_ihbarnamesi"], [PAYMENT_ORDER, IYUK_RULE_ID]),
        (["borcluya_haciz_bildirimi", "ihtiyati_haciz_giyapta_tebligi"], [SEIZURE, PRECAUTIONARY]),
        (["odeme_emri", "borcluya_e_haciz_bildirimi"], [PAYMENT_ORDER, SEIZURE]),
    ):
        both = selection.select_deadline_rule(active, _anchor(), _context(pair))
        check(
            f"(5) iki belge türlü çapa {pair}: ambiguous, kural seçilmez (fail-closed)",
            both["selection_state"] == "ambiguous"
            and both["selected_rule"] is None
            and both["calculation_allowed"] is False
            and sorted(both["ambiguous_rule_ids"]) == sorted(expected),
            both.get("ambiguous_rule_ids"),
        )

    unknown = selection.select_deadline_rule(
        active, _anchor(), _context(["ihtiyati_haciz_huzurda_tutanagi"]),
    )
    check(
        "(5) kural bağlanmamış belge türü (huzurda uygulanan ihtiyati haciz): no_match",
        unknown["selection_state"] == "no_match" and unknown["selected_rule"] is None,
        unknown.get("selection_state"),
    )
    empty = selection.select_deadline_rule(active, _anchor(), _context([]))
    check(
        "(5) belge türü bilinmeyen çapa: no_match (kural kısıtı var, bağlam yok -> fail-closed)",
        empty["selection_state"] == "no_match",
        empty.get("selection_state"),
    )

    # ------------------------------------------------------------
    # BORÇLUYA DEĞİL, BANKAYA / ÜÇÜNCÜ ŞAHSA YAPILAN BİLDİRİM
    #
    # KANITLANAN: seçim belge türü etiketini BİREBİR karşılaştırır.
    # Belge "bankaya / üçüncü şahsa haciz bildirisi" olarak ya da
    # kayıttan çıkarılan eski genel adlarla türlenmişse haciz kuralı
    # (ve başka hiçbir kural) seçilmez, hesap izni verilmez, kayıt
    # tarih taşımaz.
    #
    # KANITLANMAYAN: belgenin İÇERİĞİ hiçbir yerde denetlenmez. Bankaya
    # yapılmış bir bildirim yanlışlıkla `borcluya_haciz_bildirimi`
    # etiketiyle kaydedilirse kural seçilir. En alttaki "SINIR"
    # kontrolü bu davranışı bilerek sabitler: geçmesi bir güvence
    # DEĞİL, sınırın yazılı kaydıdır.
    # ------------------------------------------------------------
    for document_type in NOT_DEBTOR_NOTICE_TYPES:
        sel = selection.select_deadline_rule(active, _anchor(), _context([document_type]))
        rejected = {r["rule_id"]: r["reasons"] for r in sel["rejected_rules"]}
        check(
            f"(5) borçluya yapılmamış bildirim türü '{document_type}': hiçbir kural seçilmez "
            "(no_match), hesap izni yok",
            sel["selection_state"] == "no_match"
            and sel["selected_rule"] is None
            and sel["matched_rule_ids"] == []
            and sel["calculation_allowed"] is False
            and sel["requires_human_review"] is True,
            {k: sel.get(k) for k in ("selection_state", "matched_rule_ids")},
        )
        check(
            f"(5) '{document_type}': haciz kuralının TEK red nedeni belge türü uyuşmazlığıdır",
            rejected.get(SEIZURE) == ["document_type_mismatch"],
            rejected.get(SEIZURE),
        )
        record = dc.build_deadline_record(
            case_id="synthetic_case_wave2",
            anchor_event=_anchor(),
            selection=sel,
            ruleset_path=RULESET_PATH,
            holiday_calendar=CALENDAR,
            judicial_recess_applicable=True,
            stopping_event_status="none",
            stopping_event_attestation_ref=None,
        )
        check(
            f"(5) '{document_type}': kayıt blocked_missing_rule, tarih yok",
            record["calculation_state"] == "blocked_missing_rule"
            and record["calculated_deadline"] is None
            and record["rule_id"] == "unresolved_deadline_rule",
            {k: record.get(k) for k in ("calculation_state", "rule_id", "calculated_deadline")},
        )

    same_anchor = _anchor()
    labelled_debtor = selection.select_deadline_rule(
        active, same_anchor, _context(["borcluya_haciz_bildirimi"]),
    )
    labelled_bank = selection.select_deadline_rule(
        active, same_anchor, _context(["bankaya_haciz_bildirisi"]),
    )
    check(
        "(5) SINIR (bu testin KANITLAMADIĞI şey): seçim YALNIZ etikete bakar - aynı çapa, "
        "etiketi 'borcluya_haciz_bildirimi' yazılınca seçilir, 'bankaya_haciz_bildirisi' "
        "yazılınca seçilmez; bildirimin gerçekte kime yapıldığını yazılım DENETLEMEZ",
        labelled_debtor["selection_state"] == "selected"
        and labelled_debtor["selected_rule"]["rule_id"] == SEIZURE
        and labelled_bank["selection_state"] == "no_match",
        (labelled_debtor.get("selection_state"), labelled_bank.get("selection_state")),
    )

    old_anchor = _anchor(date="2017-12-31")
    for rule_id in (PAYMENT_ORDER, PRECAUTIONARY):
        spec = RULE_SPECS[rule_id]
        sel = selection.select_deadline_rule(
            active, old_anchor, _context(spec["document_types"][:1]),
        )
        rejected = {r["rule_id"]: r["reasons"] for r in sel["rejected_rules"]}
        check(
            f"(5) {spec['label']}: 2017-12-31 çapası effective_from ile reddedilir (no_match)",
            sel["selection_state"] == "no_match"
            and rejected.get(rule_id) == ["effective_date_mismatch"],
            rejected.get(rule_id),
        )
    first_day = selection.select_deadline_rule(
        active, _anchor(date="2018-01-01"), _context(["odeme_emri"]),
    )
    check(
        "(5) ödeme emri: 2018-01-01 çapası seçilir (effective_from dahil)",
        first_day["selection_state"] == "selected"
        and first_day["selected_rule"]["rule_id"] == PAYMENT_ORDER,
        first_day.get("selection_state"),
    )

    unverified = selection.select_deadline_rule(
        active, _anchor(verification="unverified"), _context(["odeme_emri"]),
    )
    check(
        "(5) doğrulanmamış çapa: kural seçilir ama hesap izni YOK (selected_blocked_anchor)",
        unverified["selection_state"] == "selected_blocked_anchor"
        and unverified["calculation_allowed"] is False,
        unverified.get("selection_state"),
    )


# ================================================================
# GEÇİCİ DİZİN YARDIMCILARI ((6) ve (7))
# ================================================================

def _verified_provisions_fixture():
    """Üretim hüküm kaydının GEÇİCİ, yalnız teste özgü kopyası: 6183
    m.58/1 ve m.15/1 "doğrulanmış" gibi kurulur. Bu, etkinleştirme
    sonrası durumun VARSAYIMSAL bir modelidir; üretim kaydında bu
    hükümler doğrulanmamıştır ve bu test onları değiştirmez."""
    manifest = _load_json(PROVISIONS_PATH)
    touched = []
    for provision in manifest["provisions"]:
        if provision["provision_id"] not in ("kanun_6183_m58_f1", "kanun_6183_m15_f1"):
            continue
        provision["verification_state"] = "verified"
        provision["formal"]["verified"] = True
        provision["formal"]["status"] = "active"
        provision["formal"]["valid_from"] = "2018-01-01"
        for item in provision["formal"]["evidence"]:
            item["verified"] = True
        provision["formal"]["evidence"].append({
            "evidence_id": "ev_test_only_%s_amending_7061" % provision["provision_id"],
            "kind": "amending_law",
            "source_document_id": None,
            "source_url": "https://example.invalid/test-only-fixture",
            "citation": "YALNIZ TEST: 7061 sayılı Kanun m.9 ve m.123 (sentetik kanıt)",
            "verified": True,
            "notes": "Geçici test kopyası; üretim kaydı değildir.",
        })
        touched.append(provision["provision_id"])
    return manifest, sorted(touched)


def _basis(ruleset_path, manifest_path, query_date):
    out = resolver.resolve_ruleset_legal_basis(
        ruleset_path=ruleset_path,
        manifest_path=manifest_path,
        temporal_mode="historical_date",
        query_date=query_date,
    )
    return {r["rule_id"]: r for r in out["rules"]}


# ================================================================
# (6) DAYANAK
# ================================================================

def test_legal_basis(tmp_root):
    # Üretim hüküm kaydı: iki 6183 hükmü VAR ve DOĞRULANMAMIŞ.
    provisions = _load_json(PROVISIONS_PATH)["provisions"]
    for provision_id, madde in (("kanun_6183_m58_f1", "58"), ("kanun_6183_m15_f1", "15")):
        matches = [p for p in provisions if p["provision_id"] == provision_id]
        check(f"(6) {provision_id}: hüküm kaydı tam bir kez bulunur", len(matches) == 1)
        if len(matches) != 1:
            continue
        provision = matches[0]
        check(
            f"(6) {provision_id}: kanun_6183 m.{madde} f.1, sürüm {provision_id}_v1",
            provision["document_id"] == "kanun_6183"
            and provision["provision_version_id"] == provision_id + "_v1"
            and provision["locator"] == {"madde": madde, "fikra": "1", "bent": None},
            provision["locator"],
        )
        check(
            f"(6) {provision_id}: DOĞRULANMAMIŞ (unverified, formal.verified=false, "
            "status=unknown, valid_from boş)",
            provision["verification_state"] == "unverified"
            and provision["formal"]["verified"] is False
            and provision["formal"]["status"] == "unknown"
            and provision["formal"]["valid_from"] is None,
            provision["formal"],
        )
        evidence = provision["formal"]["evidence"]
        check(
            f"(6) {provision_id}: kanıt listesi yalnız doğrulanmamış ADAY içerir "
            "(tek kayıt, konsolide metin, verified=false)",
            len(evidence) == 1
            and evidence[0]["verified"] is False
            and evidence[0]["kind"] == "consolidated_legislation"
            and evidence[0]["source_document_id"] == "kanun_6183",
            evidence,
        )

    current = {r["rule_id"]: r for r in resolver.resolve_ruleset_legal_basis(RULESET_PATH)["rules"]}
    for rule_id, spec in RULE_SPECS.items():
        label = spec["label"]
        item = current.get(rule_id)
        if item is not None and spec["unverified_ref"] is not None:
            resolution = next(
                (r for r in item["resolutions"]
                 if r["legal_basis_ref"] == spec["unverified_ref"]), None,
            )
            check(
                f"(6) {label}: {spec['unverified_ref']} kayıttaki hükme tam fıkra eşleşmesiyle "
                "bağlanır ama çözülmüş SAYILMAZ (doğrulanmamış)",
                resolution is not None
                and resolution["parsed"]["document_id"] == "kanun_6183"
                and resolution["repository_match_type"] == "exact_fikra"
                and len(resolution["selected_provision_version_ids"]) == 1
                and resolution["resolved"] is False
                and resolution["activation_eligible"] is False,
                resolution,
            )
        if spec["unverified_ref"] is None:
            check(
                f"(6) {label}: üretim hükümleriyle tüm dayanaklar çözülür ve doğrulanmıştır",
                item is not None
                and item["all_resolved"] is True
                and item["all_basis_verified"] is True
                and item["activation_eligible"] is True
                and item["activation_blocked_refs"] == [],
                item,
            )
        else:
            check(
                f"(6) {label}: üretim hükümleriyle etkinleştirmeye UYGUN DEĞİL; "
                f"tek engel {spec['unverified_ref']} (doğrulanmamış)",
                item is not None
                and item["all_basis_verified"] is False
                and item["activation_eligible"] is False
                and item["activation_blocked_refs"] == [spec["unverified_ref"]],
                item,
            )

    manifest, touched = _verified_provisions_fixture()
    fixture_path = tmp_root / "provisions_verified_fixture.json"
    fixture_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    check(
        "(6) geçici kopya: yalnız kanun_6183_m15_f1 ve kanun_6183_m58_f1 değiştirildi",
        touched == ["kanun_6183_m15_f1", "kanun_6183_m58_f1"],
        touched,
    )
    at_2026 = _basis(RULESET_PATH, fixture_path, "2026-02-10")
    at_2017 = _basis(RULESET_PATH, fixture_path, "2017-06-01")
    for rule_id, spec in RULE_SPECS.items():
        label = spec["label"]
        check(
            f"(6) {label}: geçici 'doğrulanmış' kopyayla 2026-02-10 itibarıyla uygun",
            at_2026[rule_id]["all_resolved"] is True
            and at_2026[rule_id]["all_basis_verified"] is True
            and at_2026[rule_id]["activation_eligible"] is True,
            at_2026[rule_id].get("activation_blocked_refs"),
        )
        if spec["unverified_ref"] is not None:
            check(
                f"(6) {label}: aynı kopyayla 2017-06-01 itibarıyla UYGUN DEĞİL "
                "(15 günlük metin 2018-01-01'de başlar)",
                at_2017[rule_id]["activation_eligible"] is False,
                at_2017[rule_id].get("activation_blocked_refs"),
            )
    return fixture_path


# ================================================================
# (7) UÇTAN UCA - geçici dizinde sentetik dosya
# ================================================================

END_TO_END_CASES = [
    # (kural, belge türü, örnek no, vergi türü)
    (PAYMENT_ORDER, "odeme_emri", 2, "Gelir Vergisi"),
    (PAYMENT_ORDER, "odeme_emri", 6, "Gelir Vergisi"),
    (SEIZURE, "borcluya_haciz_bildirimi", 128, "KDV"),
    (SEIZURE, "borcluya_e_haciz_bildirimi", 131, "KDV"),
    (PRECAUTIONARY, "ihtiyati_haciz_giyapta_tebligi", 108, "Gelir Vergisi"),
    (PRECAUTIONARY, "ihtiyati_haciz_giyapta_tebligi", 116, "Gelir Vergisi"),
]

ATTESTATION_REF = "AV-BEYAN-KOLA-DILIM1-001"


def _write_case(cases_dir, case_id, document_type, tax_type):
    case_dir = cases_dir / case_id
    doc_dir = case_dir / "documents" / "synthetic_doc_001"
    doc_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text(json.dumps({
        "schema_version": 1,
        "case_id": case_id,
        "active": True,
        "title": "Kol A Dilim 1 sentetik test dosyası",
        "case_type": None,
        "stage": None,
        "dispute_items": [{
            "dispute_item_id": "synthetic_item_001",
            "tax_type": tax_type,
            "source_document_ids": ["synthetic_doc_001"],
            "verification_state": "verified",
        }],
        "administrative_actions": [{
            "action_id": "synthetic_action_001",
            "action_category": "payment_order",
            "issuing_authority": LINKED_AUTHORITY,
            "source_document_id": "synthetic_doc_001",
            "verification_state": "verified",
        }],
        "events": [],
        "proceedings": [],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (doc_dir / "document.json").write_text(json.dumps({
        "schema_version": 1,
        "document_id": "synthetic_doc_001",
        "case_id": case_id,
        "active": True,
        "document_type": document_type,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _record(case_id, anchor, active_ruleset, ruleset_path, provisions_path, *,
            stopping_status="none", stopping_ref=ATTESTATION_REF):
    case_data, _ = deadline_validator.load_case(case_id)
    context = selection.build_case_context(case_id, case_data, anchor)
    sel = selection.select_deadline_rule(active_ruleset, anchor, context)
    record = dc.build_deadline_record(
        case_id=case_id,
        anchor_event=anchor,
        selection=sel,
        ruleset_path=ruleset_path,
        holiday_calendar=CALENDAR,
        judicial_recess_applicable=True,
        provisions_path=provisions_path,
        stopping_event_status=stopping_status,
        stopping_event_attestation_ref=stopping_ref,
    )
    return context, sel, record


def test_end_to_end(ruleset, tmp_root, verified_provisions_path):
    cases_dir = tmp_root / "cases"
    cases_dir.mkdir()
    active_ruleset = _activated_ruleset(ruleset)
    active_ruleset_path = tmp_root / "deadline_rules_active_fixture.json"
    active_ruleset_path.write_text(
        json.dumps(active_ruleset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    fixture_validation = rule_validator.validate_deadline_rules(
        ruleset_path=active_ruleset_path, raise_on_error=False,
    )
    check(
        "(7) geçici 'etkin' registry kopyası doğrulayıcıdan geçer (4 active)",
        fixture_validation["valid"] is True
        and fixture_validation["status_counts"] == {"active": 4},
        fixture_validation["errors"],
    )

    original_cases_dir = deadline_validator.CASES_DIR
    original_selection_data_dir = selection.DATA_DIR
    try:
        deadline_validator.CASES_DIR = cases_dir
        selection.DATA_DIR = tmp_root

        by_no = {e[0]: e for e in EXAMPLES}
        for index, (rule_id, document_type, no, tax_type) in enumerate(END_TO_END_CASES, 1):
            label = RULE_SPECS[rule_id]["label"]
            example = by_no[no]
            case_id = "kola_dilim1_case_%02d" % index
            _write_case(cases_dir, case_id, document_type, tax_type)
            anchor = _anchor(date=example[2])
            context, sel, record = _record(
                case_id, anchor, active_ruleset, active_ruleset_path, verified_provisions_path,
            )
            check(
                f"(7) {label} / örnek {no}: belge kaydından belge türü okunur ({document_type})",
                context["anchor_document_types"] == {document_type},
                context["anchor_document_types"],
            )
            check(
                f"(7) {label} / örnek {no}: uçtan uca calculated ve son gün {example[3]}",
                sel["selection_state"] == "selected"
                and record["calculation_state"] == CALCULATED
                and record["calculated_deadline"] == example[3]
                and record["rule_id"] == rule_id
                and record["legal_basis_refs"] == RULE_SPECS[rule_id]["refs"]
                and record["requires_human_review"] is True,
                {k: record.get(k) for k in
                 ("calculation_state", "calculated_deadline", "rule_id", "notes")},
            )

        # --- güvenlik dalları: ödeme emri, örnek 2 ---
        case_id = "kola_dilim1_case_guard"
        _write_case(cases_dir, case_id, "odeme_emri", "Gelir Vergisi")
        example = by_no[2]

        _ctx, sel, record = _record(
            case_id, _anchor(date=example[2], verification="unverified"),
            active_ruleset, active_ruleset_path, verified_provisions_path,
        )
        check(
            "(7) doğrulanmamış tebliğ tarihi: blocked_unverified_anchor, tarih yok",
            sel["selection_state"] == "selected_blocked_anchor"
            and record["calculation_state"] == "blocked_unverified_anchor"
            and record["calculated_deadline"] is None,
            {k: record.get(k) for k in ("calculation_state", "calculated_deadline")},
        )
        for status in ("unknown", "present"):
            _ctx, _sel, record = _record(
                case_id, _anchor(date=example[2]),
                active_ruleset, active_ruleset_path, verified_provisions_path,
                stopping_status=status,
            )
            check(
                f"(7) durdurucu işlem beyanı '{status}': needs_review, tarih yok",
                record["calculation_state"] == NEEDS_REVIEW
                and record["calculated_deadline"] is None
                and record["requires_human_review"] is True,
                {k: record.get(k) for k in ("calculation_state", "notes")},
            )
        _ctx, _sel, record = _record(
            case_id, _anchor(date=example[2]),
            active_ruleset, active_ruleset_path, verified_provisions_path,
            stopping_status="none", stopping_ref=None,
        )
        check(
            "(7) durdurucu işlem beyanı 'none' ama beyan referansı yok: tarih yok",
            record["calculation_state"] == NEEDS_REVIEW
            and record["calculated_deadline"] is None,
            {k: record.get(k) for k in ("calculation_state", "notes")},
        )
        _ctx, sel, record = _record(
            case_id, _anchor(date=example[2]),
            active_ruleset, active_ruleset_path, PROVISIONS_PATH,
        )
        check(
            "(7) KURAL ETKİN AMA HÜKÜM DOĞRULANMAMIŞ (üretim hüküm kaydı): seçim yapılır, "
            "tarih ÜRETİLMEZ (needs_review - dayanak doğrulaması tamamlanamadı)",
            sel["selection_state"] == "selected"
            and record["calculation_state"] == NEEDS_REVIEW
            and record["calculated_deadline"] is None
            and "hukuki dayanak" in (record.get("notes") or ""),
            {k: record.get(k) for k in ("calculation_state", "calculated_deadline", "notes")},
        )
        _write_case(
            cases_dir, "kola_dilim1_case_seizure_guard", "borcluya_haciz_bildirimi", "KDV",
        )
        _ctx, sel, record = _record(
            "kola_dilim1_case_seizure_guard", _anchor(date=by_no[127][2]),
            active_ruleset, active_ruleset_path, PROVISIONS_PATH,
        )
        check(
            "(7) haciz kuralı: dayanakları üretimde zaten doğrulanmış olduğundan, kural etkin "
            "olsaydı üretim hüküm kaydıyla da hesaplanırdı (tek engel taslak olmasıdır)",
            record["calculation_state"] == CALCULATED
            and record["calculated_deadline"] == by_no[127][3],
            {k: record.get(k) for k in ("calculation_state", "calculated_deadline", "notes")},
        )

        # --- belge kaydı "bankaya yapılan bildirim" diyorsa ---
        # Aynı tarih, aynı dosya yapısı; yalnız document.json'daki tür
        # farklı. Kural etkin ve hükümler doğrulanmış olsa bile tarih yok.
        for index, document_type in enumerate(
            ("bankaya_e_haciz_bildirisi", "ucuncu_sahsa_haciz_bildirisi"), 1,
        ):
            case_id = "kola_dilim1_case_not_debtor_%02d" % index
            _write_case(cases_dir, case_id, document_type, "KDV")
            context, sel, record = _record(
                case_id, _anchor(date=by_no[127][2]),
                active_ruleset, active_ruleset_path, verified_provisions_path,
            )
            check(
                f"(7) belge kaydında tür '{document_type}': belge türü kayıttan okunur, kural "
                "seçilmez, tarih ÜRETİLMEZ (blocked_missing_rule)",
                context["anchor_document_types"] == {document_type}
                and sel["selection_state"] == "no_match"
                and record["calculation_state"] == "blocked_missing_rule"
                and record["calculated_deadline"] is None,
                {k: record.get(k) for k in ("calculation_state", "calculated_deadline")},
            )
    finally:
        deadline_validator.CASES_DIR = original_cases_dir
        selection.DATA_DIR = original_selection_data_dir

    check(
        "(7) yama geri alındı: deadline_validator.CASES_DIR ve selection.DATA_DIR üretim değerinde",
        deadline_validator.CASES_DIR == original_cases_dir
        and selection.DATA_DIR == original_selection_data_dir,
    )


def run_self_test():
    global CALENDAR
    before_data_snapshot = _snapshot_data_tree()

    CALENDAR = dc.load_holiday_calendar()
    ruleset = _load_json(RULESET_PATH)

    test_preconditions(ruleset)
    test_drafts_inactive_in_normal_use(ruleset)
    test_golden_examples(ruleset)
    test_mali_tatil_intermediate_dates(ruleset)
    test_discrimination(ruleset)
    test_selection_when_activated(ruleset)

    tmp_root = Path(tempfile.mkdtemp(prefix="vergi_kola_dilim1_"))
    try:
        verified_provisions_path = test_legal_basis(tmp_root)
        test_end_to_end(ruleset, tmp_root, verified_provisions_path)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    check("geçici dizin koşu sonunda silindi", not tmp_root.exists())

    after_data_snapshot = _snapshot_data_tree()
    check(
        "bu test modülü: gerçek data/ ağacı tüm koşu boyunca bayt-değişmez "
        "(SALT-OKUNUR - gerçek case dizini yok, PostgreSQL yok, ağ yok)",
        before_data_snapshot == after_data_snapshot,
    )

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
