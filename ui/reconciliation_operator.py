# ============================================================
# VERGİ AI - ROW 19C-2a STEP 4: RECONCILIATION OPERATOR CLI.
#
# The FIRST caller of `ui.services.mutation_registry.
# inspect_reconciliation()` / `reconcile_and_apply_journal_entry()`
# that a human operator ever runs directly (every OTHER caller in this
# project is test code). Deliberately thin: 100% of the actual
# reconciliation decision/apply logic lives in
# `ui.services.mutation_registry` (this module owns none of it) - this
# file is only argument parsing, exit-code/output-formatting
# discipline, and wiring a real connection + a real adapter registry
# into that module's own two public entry points.
#
# USAGE:
#   python3 -m ui.reconciliation_operator --journal-id ID
#       DRY RUN (default mode - no `--apply` flag at all): calls
#       `inspect_reconciliation()`. Reports exactly what a REAL
#       `--apply` run would decide, against LIVE evidence (a real
#       adapter's `gather_evidence()` genuinely runs), under the SAME
#       session-level resource lock a real apply would take - but
#       issues ZERO UPDATEs against `mutation.mutation_journal`,
#       always, regardless of what it finds.
#
#   python3 -m ui.reconciliation_operator --journal-id ID --apply --actor-ref REF
#       REAL APPLY: calls `reconcile_and_apply_journal_entry()` with
#       `resolved_by_actor_type` hard-coded to `'cli_service'` for v1
#       (see db/migrations/0004_mutation_reconciliation_provenance.sql's
#       own column-1 comment: real OS/service-identity enforcement
#       behind this label is explicitly deferred to Row 19D+ - this
#       CLI only ever records a caller-declared, technical provenance
#       label) and `resolved_by_actor_ref` set to the given `--actor-ref`
#       value. Durably resolves the row (or raises one of the same
#       reconciliation-domain exceptions `inspect_reconciliation()`
#       could have raised for the exact same journal_id).
#
#       `--actor-ref` is REQUIRED with `--apply` (every real apply run
#       through this operator must be attributable to something,
#       even if only a technical CLI-invocation label - never an
#       anonymous reconciliation) and REJECTED without it (there would
#       be nothing to attribute it to; the dry-run path never writes
#       provenance at all, so passing it there would silently do
#       nothing, which this CLI refuses to allow silently). Pre-
#       validated here against the EXACT same shape
#       0004_mutation_reconciliation_provenance.sql's own
#       `mutation_journal_reconciled_actor_ref_shape` CHECK constraint
#       enforces (non-blank after trimming, <=255 chars) - so a
#       malformed `--actor-ref` is rejected immediately, as a clean
#       usage error, rather than surfacing later as a raw CHECK-
#       constraint SQL error from deep inside `_apply_outcome_under_
#       lock()`.
#
# EXIT CODES:
#   0 - success (a dry-run report was produced, or a real apply
#       resolved the row) - printed to the given `stdout`.
#   1 - a KNOWN reconciliation-domain failure (the journal_id does not
#       exist, the row is not in a reconciliation-eligible state, the
#       adapter's evidence does not conclusively resolve a `prepared`-
#       origin row, the dry-run's own lock-release anomaly, an
#       unregistered action_family, or - `--apply` only - the guarded
#       UPDATE itself reporting an unexpected rowcount) - printed as a
#       single labeled `ERROR: <ExceptionClassName>: <message>` line to
#       the given `stderr`. This is a NORMAL, EXPECTED way for this CLI
#       to end for a row that genuinely cannot (yet) be resolved - it
#       is not a bug in this tool.
#   2 - a USAGE error (missing/malformed arguments, an invalid
#       `--journal-id`, `--actor-ref` given without `--apply`, or
#       `--apply` given without `--actor-ref`) - printed to `stderr`
#       before any connection is even opened.
#
#   ANY OTHER exception (a genuinely unexpected failure - a database
#   misconfiguration, a bug in an adapter, a bug in this project's own
#   registry/lock code) is DELIBERATELY NEVER caught here - it
#   propagates with its own real traceback. This operator's fail-
#   closed discipline is about never MASKING a genuine problem behind
#   a falsely-clean "error: ..." line, exactly the same principle
#   `ui.services.mutation_coordinator`'s own `_log_critical_safely`
#   non-masking discipline follows for a different failure class.
#
# DEPENDENCY INJECTION FOR TESTABILITY: `main()` accepts optional
# `conn_factory` / `registry_factory` / `stdout` / `stderr` parameters.
# `ui/tests/test_reconciliation_operator_isolated.py` ALWAYS supplies
# its own fake `conn_factory` (a fake connection, no real database) and
# its own fake `registry_factory` (a `MutationAdapterRegistry` built
# from ui.services.mutation_registry.py`'s test-only adapter shapes) -
# it never reaches `_default_conn_factory` / `_default_registry_factory`
# below at all. Only a REAL CLI invocation
# (`python3 -m ui.reconciliation_operator ...`) ever calls those two
# real-wiring functions.
#
# ROW 19C-2a STEP 6 FORWARD REFERENCE: `_default_registry_factory()`
# below imports `ui.services.mutation_approval_adapters` - a module
# THIS STEP (Step 4) does not create; it is created by a LATER step of
# this same Row 19C-2a implementation (Step 6: approval facade +
# 10-family adapters) and is expected to expose a
# `build_production_registry() -> MutationAdapterRegistry` function.
# The import is lazy (inside the function body, never at this module's
# top level) specifically so THIS file - and its own isolated test -
# are both fully authorable and independently testable NOW, before
# that module exists at all; only a real CLI invocation ever reaches
# this function, and only once Step 6 has landed.
# ============================================================

