# ============================================================
# ADIM 10 B YOLU - ui/services/manual_fact_mutation_facade.py VE
# ui/services/manual_fact_mutation_adapters.py ISOLATED TESTS
# (exact-scope §5.2: F-P1, F-P2, F-N1..F-N13; ayrıca N-M1 çöküş
# matrisi, N-L3 replay corroboration, N-L4 M-09 journal durumu, N-L7
# writer-hata mesajı).
#
# Sahte journal bağlantısı (run_mutation()'ın kullandığı EXACT SQL
# şekilleri), sahte kilitler, bellek-içi authz; GERÇEK motor/validator,
# gerçek `data/cases/` altında yeniden kimliklendirilmiş sentetik
# case_0001 kopyaları (finally ile silinir; tüm data/ ağacı önce/sonra
# bayt-bayt karşılaştırılır). Windows'ta kaçış senaryoları GERÇEK
# `mklink /J` junction'larıdır (tek Python-dışı alt süreç).
#
# Run: python ui/tests/test_manual_fact_mutation_facade_isolated.py
# ============================================================

import ast
import hashlib
import json
import os
import shutil
import socket
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
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

passed = 0
failed = 0
_informational_skips = 0

_IS_WINDOWS = sys.platform == "win32"


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def skip_info(label, detail=""):
    global _informational_skips
    _informational_skips += 1
    print(f"SKIPPED (NOT counted as pass/fail) {label} - {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type as error:
        check(label, True)
        return error
    except Exception as error:  # noqa: BLE001
        check(label, False, f"{detail} - unexpected {type(error).__name__}: {error!r}")
        return None
    check(label, False, f"{detail} - no exception raised")
    return None


REAL_DATA_DIR = REPO_ROOT / "data"


def snapshot_data_tree():
    out = {}
    for path in REAL_DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(REAL_DATA_DIR))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(REAL_DATA_DIR))] = "<unreadable>"
    return out


_data_tree_before_everything = snapshot_data_tree()

# ============================================================
# F-N13 (a) - AST taraması: facade + adapter ağ/LLM/alt süreç import etmez.
# ============================================================

_FORBIDDEN = {"anthropic", "httpx", "dotenv", "openai", "socket", "subprocess", "requests"}
for _rel in ("ui/services/manual_fact_mutation_facade.py", "ui/services/manual_fact_mutation_adapters.py"):
    _tree = ast.parse((REPO_ROOT / _rel).read_text(encoding="utf-8"))
    _roots = set()
    for _node in ast.walk(_tree):
        if isinstance(_node, ast.Import):
            _roots.update(a.name.split(".")[0] for a in _node.names)
        elif isinstance(_node, ast.ImportFrom) and _node.module:
            _roots.add(_node.module.split(".")[0])
    check(f"F-N13a {_rel} imports no network/LLM/subprocess module", not (_roots & _FORBIDDEN),
          f"roots={sorted(_roots)}")
    check(f"F-N13a positive control: AST scan sees {_rel}'s real imports (json/hashlib)",
          {"json", "hashlib"} <= _roots, f"roots={sorted(_roots)}")

# F-N13 (b) - zehirli stub'lar + sayan socket hook'u, facade importu ve
# preview/apply pencereleri boyunca silahlı.
_POISON_NAMES = ("anthropic", "httpx", "openai", "dotenv", "requests")
_poison_hits = []


class _PoisonModule(types.ModuleType):
    def __getattr__(self, item):
        _poison_hits.append((self.__name__, item))
        raise AssertionError(f"poisoned module {self.__name__} accessed: {item}")


_saved_modules = {name: sys.modules.get(name) for name in _POISON_NAMES}
for _name in _POISON_NAMES:
    sys.modules[_name] = _PoisonModule(_name)

_socket_events = []
_socket_armed = [False]


def _socket_counter(event, args):
    if _socket_armed[0] and event.startswith("socket."):
        _socket_events.append(event)


sys.addaudithook(_socket_counter)
_socket_armed[0] = True
_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
_probe.close()
_socket_armed[0] = False
check("F-N13b positive control: the counting hook observes socket.* events", len(_socket_events) >= 1)
_socket_events.clear()

_socket_armed[0] = True
from ui.services import authz as _authz  # noqa: E402
from ui.services import mutation_coordinator as mc  # noqa: E402
from ui.services import mutation_lock as ml  # noqa: E402
from ui.services import mutation_registry as mr  # noqa: E402
from ui.services import paths as _paths  # noqa: E402
from ui.services import manual_fact_mutation_facade as fac  # noqa: E402
from ui.services import manual_fact_mutation_adapters as ada  # noqa: E402
from ui.services.common import ApprovalUiError, PreconditionRaceDetectedError, StaleViewError  # noqa: E402

import manual_fact_entry_engine as mfe  # noqa: E402
import case_fact_validator  # noqa: E402
import fact_approval  # noqa: E402
_socket_armed[0] = False
check("F-N13c zero socket.* events while importing the facade/adapter/engine",
      _socket_events == [], f"{_socket_events!r}")


# ============================================================
# Fake journal (exact SQL shapes) + fake locks.
# ============================================================

