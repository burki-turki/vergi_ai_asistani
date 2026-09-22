# ============================================================
# PILOT READINESS ADIM 4c - RAG PILOT EGRESS GATE ISOLATED TESTS.
#
# Tests the two remaining outbound-LLM gaps closed by this slice (see
# CLAUDE.md's "Pilot Readiness Adım 4c" scope):
#
#   Madde 2+3: `src/rag.py`'s three real network-touching functions
#   (`rewrite_query`/`rerank_candidates`/`generate_answer`) now go
#   through a single, shared, UNCONDITIONAL choke point -
#   `rag._get_client()` - and `src/rag.py`/`src/evaluation.py`/
#   `src/evaluation_v6.py` each refuse cleanly at their own `__main__`
#   entry point (Katman 2, UX/consistency; Katman 1, the function-level
#   gate, is the actual, caller-independent security mechanism proven
#   in Section A below - NOT merely "T06 was mocked").
#
# Section A exercises `src/rag.py`'s function-level gate in-process,
# with the REAL, unpatched `rag` module - never mocking the gate
# itself. Section B proves the three scripts' `__main__` closure with
# REAL OS subprocesses (same discipline as `test_cli_mutate_isolated.
# py`'s `app.py` closure block: `sys.executable`, explicit `cwd`,
# bounded timeout, never `shell=True`, `PYTHONIOENCODING=utf-8`, raw
# bytes + strict UTF-8 decode, poisoned-`anthropic`-on-PYTHONPATH
# import-order proof with a genuine positive control, and a
# `sys.addaudithook`-based network/`.env` guard reusing the OFFICIAL,
# committed `scripts/sweep_env_guard.py` byte-for-byte). Section C is a
# mechanical, repo-wide invariant sweep: across the full `generation`
# `--row-key` universe, `fact_extraction` is the ONLY family that ever
# accepts `--with-agent` during the pilot.
#
# `import rag` (and therefore `import evaluation`/`import evaluation_
# v6`) must succeed WITHOUT `anthropic` installed - this file itself
# depends on that (it runs under the official `production-parity`
# profile, `vergi_ui_runtime`, which does not have `anthropic`
# installed) and Section A/B additionally prove it explicitly.
#
# NO real Anthropic/network call is EVER made anywhere in this file.
#
# Run: python ui/tests/test_rag_pilot_egress_gate_isolated.py
# ============================================================

import contextlib
import io
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

import rag                                                                      # noqa: E402
import evaluation                                                               # noqa: E402
import evaluation_v6                                                            # noqa: E402
from ui.services import agent_generation_mutation_facade as _agf               # noqa: E402
from ui.services import legal_research_case_law_mutation_facade as _lrclf      # noqa: E402
from ui.services import fact_extraction_mutation_facade as _fef                # noqa: E402

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


# ============================================================
# SECTION A - src/rag.py FUNCTION-LEVEL GATE (Katman 1), in-process,
# REAL/unpatched `rag` module (never a mock of the gate itself).
# ============================================================

check(
    "rag module was imported successfully at THIS test file's own module load time, WITHOUT "
    "anthropic being a hard import-time dependency any more (the module no longer does `from "
    "anthropic import Anthropic` at module level)",
    "rag" in sys.modules,
)
check(
    "RagPilotPolicyEgressRefusedError is a plain Exception subclass (rag.py is not a "
    "ui.services module, so it deliberately does NOT join the ApprovalUiError family)",
    issubclass(rag.RagPilotPolicyEgressRefusedError, Exception),
)
check(
    "PILOT_POLICY_EGRESS_REFUSAL_MESSAGE is a non-empty, stable string shared by _get_client() "
    "and the __main__ refusal (single source of truth)",
    isinstance(rag.PILOT_POLICY_EGRESS_REFUSAL_MESSAGE, str)
    and bool(rag.PILOT_POLICY_EGRESS_REFUSAL_MESSAGE.strip()),
)

# --- A1: rag.answer_question(), the T06 shape, DIRECT unpatched call -
#     "don't merely mock T06" proof (acceptance criterion #5).
_T06_HISTORY = [
    {"role": "user", "content": "6736 sayılı Kanunun 5. maddesinin 3. fıkrası ne diyor?"},
    {"role": "assistant", "content": "6736 sayılı Kanunun 5. maddesinin 3. fıkrasını açıklamıştım."},
]

