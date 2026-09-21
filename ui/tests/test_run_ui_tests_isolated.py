# ============================================================
# PILOT READINESS ADIM 3 - Runner / Environment / Skip Reporting:
# isolated regression suite for scripts/run_ui_tests.py and
# scripts/sweep_env_guard.py (Fable FINAL contract section T.1).
#
# WHAT THIS PROVES (no PostgreSQL; real subprocesses, real Windows Job
# Objects, real guard shim, real private-DACL run directories):
#   1.  the output parser (G.2) on every real summary format, foreign
#       summary names, last-line selection, embedded grandchild output,
#       lowercase "not counted", strict UTF-8;
#   2.  zero-check classification and the profile rule;
#   3.  exit-code authority over summary text;
#   4.  raw PASS/FAIL and SKIPPED tally cross-checks;
#   5.  crash-mid-run;
#   6.  timeout kills the WHOLE process tree (grandchild dead, job
#       accounting zero); escaped-tree accounting -> exit 3;
#   7.  spawn failure;
#   8.  guard positive controls, shim corruption, -I inheritance
#       mismatch, .env* blocking, suspicious subprocess, ledger format;
#   9.  environment allowlist/denylist/runner-set contract (J);
#   10. capability profiles (K);
#   11. PostgreSQL syntactic contract (L.1/L.2/L.4);
#   12. discovery reconciliation, reparse-point rejection, ordering,
#       git-absent behaviour, recursion lock (M);
#   13. output-root refusal inside the repository (real path + junction),
#       exclusive suffixing, atomic report replace, no env values in JSON;
#   14. private DACL on the run directory (ctypes + independent icacls);
#   15. bytecode residue handling (pre-existing kept, new removed);
#   16. protected-path diff -> exit 3, never reverted by the runner;
#   17. secret scan -> exit 3, classes only;
#   18. concurrent-sweep refusal (pure);
#   19. paths with spaces;
#   20. abort semantics (ABORTED label, exit 130);
#   21. console labels (DIAGNOSTIC / PARTIAL / FULL / RAG_*);
#   22. import hygiene of runner and guard;
#   23. byte-invariance of data/, index/ and ui/tests; temp cleanup;
#   24. B1: Windows .env name folding (case, trailing dot/space, NTFS
#       stream, drive-relative) pure + real guard-child behaviour;
#   25. B2: Job containment -- Ctrl-C cleanup with a live grandchild,
#       assignment-failure kill + stop, Ctrl-C INSIDE the assignment step
#       (never-member suspended child killed directly, no leak, no 30 s
#       wait), containment-failed module excluded from the guard root
#       count, creation-failure refusal, no further module spawned,
#       partial report on abort; B2-R1: creation failure on the SECOND
#       module through the real main() in a driver subprocess -> exit 3,
#       fail-class outcome + integrity failure, sweep STOPPED, post-run
#       evidence present, module never spawned; first-module failure stays
#       a refusal (exit 2) -- both proven end-to-end;
#   26. B3: rag gate K.1 exact (informational skips across ALL modules);
#   27. B4: case-insensitive suspicious subprocess patterns, pure + nested;
#   28. B5: static value-leak regression on T.2 (B5-R1 structural AST rule:
#       one spawn_and_scan() helper scanning in `finally`, the raw spawner
#       called exactly once inside it, no other subprocess path) and runner
#       refusal texts; B5-R1 fail-path proofs: the REAL T.2 run as a
#       subprocess against a fake psycopg raising sentinel-laden errors --
#       before any nested runner and after one -- exits 1 with a redacted
#       FAIL, no traceback, and no sentinel db/user/password/maintenance-db/
#       port value anywhere in its stdout/stderr (the nested run's
#       report/ledger/logs are covered by T.2's own scan line).
#
# SAFETY: every nested runner is pointed at a FAKE module directory
# (--tests-dir) so the real ui/tests discovery is never triggered from
# here (recursion-safe); every temp directory is removed in `finally`.
# The guard inheritance variables of a parent sweep are always passed
# through to nested runners so a parent sweep's ledger accounting stays
# balanced.
#
# Run: python -m ui.tests.test_run_ui_tests_isolated
# ============================================================

import ast
import ctypes
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from argparse import Namespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.run_ui_tests as runner  # noqa: E402

RUNNER_PATH = REPO_ROOT / "scripts" / "run_ui_tests.py"
GUARD_PATH = REPO_ROOT / "scripts" / "sweep_env_guard.py"
IS_WIN = sys.platform == "win32"
MODULE_NAME = "test_run_ui_tests_isolated"

INHERIT_GUARD_KEYS = (
    "PYTHONPATH", "PYTHONNOUSERSITE", runner.GUARD_LEDGER_ENV, runner.GUARD_RUN_ID_ENV,
    runner.GUARD_PARENT_PID_ENV,
)

passed = 0
failed = 0
informational_skips = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def skip_info(label, detail=""):
    global informational_skips
    informational_skips += 1
    print(f"SKIPPED {label} - {detail} (NOT counted as pass/fail)")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def tree_manifest(root):
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _on_rm_error(func, path, exc):
    # git object files are read-only; make them writable and retry once.
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)
    except OSError:
        pass


def rmtree_retry(path, attempts=20):
    for i in range(attempts):
        try:
            shutil.rmtree(path, onexc=_on_rm_error)
        except FileNotFoundError:
            return True
        except OSError:
            pass
        if not os.path.exists(path):
            return True
        time.sleep(0.25)
    return not os.path.exists(path)


def write_module(dirpath, name, source):
    (Path(dirpath) / f"{name}.py").write_text(source, encoding="utf-8", newline="\n")


def spawn_runner(args, extra_env=None, base_env=None, timeout=600, cwd=None, script=None):
    env = dict(os.environ if base_env is None else base_env)
    for key in INHERIT_GUARD_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]
        else:
            env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_env:
        for k, v in extra_env.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
    argv = [sys.executable, str(script or RUNNER_PATH)] + [str(a) for a in args]
    r = subprocess.run(argv, cwd=str(cwd or REPO_ROOT), env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def find_run_dir(output_root):
    root = Path(output_root)
    if not root.exists():
        return None
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("sweep_"))
    return dirs[-1] if dirs else None


def load_report(run_dir):
    return json.loads((Path(run_dir) / "report.json").read_text(encoding="utf-8"))


def last_line(text):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def module_entry(report, name):
    for m in report["modules"]:
        if m["name"] == name:
            return m
    return None


def process_alive(pid):
    if not IS_WIN:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    h = k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
        return code.value == 259
    finally:
        k.CloseHandle(ctypes.c_void_p(h))


def make_junction(link, target):
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, timeout=60)
    return r.returncode == 0


def remove_junction(link):
    try:
        os.rmdir(link)
    except OSError:
        pass


class FakeSweepArgs(Namespace):
    pass


def make_args(**kw):
    base = dict(profile="developer", module_timeout=60.0, output_root=None, select=None, tests_dir=None, allow_untracked=False)
    base.update(kw)
    return FakeSweepArgs(**base)


# fake module sources -------------------------------------------------------

SRC_OK = "print('PASS one')\nprint('PASS two')\nprint('--- {n}: 2 passed, 0 failed ---')\nimport sys; sys.exit(0)\n"
SRC_DOC_SKIP = "print('SKIPPED no database - detail')\nprint('--- {n}: 0 passed, 0 failed, 1 skipped ---')\nimport sys; sys.exit(0)\n"
SRC_ROUTE_SKIP = "print('SKIPPED: fastapi is not installed; skipping')\nimport sys; sys.exit(0)\n"
SRC_UNDOC = "import sys; sys.exit(0)\n"
SRC_FAIL = "print('PASS a')\nprint('FAIL b boom')\nprint('TOTAL: 1 passed, 1 failed')\nimport sys; sys.exit(1)\n"
SRC_EXIT1_ZERO_FAILED = "print('PASS a')\nprint('PASS b')\nprint('--- {n}: 2 passed, 0 failed ---')\nimport sys; sys.exit(1)\n"
SRC_CONTRADICTION = "print('PASS a')\nprint('FAIL b x')\nprint('FAIL c y')\nprint('--- {n}: 1 passed, 2 failed ---')\nimport sys; sys.exit(0)\n"
SRC_TALLY = "print('PASS a')\nprint('PASS b')\nprint('--- {n}: 3 passed, 0 failed ---')\nimport sys; sys.exit(0)\n"
SRC_SKIP_TALLY = "print('PASS a')\nprint('SKIPPED one - x')\nprint('--- {n}: 1 passed, 0 failed, 2 skipped ---')\nimport sys; sys.exit(0)\n"
SRC_CRASH = "print('PASS a', flush=True)\nprint('PASS b', flush=True)\nraise RuntimeError('boom')\n"
SRC_TIMEOUT = (
    "import subprocess, sys, time\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
    "print('GRANDCHILD', p.pid, flush=True)\n"
    "time.sleep(600)\n"
)
SRC_ISOLATED_CHILD = (
    "import subprocess, sys\n"
    "r = subprocess.run([sys.executable, '-I', '-c', 'pass'])\n"
    "print('PASS spawned isolated child rc=%d' % r.returncode)\n"
    "print('--- {n}: 1 passed, 0 failed ---')\nsys.exit(0)\n"
)
SRC_CURL_TOKEN = (
    "import subprocess, sys\n"
    "r = subprocess.run([sys.executable, '-c', 'pass', 'curl'])\n"
    "print('PASS spawned with curl token rc=%d' % r.returncode)\n"
    "print('--- {n}: 1 passed, 0 failed ---')\nsys.exit(0)\n"
)
SRC_GRANDCHILD_OK = (
    "import subprocess, sys\n"
    "r = subprocess.run([sys.executable, '-c', 'pass'])\n"
    "print('PASS spawned guarded child rc=%d' % r.returncode)\n"
    "print('--- {n}: 1 passed, 0 failed ---')\nsys.exit(0)\n"
)
SRC_ENV_DUMP = (
    "import os, sys\n"
    "for k in sorted(os.environ):\n"
    "    print('ENVNAME ' + k)\n"
    "print('PASS env names dumped')\n"
    "print('--- {n}: 1 passed, 0 failed ---')\nsys.exit(0)\n"
)
SRC_ENV_BLOCK = (
    "import os, sys\n"
    "here = os.getcwd()\n"
    "for idx, name in enumerate(('.env', '.env.local', '.envx')):\n"
    "    staging = os.path.join(here, 'decoy_%d' % idx)\n"
    "    with open(staging, 'wb') as f:\n"
    "        f.write(b'x')\n"
    "    os.replace(staging, os.path.join(here, name))\n"
    "def blocked(name):\n"
    "    try:\n"
    "        open(os.path.join(here, name), 'rb').close()\n"
    "    except PermissionError:\n"
    "        return True\n"
    "    return False\n"
    "print('PASS env blocked' if blocked('.env') else 'FAIL env not blocked')\n"
    "print('PASS env.local blocked' if blocked('.env.local') else 'FAIL env.local not blocked')\n"
    "print('PASS envx allowed' if not blocked('.envx') else 'FAIL envx blocked')\n"
    "print('--- {n}: 3 passed, 0 failed ---')\nsys.exit(0)\n"
)
SRC_ENV_CASE = (
    "import os, sys\n"
    "here = os.getcwd()\n"
    "for idx, name in enumerate(('.env', '.env.local')):\n"
    "    staging = os.path.join(here, 'decoy_%d' % idx)\n"
    "    with open(staging, 'wb') as f:\n"
    "        f.write(b'x')\n"
    "    os.replace(staging, os.path.join(here, name))\n"
    "for name in ('.envx', '.environment'):\n"
    "    with open(os.path.join(here, name), 'wb') as f:\n"
    "        f.write(b'x')\n"
    "def blocked(name):\n"
    "    try:\n"
    "        open(os.path.join(here, name), 'rb').close()\n"
    "    except PermissionError:\n"
    "        return True\n"
    "    except OSError:\n"
    "        return None\n"
    "    return False\n"
    "n = 0\n"
    "for name in ('.ENV', '.Env', '.env.', '.env ', '.Env.local', '.ENV.LOCAL', '.env.production', '.env::$DATA', '.env.local.'):\n"
    "    b = blocked(name)\n"
    "    print(('PASS blocked %r' % name) if b is True else ('FAIL not blocked %r (%r)' % (name, b)))\n"
    "    n += 1\n"
    "for name in ('.envx', '.environment'):\n"
    "    b = blocked(name)\n"
    "    print(('PASS allowed %r' % name) if b is False else ('FAIL blocked or unreadable %r (%r)' % (name, b)))\n"
    "    n += 1\n"
    "print('--- {n}: %d passed, 0 failed ---' % n)\n"
    "sys.exit(0)\n"
)
SRC_KI_GRANDCHILD = (
    "import os, subprocess, sys, time\n"
    "p = subprocess.Popen([sys.executable, '-c', 'import sys,time; print(\"ready\", flush=True); time.sleep(300)'], stdout=subprocess.PIPE, text=True)\n"
    "p.stdout.readline()\n"
    "print('GRANDCHILD %d' % p.pid, flush=True)\n"
    "with open(os.path.join(os.getcwd(), 'grandchild.pid.tmp'), 'w') as f:\n"
    "    f.write(str(p.pid))\n"
    "os.replace(os.path.join(os.getcwd(), 'grandchild.pid.tmp'), os.path.join(os.getcwd(), 'grandchild.pid'))\n"
    "time.sleep(300)\n"
)
SRC_UPPER_URL = (
    "import subprocess, sys\n"
    "r = subprocess.run([sys.executable, '-c', 'pass', 'HTTPS://example.invalid/x'])\n"
    "print('PASS spawned with upper-case URL token rc=%d' % r.returncode)\n"
    "print('--- {n}: 1 passed, 0 failed ---')\nsys.exit(0)\n"
)
SRC_CMD_INVOKE = (
    "import subprocess, sys\n"
    "r = subprocess.run(['cmd.exe', '/c', 'echo', 'INVOKE-WEBREQUEST'], stdout=subprocess.DEVNULL)\n"
    "print('PASS spawned cmd.exe with INVOKE-WEBREQUEST token rc=%d' % r.returncode)\n"
    "print('--- {n}: 1 passed, 0 failed ---')\nsys.exit(0)\n"
)
SRC_TEMP_RESIDUE = (
    "import os, sys, tempfile\n"
    "d = tempfile.mkdtemp(prefix='residue_')\n"
    "open(os.path.join(d, 'left.txt'), 'w').close()\n"
    "print('PASS left residue in ' + os.path.basename(d))\n"
    "print('--- {n}: 1 passed, 0 failed ---')\nsys.exit(0)\n"
)


NESTED_TMP_DIRS = []


def note_nested_tmp(report):
    """Nested runners create their child temp dir under OUR temp root
    (%TEMP%/vsw_<pid>); they remove it only when empty. Record it so the
    `finally` block below leaves no residue behind for a parent sweep."""
    if report and report.get("tmp_dir"):
        NESTED_TMP_DIRS.append(report["tmp_dir"])


def run_fake(base, tag, modules, extra_args=(), extra_env=None, base_env=None, timeout=600):
    tests_dir = Path(base) / f"fake_{tag}"
    out_root = Path(base) / f"out_{tag}"
    tests_dir.mkdir()
    for name, src in modules.items():
        write_module(tests_dir, name, src.replace("{n}", name))
    args = ["--profile", "developer", "--tests-dir", str(tests_dir), "--output-root", str(out_root)] + list(extra_args)
    code, out, err = spawn_runner(args, extra_env=extra_env, base_env=base_env, timeout=timeout)
    run_dir = find_run_dir(out_root)
    report = load_report(run_dir) if run_dir and (run_dir / "report.json").exists() else None
    note_nested_tmp(report)
    return code, out, err, report, run_dir


# ---------------------------------------------------------------------------
# 23. byte-invariance snapshot (opening)
# ---------------------------------------------------------------------------

DATA_BEFORE = tree_manifest(REPO_ROOT / "data")
INDEX_BEFORE = tree_manifest(REPO_ROOT / "index")
TESTS_BEFORE = tree_manifest(REPO_ROOT / "ui" / "tests")

