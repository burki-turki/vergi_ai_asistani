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
from .services import review_registry as reviewreg
from .services.common import (
    ApprovalUiError,
    StaleViewError,
    PendingNotFoundError,
    UnknownCaseError,
    LiveViewInvalidError,
    ReviewUiError,
    UnknownReviewKindError,
    ReviewRecordNotFoundError,
    ReviewStaleViewError,
    ReviewLiveViewInvalidError,
    InvalidReviewNoteError,
)

# Row 18b - Layer B'nin 5 GERÇEK domain hata sınıfı allowlist'i TEK
# yerde (`review_registry.py`) tanımlıdır - burada KOPYALANMAZ,
# doğrudan oradan import edilir (kullanıcı kararı, 2026-09-04: "yalnız
# doğrulanmış beş domain exception sınıfının kontrollü mesajı
# gösterilecek").
_REVIEW_DOMAIN_ERRORS = reviewreg.DOMAIN_REVIEW_ERROR_TYPES

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
    # --- Row 18b (Layer B inceleme kararları) ---
    "UNKNOWN_REVIEW_KIND": "Bilinmeyen inceleme türü.",
    "REVIEW_RECORD_NOT_FOUND": "İncelenecek kayıt artık mevcut değil (durumu değişmiş olabilir) - liste güncellenmiş olabilir.",
    "REVIEW_STALE_VIEW": "Görünüm bu ekran açıldıktan sonra değişti - işlem iptal edildi. Lütfen sayfayı yenileyip tekrar deneyin.",
    "REVIEW_FAMILY_INVALID": "Bu ailenin canonical verisi şu anda doğrulanamıyor ve görüntülenemiyor.",
    "REVIEW_NOTE_INVALID": "İnceleme notu boş olamaz ve en fazla 2000 karakter olabilir.",
    "REVIEW_TRANSITION_FAILED": "İnceleme işlemi tamamlanamadı.",
    # FINAL DOMAIN-ERROR REDACTION REMEDIATION (2026-09-05): 5 LOCKED
    # review backend'inin (evidence/argument/risk_strategy/drafting/qa)
    # fırlattığı domain-reddi mesajları ARTIK OLDUĞU GİBİ gösterilmez -
    # bu mesajlar bazı durumlarda mutlak dosya yolu içerebiliyor (bkz.
    # `_domain_error_page` docstring'i). Bunun yerine HER ZAMAN bu tek
    # sabit metin gösterilir; gerçek ayrıntı yalnız logger'a yazılır.
    "REVIEW_DOMAIN_REJECTED": (
        "İnceleme işlemi ilgili modülün kendi iş kuralı gereği reddedildi. "
        "Lütfen sayfayı yenileyip kaydı yeniden inceleyin; sorun devam "
        "ederse case verisini kontrol edin."
    ),
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


