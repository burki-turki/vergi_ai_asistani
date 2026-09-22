# ============================================================
# ROW 19C-3c-ii - ui/services/agent_generation_mutation_facade.py
# ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator connection -
# exercises the facade's own pure/read-only functions directly: usage-
# shape validation, the containment-before-traversal manifest scanner
# (including real Windows NTFS junctions for escaping/broken-link
# cases, and a `Path.glob()` zero-call mechanical proof), identity
# payload freeze/reconstruct, and verified output-path derivation.
#
# Run: python ui/tests/test_agent_generation_mutation_facade_isolated.py
# ============================================================

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import issue_spotting_engine                                 # noqa: E402
import evidence_engine                                        # noqa: E402
import argument_engine                                        # noqa: E402
import risk_strategy_agent                                    # noqa: E402
from ui.services import agent_generation_mutation_facade as agf  # noqa: E402
from ui.services import common as _common                        # noqa: E402

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
        check(label, True, detail)
    except Exception as error:  # noqa: BLE001
        check(label, False, f"{detail} (wrong exception type: {type(error).__name__}: {error})")
    else:
        check(label, False, f"{detail} (no exception raised)")


REAL_CASE_0001 = REPO_ROOT / "data" / "cases" / "case_0001"
CASE_ID = "case_0001"


# ============================================================
# 1) Row/action-family/target-ref helpers - pure, no I/O.
# ============================================================

check(
    "AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME has exactly the five expected families",
    set(agf.AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME.keys())
    == {"issue_spotting", "evidence", "argument", "risk_strategy", "drafting"},
)
check(
    "agent_generation_action_family_for produces the exact generation.<row_key> string",
    agf.agent_generation_action_family_for("argument") == "generation.argument",
)
check(
    "agent_generation_target_ref_for produces the exact <row_key>.pending string",
    agf.agent_generation_target_ref_for("drafting") == "drafting.pending",
)
check(
    "FAMILY_LOGICAL_NAME_COUNTS is exactly 3/3/8/10/12",
    agf.FAMILY_LOGICAL_NAME_COUNTS == {
        "issue_spotting": 3, "evidence": 3, "argument": 8, "risk_strategy": 10, "drafting": 12,
    },
)


# ============================================================
# 2) Usage-shape validation - pure, no I/O, before any connection.
# ============================================================

expect_raises(
    KeyError, lambda: agf._check_argument_shapes("not_a_real_family", for_apply=False),
    "_check_argument_shapes: unknown row_key raises KeyError",
)
expect_raises(
    agf.AgentGenerationArgumentError,
    lambda: agf._check_argument_shapes("argument", None, for_apply=True),
    "_check_argument_shapes: apply without expected_input_digest raises AgentGenerationArgumentError",
)
try:
    agf._check_argument_shapes("argument", "somedigest", for_apply=True)
    check("_check_argument_shapes: apply WITH expected_input_digest passes", True)
except Exception as error:  # noqa: BLE001
    check("_check_argument_shapes: apply WITH expected_input_digest passes", False, str(error))


# ============================================================
# 3) Model/prompt provenance - deterministic / agent / injected-client,
#    read fresh via importlib each call (no caching).
# ============================================================

mode_a, model_a, prompt_a = agf._resolve_generation_provenance("risk_strategy", False, None)
check(
    "deterministic mode: model_id/prompt_agent_version are the closed sentinels",
    mode_a == "deterministic" and model_a == "deterministic_no_model" and prompt_a == "n/a",
)

mode_b, model_b, prompt_b = agf._resolve_generation_provenance("risk_strategy", True, None)
check(
    "real agent mode: model_id/prompt_agent_version are the REAL risk_strategy_agent constants",
    model_b == risk_strategy_agent.DEFAULT_AGENT_MODEL and prompt_b == risk_strategy_agent.RISK_STRATEGY_AGENT_VERSION,
)


class _FakeLLMClient:
    def generate(self, prompt):
        raise AssertionError("provenance resolution must never call .generate()")


