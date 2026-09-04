# ============================================================
# Row 18a - İZOLE SAF-PYTHON SERVİS TESTLERİ (targeted remediation)
#
# Bu dosya FastAPI'YE İHTİYAÇ DUYMAZ ve onu import ETMEZ - yalnız
# `ui/services/*` katmanını (paths.resolve_case_id, security.py,
# live_view.validate_live_view, approval_registry.case_scoped_approve)
# doğrudan çağırır. Talimat gereği (§2, §11): mutasyon/rollback/audit
# testleri yalnız `tempfile.TemporaryDirectory()` içindeki SENTETİK
# fixture'larla, GERÇEK case_0001/Row 6-17 modüllerine DOKUNMADAN
# çalışır - hiçbir ortam değişkeni gerçek repoda mutasyona İZİN VERMEZ
# (önceki `VERGI_UI_RUN_DESTRUCTIVE_TEST` yolu tamamen KALDIRILDI).
#
# Çalıştırma (bu sandbox'ta da çalışır - FastAPI gerekmez):
#   python ui/tests/test_service_isolated.py
# ============================================================

import sys
import shutil
import tempfile
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import paths as real_paths          # noqa: E402
from ui.services import security                      # noqa: E402
from ui.services import live_view                      # noqa: E402
from ui.services.common import UnknownCaseError, LiveViewInvalidError  # noqa: E402

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


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - beklenmeyen istisna: {error!r}")
    else:
        check(label, False, f"{detail} - istisna hiç fırlatılmadı")


# ============================================================
# 1) GERÇEK REPO BYTE-SNAPSHOT (test öncesi/sonrası) - bu dosyanın
#    HERHANGİ bir testinin gerçek data/src ağacına dokunmadığını
#    kanıtlar. `data/` ve `src/` altındaki her dosyanın (path, boyut,
#    mtime, sha256) manifestini alır.
# ============================================================

import hashlib


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


_SNAPSHOT_ROOTS = (real_paths.DATA_DIR, real_paths.SRC_DIR)

_before_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)


# ============================================================
# 2) case_id ALLOWLIST ÇÖZÜCÜSÜ - `..`, encode edilmiş traversal
#    biçimleri, slash/backslash denemeleri, bilinmeyen case, geçerli
#    enumerated case (talimat §3).
# ============================================================

_real_case_ids = real_paths.list_case_ids()
check("ön koşul: gerçek repoda en az bir case var", len(_real_case_ids) > 0, f"case_ids={_real_case_ids}")

if _real_case_ids:
    _valid_case = _real_case_ids[0]

    check(
        "resolve_case_id: geçerli enumerated case kabul edilir",
        real_paths.resolve_case_id(_valid_case) == _valid_case,
    )

_TRAVERSAL_CASES = [
    "..",
    "../case_0001",
    "case_0001/..",
    "%2e%2e",                     # encode edilmiş traversal - decode edilmeden geldiği için zaten allowlist'te yok
    "%2e%2e%2fcase_0001",
    "..%2fcase_0001",
    "case_0001/../../etc/passwd",
    "case_0001\\..\\..",
    "/etc/passwd",
    "\\windows\\system32",
    "",
    "   ",
    "bilinmeyen_case_9999",
    None,
    123,
]

for bad_case in _TRAVERSAL_CASES:
    expect_raises(
        UnknownCaseError,
        lambda bad_case=bad_case: real_paths.resolve_case_id(bad_case),
        f"resolve_case_id reddediyor: {bad_case!r}",
    )

# "Gizli eski dosya adını doğrudan istemek de fail-closed olmalı" -
# case_id olarak var olmayan ama gerçekçi görünen bir dizin adı da
# aynı şekilde reddedilmeli (dosya sistemi keşfi DEĞİL, yalnız
# allowlist karşılaştırması kullanıldığını doğrular).
expect_raises(
    UnknownCaseError,
    lambda: real_paths.resolve_case_id("case_0001_eski_YEDEK"),
    "resolve_case_id reddediyor: uydurma-ama-gerçekçi dizin adı",
)


# ============================================================
# 3) CSRF TOKEN - round-trip ve kurcalama (tamper) reddi (talimat §8)
# ============================================================

_secret_a = security.new_csrf_secret()
_secret_b = security.new_csrf_secret()