expect_raises(
    rag.RagPilotPolicyEgressRefusedError,
    lambda: rag.answer_question(question="Peki b bendinde ne diyor?", history=_T06_HISTORY),
    "rag.answer_question(question, history=<T06's own non-empty history shape>) - a DIRECT, "
    "unpatched call through the REAL production function, never through evaluation.py - is "
    "REFUSED by the pilot policy gate",
)

# --- A2: rewrite_query, the actual first network-touching function on
#     the answer_question call chain.
expect_raises(
    rag.RagPilotPolicyEgressRefusedError,
    lambda: rag.rewrite_query(question="soru", history=[{"role": "user", "content": "x"}]),
    "rag.rewrite_query(question, non-empty history) is REFUSED",
)
check(
    "rag.rewrite_query(question, empty/None history) still short-circuits BEFORE the gate is "
    "even reached (pre-existing, unrelated `if not history: return question` behaviour, left "
    "completely UNCHANGED by this slice)",
    rag.rewrite_query(question="q", history=[]) == "q"
    and rag.rewrite_query(question="q", history=None) == "q",
)

# --- A3: generate_answer, the LAST network-touching function on the
#     chain (reached only once retrieval succeeds and no deterministic
#     answer applies - i.e. exactly the scenario a future RAG Slice 2
#     activation would produce).
expect_raises(
    rag.RagPilotPolicyEgressRefusedError,
    lambda: rag.generate_answer(
        question="q", context="ctx", temporal_context={}, version_summary={}, provision_context=None,
    ),
    "rag.generate_answer(...) - reached ONLY when retrieval succeeded and no deterministic "
    "provision answer applied - is REFUSED",
)

# --- A4: rerank_candidates. This function wraps its own
#     `client.messages.create(...)` call in a bare `try/except
#     Exception` that falls back to `candidates[:top_k]` - PRE-EXISTING
#     behaviour, entirely unrelated to this slice and left UNTOUCHED.
#     So the gate exception does NOT propagate out of this function;
#     instead this proves the gate was genuinely REACHED (via the
#     function's own RERANK_DEBUG trace, temporarily enabled) and that
#     no real `client.messages.create` call happened (the fallback
#     truncation is the only possible reason for a clean, non-crashing
#     return here).
_original_rerank_debug = rag.RERANK_DEBUG
rag.RERANK_DEBUG = True
try:
    _rerank_candidates_in = [
        {"document_id": f"doc{i}", "text": f"metin {i}"} for i in range(5)
    ]
    _rerank_debug_buf = io.StringIO()
    with contextlib.redirect_stdout(_rerank_debug_buf):
        _rerank_result = rag.rerank_candidates(
            question="q", candidates=_rerank_candidates_in, top_k=3,
        )
    _rerank_debug_out = _rerank_debug_buf.getvalue()
    check(
        "rag.rerank_candidates(...) internally reached the SAME _get_client() gate (visible in "
        "its own RERANK_DEBUG trace as a RagPilotPolicyEgressRefusedError) and fell back to its "
        "PRE-EXISTING, unrelated candidates[:top_k] truncation (its own bare except/fallback, "
        "left UNCHANGED) - proving no real client.messages.create call was ever attempted",
        "RagPilotPolicyEgressRefusedError" in _rerank_debug_out
        and _rerank_result == _rerank_candidates_in[:3],
        f"debug_out={_rerank_debug_out!r} result_matches_fallback="
        f"{_rerank_result == _rerank_candidates_in[:3]!r}",
    )
finally:
    rag.RERANK_DEBUG = _original_rerank_debug

# --- A5: "RAG Slice 2 simulation" - positive control proving the
#     closure is NOT accidental (not merely a side effect of
#     RagBundleNotPinnedError). `retrieve_candidates` is monkeypatched
#     (in THIS isolated test process only) to simulate a FULLY
#     successful retrieval (as a future RAG Slice 2 activation would
#     produce) - `answer_question` is then called with the SAME empty-
#     history shape `__main__` itself uses. Even with retrieval never
#     touching `RagBundleNotPinnedError` at all, the pilot policy gate
#     still stops the chain (proven above to be reached from
#     generate_answer once rerank_candidates's own fallback keeps
#     candidates non-empty and the deterministic provision-answer
#     builders decline to answer - the same call chain acceptance
#     criterion #6 requires).
_original_retrieve_candidates = rag.retrieve_candidates


