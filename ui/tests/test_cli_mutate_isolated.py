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

import ast
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
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

# FACT VERIFICATION WORKFLOW - `verification` subcommand usage-shape
# grammar. Every rule fires BEFORE any connection/authz repository/
# filesystem probe/journal access (the exploding factories prove zero
# connections). Mirrors the `promotion` block above exactly in style.
code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1",
    "--target-state", "verified",
])
check(
    "verification: --target-state given WITHOUT --apply -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--target-state" in err,
)

code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1",
    "--evidence-ref", "doc1",
])
check(
    "verification: --evidence-ref given WITHOUT --apply -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--evidence-ref" in err,
)

code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1",
    "--expected-hash", "h",
])
check(
    "verification: --expected-hash given WITHOUT --apply -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--expected-hash" in err,
)

code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1",
    "--attempt", "2",
])
check(
    "verification: non-default --attempt given WITHOUT --apply -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--attempt" in err,
)

code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1", "--apply",
])
check(
    "verification: --apply WITHOUT --target-state -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--target-state" in err,
)

code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1",
    "--apply", "--target-state", "unverified",
])
check(
    "verification: --apply WITHOUT --expected-hash -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--expected-hash" in err,
)

code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1",
    "--apply", "--target-state", "verified", "--expected-hash", "h",
])
check(
    "verification: --target-state verified WITHOUT --evidence-ref -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--evidence-ref" in err,
)

code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1",
    "--apply", "--target-state", "partially_verified", "--expected-hash", "h",
])
check(
    "verification: --target-state partially_verified WITHOUT --evidence-ref -> exit 2, "
    "zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--evidence-ref" in err,
)

code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1",
    "--apply", "--target-state", "verified", "--expected-hash", "h", "--evidence-ref", "doc1",
    "--attempt", "0",
])
check(
    "verification: --attempt 0 -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--attempt" in err,
)

code, _, err = run_cli_usage_only([
    "verification", "--case", "x", "--document", "d", "--fact-id", "f", "--actor-user-id", "1",
    "--apply", "--target-state", "not_a_real_state", "--expected-hash", "h",
])
check(
    "verification: invalid --target-state -> exit 2 (argparse choices), zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR,
)

# ROW 19C-3c-i - `generation` subcommand usage-shape grammar. Every rule
# fires BEFORE any connection/authz repository/filesystem probe/journal
# access (the exploding factories prove zero connections). Mirrors the
# `promotion` block above exactly in style/coverage discipline.
code, _, err = run_cli_usage_only(["generation", "--case", "x", "--row-key", "bogus", "--actor-user-id", "1"])
check("generation: invalid --row-key -> exit 2, zero connections", code == cli_mutate.EXIT_USAGE_ERROR)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "timeline", "--actor-user-id", "1", "--anchor", "timeline_event_001",
])
check(
    "generation: --anchor with --row-key timeline -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--anchor" in err,
)

# PILOT READINESS ADIM 5 (bağımsız inceleme §3.4): `--holiday`/
# `--calendar-complete` argparse'tan TAMAMEN KALDIRILDI. Bu iki bayrak
# artık HİÇBİR row-key için argparse tarafından TANINMAZ - eski
# assertion'lar ("--holiday" in err) argparse'ın "unrecognized
# arguments" reddiyle de tesadüfen geçmeye devam ederdi (tautolojiye
# kayan bir kanıt zinciri olurdu); bu yüzden BİLİNÇLİ olarak
# "unrecognized arguments" ifadesini DOĞRUDAN doğrulayacak şekilde
# yeniden hedeflendi - artık aile-bazlı bir iş kuralı reddi DEĞİL,
# argparse'ın kendi bilinmeyen-bayrak reddi test ediliyor.
code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "timeline", "--actor-user-id", "1", "--holiday", "2026-01-01",
])
check(
    "generation: --holiday no longer exists AT ALL (any row-key) -> argparse 'unrecognized "
    "arguments' exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "unrecognized arguments" in err and "--holiday" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "timeline", "--actor-user-id", "1", "--calendar-complete",
])
check(
    "generation: --calendar-complete no longer exists AT ALL (any row-key) -> argparse "
    "'unrecognized arguments' exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "unrecognized arguments" in err and "--calendar-complete" in err,
)

# POSITIVE-TO-NEGATIVE FLIP: before this slice, `--row-key deadline
# --apply --holiday ...`/`--calendar-complete` were ACCEPTED (deadline
# was the one row-key that used them). Proving the SAME flags are now
# rejected even for `--row-key deadline` demonstrates the flag is
# genuinely gone SYSTEM-WIDE, not merely re-routed to a different
# rejection branch for the other five row-keys.
code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "deadline", "--anchor", "timeline_event_001",
    "--actor-user-id", "1", "--apply", "--expected-input-digest", "h", "--holiday", "2026-01-01",
])
check(
    "generation: --holiday with --row-key deadline (the ONE row-key that used to ACCEPT it) -> "
    "argparse 'unrecognized arguments' exit 2, zero connections (system-wide removal proof)",
    code == cli_mutate.EXIT_USAGE_ERROR and "unrecognized arguments" in err and "--holiday" in err,
)
code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "deadline", "--anchor", "timeline_event_001",
    "--actor-user-id", "1", "--apply", "--expected-input-digest", "h", "--calendar-complete",
])
check(
    "generation: --calendar-complete with --row-key deadline (the ONE row-key that used to "
    "ACCEPT it) -> argparse 'unrecognized arguments' exit 2, zero connections (system-wide "
    "removal proof)",
    code == cli_mutate.EXIT_USAGE_ERROR and "unrecognized arguments" in err and "--calendar-complete" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "timeline", "--actor-user-id", "1",
    "--judicial-recess-applicable", "yes",
])
check(
    "generation: non-default --judicial-recess-applicable with --row-key timeline -> exit 2, "
    "zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--judicial-recess-applicable" in err,
)

# ============================================================
# PILOT READINESS ADIM 7 / SLICE 1 - STOPPING-EVENT CLI CONTRACT
#
# Iki yeni bayrak YALNIZ `--row-key deadline` + `--apply` icindir. Her
# red HERHANGI bir dosya/baglanti/authz/mutation I/O sundan ONCE olur:
# `run_cli_usage_only` hem authz hem mutation connection factory sini
# PATLAYAN bir fonksiyonla besler, yani sifir-I/O mekanik olarak
# kanitlanir.
# ============================================================

_STOPEV_DEADLINE_APPLY = [
    "generation", "--case", "x", "--row-key", "deadline",
    "--anchor", "timeline_event_001", "--actor-user-id", "1",
    "--apply", "--expected-input-digest", "h",
]

code, _, err = run_cli_usage_only(
    _STOPEV_DEADLINE_APPLY + ["--stopping-event-status", "bogus"]
)
check(
    "SLICE 1: taninmayan --stopping-event-status -> argparse exit 2, zero "
    "connections (I/O oncesi)",
    code == cli_mutate.EXIT_USAGE_ERROR
    and "--stopping-event-status" in err
    and "invalid choice" in err,
    err.strip()[:160],
)

for _value in ("none", "present", "unknown"):
    # KABUL kaniti: usage-shape GECERSE CLI authz baglantisini acmaya
    # calisir ve patlayan factory AssertionError firlatir. Yani
    # AssertionError = "usage-shape bu bayragi KABUL etti"; usage
    # hatasi olsaydi exit 2 ile SIFIR baglanti acilirdi.
    try:
        run_cli_usage_only(
            _STOPEV_DEADLINE_APPLY + ["--stopping-event-status", _value]
        )
    except AssertionError:
        _accepted = True
        _detail = "authz factory cagrildi -> usage-shape gecti"
    else:
        _accepted = False
        _detail = "usage-shape reddetti (beklenmiyordu)"
    check(
        "SLICE 1: --stopping-event-status=%s deadline-apply icin usage-shape "
        "seviyesinde KABUL edilir" % _value,
        _accepted,
        _detail,
    )

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "deadline",
    "--anchor", "timeline_event_001", "--actor-user-id", "1",
    "--stopping-event-status", "none",
])
check(
    "SLICE 1: --stopping-event-status PREVIEW da (apply yok) reddedilir -> "
    "exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "apply-only" in err,
    err.strip()[:160],
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "deadline",
    "--anchor", "timeline_event_001", "--actor-user-id", "1",
    "--stopping-event-attestation-ref", "AV-1",
])
check(
    "SLICE 1: --stopping-event-attestation-ref PREVIEW da reddedilir -> "
    "exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "apply-only" in err,
    err.strip()[:160],
)

_STOPEV_OTHER_ROWS = [
    ("timeline", []),
    ("issue_spotting", []),
    ("evidence", []),
    ("argument", []),
    ("risk_strategy", []),
    ("drafting", []),
    ("legal_research", []),
    ("case_law", []),
    ("qa", []),
    ("case_view", []),
    ("fact_extraction", ["--document", "doc_001"]),
]
for _row, _extra in _STOPEV_OTHER_ROWS:
    code, _, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _row, "--actor-user-id", "1",
    ] + _extra + ["--stopping-event-status", "none"])
    check(
        "SLICE 1: --stopping-event-status --row-key %s icin REDDEDILIR -> "
        "exit 2, zero connections" % _row,
        code == cli_mutate.EXIT_USAGE_ERROR and "--stopping-event-status" in err,
        err.strip()[:160],
    )
    code, _, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _row, "--actor-user-id", "1",
    ] + _extra + ["--stopping-event-attestation-ref", "AV-1"])
    check(
        "SLICE 1: --stopping-event-attestation-ref --row-key %s icin "
        "REDDEDILIR -> exit 2, zero connections" % _row,
        code == cli_mutate.EXIT_USAGE_ERROR
        and "--stopping-event-attestation-ref" in err,
        err.strip()[:160],
    )