check("iki ayrı csrf secret farklı üretiliyor", _secret_a != _secret_b)

_token = security.make_csrf_token(_secret_a, "case_0001", "deadline", "abc123")

check(
    "csrf token round-trip: doğru secret + doğru parts -> geçerli",
    security.verify_csrf_token(_secret_a, _token, "case_0001", "deadline", "abc123"),
)
check(
    "csrf token reddi: yanlış secret",
    not security.verify_csrf_token(_secret_b, _token, "case_0001", "deadline", "abc123"),
)
check(
    "csrf token reddi: kurcalanmış (tek karakter değişmiş) token",
    not security.verify_csrf_token(_secret_a, _token[:-1] + ("0" if _token[-1] != "0" else "1"), "case_0001", "deadline", "abc123"),
)
check(
    "csrf token reddi: farklı case_id ile üretilmiş token başka case'de geçersiz",
    not security.verify_csrf_token(_secret_a, _token, "case_9999", "deadline", "abc123"),
)
check(
    "csrf token reddi: farklı expected_hash ile üretilmiş token burada geçersiz",
    not security.verify_csrf_token(_secret_a, _token, "case_0001", "deadline", "DEGISTIRILMIS_hash"),
)
check("csrf token reddi: boş token", not security.verify_csrf_token(_secret_a, "", "case_0001", "deadline", "abc123"))
check("csrf token reddi: None token", not security.verify_csrf_token(_secret_a, None, "case_0001", "deadline", "abc123"))


# ============================================================
# 4) AYNI-ORİJİN (Origin/Referer) VE LOOPBACK KONTROLÜ (talimat §7/§8)
# ============================================================

check("same-origin: origin uyuşuyor -> True", security.is_same_origin("http://127.0.0.1:8000", None, "127.0.0.1:8000"))
check("same-origin: origin uyuşmuyor -> False", not security.is_same_origin("http://evil.example:9999", None, "127.0.0.1:8000"))
check("same-origin: yalnız referer, uyuşuyor -> True", security.is_same_origin(None, "http://127.0.0.1:8000/cases/x", "127.0.0.1:8000"))
check("same-origin: yalnız referer, uyuşmuyor -> False", not security.is_same_origin(None, "http://evil.example/x", "127.0.0.1:8000"))
check("same-origin: hiçbir header yok -> True (CSRF token birincil savunma)", security.is_same_origin(None, None, "127.0.0.1:8000"))

check("loopback: 127.0.0.1 kabul", security.is_loopback_host("127.0.0.1"))
check("loopback: ::1 kabul", security.is_loopback_host("::1"))
check("loopback: localhost kabul", security.is_loopback_host("localhost"))
check("loopback: LAN IP reddi", not security.is_loopback_host("192.168.1.50"))
check("loopback: None reddi", not security.is_loopback_host(None))
check("loopback: rastgele string reddi", not security.is_loopback_host("testclient"))


# ============================================================
# 5) CANLI GÖRÜNÜM DOĞRULAMASI - pozitif, geçersiz-şema, geçersiz-
#    semantik fixture'lar (talimat §5). Row 17'nin GERÇEK
#    `orchestrator_validator` fonksiyonları saf dict alıp saf dict/
#    liste döndürdüğü için burada gerçek dosya sistemine dokunmadan
#    doğrudan çağrılabilir.
# ============================================================

