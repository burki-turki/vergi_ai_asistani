# ============================================================
# PILOT READINESS ADIM 9D - ui.deadline_report ISOLATED TESTS.
#
# Pure-Python, no real PostgreSQL. A `FakeConn` answers the exact SQL
# shapes `ui.deadline_report` (and the inherited `ui.services.cli_authz`
# / `ui.services.authz` repository methods) issue, records every
# statement, and proves: read_only was requested, every statement is a
# SELECT, commit() is never called. Every synthetic case lives in a
# tempdir (`ui.services.paths.CASES_DIR` redirected) - the real `data/`
# tree is byte-manifested before/after and must be unchanged.
#
# The domain validator (`deadline_validator.validate_deadline_analysis`,
# LOCKED Row 8) is faked for the report-logic scenarios; section R
# additionally wires the REAL validator against a tempdir copy of the
# real case_0001 fixture. The genuine calculated end-to-end chain is
# proven by `test_deadline_report_integration_postgres.py`.
#
# Run: python ui/tests/test_deadline_report_isolated.py
# ============================================================

import ast
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
REAL_DATA_DIR = REPO_ROOT / "data"
REAL_CASE_0001 = REAL_DATA_DIR / "cases" / "case_0001"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ui.deadline_report as dr                              # noqa: E402
from ui.services import paths as _paths                      # noqa: E402

import deadline_validator as _deadline_validator             # noqa: E402
import timeline_validator as _timeline_validator             # noqa: E402

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


def snapshot_data_tree():
    out = {}
    for path in REAL_DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(REAL_DATA_DIR))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(REAL_DATA_DIR))] = "<unreadable>"
    return out


_data_tree_before = snapshot_data_tree()

# ------------------------------------------------------------
# No-network guard (in-process). Any connect attempt is recorded AND
# refused.
# ------------------------------------------------------------
_network_attempts = []
_orig_socket_connect = socket.socket.connect
_orig_create_connection = socket.create_connection


def _blocked_connect(self, address, *args, **kwargs):
    _network_attempts.append(repr(address))
    raise OSError("network blocked by test_deadline_report_isolated")


def _blocked_create_connection(address, *args, **kwargs):
    _network_attempts.append(repr(address))
    raise OSError("network blocked by test_deadline_report_isolated")


socket.socket.connect = _blocked_connect
socket.create_connection = _blocked_create_connection

# ------------------------------------------------------------
# Sentinels - must NEVER appear in stdout/stderr/output file.
# ------------------------------------------------------------
SENT_TOP_NOTES = "SENTINEL_TOP_NOTES_Çağrı_Yılmaz"
SENT_TOP_WARNING = "SENTINEL_TOP_WARNING_gizli"
SENT_NOTES = "SENTINEL_DEADLINE_NOTES_Şükrü"
SENT_DESCRIPTION = "SENTINEL_DESCRIPTION_metin"
SENT_ATTESTATION = "SENTINEL_ATTESTATION_Av_Ayşe_Kaya_beyanı"
SENT_LEGAL = "SENTINEL_LEGAL_BASIS_REF"
SENT_PARTY = "SENTINEL_PARTY_DISPLAY_NAME_Kurgusal_Ltd"
SENT_VALIDATOR = "SENTINEL_VALIDATOR_ERROR_TEXT_Deadline=2099"
SENT_EXCEPTION = "SENTINEL_EXCEPTION_C:\\secret\\path"
ALL_SENTINELS = (
    SENT_TOP_NOTES, SENT_TOP_WARNING, SENT_NOTES, SENT_DESCRIPTION, SENT_ATTESTATION,
    SENT_LEGAL, SENT_PARTY, SENT_VALIDATOR, SENT_EXCEPTION, "SENTINEL",
)


def no_sentinel(*texts):
    joined = "".join(texts)
    return not any(s in joined for s in ALL_SENTINELS)


# ------------------------------------------------------------
# Fake authz/journal connection.
# ------------------------------------------------------------

class FakePsycopgError(Exception):
    pass