# ============================================================
# ADIM 7 / SLICE 2 - --attempt CLI CONTRACT
#
# fact_verification emsaliyle BIREBIR: default 1, int, >= 1,
# deadline-only, apply-only. Her red HERHANGI bir dosya/baglanti/
# authz/mutation I/O sundan ONCE olur (`run_cli_usage_only` patlayan
# factory'lerle besler -> sifir-I/O mekanik olarak kanitlanir).
# ============================================================

for _bad, _why in (("0", "sifir"), ("-1", "negatif")):
    code, _, err = run_cli_usage_only(
        _STOPEV_DEADLINE_APPLY + ["--attempt", _bad]
    )
    check(
        "SLICE 2: --attempt=%s (%s) -> exit 2, zero connections" % (_bad, _why),
        code == cli_mutate.EXIT_USAGE_ERROR and "--attempt" in err,
        err.strip()[:160],
    )

code, _, err = run_cli_usage_only(_STOPEV_DEADLINE_APPLY + ["--attempt", "abc"])
check(
    "SLICE 2: --attempt=abc (non-integer) -> argparse exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--attempt" in err,
    err.strip()[:160],
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "deadline",
    "--anchor", "timeline_event_001", "--actor-user-id", "1",
    "--attempt", "2",
])
check(
    "SLICE 2: --attempt PREVIEW da (apply yok) reddedilir -> exit 2, "
    "zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--apply" in err,
    err.strip()[:160],
)

for _row, _extra in _STOPEV_OTHER_ROWS:
    code, _, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _row, "--actor-user-id", "1",
    ] + _extra + ["--attempt", "2"])
    check(
        "SLICE 2: --attempt --row-key %s icin REDDEDILIR -> exit 2, "
        "zero connections" % _row,
        code == cli_mutate.EXIT_USAGE_ERROR and "--attempt" in err,
        err.strip()[:160],
    )

# KABUL kaniti: default (1) ve acik bir gecerli deger usage-shape'i
# GECER -> patlayan authz factory AssertionError firlatir.
for _argv, _label in (
    (_STOPEV_DEADLINE_APPLY, "default (--attempt verilmedi)"),
    (_STOPEV_DEADLINE_APPLY + ["--attempt", "1"], "--attempt=1"),
    (_STOPEV_DEADLINE_APPLY + ["--attempt", "2"], "--attempt=2"),
):
    try:
        run_cli_usage_only(_argv)
    except AssertionError:
        _accepted = True
    else:
        _accepted = False
    check(
        "SLICE 2: %s deadline-apply icin usage-shape seviyesinde KABUL edilir"
        % _label,
        _accepted,
    )


code, _, err = run_cli_usage_only(["generation", "--case", "x", "--row-key", "deadline", "--actor-user-id", "1"])
check(
    "generation: --row-key deadline WITHOUT --anchor -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--anchor" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "deadline", "--anchor", "timeline_event_001",
    "--actor-user-id", "1", "--apply",
])
check(
    "generation: --apply WITHOUT --expected-input-digest -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--expected-input-digest" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "deadline", "--anchor", "timeline_event_001",
    "--actor-user-id", "1", "--expected-input-digest", "h",
])
check(
    "generation: --expected-input-digest WITHOUT --apply -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--expected-input-digest" in err,
)

# ROW 19C-3c-iii - `generation --row-key fact_extraction` usage-shape
# grammar. Every rule fires BEFORE any connection/authz repository/
# filesystem probe/journal access (mirrors the deadline/timeline/agent-
# five blocks above exactly in style/coverage discipline). This family
# is STRICTER than the other five agent-generation row-keys: --with-
# agent is REQUIRED on BOTH preview and apply (no deterministic mode),
# and --allow-network is REJECTED on preview entirely (not merely
# optional-without-with-agent as for the other five).

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "fact_extraction", "--actor-user-id", "1",
])
check(
    "generation: --row-key fact_extraction WITHOUT --document -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "fact_extraction", "--document", "d",
    "--actor-user-id", "1",
])
check(
    "generation: --row-key fact_extraction WITHOUT --with-agent (preview) -> exit 2, zero "
    "connections (this family has no deterministic mode)",
    code == cli_mutate.EXIT_USAGE_ERROR and "--with-agent" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "fact_extraction", "--document", "d",
    "--with-agent", "--allow-network", "--actor-user-id", "1",
])
check(
    "generation: --row-key fact_extraction --allow-network on PREVIEW (no --apply) -> exit 2, "
    "zero connections (STRICTER than the other five agent-generation row-keys)",
    code == cli_mutate.EXIT_USAGE_ERROR and "--allow-network" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "fact_extraction", "--document", "d",
    "--with-agent", "--actor-user-id", "1", "--apply", "--expected-input-digest", "h",
])
check(
    "generation: --row-key fact_extraction --apply WITHOUT --allow-network -> exit 2, zero "
    "connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--allow-network" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "fact_extraction", "--document", "d",
    "--allow-network", "--actor-user-id", "1", "--apply", "--expected-input-digest", "h",
])
check(
    "generation: --row-key fact_extraction --apply WITHOUT --with-agent -> exit 2, zero "
    "connections (--with-agent checked before the apply-specific --allow-network rule)",
    code == cli_mutate.EXIT_USAGE_ERROR and "--with-agent" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "fact_extraction", "--document", "d",
    "--with-agent", "--anchor", "timeline_event_001", "--actor-user-id", "1",
])
check(
    "generation: --anchor is not accepted for --row-key fact_extraction -> exit 2, zero "
    "connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--anchor" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "fact_extraction", "--document", "d",
    "--with-agent", "--holiday", "2026-01-01", "--actor-user-id", "1",
])
check(
    "generation: --holiday no longer exists AT ALL (--row-key fact_extraction) -> argparse "
    "'unrecognized arguments' exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "unrecognized arguments" in err and "--holiday" in err,
)

# --document is REJECTED for every OTHER row-key (agent-five, timeline,
# deadline) - proven for one representative of each group; the fact_
# extraction-only requirement above proves the positive case.
code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "issue_spotting", "--document", "d",
    "--actor-user-id", "1",
])
check(
    "generation: --document is not accepted for --row-key issue_spotting (agent-five) -> exit 2, "
    "zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "timeline", "--document", "d", "--actor-user-id", "1",
])
check(
    "generation: --document is not accepted for --row-key timeline -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "deadline", "--anchor", "timeline_event_001",
    "--document", "d", "--actor-user-id", "1",
])
check(
    "generation: --document is not accepted for --row-key deadline -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "fact_extraction", "--actor-user-id", "1",
])
check(
    "generation: fact_extraction choice is genuinely present in --row-key's choices (invalid "
    "combination above still reports --document, never 'invalid choice')",
    "invalid choice" not in err,
)

# ROW 19C-3c-iv SLICE 1 - `generation --row-key legal_research`/
# `--row-key case_law` usage-shape grammar. This family's network gate
# mirrors the agent-five group's rules exactly (--allow-network requires
# --with-agent; both optional on preview and apply - NOT fact_
# extraction's stricter unconditional --with-agent requirement, since
# this family HAS a deterministic mode). --document/--anchor/--holiday/
# --calendar-complete/non-default --judicial-recess-applicable are all
# REJECTED for both row-keys (mirrors the agent-five/timeline pattern).

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "legal_research", "--document", "d",
    "--actor-user-id", "1",
])
check(
    "generation: --document is not accepted for --row-key legal_research -> exit 2, zero "
    "connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "case_law", "--document", "d",
    "--actor-user-id", "1",
])
check(
    "generation: --document is not accepted for --row-key case_law -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "legal_research", "--anchor", "timeline_event_001",
    "--actor-user-id", "1",
])
check(
    "generation: --anchor is not accepted for --row-key legal_research -> exit 2, zero "
    "connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--anchor" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "case_law", "--holiday", "2026-01-01",
    "--actor-user-id", "1",
])
check(
    "generation: --holiday no longer exists AT ALL (--row-key case_law) -> argparse "
    "'unrecognized arguments' exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "unrecognized arguments" in err and "--holiday" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "legal_research", "--calendar-complete",
    "--actor-user-id", "1",
])
check(
    "generation: --calendar-complete no longer exists AT ALL (--row-key legal_research) -> "
    "argparse 'unrecognized arguments' exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "unrecognized arguments" in err and "--calendar-complete" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "case_law", "--judicial-recess-applicable", "yes",
    "--actor-user-id", "1",
])
check(
    "generation: non-default --judicial-recess-applicable is not accepted for --row-key "
    "case_law -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--judicial-recess-applicable" in err,
)

# ============================================================
# PILOT READINESS ADIM 4a - `--mask-term` lives on the SHARED
# `generation` subparser, so every OTHER row-key must reject it
# explicitly, BEFORE any authz/DB/filesystem access (the repo's
# established `--document`/`--anchor`/`--holiday` pattern).
# ============================================================

for _mt_row_key, _mt_extra, _mt_label in [
    ("issue_spotting", [], "agent-five branch"),
    ("timeline", [], "timeline branch"),
    ("legal_research", [], "legal_research/case_law branch"),
    ("case_law", [], "legal_research/case_law branch (second row-key)"),
    ("qa", [], "PHASE B qa/case_view branch"),
    ("case_view", [], "PHASE B qa/case_view branch (second row-key)"),
    ("deadline", ["--anchor", "timeline_event_001"], "deadline else-branch"),
]:
    code, out, err = run_cli_usage_only(
        ["generation", "--case", "x", "--row-key", _mt_row_key]
        + _mt_extra
        + ["--mask-term", "Bir Ad", "--actor-user-id", "1"]
    )
    check(
        f"ADIM 4a: --mask-term is not accepted for --row-key {_mt_row_key} ({_mt_label}) "
        "-> exit 2, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and "--mask-term" in err,
        f"code={code} err={err!r}",
    )
    check(
        f"ADIM 4a: the --mask-term rejection for --row-key {_mt_row_key} prints nothing on "
        "stdout (usage errors go to stderr only)",
        out == "",
        f"out={out!r}",
    )

