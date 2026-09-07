# ============================================================
# Row 19C-2a Step 6 - isolated (fake-adapter-module, fake-journal-
# connection) tests for ui/services/mutation_approval_facade.py.
#
# This file exercises `approve_case_scoped_mutation()` end to end
# against:
#   - a REAL `mutation.mutation_journal` FAKE table/cursor (the exact
#     same shape ui/tests/test_mutation_coordinator_isolated.py's own
#     FakeJournalCursor/FakeJournalConn already proves correct against
#     the real ui.services.mutation_coordinator.run_mutation() - a
#     fresh, self-contained copy here, matching this project's
#     existing convention of each test file owning its own fakes);
#   - REAL `ui.services.authz.authorize_case_access()`, `ui.services.
#     paths.resolve_case_id()`, and a REAL, temporary
#     `data/cases/<case_id>/` filesystem fixture (this project's own
#     shared allowlist/containment choke point is never bypassed or
#     mocked here - a fabricated case_id that does not exist as a real
#     directory would genuinely fail authorization, exactly as it
#     would in production);
#   - a FAKE case-scoped approval "family" module (mimicking
#     src/deadline_approval.py's own get_pending_path/get_canonical_
#     path/run_approve shape) registered into `ROW_KEY_TO_MODULE_NAME`
#     under a test-only row_key, so this file never needs any of the
#     10 real src/*_approval.py modules' own (heavier, not fully
#     staged-in-sandbox-importable) dependencies;
#   - `ui.services.mutation_lock.acquire_case_lock_session`/
#     `release_lock_session` MONKEYPATCHED to fakes (same pattern
#     ui/tests/test_reconciliation_isolated.py and ui/tests/
#     test_reconciliation_operator_isolated.py already use) - this
#     module calls those two REAL functions directly (unlike
#     mutation_coordinator.run_mutation(), which never acquires/
#     releases a lock itself), so faking them here is this file's own
#     addition, not a copy of an existing pattern.
#
# Run: python -m ui.tests.test_mutation_approval_facade_isolated
# ============================================================

import hashlib
import json
import shutil
import sys
import types
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import authz as _authz                              # noqa: E402
from ui.services import mutation_approval_facade as facade            # noqa: E402
from ui.services import mutation_lock as ml                            # noqa: E402
from ui.services import paths as _paths                                # noqa: E402
from ui.services.common import PendingNotFoundError, StaleViewError    # noqa: E402

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
# Fake mutation.mutation_journal table + cursor - a fresh copy of
# ui/tests/test_mutation_coordinator_isolated.py's own FakeJournalCursor/
# FakeJournalConn (proven correct there against the REAL run_mutation()
# across 99 checks) - this file needs the exact same SQL shapes since
# it exercises run_mutation() through the real, unmodified facade.
# ----------------------------------------------------------------

class FakeIntegrityError(Exception):
    pass


class FakeJournalCursor:
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
        raise AssertionError(f"no fake journal row with id={journal_id}")

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._calls.append(normalized.split()[0])

        if normalized.startswith("SELECT 1 FROM mutation.mutation_journal"):
            (resource_key,) = params
            hit = any(
                r["resource_key"] == resource_key
                and r["state"] in ("prepared", "executing", "reconciliation_required")
                for r in self._table
            )
            self._last_result = (1,) if hit else None
            self.rowcount = 1 if hit else 0

        elif normalized.startswith("SELECT id, state, request_fingerprint, observed_post_hash"):
            (idempotency_key,) = params
            matches = [r for r in self._table if r["idempotency_key"] == idempotency_key]
            if not matches:
                self._last_result = None
                self.rowcount = 0
            else:
                r = matches[0]
                self._last_result = (
                    r["id"], r["state"], r["request_fingerprint"], r["observed_post_hash"],
                    r["failure_code"], r["resolution_code"],
                )
                self.rowcount = 1

        elif normalized.startswith("INSERT INTO mutation.mutation_journal"):
            (
                resource_key, action_family, actor_user_id, actor_label, target_ref, target_state,
                pre_hash, pre_revision, idempotency_key, request_fingerprint,
            ) = params
            conflict = any(r["idempotency_key"] == idempotency_key for r in self._table)
            if conflict:
                raise FakeIntegrityError(
                    f"duplicate key value violates unique constraint "
                    f"\"mutation_journal_idempotency_key_uniq\": idempotency_key={idempotency_key!r}"
                )
            new_id = len(self._table) + 1
            self._table.append({
                "id": new_id,
                "resource_key": resource_key,
                "action_family": action_family,
                "actor_user_id": actor_user_id,
                "actor_label": actor_label,
                "target_ref": target_ref,
                "target_state": target_state,
                "pre_hash": pre_hash,
                "pre_revision": pre_revision,
                "idempotency_key": idempotency_key,
                "request_fingerprint": request_fingerprint,
                "state": "prepared",
                "failure_code": None,
                "resolution_code": None,
                "executing_at": None,
                "resolved_at": None,
                "observed_post_hash": None,
            })
            self._last_result = (new_id,)
            self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'executing'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "executing"
            self._row(journal_id)["executing_at"] = "FAKE_TIMESTAMP"
            self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'completed'"):
            observed_post_hash, journal_id = params
            row = self._row(journal_id)
            row["state"] = "completed"
            row["observed_post_hash"] = observed_post_hash
            row["resolved_at"] = "FAKE_TIMESTAMP"
            self.rowcount = 1

        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'reconciliation_required'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "reconciliation_required"
            self.rowcount = 1

        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._last_result


class FakeJournalConn:
    def __init__(self, table=None):
        self.table = table if table is not None else []
        self.calls = []
        self.closed = False

    def cursor(self):
        return FakeJournalCursor(self.table, self.calls)

    def close(self):
        # ui.services.mutation_approval_facade.approve_case_scoped_mutation()
        # always closes the connection it got from conn_factory() in its
        # own `finally` block (mirroring ui.services.db.get_session_lock_
        # connection()'s real, closeable connection) - a real psycopg
        # connection is always closeable, so the fake must be too.
        self.closed = True


# ----------------------------------------------------------------
# Lock monkeypatch - see this file's own header comment.
# ----------------------------------------------------------------

_lock_calls = []
_original_acquire_case = ml.acquire_case_lock_session
_original_release = ml.release_lock_session


def _fake_acquire_case_lock_session(conn, case_id):
    _lock_calls.append(("acquire", case_id))
    return 111


def _fake_release_lock_session(conn, advisory_lock_id):
    _lock_calls.append(("release", advisory_lock_id))
    return True


# ----------------------------------------------------------------
# Real filesystem fixtures - a genuine data/cases/<case_id>/ directory
# per test case_id, so ui.services.paths.resolve_case_id() (called for
# real, inside ui.services.authz.authorize_case_access(), never
# mocked) genuinely succeeds. Cleaned up at the very end.
# ----------------------------------------------------------------

_created_case_dirs = []


def make_case(pending_content='{"x": 1}'):
    case_id = f"facadetest{uuid.uuid4().hex[:10]}"
    case_dir = _paths.CASES_DIR / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "case.json").write_text("{}", encoding="utf-8")
    _created_case_dirs.append(case_dir)
    pending_path = case_dir / "pending.json"
    if pending_content is not None:
        pending_path.write_text(pending_content, encoding="utf-8")
    return case_id, case_dir, pending_path


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_principal_and_repo(case_id, *, assigned=True, role="lawyer"):
    principal = _authz.Principal(user_id=1, session_id=100, role_version_at_issue=1)
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[100] = _authz.SessionRecord(user_id=1, current_authz_version=1, disabled=False)
    if assigned:
        repo.assignments[(1, case_id)] = _authz.CaseAssignmentRecord(role=role)
    return principal, repo


