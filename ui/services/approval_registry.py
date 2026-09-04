# ============================================================
# VERGİ AI - LAWYER UI, APPROVAL REGISTRY (Row 18a)
#
# 12 row'un Layer A onay akışını TEK bir arayüz altında toplar.
# Bu modül var olan onay modüllerinin İÇ MANTIĞINI YENİDEN
# YAZMAZ/KOPYALAMAZ - yalnız onları çağırır.
#
# TARGETED REMEDIATION (bu turda uygulanan iki değişiklik):
#
#   1) HER fonksiyon artık `case_id`'yi `paths.resolve_case_id()` ile
#      DOĞRULUYOR - önceki incelemede case_id'nin bazı fonksiyonlarda
#      hiç doğrulanmadan Row 6-17 modüllerinin
#      `CASES_DIR / case_id / "..."` şeklindeki DOĞRUDAN path
#      birleştirmesine gittiği (case_law_validator.py, deadline_
#      approval.py, argument_engine.py vb. kaynak kodu okunarak
#      DOĞRULANDI) tespit edilmişti.
#
#   2) "fact" (Row 6) ve "timeline" (Row 7) için MUTASYON (onay)
#      YOLU KALDIRILDI. Gerekçe: `fact_approval.py`/
#      `timeline_approval.py` kaynak kodu tekrar okunarak DOĞRULANDI
#      - hiçbiri `get_pending_path(case_id)` tarzı, case_id'den
#      "GÜNCEL/aktif pending hangisi" sorusunu deterministik olarak
#      çözen bir resolver TAŞIMIYOR (`review_pending`/`promote`/
#      `approve_pending` yalnız KENDİSİNE doğrudan verilen bir
#      pending_path üzerinde çalışır). "Zaten onaylanmış" hash
#      tespiti bir pending'in DAHA ÖNCE onaylandığını KANITLAYABİLİR
#      ama diğer onaylanmamış kardeşlerinden HANGİSİNİN güncel
#      olduğunu KANITLAYAMAZ - bu yüzden Row 18a bu iki aile için
#      onay düğmesi SUNMAZ, yalnız bilgi amaçlı listeler
#      (`UnsupportedApprovalFamilyError` / `kind="unsupported_
#      pending_resolution"`). Row 1-17'ye bu turda DOKUNULMADI - bir
#      resolver İCAT EDİLMEDİ.
#
# Case-scoped (10 modül: deadline...orchestrator) tekdüze arayüzü
# AYNEN korunuyor: get_pending_path(case_id) / get_canonical_path
# (case_id) / inspect_pending(case_id) / run_approve(case_id).
#
# Her review adımı SALT OKUNURDUR (ilgili modülün kendi validator'ı
# çalışır ama hiçbir şey yazılmaz). Her approve adımı, sayfa
# render edildiğinde hesaplanan pending dosya hash'inin HÂLÂ GEÇERLİ
# olduğunu yeniden kontrol eder - değişmişse ilgili approve
# fonksiyonu HİÇ ÇAĞRILMAZ (StaleViewError).
# ============================================================

import contextlib
import importlib
import io
from pathlib import Path

from . import paths
from .common import (
    ApprovalUiError,
    StaleViewError,
    PendingNotFoundError,
    UnsupportedApprovalFamilyError,
    find_latest_audit,
    sha256_file,
)


# ============================================================
# ZATEN ONAYLANMIŞ (TARİHSEL) PENDING TESPİTİ - Row 6/Row 7'nin
# approval audit kayıtları `source_pending_sha256`/`pending_sha256`
# alanında hangi pending'i onayladığını taşır. fact_approval.py ve
# timeline_approval.py ESKİ pending dosyalarını SİLMEZ/temizlemez -
# bu yüzden bir case'de aynı anda birden fazla `.pending` dosyası
# (bazıları YILLAR önce zaten onaylanmış) bulunabilir. Bunların
# HEPSİNİ "onaylanabilir" olarak göstermek TEHLİKELİDİR - bir
# avukat eski/aşılmış bir pending'i yanlışlıkla yeniden onaylayıp
# GÜNCEL canonical'ın üzerine YAZABİLİR (fact_approval.promote() ve
# timeline_approval.approve_pending() bunu ENGELLEMEZ, "bu zaten
# onaylandı" kontrolü YAPMAZ). Row 18 bu boşluğu SESSİZCE kabul
# ETMEZ - her pending dosyasını kendi reviews/ dizinindeki audit
# kayıtlarına karşı kontrol edip zaten onaylanmışsa "AKSİYON YOK,
# yalnız bilgi" olarak işaretler (fail-closed, Prensip 9).
# ============================================================