BASE = Path(tempfile.mkdtemp(prefix="vergi_step3_"))
try:
    check("temp base lives outside the repository", not runner.path_is_inside(str(BASE), str(REPO_ROOT)))
    # Fake module dir + self-test seam for refusal probes of the OFFICIAL
    # profiles: under a parent sweep the recursion lock fires first unless a
    # --tests-dir is given, and official profiles accept --tests-dir only
    # with the seam. The probed refusal (capability / PG syntax / usage)
    # comes AFTER those two gates, so the seam does not mask it.
    REFUSE_DIR = BASE / "refuse_dir"
    REFUSE_DIR.mkdir()
    write_module(REFUSE_DIR, "test_never_runs", SRC_OK.replace("{n}", "test_never_runs"))
    REFUSE_ARGS = ["--tests-dir", str(REFUSE_DIR)]
    SEAM = {runner.SELFTEST_SEAM_ENV: "1"}

    # -----------------------------------------------------------------------
    # 1. Parser (pure)
    # -----------------------------------------------------------------------
    P = runner.parse_module_output

    def enc(*lines):
        return ("\n".join(lines) + "\n").encode("utf-8")

    fmts = {
        "A": ("--- test_x: 2 passed, 0 failed ---", 2, 0, 0, 0),
        "B": ("--- test_x: 2 passed, 0 failed, 1 skipped ---", 2, 0, 1, 0),
        "C": ("--- test_x: 2 passed, 0 failed, 1 informational skips ---", 2, 0, 0, 1),
        "E": ("--- test_x: 2 passed, 0 failed (1 informational SKIPPED line(s), NOT counted) ---", 2, 0, 0, 1),
        "F": ("TOTAL: 2 passed, 0 failed", 2, 0, 0, 0),
        "G": ("2 passed, 0 failed", 2, 0, 0, 0),
        "H": ("2 passed, 0 failed, 1 informational skips", 2, 0, 0, 1),
    }
    for key, (summary, p, f, s, i) in fmts.items():
        lines = ["PASS a", "PASS b"]
        if s:
            lines.append("SKIPPED thing - reason")
        if i:
            lines.append("SKIPPED thing - reason (NOT counted as pass/fail)")
        lines.append(summary)
        r = P("test_x", enc(*lines), 0)
        check(f"parser format {key} -> PASS with p={p} s={s} i={i}",
              r.outcome == "PASS" and r.passed == p and r.counted_skips == s and r.informational_skips == i,
              f"{r.outcome} {r.as_dict()}")
    r = P("test_x", enc("PASS a", "PASS b", "--- test_x: 2 passed, 0 failed, 1 skipped ---"), 0)
    check("parser format D (two-part f-string output == B) -> PASS only when SKIPPED lines match", r.outcome == "SKIP_TALLY_MISMATCH", r.outcome)
    r = P("test_x", enc("PASS a", "--- test_other: 1 passed, 0 failed ---"), 0)
    check("parser: dash summary naming a foreign module -> PARSE_FAILURE", r.outcome == "PARSE_FAILURE", r.outcome)
    r = P("test_x", enc("--- test_x: 0 passed, 0 failed ---", "PASS a", "PASS b", "--- test_x: 2 passed, 0 failed ---"), 0)
    check("parser: last summary line wins over an early-exit 0/0 summary", r.outcome == "PASS" and r.passed == 2, r.outcome)
    r = P("test_x", enc("PASS a", "Results: 1 ok"), 0)
    check("parser: unrecognised summary with PASS lines -> PARSE_FAILURE", r.outcome == "PARSE_FAILURE", r.outcome)
    embedded = enc(
        "PASS a",
        "FAIL b child stdout=",
        "PASS child-one",
        "PASS child-two",
        "2 passed, 0 failed",
        "--- test_x: 1 passed, 1 failed ---",
    )
    r = P("test_x", embedded, 1)
    check("parser: exit!=0 with embedded grandchild summary -> FAIL (never PASS)", r.outcome == "FAIL", r.outcome)
    embedded0 = enc("PASS a", "FAIL b child stdout=", "PASS child-one", "2 passed, 0 failed", "--- test_x: 1 passed, 1 failed ---")
    r = P("test_x", embedded0, 0)
    check("parser: exit 0 + embedded fake lines + failed>0 -> EXIT_SUMMARY_CONTRADICTION", r.outcome == "EXIT_SUMMARY_CONTRADICTION", r.outcome)
    embedded_pass = enc("PASS a", "PASS child-one", "PASS child-two", "--- test_x: 1 passed, 0 failed ---")
    r = P("test_x", embedded_pass, 0)
    check("parser: exit 0 + embedded extra PASS lines -> TALLY_MISMATCH (never PASS)", r.outcome == "TALLY_MISMATCH", r.outcome)
    r = P("test_x", enc("PASS a", "SKIPPED thing (not counted as pass/fail)", "--- test_x: 1 passed, 0 failed ---"), 0)
    check("parser: lowercase 'not counted' -> informational, format A summary still PASS",
          r.outcome == "PASS" and r.informational_skips == 1 and r.counted_skips == 0, r.as_dict())
    r = P("test_x", b"PASS a\n\xff\xfe\n--- test_x: 1 passed, 0 failed ---\n", 0)
    check("parser: non-UTF-8 stdout -> PARSE_FAILURE", r.outcome == "PARSE_FAILURE", r.outcome)
    r = P("test_x", enc("PASS a", "PASS b (12 chars)", "--- test_x: 2 passed, 0 failed ---"), 0)
    check("parser: template-file 'PASS label (n chars)' variant counts by prefix", r.outcome == "PASS", r.outcome)
    r = P("test_x", enc("PASS a", "--- test_x: 1 passed, 0 failed ---"), 0, timed_out=True)
    check("parser: timed_out overrides a green summary -> TIMEOUT", r.outcome == "TIMEOUT", r.outcome)
    r = P("test_x", b"", 0, spawn_failed=True)
    check("parser: spawn_failed -> SPAWN_FAILURE", r.outcome == "SPAWN_FAILURE", r.outcome)

    # -----------------------------------------------------------------------
    # 2. zero-check
    # -----------------------------------------------------------------------
    r = P("test_x", enc("SKIPPED no db - x", "--- test_x: 0 passed, 0 failed, 1 skipped ---"), 0)
    check("zero-check: SKIPPED + 0/0 summary -> ZERO_CHECK_DOCUMENTED_SKIP", r.outcome == "ZERO_CHECK_DOCUMENTED_SKIP", r.outcome)
    r = P("test_x", enc("SKIPPED: fastapi missing"), 0)
    check("zero-check: SKIPPED without any summary (route-file shape) -> ZERO_CHECK_DOCUMENTED_SKIP", r.outcome == "ZERO_CHECK_DOCUMENTED_SKIP", r.outcome)
    r = P("test_x", b"", 0)
    check("zero-check: empty stdout exit 0 -> ZERO_CHECK_UNDOCUMENTED", r.outcome == "ZERO_CHECK_UNDOCUMENTED", r.outcome)
    r = P("test_x", enc("--- test_x: 0 passed, 0 failed ---"), 0)
    check("zero-check: bare 0/0 summary without SKIPPED -> ZERO_CHECK_UNDOCUMENTED", r.outcome == "ZERO_CHECK_UNDOCUMENTED", r.outcome)
    check("profile rule: documented zero-check -> exit 1 under production-parity",
          runner.decide_exit_code("production-parity", ["ZERO_CHECK_DOCUMENTED_SKIP"], []) == 1)
    check("profile rule: documented zero-check -> exit 1 under rag-dependency",
          runner.decide_exit_code("rag-dependency", ["ZERO_CHECK_DOCUMENTED_SKIP"], []) == 1)
    check("profile rule: documented zero-check -> exit 0 under developer",
          runner.decide_exit_code("developer", ["PASS", "ZERO_CHECK_DOCUMENTED_SKIP"], []) == 0)
    check("profile rule: undocumented zero-check -> exit 1 under developer",
          runner.decide_exit_code("developer", ["ZERO_CHECK_UNDOCUMENTED"], []) == 1)

    # -----------------------------------------------------------------------
    # 3./4. exit authority and tallies (pure)
    # -----------------------------------------------------------------------
    r = P("test_x", enc("PASS a", "PASS b", "--- test_x: 2 passed, 0 failed ---"), 1)
    check("exit!=0 + '0 failed' summary -> FAIL (exit code is authoritative)", r.outcome == "FAIL", r.outcome)
    r = P("test_x", enc("PASS a", "FAIL b x", "FAIL c y", "--- test_x: 1 passed, 2 failed ---"), 0)
    check("exit 0 + '2 failed' -> EXIT_SUMMARY_CONTRADICTION", r.outcome == "EXIT_SUMMARY_CONTRADICTION", r.outcome)
    r = P("test_x", enc("PASS a", "PASS b", "--- test_x: 3 passed, 0 failed ---"), 0)
    check("raw tally mismatch (3 vs 2 PASS lines) -> TALLY_MISMATCH", r.outcome == "TALLY_MISMATCH", r.outcome)
    r = P("test_x", enc("PASS a", "SKIPPED one - x", "--- test_x: 1 passed, 0 failed, 2 skipped ---"), 0)
    check("skip tally mismatch -> SKIP_TALLY_MISMATCH", r.outcome == "SKIP_TALLY_MISMATCH", r.outcome)
    r = P("test_x", enc("PASS a", "PASS b"), 1)
    check("PASS lines then exit 1 without summary -> CRASH_MID_RUN", r.outcome == "CRASH_MID_RUN" and r.observed_pass_lines == 2, r.outcome)

    # -----------------------------------------------------------------------
    # nested run A: mixed fake modules (2/3/4/5 end-to-end, 8, 9, 21)
    # -----------------------------------------------------------------------
    t0 = time.monotonic()
    code, out, err, report, run_dir = run_fake(BASE, "mixed", {
        "test_a_ok": SRC_OK,
        "test_b_docskip": SRC_DOC_SKIP,
        "test_c_routeskip": SRC_ROUTE_SKIP,
        "test_d_undoc": SRC_UNDOC,
        "test_e_fail": SRC_FAIL,
        "test_f_exit1_zero": SRC_EXIT1_ZERO_FAILED,
        "test_g_contra": SRC_CONTRADICTION,
        "test_h_tally": SRC_TALLY,
        "test_i_skiptally": SRC_SKIP_TALLY,
        "test_j_crash": SRC_CRASH,
        "test_k_grandchild": SRC_GRANDCHILD_OK,
        "test_l_envblock": SRC_ENV_BLOCK,
    })
    dur_a = time.monotonic() - t0
    check("nested A: report written", report is not None, f"code={code} out={out[-400:]} err={err[-400:]}")
    if report:
        expect = {
            "test_a_ok": "PASS", "test_b_docskip": "ZERO_CHECK_DOCUMENTED_SKIP",
            "test_c_routeskip": "ZERO_CHECK_DOCUMENTED_SKIP", "test_d_undoc": "ZERO_CHECK_UNDOCUMENTED",
            "test_e_fail": "FAIL", "test_f_exit1_zero": "FAIL", "test_g_contra": "EXIT_SUMMARY_CONTRADICTION",
            "test_h_tally": "TALLY_MISMATCH", "test_i_skiptally": "SKIP_TALLY_MISMATCH",
            "test_j_crash": "CRASH_MID_RUN", "test_k_grandchild": "PASS", "test_l_envblock": "PASS",
        }
        for name, exp in expect.items():
            m = module_entry(report, name)
            check(f"nested A: {name} -> {exp}", m is not None and m["outcome"] == exp, m and m["outcome"])
        check("nested A: exit 1 (FAIL-class modules present, developer profile)", code == 1, code)
        check("nested A: every module has guard_armed=True", all(m["guard_armed"] for m in report["modules"]))
        check("nested A: modules ordered bytewise by name", [m["name"] for m in report["modules"]] == sorted(expect, key=lambda s: s.encode()))
        g = report["guard"]
        pc = g.get("positive_controls") or {}
        check("nested A: positive controls 10/10", pc.get("passed") == 10 and pc.get("failures") == [], (pc, report.get("refusals")))
        check("nested A: inheritance ok (armed == modules + python POPENs)", g["inheritance_ok"] and g["armed_count"] == 13 and g["popen_python_count"] == 1, g)
        check("nested A: ledger recorded .env blocks from the fake module", g["env_open_blocked_count"] == 2, g["env_open_blocked_count"])
        check("nested A: label DIAGNOSTIC and console header", report["sweep_label"] == "DIAGNOSTIC" and "DIAGNOSTIC - NOT A FULL SWEEP" in out)
        check("nested A: console last line", last_line(out) == "SWEEP DIAGNOSTIC - exit 1", last_line(out))
        check("nested A: state completed, exit recorded", report["state"] == "completed" and report["runner_exit_code"] == 1)
        check("nested A: shim sha equals committed guard sha", g["shim_sha256"] == g["source_sha256"] == hashlib.sha256(GUARD_PATH.read_bytes()).hexdigest())
        check("nested A: discovery mode fake_dir", report["discovery"]["mode"] == "fake_dir")
        check("nested A: no integrity failures", report["integrity"]["failures"] == [], report["integrity"]["failures"])
        ledger = (run_dir / "guard_ledger.tsv").read_text(encoding="utf-8")
        armed_lines = [ln for ln in ledger.splitlines() if ln.startswith("GUARD_ARMED\t")]
        check("nested A: GUARD_ARMED ledger line has 6 tab fields (pid, ppid, run_id, executable, argv-json)",
              armed_lines and all(len(ln.split("\t")) == 6 for ln in armed_lines) and all(ln.split("\t")[3] == report["run_id"] for ln in armed_lines))
        # 14. DACL (Windows) with independent icacls cross-check
        if IS_WIN:
            acl = report["run_dir_acl"]
            check("nested A: run dir DACL verified private by the runner (ctypes)", acl["dacl_ok"] and acl["dacl_problems"] == [], acl)
            ic = subprocess.run(["icacls", str(run_dir)], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
            first = ic.split("Successfully")[0]
            entries = [ln.strip() for ln in first.splitlines() if ":(" in ln]
            names = [e.split(":(")[0].split("\\")[-1].lower() for e in entries]
            names = [n.replace(str(run_dir).lower(), "").strip() for n in names]
            check("nested A: icacls shows exactly 3 ACEs, none inherited", len(entries) == 3 and "(I)" not in first, first)
            check("nested A: icacls trustees are user/SYSTEM/Administrators only",
                  set(n.split()[-1] for n in names) == {os.environ.get("USERNAME", "").lower(), "system", "administrators"}, names)
            check("nested A: icacls shows no CodexSandboxUsers / foreign trustee", "codexsandbox" not in first.lower())
        else:
            skip_info("run dir DACL check", "POSIX: 0o700 verified by the runner itself; Windows-only icacls cross-check")
            check("nested A: POSIX run dir mode 700", stat.S_IMODE(os.stat(run_dir).st_mode) == 0o700)
        # 13. no env values / DSN / password in JSON (fake values injected below in nested B)
        # 23. logs private, raw
        check("nested A: raw stdout log kept verbatim for diagnostics", (run_dir / "logs" / "test_e_fail.stdout.bin").read_bytes().startswith(b"PASS a"))

    # -----------------------------------------------------------------------
    # nested B: environment contract + JSON secrecy (9, 13)
    # -----------------------------------------------------------------------
    FAKE = {
        "ANTHROPIC_API_KEY": "sk-ant-fakefakefakefakefakefakefake1234",
        "OPENAI_API_KEY": "sk-fake-openai-key-value-000000",
        "VERGI_IAM_DATABASE_URL": "postgresql://iamuser:iampassw0rdXYZ@127.0.0.1:5432/iam_fake",
        "VERGI_KEY_PROVIDER_KIND": "local_file",
        "VERGI_ENTRA_CLIENT_SECRET": "entra-secret-value-abcdefgh",
        "GIT_CONFIG_NOSYSTEM": "1",
        "MY_ROTATION_TOKEN": "token-value-0123456789abcdef",
        "PGHOSTADDR": "127.0.0.1",
        "PYTHONUTF8": "1",
        "SOME_UNRELATED_VAR": "unrelated-value-that-must-be-stripped",
    }
    code, out, err, report, run_dir = run_fake(BASE, "env", {"test_env_dump": SRC_ENV_DUMP}, extra_env=FAKE)
    check("nested B: exit 0", code == 0 and report is not None, f"code={code} out={out[-300:]} err={err[-300:]}")
    if report:
        names = set()
        for ln in (run_dir / "logs" / "test_env_dump.stdout.bin").read_text(encoding="utf-8").splitlines():
            if ln.startswith("ENVNAME "):
                names.add(ln[8:].upper())
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VERGI_IAM_DATABASE_URL", "VERGI_KEY_PROVIDER_KIND",
                  "VERGI_ENTRA_CLIENT_SECRET", "GIT_CONFIG_NOSYSTEM", "MY_ROTATION_TOKEN", "PGHOSTADDR", "PYTHONUTF8",
                  "SOME_UNRELATED_VAR"):
            check(f"nested B: child env lacks {k}", k not in names)
        for k in ("USERNAME", "LOCALAPPDATA", "PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP") if IS_WIN else ("PATH", "HOME"):
            check(f"nested B: child env has {k}", k in names)
        for k in ("PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "PYTHONPATH",
                  runner.GUARD_LEDGER_ENV, runner.GUARD_RUN_ID_ENV, runner.GUARD_PARENT_PID_ENV):
            check(f"nested B: child env has runner-set {k}", k in names)
        snap = report["env_snapshot"]
        check("nested B: snapshot marks secrets stripped_denylist",
              all(snap.get(k) == "stripped_denylist" for k in ("ANTHROPIC_API_KEY", "VERGI_IAM_DATABASE_URL", "VERGI_KEY_PROVIDER_KIND", "MY_ROTATION_TOKEN", "PGHOSTADDR", "GIT_CONFIG_NOSYSTEM")),
              {k: snap.get(k) for k in ("ANTHROPIC_API_KEY", "VERGI_IAM_DATABASE_URL", "MY_ROTATION_TOKEN")})
        check("nested B: snapshot marks unlisted stripped_unlisted", snap.get("SOME_UNRELATED_VAR") == "stripped_unlisted")
        check("nested B: snapshot marks PYTHONPATH runner_set", snap.get("PYTHONPATH") == "runner_set")
        text = (run_dir / "report.json").read_text(encoding="utf-8")
        leaked = [v for v in FAKE.values() if len(v) >= 8 and v in text]
        check("nested B: no fake secret VALUE appears anywhere in report.json", leaked == [], leaked)
        check("nested B: report.json carries no env values at all (snapshot values are labels)",
              set(snap.values()) <= {"passed", "stripped_denylist", "stripped_unlisted", "runner_set", "absent"})
        check("nested B: secret scan of raw logs is clean (values never reached the child)",
              report["integrity"]["secret_scan"]["hits"] == [] and report["integrity"]["failures"] == [], report["integrity"])

    # pure env checks
    env, snap = runner.build_child_env(
        {"PATH": "p", "ANTHROPIC_API_KEY": "k", "Pgpassword": "pw", "VERGI_TEST_PG_DSN": "db", "PYTHONPATH": "evil", "TEMP": "parenttemp", "HOME": "h"},
        "production-parity", "GUARDDIR", "LEDGER", "RUN", 42, "TMPDIR", platform="win32")
    check("build_child_env: allowlist passes PATH and PG contract (case-insensitive)", env.get("PATH") == "p" and env.get("PGPASSWORD") == "pw" and env.get("VERGI_TEST_PG_DSN") == "db")
    check("build_child_env: denylisted parent PYTHONPATH replaced by guard dir", env.get("PYTHONPATH") == "GUARDDIR" and snap["PYTHONPATH"] == "runner_set")
    check("build_child_env: parent TEMP not forwarded; runner-owned tmp used", env.get("TEMP") == "TMPDIR" and env.get("TMP") == "TMPDIR")
    check("build_child_env: HOME is not in the Windows allowlist", "HOME" not in env and snap["HOME"] == "stripped_unlisted")
    check("build_child_env: rag profile adds VERGI_RAG_DEPENDENCY_GATE=require",
          runner.build_child_env({}, "rag-dependency", "g", "l", "r", 1, "t", platform="win32")[0].get("VERGI_RAG_DEPENDENCY_GATE") == "require")
    check("build_child_env: production-parity does NOT set VERGI_RAG_DEPENDENCY_GATE", "VERGI_RAG_DEPENDENCY_GATE" not in env)
    check("assert_env_denylist: violation detected for a smuggled secret", runner.assert_env_denylist({"ANTHROPIC_API_KEY": "x", "PATH": "p"}, {}) == ["ANTHROPIC_API_KEY"])
    check("assert_env_denylist: runner-set PYTHONPATH tolerated only with the runner value",
          runner.assert_env_denylist({"PYTHONPATH": "g"}, {"PYTHONPATH": "g"}) == [] and runner.assert_env_denylist({"PYTHONPATH": "other"}, {"PYTHONPATH": "g"}) == ["PYTHONPATH"])
    check("is_denylisted_name: PGPASSWORD is the sole PASSWORD exception", not runner.is_denylisted_name("PGPASSWORD") and runner.is_denylisted_name("DB_PASSWORD") and runner.is_denylisted_name("x_api_key") and runner.is_denylisted_name("GIT_DIR"))

    # -----------------------------------------------------------------------
    # 10. capability profiles
    # -----------------------------------------------------------------------
    present_all = {n: "1.0" for n, _ in runner.PRODUCTION_PARITY_REQUIRED + runner.RAG_DEPENDENCY_REQUIRED}
    ok, missing, warns = runner.evaluate_profile_capabilities("production-parity", present_all, (3, 14, 4))
    check("capabilities: production-parity ok when all present on 3.14", ok and missing == [])
    ok, missing, _ = runner.evaluate_profile_capabilities("production-parity", dict(present_all, psycopg="absent"), (3, 14, 4))
    check("capabilities: production-parity missing psycopg -> not ok", not ok and missing == ["psycopg"], missing)
    ok, missing, _ = runner.evaluate_profile_capabilities("production-parity", present_all, (3, 13, 1))
    check("capabilities: python != 3.14 refused for official profiles", not ok and any("python" in m for m in missing), missing)
    ok, missing, warns = runner.evaluate_profile_capabilities("developer", dict(present_all, faiss="absent"), (3, 13, 1))
    check("capabilities: developer only warns", ok and missing == [] and len(warns) == 2, warns)
    ok, missing, _ = runner.evaluate_profile_capabilities("rag-dependency", dict(present_all, httpx2="absent"), (3, 14, 0))
    check("capabilities: rag-dependency missing httpx2 -> not ok", not ok and missing == ["httpx2"], missing)
    live = runner.probe_capabilities()
    check("probe_capabilities returns entries for every contract name", all(n in live for n, _ in runner.PRODUCTION_PARITY_REQUIRED + runner.RAG_DEPENDENCY_REQUIRED))
    check("probe_capabilities did not import a heavy module (faiss/numpy not in sys.modules)", "faiss" not in sys.modules and "numpy" not in sys.modules)
    rag_missing = [n for n, _ in runner.RAG_DEPENDENCY_REQUIRED if live.get(n) == "absent"]
    prod_missing = [n for n, _ in runner.PRODUCTION_PARITY_REQUIRED if live.get(n) == "absent"]
    if rag_missing:
        code, out, err = spawn_runner(["--profile", "rag-dependency", "--output-root", str(BASE / "out_rag_refuse")] + REFUSE_ARGS,
                                      extra_env=dict(SEAM, VERGI_TEST_PG_DSN=None))
        check("nested: rag-dependency under an interpreter lacking RAG deps -> exit 2 CAPABILITY_MISSING, no run dir",
              code == 2 and "CAPABILITY_MISSING" in out and find_run_dir(BASE / "out_rag_refuse") is None, f"code={code} {last_line(out)}")
    if prod_missing:
        code, out, err = spawn_runner(["--profile", "production-parity", "--output-root", str(BASE / "out_prod_refuse")] + REFUSE_ARGS, extra_env=SEAM)
        check("nested: production-parity under an interpreter lacking psycopg/authlib -> exit 2 CAPABILITY_MISSING",
              code == 2 and "CAPABILITY_MISSING" in out, f"code={code} {last_line(out)}")
    if not rag_missing and not prod_missing:
        skip_info("live capability refusal", "this interpreter carries every capability; refusal proven by pure checks only")

    # -----------------------------------------------------------------------
    # 11. PostgreSQL syntactic contract (pure + nested)
    # -----------------------------------------------------------------------
    check("dsn: bare name accepted", runner.validate_pg_dsn_name("vergi_test_db") is None)
    check("dsn: URI refused", runner.validate_pg_dsn_name("postgresql://u:p@127.0.0.1/db") is not None)
    check("dsn: conninfo refused", runner.validate_pg_dsn_name("dbname=x host=y") is not None)
    check("dsn: unset refused", runner.validate_pg_dsn_name(None) is not None)
    check("dsn: refusal text never echoes the value", "supersecret" not in (runner.validate_pg_dsn_name("dbname=supersecret") or ""))
    check("pghost: loopback forms accepted", all(runner.validate_pghost(h) is None for h in (None, "", "127.0.0.1", "::1", "localhost", "LOCALHOST")))
    check("pghost: non-loopback refused", runner.validate_pghost("10.0.0.5") is not None and runner.validate_pghost("db.example") is not None)
    check("pgport: numeric only", runner.validate_pgport("55432") is None and runner.validate_pgport("abc") is not None and runner.validate_pgport("70000") is not None)
    same = {"host": "localhost", "port": "55432", "dbname": "testdb"}
    check("iam url same target (loopback aliases equal) -> refused", runner.iam_url_targets_test_db(same, "127.0.0.1", "55432", "testdb"))
    check("iam url different db -> not same target", not runner.iam_url_targets_test_db(dict(same, dbname="iam"), "127.0.0.1", "55432", "testdb"))
    check("iam url different port -> not same target", not runner.iam_url_targets_test_db(dict(same, port="5432"), "127.0.0.1", "55432", "testdb"))
    check("iam url default port 5432 when omitted", runner.iam_url_targets_test_db({"host": "127.0.0.1", "dbname": "t"}, None, None, "t"))
    check("migration sentinels: all present -> none missing", runner.missing_migrations(
        {n for _, k, n in runner.MIGRATION_SENTINELS if k == "table"}, {n for _, k, n in runner.MIGRATION_SENTINELS if k == "column"}) == [])
    check("migration sentinels: 0004 columns + 0005 tables missing are named",
          runner.missing_migrations({"iam.users", "mutation.mutation_resources", "mutation.mutation_journal"}, set()) ==
          ["0004:mutation.mutation_journal.reconciled_by_actor_type", "0004:mutation.mutation_journal.reconciled_by_actor_ref",
           "0005:iam.global_resource_grants", "0005:iam.global_resource_grant_events"])
    check("inet_server_addr loopback classification", runner.is_loopback_server_addr("127.0.0.1") and runner.is_loopback_server_addr(None)
          and runner.is_loopback_server_addr("::1") and not runner.is_loopback_server_addr("192.168.1.2"))
    check("concurrent sweep detection (pure)", runner.concurrent_sweep_present([("psql", 1), (runner.APPLICATION_NAME, 2)]) and not runner.concurrent_sweep_present([("psql", 1)]))
    code, out, err = spawn_runner(["--profile", "rag-dependency", "--output-root", str(BASE / "out_mix")] + REFUSE_ARGS,
                                  extra_env=dict(SEAM, VERGI_TEST_PG_DSN="somedb"))
    check("nested: rag-dependency with VERGI_TEST_PG_DSN set -> exit 2 (PROFILE_MIX or CAPABILITY_MISSING), no run dir",
          code == 2 and ("PROFILE_MIX" in out or "CAPABILITY_MISSING" in out) and find_run_dir(BASE / "out_mix") is None, f"code={code} {last_line(out)}")
    if not prod_missing:
        code, out, err = spawn_runner(["--profile", "production-parity", "--output-root", str(BASE / "out_dsn")] + REFUSE_ARGS,
                                      extra_env=dict(SEAM, VERGI_TEST_PG_DSN="postgresql://u:pw@127.0.0.1/db", PGHOST=None))
        check("nested: production-parity with a URI in VERGI_TEST_PG_DSN -> exit 2 PG_DSN, value not echoed",
              code == 2 and "PG_DSN" in out and "pw@" not in out, f"code={code} {last_line(out)}")
        code, out, err = spawn_runner(["--profile", "production-parity", "--output-root", str(BASE / "out_host")] + REFUSE_ARGS,
                                      extra_env=dict(SEAM, VERGI_TEST_PG_DSN="somedb", PGHOST="10.1.2.3"))
        check("nested: production-parity with non-loopback PGHOST -> exit 2 PG_ENV", code == 2 and "PG_ENV" in out, f"code={code} {last_line(out)}")
    else:
        skip_info("nested production-parity PG syntax refusals", "interpreter lacks production-parity capabilities (refuses earlier)")

    # -----------------------------------------------------------------------
    # 12. discovery
    # -----------------------------------------------------------------------
    miss, untr = runner.reconcile_discovery({"test_a", "test_b"}, {"test_b", "test_c"})
    check("reconcile_discovery: missing and untracked separated", miss == ["test_a"] and untr == ["test_c"])
    ddir = BASE / "disc"
    ddir.mkdir()
    write_module(ddir, "test_b", "")
    write_module(ddir, "test_a", "")
    write_module(ddir, "test_Z", "")
    (ddir / "test_notpy.txt").write_text("x")
    (ddir / "helper.py").write_text("x")
    names, rejected = runner.filesystem_test_modules(str(ddir))
    check("filesystem discovery: only test_*.py regular files", names == {"test_a", "test_b", "test_Z"} and rejected == [])
    check("ordering is bytewise (uppercase before lowercase)", sorted(names, key=lambda s: s.encode()) == ["test_Z", "test_a", "test_b"])
    if IS_WIN:
        target = BASE / "junction_target"
        target.mkdir()
        link = ddir / "test_link.py"
        made = make_junction(link, target)
        try:
            names2, rejected2 = runner.filesystem_test_modules(str(ddir))
            check("filesystem discovery: NTFS junction named test_link.py rejected as reparse point",
                  made and "test_link" not in names2 and any(r["name"] == "test_link.py" for r in rejected2), (made, rejected2))
        finally:
            remove_junction(link)
    else:
        skip_info("junction discovery rejection", "Windows-only (mklink /J)")
    old_path = os.environ.get("PATH")
    try:
        os.environ["PATH"] = str(BASE / "nonexistent_bin")
        tracked, gerr = runner.git_tracked_test_modules(str(REPO_ROOT))
        check("git absent -> tracked set None with reason", tracked is None and gerr, gerr)
    finally:
        if old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old_path
    tracked, gerr = runner.git_tracked_test_modules(str(REPO_ROOT))
    check("git present -> tracked ui/tests set returned without error", tracked is not None and not gerr, gerr)
    if tracked is not None:
        fs_real, _rej = runner.filesystem_test_modules(str(REPO_ROOT / "ui" / "tests"))
        missing_tracked, untracked = runner.reconcile_discovery(set(tracked), set(fs_real))
        check("git present -> every tracked test module exists on disk (missing_tracked == [])", missing_tracked == [], missing_tracked)
        check("git present -> tracked set is non-trivial and names only test_* modules", len(tracked) >= 10 and all(n.startswith("test_") for n in tracked), len(tracked))
        check("git present -> a long-tracked module (test_routes) is in the tracked set", "test_routes" in tracked)
        # Honest self-reference: whether this module is still untracked (before its
        # `git add`) or already tracked, git and the reconciler must classify it the
        # same way -- the official-profile UNTRACKED_TEST_MODULE refusal rests on this.
        check("git present -> this module's tracked/untracked status is reported consistently by git and reconcile_discovery",
              MODULE_NAME in fs_real and (MODULE_NAME in tracked) == (MODULE_NAME not in untracked), (MODULE_NAME in tracked, untracked))
    code, out, err = spawn_runner(["--profile", "developer", "--output-root", str(BASE / "out_rec")], extra_env={runner.GUARD_PARENT_PID_ENV: "1"})
    check("recursion lock: sweep child env without --tests-dir -> exit 2 RECURSION, no run dir",
          code == 2 and "RECURSION" in out and find_run_dir(BASE / "out_rec") is None, f"code={code} {last_line(out)}")
    code, out, err = spawn_runner(["--profile", "developer", "--tests-dir", str(BASE / "does_not_exist"), "--output-root", str(BASE / "out_nodir")])
    check("usage: --tests-dir that is not a directory -> exit 2", code == 2 and "USAGE" in out, last_line(out))
    code, out, err = spawn_runner(["--output-root", str(BASE / "out_noprofile")])
    check("usage: --profile is mandatory (no default profile) -> exit 2", code == 2, code)
    code, out, err = spawn_runner(["--profile", "production-parity", "--select", "test_x", "--output-root", str(BASE / "out_sel")] + REFUSE_ARGS, extra_env=SEAM)
    check("usage: --select rejected outside developer -> exit 2", code == 2 and "USAGE" in out, last_line(out))
    code, out, err = spawn_runner(["--profile", "production-parity", "--output-root", str(BASE / "out_tdir")] + REFUSE_ARGS,
                                  extra_env={runner.SELFTEST_SEAM_ENV: None, runner.GUARD_PARENT_PID_ENV: None})
    check("usage: --tests-dir rejected for official profiles without the self-test seam -> exit 2", code == 2 and "USAGE" in out, last_line(out))

    # -----------------------------------------------------------------------
    # 13. output root / exclusive dir / atomic report
    # -----------------------------------------------------------------------
    inside = REPO_ROOT / "scripts" / "_step3_never_created"
    code, out, err = spawn_runner(["--profile", "developer", "--tests-dir", str(ddir), "--output-root", str(inside)])
    check("output-root inside the repository -> exit 2, directory never created", code == 2 and "OUTPUT_ROOT" in out and not inside.exists(), (code, last_line(out), inside.exists()))
    if IS_WIN:
        jlink = BASE / "junc_to_repo"
        made = make_junction(jlink, REPO_ROOT / "scripts")
        try:
            code, out, err = spawn_runner(["--profile", "developer", "--tests-dir", str(ddir), "--output-root", str(jlink / "_step3_junction_out")])
            check("output-root via junction into the repository -> exit 2 (realpath)", made and code == 2 and "OUTPUT_ROOT" in out and not (REPO_ROOT / "scripts" / "_step3_junction_out").exists(), (made, code, last_line(out)))
        finally:
            remove_junction(jlink)
    else:
        skip_info("junction output-root refusal", "Windows-only (mklink /J)")
    excl_root = BASE / "excl"
    p1, _ = runner.create_exclusive_private_run_dir(str(excl_root), "sweep_x")
    p2, _ = runner.create_exclusive_private_run_dir(str(excl_root), "sweep_x")
    check("exclusive run dir: collision gets _<n> suffix", os.path.basename(p1) == "sweep_x" and os.path.basename(p2) == "sweep_x_1")
    seam_calls = []

    def bad_seam(sddl, sid):
        seam_calls.append(1)
        return False, ["injected verification failure"]
    try:
        runner.create_exclusive_private_run_dir(str(excl_root), "sweep_bad", verify_seam=bad_seam)
        check("private dir verification failure -> RuntimeError", False, "no exception")
    except RuntimeError:
        check("private dir verification failure -> RuntimeError and directory removed", seam_calls and not (excl_root / "sweep_bad").exists())
    rep = BASE / "report.json"
    runner.write_report_atomic(str(rep), {"v": 1})
    before = rep.read_bytes()

    def failing_replace(src, dst):
        raise OSError("injected replace failure")
    try:
        runner.write_report_atomic(str(rep), {"v": 2}, replace=failing_replace)
        check("atomic report: injected replace failure raises", False)
    except OSError:
        check("atomic report: previous report.json kept byte-for-byte after a failed replace", rep.read_bytes() == before)
    # Behavioural: Sweep.finish() must turn an unwritable FINAL report into exit 3
    # (EXIT_INTEGRITY) for an otherwise clean or module-failed sweep, and must never
    # mask a refusal (exit 2) as an integrity failure.
    fin_dir = BASE / "finish_fail"
    fin_dir.mkdir()
    sw_fin = runner.Sweep(make_args(tests_dir=str(fin_dir)), {}, str(REPO_ROOT), io.StringIO())
    sw_fin.report["discovery"]["mode"] = "fake_dir"

    def failing_flush():
        raise OSError("injected final report write failure")
    sw_fin.flush_report = failing_flush
    rc_ok = sw_fin.finish(runner.EXIT_OK)
    check("atomic report: finish() turns an unwritable final report into exit 3 for an otherwise clean sweep",
          rc_ok == runner.EXIT_INTEGRITY == 3 and sw_fin.report["runner_exit_code"] == 3 and sw_fin.report["state"] == "completed" and sw_fin.report["sweep_label"] == "DIAGNOSTIC",
          (rc_ok, sw_fin.report["runner_exit_code"], sw_fin.report["sweep_label"]))
    rc_fail = sw_fin.finish(runner.EXIT_MODULE_FAILURE)
    check("atomic report: finish() promotes a module-failure exit 1 to 3 when the final report cannot be written", rc_fail == runner.EXIT_INTEGRITY, rc_fail)
    rc_ref = sw_fin.finish(runner.EXIT_REFUSED)
    check("atomic report: finish() keeps a refusal exit 2 (never masked as integrity) when the final report cannot be written", rc_ref == runner.EXIT_REFUSED == 2, rc_ref)
    if IS_WIN:
        ok, problems = runner.dacl_is_private("D:PAI(A;OICI;FA;;;S-1-5-21-1-2-3-1001)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)", "S-1-5-21-1-2-3-1001")
        check("dacl_is_private: exact private DACL accepted", ok, problems)
        ok, problems = runner.dacl_is_private("D:PAI(A;OICI;FA;;;S-1-5-21-1-2-3-1001)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;S-1-5-21-9-9-9-513)", "S-1-5-21-1-2-3-1001")
        check("dacl_is_private: extra trustee rejected", not ok)
        ok, problems = runner.dacl_is_private("D:AI(A;OICIID;FA;;;S-1-5-21-1-2-3-1001)(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)", "S-1-5-21-1-2-3-1001")
        check("dacl_is_private: inherited ACEs / unprotected DACL rejected", not ok and any("inherited" in p for p in problems) and any("protected" in p for p in problems), problems)
        ok, problems = runner.dacl_is_private("D:P(A;OICI;FA;;;S-1-5-21-1-2-3-1001)(A;OICI;FA;;;SY)", "S-1-5-21-1-2-3-1001")
        check("dacl_is_private: missing Administrators ACE rejected (set must be exact)", not ok)

    # -----------------------------------------------------------------------
    # 6. timeout kills the whole tree (nested, real Job Object)
    # -----------------------------------------------------------------------
    t0 = time.monotonic()
    code, out, err, report, run_dir = run_fake(BASE, "timeout", {"test_timeout": SRC_TIMEOUT}, extra_args=["--module-timeout", "3"], timeout=600)
    dur_t = time.monotonic() - t0
    m = report and module_entry(report, "test_timeout")
    check("timeout: outcome TIMEOUT", m is not None and m["outcome"] == "TIMEOUT", m and m["outcome"])
    check("timeout: runner returned within a bounded time (<90s)", dur_t < 90, dur_t)
    if m:
        gpid = None
        for ln in (run_dir / "logs" / "test_timeout.stdout.bin").read_text(encoding="utf-8", errors="replace").splitlines():
            if ln.startswith("GRANDCHILD "):
                gpid = int(ln.split()[1])
        check("timeout: grandchild pid was reported by the fake module", gpid is not None)
        if gpid is not None:
            time.sleep(0.5)
            check("timeout: grandchild is dead after the module was killed", not process_alive(gpid), gpid)
        if IS_WIN:
            check("timeout: job accounting reports 0 active processes", m["job_active_after"] == 0, m["job_active_after"])
            check("timeout: no PROCESS_RESIDUE integrity failure", not any(f["kind"] == "PROCESS_RESIDUE" for f in report["integrity"]["failures"]))
        else:
            skip_info("job accounting", "Windows-only Job Object accounting")
        check("timeout: developer exit 1 (module non-PASS)", code == 1, code)
    if IS_WIN:
        job = runner._JobObject()
        # The grandchild reports readiness AFTER interpreter start-up so that,
        # under a parent sweep, its GUARD_ARMED line is already written before
        # the job is terminated (keeps the parent's accounting balanced).
        child_code = (
            "import subprocess,sys,time\n"
            "p=subprocess.Popen([sys.executable,'-c','import sys,time; print(\"ready\", flush=True); time.sleep(300)'], stdout=subprocess.PIPE, text=True)\n"
            "p.stdout.readline()\n"
            "print(p.pid, flush=True)\n"
            "time.sleep(300)\n"
        )
        child = subprocess.Popen([sys.executable, "-c", child_code], stdout=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
        job.assign(child._handle)
        gpid = int(child.stdout.readline().strip())
        active_before = job.active_processes()
        job.terminate()
        child.wait(timeout=30)
        remaining = runner.wait_for_zero_active(job)
        job.close()
        time.sleep(0.3)
        check("job object: whole tree terminated (active before>=2, after==0, grandchild dead)", active_before >= 2 and remaining == 0 and not process_alive(gpid), (active_before, remaining))

        class FakeJob:
            def __init__(self, n):
                self.n = n

            def active_processes(self):
                return self.n
        check("escaped-grandchild accounting seam: non-zero active -> reported as residue", runner.wait_for_zero_active(FakeJob(2), grace_s=0.3) == 2)
    check("escaped-grandchild -> PROCESS_RESIDUE integrity failure -> exit 3 even when modules PASS",
          runner.decide_exit_code("production-parity", ["PASS"], [{"kind": "PROCESS_RESIDUE"}]) == 3 and runner.decide_exit_code("developer", ["PASS"], [{"kind": "PROCESS_RESIDUE"}]) == 3)

    # -----------------------------------------------------------------------
    # 7. spawn failure (in-process Sweep with a non-existent interpreter)
    # -----------------------------------------------------------------------
    sf_dir = BASE / "spawnfail"
    for sub in ("run", "run/logs", "run/tmp", "tests"):
        (sf_dir / sub).mkdir(parents=True)
    write_module(sf_dir / "tests", "test_sf", SRC_OK.replace("{n}", "test_sf"))
    sw = runner.Sweep(make_args(tests_dir=str(sf_dir / "tests")), {}, str(REPO_ROOT), io.StringIO())
    sw.run_dir = str(sf_dir / "run")
    sw.logs_dir = str(sf_dir / "run" / "logs")
    sw.tmp_dir = str(sf_dir / "run" / "tmp")
    sw.ledger_path = str(sf_dir / "run" / "guard_ledger.tsv")
    sw.tests_dir = str(sf_dir / "tests")
    sw.report["discovery"]["mode"] = "fake_dir"
    sw.child_env = dict(os.environ)
    # Seam: a Popen that fails like a missing interpreter WITHOUT emitting a
    # real `subprocess.Popen` audit event (a real failed spawn would still be
    # recorded in a parent sweep's ledger and unbalance its accounting).
    saved_popen = runner.subprocess.Popen

    def failing_popen(*a, **kw):
        raise FileNotFoundError(2, "simulated missing interpreter")
    try:
        runner.subprocess.Popen = failing_popen
        sw.run_module("test_sf")
    finally:
        runner.subprocess.Popen = saved_popen
    check("spawn failure: outcome SPAWN_FAILURE, no guard claim", sw.report["modules"][0]["outcome"] == "SPAWN_FAILURE" and sw.report["modules"][0]["guard_armed"] is False, sw.report["modules"][0])
    check("spawn failure -> exit 1 under every profile", runner.decide_exit_code("developer", ["SPAWN_FAILURE"], []) == 1 and runner.decide_exit_code("production-parity", ["SPAWN_FAILURE"], []) == 1)

    # -----------------------------------------------------------------------
    # 8. guard: shim corruption seam, -I inheritance, suspicious subprocess, popen parsing
    # -----------------------------------------------------------------------
    gs_dir = BASE / "shim"
    (gs_dir / "guard").mkdir(parents=True)
    sw2 = runner.Sweep(make_args(), {}, str(REPO_ROOT), io.StringIO())
    sw2.guard_dir = str(gs_dir / "guard")
    sw2.ledger_path = str(gs_dir / "ledger.tsv")
    saved_sha = runner.sha256_file
    try:
        runner.sha256_file = lambda p: "0" * 64
        try:
            sw2.phase_guard_shim()
            check("guard shim: corrupted copy (hash seam) -> refusal", False, "no refusal")
        except runner.Refusal as exc:
            check("guard shim: corrupted copy (hash seam) -> GUARD_SHIM refusal (exit 2 class)", "GUARD_SHIM" in str(exc))
    finally:
        runner.sha256_file = saved_sha
    sw2.phase_guard_shim()
    check("guard shim: honest copy accepted, bytes identical to committed source", (gs_dir / "guard" / "sitecustomize.py").read_bytes() == GUARD_PATH.read_bytes())
    code, out, err, report, run_dir = run_fake(BASE, "isolated", {"test_iso": SRC_ISOLATED_CHILD})
    check("guard: fake module spawning `python -I` -> GUARD_INHERITANCE_MISMATCH, exit 3",
          code == 3 and report and any(f["kind"] == "GUARD_INHERITANCE_MISMATCH" for f in report["integrity"]["failures"]) and report["guard"]["unarmed_flag_popen_count"] == 1,
          (code, report and report["guard"]))
    code, out, err, report, run_dir = run_fake(BASE, "curl", {"test_curl": SRC_CURL_TOKEN})
    check("guard: argv token 'curl' -> SUSPICIOUS_SUBPROCESS, exit 3",
          code == 3 and report and any(f["kind"] == "SUSPICIOUS_SUBPROCESS" for f in report["integrity"]["failures"]), (code, report and report["integrity"]["failures"]))
    check("popen parsing: Windows joined command line tokenised", runner.popen_executable_basename(['C:\\x\\python.exe -I -c "print(1)"']) == "python.exe"
          and runner.popen_has_unarmed_flag(['C:\\x\\python.exe -I -c "print(1)"']))
    check("popen parsing: list argv", runner.popen_is_python(["/usr/bin/python3", "-c", "pass"]) and not runner.popen_has_unarmed_flag(["/usr/bin/python3", "-B", "-c", "pass"]))
    check("popen parsing: combined -BI flag detected", runner.popen_has_unarmed_flag(["python.exe", "-BI", "x.py"]) and runner.popen_has_unarmed_flag(["python", "-E", "-m", "m"]))
    check("popen parsing: -I after -c is script argv, not an interpreter flag", not runner.popen_has_unarmed_flag(["python.exe", "-c", "pass", "-I"]))
    check("popen suspicious: non-allowlisted executable", runner.popen_is_suspicious(["curl.exe", "http://x"]) is not None and runner.popen_is_suspicious(["powershell", "-c", "x"]) is not None)
    check("popen suspicious: denylisted token inside an allowlisted executable", runner.popen_is_suspicious(["cmd.exe", "/c", "certutil", "-urlcache"]) is not None)
    check("popen suspicious: benign git/psql/icacls/python allowed", all(runner.popen_is_suspicious(a) is None for a in (["git", "status"], ["psql.exe", "-c", "select 1"], ["icacls", "x"], ['C:\\p\\python.exe -m ui.tests.x'])))
    recs = runner.parse_ledger_lines("GUARD_ARMED\t10\t9\trun1\tC:\\python.exe\t[\"-m\"]\nPOPEN\t10\trun1\tnull\t[\"C:\\\\python.exe -c pass\"]\tnull\nGARBAGE line\n")
    check("ledger parse: kinds and malformed detection", [r.kind for r in recs] == ["GUARD_ARMED", "POPEN", "MALFORMED"] and recs[0].pid == 10 and recs[0].ppid == 9)
    acct = runner.guard_accounting(recs[:2] + [runner.parse_ledger_lines("GUARD_ARMED\t11\t10\trun1\tC:\\python.exe\t[\"-c\"]")[0]], "run1", 1)
    check("guard accounting: armed == modules + python POPENs -> inheritance ok", acct["inheritance_ok"] and acct["armed_count"] == 2 and acct["popen_python_count"] == 1, acct)
    acct_bad = runner.guard_accounting(recs, "run1", 1)
    check("guard accounting: malformed line or missing GUARD_ARMED -> inheritance NOT ok", not acct_bad["inheritance_ok"] and acct_bad["malformed_lines"] == 1, acct_bad)
    nested = runner.parse_ledger_lines("NESTED_RUNNER\t10\t5\trun1\tchild_run\nPOPEN\t10\trun1\tnull\t[\"C:\\\\python.exe -m x\"]\tnull\nGUARD_ARMED\t10\t5\trun1\tC:\\python.exe\t[\"scripts/run_ui_tests.py\"]\n")
    acct = runner.guard_accounting(nested, "run1", 1)
    check("guard accounting (fallback window: NESTED_RUNNER line written before its own arming record): python POPENs recorded by a nested runner are excluded",
          acct["inheritance_ok"] and acct["popen_python_nested_excluded"] == 1 and acct["nested_runner_count"] == 1, acct)

    # V2: nested-runner exclusion is limited to the nested runner's LIFE window.
    # Windows reuses pids: the former bare-pid exclusion (whole run) hid the
    # python spawns of an ORDINARY process that later received a nested
    # runner's old pid (false GUARD_INHERITANCE_MISMATCH, exit 3) and, the
    # other way round, could hide a genuinely unarmed child (fail-open).
    def _lg(kind, pid, *rest):
        return "\t".join([kind, str(pid)] + [str(x) for x in rest])

    def _lg_armed(pid, ppid, argv):
        return _lg("GUARD_ARMED", pid, ppid, "run1", "C:\\python.exe", json.dumps(argv, separators=(",", ":")))

    def _lg_popen(pid, argv):
        return _lg("POPEN", pid, "run1", "null", json.dumps(argv, separators=(",", ":")), "null")

    def _lg_nested(pid, ppid):
        return _lg("NESTED_RUNNER", pid, ppid, "run1", "child_run")

    def _v2_ledger(nested_pid, child_armed):
        # module A (pid 100) spawns one python child and finishes; module T1
        # (pid 200) then spawns a nested runner whose interpreter has nested_pid.
        rows = [_lg_armed(100, 90, ["-m"]), _lg_popen(100, ["python.exe", "-c", "pass"])]
        if child_armed:
            rows.append(_lg_armed(500, 100, ["-c"]))
        rows += [_lg_armed(200, 91, ["-m"]), _lg_popen(200, ["python.exe", "scripts/run_ui_tests.py"]),
                 _lg_armed(nested_pid, 92, ["scripts/run_ui_tests.py"]), _lg_nested(nested_pid, 92)]
        return runner.parse_ledger_lines("\n".join(rows) + "\n")

    for v2_label, v2_pid, v2_armed_child, v2_truth in (
            ("armed child, no pid reuse", 300, True, True),
            ("armed child, pid REUSED by a later nested runner (former false exit 3)", 100, True, True),
            ("UNARMED child, no pid reuse", 300, False, False),
            ("UNARMED child, pid REUSED by a later nested runner (former fail-open)", 100, False, False)):
        v2_acct = runner.guard_accounting(_v2_ledger(v2_pid, v2_armed_child), "run1", 2)
        check(f"V2 guard accounting - {v2_label}: inheritance_ok is {v2_truth}", v2_acct["inheritance_ok"] is v2_truth, v2_acct)
    rows = [_lg_armed(200, 91, ["-m"]),
            _lg_popen(200, ["python.exe", "scripts/run_ui_tests.py"]), _lg_armed(300, 92, ["scripts/run_ui_tests.py"]), _lg_nested(300, 92),
            _lg_popen(300, ["python.exe", "-m", "x"]),
            _lg_popen(200, ["python.exe", "scripts/run_ui_tests.py"]), _lg_armed(300, 93, ["scripts/run_ui_tests.py"]), _lg_nested(300, 93),
            _lg_popen(300, ["python.exe", "-m", "y"])]
    v2_acct = runner.guard_accounting(runner.parse_ledger_lines("\n".join(rows) + "\n"), "run1", 1)
    check("V2 guard accounting - the SAME pid is a nested runner twice: both life windows exclude that runner's own spawns, nothing else",
          v2_acct["inheritance_ok"] and v2_acct["popen_python_count"] == 2 and v2_acct["popen_python_nested_excluded"] == 2
          and v2_acct["nested_runner_count"] == 2 and v2_acct["nested_runner_unique_pids"] == 1, v2_acct)
    # The REAL failing shape (reduced from the ledger of a real-PostgreSQL developer sweep: pid 16360 was a nested
    # runner, later an ordinary module process whose python spawn had been excluded -> armed 193 vs expected 192).
    rows = [_lg_armed(14520, 14000, ["-m"]), _lg_popen(14520, ["python.exe", "scripts/run_ui_tests.py"]),
            _lg_armed(16360, 14568, ["scripts/run_ui_tests.py"]), _lg_nested(16360, 14568), _lg_popen(16360, ["python.exe", "-m", "test_ki"]),
            _lg_armed(16360, 11232, ["-m"]), _lg_popen(16360, ["python.exe", "-c", "import sys,time; time.sleep(300)"]),
            _lg_armed(15540, 14608, ["-c"])]
    v2_acct = runner.guard_accounting(runner.parse_ledger_lines("\n".join(rows) + "\n"), "run1", 2)
    check("V2 guard accounting - real-ledger shape (pid nested runner first, ordinary module process later): armed == expected",
          v2_acct["inheritance_ok"] and v2_acct["armed_count"] == 4 and v2_acct["expected_armed"] == 4
          and v2_acct["popen_python_nested_excluded"] == 1, v2_acct)
    v2_w = runner.nested_runner_windows(runner.parse_ledger_lines("\n".join(rows) + "\n"), "run1")
    check("V2 nested_runner_windows: window opens at the nested runner's own GUARD_ARMED and closes at the same pid's next GUARD_ARMED",
          v2_w == {16360: [(2, 5)]}, v2_w)
    v2_other = runner.nested_runner_windows(runner.parse_ledger_lines("\n".join(rows) + "\n"), "another_run")
    check("V2 nested_runner_windows: NESTED_RUNNER records of another run id open no window", v2_other == {}, v2_other)
    check("module_guard_armed: matches by pid or by ppid (venv launcher indirection)",
          runner.module_guard_armed(recs, "run1", 10) and runner.module_guard_armed(recs, "run1", 9) and not runner.module_guard_armed(recs, "run1", 77) and not runner.module_guard_armed(recs, "other", 10))
    pc_ok, pc_fail = runner.evaluate_positive_controls({k: True for k in runner.POSITIVE_CONTROL_KEYS}, runner.parse_ledger_lines(
        "GUARD_ARMED\t1\t0\tr\tx\t[]\nGUARD_ARMED\t2\t1\tr\tx\t[]\nPOPEN\t1\tr\tnull\t[\"C:\\\\python.exe -c pass\"]\tnull\nPOPEN\t1\tr\tnull\t[\"C:\\\\python.exe -I -c pass\"]\tnull\n"
        "ENV_OPEN_BLOCKED\t1\tr\t.env\tabc\nENV_OPEN_BLOCKED\t1\tr\t.env.local\tabc\nNET_BLOCKED\t1\tr\tsocket.getaddrinfo\tx\nNET_BLOCKED\t1\tr\tsocket.connect\tx\nNET_BLOCKED\t1\tr\tsocket.sendto\tx\n"))
    check("positive-control evaluation: 10/10 with balanced ledger", pc_ok == 10 and pc_fail == [], pc_fail)
    pc_ok, pc_fail = runner.evaluate_positive_controls({k: True for k in runner.POSITIVE_CONTROL_KEYS[:-1]}, [])
    check("positive-control evaluation: a missing control fails closed", pc_ok == 9 and pc_fail, pc_fail)

    # -----------------------------------------------------------------------
    # 15./16./17. in-process post-run harness on a disposable git repository
    # -----------------------------------------------------------------------
    fr = BASE / "fakerepo"
    fr.mkdir()
    git_env = dict(os.environ)
    git_env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(BASE / "nogitconfig"), "HOME": str(BASE), "USERPROFILE": str(BASE)})

    def git(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false"] + list(a),
                              cwd=str(fr), env=git_env, capture_output=True, timeout=60)
    (fr / "a.txt").write_text("tracked\n")
    (fr / "data").mkdir()
    (fr / "data" / "d.txt").write_text("data\n")
    (fr / "__pycache__").mkdir()
    (fr / "__pycache__" / "pre.cpython-314.pyc").write_bytes(b"old")
    git_ok = git("init", "-q").returncode == 0 and git("add", "a.txt", "data/d.txt").returncode == 0 and git("commit", "-q", "-m", "init").returncode == 0
    check("harness: disposable git repository initialised", git_ok)
    if git_ok:
        hr = BASE / "harness_run"
        (hr / "logs").mkdir(parents=True)
        (hr / "tmp").mkdir()
        sw3 = runner.Sweep(make_args(profile="production-parity"), {"SOME_PASSWORD_X": "supersecretvalue123", "PATH": os.environ.get("PATH", "")}, str(fr), io.StringIO())
        sw3.run_dir = str(hr)
        sw3.tmp_dir = str(hr / "tmp")
        sw3.ledger_path = str(hr / "guard_ledger.tsv")
        (hr / "guard_ledger.tsv").write_text("GUARD_ARMED\t1\t0\t%s\tx\t[]\n" % sw3.run_id, encoding="utf-8")
        sw3.pg_dsn = None
        sw3.manifest_before = runner.protected_path_manifest(str(fr))
        sw3.bytecode_before = runner.bytecode_manifest(str(fr))
        check("harness: opening manifest covers tracked files, data tree and git status", {"a.txt", "data/d.txt", "<git status data/cases index>"} <= set(sw3.manifest_before))
        (fr / "a.txt").write_text("TAMPERED\n")
        (fr / "data" / "new.txt").write_text("new\n")
        (fr / "__pycache__" / "new.cpython-314.pyc").write_bytes(b"new")
        log = hr / "logs" / "test_fake.stdout.bin"
        log.write_bytes(b"PASS x\nconninfo password=supersecretvalue123 host=x\n--- test_fake: 1 passed, 0 failed ---\n")
        elog = hr / "logs" / "test_fake.stderr.bin"
        elog.write_bytes(b"")
        (hr / "tmp" / "leftover").mkdir()
        sw3.report["modules"] = [{"name": "test_fake", "temp_residue": ["leftover"], "stdout_log": str(log), "stderr_log": str(elog), "informational_skips": 0}]
        sw3.phase_post_run()
        kinds = [f["kind"] for f in sw3.integrity_failures]
        diffs = sw3.report["integrity"]["protected_path_diff"]
        check("protected-path diff: modified tracked file and new data file detected", "PROTECTED_PATH_DIFF" in kinds and {(d["path"], d["change"]) for d in diffs} >= {("a.txt", "modified"), ("data/new.txt", "new")}, diffs)
        check("protected-path diff: runner did NOT revert the tampered file", (fr / "a.txt").read_text() == "TAMPERED\n")
        check("bytecode: pre-existing .pyc untouched, new .pyc removed and logged",
              (fr / "__pycache__" / "pre.cpython-314.pyc").exists() and not (fr / "__pycache__" / "new.cpython-314.pyc").exists()
              and sw3.report["integrity"]["bytecode_residue"] == ["__pycache__/new.cpython-314.pyc"], sw3.report["integrity"]["bytecode_residue"])
        check("secret scan: SECRET_LEAK_SUSPECTED with class names only", "SECRET_LEAK_SUSPECTED" in kinds and sw3.report["integrity"]["secret_scan"]["hits"] and
              all(set(h) == {"file", "classes"} for h in sw3.report["integrity"]["secret_scan"]["hits"]), sw3.report["integrity"]["secret_scan"])
        check("secret scan: the secret value never enters the report", "supersecretvalue123" not in json.dumps(sw3.report))
        check("temp residue: reported and fatal under production-parity", "TEMP_RESIDUE" in kinds)
        check("post-run integrity -> exit 3 overrides module PASS", runner.decide_exit_code("production-parity", ["PASS"], sw3.integrity_failures) == 3)
    check("scan_bytes_for_secrets: benign test labels do not trigger",
          runner.scan_bytes_for_secrets(b"PASS client_secret=None is rejected\nPASS client_secret='' (empty) is rejected\nPASS password=<redacted>\n", []) == [])
    check("scan_bytes_for_secrets: real-looking material triggers",
          "anthropic_key" in runner.scan_bytes_for_secrets(b"x sk-ant-abcdefghijklmnopqrstuvwxyz y", []) and
          "url_userinfo_password" in runner.scan_bytes_for_secrets(b"postgresql://u:p4ssw0rd@127.0.0.1/db", []) and
          "parent_env_value" in runner.scan_bytes_for_secrets(b"leak: SUPERSECRETVALUE-XYZ", [b"SUPERSECRETVALUE-XYZ"]))

    # -----------------------------------------------------------------------
    # 24. B1: Windows .env name folding -- pure classification + real guard child
    # -----------------------------------------------------------------------
    guard = importlib.import_module("scripts.sweep_env_guard")
    folded_blocked = [".env", ".ENV", ".Env", ".env.local", ".Env.local", ".ENV.LOCAL", ".env.production", ".env.", ".env ",
                      ".env. .", ".env::$DATA", ".env:stream", ".ENV::$DATA", ".env.local."]
    folded_allowed = [".envx", ".environment", ".ENVX", "env", ".en", "x.env", ".env_local", "a.env.local", "env.txt"]
    check("B1 pure: every .env family spelling is protected (case, trailing dot/space, NTFS stream)",
          all(guard.is_env_file_name(n) for n in folded_blocked), [n for n in folded_blocked if not guard.is_env_file_name(n)])
    check("B1 pure: non-members stay allowed (.envx, .environment, prefixes, other suffixes)",
          not any(guard.is_env_file_name(n) for n in folded_allowed), [n for n in folded_allowed if guard.is_env_file_name(n)])
    check("B1 pure: bytes and PathLike inputs are classified like str",
          guard.is_env_file_name(guard.basename_of(b"C:\\x\\.ENV")) and guard.is_env_file_name(guard.basename_of(Path("d") / ".Env.local")))
    check("B1 pure: drive-relative and \\\\?\\ spellings resolve to the protected basename",
          guard.basename_of("C:.env") == ".env" and guard.basename_of("\\\\?\\C:\\x\\.ENV") == ".ENV"
          and guard.is_env_file_name(guard.basename_of("C:.ENV.")) and guard.is_env_file_name(guard.basename_of("c:.env ")))
    check("B1 pure: normalize_windows_file_name folds case, trailing dots/spaces and stream suffixes",
          guard.normalize_windows_file_name(".ENV. ") == ".env" and guard.normalize_windows_file_name(".Env.Local::$DATA") == ".env.local"
          and guard.normalize_windows_file_name(".envx") == ".envx" and guard.normalize_windows_file_name("README.md") == "readme.md")
    code, out, err, report, run_dir = run_fake(BASE, "envcase", {"test_envcase": SRC_ENV_CASE})
    m = report and module_entry(report, "test_envcase")
    check("B1 guard child: 9 folded spellings blocked (PermissionError before any I/O) and .envx/.environment readable (11 checks PASS)",
          m is not None and m["outcome"] == "PASS" and m["passed"] == 11 and m["failed"] == 0,
          (code, m and (m["outcome"], m["passed"], m["failed"], m.get("detail")), last_line(out)))
    check("B1 guard child: ledger recorded exactly 9 ENV_OPEN_BLOCKED events for the folded spellings",
          report is not None and report["guard"]["env_open_blocked_count"] == 9, report and report["guard"]["env_open_blocked_count"])
    check("B1 guard child: run clean (exit 0, no integrity failures)",
          code == 0 and report is not None and report["integrity"]["failures"] == [], (code, report and report["integrity"]["failures"]))

    # -----------------------------------------------------------------------
    # 25. B2: Job containment -- Ctrl-C cleanup, assignment failure, creation failure
    # -----------------------------------------------------------------------
    real_popen = runner.subprocess.Popen
    base_job_cls = runner._JobObject

    def harness(tag, modules):
        d = BASE / tag
        for sub in ("run", "run/logs", "run/tmp", "tests"):
            (d / sub).mkdir(parents=True)
        for name, src in modules.items():
            write_module(d / "tests", name, src)
        sw = runner.Sweep(make_args(tests_dir=str(d / "tests")), {}, str(REPO_ROOT), io.StringIO())
        sw.run_dir = str(d / "run")
        sw.logs_dir = str(d / "run" / "logs")
        sw.tmp_dir = str(d / "run" / "tmp")
        sw.ledger_path = str(d / "run" / "guard_ledger.tsv")
        sw.tests_dir = str(d / "tests")
        sw.report_path = str(d / "run" / "report.json")
        sw.report["discovery"]["mode"] = "fake_dir"
        sw.child_env = dict(os.environ)
        sw.modules = list(modules)
        return d, sw

    if IS_WIN:
        class RecJob(base_job_cls):
            instances = []

            def __init__(self):
                base_job_cls.__init__(self)
                RecJob.instances.append(self)

    # (a) KeyboardInterrupt while a module with a live grandchild is running
    ki_dir, sw_ki = harness("ki", {"test_ki": SRC_KI_GRANDCHILD, "test_after": SRC_OK})
    spawned = []
    gpids = []

    def recording_popen(*a, **kw):
        proc = real_popen(*a, **kw)
        spawned.append(proc)
        return proc

    def interrupting_wait(proc):
        deadline = time.monotonic() + 90
        marker = ki_dir / "tests" / "grandchild.pid"
        while time.monotonic() < deadline:
            if marker.exists():
                gpids.append(int(marker.read_text().strip()))
                raise KeyboardInterrupt
            if proc.poll() is not None:
                raise RuntimeError("child exited before the grandchild was ready")
            time.sleep(0.1)
        raise RuntimeError("grandchild never reported")

    sw_ki._wait_module = interrupting_wait
    raised = False
    try:
        runner.subprocess.Popen = recording_popen
        if IS_WIN:
            runner._JobObject = RecJob
        try:
            runner.run_all_modules(sw_ki)
        except KeyboardInterrupt:
            raised = True
    finally:
        runner.subprocess.Popen = real_popen
        runner._JobObject = base_job_cls
    time.sleep(0.5)
    lc = sw_ki._last_module_cleanup or {}
    check("B2 ctrl-c: KeyboardInterrupt propagated out of run_all_modules (unwound, not swallowed)", raised)
    check("B2 ctrl-c: interrupted child terminated and waited (returncode set)", len(spawned) == 1 and spawned[0].poll() is not None, [x.poll() for x in spawned])
    check("B2 ctrl-c: grandchild is dead", bool(gpids) and not process_alive(gpids[0]), gpids)
    if IS_WIN:
        check("B2 ctrl-c: Job ActiveProcesses == 0 after cleanup", lc.get("job_active_after") == 0, lc)
        check("B2 ctrl-c: Job handle closed in the finally path",
              bool(RecJob.instances) and RecJob.instances[-1].handle is None and lc.get("job_handle_closed") is True, lc)
    else:
        skip_info("B2 ctrl-c job accounting", "Windows-only Job Object")
    check("B2 ctrl-c: no cleanup problems recorded (none hidden either)", lc.get("cleanup_problems") == [], lc)
    check("B2 ctrl-c: aborted_module recorded in the report with the cleanup outcome",
          sw_ki.report.get("aborted_module", {}).get("name") == "test_ki" and "job_active_after" in sw_ki.report.get("aborted_module", {}), sw_ki.report.get("aborted_module"))
    check("B2 ctrl-c: the next module was never spawned", len(spawned) == 1 and not (ki_dir / "run" / "logs" / "test_after.stdout.bin").exists(), len(spawned))
    rc = sw_ki.finish(runner.EXIT_ABORTED, aborted=True)
    abr = load_report(ki_dir / "run")
    check("B2 ctrl-c: partial report state=aborted, label ABORTED, exit 130, aborted_module present",
          rc == 130 and abr["state"] == "aborted" and abr["sweep_label"] == "ABORTED" and abr["runner_exit_code"] == 130
          and abr.get("aborted_module", {}).get("name") == "test_ki", (rc, abr["state"], abr["sweep_label"]))

    if IS_WIN:
        # (b) AssignProcessToJobObject failure: the suspended child is killed before
        # it executes a single instruction, the sweep stops, exit 3
        af_dir, sw_af = harness("assignfail", {"test_af": SRC_OK, "test_after2": SRC_OK})
        marker_af = af_dir / "ran.txt"
        spawned_af = []

        def seam_popen(argv, **kw):
            # real, allowlisted, NON-python executable (keeps the parent sweep's
            # python accounting balanced); creationflags from the runner are kept
            proc = real_popen(["cmd.exe", "/c", "echo ran > \"%s\"" % marker_af], **kw)
            spawned_af.append(proc)
            return proc

        saved_assign = base_job_cls.assign

        def failing_assign(self, handle):
            raise OSError(1234, "simulated AssignProcessToJobObject failure")

        completed = None
        try:
            runner.subprocess.Popen = seam_popen
            base_job_cls.assign = failing_assign
            runner._JobObject = RecJob
            completed = runner.run_all_modules(sw_af)
        finally:
            runner.subprocess.Popen = real_popen
            base_job_cls.assign = saved_assign
            runner._JobObject = base_job_cls
        time.sleep(0.3)
        entry_af = sw_af.report["modules"][0] if sw_af.report["modules"] else None
        kinds_af = [f["kind"] for f in sw_af.integrity_failures]
        check("B2 assign failure: module outcome JOB_CONTAINMENT_FAILURE at stage assign (not SPAWN_FAILURE)",
              entry_af is not None and entry_af["outcome"] == "JOB_CONTAINMENT_FAILURE" and "stage assign" in entry_af["detail"], entry_af)
        check("B2 assign failure: integrity failure recorded and the sweep STOPPED after the module",
              "JOB_CONTAINMENT_FAILURE" in kinds_af and completed is False and sw_af.report.get("stopped", {}).get("after_module") == "test_af"
              and sw_af.report.get("stopped", {}).get("modules_not_run") == ["test_after2"], (kinds_af, sw_af.report.get("stopped")))
        check("B2 assign failure: child killed and waited before executing anything (no marker file, returncode set)",
              len(spawned_af) == 1 and spawned_af[0].poll() is not None and not marker_af.exists(), (len(spawned_af), marker_af.exists()))
        lc2 = sw_af._last_module_cleanup or {}
        check("B2 assign failure: Job ActiveProcesses == 0 and handle closed",
              lc2.get("job_active_after") == 0 and lc2.get("job_handle_closed") is True and RecJob.instances[-1].handle is None, lc2)
        check("B2 assign failure: no cleanup problems", lc2.get("cleanup_problems") == [], lc2)
        check("B2 assign failure: containment-failed module excluded from the guard root count (its child never executed, "
              "so it cannot have armed) -- no piggybacked GUARD_INHERITANCE_MISMATCH; the count matters to the pure accounting",
              len(sw_af.report["modules"]) == 1 and sw_af._module_root_count() == 0
              and runner.guard_accounting([], sw_af.run_id, 0)["inheritance_ok"] is True
              and runner.guard_accounting([], sw_af.run_id, 1)["inheritance_ok"] is False,
              (len(sw_af.report["modules"]), sw_af._module_root_count()))
        check("B2 assign failure: the remaining module was never spawned",
              len(spawned_af) == 1 and not (af_dir / "run" / "logs" / "test_after2.stdout.bin").exists())
        rc_af = sw_af.finish(runner.decide_exit_code("production-parity", sw_af.module_outcomes, sw_af.integrity_failures))
        check("B2 assign failure: exit 3 (integrity), report state stopped, labels PARTIAL/RAG_GATE_FAIL never FULL/RAG_GATE_PASS",
              rc_af == 3 and sw_af.report["state"] == "stopped" and runner.sweep_label("production-parity", 3) == "PARTIAL"
              and runner.sweep_label("rag-dependency", 3) == "RAG_GATE_FAIL", (rc_af, sw_af.report["state"]))
        # (b2) KeyboardInterrupt raised INSIDE the assignment step: the child was
        # spawned (suspended) but never became a job member, so TerminateJobObject
        # cannot reach it and the empty job truthfully reports ActiveProcesses 0.
        # The unconditional finally must kill the DIRECT child itself: dead within
        # seconds (no 30 s wait for a child that can never exit on its own), the
        # marker is never written, handle closed, nothing hidden.
        ka_dir, sw_ka = harness("assignki", {"test_ka": SRC_OK, "test_after3": SRC_OK})
        marker_ka = ka_dir / "ran.txt"
        spawned_ka = []

        def seam_popen_ka(argv, **kw):
            proc = real_popen(["cmd.exe", "/c", "echo ran > \"%s\"" % marker_ka], **kw)
            spawned_ka.append(proc)
            return proc

        def interrupting_assign(self, handle):
            raise KeyboardInterrupt

        raised_ka = False
        t_ka = time.monotonic()
        try:
            runner.subprocess.Popen = seam_popen_ka
            base_job_cls.assign = interrupting_assign
            runner._JobObject = RecJob
            try:
                runner.run_all_modules(sw_ka)
            except KeyboardInterrupt:
                raised_ka = True
        finally:
            runner.subprocess.Popen = real_popen
            base_job_cls.assign = saved_assign
            runner._JobObject = base_job_cls
        elapsed_ka = time.monotonic() - t_ka
        time.sleep(0.3)
        lc3 = sw_ka._last_module_cleanup or {}
        check("B2 ctrl-c at assign: KeyboardInterrupt propagated out of run_all_modules (not swallowed)", raised_ka)
        check("B2 ctrl-c at assign: never-member suspended child killed directly and waited within seconds (no 30 s timeout), "
              "marker never written",
              len(spawned_ka) == 1 and spawned_ka[0].poll() is not None and not marker_ka.exists() and elapsed_ka < 10.0,
              (len(spawned_ka), [x.poll() for x in spawned_ka], marker_ka.exists(), round(elapsed_ka, 2)))
        check("B2 ctrl-c at assign: child is dead at OS level", bool(spawned_ka) and not process_alive(spawned_ka[0].pid),
              [x.pid for x in spawned_ka])
        check("B2 ctrl-c at assign: Job ActiveProcesses == 0, handle closed, no cleanup problems (none hidden)",
              lc3.get("job_active_after") == 0 and lc3.get("job_handle_closed") is True and RecJob.instances[-1].handle is None
              and lc3.get("cleanup_problems") == [], lc3)
        check("B2 ctrl-c at assign: aborted_module recorded, the next module was never spawned",
              sw_ka.report.get("aborted_module", {}).get("name") == "test_ka" and len(spawned_ka) == 1
              and not (ka_dir / "run" / "logs" / "test_after3.stdout.bin").exists(), sw_ka.report.get("aborted_module"))
        # (c) Job Object creation failure: refusal BEFORE any spawn (N.2: exit 2)
        jc_dir, sw_jc = harness("jobcreate", {"test_jc": SRC_OK})
        spawned_jc = []

        def counting_popen(*a, **kw):
            proc = real_popen(*a, **kw)
            spawned_jc.append(proc)
            return proc

        saved_init = base_job_cls.__init__

        def failing_init(self):
            raise OSError(5, "simulated CreateJobObjectW failure")

        refused = None
        try:
            runner.subprocess.Popen = counting_popen
            base_job_cls.__init__ = failing_init
            try:
                sw_jc.run_module("test_jc")
                refused = False
            except runner.Refusal as exc:
                refused = "JOB_OBJECT" in str(exc)
        finally:
            runner.subprocess.Popen = real_popen
            base_job_cls.__init__ = saved_init
        check("B2 job creation failure: JOB_OBJECT refusal raised, module NOT spawned, no log files, refusal recorded",
              refused is True and spawned_jc == [] and not (jc_dir / "run" / "logs" / "test_jc.stdout.bin").exists()
              and sw_jc.report["refusals"] and sw_jc.report["refusals"][-1]["code"] == "JOB_OBJECT", (refused, len(spawned_jc), sw_jc.report["refusals"]))
        check("B2 job creation failure: refusal exit 2 (N.2), never 0/1", runner.decide_exit_code("production-parity", [], [], refused=True) == 2)

        # (d) B2-R1: Job Object creation failure AFTER at least one module ran,
        #     end-to-end through the real main() in a separate driver process. A
        #     driver is a nested runner: it announces itself, so a parent sweep's
        #     guard accounting stays balanced (an in-process main() here would
        #     not). Only run_module() constructs _JobObject, so "the N-th
        #     instantiation fails" is exactly "the N-th module's creation fails".
        driver = BASE / "b2r1_driver.py"
        driver.write_text(
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "import scripts.run_ui_tests as runner\n"
            "FAIL_AT = int(sys.argv[1])\n"
            "_base = runner._JobObject\n"
            "class _FailingJob(_base):\n"
            "    count = 0\n"
            "    def __init__(self):\n"
            "        _FailingJob.count += 1\n"
            "        if _FailingJob.count == FAIL_AT:\n"
            "            raise OSError(1450, 'simulated CreateJobObjectW failure (driver)')\n"
            "        _base.__init__(self)\n"
            "runner._JobObject = _FailingJob\n"
            "sys.exit(runner.main(sys.argv[2:]))\n" % str(REPO_ROOT), encoding="utf-8", newline="\n")

        def run_driver(tag, fail_at):
            tests_dir = BASE / f"fake_{tag}"
            out_root = BASE / f"out_{tag}"
            tests_dir.mkdir()
            for name in ("test_jd1", "test_jd2", "test_jd3"):
                write_module(tests_dir, name, SRC_OK.replace("{n}", name))
            code, out, err = spawn_runner([str(fail_at), "--profile", "developer", "--tests-dir", str(tests_dir), "--output-root", str(out_root)], script=driver)
            rd = find_run_dir(out_root)
            rep = load_report(rd) if rd and (rd / "report.json").exists() else None
            note_nested_tmp(rep)
            return code, out, err, rep, rd

        code_l, out_l, err_l, rep_l, rd_l = run_driver("jd_late", 2)
        mods_l = (rep_l or {}).get("modules", [])
        integ_l = (rep_l or {}).get("integrity", {})
        check("B2-R1 late creation failure (2nd module): exit 3, NOT a refusal, state stopped, label DIAGNOSTIC",
              code_l == 3 and rep_l is not None and rep_l["refusals"] == [] and rep_l["state"] == "stopped"
              and rep_l["runner_exit_code"] == 3 and rep_l["sweep_label"] == "DIAGNOSTIC" and "REFUSED" not in out_l,
              (code_l, rep_l and rep_l.get("refusals"), rep_l and rep_l.get("state"), last_line(out_l), err_l[-400:]))
        check("B2-R1 late: 1st module PASS + spawned; 2nd JOB_CONTAINMENT_FAILURE stage create, never spawned (exit_code None, spawned False, guard_armed False); 3rd absent",
              [m["name"] for m in mods_l] == ["test_jd1", "test_jd2"] and mods_l[0]["outcome"] == "PASS" and mods_l[0].get("spawned") is True
              and mods_l[1]["outcome"] == "JOB_CONTAINMENT_FAILURE" and mods_l[1].get("spawned") is False and mods_l[1]["exit_code"] is None
              and mods_l[1]["guard_armed"] is False and "stage create" in mods_l[1]["detail"] and "NOT spawned" in mods_l[1]["detail"],
              mods_l)
        check("B2-R1 late: stopped record names the failed module and the never-run remainder",
              rep_l is not None and rep_l.get("stopped") == {"after_module": "test_jd2", "reason": "JOB_CONTAINMENT_FAILURE[test_jd2] stage=create", "modules_not_run": ["test_jd3"]},
              rep_l and rep_l.get("stopped"))
        check("B2-R1 late: exactly one integrity failure -- JOB_CONTAINMENT_FAILURE, stage create, error OSError",
              integ_l.get("failures") == [{"kind": "JOB_CONTAINMENT_FAILURE", "module": "test_jd2", "stage": "create", "error": "OSError"}],
              integ_l.get("failures"))
        check("B2-R1 late: phase_post_run RAN (protected manifest ok, db residue / bytecode keys present); secret scan counted only the 2 real log files, no hits",
              integ_l.get("protected_manifest_ok") is True and "db_residue" in integ_l and "bytecode_residue" in integ_l
              and integ_l.get("secret_scan", {}).get("files_scanned") == 2 and integ_l.get("secret_scan", {}).get("hits") == [],
              integ_l)
        check("B2-R1 late: guard accounting balanced (armed 1 == expected 1; the never-spawned module is excluded)",
              rep_l is not None and rep_l["guard"].get("inheritance_ok") is True and rep_l["guard"].get("armed_count") == 1 and rep_l["guard"].get("expected_armed") == 1,
              rep_l and rep_l.get("guard"))
        check("B2-R1 late: only the first module has log files",
              rd_l is not None and (rd_l / "logs" / "test_jd1.stdout.bin").exists()
              and not (rd_l / "logs" / "test_jd2.stdout.bin").exists() and not (rd_l / "logs" / "test_jd3.stdout.bin").exists(),
              rd_l and sorted(q.name for q in (rd_l / "logs").iterdir()))
        check("B2-R1 late: totals -- modules_run 1, modules_attempted 2, modules_not_spawned 1, pass 1, non-pass 1",
              rep_l is not None and rep_l["totals"].get("modules_run") == 1 and rep_l["totals"].get("modules_attempted") == 2
              and rep_l["totals"].get("modules_not_spawned") == 1 and rep_l["totals"].get("modules_pass") == 1 and rep_l["totals"].get("modules_non_pass") == 1,
              rep_l and rep_l.get("totals"))
        check("B2-R1 late: console carries the MODULE/STOP lines and ends with SWEEP DIAGNOSTIC - exit 3",
              "MODULE test_jd2 JOB_CONTAINMENT_FAILURE stage=create error=OSError -> STOP" in out_l
              and "STOP JOB_CONTAINMENT_FAILURE[test_jd2] stage=create - 1 remaining module(s) NOT spawned" in out_l
              and last_line(out_l) == "SWEEP DIAGNOSTIC - exit 3", (last_line(out_l), out_l[-600:]))
        # (e) B2-R1: creation failure BEFORE the first module stays a refusal (exit 2), same driver
        code_e, out_e, err_e, rep_e, rd_e = run_driver("jd_early", 1)
        check("B2-R1 early creation failure (1st module): still refusal JOB_OBJECT, exit 2, no module entry, nothing spawned, no stop record",
              code_e == 2 and rep_e is not None and rep_e["modules"] == [] and rep_e["refusals"] and rep_e["refusals"][-1]["code"] == "JOB_OBJECT"
              and "stopped" not in rep_e and "REFUSED JOB_OBJECT:" in out_e and last_line(out_e) == "SWEEP DIAGNOSTIC - exit 2"
              and rd_e is not None and not (rd_e / "logs" / "test_jd1.stdout.bin").exists(),
              (code_e, rep_e and rep_e.get("refusals"), last_line(out_e), err_e[-400:]))
    else:
        skip_info("B2 assignment/creation failure seams", "Windows-only Job Object")

    # -----------------------------------------------------------------------
    # 26. B3: rag gate K.1 exact -- informational skips across ALL modules
    # -----------------------------------------------------------------------
    fr2 = BASE / "fakerepo_rag"
    fr2.mkdir()

    def git2(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false"] + list(a),
                              cwd=str(fr2), env=git_env, capture_output=True, timeout=60)
    (fr2 / "a.txt").write_text("tracked\n")
    git2_ok = git2("init", "-q").returncode == 0 and git2("add", "a.txt").returncode == 0 and git2("commit", "-q", "-m", "init").returncode == 0
    check("B3 harness: disposable git repository initialised", git2_ok)
    if git2_ok:
        hr2 = BASE / "harness_rag"
        (hr2 / "logs").mkdir(parents=True)
        (hr2 / "tmp").mkdir()
        rag_logs = {}
        smoke_with_marker = b"PASS z\n--- test_rag_bundle_dependency_smoke: 1 passed, 0 failed, 0 skipped ---\nDEPENDENCY GATE: PASS\n"
        for name, body in (("test_rag_bundle_builder_isolated", b"PASS x\nSKIPPED posix self-loop (NOT counted as pass/fail)\n--- test_rag_bundle_builder_isolated: 1 passed, 0 failed, 1 informational skips ---\n"),
                           ("test_rag_bundle_reader_isolated", b"PASS y\n--- test_rag_bundle_reader_isolated: 1 passed, 0 failed ---\n"),
                           ("test_rag_bundle_dependency_smoke", smoke_with_marker)):
            (hr2 / "logs" / (name + ".stdout.bin")).write_bytes(body)
            (hr2 / "logs" / (name + ".stderr.bin")).write_bytes(b"")
            rag_logs[name] = (str(hr2 / "logs" / (name + ".stdout.bin")), str(hr2 / "logs" / (name + ".stderr.bin")))

        def rag_sweep(builder_info):
            sw = runner.Sweep(make_args(profile="rag-dependency"), {"PATH": os.environ.get("PATH", "")}, str(fr2), io.StringIO())
            sw.run_dir = str(hr2)
            sw.tmp_dir = str(hr2 / "tmp")
            sw.ledger_path = str(hr2 / "guard_ledger.tsv")
            (hr2 / "guard_ledger.tsv").write_text("".join("GUARD_ARMED\t%d\t0\t%s\tx\t[]\n" % (i + 1, sw.run_id) for i in range(3)), encoding="utf-8")
            sw.pg_dsn = None
            sw.manifest_before = runner.protected_path_manifest(str(fr2))
            sw.bytecode_before = runner.bytecode_manifest(str(fr2))
            sw.report["modules"] = []
            for name in runner.RAG_GATE_MODULES:
                info = builder_info if name == "test_rag_bundle_builder_isolated" else 0
                sw.report["modules"].append({"name": name, "outcome": "PASS", "passed": 1, "failed": 0, "counted_skips": 0,
                                             "informational_skips": info, "temp_residue": [], "guard_armed": True,
                                             "stdout_log": rag_logs[name][0], "stderr_log": rag_logs[name][1]})
                sw.module_outcomes.append("PASS")
            sw.phase_post_run()
            return sw

        sw_gate_fail = rag_sweep(1)
        rg = sw_gate_fail.report.get("rag_gate") or {}
        warn = " | ".join(sw_gate_fail.report["warnings"])
        check("B3 gate: three PASS + smoke informational 0 + builder informational 1 -> FAIL appended, exit 1, RAG_GATE_FAIL",
              "FAIL" in sw_gate_fail.module_outcomes and rg.get("informational_skips_all_modules") == 1 and rg.get("informational_skips_smoke") == 0
              and rg.get("marker_present") is True and sw_gate_fail.integrity_failures == []
              and runner.decide_exit_code("rag-dependency", sw_gate_fail.module_outcomes, sw_gate_fail.integrity_failures) == 1
              and runner.sweep_label("rag-dependency", 1) == "RAG_GATE_FAIL", (sw_gate_fail.module_outcomes, rg, sw_gate_fail.integrity_failures))
        check("B3 gate: the warning names the offending module and the K.1 all-modules rule",
              "test_rag_bundle_builder_isolated=1" in warn and "K.1" in warn and "all modules" in warn, warn)
        sw_gate_ok = rag_sweep(0)
        rg2 = sw_gate_ok.report.get("rag_gate") or {}
        check("B3 gate: three PASS + informational 0 on ALL modules + marker -> no FAIL, exit 0, RAG_GATE_PASS (gate is not a constant FAIL)",
              "FAIL" not in sw_gate_ok.module_outcomes and rg2.get("informational_skips_all_modules") == 0 and rg2.get("marker_present") is True
              and sw_gate_ok.integrity_failures == []
              and runner.decide_exit_code("rag-dependency", sw_gate_ok.module_outcomes, sw_gate_ok.integrity_failures) == 0
              and runner.sweep_label("rag-dependency", 0) == "RAG_GATE_PASS", (sw_gate_ok.module_outcomes, rg2, sw_gate_ok.integrity_failures))
        (hr2 / "logs" / "test_rag_bundle_dependency_smoke.stdout.bin").write_bytes(smoke_with_marker.replace(b"DEPENDENCY GATE: PASS\n", b""))
        sw_gate_nomarker = rag_sweep(0)
        check("B3 gate: marker line absent alone -> FAIL (exit 1)",
              "FAIL" in sw_gate_nomarker.module_outcomes and (sw_gate_nomarker.report.get("rag_gate") or {}).get("marker_present") is False
              and runner.decide_exit_code("rag-dependency", sw_gate_nomarker.module_outcomes, sw_gate_nomarker.integrity_failures) == 1,
              (sw_gate_nomarker.module_outcomes, sw_gate_nomarker.report.get("rag_gate")))

    # -----------------------------------------------------------------------
    # 27. B4: case-insensitive suspicious subprocess patterns -- pure + nested
    # -----------------------------------------------------------------------
    variants = ["Invoke-WebRequest", "invoke-webrequest", "INVOKE-WEBREQUEST", "http://x", "HTTP://X", "https://x", "HTTPS://X", "HtTpS://x"]
    check("B4 pure: every case variant of Invoke-/http://https:// is suspicious through allowlisted cmd.exe AND python",
          all(runner.popen_is_suspicious(["cmd.exe", "/c", "echo", v]) is not None and runner.popen_is_suspicious(["python.exe", "-c", "pass", v]) is not None for v in variants),
          [v for v in variants if runner.popen_is_suspicious(["cmd.exe", "/c", "echo", v]) is None or runner.popen_is_suspicious(["python.exe", "-c", "pass", v]) is None])
    check("B4 pure: Windows joined command line with an upper-case token is suspicious",
          runner.popen_is_suspicious(['C:\\Windows\\System32\\cmd.exe /c "echo INVOKE-WEBREQUEST"']) is not None
          and runner.popen_is_suspicious(['C:\\p\\python.exe -c pass HTTPS://x']) is not None)
    check("B4 pure: benign cmd.exe/python tokens stay allowed",
          all(runner.popen_is_suspicious(a) is None for a in (["cmd.exe", "/c", "echo", "hello"], ["cmd.exe", "/c", "dir"],
                                                                 ["python.exe", "-c", "print('httpx')"], ["python.exe", "-m", "ui.tests.test_invoke_x"])))
    code, out, err, report, run_dir = run_fake(BASE, "upperurl", {"test_upperurl": SRC_UPPER_URL})
    check("B4 nested: fake module spawning python with an 'HTTPS://' token -> SUSPICIOUS_SUBPROCESS, exit 3",
          code == 3 and report is not None and any(f["kind"] == "SUSPICIOUS_SUBPROCESS" for f in report["integrity"]["failures"]),
          (code, report and report["integrity"]["failures"], last_line(out)))
    if IS_WIN:
        code, out, err, report, run_dir = run_fake(BASE, "cmdinvoke", {"test_cmdinvoke": SRC_CMD_INVOKE})
        check("B4 nested: allowlisted cmd.exe carrying INVOKE-WEBREQUEST -> SUSPICIOUS_SUBPROCESS, exit 3",
              code == 3 and report is not None and any(f["kind"] == "SUSPICIOUS_SUBPROCESS" for f in report["integrity"]["failures"]),
              (code, report and report["integrity"]["failures"], last_line(out)))
    else:
        skip_info("B4 nested cmd.exe variant", "Windows-only")

    # -----------------------------------------------------------------------
    # 28. B5: static value-leak regression on T.2 and the runner's refusal texts
    # -----------------------------------------------------------------------
    t2_src = (REPO_ROOT / "ui" / "tests" / "test_run_ui_tests_integration_postgres.py").read_text(encoding="utf-8")
    print_lines = [ln for ln in t2_src.splitlines() if "print(" in ln]
    check("B5 static: T.2 startup line no longer interpolates the database name",
          "dbname={PG_DB" not in t2_src and "{PG_DB!r}" not in t2_src and "database target configured (name not printed)" in t2_src)
    check("B5 static: no print() in T.2 interpolates PG_DB / MAINTENANCE_DB / PG env values",
          not any(("PG_DB" in ln or "MAINTENANCE_DB" in ln or "PGPASSWORD" in ln or "PGHOST" in ln or "PGUSER" in ln or "PGPORT" in ln) and "{" in ln for ln in print_lines),
          [ln.strip()[:80] for ln in print_lines if ("PG_DB" in ln or "MAINTENANCE_DB" in ln or "PG" in ln) and "{" in ln])
    check("B5 static: T.2 check()/skip() labels AND details are redacted before printing",
          'print(f"PASS {redact(label)}")' in t2_src and 'print(f"FAIL {redact(label)} {redact(detail)}")' in t2_src
          and 'print(f"SKIPPED {redact(label)} - {redact(detail)}")' in t2_src)
    t2_tree = ast.parse(t2_src)

    def t2_calls(fn):
        return sum(1 for n in ast.walk(t2_tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == fn)

    # B5-R1 structural rule (replaces the former "spawn count == scan count"
    # equality, which a scan placed before a raising load_report(), or a
    # timeout, could satisfy without ever scanning).
    def t2_calls_in(node, fn):
        return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == fn]

    t2_funcs = {n.name: n for n in ast.walk(t2_tree) if isinstance(n, ast.FunctionDef)}
    sas = t2_funcs.get("spawn_and_scan")
    sas_defs = sum(1 for n in ast.walk(t2_tree) if isinstance(n, ast.FunctionDef) and n.name == "spawn_and_scan")
    outer_try = next((n for n in sas.body if isinstance(n, ast.Try)), None) if sas else None
    scan_all = t2_calls_in(t2_tree, "scan_pg_value_leaks")
    scan_in_finally = sum(len(t2_calls_in(s, "scan_pg_value_leaks")) for s in (outer_try.finalbody if outer_try else []))
    raw_all = t2_calls_in(t2_tree, "_spawn_runner_unscanned")
    raw_in_try_body = sum(len(t2_calls_in(s, "_spawn_runner_unscanned")) for s in (outer_try.body if outer_try else []))
    raw_fn = t2_funcs.get("_spawn_runner_unscanned")

    def t2_subprocess_calls(node):
        return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"
                and n.func.attr in ("run", "Popen", "call", "check_call", "check_output")]

    sas_sites = t2_calls_in(t2_tree, "spawn_and_scan")
    sas_tags = {c.args[0].value for c in sas_sites if c.args and isinstance(c.args[0], ast.Constant)}
    check("B5-R1 static: T.2 defines exactly one spawn_and_scan() whose outer try/finally holds the module's ONLY scan_pg_value_leaks() call in its finally",
          sas_defs == 1 and outer_try is not None and len(outer_try.finalbody) >= 1 and len(scan_all) == 1 and scan_in_finally == 1
          and "scan_pg_value_leaks(tag, out, err, run_dir)" in t2_src,
          (sas_defs, len(scan_all), scan_in_finally))
    check("B5-R1 static: the raw spawner _spawn_runner_unscanned() is called exactly once in T.2, inside spawn_and_scan's try body",
          raw_fn is not None and len(raw_all) == 1 and raw_in_try_body == 1, (len(raw_all), raw_in_try_body))
    check("B5-R1 static: every subprocess.* call in T.2 lives inside the raw spawner (no second spawn path)",
          raw_fn is not None and len(t2_subprocess_calls(t2_tree)) >= 1 and len(t2_subprocess_calls(t2_tree)) == len(t2_subprocess_calls(raw_fn)),
          (len(t2_subprocess_calls(t2_tree)), raw_fn and len(t2_subprocess_calls(raw_fn))))
    check("B5-R1 static: run_fake + S4 + S5 + S7 go through spawn_and_scan (>= 4 call sites with the S4/S5/S7 tags); the old spawn_runner name is gone",
          len(sas_sites) >= 4 and {"s4_rag", "s5_same_target", "s7_concurrent"} <= sas_tags and "spawn_runner(" not in t2_src
          and t2_calls("spawn_runner") == 0, (len(sas_sites), sorted(sas_tags)))
    check("B5-R1 static: T.2 has a top-level fail-closed boundary (except BaseException -> _record_unhandled) and a redacting sys.excepthook",
          "except BaseException as _unhandled:" in t2_src and "_record_unhandled(_unhandled)" in t2_src
          and "sys.excepthook = _redacting_excepthook" in t2_src and "traceback.extract_tb" in t2_src,
          [ln.strip()[:60] for ln in t2_src.splitlines() if "excepthook" in ln])
    # V1: T.2's log scan exempts the REAL rag module's own one-line startup banner (it carries the
    # database name; the raw log is a private run-directory file). The exemption must stay the
    # narrowest possible: one tag, one exact whole-line pattern, first occurrence only. T.1 is
    # PostgreSQL-less and cannot run S4; the proof that S4 itself is green is T.2 in real mode.
    v1_table = None
    for v1_node in t2_tree.body:
        if isinstance(v1_node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "LOG_BANNER_EXEMPTION_PATTERNS_BY_TAG" for t in v1_node.targets):
            v1_table = ast.literal_eval(v1_node.value)
    check("V1 static: the exemption table has exactly one tag (s4_rag) and exactly one string pattern (it cannot silently widen)",
          isinstance(v1_table, dict) and list(v1_table) == ["s4_rag"] and isinstance(v1_table["s4_rag"], str), v1_table)
    v1_rx = re.compile(v1_table["s4_rag"]) if isinstance(v1_table, dict) and isinstance(v1_table.get("s4_rag"), str) else None
    v1_banner = "backend: REAL psycopg 3.3.5 (production driver), dbname='zz_sample_db'"
    check("V1 pattern: masks exactly the banner line (LF and CRLF line ends) and only its first occurrence",
          v1_rx is not None
          and v1_rx.sub("", v1_banner + "\nPASS a\n", count=1) == "\nPASS a\n"
          and v1_rx.sub("", v1_banner + "\r\nPASS a\r\n", count=1) == "\nPASS a\r\n"
          and v1_rx.sub("", v1_banner + "\n" + v1_banner + "\n", count=1) == "\n" + v1_banner + "\n")
    v1_wider = (v1_banner + " user=zz_sample_user", "x " + v1_banner, "PASS " + v1_banner,
                "backend: FAKE psycopg 3.3.5 (production driver), dbname='zz_sample_db'",
                "backend: REAL psycopg 3.3.5 (production driver), dbname='zz_sample_db' password=zz",
                "conninfo dbname='zz_sample_db' host=zz")
    check("V1 pattern: does NOT mask anything wider than the banner (extra text, another prefix, other keys, a password, a mid-line position)",
          v1_rx is not None and all(v1_rx.search(text) is None for text in v1_wider), [t for t in v1_wider if v1_rx and v1_rx.search(t)])
    rag_src = (REPO_ROOT / "ui" / "tests" / "test_rag_bundle_mutation_integration_postgres.py").read_text(encoding="utf-8")
    check("V1 drift guard: the byte-locked rag module still prints exactly that banner and the pattern matches its rendering",
          'print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")' in rag_src and v1_rx is not None
          and v1_rx.search("backend: REAL psycopg %s (production driver), dbname=%r" % ("9.9.9", "zz_sample_db")) is not None)
    check("V1 static: the exemption is applied only inside scan_pg_value_leaks, only to the real rag module's stdout log, first occurrence only",
          "banner_exempt = LOG_BANNER_EXEMPTION_BY_TAG.get(tag)" in t2_src and 'f.name == RAG_MODULE + ".stdout.bin"' in t2_src
          and 'banner_exempt.sub("", log_text, count=1)' in t2_src and "def scan_pg_value_leaks(tag, out, err, run_dir):" in t2_src)
    check("B5 static: runner PG refusal messages never embed the offending value",
          "postgresql://u:p@h/db" not in (runner.validate_pg_dsn_name("postgresql://u:p@h/db") or "") and "u:p@h" not in (runner.validate_pg_dsn_name("postgresql://u:p@h/db") or "")
          and "10.0.0.5" not in (runner.validate_pghost("10.0.0.5") or "x") and "99999" not in (runner.validate_pgport("99999") or "x")
          and "abc" not in (runner.validate_pgport("abc") or "x") and "bad name" not in (runner.validate_pg_dsn_name("bad name") or "x"))

    # B5-R1 fail-path proofs: the REAL T.2 module as a subprocess against a fake
    # psycopg package whose every failure message embeds sentinel PG env values.
    # T.1 is PostgreSQL-less by design; the fake goes on PYTHONPATH in FRONT of
    # the existing entries (a parent sweep's guard directory stays on it, so its
    # sitecustomize still arms and the accounting stays balanced). PGHOST stays
    # loopback (T.2 deliberately never scans loopback literals) and PGPORT is not
    # a multiple of 4 (never a Windows pid) so the digit-bounded check is real.
    T2_PATH = REPO_ROOT / "ui" / "tests" / "test_run_ui_tests_integration_postgres.py"
    T2_MODULE = "test_run_ui_tests_integration_postgres"
    fake_pkg = BASE / "fake_psycopg" / "psycopg"
    fake_pkg.mkdir(parents=True)
    (fake_pkg / "__init__.py").write_text(
        "import os\n"
        "__version__ = '0.0.0-fake-b5-sentinel'\n"
        "class Error(Exception):\n    pass\n"
        "class OperationalError(Error):\n    pass\n"
        "_MODE = os.environ.get('VERGI_FAKE_PSYCOPG_MODE', 'fail_always')\n"
        "_N = [0]\n"
        "def _msg():\n"
        "    e = os.environ.get\n"
        "    return ('connection to server at \"%s\", port %s failed: FATAL: password authentication failed for user \"%s\" '\n"
        "            '(dbname \"%s\", maintenance \"%s\", password \"%s\")' % (e('PGHOST'), e('PGPORT'), e('PGUSER'), "
        "e('VERGI_TEST_PG_DSN'), e('VERGI_TEST_PG_MAINTENANCE_DB'), e('PGPASSWORD')))\n"
        "class _Cur:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): return False\n"
        "    def execute(self, *a, **k): pass\n"
        "    def fetchall(self): return [('postgres',)]\n"
        "    def fetchone(self): return (0,)\n"
        "class _Conn:\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): return False\n"
        "    def cursor(self): return _Cur()\n"
        "    def close(self): pass\n"
        "def connect(**kw):\n"
        "    _N[0] += 1\n"
        "    if 'application_name' not in kw and _MODE == 'fail_after_3' and _N[0] <= 3:\n"
        "        return _Conn()\n"
        "    raise OperationalError(_msg())\n", encoding="utf-8", newline="\n")
    sentinel = {"VERGI_TEST_PG_DSN": "sentinel_db_7f3c9a", "PGUSER": "sentinel_user_9a2e",
                "PGPASSWORD": "sentinel-pw-Q7x9Lm2Vb8Zt", "VERGI_TEST_PG_MAINTENANCE_DB": "sentinel_maint_4b1d"}
    sentinel_port = "65431"  # 65431 % 4 != 0 -> never a Windows pid
    fake_env = dict(sentinel)
    fake_env.update({"PGPORT": sentinel_port, "PGHOST": "127.0.0.1", "VERGI_TEST_PG_SUPERUSER_AVAILABLE": "1",
                     "VERGI_TEST_PSQL_BIN": sys.executable, "VERGI_IAM_DATABASE_URL": None,
                     "PYTHONPATH": str(fake_pkg.parent) + ((os.pathsep + os.environ["PYTHONPATH"]) if os.environ.get("PYTHONPATH") else "")})
    temp_root = Path(tempfile.gettempdir())
    step3pg_before = {q.name for q in temp_root.iterdir() if q.name.startswith("vergi_step3pg_")}

    def sentinel_hits(text):
        hits = [name for name, value in sentinel.items() if value in text]
        if re.search(r"(?<!\d)" + sentinel_port + r"(?!\d)", text):
            hits.append("PGPORT")
        return hits

    fake_env["VERGI_FAKE_PSYCOPG_MODE"] = "fail_always"
    code_f1, out_f1, err_f1 = spawn_runner([], extra_env=fake_env, script=T2_PATH, timeout=600)
    fail_line_f1 = next((ln for ln in out_f1.splitlines() if ln.startswith("FAIL unhandled exception")), "")
    check("B5-R1 fail-path F1 (before any nested runner): fake psycopg imported, the first baseline snapshot raises -> exit 1, ONE redacted FAIL, summary 0 passed / 1 failed / 0 skipped",
          code_f1 == 1 and "fake-b5-sentinel" in out_f1 and fail_line_f1 != "" and "OperationalError" in fail_line_f1
          and f"--- {T2_MODULE}: 0 passed, 1 failed, 0 skipped ---" in out_f1,
          (code_f1, fail_line_f1[:200], last_line(out_f1), err_f1[-300:]))
    check("B5-R1 F1: the redacted FAIL line carries placeholders, not values (dsn, user, password, maintenance db, port)",
          all(ph in fail_line_f1 for ph in ("<VERGI_TEST_PG_DSN>", "<PGUSER>", "<PGPASSWORD>", "<VERGI_TEST_PG_MAINTENANCE_DB>", "<PGPORT>")), fail_line_f1[:300])
    check("B5-R1 F1: no sentinel VALUE and no traceback anywhere in T.2's stdout/stderr",
          sentinel_hits(out_f1) == [] and sentinel_hits(err_f1) == [] and "Traceback" not in out_f1 and "Traceback" not in err_f1,
          (sentinel_hits(out_f1), sentinel_hits(err_f1), err_f1[-300:]))
    fake_env["VERGI_FAKE_PSYCOPG_MODE"] = "fail_after_3"
    code_f2, out_f2, err_f2 = spawn_runner([], extra_env=fake_env, script=T2_PATH, timeout=900)
    fail_line_f2 = next((ln for ln in out_f2.splitlines() if ln.startswith("FAIL unhandled exception")), "")
    # captured child stdout carries CRLF on Windows: drop the CR before the anchored match
    summ_f2 = re.search(r"^--- " + re.escape(T2_MODULE) + r": (\d+) passed, (\d+) failed, (\d+) skipped ---$", out_f2.replace("\r", ""), re.M)
    fail_lines_f2 = [ln for ln in out_f2.splitlines() if ln.startswith("FAIL ")]
    pass_lines_f2 = [ln for ln in out_f2.splitlines() if ln.startswith("PASS ")]
    check("B5-R1 fail-path F2 (after a nested runner ran): exit 1, S1's nested run scanned clean (PASS B5 preflight), the later psycopg failure -> ONE redacted FAIL, summary tallies every PASS/FAIL line",
          code_f2 == 1 and "fake-b5-sentinel" in out_f2 and any(ln.startswith("PASS B5 preflight:") for ln in pass_lines_f2)
          and not any(ln.startswith("FAIL B5 ") for ln in fail_lines_f2) and fail_line_f2 != "" and "OperationalError" in fail_line_f2
          and summ_f2 is not None and int(summ_f2.group(1)) == len(pass_lines_f2) and int(summ_f2.group(2)) == len(fail_lines_f2)
          and summ_f2.group(3) == "0" and sum(1 for ln in fail_lines_f2 if ln.startswith("FAIL unhandled exception")) == 1,
          (code_f2, fail_line_f2[:200], summ_f2 and summ_f2.group(0), [ln[:90] for ln in fail_lines_f2], err_f2[-300:]))
    check("B5-R1 F2: placeholders present, no sentinel VALUE, no traceback in stdout/stderr; T.2 removed its temp base (no vergi_step3pg_ residue)",
          "<VERGI_TEST_PG_DSN>" in fail_line_f2 and "<PGPASSWORD>" in fail_line_f2 and sentinel_hits(out_f2) == [] and sentinel_hits(err_f2) == []
          and "Traceback" not in out_f2 and "Traceback" not in err_f2 and "PASS S8: temp base removed" in out_f2
          and {q.name for q in temp_root.iterdir() if q.name.startswith("vergi_step3pg_")} == step3pg_before,
          (sentinel_hits(out_f2), sentinel_hits(err_f2), err_f2[-300:]))

    # -----------------------------------------------------------------------
    # 19. paths with spaces
    # -----------------------------------------------------------------------
    sp_tests = BASE / "fake dir with spaces"
    sp_out = BASE / "out root with spaces"
    sp_tests.mkdir()
    write_module(sp_tests, "test_sp", SRC_OK.replace("{n}", "test_sp"))
    code, out, err = spawn_runner(["--profile", "developer", "--tests-dir", str(sp_tests), "--output-root", str(sp_out)])
    rd = find_run_dir(sp_out)
    sp_report = load_report(rd) if rd else None
    note_nested_tmp(sp_report)
    check("paths with spaces: nested run succeeds (argv list, no shell)", code == 0 and sp_report is not None and sp_report["modules"][0]["outcome"] == "PASS", (code, last_line(out)))
    check("child temp dir is a short private directory under the parent temp root, removed when empty",
          sp_report is not None and os.path.dirname(sp_report["tmp_dir"]) == os.path.abspath(os.environ.get("TEMP") or tempfile.gettempdir())
          and os.path.basename(sp_report["tmp_dir"]).startswith("vsw_") and sp_report.get("tmp_dir_removed") is True and not os.path.exists(sp_report["tmp_dir"]),
          sp_report and (sp_report["tmp_dir"], sp_report.get("tmp_dir_removed")))

    # -----------------------------------------------------------------------
    # temp residue end-to-end (developer: reported, not fatal)
    # -----------------------------------------------------------------------
    code, out, err, report, run_dir = run_fake(BASE, "tempres", {"test_tempres": SRC_TEMP_RESIDUE})
    check("temp residue: child TEMP is the runner-owned private dir and residue is attributed to the module",
          report is not None and code == 0 and report["integrity"]["temp_residue"] and report["integrity"]["temp_residue"][0]["module"] == "test_tempres"
          and any(e.startswith("residue_") for e in report["integrity"]["temp_residue"][0]["entries"]), (code, report and report["integrity"].get("temp_residue")))
    check("temp residue: non-empty child temp dir is KEPT for inspection (never deleted by the runner)",
          report is not None and report.get("tmp_dir_removed") is False and os.path.isdir(report["tmp_dir"]), report and report.get("tmp_dir_removed"))
    check("temp residue: fatal only under production-parity", runner.decide_exit_code("production-parity", ["PASS"], [{"kind": "TEMP_RESIDUE"}]) == 3)

    # -----------------------------------------------------------------------
    # 20./21. abort semantics and labels (pure)
    # -----------------------------------------------------------------------
    check("abort: exit 130 and ABORTED label", runner.EXIT_ABORTED == 130 and runner.sweep_label("production-parity", 130, aborted=True) == "ABORTED"
          and runner.decide_exit_code("production-parity", ["PASS"], [], aborted=True) == 130)
    sw4 = runner.Sweep(make_args(profile="production-parity"), {}, str(REPO_ROOT), io.StringIO())
    ab = BASE / "abort_run"
    ab.mkdir()
    sw4.run_dir = str(ab)
    sw4.report_path = str(ab / "report.json")
    sw4.report["modules"] = [{"name": "test_p", "outcome": "PASS", "passed": 1, "failed": 0, "counted_skips": 0, "informational_skips": 0}]
    rc = sw4.finish(runner.EXIT_ABORTED, aborted=True)
    abr = load_report(ab)
    check("abort: partial report written atomically with state=aborted, label ABORTED, exit 130", rc == 130 and abr["state"] == "aborted" and abr["sweep_label"] == "ABORTED" and abr["runner_exit_code"] == 130 and abr["totals"]["modules_run"] == 1)
    check("labels: FULL only for production-parity exit 0", runner.sweep_label("production-parity", 0) == "FULL" and runner.sweep_label("production-parity", 1) == "PARTIAL"
          and runner.sweep_label("production-parity", 3) == "PARTIAL" and runner.sweep_label("production-parity", 2) == "PARTIAL")
    check("labels: rag gate labels", runner.sweep_label("rag-dependency", 0) == "RAG_GATE_PASS" and runner.sweep_label("rag-dependency", 1) == "RAG_GATE_FAIL")
    check("labels: developer always DIAGNOSTIC", runner.sweep_label("developer", 0) == "DIAGNOSTIC" and runner.sweep_label("developer", 1) == "DIAGNOSTIC")
    check("exit precedence: integrity (3) over module failure (1)", runner.decide_exit_code("developer", ["FAIL"], [{"kind": "PROTECTED_PATH_DIFF"}]) == 3)
    check("exit precedence: refusal is 2 with nothing run", runner.decide_exit_code("production-parity", [], [], refused=True) == 2)
    check("profile rule: official profiles require PASS for every module", runner.module_violates_profile("production-parity", "ZERO_CHECK_DOCUMENTED_SKIP")
          and runner.module_violates_profile("rag-dependency", "ZERO_CHECK_DOCUMENTED_SKIP") and not runner.module_violates_profile("production-parity", "PASS"))

    # -----------------------------------------------------------------------
    # 22. import hygiene
    # -----------------------------------------------------------------------
    for path in (RUNNER_PATH, GUARD_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in ("src", "ui", "scripts"):
                        bad.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in ("src", "ui", "scripts"):
                    bad.append(node.module)
                if node.level and node.level > 0:
                    bad.append("relative import")
        check(f"import hygiene: {path.name} imports nothing from src/ui/scripts", bad == [], bad)
    check("import hygiene: runner did not import psycopg at module import", "psycopg" not in sys.modules or runner.__name__ not in sys.modules)
    # Under a parent sweep the child is already armed by sitecustomize; the
    # assertion is therefore identity-based: importing the module must not
    # create a NEW guard state nor touch the ledger named in the environment.
    r = subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, %r); import os; L=%r; os.environ['%s']=L; before=getattr(sys, '_vergi_ui_test_sweep_guard_state', None); "
                        "import scripts.sweep_env_guard as g; after=getattr(sys, '_vergi_ui_test_sweep_guard_state', None); "
                        "print(before is after, os.path.exists(L), callable(g.install))" % (str(REPO_ROOT), str(BASE / "never.tsv"), runner.GUARD_LEDGER_ENV)],
                       capture_output=True, text=True, timeout=60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    check("import hygiene: importing the guard as a module installs nothing and writes no ledger", r.stdout.strip() == "True False True", r.stdout + r.stderr)
    check("repository never contains a sitecustomize.py", not any(p.name == "sitecustomize.py" for p in (REPO_ROOT / "scripts").iterdir()) and not (REPO_ROOT / "sitecustomize.py").exists())
    check("nested runs completed in bounded time (first nested run < 120s)", dur_a < 120, dur_a)

