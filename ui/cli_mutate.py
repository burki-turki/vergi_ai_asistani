# ============================================================
# VERGİ AI - ROW 19C-3b SLICE 1: UNIVERSAL CLI MUTATION DISPATCHER.
#
# Closes the direct-`main()` CLI bypass for the 10 Layer A approval
# families and the 12 Layer B review families by giving them a SINGLE,
# coordinator-integrated CLI entry point that calls the EXACT SAME
# already-tested top-level functions the web routes call -
# `ui.services.approval_registry.case_scoped_review()`/`case_scoped_
# approve()` and `ui.services.review_registry.get_review_record()`/
# `apply_transition()` - never a domain writer (`run_approve()`/
# `apply_review_transition()`) directly, and never a re-implementation
# of any authz/journal/lock/precondition logic those functions already
# own. `drafting_request.save` is explicitly OUT OF SCOPE for this
# Slice (see the corrected scope report - it has no legacy CLI bypass
# to close).
#
# ACTOR IDENTITY MODEL (trusted-local-shell, NOT cryptographic OS
# identity): `--actor-user-id` names a real `iam.users` row, verified
# fresh (exists, not disabled, has an active case assignment with the
# needed capability) on every invocation via `ui.services.cli_authz.
# CliActorAuthzRepository` - see that module's own header comment for
# the full rationale and for why real OS/service-identity enforcement
# is explicitly deferred to Row 19D. Mirrors `scripts/iam_admin.py`'s
# own `--actor-user-id` precedent.
#
# TWO SUBCOMMANDS, mirroring the shape (and reusing the exit-code
# discipline) of `ui/reconciliation_operator.py`:
#   python -m ui.cli_mutate approval --case ID --row-key KEY \
#       --actor-user-id N [--approve --expected-hash HASH]
#   python -m ui.cli_mutate review --case ID --review-kind KIND \
#       --record-id ID --actor-user-id N \
#       [--apply --target-state STATE --note TEXT --expected-hash HASH]
#
# Without `--approve`/`--apply`: PREVIEW mode - prints the current
# pending/canonical hash an operator needs for the corresponding apply
# invocation. Zero mutation connection, zero lock, zero journal access -
# only `case_scoped_review()`/`get_review_record()` (both pure reads,
# no authz of their own) are called, gated by THIS dispatcher's own
# outer `authorize_case_access(..., "read", ...)` check first (mirrors
# `ui/main.py`'s GET routes doing the identical thing before calling the
# same two functions).
#
# With `--approve`/`--apply`: the dispatcher performs NO authorization
# logic of its own beyond building the CLI principal/repository - it
# calls `case_scoped_approve()`/`apply_transition()` exactly as
# `ui/main.py`'s POST routes do, passing `principal=`/`authz_repository=`
# so THEIR OWN existing dual (outer-then-inner) authorization,
# composite-precondition, idempotency and journal logic runs unchanged.
# `--expected-hash` is ALWAYS the operator's own explicit claim (from a
# prior preview run) - NEVER recomputed or silently substituted by this
# dispatcher; a stale/mismatched value is refused by the facade's own
# existing precondition check, exactly as for the web path.
#
# NO force/bypass/unsafe flag exists anywhere on this parser, by
# construction - see the corrected scope report's own binding decision.
# No CLI argument accepts a `reviewer_ref`/action_family/channel value -
# the review subcommand always requests
# `review_registry.LOCAL_CLI_REVIEWER_REF` internally, unconditionally.
# ============================================================

from __future__ import annotations

import argparse
import sys

EXIT_OK = 0
EXIT_DOMAIN_ERROR = 1
EXIT_USAGE_ERROR = 2

# Rendered identically for EVERY authorization-shaped denial - a
# nonexistent actor, a disabled actor, an actor with no assignment for
# this case, and an actor whose assigned role lacks the requested
# capability are ALL existence-blind from this CLI's own output (never
# distinguished by class name/message - see `_is_authz_denial()`),
# mirroring `ui.services.authz.CaseAccessDeniedError`'s own existence-
# blind contract exactly.
_AUTHZ_DENIAL_MESSAGE = (
    "ERROR: yetkisiz veya bilinmeyen case/actor/kayıt - erişim reddedildi "
    "(sıfır mutasyon, sıfır lock, sıfır journal kaydı)."
)


class _ExitSignal(Exception):
    def __init__(self, code: int, message: str | None = None):
        self.code = code
        self.message = message
        super().__init__(message or f"exit({code})")


