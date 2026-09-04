# ============================================================
# VERGİ AI - LAWYER UI, CANLI CASE VIEW (Row 18a)
#
# Kullanıcı kararı (2026-09-04, Row 17 checkpoint'ine eklendi):
# `case_view.json` onaylı/audit'li bir SNAPSHOT'tır. Row 18 her
# sayfa yüklemesinde bunu OKUMAZ - Row 17'nin AYNI saf fonksiyonunu
# (`orchestrator_engine.build_case_view`) doğrudan çağırıp CANLI bir
# görünüm üretir (hiçbir dosyaya yazmadan) ve bunu onaylı canonical
# snapshot'la karşılaştırıp uyuşmuyorsa uyarı gösterir. Bu Row 17'nin
# KODUNU değiştirmez - zaten bağımsız çağrılabilir saf bir fonksiyondu
# (orchestrator_validator.py de aynı şekilde kullanıyor).
#
# TARGETED REMEDIATION EKİ: canlı görünüm artık render edilmeden ÖNCE
# Row 17'nin KENDİ saf, dict-tabanlı doğrulama fonksiyonlarından
# (`orchestrator_validator.validate_schema/validate_case_id/
# validate_generated_at/validate_generation_status_consistency`)
# geçiriliyor - GERÇEK imzalarıyla, hiçbir geçici doğrulama dosyası
# diske/repoya YAZILMADAN (bu 4 fonksiyon zaten in-memory dict alır,
# path istemez). `validate_case_view(path, ...)`/
# `validate_deterministic_view_independently(...)` KASITLI olarak
# ÇAĞRILMIYOR - onlar build_case_view()'ı BİR DAHA çağırıp bir
# DOSYAYI bağımsız yeniden hesaplamayla karşılaştırmak için
# tasarlanmış (Row 17'nin canonical promosyon akışında kullanılıyor);
# burada zaten yeni inşa ettiğimiz aynı belgeyi kendisiyle
# karşılaştırmak anlamsız/israf olurdu - `check_snapshot_freshness`
# de aynı sebeple atlanıyor (canlı görünüm TANIM GEREĞİ o anki
# kaynaklardan yeni inşa edildi). Doğrulama BAŞARISIZ olursa canlı
# görünüm ASLA render edilmez (fail-closed) - `LiveViewInvalidError`.
# ============================================================

import importlib
import json

from . import paths
from .common import LiveViewInvalidError, sha256_file


def build_live_view(case_id):

    orchestrator_engine = importlib.import_module("orchestrator_engine")

    return orchestrator_engine.build_case_view(case_id)


def validate_live_view(live_view, case_id):
    """
    Row 17'nin GERÇEK, saf (dict alan/dönen) doğrulama fonksiyonlarını
    - orchestrator_validator.py'de tanımlı oldukları imzalarla -
    doğrudan çağırır. Hata listesi boşsa geçerlidir.
    """

    orchestrator_validator = importlib.import_module("orchestrator_validator")

    errors = []

    errors.extend(orchestrator_validator.validate_schema(live_view))
    errors.extend(orchestrator_validator.validate_case_id(live_view, case_id))
    errors.extend(orchestrator_validator.validate_generated_at(live_view))
    errors.extend(orchestrator_validator.validate_generation_status_consistency(live_view))

    return errors


def load_canonical_view(case_id):

    canonical_path = paths.CASES_DIR / case_id / "case_view" / "case_view.json"

    if not canonical_path.exists():

        return None, canonical_path

    with open(canonical_path, "r", encoding="utf-8") as file:

        return json.load(file), canonical_path


_VOLATILE_TOP_LEVEL = ("generated_at",)
_VOLATILE_METADATA = ("scan_started_at", "scan_completed_at")


def _strip_volatile(view):

    import copy

    stripped = copy.deepcopy(view)

    for field in _VOLATILE_TOP_LEVEL:

        stripped.pop(field, None)

    metadata = stripped.get("analysis_metadata")

    if isinstance(metadata, dict):

        for field in _VOLATILE_METADATA:

            metadata.pop(field, None)

    return stripped


def get_case_view_with_staleness(case_id):
    """
    Döner: {
      "live_view": <canlı üretilmiş case_view dict>,
      "canonical_view": <onaylı snapshot dict | None>,
      "canonical_path": Path,
      "is_stale": bool,          # canonical var AMA canlıdan farklı
      "has_canonical": bool,     # hiç onaylanmış snapshot yok mu
    }
    UI hiçbir zaman bu canlı görünümü diske YAZMAZ/promote ETMEZ -
    yalnız görüntüler. `case_id` her zaman `paths.resolve_case_id()`
    ile doğrulanır (targeted remediation) ve canlı görünüm Row 17'nin
    kendi doğrulama fonksiyonlarından GEÇMEDEN döndürülmez -
    `LiveViewInvalidError` fail-closed olarak fırlatılır.
    """

    case_id = paths.resolve_case_id(case_id)

    live_view = build_live_view(case_id)

    validation_errors = validate_live_view(live_view, case_id)

    if validation_errors:

        raise LiveViewInvalidError(
            "Canlı case_view Row 17'nin kendi doğrulamasından GEÇEMEDİ "
            f"({len(validation_errors)} hata) - fail-closed, render EDİLMEDİ:\n"
            + "\n".join(f"- {e}" for e in validation_errors[:20])
        )

    canonical_view, canonical_path = load_canonical_view(case_id)

    if canonical_view is None:

        return {
            "live_view": live_view, "canonical_view": None,
            "canonical_path": canonical_path, "is_stale": False,
            "has_canonical": False,
        }

    is_stale = _strip_volatile(live_view) != _strip_volatile(canonical_view)

    return {
        "live_view": live_view, "canonical_view": canonical_view,
        "canonical_path": canonical_path, "is_stale": is_stale,
        "has_canonical": True,
    }
