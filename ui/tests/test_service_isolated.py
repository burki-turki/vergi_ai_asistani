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

import json
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
from ui.services import authz as _authz                # noqa: E402 (Row 19B)
from ui.services import mutation_approval_facade as _mutfacade  # noqa: E402 (Row 19C-2a Step 8)
from ui.services import mutation_lock as _ml                     # noqa: E402 (Row 19C-2a Step 8)
from ui.services.common import UnknownCaseError, LiveViewInvalidError, StaleViewError  # noqa: E402

# Row 19B: case_scoped_approve now REQUIRES a `principal` and
# independently re-checks authorization via authz.authorize_case_access.
# This isolated suite fakes a lawyer principal with a real assignment to
# "case_iso_0001", via the InMemoryAuthzRepository - no psycopg/DB needed,
# preserving this file's "no external deps" property.
_izole_authz_repo = _authz.InMemoryAuthzRepository()
_izole_authz_repo.sessions[1] = _authz.SessionRecord(user_id=1, current_authz_version=1, disabled=False)
_izole_authz_repo.assignments[(1, "case_iso_0001")] = _authz.CaseAssignmentRecord(role="lawyer")
_izole_lawyer_principal = _authz.Principal(user_id=1, session_id=1, role_version_at_issue=1)

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
# 6) İZOLE MUTASYON / STALE-HASH / WRITER-HATASI TESTİ
#
# ROW 19C-2a STEP 8: `approval_registry.case_scoped_approve` artık
# KENDİSİ hiçbir mutasyon mantığı YÜRÜTMÜYOR - TÜMÜNÜ (Row 19C-1'in
# journal/coordinator altyapısı ÜZERİNDEN) `mutation_approval_facade.
# approve_case_scoped_mutation()`'a devrediyor (bkz. o fonksiyonun
# KENDİ docstring'i, `ui/services/approval_registry.py`). Bu bölüm bu
# yüzden artık İKİ KATMANI birlikte, ama HÂLÂ SIFIR harici bağımlılıkla
# (gerçek Postgres/psycopg YOK) sahteliyor:
#
#   - `mutation.mutation_journal`'ın kendisi: `ui/tests/
#     test_mutation_approval_facade_isolated.py`'nin (ve KENDİSİNİN de
#     `ui/tests/test_mutation_coordinator_isolated.py`'den kopyaladığı)
#     KANITLANMIŞ `FakeJournalCursor`/`FakeJournalConn` çiftinin bu
#     dosyaya ait TAZE bir kopyası (bu projenin "her test dosyası kendi
#     sahte sınıflarına SAHİPTİR" kuralı gereği);
#   - case-scoped onay ailesi modülü: `sys.modules`'e kayıtlı sahte bir
#     modül, ARTIK `reg.CASE_SCOPED_ROWS_BY_KEY` YERİNE (yalnız `row`
#     metadata'sı için hâlâ ORADA da kayıtlı olması gerekiyor)
#     `mutation_approval_facade.ROW_KEY_TO_MODULE_NAME`'e enjekte
#     ediliyor - facade'in kendi modül çözümlemesi ARTIK BUNU kullanıyor
#     (bkz. o modülün kendi başlık yorumu: bu sözlük SABİTTİR ve
#     `approval_registry`'ninkinden AYRIDIR, döngüsel import'tan
#     kaçınmak için);
#   - `ui.services.mutation_lock.acquire_case_lock_session`/
#     `release_lock_session`: sahte, her zaman başarılı fonksiyonlarla
#     monkeypatch (facade bunları DOĞRUDAN çağırıyor - `mutation_
#     coordinator.run_mutation()`'ın aksine, kendisi lock almıyor).
#
# `case_id` doğrulaması hâlâ AYNI teknikle atlanıyor: `paths.
# resolve_case_id` modül-seviyesinde (`reg.paths` İLE `ui.services.
# authz`'ın kendi LAZY `from ui.services.paths import resolve_case_id`
# çağrısı AYNI paylaşılan modül nesnesini görür) `lambda cid: cid`'e
# monkeypatch edilir - bu, Row 19C-2a'dan ÖNCE de `authorize_case_
# access`'in KENDİSİ zaten gerçek dosya sistemi çözümlemesini
# yapıyorken kullanılan AYNI teknik, hiçbir değişiklik gerekmedi.
# ============================================================

import types
import sys as _sys

from ui.services import approval_registry as reg  # noqa: E402


class _IzoleFakeIntegrityError(Exception):
    pass


