# ============================================================
# T2 - BÜRO AKIŞI ONAY KAPISI: İZOLE (sahte journal bağlantısı, sahte aile
# modülleri) testleri - ui/services/mutation_approval_facade.py.
#
# GERÇEK OLANLAR: `approve_case_scoped_mutation()` (değiştirilmeden, uçtan
# uca), `ui.services.authz.authorize_case_access()` + `ui.services.paths.
# resolve_case_id()` (gerçek, geçici bir vaka ağacına karşı), kilitli
# `src.path_containment` primitive'i, `ui.services.mutation_coordinator.
# run_mutation()`, işareti yazan GERÇEK `office_flow_records.create_owned_dir`.
#
# SAHTE OLANLAR: `mutation.mutation_journal` (bellek içi tablo - kilitli
# `test_mutation_approval_facade_isolated.py`'nin kendi FakeJournalCursor'ının
# bağımsız bir KOPYASI; o dosya DEĞİŞTİRİLMEDİ), oturum kilidi
# (acquire/release), 10 aile modülü (her `row_key` - `deadline` DAHİL - sahte
# bir modüle eşlenir; gerçek `src/deadline_approval.py` PG testinde koşar).
#
# VERİ: yalnız kurgusal. Vaka ağacı bu testin kendi geçici dizinindedir;
# `ui.services.paths.CASES_DIR` geçici olarak oraya yönlendirilir ve `finally`
# içinde geri alınır. Deponun `data/` ağacına HİÇ yazılmaz (sonda bayt-bayt
# kanıtlanır).
#
# Kapsam (T2 kapsam paketi §5): G1-G10, G5b, G6, G6b + akış dışı ek
# kanıtlar (sıra casusu, varlık-körlüğü, web rotası).
#
# Çalıştırma: python -m ui.tests.test_office_approval_gate_isolated
# ============================================================

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import authz as _authz                                  # noqa: E402
from ui.services import mutation_approval_facade as facade                # noqa: E402
from ui.services import mutation_lock as ml                                # noqa: E402
from ui.services import office_flow_outcomes as outcomes                   # noqa: E402
from ui.services import office_flow_records as records                     # noqa: E402
from ui.services import paths as _paths                                    # noqa: E402
from ui.services.common import (                                           # noqa: E402
    ApprovalUiError,
    PreconditionRaceDetectedError,
    StaleViewError,
)
import ui.cli_mutate as cli_mutate                                         # noqa: E402

passed = 0
failed = 0
skipped = 0
MODULE_NAME = "test_office_approval_gate_isolated"


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def skip(label, detail=""):
    global skipped
    skipped += 1
    print(f"SKIPPED {label} - {detail}")


def summarize_and_exit():
    print(f"--- {MODULE_NAME}: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


# ----------------------------------------------------------------
# Sahte mutation.mutation_journal - kilitli test dosyasındaki
# FakeJournalCursor/FakeJournalConn'un BAĞIMSIZ kopyası (aynı SQL şekilleri).
# ----------------------------------------------------------------

class FakeIntegrityError(Exception):
    pass


class FakeJournalCursor:
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
        raise AssertionError(f"no fake journal row with id={journal_id}")

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
            if any(r["idempotency_key"] == idempotency_key for r in self._table):
                raise FakeIntegrityError(f"duplicate idempotency_key={idempotency_key!r}")
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


class FakeJournalConn:
    def __init__(self, table=None):
        self.table = table if table is not None else []
        self.calls = []
        self.closed = False

    def cursor(self):
        return FakeJournalCursor(self.table, self.calls)

    def close(self):
        self.closed = True


# ----------------------------------------------------------------
# Kilit sahteleri.
# ----------------------------------------------------------------

LOCK_CALLS = []
_original_acquire_case = ml.acquire_case_lock_session
_original_release = ml.release_lock_session


def _fake_acquire_case_lock_session(conn, case_id):
    LOCK_CALLS.append(("acquire", case_id))
    return 4242


def _fake_release_lock_session(conn, advisory_lock_id):
    LOCK_CALLS.append(("release", advisory_lock_id))
    return True


# ----------------------------------------------------------------
# Geçici vaka ağacı + sahte aile modülleri.
# ----------------------------------------------------------------

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_t2_gate_iso_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)
_OUTSIDE = _TMP_ROOT / "outside"
_OUTSIDE.mkdir()

_IS_WINDOWS = sys.platform == "win32"
MARKER = records.OWNER_MARKER_NAME


def snapshot_real_data_tree():
    out = {}
    base = REPO_ROOT / "data"
    for path in base.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(base))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(base))] = "<unreadable>"
    return out


_real_data_before = snapshot_real_data_tree()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_fake_module(name, *, promotion_check=None):
    """Kilitli dosyadaki sahte aile modülünün şekli: get_pending_path/
    get_canonical_path/run_approve + CASES_DIR (geçici ağaca bağlı)."""
    mod = types.ModuleType(name)
    mod.CASES_DIR = _TMP_CASES
    run_approve_calls = []

    def get_pending_path(case_id):
        return _TMP_CASES / case_id / "pending.json"

    def get_canonical_path(case_id):
        return _TMP_CASES / case_id / "canonical.json"

    def run_approve(case_id, *, mutation_idempotency_key=None, mutation_resource_key=None):
        run_approve_calls.append((case_id, mutation_idempotency_key, mutation_resource_key))
        pending_path = get_pending_path(case_id)
        canonical_path = get_canonical_path(case_id)
        canonical_path.write_text(pending_path.read_text(encoding="utf-8"), encoding="utf-8")
        reviews_dir = canonical_path.parent / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        audit = {
            "mutation_idempotency_key": mutation_idempotency_key,
            "mutation_resource_key": mutation_resource_key,
            "canonical_sha256": sha256_text(canonical_path.read_text(encoding="utf-8")),
            "pending_sha256": sha256_text(pending_path.read_text(encoding="utf-8")),
            "case_id": case_id,
        }
        (reviews_dir / f"fake_{uuid.uuid4().hex}.approval.json").write_text(json.dumps(audit), encoding="utf-8")
        print(f"approved {case_id}")

    mod.get_pending_path = get_pending_path
    mod.get_canonical_path = get_canonical_path
    mod.run_approve = run_approve
    mod.run_approve_calls = run_approve_calls
    if promotion_check is not None:
        mod.check_pending_promotion_contract = promotion_check
    return mod


ALL_ROW_KEYS = list(facade.ROW_KEY_TO_MODULE_NAME)
OTHER_ROW_KEYS = [k for k in ALL_ROW_KEYS if k != "deadline"]
FAKE_MODS = {}
_original_row_key_mapping = dict(facade.ROW_KEY_TO_MODULE_NAME)


def install_fake_families():
    mapping = {}
    for key in ALL_ROW_KEYS:
        name = f"_t2_gate_fake_{key}"
        mod = make_fake_module(name)
        sys.modules[name] = mod
        FAKE_MODS[key] = mod
        mapping[key] = name
    facade.ROW_KEY_TO_MODULE_NAME = mapping


def make_case(*, marker_run_id=None, pending='{"x": 1}'):
    """`marker_run_id` verilirse vaka dizini ÜRETİMİN KENDİ yazıcısıyla
    (`records.create_owned_dir`, kind="case_dir") açılır - işaret baytları
    akışınkiyle birebir aynıdır."""
    case_id = f"t2gate{uuid.uuid4().hex[:10]}"
    case_dir = _TMP_CASES / case_id
    if marker_run_id is not None:
        records.create_owned_dir(case_dir, run_id=marker_run_id, kind="case_dir")
    else:
        case_dir.mkdir()
    (case_dir / "case.json").write_text("{}", encoding="utf-8")
    pending_path = case_dir / "pending.json"
    pending_path.write_text(pending, encoding="utf-8")
    return case_id, case_dir, pending_path, sha256_text(pending)


def make_principal_and_repo(case_id, *, assigned=True):
    principal = _authz.Principal(user_id=1, session_id=100, role_version_at_issue=1)
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[100] = _authz.SessionRecord(user_id=1, current_authz_version=1, disabled=False)
    if assigned:
        repo.assignments[(1, case_id)] = _authz.CaseAssignmentRecord(role="lawyer")
    return principal, repo


def valid_marker_bytes(run_id):
    return records.canonical_bytes({"kayit_surumu": records.RECORD_SCHEMA_VERSION, "kos": run_id, "tur": "case_dir"})


