# ============================================================
# Row 18C - FastAPI TestClient smoke testleri (yapılandırılmış avukat
# girdisi route'ları: GET/POST /cases/{case_id}/drafting-request[/confirm]).
#
# BU DOSYA CLOUD SANDBOX'TA DEĞİL, SİZİN MAKİNENİZDE (Python 3.14 venv,
# fastapi==0.141.1/starlette==1.6.0 kurulu) çalıştırılmak üzere
# yazıldı. Aşağıdaki import GUARD EDİLDİ: FastAPI mevcut değilse bu
# dosya HATA VERMEDEN "SKIPPED" olarak çıkar (exit code 0).
# `ui/services/drafting_request.py` katmanı ve yeni şablonlar zaten
# `test_drafting_request_service_isolated.py` ve
# `test_drafting_request_templates_isolated.py` ile bu sandbox'ta
# GERÇEK case_0001 verisiyle (salt-okunur) VE sentetik/tempdir
# mutasyon senaryolarıyla doğrulandı - bu dosya YALNIZ FastAPI/
# Starlette KATMANINA ÖZGÜ olan maddeleri kapsar: loopback, aynı-
# origin, case allowlist, CSRF'in HER BİR parçası, onay kutusu
# zorunluluğu, 128 KiB gövde sınırı (Content-Length VE gerçek bayt
# sayımı), sabit tarayıcı hataları, request_text/lawyer_provided_text
# İÇERİĞİNİN yanıta/loga SIZMADIĞI ve GET'in salt-okunur kaldığı -
# bunlar doğaları gereği HTTP request/response döngüsü olmadan test
# EDİLEMEZ.
#
# Bu dosyadaki TÜM senaryolar `case_iso_route_drafting_request` adlı
# SENTETİK bir case_id kullanır (`test_review_routes.py`'deki
# `isolated_review_fixture` ile AYNI ilke - `paths.list_case_ids`/
# `resolve_case_id` GEÇİCİ olarak genişletilir, `finally`'de geri
# alınır). GERÇEK case_0001'e veya başka bir gerçek case'e HİÇBİR
# KALICI ÇAĞRI gitmez; dosyanın SONUNDA genel data/+src/ byte-
# snapshot ile de AYRICA kanıtlanır.
#
# Çalıştırma:
#   cd vergi_ai_asistani
#   python -m ui.tests.test_drafting_request_routes
# ============================================================

import asyncio
import contextlib
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:

    import fastapi           # noqa: F401
    from fastapi.testclient import TestClient

    _FASTAPI_AVAILABLE = True

except ModuleNotFoundError:

    _FASTAPI_AVAILABLE = False


if not _FASTAPI_AVAILABLE:

    print("SKIPPED: fastapi bu ortamda kurulu değil - FastAPI route testleri çalıştırılamadı.")
    print("Bu dosyayı FastAPI'nin kurulu olduğu hedef ortamda (Python 3.14 venv) çalıştırıp sonucu bildirin.")
    sys.exit(0)


from ui.services import paths as svc_paths
from ui.services import security
from ui.services import drafting_request as draftreq
from ui.main import (
    app, _CSRF_SECRET, _DRAFTING_REQUEST_MAX_BODY_BYTES,
    _DRAFTING_REQUEST_BODY_TOO_LARGE_MESSAGE, _DraftingRequestBodyTooLarge,
    _exception_tree_contains_body_too_large,
)

import legal_research_validator as lrv

# targeted remediation ile AYNI ilke - TestClient'ın istemci adresini
# AÇIKÇA loopback yapıyoruz; bu dosya DIŞINDA hiçbir yerde test-host
# istisnası YOKTUR.
client = TestClient(app, client=("127.0.0.1", 12345))

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def snapshot_tree(*roots):
    manifest = {}
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest[str(path)] = (path.stat().st_size, path.stat().st_mtime_ns, digest)
    return manifest


_SNAPSHOT_ROOTS = (svc_paths.DATA_DIR, svc_paths.SRC_DIR)
_before_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)

CASE_ID = "case_iso_route_drafting_request"


