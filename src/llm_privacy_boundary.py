# ============================================================
# PILOT READINESS ADIM 4a - LLM GIZLILIK SINIRI
# (geri cevrilebilir takma adlandirma / reversible pseudonymisation)
#
# Bu modul, dis LLM'e (Anthropic) gonderilecek prompt icindeki BILINEN
# taraf adlarini ve TCKN/VKN/IBAN/telefon/e-posta bicimlerini gecici,
# geri cevrilebilir token'larla degistirir; modelin cevabinda ayni
# token'lari gercek degerlere geri cevirir.
#
# BAGLAYICI SINIRLAR (abartilmaz):
#   * Bu ANONIMLESTIRME DEGILDIR, takma adlandirmadir (pseudonymisation).
#     Vergi turu + donem + tutar + tarih + mahkeme + esas no birlesimi
#     prompt'ta KALIR ve yeniden kimliklendirme riski KALIR.
#   * Tohum (seed) listesinde olmayan bir ad HAYATTA KALIR - repoda NER
#     yoktur, semada adres alani yoktur. Tanik/mudur/muhasebeci/karsi
#     taraf adlari ve adresler bu katmanla KAPANMAZ.
#   * `case_id`/`party_id`/`document_id` MASKELENMEZ (attribution onlara
#     bagimlidir); opak olmayan bir id fail-closed REDDEDILIR, ama bu
#     yalniz BILINEN tohum cekirdeklerine karsi bir kontroldur.
#   * Modelin token'i aynen yansitip yansitmadigi bu repoda OLCULMEDI
#     (ag yok). Guvenlik agi: bilinmeyen/bozuk/harf-degismis token
#     sessizce gecmez - pending YAZILMAZ.
#   * VAZGECILEN SINIF (R1(iii), acikca): TEK kelimelik bir tohumun
#     ORTASINA duz bir bosluk veya satir sonu sokulmus olmasi (harf
#     araligi verilmis metin) ARTIK REDDEDILMEZ - yalnizca
#     `possible_squeeze_seed_match` sayaciyla onizlemede RAPORLANIR.
#     Gerekce ve olcum: bkz. `count_squeeze_only_seed_matches()`.
#   * YAPISAL NOT (N4, acik mimari borc): tohum (ad) sinifinda
#     maskeleyici ile backstop ARTIK FARKLI karsilastirma kullanir
#     (`fold1to1` vs `scan_fold`) - B1'in kok nedeni budur ve
#     kapatilmistir. Ama KIMLIK siniflarinda (TCKN/VKN/IBAN/telefon/
#     e-posta) maskeleyici ve backstop HALA AYNI regex'i paylasir; bu
#     siniflarda backstop BAGIMSIZ bir guvenlik agi DEGILDIR -
#     maskeleyicinin kor noktasi onun da kor noktasidir. R3 bu desenin
#     somut bir ornegini (tire/nokta grupli IBAN) kapatti; deseni
#     genel olarak kirmak ayri bir tasarim turudur.
#   * R4 KAPANDI (satir-sonu tire kirilimi - CLAUDE.md Pilot Readiness
#     Adim 4a checkpoint madde 4): tek gercek ASCII tire (`-`, U+002D)
#     + HEMEN ARDINDA gercek bir satir sonu (`\n`/`\r\n`), bir tohum
#     kelimesinin ICINDE (PDF hyphenation/line-wrap) daha once HICBIR
#     katmanda (maskeleyici, backstop, squeeze sayaci) taninmiyordu -
#     ad TAMAMEN SESSIZCE, ne maskelenmeden ne reddedilmeden, dis
#     LLM'e gidiyordu. Artik hem `scan_fold()` (backstop, guvenlik agi)
#     hem `_find_flexible()`/`_word_pattern()` (birincil maskeleyici,
#     asil cozum) bu deseni bir kelimenin HARFLERI ARASINDA "atlanabilir
#     kopru" olarak tanir. Desen SIKI: tire + hemen ardinda GERCEK bir
#     satir sonu SART - ayni satirda yazilmis GERCEK tireli bileşik
#     isimler (`Ali-Mehmet`) bu deseni ASLA eslestirmez, cunku tirenin
#     hemen ardinda satir sonu YOKTUR. `MASKING_POLICY_VERSION` bu
#     degisiklikle `v1` -> `v3` bump edildi (identity payload'a girer;
#     `v2` bilincli olarak atlandi - bkz. asagidaki "POLITIKA SURUMU"
#     bolumu).
#   * R4-F1 KAPANDI (bagimsiz salt-okunur inceleme, Bulgu F1 - squeeze-
#     only sayac sinyalinin sessizlesmesi): R4'un `scan_fold()`'a
#     ekledigi KOSULSUZ, GLOBAL tire+satir-sonu SILME adimi, bir seed'in
#     KENDI GERCEK tiresinin (ornek: "Ali-Mehmet" bilesik ismi, veya bir
#     sirket eki tasiyan tireli unvan) PDF satir-sarma noktasina
#     TESADUFEN denk geldigi durumda (`"Ali-\nMehmet"`), belgenin
#     squeeze bicimindeki tireyi SILIYOR ama seed'in KENDI squeeze'i
#     (seed string'inin icinde bitisik bir satir sonu OLMADIGI icin)
#     tireyi KORUYORDU - bu asimetri, ONCEDEN TUTAN bir
#     `count_squeeze_only_seed_matches()` isabetini SESSIZCE SIFIRA
#     dusuruyordu. MASKELEME/RET KARARI HICBIR ZAMAN DEGISMEDI (isim hem
#     oncesinde hem sonrasinda MASKELENMIYORDU, backstop reddi de HICBIR
#     ZAMAN tetiklenmiyordu) - yalniz operatorun onizlemede gordugu TEK
#     sinyal (`possible_squeeze_seed_match`) kayboluyordu. Duzeltme:
#     `count_squeeze_only_seed_matches()` artik HER seed icin IKI
#     BAGIMSIZ squeeze karsilastirmasi yapar - mevcut (R4, tire+satir-
#     sonu SILINMIS) `scan_squeeze()` VE
#     `_scan_squeeze_preserve_linewrap_hyphen()` (R4-ONCESI davranisin
#     BIREBIR AYNISI, tire+satir-sonu SILINMEDEN) - IKISINDEN HERHANGI
#     BIRI eslesirse sayac artar (VEYA mantigi). Bu YALNIZ bilgi amaçli
#     sayaci etkiler; `scan_fold()`/`_find_flexible()`/`_word_pattern()`
#     (maskeleyici VE backstop, R4'un asil kazanimi) DEGISMEDEN kalir -
#     desen ICERMEYEN metinlerde (coğunluk) iki varyant BIREBIR AYNI
#     sonucu urettigi icin hicbir mevcut sayim DEGISMEZ.
#     `MASKING_POLICY_VERSION` bump'i GEREKMEDI: bu sayac
#     `identity_payload`'a hic GIRMEZ (yalniz onizleme ozetinde
#     gosterilir) - dogrulandi, bkz. `ui/services/
#     fact_extraction_mutation_facade.py:_build_identity_payload()`.
#
# MIMARI KURALLAR:
#   * stdlib-only (`re`, `json`, `hashlib`, `unicodedata`, `dataclasses`).
#     Hicbir repo modulu, hicbir `ui.*` modulu import EDILMEZ; dosya/ag
#     erisimi YOKTUR. Boylece hem `src/` hem `ui/` tarafindan dongusuz
#     kullanilabilir (`src/path_containment.py` emsali).
#   * Eslesme tablosu (`MaskMapping`) DISKE YAZILMAZ, LOGLANMAZ,
#     EXCEPTION'A GIRMEZ; `__repr__`/`__str__` hicbir sey aciga vurmaz.
#   * TUM exception mesajlari SABITTIR - hicbir eslesen deger, token,
#     harita ya da belge metni mesaja girmez (`ui/cli_mutate.py` hata
#     satirinda `str(exception)` basar).
#
# TOKEN DILBILGISI: `VGMASK_<NNNN><C>` - SINIF HARFI SONDA.
#   `C` in {P isim/tohum, T 11 hane, V 10 hane, B IBAN, F telefon,
#    E e-posta}. Sayac SINIF BASINA'dir (her sinif 0001'den baslar).
#   Sinif harfinin sonda olmasi token'i kendini-sinirlayan yapar:
#     `VGMASK_00011P` (uzatilmis rakam alani) BLOKLANIR,
#     `VGMASK_0001P1` (token + KAYNAK rakami) KABUL EDILIR.
#   Onek `VGMASK` icinde `I`/`i` YOKTUR - Turkce buyuk/kucuk harf
#   tuzaklarindan (I/i/İ/ı) yapisal olarak bagisiktir.
#
# TASARIM KARARLARI (kapsam raporunun SESSIZ kaldigi yerler - hepsi
# rapora da yazildi):
#   D1. Token numaralandirma SINIF BASINA ve ILK GORULME sirasina
#       goredir: once context (kendi `json.dumps` anahtar sirasiyla:
#       `source_document_title` -> `source_actor_label` -> `parties[]`
#       sirasiyla), SONRA belge metni. Her maskeleme gecisi icinde
#       adaylar `(baslangic, -uzunluk, sinif_onceligi)` ile siralanir,
#       ortusmeyenler secilir, token'lar ARTAN metin sirasinda atanir,
#       degistirme SONDAN yapilir (indeks kaymasi olmaz).
#   D2. Fixpoint yeniden taramasi YERLESTIRILMIS TOKEN'LARIN ICINE
#       BAKMAZ (segment bazli tarama). Aksi halde bir e-posta deseni
#       `VGMASK_0001Pahmet@...` icinde token'in ICINDEN baslayip token'i
#       yok ederdi (Rapor C §4.5'in gercek kusuru).
#   D3. "Haritadaki her token cevapta en az bir kez gorunmeli" kurali
#       REDDETMEZ, RAPORLAR (`dropped_token_count`). Dusen bir token bir
#       SIZINTI degil, kalite kaybidir (kapsam raporu §5 not b); reddetmek
#       modelin alintilamadigi her IBAN/telefon icin dosyayi kalici olarak
#       islenemez kilardi. Guvenlik tarafi ("onek sayisi == eslesen token
#       sayisi") AYRI ve FAIL-CLOSED kalir.
#   D4. Bos tohum listesi = SIFIR `individual`/`company` `display_name`
#       tohumu VE SIFIR operator terimi. Yalnizca referans kodu/dosya adi
#       tohumu bu sarti KARSILAMAZ (kapsam raporu: "hicbir taraf adi").
#   D5. Opak-olmayan id kontrolu YALNIZ taraf-adi cekirdeklerini ve
#       operator terimlerini kullanir (dosya adi/referans kodu kullanilsa
#       `document_id="ihbarname_001"` kendi `file_name`'i yuzunden
#       reddedilirdi). Eslesme: ASCII-transliterasyon + fold + alfanumerik
#       disi karakterlerin atilmasi sonrasi (a) >= 4 karakterli cekirdegin
#       ALT DIZI olmasi, ya da (b) >= 3 karakterli cekirdegin id'nin
#       `_`/`-` ile bolunmus bir PARCASINA tam esit olmasi.
#   D6. Model-yonelimli token talimat blogu maskeleme adiminin ICINDE
#       uretilir ve YALNIZ maskeleme etkinken USER prompt'un SONUNA
#       eklenir; `SYSTEM_PROMPT` ve `PROMPT_VERSION` DEGISMEZ. Blok
#       SOMUT bir ornek token ICERMEZ (ornek token modelin onu aynen
#       yansitmasi ve bilinmeyen-token reddine yol acmasi riskini
#       tasirdi) - yalniz BICIM tarif edilir.
#   D7. Saglama toplami (checksum) MASKELEME KARARINI ETKILEMEZ: 10 ve
#       11 haneli TUM maksimal ASCII rakam dizileri maskelenir ve
#       UZUNLUGA gore etiketlenir (11 -> T, 10 -> V). Checksum yalnizca
#       onizlemedeki "olasi asiri maskeleme" raporu icin hesaplanir.
# ============================================================

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