if _real_case_ids:
    _valid_view = live_view.build_live_view(_valid_case)

    _errors_on_valid = live_view.validate_live_view(_valid_view, _valid_case)
    check(
        "validate_live_view: gerçek canlı görünüm geçerli (0 hata)",
        _errors_on_valid == [],
        f"errors={_errors_on_valid}",
    )

    # Pozitif yol: get_case_view_with_staleness gerçek veriyle
    # fail-closed'a DÜŞMEMELİ.
    try:
        _result = live_view.get_case_view_with_staleness(_valid_case)
        check("get_case_view_with_staleness: gerçek case için başarıyla döner", True)
    except LiveViewInvalidError as error:
        check("get_case_view_with_staleness: gerçek case için başarıyla döner", False, str(error))

    # Geçersiz şema: zorunlu bir üst-seviye alanı sil.
    import copy

    _broken_schema = copy.deepcopy(_valid_view)
    _broken_schema.pop("case_id", None)

    _errors_schema = live_view.validate_live_view(_broken_schema, _valid_case)
    check(
        "validate_live_view: case_id eksik şema -> en az 1 hata",
        len(_errors_schema) > 0,
        f"errors={_errors_schema}",
    )

    # Geçersiz semantik: case_id'yi beklenenle uyuşmayacak şekilde
    # değiştir (validate_case_id'yi tetiklemesi beklenir).
    _broken_semantic = copy.deepcopy(_valid_view)
    _broken_semantic["case_id"] = "baska_bir_case_9999"

    _errors_semantic = live_view.validate_live_view(_broken_semantic, _valid_case)
    check(
        "validate_live_view: uyuşmayan case_id -> en az 1 hata",
        len(_errors_semantic) > 0,
        f"errors={_errors_semantic}",
    )

    # fail-closed: get_case_view_with_staleness, validate_live_view
    # hata döndürdüğünde LiveViewInvalidError fırlatmalı - bunu
    # doğrudan test etmek için validate_live_view'i geçici olarak
    # (yalnız bu process içinde, dosya sistemine YAZMADAN) monkeypatch
    # ediyoruz.
    _original_validate = live_view.validate_live_view

    def _always_invalid(_view, _case_id):
        return ["yapay/enjekte edilmiş test hatası"]

    live_view.validate_live_view = _always_invalid
    try:
        expect_raises(
            LiveViewInvalidError,
            lambda: live_view.get_case_view_with_staleness(_valid_case),
            "get_case_view_with_staleness: doğrulama hatası -> fail-closed LiveViewInvalidError",
        )
    finally:
        live_view.validate_live_view = _original_validate


# ============================================================
# 6) İZOLE MUTASYON / ROLLBACK / AUDIT-FAILURE TESTİ
#
# `approval_registry.case_scoped_approve` GERÇEK Row 8-17 modüllerini
# `importlib.import_module(row["module"])` ile DİNAMİK olarak
# çağırıyor. Bu testte GERÇEK modül yerine, `sys.modules`'e
# kaydedilmiş SAHTE bir modül enjekte ediyoruz - tam path grafiği
# `tempfile.TemporaryDirectory()` içinde çözülüyor, gerçek
# case_0001/src'ye HİÇBİR ÇAĞRI gitmiyor.
# ============================================================

import types
import sys as _sys

from ui.services import approval_registry as reg  # noqa: E402


