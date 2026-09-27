# ============================================================
# PHASE B (COMMIT A) - ui/services/qa_case_view_generation_mutation_
# facade.py + _adapters.py + the portable QA locator: ISOLATED TESTS.
#
# Pure-Python, no PostgreSQL, no mutation coordinator connection.
# Exercises:
#   1) row-key / action-family / target-ref / count constants and the
#      facade<->adapter version canaries
#   2) usage-shape validation (agent mode refused unconditionally; the
#      pilot `--with-agent` egress universe is NOT widened)
#   3) the portable QA locator (`qa_discovery.canonical_locator_under` /
#      `qa_artifact_locator`): identical text across TWO worktree roots,
#      absent artefacts allowed, fail-closed on absolute/drive/UNC/`..`/
#      outside-root/junction-escape, no basename guess
#   4) approval-audit locator anchoring (option b): family-dir anchored
#      text == CASES_DIR-relative text in the production layout, and
#      still the canonical logical text when a self-test redirects the
#      family dir (the qa_review self-test pattern)
#   5) writer/adapter end-to-end on a tempdir copy of case_0001 WITHOUT
#      PostgreSQL: identity manifest (12/11 containers), first write,
#      second write with a repo-relative history_backup_path, adapter
#      full binding + tamper matrix, canonical-mutation guard, partial-
#      binding refusal, rollback on failure, real Layer A run_approve
#      (legacy path) producing repo-relative audit locators, pending-name
#      parity with the approval modules, case_view prerequisite refusals
#      (missing / stale canonical qa.json), aborted/incomplete builder
#      refusals, preview through the facade with an in-memory authz repo,
#      and apply refusals that fire BEFORE any connection factory call
#   6) deterministic same-second history-name collision regression (F1
#      remediation): each engine's REAL `datetime` binding frozen to ONE
#      instant, three `preserve_previous_pending` moves of the same pending
#      must yield EXACTLY <base>, <base>_1, <base>_2 with every original
#      byte preserved - independent of the wall clock, qa_engine and
#      orchestrator_engine asserted SEPARATELY
#   7) production data/ byte-invariance
#
# Run: python -m ui.tests.test_qa_case_view_generation_mutation_facade_isolated
# ============================================================

import datetime as _dt_module
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import path_containment                                                  # noqa: E402
import qa_discovery                                                      # noqa: E402
import qa_engine                                                         # noqa: E402
import qa_validator                                                      # noqa: E402
import qa_approval                                                       # noqa: E402
import orchestrator_discovery                                            # noqa: E402,F401
import orchestrator_engine                                               # noqa: E402
import orchestrator_validator                                            # noqa: E402,F401
import orchestrator_approval                                             # noqa: E402
from ui.services import paths as _paths                                  # noqa: E402
from ui.services import authz as _authz                                  # noqa: E402
from ui.services import common as _common                                # noqa: E402
from ui.services import qa_case_view_generation_mutation_facade as qcvf  # noqa: E402
from ui.services import qa_case_view_generation_mutation_adapters as qcva  # noqa: E402
from ui.services import agent_generation_mutation_facade as _agf         # noqa: E402
from ui.services import fact_extraction_mutation_facade as _fef          # noqa: E402
from ui.services import legal_research_case_law_mutation_facade as _lrclf  # noqa: E402

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


def snapshot_tree(root):
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def dir_snapshot(directory):
    """`{name: sha256}` for the regular files DIRECTLY in `directory` (empty
    when the directory does not exist). Used for RELATIVE before/after deltas
    on append-only provenance dirs, so no test hard-codes an absolute count."""
    if not directory.is_dir():
        return {}
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir()) if p.is_file()
    }


def kept_entries(directory, baseline):
    """The subset of `dir_snapshot(directory)` whose names are in `baseline` -
    compare against `baseline` to prove nothing pre-existing was overwritten."""
    return {n: s for n, s in dir_snapshot(directory).items() if n in baseline}


def new_entries(directory, baseline):
    """Sorted names that appeared in `directory` after `baseline` was taken."""
    return sorted(set(dir_snapshot(directory)) - set(baseline))


REAL_DATA_DIR = REPO_ROOT / "data"
REAL_CASE_0001 = REAL_DATA_DIR / "cases" / "case_0001"
_real_data_before = snapshot_tree(REAL_DATA_DIR)
_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))

IS_WINDOWS = sys.platform == "win32"


def make_junction(link: Path, target: Path) -> bool:
    """Real NTFS junction (no elevation needed). Returns False if the
    platform/tooling cannot create one (then the caller SKIPs, never PASSes)."""
    if not IS_WINDOWS:
        return False
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and os.path.lexists(link)


# ============================================================
# 1) Constants / helpers / canaries - pure, no I/O.
# ============================================================

check(
    "row-key map is exactly {'qa': 'qa_engine', 'case_view': 'orchestrator_engine'}",
    qcvf.QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME == {"qa": "qa_engine", "case_view": "orchestrator_engine"},
)
check(
    "action families / target refs are exactly generation.qa|case_view and qa|case_view.pending",
    qcvf.qa_case_view_generation_action_family_for("qa") == "generation.qa"
    and qcvf.qa_case_view_generation_action_family_for("case_view") == "generation.case_view"
    and qcvf.qa_case_view_generation_target_ref_for("qa") == "qa.pending"
    and qcvf.qa_case_view_generation_target_ref_for("case_view") == "case_view.pending",
)
check(
    "target refs equal the engines' OWN get_target_ref() (writer audit and journal agree)",
    qa_engine.get_target_ref() == "qa.pending" and orchestrator_engine.get_target_ref() == "case_view.pending"
    and qa_engine.GENERATION_ACTION_FAMILY == "generation.qa"
    and orchestrator_engine.GENERATION_ACTION_FAMILY == "generation.case_view"
    and qa_engine.GENERATION_CHANNEL == orchestrator_engine.GENERATION_CHANNEL == qcvf.CHANNEL,
)
check(
    "FAMILY_LOGICAL_NAME_COUNTS is exactly qa=12 / case_view=11",
    qcvf.FAMILY_LOGICAL_NAME_COUNTS == {"qa": 12, "case_view": 11},
    f"got {qcvf.FAMILY_LOGICAL_NAME_COUNTS}",
)
check(
    "qa manifest names == 3 multi/single case-level inputs + the 9 single-file QA scopes; case_view "
    "manifest names == case + the 9 scopes + canonical qa",
    {n for n, _k, _e in qcvf.FAMILY_INPUT_SPECS["qa"]}
    == {"case", "documents", "facts"} | set(qa_discovery.SINGLE_FILE_SCOPE_PATHS)
    and {n for n, _k, _e in qcvf.FAMILY_INPUT_SPECS["case_view"]}
    == {"case", "qa"} | set(qa_discovery.SINGLE_FILE_SCOPE_PATHS),
)
check(
    "deterministic-only provenance sentinels (same literals as the agent facade's deterministic mode)",
    qcvf.GENERATION_MODE == "deterministic" and qcvf.MODEL_ID == "deterministic_no_model"
    and qcvf.PROMPT_AGENT_VERSION == "n/a",
)
check(
    "facade<->adapter version canaries: _MANIFEST_VERSION / _SNAPSHOT_VERSION are byte-identical and "
    "DISTINCT from every other generation facade's literals",
    qcvf._MANIFEST_VERSION == qcva._MANIFEST_VERSION == "phaseb.qa_case_view_generation.v1"
    and qcvf._SNAPSHOT_VERSION == qcva._SNAPSHOT_VERSION == "phaseb.qa_case_view_generation.snapshot.v1"
    and qcvf._MANIFEST_VERSION != qcvf._SNAPSHOT_VERSION
    and qcvf._MANIFEST_VERSION != _agf._MANIFEST_VERSION and qcvf._SNAPSHOT_VERSION != _agf._SNAPSHOT_VERSION,
)
check(
    "adapter imports ONLY constant/format helpers from the facade (no decision function shared)",
    not any(
        name in vars(qcva) for name in (
            "_check_argument_shapes", "_build_manifest_containers", "_derive_identity",
            "_verify_completed_replay_binding", "_audit_record_matches_base", "_scan_single_file",
        )
    ),
)
check(
    "the adapter's own _audit_record_matches / _verify_history_backup_binding are its own objects, "
    "not re-exported from the facade",
    qcva._audit_record_matches.__module__ == qcva.__name__
    and qcva._verify_history_backup_binding.__module__ == qcva.__name__
    and qcva._scan_generation_audits is not qcvf._scan_generation_audits,
)


