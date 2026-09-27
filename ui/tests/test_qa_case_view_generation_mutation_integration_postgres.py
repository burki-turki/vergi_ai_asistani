# ============================================================
# PHASE B (COMMIT A) - QA / CASE-VIEW COORDINATED PENDING GENERATION:
# REAL PostgreSQL INTEGRATION TESTS.
#
# Drives the REAL production CLI (`ui.cli_mutate generation --row-key
# qa|case_view` and `ui.cli_mutate approval --row-key qa|case_view`)
# against a REAL, disposable PostgreSQL (migrations 0001-0005 applied)
# and a tempdir copy of case_0001 (every CASES_DIR holder redirected).
# Proves, end to end and with real journal rows:
#   Q1-Q5  qa: fresh apply -> pending + journal + audit; safe replay;
#          --with-agent refused (usage, zero rows); analyst preview ok /
#          apply denied; stale digest refused (zero rows)
#   C1     case_view on a canonical qa.json this fixture made stale (its
#          own case_id rewrite changes the upstream bytes qa.json binds)
#          is REFUSED (CaseViewQaPrerequisiteError) - zero rows/writes
#   A1     REAL Layer A approval of the generated QA pending through the
#          production `approval` CLI -> canonical qa.json; approval audit
#          path fields are repo-relative POSIX locators (option b)
#   C2     case_view after a fresh canonical qa.json: apply -> pending +
#          journal + audit (identity binds the canonical qa.json hash);
#          REAL Layer A approval of the case_view pending
#   C3     re-identified QA: an upstream change makes canonical qa.json
#          stale -> case_view is REFUSED again (zero new rows)
#   H1     second qa generation (new identity): history backup written,
#          audit `history_backup_path` is the repo-relative locator,
#          adapter gather_evidence() re-verifies the REAL row
#   R1/R2  merged reconciliation registry = 52, both families present;
#          gather_evidence() on the REAL completed rows
#   I0/I1  the real case_0001 approval-audit set is EXACTLY the 13 pinned
#          pre-Commit-B records plus the 2 Commit B promotion records, the
#          13 still carry their LF-normalized committed-content SHA-256
#          (EOL-agnostic - see _HISTORICAL_APPROVAL_AUDIT_SHA256), and
#          afterwards the
#          production data/ tree, the real case.json/timeline.json/
#          deadline.json and the real qa/case_view pending+canonical are
#          all BYTE-IDENTICAL
#
# Run: VERGI_TEST_PG_DSN=<db> python -m ui.tests.test_qa_case_view_generation_mutation_integration_postgres
# ============================================================

import dataclasses
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
    print(f"SKIPPED {label} {detail}")


def summarize_and_exit():
    print(
        f"--- test_qa_case_view_generation_mutation_integration_postgres: "
        f"{passed} passed, {failed} failed, {skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip(
        "test_qa_case_view_generation_mutation_integration_postgres",
        "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip(
        "test_qa_case_view_generation_mutation_integration_postgres",
        f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

# Every module holding a CASES_DIR / BASE_DIR-derived case root MUST be
# imported BEFORE the redirect sweep below (lazily-imported modules would
# otherwise keep pointing at the real tree).
import qa_discovery                                                     # noqa: E402
import qa_engine                                                        # noqa: E402
import qa_validator                                                     # noqa: E402
import qa_approval                                                      # noqa: E402
import orchestrator_discovery                                           # noqa: E402
import orchestrator_engine                                              # noqa: E402
import orchestrator_validator                                           # noqa: E402
import orchestrator_approval                                            # noqa: E402
import ui.cli_mutate as cli_mutate                                      # noqa: E402
import ui.reconciliation_operator as op                                 # noqa: E402
import ui.services.mutation_registry as mr                              # noqa: E402
from ui.services import approval_registry as _approval_registry         # noqa: E402,F401
from ui.services import mutation_approval_facade as _maf                # noqa: E402,F401
from ui.services import mutation_approval_adapters as _maa              # noqa: E402,F401
from ui.services import paths as _paths                                 # noqa: E402
from ui.services import qa_case_view_generation_mutation_facade as qcvf  # noqa: E402
from ui.services import qa_case_view_generation_mutation_adapters as qcva  # noqa: E402
from ui.services.common import sha256_file                              # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, resource_key, action_family, actor_user_id, target_ref, target_state, "
                "state, pre_hash, pre_revision, idempotency_key, request_fingerprint, "
                "observed_post_hash, resolution_code "
                "FROM mutation.mutation_journal WHERE resource_key = %s ORDER BY id",
                (resource_key,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


# ----------------------------------------------------------------
# Preflight.
# ----------------------------------------------------------------

_preflight = pg_connect()
try:
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('iam.users'), to_regclass('mutation.mutation_resources'), "
            "to_regclass('mutation.mutation_journal'), to_regclass('iam.global_resource_grants')"
        )
        row = cur.fetchone()
    check("preflight: iam + mutation schemas all exist (migrations 0001-0005)", all(row))
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run against a half-migrated database.")
    summarize_and_exit()

_ACTORS = {"lawyer": 601, "analyst": 602}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"phaseb-qa-case-view-actor-{user_id}"),
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
# Case fixtures under a fresh tempdir; CASES_DIR redirect sweep + the two
# BASE_DIR-derived case-root holders (`qa_validator.check_snapshot_
# freshness`, `qa_approval.compare_manifest_to_live` - both hardcode
# BASE_DIR/"data"/"cases", the known backlog item).
# ----------------------------------------------------------------

_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))
REAL_CASE_0001 = REPO_ROOT / "data" / "cases" / "case_0001"
REAL_DATA_DIR = REPO_ROOT / "data"