# CONTROL: the same deadline invocation WITHOUT --mask-term reaches a
# LATER usage rule (--apply requires --expected-input-digest), proving
# the new --mask-term guard is narrow and did not fire.
code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "deadline", "--anchor", "e1",
    "--actor-user-id", "1", "--apply",
])
check(
    "ADIM 4a CONTROL: without --mask-term, the same deadline invocation falls through to the "
    "LATER --expected-input-digest rule - the new guard is narrow, not a blanket refusal",
    code == cli_mutate.EXIT_USAGE_ERROR
    and "--expected-input-digest" in err and "--mask-term" not in err,
    f"code={code} err={err!r}",
)

# fact_extraction ACCEPTS --mask-term: the invocation gets past every
# usage-shape guard and fails only at the LATER --expected-input-digest
# rule, i.e. --mask-term itself was never rejected.
code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "fact_extraction", "--document", "d",
    "--with-agent", "--allow-network", "--mask-term", "Bir Ad", "--mask-term", "Başka Ad",
    "--actor-user-id", "1", "--apply",
])
check(
    "ADIM 4a: --mask-term IS accepted (repeatably) for --row-key fact_extraction - the "
    "invocation passes every usage-shape guard and is stopped only by the LATER "
    "--expected-input-digest rule, with zero connections opened",
    code == cli_mutate.EXIT_USAGE_ERROR
    and "--expected-input-digest" in err and "--mask-term" not in err,
    f"code={code} err={err!r}",
)

# ============================================================
# PHASE B (Commit A) - `generation --row-key qa` / `--row-key case_view`
# usage-shape grammar. These are the first OFFICIAL Row 16/17 pending
# publishers and they are DETERMINISTIC-ONLY: every deadline-only /
# fact_extraction-only flag is rejected exactly like the timeline branch,
# AND --with-agent / --allow-network are REJECTED unconditionally
# (preview AND apply) with the facade's OWN fixed message - the pilot
# `--with-agent` universe (8 families, test_rag_pilot_egress_gate_
# isolated) is NOT widened by this slice. Every rejection: exit 2, ZERO
# connections (the exploding factories prove no authz/DB access).
# ============================================================
from ui.services import qa_case_view_generation_mutation_facade as _qcvf  # noqa: E402

check(
    "PHASE B: the qa/case_view facade exposes EXACTLY {'qa', 'case_view'} as row-keys",
    set(_qcvf.QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME) == {"qa", "case_view"},
    f"got {sorted(_qcvf.QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME)}",
)
check(
    "PHASE B: neither qa nor case_view appears in ANY of the three --with-agent-capable "
    "facades' row-key namespaces (egress universe NOT widened)",
    not (
        {"qa", "case_view"}
        & (
            set(cli_mutate._agent_generation_row_keys())
            | set(cli_mutate._fact_extraction_row_keys())
            | set(cli_mutate._legal_research_case_law_row_keys())
        )
    ),
)

for _pb_row_key in ("qa", "case_view"):
    _pb_base = ["generation", "--case", "x", "--row-key", _pb_row_key, "--actor-user-id", "1"]

    code, out, err = run_cli_usage_only(_pb_base + ["--with-agent"])
    check(
        f"PHASE B: --with-agent with --row-key {_pb_row_key} (preview) -> exit 2, the facade's OWN "
        "fixed refusal text, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR
        and err.strip() == _qcvf.agent_mode_refusal_message(_pb_row_key) and out == "",
        f"code={code} out={out!r} err={err!r}",
    )
    code, out, err = run_cli_usage_only(
        _pb_base + ["--with-agent", "--allow-network", "--apply", "--expected-input-digest", "d"]
    )
    check(
        f"PHASE B: --with-agent --allow-network with --row-key {_pb_row_key} (apply) -> exit 2, "
        "same fixed refusal text, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR
        and err.strip() == _qcvf.agent_mode_refusal_message(_pb_row_key) and out == "",
        f"code={code} out={out!r} err={err!r}",
    )
    code, out, err = run_cli_usage_only(_pb_base + ["--allow-network"])
    check(
        f"PHASE B: --allow-network ALONE with --row-key {_pb_row_key} -> exit 2, same fixed "
        "refusal text (no 'requires --with-agent' hint - there is no agent mode to require), "
        "zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR
        and err.strip() == _qcvf.agent_mode_refusal_message(_pb_row_key) and out == "",
        f"code={code} out={out!r} err={err!r}",
    )
    code, out, err = run_cli_usage_only(_pb_base + ["--document", "d"])
    check(
        f"PHASE B: --document is not accepted for --row-key {_pb_row_key} -> exit 2, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err and out == "",
        f"code={code} err={err!r}",
    )
    code, out, err = run_cli_usage_only(_pb_base + ["--anchor", "timeline_event_001"])
    check(
        f"PHASE B: --anchor is not accepted for --row-key {_pb_row_key} -> exit 2, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and "--anchor" in err and out == "",
        f"code={code} err={err!r}",
    )
    code, out, err = run_cli_usage_only(_pb_base + ["--judicial-recess-applicable", "yes"])
    check(
        f"PHASE B: non-default --judicial-recess-applicable is not accepted for --row-key "
        f"{_pb_row_key} -> exit 2, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and "--judicial-recess-applicable" in err and out == "",
        f"code={code} err={err!r}",
    )
    code, out, err = run_cli_usage_only(_pb_base + ["--apply"])
    check(
        f"PHASE B CONTROL: a flag-clean --row-key {_pb_row_key} --apply passes EVERY family guard "
        "and is stopped only by the LATER --expected-input-digest rule (zero connections) - the "
        "new branch is narrow, not a blanket refusal, and never falls through into the deadline "
        "'requires --anchor' rule",
        code == cli_mutate.EXIT_USAGE_ERROR
        and "--expected-input-digest" in err and "--anchor" not in err and out == "",
        f"code={code} err={err!r}",
    )
    code, out, err = run_cli_usage_only(_pb_base + ["--expected-input-digest", "d"])
    check(
        f"PHASE B: --expected-input-digest without --apply for --row-key {_pb_row_key} -> exit 2, "
        "zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and "--expected-input-digest" in err and out == "",
        f"code={code} err={err!r}",
    )

_generation_actions = {}
for _sub_action in cli_mutate._build_arg_parser()._subparsers._group_actions[0].choices[
    "generation"
]._actions:
    for _opt in _sub_action.option_strings:
        _generation_actions[_opt] = _sub_action
_mask_term_action = _generation_actions.get("--mask-term")
check(
    "ADIM 4a: --mask-term is declared on the SHARED generation subparser with action='append', "
    "so it is genuinely repeatable and defaults to an empty list",
    _mask_term_action is not None
    and _mask_term_action.__class__.__name__ == "_AppendAction"
    and _mask_term_action.default == []
    and _mask_term_action.dest == "mask_term",
    f"{_mask_term_action!r}",
)

# ---- the suggested apply command must ECHO the given --mask-term list ----
# The canonical digest of that list is part of input_digest, so a
# copy-pasted apply command that dropped the terms would fail
# fail-closed with an --expected-input-digest mismatch, every time.
import types as _mt_types                                                # noqa: E402
from unittest import mock as _mt_mock                                    # noqa: E402
from ui.services import fact_extraction_mutation_facade as _mt_facade    # noqa: E402

_MT_PREVIEW = {
    "case_id": "case_0001", "document_id": "doc_1",
    "target_ref": "fact.doc_1.pending", "input_digest": "d" * 64,
    "generation_mode": "agent", "model_id": "m", "engine_version": "1.3",
    "prompt_agent_version": "p", "pending_exists": False, "pending_sha256": None,
    "masking_policy_version": "tr_pseudonymisation_v1",
    "masking_extra_terms_digest": "e" * 64, "mask_term_count": 2,
    "masked_document_text": "VGMASK_0001P adına", "masked_context_json": "{}",
    "token_count": 1, "class_distribution": {"T": 2, "P": 1},
    "possible_over_masking": {"vkn_without_context_word": 0,
                              "party_name_midword_matches": 3},
    "possible_split_identifier": 2,
    "possible_squeeze_seed_match": 4,
    "original_text_chars": 10, "masked_text_chars": 18,
}
_mt_captured = {}


def _mt_fake_preview(case_id, document_id, **kwargs):
    _mt_captured.update(kwargs)
    return dict(_MT_PREVIEW)


_mt_args = _mt_types.SimpleNamespace(
    row_key="fact_extraction", case_id="case_0001", document="doc_1",
    with_agent=True, allow_network=False, apply=False, actor_user_id=7,
    mask_term=["Eski Ünvan Ltd. Şti.", 'Boşluklu "Ad" A.Ş.'],
    expected_input_digest=None,
)
with _mt_mock.patch.object(_mt_facade, "preview_generation", _mt_fake_preview):
    _mt_out = cli_mutate._run_generation(
        _mt_args, principal=object(), repository=object(), mutation_conn_factory=None,
    )
check(
    "ADIM 4a: the CLI forwards the --mask-term list to the facade preview verbatim",
    _mt_captured.get("mask_terms") == ("Eski Ünvan Ltd. Şti.", 'Boşluklu "Ad" A.Ş.'),
    _mt_captured.get("mask_terms"),
)
_mt_suggested = [ln for ln in _mt_out.splitlines() if ln.startswith("Üretmek için:")][0]

