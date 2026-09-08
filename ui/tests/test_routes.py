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
import json
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
from ui.services import authz as _authz
from ui.services import mutation_approval_facade as mutfacade  # noqa: E402 (Row 19C-2a Step 8)
from ui.services import mutation_lock as ml                     # noqa: E402 (Row 19C-2a Step 8)
from ui.services.common import UnknownCaseError
import ui.main as main_module
from ui.main import app

# ============================================================
# Row 19B - AUTHENTICATED-SESSION TEST FIXTURE
#
# Every route now requires require_principal()/authorize_case_access()
# (see ui/main.py's Row 19B route-layer remediation notes). This file
# tests ROUTE MECHANICS (CSRF, cross-origin, body-size limits, path
# traversal, live-view fail-closed rendering) - NOT the auth/session/
# authorization layer itself, which has its own dedicated suites
# (ui/tests/test_auth_routes.py, ui/tests/test_authz_isolated.py -
# 15/15). `ui.main`'s OWN bound names (imported BY VALUE from
# ui.auth_routes at ui.main's import time - patching
# ui.auth_routes's names afterwards would have NO effect on ui.main's
# routes) are monkeypatched to a fixed test principal + an
# always-allow (lawyer) in-memory authorization repository - every
# route's real call sites still run, only the session/DB lookup
# underneath them is faked. This file never imported a shared
# `_CSRF_SECRET` (its tests always extract a real, server-rendered
# token from the GET page first via `_extract_hidden_input` - see
# below), so no separate test-CSRF-secret constant is needed here;
# `csrf_secret_for_request` is monkeypatched to a fixed value purely
# so GET-time generation and POST-time verification agree.
# ============================================================


class _AllowAllAsLawyerRepository(_authz.InMemoryAuthzRepository):
    """Grants the fixed test principal a 'lawyer' assignment on ANY
    case_id, and a valid/current session state - this file's tests
    exercise route MECHANICS, not authorization DECISIONS (those are
    covered by test_authz_isolated.py/test_auth_routes.py)."""

    def get_session_authz_state(self, principal):
        return _authz.SessionRecord(
            user_id=principal.user_id, current_authz_version=principal.role_version_at_issue, disabled=False,
        )

    def get_active_case_assignment(self, user_id, case_id):
        return _authz.CaseAssignmentRecord(role="lawyer")


_TEST_PRINCIPAL = _authz.Principal(user_id=999, session_id=999, role_version_at_issue=1)
_TEST_REPO = _AllowAllAsLawyerRepository()

main_module.require_principal = lambda request: _TEST_PRINCIPAL
main_module.authorize_or_redirect = lambda request, case_id, capability: _authz.authorize_case_access(
    _TEST_PRINCIPAL, case_id, capability, repository=_TEST_REPO,
)
main_module.require_principal_and_case = lambda request, case_id, capability: (
    _TEST_PRINCIPAL,
    _authz.authorize_case_access(_TEST_PRINCIPAL, case_id, capability, repository=_TEST_REPO),
)
main_module.csrf_secret_for_request = lambda request, principal: b"test-only-fixed-csrf-secret-32b"
main_module.has_capability = lambda request, principal, case_id, capability: True

# ============================================================
# Row 19B targeted remediation (finding 2) - GET / case-enumeration
# route fixture.
#
# `ui.main.index()` now calls `list_accessible_case_ids(request,
# principal)` (imported BY VALUE from ui.auth_routes at ui.main's
# import time, same reason main_module.require_principal etc. above
# are patched on ui.main directly rather than on ui.auth_routes).
#
# The fake below routes through the REAL `authz.list_accessible_case_ids`
# decision function (not a hand-substituted list) against a fully
# controllable InMemoryAuthzRepository - this exercises the ACTUAL
# route wiring (main.py calls the authz-layer function and renders
# EXACTLY what it returns, nothing more) while keeping the
# role/assignment data itself test-controlled, exactly like
# `_AllowAllAsLawyerRepository` does for the per-case routes above.
# `_TEST_PRINCIPAL` (user_id=999) is fixed for the whole file (main_module.
# require_principal always returns it) - different "roles" across the
# scenarios below are expressed by reconfiguring what this repository
# knows about user_id 999, not by swapping principals.
# ============================================================

_LISTING_REPO = _authz.InMemoryAuthzRepository()
_LISTING_REPO.sessions[999] = _authz.SessionRecord(user_id=999, current_authz_version=1, disabled=False)
# NOTE: the baseline "matches original T01b expectation" assignment
# (999, case_id) is seeded further below, right after `case_id` is
# first defined from the real case data (see "case_id = case_ids[0]") -
# `case_id` does not exist yet at this point in the file, and seeding
# it here unconditionally caused a NameError at import time.
_LISTING_STALE_MARKER = "__row19b_stale_unresolvable_case__"


