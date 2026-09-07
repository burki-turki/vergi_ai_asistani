# ============================================================
# Row 19C-2b - isolated (fake-journal-connection) tests for
# ui/services/review_mutation_facade.py.
#
# This file exercises `apply_review_mutation()` end to end against:
#   - a REAL `mutation.mutation_journal` FAKE table/cursor (the exact
#     same shape `ui/tests/test_mutation_approval_facade_isolated.py`
#     already proves correct against the real `run_mutation()` - a
#     fresh, self-contained copy here, matching this project's own
#     convention of each test file owning its own fakes);
#   - REAL `ui.services.authz.authorize_case_access()`, `ui.services.
#     paths.resolve_case_id()`, and a REAL, temporary
#     `data/cases/<case_id>/` filesystem fixture (never bypassed or
#     mocked - a fabricated case_id that does not exist as a real
#     directory would genuinely fail authorization, exactly as it
#     would in production);
#   - the REAL `evidence_review`/`argument_review` backend modules
#     (never a fake stand-in) via `canonical_path_override`/
#     `audit_dir_override` pointing at an isolated tempdir - this
#     exercises the REAL guard-hoisting dispatch (`find_candidate`,
#     `check_parent_dependency`), the REAL `write_review_audit()`
#     additive fields, and the REAL manifest-scan logic against real
#     files on disk, not a fake stand-in's approximation of them;
#   - `ui.services.mutation_lock.acquire_case_lock_session`/
#     `release_lock_session` MONKEYPATCHED to fakes (same pattern
#     `ui/tests/test_mutation_approval_facade_isolated.py` uses).
#
# Run: python -m ui.tests.test_review_mutation_facade_isolated
# ============================================================

import hashlib
import json
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import authz as _authz                                # noqa: E402
from ui.services import mutation_coordinator as mutcoord                # noqa: E402
from ui.services import mutation_lock as ml                             # noqa: E402
from ui.services import paths as _paths                                 # noqa: E402
from ui.services import review_mutation_facade as facade                # noqa: E402
from ui.services.common import (                                        # noqa: E402
    ReviewPreconditionRaceDetectedError,
    ReviewRecordNotFoundError,
    ReviewStaleViewError,
)