# SAFE terms ARE still echoed into the command (the digest depends on
# the exact list, so a copy-pasted command that dropped them would fail
# closed with an --expected-input-digest mismatch).
_mt_args_safe = _mt_types.SimpleNamespace(
    row_key="fact_extraction", case_id="case_0001", document="doc_1",
    with_agent=True, allow_network=False, apply=False, actor_user_id=7,
    mask_term=["Eski Unvan Ltd", "Ahmet"],
    expected_input_digest=None,
)
with _mt_mock.patch.object(_mt_facade, "preview_generation", _mt_fake_preview):
    _mt_out_safe = cli_mutate._run_generation(
        _mt_args_safe, principal=object(), repository=object(), mutation_conn_factory=None,
    )
_mt_suggested_safe = [ln for ln in _mt_out_safe.splitlines() if ln.startswith("Üretmek için:")][0]
check(
    "ADIM 4a: the suggested apply command ECHOES every SAFE --mask-term (otherwise the "
    "copy-pasted command would fail with an --expected-input-digest mismatch)",
    _mt_suggested_safe.count("--mask-term") == 2
    and '"Eski Unvan Ltd"' in _mt_suggested_safe
    and " --mask-term Ahmet" in _mt_suggested_safe,
    _mt_suggested_safe,
)
check(
    "ADIM 4a: an all-safe list produces NO separate operator block",
    "--mask-term DEĞERLERİ" not in _mt_out_safe,
    _mt_out_safe,
)
check(
    "S3: a term containing a double quote is NOT embedded in the suggested command - "
    "list2cmdline is an ARGV encoder, not a SHELL escaper, so unsafe terms go in a separate "
    "block instead",
    "--mask-term" not in _mt_suggested,
    _mt_suggested,
)
check(
    "S3: the unsafe terms are still shown to the operator, one per line, in a clearly "
    "delimited block, with the instruction to pass them with their own shell's quoting",
    "--mask-term DEĞERLERİ" in _mt_out
    and 'Boşluklu "Ad" A.Ş.' in _mt_out
    and "Eski Ünvan Ltd. Şti." in _mt_out
    and "fail-closed" in _mt_out,
    _mt_out,
)
check(
    "ADIM 4a: the preview output shows the masked text, the token count, the class "
    "distribution and the possible-over-masking flags - never the mapping",
    "VGMASK_0001P adına" in _mt_out
    and "masking_token_count=1" in _mt_out
    and "masking_possible_over_masking=" in _mt_out
    and "masking_policy_version=tr_pseudonymisation_v1" in _mt_out
    and "MASKELİ BELGE METNİ" in _mt_out,
    _mt_out,
)
check(
    "N7: the class distribution is printed as a readable sorted 'P=1 T=2' string, not a raw "
    "Python dict repr",
    "masking_class_distribution=P=1 T=2" in _mt_out
    and "{'P'" not in _mt_out and "{'T'" not in _mt_out,
    [ln for ln in _mt_out.splitlines() if ln.startswith("masking_class_distribution")],
)
check(
    "R1(iii): the squeeze-seed hint counter is shown in the preview with a plain Turkish note",
    "masking_possible_squeeze_seed_match=4" in _mt_out
    and "sıradan kelimelerin birleşimiyle" in _mt_out,
    [ln for ln in _mt_out.splitlines() if ln.startswith("masking_possible_squeeze_seed_match")],
)
check(
    "b2: the split-identifier hint counter is shown in the preview with a plain Turkish note",
    "masking_possible_split_identifier=2" in _mt_out
    and "satır sonu/boşlukla bölünmüş olabilir" in _mt_out,
    [ln for ln in _mt_out.splitlines() if ln.startswith("masking_possible_split_identifier")],
)
check(
    "S2: the mid-word over-masking counter reaches the operator's preview",
    "party_name_midword_matches=3" in _mt_out,
    [ln for ln in _mt_out.splitlines() if ln.startswith("masking_possible_over_masking")],
)

# ---- S3 matrix: shell metacharacters must NEVER be embedded ----
# The reviewer's own probe proved a bare '>' term actually CREATED files
# in their working directory. These checks are PURE STRING checks - no
# shell is ever invoked and no file can be created.
for _s3_term, _s3_safe, _s3_label in [
    ("Ahmet", True, "plain ASCII word"),
    ("Deneme Tekstil", True, "two words with a space"),
    ("ABC-123_x.y", True, "dot, dash, underscore"),
    ("Öztürk Gıda", True, "non-ASCII Turkish letters"),
    ("A&B", False, "ampersand"),
    ("Oz>Yon", False, "redirection"),
    ("A|B", False, "pipe"),
    ("A^B", False, "caret"),
    ("%PATH%", False, "cmd.exe variable expansion"),
    ("$env:PATH", False, "PowerShell variable"),
    ('Bos "Ad"', False, "embedded double quotes"),
    ("A'B", False, "single quote"),
    ("A`B", False, "backtick"),
    ("A;B", False, "semicolon"),
    ("A(B)", False, "parentheses"),
    (" leading", False, "leading whitespace"),
]:
    check(
        f"S3 safety classifier: {_s3_label} -> {'SAFE' if _s3_safe else 'UNSAFE'}",
        cli_mutate._mask_term_is_shell_safe(_s3_term) is _s3_safe,
        repr(_s3_term),
    )
    _s3_part, _s3_block = cli_mutate._format_mask_terms_for_operator([_s3_term])
    if _s3_safe:
        check(
            f"S3: a safe term IS embedded in the command ({_s3_label})",
            _s3_term in _s3_part and _s3_block == "",
            (_s3_part, _s3_block),
        )
        check(
            f"S3: a safe term containing a space is double-quoted ({_s3_label})",
            (" " not in _s3_term) or ('"%s"' % _s3_term in _s3_part),
            _s3_part,
        )
    else:
        check(
            f"S3: an UNSAFE term is NEVER embedded in the command ({_s3_label})",
            _s3_part == "" and _s3_term in _s3_block,
            (_s3_part, _s3_block),
        )
check(
    "S3: ONE unsafe term suppresses embedding for the WHOLE list (a partially embedded "
    "list would silently change the digest)",
    cli_mutate._format_mask_terms_for_operator(["Ahmet", "A&B"])[0] == "",
)
check(
    "S3: no shell metacharacter can appear in the embedded part for any mixed list",
    all(
        ch not in cli_mutate._format_mask_terms_for_operator(["Ahmet", "A&B", "Oz>Yon"])[0]
        for ch in "&|><^%$`;()'"
    ),
)
_s3_all_safe_part, _s3_all_safe_block = cli_mutate._format_mask_terms_for_operator(
    ["Ahmet", "Deneme Tekstil"],
)
check(
    "S3 CONTROL: an all-safe list IS embedded and produces NO separate block",
    _s3_all_safe_part == ' --mask-term Ahmet --mask-term "Deneme Tekstil"'
    and _s3_all_safe_block == "",
    _s3_all_safe_part,
)
check(
    "S3: an empty term list embeds nothing and prints no block",
    cli_mutate._format_mask_terms_for_operator([]) == ("", ""),
)

_mt_args_none = _mt_types.SimpleNamespace(
    row_key="fact_extraction", case_id="case_0001", document="doc_1",
    with_agent=True, allow_network=False, apply=False, actor_user_id=7,
    mask_term=[], expected_input_digest=None,
)
with _mt_mock.patch.object(_mt_facade, "preview_generation", _mt_fake_preview):
    _mt_out_none = cli_mutate._run_generation(
        _mt_args_none, principal=object(), repository=object(), mutation_conn_factory=None,
    )
check(
    "ADIM 4a: with no --mask-term given, the suggested apply command carries none either",
    "--mask-term" not in _mt_out_none and _mt_captured.get("mask_terms") == (),
    _mt_out_none,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "legal_research", "--allow-network",
    "--actor-user-id", "1",
])
check(
    "generation: --allow-network alone (no --with-agent) is rejected for --row-key "
    "legal_research -> exit 2, zero connections",
    code == cli_mutate.EXIT_USAGE_ERROR and "--allow-network" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "case_law", "--allow-network",
    "--actor-user-id", "1", "--apply", "--expected-input-digest", "h",
])
check(
    "generation: --allow-network alone rejected even with --apply/--expected-input-digest "
    "present, for --row-key case_law",
    code == cli_mutate.EXIT_USAGE_ERROR and "--allow-network" in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "legal_research", "--document", "d",
    "--actor-user-id", "1",
])
check(
    "generation: legal_research choice is genuinely present in --row-key's choices (the "
    "already-invalid --document combination above still reports --document, never "
    "'invalid choice' - a bare, fully-valid preview call is deliberately NOT exercised here, "
    "since it would proceed past usage validation into this harness's own EXPLODING connection "
    "factories)",
    "invalid choice" not in err,
)

code, _, err = run_cli_usage_only([
    "generation", "--case", "x", "--row-key", "case_law", "--document", "d", "--actor-user-id", "1",
])
check(
    "generation: case_law choice is genuinely present in --row-key's choices",
    "invalid choice" not in err,
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
    # ROW 19C-3c-i - the two deadline/timeline deterministic PENDING-
    # GENERATION bypasses. Neither module builds an argparse parser
    # anymore (`main()` refuses unconditionally, before parsing anything)
    # - an empty args list is therefore genuinely representative, not a
    # shortcut.
    ("deadline_engine", []),
    ("timeline_engine", []),
]