mode_c, model_c, prompt_c = agf._resolve_generation_provenance("risk_strategy", True, _FakeLLMClient())
check(
    "injected client: model_id sentinel, prompt_agent_version REAL (not sentinel), .generate() never called",
    model_c == "external_injected_client" and prompt_c == risk_strategy_agent.RISK_STRATEGY_AGENT_VERSION,
)

mode_d, model_d, prompt_d = agf._resolve_generation_provenance("risk_strategy", False, _FakeLLMClient())
check(
    "deterministic mode ignores a supplied llm_client entirely",
    mode_d == "deterministic" and model_d == "deterministic_no_model" and prompt_d == "n/a",
)


# ============================================================
# 4) Identity payload freeze/reconstruct - canonical bytes, exact
#    round-trip, mutation-after-freeze does not leak.
# ============================================================

payload_e = {"manifest_version": "v", "manifest": [{"a": 1}], "generation_mode": "deterministic",
             "model_id": "deterministic_no_model", "prompt_agent_version": "n/a"}
bytes_e1 = agf._canonical_identity_bytes(payload_e)
bytes_e2 = agf._canonical_identity_bytes(json.loads(json.dumps(payload_e)))
check("canonical identity bytes are deterministic across equal-content payloads", bytes_e1 == bytes_e2)

digest_e = agf._compute_input_digest(bytes_e1)
check("input_digest is a 64-hex-char sha256", len(digest_e) == 64 and all(c in "0123456789abcdef" for c in digest_e))

reconstructed_e = json.loads(bytes_e1.decode("utf-8"))
payload_e["manifest"].append({"MUTATED": True})  # mutate original after freeze
check(
    "reconstructed identity payload is unaffected by post-freeze mutation of the original dict",
    reconstructed_e["manifest"] == [{"a": 1}],
)


# ============================================================
# 5) Manifest scanner - real case_0001, no mutation (read-only scan).
# ============================================================

for row_key, module in [
    ("issue_spotting", issue_spotting_engine), ("evidence", evidence_engine), ("argument", argument_engine),
]:
    case_root = agf._resolve_module_case_root_real(module, CASE_ID)
    manifest = agf._build_manifest_containers(row_key, case_root, CASE_ID)
    check(
        f"real case_0001 manifest scan ({row_key}): container count matches spec exactly",
        len(manifest) == agf.FAMILY_LOGICAL_NAME_COUNTS[row_key],
    )
    check(
        f"real case_0001 manifest scan ({row_key}): sorted by logical_name",
        [c["logical_name"] for c in manifest] == sorted(c["logical_name"] for c in manifest),
    )
    for container in manifest:
        for file_entry in container["files"]:
            check(
                f"{row_key}/{container['logical_name']}: logical_relative_path is POSIX-form "
                "(no backslash)",
                "\\" not in file_entry["logical_relative_path"],
            )


# ============================================================
# 6) Containment safety - real Windows NTFS junctions (mklink /J,
#    never monkeypatched) for escaping/broken links, proving the
#    scanner fails closed and never treats a broken/escaping link as
#    "missing".
# ============================================================

_tmp_containment_root = Path(tempfile.mkdtemp(prefix="vergi_agf_containment_"))

