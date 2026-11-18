# ============================================================
# VERGİ AI - BÜRO MODELİ / T1 - ÜÇ KAYIT (KAPALI ŞEMALAR)
#
#   1. Pilot test sonucu  : yazılım sürümü, UYUMLU/UYUSMAZLIK,
#                           kontrol türü, (yalnız UYUSMAZLIK'ta) kapalı
#                           listeden hata kategorisi.
#   2. İmha kaydı         : işlem zamanı, kopya TÜRÜ, adet, yöntem, sonuç.
#   3. Geliştirici desteği: YALNIZ üç alan (sürüm, işlem adımı, hata
#                           kodu VEYA hata kategorisi). EKRANDA gösterilir;
#                           yazılım HİÇBİR ŞEY göndermez.
#
# KURALLAR: serbest metin yok; gerçek tarih/dosya no/alıntı/belge adı/
# HASH/yol/kullanıcı-makine adı/koşu-vaka kimliği hiçbir kayda GİRMEZ.
# Bu modül `kayitlar/` altındaki hiçbir dosyayı SİLMEZ veya BUDAMAZ ve
# hiçbir saklama süresi uygulamaz (imha kaydı için "en az üç yıl"
# belgelerde yazılıdır; kodda süre mantığı YOKTUR).
#
# Ağ/LLM/alt süreç import'u yok.
# ============================================================

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from ui.services.office_flow_records import (
    COPY_TYPES, ERROR_CATEGORIES, ERROR_CODES, PROCESS_STEPS, RECORD_SCHEMA_VERSION,
    SOFTWARE_VERSION, OfficeFlowError, canonical_bytes, write_new_file,
)

RESULTS = ("UYUMLU", "UYUSMAZLIK")
CONTROL_KINDS = ("ILK_KONTROL", "YENIDEN_KONTROL")
IMHA_STAGES = ("BASLADI", "SONUC")
IMHA_RESULTS = ("TAMAMLANDI", "KISMEN", "REDDEDILDI")
IMHA_ITEM_RESULTS = ("TAMAMLANDI", "KISMEN", "REDDEDILDI", "PLANLANDI")
IMHA_METHOD = "DOSYA_SISTEMI_SILME"
IMHA_SCOPE = "YALNIZ_PILOT_KOPYALARI"
IMHA_NOT_DELETED = ("VERITABANI_ISLEM_KAYITLARI",)

# Sabit cümleler (rapor/kayıt metinlerinde birebir kullanılır).
CLOSURE_NOT_PROOF_SENTENCE = (
    "İncelemenin kapatılması, hesabın doğru bulunduğu anlamına gelmez."
)
CATEGORY_NOT_FINDING_SENTENCE = (
    "Hata kategorisi avukatın sınıflamasıdır; hukuki tespit veya yazılımın çıkarımı değildir."
)

_TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")

# İçerik koruması: serbest/sızıntı olabilecek HERHANGİ bir dizge reddedilir.
_FORBIDDEN_RES = (
    re.compile(r"[0-9]{1,4}[./-][0-9]{1,2}[./-][0-9]{1,4}"),   # tarih
    re.compile(r"[0-9a-fA-F]{24,}"),                            # hash benzeri
    re.compile(r"[A-Za-z]:[\\/]"),                              # sürücü yolu
    re.compile(r"[\\/]"),                                       # yol ayracı
    re.compile(r"@"),                                           # e-posta
    re.compile(r"[0-9]{6,}"),                                   # uzun sayı (no/TCKN)
    re.compile(r"\.pdf\b", re.IGNORECASE),                      # dosya adı
)


def _assert_clean_string(value: str) -> None:
    for pattern in _FORBIDDEN_RES:
        if pattern.search(value):
            raise OfficeFlowError("KAYIT_ICERIK_RED")


