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
import os
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
import qa_approval                                                      # noqa: E402

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
        # ROW 19C-3a SLICE 2: `evidence_review.py` has its own `CASES_DIR`
        # (verified by direct reading) - matches `module=` exactly, same
        # as 10 of the 12 real registry entries (see `review_registry.
        # cases_dir_module_name()`'s own docstring).
        cases_dir_anchor_module=evidence_review,
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
        cases_dir_anchor_module=argument_review,
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
        # ROW 19C-3a SLICE 2: `qa_review.py` has NO `CASES_DIR` of its
        # own (verified by direct reading) - `qa_approval` is the
        # correct anchor, matching `review_registry.REVIEW_KIND_
        # REGISTRY["qa.suggestion"]["cases_dir_module"]` exactly.
        cases_dir_anchor_module=qa_approval,
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

    # ==================================================================
    # ROW 19C-3a SLICE 2 - NON-OVERRIDE nested path-containment scenario
    # matrix. Every test above uses `canonical_path_override`/`audit_
    # dir_override` (test-only, bypasses ALL new verification), so NONE
    # of them exercise the new code path at all - this section is the
    # first to do so, using a SYNTHETIC fake review-family module (its
    # own `CASES_DIR` monkeypatched to an isolated tempdir - never a
    # real backend module, never real case_0001 data) exactly as this
    # Slice's own scope report specified. Real NTFS junctions
    # (`mklink /J`, no elevation/Developer Mode needed) on
    # `sys.platform == "win32"`; explicitly, visibly skipped elsewhere.
    # ==================================================================

    check(
        "Row 19C-3a Slice 2: qa.suggestion's cases_dir_anchor_module is qa_approval specifically "
        "(the ONE registry exception), not qa_review itself",
        qa_binding().cases_dir_anchor_module is qa_approval,
    )

    if sys.platform != "win32":
        print(
            "SKIPPED (NOT counted as pass/fail) - ROW 19C-3a SLICE 2 non-override junction "
            f"scenarios need a real NTFS junction (sys.platform={sys.platform!r} here)."
        )
    else:
        import subprocess as _subprocess_a19c3a
        import os as _os_a19c3a
        import types as _types_a19c3a

        def _a19c3a_make_junction(link_path, target_path):
            result = _subprocess_a19c3a.run(
                ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                raise RuntimeError(f"mklink /J failed (rc={result.returncode}): {result.stdout!r} {result.stderr!r}")

        # ROW 19C-3a SLICE 2 CORRECTION: `authz.authorize_case_access()`
        # ALWAYS resolves `case_id` against the REAL `ui.services.paths.
        # CASES_DIR` (`data/cases/`) - completely independent of
        # whatever `CASES_DIR` the review-family backend module itself
        # uses (this is exactly why every REAL backend module's own
        # `CASES_DIR` happens to equal the SAME real `data/cases/` too -
        # see `ui.services.paths.py`'s own header comment). The fake
        # module below therefore anchors to the SAME real `_paths.
        # CASES_DIR` (never a separate synthetic tempdir) so a synthetic
        # case_id can pass authz for real, exactly mirroring `ui/tests/
        # test_mutation_approval_facade_isolated.py`'s own `make_fake_
        # module()` (`mod.CASES_DIR = _paths.CASES_DIR`).
        _outside_root_14 = Path(tempfile.mkdtemp(prefix="review_facade_a19c3a_outside_"))
        try:
            _fake_review_mod = _types_a19c3a.ModuleType("_fake_review_family_a19c3a")
            _fake_review_mod.CASES_DIR = _paths.CASES_DIR

            def _fake_get_canonical_path(case_id):
                return _paths.CASES_DIR / case_id / "family" / "canonical.json"

            def _fake_get_audit_dir(case_id):
                return _paths.CASES_DIR / case_id / "family" / "reviews" / "family_reviews"

            def _fake_find_record(analysis, record_type, record_id):
                for record in analysis.get("records", []):
                    if record.get("id") == record_id:
                        return record
                return None

            def _fake_apply_review_transition(
                case_id, record_type, record_id, target_state, reviewer_ref, review_note,
                canonical_path=None, audit_dir=None, *,
                mutation_idempotency_key=None, mutation_resource_key=None, mutation_actor_ref=None,
            ):
                canonical_path = Path(canonical_path if canonical_path is not None else _fake_get_canonical_path(case_id))
                audit_dir = Path(audit_dir if audit_dir is not None else _fake_get_audit_dir(case_id))
                analysis = json.loads(canonical_path.read_text(encoding="utf-8"))
                record = _fake_find_record(analysis, record_type, record_id)
                previous_state = record["review_state"]
                record["review_state"] = target_state
                canonical_path.write_text(json.dumps(analysis), encoding="utf-8")
                post_sha256 = sha256_text(canonical_path.read_text(encoding="utf-8"))
                audit_dir.mkdir(parents=True, exist_ok=True)
                audit_record = {
                    "case_id": case_id, "record_type": record_type, "record_id": record_id,
                    "new_state": target_state, "previous_state": previous_state,
                    "reviewer_ref": reviewer_ref, "review_note": review_note,
                    "pre_sha256": "x" * 64, "post_sha256": post_sha256,
                    "mutation_idempotency_key": mutation_idempotency_key,
                    "mutation_resource_key": mutation_resource_key,
                    "mutation_actor_ref": mutation_actor_ref,
                }
                audit_path = audit_dir / f"fake_{uuid.uuid4().hex}.review_audit.json"
                audit_path.write_text(json.dumps(audit_record), encoding="utf-8")
                return {
                    "previous_state": previous_state, "new_state": target_state,
                    "post_sha256": post_sha256, "audit_path": audit_path,
                }

            _fake_review_mod.get_canonical_path = _fake_get_canonical_path
            _fake_review_mod.get_audit_dir = _fake_get_audit_dir
            _fake_review_mod.find_record = _fake_find_record
            _fake_review_mod.apply_review_transition = _fake_apply_review_transition

            def _fake_binding():
                return facade.ReviewFamilyBinding(
                    review_kind="fake.record",
                    module=_fake_review_mod,
                    record_type="record",
                    call_shape="with_record_type",
                    state_field="review_state",
                    domain_error_class=RuntimeError,
                    get_audit_dir_fn=_fake_get_audit_dir,
                    reviewer_ref="local_lawyer_ui",
                    cases_dir_anchor_module=_fake_review_mod,
                )

            def _make_synth_case(record_id="rec_1", state="needs_review"):
                case_id = f"synthcase{uuid.uuid4().hex[:10]}"
                case_dir = _paths.CASES_DIR / case_id
                family_dir = case_dir / "family"
                family_dir.mkdir(parents=True, exist_ok=True)
                (case_dir / "case.json").write_text(json.dumps({"case_id": case_id}), encoding="utf-8")
                _created_case_dirs.append(case_dir)
                canonical_path = family_dir / "canonical.json"
                canonical_path.write_text(
                    json.dumps({"records": [{"id": record_id, "review_state": state}]}), encoding="utf-8",
                )
                return case_id, canonical_path

            # ----------------------------------------------------
            # 14a) Normal, non-adversarial mutation through the
            #      NON-OVERRIDE branch - the regression baseline this
            #      new code path did not have until now.
            # ----------------------------------------------------
            case_id14a, canonical_path14a = _make_synth_case()
            principal14a, repo14a = make_principal_and_repo(case_id14a)
            expected_hash14a = sha256_text(canonical_path14a.read_text(encoding="utf-8"))
            conn14a = FakeJournalConn()
            result14a = facade.apply_review_mutation(
                "fake.record", case_id14a, "rec_1", "confirmed", "note", expected_hash14a,
                _fake_binding(), principal=principal14a, authz_repository=repo14a, conn_factory=lambda: conn14a,
            )
            check(
                "14a: a normal NON-OVERRIDE mutation succeeds, writer received the verified path, "
                "canonical really flipped state",
                result14a.replayed is False
                and json.loads(canonical_path14a.read_text(encoding="utf-8"))["records"][0]["review_state"] == "confirmed",
            )
            check("14a: audit_path really exists on disk", result14a.audit_path is not None and Path(result14a.audit_path).exists())

            # ----------------------------------------------------
            # 14b) FAMILY-DIRECTORY-LEVEL escape: `family/` itself is a
            #      live junction pointing OUTSIDE the case root.
            # ----------------------------------------------------
            case_id14b, canonical_path14b = _make_synth_case()
            principal14b, repo14b = make_principal_and_repo(case_id14b)
            expected_hash14b = sha256_text(canonical_path14b.read_text(encoding="utf-8"))
            family_dir14b = canonical_path14b.parent
            shutil.rmtree(family_dir14b)
            outside_family14b = _outside_root_14 / f"family_{uuid.uuid4().hex}"
            outside_family14b.mkdir()
            (outside_family14b / "canonical.json").write_text('{"stolen": true}', encoding="utf-8")
            _a19c3a_make_junction(family_dir14b, outside_family14b)
            conn_calls14b = []
            expect_raises(
                facade.ReviewDirectoryScanError,
                lambda: facade.apply_review_mutation(
                    "fake.record", case_id14b, "rec_1", "confirmed", "note", expected_hash14b,
                    _fake_binding(), principal=principal14b, authz_repository=repo14b,
                    conn_factory=lambda: (conn_calls14b.append(1) or FakeJournalConn()),
                ),
                "14b: family directory itself is a LIVE escaping junction raises ReviewDirectoryScanError",
            )
            check("14b: ZERO journal/lock connections were opened (pre-lock failure)", conn_calls14b == [])
            _os_a19c3a.rmdir(family_dir14b)
            shutil.rmtree(outside_family14b, ignore_errors=True)

            # ----------------------------------------------------
            # 14c) AUDIT-DIRECTORY-LEVEL escape: `reviews/family_reviews`
            #      itself is a live junction pointing OUTSIDE the case
            #      root - the canonical file remains genuinely safe.
            # ----------------------------------------------------
            case_id14c, canonical_path14c = _make_synth_case()
            principal14c, repo14c = make_principal_and_repo(case_id14c)
            expected_hash14c = sha256_text(canonical_path14c.read_text(encoding="utf-8"))
            audit_dir14c = _fake_get_audit_dir(case_id14c)
            audit_dir14c.parent.mkdir(parents=True, exist_ok=True)
            outside_audit14c = _outside_root_14 / f"audit_{uuid.uuid4().hex}"
            outside_audit14c.mkdir()
            (outside_audit14c / "spy.review_audit.json").write_text(
                json.dumps({"planted": "must never be trusted"}), encoding="utf-8",
            )
            _a19c3a_make_junction(audit_dir14c, outside_audit14c)
            expect_raises(
                facade.ReviewDirectoryScanError,
                lambda: facade.apply_review_mutation(
                    "fake.record", case_id14c, "rec_1", "confirmed", "note", expected_hash14c,
                    _fake_binding(), principal=principal14c, authz_repository=repo14c,
                    conn_factory=lambda: FakeJournalConn(),
                ),
                "14c: audit_dir itself is a LIVE escaping junction raises ReviewDirectoryScanError, "
                "even though canonical itself is genuinely safe",
            )
            _os_a19c3a.rmdir(audit_dir14c)
            shutil.rmtree(outside_audit14c, ignore_errors=True)

            # ----------------------------------------------------
            # 14d) BROKEN junction at the audit-directory level (target
            #      deleted, reparse-point entry itself still on disk).
            # ----------------------------------------------------
            case_id14d, canonical_path14d = _make_synth_case()
            principal14d, repo14d = make_principal_and_repo(case_id14d)
            expected_hash14d = sha256_text(canonical_path14d.read_text(encoding="utf-8"))
            audit_dir14d = _fake_get_audit_dir(case_id14d)
            audit_dir14d.parent.mkdir(parents=True, exist_ok=True)
            outside_ghost14d = _outside_root_14 / f"ghost_{uuid.uuid4().hex}"
            outside_ghost14d.mkdir()
            _a19c3a_make_junction(audit_dir14d, outside_ghost14d)
            shutil.rmtree(outside_ghost14d, ignore_errors=True)
            check(
                "14d precondition: broken audit-dir junction has os.path.lexists()==True, "
                "Path.exists()==False",
                _os_a19c3a.path.lexists(audit_dir14d) is True and audit_dir14d.exists() is False,
            )
            expect_raises(
                facade.ReviewDirectoryScanError,
                lambda: facade.apply_review_mutation(
                    "fake.record", case_id14d, "rec_1", "confirmed", "note", expected_hash14d,
                    _fake_binding(), principal=principal14d, authz_repository=repo14d,
                    conn_factory=lambda: FakeJournalConn(),
                ),
                "14d: a BROKEN junction at the audit-dir level also raises ReviewDirectoryScanError, "
                "never silently treated as 'admission gate sees no prior audits'",
            )
            _os_a19c3a.rmdir(audit_dir14d)

            # ----------------------------------------------------
            # 14e) MATCHING-NAME ESCAPING ENTRY inside an otherwise-safe
            #      audit_dir (directory named `*.review_audit.json`,
            #      itself a junction pointing outside the case root).
            # ----------------------------------------------------
            case_id14e, canonical_path14e = _make_synth_case()
            principal14e, repo14e = make_principal_and_repo(case_id14e)
            expected_hash14e = sha256_text(canonical_path14e.read_text(encoding="utf-8"))
            audit_dir14e = _fake_get_audit_dir(case_id14e)
            audit_dir14e.mkdir(parents=True, exist_ok=True)
            outside_entry14e = _outside_root_14 / f"entry_{uuid.uuid4().hex}"
            outside_entry14e.mkdir()
            escaping_entry14e = audit_dir14e / "escaping.review_audit.json"
            _a19c3a_make_junction(escaping_entry14e, outside_entry14e)
            expect_raises(
                facade.ReviewDirectoryScanError,
                lambda: facade.apply_review_mutation(
                    "fake.record", case_id14e, "rec_1", "confirmed", "note", expected_hash14e,
                    _fake_binding(), principal=principal14e, authz_repository=repo14e,
                    conn_factory=lambda: FakeJournalConn(),
                ),
                "14e: a matching-NAME escaping entry inside an otherwise-safe audit_dir raises "
                "ReviewDirectoryScanError, aborting the whole scan",
            )
            _os_a19c3a.rmdir(escaping_entry14e)
            shutil.rmtree(outside_entry14e, ignore_errors=True)

            # ----------------------------------------------------
            # 14f) IN-TREE WRONG-PARENT ALIAS: a matching-name entry
            #      that resolves to a MULTI-LEVEL descendant of audit_dir
            #      (via a nested subdirectory that should never exist
            #      here) rather than a DIRECT child - passes plain
            #      containment (relative_to(audit_dir) succeeds) but
            #      fails the exact expected-parent-membership check.
            # ----------------------------------------------------
            case_id14f, canonical_path14f = _make_synth_case()
            principal14f, repo14f = make_principal_and_repo(case_id14f)
            expected_hash14f = sha256_text(canonical_path14f.read_text(encoding="utf-8"))
            audit_dir14f = _fake_get_audit_dir(case_id14f)
            nested_target14f = audit_dir14f / "subdir" / "nested"
            nested_target14f.mkdir(parents=True, exist_ok=True)
            alias_entry14f = audit_dir14f / "alias.review_audit.json"
            _a19c3a_make_junction(alias_entry14f, nested_target14f)
            expect_raises(
                facade.ReviewDirectoryScanError,
                lambda: facade.apply_review_mutation(
                    "fake.record", case_id14f, "rec_1", "confirmed", "note", expected_hash14f,
                    _fake_binding(), principal=principal14f, authz_repository=repo14f,
                    conn_factory=lambda: FakeJournalConn(),
                ),
                "14f: an in-tree entry resolving to a multi-level descendant (wrong immediate parent) "
                "of audit_dir raises ReviewDirectoryScanError - plain containment alone would have "
                "passed this",
            )
            _os_a19c3a.rmdir(alias_entry14f)

            # ----------------------------------------------------
            # 14g) PRE-LOCK -> UNDER-LOCK AUDIT-DIRECTORY SWAP: audit_dir
            #      is safe at pre-lock verification time, then replaced
            #      with an escaping junction WHILE this request waits
            #      for the case lock - caught by the fresh under-lock
            #      re-verification, zero prepared journal rows.
            # ----------------------------------------------------
            case_id14g, canonical_path14g = _make_synth_case()
            principal14g, repo14g = make_principal_and_repo(case_id14g)
            expected_hash14g = sha256_text(canonical_path14g.read_text(encoding="utf-8"))
            audit_dir14g = _fake_get_audit_dir(case_id14g)
            audit_dir14g.mkdir(parents=True, exist_ok=True)
            conn14g = FakeJournalConn()
            outside_swap14g = _outside_root_14 / f"swap_{uuid.uuid4().hex}"
            outside_swap14g.mkdir()

            def _acquire_then_swap_audit_dir(conn, case_id):
                _lock_calls.append(("acquire", case_id))
                shutil.rmtree(audit_dir14g, ignore_errors=True)
                _a19c3a_make_junction(audit_dir14g, outside_swap14g)
                return 111

            ml.acquire_case_lock_session = _acquire_then_swap_audit_dir
            try:
                expect_raises(
                    facade.ReviewDirectoryScanError,
                    lambda: facade.apply_review_mutation(
                        "fake.record", case_id14g, "rec_1", "confirmed", "note", expected_hash14g,
                        _fake_binding(), principal=principal14g, authz_repository=repo14g,
                        conn_factory=lambda: conn14g,
                    ),
                    "14g: audit_dir swapped to an escaping junction WHILE waiting for the lock is "
                    "caught by the fresh under-lock re-verification",
                )
            finally:
                ml.acquire_case_lock_session = _fake_acquire_case_lock_session
                shutil.rmtree(audit_dir14g, ignore_errors=True)
            check("14g: ZERO prepared journal rows", conn14g.table == [])

            # ----------------------------------------------------
            # 14h) ROW 19C-3a SLICE 2 FINAL NARROW REMEDIATION -
            #      CONTAINMENT-BEFORE-STAT ORDERING PROOF (by
            #      instrumentation, not source/AST inspection). An
            #      independent review found `_scan_review_directory()`
            #      used to call `entry.is_file()` on the RAW, unverified
            #      entry BEFORE containment was checked at all - a
            #      directory-only NTFS junction always fails
            #      `is_file()`, so the OLD "not a file" branch fired
            #      first and the containment check was never even
            #      reached for that entry (even though the FINAL
            #      exception class happened to be identical either
            #      way). `pathlib.Path.is_file` is monkeypatched here to
            #      record every `self` it is called on; a directory
            #      containing ONE escaping-junction entry named
            #      `*.review_audit.json` is scanned directly - the scan
            #      must still raise `ReviewDirectoryScanError`, but
            #      `is_file` must NEVER be invoked at all for this
            #      attempt, proving containment now runs strictly
            #      BEFORE any is_file()/stat() touch.
            # ----------------------------------------------------
            ordering_dir_14h = _outside_root_14 / f"ordering_audit_{uuid.uuid4().hex}"
            ordering_dir_14h.mkdir()
            ordering_outside_14h = _outside_root_14 / f"ordering_outside_{uuid.uuid4().hex}"
            ordering_outside_14h.mkdir()
            ordering_entry_14h = ordering_dir_14h / "escaping.review_audit.json"
            _a19c3a_make_junction(ordering_entry_14h, ordering_outside_14h)

            is_file_calls_14h = []
            _original_is_file_14h = Path.is_file

            def _recording_is_file_14h(self):
                is_file_calls_14h.append(str(self))
                return _original_is_file_14h(self)

            try:
                Path.is_file = _recording_is_file_14h
                ordering_error_14h = None
                try:
                    facade._scan_review_directory(ordering_dir_14h)
                except Exception as error:
                    ordering_error_14h = error
            finally:
                Path.is_file = _original_is_file_14h
                os.rmdir(ordering_entry_14h)
                shutil.rmtree(ordering_dir_14h, ignore_errors=True)
                shutil.rmtree(ordering_outside_14h, ignore_errors=True)

            check(
                "14h: _scan_review_directory() still raises ReviewDirectoryScanError for the "
                "escaping matching-name entry",
                isinstance(ordering_error_14h, facade.ReviewDirectoryScanError),
                f"got {ordering_error_14h!r}",
            )
            check(
                "14h ORDERING PROOF: Path.is_file() was NEVER called during this scan attempt - "
                "containment verification ran strictly before any is_file()/stat() touch on the "
                "matching entry (proven by instrumentation, not source inspection)",
                is_file_calls_14h == [],
                f"is_file was called on: {is_file_calls_14h!r}",
            )
        finally:
            shutil.rmtree(_outside_root_14, ignore_errors=True)

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
