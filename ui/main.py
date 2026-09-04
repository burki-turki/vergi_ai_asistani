# ============================================================
# VERGİ AI - LAWYER UI (Row 18a)
#
# Yerel, tek kullanıcılı FastAPI uygulaması. Yalnız 127.0.0.1'den
# gelen isteklere açıktır - auth/çoklu kullanıcı/production
# sertleştirme Row 19'a bırakıldı (kullanıcı kararı, 2026-09-04).
#
# GÜVENLİK SINIRI (kullanıcı spesifikasyonu): bu dosyada hiçbir
# GENERIC "dosya yaz", "komut çalıştır" veya kullanıcıdan keyfi path
# alan endpoint YOKTUR. Bir pending dosya kimliği yalnız
# `services/approval_registry.py`'nin KENDİ listeleme
# fonksiyonlarının döndürdüğü gerçek adaylarla eşleşiyorsa kabul
# edilir - ham path/traversal asla doğrudan açılmaz.
#
# TARGETED REMEDIATION (bu turda main.py'ye uygulanan değişiklikler):
#
#   1) sys.path bootstrap KALDIRILDI - `ui/` artık gerçek bir Python
#      paketi (`ui/__init__.py`, `ui/services/__init__.py`) ve bu
#      dosya İÇ modüllerini BAĞIL import ile çağırıyor
#      (`from .services import ...`). Desteklenen tek çalıştırma
#      biçimi: repo kökünden `python -m ui.main` (veya
#      `uvicorn ui.main:app`) - `python ui/main.py` (düz script)
#      artık bağıl import hatasıyla AÇIKÇA başarısız olur ve
#      ARTIK ÖNERİLMİYOR.
#   2) `paths.resolve_case_id()` allowlist kontrolü, case_id alan
#      HER route'un EN BAŞINDA uygulanıyor (`_resolve_case`) - servis
#      katmanındaki kontrole (approval_registry.py, live_view.py)
#      EK bir savunma katmanı olarak.
#   3) Fact (Row 6) / Timeline (Row 7) için mutasyon route'ları
#      (`fact_review_page`, `fact_confirm`, `timeline_review_page`,
#      `timeline_confirm`) TAMAMEN KALDIRILDI - bu iki aile için
#      case_id başına "hangi pending güncel" sorusunu çözecek yetkili
#      bir resolver Row 1-17'de yok (approval_registry.py'de
#      belgelenmiş bulgu). Kalan tek şey salt-bilgi listelemedir.
#   4) HER mutasyon POST'u artık: (a) sunucu tarafında üretilmiş,
#      sabit-zamanlı doğrulanan bir CSRF token, (b) mevcut
#      Origin/Referer aynı-origin kontrolü, (c) mevcut
#      expected_hash tazelik kontrolü olmak üzere ÜÇ bağımsız
#      kontrolden geçmeden hiçbir onay adaptörüne ULAŞMAZ.
#   5) Tarayıcıya artık HİÇBİR `str(error)` veya ham mutlak path
#      gösterilmiyor - yalnız sabit, genel hata kodları/mesajları
#      (`_ERROR_MESSAGES`) gösteriliyor; gerçek ayrıntı yalnız
#      `logging` ile (dosyaya/repoya YAZILMADAN) loglanıyor.
#   6) Canlı case view artık `LiveViewInvalidError` fail-closed
#      olarak yakalanıp genel bir "kullanılamıyor" ekranına
#      yönlendiriliyor - hiçbir zaman doğrulanmamış canlı görünüm
#      render edilmiyor.
#   7) Gerçekten bağlanan istemcinin IP'sini (`request.client.host`)
#      kontrol eden bir loopback-only middleware eklendi - sunucu
#      yanlışlıkla `--host 0.0.0.0` ile başlatılsa BİLE LAN'dan gelen
#      istekler reddedilir. Test-amaçlı loopback host ayarı (TestClient
#      için) yalnız TEST DOSYASINDA açıkça enjekte edilir - bu
#      dosyada/production launcher'da HİÇBİR test-host istisnası YOK.
# ============================================================

import logging

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .services import paths, live_view, security
from .services import approval_registry as reg
from .services.common import (
    ApprovalUiError,
    StaleViewError,
    PendingNotFoundError,
    UnknownCaseError,
    LiveViewInvalidError,
)

from pathlib import Path

UI_DIR = Path(__file__).resolve().parent

logger = logging.getLogger("vergi_ui")

app = FastAPI(title="Vergi AI - Lawyer UI (Row 18a)")

app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(UI_DIR / "templates"))

# Süreç ömrü boyunca sabit CSRF gizli anahtarı - import anında BİR KEZ
# üretilir, diske/repoya YAZILMAZ, sunucu yeniden başlatıldığında
# yeniden üretilir (bkz. services/security.py docstring).
_CSRF_SECRET = security.new_csrf_secret()


