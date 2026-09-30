# ============================================================
# VERGİ AI - PILOT READINESS ADIM 9D: CONCIERGE AVUKAT DEADLINE RAPORU.
#
#   python -m ui.deadline_report --case <case_id> --actor-user-id <N>
#       [--output <mutlak, repo-dışı, henüz var olmayan dosya yolu>]
#
# TAMAMEN SALT-OKUNUR. Onaylanmış canonical
# `data/cases/<case_id>/deadlines/deadline.json` dosyasından avukatın
# okuyabileceği deterministik, Türkçe bir özet üretir. Pending dosyası
# HİÇ okunmaz; case_view/web arayüzü kapsam dışıdır. Hiçbir repo/case
# dosyası yazılmaz, hiçbir DB satırı yazılmaz, ağ/LLM çağrısı yoktur.
# Tek yazma, operatörün açıkça verdiği `--output` hedefidir: mutlak,
# repo DIŞI, parent'ı önceden mevcut, `x` (yalnız-oluştur) semantiği,
# UTF-8 BOM'suz, yalnız LF.
#
# YETKİLENDİRME (PostgreSQL ZORUNLU - offline/bypass modu YOKTUR):
# `ui.services.cli_authz.build_cli_principal()` + LOCKED
# `ui.services.authz.authorize_case_access(..., "read", ...)` (taze
# authz_version/disabled kontrolü, case_id sözdizimi, aktif assignment,
# `paths.resolve_case_id` containment) + ek olarak aktif assignment
# rolünün tam olarak `lawyer` olması (analyst REDDEDİLİR). Hiçbir LOCKED
# modül değiştirilmez; yalnız import edilir. Bağlantı `read_only=True`
# yapılır ve oturumun gerçekten `transaction_read_only = on` olduğu
# İLK sorguyla doğrulanır; bu modülün kendi SQL'leri yalnız SELECT'tir
# (`_select_*` her ifadeyi ayrıca denetler), commit HİÇ çağrılmaz.
#
# CANONICAL ONAY KANITI (audit + journal BİRLİKTE, mtime KULLANILMAZ):
# contained `deadlines/reviews/` altındaki TÜM `*.approval.json`
# kayıtları taranır; her biri `approval.deadline` ailesinin `completed`
# journal satırlarıyla eşleştirilir (bkz. `_audit_matches()`). Tam
# eşleşen audit+journal çifti 0 ise `approval_not_proven`, 1'den fazla
# ise `ambiguous_approval`; yalnız tam 1 çiftte devam edilir.
# `case:<id>` üzerinde prepared/executing/reconciliation_required
# durumunda HERHANGİ bir journal satırı varsa rapor üretilmez.
# Legacy (Row 19C-2a öncesi, mutation anahtarı taşımayan) audit
# kayıtları bu nedenle REDDEDİLİR - legacy bypass YOKTUR.
#
# ÇIKTI SÖZLEŞMESİ: başarıda stdout yalnız rapordur (veya `--output`
# ile yalnız tek bir "RAPOR YAZILDI" satırı); her retde stdout TAMAMEN
# BOŞ, stderr'e tek satır `RAPOR REDDEDİLDİ: <sabit_kod>`. Validator
# hata/uyarı METNİ, dosya içeriği, yol veya istisna ayrıntısı hiçbir
# zaman yazdırılmaz. Rapor yalnız `_render_report()`'un açık alan
# allowlist'inden oluşur: notes/warnings/description/attestation metni/
# legal_basis_refs/duration/case/timeline içeriği/IAM kimlik alanları
# ve belge metni hiçbir çıktıda bulunmaz.
#
# KESİN TARİH KAPISI (Adım 7 ile uyumlu): canonical/audit/journal/
# validator kanıtlarından SONRA, render'dan ÖNCE - calculated +
# expiry not_evaluated + anchor_verification_state == verified +
# stopping_event_status == none (alanın YOKLUĞU 'unknown'dur, ASLA
# 'none' değildir) + LOCKED `deadline_calculator` şekil sözleşmesine
# uyan attestation ref. Aksi halde calculated_deadline hiçbir yere
# yazılmaz.
#
# EXIT: 0 rapor üretildi · 1 ret (internal_error dahil) · 2 kullanım.
# `__main__` hiçbir koşulda ham traceback basmaz. ENCODING-FAILURE
# FALLBACK: stdout/stderr UTF-8'e ayarlanamazsa TEK çıktı ASCII
# `RAPOR REDDEDILDI: internal_error` + LF (exit 1) olur.
# ============================================================

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import io
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2