@contextlib.contextmanager
def isolated_case():

    original_cases_dir = draftreq.CASES_DIR
    original_get_issues_dir = lrv.get_issues_dir
    original_list_case_ids = svc_paths.list_case_ids
    original_resolve_case_id = svc_paths.resolve_case_id

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / CASE_ID).mkdir(parents=True)

        draftreq.CASES_DIR = tmp_path
        lrv.get_issues_dir = lambda cid: tmp_path / cid / "legal_analysis" / "issue_spotting"
        svc_paths.list_case_ids = lambda: [CASE_ID]
        svc_paths.resolve_case_id = lambda cid: cid if cid == CASE_ID else original_resolve_case_id(cid)

        try:
            yield tmp_path
        finally:
            draftreq.CASES_DIR = original_cases_dir
            lrv.get_issues_dir = original_get_issues_dir
            svc_paths.list_case_ids = original_list_case_ids
            svc_paths.resolve_case_id = original_resolve_case_id


_BASE_FORM = {
    "draft_intent_type": "not_set",
    "appeal_level": "",
    "issue_selection_mode": "not_provided",
    "request_type": "",
    "request_text": "",
    "lawyer_provided_text": "",
    "confirm_save": "on",
}


def _get_fresh_context(case_id):
    resp = client.get(f"/cases/{case_id}/drafting-request")
    return resp


def _extract_hidden_value(html, field_name):
    marker = f'name="{field_name}" value="'
    start = html.index(marker) + len(marker)
    end = html.index('"', start)
    return html[start:end]


# ============================================================
# 0) YARDIMCI FONKSİYON BİRİM TESTLERİ -
#    `_exception_tree_contains_body_too_large` (FINAL EXCEPTIONGROUP
#    BODY-LIMIT REMEDIATION §2/§4). HTTP/ASGI GEREKTİRMEZ - saf bir
#    fonksiyon çağrısı; isinstance/BaseExceptionGroup ağaç yürüyüşünün
#    DOĞRU çalıştığının doğrudan kanıtı (T22/T22d'nin GERÇEK HTTP
#    üzerinden dolaylı kanıtına EK olarak).
# ============================================================

check(
    "H01 doğrudan _DraftingRequestBodyTooLarge -> True",
    _exception_tree_contains_body_too_large(_DraftingRequestBodyTooLarge()) is True,
)

check(
    "H02 tek-seviye ExceptionGroup içinde barındırıyor -> True",
    _exception_tree_contains_body_too_large(
        ExceptionGroup("g", [ValueError("gürültü"), _DraftingRequestBodyTooLarge()]),
    ) is True,
)

check(
    "H03 İÇ İÇE (nested) ExceptionGroup içinde barındırıyor -> True",
    _exception_tree_contains_body_too_large(
        ExceptionGroup("outer", [
            TypeError("gürültü2"),
            ExceptionGroup("inner", [_DraftingRequestBodyTooLarge()]),
        ]),
    ) is True,
)

check(
    "H04 ilgisiz bir ValueError -> False",
    _exception_tree_contains_body_too_large(ValueError("ilgisiz")) is False,
)

check(
    "H05 ilgisiz bir ExceptionGroup (hiçbir yerinde hedef YOK) -> False",
    _exception_tree_contains_body_too_large(
        ExceptionGroup("g2", [ValueError("a"), TypeError("b")]),
    ) is False,
)

check(
    "H06 3 seviye derin İÇ İÇE grup, hedefi İÇERİYOR -> True",
    _exception_tree_contains_body_too_large(
        ExceptionGroup("top", [
            ValueError("n1"),
            ExceptionGroup("mid", [
                TypeError("n2"),
                ExceptionGroup("deep", [ValueError("n3"), _DraftingRequestBodyTooLarge()]),
            ]),
        ]),
    ) is True,
)

check(
    "H07 string eşleştirmesi YAPILMIYOR - adı benzeyen ama TÜR OLARAK farklı bir istisna -> False",
    _exception_tree_contains_body_too_large(
        type("_DraftingRequestBodyTooLarge", (Exception,), {})(),  # AYNI AD, FARKLI TÜR
    ) is False,
)

# ------------------------------------------------------------
# H08 - BASEEXCEPTION SAFETY ORDER CORRECTION: KARIŞIK bir grup -
# hem `_DraftingRequestBodyTooLarge` HEM DE Exception-OLMAYAN bir
# iptal/kontrol-akışı istisnası (`asyncio.CancelledError`) birlikte -
# ASLA "gövde çok büyük" (413 adayı) olarak SINIFLANDIRILMAMALI. Test
# GERÇEK bir görevi/task'ı İPTAL ETMEZ ve `KeyboardInterrupt`/
# `SystemExit`'i test runner'ına FIRLATMAZ - yalnız BİRER `Exception`
# ÖRNEĞİ olarak inşa edilip doğrudan `_exception_tree_contains_body_
# too_large`'a PARAMETRE olarak verilir (hiçbir zaman `raise` EDİLMEZ).
# ------------------------------------------------------------

