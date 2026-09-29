"""Single honest test runner for ``ui/tests`` -- Pilot Readiness Step 3
(Runner / Environment / Skip Reporting), Fable FINAL contract sections
G-Q, S.1.

OFFICIAL COMMANDS (Windows PowerShell)
--------------------------------------
Step 3 success gate (production parity; requires a fresh, disposable,
loopback-only PostgreSQL 16 with migrations 0001-0005 and the environment
listed by ``--help``)::

    C:\\Users\\<you>\\vergi_ui_runtime\\Scripts\\python.exe scripts\\run_ui_tests.py --profile production-parity

RAG real-dependency gate (no PostgreSQL)::

    .\\.venv\\Scripts\\python.exe scripts\\run_ui_tests.py --profile rag-dependency

There is NO default profile and ``python scripts\\run_ui_tests.py`` from an
arbitrary shell is NOT an official command: the interpreter is verified by
capability (fail-closed) and a wrong interpreter refuses with exit 2 before
any module runs.

WHAT THIS RUNNER DOES
---------------------
* discovers the tracked ``ui/tests/test_*.py`` set and requires it to be
  identical to the filesystem set (exit 2 on any difference);
* builds every child environment from an explicit NAME allowlist (parent
  secrets, API keys, ``VERGI_IAM_DATABASE_URL`` ... never reach a child)
  and asserts a denylist on the result;
* arms a fail-closed audit-hook guard (``scripts/sweep_env_guard.py``
  copied byte-for-byte to ``<run>/guard/sitecustomize.py``) in EVERY child
  and proves it with ten positive controls before the first module runs and
  with per-process ``GUARD_ARMED`` accounting afterwards;
* runs each module with ``python -m ui.tests.<name>`` inside its own
  Windows Job Object (kill-on-close) with a per-module timeout, so a timed
  out module never leaves a lock-holding grandchild behind;
* classifies every module with one authority order (exit code > summary
  presence/name binding > summary numbers > raw PASS/FAIL cross-check >
  SKIPPED scan) -- a module-level zero-check is never a "full sweep"
  success, an exit-0 "0 failed" summary never rescues a non-zero exit;
* writes an atomic ``report.json`` (tmp + fsync + replace) after every
  module into a private run directory (owner + SYSTEM + Administrators
  only) that is never inside the repository; raw child logs stay verbatim
  in that private directory and are scanned for secret material post-run;
* verifies byte-invariance of every tracked file, ``data/**`` and
  ``index/**``, process/temp/database residue and bytecode residue.

The runner imports nothing from ``src``/``ui``/``scripts`` and never
imports the guard (it copies its bytes). ``psycopg`` is imported lazily and
only for the PostgreSQL preflight / residue checks of PostgreSQL profiles.
The runner never creates, starts or stops a PostgreSQL cluster and never
derives or forwards ``VERGI_IAM_DATABASE_URL``.

Exit codes: 0 gate satisfied; 1 at least one module is not PASS under the
profile rule; 2 preflight/usage refusal (no module ran); 3 integrity
failure (overrides 1); 130 Ctrl-C (aborted).
"""

import argparse
import ctypes
import datetime as _dt
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time

RUNNER_VERSION = "1"
APPLICATION_NAME = "vergi_ui_test_sweep"
DEFAULT_MODULE_TIMEOUT_S = 1200
PC_CHILD_TIMEOUT_S = 120
REPORT_FILENAME = "report.json"

EXIT_OK = 0
EXIT_MODULE_FAILURE = 1
EXIT_REFUSED = 2
EXIT_INTEGRITY = 3
EXIT_ABORTED = 130

PROFILES = ("production-parity", "rag-dependency", "developer")
PG_PROFILES = ("production-parity",)
OFFICIAL_PROFILES = ("production-parity", "rag-dependency")

RAG_GATE_MODULES = (
    "test_rag_bundle_builder_isolated",
    "test_rag_bundle_reader_isolated",
    "test_rag_bundle_dependency_smoke",
)
RAG_GATE_MARKER_MODULE = "test_rag_bundle_dependency_smoke"
RAG_GATE_MARKER_LINE = "DEPENDENCY GATE: PASS"

# K.1 amendment (user decision 2026-09-21). The RAG dependency gate demands ZERO
# informational skips across its three modules, because in require mode a skip
# means a missing dependency. One skip is different in kind: the builder test
# cannot create a self-referential symlink on Windows (POSIX-only capability,
# no dependency involved) and always reports it as an informational skip. This
# table is the ONLY exemption and is deliberately the narrowest possible: one
# module, one platform, one exact whole-line pattern, at most one occurrence.
# Anything else -- another module, another platform, another skip text, a
# second occurrence -- still fails the gate. The raw total is always reported.
RAG_GATE_PLATFORM_SKIPS = {
    "test_rag_bundle_builder_isolated": {
        "platform": "win32",
        "max_occurrences": 1,
        "pattern": (r"^SKIPPED \(NOT counted as pass/fail\) containment_looping_link - this platform/account cannot create "
                    r"a genuinely self-referential symlink \([^\r\n]*\) - POSIX-only capability "
                    r"\(see src/path_containment\.py's own ELOOP handling\); never claimed as a pass$"),
    },
}
_RAG_GATE_PLATFORM_SKIP_RES = {_n: re.compile(_s["pattern"]) for _n, _s in RAG_GATE_PLATFORM_SKIPS.items()}


def _rag_gate_platform():
    return sys.platform

REQUIRED_PYTHON = (3, 14)

# (import name used with find_spec, distribution name used with importlib.metadata)
PRODUCTION_PARITY_REQUIRED = (
    ("psycopg", "psycopg"),
    ("fastapi", "fastapi"),
    ("starlette", "starlette"),
    ("jinja2", "Jinja2"),
    ("jsonschema", "jsonschema"),
    ("pydantic", "pydantic"),
    ("httpx", "httpx"),
    ("uvicorn", "uvicorn"),
    ("multipart", "python-multipart"),
    ("authlib", "Authlib"),
    ("joserfc", "joserfc"),
    ("cryptography", "cryptography"),
)
RAG_DEPENDENCY_REQUIRED = (
    ("faiss", "faiss-cpu"),
    ("numpy", "numpy"),
    ("pypdf", "pypdf"),
    ("openai", "openai"),
    ("dotenv", "python-dotenv"),
    ("httpx2", "httpx2"),
)
REPORTED_ONLY = (
    ("anthropic", "anthropic"),
)
# distribution-only (never find_spec on dotted namespace packages)
REPORTED_DISTRIBUTIONS = ("azure-keyvault-secrets", "azure-identity", "azure-core")

# ---------------------------------------------------------------------------
# J. Environment contract
# ---------------------------------------------------------------------------

ENV_ALLOWLIST_WINDOWS = (
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "USERNAME", "USERDOMAIN",
    "COMPUTERNAME", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "ALLUSERSPROFILE",
    "PUBLIC", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "OS",
)
ENV_ALLOWLIST_POSIX_EXTRA = ("HOME", "LANG", "LC_ALL", "SHELL", "PATH")
# Slice 8A / G3: PGPASSWORD was removed from this allowlist and added to
# ENV_DENY_EXACT below. The runner forwards NO password and NO passfile
# environment value to any child process: PGPASSWORD is stripped, and
# PGPASSFILE stays denylisted as it always has been. A disposable cluster that
# uses scram is still reachable, because libpq finds a passfile at its own
# default location without any environment variable; a test that needs a
# specific passfile passes it as a `passfile` connection parameter instead.
ENV_ALLOWLIST_PG = (
    "VERGI_TEST_PG_DSN", "VERGI_TEST_PSQL_BIN", "VERGI_TEST_PG_SUPERUSER_AVAILABLE",
    "VERGI_TEST_PG_MAINTENANCE_DB", "PGHOST", "PGPORT", "PGUSER",
)
# TEMP/TMP are in the contract's pass-through list (J.1); this runner instead
# points them at a short, runner-owned, private ``%TEMP%/vsw_<pid>`` so that
# temp residue is attributable per module and unrelated host activity in
# %TEMP% cannot fail the gate. Disclosed deviation (see implementation report).
RUNNER_SET_ENV_NAMES = (
    "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "PYTHONPATH",
    "VERGI_UI_TEST_SWEEP_GUARD_LEDGER", "VERGI_UI_TEST_SWEEP_RUN_ID",
    "VERGI_UI_TEST_SWEEP_PARENT_PID", "TEMP", "TMP",
)
RAG_PROFILE_ENV = {"VERGI_RAG_DEPENDENCY_GATE": "require"}

ENV_DENY_EXACT = frozenset({
    "PGPASSWORD",
    "VERGI_KEY_PROVIDER_KIND", "VERGI_DEPLOYMENT_MODE", "VERGI_IAM_DATABASE_URL",
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONWARNINGS",
    "PYTHONBREAKPOINT", "PYTHONSAFEPATH", "PYTHONUSERBASE", "PYTHONPYCACHEPREFIX",
    "PYTHONHASHSEED", "PYTHONUTF8", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "NO_PROXY", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "CURL_CA_BUNDLE", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGDATABASE",
    "PGOPTIONS", "PGSSLMODE", "PGPASSFILE", "PGSYSCONFDIR", "PGTARGETSESSIONATTRS",
})
ENV_DENY_PREFIXES = (
    "ANTHROPIC_", "OPENAI_", "AZURE_", "VERGI_ENTRA_", "VERGI_AZURE_",
    "VERGI_RAG_DEPENDENCY_GATE", "PIP_", "GIT_",
)
# names the runner itself may set even though they are denylisted for parents
RUNNER_SET_DENYLISTED = frozenset({"PYTHONPATH", "VERGI_RAG_DEPENDENCY_GATE"})

GUARD_LEDGER_ENV = "VERGI_UI_TEST_SWEEP_GUARD_LEDGER"
GUARD_RUN_ID_ENV = "VERGI_UI_TEST_SWEEP_RUN_ID"
GUARD_PARENT_PID_ENV = "VERGI_UI_TEST_SWEEP_PARENT_PID"
SELFTEST_SEAM_ENV = "VERGI_UI_TEST_SWEEP_SELFTEST"

# ---------------------------------------------------------------------------
# G. Parser
# ---------------------------------------------------------------------------

RE_SUMMARY_DASH = re.compile(
    r"^--- (?P<name>[A-Za-z0-9_]+): (?P<p>\d+) passed, (?P<f>\d+) failed"
    r"(?:, (?P<s>\d+) skipped|, (?P<i>\d+) informational skips)? ---$"
)
RE_SUMMARY_DASH_INFO = re.compile(
    r"^--- (?P<name>[A-Za-z0-9_]+): (?P<p>\d+) passed, (?P<f>\d+) failed "
    r"\((?P<i>\d+) informational SKIPPED line\(s\), NOT counted\) ---$"
)
RE_SUMMARY_TOTAL = re.compile(r"^TOTAL: (?P<p>\d+) passed, (?P<f>\d+) failed$")
RE_SUMMARY_BARE = re.compile(r"^(?P<p>\d+) passed, (?P<f>\d+) failed(?:, (?P<i>\d+) informational skips)?$")
RE_SKIPPED = re.compile(r"^SKIPPED\b")
RE_NOT_COUNTED = re.compile(r"not counted", re.IGNORECASE)

OUTCOME_PASS = "PASS"
OUTCOME_ZERO_DOC = "ZERO_CHECK_DOCUMENTED_SKIP"
OUTCOME_ZERO_UNDOC = "ZERO_CHECK_UNDOCUMENTED"
OUTCOME_FAIL = "FAIL"
OUTCOME_CONTRADICTION = "EXIT_SUMMARY_CONTRADICTION"
OUTCOME_PARSE_FAILURE = "PARSE_FAILURE"
OUTCOME_TALLY = "TALLY_MISMATCH"
OUTCOME_SKIP_TALLY = "SKIP_TALLY_MISMATCH"
OUTCOME_CRASH = "CRASH_MID_RUN"
OUTCOME_TIMEOUT = "TIMEOUT"
OUTCOME_SPAWN_FAILURE = "SPAWN_FAILURE"
OUTCOME_GUARD_NOT_ARMED = "GUARD_NOT_ARMED"
# B2: the child could not be contained in its Job Object -- assignment or
# resume failed (the suspended child was killed before executing an
# instruction), or, B2-R1, the Job Object itself could not be CREATED after
# at least one module had already run (stage "create": the module was never
# spawned). Either way the sweep STOPPED (exit 3). A creation failure BEFORE
# the first module is a preflight-class refusal instead (N.2, exit 2).
OUTCOME_JOB_CONTAINMENT_FAILURE = "JOB_CONTAINMENT_FAILURE"

FAIL_CLASS_OUTCOMES = frozenset({
    OUTCOME_FAIL, OUTCOME_CONTRADICTION, OUTCOME_PARSE_FAILURE, OUTCOME_TALLY,
    OUTCOME_SKIP_TALLY, OUTCOME_CRASH, OUTCOME_TIMEOUT, OUTCOME_SPAWN_FAILURE,
    OUTCOME_GUARD_NOT_ARMED, OUTCOME_ZERO_UNDOC, OUTCOME_JOB_CONTAINMENT_FAILURE,
})


class ParsedModule:
    __slots__ = (
        "outcome", "passed", "failed", "counted_skips", "informational_skips",
        "summary_kind", "summary_line", "observed_pass_lines", "observed_fail_lines",
        "detail",
    )

    def __init__(self):
        self.outcome = None
        self.passed = 0
        self.failed = 0
        self.counted_skips = 0
        self.informational_skips = 0
        self.summary_kind = None
        self.summary_line = None
        self.observed_pass_lines = 0
        self.observed_fail_lines = 0
        self.detail = ""

    def as_dict(self):
        return {
            "outcome": self.outcome,
            "passed": self.passed,
            "failed": self.failed,
            "counted_skips": self.counted_skips,
            "informational_skips": self.informational_skips,
            "summary_kind": self.summary_kind,
            "summary_line": self.summary_line,
            "observed_pass_lines": self.observed_pass_lines,
            "observed_fail_lines": self.observed_fail_lines,
            "detail": self.detail,
        }


