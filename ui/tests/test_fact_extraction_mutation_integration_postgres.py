# ============================================================
# ROW 19C-3c-iii - REAL, END-TO-END PostgreSQL INTEGRATION PROOF for
# the document-scoped, agent-gated fact-extraction generation mutation
# path (ui/services/fact_extraction_mutation_facade.py + fact_
# extraction_mutation_adapters.py + the ui.cli_mutate `generation`
# subcommand's `fact_extraction` row-key + the merged ui/
# reconciliation_operator.py registry).
#
# WHAT IS REAL HERE: `ui.cli_mutate.main()` itself (for the network-free
# preview/usage-shape paths), `ui.services.cli_authz.
# CliActorAuthzRepository` against REAL iam rows, the real `mutation.
# mutation_journal`, real `pg_advisory_lock` session locking, the REAL
# `src/fact_extraction_engine.py` writer, and the REAL merged
# reconciliation registry (45 routing keys).
#
# WHAT IS NOT REAL: the case tree (a re-identified copy of data/cases/
# case_0001 under a fresh tempdir); the LLM client for every apply
# scenario (an explicit, in-process `llm_client=` test seam passed
# DIRECTLY to `preview_generation()`/`apply_generation()` - NEVER
# through the CLI, which never exposes this parameter - AND this
# family, unlike the deterministic deadline/timeline family, has NO
# deterministic mode at all, so a real CLI-driven `--apply` would
# genuinely attempt a real Anthropic network call; this suite therefore
# NEVER drives a real apply through the CLI, only through the facade
# with an injected fake client). The repository's own data/ tree is
# NEVER written, proven byte-for-byte at the end.
#
# Run: VERGI_TEST_PG_DSN=<db> python ui/tests/test_fact_extraction_mutation_integration_postgres.py
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
        f"--- test_fact_extraction_mutation_integration_postgres: {passed} passed, {failed} failed, "
        f"{skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")