def _listing_resolve_case_id(cid):
    if cid == _LISTING_STALE_MARKER:
        raise UnknownCaseError(f"{cid} does not exist on disk")
    return cid


def _fake_list_accessible_case_ids(request, principal):
    return _authz.list_accessible_case_ids(
        principal, repository=_LISTING_REPO, resolve_case_id=_listing_resolve_case_id,
    )


main_module.list_accessible_case_ids = _fake_list_accessible_case_ids

# The service layer independently RE-RUNS authz.authorize_case_access
# with its OWN default repository (a real Postgres-backed one) unless a
# route passes authz_repository= explicitly - main.py does NOT (by
# design: production always uses the real repository). Route-mechanic
# tests below therefore override the service module's
# _default_authz_repository() directly, rather than main.py's call
# sites (which must stay production-faithful).
#
# ROW 19C-2a STEP 8: this used to be `reg._default_authz_repository`
# (approval_registry.py's OWN copy of this fallback). Step 7 removed
# that function entirely - `case_scoped_approve()` no longer calls
# `authz.authorize_case_access()` itself at all; it delegates the
# ENTIRE mutation, authz re-check included, to `mutation_approval_
# facade.approve_case_scoped_mutation()`, whose OWN `_default_authz_
# repository()` is what actually runs whenever `main.py`'s route calls
# `case_scoped_approve()` without an explicit `authz_repository=` (see
# `ui/services/approval_registry.py`'s own comment on this exact
# rename). Patching the OLD, now-nonexistent-as-load-bearing `reg.
# _default_authz_repository` name would silently do NOTHING (Python
# happily sets an unused attribute on a module) - a real, silent test
# gap this step closes.
#
# ROW 19C-2a (DUAL AUTHZ): `_default_authz_repository()` now returns a
# `(repository, close)` PAIR, not a bare repository. The facade calls
# `authorize_case_access()` TWICE per approval - once OUTER (before any
# connection/lock/hash/journal SQL) and once INNER (under the resource
# lock, authoritative) - against the SAME repository, and closes the
# IAM connection exactly once afterwards, in a `finally`. This fake
# therefore returns a no-op closer: `_TEST_REPO` is an in-memory
# repository this file owns for its whole lifetime and must NOT be
# torn down after a single request.
mutfacade._default_authz_repository = lambda: (_TEST_REPO, lambda: None)

# ROW 19C-2a STEP 8 (NEW): `case_scoped_approve()` now runs the ENTIRE
# approval as one journaled mutation via `mutation_coordinator.
# run_mutation()`, which needs a `mutation.mutation_journal`-shaped
# connection - `main.py`'s route never passes `conn_factory=` either
# (production-faithful, same reasoning as `authz_repository` above), so
# without faking this, EVERY confirm POST in this file would attempt a
# REAL psycopg connection via `ui.services.db.get_session_lock_
# connection()` and fail in this FastAPI-only, no-Postgres-needed test
# file. A FRESH fake table per call (never one shared table across this
# file's 19+ scenarios) deliberately avoids any cross-scenario
# idempotency-replay interaction this file's own tests never intend to
# exercise (that is `ui/tests/test_mutation_approval_facade_isolated.py`'s
# own, dedicated job).


class _RouteFakeIntegrityError(Exception):
    pass