def _match_summary(line):
    """Return (kind, groupdict) for a summary-shaped line, else None."""
    m = RE_SUMMARY_DASH_INFO.match(line)
    if m:
        return "dash_info", m.groupdict()
    m = RE_SUMMARY_DASH.match(line)
    if m:
        return "dash", m.groupdict()
    m = RE_SUMMARY_TOTAL.match(line)
    if m:
        return "total", m.groupdict()
    m = RE_SUMMARY_BARE.match(line)
    if m:
        return "bare", m.groupdict()
    return None


def split_stdout_lines(data):
    """Strict UTF-8 decode; returns (lines, None) or (None, error_text)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, "stdout is not strict UTF-8: %s" % exc
    lines = text.split("\n")
    return [ln[:-1] if ln.endswith("\r") else ln for ln in lines], None


def classify_skipped_lines(lines):
    counted = 0
    informational = 0
    for ln in lines:
        if RE_SKIPPED.match(ln):
            if RE_NOT_COUNTED.search(ln):
                informational += 1
            else:
                counted += 1
    return counted, informational


def rag_gate_platform_exempt_skips(module_name, stdout_bytes, platform):
    """K.1 amendment. Pure. How many informational SKIPPED lines of
    ``module_name`` the named platform-gated table exempts on ``platform``:
    0 unless the module is listed, the platform matches and the line is an
    informational skip ("NOT counted") matching the module's exact
    whole-line pattern; capped at the table's max_occurrences."""
    spec = RAG_GATE_PLATFORM_SKIPS.get(module_name)
    if spec is None or platform != spec["platform"]:
        return 0
    lines, _err = split_stdout_lines(stdout_bytes if stdout_bytes is not None else b"")
    if lines is None:
        return 0
    rx = _RAG_GATE_PLATFORM_SKIP_RES[module_name]
    hits = sum(1 for ln in lines if RE_SKIPPED.match(ln) and RE_NOT_COUNTED.search(ln) and rx.match(ln))
    return min(hits, spec["max_occurrences"])


def parse_module_output(module_name, stdout_bytes, exit_code, timed_out=False, spawn_failed=False):
    """G.2 single authority order. Pure function."""
    result = ParsedModule()
    lines, err = split_stdout_lines(stdout_bytes if stdout_bytes is not None else b"")
    if lines is None:
        result.outcome = OUTCOME_PARSE_FAILURE
        result.detail = err
        return result
    result.observed_pass_lines = sum(1 for ln in lines if ln.startswith("PASS "))
    result.observed_fail_lines = sum(1 for ln in lines if ln.startswith("FAIL "))
    counted, informational = classify_skipped_lines(lines)
    result.counted_skips = counted
    result.informational_skips = informational
    has_skipped_line = any(RE_SKIPPED.match(ln) for ln in lines)

    summary = None
    for ln in reversed(lines):
        summary = _match_summary(ln)
        if summary is not None:
            result.summary_kind, groups = summary
            result.summary_line = ln
            break

    # 1. exit code is authoritative
    if spawn_failed:
        result.outcome = OUTCOME_SPAWN_FAILURE
        return result
    if timed_out:
        result.outcome = OUTCOME_TIMEOUT
        return result
    if exit_code != 0:
        if summary is None and result.observed_pass_lines >= 1:
            result.outcome = OUTCOME_CRASH
            result.detail = "no summary line; %d PASS line(s) before exit %s" % (result.observed_pass_lines, exit_code)
        else:
            result.outcome = OUTCOME_FAIL
            if summary is not None:
                result.passed = int(groups["p"])
                result.failed = int(groups["f"])
            result.detail = "exit code %s" % exit_code
        return result

    # 2. exit 0: summary presence and name binding
    if summary is None:
        if result.observed_pass_lines + result.observed_fail_lines > 0:
            result.outcome = OUTCOME_PARSE_FAILURE
            result.detail = "PASS/FAIL lines present but no recognised summary line"
        elif has_skipped_line:
            result.outcome = OUTCOME_ZERO_DOC
            result.detail = "no summary line; SKIPPED line present"
        else:
            result.outcome = OUTCOME_ZERO_UNDOC
            result.detail = "no summary line, no PASS/FAIL/SKIPPED line"
        return result
    kind, groups = summary
    if kind in ("dash", "dash_info") and groups["name"] != module_name:
        result.outcome = OUTCOME_PARSE_FAILURE
        result.detail = "summary line names a foreign module: %s" % groups["name"]
        return result
    p = int(groups["p"])
    f = int(groups["f"])
    result.passed = p
    result.failed = f

    # 3. summary numbers
    if f > 0:
        result.outcome = OUTCOME_CONTRADICTION
        result.detail = "exit 0 but summary reports %d failed" % f
        return result
    if p + f == 0:
        result.outcome = OUTCOME_ZERO_DOC if has_skipped_line else OUTCOME_ZERO_UNDOC
        result.detail = "summary reports 0 passed, 0 failed"
        return result

    # 4. raw cross-check
    if result.observed_pass_lines != p or result.observed_fail_lines != f:
        result.outcome = OUTCOME_TALLY
        result.detail = "summary %d/%d vs raw PASS/FAIL lines %d/%d" % (
            p, f, result.observed_pass_lines, result.observed_fail_lines)
        return result

    # 5. SKIPPED tally
    s_field = groups.get("s")
    i_field = groups.get("i")
    if s_field is not None and int(s_field) != counted:
        result.outcome = OUTCOME_SKIP_TALLY
        result.detail = "summary counted skips %s vs observed %d" % (s_field, counted)
        return result
    if i_field is not None and int(i_field) != informational:
        result.outcome = OUTCOME_SKIP_TALLY
        result.detail = "summary informational skips %s vs observed %d" % (i_field, informational)
        return result

    # 6. PASS
    result.outcome = OUTCOME_PASS
    return result


# ---------------------------------------------------------------------------
# K. Capability profile
# ---------------------------------------------------------------------------

def probe_capabilities():
    """Return {name: version|"present"|"absent"} without importing anything."""
    found = {}
    for import_name, dist_name in PRODUCTION_PARITY_REQUIRED + RAG_DEPENDENCY_REQUIRED + REPORTED_ONLY:
        try:
            spec = importlib.util.find_spec(import_name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            found[import_name] = "absent"
            continue
        try:
            found[import_name] = importlib.metadata.version(dist_name)
        except importlib.metadata.PackageNotFoundError:
            found[import_name] = "present"
    for dist_name in REPORTED_DISTRIBUTIONS:
        try:
            found[dist_name] = importlib.metadata.version(dist_name)
        except importlib.metadata.PackageNotFoundError:
            found[dist_name] = "absent"
    return found


def evaluate_profile_capabilities(profile, present, python_version):
    """Pure. Returns (ok, missing_names, warnings)."""
    if profile == "production-parity":
        required = [n for n, _ in PRODUCTION_PARITY_REQUIRED]
    elif profile == "rag-dependency":
        required = [n for n, _ in RAG_DEPENDENCY_REQUIRED]
    else:
        required = []
    missing = [n for n in required if present.get(n, "absent") == "absent"]
    warnings = []
    version_ok = tuple(python_version[:2]) == REQUIRED_PYTHON
    if profile in OFFICIAL_PROFILES:
        if not version_ok:
            missing.append("python==%d.%d.x (found %d.%d)" % (REQUIRED_PYTHON + tuple(python_version[:2])))
        return (len(missing) == 0), missing, warnings
    # developer: report-only
    if not version_ok:
        warnings.append("python is %d.%d, contract expects %d.%d" % (tuple(python_version[:2]) + REQUIRED_PYTHON))
    absent = [n for n, _ in PRODUCTION_PARITY_REQUIRED + RAG_DEPENDENCY_REQUIRED if present.get(n, "absent") == "absent"]
    if absent:
        warnings.append("absent capabilities: %s" % ", ".join(absent))
    return True, [], warnings


# ---------------------------------------------------------------------------
# J. Environment construction
# ---------------------------------------------------------------------------

def is_denylisted_name(name):
    upper = name.upper()
    if upper in ENV_DENY_EXACT:
        return True
    if upper.endswith("_API_KEY"):
        return True
    if "SECRET" in upper or "TOKEN" in upper:
        return True
    if "PASSWORD" in upper:
        return True
    for prefix in ENV_DENY_PREFIXES:
        if upper.startswith(prefix):
            return True
    return False


def build_child_env(parent_env, profile, guard_dir, ledger_path, run_id, parent_pid, tmp_dir, platform=None):
    """J.1-J.3. Pure. Returns (env, snapshot) where snapshot maps
    name -> passed|stripped_denylist|stripped_unlisted|runner_set|absent."""
    platform = platform or sys.platform
    allow = set(ENV_ALLOWLIST_WINDOWS if platform == "win32" else ENV_ALLOWLIST_POSIX_EXTRA)
    allow.update(ENV_ALLOWLIST_PG)
    runner_set = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(guard_dir),
        GUARD_LEDGER_ENV: str(ledger_path),
        GUARD_RUN_ID_ENV: str(run_id),
        GUARD_PARENT_PID_ENV: str(parent_pid),
        "TEMP": str(tmp_dir),
        "TMP": str(tmp_dir),
    }
    if profile == "rag-dependency":
        runner_set.update(RAG_PROFILE_ENV)
    env = {}
    snapshot = {}
    upper_parent = {}
    for name, value in parent_env.items():
        upper_parent.setdefault(name.upper(), (name, value))
    for uname, (name, value) in upper_parent.items():
        if uname in runner_set:
            continue
        if is_denylisted_name(uname):
            snapshot[uname] = "stripped_denylist"
            continue
        if uname in allow:
            env[uname] = value
            snapshot[uname] = "passed"
        else:
            snapshot[uname] = "stripped_unlisted"
    for uname in sorted(allow):
        if uname not in snapshot:
            snapshot[uname] = "absent"
    for name, value in runner_set.items():
        env[name] = value
        snapshot[name] = "runner_set"
    return env, snapshot


def assert_env_denylist(env, runner_values):
    """J.2. Returns list of violations (empty == ok)."""
    violations = []
    for name, value in env.items():
        if is_denylisted_name(name):
            if name.upper() in RUNNER_SET_DENYLISTED and runner_values.get(name.upper()) == value:
                continue
            violations.append(name)
    return sorted(violations)


# ---------------------------------------------------------------------------
# L. PostgreSQL syntactic contract
# ---------------------------------------------------------------------------

RE_DBNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
LOOPBACK_PGHOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def validate_pg_dsn_name(value):
    """L.1. Returns None when valid, else a reason (never echoing the value)."""
    if value is None or value == "":
        return "VERGI_TEST_PG_DSN is unset or empty"
    for token in ("://", "=", " ", "/"):
        if token in value:
            return "VERGI_TEST_PG_DSN must be a bare database NAME, not a DSN/URI/conninfo (contains %r)" % token
    if not RE_DBNAME.match(value):
        return "VERGI_TEST_PG_DSN is not a valid bare database name"
    return None


def validate_pghost(value):
    if value is None or value == "":
        return None
    if value.lower() in LOOPBACK_PGHOSTS:
        return None
    return "PGHOST must be unset or loopback (127.0.0.1 / ::1 / localhost)"


def validate_pgport(value):
    if value is None or value == "":
        return None
    if not value.isdigit() or not (1 <= int(value) <= 65535):
        return "PGPORT must be numeric (1-65535)"
    return None


def _normalize_host(host):
    if host is None or host == "":
        return "localhost"
    h = host.lower()
    if h in LOOPBACK_PGHOSTS or h.startswith("127."):
        return "localhost"
    return h


def iam_url_targets_test_db(conninfo_dict, pghost, pgport, dbname):
    """L.2. Pure: True when the parsed VERGI_IAM_DATABASE_URL points at the
    same (host, port, dbname) as the test target. Loopback aliases are
    considered equal (fail-closed towards refusal)."""
    if not conninfo_dict:
        return False
    url_host = _normalize_host(conninfo_dict.get("host"))
    url_port = str(conninfo_dict.get("port") or "5432")
    url_db = conninfo_dict.get("dbname")
    target_host = _normalize_host(pghost)
    target_port = str(pgport or "5432")
    return url_host == target_host and url_port == target_port and url_db == dbname


def parse_iam_url_via_psycopg(url):
    """Parse without logging. Returns dict or None; never raises with the value embedded."""
    try:
        from psycopg import conninfo  # lazy
    except Exception:
        return None
    try:
        return conninfo.conninfo_to_dict(url)
    except Exception:
        return None


def concurrent_sweep_present(rows):
    """O.1. Pure: rows are (application_name, pid) tuples for OTHER backends."""
    return any(app == APPLICATION_NAME for app, _pid in rows)


# Slice 8A: 0006 grants privileges and creates no table, column or sequence, so
# it has no object a "table"/"column" sentinel could see. A single
# has_table_privilege() probe would also not notice a PARTIALLY applied 0006.
# The "contract" kind therefore pins eight independent propositions - positive
# grants, negative (must-NOT-have) grants, role attributes, ownership and the
# PUBLIC schema ACL - each evaluated by PG_CONTRACT_SQL below and each able to
# fail on its own.
MIGRATION_SENTINELS = (
    ("0001", "table", "iam.users"),
    ("0003", "table", "mutation.mutation_resources"),
    ("0003", "table", "mutation.mutation_journal"),
    ("0004", "column", "mutation.mutation_journal.reconciled_by_actor_type"),
    ("0004", "column", "mutation.mutation_journal.reconciled_by_actor_ref"),
    ("0005", "table", "iam.global_resource_grants"),
    ("0005", "table", "iam.global_resource_grant_events"),
    ("0006", "contract", "roles_exist"),
    ("0006", "contract", "roles_not_privileged"),
    ("0006", "contract", "owner_is_vergi_owner"),
    ("0006", "contract", "app_can_write_journal"),
    ("0006", "contract", "admin_can_insert_grants"),
    ("0006", "contract", "app_cannot_insert_oidc"),
    ("0006", "contract", "admin_cannot_insert_journal"),
    ("0006", "contract", "public_has_no_schema_access"),
)

CONTRACT_ROLE_OWNER = "vergi_owner"
CONTRACT_ROLE_APP = "vergi_app"
CONTRACT_ROLE_ADMIN = "vergi_iam_admin"