check(
    "LEGACY_MUTATION_MATRIX covers all 19 legacy mutation entry points "
    "(10 Layer A + 5 Layer B + 2 promotion + 2 generation)",
    len(LEGACY_MUTATION_MATRIX) == 19,
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
    "LEGACY_MUTATION_MATRIX (19 legacy executables) + EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX (3 "
    "additional evidence_review flag variants) = 22 total refusal subprocess scenarios in this "
    "section - NOT 22 distinct legacy modules (evidence_review itself contributes 4 of the 22: "
    "one entry from each list)",
    len(LEGACY_MUTATION_MATRIX) + len(EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX) == 22,
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
    "all 22 legacy mutation bypass scenarios together (19 legacy executables + 3 additional "
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


# ============================================================
# RAG GLOBAL-RESOURCE BUNDLE FOUNDATION - `rag-bundle` subcommand
# usage-shape validation, mirroring every other subcommand's own
# dedicated block above (`run_cli_usage_only` - a usage error opens
# ZERO connections at all, authz or mutation).
# ============================================================

_v64 = "v_" + "a" * 64

code, _, err = run_cli_usage_only(["rag-bundle", "--actor-user-id", "1"])
check("rag-bundle: missing --action -> exit 2 (argparse-level)", code == cli_mutate.EXIT_USAGE_ERROR)

code, _, err = run_cli_usage_only(["rag-bundle", "--action", "list", "--actor-user-id", "1", "--apply"])
check(
    "rag-bundle: --action list rejects --apply and every other extra flag",
    code == cli_mutate.EXIT_USAGE_ERROR and "list accepts no other flag" in err, err,
)

code, _, err = run_cli_usage_only(["rag-bundle", "--action", "build", "--actor-user-id", "1", "--allow-network"])
check(
    "rag-bundle: build PREVIEW rejects --allow-network",
    code == cli_mutate.EXIT_USAGE_ERROR and "not accepted on build preview" in err, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "build", "--actor-user-id", "1", "--apply", "--expected-input-digest", "x",
])
check(
    "rag-bundle: build --apply without --allow-network is refused (no relaxed mode)",
    code == cli_mutate.EXIT_USAGE_ERROR and "requires --allow-network" in err, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "build", "--actor-user-id", "1", "--apply", "--allow-network",
])
check(
    "rag-bundle: build --apply without --expected-input-digest is refused",
    code == cli_mutate.EXIT_USAGE_ERROR and "requires --expected-input-digest" in err, err,
)

code, _, err = run_cli_usage_only(["rag-bundle", "--action", "activate", "--actor-user-id", "1"])
check(
    "rag-bundle: activate requires --bundle-version (preview and apply alike)",
    code == cli_mutate.EXIT_USAGE_ERROR and "requires --bundle-version" in err, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "activate", "--bundle-version", _v64, "--actor-user-id", "1", "--apply",
])
check(
    "rag-bundle: activate --apply without --expected-current-version is refused",
    code == cli_mutate.EXIT_USAGE_ERROR and "requires --expected-current-version" in err, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "activate", "--bundle-version", _v64, "--actor-user-id", "1", "--allow-network",
])
check(
    "rag-bundle: activate rejects --allow-network entirely",
    code == cli_mutate.EXIT_USAGE_ERROR and "not accepted for --action activate" in err, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "build", "--actor-user-id", "1", "--bundle-version", _v64,
])
check(
    "rag-bundle: --bundle-version rejected for --action build",
    code == cli_mutate.EXIT_USAGE_ERROR and "not accepted for --action build" in err, err,
)

# ============================================================
# TARGETED F1 REMEDIATION (T22) - `--activation-attempt` usage-shape
# matrix. Every rule fires strictly BEFORE any connection is opened
# (proven via run_cli_usage_only()'s own exploding conn factories,
# exactly like every other block above).
# ============================================================

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "activate", "--bundle-version", _v64, "--actor-user-id", "1",
    "--activation-attempt", "-1",
])
check(
    "rag-bundle: activate rejects a negative --activation-attempt (preview)",
    code == cli_mutate.EXIT_USAGE_ERROR and "activation-attempt must be a non-negative integer" in err, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "activate", "--bundle-version", _v64, "--actor-user-id", "1",
    "--apply", "--expected-current-version", "none", "--activation-attempt", "-1",
])
check(
    "rag-bundle: activate rejects a negative --activation-attempt (apply)",
    code == cli_mutate.EXIT_USAGE_ERROR and "activation-attempt must be a non-negative integer" in err, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "activate", "--bundle-version", _v64, "--actor-user-id", "1",
    "--activation-attempt", "not-an-int",
])
check(
    "rag-bundle: activate rejects a non-integer --activation-attempt at the argparse layer",
    code == cli_mutate.EXIT_USAGE_ERROR, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "build", "--actor-user-id", "1", "--activation-attempt", "1",
])
check(
    "rag-bundle: --activation-attempt rejected (non-default) for --action build",
    code == cli_mutate.EXIT_USAGE_ERROR and "activation-attempt is not accepted for --action build" in err, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "build", "--actor-user-id", "1", "--apply", "--allow-network",
    "--expected-input-digest", "x", "--activation-attempt", "1",
])
check(
    "rag-bundle: --activation-attempt rejected (non-default) for --action build --apply",
    code == cli_mutate.EXIT_USAGE_ERROR and "activation-attempt is not accepted for --action build" in err, err,
)

code, _, err = run_cli_usage_only([
    "rag-bundle", "--action", "list", "--actor-user-id", "1", "--activation-attempt", "1",
])
check(
    "rag-bundle: --activation-attempt rejected (non-default) for --action list",
    code == cli_mutate.EXIT_USAGE_ERROR and "list accepts no other flag" in err, err,
)

def _usage_shape_passed_to_connection(argv):
    """True iff usage validation PASSED and the code went on to try to
    open a real connection - proven by catching the exploding authz
    factory's OWN AssertionError (never guessed from a return code,
    since a valid usage shape never returns normally from `main()`
    here - it raises, exactly like every other exploding-factory proof
    in this file's error-path checks above, just triggered from the
    OTHER side of the usage-shape boundary)."""
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        cli_mutate.main(
            argv, authz_conn_factory=_exploding_authz_conn_factory,
            mutation_conn_factory=_exploding_mutation_conn_factory,
            stdout=stdout, stderr=stderr,
        )
        return False
    except AssertionError as error:
        return "authz connection factory was called" in str(error)


check(
    "rag-bundle: activate preview accepts --activation-attempt 0 (usage-shape passes, reaches authz next)",
    _usage_shape_passed_to_connection([
        "rag-bundle", "--action", "activate", "--bundle-version", _v64, "--actor-user-id", "1",
        "--activation-attempt", "0",
    ]),
)

check(
    "rag-bundle: activate preview accepts a large non-negative --activation-attempt (usage-shape passes)",
    _usage_shape_passed_to_connection([
        "rag-bundle", "--action", "activate", "--bundle-version", _v64, "--actor-user-id", "1",
        "--activation-attempt", "7",
    ]),
)

check(
    "rag-bundle: activate apply accepts a non-negative --activation-attempt (usage-shape passes)",
    _usage_shape_passed_to_connection([
        "rag-bundle", "--action", "activate", "--bundle-version", _v64, "--actor-user-id", "1",
        "--apply", "--expected-current-version", "none", "--activation-attempt", "1",
    ]),
)


# ============================================================
# PILOT READINESS ADIM 4b (1/2) - RAW-TEXT EGRESS REFUSAL at the CLI
# usage-shape layer, for the FOUR families whose prompt carries raw case
# text (issue_spotting/evidence/argument via the agent-generation
# branch; legal_research via the legal_research/case_law branch it
# SHARES with case_law).
#
# Contract: `--with-agent` is refused UNCONDITIONALLY - on preview AND
# on apply, with or without `--allow-network` - BEFORE any connection,
# authz repository, filesystem probe or journal access (the exploding
# factories prove zero connections). This is Layer 1; the two facades
# enforce the same rule INDEPENDENTLY as Layer 2 (proven in
# `test_agent_generation_mutation_facade_isolated.py` /
# `test_legal_research_case_law_mutation_facade_isolated.py`).
# ============================================================

_STEP4B_REFUSED_FAMILIES = ["issue_spotting", "evidence", "argument", "legal_research"]

# The two facades' own fixed message text, reproduced here as a literal
# so a wording drift in either facade turns this red (the CLI imports
# the message from the facades - it is never written twice in
# production code).
_STEP4B_REFUSAL_MESSAGE_TEMPLATE = (
    "HATA: --row-key {row_key} için agent modu KAPALIDIR (Pilot Readiness Adım 4b): "
    "bu ailenin prompt'u ham fact cümlesi ve/veya belgeden birebir alıntı taşır ve bu "
    "aile için HENÜZ bir maskeleme katmanı yoktur. --with-agent bu ailede preview'da da "
    "apply'da da kabul edilmez; deterministik mod (--with-agent OLMADAN) çalışmaya devam "
    "eder."
)

_data_snapshot_before_step4b = _snapshot_data_tree()