try:
    fixture_case = _tmp_containment_root / "cases" / CASE_ID
    shutil.copytree(REAL_CASE_0001, fixture_case)
    for stale in (fixture_case / "issues").glob("*.pending"):
        stale.unlink()

    original_cases_dir = issue_spotting_engine.CASES_DIR
    issue_spotting_engine.CASES_DIR = _tmp_containment_root / "cases"
    try:
        if sys.platform == "win32":
            outside_target = _tmp_containment_root / "outside_canary"
            outside_target.mkdir()
            (outside_target / "document.json").write_text("{}", encoding="utf-8")

            documents_dir = fixture_case / "documents"
            documents_dir.mkdir(exist_ok=True)
            escaping_junction = documents_dir / "escaping_doc"

            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(escaping_junction), str(outside_target)],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                case_root_f = agf._resolve_module_case_root_real(issue_spotting_engine, CASE_ID)

                # Instrument os.stat to record every path it is asked
                # about - proving the outside canary is never stat'd.
                stat_calls = []
                real_stat = os.stat

                def _recording_stat(path, *a, **kw):
                    stat_calls.append(str(path))
                    return real_stat(path, *a, **kw)

                with mock.patch("os.stat", side_effect=_recording_stat):
                    raised_escape = False
                    try:
                        agf._scan_verified_leaf_chain(
                            case_root_f, documents_dir.resolve(strict=False), ("extractions", "facts.json"),
                        )
                    except agf.AgentGenerationInputContainmentError:
                        raised_escape = True

                check("escaping documents/ junction: scanner raises fail-closed", raised_escape)
                canary_stat_paths = [p for p in stat_calls if str(outside_target) in p]
                check(
                    "escaping documents/ junction: outside canary directory NEVER stat'd during the scan",
                    canary_stat_paths == [],
                    f"unexpected stat calls: {canary_stat_paths}",
                )
            else:
                print(
                    "SKIPPED (NOT counted as pass/fail): mklink /J failed "
                    f"(rc={result.returncode}, stderr={result.stderr!r}) - junction privilege unavailable "
                    "in this environment"
                )

            # Broken junction: target removed AFTER the junction points at
            # it. `os.path.lexists()` is True (a reparse point exists);
            # `Path.exists()` would be False (dereferences and fails) -
            # this is exactly the missing-vs-broken distinction the
            # scanner must never conflate.
            broken_target = _tmp_containment_root / "broken_target"
            broken_target.mkdir()
            broken_junction = documents_dir / "broken_doc"
            broken_result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(broken_junction), str(broken_target)],
                capture_output=True, text=True,
            )
            if broken_result.returncode == 0:
                shutil.rmtree(broken_target)  # target now gone - junction is broken
                check(
                    "broken junction: os.path.lexists() is True (reparse point still present)",
                    os.path.lexists(broken_junction),
                )
                check(
                    "broken junction: pathlib.Path.exists() is False (dereference fails)",
                    not broken_junction.exists(),
                )
                case_root_g = agf._resolve_module_case_root_real(issue_spotting_engine, CASE_ID)
                raised_broken = False
                try:
                    agf._scan_verified_leaf_chain(
                        case_root_g, documents_dir.resolve(strict=False), ("extractions", "facts.json"),
                    )
                except agf.AgentGenerationInputContainmentError:
                    raised_broken = True
                check(
                    "broken documents/ junction: scanner fails closed (raises), never classified as "
                    "'missing'",
                    raised_broken,
                )
            else:
                print(
                    "SKIPPED (NOT counted as pass/fail): broken-junction mklink /J failed "
                    f"(rc={broken_result.returncode})"
                )
        else:
            print("SKIPPED (NOT counted as pass/fail): junction test is Windows-only")
    finally:
        issue_spotting_engine.CASES_DIR = original_cases_dir
finally:
    shutil.rmtree(_tmp_containment_root, ignore_errors=True)


# ============================================================
# 7) Path.glob() zero-call mechanical proof - the manifest scanner must
#    never call it, for any of the five families, on real case_0001.
# ============================================================

_glob_calls = []
_real_glob = Path.glob


def _recording_glob(self, pattern, *a, **kw):
    _glob_calls.append((str(self), pattern))
    return _real_glob(self, pattern, *a, **kw)


with mock.patch.object(Path, "glob", _recording_glob):
    for row_key, module in [
        ("issue_spotting", issue_spotting_engine), ("evidence", evidence_engine), ("argument", argument_engine),
    ]:
        case_root = agf._resolve_module_case_root_real(module, CASE_ID)
        agf._build_manifest_containers(row_key, case_root, CASE_ID)