# Every probe is guarded so the statement can never raise: has_table_privilege()
# errors on an unknown role or an unknown table, so each call sits behind an
# EXISTS(pg_roles) + to_regclass() CASE and falls back to false. PUBLIC is a
# pseudo-role and is NOT accepted by has_schema_privilege(); it is grantee OID 0
# inside the ACL, so the PUBLIC probe goes through pg_namespace.nspacl +
# aclexplode(), with acldefault('n', nspowner) standing in for a NULL acl, and
# fails closed when a schema is missing instead of reporting "no access found".
PG_CONTRACT_SQL = """
SELECT
  (SELECT count(*) = 3 FROM pg_roles WHERE rolname IN (%(owner)s, %(app)s, %(admin)s))
    AS roles_exist,
  ((SELECT count(*) = 3 FROM pg_roles WHERE rolname IN (%(owner)s, %(app)s, %(admin)s))
   AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN (%(owner)s, %(app)s, %(admin)s)
                     AND (rolsuper OR rolcreatedb OR rolcreaterole
                          OR rolreplication OR rolbypassrls)))
    AS roles_not_privileged,
  (EXISTS (SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba
             WHERE d.datname = current_database() AND r.rolname = %(owner)s)
   AND (SELECT count(*) = 2 FROM pg_namespace n JOIN pg_roles r ON r.oid = n.nspowner
          WHERE n.nspname IN ('iam', 'mutation') AND r.rolname = %(owner)s))
    AS owner_is_vergi_owner,
  (CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %(app)s)
          AND to_regclass('mutation.mutation_journal') IS NOT NULL
        THEN has_table_privilege(%(app)s, 'mutation.mutation_journal', 'INSERT')
         AND has_table_privilege(%(app)s, 'mutation.mutation_journal', 'UPDATE')
        ELSE false END)
    AS app_can_write_journal,
  (CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %(admin)s)
          AND to_regclass('iam.global_resource_grants') IS NOT NULL
        THEN has_table_privilege(%(admin)s, 'iam.global_resource_grants', 'INSERT')
        ELSE false END)
    AS admin_can_insert_grants,
  (CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %(app)s)
          AND to_regclass('iam.oidc_login_transactions') IS NOT NULL
        THEN NOT has_table_privilege(%(app)s, 'iam.oidc_login_transactions', 'INSERT')
        ELSE false END)
    AS app_cannot_insert_oidc,
  (CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %(admin)s)
          AND to_regclass('mutation.mutation_journal') IS NOT NULL
        THEN NOT has_table_privilege(%(admin)s, 'mutation.mutation_journal', 'INSERT')
        ELSE false END)
    AS admin_cannot_insert_journal,
  ((SELECT count(*) = 2 FROM pg_namespace WHERE nspname IN ('iam', 'mutation'))
   AND NOT EXISTS (
         SELECT 1
         FROM pg_namespace AS n
         CROSS JOIN LATERAL aclexplode(
             coalesce(n.nspacl, acldefault('n', n.nspowner))) AS a
         WHERE n.nspname IN ('iam', 'mutation')
           AND a.grantee = 0
           AND a.privilege_type IN ('USAGE', 'CREATE')))
    AS public_has_no_schema_access
"""

CONTRACT_LABELS = tuple(name for mig, kind, name in MIGRATION_SENTINELS if kind == "contract")


def missing_migrations(present_tables, present_columns, present_contracts=frozenset()):
    """Pure. present_tables: set of regclass names present; present_columns:
    set of 'schema.table.column'; present_contracts: set of satisfied 0006
    contract labels. Returns list of missing sentinel labels."""
    missing = []
    for mig, kind, name in MIGRATION_SENTINELS:
        if kind == "table":
            ok = name in present_tables
        elif kind == "column":
            ok = name in present_columns
        elif kind == "contract":
            ok = name in present_contracts
        else:
            ok = False  # unknown kind fails closed, never silently passes
        if not ok:
            missing.append("%s:%s" % (mig, name))
    return missing


def is_loopback_server_addr(value):
    """inet_server_addr() result: None means a local Unix socket (local by
    construction), otherwise must be loopback."""
    if value is None:
        return True
    text = str(value).split("/", 1)[0]
    if text.startswith("127.") or text in ("::1", "::ffff:127.0.0.1"):
        return True
    return False


# ---------------------------------------------------------------------------
# H. Guard ledger accounting
# ---------------------------------------------------------------------------

PYTHON_BASENAMES = frozenset({"python", "python.exe", "pythonw.exe", "pythonw", "python3", "python3.exe"})
POPEN_EXECUTABLE_ALLOWLIST = frozenset({
    "python", "python.exe", "pythonw.exe", "git", "git.exe", "cmd", "cmd.exe",
    "icacls", "icacls.exe", "psql", "psql.exe",
})
# Command names: matched as WHOLE tokens (basename, extension stripped,
# case-insensitive) -- a substring match would flag any path containing
# e.g. "az" or "ftp". Patterns: matched as CASE-INSENSITIVE substrings
# (B4: "INVOKE-WEBREQUEST", "HTTPS://" are as suspicious as the lowercase
# spellings; Windows command interpreters are case-insensitive).
POPEN_COMMAND_DENYLIST = frozenset({
    "curl", "wget", "powershell", "pwsh", "certutil", "bitsadmin", "az", "ssh",
    "scp", "ftp",
})
POPEN_PATTERN_DENYLIST = ("Invoke-", "http://", "https://")
POPEN_UNC_PREFIX = "\\\\"


def tokenize_command_line(argv):
    """Turn a POPEN argv record into tokens. On Windows CPython reports the
    already-joined command line as a single string; split it respecting
    double quotes. Lists with several elements are returned as-is."""
    if not argv:
        return []
    if len(argv) > 1:
        return [str(a) for a in argv]
    single = str(argv[0])
    tokens = []
    cur = []
    in_q = False
    i = 0
    while i < len(single):
        ch = single[i]
        if ch == '"':
            in_q = not in_q
            cur.append(ch)
        elif ch.isspace() and not in_q:
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
        i += 1
    if cur:
        tokens.append("".join(cur))
    return tokens


def _strip_quotes(token):
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1]
    return token


def popen_executable_basename(argv):
    tokens = tokenize_command_line(argv)
    if not tokens:
        return ""
    first = _strip_quotes(tokens[0]).replace("\\", "/")
    return first.rsplit("/", 1)[-1].lower()


def popen_is_python(argv):
    return popen_executable_basename(argv) in PYTHON_BASENAMES


def popen_has_unarmed_flag(argv):
    """True when a Python command line carries -I, -S or -E before the
    script/-c/-m argument (those flags disable PYTHONPATH/site)."""
    tokens = [_strip_quotes(t) for t in tokenize_command_line(argv)]
    for tok in tokens[1:]:
        if tok in ("-c", "-m", "--"):
            return False
        if not tok.startswith("-"):
            return False
        if tok.startswith("--"):
            continue
        letters = tok[1:]
        if tok.startswith("-X") or tok.startswith("-W"):
            continue
        if any(ch in letters for ch in "ISE"):
            return True
    return False


def popen_is_suspicious(argv):
    """H.3 post-run classification. Returns reason or None."""
    base = popen_executable_basename(argv)
    if base not in POPEN_EXECUTABLE_ALLOWLIST:
        return "executable not allowlisted: %s" % (base or "<empty>")
    for tok in tokenize_command_line(argv):
        t = _strip_quotes(tok)
        name = t.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name in POPEN_COMMAND_DENYLIST:
            return "argv token matches denylist entry %r" % name
        t_folded = t.lower()
        for bad in POPEN_PATTERN_DENYLIST:
            if bad.lower() in t_folded:
                return "argv token matches denylist entry %r (case-insensitive)" % bad
        if t.startswith(POPEN_UNC_PREFIX):
            return "argv token is a UNC path"
    return None


class LedgerRecord:
    __slots__ = ("kind", "pid", "ppid", "run_id", "fields", "raw")

    def __init__(self, kind, pid, ppid, run_id, fields, raw):
        self.kind = kind
        self.pid = pid
        self.ppid = ppid
        self.run_id = run_id
        self.fields = fields
        self.raw = raw


def parse_ledger_lines(text):
    """Parse ledger text into LedgerRecord list; malformed lines become
    kind='MALFORMED'."""
    records = []
    for raw in text.split("\n"):
        if raw.strip() == "":
            continue
        parts = raw.split("\t")
        kind = parts[0]
        try:
            if kind == "GUARD_ARMED":
                records.append(LedgerRecord(kind, int(parts[1]), int(parts[2]), parts[3], parts[4:], raw))
            elif kind == "POPEN":
                records.append(LedgerRecord(kind, int(parts[1]), None, parts[2], parts[3:], raw))
            elif kind in ("ENV_OPEN_BLOCKED", "NET_BLOCKED"):
                records.append(LedgerRecord(kind, int(parts[1]), None, parts[2], parts[3:], raw))
            elif kind == "NESTED_RUNNER":
                records.append(LedgerRecord(kind, int(parts[1]), int(parts[2]), parts[3], parts[4:], raw))
            else:
                records.append(LedgerRecord("MALFORMED", None, None, None, parts, raw))
        except (IndexError, ValueError):
            records.append(LedgerRecord("MALFORMED", None, None, None, parts, raw))
    return records


def popen_argv_from_record(rec):
    try:
        return json.loads(rec.fields[1])
    except Exception:
        return [rec.fields[1] if len(rec.fields) > 1 else ""]


def nested_runner_windows(records, run_id):
    """V2. Pure. Life windows of nested runners as {pid: [(start, end), ...]}
    over ledger record INDEXES. A nested runner is an armed process: its
    GUARD_ARMED line precedes its NESTED_RUNNER line, and every later POPEN
    written by that pid belongs to it until the pid arms again. Windows
    therefore run from the pid's latest GUARD_ARMED before the NESTED_RUNNER
    record (fallback: the record itself) to the pid's next GUARD_ARMED after
    it (fallback: the end of the ledger). Windows pids are reused aggressively:
    a bare-pid exclusion for the whole run also swallowed the python spawns of
    an ORDINARY process that later received a nested runner's old pid."""
    windows = {}
    for i, r in enumerate(records):
        if r.kind != "NESTED_RUNNER" or r.pid is None or r.run_id != run_id:
            continue
        start = i
        for k in range(i - 1, -1, -1):
            if records[k].kind == "GUARD_ARMED" and records[k].pid == r.pid:
                start = k
                break
        end = len(records)
        for k in range(i + 1, len(records)):
            if records[k].kind == "GUARD_ARMED" and records[k].pid == r.pid:
                end = k
                break
        windows.setdefault(r.pid, []).append((start, end))
    return windows


def guard_accounting(records, run_id, module_root_count):
    """H.2 sweep-level accounting. Pure. Returns dict with counts and
    inheritance_ok. Python POPENs recorded by a nested runner are excluded
    (their children arm into the nested run's own ledger) -- only while that
    nested runner is alive, see nested_runner_windows() (V2)."""
    windows = nested_runner_windows(records, run_id)
    nested_records = [r for r in records if r.kind == "NESTED_RUNNER" and r.run_id == run_id]
    armed = [r for r in records if r.kind == "GUARD_ARMED" and r.run_id == run_id]
    popens = [r for r in records if r.kind == "POPEN" and r.run_id == run_id]
    python_popens = [(i, r) for i, r in enumerate(records)
                     if r.kind == "POPEN" and r.run_id == run_id and popen_is_python(popen_argv_from_record(r))]
    counted_python = [r for i, r in python_popens
                      if not any(s < i < e for s, e in windows.get(r.pid, ()))]
    unarmed_flag = [r for r in counted_python if popen_has_unarmed_flag(popen_argv_from_record(r))]
    expected = module_root_count + len(counted_python)
    suspicious = []
    for r in popens:
        reason = popen_is_suspicious(popen_argv_from_record(r))
        if reason:
            suspicious.append({"pid": r.pid, "reason": reason})
    malformed = sum(1 for r in records if r.kind == "MALFORMED")
    return {
        "armed_count": len(armed),
        "popen_count": len(popens),
        "popen_python_count": len(counted_python),
        "popen_python_nested_excluded": len(python_popens) - len(counted_python),
        "nested_runner_count": len(nested_records),
        "nested_runner_unique_pids": len({r.pid for r in nested_records}),
        "unarmed_flag_popen_count": len(unarmed_flag),
        "expected_armed": expected,
        "inheritance_ok": (len(armed) == expected and len(unarmed_flag) == 0 and malformed == 0),
        "malformed_lines": malformed,
        "env_open_blocked_count": sum(1 for r in records if r.kind == "ENV_OPEN_BLOCKED"),
        "net_blocked_count": sum(1 for r in records if r.kind == "NET_BLOCKED"),
        "suspicious_popens": suspicious,
    }


def module_guard_armed(records, run_id, popen_pid):
    """Per-module H.2(a): a GUARD_ARMED line for this run whose pid equals the
    spawned pid, or whose ppid equals it (venv launcher indirection: the
    launcher pid is Popen.pid and the real interpreter is its child)."""
    for r in records:
        if r.kind == "GUARD_ARMED" and r.run_id == run_id and (r.pid == popen_pid or r.ppid == popen_pid):
            return True
    return False


# ---------------------------------------------------------------------------
# I. Secret scan
# ---------------------------------------------------------------------------

SECRET_PATTERNS = (
    ("anthropic_key", re.compile(rb"sk-ant-[A-Za-z0-9_\-]{16,}")),
    ("url_userinfo_password", re.compile(rb"://[^/\s:@]{1,64}:[^@\s/]{1,}@")),
    ("bearer_token", re.compile(rb"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{20,}")),
    ("pgpassword_assignment", re.compile(rb"\bPGPASSWORD=\S{1,}")),
    ("password_assignment", re.compile(rb"(?i)\bpassword=(?!None\b|''|\"\"|<)[^\s'\"<>,)]{8,}")),
    ("client_secret_assignment", re.compile(rb"(?i)\bclient_secret=(?!None\b|''|\"\"|<)[^\s'\"<>,)]{8,}")),
)
SECRET_VALUE_MIN_LEN = 12


def collect_parent_secret_values(parent_env):
    values = []
    for name, value in parent_env.items():
        if (is_denylisted_name(name) or name.upper() == "PGPASSWORD") and value and len(value) >= SECRET_VALUE_MIN_LEN:
            values.append(value.encode("utf-8", "replace"))
    return values


def scan_bytes_for_secrets(data, parent_values):
    """Returns list of pattern class names hit (never the matched text)."""
    hits = []
    for value in parent_values:
        if value and value in data:
            hits.append("parent_env_value")
            break
    for cls, rx in SECRET_PATTERNS:
        if rx.search(data):
            hits.append(cls)
    return hits