# ------------------------------------------------------------
# POLITIKA SURUMU
#
# Bu sabit `identity_payload`'a girer (`masking_policy_version`), yani
# `input_digest` -> `pre_revision` -> `idempotency_key` zincirine dahildir.
# Degistirilmesi, ayni girdiler icin YENI ve BAGIMSIZ bir deneme uretir
# (kalici bir conflict DEGIL). `PROMPT_VERSION` ile BILINCLI OLARAK AYRI
# tutulur - `PROMPT_VERSION` bump'i `extraction_id`/`fact_id` literal'ini
# ve pending dosya adini etkiler, bu sabit ETKILEMEZ.
#
# v1 -> v3 (R4): satir-sonu tire kirilimi duzeltmesi (bkz. modul basligi
# R4 notu). Bump ZORUNLUDUR: aksi halde v1 ile TAMAMLANMIS (ama bugli -
# isim maskesiz) bir mutasyon, kod degistikten SONRA AYNI girdilerle
# "safe replay" ile YENIDEN CALISTIRILMADAN eski sonucu dondurebilirdi.
# "v2" BILINCLI OLARAK ATLANDI: `ui/tests/test_reconciliation_isolated.py`
# (LOCKED, bu degisikligin 2-dosyalik allowlist'i DISINDA) identity-
# digest farklilasmasini kanitlamak icin "tr_pseudonymisation_v2"yi
# ONCEDEN, bagimsiz olarak, sabit bir "farkli deger" test placeholder'i
# olarak kullaniyordu; bu ikisinin CAKISMASI, allowlist disina cikip
# (yani 3. bir dosyaya dokunup) o testi degistirmek YERINE, cakismasiz
# bir surum secilerek onlenmistir (bkz. `git grep tr_pseudonymisation`
# ile dogrulanan bos "v3" alani).
# ------------------------------------------------------------

MASKING_POLICY_VERSION = "tr_pseudonymisation_v3"


# ------------------------------------------------------------
# TOKEN DILBILGISI
# ------------------------------------------------------------

TOKEN_PREFIX = "VGMASK"

# Buyuk/kucuk harf DUYARLI - yalnizca BIZIM urettigimiz, tam kurallı
# token'lari eslestirir.
TOKEN_RE = re.compile(r"VGMASK_([0-9]{4})([PTVBFE])")

# Buyuk/kucuk harf DUYARSIZ - "bir token olmaya calisan" her seyi gorur.
# Bu ayrim YUK TASIYICIDIR: harf-degismis bir token (`vgmask_0001p`)
# duyarli aramada HIC eslesmez, "onek sayisi == eslesen token sayisi"
# kontrolu 0 == 0 ile gecer ve metin sessizce pending'e girerdi.
PREFIX_RE = re.compile(TOKEN_PREFIX, re.IGNORECASE)

CLASS_PARTY = "P"
CLASS_TCKN = "T"
CLASS_VKN = "V"
CLASS_IBAN = "B"
CLASS_PHONE = "F"
CLASS_EMAIL = "E"

ALL_CLASSES = (CLASS_PARTY, CLASS_TCKN, CLASS_VKN, CLASS_IBAN, CLASS_PHONE, CLASS_EMAIL)

# Yalnizca AYNI baslangic VE AYNI uzunluktaki adaylar arasinda karar
# verir (farkli uzunluklar zaten `-uzunluk` ile cozulur). Tek gercek
# kullanim: kompakt bir cep telefonu (`05321234567`) hem telefon hem
# 11-hane dizisi olarak eslesir - telefon etiketi daha dogrudur.
_CLASS_PRIORITY = {
    CLASS_PARTY: 0,
    CLASS_EMAIL: 1,
    CLASS_IBAN: 2,
    CLASS_PHONE: 3,
    CLASS_TCKN: 4,
    CLASS_VKN: 5,
}

_MAX_TOKEN_INDEX = 9999

# Fixpoint ust siniri. Her gecis en az bir yeni token yerlestirmek
# zorundadir; yerlestiremezse dongu biter. Ust sinira ulasilmasi
# yapisal olarak beklenmez - ulasilirsa FAIL-CLOSED.
_MAX_MASK_PASSES = 8

# Turetilmis tohum varyantlarinin kabul edilen en kisa uzunlugu
# (katlanmis bicimde). 2 harfli bir cekirdek sira gelen her kelimenin
# icinde eslesirdi.
_MIN_SEED_VARIANT_LEN = 3

# Opak-olmayan id kontrolunde alt-dizi karsilastirmasi icin en kisa
# uzunluk (bkz. D5).
_MIN_ID_SUBSTRING_CORE_LEN = 4
_MIN_ID_SEGMENT_CORE_LEN = 3


# ------------------------------------------------------------
# EXCEPTION AILESI - HER MESAJ SABITTIR
# ------------------------------------------------------------


class LlmPrivacyBoundaryError(Exception):
    """Tum maskeleme/geri-cevirme hatalarinin ortak tabani."""


class MaskingError(LlmPrivacyBoundaryError):
    """GIDEN yol (outbound) hatasi - prompt GONDERILMEZ."""


class DeMaskingError(LlmPrivacyBoundaryError):
    """DONUS yolu (return path) hatasi - pending YAZILMAZ."""


class EmptySeedListError(MaskingError):
    pass


class MaskCollisionError(MaskingError):
    pass


class SurvivingPatternError(MaskingError):
    pass


class NonAsciiDigitError(MaskingError):
    pass


class ZeroWidthDigitRunError(MaskingError):
    pass


class NonOpaqueIdentifierError(MaskingError):
    pass


class MaskedInputTooLongError(MaskingError):
    pass


class TokenSpaceExhaustedError(MaskingError):
    pass


class MaskingFixpointError(MaskingError):
    pass


class SeedTermError(MaskingError):
    pass


class UnknownTokenError(DeMaskingError):
    pass


class MalformedTokenError(DeMaskingError):
    pass


class TokenInKeyError(DeMaskingError):
    pass


class ResidualTokenError(DeMaskingError):
    pass


# Sabit mesajlar - hicbiri degisken enterpolasyonu ICERMEZ.
MSG_EMPTY_SEEDS = (
    "Maskeleme reddedildi: maskelenecek hicbir taraf adi yok "
    "(gercek/tuzel kisi taraf adi ve operator terimi bulunamadi). "
    "Gerekirse --mask-term ile terim saglayin."
)
MSG_COLLISION = (
    "Maskeleme reddedildi: kaynak icerik zaten maskeleme token onekini "
    "tasiyor."
)
MSG_SURVIVING = (
    "Maskeleme reddedildi: giden metinde bilinen bir kisisel veri deseni "
    "maskelenmeden hayatta kaldi."
)
MSG_SURVIVING_NORMALISED = (
    "Maskeleme reddedildi: bir taraf adi, gorunmez karakter veya birlesik "
    "olmayan Unicode bicimi nedeniyle maskelenemeden giden metinde hayatta "
    "kaldi. Belge metnini NFC/temiz bicime getirin."
)
MSG_NON_ASCII_DIGIT = (
    "Maskeleme reddedildi: kaynak icerik ASCII olmayan rakam karakteri "
    "iceriyor."
)
MSG_ZERO_WIDTH_DIGIT_RUN = (
    "Maskeleme reddedildi: kaynak icerik, sifir genislikli karakterle "
    "bolunmus ve cozulemeyen bir rakam dizisi iceriyor."
)
MSG_NON_OPAQUE_ID = (
    "Maskeleme reddedildi: case/taraf/belge kimliklerinden biri bir taraf "
    "adini iceriyor. Opak kimlikler kullanin."
)
MSG_MASKED_TOO_LONG = (
    "Maskeleme reddedildi: maskelenmis metin tek cagri karakter sinirini "
    "asiyor."
)
MSG_TOKEN_SPACE = (
    "Maskeleme reddedildi: bir token sinifi icin ayrilmis numara alani "
    "tukendi."
)
MSG_FIXPOINT = (
    "Maskeleme reddedildi: maskeleme sabit noktaya (fixpoint) yakinsamadi."
)
MSG_SEED_TERM = (
    "Maskeleme reddedildi: saglanan terimlerden biri gecersiz "
    "(bos, metin disi veya maskeleme token onekini iceriyor)."
)
MSG_UNKNOWN_TOKEN = (
    "Model cevabi reddedildi: taninmayan bir maskeleme token'i iceriyor. "
    "Pending yazilmadi."
)
MSG_MALFORMED_TOKEN = (
    "Model cevabi reddedildi: bozuk/kesik/harfi degistirilmis bir maskeleme "
    "token'i iceriyor. Pending yazilmadi."
)
MSG_TOKEN_IN_KEY = (
    "Model cevabi reddedildi: bir JSON anahtarinda maskeleme token'i var. "
    "Pending yazilmadi."
)
MSG_RESIDUAL_TOKEN = (
    "Model cevabi reddedildi: geri cevirme sonrasi artik maskeleme token'i "
    "kaldi. Pending yazilmadi."
)


# ------------------------------------------------------------
# METIN NORMALIZASYON YARDIMCILARI
# ------------------------------------------------------------

# UZUNLUK KORUYAN 1:1 Turkce katlama. YALNIZCA KONUM BULMAK icindir;
# degistirme HER ZAMAN orijinal indeksler uzerinde yapilir.
# `casefold()` uzunlugu degistirir ("İSTANBUL" 8 -> 9) ve span
# eslestirmesini bozar.
_TR_FOLD_EXPLICIT = {
    "İ": "i",   # İ  (dotted capital I)  -> i
    "I": "ı",   # I  (dotless capital I) -> ı
}

_ASCII_TRANSLIT = {
    "ş": "s", "Ş": "S",
    "ı": "i", "İ": "I",
    "ğ": "g", "Ğ": "G",
    "ü": "u", "Ü": "U",
    "ö": "o", "Ö": "O",
    "ç": "c", "Ç": "C",
    "â": "a", "Â": "A",
    "î": "i", "Î": "I",
    "û": "u", "Û": "U",
}

_ZERO_WIDTH_CHARS = "­​‌‍﻿⁠"


def fold1to1(text):
    """Uzunlugu KORUYAN Turkce-duyarli kucuk harfe katlama.

    `I -> ı`, `İ -> i`; cok karakterli bir kucuk harf karsiligi olan her
    karakter (ör. `ß`) OLDUGU GIBI birakilir, boylece `len(fold1to1(s))
    == len(s)` HER ZAMAN saglanir."""
    out = []
    for ch in text:
        mapped = _TR_FOLD_EXPLICIT.get(ch)
        if mapped is not None:
            out.append(mapped)
            continue
        low = ch.lower()
        out.append(low if len(low) == 1 else ch)
    return "".join(out)


def ascii_transliterate(text):
    """Turkce karakterleri ASCII karsiliklarina cevirir. Yalnizca TOHUM
    VARYANTI uretmek ve id-opaklik karsilastirmasi icin kullanilir -
    kaynak metne ASLA uygulanmaz."""
    return "".join(_ASCII_TRANSLIT.get(ch, ch) for ch in text)


def nfc(text):
    return unicodedata.normalize("NFC", text)