for _family in _STEP4B_REFUSED_FAMILIES:
    _expected_msg = _STEP4B_REFUSAL_MESSAGE_TEMPLATE.format(row_key=_family)

    # (a) PREVIEW with --with-agent alone.
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1", "--with-agent",
    ])
    check(
        f"ADIM 4b: generation --row-key {_family} --with-agent (PREVIEW) -> exit 2, zero "
        "connections",
        code == cli_mutate.EXIT_USAGE_ERROR,
        f"code={code!r} stderr={err!r}",
    )
    check(
        f"ADIM 4b: {_family} PREVIEW refusal stderr is EXACTLY the facade's fixed message (names "
        "the family and --with-agent), stdout empty, no traceback",
        err == _expected_msg + "\n" and out == "" and "Traceback" not in err,
        f"stderr={err!r} stdout={out!r}",
    )

    # (b) APPLY with --with-agent alone - the F3 residue path. Before
    #     Adım 4b this was ACCEPTED and would write a pending + audit
    #     claiming `generation_mode="agent"` with the real model name,
    #     while never calling a model at all.
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        "--with-agent", "--apply", "--expected-input-digest", "h",
    ])
    check(
        f"ADIM 4b / F3: generation --row-key {_family} --with-agent --apply WITHOUT "
        "--allow-network -> exit 2, zero connections (previously ACCEPTED: it produced a pending "
        "+ audit recording agent provenance although no model was ever called)",
        code == cli_mutate.EXIT_USAGE_ERROR and err == _expected_msg + "\n" and out == "",
        f"code={code!r} stderr={err!r} stdout={out!r}",
    )

    # (c) APPLY with the full --with-agent --allow-network combination.
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        "--with-agent", "--allow-network", "--apply", "--expected-input-digest", "h",
    ])
    check(
        f"ADIM 4b: generation --row-key {_family} --with-agent --allow-network --apply -> exit 2, "
        "zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and err == _expected_msg + "\n" and out == "",
        f"code={code!r} stderr={err!r} stdout={out!r}",
    )

    # (d) PREVIEW with --with-agent --allow-network.
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        "--with-agent", "--allow-network",
    ])
    check(
        f"ADIM 4b: generation --row-key {_family} --with-agent --allow-network (PREVIEW) -> exit "
        "2, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and err == _expected_msg + "\n" and out == "",
        f"code={code!r} stderr={err!r} stdout={out!r}",
    )

    # (e) --allow-network ALONE keeps its OLD, unchanged message (the
    #     Adım 4b check is deliberately placed BEFORE that rule but is
    #     gated on --with-agent, so this path is byte-identical to
    #     before).
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        "--allow-network",
    ])
    check(
        f"ADIM 4b: {_family} --allow-network ALONE still yields the OLD '--allow-network requires "
        "--with-agent' message, NOT the new refusal (pre-existing behaviour preserved)",
        code == cli_mutate.EXIT_USAGE_ERROR
        and err == "error: --allow-network requires --with-agent\n",
        f"code={code!r} stderr={err!r}",
    )

    # (f) DETERMINISTIC mode (no --with-agent) is untouched: the usage
    #     shape passes and the command proceeds to open a connection.
    check(
        f"ADIM 4b: {_family} WITHOUT --with-agent (deterministic preview) still passes usage-shape "
        "and reaches the connection layer - deterministic generation is completely unaffected",
        _usage_shape_passed_to_connection([
            "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        ]),
    )

# ============================================================
# PILOT READINESS ADIM 4c - PILOT-POLICY EGRESS REFUSAL at the CLI
# usage-shape layer, for the THREE families whose prompt carries only
# ID/enum-only content (case_law/risk_strategy/drafting - CLAUDE.md's
# own characterization of these three families as NOT carrying raw
# case text is UNCHANGED and NOT contradicted here). Adım 4b's
# "the families that are deliberately NOT refused" positive-control
# loop that used to stand HERE is INVERTED (same discipline as
# CLAUDE.md's Row 19B `"sends no client_secret"` -> real
# `client_secret_post` assertion precedent: the assertion is NOT
# deleted, it is turned to point the other way, with the reason
# recorded) - these three families are now ALSO refused, for a
# SEPARATE, DIFFERENT reason (pilot policy, not raw text), with a
# SEPARATE, DIFFERENT fixed message. Adım 4b's own three-family
# raw-text closure above (issue_spotting/evidence/argument/
# legal_research) is completely UNTOUCHED by this block.
# ============================================================

_STEP4C_PILOT_POLICY_REFUSED_FAMILIES = ["case_law", "risk_strategy", "drafting"]

_STEP4C_REFUSAL_MESSAGE_TEMPLATE = (
    "HATA: --row-key {row_key} için agent modu KAPALIDIR (Pilot Readiness Adım 4c): "
    "bu ailenin prompt'u yalnız ID/enum-only içerik taşısa da (ham case metni TAŞIMAZ), "
    "pilot süresince fact_extraction DIŞINDA hiçbir outbound AI yolu açık tutulmaz. "
    "--with-agent bu ailede preview'da da apply'da da kabul edilmez; deterministik mod "
    "(--with-agent OLMADAN) çalışmaya devam eder."
)

_data_snapshot_before_step4c = _snapshot_data_tree()

for _family in _STEP4C_PILOT_POLICY_REFUSED_FAMILIES:
    _expected_msg = _STEP4C_REFUSAL_MESSAGE_TEMPLATE.format(row_key=_family)

    # (a) PREVIEW with --with-agent alone.
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1", "--with-agent",
    ])
    check(
        f"ADIM 4c: generation --row-key {_family} --with-agent (PREVIEW) -> exit 2, zero "
        "connections",
        code == cli_mutate.EXIT_USAGE_ERROR,
        f"code={code!r} stderr={err!r}",
    )
    check(
        f"ADIM 4c: {_family} PREVIEW refusal stderr is EXACTLY the facade's fixed pilot-policy "
        "message (a DIFFERENT message from Adım 4b's raw-text one), stdout empty, no traceback",
        err == _expected_msg + "\n" and out == "" and "Traceback" not in err,
        f"stderr={err!r} stdout={out!r}",
    )

    # (b) APPLY with --with-agent alone.
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        "--with-agent", "--apply", "--expected-input-digest", "h",
    ])
    check(
        f"ADIM 4c: generation --row-key {_family} --with-agent --apply WITHOUT --allow-network -> "
        "exit 2, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and err == _expected_msg + "\n" and out == "",
        f"code={code!r} stderr={err!r} stdout={out!r}",
    )

    # (c) APPLY with the full --with-agent --allow-network combination.
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        "--with-agent", "--allow-network", "--apply", "--expected-input-digest", "h",
    ])
    check(
        f"ADIM 4c: generation --row-key {_family} --with-agent --allow-network --apply -> exit 2, "
        "zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and err == _expected_msg + "\n" and out == "",
        f"code={code!r} stderr={err!r} stdout={out!r}",
    )

    # (d) PREVIEW with --with-agent --allow-network.
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        "--with-agent", "--allow-network",
    ])
    check(
        f"ADIM 4c: generation --row-key {_family} --with-agent --allow-network (PREVIEW) -> exit "
        "2, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and err == _expected_msg + "\n" and out == "",
        f"code={code!r} stderr={err!r} stdout={out!r}",
    )

    # (e) --allow-network ALONE keeps its OLD, unchanged message (the
    #     Adım 4c check is deliberately placed BEFORE that rule but is
    #     gated on --with-agent, so this path is byte-identical to
    #     before).
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        "--allow-network",
    ])
    check(
        f"ADIM 4c: {_family} --allow-network ALONE still yields the OLD '--allow-network requires "
        "--with-agent' message, NOT either refusal (pre-existing behaviour preserved)",
        code == cli_mutate.EXIT_USAGE_ERROR
        and err == "error: --allow-network requires --with-agent\n",
        f"code={code!r} stderr={err!r}",
    )

    # (f) DETERMINISTIC mode (no --with-agent) is untouched.
    check(
        f"ADIM 4c: {_family} WITHOUT --with-agent (deterministic preview) still passes usage-shape "
        "and reaches the connection layer - deterministic generation is completely unaffected",
        _usage_shape_passed_to_connection([
            "generation", "--case", "x", "--row-key", _family, "--actor-user-id", "1",
        ]),
    )

_data_snapshot_after_step4c = _snapshot_data_tree()
check(
    "ADIM 4c: the whole CLI pilot-policy refusal block left the REAL data/ tree byte-for-byte "
    "UNCHANGED",
    _data_snapshot_before_step4c == _data_snapshot_after_step4c,
    f"changed/added/removed keys: "
    f"{sorted(set(_data_snapshot_before_step4c) ^ set(_data_snapshot_after_step4c))}",
)

check(
    "ADIM 4c: Adım 4b's raw-text refused set and Adım 4c's pilot-policy refused set are "
    "pairwise disjoint at the CLI's OWN lazy-accessor layer (mirrors the facades' own "
    "disjointness invariant, tested independently in test_agent_generation_mutation_facade_"
    "isolated.py / test_legal_research_case_law_mutation_facade_isolated.py)",
    set(_STEP4B_REFUSED_FAMILIES).isdisjoint(set(_STEP4C_PILOT_POLICY_REFUSED_FAMILIES)),
)

check(
    "ADIM 4b: --row-key fact_extraction --document d --with-agent is NOT refused - that family "
    "keeps its OWN, unchanged Row 19C-3c-iii dual gate (Adım 4a masking already applies there)",
    _usage_shape_passed_to_connection([
        "generation", "--case", "x", "--row-key", "fact_extraction", "--document", "d",
        "--actor-user-id", "1", "--with-agent",
    ]),
)
check(
    "ADIM 4b: --row-key fact_extraction --document d --with-agent --allow-network --apply is NOT "
    "refused - its own apply-time dual gate is untouched",
    _usage_shape_passed_to_connection([
        "generation", "--case", "x", "--row-key", "fact_extraction", "--document", "d",
        "--actor-user-id", "1", "--with-agent", "--allow-network", "--apply",
        "--expected-input-digest", "h",
    ]),
)

# deadline/timeline keep their OWN, unchanged unconditional rejection
# message (a DIFFERENT message from the Adım 4b one - proof the new rule
# did not leak into those branches).
for _flagless_family, _extra in [("timeline", []), ("deadline", ["--anchor", "timeline_event_001"])]:
    code, out, err = run_cli_usage_only([
        "generation", "--case", "x", "--row-key", _flagless_family, "--actor-user-id", "1",
        "--with-agent", *_extra,
    ])
    check(
        f"ADIM 4b: --row-key {_flagless_family} --with-agent still yields its OWN pre-existing "
        "'--with-agent/--allow-network are not accepted' message, NOT the Adım 4b refusal",
        code == cli_mutate.EXIT_USAGE_ERROR
        and "--with-agent/--allow-network are not accepted" in err
        and "Adım 4b" not in err,
        f"code={code!r} stderr={err!r}",
    )