FakePsycopgError.__module__ = "psycopg.errors"


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=()):
        conn = self._conn
        conn.query_log.append((sql, tuple(params)))
        if conn.raise_on_execute is not None:
            raise conn.raise_on_execute
        normalized = " ".join(sql.split())
        if "current_setting('transaction_read_only')" in normalized:
            self._rows = [(conn.read_only_setting if conn.read_only else "off",)]
        elif "FROM iam.users" in normalized:
            (user_id,) = params
            user = conn.users.get(user_id)
            self._rows = [] if user is None else [user]
        elif "FROM iam.case_assignments" in normalized and "case_id = %s" in normalized:
            user_id, case_id = params
            role = conn.assignments.get((user_id, case_id))
            self._rows = [] if role is None else [(role,)]
        elif normalized.startswith("SELECT count(*) FROM mutation.mutation_journal"):
            resource_key, *states = params
            self._rows = [(sum(
                1 for r in conn.journal if r["resource_key"] == resource_key and r["state"] in states
            ),)]
        elif "FROM mutation.mutation_journal" in normalized:
            resource_key, action_family, state = params
            self._rows = [
                (r["id"], r["action_family"], r["state"], r["idempotency_key"], r["observed_post_hash"])
                for r in conn.journal
                if r["resource_key"] == resource_key and r["action_family"] == action_family
                and r["state"] == state
            ]
        else:
            raise AssertionError(f"unexpected SQL shape: {normalized!r}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self):
        self.users = {}
        self.assignments = {}
        self.journal = []
        self.query_log = []
        self.read_only = False
        self.read_only_setting = "on"
        self.raise_on_execute = None
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.closed = True


def all_select(conn):
    return all(sql.lstrip().upper().startswith("SELECT") for sql, _ in conn.query_log)


# ------------------------------------------------------------
# Tempdir cases root + synthetic fixture builder.
# ------------------------------------------------------------
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_deadline_report_iso_"))
_TMP_CASES = _TMP_ROOT / "data" / "cases"
_TMP_CASES.mkdir(parents=True)
_TMP_OUT = _TMP_ROOT / "out"
_TMP_OUT.mkdir()

_original_paths_cases_dir = _paths.CASES_DIR
_paths.CASES_DIR = _TMP_CASES

ACTOR = 7
OTHER_ACTOR = 8


def base_deadline_document(case_id):
    return {
        "schema_version": 1,
        "deadline_analysis_id": f"deadline_{case_id}_v1",
        "case_id": case_id,
        "status": "completed",
        "generated_at": "2026-09-30T10:00:00+03:00",
        "deadlines": [
            {
                "deadline_id": "deadline_001",
                "deadline_type": "lawsuit_filing",
                "description": SENT_DESCRIPTION,
                "anchor_event_id": "timeline_event_001",
                "anchor_date": "2026-02-10",
                "anchor_verification_state": "verified",
                "rule_id": "iyuk_tax_court_general_lawsuit_filing",
                "legal_basis_refs": [SENT_LEGAL],
                "duration": {"value": 30, "unit": "day", "day_type": "calendar"},
                "start_rule": "next_day",
                "calculation_state": "calculated",
                "calculated_deadline": "2026-03-12",
                "expiry_state": "not_evaluated",
                "confidence": 0.95,
                "requires_human_review": True,
                "notes": SENT_NOTES,
                "stopping_event_status": "none",
                "stopping_event_attestation_ref": SENT_ATTESTATION,
            }
        ],
        "warnings": [SENT_TOP_WARNING],
        "notes": SENT_TOP_NOTES,
    }


def write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def audit_for(case_id, analysis_id, canonical_sha, key):
    return {
        "audit_type": "deadline_analysis_approval",
        "approval_version": "1",
        "approved_at": "2026-09-30T10:05:00+03:00",
        "case_id": case_id,
        "deadline_analysis_id": analysis_id,
        "pending_sha256": canonical_sha,
        "canonical_sha256": canonical_sha,
        "content_identical": True,
        "deadline_count": 1,
        "mutation_idempotency_key": key,
        "mutation_resource_key": f"case:{case_id}",
        "approval_semantics": SENT_TOP_NOTES,
    }


class Fixture:
    pass


def make_fixture(*, document=None, raw_bytes=None, with_audit=True, with_journal=True, role="lawyer"):
    fx = Fixture()
    fx.case_id = f"rptiso{uuid.uuid4().hex[:10]}"
    fx.case_dir = _TMP_CASES / fx.case_id
    fx.case_dir.mkdir(parents=True)
    write_bytes(fx.case_dir / "case.json", json.dumps({
        "schema_version": 1, "case_id": fx.case_id,
        "parties": [{"party_id": "p1", "display_name": SENT_PARTY}],
    }, ensure_ascii=False).encode("utf-8"))
    fx.document = base_deadline_document(fx.case_id) if document is None else document(fx.case_id)
    fx.raw = (
        json.dumps(fx.document, ensure_ascii=False, indent=2).encode("utf-8")
        if raw_bytes is None else raw_bytes
    )
    fx.deadline_path = fx.case_dir / "deadlines" / "deadline.json"
    write_bytes(fx.deadline_path, fx.raw)
    fx.sha = hashlib.sha256(fx.raw).hexdigest()
    fx.key = hashlib.sha256(f"idem-{fx.case_id}".encode()).hexdigest()
    fx.reviews = fx.case_dir / "deadlines" / "reviews"
    fx.reviews.mkdir(parents=True, exist_ok=True)
    fx.audit = audit_for(fx.case_id, f"deadline_{fx.case_id}_v1", fx.sha, fx.key)
    fx.audit_path = fx.reviews / f"deadline_{fx.case_id}_v1_20260930_100500.approval.json"
    if with_audit:
        write_bytes(fx.audit_path, json.dumps(fx.audit, ensure_ascii=False).encode("utf-8"))
    fx.conn = FakeConn()
    fx.conn.users[ACTOR] = (1, False)
    fx.conn.assignments[(ACTOR, fx.case_id)] = role
    if with_journal:
        fx.conn.journal.append({
            "id": 1, "resource_key": f"case:{fx.case_id}", "action_family": "approval.deadline",
            "state": "completed", "idempotency_key": fx.key, "observed_post_hash": fx.sha,
        })
    fx.factory_calls = 0

    def factory():
        fx.factory_calls += 1
        return fx.conn

    fx.factory = factory
    return fx


def write_audit(fx, record, name):
    write_bytes(fx.reviews / name, json.dumps(record, ensure_ascii=False).encode("utf-8"))


def run(argv, *, conn_factory):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = dr.main(argv, conn_factory=conn_factory, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def run_fx(fx, *extra, actor=ACTOR, case_id=None):
    return run(
        ["--case", fx.case_id if case_id is None else case_id, "--actor-user-id", str(actor), *extra],
        conn_factory=fx.factory,
    )


def refused(code, out, err, expected_code):
    return code == 1 and out == "" and err == f"RAPOR REDDEDİLDİ: {expected_code}\n"


# ------------------------------------------------------------
# Fake domain validator (sections A-V). Section R restores the real one.
# ------------------------------------------------------------
_real_validate = _deadline_validator.validate_deadline_analysis
_validator_calls = []
_validator_behavior = {"mode": "valid"}


def _fake_validate(deadline_path, expected_case_id=None, raise_on_error=False):
    _validator_calls.append((str(deadline_path), expected_case_id))
    mode = _validator_behavior["mode"]
    if mode == "valid":
        return {"valid": True, "errors": [], "warnings": []}
    if mode == "valid_but_prints":
        print(SENT_VALIDATOR)
        sys.stderr.write(SENT_VALIDATOR + "\n")
        return {"valid": True, "errors": [], "warnings": []}
    if mode == "invalid":
        return {"valid": False, "errors": [SENT_VALIDATOR], "warnings": []}
    if mode == "errors_but_valid_true":
        return {"valid": True, "errors": [SENT_VALIDATOR], "warnings": []}
    if mode == "warnings":
        return {"valid": True, "errors": [], "warnings": [SENT_VALIDATOR]}
    if mode == "warnings_not_list":
        return {"valid": True, "errors": [], "warnings": None}
    if mode == "raises":
        raise RuntimeError(SENT_VALIDATOR)
    if mode == "not_dict":
        return None
    if mode == "mutate_file":
        Path(deadline_path).write_bytes(Path(deadline_path).read_bytes() + b" ")
        return {"valid": True, "errors": [], "warnings": []}
    raise AssertionError(mode)


_deadline_validator.validate_deadline_analysis = _fake_validate


def expected_report(fx, *, requires_review="EVET", sha=None):
    return (
        "VERGİ AI - DEADLINE AVUKAT RAPORU (salt-okunur, onaylı canonical kayıt)\n"
        f"case_id: {fx.case_id}\n"
        "deadline_id: deadline_001\n"
        "anchor_event_id: timeline_event_001\n"
        "anchor_date (başlangıç olayı / tebliğ tarihi): 2026-02-10\n"
        "anchor_verification_state: verified\n"
        "rule_id: iyuk_tax_court_general_lawsuit_filing\n"
        "calculated_deadline: 2026-03-12\n"
        "calculation_state: calculated\n"
        f"requires_human_review: {requires_review}\n"
        "stopping_event_status: none\n"
        "stopping_event_attestation_ref: VAR\n"
        f"canonical_sha256: {fx.sha if sha is None else sha}\n"
        "Süre aşımı (expiry) DEĞERLENDİRİLMEDİ.\n"
        "Bu çıktı hukuki karar değildir; avukat tarafından doğrulanmalıdır.\n"
    )


def with_deadline(**changes):
    def build(case_id):
        doc = base_deadline_document(case_id)
        for key, value in changes.items():
            if value is _DELETE:
                doc["deadlines"][0].pop(key, None)
            else:
                doc["deadlines"][0][key] = value
        return doc
    return build


_DELETE = object()


def _exploding_factory():
    raise AssertionError("conn_factory must not be called")


try:
    # ============================================================
    # U - usage contract (exit 2, zero DB access).
    # ============================================================
    factory_calls = {"n": 0}

    def counting_exploding_factory():
        factory_calls["n"] += 1
        raise AssertionError("conn_factory must not be called on a usage error")

    usage_cases = [
        ("U1 missing --case", ["--actor-user-id", "7"]),
        ("U2 missing --actor-user-id", ["--case", "c1"]),
        ("U3 actor zero", ["--case", "c1", "--actor-user-id", "0"]),
        ("U4 actor negative", ["--case", "c1", "--actor-user-id", "-3"]),
        ("U5 actor non-numeric", ["--case", "c1", "--actor-user-id", "abc"]),
        ("U6 actor float", ["--case", "c1", "--actor-user-id", "1.5"]),
        ("U7 actor leading zero", ["--case", "c1", "--actor-user-id", "07"]),
        ("U8 actor above BIGINT", ["--case", "c1", "--actor-user-id", "9223372036854775808"]),
        ("U9 unknown flag (no bypass flag exists)", ["--case", "c1", "--actor-user-id", "7", "--no-authz"]),
        ("U10 relative --output", ["--case", "c1", "--actor-user-id", "7", "--output", "rapor.txt"]),
        ("U11 no arguments", []),
    ]
    for label, argv in usage_cases:
        code, out, err = run(argv, conn_factory=counting_exploding_factory)
        check(f"{label} -> exit 2, empty stdout, non-empty stderr", code == 2 and out == "" and err != "",
              f"code={code} out={out!r} err={err!r}")
    check("U12 no usage error ever opened a DB connection", factory_calls["n"] == 0)

    parser_options = set()
    for action in dr._build_arg_parser()._actions:
        parser_options.update(action.option_strings)
    check("U13 parser exposes exactly --case/--actor-user-id/--output (+help) - no offline/bypass flag",
          parser_options == {"-h", "--help", "--case", "--actor-user-id", "--output"}, f"{parser_options!r}")

    # ============================================================
    # A - happy path + read-only/SELECT-only proof + allowlist.
    # ============================================================
    fx = make_fixture()
    code, out, err = run_fx(fx)
    check("A1 happy path exits 0 with empty stderr", code == 0 and err == "", f"code={code} err={err!r}")
    check("A2 stdout is EXACTLY the allowlisted report", out == expected_report(fx), f"out={out!r}")
    check("A3 exact expiry line present", "Süre aşımı (expiry) DEĞERLENDİRİLMEDİ.\n" in out)
    check("A4 exact legal disclaimer line present",
          "Bu çıktı hukuki karar değildir; avukat tarafından doğrulanmalıdır.\n" in out)
    check("A5 no sentinel (notes/warnings/description/attestation text/legal_basis_refs/case.json) leaked",
          no_sentinel(out, err))
    check("A6 duration/legal_basis_refs/description/notes/warnings keys never rendered",
          all(k not in out for k in ("duration", "legal_basis_refs", "description", "notes", "warnings",
                                    "display_name", "subject", "issuer")))
    check("A7 connection was switched to read_only BEFORE use", fx.conn.read_only is True)
    check("A8 first statement is the transaction_read_only proof",
          fx.conn.query_log and "transaction_read_only" in fx.conn.query_log[0][0])
    check("A9 every issued statement is a SELECT", all_select(fx.conn), f"{fx.conn.query_log!r}")
    check("A10 commit() never called; rollback()+close() called",
          fx.conn.commit_calls == 0 and fx.conn.rollback_calls >= 1 and fx.conn.closed)
    check("A11 exactly one connection opened", fx.factory_calls == 1)
    journal_sql = [s for s, _ in fx.conn.query_log if "mutation.mutation_journal" in s]
    check("A12 journal read = unresolved-count query + approval.deadline completed query",
          len(journal_sql) == 2 and "count(*)" in journal_sql[0], f"{journal_sql!r}")
    check("A13 validator called once with the contained canonical path and resolved case_id",
          len(_validator_calls) == 1 and _validator_calls[-1][1] == fx.case_id
          and Path(_validator_calls[-1][0]).name == "deadline.json")
    check("A14 canonical file unchanged by the report", fx.deadline_path.read_bytes() == fx.raw)

    fx = make_fixture(document=with_deadline(requires_human_review=False))
    code, out, err = run_fx(fx)
    check("A15 requires_human_review=false renders HAYIR", code == 0 and out == expected_report(fx, requires_review="HAYIR"),
          f"out={out!r} err={err!r}")

    _validator_behavior["mode"] = "valid_but_prints"
    fx = make_fixture()
    code, out, err = run_fx(fx)
    check("A18 anything the validator prints never reaches this CLI's stdout/stderr",
          code == 0 and out == expected_report(fx) and err == "" and no_sentinel(out, err), f"out={out!r} err={err!r}")
    _validator_behavior["mode"] = "valid"

    # ============================================================
    # Z - authorization (existence-blind, all -> access_denied).
    # ============================================================
    fx = make_fixture()
    code, out, err = run_fx(fx, actor=999)
    check("Z1 nonexistent actor -> access_denied", refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    fx.conn.users[ACTOR] = (1, True)
    code, out, err = run_fx(fx)
    check("Z2 disabled actor -> access_denied", refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    del fx.conn.assignments[(ACTOR, fx.case_id)]
    code, out, err = run_fx(fx)
    check("Z3 no active assignment -> access_denied", refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    fx = make_fixture(role="analyst")
    code, out, err = run_fx(fx)
    check("Z4 active ANALYST assignment -> access_denied (lawyer only)",
          refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    other = make_fixture()
    code, out, err = run_fx(fx, case_id=other.case_id)
    check("Z5 lawyer of another case -> access_denied", refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    fx.conn.assignments[(ACTOR, "rptiso_does_not_exist")] = "lawyer"
    code, out, err = run_fx(fx, case_id="rptiso_does_not_exist")
    check("Z6 assigned but nonexistent case dir -> access_denied (existence-blind)",
          refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    for bad in ("../case_0001", "a/b", "x" * 65, ""):
        fx = make_fixture()
        code, out, err = run_fx(fx, case_id=bad)
        check(f"Z7 malformed case_id {bad[:12]!r} -> access_denied",
              refused(code, out, err, "access_denied"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    calls_before = len(_validator_calls)
    fx.conn.assignments[(ACTOR, fx.case_id)] = "analyst"
    run_fx(fx)
    check("Z8 an authz refusal never reaches the validator / canonical file",
          len(_validator_calls) == calls_before)

    # ============================================================
    # D - database contract.
    # ============================================================
    def raising_factory():
        raise RuntimeError(SENT_EXCEPTION)

    code, out, err = run(["--case", "c1", "--actor-user-id", "7"], conn_factory=raising_factory)
    check("D1 connection factory failure -> database_unavailable, no detail leaked",
          refused(code, out, err, "database_unavailable") and no_sentinel(out, err), f"{code} {out!r} {err!r}")

    saved_dsn = os.environ.pop("VERGI_IAM_DATABASE_URL", None)
    try:
        code, out, err = run(["--case", "c1", "--actor-user-id", "7"], conn_factory=None)
    finally:
        if saved_dsn is not None:
            os.environ["VERGI_IAM_DATABASE_URL"] = saved_dsn
    check("D2 production factory with VERGI_IAM_DATABASE_URL unset -> database_unavailable (no offline mode)",
          refused(code, out, err, "database_unavailable"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    fx.conn.read_only_setting = "off"
    code, out, err = run_fx(fx)
    check("D3 session not actually read-only -> read_only_not_enforced",
          refused(code, out, err, "read_only_not_enforced") and fx.conn.closed, f"{code} {out!r} {err!r}")

    fx = make_fixture()
    fx.conn.raise_on_execute = FakePsycopgError(SENT_EXCEPTION)
    code, out, err = run_fx(fx)
    check("D4 psycopg-class error -> database_error, no detail leaked",
          refused(code, out, err, "database_error") and no_sentinel(out, err), f"{code} {out!r} {err!r}")

    try:
        dr._select_one(FakeConn(), "UPDATE iam.users SET disabled = TRUE", ())
        select_guard_ok = False
    except dr.ReportRefused as refusal:
        select_guard_ok = refusal.code == "internal_error"
    check("D5 the module's own SQL helper refuses any non-SELECT statement", select_guard_ok)

    # ============================================================
    # J - journal evidence.
    # ============================================================
    for state in ("prepared", "executing", "reconciliation_required"):
        for family in ("approval.deadline", "generation.deadline"):
            fx = make_fixture()
            fx.conn.journal.append({
                "id": 2, "resource_key": f"case:{fx.case_id}", "action_family": family, "state": state,
                "idempotency_key": "other", "observed_post_hash": None,
            })
            code, out, err = run_fx(fx)
            check(f"J1 unresolved {family}/{state} row on case resource -> journal_unresolved_mutation",
                  refused(code, out, err, "journal_unresolved_mutation"), f"{code} {out!r} {err!r}")

    fx = make_fixture(with_journal=False)
    code, out, err = run_fx(fx)
    check("J2 no completed approval.deadline journal row -> approval_not_proven",
          refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    fx.conn.journal[0]["observed_post_hash"] = "0" * 64
    code, out, err = run_fx(fx)
    check("J3 journal observed_post_hash != canonical sha -> approval_not_proven",
          refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    fx.conn.journal[0]["action_family"] = "promotion.timeline"
    code, out, err = run_fx(fx)
    check("J4 completed row of a DIFFERENT family only -> approval_not_proven",
          refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    fx.conn.journal[0]["state"] = "failed"
    code, out, err = run_fx(fx)
    check("J5 failed (not completed) approval row -> approval_not_proven",
          refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    fx.conn.journal[0]["resource_key"] = "case:someone_else"
    code, out, err = run_fx(fx)
    check("J6 completed row on ANOTHER case resource -> approval_not_proven",
          refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    # ============================================================
    # P - audit + journal unique-match (R4), mtime-independent.
    # ============================================================
    fx = make_fixture(with_audit=False)
    code, out, err = run_fx(fx)
    check("P1 no audit record -> approval_not_proven", refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    fx = make_fixture(with_audit=False)
    shutil.rmtree(fx.reviews)
    code, out, err = run_fx(fx)
    check("P2 no reviews dir -> approval_not_proven", refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    audit_mutations = [
        ("audit_type", "timeline_approval"),
        ("case_id", "case_other"),
        ("deadline_analysis_id", "deadline_other_v1"),
        ("content_identical", False),
        ("content_identical", "true"),
        ("canonical_sha256", "f" * 64),
        ("mutation_resource_key", "case:case_other"),
        ("mutation_idempotency_key", None),
        ("mutation_idempotency_key", "   "),
        ("mutation_idempotency_key", "a" * 64),
    ]
    for field, value in audit_mutations:
        fx = make_fixture(with_audit=False)
        record = dict(fx.audit)
        record[field] = value
        write_audit(fx, record, fx.audit_path.name)
        code, out, err = run_fx(fx)
        check(f"P3 audit {field}={value!r} -> approval_not_proven",
              refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    fx = make_fixture(with_audit=False)
    legacy = dict(fx.audit)
    legacy.pop("mutation_idempotency_key")
    legacy.pop("mutation_resource_key")
    write_audit(fx, legacy, fx.audit_path.name)
    code, out, err = run_fx(fx)
    check("P4 legacy audit (no mutation keys) -> approval_not_proven (no legacy bypass)",
          refused(code, out, err, "approval_not_proven"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    write_audit(fx, fx.audit, "copy_of_matching.approval.json")
    code, out, err = run_fx(fx)
    check("P5 two matching audits for the same completed journal row -> ambiguous_approval",
          refused(code, out, err, "ambiguous_approval"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    second_key = "b" * 64
    fx.conn.journal.append({
        "id": 2, "resource_key": f"case:{fx.case_id}", "action_family": "approval.deadline",
        "state": "completed", "idempotency_key": second_key, "observed_post_hash": fx.sha,
    })
    second = dict(fx.audit)
    second["mutation_idempotency_key"] = second_key
    write_audit(fx, second, "second_approval.approval.json")
    code, out, err = run_fx(fx)
    check("P6 two distinct fully-matching audit+journal pairs -> ambiguous_approval",
          refused(code, out, err, "ambiguous_approval"), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    newer = dict(fx.audit)
    newer["canonical_sha256"] = "e" * 64
    write_audit(fx, newer, "zz_newer_nonmatching.approval.json")
    os.utime(fx.audit_path, (1_000_000_000, 1_000_000_000))
    os.utime(fx.reviews / "zz_newer_nonmatching.approval.json", (2_000_000_000, 2_000_000_000))
    write_bytes(fx.reviews / "broken.approval.json", b"{not json")
    write_bytes(fx.reviews / "list.approval.json", b"[1, 2]")
    write_audit(fx, fx.audit, "matching_but_wrong_suffix.json")
    code, out, err = run_fx(fx)
    check("P7 selection is NOT mtime-based: an OLDER matching audit wins over a NEWER non-matching one; "
          "malformed/non-object/wrong-suffix entries are ignored",
          code == 0 and out == expected_report(fx), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    calls_before = len(_validator_calls)
    fx.conn.journal.clear()
    run_fx(fx)
    check("P8 validator never runs before approval is proven", len(_validator_calls) == calls_before)

    # ============================================================
    # C - canonical file structure.
    # ============================================================
    fx = make_fixture()
    fx.deadline_path.unlink()
    code, out, err = run_fx(fx)
    check("C1 canonical deadline.json missing -> canonical_missing", refused(code, out, err, "canonical_missing"),
          f"{code} {out!r} {err!r}")

    fx = make_fixture()
    shutil.rmtree(fx.case_dir / "deadlines")
    code, out, err = run_fx(fx)
    check("C2 deadlines dir missing -> canonical_missing", refused(code, out, err, "canonical_missing"),
          f"{code} {out!r} {err!r}")

    fx = make_fixture()
    (fx.case_dir / "deadlines" / "pending_only").mkdir()
    fx.deadline_path.unlink()
    (fx.case_dir / "deadlines" / f"deadline_{fx.case_id}_v1.json.pending").write_bytes(fx.raw)
    code, out, err = run_fx(fx)
    check("C3 a pending file alone is NEVER read as canonical -> canonical_missing",
          refused(code, out, err, "canonical_missing"), f"{code} {out!r} {err!r}")

    for label, raw in (
        ("invalid JSON", b"{\"case_id\": "),
        ("root is a list", b"[]"),
        ("UTF-8 BOM prefixed", b"\xef\xbb\xbf{}"),
        ("non-UTF-8 bytes", b"\xff\xfe\x00"),
    ):
        fx = make_fixture(raw_bytes=raw)
        code, out, err = run_fx(fx)
        check(f"C4 {label} -> canonical_unreadable", refused(code, out, err, "canonical_unreadable"),
              f"{code} {out!r} {err!r}")

    def mismatched_case(case_id):
        doc = base_deadline_document(case_id)
        doc["case_id"] = "case_other"
        return doc

    fx = make_fixture(document=mismatched_case)
    code, out, err = run_fx(fx)
    check("C5 canonical case_id != requested case -> case_id_mismatch", refused(code, out, err, "case_id_mismatch"),
          f"{code} {out!r} {err!r}")

    for label, deadlines in (("zero", []), ("two", None), ("not a list", {"a": 1})):
        def build(case_id, deadlines=deadlines):
            doc = base_deadline_document(case_id)
            doc["deadlines"] = doc["deadlines"] * 2 if deadlines is None else deadlines
            return doc
        fx = make_fixture(document=build)
        code, out, err = run_fx(fx)
        check(f"C6 deadlines {label} -> deadline_count_invalid", refused(code, out, err, "deadline_count_invalid"),
              f"{code} {out!r} {err!r}")

    def non_dict_deadline(case_id):
        doc = base_deadline_document(case_id)
        doc["deadlines"] = ["x"]
        return doc

    fx = make_fixture(document=non_dict_deadline)
    code, out, err = run_fx(fx)
    check("C7 deadline element not an object -> canonical_unreadable", refused(code, out, err, "canonical_unreadable"),
          f"{code} {out!r} {err!r}")

    # ============================================================
    # V - validator contract (details never shown).
    # ============================================================
    for mode, expected in (
        ("invalid", "validator_failed"),
        ("errors_but_valid_true", "validator_failed"),
        ("raises", "validator_failed"),
        ("not_dict", "validator_failed"),
        ("warnings", "validator_warnings"),
        ("warnings_not_list", "validator_warnings"),
    ):
        _validator_behavior["mode"] = mode
        fx = make_fixture()
        code, out, err = run_fx(fx)
        check(f"V1 validator mode {mode} -> {expected}, no validator text leaked",
              refused(code, out, err, expected) and no_sentinel(out, err), f"{code} {out!r} {err!r}")
    _validator_behavior["mode"] = "valid"

    # ============================================================
    # F - field-level fail-closed rules.
    # ============================================================
    for state in ("blocked_unverified_anchor", "blocked_missing_rule", "blocked_ambiguous_rule",
                  "needs_review", "not_applicable", None):
        fx = make_fixture(document=with_deadline(calculation_state=state))
        code, out, err = run_fx(fx)
        check(f"F1 calculation_state={state!r} -> calculation_not_calculated",
              refused(code, out, err, "calculation_not_calculated"), f"{code} {out!r} {err!r}")

    for state in ("active", "expired", "unknown", None):
        fx = make_fixture(document=with_deadline(expiry_state=state))
        code, out, err = run_fx(fx)
        check(f"F2 expiry_state={state!r} -> expiry_state_invalid",
              refused(code, out, err, "expiry_state_invalid"), f"{code} {out!r} {err!r}")

    field_cases = [
        ("calculated_deadline", None), ("calculated_deadline", "2026-02-30"), ("calculated_deadline", "12.03.2026"),
        ("anchor_date", "2026-13-01"), ("anchor_date", 20260210),
        ("rule_id", "Ahmet SENTINEL Yılmaz"), ("deadline_id", ""), ("anchor_event_id", "a\nb"),
        ("requires_human_review", "true"), ("requires_human_review", 1),
    ]
    for field, value in field_cases:
        fx = make_fixture(document=with_deadline(**{field: value}))
        code, out, err = run_fx(fx)
        check(f"F3 {field}={value!r} -> field_invalid, nothing leaked",
              refused(code, out, err, "field_invalid") and no_sentinel(out, err), f"{code} {out!r} {err!r}")

    def bad_analysis_id(case_id):
        doc = base_deadline_document(case_id)
        doc["deadline_analysis_id"] = "SENTINEL analysis id"
        return doc

    fx = make_fixture(document=bad_analysis_id)
    code, out, err = run_fx(fx)
    check("F4 malformed deadline_analysis_id -> field_invalid", refused(code, out, err, "field_invalid"),
          f"{code} {out!r} {err!r}")

    # ============================================================
    # K - definite-date gate (remediation): verified anchor + explicit
    #     'none' stopping status + shape-valid attestation ref. Every
    #     refusal: empty stdout, fixed stderr line, no --output file,
    #     calculated_deadline never leaked anywhere.
    # ============================================================
    CALCULATED_DATE = "2026-03-12"
    gate_cases = [
        ("anchor_verification_state", "unverified", "anchor_not_verified"),
        ("anchor_verification_state", "partially_verified", "anchor_not_verified"),
        ("anchor_verification_state", "disputed", "anchor_not_verified"),
        ("anchor_verification_state", "rejected", "anchor_not_verified"),
        ("anchor_verification_state", None, "anchor_not_verified"),
        ("anchor_verification_state", _DELETE, "anchor_not_verified"),
        ("anchor_verification_state", "SENTINEL_state", "anchor_not_verified"),
        ("stopping_event_status", _DELETE, "stopping_event_not_cleared"),
        ("stopping_event_status", "unknown", "stopping_event_not_cleared"),
        ("stopping_event_status", "present", "stopping_event_not_cleared"),
        ("stopping_event_status", None, "stopping_event_not_cleared"),
        ("stopping_event_status", "NONE", "stopping_event_not_cleared"),
        ("stopping_event_status", "none ", "stopping_event_not_cleared"),
        ("stopping_event_status", "maybe", "stopping_event_not_cleared"),
        ("stopping_event_attestation_ref", _DELETE, "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", None, "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", "", "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", "   ", "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", "ATTEST\rREF", "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", "ATTEST\nREF", "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", "ATTEST\r\nREF", "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", "ATTEST\tREF", "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", "x" * 201, "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", 5, "stopping_event_attestation_missing"),
        ("stopping_event_attestation_ref", ["REF"], "stopping_event_attestation_missing"),
    ]
    for field, value, expected_code in gate_cases:
        fx = make_fixture(document=with_deadline(**{field: value}))
        code, out, err = run_fx(fx)
        shown = "<absent>" if value is _DELETE else repr(value)[:24]
        check(f"K1 {field}={shown} -> {expected_code}; calculated_deadline not leaked",
              refused(code, out, err, expected_code) and CALCULATED_DATE not in out + err and no_sentinel(out, err),
              f"{code} {out!r} {err!r}")
        gate_target = _TMP_OUT / f"gate_{uuid.uuid4().hex}.txt"
        code, out, err = run_fx(fx, "--output", str(gate_target))
        check(f"K2 {field}={shown} with --output -> {expected_code}, NO output file created",
              refused(code, out, err, expected_code) and not gate_target.exists()
              and CALCULATED_DATE not in out + err, f"{code} {out!r} {err!r}")

    for label, ref in (("1 char", "R"), ("200 chars", "R" * 200), ("Turkish printable", "Av. beyanı 2026/1")):
        fx = make_fixture(document=with_deadline(stopping_event_attestation_ref=ref))
        code, out, err = run_fx(fx)
        check(f"K3 status none + valid attestation ({label}) -> success, attestation rendered only as VAR",
              code == 0 and err == "" and out == expected_report(fx) and (len(ref) < 3 or ref not in out),
              f"{code} {out!r} {err!r}")

    fx = make_fixture()
    calls_before = len(_validator_calls)
    fx.document["deadlines"][0]["stopping_event_status"] = "unknown"
    fx.raw = json.dumps(fx.document, ensure_ascii=False, indent=2).encode("utf-8")
    fx.deadline_path.write_bytes(fx.raw)
    fx.sha = hashlib.sha256(fx.raw).hexdigest()
    fx.conn.journal[0]["observed_post_hash"] = fx.sha
    fx.audit["canonical_sha256"] = fx.sha
    write_audit(fx, fx.audit, fx.audit_path.name)
    code, out, err = run_fx(fx)
    check("K4 the gate runs AFTER the proofs: validator was consulted before stopping_event_not_cleared",
          refused(code, out, err, "stopping_event_not_cleared") and len(_validator_calls) == calls_before + 1,
          f"{code} {out!r} {err!r}")

    # ============================================================
    # T - canonical changed between the two hash measurements.
    # ============================================================
    _validator_behavior["mode"] = "mutate_file"
    fx = make_fixture()
    code, out, err = run_fx(fx)
    check("T1 canonical bytes changed after the first hash -> canonical_changed",
          refused(code, out, err, "canonical_changed"), f"{code} {out!r} {err!r}")
    _validator_behavior["mode"] = "valid"

    # ============================================================
    # O - --output contract.
    # ============================================================
    fx = make_fixture()
    target = _TMP_OUT / "rapor_ok.txt"
    code, out, err = run_fx(fx, "--output", str(target))
    written = target.read_bytes() if target.exists() else b""
    check("O1 --output success: exit 0, stdout only the RAPOR YAZILDI line",
          code == 0 and err == "" and out == f"RAPOR YAZILDI: {target.resolve()}\n", f"{code} {out!r} {err!r}")
    check("O2 --output bytes == report, UTF-8, no BOM, LF only",
          written == expected_report(fx).encode("utf-8") and not written.startswith(b"\xef\xbb\xbf")
          and b"\r" not in written, f"{written!r}")

    existing = _TMP_OUT / "existing.txt"
    existing.write_bytes(b"ORIGINAL")
    fx = make_fixture()
    code, out, err = run_fx(fx, "--output", str(existing))
    check("O3 existing target -> output_exists, original untouched, DB never opened",
          refused(code, out, err, "output_exists") and existing.read_bytes() == b"ORIGINAL" and fx.factory_calls == 0,
          f"{code} {out!r} {err!r}")

    fx = make_fixture()
    missing_parent = _TMP_OUT / "no_such_dir" / "r.txt"
    code, out, err = run_fx(fx, "--output", str(missing_parent))
    check("O4 missing parent -> output_path_refused, no directory created",
          refused(code, out, err, "output_path_refused") and not missing_parent.parent.exists()
          and fx.factory_calls == 0, f"{code} {out!r} {err!r}")

    in_repo = REPO_ROOT / "ui" / "tests" / f"deadline_report_should_not_exist_{uuid.uuid4().hex}.txt"
    fx = make_fixture()
    code, out, err = run_fx(fx, "--output", str(in_repo))
    check("O5 target inside the repository -> output_path_refused, nothing created",
          refused(code, out, err, "output_path_refused") and not in_repo.exists() and fx.factory_calls == 0,
          f"{code} {out!r} {err!r}")

    in_repo_data = _original_paths_cases_dir / f"rpt_should_not_exist_{uuid.uuid4().hex}.txt"
    fx = make_fixture()
    code, out, err = run_fx(fx, "--output", str(in_repo_data))
    check("O6 target inside the REAL data/cases -> output_path_refused, nothing created",
          refused(code, out, err, "output_path_refused") and not in_repo_data.exists(), f"{code} {out!r} {err!r}")

    fx = make_fixture()
    ads = _TMP_OUT / "file.txt:stream"
    code, out, err = run_fx(fx, "--output", str(ads))
    check("O7 ':' in file name (NTFS stream) -> output_path_refused",
          refused(code, out, err, "output_path_refused"), f"{code} {out!r} {err!r}")

    fx = make_fixture(role="analyst")
    denied_target = _TMP_OUT / "denied.txt"
    code, out, err = run_fx(fx, "--output", str(denied_target))
    check("O8 a refused report never creates the --output file",
          refused(code, out, err, "access_denied") and not denied_target.exists(), f"{code} {out!r} {err!r}")

    # ============================================================
    # R - REAL deadline_validator wiring (tempdir copy of case_0001).
    # ============================================================
    _deadline_validator.validate_deadline_analysis = _real_validate
    real_copy_root = _TMP_ROOT / "real_validator" / "data" / "cases"
    real_copy_root.mkdir(parents=True)
    shutil.copytree(REAL_CASE_0001, real_copy_root / "case_0001")
    holders = [m for m in (_paths, _deadline_validator, _timeline_validator)]
    saved_holders = [(m, m.CASES_DIR) for m in holders]
    for m in holders:
        m.CASES_DIR = real_copy_root
    try:
        copy_deadline = real_copy_root / "case_0001" / "deadlines" / "deadline.json"
        copy_reviews = real_copy_root / "case_0001" / "deadlines" / "reviews"

        def real_fixture_conn(sha, key):
            conn = FakeConn()
            conn.users[ACTOR] = (1, False)
            conn.assignments[(ACTOR, "case_0001")] = "lawyer"
            conn.journal.append({
                "id": 1, "resource_key": "case:case_0001", "action_family": "approval.deadline",
                "state": "completed", "idempotency_key": key, "observed_post_hash": sha,
            })
            return conn

        copy_sha = hashlib.sha256(copy_deadline.read_bytes()).hexdigest()
        conn_r0 = real_fixture_conn(copy_sha, "c" * 64)
        code, out, err = run(["--case", "case_0001", "--actor-user-id", str(ACTOR)], conn_factory=lambda: conn_r0)
        check("R1 real case_0001 copy with its LEGACY audit (no mutation keys) -> approval_not_proven "
              "(R6: legacy is refused, no bypass)", refused(code, out, err, "approval_not_proven"),
              f"{code} {out!r} {err!r}")

        synthetic_key = "d" * 64
        record = audit_for("case_0001", "deadline_case_0001_v1", copy_sha, synthetic_key)
        (copy_reviews / "synthetic_bound.approval.json").write_bytes(json.dumps(record).encode("utf-8"))
        conn_r1 = real_fixture_conn(copy_sha, synthetic_key)
        code, out, err = run(["--case", "case_0001", "--actor-user-id", str(ACTOR)], conn_factory=lambda: conn_r1)
        check("R2 REAL validator passes (valid, 0 warnings) on the case_0001 copy, then the blocked "
              "calculation_state is refused -> calculation_not_calculated",
              refused(code, out, err, "calculation_not_calculated"), f"{code} {out!r} {err!r}")

        tampered = json.loads(copy_deadline.read_bytes().decode("utf-8"))
        tampered["deadlines"][0]["anchor_date"] = "2026-02-11"
        tampered_raw = json.dumps(tampered, ensure_ascii=False, indent=2).encode("utf-8")
        copy_deadline.write_bytes(tampered_raw)
        tampered_sha = hashlib.sha256(tampered_raw).hexdigest()
        record_t = audit_for("case_0001", "deadline_case_0001_v1", tampered_sha, "e" * 64)
        (copy_reviews / "synthetic_bound.approval.json").write_bytes(json.dumps(record_t).encode("utf-8"))
        conn_r2 = real_fixture_conn(tampered_sha, "e" * 64)
        code, out, err = run(["--case", "case_0001", "--actor-user-id", str(ACTOR)], conn_factory=lambda: conn_r2)
        check("R3 REAL validator rejects an anchor_date that no longer matches the canonical timeline "
              "-> validator_failed, and its error text (dates) is NOT shown",
              refused(code, out, err, "validator_failed") and "2026-02-11" not in out + err
              and "Timeline" not in out + err, f"{code} {out!r} {err!r}")
    finally:
        for m, value in saved_holders:
            m.CASES_DIR = value
        _paths.CASES_DIR = _TMP_CASES
        _deadline_validator.validate_deadline_analysis = _fake_validate

    # ============================================================
    # E - real OS subprocess: UTF-8/LF bytes, no traceback.
    # ============================================================
    child_env = os.environ.copy()
    for name in ("PYTHONIOENCODING", "PYTHONUTF8", "VERGI_IAM_DATABASE_URL"):
        child_env.pop(name, None)

    proc = subprocess.run(
        [sys.executable, "-m", "ui.deadline_report", "--case", "c1", "--actor-user-id", "7"],
        cwd=str(REPO_ROOT), env=child_env, stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
    )
    check("E1 real `python -m ui.deadline_report` without a DSN: exit 1, empty stdout, stderr is EXACTLY the "
          "UTF-8/LF database_unavailable line (no traceback)",
          proc.returncode == 1 and proc.stdout == b""
          and proc.stderr == "RAPOR REDDEDİLDİ: database_unavailable\n".encode("utf-8"),
          f"rc={proc.returncode} out={proc.stdout!r} err={proc.stderr!r}")

    driver = _TMP_ROOT / "driver_ok.py"
    fields = {
        "case_id": "c1", "deadline_id": "deadline_001", "anchor_event_id": "timeline_event_001",
        "anchor_date": "2026-02-10", "anchor_verification_state": "verified",
        "rule_id": "iyuk_tax_court_general_lawsuit_filing", "calculated_deadline": "2026-03-12",
        "calculation_state": "calculated", "requires_human_review": True, "stopping_event_status": "none",
        "canonical_sha256": "a" * 64,
    }
    driver.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "import ui.deadline_report as dr\n"
        f"FIELDS = {fields!r}\n"
        "dr.build_report = lambda *a, **k: dr._render_report(FIELDS)\n"
        "sys.argv = ['deadline_report', '--case', 'c1', '--actor-user-id', '7']\n"
        "sys.exit(dr._console_entrypoint())\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(driver)], cwd=str(REPO_ROOT), env=child_env,
        stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
    )
    expected_bytes = dr._render_report(fields).encode("utf-8")
    check("E2 console entrypoint writes the report as strict UTF-8 with LF only (Turkish characters intact, "
          "no cp1254, no CRLF) on a redirected stdout",
          proc.returncode == 0 and proc.stdout == expected_bytes and b"\r" not in proc.stdout
          and "DEĞERLENDİRİLMEDİ".encode("utf-8") in proc.stdout,
          f"rc={proc.returncode} out={proc.stdout!r} err={proc.stderr!r}")

    for label, raiser in (
        ("RuntimeError", f"raise RuntimeError({SENT_EXCEPTION!r})"),
        ("KeyboardInterrupt", "raise KeyboardInterrupt()"),
    ):
        driver_fail = _TMP_ROOT / f"driver_{label}.py"
        driver_fail.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "import ui.deadline_report as dr\n"
            "def boom(*a, **k):\n"
            f"    {raiser}\n"
            "dr.build_report = boom\n"
            "sys.argv = ['deadline_report', '--case', 'c1', '--actor-user-id', '7']\n"
            "sys.exit(dr._console_entrypoint())\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(driver_fail)], cwd=str(REPO_ROOT), env=child_env,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
        )
        check(f"E3 unexpected {label} -> exit 1, empty stdout, ONLY the fixed internal_error line "
              "(no traceback, no exception text/path)",
              proc.returncode == 1 and proc.stdout == b""
              and proc.stderr == "RAPOR REDDEDİLDİ: internal_error\n".encode("utf-8"),
              f"rc={proc.returncode} out={proc.stdout!r} err={proc.stderr!r}")

    # ENCODING-FAILURE FALLBACK: stdout (or stderr) cannot be switched to
    # UTF-8 -> the ONLY output is the ASCII fallback line + LF, exit 1;
    # build_report is never reached (its sentinel never appears).
    for label, stream in (("stdout", "stdout"), ("stderr", "stderr")):
        driver_enc = _TMP_ROOT / f"driver_encoding_{label}.py"
        driver_enc.write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "import ui.deadline_report as dr\n"
            "class _NoReconfigure:\n"
            "    def __init__(self, real):\n"
            "        object.__setattr__(self, '_real', real)\n"
            "    def reconfigure(self, **kwargs):\n"
            f"        raise OSError({SENT_EXCEPTION!r})\n"
            "    def __getattr__(self, name):\n"
            "        return getattr(self._real, name)\n"
            f"sys.{stream} = _NoReconfigure(sys.{stream})\n"
            "def _report(*a, **k):\n"
            f"    print({SENT_VALIDATOR!r})\n"
            f"    return dr._render_report({fields!r})\n"
            "dr.build_report = _report\n"
            "sys.argv = ['deadline_report', '--case', 'c1', '--actor-user-id', '7']\n"
            "sys.exit(dr._console_entrypoint())\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(driver_enc)], cwd=str(REPO_ROOT), env=child_env,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
        )
        check(f"E4 encoding-failure fallback ({label} reconfigure fails): exit 1, empty stdout, stderr is EXACTLY "
              "the ASCII 'RAPOR REDDEDILDI: internal_error' + LF - no traceback, no second line, no report/date",
              proc.returncode == 1 and proc.stdout == b""
              and proc.stderr == b"RAPOR REDDEDILDI: internal_error\n",
              f"rc={proc.returncode} out={proc.stdout!r} err={proc.stderr!r}")
    check("E5 the encoding-failure fallback line is pure ASCII and LF-terminated",
          dr.ENCODING_FAILURE_FALLBACK_LINE == b"RAPOR REDDEDILDI: internal_error\n"
          and dr.ENCODING_FAILURE_FALLBACK_LINE.isascii())

    # ============================================================
    # S - static source guarantees.
    # ============================================================
    source = Path(dr.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    string_constants = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    forbidden_sql = ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE", "ALTER ", "DROP ", "GRANT ", "CREATE ")
    check("S1 no string constant in the module carries a write/DDL SQL keyword",
          not any(k in s for s in string_constants for k in forbidden_sql))
    sql_constants = [s for s in string_constants if "FROM " in s or "current_setting" in s]
    check("S2 every SQL string constant starts with SELECT",
          sql_constants and all(s.lstrip().startswith("SELECT") for s in sql_constants), f"{sql_constants!r}")
    attr_calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    check("S3 the module never calls .commit()", "commit" not in attr_calls)
    check("S4 no string constant references a .pending file", not any(".pending" in s for s in string_constants))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    check("S5 module imports no network/LLM/dotenv library",
          not imported & {"anthropic", "openai", "httpx", "requests", "urllib", "socket", "dotenv", "http"},
          f"{imported!r}")
    check("S6 the refusal-code allowlist contains every code this module can raise",
          all(c in dr.REFUSAL_CODES for c in (
              "access_denied", "journal_unresolved_mutation", "approval_not_proven", "ambiguous_approval",
              "validator_failed", "validator_warnings", "calculation_not_calculated", "expiry_state_invalid",
              "anchor_not_verified", "stopping_event_not_cleared", "stopping_event_attestation_missing",
              "canonical_changed", "internal_error")))

finally:
    _deadline_validator.validate_deadline_analysis = _real_validate
    _paths.CASES_DIR = _original_paths_cases_dir
    socket.socket.connect = _orig_socket_connect
    socket.create_connection = _orig_create_connection
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)

check("G1 zero in-process network attempts", not _network_attempts, f"{_network_attempts!r}")
check("G2 no LLM/network client module was imported in-process",
      not any(m in sys.modules for m in ("anthropic", "openai", "dotenv")),
      f"{[m for m in ('anthropic', 'openai', 'dotenv') if m in sys.modules]!r}")
check("G3 real data/ tree byte-identical before/after (incl. ignored data/cases)",
      snapshot_data_tree() == _data_tree_before)
check("G4 tempdir cleaned up", not _TMP_ROOT.exists())

print(f"--- test_deadline_report_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