import evidence_review                                                  # noqa: E402
import argument_review                                                  # noqa: E402
import qa_review                                                        # noqa: E402
import qa_engine                                                        # noqa: E402

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
# Fake mutation.mutation_journal table + cursor.
# ----------------------------------------------------------------

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
                raise AssertionError(f"duplicate idempotency_key insert: {idempotency_key!r}")
            new_id = len(self._table) + 1
            self._table.append({
                "id": new_id, "resource_key": resource_key, "action_family": action_family,
                "actor_user_id": actor_user_id, "actor_label": actor_label, "target_ref": target_ref,
                "target_state": target_state, "pre_hash": pre_hash, "pre_revision": pre_revision,
                "idempotency_key": idempotency_key, "request_fingerprint": request_fingerprint,
                "state": "prepared", "failure_code": None, "resolution_code": None,
                "executing_at": None, "resolved_at": None, "observed_post_hash": None,
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
        self.closed = True


_lock_calls = []
_original_acquire_case = ml.acquire_case_lock_session
_original_release = ml.release_lock_session


def _fake_acquire_case_lock_session(conn, case_id):
    _lock_calls.append(("acquire", case_id))
    return 111


def _fake_release_lock_session(conn, advisory_lock_id):
    _lock_calls.append(("release", advisory_lock_id))
    return True


_created_case_dirs = []


def make_case():
    case_id = f"reviewfacadetest{uuid.uuid4().hex[:10]}"
    case_dir = _paths.CASES_DIR / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    # `evidence_validator.load_case()`/`argument_validator`'s own
    # post-write validators (called for REAL by the real writer this
    # file deliberately never stubs out - see this file's own header
    # comment) independently check `case.json`'s own `case_id` field
    # against the case_id being validated - a bare `{}` fails that
    # check with "case_id mismatch: expected X, found None".
    (case_dir / "case.json").write_text(json.dumps({"case_id": case_id}), encoding="utf-8")
    _created_case_dirs.append(case_dir)
    return case_id, case_dir


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_real_case_0001_qa_tree():
    real_dir = _paths.CASES_DIR / "case_0001" / "qa"
    if not real_dir.exists():
        return {"dir_exists": False, "files": {}}
    return {
        "dir_exists": True,
        "files": {
            str(p.relative_to(real_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(real_dir.rglob("*")) if p.is_file()
        },
    }


_real_case_0001_qa_before = snapshot_real_case_0001_qa_tree()


def make_principal_and_repo(case_id, *, assigned=True, role="lawyer"):
    principal = _authz.Principal(user_id=1, session_id=100, role_version_at_issue=1)
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[100] = _authz.SessionRecord(user_id=1, current_authz_version=1, disabled=False)
    if assigned:
        repo.assignments[(1, case_id)] = _authz.CaseAssignmentRecord(role=role)
    return principal, repo


def evidence_binding():
    return facade.ReviewFamilyBinding(
        review_kind="evidence.candidate",
        module=evidence_review,
        record_type="candidate",
        call_shape="with_record_type",
        state_field="review_state",
        domain_error_class=evidence_review.EvidenceReviewError,
        get_audit_dir_fn=evidence_review.get_evidence_review_audit_dir,
        reviewer_ref="local_lawyer_ui",
    )


def argument_counterargument_binding():
    return facade.ReviewFamilyBinding(
        review_kind="argument.counterargument",
        module=argument_review,
        record_type="counterargument",
        call_shape="with_record_type",
        state_field="counter_review_state",
        domain_error_class=argument_review.ArgumentReviewError,
        get_audit_dir_fn=argument_review.get_argument_review_audit_dir,
        reviewer_ref="local_lawyer_ui",
    )


def make_evidence_fixture(tmp_root, *, state="needs_review"):
    canonical_path = tmp_root / "evidence.json"
    canonical_path.write_text(
        json.dumps({"evidence_candidates": [{"candidate_id": "ec_1", "review_state": state}]}),
        encoding="utf-8",
    )
    audit_dir = tmp_root / "reviews" / "evidence_reviews"
    return canonical_path, audit_dir


def qa_binding():
    return facade.ReviewFamilyBinding(
        review_kind="qa.suggestion",
        module=qa_review,
        record_type="suggestion",
        call_shape="qa_special",
        state_field="suggestion_review_state",
        domain_error_class=qa_review.QaReviewError,
        get_audit_dir_fn=qa_review.get_qa_review_audit_dir,
        reviewer_ref="local_lawyer_ui",
    )


_QA_SUGGESTION_ID = "qa_agent_suggestion_facadetest_001"


def make_qa_fixture(tmp_root, real_case_id, *, state="needs_review"):
    """A REAL, schema-valid QA analysis against `real_case_id`'s own
    REAL upstream data (`qa_engine.build_qa_engine_output` is a pure
    deterministic engine - no LLM/agent needed, matching Row 16's own
    design) - written ONLY to `tmp_root` (never to the real case's own
    `qa/` directory) - mirrors `qa_review.py`'s own `run_self_test()`
    fixture-building pattern exactly, so this file exercises the writer
    end to end against a fixture the REAL post-write `validate_qa_
    analysis()` genuinely accepts, never a hand-rolled minimal stub
    that would only ever exercise rejection paths."""
    real_output = qa_engine.build_qa_engine_output(real_case_id)
    real_output["qa_agent_suggestions"] = [{
        "suggestion_id": _QA_SUGGESTION_ID, "suggestion_type": "needs_deeper_human_review",
        "related_check_result_id": real_output["qa_check_results"][0]["check_result_id"],
        "related_scope_id": real_output["qa_check_results"][0]["scope_id"],
        "related_issue_id": None, "grounded_explanation": "Row 19C-2b facade self-test amaçlı bir gözlem.",
        "suggestion_review_state": state,
        "suggestion_dedup_fingerprint": "dedup_facadetest_001",
        "suggestion_content_fingerprint": "content_facadetest_001",
    }]
    canonical_path = tmp_root / "qa.json"
    qa_review.atomic_write_json(canonical_path, real_output)
    audit_dir = tmp_root / "reviews" / "qa_reviews"
    return canonical_path, audit_dir


try:
    ml.acquire_case_lock_session = _fake_acquire_case_lock_session
    ml.release_lock_session = _fake_release_lock_session

    # ------------------------------------------------------------
    # 1) Fresh (non-replayed) mutation - the full happy path. Uses the
    #    REAL, existing `case_0001` (never created/destroyed by this
    #    file) so the writer's own REAL post-write `validate_qa_
    #    analysis()` genuinely succeeds against real upstream data -
    #    the canonical/audit paths are still fully isolated via
    #    `canonical_path_override`/`audit_dir_override` (an isolated
    #    tempdir, never case_0001's own real `qa/` directory).
    # ------------------------------------------------------------

    real_case_id = "case_0001"
    principal, repo = make_principal_and_repo(real_case_id)
    tmp1 = Path(tempfile.mkdtemp(prefix="review_facade_iso1_"))
    canonical1, audit_dir1 = make_qa_fixture(tmp1, real_case_id)
    expected_hash1 = sha256_text(canonical1.read_text(encoding="utf-8"))
    conn1 = FakeJournalConn()

    result1 = facade.apply_review_mutation(
        "qa.suggestion", real_case_id, _QA_SUGGESTION_ID, "accepted_for_follow_up", "self-test note", expected_hash1,
        qa_binding(),
        principal=principal, authz_repository=repo, conn_factory=lambda: conn1,
        canonical_path_override=canonical1, audit_dir_override=audit_dir1,
    )

    check("fresh mutation: replayed=False", result1.replayed is False)
    check(
        "fresh mutation: canonical record flipped to 'accepted_for_follow_up'",
        json.loads(canonical1.read_text(encoding="utf-8"))["qa_agent_suggestions"][0]["suggestion_review_state"] == "accepted_for_follow_up",
    )
    check("fresh mutation: audit_path exists", result1.audit_path is not None and Path(result1.audit_path).exists())
    check(
        "fresh mutation: canonical_hash matches the real canonical file's own sha256",
        result1.canonical_hash == sha256_text(canonical1.read_text(encoding="utf-8")),
    )
    check(
        "fresh mutation: exactly one journal row exists, ending in state='completed'",
        len(conn1.table) == 1 and conn1.table[0]["state"] == "completed",
    )
    check("fresh mutation: journal row's resource_key is 'case:<case_id>'", conn1.table[0]["resource_key"] == f"case:{real_case_id}")
    check("fresh mutation: journal row's action_family is 'review.qa.suggestion'", conn1.table[0]["action_family"] == "review.qa.suggestion")
    check("fresh mutation: journal row's target_ref is the bare record_id", conn1.table[0]["target_ref"] == _QA_SUGGESTION_ID)
    check("fresh mutation: journal row's target_state is 'accepted_for_follow_up'", conn1.table[0]["target_state"] == "accepted_for_follow_up")
    check("fresh mutation: journal row's actor_label is the principal's user_id as a string", conn1.table[0]["actor_label"] == "1")
    check(
        "fresh mutation: journal row's pre_revision is the REQUEST's own claimed expected_hash",
        conn1.table[0]["pre_revision"] == expected_hash1,
    )
    check(
        "fresh mutation: journal row's pre_hash is the COMPOSITE snapshot digest, NOT the bare canonical hash",
        conn1.table[0]["pre_hash"] != expected_hash1
        and isinstance(conn1.table[0]["pre_hash"], str) and len(conn1.table[0]["pre_hash"]) == 64,
    )
    check("fresh mutation: the lock was acquired for the RESOLVED case_id", ("acquire", real_case_id) in _lock_calls)
    check("fresh mutation: the lock was released afterwards", ("release", 111) in _lock_calls)

    audit_record1 = json.loads(Path(result1.audit_path).read_text(encoding="utf-8"))
    check(
        "fresh mutation: the REAL audit record's mutation_idempotency_key is a real, non-empty string",
        isinstance(audit_record1["mutation_idempotency_key"], str) and bool(audit_record1["mutation_idempotency_key"]),
    )
    check(
        "fresh mutation: the REAL audit record's mutation_resource_key is bound to 'case:<case_id>'",
        audit_record1["mutation_resource_key"] == f"case:{real_case_id}",
    )
    check(
        "fresh mutation: the REAL audit record's mutation_actor_ref is the principal's user_id",
        audit_record1["mutation_actor_ref"] == "1",
    )
    check(
        "fresh mutation: the REAL audit record's reviewer_ref is the fixed 'local_lawyer_ui' sentinel",
        audit_record1["reviewer_ref"] == "local_lawyer_ui",
    )
    check(
        "fresh mutation: the REAL audit record's record_id/record_type/case_id identity fields are correct",
        audit_record1["record_id"] == _QA_SUGGESTION_ID
        and audit_record1["record_type"] == "suggestion"
        and audit_record1["case_id"] == real_case_id,
    )

    # ------------------------------------------------------------
    # 2) SAFE REPLAY - same request, byte-identical - writer NOT
    #    re-invoked, 14-binding verification succeeds.
    # ------------------------------------------------------------

    _original_qa_apply_review_transition = qa_review.apply_review_transition
    _replay_calls = {"n": 0}

    def _counting_qa_apply(*args, **kwargs):
        _replay_calls["n"] += 1
        return _original_qa_apply_review_transition(*args, **kwargs)

    qa_review.apply_review_transition = _counting_qa_apply
    try:
        result1_replay = facade.apply_review_mutation(
            "qa.suggestion", real_case_id, _QA_SUGGESTION_ID, "accepted_for_follow_up", "self-test note", expected_hash1,
            qa_binding(),
            principal=principal, authz_repository=repo, conn_factory=lambda: conn1,
            canonical_path_override=canonical1, audit_dir_override=audit_dir1,
        )
    finally:
        qa_review.apply_review_transition = _original_qa_apply_review_transition

    check("safe replay: replayed=True", result1_replay.replayed is True)
    check("safe replay: the writer was NEVER re-invoked", _replay_calls["n"] == 0)
    check(
        "safe replay: canonical_hash is the FRESHLY VERIFIED current canonical hash",
        result1_replay.canonical_hash == sha256_text(canonical1.read_text(encoding="utf-8")),
    )
    check("safe replay: same journal_id as the original fresh mutation", result1_replay.journal_id == result1.journal_id)
    check("safe replay: still exactly ONE journal row (no new row created)", len(conn1.table) == 1)

    # ------------------------------------------------------------
    # 3) IDEMPOTENCY CONFLICT - same identity, DIFFERENT target_state.
    # ------------------------------------------------------------

    expect_raises(
        mutcoord.IdempotencyConflictError,
        lambda: facade.apply_review_mutation(
            "qa.suggestion", real_case_id, _QA_SUGGESTION_ID, "dismissed", "self-test note", expected_hash1,
            qa_binding(),
            principal=principal, authz_repository=repo, conn_factory=lambda: conn1,
            canonical_path_override=canonical1, audit_dir_override=audit_dir1,
        ),
        "same identity + DIFFERENT target_state -> IdempotencyConflictError",
    )

    # ------------------------------------------------------------
    # 4) IDEMPOTENCY CONFLICT - same identity, DIFFERENT note.
    # ------------------------------------------------------------

    expect_raises(
        mutcoord.IdempotencyConflictError,
        lambda: facade.apply_review_mutation(
            "qa.suggestion", real_case_id, _QA_SUGGESTION_ID, "accepted_for_follow_up", "a COMPLETELY different note", expected_hash1,
            qa_binding(),
            principal=principal, authz_repository=repo, conn_factory=lambda: conn1,
            canonical_path_override=canonical1, audit_dir_override=audit_dir1,
        ),
        "same identity + DIFFERENT note -> IdempotencyConflictError (note is fingerprint-only, not identity)",
    )

    shutil.rmtree(tmp1, ignore_errors=True)

    # ------------------------------------------------------------
    # 5) PLAIN STALE HASH - the record itself changed, screen is stale.
    # ------------------------------------------------------------

    case_id5, case_dir5 = make_case()
    principal5, repo5 = make_principal_and_repo(case_id5)
    tmp5 = case_dir5 / "iso5"
    tmp5.mkdir()
    canonical5, audit_dir5 = make_evidence_fixture(tmp5)
    stale_hash5 = sha256_text(canonical5.read_text(encoding="utf-8"))
    # Simulate "the screen was rendered, then the file changed" -
    # canonical is overwritten AFTER the claimed expected_hash was
    # captured, BEFORE the request is ever made.
    canonical5.write_text(
        json.dumps({"evidence_candidates": [{"candidate_id": "ec_1", "review_state": "needs_review", "changed": True}]}),
        encoding="utf-8",
    )
    conn5 = FakeJournalConn()
    _calls5 = {"n": 0}
    _original5 = evidence_review.apply_review_transition
    evidence_review.apply_review_transition = lambda *a, **k: _calls5.update(n=_calls5["n"] + 1) or _original5(*a, **k)
    try:
        expect_raises(
            ReviewStaleViewError,
            lambda: facade.apply_review_mutation(
                "evidence.candidate", case_id5, "ec_1", "confirmed", "note", stale_hash5,
                evidence_binding(),
                principal=principal5, authz_repository=repo5, conn_factory=lambda: conn5,
                canonical_path_override=canonical5, audit_dir_override=audit_dir5,
            ),
            "plain stale hash -> ReviewStaleViewError (not the race subclass)",
        )
    finally:
        evidence_review.apply_review_transition = _original5
    check("plain stale hash: writer was NEVER invoked", _calls5["n"] == 0)
    check("plain stale hash: ZERO journal rows were created", conn5.table == [])

    # ------------------------------------------------------------
    # 6) COMPOSITE PRECONDITION RACE - the pre-lock and under-lock
    #    scans disagree because a new audit file appears in between
    #    (simulated: seed a matching audit file BEFORE calling, so the
    #    pre-lock snapshot already reflects it, then verify the SAME
    #    call's ADMISSION GATE catches it too - see test 7 for the
    #    genuine mid-flight race via monkeypatching the snapshot fn).
    # ------------------------------------------------------------

    case_id6, case_dir6 = make_case()
    principal6, repo6 = make_principal_and_repo(case_id6)
    tmp6 = case_dir6 / "iso6"
    tmp6.mkdir()
    canonical6, audit_dir6 = make_evidence_fixture(tmp6)
    expected_hash6 = sha256_text(canonical6.read_text(encoding="utf-8"))

    _original_compute_snapshot = facade._compute_snapshot
    _snapshot_call_n = {"n": 0}

    def _racing_compute_snapshot(canonical_path, audit_dir):
        _snapshot_call_n["n"] += 1
        snap, scan = _original_compute_snapshot(canonical_path, audit_dir)
        if _snapshot_call_n["n"] == 2:
            # Simulate "something changed between pre-lock and
            # under-lock" by returning a snapshot with a different
            # composite_digest than what was really on disk at
            # pre-lock time.
            import dataclasses
            snap = dataclasses.replace(snap, composite_digest="tampered_" + snap.composite_digest[:20])
        return snap, scan

    conn6 = FakeJournalConn()
    _calls6 = {"n": 0}
    _original6 = evidence_review.apply_review_transition
    evidence_review.apply_review_transition = lambda *a, **k: _calls6.update(n=_calls6["n"] + 1) or _original6(*a, **k)
    facade._compute_snapshot = _racing_compute_snapshot
    try:
        expect_raises(
            ReviewPreconditionRaceDetectedError,
            lambda: facade.apply_review_mutation(
                "evidence.candidate", case_id6, "ec_1", "confirmed", "note", expected_hash6,
                evidence_binding(),
                principal=principal6, authz_repository=repo6, conn_factory=lambda: conn6,
                canonical_path_override=canonical6, audit_dir_override=audit_dir6,
            ),
            "composite snapshot changed under lock -> ReviewPreconditionRaceDetectedError (StaleViewError subclass)",
        )
    finally:
        evidence_review.apply_review_transition = _original6
        facade._compute_snapshot = _original_compute_snapshot
    check("composite race: writer was NEVER invoked", _calls6["n"] == 0)
    check("composite race: ZERO journal rows were created", conn6.table == [])
    check(
        "composite race: ReviewPreconditionRaceDetectedError IS a ReviewStaleViewError (existing except blocks unaffected)",
        issubclass(ReviewPreconditionRaceDetectedError, ReviewStaleViewError),
    )

    # ------------------------------------------------------------
    # 7) ADMISSION GATE - a pre-existing, content-matching audit
    #    record already exists for this exact record (restore/
    #    re-review attack: canonical looks fresh, but a genuine prior
    #    review's audit trail is already there).
    # ------------------------------------------------------------

    case_id7, case_dir7 = make_case()
    principal7, repo7 = make_principal_and_repo(case_id7)
    tmp7 = case_dir7 / "iso7"
    tmp7.mkdir()
    canonical7, audit_dir7 = make_evidence_fixture(tmp7)
    expected_hash7 = sha256_text(canonical7.read_text(encoding="utf-8"))
    audit_dir7.mkdir(parents=True)
    (audit_dir7 / "evidence_review_ec_1_20260101_000000.review_audit.json").write_text(
        json.dumps({
            "case_id": case_id7, "record_type": "candidate", "record_id": "ec_1",
            "review_note": "a pre-existing audit", "pre_sha256": "x" * 64, "post_sha256": "y" * 64,
            "previous_state": "needs_review", "new_state": "confirmed", "reviewer_ref": "local_lawyer_ui",
        }),
        encoding="utf-8",
    )
    conn7 = FakeJournalConn()
    _calls7 = {"n": 0}
    _original7 = evidence_review.apply_review_transition
    evidence_review.apply_review_transition = lambda *a, **k: _calls7.update(n=_calls7["n"] + 1) or _original7(*a, **k)
    try:
        expect_raises(
            ReviewPreconditionRaceDetectedError,
            lambda: facade.apply_review_mutation(
                "evidence.candidate", case_id7, "ec_1", "confirmed", "note", expected_hash7,
                evidence_binding(),
                principal=principal7, authz_repository=repo7, conn_factory=lambda: conn7,
                canonical_path_override=canonical7, audit_dir_override=audit_dir7,
            ),
            "admission gate: a pre-existing content-matching audit -> rejected fail-closed BEFORE the writer",
        )
    finally:
        evidence_review.apply_review_transition = _original7
    check("admission gate (pre-existing audit): writer was NEVER invoked", _calls7["n"] == 0)
    check("admission gate (pre-existing audit): ZERO journal rows were created", conn7.table == [])

    # ------------------------------------------------------------
    # 8) ADMISSION GATE - a corrupt audit-shaped file blocks the WHOLE
    #    family, even a completely unrelated record whose own state is
    #    clean 'needs_review'.
    # ------------------------------------------------------------

    case_id8, case_dir8 = make_case()
    principal8, repo8 = make_principal_and_repo(case_id8)
    tmp8 = case_dir8 / "iso8"
    tmp8.mkdir()
    canonical8, audit_dir8 = make_evidence_fixture(tmp8)
    expected_hash8 = sha256_text(canonical8.read_text(encoding="utf-8"))
    audit_dir8.mkdir(parents=True)
    (audit_dir8 / "evidence_review_some_other_record_20260101_000000.review_audit.json").write_text(
        "not valid json {{{", encoding="utf-8",
    )
    conn8 = FakeJournalConn()
    _calls8 = {"n": 0}
    _original8 = evidence_review.apply_review_transition
    evidence_review.apply_review_transition = lambda *a, **k: _calls8.update(n=_calls8["n"] + 1) or _original8(*a, **k)
    try:
        expect_raises(
            ReviewPreconditionRaceDetectedError,
            lambda: facade.apply_review_mutation(
                "evidence.candidate", case_id8, "ec_1", "confirmed", "note", expected_hash8,
                evidence_binding(),
                principal=principal8, authz_repository=repo8, conn_factory=lambda: conn8,
                canonical_path_override=canonical8, audit_dir_override=audit_dir8,
            ),
            "admission gate: a family-wide corrupt audit-shaped file blocks an UNRELATED record too",
        )
    finally:
        evidence_review.apply_review_transition = _original8
    check("admission gate (corrupt audit): writer was NEVER invoked", _calls8["n"] == 0)
    check("admission gate (corrupt audit): ZERO journal rows were created", conn8.table == [])

    # ------------------------------------------------------------
    # 9) GUARD-HOISTING - previous_state != needs_review (already
    #    reviewed) -> ReviewRecordNotFoundError, precondition-level,
    #    ZERO journal rows (never reconciliation_required).
    # ------------------------------------------------------------

    case_id9, case_dir9 = make_case()
    principal9, repo9 = make_principal_and_repo(case_id9)
    tmp9 = case_dir9 / "iso9"
    tmp9.mkdir()
    canonical9, audit_dir9 = make_evidence_fixture(tmp9, state="confirmed")
    expected_hash9 = sha256_text(canonical9.read_text(encoding="utf-8"))
    conn9 = FakeJournalConn()
    _calls9 = {"n": 0}
    _original9 = evidence_review.apply_review_transition
    evidence_review.apply_review_transition = lambda *a, **k: _calls9.update(n=_calls9["n"] + 1) or _original9(*a, **k)
    try:
        expect_raises(
            ReviewRecordNotFoundError,
            lambda: facade.apply_review_mutation(
                "evidence.candidate", case_id9, "ec_1", "rejected", "note", expected_hash9,
                evidence_binding(),
                principal=principal9, authz_repository=repo9, conn_factory=lambda: conn9,
                canonical_path_override=canonical9, audit_dir_override=audit_dir9,
            ),
            "guard-hoisting: record already 'confirmed' -> ReviewRecordNotFoundError, precondition-level",
        )
    finally:
        evidence_review.apply_review_transition = _original9
    check("guard-hoisting (already reviewed): writer was NEVER invoked", _calls9["n"] == 0)
    check("guard-hoisting (already reviewed): ZERO journal rows were created (never reconciliation_required)", conn9.table == [])

    # ------------------------------------------------------------
    # 10) GUARD-HOISTING - parent-dependency violation (argument
    #     family: counterargument review blocked while parent claim is
    #     still needs_review) -> the REAL ArgumentReviewError, via the
    #     REAL check_parent_dependency() called directly, precondition-
    #     level, ZERO journal rows.
    # ------------------------------------------------------------

    case_id10, case_dir10 = make_case()
    principal10, repo10 = make_principal_and_repo(case_id10)
    tmp10 = case_dir10 / "iso10"
    tmp10.mkdir()
    canonical10 = tmp10 / "arguments.json"
    canonical10.write_text(json.dumps({
        "argument_claims": [{"claim_id": "c1", "claim_review_state": "needs_review"}],
        "argument_counterarguments": [
            {"counterargument_id": "ca1", "counter_review_state": "needs_review", "source_claim_id": "c1"},
        ],
    }), encoding="utf-8")
    audit_dir10 = tmp10 / "reviews" / "argument_reviews"
    expected_hash10 = sha256_text(canonical10.read_text(encoding="utf-8"))
    conn10 = FakeJournalConn()
    _calls10 = {"n": 0}
    _original10 = argument_review.apply_review_transition
    argument_review.apply_review_transition = lambda *a, **k: _calls10.update(n=_calls10["n"] + 1) or _original10(*a, **k)
    try:
        expect_raises(
            argument_review.ArgumentReviewError,
            lambda: facade.apply_review_mutation(
                "argument.counterargument", case_id10, "ca1", "confirmed", "note", expected_hash10,
                argument_counterargument_binding(),
                principal=principal10, authz_repository=repo10, conn_factory=lambda: conn10,
                canonical_path_override=canonical10, audit_dir_override=audit_dir10,
            ),
            "guard-hoisting: parent claim still needs_review -> REAL ArgumentReviewError via check_parent_dependency(), precondition-level",
        )
    finally:
        argument_review.apply_review_transition = _original10
    check("guard-hoisting (parent-dependency): writer was NEVER invoked", _calls10["n"] == 0)
    check("guard-hoisting (parent-dependency): ZERO journal rows were created", conn10.table == [])

    # ------------------------------------------------------------
    # 11) OUTER AUTHZ DENIAL - zero connection/lock/hash reads.
    # ------------------------------------------------------------

    case_id11, case_dir11 = make_case()
    principal11, repo11 = make_principal_and_repo(case_id11, assigned=False)
    tmp11 = case_dir11 / "iso11"
    tmp11.mkdir()
    canonical11, audit_dir11 = make_evidence_fixture(tmp11)

    conn_factory_calls11 = []

    def counting_conn_factory11():
        conn_factory_calls11.append(1)
        return FakeJournalConn()

    _lock_calls.clear()
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: facade.apply_review_mutation(
            "evidence.candidate", case_id11, "ec_1", "confirmed", "note", "irrelevant",
            evidence_binding(),
            principal=principal11, authz_repository=repo11, conn_factory=counting_conn_factory11,
            canonical_path_override=canonical11, audit_dir_override=audit_dir11,
        ),
        "an unassigned case raises CaseAccessDeniedError from the OUTER authz check",
    )
    check("outer authz denial: ZERO journal/lock connections were opened", conn_factory_calls11 == [])
    check("outer authz denial: ZERO lock calls (never acquired, so nothing to release)", _lock_calls == [])

    # ------------------------------------------------------------
    # 12) note_hash_for() - pure hashing helper, direct proof it hashes
    #     the SAME normalized text both the facade and the writer see.
    # ------------------------------------------------------------

    check(
        "note_hash_for(): sha256 of the exact UTF-8 text given, nothing else",
        facade.note_hash_for("örnek not") == hashlib.sha256("örnek not".encode("utf-8")).hexdigest(),
    )

    # ------------------------------------------------------------
    # 13) REAL case_0001/qa/ tree byte-snapshot proof - tests 1-4 used
    #     case_0001's REAL upstream data (issues/facts/documents) to
    #     build a genuinely valid QA analysis, but every canonical/
    #     audit path was ALWAYS `canonical_path_override`/`audit_dir_
    #     override`-redirected to an isolated tempdir - this is the
    #     independent, byte-level proof that case_0001's own real qa/
    #     directory was never touched.
    # ------------------------------------------------------------

    _real_case_0001_qa_after = snapshot_real_case_0001_qa_tree()
    check(
        "REAL case_0001/qa/ tree is byte-for-byte UNCHANGED by this entire suite",
        _real_case_0001_qa_before == _real_case_0001_qa_after,
        f"before={_real_case_0001_qa_before} after={_real_case_0001_qa_after}",
    )

finally:
    ml.acquire_case_lock_session = _original_acquire_case
    ml.release_lock_session = _original_release
    for d in _created_case_dirs:
        shutil.rmtree(d, ignore_errors=True)


print(f"--- test_review_mutation_facade_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