from __future__ import annotations

import argparse
import sys

from ui.services import mutation_registry as mr

EXIT_OK = 0
EXIT_RECONCILIATION_ERROR = 1
EXIT_USAGE_ERROR = 2

# ROW 19C-2a: matches db/migrations/0004_mutation_reconciliation_provenance.sql's
# own constraint-1 comment - this CLI is 'cli_service' for v1,
# unconditionally; 'iam_user' is reserved for a future browser-driven
# reconciliation UI (Row 19D+ scope) this file does not implement.
_ACTOR_TYPE_CLI_SERVICE = "cli_service"

# ROW 19C-2a: the reconciliation-DOMAIN exceptions this CLI recognizes
# and reports as a clean, single-line `ERROR: ...` (exit code
# EXIT_RECONCILIATION_ERROR) rather than letting propagate as a raw
# traceback - every one of these is a documented, EXPECTED outcome of
# calling `inspect_reconciliation()`/`reconcile_and_apply_journal_entry()`
# for a specific, identifiable reason (see each class's own docstring
# in ui.services.mutation_registry), never a sign of a bug in this
# tool or in that module. Anything NOT in this tuple is deliberately
# left to propagate uncaught - see the module docstring's EXIT CODES
# section.
_KNOWN_RECONCILIATION_ERRORS = (
    mr.JournalEntryNotFoundError,
    mr.ResourceKeyMismatchError,
    mr.UnsupportedJournalStateError,
    mr.PreparedJournalUnresolvedError,
    mr.LockReleaseAnomalyError,
    mr.ReconciliationApplyFailedError,
    mr.UnknownActionFamilyError,
)


class _ExitSignal(Exception):
    """Raised by `_NonExitingArgumentParser` instead of that parser
    calling `sys.exit()` for real. `main()` catches this and converts
    it into a plain return code plus a write to the CALLER-supplied
    `stderr` - never the real `sys.exit()`/`sys.stderr`, so
    `ui/tests/test_reconciliation_operator_isolated.py` can exercise
    every argparse-level usage-error path in-process, repeatedly,
    without ever terminating the test runner itself or depending on
    which stream is 'real' stderr at the time."""

    def __init__(self, code: int, message: str | None = None):
        self.code = code
        self.message = message
        super().__init__(message or f"exit({code})")