def _scan_values(obj, *, skip_keys=("islem_zamani",)) -> None:
    """Kapalı kümeye ait olmayan HER dizgeyi tara (enum değerleri zaten
    önceden doğrulanmıştır; yine de savunma derinliği olarak hepsi taranır)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in skip_keys:
                continue
            _scan_values(value, skip_keys=skip_keys)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _scan_values(item, skip_keys=skip_keys)
    elif isinstance(obj, str):
        _assert_clean_string(obj)


def utc_timestamp(now=None) -> str:
    moment = now or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------
# 1. Pilot test sonucu
# ----------------------------------------------------------------

TEST_RESULT_KEYS = ("kayit_surumu", "yazilim_surumu", "sonuc", "kontrol_turu", "hata_kategorisi")


def build_test_result(*, sonuc: str, kontrol_turu: str, hata_kategorisi=None) -> dict:
    """Kapalı şema. `hata_kategorisi` YALNIZ UYUSMAZLIK'ta bulunur (UYUMLU'da
    anahtar HİÇ yoktur). Süre/zaman/kimlik alanı YOKTUR."""
    if sonuc not in RESULTS or kontrol_turu not in CONTROL_KINDS:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    record = {
        "kayit_surumu": RECORD_SCHEMA_VERSION,
        "yazilim_surumu": SOFTWARE_VERSION,
        "sonuc": sonuc,
        "kontrol_turu": kontrol_turu,
    }
    if sonuc == "UYUSMAZLIK":
        if hata_kategorisi not in ERROR_CATEGORIES:
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        record["hata_kategorisi"] = hata_kategorisi
    elif hata_kategorisi is not None:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    validate_test_result(record)
    return record


def validate_test_result(record: dict) -> None:
    if not isinstance(record, dict) or not set(record) <= set(TEST_RESULT_KEYS):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if record.get("kayit_surumu") != RECORD_SCHEMA_VERSION or not _VERSION_RE.match(
        str(record.get("yazilim_surumu", "")),
    ):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if record.get("sonuc") not in RESULTS or record.get("kontrol_turu") not in CONTROL_KINDS:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if (record["sonuc"] == "UYUSMAZLIK") != ("hata_kategorisi" in record):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if "hata_kategorisi" in record and record["hata_kategorisi"] not in ERROR_CATEGORIES:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    _scan_values(record)


# ----------------------------------------------------------------
# 2. İmha kaydı
# ----------------------------------------------------------------

IMHA_KEYS = (
    "kayit_surumu", "asama", "islem_zamani", "kopya_turleri", "yontem",
    "genel_sonuc", "tamamlandi_kapsami", "silinmeyenler",
)
IMHA_ITEM_KEYS = ("tur", "adet", "sonuc")


def build_imha_record(*, asama: str, kopya_turleri: list, genel_sonuc=None, now=None) -> dict:
    """`TAMAMLANDI` YALNIZ `YALNIZ_PILOT_KOPYALARI` kapsamında söylenir;
    veritabanı işlem kayıtları silinmez ve `silinmeyenler` alanında açıkça
    belirtilir."""
    if asama not in IMHA_STAGES:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if (asama == "SONUC") != (genel_sonuc is not None):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if genel_sonuc is not None and genel_sonuc not in IMHA_RESULTS:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    record = {
        "kayit_surumu": RECORD_SCHEMA_VERSION,
        "asama": asama,
        "islem_zamani": utc_timestamp(now),
        "kopya_turleri": [dict(item) for item in kopya_turleri],
        "yontem": IMHA_METHOD,
        "tamamlandi_kapsami": IMHA_SCOPE,
        "silinmeyenler": list(IMHA_NOT_DELETED),
    }
    if genel_sonuc is not None:
        record["genel_sonuc"] = genel_sonuc
    validate_imha_record(record)
    return record


def validate_imha_record(record: dict) -> None:
    if not isinstance(record, dict) or not set(record) <= set(IMHA_KEYS):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if record.get("kayit_surumu") != RECORD_SCHEMA_VERSION or record.get("asama") not in IMHA_STAGES:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if not _TIME_RE.match(str(record.get("islem_zamani", ""))):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if record.get("yontem") != IMHA_METHOD or record.get("tamamlandi_kapsami") != IMHA_SCOPE:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if record.get("silinmeyenler") != list(IMHA_NOT_DELETED):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if (record["asama"] == "SONUC") != ("genel_sonuc" in record):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if "genel_sonuc" in record and record["genel_sonuc"] not in IMHA_RESULTS:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    items = record.get("kopya_turleri")
    if not isinstance(items, list):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    for item in items:
        if not isinstance(item, dict) or set(item) != set(IMHA_ITEM_KEYS):
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        if item["tur"] not in COPY_TYPES or item["sonuc"] not in IMHA_ITEM_RESULTS:
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        if type(item["adet"]) is not int or item["adet"] < 0:
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    _scan_values(record)


# ----------------------------------------------------------------
# 3. Geliştirici destek özeti (YALNIZ ekranda; gönderim YOK)
# ----------------------------------------------------------------

SUPPORT_KEYS = ("yazilim_surumu", "islem_adimi", "hata_kodu", "hata_kategorisi")


def build_support_summary(*, islem_adimi: str, hata_kodu=None, hata_kategorisi=None) -> dict:
    """Üç alan: sürüm + işlem adımı + (hata kodu VEYA hata kategorisi)."""
    if islem_adimi not in PROCESS_STEPS:
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    if (hata_kodu is None) == (hata_kategorisi is None):
        raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
    summary = {"yazilim_surumu": SOFTWARE_VERSION, "islem_adimi": islem_adimi}
    if hata_kodu is not None:
        if hata_kodu not in ERROR_CODES:
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        summary["hata_kodu"] = hata_kodu
    else:
        if hata_kategorisi not in ERROR_CATEGORIES:
            raise OfficeFlowError("KAYIT_SEMASI_GECERSIZ")
        summary["hata_kategorisi"] = hata_kategorisi
    return summary


def render_support_summary(summary: dict) -> str:
    lines = ["--- DESTEK ÖZETİ (yalnız bu alanlar elle paylaşılabilir) ---"]
    lines.append(f"YAZILIM_SURUMU={summary['yazilim_surumu']}")
    lines.append(f"ISLEM_ADIMI={summary['islem_adimi']}")
    if "hata_kodu" in summary:
        lines.append(f"HATA_KODU={summary['hata_kodu']}")
    else:
        lines.append(f"HATA_KATEGORISI={summary['hata_kategorisi']}")
    lines.append("--- (yazılım hiçbir şeyi otomatik göndermez) ---")
    return "\n".join(lines) + "\n"


def error_code_for(error: BaseException) -> str:
    """İstisnayı KAPALI kodlara eşler; `str(error)`/traceback/yol ASLA
    kullanılmaz. Bilinmeyen sınıf -> BILINMEYEN_HATA."""
    if isinstance(error, OfficeFlowError):
        return error.code
    names = {cls.__name__ for cls in type(error).__mro__}
    module = type(error).__module__ or ""
    if "CaseAccessDeniedError" in names:
        return "YETKI_YOK"
    if "DatabaseNotConfiguredError" in names:
        return "VERITABANI_YAPILANDIRMASI_YOK"
    if module.startswith("psycopg"):
        return "VERITABANI_HATASI"
    if "ApprovalUiError" in names or "MutationCoordinatorError" in names:
        return "ZINCIR_ADIMI_BASARISIZ"
    if "OSError" in names:
        return "DOSYA_ISLEMI_BASARISIZ"
    if names & {"KeyboardInterrupt", "EOFError"}:
        return "KULLANICI_ILERLETMEDI"
    return "BILINMEYEN_HATA"


# ----------------------------------------------------------------
# kayitlar/ yazıcıları (O_EXCL; ASLA silme/üzerine yazma)
# ----------------------------------------------------------------


def _new_token() -> str:
    return secrets.token_hex(8)


def new_result_token() -> str:
    return _new_token()


def write_test_result(records_dir, record: dict, token=None) -> Path:
    """O_EXCL. Aynı `token` ikinci kez yazılamaz (DOSYA_MEVCUT): yeniden
    başlatmada çift sonuç kaydı oluşmaz."""
    validate_test_result(record)
    path = Path(records_dir) / f"test_sonucu_{token or _new_token()}.json"
    write_new_file(path, canonical_bytes(record))
    return path


_IMHA_NAME_RE = re.compile(r"^imha_([0-9a-f]{16})_([0-9]{4})\.json$")


def new_imha_token() -> str:
    return _new_token()


def imha_records_for(records_dir, token: str) -> list:
    """(seq, record) listesi, seq'e göre sıralı."""
    out = []
    try:
        names = sorted(p.name for p in Path(records_dir).iterdir() if p.is_file())
    except OSError:
        return []
    for name in names:
        match = _IMHA_NAME_RE.match(name)
        if not match or match.group(1) != token:
            continue
        try:
            record = json.loads((Path(records_dir) / name).read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            continue
        out.append((int(match.group(2)), record))
    return sorted(out, key=lambda item: item[0])


def write_imha_record(records_dir, token: str, record: dict) -> Path:
    """Yeni sıra numaralı dosya; ASLA üzerine yazılmaz."""
    validate_imha_record(record)
    existing = imha_records_for(records_dir, token)
    seq = (existing[-1][0] + 1) if existing else 1
    path = Path(records_dir) / f"imha_{token}_{seq:04d}.json"
    write_new_file(path, canonical_bytes(record))
    return path


def open_imha_tokens(records_dir) -> list:
    """Son kaydı BASLADI olan (SONUC yazılmamış) jetonlar: yarım kalan silme."""
    tokens = set()
    try:
        names = [p.name for p in Path(records_dir).iterdir() if p.is_file()]
    except OSError:
        return []
    for name in names:
        match = _IMHA_NAME_RE.match(name)
        if match:
            tokens.add(match.group(1))
    open_tokens = []
    for token in sorted(tokens):
        records = imha_records_for(records_dir, token)
        if records and records[-1][1].get("asama") == "BASLADI":
            open_tokens.append(token)
    return open_tokens
