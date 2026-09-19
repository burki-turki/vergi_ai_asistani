# ============================================================
# FACT VERIFICATION WORKFLOW - isolated tests for
# ui/services/fact_verification_mutation_facade.py AND
# ui/services/fact_verification_mutation_adapters.py (fake journal
# conn, fake locks, in-memory authz, REAL src/fact_verification.py
# writer against REAL, re-identified synthetic copies of case_0001
# created under the real `data/cases/` tree and fully removed at the
# end - the ENTIRE real data/ tree is snapshot-compared before/after).
#
# Run: python ui/tests/test_fact_verification_mutation_facade_isolated.py
# ============================================================

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ui.services import authz as _authz                                        # noqa: E402
from ui.services import mutation_coordinator as mc                             # noqa: E402
from ui.services import mutation_lock as ml                                    # noqa: E402
from ui.services import mutation_registry as mr                                # noqa: E402
from ui.services import paths as _paths                                        # noqa: E402
from ui.services import fact_verification_mutation_adapters as fv_adapters     # noqa: E402
from ui.services import fact_verification_mutation_facade as fv_facade         # noqa: E402
from ui.services.common import StaleViewError, PreconditionRaceDetectedError   # noqa: E402

import fact_verification as fv                                                  # noqa: E402

# CONTINUATION TURN (Fable FINAL §O completion): real downstream (Row 12
# evidence) staleness + real timeline validator downgrade-ERROR proofs
# reuse these EXISTING, LOCKED production modules directly - none of
# their domain logic is reimplemented or mocked.
import evidence_engine as _evidence_engine                                      # noqa: E402
import evidence_policy as _evidence_policy                                      # noqa: E402
import evidence_validator as _evidence_validator                                # noqa: E402
import legal_research_validator as _legal_research_validator                    # noqa: E402
import timeline_engine as _timeline_engine                                      # noqa: E402
import timeline_validator as _timeline_validator                                # noqa: E402

_IS_WINDOWS = sys.platform == "win32"

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
    except exc_type as error:
        check(label, True)
        return error
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {type(error).__name__}: {error!r}")
        return None
    else:
        check(label, False, f"{detail} - no exception raised")
        return None


REAL_DATA_DIR = REPO_ROOT / "data"


def snapshot_data_tree():
    out = {}
    for path in REAL_DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(REAL_DATA_DIR))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(REAL_DATA_DIR))] = "<unreadable>"
    return out


_data_tree_before_everything = snapshot_data_tree()


# ----------------------------------------------------------------
# Fake mutation.mutation_journal (same shape used by every prior
# facade's own isolated test).
# ----------------------------------------------------------------

class FakeJournalCursor:
    def __init__(self, conn):
        self._conn = conn
        self._last_result = None
        self.rowcount = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _row(self, journal_id):
        for r in self._conn.table:
            if r["id"] == journal_id:
                return r
        raise AssertionError(f"no fake journal row with id={journal_id}")

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._conn.calls.append(normalized.split()[0])

        if normalized.startswith("SELECT 1 FROM mutation.mutation_journal"):
            (resource_key,) = params
            hit = any(
                r["resource_key"] == resource_key
                and r["state"] in ("prepared", "executing", "reconciliation_required")
                for r in self._conn.table
            )
            self._last_result = (1,) if hit else None
        elif normalized.startswith("SELECT id, state, request_fingerprint, observed_post_hash"):
            (idempotency_key,) = params
            matches = [r for r in self._conn.table if r["idempotency_key"] == idempotency_key]
            if not matches:
                self._last_result = None
            else:
                r = matches[0]
                self._last_result = (
                    r["id"], r["state"], r["request_fingerprint"], r["observed_post_hash"],
                    r["failure_code"], r["resolution_code"],
                )
        elif normalized.startswith("INSERT INTO mutation.mutation_journal"):
            (
                resource_key, action_family, actor_user_id, actor_label, target_ref, target_state,
                pre_hash, pre_revision, idempotency_key, request_fingerprint,
            ) = params
            new_id = len(self._conn.table) + 1
            self._conn.table.append({
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
                "observed_post_hash": None,
            })
            self._last_result = (new_id,)
            self.rowcount = 1
        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'executing'"):
            (journal_id,) = params
            self._row(journal_id)["state"] = "executing"
            self.rowcount = 1
        elif normalized.startswith("UPDATE mutation.mutation_journal SET state = 'completed'"):
            observed_post_hash, journal_id = params
            if self._conn.break_completed:
                self.rowcount = 0
            else:
                row = self._row(journal_id)
                row["state"] = "completed"
                row["observed_post_hash"] = observed_post_hash
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
    def __init__(self):
        self.table = []
        self.calls = []
        self.closed = False
        self.break_completed = False

    def cursor(self):
        return FakeJournalCursor(self)

    def close(self):
        self.closed = True


_lock_calls = []
_on_acquire_hooks = []
_original_acquire = ml.acquire_case_lock_session
_original_release = ml.release_lock_session


def _fake_acquire(conn, case_id):
    _lock_calls.append(("acquire", case_id))
    for hook in list(_on_acquire_hooks):
        hook(case_id)
    return 4242


def _fake_release(conn, advisory_lock_id):
    _lock_calls.append(("release", advisory_lock_id))
    return True


_created_case_dirs = []
FACT_DOC = "dava_dilekcesi_001"