# ============================================================
# 2) Usage-shape validation + egress-universe non-expansion.
# ============================================================

expect_raises(KeyError, lambda: qcvf._check_argument_shapes("bogus", for_apply=False), "unknown row_key -> KeyError")
for rk in ("qa", "case_view"):
    expect_raises(
        qcvf.QaCaseViewGenerationAgentModeRefusedError,
        lambda rk=rk: qcvf._check_argument_shapes(rk, for_apply=False, with_agent=True),
        f"{rk}: with_agent on PREVIEW -> QaCaseViewGenerationAgentModeRefusedError",
    )
    expect_raises(
        qcvf.QaCaseViewGenerationAgentModeRefusedError,
        lambda rk=rk: qcvf._check_argument_shapes(rk, "d", for_apply=True, with_agent=True, allow_network=True),
        f"{rk}: with_agent+allow_network on APPLY -> refused",
    )
    expect_raises(
        qcvf.QaCaseViewGenerationAgentModeRefusedError,
        lambda rk=rk: qcvf._check_argument_shapes(rk, for_apply=False, allow_network=True),
        f"{rk}: allow_network ALONE -> refused (no agent mode exists to require)",
    )
    expect_raises(
        qcvf.QaCaseViewGenerationArgumentError,
        lambda rk=rk: qcvf._check_argument_shapes(rk, None, for_apply=True),
        f"{rk}: apply without expected_input_digest -> QaCaseViewGenerationArgumentError",
    )
    expect_raises(
        qcvf.QaCaseViewGenerationArgumentError,
        lambda rk=rk: qcvf._check_argument_shapes(rk, "   ", for_apply=True),
        f"{rk}: apply with blank expected_input_digest -> QaCaseViewGenerationArgumentError",
    )
    try:
        qcvf._check_argument_shapes(rk, "d", for_apply=True)
        check(f"{rk}: apply WITH expected_input_digest and no agent flags passes", True)
    except Exception as error:  # noqa: BLE001
        check(f"{rk}: apply WITH expected_input_digest and no agent flags passes", False, str(error))
    check(
        f"{rk}: the refusal message is fixed text naming the row-key and carries no filesystem path",
        rk in qcvf.agent_mode_refusal_message(rk) and "Phase B" in qcvf.agent_mode_refusal_message(rk)
        and "\\" not in qcvf.agent_mode_refusal_message(rk)
        and "data/cases" not in qcvf.agent_mode_refusal_message(rk)
        and str(REPO_ROOT) not in qcvf.agent_mode_refusal_message(rk),
    )
check(
    "the refusal error is an ApprovalUiError (ui.cli_mutate's unchanged domain-error recognition)",
    issubclass(qcvf.QaCaseViewGenerationAgentModeRefusedError, _common.ApprovalUiError)
    and issubclass(qcvf.CaseViewQaPrerequisiteError, _common.ApprovalUiError)
    and issubclass(qcvf.QaGenerationAbortedError, _common.ApprovalUiError)
    and issubclass(qcvf.CaseViewGenerationIncompleteError, _common.ApprovalUiError),
)
check(
    "EGRESS UNIVERSE NOT WIDENED: qa/case_view are absent from all three --with-agent-capable "
    "facades' row-key namespaces (agent_generation 5 + legal_research/case_law 2 + fact_extraction 1 "
    "= 8 stays 8)",
    not ({"qa", "case_view"} & (
        set(_agf.AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME) | set(_lrclf.LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME)
        | set(_fef.FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME)
    ))
    and len(
        set(_agf.AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME) | set(_lrclf.LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME)
        | set(_fef.FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME)
    ) == 8,
)
check(
    "the facade has NO llm_client DI seam at all (neither preview nor apply accepts one)",
    "llm_client" not in inspect.signature(qcvf.preview_generation).parameters
    and "llm_client" not in inspect.signature(qcvf.apply_generation).parameters,
)
check(
    "the facade module never references anthropic/openai/requests/httpx or any *_agent module",
    not any(
        token in Path(qcvf.__file__).read_text(encoding="utf-8")
        for token in ("anthropic", "openai", "import requests", "httpx", "_agent\"", "qa_agent")
    ),
)


# ============================================================
# 3) Portable QA locator - two worktree roots, fail-closed shapes.
# ============================================================

_orig_qa_discovery_cases_dir = qa_discovery.CASES_DIR
try:
    root_a = Path(tempfile.mkdtemp(prefix="qacv_rootA_"))
    root_b = Path(tempfile.mkdtemp(prefix="qacv_rootB_"))
    texts = []
    for root in (root_a, root_b):
        cases = root / "data" / "cases"
        (cases / "case_x" / "timeline").mkdir(parents=True)
        (cases / "case_x" / "timeline" / "timeline.json").write_text("{}", encoding="utf-8")
        qa_discovery.CASES_DIR = cases
        texts.append((
            qa_discovery.qa_artifact_locator(cases / "case_x" / "timeline" / "timeline.json"),
            qa_discovery.qa_artifact_locator(cases / "case_x" / "evidence" / "evidence.json"),  # absent
            qa_discovery.qa_artifact_locator(None),
        ))
    check(
        "TWO-ROOT DETERMINISM: the locator text is byte-identical across two different worktree roots "
        "(present artefact, absent artefact, None)",
        texts[0] == texts[1]
        and texts[0][0] == "data/cases/case_x/timeline/timeline.json"
        and texts[0][1] == "data/cases/case_x/evidence/evidence.json"
        and texts[0][2] is None,
        f"got {texts}",
    )
    qa_discovery.CASES_DIR = root_a / "data" / "cases"
    cases_a = qa_discovery.CASES_DIR
    expect_raises(
        qa_discovery.QaLocatorError, lambda: qa_discovery.qa_artifact_locator(root_b / "data" / "cases" / "case_x" / "timeline" / "timeline.json"),
        "a path under a DIFFERENT root is refused (no basename guess, no silent fallback)",
    )
    expect_raises(
        qa_discovery.QaLocatorError, lambda: qa_discovery.qa_artifact_locator(cases_a / "case_x" / ".." / ".." / "secret.json"),
        "a `..` traversal is refused",
    )
    expect_raises(
        qa_discovery.QaLocatorError, lambda: qa_discovery.qa_artifact_locator(cases_a),
        "the anchor root itself is refused",
    )
    expect_raises(
        qa_discovery.QaLocatorError, lambda: qa_discovery.qa_artifact_locator(Path(str(cases_a) + "_sibling") / "x.json"),
        "a sibling directory sharing the root's prefix is refused",
    )
    expect_raises(
        qa_discovery.QaLocatorError,
        lambda: qa_discovery.canonical_locator_under(cases_a / "case_x" / "D:evil.json", anchor_root=cases_a),
        "a drive-relative segment inside the path is refused (Windows re-anchoring class)",
    )
    expect_raises(
        qa_discovery.QaLocatorError, lambda: qa_discovery.qa_artifact_locator("\\\\server\\share\\case_x\\x.json"),
        "a UNC path is refused",
    )
    expect_raises(
        qa_discovery.QaLocatorError, lambda: qa_discovery.qa_artifact_locator("case_x/timeline/timeline.json"),
        "a bare relative string (not under the anchor) is refused - locators are derived, never guessed",
    )
    expect_raises(
        qa_discovery.QaLocatorError,
        lambda: qa_discovery.canonical_locator_under(cases_a / "case_x" / "x.json", anchor_root=cases_a, logical_prefix_parts=("..",)),
        "a `..` logical prefix segment is refused",
    )
    (cases_a / "case_x" / "qa").mkdir()  # the family dir exists whenever an approval audit is written
    check(
        "canonical_locator_under with logical prefix parts produces the canonical layout text "
        "(family-dir anchoring for approval audits; the artefact itself may still be absent)",
        qa_discovery.canonical_locator_under(
            cases_a / "case_x" / "qa" / "qa.json", anchor_root=cases_a / "case_x" / "qa", logical_prefix_parts=("case_x", "qa"),
        ) == "data/cases/case_x/qa/qa.json",
    )
    expect_raises(
        qa_discovery.QaLocatorError,
        lambda: qa_discovery.canonical_locator_under(
            cases_a / "case_x" / "missing_family" / "x.json", anchor_root=cases_a / "case_x" / "missing_family",
            logical_prefix_parts=("case_x", "missing_family"),
        ),
        "a NON-EXISTENT anchor root is refused (strict root resolution - never silently accepted)",
    )
    # Junction escape (real NTFS junction) - refused even though the link lives INSIDE the root.
    outside = root_b / "outside_target"
    outside.mkdir()
    (outside / "leak.json").write_text("{}", encoding="utf-8")
    link = cases_a / "case_x" / "escape"
    if make_junction(link, outside):
        expect_raises(
            qa_discovery.QaLocatorError, lambda: qa_discovery.qa_artifact_locator(link / "leak.json"),
            "a REAL NTFS junction inside the case dir that escapes the root is refused (existing artefact)",
        )
        expect_raises(
            qa_discovery.QaLocatorError, lambda: qa_discovery.qa_artifact_locator(link / "absent.json"),
            "an ABSENT artefact under an escaping junction is refused (absent tail does not bypass containment)",
        )
        os.rmdir(link)
    else:
        print("SKIPPED junction-escape locator checks (no junction tooling on this platform) - NOT counted as pass/fail")
