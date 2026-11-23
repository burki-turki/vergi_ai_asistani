# ============================================================
# T2 - BÜRO AKIŞI ONAY KAPISI: GERÇEK PostgreSQL ENTEGRASYON KANITI.
#
# GERÇEK OLANLAR: `ui.cli_mutate.main()` (gerçek CLI giriş noktası, argv ->
# exit kodu, değiştirilmeden; mevcut `test_cli_mutate_integration_postgres.py`
# kalıbıyla SÜREÇ İÇİNDEN çağrılır - alt süreç YOK, böylece resmî taramanın
# koruma sayaçlarıyla çakışan ek bir süreç/kanca kurulmaz), `ui.office_
# deadline_flow.RealChainBackend.approve_deadline()` (akışın GERÇEK onay
# yolu), `ui.services.cli_authz` + gerçek `iam.*` satırları, gerçek
# `mutation.mutation_journal`, gerçek `pg_advisory_lock`, gerçek
# `src/deadline_approval.py` yazıcısı ve `check_pending_promotion_contract`
# kapısı, işareti yazan GERÇEK `office_flow_records.create_owned_dir`.
#
# GERÇEK OLMAYAN: vaka ağacı - `data/cases/case_0001`'in (izlenen sentetik
# fikstür, YALNIZ OKUNUR) geçici bir dizine yeniden kimliklendirilmiş kopyaları;
# her `CASES_DIR` tutucusu geçici olarak oraya yönlendirilir. Deponun `data/`
# ağacı HİÇ yazılmaz (sonda bayt-bayt kanıtlanır). Gerçek veri/ağ/.env YOK.
#
#   P1  işaretli vakada `cli_mutate approval --row-key deadline --approve`
#       -> sıfırdan farklı çıkış + TEK temiz hata satırı; journal değişmez;
#       onaylı dosya yok; pending baytları aynı (kilit öncesi: sıfır
#       mutasyon bağlantısı).
#   P2  aynı vaka işaretsizken aynı komut başarılı (kontrol).
#   P3  akışın yolu (gerçek backend, koşu kimliği eşleşiyor) -> `completed`
#       satırı + onaylı süre dosyası; yanlış koşu kimliği önce reddedilir.
#   P4  P3'ten sonra aynı beklenen hash ile CLI "tekrarı" kilit öncesinde
#       reddedilir; journal değişmez.
#   P5  Adım 7 / Slice 2'nin sekiz güvencesi, ret için - hem kilit ÖNCESİ (P1)
#       hem kilit ALTINDA (işaret kilit beklenirken oluşur) ret.
#
# Çalıştırma: VERGI_TEST_PG_DSN=<db> python -m ui.tests.test_office_approval_gate_postgres
# ============================================================

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
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
skipped = 0
MODULE_NAME = "test_office_approval_gate_postgres"


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


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip("the entire T2 office-approval-gate real-PostgreSQL suite",
         "VERGI_TEST_PG_DSN is not set (no disposable, migrated database configured). NOT EXECUTED, not a pass")
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover - environment-dependent
    skip("the entire T2 office-approval-gate real-PostgreSQL suite",
         f"VERGI_TEST_PG_DSN is set but `import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass")
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                         # noqa: E402
import ui.office_deadline_flow as flow_module                              # noqa: E402
from ui.services import mutation_approval_facade as facade                 # noqa: E402
from ui.services import mutation_lock as _mutation_lock                    # noqa: E402
from ui.services import office_flow_records as records                     # noqa: E402
from ui.services import paths as _paths                                    # noqa: E402
from ui.services import approval_registry as _approval_registry            # noqa: E402,F401
from ui.services.common import sha256_file                                 # noqa: E402

import deadline_approval                                                   # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, action_family, state, actor_user_id, target_ref, idempotency_key, observed_post_hash "
                "FROM mutation.mutation_journal WHERE resource_key = %s ORDER BY id", (resource_key,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def journal_total():
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM mutation.mutation_journal")
            return cur.fetchone()[0]
    finally:
        conn.close()


def unresolved_rows(resource_key):
    """`mutation_coordinator`'ın kaynak kapısının baktığı durumlar."""
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM mutation.mutation_journal WHERE resource_key = %s "
                "AND state IN ('prepared', 'executing', 'reconciliation_required')", (resource_key,),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


# ----------------------------------------------------------------
# Preflight.
# ----------------------------------------------------------------

_pre = pg_connect()
try:
    with _pre.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('iam.users'), to_regclass('mutation.mutation_resources'), "
            "to_regclass('mutation.mutation_journal')"
        )
        _row = cur.fetchone()
    check("preflight: iam.users / mutation.mutation_resources / mutation.mutation_journal exist (migrations applied)", all(_row))