_SCAN_DROP_CHARS = frozenset(_ZERO_WIDTH_CHARS)
_WHITESPACE_RUN_RE = re.compile(r"\s+")

# R4: bir kelimenin GERCEK bir satir sonunda tire ile bolunmesi (PDF
# hyphenation/line-wrap). Tam olarak BIR gercek `-` (U+002D) + hemen
# ardindan (opsiyonel yatay bosluk/tab ile) TAM OLARAK BIR gercek satir
# sonu (`\n` ya da `\r\n`, COGUL DEGIL - `\n+` DEGIL `\n`, boylece bir
# PARAGRAF arasi YANLISLIKLA "ayni kelime" sayilmaz) + devam
# satirindaki olasi girinti/bosluk. Ayni satirda yazilmis GERCEK tireli
# bilesik isimler (`Ali-Mehmet`) bu deseni ASLA eslestirmez - tirenin
# hemen ardinda GERCEK bir satir sonu SART.
_LINE_WRAP_HYPHEN_RE = re.compile(r"[ \t]*-[ \t]*\r?\n[ \t]*")

# Ayni desen, birincil maskeleyicide (`_word_pattern()`) bir kelimenin
# HARFLERI ARASINDA "atlanabilir, opsiyonel bir kopru" olarak kullanilir.
# Desen YOKSA sifir-genislikli eslesir - literal ardarda aramayla
# BIREBIR AYNI davranir.
_LINE_WRAP_BRIDGE_GROUP = r"(?:[ \t]*-[ \t]*\r?\n[ \t]*)?"