REFUSAL_PREFIX = "RAPOR REDDEDİLDİ: "

REPORT_TITLE_LINE = "VERGİ AI - DEADLINE AVUKAT RAPORU (salt-okunur, onaylı canonical kayıt)"
EXPIRY_NOT_EVALUATED_LINE = "Süre aşımı (expiry) DEĞERLENDİRİLMEDİ."
LEGAL_DISCLAIMER_LINE = "Bu çıktı hukuki karar değildir; avukat tarafından doğrulanmalıdır."
OUTPUT_WRITTEN_PREFIX = "RAPOR YAZILDI: "

APPROVAL_ACTION_FAMILY = "approval.deadline"
APPROVAL_AUDIT_TYPE = "deadline_analysis_approval"
COMPLETED_JOURNAL_STATE = "completed"
UNRESOLVED_JOURNAL_STATES = ("prepared", "executing", "reconciliation_required")
REQUIRED_ASSIGNMENT_ROLE = "lawyer"

REFUSAL_CODES = frozenset({
    "access_denied",
    "database_unavailable",
    "database_error",
    "read_only_not_enforced",
    "journal_unresolved_mutation",
    "canonical_missing",
    "canonical_unreadable",
    "case_id_mismatch",
    "deadline_count_invalid",
    "approval_not_proven",
    "ambiguous_approval",
    "validator_failed",
    "validator_warnings",
    "calculation_not_calculated",
    "expiry_state_invalid",
    "anchor_not_verified",
    "stopping_event_not_cleared",
    "stopping_event_attestation_missing",
    "field_invalid",
    "canonical_changed",
    "output_path_refused",
    "output_exists",
    "output_write_failed",
    "internal_error",
})