_data_snapshot_after_step4b = _snapshot_data_tree()
check(
    "ADIM 4b/4c: the whole combined CLI refusal block (Adım 4b's raw-text refusals, Adım 4c's "
    "pilot-policy refusals nested inside it, and the fact_extraction/deadline/timeline regression "
    "checks) left the REAL data/ tree byte-for-byte UNCHANGED (zero pending, zero generation "
    "audit, zero journal row could have been written - every refusal fires before any connection "
    "is even opened)",
    _data_snapshot_before_step4b == _data_snapshot_after_step4b,
    f"changed/added/removed keys: "
    f"{sorted(set(_data_snapshot_before_step4b) ^ set(_data_snapshot_after_step4b))}",
)


# ============================================================
# PILOT READINESS ADIM 4b (2/2) - `app.py` EGRESS ENTRY-POINT CLOSURE
# (persistent, REAL-subprocess).
#
# `app.py` used to be the repo's only un-gated free-text entry point: it
# read the lawyer's own words with `input()` and passed them to
# `src.rag.answer_question`, whose module imported `anthropic` and built
# a client at import time. It now refuses with a fixed message and a
# genuine OS exit code 2, and - critically - imports NOTHING at module
# level, so `src.rag`/`anthropic` are never even reached.
#
# `app.py` lives at the REPO ROOT, not under `src/`, so
# `_run_legacy_script()` (which resolves `src/<name>.py`) cannot run it -
# this section uses its own narrow runner with the SAME discipline:
# `sys.executable`, explicit `cwd=REPO_ROOT`, bounded timeout, never
# `shell=True`, `PYTHONIOENCODING=utf-8`, raw bytes + strict UTF-8
# decode, and `stdin=DEVNULL` (so a regression that still reached
# `input()` would fail loudly with EOFError instead of hanging).
# ============================================================

_APP_PY_REFUSAL_MESSAGE = (
    "HATA: Bu etkileşimli sohbet giriş noktası artık DEVRE DIŞIDIR "
    "(Pilot Readiness Adım 4b).\n"
    "Avukatın serbest metnini hiçbir maskeleme/yetkilendirme/audit katmanı olmadan "
    "dış bir LLM'e gönderebilen tek kapısız yol buydu.\n"
    "Denetlenen üretim yolları için: python -m ui.cli_mutate --help"
)


def _run_repo_root_script(script_name, args=(), *, extra_pythonpath=None, timeout=90):
    """Same discipline as `_run_legacy_script()` above, for a script that
    lives at the REPO ROOT instead of under `src/`. `extra_pythonpath` is
    PREPENDED to (never replaces) the inherited PYTHONPATH, so any
    sitecustomize-based guard the sweep runner installs via PYTHONPATH
    keeps working in the child while the prepended directory still
    shadows real site-packages."""
    script_path = REPO_ROOT / script_name
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    if extra_pythonpath is not None:
        inherited = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = (
            f"{extra_pythonpath}{os.pathsep}{inherited}" if inherited else str(extra_pythonpath)
        )
    completed = subprocess.run(
        [sys.executable, str(script_path), *args],
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
        # Windows text-mode children emit CRLF; normalise ONLY the line
        # separator so the exact-equality assertion below stays exact.
        stderr=stderr_text.replace("\r\n", "\n"),
    )


_data_snapshot_before_apppy = _snapshot_data_tree()

_app_path, _app_result = _run_repo_root_script("app.py")
check(
    f"app.py: the real script file exists at the repo root and is the one actually invoked "
    f"({_app_path})",
    _app_path.is_file(),
    f"resolved path: {_app_path}",
)
check(
    "app.py: real OS subprocess returncode is exactly 2 (the genuine process exit code "
    "SystemExit(2) produces, not merely main()'s Python-level return value)",
    _app_result.returncode == 2,
    f"got returncode={_app_result.returncode!r} stdout={_app_result.stdout!r} "
    f"stderr={_app_result.stderr!r}",
)
check(
    "app.py: stderr is EXACTLY the fixed Adım 4b refusal message",
    _app_result.stderr == _APP_PY_REFUSAL_MESSAGE + "\n",
    f"stderr={_app_result.stderr!r}",
)
check(
    "app.py: stderr contains no 'Traceback' - a clean, deliberate SystemExit(2), never an "
    "unhandled exception (an EOFError from a surviving input() call, or a ModuleNotFoundError/"
    "RuntimeError from a re-introduced src.rag import, would show up here)",
    "Traceback" not in _app_result.stderr,
    f"stderr={_app_result.stderr!r}",
)
check(
    "app.py: stdout is completely empty - the old chat banner (print_header) is gone and the "
    "refusal goes to stderr only",
    _app_result.stdout == "",
    f"stdout={_app_result.stdout!r}",
)

# --- IMPORT-ORDER PROOF: a poisoned `anthropic` that raises on import
#     is placed FIRST on the child's PYTHONPATH. If `app.py` still
#     imported `src.rag` (which imports `anthropic` and builds a client
#     at module level), the child would die with that RuntimeError
#     instead of refusing cleanly.
_poison_dir = tempfile.mkdtemp(prefix="step4b_poison_")
try:
    (Path(_poison_dir) / "anthropic.py").write_text(
        'raise RuntimeError("STEP4B_POISONED_ANTHROPIC_IMPORTED")\n', encoding="utf-8",
    )

    # POSITIVE CONTROL (mandatory): the SAME PYTHONPATH must genuinely
    # shadow the real package in THIS interpreter - otherwise the proof
    # below would pass vacuously.
    _control_env = os.environ.copy()
    _control_env["PYTHONIOENCODING"] = "utf-8"
    _inherited_pp = _control_env.get("PYTHONPATH", "")
    _control_env["PYTHONPATH"] = (
        f"{_poison_dir}{os.pathsep}{_inherited_pp}" if _inherited_pp else _poison_dir
    )
    _control = subprocess.run(
        [sys.executable, "-c", "import anthropic"],
        cwd=str(REPO_ROOT), capture_output=True, stdin=subprocess.DEVNULL,
        timeout=90, env=_control_env,
    )
    _control_stderr = _control.stderr.decode("utf-8") if _control.stderr else ""
    check(
        "app.py POSITIVE CONTROL: with the SAME poisoned PYTHONPATH, a child that DELIBERATELY "
        "does `import anthropic` really does fail with the stub's RuntimeError - the shadowing "
        "is genuinely effective, so the import-order proof below is not vacuous",
        _control.returncode != 0 and "STEP4B_POISONED_ANTHROPIC_IMPORTED" in _control_stderr,
        f"returncode={_control.returncode!r} stderr={_control_stderr!r}",
    )

    _app_path_p, _app_poisoned = _run_repo_root_script("app.py", extra_pythonpath=_poison_dir)
    check(
        "app.py IMPORT-ORDER PROOF: with a poisoned `anthropic` first on PYTHONPATH the refusal "
        "is UNCHANGED (exit 2, exact fixed message, no traceback, empty stdout) - `src.rag` and "
        "therefore `anthropic` are NEVER imported by app.py",
        _app_poisoned.returncode == 2
        and _app_poisoned.stderr == _APP_PY_REFUSAL_MESSAGE + "\n"
        and "Traceback" not in _app_poisoned.stderr
        and "STEP4B_POISONED_ANTHROPIC_IMPORTED" not in _app_poisoned.stderr
        and _app_poisoned.stdout == "",
        f"returncode={_app_poisoned.returncode!r} stdout={_app_poisoned.stdout!r} "
        f"stderr={_app_poisoned.stderr!r}",
    )
finally:
    shutil.rmtree(_poison_dir, ignore_errors=True)

# Static companion check, AST-based so explanatory COMMENTS (which do
# name the removed code, deliberately) can never satisfy or break it:
# app.py must have ZERO module-level imports at all, and the dead chat
# body's identifiers must appear nowhere in the parsed code. Cheap, and
# it stays red even in an environment where `anthropic` is not installed
# at all (where a re-introduced `from src.rag import ...` would fail
# with ModuleNotFoundError rather than the poisoned stub's RuntimeError).
_app_tree = ast.parse((REPO_ROOT / "app.py").read_text(encoding="utf-8"))
_app_toplevel_imports = [
    node for node in _app_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
]
check(
    "app.py has ZERO module-level import statements (even `sys` is imported lazily inside "
    "main(), matching the src/ingest.py precedent) - so importing or running this file can "
    "never pull in src.rag and therefore never construct an Anthropic client",
    _app_toplevel_imports == [],
    f"unexpected top-level imports: {[ast.dump(n) for n in _app_toplevel_imports]}",
)
_app_identifiers = {
    node.id for node in ast.walk(_app_tree) if isinstance(node, ast.Name)
} | {
    node.attr for node in ast.walk(_app_tree) if isinstance(node, ast.Attribute)
} | {
    node.name for node in ast.walk(_app_tree) if isinstance(node, ast.FunctionDef)
} | {
    alias.name for node in ast.walk(_app_tree)
    if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names
} | {
    node.module for node in ast.walk(_app_tree)
    if isinstance(node, ast.ImportFrom) and node.module
}
check(
    "app.py CODE (not comments) references none of answer_question / run_chat / print_header / "
    "print_sources / input / rag - the ~150-line dead chat body was genuinely deleted, not "
    "merely bypassed",
    not (_app_identifiers & {
        "answer_question", "run_chat", "print_header", "print_sources", "input",
        "rag", "src.rag", "anthropic", "Anthropic",
    }),
    f"unexpected identifiers still present: "
    f"{sorted(_app_identifiers & {'answer_question', 'run_chat', 'print_header', 'print_sources', 'input', 'rag', 'src.rag', 'anthropic', 'Anthropic'})}",
)