def _scan_fold_impl(text, *, strip_line_wrap_hyphen):
    """`scan_fold()`/`_scan_fold_preserve_linewrap_hyphen()`'in ORTAK
    govdesi - R4-F1 remediasyonu (bkz. asagida) AYNI normalizasyon
    zincirini yalniz TEK bir bayrakla (satir-sonu-tire SILME adimi
    acik/kapali) tekrar kullanabilsin diye TEK bir yerde tutulur; kod
    tekrari YOK. Iki genel fonksiyonun docstring'leri kendi
    davranislarini ayrintili anlatir."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(
        ch for ch in text
        if not unicodedata.combining(ch) and ch not in _SCAN_DROP_CHARS
    )
    if strip_line_wrap_hyphen:
        # R4: satir-sonu tire kirilimini SIL - whitespace-daraltmadan
        # ONCE (bkz. `scan_fold()` docstring'i).
        text = _LINE_WRAP_HYPHEN_RE.sub("", text)
    text = _WHITESPACE_RUN_RE.sub(" ", text)
    return fold1to1(text)


def scan_fold(text):
    """YALNIZ TARAMA (backstop) icin normalizasyon - maskeleyicinin span
    aritmetigine ASLA uygulanmaz.

    B1 KOK NEDENI: maskeleyici konum bulmayi `fold1to1(segment).find(
    seed.folded)` ile, giden tarama ise `seed.folded in fold1to1(region)`
    ile yapiyordu - AYNI karsilastirma. Bu yuzden maskeleyicinin HER kor
    noktasi backstop'un da kor noktasiydi: bir taraf adi satir sonu, cift
    bosluk, sekme, NBSP, yumusak tire veya ZWSP ile bolundugunde ya da
    metin NFD bicimindeyken ne MASKELENIYOR ne de REDDEDILIYORDU -
    sessizce dis LLM'e gidiyordu.

    Bu fonksiyon backstop'u maskeleyiciden BAGIMSIZ kilar:
      NFKC -> uyumluluk + BIRLESTIRME (composition) -> BIRLESMEDEN KALAN
      birlestirici isaretleri at -> sifir genislikli karakterleri ve
      yumusak tireyi at -> her bosluk dizisini TEK boskluga daralt ->
      fold1to1.

    NEDEN NFKD DEGIL NFKC (ucuncu remediasyon):
    NFKD + "tum birlestiricileri at" Turkce AKSANLARI SILIYORDU
    (`taşınmaz` -> `tasınmaz`, `türü` -> `turu`,
    `alınmıştır` -> `alınmıstır`). Maskeleyici aksanlari KORUDUGU icin
    (`fold1to1`, normalizasyon yok) bir sirket cekirdegi `Tas`/`Tur`
    bu kelimeleri ASLA maskeleyemiyordu; ama backstop onlari
    `tasınmaz`/`turu` icinde BULUYOR ve dosyayi KALICI olarak
    reddediyordu - operatorun hicbir caresi olmadan. Siradan vergi
    metninde `taşınmaz`, `taşıt`, `türü`, `alınmıştır` rutindir; gercek
    repo fixture'larinda 3 ret bu siniftandi.

    NFKC ile:
      * NFD bicimli bir ad (`s`+U+0327, `u`+U+0308, `I`+U+0307) YENIDEN
        BIRLESIR ve tohumun birlesik biciminin AYNISI olur ⇒ B1'in
        NFD-ad REDDI KORUNUR;
      * tam genislikli / uyumluluk harfleri yine katlanir;
      * kelime ICINDE gizlenmis gorunmez karakter yine REDDEDILIR;
      * ama bir tohumun AKSANSIZ (ASCII) varyanti artik aksanli siradan
        bir kelimenin icinde ESLESMEZ.
    Adin gercekten ASCII-transliterasyonlu yazildigi durumlar
    maskeleyicinin KENDI transliterasyon varyantlariyla zaten
    karsilanir (degismedi).

    R4 (DORDUNCU remediasyon): bu fonksiyon artik satir-sonu tire
    kirilimini (`_LINE_WRAP_HYPHEN_RE`) da SILER - `\\n` henuz TEK
    BOSLUGA daraltilmadan ONCE, aksi halde "gercek satir sonu" bilgisi
    kaybolur ve `"Kayit - devam ediyor"` gibi AYNI SATIRDAKI, satir
    sonu ICERMEYEN siradan bir tire kullanimi yanlislikla etkilenebilir
    (bu duzenle ETKILENMEZ, cunku regex `\\n`'in GERCEKTEN var olmasini
    sart kosar). `scan_squeeze()` bu fonksiyonu SARDIGI icin (asagida)
    duzeltmeyi OTOMATIK MIRAS ALIR - ayri bir degisiklik gerekmez.

    R4-F1 (bagimsiz inceleme, Bulgu F1): bu KOSULSUZ, GLOBAL silme adimi
    bir seed'in KENDI GERCEK tiresini de (satir-sarma noktasina
    tesaduf ederse) siler - `_scan_fold_preserve_linewrap_hyphen()` bu
    asimetriyi `count_squeeze_only_seed_matches()`'te bagimsiz bir
    IKINCI kontrol olarak telafi eder (asagida); bu fonksiyonun KENDISI
    ve onun cagirdigi maskeleyici/backstop davranisi DEGISMEDEN kalir.

    Hem taranan bolgeye HEM tohum terimine uygulanir. Kaynak metin ASLA
    bu bicimde saklanmaz/gonderilmez (excerpt bayt sadakati)."""
    return _scan_fold_impl(text, strip_line_wrap_hyphen=True)


def scan_squeeze(text):
    """`scan_fold()` + TUM bosluklarin da atilmasi.

    Neden ayri bir bicim gerekiyor: gorunmez bir karakter bir bosluğun
    YERINE gectiginde (`"Ahmet\\u00adYılmaz"` - arada HIC bosluk yok),
    yalnizca daraltma yapan `scan_fold()` bolgeyi `"ahmetyılmaz"`,
    tohumu ise `"ahmet yılmaz"` yapar ve ESLESMEZ - ad yine sessizce
    gecerdi. Bosluklari TAMAMEN atan ikinci bir karsilastirma bu sinifi
    kapatir. Iki kontrol birlikte calisir; ikisi de yalnizca TARAMA
    icindir."""
    return scan_fold(text).replace(" ", "")


def _scan_fold_preserve_linewrap_hyphen(text):
    """R4-F1 REMEDIASYONU (bagimsiz salt-okunur inceleme, Bulgu F1):
    `scan_fold()`'un R4-ONCESI davranisinin BIREBIR AYNISI - satir-sonu-
    tire SILME adimi UYGULANMAZ, geri kalan HER SEY (NFKC, diacritic/
    drop-char temizligi, whitespace daraltma, fold1to1) AYNEN calisir.

    NEDEN GEREKLI: R4'un `scan_fold()`'a ekledigi KOSULSUZ, GLOBAL
    tire+satir-sonu SILME adimi, bu silmenin bir PDF line-wrap
    ARTEFAKTI mi yoksa SEED'IN KENDI, GERCEK bir tiresinin PARCASI mi
    oldugunu AYIRT ETMEZ. Seed'in KENDI tiresi (ornek: "Ali-Mehmet"
    bilesik ismi) tam da belgenin PDF satir-sarma noktasina denk
    geldiginde (`"Ali-\\nMehmet"`), R4-SONRASI `scan_fold` belgenin
    tiresini SILER ama seed'in KENDI `scan_fold`'u (seed string'inin
    icinde bitisik bir satir sonu OLMADIGI icin) tireyi KORUR - bu
    asimetri, ONCEDEN TUTAN bir squeeze-only eslesmeyi SESSIZCE
    SIFIRLAR (operatorun onizlemede gordugu TEK sinyal kayboluyor;
    maskeleme/ret KARARI DEGISMIYOR - bkz.
    `count_squeeze_only_seed_matches()`).

    YALNIZ `count_squeeze_only_seed_matches()`'in ONCEKI (R4-ONCESI)
    squeeze davranisini bir IKINCI, BAGIMSIZ kontrol olarak yeniden
    hesaplamak icin kullanilir - birincil maskeleyici (`_find_flexible`/
    `_word_pattern`) VEYA backstop reddi (`_scan_region_for_seeds`) bu
    fonksiyonu KULLANMAZ, ikisi de degismeden `scan_fold()`'un R4
    davranisini kullanmaya devam eder (R4'un asil kazanimi - kelime ICI
    hyphen bridging maskelemesi - bu fonksiyondan ETKILENMEZ)."""
    return _scan_fold_impl(text, strip_line_wrap_hyphen=False)


def _scan_squeeze_preserve_linewrap_hyphen(text):
    """`_scan_fold_preserve_linewrap_hyphen()` + TUM bosluklarin da
    atilmasi - `scan_squeeze()`'in R4-ONCESI davranisinin BIREBIR
    AYNISI. Yalniz `count_squeeze_only_seed_matches()` icin, R4-F1
    remediasyonunun IKINCI, BAGIMSIZ kontrolu olarak kullanilir."""
    return _scan_fold_preserve_linewrap_hyphen(text).replace(" ", "")


def has_non_ascii_digits(text):
    """ASCII olmayan ONDALIK rakam var mi?

    `isdecimal()` kullanilir, `isdigit()` DEGIL: `'²'.isdigit()` True'dur
    ve Turkce bir vergi raporundaki "m²" ifadesi yanlis yere reddedilirdi.
    `isdecimal()` Arap-Hint ve tam genislikli rakamlari yine yakalar."""
    return any(ch.isdecimal() and not ch.isascii() for ch in text)


_ZERO_WIDTH_DIGIT_RUN_RE = re.compile(
    "[0-9" + _ZERO_WIDTH_CHARS + "]+"
)


_SPLIT_SEPARATOR_CHARS = _ZERO_WIDTH_CHARS + "­"
_SPLIT_DIGIT_RUN_RE = re.compile(
    "[0-9](?:[0-9\\s" + _SPLIT_SEPARATOR_CHARS + "]*[0-9])?"
)


def count_possible_split_identifiers(text):
    """BILGI AMACLI SAYAC (kapsam karari b2) - HICBIR RET URETMEZ.

    Yalnizca bosluk / satir sonu / sifir genislikli karakter / yumusak
    tire ile ayrilmis, sikistirildiginda TAM 10 veya 11 haneye ulasan
    MASKELENMEMIS rakam dizilerini sayar.

    NEDEN RET DEGIL (sahibin karari b2): rakamlari bosluk boyunca
    birlestiren bir TARAMA, siradan tablo/binlik sayilarinda HAKSIZ RET
    uretir (`"Sayfa 12345 67890"`, `"Tutar 1 234 567 890 TL"` - ampirik
    olarak olculdu) ve operator bunu DUZELTEMEZ. Bunun yerine avukat
    onizlemede bir uyari gorur ve maskeli metni kendisi kontrol eder;
    apply zaten onizleme digest'ini gerektirir.

    `.` ve `,` AYRAC OLARAK SAYILMAZ - Turkce bir tutar (`12.345.678,90`)
    sikistirilirsa VKN sagalamasindan GECEN `1234567890` olur (kapsam
    F4). Bu yuzden ayraclar yalnizca bosluk sinifiyla sinirlidir.

    ACIK KALAN SINIR: satir sonuyla bolunmus bir TCKN/VKN bu turda
    MASKELENMEZ - yalnizca sayilir ve onizlemede gosterilir."""
    hits = 0
    for match in _SPLIT_DIGIT_RUN_RE.finditer(text):
        span = match.group(0)
        if not any(ch in _SPLIT_SEPARATOR_CHARS or ch.isspace() for ch in span):
            continue
        digits = "".join(ch for ch in span if ch.isascii() and ch.isdecimal())
        if len(digits) in (10, 11):
            hits += 1
    return hits


def count_possible_split_identifiers_outside_tokens(text):
    """`count_possible_split_identifiers()`, yerlestirilmis token'larin
    ICI ATLANARAK - yani YALNIZ maskelenmemis rakam dizileri."""
    hits = 0
    for is_token, start, end in _token_segments(text):
        if is_token:
            continue
        hits += count_possible_split_identifiers(text[start:end])
    return hits


def find_unresolvable_zero_width_digit_runs(text):
    """Sifir genislikli karakterle bolunmus, sikistirildiginda 10 veya 11
    haneye ulasan rakam dizilerinin sayisi. Bunlar duz `[0-9]{10,11}`
    maskeleyicisinden KACAR ve bir kimlik gizliyor olabilir."""
    hits = 0
    for match in _ZERO_WIDTH_DIGIT_RUN_RE.finditer(text):
        span = match.group(0)
        if not any(ch in _ZERO_WIDTH_CHARS for ch in span):
            continue
        digits = "".join(ch for ch in span if ch.isascii() and ch.isdecimal())
        if len(digits) in (10, 11):
            hits += 1
    return hits


# ------------------------------------------------------------
# KIMLIK SAGLAMA TOPLAMLARI
#
# UYARI (provenans): TCKN ve VKN algoritmalari yayimlanmis, yaygin
# bicimleriyle uygulanmistir ama bu ortamda YETKILI (GIB) bir kaynaga
# karsi DOGRULANAMADI. Bu yuzden tasarim saglama toplamina BAGIMLI
# DEGILDIR: maskeleme karari yalnizca UZUNLUGA bakar (bkz. D7); bu
# fonksiyonlar sadece onizlemedeki "olasi asiri maskeleme" raporunda
# kullanilir.
# ------------------------------------------------------------


def tckn_is_valid(value):
    if not isinstance(value, str) or len(value) != 11 or not value.isascii():
        return False
    if not value.isdecimal():
        return False
    digits = [int(ch) for ch in value]
    if digits[0] == 0:
        return False
    odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
    even_sum = digits[1] + digits[3] + digits[5] + digits[7]
    if (odd_sum * 7 - even_sum) % 10 != digits[9]:
        return False
    if sum(digits[:10]) % 10 != digits[10]:
        return False
    return True


def vkn_is_valid(value):
    if not isinstance(value, str) or len(value) != 10 or not value.isascii():
        return False
    if not value.isdecimal():
        return False
    digits = [int(ch) for ch in value]
    total = 0
    for index in range(9):
        tmp = (digits[index] + 9 - index) % 10
        if tmp == 9:
            component = 9
        else:
            component = (tmp * pow(2, 9 - index)) % 9
        total += component
    return (10 - total % 10) % 10 == digits[9]


_IBAN_LETTER_VALUES = {chr(ord("A") + i): str(10 + i) for i in range(26)}


_IBAN_SEPARATOR_CHARS = frozenset("  -.")


def tr_iban_is_valid(value):
    """Ayraclari (bosluk, NBSP, TIRE, NOKTA) temizlenmis TR IBAN mod-97
    kontrolu.

    R3: tire ve nokta ile gruplanmis bir IBAN
    (`TR33-0006-1005-1978-6457-8413-26`) hicbir kurala takilmiyordu -
    4'erli gruplar 10/11 haneli maksimal diziye de uymaz - ve TAM IBAN
    prompt'a ACIKTA gidiyordu. mod-97 kapisi yanlis-pozitifi zaten
    engelledigi icin ayrac sinifini genisletmek guvenlidir."""
    if not isinstance(value, str):
        return False
    compact = "".join(
        ch for ch in value if not ch.isspace() and ch not in _IBAN_SEPARATOR_CHARS
    )
    if len(compact) != 26:
        return False
    compact = compact.upper()
    if not compact.startswith("TR"):
        return False
    if not compact[2:].isascii() or not compact[2:].isdecimal():
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(_IBAN_LETTER_VALUES.get(ch, ch) for ch in rearranged)
    if not numeric.isdecimal():
        return False
    return int(numeric) % 97 == 1


# ------------------------------------------------------------
# DESENLER
#
# KURALLAR (Rapor C §2.3):
#   * `\d` DEGIL `[0-9]` - `\d` Arap-Hint/tam genislikli rakamlari da
#     eslestirir ve sagalama toplamindan gecemez.
#   * Kayan pencere YOK, `\b` YOK - yalnizca MAKSIMAL dizi
#     `(?<![0-9])[0-9]{N}(?![0-9])`.
#   * Ayraclar (`.` `,` bosluk) ASLA temizlenmez: Turkce bir tutar
#     (`12.345.678,90`) ayraclar silininca VKN sagalamasindan GECEN
#     `1234567890` olur.
# ------------------------------------------------------------

_DIGIT_RUN_11_RE = re.compile(r"(?<![0-9])[0-9]{11}(?![0-9])")
_DIGIT_RUN_10_RE = re.compile(r"(?<![0-9])[0-9]{10}(?![0-9])")

# TR IBAN: 'TR' + 24 rakam; gruplar arasinda tek bosluk/NBSP/TIRE/NOKTA
# olabilir (R3). Maskeleyici ve backstop AYNI regex'i kullanir - mod-97
# kapisi yanlis-pozitifi eler; eslesen span AYRACLARI DA icerir, bu
# yuzden geri cevirme BAYT-BAYT kalir.
_IBAN_RE = re.compile(
    r"(?<![0-9A-Za-z])[Tt][Rr](?:[  .\-]?[0-9]){24}(?![0-9A-Za-z])"
)

# Turk telefonu: (+90 | 0090 | 0) + [2-5]xx (cep VE sabit hat) + 3-2-2.
# Parantezli alan kodu ve bosluk/NBSP ayraclari desteklenir.
# Rapor C §2.5/D6: yalniz `5xx` kapsayan ilk referans desen kendi
# fixture'indaki `0 (212) 555 44 33` sabit hattini SESSIZCE kaciriyordu -
# tur testi bunu YAKALAYAMAZ, bu yuzden her bicim icin POZITIF test sart.
_PHONE_RE = re.compile(
    r"(?<![0-9])(?:\+90|0090|0)[  ]?\(?[2-5][0-9]{2}\)?"
    r"[  ]?[0-9]{3}[  ]?[0-9]{2}[  ]?[0-9]{2}(?![0-9])"
)

_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# Onizlemedeki "olasi asiri maskeleme" raporu icin: 10 haneli bir dizinin
# solunda ~40 karakter icinde bir VKN baglam kelimesi var mi?
_VKN_CONTEXT_RE = re.compile(
    r"(?:v\.?k\.?n\.?|vergi\s*kimlik|vergi\s*no|vergi\s*numara)",
    re.IGNORECASE,
)
_VKN_CONTEXT_WINDOW = 40


# ------------------------------------------------------------
# TOHUM (SEED) TERIMLERI
# ------------------------------------------------------------

# U2 KARARI: YALNIZ gercek/tuzel kisi taraflar maskelenir. Vergi dairesi /
# mahkeme / idare adlari (`public_authority`) MASKELENMEZ - bunlar sure ve
# yetki analizinin tasiyici girdisidir. Bunun iki sonucu vardir:
#   (+) `normalize_attribution()`'in sessiz atif dusurme riski YALNIZ
#       administration taraflari icindir, dolayisiyla yapisal olarak
#       ortadan kalkar.
#   (-) Sirket adi + vergi dairesi + tutar + tarih birlesimi yeniden
#       kimliklendiricidir - ACIK sinir (modul basligi).
_MASKABLE_PARTY_TYPES = frozenset({"individual", "company"})

# Sirket eki varyant gruplari - ayni grubun her uyesi digerleriyle
# degistirilerek ek tohum uretilir.
_COMPANY_SUFFIX_GROUPS = (
    (
        "Anonim Şirketi", "Anonim Sirketi",
        "A.Ş.", "A.S.", "A.Ş", "A.S", "AŞ", "AS",
    ),
    (
        "Limited Şirketi", "Limited Sirketi",
        "Ltd. Şti.", "Ltd. Sti.", "Ltd.Şti.", "Ltd.Sti.",
        "Ltd Şti", "Ltd Sti", "LTD ŞTİ", "LTD STI",
    ),
)

_SEED_KIND_PARTY = "party"
_SEED_KIND_REFERENCE = "reference"
_SEED_KIND_DOCUMENT_FILE = "document_file"
_SEED_KIND_OPERATOR = "operator"

# Yalnizca bu iki tur, opak-olmayan id kontrolunde CEKIRDEK olarak
# kullanilir (bkz. D5).
_ID_CHECK_SEED_KINDS = frozenset({_SEED_KIND_PARTY, _SEED_KIND_OPERATOR})


@dataclass(frozen=True)
class SeedTerm:
    """Tek bir maskelenebilir terim ve turevi.

    `term` orijinal (NFC) bicim, `folded` uzunluk-koruyan katlanmis
    bicim (eslestirme bunun uzerinde yapilir), `kind` kaynagi, `core`
    ise bu terimin opak-olmayan id kontrolunde kullanilip
    kullanilmayacagini belirler."""

    term: str
    folded: str
    kind: str


def _clean_term(value):
    if not isinstance(value, str):
        return None
    cleaned = nfc(value).strip()
    return cleaned or None


def _find_suffix_occurrence(folded_term, folded_form):
    """Bir sirket ekinin KELIME SINIRINDA gectigi ilk indeks, yoksa -1.

    KELIME SINIRI ZORUNLUDUR. Aksi halde kisa bicimler kelime ICINDE
    eslesir ve cekirdek ad KATASTROFIK bicimde yanlis cikar:
    `"MARAŞ TEKSTİL A.Ş."` icinde `"AŞ"` 3. indekste ("mar-AŞ") eslesir,
    cekirdek `"MAR"` olur ve "Mart"/"marka" gibi ilgisiz kelimeler
    maskelenir; `"HASAN ÖZ Ltd. Şti."` icinde `"AS"` 1. indekste
    ("h-AS-an") eslesir ve cekirdek `"H"` olur. Ampirik olarak
    dogrulandi ve bu kontrolle kapatildi."""
    start = 0
    while True:
        index = folded_term.find(folded_form, start)
        if index < 0:
            return -1
        end = index + len(folded_form)
        left_ok = index == 0 or not folded_term[index - 1].isalnum()
        right_ok = end >= len(folded_term) or not folded_term[end].isalnum()
        if left_ok and right_ok:
            return index
        start = index + 1


def _company_suffix_variants(term):
    """`term` icinde gecen bir sirket ekini ayni grubun diger
    bicimleriyle degistirerek ek varyantlar uretir."""
    variants = []
    folded_term = fold1to1(term)
    for group in _COMPANY_SUFFIX_GROUPS:
        for form in group:
            index = _find_suffix_occurrence(folded_term, fold1to1(form))
            if index < 0:
                continue
            head = term[:index]
            tail = term[index + len(form):]
            for other in group:
                if other == form:
                    continue
                variants.append(head + other + tail)
            break
    return variants


def _company_core(term):
    """Sirket ekinden ONCEKI cekirdek ad ("ABC Ltd. Şti. - Demo" ->
    "ABC"). Ek yoksa `None`."""
    folded_term = fold1to1(term)
    best = None
    for group in _COMPANY_SUFFIX_GROUPS:
        for form in group:
            index = _find_suffix_occurrence(folded_term, fold1to1(form))
            if index < 0:
                continue
            if best is None or index < best:
                best = index
    if best is None:
        return None
    core = term[:best].strip().strip("-–—,.;:").strip()
    return core or None


def _i_dot_variants(term):
    """Noktalı/noktasiz I varyantlari.

    `fold1to1` Turkce semantigi uygular: `I -> ı`, `İ -> i`. Bu DOGRUDUR
    ama YABANCI/ASCII yazilmis bir terimde recall bosluğu birakir:
    "CLIENT-001" katlaninca `clıent-001` olur, belgedeki "client-001"
    ise `client-001` - ESLESMEZLER. Iki ek varyant bu bosluğu kapatir:
      (a) noktali:  `I -> İ`, `ı -> i`  (katlaninca hep `i`)
      (b) noktasiz: `i -> ı`, `İ -> I`  (katlaninca hep `ı`)
    Ikisi de yalnizca eslesme gucunu ARTIRIR; geri cevirme her zaman
    ORIJINAL metin parcasini saklar, bu yuzden tur kaybi olmaz."""
    dotted = term.replace("I", "İ").replace("ı", "i")
    dotless = term.replace("i", "ı").replace("İ", "I")
    return [variant for variant in (dotted, dotless) if variant != term]


def _expand_variants(term):
    """Bir tohum teriminin TUM varyantlari (kendisi dahil)."""
    variants = [term]
    variants.extend(_company_suffix_variants(term))

    core = _company_core(term)
    if core is not None:
        variants.append(core)

    expanded = []
    for variant in variants:
        for shape in [variant] + _i_dot_variants(variant):
            expanded.append(shape)
            translit = ascii_transliterate(shape)
            if translit != shape:
                expanded.append(translit)
    return expanded


def build_seed_terms(case_data, document_data, extra_terms=()):
    """Deterministik tohum listesi.

    Kaynaklar (bu sirayla): `parties[].display_name` (YALNIZ
    `individual`/`company`), `parties[].reference_code`, case
    `reference_code`, `provenance.original_file_name`,
    `provenance.uploaded_by_ref`, `file.file_name`, operator terimleri.

    Bas harf (initials) URETILMEZ - yanlis-pozitif orani cok yuksektir.
    """
    if not isinstance(case_data, dict):
        case_data = {}
    if not isinstance(document_data, dict):
        document_data = {}

    sources = []

    for party in case_data.get("parties", []) or []:
        if not isinstance(party, dict):
            continue
        if party.get("party_type") in _MASKABLE_PARTY_TYPES:
            name = _clean_term(party.get("display_name"))
            if name is not None:
                sources.append((name, _SEED_KIND_PARTY))

    for party in case_data.get("parties", []) or []:
        if not isinstance(party, dict):
            continue
        reference = _clean_term(party.get("reference_code"))
        if reference is not None:
            sources.append((reference, _SEED_KIND_REFERENCE))

    case_reference = _clean_term(case_data.get("reference_code"))
    if case_reference is not None:
        sources.append((case_reference, _SEED_KIND_REFERENCE))

    provenance = document_data.get("provenance")
    if isinstance(provenance, dict):
        for key in ("original_file_name", "uploaded_by_ref"):
            value = _clean_term(provenance.get(key))
            if value is not None:
                sources.append((value, _SEED_KIND_DOCUMENT_FILE))

    file_block = document_data.get("file")
    if isinstance(file_block, dict):
        value = _clean_term(file_block.get("file_name"))
        if value is not None:
            sources.append((value, _SEED_KIND_DOCUMENT_FILE))

    for raw in extra_terms or ():
        if not isinstance(raw, str):
            raise SeedTermError(MSG_SEED_TERM)
        value = _clean_term(raw)
        if value is None:
            raise SeedTermError(MSG_SEED_TERM)
        sources.append((value, _SEED_KIND_OPERATOR))

    # D4: "bos tohum listesi" = sifir taraf adi VE sifir operator terimi.
    has_party_or_operator = any(
        kind in (_SEED_KIND_PARTY, _SEED_KIND_OPERATOR) for _term, kind in sources
    )
    if not has_party_or_operator:
        raise EmptySeedListError(MSG_EMPTY_SEEDS)

    seeds = []
    seen_folded = set()
    for term, kind in sources:
        if PREFIX_RE.search(term):
            raise SeedTermError(MSG_SEED_TERM)
        for variant in _expand_variants(term):
            variant = nfc(variant).strip()
            if not variant:
                continue
            if PREFIX_RE.search(variant):
                raise SeedTermError(MSG_SEED_TERM)
            folded = fold1to1(variant)
            if len(folded) < _MIN_SEED_VARIANT_LEN:
                continue
            if folded in seen_folded:
                continue
            seen_folded.add(folded)
            seeds.append(SeedTerm(term=variant, folded=folded, kind=kind))

    # EN UZUN ESLESME ONCE - "ABC" ve "ABC Ltd. Sti." birlikte varken
    # uzun olan BOLUNMEMELIDIR.
    seeds.sort(key=lambda seed: (-len(seed.folded), seed.folded))
    return seeds


# ------------------------------------------------------------
# OPAK OLMAYAN KIMLIK KONTROLU (D5)
# ------------------------------------------------------------


def _normalize_for_id_check(value):
    folded = fold1to1(ascii_transliterate(value))
    return "".join(ch for ch in folded if ch.isalnum())


def _id_segments(value):
    parts = re.split(r"[_\-]+", value)
    return [_normalize_for_id_check(part) for part in parts if part]


def assert_identifiers_are_opaque(identifiers, seeds):
    """Bir `case_id`/`party_id`/`document_id` bir taraf adi cekirdegini
    tasiyorsa fail-closed REDDEDER (bkz. D5)."""
    cores = set()
    for seed in seeds:
        if seed.kind not in _ID_CHECK_SEED_KINDS:
            continue
        normalized = _normalize_for_id_check(seed.term)
        if normalized:
            cores.add(normalized)

    for identifier in identifiers:
        if not isinstance(identifier, str) or not identifier.strip():
            continue
        normalized_id = _normalize_for_id_check(identifier)
        segments = set(_id_segments(identifier))
        for core in cores:
            if len(core) >= _MIN_ID_SUBSTRING_CORE_LEN and core in normalized_id:
                raise NonOpaqueIdentifierError(MSG_NON_OPAQUE_ID)
            if len(core) >= _MIN_ID_SEGMENT_CORE_LEN and core in segments:
                raise NonOpaqueIdentifierError(MSG_NON_OPAQUE_ID)


# ------------------------------------------------------------
# ESLESME TABLOSU - YALNIZ BELLEKTE
# ------------------------------------------------------------


class MaskMapping:
    """Token <-> orijinal deger eslesme tablosu.

    YALNIZ BELLEKTE yasar: diske YAZILMAZ, loglanmaz, exception'a
    girmez, hicbir donus sozlugune KONULMAZ. `__repr__`/`__str__`
    yalnizca token sayisini gosterir."""

    __slots__ = (
        "_token_by_value", "_value_by_token", "_class_by_token",
        "_seed_kind_by_token", "_counters", "_midword_party_matches",
    )

    def __init__(self):
        self._token_by_value = {}
        self._value_by_token = {}
        self._class_by_token = {}
        self._seed_kind_by_token = {}
        self._counters = {cls: 0 for cls in ALL_CLASSES}
        self._midword_party_matches = 0

    def note_midword_party_match(self):
        """S2: bir TARAF ADI eslesmesi bir HARFIN HEMEN ONUNDE bitti
        (`Dava Ltd. Şti.` cekirdegi `Davacı` kelimesini boler). Yalniz
        SAYAC - ret DEGIL, deger saklanmaz."""
        self._midword_party_matches += 1

    def midword_party_matches(self):
        return self._midword_party_matches

    def token_for(self, value, token_class, seed_kind=None):
        existing = self._token_by_value.get(value)
        if existing is not None:
            return existing
        self._counters[token_class] += 1
        index = self._counters[token_class]
        if index > _MAX_TOKEN_INDEX:
            raise TokenSpaceExhaustedError(MSG_TOKEN_SPACE)
        token = "%s_%04d%s" % (TOKEN_PREFIX, index, token_class)
        self._token_by_value[value] = token
        self._value_by_token[token] = value
        self._class_by_token[token] = token_class
        self._seed_kind_by_token[token] = seed_kind
        return token

    def seed_kind_of(self, token):
        return self._seed_kind_by_token.get(token)

    def count_tokens_from_seed_kinds(self, kinds):
        return sum(1 for kind in self._seed_kind_by_token.values() if kind in kinds)

    def original_for(self, token):
        """Buyuk/kucuk harf DUYARLI arama - eslesen ama haritada olmayan
        bir token BLOKLANIR."""
        return self._value_by_token.get(token)

    def token_count(self):
        return len(self._value_by_token)

    def tokens(self):
        return tuple(self._value_by_token.keys())

    def class_of(self, token):
        return self._class_by_token.get(token)

    def class_distribution(self):
        distribution = {cls: 0 for cls in ALL_CLASSES}
        for token_class in self._class_by_token.values():
            distribution[token_class] += 1
        return distribution

    def __repr__(self):
        return "<MaskMapping n=%d>" % len(self._value_by_token)

    __str__ = __repr__


# ------------------------------------------------------------
# ADAY TOPLAMA VE TEK GECIS MASKELEME
# ------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    start: int
    length: int
    token_class: str
    value: str
    seed_kind: str | None = None


_word_pattern_cache = {}


def _word_pattern(word):
    """`word`'un HARFLERI arasina R4'un opsiyonel satir-sonu-tire
    koprusu (`_LINE_WRAP_BRIDGE_GROUP`) eklenmis, DERLENMIS regex'i -
    ayni kelime icin sade bir dict ile ONBELLEKLENIR (yeni bir
    onbellekleme araci/import GEREKMEZ - bkz. modul basligi, `re`
    zaten mevcuttur).

    Desen YOKSA (metinde hicbir "tire + gercek satir sonu" GECMIYORSA)
    bu regex, literal ardarda arama ile BIREBIR AYNI ilk pozisyonu
    bulur - her kopru grubu opsiyoneldir (sifir-genislikli eslesir),
    leftmost davranis DEGISMEZ."""
    cached = _word_pattern_cache.get(word)
    if cached is not None:
        return cached
    compiled = re.compile(
        _LINE_WRAP_BRIDGE_GROUP.join(re.escape(ch) for ch in word)
    )
    _word_pattern_cache[word] = compiled
    return compiled


def _find_flexible(folded, words, start):
    """Cok kelimeli bir tohumu, kelimeler arasinda HERHANGI bir bosluk
    DIZISI kabul ederek arar (B1(a)-ii); HER kelimenin KENDI HARFLERI
    ARASINDA da R4'un satir-sonu-tire koprusunu kabul eder.

    Neden: gercek bir unvan belge metninde satir sonu, cift bosluk,
    sekme veya NBSP ile bolunur (repo'nun KENDI fixture'i ~60 karakterde
    sarmalanir). Bu olmadan ad yalnizca REDDEDILIRDI; bununla
    MASKELENIR - operator icin kullanilabilir bir sonuc.

    Konum bulma UZUNLUK KORUYAN `fold1to1` kopyasi uzerindedir, span'lar
    ORIJINAL indekslerdedir ve haritaya ORIJINAL alt dize (ozgun satir
    sonu/cift bosluk/tire dahil) yazilir - geri cevirme BAYT-BAYT kalir.

    R1(ii): AYRAC SINIFI bosluklara EK OLARAK `scan_fold()`'un attigi
    ALTI GORUNMEZ karakteri de kabul eder (U+00AD yumusak tire, U+200B
    ZWSP, U+200C ZWNJ, U+200D ZWJ, U+2060 word joiner, U+FEFF BOM) -
    tek baslarina ya da bosluklarla KARISIK. Boylece ayraci gorunmez
    bir karakter olan cok kelimeli bir ad artik yalnizca REDDEDILMEZ,
    MASKELENIR (geri cevirme yine BAYT-BAYT: haritaya orijinal alt
    dize, gorunmez karakter dahil, yazilir).

    R4 (bu, kelimenin KENDI ICINDE calisir - kelimeler ARASINDA calisan
    yukaridaki bosluk-atlama mantigindan AYRIDIR, o mantik DEGISMEDEN
    kalir): her kelime artik `_word_pattern()` ile, literal degil,
    HARFLERI arasina R4'un opsiyonel tire+gercek-satir-sonu koprusu
    eklenmis bir regex ile aranir. Boylece TEK kelimelik bir tohumun
    (`"Ahmet"`) veya cok kelimelik bir tohumun TEK bir kelimesinin
    (`"Ahmet Yılmaz"`'daki `"Ahmet"` veya `"Yılmaz"`) kendi ICINDE PDF
    hyphenation/line-wrap ile bolunmus olmasi da artik MASKELENIR -
    onceden bu durum ne maskeleniyor ne reddediliyordu (TAMAMEN
    sessizdi). Kopru YOKSA regex literal ardarda arama ile BIREBIR AYNI
    davranir (opsiyonel gruplar sifir-genislikli eslesir, leftmost
    davranis DEGISMEZ).

    Kelime ICINDE gizlenmis GORUNMEZ karakterler (ZWSP/ZWNJ/ZWJ/BOM/word
    joiner/yumusak tire) HALA maskelenmez ve `scan_fold()` backstop'u
    tarafindan FAIL-CLOSED REDDEDILIR - bu ayrim BILINCLIDIR; R4 YALNIZ
    gercek ASCII tire + gercek satir sonu desenini kapsar."""
    first_pattern = _word_pattern(words[0])
    match = first_pattern.search(folded, start)
    while match is not None:
        index = match.start()
        position = match.end()
        matched = True
        for word in words[1:]:
            cursor = position
            while cursor < len(folded) and (
                folded[cursor].isspace() or folded[cursor] in _SCAN_DROP_CHARS
            ):
                cursor += 1
            if cursor == position:
                matched = False
                break
            word_match = _word_pattern(word).match(folded, cursor)
            if word_match is None:
                matched = False
                break
            position = word_match.end()
        if matched:
            return index, position
        match = first_pattern.search(folded, index + 1)
    return None


def _collect_candidates(segment, base, seeds):
    """Bir TOKEN OLMAYAN segment icindeki tum aday span'lar.

    Konum bulma katlanmis metinde, deger cikarma ORIJINAL metinde."""
    candidates = []
    folded = fold1to1(segment)

    for seed in seeds:
        words = seed.folded.split()
        if not words:
            continue
        start = 0
        while True:
            found = _find_flexible(folded, words, start)
            if found is None:
                break
            span_start, span_end = found
            candidates.append(
                _Candidate(
                    start=base + span_start,
                    length=span_end - span_start,
                    token_class=CLASS_PARTY,
                    value=segment[span_start:span_end],
                    seed_kind=seed.kind,
                )
            )
            start = span_start + 1

    for pattern, token_class in (
        (_EMAIL_RE, CLASS_EMAIL),
        (_PHONE_RE, CLASS_PHONE),
        (_DIGIT_RUN_11_RE, CLASS_TCKN),
        (_DIGIT_RUN_10_RE, CLASS_VKN),
    ):
        for match in pattern.finditer(segment):
            candidates.append(
                _Candidate(
                    start=base + match.start(),
                    length=len(match.group(0)),
                    token_class=token_class,
                    value=match.group(0),
                )
            )

    for match in _IBAN_RE.finditer(segment):
        raw = match.group(0)
        if not tr_iban_is_valid(raw):
            continue
        candidates.append(
            _Candidate(
                start=base + match.start(),
                length=len(raw),
                token_class=CLASS_IBAN,
                value=raw,
            )
        )

    return candidates


def _token_segments(text):
    """(is_token, start, end) uclulerinin listesi. Fixpoint yeniden
    taramasi YERLESTIRILMIS TOKEN'LARIN ICINE BAKMAZ (D2)."""
    segments = []
    position = 0
    for match in TOKEN_RE.finditer(text):
        if match.start() > position:
            segments.append((False, position, match.start()))
        segments.append((True, match.start(), match.end()))
        position = match.end()
    if position < len(text):
        segments.append((False, position, len(text)))
    if not segments:
        segments.append((False, 0, len(text)))
    return segments


def _mask_once(text, seeds, mapping):
    """Tek gecis. (yeni_metin, yerlestirilen_token_sayisi) dondurur."""
    candidates = []
    for is_token, start, end in _token_segments(text):
        if is_token:
            continue
        candidates.extend(_collect_candidates(text[start:end], start, seeds))

    if not candidates:
        return text, 0

    candidates.sort(
        key=lambda c: (c.start, -c.length, _CLASS_PRIORITY[c.token_class])
    )

    chosen = []
    next_free = 0
    for candidate in candidates:
        if candidate.start < next_free:
            continue
        chosen.append(candidate)
        next_free = candidate.start + candidate.length

    # Token'lar ARTAN metin sirasinda atanir (numaralandirma ilk gorulme
    # sirasina gore olsun diye), degistirme SONDAN yapilir (indeksler
    # kaymasin diye).
    placements = []
    for candidate in chosen:
        # S2: taraf-adi eslesmesi bir HARFIN hemen onunde mi bitiyor?
        if candidate.token_class == CLASS_PARTY:
            after = candidate.start + candidate.length
            if after < len(text) and text[after].isalpha():
                mapping.note_midword_party_match()
        placements.append((
            candidate.start,
            candidate.length,
            mapping.token_for(candidate.value, candidate.token_class, candidate.seed_kind),
        ))

    out = text
    for start, length, token in reversed(placements):
        out = out[:start] + token + out[start + length:]

    return out, len(placements)


def mask_text(text, seeds, mapping):
    """Metni FIXPOINT'e kadar maskeler.

    Tek gecis yetmez: bir ad span'i, ADIN ICINDEN baslayan bir e-posta
    span'ini leftmost-longest kurali yuzunden dusurebilir ve e-posta
    maskelenmeden hayatta kalir (Rapor C §4.5'te ampirik olarak
    gosterildi). Yeniden tarama, yerlestirilmis token'larin ICINE
    bakmadan yapilir (D2)."""
    current = text
    for _ in range(_MAX_MASK_PASSES):
        current, placed = _mask_once(current, seeds, mapping)
        if placed == 0:
            return current
    raise MaskingFixpointError(MSG_FIXPOINT)


_MASKABLE_CONTEXT_FIELDS = ("source_document_title", "source_actor_label")
_MASKABLE_PARTY_FIELD = "display_name"


# S1: KORUNAN (maskelenmeyen) KIMLIK anahtarlari. Attribution
# (`build_party_map`, `normalize_attribution`, `filter_allowed_ids`)
# ve `document_reference_resolver` BUNLARA BAGIMLIDIR; maskelenirlerse
# model gecerli bir `attributed_party_id` uretemez. Bir tohum adinin
# BIR ID ICINDE gecmesi AYRI ve fail-closed bir kuralla
# (`assert_identifiers_are_opaque()`) reddedilir.
_PROTECTED_CONTEXT_ID_KEYS = frozenset({
    "case_id",
    "source_document_id",
    "source_document_issuer_party_id",
    "party_id",
    "dispute_item_id",
})


def _walk_context_strings(node, key, sink):
    if isinstance(node, str):
        if key not in _PROTECTED_CONTEXT_ID_KEYS:
            sink.append(node)
        return
    if isinstance(node, dict):
        for child_key, child in node.items():
            _walk_context_strings(child, child_key, sink)
        return
    if isinstance(node, list):
        for item in node:
            _walk_context_strings(item, key, sink)


def masked_context_text_regions(masked_context):
    """`mask_context()`'in fiilen MASKELEDIGI TUM string yapraklari.
    `scan_outbound()`'un tohum taramasi TAM OLARAK bu kumeyi kullanir -
    yalnizca korunan KIMLIK alanlari disarida kalir."""
    regions = []
    if not isinstance(masked_context, dict):
        return regions
    _walk_context_strings(masked_context, None, regions)
    return regions


def _mask_context_node(node, key, seeds, mapping):
    if isinstance(node, str):
        if key in _PROTECTED_CONTEXT_ID_KEYS:
            return node
        return mask_text(node, seeds, mapping)
    if isinstance(node, dict):
        return {
            child_key: _mask_context_node(child, child_key, seeds, mapping)
            for child_key, child in node.items()
        }
    if isinstance(node, list):
        return [_mask_context_node(item, key, seeds, mapping) for item in node]
    return node


def mask_context(context, seeds, mapping):
    """Context'in DERIN KOPYASINI maskeler; orijinal DOKUNULMAZ.

    S1 DUZELTMESI: artik korunan KIMLIK anahtarlari DISINDAKI HER string
    YAPRAK maskelenir - yalnizca `source_document_title`/
    `source_actor_label`/`parties[].display_name` degil. Onceki dar
    kume, `source_document_type`, `source_document_subtype` ve
    `dispute_items[].tax_type` uzerinden bir taraf adinin LLM'e
    ulasmasina izin veriyordu (bagimsiz incelemenin A5 probe'u ucunu de
    sizdirdi). Bu alanlar semada SERBEST STRING'dir (enum DEGIL), yani
    yapisal bir garanti YOKTU.

    Maskeleme yalnizca TOHUM/KIMLIK ESLESMELERINI degistirir - bir
    yaprakta eslesme yoksa deger AYNEN kalir, dolayisiyla enum/period/
    yasal-dayanak degerleri normal kosulda DEGISMEZ.

    Yapraklar context'in KENDI anahtar sirasinda ziyaret edilir; token
    numaralandirmasi bu yuzden deterministiktir (D1)."""
    return _mask_context_node(copy.deepcopy(context), None, seeds, mapping)


# ------------------------------------------------------------
# MODEL-YONELIMLI TOKEN TALIMAT BLOGU (D6)
# ------------------------------------------------------------

# DIKKAT: burada SOMUT bir ornek token YAZILMAZ. Yazilsaydi, model onu
# aynen yansittiginda haritada bulunmayan bir token olarak REDDEDILIRDI.
# Ayrica bu blok giden tarama (`scan_outbound`) icinden gecer, bu yuzden
# 10/11 haneli rakam dizisi, e-posta veya telefon bicimi ICERMEZ.
_TOKEN_INSTRUCTION_BLOCK = """

GIZLILIK TOKEN KURALI
=====================

Yukaridaki case context ve belge metninde bazi kisisel/kurumsal
tanimlayicilar gecici takma ad token'lariyla degistirilmistir.

Token bicimi: VGMASK_ onekinden sonra dort rakam ve tek bir buyuk harf.

Bu token'lari cevabinda AYNEN, harfi harfine kopyala.
Token'i cevirme, acma, kisaltma, buyuk/kucuk harfini degistirme,
rakam ekleme veya cikarma, baska bir token'la birlestirme ya da bolme.
Bir token'in hemen ardina fazladan karakter yazma.
Token'in arkasindaki gercek degeri tahmin etmeye calisma.
Token'i bir JSON anahtari olarak kullanma.
"""


def token_instruction_block():
    """USER prompt'un SONUNA eklenecek sabit talimat blogu.
    `SYSTEM_PROMPT` DEGISMEZ."""
    return _TOKEN_INSTRUCTION_BLOCK


# ------------------------------------------------------------
# MASKELEME SONUCU
# ------------------------------------------------------------


@dataclass
class MaskingResult:
    """Maskeleme adiminin sonucu.

    `mapping` alani YALNIZ cagiran fonksiyonun frame'inde yasamalidir -
    `build_fact_extraction()`'in DONUS SOZLUGUNE, bir pending
    artefaktina, bir audit kaydina, bir loga veya bir exception'a ASLA
    KONULMAZ."""

    masked_text: str
    masked_context: dict
    prompt_instruction_block: str
    mapping: MaskMapping
    seeds: tuple = ()
    summary: dict = field(default_factory=dict)

    def __repr__(self):
        return "<MaskingResult tokens=%d>" % self.mapping.token_count()

    __str__ = __repr__


def _class_distribution_public(mapping):
    return dict(mapping.class_distribution())


def _possible_over_masking(original_text, mapping):
    """Onizleme icin "olasi asiri maskeleme" gostergeleri.

    ASLA deger dondurmez - yalnizca SAYAC.

    `reference_or_filename_seed_matches`: referans kodu / dosya adi
    tohumundan turemis token sayisi. Bunlar GERCEK ve gozlemlenmis bir
    asiri maskeleme kaynagidir - ornegin `case_0001`'de case
    `reference_code` "DEMO-2026-001", belge metnindeki
    "IHB-DEMO-2026-001" ihbarname numarasinin ICINDE gecer ve numara
    "IHB-<token>" hâline gelir. Geri cevrilebilir oldugu icin butunluk
    kaybi YOKTUR, ama modelin belge numarasini `reference` structured
    value olarak cikarma kalitesi DUSEBILIR (`SYSTEM_PROMPT` bunu
    ister). Avukat bunu onizlemede gorur."""
    vkn_without_context = 0
    tckn_checksum_failed = 0
    vkn_checksum_failed = 0

    for match in _DIGIT_RUN_10_RE.finditer(original_text):
        window_start = max(0, match.start() - _VKN_CONTEXT_WINDOW)
        window = original_text[window_start:match.start()]
        if not _VKN_CONTEXT_RE.search(window):
            vkn_without_context += 1
        if not vkn_is_valid(match.group(0)):
            vkn_checksum_failed += 1

    for match in _DIGIT_RUN_11_RE.finditer(original_text):
        if not tckn_is_valid(match.group(0)):
            tckn_checksum_failed += 1

    return {
        "vkn_without_context_word": vkn_without_context,
        "vkn_checksum_failed": vkn_checksum_failed,
        "tckn_checksum_failed": tckn_checksum_failed,
        "reference_or_filename_seed_matches": mapping.count_tokens_from_seed_kinds(
            (_SEED_KIND_REFERENCE, _SEED_KIND_DOCUMENT_FILE)
        ),
        # S2: tek kelimelik bir sirket cekirdegi siradan Turkce
        # kelimeleri bolebilir (`Dava Ltd. Şti.` -> `Davacı`). Geri
        # cevrilebilir oldugu icin butunluk kaybi YOK, ama modelin
        # anlamasi zayiflar - avukat bunu onizlemede gormelidir.
        "party_name_midword_matches": mapping.midword_party_matches(),
    }


def mask_prompt_inputs(
    *,
    case_data,
    document_data,
    context,
    document_text,
    extra_terms=(),
):
    """Prompt'un IKI girdisini (context + belge metni) AYNI haritayla
    maskeler.

    SIRA (D1): once fail-closed on kontroller, sonra context (kendi
    anahtar sirasinda), sonra belge metni. Boylece token numaralari
    deterministik ve tekrar edilebilirdir.

    Orijinal `context` ve `document_text` DEGISTIRILMEZ - `context`'in
    derin kopyasi maskelenir."""
    if not isinstance(document_text, str):
        raise SeedTermError(MSG_SEED_TERM)

    seeds = build_seed_terms(case_data, document_data, extra_terms)

    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)

    # --- fail-closed on kontroller (prompt HIC uretilmeden) ---
    for probe in (document_text, context_json):
        if PREFIX_RE.search(probe):
            raise MaskCollisionError(MSG_COLLISION)
        if has_non_ascii_digits(probe):
            raise NonAsciiDigitError(MSG_NON_ASCII_DIGIT)

    if find_unresolvable_zero_width_digit_runs(document_text):
        raise ZeroWidthDigitRunError(MSG_ZERO_WIDTH_DIGIT_RUN)

    # R2: `source_document_issuer_party_id` KORUNAN (maskelenmeyen) bir
    # kimliktir ve backstop'un taradigi bolgelere de GIRMEZ - bu yuzden
    # opaklik kontrolune AYRICA eklenmek ZORUNDADIR. Aksi halde BIREBIR
    # AYNI dize `party_id` konumunda fail-closed reddedilirken
    # `issuer_party_id` konumunda SESSIZCE gonderiliyordu (modulun kendi
    # sozlesmesiyle ic tutarsizlik). Row 3 onayli veride bu deger zaten
    # bir `parties[].party_id`'ye esittir (FK), yani regresyon riski
    # YOKTUR; yalniz FK'siz/elle duzenlenmis veri reddedilmeye baslar.
    identifiers = [
        context.get("case_id"),
        context.get("source_document_id"),
        context.get("source_document_issuer_party_id"),
    ]
    for party in context.get("parties", []) or []:
        if isinstance(party, dict):
            identifiers.append(party.get("party_id"))
    for item in context.get("dispute_items", []) or []:
        if isinstance(item, dict):
            identifiers.append(item.get("dispute_item_id"))
    assert_identifiers_are_opaque(identifiers, seeds)

    mapping = MaskMapping()

    masked_context = mask_context(context, seeds, mapping)
    masked_text = mask_text(document_text, seeds, mapping)

    summary = {
        "masking_policy_version": MASKING_POLICY_VERSION,
        "token_count": mapping.token_count(),
        "class_distribution": _class_distribution_public(mapping),
        "possible_over_masking": _possible_over_masking(document_text, mapping),
        # Karar b2: BILGI AMACLI, ret URETMEZ (bkz.
        # `count_possible_split_identifiers`).
        "possible_split_identifier": count_possible_split_identifiers_outside_tokens(
            masked_text
        ),
        # R1(iii): squeeze-only tohum isabeti - BILGI AMACLI, ret YOK.
        "possible_squeeze_seed_match": count_squeeze_only_seed_matches(
            [masked_text] + masked_context_text_regions(masked_context),
            seeds,
        ),
        "original_text_chars": len(document_text),
        "masked_text_chars": len(masked_text),
    }

    return MaskingResult(
        masked_text=masked_text,
        masked_context=masked_context,
        prompt_instruction_block=token_instruction_block(),
        mapping=mapping,
        seeds=tuple(seeds),
        summary=summary,
    )