def _already_approved_pending_hashes(reviews_dir, hash_field_candidates):

    import json as _json

    reviews_dir = Path(reviews_dir)

    hashes = set()

    if not reviews_dir.is_dir():

        return hashes

    for audit_path in reviews_dir.glob("*.approval.json"):

        try:

            with open(audit_path, "r", encoding="utf-8") as file:

                record = _json.load(file)

        except Exception:

            continue

        for field in hash_field_candidates:

            value = record.get(field)

            if value:

                hashes.add(value)

    return hashes


def _mark_already_approved(items, hash_field_candidates):
    """
    `items`: [{"pending_path": Path, ...}, ...]. Her item'a
    `already_approved` (bool) ve `pending_hash` ekler; reviews/
    dizini pending dosyasının kardeşi olarak varsayılır (CLAUDE.md
    §2 konvansiyonu).
    """

    for item in items:

        pending_path = item["pending_path"]

        reviews_dir = pending_path.parent / "reviews"

        already_approved_hashes = _already_approved_pending_hashes(reviews_dir, hash_field_candidates)

        pending_hash = sha256_file(pending_path)

        item["pending_hash"] = pending_hash
        item["already_approved"] = pending_hash in already_approved_hashes

    return items


# ============================================================
# CASE-SCOPED (UNIFORM) ROW REGISTRY - Row 8-17
# ============================================================

CASE_SCOPED_ROWS = [
    {"key": "deadline", "row_no": 8, "label": "Deadline Engine", "module": "deadline_approval"},
    {"key": "issue_spotting", "row_no": 9, "label": "Issue Spotting Agent", "module": "issue_spotting_approval"},
    {"key": "legal_research", "row_no": 10, "label": "Legal Research Agent", "module": "legal_research_approval"},
    {"key": "case_law", "row_no": 11, "label": "Case Law Agent", "module": "case_law_approval"},
    {"key": "evidence", "row_no": 12, "label": "Evidence Agent", "module": "evidence_approval"},
    {"key": "arguments", "row_no": 13, "label": "Argument Agent", "module": "argument_approval"},
    {"key": "risk_strategy", "row_no": 14, "label": "Risk / Strategy Agent", "module": "risk_strategy_approval"},
    {"key": "drafting", "row_no": 15, "label": "Drafting Agent", "module": "drafting_approval"},
    {"key": "qa", "row_no": 16, "label": "QA Agent", "module": "qa_approval"},
    {"key": "case_view", "row_no": 17, "label": "Product Orchestrator (Case View)", "module": "orchestrator_approval"},
]

CASE_SCOPED_ROWS_BY_KEY = {row["key"]: row for row in CASE_SCOPED_ROWS}

# Doküman/case-özel adapter'lar ayrı ele alınır - CASE_SCOPED_ROWS'a
# KARIŞTIRILMAZ (farklı fonksiyon imzaları taşırlar).
SPECIAL_ROWS = [
    {"key": "fact", "row_no": 6, "label": "Fact Extraction Agent (doküman bazlı)"},
    {"key": "timeline", "row_no": 7, "label": "Timeline Agent"},
]

ALL_ROW_KEYS = [r["key"] for r in SPECIAL_ROWS] + [r["key"] for r in CASE_SCOPED_ROWS]


def _import_module(name):

    return importlib.import_module(name)


# ============================================================
# CASE-SCOPED ADAPTER
# ============================================================