class _NonExitingArgumentParser(argparse.ArgumentParser):
    """Mirrors `ui.reconciliation_operator._NonExitingArgumentParser`
    exactly - raises `_ExitSignal` instead of calling the real
    `sys.exit()`/writing to the real `sys.stderr`, so this module's own
    isolated tests can exercise every argparse-level usage-error path
    in-process, repeatedly, without terminating the test runner."""

    def error(self, message: str) -> None:  # noqa: D102
        raise _ExitSignal(EXIT_USAGE_ERROR, self.format_usage() + f"{self.prog}: error: {message}\n")

    def exit(self, status: int = 0, message: str | None = None) -> None:  # noqa: D102
        raise _ExitSignal(status, message)


def _build_arg_parser():
    # Lazy import - keeps `import ui.cli_mutate` itself free of any
    # hard dependency on psycopg/case-data being importable at module
    # load time, matching this project's own lazy-import discipline
    # (ui.services.db, ui.reconciliation_operator).
    from ui.services import approval_registry as _approval_registry
    from ui.services import review_registry as _review_registry

    parser = _NonExitingArgumentParser(
        prog="python -m ui.cli_mutate",
        description=(
            "Row 19C-3b Slice 1 - coordinator-integrated CLI for the 10 Layer A "
            "approval families and 12 Layer B review families. drafting_request.save "
            "is NOT covered by this dispatcher."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    approval_parser = subparsers.add_parser("approval", help="Layer A case-scoped approval")
    approval_parser.add_argument("--case", dest="case_id", required=True)
    approval_parser.add_argument(
        "--row-key", dest="row_key", required=True,
        choices=sorted(_approval_registry.CASE_SCOPED_ROWS_BY_KEY.keys()),
    )
    approval_parser.add_argument("--actor-user-id", dest="actor_user_id", required=True, type=int)
    approval_parser.add_argument("--approve", action="store_true", default=False)
    approval_parser.add_argument(
        "--expected-hash", dest="expected_hash", default=None,
        help="REQUIRED with --approve (rejected without it): the pending file's sha256, "
        "as printed by a prior preview (no --approve) run of this same command.",
    )

    review_parser = subparsers.add_parser("review", help="Layer B record-level review")
    review_parser.add_argument("--case", dest="case_id", required=True)
    review_parser.add_argument(
        "--review-kind", dest="review_kind", required=True,
        choices=sorted(_review_registry.REVIEW_KIND_REGISTRY.keys()),
    )
    review_parser.add_argument("--record-id", dest="record_id", required=True)
    review_parser.add_argument("--actor-user-id", dest="actor_user_id", required=True, type=int)
    review_parser.add_argument("--apply", action="store_true", default=False)
    review_parser.add_argument("--target-state", dest="target_state", default=None)
    review_parser.add_argument("--note", dest="note", default=None)
    review_parser.add_argument(
        "--expected-hash", dest="expected_hash", default=None,
        help="REQUIRED with --apply (rejected without it): the canonical file's sha256, "
        "as printed by a prior preview (no --apply) run of this same command.",
    )

    return parser


def _validate_approval_args(args, *, stderr) -> int | None:
    """Pure, zero-connection usage-shape checks specific to the
    `--approve`/no-`--approve` pairing. Returns an exit code if usage is
    invalid (caller must return it immediately, without opening
    anything), or None if usage is valid."""
    if args.approve and args.expected_hash is None:
        stderr.write("error: --approve requires --expected-hash\n")
        return EXIT_USAGE_ERROR
    if args.expected_hash is not None and not args.approve:
        stderr.write("error: --expected-hash is only meaningful together with --approve\n")
        return EXIT_USAGE_ERROR
    return None


def _validate_review_args(args, *, stderr) -> int | None:
    """Pure, zero-connection usage-shape checks specific to the
    `--apply`/no-`--apply` pairing, INCLUDING the target_state
    membership check (`review_registry.get_allowed_targets()` - the
    SAME pure function `apply_transition()` itself re-checks; doing it
    here too costs nothing and avoids wasting an authz connection on a
    request that is usage-invalid regardless of actor)."""
    from ui.services import review_registry as _review_registry

    required_with_apply = {
        "--target-state": args.target_state,
        "--note": args.note,
        "--expected-hash": args.expected_hash,
    }
    if args.apply:
        missing = [flag for flag, value in required_with_apply.items() if value is None]
        if missing:
            stderr.write(f"error: --apply requires {', '.join(missing)}\n")
            return EXIT_USAGE_ERROR
        allowed_targets = _review_registry.get_allowed_targets(args.review_kind)
        if args.target_state not in allowed_targets:
            stderr.write(
                f"error: --target-state={args.target_state!r} is not one of "
                f"{sorted(allowed_targets)!r} for --review-kind={args.review_kind!r}\n"
            )
            return EXIT_USAGE_ERROR
    else:
        given = [flag for flag, value in required_with_apply.items() if value is not None]
        if given:
            stderr.write(f"error: {', '.join(given)} are only meaningful together with --apply\n")
            return EXIT_USAGE_ERROR
    return None


def _default_authz_conn_factory():
    """Real production authz connection factory - lazy-imported so
    `import ui.cli_mutate` never itself requires psycopg (matches
    `ui.services.db`'s own discipline). Returns the SAME plain,
    `autocommit=False` connection shape `ui.services.mutation_approval_
    facade._default_authz_repository()` already uses for the web path -
    NEVER the session-lock-capable connection the mutation/journal side
    uses (see this module's own header comment on why the two must stay
    separate)."""
    from ui.services import db as _db

    return _db.get_connection()


def main(
    argv: list[str] | None = None,
    *,
    authz_conn_factory=None,
    mutation_conn_factory=None,
    stdout=None,
    stderr=None,
) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    authz_conn_factory = _default_authz_conn_factory if authz_conn_factory is None else authz_conn_factory

    parser = _build_arg_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except _ExitSignal as exit_signal:
        if exit_signal.message:
            stderr.write(exit_signal.message)
        return exit_signal.code

    if args.command == "approval":
        usage_error = _validate_approval_args(args, stderr=stderr)
    else:
        usage_error = _validate_review_args(args, stderr=stderr)
    if usage_error is not None:
        return usage_error

    # ============================================================
    # AUTHZ CONNECTION - completely separate from the mutation/journal
    # connection the facade opens for itself (see this module's own
    # header comment). Opened exactly once per invocation, closed in
    # `finally` no matter what happens below.
    # ============================================================
    from ui.services import authz as _authz
    from ui.services import cli_authz as _cli_authz

    authz_conn = authz_conn_factory()
    try:
        try:
            principal = _cli_authz.build_cli_principal(authz_conn, args.actor_user_id)
        except (_cli_authz.CliActorNotFoundError, _cli_authz.CliActorDisabledError):
            stderr.write(_AUTHZ_DENIAL_MESSAGE + "\n")
            return EXIT_DOMAIN_ERROR

        repository = _cli_authz.CliActorAuthzRepository(authz_conn)

        try:
            if args.command == "approval":
                outcome = _run_approval(
                    args, principal=principal, repository=repository,
                    mutation_conn_factory=mutation_conn_factory,
                )
            else:
                outcome = _run_review(
                    args, principal=principal, repository=repository,
                    mutation_conn_factory=mutation_conn_factory,
                )
        except _authz.CaseAccessDeniedError:
            stderr.write(_AUTHZ_DENIAL_MESSAGE + "\n")
            return EXIT_DOMAIN_ERROR
        except Exception as error:
            # Only a RECOGNIZED domain-level error is reported as a
            # clean, single-line message - anything else re-raises
            # unchanged, with its own real traceback, exactly like
            # `ui.reconciliation_operator.py`'s own discipline (a
            # genuinely unexpected failure must never be masked behind
            # a falsely-clean error line).
            if not _is_known_domain_error(error):
                raise
            stderr.write(f"ERROR: {type(error).__name__}: {error}\n")
            return EXIT_DOMAIN_ERROR

        stdout.write(outcome)
        return EXIT_OK
    finally:
        authz_conn.close()


def _run_approval(args, *, principal, repository, mutation_conn_factory) -> str:
    from ui.services import approval_registry as _approval_registry
    from ui.services import authz as _authz

    if not args.approve:
        # PREVIEW - this dispatcher's OWN outer "read" authorization,
        # mirroring ui/main.py's GET route exactly (case_scoped_review()
        # performs no authz of its own).
        resolved_case_id = _authz.authorize_case_access(
            principal, args.case_id, "read", repository=repository,
        )
        review = _approval_registry.case_scoped_review(args.row_key, resolved_case_id)
        return (
            f"PREVIEW row_key={args.row_key} case_id={resolved_case_id}\n"
            f"pending_hash={review['pending_hash']}\n"
            f"validation_valid={review['validation'].get('valid')}\n"
            "Onaylamak için: python -m ui.cli_mutate approval --case "
            f"{resolved_case_id} --row-key {args.row_key} --actor-user-id {args.actor_user_id} "
            f"--approve --expected-hash {review['pending_hash']}\n"
        )

    # APPLY - zero authz logic of our own; case_scoped_approve() runs
    # its OWN outer-then-inner dual authorization, using OUR principal/
    # repository, before its own mutation connection is ever opened.
    result = _approval_registry.case_scoped_approve(
        args.row_key, args.case_id, args.expected_hash,
        principal=principal, authz_repository=repository, conn_factory=mutation_conn_factory,
    )
    return (
        f"APPLIED row_key={args.row_key}\n"
        f"canonical_path={result['canonical_path']}\n"
        f"canonical_hash={result['canonical_hash']}\n"
        f"audit_path={result['audit_path']}\n"
    )


def _run_review(args, *, principal, repository, mutation_conn_factory) -> str:
    from ui.services import review_registry as _review_registry
    from ui.services import authz as _authz

    if not args.apply:
        # PREVIEW - this dispatcher's OWN outer "read" authorization,
        # mirroring ui/main.py's GET route exactly (get_review_record()
        # performs no authz of its own).
        resolved_case_id = _authz.authorize_case_access(
            principal, args.case_id, "read", repository=repository,
        )
        found = _review_registry.get_review_record(args.review_kind, resolved_case_id, args.record_id)
        allowed_targets = sorted(_review_registry.get_allowed_targets(args.review_kind))
        return (
            f"PREVIEW review_kind={args.review_kind} case_id={resolved_case_id} "
            f"record_id={args.record_id}\n"
            f"canonical_hash={found['canonical_hash']}\n"
            f"allowed_target_states={allowed_targets}\n"
            "Uygulamak için: python -m ui.cli_mutate review --case "
            f"{resolved_case_id} --review-kind {args.review_kind} --record-id {args.record_id} "
            f"--actor-user-id {args.actor_user_id} --apply --target-state <STATE> "
            f"--note <NOTE> --expected-hash {found['canonical_hash']}\n"
        )

    # APPLY - zero authz logic of our own; apply_transition() runs its
    # OWN outer-then-inner dual authorization, using OUR principal/
    # repository, before its own mutation connection is ever opened.
    # `reviewer_ref` is ALWAYS `LOCAL_CLI_REVIEWER_REF` here,
    # unconditionally - never taken from any CLI argument.
    result = _review_registry.apply_transition(
        args.review_kind, args.case_id, args.record_id, args.target_state, args.note, args.expected_hash,
        principal=principal, authz_repository=repository, conn_factory=mutation_conn_factory,
        reviewer_ref=_review_registry.LOCAL_CLI_REVIEWER_REF,
    )
    return (
        f"APPLIED review_kind={args.review_kind} record_id={args.record_id}\n"
        f"canonical_path={result['canonical_path']}\n"
        f"post_sha256={result['post_sha256']}\n"
        f"previous_state={result['previous_state']}\n"
        f"new_state={result['new_state']}\n"
        f"audit_path={result['audit_path']}\n"
    )


def _is_known_domain_error(error: BaseException) -> bool:
    """True iff `error` is one of the domain-level exception classes
    this CLI recognizes and reports as a clean, single-line
    `ERROR: ClassName: message` (exit EXIT_DOMAIN_ERROR) - never a raw
    traceback. Resolved lazily, INSIDE this function, on every call -
    NOT cached at module import time - so `import ui.cli_mutate` itself
    never requires these mutation-side modules to already be importable
    (matches this project's own lazy-import discipline).

    `ApprovalUiError`/`ReviewUiError` are BASE classes covering every
    Layer A/Layer B domain exception already defined in
    `ui.services.common` (`PendingNotFoundError`, `StaleViewError`,
    `PreconditionRaceDetectedError`, `UnknownCaseError`,
    `ReviewRecordNotFoundError`, `ReviewStaleViewError`,
    `ReviewPreconditionRaceDetectedError`, `InvalidReviewNoteError`, the
    facades' own `ReviewAuditBindingVerificationFailedError`/
    `ReviewResolvedCaseIdMismatchError`, etc.) - confirmed by reading
    `ui/services/common.py`'s own class hierarchy, never assumed.
    `AuditBindingVerificationFailedError`/`ResolvedCaseIdMismatchError`
    (Layer A) are plain `Exception` subclasses (NOT `ApprovalUiError`),
    so they are listed explicitly. `MutationCoordinatorError` is the
    base for every `ui.services.mutation_coordinator` exception
    (`ResourceGatedError`, `IdempotencyConflictError`,
    `PriorAttemptFailedError`, `JournalExecutingTransitionFailedError`,
    `JournalCompletionUncertainError`,
    `JournalReconciliationTransitionFailedError`).

    Anything NOT covered here (and not `CaseAccessDeniedError`, handled
    separately for existence-blindness in `main()`) is deliberately left
    to propagate uncaught with its own real traceback - a genuinely
    unexpected failure must never be masked behind a falsely-clean error
    line, matching `ui.reconciliation_operator.py`'s own discipline."""
    from ui.services.common import ApprovalUiError, ReviewUiError
    from ui.services.mutation_approval_facade import (
        AuditBindingVerificationFailedError,
        ResolvedCaseIdMismatchError,
    )
    from ui.services.mutation_coordinator import MutationCoordinatorError

    known = (
        ApprovalUiError,
        ReviewUiError,
        AuditBindingVerificationFailedError,
        ResolvedCaseIdMismatchError,
        MutationCoordinatorError,
    )
    return isinstance(error, known)


if __name__ == "__main__":
    sys.exit(main())
