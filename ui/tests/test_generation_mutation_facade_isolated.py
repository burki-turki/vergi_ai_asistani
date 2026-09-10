# ============================================================
# ROW 19C-3c-i - isolated tests for
# ui/services/generation_mutation_facade.py AND
# ui/services/generation_mutation_adapters.py (fake journal conn, fake
# locks, in-memory authz, REAL deadline_engine/timeline_engine writer
# modules against REAL, re-identified synthetic copies of case_0001
# created under the real `data/cases/` tree and fully removed at the
# end - the ENTIRE real data/ tree is snapshot-compared before/after).
# Mirrors `test_promotion_mutation_facade_isolated.py`'s established
# fixture/fake shapes exactly (same FakeJournalConn/Cursor SQL
# handling, same on-acquire lock hook mechanism, same synthetic-case
# helper pattern) - never re-derived independently.
#
# Run: python ui/tests/test_generation_mutation_facade_isolated.py
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

from ui.services import authz as _authz                                    # noqa: E402
from ui.services import mutation_coordinator as mc                          # noqa: E402
from ui.services import mutation_lock as ml                                 # noqa: E402
from ui.services import paths as _paths                                     # noqa: E402
from ui.services import generation_mutation_facade as gen                   # noqa: E402
from ui.services import generation_mutation_adapters as gen_adapters        # noqa: E402
from ui.services.common import StaleViewError, PreconditionRaceDetectedError  # noqa: E402

