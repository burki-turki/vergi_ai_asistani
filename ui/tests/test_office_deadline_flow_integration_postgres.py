# ============================================================
# BÜRO MODELİ / T1 - GERÇEK ZİNCİR, GERÇEK PostgreSQL ENTEGRASYON KANITI
# (ui/office_deadline_flow.py + ui/services/office_flow_*.py)
#
#   S1  uyumlu hesap -> rapor kontrolü -> silme (TAMAMLANDI)
#   S2  uyuşmazlık: onay açılmaz, rapor korunur, silme reddedilir, kapatma ->
#       UYUŞMAZLIK sonucu -> silme; ikinci koşu = YENIDEN_KONTROL; önceki
#       uyuşmazlık koşusu silinmez/üzerine yazılmaz
#   S3  girdi değişti -> GEÇERSİZ (onay/“kontrol tamamlandı” yok, sonuç yok)
#   S4  silme yarıda kalırsa yanlış imha kaydı yok (a-e)
#   K   kimlik: oturum principal'ı belirler, yazılan ad yalnız ek teyit
#   N   normal yerel hesap (uygulama DB rolü + lawyer) çalışır;
#       dış YZ çağrısı REDDEDİLİR (preflight + wheel-yok fact_extraction)
#   D   DB kolon taraması (tarih/alıntı yok), TEMP karakterizasyonu,
#       ağ (loopback-dışı yok)
#
# GERÇEK OLMAYAN: vaka ağacı (geçici dizin + CASES_DIR yönlendirmesi; deponun
# data/ ağacına HİÇ yazılmaz - bayt-bayt kanıtlanır), sentetik tatil
# takvimi, sentetik "asıl PDF". Gerçek veri/ağ/.env YOK.
#
# Çalıştırma: VERGI_TEST_PG_DSN=<db> python -m ui.tests.test_office_deadline_flow_integration_postgres
# ============================================================

import hashlib
import io
import json
import os
import shutil
import stat
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
        f"--- test_office_deadline_flow_integration_postgres: {passed} passed, "
        f"{failed} failed, {skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip("the entire office-flow real-PostgreSQL suite",
         "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass")
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip("the entire office-flow real-PostgreSQL suite",
         f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass")
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                              # noqa: E402
from ui.services import paths as _paths                                        # noqa: E402
from ui.services import office_flow_records as records                          # noqa: E402
from ui.services import office_flow_cleanup as cleanup                          # noqa: E402
from ui.services import office_flow_outcomes as outcomes                        # noqa: E402
from ui.services import office_flow_intake as intake                            # noqa: E402
from ui.services import office_flow_preflight as preflight                      # noqa: E402
import ui.office_deadline_flow as flow_module                                   # noqa: E402

# CASES_DIR yönlendirmesinden ÖNCE import edilmeli (her src modülü kendi CASES_DIR'ini taşır).
import manual_fact_entry_engine as _m1                                          # noqa: E402,F401
import case_fact_validator as _m2                                               # noqa: E402,F401
import fact_verification as _m3                                                 # noqa: E402,F401
import timeline_engine as _m4                                                   # noqa: E402,F401
import timeline_validator as _m5                                                # noqa: E402,F401
import timeline_approval as _m6                                                 # noqa: E402,F401
import fact_approval as _m7                                                     # noqa: E402,F401
import deadline_engine as _pg_deadline_engine                                   # noqa: E402,F401
import deadline_approval as _m9                                                 # noqa: E402,F401
import deadline_validator as _m10                                               # noqa: E402,F401
import deadline_calculator as _pg_deadline_calculator                           # noqa: E402,F401
import holiday_calendar_validator as _pg_holiday_calendar_validator             # noqa: E402,F401
import deadline_rule_selection_policy as _pg_deadline_rule_selection_policy     # noqa: E402,F401
import case_validator as _m14                                                   # noqa: E402,F401
import case_document_validator as _m15                                          # noqa: E402,F401
import fact_extraction_engine as _m16                                           # noqa: E402,F401
from ui.services import manual_fact_mutation_facade as _f1                      # noqa: E402,F401
from ui.services import promotion_mutation_facade as _f2                        # noqa: E402,F401
from ui.services import generation_mutation_facade as _f3                       # noqa: E402,F401
from ui.services import fact_verification_mutation_facade as _f4                # noqa: E402,F401
from ui.services import approval_registry as _f5                                # noqa: E402,F401
from ui.services import fact_extraction_mutation_facade as _fx_facade           # noqa: E402,F401
import ui.deadline_report as deadline_report                                    # noqa: E402,F401

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, action_family, state, actor_user_id, target_ref FROM mutation.mutation_journal "
                "WHERE resource_key = %s ORDER BY id", (resource_key,),
            )
            return [dict(zip(("id", "family", "state", "actor", "target_ref"), row)) for row in cur.fetchall()]
    finally:
        conn.close()


# ----------------------------------------------------------------
# Preflight: migrations + uygulama rolü (0006) mevcut olmalı.
# ----------------------------------------------------------------

_pre = pg_connect()
try:
    with _pre.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('iam.users'), to_regclass('mutation.mutation_journal'), "
            "(SELECT count(*) FROM pg_roles WHERE rolname = 'vergi_app')"
        )
        _row = cur.fetchone()
    check("preflight: iam + mutation schemas exist (migrations applied)", bool(_row[0]) and bool(_row[1]))
    check("preflight: the canonical runtime role vergi_app exists (0006 contract applied)", _row[2] == 1)
finally:
    _pre.close()
if failed:
    print("Preflight failed - refusing to run against a half-migrated database.")
    summarize_and_exit()