_h08_cancelled = asyncio.CancelledError()

check(
    "H08a sağlama: asyncio.CancelledError bir Exception ÖRNEĞİ DEĞİLDİR",
    not isinstance(_h08_cancelled, Exception),
)

_h08_mixed_group = BaseExceptionGroup(
    "karışık grup", [_DraftingRequestBodyTooLarge(), _h08_cancelled],
)

check(
    "H08b sağlama: hedefi + CancelledError'ı içeren karışık grup BİLE bir Exception ÖRNEĞİ DEĞİLDİR "
    "(Python'un kendi grup kurma kuralı)",
    not isinstance(_h08_mixed_group, Exception),
)

check(
    "H08 KARIŞIK BaseExceptionGroup (hedef + CancelledError BİRLİKTE) -> False "
    "(413'e DÖNÜŞTÜRÜLMEMELİ - kontrol-akışı sinyali YUTULMAMALI)",
    _exception_tree_contains_body_too_large(_h08_mixed_group) is False,
)

# H08c - route/middleware'in KULLANDIĞI `except Exception` sınırının,
# bu KARIŞIK grubu zaten KENDİSİ hiç yakalamayacağının (dolayısıyla
# yardımcı fonksiyona BİLE ULAŞMAYACAĞININ) bağımsız kanıtı - GERÇEK
# bir `try/except Exception` bloğuyla, hiçbir görev/task iptal
# EDİLMEDEN.
_h08_caught_as_exception = False
try:
    try:
        raise _h08_mixed_group
    except Exception:
        _h08_caught_as_exception = True
except BaseExceptionGroup:
    _h08_caught_as_exception = False

check(
    "H08c `except Exception` sınırı KARIŞIK grubu YAKALAMIYOR/YUTMUYOR (otomatik yayılır)",
    _h08_caught_as_exception is False,
)


# ============================================================
# 1) LOOPBACK-OLMAYAN İSTEMCİ REDDİ (Row 18a/18b ile AYNI middleware,
#    ama BU route için de ÇALIŞTIĞININ pozitif kanıtı)
# ============================================================

with isolated_case():
    non_loopback_client = TestClient(app, client=("10.0.0.5", 12345))
    resp = non_loopback_client.get(f"/cases/{CASE_ID}/drafting-request")
    check("T01 loopback olmayan istemci GET drafting-request'te 403 alıyor", resp.status_code == 403)

    resp = non_loopback_client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=_BASE_FORM)
    check("T02 loopback olmayan istemci POST confirm'de 403 alıyor", resp.status_code == 403)


# ============================================================
# 2) CASE ALLOWLIST
# ============================================================

with isolated_case():
    resp = client.get("/cases/hic_boyle_bir_case_yok_route/drafting-request")
    check("T03 bilinmeyen case_id GET'te 404 alıyor", resp.status_code == 404)

    # TARGETED ROUTE SAFETY REMEDIATION - kök-neden: bu gövde BİLEREK
    # "yapısal olarak eksiksiz" tutulur (expected_current_input_hash/
    # csrf_token DAHİL, gerçek olmayan ama STRING değerlerle) - böylece
    # bu test YALNIZ case_id koşulunu izole eder. Eskiden bu iki alan
    # `_BASE_FORM`'da YOKTU; route FastAPI'nin otomatik `Form(...)`
    # bağımlılık çözümünü kullandığı için eksik zorunlu alan, case_id
    # kontrolüne HİÇ ULAŞILMADAN 422'ye düşüyordu. Route artık case_id'yi
    # gövdeye HİÇ dokunmadan EN BAŞTA çözüyor (bkz. `ui/main.py` -
    # `drafting_request_confirm`), bu yüzden gövde eksik OLSA BİLE 404
    # değişmez - ama test yine de "yapısal olarak eksiksiz" bir gövdeyle
    # yazılır (talimatın kendi şartı).
    complete_form_unknown_case = dict(
        _BASE_FORM, expected_current_input_hash="0" * 64,
        csrf_token="irrelevant_case_id_checked_first",
    )
    resp = client.post(
        "/cases/hic_boyle_bir_case_yok_route/drafting-request/confirm", data=complete_form_unknown_case,
    )
    check(
        "T04 bilinmeyen case_id POST confirm'de 404 alıyor (yapısal olarak EKSİKSİZ gövdeyle)",
        resp.status_code == 404,
    )
    check(
        "T04b T04: yanıt CSRF/form-doğrulama metni İÇERMİYOR (gerçekten case_id yolundan reddedildi)",
        "Güvenlik doğrulaması" not in resp.text and "form geçerli değil" not in resp.text,
    )