def _fake_successful_retrieve_candidates(search_query, metadata, temporal_context):
    return {
        "candidates": [
            {
                "document_id": f"doc{i}",
                "belge_turu": "Kanun",
                "title": "Sentetik Test Başlığı",
                "kanun_no": "123",
                "madde": "1",
                "fikra": "1",
                "bent": "a",
                "version": "v1",
                "version_selection_status": "selected",
                "temporal_result": "valid",
                "authority_level": 1,
                "final_score": 0.9,
                "text": f"sentetik metin {i}",
            }
            for i in range(5)
        ],
        "failure_reason": None,
        "retriever_failure_reason": None,
        "version_selection": {},
    }


rag.retrieve_candidates = _fake_successful_retrieve_candidates
try:
    try:
        rag.answer_question(question="RAG Slice 2 simülasyon sorusu", history=[])
    except rag.RagPilotPolicyEgressRefusedError:
        check(
            "RAG SLICE 2 SIMULATION: with retrieve_candidates monkeypatched to a FULLY "
            "successful, non-empty retrieval (bundle-pinning never even consulted), "
            "answer_question(question, history=[]) is STILL refused by the pilot policy gate - "
            "this is NOT an accident of RagBundleNotPinnedError, the gate is caller-/"
            "retrieval-outcome-independent",
            True,
        )
    except Exception as error:  # noqa: BLE001
        check(
            "RAG SLICE 2 SIMULATION: answer_question is refused by the pilot policy gate even "
            "with a simulated successful retrieval",
            False, f"wrong exception: {type(error).__name__}: {error}",
        )
    else:
        check(
            "RAG SLICE 2 SIMULATION: answer_question is refused by the pilot policy gate even "
            "with a simulated successful retrieval",
            False, "no exception raised at all",
        )
finally:
    rag.retrieve_candidates = _original_retrieve_candidates

check(
    "RAG SLICE 2 SIMULATION cleanup: retrieve_candidates was restored to the REAL production "
    "function after the monkeypatch",
    rag.retrieve_candidates is _original_retrieve_candidates,
)