RUN_TOKEN = uuid.uuid4().hex[:8]
LAWYER_ID, OTHER_ID, ANALYST_ID, APPUSER_ID = 811, 812, 813, 814
NAMES = {
    LAWYER_ID: "Av. Örnek Kullanıcı Bir",
    OTHER_ID: "Av. Örnek Kullanıcı İki",
    ANALYST_ID: "Analist Örnek Üç",
    APPUSER_ID: "Av. Uygulama Rolü Dört",
}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id, display_name in NAMES.items():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE, display_name = EXCLUDED.display_name",
                (user_id, display_name),
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
# CASES_DIR yönlendirmesi + sentetik tatil takvimi (mevcut PG testlerinin deseni).
# ----------------------------------------------------------------

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
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_t1_pgint_"))
_SYSTEM_TEMP = Path(tempfile.gettempdir())
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
check(
    "the CASES_DIR redirect sweep found ui.services.paths and every src module the real chain touches",
    all(any(getattr(m, "__name__", "") == name for m in _cases_dir_holders) for name in (
        "ui.services.paths", "manual_fact_entry_engine", "fact_approval", "fact_verification",
        "timeline_engine", "timeline_validator", "timeline_approval", "deadline_engine",
        "deadline_approval", "deadline_validator")),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES
_pg_deadline_rule_selection_policy.DATA_DIR = _TMP_ROOT / "data"

_cal_dir = _TMP_ROOT / "synthetic_holiday_calendar"
_cal_dir.mkdir(parents=True)
_cal_path = _cal_dir / "holiday_calendar.json"
_cal_doc = {
    "schema_version": 1, "calendar_id": "tr_official_holiday_calendar_v1", "calendar_version": 1,
    "effective_from": "2026-01-01", "jurisdiction": "TR",
    "weekend_policy": {"non_working_weekdays": [5, 6], "notes": None},
    "half_day_policy": "not_decided",
    "years": [{"year": 2026, "verified": True,
               "verification_ref": "office_flow_pg_test_only_synthetic_verification_ref",
               "source_refs": [{"source_kind": "test_fixture",
                                "citation": "Office-flow PG test-only synthetic calendar - NOT a real legal source.",
                                "url": None}],
               "holidays": []}],
    "governance": {"change_approval": "test-only", "verification_authority": "test-only", "notes": None},
    "notes": "Office-flow PG test-only synthetic calendar (Prensip 18).",
}
_pg_holiday_calendar_validator.attach_fixture_verification(_cal_doc, seed="office_flow_pg_test_only_synthetic")
if not _pg_holiday_calendar_validator.validate_holiday_calendar(calendar=_cal_doc)["valid"]:
    raise AssertionError("synthetic holiday calendar fixture is itself invalid")
_cal_path.write_text(json.dumps(_cal_doc, ensure_ascii=False, indent=2), encoding="utf-8")
_pg_deadline_calculator.DEFAULT_HOLIDAY_CALENDAR_PATH = _cal_path


# ----------------------------------------------------------------
# İzleme: sys.addaudithook (YALNIZ KAYIT; engelleme yok, runner guard'ı yeniden kurulmaz).
# ----------------------------------------------------------------

WATCH = {"source": None, "source_name": None}
SOURCE_EVENTS = []
TEMP_EVENTS = []
NET_EVENTS = []
ENV_OPEN_EVENTS = []
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _is_source(path) -> bool:
    name = WATCH["source_name"]
    if not name:
        return False
    try:
        text = os.fspath(path) if not isinstance(path, int) else ""
    except TypeError:
        return False
    if os.path.basename(str(text)) != name:
        return False
    return os.path.normcase(os.path.realpath(str(text))) == WATCH["source"]


def _audit(event, args):
    try:
        if event == "open" and args:
            path, mode, flags = (list(args) + [None, None])[:3]
            if _is_source(path):
                text_mode = isinstance(mode, str) and any(c in mode for c in "wax+")
                flag_write = isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
                if text_mode or flag_write:
                    SOURCE_EVENTS.append(("open-write", str(mode), flags))
            if isinstance(path, (str, bytes, os.PathLike)) and os.path.basename(str(path)).startswith(".env"):
                ENV_OPEN_EVENTS.append(str(path))
        elif event in ("os.remove", "os.rmdir", "os.truncate", "shutil.rmtree", "os.chmod") and args:
            if _is_source(args[0]):
                SOURCE_EVENTS.append((event,))
        elif event in ("os.rename", "shutil.move") and args:
            if _is_source(args[0]) or (len(args) > 1 and _is_source(args[1])):
                SOURCE_EVENTS.append((event,))
        elif event == "tempfile.mkstemp" and args:
            TEMP_EVENTS.append(("mkstemp", str(args[0])))
        elif event == "tempfile.mkdtemp" and args:
            TEMP_EVENTS.append(("mkdtemp", str(args[0])))
        elif event.startswith("socket.connect") or event in ("socket.sendto", "socket.sendmsg"):
            addr = args[1] if len(args) > 1 else None
            host = addr[0] if isinstance(addr, tuple) and addr else ""
            if isinstance(addr, tuple) and str(host).lower() not in _LOOPBACK:
                NET_EVENTS.append((event, "non-loopback"))
        elif event in ("socket.getaddrinfo", "socket.gethostbyname"):
            host = args[0] if args else ""
            if str(host).lower() not in _LOOPBACK and host not in (None, ""):
                NET_EVENTS.append((event, "non-loopback"))
    except Exception:
        pass


sys.addaudithook(_audit)


def file_identity(path):
    stat_result = os.stat(path)
    return (hashlib.sha256(Path(path).read_bytes()).hexdigest(), stat_result.st_size, stat_result.st_mtime_ns)


# ----------------------------------------------------------------
# Senaryo düzeneği
# ----------------------------------------------------------------

PDF_BYTES = b"%PDF-1.4\n% sentetik pilot belgesi - GERCEK DEGIL\n" + b"x" * 64 + b"\n%%EOF\n"
PDF_SHA = hashlib.sha256(PDF_BYTES).hexdigest()
SYNTH_TEXT = (
    "SENTETIK VERGİ CEZA İHBARNAMESİ - GERÇEK DEĞİL\n"
    "Düzenleme tarihi 05.02.2026 ve vade tarihi 06.02.2026 olarak kayıtlıdır.\n"
    "İhbarname mükellefe 10.02.2026 tarihinde tebliğ edilmiştir.\n"
    "Bilgi için ek yazı 15.02.2026 tarihlidir.\n"
)
SENT_DATES = ["10.02.2026", "2026-02-10", "12.03.2026", "2026-03-12", "13.03.2026", "2026-03-13"]
SENT_TEXT = "tarihinde tebliğ edilmiştir"
SOURCE_STEM = f"ihbarname_kaynak_{RUN_TOKEN}"


class ScriptedIO:
    def __init__(self, answers, events, on_ask=None, on_say=None):
        self.answers = {k: (list(v) if isinstance(v, (list, tuple)) else [v]) for k, v in answers.items()}
        self.asked, self.said = [], []
        self.events = events
        self.on_ask, self.on_say = on_ask, on_say

    def ask(self, key, prompt):
        self.asked.append(key)
        self.events.append(("ask", key))
        if self.on_ask:
            override = self.on_ask(key)
            if override is not None:
                return override
        queue = self.answers.get(key)
        if not queue:
            raise EOFError()
        return queue.pop(0)

    def say(self, text):
        self.said.append(text)
        self.events.append(("say", text))
        if self.on_say:
            self.on_say(text)


def conn_factories(role_user=None, role_password=None):
    if role_user is None:
        return (lambda: psycopg.connect(dbname=PG_DB), lambda: psycopg.connect(dbname=PG_DB, autocommit=True),
                lambda: psycopg.connect(dbname=PG_DB))
    kw = dict(dbname=PG_DB, user=role_user, password=role_password)
    return (lambda: psycopg.connect(**kw), lambda: psycopg.connect(autocommit=True, **kw),
            lambda: psycopg.connect(**kw))


class SpyBackend(flow_module.RealChainBackend):
    def __init__(self, *args, events, **kwargs):
        super().__init__(*args, **kwargs)
        self._events = events

    def _note(self, name):
        self._events.append(("backend", name))


for _name in ("manual_fact", "promote_fact", "verify_fact", "generate_timeline", "promote_timeline",
              "generate_deadline", "approve_deadline", "canonical_report"):
    def _make(name):
        base = getattr(flow_module.RealChainBackend, name)

        def wrapper(self, *args, **kwargs):
            self._note(name)
            return base(self, *args, **kwargs)
        return wrapper
    setattr(SpyBackend, _name, _make(_name))


class Ctx:
    pass


def start_ctx(tag, *, role="lawyer", user=LAWYER_ID, dosya_kodu=None, factories=None, source_bytes=PDF_BYTES, office=None):
    ctx = Ctx()
    ctx.tag = tag
    ctx.office = office if office is not None else _TMP_ROOT / f"office_{tag}"
    if office is None:
        ctx.office.mkdir()
    ctx.source_dir = _TMP_ROOT / f"kaynak_{tag}"
    ctx.source_dir.mkdir()
    ctx.source = ctx.source_dir / f"{SOURCE_STEM}_{tag}.pdf"
    ctx.source.write_bytes(source_bytes)
    os.chmod(ctx.source, stat.S_IREAD)
    ctx.source_identity = file_identity(ctx.source)
    ctx.case_id = f"t1pg{RUN_TOKEN}{tag}"
    ctx.dosya_kodu = dosya_kodu or f"DK{RUN_TOKEN}{tag}"
    ctx.user = user
    ctx.events = []
    ctx.factories = factories or conn_factories()
    seed_assignment(user, ctx.case_id, role)
    return ctx


def base_answers(ctx, *, kor="12.03.2026", tarih="10.02.2026", select="1", name=None, extra=None):
    name = name or NAMES[ctx.user]
    answers = {
        "kimlik_ad": name, "sayfa_sayisi": "1", "vergi_turleri": "KDV",
        "tebligat_tarihi": tarih, "tebligat_sayfa": "1", "kor_son_gun": kor, "adli_tatil": "no",
        "stopping_durum": "none", "stopping_ref": "BEYAN-T1", "aday_secimi": select,
        "dogrulama_karari": "evet", "onay_ad": name,
    }
    answers.update(extra or {})
    return answers


def new_flow(ctx, answers, *, on_ask=None, on_say=None, fs=None, clock=None, probes=None):
    authz_cf, mutation_cf, report_cf = ctx.factories
    backend = SpyBackend(actor_user_id=ctx.user, authz_conn_factory=authz_cf, mutation_conn_factory=mutation_cf,
                         report_conn_factory=report_cf, events=ctx.events)
    io_obj = ScriptedIO(answers, ctx.events, on_ask=on_ask, on_say=on_say)
    flow = flow_module.OfficeFlow(
        office_root=ctx.office, case_root=_TMP_CASES, backend=backend, io=io_obj,
        extractor=lambda path: SYNTH_TEXT, repo_root=REPO_ROOT, allow_system_drive=True, fs=fs, clock=clock,
        preflight_options=probes,
    )
    ctx.flow, ctx.io, ctx.backend = flow, io_obj, backend
    return flow


def watch_source(ctx):
    WATCH["source"] = os.path.normcase(os.path.realpath(str(ctx.source)))
    WATCH["source_name"] = ctx.source.name
    del SOURCE_EVENTS[:]


def run_new(ctx, answers, **kwargs):
    watch_source(ctx)
    flow = new_flow(ctx, answers, **{k: v for k, v in kwargs.items() if k in ("on_ask", "on_say", "fs", "clock", "probes")})
    run_id = flow.run_new(case_id=ctx.case_id, dosya_kodu=ctx.dosya_kodu, source_pdf=ctx.source)
    ctx.run_id = run_id
    ctx.paths = records.build_run_paths(ctx.office, _TMP_CASES, ctx.case_id, run_id)
    return run_id


def resume(ctx, answers, **kwargs):
    watch_source(ctx)
    flow = new_flow(ctx, answers, **{k: v for k, v in kwargs.items() if k in ("on_ask", "on_say", "fs", "clock", "probes")})
    return flow.continue_run(ctx.run_id)


def state_of(ctx):
    return records.load_run_state(ctx.paths.run_dir)


def kayitlar(ctx):
    return sorted(p.name for p in (ctx.office / "kayitlar").iterdir())


def read_records(ctx, prefix):
    out = []
    for name in kayitlar(ctx):
        if name.startswith(prefix):
            out.append(json.loads((ctx.office / "kayitlar" / name).read_bytes().decode("utf-8")))
    return out


def source_intact(ctx):
    return (ctx.source.exists() and file_identity(ctx.source) == ctx.source_identity
            and not SOURCE_EVENTS)


def all_record_text(ctx):
    return "".join((ctx.office / "kayitlar" / n).read_bytes().decode("utf-8") for n in kayitlar(ctx))


def sentinels(ctx, run_id=None):
    items = list(SENT_DATES) + [SENT_TEXT, ctx.case_id, intake.DOC_ID, ctx.source.stem, PDF_SHA, "KDV",
                                NAMES[ctx.user], str(ctx.source_dir), str(ctx.office), ctx.dosya_kodu, ".pdf"]
    if run_id:
        items.append(run_id)
    return items


def run_cli(argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = cli_mutate.main(
        argv, authz_conn_factory=lambda: psycopg.connect(dbname=PG_DB),
        mutation_conn_factory=lambda: psycopg.connect(dbname=PG_DB, autocommit=True),
        stdout=stdout, stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def downgrade_verification(ctx):
    """Karşılaştırmadan SONRA doğrulanmış girdiyi değiştirir (facts canonical)."""
    facts_path = ctx.paths.case_dir / "documents" / intake.DOC_ID / "extractions" / "facts.json"
    fact_id = json.loads(facts_path.read_bytes())["facts"][0]["fact_id"]
    return run_cli([
        "verification", "--case", ctx.case_id, "--document", intake.DOC_ID, "--fact-id", fact_id,
        "--actor-user-id", str(ctx.user), "--apply", "--target-state", "unverified",
        "--expected-hash", hashlib.sha256(facts_path.read_bytes()).hexdigest(),
    ])


def count_family(ctx, family):
    return sum(1 for r in journal_rows(f"case:{ctx.case_id}") if r["family"] == family and r["state"] == "completed")


def unknown_paths(paths):
    """Kapalı tür listesinde OLMAYAN dosyalar (yalnız tanı/ayrıntı için)."""
    found = []
    for root, classify in ((paths.case_dir, cleanup.classify_case_file), (paths.run_dir, cleanup.classify_run_file)):
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                rel = os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/")
                if classify(rel) is None:
                    found.append(rel)
    return sorted(found)


def runs_of(office):
    runs = Path(office) / "runs"
    return [p.name for p in runs.iterdir()] if runs.is_dir() else []


def tree_listing(root):
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            out.append(os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/"))
    return sorted(out)


class FaultyFs(cleanup.FsOps):
    def __init__(self, *, deny_substring=None, fail_after=None, kill_after=None):
        self.deny_substring, self.fail_after, self.kill_after = deny_substring, fail_after, kill_after
        self.calls = 0

    def unlink(self, path):
        self.calls += 1
        if self.deny_substring and self.deny_substring in str(path).replace("\\", "/"):
            raise PermissionError("denied")
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("injected")
        if self.kill_after is not None and self.calls > self.kill_after:
            raise SimulatedKill()
        super().unlink(path)


class SimulatedKill(BaseException):
    pass


_system_temp_before = set(os.listdir(_SYSTEM_TEMP))

PINNED_TEXT_COLUMNS = {tuple(item.split(".")) for item in (
    "iam.case_assignments.case_id", "iam.case_assignments.role", "iam.external_identities.issuer",
    "iam.external_identities.subject", "iam.global_resource_grant_events.capability",
    "iam.global_resource_grant_events.event_type", "iam.global_resource_grant_events.resource",
    "iam.global_resource_grants.capability", "iam.global_resource_grants.resource",
    "iam.oidc_login_transactions.nonce_hash", "iam.oidc_login_transactions.pkce_enc_alg",
    "iam.oidc_login_transactions.pkce_key_id", "iam.oidc_login_transactions.required_authentication_context_id",
    "iam.oidc_login_transactions.state_hash", "iam.security_events.case_id", "iam.security_events.event_type",
    "iam.security_events.mfa_assurance_level", "iam.security_events.mfa_assurance_policy_version",
    "iam.security_events.reason_code", "iam.security_events.requested_capability", "iam.security_events.role",
    "iam.sessions.token_hash", "iam.user_roles.role", "iam.users.display_name",
    "mutation.mutation_journal.action_family", "mutation.mutation_journal.actor_label",
    "mutation.mutation_journal.expected_post_hash", "mutation.mutation_journal.failure_code",
    "mutation.mutation_journal.idempotency_key", "mutation.mutation_journal.observed_post_hash",
    "mutation.mutation_journal.pre_hash", "mutation.mutation_journal.pre_revision",
    "mutation.mutation_journal.reconciled_by_actor_ref", "mutation.mutation_journal.reconciled_by_actor_type",
    "mutation.mutation_journal.request_fingerprint", "mutation.mutation_journal.resolution_code",
    "mutation.mutation_journal.resource_key", "mutation.mutation_journal.state",
    "mutation.mutation_journal.target_ref", "mutation.mutation_journal.target_state",
    "mutation.mutation_resources.resource_key",
)}

try:
    # ============================================================
    # S1 - UYUMLU hesap -> rapor kontrolü -> silme
    # ============================================================
    s1 = start_ctx("s1")
    answers = base_answers(s1)
    run_id = run_new(s1, answers)
    # Sıra kanıtı: olay günlüğünde F2 sorularından SONRA ilk backend çağrısı / sistem sonucu.
    events = s1.events
    first_backend = next(i for i, e in enumerate(events) if e[0] == "backend" and e[1] == "manual_fact")
    last_f2_ask = max(i for i, e in enumerate(events) if e == ("ask", "stopping_ref"))
    first_candidate_say = next((i for i, e in enumerate(events) if e[0] == "say" and "ADAY SATIR" in e[1]), -1)
    first_system_say = next((i for i, e in enumerate(events) if e[0] == "say" and "SİSTEMİN SONUCU" in e[1]), -1)
    first_date_say = next((i for i, e in enumerate(events) if e[0] == "say" and any(d in e[1] for d in ("10.02.2026", "12.03.2026"))), -1)
    check("S1-a F2 independent reading was asked BEFORE any candidate line/system result/backend call",
          last_f2_ask < first_candidate_say < first_backend < first_system_say, f"{last_f2_ask},{first_candidate_say},{first_backend},{first_system_say}")
    check("S1-b no date was printed before the F2 reading was recorded (first date appears at/after the candidate list)",
          first_date_say >= first_candidate_say > last_f2_ask, f"{first_date_say},{first_candidate_say}")
    check("S1-c the reading record file exists and holds the lawyer's date/last-day, page and the session identity snapshot",
          (lambda r: r["tebligat_tarihi"] == "2026-02-10" and r["kor_son_gun"] == "2026-03-12" and r["sayfa"] == 1
           and r["kimlik"]["user_id"] == LAWYER_ID and r["kimlik"]["display_name"] == NAMES[LAWYER_ID])(records.load_reading_record(s1.paths)))
    st = state_of(s1)
    check("S1-d comparison UYUMLU: state UYUMLU_RAPOR_KONTROLU, system calculated 2026-03-12 == the lawyer's blind last day",
          st.state == "UYUMLU_RAPOR_KONTROLU" and st["sistem_ozeti"]["calculated_deadline"] == "2026-03-12"
          and st["sistem_ozeti"]["calculation_state"] == "calculated", f"{st.data!r}")
    check("S1-e the lawyer approval was journaled exactly once (approval.deadline completed) and canonical deadline.json exists",
          count_family(s1, "approval.deadline") == 1 and (s1.paths.case_dir / "deadlines" / "deadline.json").is_file())
    rows = journal_rows(f"case:{s1.case_id}")
    check("S1-f every journal row of the case is completed and attributed to the session user (typed name never selects the actor)",
          rows and all(r["state"] == "completed" and r["actor"] == LAWYER_ID for r in rows), f"{rows!r}")
    check("S1-g the Pilot Hesap Raporu exists in the run dir and carries the canonical deadline_report output",
          s1.paths.report_path.is_file() and "UYUMLU" in s1.paths.report_path.read_text(encoding="utf-8")
          and "ONAYLI SONUCUN RAPORU" in s1.paths.report_path.read_text(encoding="utf-8"))
    plan = cleanup.build_deletion_plan(s1.paths)
    types_s1 = sorted(plan.counts)
    print("INFO S1 derived closed-type counts:", plan.counts, "unknown:", plan.unknown_count)
    check("S1-h the deletion plan classifies EVERY real facade artifact of the chain (unclassified == 0) AND every one is registered in the run manifest (not-in-manifest == 0)",
          plan.ok and plan.unknown_count == 0 and plan.unclassified_count == 0 and plan.unregistered_count == 0,
          f"refusal={plan.refusal_code} unclassified={plan.unclassified_count} unregistered={plan.unregistered_count} unknown={unknown_paths(s1.paths)}")
    manifest_s1 = records.RunManifest.load(s1.paths.manifest_path)
    snap_case, snap_run = cleanup.snapshot_tree(s1.paths.case_dir), cleanup.snapshot_tree(s1.paths.run_dir)
    run_infra = set(cleanup.RUN_INFRA_NAMES)
    check("S1-h2 the manifest written by the REAL chain lists every file present on disk in both roots (set equality; run-infra names and the case marker excepted)",
          snap_case[0] - {records.OWNER_MARKER_NAME} == set(manifest_s1.file_types("case"))
          and snap_run[0] - run_infra == set(manifest_s1.file_types("run")) - run_infra,
          f"case-only-disk={sorted(snap_case[0] - {records.OWNER_MARKER_NAME} - set(manifest_s1.file_types('case')))[:5]} "
          f"case-only-manifest={sorted(set(manifest_s1.file_types('case')) - snap_case[0])[:5]} "
          f"run-only-disk={sorted(snap_run[0] - run_infra - set(manifest_s1.file_types('run')))[:5]}")
    check("S1-h3 every directory on disk in the case root is registered or a parent of a registered file",
          all(d in manifest_s1.dir_rels("case") or any(f.startswith(d + "/") for f in manifest_s1.file_types("case")) for d in snap_case[1]),
          f"{sorted(d for d in snap_case[1] if d not in manifest_s1.dir_rels('case'))[:5]}")
    check("S1-i the closed copy types seen in a real chain are exactly the five declared types",
          set(plan.counts) <= set(records.COPY_TYPES) and {"CALISMA_DIZINI_BELGE_KOPYASI", "CIKARILMIS_METIN",
          "CALISMA_DOSYALARI", "PILOT_HESAP_RAPORU"} <= set(plan.counts), f"{types_s1}")

    import re as _re0
    derived = sorted({_re0.sub(r"[0-9]{8}_[0-9]{6}[_0-9a-f]*", "<ts>", _re0.sub(r"ihbarname_001", "<doc>", rel))
                      for rel in tree_listing(s1.paths.case_dir)})
    print("INFO derived case-dir artifact patterns (all classified):", derived)
    # Deletion before 'kontrol tamamlandı' / not in a deletion-entry state is refused.
    try:
        flow_module.OfficeFlow.delete_run(s1.flow, s1.paths, state_of(s1))
        refused = None
    except records.OfficeFlowError as error:
        refused = error.code
    check("S1-j deletion is refused while the report is not yet checked (no automatic deletion path)",
          refused == "SILME_DURUMU_UYGUN_DEGIL" and s1.paths.case_dir.exists() and s1.paths.run_dir.exists(), str(refused))

    resume(s1, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "evet", "silme_tam_ad": NAMES[LAWYER_ID],
                "silme_kod": s1.dosya_kodu, "silme_onay": "SİLMEYİ ONAYLIYORUM", "kimlik_ad": NAMES[LAWYER_ID]})
    results = read_records(s1, "test_sonucu_")
    check("S1-k exactly one pilot test result was written: UYUMLU / ILK_KONTROL, closed keys, no time/identity/hash field",
          len(results) == 1 and results[0] == {"kayit_surumu": 1, "yazilim_surumu": records.SOFTWARE_VERSION,
                                               "sonuc": "UYUMLU", "kontrol_turu": "ILK_KONTROL"}, f"{results!r}")
    imha = [json.loads((s1.office / "kayitlar" / n).read_bytes().decode("utf-8")) for n in kayitlar(s1) if n.startswith("imha_")]
    check("S1-l the deletion wrote BASLADI then SONUC=TAMAMLANDI (scope YALNIZ_PILOT_KOPYALARI, DB records listed as NOT deleted)",
          [r["asama"] for r in imha] == ["BASLADI", "SONUC"] and imha[-1]["genel_sonuc"] == "TAMAMLANDI"
          and imha[-1]["tamamlandi_kapsami"] == "YALNIZ_PILOT_KOPYALARI"
          and imha[-1]["silinmeyenler"] == ["VERITABANI_ISLEM_KAYITLARI"], f"{imha!r}")
    check("S1-m both owned directories are gone (case dir, run dir) after verification",
          not s1.paths.case_dir.exists() and not s1.paths.run_dir.exists())
    check("S1-n kayitlar/ holds ONLY the test result + the two imha records (nothing else, nothing deleted from it)",
          len(kayitlar(s1)) == 3 and sum(n.startswith("test_sonucu_") for n in kayitlar(s1)) == 1
          and sum(n.startswith("imha_") for n in kayitlar(s1)) == 2)
    text_all = all_record_text(s1)
    check("S1-o NO sentinel (dates, excerpt, case/doc ids, file name, PDF hash, run id, display name, paths) in any of the records",
          not any(s in text_all for s in sentinels(s1, run_id)), str([s for s in sentinels(s1, run_id) if s in text_all]))
    check("S1-p the database journal rows REMAIN after the deletion (DB records are not deleted)",
          len(journal_rows(f"case:{s1.case_id}")) >= 6)
    check("S1-q the ORIGINAL PDF is intact: same sha256/size/mtime_ns, still readable, NO write/delete/rename audit event targeted it",
          source_intact(s1) and Path(s1.source).read_bytes() == PDF_BYTES, f"events={SOURCE_EVENTS!r}")

    # ============================================================
    # S2 - UYUŞMAZLIK
    # ============================================================
    s2 = start_ctx("s2")
    run_new(s2, base_answers(s2, kor="13.03.2026"))
    st2 = state_of(s2)
    report_before = hashlib.sha256(s2.paths.report_path.read_bytes()).hexdigest()
    check("S2-a one day off: state UYUSMAZLIK_INCELEME_ACIK, the approval step was NEVER offered (no 'onay_ad' prompt)",
          st2.state == "UYUSMAZLIK_INCELEME_ACIK" and "onay_ad" not in s2.io.asked, f"{st2.state} {s2.io.asked}")
    check("S2-b no approval journal row and NO canonical deadline.json was written",
          count_family(s2, "approval.deadline") == 0 and not (s2.paths.case_dir / "deadlines" / "deadline.json").exists())
    check("S2-c the Pilot Hesap Raporu exists and states UYUSMAZLIK (the comparison record does not depend on approval)",
          s2.paths.report_path.is_file() and "UYUSMAZLIK" in s2.paths.report_path.read_text(encoding="utf-8"))
    try:
        s2.flow.delete_run(s2.paths, state_of(s2))
        refused = None
    except records.OfficeFlowError as error:
        refused = error.code
    check("S2-d a deletion request while the review is open is REFUSED (INCELEME_ACIK) and nothing was deleted",
          refused == "INCELEME_ACIK" and s2.paths.case_dir.exists() and s2.paths.run_dir.exists(), str(refused))
    resume(s2, {"inceleme_kapat": "hayır"}, clock=lambda: None)
    resume(s2, {"inceleme_kapat": "hayır"})
    check("S2-e after two later launches (restart / time passing) the report and run state are untouched; no automatic deletion",
          hashlib.sha256(s2.paths.report_path.read_bytes()).hexdigest() == report_before
          and state_of(s2).state == "UYUSMAZLIK_INCELEME_ACIK" and s2.paths.case_dir.exists())
    check("S2-f UYUSMAZLIK can never transition to an UYUMLU state (state machine)",
          not records.transition_allowed("UYUSMAZLIK_INCELEME_ACIK", "KONTROL_TAMAM")
          and not records.transition_allowed("UYUSMAZLIK_INCELEME_ACIK", "UYUMLU_RAPOR_KONTROLU")
          and not records.transition_allowed("INCELEME_KAPALI", "KONTROL_TAMAM"))
    resume(s2, {"inceleme_kapat": "İNCELEMEYİ KAPAT", "kategori": "SURE_KURALI", "silme_simdi": "evet",
                "silme_tam_ad": NAMES[LAWYER_ID], "silme_kod": s2.dosya_kodu, "silme_onay": "SİLMEYİ ONAYLIYORUM",
                "kimlik_ad": NAMES[LAWYER_ID]})
    results2 = read_records(s2, "test_sonucu_")
    check("S2-g closing wrote ONE result: UYUSMAZLIK + SURE_KURALI, never UYUMLU, no 'doğru' claim",
          len(results2) == 1 and results2[0]["sonuc"] == "UYUSMAZLIK" and results2[0]["hata_kategorisi"] == "SURE_KURALI"
          and "doğru" not in json.dumps(results2[0], ensure_ascii=False), f"{results2!r}")
    check("S2-h after closing, the deletion step ran: both directories gone, imha SONUC TAMAMLANDI",
          not s2.paths.case_dir.exists() and not s2.paths.run_dir.exists()
          and any('"TAMAMLANDI"' in (s2.office / "kayitlar" / n).read_text(encoding="utf-8") for n in kayitlar(s2)
                  if n.startswith("imha_")))
    check("S2-i the original PDF is intact (sha256/size/mtime_ns + no write/delete audit event)", source_intact(s2), f"{SOURCE_EVENTS!r}")

    # --- ikinci deneme: aynı dosya, yeni koşu; önceki uyuşmazlık dokunulmaz ---
    a = start_ctx("s2a", dosya_kodu=f"DK{RUN_TOKEN}rr")
    run_new(a, base_answers(a, kor="14.03.2026"))
    report_a = hashlib.sha256(a.paths.report_path.read_bytes()).hexdigest()
    state_a = json.dumps(state_of(a).data, sort_keys=True)
    b = start_ctx("s2b", dosya_kodu=a.dosya_kodu, office=a.office)
    run_new(b, base_answers(b))
    check("S2-j the first run of a file is ILK_KONTROL, the second run on the SAME file after the system result was seen is YENIDEN_KONTROL",
          state_of(a)["kontrol_turu"] == "ILK_KONTROL" and state_of(b)["kontrol_turu"] == "YENIDEN_KONTROL")
    check("S2-k the previous UYUSMAZLIK run was neither deleted nor overwritten (report bytes + run state identical)",
          a.paths.report_path.is_file() and hashlib.sha256(a.paths.report_path.read_bytes()).hexdigest() == report_a
          and json.dumps(state_of(a).data, sort_keys=True) == state_a and a.paths.case_dir.exists())
    resume(b, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır", "kimlik_ad": NAMES[LAWYER_ID]})
    check("S2-l a YENIDEN_KONTROL match is recorded as such in the pilot test result (still UYUMLU)",
          [r for r in read_records(b, "test_sonucu_")][-1]["kontrol_turu"] == "YENIDEN_KONTROL")
    check("S2-m the marker store (dosya_gecmisi) holds only a content-free flag per file code",
          all(json.loads(p.read_bytes()) == {"kayit_surumu": 1, "sonuc_gorulmus": True}
              for p in (b.office / "dosya_gecmisi").iterdir()))
    check("S2-n the original PDFs of both runs are intact", source_intact(b) and (a.source.exists() and file_identity(a.source) == a.source_identity))

    # ============================================================
    # S3 - girdi değişti -> GEÇERSİZ
    # ============================================================
    s3 = start_ctx("s3")
    flipped = {}

    def s3_on_ask(key):
        if key == "onay_ad" and "code" not in flipped:
            s3.paths = records.build_run_paths(s3.office, _TMP_CASES, s3.case_id, runs_of(s3.office)[0])
            flipped["code"] = downgrade_verification(s3)[0]
        return None

    watch_source(s3)
    flow3 = new_flow(s3, base_answers(s3), on_ask=s3_on_ask)
    s3.run_id = flow3.run_new(case_id=s3.case_id, dosya_kodu=s3.dosya_kodu, source_pdf=s3.source)
    s3.paths = records.build_run_paths(s3.office, _TMP_CASES, s3.case_id, s3.run_id)
    check("S3-a the changed verified input (verification downgraded after the comparison) was applied through the real facade",
          flipped.get("code") == 0, str(flipped))
    st3 = state_of(s3)
    check("S3-b the run is GECERSIZ: no approval was journaled, no canonical deadline, no pilot report 'UYUMLU'",
          st3.state == "GECERSIZ" and count_family(s3, "approval.deadline") == 0
          and not (s3.paths.case_dir / "deadlines" / "deadline.json").exists(), f"{st3.state}")
    check("S3-c no pilot test result is written for an invalid run and 'kontrol tamamlandı' is never asked",
          read_records(s3, "test_sonucu_") == [] and "kontrol_tamam" not in s3.io.asked)
    check("S3-d the user was told the old result is unusable (GIRDI_DEGISTI)", any("GIRDI_DEGISTI" in t for t in s3.io.said))
    # GECERSIZ -> silme yolu açık (başarı sonucu yok). Girdiyi DEĞİŞTİREN dış işlem (cli_mutate verification) vaka
    # dizinine akışın bildiriminde OLMAYAN dosyalar yazmıştır: silme önce REDDEDİLİR (H-1), avukat bunları kendi
    # elleriyle kaldırdıktan sonra aynı koşu onayla silinir.
    s3_listing = tree_listing(s3.paths.case_dir) + tree_listing(s3.paths.run_dir)
    resume(s3, {})
    check("S3-e1 H-1/L-6: the files the out-of-band verification wrote are NOT in the run manifest -> deletion REFUSED: nothing deleted, SILME_REDDEDILDI, "
          "no name/code/phrase question, a single REDDEDILDI SONUC record",
          state_of(s3).state == "SILME_REDDEDILDI" and tree_listing(s3.paths.case_dir) + tree_listing(s3.paths.run_dir) == s3_listing
          and not {"silme_tam_ad", "silme_kod", "silme_onay"} & set(s3.io.asked)
          and [r["asama"] for r in read_records(s3, "imha_")] == ["SONUC"] and read_records(s3, "imha_")[0]["genel_sonuc"] == "REDDEDILDI",
          f"{state_of(s3).state} {s3.io.asked}")
    manifest_s3 = records.RunManifest.load(s3.paths.manifest_path)
    snap_s3 = cleanup.snapshot_tree(s3.paths.case_dir)
    stray_files = sorted(snap_s3[0] - {records.OWNER_MARKER_NAME} - set(manifest_s3.file_types("case")))
    check("S3-e2 the unregistered entries are exactly the out-of-band verification artifacts (review / history / backup files)",
          bool(stray_files) and all(("reviews" in f or "history" in f or f.endswith(".bak")) for f in stray_files), f"{stray_files!r}")
    for rel in stray_files:
        os.unlink(s3.paths.case_dir / rel)
    for rel in sorted(snap_s3[1] - manifest_s3.dir_rels("case"), key=len, reverse=True):
        try:
            os.rmdir(s3.paths.case_dir / rel)
        except OSError:
            pass
    resume(s3, {"silme_tam_ad": NAMES[LAWYER_ID], "silme_kod": s3.dosya_kodu, "silme_onay": "SİLMEYİ ONAYLIYORUM",
                "kimlik_ad": NAMES[LAWYER_ID]})
    check("S3-e an invalid run is deleted by the lawyer's separate approval once the foreign entries are gone; the test-result dir holds NO result for it",
          not s3.paths.case_dir.exists() and read_records(s3, "test_sonucu_") == []
          and sorted(r.get("genel_sonuc") or "-" for r in read_records(s3, "imha_")) == ["-", "REDDEDILDI", "TAMAMLANDI"],
          f"{read_records(s3, 'imha_')!r}")
    check("S3-f the original PDF is intact", source_intact(s3), f"{SOURCE_EVENTS!r}")

    # S3 (b): onaydan SONRA değişiklik -> kontrol tamamlandı reddedilir, rapor damgalı.
    s3b = start_ctx("s3b")
    run_new(s3b, base_answers(s3b))
    downgrade_verification(s3b)
    resume(s3b, {"kontrol_tamam": "KONTROL TAMAMLANDI"})
    st3b = state_of(s3b)
    check("S3-g after the approval, a changed input makes the next review step INVALID (state GECERSIZ, report stamped, no result)",
          st3b.state == "GECERSIZ" and "GEÇERSİZ" in s3b.paths.report_path.read_text(encoding="utf-8")
          and read_records(s3b, "test_sonucu_") == [], st3b.state)
    # S3 (c): UYUŞMAZLIK açıkken girdi değişimi -> durum UYUSMAZLIK kalır
    s3c = start_ctx("s3c")
    run_new(s3c, base_answers(s3c, kor="20.03.2026"))
    downgrade_verification(s3c)
    resume(s3c, {"inceleme_kapat": "İNCELEMEYİ KAPAT", "kategori": "NEDEN_HENUZ_BELIRLENEMEDI", "silme_simdi": "hayır"})
    rs = read_records(s3c, "test_sonucu_")
    check("S3-h input change during an open UYUSMAZLIK review: stays UYUSMAZLIK (never promoted), report stamped, result UYUSMAZLIK",
          len(rs) == 1 and rs[0]["sonuc"] == "UYUSMAZLIK" and "GEÇERSİZ" in s3c.paths.report_path.read_text(encoding="utf-8"), f"{rs!r}")

    # ============================================================
    # S4 - silme yarıda kalırsa yanlış imha kaydı yok
    # ============================================================
    def s4_ready(tag):
        c = start_ctx(tag)
        run_new(c, base_answers(c))
        resume(c, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
        assert state_of(c).state == "SILME_ONAYI_BEKLIYOR"
        return c

    def delete_answers(c):
        return {"silme_tam_ad": NAMES[LAWYER_ID], "silme_kod": c.dosya_kodu, "silme_onay": "SİLMEYİ ONAYLIYORUM",
                "kimlik_ad": NAMES[LAWYER_ID]}

    def imha_stages(c):
        return [json.loads((c.office / "kayitlar" / n).read_bytes().decode("utf-8")) for n in kayitlar(c) if n.startswith("imha_")]

    # (a) tek bir yol silinemiyor
    c4a = s4_ready("s4a")
    resume(c4a, delete_answers(c4a), fs=FaultyFs(deny_substring="extractions/facts.json"))
    imha_a = imha_stages(c4a)
    check("S4-a one undeletable path: records BASLADI then SONUC=KISMEN, NEVER TAMAMLANDI; remaining types are listed",
          [r["asama"] for r in imha_a] == ["BASLADI", "SONUC"] and imha_a[-1]["genel_sonuc"] == "KISMEN"
          and any(i["sonuc"] == "KISMEN" for i in imha_a[-1]["kopya_turleri"])
          and all(r.get("genel_sonuc") != "TAMAMLANDI" for r in imha_a), f"{imha_a!r}")
    check("S4-b the lawyer-visible state is SILME_YARIM and the ownership marker is retained so the run can be resumed",
          state_of(c4a).state == "SILME_YARIM" and records.read_owner_marker(c4a.paths.case_dir, run_id=c4a.run_id, kind="case_dir"))
    resume(c4a, delete_answers(c4a))
    imha_a2 = imha_stages(c4a)
    check("S4-c a healthy retry completes: new BASLADI + SONUC=TAMAMLANDI, both directories gone, TAMAMLANDI only AFTER verification",
          [r["asama"] for r in imha_a2][-2:] == ["BASLADI", "SONUC"] and imha_a2[-1]["genel_sonuc"] == "TAMAMLANDI"
          and sum(1 for r in imha_a2 if r.get("genel_sonuc") == "TAMAMLANDI") == 1
          and not c4a.paths.case_dir.exists() and not c4a.paths.run_dir.exists(), f"{imha_a2!r}")
    check("S4-d original PDF intact after the partial + retry sequence", source_intact(c4a), f"{SOURCE_EVENTS!r}")

    # (b) ilk silmeden sonra beklenmeyen istisna
    c4b = s4_ready("s4b")
    resume(c4b, delete_answers(c4b), fs=FaultyFs(fail_after=1))
    imha_b = imha_stages(c4b)
    check("S4-e an unexpected exception after the first unlink -> KISMEN (no TAMAMLANDI), files remain",
          imha_b[-1]["asama"] == "SONUC" and imha_b[-1]["genel_sonuc"] == "KISMEN" and c4b.paths.case_dir.exists(), f"{imha_b!r}")
    resume(c4b, delete_answers(c4b))
    check("S4-f retry completes the remaining owned copies only", not c4b.paths.case_dir.exists() and source_intact(c4b))

    # (c) süreç BASLADI'dan sonra ölür
    c4c = s4_ready("s4c")
    killed = False
    try:
        resume(c4c, delete_answers(c4c), fs=FaultyFs(kill_after=2))
    except SimulatedKill:
        killed = True
    imha_c = imha_stages(c4c)
    check("S4-g process death mid-deletion: the LAST record is BASLADI, no SONUC and NO TAMAMLANDI exists",
          killed and imha_c[-1]["asama"] == "BASLADI" and all("genel_sonuc" not in r for r in imha_c), f"{imha_c!r}")
    open_tokens = outcomes.open_imha_tokens(c4c.office / "kayitlar")
    check("S4-h on restart the interrupted deletion is detected (open BASLADI token)", len(open_tokens) == 1)
    before_remaining = tree_listing(c4c.paths.case_dir) if c4c.paths.case_dir.exists() else []
    resume(c4c, delete_answers(c4c))
    imha_c2 = imha_stages(c4c)
    check("S4-i the restart checked the remaining files and finished: SONUC=TAMAMLANDI only after verification, dirs gone",
          imha_c2[-1]["asama"] == "SONUC" and imha_c2[-1]["genel_sonuc"] == "TAMAMLANDI"
          and not c4c.paths.case_dir.exists() and not c4c.paths.run_dir.exists()
          and outcomes.open_imha_tokens(c4c.office / "kayitlar") == [], f"{imha_c2!r}")
    check("S4-j original PDF intact after the simulated crash + restart", source_intact(c4c), f"{SOURCE_EVENTS!r}")

    # (d) yabancı dosya -> belirsiz sahiplik
    c4d = s4_ready("s4d")
    foreign = c4d.paths.case_dir / "documents" / intake.DOC_ID / "notlar_yabanci.docx"
    foreign.write_bytes(b"yabanci")
    listing_before = tree_listing(c4d.paths.case_dir) + tree_listing(c4d.paths.run_dir)
    resume(c4d, {})   # plan reddedilirse ad/kod/onay cümlesi SORULMAZ (soru gelseydi EOFError)
    imha_d = imha_stages(c4d)
    listing_after = tree_listing(c4d.paths.case_dir) + tree_listing(c4d.paths.run_dir)
    check("S4-k a foreign file inside the owned case dir -> REDDEDILDI: NOTHING deleted, no BASLADI, no TAMAMLANDI",
          imha_d and imha_d[-1]["genel_sonuc"] == "REDDEDILDI" and listing_before == listing_after
          and all(r.get("genel_sonuc") != "TAMAMLANDI" for r in imha_d) and all(r["asama"] == "SONUC" for r in imha_d), f"{imha_d!r}")
    check("S4-l the foreign file survives and the original PDF is intact", foreign.exists() and source_intact(c4d))
    check("S4-l2 L-6: a refused plan asks NO approval question and the state is SILME_REDDEDILDI (not SILME_YARIM)",
          state_of(c4d).state == "SILME_REDDEDILDI" and not {"silme_tam_ad", "silme_kod", "silme_onay"} & set(c4d.io.asked), f"{state_of(c4d).state} {c4d.io.asked}")

    # (d2) H-1: kapalı tür desenine UYAN ama bildirimde OLMAYAN büro dosyaları (gerçek zincir) -> REDDEDILDI
    c4f = s4_ready("s4f")
    pattern_foreign = [
        c4f.paths.case_dir / "documents" / intake.DOC_ID / "baska_muvekkil_dilekce.pdf",
        c4f.paths.case_dir / "deadlines" / "buro_notu.json",
        c4f.paths.run_dir / "pilot_hesap_raporu_eski_muvekkil.txt",
        c4f.paths.tmp_dir / "kisisel_not.docx",
    ]
    for f in pattern_foreign:
        f.write_bytes(b"BUROYA AIT")
    listing_f = tree_listing(c4f.paths.case_dir) + tree_listing(c4f.paths.run_dir)
    plan_f = cleanup.build_deletion_plan(c4f.paths)
    resume(c4f, {})
    imha_f = imha_stages(c4f)
    check("S4-p H-1 REAL CHAIN: office files that merely MATCH closed type names (a .pdf, a .json, a pilot_hesap_raporu*.txt, a tmp/ file) are not in the manifest -> "
          "REDDEDILDI, NOTHING deleted, never TAMAMLANDI, no approval question, SILME_REDDEDILDI",
          not plan_f.ok and plan_f.unregistered_count == 4 and plan_f.unclassified_count == 0
          and imha_f[-1]["genel_sonuc"] == "REDDEDILDI" and all(r["asama"] == "SONUC" for r in imha_f)
          and tree_listing(c4f.paths.case_dir) + tree_listing(c4f.paths.run_dir) == listing_f and all(f.exists() for f in pattern_foreign)
          and state_of(c4f).state == "SILME_REDDEDILDI" and not {"silme_tam_ad", "silme_kod", "silme_onay"} & set(c4f.io.asked),
          f"{plan_f.unregistered_count}/{plan_f.unclassified_count} {imha_f!r}")
    for f in pattern_foreign:
        f.unlink()
    resume(c4f, delete_answers(c4f))
    check("S4-q once the lawyer removes the four foreign files the SAME run is deleted with the full approval (TAMAMLANDI) and the original PDF is intact",
          sorted(r.get("genel_sonuc") or "-" for r in imha_stages(c4f)) == ["-", "REDDEDILDI", "TAMAMLANDI"]
          and not c4f.paths.case_dir.exists() and not c4f.paths.run_dir.exists() and source_intact(c4f), f"{imha_stages(c4f)!r}")

    # (e) sahiplik işareti yok -> yanlış hedef
    c4e = s4_ready("s4e")
    marker = c4e.paths.case_dir / records.OWNER_MARKER_NAME
    marker.unlink()
    listing_before = tree_listing(c4e.paths.case_dir) + tree_listing(c4e.paths.run_dir)
    resume(c4e, {})
    imha_e = imha_stages(c4e)
    listing_after = tree_listing(c4e.paths.case_dir) + tree_listing(c4e.paths.run_dir)
    check("S4-m missing ownership marker (wrong target) -> REDDEDILDI, nothing deleted, never TAMAMLANDI",
          imha_e[-1]["genel_sonuc"] == "REDDEDILDI" and listing_before == listing_after
          and all(r.get("genel_sonuc") != "TAMAMLANDI" for r in imha_e), f"{imha_e!r}")
    check("S4-n original PDF intact", source_intact(c4e))
    offenders = [(c.tag, item) for c in (c4a, c4b, c4c, c4d, c4e)
                 for item in sentinels(c, c.run_id) if item in all_record_text(c)]
    check("S4-o every S4 record set is sentinel-free (no date/hash/path/name/run id)", not offenders, f"{offenders!r}")

    # ============================================================
    # K - kimlik
    # ============================================================
    k1 = start_ctx("k1")
    flow = new_flow(k1, base_answers(k1, name=NAMES[OTHER_ID]))
    try:
        flow.run_new(case_id=k1.case_id, dosya_kodu=k1.dosya_kodu, source_pdf=k1.source)
        code = None
    except records.OfficeFlowError as error:
        code = error.code
    check("K-a a typed name that is NOT the session user's registered name stops at F0 (KIMLIK_TEYIDI_BASARISIZ); no run/case dir created",
          code == "KIMLIK_TEYIDI_BASARISIZ" and not runs_of(k1.office) and not (_TMP_CASES / k1.case_id).exists(), str(code))
    k2 = start_ctx("k2")
    flow = new_flow(k2, base_answers(k2, extra={"onay_ad": NAMES[OTHER_ID]}))
    try:
        flow.run_new(case_id=k2.case_id, dosya_kodu=k2.dosya_kodu, source_pdf=k2.source)
        code = None
    except records.OfficeFlowError as error:
        code = error.code
    k2.run_id = runs_of(k2.office)[0]
    k2.paths = records.build_run_paths(k2.office, _TMP_CASES, k2.case_id, k2.run_id)
    check("K-b the approval name confirmation mismatch (another user's name) -> ONAY_TEYIDI_BASARISIZ, NO approval journaled, state unchanged",
          code == "ONAY_TEYIDI_BASARISIZ" and count_family(k2, "approval.deadline") == 0
          and state_of(k2).state == "KARSILASTIRMA_YAPILDI", f"{code} {state_of(k2).state}")
    try:
        k2.backend.approve_deadline(k2.case_id, expected_pending_sha="0" * 64)
        l5_code = None
    except records.OfficeFlowError as error:
        l5_code = error.code
    check("K-b2 L-5 the REAL backend refuses an approval whose pending sha differs from the one the comparison saw (GIRDI_DEGISTI): NO approval journaled",
          l5_code == "GIRDI_DEGISTI" and count_family(k2, "approval.deadline") == 0, f"{l5_code}")
    resume(k2, {"onay_ad": NAMES[LAWYER_ID], "kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır", "kimlik_ad": NAMES[LAWYER_ID]})
    rows = [r for r in journal_rows(f"case:{k2.case_id}") if r["family"] == "approval.deadline"]
    check("K-c after the correct name the approval is journaled with actor == the SESSION user id (typed name never chooses the actor)",
          len(rows) == 1 and rows[0]["actor"] == LAWYER_ID and state_of(k2).state == "SILME_ONAYI_BEKLIYOR", f"{rows!r}")
    k3 = start_ctx("k3", role="analyst", user=ANALYST_ID)
    flow = new_flow(k3, base_answers(k3))
    try:
        flow.run_new(case_id=k3.case_id, dosya_kodu=k3.dosya_kodu, source_pdf=k3.source)
        code = None
    except records.OfficeFlowError as error:
        code = error.code
    check("K-d a user assigned with a non-lawyer role is refused (YETKI_YOK); nothing created",
          code == "YETKI_YOK" and not runs_of(k3.office))
    k4 = start_ctx("k4")
    k4.user = OTHER_ID  # atanmamış kullanıcı
    flow = new_flow(k4, base_answers(k4, name=NAMES[OTHER_ID]))
    try:
        flow.run_new(case_id=k4.case_id, dosya_kodu=k4.dosya_kodu, source_pdf=k4.source)
        code = None
    except records.OfficeFlowError as error:
        code = error.code
    check("K-e a user with NO assignment to the case is refused (YETKI_YOK)", code == "YETKI_YOK")

    # ============================================================
    # M-A - GERÇEK IAM: devam yollarında yetkisiz kullanıcı hiçbir şey göremez/yazamaz
    # ============================================================
    def ma_fingerprint(ctx):
        out = {}
        for base in (ctx.paths.case_dir, ctx.paths.run_dir, ctx.office / "kayitlar", ctx.office / "dosya_gecmisi"):
            for dp, _d, fs_ in os.walk(base):
                for f in fs_:
                    fp_ = os.path.join(dp, f)
                    out[fp_] = hashlib.sha256(open(fp_, "rb").read()).hexdigest()
        out["journal"] = len(journal_rows(f"case:{ctx.case_id}"))
        return out

    def ma_denied(ctx, user, answers):
        original_user = ctx.user
        ctx.user = user
        before = ma_fingerprint(ctx)
        code = None
        try:
            resume(ctx, answers)
        except records.OfficeFlowError as error:
            code = error.code
        finally:
            ctx.user = original_user
        return code, ma_fingerprint(ctx) == before and ctx.io.said == [] and ctx.io.asked == []

    ma1 = start_ctx("ma1")
    run_new(ma1, base_answers(ma1, kor="13.03.2026"))         # UYUSMAZLIK_INCELEME_ACIK
    ma2 = start_ctx("ma2")
    run_new(ma2, base_answers(ma2))                            # UYUMLU_RAPOR_KONTROLU
    ma3 = start_ctx("ma3")
    run_new(ma3, base_answers(ma3))
    resume(ma3, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})   # SILME_ONAYI_BEKLIYOR
    (ma3.paths.case_dir / "documents" / intake.DOC_ID / "baska_muvekkil.pdf").write_bytes(b"BURO")
    for c_ in (ma1, ma2, ma3):
        seed_assignment(ANALYST_ID, c_.case_id, "analyst")
    NONEXISTENT_ID = 999999
    for label, user in (("an assigned ANALYST (not lawyer)", ANALYST_ID), ("an UNASSIGNED user", OTHER_ID), ("a user that does NOT EXIST in the DB", NONEXISTENT_ID)):
        c1_, k1_ = ma_denied(ma1, user, {"inceleme_kapat": "İNCELEMEYİ KAPAT", "kategori": "SURE_KURALI"})
        c2_, k2_ = ma_denied(ma2, user, {"kontrol_tamam": "KONTROL TAMAMLANDI"})
        c3_, k3_ = ma_denied(ma3, user, {})
        check(f"M-A REAL IAM: {label} cannot close an UYUSMAZLIK review, cannot confirm 'KONTROL TAMAMLANDI', cannot trigger the deletion plan/refusal: "
              "YETKI_YOK on all three paths, NO screen output, NO question, NO file/record/journal change",
              (c1_, c2_, c3_) == ("YETKI_YOK",) * 3 and k1_ and k2_ and k3_, f"{(c1_, c2_, c3_)} {(k1_, k2_, k3_)}")
    check("M-A REAL IAM: nothing was recorded for any of the denied attempts (no test result, no imha record) and the states are unchanged",
          read_records(ma1, "test_sonucu_") == [] and read_records(ma2, "test_sonucu_") == [] and read_records(ma3, "imha_") == []
          and state_of(ma1).state == "UYUSMAZLIK_INCELEME_ACIK" and state_of(ma2).state == "UYUMLU_RAPOR_KONTROLU"
          and state_of(ma3).state == "SILME_ONAYI_BEKLIYOR")
    resume(ma2, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    check("M-A REAL IAM: the assigned lawyer's identical call still works (UYUMLU result written)", len(read_records(ma2, "test_sonucu_")) == 1)

    # ============================================================
    # TF-1 - GERÇEK IAM: atama uzun insan beklemesi SIRASINDA geri alınır; kayıt/silme yazımından HEMEN önce yeniden kontrol
    # (revoke gerçek `UPDATE iam.case_assignments SET revoked_at = now()`; yeniden yetkilendirme `revoked_at = NULL`)
    # ============================================================
    def set_assignment_revoked(ctx, revoked):
        conn_ = pg_connect()
        try:
            with conn_.cursor() as cur_:
                cur_.execute("UPDATE iam.case_assignments SET revoked_at = " + ("now()" if revoked else "NULL")
                             + " WHERE user_id = %s AND case_id = %s", (ctx.user, ctx.case_id))
                return cur_.rowcount
        finally:
            conn_.close()

    def revoke_at(ctx, key_name, snap):
        def hook(key):
            if key == key_name:
                snap["fp"], snap["said"] = ma_fingerprint(ctx), len(ctx.io.said)
                snap["rows"] = set_assignment_revoked(ctx, True)
            return None
        return hook

    def code_of_resume(ctx, answers, **kwargs):
        try:
            resume(ctx, answers, **kwargs)
        except records.OfficeFlowError as error:
            return error.code
        except EOFError:
            return "EOFError(beklenmeyen soru)"
        return None

    def tolerant_resume(ctx, answers):
        """Kurtarma adımı: bozuk (mutasyonlu) bir akışta test çökmek yerine adlandırılmış FAIL ile sürsün."""
        try:
            return resume(ctx, answers)
        except (records.OfficeFlowError, EOFError):
            return None

    def state_name_pg(ctx):
        try:
            return state_of(ctx).state
        except records.OfficeFlowError:
            return "(durum dosyası yok)"

    # W1/W3 gerçek IAM: UYUMLU, 'KONTROL TAMAMLANDI' beklenirken atama geri alınır
    tf1 = start_ctx("tf1")
    run_new(tf1, base_answers(tf1))
    snap_tf1 = {}
    code_tf1 = code_of_resume(tf1, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"}, on_ask=revoke_at(tf1, "kontrol_tamam", snap_tf1))
    print(f"INFO TF-1 PG W1 disk after the refusal: state={state_name_pg(tf1)}, result_records={len(read_records(tf1, 'test_sonucu_'))}, "
          f"journal_rows={len(journal_rows(f'case:{tf1.case_id}'))}")
    check("TF-1 PG W1 REAL IAM: assignment revoked (UPDATE touched 1 row) while 'KONTROL TAMAMLANDI' is awaited -> YETKI_YOK; state stays UYUMLU_RAPOR_KONTROLU, "
          "NO result record, NO journal row, NO file change, NO screen output after the confirmation",
          snap_tf1.get("rows") == 1 and code_tf1 == "YETKI_YOK" and read_records(tf1, "test_sonucu_") == []
          and state_name_pg(tf1) == "UYUMLU_RAPOR_KONTROLU" and ma_fingerprint(tf1) == snap_tf1["fp"] and len(tf1.io.said) == snap_tf1["said"],
          f"{code_tf1} rows={snap_tf1.get('rows')}")
    code_tf1_still = code_of_resume(tf1, {"kontrol_tamam": "KONTROL TAMAMLANDI"})
    check("TF-1 PG W1: while the assignment stays revoked a fresh --devam is also refused at its FIRST step (YETKI_YOK, nothing asked)",
          code_tf1_still == "YETKI_YOK" and tf1.io.asked == [] and read_records(tf1, "test_sonucu_") == [])
    check("TF-1 PG W1: re-assigning the lawyer (revoked_at = NULL) touched exactly 1 row", set_assignment_revoked(tf1, False) == 1)
    tolerant_resume(tf1, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    check("TF-1 PG W1 recovery: the authorised --devam completes from the SAME state with exactly ONE UYUMLU result record (no duplicate), state SILME_ONAYI_BEKLIYOR",
          len(read_records(tf1, "test_sonucu_")) == 1 and read_records(tf1, "test_sonucu_")[0]["sonuc"] == "UYUMLU"
          and state_name_pg(tf1) == "SILME_ONAYI_BEKLIYOR")

    # W4/W5/W6 gerçek IAM: silme onayından ('SİLMEYİ ONAYLIYORUM') sonra, silmeden ÖNCE atama geri alınır
    tf2 = start_ctx("tf2")
    run_new(tf2, base_answers(tf2))
    tolerant_resume(tf2, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır"})
    snap_tf2 = {}
    del_answers = {"silme_tam_ad": NAMES[LAWYER_ID], "silme_kod": tf2.dosya_kodu, "silme_onay": "SİLMEYİ ONAYLIYORUM", "kimlik_ad": NAMES[LAWYER_ID]}
    code_tf2 = code_of_resume(tf2, del_answers, on_ask=revoke_at(tf2, "silme_onay", snap_tf2))
    print(f"INFO TF-1 PG W5 disk after the refusal: state={state_name_pg(tf2)}, imha_records={len(read_records(tf2, 'imha_'))}, "
          f"case_dir_exists={tf2.paths.case_dir.exists()}")
    check("TF-1 PG W5/W6 REAL IAM: revoked after the last confirmation and BEFORE the deletion -> YETKI_YOK; deletion NEVER started: no imha record (no BASLADI), "
          "no binding, every case/run file still on disk and byte-identical, no journal change, state SILME_ONAYI_BEKLIYOR",
          snap_tf2.get("rows") == 1 and code_tf2 == "YETKI_YOK" and read_records(tf2, "imha_") == []
          and records.read_imha_binding(tf2.paths.run_dir, run_id=tf2.run_id) is None and tf2.paths.case_dir.exists()
          and ma_fingerprint(tf2) == snap_tf2["fp"] and state_name_pg(tf2) == "SILME_ONAYI_BEKLIYOR", f"{code_tf2}")
    set_assignment_revoked(tf2, False)
    tolerant_resume(tf2, del_answers)
    imha_tf2 = read_records(tf2, "imha_")
    check("TF-1 PG W5/W6 recovery: the re-assigned lawyer's --devam performs the deletion: BASLADI then SONUC=TAMAMLANDI exactly once, both owned directories gone, still ONE result record",
          imha_tf2 and [r["asama"] for r in imha_tf2] == ["BASLADI", "SONUC"] and imha_tf2[-1]["genel_sonuc"] == "TAMAMLANDI"
          and not tf2.paths.case_dir.exists() and len(read_records(tf2, "test_sonucu_")) == 1)

    # L-1 (W7) gerçek IAM: onay ADI beklenirken atama geri alınır. Red artık `_approval_phase` içindeki canlı yetki
    # sorgusundan gelir (ilk yazım olan `onay_kimlik` öncesi); gerçek onay yolu hiç çağrılmaz.
    tf3 = start_ctx("tf3")
    holder_tf3 = {}

    def revoke_before_approval(key):
        if key == "onay_ad":
            holder_tf3["rows"] = set_assignment_revoked(tf3, True)
        return None

    code_tf3 = None
    try:
        run_new(tf3, base_answers(tf3), on_ask=revoke_before_approval)
    except records.OfficeFlowError as error:
        code_tf3 = error.code
    # run_new reddedildi: koşu kimliği/yolları diskteki tek koşu dizininden okunur
    tf3.run_id = [p.name for p in (tf3.office / "runs").iterdir()][0]
    tf3.paths = records.build_run_paths(tf3.office, _TMP_CASES, tf3.case_id, tf3.run_id)

    def onay_pg(ctx):
        try:
            return state_of(ctx).get("onay_kimlik")
        except records.OfficeFlowError:
            return "(durum dosyası yok)"

    canonical_tf3 = _TMP_CASES / tf3.case_id / "deadlines" / "deadline.json"
    check("TF-1 PG W7 REAL IAM: revoked while the approval NAME is awaited (UPDATE touched 1 row) -> exactly YETKI_YOK; NO approval.deadline journal row, NO canonical "
          "deadline.json, no test result record, and the run state holds NO 'onay_kimlik' (state stays KARSILASTIRMA_YAPILDI)",
          holder_tf3.get("rows") == 1 and code_tf3 == "YETKI_YOK" and count_family(tf3, "approval.deadline") == 0
          and not canonical_tf3.exists() and read_records(tf3, "test_sonucu_") == []
          and onay_pg(tf3) is None and state_name_pg(tf3) == "KARSILASTIRMA_YAPILDI", f"{code_tf3} {onay_pg(tf3)!r} {state_name_pg(tf3)}")
    print(f"INFO TF-1 PG W7: approval name step refused with code {code_tf3}")
    check("TF-1 PG W7: re-assigning the lawyer (revoked_at = NULL) touched exactly 1 row", set_assignment_revoked(tf3, False) == 1)
    mark_tf3 = {}

    def mark_onay_time(key):
        """Ad sorulduğu anki GERÇEK DB saati: taze sorgu bundan SONRA, bayat (continue_run başı) anlık görüntü bundan ÖNCE alınmış olur."""
        if key == "onay_ad":
            conn_t = pg_connect()
            try:
                with conn_t.cursor() as cur_t:
                    cur_t.execute("SELECT clock_timestamp()")
                    mark_tf3["t"] = cur_t.fetchone()[0]
            finally:
                conn_t.close()
        return None

    try:
        resume(tf3, {"onay_ad": NAMES[LAWYER_ID], "kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "hayır", "kimlik_ad": NAMES[LAWYER_ID]},
               on_ask=mark_onay_time)
    except (records.OfficeFlowError, EOFError):
        pass
    onay_tf3 = onay_pg(tf3)
    reading_tf3 = records.load_reading_record(tf3.paths)
    check("TF-1 PG W7 recovery: the authorised --devam completes the approval EXACTLY ONCE (ONE approval.deadline journal row, canonical deadline.json exists), writes 'onay_kimlik' "
          "(exact key set, ek_teyit_eslesti True), state SILME_ONAYI_BEKLIYOR, exactly ONE UYUMLU result record",
          count_family(tf3, "approval.deadline") == 1 and canonical_tf3.exists() and isinstance(onay_tf3, dict)
          and set(onay_tf3) == {"user_id", "display_name", "windows_user", "machine_name", "db_time", "ek_teyit_eslesti"} and onay_tf3["ek_teyit_eslesti"] is True
          and state_name_pg(tf3) == "SILME_ONAYI_BEKLIYOR" and len(read_records(tf3, "test_sonucu_")) == 1
          and read_records(tf3, "test_sonucu_")[0]["sonuc"] == "UYUMLU", f"{onay_tf3!r} {state_name_pg(tf3)}")
    check("TF-1 PG W7 (same user): the approval mark's user_id equals the first identity's user_id in the reading record (the name confirmation and the fresh live query bind to ONE user, the real IAM lawyer)",
          isinstance(onay_tf3, dict) and onay_tf3["user_id"] == reading_tf3["kimlik"]["user_id"] == LAWYER_ID
          and onay_tf3["display_name"] == reading_tf3["kimlik"]["display_name"] == NAMES[LAWYER_ID])
    import datetime as _dt_w7
    check("TF-1 PG W7 (fresh identity, REAL DB clock): 'onay_kimlik.db_time' was taken AFTER the approval-name question was asked in the --devam run (a snapshot passed in from "
          "the start of continue_run would predate it)",
          isinstance(onay_tf3, dict) and "t" in mark_tf3 and _dt_w7.datetime.fromisoformat(onay_tf3["db_time"]) >= mark_tf3["t"], f"{onay_tf3!r} {mark_tf3!r}")

    # ============================================================
    # N - normal yerel hesap (uygulama DB rolü) çalışır; dış YZ reddedilir
    # ============================================================
    from psycopg import sql as _sql

    role_name = f"t1app_{RUN_TOKEN}"
    role_password = uuid.uuid4().hex
    admin = pg_connect()
    try:
        with admin.cursor() as cur:
            cur.execute(_sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}")
                        .format(_sql.Identifier(role_name), _sql.Literal(role_password)))
            cur.execute(_sql.SQL("GRANT vergi_app TO {}").format(_sql.Identifier(role_name)))
    finally:
        admin.close()
    try:
        app_factories = conn_factories(role_name, role_password)
        probe = app_factories[0]()
        with probe.cursor() as cur:
            cur.execute("SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)")
            who, is_super = cur.fetchone()
        probe.close()
        check("N-a the connections of this test run as a NON-superuser application role (membership of vergi_app only)",
              who == role_name and is_super is False, f"{who} {is_super}")
        n1 = start_ctx("n1", user=APPUSER_ID, factories=app_factories)
        run_new(n1, base_answers(n1))
        resume(n1, {"kontrol_tamam": "KONTROL TAMAMLANDI", "silme_simdi": "evet", "silme_tam_ad": NAMES[APPUSER_ID],
                    "silme_kod": n1.dosya_kodu, "silme_onay": "SİLMEYİ ONAYLIYORUM", "kimlik_ad": NAMES[APPUSER_ID]})
        results_n = read_records(n1, "test_sonucu_")
        check("N-b the WHOLE flow (seed -> chain -> approval -> report -> result -> deletion) WORKS with a normal (non-superuser) DB role + lawyer principal",
              len(results_n) == 1 and results_n[0]["sonuc"] == "UYUMLU" and not n1.paths.case_dir.exists(), f"{results_n!r}")
    finally:
        admin = pg_connect()
        try:
            with admin.cursor() as cur:
                cur.execute(_sql.SQL("REVOKE vergi_app FROM {}").format(_sql.Identifier(role_name)))
                cur.execute(_sql.SQL("DROP ROLE {}").format(_sql.Identifier(role_name)))
        finally:
            admin.close()

    # --- dış YZ reddi: preflight (paket), ortam anahtarı, wheel-yok fact_extraction ---
    n2 = start_ctx("n2")
    rows_before = len(journal_rows(f"case:{n2.case_id}"))
    flow = new_flow(n2, base_answers(n2), probes={"import_probe": lambda name: name == "anthropic"})
    try:
        flow.run_new(case_id=n2.case_id, dosya_kodu=n2.dosya_kodu, source_pdf=n2.source)
        code = None
    except records.OfficeFlowError as error:
        code = error.code
    check("N-c an importable `anthropic` package makes the preflight REFUSE (DIS_YZ_PAKETI_VAR) before any run/case dir or DB write",
          code == "DIS_YZ_PAKETI_VAR" and not runs_of(n2.office) and not (_TMP_CASES / n2.case_id).exists()
          and len(journal_rows(f"case:{n2.case_id}")) == rows_before, str(code))
    flow = new_flow(n2, base_answers(n2), probes={"env": {"ANTHROPIC_API_KEY": "x"}})
    try:
        flow.run_new(case_id=n2.case_id, dosya_kodu=n2.dosya_kodu, source_pdf=n2.source)
        code = None
    except records.OfficeFlowError as error:
        code = error.code
    check("N-d an ANTHROPIC_* environment variable makes the preflight REFUSE (DIS_YZ_ORTAM_ANAHTARI_VAR)",
          code == "DIS_YZ_ORTAM_ANAHTARI_VAR", str(code))
    check("N-e the flow exposes NO fact_extraction/agent entry point (backend has no such method; CLI has no such flag)",
          not any("fact_extraction" in n or "agent" in n.lower() for n in dir(flow_module.RealChainBackend))
          and "--with-agent" not in flow_module._build_parser().format_help())

    # wheel-yok fact_extraction apply: fail-closed, sıfır journal, sıfır .env açma
    n3 = start_ctx("n3")
    n3_run = records.new_run_id()
    n3_paths = records.build_run_paths(n3.office, _TMP_CASES, n3.case_id, n3_run)
    records.ensure_office_infra(n3.office)
    records.create_owned_dir(n3_paths.run_dir, run_id=n3_run, kind="run_dir")
    intake.seed_case(paths=n3_paths, source_pdf=n3.source, page_count=1, tax_types=["KDV"],
                     extractor=lambda p: SYNTH_TEXT, manifest=records.RunManifest(), protected_roots=[_TMP_CASES, n3.office])
    from ui.services import cli_authz as _cli_authz
    import contextlib
    authz_conn = psycopg.connect(dbname=PG_DB)
    try:
        principal = _cli_authz.build_cli_principal(authz_conn, LAWYER_ID)
        repo = _cli_authz.CliActorAuthzRepository(authz_conn)
        sys.modules["anthropic"] = None  # import -> ImportError (wheel yok simülasyonu)
        journal_before = len(journal_rows(f"case:{n3.case_id}"))
        raised = None
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                preview = _fx_facade.preview_generation(n3.case_id, intake.DOC_ID, with_agent=True, principal=principal, authz_repository=repo)
                _fx_facade.apply_generation(
                    n3.case_id, intake.DOC_ID, preview["input_digest"], with_agent=True, allow_network=True,
                    principal=principal, authz_repository=repo, conn_factory=lambda: psycopg.connect(dbname=PG_DB, autocommit=True),
                )
        except BaseException as error:  # noqa: BLE001
            raised = type(error).__name__
        finally:
            sys.modules.pop("anthropic", None)
    finally:
        authz_conn.close()
    check("N-f with the `anthropic` wheel absent a fact_extraction apply FAILS CLOSED (ImportError family) ...",
          raised in ("ModuleNotFoundError", "ImportError"), str(raised))
    check("N-g ... with ZERO journal rows written for the case and ZERO `.env*` open events",
          len(journal_rows(f"case:{n3.case_id}")) == journal_before and not ENV_OPEN_EVENTS, f"env={ENV_OPEN_EVENTS!r}")

    # ============================================================
    # D - DB kolon taraması, TEMP karakterizasyonu, ağ
    # ============================================================
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_schema, table_name, column_name FROM information_schema.columns "
                "WHERE table_schema IN ('iam','mutation') AND data_type IN ('text','character varying','jsonb','json') "
                "ORDER BY 1,2,3"
            )
            text_columns = [tuple(r) for r in cur.fetchall()]
        check("D-a0 the set of text-like iam/mutation columns equals the PINNED allowlist (a new column breaks this test on purpose)",
              set(text_columns) == PINNED_TEXT_COLUMNS,
              f"added={sorted(set(text_columns) - PINNED_TEXT_COLUMNS)} removed={sorted(PINNED_TEXT_COLUMNS - set(text_columns))}")
        hits = []
        needles = SENT_DATES + [SENT_TEXT, SOURCE_STEM, PDF_SHA, ".pdf", intake.DOC_FILE_NAME]
        with conn.cursor() as cur:
            for schema, table, column in text_columns:
                for needle in needles:
                    cur.execute(
                        _sql.SQL("SELECT count(*) FROM {}.{} WHERE {}::text LIKE %s").format(
                            _sql.Identifier(schema), _sql.Identifier(table), _sql.Identifier(column)),
                        (f"%{needle}%",),
                    )
                    if cur.fetchone()[0]:
                        hits.append((schema, table, column, needle))
        check("D-a NO tebliğ/son-gün date, excerpt text, source file name or PDF hash in ANY text-like column of the iam/mutation schemas",
              not hits, f"{hits!r}")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT action_family, target_ref FROM mutation.mutation_journal WHERE resource_key LIKE %s",
                (f"case:t1pg{RUN_TOKEN}%",),
            )
            refs = cur.fetchall()
        import re as _re
        shape_ok = all(
            _re.match(r"^(fact\.[a-z0-9_]+\.pending|fact\.[a-z0-9_]+|timeline\.[A-Za-z0-9_.\-]+|deadline\.[A-Za-z0-9_.\-]+|[A-Za-z0-9_.\-]+)$", ref or "")
            for _family, ref in refs)
        check("D-b every journal target_ref of these runs is an opaque `family.id` shape (no free text, no dates)",
              shape_ok and refs, f"{refs!r}")
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT resource_key FROM mutation.mutation_journal WHERE resource_key LIKE %s",
                        (f"case:t1pg{RUN_TOKEN}%",))
            keys = [r[0] for r in cur.fetchall()]
        check("D-c every resource_key is `case:<opaque lowercase id>`",
              keys and all(_re.match(r"^case:[a-z0-9_-]+$", k) for k in keys), f"{keys!r}")
    finally:
        conn.close()

    run_tmp_prefixes = [str(p) for p in (_TMP_ROOT).glob("office_*")]
    chain_temp_events = [e for e in TEMP_EVENTS if any(e[1].startswith(prefix) for prefix in run_tmp_prefixes)]
    other_temp_events = [e for e in TEMP_EVENTS if not any(e[1].startswith(prefix) for prefix in run_tmp_prefixes)]
    print("INFO tempfile events inside the flow's run tmp dirs:", len(chain_temp_events), "elsewhere:", len(other_temp_events))
    check("D-d TEMP characterization: the real chain DID use tempfile (deadline analysis writes a temp file) and those events are inside the run's own tmp dir",
          len(chain_temp_events) >= 1, f"inside={len(chain_temp_events)}")
    leaked = [e for e in other_temp_events if e[1].startswith(str(_SYSTEM_TEMP)) and "office_" not in e[1] and "vergi_t1_pgint_" not in e[1]]
    check("D-e NO tempfile was created in the SYSTEM temp dir by the flow (redirect holds for the real chain)", not leaked, f"{leaked[:3]!r}")
    check("D-f after S1 the run tmp dir is gone with the run dir (no TEMP residue)", not s1.paths.tmp_dir.exists())
    check("D-g the TEMP env/tempdir were restored after every run (no leak of the redirected value)",
          tempfile.gettempdir() != str(s1.paths.tmp_dir) and os.path.realpath(tempfile.gettempdir()) == os.path.realpath(str(_SYSTEM_TEMP)),
          tempfile.gettempdir())
    check("D-h network: NO non-loopback socket connect/resolve event was observed by the in-process recorder during the whole suite",
          not NET_EVENTS, f"{NET_EVENTS[:3]!r}")
    check("D-i NO `.env*` file was opened during the whole suite", not ENV_OPEN_EVENTS, f"{ENV_OPEN_EVENTS!r}")
    ledger = os.environ.get("VERGI_UI_TEST_SWEEP_GUARD_LEDGER")
    if ledger and os.path.isfile(ledger):
        lines = [l for l in Path(ledger).read_text(encoding="utf-8", errors="replace").splitlines() if f"\t{os.getpid()}\t" in l]
        check("D-j the runner's sweep guard is ARMED for this process and recorded no NET_BLOCKED/ENV_OPEN_BLOCKED event",
              any(l.startswith("GUARD_ARMED") for l in lines) and not any(l.startswith(("NET_BLOCKED", "ENV_OPEN_BLOCKED")) for l in lines))
    else:
        skip("D-j the runner's sweep guard ledger", "not run under scripts/run_ui_tests.py (guard not armed). NOT EXECUTED, not a pass")

    deleted = (s1, s2, s3, c4a, c4b, c4c, c4f, n1)
    kept_open = (a, s3b, s3c, c4d, c4e)
    check("D-k pilot copies: every run that reached its deletion step is gone; every run the scenario left open (UYUSMAZLIK/GECERSIZ/refused deletion) is STILL intact",
          all(not (_TMP_CASES / c.case_id).exists() and not (c.office / "runs" / c.run_id).exists() for c in deleted)
          and all((_TMP_CASES / c.case_id).exists() and (c.office / "runs" / c.run_id).exists() for c in kept_open),
          str([(c.tag, (_TMP_CASES / c.case_id).exists()) for c in deleted + kept_open]))
finally:
    for _m in _cases_dir_holders:
        _m.CASES_DIR = _REAL_CASES_ROOT
    # Source PDFs are read-only: clear the attribute so the temp tree can be removed.
    for _p in _TMP_ROOT.rglob("*.pdf"):
        try:
            os.chmod(_p, stat.S_IWRITE)
        except OSError:
            pass
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

_real_data_after = snapshot_real_data_tree()
check("the repository's own data/ tree is byte-for-byte unchanged (every case dir was a temp copy)",
      _real_data_before == _real_data_after,
      f"added={sorted(set(_real_data_after) - set(_real_data_before))[:3]} changed={[k for k in _real_data_before if _real_data_after.get(k) != _real_data_before[k]][:3]}")
check("the temp tree of this suite was removed", not _TMP_ROOT.exists())
_system_temp_after = set(os.listdir(_SYSTEM_TEMP))
_new_in_system_temp = sorted(n for n in (_system_temp_after - _system_temp_before)
                             if "office" in n or "vergi_t1" in n)
check("no residue of this suite remains in the SYSTEM temp dir", not _new_in_system_temp, f"{_new_in_system_temp[:5]}")
summarize_and_exit()