# ============================================================
# 3) GET SALT-OKUNUR DAVRANIŞ
# ============================================================

with isolated_case():
    resp = _get_fresh_context(CASE_ID)
    check("T05 GET drafting-request 200 dönüyor", resp.status_code == 200)
    check("T06 GET: kaydedilmiş girdi yokken uyarı banner'ı var", "henüz kaydedilmiş bir avukat girdisi yok" in resp.text)
    check("T07 GET hiçbir dosya YAZMADI", not draftreq.get_current_input_path(CASE_ID).exists())


# ============================================================
# 4) CSRF - HER BİR PARÇA (case_id, "drafting_request", "save",
#    expected_current_input_hash) - herhangi biri yanlışsa REDDEDİLİR.
# ============================================================

with isolated_case():
    resp = _get_fresh_context(CASE_ID)
    csrf_token = _extract_hidden_value(resp.text, "csrf_token")
    expected_hash = _extract_hidden_value(resp.text, "expected_current_input_hash")

    # 4a) token AÇIKÇA boş string olarak gönderiliyor (alan VAR ama
    # değeri "").
    form = dict(_BASE_FORM, expected_current_input_hash=expected_hash, csrf_token="")
    resp = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form)
    check("T08 boş csrf_token reddediliyor (CSRF_INVALID mesajı)", "Güvenlik doğrulaması başarısız" in resp.text)
    check("T09 T08: hiçbir dosya yazılmadı", not draftreq.get_current_input_path(CASE_ID).exists())

    # 4a-bis) token TAMAMEN YOK (form alanı hiç gönderilmedi) - "AÇIKÇA
    # boş" senaryosundan (T08) FARKLI bir kod yolu (`form_data.get(...)`
    # `None` döner) - targeted remediation §3'ün AYRICA istediği kapsam.
    form_missing_csrf = dict(_BASE_FORM, expected_current_input_hash=expected_hash)
    assert "csrf_token" not in form_missing_csrf
    resp = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form_missing_csrf)
    check(
        "T08b csrf_token TAMAMEN YOKSA da (form'da hiç gönderilmemiş) reddediliyor (CSRF_INVALID mesajı)",
        "Güvenlik doğrulaması başarısız" in resp.text,
    )
    check("T08c T08b: hiçbir dosya yazılmadı", not draftreq.get_current_input_path(CASE_ID).exists())

    # 4b) doğru token ama YANLIŞ expected_hash (CSRF hash'e BAĞLI)
    form = dict(_BASE_FORM, expected_current_input_hash="0" * 64, csrf_token=csrf_token)
    resp = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form)
    check("T10 doğru token + YANLIŞ expected_hash reddediliyor (CSRF parçalarından biri değişti)", "Güvenlik doğrulaması başarısız" in resp.text)

    # 4c) başka bir case için üretilmiş token (case_id parçası farklı)
    with isolated_case():
        pass  # yalnız iki ayrı case_id simüle etmek için CSRF'i elle üretiyoruz
    foreign_token = security.make_csrf_token(_CSRF_SECRET, "baska_case", "drafting_request", "save", expected_hash)
    form = dict(_BASE_FORM, expected_current_input_hash=expected_hash, csrf_token=foreign_token)
    resp = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form)
    check("T11 başka bir case_id için üretilmiş token reddediliyor", "Güvenlik doğrulaması başarısız" in resp.text)

    # 4d) doğru her şey - kabul edilmeli (pozitif kontrol)
    form = dict(_BASE_FORM, expected_current_input_hash=expected_hash, csrf_token=csrf_token)
    resp = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form)
    check("T12 DOĞRU CSRF (dört parça da doğru) kabul ediliyor (200)", resp.status_code == 200)
    check("T13 T12: sonuç sayfası kaydetmenin ÜRETİM ANLAMINA GELMEDİĞİNİ belirtiyor", "ÜRETİLMEDİ" in resp.text)


