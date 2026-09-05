# ============================================================
# Row 18b - FastAPI TestClient smoke testleri (Layer B inceleme
# kararları route'ları: GET /cases/{case_id}/reviews,
# GET/POST /cases/{case_id}/reviews/{review_kind}/{record_id}[/confirm]).
#
# BU DOSYA CLOUD SANDBOX'TA DEĞİL, SİZİN MAKİNENİZDE (Python 3.14 venv)
# çalıştırılmak üzere yazıldı. Aşağıdaki import GUARD EDİLDİ: FastAPI
# mevcut değilse bu dosya HATA VERMEDEN "SKIPPED" olarak çıkar (exit
# code 0). `ui/services/review_registry.py` katmanı ve yeni şablonlar
# zaten `test_review_service_isolated.py` ve `test_review_templates_isolated.py`
# ile bu sandbox'ta GERÇEK case_0001 verisiyle doğrulandı - bu dosya
# yalnız FastAPI/Starlette KATMANININ (route eşleme, middleware, form
# parametreleri, CSRF/aynı-origin/loopback koruması, template
# context aktarımı) çalıştığını doğrular.
#
# TARGETED REMEDIATION (2026-09-05) - KÖK NEDEN VE DÜZELTME:
# önceki turda bu dosyadaki `isolated_review_fixture`, GERÇEK
# `evidence_validator.validate_evidence_analysis`'in minimal/sentetik
# bir `evidence.json` ile ÇAĞRILMASINA izin veriyordu. O validator
# `raise_on_error` bayrağından TAMAMEN BAĞIMSIZ olarak, KENDİ ön koşul
# yüklemesinde (`load_case(case_id)`) sentetik case_id için GERÇEK
# `data/cases/case_iso_route_review/case.json` dosyasını aramaya
# çalışıp `FileNotFoundError` fırlatıyordu - izolasyon İHLALİ
# (kök neden `src/evidence_validator.py`'de, LOCKED, değiştirilmedi).
# Düzeltme İKİ KATMANLIDIR:
#   1) `ui/services/review_registry.py::_load_and_validate_canonical`
#      artık dosya-okuma + validator çağrısını TEK bir korumalı blokta
#      yapıyor - HERHANGİ bir beklenmeyen exception (bu ön koşul
#      yükleme hatası dahil) `ReviewLiveViewInvalidError`'a çevriliyor
#      (bkz. o dosyadaki fonksiyon docstring'i).
#   2) BU test dosyası artık GERÇEK validator'ı hiç ÇAĞIRMIYOR: registry
#      `_import_module(entry["validator_module"])` ile modülü HER
#      SEFERİNDE `getattr` ile TAZE okuduğundan (kopya/cache YOK),
#      `evidence_validator.validate_evidence_analysis`'i (modülün
#      KENDİ attribute'u) GEÇİCİ olarak sahte/schema-özgür bir
#      fonksiyonla değiştiriyoruz - `evidence_review.py`'nin YAZMA
#      tarafı (`from evidence_validator import ...` - kendi isim
#      alanına AYRI bir referans) bundan ETKİLENMEZ, ki zaten bu
#      dosyadaki hiçbir senaryo başarılı bir mutasyon GEREKTİRMEZ
#      (yalnız RET yolları test edilir, adaptör hiç çağrılmaz).
# Bu, backend'in İÇ MANTIĞINI (evidence_validator.py, evidence_review.py
# - ikisi de LOCKED) HİÇBİR ŞEKİLDE değiştirmez/yeniden yazmaz - yalnız
# test İZOLASYONUNU, gerçek dosya sistemine dokunmadan sağlar.
#
# KAPSAM NOTU: kullanıcının bağlayıcı talimatındaki test kapsamı
# maddelerinin NEREDEYSE TAMAMI (12 review_kind mapping, QA call
# shape, review_note sınırları, geçersiz target_state, bileşik kimlik
# çakışmaması, backend parent-dependency/R1-R6/stale-source retleri,
# terminal-state ikinci transition reddi, stale-hash sıfır-mutasyon/
# sıfır-audit, domain/beklenmeyen exception ayrımı, fail-closed şema,
# Drafting/QA empty-state, risk_strategy R2 kabul-yolu) ZATEN
# `test_review_service_isolated.py` içinde SAF PYTHON olarak (FastAPI'ye
# ihtiyaç duymadan) tam kapsanıyor. Bu dosya YALNIZ FastAPI/HTTP
# katmanına ÖZGÜ olan maddeleri kapsar: CSRF (5 parça), aynı-origin,
# loopback korumaları ve validator/upstream-load hatasının HTTP
# katmanında fail-closed'a düştüğünün kanıtı - bunlar doğaları gereği
# HTTP request/response döngüsü olmadan test EDİLEMEZ.
#
# Tüm izole testler `evidence.candidate` review_kind'ını kullanır.
# GERÇEK case_0001/backend modüllerine HİÇBİR KALICI ÇAĞRI gitmez -
# yalnız `evidence_review.get_canonical_path` ve (yukarıda açıklanan)
# `evidence_validator.validate_evidence_analysis` GEÇİCİ olarak
# değiştirilir, `finally`'de İKİSİ DE geri alınır. Bu dosyadaki HİÇBİR
# test senaryosu GERÇEK `apply_review_transition`'ın BAŞARIYLA
# tamamlanmasını GEREKTİRMEZ - yalnız RET yollarını (CSRF/origin/
# loopback/stale-hash/validator-exception) sınadığından, adaptör
# fonksiyonu bu testlerin HİÇBİRİNDE gerçekten çağrılmaz (sayaçla
# doğrulanır) - bu yüzden gerçek audit dizini isolasyonuna BİLE gerek
# yoktur. Hiçbir zaman `data/cases/case_iso_route_review/` gerçek
# ağacı OLUŞTURULMAZ - bu, hem yerel bir varlık kontrolüyle hem de
# dosyanın sonundaki genel data/+src/ byte-snapshot ile kanıtlanır.
#
# Çalıştırma:
#   cd vergi_ai_asistani
#   python -m ui.tests.test_review_routes
# ============================================================