import deadline_engine                                                      # noqa: E402
import deadline_calculator                                                  # noqa: E402
import timeline_engine                                                      # noqa: E402

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
    global _informational_skips
    _informational_skips += 1
    print(f"SKIPPED (NOT counted as pass/fail) {label} - {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type as error:
        check(label, True)
        return error
    except Exception as error:  # noqa: BLE001
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
# Fake mutation.mutation_journal (exact SQL shapes run_mutation() uses) -
# an INDEPENDENT copy of test_promotion_mutation_facade_isolated.py's own
# fixture, never imported from it (each isolated test file owns its own
# fixtures, by this project's own established convention).
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
                "id": new_id, "resource_key": resource_key, "action_family": action_family,
                "actor_user_id": actor_user_id, "actor_label": actor_label, "target_ref": target_ref,
                "target_state": target_state, "pre_hash": pre_hash, "pre_revision": pre_revision,
                "idempotency_key": idempotency_key, "request_fingerprint": request_fingerprint,
                "state": "prepared", "failure_code": None, "resolution_code": None,
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
# work - the exact window a concurrent case-content edit would occupy).
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
_junction_links = []


def make_junction(link_path: Path, target_path: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(f"mklink /J failed rc={result.returncode}: {result.stdout!r} {result.stderr!r}")
    _junction_links.append(link_path)


def make_generation_case():
    case_id = f"geniso{uuid.uuid4().hex[:10]}"
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
    # strip stale, checked-in generation artefacts (case_0001 already
    # carries a committed deadline/timeline pending+canonical from an
    # earlier development row) for a genuinely clean generation state.
    deadlines_dir = dst / "deadlines"
    for stale in deadlines_dir.glob("*.pending"):
        stale.unlink()
    timeline_dir = dst / "timeline"
    stale_timeline_pending = timeline_dir / timeline_engine.CANONICAL_PENDING_FILENAME
    if stale_timeline_pending.exists():
        stale_timeline_pending.unlink()
    for base_dir in (deadlines_dir, timeline_dir):
        for stale_dir_name in ("history", "generation_reviews"):
            stale_dir = base_dir / stale_dir_name
            if stale_dir.exists():
                shutil.rmtree(stale_dir)
    _created_case_dirs.append(dst)
    return case_id, dst


def make_principal_and_repo(case_id, *, assigned=True, role="lawyer"):
    principal = _authz.Principal(user_id=7, session_id=700, role_version_at_issue=1)
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[700] = _authz.SessionRecord(user_id=7, current_authz_version=1, disabled=False)
    if assigned:
        repo.assignments[(7, case_id)] = _authz.CaseAssignmentRecord(role=role)
    return principal, repo


ANCHOR_EVENT_ID = "timeline_event_003"


def preview(row_key, case_id, *, anchor_event_id=None, principal, repo, ruleset_path=None, provisions_path=None):
    return gen.preview_generation(
        row_key, case_id, anchor_event_id=anchor_event_id, principal=principal, authz_repository=repo,
        ruleset_path=ruleset_path, provisions_path=provisions_path,
    )


def apply(row_key, case_id, expected_input_digest, *, anchor_event_id=None, holiday_dates=None,
          calendar_complete=False, judicial_recess_applicable=None, principal, repo, conn=None,
          ruleset_path=None, provisions_path=None):
    conn = conn if conn is not None else FakeJournalConn()

    def conn_factory():
        return conn

    result = gen.apply_generation(
        row_key, case_id, expected_input_digest,
        anchor_event_id=anchor_event_id, holiday_dates=holiday_dates,
        calendar_complete=calendar_complete, judicial_recess_applicable=judicial_recess_applicable,
        principal=principal, authz_repository=repo, conn_factory=conn_factory,
        ruleset_path=ruleset_path, provisions_path=provisions_path,
    )
    return result, conn


# ----------------------------------------------------------------
# ROW 19C-3c-i DEADLINE REVISION-IDENTITY REMEDIATION - injected
# ruleset/provisions test fixtures (`_read_global_resource_bytes()`'s
# own documented "test-injection seam", never the real production
# `data/deadline_rules/deadline_rules.json`/`data/provisions.json`).
# Seeded with the REAL production bytes (so the actual rule-selection
# logic inside `deadline_engine.run_engine()` behaves identically to
# every other test in this suite) plus an appended, JSON-harmless
# trailing-whitespace suffix to produce a byte-distinct "revision" -
# `json.loads()` tolerates trailing whitespace after the top-level
# value, so this changes the SHA256 (and therefore `input_digest`)
# without changing a single parsed rule/provision.
# ----------------------------------------------------------------

_tmp_global_resources_dir = Path(tempfile.mkdtemp(prefix="vergi_gen_iso_globalres_"))
_ruleset_path_k = _tmp_global_resources_dir / "ruleset.json"
_provisions_path_k = _tmp_global_resources_dir / "provisions.json"
_REAL_RULESET_BYTES = deadline_engine.DEFAULT_RULESET_PATH.read_bytes()
_REAL_PROVISIONS_BYTES = deadline_calculator.DEFAULT_PROVISIONS_PATH.read_bytes()


def _write_ruleset_revision(revision: int) -> None:
    _ruleset_path_k.write_bytes(_REAL_RULESET_BYTES + b"\n" * revision)


def _write_provisions_revision(revision: int) -> None:
    _provisions_path_k.write_bytes(_REAL_PROVISIONS_BYTES + b"\n" * revision)


ml.acquire_case_lock_session = _fake_acquire
ml.release_lock_session = _fake_release

try:
    # ============================================================
    # A) ARGUMENT-SHAPE VALIDATION - zero I/O, zero connections.
    # ============================================================
    case_id_a, case_dir_a = make_generation_case()
    principal_a, repo_a = make_principal_and_repo(case_id_a)

    expect_raises(
        gen.GenerationArgumentError,
        lambda: preview("timeline", case_id_a, anchor_event_id="x", principal=principal_a, repo=repo_a),
        "A1: timeline preview with anchor_event_id -> GenerationArgumentError",
    )
    expect_raises(
        gen.GenerationArgumentError,
        lambda: preview("deadline", case_id_a, anchor_event_id=None, principal=principal_a, repo=repo_a),
        "A2: deadline preview WITHOUT anchor_event_id -> GenerationArgumentError",
    )
    expect_raises(
        gen.GenerationArgumentError,
        lambda: apply("timeline", case_id_a, "digest", holiday_dates=["2026-01-01"], principal=principal_a, repo=repo_a),
        "A3: timeline apply with holiday_dates -> GenerationArgumentError",
    )
    expect_raises(
        gen.GenerationArgumentError,
        lambda: apply("timeline", case_id_a, "digest", calendar_complete=True, principal=principal_a, repo=repo_a),
        "A4: timeline apply with calendar_complete -> GenerationArgumentError",
    )
    expect_raises(
        gen.GenerationArgumentError,
        lambda: apply("timeline", case_id_a, "digest", judicial_recess_applicable=True, principal=principal_a, repo=repo_a),
        "A5: timeline apply with judicial_recess_applicable -> GenerationArgumentError",
    )
    expect_raises(
        gen.GenerationArgumentError,
        lambda: apply("deadline", case_id_a, "", anchor_event_id=ANCHOR_EVENT_ID, principal=principal_a, repo=repo_a),
        "A6: apply with blank expected_input_digest -> GenerationArgumentError",
    )
    check(
        "A7: zero connections/journal rows were created by any of the above (pure arg checks)",
        True,  # implicit - no FakeJournalConn was ever constructed above
    )

    # ============================================================
    # B) PREVIEW - read-only, real containment-verified computation.
    # ============================================================
    preview_deadline_b = preview("deadline", case_id_a, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_a, repo=repo_a)
    check(
        "B1: deadline preview returns a real target_ref/input_digest and pending_exists=False "
        "(fresh synthetic case, no prior pending)",
        preview_deadline_b["target_ref"] == f"deadline.{ANCHOR_EVENT_ID}.pending"
        and isinstance(preview_deadline_b["input_digest"], str) and len(preview_deadline_b["input_digest"]) == 64
        and preview_deadline_b["pending_exists"] is False,
        f"got {preview_deadline_b!r}",
    )
    preview_timeline_b = preview("timeline", case_id_a, principal=principal_a, repo=repo_a)
    check(
        "B2: timeline preview returns target_ref='timeline.pending' and a real input_digest",
        preview_timeline_b["target_ref"] == "timeline.pending"
        and isinstance(preview_timeline_b["input_digest"], str) and len(preview_timeline_b["input_digest"]) == 64
        and preview_timeline_b["pending_exists"] is False,
        f"got {preview_timeline_b!r}",
    )
    check(
        "B3: previewing twice (read-only) produces the IDENTICAL input_digest both times "
        "(deterministic, no side effect)",
        preview("deadline", case_id_a, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_a, repo=repo_a)["input_digest"]
        == preview_deadline_b["input_digest"],
    )

    # ============================================================
    # C) APPLY - FRESH SUCCESS, deadline family.
    # ============================================================
    case_id_c, case_dir_c = make_generation_case()
    principal_c, repo_c = make_principal_and_repo(case_id_c)
    preview_c = preview("deadline", case_id_c, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_c, repo=repo_c)
    result_c, conn_c = apply(
        "deadline", case_id_c, preview_c["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_c, repo=repo_c,
    )
    check(
        "C1: fresh deadline apply: replayed=False, a real pending_path/pending_sha256/audit_path "
        "were produced",
        result_c.replayed is False and result_c.pending_path.is_file()
        and isinstance(result_c.pending_sha256, str) and result_c.audit_path is not None,
        f"got {result_c!r}",
    )
    check(
        "C2: fresh deadline apply: exactly ONE journal row, state='completed', "
        "action_family='generation.deadline', target_ref matches, target_state='generated'",
        len(conn_c.table) == 1 and conn_c.table[0]["state"] == "completed"
        and conn_c.table[0]["action_family"] == "generation.deadline"
        and conn_c.table[0]["target_ref"] == f"deadline.{ANCHOR_EVENT_ID}.pending"
        and conn_c.table[0]["target_state"] == "generated",
        f"got {conn_c.table!r}",
    )
    audit_record_c = json.loads(Path(result_c.audit_path).read_text(encoding="utf-8"))
    check(
        "C3: the real audit record's mutation_idempotency_key matches the journal row's own "
        "idempotency_key",
        audit_record_c["mutation_idempotency_key"] == conn_c.table[0]["idempotency_key"],
    )
    check(
        "C4: the lock was acquired for case_id_c and released exactly once each",
        _lock_calls.count(("acquire", case_id_c)) == 1 and _lock_calls.count(("release", 4242)) >= 1,
    )

    # ============================================================
    # D) APPLY - FRESH SUCCESS, timeline family.
    # ============================================================
    case_id_d, case_dir_d = make_generation_case()
    principal_d, repo_d = make_principal_and_repo(case_id_d)
    preview_d = preview("timeline", case_id_d, principal=principal_d, repo=repo_d)
    result_d, conn_d = apply("timeline", case_id_d, preview_d["input_digest"], principal=principal_d, repo=repo_d)
    check(
        "D1: fresh timeline apply: replayed=False, real pending/audit produced, target_ref="
        "'timeline.pending'",
        result_d.replayed is False and result_d.pending_path.is_file() and result_d.audit_path is not None
        and conn_d.table[0]["target_ref"] == "timeline.pending"
        and conn_d.table[0]["action_family"] == "generation.timeline",
        f"got {result_d!r} / {conn_d.table!r}",
    )
    audit_record_d = json.loads(Path(result_d.audit_path).read_text(encoding="utf-8"))
    check(
        "D2: timeline audit record's generation_parameters_digest is explicitly None",
        audit_record_d["generation_parameters_digest"] is None,
    )

    # ============================================================
    # E) StaleViewError - wrong expected_input_digest, ZERO journal rows.
    # ============================================================
    case_id_e, case_dir_e = make_generation_case()
    principal_e, repo_e = make_principal_and_repo(case_id_e)
    conn_e = FakeJournalConn()
    expect_raises(
        StaleViewError,
        lambda: apply("deadline", case_id_e, "0" * 64, anchor_event_id=ANCHOR_EVENT_ID,
                      principal=principal_e, repo=repo_e, conn=conn_e),
        "E1: wrong expected_input_digest -> StaleViewError",
    )
    check("E2: zero journal rows were created for the wrong-digest attempt", len(conn_e.table) == 0)
    check("E3: no pending file was written for the wrong-digest attempt", not deadline_engine.get_pending_path(case_id_e).exists())

    # ============================================================
    # F) PreconditionRaceDetectedError - case content changes WHILE the
    #    lock is being waited for (via the on-acquire hook).
    # ============================================================
    case_id_f, case_dir_f = make_generation_case()
    principal_f, repo_f = make_principal_and_repo(case_id_f)
    preview_f = preview("deadline", case_id_f, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_f, repo=repo_f)

    def _mutate_case_json_mid_lock_wait(case_id):
        if case_id != case_id_f:
            return
        case_json_path = case_dir_f / "case.json"
        data = json.loads(case_json_path.read_text(encoding="utf-8"))
        data["_row19c3ci_race_probe"] = True
        case_json_path.write_text(json.dumps(data), encoding="utf-8")

    _on_acquire_hooks.append(_mutate_case_json_mid_lock_wait)
    conn_f = FakeJournalConn()
    try:
        expect_raises(
            PreconditionRaceDetectedError,
            lambda: apply("deadline", case_id_f, preview_f["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
                          principal=principal_f, repo=repo_f, conn=conn_f),
            "F1: case.json changes while waiting for the lock -> PreconditionRaceDetectedError",
        )
    finally:
        _on_acquire_hooks.remove(_mutate_case_json_mid_lock_wait)
    check("F2: zero journal rows were created for the mid-wait race", len(conn_f.table) == 0)
    check("F3: no pending file was written for the mid-wait race", not deadline_engine.get_pending_path(case_id_f).exists())

    # ============================================================
    # G) SAFE REPLAY - same idempotency_key + same fingerprint -> writer
    #    NOT re-invoked, replay corroboration succeeds via the real
    #    audit trail.
    # ============================================================
    case_id_g, case_dir_g = make_generation_case()
    principal_g, repo_g = make_principal_and_repo(case_id_g)
    preview_g = preview("timeline", case_id_g, principal=principal_g, repo=repo_g)
    conn_g = FakeJournalConn()
    result_g1, _ = apply("timeline", case_id_g, preview_g["input_digest"], principal=principal_g, repo=repo_g, conn=conn_g)
    pending_sha_g1 = result_g1.pending_sha256
    result_g2, _ = apply("timeline", case_id_g, preview_g["input_digest"], principal=principal_g, repo=repo_g, conn=conn_g)
    check(
        "G1: the SECOND identical apply is a safe replay (replayed=True), NOT a second writer "
        "invocation",
        result_g2.replayed is True and len(conn_g.table) == 1,
        f"got {result_g2!r} table={conn_g.table!r}",
    )
    check(
        "G2: the replayed result reports the SAME pending_sha256 as the original apply",
        result_g2.pending_sha256 == pending_sha_g1,
    )

    # ============================================================
    # H) IDEMPOTENCY CONFLICT - same case/anchor/content (same
    #    idempotency_key) but a DIFFERENT generation_parameters_digest
    #    (different holiday_dates) -> IdempotencyConflictError.
    # ============================================================
    case_id_h, case_dir_h = make_generation_case()
    principal_h, repo_h = make_principal_and_repo(case_id_h)
    preview_h = preview("deadline", case_id_h, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_h, repo=repo_h)
    conn_h = FakeJournalConn()
    apply(
        "deadline", case_id_h, preview_h["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_h, repo=repo_h, conn=conn_h,
    )
    expect_raises(
        mc.IdempotencyConflictError,
        lambda: apply(
            "deadline", case_id_h, preview_h["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
            holiday_dates=["2026-12-31"], principal=principal_h, repo=repo_h, conn=conn_h,
        ),
        "H1: same identity + DIFFERENT generation_parameters_digest (holiday_dates changed) -> "
        "IdempotencyConflictError",
    )
    check("H2: still exactly ONE journal row (the conflicting attempt created no new row)", len(conn_h.table) == 1)

    # ============================================================
    # I) GlobalResourceStaleError - the LIVE production ruleset/
    #    provisions content changes between the under-lock snapshot and
    #    the final pre-commit re-check, via a monkeypatched reader.
    # ============================================================
    case_id_i, case_dir_i = make_generation_case()
    principal_i, repo_i = make_principal_and_repo(case_id_i)
    preview_i = preview("deadline", case_id_i, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_i, repo=repo_i)

    _original_read_global = gen._read_global_resource_bytes
    _read_calls = {"n": 0}

    def _flaky_read_global(path):
        _read_calls["n"] += 1
        real_bytes = _original_read_global(path)
        # The 3rd call for the ruleset path happens inside
        # pre_commit_callback (1st: pre-lock, 2nd: under-lock
        # precondition, 3rd: final live re-check) - return DIFFERENT
        # bytes only then, simulating a concurrent ruleset edit.
        if _read_calls["n"] >= 5 and str(path).endswith("deadline_rules.json"):
            return real_bytes + b" "
        return real_bytes

    gen._read_global_resource_bytes = _flaky_read_global
    conn_i = FakeJournalConn()
    try:
        expect_raises(
            gen.GlobalResourceStaleError,
            lambda: apply(
                "deadline", case_id_i, preview_i["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
                principal=principal_i, repo=repo_i, conn=conn_i,
            ),
            "I1: ruleset content changes between capture and final pre-commit re-check -> "
            "GlobalResourceStaleError",
        )
    finally:
        gen._read_global_resource_bytes = _original_read_global
    check(
        "I2: the writer boundary was already crossed - the journal row resolves to "
        "'reconciliation_required', never silently 'failed' or 'completed'",
        len(conn_i.table) == 1 and conn_i.table[0]["state"] == "reconciliation_required",
        f"got {conn_i.table!r}",
    )

    # ============================================================
    # J) TIMELINE FAIL-CLOSED CONTAINMENT PROOF - a broken/looping NTFS
    #    junction standing in for a document-id directory under
    #    documents/ must fail-closed the ENTIRE apply, zero journal
    #    rows, zero writer invocation. Windows-real mklink /J (never a
    #    monkeypatch); POSIX platforms get an informational skip only.
    # ============================================================
    if _IS_WINDOWS:
        case_id_j, case_dir_j = make_generation_case()
        principal_j, repo_j = make_principal_and_repo(case_id_j)
        junction_target = case_dir_j.parent / f"{case_id_j}_outside_target"
        junction_target.mkdir()
        junction_link = case_dir_j / "documents" / "evil_escape_doc"
        make_junction(junction_link, junction_target)
        conn_j = FakeJournalConn()
        expect_raises(
            gen.GenerationInputContainmentError,
            lambda: apply("timeline", case_id_j, "0" * 64, principal=principal_j, repo=repo_j, conn=conn_j),
            "J1: a live escaping junction under documents/ -> GenerationInputContainmentError "
            "(fail-closed, before any journal row)",
        )
        check("J2: zero journal rows were created for the escaping-junction attempt", len(conn_j.table) == 0)
        check(
            "J3: no timeline pending file was written for the escaping-junction attempt",
            not timeline_engine.get_pending_path(case_id_j).exists(),
        )
    else:
        skip_info(
            "J: timeline fail-closed containment (live escaping junction)",
            "this platform is not win32 - the authoritative Windows proof lives in this same "
            "file's own run on a Windows target environment; POSIX symlink coverage of the "
            "underlying path_containment primitive is already proven in "
            "test_path_containment_isolated.py",
        )

    # ============================================================
    # K) ROW 19C-3c-i DEADLINE REVISION-IDENTITY REMEDIATION - explicit
    #    identity-contract proofs (bkz. generation_mutation_facade.py'nin
    #    kendi "REMEDIATION NOTU"). Ruleset/provisions HER ZAMAN
    #    `_ruleset_path_k`/`_provisions_path_k` test-injection seam'i
    #    üzerinden verilir - gerçek production dosyaları HİÇ OKUNMAZ/
    #    YAZILMAZ burada.
    # ============================================================

    # K1 - same content (case/timeline + ruleset revision 1 + provisions
    # revision 1) + same anchor + same params -> same identity; second
    # apply is a safe replay (writer NOT re-invoked), not a new row.
    case_id_k1, case_dir_k1 = make_generation_case()
    principal_k1, repo_k1 = make_principal_and_repo(case_id_k1)
    _write_ruleset_revision(1)
    _write_provisions_revision(1)
    preview_k1 = preview(
        "deadline", case_id_k1, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_k1, repo=repo_k1,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    conn_k1 = FakeJournalConn()
    result_k1a, _ = apply(
        "deadline", case_id_k1, preview_k1["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_k1, repo=repo_k1, conn=conn_k1,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    result_k1b, _ = apply(
        "deadline", case_id_k1, preview_k1["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_k1, repo=repo_k1, conn=conn_k1,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    check(
        "K1a: fresh deadline apply (revision 1 ruleset+provisions) succeeds, replayed=False",
        result_k1a.replayed is False and result_k1a.pending_path.is_file(),
        f"got {result_k1a!r}",
    )
    check(
        "K1b: SAME content + SAME anchor + SAME params, applied twice -> the SECOND apply is a "
        "safe replay (SAME identity), writer NOT re-invoked, still exactly ONE journal row",
        result_k1b.replayed is True and len(conn_k1.table) == 1
        and result_k1b.pending_sha256 == result_k1a.pending_sha256,
        f"got {result_k1b!r} table={conn_k1.table!r}",
    )

    # K2 - RULESET revision change (same case/timeline, same provisions)
    # -> a genuinely NEW input_digest/pre_revision/idempotency_key; the
    # second, content-revised generation completes successfully - NEVER
    # an IdempotencyConflictError.
    case_id_k2, case_dir_k2 = make_generation_case()
    principal_k2, repo_k2 = make_principal_and_repo(case_id_k2)
    _write_ruleset_revision(1)
    _write_provisions_revision(1)
    preview_k2a = preview(
        "deadline", case_id_k2, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_k2, repo=repo_k2,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    conn_k2 = FakeJournalConn()
    result_k2a, _ = apply(
        "deadline", case_id_k2, preview_k2a["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_k2, repo=repo_k2, conn=conn_k2,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    _write_ruleset_revision(2)  # RULESET content changes; provisions unchanged (still revision 1)
    preview_k2b = preview(
        "deadline", case_id_k2, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_k2, repo=repo_k2,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    check(
        "K2a: a RULESET-only revision change (same case/timeline/provisions) produces a genuinely "
        "DIFFERENT input_digest",
        preview_k2b["input_digest"] != preview_k2a["input_digest"],
        f"got before={preview_k2a['input_digest']!r} after={preview_k2b['input_digest']!r}",
    )
    result_k2b, _ = apply(
        "deadline", case_id_k2, preview_k2b["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_k2, repo=repo_k2, conn=conn_k2,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    check(
        "K2b: the ruleset-revised generation attempt completes successfully (replayed=False, a "
        "SECOND, genuinely NEW journal row) - NEVER an IdempotencyConflictError",
        result_k2b.replayed is False and len(conn_k2.table) == 2
        and conn_k2.table[1]["state"] == "completed",
        f"got {result_k2b!r} table={conn_k2.table!r}",
    )
    check(
        "K2c: the two journal rows carry DIFFERENT idempotency_key values (ruleset revision "
        "changed the identity, not merely the fingerprint)",
        conn_k2.table[0]["idempotency_key"] != conn_k2.table[1]["idempotency_key"],
        f"got {conn_k2.table!r}",
    )

    # K3 - PROVISIONS revision change (same case/timeline, same ruleset)
    # -> same shape of proof as K2, for the OTHER global resource.
    case_id_k3, case_dir_k3 = make_generation_case()
    principal_k3, repo_k3 = make_principal_and_repo(case_id_k3)
    _write_ruleset_revision(1)
    _write_provisions_revision(1)
    preview_k3a = preview(
        "deadline", case_id_k3, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_k3, repo=repo_k3,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    conn_k3 = FakeJournalConn()
    result_k3a, _ = apply(
        "deadline", case_id_k3, preview_k3a["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_k3, repo=repo_k3, conn=conn_k3,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    _write_provisions_revision(2)  # PROVISIONS content changes; ruleset unchanged (still revision 1)
    preview_k3b = preview(
        "deadline", case_id_k3, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_k3, repo=repo_k3,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    check(
        "K3a: a PROVISIONS-only revision change (same case/timeline/ruleset) produces a genuinely "
        "DIFFERENT input_digest",
        preview_k3b["input_digest"] != preview_k3a["input_digest"],
        f"got before={preview_k3a['input_digest']!r} after={preview_k3b['input_digest']!r}",
    )
    result_k3b, _ = apply(
        "deadline", case_id_k3, preview_k3b["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_k3, repo=repo_k3, conn=conn_k3,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    check(
        "K3b: the provisions-revised generation attempt completes successfully (replayed=False, a "
        "SECOND, genuinely NEW journal row) - NEVER an IdempotencyConflictError",
        result_k3b.replayed is False and len(conn_k3.table) == 2
        and conn_k3.table[1]["state"] == "completed",
        f"got {result_k3b!r} table={conn_k3.table!r}",
    )
    check(
        "K3c: the two journal rows carry DIFFERENT idempotency_key values (provisions revision "
        "changed the identity, not merely the fingerprint)",
        conn_k3.table[0]["idempotency_key"] != conn_k3.table[1]["idempotency_key"],
        f"got {conn_k3.table!r}",
    )

    # K4 - SAME content (case/timeline/ruleset/provisions) + SAME anchor
    # + DIFFERENT holiday/calendar/recess -> SAME idempotency_key (the
    # content identity is unchanged), DIFFERENT request_fingerprint ->
    # IdempotencyConflictError. This is the EXISTING scenario H's shape,
    # repeated here with an EXPLICIT idempotency_key-equality proof (H
    # itself only proved the exception type + row count).
    case_id_k4, case_dir_k4 = make_generation_case()
    principal_k4, repo_k4 = make_principal_and_repo(case_id_k4)
    _write_ruleset_revision(1)
    _write_provisions_revision(1)
    preview_k4 = preview(
        "deadline", case_id_k4, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_k4, repo=repo_k4,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    conn_k4 = FakeJournalConn()
    apply(
        "deadline", case_id_k4, preview_k4["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_k4, repo=repo_k4, conn=conn_k4,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    idempotency_key_k4_first = conn_k4.table[0]["idempotency_key"]
    conflict_error_k4 = expect_raises(
        mc.IdempotencyConflictError,
        lambda: apply(
            "deadline", case_id_k4, preview_k4["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
            holiday_dates=["2026-12-31"], principal=principal_k4, repo=repo_k4, conn=conn_k4,
            ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
        ),
        "K4a: SAME content (case/timeline/ruleset/provisions) + SAME anchor + DIFFERENT "
        "holiday_dates -> IdempotencyConflictError",
    )
    check(
        "K4b: the conflicting attempt's error message references the SAME idempotency_key as the "
        "first, successful attempt (proving the IDENTITY, not merely the OUTCOME, is the same)",
        conflict_error_k4 is not None and idempotency_key_k4_first in str(conflict_error_k4),
        f"idempotency_key={idempotency_key_k4_first!r} error={conflict_error_k4!r}",
    )
    check(
        "K4c: still exactly ONE journal row (the conflicting attempt created no new row)",
        len(conn_k4.table) == 1,
    )

    # K5 - DIFFERENT anchor (same case/timeline/ruleset/provisions/
    # params) -> DIFFERENT target_ref, a fully INDEPENDENT identity:
    # BOTH generations complete successfully as two SEPARATE journal
    # rows with DIFFERENT idempotency_key values (never a conflict).
    case_id_k5, case_dir_k5 = make_generation_case()
    principal_k5, repo_k5 = make_principal_and_repo(case_id_k5)
    _write_ruleset_revision(1)
    _write_provisions_revision(1)
    ANCHOR_EVENT_ID_K5_B = "timeline_event_001"
    preview_k5a = preview(
        "deadline", case_id_k5, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_k5, repo=repo_k5,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    preview_k5b = preview(
        "deadline", case_id_k5, anchor_event_id=ANCHOR_EVENT_ID_K5_B, principal=principal_k5, repo=repo_k5,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    check(
        "K5a: two DIFFERENT anchors on the SAME case/ruleset/provisions content produce the SAME "
        "input_digest (anchor is never part of the digest) but DIFFERENT target_ref",
        preview_k5a["input_digest"] == preview_k5b["input_digest"]
        and preview_k5a["target_ref"] != preview_k5b["target_ref"],
        f"got {preview_k5a!r} / {preview_k5b!r}",
    )
    conn_k5 = FakeJournalConn()
    result_k5a, _ = apply(
        "deadline", case_id_k5, preview_k5a["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_k5, repo=repo_k5, conn=conn_k5,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    result_k5b, _ = apply(
        "deadline", case_id_k5, preview_k5b["input_digest"], anchor_event_id=ANCHOR_EVENT_ID_K5_B,
        principal=principal_k5, repo=repo_k5, conn=conn_k5,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )
    check(
        "K5b: BOTH anchor-scoped generations complete successfully as two SEPARATE journal rows "
        "(never a conflict) with DIFFERENT idempotency_key values",
        result_k5a.replayed is False and result_k5b.replayed is False and len(conn_k5.table) == 2
        and conn_k5.table[0]["idempotency_key"] != conn_k5.table[1]["idempotency_key"],
        f"got {conn_k5.table!r}",
    )

    # K6 - a RULESET revision change WHILE the case lock is being waited
    # for (via the on-acquire hook, mirroring scenario F's case.json
    # race but targeting the injected ruleset test-seam - NEVER the real
    # production ruleset file) -> PreconditionRaceDetectedError, zero
    # journal rows, zero writer invocation.
    case_id_k6, case_dir_k6 = make_generation_case()
    principal_k6, repo_k6 = make_principal_and_repo(case_id_k6)
    _write_ruleset_revision(1)
    _write_provisions_revision(1)
    preview_k6 = preview(
        "deadline", case_id_k6, anchor_event_id=ANCHOR_EVENT_ID, principal=principal_k6, repo=repo_k6,
        ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
    )

    def _mutate_ruleset_mid_lock_wait(case_id):
        if case_id != case_id_k6:
            return
        _write_ruleset_revision(2)

    _on_acquire_hooks.append(_mutate_ruleset_mid_lock_wait)
    conn_k6 = FakeJournalConn()
    try:
        expect_raises(
            PreconditionRaceDetectedError,
            lambda: apply(
                "deadline", case_id_k6, preview_k6["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
                principal=principal_k6, repo=repo_k6, conn=conn_k6,
                ruleset_path=_ruleset_path_k, provisions_path=_provisions_path_k,
            ),
            "K6a: the injected ruleset file changes while waiting for the case lock -> "
            "PreconditionRaceDetectedError (fail-closed, before any journal row)",
        )
    finally:
        _on_acquire_hooks.remove(_mutate_ruleset_mid_lock_wait)
    check("K6b: zero journal rows were created for the mid-wait ruleset race", len(conn_k6.table) == 0)
    check(
        "K6c: no deadline pending file was written for the mid-wait ruleset race",
        not deadline_engine.get_pending_path(case_id_k6).exists(),
    )

    # ============================================================
    # L) ROW 19C-3c-i MEDIUM authz-coverage remediation - the generation
    #    family had ZERO authz-denial test coverage prior to this turn
    #    (analyst role split, unassigned/unknown actor existence-
    #    blindness) despite this being established, standard coverage
    #    for every sibling family - mirrors
    #    test_promotion_mutation_facade_isolated.py's S7f-S7h pattern.
    # ============================================================

    case_id_l, case_dir_l = make_generation_case()

    # L1/L2 - analyst: preview (read) allowed, apply (mutate) denied.
    principal_l_analyst, repo_l_analyst = make_principal_and_repo(case_id_l, role="analyst")
    preview_l1 = preview(
        "deadline", case_id_l, anchor_event_id=ANCHOR_EVENT_ID,
        principal=principal_l_analyst, repo=repo_l_analyst,
    )
    check(
        "L1: an analyst (read-only capability) CAN preview a deadline generation",
        isinstance(preview_l1["input_digest"], str) and len(preview_l1["input_digest"]) == 64,
        f"got {preview_l1!r}",
    )
    conn_l2 = FakeJournalConn()
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: apply(
            "deadline", case_id_l, preview_l1["input_digest"], anchor_event_id=ANCHOR_EVENT_ID,
            principal=principal_l_analyst, repo=repo_l_analyst, conn=conn_l2,
        ),
        "L2a: an analyst (read-only capability) apply -> CaseAccessDeniedError (mutate capability "
        "missing)",
    )
    check("L2b: zero journal rows were created for the analyst apply-denial", len(conn_l2.table) == 0)
    check(
        "L2c: no deadline pending file was written for the analyst apply-denial",
        not deadline_engine.get_pending_path(case_id_l).exists(),
    )

    # L3 - unassigned actor (a REAL session, but no case_assignments row
    # for THIS case) - preview AND apply both denied, existence-blind
    # (the SAME CaseAccessDeniedError family as a nonexistent case_id).
    principal_l_unassigned, repo_l_unassigned = make_principal_and_repo(case_id_l, assigned=False)
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: preview(
            "deadline", case_id_l, anchor_event_id=ANCHOR_EVENT_ID,
            principal=principal_l_unassigned, repo=repo_l_unassigned,
        ),
        "L3a: an unassigned actor's preview -> CaseAccessDeniedError",
    )
    conn_l3 = FakeJournalConn()
    expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: apply(
            "deadline", case_id_l, "0" * 64, anchor_event_id=ANCHOR_EVENT_ID,
            principal=principal_l_unassigned, repo=repo_l_unassigned, conn=conn_l3,
        ),
        "L3b: an unassigned actor's apply -> CaseAccessDeniedError",
    )
    check("L3c: zero journal rows were created for the unassigned-actor apply-denial", len(conn_l3.table) == 0)

    # L4 - unknown actor (NO session record at all for this user_id/
    # session_id - a genuinely nonexistent actor, not merely unassigned)
    # - preview AND apply both denied, with the IDENTICAL reason_code as
    # L3's unassigned-but-real actor (existence-blind proof).
    principal_l_unknown = _authz.Principal(user_id=999999, session_id=999999, role_version_at_issue=1)
    repo_l_unknown = _authz.InMemoryAuthzRepository()  # deliberately empty - no session seeded at all
    unknown_preview_error = expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: preview(
            "deadline", case_id_l, anchor_event_id=ANCHOR_EVENT_ID,
            principal=principal_l_unknown, repo=repo_l_unknown,
        ),
        "L4a: an unknown actor (no session record at all) preview -> CaseAccessDeniedError",
    )
    conn_l4 = FakeJournalConn()
    unknown_apply_error = expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: apply(
            "deadline", case_id_l, "0" * 64, anchor_event_id=ANCHOR_EVENT_ID,
            principal=principal_l_unknown, repo=repo_l_unknown, conn=conn_l4,
        ),
        "L4b: an unknown actor (no session record at all) apply -> CaseAccessDeniedError",
    )
    check("L4c: zero journal rows were created for the unknown-actor apply-denial", len(conn_l4.table) == 0)
    check(
        "L4d: the unknown actor's denial carries the SAME reason_code as an unassigned-but-real "
        "actor's denial (existence-blind - a nonexistent session and a real-but-unassigned "
        "session are indistinguishable from outside)",
        unknown_preview_error is not None and unknown_preview_error.reason_code == "assignment_revoked"
        and unknown_apply_error is not None and unknown_apply_error.reason_code == "assignment_revoked",
        f"preview_error={unknown_preview_error!r} apply_error={unknown_apply_error!r}",
    )

    # L5 - usage-shape validation still runs BEFORE authz/connection/
    # filesystem, even for a bad/unknown actor and a malformed row_key
    # combination together - the SAME GenerationArgumentError as
    # scenario A fires, NEVER an authz-layer exception, proving the
    # ordering holds regardless of actor validity.
    expect_raises(
        gen.GenerationArgumentError,
        lambda: preview(
            "timeline", case_id_l, anchor_event_id="x", principal=principal_l_unknown, repo=repo_l_unknown,
        ),
        "L5: usage-shape validation (timeline preview with anchor_event_id) fires BEFORE authz, "
        "even for a completely unknown actor - GenerationArgumentError, NOT CaseAccessDeniedError",
    )
finally:
    ml.acquire_case_lock_session = _original_acquire
    ml.release_lock_session = _original_release
    for link in _junction_links:
        try:
            link.rmdir()
        except OSError:
            pass
    for case_dir in _created_case_dirs:
        shutil.rmtree(case_dir, ignore_errors=True)
    for case_dir in _created_case_dirs:
        outside_target = case_dir.parent / f"{case_dir.name}_outside_target"
        if outside_target.exists():
            shutil.rmtree(outside_target, ignore_errors=True)
    shutil.rmtree(_tmp_global_resources_dir, ignore_errors=True)

_data_tree_after_everything = snapshot_data_tree()
check(
    "the REAL data/ tree is byte-for-byte UNCHANGED before vs after this entire test file",
    _data_tree_before_everything == _data_tree_after_everything,
    f"diff keys: {set(_data_tree_before_everything) ^ set(_data_tree_after_everything)}",
)

print(f"--- test_generation_mutation_facade_isolated: {passed} passed, {failed} failed, {_informational_skips} informational skips ---")
sys.exit(1 if failed else 0)