# ============================================================
# 5) AYNI-ORİJİN (Origin/Referer) KONTROLÜ
# ============================================================

with isolated_case():
    resp = _get_fresh_context(CASE_ID)
    csrf_token = _extract_hidden_value(resp.text, "csrf_token")
    expected_hash = _extract_hidden_value(resp.text, "expected_current_input_hash")

    form = dict(_BASE_FORM, expected_current_input_hash=expected_hash, csrf_token=csrf_token)
    resp = client.post(
        f"/cases/{CASE_ID}/drafting-request/confirm", data=form,
        headers={"origin": "https://evil.example.com"},
    )
    check("T14 farklı origin header'ı ile POST reddediliyor", "Güvenlik doğrulaması başarısız" in resp.text)
    check("T15 T14: hiçbir dosya yazılmadı", not draftreq.get_current_input_path(CASE_ID).exists())


# ============================================================
# 6) ONAY KUTUSU ZORUNLULUĞU
# ============================================================

with isolated_case():
    resp = _get_fresh_context(CASE_ID)
    csrf_token = _extract_hidden_value(resp.text, "csrf_token")
    expected_hash = _extract_hidden_value(resp.text, "expected_current_input_hash")

    form = dict(_BASE_FORM, expected_current_input_hash=expected_hash, csrf_token=csrf_token)
    del form["confirm_save"]
    resp = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form)
    check("T16 confirm_save checkbox İŞARETLENMEMİŞSE (form'da hiç YOK) reddediliyor", "onay kutusunu işaretlemelisiniz" in resp.text)
    check("T17 T16: hiçbir dosya yazılmadı", not draftreq.get_current_input_path(CASE_ID).exists())


# ============================================================
# 7) STALE-HASH REDDİ (HTTP katmanı üzerinden)
# ============================================================

with isolated_case():
    resp = _get_fresh_context(CASE_ID)
    csrf_token = _extract_hidden_value(resp.text, "csrf_token")
    expected_hash = _extract_hidden_value(resp.text, "expected_current_input_hash")

    form = dict(_BASE_FORM, expected_current_input_hash=expected_hash, csrf_token=csrf_token)
    client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form)  # ilk kayıt

    # AYNI (artık ESKİMİŞ) expected_hash/csrf_token ile İKİNCİ bir POST.
    resp2 = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form)
    check("T18 eskimiş (stale) expected_hash ile ikinci POST reddediliyor", "değişti" in resp2.text)


# ============================================================
# 8) 128 KiB GÖVDE SINIRI - Content-Length İLE VE Content-Length
#    OLMADAN (gerçek bayt sayımı)
# ============================================================