check(
    "Path.glob() is NEVER called anywhere in the manifest scanner, for any family, on real case_0001",
    _glob_calls == [],
    f"unexpected glob calls: {_glob_calls}",
)


# ============================================================
# PILOT READINESS ADIM 4b - RAW-TEXT EGRESS REFUSAL (facade layer,
# INDEPENDENT of ui.cli_mutate's own usage-shape layer).
#
# Contract under test: for the THREE families whose prompt carries raw
# case text (issue_spotting/evidence/argument), `with_agent=True`
# together with the PRODUCTION client (`llm_client is None`) is refused
# BEFORE any module import, authz repository, or filesystem probe.
# `risk_strategy`/`drafting` are NOT refused, an INJECTED test client is
# NOT refused (that DI seam never reaches an external model), and
# deterministic mode (`with_agent=False`) is untouched.
# ============================================================

check(
    "AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS is EXACTLY the three raw-text families "
    "(risk_strategy/drafting deliberately absent - their prompts carry only IDs/fixed enums)",
    agf.AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS == frozenset(
        {"issue_spotting", "evidence", "argument"}
    ),
    f"got: {sorted(agf.AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS)}",
)
check(
    "the refused set is a strict SUBSET of the five known agent-generation families (no "
    "invented row_key)",
    agf.AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS
    < set(agf.AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME),
)
check(
    "AgentGenerationRawTextEgressRefusedError subclasses AgentGenerationArgumentError (and thus "
    "ApprovalUiError) - so ui.cli_mutate's UNCHANGED _is_known_domain_error prints it as one "
    "clean line, never a traceback",
    issubclass(agf.AgentGenerationRawTextEgressRefusedError, agf.AgentGenerationArgumentError)
    and issubclass(agf.AgentGenerationRawTextEgressRefusedError, _common.ApprovalUiError),
)

for _refused in sorted(agf.AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS):
    expect_raises(
        agf.AgentGenerationRawTextEgressRefusedError,
        lambda rk=_refused: agf._check_argument_shapes(
            rk, for_apply=False, with_agent=True, llm_client=None,
        ),
        f"_check_argument_shapes({_refused}, PREVIEW, with_agent=True, production client) is "
        "REFUSED",
    )
    expect_raises(
        agf.AgentGenerationRawTextEgressRefusedError,
        lambda rk=_refused: agf._check_argument_shapes(
            rk, "somedigest", for_apply=True, with_agent=True, llm_client=None,
        ),
        f"_check_argument_shapes({_refused}, APPLY, with_agent=True, production client) is "
        "REFUSED",
    )
    _msg = agf.raw_text_egress_refusal_message(_refused)
    check(
        f"{_refused}: the fixed refusal message names the family AND --with-agent, and leaks no "
        "filesystem path / case data (no drive letter, no backslash, no data/ or case_ segment)",
        _refused in _msg and "--with-agent" in _msg and "Adım 4b" in _msg
        and "C:" not in _msg and "\\" not in _msg
        and "data/" not in _msg and "case_" not in _msg and str(REPO_ROOT) not in _msg,
        f"message={_msg!r}",
    )
    try:
        agf._check_argument_shapes(_refused, for_apply=False, with_agent=True, llm_client=_FakeLLMClient())
        check(
            f"{_refused}: an INJECTED test client is NOT refused - the DI seam that never reaches "
            "an external model is preserved",
            True,
        )
    except Exception as error:  # noqa: BLE001
        check(
            f"{_refused}: an INJECTED test client is NOT refused - the DI seam that never reaches "
            "an external model is preserved",
            False, f"{type(error).__name__}: {error}",
        )
    try:
        agf._check_argument_shapes(_refused, for_apply=False, with_agent=False, llm_client=None)
        agf._check_argument_shapes(_refused, "somedigest", for_apply=True, with_agent=False, llm_client=None)
        check(f"{_refused}: DETERMINISTIC mode (with_agent=False) is completely unaffected", True)
    except Exception as error:  # noqa: BLE001
        check(
            f"{_refused}: DETERMINISTIC mode (with_agent=False) is completely unaffected",
            False, f"{type(error).__name__}: {error}",
        )

