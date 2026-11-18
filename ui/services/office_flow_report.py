# ============================================================
# VERGİ AI - BÜRO MODELİ / T1 - PİLOT HESAP RAPORU, KARŞILAŞTIRMA, BAYATLIK
#
# Pilot Hesap Raporu: avukatın F2 kayıtları + sistemin BEKLEYEN (pending)
# sonucu + fark. Neden ayrı: `ui/deadline_report.py` yalnız ONAYLI sonucu
# okur; UYUŞMAZLIK'ta onay olmadığı için o rapor hiç çalışmaz. Bu rapor
# onaya bağlı değildir ve GERÇEK tarih içerir (büro cihazında kalır, silme
# adımına girer). Hukuki görüş veya karar DEĞİLDİR.
#
# Bu modül hiçbir kaydı (`kayitlar/`) yazmaz; yalnız rapor metnini üretir ve
# koşu dizinine O_EXCL yazar/damgalar.
# ============================================================

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ui.services.office_flow_outcomes import CLOSURE_NOT_PROOF_SENTENCE
from ui.services.office_flow_records import (
    REPORT_NAME, OfficeFlowError, RunPaths, atomic_replace_file, changed_inputs, write_new_file,
)

NOT_LEGAL_SENTENCE = (
    "Bu rapor hukuki görüş veya karar değildir; süreye ilişkin karar ve dilekçe avukata aittir."
)
STALE_BANNER = (
    "*** GEÇERSİZ: Karşılaştırmadan sonra doğrulanmış girdi değişti; bu rapor nihai onay veya "
    "geçerli rapor olarak KULLANILAMAZ. ***"
)


def iso_to_tr(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}.{month}.{year}"


@dataclass(frozen=True)
class SystemSummary:
    anchor_date: str | None
    calculation_state: str | None
    calculated_deadline: str | None
    rule_id: str | None
    requires_human_review: bool | None


def summarize_pending_deadline(pending_doc) -> SystemSummary:
    """Bekleyen deadline belgesinden TEK deadline özeti. Beklenen şekil
    dışı -> `SISTEM_HESAPLAMADI` (karşılaştırma yok)."""
    deadlines = pending_doc.get("deadlines") if isinstance(pending_doc, dict) else None
    if not isinstance(deadlines, list) or len(deadlines) != 1 or not isinstance(deadlines[0], dict):
        raise OfficeFlowError("SISTEM_HESAPLAMADI")
    item = deadlines[0]
    return SystemSummary(
        anchor_date=item.get("anchor_date"),
        calculation_state=item.get("calculation_state"),
        calculated_deadline=item.get("calculated_deadline"),
        rule_id=item.get("rule_id"),
        requires_human_review=item.get("requires_human_review"),
    )


