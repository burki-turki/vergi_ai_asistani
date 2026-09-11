# ============================================================
# Row 19C-2a Step 4 - isolated (fake-adapter, fake-connection) tests
# for ui/reconciliation_operator.py.
#
# This file tests the CLI LAYER ONLY - argument parsing, exit-code
# discipline, output formatting, provenance wiring (the hard-coded
# 'cli_service' actor_type plus the given --actor-ref), and the
# dependency-injected conn_factory/registry_factory seams. It
# deliberately does NOT re-prove ui.services.mutation_registry's own
# decision table, lock discipline, or rowcount-checked UPDATE
# semantics - see ui/tests/test_reconciliation_isolated.py (fake-conn)
# and ui/tests/test_mutation_reconciliation_provenance_postgres.py
# (real PostgreSQL) for that. Every SUCCESS-path check below still
# calls the REAL ui.services.mutation_registry functions (never a fake
# stand-in for those) against a FAKE `mutation.mutation_journal` table
# - only the database connection itself is faked, exactly like
# ui/tests/test_reconciliation_isolated.py's own FakeReconcileConn (a
# fresh, self-contained copy here, matching this project's existing
# convention of each test file owning its own fakes rather than
# importing another test file's).
#
# Run: python -m ui.tests.test_reconciliation_operator_isolated
# ============================================================

import io
import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui import reconciliation_operator as op            # noqa: E402
from ui.services import mutation_lock as ml              # noqa: E402
from ui.services import mutation_registry as mr           # noqa: E402

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
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")


# ----------------------------------------------------------------
# Fake mutation.mutation_journal table + cursor - same minimal shape
# ui/tests/test_reconciliation_isolated.py's own FakeReconcileCursor
# uses, extended only with a `.closed` counter on the connection so
# this file can prove `main()` ALWAYS closes the connection it was
# handed, on every exit path (success, known error, or an unexpected
# exception propagating out of registry_factory()).
# ----------------------------------------------------------------

_RESOLVABLE_STATES = ("prepared", "executing", "reconciliation_required")


class FakeAdapter:
    def __init__(self, evidence_or_raiser):
        self._evidence_or_raiser = evidence_or_raiser

    def gather_evidence(self, entry):
        if callable(self._evidence_or_raiser):
            return self._evidence_or_raiser(entry)
        return self._evidence_or_raiser


class FakeCursor:
    def __init__(self, table, calls):
        self._table = table
        self._calls = calls
        self._last_result = None
        self.rowcount = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _row(self, journal_id):
        for r in self._table:
            if r["id"] == journal_id:
                return r
        return None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._calls.append(normalized)

        if normalized.startswith("SELECT resource_key FROM mutation.mutation_journal WHERE id"):
            (journal_id,) = params
            row = self._row(journal_id)
            self._last_result = (row["resource_key"],) if row is not None else None
            self.rowcount = 1 if row is not None else 0

        elif normalized.startswith("SELECT id, resource_key, action_family, target_ref, target_state"):
            (journal_id,) = params
            row = self._row(journal_id)
            if row is None:
                self._last_result = None
                self.rowcount = 0
            else:
                self._last_result = (
                    row["id"], row["resource_key"], row["action_family"], row["target_ref"],
                    row["target_state"], row["pre_hash"], row["pre_revision"],
                    row["expected_post_hash"], row["state"], row["idempotency_key"],
                    row["request_fingerprint"], row["actor_label"],  # ROW 19C-2b: appended fields
                )
                self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'reconciliation_required'"):
            (journal_id,) = params
            row = self._row(journal_id)
            if row is not None and row["state"] in _RESOLVABLE_STATES:
                row["state"] = "reconciliation_required"
                if row.get("executing_at") is None:
                    row["executing_at"] = "FAKE_TIMESTAMP"
                self.rowcount = 1
            else:
                self.rowcount = 0

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'failed', resolution_code = %s"):
            resolution_code, observed_post_hash, reconciled_by_actor_type, reconciled_by_actor_ref, journal_id = params
            row = self._row(journal_id)
            if row is not None and row["state"] == "prepared":
                row["state"] = "failed"
                row["resolution_code"] = resolution_code
                row["observed_post_hash"] = observed_post_hash
                row["resolved_at"] = "FAKE_TIMESTAMP"
                row["reconciled_by_actor_type"] = reconciled_by_actor_type
                row["reconciled_by_actor_ref"] = reconciled_by_actor_ref
                self.rowcount = 1
            else:
                self.rowcount = 0

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = %s"):
            new_state, resolution_code, observed_post_hash, reconciled_by_actor_type, reconciled_by_actor_ref, journal_id = params
            row = self._row(journal_id)
            if row is not None and row["state"] in ("executing", "reconciliation_required"):
                row["state"] = new_state
                row["resolution_code"] = resolution_code
                row["observed_post_hash"] = observed_post_hash
                row["resolved_at"] = "FAKE_TIMESTAMP"
                if row.get("executing_at") is None:
                    row["executing_at"] = "FAKE_TIMESTAMP"
                row["reconciled_by_actor_type"] = reconciled_by_actor_type
                row["reconciled_by_actor_ref"] = reconciled_by_actor_ref
                self.rowcount = 1
            else:
                self.rowcount = 0

        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._last_result


