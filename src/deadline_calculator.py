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
import unicodedata

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
    load_case,
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
# PILOT READINESS ADIM 7 - MALİ TATİL (5604 sayılı Kanun m.1)
#
# `MALI_TATIL_TRIGGER_REF` bir kuralın `legal_basis_refs` listesinde
# bulunup bulunmadığı KOŞULSUZ olarak kontrol edilir
# (`rule_has_mali_tatil_basis()` - `rule_has_iyuk_recess_basis()`
# ile AYNI, saf containment deseni). Ayrı bir operatör-beyanlı
# parametre YOKTUR (kullanıcı kararı) - mekanizma tamamen kuralın
# KENDİSİNİN bu referansı taşıyıp taşımadığına ve somut case'in
# 5604 m.1/7 istisna kapsamına girip girmediğine bağlıdır.
# ============================================================

MALI_TATIL_TRIGGER_REF = (
    "KANUN_5604_m1"
)

MALI_TATIL_GRACE_PERIOD_DAYS = 5

# 5604 m.1/7 (6661 sayılı Kanun m.18 ile güncellenmiş kapsam):
# özel tüketim vergisi, banka ve sigorta muameleleri vergisi, özel
# iletişim vergisi, şans oyunları vergisi - TAMAMEN kanunun kendi
# ADINDAN istisna edilmiştir, tarh/tahsil eden idareden BAĞIMSIZDIR.
# Değerler küçük harfle yazılmıştır; karşılaştırma HER ZAMAN
# `_normalize_mali_tatil_text()` üzerinden yapılır (bkz. aşağıda) -
# bu sabitlerin KENDİSİ "İ" harfi içermediğinden literal halleri zaten
# değişmeden kalır, ama karşılaştırma tarafı (gelen case verisi) "İ"
# içerebileceğinden normalizasyon HER İKİ tarafa da uygulanır.
MALI_TATIL_EXCLUDED_TAX_TYPES = frozenset(
    {
        "özel tüketim vergisi",
        "ötv",
        "banka ve sigorta muameleleri vergisi",
        "bsmv",
        "özel iletişim vergisi",
        "öiv",
        "şans oyunları vergisi",
    }
)

# Dar, doğrulanmış "bilinen dahil" listesi - VUK'a tabi, 5604 m.1/7
# tarafından istisna edilmemiş, vergi mahkemesi davalarında sık
# görülen vergi/ceza türleri. Bu listede OLMAYAN bir tax_type
# "unrecognized" sayılır (sessiz tahmin YOK, fail-closed).
#
# BAĞIMSIZ İNCELEME REMEDİASYONU (hukuk görüşü ışığında düzeltildi):
# "gecikme faizi"/"gecikme zammı" BİLİNÇLİ olarak bu listede DEĞİLDİR.
# 5604 m.1/2-b METNİNDE yalnız "GECİKME FAİZLERİNİN ödeme süresi"
# ismen geçer ("gecikme zammı" bu fıkrada İSİMEN YOKTUR - metne dayalı
# bir varsayım İCAT EDİLMEMİŞTİR). m.1/2-b'nin ödeme süresi fıkra 3'ün
# pause/resume mekanizmasından FARKLI, yalnız son-gün kontrolü + YEDİ
# gün uzatma mekanizmasıdır (m.1/2'nin "yedi gün" ibaresi 2007'den bu
# yana DEĞİŞMEMİŞTİR - yalnız fıkra 6'nın asgari süresi 6661 sayılı
# Kanunla "yedi gün"den "beş gün"e indirilmiştir, fıkra 2 DEĞİL).
# Deadline Calculator V1 yalnız dava açma süresi (fıkra 3) hesaplar.
# Avukatın yazılı teyidi olmadan "gecikme faizi"nin fıkra 3 mekanizmasına
# tabi olup olmadığına, veya "gecikme zammı"nın 5604 kapsamına hiç girip
# girmediğine dair bir varsayım YAPILMAZ - tax_type bunlardan biriyse
# sonuç fail-closed needs_review'dır (bkz. ui/tests/test_deadline_
# calculator_mali_tatil_isolated.py, "2c) INDEPENDENT REVIEW
# REMEDIATION - gecikme" bölümü).
MALI_TATIL_INCLUDED_TAX_TYPES = frozenset(
    {
        "katma değer vergisi",
        "kdv",
        "kurumlar vergisi",
        "gelir vergisi",
        "damga vergisi",
        "veraset ve intikal vergisi",
        "motorlu taşıtlar vergisi",
        "mtv",
        "vergi ziyaı cezası",
        "usulsüzlük cezası",
        "özel usulsüzlük cezası",
    }
)

