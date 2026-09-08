# ============================================================
# ROW 19C-2c - İZOLE SAF-PYTHON FACADE TESTLERİ
# (`ui/services/drafting_request_mutation_facade.py`).
#
# Bu dosya FastAPI'YE İHTİYAÇ DUYMAZ ve GERÇEK PostgreSQL'E BAĞLANMAZ -
# `apply_drafting_request_mutation()`'ı GERÇEK `mutation_coordinator.
# run_mutation()` ile, ama FAKE bir journal/lock connection'la çağırır
# (`ui/tests/test_review_mutation_facade_isolated.py` ile AYNI izolasyon
# ilkesi). Gerçek case dizinleri `data/cases/` altında, SENTETİK case_id
# ile oluşturulur ve `finally`'de TAMAMEN silinir - gerçek `case_0001`'e
# veya başka bir gerçek case'e HİÇBİR ŞEY YAZILMAZ; bu, `to_repo_
# relative()`'in overwrite senaryosunda GERÇEK, repo-göreli bir backup
# path'i üretmesi için GEREKLİDİR (bir tempdir-dışı-repo override,
# `to_repo_relative()`'i "(repo dışında bir konum)" placeholder'ına
# düşürür ve backup-binding testlerini anlamsızlaştırırdı).
#
# Çalıştırma:
#   python ui/tests/test_drafting_request_mutation_facade_isolated.py
# ============================================================

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import paths as real_paths                              # noqa: E402
from ui.services import authz as _authz                                  # noqa: E402
from ui.services import mutation_coordinator as mutcoord                 # noqa: E402
from ui.services import drafting_request as dr                           # noqa: E402
from ui.services import drafting_request_mutation_facade as facade       # noqa: E402
from ui.services.common import (                                         # noqa: E402
    DraftingRequestStaleInputError,
    DraftingRequestPreconditionRaceDetectedError,
)

import drafting_policy                                                   # noqa: E402

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
# 0) GERÇEK REPO BYTE-SNAPSHOT (test öncesi/sonrası) + CASE_0001 BYTE-
#    SNAPSHOT (bu dosya HİÇBİR GERÇEK case'e dokunmaz)
# ============================================================

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


_SNAPSHOT_ROOTS = (real_paths.SRC_DIR,)
_CASE_0001_DIR = real_paths.CASES_DIR / "case_0001"
_before_case_0001_snapshot = snapshot_tree(_CASE_0001_DIR)
_before_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)


class _AllowAllAsLawyerRepository(_authz.InMemoryAuthzRepository):
    def get_session_authz_state(self, principal):
        return _authz.SessionRecord(
            user_id=principal.user_id, current_authz_version=principal.role_version_at_issue, disabled=False,
        )

    def get_active_case_assignment(self, user_id, case_id):
        return _authz.CaseAssignmentRecord(role="lawyer")


class _DenyAllRepository(_authz.InMemoryAuthzRepository):
    def get_session_authz_state(self, principal):
        return _authz.SessionRecord(
            user_id=principal.user_id, current_authz_version=principal.role_version_at_issue, disabled=False,
        )

    def get_active_case_assignment(self, user_id, case_id):
        return None


_izole_repo = _AllowAllAsLawyerRepository()
_izole_principal = _authz.Principal(user_id=42, session_id=1, role_version_at_issue=1)

_created_case_dirs = []


def _make_case(case_id):
    case_dir = real_paths.CASES_DIR / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text(json.dumps({"case_id": case_id}), encoding="utf-8")
    _created_case_dirs.append(case_dir)
    return case_dir


def _cleanup_case(case_id):
    case_dir = real_paths.CASES_DIR / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)


_original_resolve_case_id = real_paths.resolve_case_id
_original_list_case_ids = real_paths.list_case_ids
_registered_case_ids = set()
real_paths.resolve_case_id = lambda cid: (
    cid if cid in _registered_case_ids else _original_resolve_case_id(cid)
)
real_paths.list_case_ids = lambda: _original_list_case_ids() + sorted(_registered_case_ids)


def _register_case(case_id):
    _registered_case_ids.add(case_id)


# ============================================================
# ROW 19C-2c PATH CONTAINMENT REMEDIATION - REAL, platform-native
# directory-escape link helpers (never a monkeypatch). An NTFS junction
# via `mklink /J` on Windows needs NEITHER Developer Mode NOR elevation
# (reuses the exact mechanism/pattern already established by
# `ui/tests/test_path_containment_windows.py`); a POSIX symlink
# everywhere else.
# ============================================================


def _make_directory_escape_link(link_path: Path, target_path: Path) -> None:
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"mklink /J failed (rc={result.returncode}): {result.stdout!r} {result.stderr!r}")
    else:
        os.symlink(str(target_path), str(link_path))


def _remove_escape_link(link_path: Path) -> None:
    """Removes a link created by `_make_directory_escape_link()` WITHOUT
    ever recursing into (and deleting) its target - `.rmdir()` for a
    Windows junction (removes only the reparse point, never `.unlink()`
    - see `test_path_containment_windows.py`'s own established
    comment), `.unlink()` for a POSIX symlink."""
    try:
        link_path.unlink()
    except OSError:
        try:
            link_path.rmdir()
        except OSError:
            pass