def snapshot_tree(root):
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(root))] = "<unreadable>"
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


_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_qacv_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
check(
    "the CASES_DIR redirect sweep found ui.services.paths, qa_discovery, qa_engine, qa_approval, "
    "orchestrator_discovery, orchestrator_engine and orchestrator_approval",
    all(
        any(getattr(m, "__name__", "") == name for m in _cases_dir_holders)
        for name in (
            "ui.services.paths", "qa_discovery", "qa_engine", "qa_approval",
            "orchestrator_discovery", "orchestrator_engine", "orchestrator_approval",
        )
    ),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES
_REAL_QA_VALIDATOR_BASE_DIR = qa_validator.BASE_DIR
_REAL_QA_APPROVAL_BASE_DIR = qa_approval.BASE_DIR
qa_validator.BASE_DIR = _TMP_ROOT
qa_approval.BASE_DIR = _TMP_ROOT

_real_data_before = snapshot_tree(REAL_DATA_DIR)
_real_case_before = snapshot_tree(REAL_CASE_0001)
_real_approval_audits_before = {
    str(p.relative_to(REAL_CASE_0001)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(REAL_CASE_0001.rglob("*.approval.json"))
}
_REAL_KEY_FILES = [
    "case.json", "timeline/timeline.json", "deadlines/deadline.json",
    "qa/qa.json", "qa/qa_case_0001_v1.json.pending",
    "case_view/case_view.json", "case_view/case_view_case_0001_v1.json.pending",
]
_real_key_before = {rel: hashlib.sha256((REAL_CASE_0001 / rel).read_bytes()).hexdigest() for rel in _REAL_KEY_FILES}
# The 13 pre-Commit-B historical approval audits, pinned by repo-relative path
# AND LF-normalized committed-content SHA-256: the digest of the file's bytes
# with CRLF collapsed to LF, which for these 13 IS the digest of the committed
# bytes, because all 13 are `i/lf` in the index (`git ls-files --eol`).
#
# Why normalize instead of hashing raw bytes: `.gitattributes` marks *.json
# `text eol=lf`, but git only converts on check-IN, not check-OUT - a blob that
# is LF in the index is written verbatim, and any writer that later emits CRLF
# leaves the file `i/lf w/crlf`. Today that is exactly 4 of the 13 (the three
# documents/*/extractions/reviews fact-promotion audits and the timeline audit).
# `git status` normalizes before comparing, so it reports that drift as CLEAN.
# Pinning raw bytes would therefore pin ONE checkout's line endings and fail on
# the other; normalizing makes I0 EOL-agnostic, so it holds on the CRLF main
# checkout and on a clean LF checkout alike while still catching every
# non-EOL byte change.
#
# Commit B (the coordinated QA/case-view regeneration) appends exactly two MORE
# promotion audits and must leave these 13 untouched - so I0 asserts an exact
# SET (never a blind total) plus content-identity of the 13 modulo line endings.
_HISTORICAL_APPROVAL_AUDIT_SHA256 = {
    "arguments/reviews/arguments_case_0001_v1_20260903_142708.approval.json":
        "e94d73609250b212c673cad0c616d097c62e7675ffd662d0edb67a8faee903fb",
    "case_law/reviews/case_law_case_0001_v1_20260902_185750.approval.json":
        "ad5e1f29f4015c85e021aac86c3ad02aef8bf070104cd3f02aa5708b2e91500d",
    "case_view/reviews/case_view_case_0001_v1_20260904_212319.approval.json":
        "25ed3c933e7d341bf0f1755ababf36ab4f276a57a3d10d99f27a46f1f3a01817",
    "deadlines/reviews/deadline_case_0001_v1_20260902_001630.approval.json":
        "8fc3325d41c533e1aa51a3632e6a8dfc418debc0b001a25f6b0aab8e235ebaf6",
    "documents/dava_dilekcesi_001/extractions/reviews/extract_dava_dilekcesi_001_llm_v1_3_20260901_130225.approval.json":
        "ebe936dac19eca63effa9e4d2f32979b00b5e1ddcf6fcb3b4b7dc22341d1eab2",
    "documents/ihbarname_001/extractions/reviews/extract_ihbarname_001_llm_v1_2_1_20260901_122652.approval.json":
        "52ece44d16cc9fe567bc5590b0859c669a5f7e107606a946e55322090495d54f",
    "documents/vir_001/extractions/reviews/extract_vir_001_llm_v1_1_20260901_105342.approval.json":
        "780baacd3ff69a57211adfca5a3b0f7be612e54f2233209999e6f55e31a30f2a",
    "drafting/reviews/drafting_case_0001_v1_20260904_171024.approval.json":
        "7022b8b3b821c2cac96815074d877850675712f69bf5fd81e4b87f8a88cb02cb",
    "issues/reviews/issue_spotting_case_0001_v1_20260902_114359.approval.json":
        "6a14eb80b5d91c08e3318069021a0095ed5b92b4321c3a397fbe4a9582782c3a",
    "qa/reviews/qa_case_0001_v1_20260904_202837.approval.json":
        "eb0ab3bc236a0410873ac6df6e4736ca731d0876b10eee649a28bd83accaa197",
    "research/reviews/legal_research_case_0001_v1_20260902_151601.approval.json":
        "f32f6fc99e7e68322251e1d1aef81df1613da31993921b8666a2dc433c3c38b0",
    "risk_strategy/reviews/risk_strategy_case_0001_v1_20260904_112002.approval.json":
        "907b05c88a033ebba9391f2e551e9f9a17f72faff0d3fdfb3ce14639d30359ab",
    "timeline/reviews/timeline_case_0001_v1_1_20260901_184144.approval.json":
        "bd5ae8dbefbfd19524066238bb1638dd1baffa9f5f7b6d5162a30225542c7bf9",
}
_COMMIT_B_APPROVAL_AUDIT_RELS = {
    "qa/reviews/qa_case_0001_v1_20260927_193137.approval.json",
    "case_view/reviews/case_view_case_0001_v1_20260927_193245.approval.json",
}
_EXPECTED_APPROVAL_AUDIT_RELS = set(_HISTORICAL_APPROVAL_AUDIT_SHA256) | _COMMIT_B_APPROVAL_AUDIT_RELS
_observed_audit_rels = {Path(rel).as_posix() for rel in _real_approval_audits_before}
check(
    "I0 the real case_0001 approval-audit set is EXACTLY the 13 pinned pre-Commit-B historical records "
    "PLUS the 2 Commit B promotion records (exact set, not a blind total) - NON-VACUITY: this suite cannot "
    "go green on a pre-Commit-B tree",
    _observed_audit_rels == _EXPECTED_APPROVAL_AUDIT_RELS,
    f"unexpected={sorted(_observed_audit_rels - _EXPECTED_APPROVAL_AUDIT_RELS)} "
    f"missing={sorted(_EXPECTED_APPROVAL_AUDIT_RELS - _observed_audit_rels)}",
)


class BareCarriageReturnError(RuntimeError):
    """A historical approval audit carries a CR that CRLF->LF cannot explain."""


def sha256_lf_normalized_audit(rel):
    """SHA-256 of the historical audit at `rel`, with CRLF collapsed to LF.

    CRLF->LF is the ONLY transformation applied (no strip, no BOM handling, no
    lone-CR rewrite), so every non-EOL byte difference still changes the digest.
    Fail-closed: a bare CR surviving the collapse is not an end-of-line variant
    this normalization is licensed to absorb, so it raises rather than fold an
    unexplained byte into a byte-identity comparison. A missing/unreadable file
    returns the same non-digest sentinel `snapshot_tree` uses, so the exact-set
    check above stays the legible reporter for that case.
    """
    try:
        data = (REAL_CASE_0001 / rel).read_bytes()
    except OSError:
        return "<unreadable>"
    data = data.replace(b"\r\n", b"\n")
    if b"\r" in data:
        raise BareCarriageReturnError(
            f"bare CR (not part of CRLF) in historical approval audit {rel}"
        )
    return hashlib.sha256(data).hexdigest()


# Computed over exactly the 13 pinned paths (not an rglob), so the normalization
# is scoped to "historical approval audit bytes" and nothing else. Raw-byte
# digests stay in `_real_approval_audits_before` for I1c, which must remain
# EOL-SENSITIVE: it is a before/after invariance check on one single tree, so
# normalizing there would blind it to an EOL-only mutation of a real audit.
_historical_audits_lf = {
    rel: sha256_lf_normalized_audit(rel) for rel in sorted(_HISTORICAL_APPROVAL_AUDIT_SHA256)
}
check(
    "I0 each of the 13 pre-Commit-B historical approval audits still carries its LF-normalized "
    "committed-content SHA-256 - EOL-agnostic, so CRLF-only checkout drift is normalized away "
    "while every other byte change still fails (Commit B appended two records and rewrote NONE of the 13)",
    all(_historical_audits_lf.get(rel) == digest for rel, digest in _HISTORICAL_APPROVAL_AUDIT_SHA256.items()),
    f"drifted={sorted(rel for rel, digest in _HISTORICAL_APPROVAL_AUDIT_SHA256.items() if _historical_audits_lf.get(rel) != digest)}",
)

RUN_TOKEN = uuid.uuid4().hex[:8]


def make_case(tag):
    """Tempdir copy of case_0001 with a fresh case_id (every `case_0001`
    mention rewritten). The committed qa/case_view pendings are removed
    so the first coordinated write is a genuine first write; the Commit B
    provenance dirs (history/, generation_reviews/) are removed for the same
    reason. The canonical qa.json/case_view.json are KEPT on purpose: the
    case_id rewrite changes the upstream bytes they bind, which is exactly the
    SYNTHETIC stale state C1 exercises (see C1a's mechanical proof)."""
    case_id = f"qacvpg{RUN_TOKEN}{tag}"
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
    for family_dir_name in ("qa", "case_view"):
        family_dir = dst / family_dir_name
        for stale in list(family_dir.glob("*.pending")):
            stale.unlink()
        for stale_dir_name in ("history", "generation_reviews"):
            stale_dir = family_dir / stale_dir_name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
    return case_id, dst


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


def _line_value(out, key):
    for line in out.splitlines():
        if line.startswith(key + "="):
            return line[len(key) + 1:]
    raise AssertionError(f"{key}= not found in output: {out!r}")


def preview_digest(case_id, row_key, *, actor_user_id=None):
    code, out, err = run_cli([
        "generation", "--case", case_id, "--row-key", row_key,
        "--actor-user-id", str(actor_user_id if actor_user_id is not None else _ACTORS["lawyer"]),
    ])
    if code != 0:
        raise AssertionError(f"preview failed: code={code} out={out!r} err={err!r}")
    return _line_value(out, "input_digest"), out


def approve_via_cli(case_id, row_key, actor_user_id):
    """REAL Layer A through the production `approval` CLI: preview (prints
    the pending hash) then --approve --expected-hash."""
    code, out, err = run_cli([
        "approval", "--case", case_id, "--row-key", row_key, "--actor-user-id", str(actor_user_id),
    ])
    if code != 0:
        raise AssertionError(f"approval preview failed: code={code} out={out!r} err={err!r}")
    # The approval CLI preview prints `pending_hash=<sha256>` (Layer A's
    # own, unchanged output shape) plus the copy-paste --approve command.
    pending_hash = _line_value(out, "pending_hash")
    code, out, err = run_cli([
        "approval", "--case", case_id, "--row-key", row_key, "--actor-user-id", str(actor_user_id),
        "--approve", "--expected-hash", pending_hash,
    ])
    return code, out, err, pending_hash


def newest_approval_audit(family_dir):
    audits = sorted((family_dir / "reviews").glob("*.approval.json"))
    return json.loads(audits[-1].read_text(encoding="utf-8")) if audits else None


def generation_audits(reviews_dir):
    return sorted(reviews_dir.glob("*.generation_audit.json"))


def is_portable_locator(value):
    return (
        isinstance(value, str) and value.startswith("data/cases/") and "\\" not in value
        and ":" not in value and ".." not in value.split("/")
    )


try:
    # ============================================================
    # Q1 - qa fresh deterministic generation, END-TO-END through the
    #      real CLI (preview -> apply).
    # ============================================================
    case_q, dir_q = make_case("q")
    seed_assignment(_ACTORS["lawyer"], case_q, "lawyer")
    canonical_qa_q = dir_q / "qa" / "qa.json"
    canonical_qa_q_before = canonical_qa_q.read_bytes()

    digest_q, preview_out_q = preview_digest(case_q, "qa")
    check(
        "Q1a qa preview prints target_ref=qa.pending, deterministic provenance sentinels, "
        "pending_exists=False",
        _line_value(preview_out_q, "target_ref") == "qa.pending"
        and _line_value(preview_out_q, "generation_mode") == "deterministic"
        and _line_value(preview_out_q, "model_id") == "deterministic_no_model"
        and _line_value(preview_out_q, "prompt_agent_version") == "n/a"
        and _line_value(preview_out_q, "pending_exists") == "False",
        f"out={preview_out_q!r}",
    )
    check("Q1b preview input_digest is a 64-hex sha256", len(digest_q) == 64 and int(digest_q, 16) >= 0)
    digest_q2, _ = preview_digest(case_q, "qa")
    check("Q1c preview is deterministic (same digest on a second preview)", digest_q == digest_q2)

    code, out, err = run_cli([
        "generation", "--case", case_q, "--row-key", "qa",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_q,
    ])
    check("Q1d CLI qa apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    pending_q = qa_engine.get_pending_path(case_q)
    check(
        "Q1e the REAL pending file was written at the Layer-A-pinned pending name",
        pending_q.is_file() and pending_q == qa_approval.get_pending_path(case_q),
    )
    rows_q = journal_rows(f"case:{case_q}")
    check(
        "Q1f exactly one REAL journal row: completed / generation.qa / qa.pending / generated / "
        "pre_revision == input_digest",
        len(rows_q) == 1 and rows_q[0]["state"] == "completed"
        and rows_q[0]["action_family"] == "generation.qa" and rows_q[0]["target_ref"] == "qa.pending"
        and rows_q[0]["target_state"] == "generated" and rows_q[0]["pre_revision"] == digest_q,
        f"rows={rows_q}",
    )
    check(
        "Q1g journal observed_post_hash == on-disk pending sha256 == CLI-reported pending_sha256",
        rows_q[0]["observed_post_hash"] == sha256_file(pending_q) == _line_value(out, "pending_sha256"),
    )
    audits_q = generation_audits(qa_engine.get_reviews_dir(case_q))
    check("Q1h exactly one *.generation_audit.json under qa/generation_reviews/", len(audits_q) == 1)
    audit_q = json.loads(audits_q[0].read_text(encoding="utf-8"))
    check(
        "Q1i audit: action_family/channel/actor/idempotency/resource bound; first_write=True; "
        "history_backup_path=None; deterministic provenance",
        audit_q["action_family"] == "generation.qa" and audit_q["channel"] == "local_lawyer_generation_cli"
        and audit_q["mutation_actor_ref"] == str(_ACTORS["lawyer"])
        and audit_q["mutation_idempotency_key"] == rows_q[0]["idempotency_key"]
        and audit_q["mutation_resource_key"] == f"case:{case_q}"
        and audit_q["first_write"] is True and audit_q["history_backup_path"] is None
        and audit_q["generation_mode"] == "deterministic" and audit_q["input_digest"] == digest_q,
        f"audit={audit_q}",
    )
    check(
        "Q1j the (stale, committed) canonical qa.json is BYTE-IDENTICAL after generation - the "
        "publisher never writes canonical",
        canonical_qa_q.read_bytes() == canonical_qa_q_before,
    )
    pending_q_data = json.loads(pending_q.read_text(encoding="utf-8"))
    locator_paths = [
        r["artifact_locator"]["path"] for r in pending_q_data["qa_check_results"]
        if r.get("artifact_locator") and r["artifact_locator"].get("path") is not None
    ]
    check(
        "Q1k every artifact_locator.path in the generated QA pending is a portable repo-relative "
        "POSIX locator starting with data/cases/<case_id>/ (no drive letter, backslash or '..')",
        locator_paths and all(is_portable_locator(p) and p.startswith(f"data/cases/{case_q}/") for p in locator_paths),
        f"sample={locator_paths[:3]}",
    )
    check(
        "Q1l no worktree/user-directory absolute path appears anywhere in the generated QA pending "
        "or its generation audit",
        str(_TMP_ROOT) not in pending_q.read_text(encoding="utf-8")
        and str(_TMP_ROOT) not in audits_q[0].read_text(encoding="utf-8")
        and str(REPO_ROOT) not in audits_q[0].read_text(encoding="utf-8"),
    )

    # ============================================================
    # Q2 - SAFE REPLAY via the real CLI.
    # ============================================================
    pending_bytes_q_before_replay = pending_q.read_bytes()
    code, out, err = run_cli([
        "generation", "--case", case_q, "--row-key", "qa",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_q,
    ])
    check("Q2a replay of the SAME apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    check("Q2b replayed=True reported", "replayed=True" in out, f"out={out!r}")
    check("Q2c pending bytes BYTE-IDENTICAL (writer NOT re-invoked)", pending_q.read_bytes() == pending_bytes_q_before_replay)
    check("Q2d still exactly ONE journal row", len(journal_rows(f"case:{case_q}")) == 1)
    check("Q2e still exactly ONE generation audit", len(generation_audits(qa_engine.get_reviews_dir(case_q))) == 1)

    # ============================================================
    # Q3 - --with-agent / --allow-network REFUSED for both row-keys via
    #      the real CLI: pure usage-shape rejections, ZERO journal rows.
    # ============================================================
    for rk in ("qa", "case_view"):
        code, out, err = run_cli([
            "generation", "--case", case_q, "--row-key", rk, "--actor-user-id", str(_ACTORS["lawyer"]),
            "--with-agent",
        ])
        check(
            f"Q3a --with-agent refused for --row-key {rk} (exit 2, facade's fixed message)",
            code == 2 and err.strip() == qcvf.agent_mode_refusal_message(rk), f"code={code} err={err!r}",
        )
        code, out, err = run_cli([
            "generation", "--case", case_q, "--row-key", rk, "--actor-user-id", str(_ACTORS["lawyer"]),
            "--with-agent", "--allow-network", "--apply", "--expected-input-digest", digest_q,
        ])
        check(f"Q3b --with-agent --allow-network --apply refused for --row-key {rk} (exit 2)", code == 2, f"code={code} err={err!r}")
    check("Q3c zero NEW journal rows from the refused attempts", len(journal_rows(f"case:{case_q}")) == 1)

    # ============================================================
    # Q4 - ANALYST: preview allowed, apply denied (existence-blind).
    # ============================================================
    case_an, dir_an = make_case("an")
    seed_assignment(_ACTORS["analyst"], case_an, "analyst")
    digest_an, _ = preview_digest(case_an, "qa", actor_user_id=_ACTORS["analyst"])
    check("Q4a analyst preview succeeded (read capability)", len(digest_an) == 64)
    code, out, err = run_cli([
        "generation", "--case", case_an, "--row-key", "qa",
        "--actor-user-id", str(_ACTORS["analyst"]), "--apply", "--expected-input-digest", digest_an,
    ])
    check("Q4b analyst apply denied", code != 0, f"code={code} out={out!r} err={err!r}")
    check("Q4c zero journal rows for the denied attempt", journal_rows(f"case:{case_an}") == [])
    check("Q4d no pending written for the denied attempt", not qa_engine.get_pending_path(case_an).exists())

    # ============================================================
    # Q5 - STALE DIGEST: mutate a manifest input after preview.
    # ============================================================
    case_s, dir_s = make_case("s")
    seed_assignment(_ACTORS["lawyer"], case_s, "lawyer")
    digest_s, _ = preview_digest(case_s, "qa")
    timeline_s = dir_s / "timeline" / "timeline.json"
    original_timeline_s = timeline_s.read_bytes()
    # Schema-preserving byte change (re-serialization with a different
    # indent): same JSON content, different raw bytes -> different
    # manifest hash. A schema-invalid marker would make QA's own strict
    # timeline loader raise instead of exercising the digest gate.
    timeline_s.write_text(
        json.dumps(json.loads(original_timeline_s.decode("utf-8")), ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    check("Q5 precondition: the re-serialized timeline.json has different bytes", timeline_s.read_bytes() != original_timeline_s)
    code, out, err = run_cli([
        "generation", "--case", case_s, "--row-key", "qa",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_s,
    ])
    check("Q5a stale-digest apply exits non-zero (domain error)", code == 1, f"code={code} out={out!r} err={err!r}")
    check("Q5b zero journal rows for the stale attempt", journal_rows(f"case:{case_s}") == [])
    check("Q5c no pending written for the stale attempt", not qa_engine.get_pending_path(case_s).exists())
    timeline_s.write_bytes(original_timeline_s)

    # ============================================================
    # C1 - case_view on the committed (STALE in a clean tree) canonical
    #      qa.json is REFUSED at preview AND apply - zero rows, zero writes.
    # ============================================================
    canonical_qa_c1_valid = qa_validator.validate_qa_analysis(
        dir_q / "qa" / "qa.json", expected_case_id=case_q, raise_on_error=False,
    )["valid"]
    # The stale state is created BY THIS FIXTURE, not inherited: `make_case`
    # rewrites every `case_0001` mention to a fresh case_id, which changes the
    # upstream bytes this copy's qa.json binds. Proven mechanically below - the
    # recorded `case.json` hash still matches the REAL (Commit B, fresh) tree
    # and no longer matches this copy.
    _c1_recorded_case_sha = next(
        e["raw_byte_sha256"] for e in
        json.loads((dir_q / "qa" / "qa.json").read_text(encoding="utf-8"))["analysis_metadata"]["dependency_manifest"]
        if e["artifact_ref"] == "case.json"
    )
    check(
        "C1a precondition: the canonical qa.json is NOT valid/fresh for THIS COPY, and the cause is this "
        "fixture's own case_id rewrite - the recorded case.json hash still equals the REAL Commit B tree's "
        "case.json and differs from this copy's",
        canonical_qa_c1_valid is False
        and _c1_recorded_case_sha == hashlib.sha256((REAL_CASE_0001 / "case.json").read_bytes()).hexdigest()
        and _c1_recorded_case_sha != hashlib.sha256((dir_q / "case.json").read_bytes()).hexdigest(),
        f"recorded={_c1_recorded_case_sha}",
    )
    code, out, err = run_cli([
        "generation", "--case", case_q, "--row-key", "case_view", "--actor-user-id", str(_ACTORS["lawyer"]),
    ])
    check(
        "C1b case_view PREVIEW refused with CaseViewQaPrerequisiteError (exit 1, clean domain error)",
        code == 1 and "CaseViewQaPrerequisiteError" in err and "Traceback" not in err,
        f"code={code} out={out!r} err={err!r}",
    )
    code, out, err = run_cli([
        "generation", "--case", case_q, "--row-key", "case_view", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--apply", "--expected-input-digest", "0" * 64,
    ])
    check(
        "C1c case_view APPLY refused with CaseViewQaPrerequisiteError before any journal/lock (exit 1)",
        code == 1 and "CaseViewQaPrerequisiteError" in err, f"code={code} err={err!r}",
    )
    check("C1d zero case_view journal rows, no case_view pending written",
          all(r["action_family"] != "generation.case_view" for r in journal_rows(f"case:{case_q}"))
          and not orchestrator_engine.get_pending_path(case_q).exists())

    # ============================================================
    # A1 - REAL Layer A approval of the generated QA pending through the
    #      production `approval` CLI (option-b audit path fields).
    # ============================================================
    code, out, err, qa_pending_hash = approve_via_cli(case_q, "qa", _ACTORS["lawyer"])
    check("A1a real `approval --row-key qa --approve` exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    check(
        "A1b canonical qa.json now BYTE-IDENTICAL to the generated pending",
        canonical_qa_q.read_bytes() == pending_q.read_bytes(),
    )
    rows_q_after_approval = journal_rows(f"case:{case_q}")
    check(
        "A1c an approval.qa journal row was added (completed)",
        any(r["action_family"] == "approval.qa" and r["state"] == "completed" for r in rows_q_after_approval),
        f"rows={[(r['action_family'], r['state']) for r in rows_q_after_approval]}",
    )
    approval_audit_qa = newest_approval_audit(dir_q / "qa")
    check(
        "A1d approval audit source_pending_path/canonical_path/previous_canonical_backup are "
        "repo-relative POSIX locators with the exact canonical layout (option b)",
        approval_audit_qa is not None
        and approval_audit_qa["source_pending_path"] == f"data/cases/{case_q}/qa/qa_{case_q}_v1.json.pending"
        and approval_audit_qa["canonical_path"] == f"data/cases/{case_q}/qa/qa.json"
        and is_portable_locator(approval_audit_qa["previous_canonical_backup"])
        and approval_audit_qa["previous_canonical_backup"].startswith(f"data/cases/{case_q}/qa/qa.json.before_approval_"),
        f"audit={approval_audit_qa}",
    )
    check(
        "A1e approval audit still carries the Row 19C-2a mutation binding (idempotency/resource keys) "
        "and the pending/canonical sha256 fields",
        approval_audit_qa["mutation_resource_key"] == f"case:{case_q}"
        and isinstance(approval_audit_qa.get("mutation_idempotency_key"), str)
        and approval_audit_qa["pending_sha256"] == qa_pending_hash
        and approval_audit_qa["canonical_sha256"] == sha256_file(canonical_qa_q),
    )
    check(
        "A1f no worktree absolute path anywhere in the new approval audit",
        str(_TMP_ROOT) not in json.dumps(approval_audit_qa) and str(REPO_ROOT) not in json.dumps(approval_audit_qa),
    )
    check(
        "A1g canonical qa.json is now valid/fresh per qa_validator (prerequisite for case_view)",
        qa_validator.validate_qa_analysis(canonical_qa_q, expected_case_id=case_q, raise_on_error=False)["valid"] is True,
    )

    # ============================================================
    # C2 - case_view after a fresh canonical qa.json: preview -> apply ->
    #      real approval.
    # ============================================================
    canonical_cv_q = dir_q / "case_view" / "case_view.json"
    canonical_cv_q_before = canonical_cv_q.read_bytes()
    digest_cv, preview_out_cv = preview_digest(case_q, "case_view")
    check("C2a case_view preview now succeeds (target_ref=case_view.pending)", _line_value(preview_out_cv, "target_ref") == "case_view.pending")
    code, out, err = run_cli([
        "generation", "--case", case_q, "--row-key", "case_view",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_cv,
    ])
    check("C2b CLI case_view apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    pending_cv = orchestrator_engine.get_pending_path(case_q)
    check(
        "C2c case_view pending written at the Layer-A-pinned name; canonical case_view.json untouched",
        pending_cv.is_file() and pending_cv == orchestrator_approval.get_pending_path(case_q)
        and canonical_cv_q.read_bytes() == canonical_cv_q_before,
    )
    rows_cv = [r for r in journal_rows(f"case:{case_q}") if r["action_family"] == "generation.case_view"]
    check(
        "C2d exactly one generation.case_view journal row (completed, target case_view.pending)",
        len(rows_cv) == 1 and rows_cv[0]["state"] == "completed" and rows_cv[0]["target_ref"] == "case_view.pending"
        and rows_cv[0]["observed_post_hash"] == sha256_file(pending_cv),
        f"rows={rows_cv}",
    )
    audits_cv = generation_audits(orchestrator_engine.get_reviews_dir(case_q))
    audit_cv = json.loads(audits_cv[0].read_text(encoding="utf-8")) if audits_cv else {}
    qa_container = next(
        (c for c in audit_cv.get("identity_payload", {}).get("manifest", []) if c.get("logical_name") == "qa"), None,
    )
    check(
        "C2e case_view identity BINDS the canonical qa.json raw-byte sha256 (qa container present, "
        "sha256 == current canonical qa.json)",
        len(audits_cv) == 1 and qa_container is not None and qa_container["state"] == "present"
        and qa_container["files"][0]["sha256"] == sha256_file(canonical_qa_q),
        f"qa_container={qa_container}",
    )
    check(
        "C2f generated case_view pending: generation_status=completed and validates with the real "
        "orchestrator_validator",
        json.loads(pending_cv.read_text(encoding="utf-8"))["generation_status"] == "completed"
        and orchestrator_validator.validate_case_view(pending_cv, expected_case_id=case_q, raise_on_error=False)["valid"] is True,
    )
    code, out, err, cv_pending_hash = approve_via_cli(case_q, "case_view", _ACTORS["lawyer"])
    check("C2g real `approval --row-key case_view --approve` exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    check("C2h canonical case_view.json == generated pending", canonical_cv_q.read_bytes() == pending_cv.read_bytes())
    approval_audit_cv = newest_approval_audit(dir_q / "case_view")
    check(
        "C2i case_view approval audit path fields are repo-relative POSIX locators (option b)",
        approval_audit_cv["source_pending_path"] == f"data/cases/{case_q}/case_view/case_view_{case_q}_v1.json.pending"
        and approval_audit_cv["canonical_path"] == f"data/cases/{case_q}/case_view/case_view.json"
        and is_portable_locator(approval_audit_cv["previous_canonical_backup"])
        and approval_audit_cv["previous_canonical_backup"].startswith(f"data/cases/{case_q}/case_view/case_view.json.before_approval_"),
        f"audit={approval_audit_cv}",
    )

    # ============================================================
    # C3 - RE-IDENTIFIED QA: an upstream change makes the canonical
    #      qa.json stale -> case_view refused again, zero new rows.
    # ============================================================
    rows_before_c3 = len(journal_rows(f"case:{case_q}"))
    timeline_q = dir_q / "timeline" / "timeline.json"
    original_timeline_q = timeline_q.read_bytes()
    # Schema-preserving byte change (see Q5): QA must still be able to
    # REBUILD on the changed tree in H1, so the timeline stays schema-valid.
    timeline_q.write_text(
        json.dumps(json.loads(original_timeline_q.decode("utf-8")), ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    check("C3 precondition: the re-serialized timeline.json has different bytes", timeline_q.read_bytes() != original_timeline_q)
    code, out, err = run_cli([
        "generation", "--case", case_q, "--row-key", "case_view", "--actor-user-id", str(_ACTORS["lawyer"]),
    ])
    check(
        "C3a after an upstream change the canonical qa.json is stale -> case_view preview REFUSED "
        "(CaseViewQaPrerequisiteError)",
        code == 1 and "CaseViewQaPrerequisiteError" in err, f"code={code} err={err!r}",
    )
    code, out, err = run_cli([
        "generation", "--case", case_q, "--row-key", "case_view", "--actor-user-id", str(_ACTORS["lawyer"]),
        "--apply", "--expected-input-digest", digest_cv,
    ])
    check("C3b case_view apply with the old digest also REFUSED (exit 1)", code == 1, f"code={code} err={err!r}")
    check("C3c zero NEW journal rows from the refused case_view attempts", len(journal_rows(f"case:{case_q}")) == rows_before_c3)

    # ============================================================
    # H1 - SECOND qa generation (new identity after the upstream change):
    #      history backup written, audit history_backup_path is the
    #      repo-relative locator, adapter re-verifies the REAL row.
    # ============================================================
    digest_q_v2, _ = preview_digest(case_q, "qa")
    check("H1a upstream change produced a NEW qa input_digest", digest_q_v2 != digest_q)
    pending_q_before_v2 = pending_q.read_bytes()
    code, out, err = run_cli([
        "generation", "--case", case_q, "--row-key", "qa",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_q_v2,
    ])
    check("H1b second qa apply (new identity) exits 0, replayed=False", code == 0 and "replayed=False" in out, f"code={code} out={out!r} err={err!r}")
    history_files = sorted((dir_q / "qa" / "history").glob("qa_pending_before_engine_*.json.pending"))
    check(
        "H1c previous pending preserved under qa/history/ byte-identical",
        len(history_files) == 1 and history_files[0].read_bytes() == pending_q_before_v2,
    )
    audits_q2 = generation_audits(qa_engine.get_reviews_dir(case_q))
    audit_q2 = json.loads(audits_q2[-1].read_text(encoding="utf-8"))
    check(
        "H1d second audit: first_write=False, history_backup_path is the EXACT repo-relative locator "
        "data/cases/<case_id>/qa/history/<name>, history_backup_sha256 matches the backup bytes",
        len(audits_q2) == 2 and audit_q2["first_write"] is False
        and audit_q2["history_backup_path"] == f"data/cases/{case_q}/qa/history/{history_files[0].name}"
        and audit_q2["history_backup_sha256"] == hashlib.sha256(history_files[0].read_bytes()).hexdigest(),
        f"audit={audit_q2}",
    )
    rows_q_v2 = [r for r in journal_rows(f"case:{case_q}") if r["action_family"] == "generation.qa"]
    check("H1e two generation.qa journal rows now exist, both completed", len(rows_q_v2) == 2 and all(r["state"] == "completed" for r in rows_q_v2))
    entry_v2 = mr.JournalEntrySnapshot(
        journal_id=rows_q_v2[-1]["id"], resource_key=rows_q_v2[-1]["resource_key"],
        action_family=rows_q_v2[-1]["action_family"], target_ref=rows_q_v2[-1]["target_ref"],
        target_state=rows_q_v2[-1]["target_state"], pre_hash=rows_q_v2[-1]["pre_hash"],
        pre_revision=rows_q_v2[-1]["pre_revision"], expected_post_hash=rows_q_v2[-1]["observed_post_hash"],
        state=rows_q_v2[-1]["state"], idempotency_key=rows_q_v2[-1]["idempotency_key"],
        request_fingerprint=rows_q_v2[-1]["request_fingerprint"], actor_label=str(_ACTORS["lawyer"]),
    )
    evidence_v2 = qcva.QaCaseViewGenerationReconciliationAdapter(qa_engine, "qa").gather_evidence(entry_v2)
    check(
        "H1f adapter gather_evidence() on the REAL second row: post_state_verified=True via the "
        "portable history_backup_path binding; observed_post_hash == on-disk pending",
        evidence_v2.post_state_verified is True and evidence_v2.observed_post_hash == sha256_file(pending_q),
        f"evidence={evidence_v2}",
    )
    tampered = dict(audit_q2)
    tampered["history_backup_path"] = str(history_files[0])  # absolute -> must be rejected
    check(
        "H1g an ABSOLUTE history_backup_path in the audit is rejected by the adapter's full binding "
        "(locators must be repo-relative)",
        qcva._audit_record_matches(
            tampered, "qa", idempotency_key=rows_q_v2[-1]["idempotency_key"], resource_key=f"case:{case_q}",
            action_family="generation.qa", target_ref="qa.pending", target_state="generated",
            actor_label=str(_ACTORS["lawyer"]), pending_sha256=sha256_file(pending_q),
            history_dir_verified=qa_engine.get_history_dir(case_q),
        ) is False,
    )
    timeline_q.write_bytes(original_timeline_q)

    # ============================================================
    # R1/R2 - merged reconciliation registry + gather_evidence() on the
    #         REAL completed rows (qa first row, case_view row).
    # ============================================================
    merged = op._default_registry_factory()
    check(
        "R1 merged reconciliation registry has exactly 52 routing keys and contains generation.qa + "
        "generation.case_view",
        len(merged.known_action_families()) == 52
        and {"generation.qa", "generation.case_view"} <= set(merged.known_action_families()),
        f"got {len(merged.known_action_families())}",
    )
    entry_cv = mr.JournalEntrySnapshot(
        journal_id=rows_cv[0]["id"], resource_key=rows_cv[0]["resource_key"],
        action_family=rows_cv[0]["action_family"], target_ref=rows_cv[0]["target_ref"],
        target_state=rows_cv[0]["target_state"], pre_hash=rows_cv[0]["pre_hash"],
        pre_revision=rows_cv[0]["pre_revision"], expected_post_hash=rows_cv[0]["observed_post_hash"],
        state=rows_cv[0]["state"], idempotency_key=rows_cv[0]["idempotency_key"],
        request_fingerprint=rows_cv[0]["request_fingerprint"], actor_label=str(_ACTORS["lawyer"]),
    )
    evidence_cv = merged.get("generation.case_view").gather_evidence(entry_cv)
    check(
        "R2a registry-resolved case_view adapter re-verifies the REAL completed case_view row "
        "(post_state_verified=True, observed_post_hash == on-disk pending)",
        evidence_cv.post_state_verified is True and evidence_cv.observed_post_hash == sha256_file(pending_cv),
        f"evidence={evidence_cv}",
    )
    wrong_actor_entry = dataclasses.replace(entry_cv, actor_label="999")
    evidence_wrong = merged.get("generation.case_view").gather_evidence(wrong_actor_entry)
    check(
        "R2b the same row with a WRONG actor_label is NOT post-verified (mutation_actor_ref binding)",
        evidence_wrong.post_state_verified is False,
    )

finally:
    for _m in _cases_dir_holders:
        _m.CASES_DIR = _REAL_CASES_ROOT
    qa_validator.BASE_DIR = _REAL_QA_VALIDATOR_BASE_DIR
    qa_approval.BASE_DIR = _REAL_QA_APPROVAL_BASE_DIR
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

# ============================================================
# I1 - production data invariance (raw byte manifests, NOT git status -
#      /data/cases/ is gitignored for new files).
# ============================================================
_real_data_after = snapshot_tree(REAL_DATA_DIR)
check("I1a production data/ tree is BYTE-FOR-BYTE unchanged after this entire suite", _real_data_before == _real_data_after,
      f"diff={sorted(set(_real_data_before.items()) ^ set(_real_data_after.items()))[:5]}")
check("I1b real case_0001 tree (65 files) BYTE-IDENTICAL, no new files", snapshot_tree(REAL_CASE_0001) == _real_case_before)
check(
    "I1c the 13 historical *.approval.json records are BYTE-IDENTICAL (never rewritten)",
    {
        str(p.relative_to(REAL_CASE_0001)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(REAL_CASE_0001.rglob("*.approval.json"))
    } == _real_approval_audits_before,
)
check(
    "I1d real case.json / timeline.json / deadline.json and the real qa + case_view pending/canonical "
    "are BYTE-IDENTICAL (Commit A refreshes NO data/cases snapshot - that is Commit B)",
    {rel: hashlib.sha256((REAL_CASE_0001 / rel).read_bytes()).hexdigest() for rel in _REAL_KEY_FILES} == _real_key_before,
)
check("I1e tempdir removed (no residue)", not _TMP_ROOT.exists())

summarize_and_exit()