_BIGINT_MAX = 9223372036854775807
_POSITIVE_INT_PATTERN = re.compile(r"^[1-9][0-9]{0,18}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_ISO_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

# ENCODING-FAILURE FALLBACK: the ONLY line ever emitted when stdout/stderr
# cannot be switched to strict UTF-8. Deliberately pure ASCII (dotless
# "REDDEDILDI"), LF-terminated, written as raw bytes - it must be
# representable in ANY console encoding. No traceback, no second line,
# no report, no date.
ENCODING_FAILURE_FALLBACK_LINE = b"RAPOR REDDEDILDI: internal_error\n"


class ReportRefused(Exception):
    """Every domain refusal. `code` is always one of `REFUSAL_CODES` -
    the ONLY thing ever shown to the operator."""

    def __init__(self, code: str):
        if code not in REFUSAL_CODES:
            code = "internal_error"
        self.code = code
        super().__init__(code)


class _ExitSignal(Exception):
    def __init__(self, code: int, message: str | None = None):
        self.code = code
        self.message = message
        super().__init__(message or f"exit({code})")


class _NonExitingArgumentParser(argparse.ArgumentParser):
    """Mirrors `ui.cli_mutate._NonExitingArgumentParser` - argparse
    usage errors become `_ExitSignal` instead of a real `sys.exit()`."""

    def error(self, message: str) -> None:  # noqa: D102
        raise _ExitSignal(EXIT_USAGE, self.format_usage() + f"{self.prog}: error: {message}\n")

    def exit(self, status: int = 0, message: str | None = None) -> None:  # noqa: D102
        raise _ExitSignal(status, message)


def _positive_int(value: str) -> int:
    if not _POSITIVE_INT_PATTERN.match(value) or int(value) > _BIGINT_MAX:
        raise argparse.ArgumentTypeError("pozitif bir tamsayı olmalıdır")
    return int(value)


def _build_arg_parser():
    parser = _NonExitingArgumentParser(
        prog="python -m ui.deadline_report",
        description=(
            "Adım 9D - onaylı canonical deadline.json'dan salt-okunur avukat raporu. "
            "PostgreSQL yetkilendirmesi zorunludur; aktif lawyer assignment gerekir."
        ),
    )
    parser.add_argument("--case", dest="case_id", required=True)
    parser.add_argument("--actor-user-id", dest="actor_user_id", required=True, type=_positive_int)
    parser.add_argument(
        "--output", dest="output", default=None,
        help="Mutlak, repo DIŞI, henüz var olmayan dosya yolu (parent önceden mevcut olmalı).",
    )
    return parser


# ============================================================
# OUTPUT TARGET (repo-dışı, yalnız-oluştur)
# ============================================================

def _is_within(child, root) -> bool:
    child_norm = os.path.normcase(os.path.abspath(str(child)))
    root_norm = os.path.normcase(os.path.abspath(str(root)))
    try:
        return os.path.commonpath([child_norm, root_norm]) == root_norm
    except ValueError:
        return False


def _repo_root_real() -> Path:
    from ui.services import paths as _paths

    return Path(_paths.BASE_DIR).resolve(strict=True)


def _prepare_output_target(raw: str) -> Path:
    """Pure pre-check, performed BEFORE any database connection. A
    relative path is a usage error (exit 2); every other unsafe shape is
    a refusal. Existence is re-enforced atomically by `open(..., "x")`
    in `_write_output_file()`."""
    if "\x00" in raw:
        raise ReportRefused("output_path_refused")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise _ExitSignal(EXIT_USAGE, "error: --output mutlak bir yol olmalıdır\n")
    name = candidate.name
    if name in ("", ".", "..") or ":" in name:
        raise ReportRefused("output_path_refused")
    try:
        parent_real = candidate.parent.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ReportRefused("output_path_refused") from None
    if not parent_real.is_dir():
        raise ReportRefused("output_path_refused")
    repo_real = _repo_root_real()
    target = parent_real / name
    if _is_within(parent_real, repo_real) or _is_within(target, repo_real):
        raise ReportRefused("output_path_refused")
    if os.path.lexists(target):
        raise ReportRefused("output_exists")
    return target


def _write_output_file(target: Path, text: str) -> None:
    try:
        handle = open(target, "x", encoding="utf-8", newline="")
    except FileExistsError:
        raise ReportRefused("output_exists") from None
    except OSError:
        raise ReportRefused("output_write_failed") from None
    created_ok = False
    try:
        # Post-create containment re-check (a parent swapped for a link
        # into the repository between pre-check and open is refused and
        # the file this call itself just created is removed).
        if _is_within(Path(target).resolve(strict=True), _repo_root_real()):
            raise ReportRefused("output_path_refused")
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        created_ok = True
    except ReportRefused:
        raise
    except Exception:
        raise ReportRefused("output_write_failed") from None
    finally:
        handle.close()
        if not created_ok:
            with contextlib.suppress(OSError):
                os.unlink(target)


# ============================================================
# DATABASE (read-only, SELECT-only)
# ============================================================

def _default_conn_factory():
    """Production factory - `ui.services.db.get_connection()` (plain,
    autocommit=False; `VERGI_IAM_DATABASE_URL` zorunlu, yoksa fail-closed
    `DatabaseNotConfiguredError`). Lazy import: `import ui.deadline_report`
    never itself requires psycopg."""
    from ui.services import db as _db

    return _db.get_connection()


def _is_database_error(error: BaseException) -> bool:
    return type(error).__module__.split(".")[0] == "psycopg"


def _assert_select(sql: str) -> None:
    if not sql.lstrip().upper().startswith("SELECT"):
        raise ReportRefused("internal_error")


def _select_one(conn, sql: str, params):
    _assert_select(sql)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def _select_all(conn, sql: str, params):
    _assert_select(sql)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _open_read_only_connection(conn_factory):
    try:
        conn = conn_factory()
    except Exception:
        raise ReportRefused("database_unavailable") from None
    try:
        conn.read_only = True
        row = _select_one(conn, "SELECT current_setting('transaction_read_only')", ())
    except ReportRefused:
        _close_quietly(conn)
        raise
    except Exception:
        _close_quietly(conn)
        raise ReportRefused("database_error") from None
    if row is None or row[0] != "on":
        _close_quietly(conn)
        raise ReportRefused("read_only_not_enforced")
    return conn


def _close_quietly(conn) -> None:
    with contextlib.suppress(Exception):
        conn.rollback()
    with contextlib.suppress(Exception):
        conn.close()


# ============================================================
# AUTHORIZATION
# ============================================================

def _authorize_lawyer(conn, case_id: str, actor_user_id: int) -> str:
    from ui.services import authz as _authz
    from ui.services import cli_authz as _cli_authz

    try:
        principal = _cli_authz.build_cli_principal(conn, actor_user_id)
    except (_cli_authz.CliActorNotFoundError, _cli_authz.CliActorDisabledError):
        raise ReportRefused("access_denied") from None
    repository = _cli_authz.CliActorAuthzRepository(conn)
    try:
        resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "read", repository=repository,
        )
    except _authz.CaseAccessDeniedError:
        raise ReportRefused("access_denied") from None
    assignment = repository.get_active_case_assignment(principal.user_id, resolved_case_id)
    if assignment is None or assignment.role != REQUIRED_ASSIGNMENT_ROLE:
        raise ReportRefused("access_denied")
    return resolved_case_id


