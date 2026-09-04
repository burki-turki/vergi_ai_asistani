# ============================================================
# VERGİ AI - LAWYER UI, PATHS BOOTSTRAP (Row 18a)
#
# `ui/` paketi `src/`'nin bir KOPYASI/YENİDEN YAZIMI DEĞİLDİR - var
# olan 12 onay modülünü OLDUĞU GİBİ import edip kullanır (Prensip 10).
# Bu modülün TEK işi: src/'yi import edilebilir kılmak ve DATA_DIR'i
# tek bir yerden vermek.
# ============================================================

import sys
from pathlib import Path

from .common import UnknownCaseError

UI_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = UI_DIR.parent
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"
CASES_DIR = DATA_DIR / "cases"

if str(SRC_DIR) not in sys.path:

    sys.path.insert(0, str(SRC_DIR))


def list_case_ids():
    """
    `data/cases/*` altındaki case dizinlerini listeler (bir case.json
    içeren her dizin). Yeni bir case registry İCAT EDİLMEZ - dosya
    sistemi zaten tek source of truth.
    """

    if not CASES_DIR.is_dir():

        return []

    return sorted(
        p.name for p in CASES_DIR.iterdir()
        if p.is_dir() and (p / "case.json").exists()
    )


# ============================================================
# PAYLAŞILAN ALLOWLIST ÇÖZÜCÜ (targeted remediation, bkz. inceleme
# bulgusu: case_id 6 route'ta hiç doğrulanmadan Row 6-17 modüllerinin
# `CASES_DIR / case_id / "..."` şeklindeki DOĞRUDAN path
# birleştirmesine gidiyordu). BU FONKSİYON, case_id kullanan HER
# route/servis fonksiyonunun İLK SATIRINDA çağrılmalıdır - hiçbir
# upstream modül fonksiyonu (get_pending_path, get_canonical_path,
# inspect_pending, run_approve, glob tabanlı keşif) doğrulanmamış bir
# case_id ile ÇAĞRILMAMALIDIR.
#
# Starlette/uvicorn'un URL normalizasyonuna GÜVENİLMEZ - bu kontrol
# path birleştirmesinden ÖNCE, Python içinde, decode edilmiş DEĞER
# üzerinde çalışır. `%2e%2e` gibi encode edilmiş traversal biçimleri
# ASGI katmanı tarafından tek seviye decode edilip düz `..` olarak
# BURAYA ulaşır (aşağıdaki karakter kontrolü bunu yakalar); double-
# encoding (`%252e%252e`) decode edilmeden `%2e%2e` string'i olarak
# gelir ve gerçek bir case adıyla ASLA eşleşmediği için allowlist
# kontrolünde zaten reddedilir - iki savunma katmanı da bağımsız
# olarak yeterlidir.
# ============================================================

_FORBIDDEN_SUBSTRINGS = ("..", "/", "\\", "\x00")


def resolve_case_id(case_id):
    """
    Yalnız `list_case_ids()`'in GERÇEKTEN keşfettiği bir case dizini
    adıyla TAM eşleşen bir case_id'yi kabul eder; aksi halde
    `UnknownCaseError` fırlatır (boş değer, separator/traversal
    biçimleri ve bilinmeyen ID'ler dahil - hepsi AYNI kapalı sonuca
    gider, hangi kontrolün tetiklendiği saldırgana sızdırılmaz).
    """

    if not isinstance(case_id, str) or not case_id:

        raise UnknownCaseError("Geçersiz (boş) case kimliği.")

    if any(token in case_id for token in _FORBIDDEN_SUBSTRINGS):

        raise UnknownCaseError("Geçersiz case kimliği.")

    if case_id not in list_case_ids():

        raise UnknownCaseError("Bilinmeyen case kimliği.")

    return case_id


def to_repo_relative(path):
    """
    Tarayıcıya HİÇBİR ZAMAN ham mutlak dosya sistemi path'i
    göstermemek için (bkz. inceleme bulgusu) - repo köküne göre
    göreli, güvenli bir gösterim üretir. Repo dışında bir path
    (beklenmez ama savunma amaçlı) genel bir metinle değiştirilir.
    """

    try:

        return str(Path(path).resolve().relative_to(BASE_DIR))

    except Exception:

        return "(repo dışında bir konum)"