class _RouteFakeJournalCursor:
    """Row 19C-2a Step 8: a fresh, file-local copy of the SAME
    fake-journal-cursor shape `ui/tests/test_mutation_approval_facade_
    isolated.py` and `ui/tests/test_service_isolated.py` already use
    (each proven correct there against the real `run_mutation()`)."""

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
                raise _RouteFakeIntegrityError(
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


class _RouteFakeJournalConn:
    def __init__(self):
        self.table = []
        self.calls = []
        self.closed = False

    def cursor(self):
        return _RouteFakeJournalCursor(self.table, self.calls)

    def close(self):
        self.closed = True


mutfacade._default_conn_factory = lambda: _RouteFakeJournalConn()

# ROW 19C-2a STEP 8 (NEW): `case_scoped_approve()`/the facade also call
# `ui.services.mutation_lock.acquire_case_lock_session`/
# `release_lock_session` directly (real Postgres advisory locks) -
# faked here to always succeed, same pattern already proven in
# `ui/tests/test_mutation_approval_facade_isolated.py`/`ui/tests/
# test_service_isolated.py`. This file tests ROUTE mechanics, never
# lock-acquisition semantics themselves (those have their own dedicated
# suites), so no call-tracking is needed here beyond "always succeeds".
ml.acquire_case_lock_session = lambda conn, case_id: 111
ml.release_lock_session = lambda conn, advisory_lock_id: True

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

        # ROW 19C-3a SLICE 2: the facade's pre-lock/under-lock nested
        # path-containment verification reads `module.CASES_DIR` and
        # re-derives `CASES_DIR/case_id/...` from each raw path it is
        # given - pending/canonical/reviews therefore live inside
        # `fake_case_dir` (which already has the right `CASES_DIR/
        # case_id` shape for the authz fixture above), never directly
        # under `tmp_path`; `fake_module` below sets `CASES_DIR =
        # tmp_path / "cases"` accordingly.
        pending_path = fake_case_dir / "pending.json"
        pending_path.write_text('{"synthetic": true}', encoding="utf-8")
        canonical_path = fake_case_dir / "canonical.json"
        reviews_dir = fake_case_dir / "reviews"
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

        def _run_approve(cid, *, mutation_idempotency_key=None, mutation_resource_key=None):
            # ROW 19C-2a: `mutation_idempotency_key` and
            # `mutation_resource_key` are the two additive,
            # KEYWORD-ONLY audit-binding parameters all 10 REAL
            # src/*_approval.py modules' own `run_approve()` now carry
            # (verified by AST across every one of them), and which
            # `mutation_approval_facade.writer_callback()` always passes
            # BY KEYWORD, BOTH TOGETHER - this fake must accept both, in
            # the same keyword-only shape, or every confirm POST in this
            # fixture would raise a spurious TypeError from inside
            # writer_callback (itself indistinguishable, from the
            # coordinator's own point of view, from any other writer
            # exception - but not what THIS fixture's "approve_exception"
            # behavior is meant to simulate).
            calls["run_approve"] += 1
            calls["mutation_idempotency_key"] = mutation_idempotency_key
            calls["mutation_resource_key"] = mutation_resource_key
            if behavior == "approve_exception":
                raise RuntimeError(f"sentetik onay hatası - ham path: {tmp_path / 'gizli'}")
            canonical_path.write_text(pending_path.read_text(encoding="utf-8"), encoding="utf-8")
            (reviews_dir / "iso_v1.approval.json").write_text(
                json.dumps({
                    "source_pending_sha256": "x",
                    "mutation_idempotency_key": mutation_idempotency_key,
                    "mutation_resource_key": mutation_resource_key,
                    "canonical_sha256": hashlib.sha256(
                        canonical_path.read_bytes()
                    ).hexdigest(),
                }),
                encoding="utf-8",
            )

        fake_module = types.SimpleNamespace(
            get_pending_path=_get_pending_path,
            get_canonical_path=_get_canonical_path,
            inspect_pending=_inspect_pending,
            run_approve=_run_approve,
            CASES_DIR=tmp_path / "cases",
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
        # ROW 19C-2a Step 8 (NEW): `case_scoped_approve()` now resolves
        # the module to call via `mutation_approval_facade.
        # ROW_KEY_TO_MODULE_NAME` (a SEPARATE, fixed dict from
        # `reg.CASE_SCOPED_ROWS_BY_KEY` - see that module's own header
        # comment on why) - registering only the line above, as this
        # fixture did before this step, would make the facade raise
        # `KeyError` for every one of this fixture's own synthetic
        # row_keys.
        mutfacade.ROW_KEY_TO_MODULE_NAME[row_key] = module_name

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
            mutfacade.ROW_KEY_TO_MODULE_NAME.pop(row_key, None)
            sys.modules.pop(module_name, None)


case_ids = svc_paths.list_case_ids()
check("en az bir case bulundu", len(case_ids) > 0, f"case_ids={case_ids}")

if not case_ids:
    print("Hiç case yok - test devam edemiyor.")
    sys.exit(1)

case_id = case_ids[0]

# Row 19B test-harness reconciliation: this is the baseline assignment
# T01b's original expectation depends on (`case_id in r_index.text`) -
# moved here, after `case_id` is actually defined, instead of at
# `_LISTING_REPO`'s construction above (where `case_id` did not exist
# yet and referencing it raised a NameError at import time).
_LISTING_REPO.assignments[(999, case_id)] = _authz.CaseAssignmentRecord(role="lawyer")

# --- T00: loopback-only middleware gerçekten reddediyor mu? ---
_loopback_test_client = TestClient(app, client=("203.0.113.7", 55555))
r = _loopback_test_client.get("/")
check("T00 loopback olmayan istemci -> 403", r.status_code == 403, f"status={r.status_code}")

# --- T01: ana sayfa ---
r_index = client.get("/")
check("T01 GET / -> 200", r_index.status_code == 200, f"status={r_index.status_code}")
check("T01b GET / case_id'yi listeliyor", case_id in r_index.text)

# ============================================================
# T01c-T01h: Row 19B targeted remediation (finding 2) - GET / case
# enumeration is now an AUTHZ-LAYER decision (authz.list_accessible_case_ids
# via main_module.list_accessible_case_ids), not the unfiltered
# `paths.list_case_ids()`. Each scenario reconfigures `_LISTING_REPO`
# for the fixed test principal (user_id=999) and/or a second synthetic
# user_id, then re-requests GET / and inspects the rendered page.
# ============================================================

_OTHER_CASE_A = "case_row19b_listing_a"
_OTHER_CASE_B = "case_row19b_listing_b"


def _reset_listing_repo():
    _LISTING_REPO.assignments.clear()
    _LISTING_REPO.admins.clear()
    _LISTING_REPO.assignments[(999, case_id)] = _authz.CaseAssignmentRecord(role="lawyer")


# --- T01c: lawyer sees exactly their own active, resolvable assigned cases ---
_reset_listing_repo()
_LISTING_REPO.assignments[(999, _OTHER_CASE_A)] = _authz.CaseAssignmentRecord(role="lawyer")
r = client.get("/")
check(
    "T01c lawyer (GET /) sees ALL of their own active assigned+resolvable case ids",
    case_id in r.text and _OTHER_CASE_A in r.text,
    f"status={r.status_code}",
)

# --- T01d: analyst role behaves the same way for listing purposes (read-only capability does not affect visibility) ---
_reset_listing_repo()
_LISTING_REPO.assignments[(999, _OTHER_CASE_B)] = _authz.CaseAssignmentRecord(role="analyst")
r = client.get("/")
check(
    "T01d analyst (GET /) sees their own active assigned case id",
    _OTHER_CASE_B in r.text,
    f"status={r.status_code}",
)

# --- T01e: global admin sees ZERO case ids, even when also explicitly assigned one ---
_reset_listing_repo()
_LISTING_REPO.admins.add(999)
r = client.get("/")
check(
    "T01e admin (GET /) sees the ORIGINAL default assigned case_id nowhere on the page (unconditional admin veto)",
    case_id not in r.text,
    f"status={r.status_code}",
)
check(
    "T01e (self-check) the admin-veto scenario actually starts from a repository that DOES carry an active assignment "
    "for this user - proving the empty result comes from the admin check, not from an empty repository",
    (999, case_id) in _LISTING_REPO.assignments,
)

# --- T01f: cross-user isolation - a case assigned to a DIFFERENT user_id must never appear in user 999's listing ---
_reset_listing_repo()
_LISTING_REPO.assignments[(888, "case_belongs_to_someone_else")] = _authz.CaseAssignmentRecord(role="lawyer")
r = client.get("/")
check(
    "T01f GET / never renders a case id assigned to a DIFFERENT user_id (cross-user isolation)",
    "case_belongs_to_someone_else" not in r.text,
    f"status={r.status_code}",
)
check("T01f (sanity) the requesting user's own case_id is still listed alongside the isolation check", case_id in r.text)

# --- T01g: a revoked assignment must not appear (simulated by removal, matching InMemoryAuthzRepository's existing convention throughout this test suite / test_authz_isolated.py) ---
_reset_listing_repo()
_LISTING_REPO.assignments[(999, "case_to_be_revoked")] = _authz.CaseAssignmentRecord(role="lawyer")
del _LISTING_REPO.assignments[(999, "case_to_be_revoked")]
r = client.get("/")
check(
    "T01g a revoked (removed) assignment does not appear in GET /'s listing",
    "case_to_be_revoked" not in r.text,
    f"status={r.status_code}",
)

# --- T01h: a stale/nonexistent assigned case (filesystem no longer resolves it) is silently omitted, page still renders 200 with the remaining valid case ids ---
_reset_listing_repo()
_LISTING_REPO.assignments[(999, _LISTING_STALE_MARKER)] = _authz.CaseAssignmentRecord(role="lawyer")
r = client.get("/")
check("T01h a stale/unresolvable assigned case does not crash GET / (still 200)", r.status_code == 200)
check(
    "T01h a stale/unresolvable assigned case_id is silently omitted from the rendered page",
    _LISTING_STALE_MARKER not in r.text,
)
check(
    "T01h the requesting user's other, genuinely resolvable assigned case_id still renders normally "
    "(one stale entry does not blank out the whole listing)",
    case_id in r.text,
)

_reset_listing_repo()  # restore the baseline the rest of this file (T02 onward) already depends on

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