# ------------------------------------------------------------
# GIDEN (OUTBOUND) TARAMA
# ------------------------------------------------------------


def _scan_region_for_seeds(region, seeds):
    """Backstop - `scan_fold()` ile MASKELEYICIDEN BAGIMSIZ karsilastirir
    (B1(a)-i). Maskeleyici bir adi kacirirsa burada YAKALANIR.

    R1(iii): YALNIZ `scan_fold` isabeti REDDEDER. `scan_squeeze` isabeti
    (bkz. `count_squeeze_only_seed_matches`) ARTIK RET DEGILDIR -
    onizleme sayacina indirilmistir."""
    for is_token, start, end in _token_segments(region):
        if is_token:
            continue
        folded = scan_fold(region[start:end])
        for seed in seeds:
            if scan_fold(seed.term) in folded:
                raise SurvivingPatternError(MSG_SURVIVING_NORMALISED)


def count_squeeze_only_seed_matches(regions, seeds):
    """R1(iii) BILGI AMACLI SAYAC - HICBIR RET URETMEZ.

    `scan_squeeze` formunda gorunen ama `scan_fold` formunda GORUNMEYEN
    tohum isabetlerini sayar. Boyle bir isabet neredeyse her zaman bir
    BIRLESME ARTEFAKTIDIR: squeeze TUM bosluklari attigi icin bolgedeki
    AYRI kelimeler birlesir ve kisa bir tohum ortada eslesir
    ("BASKANLIGINA" + "DAVA" -> "...naDAva..." icinde 'ada').

    NEDEN RET DEGIL (b2 emsali): bagimsiz inceleme GERCEK repo fixture
    metinleriyle olctu - 83 makul tek kelimelik cekirdek x 3 gercek
    metin = 249 kombinasyonun 25'i (yaklasik %10) HAKSIZ RET aliyordu ve
    operatorun HICBIR caresi yoktu: terimi cikarmak da, baska bir terim
    eklemek de, belgeyi temizlemek de kurtarmiyordu (cekirdek
    `case.json`'daki `display_name`'den turuyorsa terim hic
    cikarilamaz). Bir UZUNLUK KAPISI da olcumle CURUTULDU: squeeze'e
    ozgu L-gram sayisi uzunlukla AZALMIYOR, ARTIYOR.

    VAZGECILEN SINIF (acikca): TEK kelimelik bir tohumun ORTASINA duz
    bir bosluk veya satir sonu sokulmus olmasi (harf araligi verilmis
    metin) ARTIK REDDEDILMEZ, yalnizca SAYILIR. Cok kelimeli adlarin
    gorunmez-karakter ayracli hali ise R1(ii) ile MASKELENIR, yani bu
    turda squeeze'e artik ihtiyac duymaz.

    R4-F1 (bagimsiz inceleme, Bulgu F1 - IKI BAGIMSIZ squeeze
    karsilastirmasi, VEYA mantigi): her seed icin HEM mevcut (R4, tire+
    satir-sonu SILINMIS) `scan_squeeze()` HEM `_scan_squeeze_
    preserve_linewrap_hyphen()` (R4-ONCESI davranisin BIREBIR AYNISI,
    tire+satir-sonu SILINMEDEN) ile ayri ayri karsilastirilir -
    IKISINDEN HERHANGI BIRI eslesirse `hits` artar. Boylece seed'in
    KENDI gercek tiresinin (`"Ali-Mehmet"`) PDF satir-sarma noktasina
    tesaduf ettigi durumda (`"Ali-\\nMehmet"`) R4-ONCESI TUTAN isabet
    (`_scan_squeeze_preserve_linewrap_hyphen` yolu) SESSIZCE
    kaybolmuyor - `scan_fold()`'un R4 silme adiminin bu isabeti neden
    SIFIRLADIGI icin bkz. `_scan_fold_preserve_linewrap_hyphen()`
    docstring'i. Desen (tire+GERCEK satir-sonu) ICERMEYEN metin/tohum
    ciftlerinde iki varyant BIREBIR AYNI degeri urettigi icin (bkz.
    `_LINE_WRAP_HYPHEN_RE` - eslesecek desen yoksa `.sub("", ...)` bir
    no-op'tur) bu ekleme HICBIR mevcut sayimi DEGISTIRMEZ; yalniz bu
    fonksiyonun KENDISI etkilenir - maskeleme/ret kararlari (`mask_text`,
    `_scan_region_for_seeds`) DEGISMEDEN kalir."""
    hits = 0
    for region in regions:
        for is_token, start, end in _token_segments(region):
            if is_token:
                continue
            segment = region[start:end]
            folded = scan_fold(segment)
            squeezed = scan_squeeze(segment)
            squeezed_preserve = _scan_squeeze_preserve_linewrap_hyphen(segment)
            for seed in seeds:
                if scan_fold(seed.term) in folded:
                    continue
                seed_squeezed = scan_squeeze(seed.term)
                seed_squeezed_preserve = _scan_squeeze_preserve_linewrap_hyphen(seed.term)
                if seed_squeezed in squeezed or seed_squeezed_preserve in squeezed_preserve:
                    hits += 1
    return hits


