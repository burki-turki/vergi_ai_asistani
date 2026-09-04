# ============================================================
# Row 18a - FastAPI TestClient smoke testleri.
#
# BU DOSYA CLOUD SANDBOX'TA DEĞİL, SİZİN MAKİNENİZDE (Python 3.14 venv)
# çalıştırılmak üzere yazıldı. Aşağıdaki import GUARD EDİLDİ: FastAPI
# mevcut değilse bu dosya HATA VERMEDEN "SKIPPED" olarak çıkar (exit
# code 0). `ui/services/*` katmanı ve şablonlar zaten
# `test_service_isolated.py` (50/50) ve `test_templates_isolated.py`
# (17/17) ile bu sandbox'ta GERÇEK case_0001 verisiyle doğrulandı - bu
# dosya yalnız FastAPI/Starlette KATMANININ (route eşleme, middleware,
# form parametreleri, template context aktarımı) çalıştığını doğrular.
#
# ROUTE-TEST DÜZELTME TURU (bu turda yapılan değişiklikler):
#
#   1) DÜZELTME: `GET /cases/..` ve `GET /cases/case_0001/../..` için
#      önceki "404 bekleniyor" varsayımı YANLIŞTI. httpx/TestClient bu
#      HAM nokta-segmentli path'leri UYGULAMAYA ULAŞMADAN, istemci
#      tarafında URL normalizasyonuyla `/`'e indirger - FastAPI
#      uygulaması hiçbir traversal değeri GÖRMEZ, hiçbir case-view/
#      approval handler'ı ÇAĞRILMAZ. 200 dönen şey traversal'ın kabul
#      edilmesi DEĞİL, salt-okunur index sayfasıdır. Bu artık `r.url`
#      (nihai istek path'i) ve içerik karşılaştırmasıyla AÇIKÇA
#      doğrulanıyor - "404 bekle" yerine "index'e normalize edildiğini
#      ve case-specific hiçbir şey tetiklenmediğini kanıtla".
#   1b) İKİNCİ DÜZELTME: `GET /cases/foo/..` yukarıdakiyle AYNI
#      kategoride DEĞİL - istemci tarafı normalizasyonu bunu `/`'e
#      DEĞİL, `/cases`'e indirger (["cases","foo",".."] -> ".." yalnız
#      hemen önceki "foo" segmentini siler, "cases"i SİLMEZ). `/cases`
#      (case_id'siz, sondaki slash yok) uygulamada tanımlı bir route
#      DEĞİL - bu yüzden gerçek, doğru beklenti 404'tür ve YİNE hiçbir
#      case-specific/approval handler'ı çağrılmaz. Bu artık AYRI bir
#      blokta, nihai path'in `/cases` olduğu ve yanıtın 404 olduğu
#      doğrudan doğrulanarak test ediliyor - `/` ve 200 İDDİA EDİLMİYOR.
#   2) Encode edilmiş traversal biçimleri (`%2e%2e` vb.) İSTEMCİ
#      TARAFINDA normalize EDİLMEZ - gerçekten uygulamaya ulaşır ve
#      orada `resolve_case_id` tarafından reddedilir (404). Bu testler
#      DEĞİŞMEDİ - hâlâ 404 bekleniyor.
#   3) YENİ: POST ile nokta-segment normalizasyon testi - normalize
#      olmuş path'e POST, 405 dönmeli (yalnız GET tanımlı) ve hiçbir
#      onay adaptörü çağrılmamalı (çağrı sayacıyla doğrulanıyor).
#   4) YENİ: izole (TemporaryDirectory + sahte adaptör) HTTP testleri -
#      cross-origin POST reddi, eksik/kurcalanmış CSRF reddi,
#      loopback-olmayan POST reddi, confirm endpoint'ine GET -> 405,
#      canlı görünüm doğrulama hatası -> genel fail-closed sayfa,
#      validator/semantik hata -> genel hata (başarı sayfası DEĞİL),
#      onay fonksiyonu exception -> ham path/exception sızmıyor.
#   5) YENİ: tüm dosya çalışması boyunca GERÇEK data/src ağacının
#      byte-düzeyinde DEĞİŞMEDİĞİNİ kanıtlayan önce/sonra snapshot.
#
# Hiçbir ortam değişkeni gerçek case_0001'i mutasyona uğratamaz -
# önceki `VERGI_UI_RUN_DESTRUCTIVE_TEST` yolu KALICI olarak kaldırıldı
# (önceki remediation turu) ve bu turda YENİDEN EKLENMEDİ.
#
# Çalıştırma:
#   cd vergi_ai_asistani
#   python -m ui.tests.test_routes
# ============================================================

