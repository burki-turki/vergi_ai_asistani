# ============================================================
# ROW 19C-3b SLICE 2 - isolated tests for
# ui/services/promotion_mutation_facade.py AND
# ui/services/promotion_mutation_adapters.py (fake journal conn, fake
# locks, in-memory authz, REAL fact_approval/timeline_approval writer
# modules against REAL, re-identified synthetic copies of case_0001
# created under the real `data/cases/` tree and fully removed at the
# end - the ENTIRE real data/ tree is snapshot-compared before/after).
#
# Windows escape scenarios use REAL `mklink /J` NTFS junctions (never
# monkeypatch); POSIX symlink/ELOOP sub-tests are platform-gated and a
# skip is NEVER counted as a pass (informational SKIPPED lines only).
#
# Run: python ui/tests/test_promotion_mutation_facade_isolated.py
# ============================================================

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ui.services import authz as _authz                                  # noqa: E402
from ui.services import mutation_coordinator as mc                        # noqa: E402
from ui.services import mutation_lock as ml                               # noqa: E402
from ui.services import mutation_registry as mr                           # noqa: E402
from ui.services import paths as _paths                                   # noqa: E402
from ui.services import promotion_mutation_adapters as promo_adapters     # noqa: E402
from ui.services import promotion_mutation_facade as promo                # noqa: E402
from ui.services.common import PendingNotFoundError, StaleViewError, PreconditionRaceDetectedError, sha256_file  # noqa: E402

import fact_approval                                                       # noqa: E402
import timeline_approval                                                   # noqa: E402

passed = 0
failed = 0
_informational_skips = 0

_IS_WINDOWS = sys.platform == "win32"


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def skip_info(label, detail=""):
    """Informational only - NEVER counted as pass or fail."""
    global _informational_skips
    _informational_skips += 1
    print(f"SKIPPED (NOT counted as pass/fail) {label} - {detail}")


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


# ----------------------------------------------------------------
# Full real data/ tree snapshot (byte-level) - taken BEFORE any fixture
# is created and again AFTER full cleanup; must be identical.
# ----------------------------------------------------------------

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
# Fake mutation.mutation_journal (exact SQL shapes run_mutation() uses -
# same fake ui/tests/test_mutation_approval_facade_isolated.py proved
# against the real coordinator), with an optional break_completed knob.
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


# ----------------------------------------------------------------
# Fake session locks with an injectable on-acquire hook (runs BETWEEN
# the facade's pre-lock derivation and run_mutation()'s under-lock
# work - the exact window a link swap / IAM revocation would occupy).
# ----------------------------------------------------------------

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


# ----------------------------------------------------------------
# Synthetic, re-identified copies of the REAL case_0001 tree.
# ----------------------------------------------------------------

_created_case_dirs = []
_junction_links = []          # removed FIRST (link before target)
_outside_dirs = []            # junction targets outside data/