# ---------------------------------------------------------------------------
# O. Atomic report
# ---------------------------------------------------------------------------

def write_report_atomic(path, obj, replace=os.replace):
    tmp = path + ".tmp"
    data = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True).encode("utf-8") + b"\n"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    replace(tmp, path)


def sweep_label(profile, exit_code, aborted=False, diagnostic=False):
    """K.4 word discipline. ``diagnostic`` forces DIAGNOSTIC for any run that
    is structurally not a full sweep (developer profile, fake module dir,
    self-test seam) -- FULL/RAG_GATE_PASS are reserved for real discovery."""
    if aborted:
        return "ABORTED"
    if diagnostic:
        return "DIAGNOSTIC"
    if profile == "production-parity":
        return "FULL" if exit_code == 0 else "PARTIAL"
    if profile == "rag-dependency":
        return "RAG_GATE_PASS" if exit_code == 0 else "RAG_GATE_FAIL"
    return "DIAGNOSTIC"


def module_violates_profile(profile, outcome):
    """P.3 profile rule. Pure."""
    if profile in OFFICIAL_PROFILES:
        return outcome != OUTCOME_PASS
    return outcome in FAIL_CLASS_OUTCOMES


def decide_exit_code(profile, module_outcomes, integrity_failures, refused=False, aborted=False):
    """P.2. Pure."""
    if aborted:
        return EXIT_ABORTED
    if refused:
        return EXIT_REFUSED
    if integrity_failures:
        return EXIT_INTEGRITY
    if any(module_violates_profile(profile, o) for o in module_outcomes):
        return EXIT_MODULE_FAILURE
    return EXIT_OK


# ---------------------------------------------------------------------------
# I.2 Private run directory (Windows DACL via ctypes; POSIX 0o700)
# ---------------------------------------------------------------------------

SDDL_SYSTEM = "S-1-5-18"
SDDL_ADMINS = "S-1-5-32-544"


def parse_sddl_dacl(sddl):
    """Pure. Returns (dacl_flags, [ (type, flags, rights, sid) ]) from an SDDL
    string that contains a D: section."""
    idx = sddl.find("D:")
    if idx < 0:
        return "", []
    rest = sddl[idx + 2:]
    end = rest.find("(")
    flags = rest[:end] if end >= 0 else rest
    aces = []
    for m in re.finditer(r"\(([^)]*)\)", rest):
        parts = m.group(1).split(";")
        if len(parts) < 6:
            aces.append(("MALFORMED", "", "", m.group(1)))
            continue
        aces.append((parts[0], parts[1], parts[2], parts[5]))
    return flags, aces


def dacl_is_private(sddl, user_sid):
    """Pure verification of I.2(2): protected DACL, exactly the three expected
    trustees with OICI FullControl allow ACEs, no inherited ACEs, nothing else."""
    flags, aces = parse_sddl_dacl(sddl)
    problems = []
    if "P" not in flags:
        problems.append("dacl not protected (no P flag)")
    expected = {
        ("A", "OICI", "FA", user_sid),
        ("A", "OICI", "FA", "SY"),
        ("A", "OICI", "FA", "BA"),
    }
    normalized = set()
    for ace in aces:
        typ, aflags, rights, sid = ace
        if "ID" in aflags:
            problems.append("inherited ACE present for %s" % sid)
        if sid == SDDL_SYSTEM:
            sid = "SY"
        if sid == SDDL_ADMINS:
            sid = "BA"
        normalized.add((typ, aflags, rights, sid))
    if normalized != expected:
        problems.append("ACE set differs from expected owner/SYSTEM/Administrators FullControl")
    return (len(problems) == 0), problems


class _Win32:
    def __init__(self):
        import ctypes.wintypes as wt
        self.wt = wt
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        k = self.kernel32
        a = self.advapi32
        k.GetCurrentProcess.restype = wt.HANDLE
        k.CloseHandle.argtypes = [wt.HANDLE]
        k.LocalFree.argtypes = [ctypes.c_void_p]
        k.CreateDirectoryW.argtypes = [wt.LPCWSTR, ctypes.c_void_p]
        k.CreateDirectoryW.restype = wt.BOOL
        a.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
        a.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
        a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.LPWSTR)]
        a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wt.LPCWSTR, wt.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.ULONG)]
        a.GetNamedSecurityInfoW.argtypes = [
            wt.LPCWSTR, ctypes.c_int, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        a.GetNamedSecurityInfoW.restype = wt.DWORD
        a.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.POINTER(wt.LPWSTR), ctypes.POINTER(wt.ULONG)]

    def current_user_sid(self):
        wt = self.wt
        tok = wt.HANDLE()
        if not self.advapi32.OpenProcessToken(self.kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(tok)):
            raise OSError("OpenProcessToken failed: %d" % ctypes.get_last_error())
        try:
            need = wt.DWORD()
            self.advapi32.GetTokenInformation(tok, 1, None, 0, ctypes.byref(need))
            buf = ctypes.create_string_buffer(need.value)
            if not self.advapi32.GetTokenInformation(tok, 1, buf, need.value, ctypes.byref(need)):
                raise OSError("GetTokenInformation failed: %d" % ctypes.get_last_error())
            sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            s = wt.LPWSTR()
            if not self.advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(s)):
                raise OSError("ConvertSidToStringSidW failed: %d" % ctypes.get_last_error())
            try:
                return s.value
            finally:
                self.kernel32.LocalFree(s)
        finally:
            self.kernel32.CloseHandle(tok)

    def create_private_directory(self, path, user_sid):
        """CreateDirectoryW with a creation-time protected DACL. Returns
        True on creation, False when the path already exists."""
        wt = self.wt
        sddl = "D:P(A;OICI;FA;;;%s)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)" % user_sid
        psd = ctypes.c_void_p()
        sz = wt.ULONG()
        if not self.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(psd), ctypes.byref(sz)):
            raise OSError("ConvertStringSecurityDescriptorToSecurityDescriptorW failed: %d" % ctypes.get_last_error())
        try:
            class SECURITY_ATTRIBUTES(ctypes.Structure):
                _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p), ("bInheritHandle", wt.BOOL)]
            sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), psd, False)
            ok = self.kernel32.CreateDirectoryW(path, ctypes.byref(sa))
            if not ok:
                err = ctypes.get_last_error()
                if err == 183:  # ERROR_ALREADY_EXISTS
                    return False
                raise OSError("CreateDirectoryW failed: %d" % err)
            return True
        finally:
            self.kernel32.LocalFree(psd)

    def read_dacl_sddl(self, path):
        wt = self.wt
        pdacl = ctypes.c_void_p()
        psd = ctypes.c_void_p()
        rc = self.advapi32.GetNamedSecurityInfoW(path, 1, 0x4, None, None, ctypes.byref(pdacl), None, ctypes.byref(psd))
        if rc != 0:
            raise OSError("GetNamedSecurityInfoW failed: %d" % rc)
        try:
            out = wt.LPWSTR()
            n = wt.ULONG()
            if not self.advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(psd, 1, 0x4, ctypes.byref(out), ctypes.byref(n)):
                raise OSError("ConvertSecurityDescriptorToStringSecurityDescriptorW failed: %d" % ctypes.get_last_error())
            try:
                return out.value
            finally:
                self.kernel32.LocalFree(out)
        finally:
            self.kernel32.LocalFree(psd)


def create_exclusive_private_run_dir(output_root, base_name, verify_seam=None, max_suffix=1000):
    """I.2(1)-(2). Creates <output_root>/<base_name>[_n] exclusively with a
    private DACL (Windows) / 0o700 (POSIX) and verifies it BEFORE returning.
    Returns (path, verification_info). Raises RuntimeError on failure (the
    directory is removed first)."""
    os.makedirs(output_root, exist_ok=True)
    win = _Win32() if sys.platform == "win32" else None
    user_sid = win.current_user_sid() if win else None
    chosen = None
    for n in range(0, max_suffix):
        candidate = os.path.join(output_root, base_name if n == 0 else "%s_%d" % (base_name, n))
        if win:
            created = win.create_private_directory(candidate, user_sid)
        else:
            try:
                os.mkdir(candidate, 0o700)
                created = True
            except FileExistsError:
                created = False
        if created:
            chosen = candidate
            break
    if chosen is None:
        raise RuntimeError("could not allocate an exclusive run directory under %s" % output_root)
    info = {"path": chosen, "platform": sys.platform}
    if win:
        sddl = win.read_dacl_sddl(chosen)
        ok, problems = dacl_is_private(sddl, user_sid)
        if verify_seam is not None:
            ok, problems = verify_seam(sddl, user_sid)
        info["dacl_ok"] = ok
        info["dacl_problems"] = problems
    else:
        os.chmod(chosen, 0o700)
        mode = stat.S_IMODE(os.stat(chosen).st_mode)
        ok = (mode == 0o700)
        if verify_seam is not None:
            ok, problems = verify_seam("mode=%o" % mode, None)
        else:
            problems = [] if ok else ["mode is %o, expected 700" % mode]
        info["dacl_ok"] = ok
        info["dacl_problems"] = problems
    if not ok:
        try:
            os.rmdir(chosen)
        except OSError:
            pass
        raise RuntimeError("run directory ACL verification failed: %s" % "; ".join(problems))
    return chosen, info


# ---------------------------------------------------------------------------
# N. Windows Job Object
# ---------------------------------------------------------------------------

class _JobObject:
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

    def __init__(self):
        import ctypes.wintypes as wt
        self.wt = wt
        self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        k = self.k
        k.CreateJobObjectW.restype = wt.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
        k.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
        k.TerminateJobObject.argtypes = [wt.HANDLE, ctypes.c_uint]
        k.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
        k.CloseHandle.argtypes = [wt.HANDLE]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class BASIC_ACCOUNTING(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", wt.DWORD), ("TotalProcesses", wt.DWORD),
                ("ActiveProcesses", wt.DWORD), ("TotalTerminatedProcesses", wt.DWORD)]

        self.EXTENDED_LIMIT = EXTENDED_LIMIT
        self.BASIC_ACCOUNTING = BASIC_ACCOUNTING
        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObjectW failed: %d" % ctypes.get_last_error())
        # B2-R1: from here on the handle is owned; any unwind before the
        # constructor returns (limit-setting failure OR a KeyboardInterrupt
        # arriving between the two Win32 calls) closes it -- a handle that
        # never reaches the caller can never be closed by the caller.
        try:
            info = EXTENDED_LIMIT()
            info.BasicLimitInformation.LimitFlags = self.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise OSError("SetInformationJobObject failed: %d" % ctypes.get_last_error())
        except BaseException:
            k.CloseHandle(self.handle)
            self.handle = None
            raise

    def assign(self, process_handle):
        if not self.k.AssignProcessToJobObject(self.handle, self.wt.HANDLE(int(process_handle))):
            raise OSError("AssignProcessToJobObject failed: %d" % ctypes.get_last_error())

    def terminate(self):
        self.k.TerminateJobObject(self.handle, 1)

    def active_processes(self):
        acc = self.BASIC_ACCOUNTING()
        if not self.k.QueryInformationJobObject(self.handle, 1, ctypes.byref(acc), ctypes.sizeof(acc), None):
            raise OSError("QueryInformationJobObject failed: %d" % ctypes.get_last_error())
        return int(acc.ActiveProcesses)

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def wait_for_zero_active(job, grace_s=5.0, poll_s=0.1):
    deadline = time.monotonic() + grace_s
    last = None
    while time.monotonic() < deadline:
        last = job.active_processes()
        if last == 0:
            return 0
        time.sleep(poll_s)
    return job.active_processes() if last is None else last


CREATE_SUSPENDED = 0x00000004  # CreateProcess creation flag


def resume_suspended_process(pid, attempts=5):
    """B2 (Windows): resume the single main thread of a process created with
    CREATE_SUSPENDED -- called only AFTER the process is a member of its Job
    Object, so the child never executes an instruction outside the job (the
    N.2 assignment window is closed). Any failure raises
    JobContainmentError("resume", ...) and the caller kills the child."""
    import ctypes.wintypes as wt
    k = ctypes.WinDLL("kernel32", use_last_error=True)

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
                    ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", wt.LONG), ("tpDeltaPri", wt.LONG),
                    ("dwFlags", wt.DWORD)]

    k.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k.Thread32First.restype = wt.BOOL
    k.Thread32First.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
    k.Thread32Next.restype = wt.BOOL
    k.Thread32Next.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
    k.OpenThread.restype = wt.HANDLE
    k.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k.ResumeThread.restype = wt.DWORD
    k.ResumeThread.argtypes = [wt.HANDLE]
    k.CloseHandle.argtypes = [wt.HANDLE]
    invalid = ctypes.c_void_p(-1).value
    tids = []
    for _ in range(attempts):
        snap = k.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        if not snap or snap == invalid:
            time.sleep(0.02)
            continue
        try:
            te = THREADENTRY32()
            te.dwSize = ctypes.sizeof(te)
            ok = k.Thread32First(snap, ctypes.byref(te))
            while ok:
                if te.th32OwnerProcessID == pid:
                    tids.append(int(te.th32ThreadID))
                ok = k.Thread32Next(snap, ctypes.byref(te))
        finally:
            k.CloseHandle(snap)
        if tids:
            break
        time.sleep(0.02)
    if not tids:
        raise JobContainmentError("resume", RuntimeError("no thread found for the suspended child"))
    for tid in tids:
        h = k.OpenThread(0x0002, False, tid)  # THREAD_SUSPEND_RESUME
        if not h:
            raise JobContainmentError("resume", OSError(ctypes.get_last_error(), "OpenThread failed"))
        try:
            prev = k.ResumeThread(h)
        finally:
            k.CloseHandle(h)
        if prev == 0xFFFFFFFF:
            raise JobContainmentError("resume", OSError(ctypes.get_last_error(), "ResumeThread failed"))
    return len(tids)


def kill_and_wait(proc, wait_s=30.0):
    """Terminate a (never-resumed or runaway) child and wait for it. Returns a
    list of problems (empty on success); never raises."""
    problems = []
    try:
        proc.kill()
    except OSError as exc:
        problems.append("kill: %s" % type(exc).__name__)
    try:
        proc.wait(timeout=wait_s)
    except subprocess.TimeoutExpired:
        problems.append("child did not exit within %ss after kill" % wait_s)
    return problems