def read_pending_summary(pending_path) -> SystemSummary:
    try:
        doc = json.loads(Path(pending_path).read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        raise OfficeFlowError("SISTEM_HESAPLAMADI") from None
    return summarize_pending_deadline(doc)


@dataclass(frozen=True)
class Comparison:
    sonuc: str                       # UYUMLU | UYUSMAZLIK
    tarih_uyumu: bool | None
    son_gun_uyumu: bool | None
    neden: str | None                # dahili: TARIH_FARKLI | SON_GUN_FARKLI | SISTEM_HESAPLAMADI | ANCHOR_FARKLI


def compare(reading: dict, system: SystemSummary) -> Comparison:
    """UYUMLU YALNIZ: anchor tarihi == avukatın bağımsız tarihi VE sistem
    durumu `calculated` VE `calculated_deadline` == avukatın kör son günü.
    Belirsiz/hesaplanamayan -> UYUSMAZLIK (fail-closed; onay açılmaz)."""
    tarih_ok = system.anchor_date == reading["tebligat_tarihi"]
    if system.calculation_state != "calculated" or not system.calculated_deadline:
        return Comparison("UYUSMAZLIK", tarih_ok, None, "SISTEM_HESAPLAMADI")
    son_gun_ok = system.calculated_deadline == reading["kor_son_gun"]
    if not tarih_ok:
        return Comparison("UYUSMAZLIK", False, son_gun_ok, "ANCHOR_FARKLI")
    if not son_gun_ok:
        return Comparison("UYUSMAZLIK", True, False, "SON_GUN_FARKLI")
    return Comparison("UYUMLU", True, True, None)


def _line(label: str, value) -> str:
    return f"{label}: {value}"


def build_report_text(
    *, reading: dict, system: SystemSummary | None, comparison: Comparison | None,
    state: str, f3_date_mismatch=None, canonical_report: str | None = None,
    kontrol_turu: str | None = None,
) -> str:
    lines = ["PİLOT HESAP RAPORU", "=" * 18]
    lines.append(
        "Amaç: dosya avukatının, uygulamanın hesapladığı son günü kendi bağımsız hesabıyla "
        "karşılaştırabilmesi."
    )
    lines.append(NOT_LEGAL_SENTENCE)
    lines.append("")
    lines.append("AVUKATIN BAĞIMSIZ KAYDI (sistem sonucu görülmeden önce)")
    lines.append(_line("Tebliğ tarihi (asıl belgeden)", iso_to_tr(reading["tebligat_tarihi"])))
    lines.append(_line("Sayfa", reading["sayfa"]))
    lines.append(_line("Avukatın hesapladığı son gün", iso_to_tr(reading["kor_son_gun"])))
    lines.append(_line("Adli tatil beyanı", reading["adli_tatil"]))
    lines.append(_line("Süreyi etkileyen işlem beyanı", reading["stopping_event_status"]))
    if f3_date_mismatch is not None:
        lines.append("")
        lines.append("TEBLİĞ TARİHİ KARŞILAŞTIRMASI (F3): seçilen aday satırdaki tarih avukatın bağımsız tarihiyle UYUŞMUYOR.")
        lines.append(_line("Aday satırdaki tarih", iso_to_tr(f3_date_mismatch)))
        lines.append("Hesap yapılmadı.")
    if system is not None:
        lines.append("")
        lines.append("SİSTEMİN SONUCU")
        lines.append(_line("Anchor (tebliğ) tarihi", iso_to_tr(system.anchor_date) if system.anchor_date else "-"))
        lines.append(_line("Hesap durumu", system.calculation_state))
        lines.append(_line("Hesaplanan son gün", iso_to_tr(system.calculated_deadline) if system.calculated_deadline else "-"))
        lines.append(_line("Kural", system.rule_id or "-"))
    if comparison is not None:
        lines.append("")
        lines.append("KARŞILAŞTIRMA")
        lines.append(_line("Sonuç", comparison.sonuc))
        if comparison.tarih_uyumu is not None:
            lines.append(_line("Tebliğ tarihi", "uyumlu" if comparison.tarih_uyumu else "FARKLI"))
        if comparison.son_gun_uyumu is not None:
            lines.append(_line("Son gün", "uyumlu" if comparison.son_gun_uyumu else "FARKLI"))
        if comparison.sonuc == "UYUSMAZLIK":
            lines.append("Nihai onay verilmez; fark büro cihazında incelenir.")
    if kontrol_turu is not None:
        lines.append(_line("Kontrol türü", kontrol_turu))
    lines.append(_line("Koşu durumu", state))
    if canonical_report:
        lines.append("")
        lines.append("ONAYLI SONUCUN RAPORU (ui.deadline_report çıktısı)")
        lines.append(canonical_report.rstrip("\n"))
    lines.append("")
    lines.append(CLOSURE_NOT_PROOF_SENTENCE)
    return "\n".join(lines) + "\n"


def write_report(paths: RunPaths, text: str) -> None:
    """İlk yazım O_EXCL; sonraki güncellemeler (örn. UYUMLU'da onaylı rapor
    eki, GEÇERSİZ damgası) atomik değiştirme (aynı çalışma kaydı)."""
    data = text.encode("utf-8")
    if paths.report_path.exists():
        atomic_replace_file(paths.report_path, data)
    else:
        write_new_file(paths.report_path, data)


def read_report(paths: RunPaths) -> str:
    try:
        return paths.report_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise OfficeFlowError("DOSYA_ISLEMI_BASARISIZ") from None


def stamp_report_invalid(paths: RunPaths) -> None:
    text = read_report(paths) if paths.report_path.exists() else ""
    if text.startswith(STALE_BANNER):
        return
    write_report(paths, STALE_BANNER + "\n" + text)


def is_stale(recorded_inputs: dict, current_inputs: dict) -> list:
    """Değişen girdi ADLARI (boş liste = bayat değil)."""
    return changed_inputs(recorded_inputs, current_inputs)