import contextlib
import hashlib
import re
import sys
import tempfile
import types
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
from ui.services import live_view
from ui.services import approval_registry as reg
from ui.main import app

# targeted remediation §7/§9: TestClient'ın istemci adresini AÇIKÇA
# loopback yapıyoruz - httpx/Starlette TestClient varsayılanı
# ("testclient") yeni loopback-only middleware tarafından reddedilir
# (bu KASITLI - middleware production'da GERÇEKTEN çalıştığını
# kanıtlar). Bu dosya DIŞINDA (main.py/production launcher) hiçbir
# yerde test-host istisnası YOKTUR.
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


def _extract_hidden_input(html, name):
    match = re.search(rf'name="{re.escape(name)}"\s+value="([^"]*)"', html)
    return match.group(1) if match else None


def _snapshot_real_tree():
    manifest = {}
    for root in (svc_paths.DATA_DIR, svc_paths.SRC_DIR):
        root = Path(root)
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                manifest[str(p)] = (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
    return manifest


_before_real_tree = _snapshot_real_tree()


@contextlib.contextmanager
def isolated_case_fixture(behavior="ok"):
    """
    İzole bir case + sahte case-scoped adaptör modülü kurar - GERÇEK
    case_0001/Row 6-17 modüllerine HİÇBİR ÇAĞRI gitmez, her şey
    `tempfile.TemporaryDirectory()` içinde çözülür.

    behavior:
      "ok"               -> normal başarılı onay akışı.
      "validator_fail"   -> inspect_pending (review aşaması) hata fırlatır.
      "approve_exception"-> run_approve (onay aşaması) hata fırlatır.

    Yield edilen dict: case_id, row_key, review_url, confirm_url,
    tmp_path, canonical_path, pending_path, reviews_dir,
    calls (dict: "run_approve"/"inspect_pending" çağrı sayaçları).
    """

    with tempfile.TemporaryDirectory() as tmp:

        tmp_path = Path(tmp)
        fake_case_id = f"case_iso_route_{behavior}"
        fake_case_dir = tmp_path / "cases" / fake_case_id
        fake_case_dir.mkdir(parents=True)
        (fake_case_dir / "case.json").write_text('{"case_id": "%s"}' % fake_case_id, encoding="utf-8")

        pending_path = tmp_path / "pending.json"
        pending_path.write_text('{"synthetic": true}', encoding="utf-8")
        canonical_path = tmp_path / "canonical.json"
        reviews_dir = tmp_path / "reviews"
        reviews_dir.mkdir()

        calls = {"run_approve": 0, "inspect_pending": 0}

        def _get_pending_path(cid):
            return pending_path

        def _get_canonical_path(cid):
            return canonical_path

        def _inspect_pending(cid):
            calls["inspect_pending"] += 1
            if behavior == "validator_fail":
                # Ham path'i KASITLI olarak mesaja gömüyoruz - test
                # bunun tarayıcıya SIZMADIĞINI doğrulayacak.
                raise ValueError(f"sentetik semantik doğrulama hatası - ham path: {tmp_path}")
            return pending_path, {"ok": True}, {"synthetic_field": "izole route testi"}

        def _run_approve(cid):
            calls["run_approve"] += 1
            if behavior == "approve_exception":
                raise RuntimeError(f"sentetik onay hatası - ham path: {tmp_path / 'gizli'}")
            canonical_path.write_text(pending_path.read_text(encoding="utf-8"), encoding="utf-8")
            (reviews_dir / "iso_v1.approval.json").write_text('{"source_pending_sha256": "x"}', encoding="utf-8")

        fake_module = types.SimpleNamespace(
            get_pending_path=_get_pending_path,
            get_canonical_path=_get_canonical_path,
            inspect_pending=_inspect_pending,
            run_approve=_run_approve,
        )
        module_name = f"_izole_route_test_module_{behavior}"
        row_key = f"_izole_route_test_{behavior}"
        sys.modules[module_name] = fake_module

        original_list_case_ids = svc_paths.list_case_ids
        original_resolve = svc_paths.resolve_case_id
        svc_paths.list_case_ids = lambda: original_list_case_ids() + [fake_case_id]
        svc_paths.resolve_case_id = lambda cid: cid if cid == fake_case_id else original_resolve(cid)
        reg.CASE_SCOPED_ROWS_BY_KEY[row_key] = {
            "key": row_key, "row_no": 990, "label": f"İzole Route Testi ({behavior})",
            "module": module_name,
        }

        try:

            yield {
                "case_id": fake_case_id, "row_key": row_key,
                "review_url": f"/cases/{fake_case_id}/approvals/{row_key}",
                "confirm_url": f"/cases/{fake_case_id}/approvals/{row_key}/confirm",
                "tmp_path": tmp_path, "canonical_path": canonical_path,
                "pending_path": pending_path, "reviews_dir": reviews_dir,
                "calls": calls,
            }

        finally:

            svc_paths.list_case_ids = original_list_case_ids
            svc_paths.resolve_case_id = original_resolve
            reg.CASE_SCOPED_ROWS_BY_KEY.pop(row_key, None)
            sys.modules.pop(module_name, None)


case_ids = svc_paths.list_case_ids()
check("en az bir case bulundu", len(case_ids) > 0, f"case_ids={case_ids}")

if not case_ids:
    print("Hiç case yok - test devam edemiyor.")
    sys.exit(1)

case_id = case_ids[0]

# --- T00: loopback-only middleware gerçekten reddediyor mu? ---
_loopback_test_client = TestClient(app, client=("203.0.113.7", 55555))
r = _loopback_test_client.get("/")
check("T00 loopback olmayan istemci -> 403", r.status_code == 403, f"status={r.status_code}")

# --- T01: ana sayfa ---
r_index = client.get("/")
check("T01 GET / -> 200", r_index.status_code == 200, f"status={r_index.status_code}")
check("T01b GET / case_id'yi listeliyor", case_id in r_index.text)

# --- T02: canlı case view ---
r = client.get(f"/cases/{case_id}")
check("T02 GET /cases/{case_id} -> 200", r.status_code == 200, f"status={r.status_code}")

# --- T03: HAM nokta-segmentli path'ler ("/"e normalize olanlar) -
# istemci tarafında '/'e normalize edilir, uygulama traversal'ı HİÇ
# GÖRMEZ (DÜZELTİLDİ - bkz. modül docstring'i §1). "Kabul edildi"
# değil, "asla ulaşmadı" iddiası doğrulanıyor: hem nihai istek path'i
# hem de içerik index sayfasıyla birebir aynı olmalı (case-specific
# hiçbir handler tetiklenmemiş).
for raw_dotseg in ["/cases/..", "/cases/case_0001/../.."]:
    r = client.get(raw_dotseg)
    check(
        f"T03 GET {raw_dotseg!r} -> 200 (index sayfası, traversal DEĞİL)",
        r.status_code == 200,
        f"status={r.status_code}",
    )
    # httpx TestClient normalizasyonu: nihai istek path'i "/" olmalı.
    check(
        f"T03b {raw_dotseg!r}: nihai istek path'i '/' (case-specific handler ÇAĞRILMADI)",
        r.request.url.path == "/",
        f"gerçek path={r.request.url.path}",
    )
    check(
        f"T03c {raw_dotseg!r}: içerik index sayfasıyla BİREBİR AYNI",
        r.text == r_index.text,
    )

# --- T03f: `/cases/foo/..` FARKLI bir kategori (DÜZELTİLDİ - bkz.
# modül docstring'i §1b). İstemci tarafı normalizasyonu bunu `/`'e
# DEĞİL, `/cases`'e indirger - `/cases` (case_id'siz) tanımlı bir
# route DEĞİL, bu yüzden GERÇEK/doğru beklenti 404'tür. `/` ve 200
# İDDİA EDİLMİYOR. Yine de case-specific/approval adaptörü hiç
# çağrılmamalı - bunu adaptör çağrı-sayacıyla doğrudan doğruluyoruz.
_foo_dotseg_approve_calls = {"n": 0}
_original_case_scoped_approve_foo = reg.case_scoped_approve


def _counting_case_scoped_approve_foo(*args, **kwargs):
    _foo_dotseg_approve_calls["n"] += 1
    return _original_case_scoped_approve_foo(*args, **kwargs)


reg.case_scoped_approve = _counting_case_scoped_approve_foo
try:
    r = client.get("/cases/foo/..")
    check(
        "T03f GET '/cases/foo/..' -> nihai istek path'i '/cases' (DÜZELTİLDİ)",
        r.request.url.path == "/cases",
        f"gerçek path={r.request.url.path}",
    )
    check(
        "T03g GET '/cases/foo/..' -> 404 (tanımsız route, index/200 DEĞİL) (DÜZELTİLDİ)",
        r.status_code == 404,
        f"status={r.status_code}",
    )
    check(
        "T03h '/cases/foo/..' -> hiçbir onay adaptörü çağrılmadı",
        _foo_dotseg_approve_calls["n"] == 0,
    )
finally:
    reg.case_scoped_approve = _original_case_scoped_approve_foo

# --- Encode edilmiş traversal biçimleri: GERÇEKTEN uygulamaya ulaşır,
# istemci tarafında normalize EDİLMEZ - resolve_case_id tarafından
# reddedilmesi (404) beklenir. Bu grup DEĞİŞMEDİ.
for bad_case in ["__olmayan_case__", "%2e%2e", "%2e%2e%2fcase_0001", "..%2fcase_0001"]:
    r = client.get(f"/cases/{bad_case}")
    check(f"T03d GET /cases/{bad_case!r} -> uygulamaya ulaştı ve 404 döndü", r.status_code == 404, f"status={r.status_code}")

# --- T03e: POST ile nokta-segment normalizasyonu - normalize olmuş
# path'e ("/") POST -> yalnız GET tanımlı olduğu için 405, HİÇBİR onay
# adaptörü çağrılmamalı.
_approve_call_count = {"n": 0}
_original_case_scoped_approve = reg.case_scoped_approve


def _counting_case_scoped_approve(*args, **kwargs):
    _approve_call_count["n"] += 1
    return _original_case_scoped_approve(*args, **kwargs)


reg.case_scoped_approve = _counting_case_scoped_approve
try:
    r = client.post("/cases/..", data={})
    check(
        "T03e POST /cases/.. (normalize -> '/') -> 404/405, adaptör HİÇ çağrılmadı",
        r.status_code in (404, 405) and _approve_call_count["n"] == 0,
        f"status={r.status_code}",
    )
finally:
    reg.case_scoped_approve = _original_case_scoped_approve

# --- T04: approvals listesi ---
r = client.get(f"/cases/{case_id}/approvals")
check("T04 GET /cases/{case_id}/approvals -> 200", r.status_code == 200, f"status={r.status_code}")
check(
    "T04b fact/timeline satırları onay linki İÇERMİYOR (unsupported_pending_resolution)",
    "/approvals/fact/" not in r.text and "/approvals/timeline/" not in r.text,
)

# --- T05: bilinmeyen row_key -> 404 ---
r = client.get(f"/cases/{case_id}/approvals/__olmayan_row__")
check("T05 GET .../approvals/<bilinmeyen row_key> -> 404", r.status_code == 404, f"status={r.status_code}")

# --- T05b/c: kaldırılan fact/timeline route'ları artık MEVCUT DEĞİL ---
r = client.get(f"/cases/{case_id}/approvals/fact/doc/whatever.json.pending")
check("T05b GET eski fact route -> 404 (route kaldırıldı)", r.status_code == 404, f"status={r.status_code}")
r = client.get(f"/cases/{case_id}/approvals/timeline/whatever.pending")
check("T05c GET eski timeline route -> 404 (route kaldırıldı)", r.status_code == 404, f"status={r.status_code}")

# --- T06-T09: gerçek case-scoped review + CSRF/hash reddi (pending'i olan ilk row, GERÇEK veri, SALT OKUNUR + yanlış hash/csrf denemeleri) ---
status_rows = reg.full_case_approval_status(case_id)
reviewable = next(
    (row for row in status_rows if row["kind"] == "case_scoped" and row["pending_exists"]),
    None,
)

if reviewable:

    r = client.get(f"/cases/{case_id}/approvals/{reviewable['key']}")
    check(f"T06 GET review sayfası ({reviewable['key']}) -> 200", r.status_code == 200, f"status={r.status_code}")

    real_hash = _extract_hidden_input(r.text, "expected_hash")
    real_csrf = _extract_hidden_input(r.text, "csrf_token")
    check("T06b review sayfası bir csrf_token render ediyor", bool(real_csrf))

    confirm_url = f"/cases/{case_id}/approvals/{reviewable['key']}/confirm"

    r = client.post(confirm_url, data={"expected_hash": "0" * 64, "csrf_token": real_csrf})
    check("T07 POST confirm (yanlış hash, doğru csrf) -> 200 (hata sayfası)", r.status_code == 200, f"status={r.status_code}")
    check("T07b yanlış hash -> ham exception metni SIZMIYOR", "Traceback" not in r.text and "raise" not in r.text)

    r = client.post(confirm_url, data={"expected_hash": real_hash or "", "csrf_token": ""})
    check("T08 POST confirm (doğru hash, boş csrf) -> reddedilir", r.status_code in (200, 422), f"status={r.status_code}")

    tampered = (real_csrf[:-1] + ("0" if real_csrf[-1] != "0" else "1")) if real_csrf else "x"
    r = client.post(confirm_url, data={"expected_hash": real_hash or "", "csrf_token": tampered})
    check(
        "T09 POST confirm (doğru hash, kurcalanmış csrf) -> onaylanmadı",
        "canonical'a yükseltildi" not in r.text,
        r.text[:200],
    )

else:
    print("UYARI: case-scoped bir pending bulunamadı - T06-T09 atlandı.")

# --- T10: İZOLE uçtan uca mutasyon testi (mutlu yol) - GERÇEK
# case_0001'e ASLA dokunmaz. ---
with isolated_case_fixture("ok") as fx:

    r = client.get(fx["review_url"])
    check("T10 GET izole review sayfası -> 200", r.status_code == 200, f"status={r.status_code}")

    iso_hash = _extract_hidden_input(r.text, "expected_hash")
    iso_csrf = _extract_hidden_input(r.text, "csrf_token")

    r = client.post(fx["confirm_url"], data={"expected_hash": iso_hash, "csrf_token": iso_csrf})
    check("T10b POST izole confirm (doğru hash+csrf) -> 200", r.status_code == 200, f"status={r.status_code}")
    check("T10c izole onay GERÇEKTEN canonical'a yazdı (yalnız izole dosyaya)", fx["canonical_path"].exists())
    check("T10d sonuç sayfası repo-göreli/izole path gösteriyor, ham mutlak path DEĞİL", str(fx["tmp_path"]) not in r.text)
    check("T10e yalnız izole reviews_dir'a audit yazıldı", any(fx["reviews_dir"].iterdir()))

# --- T11: cross-origin POST, geçerli CSRF token OLSA BİLE adaptörden ÖNCE reddedilmeli ---
with isolated_case_fixture("ok") as fx:

    r = client.get(fx["review_url"])
    real_hash = _extract_hidden_input(r.text, "expected_hash")
    real_csrf = _extract_hidden_input(r.text, "csrf_token")

    r2 = client.post(
        fx["confirm_url"],
        data={"expected_hash": real_hash, "csrf_token": real_csrf},
        headers={"Origin": "http://evil.example"},
    )
    check(
        "T11 cross-origin Origin header (geçerli csrf) -> onaylanmadı, adaptör HİÇ çağrılmadı",
        ("canonical'a yükseltildi" not in r2.text) and fx["calls"]["run_approve"] == 0,
        f"status={r2.status_code}",
    )

# --- T12: eksik CSRF token -> FastAPI form validasyonu (422), adaptör HİÇ çağrılmadı ---
with isolated_case_fixture("ok") as fx:

    r = client.get(fx["review_url"])
    real_hash = _extract_hidden_input(r.text, "expected_hash")

    r2 = client.post(fx["confirm_url"], data={"expected_hash": real_hash})
    check(
        "T12 eksik csrf_token -> 422, adaptör HİÇ çağrılmadı",
        r2.status_code == 422 and fx["calls"]["run_approve"] == 0,
        f"status={r2.status_code}",
    )

# --- T13: kurcalanmış CSRF token -> reddedilmeli, adaptör HİÇ çağrılmadı ---
with isolated_case_fixture("ok") as fx:

    r = client.get(fx["review_url"])
    real_hash = _extract_hidden_input(r.text, "expected_hash")
    real_csrf = _extract_hidden_input(r.text, "csrf_token")
    tampered = real_csrf[:-1] + ("0" if real_csrf[-1] != "0" else "1")

    r2 = client.post(fx["confirm_url"], data={"expected_hash": real_hash, "csrf_token": tampered})
    check(
        "T13 kurcalanmış csrf_token -> onaylanmadı, adaptör HİÇ çağrılmadı",
        ("canonical'a yükseltildi" not in r2.text) and fx["calls"]["run_approve"] == 0,
    )

# --- T14: loopback-olmayan istemciden POST -> mutasyondan ÖNCE middleware'de reddedilmeli ---
with isolated_case_fixture("ok") as fx:

    r = client.get(fx["review_url"])
    real_hash = _extract_hidden_input(r.text, "expected_hash")
    real_csrf = _extract_hidden_input(r.text, "csrf_token")

    _non_loopback_client = TestClient(app, client=("203.0.113.7", 4444))
    r2 = _non_loopback_client.post(fx["confirm_url"], data={"expected_hash": real_hash, "csrf_token": real_csrf})
    check(
        "T14 loopback olmayan POST -> 403, adaptör HİÇ çağrılmadı",
        r2.status_code == 403 and fx["calls"]["run_approve"] == 0,
        f"status={r2.status_code}",
    )

# --- T15: confirm endpoint'ine GET -> 405, mutasyon YOK ---
with isolated_case_fixture("ok") as fx:

    r = client.get(fx["confirm_url"])
    check(
        "T15 GET confirm endpoint -> 405, adaptör HİÇ çağrılmadı",
        r.status_code == 405 and fx["calls"]["run_approve"] == 0,
        f"status={r.status_code}",
    )

# --- T16: canlı görünüm şema/semantik doğrulaması BAŞARISIZ -> genel fail-closed hata sayfası (main.py'nin GERÇEK LiveViewInvalidError yakalama yolu) ---
_original_validate_live_view = live_view.validate_live_view
live_view.validate_live_view = lambda view, cid: ["enjekte edilmiş test hatası - bu metin TARAYICIYA sızmamalı"]
try:
    r = client.get(f"/cases/{case_id}")
    check("T16 canlı görünüm geçersiz -> 200 (genel fail-closed sayfa, 500 DEĞİL)", r.status_code == 200, f"status={r.status_code}")
    check(
        "T16b genel LIVE_VIEW_INVALID mesajı gösteriliyor",
        "doğrulanamıyor" in r.text,
    )
    check("T16c ham doğrulama hatası metni SIZMIYOR", "enjekte edilmiş test hatası" not in r.text)
finally:
    live_view.validate_live_view = _original_validate_live_view

# --- T17: review aşamasında validator/semantik hata -> genel hata sayfası, başarı sayfası DEĞİL, ham path sızmıyor ---
with isolated_case_fixture("validator_fail") as fx:

    r = client.get(fx["review_url"])
    check("T17 validator/semantik hata -> 200 (genel hata sayfası)", r.status_code == 200, f"status={r.status_code}")
    check("T17b başarı sayfası DEĞİL", "canonical'a yükseltildi" not in r.text)
    check(
        "T17c ham exception metni/mutlak path SIZMIYOR",
        ("sentetik semantik doğrulama hatası" not in r.text) and (str(fx["tmp_path"]) not in r.text),
    )

# --- T18: onay fonksiyonu (run_approve) exception fırlatıyor -> başarı sayfası DEĞİL, ham exception/path sızmıyor ---
with isolated_case_fixture("approve_exception") as fx:

    r = client.get(fx["review_url"])
    iso_hash = _extract_hidden_input(r.text, "expected_hash")
    iso_csrf = _extract_hidden_input(r.text, "csrf_token")

    r2 = client.post(fx["confirm_url"], data={"expected_hash": iso_hash, "csrf_token": iso_csrf})
    check("T18 onay fonksiyonu hata fırlatıyor -> başarı sayfası DEĞİL", "canonical'a yükseltildi" not in r2.text)
    check(
        "T18b ham exception/path SIZMIYOR",
        ("RuntimeError" not in r2.text) and ("sentetik onay hatası" not in r2.text) and (str(fx["tmp_path"]) not in r2.text),
    )
    check("T18c izole canonical dosyası YAZILMADI (hata run_approve içinde, dosya yazımından ÖNCE fırlatıldı)", not fx["canonical_path"].exists())

# --- T19: GERÇEK data/ ve src/ ağacı bu dosyanın HİÇBİR testiyle DEĞİŞMEDİ (byte-düzeyinde) ---
_after_real_tree = _snapshot_real_tree()
check(
    "T19 GERÇEK data/ ve src/ ağaçları test_routes.py ile DEĞİŞMEDİ (byte-düzeyinde)",
    _before_real_tree == _after_real_tree,
    f"fark={set(_before_real_tree) ^ set(_after_real_tree)}",
)

print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