# --- A6: poisoned-`anthropic` import-order proof (same technique as
#     `test_cli_mutate_isolated.py`'s `app.py` closure block) - proves
#     the gate fires BEFORE any lazy anthropic import could ever be
#     attempted, with a genuine positive control.
_poison_dir_a = tempfile.mkdtemp(prefix="step4c_poison_a_")
try:
    (Path(_poison_dir_a) / "anthropic.py").write_text(
        'raise RuntimeError("STEP4C_POISONED_ANTHROPIC_IMPORTED")\n', encoding="utf-8",
    )

    _poisoned_env_a = os.environ.copy()
    _poisoned_env_a["PYTHONIOENCODING"] = "utf-8"
    _inherited_pp_a = _poisoned_env_a.get("PYTHONPATH", "")
    _poisoned_env_a["PYTHONPATH"] = (
        f"{_poison_dir_a}{os.pathsep}{_inherited_pp_a}" if _inherited_pp_a else _poison_dir_a
    )

    _control_a = subprocess.run(
        [sys.executable, "-c", "import anthropic"],
        cwd=str(REPO_ROOT), capture_output=True, stdin=subprocess.DEVNULL,
        timeout=90, env=_poisoned_env_a,
    )
    _control_a_stderr = _control_a.stderr.decode("utf-8") if _control_a.stderr else ""
    check(
        "POSITIVE CONTROL: with the poisoned PYTHONPATH, a child that DELIBERATELY does `import "
        "anthropic` really does fail with the stub's RuntimeError - the shadowing is genuinely "
        "effective, so the import-order proof below is not vacuous",
        _control_a.returncode != 0 and "STEP4C_POISONED_ANTHROPIC_IMPORTED" in _control_a_stderr,
        f"returncode={_control_a.returncode!r} stderr={_control_a_stderr!r}",
    )

    _gate_probe_code = (
        "import sys\n"
        f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
        "import rag\n"
        "try:\n"
        "    rag.answer_question(\n"
        "        question='q',\n"
        "        history=[\n"
        "            {'role': 'user', 'content': 'x'},\n"
        "            {'role': 'assistant', 'content': 'y'},\n"
        "        ],\n"
        "    )\n"
        "except rag.RagPilotPolicyEgressRefusedError:\n"
        "    print('GATE_FIRED_BEFORE_ANTHROPIC')\n"
        "except Exception as error:\n"
        "    print('WRONG_EXCEPTION', type(error).__name__, error)\n"
        "else:\n"
        "    print('NO_EXCEPTION')\n"
    )

    _probe_a = subprocess.run(
        [sys.executable, "-c", _gate_probe_code],
        cwd=str(REPO_ROOT), capture_output=True, stdin=subprocess.DEVNULL,
        timeout=90, env=_poisoned_env_a,
    )
    _probe_a_stdout = _probe_a.stdout.decode("utf-8") if _probe_a.stdout else ""
    _probe_a_stderr = _probe_a.stderr.decode("utf-8") if _probe_a.stderr else ""
    check(
        "IMPORT-ORDER PROOF: with a poisoned `anthropic` FIRST on PYTHONPATH, `import rag` "
        "still succeeds and rag.answer_question(...) is refused by OUR gate - not by the "
        "poisoned stub's RuntimeError - proving _get_client()'s unconditional refusal is "
        "reached before any anthropic import could ever be attempted",
        _probe_a.returncode == 0 and _probe_a_stdout.strip() == "GATE_FIRED_BEFORE_ANTHROPIC"
        and "STEP4C_POISONED_ANTHROPIC_IMPORTED" not in _probe_a_stdout
        and "STEP4C_POISONED_ANTHROPIC_IMPORTED" not in _probe_a_stderr
        and "Traceback" not in _probe_a_stderr,
        f"returncode={_probe_a.returncode!r} stdout={_probe_a_stdout!r} stderr={_probe_a_stderr!r}",
    )
finally:
    shutil.rmtree(_poison_dir_a, ignore_errors=True)


# ============================================================
# SECTION B - REAL OS SUBPROCESS CLOSURE PROOFS (`__main__`, Katman 2).
# ============================================================

_EXPECTED_MESSAGE_BY_MODULE = {
    "rag": rag.PILOT_POLICY_EGRESS_REFUSAL_MESSAGE,
    "evaluation": evaluation.PILOT_POLICY_EGRESS_REFUSAL_MESSAGE,
    "evaluation_v6": evaluation_v6.PILOT_POLICY_EGRESS_REFUSAL_MESSAGE,
}


def _run_src_script(module_name, *, extra_pythonpath=None, timeout=90):
    """Same discipline as `test_cli_mutate_isolated.py`'s
    `_run_legacy_script()`: a real subprocess, an EXPLICIT, deterministic
    child environment (a full copy of the parent's own `os.environ` so
    PostgreSQL DSN variables and everything else the child might need
    survive unchanged), `PYTHONIOENCODING=utf-8` pinned regardless of the
    parent's ambient locale, raw bytes captured (never `text=True`) and
    decoded STRICTLY (a decode failure is itself a genuine signal, never
    silently substituted with U+FFFD)."""
    script_path = SRC_DIR / f"{module_name}.py"
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    if extra_pythonpath is not None:
        inherited = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = (
            f"{extra_pythonpath}{os.pathsep}{inherited}" if inherited else str(extra_pythonpath)
        )
    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        env=child_env,
    )
    stdout_text = completed.stdout.decode("utf-8") if completed.stdout else ""
    stderr_text = completed.stderr.decode("utf-8") if completed.stderr else ""
    return script_path, types.SimpleNamespace(
        returncode=completed.returncode,
        stdout=stdout_text,
        stderr=stderr_text.replace("\r\n", "\n"),
    )