def case_scoped_status(row_key, case_id):

    case_id = paths.resolve_case_id(case_id)

    row = CASE_SCOPED_ROWS_BY_KEY[row_key]

    module = _import_module(row["module"])

    pending_path = module.get_pending_path(case_id)
    canonical_path = module.get_canonical_path(case_id)

    return {
        "row": row,
        "pending_path": pending_path,
        "canonical_path": canonical_path,
        "pending_exists": pending_path.exists(),
        "canonical_exists": canonical_path.exists(),
    }


def case_scoped_review(row_key, case_id):
    """
    SALT OKUNUR. `inspect_pending(case_id)` ilgili modülün validator'ını
    ve approval semantic guard'ını ZATEN çalıştırır (bkz. Row 16/17
    `inspect_pending`) - Row 18 bunu YENİDEN YAZMAZ.
    """

    case_id = paths.resolve_case_id(case_id)

    row = CASE_SCOPED_ROWS_BY_KEY[row_key]

    module = _import_module(row["module"])

    pending_path = module.get_pending_path(case_id)

    if not pending_path.exists():

        raise PendingNotFoundError(f"Pending bulunamadı: {pending_path}")

    pending_path, validation, analysis = module.inspect_pending(case_id)

    return {
        "row": row,
        "pending_path": pending_path,
        "pending_hash": sha256_file(pending_path),
        "validation": validation,
        "analysis": analysis,
    }


def case_scoped_approve(row_key, case_id, expected_hash):
    """
    MUTASYON. `expected_hash`, review ekranı render edildiğinde
    hesaplanan pending hash'idir - şu ANKİ pending hash'iyle
    eşleşmiyorsa `run_approve` HİÇ ÇAĞRILMAZ (StaleViewError).
    `run_approve` kendi içinde backup/pre-post-write manifest
    karşılaştırması/rollback yapar - Row 18 bunların HİÇBİRİNİ
    YENİDEN UYGULAMAZ, yalnız çağırır ve sonucu okur.
    """

    case_id = paths.resolve_case_id(case_id)

    row = CASE_SCOPED_ROWS_BY_KEY[row_key]

    module = _import_module(row["module"])

    pending_path = module.get_pending_path(case_id)

    if not pending_path.exists():

        raise PendingNotFoundError(f"Pending bulunamadı: {pending_path}")

    current_hash = sha256_file(pending_path)

    if current_hash != expected_hash:

        raise StaleViewError(
            "Bu review ekranı açıldıktan sonra pending dosya değişti "
            f"(o zamanki hash: {expected_hash}, şimdiki: {current_hash}). "
            "Onay iptal edildi - lütfen sayfayı yenileyip tekrar deneyin."
        )

    stdout_capture = io.StringIO()

    with contextlib.redirect_stdout(stdout_capture):

        module.run_approve(case_id)

    canonical_path = module.get_canonical_path(case_id)
    reviews_dir = canonical_path.parent / "reviews"

    return {
        "row": row,
        "canonical_path": canonical_path,
        "canonical_hash": sha256_file(canonical_path),
        "audit_path": find_latest_audit(reviews_dir),
        "stdout": stdout_capture.getvalue(),
    }


# ============================================================
# FACT (Row 6) / TIMELINE (Row 7) - DESTEKLENMİYOR (UNSUPPORTED)
#
# TARGETED REMEDIATION: bu iki aile için önceki turda var olan
# `fact_review`/`fact_approve`/`timeline_review`/`timeline_approve`
# fonksiyonları KALDIRILDI. Kalan tek şey, case_id başına hangi
# `.pending` dosyalarının VAR OLDUĞUNU (ve hangilerinin geçmişte
# zaten onaylandığını) SALT BİLGİ AMAÇLI listlemektir - bu listeleme
# hiçbir mutasyon fonksiyonuna GİRDİ OLARAK kullanılmaz, main.py bu
# aileler için hiçbir onay/confirm route'u SUNMAZ.
#
# `already_approved` bilgisi burada da YALNIZ ek bir bilgi olarak
# kalır (talimat: "Keep already-approved hash detection only as an
# additional check, not as the active-version selector") - "geri
# kalanlardan hangisi GÜNCEL" sorusuna asla cevap ÜRETMEZ.
# ============================================================