def make_junction(link_path: Path, target_path: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mklink /J failed rc={result.returncode}: {result.stdout!r} {result.stderr!r}")
    _junction_links.append(link_path)


def make_promotion_case():
    """Copies data/cases/case_0001 to a fresh synthetic case id under
    the REAL data/cases tree (the same location authz's resolve_case_id
    and the writer modules' own CASES_DIR both point at in production),
    rewriting every textual 'case_0001' occurrence (case_id fields AND
    embedded ids like timeline_case_0001_v1_1) to the new id."""
    case_id = f"promoiso{uuid.uuid4().hex[:10]}"
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


FACT_DOC = "dava_dilekcesi_001"


def fact_paths_for(case_dir):
    ext = case_dir / "documents" / FACT_DOC / "extractions"
    return {
        "extractions": ext,
        "pending": ext / fact_approval.CURRENT_PENDING_FILENAME,
        "canonical": ext / "facts.json",
        "history": ext / "history",
        "reviews": ext / "reviews",
    }


def timeline_paths_for(case_dir):
    tl = case_dir / "timeline"
    return {
        "timeline": tl,
        "pending": tl / timeline_approval.CURRENT_PENDING_FILENAME,
        "canonical": tl / "timeline.json",
        "history": tl / "history",
        "reviews": tl / "reviews",
    }


def approve(row_key, case_id, expected_hash, *, document_id=None, note=None,
            principal, repo, conn=None):
    conn = conn if conn is not None else FakeJournalConn()
    calls = {"n": 0}

    def conn_factory():
        calls["n"] += 1
        return conn

    result = promo.approve_promotion_mutation(
        row_key, case_id, expected_hash,
        document_id=document_id, note=note,
        principal=principal, authz_repository=repo, conn_factory=conn_factory,
    )
    return result, conn, calls


# ================================================================
# Monkeypatch the locks for the whole run.
# ================================================================

ml.acquire_case_lock_session = _fake_acquire
ml.release_lock_session = _fake_release

try:
    # ============================================================
    # S0 - serializer single-source / byte-equivalence / purity +
    #      facade<->adapters snapshot drift canary.
    # ============================================================
    _payload = {"b": "çok satırlı\ndeğer", "a": [1, {"iç": "ünïcode"}]}
    import tempfile
    with tempfile.TemporaryDirectory() as _td:
        _legacy_out = Path(_td) / "legacy.json"
        # The EXACT legacy writer shape: text-mode json.dump.
        with open(_legacy_out, "w", encoding="utf-8") as f:
            json.dump(_payload, f, ensure_ascii=False, indent=2)
        legacy_bytes = _legacy_out.read_bytes()
    check(
        "S0a fact _canonical_json_bytes == legacy text-mode json.dump bytes (golden byte-equivalence)",
        fact_approval._canonical_json_bytes(_payload) == legacy_bytes,
    )
    check(
        "S0b timeline _canonical_json_bytes == legacy text-mode json.dump bytes",
        timeline_approval._canonical_json_bytes(_payload) == legacy_bytes,
    )
    check(
        "S0c serializer determinism: two calls byte-identical",
        fact_approval._canonical_json_bytes(_payload) == fact_approval._canonical_json_bytes(_payload),
    )

    case_id0, case_dir0 = make_promotion_case()
    fp0 = fact_paths_for(case_dir0)
    _before = snapshot_data_tree()
    _exp_1 = fact_approval.compute_expected_canonical_sha256(fp0["pending"])
    _exp_2 = fact_approval.compute_expected_canonical_sha256(fp0["pending"])
    _exp_t = timeline_approval.compute_expected_canonical_sha256(timeline_paths_for(case_dir0)["pending"])
    check("S0d compute_expected_canonical_sha256 deterministic (fact)", _exp_1 == _exp_2)
    check("S0e compute_expected_canonical_sha256 returns a sha256 hex digest (timeline)",
          isinstance(_exp_t, str) and len(_exp_t) == 64)
    check(
        "S0f compute_expected_canonical_sha256 writes NOTHING (full data/ tree byte-identical)",
        snapshot_data_tree() == _before,
    )
    check(
        "S0g facade snapshot composite == adapters' independent recomputation (drift canary)",
        promo._compute_promotion_snapshot(fp0["pending"], fp0["canonical"]).composite_digest
        == promo_adapters._compute_promotion_composite(fp0["pending"], fp0["canonical"]),
    )

    # ============================================================
    # S1 - fact fresh promotion, OVERWRITE variant (canonical exists).
    # ============================================================
    case_id1, case_dir1 = make_promotion_case()
    fp1 = fact_paths_for(case_dir1)
    principal1, repo1 = make_principal_and_repo(case_id1)
    pending_sha1 = sha256_file(fp1["pending"])
    expected_canonical1 = fact_approval.compute_expected_canonical_sha256(fp1["pending"])
    legacy_audits_before = {
        p.name: sha256_file(p) for p in fp1["reviews"].glob("*.approval.json")
    }
    history_before = set(p.name for p in fp1["history"].glob("*")) if fp1["history"].is_dir() else set()

    result1, conn1, calls1 = approve(
        "fact", case_id1, pending_sha1, document_id=FACT_DOC, principal=principal1, repo=repo1,
    )
    check("S1a fresh fact promotion returns replayed=False", result1.replayed is False)
    check("S1b journal row completed", conn1.table[0]["state"] == "completed", f"{conn1.table!r}")
    check(
        "S1c observed_post_hash == deterministic expected == disk canonical sha",
        conn1.table[0]["observed_post_hash"] == expected_canonical1 == sha256_file(fp1["canonical"])
        == result1.canonical_hash,
    )
    check(
        "S1d canonical bytes are EXACTLY the single-source serializer's output",
        fp1["canonical"].read_bytes()
        == fact_approval._canonical_json_bytes(
            fact_approval.build_canonical(json.loads(fp1["pending"].read_text(encoding="utf-8")))
        ),
    )
    check("S1e journal action_family/target_ref/target_state correct",
          conn1.table[0]["action_family"] == "promotion.fact"
          and conn1.table[0]["target_ref"] == f"fact.{FACT_DOC}.canonical"
          and conn1.table[0]["target_state"] == "approved")
    audit1 = json.loads(Path(result1.audit_path).read_text(encoding="utf-8"))
    check(
        "S1f audit carries mutation_idempotency_key/resource_key/actor_ref + promotion reviewer sentinel",
        audit1.get("mutation_idempotency_key") == conn1.table[0]["idempotency_key"]
        and audit1.get("mutation_resource_key") == f"case:{case_id1}"
        and audit1.get("mutation_actor_ref") == "7"
        and audit1.get("reviewer_ref") == promo.PROMOTION_REVIEWER_REF,
    )
    check(
        "S1g audit binds pending+canonical hashes (source_pending_sha256/canonical_sha256)",
        audit1.get("source_pending_sha256") == pending_sha1
        and audit1.get("canonical_sha256") == expected_canonical1,
    )
    _extraction_id1 = audit1.get("extraction_id")
    check(
        "S1h audit filename is timestamped (NOT the legacy fixed '<extraction_id>.approval.json' name)",
        Path(result1.audit_path).name != f"{_extraction_id1}.approval.json"
        and Path(result1.audit_path).name.startswith(f"{_extraction_id1}_"),
        f"got {Path(result1.audit_path).name!r}",
    )
    check(
        "S1i pre-existing legacy audits are untouched byte-for-byte (coexistence, no overwrite)",
        all(
            sha256_file(fp1["reviews"] / name) == digest
            for name, digest in legacy_audits_before.items()
        ),
    )
    history_after1 = set(p.name for p in fp1["history"].glob("*"))
    new_backups1 = {n for n in history_after1 - history_before if n.startswith("facts_before_promotion_")}
    check("S1j overwrite variant created exactly one canonical backup in history/", len(new_backups1) == 1,
          f"{sorted(history_after1 - history_before)!r}")

    # ============================================================
    # S2 - fact FIRST-SAVE variant (canonical absent).
    # ============================================================
    case_id2, case_dir2 = make_promotion_case()
    fp2 = fact_paths_for(case_dir2)
    fp2["canonical"].unlink()
    principal2, repo2 = make_principal_and_repo(case_id2)
    pending_sha2 = sha256_file(fp2["pending"])
    history_before2 = set(p.name for p in fp2["history"].glob("*")) if fp2["history"].is_dir() else set()
    result2, conn2, _ = approve(
        "fact", case_id2, pending_sha2, document_id=FACT_DOC, principal=principal2, repo=repo2,
    )
    check("S2a first-save fact promotion completed", conn2.table[0]["state"] == "completed")
    check("S2b canonical now exists and matches expected",
          sha256_file(fp2["canonical"]) == fact_approval.compute_expected_canonical_sha256(fp2["pending"]))
    history_after2 = set(p.name for p in fp2["history"].glob("*")) if fp2["history"].is_dir() else set()
    check(
        "S2c first-save created NO canonical backup (there was nothing to back up)",
        not any(n.startswith("facts_before_promotion_") for n in history_after2 - history_before2),
    )

    # ============================================================
    # S3 - fact SAFE REPLAY (same identity, writer NOT re-invoked).
    # ============================================================
    audit_count_before_replay = len(list(fp1["reviews"].glob("*.approval.json")))
    result3, _, _ = approve(
        "fact", case_id1, pending_sha1, document_id=FACT_DOC,
        principal=principal1, repo=repo1, conn=conn1,
    )
    check("S3a safe replay returns replayed=True", result3.replayed is True)
    check("S3b replay: journal table still has exactly ONE row", len(conn1.table) == 1)
    check(
        "S3c replay: audit file count unchanged (writer genuinely NOT re-invoked)",
        len(list(fp1["reviews"].glob("*.approval.json"))) == audit_count_before_replay,
    )
    check(
        "S3d replay: canonical_hash is the FRESHLY re-verified disk hash",
        result3.canonical_hash == sha256_file(fp1["canonical"]),
    )
    check(
        "S3e replay: audit_path is the content-matched audit (not an mtime guess)",
        Path(result3.audit_path).name == Path(result1.audit_path).name,
    )

    # ============================================================
    # S4 - same identity + DIFFERENT note -> IdempotencyConflictError.
    # ============================================================
    expect_raises(
        mc.IdempotencyConflictError,
        lambda: approve(
            "fact", case_id1, pending_sha1, document_id=FACT_DOC, note="farklı bir not",
            principal=principal1, repo=repo1, conn=conn1,
        ),
        "S4a same identity + different --note -> IdempotencyConflictError",
    )
    check("S4b conflict created NO new journal row", len(conn1.table) == 1)

    # ============================================================
    # S5 - plain stale expected hash -> StaleViewError, zero rows.
    # ============================================================
    case_id5, case_dir5 = make_promotion_case()
    fp5 = fact_paths_for(case_dir5)
    principal5, repo5 = make_principal_and_repo(case_id5)
    canonical_sha_before5 = sha256_file(fp5["canonical"])
    _, conn5, _ = (None, FakeJournalConn(), None)
    expect_raises(
        StaleViewError,
        lambda: approve(
            "fact", case_id5, "0" * 64, document_id=FACT_DOC,
            principal=principal5, repo=repo5, conn=conn5,
        ),
        "S5a wrong --expected-hash -> StaleViewError",
    )
    check("S5b stale rejection wrote ZERO journal rows", len(conn5.table) == 0)
    check("S5c stale rejection left canonical untouched", sha256_file(fp5["canonical"]) == canonical_sha_before5)

    # ============================================================
    # S6 - composite race: canonical changed while waiting for the lock.
    # ============================================================
    case_id6, case_dir6 = make_promotion_case()
    fp6 = fact_paths_for(case_dir6)
    principal6, repo6 = make_principal_and_repo(case_id6)
    pending_sha6 = sha256_file(fp6["pending"])
    conn6 = FakeJournalConn()

    def _race_hook(_case_id):
        fp6["canonical"].write_text('{"tampered": true}', encoding="utf-8")

    _on_acquire_hooks.append(_race_hook)
    try:
        expect_raises(
            PreconditionRaceDetectedError,
            lambda: approve(
                "fact", case_id6, pending_sha6, document_id=FACT_DOC,
                principal=principal6, repo=repo6, conn=conn6,
            ),
            "S6a canonical-only change under the lock wait -> PreconditionRaceDetectedError",
        )
    finally:
        _on_acquire_hooks.remove(_race_hook)
    check("S6b composite race wrote ZERO journal rows (no prepared row)", len(conn6.table) == 0)

    # ============================================================
    # S7 - OUTER authz denial: zero connections, zero locks, zero
    #      journal, zero writer-path probes.
    # ============================================================
    case_id7, case_dir7 = make_promotion_case()
    principal7, repo7 = make_principal_and_repo(case_id7, assigned=False)
    conn7 = FakeJournalConn()
    _lock_calls_before7 = len(_lock_calls)
    _probe_counter = {"n": 0}
    _orig_get_pending = fact_approval.get_pending_path

    def _counting_get_pending(case_id, document_id):
        _probe_counter["n"] += 1
        return _orig_get_pending(case_id, document_id)

    fact_approval.get_pending_path = _counting_get_pending
    try:
        expect_raises(
            _authz.CaseAccessDeniedError,
            lambda: approve(
                "fact", case_id7, "1" * 64, document_id=FACT_DOC,
                principal=principal7, repo=repo7, conn=conn7,
            ),
            "S7a unassigned actor -> CaseAccessDeniedError (existence-blind)",
        )
        expect_raises(
            _authz.CaseAccessDeniedError,
            lambda: promo.preview_promotion(
                "fact", case_id7, principal=principal7, authz_repository=repo7,
            ),
            "S7b unassigned actor preview -> CaseAccessDeniedError BEFORE any enumeration",
        )
    finally:
        fact_approval.get_pending_path = _orig_get_pending
    check("S7c outer denial: ZERO journal rows / ZERO SQL calls", len(conn7.table) == 0 and len(conn7.calls) == 0)
    check("S7d outer denial: ZERO lock calls", len(_lock_calls) == _lock_calls_before7)
    check("S7e outer denial: ZERO writer path-getter probes (no filesystem targeting before authz)",
          _probe_counter["n"] == 0)

    # analyst: preview allowed (read), apply denied (mutate).
    principal7b, repo7b = make_principal_and_repo(case_id7, role="analyst")
    preview7 = promo.preview_promotion("fact", case_id7, principal=principal7b, authz_repository=repo7b)
    check("S7f analyst CAN preview (read capability)", preview7["mode"] == "enumeration")
    conn7b = FakeJournalConn()
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: approve(
            "fact", case_id7, "1" * 64, document_id=FACT_DOC,
            principal=principal7b, repo=repo7b, conn=conn7b,
        ),
        "S7g analyst apply -> CaseAccessDeniedError (mutate capability missing)",
    )
    check("S7h analyst apply denial: zero journal rows", len(conn7b.table) == 0)

    # ============================================================
    # S8 - INNER authz revocation while waiting for the lock.
    # ============================================================
    case_id8, case_dir8 = make_promotion_case()
    fp8 = fact_paths_for(case_dir8)
    principal8, repo8 = make_principal_and_repo(case_id8)
    pending_sha8 = sha256_file(fp8["pending"])
    conn8 = FakeJournalConn()

    def _revoke_hook(_case_id):
        repo8.assignments.pop((7, case_id8), None)

    _on_acquire_hooks.append(_revoke_hook)
    try:
        expect_raises(
            _authz.CaseAccessDeniedError,
            lambda: approve(
                "fact", case_id8, pending_sha8, document_id=FACT_DOC,
                principal=principal8, repo=repo8, conn=conn8,
            ),
            "S8a under-lock revocation -> inner authoritative authz denies",
        )
    finally:
        _on_acquire_hooks.remove(_revoke_hook)
    check("S8b inner denial wrote ZERO journal rows", len(conn8.table) == 0)
    check("S8c inner denial left canonical untouched", fp8["canonical"].is_file())

    # ============================================================
    # S9 - TIMELINE writer crash BEFORE canonical (T1b boundary):
    #      backup exists, rollback audit exists, canonical unchanged,
    #      journal reconciliation_required, adapter proves pre-unchanged.
    # ============================================================
    case_id9, case_dir9 = make_promotion_case()
    tp9 = timeline_paths_for(case_dir9)
    principal9, repo9 = make_principal_and_repo(case_id9)
    pending_sha9 = sha256_file(tp9["pending"])
    canonical_sha_before9 = sha256_file(tp9["canonical"])
    pre_composite9 = promo_adapters._compute_promotion_composite(tp9["pending"], tp9["canonical"])
    conn9 = FakeJournalConn()

    _orig_atomic = timeline_approval.atomic_write_json
    _boom9 = OSError("simulated disk failure at canonical write")

    def _raising_atomic(path, data):
        raise _boom9

    timeline_approval.atomic_write_json = _raising_atomic
    try:
        caught9 = expect_raises(
            OSError,
            lambda: approve(
                "timeline", case_id9, pending_sha9, principal=principal9, repo=repo9, conn=conn9,
            ),
            "S9a canonical-write crash propagates the ORIGINAL writer exception",
        )
        check("S9a2 the propagated exception IS the injected instance", caught9 is _boom9)
    finally:
        timeline_approval.atomic_write_json = _orig_atomic
    check("S9b journal row is reconciliation_required (NEVER failed)",
          len(conn9.table) == 1 and conn9.table[0]["state"] == "reconciliation_required")
    check("S9c observed_post_hash is NULL while writer effects are partial",
          conn9.table[0]["observed_post_hash"] is None)
    check("S9d canonical is byte-unchanged (rollback/atomicity)",
          sha256_file(tp9["canonical"]) == canonical_sha_before9)
    _rollback_audits9 = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in tp9["reviews"].glob("*.approval.json")
        if json.loads(p.read_text(encoding="utf-8")).get("rollback") is True
    ]
    check(
        "S9e rollback audit exists, carries mutation keys, and carries NO canonical_sha256",
        len(_rollback_audits9) == 1
        and _rollback_audits9[0].get("mutation_idempotency_key") == conn9.table[0]["idempotency_key"]
        and _rollback_audits9[0].get("mutation_resource_key") == f"case:{case_id9}"
        and "canonical_sha256" not in _rollback_audits9[0],
        f"{_rollback_audits9!r}",
    )
    _backups9 = [p.name for p in tp9["history"].glob("timeline_before_promotion_*")]
    check("S9f pre-canonical backup exists in history/ (durable writer-entry evidence)", len(_backups9) >= 1)

    entry9 = mr.JournalEntrySnapshot(
        journal_id=1, resource_key=f"case:{case_id9}", action_family="promotion.timeline",
        target_ref="timeline.canonical", target_state="approved",
        pre_hash=pre_composite9, pre_revision=pending_sha9, expected_post_hash=None,
        state="reconciliation_required", idempotency_key=conn9.table[0]["idempotency_key"],
        request_fingerprint=conn9.table[0]["request_fingerprint"], actor_label="iam_user",
    )
    _adapter_t = promo_adapters.PromotionReconciliationAdapter(timeline_approval, "timeline")
    ev9 = _adapter_t.gather_evidence(entry9)
    check(
        "S9g adapter proves pre-state unchanged (post=False, pre=True) -> would resolve failed",
        ev9.pre_state_confirmed_unchanged is True and ev9.post_state_verified is False,
    )

    # ============================================================
    # S10 - FACT audit-write crash AFTER canonical (F3 boundary):
    #       FIRST-SAVE fixture (canonical absent at request time), so
    #       the composite pre-state REALLY transitions - an OVERWRITE
    #       re-promotion of an already-promoted pending is byte-
    #       idempotent and its composite pre-proof legitimately resolves
    #       `failed` instead (pinned by the PG integration test's own
    #       P6d scenario). Here: canonical newly created + deterministic
    #       match + NO matching audit -> adapter dual-false, with the
    #       REAL request-time composite as entry.pre_hash (never a
    #       fabricated value).
    # ============================================================
    case_id10, case_dir10 = make_promotion_case()
    fp10 = fact_paths_for(case_dir10)
    fp10["canonical"].unlink()
    principal10, repo10 = make_principal_and_repo(case_id10)
    pending_sha10 = sha256_file(fp10["pending"])
    expected10 = fact_approval.compute_expected_canonical_sha256(fp10["pending"])
    pre_composite10 = promo_adapters._compute_promotion_composite(fp10["pending"], fp10["canonical"])
    conn10 = FakeJournalConn()

    _orig_audit_writer = fact_approval._write_audit_record_excl
    _boom10 = OSError("simulated disk failure at audit write")

    def _raising_audit_writer(reviews_dir, extraction_id, record):
        raise _boom10

    fact_approval._write_audit_record_excl = _raising_audit_writer
    try:
        expect_raises(
            OSError,
            lambda: approve(
                "fact", case_id10, pending_sha10, document_id=FACT_DOC,
                principal=principal10, repo=repo10, conn=conn10,
            ),
            "S10a audit-write crash propagates (post-canonical boundary)",
        )
    finally:
        fact_approval._write_audit_record_excl = _orig_audit_writer
    check("S10b journal row reconciliation_required, observed NULL",
          conn10.table[0]["state"] == "reconciliation_required"
          and conn10.table[0]["observed_post_hash"] is None)
    check("S10c canonical IS promoted (matches deterministic expected)",
          sha256_file(fp10["canonical"]) == expected10)
    entry10 = mr.JournalEntrySnapshot(
        journal_id=1, resource_key=f"case:{case_id10}", action_family="promotion.fact",
        target_ref=f"fact.{FACT_DOC}.canonical", target_state="approved",
        pre_hash=pre_composite10, pre_revision=pending_sha10, expected_post_hash=None,
        state="reconciliation_required", idempotency_key=conn10.table[0]["idempotency_key"],
        request_fingerprint=conn10.table[0]["request_fingerprint"], actor_label="iam_user",
    )
    _adapter_f = promo_adapters.PromotionReconciliationAdapter(fact_approval, "fact")
    ev10 = _adapter_f.gather_evidence(entry10)
    check(
        "S10d F3 contract: canonical deterministically correct BUT no matching audit -> DUAL-FALSE "
        "(never auto-completed)",
        ev10.post_state_verified is False and ev10.pre_state_confirmed_unchanged is False,
    )

    # ============================================================
    # S11 - completed-UPDATE failure AFTER a successful writer.
    # ============================================================
    case_id11, case_dir11 = make_promotion_case()
    tp11 = timeline_paths_for(case_dir11)
    principal11, repo11 = make_principal_and_repo(case_id11)
    pending_sha11 = sha256_file(tp11["pending"])
    conn11 = FakeJournalConn()
    conn11.break_completed = True
    expect_raises(
        mc.JournalCompletionUncertainError,
        lambda: approve(
            "timeline", case_id11, pending_sha11, principal=principal11, repo=repo11, conn=conn11,
        ),
        "S11a _mark_completed failure -> JournalCompletionUncertainError",
    )
    check("S11b row remains 'executing' with observed NULL (stale-executing gate)",
          conn11.table[0]["state"] == "executing" and conn11.table[0]["observed_post_hash"] is None)
    check("S11c writer effects ARE durable (canonical == deterministic expected)",
          sha256_file(tp11["canonical"]) == timeline_approval.compute_expected_canonical_sha256(tp11["pending"]))
    _success_audits11 = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in tp11["reviews"].glob("*.approval.json")
        if json.loads(p.read_text(encoding="utf-8")).get("approved") is True
        and json.loads(p.read_text(encoding="utf-8")).get("mutation_idempotency_key")
    ]
    check("S11d success audit exists with canonical_sha256 bound",
          len(_success_audits11) == 1
          and _success_audits11[0].get("canonical_sha256") == sha256_file(tp11["canonical"]))
    entry11 = mr.JournalEntrySnapshot(
        journal_id=1, resource_key=f"case:{case_id11}", action_family="promotion.timeline",
        target_ref="timeline.canonical", target_state="approved",
        pre_hash="x" * 64, pre_revision=pending_sha11, expected_post_hash=None,
        state="executing", idempotency_key=conn11.table[0]["idempotency_key"],
        request_fingerprint=conn11.table[0]["request_fingerprint"], actor_label="iam_user",
    )
    ev11 = _adapter_t.gather_evidence(entry11)
    check(
        "S11e adapter can prove post-state for the stale-executing row (deterministic match + "
        "exactly-one bound audit) -> would resolve completed",
        ev11.post_state_verified is True and ev11.observed_post_hash == sha256_file(tp11["canonical"]),
    )

    # ============================================================
    # S12 - timeline fresh overwrite + first-save + replay.
    # ============================================================
    case_id12, case_dir12 = make_promotion_case()
    tp12 = timeline_paths_for(case_dir12)
    principal12, repo12 = make_principal_and_repo(case_id12)
    pending_sha12 = sha256_file(tp12["pending"])
    expected12 = timeline_approval.compute_expected_canonical_sha256(tp12["pending"])
    result12, conn12, _ = approve("timeline", case_id12, pending_sha12, principal=principal12, repo=repo12)
    check("S12a timeline overwrite promotion completed; hash chain consistent",
          conn12.table[0]["state"] == "completed"
          and result12.canonical_hash == expected12 == sha256_file(tp12["canonical"]))
    audit12 = json.loads(Path(result12.audit_path).read_text(encoding="utf-8"))
    check(
        "S12b timeline SUCCESS audit carries canonical_sha256 + all three mutation fields",
        audit12.get("canonical_sha256") == expected12
        and audit12.get("mutation_idempotency_key") == conn12.table[0]["idempotency_key"]
        and audit12.get("mutation_resource_key") == f"case:{case_id12}"
        and audit12.get("mutation_actor_ref") == "7"
        and audit12.get("approved") is True and audit12.get("rollback") is False,
    )
    result12r, _, _ = approve(
        "timeline", case_id12, pending_sha12, principal=principal12, repo=repo12, conn=conn12,
    )
    check("S12c timeline safe replay OK (replayed=True, fresh hash)",
          result12r.replayed is True and result12r.canonical_hash == expected12)

    entry12 = mr.JournalEntrySnapshot(
        journal_id=1, resource_key=f"case:{case_id12}", action_family="promotion.timeline",
        target_ref="timeline.canonical", target_state="approved",
        pre_hash="x" * 64, pre_revision=pending_sha12, expected_post_hash=None,
        state="reconciliation_required", idempotency_key=conn12.table[0]["idempotency_key"],
        request_fingerprint=conn12.table[0]["request_fingerprint"], actor_label="iam_user",
    )
    ev12 = _adapter_t.gather_evidence(entry12)
    check("S12d adapter post-verifies the completed timeline promotion",
          ev12.post_state_verified is True and ev12.observed_post_hash == expected12)

    case_id12b, case_dir12b = make_promotion_case()
    tp12b = timeline_paths_for(case_dir12b)
    tp12b["canonical"].unlink()
    principal12b, repo12b = make_principal_and_repo(case_id12b)
    result12b, conn12b, _ = approve(
        "timeline", case_id12b, sha256_file(tp12b["pending"]), principal=principal12b, repo=repo12b,
    )
    check("S12e timeline FIRST-SAVE promotion completed (missing create-chain handled)",
          conn12b.table[0]["state"] == "completed" and tp12b["canonical"].is_file())

    # ============================================================
    # S13 - facade-level argument-shape rules (pre-I/O).
    # ============================================================
    conn13 = FakeJournalConn()
    for label, kwargs in [
        ("S13a timeline + document -> PromotionArgumentError", dict(row_key="timeline", document_id="x")),
        ("S13b timeline + note -> PromotionArgumentError", dict(row_key="timeline", note="n")),
        ("S13c fact apply without document -> PromotionArgumentError", dict(row_key="fact")),
        ("S13d blank expected_hash -> PromotionArgumentError", dict(row_key="fact", document_id=FACT_DOC, expected=" ")),
    ]:
        expect_raises(
            promo.PromotionArgumentError,
            lambda kw=kwargs: promo.approve_promotion_mutation(
                kw["row_key"], case_id12, kw.get("expected", "a" * 64),
                document_id=kw.get("document_id"), note=kw.get("note"),
                principal=principal12, authz_repository=repo12,
                conn_factory=lambda: (_ for _ in ()).throw(AssertionError("conn_factory must not be called")),
            ),
            label,
        )
    check("S13e argument-shape rejections performed ZERO journal SQL", len(conn13.calls) == 0)

    # ============================================================
    # S14 - content cross-check failures.
    # ============================================================
    case_id14, case_dir14 = make_promotion_case()
    fp14 = fact_paths_for(case_dir14)
    other_ext = case_dir14 / "documents" / "ihbarname_001" / "extractions"
    shutil.copy2(fp14["pending"], other_ext / fact_approval.CURRENT_PENDING_FILENAME)
    principal14, repo14 = make_principal_and_repo(case_id14)
    conn14 = FakeJournalConn()
    expect_raises(
        promo.PromotionContentMismatchError,
        lambda: approve(
            "fact", case_id14, sha256_file(other_ext / fact_approval.CURRENT_PENDING_FILENAME),
            document_id="ihbarname_001", principal=principal14, repo=repo14, conn=conn14,
        ),
        "S14a pending whose source_document_id != --document -> PromotionContentMismatchError",
    )
    _p14 = json.loads(fp14["pending"].read_text(encoding="utf-8"))
    _p14["case_id"] = "case_9999"
    fp14["pending"].write_text(json.dumps(_p14, ensure_ascii=False, indent=2), encoding="utf-8")
    expect_raises(
        promo.PromotionContentMismatchError,
        lambda: approve(
            "fact", case_id14, sha256_file(fp14["pending"]), document_id=FACT_DOC,
            principal=principal14, repo=repo14, conn=conn14,
        ),
        "S14b pending whose case_id != resolved case -> PromotionContentMismatchError",
    )
    check("S14c content-mismatch rejections wrote ZERO journal rows", len(conn14.table) == 0)

    # ============================================================
    # S15 - EXACT under-lock verified-Path handoff to the writer.
    # ============================================================
    case_id15, case_dir15 = make_promotion_case()
    fp15 = fact_paths_for(case_dir15)
    principal15, repo15 = make_principal_and_repo(case_id15)
    pending_sha15 = sha256_file(fp15["pending"])
    captured15 = {}
    _orig_promote = fact_approval.promote

    def _capturing_promote(*args, **kwargs):
        captured15["kwargs"] = kwargs
        return _orig_promote(*args, **kwargs)

    fact_approval.promote = _capturing_promote
    try:
        result15, conn15, _ = approve(
            "fact", case_id15, pending_sha15, document_id=FACT_DOC,
            principal=principal15, repo=repo15,
        )
    finally:
        fact_approval.promote = _orig_promote
    vp15 = captured15["kwargs"]["verified_paths"]
    check("S15a writer got verified_paths with the exact five-key contract",
          set(vp15.keys()) == {"extractions_dir", "pending_path", "canonical_path", "history_dir", "reviews_dir"})
    check(
        "S15b pending arg IS the same object as verified_paths['pending_path'] (identity, not equality)",
        captured15["kwargs"]["pending_path"] is vp15["pending_path"],
    )
    check(
        "S15c every handed-off Path is fully RESOLVED (== its own realpath) inside the writer case root",
        all(
            str(p) == os.path.realpath(str(p)) or not Path(p).exists()
            for p in vp15.values()
        ) and str(vp15["pending_path"]) == os.path.realpath(str(vp15["pending_path"])),
    )
    check("S15d handoff run itself completed", conn15.table[0]["state"] == "completed")

    # ============================================================
    # S16 - PATH ESCAPE MATRIX (real mklink /J on Windows).
    # ============================================================
    if _IS_WINDOWS:
        outside_root = Path(tempfile.mkdtemp(prefix="vergi_promo_outside_"))
        _outside_dirs.append(outside_root)
        canary = outside_root / "canary.json"
        canary.write_text('{"canary": "untouched"}', encoding="utf-8")
        canary_sha = sha256_file(canary)

        def outside_snapshot():
            return sorted(p.name for p in outside_root.rglob("*"))

        outside_before = outside_snapshot()

        def escape_case(label, row_key, make_link, *, doc=None, expect_exc=promo.PromotionNestedPathContainmentError):
            case_id_e, case_dir_e = make_promotion_case()
            if row_key == "fact":
                pe = fact_paths_for(case_dir_e)
            else:
                pe = timeline_paths_for(case_dir_e)
            pending_sha_e = sha256_file(pe["pending"]) if pe["pending"].is_file() else "1" * 64
            make_link(case_dir_e, pe)
            principal_e, repo_e = make_principal_and_repo(case_id_e)
            conn_e = FakeJournalConn()
            expect_raises(
                expect_exc,
                lambda: approve(
                    row_key, case_id_e, pending_sha_e, document_id=doc,
                    principal=principal_e, repo=repo_e, conn=conn_e,
                ),
                label,
            )
            check(f"{label} [zero journal rows]", len(conn_e.table) == 0, f"{conn_e.table!r}")
            return case_dir_e

        # a) fact extractions dir -> live junction OUTSIDE.
        def _link_extractions(case_dir_e, pe):
            target = outside_root / f"ext_{uuid.uuid4().hex[:6]}"
            shutil.copytree(pe["extractions"], target)
            shutil.rmtree(pe["extractions"])
            make_junction(pe["extractions"], target)

        escape_case("S16a fact extractions-dir LIVE junction escape refused", "fact",
                    _link_extractions, doc=FACT_DOC)

        _empty_escape_targets = []

        # b) fact history dir -> live junction OUTSIDE (empty target:
        #    stays empty <=> the facade/writer never wrote through it).
        def _link_history(case_dir_e, pe):
            target = outside_root / f"hist_{uuid.uuid4().hex[:6]}"
            target.mkdir()
            _empty_escape_targets.append(target)
            if pe["history"].is_dir():
                shutil.rmtree(pe["history"])
            make_junction(pe["history"], target)

        escape_case("S16b fact history-dir LIVE junction escape refused", "fact",
                    _link_history, doc=FACT_DOC)

        # c) fact reviews dir -> live junction OUTSIDE (empty target).
        def _link_reviews(case_dir_e, pe):
            target = outside_root / f"rev_{uuid.uuid4().hex[:6]}"
            target.mkdir()
            _empty_escape_targets.append(target)
            if pe["reviews"].is_dir():
                shutil.rmtree(pe["reviews"])
            make_junction(pe["reviews"], target)

        escape_case("S16c fact reviews-dir LIVE junction escape refused", "fact",
                    _link_reviews, doc=FACT_DOC)

        # d) timeline dir -> live junction OUTSIDE.
        def _link_timeline(case_dir_e, pe):
            target = outside_root / f"tl_{uuid.uuid4().hex[:6]}"
            shutil.copytree(pe["timeline"], target)
            shutil.rmtree(pe["timeline"])
            make_junction(pe["timeline"], target)

        escape_case("S16d timeline-dir LIVE junction escape refused", "timeline", _link_timeline)

        # e) BROKEN junction (target removed after link creation).
        def _broken_timeline(case_dir_e, pe):
            target = outside_root / f"broken_{uuid.uuid4().hex[:6]}"
            target.mkdir()
            shutil.rmtree(pe["timeline"])
            make_junction(pe["timeline"], target)
            target.rmdir()
            assert os.path.lexists(pe["timeline"]) and not pe["timeline"].exists()

        escape_case("S16e timeline BROKEN junction (lexists=True/exists=False) refused fail-closed",
                    "timeline", _broken_timeline)

        # f) under-lock junction SWAP (pre-lock verified, swapped while
        #    waiting for the lock) -> race detection, zero prepared rows.
        case_id16f, case_dir16f = make_promotion_case()
        tp16f = timeline_paths_for(case_dir16f)
        principal16f, repo16f = make_principal_and_repo(case_id16f)
        pending_sha16f = sha256_file(tp16f["pending"])
        conn16f = FakeJournalConn()

        def _swap_hook(_case_id):
            aside = case_dir16f / "timeline_swapped_aside"
            tp16f["timeline"].rename(aside)
            make_junction(tp16f["timeline"], aside)

        _on_acquire_hooks.append(_swap_hook)
        try:
            expect_raises(
                PreconditionRaceDetectedError,
                lambda: approve(
                    "timeline", case_id16f, pending_sha16f,
                    principal=principal16f, repo=repo16f, conn=conn16f,
                ),
                "S16f pre-lock->under-lock junction swap -> PreconditionRaceDetectedError",
            )
        finally:
            _on_acquire_hooks.remove(_swap_hook)
        check("S16f [zero journal rows]", len(conn16f.table) == 0)

        # g) SAFE INTERNAL alias: timeline dir is a junction to a REAL
        #    sibling INSIDE the same case dir -> promotion succeeds and
        #    writes land at the RESOLVED real target.
        case_id16g, case_dir16g = make_promotion_case()
        tp16g = timeline_paths_for(case_dir16g)
        real_target = case_dir16g / "timeline_realdata"
        tp16g["timeline"].rename(real_target)
        make_junction(tp16g["timeline"], real_target)
        principal16g, repo16g = make_principal_and_repo(case_id16g)
        pending_sha16g = sha256_file(real_target / timeline_approval.CURRENT_PENDING_FILENAME)
        result16g, conn16g, _ = approve(
            "timeline", case_id16g, pending_sha16g, principal=principal16g, repo=repo16g,
        )
        check(
            "S16g SAFE internal alias: promotion succeeds THROUGH the alias, writing at the "
            "resolved real target",
            conn16g.table[0]["state"] == "completed"
            and (real_target / "timeline.json").is_file()
            and sha256_file(real_target / "timeline.json") == result16g.canonical_hash,
        )

        # canary / outside-tree invariance for every refusal above: the
        # canary is byte-unchanged AND every EMPTY escape target stayed
        # empty (nothing was ever read from or written through an
        # escaping link).
        check(
            "S16h outside canary byte-unchanged AND all empty escape targets stayed empty",
            sha256_file(canary) == canary_sha
            and all(list(t.iterdir()) == [] for t in _empty_escape_targets if t.exists()),
            f"canary_ok={sha256_file(canary) == canary_sha} "
            f"targets={[(str(t), [p.name for p in t.iterdir()]) for t in _empty_escape_targets if t.exists()]!r}",
        )
        # Adapter containment failure -> dual-false (reviews junction).
        case_id16i, case_dir16i = make_promotion_case()
        tp16i = timeline_paths_for(case_dir16i)
        target16i = outside_root / f"advrev_{uuid.uuid4().hex[:6]}"
        target16i.mkdir()
        shutil.rmtree(tp16i["reviews"])
        make_junction(tp16i["reviews"], target16i)
        entry16i = mr.JournalEntrySnapshot(
            journal_id=99, resource_key=f"case:{case_id16i}", action_family="promotion.timeline",
            target_ref="timeline.canonical", target_state="approved",
            pre_hash="x" * 64, pre_revision=sha256_file(tp16i["pending"]), expected_post_hash=None,
            state="reconciliation_required", idempotency_key="k" * 64,
            request_fingerprint="f" * 64, actor_label="iam_user",
        )
        ev16i = _adapter_t.gather_evidence(entry16i)
        check(
            "S16i adapter: reviews-dir junction escape -> DUAL-FALSE evidence (never a raise, "
            "never a proof)",
            ev16i.post_state_verified is False and ev16i.pre_state_confirmed_unchanged is False,
        )
    else:
        skip_info("S16a-S16i Windows NTFS junction escape matrix", "sys.platform != 'win32'")
        # POSIX symlink equivalents (file-level symlinks possible without privileges).
        try:
            case_id16p, case_dir16p = make_promotion_case()
            tp16p = timeline_paths_for(case_dir16p)
            outside_root_p = Path(tempfile.mkdtemp(prefix="vergi_promo_outside_"))
            _outside_dirs.append(outside_root_p)
            target_p = outside_root_p / "tl_target"
            shutil.copytree(tp16p["timeline"], target_p)
            shutil.rmtree(tp16p["timeline"])
            os.symlink(target_p, tp16p["timeline"], target_is_directory=True)
            _junction_links.append(tp16p["timeline"])
            principal16p, repo16p = make_principal_and_repo(case_id16p)
            conn16p = FakeJournalConn()
            expect_raises(
                promo.PromotionNestedPathContainmentError,
                lambda: approve(
                    "timeline", case_id16p, sha256_file(target_p / timeline_approval.CURRENT_PENDING_FILENAME),
                    principal=principal16p, repo=repo16p, conn=conn16p,
                ),
                "S16p POSIX timeline-dir symlink escape refused",
            )
            check("S16p [zero journal rows]", len(conn16p.table) == 0)
            # ELOOP: self-referential symlink.
            loop_case_id, loop_case_dir = make_promotion_case()
            lp = timeline_paths_for(loop_case_dir)
            shutil.rmtree(lp["timeline"])
            os.symlink(lp["timeline"], lp["timeline"])
            _junction_links.append(lp["timeline"])
            principal_lp, repo_lp = make_principal_and_repo(loop_case_id)
            conn_lp = FakeJournalConn()
            expect_raises(
                promo.PromotionNestedPathContainmentError,
                lambda: approve(
                    "timeline", loop_case_id, "1" * 64,
                    principal=principal_lp, repo=repo_lp, conn=conn_lp,
                ),
                "S16q POSIX looping (ELOOP) timeline symlink refused fail-closed",
            )
            check("S16q [zero journal rows]", len(conn_lp.table) == 0)
        except OSError as _posix_err:
            skip_info("S16p/S16q POSIX symlink sub-tests", f"symlink creation unavailable: {_posix_err!r}")

    # ============================================================
    # S17 - preview surfaces.
    # ============================================================
    case_id17, case_dir17 = make_promotion_case()
    fp17 = fact_paths_for(case_dir17)
    tp17 = timeline_paths_for(case_dir17)
    principal17, repo17 = make_principal_and_repo(case_id17)
    enum17 = promo.preview_promotion("fact", case_id17, principal=principal17, authz_repository=repo17)
    check(
        "S17a fact enumeration preview lists exactly the documents holding a CURRENT-name pending",
        enum17["mode"] == "enumeration"
        and [d["document_id"] for d in enum17["documents"]] == [FACT_DOC]
        and enum17["documents"][0]["pending_hash"] == sha256_file(fp17["pending"]),
    )
    single17 = promo.preview_promotion(
        "fact", case_id17, document_id=FACT_DOC, principal=principal17, authz_repository=repo17,
    )
    check(
        "S17b fact single preview: hash + canonical presence + validator-ready",
        single17["mode"] == "single" and single17["pending_hash"] == sha256_file(fp17["pending"])
        and single17["canonical_exists"] is True and single17["validation_ready"] is True,
    )
    single17t = promo.preview_promotion(
        "timeline", case_id17, principal=principal17, authz_repository=repo17,
    )
    check(
        "S17c timeline preview: hash + validator-ready",
        single17t["pending_hash"] == sha256_file(tp17["pending"]) and single17t["validation_ready"] is True,
    )
    expect_raises(
        PendingNotFoundError,
        lambda: promo.preview_promotion(
            "fact", case_id17, document_id="vir_001", principal=principal17, authz_repository=repo17,
        ),
        "S17d fact preview for a document WITHOUT a current-name pending -> PendingNotFoundError "
        "(old version-named pendings are deliberately unresolvable)",
    )

    # ============================================================
    # S18 - adapter: malformed target_ref -> dual-false; happy fact
    #       post-verification for a REAL completed promotion.
    # ============================================================
    ev18a = _adapter_f.gather_evidence(mr.JournalEntrySnapshot(
        journal_id=5, resource_key=f"case:{case_id1}", action_family="promotion.fact",
        target_ref="fact..canonical", target_state="approved",
        pre_hash="x" * 64, pre_revision="y" * 64, expected_post_hash=None,
        state="reconciliation_required", idempotency_key="k" * 64,
        request_fingerprint="f" * 64, actor_label="iam_user",
    ))
    check("S18a adapter: malformed/empty-document target_ref -> dual-false",
          ev18a.post_state_verified is False and ev18a.pre_state_confirmed_unchanged is False)
    entry18b = mr.JournalEntrySnapshot(
        journal_id=6, resource_key=f"case:{case_id1}", action_family="promotion.fact",
        target_ref=f"fact.{FACT_DOC}.canonical", target_state="approved",
        pre_hash="x" * 64, pre_revision=pending_sha1, expected_post_hash=None,
        state="reconciliation_required", idempotency_key=conn1.table[0]["idempotency_key"],
        request_fingerprint=conn1.table[0]["request_fingerprint"], actor_label="iam_user",
    )
    ev18b = _adapter_f.gather_evidence(entry18b)
    check(
        "S18b adapter: REAL completed fact promotion post-verified (deterministic + exactly-one "
        "bound audit)",
        ev18b.post_state_verified is True and ev18b.observed_post_hash == expected_canonical1,
    )
    # Duplicate bound audit -> refuses to auto-complete (dual-false).
    dup_target = Path(result1.audit_path).with_name("zzz_dup_" + Path(result1.audit_path).name)
    shutil.copy2(result1.audit_path, dup_target)
    ev18c = _adapter_f.gather_evidence(entry18b)
    check(
        "S18c adapter: DUPLICATE fully-bound audits -> dual-false (exactly-one rule enforced)",
        ev18c.post_state_verified is False and ev18c.pre_state_confirmed_unchanged is False,
    )
    dup_target.unlink()