if not PG_DB:
    skip(
        "the entire real-PostgreSQL fact-extraction generation integration suite",
        "VERGI_TEST_PG_DSN is not set. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover
    skip(
        "the entire real-PostgreSQL fact-extraction generation integration suite",
        f"`import psycopg` failed ({_psycopg_error!r}). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

import ui.cli_mutate as cli_mutate                                     # noqa: E402
import ui.reconciliation_operator as op                                 # noqa: E402
from ui.services import fact_extraction_mutation_facade as fac          # noqa: E402
from ui.services import fact_extraction_mutation_adapters as ada        # noqa: E402
from ui.services import paths as _paths                                 # noqa: E402
from ui.services.common import sha256_file                              # noqa: E402

import fact_extraction_engine as fee                                    # noqa: E402
import document_reference_resolver as drr                               # noqa: E402
import fact_approval                                                    # noqa: E402

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

_ACTORS = {"lawyer": 601, "analyst": 602}
_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for user_id in _ACTORS.values():
            cur.execute(
                "INSERT INTO iam.users (id, display_name, disabled) VALUES (%s, %s, FALSE) "
                "ON CONFLICT (id) DO UPDATE SET disabled = FALSE",
                (user_id, f"row19c3ciii-factextraction-actor-{user_id}"),
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
DOCUMENT_ID = "dava_dilekcesi_001"


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


_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_factextraction_pgint_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
check(
    "the CASES_DIR redirect sweep found ui.services.paths, fact_extraction_engine, "
    "document_reference_resolver AND fact_approval (the promotion writer - needed for the "
    "generation-pending-to-canonical-promotion compatibility proof)",
    all(
        any(getattr(m, "__name__", "") == name for m in _cases_dir_holders)
        for name in (
            "ui.services.paths", "fact_extraction_engine", "document_reference_resolver",
            "fact_approval",
        )
    ),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
for _m in _cases_dir_holders:
    _m.CASES_DIR = _TMP_CASES

_real_data_before = snapshot_real_data_tree()

RUN_TOKEN = uuid.uuid4().hex[:8]


def make_generation_case(tag):
    case_id = f"factextpg{RUN_TOKEN}{tag}"
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
    extractions_dir = dst / "documents" / DOCUMENT_ID / "extractions"
    for stale in extractions_dir.glob("*.pending"):
        stale.unlink()
    for stale_dir_name in ("history", "generation_reviews"):
        stale_dir = extractions_dir / stale_dir_name
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


def preview_input_digest_via_cli(case_id, document_id, *, actor_user_id=None):
    args = [
        "generation", "--case", case_id, "--row-key", "fact_extraction", "--document", document_id,
        "--with-agent", "--actor-user-id", str(actor_user_id if actor_user_id is not None else _ACTORS["lawyer"]),
    ]
    code, out, err = run_cli(args)
    if code != 0:
        raise AssertionError(f"preview failed: code={code} out={out!r} err={err!r}")
    for line in out.splitlines():
        if line.startswith("input_digest="):
            return line[len("input_digest="):]
    raise AssertionError(f"input_digest= not found in preview output: {out!r}")


class _FakeAgentLLMClient:
    def __init__(self, payload_text='{"facts": [], "warnings": []}'):
        self._payload_text = payload_text
        self.generate_calls = 0

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            self._outer.generate_calls += 1

            class _Block:
                type = "text"

            block = _Block()
            block.text = self._outer._payload_text

            class _Resp:
                pass

            resp = _Resp()
            resp.content = [block]
            return resp

    @property
    def messages(self):
        return self._Messages(self)


def _valid_fact_payload_text(*, count=1, tag=""):
    facts = []
    for index in range(count):
        facts.append({
            "fact_kind": "taxpayer_claim",
            "statement": f"Davacı örnek iddia {tag}{index} ileri sürmüştür.",
            "normalized_statement": None,
            "extraction_basis": "explicit_text",
            "attributed_party_id": None,
            "attributed_actor_label": None,
            "source": {
                "page": None, "section": None, "paragraph": None,
                "text_excerpt": f"örnek alıntı metni {tag}{index}",
            },
            "structured_values": [],
            "related_party_ids": [],
            "related_document_ids": [],
            "related_dispute_item_ids": [],
            "confidence": 0.8,
            "verification_state": "unverified",
            "notes": None,
        })
    return json.dumps({"facts": facts, "warnings": []})


class _ExplodingLLMClient:
    class _Messages:
        def create(self, **kwargs):
            raise AssertionError(
                "a REAL/fake .messages.create() call was made on a build that should have been "
                "SKIPPED (build_needed=False expected) - the read-only precheck failed to honor "
                "an existing journal row"
            )

    messages = _Messages()


from ui.services import authz as _authz                                 # noqa: E402
from ui.services import cli_authz as _cli_authz                          # noqa: E402


try:
    # ============================================================
    # B1 - real CLI PREVIEW (network-free, with_agent=True required) -
    #      succeeds, real input_digest, real manifest scan against the
    #      real synthetic case tree.
    # ============================================================
    case_b1, dir_b1 = make_generation_case("b1")
    seed_assignment(_ACTORS["lawyer"], case_b1, "lawyer")

    digest_b1 = preview_input_digest_via_cli(case_b1, DOCUMENT_ID)
    check("B1a CLI preview returns a real 64-hex-char input_digest", len(digest_b1) == 64 and all(c in "0123456789abcdef" for c in digest_b1))
    check("B1b zero journal rows exist yet for this case (preview never writes)", journal_rows(f"case:{case_b1}") == [])

    # ============================================================
    # B2 - DUAL NETWORK GATE + --document grammar, via the real CLI,
    #      pure usage-shape rejections BEFORE any connection (mirrors
    #      the isolated CLI tests, re-proven here with a real DB
    #      configured to show the rejection genuinely precedes any
    #      connection/journal access even when one IS available).
    # ============================================================
    code, out, err = run_cli([
        "generation", "--case", case_b1, "--row-key", "fact_extraction", "--document", DOCUMENT_ID,
        "--actor-user-id", str(_ACTORS["lawyer"]),
    ])
    check("B2a preview WITHOUT --with-agent rejected with usage error", code == 2, f"code={code} err={err!r}")
    code, out, err = run_cli([
        "generation", "--case", case_b1, "--row-key", "fact_extraction", "--document", DOCUMENT_ID,
        "--with-agent", "--allow-network", "--actor-user-id", str(_ACTORS["lawyer"]),
    ])
    check("B2b --allow-network on preview rejected with usage error", code == 2, f"code={code} err={err!r}")
    code, out, err = run_cli([
        "generation", "--case", case_b1, "--row-key", "fact_extraction", "--document", DOCUMENT_ID,
        "--with-agent", "--actor-user-id", str(_ACTORS["lawyer"]), "--apply",
        "--expected-input-digest", digest_b1,
    ])
    check("B2c apply WITHOUT --allow-network rejected with usage error", code == 2, f"code={code} err={err!r}")
    check("B2d zero journal rows after the three rejected usage-shape attempts", journal_rows(f"case:{case_b1}") == [])

    # ============================================================
    # B3 - FRESH apply, DIRECT facade call with an injected fake
    #      client (never through the CLI, which never exposes
    #      llm_client and which would otherwise attempt a REAL
    #      Anthropic call for this family - there is no deterministic
    #      mode to fall back to). build_needed=True (no prior journal
    #      row) - the fake client's .messages.create() IS called
    #      exactly once.
    # ============================================================
    authz_conn_b3 = authz_conn_factory()
    try:
        principal_b3 = _cli_authz.build_cli_principal(authz_conn_b3, _ACTORS["lawyer"])
        repository_b3 = _cli_authz.CliActorAuthzRepository(authz_conn_b3)

        fake_client_b3 = _FakeAgentLLMClient(_valid_fact_payload_text(count=2, tag="b3_"))
        # preview and apply MUST use the SAME llm_client-presence (both
        # produce model_id="external_injected_client" whenever llm_client
        # is not None, regardless of which fake object it is) so their
        # computed input_digest genuinely matches - preview NEVER calls
        # any method on it (see the facade's own isolated-test proof).
        preview_b3 = fac.preview_generation(
            case_b1, DOCUMENT_ID, with_agent=True, llm_client=fake_client_b3,
            principal=principal_b3, authz_repository=repository_b3,
        )
        result_b3 = fac.apply_generation(
            case_b1, DOCUMENT_ID, preview_b3["input_digest"],
            with_agent=True, allow_network=True, llm_client=fake_client_b3,
            principal=principal_b3, authz_repository=repository_b3, conn_factory=mutation_conn_factory,
        )
        check("B3a fresh apply succeeded, NOT replayed", result_b3.replayed is False)
        check("B3b fake client's .messages.create() was called EXACTLY ONCE (build genuinely ran)", fake_client_b3.generate_calls == 1)
        pending_path_b3 = fee.get_pending_path(case_b1, DOCUMENT_ID)
        check("B3c the REAL pending file was written", pending_path_b3.is_file())
        check("B3d result.pending_sha256 matches the REAL on-disk bytes", result_b3.pending_sha256 == sha256_file(pending_path_b3))
        rows_b3 = journal_rows(f"case:{case_b1}")
        check(
            "B3e exactly one REAL journal row, state='completed', action_family="
            "'generation.fact_extraction', target_ref='fact.<doc>.pending'",
            len(rows_b3) == 1 and rows_b3[0]["state"] == "completed"
            and rows_b3[0]["action_family"] == "generation.fact_extraction"
            and rows_b3[0]["target_ref"] == f"fact.{DOCUMENT_ID}.pending"
            and rows_b3[0]["target_state"] == "generated",
            f"rows={rows_b3}",
        )
        check(
            "B3f journal row's observed_post_hash matches the REAL on-disk pending bytes",
            rows_b3[0]["observed_post_hash"] == sha256_file(pending_path_b3),
        )
        audit_files_b3 = list(fee.get_reviews_dir(case_b1, DOCUMENT_ID).glob("*.generation_audit.json"))
        check("B3g exactly one real *.generation_audit.json audit file exists", len(audit_files_b3) == 1)
        audit_record_b3 = json.loads(audit_files_b3[0].read_text(encoding="utf-8"))
        check(
            "B3h real audit record: document_id/generation_mode/model_id/engine_version exact",
            audit_record_b3["document_id"] == DOCUMENT_ID
            and audit_record_b3["generation_mode"] == "agent"
            and audit_record_b3["model_id"] == "external_injected_client"
            and audit_record_b3["engine_version"] == fee.FACT_EXTRACTION_ENGINE_VERSION,
        )

        # B3i - adapter independently re-verifies this real record end to
        # end (cryptographic identity_payload re-hash + direct
        # entry.pre_revision binding).
        adapter_b3 = ada.FactExtractionReconciliationAdapter(fee)
        current_sha_b3 = sha256_file(pending_path_b3)
        matches_b3 = ada._audit_record_matches(
            audit_record_b3,
            idempotency_key=rows_b3[0]["idempotency_key"], resource_key=f"case:{case_b1}",
            action_family="generation.fact_extraction", document_id=DOCUMENT_ID,
            target_ref=f"fact.{DOCUMENT_ID}.pending", target_state="generated",
            actor_label=str(_ACTORS["lawyer"]), pending_sha256=current_sha_b3,
            entry_pre_revision=rows_b3[0]["pre_revision"],
        )
        check("B3i adapter independently re-verifies the real record end to end", matches_b3)
    finally:
        authz_conn_b3.close()

    # ============================================================
    # B4 - SAFE REPLAY, direct facade call, SAME input_digest, a
    #      DIFFERENT (EXPLODING) fake client this time - proves the
    #      READ-ONLY precheck genuinely SKIPPED the build (the
    #      exploding client's .messages.create() is NEVER called; if
    #      it had been, this would raise AssertionError, not merely
    #      fail a `check()`).
    # ============================================================
    authz_conn_b4 = authz_conn_factory()
    try:
        principal_b4 = _cli_authz.build_cli_principal(authz_conn_b4, _ACTORS["lawyer"])
        repository_b4 = _cli_authz.CliActorAuthzRepository(authz_conn_b4)

        pending_bytes_b3_before_replay = fee.get_pending_path(case_b1, DOCUMENT_ID).read_bytes()
        exploding_client_b4 = _ExplodingLLMClient()
        # MUST use the SAME injected-client provenance B3 used (both
        # resolve to model_id="external_injected_client") - a CLI-driven
        # (no-llm_client, production-provenance) preview here would
        # compute a DIFFERENT input_digest than the journal row B3 wrote,
        # and would raise StaleViewError before ever reaching the
        # build-skip precheck this scenario is actually testing.
        preview_b4 = fac.preview_generation(
            case_b1, DOCUMENT_ID, with_agent=True, llm_client=exploding_client_b4,
            principal=principal_b4, authz_repository=repository_b4,
        )
        digest_b4 = preview_b4["input_digest"]
        result_b4 = fac.apply_generation(
            case_b1, DOCUMENT_ID, digest_b4,
            with_agent=True, allow_network=True, llm_client=exploding_client_b4,
            principal=principal_b4, authz_repository=repository_b4, conn_factory=mutation_conn_factory,
        )
        check("B4a replayed=True was reported by apply_generation()", result_b4.replayed is True)
        check(
            "B4b pending bytes BYTE-IDENTICAL to before the replay (writer NOT re-invoked, build "
            "NOT re-run)",
            fee.get_pending_path(case_b1, DOCUMENT_ID).read_bytes() == pending_bytes_b3_before_replay,
        )
        check("B4c still exactly ONE journal row for this resource_key", len(journal_rows(f"case:{case_b1}")) == 1)
    finally:
        authz_conn_b4.close()

    # ============================================================
    # B5 - STALE DIGEST rejection: mutate a manifest input after
    #      preview, apply with the now-stale expected_input_digest ->
    #      clean domain error, zero NEW journal rows, build NEVER
    #      attempted (exploding client).
    # ============================================================
    case_b5, dir_b5 = make_generation_case("b5")
    seed_assignment(_ACTORS["lawyer"], case_b5, "lawyer")
    doc_json_b5 = dir_b5 / "documents" / DOCUMENT_ID / "document.json"
    original_doc_bytes_b5 = doc_json_b5.read_bytes()

    authz_conn_b5 = authz_conn_factory()
    try:
        principal_b5 = _cli_authz.build_cli_principal(authz_conn_b5, _ACTORS["lawyer"])
        repository_b5 = _cli_authz.CliActorAuthzRepository(authz_conn_b5)
        exploding_client_b5 = _ExplodingLLMClient()
        # Same injected-client provenance for BOTH preview and apply -
        # isolates the staleness to the deliberate document.json
        # mutation below, not an accidental provenance mismatch (preview
        # never calls any method on the client either way).
        preview_b5 = fac.preview_generation(
            case_b5, DOCUMENT_ID, with_agent=True, llm_client=exploding_client_b5,
            principal=principal_b5, authz_repository=repository_b5,
        )
        digest_b5 = preview_b5["input_digest"]

        mutated_doc_b5 = json.loads(original_doc_bytes_b5.decode("utf-8"))
        mutated_doc_b5["_test_mutation_marker"] = "stale-digest-test"
        doc_json_b5.write_text(json.dumps(mutated_doc_b5), encoding="utf-8")

        raised_b5 = False
        try:
            fac.apply_generation(
                case_b5, DOCUMENT_ID, digest_b5,
                with_agent=True, allow_network=True, llm_client=exploding_client_b5,
                principal=principal_b5, authz_repository=repository_b5, conn_factory=mutation_conn_factory,
            )
        except fac.StaleViewError:
            raised_b5 = True
        check("B5a stale-digest apply raises StaleViewError, exploding client never touched", raised_b5)
    finally:
        authz_conn_b5.close()
    check("B5b zero journal rows created for the stale attempt", journal_rows(f"case:{case_b5}") == [])
    doc_json_b5.write_bytes(original_doc_bytes_b5)  # restore for cleanliness

    # ============================================================
    # B6 - ANALYST: preview allowed, apply denied (existence-blind),
    #      via the real CLI + a real direct facade call.
    # ============================================================
    case_b6, dir_b6 = make_generation_case("b6")
    seed_assignment(_ACTORS["analyst"], case_b6, "analyst")
    digest_b6 = preview_input_digest_via_cli(case_b6, DOCUMENT_ID, actor_user_id=_ACTORS["analyst"])
    check("B6a analyst preview succeeded (read capability)", isinstance(digest_b6, str) and len(digest_b6) == 64)

    authz_conn_b6 = authz_conn_factory()
    try:
        principal_b6 = _cli_authz.build_cli_principal(authz_conn_b6, _ACTORS["analyst"])
        repository_b6 = _cli_authz.CliActorAuthzRepository(authz_conn_b6)
        raised_b6 = False
        try:
            fac.apply_generation(
                case_b6, DOCUMENT_ID, digest_b6,
                with_agent=True, allow_network=True, llm_client=_ExplodingLLMClient(),
                principal=principal_b6, authz_repository=repository_b6, conn_factory=mutation_conn_factory,
            )
        except _authz.CaseAccessDeniedError:
            raised_b6 = True
        check("B6b analyst apply denied (existence-blind authz denial), exploding client never touched", raised_b6)
    finally:
        authz_conn_b6.close()
    check("B6c zero journal rows for the denied analyst attempt", journal_rows(f"case:{case_b6}") == [])

    # ============================================================
    # B7 - RECONCILIATION merged registry - 45 routing keys, real
    #      operator-factory construction (no fake injection).
    # ============================================================
    merged_registry_b7 = op._default_registry_factory()
    check(
        "B7 merged reconciliation registry has exactly 45 routing keys "
        "(10 approval + 24 review + 1 drafting_request + 2 promotion + 2 deterministic-generation "
        "+ 5 agent-generation + 1 fact-extraction-generation)",
        len(merged_registry_b7.known_action_families()) == 45,
        f"got {len(merged_registry_b7.known_action_families())}",
    )
    check(
        "B7b generation.fact_extraction is present in the merged registry",
        "generation.fact_extraction" in merged_registry_b7.known_action_families(),
    )

    # ============================================================
    # B8 - RECONCILIATION via gather_evidence() on the REAL completed
    #      B3 row, WITHOUT re-invoking anything.
    # ============================================================
    import ui.services.mutation_registry as mr

    rows_b3_final = journal_rows(f"case:{case_b1}")
    entry_b8 = mr.JournalEntrySnapshot(
        journal_id=rows_b3_final[0]["id"], resource_key=rows_b3_final[0]["resource_key"],
        action_family=rows_b3_final[0]["action_family"], target_ref=rows_b3_final[0]["target_ref"],
        target_state=rows_b3_final[0]["target_state"], pre_hash=None,
        pre_revision=rows_b3_final[0]["pre_revision"], expected_post_hash=rows_b3_final[0]["observed_post_hash"],
        state=rows_b3_final[0]["state"], idempotency_key=rows_b3_final[0]["idempotency_key"],
        request_fingerprint="unused-in-this-adapter", actor_label=str(_ACTORS["lawyer"]),
    )
    adapter_b8 = ada.FactExtractionReconciliationAdapter(fee)
    evidence_b8 = adapter_b8.gather_evidence(entry_b8)
    check(
        "B8 gather_evidence() on the real completed B3 row: post_state_verified=True",
        evidence_b8.post_state_verified is True,
        f"evidence={evidence_b8}",
    )
    check(
        "B8b gather_evidence() observed_post_hash matches the real on-disk pending",
        evidence_b8.observed_post_hash == sha256_file(fee.get_pending_path(case_b1, DOCUMENT_ID)),
    )

    # ============================================================
    # B9 - BUILD-SKIP AGAINST A NON-'completed' ROW (spec §D: "current
    #      idempotency key için herhangi bir journal satırı VARSA...
    #      HEPSİNDE build_needed=False"). Direct SQL fault-injection
    #      flips a REAL 'completed' row to 'failed' for a FRESH
    #      idempotency_key (via a real, isolated fixture case), then a
    #      second apply attempt with an EXPLODING client for the SAME
    #      identity must still skip the build (PriorAttemptFailedError
    #      from run_mutation(), never a real/fake model call).
    # ============================================================
    case_b9, dir_b9 = make_generation_case("b9")
    seed_assignment(_ACTORS["lawyer"], case_b9, "lawyer")

    authz_conn_b9 = authz_conn_factory()
    try:
        principal_b9 = _cli_authz.build_cli_principal(authz_conn_b9, _ACTORS["lawyer"])
        repository_b9 = _cli_authz.CliActorAuthzRepository(authz_conn_b9)
        fake_client_b9 = _FakeAgentLLMClient(_valid_fact_payload_text(count=1, tag="b9_"))
        preview_b9 = fac.preview_generation(
            case_b9, DOCUMENT_ID, with_agent=True, llm_client=fake_client_b9,
            principal=principal_b9, authz_repository=repository_b9,
        )
        result_b9_first = fac.apply_generation(
            case_b9, DOCUMENT_ID, preview_b9["input_digest"],
            with_agent=True, allow_network=True, llm_client=fake_client_b9,
            principal=principal_b9, authz_repository=repository_b9, conn_factory=mutation_conn_factory,
        )
        check("B9a first apply for the b9 fixture succeeded", result_b9_first.replayed is False)
    finally:
        authz_conn_b9.close()

    _flip_conn = pg_connect()
    try:
        with _flip_conn.cursor() as cur:
            cur.execute(
                "UPDATE mutation.mutation_journal SET state = 'failed', resolution_code = "
                "'row19c3ciii_test_fault_injection', resolved_at = now() "
                "WHERE resource_key = %s AND action_family = 'generation.fact_extraction'",
                (f"case:{case_b9}",),
            )
            check("B9b fault injection: exactly 1 row flipped to 'failed'", cur.rowcount == 1)
    finally:
        _flip_conn.close()

    authz_conn_b9b = authz_conn_factory()
    try:
        principal_b9b = _cli_authz.build_cli_principal(authz_conn_b9b, _ACTORS["lawyer"])
        repository_b9b = _cli_authz.CliActorAuthzRepository(authz_conn_b9b)
        exploding_client_b9b = _ExplodingLLMClient()
        # Same injected-client provenance sentinel ("external_injected_
        # client") as B9's first apply used - a production-provenance
        # (no-llm_client) preview here would compute a DIFFERENT
        # input_digest and raise StaleViewError before ever reaching the
        # PriorAttemptFailedError this scenario is actually testing.
        preview_b9b = fac.preview_generation(
            case_b9, DOCUMENT_ID, with_agent=True, llm_client=exploding_client_b9b,
            principal=principal_b9b, authz_repository=repository_b9b,
        )
        check(
            "B9c a fresh preview against the UNCHANGED case fixture reproduces the SAME "
            "input_digest as before the fault injection",
            preview_b9b["input_digest"] == preview_b9["input_digest"],
        )
        raised_b9c = False
        try:
            fac.apply_generation(
                case_b9, DOCUMENT_ID, preview_b9b["input_digest"],
                with_agent=True, allow_network=True, llm_client=exploding_client_b9b,
                principal=principal_b9b, authz_repository=repository_b9b, conn_factory=mutation_conn_factory,
            )
        except Exception as error:  # noqa: BLE001
            raised_b9c = type(error).__name__ == "PriorAttemptFailedError"
            _b9c_error = error
        check(
            "B9d apply against a 'failed' prior row with the SAME identity raises "
            "PriorAttemptFailedError (terminal, permanent) - the EXPLODING client's ."
            "messages.create() was NEVER called, proving the read-only precheck genuinely "
            "skipped the build for a NON-'completed' state too",
            raised_b9c,
        )
    finally:
        authz_conn_b9b.close()

    # ============================================================
    # B10 - GENERATION-PENDING-TO-PROMOTION COMPATIBILITY: the pending
    #      file this suite's own B3 apply produced is genuinely
    #      approvable through the SEPARATE, LOCKED `promotion.fact`
    #      facade (Row 19C-3b Slice 2) - i.e. this family's writer
    #      produces output in the pinned CURRENT_PENDING_FILENAME shape
    #      fact_approval.py already expects, end to end.
    # ============================================================
    from ui.services import promotion_mutation_facade as _promotion_facade

    authz_conn_b10 = authz_conn_factory()
    try:
        principal_b10 = _cli_authz.build_cli_principal(authz_conn_b10, _ACTORS["lawyer"])
        repository_b10 = _cli_authz.CliActorAuthzRepository(authz_conn_b10)
        preview_promotion_b10 = _promotion_facade.preview_promotion(
            "fact", case_b1, document_id=DOCUMENT_ID, principal=principal_b10, authz_repository=repository_b10,
        )
        check(
            "B10a promotion preview finds this suite's OWN generated pending, matching hash",
            preview_promotion_b10["pending_hash"] == sha256_file(fee.get_pending_path(case_b1, DOCUMENT_ID)),
        )
        promotion_result_b10 = _promotion_facade.approve_promotion_mutation(
            "fact", case_b1, preview_promotion_b10["pending_hash"],
            document_id=DOCUMENT_ID, note=None,
            principal=principal_b10, authz_repository=repository_b10, conn_factory=mutation_conn_factory,
        )
        check(
            "B10b the generation-produced pending was REALLY promoted to canonical facts.json",
            promotion_result_b10.canonical_path.is_file(),
        )
    finally:
        authz_conn_b10.close()

finally:
    for _m in _cases_dir_holders:
        _m.CASES_DIR = _REAL_CASES_ROOT
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

_real_data_after = snapshot_real_data_tree()
check(
    "production data/ tree is BYTE-FOR-BYTE unchanged after this entire suite",
    _real_data_before == _real_data_after,
)

summarize_and_exit()