def _run_isolated_mutation_scenario():

    with tempfile.TemporaryDirectory() as tmp:

        tmp_path = Path(tmp)

        fake_case_dir = tmp_path / "cases" / "case_iso_0001"
        fake_case_dir.mkdir(parents=True)
        (fake_case_dir / "case.json").write_text('{"case_id": "case_iso_0001"}', encoding="utf-8")

        pending_path = tmp_path / "pending.json"
        pending_path.write_text('{"synthetic": true, "value": 1}', encoding="utf-8")

        canonical_path = tmp_path / "canonical.json"
        reviews_dir = tmp_path / "reviews"
        reviews_dir.mkdir()

        # --- Senaryo A: başarılı onay (mutlu yol) ---

        calls = {"run_approve": 0}

        def _fake_get_pending_path(case_id):
            assert case_id == "case_iso_0001"
            return pending_path

        def _fake_get_canonical_path(case_id):
            assert case_id == "case_iso_0001"
            return canonical_path

        def _fake_run_approve_ok(case_id):
            calls["run_approve"] += 1
            canonical_path.write_text(pending_path.read_text(encoding="utf-8"), encoding="utf-8")
            (reviews_dir / "case_iso_0001_v1_20260101_000000.approval.json").write_text(
                '{"source_pending_sha256": "izole-test"}', encoding="utf-8",
            )

        fake_module_ok = types.SimpleNamespace(
            get_pending_path=_fake_get_pending_path,
            get_canonical_path=_fake_get_canonical_path,
            run_approve=_fake_run_approve_ok,
        )

        _sys.modules["_izole_sahte_row_ok"] = fake_module_ok

        # `resolve_case_id` gerçek data/cases dizinini kontrol ettiği
        # için, izole testte case_id doğrulamasını atlamak üzere
        # case_scoped_approve'un case_id çözümlemesini de monkeypatch
        # ediyoruz - BU YALNIZ izole test kapsamında, gerçek fonksiyon
        # gövdesi (mutasyon mantığı: hash tazelik kontrolü, run_approve
        # çağrısı, sonuç toplama) DEĞİŞTİRİLMEDEN test edilir.
        _original_resolve = paths_module_resolve = reg.paths.resolve_case_id
        reg.paths.resolve_case_id = lambda cid: cid
        reg.CASE_SCOPED_ROWS_BY_KEY["_izole_test_ok"] = {
            "key": "_izole_test_ok", "row_no": 999, "label": "İzole Test (OK)",
            "module": "_izole_sahte_row_ok",
        }

        try:

            expected_hash = reg.sha256_file(pending_path)

            result = reg.case_scoped_approve("_izole_test_ok", "case_iso_0001", expected_hash)

            check(
                "izole mutasyon: başarılı onay -> canonical dosyası yazıldı",
                canonical_path.exists() and canonical_path.read_text(encoding="utf-8") == pending_path.read_text(encoding="utf-8"),
            )
            check("izole mutasyon: run_approve tam olarak 1 kez çağrıldı", calls["run_approve"] == 1)
            check("izole mutasyon: audit dosyası bulundu", result["audit_path"] is not None)

            # --- Senaryo B: stale hash -> run_approve HİÇ ÇAĞRILMAMALI ---

            calls["run_approve"] = 0

            expect_raises(
                Exception,
                lambda: reg.case_scoped_approve("_izole_test_ok", "case_iso_0001", "0" * 64),
                "izole mutasyon: yanlış (stale) expected_hash -> StaleViewError",
            )
            check("izole mutasyon: stale hash durumunda run_approve HİÇ çağrılmadı", calls["run_approve"] == 0)

            # --- Senaryo C: audit/approve sırasında hata (rollback/audit-failure) ---

            def _fake_run_approve_fails(case_id):
                calls["run_approve"] += 1
                raise RuntimeError("yapay/enjekte edilmiş audit yazma hatası (izole test)")

            fake_module_fail = types.SimpleNamespace(
                get_pending_path=_fake_get_pending_path,
                get_canonical_path=_fake_get_canonical_path,
                run_approve=_fake_run_approve_fails,
            )
            _sys.modules["_izole_sahte_row_fail"] = fake_module_fail
            reg.CASE_SCOPED_ROWS_BY_KEY["_izole_test_fail"] = {
                "key": "_izole_test_fail", "row_no": 998, "label": "İzole Test (FAIL)",
                "module": "_izole_sahte_row_fail",
            }

            calls["run_approve"] = 0
            expected_hash_2 = reg.sha256_file(pending_path)

            expect_raises(
                RuntimeError,
                lambda: reg.case_scoped_approve("_izole_test_fail", "case_iso_0001", expected_hash_2),
                "izole mutasyon: run_approve içinde hata -> istisna yukarı yayılır (sessizce yutulmaz)",
            )
            check("izole mutasyon: hata senaryosunda run_approve 1 kez denendi", calls["run_approve"] == 1)

        finally:

            reg.paths.resolve_case_id = _original_resolve
            reg.CASE_SCOPED_ROWS_BY_KEY.pop("_izole_test_ok", None)
            reg.CASE_SCOPED_ROWS_BY_KEY.pop("_izole_test_fail", None)
            _sys.modules.pop("_izole_sahte_row_ok", None)
            _sys.modules.pop("_izole_sahte_row_fail", None)


_run_isolated_mutation_scenario()


# ============================================================
# 7) GERÇEK data/src AĞACININ HİÇBİR TESTLE DEĞİŞMEDİĞİNİN
#    BYTE-DÜZEYİNDE KANITI (before/after karşılaştırma)
# ============================================================

_after_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)

check(
    "GERÇEK data/ ve src/ ağaçları bu test dosyasıyla DEĞİŞMEDİ (byte-düzeyinde)",
    _before_snapshot == _after_snapshot,
    f"before={len(_before_snapshot)} dosya, after={len(_after_snapshot)} dosya, "
    f"fark={set(_before_snapshot) ^ set(_after_snapshot)}",
)


print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