class _IzoleFakeJournalCursor:
    """Row 19C-2a Step 8: taze, bu dosyaya özgü kopya - bkz.
    `ui/tests/test_mutation_approval_facade_isolated.py`'nin kendi
    `FakeJournalCursor`'ı (AYNI SQL şekilleri, gerçek `run_mutation()`'a
    karşı orada zaten kanıtlanmış)."""

    def __init__(self, table, calls):
        self._table = table
        self._calls = calls
        self._last_result = None
        self.rowcount = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _row(self, journal_id):
        for r in self._table:
            if r["id"] == journal_id:
                return r
        raise AssertionError(f"sahte journal tablosunda id={journal_id} yok")

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._calls.append(normalized.split()[0])

        if normalized.startswith("SELECT 1 FROM mutation.mutation_journal"):
            (resource_key,) = params
            hit = any(
                r["resource_key"] == resource_key
                and r["state"] in ("prepared", "executing", "reconciliation_required")
                for r in self._table
            )
            self._last_result = (1,) if hit else None
            self.rowcount = 1 if hit else 0

        elif normalized.startswith("SELECT id, state, request_fingerprint, observed_post_hash"):
            (idempotency_key,) = params
            matches = [r for r in self._table if r["idempotency_key"] == idempotency_key]
            if not matches:
                self._last_result = None
                self.rowcount = 0
            else:
                r = matches[0]
                self._last_result = (
                    r["id"], r["state"], r["request_fingerprint"], r["observed_post_hash"],
                    r["failure_code"], r["resolution_code"],
                )
                self.rowcount = 1

        elif normalized.startswith("INSERT INTO mutation.mutation_journal"):
            (
                resource_key, action_family, actor_user_id, actor_label, target_ref, target_state,
                pre_hash, pre_revision, idempotency_key, request_fingerprint,
            ) = params
            conflict = any(r["idempotency_key"] == idempotency_key for r in self._table)
            if conflict:
                raise _IzoleFakeIntegrityError(
                    f"duplicate key value violates unique constraint "
                    f"\"mutation_journal_idempotency_key_uniq\": idempotency_key={idempotency_key!r}"
                )
            new_id = len(self._table) + 1
            self._table.append({
                "id": new_id,
                "resource_key": resource_key,
                "action_family": action_family,
                "actor_user_id": actor_user_id,
                "actor_label": actor_label,
                "target_ref": target_ref,
                "target_state": target_state,
                "pre_hash": pre_hash,
                "pre_revision": pre_revision,
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "state": "prepared",
                "failure_code": None,
                "resolution_code": None,
                "executing_at": None,
                "resolved_at": None,
                "observed_post_hash": None,
            })
            self._last_result = (new_id,)
            self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'executing'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "executing"
            self._row(journal_id)["executing_at"] = "FAKE_TIMESTAMP"
            self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'completed'"):
            observed_post_hash, journal_id = params
            row = self._row(journal_id)
            row["state"] = "completed"
            row["observed_post_hash"] = observed_post_hash
            row["resolved_at"] = "FAKE_TIMESTAMP"
            self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'reconciliation_required'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "reconciliation_required"
            self.rowcount = 1

        else:
            raise AssertionError(f"beklenmeyen SQL: {sql}")

    def fetchone(self):
        return self._last_result


class _IzoleFakeJournalConn:
    def __init__(self, table=None):
        self.table = table if table is not None else []
        self.calls = []
        self.closed = False

    def cursor(self):
        return _IzoleFakeJournalCursor(self.table, self.calls)

    def close(self):
        self.closed = True


_izole_lock_calls = []
_izole_original_acquire_case = _ml.acquire_case_lock_session
_izole_original_release = _ml.release_lock_session


def _izole_fake_acquire_case_lock_session(conn, case_id):
    _izole_lock_calls.append(("acquire", case_id))
    return 111


def _izole_fake_release_lock_session(conn, advisory_lock_id):
    _izole_lock_calls.append(("release", advisory_lock_id))
    return True


