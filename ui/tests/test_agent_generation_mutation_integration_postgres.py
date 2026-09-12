# ============================================================
# ROW 19C-3c-ii - REAL, END-TO-END PostgreSQL INTEGRATION PROOF for the
# case-scoped agent-gated generation mutation path (ui/services/agent_
# generation_mutation_facade.py + agent_generation_mutation_adapters.py
# + the ui.cli_mutate `generation` subcommand's five new row-keys + the
# merged ui/reconciliation_operator.py registry).
#
# WHAT IS REAL HERE: `ui.cli_mutate.main()` itself, `ui.services.
# cli_authz.CliActorAuthzRepository` against REAL iam rows, the real
# `mutation.mutation_journal`, real `pg_advisory_lock` session locking,
# the REAL `src/issue_spotting_engine.py`/`argument_engine.py` writers,
# and the REAL merged reconciliation registry (44 routing keys).
#
# WHAT IS NOT REAL: the case tree (re-identified copies of data/cases/
# case_0001 under a fresh tempdir); the LLM client for agent-mode
# scenarios (an explicit, in-process `llm_client=` test seam passed
# DIRECTLY to `preview_generation()`/`apply_generation()` - NEVER
# through the CLI, which never exposes this parameter). The
# repository's own data/ tree is NEVER written, proven byte-for-byte at
# the end. The same-case two-connection lock-serialization proof is
# DELIBERATELY NOT repeated here - it is generic coordinator machinery,
# already proven for this exact code path by the sibling deterministic-
# generation and other Row 19C-3c-i/3b suites.
#
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_agent_generation_mutation_integration_postgres.py
# ============================================================

import io
import hashlib
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
        f"--- test_agent_generation_mutation_integration_postgres: {passed} passed, {failed} failed, "
        f"{skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip(
        "the entire real-PostgreSQL agent-generation integration suite",
        "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip(
        "the entire real-PostgreSQL agent-generation integration suite",
        f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                     # noqa: E402
import ui.reconciliation_operator as op                                 # noqa: E402
from ui.services import agent_generation_mutation_facade as agf         # noqa: E402
from ui.services import agent_generation_mutation_adapters as ada       # noqa: E402
from ui.services import paths as _paths                                 # noqa: E402
from ui.services.common import sha256_file                              # noqa: E402

import issue_spotting_engine                                            # noqa: E402
import evidence_engine                                                  # noqa: E402
import argument_engine                                                  # noqa: E402
import risk_strategy_engine                                             # noqa: E402
import drafting_engine                                                  # noqa: E402

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")


def pg_connect():
    return psycopg.connect(dbname=PG_DB, autocommit=True)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, resource_key, action_family, actor_user_id, target_ref, target_state, "
                "state, pre_revision, idempotency_key, observed_post_hash, resolution_code "
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
            "to_regclass('mutation.mutation_journal')"
        )
        row = cur.fetchone()
    check("preflight: iam + mutation schemas all exist (migrations 0001-0004)", all(row))
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run against a half-migrated database.")
    summarize_and_exit()

_ACTORS = {"lawyer": 501, "analyst": 502}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"row19c3cii-agentgen-actor-{user_id}"),
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
# Case fixtures under a fresh tempdir; CASES_DIR redirect sweep (the
# SAME generic sweep test_generation_mutation_integration_postgres.py
# already established, extended to cover the five new engines).
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