# ============================================================
# LOOPBACK-ONLY ZORUNLULUĞU (targeted remediation §7)
#
# GERÇEK bağlanan istemcinin IP'sine bakar - `uvicorn.run(...,
# host="127.0.0.1")` varsayılanına GÜVENMEZ, dolayısıyla operatör
# yanlışlıkla `--host 0.0.0.0` ile başlatsa bile LAN'dan gelen
# istekler burada reddedilir. Test dosyası, kendi TestClient'ını
# AÇIKÇA `client=("127.0.0.1", ...)` ile başlatarak bu kontrolden
# geçer - bu dosyada test için hiçbir istisna TANIMLANMAZ.
# ============================================================

@app.middleware("http")
async def _loopback_only_middleware(request: Request, call_next):

    client = request.client
    client_host = client.host if client else None

    if not security.is_loopback_host(client_host):

        logger.warning("Loopback olmayan istemci reddedildi: %s", client_host)

        return PlainTextResponse(
            "Bu uygulama yalnız 127.0.0.1 (loopback) üzerinden erişime açıktır.",
            status_code=403,
        )

    return await call_next(request)


# ============================================================
# ORTAK YARDIMCILAR
# ============================================================

def render(request, template_name, **context):

    return templates.TemplateResponse(request, template_name, context)


# Tarayıcıya gösterilen mesajlar KASITLI olarak sabit/genel - hiçbir
# zaman `str(exception)` veya ham path içermez (targeted remediation
# §6). Gerçek ayrıntı yalnız `logger.exception`/`logger.warning` ile
# loglanır.
_ERROR_MESSAGES = {
    "UNKNOWN_CASE": "Case bulunamadı.",
    "UNKNOWN_ROW": "Bilinmeyen onay adımı.",
    "PENDING_NOT_FOUND": "Onaylanacak pending kayıt artık mevcut değil - liste güncellenmiş olabilir.",
    "STALE_VIEW": "Görünüm bu ekran açıldıktan sonra değişti - onay iptal edildi. Lütfen sayfayı yenileyip tekrar deneyin.",
    "VALIDATION_FAILED": "Kayıt, ilgili modülün kendi doğrulamasından geçemedi.",
    "APPROVAL_FAILED": "Onay işlemi tamamlanamadı.",
    "CSRF_INVALID": "Güvenlik doğrulaması başarısız oldu (oturum/origin uyuşmazlığı). Lütfen sayfayı yeniden açıp tekrar deneyin.",
    "LIVE_VIEW_INVALID": "Bu case için canlı görünüm şu anda doğrulanamıyor ve görüntülenemiyor.",
    "ISSUE_NOT_FOUND": "Issue bulunamadı.",
}


def _error_page(request, code, back_url, exc=None):
    """
    Tarayıcıya YALNIZ `_ERROR_MESSAGES`'taki sabit, genel metni
    gösterir - `exc` verilmişse gerçek ayrıntı yalnız logger'a
    yazılır (repoya/diske DEĞİL).
    """

    if exc is not None:

        logger.exception("UI hatası [%s]: %s", code, exc)

    return render(
        request, "error.html",
        title="Hata", message=_ERROR_MESSAGES.get(code, "Beklenmeyen bir hata oluştu."),
        code=code, back_url=back_url,
    )


def _resolve_case(case_id):
    """
    Targeted remediation §3: case_id'yi route katmanında da (servis
    katmanına EK olarak) doğrular - hiçbir case_id, doğrulanmadan bir
    sonraki koda geçemez. Bilinmeyen/geçersiz case_id her zaman AYNI
    genel 404'e gider (hangi kontrolün tetiklendiği sızdırılmaz).
    """

    try:

        return paths.resolve_case_id(case_id)

    except UnknownCaseError as error:

        logger.warning("Bilinmeyen/geçersiz case_id reddedildi: %r (%s)", case_id, error)

        raise HTTPException(status_code=404, detail="Case bulunamadı.")


def _check_csrf_and_origin(request, secret, token, *parts):

    same_origin = security.is_same_origin(
        request.headers.get("origin"),
        request.headers.get("referer"),
        request.headers.get("host"),
    )

    csrf_ok = security.verify_csrf_token(secret, token, *parts)

    if not same_origin:

        logger.warning("Aynı-origin kontrolü başarısız (origin/referer host uyuşmuyor).")

    if not csrf_ok:

        logger.warning("CSRF token doğrulaması başarısız.")

    return same_origin and csrf_ok


# ============================================================
# CASE LİSTESİ / CANLI CASE VIEW
# ============================================================

@app.get("/")
def index(request: Request):

    return render(request, "index.html", case_ids=paths.list_case_ids())


@app.get("/cases/{case_id}")
def case_view(request: Request, case_id: str):

    case_id = _resolve_case(case_id)

    try:

        data = live_view.get_case_view_with_staleness(case_id)

    except LiveViewInvalidError as error:

        return _error_page(request, "LIVE_VIEW_INVALID", "/", exc=error)

    return render(
        request, "case_view.html", case_id=case_id,
        view=data["live_view"], is_stale=data["is_stale"],
        has_canonical=data["has_canonical"],
    )