_data_snapshot_after_apppy = _snapshot_data_tree()
check(
    "app.py closure scenarios: the REAL data/ tree is byte-for-byte UNCHANGED",
    _data_snapshot_before_apppy == _data_snapshot_after_apppy,
    f"changed/added/removed keys: "
    f"{sorted(set(_data_snapshot_before_apppy) ^ set(_data_snapshot_after_apppy))}",
)

# Refusal-scenario counter: 44 -> 45. `app.py` is the ONLY addition that
# meets this counter's definition (a REAL-OS-subprocess refusal
# scenario); the four families' CLI refusals above are in-process usage-
# shape checks, which this counter has never tracked.
check(
    "ADIM 4b: exactly ONE new real-OS-subprocess refusal scenario is added by this slice "
    "(app.py) - LEGACY_MUTATION_MATRIX (19) + EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX (3) + app.py "
    "(1) = 23 real-subprocess refusal scenarios in THIS file; app.py is counted as a closed "
    "EGRESS entry point, NOT as one of the 29 closed MUTATION entry points",
    len(LEGACY_MUTATION_MATRIX) + len(EVIDENCE_REVIEW_EXTRA_FLAG_MATRIX) + 1 == 23,
)


# ============================================================
# ADIM 10 B YOLU - `manual-fact` subcommand (exact-scope §5.5: C-N1,
# C-N2, C-P1, C-P2). Every refusal below happens BEFORE any connection
# (exploding factories).
# ============================================================

_MF_BASE = ["manual-fact", "--case", "case_0001", "--document", "ihbarname_001", "--actor-user-id", "7"]
_MF_DIGEST = "a" * 64

for _mf_flag in (["--with-agent"], ["--allow-network"], ["--mask-term", "x"], ["--text-path", "p"],
                 ["--model", "m"]):
    code, out, err = run_cli_usage_only(_MF_BASE + _mf_flag)
    check(
        f"C-N1 manual-fact {_mf_flag[0]} -> exit 2 'unrecognized arguments', zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and "unrecognized arguments" in err and out == "",
        f"code={code} err={err!r}",
    )
    code, out, err = run_cli_usage_only(_MF_BASE + ["--apply", "--expected-input-digest", _MF_DIGEST] + _mf_flag)
    check(
        f"C-N1 manual-fact --apply {_mf_flag[0]} -> exit 2 'unrecognized arguments', zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and "unrecognized arguments" in err and out == "",
        f"code={code} err={err!r}",
    )

for _mf_label, _mf_argv, _mf_needle in (
    ("--apply without --expected-input-digest", _MF_BASE + ["--apply"], "--expected-input-digest"),
    ("--expected-input-digest without --apply", _MF_BASE + ["--expected-input-digest", _MF_DIGEST],
     "--expected-input-digest"),
    ("--attempt 2 without --apply", _MF_BASE + ["--attempt", "2"], "--attempt"),
    ("--attempt 0", _MF_BASE + ["--apply", "--expected-input-digest", _MF_DIGEST, "--attempt", "0"], "--attempt"),
    ("--attempt -1", _MF_BASE + ["--apply", "--expected-input-digest", _MF_DIGEST, "--attempt", "-1"], "--attempt"),
    ("non-hex digest", _MF_BASE + ["--apply", "--expected-input-digest", "z" * 64], "--expected-input-digest"),
    ("uppercase digest", _MF_BASE + ["--apply", "--expected-input-digest", "A" * 64], "--expected-input-digest"),
    ("short digest", _MF_BASE + ["--apply", "--expected-input-digest", "a" * 63], "--expected-input-digest"),
):
    code, out, err = run_cli_usage_only(_mf_argv)
    check(
        f"C-N2 manual-fact {_mf_label} -> exit 2, zero connections",
        code == cli_mutate.EXIT_USAGE_ERROR and _mf_needle in err and out == "",
        f"code={code} err={err!r}",
    )

code, out, err = run_cli_usage_only(["manual-fact", "--case", "case_0001", "--actor-user-id", "7"])
check("C-N2 manual-fact without --document -> exit 2 (required), zero connections",
      code == cli_mutate.EXIT_USAGE_ERROR and "--document" in err, f"err={err!r}")

_mf_parser = cli_mutate._build_arg_parser()
_mf_sub_choices = _mf_parser._subparsers._group_actions[0].choices
_mf_options = set()
for _sub_action in _mf_sub_choices["manual-fact"]._actions:
    _mf_options.update(_sub_action.option_strings)
check(
    "C-P1 manual-fact accepts EXACTLY {--case, --document, --actor-user-id, --apply, "
    "--expected-input-digest, --attempt, -h/--help}",
    _mf_options == {"--case", "--document", "--actor-user-id", "--apply", "--expected-input-digest",
                    "--attempt", "-h", "--help"},
    f"{sorted(_mf_options)!r}",
)
check(
    "C-P2a the dispatcher now has exactly 7 subcommands (manual-fact added, none removed)",
    set(_mf_sub_choices) == {"approval", "review", "promotion", "generation", "rag-bundle", "verification",
                             "manual-fact"},
    f"{sorted(_mf_sub_choices)!r}",
)
_mf_generation_row_keys = None
for _sub_action in _mf_sub_choices["generation"]._actions:
    if "--row-key" in _sub_action.option_strings:
        _mf_generation_row_keys = set(_sub_action.choices)
check(
    "C-P2b `generation --row-key` choices do NOT include fact_manual (separate subcommand only) and still "
    "include fact_extraction",
    _mf_generation_row_keys is not None and "fact_manual" not in _mf_generation_row_keys
    and "fact_extraction" in _mf_generation_row_keys,
    f"{sorted(_mf_generation_row_keys or [])!r}",
)

# C-P3: dispatch wiring with a fake facade (no filesystem, no journal).
from ui.services import manual_fact_mutation_facade as _mf_facade  # noqa: E402

_mf_calls = []
_mf_orig_preview = _mf_facade.preview_manual_fact
_mf_orig_apply = _mf_facade.apply_manual_fact


def _mf_fake_preview(case_id, document_id, *, principal, authz_repository):
    _mf_calls.append(("preview", case_id, document_id))
    return {
        "case_id": case_id, "document_id": document_id, "target_ref": f"fact.{document_id}.pending",
        "input_digest": "b" * 64, "pending_sha256": "c" * 64, "notification_date": "2026-02-10",
        "page": 1, "excerpt_found": True, "text_excerpt_sha256": "d" * 64,
    }


def _mf_fake_apply(case_id, document_id, expected_input_digest, *, attempt, principal, authz_repository,
                   conn_factory):
    _mf_calls.append(("apply", case_id, document_id, expected_input_digest, attempt))
    if attempt == 9:
        raise _mf_facade.ManualFactExcerptRejectedError("Manuel fact girişi reddedildi (kural M-07).")
    return _mf_facade.ManualFactApplyResult(
        case_id=case_id, document_id=document_id, pending_sha256="c" * 64,
        audit_file="manual_ihbarname_001_20261008_000000.generation_audit.json", journal_id=5,
        attempt=attempt, replayed=False,
    )


_mf_facade.preview_manual_fact = _mf_fake_preview
_mf_facade.apply_manual_fact = _mf_fake_apply
try:
    _mf_conn = FakeAuthzConn(users={7: (1, False)}, assignments={(7, "case_0001"): "lawyer"})
    code, out, err = run_cli(_MF_BASE, authz_conn=_mf_conn, mutation_conn_factory=_exploding_mutation_conn_factory)
    check(
        "C-P3a preview dispatch -> exit 0, prints input_digest/excerpt_found/sha and the apply command with --attempt 1",
        code == 0 and "PREVIEW manual-fact" in out and f"input_digest={'b' * 64}" in out
        and "excerpt_found=true" in out and f"text_excerpt_sha256={'d' * 64}" in out
        and f"--expected-input-digest {'b' * 64} --attempt 1" in out and _mf_calls[-1][0] == "preview",
        f"code={code} out={out!r} err={err!r}",
    )
    code, out, err = run_cli(_MF_BASE + ["--apply", "--expected-input-digest", _MF_DIGEST, "--attempt", "3"],
                             authz_conn=_mf_conn, mutation_conn_factory=_exploding_mutation_conn_factory)
    check(
        "C-P3b apply dispatch passes --expected-input-digest and --attempt through unchanged",
        code == 0 and _mf_calls[-1] == ("apply", "case_0001", "ihbarname_001", _MF_DIGEST, 3)
        and "APPLIED manual-fact" in out and "attempt=3" in out and "journal_id=5" in out
        and "promotion --case case_0001 --row-key fact --document ihbarname_001" in out,
        f"code={code} out={out!r} err={err!r}",
    )
    code, out, err = run_cli(_MF_BASE + ["--apply", "--expected-input-digest", _MF_DIGEST, "--attempt", "9"],
                             authz_conn=_mf_conn, mutation_conn_factory=_exploding_mutation_conn_factory)
    check(
        "C-P3c a facade domain error -> exit 1, ONE clean ERROR line, no traceback",
        code == cli_mutate.EXIT_DOMAIN_ERROR and err.startswith("ERROR: ManualFactExcerptRejectedError:")
        and "Traceback" not in err and out == "",
        f"code={code} out={out!r} err={err!r}",
    )
finally:
    _mf_facade.preview_manual_fact = _mf_orig_preview
    _mf_facade.apply_manual_fact = _mf_orig_apply


print(f"--- test_cli_mutate_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