finally:
    _pre.close()
if failed:
    print("Preflight failed - refusing to run against a half-migrated database.")
    summarize_and_exit()

ACTOR = 2301
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        cur.execute(
            "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
            "ON CONFLICT (id) DO UPDATE SET disabled = FALSE", (ACTOR, "t2-gate-pg-actor (synthetic)"),
        )
        cur.execute("SELECT setval(pg_get_serial_sequence('iam.users', 'id'), GREATEST((SELECT max(id) FROM iam.users), 1))")
finally:
    _seed.close()


def seed_assignment(user_id, case_id, role="lawyer"):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO iam.case_assignments (user_id, case_id, role) VALUES (%s, %s, %s)",
                        (user_id, case_id, role))
    finally:
        conn.close()


# ----------------------------------------------------------------
# CASES_DIR yönlendirmesi (mevcut PG testlerinin deseni).
# ----------------------------------------------------------------

RUN_TOKEN = uuid.uuid4().hex[:8]
_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))


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


def discover_cases_dir_holders():
    holders = []
    for module in list(sys.modules.values()):
        if getattr(module, "__file__", None) is None:
            continue
        candidate = getattr(module, "CASES_DIR", None)
        if candidate is None:
            continue
        try:
            if Path(os.path.realpath(str(candidate))) == _REAL_CASES_ROOT:
                holders.append(module)
        except Exception:
            continue
    return holders