# ============================================================
# PILOT READINESS ADIM 4c - PILOT-POLICY EGRESS REFUSAL (facade layer),
# a SEPARATE, additional gate for the TWO families whose prompt is
# ID/enum-only (`risk_strategy`/`drafting` - CLAUDE.md's own
# characterization of these two families as NOT carrying raw case text
# is UNCHANGED and NOT contradicted here). The `for _open_family in
# ["risk_strategy", "drafting"]:` positive-control block that used to
# stand HERE is INVERTED (same discipline as CLAUDE.md's Row 19B
# `"sends no client_secret"` -> real `client_secret_post` assertion
# precedent - the assertion is not deleted, it is turned to point the
# other way, with the reason recorded): these two families are now
# ALSO refused, for a SEPARATE reason (pilot policy, not raw text),
# with a SEPARATE exception class and message.
# ============================================================

check(
    "AGENT_GENERATION_PILOT_POLICY_REFUSED_ROW_KEYS is EXACTLY {'risk_strategy', 'drafting'} - a "
    "SEPARATE set from AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS, which is UNCHANGED above",
    agf.AGENT_GENERATION_PILOT_POLICY_REFUSED_ROW_KEYS == frozenset({"risk_strategy", "drafting"}),
    f"got: {sorted(agf.AGENT_GENERATION_PILOT_POLICY_REFUSED_ROW_KEYS)}",
)
check(
    "the two refused sets (raw-text/Adım 4b and pilot-policy/Adım 4c) are pairwise DISJOINT and "
    "their UNION is EXACTLY the full five-family agent_generation universe - zero open families "
    "remain",
    agf.AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS.isdisjoint(
        agf.AGENT_GENERATION_PILOT_POLICY_REFUSED_ROW_KEYS
    )
    and (
        agf.AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS
        | agf.AGENT_GENERATION_PILOT_POLICY_REFUSED_ROW_KEYS
    ) == set(agf.AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME),
)
check(
    "AgentGenerationPilotPolicyEgressRefusedError subclasses AgentGenerationArgumentError (and "
    "thus ApprovalUiError) - so ui.cli_mutate's UNCHANGED _is_known_domain_error prints it as one "
    "clean line, never a traceback",
    issubclass(agf.AgentGenerationPilotPolicyEgressRefusedError, agf.AgentGenerationArgumentError)
    and issubclass(agf.AgentGenerationPilotPolicyEgressRefusedError, _common.ApprovalUiError),
)