def _domain_error_page(request, error, back_url):
    """
    Row 18b - Layer B'nin 5 GERÇEK domain hata sınıfı
    (`_REVIEW_DOMAIN_ERRORS`) için çağrılır.

    FINAL DOMAIN-ERROR REDACTION REMEDIATION (2026-09-05): önceki
    turun varsayımı - bu 5 sınıfın mesajlarının HER ZAMAN sabit,
    ham-path/traceback İÇERMEYEN iş-kuralı cümleleri olduğu - YANLIŞ
    olduğu kanıtlandı: 5 LOCKED backend'in (evidence/argument/
    risk_strategy/drafting/qa) TAMAMI, "Canonical X.json bulunamadı:
    \n{canonical_path}" biçiminde AYNI domain sınıflarından biriyle
    MUTLAK bir dosya yolu içeren bir mesaj fırlatabiliyor. Bu yüzden
    `str(error)` (veya review_note içeriği, traceback metni, vb.)
    ARTIK HİÇBİR ZAMAN tarayıcıya geçirilmez:

      - orijinal exception TÜRÜ ve TAM mesajı yalnız yerel `logger`'a
        yazılır (konsol/log - repoya/diske ayrı bir dosya olarak
        YAZILMAZ, tanı için tam ayrıntı burada saklı kalır);
      - tarayıcıya YALNIZ `_ERROR_MESSAGES["REVIEW_DOMAIN_REJECTED"]`
        sabit metni gösterilir - işlemin reddedildiğini ve kaydın
        yenilenip incelenmesi gerektiğini açıklar, ham backend metni
        İÇERMEZ.

    Sınıflandırma (bunun bir "domain reddi" olduğu, generic bir hata
    olmadığı) `code="REVIEW_DOMAIN_REJECTED"` ile KORUNUR - değişen
    yalnız tarayıcıya giden MESAJ metnidir, sabit koda çevrilmiştir.
    Beklenmeyen HERHANGİ bir başka exception türü buradan ASLA
    geçirilmez - yalnız `_REVIEW_DOMAIN_ERRORS` allowlist'indeki 5
    sınıf için çağrılır.
    """

    logger.warning(
        "Layer B domain reddi [%s]: %s", type(error).__name__, error,
    )

    return render(
        request, "error.html",
        title="İnceleme reddedildi",
        message=_ERROR_MESSAGES["REVIEW_DOMAIN_REJECTED"],
        code="REVIEW_DOMAIN_REJECTED", back_url=back_url,
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
# LAYER B İNCELEME AKIŞI (Row 18b) - 12 review_kind, tek registry
# üzerinden. Parent-dependency/R1-R6/stale-source kuralları BURADA
# YENİDEN UYGULANMAZ - `review_registry.apply_transition` gerçek
# `apply_review_transition`'ı çağırır, backend TEK OTORİTE kalır.
# ============================================================

@app.get("/cases/{case_id}/reviews")
def reviews_list(request: Request, case_id: str):

    case_id = _resolve_case(case_id)

    try:

        rows = reviewreg.full_case_review_status(case_id)

    except Exception as error:

        # Savunma derinliği: `full_case_review_status` kendi başına
        # her review_kind için `ReviewLiveViewInvalidError`'ı zaten
        # yakalayıp o satırı "invalid" işaretliyor (bkz.
        # `review_registry.py`) - bu except BLOĞU yalnız gerçekten
        # ÖNGÖRÜLMEMİŞ bir hata için EK bir fail-closed katmanıdır,
        # ana savunma DEĞİLDİR.
        return _error_page(request, "REVIEW_FAMILY_INVALID", "/", exc=error)

    return render(request, "reviews_list.html", case_id=case_id, rows=rows)


@app.get("/cases/{case_id}/reviews/{review_kind}/{record_id}")
def review_detail_page(request: Request, case_id: str, review_kind: str, record_id: str):

    case_id = _resolve_case(case_id)

    if review_kind not in reviewreg.REVIEW_KIND_REGISTRY:

        raise HTTPException(status_code=404, detail="Bilinmeyen inceleme türü.")

    back_url = f"/cases/{case_id}/reviews"
    entry = reviewreg.REVIEW_KIND_REGISTRY[review_kind]

    try:

        found = reviewreg.get_review_record(review_kind, case_id, record_id)

    except ReviewRecordNotFoundError as error:

        return _error_page(request, "REVIEW_RECORD_NOT_FOUND", back_url, exc=error)

    except ReviewLiveViewInvalidError as error:

        return _error_page(request, "REVIEW_FAMILY_INVALID", back_url, exc=error)

    except Exception as error:

        # Savunma derinliği (targeted remediation, 2026-09-05):
        # `review_registry._load_and_validate_canonical` artık
        # BEKLENMEYEN her exception'ı zaten `ReviewLiveViewInvalidError`'a
        # ÇEVİRİYOR (kök neden düzeltmesi orada) - bu blok yalnız
        # registry'nin KENDİSİNDE öngörülmemiş bambaşka bir hata
        # (ör. bir KeyError) için EK bir son-çare fail-closed
        # katmanıdır; ham exception/traceback ASLA tarayıcıya sızmaz.
        return _error_page(request, "REVIEW_FAMILY_INVALID", back_url, exc=error)

    # CSRF token BEŞ parçaya BAĞLIDIR: case_id + review_kind +
    # record_id + target_state + o anki canonical hash (targeted
    # remediation, 2026-09-05 - önceki turda target_state KASITLI
    # olarak dışarıda bırakılmıştı; artık her BEŞ değerden herhangi
    # biri POST anında değişirse - yalnız hash değil, seçilen hedef
    # durum da - işlem adaptöre ULAŞMADAN reddedilir). target_state
    # GET anında henüz seçilmediğinden, `allowed_targets`'taki HER
    # olası hedef için AYRI bir token üretilip sayfaya gömülür;
    # tarayıcıda `<select>` değiştikçe gizli `csrf_token` alanı
    # JS ile o hedefin token'ına güncellenir (bkz. review_detail.html).
    allowed_targets = sorted(reviewreg.get_allowed_targets(review_kind))

    csrf_tokens_by_target = {
        target: security.make_csrf_token(
            _CSRF_SECRET, case_id, review_kind, record_id, target, found["canonical_hash"],
        )
        for target in allowed_targets
    }

    return render(
        request, "review_detail.html", case_id=case_id, record_id=record_id,
        label=entry["label"], record=found["record"],
        canonical_hash=found["canonical_hash"],
        allowed_targets=allowed_targets,
        # SCRIPT-CONTEXT JSON SERIALIZATION HARDENING (2026-09-05): ham
        # bir sözlük geçiriliyor - önceden burada elle `json.dumps(...)`
        # ile üretilip `|safe` ile HTML-escape'ten muaf tutularak
        # gömülen bir string vardı (gereksiz bir script-context güven
        # sınırı). Artık şablon, Jinja'nın KENDİ `|tojson` filtresiyle
        # (script-context için güvenli - `<`, `>`, `&`, `'` Unicode
        # escape edilir, `</script>` KAÇIŞI dahil) serileştiriyor.
        csrf_tokens_by_target=csrf_tokens_by_target,
        csrf_token=csrf_tokens_by_target[allowed_targets[0]],
        confirm_action=f"/cases/{case_id}/reviews/{review_kind}/{record_id}/confirm",
        back_url=back_url,
    )


@app.post("/cases/{case_id}/reviews/{review_kind}/{record_id}/confirm")
def review_confirm(
    request: Request, case_id: str, review_kind: str, record_id: str,
    target_state: str = Form(...), review_note: str = Form(...),
    expected_hash: str = Form(...), csrf_token: str = Form(...),
):

    case_id = _resolve_case(case_id)

    if review_kind not in reviewreg.REVIEW_KIND_REGISTRY:

        raise HTTPException(status_code=404, detail="Bilinmeyen inceleme türü.")

    entry = reviewreg.REVIEW_KIND_REGISTRY[review_kind]
    back_url = f"/cases/{case_id}/reviews/{review_kind}/{record_id}"

    # CSRF + aynı-origin kontrolü, HERHANGİ bir review adaptörüne
    # ULAŞMADAN ÖNCE, expected_hash tazelik kontrolünden BAĞIMSIZ bir
    # katman olarak yapılır (18a ile AYNI ilke). Parça sırası
    # `review_detail_page`'deki üretim sırasıyla BİREBİR AYNI olmalı:
    # case_id + review_kind + record_id + target_state + expected_hash
    # (targeted remediation, 2026-09-05 - target_state artık BAĞLAYICI
    # bir parça: submit edilen `target_state` GET anında token'ın
    # üretildiği hedeften FARKLIYSA, token doğrulaması BAŞARISIZ olur).
    if not _check_csrf_and_origin(
        request, _CSRF_SECRET, csrf_token, case_id, review_kind, record_id, target_state, expected_hash,
    ):

        return _error_page(request, "CSRF_INVALID", back_url)

    # review_note doğrulaması TAMAMEN `review_registry.normalize_review_note`
    # üzerinden yapılır (ikinci bir elle yazılmış kopya YOK) - route
    # burada bu paylaşılan fonksiyonu ÇAĞIRARAK sunucu tarafı zorunlu
    # kontrolü uygular; HTML `maxlength` tek başına YETERLİ DEĞİLDİR.
    try:

        reviewreg.normalize_review_note(review_note)

    except InvalidReviewNoteError as error:

        return _error_page(request, "REVIEW_NOTE_INVALID", back_url, exc=error)

    try:

        result = reviewreg.apply_transition(
            review_kind, case_id, record_id, target_state, review_note, expected_hash,
        )

    except ReviewStaleViewError as error:

        return _error_page(request, "REVIEW_STALE_VIEW", back_url, exc=error)

    except ReviewRecordNotFoundError as error:

        return _error_page(request, "REVIEW_RECORD_NOT_FOUND", back_url, exc=error)

    except _REVIEW_DOMAIN_ERRORS as error:

        # FINAL DOMAIN-ERROR REDACTION REMEDIATION (2026-09-05): bu 5
        # GERÇEK, doğrulanmış domain hata sınıfı için ARTIK `str(error)`
        # tarayıcıya geçirilmez - `_domain_error_page` yalnız SABİT,
        # redakte edilmiş bir mesaj render eder; orijinal exception
        # NESNESİ (mesaj DEĞİL, ham metin asla değil) buraya geçirilir
        # ve ham ayrıntı yalnız `_domain_error_page` içinde logger'a
        # yazılır (bkz. o fonksiyonun docstring'i - önceki turun "bu
        # mesajlar zaten path-free" varsayımı YANLIŞ çıktı).
        return _domain_error_page(request, error, back_url)

    except ReviewUiError as error:

        return _error_page(request, "REVIEW_TRANSITION_FAILED", back_url, exc=error)

    except Exception as error:

        # Beklenmeyen HERHANGİ bir exception türü - generic kalır,
        # ham mesaj/traceback ASLA tarayıcıya gösterilmez.
        return _error_page(request, "REVIEW_TRANSITION_FAILED", back_url, exc=error)

    # 5 review modülünün de `apply_review_transition` dönüş sözlüğü
    # (kaynak kodu okunarak doğrulandı) her zaman `canonical_path`/
    # `audit_path`/`post_sha256`/`previous_state`/`new_state`
    # anahtarlarını taşır - registry bunu YENİDEN YORUMLAMAZ.
    audit_path = result["audit_path"]

    return render(
        request, "review_result.html", case_id=case_id, record_id=record_id,
        label=entry["label"],
        previous_state=result["previous_state"], new_state=result["new_state"],
        canonical_path=paths.to_repo_relative(result["canonical_path"]),
        canonical_hash=result["post_sha256"],
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