finally:
    # 23. cleanup + byte-invariance
    removed = rmtree_retry(BASE)
    check("cleanup: temp base removed", removed and not BASE.exists())
    leftover = [d for d in NESTED_TMP_DIRS if os.path.exists(d)]
    for d in leftover:
        rmtree_retry(d)
    check("cleanup: nested runner child temp dirs removed (none left under the parent temp root)",
          not any(os.path.exists(d) for d in NESTED_TMP_DIRS), [d for d in NESTED_TMP_DIRS if os.path.exists(d)])
    check("byte-invariance: data/ unchanged", tree_manifest(REPO_ROOT / "data") == DATA_BEFORE)
    check("byte-invariance: index/ unchanged", tree_manifest(REPO_ROOT / "index") == INDEX_BEFORE)
    check("byte-invariance: ui/tests unchanged", tree_manifest(REPO_ROOT / "ui" / "tests") == TESTS_BEFORE)
    check("cleanup: nothing left under scripts/ by the output-root refusals", not (REPO_ROOT / "scripts" / "_step3_never_created").exists() and not (REPO_ROOT / "scripts" / "_step3_junction_out").exists())

print(f"--- {MODULE_NAME}: {passed} passed, {failed} failed, {informational_skips} informational skips ---")
sys.exit(1 if failed else 0)