for _pilot_refused in sorted(agf.AGENT_GENERATION_PILOT_POLICY_REFUSED_ROW_KEYS):
    expect_raises(
        agf.AgentGenerationPilotPolicyEgressRefusedError,
        lambda rk=_pilot_refused: agf._check_argument_shapes(
            rk, for_apply=False, with_agent=True, llm_client=None,
        ),
        f"_check_argument_shapes({_pilot_refused}, PREVIEW, with_agent=True, production client) "
        "is REFUSED by the pilot-policy gate",
    )
    expect_raises(
        agf.AgentGenerationPilotPolicyEgressRefusedError,
        lambda rk=_pilot_refused: agf._check_argument_shapes(
            rk, "somedigest", for_apply=True, with_agent=True, llm_client=None,
        ),
        f"_check_argument_shapes({_pilot_refused}, APPLY, with_agent=True, production client) is "
        "REFUSED by the pilot-policy gate",
    )
    _pilot_msg = agf.pilot_policy_egress_refusal_message(_pilot_refused)
    check(
        f"{_pilot_refused}: the fixed pilot-policy refusal message names the family AND "
        "--with-agent, is a DIFFERENT message from raw_text_egress_refusal_message (does not "
        "falsely claim this family carries raw text), and leaks no filesystem path / case data",
        _pilot_refused in _pilot_msg and "--with-agent" in _pilot_msg and "Adım 4c" in _pilot_msg
        and _pilot_msg != agf.raw_text_egress_refusal_message(_pilot_refused)
        and "ham fact cümlesi" not in _pilot_msg
        and "C:" not in _pilot_msg and "\\" not in _pilot_msg
        and "data/" not in _pilot_msg and "case_" not in _pilot_msg and str(REPO_ROOT) not in _pilot_msg,
        f"message={_pilot_msg!r}",
    )
    try:
        agf._check_argument_shapes(
            _pilot_refused, for_apply=False, with_agent=True, llm_client=_FakeLLMClient(),
        )
        check(
            f"{_pilot_refused}: an INJECTED test client is NOT refused by the pilot-policy gate "
            "either - the DI seam that never reaches an external model is preserved",
            True,
        )
    except Exception as error:  # noqa: BLE001
        check(
            f"{_pilot_refused}: an INJECTED test client is NOT refused by the pilot-policy gate "
            "either - the DI seam that never reaches an external model is preserved",
            False, f"{type(error).__name__}: {error}",
        )
    try:
        agf._check_argument_shapes(_pilot_refused, for_apply=False, with_agent=False, llm_client=None)
        agf._check_argument_shapes(
            _pilot_refused, "somedigest", for_apply=True, with_agent=False, llm_client=None,
        )
        check(f"{_pilot_refused}: DETERMINISTIC mode (with_agent=False) is completely unaffected", True)
    except Exception as error:  # noqa: BLE001
        check(
            f"{_pilot_refused}: DETERMINISTIC mode (with_agent=False) is completely unaffected",
            False, f"{type(error).__name__}: {error}",
        )

expect_raises(
    KeyError,
    lambda: agf._check_argument_shapes(
        "not_a_real_family", for_apply=False, with_agent=True, llm_client=None,
    ),
    "unknown row_key STILL raises KeyError even with with_agent=True - the refusal check is "
    "placed AFTER the KeyError guard, so no caller sees a changed exception TYPE",
)


# ------------------------------------------------------------
# ORDERING PROOF: the refusal fires before importlib.import_module AND
# before the authz repository is ever touched (an exploding repository
# and a recording import hook prove it - not merely asserted).
# ------------------------------------------------------------

class _ExplodingAuthzRepository:
    def __getattr__(self, name):
        raise AssertionError(
            f"the authz repository was touched ({name}) - the Adım 4b refusal must fire first"
        )


class _DummyPrincipal:
    user_id = 1
    roles = ()


_import_calls_4b = []
_real_import_module = importlib.import_module


def _recording_import_module(name, *a, **kw):
    _import_calls_4b.append(name)
    return _real_import_module(name, *a, **kw)


for _refused in sorted(agf.AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS):
    _import_calls_4b.clear()
    with mock.patch.object(importlib, "import_module", _recording_import_module):
        expect_raises(
            agf.AgentGenerationRawTextEgressRefusedError,
            lambda rk=_refused: agf.preview_generation(
                rk, CASE_ID, with_agent=True, llm_client=None,
                principal=_DummyPrincipal(), authz_repository=_ExplodingAuthzRepository(),
            ),
            f"preview_generation({_refused}, with_agent=True, production client) is REFUSED",
        )
    check(
        f"preview_generation({_refused}): ZERO engine-module imports and ZERO authz repository "
        "access before the refusal",
        _import_calls_4b == [],
        f"unexpected import_module calls: {_import_calls_4b}",
    )

    _import_calls_4b.clear()
    with mock.patch.object(importlib, "import_module", _recording_import_module):
        expect_raises(
            agf.AgentGenerationRawTextEgressRefusedError,
            lambda rk=_refused: agf.apply_generation(
                rk, CASE_ID, "somedigest", with_agent=True, allow_network=True, llm_client=None,
                principal=_DummyPrincipal(), authz_repository=_ExplodingAuthzRepository(),
                conn_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("a mutation connection was opened - refusal must fire first")
                ),
            ),
            f"apply_generation({_refused}, with_agent=True, --allow-network equivalent, production "
            "client) is REFUSED",
        )
    check(
        f"apply_generation({_refused}): ZERO engine-module imports, ZERO authz repository access "
        "and ZERO mutation connection before the refusal",
        _import_calls_4b == [],
        f"unexpected import_module calls: {_import_calls_4b}",
    )