def scan_outbound(prompt, result):
    """Giden prompt'ta hayatta kalan bilinen desen var mi?

    IKI FARKLI KAPSAM - bilincli:

    (1) KIMLIK DESENLERI (TCKN/VKN/IBAN/telefon/e-posta), ASCII olmayan
        rakam ve sifir genislikli rakam dizisi: PROMPT'UN TAMAMI
        taranir. Bunlar guclu, genel bir agdir ve sabit sablon metninde
        zaten hic bulunmaz.

    (2) TOHUM ADLARI: YALNIZ maskelemenin fiilen UZERINDE CALISTIGI
        metin taranir - maskeli belge metni ve `mask_context()`'in
        maskeledigi UC alan (`source_document_title`,
        `source_actor_label`, `parties[].display_name`). Sabit prompt
        sablonu, talimat blogu ve maskelenmeyen context alanlari
        (`case_id`, `*_id`, `source_document_type` gibi ENUM'lar,
        `tax_type`, `period`, `asserted_legal_basis_refs`) DISARIDA
        birakilir.

        GEREKCE (ampirik): `build_user_prompt`'in DEGISMEZ TASK metni
        "Kaynak belgeden...", "Belge turunu...", "Dava dilekcesindeki...",
        "Vergi Inceleme Raporundaki...", "...Rapor..." kelimelerini
        icerir. Tek kelimelik bir sirket adi (`Kaynak A.Ş.`, `Demo A.Ş.`,
        `Dava Ltd. Şti.`, `Vergi A.Ş.`, `Rapor Ltd. Şti.`) bu kelimeyi
        bir cekirdek tohum olarak turetir; maskeleme degisken metindeki
        HER gecisini yerine koyar, ama tarama sabit sablonda o kelimeyi
        bulup `SurvivingPatternError` firlatirdi. Operator bunu
        `--mask-term` ile DUZELTEMEZ (o yalnizca tohum EKLER), yani
        dosya yaniltici bir mesajla KALICI olarak islenemez hale
        gelirdi. Bes ad icin bu ampirik olarak dogrulandi. AYNI sinif,
        maskelenmeyen bir context ENUM'u icinde de gerceklesir
        (`Dava Ltd. Şti.` -> cekirdek "dava" -> `source_document_type:
        "dava_dilekcesi"`), bu yuzden tum context JSON'u degil YALNIZ
        maskelenen UC alan taranir.

        Bu daraltma kapsami ZAYIFLATMAZ, DOGRULAR: prompt'ta case
        verisinden turetilen SERBEST METIN yalnizca bu bolgelerdir;
        geri kalani ya bu repository'nin kendi sabiti ya da bilincli
        olarak maskelenmeyen, yuk tasiyan kimlik/enum alanlaridir (bir
        tohum adinin ID icinde gecmesi AYRI bir kuralla -
        `assert_identifiers_are_opaque()` - zaten fail-closed
        reddedilir). Maskeleme fixpoint'e kadar kostugu icin bu
        bolgelerde hayatta kalan bir tohum GERCEK bir kacaktir ve hala
        FAIL-CLOSED reddedilir.

    Talimat blogundaki cıplak `VGMASK_` oneki BIR HATA DEGILDIR ve
    burada kontrol EDILMEZ."""
    if not isinstance(prompt, str):
        raise SurvivingPatternError(MSG_SURVIVING)

    if has_non_ascii_digits(prompt):
        raise NonAsciiDigitError(MSG_NON_ASCII_DIGIT)

    if find_unresolvable_zero_width_digit_runs(prompt):
        raise ZeroWidthDigitRunError(MSG_ZERO_WIDTH_DIGIT_RUN)

    for is_token, start, end in _token_segments(prompt):
        if is_token:
            continue
        segment = prompt[start:end]

        for pattern in (_EMAIL_RE, _PHONE_RE, _DIGIT_RUN_11_RE, _DIGIT_RUN_10_RE):
            if pattern.search(segment):
                raise SurvivingPatternError(MSG_SURVIVING)

        for match in _IBAN_RE.finditer(segment):
            if tr_iban_is_valid(match.group(0)):
                raise SurvivingPatternError(MSG_SURVIVING)

    if isinstance(result, MaskingResult):
        seeds = result.seeds
        regions = [result.masked_text]
        regions.extend(masked_context_text_regions(result.masked_context))
    else:
        # Dusuk seviyeli kullanim (izole testler): `result` duz bir
        # tohum dizisidir ve `prompt` zaten yalnizca maskeli metindir.
        seeds = tuple(result)
        regions = (prompt,)

    for region in regions:
        _scan_region_for_seeds(region, seeds)