class FakeConn:
    def __init__(self, table=None):
        self.table = table if table is not None else []
        self.calls = []
        self.close_count = 0

    def cursor(self):
        return FakeCursor(self.table, self.calls)

    def close(self):
        self.close_count += 1


def make_journal_row(**overrides):
    row = dict(
        id=1, resource_key="case:case_0001", action_family="fam.op_test",
        target_ref="target_a", target_state=None, pre_hash=None, pre_revision=None,
        expected_post_hash=None, state="executing",
        resolution_code=None, observed_post_hash=None, resolved_at=None, executing_at="PRE_EXISTING_TS",
        idempotency_key="fake_idempotency_key_op_0001",
        reconciled_by_actor_type=None, reconciled_by_actor_ref=None,
        # ROW 19C-2b: JournalEntrySnapshot's two newest appended fields.
        request_fingerprint="fake_request_fingerprint_op_0001", actor_label="1",
    )
    row.update(overrides)
    return row


def _poisoned_factory(label):
    def _factory():
        raise AssertionError(f"{label} must NOT be called for this scenario")
    return _factory


_original_acquire_case = ml.acquire_case_lock_session
_original_acquire_global = ml.acquire_global_lock_session
_original_release = ml.release_lock_session


def _fake_acquire_case_lock_session(conn, case_id):
    return 111


def _fake_acquire_global_lock_session(conn, resource_key):
    return 222


def _fake_release_lock_session(conn, advisory_lock_id):
    return True