finally:
    ml.acquire_case_lock_session = _original_acquire
    ml.release_lock_session = _original_release

    # Cleanup: links BEFORE targets, then case dirs, then outside dirs.
    for link in _junction_links:
        try:
            if os.path.lexists(link):
                if link.is_symlink() or _IS_WINDOWS:
                    try:
                        os.rmdir(link)
                    except OSError:
                        os.unlink(link)
        except OSError as cleanup_error:
            print(f"CLEANUP WARNING: link {link}: {cleanup_error!r}")
    for case_dir in _created_case_dirs:
        try:
            if case_dir.exists():
                shutil.rmtree(case_dir)
        except OSError as cleanup_error:
            print(f"CLEANUP WARNING: case dir {case_dir}: {cleanup_error!r}")
    for outside in _outside_dirs:
        try:
            if outside.exists():
                shutil.rmtree(outside)
        except OSError as cleanup_error:
            print(f"CLEANUP WARNING: outside dir {outside}: {cleanup_error!r}")

_data_tree_after_everything = snapshot_data_tree()
check(
    "FINAL: the real data/ tree is byte-for-byte IDENTICAL to the pre-test snapshot "
    "(all synthetic cases fully removed, no residue anywhere)",
    _data_tree_after_everything == _data_tree_before_everything,
    f"diff keys: {sorted(set(_data_tree_after_everything) ^ set(_data_tree_before_everything))[:20]!r}",
)
check(
    "FINAL: no junction/symlink link residue remains",
    all(not os.path.lexists(link) for link in _junction_links),
)

print(
    f"--- test_promotion_mutation_facade_isolated: {passed} passed, {failed} failed "
    f"({_informational_skips} informational SKIPPED line(s), NOT counted) ---"
)
sys.exit(1 if failed else 0)