def make_fake_module(name, *, raise_on_approve=None, on_approve_hook=None):
    """A minimal stand-in for one of the 10 real src/*_approval.py
    modules - just enough of get_pending_path/get_canonical_path/
    run_approve for the facade to drive for real, writing a REAL audit
    JSON record shaped exactly like Row 19C-2a's own
    write_approval_audit() output. In particular it reproduces all
    THREE fields the facade's FOUR EXACT BINDINGS check reads back:
    `mutation_idempotency_key`, `mutation_resource_key` and
    `canonical_sha256` (that last one is NOT new - all 10 real families
    have always written it).

    `run_approve`'s two audit-binding parameters are KEYWORD-ONLY here,
    exactly as all 10 real modules' now are (verified by AST across
    every one of them) - so this fake would genuinely reject a
    positional caller too, and cannot drift into accepting a shape
    production would refuse."""
    mod = types.ModuleType(name)
    run_approve_calls = []

    def get_pending_path(case_id):
        return _paths.CASES_DIR / case_id / "pending.json"

    def get_canonical_path(case_id):
        return _paths.CASES_DIR / case_id / "canonical.json"

    def run_approve(case_id, *, mutation_idempotency_key=None, mutation_resource_key=None):
        run_approve_calls.append((case_id, mutation_idempotency_key, mutation_resource_key))
        if raise_on_approve is not None:
            raise raise_on_approve
        pending_path = get_pending_path(case_id)
        canonical_path = get_canonical_path(case_id)
        canonical_path.write_text(pending_path.read_text(encoding="utf-8"), encoding="utf-8")
        reviews_dir = canonical_path.parent / "reviews"
        reviews_dir.mkdir(parents=True, exist_ok=True)
        audit = {
            "audit_type": "fake_family_approval",
            "mutation_idempotency_key": mutation_idempotency_key,
            "mutation_resource_key": mutation_resource_key,
            "canonical_sha256": sha256_text(canonical_path.read_text(encoding="utf-8")),
            # ROW 19C-2a FINAL AUDIT REMEDIATION: binding 5
            # (`audit.pending_sha256 == journal/request pre_revision`)
            # needs this field. It is NOT new and NOT invented for the
            # test - all 10 real src/*_approval.py families have
            # written `pending_sha256` since long before Row 19C-2a
            # (verified across every one of them), so a fake that
            # omitted it was simply an unfaithful stand-in.
            "pending_sha256": sha256_text(pending_path.read_text(encoding="utf-8")),
            "case_id": case_id,
        }
        audit_path = reviews_dir / f"fake_{uuid.uuid4().hex}.approval.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        print(f"approved {case_id}")
        if on_approve_hook is not None:
            on_approve_hook(case_id)

    mod.get_pending_path = get_pending_path
    mod.get_canonical_path = get_canonical_path
    mod.run_approve = run_approve
    mod.run_approve_calls = run_approve_calls
    return mod


_original_row_key_mapping = dict(facade.ROW_KEY_TO_MODULE_NAME)