try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.acquire_global_lock_session = _fake_acquire_global_lock_session
    ml.release_lock_session = _fake_release_lock_session

    # ----------------------------------------------------------------
    # 1) USAGE ERRORS - exit code 2, printed to the INJECTED stderr,
    #    and (critically) conn_factory/registry_factory are NEVER
    #    called for any of these - usage validation happens strictly
    #    before any connection or registry is ever built.
    # ----------------------------------------------------------------

    def _run_usage_case(argv, label, message_substring):
        out, err = io.StringIO(), io.StringIO()
        code = op.main(
            argv,
            conn_factory=_poisoned_factory("conn_factory"),
            registry_factory=_poisoned_factory("registry_factory"),
            stdout=out, stderr=err,
        )
        check(f"{label}: exit code is EXIT_USAGE_ERROR (2)", code == op.EXIT_USAGE_ERROR, f"got {code}")
        check(f"{label}: stderr mentions {message_substring!r}", message_substring in err.getvalue(), f"got {err.getvalue()!r}")
        check(f"{label}: nothing was written to stdout", out.getvalue() == "", f"got {out.getvalue()!r}")

    _run_usage_case([], "missing --journal-id entirely", "required")
    _run_usage_case(["--journal-id", "abc"], "non-integer --journal-id", "invalid int value")
    _run_usage_case(["--journal-id", "0"], "zero --journal-id", "positive integer")
    _run_usage_case(["--journal-id", "-5"], "negative --journal-id", "positive integer")
    _run_usage_case(["--journal-id", "1", "--apply"], "--apply without --actor-ref", "requires --actor-ref")
    _run_usage_case(["--journal-id", "1", "--actor-ref", "someone"], "--actor-ref without --apply", "only meaningful together with --apply")
    _run_usage_case(["--journal-id", "1", "--apply", "--actor-ref", "   "], "whitespace-only --actor-ref", "blank")
    _run_usage_case(["--journal-id", "1", "--apply", "--actor-ref", "x" * 256], "256-char --actor-ref", "255 characters")

    # ----------------------------------------------------------------
    # 2) _NonExitingArgumentParser never calls the REAL sys.exit()/
    #    sys.stderr - proven by the fact that every usage case above
    #    already returned a plain int without terminating this test
    #    process, plus an explicit direct check that a bad-args call
    #    does not raise SystemExit.
    # ----------------------------------------------------------------

    try:
        code = op.main(
            ["--journal-id", "not-a-number"],
            conn_factory=_poisoned_factory("conn_factory"), registry_factory=_poisoned_factory("registry_factory"),
            stdout=io.StringIO(), stderr=io.StringIO(),
        )
        check("a bad-args call returns a plain int, never raises SystemExit", isinstance(code, int) and not isinstance(code, bool))
    except SystemExit:
        check("a bad-args call returns a plain int, never raises SystemExit", False, "SystemExit was raised for real")

    # ----------------------------------------------------------------
    # 3) DRY RUN success path - real mutation_registry.inspect_reconciliation()
    #    is genuinely invoked; the row is left COMPLETELY untouched (zero
    #    UPDATEs) even though the evidence conclusively resolves it.
    # ----------------------------------------------------------------

    dry_run_conn = FakeConn([make_journal_row(id=1, state="executing")])
    dry_run_registry = mr.MutationAdapterRegistry().with_adapter(
        "fam.op_test", FakeAdapter(mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=False, observed_post_hash="dry_hash")),
    )
    out, err = io.StringIO(), io.StringIO()
    code = op.main(
        ["--journal-id", "1"],
        conn_factory=lambda: dry_run_conn, registry_factory=lambda: dry_run_registry,
        stdout=out, stderr=err,
    )
    check("dry run: exit code is EXIT_OK (0)", code == op.EXIT_OK, f"got {code}")
    check("dry run: stdout is labeled DRY RUN", "DRY RUN" in out.getvalue())
    check("dry run: stdout reports the would-be outcome", "new_state=completed" in out.getvalue(), f"got {out.getvalue()!r}")
    check("dry run: nothing was written to stderr", err.getvalue() == "", f"got {err.getvalue()!r}")
    check("dry run: the row was left COMPLETELY untouched (zero UPDATEs)", dry_run_conn.table[0]["state"] == "executing")
    check("dry run: no provenance was recorded on the untouched row", dry_run_conn.table[0]["reconciled_by_actor_type"] is None)
    check("dry run: the connection was closed exactly once", dry_run_conn.close_count == 1)

    # ----------------------------------------------------------------
    # 4) APPLY success path - real mutation_registry.reconcile_and_apply_
    #    journal_entry() is genuinely invoked; the hard-coded
    #    'cli_service' actor_type and the given --actor-ref both reach
    #    the durable row, in the SAME atomic UPDATE. Also exercises the
    #    255-char boundary (exactly at the limit - accepted, not rejected).
    # ----------------------------------------------------------------

    apply_conn = FakeConn([make_journal_row(id=1, state="executing")])
    apply_registry = mr.MutationAdapterRegistry().with_adapter(
        "fam.op_test", FakeAdapter(mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=False, observed_post_hash="apply_hash")),
    )
    boundary_actor_ref = "a" * 255
    out, err = io.StringIO(), io.StringIO()
    code = op.main(
        ["--journal-id", "1", "--apply", "--actor-ref", boundary_actor_ref],
        conn_factory=lambda: apply_conn, registry_factory=lambda: apply_registry,
        stdout=out, stderr=err,
    )
    check("apply: exit code is EXIT_OK (0)", code == op.EXIT_OK, f"got {code}")
    check("apply: stdout is labeled APPLIED", "APPLIED" in out.getvalue())
    check("apply: stdout echoes the hard-coded actor_type", "resolved_by_actor_type=cli_service" in out.getvalue())
    check("apply: stdout echoes the given --actor-ref", f"resolved_by_actor_ref={boundary_actor_ref}" in out.getvalue())
    check("apply: stdout reports the resolved outcome", "new_state=completed" in out.getvalue(), f"got {out.getvalue()!r}")
    check("apply: nothing was written to stderr", err.getvalue() == "", f"got {err.getvalue()!r}")
    check("apply: the row was durably updated to 'completed'", apply_conn.table[0]["state"] == "completed")
    check("apply: the hard-coded actor_type reached the durable row", apply_conn.table[0]["reconciled_by_actor_type"] == "cli_service")
    check(
        "apply: the EXACT 255-char --actor-ref reached the durable row unmodified",
        apply_conn.table[0]["reconciled_by_actor_ref"] == boundary_actor_ref,
    )
    check("apply: the connection was closed exactly once", apply_conn.close_count == 1)

    # ----------------------------------------------------------------
    # 5) APPLY resolving to 'reconciliation_required' (ambiguous
    #    evidence - a normal, non-exceptional outcome, NOT an error) -
    #    exit 0, and per _apply_outcome_under_lock()'s own contract, NO
    #    provenance is recorded on this branch even though --actor-ref
    #    was given.
    # ----------------------------------------------------------------

    ambiguous_conn = FakeConn([make_journal_row(id=1, state="executing")])
    ambiguous_registry = mr.MutationAdapterRegistry().with_adapter(
        "fam.op_test", FakeAdapter(mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)),
    )
    out, err = io.StringIO(), io.StringIO()
    code = op.main(
        ["--journal-id", "1", "--apply", "--actor-ref", "ops-runbook-42"],
        conn_factory=lambda: ambiguous_conn, registry_factory=lambda: ambiguous_registry,
        stdout=out, stderr=err,
    )
    check("ambiguous apply: exit code is STILL EXIT_OK (0) - reconciliation_required is not an error", code == op.EXIT_OK, f"got {code}")
    check("ambiguous apply: stdout reports new_state=reconciliation_required", "new_state=reconciliation_required" in out.getvalue())
    check("ambiguous apply: the row really was moved to reconciliation_required", ambiguous_conn.table[0]["state"] == "reconciliation_required")
    check(
        "ambiguous apply: NO provenance was recorded despite --actor-ref being given (matches "
        "_apply_outcome_under_lock()'s own contract for this branch)",
        ambiguous_conn.table[0]["reconciled_by_actor_type"] is None and ambiguous_conn.table[0]["reconciled_by_actor_ref"] is None,
    )

    # ----------------------------------------------------------------
    # 6) KNOWN reconciliation-domain errors - exit code 1, a single
    #    labeled ERROR line on stderr naming the real exception class,
    #    and the connection is STILL closed exactly once.
    # ----------------------------------------------------------------

    def _run_known_error_case(table, registry, argv, label, expected_exc_name):
        conn = FakeConn(table)
        out, err = io.StringIO(), io.StringIO()
        code = op.main(
            argv, conn_factory=lambda conn=conn: conn, registry_factory=lambda registry=registry: registry,
            stdout=out, stderr=err,
        )
        check(f"{label}: exit code is EXIT_RECONCILIATION_ERROR (1)", code == op.EXIT_RECONCILIATION_ERROR, f"got {code}")
        check(f"{label}: stderr names {expected_exc_name}", f"ERROR: {expected_exc_name}:" in err.getvalue(), f"got {err.getvalue()!r}")
        check(f"{label}: nothing was written to stdout", out.getvalue() == "", f"got {out.getvalue()!r}")
        check(f"{label}: the connection was still closed exactly once", conn.close_count == 1)

    _run_known_error_case(
        [], mr.MutationAdapterRegistry(), ["--journal-id", "999"],
        "nonexistent journal_id (dry run)", "JournalEntryNotFoundError",
    )
    _run_known_error_case(
        [], mr.MutationAdapterRegistry(), ["--journal-id", "999", "--apply", "--actor-ref", "someone"],
        "nonexistent journal_id (apply)", "JournalEntryNotFoundError",
    )
    _run_known_error_case(
        [make_journal_row(id=1, state="completed")], mr.MutationAdapterRegistry(), ["--journal-id", "1"],
        "already-terminal row", "UnsupportedJournalStateError",
    )
    _run_known_error_case(
        [make_journal_row(id=1, resource_key="case:case_unknown_family", action_family="fam.unregistered", state="executing")],
        mr.MutationAdapterRegistry(), ["--journal-id", "1"],
        "unregistered action_family", "UnknownActionFamilyError",
    )
    inconclusive_registry = mr.MutationAdapterRegistry().with_adapter(
        "fam.op_test", FakeAdapter(mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)),
    )
    _run_known_error_case(
        [make_journal_row(id=1, state="prepared", executing_at=None)], inconclusive_registry, ["--journal-id", "1"],
        "inconclusive evidence against a 'prepared'-origin row", "PreparedJournalUnresolvedError",
    )

    # LockReleaseAnomalyError - dry-run only, release_lock_session()
    # returns False with no other exception in flight.
    anomaly_conn = FakeConn([make_journal_row(id=1, state="executing")])
    anomaly_registry = mr.MutationAdapterRegistry().with_adapter(
        "fam.op_test", FakeAdapter(mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=False)),
    )
    ml.release_lock_session = lambda conn, advisory_lock_id: False
    try:
        out, err = io.StringIO(), io.StringIO()
        code = op.main(
            ["--journal-id", "1"], conn_factory=lambda: anomaly_conn, registry_factory=lambda: anomaly_registry,
            stdout=out, stderr=err,
        )
        check("lock-release anomaly: exit code is EXIT_RECONCILIATION_ERROR (1)", code == op.EXIT_RECONCILIATION_ERROR, f"got {code}")
        check("lock-release anomaly: stderr names LockReleaseAnomalyError", "ERROR: LockReleaseAnomalyError:" in err.getvalue(), f"got {err.getvalue()!r}")
        check("lock-release anomaly: the connection was still closed exactly once", anomaly_conn.close_count == 1)
    finally:
        ml.release_lock_session = _fake_release_lock_session

    # ----------------------------------------------------------------
    # 7) An UNEXPECTED exception (not in _KNOWN_RECONCILIATION_ERRORS -
    #    e.g. a genuine bug surfacing from registry_factory() itself)
    #    is DELIBERATELY NEVER caught by main() - it propagates with
    #    its own real traceback, never masked as a clean "ERROR: ..."
    #    line. The connection must still be closed (it was already
    #    opened via conn_factory() before registry_factory() ran).
    # ----------------------------------------------------------------

    unexpected_conn = FakeConn([make_journal_row(id=1, state="executing")])

    def _exploding_registry_factory():
        raise RuntimeError("a genuine bug, not a reconciliation-domain outcome")

    expect_raises(
        RuntimeError,
        lambda: op.main(
            ["--journal-id", "1"], conn_factory=lambda: unexpected_conn, registry_factory=_exploding_registry_factory,
            stdout=io.StringIO(), stderr=io.StringIO(),
        ),
        "an unexpected exception from registry_factory() propagates out of main() uncaught, never masked",
    )
    check("the connection was still closed even though registry_factory() raised", unexpected_conn.close_count == 1)

    # ----------------------------------------------------------------
    # 8) main()'s default argv/stdout/stderr actually fall back to
    #    sys.argv/sys.stdout/sys.stderr when omitted - proven by
    #    temporarily monkeypatching all three and confirming main()
    #    reads/writes through them without any of argv/stdout/stderr
    #    being passed explicitly.
    # ----------------------------------------------------------------

    _original_argv = sys.argv
    _original_stdout = sys.stdout
    _original_stderr = sys.stderr
    fake_stdout = io.StringIO()
    fake_stderr = io.StringIO()
    default_path_conn = FakeConn([make_journal_row(id=1, state="executing")])
    default_path_registry = mr.MutationAdapterRegistry().with_adapter(
        "fam.op_test", FakeAdapter(mr.ReconciliationEvidence(post_state_verified=True, pre_state_confirmed_unchanged=False)),
    )
    # NOTE: this project's own `check()` helper calls `print()`, which
    # itself reads the CURRENT `sys.stdout` at call time - so `check()`
    # must never be called while `sys.stdout` is monkeypatched below,
    # or its own PASS/FAIL diagnostic line would be silently swallowed
    # into `fake_stdout` right along with `main()`'s captured output,
    # instead of reaching this test run's real, visible output. Every
    # value `check()` needs is captured into a plain local variable
    # FIRST, `sys.argv`/`sys.stdout`/`sys.stderr` are restored in
    # `finally`, and ONLY THEN are the `check()` calls made below.
    try:
        sys.argv = ["ui.reconciliation_operator", "--journal-id", "1"]
        sys.stdout = fake_stdout
        sys.stderr = fake_stderr
        code = op.main(conn_factory=lambda: default_path_conn, registry_factory=lambda: default_path_registry)
        captured_stdout = fake_stdout.getvalue()
    finally:
        sys.argv = _original_argv
        sys.stdout = _original_stdout
        sys.stderr = _original_stderr

    check("main() with no argv/stdout/stderr falls back to sys.argv and returns EXIT_OK", code == op.EXIT_OK, f"got {code}")
    check("main()'s fallback wrote the dry-run report to the (monkeypatched) real sys.stdout", "DRY RUN" in captured_stdout, f"got {captured_stdout!r}")

finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.acquire_global_lock_session = _original_acquire_global
    ml.release_lock_session = _original_release


# ============================================================
# ROW 19C-2b/19C-2c/19C-3b - `_default_registry_factory()` merges Layer
# A's 10 case-scoped approval families, Layer B's 12 review_kinds
# (ROW 19C-3b SLICE 1: each registered under TWO exact routing keys -
# web `review.<kind>` and CLI `review.<kind>.cli` - pointing at the SAME
# single adapter instance per review_kind, so 12 logical review_kinds
# now occupy 24 routing keys, NOT 24 logical families), Row 18C's
# single `drafting_request.save` family, (ROW 19C-3b SLICE 2) the two
# fact/timeline `promotion.*` families, AND (ROW 19C-3c-i) the two
# deadline/timeline `generation.*` families into ONE registry - never
# called by any test above (which always injects its OWN fake
# `registry_factory`, per this module's own header comment), so this is
# the ONE place that ever exercises the REAL default factory for real,
# proving a human operator's real CLI invocation can reconcile a
# journal row from ANY of the five families (any of BOTH channels, for
# Layer B) through the SAME registry.
# ============================================================

_real_registry = op._default_registry_factory()
_real_families = _real_registry.known_action_families()
_approval_families = {f for f in _real_families if f.startswith("approval.")}
_review_families = {f for f in _real_families if f.startswith("review.")}
_review_families_cli = {f for f in _review_families if f.endswith(".cli")}
_review_families_web = _review_families - _review_families_cli
_drafting_request_families = {f for f in _real_families if f.startswith("drafting_request.")}
_promotion_families = {f for f in _real_families if f.startswith("promotion.")}
_generation_families = {f for f in _real_families if f.startswith("generation.")}