import contextlib
import hashlib
import importlib
import json
import logging
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
from ui.services import review_registry as reviewreg
from ui.main import app, _CSRF_SECRET

import evidence_review
import evidence_validator
import argument_review
import risk_strategy_review
import drafting_review
import qa_review

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
def isolated_review_fixture(initial_state="needs_review", validator_exception=None):
    """
    İzole bir case + izole/sentetik `evidence.json` kurar - GERÇEK
    case_0001'e veya `evidence_review.py`/`evidence_validator.py`'nin
    İÇ MANTIĞINA hiçbir şekilde dokunmaz. `evidence_review.get_canonical_path`
    GEÇİCİ olarak bu sentetik dosyaya yönlendirilir (main.py'nin GERÇEK
    çağrı yolunu - `reviewreg.apply_transition` ->
    `module.get_canonical_path(case_id)` - AYNEN kullanır, hiçbir
    override parametresi enjekte EDİLMEZ, çünkü main.py de ASLA
    enjekte etmez).

    TARGETED REMEDIATION (2026-09-05): `evidence_validator.validate_evidence_analysis`
    de GEÇİCİ olarak bir sahte fonksiyonla değiştirilir - `review_registry.
    _load_and_validate_canonical`, `_import_module("evidence_validator")`
    ile modülü HER ÇAĞRIDA TAZE `getattr` eder (kopya/cache TUTMAZ), bu
    yüzden bu değişiklik registry'nin OKUMA tarafına (`list_reviewable`/
    `get_review_record`/`full_case_review_status`) tam olarak yansır.
    Sahte fonksiyon `validator_exception` VERİLMEMİŞSE her zaman
    şema-doğrulamasından GEÇEN bir sonuç döner (`{"valid": True, ...}`)
    - böylece GERÇEK `evidence_validator.py`'nin (LOCKED) kendi ön koşul
    yüklemesi (`load_case(case_id)` -> gerçek `data/cases/{case_id}/
    case.json`'ı okumaya ÇALIŞIR) hiçbir şekilde tetiklenmez; `evidence_
    review.py`'nin (LOCKED) YAZMA tarafı BUNDAN ETKİLENMEZ, çünkü orası
    `from evidence_validator import validate_evidence_analysis` ile
    KENDİ isim alanına AYRI bir referans tutar - bu dosyadaki hiçbir
    senaryo zaten başarılı bir mutasyon GEREKTİRMEZ. `validator_exception`
    VERİLMİŞSE, sahte fonksiyon bunu fırlatır - bu, "validator/upstream-
    load hatası" senaryosunu (ör. gerçek bir `FileNotFoundError`)
    GERÇEK dosya sistemine hiç dokunmadan, tam olarak `registry.
    _load_and_validate_canonical`'ın `except Exception` bloğunun
    yakalayacağı şekilde simüle eder.

    CSRF token'ları main.py ile AYNI 5-parça şemasıyla (case_id +
    review_kind + record_id + target_state + expected_hash) ve AYNI
    fonksiyonla (`security.make_csrf_token`) DOĞRUDAN üretilir - GET
    HTML çıktısından KAZINMAZ (`allowed_targets`teki HER hedef için
    ayrı bir token main.py'nin GERÇEK `review_detail_page`'iyle BİREBİR
    AYNI şekilde üretilir).

    Yield edilen dict: case_id, review_kind, record_id, review_url,
    confirm_url, canonical_path, expected_hash, csrf_token (target_state=
    "confirmed" için), csrf_tokens_by_target (hedef -> token), allowed_targets,
    calls (adaptör çağrı sayacı), validator_calls (sahte validator çağrı sayacı).
    """

    with tempfile.TemporaryDirectory() as tmp:

        tmp_path = Path(tmp)
        fake_case_id = "case_iso_route_review"
        review_kind = "evidence.candidate"
        record_id = "ec_route_1"
        canonical_path = tmp_path / "evidence.json"
        canonical_path.write_text(
            json.dumps({"evidence_candidates": [{"candidate_id": record_id, "review_state": initial_state}]}),
            encoding="utf-8",
        )
        expected_hash = hashlib.sha256(canonical_path.read_bytes()).hexdigest()

        allowed_targets = sorted(evidence_review.CANDIDATE_ALLOWED_TARGETS)
        csrf_tokens_by_target = {
            target: security.make_csrf_token(
                _CSRF_SECRET, fake_case_id, review_kind, record_id, target, expected_hash,
            )
            for target in allowed_targets
        }
        csrf_token = csrf_tokens_by_target["confirmed"]

        calls = {"n": 0}
        original_apply = evidence_review.apply_review_transition

        def _counting_apply(*args, **kwargs):
            calls["n"] += 1
            return original_apply(*args, **kwargs)

        validator_calls = {"n": 0}
        original_validate = evidence_validator.validate_evidence_analysis

        def _fake_validate(*args, **kwargs):
            validator_calls["n"] += 1
            if validator_exception is not None:
                raise validator_exception
            return {"valid": True, "errors": [], "warnings": []}

        original_get_canonical_path = evidence_review.get_canonical_path
        original_list_case_ids = svc_paths.list_case_ids
        original_resolve = svc_paths.resolve_case_id

        evidence_review.get_canonical_path = lambda cid: canonical_path
        evidence_review.apply_review_transition = _counting_apply
        evidence_validator.validate_evidence_analysis = _fake_validate
        svc_paths.list_case_ids = lambda: original_list_case_ids() + [fake_case_id]
        svc_paths.resolve_case_id = lambda cid: cid if cid == fake_case_id else original_resolve(cid)

        try:

            yield {
                "case_id": fake_case_id, "review_kind": review_kind,
                "record_id": record_id,
                "review_url": f"/cases/{fake_case_id}/reviews/{review_kind}/{record_id}",
                "confirm_url": f"/cases/{fake_case_id}/reviews/{review_kind}/{record_id}/confirm",
                "canonical_path": canonical_path, "calls": calls,
                "validator_calls": validator_calls,
                "expected_hash": expected_hash, "csrf_token": csrf_token,
                "csrf_tokens_by_target": csrf_tokens_by_target,
                "allowed_targets": allowed_targets,
            }

        finally:

            evidence_review.get_canonical_path = original_get_canonical_path
            evidence_review.apply_review_transition = original_apply
            evidence_validator.validate_evidence_analysis = original_validate
            svc_paths.list_case_ids = original_list_case_ids
            svc_paths.resolve_case_id = original_resolve