# ============================================================
# JOURNAL
# ============================================================

def _load_journal_evidence(conn, case_id: str):
    resource_key = f"case:{case_id}"
    row = _select_one(
        conn,
        "SELECT count(*) FROM mutation.mutation_journal "
        "WHERE resource_key = %s AND state IN (%s, %s, %s)",
        (resource_key, *UNRESOLVED_JOURNAL_STATES),
    )
    if row is None or row[0] != 0:
        raise ReportRefused("journal_unresolved_mutation")
    rows = _select_all(
        conn,
        "SELECT id, action_family, state, idempotency_key, observed_post_hash "
        "FROM mutation.mutation_journal "
        "WHERE resource_key = %s AND action_family = %s AND state = %s ORDER BY id",
        (resource_key, APPROVAL_ACTION_FAMILY, COMPLETED_JOURNAL_STATE),
    )
    return [
        {
            "id": r[0], "action_family": r[1], "state": r[2],
            "idempotency_key": r[3], "observed_post_hash": r[4],
        }
        for r in rows
    ]


# ============================================================
# CANONICAL FILE + AUDIT SCAN
# ============================================================

def _resolve_case_dir(case_id: str) -> Path:
    from ui.services import paths as _paths
    from ui.services.common import UnknownCaseError

    try:
        return _paths.verify_real_path_contained(_paths.CASES_DIR / case_id, root=_paths.CASES_DIR)
    except UnknownCaseError:
        raise ReportRefused("canonical_missing") from None