finally:
    qa_discovery.CASES_DIR = _orig_qa_discovery_cases_dir
    shutil.rmtree(root_a, ignore_errors=True)
    shutil.rmtree(root_b, ignore_errors=True)


# ============================================================
# 4) Approval-audit locator anchoring (option b) - parity.
# ============================================================

for module, family_dir, getter in ((qa_approval, "qa", "get_qa_dir"), (orchestrator_approval, "case_view", "get_view_dir")):
    cid = "case_0001"
    fam_dir = getattr(module, getter)(cid)
    pending = module.get_pending_path(cid)
    via_family = qa_discovery.canonical_locator_under(pending, anchor_root=fam_dir, logical_prefix_parts=(cid, family_dir))
    via_cases = qa_discovery.canonical_locator_under(pending, anchor_root=module.CASES_DIR)
    check(
        f"{module.__name__}: family-dir anchored audit locator == CASES_DIR-relative locator in the "
        "production layout",
        via_family == via_cases == f"data/cases/{cid}/{family_dir}/{pending.name}",
        f"family={via_family!r} cases={via_cases!r}",
    )
    # qa_review self-test pattern: the family dir is redirected to a tempdir - the audit still
    # records the canonical LOGICAL location (never the physical temp path).
    tmp_family = Path(tempfile.mkdtemp(prefix="qacv_fam_"))
    try:
        redirected = qa_discovery.canonical_locator_under(
            tmp_family / pending.name, anchor_root=tmp_family, logical_prefix_parts=(cid, family_dir),
        )
        check(
            f"{module.__name__}: with the family dir redirected to a tempdir the audit locator is STILL "
            "the canonical logical text (no temp/user-dir path leaks into the audit)",
            redirected == f"data/cases/{cid}/{family_dir}/{pending.name}" and str(tmp_family) not in redirected,
        )
    finally:
        shutil.rmtree(tmp_family, ignore_errors=True)
check(
    "PENDING-NAME PARITY: engine get_pending_path == approval get_pending_path for both families",
    qa_engine.get_pending_path("case_0001") == qa_approval.get_pending_path("case_0001")
    and orchestrator_engine.get_pending_path("case_0001") == orchestrator_approval.get_pending_path("case_0001")
    and qa_engine.get_canonical_path("case_0001") == qa_approval.get_canonical_path("case_0001")
    and orchestrator_engine.get_canonical_path("case_0001") == orchestrator_approval.get_canonical_path("case_0001"),
)


# ============================================================
# 5) Writer / adapter / approval end-to-end on a tempdir copy of
#    case_0001 (no PostgreSQL). Every CASES_DIR holder redirected; the two
#    BASE_DIR-derived case-root holders redirected too.
# ============================================================

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