with isolated_case():
    resp = _get_fresh_context(CASE_ID)
    csrf_token = _extract_hidden_value(resp.text, "csrf_token")
    expected_hash = _extract_hidden_value(resp.text, "expected_current_input_hash")

    oversized_text = "a" * (_DRAFTING_REQUEST_MAX_BODY_BYTES + 4096)

    # 8a) TestClient normalde Content-Length header'ını KENDİSİ doğru
    # hesaplayıp gönderir - bu, "header VARSA ve sınırı aşıyorsa erken
    # reddet" yolunu sınar.
    form = dict(_BASE_FORM, expected_current_input_hash=expected_hash, csrf_token=csrf_token,
                lawyer_provided_text=oversized_text)
    resp = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form)
    check("T19 Content-Length İLE 128 KiB'yi aşan gövde 413 alıyor", resp.status_code == 413)
    check("T20 T19: gönderilen METİN yanıtta YOK (içerik sızmıyor)", oversized_text[:200] not in resp.text)
    check("T21 T19: hiçbir dosya yazılmadı", not draftreq.get_current_input_path(CASE_ID).exists())

    # 8b) Content-Length'İ KASITLI OLARAK YANLIŞ/eksik gönderen bir ham
    # istek - gerçek alınan bayt sayacının devreye girdiğinin kanıtı.
    import httpx

    body_str = "&".join(
        f"{k}={v}" for k, v in dict(
            _BASE_FORM, expected_current_input_hash=expected_hash, csrf_token=csrf_token,
            lawyer_provided_text=oversized_text,
        ).items()
    )
    body_bytes = body_str.encode("utf-8")

    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))

    async def _send_with_bad_content_length():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            headers = {
                "content-type": "application/x-www-form-urlencoded",
                "content-length": "10",  # KASITLI OLARAK YANLIŞ (çok düşük)
            }
            return await ac.post(
                f"/cases/{CASE_ID}/drafting-request/confirm", content=body_bytes, headers=headers,
            )

    import asyncio

    try:
        resp_bad_cl = asyncio.run(_send_with_bad_content_length())
        check(
            "T22 yanlış/düşük Content-Length + gerçek büyük gövde: gerçek bayt sayacı devreye girip 413 döndürüyor",
            resp_bad_cl.status_code == 413,
        )
        # FINAL EXCEPTIONGROUP BODY-LIMIT REMEDIATION - ek zorunlu
        # kapsam (§4): yanıt YALNIZ sabit metni içermeli - hiçbir
        # ExceptionGroup/traceback/dosya yolu/gönderilen serbest metin
        # sızmamalı.
        check(
            "T22-msg T22: yanıt YALNIZ sabit gövde-çok-büyük metnini içeriyor",
            resp_bad_cl.text.strip() == _DRAFTING_REQUEST_BODY_TOO_LARGE_MESSAGE,
        )
        check(
            "T22-noleak T22: yanıtta ExceptionGroup/Traceback/dosya yolu YOK",
            "ExceptionGroup" not in resp_bad_cl.text
            and "Traceback" not in resp_bad_cl.text
            and REPO_ROOT.name not in resp_bad_cl.text,
        )
        check(
            "T22-nofreetext T22: gönderilen serbest METİN yanıtta YOK (içerik sızmıyor)",
            oversized_text[:200] not in resp_bad_cl.text,
        )
    except Exception as error:
        check(
            "T22 yanlış/düşük Content-Length + gerçek büyük gövde: gerçek bayt sayacı devreye girip 413 döndürüyor",
            False, f"istisna: {error!r}",
        )

    check("T23 128 KiB testi: hiçbir dosya yazılmadı", not draftreq.get_current_input_path(CASE_ID).exists())

    # 8c) sınır İÇİNDE bir gövde NORMAL kabul edilmeli (pozitif kontrol,
    # var olan Row 18a/18b route'larının davranışı DEĞİŞMEDİĞİNİN de
    # dolaylı kanıtı - bu route'un KENDİSİ normal boyutlu istekleri
    # reddetmiyor).
    form_ok = dict(_BASE_FORM, expected_current_input_hash=expected_hash, csrf_token=csrf_token,
                    lawyer_provided_text="normal boyutlu metin")
    resp_ok = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form_ok)
    check("T24 sınır İÇİNDE normal gövde 413 DEĞİL, 200 alıyor", resp_ok.status_code == 200)

    # ------------------------------------------------------------
    # 8d) TARGETED ROUTE SAFETY REMEDIATION - ek zorunlu kapsam:
    # TAM SINIRDA (== 128 KiB) bir gövde YALNIZ boyut yüzünden
    # reddedilmemeli, SINIRIN 1 bayt ÜSTÜNDEKİ bir gövde 413 almalı,
    # ve Content-Length HİÇ OLMADAN + BİRDEN FAZLA ASGI parçası
    # (chunk) halinde gelen aşırı büyük bir gövde de kümülatif bayt
    # sayacı tarafından yakalanmalı. Gerçek alan uzunluk sınırları
    # (request_text<=5000, lawyer_provided_text<=50000 vb.) TOPLAMDA
    # 128 KiB'ye asla ulaşamayacağı için, route tarafından HİÇ
    # OKUNMAYAN (bu yüzden semantik doğrulamayı ETKİLEMEYEN) ayrı bir
    # `_padding` alanı yalnız HAM GÖVDE BOYUTUNU kontrollü şekilde
    # büyütmek için eklenir.
    # ------------------------------------------------------------

    def _urlencode_fields(fields):
        from urllib.parse import quote_plus
        return "&".join(f"{quote_plus(str(k))}={quote_plus(str(v))}" for k, v in fields.items()).encode("ascii")

    def _build_body_of_exact_size(total_target_bytes, csrf, hash_value):
        base_fields = dict(
            _BASE_FORM, expected_current_input_hash=hash_value, csrf_token=csrf,
            lawyer_provided_text="normal metin",
        )
        base_fields["_padding"] = ""
        base_len = len(_urlencode_fields(base_fields))
        pad_len = total_target_bytes - base_len
        assert pad_len >= 0, (
            f"hedef boyut ({total_target_bytes}) dolgusuz taban gövdeden "
            f"({base_len}) KÜÇÜK olamaz"
        )
        base_fields["_padding"] = "a" * pad_len
        body = _urlencode_fields(base_fields)
        assert len(body) == total_target_bytes, (len(body), total_target_bytes)
        return body

    # 8d-i) TAM SINIRDA (== 128 KiB) - route'un KENDİ okuduğu alanlar
    # geçerli kaldığı için bu GERÇEK bir kayıt üretmeli (200).
    resp = _get_fresh_context(CASE_ID)
    csrf_token = _extract_hidden_value(resp.text, "csrf_token")
    expected_hash = _extract_hidden_value(resp.text, "expected_current_input_hash")

    exact_limit_body = _build_body_of_exact_size(
        _DRAFTING_REQUEST_MAX_BODY_BYTES, csrf_token, expected_hash,
    )

    async def _send_exact_limit_body():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(
                f"/cases/{CASE_ID}/drafting-request/confirm", content=exact_limit_body,
                headers={"content-type": "application/x-www-form-urlencoded"},
            )

    resp_exact = asyncio.run(_send_exact_limit_body())
    check(
        "T22b TAM 128 KiB'lik (== sınır) gövde YALNIZ boyut yüzünden reddedilmiyor (200 alıyor)",
        resp_exact.status_code == 200,
    )

    # T22b'nin GERÇEKTEN yazdığı dosyanın ham baytları - T22c/T22d'nin
    # (ikisi de 413 ile reddedilmesi beklenen) bu dosyayı HİÇ
    # DEĞİŞTİRMEDİĞİNİN sonradan kanıtlanması için burada saklanır.
    _post_t22b_current_bytes = draftreq.get_current_input_path(CASE_ID).read_bytes()

    # 8d-ii) SINIRIN 1 BAYT ÜSTÜ (== 128 KiB + 1) - 413 almalı. T22b
    # bir önceki kaydı DEĞİŞTİRDİĞİ için (hash artık eskimiş olurdu),
    # yine de bu test CSRF/hash'e BAKMADAN yalnız boyut yüzünden
    # reddedileceğinden (Content-Length beyanı ASGI middleware'inde
    # HERHANGİ bir form/CSRF ayrıştırmasından ÖNCE kontrol edilir),
    # T22b'nin ARTIK ESKİMİŞ olan aynı csrf/hash değerlerini yeniden
    # kullanmak GEÇERLİDİR - amaç yalnız ham boyut sınırını sınamaktır.
    one_over_limit_body = _build_body_of_exact_size(
        _DRAFTING_REQUEST_MAX_BODY_BYTES + 1, csrf_token, expected_hash,
    )

    async def _send_one_byte_over_body():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(
                f"/cases/{CASE_ID}/drafting-request/confirm", content=one_over_limit_body,
                headers={"content-type": "application/x-www-form-urlencoded"},
            )

    resp_one_over = asyncio.run(_send_one_byte_over_body())
    check(
        "T22c 128 KiB + 1 bayt'lık gövde 413 alıyor (tam sınırın HEMEN üstü)",
        resp_one_over.status_code == 413,
    )

    # 8d-iii) Content-Length HİÇ YOK + gövde BİRDEN FAZLA ASGI mesajıyla
    # (chunk) geliyor - kümülatif bayt sayacının TEK BİR mesaja değil
    # TÜM mesajların TOPLAMINA baktığının kanıtı. İçerik yalnız dolgu
    # amaçlı ("a" karakterleri) - zaten yalnız HAM BOYUT yüzünden
    # reddedilmesi bekleniyor, form hiçbir zaman ayrıştırılana kadar
    # ULAŞMIYOR.
    async def _chunked_filler(total_bytes, chunk_size=4096):
        remaining = total_bytes
        while remaining > 0:
            piece = min(chunk_size, remaining)
            yield b"a" * piece
            remaining -= piece

    oversized_chunked_total = _DRAFTING_REQUEST_MAX_BODY_BYTES + 4096

    async def _send_chunked_no_content_length():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            headers = {"content-type": "application/x-www-form-urlencoded"}
            return await ac.post(
                f"/cases/{CASE_ID}/drafting-request/confirm",
                content=_chunked_filler(oversized_chunked_total), headers=headers,
            )

    try:
        resp_chunked = asyncio.run(_send_chunked_no_content_length())
        check(
            "T22d Content-Length HİÇ YOKKEN + çok-parçalı (chunked) aşırı büyük gövde: "
            "kümülatif bayt sayacı 413 döndürüyor",
            resp_chunked.status_code == 413,
        )
        # FINAL EXCEPTIONGROUP BODY-LIMIT REMEDIATION - ek zorunlu
        # kapsam (§4): yanıt YALNIZ sabit metni içermeli - hiçbir
        # ExceptionGroup/traceback/dosya yolu sızmamalı.
        check(
            "T22d-msg T22d: yanıt YALNIZ sabit gövde-çok-büyük metnini içeriyor",
            resp_chunked.text.strip() == _DRAFTING_REQUEST_BODY_TOO_LARGE_MESSAGE,
        )
        check(
            "T22d-noleak T22d: yanıtta ExceptionGroup/Traceback/dosya yolu YOK",
            "ExceptionGroup" not in resp_chunked.text
            and "Traceback" not in resp_chunked.text
            and REPO_ROOT.name not in resp_chunked.text,
        )
    except Exception as error:
        check(
            "T22d Content-Length HİÇ YOKKEN + çok-parçalı (chunked) aşırı büyük gövde: "
            "kümülatif bayt sayacı 413 döndürüyor",
            False, f"istisna: {error!r}",
        )

    check(
        "T22e T22c/T22d: (413 ile reddedilen istekler) mevcut girdi dosyasını HİÇ DEĞİŞTİRMEDİ "
        "(T22b'nin meşru kaydından SONRA byte-düzeyinde aynı kaldı)",
        draftreq.get_current_input_path(CASE_ID).read_bytes() == _post_t22b_current_bytes,
    )


