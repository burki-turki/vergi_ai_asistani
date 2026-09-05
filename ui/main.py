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

from typing import List

from .services import paths, live_view, security
from .services import approval_registry as reg
from .services import review_registry as reviewreg
from .services import drafting_request as draftreq
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
    DraftingRequestUiError,
    DraftingRequestFormError,
    DraftingRequestValidationError,
    DraftingRequestStaleInputError,
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
# ROW 18C - POST GÖVDE BOYUTU SINIRI (yalnız
# `.../drafting-request/confirm`'e ÖZGÜ - kontrat madde 7: "must be
# route-specific... must not change the behavior of existing Row
# 18A/18B routes"). `@app.middleware("http")` (BaseHTTPMiddleware)
# YERİNE HAM bir ASGI middleware sınıfı kullanılır - BaseHTTPMiddleware
# `receive`'i GÜVENİLİR şekilde sarmalamayı/akan bayt sayısını
# SAYMAYI DESTEKLEMEZ (kendi içinde gövdeyi erken tüketebilir). Bu
# sınıf, Starlette'in `Form(...)` ayrıştırmasına ULAŞMADAN ÖNCE İKİ
# bağımsız kontrol uygular:
#   1) `Content-Length` header'ı VARSA ve sınırı aşıyorsa, gövde HİÇ
#      OKUNMADAN 413 döner;
#   2) header YOKSA/YANLIŞSA, `receive`'i sarmalayıp GERÇEKTEN alınan
#      bayt sayısını sayar - sınır aşılırsa akan isteği bir istisna ile
#      KESER ve 413 döner.
# İkisi de SABİT, genel bir metin döner - gönderilen alan İÇERİĞİ asla
# yanıta/loga YANSIMAZ (kontrat madde 7).
#
# TARGETED ROUTE SAFETY REMEDIATION (kök-neden düzeltmesi): (2) kontrolü
# `receive`'i SARMALAR ama gövdeyi KENDİSİ OKUMAZ - fiili okuma, aşağıdaki
# `drafting_request_confirm` route'unun KENDİSİNİN `await request.form()`
# çağırmasıyla gerçekleşir (route ARTIK FastAPI'nin otomatik `Form(...)`
# bağımlılık çözümünü KULLANMIYOR - bkz. route'un kendi docstring'i).
# Sınır aşıldığında `_counting_receive` içinde fırlatılan
# `_DraftingRequestBodyTooLarge`, route'un KENDİ `try/except`'i
# tarafından DOĞRUDAN yakalanır (hiçbir framework-içi Form ayrıştırma
# sarmalayıcısına UĞRAMADAN) - bu yüzden istisna asla farklı bir hataya
# (ör. FastAPI'nin kendi 400/422'sine) dönüştürülüp YUTULMAZ. Bu
# middleware'in kendi `try/except`'i (aşağıda) yalnız EK bir savunma
# katmanı olarak kalır.
# ============================================================

_DRAFTING_REQUEST_CONFIRM_SUFFIX = "/drafting-request/confirm"
_DRAFTING_REQUEST_MAX_BODY_BYTES = 128 * 1024

# TARGETED ROUTE SAFETY REMEDIATION (bu bölüm) - hem ASGI middleware'i
# hem de aşağıdaki route'un KENDİSİ AYNI sabit metni döndürür - TEK
# kaynak, iki yazım arasında sürüklenme riski YOK.
_DRAFTING_REQUEST_BODY_TOO_LARGE_MESSAGE = "İstek gövdesi izin verilen azami boyutu aşıyor."


class _DraftingRequestBodyTooLarge(Exception):
    pass