_TMP_ROOT = Path(tempfile.mkdtemp(prefix="qacv_iso_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)
_holders = discover_cases_dir_holders()
check(
    "redirect sweep covers qa_discovery/qa_engine/qa_approval/orchestrator_discovery/orchestrator_engine/"
    "orchestrator_approval/ui.services.paths",
    {"qa_discovery", "qa_engine", "qa_approval", "orchestrator_discovery", "orchestrator_engine",
     "orchestrator_approval", "ui.services.paths"} <= {getattr(m, "__name__", "") for m in _holders},
    f"holders={sorted(getattr(m, '__name__', '?') for m in _holders)}",
)
for _m in _holders:
    _m.CASES_DIR = _TMP_CASES
_real_qv_base = qa_validator.BASE_DIR
_real_qa_base = qa_approval.BASE_DIR
qa_validator.BASE_DIR = _TMP_ROOT
qa_approval.BASE_DIR = _TMP_ROOT

CASE_ID = "case_0001"
CASE_DIR = _TMP_CASES / CASE_ID


class _ExplodingConnFactory:
    def __call__(self):
        raise AssertionError("conn_factory was called - this refusal must fire BEFORE any connection")


try:
    shutil.copytree(REAL_CASE_0001, CASE_DIR)
    (CASE_DIR / "qa" / f"qa_{CASE_ID}_v1.json.pending").unlink()
    (CASE_DIR / "case_view" / f"case_view_{CASE_ID}_v1.json.pending").unlink()
    canonical_qa = CASE_DIR / "qa" / "qa.json"
    canonical_cv = CASE_DIR / "case_view" / "case_view.json"
    canonical_qa_before = canonical_qa.read_bytes()
    canonical_cv_before = canonical_cv.read_bytes()

    # --- append-only provenance BASELINE (Commit B) ---------------------
    # The real case_0001 tree now carries the Commit B provenance directories
    # (history/, generation_reviews/) and the Commit B promotion audits, so the
    # copy carries them too. Every count below is therefore a RELATIVE delta
    # against these baselines - never an absolute total - and every pre-existing
    # entry must stay byte-identical (nothing overwritten).
    qa_history_before = dir_snapshot(CASE_DIR / "qa" / "history")
    qa_genrev_before = dir_snapshot(CASE_DIR / "qa" / "generation_reviews")
    qa_reviews_before = dir_snapshot(CASE_DIR / "qa" / "reviews")
    cv_history_before = dir_snapshot(CASE_DIR / "case_view" / "history")
    cv_genrev_before = dir_snapshot(CASE_DIR / "case_view" / "generation_reviews")
    cv_reviews_before = dir_snapshot(CASE_DIR / "case_view" / "reviews")
    check(
        "NON-VACUITY: the copied fixture carries the Commit B provenance set - a qa/ and case_view/ "
        "history backup, a generation audit in each generation_reviews/, and in each reviews/ BOTH the "
        "pre-Commit-B 20260904 promotion audit AND a Commit B (2026-09-2x) promotion audit. This suite "
        "cannot go green on a pre-Commit-B tree.",
        all(len(b) >= 1 for b in (qa_history_before, qa_genrev_before, cv_history_before, cv_genrev_before))
        and any("20260904_202837" in n for n in qa_reviews_before)
        and any("20260904_212319" in n for n in cv_reviews_before)
        and any(n.startswith("qa_case_0001_v1_20260927") or n.startswith("qa_case_0001_v1_20260928")
                or n.startswith("qa_case_0001_v1_20260929") for n in qa_reviews_before)
        and any(n.startswith("case_view_case_0001_v1_20260927") or n.startswith("case_view_case_0001_v1_20260928")
                or n.startswith("case_view_case_0001_v1_20260929") for n in cv_reviews_before),
        f"qa_history={sorted(qa_history_before)} qa_genrev={sorted(qa_genrev_before)} "
        f"qa_reviews={sorted(qa_reviews_before)} cv_history={sorted(cv_history_before)} "
        f"cv_genrev={sorted(cv_genrev_before)} cv_reviews={sorted(cv_reviews_before)}",
    )

    def _commit_b_audit(reviews_dir, baseline, prefix):
        """The Commit B (2026-09-2x) promotion audit already present in the
        copied fixture - i.e. one of the TRANSFERRED records, not one this
        suite generates."""
        hits = [n for n in sorted(baseline) if n.startswith(prefix)
                and any(f"_2026092{d}_" in n for d in "789")]
        return (reviews_dir / hits[0]) if hits else None

    for _fam, _reviews_dir, _baseline, _prefix in (
        ("qa", CASE_DIR / "qa" / "reviews", qa_reviews_before, "qa_case_0001_v1_"),
        ("case_view", CASE_DIR / "case_view" / "reviews", cv_reviews_before, "case_view_case_0001_v1_"),
    ):
        _audit_path = _commit_b_audit(_reviews_dir, _baseline, _prefix)
        _audit_text = _audit_path.read_text(encoding="utf-8") if _audit_path else ""
        _audit_doc = json.loads(_audit_text) if _audit_text else {}
        check(
            f"the TRANSFERRED Commit B {_fam} promotion audit carries ONLY repo-relative POSIX locators "
            f"(source_pending_path / canonical_path / previous_canonical_backup under data/cases/{CASE_ID}/) "
            "with no backslash, no drive letter and no worktree/repo absolute path",
            _audit_path is not None
            and all(
                isinstance(_audit_doc.get(field), str)
                and _audit_doc[field].startswith(f"data/cases/{CASE_ID}/{_fam}/")
                and "\\" not in _audit_doc[field] and ":" not in _audit_doc[field]
                for field in ("source_pending_path", "canonical_path", "previous_canonical_backup")
            )
            and "\\" not in _audit_text and "C:/" not in _audit_text
            and str(REPO_ROOT) not in _audit_text and str(_TMP_ROOT) not in _audit_text,
            f"audit={_audit_path.name if _audit_path else None} "
            f"fields={ {f: _audit_doc.get(f) for f in ('source_pending_path', 'canonical_path', 'previous_canonical_backup')} }",
        )

    # --- identity / manifest -------------------------------------------
    root_real = qcvf._resolve_module_case_root_real(qa_engine, CASE_ID)
    paths_qa, manifest_qa, identity_qa, identity_bytes_qa, digest_qa = qcvf._derive_identity("qa", qa_engine, root_real, CASE_ID)
    names = [c["logical_name"] for c in manifest_qa]
    states = {c["logical_name"]: c["state"] for c in manifest_qa}
    check(
        "qa manifest: 12 containers, sorted by logical_name, documents/facts present with 3 files each, "
        "evidence missing (Row 12 canonical evidence.json does not exist)",
        len(manifest_qa) == 12 and names == sorted(names)
        and states["documents"] == "present" and states["facts"] == "present"
        and len(next(c for c in manifest_qa if c["logical_name"] == "documents")["files"]) == 3
        and states["evidence"] == "missing",
        f"states={states}",
    )
    check(
        "qa manifest file entries use POSIX logical relative paths derived from validated segments "
        "(documents/<id>/document.json), never resolved absolute paths",
        all(
            "\\" not in f["logical_relative_path"] and not f["logical_relative_path"].startswith("/")
            and ":" not in f["logical_relative_path"]
            for c in manifest_qa for f in c["files"]
        )
        and {f["logical_relative_path"] for f in next(c for c in manifest_qa if c["logical_name"] == "documents")["files"]}
        == {f"documents/{d}/document.json" for d in ("vir_001", "ihbarname_001", "dava_dilekcesi_001")},
    )
    check("qa identity payload has exactly the 5 keys", set(identity_qa) == {"manifest_version", "manifest", "generation_mode", "model_id", "prompt_agent_version"})
    check("qa input_digest is deterministic across two derivations", qcvf._derive_identity("qa", qa_engine, root_real, CASE_ID)[4] == digest_qa)
    check("adapter accepts the facade's own identity payload shape", qcva._validate_identity_payload_shape(identity_qa, "qa") is True)
    check(
        "adapter rejects an agent-mode identity payload for this deterministic-only family",
        qcva._validate_identity_payload_shape({**identity_qa, "generation_mode": "agent", "model_id": "claude-x"}, "qa") is False,
    )
    check(
        "verified output paths: family_root/pending/history/reviews all under the verified case root and "
        "pending == Layer A's pinned pending name",
        all(str(p).startswith(str(root_real)) for p in (paths_qa.family_root, paths_qa.pending_path, paths_qa.history_dir, paths_qa.reviews_dir))
        and paths_qa.pending_path.name == qa_approval.get_pending_path(CASE_ID).name
        and paths_qa.reviews_dir.name == "generation_reviews" and paths_qa.history_dir.name == "history",
    )
    check(
        "BASELINE: the canonical qa.json in this tree is FRESH/VALID (Commit B regenerated snapshot) - "
        "so every stale-QA refusal below is exercised on a SYNTHETIC stale state this suite creates "
        "itself, never on the committed fixture's state",
        qa_validator.validate_qa_analysis(canonical_qa, expected_case_id=CASE_ID, raise_on_error=False)["valid"] is True,
        str(qa_validator.validate_qa_analysis(canonical_qa, expected_case_id=CASE_ID, raise_on_error=False).get("errors"))[:400],
    )
    check(
        "case_view identity derivation SUCCEEDS on the fresh canonical qa.json (positive control for the "
        "prerequisite guard: its refusals below cannot be an unrelated failure)",
        qcvf._derive_identity(
            "case_view", orchestrator_engine,
            qcvf._resolve_module_case_root_real(orchestrator_engine, CASE_ID), CASE_ID,
        )[4] is not None,
    )

    # --- facade preview with an in-memory authz repository ------------
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[1] = _authz.SessionRecord(user_id=501, current_authz_version=1, disabled=False)
    repo.assignments[(501, CASE_ID)] = _authz.CaseAssignmentRecord(role="lawyer")
    repo.assignments[(502, CASE_ID)] = _authz.CaseAssignmentRecord(role="analyst")
    repo.sessions[2] = _authz.SessionRecord(user_id=502, current_authz_version=1, disabled=False)
    lawyer = _authz.Principal(user_id=501, session_id=1, role_version_at_issue=1)
    analyst = _authz.Principal(user_id=502, session_id=2, role_version_at_issue=1)
    preview = qcvf.preview_generation("qa", CASE_ID, principal=lawyer, authz_repository=repo)
    check(
        "facade preview (in-memory authz): target_ref/input_digest/deterministic sentinels/pending_exists=False",
        preview["target_ref"] == "qa.pending" and preview["input_digest"] == digest_qa
        and preview["generation_mode"] == "deterministic" and preview["pending_exists"] is False
        and preview["pending_sha256"] is None,
        f"preview={preview}",
    )
    preview_analyst = qcvf.preview_generation("qa", CASE_ID, principal=analyst, authz_repository=repo)
    check("analyst preview allowed (read capability) and yields the same digest", preview_analyst["input_digest"] == digest_qa)
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: qcvf.apply_generation("qa", CASE_ID, digest_qa, principal=analyst, authz_repository=repo, conn_factory=_ExplodingConnFactory()),
        "analyst apply denied by the OUTER authz before any connection factory call",
    )
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: qcvf.preview_generation("qa", "case_9999", principal=lawyer, authz_repository=repo),
        "preview of an unassigned/nonexistent case is denied (existence-blind)",
    )
    expect_raises(
        _common.StaleViewError,
        lambda: qcvf.apply_generation("qa", CASE_ID, "0" * 64, principal=lawyer, authz_repository=repo, conn_factory=_ExplodingConnFactory()),
        "apply with a stale expected_input_digest -> StaleViewError BEFORE any connection factory call",
    )
    expect_raises(
        qcvf.QaCaseViewGenerationAgentModeRefusedError,
        lambda: qcvf.apply_generation("qa", CASE_ID, digest_qa, with_agent=True, allow_network=True, principal=lawyer, authz_repository=repo, conn_factory=_ExplodingConnFactory()),
        "apply with agent flags refused BEFORE authz/connection",
    )

    # --- SYNTHETIC stale canonical qa.json -----------------------------
    # ONE reversible, schema-preserving byte change to an upstream artefact the
    # QA dependency manifest binds (timeline.json) is the ONLY thing that makes
    # canonical qa.json stale here. The positive control above proved the guard
    # accepts the fresh tree; the revert below proves the mutation - not an
    # unrelated error - is what the refusals detect.
    _stale_upstream = CASE_DIR / "timeline" / "timeline.json"
    _stale_pristine = _stale_upstream.read_bytes()
    _stale_upstream.write_bytes(_stale_pristine.replace(b"}", b" }", 1))
    check(
        "the single upstream mutation is schema-preserving (same parsed JSON, different bytes) and makes "
        "canonical qa.json STALE/invalid",
        json.loads(_stale_upstream.read_text(encoding="utf-8")) == json.loads(_stale_pristine.decode("utf-8"))
        and _stale_upstream.read_bytes() != _stale_pristine
        and qa_validator.validate_qa_analysis(canonical_qa, expected_case_id=CASE_ID, raise_on_error=False)["valid"] is False,
    )
    expect_raises(
        qcvf.CaseViewQaPrerequisiteError,
        lambda: qcvf._derive_identity("case_view", orchestrator_engine, qcvf._resolve_module_case_root_real(orchestrator_engine, CASE_ID), CASE_ID),
        "case_view on a stale canonical qa.json -> CaseViewQaPrerequisiteError",
    )
    expect_raises(
        qcvf.CaseViewQaPrerequisiteError,
        lambda: qcvf.preview_generation("case_view", CASE_ID, principal=lawyer, authz_repository=repo),
        "case_view preview on the stale canonical qa.json -> CaseViewQaPrerequisiteError",
    )
    expect_raises(
        qcvf.CaseViewQaPrerequisiteError,
        lambda: qcvf.apply_generation("case_view", CASE_ID, "0" * 64, principal=lawyer, authz_repository=repo, conn_factory=_ExplodingConnFactory()),
        "case_view apply on the stale canonical qa.json -> CaseViewQaPrerequisiteError BEFORE any connection",
    )
    _stale_upstream.write_bytes(_stale_pristine)
    check(
        "reverting that single byte change restores BOTH canonical qa.json validity AND the qa input_digest "
        "(the synthetic stale state is fully reversible - nothing else drifted)",
        _stale_upstream.read_bytes() == _stale_pristine
        and qa_validator.validate_qa_analysis(canonical_qa, expected_case_id=CASE_ID, raise_on_error=False)["valid"] is True
        and qcvf._derive_identity("qa", qa_engine, root_real, CASE_ID)[4] == digest_qa,
    )

    # --- builder result gates (fake builders; nothing written) ----------
    class _FakeQaModule:
        def build_qa_engine_output(self, case_id):
            return {"qa_generation_status": "aborted_source_changed", "case_id": case_id}

    class _FakeViewModule:
        def build_case_view(self, case_id):
            return {"generation_status": "failed", "case_id": case_id}

    expect_raises(
        qcvf.QaGenerationAbortedError, lambda: qcvf._invoke_builder("qa", _FakeQaModule(), CASE_ID),
        "a qa build reporting aborted_source_changed is refused (QaGenerationAbortedError) - no write",
    )
    expect_raises(
        qcvf.CaseViewGenerationIncompleteError, lambda: qcvf._invoke_builder("case_view", _FakeViewModule(), CASE_ID),
        "a case_view build with generation_status != completed is refused - no write",
    )
    # Real builder path, apply refused AFTER build but BEFORE lock: patch the real module's builder.
    _real_build = qa_engine.build_qa_engine_output
    try:
        qa_engine.build_qa_engine_output = lambda case_id: {**_real_build(case_id), "qa_generation_status": "aborted_source_changed"}
        expect_raises(
            qcvf.QaGenerationAbortedError,
            lambda: qcvf.apply_generation("qa", CASE_ID, digest_qa, principal=lawyer, authz_repository=repo, conn_factory=_ExplodingConnFactory()),
            "apply: an aborted_source_changed build is refused BEFORE any connection/lock/journal (zero writes)",
        )
    finally:
        qa_engine.build_qa_engine_output = _real_build
    check("no pending and NO NEW history / generation_reviews entries were created by any refusal above "
          "(relative to the Commit B provenance baseline, which is byte-identical)",
          not paths_qa.pending_path.exists()
          and new_entries(paths_qa.history_dir, qa_history_before) == []
          and new_entries(paths_qa.reviews_dir, qa_genrev_before) == []
          and kept_entries(paths_qa.history_dir, qa_history_before) == qa_history_before
          and kept_entries(paths_qa.reviews_dir, qa_genrev_before) == qa_genrev_before)

    # --- writer: partial binding refused, first write, second write -----
    analysis = qcvf._invoke_builder("qa", qa_engine, CASE_ID)
    frozen = qcvf._freeze_pending_bytes(analysis)
    expect_raises(
        qa_engine.QaEngineError,
        lambda: qa_engine.write_pending(CASE_ID, json.loads(frozen.decode()), verified_paths=paths_qa, mutation_idempotency_key="k" * 64),
        "write_pending: partial mutation binding refused (QaEngineError)",
    )
    check("partial-binding refusal wrote nothing", not paths_qa.pending_path.exists())
    identity_for_audit = json.loads(identity_bytes_qa.decode())
    res1 = qa_engine.write_pending(
        CASE_ID, json.loads(frozen.decode()), verified_paths=paths_qa, input_digest=digest_qa,
        identity_payload=identity_for_audit, mutation_idempotency_key="k" * 64,
        mutation_resource_key=f"case:{CASE_ID}", mutation_actor_ref="501",
    )
    check(
        "first write: pending written at the pinned name, first_write=True, audit under qa/generation_reviews/",
        res1["pending_path"] == paths_qa.pending_path and paths_qa.pending_path.is_file() and res1["first_write"] is True
        and res1["audit_path"].parent == paths_qa.reviews_dir and res1["audit_path"].name.endswith(".generation_audit.json"),
    )
    check("first write: the pending bytes equal the frozen recipe (ensure_ascii=False, indent=2, trailing LF)", paths_qa.pending_path.read_bytes() == frozen)
    check("first write: pending_sha256 reported == on-disk sha256", res1["pending_sha256"] == hashlib.sha256(frozen).hexdigest())
    check("first write: canonical qa.json untouched (canonical-mutation guard)", canonical_qa.read_bytes() == canonical_qa_before)
    audit1 = json.loads(res1["audit_path"].read_text(encoding="utf-8"))
    check(
        "first audit: full mutation binding, channel sentinel, history_backup_path=None, no absolute path anywhere",
        audit1["mutation_idempotency_key"] == "k" * 64 and audit1["mutation_resource_key"] == f"case:{CASE_ID}"
        and audit1["mutation_actor_ref"] == "501" and audit1["channel"] == "local_lawyer_generation_cli"
        and audit1["history_backup_path"] is None and audit1["history_backup_sha256"] is None
        and audit1["target_ref"] == "qa.pending" and audit1["action_family"] == "generation.qa"
        and audit1["input_digest"] == digest_qa and audit1["identity_payload"] == identity_for_audit
        and str(_TMP_ROOT) not in res1["audit_path"].read_text(encoding="utf-8")
        and str(REPO_ROOT) not in res1["audit_path"].read_text(encoding="utf-8"),
        f"audit1={audit1}",
    )
    pending_locators = [
        r["artifact_locator"]["path"] for r in json.loads(paths_qa.pending_path.read_text(encoding="utf-8"))["qa_check_results"]
        if r.get("artifact_locator") and r["artifact_locator"].get("path") is not None
    ]
    check(
        "generated QA pending: every artifact_locator.path is a repo-relative POSIX locator under "
        "data/cases/case_0001/ (portable across worktrees)",
        pending_locators and all(p.startswith("data/cases/case_0001/") and "\\" not in p and ":" not in p for p in pending_locators),
        f"sample={pending_locators[:3]}",
    )
    history_dir_verified = qcva._derive_history_dir(qa_engine, root_real, CASE_ID)
    check(
        "adapter full binding accepts the REAL first audit",
        qcva._audit_record_matches(
            audit1, "qa", idempotency_key="k" * 64, resource_key=f"case:{CASE_ID}", action_family="generation.qa",
            target_ref="qa.pending", target_state="generated", actor_label="501",
            pending_sha256=res1["pending_sha256"], history_dir_verified=history_dir_verified,
        ) is True,
    )
    tamper_cases = {
        "wrong actor": {"mutation_actor_ref": "502"},
        "wrong channel": {"channel": "web"},
        "wrong action_family": {"action_family": "generation.case_view"},
        "wrong target_ref": {"target_ref": "case_view.pending"},
        "identity payload tampered (digest no longer recomputes)": {"identity_payload": {**identity_for_audit, "model_id": "x"}},
        "top-level generation_mode != identity payload": {"generation_mode": "agent"},
        "non-null generation_parameters_digest": {"generation_parameters_digest": "abc"},
        "first_write=False but no backup fields": {"first_write": False},
        "outcome not generated": {"outcome": "failed"},
    }
    for label, patch in tamper_cases.items():
        check(
            f"adapter tamper matrix: {label} -> not matched",
            qcva._audit_record_matches(
                {**audit1, **patch}, "qa", idempotency_key="k" * 64, resource_key=f"case:{CASE_ID}",
                action_family="generation.qa", target_ref="qa.pending", target_state="generated", actor_label="501",
                pending_sha256=res1["pending_sha256"], history_dir_verified=history_dir_verified,
            ) is False,
        )
    check(
        "adapter: wrong idempotency key / wrong pending sha -> not matched",
        qcva._audit_record_matches(
            audit1, "qa", idempotency_key="z" * 64, resource_key=f"case:{CASE_ID}", action_family="generation.qa",
            target_ref="qa.pending", target_state="generated", actor_label="501",
            pending_sha256=res1["pending_sha256"], history_dir_verified=history_dir_verified,
        ) is False
        and qcva._audit_record_matches(
            audit1, "qa", idempotency_key="k" * 64, resource_key=f"case:{CASE_ID}", action_family="generation.qa",
            target_ref="qa.pending", target_state="generated", actor_label="501",
            pending_sha256="0" * 64, history_dir_verified=history_dir_verified,
        ) is False,
    )

    # second write (same content, different idempotency key) -> history backup + repo-relative locator
    pending_before_second = paths_qa.pending_path.read_bytes()
    res2 = qa_engine.write_pending(
        CASE_ID, json.loads(frozen.decode()), verified_paths=paths_qa, input_digest=digest_qa,
        identity_payload=identity_for_audit, mutation_idempotency_key="j" * 64,
        mutation_resource_key=f"case:{CASE_ID}", mutation_actor_ref="501",
    )
    audit2 = json.loads(res2["audit_path"].read_text(encoding="utf-8"))
    # Fail-safe: a writer that recorded NO history_backup_path must still yield
    # clean FAILs below, never a NoneType AttributeError.
    _audit2_backup_locator = audit2["history_backup_path"] or f"data/cases/{CASE_ID}/qa/history/__NO_NEW_BACKUP__"
    _new_backup_names = new_entries(paths_qa.history_dir, qa_history_before)
    backups = [paths_qa.history_dir / n for n in _new_backup_names]
    # Fail-safe probes: if the writer produced NO new backup (a broken/neutered
    # history move) every check below must report a clean FAIL instead of an
    # IndexError that would abort the rest of the suite.
    _backup_name = backups[0].name if backups else "__NO_NEW_BACKUP__"
    _backup_bytes = backups[0].read_bytes() if backups else b""
    _backup_str = str(backups[0]) if backups else str(paths_qa.history_dir / _backup_name)
    check(
        "second write: EXACTLY ONE NEW qa/history/ backup appeared (set difference against the Commit B "
        "baseline) carrying the previous pending byte-identically; first_write=False; every pre-existing "
        "history file untouched",
        res2["first_write"] is False and len(backups) == 1 and backups[0].read_bytes() == pending_before_second
        and backups[0].name.startswith("qa_pending_before_engine_")
        and kept_entries(paths_qa.history_dir, qa_history_before) == qa_history_before,
        f"new={_new_backup_names}",
    )
    check(
        "second audit: history_backup_path is the EXACT repo-relative locator "
        "data/cases/case_0001/qa/history/<name> (no absolute path), sha matches the backup",
        len(backups) == 1
        and audit2["history_backup_path"] == f"data/cases/{CASE_ID}/qa/history/{_backup_name}"
        and audit2["history_backup_sha256"] == hashlib.sha256(_backup_bytes).hexdigest()
        and str(_TMP_ROOT) not in json.dumps(audit2)
        and str(REPO_ROOT) not in json.dumps(audit2),
        f"audit2={audit2}",
    )
    check(
        "adapter full binding accepts the second audit via the portable history_backup_path binding",
        qcva._audit_record_matches(
            audit2, "qa", idempotency_key="j" * 64, resource_key=f"case:{CASE_ID}", action_family="generation.qa",
            target_ref="qa.pending", target_state="generated", actor_label="501",
            pending_sha256=res2["pending_sha256"], history_dir_verified=history_dir_verified,
        ) is True,
    )
    for label, bad_path in {
        "absolute path": _backup_str,
        "backslash separators": _audit2_backup_locator.replace("/", "\\"),
        "wrong case_id in locator": _audit2_backup_locator.replace(CASE_ID, "case_0002"),
        "wrong family dir": _audit2_backup_locator.replace("/qa/history/", "/case_view/history/"),
        "traversal": "data/cases/case_0001/qa/history/../" + _backup_name,
        "nonexistent backup name": f"data/cases/{CASE_ID}/qa/history/qa_pending_before_engine_00000000_000000.json.pending",
        "bare name": _backup_name,
    }.items():
        check(
            f"adapter history_backup_path binding rejects: {label}",
            qcva._audit_record_matches(
                {**audit2, "history_backup_path": bad_path}, "qa", idempotency_key="j" * 64,
                resource_key=f"case:{CASE_ID}", action_family="generation.qa", target_ref="qa.pending",
                target_state="generated", actor_label="501", pending_sha256=res2["pending_sha256"],
                history_dir_verified=history_dir_verified,
            ) is False,
        )
    check(
        "adapter: history_dir_verified=None (containment failure upstream) -> a non-first-write audit "
        "is NOT matched (fail-closed, audit text never used as a root)",
        qcva._audit_record_matches(
            audit2, "qa", idempotency_key="j" * 64, resource_key=f"case:{CASE_ID}", action_family="generation.qa",
            target_ref="qa.pending", target_state="generated", actor_label="501",
            pending_sha256=res2["pending_sha256"], history_dir_verified=None,
        ) is False,
    )
    # pre-state proof round trip (adapter's independent snapshot formula)
    snap = qcvf._compute_pending_snapshot(digest_qa, paths_qa.pending_path)
    check(
        "adapter pre-hash formula == facade composite snapshot (independent copies agree)",
        qcva._compute_candidate_pre_hash(digest_qa, snap.pending_presence, snap.pending_sha256) == snap.composite_digest,
    )

    # --- rollback: a write whose post-write validation fails restores the previous pending
    pending_before_bad = paths_qa.pending_path.read_bytes()
    bad = json.loads(frozen.decode())
    bad["qa_generation_status"] = "aborted_source_changed"
    try:
        qa_engine.write_pending(
            CASE_ID, bad, verified_paths=paths_qa, input_digest=digest_qa, identity_payload=identity_for_audit,
            mutation_idempotency_key="b" * 64, mutation_resource_key=f"case:{CASE_ID}", mutation_actor_ref="501",
        )
        check("write_pending refuses an aborted_source_changed analysis", False, "no exception")
    except Exception:  # noqa: BLE001 - validator ValueError or QaEngineError, both fail-closed
        check("write_pending refuses an aborted_source_changed analysis (raises)", True)
    check(
        "rollback: the previous pending is restored byte-identical, no extra NEW history backup, no third "
        "NEW audit (relative deltas against the Commit B baseline; pre-existing entries untouched)",
        paths_qa.pending_path.read_bytes() == pending_before_bad
        and new_entries(paths_qa.history_dir, qa_history_before) == _new_backup_names
        and len(new_entries(paths_qa.reviews_dir, qa_genrev_before)) == 2
        and kept_entries(paths_qa.history_dir, qa_history_before) == qa_history_before
        and kept_entries(paths_qa.reviews_dir, qa_genrev_before) == qa_genrev_before,
        f"new_history={new_entries(paths_qa.history_dir, qa_history_before)} "
        f"new_audits={new_entries(paths_qa.reviews_dir, qa_genrev_before)}",
    )

    # --- real Layer A run_approve (legacy path, no coordinator) -> option (b) audit locators
    qa_approval.run_approve(CASE_ID)
    _qa_new_approvals = new_entries(CASE_DIR / "qa" / "reviews", qa_reviews_before)
    check(
        "Layer A qa approval produced EXACTLY ONE NEW approval audit under qa/reviews/ (identified by set "
        "difference against the Commit B baseline, never by `sorted(glob)[-1]`)",
        len(_qa_new_approvals) == 1, f"new={_qa_new_approvals}",
    )
    # Fail-safe: a neutered/broken approval writes no new audit - report clean
    # FAILs below instead of an IndexError that would abort the suite.
    approval_audit = json.loads(
        (CASE_DIR / "qa" / "reviews" / _qa_new_approvals[-1]).read_text(encoding="utf-8")
    ) if _qa_new_approvals else {}
    check(
        "qa approval audit: source_pending_path/canonical_path/previous_canonical_backup are repo-relative "
        "POSIX locators with the exact canonical layout",
        approval_audit.get("source_pending_path") == f"data/cases/{CASE_ID}/qa/qa_{CASE_ID}_v1.json.pending"
        and approval_audit.get("canonical_path") == f"data/cases/{CASE_ID}/qa/qa.json"
        and str(approval_audit.get("previous_canonical_backup")).startswith(f"data/cases/{CASE_ID}/qa/qa.json.before_approval_")
        and str(_TMP_ROOT) not in json.dumps(approval_audit)
        and str(REPO_ROOT) not in json.dumps(approval_audit),
        f"audit={approval_audit}",
    )
    check("canonical qa.json now equals the generated pending", canonical_qa.read_bytes() == paths_qa.pending_path.read_bytes())
    check(
        "the pre-existing approval audits copied from case_0001 are byte-identical (never rewritten) - "
        "both the pre-Commit-B 20260904_202837 record and the Commit B promotion record",
        kept_entries(CASE_DIR / "qa" / "reviews", qa_reviews_before) == qa_reviews_before
        and any("20260904_202837" in n for n in qa_reviews_before) and len(qa_reviews_before) >= 2,
        f"baseline={sorted(qa_reviews_before)}",
    )

    # --- case_view now passes the prerequisite; write + approve --------
    root_real_cv = qcvf._resolve_module_case_root_real(orchestrator_engine, CASE_ID)
    paths_cv, manifest_cv, identity_cv, identity_bytes_cv, digest_cv = qcvf._derive_identity("case_view", orchestrator_engine, root_real_cv, CASE_ID)
    qa_container = next(c for c in manifest_cv if c["logical_name"] == "qa")
    check(
        "case_view manifest: 11 containers; the qa container binds the CURRENT canonical qa.json sha256",
        len(manifest_cv) == 11 and qa_container["state"] == "present"
        and qa_container["files"][0]["sha256"] == hashlib.sha256(canonical_qa.read_bytes()).hexdigest(),
    )
    preview_cv = qcvf.preview_generation("case_view", CASE_ID, principal=lawyer, authz_repository=repo)
    check("case_view preview succeeds after a fresh canonical qa.json", preview_cv["input_digest"] == digest_cv and preview_cv["target_ref"] == "case_view.pending")
    view = qcvf._invoke_builder("case_view", orchestrator_engine, CASE_ID)
    frozen_cv = qcvf._freeze_pending_bytes(view)
    rescv = orchestrator_engine.write_pending(
        CASE_ID, json.loads(frozen_cv.decode()), verified_paths=paths_cv, input_digest=digest_cv,
        identity_payload=json.loads(identity_bytes_cv.decode()), mutation_idempotency_key="c" * 64,
        mutation_resource_key=f"case:{CASE_ID}", mutation_actor_ref="501",
    )
    check(
        "case_view first write: pending at the Layer-A-pinned name, generation_status=completed, canonical untouched",
        rescv["pending_path"] == orchestrator_approval.get_pending_path(CASE_ID) and rescv["first_write"] is True
        and json.loads(rescv["pending_path"].read_text(encoding="utf-8"))["generation_status"] == "completed"
        and canonical_cv.read_bytes() == canonical_cv_before,
    )
    audit_cv = json.loads(rescv["audit_path"].read_text(encoding="utf-8"))
    check(
        "case_view audit: generation.case_view / case_view.pending / channel / actor / no absolute path",
        audit_cv["action_family"] == "generation.case_view" and audit_cv["target_ref"] == "case_view.pending"
        and audit_cv["channel"] == "local_lawyer_generation_cli" and audit_cv["mutation_actor_ref"] == "501"
        and str(_TMP_ROOT) not in json.dumps(audit_cv)
        and str(REPO_ROOT) not in json.dumps(audit_cv),
    )
    check(
        "case_view first write: EXACTLY ONE NEW generation audit and NO new history backup (set differences "
        "against the Commit B baseline); every pre-existing case_view provenance file untouched",
        len(new_entries(paths_cv.reviews_dir, cv_genrev_before)) == 1
        and new_entries(paths_cv.history_dir, cv_history_before) == []
        and kept_entries(paths_cv.reviews_dir, cv_genrev_before) == cv_genrev_before
        and kept_entries(paths_cv.history_dir, cv_history_before) == cv_history_before,
        f"new_audits={new_entries(paths_cv.reviews_dir, cv_genrev_before)} "
        f"new_history={new_entries(paths_cv.history_dir, cv_history_before)}",
    )
    check(
        "adapter full binding accepts the REAL case_view audit",
        qcva._audit_record_matches(
            audit_cv, "case_view", idempotency_key="c" * 64, resource_key=f"case:{CASE_ID}",
            action_family="generation.case_view", target_ref="case_view.pending", target_state="generated",
            actor_label="501", pending_sha256=rescv["pending_sha256"],
            history_dir_verified=qcva._derive_history_dir(orchestrator_engine, root_real_cv, CASE_ID),
        ) is True,
    )
    orchestrator_approval.run_approve(CASE_ID)
    _cv_new_approvals = new_entries(CASE_DIR / "case_view" / "reviews", cv_reviews_before)
    check(
        "Layer A case_view approval produced EXACTLY ONE NEW approval audit under case_view/reviews/ (set "
        "difference, never `sorted(glob)[-1]`) and left every pre-existing audit byte-identical - including "
        "the pre-Commit-B 20260904_212319 record and the Commit B promotion record",
        len(_cv_new_approvals) == 1
        and kept_entries(CASE_DIR / "case_view" / "reviews", cv_reviews_before) == cv_reviews_before
        and any("20260904_212319" in n for n in cv_reviews_before) and len(cv_reviews_before) >= 2,
        f"new={_cv_new_approvals} baseline={sorted(cv_reviews_before)}",
    )
    approval_audit_cv = json.loads(
        (CASE_DIR / "case_view" / "reviews" / _cv_new_approvals[-1]).read_text(encoding="utf-8")
    ) if _cv_new_approvals else {}
    check(
        "case_view approval audit: repo-relative POSIX locators with the exact canonical layout",
        approval_audit_cv.get("source_pending_path") == f"data/cases/{CASE_ID}/case_view/case_view_{CASE_ID}_v1.json.pending"
        and approval_audit_cv.get("canonical_path") == f"data/cases/{CASE_ID}/case_view/case_view.json"
        and str(approval_audit_cv.get("previous_canonical_backup")).startswith(f"data/cases/{CASE_ID}/case_view/case_view.json.before_approval_")
        and str(_TMP_ROOT) not in json.dumps(approval_audit_cv)
        and str(REPO_ROOT) not in json.dumps(approval_audit_cv),
        f"audit={approval_audit_cv}",
    )

    # --- re-identified / missing QA -> case_view refused again -----------
    timeline = CASE_DIR / "timeline" / "timeline.json"
    original_timeline = timeline.read_bytes()
    timeline.write_bytes(original_timeline.replace(b"}", b" }", 1))
    expect_raises(
        qcvf.CaseViewQaPrerequisiteError,
        lambda: qcvf.preview_generation("case_view", CASE_ID, principal=lawyer, authz_repository=repo),
        "after an upstream change the canonical qa.json is stale -> case_view preview refused",
    )
    check(
        "the same upstream change yields a NEW qa input_digest (re-identification)",
        qcvf.preview_generation("qa", CASE_ID, principal=lawyer, authz_repository=repo)["input_digest"] != digest_qa,
    )
    timeline.write_bytes(original_timeline)
    canonical_qa.rename(canonical_qa.with_suffix(".json.moved"))
    expect_raises(
        qcvf.CaseViewQaPrerequisiteError,
        lambda: qcvf.preview_generation("case_view", CASE_ID, principal=lawyer, authz_repository=repo),
        "missing canonical qa.json -> case_view preview refused",
    )
    canonical_qa.with_suffix(".json.moved").rename(canonical_qa)

    # --- containment: an escaping junction inside the case dir is refused by the manifest scanner
    outside = _TMP_ROOT / "outside"
    outside.mkdir()
    (outside / "issues.json").write_text("{}", encoding="utf-8")
    real_issues_dir = CASE_DIR / "issues"
    moved_issues = _TMP_ROOT / "issues_moved"
    shutil.move(str(real_issues_dir), str(moved_issues))
    if make_junction(real_issues_dir, outside):
        expect_raises(
            qcvf.QaCaseViewGenerationInputContainmentError,
            lambda: qcvf._build_manifest_containers("qa", root_real, CASE_ID),
            "manifest scanner: an escaping NTFS junction in place of issues/ is refused (fail-closed, "
            "never treated as missing)",
        )
        os.rmdir(real_issues_dir)
    else:
        print("SKIPPED junction-escape manifest check (no junction tooling on this platform) - NOT counted as pass/fail")
    shutil.move(str(moved_issues), str(real_issues_dir))
    check("manifest scanner recovers to the same digest after the junction is removed",
          qcvf._derive_identity("qa", qa_engine, root_real, CASE_ID)[4] == digest_qa)