# 5604 m.1/7'nin idare-temelli istisnası (gümrük idareleri, il özel
# idareleri, belediyeler tarafından tarh/tahsil edilen vergi, resim
# ve harçlar) - tax_type adından BAĞIMSIZ, `issuing_authority` serbest
# metninde bu anahtar kelimelerden biri geçerse KESİN istisna sayılır.
# Bu, `case_tax_context`'te issuing_authority MEVCUTSA çalışan, saf
# EK bir dışlama sinyalidir - eksik veya tanınmayan issuing_authority
# TEK BAŞINA needs_review TETİKLEMEZ (yalnız tax_type sınıflandırması
# tetikler).
MALI_TATIL_EXCLUDED_AUTHORITY_KEYWORDS = (
    "gümrük",
    "belediye",
    "il özel idaresi",
    "il özel idare",
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
    ise) `half_day` tatillerinin BİRLEŞİMİDİR.

    PHASE A (REV4.1 kanıt kapanışı, additive): dönüş artık ÜÇÜNCÜ bir
    küme - `half_day_only_dates` - taşır: yalnız `half_day_policy ==
    'needs_review_if_deadline_day'` iken, ve yalnız GERÇEKTEN sadece
    half_day kalan (full_day'e hiç dönüşmeyen) tarihler için doldurulur
    - diğer üç politika değerinde bu küme HER ZAMAN boş kalır (davranış
    byte/semantic olarak değişmez). Her `holiday` girdisinin EFEKTİF
    `day_type`'ı artık observances[]-farkındadır: `observances` alanı
    doluysa (Phase B'den önce production'da HİÇBİR zaman dolu
    DEĞİLDİR) `full_day` varsa `full_day`, yoksa `half_day` olarak
    türetilir (REV4.1'in "full_day kazanır" collision-merge kuralı);
    `observances` yoksa (bugünkü TEK gerçek durum) düz `day_type`
    alanı KULLANILIR - davranış bugün bayt-bayt aynı kalır."""

    half_day_policy = calendar_document.get(
        "half_day_policy"
    )

    covered_verified_years = set()

    holiday_dates = set()

    half_day_only_dates = set()

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

            observances = holiday.get(
                "observances"
            )

            if observances:

                observance_day_types = {
                    observance.get("day_type")
                    for observance in observances
                    if isinstance(observance, dict)
                }

                effective_day_type = (
                    "full_day"
                    if "full_day" in observance_day_types
                    else "half_day"
                )

            else:

                effective_day_type = holiday.get(
                    "day_type"
                )

            counts_as_holiday = (
                effective_day_type
                == "full_day"

                or
                (
                    effective_day_type
                    == "half_day"
                    and half_day_policy
                    == "counts_as_holiday"
                )
            )

            parsed = parse_iso_date(
                holiday.get(
                    "date"
                )
            )

            if counts_as_holiday:

                if parsed is not None:

                    holiday_dates.add(
                        parsed
                    )

            elif (
                effective_day_type
                == "half_day"
                and half_day_policy
                == "needs_review_if_deadline_day"
            ):

                if parsed is not None:

                    half_day_only_dates.add(
                        parsed
                    )

    return {
        "holiday_dates":
            holiday_dates,

        "covered_verified_years":
            covered_verified_years,

        "half_day_only_dates":
            half_day_only_dates,
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

        "half_day_only_dates":
            derived[
                "half_day_only_dates"
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
# MALİ TATİL (5604 sayılı Kanun m.1) - PILOT READINESS ADIM 7
# ============================================================

def rule_has_mali_tatil_basis(
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
        MALI_TATIL_TRIGGER_REF
        in refs
    )


def _normalize_mali_tatil_text(
    value,
):
    """BAĞIMSIZ İNCELEME REMEDİASYONU (Unicode fail-open düzeltmesi).

    Bu, YALNIZ mali tatil tax_type/issuing_authority eşleştirmesi için
    kullanılan DAR bir normalizasyondur - `deadline_rule_selection_
    policy.normalize_string()` (repo genelinde BAŞKA tüketicileri olan
    paylaşılan fonksiyon - kural SEÇİMİNİN kendi tax_type filtresi gibi)
    BİLİNÇLİ olarak DEĞİŞTİRİLMEMİŞTİR ve BURADA KULLANILMAMIŞTIR.

    SORUN: Python'un standart `str.casefold()`'u Türkçe büyük "İ"yi
    (U+0130) TEK bir küçük "i" harfine DEĞİL, "i" (U+0069) + COMBINING
    DOT ABOVE (U+0307) İKİLİSİNE katlar (Unicode SpecialCasing.txt'nin
    tanımladığı, dile-duyarsız "full casefold" davranışı). Bu, plain
    `.casefold()` ile normalize edilmiş "İl Özel İdaresi" gibi bir
    metnin, aynı kelimenin düz-"i" ile yazılmış alias/keyword'üne
    (`"il özel idaresi"`) ASLA eşleşmemesine yol açar - sessiz bir
    fail-open riski (istisna KAÇIRILABİLİR).

    ÇÖZÜM: Unicode NFC normalizasyonu + casefold, ardından SADECE bu
    ikili diziyi ("i\\u0307") kanonik düz "i"ye eşitleyen DAR bir
    `.replace()`. BAŞKA HİÇBİR combining mark silinmez - ö/ü/ş/ç/ğ gibi
    Türkçe karakterler ASCII'ye dönüştürülMEZ, yalnız bu TEK, belgelenmiş
    İ-katlama dizisi düzeltilir.

    DAR GARANTİ (mutlak/genel idempotence İDDİA EDİLMEZ): NFC ve
    `.casefold()` HER İKİSİ de Unicode standardının kendi tanımı gereği
    tek başlarına idempotenttir (NFC(NFC(x))=NFC(x),
    casefold(casefold(x))=casefold(x)); bu fonksiyonun kendi çıktısını
    (yalnız "İ"nin (U+0130) katlanmasından kaynaklanan "i\\u0307"
    dizileri - EMPİRİK olarak doğrulanan TEK bilinen kaynak - temizlenmiş
    metin) tekrar bu fonksiyona vermek güvenlidir ve aynı sonucu üretir.
    Bu, Unicode'da "İ" DIŞINDA HİÇBİR codepoint'in casefold altında
    "i\\u0307" üretemeyeceğinin KAPSAMLI/BAĞIMSIZ bir kanıtı DEĞİLDİR -
    yalnız BU fonksiyonun kendi, tek geçişlik davranışının kararlı
    olduğu iddia edilir."""

    if value is None:

        return None

    text = str(
        value
    ).strip()

    if not text:

        return None

    text = unicodedata.normalize(
        "NFC",
        text,
    ).casefold()

    text = text.replace(
        "i̇",
        "i",
    )

    return (
        text
        if text
        else None
    )


def get_case_issuing_authorities(
    case_data,
):
    """`administrativeAction[*].issuing_authority` serbest metin
    alanlarını toplar, `_normalize_mali_tatil_text()` ile normalize
    eder (BAĞIMSIZ İNCELEME REMEDİASYONU - önceden genel `normalize_
    string()` kullanıyordu, Unicode "İ" fail-open riski taşıyordu; bkz.
    `_normalize_mali_tatil_text()` docstring'i). Bu fonksiyon
    `deadline_rule_selection_policy.py`'ye DEĞİL bu modüle aittir -
    rule SELECTION'ın applicability filtresi issuing_authority'yi
    kullanmaz, yalnız mali tatil m.1/7 istisna kontrolü kullanır."""

    result = set()

    for action in case_data.get(
        "administrative_actions",
        [],
    ):

        if not isinstance(
            action,
            dict,
        ):

            continue

        normalized = _normalize_mali_tatil_text(
            action.get(
                "issuing_authority"
            )
        )

        if normalized:

            result.add(
                normalized
            )

    return result


def get_case_tax_types_for_mali_tatil(
    case_data,
):
    """BAĞIMSIZ İNCELEME REMEDİASYONU: `deadline_rule_selection_
    policy.get_case_tax_types()`'i (repo genelinde kural SEÇİMİ için de
    kullanılan, paylaşılan fonksiyon - genel `normalize_string()`
    kullanır, DEĞİŞTİRİLMEMİŞTİR) YENİDEN KULLANMAZ. Bunun yerine
    `dispute_items[*].tax_type`'ı HAM olarak okur ve yalnız
    `_normalize_mali_tatil_text()` (İ-güvenli, dar normalizasyon)
    uygular - bu, mali tatil sınıflandırmasının paylaşılan fonksiyonun
    Unicode fail-open riskinden TAMAMEN bağımsız kalmasını sağlar."""

    result = set()

    for item in case_data.get(
        "dispute_items",
        [],
    ):

        if not isinstance(
            item,
            dict,
        ):

            continue

        normalized = _normalize_mali_tatil_text(
            item.get(
                "tax_type"
            )
        )

        if normalized:

            result.add(
                normalized
            )

    return result


def classify_mali_tatil_tax_type(
    tax_types,
):
    """Dönüş: (sınıf, eşleşen_deger). sınıf ∈ {"excluded", "included",
    "mixed", "unrecognized"}. Serbest metinden sessiz tahmin YAPILMAZ -
    dar, doğrulanmış iki alias kümesine (`MALI_TATIL_EXCLUDED_TAX_
    TYPES`/`MALI_TATIL_INCLUDED_TAX_TYPES`) karşı EXACT eşleşme
    aranır. Boş girdi veya bilinmeyen HERHANGİ bir tax_type
    "unrecognized" sayılır (öncelikli kontrol - fail-closed).
    Hem excluded hem included eşleşmesi varsa (case birden fazla
    dispute_item'a sahipse ve bunlar karışıksa) "mixed" döner -
    hangi somut dispute'un bu anchor'a ait olduğu belirsiz olduğundan
    tek bir kesin karar VERİLEMEZ.

    BAĞIMSIZ İNCELEME REMEDİASYONU: hem gelen değerler hem de alias
    kümelerinin KENDİSİ `_normalize_mali_tatil_text()`'ten geçirilir -
    girdi ÖNCEDEN normalize edilmiş olsa bile (idempotent) veya HİÇ
    normalize edilmemiş ham bir değer olsa bile (ör. büyük "İ" içeren
    bir tax_type) aynı, doğru sonucu üretir."""

    excluded_alias = {
        _normalize_mali_tatil_text(value)
        for value in MALI_TATIL_EXCLUDED_TAX_TYPES
    }

    included_alias = {
        _normalize_mali_tatil_text(value)
        for value in MALI_TATIL_INCLUDED_TAX_TYPES
    }

    normalized = {
        _normalize_mali_tatil_text(value)
        for value in (
            tax_types
            or set()
        )
        if _normalize_mali_tatil_text(
            value
        )
    }

    if not normalized:

        return (
            "unrecognized",
            None,
        )

    excluded_matches = (
        normalized
        & excluded_alias
    )

    included_matches = (
        normalized
        & included_alias
    )

    unrecognized_matches = (
        normalized
        - excluded_alias
        - included_alias
    )

    if unrecognized_matches:

        return (
            "unrecognized",
            sorted(
                unrecognized_matches
            )[0],
        )

    if (
        excluded_matches
        and included_matches
    ):

        return (
            "mixed",
            None,
        )

    if excluded_matches:

        return (
            "excluded",
            sorted(
                excluded_matches
            )[0],
        )

    return (
        "included",
        None,
    )


def classify_mali_tatil_authority(
    issuing_authorities,
):
    """Dönüş: (sınıf, eşleşen_anahtar_kelime). sınıf ∈ {"excluded",
    "not_excluded"}. Bu kontrol PURE EK bir dışlama sinyalidir -
    issuing_authority eksik veya tanınmayan bir metinse "not_excluded"
    döner (BLOKE ETMEZ); yalnız gümrük/belediye/il özel idaresi
    anahtar kelimelerinden biri AÇIKÇA geçerse "excluded" döner.

    BAĞIMSIZ İNCELEME REMEDİASYONU: hem gelen değerler hem de anahtar
    kelimelerin KENDİSİ `_normalize_mali_tatil_text()`'ten geçirilir -
    "Ankara İl Özel İdaresi" (büyük "İ") artık "il özel idaresi"
    anahtar kelimesiyle DOĞRU eşleşir (önceden plain `.casefold()`'un
    "İ"yi "i"+COMBINING DOT ABOVE'a katlaması nedeniyle SESSİZCE
    KAÇIRILIYORDU - bkz. `_normalize_mali_tatil_text()` docstring'i)."""

    excluded_keywords = {
        _normalize_mali_tatil_text(keyword)
        for keyword in MALI_TATIL_EXCLUDED_AUTHORITY_KEYWORDS
    }

    normalized = {
        _normalize_mali_tatil_text(value)
        for value in (
            issuing_authorities
            or set()
        )
        if _normalize_mali_tatil_text(
            value
        )
    }

    for authority in sorted(
        normalized
    ):

        for keyword in sorted(
            excluded_keywords
        ):

            if (
                keyword
                in authority
            ):

                return (
                    "excluded",
                    keyword,
                )

    return (
        "not_excluded",
        None,
    )


def mali_tatil_window_for_year(
    year,
    holiday_dates,
):
    """5604 m.1/1: mali tatil normalde 1-20 Temmuz (20'si dahil).
    Haziran'ın son gününün tatil günü (hafta sonu VEYA resmî tatil)
    olması halinde başlangıç, temmuz ayının ilk iş gününü TAKİP EDEN
    güne kayar - bitiş tarihi (20 Temmuz) DEĞİŞMEZ."""

    end = date(
        year,
        7,
        20,
    )

    june_30 = date(
        year,
        6,
        30,
    )

    if is_non_working_day(
        june_30,
        holiday_dates,
    ):

        first_business_day_july = (
            move_to_next_business_day(
                date(
                    year,
                    7,
                    1,
                ),
                holiday_dates,
            )
        )

        start = (
            first_business_day_july
            + timedelta(
                days=1
            )
        )

    else:

        start = date(
            year,
            7,
            1,
        )

    return (
        start,
        end,
    )


def is_within_mali_tatil(
    target_date,
    holiday_dates,
):

    start, end = (
        mali_tatil_window_for_year(
            target_date.year,
            holiday_dates,
        )
    )

    return (
        start
        <= target_date
        <= end
    )


def is_mali_tatil_relevant(
    anchor,
    duration_value,
    holiday_dates,
):
    """Ucuz ön-kontrol: [anchor+1, anchor+duration_value] (naif, mali
    tatilsiz sayım penceresi) HERHANGİ bir yılın mali tatil aralığına
    dokunuyor mu? Dokunmuyorsa mali tatil TAMAMEN moot'tur - tax_type/
    issuing_authority sınıflandırması hiç ÇALIŞTIRILMAZ (davranış bu
    fonksiyonun EKLENMESİNDEN ÖNCEki ile bayt-bayt aynı kalır)."""

    naive_end = (
        anchor
        + timedelta(
            days=duration_value
        )
    )

    window_first_day = (
        anchor
        + timedelta(
            days=1
        )
    )

    for year in range(
        anchor.year,
        naive_end.year
        + 1,
    ):

        start, end = (
            mali_tatil_window_for_year(
                year,
                holiday_dates,
            )
        )

        if (
            start
            <= naive_end
            and end
            >= window_first_day
        ):

            return True

    return False


def apply_mali_tatil_pause_resume(
    anchor,
    duration_value,
    holiday_dates,
):
    """5604 m.1/3 (pause/resume) + m.1/6 (asgari beş günlük süre,
    6661 sayılı Kanun m.18 ile güncellenmiş). Gün gün sayar; mali
    tatile denk gelen HER gün sayıma dahil EDİLMEZ (atlanır). Sayım
    tamamlandıktan sonra, eğer sayım herhangi bir mali tatili
    GERÇEKTEN geçtiyse ve ham sonuç o mali tatilin bitimini izleyen
    ilk 5 gün içine denk geliyorsa, sonuç mali tatilin bitimini
    izleyen 5. güne (dahil) sabitlenir.

    Dönüş: (resumed_date, grace_floor_applied). `grace_floor_applied`
    - HUKUK GÖRÜŞÜ REMEDİASYONU (Pilot Readiness Adım 7 final tur) -
    m.1/6'nın asgari-süre kuralının HAM sonucu GERÇEKTEN değiştirip
    değiştirmediğini çağırana bildirir. `calculate_rule_deadline()`
    bunu, `judicial_recess_applicable=False` iken nihai tarihin YALNIZ
    bu asgari-süre mekanizmasına dayanmasını (adli tatil tarafından
    AYRICA teyit/uzatma olmadan) engellemek için kullanır - avukatın
    dava açma süreleri bakımından bu mekanizmaya ihtiyatla yaklaşılması
    yönündeki görüşü gereği."""

    remaining = duration_value

    current = anchor

    mali_tatil_end_crossed = None

    safety_counter = 0

    while (
        remaining
        > 0
    ):

        safety_counter += 1

        if (
            safety_counter
            > 730
        ):

            raise DeadlineCalculatorError(
                "Mali tatil pause/resume 730 gün "
                "içinde tamamlanamadı."
            )

        current = (
            current
            + timedelta(
                days=1
            )
        )

        if is_within_mali_tatil(
            current,
            holiday_dates,
        ):

            _, year_end = (
                mali_tatil_window_for_year(
                    current.year,
                    holiday_dates,
                )
            )

            mali_tatil_end_crossed = (
                year_end
            )

            continue

        remaining -= 1

    resumed = current

    grace_floor_applied = False

    if (
        mali_tatil_end_crossed
        is not None
    ):

        grace_start = (
            mali_tatil_end_crossed
            + timedelta(
                days=1
            )
        )

        grace_floor = (
            mali_tatil_end_crossed
            + timedelta(
                days=
                    MALI_TATIL_GRACE_PERIOD_DAYS
            )
        )

        if (
            grace_start
            <= resumed
            <= grace_floor
        ):

            resumed = grace_floor

            grace_floor_applied = True

    return (
        resumed,
        grace_floor_applied,
    )


# ============================================================
# PILOT READINESS ADIM 7 / SLICE 1 - STOPPING-EVENT ATTESTATION
#
# DRAFT-4 SORU 8.5(iii) bağlayıcı talimatı: "bu tür bir başvuru/işlem
# yapılmış dosyalar mevcut sürümde kapsam dışı bırakılmalı. İşletmeci
# hukuki etkiyi KENDİSİ YORUMLAMAMALI; avukat 'bu olay süreyi
# etkilemez' diye ayrıca YAZILI karar vermedikçe işlemeyi durdurmalı."
# ve "HAYIR -> pilot devam edebilir. EVET / BİLİNMİYOR -> pilot durur;
# son gün üretilmez ve avukat incelemesi gerekir."
#
# Bu blok TAM OLARAK bunu uygular ve BAŞKA HİÇBİR ŞEY yapmaz: hiçbir
# hukuki süre aritmetiği (uzlaşmanın 15 günü, İYUK m.11'in kalan
# süresi, VUK m.35/376'nın yeni başlangıcı) BU SLICE'TA modellenmez -
# kapı yalnız DURDURUR.
#
# DAR, EXACT İDDİA (abartılmaz): aşağıdaki case.json çapraz kontrolü
# bir DEDEKTÖR DEĞİLDİR. Yalnız case modelinin ifade edebildiği İKİ
# kategoriyi (`settlement`, `correction_complaint`) görür. VUK m.35
# (VİR/VTR eklenmemesi), usulsüz tebligat, VUK m.376, pişmanlık
# ihlali, takdir komisyonu eksikliği ve genel İYUK m.11 başvurusunun
# `action_category`'de HİÇBİR karşılığı YOKTUR; bu altı hâl tamamen
# avukatın `none` beyanına dayanır.
# ============================================================

STOPPING_EVENT_STATUS_NONE = "none"
STOPPING_EVENT_STATUS_PRESENT = "present"
STOPPING_EVENT_STATUS_UNKNOWN = "unknown"

STOPPING_EVENT_STATUS_VALUES = (
    STOPPING_EVENT_STATUS_NONE,
    STOPPING_EVENT_STATUS_PRESENT,
    STOPPING_EVENT_STATUS_UNKNOWN,
)

# Sabit `reason`/notes literalleri - testler bunları PİNLER.
STOPPING_EVENT_REASON_UNKNOWN = (
    "stopping_event_status_unknown"
)

STOPPING_EVENT_REASON_PRESENT = (
    "stopping_event_present_requires_lawyer_review"
)

STOPPING_EVENT_REASON_MISSING_REF = (
    "stopping_event_none_requires_attestation_ref"
)

STOPPING_EVENT_REASON_CONFLICT = (
    "stopping_event_attestation_conflicts_with_case_record"
)

# Çapraz kontrolün gördüğü TEK iki kategori (DAR - bkz. yukarıdaki
# disclosure). `audit`/`assessment` gibi diğer kategoriler ASLA
# engelleme üretmez.
STOPPING_EVENT_CONFLICT_ACTION_CATEGORIES = frozenset(
    {
        "settlement",
        "correction_complaint",
    }
)

STOPPING_EVENT_ATTESTATION_REF_MIN_LENGTH = 1
STOPPING_EVENT_ATTESTATION_REF_MAX_LENGTH = 200


def normalize_stopping_event_status(
    value,
):
    """Fail-closed normalizasyon. `None` (parametre hiç verilmedi) VE
    tanınmayan/boş/non-str her değer `unknown`'a düşer - default ASLA
    `none` DEĞİLDİR. Ham değer DEĞİŞTİRİLMEZ, yalnız sınıflandırılır."""

    if not isinstance(
        value,
        str,
    ):

        return STOPPING_EVENT_STATUS_UNKNOWN

    if (
        value
        in STOPPING_EVENT_STATUS_VALUES
    ):

        return value

    return STOPPING_EVENT_STATUS_UNKNOWN


def is_valid_stopping_event_attestation_ref(
    value,
):
    """YALNIZ ŞEKİL doğrulaması - ref'in GERÇEKLİĞİ veya avukatın
    gerçekten böyle bir beyan verdiği DOĞRULANMAZ. Sözleşme: `str`
    olacak, `strip()` sonrası boş olmayacak, 1-200 karakter, TAMAMEN
    printable (CR/LF/tab/kontrol karakteri YASAK). Non-str girdi
    exception ÜRETMEZ, yalnız `False` döner (fail-closed)."""

    if not isinstance(
        value,
        str,
    ):

        return False

    if not value.strip():

        return False

    if (
        len(
            value
        )
        < STOPPING_EVENT_ATTESTATION_REF_MIN_LENGTH
        or len(
            value
        )
        > STOPPING_EVENT_ATTESTATION_REF_MAX_LENGTH
    ):

        return False

    # `str.isprintable()` newline/CR/tab ve tüm kontrol karakterleri
    # için False döner; ayrıca açık bir CR/LF kontrolü savunma amaçlı
    # tekrarlanır.
    if not value.isprintable():

        return False

    if (
        "\r" in value
        or "\n" in value
    ):

        return False

    return True


def case_has_stopping_event_signal(
    case_data,
):
    """`administrative_actions[*].action_category`'nin YALNIZ iki
    değerini görür (bkz. modül içi disclosure). Beklenmeyen/eksik
    yapıda sessizce False döner - bu bir DEDEKTÖR değil, `none`
    beyanıyla ÇELİŞKİ arayan dar bir kontroldür."""

    if not isinstance(
        case_data,
        dict,
    ):

        return False

    actions = case_data.get(
        "administrative_actions",
    )

    if not isinstance(
        actions,
        list,
    ):

        return False

    for action in actions:

        if not isinstance(
            action,
            dict,
        ):

            continue

        category = action.get(
            "action_category"
        )

        if (
            isinstance(
                category,
                str,
            )
            and category
            in STOPPING_EVENT_CONFLICT_ACTION_CATEGORIES
        ):

            return True

    return False


def evaluate_stopping_event_gate(
    stopping_event_status,
    stopping_event_attestation_ref,
    case_data,
):
    """Saf, I/O'suz karar fonksiyonu. Dönüş: `None` -> hesaplamaya
    DEVAM; aksi halde sabit `reason` literali (string) -> ENGELLE.

    Karar sırası fail-closed'dır: önce status sınıflandırılır (None/
    tanınmayan -> unknown), sonra `none` için ref şekli, EN SON
    case.json çelişkisi bakılır."""

    status = normalize_stopping_event_status(
        stopping_event_status
    )

    if (
        status
        == STOPPING_EVENT_STATUS_PRESENT
    ):

        return STOPPING_EVENT_REASON_PRESENT

    if (
        status
        != STOPPING_EVENT_STATUS_NONE
    ):

        return STOPPING_EVENT_REASON_UNKNOWN

    if not is_valid_stopping_event_attestation_ref(
        stopping_event_attestation_ref
    ):

        return STOPPING_EVENT_REASON_MISSING_REF

    if case_has_stopping_event_signal(
        case_data
    ):

        return STOPPING_EVENT_REASON_CONFLICT

    return None


def canonical_stopping_event_fields(
    stopping_event_status,
    stopping_event_attestation_ref,
):
    """ADIM 7 / SLICE 2. Bir deadline kaydına YAZILACAK iki canonical
    alanı üretir. SAF, I/O'suz; yalnız mevcut iki fail-closed
    primitive'i (`normalize_stopping_event_status`,
    `is_valid_stopping_event_attestation_ref`) YENİDEN KULLANIR -
    normalizasyon mantığı KOPYALANMAZ.

    Sözleşme:

    - `stopping_event_status` HER ZAMAN üç enum değerinden biridir;
      `None` (parametre hiç verilmedi) ve tanınmayan/non-str her değer
      `unknown`'a düşer - default ASLA `none` DEĞİLDİR.
    - `stopping_event_attestation_ref` YALNIZ şekil olarak geçerliyse
      VERBATIM (strip/normalize EDİLMEDEN) yazılır; aksi halde `None`.
      Bu, status'tan BAĞIMSIZDIR: avukat `present`/`unknown` beyanıyla
      birlikte de geçerli bir referans verebilir ve onu sessizce
      silmek, gerçekten verilmiş bir beyanı yok etmek olurdu.
    - Non-str/geçersiz ham girdi canonical'a ASLA sızmaz (ve exception
      da ÜRETMEZ - her iki primitive de fail-closed'dır); ham değer
      yalnız generation audit'te verbatim saklanır.

    Bu fonksiyonun çıktısı `build_deadline_record()`'un DÖRT erken
    dönüşünde ve normal hesaplama yolunda AYNI şekilde kullanılır, yani
    iki anahtar ÜRETİLEN HER kayıtta fiziksel olarak bulunur."""

    normalized_status = (
        normalize_stopping_event_status(
            stopping_event_status
        )
    )

    if is_valid_stopping_event_attestation_ref(
        stopping_event_attestation_ref
    ):

        normalized_ref = (
            stopping_event_attestation_ref
        )

    else:

        normalized_ref = None

    return (
        normalized_status,
        normalized_ref,
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
    case_tax_context=None,
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
    ÖNCE karar verilir).

    PILOT READINESS ADIM 7: `case_tax_context` (opsiyonel,
    `{"tax_types": set(str), "issuing_authorities": set(str)}` -
    HER İKİSİ de ideal olarak `_normalize_mali_tatil_text()` ile
    normalize edilmiş olmalıdır, ama `classify_mali_tatil_tax_type()`/
    `classify_mali_tatil_authority()` girdiyi HER DURUMDA yeniden
    normalize eder - bağımsız inceleme remediasyonu, idempotent ve
    savunmacı) yalnız kural `rule_has_mali_tatil_basis()` İSE ve sayım
    penceresi GERÇEKTEN mali tatile dokunuyorsa tüketilir; aksi halde
    tamamen moot'tur ve davranış bu parametrenin EKLENMESİNDEN ÖNCEki
    ile bayt-bayt aynı kalır."""

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

    mali_tatil_applied = False

    mali_tatil_exclusion_reason = None

    # PILOT READINESS ADIM 7 (§7.1): `holidays`/`covered_verified_
    # years` burada, mali tatil bölümünden ÖNCE hesaplanır (m.1/1'in
    # başlangıç-kayması edge case'i için gerekir); aşağıdaki END DAY
    # POLICY bölümü bu AYNI değişkenleri yeniden kullanır, ikinci kez
    # HESAPLAMAZ.

    effective_holiday_calendar = (
        holiday_calendar
        if holiday_calendar is not None
        else {
            "holiday_dates": set(),
            "covered_verified_years": set(),
            "half_day_only_dates": set(),
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

    half_day_only_dates = normalize_holiday_dates(
        effective_holiday_calendar.get(
            "half_day_only_dates"
        )
        or set()
    )

    # ========================================================
    # MALİ TATİL (5604 sayılı Kanun m.1) - PILOT READINESS ADIM 7
    # ========================================================

    if rule_has_mali_tatil_basis(
        rule
    ):

        if is_mali_tatil_relevant(
            anchor,
            duration_value,
            holidays,
        ):

            tax_class, tax_match = (
                classify_mali_tatil_tax_type(
                    (
                        case_tax_context
                        or {}
                    ).get(
                        "tax_types"
                    )
                )
            )

            authority_class, authority_match = (
                classify_mali_tatil_authority(
                    (
                        case_tax_context
                        or {}
                    ).get(
                        "issuing_authorities"
                    )
                )
            )

            if (
                authority_class
                == "excluded"
            ):

                mali_tatil_exclusion_reason = (
                    "issuing_authority_excluded:"
                    f"{authority_match}"
                )

            elif (
                tax_class
                == "excluded"
            ):

                mali_tatil_exclusion_reason = (
                    "tax_type_excluded:"
                    f"{tax_match}"
                )

            elif tax_class in (
                "unrecognized",
                "mixed",
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

                    "mali_tatil_applied":
                        False,

                    "mali_tatil_exclusion_reason":
                        None,

                    "reason":
                        (
                            "Base deadline mali tatile denk "
                            "gelen bir sayım penceresi "
                            "içeriyor ancak case vergi türü "
                            "5604 m.1/7 istisnası bakımından "
                            "güvenilir şekilde "
                            "sınıflandırılamadı "
                            f"(tax_classification={tax_class})."
                        ),
                }

            else:

                # tax_class == "included" ve issuing_authority
                # istisna kapsamında değil -> mali tatil UYGULANIR.

                provisional_deadline, grace_floor_applied = (
                    apply_mali_tatil_pause_resume(
                        anchor,
                        duration_value,
                        holidays,
                    )
                )

                mali_tatil_applied = True

                # ================================================
                # HUKUK GÖRÜŞÜ REMEDİASYONU (Pilot Readiness Adım 7
                # final tur): m.1/6'nın asgari 5 günlük süresi
                # (6661 sayılı Kanunla güncellenmiş) HAM sonucu
                # GERÇEKTEN değiştirdiyse (`grace_floor_applied`) VE
                # judicial_recess_applicable AÇIKÇA False ise, nihai
                # tarihin YALNIZ bu asgari-süre mekanizmasına
                # dayanmasına İZİN VERİLMEZ - avukatın dava açma
                # süreleri (çalışmaya ara vermeyen mahkemeler dahil)
                # bakımından bu mekanizmaya ihtiyatla yaklaşılması
                # gerektiği yönündeki görüşü gereği, fail-closed
                # needs_review döner. `judicial_recess_applicable`
                # True veya None ise BU KONTROL ÇALIŞMAZ - True
                # durumunda adli tatil zaten bağımsız olarak nihai
                # tarihi daha ileri taşıyabilir (aşağıdaki İYUK
                # JUDICIAL RECESS bölümü); None durumunda ZATEN
                # mevcut resess-ambiguity kontrolü devreye girer
                # (floor'un ürettiği tarih HER ZAMAN İYUK çalışmaya
                # ara verme aralığının içindedir, bu yüzden None her
                # durumda o bölümde needs_review'a düşer - burada
                # AYRICA ele almaya gerek yoktur).
                # ================================================

                if (
                    grace_floor_applied
                    and judicial_recess_applicable
                    is False
                ):

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
                            False,

                        "holiday_adjustment_applied":
                            False,

                        "mali_tatil_applied":
                            True,

                        "mali_tatil_exclusion_reason":
                            None,

                        "reason":
                            (
                                "5604 m.1/6 asgari beş günlük süre "
                                "kuralı (6661 sayılı Kanunla "
                                "güncellenmiş) nihai tarihi TEK "
                                "BAŞINA belirliyor ve "
                                "judicial_recess_applicable=False "
                                "olarak beyan edilmiş (adli tatil "
                                "tarafından ayrıca teyit/uzatma "
                                "yok). Avukat teyidi olmadan dava "
                                "açma süreleri bakımından bu "
                                "mekanizmaya dayanarak kesin tarih "
                                "üretilmiyor - "
                                "reason_code=mali_tatil_grace_"
                                "floor_unconfirmed_without_recess."
                            ),
                    }

        else:

            mali_tatil_exclusion_reason = (
                "window_not_relevant"
            )

    else:

        mali_tatil_exclusion_reason = (
            "rule_lacks_legal_basis"
        )

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

                "mali_tatil_applied":
                    mali_tatil_applied,

                "mali_tatil_exclusion_reason":
                    mali_tatil_exclusion_reason,

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

    # `effective_holiday_calendar`/`holidays`/`covered_verified_years`
    # PILOT READINESS ADIM 7 ile MALİ TATİL bölümünden önceye taşındı
    # (m.1/1'in başlangıç-kayması edge case'i için gerekiyordu) - burada
    # AYNI değişkenler yeniden kullanılır, ikinci kez hesaplanmaz.

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

                "mali_tatil_applied":
                    mali_tatil_applied,

                "mali_tatil_exclusion_reason":
                    mali_tatil_exclusion_reason,

                "reason":
                    (
                        "end_day_policy="
                        "'next_business_day_if_holiday' ancak "
                        "şu yıl(lar) resmi tatil takviminde "
                        "'verified' olarak işaretlenmemiş: "
                        f"{uncovered_years}."
                    ),
            }

        # PILOT READINESS ADIM 5 PHASE A (REV4.1 kanıt kapanışı):
        # half_day_policy == "needs_review_if_deadline_day" iken,
        # final_deadline GERÇEKTEN yalnız-half-day bir tarihe denk
        # gelirse fail-closed needs_review döner. full_day (veya
        # full_day+half_day collision - "full_day kazanır" kuralı)
        # tarihleri zaten YUKARIDA holiday_dates'e girip kaydırılmış
        # olduğundan final_deadline ORADA asla kalmaz - bu blok yalnız
        # GERÇEKTEN yalnız-half-day kalan tarihler için tetiklenir.
        # Diğer üç half_day_policy değerinde half_day_only_dates HER
        # ZAMAN boştur (derive_effective_holiday_calendar'ın kendi
        # kuralı) - bu yüzden bu blok o üç politikada davranışı
        # byte/semantic olarak DEĞİŞTİRMEZ. Yalnız
        # end_day_policy=='next_business_day_if_holiday' dalına
        # sınırlıdır - bugün aktif TEK deadline_rule bu değeri
        # kullanıyor (data/deadline_rules/deadline_rules.json).

        if final_deadline in half_day_only_dates:

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

                "mali_tatil_applied":
                    mali_tatil_applied,

                "mali_tatil_exclusion_reason":
                    mali_tatil_exclusion_reason,

                "reason":
                    "holiday_calendar_half_day_deadline_requires_review",
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

            "mali_tatil_applied":
                mali_tatil_applied,

            "mali_tatil_exclusion_reason":
                mali_tatil_exclusion_reason,

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

        "mali_tatil_applied":
            mali_tatil_applied,

        "mali_tatil_exclusion_reason":
            mali_tatil_exclusion_reason,

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
    stopping_event_status=None,
    stopping_event_attestation_ref=None,
):

    # ADIM 7 / SLICE 2: canonical'a yazılacak iki alan EN BAŞTA, her
    # erken dönüşten ÖNCE normalize edilir; böylece bu fonksiyonun
    # ÜRETTİĞİ HER kayıtta (rule çözülemedi / blocked_unverified_anchor
    # / date_precision / selection / legal-basis / stopping-gate /
    # normal hesap) iki anahtar da FİZİKSEL olarak bulunur.
    (
        canonical_stopping_event_status,
        canonical_stopping_event_attestation_ref,
    ) = canonical_stopping_event_fields(
        stopping_event_status,
        stopping_event_attestation_ref,
    )

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

            # ADIM 7 / SLICE 2 - bu dal stopping-event kapısına HİÇ
            # ULAŞMAZ (rule çözülemedi), ama avukatın BEYANI yine de
            # kayda geçer. Çelişki çapraz-kontrolü bu dalda
            # DEĞERLENDİRİLMEMİŞTİR.
            "stopping_event_status":
                canonical_stopping_event_status,

            "stopping_event_attestation_ref":
                canonical_stopping_event_attestation_ref,
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

        # ADIM 7 / SLICE 2 - `base_record`'a EN BAŞTA konur, böylece
        # bundan sonraki BEŞ erken dönüşün (unverified anchor,
        # date_precision, selection, legal-basis, stopping-gate) ve
        # normal hesap yolunun HEPSİ iki anahtarı taşır. Sonraki
        # `base_record.update(...)` çağrılarının hiçbiri bu iki alana
        # DOKUNMAZ.
        "stopping_event_status":
            canonical_stopping_event_status,

        "stopping_event_attestation_ref":
            canonical_stopping_event_attestation_ref,
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
    # PILOT READINESS ADIM 7 / SLICE 1 - STOPPING-EVENT GATE
    #
    # Konum SÖZLEŞMESİ: `blocked_unverified_anchor` kontrolünden
    # SONRA (satır ~2701 - bu yüzden doğrulanmamış anchor bu kapıya
    # HİÇ ULAŞMAZ ve davranışı DEĞİŞMEZ), `calculate_rule_deadline()`
    # çağrısından ÖNCE. Kapı `calculate_rule_deadline()`'ın İÇİNE
    # KONMAZ - o fonksiyon saf tarih aritmetiği olarak kalır.
    #
    # case.json YALNIZ gerçekten gerekliyse (status=none VE ref şekil
    # olarak geçerli) yüklenir - `present`/`unknown`/geçersiz-ref
    # dallarında SIFIR ek I/O olur.
    # ========================================================

    stopping_gate_case_data = None

    if (
        normalize_stopping_event_status(
            stopping_event_status
        )
        == STOPPING_EVENT_STATUS_NONE
        and is_valid_stopping_event_attestation_ref(
            stopping_event_attestation_ref
        )
    ):

        stopping_gate_case_data, _ = load_case(
            case_id
        )

    stopping_block_reason = (
        evaluate_stopping_event_gate(
            stopping_event_status,
            stopping_event_attestation_ref,
            stopping_gate_case_data,
        )
    )

    if (
        stopping_block_reason
        is not None
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
                    stopping_block_reason,
            }
        )

        return base_record

    # ========================================================
    # PILOT READINESS ADIM 7 - MALİ TATİL CASE TAX CONTEXT
    #
    # Yalnız kural `rule_has_mali_tatil_basis()` İSE case.json
    # yüklenir (`deadline_validator.load_case()` - `deadline_rule_
    # selection_policy.select_for_case_event()`'in ZATEN kullandığı
    # AYNI, self-contained fonksiyon); aksi halde gereksiz I/O YOK,
    # davranış bu bölümün EKLENMESİNDEN ÖNCEki ile bayt-bayt aynı.
    # SLICE 1: stopping-event kapısı case.json'ı zaten yüklediyse
    # yeniden okunmaz (tek okuma).
    # ========================================================

    case_tax_context = None

    if rule_has_mali_tatil_basis(
        selected_rule
    ):

        case_data = stopping_gate_case_data

        if case_data is None:

            case_data, _ = load_case(
                case_id
            )

        case_tax_context = {
            "tax_types":
                get_case_tax_types_for_mali_tatil(
                    case_data
                ),

            "issuing_authorities":
                get_case_issuing_authorities(
                    case_data
                ),
        }

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

            case_tax_context=
                case_tax_context,
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

    if calculation.get(
        "mali_tatil_applied"
    ):

        notes.append(
            "mali_tatil_adjustment=applied"
        )

    elif (
        calculation.get(
            "mali_tatil_exclusion_reason"
        )
        not in (
            None,
            "window_not_relevant",
            "rule_lacks_legal_basis",
        )
    ):

        # Yalnız ANLAMLI (aktif bir 5604 m.1/7 istisna kararı verilmiş)
        # durumlar notes'a yansıtılır; "window_not_relevant"/"rule_
        # lacks_legal_basis" rutin/varsayılan durumlardır - `calculation`
        # dict'inin KENDİSİNDE (yapısal, sorgulanabilir alanda) HER ZAMAN
        # mevcuttur, insan-okunur notes string'i gereksiz yere
        # kalabalıklaştırılmaz.

        notes.append(
            "mali_tatil="
            + calculation[
                "mali_tatil_exclusion_reason"
            ]
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
    stopping_event_status=None,
    stopping_event_attestation_ref=None,
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

            stopping_event_status=
                stopping_event_status,

            stopping_event_attestation_ref=
                stopping_event_attestation_ref,
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
        == 7
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
    # PILOT READINESS ADIM 7: anchor kasıtlı olarak mali tatil (1-20
    # Temmuz) bitiminden SONRAya ("2026-07-21") taşındı - bu test
    # yalnız İYUK adli tatilini İZOLE test eder; anchor+30 sayım
    # penceresi (22 Temmuz - 20 Ağustos) mali tatile HİÇ dokunmaz
    # (`is_mali_tatil_relevant()` False döner), bu yüzden
    # `case_tax_context` GEREKMEZ. Mali tatil pause/resume'un KENDİSİ
    # T07c+ testlerinde ayrıca test edilir.
    #
    # 21.07 + 30 = 20.08.2026
    # Judicial recess -> 07.09
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-07-21",

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
        == "2026-08-20"
    )

    assert (
        result[
            "mali_tatil_applied"
        ]
        is False
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
    # PILOT READINESS ADIM 7: anchor T05 ile AYNI gerekçeyle
    # "2026-07-21"e taşındı (mali tatilden izole).
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-07-21",

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
    # T07c MALİ TATİL PAUSE/RESUME - PILOT READINESS ADIM 7
    #
    # 15.06.2026 + 30 gün, 1-20 Temmuz (dahil) sayılmaz:
    # 16-30 Haziran = 15 gün, 21 Temmuz'dan itibaren 15 gün daha
    # -> 04.08.2026. Recess kasıtlı olarak False (mali tatilin KENDİ
    # etkisini adli tatilden izole test etmek için); 04.08.2026 hafta
    # içi olduğundan holiday_adjustment_applied=False.
    # ========================================================

    kdv_tax_context = {
        "tax_types": {
            "kdv"
        },

        "issuing_authorities":
            set(),
    }

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-15",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                False,

            case_tax_context=
                kdv_tax_context,
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
        == "2026-08-04"
    )

    assert (
        result[
            "mali_tatil_applied"
        ]
        is True
    )

    print(
        "T07c Mali tatil pause/resume:",
        "PASS"
    )

    # ========================================================
    # T07d MALİ TATİL m.1/6 ASGARİ BEŞ GÜNLÜK SÜRE (6661 sayılı
    # Kanun m.18) - HUKUK GÖRÜŞÜ REMEDİASYONU (Pilot Readiness Adım 7
    # final tur): ham resume tarihi mali tatilin bitimini izleyen ilk
    # 5 gün (21-25 Temmuz) içine denk geliyorsa VE
    # judicial_recess_applicable=False ise (adli tatil tarafından
    # AYRICA teyit/uzatma YOKSA), nihai tarih YALNIZ bu asgari-süre
    # mekanizmasına dayanarak ÜRETİLMEZ - avukatın dava açma süreleri
    # bakımından bu mekanizmaya ihtiyatla yaklaşılması gerektiği
    # yönündeki görüşü gereği fail-closed needs_review döner (ÖNCEKİ
    # davranış - sessizce 27.07.2026'ya calculated - artık YANLIŞTIR
    # ve bu turda düzeltilmiştir).
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-01",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                False,

            case_tax_context=
                kdv_tax_context,
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

    assert (
        result[
            "mali_tatil_applied"
        ]
        is True
    )

    assert (
        "mali_tatil_grace_floor_unconfirmed_without_recess"
        in result[
            "reason"
        ]
    )

    print(
        "T07d Mali tatil m.1/6 five-day grace floor WITHOUT "
        "judicial recess confirmation is fail-closed needs_review:",
        "PASS"
    )

    # ========================================================
    # T07d2 SAME grace-floor scenario, but judicial_recess_
    # applicable=True this time - the floor is NOT the sole
    # determinant anymore (recess independently extends further to
    # the fixed 7 Eylül), so this DOES reach calculated. Proves the
    # T07d fail-closed check is narrowly scoped to recess=False only.
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-01",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                True,

            case_tax_context=
                kdv_tax_context,
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
        == "2026-09-07"
    )

    assert (
        result[
            "judicial_recess_applied"
        ]
        is True
    )

    assert (
        result[
            "mali_tatil_applied"
        ]
        is True
    )

    print(
        "T07d2 Same grace-floor scenario WITH judicial recess "
        "confirmation reaches calculated (recess independently "
        "extends further):",
        "PASS"
    )

    # ========================================================
    # T07d3 HUKUK GÖRÜŞÜ TEST B - mali tatil İÇİNDE fiilî tebliğ
    # (anchor 10 Temmuz, 1-20 Temmuz aralığının içinde) + kapsam içi
    # vergi + judicial_recess_applicable=True: fıkra 5 gereği ilk
    # sayılan gün 21 Temmuz'dur (mali tatil bitimini izleyen gün);
    # sonuç adli tatil aralığına denk geldiğinden adli tatil final
    # tarihi 7 Eylül'e taşır.
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-07-10",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                True,

            case_tax_context=
                kdv_tax_context,
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
        == "2026-09-07"
    )

    assert (
        result[
            "judicial_recess_applied"
        ]
        is True
    )

    assert (
        result[
            "mali_tatil_applied"
        ]
        is True
    )

    print(
        "T07d3 Actual tebliğ inside mali tatil (fıkra 5) + judicial "
        "recess confirmed -> final 7 Eylül:",
        "PASS"
    )

    # ========================================================
    # T07d4 HUKUK GÖRÜŞÜ TEST C - m.1/7 kapsam dışı vergi (ÖTV) +
    # judicial_recess_applicable=True: mali_tatil_applied=False VE
    # judicial_recess_applied=True AYNI kayıtta bir arada mümkündür -
    # mali tatil m.1/7 kapsamı dışında olduğu için hiç uygulanmaz,
    # ama İYUK m.8/3 adli tatili BAĞIMSIZ olarak yine uygulanabilir.
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

            case_tax_context={
                "tax_types": {
                    "ötv"
                },

                "issuing_authorities":
                    set(),
            },
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
        == "2026-09-07"
    )

    assert (
        result[
            "mali_tatil_applied"
        ]
        is False
    )

    assert (
        result[
            "judicial_recess_applied"
        ]
        is True
    )

    print(
        "T07d4 mali_tatil_applied=False and judicial_recess_applied="
        "True coexist in the same record (m.1/7-excluded tax type, "
        "İYUK m.8/3 recess independently applies):",
        "PASS"
    )

    # ========================================================
    # T07d6 HUKUK GÖRÜŞÜ TEST E - adli tatil uygulanabilirliği
    # bilinmiyor (None) VE mali tatil sonucu adli tatil aralığına
    # denk geliyor -> needs_review (mevcut recess-ambiguity kontrolü,
    # DEĞİŞTİRİLMEDİ, yalnız mali-tatil-birleşik senaryoda AYRICA
    # kanıtlanıyor).
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
                None,

            case_tax_context=
                kdv_tax_context,
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
        "T07d6 Unknown judicial recess applicability with a mali-"
        "tatil-relevant result -> needs_review:",
        "PASS"
    )

    # ========================================================
    # T07d8 HUKUK GÖRÜŞÜ TEST F - İYUK m.8/2 kapsamında recess-
    # extended 7 Eylül'ün kendisi resmî tatile/hafta sonuna denk
    # gelirse izleyen ilk çalışma gününe (8 Eylül) kayar - mevcut
    # end_day_policy altyapısı, mali tatil + adli tatil BİRLEŞİK
    # sonucunun ÜZERİNE de değişmeden uygulanmaya devam eder.
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-25",

            rule=
                rule,

            holiday_calendar={
                "holiday_dates": {
                    date(
                        2026,
                        9,
                        7,
                    ),
                },

                "covered_verified_years":
                    {2026},
            },

            judicial_recess_applicable=
                True,

            case_tax_context=
                kdv_tax_context,
        )
    )

    assert (
        result[
            "calculated_deadline"
        ]
        == "2026-09-08"
    )

    assert (
        result[
            "holiday_adjustment_applied"
        ]
        is True
    )

    print(
        "T07d8 7 Eylül itself marked as a holiday, on the combined "
        "mali tatil + adli tatil path, shifts forward to 8 Eylül:",
        "PASS"
    )

    # ========================================================
    # T07e MALİ TATİL m.1/1 BAŞLANGIÇ KAYMASI - 2029'da 30 Haziran
    # Cumartesi'dir; mali tatil normal 1 Temmuz yerine 3 Temmuz'da
    # başlar (20 Temmuz'da biter, bitiş DEĞİŞMEZ).
    # ========================================================

    covered_2029_2030 = {
        "holiday_dates": set(),
        "covered_verified_years":
            {
                2029,
                2030,
            },
    }

    assert (
        mali_tatil_window_for_year(
            2029,
            set(),
        )
        == (
            date(
                2029,
                7,
                3,
            ),
            date(
                2029,
                7,
                20,
            ),
        )
    )

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2029-06-25",

            rule=
                rule,

            holiday_calendar=
                covered_2029_2030,

            judicial_recess_applicable=
                False,

            case_tax_context=
                kdv_tax_context,
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
            "mali_tatil_applied"
        ]
        is True
    )

    print(
        "T07e Mali tatil m.1/1 start-date shift (2029 - 30 June "
        "is a Saturday):",
        "PASS"
    )

    # ========================================================
    # T07f MALİ TATİL m.1/7 - VERGİ TÜRÜNE GÖRE İSTİSNA (ÖTV) - mali
    # tatil UYGULANMAZ, naif takvim-günü hesabı (mali tatilsiz)
    # DEĞİŞMEDEN kullanılır.
    # ========================================================

    otv_tax_context = {
        "tax_types": {
            "ötv"
        },

        "issuing_authorities":
            set(),
    }

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-15",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                False,

            case_tax_context=
                otv_tax_context,
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
        == "2026-07-15"
    )

    assert (
        result[
            "mali_tatil_applied"
        ]
        is False
    )

    assert (
        result[
            "mali_tatil_exclusion_reason"
        ]
        == "tax_type_excluded:ötv"
    )

    print(
        "T07f Mali tatil m.1/7 tax-type exclusion (ÖTV):",
        "PASS"
    )

    # ========================================================
    # T07g MALİ TATİL m.1/7 - İDAREYE GÖRE İSTİSNA (gümrük) -
    # tax_type dahil-listede olsa BİLE issuing_authority istisnası
    # ÖNCELİKLİDİR.
    # ========================================================

    gumruk_tax_context = {
        "tax_types": {
            "kdv"
        },

        "issuing_authorities": {
            "istanbul gümrük ve dış "
            "ticaret bölge müdürlüğü"
        },
    }

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-15",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                False,

            case_tax_context=
                gumruk_tax_context,
        )
    )

    assert (
        result[
            "mali_tatil_applied"
        ]
        is False
    )

    assert (
        result[
            "mali_tatil_exclusion_reason"
        ]
        == "issuing_authority_excluded:gümrük"
    )

    print(
        "T07g Mali tatil m.1/7 authority exclusion (gümrük):",
        "PASS"
    )

    # ========================================================
    # T07h MALİ TATİL BİLİNMEYEN VERGİ TÜRÜ FAIL-CLOSED - sessiz
    # tahmin YOK; needs_review.
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-15",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                False,

            case_tax_context={
                "tax_types": {
                    "bilinmeyen vergi türü xyz"
                },

                "issuing_authorities":
                    set(),
            },
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

    assert (
        result[
            "mali_tatil_applied"
        ]
        is False
    )

    print(
        "T07h Mali tatil unrecognized tax_type fail-closed:",
        "PASS"
    )

    # ========================================================
    # T07i MALİ TATİL case_tax_context HİÇ VERİLMEMİŞ (None) -
    # AYNI şekilde fail-closed needs_review (mevcut değil = tanınmıyor
    # sayılır, otomatik "included" VARSAYILMAZ).
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-15",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

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

    print(
        "T07i Mali tatil missing case_tax_context fail-closed:",
        "PASS"
    )

    # ========================================================
    # T07j MALİ TATİL KARIŞIK (MIXED) VERGİ TÜRÜ FAIL-CLOSED - aynı
    # case'te hem istisna (ÖTV) hem dahil (KDV) tax_type varsa, hangi
    # dispute'un bu anchor'a ait olduğu belirsizdir -> needs_review.
    # ========================================================

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-15",

            rule=
                rule,

            holiday_calendar=
                covered_2026_only,

            judicial_recess_applicable=
                False,

            case_tax_context={
                "tax_types": {
                    "kdv",
                    "ötv",
                },

                "issuing_authorities":
                    set(),
            },
        )
    )

    assert (
        result[
            "calculation_state"
        ]
        == "needs_review"
    )

    print(
        "T07j Mali tatil mixed tax_type fail-closed:",
        "PASS"
    )

    # ========================================================
    # T07k MALİ TATİL SIZMAMASI - ref'i TAŞIMAYAN bir kural, sayım
    # penceresi mali tatile denk gelse BİLE, davranış bu özelliğin
    # EKLENMESİNDEN ÖNCEki ile bayt-bayt AYNI kalır (eski T05 senaryosu
    # - anchor 25.06, ham 25.07, adli tatil -> 07.09).
    # ========================================================

    rule_without_mali_tatil_ref = dict(
        rule
    )

    rule_without_mali_tatil_ref[
        "legal_basis_refs"
    ] = [
        ref
        for ref in rule.get(
            "legal_basis_refs",
            []
        )
        if ref
        != MALI_TATIL_TRIGGER_REF
    ]

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-25",

            rule=
                rule_without_mali_tatil_ref,

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
            "calculated_deadline"
        ]
        == "2026-09-07"
    )

    assert (
        result[
            "mali_tatil_applied"
        ]
        is False
    )

    assert (
        result[
            "mali_tatil_exclusion_reason"
        ]
        == "rule_lacks_legal_basis"
    )

    print(
        "T07k Mali tatil non-leakage (rule without the ref):",
        "PASS"
    )

    # ========================================================
    # T07l MALİ TATİL SIZMAMASI - BİLİNMEYEN (5604'ün GERÇEK ref'i
    # OLMAYAN) bir ref taşıyan kural da AYNI şekilde sızıntısız kalır.
    # ========================================================

    rule_with_unknown_ref = dict(
        rule
    )

    rule_with_unknown_ref[
        "legal_basis_refs"
    ] = [
        (
            ref
            if ref
            != MALI_TATIL_TRIGGER_REF
            else "KANUN_9999_m1"
        )
        for ref in rule.get(
            "legal_basis_refs",
            []
        )
    ]

    result = (
        calculate_rule_deadline(
            anchor_date=
                "2026-06-25",

            rule=
                rule_with_unknown_ref,

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
        == "2026-09-07"
    )

    assert (
        result[
            "mali_tatil_applied"
        ]
        is False
    )

    assert (
        result[
            "mali_tatil_exclusion_reason"
        ]
        == "rule_lacks_legal_basis"
    )

    print(
        "T07l Mali tatil non-leakage (rule with an unrelated ref):",
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
        == 7
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
        " DEADLINE CALCULATOR V1: 27/27 PASS"
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