_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_agentgen_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
check(
    "the CASES_DIR redirect sweep found ui.services.paths AND all five new engines",
    all(
        any(getattr(m, "__name__", "") == name for m in _cases_dir_holders)
        for name in (
            "ui.services.paths", "issue_spotting_engine", "evidence_engine", "argument_engine",
            "risk_strategy_engine", "drafting_engine",
        )
    ),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

_real_data_before = snapshot_real_data_tree()

RUN_TOKEN = uuid.uuid4().hex[:8]


def make_generation_case(tag):
    case_id = f"agentgenpg{RUN_TOKEN}{tag}"
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
    for family_dir_name, module in (
        ("issues", issue_spotting_engine), ("evidence", evidence_engine), ("arguments", argument_engine),
        ("risk_strategy", risk_strategy_engine), ("drafting", drafting_engine),
    ):
        family_dir = dst / family_dir_name
        if not family_dir.exists():
            continue
        for stale in family_dir.glob("*.pending"):
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


def preview_input_digest(case_id, row_key, *, with_agent=False, actor_user_id=None):
    args = [
        "generation", "--case", case_id, "--row-key", row_key,
        "--actor-user-id", str(actor_user_id if actor_user_id is not None else _ACTORS["lawyer"]),
    ]
    if with_agent:
        args.append("--with-agent")
    code, out, err = run_cli(args)
    if code != 0:
        raise AssertionError(f"preview failed: code={code} out={out!r} err={err!r}")
    for line in out.splitlines():
        if line.startswith("input_digest="):
            return line[len("input_digest="):]
    raise AssertionError(f"input_digest= not found in preview output: {out!r}")


try:
    # ============================================================
    # A1 - issue_spotting fresh deterministic generation, END-TO-END
    #      through the real CLI.
    # ============================================================
    case_a1, dir_a1 = make_generation_case("a1")
    seed_assignment(_ACTORS["lawyer"], case_a1, "lawyer")

    digest_a1 = preview_input_digest(case_a1, "issue_spotting")
    code, out, err = run_cli([
        "generation", "--case", case_a1, "--row-key", "issue_spotting",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_a1,
    ])
    check("A1a CLI issue_spotting apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    pending_path_a1 = issue_spotting_engine.get_pending_path(case_a1)
    check("A1b the REAL pending file was written", pending_path_a1.is_file())
    rows_a1 = journal_rows(f"case:{case_a1}")
    check(
        "A1c exactly one REAL journal row, state='completed', action_family='generation.issue_spotting'",
        len(rows_a1) == 1 and rows_a1[0]["state"] == "completed"
        and rows_a1[0]["action_family"] == "generation.issue_spotting"
        and rows_a1[0]["target_ref"] == "issue_spotting.pending"
        and rows_a1[0]["target_state"] == "generated",
        f"rows={rows_a1}",
    )
    check(
        "A1d journal row's observed_post_hash matches the REAL on-disk pending bytes",
        rows_a1[0]["observed_post_hash"] == sha256_file(pending_path_a1),
    )
    check(
        "A1e a real *.generation_audit.json audit file exists under generation_reviews/",
        any(issue_spotting_engine.get_reviews_dir(case_a1).glob("*.generation_audit.json")),
    )

    # ============================================================
    # A2 - SAFE REPLAY via the real CLI.
    # ============================================================
    pending_bytes_a1_before_replay = pending_path_a1.read_bytes()
    code, out, err = run_cli([
        "generation", "--case", case_a1, "--row-key", "issue_spotting",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_a1,
    ])
    check("A2a a real CLI replay of the SAME apply exits 0", code == 0, f"code={code} out={out!r} err={err!r}")
    check("A2b replayed=True was reported by the CLI", "replayed=True" in out, f"out={out!r}")
    check(
        "A2c pending bytes BYTE-IDENTICAL to before the replay (writer NOT re-invoked)",
        pending_path_a1.read_bytes() == pending_bytes_a1_before_replay,
    )
    check("A2d still exactly ONE journal row for this resource_key", len(journal_rows(f"case:{case_a1}")) == 1)

    # ============================================================
    # A3 - STALE DIGEST rejection: mutate a manifest input after preview,
    #      apply with the now-stale expected_input_digest -> clean
    #      domain error, zero NEW journal rows.
    # ============================================================
    case_a3, dir_a3 = make_generation_case("a3")
    seed_assignment(_ACTORS["lawyer"], case_a3, "lawyer")
    digest_a3 = preview_input_digest(case_a3, "issue_spotting")
    timeline_path_a3 = dir_a3 / "timeline" / "timeline.json"
    original_timeline_bytes = timeline_path_a3.read_bytes()
    mutated = json.loads(original_timeline_bytes.decode("utf-8"))
    mutated["_test_mutation_marker"] = "stale-digest-test"
    timeline_path_a3.write_text(json.dumps(mutated), encoding="utf-8")
    code, out, err = run_cli([
        "generation", "--case", case_a3, "--row-key", "issue_spotting",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply", "--expected-input-digest", digest_a3,
    ])
    check("A3a stale-digest apply exits non-zero (domain error)", code != 0, f"code={code} out={out!r} err={err!r}")
    check("A3b zero journal rows created for the stale attempt", journal_rows(f"case:{case_a3}") == [])
    timeline_path_a3.write_bytes(original_timeline_bytes)  # restore for cleanliness

    # ============================================================
    # A4 - DUAL NETWORK GATE, via the real CLI, pure usage-shape
    #      rejections BEFORE any connection.
    # ============================================================
    code, out, err = run_cli([
        "generation", "--case", case_a1, "--row-key", "issue_spotting",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--allow-network",
    ])
    check("A4a --allow-network alone (no --with-agent) rejected with usage error", code == 2, f"code={code} err={err!r}")
    code, out, err = run_cli([
        "generation", "--case", case_a1, "--row-key", "issue_spotting",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--apply",
        "--expected-input-digest", digest_a1, "--allow-network",
    ])
    check(
        "A4b --allow-network alone rejected even with --apply/--expected-input-digest present",
        code == 2, f"code={code} err={err!r}",
    )
    code, out, err = run_cli([
        "generation", "--case", case_a1, "--row-key", "deadline", "--anchor", "timeline_event_003",
        "--actor-user-id", str(_ACTORS["lawyer"]), "--with-agent",
    ])
    check("A4c --with-agent rejected for --row-key deadline", code == 2, f"code={code} err={err!r}")

    # ============================================================
    # A5 - ANALYST: preview allowed, apply denied (existence-blind).
    # ============================================================
    case_a5, dir_a5 = make_generation_case("a5")
    seed_assignment(_ACTORS["analyst"], case_a5, "analyst")
    digest_a5 = preview_input_digest(case_a5, "issue_spotting", actor_user_id=_ACTORS["analyst"])
    check("A5a analyst preview succeeded (read capability)", isinstance(digest_a5, str) and len(digest_a5) == 64)
    code, out, err = run_cli([
        "generation", "--case", case_a5, "--row-key", "issue_spotting",
        "--actor-user-id", str(_ACTORS["analyst"]), "--apply", "--expected-input-digest", digest_a5,
    ])
    check("A5b analyst apply denied (existence-blind authz denial)", code != 0, f"code={code} out={out!r} err={err!r}")
    check("A5c zero journal rows for the denied analyst attempt", journal_rows(f"case:{case_a5}") == [])

    # ============================================================
    # A6 - AGENT MODE with an in-process fake-client TEST SEAM, called
    #      DIRECTLY through the facade (never through the CLI, which has
    #      no llm_client parameter at all) - proves preview/apply produce
    #      the SAME identity (model_id="external_injected_client",
    #      prompt_agent_version REAL), preview never calls .generate(),
    #      and the real journal/audit reflect agent mode correctly.
    # ============================================================
    class _FakeAgentLLMClient:
        def __init__(self):
            self.generate_calls = 0

        def generate(self, prompt):
            self.generate_calls += 1
            return "[]"

    from ui.services import authz as _authz
    from ui.services import cli_authz as _cli_authz

    case_a6, dir_a6 = make_generation_case("a6")
    seed_assignment(_ACTORS["lawyer"], case_a6, "lawyer")

    authz_conn_a6 = authz_conn_factory()
    try:
        principal_a6 = _cli_authz.build_cli_principal(authz_conn_a6, _ACTORS["lawyer"])
        repository_a6 = _cli_authz.CliActorAuthzRepository(authz_conn_a6)

        fake_client_a6 = _FakeAgentLLMClient()
        preview_a6 = agf.preview_generation(
            "issue_spotting", case_a6, with_agent=True, llm_client=fake_client_a6,
            principal=principal_a6, authz_repository=repository_a6,
        )
        check(
            "A6a preview with fake client: model_id sentinel, prompt_agent_version REAL",
            preview_a6["model_id"] == "external_injected_client"
            and preview_a6["prompt_agent_version"] == "1.1",
        )
        check("A6b preview NEVER invoked the fake client's .generate()", fake_client_a6.generate_calls == 0)

        result_a6 = agf.apply_generation(
            "issue_spotting", case_a6, preview_a6["input_digest"],
            with_agent=True, allow_network=True, llm_client=fake_client_a6,
            principal=principal_a6, authz_repository=repository_a6, conn_factory=mutation_conn_factory,
        )
        check(
            "A6c apply with the SAME fake client succeeds using preview's own input_digest "
            "(no stale-digest mismatch)",
            result_a6.pending_sha256 is not None,
        )
        rows_a6 = journal_rows(f"case:{case_a6}")
        check(
            "A6d journal row reflects agent mode via the audit (fetched separately, not on the "
            "journal row itself)",
            len(rows_a6) == 1 and rows_a6[0]["state"] == "completed",
        )
        audit_files_a6 = list(issue_spotting_engine.get_reviews_dir(case_a6).glob("*.generation_audit.json"))
        check("A6e exactly one real audit file written", len(audit_files_a6) == 1)
        audit_record_a6 = json.loads(audit_files_a6[0].read_text(encoding="utf-8"))
        check(
            "A6f real audit record: generation_mode=agent, model_id sentinel, prompt_agent_version REAL",
            audit_record_a6["generation_mode"] == "agent"
            and audit_record_a6["model_id"] == "external_injected_client"
            and audit_record_a6["prompt_agent_version"] == "1.1",
        )
        check(
            "A6g mutation_actor_ref bound to the real IAM actor id (never the channel sentinel)",
            audit_record_a6["mutation_actor_ref"] == str(_ACTORS["lawyer"]),
        )
        check(
            "A6h channel sentinel is exactly local_lawyer_generation_cli",
            audit_record_a6["channel"] == "local_lawyer_generation_cli",
        )

        # A6i - adapter independently re-verifies this real, agent-mode
        # record end to end (cryptographic identity_payload re-hash).
        current_sha_a6 = sha256_file(issue_spotting_engine.get_pending_path(case_a6))
        matches_a6 = ada._audit_record_matches(
            audit_record_a6, "issue_spotting",
            idempotency_key=rows_a6[0]["idempotency_key"], resource_key=f"case:{case_a6}",
            action_family="generation.issue_spotting", target_ref="issue_spotting.pending",
            target_state="generated", actor_label=str(_ACTORS["lawyer"]), pending_sha256=current_sha_a6,
            carry_forward_dir_verified=None,
        )
        check("A6i adapter independently re-verifies the real agent-mode audit record end to end", matches_a6)
    finally:
        authz_conn_a6.close()

    # ============================================================
    # A7 - RECONCILIATION merged registry - 49 routing keys, real
    #      operator-factory construction (no fake injection).
    # ============================================================
    merged_registry_a7 = op._default_registry_factory()
    check(
        "A7 merged reconciliation registry has exactly 49 routing keys "
        "(10 approval + 24 review + 1 drafting_request + 2 promotion + 2 deterministic-generation "
        "+ 5 agent-generation + 1 fact-extraction-generation + 2 legal-research/case-law-generation "
        "+ 2 rag-bundle-build/activate)",
        len(merged_registry_a7.known_action_families()) == 49,
        f"got {len(merged_registry_a7.known_action_families())}",
    )
    check(
        "A7b all five new action families are present in the merged registry",
        all(
            f"generation.{row_key}" in merged_registry_a7.known_action_families()
            for row_key in ("issue_spotting", "evidence", "argument", "risk_strategy", "drafting")
        ),
    )

    # ============================================================
    # A8 - RECONCILIATION via gather_evidence() on the REAL completed
    #      A1 row, WITHOUT re-invoking anything - proves evidence-only
    #      verification.
    # ============================================================
    import ui.services.mutation_registry as mr

    entry_a1 = mr.JournalEntrySnapshot(
        journal_id=rows_a1[0]["id"], resource_key=rows_a1[0]["resource_key"],
        action_family=rows_a1[0]["action_family"], target_ref=rows_a1[0]["target_ref"],
        target_state=rows_a1[0]["target_state"], pre_hash=rows_a1[0]["pre_revision"] and None,
        pre_revision=rows_a1[0]["pre_revision"], expected_post_hash=rows_a1[0]["observed_post_hash"],
        state=rows_a1[0]["state"], idempotency_key=rows_a1[0]["idempotency_key"],
        request_fingerprint="unused-in-this-adapter", actor_label=str(_ACTORS["lawyer"]),
    )
    adapter_a8 = ada.AgentGenerationReconciliationAdapter(issue_spotting_engine, "issue_spotting")
    # NOTE: pre_hash was deliberately set to None above (unused by
    # gather_evidence's pre-state proof in this specific A8 check, which
    # focuses on post-state only); a full pre_hash round-trip is already
    # covered by the isolated adapter tests.
    evidence_a8 = adapter_a8.gather_evidence(entry_a1)
    check(
        "A8 gather_evidence() on the real completed A1 row: post_state_verified=True",
        evidence_a8.post_state_verified is True,
        f"evidence={evidence_a8}",
    )
    check(
        "A8b gather_evidence() observed_post_hash matches the real on-disk pending",
        evidence_a8.observed_post_hash == sha256_file(pending_path_a1),
    )

finally:
    # Cleanup - remove every case fixture directory this run created,
    # regardless of pass/fail, and restore every redirected CASES_DIR.
    for _m in _cases_dir_holders:
        _m.CASES_DIR = _REAL_CASES_ROOT
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

_real_data_after = snapshot_real_data_tree()
check(
    "production data/ tree is BYTE-FOR-BYTE unchanged after this entire suite",
    _real_data_before == _real_data_after,
)

summarize_and_exit()