def _resolve_contained(case_dir_real: Path, *parts: str, refusal: str) -> Path:
    from ui.services import paths as _paths
    from ui.services.common import UnknownCaseError

    try:
        return _paths.verify_real_path_contained(case_dir_real.joinpath(*parts), root=case_dir_real)
    except UnknownCaseError:
        raise ReportRefused(refusal) from None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_json_object(data: bytes):
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _scan_approval_audits(case_dir_real: Path) -> list:
    reviews_real = _resolve_contained(case_dir_real, "deadlines", "reviews", refusal="approval_not_proven")
    if not reviews_real.is_dir():
        raise ReportRefused("approval_not_proven")
    path_containment = importlib.import_module("path_containment")
    try:
        entries = path_containment.list_contained_dir(reviews_real)
    except path_containment.PathContainmentError:
        raise ReportRefused("approval_not_proven") from None
    audits = []
    for entry in entries:
        if not entry.name.endswith(".approval.json"):
            continue
        try:
            entry_real = entry.resolve(strict=True)
            if not entry_real.is_file():
                continue
            record = _parse_json_object(entry_real.read_bytes())
        except (OSError, RuntimeError):
            continue
        if record is not None:
            audits.append(record)
    return audits


def _nonblank_str(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _audit_matches(audit: dict, journal_row: dict, *, case_id: str, analysis_id: str, canonical_sha: str) -> bool:
    """ALL of these must hold for one audit+journal pair (R4)."""
    idempotency_key = audit.get("mutation_idempotency_key")
    return (
        audit.get("audit_type") == APPROVAL_AUDIT_TYPE
        and audit.get("case_id") == case_id
        and audit.get("deadline_analysis_id") == analysis_id
        and audit.get("content_identical") is True
        and audit.get("canonical_sha256") == canonical_sha
        and audit.get("mutation_resource_key") == f"case:{case_id}"
        and _nonblank_str(idempotency_key)
        and journal_row.get("action_family") == APPROVAL_ACTION_FAMILY
        and journal_row.get("state") == COMPLETED_JOURNAL_STATE
        and journal_row.get("idempotency_key") == idempotency_key
        and journal_row.get("observed_post_hash") == canonical_sha
    )


def _count_matching_pairs(audits, journal_rows, *, case_id, analysis_id, canonical_sha) -> int:
    return sum(
        1
        for audit in audits
        for journal_row in journal_rows
        if _audit_matches(
            audit, journal_row, case_id=case_id, analysis_id=analysis_id, canonical_sha=canonical_sha,
        )
    )


def _run_domain_validator(deadline_path: Path, case_id: str) -> None:
    deadline_validator = importlib.import_module("deadline_validator")
    sink = io.StringIO()
    try:
        # Defense-in-depth: nothing the validator chain might print can
        # ever reach this CLI's own stdout/stderr.
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            result = deadline_validator.validate_deadline_analysis(
                deadline_path=deadline_path, expected_case_id=case_id, raise_on_error=False,
            )
    except Exception:
        raise ReportRefused("validator_failed") from None
    if not isinstance(result, dict) or result.get("valid") is not True or result.get("errors"):
        raise ReportRefused("validator_failed")
    warnings = result.get("warnings")
    if not isinstance(warnings, list) or warnings:
        raise ReportRefused("validator_warnings")


# ============================================================
# FIELD ALLOWLIST + RENDER
# ============================================================

def _require_id(value) -> str:
    if not isinstance(value, str) or not _ID_PATTERN.match(value):
        raise ReportRefused("field_invalid")
    return value


def _require_iso_date(value) -> str:
    if not isinstance(value, str) or not _ISO_DATE_PATTERN.match(value):
        raise ReportRefused("field_invalid")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ReportRefused("field_invalid") from None
    return value


def _attestation_ref_is_valid(value) -> bool:
    """The EXISTING shape contract, reused - never re-implemented here:
    LOCKED Row 8 `deadline_calculator.is_valid_stopping_event_attestation_ref`
    (str, non-blank after strip, 1-200 chars, fully printable, no CR/LF).
    Shape only - the ref's truth is never verified, and its content is
    never rendered."""
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        deadline_calculator = importlib.import_module("deadline_calculator")
    return deadline_calculator.is_valid_stopping_event_attestation_ref(value) is True


def _extract_allowlisted_fields(case_id: str, deadline: dict, canonical_sha: str) -> dict:
    """Runs only AFTER the canonical/audit/journal/validator proofs.
    A definite date is reported ONLY when: calculated, expiry not
    evaluated, anchor verified, stopping event explicitly declared
    'none' AND backed by a shape-valid attestation ref. Absence of
    `stopping_event_status` is 'unknown' by schema contract, never
    'none' (Adım 7)."""
    if deadline.get("calculation_state") != "calculated":
        raise ReportRefused("calculation_not_calculated")
    if deadline.get("expiry_state") != "not_evaluated":
        raise ReportRefused("expiry_state_invalid")
    if deadline.get("anchor_verification_state") != "verified":
        raise ReportRefused("anchor_not_verified")
    if deadline.get("stopping_event_status") != "none":
        raise ReportRefused("stopping_event_not_cleared")
    if not _attestation_ref_is_valid(deadline.get("stopping_event_attestation_ref")):
        raise ReportRefused("stopping_event_attestation_missing")

    requires_human_review = deadline.get("requires_human_review")
    if not isinstance(requires_human_review, bool):
        raise ReportRefused("field_invalid")

    return {
        "case_id": _require_id(case_id),
        "deadline_id": _require_id(deadline.get("deadline_id")),
        "anchor_event_id": _require_id(deadline.get("anchor_event_id")),
        "anchor_date": _require_iso_date(deadline.get("anchor_date")),
        "anchor_verification_state": "verified",
        "rule_id": _require_id(deadline.get("rule_id")),
        "calculated_deadline": _require_iso_date(deadline.get("calculated_deadline")),
        "calculation_state": "calculated",
        "requires_human_review": requires_human_review,
        "stopping_event_status": "none",
        "canonical_sha256": canonical_sha,
    }


def _render_report(fields: dict) -> str:
    lines = [
        REPORT_TITLE_LINE,
        f"case_id: {fields['case_id']}",
        f"deadline_id: {fields['deadline_id']}",
        f"anchor_event_id: {fields['anchor_event_id']}",
        f"anchor_date (başlangıç olayı / tebliğ tarihi): {fields['anchor_date']}",
        f"anchor_verification_state: {fields['anchor_verification_state']}",
        f"rule_id: {fields['rule_id']}",
        f"calculated_deadline: {fields['calculated_deadline']}",
        f"calculation_state: {fields['calculation_state']}",
        f"requires_human_review: {'EVET' if fields['requires_human_review'] else 'HAYIR'}",
        f"stopping_event_status: {fields['stopping_event_status']}",
        "stopping_event_attestation_ref: VAR",
        f"canonical_sha256: {fields['canonical_sha256']}",
        EXPIRY_NOT_EVALUATED_LINE,
        LEGAL_DISCLAIMER_LINE,
    ]
    return "\n".join(lines) + "\n"


# ============================================================
# ORCHESTRATION
# ============================================================

def build_report(case_id: str, actor_user_id: int, *, conn_factory=None) -> str:
    """Returns the full report text or raises `ReportRefused`. Any
    other exception propagates with its own chain (tests may call this
    directly); `main()` maps it to `internal_error`."""
    conn_factory = _default_conn_factory if conn_factory is None else conn_factory
    conn = _open_read_only_connection(conn_factory)
    try:
        try:
            resolved_case_id = _authorize_lawyer(conn, case_id, actor_user_id)
            journal_rows = _load_journal_evidence(conn, resolved_case_id)
        except ReportRefused:
            raise
        except Exception as error:
            if _is_database_error(error):
                raise ReportRefused("database_error") from None
            raise
    finally:
        _close_quietly(conn)

    case_dir_real = _resolve_case_dir(resolved_case_id)
    deadline_path = _resolve_contained(
        case_dir_real, "deadlines", "deadline.json", refusal="canonical_missing",
    )
    if not deadline_path.is_file():
        raise ReportRefused("canonical_missing")
    try:
        raw = deadline_path.read_bytes()
    except OSError:
        raise ReportRefused("canonical_missing") from None
    canonical_sha = _sha256_bytes(raw)

    document = _parse_json_object(raw)
    if document is None:
        raise ReportRefused("canonical_unreadable")
    if document.get("case_id") != resolved_case_id:
        raise ReportRefused("case_id_mismatch")
    deadlines = document.get("deadlines")
    if not isinstance(deadlines, list) or len(deadlines) != 1:
        raise ReportRefused("deadline_count_invalid")
    deadline = deadlines[0]
    if not isinstance(deadline, dict):
        raise ReportRefused("canonical_unreadable")
    analysis_id = document.get("deadline_analysis_id")
    if not isinstance(analysis_id, str) or not _ID_PATTERN.match(analysis_id):
        raise ReportRefused("field_invalid")

    audits = _scan_approval_audits(case_dir_real)
    pair_count = _count_matching_pairs(
        audits, journal_rows,
        case_id=resolved_case_id, analysis_id=analysis_id, canonical_sha=canonical_sha,
    )
    if pair_count == 0:
        raise ReportRefused("approval_not_proven")
    if pair_count > 1:
        raise ReportRefused("ambiguous_approval")

    _run_domain_validator(deadline_path, resolved_case_id)

    fields = _extract_allowlisted_fields(resolved_case_id, deadline, canonical_sha)

    try:
        second_sha = _sha256_bytes(deadline_path.read_bytes())
    except OSError:
        raise ReportRefused("canonical_changed") from None
    if second_sha != canonical_sha:
        raise ReportRefused("canonical_changed")

    return _render_report(fields)


def main(argv: list[str] | None = None, *, conn_factory=None, stdout=None, stderr=None) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    parser = _build_arg_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except _ExitSignal as exit_signal:
        if exit_signal.message:
            stderr.write(exit_signal.message)
        return exit_signal.code

    try:
        output_target = _prepare_output_target(args.output) if args.output is not None else None
        report = build_report(args.case_id, args.actor_user_id, conn_factory=conn_factory)
        if output_target is not None:
            _write_output_file(output_target, report)
            stdout.write(f"{OUTPUT_WRITTEN_PREFIX}{output_target}\n")
        else:
            stdout.write(report)
        return EXIT_OK
    except _ExitSignal as exit_signal:
        if exit_signal.message:
            stderr.write(exit_signal.message)
        return exit_signal.code
    except ReportRefused as refusal:
        stderr.write(f"{REFUSAL_PREFIX}{refusal.code}\n")
        return EXIT_REFUSED
    except Exception:
        stderr.write(f"{REFUSAL_PREFIX}internal_error\n")
        return EXIT_REFUSED


def _emit_encoding_failure_fallback() -> None:
    """ENCODING-FAILURE FALLBACK (see `ENCODING_FAILURE_FALLBACK_LINE`).
    Written as raw bytes to the underlying stderr buffer so no text-mode
    CRLF translation or console codec can alter it."""
    with contextlib.suppress(Exception):
        buffer = getattr(sys.stderr, "buffer", None)
        if buffer is not None:
            buffer.write(ENCODING_FAILURE_FALLBACK_LINE)
            buffer.flush()
        else:
            sys.stderr.write(ENCODING_FAILURE_FALLBACK_LINE.decode("ascii"))
            sys.stderr.flush()


def _console_entrypoint() -> int:
    """`python -m ui.deadline_report`. Forces strict UTF-8 + LF on both
    streams (Windows redirected stdout otherwise defaults to cp1254) and
    never lets a raw traceback reach the console. If either stream cannot
    be reconfigured, the encoding-failure fallback is the ONLY output
    and nothing else runs."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    except Exception:
        _emit_encoding_failure_fallback()
        return EXIT_REFUSED
    try:
        return main()
    except BaseException:
        with contextlib.suppress(Exception):
            sys.stderr.write(f"{REFUSAL_PREFIX}internal_error\n")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(_console_entrypoint())