finally:
    for _m in _holders:
        _m.CASES_DIR = _REAL_CASES_ROOT
    qa_validator.BASE_DIR = _real_qv_base
    qa_approval.BASE_DIR = _real_qa_base
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


# ============================================================
# 6) Deterministic same-second history-name collision (FROZEN clock) -
#    F1 test-only remediation.
#
#    Regression guard for the numeric-suffix loop in
#    `qa_engine.preserve_previous_pending` and
#    `orchestrator_engine.preserve_previous_pending`: three moves of the
#    SAME pending under a clock frozen to ONE second must yield EXACTLY
#    <base>, <base>_1, <base>_2 with every original byte preserved and
#    nothing overwritten. The clock is frozen, so the outcome does not
#    depend on a wall-clock race: with the suffix loop removed the second
#    move lands on the first backup's name and `shutil.move` overwrites it
#    (1 file instead of 3) DETERMINISTICALLY.
#
#    Each engine's REAL datetime binding is patched - qa_engine binds the
#    CLASS (`from datetime import datetime`), orchestrator_engine binds
#    the MODULE (`import datetime`, used as `datetime.datetime.now()`) -
#    and restored in `finally`. Tempdir only; nothing under the repo or
#    data/cases is touched. The two engines are asserted SEPARATELY with
#    engine-labelled messages so neither can mask the other.
# ============================================================