for _module_name in ("rag", "evaluation", "evaluation_v6"):
    _expected_message = _EXPECTED_MESSAGE_BY_MODULE[_module_name]

    _script_path, _result = _run_src_script(_module_name)
    check(
        f"{_module_name}.py: the real script file exists at the expected src/ path "
        f"({_script_path})",
        _script_path.is_file(),
        f"resolved path: {_script_path}",
    )
    check(
        f"{_module_name}.py: real OS subprocess returncode is exactly 2 (the genuine process "
        "exit code SystemExit(2) produces, not merely a Python-level return value)",
        _result.returncode == 2,
        f"got returncode={_result.returncode!r} stdout={_result.stdout!r} stderr={_result.stderr!r}",
    )
    check(
        f"{_module_name}.py: stderr is EXACTLY the fixed Adım 4c refusal message (the SAME "
        "string the module exposes as PILOT_POLICY_EGRESS_REFUSAL_MESSAGE - single source of "
        "truth)",
        _result.stderr == _expected_message + "\n",
        f"stderr={_result.stderr!r}",
    )
    check(
        f"{_module_name}.py: stderr contains no 'Traceback' - a clean, deliberate SystemExit(2), "
        "never an unhandled exception",
        "Traceback" not in _result.stderr,
        f"stderr={_result.stderr!r}",
    )
    check(
        f"{_module_name}.py: stdout is completely empty - no test/question output was ever "
        "printed before the refusal fired",
        _result.stdout == "",
        f"stdout={_result.stdout!r}",
    )

    # --- SAME result with a poisoned `anthropic` shadowing the real
    #     package - proves the closure is anthropic-install-independent
    #     (identical result whether anthropic is present, absent, or
    #     actively broken).
    _poison_dir_b = tempfile.mkdtemp(prefix=f"step4c_poison_b_{_module_name}_")
    try:
        (Path(_poison_dir_b) / "anthropic.py").write_text(
            'raise RuntimeError("STEP4C_POISONED_ANTHROPIC_IMPORTED")\n', encoding="utf-8",
        )
        _script_path_p, _result_p = _run_src_script(_module_name, extra_pythonpath=_poison_dir_b)
        check(
            f"{_module_name}.py WITH A POISONED `anthropic` FIRST ON PYTHONPATH: IDENTICAL "
            "refusal (exit 2, exact fixed message, no traceback, empty stdout, no poisoned-stub "
            "text anywhere) - the closure does not depend on anthropic being importable at all",
            _result_p.returncode == 2
            and _result_p.stderr == _expected_message + "\n"
            and _result_p.stdout == ""
            and "Traceback" not in _result_p.stderr
            and "STEP4C_POISONED_ANTHROPIC_IMPORTED" not in _result_p.stdout
            and "STEP4C_POISONED_ANTHROPIC_IMPORTED" not in _result_p.stderr,
            f"returncode={_result_p.returncode!r} stdout={_result_p.stdout!r} "
            f"stderr={_result_p.stderr!r}",
        )
    finally:
        shutil.rmtree(_poison_dir_b, ignore_errors=True)


# ------------------------------------------------------------
# NETWORK/`.env` GUARD - reuses the OFFICIAL, committed
# `scripts/sweep_env_guard.py` byte-for-byte (the exact same source the
# official `scripts/run_ui_tests.py` sweep runner copies to
# `<run>/guard/sitecustomize.py` in every child it starts), independent
# of this file's own poisoned-PYTHONPATH mechanism above.
# ------------------------------------------------------------

_GUARD_SOURCE_PATH = REPO_ROOT / "scripts" / "sweep_env_guard.py"


_SWEEP_GUARD_LEDGER_ENV = "VERGI_UI_TEST_SWEEP_GUARD_LEDGER"
_SWEEP_GUARD_RUN_ID_ENV = "VERGI_UI_TEST_SWEEP_RUN_ID"


