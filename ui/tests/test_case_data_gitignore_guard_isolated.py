# ============================================================
# PILOT READINESS ADIM 2 - Case-Data Repository Protection: permanent
# regression guard for the `.gitignore` rule that keeps NEW content
# under data/cases/ out of Git.
#
# WHAT THIS PROVES (Fable FINAL review, sections G-I, O):
#   * The production `.gitignore` (read VERBATIM from the repository
#     root - never a copy this file writes itself) carries exactly one
#     root-anchored rule `/data/cases/`, no negation, LF-only, with a
#     final newline.
#   * Git's real semantics for that rule, exercised in a DISPOSABLE
#     temp repository with fully isolated git configuration:
#       - already-tracked fixture files stay tracked: edits show as
#         ` M`, deletions as ` D`, and `git add -A` stages both;
#       - a NEW file dropped into the tracked fixture directory, a NEW
#         nested directory inside it, a NEW case directory, and a stray
#         file directly under data/cases/ are ALL ignored: `git status`
#         is silent, `git add -A --dry-run` / `git add . --dry-run` are
#         empty, a REAL `git add -A` stages nothing;
#       - `git add -f` bypasses the rule (recorded as a LIMIT, never
#         presented as a guarantee);
#       - a force-added fixture file is tracked afterwards and its later
#         edits are visible;
#       - the rule is anchored: `other/data/cases/...` is NOT ignored.
#   * A positive control: the SAME temp repository with the rule
#     stripped out of the production bytes DOES stage the synthetic
#     case data - so this file is sensitive to the rule, not tautological.
#   * A read-only probe against the real repository (only when a `.git`
#     directory exists next to this checkout): `git check-ignore
#     --no-index` for a hypothetical path (NO file is created) and
#     `git ls-files --error-unmatch` for the tracked fixture.
#
# WHAT THIS DOES NOT CLAIM: `.gitignore` only affects Git's untracked-
# file discovery/staging. It does not protect real data written INTO an
# already-tracked case_0001 file, does not stop `git add -f`, `git clean
# -x` or `git stash --all`, and is not a pre-commit hook or CI guard.
#
# SAFETY: the temp repository lives under tempfile.mkdtemp() (asserted
# to be OUTSIDE this repository); every git WRITE command targets that
# temp repository only; the only commands ever run against the real
# repository are `check-ignore --no-index` and `ls-files` (read-only).
# This file never creates, modifies or deletes anything under the real
# data/ tree.
#
# DEPENDENCY: a `git` executable on PATH. If absent, the git-dependent
# checks print an explicit `SKIPPED (NOT counted as pass/fail)` line
# (existing repository convention) - the pure-Python content checks on
# the production `.gitignore` still run and are fail-closed.
#
# Run: python -m ui.tests.test_case_data_gitignore_guard_isolated
# ============================================================

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GITIGNORE_PATH = REPO_ROOT / ".gitignore"
EXPECTED_RULE = "/data/cases/"

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


def skip_informational(label, detail=""):
    global informational_skips
    informational_skips += 1
    print(f"SKIPPED (NOT counted as pass/fail) {label} - {detail}")


# ------------------------------------------------------------
# Part 1 - pure-Python, fail-closed checks on the PRODUCTION .gitignore
# (run even when git is unavailable).
# ------------------------------------------------------------

check("gitignore exists at repository root", GITIGNORE_PATH.is_file(), str(GITIGNORE_PATH))
production_bytes = GITIGNORE_PATH.read_bytes() if GITIGNORE_PATH.is_file() else b""
production_sha256 = hashlib.sha256(production_bytes).hexdigest()

check("gitignore is non-empty", len(production_bytes) > 0)
check("gitignore is ASCII", all(b < 128 for b in production_bytes))
check("gitignore has a final newline", production_bytes.endswith(b"\n"))
cr_count = production_bytes.count(b"\r")
check("gitignore contains zero CR bytes (LF-only)", cr_count == 0, f"CR count={cr_count}")

production_lines = production_bytes.decode("ascii", errors="replace").split("\n")
rule_lines = [ln for ln in production_lines if ln.strip() and not ln.lstrip().startswith("#")]
case_rule_lines = [ln for ln in rule_lines if "data/cases" in ln]
negation_case_lines = [ln for ln in rule_lines if ln.startswith("!") and "data/cases" in ln]