def list_fact_pending_items(case_id):

    case_id = paths.resolve_case_id(case_id)

    documents_dir = paths.CASES_DIR / case_id / "documents"

    items = []

    if not documents_dir.is_dir():

        return items

    for document_dir in sorted(documents_dir.iterdir()):

        extractions_dir = document_dir / "extractions"

        if not extractions_dir.is_dir():

            continue

        for pending_path in sorted(extractions_dir.glob("*.json.pending")):

            items.append({
                "document_id": document_dir.name,
                "pending_path": pending_path,
            })

    return _mark_already_approved(items, ["source_pending_sha256"])


def list_timeline_pending_items(case_id):

    case_id = paths.resolve_case_id(case_id)

    timeline_dir = paths.CASES_DIR / case_id / "timeline"

    if not timeline_dir.is_dir():

        return []

    items = [
        {"pending_path": p}
        for p in sorted(timeline_dir.glob("*.pending"))
    ]

    return _mark_already_approved(items, ["pending_sha256"])


def raise_unsupported_family(family_label):
    """main.py, fact/timeline için (kazara da olsa) bir onay/confirm
    isteği alırsa bunu ÇAĞIRIR - hiçbir koşulda `promote`/
    `approve_pending` fonksiyonlarına ULAŞMAZ."""

    raise UnsupportedApprovalFamilyError(
        f"{family_label} ailesi için Row 18a'da onay DESTEKLENMİYOR: "
        "case_id başına 'hangi pending güncel' sorusunu deterministik "
        "olarak çözecek yetkili bir resolver Row 1-17'de yok. Mevcut "
        "CLI aracını (python src/... --approve) kullanın."
    )


# ============================================================
# TÜM CASE İÇİN DURUM ÖZETİ (approvals listesi ekranı)
# ============================================================

def full_case_approval_status(case_id):

    case_id = paths.resolve_case_id(case_id)

    rows = []

    fact_items = list_fact_pending_items(case_id)
    fact_actionable = [i for i in fact_items if not i["already_approved"]]

    rows.append({
        "key": "fact", "row_no": 6, "label": "Fact Extraction Agent (doküman bazlı)",
        "kind": "unsupported_pending_resolution",
        "unsupported_reason": (
            "case_id başına 'güncel pending hangisi' sorusunu çözecek "
            "yetkili bir resolver Row 1-17'de yok - onay yalnız mevcut "
            "CLI aracıyla yapılabilir."
        ),
        "pending_count": len(fact_actionable),
        "historical_count": len(fact_items) - len(fact_actionable),
        "items": fact_items,
    })

    timeline_items = list_timeline_pending_items(case_id)
    timeline_actionable = [i for i in timeline_items if not i["already_approved"]]

    rows.append({
        "key": "timeline", "row_no": 7, "label": "Timeline Agent",
        "kind": "unsupported_pending_resolution",
        "unsupported_reason": (
            "case_id başına 'güncel pending hangisi' sorusunu çözecek "
            "yetkili bir resolver Row 1-17'de yok - onay yalnız mevcut "
            "CLI aracıyla yapılabilir."
        ),
        "pending_count": len(timeline_actionable),
        "historical_count": len(timeline_items) - len(timeline_actionable),
        "items": timeline_items,
    })

    for row in CASE_SCOPED_ROWS:

        status = case_scoped_status(row["key"], case_id)

        rows.append({
            "key": row["key"], "row_no": row["row_no"], "label": row["label"],
            "kind": "case_scoped",
            "pending_count": 1 if status["pending_exists"] else 0,
            "pending_exists": status["pending_exists"],
            "canonical_exists": status["canonical_exists"],
        })

    rows.sort(key=lambda r: r["row_no"])

    return rows