def make_case():
    case_id = f"fvfciso{uuid.uuid4().hex[:9]}"
    src = _paths.CASES_DIR / "case_0001"
    dst = _paths.CASES_DIR / case_id
    shutil.copytree(src, dst)
    for path in dst.rglob("*"):
        if path.is_file() and (path.suffix in (".json", ".pending", ".bak") or path.name.endswith(".json.pending")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "case_0001" in text:
                path.write_text(text.replace("case_0001", case_id), encoding="utf-8")
    _created_case_dirs.append(dst)
    return case_id, dst


def make_principal_and_repo(case_id, *, assigned=True, role="lawyer"):
    principal = _authz.Principal(user_id=7, session_id=700, role_version_at_issue=1)
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[700] = _authz.SessionRecord(user_id=7, current_authz_version=1, disabled=False)
    if assigned:
        repo.assignments[(7, case_id)] = _authz.CaseAssignmentRecord(role=role)
    return principal, repo


def canonical_path_for(case_dir, document_id=FACT_DOC):
    return case_dir / "documents" / document_id / "extractions" / "facts.json"


def apply_verification(case_id, document_id, fact_id, expected_hash, target_state, *,
                        evidence_document_id=None, attempt=1, principal, repo, conn=None):
    conn = conn if conn is not None else FakeJournalConn()
    calls = {"n": 0}

    def conn_factory():
        calls["n"] += 1
        return conn

    result = fv_facade.apply_verification_mutation(
        case_id, document_id, fact_id, expected_hash, target_state,
        evidence_document_id=evidence_document_id, attempt=attempt,
        principal=principal, authz_repository=repo, conn_factory=conn_factory,
    )
    return result, conn, calls


ml.acquire_case_lock_session = _fake_acquire
ml.release_lock_session = _fake_release

try:
    # ============================================================
    # F1 - happy path: unverified -> verified, WITH evidence-ref.
    # ============================================================
    case_id1, case_dir1 = make_case()
    canonical1 = canonical_path_for(case_dir1)
    extraction1 = json.loads(canonical1.read_bytes().decode("utf-8"))
    fact1 = extraction1["facts"][0]
    fact_id1 = fact1["fact_id"]
    principal1, repo1 = make_principal_and_repo(case_id1)
    canonical_sha1 = hashlib.sha256(canonical1.read_bytes()).hexdigest()

    preview1 = fv_facade.preview_verification(
        case_id1, FACT_DOC, fact_id1, principal=principal1, authz_repository=repo1,
    )
    check("F1a preview reports correct from_state/hash/allowed evidence",
          preview1["from_state"] == "unverified" and preview1["canonical_sha256"] == canonical_sha1
          and extraction1["source_document_id"] in preview1["allowed_evidence_documents"])

    result1, conn1, _ = apply_verification(
        case_id1, FACT_DOC, fact_id1, canonical_sha1, "verified",
        evidence_document_id=extraction1["source_document_id"],
        principal=principal1, repo=repo1,
    )
    check("F1b apply returns replayed=False, correct from/target state",
          result1.replayed is False and result1.from_state == "unverified" and result1.target_state == "verified")
    check("F1c journal row completed", conn1.table[0]["state"] == "completed")
    check("F1d journal action_family/target_ref/target_state correct",
          conn1.table[0]["action_family"] == "verification.fact"
          and conn1.table[0]["target_ref"] == f"fact.{FACT_DOC}.{fact_id1}.verification"
          and conn1.table[0]["target_state"] == "verified")
    reloaded1 = json.loads(canonical1.read_bytes().decode("utf-8"))
    check("F1e canonical fact state actually changed on disk",
          fv.find_fact(reloaded1, fact_id1)["verification_state"] == "verified")
    audit1 = json.loads(Path(result1.audit_path).read_text(encoding="utf-8"))
    check("F1f audit carries mutation_idempotency_key/resource_key/actor_ref",
          audit1.get("mutation_idempotency_key") == conn1.table[0]["idempotency_key"]
          and audit1.get("mutation_resource_key") == f"case:{case_id1}"
          and audit1.get("mutation_actor_ref") == "7")
    check("F1g audit identity_payload round-trips to entry.pre_revision",
          hashlib.sha256(
              json.dumps(audit1["identity_payload"], sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("utf-8")
          ).hexdigest() == conn1.table[0]["pre_revision"])

    # ============================================================
    # F2 - SELF-TRANSITION rejected for all three states (fail-closed,
    #      zero journal rows).
    # ============================================================
    case_id2, case_dir2 = make_case()
    canonical2 = canonical_path_for(case_dir2)
    extraction2 = json.loads(canonical2.read_bytes().decode("utf-8"))
    fact_id2 = extraction2["facts"][0]["fact_id"]
    principal2, repo2 = make_principal_and_repo(case_id2)
    canonical_sha2 = hashlib.sha256(canonical2.read_bytes()).hexdigest()
    conn2 = FakeJournalConn()
    expect_raises(
        fv_facade.FactVerificationNoOpError,
        lambda: apply_verification(
            case_id2, FACT_DOC, fact_id2, canonical_sha2, "unverified",
            principal=principal2, repo=repo2, conn=conn2,
        ),
        "F2a unverified->unverified self-transition -> FactVerificationNoOpError",
    )
    check("F2b self-transition wrote ZERO journal rows", len(conn2.table) == 0)
    check("F2c self-transition left canonical byte-unchanged",
          hashlib.sha256(canonical2.read_bytes()).hexdigest() == canonical_sha2)

    # Move to 'verified' first, then confirm verified->verified is rejected too.
    result2b, conn2b, _ = apply_verification(
        case_id2, FACT_DOC, fact_id2, canonical_sha2, "verified",
        evidence_document_id=extraction2["source_document_id"], principal=principal2, repo=repo2,
    )
    canonical_sha2b = result2b.canonical_hash
    expect_raises(
        fv_facade.FactVerificationNoOpError,
        lambda: apply_verification(
            case_id2, FACT_DOC, fact_id2, canonical_sha2b, "verified",
            evidence_document_id=extraction2["source_document_id"],
            principal=principal2, repo=repo2, conn=conn2b,
        ),
        "F2d verified->verified self-transition -> FactVerificationNoOpError",
    )
    check("F2e verified->verified rejection created NO new journal row", len(conn2b.table) == 1)

    # partially_verified->partially_verified.
    result2c, conn2c, _ = apply_verification(
        case_id2, FACT_DOC, fact_id2, canonical_sha2b, "partially_verified",
        evidence_document_id=extraction2["source_document_id"], principal=principal2, repo=repo2,
    )
    conn2d = FakeJournalConn()
    expect_raises(
        fv_facade.FactVerificationNoOpError,
        lambda: apply_verification(
            case_id2, FACT_DOC, fact_id2, result2c.canonical_hash, "partially_verified",
            evidence_document_id=extraction2["source_document_id"],
            principal=principal2, repo=repo2, conn=conn2d,
        ),
        "F2f partially_verified->partially_verified self-transition -> FactVerificationNoOpError",
    )
    check("F2g self-transition (3rd variant) wrote ZERO journal rows", len(conn2d.table) == 0)

    # ============================================================
    # F3 - all SIX real transitions succeed.
    # ============================================================
    case_id3, case_dir3 = make_case()
    canonical3 = canonical_path_for(case_dir3)
    extraction3 = json.loads(canonical3.read_bytes().decode("utf-8"))
    fact_id3 = extraction3["facts"][0]["fact_id"]
    doc3 = extraction3["source_document_id"]
    principal3, repo3 = make_principal_and_repo(case_id3)

    transitions = [
        ("unverified", "partially_verified"),
        ("partially_verified", "verified"),
        ("verified", "partially_verified"),
        ("partially_verified", "unverified"),
        ("unverified", "verified"),
        ("verified", "unverified"),
    ]
    current_hash = hashlib.sha256(canonical3.read_bytes()).hexdigest()
    all_ok = True
    for idx, (from_s, to_s) in enumerate(transitions):
        needs_evidence = to_s in ("verified", "partially_verified")
        result, _, _ = apply_verification(
            case_id3, FACT_DOC, fact_id3, current_hash, to_s,
            evidence_document_id=doc3 if needs_evidence else None,
            principal=principal3, repo=repo3,
        )
        if result.from_state != from_s or result.target_state != to_s:
            all_ok = False
        current_hash = result.canonical_hash
    check(f"F3 all six real transitions succeed in sequence {transitions}", all_ok)

    # ============================================================
    # F4 - evidence / locator rules.
    # ============================================================
    case_id4, case_dir4 = make_case()
    canonical4 = canonical_path_for(case_dir4)
    extraction4 = json.loads(canonical4.read_bytes().decode("utf-8"))
    fact_id4 = extraction4["facts"][0]["fact_id"]
    principal4, repo4 = make_principal_and_repo(case_id4)
    canonical_sha4 = hashlib.sha256(canonical4.read_bytes()).hexdigest()

    # verified WITHOUT evidence-ref -> argument error, before any I/O.
    expect_raises(
        fv_facade.FactVerificationArgumentError,
        lambda: apply_verification(
            case_id4, FACT_DOC, fact_id4, canonical_sha4, "verified", principal=principal4, repo=repo4,
        ),
        "F4a target_state=verified WITHOUT evidence-ref -> FactVerificationArgumentError",
    )
    # partially_verified WITHOUT evidence-ref -> also required per this workflow's business rule.
    expect_raises(
        fv_facade.FactVerificationArgumentError,
        lambda: apply_verification(
            case_id4, FACT_DOC, fact_id4, canonical_sha4, "partially_verified",
            principal=principal4, repo=repo4,
        ),
        "F4b target_state=partially_verified WITHOUT evidence-ref -> FactVerificationArgumentError",
    )
    # evidence-ref not in the allowed set -> rejected.
    conn4c = FakeJournalConn()
    expect_raises(
        fv_facade.FactVerificationEvidenceNotAllowedError,
        lambda: apply_verification(
            case_id4, FACT_DOC, fact_id4, canonical_sha4, "verified",
            evidence_document_id="totally_unrelated_doc_id",
            principal=principal4, repo=repo4, conn=conn4c,
        ),
        "F4c evidence-ref outside {source_document_id} UNION related_document_ids -> "
        "FactVerificationEvidenceNotAllowedError",
    )
    check("F4d disallowed-evidence rejection wrote ZERO journal rows", len(conn4c.table) == 0)

    # unverified downgrade WITHOUT evidence-ref succeeds (evidence optional there).
    result4e, _, _ = apply_verification(
        case_id4, FACT_DOC, fact_id4, canonical_sha4, "partially_verified",
        evidence_document_id=extraction4["source_document_id"], principal=principal4, repo=repo4,
    )
    result4f, _, _ = apply_verification(
        case_id4, FACT_DOC, fact_id4, result4e.canonical_hash, "unverified",
        principal=principal4, repo=repo4,
    )
    check("F4e unverified downgrade succeeds WITHOUT any evidence-ref", result4f.target_state == "unverified")

    # ============================================================
    # F5 - preview never mutates; zero journal/lock/write.
    # ============================================================
    case_id5, case_dir5 = make_case()
    canonical5 = canonical_path_for(case_dir5)
    canonical_sha5_before = hashlib.sha256(canonical5.read_bytes()).hexdigest()
    principal5, repo5 = make_principal_and_repo(case_id5)
    extraction5 = json.loads(canonical5.read_bytes().decode("utf-8"))
    fact_id5 = extraction5["facts"][0]["fact_id"]
    _lock_calls_before5 = len(_lock_calls)
    _ = fv_facade.preview_verification(case_id5, FACT_DOC, fact_id5, principal=principal5, authz_repository=repo5)
    check("F5a preview leaves canonical byte-unchanged",
          hashlib.sha256(canonical5.read_bytes()).hexdigest() == canonical_sha5_before)
    check("F5b preview acquired ZERO locks", len(_lock_calls) == _lock_calls_before5)

    # ============================================================
    # F6 - stale --expected-hash -> StaleViewError, zero rows.
    # ============================================================
    case_id6, case_dir6 = make_case()
    canonical6 = canonical_path_for(case_dir6)
    canonical_sha6_before = hashlib.sha256(canonical6.read_bytes()).hexdigest()
    principal6, repo6 = make_principal_and_repo(case_id6)
    extraction6 = json.loads(canonical6.read_bytes().decode("utf-8"))
    fact_id6 = extraction6["facts"][0]["fact_id"]
    conn6 = FakeJournalConn()
    expect_raises(
        StaleViewError,
        lambda: apply_verification(
            case_id6, FACT_DOC, fact_id6, "0" * 64, "unverified", principal=principal6, repo=repo6, conn=conn6,
        ),
        "F6a wrong --expected-hash -> StaleViewError",
    )
    check("F6b stale rejection wrote ZERO journal rows", len(conn6.table) == 0)
    check("F6c stale rejection left canonical untouched",
          hashlib.sha256(canonical6.read_bytes()).hexdigest() == canonical_sha6_before)

    # ============================================================
    # F7 - safe replay (writer not re-invoked) + conflicting replay
    #      (--attempt N+1 opens a new slot).
    # ============================================================
    case_id7, case_dir7 = make_case()
    canonical7 = canonical_path_for(case_dir7)
    extraction7 = json.loads(canonical7.read_bytes().decode("utf-8"))
    fact_id7 = extraction7["facts"][0]["fact_id"]
    doc7 = extraction7["source_document_id"]
    principal7, repo7 = make_principal_and_repo(case_id7)
    canonical_sha7 = hashlib.sha256(canonical7.read_bytes()).hexdigest()

    result7a, conn7, _ = apply_verification(
        case_id7, FACT_DOC, fact_id7, canonical_sha7, "verified",
        evidence_document_id=doc7, principal=principal7, repo=repo7,
    )
    audit_count_before_replay = len(list((case_dir7 / "documents" / FACT_DOC / "extractions" / "reviews"
                                           / "fact_verifications").glob("*.verification.json")))
    result7b, _, _ = apply_verification(
        case_id7, FACT_DOC, fact_id7, canonical_sha7, "verified",
        evidence_document_id=doc7, principal=principal7, repo=repo7, conn=conn7,
    )
    check("F7a safe replay returns replayed=True", result7b.replayed is True)
    check("F7b safe replay: journal table still has exactly ONE row", len(conn7.table) == 1)
    check(
        "F7c safe replay: audit file count unchanged (writer genuinely NOT re-invoked)",
        len(list((case_dir7 / "documents" / FACT_DOC / "extractions" / "reviews"
                  / "fact_verifications").glob("*.verification.json"))) == audit_count_before_replay,
    )

    # Conflicting replay: same identity (same canonical H, same attempt),
    # DIFFERENT evidence-ref -> IdempotencyConflictError.
    # F3 REMEDIATION (independent review, Low): the first implementation
    # used facts[0] (whose related_document_ids is EMPTY in the real
    # case_0001 fixture) and fell into a `check(..., True)` branch - a
    # skip counted as a PASS. Now a fact that GENUINELY carries a second
    # allowed evidence document is located; if the fixture has none the
    # test FAILS LOUDLY (no conditional PASS, no skip branch).
    fact7d = next(
        (f for f in extraction7.get("facts", [])
         if any(d != doc7 for d in (f.get("related_document_ids") or []))),
        None,
    )
    check(
        "F7d-setup the real fixture carries a fact with a second allowed evidence document "
        "(related_document_ids) - required, never skipped",
        fact7d is not None,
    )
    if fact7d is None:
        raise AssertionError("F7d/F7e fixture precondition failed - fact with related_document_ids required")
    fact_id7d = fact7d["fact_id"]
    other_doc7 = next(d for d in fact7d["related_document_ids"] if d != doc7)
    canonical_sha7d = hashlib.sha256(canonical7.read_bytes()).hexdigest()
    apply_verification(
        case_id7, FACT_DOC, fact_id7d, canonical_sha7d, "verified",
        evidence_document_id=doc7, principal=principal7, repo=repo7, conn=conn7,
    )
    check("F7d-setup second fact verified with the source document as evidence (2 rows now)",
          len(conn7.table) == 2)
    err7d = expect_raises(
        mc.IdempotencyConflictError,
        lambda: apply_verification(
            case_id7, FACT_DOC, fact_id7d, canonical_sha7d, "verified",
            evidence_document_id=other_doc7, principal=principal7, repo=repo7, conn=conn7,
        ),
        "F7d same identity + DIFFERENT evidence-ref (related_document_ids member) -> "
        "IdempotencyConflictError (secondary_input_hash fingerprint path genuinely exercised)",
    )
    check(
        "F7d the conflict is the fact-specific, actionable subclass "
        "(FactVerificationIdentityConflictError) carrying the --attempt N+1 guidance",
        isinstance(err7d, fv_facade.FactVerificationIdentityConflictError)
        and "--attempt N+1" in str(err7d) and str(case_dir7) not in str(err7d),
    )
    check("F7e conflict created NO new journal row", len(conn7.table) == 2)

    # ============================================================
    # F7g/h/i - the `--attempt` dead-end-closing mechanism: after a
    #      PRIOR attempt is TERMINALLY 'failed' (reconciliation resolved
    #      it as pre_state_confirmed_unchanged - canonical genuinely
    #      never moved for that identity), attempt=1 retry is a
    #      permanent PriorAttemptFailedError; attempt=2 with the SAME
    #      still-valid expected_hash (canonical truly unchanged) opens a
    #      genuinely NEW identity slot and succeeds. This mirrors the
    #      rag_bundle precedent's own use of an attempt counter to close
    #      exactly this dead-end - it is NOT meant to paper over a case
    #      where the mutation already succeeded (see the facade's own
    #      docstring: a fresh preview/new expected_hash is required
    #      after a genuine success).
    # ============================================================
    from mutation_guard import (
        MutationIntent as _MI, compute_idempotency_key as _cik, compute_request_fingerprint as _crf,
    )

    case_id7g, case_dir7g = make_case()
    canonical7g = canonical_path_for(case_dir7g)
    extraction7g = json.loads(canonical7g.read_bytes().decode("utf-8"))
    fact_id7g = extraction7g["facts"][0]["fact_id"]
    doc7g = extraction7g["source_document_id"]
    principal7g, repo7g = make_principal_and_repo(case_id7g)
    canonical_sha7g = hashlib.sha256(canonical7g.read_bytes()).hexdigest()
    conn7g = FakeJournalConn()

    identity_payload_7g = fv_facade.compute_identity_payload(canonical_sha7g, 1)
    pre_revision_7g = fv_facade.compute_pre_revision(identity_payload_7g)
    secondary_7g = fv_facade._compute_secondary_input_hash(doc7g)
    intent_7g = _MI(
        actor_type="iam_user", actor_ref="7", resource_key=f"case:{case_id7g}",
        action_family="verification.fact", target_ref=f"fact.{FACT_DOC}.{fact_id7g}.verification",
        target_state="verified", pre_hash="d" * 64, pre_revision=pre_revision_7g,
        secondary_input_hash=secondary_7g,
    )
    idem_key_7g = _cik(intent_7g)
    fp_7g = _crf(intent_7g)
    conn7g.table.append({
        "id": 1, "resource_key": f"case:{case_id7g}", "action_family": "verification.fact",
        "actor_user_id": 7, "actor_label": "7", "target_ref": intent_7g.target_ref,
        "target_state": "verified", "pre_hash": intent_7g.pre_hash, "pre_revision": pre_revision_7g,
        "idempotency_key": idem_key_7g, "request_fingerprint": fp_7g, "state": "failed",
        "failure_code": None, "resolution_code": "reconciled_failed_pre_state_confirmed_unchanged",
        "observed_post_hash": None,
    })

    expect_raises(
        mc.PriorAttemptFailedError,
        lambda: apply_verification(
            case_id7g, FACT_DOC, fact_id7g, canonical_sha7g, "verified",
            evidence_document_id=doc7g, attempt=1, principal=principal7g, repo=repo7g, conn=conn7g,
        ),
        "F7g attempt=1 with a prior terminal 'failed' row for the SAME identity -> "
        "PriorAttemptFailedError",
    )
    check("F7h attempt=1 retry created NO new row (terminal, permanent)", len(conn7g.table) == 1)

    result7i, _, _ = apply_verification(
        case_id7g, FACT_DOC, fact_id7g, canonical_sha7g, "verified",
        evidence_document_id=doc7g, attempt=2, principal=principal7g, repo=repo7g, conn=conn7g,
    )
    check(
        "F7i attempt=2 with the SAME still-valid expected_hash opens a genuinely NEW identity "
        "slot and succeeds",
        conn7g.table[-1]["state"] == "completed" and result7i.replayed is False,
    )

    # ============================================================
    # F8 - composite race: audit-manifest state changes while waiting
    #      for the lock -> PreconditionRaceDetectedError, zero rows.
    # ============================================================
    case_id8, case_dir8 = make_case()
    canonical8 = canonical_path_for(case_dir8)
    extraction8 = json.loads(canonical8.read_bytes().decode("utf-8"))
    fact_id8 = extraction8["facts"][0]["fact_id"]
    doc8 = extraction8["source_document_id"]
    principal8, repo8 = make_principal_and_repo(case_id8)
    canonical_sha8 = hashlib.sha256(canonical8.read_bytes()).hexdigest()
    conn8 = FakeJournalConn()

    reviews_dir8 = case_dir8 / "documents" / FACT_DOC / "extractions" / "reviews" / "fact_verifications"

    def _race_hook_8(_case_id):
        # Inject a foreign, ALREADY fully-shaped verification audit file
        # into the reviews dir while the lock is being waited for - this
        # changes the audit-manifest digest without touching canonical.
        reviews_dir8.mkdir(parents=True, exist_ok=True)
        (reviews_dir8 / "zzz_injected.verification.json").write_text(
            json.dumps({"injected": True}), encoding="utf-8",
        )

    _on_acquire_hooks.append(_race_hook_8)
    try:
        expect_raises(
            PreconditionRaceDetectedError,
            lambda: apply_verification(
                case_id8, FACT_DOC, fact_id8, canonical_sha8, "verified",
                evidence_document_id=doc8, principal=principal8, repo=repo8, conn=conn8,
            ),
            "F8a audit-manifest change under the lock wait -> PreconditionRaceDetectedError",
        )
    finally:
        _on_acquire_hooks.remove(_race_hook_8)
    check("F8b composite race wrote ZERO journal rows", len(conn8.table) == 0)

    # ============================================================
    # F9 - OUTER authz denial (existence-blind, zero connections) +
    #      analyst can preview but not apply.
    # ============================================================
    case_id9, case_dir9 = make_case()
    extraction9 = json.loads(canonical_path_for(case_dir9).read_bytes().decode("utf-8"))
    fact_id9 = extraction9["facts"][0]["fact_id"]
    principal9, repo9 = make_principal_and_repo(case_id9, assigned=False)
    conn9 = FakeJournalConn()
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: apply_verification(
            case_id9, FACT_DOC, fact_id9, "1" * 64, "unverified", principal=principal9, repo=repo9, conn=conn9,
        ),
        "F9a unassigned actor -> CaseAccessDeniedError (existence-blind)",
    )
    check("F9b outer denial: ZERO journal rows / ZERO SQL calls", len(conn9.table) == 0 and len(conn9.calls) == 0)

    principal9b, repo9b = make_principal_and_repo(case_id9, role="analyst")
    preview9b = fv_facade.preview_verification(
        case_id9, FACT_DOC, fact_id9, principal=principal9b, authz_repository=repo9b,
    )
    check("F9c analyst CAN preview (read capability)", preview9b["from_state"] == "unverified")
    conn9c = FakeJournalConn()
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: apply_verification(
            case_id9, FACT_DOC, fact_id9, "1" * 64, "unverified",
            principal=principal9b, repo=repo9b, conn=conn9c,
        ),
        "F9d analyst apply -> CaseAccessDeniedError (mutate capability missing)",
    )
    check("F9e analyst apply denial: zero journal rows", len(conn9c.table) == 0)

    # ============================================================
    # F10 - unknown fact_id / unknown document.
    # ============================================================
    case_id10, case_dir10 = make_case()
    principal10, repo10 = make_principal_and_repo(case_id10)
    expect_raises(
        fv_facade.FactVerificationFactNotFoundError,
        lambda: fv_facade.preview_verification(
            case_id10, FACT_DOC, "definitely_not_a_real_fact_id",
            principal=principal10, authz_repository=repo10,
        ),
        "F10a preview with unknown fact_id -> FactVerificationFactNotFoundError",
    )
    expect_raises(
        fv_facade.FactVerificationNestedPathContainmentError,
        lambda: fv_facade.preview_verification(
            case_id10, "not_a_real_document_id", "irrelevant",
            principal=principal10, authz_repository=repo10,
        ),
        "F10b preview with unknown document_id -> FactVerificationNestedPathContainmentError",
    )

    # ============================================================
    # F11 - missing-locator defense for a positive target state.
    # ============================================================
    case_id11, case_dir11 = make_case()
    canonical11 = canonical_path_for(case_dir11)
    extraction11 = json.loads(canonical11.read_bytes().decode("utf-8"))
    fact11 = extraction11["facts"][0]
    fact11["source"] = {"page": None, "section": None, "paragraph": None, "text_excerpt": None}
    canonical11.write_text  # noop reference to keep linters quiet about unused import style
    canonical_path_for(case_dir11).write_text(
        json.dumps(extraction11, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    principal11, repo11 = make_principal_and_repo(case_id11)
    canonical_sha11 = hashlib.sha256(canonical_path_for(case_dir11).read_bytes()).hexdigest()
    conn11 = FakeJournalConn()
    expect_raises(
        fv_facade.FactVerificationMissingLocatorError,
        lambda: apply_verification(
            case_id11, FACT_DOC, fact11["fact_id"], canonical_sha11, "verified",
            evidence_document_id=extraction11["source_document_id"],
            principal=principal11, repo=repo11, conn=conn11,
        ),
        "F11a target_state=verified for a locator-less fact -> FactVerificationMissingLocatorError",
    )
    check("F11b missing-locator rejection wrote ZERO journal rows", len(conn11.table) == 0)

    # ============================================================
    # F12 - reconciliation adapter: real completed row post-verifies;
    #       malformed target_ref -> dual-false; pre-state proof.
    # ============================================================
    adapter = fv_adapters.FactVerificationReconciliationAdapter()
    # F1 REMEDIATION fixture correction: the first fixture set
    # `actor_label="iam_user"` (the actor TYPE) - the real journal column
    # holds the actor REF (`str(principal.user_id)`, here "7"), as the
    # fake journal's own INSERT recorded it. The old matcher never bound
    # the actor, so the wrong label went unnoticed; the full-binding
    # adapter now correctly rejects it (see F19/test_reconciliation_isolated
    # for the explicit journal-actor-mismatch tamper). Use the REAL
    # journaled value.
    check("F12-setup the fake journal recorded the actor REF ('7'), not the actor type",
          conn1.table[0]["actor_label"] == "7")
    entry12 = mr.JournalEntrySnapshot(
        journal_id=1, resource_key=f"case:{case_id1}", action_family="verification.fact",
        target_ref=f"fact.{FACT_DOC}.{fact_id1}.verification", target_state="verified",
        pre_hash=conn1.table[0]["pre_hash"], pre_revision=conn1.table[0]["pre_revision"],
        expected_post_hash=None, state="reconciliation_required",
        idempotency_key=conn1.table[0]["idempotency_key"],
        request_fingerprint=conn1.table[0]["request_fingerprint"],
        actor_label=conn1.table[0]["actor_label"],
    )
    ev12 = adapter.gather_evidence(entry12)
    check(
        "F12a adapter post-verifies a REAL completed verification (exactly-one bound audit + "
        "recomputed pre_revision match)",
        ev12.post_state_verified is True and ev12.observed_post_hash == result1.canonical_hash,
    )
    ev12b = adapter.gather_evidence(mr.JournalEntrySnapshot(
        journal_id=2, resource_key=f"case:{case_id1}", action_family="verification.fact",
        target_ref="fact..verification", target_state="verified",
        pre_hash="x" * 64, pre_revision="y" * 64, expected_post_hash=None,
        state="reconciliation_required", idempotency_key="k" * 64,
        request_fingerprint="f" * 64, actor_label="iam_user",
    ))
    check("F12b adapter: malformed target_ref -> dual-false",
          ev12b.post_state_verified is False and ev12b.pre_state_confirmed_unchanged is False)

    # Pre-state proof: a NEVER-EXECUTED journal row whose pre_hash matches
    # the CURRENT (untouched) composite.
    case_id12c, case_dir12c = make_case()
    canonical12c = canonical_path_for(case_dir12c)
    extraction12c = json.loads(canonical12c.read_bytes().decode("utf-8"))
    fact_id12c = extraction12c["facts"][0]["fact_id"]
    canonical_sha12c = hashlib.sha256(canonical12c.read_bytes()).hexdigest()
    empty_manifest_digest = fv_facade._compute_audit_manifest_digest(
        fv_facade._resolve_case_root_real(case_id12c),
        fv_facade._derive_verified_paths(
            fv_facade._resolve_case_root_real(case_id12c), case_id12c, FACT_DOC,
        ).reviews_dir,
    )
    pre_hash12c = fv_facade._compute_pre_hash(canonical_sha12c, empty_manifest_digest)
    entry12c = mr.JournalEntrySnapshot(
        journal_id=3, resource_key=f"case:{case_id12c}", action_family="verification.fact",
        target_ref=f"fact.{FACT_DOC}.{fact_id12c}.verification", target_state="verified",
        pre_hash=pre_hash12c, pre_revision="z" * 64, expected_post_hash=None,
        state="reconciliation_required", idempotency_key="k2" * 32,
        request_fingerprint="f2" * 32, actor_label="iam_user",
    )
    ev12c = adapter.gather_evidence(entry12c)
    check(
        "F12c adapter: never-executed row whose pre_hash matches the untouched composite -> "
        "pre-state confirmed unchanged",
        ev12c.post_state_verified is False and ev12c.pre_state_confirmed_unchanged is True,
    )

    # ============================================================
    # F13 - facade-level argument-shape rules (pre-I/O).
    # ============================================================
    conn13 = FakeJournalConn()
    for label, kwargs in [
        ("F13a invalid target_state -> FactVerificationArgumentError", dict(target_state="bogus")),
        ("F13b blank expected_hash -> FactVerificationArgumentError", dict(target_state="unverified", expected_hash=" ")),
        ("F13c attempt=0 -> FactVerificationArgumentError", dict(target_state="unverified", attempt=0)),
    ]:
        expect_raises(
            fv_facade.FactVerificationArgumentError,
            lambda kw=kwargs: fv_facade.apply_verification_mutation(
                "some_case", FACT_DOC, "some_fact", kw.get("expected_hash", "a" * 64),
                kw["target_state"], attempt=kw.get("attempt", 1),
                principal=_authz.Principal(user_id=1, session_id=1, role_version_at_issue=1),
                authz_repository=_authz.InMemoryAuthzRepository(),
                conn_factory=lambda: (_ for _ in ()).throw(AssertionError("conn_factory must not be called")),
            ),
            label,
        )
    check("F13d argument-shape rejections performed ZERO journal SQL", len(conn13.calls) == 0)

    # ============================================================
    # F14 - stale-downstream block renders the exact literal contract.
    # ============================================================
    block = fv_facade.render_stale_downstream_block()
    check("F14a STALE_DOWNSTREAM block lists all 11 families", "qa case_view" in block and "timeline deadline" in block)
    check("F14b RERUN_ORDER block starts with generation.timeline", "generation.timeline\npromotion.timeline" in block)
    check("F14c NO_COORDINATED_PATH block names qa and case_view", "NO_COORDINATED_PATH:\nqa case_view" in block)

    # ============================================================
    # F15 - DOWNSTREAM STALENESS (Fable FINAL §O #18, real evidence.json
    #       facts_input_hash - the REAL Row 12 evidence_engine/
    #       evidence_validator/evidence_policy modules, no mocking).
    # ============================================================
    case_id15, case_dir15 = make_case()
    canonical15 = canonical_path_for(case_dir15)
    extraction15 = json.loads(canonical15.read_bytes().decode("utf-8"))
    fact_id15 = extraction15["facts"][0]["fact_id"]
    doc15 = extraction15["source_document_id"]
    principal15, repo15 = make_principal_and_repo(case_id15)
    canonical_sha15 = hashlib.sha256(canonical15.read_bytes()).hexdigest()

    # A REAL evidence analysis (Row 12 engine), built from the CURRENT
    # (pre-verification) canonical facts/issues/documents - genuinely
    # valid at the moment it is built.
    real_evidence_analysis15 = _evidence_engine.build_evidence_engine_output(case_id15)["analysis"]
    evidence_dir15 = case_dir15 / "evidence"
    evidence_dir15.mkdir(parents=True, exist_ok=True)
    (evidence_dir15 / "evidence.json").write_text(
        json.dumps(real_evidence_analysis15, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    recorded_facts_hash15 = real_evidence_analysis15["analysis_metadata"]["facts_input_hash"]
    # Captured BEFORE any mutation, for the F15d non-regression sanity
    # check below (once the fact is mutated, the ORIGINAL pre-mutation
    # fact_index can no longer be re-derived from disk).
    pre_mutation_fact_index15 = _timeline_validator.load_canonical_fact_index(case_id15)["facts"]
    pre_mutation_issues15 = _legal_research_validator.load_canonical_issues(case_id15)["issues"]
    pre_mutation_active_docs15 = _evidence_policy.load_active_case_documents_index(case_id15)

    def _fresh_facts_input_hash(case_id):
        fact_context = _timeline_validator.load_canonical_fact_index(case_id)
        return _evidence_policy.sha256_of(
            {fact_id: record["fact"] for fact_id, record in fact_context["facts"].items()}
        )

    check(
        "F15a the REAL evidence engine's OWN recorded facts_input_hash matches a freshly, "
        "independently recomputed hash of the SAME pre-mutation canonical facts (sanity: our "
        "recomputation formula is byte-identical to the engine's own)",
        recorded_facts_hash15 == _fresh_facts_input_hash(case_id15),
    )

    # A REAL verification.fact apply GENUINELY changes the canonical
    # fact content.
    result15, _, _ = apply_verification(
        case_id15, FACT_DOC, fact_id15, canonical_sha15, "verified",
        evidence_document_id=doc15, principal=principal15, repo=repo15,
    )
    fresh_facts_hash15_after = _fresh_facts_input_hash(case_id15)
    check(
        "F15b after a REAL verification.fact apply, the freshly recomputed facts_input_hash "
        "GENUINELY differs from the pre-mutation value (not a fabricated/asserted difference)",
        fresh_facts_hash15_after != recorded_facts_hash15,
        f"before={recorded_facts_hash15!r} after={fresh_facts_hash15_after!r}",
    )

    # The REAL Row 12 validator, given the (now-stale) evidence.json's
    # OWN recorded analysis_metadata against FRESH facts/issues/
    # documents, genuinely reports a STALE INPUT error naming
    # facts_input_hash - never a warning-string check, a real function
    # call against real canonical artefacts.
    fresh_fact_context15 = _timeline_validator.load_canonical_fact_index(case_id15)
    fresh_fact_index15 = fresh_fact_context15["facts"]
    fresh_issues15 = _legal_research_validator.load_canonical_issues(case_id15)["issues"]
    fresh_active_docs15 = _evidence_policy.load_active_case_documents_index(case_id15)
    stale_errors15 = _evidence_validator.validate_analysis_metadata(
        real_evidence_analysis15["analysis_metadata"], fresh_issues15, fresh_fact_index15, fresh_active_docs15,
    )
    check(
        "F15c the REAL evidence_validator.validate_analysis_metadata() genuinely reports a "
        "STALE INPUT error naming 'facts_input_hash' after the real verification.fact mutation",
        any("facts_input_hash" in error and "STALE INPUT" in error for error in stale_errors15),
        f"{stale_errors15!r}",
    )
    check(
        "F15d the SAME validator call against the ORIGINAL (pre-mutation, captured-before-apply) "
        "fact_index/issues/documents reports ZERO staleness errors (the error in F15c is "
        "genuinely caused by the real mutation, not a bug in the fixture/validator call itself)",
        _evidence_validator.validate_analysis_metadata(
            real_evidence_analysis15["analysis_metadata"], pre_mutation_issues15,
            pre_mutation_fact_index15, pre_mutation_active_docs15,
        ) == [],
    )

    # ============================================================
    # F16 - DOWNSTREAM STALENESS (Fable FINAL §O #18, real timeline
    #       validator downgrade-ERROR proof - event_004 has EXACTLY one
    #       source_fact_id, avoiding multi-fact consolidation ambiguity).
    # ============================================================
    case_id16, case_dir16 = make_case()
    canonical16 = canonical_path_for(case_dir16)
    timeline16_path = case_dir16 / "timeline" / "timeline.json"
    timeline16 = json.loads(timeline16_path.read_bytes().decode("utf-8"))
    event16 = next(e for e in timeline16["events"] if e["event_id"] == "timeline_event_004")
    check(
        "F16 setup: timeline_event_004 genuinely has EXACTLY one source_fact_id (no multi-fact "
        "consolidation ambiguity)",
        len(event16["source_fact_ids"]) == 1,
        f"{event16!r}",
    )
    fact_id16 = event16["source_fact_ids"][0]
    extraction16 = json.loads(canonical16.read_bytes().decode("utf-8"))
    fact16 = fv.find_fact(extraction16, fact_id16)
    check("F16 setup: the source fact is genuinely 'unverified' at the start",
          fact16 is not None and fact16.get("verification_state") == "unverified")
    principal16, repo16 = make_principal_and_repo(case_id16)
    canonical_sha16 = hashlib.sha256(canonical16.read_bytes()).hexdigest()

    # UPGRADE the sole source fact to 'verified' via the REAL facade.
    result16a, _, _ = apply_verification(
        case_id16, FACT_DOC, fact_id16, canonical_sha16, "verified",
        evidence_document_id=extraction16["source_document_id"], principal=principal16, repo=repo16,
    )
    verified_fact16 = fv.find_fact(
        json.loads(canonical16.read_bytes().decode("utf-8")), fact_id16,
    )
    # The REAL timeline_engine's own single-fact propagation function -
    # what a genuine timeline regeneration would derive for this event
    # AT THIS MOMENT (not fabricated).
    derived_state_at_verified16 = _timeline_engine.propagate_verification_state(verified_fact16)
    check("F16a real timeline_engine.propagate_verification_state() derives 'verified' for the "
          "now-verified sole source fact", derived_state_at_verified16 == "verified")

    stale_event16 = dict(event16)
    stale_event16["verification_state"] = derived_state_at_verified16

    # DOWNGRADE the SAME fact back to 'unverified' via the REAL facade -
    # the canonical timeline event above is now STALE (still claims
    # 'verified', but its sole source fact genuinely regressed).
    result16b, _, _ = apply_verification(
        case_id16, FACT_DOC, fact_id16, result16a.canonical_hash, "unverified",
        principal=principal16, repo=repo16,
    )
    fresh_fact_index16 = _timeline_validator.load_canonical_fact_index(case_id16)["facts"]
    check(
        "F16b the fresh fact_index genuinely reflects the downgrade (sole source fact is "
        "'unverified' again)",
        fresh_fact_index16[fact_id16]["fact"]["verification_state"] == "unverified",
    )
    downgrade_errors16, downgrade_warnings16 = _timeline_validator.validate_verification_state(
        stale_event16, fresh_fact_index16,
    )
    check(
        "F16c the REAL timeline_validator.validate_verification_state() genuinely reports an "
        "ERROR for the stale ('verified') event against its now-downgraded ('unverified') sole "
        "source fact - 'event kaynaktan güçlü olamaz' rule, never a warning-string check",
        len(downgrade_errors16) == 1 and "kaynak fact" in downgrade_errors16[0],
        f"errors={downgrade_errors16!r} warnings={downgrade_warnings16!r}",
    )
    # Sanity: the SAME check against the ORIGINAL (non-stale, honestly
    # 'unverified') event dict reports NO such error.
    honest_errors16, _ = _timeline_validator.validate_verification_state(event16, fresh_fact_index16)
    check(
        "F16d the SAME real validator call against the HONEST (non-stale) original event dict "
        "reports ZERO verification-rank errors (F16c's error is genuinely caused by staleness, "
        "not a bug in the fixture)",
        honest_errors16 == [],
        f"{honest_errors16!r}",
    )

    # ============================================================
    # F17 - explicit self-transition / safe-replay contract proofs
    #       (Fable FINAL continuation instruction, four bullets).
    # ============================================================
    case_id17b, case_dir17b = make_case()
    canonical17b = canonical_path_for(case_dir17b)
    extraction17b = json.loads(canonical17b.read_bytes().decode("utf-8"))
    fact_id17b = extraction17b["facts"][0]["fact_id"]
    doc17b = extraction17b["source_document_id"]
    principal17b, repo17b = make_principal_and_repo(case_id17b)
    canonical_sha17b = hashlib.sha256(canonical17b.read_bytes()).hexdigest()

    # Bullet 1: genuine completed-request replay -> stored result,
    # writer call count 0 (already exhaustively proven as F7a/b/c above -
    # referenced here again with an explicit writer call-count spy for
    # this exact bullet's own, standalone evidence).
    _spy_calls17 = {"n": 0}
    _orig_apply_verification17 = fv.apply_verification

    def _counting_apply_verification(*args, **kwargs):
        _spy_calls17["n"] += 1
        return _orig_apply_verification17(*args, **kwargs)

    fv.apply_verification = _counting_apply_verification
    try:
        result17b1, conn17b, _ = apply_verification(
            case_id17b, FACT_DOC, fact_id17b, canonical_sha17b, "verified",
            evidence_document_id=doc17b, principal=principal17b, repo=repo17b,
        )
        check("F17-bullet1 first apply genuinely invoked the writer once", _spy_calls17["n"] == 1)
        result17b2, _, _ = apply_verification(
            case_id17b, FACT_DOC, fact_id17b, canonical_sha17b, "verified",
            evidence_document_id=doc17b, principal=principal17b, repo=repo17b, conn=conn17b,
        )
        check(
            "F17-bullet1 genuine replay of a completed request returns the SAME stored result "
            "(replayed=True) and the writer call count stayed at 1 (0 NEW invocations)",
            result17b2.replayed is True and _spy_calls17["n"] == 1
            and result17b2.canonical_hash == result17b1.canonical_hash,
        )
    finally:
        fv.apply_verification = _orig_apply_verification17

    # Bullet 2: same canonical state (unverified), but NO matching
    # completed identity exists (fresh case, never touched before) ->
    # FactVerificationNoOpError (not a replay - genuinely a first-ever,
    # no-op request).
    case_id17c, case_dir17c = make_case()
    canonical17c = canonical_path_for(case_dir17c)
    extraction17c = json.loads(canonical17c.read_bytes().decode("utf-8"))
    fact_id17c = extraction17c["facts"][0]["fact_id"]
    principal17c, repo17c = make_principal_and_repo(case_id17c)
    canonical_sha17c = hashlib.sha256(canonical17c.read_bytes()).hexdigest()
    conn17c = FakeJournalConn()
    expect_raises(
        fv_facade.FactVerificationNoOpError,
        lambda: apply_verification(
            case_id17c, FACT_DOC, fact_id17c, canonical_sha17c, "unverified",
            principal=principal17c, repo=repo17c, conn=conn17c,
        ),
        "F17-bullet2 same canonical state (unverified), NO prior completed identity for this "
        "case (fresh, never touched) -> FactVerificationNoOpError (genuinely NOT a replay)",
    )
    check("F17-bullet2 wrote ZERO journal rows", len(conn17c.table) == 0)

    # Bullet 3: conflicting evidence/target + SAME attempt -> unconditional,
    # non-fixture-dependent IdempotencyConflictError (same H, same
    # attempt, DIFFERENT target_state - guaranteed fingerprint mismatch,
    # unlike F7d/F7e above which depend on the fixture fact having a
    # second related_document_id).
    conn17d = FakeJournalConn()
    result17d1, _, _ = apply_verification(
        case_id17c, FACT_DOC, fact_id17c, canonical_sha17c, "verified",
        evidence_document_id=extraction17c["source_document_id"],
        principal=principal17c, repo=repo17c, conn=conn17d,
    )
    expect_raises(
        mc.IdempotencyConflictError,
        lambda: apply_verification(
            case_id17c, FACT_DOC, fact_id17c, canonical_sha17c, "partially_verified",
            evidence_document_id=extraction17c["source_document_id"],
            principal=principal17c, repo=repo17c, conn=conn17d,
        ),
        "F17-bullet3 SAME identity (same H, same attempt=1), DIFFERENT target_state -> "
        "IdempotencyConflictError, UNCONDITIONALLY reproducible (guaranteed fingerprint mismatch)",
    )
    check("F17-bullet3 conflict created NO new journal row", len(conn17d.table) == 1)

    # Bullet 4: attempt N+1 does NOT bypass staleness - a genuinely
    # stale (superseded) expected_hash is STILL rejected even with a
    # bumped --attempt.
    expect_raises(
        StaleViewError,
        lambda: apply_verification(
            case_id17c, FACT_DOC, fact_id17c, canonical_sha17c, "verified",
            evidence_document_id=extraction17c["source_document_id"], attempt=2,
            principal=principal17c, repo=repo17c, conn=conn17d,
        ),
        "F17-bullet4 --attempt 2 with a STALE (already-superseded) expected_hash still raises "
        "StaleViewError - attempt does NOT bypass the staleness check, only opens a new identity "
        "slot for a genuinely still-valid H",
    )
    check("F17-bullet4 the stale-hash-with-bumped-attempt rejection wrote NO new journal row",
          len(conn17d.table) == 1)

    # ============================================================
    # F19 - F1/F2 REMEDIATION (independent review, two Medium findings):
    #       completed-replay corroboration FULL BINDING tamper matrix
    #       (F1) + genuine replay / state-cycle / identity-conflict
    #       classification (F2) through the facade's REAL apply() with
    #       the FakeJournalConn and the REAL writer. Every tamper below
    #       was ACCEPTED as a silent safe replay by the first
    #       implementation.
    # ============================================================
    case_id19, case_dir19 = make_case()
    canonical19 = canonical_path_for(case_dir19)
    extraction19 = json.loads(canonical19.read_bytes().decode("utf-8"))
    fact19 = next(
        f for f in extraction19["facts"] if any(d != FACT_DOC for d in (f.get("related_document_ids") or []))
    )
    fact_id19 = fact19["fact_id"]
    related19 = next(d for d in fact19["related_document_ids"] if d != FACT_DOC)
    principal19, repo19 = make_principal_and_repo(case_id19)

    def _sha19():
        return hashlib.sha256(canonical19.read_bytes()).hexdigest()

    sha19_0 = _sha19()
    result19, conn19, _ = apply_verification(
        case_id19, FACT_DOC, fact_id19, sha19_0, "verified",
        evidence_document_id=FACT_DOC, principal=principal19, repo=repo19,
    )
    sha19_1 = _sha19()
    audit19 = Path(result19.audit_path)
    audit19_bytes = audit19.read_bytes()
    reviews19 = audit19.parent

    def _audits19():
        return sorted(reviews19.glob("*.verification.json"))

    def replay19(**overrides):
        kwargs = dict(evidence_document_id=FACT_DOC, principal=principal19, repo=repo19, conn=conn19)
        kwargs.update(overrides)
        return apply_verification(case_id19, FACT_DOC, fact_id19, sha19_0, "verified", **kwargs)

    r19a, _, _ = replay19()
    check(
        "F19a POSITIVE control: untampered completed row -> genuine replay (replayed=True, "
        "stored hash, from_state from the bound audit) - the matcher does NOT reject unconditionally",
        r19a.replayed is True and r19a.canonical_hash == sha19_1 and r19a.from_state == "unverified",
    )

    def tamper19(label, mutate):
        record = json.loads(audit19_bytes.decode("utf-8"))
        mutate(record)
        audit19.write_bytes(fv.canonical_json_bytes(record))
        try:
            expect_raises(
                fv_facade.FactVerificationAuditBindingVerificationFailedError,
                lambda: replay19(),
                f"F19b replay TAMPER {label} -> FactVerificationAuditBindingVerificationFailedError "
                "(never a silent safe replay, never classified as a state-cycle)",
            )
        finally:
            audit19.write_bytes(audit19_bytes)

    tamper19("mutation_actor_ref", lambda r: r.__setitem__("mutation_actor_ref", "999"))
    tamper19("target_state", lambda r: r.__setitem__("target_state", "partially_verified"))
    tamper19("from_state", lambda r: r.__setitem__("from_state", "verified"))
    tamper19("evidence_document_id", lambda r: r.__setitem__("evidence_document_id", related19))
    tamper19("secondary_input_hash", lambda r: r.__setitem__("secondary_input_hash", "0" * 64))
    tamper19("attempt (top-level)", lambda r: r.__setitem__("attempt", 5))
    tamper19("identity_payload.attempt", lambda r: r["identity_payload"].__setitem__("attempt", 2))
    tamper19("identity_payload.canonical_sha256", lambda r: r["identity_payload"].__setitem__("canonical_sha256", "0" * 64))
    tamper19("document_id", lambda r: r.__setitem__("document_id", related19))
    tamper19("fact_id", lambda r: r.__setitem__("fact_id", "fact_zzz"))
    tamper19("mutation_resource_key", lambda r: r.__setitem__("mutation_resource_key", "case:other"))
    tamper19("target_ref", lambda r: r.__setitem__("target_ref", f"fact.{FACT_DOC}.fact_zzz.verification"))
    tamper19("history_backup_path absolute escape", lambda r: r.__setitem__("history_backup_path", r"C:\Windows\win.ini"))
    tamper19("history_backup_path traversal", lambda r: r.__setitem__("history_backup_path", "..\\..\\facts.json"))
    tamper19("history_backup_sha256", lambda r: r.__setitem__("history_backup_sha256", "0" * 64))
    tamper19("canonical_sha256_before", lambda r: r.__setitem__("canonical_sha256_before", "0" * 64))
    tamper19("canonical_sha256 (after)", lambda r: r.__setitem__("canonical_sha256", "0" * 64))
    tamper19("outcome", lambda r: r.__setitem__("outcome", "x"))
    backup19 = Path(json.loads(audit19_bytes.decode("utf-8"))["history_backup_path"])
    backup19_bytes = backup19.read_bytes()
    backup19.unlink()
    try:
        expect_raises(
            fv_facade.FactVerificationAuditBindingVerificationFailedError, lambda: replay19(),
            "F19b replay TAMPER history backup FILE deleted -> AuditBindingVerificationFailedError",
        )
    finally:
        backup19.write_bytes(backup19_bytes)
    backup_doc19 = json.loads(backup19_bytes.decode("utf-8"))
    fv.find_fact(backup_doc19, fact_id19)["verification_state"] = "partially_verified"
    backup19.write_bytes(fv.canonical_json_bytes(backup_doc19))
    try:
        expect_raises(
            fv_facade.FactVerificationAuditBindingVerificationFailedError, lambda: replay19(),
            "F19b replay TAMPER history backup CONTENT (from_state no longer carried) -> "
            "AuditBindingVerificationFailedError",
        )
    finally:
        backup19.write_bytes(backup19_bytes)
    dup19 = audit19.with_name("zz_dup_" + audit19.name)
    shutil.copy2(audit19, dup19)
    try:
        expect_raises(
            fv_facade.FactVerificationAuditBindingVerificationFailedError, lambda: replay19(),
            "F19b replay DUPLICATE otherwise-valid audit -> AuditBindingVerificationFailedError (exactly-one)",
        )
    finally:
        dup19.unlink()
    corrupt19 = reviews19 / "zz_corrupt.verification.json"
    corrupt19.write_bytes(b"{not json")
    try:
        expect_raises(
            fv_facade.FactVerificationAuditBindingVerificationFailedError, lambda: replay19(),
            "F19b replay CORRUPT sibling audit -> AuditBindingVerificationFailedError",
        )
    finally:
        corrupt19.unlink()
    check(
        "F19c tamper probes: journal still ONE row, still ONE audit, canonical byte-unchanged "
        "(writer never re-invoked, zero new journal/audit/history)",
        len(conn19.table) == 1 and len(_audits19()) == 1 and _sha19() == sha19_1,
    )
    check("F19d after restoring the audit the genuine replay works again", replay19()[0].replayed is True)

    # ---- F2: state cycle back to the byte-identical pre-state ----
    apply_verification(
        case_id19, FACT_DOC, fact_id19, sha19_1, "unverified", principal=principal19, repo=repo19, conn=conn19,
    )
    check("F19e downgrade (new identity) restored the ORIGINAL bytes -> content-hash identity collision is live",
          _sha19() == sha19_0 and len(conn19.table) == 2)
    err19f = expect_raises(
        fv_facade.FactVerificationRevisionCycleConflictError, lambda: replay19(),
        "F19f identical transition after the cycle (same attempt) -> FactVerificationRevisionCycleConflictError "
        "(NOT the generic audit-binding/reconciliation error)",
    )
    check(
        "F19f the cycle message is fixed, names --attempt N+1, carries no path/evidence content",
        err19f is not None and "--attempt N+1" in str(err19f) and str(case_dir19) not in str(err19f)
        and "reconciliation" not in str(err19f).lower(),
    )
    check("F19g cycle rejection: zero new journal rows / audits, canonical unchanged",
          len(conn19.table) == 2 and len(_audits19()) == 2 and _sha19() == sha19_0)
    err19h = expect_raises(
        fv_facade.FactVerificationIdentityConflictError,
        lambda: replay19(evidence_document_id=related19),
        "F19h different EVIDENCE after the cycle (same attempt) -> FactVerificationIdentityConflictError",
    )
    err19i = expect_raises(
        fv_facade.FactVerificationIdentityConflictError,
        lambda: apply_verification(
            case_id19, FACT_DOC, fact_id19, sha19_0, "partially_verified",
            evidence_document_id=FACT_DOC, principal=principal19, repo=repo19, conn=conn19,
        ),
        "F19i different TARGET after the cycle (same attempt) -> FactVerificationIdentityConflictError",
    )
    check(
        "F19j identity-conflict errors are STILL IdempotencyConflictError subclasses (generic refusal "
        "preserved) and carry the actionable --attempt N+1 guidance",
        all(isinstance(e, mc.IdempotencyConflictError) and "--attempt N+1" in str(e) for e in (err19h, err19i)),
    )
    check("F19k conflict rejections: zero new journal rows", len(conn19.table) == 2)
    # tampered OLD audit on a cycle must NOT be classified as a cycle
    record19 = json.loads(audit19_bytes.decode("utf-8"))
    record19["mutation_actor_ref"] = "999"
    audit19.write_bytes(fv.canonical_json_bytes(record19))
    try:
        expect_raises(
            fv_facade.FactVerificationAuditBindingVerificationFailedError, lambda: replay19(),
            "F19l tampered old audit on a cycle -> AuditBindingVerificationFailedError, NEVER a cycle",
        )
    finally:
        audit19.write_bytes(audit19_bytes)
    # attempt N+1 escape
    r19m, _, _ = replay19(attempt=2)
    check(
        "F19m --attempt 2 opens a NEW identity: genuine mutation completed (replayed=False), 3 rows, "
        "3 audits, fact verified, new pre_revision differs from the attempt=1 row",
        r19m.replayed is False and len(conn19.table) == 3 and len(_audits19()) == 3
        and fv.find_fact(json.loads(canonical19.read_bytes().decode("utf-8")), fact_id19)["verification_state"] == "verified"
        and conn19.table[2]["pre_revision"] != conn19.table[0]["pre_revision"]
        and conn19.table[2]["idempotency_key"] != conn19.table[0]["idempotency_key"],
    )
    check("F19n immediate genuine replay of the attempt=2 request -> stored result, no new row",
          replay19(attempt=2)[0].replayed is True and len(conn19.table) == 3)
    expect_raises(
        StaleViewError,
        lambda: apply_verification(
            case_id19, FACT_DOC, fact_id19, "0" * 64, "verified",
            evidence_document_id=FACT_DOC, attempt=3, principal=principal19, repo=repo19, conn=conn19,
        ),
        "F19o stale expected hash + bumped attempt -> STILL StaleViewError (attempt never bypasses staleness)",
    )
    expect_raises(
        fv_facade.FactVerificationNoOpError,
        lambda: apply_verification(
            case_id19, FACT_DOC, fact_id19, _sha19(), "verified",
            evidence_document_id=FACT_DOC, attempt=3, principal=principal19, repo=repo19, conn=conn19,
        ),
        "F19p --attempt 3 with the CURRENT hash on an ALREADY verified fact -> NoOp (attempt never "
        "bypasses the state rules)",
    )
    check("F19q attempt probes: still 3 rows", len(conn19.table) == 3)

    # ============================================================
    # F18 - WINDOWS JUNCTION / PATH-ESCAPE MATRIX (Fable FINAL
    #       continuation instruction #5), through the facade's REAL
    #       PUBLIC preview()/apply() entry points only.
    # ============================================================
    if _IS_WINDOWS:
        outside_root18 = Path(tempfile.mkdtemp(prefix="vergi_fv_outside_"))
        canary18 = outside_root18 / "canary.json"
        canary18.write_text('{"canary": "untouched"}', encoding="utf-8")
        canary18_sha = hashlib.sha256(canary18.read_bytes()).hexdigest()
        _junction_links18 = []
        _empty_escape_targets18 = []

        # F18j proof-of-non-access: a repo-external sys.addaudithook that
        # records any open()/os.scandir()/os.listdir() whose target path
        # lies under outside_root18, ARMED ONLY around the facade's own
        # preview()/apply() call windows (never around test setup, which
        # legitimately copies/reads/writes under outside_root18 while
        # building each scenario's escape target). This proves containment
        # rejects BEFORE the external target is ever opened - not merely
        # before it is written to (byte-unchanged canary/empty-dir checks
        # alone only prove the latter).
        _f18_opens = []
        _f18_armed = [False]
        _outside_root18_str = str(outside_root18)

        def _f18_audit_hook(event, args):
            if not _f18_armed[0]:
                return
            if event not in ("open", "os.scandir", "os.listdir"):
                return
            try:
                p = str(args[0])
            except (IndexError, TypeError, ValueError):
                return
            if p.startswith(_outside_root18_str):
                _f18_opens.append((event, p))

        sys.addaudithook(_f18_audit_hook)

        # Positive control FIRST: prove the hook genuinely fires on a real
        # open() under outside_root18, so a later "zero events" result is
        # meaningful rather than a silently-broken/never-armed hook.
        _f18_armed[0] = True
        _ = canary18.read_bytes()
        _f18_armed[0] = False
        check(
            "F18-positive-control the audit hook genuinely fires on a real open() "
            "under outside_root18 (proves a later zero-events result is meaningful)",
            len(_f18_opens) >= 1 and all(e[1].startswith(_outside_root18_str) for e in _f18_opens),
            f"{_f18_opens!r}",
        )
        _f18_opens.clear()

        def make_junction18(link_path, target_path):
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                raise RuntimeError(f"mklink /J failed rc={result.returncode}: {result.stdout!r} {result.stderr!r}")
            _junction_links18.append(link_path)

        def escape_preview_and_apply(label, case_id, document_id, fact_id, expected_hash, *,
                                      evidence_document_id=None, expect_exc=fv_facade.FactVerificationNestedPathContainmentError):
            principal_e, repo_e = make_principal_and_repo(case_id)
            conn_e = FakeJournalConn()
            _f18_armed[0] = True
            try:
                expect_raises(
                    expect_exc,
                    lambda: fv_facade.preview_verification(
                        case_id, document_id, fact_id, principal=principal_e, authz_repository=repo_e,
                    ),
                    f"{label} [preview]",
                )
                expect_raises(
                    expect_exc,
                    lambda: apply_verification(
                        case_id, document_id, fact_id, expected_hash, "unverified",
                        evidence_document_id=evidence_document_id,
                        principal=principal_e, repo=repo_e, conn=conn_e,
                    ),
                    f"{label} [apply]",
                )
            finally:
                _f18_armed[0] = False
            check(f"{label} [zero open/scandir/listdir under outside_root18]", _f18_opens == [],
                  f"{_f18_opens!r}")
            _f18_opens.clear()
            check(f"{label} [zero journal rows]", len(conn_e.table) == 0, f"{conn_e.table!r}")

        try:
            # (a) document directory junction escape.
            case_id18a, case_dir18a = make_case()
            doc_dir18a = case_dir18a / "documents" / FACT_DOC
            target18a = outside_root18 / f"doc_{uuid.uuid4().hex[:6]}"
            shutil.copytree(doc_dir18a, target18a)
            shutil.rmtree(doc_dir18a)
            make_junction18(doc_dir18a, target18a)
            escape_preview_and_apply(
                "F18a document-dir LIVE junction escape refused", case_id18a, FACT_DOC,
                "irrelevant_fact_id", "1" * 64,
            )

            # (b) extractions directory junction escape.
            case_id18b, case_dir18b = make_case()
            ext_dir18b = case_dir18b / "documents" / FACT_DOC / "extractions"
            target18b = outside_root18 / f"ext_{uuid.uuid4().hex[:6]}"
            shutil.copytree(ext_dir18b, target18b)
            shutil.rmtree(ext_dir18b)
            make_junction18(ext_dir18b, target18b)
            escape_preview_and_apply(
                "F18b extractions-dir LIVE junction escape refused (canonical facts.json "
                "outside-root redirection)", case_id18b, FACT_DOC, "irrelevant_fact_id", "1" * 64,
            )

            # (c) history directory junction escape (empty outside target -
            # stays empty <=> writer never wrote through it).
            case_id18c, case_dir18c = make_case()
            history_dir18c = case_dir18c / "documents" / FACT_DOC / "extractions" / "history"
            target18c = outside_root18 / f"hist_{uuid.uuid4().hex[:6]}"
            target18c.mkdir()
            _empty_escape_targets18.append(target18c)
            if history_dir18c.is_dir():
                shutil.rmtree(history_dir18c)
            make_junction18(history_dir18c, target18c)
            canonical18c = canonical_path_for(case_dir18c)
            sha18c = hashlib.sha256(canonical18c.read_bytes()).hexdigest()
            extraction18c = json.loads(canonical18c.read_bytes().decode("utf-8"))
            escape_preview_and_apply(
                "F18c history-dir LIVE junction escape refused", case_id18c, FACT_DOC,
                extraction18c["facts"][0]["fact_id"], sha18c,
            )

            # (d) reviews (fact_verifications) directory junction escape.
            case_id18d, case_dir18d = make_case()
            reviews_dir18d = case_dir18d / "documents" / FACT_DOC / "extractions" / "reviews"
            target18d = outside_root18 / f"rev_{uuid.uuid4().hex[:6]}"
            target18d.mkdir()
            _empty_escape_targets18.append(target18d)
            if reviews_dir18d.is_dir():
                shutil.rmtree(reviews_dir18d)
            make_junction18(reviews_dir18d, target18d)
            canonical18d = canonical_path_for(case_dir18d)
            sha18d = hashlib.sha256(canonical18d.read_bytes()).hexdigest()
            extraction18d = json.loads(canonical18d.read_bytes().decode("utf-8"))
            escape_preview_and_apply(
                "F18d reviews-dir LIVE junction escape refused", case_id18d, FACT_DOC,
                extraction18d["facts"][0]["fact_id"], sha18d,
            )

            # (e) evidence document directory junction escape - the
            # EVIDENCE document (not the target fact's own document) is
            # the one escaping.
            case_id18e, case_dir18e = make_case()
            canonical18e = canonical_path_for(case_dir18e)
            extraction18e = json.loads(canonical18e.read_bytes().decode("utf-8"))
            fact_id18e = extraction18e["facts"][0]["fact_id"]
            evidence_doc18e = extraction18e["source_document_id"]
            evidence_doc_dir18e = case_dir18e / "documents" / evidence_doc18e
            target18e = outside_root18 / f"evdoc_{uuid.uuid4().hex[:6]}"
            shutil.copytree(evidence_doc_dir18e, target18e)
            shutil.rmtree(evidence_doc_dir18e)
            make_junction18(evidence_doc_dir18e, target18e)
            sha18e = hashlib.sha256(canonical18e.read_bytes()).hexdigest()
            principal18e, repo18e = make_principal_and_repo(case_id18e)
            conn18e = FakeJournalConn()
            _f18_armed[0] = True
            try:
                expect_raises(
                    fv_facade.FactVerificationNestedPathContainmentError,
                    lambda: apply_verification(
                        case_id18e, FACT_DOC, fact_id18e, sha18e, "verified",
                        evidence_document_id=evidence_doc18e,
                        principal=principal18e, repo=repo18e, conn=conn18e,
                    ),
                    "F18e evidence-document-dir LIVE junction escape refused (evidence-ref target, "
                    "not the fact's own document)",
                )
            finally:
                _f18_armed[0] = False
            check("F18e [zero open/scandir/listdir under outside_root18]", _f18_opens == [],
                  f"{_f18_opens!r}")
            _f18_opens.clear()
            check("F18e [zero journal rows]", len(conn18e.table) == 0)

            # (f) traversal ('..') in document_id.
            case_id18f, _ = make_case()
            escape_preview_and_apply(
                "F18f traversal ('..') document_id refused", case_id18f, "..\\..\\windows",
                "irrelevant", "1" * 64,
            )

            # (g) absolute, drive-qualified path shape as document_id.
            case_id18g, _ = make_case()
            escape_preview_and_apply(
                "F18g absolute drive-qualified document_id refused", case_id18g,
                "C:\\Windows\\System32", "irrelevant", "1" * 64,
            )

            # (h) UNC-style document_id.
            case_id18h, _ = make_case()
            escape_preview_and_apply(
                "F18h UNC-style document_id refused", case_id18h, r"\\evil-server\share",
                "irrelevant", "1" * 64,
            )

            # canary / outside-tree invariance for every refusal above.
            check(
                "F18i outside canary byte-unchanged AND all empty escape targets stayed empty "
                "(nothing was ever read from or written through an escaping link)",
                hashlib.sha256(canary18.read_bytes()).hexdigest() == canary18_sha
                and all(list(t.iterdir()) == [] for t in _empty_escape_targets18 if t.exists()),
            )
        finally:
            for link in _junction_links18:
                try:
                    if os.path.lexists(link):
                        os.rmdir(link)
                except OSError as cleanup_error:
                    print(f"CLEANUP WARNING: link {link}: {cleanup_error!r}")
            shutil.rmtree(outside_root18, ignore_errors=True)
    else:
        def _skip_info18(label, detail=""):
            print(f"SKIPPED (NOT counted as pass/fail) {label} - {detail}")

        _skip_info18(
            "F18a-i Windows NTFS junction escape matrix", "sys.platform != 'win32' - real "
            "privilege/junction-creation limitation, not a fabricated green skip. The underlying "
            "path_containment.py primitives ARE exhaustively tested (including real POSIX "
            "symlink/ELOOP escapes) elsewhere in this repository's test suite "
            "(test_path_containment_isolated.py, test_path_containment_module_isolated.py) - this "
            "is a coverage GAP specific to THIS facade's own call sites on non-Windows platforms, "
            "disclosed here rather than hidden.",
        )

finally:
    ml.acquire_case_lock_session = _original_acquire
    ml.release_lock_session = _original_release

    for case_dir in _created_case_dirs:
        try:
            if case_dir.exists():
                shutil.rmtree(case_dir)
        except OSError as cleanup_error:
            print(f"CLEANUP WARNING: case dir {case_dir}: {cleanup_error!r}")

_data_tree_after_everything = snapshot_data_tree()
check(
    "FINAL: the real data/ tree is byte-for-byte IDENTICAL to the pre-test snapshot "
    "(all synthetic cases fully removed, no residue anywhere)",
    _data_tree_after_everything == _data_tree_before_everything,
    f"diff keys: {sorted(set(_data_tree_after_everything) ^ set(_data_tree_before_everything))[:20]!r}",
)

print(
    f"--- test_fact_verification_mutation_facade_isolated: {passed} passed, {failed} failed ---"
)
sys.exit(1 if failed else 0)