class FakeJournalCursor:
    def __init__(self, conn):
        self._conn = conn
        self._last_result = None
        self.rowcount = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _row(self, journal_id):
        for r in self._conn.table:
            if r["id"] == journal_id:
                return r
        raise AssertionError(f"no fake journal row id={journal_id}")

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._conn.calls.append(normalized)
        if normalized.startswith("SELECT 1 FROM mutation.mutation_journal"):
            (resource_key,) = params
            hit = any(
                r["resource_key"] == resource_key
                and r["state"] in ("prepared", "executing", "reconciliation_required")
                for r in self._conn.table
            )
            self._last_result = (1,) if hit else None
        elif normalized.startswith("SELECT id, state, request_fingerprint, observed_post_hash"):
            (idempotency_key,) = params
            matches = [r for r in self._conn.table if r["idempotency_key"] == idempotency_key]
            self._last_result = None if not matches else (
                matches[0]["id"], matches[0]["state"], matches[0]["request_fingerprint"],
                matches[0]["observed_post_hash"], matches[0]["failure_code"], matches[0]["resolution_code"],
            )
        elif normalized.startswith("SELECT id, state FROM mutation.mutation_journal WHERE resource_key = %s AND action_family = %s AND target_ref = %s"):
            resource_key, action_family, target_ref = params
            rows = [r for r in self._conn.table
                    if r["resource_key"] == resource_key and r["action_family"] == action_family
                    and r["target_ref"] == target_ref]
            self._last_result = (rows[-1]["id"], rows[-1]["state"]) if rows else None
        elif normalized.startswith("INSERT INTO mutation.mutation_journal"):
            (resource_key, action_family, actor_user_id, actor_label, target_ref, target_state,
             pre_hash, pre_revision, idempotency_key, request_fingerprint) = params
            new_id = len(self._conn.table) + 1
            self._conn.table.append({
                "id": new_id, "resource_key": resource_key, "action_family": action_family,
                "actor_user_id": actor_user_id, "actor_label": actor_label, "target_ref": target_ref,
                "target_state": target_state, "pre_hash": pre_hash, "pre_revision": pre_revision,
                "idempotency_key": idempotency_key, "request_fingerprint": request_fingerprint,
                "state": "prepared", "failure_code": None, "resolution_code": None,
                "observed_post_hash": None,
            })
            self._last_result = (new_id,)
            self.rowcount = 1
        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'executing'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "executing"
            self.rowcount = 1
        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'completed'"):
            observed_post_hash, journal_id = params
            row = self._row(journal_id)
            row["state"] = "completed"
            row["observed_post_hash"] = observed_post_hash
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
    def __init__(self):
        self.table = []
        self.calls = []

    def cursor(self):
        return FakeJournalCursor(self)

    def close(self):
        pass


_lock_calls = []
_on_acquire_hooks = []
_original_acquire = ml.acquire_case_lock_session
_original_release = ml.release_lock_session


def _fake_acquire(conn, case_id):
    _lock_calls.append(("acquire", case_id))
    hooks = list(_on_acquire_hooks)
    _on_acquire_hooks.clear()
    for hook in hooks:
        hook(case_id)
    return 4242


def _fake_release(conn, advisory_lock_id):
    _lock_calls.append(("release", advisory_lock_id))
    return True


# ============================================================
# Fixtures.
# ============================================================

DOC = "ihbarname_001"
DATE = "2026-02-10"
EXCERPT = "İhbarname mükellefe 10.02.2026 tarihinde tebliğ edilmiştir."
REAL_CASE_0001 = _paths.CASES_DIR / "case_0001"

_created_case_dirs = []
_junction_links = []
_outside_dirs = []