_EMPTY_LI = {
    "draft_intent_type": None, "appeal_level": None, "selected_issue_ids": None,
    "selected_source_ids": dict(dr._EMPTY_SELECTED_SOURCE_IDS),
    "request_input": None, "lawyer_provided_text": None,
}


def _build_wrapper(case_id, lawyer_provided_text=None, saved_at="2026-01-01T00:00:00+00:00"):
    li = dict(_EMPTY_LI)
    if lawyer_provided_text is not None:
        li["lawyer_provided_text"] = lawyer_provided_text
    normalized = dr.normalize_lawyer_input(li)
    return {
        "schema_version": 1, "case_id": case_id, "saved_at": saved_at,
        "source": "local_lawyer_ui_submission",
        "lawyer_input_hash": dr.compute_lawyer_input_hash(normalized),
        "lawyer_input": normalized,
    }


class _FakeJournalCursor:
    def __init__(self, table):
        self._table = table
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
        raise AssertionError(f"no fake journal row with id={journal_id}")

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())

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
            new_id = len(self._table) + 1
            self._table.append({
                "id": new_id, "resource_key": resource_key, "action_family": action_family,
                "actor_user_id": actor_user_id, "actor_label": actor_label, "target_ref": target_ref,
                "target_state": target_state, "pre_hash": pre_hash, "pre_revision": pre_revision,
                "idempotency_key": idempotency_key, "request_fingerprint": request_fingerprint,
                "state": "prepared", "failure_code": None, "resolution_code": None,
                "executing_at": None, "resolved_at": None, "observed_post_hash": None,
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
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._last_result


class _FakeJournalConn:
    def __init__(self, table=None):
        self.table = table if table is not None else []
        self.closed = False
        self.lock_calls = []

    def cursor(self):
        return _FakeJournalCursor(self.table)

    def close(self):
        self.closed = True


_original_acquire = None
_original_release = None


def _install_lock_fakes():
    from ui.services import mutation_lock as ml
    global _original_acquire, _original_release
    _original_acquire = ml.acquire_case_lock_session
    _original_release = ml.release_lock_session
    ml.acquire_case_lock_session = lambda conn, case_id: 555001
    ml.release_lock_session = lambda conn, advisory_lock_id: True


def _restore_lock_fakes():
    from ui.services import mutation_lock as ml
    ml.acquire_case_lock_session = _original_acquire
    ml.release_lock_session = _original_release


_install_lock_fakes()


def _run(case_id, wrapper, expected_hash, *, repository=None, conn=None, principal=None):
    repo = repository if repository is not None else _izole_repo
    prin = principal if principal is not None else _izole_principal
    outer_resolved = facade.authorize_outer(prin, case_id, repo)
    conn_obj = conn if conn is not None else _FakeJournalConn()
    return facade.apply_drafting_request_mutation(
        outer_resolved, wrapper, expected_hash,
        principal=prin, repository=repo, conn_factory=lambda: conn_obj,
    )


# ============================================================
# 1) FRESH FIRST-SAVE
# ============================================================

CASE_1 = "case_iso_dr_facade_1"
_make_case(CASE_1)
_register_case(CASE_1)

wrapper1 = _build_wrapper(CASE_1, lawyer_provided_text="ilk metin")
result1 = _run(CASE_1, wrapper1, dr.NO_EXISTING_INPUT_SENTINEL)
check("T01 fresh first-save: replayed=False", result1.replayed is False)
check("T02 fresh first-save: journal_id atandı", isinstance(result1.journal_id, int))
check("T03 fresh first-save: current dosya diskte mevcut", dr.get_current_input_path(CASE_1).exists())
check("T04 fresh first-save: audit_path döndü ve GERÇEKTEN var", result1.audit_path is not None and Path(result1.audit_path).exists())
check("T05 fresh first-save: history_backup_path None (ilk kayıt)", result1.history_backup_path is None)

audit_content_1 = json.loads(Path(result1.audit_path).read_text(encoding="utf-8"))
check("T06 audit: mutation_idempotency_key dolu", bool(audit_content_1.get("mutation_idempotency_key")))
check("T07 audit: mutation_resource_key == case:<case_id>", audit_content_1.get("mutation_resource_key") == f"case:{CASE_1}")
check("T08 audit: mutation_actor_ref == str(principal.user_id)", audit_content_1.get("mutation_actor_ref") == str(_izole_principal.user_id))
check("T09 audit: previous_input_token == sentinel (ilk kayıt)", audit_content_1.get("previous_input_token") == dr.NO_EXISTING_INPUT_SENTINEL)

_cleanup_case(CASE_1)
_registered_case_ids.discard(CASE_1)


# ============================================================
# 2) FRESH OVERWRITE
# ============================================================

CASE_2 = "case_iso_dr_facade_2"
_make_case(CASE_2)
_register_case(CASE_2)

wrapper_a = _build_wrapper(CASE_2, lawyer_provided_text="birinci")
result_a = _run(CASE_2, wrapper_a, dr.NO_EXISTING_INPUT_SENTINEL)
token_after_a = dr.compute_current_freshness_token(CASE_2)

wrapper_b = _build_wrapper(CASE_2, lawyer_provided_text="ikinci")
result_b = _run(CASE_2, wrapper_b, token_after_a)

check("T10 overwrite: replayed=False", result_b.replayed is False)
check("T11 overwrite: history_backup_path dolu", result_b.history_backup_path is not None)
check("T12 overwrite: history backup dosyası GERÇEKTEN var", Path(result_b.history_backup_path).exists())
check(
    "T13 overwrite: backup içeriğinin raw hash'i ÖNCEKİ token ile eşleşiyor",
    hashlib.sha256(Path(result_b.history_backup_path).read_bytes()).hexdigest() == token_after_a,
)
audit_content_b = json.loads(Path(result_b.audit_path).read_text(encoding="utf-8"))
check("T14 overwrite audit: action == overwrite", audit_content_b.get("action") == "overwrite")
check(
    "T15 overwrite audit: history_backup_path repo-göreli VE containment altında",
    audit_content_b.get("history_backup_path") is not None
    and (real_paths.BASE_DIR / audit_content_b["history_backup_path"]).resolve() == Path(result_b.history_backup_path).resolve(),
)

_cleanup_case(CASE_2)
_registered_case_ids.discard(CASE_2)


# ============================================================
# 3) SAFE REPLAY (aynı identity + aynı normalize edilmiş içerik)
# ============================================================

CASE_3 = "case_iso_dr_facade_3"
_make_case(CASE_3)
_register_case(CASE_3)

shared_table = []
conn1 = _FakeJournalConn(table=shared_table)
conn2 = _FakeJournalConn(table=shared_table)

wrapper3 = _build_wrapper(CASE_3, lawyer_provided_text="replay testi")
result3a = _run(CASE_3, wrapper3, dr.NO_EXISTING_INPUT_SENTINEL, conn=conn1)
check("T16 replay hazırlığı: fresh mutation replayed=False", result3a.replayed is False)

# AYNI wrapper (AYNI normalize edilmiş içerik, AYNI saved_at dahil - iki
# ayrı wrapper nesnesi ama BİREBİR aynı lawyer_input/lawyer_input_hash),
# AYNI expected_hash (sentinel) - bu, gerçek bir "double-click/retry"
# senaryosudur.
wrapper3_retry = _build_wrapper(CASE_3, lawyer_provided_text="replay testi")
result3b = _run(CASE_3, wrapper3_retry, dr.NO_EXISTING_INPUT_SENTINEL, conn=conn2)

check("T17 replay: replayed=True", result3b.replayed is True)
check("T18 replay: AYNI journal_id", result3b.journal_id == result3a.journal_id)
check("T19 replay: writer YENİDEN ÇAĞRILMADI (audit sayısı hâlâ 1)", len(list(dr.get_input_audit_dir(CASE_3).glob("*.audit.json"))) == 1)
check("T20 replay: reconstructed wrapper GERÇEK dosyayla tutarlı", result3b.wrapper.get("lawyer_input_hash") == wrapper3["lawyer_input_hash"])
check("T21 replay: audit_path aynı tek audit kaydına işaret ediyor", Path(result3b.audit_path).resolve() == Path(result3a.audit_path).resolve())

_cleanup_case(CASE_3)
_registered_case_ids.discard(CASE_3)


# ============================================================
# 4) AYNI IDENTITY + FARKLI İÇERİK -> IdempotencyConflictError
# ============================================================

CASE_4 = "case_iso_dr_facade_4"
_make_case(CASE_4)
_register_case(CASE_4)

# AYNI fake journal table PAYLAŞILIR (gerçek bir veritabanında iki
# çağrı da AYNI mutation.mutation_journal'ı görür) - ikinci çağrının
# `_idempotency_lookup()`'ı BİRİNCİ çağrının satırını GERÇEKTEN
# görebilsin diye. Aksi halde (her çağrı kendi boş fake journal'ıyla)
# coordinator ikinci çağrının aslında BİRİNCİYLE AYNI idempotency_key'e
# sahip olduğunu HİÇ FARK EDEMEZ.
shared_table_4 = []
wrapper4a = _build_wrapper(CASE_4, lawyer_provided_text="metin A")
_run(CASE_4, wrapper4a, dr.NO_EXISTING_INPUT_SENTINEL, conn=_FakeJournalConn(table=shared_table_4))

wrapper4b = _build_wrapper(CASE_4, lawyer_provided_text="metin B (FARKLI içerik)")
expect_raises(
    mutcoord.IdempotencyConflictError,
    lambda: _run(CASE_4, wrapper4b, dr.NO_EXISTING_INPUT_SENTINEL, conn=_FakeJournalConn(table=shared_table_4)),
    "T22 aynı identity + FARKLI içerik -> IdempotencyConflictError",
)
check("T23 conflict: audit sayısı hâlâ 1 (ikinci writer HİÇ ÇAĞRILMADI)", len(list(dr.get_input_audit_dir(CASE_4).glob("*.audit.json"))) == 1)

_cleanup_case(CASE_4)
_registered_case_ids.discard(CASE_4)


# ============================================================
# 5) PLAIN STALE HASH
# ============================================================

CASE_5 = "case_iso_dr_facade_5"
_make_case(CASE_5)
_register_case(CASE_5)

wrapper5 = _build_wrapper(CASE_5, lawyer_provided_text="stale testi")
expect_raises(
    DraftingRequestStaleInputError,
    lambda: _run(CASE_5, wrapper5, "0" * 64),
    "T24 yanlış (stale) expected_hash -> DraftingRequestStaleInputError",
)
check("T25 stale: hiçbir dosya yazılmadı", not dr.get_current_input_path(CASE_5).exists())
check("T26 stale: hiçbir audit dizini oluşmadı", not dr.get_input_audit_dir(CASE_5).exists())

_cleanup_case(CASE_5)
_registered_case_ids.discard(CASE_5)


# ============================================================
# 6) COMPOSITE RACE (precondition_callback İÇİNDE dosya değişir)
# ============================================================

CASE_6 = "case_iso_dr_facade_6"
_make_case(CASE_6)
_register_case(CASE_6)

wrapper6 = _build_wrapper(CASE_6, lawyer_provided_text="race testi")

_original_scan_audit = facade._scan_audit_directory


def _race_injecting_scan_audit(audit_dir):
    # İlk çağrı pre-lock snapshot İÇİNDİR (dokunma); SONRAKİ (under-lock)
    # snapshot'ın KENDİ audit taramasından HEMEN ÖNCE audit dizinine
    # beklenmedik bir dosya enjekte ederek "kilit beklenirken bir şey
    # değişti" senaryosunu GERÇEKTEN üretiyoruz (mock DEĞİL - gerçek
    # dosya sistemi durumu değişiyor, enjeksiyon o TARAMANIN KENDİSİNDEN
    # ÖNCE yapılıyor ki AYNI taramanın SONUCUNA yansısın).
    if _race_injecting_scan_audit.calls == 1:
        Path(audit_dir).mkdir(parents=True, exist_ok=True)
        (Path(audit_dir) / "lawyer_input_save_INJECTED_RACE.audit.json").write_text(
            json.dumps({"mutation_idempotency_key": "not_the_real_one", "case_id": CASE_6}),
            encoding="utf-8",
        )
    _race_injecting_scan_audit.calls += 1
    return _original_scan_audit(audit_dir)


_race_injecting_scan_audit.calls = 0
facade._scan_audit_directory = _race_injecting_scan_audit
try:
    expect_raises(
        DraftingRequestPreconditionRaceDetectedError,
        lambda: _run(CASE_6, wrapper6, dr.NO_EXISTING_INPUT_SENTINEL),
        "T27 composite race (audit dizini kilit beklenirken değişti) -> DraftingRequestPreconditionRaceDetectedError",
    )
finally:
    facade._scan_audit_directory = _original_scan_audit

check(
    "T28 composite race: hâlâ bir StaleInputError ALT SINIFI (mevcut except blokları değişmeden yakalar)",
    issubclass(DraftingRequestPreconditionRaceDetectedError, DraftingRequestStaleInputError),
)
check("T29 composite race: hiçbir current dosya yazılmadı", not dr.get_current_input_path(CASE_6).exists())

_cleanup_case(CASE_6)
_registered_case_ids.discard(CASE_6)


# ============================================================
# 7) ADMISSION GATE: ÖNCEDEN-MEVCUT (orphan) BİR AUDIT, PROPOSED
#    IDEMPOTENCY KEY İLE EŞLEŞİYOR
# ============================================================

CASE_7 = "case_iso_dr_facade_7"
_make_case(CASE_7)
_register_case(CASE_7)

wrapper7 = _build_wrapper(CASE_7, lawyer_provided_text="admission testi")

# Önce GERÇEK bir intent inşa ederek bu TAM isteğin idempotency_key'ini
# önceden hesaplıyoruz (facade'in KENDİSİNİN hesaplayacağı DEĞERLE
# BİREBİR AYNI algoritma - src/mutation_guard.py).
import sys as _sys
_sys.path.insert(0, str(REPO_ROOT / "src")) if str(REPO_ROOT / "src") not in _sys.path else None
from mutation_guard import MutationIntent, compute_idempotency_key  # noqa: E402

resolved_case_7 = facade.authorize_outer(_izole_principal, CASE_7, _izole_repo)
resource_key_7 = f"case:{resolved_case_7}"
probe_intent = MutationIntent(
    actor_type="iam_user", actor_ref=str(_izole_principal.user_id),
    resource_key=resource_key_7, action_family=facade.ACTION_FAMILY,
    target_ref=facade.TARGET_REF, target_state=facade.TARGET_STATE,
    pre_hash="irrelevant_placeholder_not_hashed_into_identity",
    pre_revision=dr.NO_EXISTING_INPUT_SENTINEL,
    secondary_input_hash=wrapper7["lawyer_input_hash"],
)
proposed_key = compute_idempotency_key(probe_intent)

orphan_audit_dir = dr.get_input_audit_dir(CASE_7)
orphan_audit_dir.mkdir(parents=True, exist_ok=True)
(orphan_audit_dir / "lawyer_input_save_ORPHAN.audit.json").write_text(
    json.dumps({"mutation_idempotency_key": proposed_key, "case_id": CASE_7}), encoding="utf-8",
)

expect_raises(
    DraftingRequestPreconditionRaceDetectedError,
    lambda: _run(CASE_7, wrapper7, dr.NO_EXISTING_INPUT_SENTINEL),
    "T30 admission gate: proposed idempotency key ile eşleşen orphan audit -> fail-closed",
)
check("T31 admission gate (orphan): hiçbir current dosya yazılmadı", not dr.get_current_input_path(CASE_7).exists())
check(
    "T32 admission gate (orphan): audit dizininde HÂLÂ yalnız 1 dosya (orphan'ın kendisi - yeni yazılmadı)",
    len(list(orphan_audit_dir.glob("*.audit.json"))) == 1,
)

_cleanup_case(CASE_7)
_registered_case_ids.discard(CASE_7)


# ============================================================
# 8) ADMISSION GATE: BOZUK (corrupt) BİR AUDIT DOSYASI
# ============================================================

CASE_8 = "case_iso_dr_facade_8"
_make_case(CASE_8)
_register_case(CASE_8)

wrapper8 = _build_wrapper(CASE_8, lawyer_provided_text="corrupt testi")
corrupt_audit_dir = dr.get_input_audit_dir(CASE_8)
corrupt_audit_dir.mkdir(parents=True, exist_ok=True)
(corrupt_audit_dir / "lawyer_input_save_CORRUPT.audit.json").write_text("{ bozuk json degil", encoding="utf-8")

expect_raises(
    DraftingRequestPreconditionRaceDetectedError,
    lambda: _run(CASE_8, wrapper8, dr.NO_EXISTING_INPUT_SENTINEL),
    "T33 admission gate: bozuk (corrupt) audit dosyası varlığı TEK BAŞINA fail-closed",
)
check("T34 admission gate (corrupt): hiçbir current dosya yazılmadı", not dr.get_current_input_path(CASE_8).exists())

_cleanup_case(CASE_8)
_registered_case_ids.discard(CASE_8)


# ============================================================
# 9) OUTER AUTHZ DENIAL - SIFIR connection/lock/hash okuması
# ============================================================

CASE_9 = "case_iso_dr_facade_9"
_make_case(CASE_9)
_register_case(CASE_9)

_deny_repo = _DenyAllRepository()
expect_raises(
    _authz.CaseAccessDeniedError,
    lambda: facade.authorize_outer(_izole_principal, CASE_9, _deny_repo),
    "T35 outer authz denial (authorize_outer) -> CaseAccessDeniedError",
)
check("T36 outer authz denial: hiçbir current dosya yazılmadı", not dr.get_current_input_path(CASE_9).exists())
check("T37 outer authz denial: hiçbir audit dizini oluşmadı", not dr.get_input_audit_dir(CASE_9).exists())

_cleanup_case(CASE_9)
_registered_case_ids.discard(CASE_9)


# ============================================================
# 9b) ROW 19C-2c PATH CONTAINMENT REMEDIATION - REAL, platform-native
#     nested directory-escape links (an NTFS junction via `mklink /J`
#     on Windows, a POSIX symlink elsewhere - see
#     _make_directory_escape_link() above; NEVER a monkeypatch - this
#     is a REAL filesystem escape the OS itself resolves). Proves,
#     separately: (a) audit directory escape rejected, (b) history
#     directory escape rejected, (c) current-input PARENT (the
#     `drafting/inputs` directory itself) escape rejected, (d) a
#     correctly-named, valid-JSON file planted OUTSIDE is still never
#     read/accepted merely because it "looks right", (e) a normal,
#     non-escaping case directory continues to work completely
#     unaffected by any of the above.
# ============================================================

CASE_ESC_A = "case_iso_dr_facade_escape_audit"
CASE_ESC_B = "case_iso_dr_facade_escape_history"
CASE_ESC_C = "case_iso_dr_facade_escape_inputs"

_escape_outside_root = Path(tempfile.mkdtemp(prefix="vergi_dr_facade_escape_outside_"))
_escape_links_created = []

try:
    # ---- (a) AUDIT DIRECTORY ESCAPE ----
    _make_case(CASE_ESC_A)
    _register_case(CASE_ESC_A)
    esc_a_case_dir = real_paths.CASES_DIR / CASE_ESC_A
    (esc_a_case_dir / "drafting" / "inputs").mkdir(parents=True)

    esc_a_outside_target = _escape_outside_root / "audit_escape_target"
    esc_a_outside_target.mkdir()
    outside_audit_record = {"mutation_idempotency_key": "outside_key", "case_id": CASE_ESC_A}
    (esc_a_outside_target / "lawyer_input_save_OUTSIDE.audit.json").write_text(
        json.dumps(outside_audit_record), encoding="utf-8",
    )

    esc_a_audit_link = esc_a_case_dir / "drafting" / "inputs" / "audit"
    _make_directory_escape_link(esc_a_audit_link, esc_a_outside_target)
    _escape_links_created.append(esc_a_audit_link)

    wrapper_esc_a = _build_wrapper(CASE_ESC_A, lawyer_provided_text="audit escape testi")
    expect_raises(
        facade.DraftingRequestDirectoryScanError,
        lambda: _run(CASE_ESC_A, wrapper_esc_a, dr.NO_EXISTING_INPUT_SENTINEL),
        "T-ESC-A (a) audit dizininin KENDİSİ CASES_DIR dışına çözümlenen bir junction/symlink ise "
        "-> DraftingRequestDirectoryScanError",
    )
    check(
        "T-ESC-A: escape denemesinden sonra GERÇEK case dizininde hiçbir current dosya yazılmadı",
        not dr.get_current_input_path(CASE_ESC_A).exists(),
    )
    check(
        "T-ESC-A (d): dışarıdaki, doğru adlı VE geçerli JSON içeren audit dosyası test boyunca hiç "
        "OKUNMADI/DEĞİŞTİRİLMEDİ (asla kabul edilmedi)",
        json.loads((esc_a_outside_target / "lawyer_input_save_OUTSIDE.audit.json").read_text(encoding="utf-8"))
        == outside_audit_record,
    )

    # ---- (b) HISTORY DIRECTORY ESCAPE ----
    _make_case(CASE_ESC_B)
    _register_case(CASE_ESC_B)
    esc_b_case_dir = real_paths.CASES_DIR / CASE_ESC_B
    (esc_b_case_dir / "drafting" / "inputs").mkdir(parents=True)

    esc_b_outside_target = _escape_outside_root / "history_escape_target"
    esc_b_outside_target.mkdir()
    (esc_b_outside_target / "lawyer_input_before_save_OUTSIDE.json").write_text(
        "should never be read as a real history backup", encoding="utf-8",
    )

    esc_b_history_link = esc_b_case_dir / "drafting" / "inputs" / "history"
    _make_directory_escape_link(esc_b_history_link, esc_b_outside_target)
    _escape_links_created.append(esc_b_history_link)

    # A first save (never touches history/ as a WRITE target) must
    # still be rejected - the pre-lock composite snapshot scans
    # history/ UNCONDITIONALLY, even for a first save.
    wrapper_esc_b1 = _build_wrapper(CASE_ESC_B, lawyer_provided_text="history escape - ilk kayıt")
    expect_raises(
        facade.DraftingRequestDirectoryScanError,
        lambda: _run(CASE_ESC_B, wrapper_esc_b1, dr.NO_EXISTING_INPUT_SENTINEL),
        "T-ESC-B (b) history dizininin KENDİSİ CASES_DIR dışına çözümlenen bir junction/symlink ise "
        "-> DraftingRequestDirectoryScanError (ilk kayıt denemesi bile - history/ pre-lock "
        "snapshot'ın parçası olarak KOŞULSUZ taranır)",
    )
    check(
        "T-ESC-B: escape denemesinden sonra GERÇEK case dizininde hiçbir current dosya yazılmadı",
        not dr.get_current_input_path(CASE_ESC_B).exists(),
    )
    check(
        "T-ESC-B (d): dışarıdaki, doğru adlı history-backup-şekilli dosya test boyunca hiç "
        "OKUNMADI/DEĞİŞTİRİLMEDİ",
        (esc_b_outside_target / "lawyer_input_before_save_OUTSIDE.json").read_text(encoding="utf-8")
        == "should never be read as a real history backup",
    )

    # ---- (c) CURRENT-INPUT PARENT ESCAPE (the `drafting/inputs`
    #      directory itself, one level ABOVE audit/history) ----
    _make_case(CASE_ESC_C)
    _register_case(CASE_ESC_C)
    esc_c_case_dir = real_paths.CASES_DIR / CASE_ESC_C
    (esc_c_case_dir / "drafting").mkdir(parents=True)

    esc_c_outside_target = _escape_outside_root / "inputs_escape_target"
    esc_c_outside_target.mkdir()
    outside_wrapper = _build_wrapper(CASE_ESC_C, lawyer_provided_text="dışarıdaki sahte current dosya")
    (esc_c_outside_target / "lawyer_input.json").write_text(json.dumps(outside_wrapper), encoding="utf-8")

    esc_c_inputs_link = esc_c_case_dir / "drafting" / "inputs"
    _make_directory_escape_link(esc_c_inputs_link, esc_c_outside_target)
    _escape_links_created.append(esc_c_inputs_link)

    wrapper_esc_c = _build_wrapper(CASE_ESC_C, lawyer_provided_text="inputs escape testi")
    expect_raises(
        facade.DraftingRequestDirectoryScanError,
        lambda: _run(CASE_ESC_C, wrapper_esc_c, dr.NO_EXISTING_INPUT_SENTINEL),
        "T-ESC-C (c) `drafting/inputs`'in KENDİSİ (current dosyanın PARENT'ı) CASES_DIR dışına "
        "çözümlenen bir junction/symlink ise -> DraftingRequestDirectoryScanError",
    )
    check(
        "T-ESC-C (d): dışarıdaki, doğru adlı VE geçerli JSON içeren sahte 'lawyer_input.json' test "
        "boyunca hiç OKUNMADI/DEĞİŞTİRİLMEDİ (asla gerçek current dosya sanılmadı)",
        json.loads((esc_c_outside_target / "lawyer_input.json").read_text(encoding="utf-8")) == outside_wrapper,
    )
finally:
    for link_path in _escape_links_created:
        _remove_escape_link(link_path)
    for esc_case_id in (CASE_ESC_A, CASE_ESC_B, CASE_ESC_C):
        _cleanup_case(esc_case_id)
        _registered_case_ids.discard(esc_case_id)
    shutil.rmtree(_escape_outside_root, ignore_errors=True)

check(
    "T-ESC: escape denemeleri sonrası TÜM sentetik escape-test case dizinleri VE dış hedef "
    "tempdir'i temizlendi",
    not _escape_outside_root.exists()
    and all(not (real_paths.CASES_DIR / cid).exists() for cid in (CASE_ESC_A, CASE_ESC_B, CASE_ESC_C)),
)

# ---- (e) A NORMAL, NON-ESCAPING CASE DIRECTORY CONTINUES TO WORK,
#      completely unaffected by the containment fix above. ----
CASE_ESC_E = "case_iso_dr_facade_escape_normal_control"
_make_case(CASE_ESC_E)
_register_case(CASE_ESC_E)
wrapper_esc_e = _build_wrapper(CASE_ESC_E, lawyer_provided_text="normal case - escape sonrası kontrol")
result_esc_e = _run(CASE_ESC_E, wrapper_esc_e, dr.NO_EXISTING_INPUT_SENTINEL)
check(
    "T-ESC-E (e): normal (escape İÇERMEYEN) bir case dizini, containment düzeltmesinden SONRA da "
    "TAMAMEN normal çalışmaya devam ediyor",
    result_esc_e.replayed is False and dr.get_current_input_path(CASE_ESC_E).exists(),
)
_cleanup_case(CASE_ESC_E)
_registered_case_ids.discard(CASE_ESC_E)


# ============================================================
# 9c) ROW 19C-2c BROKEN-LINK FAIL-CLOSED REMEDIATION - a REAL,
#     platform-native link (junction on Windows, symlink elsewhere -
#     never a monkeypatch) whose TARGET is then removed, leaving a
#     genuine broken reparse-point/symlink entry in place. Proves the
#     `os.path.lexists()` vs `Path.exists()` distinction directly
#     (the exact precondition the prior `.exists()`-only gate got
#     wrong), then proves the facade fails closed BEFORE any writer/
#     journal involvement for (1) a broken audit-directory link and
#     (2) a broken history-directory link. (5) re-confirms a
#     GENUINELY missing (never-created) audit/history directory is
#     still an empty manifest, unaffected by this fix.
# ============================================================

CASE_BROKEN_A = "case_iso_dr_facade_broken_audit"
CASE_BROKEN_B = "case_iso_dr_facade_broken_history"

_broken_outside_root = Path(tempfile.mkdtemp(prefix="vergi_dr_facade_broken_outside_"))
_broken_links_created = []

try:
    # ---- (1) BROKEN AUDIT-DIRECTORY LINK ----
    _make_case(CASE_BROKEN_A)
    _register_case(CASE_BROKEN_A)
    broken_a_case_dir = real_paths.CASES_DIR / CASE_BROKEN_A
    (broken_a_case_dir / "drafting" / "inputs").mkdir(parents=True)

    broken_a_ghost_target = _broken_outside_root / "broken_audit_ghost"
    broken_a_ghost_target.mkdir()

    broken_a_audit_link = broken_a_case_dir / "drafting" / "inputs" / "audit"
    _make_directory_escape_link(broken_a_audit_link, broken_a_ghost_target)
    _broken_links_created.append(broken_a_audit_link)

    # Break it - remove the target the link points to, while the
    # link/junction ENTRY ITSELF remains in place on disk.
    shutil.rmtree(broken_a_ghost_target)

    check(
        "T-BROKEN-A precondition: kırık audit linki os.path.lexists()==True (reparse-point/symlink "
        "girişinin KENDİSİ hâlâ diskte var)",
        os.path.lexists(broken_a_audit_link) is True,
    )
    check(
        "T-BROKEN-A precondition: kırık audit linki Path.exists()==False (target çözülemiyor - bu "
        "AYRIM tam olarak düzeltilen kaynak-kod hatasının kendisidir)",
        broken_a_audit_link.exists() is False,
    )

    wrapper_broken_a = _build_wrapper(CASE_BROKEN_A, lawyer_provided_text="broken audit testi")
    expect_raises(
        facade.DraftingRequestDirectoryScanError,
        lambda: _run(CASE_BROKEN_A, wrapper_broken_a, dr.NO_EXISTING_INPUT_SENTINEL),
        "T-BROKEN-A: KIRIK audit dizini linki (hedefi kaldırılmış) -> DraftingRequestDirectoryScanError "
        "(writer/journal'a HİÇ ULAŞMADAN fail closed)",
    )
    check(
        "T-BROKEN-A: kırık link denemesinden sonra GERÇEK case dizininde hiçbir current dosya yazılmadı",
        not dr.get_current_input_path(CASE_BROKEN_A).exists(),
    )

    # ---- (2) BROKEN HISTORY-DIRECTORY LINK ----
    _make_case(CASE_BROKEN_B)
    _register_case(CASE_BROKEN_B)
    broken_b_case_dir = real_paths.CASES_DIR / CASE_BROKEN_B
    (broken_b_case_dir / "drafting" / "inputs").mkdir(parents=True)

    broken_b_ghost_target = _broken_outside_root / "broken_history_ghost"
    broken_b_ghost_target.mkdir()

    broken_b_history_link = broken_b_case_dir / "drafting" / "inputs" / "history"
    _make_directory_escape_link(broken_b_history_link, broken_b_ghost_target)
    _broken_links_created.append(broken_b_history_link)

    shutil.rmtree(broken_b_ghost_target)

    check(
        "T-BROKEN-B precondition: kırık history linki os.path.lexists()==True",
        os.path.lexists(broken_b_history_link) is True,
    )
    check(
        "T-BROKEN-B precondition: kırık history linki Path.exists()==False",
        broken_b_history_link.exists() is False,
    )

    wrapper_broken_b = _build_wrapper(CASE_BROKEN_B, lawyer_provided_text="broken history testi")
    expect_raises(
        facade.DraftingRequestDirectoryScanError,
        lambda: _run(CASE_BROKEN_B, wrapper_broken_b, dr.NO_EXISTING_INPUT_SENTINEL),
        "T-BROKEN-B: KIRIK history dizini linki (hedefi kaldırılmış) -> "
        "DraftingRequestDirectoryScanError (ilk kayıt denemesi bile - history/ pre-lock snapshot'ın "
        "parçası olarak KOŞULSUZ taranır)",
    )
    check(
        "T-BROKEN-B: kırık link denemesinden sonra GERÇEK case dizininde hiçbir current dosya yazılmadı",
        not dr.get_current_input_path(CASE_BROKEN_B).exists(),
    )
finally:
    for link_path in _broken_links_created:
        _remove_escape_link(link_path)
    for broken_case_id in (CASE_BROKEN_A, CASE_BROKEN_B):
        _cleanup_case(broken_case_id)
        _registered_case_ids.discard(broken_case_id)
    shutil.rmtree(_broken_outside_root, ignore_errors=True)

check(
    "T-BROKEN: kırık-link denemeleri sonrası TÜM sentetik case dizinleri VE dış hedef tempdir'i "
    "temizlendi (link entry'leri kendi dış hedeflerinden AYRI, finally içinde kaldırıldı)",
    not _broken_outside_root.exists()
    and all(not (real_paths.CASES_DIR / cid).exists() for cid in (CASE_BROKEN_A, CASE_BROKEN_B)),
)

# ---- (5) GENUINELY MISSING (never-created) audit/history directories
#      still yield an EMPTY manifest, completely unaffected by this
#      fix - `os.path.lexists()` is False for a segment with NO
#      filesystem entry at all, exactly like `Path.exists()` was. ----
CASE_MISSING_DIRS = "case_iso_dr_facade_missing_dirs_control"
_make_case(CASE_MISSING_DIRS)
_register_case(CASE_MISSING_DIRS)
wrapper_missing = _build_wrapper(CASE_MISSING_DIRS, lawyer_provided_text="missing dirs kontrolü")
result_missing = _run(CASE_MISSING_DIRS, wrapper_missing, dr.NO_EXISTING_INPUT_SENTINEL)
check(
    "T-BROKEN-CONTROL: hiç var olmamış (gerçekten yok) audit/history dizinleri normal ilk kayıtta "
    "hâlâ boş manifest olarak kabul ediliyor (bu düzeltmeden ETKİLENMEDİ)",
    result_missing.replayed is False and dr.get_current_input_path(CASE_MISSING_DIRS).exists(),
)
_cleanup_case(CASE_MISSING_DIRS)
_registered_case_ids.discard(CASE_MISSING_DIRS)


# ============================================================
# 10) secondary_input_hash - compute_lawyer_input_hash TEK KAYNAK
# ============================================================

li_sample = dict(_EMPTY_LI)
li_sample["lawyer_provided_text"] = "hash paritesi testi"
normalized_sample = dr.normalize_lawyer_input(li_sample)
check(
    "T38 secondary_input_hash == drafting_policy.compute_lawyer_input_hash (TEK kaynak, ikinci bir tanım YOK)",
    dr.compute_lawyer_input_hash(normalized_sample) == drafting_policy.compute_lawyer_input_hash(normalized_sample),
)
check(
    "T39 compute_lawyer_input_hash: sha256 hex şekli (64 küçük harf hex) - MutationIntent.secondary_input_hash ile UYUMLU",
    len(dr.compute_lawyer_input_hash(normalized_sample)) == 64
    and all(c in "0123456789abcdef" for c in dr.compute_lawyer_input_hash(normalized_sample)),
)
check(
    "T40 tamamen BOŞ lawyer_input -> compute_lawyer_input_hash None döner (MutationIntent.secondary_input_hash=None GEÇERLİ)",
    dr.compute_lawyer_input_hash(dr.normalize_lawyer_input(dict(_EMPTY_LI))) is None,
)


# ============================================================
# 11) TEMİZLİK + GERÇEK data/ AĞACININ (case_0001 DAHİL) BYTE-DÜZEYİNDE
#     DEĞİŞMEDİĞİNİN KANITI
# ============================================================

_restore_lock_fakes()
real_paths.resolve_case_id = _original_resolve_case_id
real_paths.list_case_ids = _original_list_case_ids

for leftover in list(_created_case_dirs):
    if leftover.exists():
        shutil.rmtree(leftover)

_after_case_0001_snapshot = snapshot_tree(_CASE_0001_DIR)
check("T41 GERÇEK case_0001 ağacı bu test dosyasıyla DEĞİŞMEDİ (byte-düzeyinde)", _before_case_0001_snapshot == _after_case_0001_snapshot)

_after_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)
check(
    "T42 GERÇEK src/ ağacı bu test dosyasıyla DEĞİŞMEDİ (byte-düzeyinde)",
    _before_snapshot == _after_snapshot,
    f"fark={set(_before_snapshot) ^ set(_after_snapshot)}",
)
check(
    "T43 test tarafından oluşturulan TÜM sentetik case dizinleri temizlendi",
    all(not (real_paths.CASES_DIR / cid).exists() for cid in (
        CASE_1, CASE_2, CASE_3, CASE_4, CASE_5, CASE_6, CASE_7, CASE_8, CASE_9,
    )),
)


print()
print(f"--- test_drafting_request_mutation_facade_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