check("exact rule line '/data/cases/' is present (verbatim, no surrounding whitespace)",
      EXPECTED_RULE in rule_lines, f"rule lines={rule_lines}")
check("exactly ONE rule line mentions data/cases (no weaker/duplicate variants)",
      case_rule_lines == [EXPECTED_RULE], f"case rule lines={case_rule_lines}")
check("no negation rule re-includes anything under data/cases",
      negation_case_lines == [], f"negations={negation_case_lines}")
check("legacy security exclusions still present (.env, .venv/, index/)",
      all(x in rule_lines for x in (".env", ".venv/", "index/")), f"rule lines={rule_lines}")

# ------------------------------------------------------------
# Part 2 - git-dependent semantics in a DISPOSABLE temp repository.
# ------------------------------------------------------------

GIT = shutil.which("git")


def _rmtree_force(path):
    """Remove a temp git repository on Windows too (read-only objects)."""

    def _onexc(func, p, exc):  # pragma: no cover - platform dependent
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    # `onexc` (Python 3.12+) - `onerror` is deprecated since 3.12.
    shutil.rmtree(path, onexc=_onexc)


class TempGitRepo:
    """A disposable git repository with fully isolated configuration."""

    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.root = self.base_dir / "repo"
        self.home = self.base_dir / "home"
        self.home.mkdir()
        self.root.mkdir()
        empty_config = self.home / "empty_gitconfig"
        empty_config.write_bytes(b"")
        env = dict(os.environ)
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                  "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_COMMON_DIR"):
            env.pop(k, None)
        env.update({
            "GIT_CONFIG_GLOBAL": str(empty_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "XDG_CONFIG_HOME": str(self.home),
            "GIT_CEILING_DIRECTORIES": str(self.base_dir),
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C",
            "LC_ALL": "C",
            "PYTHONIOENCODING": "utf-8",
        })
        self.env = env

    def git(self, *args, cwd=None):
        proc = subprocess.run(
            [GIT, *args],
            cwd=str(cwd or self.root),
            env=self.env,
            capture_output=True,
            timeout=120,
            check=False,
        )
        return proc.returncode, proc.stdout.decode("utf-8", errors="strict"), proc.stderr.decode("utf-8", errors="strict")

    def must(self, *args):
        rc, out, err = self.git(*args)
        if rc != 0:
            raise RuntimeError(f"git {' '.join(args)} failed rc={rc}: {err.strip()}")
        return out

    def status_lines(self):
        return [ln for ln in self.must("status", "--porcelain=v1", "--untracked-files=all").splitlines() if ln]

    def dry_add_all(self):
        return [ln for ln in self.must("add", "-A", "--dry-run").splitlines() if ln]

    def dry_add_dot(self):
        return [ln for ln in self.must("add", ".", "--dry-run").splitlines() if ln]

    def staged(self):
        return [ln for ln in self.must("diff", "--cached", "--name-status").splitlines() if ln]

    def check_ignore(self, rel):
        rc, out, _ = self.git("check-ignore", "-v", "--no-index", "--", rel)
        return rc, out.strip()

    def reset_clean(self):
        self.must("reset", "-q", "--hard")
        self.must("clean", "-qfdx")

    def write(self, rel, text="{}\n"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


FIXTURE_FILES = (
    "data/cases/case_0001/case.json",
    "data/cases/case_0001/documents/doc_0001/document.json",
    "data/cases/case_0001/timeline/timeline.json",
)


def build_repo(base_dir, gitignore_bytes):
    repo = TempGitRepo(base_dir)
    repo.must("-c", "init.defaultBranch=main", "init", "-q")
    repo.must("config", "user.email", "guard@example.invalid")
    repo.must("config", "user.name", "gitignore guard")
    repo.must("config", "core.autocrlf", "false")
    repo.must("config", "core.safecrlf", "false")
    # Mirror the real history: the fixture was tracked BEFORE the guard
    # rule existed (commit 1), then the .gitignore was introduced
    # (commit 2). No `git add -f` is needed for the fixture this way.
    for rel in FIXTURE_FILES:
        repo.write(rel)
    repo.write("src/m.py", "x = 1\n")
    repo.must("add", "-A")
    repo.must("commit", "-q", "-m", "fixture-before-guard")
    (repo.root / ".gitignore").write_bytes(gitignore_bytes)
    repo.must("add", "--", ".gitignore")
    repo.must("commit", "-q", "-m", "guard")
    return repo


def run_semantics(repo, tag):
    """The candidate-B assertion matrix (Fable FINAL section G.1)."""
    installed = (repo.root / ".gitignore").read_bytes()
    check(f"[{tag}] temp repo .gitignore is BYTE-IDENTICAL to production (binding)",
          hashlib.sha256(installed).hexdigest() == production_sha256)
    check(f"[{tag}] baseline: 3 tracked fixture files under data/cases",
          repo.must("ls-files", "data/cases").split() == list(FIXTURE_FILES))
    check(f"[{tag}] baseline: clean status", repo.status_lines() == [])

    # T1 - modify a tracked fixture file
    with open(repo.root / FIXTURE_FILES[0], "a", encoding="utf-8") as fh:
        fh.write("// edit\n")
    check(f"[{tag}] T1 tracked edit visible as ' M'", repo.status_lines() == [f" M {FIXTURE_FILES[0]}"], str(repo.status_lines()))
    check(f"[{tag}] T1 tracked edit staged by add -A --dry-run", repo.dry_add_all() == [f"add '{FIXTURE_FILES[0]}'"], str(repo.dry_add_all()))
    repo.reset_clean()

    # T2 - delete a tracked fixture file
    (repo.root / FIXTURE_FILES[2]).unlink()
    check(f"[{tag}] T2 tracked delete visible as ' D'", repo.status_lines() == [f" D {FIXTURE_FILES[2]}"], str(repo.status_lines()))
    check(f"[{tag}] T2 tracked delete staged by add -A --dry-run", repo.dry_add_all() == [f"remove '{FIXTURE_FILES[2]}'"], str(repo.dry_add_all()))
    repo.must("add", "-A")
    check(f"[{tag}] T2 real add -A stages the deletion", repo.staged() == [f"D\t{FIXTURE_FILES[2]}"], str(repo.staged()))
    repo.reset_clean()

    # T3 - NEW file dropped into the tracked fixture directory
    new_in_fixture = "data/cases/case_0001/client_real.json"
    repo.write(new_in_fixture, '{"real": true}\n')
    rc, out = repo.check_ignore(new_in_fixture)
    check(f"[{tag}] T3 new file inside case_0001 is ignored by the exact rule",
          rc == 0 and f":{EXPECTED_RULE}\t" in out, f"rc={rc} out={out!r}")
    check(f"[{tag}] T3 status silent", repo.status_lines() == [], str(repo.status_lines()))
    check(f"[{tag}] T3 add -A --dry-run empty", repo.dry_add_all() == [], str(repo.dry_add_all()))
    check(f"[{tag}] T3 add . --dry-run empty", repo.dry_add_dot() == [], str(repo.dry_add_dot()))
    repo.must("add", "-A")
    check(f"[{tag}] T3 real add -A stages nothing", repo.staged() == [], str(repo.staged()))
    repo.reset_clean()

    # T4 - NEW nested directory + file inside case_0001
    nested = "data/cases/case_0001/documents/doc_0099/extractions/facts.json"
    repo.write(nested)
    rc, out = repo.check_ignore(nested)
    check(f"[{tag}] T4 new nested dir/file inside case_0001 is ignored", rc == 0 and f":{EXPECTED_RULE}\t" in out, f"rc={rc} out={out!r}")
    check(f"[{tag}] T4 status silent + dry-runs empty",
          repo.status_lines() == [] and repo.dry_add_all() == [] and repo.dry_add_dot() == [])
    repo.reset_clean()

    # T5 - NEW case directory with nested content
    new_case = "data/cases/case_9999/case.json"
    new_case_nested = "data/cases/case_9999/documents/doc_0001/extractions/facts.json"
    repo.write(new_case)
    repo.write(new_case_nested)
    rc1, out1 = repo.check_ignore(new_case)
    rc2, out2 = repo.check_ignore(new_case_nested)
    check(f"[{tag}] T5 new case_9999 (top + nested) ignored by the exact rule",
          rc1 == 0 and rc2 == 0 and f":{EXPECTED_RULE}\t" in out1 and f":{EXPECTED_RULE}\t" in out2,
          f"{rc1}/{rc2} {out1!r} {out2!r}")
    check(f"[{tag}] T5 status silent + dry-runs empty",
          repo.status_lines() == [] and repo.dry_add_all() == [] and repo.dry_add_dot() == [])
    repo.must("add", "-A")
    check(f"[{tag}] T5 real add -A stages nothing", repo.staged() == [], str(repo.staged()))
    repo.must("reset", "-q")
    # T8 - documented LIMIT: git add -f bypasses the rule
    rc, out, _ = repo.git("add", "-f", "--dry-run", "data/cases/case_9999")
    forced = [ln for ln in out.splitlines() if ln]
    check(f"[{tag}] T8 LIMIT recorded: git add -f --dry-run WOULD stage case_9999 (bypass exists)",
          rc == 0 and sorted(forced) == sorted([f"add '{new_case}'", f"add '{new_case_nested}'"]), str(forced))
    check(f"[{tag}] T8 the forced dry-run did not actually stage anything", repo.staged() == [])
    repo.reset_clean()

    # T6 - stray file directly under data/cases/
    stray = "data/cases/stray.txt"
    repo.write(stray, "stray\n")
    rc, out = repo.check_ignore(stray)
    check(f"[{tag}] T6 stray file under data/cases/ ignored", rc == 0 and f":{EXPECTED_RULE}\t" in out, f"rc={rc} out={out!r}")
    check(f"[{tag}] T6 status silent + dry-runs empty",
          repo.status_lines() == [] and repo.dry_add_all() == [] and repo.dry_add_dot() == [])
    repo.reset_clean()

    # T9 - tracked files are not un-tracked by the rule
    check(f"[{tag}] T9 tracked fixture count unchanged", len(repo.must("ls-files", "data/cases").split()) == 3)
    rc, _, _ = repo.git("check-ignore", "-q", "--", FIXTURE_FILES[0])
    check(f"[{tag}] T9 default-mode check-ignore does NOT report the tracked fixture as ignored", rc == 1, f"rc={rc}")

    # T12 - anchoring: a nested data/cases elsewhere is NOT matched
    elsewhere = "other/data/cases/case_7777/case.json"
    repo.write(elsewhere)
    rc, out = repo.check_ignore(elsewhere)
    check(f"[{tag}] T12 rule is root-anchored: other/data/cases/... NOT ignored", rc == 1 and out == "", f"rc={rc} out={out!r}")
    check(f"[{tag}] T12 other/data/cases/... shows as untracked", repo.status_lines() == [f"?? {elsewhere}"], str(repo.status_lines()))
    repo.reset_clean()

    # T13 - intentional new fixture via git add -f stays tracked afterwards
    new_fixture = "data/cases/case_0001/new_fixture.json"
    repo.write(new_fixture)
    repo.must("add", "-f", "--", new_fixture)
    repo.must("commit", "-q", "-m", "fixture")
    with open(repo.root / new_fixture, "a", encoding="utf-8") as fh:
        fh.write("// edit\n")
    check(f"[{tag}] T13 force-added fixture file is tracked and its later edit is visible",
          repo.status_lines() == [f" M {new_fixture}"], str(repo.status_lines()))
    repo.must("reset", "-q", "--hard", "HEAD~1")
    repo.reset_clean()
    check(f"[{tag}] end: temp repo back to clean baseline", repo.status_lines() == [] and len(repo.must("ls-files", "data/cases").split()) == 3)


def run_positive_control(base_dir):
    """Same fixture, production bytes with the rule REMOVED: synthetic
    case data MUST become stageable, proving this file is sensitive to
    the rule (non-tautological)."""
    stripped_lines = [ln for ln in production_bytes.split(b"\n") if ln.strip() != EXPECTED_RULE.encode("ascii")]
    stripped = b"\n".join(stripped_lines)
    check("[control] rule really removed from the control copy", EXPECTED_RULE.encode("ascii") not in stripped)
    repo = build_repo(base_dir, stripped)
    repo.write("data/cases/case_9999/case.json")
    repo.write("data/cases/case_0001/client_real.json")
    repo.write("data/cases/stray.txt", "stray\n")
    lines = repo.status_lines()
    check("[control] WITHOUT the rule, new case data is untracked-visible (3 x ??)",
          sorted(lines) == sorted(["?? data/cases/case_9999/case.json",
                                   "?? data/cases/case_0001/client_real.json",
                                   "?? data/cases/stray.txt"]), str(lines))
    check("[control] WITHOUT the rule, add -A --dry-run WOULD stage all three", len(repo.dry_add_all()) == 3, str(repo.dry_add_all()))
    repo.must("add", "-A")
    check("[control] WITHOUT the rule, a real add -A stages all three", len(repo.staged()) == 3, str(repo.staged()))


def run_real_repo_probe():
    """Read-only probe against the real checkout. Only `check-ignore
    --no-index` and `ls-files` are ever run here; no file is created."""
    if not os.path.lexists(REPO_ROOT / ".git"):
        skip_informational("real-repo probe", "no .git next to this checkout (packaged runtime)")
        return
    # Global/system git config is isolated so an operator's personal
    # `core.excludesfile` cannot influence the result; the repository's
    # own `.gitignore` and `.git/info/exclude` are still read.
    with tempfile.TemporaryDirectory(prefix="vergi_gitignore_probe_") as probe_home:
        empty_config = Path(probe_home) / "empty_gitconfig"
        empty_config.write_bytes(b"")
        env = dict(os.environ)
        env.update({
            "GIT_CONFIG_GLOBAL": str(empty_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C",
            "LC_ALL": "C",
        })
        env.pop("GIT_CEILING_DIRECTORIES", None)
        _run_real_repo_probes(env)


def _run_real_repo_probes(env):
    def probe(*args):
        proc = subprocess.run([GIT, "-C", str(REPO_ROOT), *args], env=env, capture_output=True, timeout=120, check=False)
        return proc.returncode, proc.stdout.decode("utf-8", errors="strict").strip()

    rc, out = probe("check-ignore", "-v", "--no-index", "--", "data/cases/__probe_case__/case.json")
    check("[real] hypothetical new case path is ignored by the production rule (no file created)",
          rc == 0 and out.startswith(".gitignore:") and f":{EXPECTED_RULE}\t" in out, f"rc={rc} out={out!r}")
    rc, out = probe("check-ignore", "-v", "--no-index", "--", "data/cases/case_0001/__probe_new__.json")
    check("[real] hypothetical new file inside case_0001 is ignored by the production rule",
          rc == 0 and f":{EXPECTED_RULE}\t" in out, f"rc={rc} out={out!r}")
    rc, out = probe("ls-files", "--error-unmatch", "--", "data/cases/case_0001/case.json")
    check("[real] canonical fixture data/cases/case_0001/case.json is still tracked", rc == 0, f"rc={rc}")
    rc, out = probe("check-ignore", "-v", "--no-index", "--", "src/__probe__.py")
    check("[real] unrelated path is NOT ignored (rule is not over-broad)", rc == 1 and out == "", f"rc={rc} out={out!r}")


if GIT is None:
    skip_informational("temp-repo semantics (T1-T13)", "git executable not found on PATH")
    skip_informational("positive control", "git executable not found on PATH")
    skip_informational("real-repo probe", "git executable not found on PATH")
else:
    base = Path(tempfile.mkdtemp(prefix="vergi_gitignore_guard_")).resolve()
    try:
        check("temp base directory is OUTSIDE this repository",
              REPO_ROOT not in base.parents and base != REPO_ROOT, f"base={base}")
        (base / "control").mkdir()
        run_positive_control(base / "control")
        _rmtree_force(base / "control")
        (base / "guarded").mkdir()
        repo = build_repo(base / "guarded", production_bytes)
        run_semantics(repo, "B")
        run_real_repo_probe()
    finally:
        _rmtree_force(base)
        check("temp base directory fully removed (no residue)", not base.exists(), f"base={base}")

check("real repository .gitignore bytes unchanged by this run",
      GITIGNORE_PATH.read_bytes() == production_bytes)

# Summary line follows the existing informational-skip precedent (see
# test_fact_extraction_engine_isolated.py): only passed/failed here;
# informational skips are visible as the raw `SKIPPED (NOT counted as
# pass/fail)` lines above and are NEVER counted as pass or fail.
print(f"--- test_case_data_gitignore_guard_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