def _child_own_ledger_lines(ledger_text, run_id, child_pid):
    """Filter a (possibly shared, multi-process, multi-module) guard ledger
    file's lines down to only the ones that belong to THIS run and THIS
    child: a ``GUARD_ARMED`` line whose own pid OR ppid equals `child_pid`
    (venv-launcher indirection - the launcher pid is `Popen.pid` and the
    real interpreter is its child, the SAME convention
    `scripts/run_ui_tests.py`'s own ``module_guard_armed()`` uses), or an
    ``ENV_OPEN_BLOCKED``/``NET_BLOCKED``/``POPEN`` line whose own pid
    equals `child_pid` - in every case ALSO requiring the line's own
    `run_id` field to equal `run_id`, so a stale line from an unrelated,
    earlier sweep that happens to share the same ledger path (or an
    unrelated pid collision) can never be mistaken for this child's own
    event. Malformed/foreign lines are ignored, never raised - this is a
    defensive, read-only filter over a file this function does not own,
    truncate or otherwise mutate; matches the tab-separated line formats
    documented at the top of ``scripts/sweep_env_guard.py``."""
    own = []
    for line in ledger_text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        kind = parts[0]
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        if kind == "GUARD_ARMED":
            if len(parts) < 4 or parts[3] != run_id:
                continue
            try:
                ppid = int(parts[2])
            except ValueError:
                ppid = None
            if pid == child_pid or ppid == child_pid:
                own.append(line)
        elif kind in ("ENV_OPEN_BLOCKED", "NET_BLOCKED", "POPEN"):
            if len(parts) < 3 or parts[2] != run_id:
                continue
            if pid == child_pid:
                own.append(line)
    return own


def _run_src_script_with_env_guard(module_name, *, timeout=90):
    """Same closure proof as `_run_src_script()` above, PLUS a real
    network/`.env` guard verification for this one child process.

    Two mutually exclusive branches, chosen ONCE per call by inspecting
    THIS process's own environment for an already-armed, inherited sweep
    guard:

    * INSIDE an official sweep (`scripts/run_ui_tests.py` already armed a
      guard in THIS process's own environment - with the SWEEP's own
      ledger path and run id - before this test module even started):
      minting a brand-new, private ledger/run-id here (as the standalone
      branch below does) would make the CHILD's own `GUARD_ARMED` event
      land in that private ledger/run-id while the `subprocess.Popen`
      call itself is still recorded (correctly, by the guard already
      armed in THIS process) in the SWEEP's own ledger under the SWEEP's
      own run id - exactly the `GUARD_INHERITANCE_MISMATCH` integrity
      failure `scripts/run_ui_tests.py`'s own `guard_accounting()` checks
      for (armed count falling short of expected by one per env-guarded
      child). So in this branch PYTHONPATH and the ledger/run-id env vars
      are NOT overridden at all - they are inherited completely
      unchanged, exactly the way `_run_src_script()`'s plain
      `os.environ.copy()` already does correctly for the other 8 of the
      11 subprocess calls in this file. Because the ledger is then the
      SWEEP's own, shared file (other modules' events may already be in
      it, or may be appended concurrently by sibling processes), this
      branch captures the child's real OS pid via `subprocess.Popen`
      (`subprocess.run`'s `CompletedProcess` does not expose it) and
      filters the ledger down to only this child's own events
      (`_child_own_ledger_lines()`) before returning - this test's own
      NET_BLOCKED/ENV_OPEN_BLOCKED/GUARD_ARMED assertions below must look
      only at their own three children, never at the whole shared file.
    * STANDALONE (no guard is armed/inherited in THIS process's own
      environment - e.g. `python ui/tests/test_rag_pilot_egress_gate_
      isolated.py` run directly, outside any sweep): the original,
      self-sufficient design is UNCHANGED - a brand-new, private,
      temporary guard directory + ledger + run id is minted so the test
      remains fully self-contained with zero dependency on
      `scripts/run_ui_tests.py` ever having run.
    """
    inherited_ledger = os.environ.get(_SWEEP_GUARD_LEDGER_ENV)
    inherited_run_id = os.environ.get(_SWEEP_GUARD_RUN_ID_ENV)
    script_path = SRC_DIR / f"{module_name}.py"

    if inherited_ledger and inherited_run_id:
        # Running INSIDE an already-armed sweep - reuse its guard exactly
        # as-is, the same way `_run_src_script()` already does.
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=child_env,
        )
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        child_pid = proc.pid
        ledger_lines = []
        ledger_file = Path(inherited_ledger)
        if ledger_file.exists():
            ledger_text = ledger_file.read_text(encoding="utf-8", errors="replace")
            ledger_lines = _child_own_ledger_lines(ledger_text, inherited_run_id, child_pid)
        stdout_text = stdout_bytes.decode("utf-8") if stdout_bytes else ""
        stderr_text = stderr_bytes.decode("utf-8") if stderr_bytes else ""
        return types.SimpleNamespace(
            returncode=proc.returncode,
            stdout=stdout_text,
            stderr=stderr_text.replace("\r\n", "\n"),
            ledger_lines=ledger_lines,
        )

    # Standalone (no inherited sweep guard) - original, self-sufficient
    # private ledger/run-id behaviour, UNCHANGED.
    guard_dir = tempfile.mkdtemp(prefix=f"step4c_envguard_{module_name}_")
    try:
        guard_source = _GUARD_SOURCE_PATH.read_bytes()
        (Path(guard_dir) / "sitecustomize.py").write_bytes(guard_source)
        ledger_path = Path(guard_dir) / "ledger.tsv"
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONNOUSERSITE"] = "1"
        inherited = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = f"{guard_dir}{os.pathsep}{inherited}" if inherited else guard_dir
        child_env[_SWEEP_GUARD_LEDGER_ENV] = str(ledger_path)
        child_env[_SWEEP_GUARD_RUN_ID_ENV] = f"step4c_{module_name}"
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            env=child_env,
        )
        ledger_lines = []
        if ledger_path.exists():
            ledger_lines = ledger_path.read_text(encoding="utf-8", errors="replace").splitlines()
        stdout_text = completed.stdout.decode("utf-8") if completed.stdout else ""
        stderr_text = completed.stderr.decode("utf-8") if completed.stderr else ""
        return types.SimpleNamespace(
            returncode=completed.returncode,
            stdout=stdout_text,
            stderr=stderr_text.replace("\r\n", "\n"),
            ledger_lines=ledger_lines,
        )
    finally:
        shutil.rmtree(guard_dir, ignore_errors=True)