def terminate_tree(job, proc, wait_s=30.0):
    """Terminate the direct child itself AND the whole module tree (Job Object
    on Windows, process group on POSIX), then wait for the direct child.

    The direct kill is UNCONDITIONAL and comes first: a child that was spawned
    (suspended) but never became a job member -- an unwind such as Ctrl-C
    between Popen and a successful AssignProcessToJobObject -- is not reached
    by TerminateJobObject; without the direct kill it would leak suspended
    forever while the empty job truthfully reports ActiveProcesses == 0.
    Popen.kill() is idempotent on an already-dead child (CPython maps the
    ERROR_ACCESS_DENIED of an exited process to its exit code). Grandchildren
    are job members and are reached by the tree terminate. Returns problems,
    never raises."""
    problems = []
    try:
        proc.kill()
    except OSError as exc:
        problems.append("kill: %s" % type(exc).__name__)
    try:
        if job is not None:
            job.terminate()
        else:
            os.killpg(proc.pid, 9)
    except OSError as exc:
        problems.append("terminate: %s" % type(exc).__name__)
    try:
        proc.wait(timeout=wait_s)
    except subprocess.TimeoutExpired:
        problems.append("child did not exit within %ss after termination" % wait_s)
    return problems


# ---------------------------------------------------------------------------
# M. Discovery
# ---------------------------------------------------------------------------

