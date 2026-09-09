# ============================================================
# ROW 19C-3b SLICE 1 - ui.cli_mutate ISOLATED TESTS.
#
# Pure-Python, no real PostgreSQL - a `FakeAuthzConn` answers the three
# real SQL shapes `ui.services.authz.PostgresAuthzRepository`/
# `ui.services.cli_authz.CliActorAuthzRepository` actually issue
# (`iam.users`, `iam.case_assignments`, `iam.user_roles`), and
# `approval_registry.case_scoped_review`/`case_scoped_approve`/
# `review_registry.get_review_record`/`apply_transition` are
# monkeypatched with recording fakes - this file tests the DISPATCHER's
# OWN responsibilities (argparse/usage validation, actor bootstrap,
# authz-vs-mutation connection separation, exit codes, existence-blind
# denial rendering, correct pass-through of arguments) - it does NOT
# re-test the facades' own internal precondition/idempotency/replay
# logic, which `test_mutation_approval_facade_isolated.py`/`test_review_
# mutation_facade_isolated.py` already exhaustively cover.
#
# Run: python ui/tests/test_cli_mutate_isolated.py
# ============================================================

import hashlib
import io
import os
import subprocess
import sys
import types
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ui.cli_mutate as cli_mutate                          # noqa: E402
from ui.services import authz as _authz                     # noqa: E402
from ui.services import cli_authz as _cli_authz              # noqa: E402
from ui.services import approval_registry as _approval_registry  # noqa: E402
from ui.services import review_registry as _review_registry      # noqa: E402

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


# ============================================================
# FAKE AUTHZ CONNECTION - answers the three real SQL shapes
# `PostgresAuthzRepository`/`CliActorAuthzRepository` issue.
# ============================================================

class _FakeAuthzCursor:
    def __init__(self, conn):
        self._conn = conn
        self._result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=()):
        self._conn.query_log.append((sql, params))
        normalized = " ".join(sql.split())
        if "FROM iam.users" in normalized:
            (user_id,) = params
            self._result = self._conn.users.get(user_id)
        elif "FROM iam.case_assignments" in normalized:
            user_id, case_id = params
            role = self._conn.assignments.get((user_id, case_id))
            self._result = (role,) if role else None
        elif "FROM iam.user_roles" in normalized:
            (user_id,) = params
            self._result = (1,) if user_id in self._conn.admins else None
        else:
            raise AssertionError(f"unexpected SQL in FakeAuthzConn: {sql!r}")

    def fetchone(self):
        return self._result


class FakeAuthzConn:
    def __init__(self, *, users=None, assignments=None, admins=None):
        self.users = users or {}
        self.assignments = assignments or {}
        self.admins = admins or set()
        self.closed = False
        self.close_calls = 0
        self.query_log = []

    def cursor(self):
        return _FakeAuthzCursor(self)

    def close(self):
        self.closed = True
        self.close_calls += 1


def _exploding_mutation_conn_factory():
    raise AssertionError("mutation connection factory was called - it must NEVER be reached on authz denial")