_FROZEN_INSTANT = _dt_module.datetime(2026, 9, 27, 12, 0, 0, tzinfo=_dt_module.timezone.utc)
# The engines format LOCAL time (`.now().astimezone().strftime(...)`) - derive the expected
# stamp the same way, so the expectation is timezone-independent.
_FROZEN_STAMP = _FROZEN_INSTANT.astimezone().strftime("%Y%m%d_%H%M%S")


class _FrozenDateTime(_dt_module.datetime):
    """`datetime` subclass whose `now()` always returns the same aware instant."""

    @classmethod
    def now(cls, tz=None):
        return _FROZEN_INSTANT if tz is None else _FROZEN_INSTANT.astimezone(tz)


def _frozen_datetime_module():
    """A stand-in for the `datetime` MODULE (orchestrator_engine's binding):
    every public attribute of the real module, with `datetime` replaced by
    the frozen class."""
    fake = types.SimpleNamespace(
        **{name: getattr(_dt_module, name) for name in dir(_dt_module) if not name.startswith("__")}
    )
    fake.datetime = _FrozenDateTime
    return fake


def run_frozen_clock_collision_case(module, engine_label, history_prefix, *, clock_stamp, patch_clock, unpatch_clock):
    td = Path(tempfile.mkdtemp(prefix=f"qacv_ss_{engine_label}_"))
    try:
        pending = td / "fam" / "x.json.pending"
        pending.parent.mkdir(parents=True)
        history = td / "fam" / "history"
        payloads = [f'{{"engine": "{engine_label}", "write": {i}}}\n'.encode("utf-8") for i in range(3)]
        expected_names = [
            f"{history_prefix}{_FROZEN_STAMP}.json.pending",
            f"{history_prefix}{_FROZEN_STAMP}_1.json.pending",
            f"{history_prefix}{_FROZEN_STAMP}_2.json.pending",
        ]
        returned = []
        patch_clock()
        try:
            # Non-vacuity guard: the engine's OWN clock binding must now be frozen. If the
            # monkeypatch did not take effect, this fails loudly instead of the case passing on
            # three distinct real-time stamps.
            observed_stamp = clock_stamp()
            check(
                f"{engine_label} SAME-SECOND: engine clock binding is frozen to the single instant "
                f"{_FROZEN_STAMP} (monkeypatch took effect)",
                observed_stamp == _FROZEN_STAMP, f"observed {observed_stamp!r}",
            )
            for payload in payloads:
                pending.write_bytes(payload)
                returned.append(module.preserve_previous_pending("case_frozen", pending, history_dir=history))
        finally:
            unpatch_clock()
        on_disk = sorted(p.name for p in history.iterdir()) if history.is_dir() else []
        check(
            f"{engine_label} SAME-SECOND: three moves under ONE frozen second produced EXACTLY "
            f"{expected_names} (base, _1, _2)",
            on_disk == sorted(expected_names), f"got {on_disk}",
        )
        check(
            f"{engine_label} SAME-SECOND: returned history paths are base/_1/_2 in write order",
            [p.name for p in returned] == expected_names, f"got {[p.name for p in returned]}",
        )
        check(
            f"{engine_label} SAME-SECOND: every backup carries its ORIGINAL bytes "
            "(write 0 -> base, write 1 -> _1, write 2 -> _2)",
            on_disk == sorted(expected_names)
            and all((history / name).read_bytes() == payloads[i] for i, name in enumerate(expected_names)),
            f"got {[(history / n).read_bytes() for n in on_disk]}",
        )
        check(
            f"{engine_label} SAME-SECOND: no earlier backup was overwritten (the three distinct payloads "
            "are each present exactly once)",
            sorted(p.read_bytes() for p in history.iterdir()) == sorted(payloads) if history.is_dir() else False,
            f"got {sorted(p.read_bytes() for p in history.iterdir()) if history.is_dir() else None}",
        )
        check(f"{engine_label} SAME-SECOND: the pending was consumed by each move (not left behind)", not pending.exists())
    finally:
        shutil.rmtree(td, ignore_errors=True)
    check(f"{engine_label} SAME-SECOND: frozen-clock tempdir removed (no residue)", not td.exists())