def assert_masked_length_within(masked_text, limit):
    """Maskelenmis metin `limit` karakteri asiyorsa fail-closed REDDEDER.

    Bu, `load_text()` icindeki HAM metin kontrolune EK bir kontroldur -
    onun YERINE GECMEZ. Maskelenmis metin ORIJINALDEN UZUN olabilir
    (`VGMASK_0001E` kisa bir e-postanin yerini alir), bu yuzden ham
    kontrolu gecen bir belge burada reddedilebilir."""
    if len(masked_text) > limit:
        raise MaskedInputTooLongError(MSG_MASKED_TOO_LONG)


# ------------------------------------------------------------
# DONUS YOLU (RETURN PATH)
# ------------------------------------------------------------


def _resolve_mapping(mapping_or_result):
    if isinstance(mapping_or_result, MaskingResult):
        return mapping_or_result.mapping
    return mapping_or_result


def _de_mask_string(text, mapping):
    """Tek bir string'i geri cevirir.

    IKI BAGIMSIZ KONTROL:
      (a) `VGMASK` onegi buyuk/kucuk harf DUYARSIZ sayilir;
      (b) tam kurallı token'lar buyuk/kucuk harf DUYARLI eslestirilir.
    Iki sayi esit degilse bozuk/kesik/harf-degismis bir token vardir ->
    FAIL-CLOSED."""
    prefix_hits = len(PREFIX_RE.findall(text))
    if prefix_hits == 0:
        return text

    matched = 0

    def _replace(match):
        nonlocal matched
        token = match.group(0)
        value = mapping.original_for(token)
        if value is None:
            raise UnknownTokenError(MSG_UNKNOWN_TOKEN)
        matched += 1
        return value

    out = TOKEN_RE.sub(_replace, text)

    if matched != prefix_hits:
        raise MalformedTokenError(MSG_MALFORMED_TOKEN)

    return out