def run_cli(argv, *, authz_conn, mutation_conn_factory=None):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_mutate.main(
        argv,
        authz_conn_factory=lambda: authz_conn,
        mutation_conn_factory=mutation_conn_factory,
        stdout=stdout,
        stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


# ============================================================
# 1) ARGPARSE / USAGE-SHAPE ERRORS - exit 2, ZERO connection opened at all
#    (the authz_conn_factory itself must never even be called).
# ============================================================

def _exploding_authz_conn_factory():
    raise AssertionError("authz connection factory was called - a usage error must open ZERO connections")


def run_cli_usage_only(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = cli_mutate.main(
        argv,
        authz_conn_factory=_exploding_authz_conn_factory,
        mutation_conn_factory=_exploding_mutation_conn_factory,
        stdout=stdout, stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


code, _, err = run_cli_usage_only([])
check("no subcommand at all -> exit 2 (usage error), zero connections", code == cli_mutate.EXIT_USAGE_ERROR)

code, _, err = run_cli_usage_only(["approval", "--case", "x", "--row-key", "bogus_key", "--actor-user-id", "1"])
check("invalid --row-key -> exit 2, zero connections", code == cli_mutate.EXIT_USAGE_ERROR)

code, _, err = run_cli_usage_only(["approval", "--case", "x", "--row-key", "evidence", "--actor-user-id", "1", "--expected-hash", "abc"])
check(
    "--expected-hash given WITHOUT --approve -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--expected-hash" in err,
)

code, _, err = run_cli_usage_only(["approval", "--case", "x", "--row-key", "evidence", "--actor-user-id", "1", "--approve"])
check(
    "--approve given WITHOUT --expected-hash -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--expected-hash" in err,
)

code, _, err = run_cli_usage_only(["review", "--case", "x", "--review-kind", "bogus.kind", "--record-id", "r", "--actor-user-id", "1"])
check("invalid --review-kind -> exit 2, zero connections", code == cli_mutate.EXIT_USAGE_ERROR)

code, _, err = run_cli_usage_only([
    "review", "--case", "x", "--review-kind", "evidence.candidate", "--record-id", "r", "--actor-user-id", "1", "--apply",
])
check(
    "--apply WITHOUT --target-state/--note/--expected-hash -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--target-state" in err and "--note" in err and "--expected-hash" in err,
)

code, _, err = run_cli_usage_only([
    "review", "--case", "x", "--review-kind", "evidence.candidate", "--record-id", "r", "--actor-user-id", "1",
    "--apply", "--target-state", "not_a_real_state", "--note", "n", "--expected-hash", "h",
])
check(
    "--target-state not in get_allowed_targets(review_kind) -> exit 2, zero connections "
    "(pure check, never reaches DB)",
    code == cli_mutate.EXIT_USAGE_ERROR and "not_a_real_state" in err,
)

code, _, err = run_cli_usage_only([
    "review", "--case", "x", "--review-kind", "evidence.candidate", "--record-id", "r", "--actor-user-id", "1",
    "--target-state", "confirmed",
])
check(
    "--target-state given WITHOUT --apply -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--apply" in err,
)

# ROW 19C-3b SLICE 2 - `promotion` subcommand usage-shape grammar. Every
# rule fires BEFORE any connection/authz repository/filesystem probe/
# journal access (the exploding factories prove zero connections).
code, _, err = run_cli_usage_only(["promotion", "--case", "x", "--row-key", "bogus", "--actor-user-id", "1"])
check("promotion: invalid --row-key -> exit 2, zero connections", code == cli_mutate.EXIT_USAGE_ERROR)

code, _, err = run_cli_usage_only([
    "promotion", "--case", "x", "--row-key", "timeline", "--actor-user-id", "1", "--document", "d",
])
check(
    "promotion: --document with --row-key timeline -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err,
)

code, _, err = run_cli_usage_only([
    "promotion", "--case", "x", "--row-key", "timeline", "--actor-user-id", "1",
    "--approve", "--expected-hash", "h", "--note", "n",
])
check(
    "promotion: --note with --row-key timeline -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--note" in err,
)

code, _, err = run_cli_usage_only([
    "promotion", "--case", "x", "--row-key", "fact", "--actor-user-id", "1", "--approve", "--expected-hash", "h",
])
check(
    "promotion: fact --approve WITHOUT --document -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err,
)

code, _, err = run_cli_usage_only([
    "promotion", "--case", "x", "--row-key", "fact", "--document", "d", "--actor-user-id", "1", "--approve",
])
check(
    "promotion: --approve WITHOUT --expected-hash -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--expected-hash" in err,
)

code, _, err = run_cli_usage_only([
    "promotion", "--case", "x", "--row-key", "fact", "--document", "d", "--actor-user-id", "1",
    "--expected-hash", "h",
])
check(
    "promotion: --expected-hash WITHOUT --approve -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--expected-hash" in err,
)

code, _, err = run_cli_usage_only([
    "promotion", "--case", "x", "--row-key", "fact", "--document", "d", "--actor-user-id", "1", "--note", "n",
])
check(
    "promotion: --note WITHOUT --approve -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--note" in err,
)


# ============================================================
# 2) ACTOR IDENTITY - nonexistent/disabled actor, EXISTENCE-BLIND
#    denial (same message, same exit code, no class-name leak).
# ============================================================

conn_no_such_actor = FakeAuthzConn(users={})
code, out, err = run_cli(
    ["approval", "--case", "case_x", "--row-key", "evidence", "--actor-user-id", "999", "--approve", "--expected-hash", "h"],
    authz_conn=conn_no_such_actor, mutation_conn_factory=_exploding_mutation_conn_factory,
)
check("nonexistent --actor-user-id -> exit 1 (domain error), zero mutation connection", code == cli_mutate.EXIT_DOMAIN_ERROR)
check("nonexistent actor: the SAME fixed generic denial message is used", err.strip() == cli_mutate._AUTHZ_DENIAL_MESSAGE)
check("nonexistent actor: the authz connection was still closed", conn_no_such_actor.closed)

conn_disabled_actor = FakeAuthzConn(users={7: (1, True)})
code, out, err = run_cli(
    ["approval", "--case", "case_x", "--row-key", "evidence", "--actor-user-id", "7", "--approve", "--expected-hash", "h"],
    authz_conn=conn_disabled_actor, mutation_conn_factory=_exploding_mutation_conn_factory,
)
check("disabled --actor-user-id -> exit 1 (domain error), zero mutation connection", code == cli_mutate.EXIT_DOMAIN_ERROR)
check(
    "disabled actor: the EXACT SAME fixed generic denial message as 'nonexistent' - "
    "existence-blind, no class-name/reason leak",
    err.strip() == cli_mutate._AUTHZ_DENIAL_MESSAGE,
)
check("disabled actor: the authz connection was still closed", conn_disabled_actor.closed)


# ============================================================
# 3) AUTHZ DENIAL (unassigned / wrong capability) - via the REAL
#    authorize_case_access() call chain (CliActorAuthzRepository against
#    the fake connection's 3 query shapes), for BOTH preview ("read")
#    and apply ("mutate") modes. ZERO mutation connection either way.
# ============================================================

conn_unassigned = FakeAuthzConn(users={7: (1, False)}, assignments={})
code, out, err = run_cli(
    ["approval", "--case", "case_x", "--row-key", "evidence", "--actor-user-id", "7"],  # preview mode
    authz_conn=conn_unassigned, mutation_conn_factory=_exploding_mutation_conn_factory,
)
check(
    "unassigned actor, PREVIEW mode -> exit 1, generic denial (case_scoped_review never reached)",
    code == cli_mutate.EXIT_DOMAIN_ERROR and err.strip() == cli_mutate._AUTHZ_DENIAL_MESSAGE,
)

conn_wrong_capability = FakeAuthzConn(users={7: (1, False)}, assignments={(7, "case_x"): "analyst"})
code, out, err = run_cli(
    ["approval", "--case", "case_x", "--row-key", "evidence", "--actor-user-id", "7", "--approve", "--expected-hash", "h"],
    authz_conn=conn_wrong_capability, mutation_conn_factory=_exploding_mutation_conn_factory,
)
check(
    "analyst (read-only) actor attempting --approve (mutate) -> exit 1, generic denial, "
    "ZERO mutation connection (facade's OWN outer authz check catches this before conn_factory())",
    code == cli_mutate.EXIT_DOMAIN_ERROR and err.strip() == cli_mutate._AUTHZ_DENIAL_MESSAGE,
)


# ============================================================
# 4) APPROVAL PREVIEW / APPLY - correct pass-through to
#    approval_registry, correct authz-vs-mutation connection separation.
# ============================================================

_ORIGINAL_CASE_SCOPED_REVIEW = _approval_registry.case_scoped_review
_ORIGINAL_CASE_SCOPED_APPROVE = _approval_registry.case_scoped_approve

_review_calls = []
_approve_calls = []


def _fake_case_scoped_review(row_key, case_id):
    _review_calls.append((row_key, case_id))
    return {
        "row": {"key": row_key}, "pending_path": "P", "pending_hash": "deadbeef" * 8,
        "validation": {"valid": True}, "analysis": {},
    }


def _fake_case_scoped_approve(row_key, case_id, expected_hash, *, principal, authz_repository, conn_factory):
    _approve_calls.append((row_key, case_id, expected_hash, principal.user_id, conn_factory))
    return {"row": {"key": row_key}, "canonical_path": "C", "canonical_hash": "cafebabe" * 8, "audit_path": "A", "stdout": ""}


_approval_registry.case_scoped_review = _fake_case_scoped_review
_approval_registry.case_scoped_approve = _fake_case_scoped_approve
try:
    # PREVIEW mode calls the REAL authorize_case_access() directly (this
    # dispatcher's OWN outer check, since case_scoped_review() itself
    # performs no authz) - its step 5 (paths.resolve_case_id()) needs a
    # REAL, filesystem-existing case_id, so "case_0001" is used here
    # specifically (read-only path existence check only - case_scoped_
    # review() itself is mocked, so nothing is ever read from it).
    conn_assigned_lawyer = FakeAuthzConn(users={7: (1, False)}, assignments={(7, "case_0001"): "lawyer"})
    code, out, err = run_cli(
        ["approval", "--case", "case_0001", "--row-key", "evidence", "--actor-user-id", "7"],  # preview
        authz_conn=conn_assigned_lawyer, mutation_conn_factory=_exploding_mutation_conn_factory,
    )
    check("approval preview: exit 0", code == cli_mutate.EXIT_OK)
    check("approval preview: case_scoped_review() was called exactly once with the resolved args", _review_calls == [("evidence", "case_0001")])
    check("approval preview: prints the pending_hash", "deadbeef" * 8 in out)
    check("approval preview: ZERO mutation connection was opened", True)  # exploding factory never raised

    def _capturing_mutation_conn_factory():
        return "SENTINEL_MUTATION_CONN"

    conn_assigned_lawyer2 = FakeAuthzConn(users={7: (1, False)}, assignments={(7, "case_x"): "lawyer"})
    code, out, err = run_cli(
        ["approval", "--case", "case_x", "--row-key", "evidence", "--actor-user-id", "7", "--approve", "--expected-hash", "deadbeef" * 8],
        authz_conn=conn_assigned_lawyer2, mutation_conn_factory=_capturing_mutation_conn_factory,
    )
    check("approval apply: exit 0", code == cli_mutate.EXIT_OK)
    check(
        "approval apply: case_scoped_approve() received the EXACT row_key/case_id/expected_hash/"
        "actor_user_id/conn_factory the dispatcher was given - a genuine pass-through, not a copy",
        _approve_calls[-1] == ("evidence", "case_x", "deadbeef" * 8, 7, _capturing_mutation_conn_factory),
    )
    check("approval apply: prints the canonical_hash", "cafebabe" * 8 in out)
finally:
    _approval_registry.case_scoped_review = _ORIGINAL_CASE_SCOPED_REVIEW
    _approval_registry.case_scoped_approve = _ORIGINAL_CASE_SCOPED_APPROVE


# ============================================================
# 5) REVIEW PREVIEW / APPLY - correct pass-through to review_registry,
#    reviewer_ref is ALWAYS LOCAL_CLI_REVIEWER_REF, NEVER a CLI argument.
# ============================================================

_ORIGINAL_GET_REVIEW_RECORD = _review_registry.get_review_record
_ORIGINAL_APPLY_TRANSITION = _review_registry.apply_transition

_get_record_calls = []
_apply_transition_calls = []


def _fake_get_review_record(review_kind, case_id, record_id):
    _get_record_calls.append((review_kind, case_id, record_id))
    return {"record": {}, "canonical_path": "C", "canonical_hash": "feedface" * 8}


def _fake_apply_transition(review_kind, case_id, record_id, target_state, review_note, expected_hash, *, principal, authz_repository, conn_factory, reviewer_ref):
    _apply_transition_calls.append(
        (review_kind, case_id, record_id, target_state, review_note, expected_hash, principal.user_id, reviewer_ref),
    )
    return {
        "canonical_path": "C", "audit_path": "A", "post_sha256": "0" * 64,
        "previous_state": "needs_review", "new_state": target_state,
    }


_review_registry.get_review_record = _fake_get_review_record
_review_registry.apply_transition = _fake_apply_transition
try:
    # Same reasoning as the approval preview block above - PREVIEW
    # mode's own outer authorize_case_access() needs a real case_id.
    conn_assigned_lawyer3 = FakeAuthzConn(users={7: (1, False)}, assignments={(7, "case_0001"): "lawyer"})
    code, out, err = run_cli(
        ["review", "--case", "case_0001", "--review-kind", "evidence.candidate", "--record-id", "ec_1", "--actor-user-id", "7"],
        authz_conn=conn_assigned_lawyer3, mutation_conn_factory=_exploding_mutation_conn_factory,
    )
    check("review preview: exit 0", code == cli_mutate.EXIT_OK)
    check(
        "review preview: get_review_record() was called exactly once with the resolved args",
        _get_record_calls == [("evidence.candidate", "case_0001", "ec_1")],
    )
    check("review preview: prints the canonical_hash", "feedface" * 8 in out)

    conn_assigned_lawyer4 = FakeAuthzConn(users={7: (1, False)}, assignments={(7, "case_x"): "lawyer"})
    code, out, err = run_cli(
        [
            "review", "--case", "case_x", "--review-kind", "evidence.candidate", "--record-id", "ec_1",
            "--actor-user-id", "7", "--apply", "--target-state", "confirmed", "--note", "gerçek not",
            "--expected-hash", "feedface" * 8,
        ],
        authz_conn=conn_assigned_lawyer4, mutation_conn_factory=lambda: "SENTINEL",
    )
    check("review apply: exit 0", code == cli_mutate.EXIT_OK)
    last_call = _apply_transition_calls[-1]
    check(
        "review apply: apply_transition() received the EXACT args the dispatcher was given",
        last_call[:7] == ("evidence.candidate", "case_x", "ec_1", "confirmed", "gerçek not", "feedface" * 8, 7),
    )
    check(
        "review apply: reviewer_ref is ALWAYS review_registry.LOCAL_CLI_REVIEWER_REF - "
        "there is NO CLI flag that could override this",
        last_call[7] == _review_registry.LOCAL_CLI_REVIEWER_REF,
    )
    check("--reviewer-ref/--channel/--action-family do not exist as flags at all", not hasattr(
        cli_mutate._build_arg_parser().parse_args(
            ["review", "--case", "x", "--review-kind", "evidence.candidate", "--record-id", "r", "--actor-user-id", "1"],
        ),
        "reviewer_ref",
    ))
finally:
    _review_registry.get_review_record = _ORIGINAL_GET_REVIEW_RECORD
    _review_registry.apply_transition = _ORIGINAL_APPLY_TRANSITION


# ============================================================
# 6) NO FORCE/BYPASS FLAG EXISTS ANYWHERE ON EITHER SUBPARSER.
# ============================================================

_approval_help = io.StringIO()
_parser = cli_mutate._build_arg_parser()
for _bad_flag in ("--force", "--bypass", "--unsafe", "--no-journal", "--skip-authz", "--i-understand-this-bypasses-the-coordinator"):
    code, out, err = run_cli_usage_only([
        "approval", "--case", "x", "--row-key", "evidence", "--actor-user-id", "1", _bad_flag,
    ])
    check(f"no such flag as {_bad_flag!r} on the approval subparser (usage error)", code == cli_mutate.EXIT_USAGE_ERROR)


# ============================================================
# 7) ROW 19C-3b SLICE 1 - LEGACY CLI MUTATION BYPASS REGRESSION
#    (persistent, real-subprocess). All 15 legacy `src/*.py` mutation
#    entry points must refuse via a genuine OS process exit code 2 and
#    the fixed Row 19C-3b refusal message - proven by actually spawning
#    each script as its own OS process with `subprocess.run()` (never
#    `shell=True`, never by calling its `main()` in-process, which would
#    only prove the Python-level SystemExit object, not the real OS exit
#    code a shell/orchestrator would observe). Every invocation uses
#    `sys.executable`, an explicit `cwd=REPO_ROOT`, and a bounded
#    timeout.
# ============================================================

_SRC_DIR = REPO_ROOT / "src"

_LEGACY_CLI_REFUSAL_MESSAGE = "HATA: Bu doğrudan CLI mutasyon yolu artık DEVRE DIŞIDIR (Row 19C-3b)."


def _snapshot_data_tree():
    """Real before/after byte snapshot of the ENTIRE `data/` tree (every
    file's own sha256, keyed by its path relative to `data/`) - a new,
    removed, or content-modified file ANYWHERE under `data/` (canonical,
    pending, audit, backup, or otherwise) changes this snapshot; it is
    never limited to case_0001's own known artefact files."""
    data_dir = REPO_ROOT / "data"
    snapshot = {}
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            snapshot[path.relative_to(data_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _run_legacy_script(module_name, args, *, timeout=90):
    """Real subprocess with an EXPLICIT, deterministic child environment -
    a full copy of the parent's own `os.environ` (so PostgreSQL DSN
    variables and everything else the child might need survive
    unchanged), with only `PYTHONIOENCODING=utf-8` added/overridden -
    the child's OWN stdout/stderr encoding is therefore pinned to UTF-8
    regardless of the PARENT process's ambient locale (cp1254 on this
    Turkish-locale machine); the parent's global `os.environ` itself is
    NEVER mutated (`os.environ.copy()` only, passed via `env=`).

    ROW 19C-3b SLICE 1 LEGACY SUBPROCESS ENCODING REMEDIATION: raw bytes
    are still captured (never `text=True` - `subprocess.run(text=True)`'s
    own internal reader threads would decode using the PARENT process's
    own locale-preferred encoding, ignoring `env=` entirely, which is
    exactly the non-determinism this fix closes another way), but they
    are now decoded STRICTLY (`errors="strict"`, the default - no
    `errors="replace"`): since the child is now guaranteed to emit valid
    UTF-8, a strict-decode failure is itself a genuine signal something
    is wrong, rather than silently substituting U+FFFD replacement
    characters that could quietly weaken the exact message-equality
    assertions below."""
    script_path = _SRC_DIR / f"{module_name}.py"
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=timeout,
        env=child_env,
    )
    stdout_text = completed.stdout.decode("utf-8") if completed.stdout else ""
    stderr_text = completed.stderr.decode("utf-8") if completed.stderr else ""
    result = types.SimpleNamespace(returncode=completed.returncode, stdout=stdout_text, stderr=stderr_text)
    return script_path, result


LEGACY_MUTATION_MATRIX = [
    # Layer A (10) - each module's OWN real `--approve` flag, taken
    # directly from its own argparse contract (verified by reading each
    # file's `main()` before writing this matrix).
    ("deadline_approval", ["--case", "case_0001", "--approve"]),
    ("issue_spotting_approval", ["--case", "case_0001", "--approve"]),
    ("legal_research_approval", ["--case", "case_0001", "--approve"]),
    ("case_law_approval", ["--case", "case_0001", "--approve"]),
    ("evidence_approval", ["--case", "case_0001", "--approve"]),
    ("argument_approval", ["--case", "case_0001", "--approve"]),
    ("risk_strategy_approval", ["--case", "case_0001", "--approve"]),
    ("drafting_approval", ["--case", "case_0001", "--approve"]),
    ("qa_approval", ["--case", "case_0001", "--approve"]),
    ("orchestrator_approval", ["--case", "case_0001", "--approve"]),
    # Layer B (5) - each module's OWN real mutation-flag combination.
    ("evidence_review", ["--case", "case_0001", "--confirm", "row19c3b_nonexistent_candidate_id"]),
    ("argument_review", [
        "--case", "case_0001", "--record-type", "claim",
        "--record-id", "row19c3b_nonexistent_claim_id", "--action", "confirm",
    ]),
    ("risk_strategy_review", [
        "--case", "case_0001", "--record-type", "risk",
        "--record-id", "row19c3b_nonexistent_risk_id", "--action", "confirm",
    ]),
    ("drafting_review", [
        "--case", "case_0001", "--record-type", "section",
        "--record-id", "row19c3b_nonexistent_section_id", "--action", "confirm",
    ]),
    ("qa_review", [
        "--case", "case_0001", "--suggestion-id", "row19c3b_nonexistent_suggestion_id",
        "--target-state", "accepted_for_follow_up",
    ]),
    # ROW 19C-3b SLICE 2 - the two fact/timeline canonical PROMOTION
    # bypasses (each module's OWN real --approve flag; timeline's
    # --pending is required by its own argparse contract, so a
    # nonexistent value is supplied - the refusal fires strictly BEFORE
    # any pending read, proven by returncode/stderr/stdout below).
    ("fact_approval", ["--approve"]),
    ("timeline_approval", ["--pending", "row19c3b_slice2_nonexistent.pending", "--approve"]),
]

check(
    "LEGACY_MUTATION_MATRIX covers all 17 legacy mutation entry points "
    "(10 Layer A + 5 Layer B + 2 promotion)",
    len(LEGACY_MUTATION_MATRIX) == 17,
)

# ROW 19C-3b SLICE 1 - EVIDENCE REVIEW FULL FLAG COVERAGE: `evidence_
# review.py` exposes FOUR independent public mutation flags (`--confirm`,
# `--reject`, `--accept-follow-up`, `--dismiss` - verified directly from
# its own argparse definitions), but LEGACY_MUTATION_MATRIX above only
# ever exercises `--confirm`. All four route to the SAME Row 19C-3b
# refusal branch (the mutation-flag dispatch happens strictly BEFORE
# that branch, so which flag was given never changes the outcome) - but
# "reaches the same branch" is not itself proof for the three flags never
# actually invoked, so this list exercises them for real, each as its
# own separate OS subprocess. This is 3 ADDITIONAL scenarios, not 3
# additional legacy MODULES - `evidence_review` itself contributes one
# entry to LEGACY_MUTATION_MATRIX above and three more here.
EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX = [
    ("evidence_review", ["--case", "case_0001", "--reject", "row19c3b_nonexistent_candidate_id_reject"]),
    ("evidence_review", ["--case", "case_0001", "--accept-follow-up", "row19c3b_nonexistent_suggestion_id_acceptfu"]),
    ("evidence_review", ["--case", "case_0001", "--dismiss", "row19c3b_nonexistent_suggestion_id_dismiss"]),
]
check(
    "EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX covers the 3 remaining evidence_review public mutation "
    "flags (--reject/--accept-follow-up/--dismiss) not already exercised by LEGACY_MUTATION_"
    "MATRIX's own --confirm invocation - all FOUR public evidence_review mutation flags are now "
    "each independently proven, even though all four route to the SAME Row 19C-3b refusal branch",
    len(EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX) == 3,
)
check(
    "LEGACY_MUTATION_MATRIX (17 legacy executables) + EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX (3 "
    "additional evidence_review flag variants) = 20 total refusal subprocess scenarios in this "
    "section - NOT 20 distinct legacy modules (evidence_review itself contributes 4 of the 20: "
    "one entry from each list)",
    len(LEGACY_MUTATION_MATRIX) + len(EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX) == 20,
)

_data_snapshot_before_matrix = _snapshot_data_tree()

for _module_name, _mutation_args in LEGACY_MUTATION_MATRIX + EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX:
    _script_path, _result = _run_legacy_script(_module_name, _mutation_args)
    check(
        f"{_module_name}: the real script file exists on disk and is the one actually invoked "
        f"({_script_path})",
        _script_path.is_file(),
        f"resolved path: {_script_path}",
    )
    check(
        f"{_module_name}: real OS subprocess returncode is exactly 2 (the genuine process exit "
        "code SystemExit(2) produces, not merely main()'s Python-level return value)",
        _result.returncode == 2,
        f"got returncode={_result.returncode!r} stdout={_result.stdout!r} stderr={_result.stderr!r}",
    )
    check(
        f"{_module_name}: the fixed Row 19C-3b refusal message appears in stderr",
        _LEGACY_CLI_REFUSAL_MESSAGE in _result.stderr,
        f"stderr={_result.stderr!r}",
    )
    check(
        f"{_module_name}: stderr contains no 'Traceback' - this is a clean, deliberate "
        "SystemExit(2), never an unhandled exception escaping",
        "Traceback" not in _result.stderr,
        f"stderr={_result.stderr!r}",
    )
    check(
        f"{_module_name}: stdout is completely empty - no unexpected domain-writer success "
        "output (the refusal print goes to stderr only, and fires before any writer/success "
        "banner could ever print)",
        _result.stdout == "",
        f"stdout={_result.stdout!r}",
    )

_data_snapshot_after_matrix = _snapshot_data_tree()
check(
    "all 20 legacy mutation bypass scenarios together (17 legacy executables + 3 additional "
    "evidence_review flag variants): the REAL data/ tree is byte-for-byte UNCHANGED (before/after "
    "sha256 snapshot of every file under data/ - would catch a new, removed, or modified "
    "canonical/pending/audit/backup file anywhere, not only in case_0001's own tree)",
    _data_snapshot_before_matrix == _data_snapshot_after_matrix,
    f"changed/added/removed keys: "
    f"{sorted(set(_data_snapshot_before_matrix) ^ set(_data_snapshot_after_matrix))}",
)


# ============================================================
# 8) ROW 19C-3b SLICE 1 - LEGACY CLI NON-MUTATION PATHS (persistent,
#    real-subprocess). Pins down ACTUAL, already-observed behavior only
#    - production code is never touched to make an assertion pass.
# ============================================================

SELF_TEST_MODULES = [
    "evidence_approval", "argument_approval", "risk_strategy_approval",
    "drafting_approval", "qa_approval", "orchestrator_approval",
    "evidence_review", "argument_review", "risk_strategy_review",
    "drafting_review", "qa_review",
]
check("SELF_TEST_MODULES covers exactly the 11 modules with --self-test support", len(SELF_TEST_MODULES) == 11)

NO_SELF_TEST_MODULES = [
    "deadline_approval", "issue_spotting_approval", "legal_research_approval", "case_law_approval",
]
check("NO_SELF_TEST_MODULES covers exactly the 4 modules without --self-test", len(NO_SELF_TEST_MODULES) == 4)

_data_snapshot_before_nonmutation = _snapshot_data_tree()

for _module_name in SELF_TEST_MODULES:
    _script_path, _result = _run_legacy_script(_module_name, ["--self-test"], timeout=120)
    check(
        f"{_module_name} --self-test: real OS subprocess exit code 0",
        _result.returncode == 0,
        f"got returncode={_result.returncode!r} stdout(tail)={_result.stdout[-400:]!r} "
        f"stderr={_result.stderr!r}",
    )

for _module_name in NO_SELF_TEST_MODULES:
    _script_path, _result = _run_legacy_script(_module_name, ["--case", "case_0001"])
    check(
        f"{_module_name}: no-flag read-only preview path -> real OS subprocess exit code 0",
        _result.returncode == 0,
        f"got returncode={_result.returncode!r} stdout(tail)={_result.stdout[-400:]!r} "
        f"stderr={_result.stderr!r}",
    )

# evidence_review / argument_review preview paths (no mutation flags at all).
_script_path, _result = _run_legacy_script("evidence_review", ["--case", "case_0001"])
check(
    "evidence_review: no mutation flags -> run_review_report() preview path -> exit 0",
    _result.returncode == 0,
    f"got returncode={_result.returncode!r} stderr={_result.stderr!r}",
)
_script_path, _result = _run_legacy_script("argument_review", ["--case", "case_0001"])
check(
    "argument_review: no mutation flags -> run_review_report() preview path -> exit 0",
    _result.returncode == 0,
    f"got returncode={_result.returncode!r} stderr={_result.stderr!r}",
)

# risk_strategy_review / drafting_review existing usage-message path -
# exact literal copied from each file's own `print(...)` call.
_USAGE_MESSAGE = "Kullanım: --record-type --record-id --action [--reviewer] [--note]"
_script_path, _result = _run_legacy_script("risk_strategy_review", ["--case", "case_0001"])
check(
    "risk_strategy_review: missing --record-type/--record-id/--action -> existing usage-message "
    "path (exit 0, NOT the Row 19C-3b refusal - this path never reaches the mutation branch at "
    "all)",
    _result.returncode == 0
    and _USAGE_MESSAGE in _result.stdout
    and _LEGACY_CLI_REFUSAL_MESSAGE not in _result.stdout,
    f"got returncode={_result.returncode!r} stdout={_result.stdout!r}",
)
_script_path, _result = _run_legacy_script("drafting_review", ["--case", "case_0001"])
check(
    "drafting_review: missing --record-type/--record-id/--action -> existing usage-message path "
    "(exit 0, NOT the Row 19C-3b refusal - this path never reaches the mutation branch at all)",
    _result.returncode == 0
    and _USAGE_MESSAGE in _result.stdout
    and _LEGACY_CLI_REFUSAL_MESSAGE not in _result.stdout,
    f"got returncode={_result.returncode!r} stdout={_result.stdout!r}",
)

# ROW 19C-3b SLICE 2 - fact/timeline PREVIEW paths are PRESERVED
# (read-only, exit 0, NOT the refusal): fact's default no-flag review
# mode, fact's explicit --pending review against the real v1_3 pending,
# and timeline's --pending review against the real v1_1 pending. All
# three read the REAL case_0001 data strictly read-only (the section's
# own data/ byte-invariance check below covers them).
_script_path, _result = _run_legacy_script("fact_approval", [], timeout=120)
check(
    "fact_approval: no-flag read-only preview path preserved -> exit 0, READY banner, no refusal",
    _result.returncode == 0 and "FACT APPROVAL V1: READY" in _result.stdout
    and _LEGACY_CLI_REFUSAL_MESSAGE not in _result.stderr,
    f"got returncode={_result.returncode!r} stdout(tail)={_result.stdout[-300:]!r} stderr={_result.stderr!r}",
)
_script_path, _result = _run_legacy_script(
    "fact_approval",
    ["--pending", "data/cases/case_0001/documents/dava_dilekcesi_001/extractions/facts_llm_v1_3.json.pending"],
    timeout=120,
)
check(
    "fact_approval: explicit --pending (current v1_3) preview preserved -> exit 0, READY",
    _result.returncode == 0 and "FACT APPROVAL V1: READY" in _result.stdout,
    f"got returncode={_result.returncode!r} stdout(tail)={_result.stdout[-300:]!r} stderr={_result.stderr!r}",
)
_script_path, _result = _run_legacy_script(
    "timeline_approval",
    ["--pending", "data/cases/case_0001/timeline/timeline_v1_1.json.pending"],
    timeout=180,
)
check(
    "timeline_approval: --pending preview preserved -> exit 0, READY, no refusal",
    _result.returncode == 0 and "TIMELINE APPROVAL V1: READY" in _result.stdout
    and _LEGACY_CLI_REFUSAL_MESSAGE not in _result.stderr,
    f"got returncode={_result.returncode!r} stdout(tail)={_result.stdout[-300:]!r} stderr={_result.stderr!r}",
)

# qa_review's OLD missing-required-argument SystemExit, distinct from the NEW Row 19C-3b refusal.
_script_path, _result = _run_legacy_script("qa_review", ["--case", "case_0001"])
check(
    "qa_review: missing --suggestion-id/--target-state -> the OLD 'zorunludur' SystemExit "
    "(exit 1), NEVER confused with the NEW Row 19C-3b refusal (exit 2) - different code, "
    "different message, reached via a completely different, earlier guard in main()",
    _result.returncode == 1
    and "zorunludur" in _result.stderr
    and _LEGACY_CLI_REFUSAL_MESSAGE not in _result.stderr
    and "Traceback" not in _result.stderr,
    f"got returncode={_result.returncode!r} stderr={_result.stderr!r}",
)

_data_snapshot_after_nonmutation = _snapshot_data_tree()
check(
    "all non-mutation legacy CLI paths together: the REAL data/ tree is byte-for-byte UNCHANGED",
    _data_snapshot_before_nonmutation == _data_snapshot_after_nonmutation,
    f"changed/added/removed keys: "
    f"{sorted(set(_data_snapshot_before_nonmutation) ^ set(_data_snapshot_after_nonmutation))}",
)


print(f"--- test_cli_mutate_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