def write_marker(case_dir, data: bytes):
    target = case_dir / MARKER
    if os.path.lexists(target):
        if target.is_dir() and not target.is_symlink():
            target.rmdir()
        else:
            target.unlink()
    target.write_bytes(data)


def make_junction(link_path: Path, target_path: Path) -> bool:
    if not _IS_WINDOWS:
        return False
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True, text=True, timeout=15,
    )
    return result.returncode == 0


_NOPARAM = object()


class Outcome:
    def __init__(self, result, error, conn, factory_calls, writer_calls):
        self.result, self.error, self.conn = result, error, conn
        self.factory_calls, self.writer_calls = factory_calls, writer_calls


def approve(row_key, case_id, expected_hash, *, run_id=_NOPARAM, conn=None, on_open=None,
            principal=None, repo=None):
    if principal is None or repo is None:
        principal, repo = make_principal_and_repo(case_id)
    conn = conn if conn is not None else FakeJournalConn()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if on_open is not None:
            on_open()
        return conn

    kwargs = {}
    if run_id is not _NOPARAM:
        kwargs["office_flow_run_id"] = run_id
    mod = FAKE_MODS[row_key]
    before = len(mod.run_approve_calls)
    try:
        result = facade.approve_case_scoped_mutation(
            row_key, case_id, expected_hash, principal=principal, authz_repository=repo,
            conn_factory=factory, **kwargs,
        )
        error = None
    except Exception as exc:  # noqa: BLE001
        result, error = None, exc
    return Outcome(result, error, conn, calls["n"], len(mod.run_approve_calls) - before)


ERRORS_SEEN = []   # G6b: her ret örneği burada toplanır.


def is_gate_reject(out):
    if isinstance(out.error, facade.OfficeFlowApprovalRequiredError):
        ERRORS_SEEN.append(out.error)
        return True
    return False


def zero_effect(out, case_dir, pending_before):
    """Ret sözleşmesi: sıfır journal satırı (prepared dahil), yazıcı yok,
    canonical/reviews yok, pending baytları aynı."""
    return (
        out.conn.table == [] and out.writer_calls == 0
        and not (case_dir / "canonical.json").exists() and not (case_dir / "reviews").exists()
        and (case_dir / "pending.json").read_bytes() == pending_before
    )


# ----------------------------------------------------------------
# Casuslar: işaret okuma sayacı + işaretle ilgili os/containment çağrı sırası.
# ----------------------------------------------------------------

READ_CALLS = {"n": 0}
_original_read_marker = facade._read_office_flow_marker


def _counting_read_marker(case_root_real):
    READ_CALLS["n"] += 1
    return _original_read_marker(case_root_real)


EVENTS = []
_real_os = facade.os
_real_containment = facade._path_containment


class _OsSpy:
    """facade.os yerine konur: işaret yolu üzerindeki lstat/stat/open/fstat/
    read çağrılarını sırasıyla kaydeder, sonra gerçeğine devreder."""

    def __getattr__(self, name):
        real = getattr(_real_os, name)
        if name in ("lstat", "stat", "open"):
            def wrapper(path, *args, **kwargs):
                if os.fspath(path).endswith(MARKER):
                    EVENTS.append(name)
                return real(path, *args, **kwargs)
            return wrapper
        if name in ("fstat", "read"):
            def wrapper2(*args, **kwargs):
                EVENTS.append(name)
                return real(*args, **kwargs)
            return wrapper2
        return real


class _ContainmentSpy:
    def __getattr__(self, name):
        real = getattr(_real_containment, name)
        if name in ("resolve_for_create", "resolve_existing"):
            def wrapper(*args, **kwargs):
                if any(isinstance(a, (str, os.PathLike)) and os.fspath(a).endswith(MARKER) for a in args):
                    EVENTS.append("contain")
                return real(*args, **kwargs)
            return wrapper
        return real


SHA_CALLS = {"n": 0}
_original_sha256_file = facade.sha256_file


def _counting_sha256_file(path):
    SHA_CALLS["n"] += 1
    return _original_sha256_file(path)


_original_paths_cases_dir = _paths.CASES_DIR
_original_compute_key = facade.compute_idempotency_key