def git_tracked_test_modules(repo_root):
    """Returns (set_of_names, error). Read-only git."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", "ui/tests/test_*.py"],
            cwd=repo_root, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "git unavailable: %s" % type(exc).__name__
    if out.returncode != 0:
        return None, "git ls-files failed with exit %d" % out.returncode
    names = set()
    for raw in out.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "replace").replace("\\", "/")
        if rel.startswith("ui/tests/") and rel.count("/") == 2 and rel.endswith(".py"):
            names.add(rel.rsplit("/", 1)[-1][:-3])
    return names, None


def filesystem_test_modules(tests_dir):
    """os.scandir: regular files only, no reparse points/symlinks (lstat),
    realpath inside tests_dir, realpath-deduplicated. Returns (names, rejected)."""
    names = {}
    rejected = []
    real_root = os.path.realpath(tests_dir)
    with os.scandir(tests_dir) as it:
        for entry in it:
            if not (entry.name.startswith("test_") and entry.name.endswith(".py")):
                continue
            st = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(st.st_mode) or (getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                rejected.append({"name": entry.name, "reason": "symlink/reparse point"})
                continue
            if not stat.S_ISREG(st.st_mode):
                rejected.append({"name": entry.name, "reason": "not a regular file"})
                continue
            real = os.path.realpath(entry.path)
            if os.path.dirname(real) != real_root:
                rejected.append({"name": entry.name, "reason": "realpath outside tests dir"})
                continue
            names[real] = entry.name[:-3]
    return set(names.values()), rejected


def reconcile_discovery(tracked, fs_names):
    """Pure. Returns (missing_tracked, untracked)."""
    return sorted(tracked - fs_names), sorted(fs_names - tracked)


# ---------------------------------------------------------------------------
# O.3 / N.4 / N.5 manifests
# ---------------------------------------------------------------------------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_tracked_files(repo_root):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=repo_root, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("git ls-files failed")
    return [p.decode("utf-8", "replace") for p in out.stdout.split(b"\0") if p]


def walk_files(root, skip_dir_names=()):
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dir_names]
        for fn in filenames:
            result.append(os.path.join(dirpath, fn))
    return result


def protected_path_manifest(repo_root):
    """O.3: raw SHA-256 of every tracked file + full data/** and index/** trees
    + git status (porcelain, ignored, untracked) for data/cases and index."""
    entries = {}
    for rel in git_tracked_files(repo_root):
        abs_path = os.path.join(repo_root, rel)
        try:
            entries[rel.replace("\\", "/")] = sha256_file(abs_path)
        except OSError:
            entries[rel.replace("\\", "/")] = "<unreadable>"
    for sub in ("data", "index"):
        base = os.path.join(repo_root, sub)
        if os.path.isdir(base):
            for abs_path in walk_files(base):
                rel = os.path.relpath(abs_path, repo_root).replace("\\", "/")
                try:
                    entries[rel] = sha256_file(abs_path)
                except OSError:
                    entries[rel] = "<unreadable>"
    status = subprocess.run(
        ["git", "status", "--porcelain", "--ignored", "-uall", "--", "data/cases", "index"],
        cwd=repo_root, stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
    )
    entries["<git status data/cases index>"] = hashlib.sha256(status.stdout).hexdigest()
    return entries


def manifest_diff(before, after):
    """Pure. Returns sorted list of {path, change}."""
    diffs = []
    for k in sorted(set(before) | set(after)):
        if k not in after:
            diffs.append({"path": k, "change": "deleted"})
        elif k not in before:
            diffs.append({"path": k, "change": "new"})
        elif before[k] != after[k]:
            diffs.append({"path": k, "change": "modified"})
    return diffs


def bytecode_manifest(repo_root, skip_dir_names=(".git", ".venv", "node_modules")):
    found = set()
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in skip_dir_names and not d.startswith(".venv")]
        for fn in filenames:
            if fn.endswith(".pyc"):
                found.add(os.path.join(dirpath, fn))
    return found


def top_level_entries(path):
    try:
        return set(os.listdir(path))
    except OSError:
        return set()


# ---------------------------------------------------------------------------
# H.5 Positive-control child (written to <run>/pc/positive_control.py)
# ---------------------------------------------------------------------------

POSITIVE_CONTROL_SOURCE = r'''
import json, os, socket, subprocess, sys
D = sys.argv[1]
results = {}
def blocked(fn):
    try:
        fn()
    except PermissionError:
        return True
    except Exception:
        return False
    return False
def allowed(fn):
    try:
        fn()
    except PermissionError:
        return False
    except Exception:
        return True
    return True
results["1_env_open_blocked"] = blocked(lambda: open(os.path.join(D, ".env"), "rb"))
results["2_env_local_open_blocked"] = blocked(lambda: open(os.path.join(D, ".env.local"), "rb"))
def _envx():
    with open(os.path.join(D, ".envx"), "rb") as f:
        f.read()
results["3_envx_allowed"] = allowed(_envx)
results["4_dns_blocked"] = blocked(lambda: socket.getaddrinfo("example.invalid", 80))
def _connect():
    s = socket.socket(); s.settimeout(1)
    try:
        s.connect(("203.0.113.1", 9))
    finally:
        s.close()
results["5_connect_blocked"] = blocked(_connect)
def _sendto():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(b"x", ("203.0.113.1", 9))
    finally:
        s.close()
results["6_sendto_blocked"] = blocked(_sendto)
results["7_dns_localhost_allowed"] = allowed(lambda: socket.getaddrinfo("localhost", 80))
def _loop():
    s = socket.socket(); s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", 1))
    except PermissionError:
        raise
    except OSError:
        return
    finally:
        s.close()
results["8_loopback_connect_allowed"] = allowed(_loop)
r = subprocess.run([sys.executable, "-c", "import sys; sys.exit(0)"], capture_output=True, timeout=60)
results["9_guarded_grandchild_exit0"] = (r.returncode == 0)
r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.exit(0)"], capture_output=True, timeout=60)
results["10_isolated_grandchild_exit0"] = (r.returncode == 0)
print(json.dumps(results, sort_keys=True))
'''

POSITIVE_CONTROL_KEYS = (
    "1_env_open_blocked", "2_env_local_open_blocked", "3_envx_allowed", "4_dns_blocked",
    "5_connect_blocked", "6_sendto_blocked", "7_dns_localhost_allowed",
    "8_loopback_connect_allowed", "9_guarded_grandchild_exit0", "10_isolated_grandchild_exit0",
)


def evaluate_positive_controls(results, pc_records):
    """Pure. Returns (passed_count, failures)."""
    failures = []
    for key in POSITIVE_CONTROL_KEYS:
        if results.get(key) is not True:
            failures.append(key)
    armed = sum(1 for r in pc_records if r.kind == "GUARD_ARMED")
    popens = [r for r in pc_records if r.kind == "POPEN" and popen_is_python(popen_argv_from_record(r))]
    unarmed = [r for r in popens if popen_has_unarmed_flag(popen_argv_from_record(r))]
    env_blocked = sum(1 for r in pc_records if r.kind == "ENV_OPEN_BLOCKED")
    net_blocked = sum(1 for r in pc_records if r.kind == "NET_BLOCKED")
    if armed != 2:
        failures.append("ledger:GUARD_ARMED expected 2 (child + guarded grandchild), got %d" % armed)
    if len(popens) != 2:
        failures.append("ledger:POPEN python expected 2, got %d" % len(popens))
    if len(unarmed) != 1:
        failures.append("ledger:-I POPEN expected exactly 1, got %d" % len(unarmed))
    if env_blocked != 2:
        failures.append("ledger:ENV_OPEN_BLOCKED expected 2, got %d" % env_blocked)
    if net_blocked != 3:
        failures.append("ledger:NET_BLOCKED expected 3, got %d" % net_blocked)
    passed = len(POSITIVE_CONTROL_KEYS) - sum(1 for f in failures if not f.startswith("ledger:"))
    return passed, failures


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_output_root():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "vergi_ai", "test_sweeps")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "vergi_ai", "test_sweeps")


def path_is_inside(child, parent):
    child_r = os.path.realpath(child)
    parent_r = os.path.realpath(parent)
    try:
        return os.path.commonpath([child_r, parent_r]) == parent_r
    except ValueError:
        return False


def build_arg_parser():
    p = argparse.ArgumentParser(
        prog="run_ui_tests.py",
        description="Single honest runner for ui/tests (Pilot Readiness Step 3).",
        epilog=(
            "production-parity operator preconditions (values never printed): a fresh, DISPOSABLE, "
            "loopback-only PostgreSQL 16 with migrations 0001-0006 applied; environment "
            "VERGI_TEST_PG_DSN=<dbname> PGHOST=127.0.0.1 PGPORT=<port> PGUSER=<user> "
            "VERGI_TEST_PSQL_BIN=<psql.exe> VERGI_TEST_PG_SUPERUSER_AVAILABLE=1 "
            "VERGI_TEST_PG_MAINTENANCE_DB=postgres. "
            "AUTHENTICATION, disposable test cluster ONLY: a trust rule is permitted here and "
            "nowhere else, and only when the pg_hba line matches the exact bootstrap superuser "
            "AND the exact loopback address, i.e. 'host all <superuser> 127.0.0.1/32 trust'. "
            "'host all all 127.0.0.1/32 trust' and every other blanket-trust rule are FORBIDDEN "
            "and are refused by test_iam_runtime_privileges_postgres' P1 check. vergi_owner, "
            "vergi_app, vergi_iam_admin and every other role authenticate with scram-sha-256. "
            "The PERSISTENT pilot cluster uses trust for no role at all, the superuser included. "
            "The runner carries neither PGPASSWORD nor PGPASSFILE into any child process: both "
            "are denylisted, so a test that needs a password supplies it through libpq's "
            "`passfile` connection parameter, never through the environment. "
            "0006 additionally requires the roles vergi_owner / vergi_app / vergi_iam_admin to "
            "exist (created by operational bootstrap, never by a migration), none of them "
            "superuser/createdb/createrole/replication/bypassrls, with the database and both "
            "schemas owned by vergi_owner. This is NOT the persistent IAM database; "
            "VERGI_IAM_DATABASE_URL is never forwarded and a same-target value is refused."
        ),
    )
    p.add_argument("--profile", choices=PROFILES, required=True)
    p.add_argument("--module-timeout", type=float, default=DEFAULT_MODULE_TIMEOUT_S)
    p.add_argument("--output-root", default=None)
    p.add_argument("--select", nargs="+", default=None, help="developer only: module names to run")
    p.add_argument("--tests-dir", default=None, help="runner self-test only: fake module directory")
    p.add_argument("--allow-untracked", action="store_true", help="developer only")
    return p


class Refusal(Exception):
    pass


class SweepStop(Exception):
    """B2: fail-closed stop after a module. No further module is spawned;
    the finding is already recorded as an integrity failure (exit 3)."""


class JobContainmentError(OSError):
    """B2: the spawned child could not be contained in its Job Object."""

    def __init__(self, stage, cause):
        OSError.__init__(self, "%s: %s" % (stage, type(cause).__name__))
        self.stage = stage
        self.cause_name = type(cause).__name__


class Sweep:
    def __init__(self, args, parent_env, repo_root, stdout):
        self.args = args
        self.parent_env = dict(parent_env)
        self.repo_root = repo_root
        self.out = stdout
        self.profile = args.profile
        self.pid = os.getpid()
        self.run_id = "%s_%d" % (_dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), self.pid)
        self.report = {
            "runner_version": RUNNER_VERSION,
            "profile": self.profile,
            "sweep_label": None,
            "state": "running",
            "started_at": utc_now(),
            "finished_at": None,
            "run_id": self.run_id,
            "interpreter": {
                "executable": sys.executable,
                "version": "%d.%d.%d" % sys.version_info[:3],
                "prefix": sys.prefix,
                "capabilities": {},
            },
            "git": {},
            "discovery": {},
            "env_snapshot": {},
            "guard": {},
            "postgres": {"required": self.profile in PG_PROFILES},
            "modules": [],
            "totals": {},
            "integrity": {},
            "refusals": [],
            "warnings": [],
            "deviations": [
                "TEMP/TMP for children point at a short private runner-owned %TEMP%/vsw_<pid> directory instead of the parent %TEMP% itself",
                "NESTED_RUNNER ledger record: a runner armed by a parent sweep announces itself so the parent excludes its spawns; the exclusion is limited to that nested runner's life window (its GUARD_ARMED line up to the same pid's next GUARD_ARMED) because Windows reuses pids and a bare-pid exclusion hid the python spawns of ordinary processes (V2); nested_runner_count counts NESTED_RUNNER records, nested_runner_unique_pids the distinct pids",
                "RAG gate K.1 amendment (user decision): the informational-skip total must be zero after subtracting the ONE named platform-gated skip of RAG_GATE_PLATFORM_SKIPS (builder module, win32, exact whole-line pattern, at most once); the raw total and the exempted count are reported separately",
                "Windows children are spawned CREATE_SUSPENDED, assigned to the per-module Job Object and only then resumed: N.2's assignment window (W11) is closed, not merely disclosed; an assignment/resume failure kills the never-started child, is recorded as JOB_CONTAINMENT_FAILURE and STOPS the sweep (exit 3)",
                "A Job Object CREATION failure is a refusal (exit 2) only BEFORE the first module; after at least one module has run it is recorded as JOB_CONTAINMENT_FAILURE (stage create, module never spawned), STOPS the sweep and phase_post_run still collects the evidence of the modules that did run (exit 3) -- never a late refusal that would relabel partial work as 'no module ran' (B2-R1)",
            ],
            "raw_logs_are_diagnostic_only": True,
            "runner_exit_code": None,
        }
        self.run_dir = None
        self.report_path = None
        self.integrity_failures = []
        self.module_outcomes = []
        self.pg_dsn = None
        self.selftest_seam = parent_env.get(SELFTEST_SEAM_ENV) == "1"
        self._last_module_cleanup = None  # B2: outcome of the last module's tree cleanup (also on Ctrl-C)
        self.nested_parent_ledger = parent_env.get(GUARD_LEDGER_ENV)

    # -- console ---------------------------------------------------------
    def say(self, text):
        self.out.write(text + "\n")
        self.out.flush()

    # -- report ----------------------------------------------------------
    def flush_report(self):
        if self.report_path is None:
            return
        try:
            write_report_atomic(self.report_path, self.report)
        except OSError as exc:
            self.integrity_failures.append({"kind": "REPORT_WRITE_FAILURE", "detail": type(exc).__name__})
            sys.stderr.write("REPORT_WRITE_FAILURE: %s\n" % type(exc).__name__)
            sys.stderr.flush()
            raise

    def refuse(self, code, message):
        self.report["refusals"].append({"code": code, "message": message})
        raise Refusal("%s: %s" % (code, message))

    # -- phases ----------------------------------------------------------
    def phase_recursion_lock(self):
        if GUARD_PARENT_PID_ENV in self.parent_env:
            if self.args.tests_dir:
                return
            if self.selftest_seam and self.args.select and not any(s.startswith("test_run_ui_tests") for s in self.args.select):
                self.report["warnings"].append("selftest seam: nested runner with --select under a parent sweep")
                return
            self.refuse("RECURSION", "runner started inside a sweep child environment without --tests-dir")

    def phase_usage(self):
        a = self.args
        if a.module_timeout <= 0:
            self.refuse("USAGE", "--module-timeout must be positive")
        if a.select and self.profile != "developer":
            self.refuse("USAGE", "--select is developer-only")
        if a.allow_untracked and self.profile != "developer":
            self.refuse("USAGE", "--allow-untracked is developer-only")
        if a.tests_dir and self.profile in OFFICIAL_PROFILES and not self.selftest_seam:
            self.refuse("USAGE", "--tests-dir is rejected for official profiles")
        if a.tests_dir and not os.path.isdir(a.tests_dir):
            self.refuse("USAGE", "--tests-dir is not a directory")

    def phase_capabilities(self):
        present = probe_capabilities()
        self.report["interpreter"]["capabilities"] = present
        ok, missing, warnings = evaluate_profile_capabilities(self.profile, present, sys.version_info)
        for w in warnings:
            self.report["warnings"].append("capability: " + w)
            self.say("WARNING capability: " + w)
        if not ok:
            self.refuse("CAPABILITY_MISSING", "interpreter lacks required capability: %s" % ", ".join(missing))

    def phase_pg_syntax(self):
        env = self.parent_env
        dsn = env.get("VERGI_TEST_PG_DSN")
        if self.profile == "rag-dependency":
            if dsn:
                self.refuse("PROFILE_MIX", "VERGI_TEST_PG_DSN is set; the rag-dependency profile must run without PostgreSQL")
            return
        if self.profile == "production-parity":
            reason = validate_pg_dsn_name(dsn)
            if reason:
                self.refuse("PG_DSN", reason)
            for name, fn in (("PGHOST", validate_pghost), ("PGPORT", validate_pgport)):
                r = fn(env.get(name))
                if r:
                    self.refuse("PG_ENV", r)
            if env.get("VERGI_TEST_PG_SUPERUSER_AVAILABLE") != "1":
                self.refuse("PG_ENV", "VERGI_TEST_PG_SUPERUSER_AVAILABLE must be 1")
            psql = env.get("VERGI_TEST_PSQL_BIN")
            if psql:
                if not os.path.isfile(psql):
                    self.refuse("PG_ENV", "VERGI_TEST_PSQL_BIN does not name an existing file")
            else:
                from shutil import which
                if which("psql") is None:
                    self.refuse("PG_ENV", "VERGI_TEST_PSQL_BIN unset and psql not on PATH")
            self.pg_dsn = dsn
        elif dsn:
            reason = validate_pg_dsn_name(dsn)
            if reason:
                self.refuse("PG_DSN", reason)
            r = validate_pghost(env.get("PGHOST"))
            if r:
                self.refuse("PG_ENV", r)
            self.pg_dsn = dsn
        # L.2 same-target refusal (any profile where a target exists)
        iam_url = env.get("VERGI_IAM_DATABASE_URL")
        if iam_url and self.pg_dsn:
            parsed = parse_iam_url_via_psycopg(iam_url)
            if parsed is None and self.profile == "production-parity":
                self.refuse("IAM_URL_UNPARSEABLE", "VERGI_IAM_DATABASE_URL present in parent but could not be parsed; refusing to guess")
            if parsed and iam_url_targets_test_db(parsed, env.get("PGHOST"), env.get("PGPORT"), self.pg_dsn):
                self.refuse("IAM_SAME_TARGET", "VERGI_IAM_DATABASE_URL points at the disposable test database; the IAM database can never be the test target")

    def phase_discovery(self):
        a = self.args
        disc = self.report["discovery"]
        if a.tests_dir:
            names, rejected = filesystem_test_modules(a.tests_dir)
            disc.update({"mode": "fake_dir", "tests_dir": os.path.realpath(a.tests_dir), "count": len(names),
                         "missing": [], "untracked": [], "rejected": rejected})
            self.tests_dir = os.path.realpath(a.tests_dir)
            self.modules = sorted(names, key=lambda s: s.encode("utf-8"))
            if rejected:
                self.refuse("DISCOVERY", "rejected entries in tests dir: %s" % ", ".join(r["name"] for r in rejected))
            return
        tests_dir = os.path.join(self.repo_root, "ui", "tests")
        tracked, err = git_tracked_test_modules(self.repo_root)
        fs_names, rejected = filesystem_test_modules(tests_dir)
        if rejected:
            self.refuse("DISCOVERY", "rejected entries in ui/tests: %s" % ", ".join("%s (%s)" % (r["name"], r["reason"]) for r in rejected))
        if tracked is None:
            if self.profile in OFFICIAL_PROFILES:
                self.refuse("DISCOVERY", "git unavailable; official profiles require the tracked module set (%s)" % err)
            self.report["warnings"].append("discovery: git unavailable, filesystem-only (%s)" % err)
            disc.update({"mode": "fs_only", "count": len(fs_names), "missing": [], "untracked": [], "rejected": []})
            self.modules = sorted(fs_names, key=lambda s: s.encode("utf-8"))
        else:
            missing, untracked = reconcile_discovery(tracked, fs_names)
            disc.update({"mode": "git_and_fs", "count": len(fs_names), "tracked_count": len(tracked),
                         "missing": missing, "untracked": untracked, "rejected": []})
            self.report["git"]["tracked_test_count"] = len(tracked)
            if missing:
                self.refuse("DISCOVERY", "MISSING_TRACKED_MODULE[%s]" % ", ".join(missing))
            if untracked and not (self.profile == "developer" and self.args.allow_untracked):
                self.refuse("DISCOVERY", "UNTRACKED_TEST_MODULE[%s]" % ", ".join(untracked))
            if untracked:
                disc["untracked_allowed"] = True
            self.modules = sorted(fs_names, key=lambda s: s.encode("utf-8"))
        self.tests_dir = tests_dir
        if self.profile == "rag-dependency":
            missing_gate = [m for m in RAG_GATE_MODULES if m not in self.modules]
            if missing_gate:
                self.refuse("DISCOVERY", "rag gate modules not discovered: %s" % ", ".join(missing_gate))
            self.modules = list(RAG_GATE_MODULES)
        if a.select:
            unknown = [s for s in a.select if s not in self.modules]
            if unknown:
                self.refuse("DISCOVERY", "--select names unknown modules: %s" % ", ".join(unknown))
            self.modules = [m for m in self.modules if m in set(a.select)]
            disc["selected"] = list(self.modules)
        disc["run_count"] = len(self.modules)

    def phase_git_state(self):
        try:
            branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.repo_root, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo_root, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
            status = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo_root, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
            self.report["git"].update({
                "branch": branch.stdout.strip() if branch.returncode == 0 else None,
                "head": head.stdout.strip() if head.returncode == 0 else None,
                "clean": (status.returncode == 0 and status.stdout.strip() == ""),
            })
        except (OSError, subprocess.TimeoutExpired):
            self.report["git"].update({"branch": None, "head": None, "clean": None})

    def phase_run_dir(self):
        root = self.args.output_root or _default_output_root()
        root = os.path.abspath(root)
        if path_is_inside(root, self.repo_root):
            self.refuse("OUTPUT_ROOT", "output root resolves inside the repository")
        try:
            self.run_dir, info = create_exclusive_private_run_dir(root, "sweep_" + self.run_id)
        except (OSError, RuntimeError) as exc:
            self.refuse("RUN_DIR", "cannot create a private run directory: %s" % exc)
        if path_is_inside(self.run_dir, self.repo_root):
            self.refuse("OUTPUT_ROOT", "run directory resolves inside the repository")
        self.report["run_dir"] = self.run_dir
        self.report["run_dir_acl"] = {k: v for k, v in info.items() if k != "path"}
        for sub in ("guard", "logs", "pc"):
            os.mkdir(os.path.join(self.run_dir, sub))
        self.guard_dir = os.path.join(self.run_dir, "guard")
        self.logs_dir = os.path.join(self.run_dir, "logs")
        self.pc_dir = os.path.join(self.run_dir, "pc")
        # Child TEMP/TMP: a SHORT, private, runner-owned directory directly
        # under the operator's temp root (not under the run dir, whose path
        # is long enough to push git/icacls -- which are not long-path
        # aware -- past MAX_PATH in some tests). Residue inside it is
        # attributable per module; it is removed at the end only when empty.
        temp_root = self.parent_env.get("TEMP") or self.parent_env.get("TMP") or tempfile.gettempdir()
        temp_root = os.path.abspath(temp_root)
        if path_is_inside(temp_root, self.repo_root):
            self.refuse("TEMP_ROOT", "parent TEMP resolves inside the repository")
        try:
            self.tmp_dir, tmp_info = create_exclusive_private_run_dir(temp_root, "vsw_%d" % self.pid)
        except (OSError, RuntimeError) as exc:
            self.refuse("RUN_DIR", "cannot create a private child temp directory: %s" % exc)
        self.report["tmp_dir"] = self.tmp_dir
        self.report["tmp_dir_acl"] = {k: v for k, v in tmp_info.items() if k != "path"}
        self.ledger_path = os.path.join(self.run_dir, "guard_ledger.tsv")
        self.report_path = os.path.join(self.run_dir, REPORT_FILENAME)
        self.say("run directory: %s" % self.run_dir)

    def phase_env(self):
        env, snapshot = build_child_env(
            self.parent_env, self.profile, self.guard_dir, self.ledger_path, self.run_id, self.pid, self.tmp_dir)
        runner_values = {"PYTHONPATH": self.guard_dir}
        runner_values.update({k: v for k, v in RAG_PROFILE_ENV.items()} if self.profile == "rag-dependency" else {})
        violations = assert_env_denylist(env, runner_values)
        if violations:
            self.refuse("ENV_DENYLIST", "programming error: denylisted names in child env: %s" % ", ".join(violations))
        self.child_env = env
        self.report["env_snapshot"] = snapshot

    def phase_guard_shim(self):
        source_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_env_guard.py")
        with open(source_path, "rb") as f:
            source = f.read()
        shim_path = os.path.join(self.guard_dir, "sitecustomize.py")
        with open(shim_path, "wb") as f:
            f.write(source)
        shim_sha = sha256_file(shim_path)
        source_sha = hashlib.sha256(source).hexdigest()
        self.report["guard"].update({
            "source_path": source_path, "source_sha256": source_sha, "shim_path": shim_path,
            "shim_sha256": shim_sha, "ledger_path": self.ledger_path,
        })
        if shim_sha != source_sha:
            self.refuse("GUARD_SHIM", "guard shim bytes differ from committed source")

    def announce_nested(self):
        """When this runner is itself a child of a parent sweep (armed by the
        parent's guard), announce our pid to the PARENT ledger first thing so
        the parent excludes every Python we spawn from its GUARD_ARMED
        accounting (our children arm into OUR ledger, not the parent's)."""
        if self.nested_parent_ledger:
            try:
                with open(self.nested_parent_ledger, "ab") as f:
                    f.write(("NESTED_RUNNER\t%d\t%d\t%s\t%s\n" % (
                        self.pid, os.getppid(), self.parent_env.get(GUARD_RUN_ID_ENV, ""), self.run_id)).encode("utf-8"))
            except OSError:
                pass

    def phase_positive_controls(self):
        decoy = os.path.join(self.pc_dir, "decoy")
        os.mkdir(decoy)
        # Written under a neutral staging name and renamed: when this runner
        # itself is nested inside a parent sweep it is armed by the parent's
        # guard, which would block open() of a ".env*" name (os.replace is
        # not an `open` audit event).
        for idx, name in enumerate((".env", ".env.local", ".envx")):
            staging = os.path.join(decoy, "decoy_%d" % idx)
            with open(staging, "wb") as f:
                f.write(b"decoy\n")
            os.replace(staging, os.path.join(decoy, name))
        script = os.path.join(self.pc_dir, "positive_control.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(POSITIVE_CONTROL_SOURCE)
        pc_ledger = os.path.join(self.pc_dir, "pc_ledger.tsv")
        env = dict(self.child_env)
        env[GUARD_LEDGER_ENV] = pc_ledger
        try:
            proc = subprocess.run(
                [sys.executable, script, decoy], cwd=self.pc_dir, env=env, stdin=subprocess.DEVNULL,
                capture_output=True, timeout=PC_CHILD_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.refuse("GUARD_POSITIVE_CONTROL", "positive-control child failed to run: %s" % type(exc).__name__)
        results = {}
        try:
            last = [ln for ln in proc.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
            results = json.loads(last[-1]) if last else {}
        except (ValueError, IndexError):
            results = {}
        try:
            with open(pc_ledger, "r", encoding="utf-8", errors="replace") as f:
                pc_records = parse_ledger_lines(f.read())
        except OSError:
            pc_records = []
        passed, failures = evaluate_positive_controls(results, pc_records)
        self.report["guard"]["positive_controls"] = {"passed": passed, "of": len(POSITIVE_CONTROL_KEYS), "failures": failures,
                                                     "child_exit_code": proc.returncode}
        if failures or proc.returncode != 0:
            self.refuse("GUARD_POSITIVE_CONTROL", "guard positive controls failed: %s" % "; ".join(failures) or "child exit %d" % proc.returncode)
        self.say("guard positive controls: %d/%d" % (passed, len(POSITIVE_CONTROL_KEYS)))

    def _pg_connect(self):
        import psycopg  # lazy, PG profiles only
        return psycopg.connect(dbname=self.pg_dsn, connect_timeout=5, application_name=APPLICATION_NAME, autocommit=True)

    def phase_pg_preflight(self):
        pg = self.report["postgres"]
        if self.pg_dsn is None:
            pg.update({"connected": False})
            return
        try:
            conn = self._pg_connect()
        except Exception as exc:
            if self.profile == "production-parity":
                self.refuse("PG_CONNECT", "cannot connect to the test database: %s" % type(exc).__name__)
            self.report["warnings"].append("postgres: connection failed (%s); PG modules will self-skip" % type(exc).__name__)
            pg.update({"connected": False})
            self.pg_dsn = None
            return
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT inet_server_addr()::text")
                addr = cur.fetchone()[0]
                pg["server_addr_loopback"] = is_loopback_server_addr(addr)
                if not pg["server_addr_loopback"]:
                    self.refuse("PG_NOT_LOOPBACK", "server reports a non-loopback address")
                cur.execute("SELECT application_name, pid FROM pg_stat_activity WHERE pid <> pg_backend_pid()")
                if concurrent_sweep_present(cur.fetchall()):
                    self.refuse("PG_CONCURRENT_SWEEP", "another %s connection is active on this server" % APPLICATION_NAME)
                tables = set()
                for _mig, kind, name in MIGRATION_SENTINELS:
                    if kind == "table":
                        cur.execute("SELECT to_regclass(%s)::text", (name,))
                        if cur.fetchone()[0] is not None:
                            tables.add(name)
                cur.execute(
                    "SELECT table_schema || '.' || table_name || '.' || column_name FROM information_schema.columns "
                    "WHERE table_schema = 'mutation' AND table_name = 'mutation_journal'")
                columns = {row[0] for row in cur.fetchall()}
                # 0006 contract probe. Fails CLOSED: if the statement itself
                # raises, every contract label counts as missing and only the
                # exception CLASS is recorded - never its message, which could
                # carry connection details.
                contracts = set()
                try:
                    cur.execute(PG_CONTRACT_SQL, {"owner": CONTRACT_ROLE_OWNER,
                                                  "app": CONTRACT_ROLE_APP,
                                                  "admin": CONTRACT_ROLE_ADMIN})
                    row = cur.fetchone()
                    if row is not None and len(row) == len(CONTRACT_LABELS):
                        contracts = {label for label, value in zip(CONTRACT_LABELS, row) if value is True}
                        pg["contract_probe"] = "ok"
                    else:
                        pg["contract_probe"] = "unexpected_shape"
                except Exception as exc:
                    conn.rollback()
                    pg["contract_probe"] = "error:%s" % type(exc).__name__
                missing = missing_migrations(tables, columns, contracts)
                pg["migrations_ok"] = (len(missing) == 0)
                pg["migrations_missing"] = missing
                if missing and self.profile == "production-parity":
                    self.refuse("MIGRATION_MISSING", "MIGRATION_MISSING[%s]" % ", ".join(missing))
                if missing:
                    self.report["warnings"].append("postgres: MIGRATION_MISSING[%s]" % ", ".join(missing))
                cur.execute("SELECT datname FROM pg_database ORDER BY datname")
                self.pg_databases_before = {row[0] for row in cur.fetchall()}
                pg["database_snapshot_count"] = len(self.pg_databases_before)
                pg["connected"] = True
        finally:
            conn.close()

    def phase_opening_manifests(self):
        self.manifest_before = protected_path_manifest(self.repo_root)
        self.bytecode_before = bytecode_manifest(self.repo_root)
        self.report["integrity"]["protected_manifest_entries"] = len(self.manifest_before)
        self.report["integrity"]["bytecode_opening_count"] = len(self.bytecode_before)

    def _spawn_module(self, name):
        stdout_path = os.path.join(self.logs_dir, name + ".stdout.bin")
        stderr_path = os.path.join(self.logs_dir, name + ".stderr.bin")
        if self.report["discovery"].get("mode") == "fake_dir":
            argv = [sys.executable, "-m", name]
            cwd = self.tests_dir
        else:
            argv = [sys.executable, "-m", "ui.tests." + name]
            cwd = self.repo_root
        return argv, cwd, stdout_path, stderr_path

    def _job_object_creation_failed(self, name, entry, exc, start):
        """B2-R1. Always raises. Before the first module a Job Object
        creation failure is a preflight-class refusal (N.2: exit 2, no
        module ran). After at least one module has run, a refusal would be
        a lie: it would return exit 2 ("nothing ran") for partial work and
        skip phase_post_run (protected-path / residue / secret / guard
        evidence of the modules that DID run). It is therefore recorded as
        a fail-class module outcome (JOB_CONTAINMENT_FAILURE, stage create,
        module never spawned, no child, no logs) plus an integrity failure,
        the report is flushed and the sweep is STOPPED with SweepStop:
        run_all_modules() spawns nothing further, phase_post_run() still
        runs and the exit code is 3 (integrity)."""
        err_name = type(exc).__name__
        if not self.report["modules"]:
            self.refuse("JOB_OBJECT", "Job Object could not be created before spawning %s (%s); module not spawned" % (name, err_name))
        entry["duration_s"] = round(time.monotonic() - start, 3)
        entry["outcome"] = OUTCOME_JOB_CONTAINMENT_FAILURE
        entry["guard_armed"] = False
        entry["parser"] = None
        entry["detail"] = ("Job Object could not be created at stage create (%s) after %d module(s) had already run; "
                           "%s was NOT spawned (no child, no logs); sweep STOPPED" % (err_name, len(self.report["modules"]), name))
        self.integrity_failures.append({"kind": "JOB_CONTAINMENT_FAILURE", "module": name, "stage": "create", "error": err_name})
        self.module_outcomes.append(entry["outcome"])
        self.report["modules"].append(entry)
        self._last_module_cleanup = {
            "module": name, "job_active_after": None, "cleanup_problems": [],
            "child_returncode": None, "child_pid": None, "job_handle_closed": None,
        }
        self.say("MODULE %s %s stage=create error=%s -> STOP (module not spawned; no further module is spawned)" % (name, entry["outcome"], err_name))
        self.flush_report()
        raise SweepStop("JOB_CONTAINMENT_FAILURE[%s] stage=create" % name)

    def run_module(self, name):
        argv, cwd, stdout_path, stderr_path = self._spawn_module(name)
        entry = {
            "name": name, "outcome": None, "passed": 0, "failed": 0, "counted_skips": 0, "informational_skips": 0,
            "exit_code": None, "duration_s": None, "stdout_log": stdout_path, "stderr_log": stderr_path,
            "stdout_sha256": None, "stderr_bytes": 0, "guard_armed": None, "job_active_after": None,
            "temp_residue": [], "detail": "", "spawned": False,
        }
        ledger_offset = os.path.getsize(self.ledger_path) if os.path.exists(self.ledger_path) else 0
        tmp_before = top_level_entries(self.tmp_dir)
        timed_out = False
        spawn_failed = False
        containment = None  # (stage, error name) when the child could not be contained
        cleanup_problems = []
        proc = None
        start = time.monotonic()
        # B2: the Job Object is created BEFORE anything is spawned. If it
        # cannot be created the module is NOT spawned. Before the first
        # module that is a preflight-class refusal (N.2: exit 2, nothing
        # ran); once at least one module has run it is a fail-class module
        # outcome + integrity failure that STOPS the sweep (exit 3) with the
        # post-run evidence still collected -- never a late "refusal" that
        # would skip phase_post_run and relabel partial work as "no module
        # ran" (B2-R1). _job_object_creation_failed() always raises.
        job = None
        if sys.platform == "win32":
            try:
                job = _JobObject()
            except OSError as exc:
                self._job_object_creation_failed(name, entry, exc, start)
        # B2-R1: this try/finally is the FIRST statement after the
        # constructor returned -- the handle is owned by the finally from
        # that instant, so a KeyboardInterrupt anywhere in the spawn/assign
        # window still reaches job.close().
        try:
            with open(stdout_path, "wb") as so, open(stderr_path, "wb") as se:
                popen_kwargs = {"cwd": cwd, "env": self.child_env, "stdin": subprocess.DEVNULL, "stdout": so, "stderr": se}
                if job is not None:
                    # The child starts SUSPENDED: it executes no instruction until
                    # it is a member of the job and is explicitly resumed.
                    popen_kwargs["creationflags"] = CREATE_SUSPENDED
                elif sys.platform != "win32":
                    popen_kwargs["start_new_session"] = True
                try:
                    proc = subprocess.Popen(argv, **popen_kwargs)
                except OSError as exc:
                    spawn_failed = True
                    entry["detail"] = "spawn failed: %s" % type(exc).__name__
                else:
                    entry["spawned"] = True
                if proc is not None and job is not None:
                    try:
                        try:
                            job.assign(proc._handle)
                        except OSError as exc:
                            raise JobContainmentError("assign", exc)
                        resume_suspended_process(proc.pid)
                    except JobContainmentError as exc:
                        # never-started child: kill + wait immediately, then stop
                        containment = (exc.stage, exc.cause_name)
                        cleanup_problems.extend(kill_and_wait(proc))
                if proc is not None and containment is None:
                    try:
                        self._wait_module(proc)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        cleanup_problems.extend(terminate_tree(job, proc))
            entry["exit_code"] = proc.returncode if proc is not None else None
        except OSError as exc:
            spawn_failed = True
            entry["detail"] = "spawn failed: %s" % type(exc).__name__
        finally:
            # Unconditional unwind (normal end, timeout, KeyboardInterrupt,
            # OSError, anything): a still-running tree is terminated, the child
            # is waited, ActiveProcesses == 0 is verified and the job handle is
            # closed. Problems are recorded as an integrity failure, never hidden.
            if proc is not None and proc.poll() is None:
                cleanup_problems.extend(terminate_tree(job, proc))
            if job is not None:
                try:
                    try:
                        active = wait_for_zero_active(job)
                        entry["job_active_after"] = active
                        if active != 0:
                            self.integrity_failures.append({"kind": "PROCESS_RESIDUE", "module": name, "active_processes": active})
                    except OSError as exc:
                        cleanup_problems.append("job accounting: %s" % type(exc).__name__)
                finally:
                    job.close()
            if cleanup_problems:
                entry["cleanup_problems"] = list(cleanup_problems)
                self.integrity_failures.append({"kind": "CLEANUP_FAILURE", "module": name, "problems": list(cleanup_problems)})
            self._last_module_cleanup = {
                "module": name, "job_active_after": entry["job_active_after"],
                "cleanup_problems": list(cleanup_problems),
                "child_returncode": proc.returncode if proc is not None else None,
                "child_pid": proc.pid if proc is not None else None,
                "job_handle_closed": (job.handle is None) if job is not None else None,
            }
        entry["duration_s"] = round(time.monotonic() - start, 3)
        if containment is not None:
            stage, err_name = containment
            entry["outcome"] = OUTCOME_JOB_CONTAINMENT_FAILURE
            entry["guard_armed"] = False
            entry["parser"] = None
            entry["detail"] = ("child could not be contained in its Job Object at stage %s (%s); the never-started child was "
                               "terminated and waited (returncode %s); sweep STOPPED" % (stage, err_name, entry["exit_code"]))
            self.integrity_failures.append({"kind": "JOB_CONTAINMENT_FAILURE", "module": name, "stage": stage, "error": err_name})
            self.module_outcomes.append(entry["outcome"])
            self.report["modules"].append(entry)
            self.say("MODULE %s %s stage=%s error=%s -> STOP (no further module is spawned)" % (name, entry["outcome"], stage, err_name))
            self.flush_report()
            raise SweepStop("JOB_CONTAINMENT_FAILURE[%s] stage=%s" % (name, stage))
        try:
            with open(stdout_path, "rb") as f:
                stdout_bytes = f.read()
        except OSError:
            stdout_bytes = b""
        try:
            entry["stderr_bytes"] = os.path.getsize(stderr_path)
        except OSError:
            entry["stderr_bytes"] = 0
        entry["stdout_sha256"] = hashlib.sha256(stdout_bytes).hexdigest()
        parsed = parse_module_output(name, stdout_bytes, entry["exit_code"] if entry["exit_code"] is not None else -1,
                                     timed_out=timed_out, spawn_failed=spawn_failed)
        for key in ("outcome", "passed", "failed", "counted_skips", "informational_skips"):
            entry[key] = getattr(parsed, key)
        entry["parser"] = parsed.as_dict()
        if parsed.detail and not entry["detail"]:
            entry["detail"] = parsed.detail
        # per-module guard check (H.2 a)
        records = self._ledger_records_from(ledger_offset)
        armed = module_guard_armed(records, self.run_id, proc.pid) if proc is not None else False
        entry["guard_armed"] = armed
        if proc is not None and not armed and not spawn_failed:
            entry["outcome"] = OUTCOME_GUARD_NOT_ARMED
            entry["detail"] = (entry["detail"] + "; " if entry["detail"] else "") + "no GUARD_ARMED ledger line for this child"
        tmp_after = top_level_entries(self.tmp_dir)
        new_tmp = sorted(tmp_after - tmp_before)
        if new_tmp:
            entry["temp_residue"] = new_tmp
        if entry["outcome"] == OUTCOME_GUARD_NOT_ARMED:
            self.integrity_failures.append({"kind": "GUARD_NOT_ARMED", "module": name})
        self.module_outcomes.append(entry["outcome"])
        self.report["modules"].append(entry)
        self.say("MODULE %s %s passed=%d failed=%d counted_skips=%d informational_skips=%d exit=%s %.1fs" % (
            name, entry["outcome"], entry["passed"], entry["failed"], entry["counted_skips"],
            entry["informational_skips"], entry["exit_code"], entry["duration_s"]))
        self.flush_report()

    def _wait_module(self, proc):
        """Waits for the module child. A KeyboardInterrupt arriving here is
        the Ctrl-C case; run_module's try/finally owns the tree cleanup."""
        proc.wait(timeout=self.args.module_timeout)

    def _ledger_records_from(self, offset):
        try:
            with open(self.ledger_path, "rb") as f:
                f.seek(offset)
                data = f.read()
        except OSError:
            return []
        return parse_ledger_lines(data.decode("utf-8", "replace"))

    def _all_ledger_records(self):
        return self._ledger_records_from(0)

    def _module_root_count(self):
        """Modules whose child actually started executing Python and therefore
        must have armed the guard. A JOB_CONTAINMENT_FAILURE module's child was
        killed while still suspended (it executed no instruction), so it is
        excluded: counting it would piggyback a spurious
        GUARD_INHERITANCE_MISMATCH onto the containment failure that already
        stopped the sweep with exit 3."""
        return sum(1 for m in self.report["modules"] if m.get("outcome") != OUTCOME_JOB_CONTAINMENT_FAILURE)

    def phase_post_run(self):
        integ = self.report["integrity"]
        # H.2 sweep-level guard accounting
        records = self._all_ledger_records()
        acct = guard_accounting(records, self.run_id, self._module_root_count())
        self.report["guard"].update(acct)
        if not acct["inheritance_ok"]:
            self.integrity_failures.append({"kind": "GUARD_INHERITANCE_MISMATCH", "detail": {
                "armed": acct["armed_count"], "expected": acct["expected_armed"],
                "unarmed_flag_popens": acct["unarmed_flag_popen_count"], "malformed": acct["malformed_lines"]}})
        if acct["suspicious_popens"]:
            self.integrity_failures.append({"kind": "SUSPICIOUS_SUBPROCESS", "detail": acct["suspicious_popens"]})
        # temp residue (N.5 a)
        temp_residue = [{"module": m["name"], "entries": m["temp_residue"]} for m in self.report["modules"] if m["temp_residue"]]
        integ["temp_residue"] = temp_residue
        if temp_residue and self.profile == "production-parity":
            self.integrity_failures.append({"kind": "TEMP_RESIDUE", "detail": temp_residue})
        # db residue (N.5 b)
        db_residue = []
        if self.pg_dsn is not None and getattr(self, "pg_databases_before", None) is not None:
            try:
                conn = self._pg_connect()
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT datname FROM pg_database ORDER BY datname")
                        after = {row[0] for row in cur.fetchall()}
                finally:
                    conn.close()
                db_residue = sorted(after - self.pg_databases_before)
            except Exception as exc:
                db_residue = ["<snapshot failed: %s>" % type(exc).__name__]
        integ["db_residue"] = db_residue
        if db_residue and self.profile == "production-parity":
            self.integrity_failures.append({"kind": "DB_RESIDUE", "detail": db_residue})
        # protected-path diff (O.3)
        try:
            after = protected_path_manifest(self.repo_root)
            diffs = manifest_diff(self.manifest_before, after)
        except Exception as exc:
            diffs = [{"path": "<manifest failed>", "change": type(exc).__name__}]
        integ["protected_manifest_ok"] = (len(diffs) == 0)
        integ["protected_path_diff"] = diffs
        if diffs:
            self.integrity_failures.append({"kind": "PROTECTED_PATH_DIFF", "detail": diffs})
        # bytecode residue (N.4)
        new_pyc = sorted(bytecode_manifest(self.repo_root) - self.bytecode_before)
        removed = []
        for p in new_pyc:
            try:
                os.remove(p)
                removed.append(os.path.relpath(p, self.repo_root).replace("\\", "/"))
            except OSError:
                removed.append(os.path.relpath(p, self.repo_root).replace("\\", "/") + " (unlink failed)")
        integ["bytecode_residue"] = removed
        if removed:
            self.report["warnings"].append("BYTECODE_RESIDUE removed: %d file(s)" % len(removed))
        # process residue summary
        integ["process_residue"] = [f for f in self.integrity_failures if f["kind"] == "PROCESS_RESIDUE"]
        # secret scan (I.2 5)
        parent_values = collect_parent_secret_values(self.parent_env)
        scan = []
        files_scanned = 0  # B2-R1: count files actually read (a never-spawned module has no logs)
        for m in self.report["modules"]:
            for key in ("stdout_log", "stderr_log"):
                try:
                    with open(m[key], "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                files_scanned += 1
                hits = scan_bytes_for_secrets(data, parent_values)
                if hits:
                    scan.append({"file": os.path.basename(m[key]), "classes": hits})
        integ["secret_scan"] = {"files_scanned": files_scanned, "hits": scan}
        if scan:
            self.integrity_failures.append({"kind": "SECRET_LEAK_SUSPECTED", "detail": scan})
        # rag gate marker
        if self.profile == "rag-dependency":
            marker_ok = False
            # K.1 contract (B3) as amended: every module of the exact
            # three-module set PASS, EFFECTIVE informational skips == 0 across
            # ALL modules (require mode), and the smoke marker present as a
            # full line. Effective = raw total minus the named platform-gated
            # skips of RAG_GATE_PLATFORM_SKIPS (one exact line of one module
            # on one platform). The rule is NOT relaxed to the smoke module
            # only, and the raw total is always reported.
            info_smoke = sum(m["informational_skips"] for m in self.report["modules"] if m["name"] == RAG_GATE_MARKER_MODULE)
            info_by_module = {m["name"]: m["informational_skips"] for m in self.report["modules"]}
            info_all = sum(info_by_module.values())
            exempt_by_module = {}
            for m in self.report["modules"]:
                if m["name"] not in RAG_GATE_PLATFORM_SKIPS:
                    continue
                try:
                    with open(m["stdout_log"], "rb") as f:
                        exempt_source = f.read()
                except OSError:
                    exempt_source = b""
                n_exempt = min(rag_gate_platform_exempt_skips(m["name"], exempt_source, _rag_gate_platform()), m["informational_skips"])
                if n_exempt:
                    exempt_by_module[m["name"]] = n_exempt
            effective_by_module = {n: c - exempt_by_module.get(n, 0) for n, c in info_by_module.items()}
            info_exempt = sum(exempt_by_module.values())
            info_effective = sum(effective_by_module.values())
            for m in self.report["modules"]:
                if m["name"] == RAG_GATE_MARKER_MODULE:
                    try:
                        with open(m["stdout_log"], "rb") as f:
                            lines, _ = split_stdout_lines(f.read())
                        marker_ok = bool(lines) and RAG_GATE_MARKER_LINE in lines
                    except OSError:
                        marker_ok = False
            self.report["rag_gate"] = {"marker_present": marker_ok, "informational_skips_smoke": info_smoke,
                                       "informational_skips_all_modules": info_all,
                                       "informational_skips_by_module": info_by_module,
                                       "informational_skips_platform_exempt": info_exempt,
                                       "informational_skips_platform_exempt_by_module": exempt_by_module,
                                       "informational_skips_effective": info_effective,
                                       "rule": "K.1 amended: all modules PASS, informational_skips_effective == 0 (raw total minus the named platform-gated skips), marker full line"}
            if not marker_ok:
                self.module_outcomes.append(OUTCOME_FAIL)
                self.report["warnings"].append("rag gate: '%s' marker line absent" % RAG_GATE_MARKER_LINE)
            if info_exempt:
                self.report["warnings"].append(
                    "rag gate: K.1 amendment exempted %d platform-gated informational skip(s) by name on %s (%s)" % (
                        info_exempt, _rag_gate_platform(), ", ".join("%s=%d" % (n, c) for n, c in sorted(exempt_by_module.items()))))
            if info_effective != 0:
                offenders = ", ".join("%s=%d" % (n, c) for n, c in sorted(effective_by_module.items()) if c)
                self.module_outcomes.append(OUTCOME_FAIL)
                self.report["warnings"].append(
                    "rag gate: K.1 requires informational skips == 0 across all modules in require mode (got %d: %s)" % (info_effective, offenders))

    def finish(self, exit_code, aborted=False):
        self.report["integrity"]["failures"] = self.integrity_failures
        mods = self.report["modules"]
        self.report["totals"] = {
            # B2-R1: an entry whose child was never spawned (Job Object
            # creation failure after the first module, spawn failure) is
            # attempted-but-not-run; a synthetic/legacy entry without the
            # flag counts as run (permissive default).
            "modules_attempted": len(mods),
            "modules_run": sum(1 for m in mods if m.get("spawned", True)),
            "modules_not_spawned": sum(1 for m in mods if not m.get("spawned", True)),
            "modules_pass": sum(1 for m in mods if m["outcome"] == OUTCOME_PASS),
            "modules_non_pass": sum(1 for m in mods if m["outcome"] != OUTCOME_PASS),
            "passed": sum(m["passed"] for m in mods),
            "failed": sum(m["failed"] for m in mods),
            "counted_skips": sum(m["counted_skips"] for m in mods),
            "informational_skips": sum(m["informational_skips"] for m in mods),
            "outcomes": {o: sum(1 for m in mods if m["outcome"] == o) for o in sorted(set(m["outcome"] for m in mods))},
        }
        self.report["state"] = "aborted" if aborted else ("stopped" if self.report.get("stopped") else "completed")
        self.report["finished_at"] = utc_now()
        self.report["runner_exit_code"] = exit_code
        self.report["sweep_label"] = sweep_label(self.profile, exit_code, aborted=aborted, diagnostic=self.is_diagnostic())
        tmp_dir = getattr(self, "tmp_dir", None)
        if tmp_dir and os.path.isdir(tmp_dir):
            try:
                if not os.listdir(tmp_dir):
                    os.rmdir(tmp_dir)
                    self.report["tmp_dir_removed"] = True
                else:
                    self.report["tmp_dir_removed"] = False  # residue kept for inspection
            except OSError:
                self.report["tmp_dir_removed"] = False
        try:
            self.flush_report()
        except OSError:
            if exit_code in (EXIT_OK, EXIT_MODULE_FAILURE):
                exit_code = EXIT_INTEGRITY
                self.report["runner_exit_code"] = exit_code
                self.report["sweep_label"] = sweep_label(self.profile, exit_code, aborted=aborted, diagnostic=self.is_diagnostic())
        return exit_code

    def is_diagnostic(self):
        return (self.profile == "developer" or self.selftest_seam
                or self.report.get("discovery", {}).get("mode") == "fake_dir")


def run_all_modules(sweep):
    """B2: run the discovered modules in order. Returns True when every module
    was attempted, False when a SweepStop ended the sweep early -- the
    remaining modules are NOT spawned. A KeyboardInterrupt is re-raised after
    the interrupted module's cleanup outcome has been recorded in the report
    (``aborted_module``) so the partial report never hides it."""
    for index, name in enumerate(sweep.modules):
        try:
            sweep.run_module(name)
        except SweepStop as exc:
            not_run = list(sweep.modules[index + 1:])
            sweep.report["stopped"] = {"after_module": name, "reason": str(exc), "modules_not_run": not_run}
            sweep.say("STOP %s - %d remaining module(s) NOT spawned" % (exc, len(not_run)))
            return False
        except KeyboardInterrupt:
            info = dict(sweep._last_module_cleanup or {})
            info["name"] = name
            sweep.report["aborted_module"] = info
            raise
    return True


def main(argv=None, parent_env=None, stdout=None):
    stdout = stdout or sys.stdout
    try:
        stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    parent_env = dict(os.environ if parent_env is None else parent_env)
    parser = build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else EXIT_REFUSED
        if code != 0:
            stdout.write("SWEEP REFUSED - exit %d\n" % EXIT_REFUSED)
            return EXIT_REFUSED
        return 0
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sweep = Sweep(args, parent_env, repo_root, stdout)
    sweep.announce_nested()
    if sweep.profile == "developer":
        sweep.say("DIAGNOSTIC - NOT A FULL SWEEP (developer profile)")
    exit_code = None
    aborted = False
    try:
        try:
            sweep.phase_recursion_lock()
            sweep.phase_usage()
            sweep.phase_capabilities()
            sweep.phase_pg_syntax()
            sweep.phase_discovery()
            sweep.phase_git_state()
            sweep.phase_run_dir()
            sweep.phase_env()
            sweep.phase_guard_shim()
            sweep.flush_report()
            sweep.phase_positive_controls()
            sweep.phase_pg_preflight()
            sweep.phase_opening_manifests()
            sweep.flush_report()
            sweep.say("profile=%s modules=%d timeout=%ss" % (sweep.profile, len(sweep.modules), args.module_timeout))
            run_all_modules(sweep)
            sweep.phase_post_run()
            exit_code = decide_exit_code(sweep.profile, sweep.module_outcomes, sweep.integrity_failures)
        except Refusal as exc:
            sweep.say("REFUSED " + str(exc))
            exit_code = decide_exit_code(sweep.profile, [], [], refused=True)
        except KeyboardInterrupt:
            aborted = True
            exit_code = EXIT_ABORTED
            am = sweep.report.get("aborted_module") or {}
            sweep.say("ABORTED (Ctrl-C) - module %s: job_active_after=%s cleanup_problems=%s" % (
                am.get("name"), am.get("job_active_after"), am.get("cleanup_problems") or []))
    except OSError as exc:
        # report write failure already recorded as integrity failure
        exit_code = EXIT_INTEGRITY
        sweep.say("INTEGRITY report write failure: %s" % type(exc).__name__)
    if sweep.report_path is not None or sweep.run_dir is not None:
        try:
            exit_code = sweep.finish(exit_code, aborted=aborted)
        except OSError:
            exit_code = EXIT_INTEGRITY
    else:
        sweep.report["sweep_label"] = sweep_label(sweep.profile, exit_code, aborted=aborted, diagnostic=sweep.is_diagnostic())
    label = sweep.report["sweep_label"]
    if label == "DIAGNOSTIC":
        sweep.say("DIAGNOSTIC - NOT A FULL SWEEP")
    sweep.say("SWEEP %s - exit %d" % (label, exit_code))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