def _exception_tree_contains_body_too_large(error):
    """
    `error` içinde (doğrudan VEYA bir `ExceptionGroup` ağacının
    HERHANGİ bir derinliğinde) bir `_DraftingRequestBodyTooLarge`
    örneği olup olmadığını YİNELEMELİ olarak kontrol eder.

    NEDEN GEREKLİ: AnyIO/Starlette'in task-group tabanlı iptal
    mekanizması, `_counting_receive` içinde fırlatılan
    `_DraftingRequestBodyTooLarge`'ı doğrudan yaymak yerine bir
    `ExceptionGroup` İÇİNE SARMALAYABİLİR - bu durumda
    `except _DraftingRequestBodyTooLarge:` KENDİSİ artık eşleşmez
    (bir ExceptionGroup, sardığı istisna türünün alt sınıfı DEĞİLDİR).

    BASEEXCEPTION SAFETY ORDER CORRECTION (bu fonksiyonun EN ÖNEMLİ
    kuralı): `error` normal `Exception` ailesine AİT DEĞİLSE (ör.
    `asyncio.CancelledError`, `SystemExit`, `KeyboardInterrupt`, VEYA
    bunlardan birini İÇEREN KARIŞIK bir grup), fonksiyon alt ağaca HİÇ
    İNMEDEN doğrudan `False` döner. Bu, en dış çağrı için OLDUĞU KADAR
    her YİNELEMELİ alt-çağrı için de GEÇERLİDİR - fonksiyon HER
    seviyede önce bu kontrolü yapar. Python'un kendi grup kurma kuralı
    gereği, İÇİNDE herhangi bir Exception-olmayan üye barındıran bir
    grup ASLA `ExceptionGroup` (Exception alt sınıfı) OLARAK
    KURULMAZ - her zaman yalnız `BaseExceptionGroup` kalır (bir
    `Exception` örneği DEĞİLDİR) - ve bu özellik iç içe gruplarda da
    YUKARI DOĞRU YAYILIR. Sonuç: içinde GERÇEKTEN
    `_DraftingRequestBodyTooLarge` bulunsa BİLE, yanında bir iptal/
    kontrol-akışı istisnası TAŞIYAN karışık bir grup ASLA "gövde çok
    büyük" olarak SINIFLANDIRILMAZ - bu, o karışık grubun kontrolsüzce
    413'e dönüştürülüp yanındaki BaseException sinyalinin YUTULMASINI
    önler (çağıran taraf zaten `except Exception` kullandığı için böyle
    bir grup pratikte BURAYA hiç ULAŞMAZ - bu, o garantiyi YARDIMCI
    FONKSİYONUN KENDİSİNDE de bağımsız olarak doğrulayan bir savunma
    katmanıdır).

    Bu fonksiyon YALNIZ tür ağacını (`.exceptions`) GERÇEKTEN yürüyerek
    karar verir:
      - istisna adı/mesajı üzerinde HİÇBİR string eşleştirmesi YAPMAZ
        (yalnız `isinstance`/tür kimliği);
      - HER ExceptionGroup'u kör bir şekilde "gövde çok büyük" olarak
        SINIFLANDIRMAZ - yalnız ağacında GERÇEKTEN
        `_DraftingRequestBodyTooLarge` barındıran, TAMAMEN
        `Exception` ailesinden oluşan grupları `True` sayar.
    """

    if not isinstance(error, Exception):

        return False

    if isinstance(error, _DraftingRequestBodyTooLarge):

        return True

    if isinstance(error, BaseExceptionGroup):

        return any(_exception_tree_contains_body_too_large(sub) for sub in error.exceptions)

    return False


class _DraftingRequestBodySizeASGIMiddleware:

    def __init__(self, app):

        self.app = app

    async def __call__(self, scope, receive, send):

        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or not str(scope.get("path", "")).endswith(_DRAFTING_REQUEST_CONFIRM_SUFFIX)
        ):

            await self.app(scope, receive, send)

            return

        headers = dict(scope.get("headers") or [])
        content_length_raw = headers.get(b"content-length")

        if content_length_raw is not None:

            try:

                declared_length = int(content_length_raw)

            except ValueError:

                declared_length = None

            if declared_length is not None and declared_length > _DRAFTING_REQUEST_MAX_BODY_BYTES:

                logger.warning(
                    "Row 18C: Content-Length beyan edilen boyut sınırı aşıyor: %s", declared_length,
                )

                response = PlainTextResponse(
                    _DRAFTING_REQUEST_BODY_TOO_LARGE_MESSAGE, status_code=413,
                )

                await response(scope, receive, send)

                return

        received_total = 0

        async def _counting_receive():

            nonlocal received_total

            message = await receive()

            if message.get("type") == "http.request":

                received_total += len(message.get("body") or b"")

                if received_total > _DRAFTING_REQUEST_MAX_BODY_BYTES:

                    raise _DraftingRequestBodyTooLarge()

            return message

        try:

            await self.app(scope, _counting_receive, send)

        except Exception as error:

            # BASEEXCEPTION SAFETY ORDER CORRECTION: bilinçli olarak
            # `except BaseException` DEĞİL, `except Exception`
            # kullanılıyor - bir iptal/`CancelledError`/`SystemExit`/
            # `KeyboardInterrupt` (veya bunlardan birini İÇEREN karışık
            # bir `BaseExceptionGroup`, ki bu HİÇBİR ZAMAN bir
            # `Exception` örneği DEĞİLDİR) burada YAKALANMADAN otomatik
            # olarak YUKARI YAYILMALI - kontrol-akışı sinyali ASLA
            # YUTULMAMALI. Bu, route'un KENDİ `try/except`'inin
            # (aşağıda, `drafting_request_confirm`) ARKASINDA kalan
            # yalnız EK bir savunma katmanıdır - normal akışta istisna
            # zaten route seviyesinde yakalanır. Yine de burada da
            # AnyIO/Starlette'in `_DraftingRequestBodyTooLarge`'ı
            # (yalnız Exception alt sınıflarından oluşan) bir
            # `ExceptionGroup` içine sarmalamış olma ihtimaline karşı
            # AYNI yinelemeli ağaç kontrolü kullanılır - saf
            # `isinstance`, string eşleştirmesi YOK.
            if not _exception_tree_contains_body_too_large(error):

                raise

            logger.warning(
                "Row 18C: gerçek alınan bayt sayısı sınırı aşıyor (Content-Length eksik/yanlış).",
            )

            response = PlainTextResponse(
                _DRAFTING_REQUEST_BODY_TOO_LARGE_MESSAGE, status_code=413,
            )

            await response(scope, receive, send)