@app.get("/cases/{case_id}/issues/{issue_id}")
def issue_detail(request: Request, case_id: str, issue_id: str):

    case_id = _resolve_case(case_id)

    try:

        data = live_view.get_case_view_with_staleness(case_id)

    except LiveViewInvalidError as error:

        return _error_page(request, "LIVE_VIEW_INVALID", f"/cases/{case_id}", exc=error)

    entry = next((i for i in data["live_view"]["issue_panel"] if i["issue_id"] == issue_id), None)

    if entry is None:

        return _error_page(request, "ISSUE_NOT_FOUND", f"/cases/{case_id}")

    return render(request, "issue_detail.html", case_id=case_id, issue=entry)


# ============================================================
# ONAY LİSTESİ
# ============================================================

@app.get("/cases/{case_id}/approvals")
def approvals_list(request: Request, case_id: str):

    case_id = _resolve_case(case_id)

    rows = reg.full_case_approval_status(case_id)

    return render(request, "approvals_list.html", case_id=case_id, rows=rows)


# ============================================================
# CASE-SCOPED ONAY AKIŞI (Row 8-17, tekdüze adapter) - Row 18a'da
# MUTASYON DESTEKLENEN TEK AİLE (fact/timeline için bkz. yukarıdaki
# modül docstring'i - resolver eksikliği nedeniyle desteklenmiyor).
# ============================================================

@app.get("/cases/{case_id}/approvals/{row_key}")
def case_scoped_review_page(request: Request, case_id: str, row_key: str):

    case_id = _resolve_case(case_id)

    if row_key not in reg.CASE_SCOPED_ROWS_BY_KEY:

        raise HTTPException(status_code=404, detail="Bilinmeyen onay adımı.")

    back_url = f"/cases/{case_id}/approvals"

    try:

        review = reg.case_scoped_review(row_key, case_id)

    except PendingNotFoundError as error:

        return _error_page(request, "PENDING_NOT_FOUND", back_url, exc=error)

    except ApprovalUiError as error:

        return _error_page(request, "VALIDATION_FAILED", back_url, exc=error)

    except Exception as error:

        return _error_page(request, "VALIDATION_FAILED", back_url, exc=error)

    # CSRF token bu tam review'a (case_id + row_key + o anki pending
    # hash) BAĞLIDIR - başka bir case/row/pending için üretilmiş bir
    # token burada asla geçerli olmaz (bkz. services/security.py).
    csrf_token = security.make_csrf_token(_CSRF_SECRET, case_id, row_key, review["pending_hash"])

    return render(
        request, "approval_review.html", case_id=case_id, row=review["row"],
        pending_hash=review["pending_hash"], analysis=review["analysis"],
        csrf_token=csrf_token,
        confirm_action=f"/cases/{case_id}/approvals/{row_key}/confirm",
        back_url=back_url,
    )


@app.post("/cases/{case_id}/approvals/{row_key}/confirm")
def case_scoped_confirm(
    request: Request, case_id: str, row_key: str,
    expected_hash: str = Form(...), csrf_token: str = Form(...),
):

    case_id = _resolve_case(case_id)

    if row_key not in reg.CASE_SCOPED_ROWS_BY_KEY:

        raise HTTPException(status_code=404, detail="Bilinmeyen onay adımı.")

    back_url = f"/cases/{case_id}/approvals/{row_key}"

    # CSRF + aynı-origin kontrolü, HERHANGİ bir onay adaptörü
    # çağrılmadan ÖNCE, expected_hash tazelik kontrolünden BAĞIMSIZ
    # bir katman olarak yapılır (targeted remediation §8: "expected
    # pending hash is not a substitute for a CSRF token").
    if not _check_csrf_and_origin(request, _CSRF_SECRET, csrf_token, case_id, row_key, expected_hash):

        return _error_page(request, "CSRF_INVALID", back_url)

    try:

        result = reg.case_scoped_approve(row_key, case_id, expected_hash)

    except StaleViewError as error:

        return _error_page(request, "STALE_VIEW", back_url, exc=error)

    except ApprovalUiError as error:

        return _error_page(request, "APPROVAL_FAILED", back_url, exc=error)

    except Exception as error:

        return _error_page(request, "APPROVAL_FAILED", back_url, exc=error)

    audit_path = result["audit_path"]

    return render(
        request, "approval_result.html", case_id=case_id,
        label=result["row"]["label"],
        canonical_path=paths.to_repo_relative(result["canonical_path"]),
        canonical_hash=result["canonical_hash"],
        audit_path=paths.to_repo_relative(audit_path) if audit_path else None,
    )


# ============================================================
# YEREL BAŞLATICI
#
# Desteklenen TEK çalıştırma biçimi: repo kökünden
#     python -m ui.main
# (veya `uvicorn ui.main:app --host 127.0.0.1 --port 8000`).
# `python ui/main.py` (düz script) ARTIK ÇALIŞMAZ - bağıl import
# ("attempted relative import with no known parent package") ile
# AÇIKÇA ve HEMEN başarısız olur; hiçbir sys.path bypass'ı YOKTUR.
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