@contextlib.contextmanager
def isolated_domain_error_fixture(review_kind, injected_error, review_note="test notu"):
    """
    FINAL DOMAIN-ERROR REDACTION REMEDIATION (2026-09-05) test yardımcısı.

    `reviewreg.apply_transition` (Row 18b registry, LOCKED DEĞİL) şu
    sırayla çalışır: (1) `module.get_canonical_path(case_id)` ile
    canonical yolu bulur, (2) dosyanın VAR OLUP olmadığını kontrol
    eder, (3) `expected_hash` tazeliğini kontrol eder, (4) yalnız bu
    ikisi GEÇERSE `module.apply_review_transition(...)` (GERÇEK LOCKED
    backend) ÇAĞIRIR. Bu yardımcı yalnız SON adımı (backend çağrısı)
    `injected_error`'ı fırlatan sahte bir fonksiyonla GEÇİCİ olarak
    değiştirir - ilk üç adım GERÇEK sentetik bir dosya ve GERÇEK
    `sha256_file` ile olduğu gibi ÇALIŞIR. Böylece `main.py`'nin
    `review_confirm` route'u GERÇEKTEN `except _REVIEW_DOMAIN_ERRORS`
    bloğuna ulaşır (main.py'nin redaksiyon düzeltmesi TAM OLARAK burada
    sınanır) - hiçbir GERÇEK backend İÇ MANTIĞI (parent-dependency/
    R1-R6/stale-source/previous_state, dosya yazma/backup/rollback)
    ÇAĞRILMAZ/DEĞİŞTİRİLMEZ.

    `target_state`, ilgili ailenin KENDİ GERÇEK `get_allowed_targets()`
    sonucundan (canlı okunur, kopya YOK) seçilir - rastgele/geçersiz
    bir değer DEĞİLDİR, bu yüzden `reviewreg.apply_transition`'ın
    "geçersiz hedef durum" kontrolünü de GERÇEKTEN GEÇER.

    Yield edilen dict: case_id, review_kind, record_id, confirm_url,
    canonical_path, calls (sahte backend çağrı sayacı), expected_hash,
    csrf_token, target_state, review_note.
    """

    entry = reviewreg.REVIEW_KIND_REGISTRY[review_kind]
    module = importlib.import_module(entry["module"])

    with tempfile.TemporaryDirectory() as tmp:

        tmp_path = Path(tmp)
        fake_case_id = f"case_iso_domain_{review_kind.replace('.', '_')}"
        record_id = "dom_err_record_1"
        canonical_path = tmp_path / "canonical.json"
        canonical_path.write_text(json.dumps({"placeholder": True}), encoding="utf-8")
        expected_hash = hashlib.sha256(canonical_path.read_bytes()).hexdigest()

        target_state = sorted(reviewreg.get_allowed_targets(review_kind))[0]

        csrf_token = security.make_csrf_token(
            _CSRF_SECRET, fake_case_id, review_kind, record_id, target_state, expected_hash,
        )

        calls = {"n": 0}

        def _raising_apply(*args, **kwargs):
            calls["n"] += 1
            raise injected_error

        original_get_canonical_path = module.get_canonical_path
        original_apply = module.apply_review_transition
        original_list_case_ids = svc_paths.list_case_ids
        original_resolve = svc_paths.resolve_case_id

        module.get_canonical_path = lambda cid: canonical_path
        module.apply_review_transition = _raising_apply
        svc_paths.list_case_ids = lambda: original_list_case_ids() + [fake_case_id]
        svc_paths.resolve_case_id = lambda cid: cid if cid == fake_case_id else original_resolve(cid)

        try:

            yield {
                "case_id": fake_case_id, "review_kind": review_kind,
                "record_id": record_id,
                "confirm_url": f"/cases/{fake_case_id}/reviews/{review_kind}/{record_id}/confirm",
                "canonical_path": canonical_path, "calls": calls,
                "expected_hash": expected_hash, "csrf_token": csrf_token,
                "target_state": target_state, "review_note": review_note,
            }

        finally:

            module.get_canonical_path = original_get_canonical_path
            module.apply_review_transition = original_apply
            svc_paths.list_case_ids = original_list_case_ids
            svc_paths.resolve_case_id = original_resolve