app.add_middleware(_DraftingRequestBodySizeASGIMiddleware)


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
    # --- Row 18C (yapılandırılmış avukat girdisi) ---
    "DRAFTING_REQUEST_VIEW_INVALID": (
        "Bu case için avukat girdisi ekranı şu anda görüntülenemiyor "
        "(kayıtlı girdi, canonical issue listesi veya pending/canonical "
        "karşılaştırması okunamadı/doğrulanamadı)."
    ),
    "DRAFTING_REQUEST_STALE": (
        "Girdi bu ekran açıldıktan sonra değişti - kaydetme iptal edildi. "
        "Lütfen sayfayı yenileyip tekrar deneyin."
    ),
    "DRAFTING_REQUEST_FORM_INVALID": (
        "Gönderilen form geçerli değil (uzunluk sınırı, geçersiz seçim veya "
        "eksik/çelişkili alan). Lütfen alanları kontrol edip tekrar deneyin."
    ),
    "DRAFTING_REQUEST_CONFIRM_REQUIRED": (
        "Kaydetmeden önce onay kutusunu işaretlemelisiniz."
    ),
    "DRAFTING_REQUEST_SAVE_FAILED": (
        "Kaydetme işlemi tamamlanamadı - hiçbir değişiklik kalıcı olmadı."
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
# ROW 18C - YAPILANDIRILMIŞ AVUKAT GİRDİSİ (Option A-prime, kontrat
# 2026-09-05). Bu route'lar YALNIZ `ui.services.drafting_request`'i
# çağırır - Drafting Engine'i/bir agent'ı/network'ü HİÇBİR ZAMAN
# TETİKLEMEZ (bu, yalnız ayrı `ui/run_drafting_request.py` CLI
# köprüsünün işidir - main.py bu modülü ASLA import ETMEZ).
# ============================================================

@app.get("/cases/{case_id}/drafting-request")
def drafting_request_page(request: Request, case_id: str):

    case_id = _resolve_case(case_id)

    back_url = f"/cases/{case_id}"

    try:

        view = draftreq.build_drafting_request_view(case_id)

    except Exception as error:

        return _error_page(request, "DRAFTING_REQUEST_VIEW_INVALID", back_url, exc=error)

    csrf_token = security.make_csrf_token(
        _CSRF_SECRET, case_id, "drafting_request", "save", view["expected_current_input_hash"],
    )

    return render(
        request, "drafting_request.html", case_id=case_id,
        current_wrapper=view["current_wrapper"],
        current_validation_errors=view["current_validation_errors"],
        expected_current_input_hash=view["expected_current_input_hash"],
        pending_status=view["pending_status"], canonical_status=view["canonical_status"],
        canonical_issues=view["canonical_issues"],
        draft_intent_types=sorted(draftreq.DRAFT_INTENT_TYPES),
        appeal_levels=sorted(draftreq.APPEAL_LEVELS),
        request_authorized_explanation=view["request_authorized_explanation"],
        csrf_token=csrf_token,
        confirm_action=f"/cases/{case_id}/drafting-request/confirm",
        back_url=back_url,
        limits=draftreq.FIELD_LIMITS,
    )


@app.post("/cases/{case_id}/drafting-request/confirm")
async def drafting_request_confirm(request: Request, case_id: str):

    # TARGETED ROUTE SAFETY REMEDIATION (kök-neden): bu route ARTIK
    # FastAPI'nin otomatik `Form(...)` parametre bağımlılık çözümünü
    # KULLANMIYOR. O mekanizma TÜM Form alanlarını route gövdesi HİÇ
    # başlamadan ÖNCE ayrıştırıp doğruluyordu - bu da üç bağımsız
    # sorununa yol açıyordu: (a) case_id allowlist kontrolüne
    # ULAŞMADAN ÖNCE eksik bir form alanı 422'ye düşüyordu; (b) form
    # gövdesi okuma/ayrıştırma sırasında oluşan istisnalar (ör. bizim
    # kendi `_DraftingRequestBodyTooLarge`'ımız) FastAPI'nin KENDİ
    # bağımlılık-çözümleme katmanı tarafından YUTULUP farklı bir hataya
    # dönüştürülebiliyordu. Aşağıdaki sıra artık TAMAMEN bu route'un
    # kendi kontrolünde: (1) case_id çözümü - gövdeye HİÇ dokunmadan;
    # (2) gövde boyutu zaten ASGI middleware'i tarafından sınırlanmış
    # durumdayken, form'un MANUEL ayrıştırılması; (3) CSRF/aynı-origin/
    # onay-kutusu kontrolleri; (4) anlamsal doğrulama + kaydetme.
    case_id = _resolve_case(case_id)

    back_url = f"/cases/{case_id}/drafting-request"

    try:

        form_data = await request.form()

    except Exception as error:

        # BASEEXCEPTION SAFETY ORDER CORRECTION: bilinçli olarak
        # `except BaseException` DEĞİL, `except Exception` kullanılıyor
        # - bir iptal/`asyncio.CancelledError`/`SystemExit`/
        # `KeyboardInterrupt` (veya bunlardan birini İÇEREN karışık bir
        # grup, ki Python'un kendi kuralı gereği bu HİÇBİR ZAMAN bir
        # `Exception` örneği DEĞİLDİR - yalnız `BaseExceptionGroup`
        # kalır) burada HİÇ YAKALANMAZ, otomatik olarak YUKARI YAYILIR -
        # ASGI/asyncio'nun kendi kontrol-akışı sinyali ASLA YUTULMAZ.
        #
        # `request.form()` artık BİZİM tarafımızdan çağrılıyor
        # (FastAPI'nin otomatik Form ayrıştırma sarmalayıcısı ARADA
        # YOK), ama AnyIO/Starlette'in KENDİ task-group tabanlı iptal
        # mekanizması, `_counting_receive` içinde fırlatılan
        # `_DraftingRequestBodyTooLarge`'ı doğrudan yaymak yerine
        # (yalnız Exception alt sınıflarından oluşan) bir
        # `ExceptionGroup` İÇİNE SARMALAYABİLİR - bu durumda
        # `except _DraftingRequestBodyTooLarge:` KENDİSİ artık
        # eşleşmez. Bu yüzden `_exception_tree_contains_body_too_large`
        # ile ağaç GERÇEKTEN yürünerek karar verilir - istisna adı/
        # mesajı üzerinde HİÇBİR string eşleştirmesi YOK, ve HER
        # ExceptionGroup KÖRÜ KÖRÜNE "gövde çok büyük" SAYILMIYOR (o
        # yardımcı fonksiyon KENDİSİ de, üstteki `except Exception`
        # garantisinden BAĞIMSIZ olarak, karışık/Exception-olmayan
        # ağaçları ayrıca reddeder - bkz. fonksiyonun kendi docstring'i).
        if _exception_tree_contains_body_too_large(error):

            # ASGI middleware'inin ürettiğiyle BİREBİR AYNI sabit
            # metin/kod - tek kaynak
            # (`_DRAFTING_REQUEST_BODY_TOO_LARGE_MESSAGE`).
            logger.warning(
                "Row 18C: gerçek alınan bayt sayısı sınırı aşıyor (route-seviyesi yakalama).",
            )

            return PlainTextResponse(_DRAFTING_REQUEST_BODY_TOO_LARGE_MESSAGE, status_code=413)

        # Gövde bozuk/ayrıştırılamıyor (ör. geçersiz multipart sınırı)
        # - sabit, genel bir form hatası; ham exception mesajı yalnız
        # logger'a yazılır.
        logger.warning("Row 18C: form gövdesi ayrıştırılamadı: %s", type(error).__name__)

        return _error_page(request, "DRAFTING_REQUEST_FORM_INVALID", back_url)

    # Aşağıdaki `.get(...)` çağrıları, alan TAMAMEN YOKSA `None` döner
    # (eskiden `Form(...)` ZORUNLU olan alanlar için bunu AÇIKÇA ele
    # alıyoruz), alan AÇIKÇA BOŞ gönderilmişse `""` döner - bu ikisi
    # ARTIK BİRBİRİNE KARIŞMIYOR (targeted remediation §3).
    def _text_field(name, default):

        value = form_data.get(name, default)

        return value if isinstance(value, str) else default

    draft_intent_type = _text_field("draft_intent_type", draftreq.DRAFT_INTENT_NOT_SET)
    appeal_level = _text_field("appeal_level", "")
    request_type = _text_field("request_type", "")
    request_text = _text_field("request_text", "")
    lawyer_provided_text = _text_field("lawyer_provided_text", "")

    selected_issue_ids: List[str] = [
        value for value in form_data.getlist("selected_issue_ids") if isinstance(value, str)
    ]

    issue_selection_mode = form_data.get("issue_selection_mode")
    expected_current_input_hash = form_data.get("expected_current_input_hash")
    csrf_token = form_data.get("csrf_token")
    confirm_save = form_data.get("confirm_save")

    # `issue_selection_mode`/`expected_current_input_hash` eskiden
    # `Form(...)` ile ZORUNLU idi - TAMAMEN YOKSA (None) veya string
    # DEĞİLSE (ör. yanlışlıkla bir dosya alanı) sabit, genel bir form
    # hatasıdır - servis katmanına HİÇ ULAŞMAZ.
    if not isinstance(issue_selection_mode, str) or not isinstance(expected_current_input_hash, str):

        return _error_page(request, "DRAFTING_REQUEST_FORM_INVALID", back_url)

    # `csrf_token` TAMAMEN YOKSA `verify_csrf_token`'ın "boş/None ->
    # HER ZAMAN reddet" kuralına düşmesi için boş string'e sabitlenir -
    # `security.verify_csrf_token` zaten `not token` için `False` döner
    # (CSRF zayıflatılmıyor, yalnız None/"" AYNI reddi üretiyor).
    if not isinstance(csrf_token, str):

        csrf_token = ""

    # CSRF + aynı-origin kontrolü, HERHANGİ bir doğrulama/kaydetme
    # adımından ÖNCE (18a/18b ile AYNI ilke). Parça sırası GET
    # route'undaki üretim sırasıyla BİREBİR AYNI olmalı: case_id +
    # "drafting_request" + "save" + expected_current_input_hash.
    if not _check_csrf_and_origin(
        request, _CSRF_SECRET, csrf_token, case_id, "drafting_request", "save", expected_current_input_hash,
    ):

        return _error_page(request, "CSRF_INVALID", back_url)

    # Onay kutusu ZORUNLU - işaretlenmemiş bir checkbox form verisinde
    # HİÇ GÖNDERİLMEZ (Starlette bunu `None` olarak çözer), bu yüzden
    # yalnız TARAYICININ gönderdiği "on" değeri kabul edilir.
    if confirm_save != "on":

        return _error_page(request, "DRAFTING_REQUEST_CONFIRM_REQUIRED", back_url)

    try:

        wrapper = draftreq.save_lawyer_input_from_form(
            case_id=case_id,
            draft_intent_type_choice=draft_intent_type,
            appeal_level_choice=appeal_level,
            issue_selection_mode=issue_selection_mode,
            selected_issue_ids_raw=selected_issue_ids,
            request_type_raw=request_type,
            request_text_raw=request_text,
            lawyer_provided_text_raw=lawyer_provided_text,
            expected_current_input_hash=expected_current_input_hash,
        )

    except DraftingRequestStaleInputError as error:

        return _error_page(request, "DRAFTING_REQUEST_STALE", back_url, exc=error)

    except (DraftingRequestFormError, DraftingRequestValidationError) as error:

        return _error_page(request, "DRAFTING_REQUEST_FORM_INVALID", back_url, exc=error)

    except DraftingRequestUiError as error:

        return _error_page(request, "DRAFTING_REQUEST_SAVE_FAILED", back_url, exc=error)

    except Exception as error:

        # Beklenmeyen HERHANGİ bir exception türü - generic kalır, ham
        # mesaj/traceback ASLA tarayıcıya gösterilmez (mevcut 18a/18b
        # ilkesiyle AYNI, bkz. `_error_page`).
        return _error_page(request, "DRAFTING_REQUEST_SAVE_FAILED", back_url, exc=error)

    return render(
        request, "drafting_request_result.html", case_id=case_id,
        lawyer_input_hash=wrapper.get("lawyer_input_hash"), saved_at=wrapper.get("saved_at"),
        back_url=f"/cases/{case_id}/drafting-request", case_home_url=f"/cases/{case_id}",
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