check(
    "_default_registry_factory(): the merged registry contains exactly Layer A's 10 "
    "'approval.*' families",
    len(_approval_families) == 10, f"got {sorted(_approval_families)}",
)
check(
    "ROW 19C-3b SLICE 1: the merged registry contains exactly Layer B's 24 'review.*' "
    "ROUTING KEYS (12 review_kinds x 2 channels - web + CLI)",
    len(_review_families) == 24, f"got {sorted(_review_families)}",
)
check(
    "ROW 19C-3b SLICE 1: exactly 12 of those are web-channel keys (no '.cli' suffix)",
    len(_review_families_web) == 12, f"got {sorted(_review_families_web)}",
)
check(
    "ROW 19C-3b SLICE 1: exactly 12 of those are CLI-channel keys (the '.cli' suffix)",
    len(_review_families_cli) == 12, f"got {sorted(_review_families_cli)}",
)
check(
    "ROW 19C-3b SLICE 1: the number of LOGICAL review_kinds is still 12, unchanged - stripping "
    "the '.cli' suffix from the CLI keys reproduces EXACTLY the web-key set (same review_kinds, "
    "not a different set of 12)",
    {f[: -len(".cli")] for f in _review_families_cli} == _review_families_web,
)
check(
    "_default_registry_factory(): the merged registry contains exactly Row 18C's 1 "
    "'drafting_request.*' family",
    len(_drafting_request_families) == 1, f"got {sorted(_drafting_request_families)}",
)
check(
    "ROW 19C-3b SLICE 2: the merged registry contains exactly the 2 'promotion.*' families "
    "(promotion.fact + promotion.timeline)",
    _promotion_families == {"promotion.fact", "promotion.timeline"},
    f"got {sorted(_promotion_families)}",
)
check(
    "ROW 19C-3c-i/3c-ii/3c-iii: the merged registry contains exactly the 8 'generation.*' "
    "families (generation.deadline + generation.timeline, deterministic, PLUS "
    "generation.issue_spotting + generation.evidence + generation.argument + "
    "generation.risk_strategy + generation.drafting, agent-gated, PLUS generation.fact_extraction, "
    "document-scoped agent-gated - THREE SEPARATE facade/adapter pairs, one merged namespace)",
    _generation_families == {
        "generation.deadline", "generation.timeline", "generation.issue_spotting", "generation.evidence",
        "generation.argument", "generation.risk_strategy", "generation.drafting",
        "generation.fact_extraction",
    },
    f"got {sorted(_generation_families)}",
)
check(
    "ROW 19C-3c-iii: the merged registry's total size is exactly 10 + 24 + 1 + 2 + 2 + 5 + 1 = 45 "
    "(no overlap, no family lost, no family duplicated) - this is a ROUTING-KEY count, "
    "distinct from the 33 LOGICAL action families (10 approval + 12 review + 1 "
    "drafting_request + 2 promotion + 2 deterministic-generation + 5 agent-generation + 1 "
    "fact-extraction-generation); the 'approval.*' bucket itself stays exactly 10",
    len(_real_families) == 45, f"got {len(_real_families)}",
)
check(
    "_default_registry_factory(): a representative Layer A family (approval.deadline) resolves "
    "to a real adapter",
    _real_registry.get("approval.deadline") is not None,
)
check(
    "_default_registry_factory(): a representative Layer B WEB family (review.evidence.candidate) "
    "resolves to a real adapter",
    _real_registry.get("review.evidence.candidate") is not None,
)
check(
    "ROW 19C-3b SLICE 1: the SAME review_kind's CLI routing key (review.evidence.candidate.cli) "
    "also resolves to a real adapter",
    _real_registry.get("review.evidence.candidate.cli") is not None,
)
check(
    "ROW 19C-3b SLICE 1: the web and CLI routing keys for the SAME review_kind resolve to the "
    "EXACT SAME adapter instance (one instance genuinely serves both channels)",
    _real_registry.get("review.evidence.candidate") is _real_registry.get("review.evidence.candidate.cli"),
)
check(
    "_default_registry_factory(): Row 18C's own family (drafting_request.save) resolves to a "
    "real adapter",
    _real_registry.get("drafting_request.save") is not None,
)
check(
    "ROW 19C-3b SLICE 2: promotion.fact and promotion.timeline each resolve to a real "
    "PromotionReconciliationAdapter instance (and to DIFFERENT instances - one per family)",
    _real_registry.get("promotion.fact") is not None
    and _real_registry.get("promotion.timeline") is not None
    and _real_registry.get("promotion.fact") is not _real_registry.get("promotion.timeline"),
)
check(
    "ROW 19C-3c-i: generation.deadline and generation.timeline each resolve to a real "
    "GenerationReconciliationAdapter instance (and to DIFFERENT instances - one per family)",
    _real_registry.get("generation.deadline") is not None
    and _real_registry.get("generation.timeline") is not None
    and _real_registry.get("generation.deadline") is not _real_registry.get("generation.timeline"),
)
check(
    "ROW 19C-3c-ii: each of the five agent-generation families resolves to a real "
    "AgentGenerationReconciliationAdapter instance, all mutually distinct",
    len({
        id(_real_registry.get(f"generation.{row_key}"))
        for row_key in ("issue_spotting", "evidence", "argument", "risk_strategy", "drafting")
    }) == 5
    and all(
        _real_registry.get(f"generation.{row_key}") is not None
        for row_key in ("issue_spotting", "evidence", "argument", "risk_strategy", "drafting")
    ),
)
check(
    "ROW 19C-3c-ii: the deterministic generation.deadline adapter and the agent-gated "
    "generation.argument adapter are DIFFERENT classes (two separate facade/adapter pairs, "
    "confirming generation_mutation_adapters.py was never extended)",
    type(_real_registry.get("generation.deadline")).__name__ == "GenerationReconciliationAdapter"
    and type(_real_registry.get("generation.argument")).__name__ == "AgentGenerationReconciliationAdapter",
)
check(
    "ROW 19C-3c-iii: generation.fact_extraction resolves to a real "
    "FactExtractionReconciliationAdapter instance - a THIRD, SEPARATE class from BOTH "
    "GenerationReconciliationAdapter and AgentGenerationReconciliationAdapter (confirming "
    "neither of the two LOCKED facade/adapter pairs was extended for this family)",
    _real_registry.get("generation.fact_extraction") is not None
    and type(_real_registry.get("generation.fact_extraction")).__name__ == "FactExtractionReconciliationAdapter"
    and type(_real_registry.get("generation.fact_extraction")).__name__
    not in (
        type(_real_registry.get("generation.deadline")).__name__,
        type(_real_registry.get("generation.argument")).__name__,
    ),
)


print(f"--- test_reconciliation_operator_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