# ============================================================
# 9) MEVCUT ROW 18A/18B ROUTE'LARI BU ORTA-KATMANDAN ETKİLENMEDİ
#    (route-özgü olduğunun pozitif kanıtı)
# ============================================================

with isolated_case():
    resp = client.get(f"/cases/{CASE_ID}")
    check("T25 mevcut GET /cases/{case_id} (Row 18a) yeni middleware'den ETKİLENMEDİ (200 veya beklenen bir kod)", resp.status_code in (200, 404, 500) and resp.status_code != 413)


# ============================================================
# 10) FORM GEÇERSİZLİĞİ - SABİT TARAYICI HATASI, İÇERİK SIZDIRMAZ
# ============================================================

with isolated_case():
    resp = _get_fresh_context(CASE_ID)
    csrf_token = _extract_hidden_value(resp.text, "csrf_token")
    expected_hash = _extract_hidden_value(resp.text, "expected_current_input_hash")

    secret_marker = "GIZLI_HUKUKI_METIN_ASLA_GORUNMEMELI_9f3a"
    form = dict(
        _BASE_FORM, expected_current_input_hash=expected_hash, csrf_token=csrf_token,
        issue_selection_mode="specific",  # ama selected_issue_ids YOK -> DraftingRequestFormError
        request_text=secret_marker,
    )
    resp = client.post(f"/cases/{CASE_ID}/drafting-request/confirm", data=form)
    check("T26 geçersiz form (specific + boş seçim) SABİT hata mesajıyla reddediliyor", "Gönderilen form geçerli değil" in resp.text)
    check("T27 T26: gönderilen SERBEST METİN yanıtta YOK", secret_marker not in resp.text)


# ============================================================
# 11) GERÇEK data/ ve src/ AĞAÇLARININ HİÇBİR TESTLE DEĞİŞMEDİĞİNİN
#     BYTE-DÜZEYİNDE KANITI
# ============================================================

_after_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)
check(
    "T28 GERÇEK data/ ve src/ ağaçları bu test dosyasıyla DEĞİŞMEDİ (byte-düzeyinde)",
    _before_snapshot == _after_snapshot,
    f"fark={set(_before_snapshot) ^ set(_after_snapshot)}",
)


print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