check(
    "the committed scripts/sweep_env_guard.py source file exists and is used byte-for-byte "
    "below (never re-implemented/duplicated)",
    _GUARD_SOURCE_PATH.is_file(),
)

for _module_name in ("rag", "evaluation", "evaluation_v6"):
    _guarded = _run_src_script_with_env_guard(_module_name)
    check(
        f"{_module_name}.py ENV-GUARDED run: SAME refusal as the unguarded run above (exit 2, "
        "exact fixed message)",
        _guarded.returncode == 2 and _guarded.stderr == _EXPECTED_MESSAGE_BY_MODULE[_module_name] + "\n",
        f"returncode={_guarded.returncode!r} stderr={_guarded.stderr!r}",
    )
    check(
        f"{_module_name}.py ENV-GUARDED run: the guard genuinely armed in the child process "
        "(a GUARD_ARMED ledger line was written)",
        any(line.startswith("GUARD_ARMED") for line in _guarded.ledger_lines),
        f"ledger={_guarded.ledger_lines!r}",
    )
    check(
        f"{_module_name}.py ENV-GUARDED run: ZERO non-loopback network connection attempts "
        "(no NET_BLOCKED ledger line)",
        not any(line.startswith("NET_BLOCKED") for line in _guarded.ledger_lines),
        f"ledger={_guarded.ledger_lines!r}",
    )
    check(
        f"{_module_name}.py ENV-GUARDED run: ZERO `.env*` open attempts (no ENV_OPEN_BLOCKED "
        "ledger line)",
        not any(line.startswith("ENV_OPEN_BLOCKED") for line in _guarded.ledger_lines),
        f"ledger={_guarded.ledger_lines!r}",
    )


# ============================================================
# SECTION C - GLOBAL INVARIANT: across the WHOLE `generation`
# `--row-key` universe (agent_generation's 5 families + legal_research_
# case_law's 2 families + fact_extraction itself), fact_extraction is
# the ONLY family that ever accepts `--with-agent` with the PRODUCTION
# client during the pilot.
# ============================================================

