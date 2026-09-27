# ============================================================
# FACT VERIFICATION WORKFLOW - REAL, END-TO-END PostgreSQL INTEGRATION
# PROOF for the `verification.fact` mutation path
# (ui/services/fact_verification_mutation_facade.py +
# fact_verification_mutation_adapters.py + the ui.cli_mutate
# `verification` subcommand + ui/reconciliation_operator.py).
#
# WHAT IS REAL HERE: `ui.cli_mutate.main()` itself, `ui.services.
# cli_authz.CliActorAuthzRepository` against REAL iam rows, the real
# `mutation.mutation_journal`, real `pg_advisory_lock` session locking
# (observed via PostgreSQL's OWN pg_locks view), the REAL
# `src/fact_verification.py` writer, and the REAL merged reconciliation
# registry (`ui.reconciliation_operator._default_registry_factory()` -
# 50 routing keys as of this workflow).
#
# WHAT IS NOT REAL: the case tree (re-identified copies of
# data/cases/case_0001 under a fresh tempdir via a CASES_DIR redirect
# sweep - the repository's own data/ tree is NEVER written, proven
# byte-for-byte at the end).
#
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_fact_verification_mutation_integration_postgres.py
# ============================================================

import io
import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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
    print(
        f"--- test_fact_verification_mutation_integration_postgres: {passed} passed, "
        f"{failed} failed, {skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip(
        "the entire real-PostgreSQL fact-verification integration suite",
        "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip(
        "the entire real-PostgreSQL fact-verification integration suite",
        f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                              # noqa: E402
import ui.reconciliation_operator as op                                        # noqa: E402
from ui.services import authz as _authz                                        # noqa: E402
from ui.services import cli_authz as _cli_authz                                # noqa: E402
from ui.services import mutation_coordinator as mc                             # noqa: E402
from ui.services import mutation_lock as _mutation_lock                        # noqa: E402
from ui.services import fact_verification_mutation_facade as fv_facade         # noqa: E402
from ui.services import fact_verification_mutation_adapters as fv_adapters     # noqa: E402
from ui.services import paths as _paths                                        # noqa: E402
from ui.services.common import sha256_file, StaleViewError                     # noqa: E402

import fact_verification as fv                                                  # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, resource_key, action_family, actor_user_id, target_ref, target_state, "
                "state, pre_hash, pre_revision, observed_post_hash, resolution_code, "
                "reconciled_by_actor_type, reconciled_by_actor_ref, executing_at "
                "FROM mutation.mutation_journal WHERE resource_key = %s ORDER BY id",
                (resource_key,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _count_advisory_locks(advisory_lock_id, *, granted):
    if advisory_lock_id is None:
        return 0
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND classid = %s AND objid = %s AND granted = %s",
                ((advisory_lock_id >> 32) & 0xFFFFFFFF, advisory_lock_id & 0xFFFFFFFF, granted),
            )
            (count,) = cur.fetchone()
            return count
    finally:
        conn.close()


def wait_for_lock_waiter(advisory_lock_id, *, timeout_seconds=30.0, poll_seconds=0.1):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _count_advisory_locks(advisory_lock_id, granted=False) > 0:
            return True
        time.sleep(poll_seconds)
    return False


def wait_for_lock_waiters(advisory_lock_id, count, *, timeout_seconds=30.0, poll_seconds=0.1):
    """P11 (two-different-facts concurrency): waits until AT LEAST
    `count` genuinely-waiting advisory-lock requests are observed via
    PostgreSQL's own pg_locks view (granted=False rows)."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _count_advisory_locks(advisory_lock_id, granted=False) >= count:
            return True
        time.sleep(poll_seconds)
    return False


# ----------------------------------------------------------------
# Preflight.
# ----------------------------------------------------------------

_preflight = pg_connect()
try:
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('iam.users'), to_regclass('mutation.mutation_resources'), "
            "to_regclass('mutation.mutation_journal')"
        )
        row = cur.fetchone()
    check("preflight: iam + mutation schemas all exist (migrations 0001-0005)", all(row))
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run against a half-migrated database.")
    summarize_and_exit()

_ACTORS = {"lawyer": 401, "analyst": 402, "lawyer2": 403}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"fact-verification-actor-{user_id}"),
            )
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('iam.users', 'id'), "
            "GREATEST((SELECT max(id) FROM iam.users), 1))"
        )
finally:
    _seed.close()


def seed_assignment(user_id, case_id, role):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO iam.case_assignments (user_id, case_id, role) VALUES (%s, %s, %s)",
                (user_id, case_id, role),
            )
    finally:
        conn.close()


# ----------------------------------------------------------------
# Case fixtures under a fresh tempdir; CASES_DIR redirect sweep.
# ----------------------------------------------------------------

_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))
REAL_CASE_0001 = REPO_ROOT / "data" / "cases" / "case_0001"


def snapshot_real_data_tree():
    real_data_dir = REPO_ROOT / "data"
    out = {}
    for path in real_data_dir.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(real_data_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(real_data_dir))] = "<unreadable>"
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


# CONTINUATION TURN (Fable FINAL §O completion, categories 2/3):
# `ui.cli_mutate`'s `generation`/`promotion`/`approval` subcommands
# LAZILY import these engine/validator/approval modules from INSIDE
# their own dispatch functions - each carries its OWN, independent
# module-level `CASES_DIR`. They must be imported HERE, BEFORE the
# redirect sweep below runs, or the real `generation.timeline`/
# `promotion.timeline`/`generation.deadline`/`approval.deadline` CLI
# calls used later in this file (P9/P10 real production-chain proofs)
# would resolve against the REAL `data/cases/` tree instead of this
# file's own redirected tempdir.
import timeline_engine as _pg_timeline_engine                                   # noqa: E402,F401
import timeline_validator as _pg_timeline_validator                             # noqa: E402,F401
import timeline_approval as _pg_timeline_approval                               # noqa: E402,F401
import fact_approval as _pg_fact_approval                                       # noqa: E402,F401
import deadline_engine as _pg_deadline_engine                                   # noqa: E402,F401
import deadline_approval as _pg_deadline_approval                               # noqa: E402,F401
import deadline_validator as _pg_deadline_validator                             # noqa: E402,F401
import deadline_calculator as _pg_deadline_calculator                           # noqa: E402,F401
import holiday_calendar_validator as _pg_holiday_calendar_validator             # noqa: E402,F401
from ui.services import promotion_mutation_facade as _pg_promotion_facade       # noqa: E402,F401
from ui.services import generation_mutation_facade as _pg_generation_facade     # noqa: E402,F401
import deadline_rule_selection_policy as _pg_deadline_rule_selection_policy     # noqa: E402,F401

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_fv_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
check(
    "the CASES_DIR redirect sweep found ui.services.paths, fact_verification, AND the "
    "timeline/deadline engine+validator+approval modules needed for the real generation.timeline/"
    "promotion.timeline/generation.deadline/approval.deadline production chain (P9/P10 below)",
    all(
        any(getattr(m, "__name__", "") == name for m in _cases_dir_holders)
        for name in (
            "ui.services.paths", "fact_verification", "timeline_engine", "timeline_validator",
            "timeline_approval", "fact_approval", "deadline_engine", "deadline_approval",
            "deadline_validator",
        )
    ),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
_original_cases_dirs = [(m, m.CASES_DIR) for m in _cases_dir_holders]
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

# `deadline_rule_selection_policy.py` resolves case-scoped document
# types via its OWN `DATA_DIR` (never a `CASES_DIR` attribute of its
# own) - `discover_cases_dir_holders()` cannot catch this by its
# `CASES_DIR`-only scan, so it is redirected explicitly here (restored
# in `finally`, alongside every other redirected module).
_original_deadline_rule_policy_data_dir = _pg_deadline_rule_selection_policy.DATA_DIR
_pg_deadline_rule_selection_policy.DATA_DIR = _TMP_ROOT / "data"

# PILOT READINESS ADIM 5 - `--calendar-complete` elle beyan bayrağı
# TAMAMEN KALDIRILDI (K4); `generation.deadline` artık HER ZAMAN
# `deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH`'ten resmi tatil
# takvimini okur/doğrular. P10's calculated_deadline='2026-03-12'
# kanıtını (`--calendar-complete` bağımlılığı kalkmış olarak) korumak
# için, bu modülün TEK deadline-row-key kullanıcısı olan P10'un süresi
# boyunca bu sabit, GERÇEK production dosyasına DEĞİL (Prensip 18 -
# test fixture ile production canonical data KARIŞTIRILMAZ), tempdir-
# izoleli, sentetik, 2026 için `verified:true`+`holidays: []` (sıfır
# tatil - kaydırma OLMADAN) bir takvime yönlendirilir - testin zaten
# `CASES_DIR`/`DATA_DIR` için kullandığı AYNI monkeypatch seam'i
# (`deadline_calculator.py:58` `deadline_engine.py`'nin bare-name DEĞİL
# dotted-attribute erişimiyle bu patch'i her zaman görür - bkz.
# `deadline_engine.py`'nin `import deadline_calculator` satırı).
# Restore edilir `finally`'de, diğer her redirect ile birlikte.
_original_default_holiday_calendar_path = _pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH
_p10_synthetic_holiday_calendar_dir = _TMP_ROOT / "p10_holiday_calendar"
_p10_synthetic_holiday_calendar_dir.mkdir(parents=True, exist_ok=True)
_p10_synthetic_holiday_calendar_path = _p10_synthetic_holiday_calendar_dir / "holiday_calendar.json"
_p10_synthetic_holiday_calendar_doc = {
    "schema_version": 1,
    "calendar_id": "tr_official_holiday_calendar_v1",
    "calendar_version": 1,
    "effective_from": "2026-01-01",
    "jurisdiction": "TR",
    "weekend_policy": {"non_working_weekdays": [5, 6], "notes": None},
    "half_day_policy": "not_decided",
    "years": [
        {
            "year": 2026,
            "verified": True,
            "verification_ref": "p10_test_only_synthetic_verification_ref",
            "source_refs": [
                {"source_kind": "test_fixture", "citation": "P10 test-only synthetic calendar - NOT a real legal source.", "url": None},
            ],
            "holidays": [],
        },
    ],
    "governance": {"change_approval": "test-only", "verification_authority": "test-only", "notes": None},
    "notes": "P10 test-only synthetic calendar (Prensip 18) - never written to the real data/ tree.",
}
# PILOT READINESS ADIM 6: verified=true bir yıl artık takvimin kendi verifications[]
# dizisindeki bir avukat doğrulama kaydına çözülmek ZORUNDADIR (fail-closed);
# bu sentetik fixture yine sentetik (Prensip 18) bir kayda bağlanır.
_pg_holiday_calendar_validator.attach_fixture_verification(
    _p10_synthetic_holiday_calendar_doc, seed="p10_test_only_synthetic"
)
_p10_synthetic_holiday_calendar_check = _pg_holiday_calendar_validator.validate_holiday_calendar(
    calendar=_p10_synthetic_holiday_calendar_doc,
)
if not _p10_synthetic_holiday_calendar_check["valid"]:
    raise AssertionError(
        f"P10 synthetic holiday calendar fixture is itself invalid: {_p10_synthetic_holiday_calendar_check['errors']!r}"
    )
with open(_p10_synthetic_holiday_calendar_path, "w", encoding="utf-8") as _p10_cal_file:
    json.dump(_p10_synthetic_holiday_calendar_doc, _p10_cal_file, ensure_ascii=False, indent=2)
_pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH = _p10_synthetic_holiday_calendar_path

_real_data_before = snapshot_real_data_tree()

RUN_TOKEN = uuid.uuid4().hex[:8]
FACT_DOC = "dava_dilekcesi_001"


def make_case(tag):
    case_id = f"fvpg{RUN_TOKEN}{tag}"
    dst = _TMP_CASES / case_id
    shutil.copytree(REAL_CASE_0001, dst)
    for path in dst.rglob("*"):
        if path.is_file() and (path.suffix in (".json", ".pending", ".bak") or path.name.endswith(".json.pending")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "case_0001" in text:
                path.write_text(text.replace("case_0001", case_id), encoding="utf-8")
    return case_id, dst


def canonical_path_for(case_dir, document_id=FACT_DOC):
    return case_dir / "documents" / document_id / "extractions" / "facts.json"


def authz_conn_factory():
    return psycopg.connect(dbname=PG_DB)


def mutation_conn_factory():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def run_cli(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_mutate.main(
        argv, authz_conn_factory=authz_conn_factory, mutation_conn_factory=mutation_conn_factory,
        stdout=stdout, stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def make_pg_principal_and_repo(actor_user_id):
    conn = authz_conn_factory()
    principal = _cli_authz.build_cli_principal(conn, actor_user_id)
    repo = _cli_authz.CliActorAuthzRepository(conn)
    return principal, repo, conn


def _parse_kv(out, key):
    """CONTINUATION TURN: extracts a `key=value` line from real CLI
    stdout (as printed by `ui.cli_mutate`'s own `_run_generation`/
    `_run_promotion` formatters) - fails loudly (never silently) if the
    key is genuinely absent."""
    prefix = key + "="
    for line in out.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    raise AssertionError(f"key {key!r} not found in real CLI output: {out!r}")


def make_single_fact_deadline_case(tag):
    """CONTINUATION TURN (P10, deadline blocked->calculated). Builds a
    REAL, trimmed-down copy of case_0001 containing EXACTLY one
    document (`ihbarname_001`, document_type='vergi_ceza_ihbarnamesi' -
    the ONLY document_type the real, active
    `data/deadline_rules/deadline_rules.json` rule applies to) and
    EXACTLY one fact (the REAL notification-date fact,
    `fact_ihbarname_001_llm_v1_2_1_20260901_122652_008`, 'Tebliğ
    Tarihi' 2026-02-10 - the SAME anchor date CLAUDE.md's own worked
    example and `deadline_calculator.py`'s own embedded self-test T02
    use) - this avoids Timeline Consolidation Policy's multi-fact
    event merging entirely, so the resulting anchor event's
    source_fact_ids is unambiguously a SINGLE fact. `dava_dilekcesi_001`
    and `vir_001` (and every fact/event that depended on them) are
    removed outright, never merely hidden."""
    case_id = f"fvpg{RUN_TOKEN}{tag}"
    dst = _TMP_CASES / case_id
    shutil.copytree(REAL_CASE_0001, dst)
    for path in dst.rglob("*"):
        if path.is_file() and (path.suffix in (".json", ".pending", ".bak") or path.name.endswith(".json.pending")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "case_0001" in text:
                path.write_text(text.replace("case_0001", case_id), encoding="utf-8")

    for other_doc in ("dava_dilekcesi_001", "vir_001"):
        other_dir = dst / "documents" / other_doc
        if other_dir.exists():
            shutil.rmtree(other_dir)

    facts_path = dst / "documents" / "ihbarname_001" / "extractions" / "facts.json"
    extraction = json.loads(facts_path.read_text(encoding="utf-8"))
    keep_fact_id = "fact_ihbarname_001_llm_v1_2_1_20260901_122652_008"
    trimmed_facts = [f for f in extraction["facts"] if f["fact_id"] == keep_fact_id]
    if len(trimmed_facts) != 1:
        raise AssertionError(
            f"expected exactly 1 kept fact ({keep_fact_id!r}) in the real ihbarname_001 fixture, "
            f"got {[f['fact_id'] for f in extraction['facts']]!r}"
        )
    extraction["facts"] = trimmed_facts
    facts_path.write_text(json.dumps(extraction, ensure_ascii=False, indent=2), encoding="utf-8")

    case_path = dst / "case.json"
    case_data = json.loads(case_path.read_text(encoding="utf-8"))
    case_data["case_document_refs"] = [
        r for r in case_data.get("case_document_refs", []) if r.get("document_id") == "ihbarname_001"
    ]
    case_path.write_text(json.dumps(case_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return case_id, dst


try:
    # ============================================================
    # P1 - same-case two-connection lock serialization (pg_locks proof).
    # ============================================================
    case_p1, dir_p1 = make_case("p1")
    seed_assignment(_ACTORS["lawyer"], case_p1, "lawyer")
    canonical_p1 = canonical_path_for(dir_p1)
    extraction_p1 = json.loads(canonical_p1.read_bytes().decode("utf-8"))
    fact_id_p1 = extraction_p1["facts"][0]["fact_id"]
    canonical_sha_p1 = hashlib.sha256(canonical_p1.read_bytes()).hexdigest()

    holder_conn = mutation_conn_factory()
    holder_lock_id = _mutation_lock.acquire_case_lock_session(holder_conn, case_p1)
    check("P1a holder connection genuinely holds the case advisory lock (pg_locks granted=True)",
          _count_advisory_locks(holder_lock_id, granted=True) >= 1)

    blocked_result = {}

    def run_blocked_verification():
        principal, repo, conn = make_pg_principal_and_repo(_ACTORS["lawyer"])
        try:
            result = fv_facade.apply_verification_mutation(
                case_p1, FACT_DOC, fact_id_p1, canonical_sha_p1, "verified",
                evidence_document_id=extraction_p1["source_document_id"],
                principal=principal, authz_repository=repo, conn_factory=mutation_conn_factory,
            )
            blocked_result["result"] = result
        except Exception as error:  # pragma: no cover - surfaced via checks
            blocked_result["error"] = error
        finally:
            conn.close()

    worker = threading.Thread(target=run_blocked_verification, daemon=True)
    worker.start()
    check("P1b pg_locks reports a genuinely WAITING advisory-lock request while the holder holds",
          wait_for_lock_waiter(holder_lock_id))
    check("P1c the verification thread is still blocked (no result yet)",
          worker.is_alive() and "result" not in blocked_result and "error" not in blocked_result,
          f"{blocked_result!r}")
    _mutation_lock.release_lock_session(holder_conn, holder_lock_id)
    holder_conn.close()
    worker.join(timeout=120)
    check(
        "P1d after release the blocked verification completes for real (journal completed, "
        "canonical fact state changed)",
        "result" in blocked_result
        and blocked_result["result"].replayed is False
        and journal_rows(f"case:{case_p1}")[0]["state"] == "completed"
        and fv.find_fact(
            json.loads(canonical_p1.read_bytes().decode("utf-8")), fact_id_p1
        )["verification_state"] == "verified",
        f"{blocked_result!r}",
    )

    # ============================================================
    # P2 - fresh apply END-TO-END через the real CLI (preview -> apply).
    # ============================================================
    case_p2, dir_p2 = make_case("p2")
    seed_assignment(_ACTORS["lawyer"], case_p2, "lawyer")
    canonical_p2 = canonical_path_for(dir_p2)
    extraction_p2 = json.loads(canonical_p2.read_bytes().decode("utf-8"))
    fact_id_p2 = extraction_p2["facts"][0]["fact_id"]
    doc_p2 = extraction_p2["source_document_id"]
    canonical_sha_p2 = hashlib.sha256(canonical_p2.read_bytes()).hexdigest()

    code, out, err = run_cli([
        "verification", "--case", case_p2, "--document", FACT_DOC, "--fact-id", fact_id_p2,
        "--actor-user-id", str(_ACTORS["lawyer"]),
    ])
    check("P2a CLI preview exits 0 and shows from_state=unverified + correct hash",
          code == 0 and "from_state=unverified" in out and canonical_sha_p2 in out,
          f"code={code} out={out!r} err={err!r}")

    code, out, err = run_cli([
        "verification", "--case", case_p2, "--document", FACT_DOC, "--fact-id", fact_id_p2,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--target-state", "verified",
        "--expected-hash", canonical_sha_p2, "--evidence-ref", doc_p2,
    ])
    rows_p2 = journal_rows(f"case:{case_p2}")
    check("P2b CLI apply exits 0 (APPLIED)", code == 0 and "APPLIED verification" in out,
          f"code={code} out={out!r} err={err!r}")
    check(
        "P2c REAL journal row: verification.fact / fact.<doc>.<fact>.verification / verified / "
        "completed",
        len(rows_p2) == 1
        and rows_p2[0]["action_family"] == "verification.fact"
        and rows_p2[0]["target_ref"] == f"fact.{FACT_DOC}.{fact_id_p2}.verification"
        and rows_p2[0]["target_state"] == "verified"
        and rows_p2[0]["state"] == "completed"
        and rows_p2[0]["actor_user_id"] == _ACTORS["lawyer"],
        f"{rows_p2!r}",
    )
    check("P2d canonical fact state genuinely changed on disk",
          fv.find_fact(json.loads(canonical_p2.read_bytes().decode("utf-8")), fact_id_p2)
          ["verification_state"] == "verified")
    check(
        "P2e CLI stdout carries the STALE_DOWNSTREAM/RERUN_ORDER/NO_COORDINATED_PATH warning block",
        "STALE_DOWNSTREAM:" in out and "RERUN_ORDER:" in out and "NO_COORDINATED_PATH:" in out,
        f"out={out!r}",
    )
    reviews_p2 = canonical_p2.parent / "reviews" / "fact_verifications"
    audits_p2 = [json.loads(p.read_text(encoding="utf-8")) for p in reviews_p2.glob("*.verification.json")]
    check(
        "P2f exactly one audit, correctly bound (mutation keys + actor_ref + outcome + hashes)",
        len(audits_p2) == 1
        and audits_p2[0].get("mutation_actor_ref") == str(_ACTORS["lawyer"])
        and audits_p2[0].get("outcome") == "verified_state_changed"
        and audits_p2[0].get("canonical_sha256_before") == canonical_sha_p2
        and audits_p2[0].get("canonical_sha256") == sha256_file(canonical_p2),
        f"{audits_p2!r}",
    )

    # ============================================================
    # P3 - safe replay via CLI (same apply argv again).
    # ============================================================
    audits_before_replay = len(list(reviews_p2.glob("*.verification.json")))
    code, out, err = run_cli([
        "verification", "--case", case_p2, "--document", FACT_DOC, "--fact-id", fact_id_p2,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--target-state", "verified",
        "--expected-hash", canonical_sha_p2, "--evidence-ref", doc_p2,
    ])
    check("P3a CLI safe replay exits 0 with replayed=True", code == 0 and "replayed=True" in out,
          f"code={code} out={out!r} err={err!r}")
    check("P3b safe replay wrote NO new journal row", len(journal_rows(f"case:{case_p2}")) == 1)
    check("P3c safe replay wrote NO new audit file (writer genuinely not re-invoked)",
          len(list(reviews_p2.glob("*.verification.json"))) == audits_before_replay)

    # ============================================================
    # P4 - conflicting replay: same identity, DIFFERENT target_state ->
    #      IdempotencyConflictError, zero new rows.
    # ============================================================
    principal_p4, repo_p4, conn_p4 = make_pg_principal_and_repo(_ACTORS["lawyer"])
    try:
        raised_p4 = False
        try:
            fv_facade.apply_verification_mutation(
                case_p2, FACT_DOC, fact_id_p2, canonical_sha_p2, "partially_verified",
                evidence_document_id=doc_p2,
                principal=principal_p4, authz_repository=repo_p4, conn_factory=mutation_conn_factory,
            )
        except mc.IdempotencyConflictError:
            raised_p4 = True
        check("P4a same identity + different target_state -> IdempotencyConflictError", raised_p4)
    finally:
        conn_p4.close()
    check("P4b conflict created NO new journal row", len(journal_rows(f"case:{case_p2}")) == 1)

    # ============================================================
    # P5 - writer crash (post-canonical-write, at audit-write boundary)
    #      -> reconciliation_required; REAL merged registry resolves it
    #      via dual-false (rollback restores original bytes, canonical
    #      pre-state is confirmed changed relative to entry.pre_hash
    #      only if audit-manifest state differs - here rollback restores
    #      byte-identity, so pre-state IS confirmed unchanged).
    # ============================================================
    case_p5, dir_p5 = make_case("p5")
    seed_assignment(_ACTORS["lawyer"], case_p5, "lawyer")
    canonical_p5 = canonical_path_for(dir_p5)
    extraction_p5 = json.loads(canonical_p5.read_bytes().decode("utf-8"))
    fact_id_p5 = extraction_p5["facts"][0]["fact_id"]
    doc_p5 = extraction_p5["source_document_id"]
    canonical_sha_p5 = hashlib.sha256(canonical_p5.read_bytes()).hexdigest()

    _orig_audit_writer = fv._write_audit_record_excl
    _boom_p5 = OSError("simulated disk failure at audit write (P5 real-PG crash test)")

    def _raising_audit_writer(reviews_dir, document_id, fact_id, record):
        raise _boom_p5

    fv._write_audit_record_excl = _raising_audit_writer
    principal_p5, repo_p5, conn_p5 = make_pg_principal_and_repo(_ACTORS["lawyer"])
    try:
        raised_p5 = None
        try:
            fv_facade.apply_verification_mutation(
                case_p5, FACT_DOC, fact_id_p5, canonical_sha_p5, "verified",
                evidence_document_id=doc_p5,
                principal=principal_p5, authz_repository=repo_p5, conn_factory=mutation_conn_factory,
            )
        except Exception as error:
            raised_p5 = error
        check("P5a audit-write crash propagates the ORIGINAL exception", raised_p5 is _boom_p5)
    finally:
        fv._write_audit_record_excl = _orig_audit_writer
        conn_p5.close()
    rows_p5 = journal_rows(f"case:{case_p5}")
    check(
        "P5b REAL journal row is reconciliation_required (NEVER failed) with NULL observed_post_hash",
        len(rows_p5) == 1 and rows_p5[0]["state"] == "reconciliation_required"
        and rows_p5[0]["observed_post_hash"] is None,
        f"{rows_p5!r}",
    )
    check("P5c canonical rolled back to the exact pre-image (writer rollback worked)",
          hashlib.sha256(canonical_p5.read_bytes()).hexdigest() == canonical_sha_p5)

    out_io_p5, err_io_p5 = io.StringIO(), io.StringIO()
    rc_p5 = op.main(
        ["--journal-id", str(rows_p5[0]["id"]), "--apply", "--actor-ref", f"fv-test-{RUN_TOKEN}"],
        conn_factory=mutation_conn_factory, stdout=out_io_p5, stderr=err_io_p5,
    )
    rows_p5_after = journal_rows(f"case:{case_p5}")
    check(
        "P5d REAL merged-registry reconciliation resolves the row to 'failed' + "
        "reconciled_failed_pre_state_confirmed_unchanged (canonical genuinely never moved)",
        rc_p5 == 0 and rows_p5_after[0]["state"] == "failed"
        and rows_p5_after[0]["resolution_code"] == "reconciled_failed_pre_state_confirmed_unchanged"
        and rows_p5_after[0]["reconciled_by_actor_type"] == "cli_service"
        and rows_p5_after[0]["reconciled_by_actor_ref"] == f"fv-test-{RUN_TOKEN}",
        f"rc={rc_p5} rows={rows_p5_after!r} err={err_io_p5.getvalue()!r}",
    )

    # A genuinely NEW attempt (attempt=2) against the SAME still-valid
    # canonical hash now succeeds for real.
    principal_p5b, repo_p5b, conn_p5b = make_pg_principal_and_repo(_ACTORS["lawyer"])
    try:
        result_p5b = fv_facade.apply_verification_mutation(
            case_p5, FACT_DOC, fact_id_p5, canonical_sha_p5, "verified",
            evidence_document_id=doc_p5, attempt=2,
            principal=principal_p5b, authz_repository=repo_p5b, conn_factory=mutation_conn_factory,
        )
    finally:
        conn_p5b.close()
    check("P5e attempt=2 retry succeeds for real after the failed attempt=1",
          result_p5b.target_state == "verified" and result_p5b.replayed is False)

    # ============================================================
    # P6 - REAL-PostgreSQL `_mark_completed` FAILURE: the writer's
    # filesystem effects fully succeed (canonical + bound success audit
    # + backup), then the journal's OWN `state='completed'` UPDATE is
    # made to fail AT THE DATABASE LEVEL via a disposable-DB-only
    # BEFORE UPDATE trigger. NOTHING in production code is
    # monkeypatched. After dropping the trigger, the REAL merged
    # registry reconciles the row via the fact-verification adapter's
    # own independent post-state proof (exactly-one bound audit +
    # recomputed pre_revision match).
    # ============================================================

    def _install_completion_block(resource_key):
        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE OR REPLACE FUNCTION mutation.fv_block_completion() "
                    "RETURNS trigger AS $$ BEGIN "
                    "IF NEW.state = 'completed' AND NEW.resource_key = '" + resource_key + "' THEN "
                    "RAISE EXCEPTION 'fact_verification injected completion failure'; "
                    "END IF; RETURN NEW; END $$ LANGUAGE plpgsql"
                )
                cur.execute(
                    "CREATE TRIGGER fv_block_completion BEFORE UPDATE "
                    "ON mutation.mutation_journal FOR EACH ROW "
                    "EXECUTE FUNCTION mutation.fv_block_completion()"
                )
        finally:
            conn.close()

    def _drop_completion_block():
        conn = pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DROP TRIGGER IF EXISTS fv_block_completion ON mutation.mutation_journal")
                cur.execute("DROP FUNCTION IF EXISTS mutation.fv_block_completion()")
        finally:
            conn.close()

    case_p6, dir_p6 = make_case("p6")
    seed_assignment(_ACTORS["lawyer"], case_p6, "lawyer")
    canonical_p6 = canonical_path_for(dir_p6)
    extraction_p6 = json.loads(canonical_p6.read_bytes().decode("utf-8"))
    fact_id_p6 = extraction_p6["facts"][0]["fact_id"]
    doc_p6 = extraction_p6["source_document_id"]
    canonical_sha_p6 = hashlib.sha256(canonical_p6.read_bytes()).hexdigest()
    rk_p6 = f"case:{case_p6}"

    principal_p6, repo_p6, conn_p6 = make_pg_principal_and_repo(_ACTORS["lawyer"])
    _install_completion_block(rk_p6)
    try:
        try:
            fv_facade.apply_verification_mutation(
                case_p6, FACT_DOC, fact_id_p6, canonical_sha_p6, "verified",
                evidence_document_id=doc_p6,
                principal=principal_p6, authz_repository=repo_p6, conn_factory=mutation_conn_factory,
            )
            check("P6a injected completion failure propagates", False, "no exception raised")
        except Exception as p6_err:
            check(
                "P6a the DB-level completion failure propagates as the REAL database error "
                "(never re-classified as a writer failure)",
                isinstance(p6_err, psycopg.Error) and "injected completion failure" in str(p6_err),
                f"got {type(p6_err).__name__}: {p6_err!r}",
            )
    finally:
        _drop_completion_block()
        conn_p6.close()

    rows_p6 = journal_rows(rk_p6)
    check(
        "P6b journal row stays 'executing' with observed_post_hash NULL and a real executing_at",
        len(rows_p6) == 1 and rows_p6[0]["state"] == "executing"
        and rows_p6[0]["observed_post_hash"] is None and rows_p6[0]["executing_at"] is not None,
        f"{rows_p6!r}",
    )
    reviews_p6 = canonical_p6.parent / "reviews" / "fact_verifications"
    audits_p6 = [json.loads(p.read_text(encoding="utf-8")) for p in reviews_p6.glob("*.verification.json")]
    bound_p6 = [a for a in audits_p6 if a.get("mutation_resource_key") == rk_p6]
    check(
        "P6c writer effects ARE fully durable: canonical fact state changed, exactly ONE bound "
        "audit, history backup exists",
        fv.find_fact(json.loads(canonical_p6.read_bytes().decode("utf-8")), fact_id_p6)
        ["verification_state"] == "verified"
        and len(bound_p6) == 1
        and any(p.name.startswith("facts_before_verification_")
                for p in (canonical_p6.parent / "history").glob("*")),
        f"bound_audits={len(bound_p6)}",
    )

    audit_count_before_recon_p6 = len(list(reviews_p6.glob("*.verification.json")))
    out_io_p6, err_io_p6 = io.StringIO(), io.StringIO()
    rc_p6 = op.main(
        ["--journal-id", str(rows_p6[0]["id"]), "--apply", "--actor-ref", f"fv-test-{RUN_TOKEN}"],
        conn_factory=mutation_conn_factory, stdout=out_io_p6, stderr=err_io_p6,
    )
    rows_p6_after = journal_rows(rk_p6)
    check(
        "P6d REAL merged-registry reconciliation resolves the stale-executing row to completed + "
        "reconciled_completed_post_state_verified + cli_service provenance",
        rc_p6 == 0 and rows_p6_after[0]["state"] == "completed"
        and rows_p6_after[0]["resolution_code"] == "reconciled_completed_post_state_verified"
        and rows_p6_after[0]["reconciled_by_actor_type"] == "cli_service"
        and rows_p6_after[0]["reconciled_by_actor_ref"] == f"fv-test-{RUN_TOKEN}",
        f"rc={rc_p6} rows={rows_p6_after!r} err={err_io_p6.getvalue()!r}",
    )
    check(
        "P6e the writer was NEVER invoked a second time (audit file count invariant across "
        "reconciliation)",
        len(list(reviews_p6.glob("*.verification.json"))) == audit_count_before_recon_p6,
    )

    _residue_conn = pg_connect()
    try:
        with _residue_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_trigger WHERE tgname = 'fv_block_completion'")
            (_trig_count,) = cur.fetchone()
            cur.execute("SELECT count(*) FROM pg_proc WHERE proname = 'fv_block_completion'")
            (_proc_count,) = cur.fetchone()
    finally:
        _residue_conn.close()
    check("P6f no injected trigger/function residue remains in the database",
          _trig_count == 0 and _proc_count == 0)

    # ============================================================
    # P7 - unauthorized/analyst; existence-blind denial via real IAM.
    # ============================================================
    case_p7, dir_p7 = make_case("p7")
    seed_assignment(_ACTORS["analyst"], case_p7, "analyst")
    canonical_p7 = canonical_path_for(dir_p7)
    extraction_p7 = json.loads(canonical_p7.read_bytes().decode("utf-8"))
    fact_id_p7 = extraction_p7["facts"][0]["fact_id"]
    canonical_sha_p7 = hashlib.sha256(canonical_p7.read_bytes()).hexdigest()

    code, out, err = run_cli([
        "verification", "--case", case_p7, "--document", FACT_DOC, "--fact-id", fact_id_p7,
        "--actor-user-id", str(_ACTORS["analyst"]),
    ])
    check("P7a analyst CAN preview via real CLI (read capability)", code == 0 and "PREVIEW" in out)

    code, out, err = run_cli([
        "verification", "--case", case_p7, "--document", FACT_DOC, "--fact-id", fact_id_p7,
        "--actor-user-id", str(_ACTORS["analyst"]), "--apply", "--target-state", "unverified",
        "--expected-hash", canonical_sha_p7,
    ])
    check("P7b analyst apply denied via real CLI (existence-blind, exit 1)",
          code == cli_mutate.EXIT_DOMAIN_ERROR, f"code={code} out={out!r} err={err!r}")
    check("P7c analyst-denied apply wrote ZERO journal rows", len(journal_rows(f"case:{case_p7}")) == 0)

    # ============================================================
    # P8 - REAL merged reconciliation registry has exactly 52 routing
    #      keys (50 + Phase B's 2 qa/case_view generation families) and
    #      includes 'verification.fact'.
    # ============================================================
    real_registry = op._default_registry_factory()
    check(
        "P8a real merged reconciliation registry has exactly 52 routing keys",
        len(real_registry.known_action_families()) == 52,
        f"got {len(real_registry.known_action_families())}",
    )
    check(
        "P8b 'verification.fact' resolves to a real FactVerificationReconciliationAdapter instance",
        isinstance(
            real_registry.get("verification.fact"), fv_adapters.FactVerificationReconciliationAdapter,
        ),
    )

    # ============================================================
    # P9 - TIMELINE PROPAGATION (Fable FINAL continuation instruction
    #      #2): verification.fact apply -> generation.timeline ->
    #      promotion.timeline, through the REAL production CLI chain,
    #      BOTH upgrade and downgrade directions. timeline_event_004 has
    #      EXACTLY one source_fact_id (no multi-fact consolidation
    #      ambiguity - confirmed below, never assumed).
    # ============================================================
    case_p9, dir_p9 = make_case("p9")
    seed_assignment(_ACTORS["lawyer"], case_p9, "lawyer")
    timeline_p9_path = dir_p9 / "timeline" / "timeline.json"
    event004_p9 = next(
        e for e in json.loads(timeline_p9_path.read_bytes())["events"] if e["event_id"] == "timeline_event_004"
    )
    check(
        "P9 setup: the REAL case_0001-derived timeline_event_004 genuinely has exactly one "
        "source_fact_id",
        len(event004_p9["source_fact_ids"]) == 1,
        f"{event004_p9!r}",
    )
    fact_id_p9 = event004_p9["source_fact_ids"][0]
    canonical_p9 = canonical_path_for(dir_p9)
    extraction_p9 = json.loads(canonical_p9.read_bytes())
    doc_p9 = extraction_p9["source_document_id"]
    fact_p9_pre = next(f for f in extraction_p9["facts"] if f["fact_id"] == fact_id_p9)
    check("P9 setup: the source fact is genuinely 'unverified' at the start",
          fact_p9_pre["verification_state"] == "unverified")

    # ---- UPGRADE direction: verification.fact (unverified->verified). ----
    canonical_sha_p9a = hashlib.sha256(canonical_p9.read_bytes()).hexdigest()
    code, out, err = run_cli([
        "verification", "--case", case_p9, "--document", FACT_DOC, "--fact-id", fact_id_p9,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--target-state", "verified",
        "--expected-hash", canonical_sha_p9a, "--evidence-ref", doc_p9,
    ])
    check("P9a real verification.fact UPGRADE apply exits 0", code == 0, f"out={out!r} err={err!r}")

    code, out, err = run_cli(["generation", "--case", case_p9, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"])])
    check("P9b real generation.timeline preview (post-upgrade) exits 0", code == 0, f"out={out!r} err={err!r}")
    digest_p9a = _parse_kv(out, "input_digest")
    code, out, err = run_cli([
        "generation", "--case", case_p9, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--apply", "--expected-input-digest", digest_p9a,
    ])
    check("P9c real generation.timeline apply (post-upgrade) exits 0", code == 0, f"out={out!r} err={err!r}")

    code, out, err = run_cli(["promotion", "--case", case_p9, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"])])
    check("P9d real promotion.timeline preview (post-upgrade) exits 0", code == 0, f"out={out!r} err={err!r}")
    pending_hash_p9a = _parse_kv(out, "pending_hash")
    code, out, err = run_cli([
        "promotion", "--case", case_p9, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--approve", "--expected-hash", pending_hash_p9a,
    ])
    check("P9e real promotion.timeline apply (post-upgrade) exits 0", code == 0, f"out={out!r} err={err!r}")

    timeline_p9_after_upgrade = json.loads(timeline_p9_path.read_bytes())
    event004_p9_after_upgrade = next(
        e for e in timeline_p9_after_upgrade["events"] if e["event_id"] == "timeline_event_004"
    )
    check(
        "P9f the REAL, regenerated+re-promoted canonical timeline.json event's "
        "verification_state was GENUINELY RE-DERIVED to 'verified' from the source fact's real "
        "(now-verified) state - real timeline_engine.propagate_verification_state(), never mocked",
        event004_p9_after_upgrade["verification_state"] == "verified",
        f"{event004_p9_after_upgrade!r}",
    )

    # ---- DOWNGRADE direction: verification.fact (verified->unverified). ----
    canonical_sha_p9b = hashlib.sha256(canonical_p9.read_bytes()).hexdigest()
    code, out, err = run_cli([
        "verification", "--case", case_p9, "--document", FACT_DOC, "--fact-id", fact_id_p9,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--target-state", "unverified",
        "--expected-hash", canonical_sha_p9b,
    ])
    check("P9g real verification.fact DOWNGRADE apply exits 0", code == 0, f"out={out!r} err={err!r}")

    code, out, err = run_cli(["generation", "--case", case_p9, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"])])
    digest_p9b = _parse_kv(out, "input_digest")
    code, out, err = run_cli([
        "generation", "--case", case_p9, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--apply", "--expected-input-digest", digest_p9b,
    ])
    check("P9h real generation.timeline apply (post-downgrade) exits 0", code == 0, f"out={out!r} err={err!r}")

    code, out, err = run_cli(["promotion", "--case", case_p9, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"])])
    pending_hash_p9b = _parse_kv(out, "pending_hash")
    code, out, err = run_cli([
        "promotion", "--case", case_p9, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--approve", "--expected-hash", pending_hash_p9b,
    ])
    check("P9i real promotion.timeline apply (post-downgrade) exits 0", code == 0, f"out={out!r} err={err!r}")

    timeline_p9_after_downgrade = json.loads(timeline_p9_path.read_bytes())
    event004_p9_after_downgrade = next(
        e for e in timeline_p9_after_downgrade["events"] if e["event_id"] == "timeline_event_004"
    )
    check(
        "P9j the REAL, regenerated+re-promoted canonical timeline.json event's "
        "verification_state was GENUINELY RE-DERIVED back to 'unverified' after the real "
        "downgrade - a full, real production-chain round trip",
        event004_p9_after_downgrade["verification_state"] == "unverified",
        f"{event004_p9_after_downgrade!r}",
    )

    # ============================================================
    # P10 - DEADLINE BLOCKED -> CALCULATED (Fable FINAL continuation
    #      instruction #3), through the REAL production CLI chain end
    #      to end: generation.timeline -> promotion.timeline ->
    #      generation.deadline (blocked_unverified_anchor) ->
    #      verification.fact -> generation.timeline -> promotion.
    #      timeline -> generation.deadline (calculated) ->
    #      approval.deadline. Zero fake/mocked deadline result anywhere.
    # ============================================================
    case_p10, dir_p10 = make_single_fact_deadline_case("p10")
    seed_assignment(_ACTORS["lawyer"], case_p10, "lawyer")
    DOC_P10 = "ihbarname_001"

    # ---- first-pass generation.timeline/promotion.timeline (anchor still unverified). ----
    code, out, err = run_cli(["generation", "--case", case_p10, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"])])
    check("P10a real generation.timeline preview (first pass) exits 0", code == 0, f"out={out!r} err={err!r}")
    digest_p10a = _parse_kv(out, "input_digest")
    code, out, err = run_cli([
        "generation", "--case", case_p10, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--apply", "--expected-input-digest", digest_p10a,
    ])
    check("P10b real generation.timeline apply (first pass) exits 0", code == 0, f"out={out!r} err={err!r}")
    code, out, err = run_cli(["promotion", "--case", case_p10, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"])])
    pending_hash_p10a = _parse_kv(out, "pending_hash")
    code, out, err = run_cli([
        "promotion", "--case", case_p10, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--approve", "--expected-hash", pending_hash_p10a,
    ])
    check("P10c real promotion.timeline apply (first pass) exits 0", code == 0, f"out={out!r} err={err!r}")

    timeline_p10 = json.loads((dir_p10 / "timeline" / "timeline.json").read_bytes())
    check(
        "P10 setup: the REAL, freshly-generated timeline has EXACTLY one event (the trimmed "
        "single-document/single-fact fixture produces no consolidation ambiguity)",
        len(timeline_p10["events"]) == 1,
        f"{timeline_p10!r}",
    )
    anchor_event_p10 = timeline_p10["events"][0]
    anchor_event_id_p10 = anchor_event_p10["event_id"]
    check(
        "P10 setup: the REAL anchor event is genuinely notification_date/deadline_relevant=True/"
        "unverified, date=2026-02-10 (the SAME anchor date CLAUDE.md's own worked example and "
        "deadline_calculator.py's own embedded self-test T02 use)",
        anchor_event_p10["event_type"] == "notification_date"
        and anchor_event_p10["deadline_relevant"] is True
        and anchor_event_p10["verification_state"] == "unverified"
        and anchor_event_p10["date"] == "2026-02-10",
        f"{anchor_event_p10!r}",
    )

    # ---- generation.deadline (anchor still unverified) -> blocked_unverified_anchor. ----
    code, out, err = run_cli([
        "generation", "--case", case_p10, "--row-key", "deadline", "--anchor", anchor_event_id_p10,
        "--actor-user-id", str(_ACTORS["lawyer"]),
    ])
    check("P10d real generation.deadline preview (anchor unverified) exits 0", code == 0, f"out={out!r} err={err!r}")
    digest_p10b = _parse_kv(out, "input_digest")
    code, out, err = run_cli([
        "generation", "--case", case_p10, "--row-key", "deadline", "--anchor", anchor_event_id_p10,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_p10b,
        "--judicial-recess-applicable", "no",
    ])
    check("P10e real generation.deadline apply (anchor unverified) exits 0", code == 0, f"out={out!r} err={err!r}")
    pending_deadline_p10 = json.loads(_pg_deadline_engine.get_pending_path(case_p10).read_bytes())
    check(
        "P10f the REAL deadline engine genuinely reports calculation_state="
        "'blocked_unverified_anchor' while the anchor's sole source fact is still unverified - "
        "NOT a fabricated/asserted value",
        pending_deadline_p10["deadlines"][0]["calculation_state"] == "blocked_unverified_anchor",
        f"{pending_deadline_p10!r}",
    )

    # ---- verification.fact: verify the sole anchor fact. ----
    canonical_p10 = canonical_path_for(dir_p10, document_id=DOC_P10)
    extraction_p10 = json.loads(canonical_p10.read_bytes())
    fact_id_p10 = extraction_p10["facts"][0]["fact_id"]
    canonical_sha_p10 = hashlib.sha256(canonical_p10.read_bytes()).hexdigest()
    code, out, err = run_cli([
        "verification", "--case", case_p10, "--document", DOC_P10, "--fact-id", fact_id_p10,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--target-state", "verified",
        "--expected-hash", canonical_sha_p10, "--evidence-ref", DOC_P10,
    ])
    check("P10g real verification.fact apply (the anchor's sole source fact) exits 0",
          code == 0, f"out={out!r} err={err!r}")

    # ---- second-pass generation.timeline/promotion.timeline (anchor now verified). ----
    code, out, err = run_cli(["generation", "--case", case_p10, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"])])
    digest_p10c = _parse_kv(out, "input_digest")
    code, out, err = run_cli([
        "generation", "--case", case_p10, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--apply", "--expected-input-digest", digest_p10c,
    ])
    check("P10h real generation.timeline apply (second pass, post-verification) exits 0",
          code == 0, f"out={out!r} err={err!r}")
    code, out, err = run_cli(["promotion", "--case", case_p10, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"])])
    pending_hash_p10b = _parse_kv(out, "pending_hash")
    code, out, err = run_cli([
        "promotion", "--case", case_p10, "--row-key", "timeline", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--approve", "--expected-hash", pending_hash_p10b,
    ])
    check("P10i real promotion.timeline apply (second pass, post-verification) exits 0",
          code == 0, f"out={out!r} err={err!r}")
    timeline_p10_v2 = json.loads((dir_p10 / "timeline" / "timeline.json").read_bytes())
    check(
        "P10j the REAL, regenerated anchor event's verification_state is now 'verified'",
        timeline_p10_v2["events"][0]["verification_state"] == "verified",
        f"{timeline_p10_v2!r}",
    )

    # ---- generation.deadline (anchor now verified) -> calculated. ----
    code, out, err = run_cli([
        "generation", "--case", case_p10, "--row-key", "deadline", "--anchor", anchor_event_id_p10,
        "--actor-user-id", str(_ACTORS["lawyer"]),
    ])
    digest_p10d = _parse_kv(out, "input_digest")
    code, out, err = run_cli([
        "generation", "--case", case_p10, "--row-key", "deadline", "--anchor", anchor_event_id_p10,
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_p10d,
        "--judicial-recess-applicable", "no",
    ])
    check("P10k real generation.deadline apply (anchor verified) exits 0", code == 0, f"out={out!r} err={err!r}")
    pending_deadline_p10_v2 = json.loads(_pg_deadline_engine.get_pending_path(case_p10).read_bytes())
    check(
        "P10l the REAL deadline engine genuinely reports calculation_state='calculated' with "
        "calculated_deadline='2026-03-12' (2026-02-10 + 30 calendar days, next_day start, "
        "no holidays, outside judicial recess) - NOT a fabricated/asserted value",
        pending_deadline_p10_v2["deadlines"][0]["calculation_state"] == "calculated"
        and pending_deadline_p10_v2["deadlines"][0]["calculated_deadline"] == "2026-03-12",
        f"{pending_deadline_p10_v2!r}",
    )

    # ---- approval.deadline -> canonical deadline.json = calculated. ----
    code, out, err = run_cli(["approval", "--case", case_p10, "--row-key", "deadline", "--actor-user-id", str(_ACTORS["lawyer"])])
    check("P10m real approval.deadline preview exits 0", code == 0, f"out={out!r} err={err!r}")
    pending_hash_p10c = _parse_kv(out, "pending_hash")
    code, out, err = run_cli([
        "approval", "--case", case_p10, "--row-key", "deadline", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--approve", "--expected-hash", pending_hash_p10c,
    ])
    check("P10n real approval.deadline apply exits 0", code == 0, f"out={out!r} err={err!r}")
    canonical_deadline_p10 = json.loads(_pg_deadline_approval.get_canonical_path(case_p10).read_bytes())
    check(
        "P10o the REAL canonical deadline.json (Fable FINAL continuation instruction #3's own "
        "goal) genuinely shows calculation_state='calculated' with anchor_verification_state="
        "'verified' - the FULL blocked->calculated production chain, zero mocking anywhere",
        canonical_deadline_p10["deadlines"][0]["calculation_state"] == "calculated"
        and canonical_deadline_p10["deadlines"][0]["anchor_verification_state"] == "verified"
        and canonical_deadline_p10["deadlines"][0]["calculated_deadline"] == "2026-03-12",
        f"{canonical_deadline_p10!r}",
    )

    # ============================================================
    # P11 - TWO DIFFERENT FACTS CONCURRENCY (Fable FINAL continuation
    #      instruction #4): same document, two different facts, two
    #      different REAL actors, genuinely concurrent apply through
    #      the real facade, real PostgreSQL advisory lock. Exactly ONE
    #      thread's writer runs; the OTHER's stale whole-file
    #      expected_hash is rejected under lock, zero canonical/audit
    #      write.
    # ============================================================
    case_p11, dir_p11 = make_case("p11")
    seed_assignment(_ACTORS["lawyer"], case_p11, "lawyer")
    seed_assignment(_ACTORS["lawyer2"], case_p11, "lawyer")
    canonical_p11 = canonical_path_for(dir_p11)
    extraction_p11 = json.loads(canonical_p11.read_bytes())
    check("P11 setup: the fixture document genuinely has at least 2 distinct facts",
          len(extraction_p11["facts"]) >= 2, f"{[f['fact_id'] for f in extraction_p11['facts']]!r}")
    fact_a_p11 = extraction_p11["facts"][0]["fact_id"]
    fact_b_p11 = extraction_p11["facts"][1]["fact_id"]
    doc_p11 = extraction_p11["source_document_id"]
    canonical_sha_p11 = hashlib.sha256(canonical_p11.read_bytes()).hexdigest()
    reviews_dir_p11 = canonical_p11.parent / "reviews" / "fact_verifications"
    audit_count_before_p11 = (
        len(list(reviews_dir_p11.glob("*.verification.json"))) if reviews_dir_p11.is_dir() else 0
    )

    holder_conn_p11 = mutation_conn_factory()
    holder_lock_id_p11 = _mutation_lock.acquire_case_lock_session(holder_conn_p11, case_p11)
    check("P11a holder connection genuinely holds the case advisory lock",
          _count_advisory_locks(holder_lock_id_p11, granted=True) >= 1)

    results_p11 = {}

    def run_p11_apply(label, actor_user_id, fact_id, evidence_document_id):
        principal, repo, conn = make_pg_principal_and_repo(actor_user_id)
        try:
            result = fv_facade.apply_verification_mutation(
                case_p11, FACT_DOC, fact_id, canonical_sha_p11, "verified",
                evidence_document_id=evidence_document_id,
                principal=principal, authz_repository=repo, conn_factory=mutation_conn_factory,
            )
            results_p11[label] = {"ok": True, "result": result}
        except Exception as error:
            results_p11[label] = {"ok": False, "error": error}
        finally:
            conn.close()

    thread_a = threading.Thread(
        target=run_p11_apply, args=("A", _ACTORS["lawyer"], fact_a_p11, doc_p11), daemon=True,
    )
    thread_b = threading.Thread(
        target=run_p11_apply, args=("B", _ACTORS["lawyer2"], fact_b_p11, doc_p11), daemon=True,
    )
    thread_a.start()
    thread_b.start()
    check(
        "P11b pg_locks reports TWO genuinely WAITING advisory-lock requests while the holder "
        "holds (real, observed concurrent contention - not a fabricated ordering)",
        wait_for_lock_waiters(holder_lock_id_p11, 2),
    )
    check(
        "P11c BOTH threads are still genuinely blocked (no result yet from either)",
        thread_a.is_alive() and thread_b.is_alive() and not results_p11,
        f"{results_p11!r}",
    )
    _mutation_lock.release_lock_session(holder_conn_p11, holder_lock_id_p11)
    holder_conn_p11.close()
    thread_a.join(timeout=120)
    thread_b.join(timeout=120)

    check("P11d both threads genuinely completed (no hang)", "A" in results_p11 and "B" in results_p11)
    winners = [label for label, r in results_p11.items() if r["ok"]]
    losers = [label for label, r in results_p11.items() if not r["ok"]]
    check(
        "P11e EXACTLY ONE of the two concurrent apply attempts succeeded and the OTHER failed "
        "with StaleViewError (whole-file expected_hash granularity - documented, accepted "
        "limitation) - the winner is determined by REAL lock-acquisition order, never assumed",
        len(winners) == 1 and len(losers) == 1
        and isinstance(results_p11[losers[0]]["error"], StaleViewError),
        f"{results_p11!r}",
    )
    winner_label, loser_label = winners[0], losers[0]
    winner_fact_id = fact_a_p11 if winner_label == "A" else fact_b_p11
    loser_fact_id = fact_b_p11 if winner_label == "A" else fact_a_p11
    check(
        f"P11f the WINNER ({winner_label}) genuinely completed: journal row completed, "
        "canonical fact state changed",
        results_p11[winner_label]["result"].replayed is False
        and fv.find_fact(json.loads(canonical_p11.read_bytes()), winner_fact_id)["verification_state"] == "verified",
    )
    check(
        f"P11g the LOSER ({loser_label})'s target fact was NEVER touched (still 'unverified') - "
        "the second writer wrote NOTHING to canonical or audit",
        fv.find_fact(json.loads(canonical_p11.read_bytes()), loser_fact_id)["verification_state"] == "unverified",
    )
    audit_count_after_p11 = len(list(reviews_dir_p11.glob("*.verification.json")))
    check(
        "P11h EXACTLY ONE new audit file was written (the winner's) - the loser's writer never "
        "ran, never wrote an audit",
        audit_count_after_p11 - audit_count_before_p11 == 1,
        f"before={audit_count_before_p11} after={audit_count_after_p11}",
    )
    check(
        "P11i real PostgreSQL journal: exactly ONE completed row for this case (the loser's "
        "rejection happened entirely inside precondition_callback, BEFORE any journal row would "
        "have been inserted for it)",
        len(journal_rows(f"case:{case_p11}")) == 1
        and journal_rows(f"case:{case_p11}")[0]["state"] == "completed",
        f"{journal_rows(f'case:{case_p11}')!r}",
    )

    # ============================================================
    # P12 - F2 REMEDIATION (independent review, Medium): revision/state-
    #       cycle identity collision on REAL PostgreSQL through the REAL
    #       CLI - genuine replay vs cycle conflict vs identity conflict vs
    #       stale, and the `--attempt N+1` escape. Plus F1: a tampered old
    #       audit on a cycle is NEVER classified as a cycle.
    # ============================================================
    case_p12, dir_p12 = make_case("p12")
    seed_assignment(_ACTORS["lawyer"], case_p12, "lawyer")
    canonical_p12 = canonical_path_for(dir_p12)
    extraction_p12 = json.loads(canonical_p12.read_bytes().decode("utf-8"))
    fact_p12 = next(
        f for f in extraction_p12["facts"] if any(d != FACT_DOC for d in (f.get("related_document_ids") or []))
    )
    fact_id_p12 = fact_p12["fact_id"]
    related_p12 = next(d for d in fact_p12["related_document_ids"] if d != FACT_DOC)
    reviews_dir_p12 = dir_p12 / "documents" / FACT_DOC / "extractions" / "reviews" / "fact_verifications"
    rk_p12 = f"case:{case_p12}"

    def audits_p12():
        return sorted(reviews_dir_p12.glob("*.verification.json")) if reviews_dir_p12.is_dir() else []

    def cli_verify_p12(target, expected, *, evidence=None, attempt=None):
        argv = [
            "verification", "--case", case_p12, "--document", FACT_DOC, "--fact-id", fact_id_p12,
            "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--target-state", target,
            "--expected-hash", expected,
        ]
        if evidence:
            argv += ["--evidence-ref", evidence]
        if attempt is not None:
            argv += ["--attempt", str(attempt)]
        return run_cli(argv)

    h0_p12 = sha256_file(canonical_p12)
    code, out, err = cli_verify_p12("verified", h0_p12, evidence=FACT_DOC)
    check("P12a first transition via real CLI (unverified -> verified) exits 0", code == 0, err)
    h1_p12 = sha256_file(canonical_p12)
    audit1_p12 = Path(_parse_kv(out, "audit_path"))
    if not audit1_p12.is_absolute():
        audit1_p12 = REPO_ROOT / audit1_p12
    code, out, err = cli_verify_p12("verified", h0_p12, evidence=FACT_DOC)
    check("P12b immediate genuine replay via real CLI -> exit 0, replayed=True, no new row",
          code == 0 and _parse_kv(out, "replayed") == "True" and len(journal_rows(rk_p12)) == 1, err)
    code, out, err = cli_verify_p12("unverified", h1_p12)
    check("P12c downgrade (new identity) exits 0 and restores the BYTE-IDENTICAL original canonical",
          code == 0 and sha256_file(canonical_p12) == h0_p12 and len(journal_rows(rk_p12)) == 2, err)

    code, out, err = cli_verify_p12("verified", h0_p12, evidence=FACT_DOC)
    check(
        "P12d identical transition after the cycle (same attempt) -> exit 1 with the explicit "
        "FactVerificationRevisionCycleConflictError naming --attempt N+1 (NOT the generic "
        "audit-binding/reconciliation error)",
        code == cli_mutate.EXIT_DOMAIN_ERROR and "FactVerificationRevisionCycleConflictError" in err
        and "--attempt N+1" in err and "AuditBindingVerificationFailed" not in err,
        f"code={code} err={err!r}",
    )
    check("P12d cycle error carries no filesystem path", str(dir_p12) not in err and str(_TMP_ROOT) not in err)
    check("P12e cycle rejection: zero new writer/journal/audit, canonical unchanged",
          len(journal_rows(rk_p12)) == 2 and len(audits_p12()) == 2 and sha256_file(canonical_p12) == h0_p12)
    code, out, err = cli_verify_p12("partially_verified", h0_p12, evidence=FACT_DOC)
    check(
        "P12f DIFFERENT target after the cycle (same attempt) -> exit 1 FactVerificationIdentityConflictError "
        "with the --attempt N+1 guidance",
        code == cli_mutate.EXIT_DOMAIN_ERROR and "FactVerificationIdentityConflictError" in err and "--attempt N+1" in err,
        f"code={code} err={err!r}",
    )
    code, out, err = cli_verify_p12("verified", h0_p12, evidence=related_p12)
    check(
        "P12g DIFFERENT evidence after the cycle (same attempt) -> exit 1 FactVerificationIdentityConflictError",
        code == cli_mutate.EXIT_DOMAIN_ERROR and "FactVerificationIdentityConflictError" in err and "--attempt N+1" in err,
        f"code={code} err={err!r}",
    )
    check("P12h identity-conflict rejections: zero new rows", len(journal_rows(rk_p12)) == 2)
    code, out, err = cli_verify_p12("verified", "0" * 64, evidence=FACT_DOC, attempt=2)
    check("P12i stale expected hash + bumped attempt -> still StaleViewError (exit 1)",
          code == cli_mutate.EXIT_DOMAIN_ERROR and "StaleViewError" in err, f"code={code} err={err!r}")

    code, out, err = cli_verify_p12("verified", h0_p12, evidence=FACT_DOC, attempt=2)
    rows_p12 = journal_rows(rk_p12)
    check(
        "P12j --attempt 2: the SAME logical mutation completes for real (exit 0, replayed=False), "
        "ONE new completed row with a NEW pre_revision, ONE new full-binding audit, fact verified",
        code == 0 and _parse_kv(out, "replayed") == "False" and len(rows_p12) == 3
        and rows_p12[2]["state"] == "completed" and rows_p12[2]["pre_revision"] != rows_p12[0]["pre_revision"]
        and len(audits_p12()) == 3
        and fv.find_fact(json.loads(canonical_p12.read_bytes().decode("utf-8")), fact_id_p12)["verification_state"] == "verified",
        f"code={code} err={err!r} rows={rows_p12!r}",
    )
    audit3_p12 = Path(_parse_kv(out, "audit_path"))
    if not audit3_p12.is_absolute():
        audit3_p12 = REPO_ROOT / audit3_p12
    code, out, err = cli_verify_p12("verified", h0_p12, evidence=FACT_DOC, attempt=2)
    check("P12k immediate genuine replay of the attempt=2 request -> exit 0, replayed=True, no new row",
          code == 0 and _parse_kv(out, "replayed") == "True" and len(journal_rows(rk_p12)) == 3, err)
    h_verified_p12 = sha256_file(canonical_p12)
    code, out, err = cli_verify_p12("verified", h_verified_p12, evidence=FACT_DOC, attempt=3)
    check("P12l --attempt 3 on an already-verified fact -> NoOp (attempt never bypasses state rules)",
          code == cli_mutate.EXIT_DOMAIN_ERROR and "FactVerificationNoOpError" in err, f"code={code} err={err!r}")
    code, out, err = cli_verify_p12("partially_verified", h_verified_p12, evidence=FACT_DOC, attempt=3)
    check("P12m --attempt 3 with a VALID real transition (verified -> partially_verified) succeeds",
          code == 0 and len(journal_rows(rk_p12)) == 4, err)
    # F1 x F2: tampered OLD audit on a cycle -> binding failure, never a cycle
    h_p_p12 = sha256_file(canonical_p12)
    code, out, err = cli_verify_p12("unverified", h_p_p12)
    check("P12n second cycle back to the original bytes", code == 0 and sha256_file(canonical_p12) == h0_p12, err)
    audit3_bytes_p12 = audit3_p12.read_bytes()
    record3_p12 = json.loads(audit3_bytes_p12.decode("utf-8"))
    record3_p12["mutation_actor_ref"] = "999"
    audit3_p12.write_bytes(fv.canonical_json_bytes(record3_p12))
    try:
        code, out, err = cli_verify_p12("verified", h0_p12, evidence=FACT_DOC, attempt=2)
        check(
            "P12o TAMPERED old audit (actor) on a cycle -> FactVerificationAuditBindingVerificationFailedError, "
            "NEVER classified as a revision cycle",
            code == cli_mutate.EXIT_DOMAIN_ERROR and "FactVerificationAuditBindingVerificationFailedError" in err
            and "RevisionCycle" not in err,
            f"code={code} err={err!r}",
        )
    finally:
        audit3_p12.write_bytes(audit3_bytes_p12)
    code, out, err = cli_verify_p12("verified", h0_p12, evidence=FACT_DOC, attempt=2)
    check("P12p with the audit restored the same request is the explicit cycle conflict again",
          code == cli_mutate.EXIT_DOMAIN_ERROR and "FactVerificationRevisionCycleConflictError" in err, f"err={err!r}")
    check("P12q the whole P12 probe sequence left exactly 5 journal rows, all completed",
          len(journal_rows(rk_p12)) == 5 and all(r["state"] == "completed" for r in journal_rows(rk_p12)),
          f"{journal_rows(rk_p12)!r}")

finally:
    for _m, _orig in _original_cases_dirs:
        _m.CASES_DIR = _orig
    _pg_deadline_rule_selection_policy.DATA_DIR = _original_deadline_rule_policy_data_dir
    _pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH = _original_default_holiday_calendar_path
    try:
        shutil.rmtree(_TMP_ROOT)
    except OSError as cleanup_error:
        print(f"CLEANUP WARNING: tempdir {_TMP_ROOT}: {cleanup_error!r}")

_real_data_after = snapshot_real_data_tree()
check(
    "FINAL: the REAL data/ tree is byte-for-byte UNCHANGED (all fixtures lived under a redirected "
    "tempdir CASES_DIR, never the real data/cases tree)",
    _real_data_before == _real_data_after,
    f"diff keys: {sorted(set(_real_data_before) ^ set(_real_data_after))[:20]!r}",
)

summarize_and_exit()