try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.release_lock_session = _fake_release_lock_session

    fake_mod = make_fake_module("_fake_approval_mod_facade_test_1")
    sys.modules["_fake_approval_mod_facade_test_1"] = fake_mod
    facade.ROW_KEY_TO_MODULE_NAME = dict(_original_row_key_mapping, test_family="_fake_approval_mod_facade_test_1")

    # ------------------------------------------------------------
    # 1) Fresh (non-replayed) approval - the full happy path.
    # ------------------------------------------------------------

    case_id, case_dir, pending_path = make_case()
    expected_hash = sha256_text(pending_path.read_text(encoding="utf-8"))
    principal, repo = make_principal_and_repo(case_id)
    conn = FakeJournalConn()

    result = facade.approve_case_scoped_mutation(
        "test_family", case_id, expected_hash,
        principal=principal, authz_repository=repo, conn_factory=lambda: conn,
    )

    check("fresh approval: replayed=False", result.replayed is False)
    check("fresh approval: run_approve was called exactly once", len(fake_mod.run_approve_calls) == 1)
    check(
        "fresh approval: canonical file now matches the pending content",
        result.canonical_path.read_text(encoding="utf-8") == pending_path.read_text(encoding="utf-8"),
    )
    check(
        "fresh approval: canonical_hash matches the real canonical file's own sha256",
        result.canonical_hash == sha256_text(result.canonical_path.read_text(encoding="utf-8")),
    )
    check("fresh approval: audit_path was found and really exists on disk", result.audit_path is not None and result.audit_path.exists())
    audit_record = json.loads(result.audit_path.read_text(encoding="utf-8"))
    check(
        "fresh approval: the REAL audit record's mutation_idempotency_key is a real, non-empty string",
        isinstance(audit_record["mutation_idempotency_key"], str) and bool(audit_record["mutation_idempotency_key"]),
    )
    check(
        "fresh approval: the REAL audit record's mutation_resource_key is bound to 'case:<case_id>'",
        audit_record["mutation_resource_key"] == f"case:{case_id}",
    )
    check(
        "fresh approval: run_approve received BOTH audit-binding kwargs (idempotency_key AND resource_key)",
        fake_mod.run_approve_calls[0][1] == audit_record["mutation_idempotency_key"]
        and fake_mod.run_approve_calls[0][2] == f"case:{case_id}",
    )
    check(
        "fresh approval: the audit record's canonical_sha256 equals the canonical file's real hash",
        audit_record["canonical_sha256"] == sha256_text(result.canonical_path.read_text(encoding="utf-8")),
    )
    check("fresh approval: stdout captured run_approve's own print() output", f"approved {case_id}" in result.stdout)
    check(
        "fresh approval: exactly one journal row exists, ending in state='completed'",
        len(conn.table) == 1 and conn.table[0]["state"] == "completed",
    )
    check("fresh approval: journal row's resource_key is 'case:<case_id>'", conn.table[0]["resource_key"] == f"case:{case_id}")
    check("fresh approval: journal row's action_family is 'approval.test_family'", conn.table[0]["action_family"] == "approval.test_family")
    check("fresh approval: journal row's target_ref is 'test_family.canonical'", conn.table[0]["target_ref"] == "test_family.canonical")
    check("fresh approval: journal row's target_state is 'approved'", conn.table[0]["target_state"] == "approved")
    check("fresh approval: journal row's actor_user_id is the principal's user_id", conn.table[0]["actor_user_id"] == 1)
    check("fresh approval: journal row's actor_label is the principal's user_id as a string", conn.table[0]["actor_label"] == "1")
    check(
        "fresh approval: journal row's pre_revision is the REQUEST's own claimed expected_hash",
        conn.table[0]["pre_revision"] == expected_hash,
    )
    check(
        "fresh approval: journal row's pre_hash is the COMPOSITE snapshot digest, NOT the bare pending hash",
        conn.table[0]["pre_hash"] != expected_hash
        and isinstance(conn.table[0]["pre_hash"], str)
        and len(conn.table[0]["pre_hash"]) == 64,
    )
    check("fresh approval: the lock was acquired for the RESOLVED case_id", ("acquire", case_id) in _lock_calls)
    check("fresh approval: the lock was released afterwards", ("release", 111) in _lock_calls)

    # The composite pre_hash recorded on the journal row must be
    # EXACTLY what _compute_precondition_snapshot() produces for the
    # pre-mutation state (pending present, canonical still ABSENT) -
    # recomputed here independently, from the same public helper.
    expected_pre_snapshot = facade._compute_precondition_snapshot(
        pending_path, _paths.CASES_DIR / case_id / "no_such_canonical_yet.json",
    )
    check(
        "fresh approval: the recorded pre_hash matches an independently recomputed pre-state snapshot "
        "(pending present, canonical absent)",
        conn.table[0]["pre_hash"] == expected_pre_snapshot.composite_digest,
    )
    check(
        "snapshot: a pending-present/canonical-absent snapshot records both facts faithfully",
        expected_pre_snapshot.pending_sha256 == expected_hash
        and expected_pre_snapshot.canonical_presence == facade.SNAPSHOT_ABSENT
        and expected_pre_snapshot.canonical_sha256 == facade.SNAPSHOT_ABSENT,
    )
    check(
        "snapshot: the SAME three facts always produce the SAME composite digest (deterministic)",
        facade._compute_precondition_snapshot(
            pending_path, _paths.CASES_DIR / case_id / "no_such_canonical_yet.json",
        ).composite_digest == expected_pre_snapshot.composite_digest,
    )
    check(
        "snapshot: a CHANGED canonical side alone changes the composite digest (a pending-only check "
        "would have missed it)",
        facade._compute_precondition_snapshot(pending_path, result.canonical_path).composite_digest
        != expected_pre_snapshot.composite_digest,
    )

    # ------------------------------------------------------------
    # 2) Safe replay - same (row_key, case_id, expected_hash,
    #    principal) -> same idempotency_key/fingerprint. The writer
    #    must NOT be re-invoked; the SAME journal row is returned.
    # ------------------------------------------------------------

    result2 = facade.approve_case_scoped_mutation(
        "test_family", case_id, expected_hash,
        principal=principal, authz_repository=repo, conn_factory=lambda: conn,
    )
    check("replay: replayed=True", result2.replayed is True)
    check("replay: run_approve was NOT re-invoked", len(fake_mod.run_approve_calls) == 1)
    check("replay: the SAME journal_id is returned", result2.journal_id == result.journal_id)
    check("replay: canonical_hash is unchanged from the fresh result", result2.canonical_hash == result.canonical_hash)
    check("replay: stdout is empty (nothing new was written)", result2.stdout == "")
    check("replay: no NEW journal row was created", len(conn.table) == 1)

    # ------------------------------------------------------------
    # 3) Tampered audit record on a subsequent replay -> the request-
    #    time audit-binding check catches it for real.
    # ------------------------------------------------------------

    tampered = dict(audit_record)
    tampered["mutation_idempotency_key"] = "bogus-key-does-not-match-anything"
    result.audit_path.write_text(json.dumps(tampered), encoding="utf-8")

    expect_raises(
        facade.AuditBindingVerificationFailedError,
        lambda: facade.approve_case_scoped_mutation(
            "test_family", case_id, expected_hash,
            principal=principal, authz_repository=repo, conn_factory=lambda: conn,
        ),
        "a replay whose latest audit record's mutation_idempotency_key does NOT match raises "
        "AuditBindingVerificationFailedError",
    )
    check("tampered-audit replay: run_approve was STILL never re-invoked", len(fake_mod.run_approve_calls) == 1)
    check("tampered-audit replay: no journal row was added/removed", len(conn.table) == 1)

    # ------------------------------------------------------------
    # 4) Missing audit record entirely on a subsequent replay.
    # ------------------------------------------------------------

    shutil.rmtree(result.audit_path.parent)
    expect_raises(
        facade.AuditBindingVerificationFailedError,
        lambda: facade.approve_case_scoped_mutation(
            "test_family", case_id, expected_hash,
            principal=principal, authz_repository=repo, conn_factory=lambda: conn,
        ),
        "a replay with NO audit record at all (reviews/ removed) raises AuditBindingVerificationFailedError",
    )

    # ------------------------------------------------------------
    # 5) PendingNotFoundError - no pending file exists at all. Fails
    #    closed with NO journal row created (authz succeeds, but
    #    precondition_callback fails before any INSERT).
    # ------------------------------------------------------------

    case_id5, case_dir5, _ = make_case(pending_content=None)
    principal5, repo5 = make_principal_and_repo(case_id5)
    conn5 = FakeJournalConn()
    pre_calls_5 = len(fake_mod.run_approve_calls)
    expect_raises(
        PendingNotFoundError,
        lambda: facade.approve_case_scoped_mutation(
            "test_family", case_id5, "irrelevant-hash", principal=principal5, authz_repository=repo5,
            conn_factory=lambda: conn5,
        ),
        "no pending file at all raises PendingNotFoundError",
    )
    check("PendingNotFoundError: no journal row was created", conn5.table == [])
    check("PendingNotFoundError: run_approve was never invoked", len(fake_mod.run_approve_calls) == pre_calls_5)

    # ------------------------------------------------------------
    # 6) StaleViewError - expected_hash does not match the REAL
    #    current pending file's hash.
    # ------------------------------------------------------------

    case_id6, case_dir6, pending_path6 = make_case()
    principal6, repo6 = make_principal_and_repo(case_id6)
    conn6 = FakeJournalConn()
    expect_raises(
        StaleViewError,
        lambda: facade.approve_case_scoped_mutation(
            "test_family", case_id6, "this-does-not-match-the-real-pending-hash",
            principal=principal6, authz_repository=repo6, conn_factory=lambda: conn6,
        ),
        "a stale expected_hash raises StaleViewError",
    )
    check("StaleViewError: no journal row was created", conn6.table == [])

    # ------------------------------------------------------------
    # 7) OUTER AUTHZ DENIAL - the dual-authz contract's headline
    #    property: an unauthorized caller costs NOTHING and reveals
    #    NOTHING. ZERO connections opened, ZERO lock calls, ZERO
    #    filesystem hash reads, ZERO journal SQL - all four proven
    #    directly by instrumentation, not inferred.
    #
    #    `conn_factory` is a COUNTING factory here rather than
    #    `lambda: conn7`: if the outer denial ever regressed into
    #    opening a connection, this test must FAIL rather than quietly
    #    succeed because a connection object happened to be available.
    # ------------------------------------------------------------

    case_id7, case_dir7, pending_path7 = make_case()
    principal7, repo7 = make_principal_and_repo(case_id7, assigned=False)

    conn_factory_calls = []

    def counting_conn_factory():
        conn_factory_calls.append(1)
        return FakeJournalConn()

    _lock_calls.clear()
    _original_sha256_file = facade.sha256_file
    sha256_read_calls = []

    def counting_sha256_file(path):
        sha256_read_calls.append(str(path))
        return _original_sha256_file(path)

    try:
        facade.sha256_file = counting_sha256_file
        expect_raises(
            _authz.CaseAccessDeniedError,
            lambda: facade.approve_case_scoped_mutation(
                "test_family", case_id7, "irrelevant", principal=principal7, authz_repository=repo7,
                conn_factory=counting_conn_factory,
            ),
            "an unassigned case raises CaseAccessDeniedError from the OUTER authz check",
        )
    finally:
        facade.sha256_file = _original_sha256_file

    check("outer authz denial: ZERO journal/lock connections were opened", conn_factory_calls == [])
    check("outer authz denial: ZERO lock calls (never acquired, so nothing to release)", _lock_calls == [])
    check("outer authz denial: ZERO filesystem hash reads", sha256_read_calls == [])
    check(
        "outer authz denial: run_approve was never invoked",
        len(fake_mod.run_approve_calls) == 1,
    )

    # The same denial, now with a REAL (inspectable) fake connection
    # available - proving the zero-SQL half of the claim explicitly:
    # not one statement of ANY kind reached the journal connection.
    conn7 = FakeJournalConn()
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: facade.approve_case_scoped_mutation(
            "test_family", case_id7, "irrelevant", principal=principal7, authz_repository=repo7,
            conn_factory=lambda: conn7,
        ),
        "the outer authz denial is reproducible with a real fake connection injected",
    )
    check("outer authz denial: ZERO journal SQL statements were executed", conn7.calls == [])
    check("outer authz denial: no journal row was created", conn7.table == [])
    check("outer authz denial: the injected connection was never even closed (never opened/used)", conn7.closed is False)

    # A DISABLED user and a REVOKED session are denied by the very same
    # outer check, with the very same zero-effect profile - the denial
    # is not specific to the "unassigned" reason code.
    case_id7b, _, _ = make_case()
    principal7b, repo7b = make_principal_and_repo(case_id7b)
    repo7b.sessions[100] = _authz.SessionRecord(user_id=1, current_authz_version=1, disabled=True)
    conn7b = FakeJournalConn()
    _lock_calls.clear()
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: facade.approve_case_scoped_mutation(
            "test_family", case_id7b, "irrelevant", principal=principal7b, authz_repository=repo7b,
            conn_factory=lambda: conn7b,
        ),
        "a DISABLED user is denied by the same outer check",
    )
    check(
        "outer authz denial (disabled user): still ZERO SQL, ZERO lock calls, ZERO journal rows",
        conn7b.calls == [] and _lock_calls == [] and conn7b.table == [],
    )

    # ------------------------------------------------------------
    # 7c) INNER (UNDER-LOCK) AUTHZ - the authoritative half of the
    #     dual-authz contract. The outer check is a pre-lock read of
    #     MUTABLE IAM state; a revocation committed while this request
    #     waited for the case lock must still be caught. Simulated by a
    #     repository that PASSES the outer call and then revokes itself
    #     before the inner one.
    # ------------------------------------------------------------

    case_id7c, _, pending_path7c = make_case()
    expected_hash7c = sha256_text(pending_path7c.read_text(encoding="utf-8"))
    principal7c, repo7c = make_principal_and_repo(case_id7c)

    class RevokeAfterOuterRepository:
        """Delegates to a real InMemoryAuthzRepository, but revokes the
        case assignment immediately after the FIRST (outer)
        authorization completes - so the SECOND (inner, under-lock)
        call genuinely fails. If the facade ever stopped re-checking
        authz under the lock, this test would FAIL by succeeding."""

        def __init__(self, inner, case_id):
            self._inner = inner
            self._case_id = case_id
            self.capability_calls = 0

        def get_session_authz_state(self, principal):
            return self._inner.get_session_authz_state(principal)

        def get_active_case_assignment(self, user_id, case_id):
            assignment = self._inner.get_active_case_assignment(user_id, case_id)
            self.capability_calls += 1
            if self.capability_calls == 1:
                # The outer call succeeds; the revocation lands right
                # after it, i.e. exactly while the lock is being taken.
                self._inner.assignments.pop((user_id, self._case_id), None)
            return assignment

    repo7c_wrapped = RevokeAfterOuterRepository(repo7c, case_id7c)
    conn7c = FakeJournalConn()
    _lock_calls.clear()
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: facade.approve_case_scoped_mutation(
            "test_family", case_id7c, expected_hash7c, principal=principal7c,
            authz_repository=repo7c_wrapped, conn_factory=lambda: conn7c,
        ),
        "an assignment revoked AFTER the outer check is still caught by the INNER, under-lock check",
    )
    check(
        "inner authz denial: authorize_case_access really ran TWICE (outer + inner)",
        repo7c_wrapped.capability_calls == 2,
    )
    check("inner authz denial: no journal row was created", conn7c.table == [])
    check(
        "inner authz denial: ZERO journal gate/idempotency SQL ran (authz precedes every journal query)",
        conn7c.calls == [],
    )
    check(
        "inner authz denial: the lock WAS acquired and WAS released (the inner check runs under it)",
        ("acquire", case_id7c) in _lock_calls and ("release", 111) in _lock_calls,
    )

    # ------------------------------------------------------------
    # 8) Writer exception - the ORIGINAL exception propagates
    #    unchanged, and the journal row ends in 'reconciliation_required'
    #    (never 'failed' - see mutation_coordinator.py's own ordering
    #    contract).
    # ------------------------------------------------------------

    case_id8, case_dir8, pending_path8 = make_case()
    expected_hash8 = sha256_text(pending_path8.read_text(encoding="utf-8"))
    boom = RuntimeError("writer exploded - not evidence of anything")
    fake_mod8 = make_fake_module("_fake_approval_mod_facade_test_8", raise_on_approve=boom)
    sys.modules["_fake_approval_mod_facade_test_8"] = fake_mod8
    facade.ROW_KEY_TO_MODULE_NAME["test_family_8"] = "_fake_approval_mod_facade_test_8"
    principal8, repo8 = make_principal_and_repo(case_id8)
    conn8 = FakeJournalConn()

    expect_raises(
        RuntimeError,
        lambda: facade.approve_case_scoped_mutation(
            "test_family_8", case_id8, expected_hash8, principal=principal8, authz_repository=repo8,
            conn_factory=lambda: conn8,
        ),
        "the writer's own exception propagates unchanged out of the facade",
    )
    check(
        "writer exception: the journal row ends in 'reconciliation_required', never 'failed'",
        len(conn8.table) == 1 and conn8.table[0]["state"] == "reconciliation_required",
    )

    # ------------------------------------------------------------
    # 9) An unknown row_key fails closed with KeyError, BEFORE any
    #    lock is even acquired.
    # ------------------------------------------------------------

    _lock_calls.clear()
    expect_raises(
        KeyError,
        lambda: facade.approve_case_scoped_mutation(
            "no_such_family_at_all", "whatever-case-id", "x", principal=principal, authz_repository=repo,
            conn_factory=lambda: FakeJournalConn(),
        ),
        "an unrecognized row_key raises KeyError",
    )
    check("unknown row_key: no lock was ever acquired", _lock_calls == [])

    # ------------------------------------------------------------
    # 10) PRECONDITION RACE - the composite snapshot's whole reason for
    #     existing. Another writer changes the case's files WHILE this
    #     request waits for the lock; the under-lock recomputation must
    #     catch it, with ZERO prepared rows and ZERO writer calls.
    #
    #     Simulated at the only point that is genuinely "while waiting
    #     for the lock": inside the (monkeypatched) lock acquisition
    #     itself, which the facade calls strictly AFTER the pre-lock
    #     snapshot and strictly BEFORE run_mutation().
    # ------------------------------------------------------------

    # 10a) The CANONICAL side changes only - invisible to any
    #      pending-only staleness check, caught by the composite one.
    case_id10, case_dir10, pending_path10 = make_case()
    expected_hash10 = sha256_text(pending_path10.read_text(encoding="utf-8"))
    principal10, repo10 = make_principal_and_repo(case_id10)
    conn10 = FakeJournalConn()
    pre_calls_10 = len(fake_mod.run_approve_calls)

    def _acquire_then_change_canonical(conn, case_id):
        _lock_calls.append(("acquire", case_id))
        (_paths.CASES_DIR / case_id / "canonical.json").write_text(
            '{"written":"by a concurrent writer while this request waited for the lock"}',
            encoding="utf-8",
        )
        return 111

    ml.acquire_case_lock_session = _acquire_then_change_canonical
    try:
        expect_raises(
            facade.PreconditionRaceDetectedError,
            lambda: facade.approve_case_scoped_mutation(
                "test_family", case_id10, expected_hash10, principal=principal10,
                authz_repository=repo10, conn_factory=lambda: conn10,
            ),
            "a CANONICAL-side change while waiting for the lock raises PreconditionRaceDetectedError",
        )
    finally:
        ml.acquire_case_lock_session = _fake_acquire_case_lock_session

    check("precondition race (canonical side): ZERO prepared journal rows", conn10.table == [])
    check(
        "precondition race (canonical side): run_approve was NEVER invoked",
        len(fake_mod.run_approve_calls) == pre_calls_10,
    )
    check(
        "precondition race (canonical side): the pending file itself was untouched, so a pending-only "
        "check would have let this through",
        sha256_text(pending_path10.read_text(encoding="utf-8")) == expected_hash10,
    )
    check(
        "precondition race: PreconditionRaceDetectedError IS a StaleViewError subclass, so every "
        "existing `except StaleViewError` handler keeps working unchanged",
        issubclass(facade.PreconditionRaceDetectedError, StaleViewError),
    )

    # 10b) The PENDING side changes while waiting for the lock. The
    #      composite digest differs first, so the RACE error (not the
    #      plain staleness error) is what a caller sees - a genuinely
    #      more accurate description of what happened.
    case_id10b, case_dir10b, pending_path10b = make_case()
    expected_hash10b = sha256_text(pending_path10b.read_text(encoding="utf-8"))
    principal10b, repo10b = make_principal_and_repo(case_id10b)
    conn10b = FakeJournalConn()
    pre_calls_10b = len(fake_mod.run_approve_calls)

    def _acquire_then_change_pending(conn, case_id):
        _lock_calls.append(("acquire", case_id))
        (_paths.CASES_DIR / case_id / "pending.json").write_text('{"x": 999}', encoding="utf-8")
        return 111

    ml.acquire_case_lock_session = _acquire_then_change_pending
    try:
        expect_raises(
            facade.PreconditionRaceDetectedError,
            lambda: facade.approve_case_scoped_mutation(
                "test_family", case_id10b, expected_hash10b, principal=principal10b,
                authz_repository=repo10b, conn_factory=lambda: conn10b,
            ),
            "a PENDING-side change while waiting for the lock also raises PreconditionRaceDetectedError",
        )
    finally:
        ml.acquire_case_lock_session = _fake_acquire_case_lock_session

    check("precondition race (pending side): ZERO prepared journal rows", conn10b.table == [])
    check(
        "precondition race (pending side): run_approve was NEVER invoked",
        len(fake_mod.run_approve_calls) == pre_calls_10b,
    )

    # 10c) NOTHING changes while waiting for the lock, but the caller's
    #      OWN claimed expected_hash was already wrong - the plain
    #      StaleViewError, NOT the race subclass. This is what keeps
    #      the two conditions genuinely distinguishable.
    case_id10c, case_dir10c, pending_path10c = make_case()
    principal10c, repo10c = make_principal_and_repo(case_id10c)
    conn10c = FakeJournalConn()
    try:
        facade.approve_case_scoped_mutation(
            "test_family", case_id10c, "a-hash-the-caller-simply-made-up",
            principal=principal10c, authz_repository=repo10c, conn_factory=lambda: conn10c,
        )
        check("stale claim (no race): raised StaleViewError", False, "no exception raised")
    except facade.PreconditionRaceDetectedError:
        check(
            "stale claim (no race): raises the PLAIN StaleViewError, never the race subclass",
            False, "got PreconditionRaceDetectedError instead of the plain StaleViewError",
        )
    except StaleViewError:
        check("stale claim (no race): raises the PLAIN StaleViewError, never the race subclass", True)
    check("stale claim (no race): ZERO prepared journal rows", conn10c.table == [])

    # ------------------------------------------------------------
    # 11) IDEMPOTENCY IDENTITY STABILITY - the same actor/resource/
    #     action/target/pre_revision retry must produce the SAME
    #     idempotency key EVEN IF the filesystem has moved on, and must
    #     safely replay the completed outcome. This is exactly what
    #     excluding `pre_hash` from mutation identity buys (see
    #     src/mutation_guard.py's own ROW 19C-2a correction).
    # ------------------------------------------------------------

    case_id11, case_dir11, pending_path11 = make_case()
    expected_hash11 = sha256_text(pending_path11.read_text(encoding="utf-8"))
    principal11, repo11 = make_principal_and_repo(case_id11)
    conn11 = FakeJournalConn()

    result11 = facade.approve_case_scoped_mutation(
        "test_family", case_id11, expected_hash11,
        principal=principal11, authz_repository=repo11, conn_factory=lambda: conn11,
    )
    first_key_11 = conn11.table[0]["idempotency_key"]
    first_pre_hash_11 = conn11.table[0]["pre_hash"]
    check("idempotency stability: the first attempt completed freshly", result11.replayed is False)

    # The retry now runs against a genuinely DIFFERENT filesystem state
    # (canonical.json exists now - it did not when the first attempt
    # computed its pre-lock snapshot), so the COMPOSITE pre_hash a
    # fresh attempt would compute is different...
    retry_snapshot_11 = facade._compute_precondition_snapshot(pending_path11, result11.canonical_path)
    check(
        "idempotency stability: the filesystem really did change between the two attempts",
        retry_snapshot_11.composite_digest != first_pre_hash_11,
    )

    # ...yet the retry must still recompute the SAME idempotency key
    # and replay the stored completed outcome, without re-invoking the
    # writer.
    calls_before_retry_11 = len(fake_mod.run_approve_calls)
    result11_retry = facade.approve_case_scoped_mutation(
        "test_family", case_id11, expected_hash11,
        principal=principal11, authz_repository=repo11, conn_factory=lambda: conn11,
    )
    check("idempotency stability: the retry REPLAYED (writer not re-invoked)", result11_retry.replayed is True)
    check(
        "idempotency stability: the writer really was not called again",
        len(fake_mod.run_approve_calls) == calls_before_retry_11,
    )
    check("idempotency stability: the SAME journal row was reused", result11_retry.journal_id == result11.journal_id)
    check("idempotency stability: no SECOND journal row was created", len(conn11.table) == 1)
    check(
        "idempotency stability: the journal row's idempotency_key is unchanged despite the changed filesystem",
        conn11.table[0]["idempotency_key"] == first_key_11,
    )

    # ------------------------------------------------------------
    # 12) THE FOUR EXACT BINDINGS - each one proven to be genuinely
    #     load-bearing on a safe replay, one at a time, against the
    #     REAL audit record the fake family module wrote.
    # ------------------------------------------------------------

    real_audit_path_12 = result11.audit_path
    good_record_12 = json.loads(real_audit_path_12.read_text(encoding="utf-8"))

    def replay_11():
        return facade.approve_case_scoped_mutation(
            "test_family", case_id11, expected_hash11,
            principal=principal11, authz_repository=repo11, conn_factory=lambda: conn11,
        )

    def with_record(mutated):
        real_audit_path_12.write_text(json.dumps(mutated), encoding="utf-8")

    # Sanity: the untouched record replays cleanly (so every failure
    # below is caused by the ONE field it mutates, nothing else).
    with_record(good_record_12)
    try:
        check("five bindings: the UNTOUCHED audit record replays cleanly", replay_11().replayed is True)
    except Exception as error:
        check("five bindings: the UNTOUCHED audit record replays cleanly", False, f"unexpected: {error!r}")

    binding_cases_12 = [
        ("binding 1 (idempotency key) WRONG", {"mutation_idempotency_key": "not-the-right-key"}),
        ("binding 1 (idempotency key) MISSING", {"mutation_idempotency_key": None}),
        ("binding 1 (idempotency key) BLANK", {"mutation_idempotency_key": "   "}),
        ("binding 2 (resource key) WRONG - a different case", {"mutation_resource_key": "case:some_other_case"}),
        ("binding 2 (resource key) MISSING", {"mutation_resource_key": None}),
        ("binding 2 (resource key) BLANK", {"mutation_resource_key": ""}),
        ("binding 2 (resource key) MALFORMED - no 'case:' prefix", {"mutation_resource_key": "global:rag_index"}),
        ("binding 4 (audit canonical hash) WRONG", {"canonical_sha256": "0" * 64}),
        ("binding 4 (audit canonical hash) MISSING", {"canonical_sha256": None}),
        ("binding 4 (audit canonical hash) BLANK", {"canonical_sha256": "\t"}),
        # ROW 19C-2a FINAL AUDIT REMEDIATION - binding 5.
        ("binding 5 (audit pending hash) WRONG", {"pending_sha256": "f" * 64}),
        ("binding 5 (audit pending hash) MISSING", {"pending_sha256": None}),
        ("binding 5 (audit pending hash) BLANK", {"pending_sha256": "  \t "}),
        ("binding 5 (audit pending hash) is a DIFFERENT real document's hash",
         {"pending_sha256": sha256_text('{"a totally different pending document": true}')}),
    ]
    for label, mutation in binding_cases_12:
        with_record({**good_record_12, **mutation})
        expect_raises(
            facade.AuditBindingVerificationFailedError,
            replay_11,
            f"five bindings: a replay is REJECTED when {label}",
        )

    # Binding 2's MALFORMED case is worth asserting at the helper level
    # too: the resource_key SHAPE check must fire even when the audit
    # record agrees with it perfectly (so it cannot be mistaken for the
    # equality check).
    with_record({**good_record_12, "mutation_resource_key": "not-a-case-key"})
    expect_raises(
        facade.AuditBindingVerificationFailedError,
        lambda: facade._verify_completed_replay_audit_binding(
            result11.canonical_path,
            journal_state=facade.COMPLETED_JOURNAL_STATE,
            journal_id=result11.journal_id,
            idempotency_key=good_record_12["mutation_idempotency_key"],
            resource_key="not-a-case-key",
            observed_post_hash=sha256_text(result11.canonical_path.read_text(encoding="utf-8")),
            pre_revision=expected_hash11,
        ),
        "binding 2b: a resource_key that is not a well-formed 'case:<case_id>' key is rejected even "
        "when the audit record agrees with it exactly",
    )
    with_record(good_record_12)

    # ------------------------------------------------------------
    # 12b) BINDING 3b - `journal.observed_post_hash == current
    #      canonical SHA-256`. Called at the helper level because the
    #      only way for a real journal row to carry a diverging
    #      observed_post_hash is out-of-band tampering, and the point
    #      is that the helper refuses it rather than passing it
    #      through to the success page.
    # ------------------------------------------------------------

    real_current_hash_12b = sha256_text(result11.canonical_path.read_text(encoding="utf-8"))

    def call_helper(**overrides):
        kwargs = dict(
            journal_state=facade.COMPLETED_JOURNAL_STATE,
            journal_id=result11.journal_id,
            idempotency_key=good_record_12["mutation_idempotency_key"],
            resource_key=f"case:{case_id11}",
            observed_post_hash=real_current_hash_12b,
            pre_revision=expected_hash11,
        )
        kwargs.update(overrides)
        return facade._verify_completed_replay_audit_binding(result11.canonical_path, **kwargs)

    check(
        "binding 3b: with every binding correct, the helper returns the FRESHLY COMPUTED current "
        "canonical hash",
        call_helper() == real_current_hash_12b,
    )
    for label, override in [
        ("WRONG (a stale journal hash)", {"observed_post_hash": "1" * 64}),
        ("MISSING (NULL observed_post_hash on a 'completed' row)", {"observed_post_hash": None}),
        ("BLANK", {"observed_post_hash": "   "}),
    ]:
        expect_raises(
            facade.AuditBindingVerificationFailedError,
            lambda override=override: call_helper(**override),
            f"binding 3b: journal.observed_post_hash {label} is REJECTED",
        )
    for label, override in [
        ("MISSING", {"pre_revision": None}),
        ("BLANK", {"pre_revision": " "}),
    ]:
        expect_raises(
            facade.AuditBindingVerificationFailedError,
            lambda override=override: call_helper(**override),
            f"binding 5: a request whose OWN pre_revision is {label} is REJECTED (nothing to "
            "corroborate the audit record's pending_sha256 against)",
        )

    # ------------------------------------------------------------
    # 12c) The helper is CLOSED to non-completed states - the
    #      "this can only be a completed replay" precondition is now
    #      enforced inside the helper, not merely by its call site's
    #      `if outcome.replayed:` guard.
    # ------------------------------------------------------------

    for bad_state in ("prepared", "executing", "reconciliation_required", "failed", "", None):
        expect_raises(
            facade.AuditBindingVerificationFailedError,
            lambda bad_state=bad_state: call_helper(journal_state=bad_state),
            f"closed API: the helper REFUSES journal_state={bad_state!r} - only "
            f"{facade.COMPLETED_JOURNAL_STATE!r} is accepted",
        )
    check(
        "closed API: the binding helper is PRIVATE (the old public `verify_audit_binding` name is gone)",
        not hasattr(facade, "verify_audit_binding")
        and hasattr(facade, "_verify_completed_replay_audit_binding"),
    )

    # Binding 3: the canonical artefact itself is gone right now, so a
    # 'completed' journal outcome cannot be corroborated at all.
    with_record(good_record_12)
    canonical_backup_12 = result11.canonical_path.read_text(encoding="utf-8")
    result11.canonical_path.unlink()
    expect_raises(
        facade.AuditBindingVerificationFailedError,
        replay_11,
        "five bindings: a replay is REJECTED when binding 3 (the canonical artefact) no longer exists",
    )
    result11.canonical_path.write_text(canonical_backup_12, encoding="utf-8")

    # Binding 4, the substantive case: the audit record is entirely
    # self-consistent and correctly bound, but the canonical artefact
    # ON DISK has since been overwritten by something else. Bindings
    # 1+2 still match; only 3-vs-4 catches this.
    with_record(good_record_12)
    result11.canonical_path.write_text('{"overwritten":"out of band"}', encoding="utf-8")
    expect_raises(
        facade.AuditBindingVerificationFailedError,
        replay_11,
        "five bindings: a replay is REJECTED when the canonical artefact was overwritten after the "
        "audit record was written (bindings 1+2 still match; only 3-vs-4 catches it)",
    )
    result11.canonical_path.write_text(canonical_backup_12, encoding="utf-8")

    check(
        "five bindings: NONE of the rejected replays ever re-invoked the writer",
        len(fake_mod.run_approve_calls) == calls_before_retry_11,
    )
    check(
        "five bindings: NONE of the rejected replays added a journal row",
        len(conn11.table) == 1 and conn11.table[0]["state"] == "completed",
    )

    # A corrupt (unparseable) audit record and a valid-JSON-but-not-an-
    # object one are both rejected, never accepted as corroboration.
    real_audit_path_12.write_text("{not valid json at all", encoding="utf-8")
    expect_raises(
        facade.AuditBindingVerificationFailedError,
        replay_11,
        "five bindings: an UNPARSEABLE audit record is rejected",
    )
    real_audit_path_12.write_text('["a", "list", "not", "an", "object"]', encoding="utf-8")
    expect_raises(
        facade.AuditBindingVerificationFailedError,
        replay_11,
        "five bindings: a valid-JSON-but-not-an-object audit record is rejected inside this module's own "
        "closed error contract (never as a bare AttributeError)",
    )
    with_record(good_record_12)

    check(
        "replay: the returned canonical_hash is the FRESHLY VERIFIED current canonical hash, not an "
        "unverified value carried over from the journal row",
        replay_11().canonical_hash == sha256_text(result11.canonical_path.read_text(encoding="utf-8")),
    )

    # ------------------------------------------------------------
    # 13) PRODUCTION-DEFAULT AUTHZ REPOSITORY LIFECYCLE.
    #
    # Every OTHER test in this file (and in test_service_isolated.py /
    # the real-Postgres integration file) injects `authz_repository=`,
    # and `test_routes.py` monkeypatches `_default_authz_repository`
    # with a lambda - so the REAL production-default path, which is
    # what `ui/main.py` actually uses, was previously executed by NO
    # test at all. That is exactly the code whose contract changed in
    # this row (a bare repository became a `(repository, close)` pair),
    # so it is exercised here for real, with only `ui.services.db.
    # get_connection` stubbed - `_default_authz_repository()` and
    # `_resolve_authz_repository()` themselves run unmodified, and so
    # does the REAL `authz.PostgresAuthzRepository` against the stub.
    # ------------------------------------------------------------

    from ui.services import db as _db

    _original_get_connection = _db.get_connection

    class StubIamCursor:
        """Serves exactly the two SELECTs the REAL
        `authz.PostgresAuthzRepository` issues - so that real
        repository class is genuinely exercised here, not bypassed."""

        def __init__(self, conn, case_id, assigned):
            self._conn = conn
            self._case_id = case_id
            self._assigned = assigned
            self._result = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            self._conn.queries.append(normalized)
            if normalized.startswith("SELECT s.user_id, u.authz_version, u.disabled"):
                self._result = (1, 1, False)
            elif normalized.startswith("SELECT role FROM iam.case_assignments"):
                _user_id, requested_case_id = params
                self._result = ("lawyer",) if (self._assigned and requested_case_id == self._case_id) else None
            else:
                raise AssertionError(f"unexpected IAM SQL: {normalized}")

        def fetchone(self):
            return self._result

    class StubIamConn:
        def __init__(self, case_id, assigned=True, fail_on_close=False):
            self.case_id = case_id
            self.assigned = assigned
            self.fail_on_close = fail_on_close
            self.queries = []
            self.close_calls = 0
            self.autocommit = None

        def cursor(self):
            return StubIamCursor(self, self.case_id, self.assigned)

        def close(self):
            self.close_calls += 1
            if self.fail_on_close:
                raise RuntimeError("injected: IAM connection close() failed")

    # 13a) The (repository, close) contract itself.
    stub_a = StubIamConn("irrelevant")
    opened_a = []
    try:
        _db.get_connection = lambda: (opened_a.append(stub_a) or stub_a)
        pair = facade._resolve_authz_repository(None)
    finally:
        _db.get_connection = _original_get_connection

    check(
        "default authz: _resolve_authz_repository(None) returns a 2-tuple",
        isinstance(pair, tuple) and len(pair) == 2,
        f"got {pair!r}",
    )
    check(
        "default authz: element 0 is a REAL authz.PostgresAuthzRepository built on the opened connection",
        isinstance(pair[0], _authz.PostgresAuthzRepository),
    )
    check("default authz: element 1 is callable (the closer)", callable(pair[1]))
    check("default authz: exactly ONE IAM connection was opened", len(opened_a) == 1)
    check("default authz: the closer has NOT been called yet", stub_a.close_calls == 0)
    pair[1]()
    check("default authz: invoking the closer really closes THAT connection", stub_a.close_calls == 1)

    # 13b) An INJECTED repository must open nothing and close nothing.
    opened_b = []
    try:
        _db.get_connection = lambda: (opened_b.append(1) or StubIamConn("x"))
        injected_repo = _authz.InMemoryAuthzRepository()
        repo_b, close_b = facade._resolve_authz_repository(injected_repo)
    finally:
        _db.get_connection = _original_get_connection

    check("default authz: an INJECTED repository is returned unchanged", repo_b is injected_repo)
    check("default authz: an INJECTED repository opens ZERO IAM connections", opened_b == [])
    check(
        "default authz: the closer for an INJECTED repository is a harmless no-op (its lifetime "
        "belongs to whoever created it)",
        close_b() is None,
    )

    # 13c) FULL production-default flow: authz_repository=None all the
    #      way through a real, successful approval. The IAM connection
    #      must be opened once and closed EXACTLY once.
    case_id13, case_dir13, pending_path13 = make_case()
    expected_hash13 = sha256_text(pending_path13.read_text(encoding="utf-8"))
    principal13 = _authz.Principal(user_id=1, session_id=100, role_version_at_issue=1)
    stub_c = StubIamConn(case_id13, assigned=True)
    opened_c = []
    conn13 = FakeJournalConn()
    try:
        _db.get_connection = lambda: (opened_c.append(stub_c) or stub_c)
        result13 = facade.approve_case_scoped_mutation(
            "test_family", case_id13, expected_hash13,
            principal=principal13, authz_repository=None, conn_factory=lambda: conn13,
        )
    finally:
        _db.get_connection = _original_get_connection

    check(
        "default authz (full flow): the approval succeeded through the REAL production-default path",
        result13.replayed is False and result13.canonical_path.exists(),
    )
    check("default authz (full flow): exactly ONE IAM connection was opened", len(opened_c) == 1)
    check(
        "default authz (full flow): that IAM connection was closed EXACTLY once",
        stub_c.close_calls == 1, f"close_calls={stub_c.close_calls}",
    )
    check(
        "default authz (full flow): the REAL PostgresAuthzRepository really ran BOTH authz checks "
        "(outer + inner) against it - 2 session lookups and 2 assignment lookups",
        sum(1 for q in stub_c.queries if q.startswith("SELECT s.user_id")) == 2
        and sum(1 for q in stub_c.queries if q.startswith("SELECT role FROM iam.case_assignments")) == 2,
        f"queries={stub_c.queries}",
    )

    # 13d) EXCEPTION path (outer authz denial): the owned IAM
    #      connection must STILL be closed exactly once.
    case_id13d, _, _ = make_case()
    stub_d = StubIamConn(case_id13d, assigned=False)
    conn13d = FakeJournalConn()
    try:
        _db.get_connection = lambda: stub_d
        expect_raises(
            _authz.CaseAccessDeniedError,
            lambda: facade.approve_case_scoped_mutation(
                "test_family", case_id13d, "irrelevant",
                principal=principal13, authz_repository=None, conn_factory=lambda: conn13d,
            ),
            "default authz (denial): the production-default path still denies an unassigned case",
        )
    finally:
        _db.get_connection = _original_get_connection

    check(
        "default authz (denial): the owned IAM connection was STILL closed exactly once on the "
        "exception path",
        stub_d.close_calls == 1, f"close_calls={stub_d.close_calls}",
    )
    check(
        "default authz (denial): the denial still opened ZERO journal connections and ran ZERO journal SQL",
        conn13d.calls == [] and conn13d.table == [],
    )

    # 13e) A closer that itself RAISES must not replace the outcome.
    case_id13e, _, pending_path13e = make_case()
    expected_hash13e = sha256_text(pending_path13e.read_text(encoding="utf-8"))
    stub_e = StubIamConn(case_id13e, assigned=True, fail_on_close=True)
    conn13e = FakeJournalConn()
    try:
        _db.get_connection = lambda: stub_e
        result13e = facade.approve_case_scoped_mutation(
            "test_family", case_id13e, expected_hash13e,
            principal=principal13, authz_repository=None, conn_factory=lambda: conn13e,
        )
        check(
            "default authz: an IAM closer that RAISES is logged and swallowed - the successful "
            "approval outcome is returned unchanged",
            result13e.replayed is False and result13e.canonical_path.exists(),
        )
    except Exception as error:
        check(
            "default authz: an IAM closer that RAISES is logged and swallowed - the successful "
            "approval outcome is returned unchanged",
            False, f"the closer's exception escaped: {error!r}",
        )
    finally:
        _db.get_connection = _original_get_connection
    check("default authz: the failing closer really was invoked", stub_e.close_calls == 1)

    # ------------------------------------------------------------
    # 14) UNLOCK / CLOSE EXCEPTION SAFETY.
    #
    # `release_lock_session()` executes real SQL and can therefore
    # RAISE, not merely return False. A raise from the cleanup block
    # must never (a) replace a successful, already-durable outcome, nor
    # (b) mask an exception already in flight, nor (c) skip
    # `conn.close()`.
    # ------------------------------------------------------------

    class ClosableFakeJournalConn(FakeJournalConn):
        def __init__(self, table=None, fail_on_close=False):
            super().__init__(table)
            self.fail_on_close = fail_on_close
            self.close_calls = 0

        def close(self):
            self.close_calls += 1
            self.closed = True
            if self.fail_on_close:
                raise RuntimeError("injected: journal connection close() failed")

    def raising_release(conn, advisory_lock_id):
        _lock_calls.append(("release-raises", advisory_lock_id))
        raise RuntimeError("injected: pg_advisory_unlock failed (connection died after the commit)")

    # 14a) SUCCESSFUL outcome + release RAISES -> the outcome survives.
    case_id14a, _, pending_path14a = make_case()
    expected_hash14a = sha256_text(pending_path14a.read_text(encoding="utf-8"))
    principal14a, repo14a = make_principal_and_repo(case_id14a)
    conn14a = ClosableFakeJournalConn()
    calls_before_14a = len(fake_mod.run_approve_calls)
    try:
        ml.release_lock_session = raising_release
        result14a = facade.approve_case_scoped_mutation(
            "test_family", case_id14a, expected_hash14a,
            principal=principal14a, authz_repository=repo14a, conn_factory=lambda: conn14a,
        )
        check(
            "unlock safety (success + release raises): the durable, successful outcome is returned "
            "UNCHANGED - a cleanup failure never becomes a reported approval failure",
            result14a.replayed is False
            and result14a.canonical_hash == sha256_text(result14a.canonical_path.read_text(encoding="utf-8")),
        )
    except Exception as error:
        check(
            "unlock safety (success + release raises): the durable, successful outcome is returned "
            "UNCHANGED - a cleanup failure never becomes a reported approval failure",
            False, f"the release exception escaped: {error!r}",
        )
    finally:
        ml.release_lock_session = _fake_release_lock_session

    check(
        "unlock safety (success + release raises): the writer still ran exactly once and the journal "
        "row is 'completed'",
        len(fake_mod.run_approve_calls) == calls_before_14a + 1
        and len(conn14a.table) == 1 and conn14a.table[0]["state"] == "completed",
    )
    check(
        "unlock safety (success + release raises): conn.close() was STILL called (its own nested finally)",
        conn14a.close_calls == 1, f"close_calls={conn14a.close_calls}",
    )

    # 14b) PRIMARY exception (writer) + release RAISES -> the ORIGINAL
    #      writer exception is what propagates, never the release one.
    case_id14b, _, pending_path14b = make_case()
    expected_hash14b = sha256_text(pending_path14b.read_text(encoding="utf-8"))
    principal14b, repo14b = make_principal_and_repo(case_id14b)
    conn14b = ClosableFakeJournalConn()
    primary_boom = ValueError("the ORIGINAL writer exception - this exact instance must propagate")
    fake_mod14b = make_fake_module("_fake_approval_mod_facade_test_14b", raise_on_approve=primary_boom)
    sys.modules["_fake_approval_mod_facade_test_14b"] = fake_mod14b
    facade.ROW_KEY_TO_MODULE_NAME["test_family_14b"] = "_fake_approval_mod_facade_test_14b"
    caught_14b = None
    try:
        ml.release_lock_session = raising_release
        facade.approve_case_scoped_mutation(
            "test_family_14b", case_id14b, expected_hash14b,
            principal=principal14b, authz_repository=repo14b, conn_factory=lambda: conn14b,
        )
    except BaseException as error:
        caught_14b = error
    finally:
        ml.release_lock_session = _fake_release_lock_session

    check(
        "unlock safety (writer exception + release raises): the EXACT ORIGINAL writer exception "
        "instance propagates - the release failure never masks it",
        caught_14b is primary_boom, f"caught={caught_14b!r}",
    )
    check(
        "unlock safety (writer exception + release raises): the journal row is still "
        "'reconciliation_required'",
        len(conn14b.table) == 1 and conn14b.table[0]["state"] == "reconciliation_required",
    )
    check(
        "unlock safety (writer exception + release raises): conn.close() was STILL called",
        conn14b.close_calls == 1, f"close_calls={conn14b.close_calls}",
    )

    # 14c) conn.close() itself RAISES, on a SUCCESSFUL outcome.
    case_id14c, _, pending_path14c = make_case()
    expected_hash14c = sha256_text(pending_path14c.read_text(encoding="utf-8"))
    principal14c, repo14c = make_principal_and_repo(case_id14c)
    conn14c = ClosableFakeJournalConn(fail_on_close=True)
    try:
        result14c = facade.approve_case_scoped_mutation(
            "test_family", case_id14c, expected_hash14c,
            principal=principal14c, authz_repository=repo14c, conn_factory=lambda: conn14c,
        )
        check(
            "unlock safety (close raises, success): the successful outcome is returned unchanged",
            result14c.replayed is False and result14c.canonical_path.exists(),
        )
    except Exception as error:
        check(
            "unlock safety (close raises, success): the successful outcome is returned unchanged",
            False, f"the close exception escaped: {error!r}",
        )
    check("unlock safety (close raises, success): close really was attempted", conn14c.close_calls == 1)

    # 14d) conn.close() RAISES while a PRIMARY exception is in flight.
    case_id14d, _, pending_path14d = make_case()
    expected_hash14d = sha256_text(pending_path14d.read_text(encoding="utf-8"))
    principal14d, repo14d = make_principal_and_repo(case_id14d)
    conn14d = ClosableFakeJournalConn(fail_on_close=True)
    caught_14d = None
    try:
        facade.approve_case_scoped_mutation(
            "test_family_14b", case_id14d, expected_hash14d,
            principal=principal14d, authz_repository=repo14d, conn_factory=lambda: conn14d,
        )
    except BaseException as error:
        caught_14d = error

    check(
        "unlock safety (close raises + primary exception): the EXACT ORIGINAL writer exception is "
        "PRESERVED - the close failure never replaces it",
        caught_14d is primary_boom, f"caught={caught_14d!r}",
    )
    check("unlock safety (close raises + primary exception): close really was attempted", conn14d.close_calls == 1)

    # 14e) BOTH release and close raise, on a successful outcome - the
    #      outcome must still survive both.
    case_id14e, _, pending_path14e = make_case()
    expected_hash14e = sha256_text(pending_path14e.read_text(encoding="utf-8"))
    principal14e, repo14e = make_principal_and_repo(case_id14e)
    conn14e = ClosableFakeJournalConn(fail_on_close=True)
    try:
        ml.release_lock_session = raising_release
        result14e = facade.approve_case_scoped_mutation(
            "test_family", case_id14e, expected_hash14e,
            principal=principal14e, authz_repository=repo14e, conn_factory=lambda: conn14e,
        )
        check(
            "unlock safety (BOTH release and close raise): the successful outcome STILL survives",
            result14e.replayed is False and result14e.canonical_path.exists(),
        )
    except Exception as error:
        check(
            "unlock safety (BOTH release and close raise): the successful outcome STILL survives",
            False, f"a cleanup exception escaped: {error!r}",
        )
    finally:
        ml.release_lock_session = _fake_release_lock_session
    check("unlock safety (BOTH raise): close was still attempted", conn14e.close_calls == 1)

    # 14f) The pre-existing `released is False` behavior is UNCHANGED:
    #      visible (critically logged) but never raising.
    case_id14f, _, pending_path14f = make_case()
    expected_hash14f = sha256_text(pending_path14f.read_text(encoding="utf-8"))
    principal14f, repo14f = make_principal_and_repo(case_id14f)
    conn14f = ClosableFakeJournalConn()
    try:
        ml.release_lock_session = lambda conn, advisory_lock_id: False
        result14f = facade.approve_case_scoped_mutation(
            "test_family", case_id14f, expected_hash14f,
            principal=principal14f, authz_repository=repo14f, conn_factory=lambda: conn14f,
        )
        check(
            "unlock safety (released is False): UNCHANGED contract - visible via a CRITICAL log, "
            "never raised, outcome returned normally",
            result14f.replayed is False and result14f.canonical_path.exists(),
        )
    except Exception as error:
        check(
            "unlock safety (released is False): UNCHANGED contract - visible via a CRITICAL log, "
            "never raised, outcome returned normally",
            False, f"a False release raised: {error!r}",
        )
    finally:
        ml.release_lock_session = _fake_release_lock_session
    check("unlock safety (released is False): conn.close() was still called", conn14f.close_calls == 1)

finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.release_lock_session = _original_release
    facade.ROW_KEY_TO_MODULE_NAME = _original_row_key_mapping
    for name in (
        "_fake_approval_mod_facade_test_1",
        "_fake_approval_mod_facade_test_8",
        "_fake_approval_mod_facade_test_14b",
    ):
        sys.modules.pop(name, None)
    for case_dir in _created_case_dirs:
        shutil.rmtree(case_dir, ignore_errors=True)


print(f"--- test_mutation_approval_facade_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