@contextlib.contextmanager
def _capture_ui_logger():
    """
    FINAL DOMAIN-ERROR REDACTION REMEDIATION (2026-09-05) test
    yardımcısı - "detaylı ayrıntı yalnız yerel logging'de TAM olarak
    KALMALI" (madde 8) gereksinimini KANITLAMAK için `main.py`'nin
    KULLANDIĞI GERÇEK `logger = logging.getLogger("vergi_ui")`
    nesnesine geçici bir `logging.Handler` ekler ve yayılan TÜM
    `LogRecord`'ları (formatlanmış mesajlarıyla) bir listede toplar.
    main.py/logger yapılandırması DEĞİŞTİRİLMEZ - yalnız EK bir
    handler geçici olarak eklenir, `finally`'de KALDIRILIR.
    """

    ui_logger = logging.getLogger("vergi_ui")
    records = []

    class _ListHandler(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = _ListHandler()
    previous_level = ui_logger.level
    ui_logger.addHandler(handler)
    ui_logger.setLevel(logging.DEBUG)

    try:

        yield records

    finally:

        ui_logger.removeHandler(handler)
        ui_logger.setLevel(previous_level)


case_ids = svc_paths.list_case_ids()
check("en az bir case bulundu", len(case_ids) > 0, f"case_ids={case_ids}")

if not case_ids:
    print("Hiç case yok - test devam edemiyor.")
    sys.exit(1)

case_id = case_ids[0]

# --- T00: loopback-only middleware review route'larında da çalışıyor mu? ---
_loopback_test_client = TestClient(app, client=("203.0.113.7", 55555))
r = _loopback_test_client.get(f"/cases/{case_id}/reviews")
check("T00 loopback olmayan istemci -> 403 (reviews listesi)", r.status_code == 403, f"status={r.status_code}")

# --- T01: GERÇEK case için İncelemeler listesi -> 200 ---
r = client.get(f"/cases/{case_id}/reviews")
check("T01 GET /cases/{case_id}/reviews -> 200", r.status_code == 200, f"status={r.status_code}")
check("T01b reviews listesi 12 review_kind'ın etiketlerini içeriyor (ör. Row numarası)", "İncelemeler" in r.text)

# --- T02: bilinmeyen review_kind -> 404 ---
r = client.get(f"/cases/{case_id}/reviews/__olmayan_kind__/x")
check("T02 GET bilinmeyen review_kind -> 404", r.status_code == 404, f"status={r.status_code}")
r = client.post(f"/cases/{case_id}/reviews/__olmayan_kind__/x/confirm", data={
    "target_state": "confirmed", "review_note": "not", "expected_hash": "0" * 64, "csrf_token": "x",
})
check("T02b POST confirm bilinmeyen review_kind -> 404", r.status_code == 404, f"status={r.status_code}")

# --- T03: var olmayan record_id -> genel hata sayfası (REVIEW_RECORD_NOT_FOUND),
# 500 DEĞİL, ve İZOLE sahte validator'a ULAŞIR - GERÇEK
# evidence_validator/case.json'a HİÇ ULAŞMAZ (kök neden düzeltmesi). ---
with isolated_review_fixture() as fx:
    r = client.get(f"/cases/{fx['case_id']}/reviews/evidence.candidate/__olmayan_kayit__")
    check("T03 GET var olmayan record_id -> 200 (genel hata sayfası, 500 DEĞİL)", r.status_code == 200, f"status={r.status_code}")
    check("T03b ham exception/traceback metni SIZMIYOR", "Traceback" not in r.text and "raise " not in r.text)
    check(
        "T03c GET izole/sahte validator'a ULAŞTI (registry OKUMA yolu çalıştı), GERÇEK case.json'a HİÇ İHTİYAÇ DUYMADI",
        fx["validator_calls"]["n"] >= 1,
    )
    check(
        "T03d GERÇEK data/cases/case_iso_route_review/ ağacı HİÇ OLUŞTURULMADI",
        not (svc_paths.CASES_DIR / fx["case_id"]).exists(),
    )

# --- T04: izole review sayfası GET - artık sahte validator SAYESİNDE
# GERÇEKTEN BAŞARIYLA render edilir (200, gerçek kayıt içeriğiyle) -
# önceki turdaki "fail-closed'a düşebilir" belirsizliği, kök neden
# düzeltmesiyle birlikte ORTADAN KALKTI: GET artık GERÇEK
# evidence_validator/case.json'a HİÇ ULAŞMADAN, tam anlamıyla izole
# çalışır. CSRF/origin/loopback testleri (T05-T10) `expected_hash`/
# `csrf_token`'ı main.py ile AYNI fonksiyonlarla DOĞRUDAN üretir (bkz.
# `isolated_review_fixture` docstring'i). ---
with isolated_review_fixture() as fx:

    r = client.get(fx["review_url"])
    check(
        "T04 GET izole review sayfası -> 200 (GERÇEKTEN başarıyla render edilir, sahte validator sayesinde)",
        r.status_code == 200,
        f"status={r.status_code}",
    )
    check("T04b ham exception/traceback metni SIZMIYOR", "Traceback" not in r.text and "raise " not in r.text)
    check("T04c render edilen sayfa kaydın kimliğini içeriyor", fx["record_id"] in r.text)
    check(
        "T04d review_detail.html: her allowed_target için AYRI bir CSRF token gömülü (5-parça şema)",
        all(token in r.text for token in fx["csrf_tokens_by_target"].values()),
    )
    check(
        "T04e GERÇEK data/cases/case_iso_route_review/ ağacı HİÇ OLUŞTURULMADI",
        not (svc_paths.CASES_DIR / fx["case_id"]).exists(),
    )

    real_hash = fx["expected_hash"]
    real_csrf = fx["csrf_token"]

    # --- T05: confirm endpoint'ine GET -> 405, adaptör HİÇ çağrılmadı ---
    r = client.get(fx["confirm_url"])
    check("T05 GET confirm endpoint -> 405, adaptör HİÇ çağrılmadı", r.status_code == 405 and fx["calls"]["n"] == 0, f"status={r.status_code}")

    # --- T06: cross-origin POST, GEÇERLİ csrf/hash OLSA BİLE adaptörden ÖNCE reddedilmeli ---
    r2 = client.post(
        fx["confirm_url"],
        data={"target_state": "confirmed", "review_note": "test notu", "expected_hash": real_hash, "csrf_token": real_csrf},
        headers={"Origin": "http://evil.example"},
    )
    check(
        "T06 cross-origin Origin header (geçerli csrf/hash) -> reddedildi, adaptör HİÇ çağrılmadı",
        fx["calls"]["n"] == 0,
        f"status={r2.status_code}",
    )

    # --- T07: eksik csrf_token -> FastAPI form validasyonu (422), adaptör HİÇ çağrılmadı ---
    r3 = client.post(fx["confirm_url"], data={
        "target_state": "confirmed", "review_note": "test notu", "expected_hash": real_hash,
    })
    check(
        "T07 eksik csrf_token -> 422, adaptör HİÇ çağrılmadı",
        r3.status_code == 422 and fx["calls"]["n"] == 0,
        f"status={r3.status_code}",
    )

    # --- T08: kurcalanmış csrf_token -> reddedilmeli, adaptör HİÇ çağrılmadı ---
    tampered = (real_csrf[:-1] + ("0" if real_csrf[-1] != "0" else "1")) if real_csrf else "x"
    r4 = client.post(fx["confirm_url"], data={
        "target_state": "confirmed", "review_note": "test notu", "expected_hash": real_hash, "csrf_token": tampered,
    })
    check(
        "T08 kurcalanmış csrf_token -> reddedildi, adaptör HİÇ çağrılmadı",
        fx["calls"]["n"] == 0,
        f"status={r4.status_code}",
    )

    # --- T09: loopback olmayan istemciden POST -> middleware'de reddedilmeli, adaptör HİÇ çağrılmadı ---
    _non_loopback_client = TestClient(app, client=("203.0.113.7", 4444))
    r5 = _non_loopback_client.post(fx["confirm_url"], data={
        "target_state": "confirmed", "review_note": "test notu", "expected_hash": real_hash, "csrf_token": real_csrf,
    })
    check(
        "T09 loopback olmayan POST -> 403, adaptör HİÇ çağrılmadı",
        r5.status_code == 403 and fx["calls"]["n"] == 0,
        f"status={r5.status_code}",
    )

    # --- T10: GERÇEK stale-hash senaryosu HTTP katmanında - CSRF token
    # (case_id+review_kind+record_id+hash'e bağlı) DOĞRU/DEĞİŞMEMİŞ
    # gönderilir (aynı-origin/CSRF katmanı GEÇER), ama dosya ekran
    # açıldıktan SONRA değişmiştir - `reviewreg.apply_transition`
    # kendi hash karşılaştırmasında bunu yakalamalı, adaptör HİÇ
    # çağrılmamalı, sıfır mutasyon/audit olmalı. ---
    fx["canonical_path"].write_text(
        json.dumps({"evidence_candidates": [{"candidate_id": "ec_route_1", "review_state": "needs_review", "degisti": True}]}),
        encoding="utf-8",
    )
    r6 = client.post(fx["confirm_url"], data={
        "target_state": "confirmed", "review_note": "test notu", "expected_hash": real_hash, "csrf_token": real_csrf,
    })
    check("T10 GERÇEK stale-hash -> 200 (genel hata sayfası)", r6.status_code == 200, f"status={r6.status_code}")
    check(
        "T10b GERÇEK stale-hash -> adaptör HİÇ çağrılmadı (sıfır mutasyon)",
        fx["calls"]["n"] == 0,
    )
    check(
        "T10c GERÇEK stale-hash sonrası izole canonical dosya İÇERİĞİ (yalnız bizim yaptığımız değişiklik dışında) DEĞİŞMEDİ",
        json.loads(fx["canonical_path"].read_text(encoding="utf-8"))["evidence_candidates"][0]["degisti"] is True,
    )
    check("T10d ham exception/traceback metni SIZMIYOR", "Traceback" not in r6.text and "raise " not in r6.text)

    # --- T11: target_state CSRF BAĞLAMASI (targeted remediation,
    # 2026-09-05'te eklenen 5. parça) - GEÇERLİ csrf/hash gönderilir
    # AMA token "confirmed" için üretilmişken form'da target_state=
    # "rejected" gönderilir (ikisi de KENDİ BAŞINA geçerli bir hedef
    # durumdur - bu, rastgele/geçersiz bir değer değil, GERÇEKTEN
    # farklı bir SEÇİM'in de reddedildiğini kanıtlar). Doğrulama
    # adaptöre ULAŞMADAN BAŞARISIZ olmalı. ---
    r7 = client.post(fx["confirm_url"], data={
        "target_state": "rejected", "review_note": "test notu", "expected_hash": real_hash, "csrf_token": real_csrf,
    })
    check(
        "T11 target_state CSRF token'ından FARKLI gönderilirse (confirmed token + rejected form) reddedilir, adaptör HİÇ çağrılmadı",
        fx["calls"]["n"] == 0,
        f"status={r7.status_code}",
    )
    check("T11b ham exception/traceback metni SIZMIYOR", "Traceback" not in r7.text and "raise " not in r7.text)

# --- T12: FAIL-CLOSED VALIDATOR/UPSTREAM-LOAD HATASI - sahte validator
# GERÇEK bir `FileNotFoundError`'ı (case.json'a atıfla, ama HİÇBİR
# GERÇEK dosyaya dokunmadan) fırlatır. Tarayıcı SABİT genel hata
# sayfasını (200) almalı; ham exception metni/mutlak path SIZMAMALI;
# hiçbir review transition/canonical yazma/backup/audit OLUŞMAMALI. ---
_injected_error = FileNotFoundError(
    "[Errno 2] No such file or directory: "
    "'/mnt/user-data/uploads/vergi_ai_asistani/data/cases/case_iso_route_review/case.json'"
)
with isolated_review_fixture(validator_exception=_injected_error) as fx:

    _canonical_before = fx["canonical_path"].read_text(encoding="utf-8")

    r8 = client.get(fx["review_url"])
    check(
        "T12 GET izole review sayfası + validator FileNotFoundError -> 200 (SABİT genel hata sayfası, 500 DEĞİL)",
        r8.status_code == 200,
        f"status={r8.status_code}",
    )
    check(
        "T12b sayfa REVIEW_FAMILY_INVALID'in SABİT genel mesajını içeriyor",
        "canonical verisi şu anda doğrulanamıyor" in r8.text,
    )
    check(
        "T12c ham exception metni ('FileNotFoundError'/'Errno 2') SIZMIYOR",
        "FileNotFoundError" not in r8.text and "Errno 2" not in r8.text,
    )
    check(
        "T12d mutlak dosya yolu (case.json'a giden path) SIZMIYOR",
        "case_iso_route_review/case.json" not in r8.text and "/mnt/user-data" not in r8.text,
    )
    check("T12e ham traceback SIZMIYOR", "Traceback" not in r8.text and "raise " not in r8.text)
    check(
        "T12f sahte validator GERÇEKTEN çağrıldı (izole yol çalıştı) VE istisna fırlattı",
        fx["validator_calls"]["n"] >= 1,
    )
    check(
        "T12g validator hatası sonrası GERÇEK apply_review_transition adaptörü HİÇ ÇAĞRILMADI (sıfır transition)",
        fx["calls"]["n"] == 0,
    )
    check(
        "T12h validator hatası sonrası izole canonical dosya İÇERİĞİ DEĞİŞMEDİ (sıfır yazma)",
        fx["canonical_path"].read_text(encoding="utf-8") == _canonical_before,
    )
    check(
        "T12i validator hatası sonrası hiçbir audit dizini OLUŞMADI (sıfır audit)",
        not (fx["canonical_path"].parent / "reviews").exists(),
    )
    check(
        "T12j GERÇEK data/cases/case_iso_route_review/ ağacı HİÇ OLUŞTURULMADI",
        not (svc_paths.CASES_DIR / fx["case_id"]).exists(),
    )

    # Aynı fail-closed davranış /reviews listesinde de (full_case_review_status
    # yolunda) doğrulanır - farklı bir route, AYNI kök-neden sınıfı.
    r9 = client.get(f"/cases/{fx['case_id']}/reviews")
    check(
        "T12k GET /cases/{case_id}/reviews + validator FileNotFoundError -> 200 (fail-closed, 500 DEĞİL)",
        r9.status_code == 200,
        f"status={r9.status_code}",
    )
    check(
        "T12l ham exception metni /reviews listesinde de SIZMIYOR",
        "FileNotFoundError" not in r9.text and "Errno 2" not in r9.text and "Traceback" not in r9.text,
    )

# --- T13: CSRF BEŞ-PARÇA BAĞLAMA MATRİSİ - main.py'nin GERÇEK
# `security.verify_csrf_token` fonksiyonu DOĞRUDAN kullanılır (HİÇBİR
# HMAC mantığı burada yeniden yazılmaz). Doğru 5-parçalık demet için
# üretilen bir token, BEŞ parçadan HERHANGİ BİRİ tek başına
# değiştirildiğinde doğrulamadan GEÇMEMELİ; parçaların HİÇBİRİ
# değişmediğinde ise GEÇMELİ (pozitif kontrol). ---
_m_case_id = "case_iso_route_review"
_m_review_kind = "evidence.candidate"
_m_record_id = "ec_route_1"
_m_target_state = "confirmed"
_m_expected_hash = "a" * 64
_m_parts = (_m_case_id, _m_review_kind, _m_record_id, _m_target_state, _m_expected_hash)
_m_token = security.make_csrf_token(_CSRF_SECRET, *_m_parts)

check(
    "T13 (pozitif kontrol) 5 parçanın TAMAMI değişmeden verify_csrf_token BAŞARILI",
    security.verify_csrf_token(_CSRF_SECRET, _m_token, *_m_parts) is True,
)

_m_part_names = ("case_id", "review_kind", "record_id", "target_state", "expected_hash")
for _m_index, _m_name in enumerate(_m_part_names):
    _m_tampered_parts = list(_m_parts)
    _m_tampered_parts[_m_index] = _m_tampered_parts[_m_index] + "_TAMPERED"
    check(
        f"T13 CSRF 5-parça matrisi: yalnız '{_m_name}' değiştirilince verify_csrf_token BAŞARISIZ olur",
        security.verify_csrf_token(_CSRF_SECRET, _m_token, *_m_tampered_parts) is False,
    )

# --- T15: FINAL DOMAIN-ERROR REDACTION REMEDIATION (2026-09-05) -
# main.py ARTIK 5 GERÇEK domain hata sınıfının (`_REVIEW_DOMAIN_ERRORS`)
# `str(error)` içeriğini TARAYICIYA HİÇ GEÇİRMİYOR (kök neden: LOCK-
# READINESS incelemesinde kanıtlandığı gibi, 5 backend'in TAMAMI aynı
# domain sınıflarıyla "Canonical X.json bulunamadı:\n{mutlak_path}"
# biçiminde MUTLAK PATH içeren bir mesaj fırlatabiliyordu). Her aileden
# (evidence/argument/risk_strategy/drafting/qa - TÜM 5 GERÇEK domain
# sınıfı) birer review_kind için, GERÇEK backend `apply_review_transition`
# GEÇİCİ olarak; Windows mutlak path + POSIX mutlak path + traceback-
# benzeri metin + HTML/script payload + gönderilen review_note
# içeriğinin TAMAMINI içeren bir mesajla o ailenin GERÇEK domain
# sınıfını fırlatacak şekilde değiştirilir (`isolated_domain_error_
# fixture` - GERÇEK dosya sistemine/backend İÇ MANTIĞINA dokunmadan).
# `reviewreg.apply_transition`'ın KENDİ dosya-varlığı/hash-tazelik
# kontrolleri GERÇEK sentetik dosya ile GEÇER, böylece main.py'nin
# `except _REVIEW_DOMAIN_ERRORS` bloğuna GERÇEKTEN ulaşılır - main.py'nin
# redaksiyon düzeltmesi TAM OLARAK burada, uçtan uca (HTTP response
# body üzerinden) sınanır. ---
DOMAIN_ERROR_CASES = [
    ("evidence.candidate", evidence_review.EvidenceReviewError),
    ("argument.claim", argument_review.ArgumentReviewError),
    ("risk_strategy.risk", risk_strategy_review.RiskStrategyReviewError),
    ("drafting.section", drafting_review.DraftingReviewError),
    ("qa.suggestion", qa_review.QaReviewError),
]

for _dom_kind, _dom_exc_cls in DOMAIN_ERROR_CASES:

    _dom_note_marker = f"GIZLI_AVUKAT_NOTU_MARKER_{_dom_kind.replace('.', '_')}"
    _dom_windows_path = r"C:\Users\Burki\vergi_ai_asistani\data\cases\case_0001\evidence\evidence.json"
    _dom_posix_path = "/mnt/user-data/uploads/vergi_ai_asistani/data/cases/case_0001/evidence/evidence.json"
    _dom_injected_message = (
        "Canonical dosya bulunamadı:\n"
        f"{_dom_windows_path}\n"
        f"{_dom_posix_path}\n"
        "Traceback (most recent call last):\n"
        "  File \"src/evidence_review.py\", line 566, in apply_review_transition\n"
        "FileNotFoundError: [Errno 2] No such file or directory\n"
        "<script>alert('xss')</script>\n"
        f"review_note: {_dom_note_marker}"
    )
    _dom_injected_error = _dom_exc_cls(_dom_injected_message)

    with isolated_domain_error_fixture(_dom_kind, _dom_injected_error, review_note=_dom_note_marker) as fx:

        _canonical_before = fx["canonical_path"].read_bytes()
        _sibling_before = sorted(p.name for p in fx["canonical_path"].parent.iterdir())

        with _capture_ui_logger() as _log_records:

            r = client.post(fx["confirm_url"], data={
                "target_state": fx["target_state"],
                "review_note": fx["review_note"],
                "expected_hash": fx["expected_hash"],
                "csrf_token": fx["csrf_token"],
            })

        _log_text = "\n".join(_log_records)

        check(
            f"T15 [{_dom_kind}] domain hata sonrası 200 (SABİT genel reddi sayfası, 500 DEĞİL)",
            r.status_code == 200,
            f"status={r.status_code}",
        )
        check(
            f"T15 [{_dom_kind}] GERÇEK backend apply_review_transition GERÇEKTEN çağrıldı (domain sınıfı GERÇEKTEN fırlatıldı, adaptör atlanmadı)",
            fx["calls"]["n"] == 1,
        )
        check(
            f"T15 [{_dom_kind}] sabit REVIEW_DOMAIN_REJECTED mesajı GÖRÜNÜYOR",
            "ilgili modülün kendi iş kuralı gereği reddedildi" in r.text,
        )
        check(
            f"T15 [{_dom_kind}] hata kodu REVIEW_DOMAIN_REJECTED GÖRÜNÜYOR",
            "REVIEW_DOMAIN_REJECTED" in r.text,
        )
        check(
            f"T15 [{_dom_kind}] Windows mutlak path SIZMIYOR",
            _dom_windows_path not in r.text and "Burki" not in r.text,
        )
        check(
            f"T15 [{_dom_kind}] POSIX mutlak path SIZMIYOR",
            _dom_posix_path not in r.text and "/mnt/user-data" not in r.text,
        )
        check(
            f"T15 [{_dom_kind}] traceback/FileNotFoundError-benzeri metin SIZMIYOR",
            "Traceback" not in r.text and "FileNotFoundError" not in r.text and "Errno 2" not in r.text,
        )
        check(
            f"T15 [{_dom_kind}] HTML/script payload SIZMIYOR (ham veya escape edilmiş biçimde DEĞİL)",
            "<script>" not in r.text and "&lt;script&gt;" not in r.text and "alert(" not in r.text,
        )
        check(
            f"T15 [{_dom_kind}] gönderilen review_note içeriği SIZMIYOR",
            _dom_note_marker not in r.text,
        )
        check(
            f"T15 [{_dom_kind}] işlem BAŞARILI olarak gösterilmiyor (review_result.html göstergeleri YOK)",
            "başarıyla geçirildi" not in r.text and "Yeni canonical hash" not in r.text,
        )
        check(
            f"T15 [{_dom_kind}] sentetik canonical dosya İÇERİĞİ DEĞİŞMEDİ (sıfır canonical yazma)",
            fx["canonical_path"].read_bytes() == _canonical_before,
        )
        check(
            f"T15 [{_dom_kind}] sentetik canonical'ın yanında hiçbir audit dizini/dosyası OLUŞMADI (sıfır audit)",
            sorted(p.name for p in fx["canonical_path"].parent.iterdir()) == _sibling_before,
        )
        check(
            f"T15 [{_dom_kind}] yerel logger TAM ayrıntıyı (exception TÜRÜ) YAKALADI (madde 8: tanı için tam ayrıntı yerelde SAKLI)",
            _dom_exc_cls.__name__ in _log_text,
        )
        check(
            f"T15 [{_dom_kind}] yerel logger TAM ayrıntıyı (ham mesaj/mutlak path/review_note dahil) YAKALADI",
            _dom_windows_path in _log_text and _dom_note_marker in _log_text,
        )

# --- T14: GERÇEK data/ ve src/ ağaçları bu dosyanın HİÇBİR testiyle DEĞİŞMEDİ (byte-düzeyinde) ---
_after_real_tree = _snapshot_real_tree()
check(
    "T14 GERÇEK data/ ve src/ ağaçları test_review_routes.py ile DEĞİŞMEDİ (byte-düzeyinde)",
    _before_real_tree == _after_real_tree,
    f"fark={set(_before_real_tree) ^ set(_after_real_tree)}",
)

print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