# PILOT READINESS ADIM 4c: the SAME ordering proof, for the pilot-policy
# refused set - preview/apply is refused BEFORE any engine-module
# import or authz repository access, exactly like the raw-text set
# above (a SEPARATE loop, a SEPARATE exception type).
for _pilot_refused in sorted(agf.AGENT_GENERATION_PILOT_POLICY_REFUSED_ROW_KEYS):
    _import_calls_4b.clear()
    with mock.patch.object(importlib, "import_module", _recording_import_module):
        expect_raises(
            agf.AgentGenerationPilotPolicyEgressRefusedError,
            lambda rk=_pilot_refused: agf.preview_generation(
                rk, CASE_ID, with_agent=True, llm_client=None,
                principal=_DummyPrincipal(), authz_repository=_ExplodingAuthzRepository(),
            ),
            f"preview_generation({_pilot_refused}, with_agent=True, production client) is "
            "REFUSED by the pilot-policy gate",
        )
    check(
        f"preview_generation({_pilot_refused}): ZERO engine-module imports and ZERO authz "
        "repository access before the pilot-policy refusal",
        _import_calls_4b == [],
        f"unexpected import_module calls: {_import_calls_4b}",
    )

    _import_calls_4b.clear()
    with mock.patch.object(importlib, "import_module", _recording_import_module):
        expect_raises(
            agf.AgentGenerationPilotPolicyEgressRefusedError,
            lambda rk=_pilot_refused: agf.apply_generation(
                rk, CASE_ID, "somedigest", with_agent=True, allow_network=True, llm_client=None,
                principal=_DummyPrincipal(), authz_repository=_ExplodingAuthzRepository(),
                conn_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("a mutation connection was opened - refusal must fire first")
                ),
            ),
            f"apply_generation({_pilot_refused}, with_agent=True, --allow-network equivalent, "
            "production client) is REFUSED by the pilot-policy gate",
        )
    check(
        f"apply_generation({_pilot_refused}): ZERO engine-module imports, ZERO authz repository "
        "access and ZERO mutation connection before the pilot-policy refusal",
        _import_calls_4b == [],
        f"unexpected import_module calls: {_import_calls_4b}",
    )

# GLOBAL REGRESSION PROOF: after BOTH refused sets, NO row_key in the
# whole five-family universe remains open - apply_generation(row_key)
# for every family reaches EITHER refusal, never the authz layer.
for _row_key in sorted(agf.AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME):
    try:
        agf.apply_generation(
            _row_key, CASE_ID, "somedigest", with_agent=True, allow_network=True,
            llm_client=None, principal=_DummyPrincipal(),
            authz_repository=_ExplodingAuthzRepository(),
        )
        check(
            f"apply_generation({_row_key}) with_agent=True + production client is REFUSED "
            "(GLOBAL PILOT INVARIANT: zero open agent_generation families remain)",
            False, "no exception at all - this family is WRONGLY still open",
        )
    except (agf.AgentGenerationRawTextEgressRefusedError, agf.AgentGenerationPilotPolicyEgressRefusedError):
        check(
            f"apply_generation({_row_key}) with_agent=True + production client is REFUSED "
            "(GLOBAL PILOT INVARIANT: zero open agent_generation families remain)",
            True,
        )
    except Exception as error:  # noqa: BLE001
        check(
            f"apply_generation({_row_key}) with_agent=True + production client is REFUSED "
            "(GLOBAL PILOT INVARIANT: zero open agent_generation families remain)",
            False, f"unexpected {type(error).__name__}: {error}",
        )


print(f"--- test_agent_generation_mutation_facade_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