# qa_engine: `from datetime import datetime` -> the module attribute IS the class.
_orig_qa_engine_datetime = qa_engine.datetime
run_frozen_clock_collision_case(
    qa_engine, "qa_engine", "qa_pending_before_engine_",
    clock_stamp=lambda: qa_engine.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S"),
    patch_clock=lambda: setattr(qa_engine, "datetime", _FrozenDateTime),
    unpatch_clock=lambda: setattr(qa_engine, "datetime", _orig_qa_engine_datetime),
)
check(
    "qa_engine SAME-SECOND: real datetime binding restored after the frozen-clock case",
    qa_engine.datetime is _orig_qa_engine_datetime is _dt_module.datetime,
)

# orchestrator_engine: `import datetime` -> the module attribute is the MODULE (`datetime.datetime.now()`).
_orig_orchestrator_engine_datetime = orchestrator_engine.datetime
run_frozen_clock_collision_case(
    orchestrator_engine, "orchestrator_engine", "case_view_pending_before_engine_",
    clock_stamp=lambda: orchestrator_engine.datetime.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S"),
    patch_clock=lambda: setattr(orchestrator_engine, "datetime", _frozen_datetime_module()),
    unpatch_clock=lambda: setattr(orchestrator_engine, "datetime", _orig_orchestrator_engine_datetime),
)
check(
    "orchestrator_engine SAME-SECOND: real datetime module binding restored after the frozen-clock case",
    orchestrator_engine.datetime is _orig_orchestrator_engine_datetime is _dt_module,
)


# ============================================================
# 7) Production data invariance.
# ============================================================

check("production data/ tree is BYTE-FOR-BYTE unchanged after this suite", snapshot_tree(REAL_DATA_DIR) == _real_data_before)
check("tempdir removed (no residue)", not _TMP_ROOT.exists())

print(f"--- test_qa_case_view_generation_mutation_facade_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