class _NonExitingArgumentParser(argparse.ArgumentParser):
    """`argparse.ArgumentParser.error()`/`.exit()` both call the real
    `sys.exit()` and print straight to the real `sys.stderr` by
    default - wrong for a function this project's own isolated test
    suite must be able to call in-process. This override raises
    `_ExitSignal` instead, preserving the exact same observable
    contract a real CLI invocation gets (exit code 2, a usage message)
    once `main()` catches it and writes that message to the
    CALLER-supplied `stderr` instead."""

    def error(self, message: str) -> None:  # noqa: D102 - argparse's own signature
        raise _ExitSignal(EXIT_USAGE_ERROR, self.format_usage() + f"{self.prog}: error: {message}\n")

    def exit(self, status: int = 0, message: str | None = None) -> None:  # noqa: D102
        raise _ExitSignal(status, message)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = _NonExitingArgumentParser(
        prog="python3 -m ui.reconciliation_operator",
        description=(
            "Row 19C-2a reconciliation operator: inspects (dry run, default) or applies "
            "(--apply) the reconciliation decision for one mutation.mutation_journal row."
        ),
    )
    parser.add_argument(
        "--journal-id", type=int, required=True,
        help="the mutation.mutation_journal row id to inspect or reconcile",
    )
    parser.add_argument(
        "--apply", action="store_true", default=False,
        help="apply the reconciliation decision for real (default: dry run only, zero UPDATEs)",
    )
    parser.add_argument(
        "--actor-ref", default=None,
        help="REQUIRED with --apply (rejected without it): a technical provenance label for this "
        "apply run, recorded as reconciled_by_actor_ref (actor_type is fixed to 'cli_service')",
    )
    return parser


def _validate_actor_ref_shape(actor_ref: str) -> str | None:
    """Mirrors 0004_mutation_reconciliation_provenance.sql's own
    `mutation_journal_reconciled_actor_ref_shape` CHECK constraint
    exactly (non-blank after trimming, <=255 chars) - returns an error
    message string if invalid, or None if the value is acceptable.
    Pre-validating here means a malformed `--actor-ref` is rejected as
    a clean, immediate usage error instead of surfacing later as a raw
    CHECK-constraint SQL error from deep inside `_apply_outcome_under_
    lock()`."""
    if not actor_ref.strip():
        return "--actor-ref must not be blank/whitespace-only"
    if len(actor_ref) > 255:
        return f"--actor-ref must be at most 255 characters (got {len(actor_ref)})"
    return None


def _default_conn_factory():
    """Real production connection factory - lazy-imported (never at
    this module's top level) so importing `ui.reconciliation_operator`
    itself never requires psycopg to be installed (matches
    `ui.services.db`'s own lazy-import discipline). Returns the SAME
    autocommit, session-lock-capable connection shape `ui.services.
    mutation_coordinator` itself uses - `inspect_reconciliation()`/
    `reconcile_and_apply_journal_entry()` both need a session-level
    (not transaction-level) advisory lock, exactly like a real
    mutation does."""
    from ui.services import db as _db  # lazy import - see docstring above

    return _db.get_session_lock_connection()