def _run_isolated_mutation_scenario():

    with tempfile.TemporaryDirectory() as tmp:

        tmp_path = Path(tmp)

        # ROW 19C-3a SLICE 2: the facade's pre-lock/under-lock nested
        # path-containment verification reads `module.CASES_DIR` and
        # re-derives `CASES_DIR/case_id/...` from each raw path it is
        # given (`ui.services.mutation_approval_facade._resolve_case_
        # root_real()`/`_verify_nested()`) - so this fixture is nested
        # one level deeper (`tmp_path/case_iso_0001/...`, never
        # `tmp_path/...` directly) to present a genuine `CASES_DIR/
        # case_id` shape that `path_containment.resolve_existing()`
        # can verify for real (never bypassed/monkeypatched);
        # `fake_module_ok`/`fake_module_fail` below both set
        # `CASES_DIR = tmp_path` accordingly.
        case_root = tmp_path / "case_iso_0001"
        case_root.mkdir()

        pending_path = case_root / "pending.json"
        pending_path.write_text('{"synthetic": true, "value": 1}', encoding="utf-8")

        canonical_path = case_root / "canonical.json"
        reviews_dir = case_root / "reviews"
        reviews_dir.mkdir()

        # --- Senaryo A: başarılı onay (mutlu yol) ---

        calls = {"run_approve": 0}

        def _fake_get_pending_path(case_id):
            assert case_id == "case_iso_0001"
            return pending_path

        def _fake_get_canonical_path(case_id):
            assert case_id == "case_iso_0001"
            return canonical_path

        def _fake_run_approve_ok(case_id, *, mutation_idempotency_key=None, mutation_resource_key=None):
            # ROW 19C-2a AUDIT BINDING: BOTH audit-binding parameters
            # are KEYWORD-ONLY, exactly as all 10 real
            # src/*_approval.py modules' own `run_approve()` now are,
            # and the audit record this fake writes carries all THREE
            # fields the facade's FOUR EXACT BINDINGS check reads back
            # (`mutation_idempotency_key`, `mutation_resource_key`,
            # `canonical_sha256`).
            calls["run_approve"] += 1
            calls["mutation_idempotency_key"] = mutation_idempotency_key
            calls["mutation_resource_key"] = mutation_resource_key
            canonical_path.write_text(pending_path.read_text(encoding="utf-8"), encoding="utf-8")
            (reviews_dir / "case_iso_0001_v1_20260101_000000.approval.json").write_text(
                json.dumps({
                    "source_pending_sha256": "izole-test",
                    "mutation_idempotency_key": mutation_idempotency_key,
                    "mutation_resource_key": mutation_resource_key,
                    "canonical_sha256": reg.sha256_file(canonical_path),
                }),
                encoding="utf-8",
            )

        fake_module_ok = types.SimpleNamespace(
            get_pending_path=_fake_get_pending_path,
            get_canonical_path=_fake_get_canonical_path,
            run_approve=_fake_run_approve_ok,
            CASES_DIR=tmp_path,
        )

        _sys.modules["_izole_sahte_row_ok"] = fake_module_ok

        # `resolve_case_id` gerçek data/cases dizinini kontrol ettiği
        # için, izole testte case_id doğrulamasını atlamak üzere modül
        # seviyesindeki `paths.resolve_case_id`'yi monkeypatch ediyoruz
        # (bkz. bu bölümün kendi başlık yorumu - `ui.services.authz`'ın
        # KENDİ lazy import'u bunu AYNEN görür).
        _original_resolve = real_paths.resolve_case_id
        real_paths.resolve_case_id = lambda cid: cid
        reg.CASE_SCOPED_ROWS_BY_KEY["_izole_test_ok"] = {
            "key": "_izole_test_ok", "row_no": 999, "label": "İzole Test (OK)",
            "module": "_izole_sahte_row_ok",
        }
        _mutfacade.ROW_KEY_TO_MODULE_NAME["_izole_test_ok"] = "_izole_sahte_row_ok"
        _ml.acquire_case_lock_session = _izole_fake_acquire_case_lock_session
        _ml.release_lock_session = _izole_fake_release_lock_session

        journal_conn = _IzoleFakeJournalConn()

        try:

            expected_hash = reg.sha256_file(pending_path)

            result = reg.case_scoped_approve(
                "_izole_test_ok", "case_iso_0001", expected_hash,
                principal=_izole_lawyer_principal, authz_repository=_izole_authz_repo,
                conn_factory=lambda: journal_conn,
            )

            check(
                "izole mutasyon: başarılı onay -> canonical dosyası yazıldı",
                canonical_path.exists() and canonical_path.read_text(encoding="utf-8") == pending_path.read_text(encoding="utf-8"),
            )
            check("izole mutasyon: run_approve tam olarak 1 kez çağrıldı", calls["run_approve"] == 1)
            check("izole mutasyon: audit dosyası bulundu", result["audit_path"] is not None)
            check(
                "izole mutasyon: journal satırı 'completed' durumunda",
                journal_conn.table and journal_conn.table[-1]["state"] == "completed",
            )
            check(
                "izole mutasyon: dönüş sözlüğü journal_id/replayed alanlarını taşıyor (Step 7 - additive)",
                isinstance(result["journal_id"], int) and result["replayed"] is False,
            )

            # --- Senaryo B: stale hash -> run_approve HİÇ ÇAĞRILMAMALI,
            #     hiçbir journal satırı OLUŞTURULMAMALI (precondition_
            #     callback, run_mutation()'ın 'prepared' satırı EKLEMEDEN
            #     ÖNCEKİ 5. adımında fırlatır). ---

            calls["run_approve"] = 0
            rows_before_b = len(journal_conn.table)

            expect_raises(
                StaleViewError,
                lambda: reg.case_scoped_approve(
                    "_izole_test_ok", "case_iso_0001", "0" * 64,
                    principal=_izole_lawyer_principal, authz_repository=_izole_authz_repo,
                    conn_factory=lambda: journal_conn,
                ),
                "izole mutasyon: yanlış (stale) expected_hash -> StaleViewError",
            )
            check("izole mutasyon: stale hash durumunda run_approve HİÇ çağrılmadı", calls["run_approve"] == 0)
            check(
                "izole mutasyon: stale hash durumunda hiçbir journal satırı eklenmedi",
                len(journal_conn.table) == rows_before_b,
            )

            # --- Senaryo C: run_approve içinde hata (writer exception) ->
            #     istisna DEĞİŞTİRİLMEDEN yukarı yayılır, journal satırı
            #     'reconciliation_required'de kalır (ASLA 'failed' değil -
            #     bkz. mutation_coordinator.run_mutation()'ın kendi
            #     except Exception davranışı). ---

            def _fake_run_approve_fails(case_id, *, mutation_idempotency_key=None, mutation_resource_key=None):
                calls["run_approve"] += 1
                raise RuntimeError("yapay/enjekte edilmiş audit yazma hatası (izole test)")

            fake_module_fail = types.SimpleNamespace(
                get_pending_path=_fake_get_pending_path,
                get_canonical_path=_fake_get_canonical_path,
                run_approve=_fake_run_approve_fails,
                CASES_DIR=tmp_path,
            )
            _sys.modules["_izole_sahte_row_fail"] = fake_module_fail
            reg.CASE_SCOPED_ROWS_BY_KEY["_izole_test_fail"] = {
                "key": "_izole_test_fail", "row_no": 998, "label": "İzole Test (FAIL)",
                "module": "_izole_sahte_row_fail",
            }
            _mutfacade.ROW_KEY_TO_MODULE_NAME["_izole_test_fail"] = "_izole_sahte_row_fail"

            calls["run_approve"] = 0
            expected_hash_2 = reg.sha256_file(pending_path)

            expect_raises(
                RuntimeError,
                lambda: reg.case_scoped_approve(
                    "_izole_test_fail", "case_iso_0001", expected_hash_2,
                    principal=_izole_lawyer_principal, authz_repository=_izole_authz_repo,
                    conn_factory=lambda: journal_conn,
                ),
                "izole mutasyon: run_approve içinde hata -> istisna yukarı yayılır (sessizce yutulmaz)",
            )
            check("izole mutasyon: hata senaryosunda run_approve 1 kez denendi", calls["run_approve"] == 1)
            check(
                "izole mutasyon: hata senaryosunda journal satırı 'reconciliation_required'de kaldı (ASLA 'failed' değil)",
                journal_conn.table[-1]["state"] == "reconciliation_required",
            )
            check(
                "izole mutasyon: hata senaryosunda lock yine de alındı VE bırakıldı (finally garantisi)",
                ("acquire", "case_iso_0001") in _izole_lock_calls and ("release", 111) in _izole_lock_calls,
            )

        finally:

            real_paths.resolve_case_id = _original_resolve
            reg.CASE_SCOPED_ROWS_BY_KEY.pop("_izole_test_ok", None)
            reg.CASE_SCOPED_ROWS_BY_KEY.pop("_izole_test_fail", None)
            _mutfacade.ROW_KEY_TO_MODULE_NAME.pop("_izole_test_ok", None)
            _mutfacade.ROW_KEY_TO_MODULE_NAME.pop("_izole_test_fail", None)
            _sys.modules.pop("_izole_sahte_row_ok", None)
            _sys.modules.pop("_izole_sahte_row_fail", None)
            _ml.acquire_case_lock_session = _izole_original_acquire_case
            _ml.release_lock_session = _izole_original_release


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