def make_junction(link_path: Path, target_path: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mklink /J failed rc={result.returncode}")
    _junction_links.append(link_path)


def write_json(path: Path, data) -> None:
    path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def manual_input_for(case_id, **fact_overrides):
    fact = {"role": "notification_date", "date": DATE, "page": 1, "text_excerpt": EXCERPT}
    fact.update(fact_overrides)
    return {"schema_version": 1, "case_id": case_id, "document_id": DOC, "facts": [fact]}


def doc_dir_of(case_dir):
    return case_dir / "documents" / DOC


def input_path_of(case_dir):
    return doc_dir_of(case_dir) / mfe.MANUAL_INPUT_DIRNAME / mfe.MANUAL_INPUT_FILENAME


def ext_dir_of(case_dir):
    return doc_dir_of(case_dir) / "extractions"


def pending_of(case_dir):
    return ext_dir_of(case_dir) / mfe.CURRENT_PENDING_FILENAME


def temp_of(case_dir):
    return ext_dir_of(case_dir) / mfe.TEMP_FILENAME


def reviews_of(case_dir):
    return ext_dir_of(case_dir) / mfe.GENERATION_REVIEWS_DIRNAME


def make_manual_case(tag):
    case_id = f"mfiso{tag}{uuid.uuid4().hex[:8]}"
    dst = _paths.CASES_DIR / case_id
    shutil.copytree(REAL_CASE_0001, dst)
    _created_case_dirs.append(dst)
    for path in dst.rglob("*"):
        if path.is_file() and (path.suffix in (".json", ".pending", ".bak") or path.name.endswith(".json.pending")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "case_0001" in text:
                path.write_text(text.replace("case_0001", case_id), encoding="utf-8")
    shutil.rmtree(ext_dir_of(dst))
    document = json.loads(doc_dir_of(dst).joinpath("document.json").read_text(encoding="utf-8"))
    document["file"]["page_count"] = 1
    write_json(doc_dir_of(dst) / "document.json", document)
    input_path_of(dst).parent.mkdir()
    write_json(input_path_of(dst), manual_input_for(case_id))
    return case_id, dst


def make_principal_and_repo(case_id, *, assigned=True, role="lawyer", user_id=7):
    principal = _authz.Principal(user_id=user_id, session_id=700 + user_id, role_version_at_issue=1)
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[700 + user_id] = _authz.SessionRecord(user_id=user_id, current_authz_version=1, disabled=False)
    if assigned:
        repo.assignments[(user_id, case_id)] = _authz.CaseAssignmentRecord(role=role)
    return principal, repo


def preview(case_id, principal, repo):
    _socket_armed[0] = True
    try:
        return fac.preview_manual_fact(case_id, DOC, principal=principal, authz_repository=repo)
    finally:
        _socket_armed[0] = False


def apply(case_id, digest, principal, repo, *, conn=None, attempt=1):
    conn = conn if conn is not None else FakeJournalConn()
    _socket_armed[0] = True
    try:
        result = fac.apply_manual_fact(
            case_id, DOC, digest, attempt=attempt, principal=principal, authz_repository=repo,
            conn_factory=lambda: conn,
        )
    finally:
        _socket_armed[0] = False
    return result, conn


def entry_from_row(row, *, state=None):
    return mr.JournalEntrySnapshot(
        journal_id=row["id"], resource_key=row["resource_key"], action_family=row["action_family"],
        target_ref=row["target_ref"], target_state=row["target_state"], pre_hash=row["pre_hash"],
        pre_revision=row["pre_revision"], expected_post_hash=None, state=state or row["state"],
        idempotency_key=row["idempotency_key"], request_fingerprint=row["request_fingerprint"],
        actor_label=row["actor_label"],
    )


ADAPTER = ada.ManualFactReconciliationAdapter(mfe)


def decide(entry):
    evidence = ADAPTER.gather_evidence(entry)
    try:
        return mr._decide_outcome(entry, evidence).new_state, evidence
    except mr.PreparedJournalUnresolvedError:
        return "prepared_unresolved", evidence


_collected_errors = []


def collect(error):
    if error is not None:
        _collected_errors.append(error)
    return error


ml.acquire_case_lock_session = _fake_acquire
ml.release_lock_session = _fake_release

try:
    # ========================================================
    # F-P1 - preview is read-only, excerpt text never returned.
    # ========================================================
    case1, dir1 = make_manual_case("p1")
    principal1, repo1 = make_principal_and_repo(case1)
    before = snapshot_data_tree()
    prev1 = preview(case1, principal1, repo1)
    check("F-P1a preview leaves the data/ tree byte-identical", snapshot_data_tree() == before)
    check("F-P1b preview returns input_digest + text_excerpt_sha256 + excerpt_found",
          len(prev1["input_digest"]) == 64 and prev1["excerpt_found"] is True
          and prev1["text_excerpt_sha256"] == hashlib.sha256(EXCERPT.encode("utf-8")).hexdigest())
    check("F-P1c preview NEVER contains the excerpt text (K-18)",
          EXCERPT not in json.dumps(prev1, ensure_ascii=False) and "tebliğ edilmiştir" not in str(prev1))
    check("F-P1d preview reports notification_date and page",
          prev1["notification_date"] == DATE and prev1["page"] == 1)

    # ========================================================
    # F-P2 - apply completes.
    # ========================================================
    result1, conn1 = apply(case1, prev1["input_digest"], principal1, repo1)
    row1 = conn1.table[0] if conn1.table else {}
    check("F-P2a apply -> exactly one journal row, completed, generation.fact_manual",
          len(conn1.table) == 1 and row1["state"] == "completed"
          and row1["action_family"] == "generation.fact_manual"
          and row1["target_ref"] == f"fact.{DOC}.pending" and result1.replayed is False, f"{conn1.table!r}")
    check("F-P2b pending bytes have exactly the preview's deterministic sha",
          hashlib.sha256(pending_of(dir1).read_bytes()).hexdigest() == prev1["pending_sha256"]
          == result1.pending_sha256 == row1.get("observed_post_hash"))
    audits1 = sorted(reviews_of(dir1).iterdir())
    check("F-P2c exactly one manual_-prefixed generation audit",
          len(audits1) == 1 and audits1[0].name.startswith(f"manual_{DOC}_")
          and audits1[0].name.endswith(".generation_audit.json"))
    audit1 = json.loads(audits1[0].read_bytes())
    check("F-P2d audit binds channel/action_family/attempt=1/composite pre_revision == journal",
          audit1["channel"] == "local_lawyer_manual_fact_cli"
          and audit1["action_family"] == "generation.fact_manual"
          and audit1["attempt"] == 1
          and audit1["pre_revision"] == row1["pre_revision"]
          == fac.compute_pre_revision(prev1["input_digest"], 1)
          and audit1["input_digest"] == prev1["input_digest"]
          and audit1["pending_sha256"] == prev1["pending_sha256"])
    check("F-P2e journal pre_revision is the composite, NOT the raw input_digest",
          row1["pre_revision"] != prev1["input_digest"])
    pending1 = json.loads(pending_of(dir1).read_bytes())
    check("F-P2f pending is method=manual, every fact unverified",
          pending1["extractor"]["method"] == "manual"
          and all(f["verification_state"] == "unverified" for f in pending1["facts"]))
    check("F-P2g canonical facts.json NOT written", not (ext_dir_of(dir1) / "facts.json").exists())
    check("F-P2h no temp residue after success", not os.path.lexists(temp_of(dir1)))
    check("F-P2i the real fact_approval.validate_pending accepts the manual pending",
          fact_approval.validate_pending(pending_of(dir1))[0]["extraction_id"] == pending1["extraction_id"])
    check("F-P2j audit_file is a bare file name (no absolute path in the result)",
          result1.audit_file == audits1[0].name)
    check("F-P2k adapter: completed row on disk reconciles to completed (post proven)",
          decide(entry_from_row(row1, state="executing"))[0] == "completed")

    # ========================================================
    # F-N1 (M-09) - existing pending (own / LLM-family).
    # ========================================================
    pending_before = pending_of(dir1).read_bytes()
    err = collect(expect_raises(fac.ManualFactPendingExistsError, lambda: preview(case1, principal1, repo1),
                                "F-N1a own completed pending -> preview refused (M-09)"))
    conn_second = FakeJournalConn()
    conn_second.table = [dict(row1)]
    err = collect(expect_raises(fac.ManualFactPendingExistsError,
                                lambda: apply(case1, prev1["input_digest"], principal1, repo1, conn=conn_second),
                                "F-N1b second apply after completion refused at PL (M-09)"))
    check("F-N1c second apply wrote no new journal row", len(conn_second.table) == 1)
    check("F-N1d M-09 message shows this family's last journal row (N-L4)",
          err is not None and "journal_id=1 state=completed" in str(err), f"{err}")
    check("F-N1e pending byte-unchanged", pending_of(dir1).read_bytes() == pending_before)

    case_llm, dir_llm = make_manual_case("llm")
    principal_llm, repo_llm = make_principal_and_repo(case_llm)
    prev_llm = preview(case_llm, principal_llm, repo_llm)
    ext_dir_of(dir_llm).mkdir()
    llm_src = REAL_CASE_0001 / "documents" / "dava_dilekcesi_001" / "extractions" / fact_approval.CURRENT_PENDING_FILENAME
    llm_bytes = llm_src.read_bytes() if llm_src.is_file() else b'{"extractor": {"method": "llm"}}'
    pending_of(dir_llm).write_bytes(llm_bytes)
    collect(expect_raises(fac.ManualFactPendingExistsError, lambda: preview(case_llm, principal_llm, repo_llm),
                          "F-N1f LLM-family pending present -> preview refused"))
    conn_llm = FakeJournalConn()
    err = collect(expect_raises(fac.ManualFactPendingExistsError,
                                lambda: apply(case_llm, prev_llm["input_digest"], principal_llm, repo_llm, conn=conn_llm),
                                "F-N1g LLM-family pending present -> apply refused"))
    check("F-N1h zero journal rows; LLM pending byte-unchanged; message says no record",
          conn_llm.table == [] and pending_of(dir_llm).read_bytes() == llm_bytes
          and err is not None and "kayıt yok/bilinmiyor" in str(err))

    # ========================================================
    # F-N2 (M-10) - canonical exists.
    # ========================================================
    case2, dir2 = make_manual_case("n2")
    principal2, repo2 = make_principal_and_repo(case2)
    prev2 = preview(case2, principal2, repo2)
    ext_dir_of(dir2).mkdir()
    (ext_dir_of(dir2) / "facts.json").write_bytes(b"{}")
    collect(expect_raises(fac.ManualFactCanonicalExistsError, lambda: preview(case2, principal2, repo2),
                          "F-N2a canonical present -> preview refused (M-10)"))
    conn2 = FakeJournalConn()
    collect(expect_raises(fac.ManualFactCanonicalExistsError,
                          lambda: apply(case2, prev2["input_digest"], principal2, repo2, conn=conn2),
                          "F-N2b canonical present -> apply refused"))
    check("F-N2c zero journal rows, no pending", conn2.table == [] and not pending_of(dir2).exists())

    # ========================================================
    # F-N3 (M-12) - stale preview / change while waiting for the lock.
    # ========================================================
    case3, dir3 = make_manual_case("n3")
    principal3, repo3 = make_principal_and_repo(case3)
    prev3 = preview(case3, principal3, repo3)
    write_json(input_path_of(dir3), manual_input_for(case3, text_excerpt=EXCERPT.replace(" ", "  ", 1)))
    conn3 = FakeJournalConn()
    err = collect(expect_raises(StaleViewError,
                                lambda: apply(case3, prev3["input_digest"], principal3, repo3, conn=conn3),
                                "F-N3a input changed after preview -> StaleViewError"))
    check("F-N3b ... a plain StaleViewError (not a lock race), zero rows, no pending",
          err is not None and not isinstance(err, PreconditionRaceDetectedError)
          and conn3.table == [] and not pending_of(dir3).exists())
    prev3b = preview(case3, principal3, repo3)

    def mutate_input_during_lock_wait(_case_id):
        write_json(input_path_of(dir3), manual_input_for(case3))

    _on_acquire_hooks.append(mutate_input_during_lock_wait)
    conn3b = FakeJournalConn()
    collect(expect_raises(PreconditionRaceDetectedError,
                          lambda: apply(case3, prev3b["input_digest"], principal3, repo3, conn=conn3b),
                          "F-N3c input changed while waiting for the lock -> PreconditionRaceDetectedError"))
    check("F-N3d zero rows, no pending, no audit", conn3b.table == [] and not pending_of(dir3).exists()
          and not reviews_of(dir3).exists())

    def create_pending_during_lock_wait(_case_id):
        ext_dir_of(dir3).mkdir(exist_ok=True)
        pending_of(dir3).write_bytes(b"{}")

    prev3c = preview(case3, principal3, repo3)
    _on_acquire_hooks.append(create_pending_during_lock_wait)
    conn3c = FakeJournalConn()
    err = collect(expect_raises(fac.ManualFactPendingExistsError,
                                lambda: apply(case3, prev3c["input_digest"], principal3, repo3, conn=conn3c),
                                "F-N3e pending appearing during the lock wait -> refused under lock (PC)"))
    check("F-N3f PC refusal wrote zero rows; foreign pending untouched",
          conn3c.table == [] and pending_of(dir3).read_bytes() == b"{}")
    pending_of(dir3).unlink()

    # ========================================================
    # F-N4 (M-01/M-3) - containment with REAL junctions.
    # ========================================================
    if _IS_WINDOWS:
        case4, dir4 = make_manual_case("n4")
        principal4, repo4 = make_principal_and_repo(case4)
        manual_dir4 = input_path_of(dir4).parent
        outside4 = Path(tempfile.mkdtemp(prefix="vergi_mf_outside_"))
        _outside_dirs.append(outside4)
        write_json(outside4 / mfe.MANUAL_INPUT_FILENAME, manual_input_for(case4))
        real_manual4 = doc_dir_of(dir4) / "manual_input_real"
        shutil.move(str(manual_dir4), str(real_manual4))

        def junction_case(label, target):
            make_junction(manual_dir4, target)
            conn = FakeJournalConn()
            try:
                collect(expect_raises(fac.ManualFactInputContainmentError,
                                      lambda: preview(case4, principal4, repo4),
                                      f"F-N4 {label} -> preview refused (containment)"))
                collect(expect_raises(fac.ManualFactInputContainmentError,
                                      lambda: apply(case4, "0" * 64, principal4, repo4, conn=conn),
                                      f"F-N4 {label} -> apply refused (containment)"))
                check(f"F-N4 {label} -> zero journal rows, no pending",
                      conn.table == [] and not pending_of(dir4).exists())
            finally:
                os.rmdir(manual_dir4)
                _junction_links.remove(manual_dir4)

        junction_case("junction escaping the case (outside data/)", outside4)
        junction_case("junction to a SIBLING dir in the same parent (name check)", real_manual4)
        other_doc_manual = dir4 / "documents" / "vir_001" / "manual_input"
        shutil.copytree(real_manual4, other_doc_manual)
        junction_case("junction to another document's manual_input (in-tree alias)", other_doc_manual)
        broken_target = Path(tempfile.mkdtemp(prefix="vergi_mf_broken_"))
        make_junction(manual_dir4, broken_target)
        shutil.rmtree(broken_target)
        conn_b = FakeJournalConn()
        try:
            collect(expect_raises(fac.ManualFactInputContainmentError, lambda: preview(case4, principal4, repo4),
                                  "F-N4 broken junction -> preview refused"))
            check("F-N4 broken junction -> zero rows", conn_b.table == [])
        finally:
            os.rmdir(manual_dir4)
            _junction_links.remove(manual_dir4)
        # Write-side intermediate (N-L6): extractions/ as a junction to
        # another document's extractions dir.
        shutil.move(str(real_manual4), str(manual_dir4))
        prev4 = preview(case4, principal4, repo4)
        other_ext = dir4 / "documents" / "vir_001" / "extractions"
        make_junction(ext_dir_of(dir4), other_ext)
        conn_w = FakeJournalConn()
        try:
            collect(expect_raises(fac.ManualFactInputContainmentError,
                                  lambda: apply(case4, prev4["input_digest"], principal4, repo4, conn=conn_w),
                                  "F-N4 write-side extractions/ junction to another document -> refused before the writer (N-L6)"))
            check("F-N4 write-side alias -> zero rows, the other document's extractions untouched",
                  conn_w.table == [] and not (other_ext / mfe.CURRENT_PENDING_FILENAME).exists())
        finally:
            os.rmdir(ext_dir_of(dir4))
            _junction_links.remove(ext_dir_of(dir4))
    else:
        skip_info("F-N4 junction containment", "requires Windows mklink /J")

    # ========================================================
    # F-N5 - unassigned actor.
    # ========================================================
    case5, dir5 = make_manual_case("n5")
    principal5, repo5 = make_principal_and_repo(case5, assigned=False)
    conn5 = FakeJournalConn()
    expect_raises(_authz.CaseAccessDeniedError, lambda: preview(case5, principal5, repo5),
                  "F-N5a unassigned actor -> preview CaseAccessDeniedError")
    expect_raises(_authz.CaseAccessDeniedError, lambda: apply(case5, "0" * 64, principal5, repo5, conn=conn5),
                  "F-N5b unassigned actor -> apply CaseAccessDeniedError")
    principal5r, repo5r = make_principal_and_repo(case5, role="analyst")
    expect_raises(_authz.CaseAccessDeniedError, lambda: apply(case5, "0" * 64, principal5r, repo5r, conn=conn5),
                  "F-N5c read-only role -> apply CaseAccessDeniedError")
    check("F-N5d zero rows", conn5.table == [])

    # ========================================================
    # F-N6 (M-13) - identity.
    # ========================================================
    case6, dir6 = make_manual_case("n6")
    principal6, repo6 = make_principal_and_repo(case6)
    write_json(input_path_of(dir6), dict(manual_input_for(case6), case_id="case_0001"))
    collect(expect_raises(fac.ManualFactIdentityMismatchError, lambda: preview(case6, principal6, repo6),
                          "F-N6a input case_id != --case -> M-13 refusal"))
    write_json(input_path_of(dir6), dict(manual_input_for(case6), document_id="vir_001"))
    collect(expect_raises(fac.ManualFactIdentityMismatchError, lambda: preview(case6, principal6, repo6),
                          "F-N6b input document_id != --document -> M-13 refusal"))
    write_json(input_path_of(dir6), manual_input_for(case6))
    case_json6 = dir6 / "case.json"
    case_json6_original = case_json6.read_bytes()
    case_data6 = json.loads(case_json6_original)
    case_data6["case_id"] = "case_0001"
    write_json(case_json6, case_data6)
    collect(expect_raises(fac.ManualFactIdentityMismatchError, lambda: preview(case6, principal6, repo6),
                          "F-N6g case.json case_id != --case -> M-13 refusal"))
    case_json6.write_bytes(case_json6_original)
    document6 = json.loads((doc_dir_of(dir6) / "document.json").read_bytes())
    document6["document_id"] = "ihbarname_999"
    write_json(doc_dir_of(dir6) / "document.json", document6)
    collect(expect_raises(fac.ManualFactIdentityMismatchError, lambda: preview(case6, principal6, repo6),
                          "F-N6c document.json document_id != directory name -> M-13 refusal"))
    document6["document_id"] = DOC
    document6["case_id"] = "case_0001"
    write_json(doc_dir_of(dir6) / "document.json", document6)
    conn6 = FakeJournalConn()
    collect(expect_raises(fac.ManualFactIdentityMismatchError,
                          lambda: apply(case6, "0" * 64, principal6, repo6, conn=conn6),
                          "F-N6d document.json case_id mismatch -> M-13 refusal on apply"))
    check("F-N6e zero rows", conn6.table == [])
    document6["file"]["page_count"] = None
    document6["case_id"] = case6
    write_json(doc_dir_of(dir6) / "document.json", document6)
    collect(expect_raises(fac.ManualFactDocumentIneligibleError, lambda: preview(case6, principal6, repo6),
                          "F-N6f page_count null -> M-04 refusal through the facade"))

    # ========================================================
    # F-N7 (M-14) - temp residue.
    # ========================================================
    case7, dir7 = make_manual_case("n7")
    principal7, repo7 = make_principal_and_repo(case7)
    prev7 = preview(case7, principal7, repo7)
    ext_dir_of(dir7).mkdir()
    temp_of(dir7).write_bytes(b"residue")
    conn7 = FakeJournalConn()
    collect(expect_raises(fac.ManualFactTempResidueError,
                          lambda: apply(case7, prev7["input_digest"], principal7, repo7, conn=conn7),
                          "F-N7a temp residue -> refused (M-14)"))
    check("F-N7b zero rows; the residue is NOT deleted",
          conn7.table == [] and temp_of(dir7).read_bytes() == b"residue")

    # ========================================================
    # F-N10/F-N11 + N-M1 crash matrix.
    # ========================================================
    # (a) writer validator FAIL -> reconciliation_required -> failed;
    #     attempt 1 again -> PriorAttemptFailedError; attempt 2 -> completed.
    case_a, dir_a = make_manual_case("ca")
    principal_a, repo_a = make_principal_and_repo(case_a)
    prev_a = preview(case_a, principal_a, repo_a)
    conn_a = FakeJournalConn()
    _orig_validate = case_fact_validator.validate_fact_extraction

    def _failing_validate(path, raise_on_error=True):
        raise ValueError("synthetic writer-side validator failure /abs/path/should/not/leak")

    case_fact_validator.validate_fact_extraction = _failing_validate
    try:
        err_a = collect(expect_raises(fac.ManualFactWriteFailedError,
                                      lambda: apply(case_a, prev_a["input_digest"], principal_a, repo_a, conn=conn_a),
                                      "F-N10a writer validator FAIL -> ManualFactWriteFailedError"))
    finally:
        case_fact_validator.validate_fact_extraction = _orig_validate
    check("F-N10b journal row is reconciliation_required (writer boundary crossed)",
          len(conn_a.table) == 1 and conn_a.table[0]["state"] == "reconciliation_required")
    check("F-N10c disk clean after in-process rollback (no pending/temp/audit)",
          not pending_of(dir_a).exists() and not temp_of(dir_a).exists()
          and (not reviews_of(dir_a).exists() or list(reviews_of(dir_a).iterdir()) == []))
    check("F-N10d (N-L7) the message names the journal row and the reconciliation command",
          err_a is not None and "journal_id=1" in str(err_a) and "reconciliation_operator" in str(err_a)
          and "--attempt" in str(err_a), f"{err_a}")
    check("F-N10e the original validator message (with its path) does NOT leak into str(error)",
          err_a is not None and "/abs/path" not in str(err_a) and "synthetic" not in str(err_a))
    outcome_a, _ = decide(entry_from_row(conn_a.table[0]))
    check("F-N10f cell (a): adapter evidence resolves to failed", outcome_a == "failed")
    conn_a.table[0]["state"] = "failed"
    expect_raises(mc.PriorAttemptFailedError,
                  lambda: apply(case_a, prev_a["input_digest"], principal_a, repo_a, conn=conn_a, attempt=1),
                  "F-N11a same input + attempt 1 after failed -> PriorAttemptFailedError")
    check("F-N11b ... and no new journal row", len(conn_a.table) == 1)
    result_a2, _ = apply(case_a, prev_a["input_digest"], principal_a, repo_a, conn=conn_a, attempt=2)
    check("F-N11c attempt 2 -> NEW idempotency key, completed",
          len(conn_a.table) == 2 and conn_a.table[1]["state"] == "completed"
          and conn_a.table[1]["idempotency_key"] != conn_a.table[0]["idempotency_key"]
          and result_a2.attempt == 2)
    audit_a2 = json.loads(sorted(reviews_of(dir_a).iterdir())[-1].read_bytes())
    check("F-N11d attempt-2 audit carries attempt=2 and the matching composite",
          audit_a2["attempt"] == 2 and audit_a2["pre_revision"] == conn_a.table[1]["pre_revision"]
          == fac.compute_pre_revision(prev_a["input_digest"], 2))

    # (b) hard crash after temp write: temp only.
    case_b, dir_b = make_manual_case("cb")
    principal_b, repo_b = make_principal_and_repo(case_b)
    prev_b = preview(case_b, principal_b, repo_b)
    conn_b2 = FakeJournalConn()
    result_b, _ = apply(case_b, prev_b["input_digest"], principal_b, repo_b, conn=conn_b2)
    row_b = dict(conn_b2.table[0])
    frozen_b = pending_of(dir_b).read_bytes()
    pending_of(dir_b).unlink()
    for p in reviews_of(dir_b).iterdir():
        p.unlink()
    temp_of(dir_b).write_bytes(frozen_b)
    outcome_b, ev_b = decide(entry_from_row(row_b, state="executing"))
    check("F-N10g cell (b) temp-only: pre=True, post=False -> failed",
          outcome_b == "failed" and ev_b.pre_state_confirmed_unchanged and not ev_b.post_state_verified)
    conn_b3 = FakeJournalConn()
    collect(expect_raises(fac.ManualFactTempResidueError,
                          lambda: apply(case_b, prev_b["input_digest"], principal_b, repo_b, conn=conn_b3, attempt=2),
                          "F-N10h after cell (b) the next apply is refused by M-14"))
    temp_of(dir_b).unlink()

    # (c') N-M1: audit written, crash before os.replace: audit only.
    case_c, dir_c = make_manual_case("cc")
    principal_c, repo_c = make_principal_and_repo(case_c)
    prev_c = preview(case_c, principal_c, repo_c)
    conn_c = FakeJournalConn()
    apply(case_c, prev_c["input_digest"], principal_c, repo_c, conn=conn_c)
    row_c = dict(conn_c.table[0])
    frozen_c = pending_of(dir_c).read_bytes()
    pending_of(dir_c).unlink()
    outcome_c, ev_c = decide(entry_from_row(row_c, state="executing"))
    check("F-N10i cell audit-only (N-M1 crash between audit and os.replace): pre=True -> failed",
          outcome_c == "failed" and ev_c.pre_state_confirmed_unchanged and not ev_c.post_state_verified)

    # (d) audit + pending, crash before _mark_completed.
    case_d, dir_d = make_manual_case("cd")
    principal_d, repo_d = make_principal_and_repo(case_d)
    prev_d = preview(case_d, principal_d, repo_d)
    conn_d = FakeJournalConn()
    apply(case_d, prev_d["input_digest"], principal_d, repo_d, conn=conn_d)
    outcome_d, ev_d = decide(entry_from_row(conn_d.table[0], state="executing"))
    check("F-N10j cell (d) audit+pending, row executing: post=True, pre=False -> completed",
          outcome_d == "completed" and ev_d.post_state_verified and not ev_d.pre_state_confirmed_unchanged
          and ev_d.observed_post_hash == prev_d["pending_sha256"])

    # prepared-row cell (JournalExecutingTransitionFailedError leaves 'prepared').
    outcome_p, ev_p = decide(entry_from_row(row_c, state="prepared"))
    check("F-N10k prepared row, writer never ran (disk clean of pending): -> failed (never executed)",
          outcome_p == "failed")

    # Externally-planted pending without any audit (not producible by the
    # N-M1 writer itself) stays dual-false - documented, deliberate.
    pending_of(dir_c).write_bytes(frozen_c)
    for p in reviews_of(dir_c).iterdir():
        p.unlink()
    outcome_x, ev_x = decide(entry_from_row(row_c, state="executing"))
    check("F-N10l pending-without-audit (external interference only) is dual-false -> stays reconciliation_required",
          outcome_x == "reconciliation_required"
          and not ev_x.pre_state_confirmed_unchanged and not ev_x.post_state_verified)

    # ========================================================
    # F-N9 - cross-family isolation (K-13).
    # ========================================================
    from ui.services import fact_extraction_mutation_adapters as llm_ada
    from ui.services import fact_extraction_mutation_facade as llm_fac
    import fact_extraction_engine as fee

    row_d = conn_d.table[0]
    llm_entry = mr.JournalEntrySnapshot(
        journal_id=99, resource_key=row_d["resource_key"], action_family="generation.fact_extraction",
        target_ref=row_d["target_ref"], target_state="generated", pre_hash=row_d["pre_hash"],
        pre_revision=row_d["pre_revision"], expected_post_hash=None, state="executing",
        idempotency_key=row_d["idempotency_key"], request_fingerprint=row_d["request_fingerprint"],
        actor_label=row_d["actor_label"],
    )
    llm_ev = llm_ada.FactExtractionReconciliationAdapter(fee).gather_evidence(llm_entry)
    check("F-N9a the LLM adapter does NOT accept the manual audit as post-state proof",
          llm_ev.post_state_verified is False)
    manual_audit_d = json.loads(sorted(reviews_of(dir_d).iterdir())[0].read_bytes())
    check("F-N9b the LLM facade's replay matcher rejects the manual audit",
          llm_fac._audit_record_matches_base(
              manual_audit_d, idempotency_key=row_d["idempotency_key"], resource_key=row_d["resource_key"],
              action_family="generation.fact_extraction", document_id=DOC,
              pending_sha256=prev_d["pending_sha256"], masking_policy_version="x",
              masking_extra_terms_digest="y",
          ) is False)
    llm_shaped = dict(manual_audit_d, channel="local_lawyer_fact_extraction_cli",
                      action_family="generation.fact_extraction")
    (reviews_of(dir_d) / f"extract_{DOC}_20260101_000000.generation_audit.json").write_bytes(
        json.dumps(llm_shaped, ensure_ascii=False, indent=2).encode("utf-8"))
    check("F-N9c an LLM-family audit alongside is NOT counted by the manual adapter (still exactly 1 match)",
          decide(entry_from_row(row_d, state="executing"))[0] == "completed")
    llm_only = dict(manual_audit_d, channel="local_lawyer_fact_extraction_cli")
    for p in reviews_of(dir_d).iterdir():
        p.unlink()
    (reviews_of(dir_d) / f"manual_{DOC}_20260101_000000.generation_audit.json").write_bytes(
        json.dumps(llm_only, ensure_ascii=False, indent=2).encode("utf-8"))
    check("F-N9d a channel-tampered audit is not accepted (post False -> not completed)",
          decide(entry_from_row(row_d, state="executing"))[0] != "completed")
    (reviews_of(dir_d) / f"manual_{DOC}_20260101_000001.generation_audit.json").write_bytes(
        json.dumps(manual_audit_d, ensure_ascii=False, indent=2).encode("utf-8"))
    check("F-N9e restoring the genuine audit restores completed", decide(entry_from_row(row_d, state="executing"))[0] == "completed")
    (reviews_of(dir_d) / "broken.generation_audit.json").write_bytes(b"{not json")
    ev_broken = ADAPTER.gather_evidence(entry_from_row(row_d, state="executing"))
    llm_ev_broken = llm_ada.FactExtractionReconciliationAdapter(fee).gather_evidence(llm_entry)
    check("F-N9f an unparseable audit stops BOTH families fail-closed (K-13, deliberate)",
          ev_broken.post_state_verified is False and llm_ev_broken.post_state_verified is False)

    # Binding-field negatives on a fresh completed case (each tamper alone
    # must defeat the post-state proof).
    case_t, dir_t = make_manual_case("bt")
    principal_t, repo_t = make_principal_and_repo(case_t)
    prev_t = preview(case_t, principal_t, repo_t)
    conn_t = FakeJournalConn()
    apply(case_t, prev_t["input_digest"], principal_t, repo_t, conn=conn_t)
    audit_path_t = sorted(reviews_of(dir_t).iterdir())[0]
    genuine_t = audit_path_t.read_bytes()
    entry_t = entry_from_row(conn_t.table[0], state="executing")
    check("F-N9g binding baseline: genuine audit -> completed", decide(entry_t)[0] == "completed")
    for field, value in (("case_id", "other_case"), ("document_id", "vir_001"), ("target_ref", "fact.x.pending"),
                         ("target_state", "x"), ("mutation_actor_ref", "999"), ("mutation_idempotency_key", "0" * 64),
                         ("mutation_resource_key", "case:other"), ("pending_sha256", "0" * 64),
                         ("outcome", "rolled_back"), ("schema_version", "2"), ("attempt", 2),
                         ("input_digest", "0" * 64), ("pre_revision", "0" * 64)):
        tampered = json.loads(genuine_t)
        tampered[field] = value
        audit_path_t.write_bytes(json.dumps(tampered).encode("utf-8"))
        check(f"F-N9h tampering audit.{field} defeats the post-state proof", decide(entry_t)[0] != "completed")
    tampered = json.loads(genuine_t)
    tampered["identity_payload"]["source_text_sha256"] = "0" * 64
    audit_path_t.write_bytes(json.dumps(tampered).encode("utf-8"))
    check("F-N9i tampering the identity_payload (input_digest recompute mismatch) defeats the proof",
          decide(entry_t)[0] != "completed")
    audit_path_t.write_bytes(genuine_t)

    # ========================================================
    # N-L3 - concurrent duplicate apply -> replay + corroboration.
    # ========================================================
    case_r, dir_r = make_manual_case("rp")
    principal_r, repo_r = make_principal_and_repo(case_r)
    prev_r = preview(case_r, principal_r, repo_r)
    conn_r = FakeJournalConn()

    def first_apply_completes_during_wait(_case_id):
        fac.apply_manual_fact(case_r, DOC, prev_r["input_digest"], principal=principal_r,
                              authz_repository=repo_r, conn_factory=lambda: conn_r)

    _on_acquire_hooks.append(first_apply_completes_during_wait)
    result_r, _ = apply(case_r, prev_r["input_digest"], principal_r, repo_r, conn=conn_r)
    check("N-L3a the waiting duplicate apply becomes a corroborated replay (replayed=True, 1 row, 1 audit)",
          result_r.replayed is True and len(conn_r.table) == 1 and len(list(reviews_of(dir_r).iterdir())) == 1
          and result_r.pending_sha256 == prev_r["pending_sha256"])

    case_r2, dir_r2 = make_manual_case("rq")
    principal_r2, repo_r2 = make_principal_and_repo(case_r2)
    prev_r2 = preview(case_r2, principal_r2, repo_r2)
    conn_r2 = FakeJournalConn()

    def first_apply_then_tamper(_case_id):
        fac.apply_manual_fact(case_r2, DOC, prev_r2["input_digest"], principal=principal_r2,
                              authz_repository=repo_r2, conn_factory=lambda: conn_r2)
        audit_path = sorted(reviews_of(dir_r2).iterdir())[0]
        record = json.loads(audit_path.read_bytes())
        record["channel"] = "tampered"
        audit_path.write_bytes(json.dumps(record).encode("utf-8"))

    _on_acquire_hooks.append(first_apply_then_tamper)
    collect(expect_raises(fac.ManualFactAuditBindingVerificationFailedError,
                          lambda: apply(case_r2, prev_r2["input_digest"], principal_r2, repo_r2, conn=conn_r2),
                          "N-L3b replay with a tampered audit -> ManualFactAuditBindingVerificationFailedError"))

    # ========================================================
    # F-N12 - canary: facade vs adapter formulas.
    # ========================================================
    digest = prev_d["input_digest"]
    check("F-N12a composite pre_revision: facade == adapter",
          fac.compute_pre_revision(digest, 3) == ada.candidate_pre_revision(digest, 3))
    rev = fac.compute_pre_revision(digest, 1)
    check("F-N12b pre_hash with pending present: facade == adapter",
          fac.compute_pre_hash(rev, pending_of(dir_d))
          == ada.candidate_pre_hash(rev, hashlib.sha256(pending_of(dir_d).read_bytes()).hexdigest()))
    check("F-N12c pre_hash with pending absent: facade == adapter",
          fac.compute_pre_hash(rev, pending_of(dir_d).parent / "absent.pending") == ada.candidate_pre_hash(rev, None))
    check("F-N12d version literals identical across facade and adapter",
          fac.REVISION_VERSION == ada._REVISION_VERSION and fac.SNAPSHOT_VERSION == ada._SNAPSHOT_VERSION
          and fac.CHANNEL == ada._CHANNEL == mfe.CHANNEL and fac.ACTION_FAMILY == mfe.ACTION_FAMILY)

    # ========================================================
    # Argument shapes (pre-I/O).
    # ========================================================
    for label, kwargs in (
        ("case_id with a separator", dict(case_id="a/b", document_id=DOC)),
        ("document_id '..'", dict(case_id=case1, document_id="..")),
        ("document_id with a colon", dict(case_id=case1, document_id="c:x")),
        ("blank document_id", dict(case_id=case1, document_id="")),
    ):
        expect_raises(fac.ManualFactArgumentError,
                      lambda kw=kwargs: fac.preview_manual_fact(kw["case_id"], kw["document_id"],
                                                                principal=principal1, authz_repository=repo1),
                      f"ARG {label} -> ManualFactArgumentError before any I/O")
    for label, digest_value, attempt_value in (("non-hex digest", "x" * 64, 1), ("uppercase digest", "A" * 64, 1),
                                               ("attempt 0", "0" * 64, 0), ("attempt True", "0" * 64, True)):
        expect_raises(fac.ManualFactArgumentError,
                      lambda d=digest_value, a=attempt_value: fac.apply_manual_fact(
                          case1, DOC, d, attempt=a, principal=principal1, authz_repository=repo1,
                          conn_factory=lambda: (_ for _ in ()).throw(AssertionError("conn opened"))),
                      f"ARG apply {label} -> ManualFactArgumentError, no connection opened")

    check("F-N13d zero poisoned-stub accesses during every preview/apply window", _poison_hits == [],
          f"{_poison_hits!r}")
    check("F-N13e zero socket.* audit events during every preview/apply window", _socket_events == [],
          f"{_socket_events!r}")
finally:
    _socket_armed[0] = False
    ml.acquire_case_lock_session = _original_acquire
    ml.release_lock_session = _original_release
    for _name, _mod in _saved_modules.items():
        if _mod is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _mod
    for link in list(_junction_links):
        try:
            if os.path.lexists(link):
                os.rmdir(link)
        except OSError as cleanup_error:
            print(f"CLEANUP WARNING: link {link}: {cleanup_error!r}")
    for case_dir in _created_case_dirs:
        try:
            if case_dir.exists():
                shutil.rmtree(case_dir)
        except OSError as cleanup_error:
            print(f"CLEANUP WARNING: case dir {case_dir}: {cleanup_error!r}")
    for outside in _outside_dirs:
        shutil.rmtree(outside, ignore_errors=True)

# ============================================================
# F-N8 (H-2) - error hygiene over every collected domain error (stubs
# restored first: _is_known_domain_error lazily imports other facades).
# ============================================================
import ui.cli_mutate as cli_mutate  # noqa: E402

check("F-N8a at least 25 domain errors were collected from the scenarios above",
      len(_collected_errors) >= 25, f"n={len(_collected_errors)}")
_cases_root_str = str(_paths.CASES_DIR)
for _error in _collected_errors:
    _text = str(_error)
    _label = type(_error).__name__
    check(f"F-N8b {_label} is an ApprovalUiError subclass", isinstance(_error, ApprovalUiError))
    check(f"F-N8c {_label} message carries no excerpt text, no input content, no absolute path",
          EXCERPT not in _text and "tebliğ edilmiştir" not in _text and _cases_root_str not in _text
          and str(REPO_ROOT) not in _text and "C:\\" not in _text, _text)
    check(f"F-N8d {_label} is a known CLI domain error", cli_mutate._is_known_domain_error(_error) is True)
_invariant = mfe.ManualFactPostWriteInvariantError("x")
check("F-N8e the post-write invariant is deliberately NOT an ApprovalUiError and NOT a known CLI domain error",
      not isinstance(_invariant, ApprovalUiError) and cli_mutate._is_known_domain_error(_invariant) is False)

check("FINAL: no junction residue remains", all(not os.path.lexists(link) for link in _junction_links))
check("FINAL: the real data/ tree is byte-for-byte IDENTICAL to the pre-test snapshot",
      snapshot_data_tree() == _data_tree_before_everything)

if _informational_skips:
    print(
        f"--- test_manual_fact_mutation_facade_isolated: {passed} passed, {failed} failed "
        f"({_informational_skips} informational SKIPPED line(s), NOT counted) ---"
    )
else:
    print(f"--- test_manual_fact_mutation_facade_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