def _default_registry_factory() -> mr.MutationAdapterRegistry:
    """ROW 19C-2a STEP 6 / ROW 19C-2b / ROW 19C-2c: builds ONE merged
    registry covering EVERY production mutation family this coordinator
    serves - Layer A's 10 case-scoped approval families
    (`mutation_approval_adapters.build_production_registry()`) PLUS
    Layer B's 12 review_kind record-level review families
    (`review_mutation_adapters.register_into()`) PLUS Row 18C's single
    `drafting_request.save` family (`drafting_request_mutation_adapters.
    register_into()`) - all folded onto the SAME registry rather than
    building separate ones - so a human operator can reconcile ANY
    journal row this project produces, regardless of family, through
    this ONE CLI. NEVER called by `ui/tests/test_reconciliation_
    operator_isolated.py` (which always injects its own fake
    `registry_factory`) - only a real CLI invocation reaches this."""
    from ui.services import mutation_approval_adapters  # lazy import - see module docstring
    from ui.services import review_mutation_adapters  # lazy import - see module docstring
    from ui.services import drafting_request_mutation_adapters  # lazy import - see module docstring

    registry = mutation_approval_adapters.build_production_registry()
    registry = review_mutation_adapters.register_into(registry)
    return drafting_request_mutation_adapters.register_into(registry)


def _format_outcome_line(outcome: mr.ReconciliationOutcome) -> str:
    return (
        f"  new_state={outcome.new_state} resolution_code={outcome.resolution_code} "
        f"observed_post_hash={outcome.observed_post_hash}\n"
    )


def main(
    argv: list[str] | None = None,
    *,
    conn_factory=None,
    registry_factory=None,
    stdout=None,
    stderr=None,
) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    conn_factory = _default_conn_factory if conn_factory is None else conn_factory
    registry_factory = _default_registry_factory if registry_factory is None else registry_factory

    parser = _build_arg_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except _ExitSignal as exit_signal:
        if exit_signal.message:
            stderr.write(exit_signal.message)
        return exit_signal.code

    # ROW 19C-2a: --apply/--actor-ref are a BOTH-or-NEITHER pair at the
    # CLI level too, mirroring 0004's own actor_type/actor_ref
    # both-or-neither CHECK constraint in spirit (there the pairing is
    # type/ref; here it is apply-mode/ref, for the same underlying
    # reason - a half-specified provenance intent is never silently
    # accepted).
    if args.apply and args.actor_ref is None:
        stderr.write(
            "error: --apply requires --actor-ref (every real reconciliation apply through this "
            "operator must be attributable to something)\n"
        )
        return EXIT_USAGE_ERROR
    if args.actor_ref is not None and not args.apply:
        stderr.write(
            "error: --actor-ref is only meaningful together with --apply (a dry-run inspection "
            "never records provenance - passing --actor-ref here would silently do nothing)\n"
        )
        return EXIT_USAGE_ERROR
    if args.actor_ref is not None:
        shape_error = _validate_actor_ref_shape(args.actor_ref)
        if shape_error is not None:
            stderr.write(f"error: {shape_error}\n")
            return EXIT_USAGE_ERROR
    if args.journal_id <= 0:
        stderr.write(f"error: --journal-id must be a positive integer, got {args.journal_id}\n")
        return EXIT_USAGE_ERROR

    conn = conn_factory()
    try:
        registry = registry_factory()
        try:
            if args.apply:
                outcome = mr.reconcile_and_apply_journal_entry(
                    conn, args.journal_id, registry,
                    resolved_by_actor_type=_ACTOR_TYPE_CLI_SERVICE,
                    resolved_by_actor_ref=args.actor_ref,
                )
                stdout.write(
                    f"APPLIED journal_id={args.journal_id} "
                    f"resolved_by_actor_type={_ACTOR_TYPE_CLI_SERVICE} resolved_by_actor_ref={args.actor_ref}\n"
                )
            else:
                outcome = mr.inspect_reconciliation(conn, args.journal_id, registry)
                stdout.write(
                    f"DRY RUN journal_id={args.journal_id} (no changes applied - pass "
                    f"--apply --actor-ref <ref> to apply for real)\n"
                )
            stdout.write(_format_outcome_line(outcome))
            return EXIT_OK
        except _KNOWN_RECONCILIATION_ERRORS as error:
            stderr.write(f"ERROR: {type(error).__name__}: {error}\n")
            return EXIT_RECONCILIATION_ERROR
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