try:
    _paths.CASES_DIR = _TMP_CASES
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.release_lock_session = _fake_release_lock_session
    install_fake_families()
    facade._read_office_flow_marker = _counting_read_marker
    facade.sha256_file = _counting_sha256_file

    # ============================================================
    # G10 - işaret adı/sürümü tek kaynaktan.
    # ============================================================
    check("G10: the facade's marker name IS office_flow_records.OWNER_MARKER_NAME (same object, single source)",
          facade._OFFICE_FLOW_OWNER_MARKER_NAME is records.OWNER_MARKER_NAME and records.OWNER_MARKER_NAME == ".office_flow_owner")
    check("G10: the facade's marker schema version IS office_flow_records.RECORD_SCHEMA_VERSION (== 1)",
          facade._OFFICE_FLOW_RECORD_SCHEMA_VERSION is records.RECORD_SCHEMA_VERSION and records.RECORD_SCHEMA_VERSION == 1)
    _facade_src = Path(facade.__file__).read_text(encoding="utf-8")
    check("G10: the facade source carries NO second literal copy of the marker file name",
          '".office_flow_owner"' not in _facade_src and "'.office_flow_owner'" not in _facade_src)
    check("G10: the gate is scoped to exactly the 'deadline' row key and the 'case_dir' marker kind",
          facade.OFFICE_FLOW_GATED_ROW_KEY == "deadline" and facade.OFFICE_FLOW_MARKER_KIND == "case_dir")

    # ============================================================
    # G9 - hata sınıfı ve üç çağıranın eşlemesi.
    # ============================================================
    _err = facade.OfficeFlowApprovalRequiredError()
    check("G9: OfficeFlowApprovalRequiredError is an ApprovalUiError subclass",
          issubclass(facade.OfficeFlowApprovalRequiredError, ApprovalUiError))
    check("G9: it is NOT a StaleViewError / NestedPathContainmentError (never mistaken for a race or a path failure)",
          not isinstance(_err, StaleViewError) and not isinstance(_err, facade.NestedPathContainmentError))
    check("G9: ui.cli_mutate's known-domain-error classification recognises it (clean ERROR line, no traceback)",
          cli_mutate._is_known_domain_error(_err) is True)
    check("G9: the office flow maps it to the EXISTING closed code ZINCIR_ADIMI_BASARISIZ",
          outcomes.error_code_for(_err) == "ZINCIR_ADIMI_BASARISIZ")
    _err_ctor_args = None
    try:
        facade.OfficeFlowApprovalRequiredError("yol C:\\x kos abc")
    except TypeError:
        _err_ctor_args = "rejected"
    check("G9/G6b: the error class takes NO constructor argument (no caller can smuggle a path/id into its text)",
          _err_ctor_args == "rejected")

    # ============================================================
    # G1 - işaret yok, parametre yok -> bugünkü davranış (yazıcıya ulaşır).
    # ============================================================
    cid, cdir, ppath, eh = make_case()
    READ_CALLS["n"] = 0
    out = approve("deadline", cid, eh)
    check("G1: unmarked case, no office_flow_run_id -> approved exactly as today (writer once, one 'completed' row)",
          out.error is None and out.writer_calls == 1 and len(out.conn.table) == 1
          and out.conn.table[0]["state"] == "completed" and out.result.replayed is False, repr(out.error))
    check("G1: the marker WAS consulted for the deadline family (pre-lock + under-lock = 2 reads)", READ_CALLS["n"] == 2,
          str(READ_CALLS["n"]))

    # ============================================================
    # G2 - geçerli işaret, parametre yok -> KİLİT ÖNCESİ ret.
    # ============================================================
    RID = uuid.uuid4().hex
    cid2, cdir2, ppath2, eh2 = make_case(marker_run_id=RID)
    pend2 = ppath2.read_bytes()
    LOCK_CALLS.clear()
    SHA_CALLS["n"] = 0
    out2 = approve("deadline", cid2, eh2)
    check("G2: valid office-flow marker + NO office_flow_run_id -> OfficeFlowApprovalRequiredError",
          is_gate_reject(out2), repr(out2.error))
    check("G2: rejected BEFORE the lock: ZERO conn_factory() calls, ZERO lock calls, ZERO pre-state hash reads",
          out2.factory_calls == 0 and LOCK_CALLS == [] and SHA_CALLS["n"] == 0,
          f"factory={out2.factory_calls} lock={LOCK_CALLS} sha={SHA_CALLS['n']}")
    check("G2: zero journal rows, writer never called, no canonical/reviews, pending bytes unchanged",
          zero_effect(out2, cdir2, pend2))

    # ============================================================
    # G3 - parametre var, farklı koşu kimliği -> ret (kilit öncesi).
    # ============================================================
    out3 = approve("deadline", cid2, eh2, run_id=uuid.uuid4().hex)
    check("G3: valid marker + a DIFFERENT run id -> OfficeFlowApprovalRequiredError, pre-lock (zero conn_factory calls)",
          is_gate_reject(out3) and out3.factory_calls == 0, repr(out3.error))
    check("G3: zero effect", zero_effect(out3, cdir2, pend2))
    out3b = approve("deadline", cid2, eh2, run_id=RID.upper())
    check("G3: a case-variant of the right run id is a DIFFERENT run id (exact comparison) -> rejected",
          is_gate_reject(out3b) and out3b.factory_calls == 0 and zero_effect(out3b, cdir2, pend2), repr(out3b.error))
    out3c = approve("deadline", cid2, eh2, run_id=b"x" if False else 12345)
    check("G3: a non-string office_flow_run_id never matches -> rejected", is_gate_reject(out3c) and zero_effect(out3c, cdir2, pend2))

    # ============================================================
    # G4 - koşu kimliği eşleşiyor -> yazıcıya ulaşır.
    # ============================================================
    conn4 = FakeJournalConn()
    out4 = approve("deadline", cid2, eh2, run_id=RID, conn=conn4)
    check("G4: valid marker + MATCHING office_flow_run_id -> approved (writer once, one 'completed' row, canonical written)",
          out4.error is None and out4.writer_calls == 1 and len(conn4.table) == 1 and conn4.table[0]["state"] == "completed"
          and (cdir2 / "canonical.json").read_bytes() == pend2, repr(out4.error))
    check("G4: the marker itself is untouched by the approval (bytes == the production writer's own bytes)",
          (cdir2 / MARKER).read_bytes() == valid_marker_bytes(RID))

    # ---- tekrar (replay) yalnız kilit öncesi aşamada yakalanır ----
    out4r = approve("deadline", cid2, eh2, conn=conn4)
    check("G4-replay: after the flow's approval, a NO-parameter call with the SAME expected hash (would be a safe replay) "
          "-> rejected PRE-LOCK (zero conn_factory calls), journal still exactly 1 row, writer not called again",
          is_gate_reject(out4r) and out4r.factory_calls == 0 and len(conn4.table) == 1 and out4r.writer_calls == 0,
          repr(out4r.error))
    out4rr = approve("deadline", cid2, eh2, run_id=RID, conn=conn4)
    check("G4-replay: the flow's OWN replay (matching run id) is still a normal safe replay (replayed=True, no new row)",
          out4rr.error is None and out4rr.result.replayed is True and len(conn4.table) == 1 and out4rr.writer_calls == 0,
          repr(out4rr.error))

    # ============================================================
    # G5 - bozuk işaretler (koşu kimliği verilmiş olsa bile) -> ret.
    # ============================================================
    R5 = uuid.uuid4().hex
    v = records.RECORD_SCHEMA_VERSION
    bad_markers = [
        ("invalid JSON", b"{bozuk"),
        ("empty file", b""),
        ("wrong tur (run_dir)", records.canonical_bytes({"kayit_surumu": v, "kos": R5, "tur": "run_dir"})),
        ("wrong version (2)", records.canonical_bytes({"kayit_surumu": 2, "kos": R5, "tur": "case_dir"})),
        ("version is JSON true (True == 1 trap)", ('{"kayit_surumu": true, "kos": "%s", "tur": "case_dir"}' % R5).encode()),
        ("version is the string '1'", records.canonical_bytes({"kayit_surumu": "1", "kos": R5, "tur": "case_dir"})),
        ("version is the float 1.0", ('{"kayit_surumu": 1.0, "kos": "%s", "tur": "case_dir"}' % R5).encode()),
        ("missing kos", records.canonical_bytes({"kayit_surumu": v, "tur": "case_dir"})),
        ("extra key", records.canonical_bytes({"kayit_surumu": v, "kos": R5, "tur": "case_dir", "x": 1})),
        ("kos is not a string", records.canonical_bytes({"kayit_surumu": v, "kos": 5, "tur": "case_dir"})),
        ("duplicate key", ('{"kayit_surumu": 1, "kos": "%s", "kos": "%s", "tur": "case_dir"}' % (R5, R5)).encode()),
        ("JSON array", json.dumps([v, R5, "case_dir"]).encode()),
        ("invalid UTF-8", b"\xff\xfe" + valid_marker_bytes(R5)),
        ("UTF-8 BOM prefix", b"\xef\xbb\xbf" + valid_marker_bytes(R5)),
        ("oversize (> 4096 bytes, otherwise valid)", valid_marker_bytes(R5)[:-2] + b" " * 5000 + b"}\n"),
    ]
    for label, data in bad_markers:
        c5, d5, p5, h5 = make_case()
        write_marker(d5, data)
        before5 = p5.read_bytes()
        o5 = approve("deadline", c5, h5, run_id=R5)
        check(f"G5: marker {label} + office_flow_run_id given -> rejected PRE-LOCK, zero effect",
              is_gate_reject(o5) and o5.factory_calls == 0 and zero_effect(o5, d5, before5), repr(o5.error))
        o5n = approve("deadline", c5, h5)
        check(f"G5: marker {label} + NO office_flow_run_id -> ALSO rejected pre-lock (an invalid entry is 'marker "
              "present', never 'absent'), zero effect",
              is_gate_reject(o5n) and o5n.factory_calls == 0 and zero_effect(o5n, d5, before5), repr(o5n.error))

    # empty kos + empty param: an empty run id never validates.
    c5e, d5e, p5e, h5e = make_case()
    write_marker(d5e, records.canonical_bytes({"kayit_surumu": v, "kos": "", "tur": "case_dir"}))
    o5e = approve("deadline", c5e, h5e, run_id="")
    check("G5: marker with an EMPTY kos + an empty office_flow_run_id -> rejected (blank run id never valid)",
          is_gate_reject(o5e) and o5e.factory_calls == 0 and zero_effect(o5e, d5e, p5e.read_bytes()))

    # same-name DIRECTORY (with and without the parameter).
    c5d, d5d, p5d, h5d = make_case()
    (d5d / MARKER).mkdir()
    for label, kw in (("with", {"run_id": R5}), ("without", {})):
        o5d = approve("deadline", c5d, h5d, **kw)
        check(f"G5: a DIRECTORY named {MARKER} ({label} office_flow_run_id) counts as 'marker present' -> rejected pre-lock",
              is_gate_reject(o5d) and o5d.factory_calls == 0 and zero_effect(o5d, d5d, p5d.read_bytes()), repr(o5d.error))

    # hard link: a regular file whose content lives elsewhere (st_nlink > 1) -> not the flow's own marker.
    c5h, d5h, p5h, h5h = make_case()
    _hl_src = _OUTSIDE / f"hardlink_src_{uuid.uuid4().hex[:6]}.json"
    _hl_src.write_bytes(valid_marker_bytes(R5))
    try:
        os.link(_hl_src, d5h / MARKER)
        _hl_ok = True
    except OSError as _hl_error:
        _hl_ok = False
        skip("G5: hard-linked marker (st_nlink > 1)", f"os.link not permitted here ({type(_hl_error).__name__}). NOT EXECUTED, not a pass")
    if _hl_ok:
        o5h = approve("deadline", c5h, h5h, run_id=R5)
        check("G5: a HARD-LINKED marker (valid content, but st_nlink > 1 - content shared with a file outside the case) -> rejected",
              is_gate_reject(o5h) and o5h.factory_calls == 0 and zero_effect(o5h, d5h, p5h.read_bytes()), repr(o5h.error))

    # Windows NTFS junctions (escaping, in-tree alias, broken).
    junction_cases = []
    if _IS_WINDOWS:
        cjo, djo, pjo, hjo = make_case()
        out_target = _OUTSIDE / f"jtarget_{uuid.uuid4().hex[:6]}"
        out_target.mkdir()
        cji, dji, pji, hji = make_case()
        (dji / "inner_dir").mkdir()
        cjb, djb, pjb, hjb = make_case()
        broken_target = _OUTSIDE / f"jgone_{uuid.uuid4().hex[:6]}"
        broken_target.mkdir()
        ok_o = make_junction(djo / MARKER, out_target)
        ok_i = make_junction(dji / MARKER, dji / "inner_dir")
        ok_b = make_junction(djb / MARKER, broken_target)
        if ok_b:
            broken_target.rmdir()
        for label, ok, c, d, p, h in (("escaping the case root", ok_o, cjo, djo, pjo, hjo),
                                      ("aliasing an in-case directory", ok_i, cji, dji, pji, hji),
                                      ("BROKEN (target removed)", ok_b, cjb, djb, pjb, hjb)):
            if not ok:
                skip(f"G5: NTFS junction marker {label}", "mklink /J failed in this environment. NOT EXECUTED, not a pass")
                continue
            for plabel, kw in (("with", {"run_id": R5}), ("without", {})):
                oj = approve("deadline", c, h, **kw)
                check(f"G5: NTFS junction marker {label} ({plabel} office_flow_run_id) -> rejected PRE-LOCK with "
                      "OfficeFlowApprovalRequiredError (a link is 'marker present'; never followed), zero effect",
                      is_gate_reject(oj) and oj.factory_calls == 0 and zero_effect(oj, d, p.read_bytes()), repr(oj.error))
            junction_cases.append(label)
    else:
        skip("G5: NTFS junction markers", "not Windows. NOT EXECUTED, not a pass")

    # file symlinks (need SeCreateSymbolicLinkPrivilege / Developer Mode on Windows).
    for label, target_maker in (
        ("to a VALID marker file elsewhere INSIDE the case", "inside"),
        ("to a VALID marker file OUTSIDE the case root", "outside"),
    ):
        cs, ds, ps, hs = make_case()
        if target_maker == "inside":
            tgt = ds / "valid_marker_copy.json"
        else:
            tgt = _OUTSIDE / f"valid_marker_{uuid.uuid4().hex[:6]}.json"
        tgt.write_bytes(valid_marker_bytes(R5))
        try:
            os.symlink(tgt, ds / MARKER)
            sym_ok = True
        except (OSError, NotImplementedError) as sym_error:
            sym_ok = False
            skip(f"G5: file-symlink marker {label}",
                 f"os.symlink not permitted here ({type(sym_error).__name__}). NOT EXECUTED, not a pass")
        if sym_ok:
            os_ = approve("deadline", cs, hs, run_id=R5)
            check(f"G5: file-symlink marker {label} (valid content) -> rejected PRE-LOCK (link is never accepted)",
                  is_gate_reject(os_) and os_.factory_calls == 0 and zero_effect(os_, ds, ps.read_bytes()), repr(os_.error))

    # ============================================================
    # G5b - parametre var ama işaret yok -> ret.
    # ============================================================
    c5b, d5b, p5b, h5b = make_case()
    o5b = approve("deadline", c5b, h5b, run_id=uuid.uuid4().hex)
    check("G5b: NO marker + office_flow_run_id given -> rejected pre-lock (protection never left to the flow's own pre-check)",
          is_gate_reject(o5b) and o5b.factory_calls == 0 and zero_effect(o5b, d5b, p5b.read_bytes()), repr(o5b.error))

    # ============================================================
    # G6 - kilit öncesi ile kilit altı arasında işaret oluşur/değişir ->
    # KİLİT ALTINDA ret, sıfır prepared.
    # ============================================================
    c6a, d6a, p6a, h6a = make_case()
    LOCK_CALLS.clear()
    o6a = approve("deadline", c6a, h6a,
                  on_open=lambda: records.write_new_file(d6a / MARKER, valid_marker_bytes(uuid.uuid4().hex)))
    check("G6(a): no marker pre-lock (passes), a valid marker APPEARS while the request waits for the lock -> "
          "rejected UNDER the lock (conn_factory reached once, lock acquired AND released)",
          is_gate_reject(o6a) and o6a.factory_calls == 1 and ("acquire", c6a) in LOCK_CALLS and ("release", 4242) in LOCK_CALLS,
          f"{o6a.error!r} {LOCK_CALLS}")
    check("G6(a): ZERO journal rows (no 'prepared'), writer never called, no canonical, pending unchanged",
          zero_effect(o6a, d6a, p6a.read_bytes()))

    R6 = uuid.uuid4().hex
    c6b, d6b, p6b, h6b = make_case(marker_run_id=R6)
    o6b = approve("deadline", c6b, h6b, run_id=R6,
                  on_open=lambda: write_marker(d6b, valid_marker_bytes(uuid.uuid4().hex)))
    check("G6(b): matching marker pre-lock, marker REWRITTEN to another run while waiting -> rejected under the lock, zero effect",
          is_gate_reject(o6b) and o6b.factory_calls == 1 and zero_effect(o6b, d6b, p6b.read_bytes()), repr(o6b.error))

    c6c, d6c, p6c, h6c = make_case(marker_run_id=R6)
    o6c = approve("deadline", c6c, h6c, run_id=R6, on_open=lambda: (d6c / MARKER).unlink())
    check("G6(c): matching marker pre-lock, marker DELETED while waiting -> rejected under the lock (G5b under lock), zero effect",
          is_gate_reject(o6c) and o6c.factory_calls == 1 and zero_effect(o6c, d6c, p6c.read_bytes()), repr(o6c.error))

    if _IS_WINDOWS:
        c6d, d6d, p6d, h6d = make_case(marker_run_id=R6)
        j_target = _OUTSIDE / f"j6_{uuid.uuid4().hex[:6]}"
        j_target.mkdir()
        (j_target / MARKER).write_bytes(valid_marker_bytes(R6))
        _j6 = {"ok": None}

        def _swap_to_junction():
            (d6d / MARKER).unlink()
            _j6["ok"] = make_junction(d6d / MARKER, j_target)

        o6d = approve("deadline", c6d, h6d, run_id=R6, on_open=_swap_to_junction)
        if _j6["ok"]:
            check("G6(d): matching marker pre-lock, swapped for an escaping NTFS junction while waiting -> rejected under the lock, zero effect",
                  is_gate_reject(o6d) and o6d.factory_calls == 1 and zero_effect(o6d, d6d, p6d.read_bytes()), repr(o6d.error))
        else:
            skip("G6(d): junction swap under the lock", "mklink /J failed in this environment. NOT EXECUTED, not a pass")
    else:
        skip("G6(d): junction swap under the lock", "not Windows. NOT EXECUTED, not a pass")

    # sıra: yarış kontrolü ÖNCE gelir (gerçek bir yarış kendi hatasıyla görünür).
    c6e, d6e, p6e, h6e = make_case()

    def _race_and_marker():
        (d6e / "pending.json").write_text('{"x": 2}', encoding="utf-8")
        records.write_new_file(d6e / MARKER, valid_marker_bytes(uuid.uuid4().hex))

    o6e = approve("deadline", c6e, h6e, on_open=_race_and_marker)
    check("G6(e) ORDER: pending changed AND marker appeared while waiting -> the EXISTING race error wins "
          "(PreconditionRaceDetectedError), i.e. the gate runs AFTER the race/stale checks; zero journal rows, writer not called",
          isinstance(o6e.error, PreconditionRaceDetectedError) and o6e.conn.table == [] and o6e.writer_calls == 0, repr(o6e.error))

    # sıra: iç (otoriter) yetki denetimi ÖNCE gelir.
    c6f, d6f, p6f, h6f = make_case()
    pr6f, repo6f = make_principal_and_repo(c6f)

    def _revoke_and_marker():
        repo6f.assignments.pop((1, c6f), None)
        records.write_new_file(d6f / MARKER, valid_marker_bytes(uuid.uuid4().hex))

    o6f = approve("deadline", c6f, h6f, on_open=_revoke_and_marker, principal=pr6f, repo=repo6f)
    check("G6(f) ORDER: assignment revoked AND marker appeared while waiting -> CaseAccessDeniedError from the INNER authz "
          "(the gate never runs before the authoritative authz); zero journal rows",
          isinstance(o6f.error, _authz.CaseAccessDeniedError) and o6f.conn.table == [] and o6f.writer_calls == 0, repr(o6f.error))

    # sıra: check_pending_promotion_contract ÖNCE ve aynen çalışır.
    class _PromotionRefused(ApprovalUiError):
        pass

    _promo_calls = []

    def _promo(pending_path, case_id):
        _promo_calls.append(case_id)
        raise _PromotionRefused("legacy pending")

    _promo_mod = make_fake_module("_t2_gate_fake_deadline_promo", promotion_check=_promo)
    sys.modules["_t2_gate_fake_deadline_promo"] = _promo_mod
    _saved_deadline_mod = FAKE_MODS["deadline"]
    facade.ROW_KEY_TO_MODULE_NAME["deadline"] = "_t2_gate_fake_deadline_promo"
    FAKE_MODS["deadline"] = _promo_mod
    try:
        c6g, d6g, p6g, h6g = make_case()
        o6g = approve("deadline", c6g, h6g,
                      on_open=lambda: records.write_new_file(d6g / MARKER, valid_marker_bytes(uuid.uuid4().hex)))
        check("G6(g) ORDER: check_pending_promotion_contract still runs (once) and its refusal surfaces BEFORE the T2 gate; zero rows",
              isinstance(o6g.error, _PromotionRefused) and _promo_calls == [c6g] and o6g.conn.table == [], repr(o6g.error))
    finally:
        facade.ROW_KEY_TO_MODULE_NAME["deadline"] = "_t2_gate_fake_deadline"
        FAKE_MODS["deadline"] = _saved_deadline_mod

    # ============================================================
    # Sıra casusu: containment -> lstat -> open -> fstat -> read; iki aşama.
    # ============================================================
    R7 = uuid.uuid4().hex
    c7, d7, p7, h7 = make_case(marker_run_id=R7)
    EVENTS.clear()
    facade.os = _OsSpy()
    facade._path_containment = _ContainmentSpy()
    try:
        o7 = approve("deadline", c7, h7, run_id=R7)
    finally:
        facade.os = _real_os
        facade._path_containment = _real_containment
    marker_events = list(EVENTS)
    check("ORDER spy: a matched approval read the marker in EXACTLY two stages (pre-lock + under-lock): "
          "two containment calls, two lstat, two open",
          o7.error is None and marker_events.count("contain") == 2 and marker_events.count("lstat") == 2
          and marker_events.count("open") == 2, f"{o7.error!r} {marker_events}")
    # Her aşama bir "contain" olayıyla başlar; aşamalar ona göre bölünür.
    _starts = [i for i, e in enumerate(marker_events) if e == "contain"]
    _stages = [marker_events[s:(_starts[k + 1] if k + 1 < len(_starts) else len(marker_events))]
               for k, s in enumerate(_starts)]
    _stage_ok = len(_stages) == 2 and bool(marker_events) and marker_events[0] == "contain"
    for _st in _stages:
        try:
            if not (_st[0] == "contain" and _st.index("lstat") < _st.index("open") < _st.index("fstat") < _st.index("read")):
                _stage_ok = False
        except ValueError:
            _stage_ok = False
    check("ORDER spy (Row 19C-3a Slice 2 safe-scan contract): in EACH stage containment verification precedes the "
          "first lstat, which precedes open -> fstat -> read; no stat() on the marker at all",
          _stage_ok and "stat" not in marker_events, str(marker_events))

    # ============================================================
    # G7 - işaretli vakada diğer 9 aile: davranış aynı, işaret HİÇ okunmaz.
    # ============================================================
    R8 = uuid.uuid4().hex
    for key in OTHER_ROW_KEYS:
        for variant in ("valid marker, no parameter", "same-name DIRECTORY marker, no parameter",
                        "valid marker, an arbitrary office_flow_run_id"):
            cg, dg, pg, hg = make_case(marker_run_id=R8 if variant.startswith("valid") else None)
            if variant.startswith("same-name"):
                (dg / MARKER).mkdir()
            READ_CALLS["n"] = 0
            EVENTS.clear()
            facade.os = _OsSpy()
            facade._path_containment = _ContainmentSpy()
            try:
                og = approve(key, cg, hg, **({"run_id": uuid.uuid4().hex} if "arbitrary" in variant else {}))
            finally:
                facade.os = _real_os
                facade._path_containment = _real_containment
            check(f"G7 [{key}] {variant}: approved exactly as today (writer once, one 'completed' row) and the "
                  "marker was NEVER read (zero reads, zero marker containment/lstat/open calls)",
                  og.error is None and og.writer_calls == 1 and len(og.conn.table) == 1 and og.conn.table[0]["state"] == "completed"
                  and READ_CALLS["n"] == 0 and EVENTS == [], f"{og.error!r} reads={READ_CALLS['n']} events={EVENTS}")
    check("G7: all 9 non-deadline families were covered", len(OTHER_ROW_KEYS) == 9, str(OTHER_ROW_KEYS))

    # ============================================================
    # G8 - office_flow_run_id idempotency anahtarını değiştirmez.
    # ============================================================
    INTENTS = []

    def _capturing_key(intent):
        key = _original_compute_key(intent)
        INTENTS.append((intent, key))
        return key

    facade.compute_idempotency_key = _capturing_key
    try:
        R9 = uuid.uuid4().hex
        c9, d9, p9, h9 = make_case(marker_run_id=R9)
        conn9 = FakeJournalConn()
        o9a = approve("deadline", c9, h9, run_id=R9, conn=conn9)
        (d9 / MARKER).unlink()   # işaret kalkınca parametresiz çağrı kapıdan geçer
        o9b = approve("deadline", c9, h9, conn=conn9)
    finally:
        facade.compute_idempotency_key = _original_compute_key
    import dataclasses as _dc
    # `pre_hash` is recorded filesystem EVIDENCE, deliberately NOT identity (Row 19C-2a): it legitimately differs
    # here (canonical now exists). Every OTHER intent field must be identical, and so must the key.
    _ident = [_dc.replace(i, pre_hash="<evidence>") for i, _k in INTENTS]
    check("G8: with vs without office_flow_run_id the SAME request computes the IDENTICAL MutationIntent identity "
          "(all fields except the evidence-only pre_hash) and the IDENTICAL idempotency key",
          o9a.error is None and o9b.error is None and len(INTENTS) == 2
          and _ident[0] == _ident[1] and INTENTS[0][1] == INTENTS[1][1], f"{o9a.error!r} {o9b.error!r} n={len(INTENTS)}")
    check("G8: ... so the second call is a SAFE REPLAY of the first (replayed=True, still 1 journal row, writer once in total)",
          o9b.error is None and o9b.result.replayed is True and len(conn9.table) == 1
          and o9a.writer_calls == 1 and o9b.writer_calls == 0)
    check("G8: the run id appears in NO MutationIntent field and NOT in the journal row",
          all(R9 not in repr(i) for i, _k in INTENTS) and R9 not in repr(conn9.table))

    # ============================================================
    # Varlık-körlüğü: yetkisiz çağıran kapıya hiç ulaşmaz.
    # ============================================================
    R10 = uuid.uuid4().hex
    c10, d10, p10, h10 = make_case(marker_run_id=R10)
    pr10, repo10 = make_principal_and_repo(c10, assigned=False)
    READ_CALLS["n"] = 0
    o10 = approve("deadline", c10, h10, principal=pr10, repo=repo10)
    check("existence-blindness: an UNASSIGNED caller on a marked case gets the generic CaseAccessDeniedError, "
          "the marker is never read, zero conn_factory calls",
          isinstance(o10.error, _authz.CaseAccessDeniedError) and READ_CALLS["n"] == 0 and o10.factory_calls == 0, repr(o10.error))
    pr11, repo11 = make_principal_and_repo("t2gate_no_such_case")
    o11 = approve("deadline", "t2gate_no_such_case", "0" * 64, principal=pr11, repo=repo11)
    check("existence-blindness: a nonexistent case id gets the SAME CaseAccessDeniedError, the marker code is never reached",
          isinstance(o11.error, _authz.CaseAccessDeniedError) and READ_CALLS["n"] == 0)

    # ============================================================
    # G6b - ret metni sabit: yol, koşu kimliği, vaka kimliği YOK.
    # ============================================================
    _tmp_s = str(_TMP_ROOT)
    _bad = []
    for e in ERRORS_SEEN:
        text = str(e)
        if (text != facade.OFFICE_FLOW_APPROVAL_REQUIRED_MESSAGE or e.args != (facade.OFFICE_FLOW_APPROVAL_REQUIRED_MESSAGE,)
                or "t2gate" in text or _tmp_s in text or MARKER in text or "\\" in text or "/" in text
                or any(r in text for r in (RID, R5, R6, R7, R8, R9))
                or e.__cause__ is not None or e.__suppress_context__ is not True):
            _bad.append(repr(e))
    check(f"G6b: EVERY one of the {len(ERRORS_SEEN)} rejections carried exactly the fixed text - no path, no run id, "
          "no case id, no marker name, no chained cause",
          len(ERRORS_SEEN) >= 20 and _bad == [], f"n={len(ERRORS_SEEN)} bad={_bad[:3]}")

    # ============================================================
    # T2-GATE-DUZELTME-1 (bağımsız inceleme L-1, L-2, L-3, L-5): YALNIZ EK
    # kontroller. Bu blok BİLEREK G6b'den SONRA durur: G6b etiketi o ana
    # kadarki ret sayısını içerir; buradaki retler o etiketi değiştirmez.
    # Her casus YALNIZ bu bloğun kendi vakasının işaret yolunu etkiler; öteki
    # her yol/ad gerçek nesneye gider. Yetki (symlink/Developer Mode/ACL)
    # gerekmez; yalnız bu modülün geçici ağacı kullanılır.
    # ============================================================
    import pathlib as _pathlib_mod
    import stat as _stat_mod

    def _real_root(case_dir):
        return Path(os.path.realpath(case_dir))

    def _is_this_marker(path, case_id):
        p = Path(os.fspath(path))
        return p.name == MARKER and p.parent.name == case_id

    # ---- L-1: "okunamayan giriş = işaret var" (lstat / os.open PermissionError) ----
    class _RaisingMarkerOs:
        """facade.os yerine: YALNIZ verilen vakanın işaret yolundaki `op`
        çağrısı PermissionError fırlatır; öteki her yol ve ad gerçek os'a gider."""

        def __init__(self, op, case_ids):
            self._op = op
            self._case_ids = tuple(case_ids)
            self.raised = 0

        def __getattr__(self, name):
            real = getattr(_real_os, name)
            if name == self._op:
                def wrapper(path, *args, **kwargs):
                    if any(_is_this_marker(path, c) for c in self._case_ids):
                        self.raised += 1
                        raise PermissionError(13, "simulated access denied (T2 L-1 test)", os.fspath(path))
                    return real(path, *args, **kwargs)
                return wrapper
            return real

    for _tag, _op in (("L-1a", "lstat"), ("L-1b", "open")):
        _rid = uuid.uuid4().hex
        # Her çağrı KENDİ taze vakasında: bir çağrının (mutantta) kabulü ötekinin sıfır-etki ölçümüne karışmaz.
        _cid, _cdir, _ppath, _eh = make_case(marker_run_id=_rid)
        _pend = _ppath.read_bytes()
        _cidn, _cdirn, _ppathn, _ehn = make_case(marker_run_id=_rid)
        _pendn = _ppathn.read_bytes()
        _ctl_cid, _ctl_dir, _ctl_p, _ctl_eh = make_case()
        _spy = _RaisingMarkerOs(_op, (_cid, _cidn))
        facade.os = _spy
        try:
            _o_with = approve("deadline", _cid, _eh, run_id=_rid)
            _o_without = approve("deadline", _cidn, _ehn)
            _state = _original_read_marker(_real_root(_cdir))
            _o_ctl = approve("deadline", _ctl_cid, _ctl_eh)
        finally:
            facade.os = _real_os
        check(f"{_tag}: a VALID marker whose os.{_op}() raises PermissionError (unreadable entry) + MATCHING "
              "office_flow_run_id -> rejected PRE-LOCK, zero effect",
              is_gate_reject(_o_with) and _o_with.factory_calls == 0 and zero_effect(_o_with, _cdir, _pend),
              f"{_o_with.error!r} factory={_o_with.factory_calls} writer={_o_with.writer_calls}")
        check(f"{_tag}: the same unreadable marker (os.{_op}() PermissionError) + NO office_flow_run_id -> ALSO "
              "rejected pre-lock (an unreadable entry is 'marker present', NEVER 'absent'), zero effect",
              is_gate_reject(_o_without) and _o_without.factory_calls == 0 and zero_effect(_o_without, _cdirn, _pendn),
              f"{_o_without.error!r} factory={_o_without.factory_calls} writer={_o_without.writer_calls}")
        check(f"{_tag}: the reader itself classifies the unreadable entry as INVALID (never ABSENT); the spy really "
              "raised on the marker path and the marker bytes are untouched",
              _state == (facade._MARKER_INVALID, None) and _spy.raised >= 3
              and (_cdir / MARKER).read_bytes() == valid_marker_bytes(_rid),
              f"state={_state} raised={_spy.raised}")
        check(f"{_tag}: the spy affects ONLY that one marker path - under the same spy a no-parameter approval of an "
              "UNMARKED case is approved exactly as today (writer once, one 'completed' row)",
              _o_ctl.error is None and _o_ctl.writer_calls == 1 and len(_o_ctl.conn.table) == 1
              and _o_ctl.conn.table[0]["state"] == "completed", repr(_o_ctl.error))
        check(f"{_tag}: facade.os was restored to the real os module", facade.os is _real_os)

    # ---- L-2: takma ad - containment işaret adını kök içi BAŞKA bir düzenli dosyaya çözer ----
    class _AliasContainment:
        """facade._path_containment yerine: YALNIZ bu vakanın işaret adı için
        gerçek doğrulama yine koşar, ama kök içindeki başka bir düzenli, tek
        bağlantılı, geçerli içerikli dosyanın yolu döner (bir dosya
        symlink'inin çözülmüş sonucunu taklit eder). Öteki her çağrı gerçektir."""

        def __init__(self, alias_targets):
            self._alias_targets = dict(alias_targets)   # case_id -> kök içi takma ad hedefi
            self.aliased = 0

        def __getattr__(self, name):
            real = getattr(_real_containment, name)
            if name == "resolve_for_create":
                def wrapper(root, *parts, **kwargs):
                    case_id = Path(os.fspath(root)).name
                    if parts == (MARKER,) and case_id in self._alias_targets:
                        real(root, *parts, **kwargs)
                        self.aliased += 1
                        return self._alias_targets[case_id]
                    return real(root, *parts, **kwargs)
                return wrapper
            return real

    _rid2 = uuid.uuid4().hex
    # Her çağrı KENDİ taze vakasında (bkz. L-1).
    _cid2, _cdir2, _ppath2, _eh2 = make_case()
    _pend2 = _ppath2.read_bytes()
    _cid2n, _cdir2n, _ppath2n, _eh2n = make_case()
    _pend2n = _ppath2n.read_bytes()
    _alias_target = _real_root(_cdir2) / "valid_marker_alias.json"
    _alias_target.write_bytes(valid_marker_bytes(_rid2))
    _alias_target_n = _real_root(_cdir2n) / "valid_marker_alias.json"
    _alias_target_n.write_bytes(valid_marker_bytes(_rid2))
    _alias_st = os.lstat(_alias_target)
    _alias = _AliasContainment({_cid2: _alias_target, _cid2n: _alias_target_n})
    facade._path_containment = _alias
    try:
        _o2_with = approve("deadline", _cid2, _eh2, run_id=_rid2)
        _aliased_with = _alias.aliased
        _o2_without = approve("deadline", _cid2n, _eh2n)
        _state2 = _original_read_marker(_real_root(_cdir2))
    finally:
        facade._path_containment = _real_containment
    check("L-2: the alias target is an in-root, REGULAR, single-link file with VALID content for the run id "
          "(so only the alias check can reject it)",
          _stat_mod.S_ISREG(_alias_st.st_mode) and _alias_st.st_nlink == 1
          and _alias_target.parent == _real_root(_cdir2) and _alias_target.read_bytes() == valid_marker_bytes(_rid2))
    check("L-2: containment resolves the marker name to a DIFFERENT in-root regular file with valid content (what a "
          "file symlink would resolve to) + MATCHING office_flow_run_id -> rejected PRE-LOCK, zero effect",
          _aliased_with >= 1 and is_gate_reject(_o2_with) and _o2_with.factory_calls == 0
          and zero_effect(_o2_with, _cdir2, _pend2),
          f"{_o2_with.error!r} aliased={_aliased_with} factory={_o2_with.factory_calls} writer={_o2_with.writer_calls}")
    check("L-2: the same alias + NO office_flow_run_id -> also rejected pre-lock, zero effect",
          is_gate_reject(_o2_without) and _o2_without.factory_calls == 0 and zero_effect(_o2_without, _cdir2n, _pend2n),
          repr(_o2_without.error))
    check("L-2: the reader itself classifies the aliased marker as INVALID", _state2 == (facade._MARKER_INVALID, None),
          str(_state2))
    check("L-2: the containment patch was undone in `finally` (facade._path_containment is the real module again)",
          facade._path_containment is _real_containment)

    # ---- L-3a: lstat ile open ARASINDA aynı içerikli YENİ düzenli dosyayla takas ----
    class _SwapAfterLstatOs:
        """facade.os yerine: bu vakanın işaretindeki İLK gerçek lstat sonucu
        alındıktan HEMEN SONRA girişi takas eder (bir kez); öteki her şey gerçek."""

        def __init__(self, case_id, swap):
            self._case_id = case_id
            self._swap = swap
            self.swapped = False

        def __getattr__(self, name):
            real = getattr(_real_os, name)
            if name == "lstat":
                def wrapper(path, *args, **kwargs):
                    result = real(path, *args, **kwargs)
                    if not self.swapped and _is_this_marker(path, self._case_id):
                        self.swapped = True
                        self._swap(Path(os.fspath(path)))
                    return result
                return wrapper
            return real

    _rid3 = uuid.uuid4().hex
    _cid3, _cdir3, _ppath3, _eh3 = make_case(marker_run_id=_rid3)
    _pend3 = _ppath3.read_bytes()
    _replacement = _cdir3 / "marker_replacement.json"
    _replacement.write_bytes(valid_marker_bytes(_rid3))      # önceden VAR: kimliği eskisinden kesin farklı
    _before3 = os.lstat(_cdir3 / MARKER)
    _swapper = _SwapAfterLstatOs(_cid3, lambda marker: os.replace(_replacement, marker))
    facade.os = _swapper
    try:
        _o3 = approve("deadline", _cid3, _eh3, run_id=_rid3)
    finally:
        facade.os = _real_os
    _after3 = os.lstat(_cdir3 / MARKER)
    check("L-3a: the swap really happened between lstat and open: the marker is now a DIFFERENT regular, single-link "
          "file (nonzero, different (st_dev, st_ino)) with the SAME valid bytes",
          _swapper.swapped and _before3.st_ino != 0 and _after3.st_ino != 0
          and (_before3.st_dev, _before3.st_ino) != (_after3.st_dev, _after3.st_ino)
          and _stat_mod.S_ISREG(_after3.st_mode) and _after3.st_nlink == 1
          and (_cdir3 / MARKER).read_bytes() == valid_marker_bytes(_rid3) and not _replacement.exists(),
          f"swapped={_swapper.swapped} before={(_before3.st_dev, _before3.st_ino)} after={(_after3.st_dev, _after3.st_ino)}")
    check("L-3a: marker swapped between lstat and open for a NEW regular file with the same valid content + MATCHING "
          "office_flow_run_id -> rejected PRE-LOCK ((st_dev, st_ino) of lstat != fstat), zero effect",
          is_gate_reject(_o3) and _o3.factory_calls == 0 and zero_effect(_o3, _cdir3, _pend3),
          f"{_o3.error!r} factory={_o3.factory_calls} writer={_o3.writer_calls}")
    check("L-3a: facade.os was restored to the real os module", facade.os is _real_os)

    # ---- L-3b: lstat düzenli dosya + reparse bayrağı döndürür ----
    _REPARSE_FLAG = getattr(_stat_mod, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

    class _ReparseStat:
        """Gerçek lstat sonucunu sarar; YALNIZ st_file_attributes'a reparse
        bayrağını ekler. st_mode/st_nlink/st_size/st_dev/st_ino GERÇEKTİR."""

        def __init__(self, real_result):
            self._real = real_result

        def __getattr__(self, name):
            return getattr(self._real, name)

        @property
        def st_file_attributes(self):
            return getattr(self._real, "st_file_attributes", 0) | _REPARSE_FLAG

    class _ReparseLstatOs:
        def __init__(self, case_id):
            self._case_id = case_id
            self.wrapped = []

        def __getattr__(self, name):
            real = getattr(_real_os, name)
            if name == "lstat":
                def wrapper(path, *args, **kwargs):
                    result = real(path, *args, **kwargs)
                    if _is_this_marker(path, self._case_id):
                        result = _ReparseStat(result)
                        self.wrapped.append(result)
                    return result
                return wrapper
            return real

    _rid4 = uuid.uuid4().hex
    _cid4, _cdir4, _ppath4, _eh4 = make_case(marker_run_id=_rid4)
    _pend4 = _ppath4.read_bytes()
    _reparse_spy = _ReparseLstatOs(_cid4)
    facade.os = _reparse_spy
    try:
        _o4 = approve("deadline", _cid4, _eh4, run_id=_rid4)
    finally:
        facade.os = _real_os
    _w4 = _reparse_spy.wrapped[0] if _reparse_spy.wrapped else None
    _real4 = os.lstat(_cdir4 / MARKER)
    check("L-3b: the spy's lstat result is a REGULAR, single-link file whose identity/size are the REAL ones and whose "
          "ONLY change is the reparse-point attribute",
          _w4 is not None and _stat_mod.S_ISREG(_w4.st_mode) and _w4.st_nlink == 1
          and (_w4.st_dev, _w4.st_ino, _w4.st_size) == (_real4.st_dev, _real4.st_ino, _real4.st_size)
          and bool(_w4.st_file_attributes & _REPARSE_FLAG)
          and not (getattr(_real4, "st_file_attributes", 0) & _REPARSE_FLAG),
          f"wrapped={len(_reparse_spy.wrapped)}")
    check("L-3b: lstat reports a regular file carrying the reparse-point attribute + MATCHING office_flow_run_id -> "
          "rejected PRE-LOCK, zero effect",
          is_gate_reject(_o4) and _o4.factory_calls == 0 and zero_effect(_o4, _cdir4, _pend4),
          f"{_o4.error!r} factory={_o4.factory_calls} writer={_o4.writer_calls}")
    check("L-3b: facade.os was restored to the real os module", facade.os is _real_os)

    # ---- L-5: EK sıra kontrolü - pathlib.Path sondaları da kayda alınır ----
    PROBE_EVENTS = []
    _PATHLIB_PROBES = ("is_file", "exists", "stat", "lstat", "open", "read_bytes", "read_text")
    _pathlib_saved = []
    for _pn in _PATHLIB_PROBES:
        _owner = next(c for c in type(_pathlib_mod.Path(".")).__mro__ if _pn in c.__dict__)
        _pathlib_saved.append((_owner, _pn, _owner.__dict__[_pn]))

    def _pathlib_probe(pname, orig):
        def wrapper(self, *args, **kwargs):
            if self.name == MARKER:
                PROBE_EVENTS.append("pathlib." + pname)
            return orig(self, *args, **kwargs)
        return wrapper

    class _ProbeOsSpy:
        def __getattr__(self, name):
            real = getattr(_real_os, name)
            if name in ("lstat", "stat", "open"):
                def wrapper(path, *args, **kwargs):
                    if os.fspath(path).endswith(MARKER):
                        PROBE_EVENTS.append("os." + name)
                    return real(path, *args, **kwargs)
                return wrapper
            return real

    class _ProbeContainmentSpy:
        def __getattr__(self, name):
            real = getattr(_real_containment, name)
            if name in ("resolve_for_create", "resolve_existing"):
                def wrapper(*args, **kwargs):
                    hit = any(isinstance(a, (str, os.PathLike)) and os.fspath(a).endswith(MARKER) for a in args)
                    if hit:
                        PROBE_EVENTS.append("contain_start")
                    try:
                        return real(*args, **kwargs)
                    finally:
                        if hit:
                            PROBE_EVENTS.append("contain_end")
                return wrapper
            return real

    _reader_before_l5 = facade._read_office_flow_marker

    def _reader_with_bounds(case_root_real):
        PROBE_EVENTS.append("reader_enter")
        try:
            return _reader_before_l5(case_root_real)
        finally:
            PROBE_EVENTS.append("reader_exit")

    _rid5 = uuid.uuid4().hex
    _cid5, _cdir5, _ppath5, _eh5 = make_case(marker_run_id=_rid5)
    _positive = []
    try:
        for _owner, _pn, _orig in _pathlib_saved:
            setattr(_owner, _pn, _pathlib_probe(_pn, _orig))
        facade.os = _ProbeOsSpy()
        facade._path_containment = _ProbeContainmentSpy()
        facade._read_office_flow_marker = _reader_with_bounds
        _o5 = approve("deadline", _cid5, _eh5, run_id=_rid5)
        _trace5 = list(PROBE_EVENTS)
        PROBE_EVENTS.clear()
        (_cdir5 / MARKER).is_file()          # pozitif kontrol: casus pathlib sondasını görebiliyor mu
        _positive = list(PROBE_EVENTS)
    finally:
        facade._read_office_flow_marker = _reader_before_l5
        facade._path_containment = _real_containment
        facade.os = _real_os
        for _owner, _pn, _orig in _pathlib_saved:
            setattr(_owner, _pn, _orig)
    check("L-5: positive control - the new pathlib spy DOES record a Path.is_file() call on the marker path (an empty "
          "pathlib trace below is therefore meaningful)", _positive == ["pathlib.is_file"], str(_positive))
    _stages5 = []
    _violations5 = []
    _in_reader = False
    _contained = False
    for _e in _trace5:
        if _e == "reader_enter":
            _in_reader, _contained = True, False
            _stages5.append([])
        elif _e == "reader_exit":
            _in_reader, _contained = False, False
        elif _e == "contain_start":
            if _in_reader:
                _contained = True
                _stages5[-1].append(_e)
        elif _e.startswith("pathlib.") or _e.startswith("os."):
            if not _contained:
                _violations5.append(_e)
            if _in_reader:
                _stages5[-1].append(_e)
    check("L-5: a matched approval entered the marker reader in EXACTLY two stages (pre-lock + under-lock) and each "
          "stage called containment on the marker",
          _o5.error is None and len(_stages5) == 2 and all("contain_start" in s for s in _stages5),
          f"{_o5.error!r} trace={_trace5}")
    check("L-5 ORDER (Row 19C-3a Slice 2, pathlib-inclusive): in EACH stage NO probe on the marker path - neither via "
          "facade.os (lstat/stat/open) nor via pathlib.Path (is_file/exists/stat/lstat/open/read_bytes/read_text) - "
          "happens before that stage's containment call STARTS",
          _o5.error is None and _violations5 == [] and len(_stages5) == 2, f"violations={_violations5} trace={_trace5}")
    check("L-5: the pathlib methods, facade.os, facade._path_containment and the marker-reader wrapper were all restored",
          all(_owner.__dict__[_pn] is _orig for _owner, _pn, _orig in _pathlib_saved)
          and facade.os is _real_os and facade._path_containment is _real_containment
          and facade._read_office_flow_marker is _counting_read_marker)

    # ============================================================
    # WEB - POST onay rotası (ui/main.py değiştirilmeden): işaretli vakada
    # APPROVAL_FAILED genel sayfası, yazıcı/bağlantı yok; işaretsiz kontrol.
    # ============================================================
    try:
        import fastapi  # noqa: F401
        from fastapi.testclient import TestClient
        _fastapi_ok = True
    except ModuleNotFoundError:
        _fastapi_ok = False
    if not _fastapi_ok:
        skip("WEB: POST approval route on a marked case", "fastapi is not installed in this interpreter. NOT EXECUTED, not a pass")
    else:
        import ui.main as main_module
        from ui.services import security as _security

        _W_SECRET = b"t2-gate-test-only-fixed-csrf-secret"
        _w_principal = _authz.Principal(user_id=1, session_id=100, role_version_at_issue=1)
        _w_repo = _authz.InMemoryAuthzRepository()
        _w_repo.sessions[100] = _authz.SessionRecord(user_id=1, current_authz_version=1, disabled=False)
        _saved_main = {n: getattr(main_module, n) for n in ("require_principal_and_case", "csrf_secret_for_request")}
        _saved_facade = {n: getattr(facade, n) for n in ("_default_authz_repository", "_default_conn_factory")}
        _w_conn_calls = {"n": 0}
        _w_conn = FakeJournalConn()

        def _w_conn_factory():
            _w_conn_calls["n"] += 1
            return _w_conn

        # ui/main.py's `_error_page` logs the real exception locally (by design); keep this test's stderr quiet.
        _w_logger = getattr(main_module, "logger", None)
        _w_logger_prev = getattr(_w_logger, "disabled", None)
        try:
            if _w_logger is not None:
                _w_logger.disabled = True
            main_module.require_principal_and_case = lambda request, case_id, capability: (
                _w_principal, _authz.authorize_case_access(_w_principal, case_id, capability, repository=_w_repo))
            main_module.csrf_secret_for_request = lambda request, principal: _W_SECRET
            facade._default_authz_repository = lambda: (_w_repo, lambda: None)
            facade._default_conn_factory = _w_conn_factory
            client = TestClient(main_module.app, client=("127.0.0.1", 12345))

            RW = uuid.uuid4().hex
            cw, dw, pw, hw = make_case(marker_run_id=RW)
            _w_repo.assignments[(1, cw)] = _authz.CaseAssignmentRecord(role="lawyer")
            before_w = pw.read_bytes()
            writer_before = len(FAKE_MODS["deadline"].run_approve_calls)
            token = _security.make_csrf_token(_W_SECRET, cw, "deadline", hw)
            resp = client.post(f"/cases/{cw}/approvals/deadline/confirm", data={"expected_hash": hw, "csrf_token": token})
            body = resp.text
            check("WEB: marked case -> the EXISTING generic APPROVAL_FAILED error page (HTTP 200), via ui/main.py's unchanged "
                  "`except ApprovalUiError` branch",
                  resp.status_code == 200 and main_module._ERROR_MESSAGES["APPROVAL_FAILED"] in body, f"status={resp.status_code}")
            check("WEB: the page leaks neither the run id, the case path, nor the facade's own message; no journal "
                  "connection was opened and the writer was never called",
                  RW not in body and _tmp_s not in body and facade.OFFICE_FLOW_APPROVAL_REQUIRED_MESSAGE not in body
                  and _w_conn_calls["n"] == 0 and len(FAKE_MODS["deadline"].run_approve_calls) == writer_before
                  and pw.read_bytes() == before_w and not (dw / "canonical.json").exists())

            cw2, dw2, pw2, hw2 = make_case()
            _w_repo.assignments[(1, cw2)] = _authz.CaseAssignmentRecord(role="lawyer")
            token2 = _security.make_csrf_token(_W_SECRET, cw2, "deadline", hw2)
            resp2 = client.post(f"/cases/{cw2}/approvals/deadline/confirm", data={"expected_hash": hw2, "csrf_token": token2})
            check("WEB control: the SAME route on an UNMARKED case still approves (writer once, canonical written, "
                  "no APPROVAL_FAILED page) - only the marker made the difference",
                  resp2.status_code == 200 and main_module._ERROR_MESSAGES["APPROVAL_FAILED"] not in resp2.text
                  and len(FAKE_MODS["deadline"].run_approve_calls) == writer_before + 1 and (dw2 / "canonical.json").exists(),
                  f"status={resp2.status_code}")
        finally:
            if _w_logger is not None:
                _w_logger.disabled = _w_logger_prev
            for n, val in _saved_main.items():
                setattr(main_module, n, val)
            for n, val in _saved_facade.items():
                setattr(facade, n, val)

finally:
    facade.os = _real_os
    facade._path_containment = _real_containment
    facade._read_office_flow_marker = _original_read_marker
    facade.sha256_file = _original_sha256_file
    facade.compute_idempotency_key = _original_compute_key
    facade.ROW_KEY_TO_MODULE_NAME = _original_row_key_mapping
    ml.acquire_case_lock_session = _original_acquire_case
    ml.release_lock_session = _original_release
    _paths.CASES_DIR = _original_paths_cases_dir
    for _name in list(sys.modules):
        if _name.startswith("_t2_gate_fake_"):
            del sys.modules[_name]
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

check("cleanup: every monkeypatch was restored (facade mapping, os, containment, lock, CASES_DIR)",
      facade.ROW_KEY_TO_MODULE_NAME == _original_row_key_mapping and facade.os is _real_os
      and facade._path_containment is _real_containment and ml.acquire_case_lock_session is _original_acquire_case
      and _paths.CASES_DIR == _original_paths_cases_dir and facade._read_office_flow_marker is _original_read_marker)
check("cleanup: this test's temp tree was removed", not _TMP_ROOT.exists())
check("this repository's REAL data/ tree is byte-for-byte UNCHANGED by this module", snapshot_real_data_tree() == _real_data_before)

summarize_and_exit()