_AGENT_GENERATION_ALL = set(_agf.AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME.keys())
_AGENT_GENERATION_CLOSED = (
    _agf.AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS
    | _agf.AGENT_GENERATION_PILOT_POLICY_REFUSED_ROW_KEYS
)
check(
    "agent_generation_mutation_facade: the union of the raw-text (Adım 4b) and pilot-policy "
    "(Adım 4c) refused sets is EXACTLY the full five-family universe - zero open families remain",
    _AGENT_GENERATION_CLOSED == _AGENT_GENERATION_ALL,
    f"union={sorted(_AGENT_GENERATION_CLOSED)!r} universe={sorted(_AGENT_GENERATION_ALL)!r}",
)
check(
    "agent_generation_mutation_facade: the two refused sets are pairwise DISJOINT - no row_key "
    "is refused twice with two different (and therefore ambiguous) messages",
    _agf.AGENT_GENERATION_RAW_TEXT_REFUSED_ROW_KEYS.isdisjoint(
        _agf.AGENT_GENERATION_PILOT_POLICY_REFUSED_ROW_KEYS
    ),
)

_LRCL_ALL = set(_lrclf.LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME.keys())
_LRCL_CLOSED = (
    _lrclf.LEGAL_RESEARCH_CASE_LAW_RAW_TEXT_REFUSED_ROW_KEYS
    | _lrclf.LEGAL_RESEARCH_CASE_LAW_PILOT_POLICY_REFUSED_ROW_KEYS
)
check(
    "legal_research_case_law_mutation_facade: the union of the raw-text (Adım 4b) and "
    "pilot-policy (Adım 4c) refused sets is EXACTLY the full two-family universe",
    _LRCL_CLOSED == _LRCL_ALL,
    f"union={sorted(_LRCL_CLOSED)!r} universe={sorted(_LRCL_ALL)!r}",
)
check(
    "legal_research_case_law_mutation_facade: the two refused sets are pairwise DISJOINT",
    _lrclf.LEGAL_RESEARCH_CASE_LAW_RAW_TEXT_REFUSED_ROW_KEYS.isdisjoint(
        _lrclf.LEGAL_RESEARCH_CASE_LAW_PILOT_POLICY_REFUSED_ROW_KEYS
    ),
)

_FACT_EXTRACTION_ALL = set(_fef.FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME.keys())
check(
    "fact_extraction_mutation_facade: exactly {'fact_extraction'} - unchanged by this slice, "
    "the sole family whose agent mode remains reachable during the pilot",
    _FACT_EXTRACTION_ALL == {"fact_extraction"},
    f"got: {sorted(_FACT_EXTRACTION_ALL)}",
)

_WHOLE_GENERATION_WITH_AGENT_UNIVERSE = _AGENT_GENERATION_ALL | _LRCL_ALL | _FACT_EXTRACTION_ALL
_WHOLE_GENERATION_CLOSED = _AGENT_GENERATION_CLOSED | _LRCL_CLOSED
_WHOLE_GENERATION_OPEN = _WHOLE_GENERATION_WITH_AGENT_UNIVERSE - _WHOLE_GENERATION_CLOSED

check(
    "GLOBAL PILOT INVARIANT: across the entire `generation --row-key` --with-agent-capable "
    "universe (agent_generation's 5 + legal_research_case_law's 2 + fact_extraction's own 1 = "
    "8 families), fact_extraction is the ONE AND ONLY family left open - every other family "
    "unconditionally refuses --with-agent with the production client",
    _WHOLE_GENERATION_OPEN == {"fact_extraction"},
    f"open families (expected exactly {{'fact_extraction'}}): {sorted(_WHOLE_GENERATION_OPEN)!r}",
)
check(
    "GLOBAL PILOT INVARIANT: the full universe has exactly 8 members (5 + 2 + 1, no overlap "
    "between agent_generation's and legal_research_case_law's own row_key namespaces)",
    len(_WHOLE_GENERATION_WITH_AGENT_UNIVERSE) == 8
    and _AGENT_GENERATION_ALL.isdisjoint(_LRCL_ALL)
    and _AGENT_GENERATION_ALL.isdisjoint(_FACT_EXTRACTION_ALL)
    and _LRCL_ALL.isdisjoint(_FACT_EXTRACTION_ALL),
    f"universe={sorted(_WHOLE_GENERATION_WITH_AGENT_UNIVERSE)!r} "
    f"(agent_generation={sorted(_AGENT_GENERATION_ALL)!r}, legal_research_case_law="
    f"{sorted(_LRCL_ALL)!r}, fact_extraction={sorted(_FACT_EXTRACTION_ALL)!r})",
)


print(f"--- test_rag_pilot_egress_gate_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