_real_data_before = snapshot_real_data_tree()
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_t2_gate_pg_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
_original_cases_dirs = [(m, m.CASES_DIR) for m in _cases_dir_holders]
check(
    "the CASES_DIR redirect sweep found ui.services.paths AND deadline_approval (the authz choke point and the gated writer)",
    {"ui.services.paths", "deadline_approval"} <= {getattr(m, "__name__", "") for m in _cases_dir_holders},
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES


def make_deadline_case(base_name, *, marker_run_id=None):
    """`case_0001`'in yeniden kimliklendirilmiş kopyası (mevcut CLI PG testinin
    `make_deadline_case`'iyle aynı mekanik). `marker_run_id` verilirse vaka
    dizini ÖNCE üretimin kendi yazıcısıyla (`create_owned_dir`, kind=case_dir)
    açılır - akışın `seed_case`'indeki gibi işaret dizindeki İLK dosyadır."""
    case_id = f"{base_name}_{RUN_TOKEN}"
    destination = _TMP_CASES / case_id
    if marker_run_id is not None:
        records.create_owned_dir(destination, run_id=marker_run_id, kind="case_dir")
        shutil.copytree(_REAL_CASES_ROOT / "case_0001", destination, dirs_exist_ok=True)
    else:
        shutil.copytree(_REAL_CASES_ROOT / "case_0001", destination)
    for path in destination.rglob("*"):
        if not path.is_file() or path.name == records.OWNER_MARKER_NAME:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "case_0001" in text:
            path.write_text(text.replace("case_0001", case_id), encoding="utf-8")
    for path in sorted(destination.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if "case_0001" in path.name:
            path.rename(path.with_name(path.name.replace("case_0001", case_id)))

    pending_path = deadline_approval.get_pending_path(case_id)
    canonical_path = deadline_approval.get_canonical_path(case_id)
    # ADIM 7 / SLICE 2 mekanik fikstür uyumu (CLI PG testindekiyle aynı): kopyalanan
    # pending iki canonical stopping alanını taşımaz; burada ekleniyor.
    _doc = json.loads(pending_path.read_text(encoding="utf-8"))
    for _record in _doc.get("deadlines", []):
        _record.setdefault("stopping_event_status", "unknown")
        _record.setdefault("stopping_event_attestation_ref", None)
    pending_path.write_text(json.dumps(_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if canonical_path.exists():
        canonical_path.unlink()
    reviews_dir = deadline_approval.get_reviews_dir(case_id)
    if reviews_dir.is_dir():
        shutil.rmtree(reviews_dir)
    seed_assignment(ACTOR, case_id)
    return {
        "case_id": case_id, "case_dir": destination,
        "resource_key": _mutation_lock.case_resource_key(case_id),
        "pending_path": pending_path, "canonical_path": canonical_path,
        "reviews_dir": reviews_dir, "expected_hash": sha256_file(pending_path),
    }


def tree_snapshot(root, *, exclude=()):
    out = {}
    for path in Path(root).rglob("*"):
        if path.name in exclude:
            continue
        rel = str(path.relative_to(root))
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "<dir>"
    return out


MUTATION_CONN_CALLS = {"n": 0}
ON_MUTATION_CONN = {"fn": None}


def counting_mutation_conn():
    MUTATION_CONN_CALLS["n"] += 1
    hook = ON_MUTATION_CONN["fn"]
    if hook is not None:
        ON_MUTATION_CONN["fn"] = None
        hook()
    return pg_connect()


def run_cli(argv):
    """Gerçek `ui.cli_mutate.main()`; authz ve mutasyon bağlantıları gerçek
    PostgreSQL (mevcut CLI PG testinin `run_cli` kalıbı + sayaçlı fabrika)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    MUTATION_CONN_CALLS["n"] = 0
    code = cli_mutate.main(argv, authz_conn_factory=pg_connect, mutation_conn_factory=counting_mutation_conn,
                           stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def approve_argv(fx):
    return ["approval", "--case", fx["case_id"], "--row-key", "deadline", "--actor-user-id", str(ACTOR),
            "--approve", "--expected-hash", fx["expected_hash"]]


EXPECTED_ERROR_LINE = f"ERROR: OfficeFlowApprovalRequiredError: {facade.OFFICE_FLOW_APPROVAL_REQUIRED_MESSAGE}"

WRITER_CALLS = {"n": 0}
_original_run_approve = deadline_approval.run_approve


def _counting_run_approve(*args, **kwargs):
    WRITER_CALLS["n"] += 1
    return _original_run_approve(*args, **kwargs)


def real_backend():
    return flow_module.RealChainBackend(
        actor_user_id=ACTOR,
        authz_conn_factory=lambda: psycopg.connect(dbname=PG_DB),
        mutation_conn_factory=lambda: psycopg.connect(dbname=PG_DB, autocommit=True),
        report_conn_factory=lambda: psycopg.connect(dbname=PG_DB),
    )


def eight_guarantees(tag, fx, *, tree_before, writer_before, rows_before, exclude=()):
    """Adım 7 / Slice 2'nin sekiz güvencesinin ilk yedisi (sekizincisi -
    'ret sonrası geçerli onay bloke olmaz' - çağıranda ayrı kanıtlanır)."""
    rows = journal_rows(fx["resource_key"])
    check(f"{tag} [1/8]: ZERO new journal rows for this case (no 'prepared')",
          rows == rows_before and not any(r["state"] == "prepared" for r in rows), f"rows={rows}")
    check(f"{tag} [2/8]: the REAL deadline_approval writer was NEVER invoked", WRITER_CALLS["n"] == writer_before)
    check(f"{tag} [3/8]: no canonical deadline.json was written", not fx["canonical_path"].exists())
    after = tree_snapshot(fx["case_dir"], exclude=exclude)
    added = sorted(set(after) - set(tree_before))
    changed = sorted(k for k in set(after) & set(tree_before) if after[k] != tree_before[k])
    removed = sorted(set(tree_before) - set(after))
    check(f"{tag} [4/8]: no history/backup file and no other new/changed/removed file anywhere in the case tree",
          added == [] and changed == [] and removed == [], f"added={added} changed={changed} removed={removed}")
    check(f"{tag} [5/8]: no approval audit record (reviews/ absent)", not fx["reviews_dir"].exists())
    check(f"{tag} [6/8]: the pending file's bytes are unchanged", sha256_file(fx["pending_path"]) == fx["expected_hash"])
    check(f"{tag} [7/8]: no reconciliation_required / unresolved row -> the resource is NOT gated",
          unresolved_rows(fx["resource_key"]) == 0)


try:
    deadline_approval.run_approve = _counting_run_approve

    # ============================================================
    # P1 - işaretli vakada CLI onayı reddedilir (kilit ÖNCESİ).
    # ============================================================
    RID1 = uuid.uuid4().hex
    fx1 = make_deadline_case("t2gate_p1", marker_run_id=RID1)
    check("P1 fixture: the marker is the production writer's exact bytes, and the case otherwise mirrors case_0001",
          (fx1["case_dir"] / records.OWNER_MARKER_NAME).read_bytes()
          == records.canonical_bytes({"kayit_surumu": 1, "kos": RID1, "tur": "case_dir"})
          and fx1["pending_path"].is_file())

    code_pv, out_pv, err_pv = run_cli(["approval", "--case", fx1["case_id"], "--row-key", "deadline",
                                       "--actor-user-id", str(ACTOR)])
    check("P1 context: the read-only PREVIEW still works on a marked case (exit 0, prints the pending hash)",
          code_pv == cli_mutate.EXIT_OK and fx1["expected_hash"] in out_pv, f"err={err_pv}")

    tree1 = tree_snapshot(fx1["case_dir"])
    total1 = journal_total()
    w1 = WRITER_CALLS["n"]
    code1, out1, err1 = run_cli(approve_argv(fx1))
    check("P1: marked case -> `cli_mutate approval --row-key deadline --approve --expected-hash ...` exits NON-ZERO "
          "(EXIT_DOMAIN_ERROR)", code1 == cli_mutate.EXIT_DOMAIN_ERROR, f"code={code1} err={err1!r}")
    check("P1: exactly ONE clean error line on stderr (no traceback), nothing on stdout",
          out1 == "" and err1.count("\n") == 1 and err1.strip() == EXPECTED_ERROR_LINE and "Traceback" not in err1,
          f"err={err1!r}")
    check("P1: the error line carries neither the run id nor the case id nor a path",
          RID1 not in err1 and fx1["case_id"] not in err1 and str(_TMP_ROOT) not in err1)
    check("P1: rejected PRE-LOCK - the mutation (journal/lock) connection factory was NEVER called",
          MUTATION_CONN_CALLS["n"] == 0, str(MUTATION_CONN_CALLS["n"]))
    check("P1: the journal's TOTAL row count did not change", journal_total() == total1)
    eight_guarantees("P5a (pre-lock rejection, P1)", fx1, tree_before=tree1, writer_before=w1, rows_before=[])

    # ============================================================
    # P2 - aynı vaka işaretsizken aynı komut başarılı (kontrol) +
    # P5a [8/8]: ret sonrası geçerli onay bloke değil.
    # ============================================================
    (fx1["case_dir"] / records.OWNER_MARKER_NAME).unlink()
    code2, out2, err2 = run_cli(approve_argv(fx1))
    rows2 = journal_rows(fx1["resource_key"])
    check("P2 (control): the SAME case with the marker removed -> the SAME command succeeds (exit 0), canonical written",
          code2 == cli_mutate.EXIT_OK and fx1["canonical_path"].exists(), f"code={code2} err={err2!r}")
    check("P2 / P5a [8/8]: exactly one 'completed' approval.deadline row - the earlier rejection left nothing that blocks "
          "a later valid approval", len(rows2) == 1 and rows2[0]["state"] == "completed"
          and rows2[0]["action_family"] == "approval.deadline" and WRITER_CALLS["n"] == w1 + 1, f"rows={rows2}")

    # ============================================================
    # P3 - akışın gerçek onay yolu (RealChainBackend, koşu kimliği eşleşiyor).
    # ============================================================
    RID3 = uuid.uuid4().hex
    fx3 = make_deadline_case("t2gate_p3", marker_run_id=RID3)
    backend3 = real_backend()
    try:
        w3 = WRITER_CALLS["n"]
        tree3 = tree_snapshot(fx3["case_dir"])
        wrong_error = None
        try:
            backend3.approve_deadline(fx3["case_id"], expected_pending_sha=fx3["expected_hash"],
                                      office_flow_run_id=uuid.uuid4().hex)
        except Exception as exc:  # noqa: BLE001
            wrong_error = exc
        check("P3 (negative): the REAL flow backend with a WRONG run id -> OfficeFlowApprovalRequiredError, "
              "zero journal rows, writer not called",
              isinstance(wrong_error, facade.OfficeFlowApprovalRequiredError) and journal_rows(fx3["resource_key"]) == []
              and WRITER_CALLS["n"] == w3, repr(wrong_error))
        check("P3 (negative): ... and the case tree is untouched", tree_snapshot(fx3["case_dir"]) == tree3)

        p3_error = None
        try:
            backend3.approve_deadline(fx3["case_id"], expected_pending_sha=fx3["expected_hash"], office_flow_run_id=RID3)
        except Exception as exc:  # noqa: BLE001 - adlı FAIL olarak raporlanır, çökme değil
            p3_error = exc
        rows3 = journal_rows(fx3["resource_key"])
        check("P3: the REAL flow backend with the MATCHING run id -> no error and exactly one 'completed' approval.deadline row",
              p3_error is None and len(rows3) == 1 and rows3[0]["state"] == "completed"
              and rows3[0]["action_family"] == "approval.deadline" and rows3[0]["actor_user_id"] == ACTOR,
              f"error={p3_error!r} rows={rows3}")
        check("P3: the approved canonical deadline file exists, its hash is the journal's observed_post_hash, writer once",
              fx3["canonical_path"].exists() and rows3[0]["observed_post_hash"] == sha256_file(fx3["canonical_path"])
              and WRITER_CALLS["n"] == w3 + 1)
        check("P3: the run id is NOT part of the journal row (identity unchanged)", RID3 not in repr(rows3))
    finally:
        backend3.close()

    # ============================================================
    # P4 - P3 sonrası CLI "tekrarı" kilit öncesinde reddedilir.
    # ============================================================
    canon3 = sha256_file(fx3["canonical_path"])
    total4 = journal_total()
    w4 = WRITER_CALLS["n"]
    code4, out4, err4 = run_cli(approve_argv(fx3))
    check("P4: after the flow's approval, a CLI call with the SAME expected hash (would be a safe replay) -> exit "
          "NON-ZERO with the one clean error line", code4 == cli_mutate.EXIT_DOMAIN_ERROR and out4 == ""
          and err4.strip() == EXPECTED_ERROR_LINE, f"code={code4} err={err4!r}")
    check("P4: rejected PRE-LOCK (zero mutation-connection calls); the journal is unchanged (still exactly 1 row, "
          "total count unchanged); writer not called; canonical bytes unchanged",
          MUTATION_CONN_CALLS["n"] == 0 and len(journal_rows(fx3["resource_key"])) == 1 and journal_total() == total4
          and WRITER_CALLS["n"] == w4 and sha256_file(fx3["canonical_path"]) == canon3)

    # ============================================================
    # P5b - KİLİT ALTINDA ret: işaret, kilit öncesi kontrolden SONRA (mutasyon
    # bağlantısı açılırken) oluşur. Sekiz güvence + sonra akışın geçerli onayı.
    # ============================================================
    fx5 = make_deadline_case("t2gate_p5")
    RID5 = uuid.uuid4().hex
    tree5 = tree_snapshot(fx5["case_dir"])
    w5 = WRITER_CALLS["n"]
    ON_MUTATION_CONN["fn"] = lambda: records.write_new_file(
        fx5["case_dir"] / records.OWNER_MARKER_NAME,
        records.canonical_bytes({"kayit_surumu": 1, "kos": RID5, "tur": "case_dir"}),
    )
    code5, out5, err5 = run_cli(approve_argv(fx5))
    check("P5b: marker appears AFTER the pre-lock check (while the mutation connection opens) -> rejected UNDER the "
          "real advisory lock: exit NON-ZERO, one clean error line, the mutation connection WAS opened (exactly once)",
          code5 == cli_mutate.EXIT_DOMAIN_ERROR and err5.strip() == EXPECTED_ERROR_LINE and MUTATION_CONN_CALLS["n"] == 1,
          f"code={code5} calls={MUTATION_CONN_CALLS['n']} err={err5!r}")
    eight_guarantees("P5b (under-lock rejection)", fx5, tree_before=tree5, writer_before=w5, rows_before=[],
                     exclude=(records.OWNER_MARKER_NAME,))
    backend5 = real_backend()
    p5_error = None
    try:
        backend5.approve_deadline(fx5["case_id"], expected_pending_sha=fx5["expected_hash"], office_flow_run_id=RID5)
    except Exception as exc:  # noqa: BLE001 - adlı FAIL olarak raporlanır, çökme değil
        p5_error = exc
    finally:
        backend5.close()
    rows5 = journal_rows(fx5["resource_key"])
    check("P5b [8/8]: after the under-lock rejection, the flow's VALID approval (matching run id) is NOT blocked -> no "
          "error, one 'completed' row, canonical written", p5_error is None and len(rows5) == 1
          and rows5[0]["state"] == "completed" and fx5["canonical_path"].exists(), f"error={p5_error!r} rows={rows5}")

finally:
    deadline_approval.run_approve = _original_run_approve
    for _m, _original in _original_cases_dirs:
        _m.CASES_DIR = _original
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

check("cleanup: writer spy and every CASES_DIR redirect restored",
      deadline_approval.run_approve is _original_run_approve and all(m.CASES_DIR == o for m, o in _original_cases_dirs))
check("cleanup: this test's temp tree was removed", not _TMP_ROOT.exists())
check("this repository's REAL data/ tree is byte-for-byte UNCHANGED by this suite", snapshot_real_data_tree() == _real_data_before)

summarize_and_exit()