def de_mask_tree(obj, mapping_or_result):
    """`json.loads()` SONRASI, ayristirilmis agac uzerinde geri cevirme.

    HAM string uzerinde yapilmaz: icinde `"` veya `\\` olan bir ad
    JSON'u bozar (Rapor C §5.5, ampirik).

    Dict DEGERLERI ve liste elemanlari cozulur. Bir ANAHTAR konumunda
    token gorulurse bu sema-disi bir model davranisidir -> de-mask
    EDILMEZ, fail-closed REDDEDILIR."""
    mapping = _resolve_mapping(mapping_or_result)

    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if isinstance(key, str) and PREFIX_RE.search(key):
                raise TokenInKeyError(MSG_TOKEN_IN_KEY)
            out[key] = de_mask_tree(value, mapping)
        return out

    if isinstance(obj, list):
        return [de_mask_tree(item, mapping) for item in obj]

    if isinstance(obj, str):
        return _de_mask_string(obj, mapping)

    return obj


def _walk_strings(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str):
                yield key
            yield from _walk_strings(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_strings(item)
    elif isinstance(obj, str):
        yield obj


def assert_no_tokens_remain(obj, mapping_or_result=None):
    """Geri cevirme SONRASI bagimsiz artik-token taramasi.

    Onek buyuk/kucuk harf DUYARSIZ aranir - harf-degismis bir token da
    yakalanir."""
    for text in _walk_strings(obj):
        if PREFIX_RE.search(text):
            raise ResidualTokenError(MSG_RESIDUAL_TOKEN)


def count_dropped_tokens(obj, mapping_or_result):
    """Haritadaki KAC token modelin cevabinda HIC gorunmedi? (D3)

    BU BIR RET SEBEBI DEGILDIR - dusen bir token sizinti degil, kalite
    kaybidir. Yalnizca SAYAC dondurur; token ya da deger DONDURMEZ.
    Geri cevirmeden ONCE, ham (maskeli) agac uzerinde cagrilmalidir."""
    mapping = _resolve_mapping(mapping_or_result)

    present = set()
    for text in _walk_strings(obj):
        for match in TOKEN_RE.finditer(text):
            present.add(match.group(0))

    by_class = {cls: 0 for cls in ALL_CLASSES}
    dropped = 0
    for token in mapping.tokens():
        if token in present:
            continue
        dropped += 1
        token_class = mapping.class_of(token)
        if token_class in by_class:
            by_class[token_class] += 1

    return {"dropped_token_count": dropped, "dropped_by_class": by_class}


# ------------------------------------------------------------
# OPERATOR EK TERIM DIGEST'I (identity payload uyesi)
# ------------------------------------------------------------


def compute_extra_terms_digest(terms):
    """Operatorun `--mask-term` listesinin kanonik sha256'si.

    Kanonlastirma: NFC -> `strip()` -> bos olanlari at -> tekillestir ->
    sirala -> `json.dumps(..., ensure_ascii=False, sort_keys=True,
    separators=(",", ":"))` -> sha256 hex.

    BOS LISTE OZEL DURUM DEGILDIR: `[]` ayni formulden gecer ve HER ZAMAN
    ayni sabit digest'i uretir
    (`sha256(b"[]")` = 4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945).

    ASLA terimlerin KENDISINI dondurmez."""
    cleaned = set()
    for raw in terms or ():
        if not isinstance(raw, str):
            raise SeedTermError(MSG_SEED_TERM)
        value = nfc(raw).strip()
        if value:
            cleaned.add(value)
    canonical = json.dumps(
        sorted(cleaned), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


EMPTY_EXTRA_TERMS_DIGEST = compute_extra_terms_digest(())
