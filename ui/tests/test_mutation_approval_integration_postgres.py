# ============================================================
# Row 19C-2a - REAL, END-TO-END PostgreSQL INTEGRATION PROOF for the
# PRODUCTION case-scoped approval mutation path.
#
# WHAT IS REAL HERE (and why this file exists separately from every
# other test in this directory)
# ----------------------------------------------------------------
# `ui/tests/test_mutation_approval_facade_isolated.py` proves this
# project's OWN ordering/gating/binding LOGIC against an in-memory fake
# journal connection, a fake lock and a fake approval-family module.
# `ui/tests/test_mutation_journal_postgres.py` proves the coordinator's
# journal state machine against a real database, but with FAKE writer
# callbacks. NEITHER of them can prove the thing this file exists for:
# that the WHOLE PRODUCTION STACK, wired together exactly as
# `ui/main.py`'s confirm route wires it, actually works - and actually
# fails closed - against a real PostgreSQL server and a real approval
# writer that really rewrites a real canonical artefact on disk.
#
# Every one of these is the GENUINE production object here, NOT a fake:
#   - `ui.services.mutation_approval_facade.approve_case_scoped_mutation()`
#     - the real production facade, called exactly as
#     `ui.services.approval_registry.case_scoped_approve()` calls it;
#   - `ui.services.mutation_lock.acquire_case_lock_session()` /
#     `release_lock_session()` - the REAL session-level
#     `pg_advisory_lock`/`pg_advisory_unlock`, never monkeypatched
#     anywhere in this file (this is what makes the two-connection
#     blocking proof below meaningful at all);
#   - `ui.services.mutation_coordinator.run_mutation()` - the real
#     coordinator, against the real `mutation.mutation_journal` table;
#   - `ui.services.mutation_registry.reconcile_and_apply_journal_entry()`
#     and the REAL production adapter registry from
#     `ui.services.mutation_approval_adapters.build_production_registry()`
#     (all 10 families) - never a test-only adapter;
#   - `src/deadline_approval.py`'s REAL `run_approve()` - a real Row 8
#     approval writer, running its real validator, real backup, real
#     atomic canonical write, real post-write validation, real SHA256
#     equality check and real approval-audit record;
#   - `psycopg` - the real production driver
#     (`ui.services.db.get_session_lock_connection()`'s own driver).
#     This file has NO `psql`-subprocess shim fallback of any kind: if
#     `psycopg` is not importable, this file SKIPS loudly rather than
#     silently proving something weaker through a substitute harness.
#
# WHAT IS NOT REAL, AND EXACTLY WHY (stated plainly rather than
# implied)
# ----------------------------------------------------------------
#   1. IAM/authz: `authz_repository=` is an `authz.InMemoryAuthzRepository`
#      (this file's subject is MUTATION INTEGRITY, not Row 19B's IAM
#      persistence, which `ui/tests/test_iam_migrations_isolated.py`
#      and `ui/tests/test_authz_isolated.py` already cover against a
#      real database). `authz_repository=` is a REAL production
#      parameter of `approve_case_scoped_mutation()`, not a test-only
#      hook, and the REAL `authz.authorize_case_access()` function -
#      including the REAL `paths.resolve_case_id()` filesystem
#      containment choke point - runs unmodified against it, twice per
#      approval (outer + inner).
#   2. The case tree: a REAL copy of this repository's real
#      `data/cases/case_0001` tree, re-identified per scenario (see
#      `make_case()`), living under a fresh `tempfile.mkdtemp()`. The
#      content is genuinely valid domain data - that is exactly why the
#      real `deadline_approval` validator accepts it - but this file
#      NEVER reads, writes or even lists this repository's own real
#      `data/` tree during a scenario, and proves that at the end
#      (`REAL data/ tree byte-integrity`).
#   3. Two deliberately-injected FAULTS, at two precisely-named
#      boundaries, for the failure-classification scenarios that cannot
#      otherwise be reached deterministically:
#        (a) `_writer_fault` - a PASS-THROUGH wrapper around the real
#            `deadline_approval.run_approve`. With no fault requested it
#            calls the genuine function and nothing else; a scenario may
#            ask it to raise BEFORE calling through (nothing happened)
#            or AFTER the genuine call fully completed (the real
#            canonical write and real audit record DID happen, and the
#            call then failed to return cleanly - i.e. exactly the
#            "process/IO fault after a successful writer" case
#            `run_mutation()`'s `reconciliation_required` classification
#            exists for). It also COUNTS invocations, which is how
#            "the writer ran exactly once" is proven.
#        (b) `install_delete_after()` - a PASS-THROUGH wrapper around
#            `mutation_coordinator._insert_prepared` /
#            `_mark_executing` that runs the genuine statement and then
#            DELETEs that journal row through a SECOND real connection.
#            The resulting rowcount failure in the real, unmodified
#            `_mark_executing`/`_mark_completed` UPDATE is therefore a
#            GENUINE real-database rowcount-0 outcome, not a stubbed
#            return value.
#
#      EXACT LIFETIMES (corrected - an earlier version of this comment
#      claimed both wrappers were "installed per scenario and removed
#      immediately after", and that non-fault scenarios ran "the
#      completely unwrapped production path". That was wrong for (a)
#      and is stated accurately here instead):
#        - (a) `deadline_approval.run_approve` is replaced ONCE, at
#          module import, and restored ONLY in this file's final
#          `finally` (see the `_REAL_RUN_APPROVE` assignment and the
#          teardown assertion). EVERY scenario therefore runs THROUGH
#          the wrapper, including the happy path. What varies per
#          scenario is only the `writer_state["fault"]` FLAG; with it
#          set to `None` the wrapper's entire behavior is
#          `writer_state` bookkeeping plus an unconditional call to the
#          genuine `_REAL_RUN_APPROVE(...)` with the same arguments, so
#          the production code path executed is identical - but it is a
#          pass-through, not an absence of a wrapper.
#        - (b) IS genuinely installed and restored per scenario, inside
#          a `try/finally` (`install_delete_after(...)` /
#          `restore_coordinator_internals()`), and the teardown asserts
#          both coordinator internals are the genuine functions again.
#        - `facade._compute_precondition_snapshot` is likewise wrapped
#          per scenario (scenario 4 only) as a counting pass-through and
#          restored in that scenario's own `finally`.
#
# SETUP (opt-in, never silently skipped):
#   VERGI_TEST_PG_DSN=<the NAME of a disposable database with
#                      db/migrations/0001+0002+0003+0004 applied>
#   plus the ordinary libpq environment (PGHOST/PGPORT/PGUSER/
#   PGPASSWORD) this process already has - exactly the same convention
#   ui/tests/test_mutation_journal_postgres.py already uses (that file
#   passes this value as psycopg's `dbname=`, not as a URI; this file
#   does the same so one environment configures both).
#
# Run: python -m ui.tests.test_mutation_approval_integration_postgres
# ============================================================

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

passed = 0
failed = 0
skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def skip(label, detail=""):
    global skipped
    skipped += 1
    print(f"SKIPPED {label} - {detail}")


def expect_raises(exc_type, fn, label, detail=""):
    """Returns the caught exception (or None) so a scenario can assert
    on its attributes as well as its type."""
    try:
        fn()
    except exc_type as error:
        check(label, True)
        return error
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")
    return None


def summarize_and_exit():
    print(
        f"--- test_mutation_approval_integration_postgres: {passed} passed, "
        f"{failed} failed, {skipped} skipped ---"
    )
    sys.exit(1 if failed else 0)


# ----------------------------------------------------------------
# Opt-in gating. BOTH conditions are hard requirements - neither is
# ever worked around with a substitute harness (see this file's own
# header comment).
# ----------------------------------------------------------------

PG_DB = os.environ.get("VERGI_TEST_PG_DSN")

if not PG_DB:
    skip(
        "the entire real-PostgreSQL approval integration suite",
        "VERGI_TEST_PG_DSN is not set (no disposable database with migrations "
        "0001+0002+0003+0004 applied is configured for this run). NOT EXECUTED, not a pass",
    )
    summarize_and_exit()

try:
    import psycopg
except Exception as _psycopg_error:  # pragma: no cover - environment-dependent
    skip(
        "the entire real-PostgreSQL approval integration suite",
        "VERGI_TEST_PG_DSN is set but `import psycopg` failed "
        f"({_psycopg_error!r}). This file deliberately has NO psql-subprocess fallback: "
        "the production driver itself is part of what is under test here. NOT EXECUTED, not a pass",
    )
    summarize_and_exit()


from ui.services import authz as _authz                                  # noqa: E402
from ui.services import mutation_approval_adapters as _adapters          # noqa: E402
from ui.services import mutation_approval_facade as facade               # noqa: E402
from ui.services import mutation_coordinator as mutcoord                 # noqa: E402
from ui.services import mutation_lock as _mutation_lock                  # noqa: E402
from ui.services import mutation_registry as mr                          # noqa: E402
from ui.services import paths as _paths                                  # noqa: E402
from ui.services.common import PreconditionRaceDetectedError, StaleViewError, sha256_file  # noqa: E402

import deadline_approval                                                  # noqa: E402
import deadline_validator as _deadline_validator                          # noqa: E402
# ROW 19C-3a SLICE 2 REAL-POSTGRES PATH-PROOF REMEDIATION: `argument_
# approval` is imported here - BEFORE `discover_cases_dir_holders()`
# runs below - purely so scenario A2's carry-forward escape (only the 4
# families with a `get_carry_forward_dir()` - argument/risk_strategy/
# drafting/qa - have one) gets its OWN `CASES_DIR` genuinely swept into
# `_TMP_CASES` alongside `deadline_approval`'s, exactly like every other
# already-loaded module here. No other file/production code changes.
import argument_approval                                                  # noqa: E402
from mutation_guard import (                                              # noqa: E402
    RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
)

print(f"backend: REAL psycopg {psycopg.__version__} (production driver), dbname={PG_DB!r}")

ROW_KEY = "deadline"
ACTION_FAMILY = facade.action_family_for(ROW_KEY)


def pg_connect():
    """A REAL, autocommit, session-lock-capable connection - the same
    shape `ui.services.db.get_session_lock_connection()` returns in
    production."""
    return psycopg.connect(dbname=PG_DB, autocommit=True)


# ----------------------------------------------------------------
# Preflight: the disposable database really does carry 0003's journal
# table AND 0004's provenance columns. Fail LOUDLY (never skip, never
# pass) if not - a half-migrated database would make every scenario
# below meaningless.
# ----------------------------------------------------------------

_preflight = pg_connect()
try:
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'mutation' AND table_name IN ('mutation_journal', 'mutation_resources')"
        )
        (_table_count,) = cur.fetchone()
    check(
        "preflight: mutation.mutation_journal AND mutation.mutation_resources both exist (0002+0003 applied)",
        _table_count == 2, f"found {_table_count} of the 2 expected tables",
    )
    with _preflight.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'mutation' AND table_name = 'mutation_journal' "
            "AND column_name IN ('reconciled_by_actor_type', 'reconciled_by_actor_ref')"
        )
        (_prov_count,) = cur.fetchone()
    check(
        "preflight: 0004's two reconciliation-provenance columns exist",
        _prov_count == 2, f"found {_prov_count} of the 2 expected columns",
    )
finally:
    _preflight.close()

if failed:
    print("Preflight failed - refusing to run the integration scenarios against a half-migrated database.")
    summarize_and_exit()


# ----------------------------------------------------------------
# REAL `iam.users` rows for every actor this file uses.
#
# `mutation.mutation_journal.actor_user_id` carries a REAL FOREIGN KEY
# to `iam.users(id)` (db/migrations/0003_mutation_journal.sql) - so a
# journal row simply CANNOT be written for a user id that does not
# genuinely exist. That constraint is itself part of what this file
# proves is real: these rows are inserted with the EXACT ids the
# scenarios below use as `Principal.user_id`, so every journaled
# mutation here is attributed to a genuinely-existing IAM user, exactly
# as production requires.
#
# Deliberately id-explicit (`OVERRIDING SYSTEM VALUE`-free plain INSERT
# with an explicit id, then a sequence fix-up) rather than letting
# BIGSERIAL choose: the scenarios' `Principal(user_id=...)` values are
# what the FK must satisfy, and inventing a mapping layer between the
# two would only obscure which real user id each journal row is
# actually bound to.
# ----------------------------------------------------------------

_ACTOR_USER_IDS = (1, 2, 7, 11, 12, 21, 22, 31)

_seed = pg_connect()
try:
    with _seed.cursor() as cur:
        for _user_id in _ACTOR_USER_IDS:
            cur.execute(
                "INSERT INTO iam.users (id, display_name) VALUES (%s, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (_user_id, f"row19c2a-integration-actor-{_user_id}"),
            )
        cur.execute(
            "SELECT setval(pg_get_serial_sequence('iam.users', 'id'), "
            "GREATEST((SELECT max(id) FROM iam.users), 1))"
        )
        cur.execute(
            "SELECT count(*) FROM iam.users WHERE id = ANY(%s)",
            (list(_ACTOR_USER_IDS),),
        )
        (_seeded_count,) = cur.fetchone()
finally:
    _seed.close()

check(
    "preflight: every actor this suite uses really exists in iam.users (mutation_journal's own "
    "FOREIGN KEY to iam.users(id) is genuinely enforced here)",
    _seeded_count == len(_ACTOR_USER_IDS),
    f"seeded {_seeded_count} of {len(_ACTOR_USER_IDS)} expected actor rows",
)

if failed:
    print("Actor seeding failed - refusing to run the integration scenarios.")
    summarize_and_exit()


# ----------------------------------------------------------------
# Journal helpers - plain, direct SQL reads/writes on a REAL
# connection. Deliberately NOT routed through any project module, so
# what a scenario asserts about the journal is what the DATABASE says,
# never what this project's own code believes.
# ----------------------------------------------------------------

_JOURNAL_COLUMNS = (
    "id, resource_key, action_family, actor_user_id, actor_label, target_ref, target_state, "
    "pre_hash, pre_revision, idempotency_key, request_fingerprint, state, failure_code, "
    "resolution_code, observed_post_hash, executing_at, resolved_at, "
    "reconciled_by_actor_type, reconciled_by_actor_ref"
)


def journal_rows(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_JOURNAL_COLUMNS} FROM mutation.mutation_journal "
                "WHERE resource_key = %s ORDER BY id",
                (resource_key,),
            )
            names = [d.name for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def delete_journal_row(journal_id):
    """An OUT-OF-BAND delete through its own real connection - used only
    by `_delete_row_after` (see this file's header comment) to create a
    genuine rowcount-0 condition for the real, unmodified coordinator
    UPDATEs."""
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mutation.mutation_journal WHERE id = %s", (journal_id,))
    finally:
        conn.close()


def advisory_lock_id_for(resource_key):
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT advisory_lock_id FROM mutation.mutation_resources WHERE resource_key = %s",
                (resource_key,),
            )
            row = cur.fetchone()
            return None if row is None else row[0]
    finally:
        conn.close()


def lock_is_held_by_anyone(advisory_lock_id):
    """Reads PostgreSQL's OWN `pg_locks` view - the server's account of
    which advisory locks are actually granted right now, not this
    project's belief about it.

    `advisory_lock_id is None` means `mutation.mutation_resources` has
    no row for that resource_key at all, i.e. the lock was never even
    requested (which is itself the correct answer to "is anything
    holding it": no). This is the normal state after an OUTER authz
    denial, which returns before `acquire_case_lock_session()` - the
    function that would have get-or-created that row - is ever reached.

    A `pg_advisory_lock(bigint)` key is split by the server into
    `classid` (high 32 bits) and `objid` (low 32 bits); both halves are
    matched here rather than `objid` alone, so this can never report a
    different resource's lock as this one's."""
    return _count_advisory_locks(advisory_lock_id, granted=True) > 0


def _count_advisory_locks(advisory_lock_id, *, granted):
    if advisory_lock_id is None:
        return 0
    conn = pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND classid = %s AND objid = %s AND granted = %s",
                ((advisory_lock_id >> 32) & 0xFFFFFFFF, advisory_lock_id & 0xFFFFFFFF, granted),
            )
            (count,) = cur.fetchone()
            return count
    finally:
        conn.close()


def wait_for_lock_waiter(advisory_lock_id, *, timeout_seconds=30.0, poll_seconds=0.1):
    """Blocks until PostgreSQL's OWN `pg_locks` view reports at least
    one NOT-granted (i.e. genuinely WAITING) advisory lock on
    `advisory_lock_id`, or the timeout expires. Returns True if a real
    waiter was observed.

    ROW 19C-2a FINAL AUDIT REMEDIATION: this replaces inferring
    "blocked" from `time.sleep(...) + thread.is_alive()` alone. That
    inference could pass VACUOUSLY on a pathologically slow machine -
    a thread that had not yet even reached the lock is also "still
    alive" and has also "written nothing to the journal". Asking the
    SERVER whether a waiter exists turns the claim into an observed
    fact: a NOT-granted advisory lock row for this exact lock id can
    only exist because some session is really queued behind the holder.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _count_advisory_locks(advisory_lock_id, granted=False) > 0:
            return True
        time.sleep(poll_seconds)
    return False


def make_directory_escape_link(link_path: Path, target_path: Path) -> None:
    """ROW 19C-3a SLICE 2 REAL-POSTGRES PATH-PROOF REMEDIATION: a REAL,
    platform-native directory-escape link - NTFS junction via
    `mklink /J` on Windows (needs neither elevation nor Developer Mode),
    a real POSIX symlink elsewhere - mirroring `ui/tests/
    test_reconciliation_isolated.py`'s own identically-purposed
    `_dr_make_directory_escape_link()` helper (an independent copy, this
    file's own test-only utility, never shared/imported). A failed link
    creation raises - never silently treated as a skip or a pass."""
    if sys.platform == "win32":
        # `capture_output=True, text=True` would decode stdout/stderr
        # using the console's own (here: Turkish, cp1254) codepage - a
        # genuine `mklink` failure can emit a localized error message
        # containing a byte that codepage cannot decode, crashing the
        # reader thread with a SECOND, unrelated UnicodeDecodeError that
        # masks the real one. Captured as raw bytes and decoded with
        # `errors="replace"` instead, so any real failure's message is
        # always readable.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            stdout_text = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
            stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            raise RuntimeError(f"mklink /J failed (rc={result.returncode}): {stdout_text!r} {stderr_text!r}")
    else:
        os.symlink(str(target_path), str(link_path))


# ----------------------------------------------------------------
# Real case-tree fixtures. ONE temp cases root for the whole file, with
# a SEPARATE, independently re-identified copy of the real case_0001
# tree per scenario - so every scenario gets its own `case:<case_id>`
# lock resource and its own journal rows, and no scenario can influence
# another through either the filesystem or the journal.
#
# EVERY loaded `src/` module that carries a module-level `CASES_DIR`
# pointing at the REAL cases root is redirected here (25 of them at the
# time of writing - `deadline_approval` itself, plus the whole
# validator chain it transitively calls: `deadline_validator`,
# `timeline_validator`, ...). The redirect set is DISCOVERED, not
# hardcoded, and asserted non-empty + fully restored afterwards - this
# is exactly the "~30 files use paths.CASES_DIR directly" surface Row
# 19C-2's own opening gate names.
# ----------------------------------------------------------------

_REAL_CASES_ROOT = Path(os.path.realpath(str(_paths.CASES_DIR)))

# Import the whole production adapter registry FIRST, so every family's
# module (and its validator chain) is already loaded and therefore
# discoverable by the redirect sweep below.
PRODUCTION_REGISTRY = _adapters.build_production_registry()
check(
    "the REAL production adapter registry covers all 10 case-scoped approval families",
    len(PRODUCTION_REGISTRY.known_action_families()) == 10,
    f"got {sorted(PRODUCTION_REGISTRY.known_action_families())}",
)
check(
    "the REAL production registry has an adapter registered for this file's own action_family",
    ACTION_FAMILY in PRODUCTION_REGISTRY.known_action_families(),
)


def discover_cases_dir_holders():
    holders = []
    for module in list(sys.modules.values()):
        if getattr(module, "__file__", None) is None:
            continue
        candidate = getattr(module, "CASES_DIR", None)
        if candidate is None:
            continue
        try:
            if Path(os.path.realpath(str(candidate))) == _REAL_CASES_ROOT:
                holders.append(module)
        except Exception:
            continue
    return holders


_TMP_ROOT = Path(tempfile.mkdtemp(prefix="vergi_pgint_"))
_TMP_CASES = _TMP_ROOT / "cases"
_TMP_CASES.mkdir(parents=True)

_cases_dir_holders = discover_cases_dir_holders()
_original_cases_dirs = [(m, m.CASES_DIR) for m in _cases_dir_holders]

check(
    "the CASES_DIR redirect sweep found the real production modules to redirect "
    "(deadline_approval + its transitive validator chain)",
    len(_cases_dir_holders) >= 5
    and any(getattr(m, "__name__", "") == "deadline_approval" for m in _cases_dir_holders)
    and any(getattr(m, "__name__", "") == "deadline_validator" for m in _cases_dir_holders)
    and any(getattr(m, "__name__", "") == "ui.services.paths" for m in _cases_dir_holders),
    f"holders={sorted(getattr(m, '__name__', '?') for m in _cases_dir_holders)}",
)
print(f"redirecting CASES_DIR for {len(_cases_dir_holders)} loaded module(s) -> {_TMP_CASES}")


def snapshot_real_data_tree():
    """A byte-level manifest of this repository's real `data/` tree,
    used to prove at the end that no scenario ever touched it."""
    manifest = {}
    data_dir = Path(os.path.realpath(str(_REAL_CASES_ROOT))).parent
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            try:
                manifest[str(path)] = (path.stat().st_size, sha256_file(path))
            except OSError:
                manifest[str(path)] = ("unreadable", None)
    return manifest


_REAL_DATA_BEFORE = snapshot_real_data_tree()


# ROW 19C-2a: a per-RUN token appended to every scenario's case_id.
#
# WHY THIS IS NECESSARY, AND WHY IT IS NOT A WEAKENING OF THE TEST:
# `idempotency_key` is a deterministic function of (actor, resource_key,
# action_family, target_ref, pre_revision) - by design (see
# src/mutation_guard.py), and scenario 2 below depends on exactly that.
# `mutation.mutation_journal.idempotency_key` is also UNCONDITIONALLY
# UNIQUE across the table's ENTIRE history (0003's plain UNIQUE
# constraint, never a partial index). Put together, a SECOND run of this
# file against the SAME database would recompute the IDENTICAL
# idempotency keys as the first run and therefore find its own previous
# run's `completed`/`reconciliation_required` rows - so scenario 1's
# "fresh approval" would silently become a replay, and the gated
# scenarios would refuse before doing anything.
#
# Giving each RUN its own case_ids gives each run its own resource_keys
# and therefore its own idempotency keys - which is what makes this file
# genuinely re-runnable against a persistent disposable database rather
# than only ever correct on a pristine one. It does NOT weaken anything:
# every within-run identity/replay property (scenarios 2 and 9 in
# particular) is asserted exactly as before, because the token is fixed
# for the whole run.
RUN_TOKEN = uuid.uuid4().hex[:10]
print(f"per-run case_id token: {RUN_TOKEN}")


def make_case(base_name, *, pending_content=None):
    """A REAL, independently re-identified copy of this repository's
    real `data/cases/case_0001` tree at `<tmp>/cases/<case_id>`, where
    `case_id` is `f"{base_name}_{RUN_TOKEN}"` (see `RUN_TOKEN` above).

    Re-identification rewrites the literal `case_0001` in every text
    file's CONTENT and in every file/directory NAME, so the copy is a
    genuinely self-consistent case whose own embedded `case_id` fields
    match its directory name - which is precisely why the real
    `deadline_approval` validator chain accepts it. The real tree is
    only ever READ.

    `pending_content`, when given, REPLACES the pending deadline
    document's content after the copy - used by the writer-failure
    scenario to make the REAL validator genuinely reject it.
    """
    case_id = f"{base_name}_{RUN_TOKEN}"
    destination = _TMP_CASES / case_id
    shutil.copytree(_REAL_CASES_ROOT / "case_0001", destination)

    for path in destination.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "case_0001" in text:
            path.write_text(text.replace("case_0001", case_id), encoding="utf-8")

    for path in sorted(destination.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if "case_0001" in path.name:
            path.rename(path.with_name(path.name.replace("case_0001", case_id)))

    pending_path = deadline_approval.get_pending_path(case_id)
    canonical_path = deadline_approval.get_canonical_path(case_id)

    # Start every scenario from a clean "not yet promoted" state, so
    # the composite pre-state snapshot's canonical side is meaningful
    # and the real writer's own backup/overwrite path is exercised
    # from a known starting point.
    if canonical_path.exists():
        canonical_path.unlink()
    reviews_dir = deadline_approval.get_reviews_dir(case_id)
    if reviews_dir.is_dir():
        shutil.rmtree(reviews_dir)

    if pending_content is not None:
        pending_path.write_text(pending_content, encoding="utf-8")

    return {
        "case_id": case_id,
        "resource_key": _mutation_lock.case_resource_key(case_id),
        "pending_path": pending_path,
        "canonical_path": canonical_path,
        "expected_hash": sha256_file(pending_path),
    }


def make_principal_and_repo(case_id, *, user_id=1, session_id=100, assigned=True, role="lawyer"):
    principal = _authz.Principal(user_id=user_id, session_id=session_id, role_version_at_issue=1)
    repo = _authz.InMemoryAuthzRepository()
    repo.sessions[session_id] = _authz.SessionRecord(
        user_id=user_id, current_authz_version=1, disabled=False,
    )
    if assigned:
        repo.assignments[(user_id, case_id)] = _authz.CaseAssignmentRecord(role=role)
    return principal, repo


def latest_audit_record(case_id):
    reviews_dir = deadline_approval.get_reviews_dir(case_id)
    candidates = sorted(reviews_dir.glob("*.approval.json"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None, None
    return candidates[-1], json.loads(candidates[-1].read_text(encoding="utf-8"))


# ----------------------------------------------------------------
# The two deliberately-injected fault wrappers. See this file's header
# comment ("WHAT IS NOT REAL, AND EXACTLY WHY", item 3) - both are
# PASS-THROUGH by default and always call the genuine production
# function; a scenario opts into a fault explicitly.
# ----------------------------------------------------------------

_REAL_RUN_APPROVE = deadline_approval.run_approve
_REAL_INSERT_PREPARED = mutcoord._insert_prepared
_REAL_MARK_EXECUTING = mutcoord._mark_executing

writer_state = {"calls": 0, "fault": None}


def _writer_fault(case_id, *, mutation_idempotency_key=None, mutation_resource_key=None):
    writer_state["calls"] += 1
    writer_state["last_idempotency_key"] = mutation_idempotency_key
    writer_state["last_resource_key"] = mutation_resource_key
    fault = writer_state["fault"]
    if fault == "before":
        raise RuntimeError(
            "INJECTED FAULT (before): simulating a failure at the writer boundary before the real "
            "deadline_approval.run_approve() was called at all - nothing was written"
        )
    _REAL_RUN_APPROVE(
        case_id,
        mutation_idempotency_key=mutation_idempotency_key,
        mutation_resource_key=mutation_resource_key,
    )
    if fault == "after":
        raise RuntimeError(
            "INJECTED FAULT (after): the REAL deadline_approval.run_approve() completed in full "
            "(real canonical write + real approval audit record), and the call then failed to "
            "return cleanly - the exact process/IO-fault case run_mutation()'s "
            "'reconciliation_required' classification exists for"
        )


deadline_approval.run_approve = _writer_fault


def install_delete_after(which):
    """Wraps `_insert_prepared` (which='prepared') or `_mark_executing`
    (which='executing') so the GENUINE statement runs first and the row
    is then DELETEd through a SECOND real connection - producing a real
    rowcount-0 outcome in the next, completely unmodified coordinator
    UPDATE."""
    if which == "prepared":
        def wrapper(conn, intent, *, actor_user_id, idempotency_key, request_fingerprint):
            journal_id = _REAL_INSERT_PREPARED(
                conn, intent, actor_user_id=actor_user_id,
                idempotency_key=idempotency_key, request_fingerprint=request_fingerprint,
            )
            delete_journal_row(journal_id)
            return journal_id
        mutcoord._insert_prepared = wrapper
    elif which == "executing":
        def wrapper(conn, journal_id):
            _REAL_MARK_EXECUTING(conn, journal_id)
            delete_journal_row(journal_id)
        mutcoord._mark_executing = wrapper
    else:  # pragma: no cover
        raise AssertionError(which)


def restore_coordinator_internals():
    mutcoord._insert_prepared = _REAL_INSERT_PREPARED
    mutcoord._mark_executing = _REAL_MARK_EXECUTING


def approve(fixture, principal, repo, *, expected_hash=None):
    """Calls the REAL production facade with a REAL psycopg connection
    factory - the same call shape `approval_registry.case_scoped_approve()`
    makes in production."""
    return facade.approve_case_scoped_mutation(
        ROW_KEY, fixture["case_id"],
        fixture["expected_hash"] if expected_hash is None else expected_hash,
        principal=principal, authz_repository=repo, conn_factory=pg_connect,
    )


try:
    for _module in _cases_dir_holders:
        _module.CASES_DIR = _TMP_CASES

    # ============================================================
    # SCENARIO 1 - the production happy path, end to end, for real.
    # ============================================================

    fx1 = make_case("case_pgint_happy")
    principal1, repo1 = make_principal_and_repo(fx1["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    check(
        "scenario 1 preflight: the real case copy has a pending deadline document and NO canonical yet",
        fx1["pending_path"].exists() and not fx1["canonical_path"].exists(),
    )

    result1 = approve(fx1, principal1, repo1)

    check("scenario 1: the approval completed freshly (not a replay)", result1.replayed is False)
    check("scenario 1: the REAL writer ran exactly once", writer_state["calls"] == 1)
    check(
        "scenario 1: the REAL canonical artefact now exists on disk",
        fx1["canonical_path"].exists(),
    )
    check(
        "scenario 1: the returned canonical_hash equals the real canonical file's own sha256",
        result1.canonical_hash == sha256_file(fx1["canonical_path"]),
    )
    check(
        "scenario 1: the real writer's own stdout was captured (real CLI-style output, not empty)",
        "DEADLINE APPROVAL" in result1.stdout,
    )

    rows1 = journal_rows(fx1["resource_key"])
    check(
        "scenario 1: exactly ONE real journal row exists, in state 'completed'",
        len(rows1) == 1 and rows1[0]["state"] == "completed",
        f"rows={[(r['id'], r['state']) for r in rows1]}",
    )
    check(
        "scenario 1: the real journal row's resource_key is 'case:<case_id>'",
        rows1[0]["resource_key"] == f"case:{fx1['case_id']}",
    )
    check(
        "scenario 1: the real journal row's action_family is the production 'approval.deadline'",
        rows1[0]["action_family"] == ACTION_FAMILY,
    )
    check(
        "scenario 1: the real journal row's pre_revision is the REQUEST's own claimed expected_hash",
        rows1[0]["pre_revision"] == fx1["expected_hash"],
    )
    check(
        "scenario 1: the real journal row's pre_hash is the COMPOSITE snapshot digest, not the bare "
        "pending hash",
        rows1[0]["pre_hash"] != fx1["expected_hash"] and len(rows1[0]["pre_hash"]) == 64,
    )
    check(
        "scenario 1: the real journal row's observed_post_hash equals the real canonical file's sha256",
        rows1[0]["observed_post_hash"] == sha256_file(fx1["canonical_path"]),
    )
    check(
        "scenario 1: a coordinator-proven completion carries NO resolution_code and NO reconciliation "
        "provenance (that provenance belongs only to a RECONCILED outcome)",
        rows1[0]["resolution_code"] is None
        and rows1[0]["reconciled_by_actor_type"] is None
        and rows1[0]["reconciled_by_actor_ref"] is None,
    )
    check(
        "scenario 1: executing_at AND resolved_at are both really set on the completed row",
        rows1[0]["executing_at"] is not None and rows1[0]["resolved_at"] is not None,
    )

    # --- AUDIT BINDING, on a REAL approval audit record written by the
    #     REAL src/deadline_approval.py write_approval_audit(). ---
    audit_path1, audit1 = latest_audit_record(fx1["case_id"])
    check("scenario 1: a REAL approval audit record was written", audit_path1 is not None)
    check(
        "scenario 1 audit binding: mutation_idempotency_key matches the real journal row's own "
        "idempotency_key",
        audit1 is not None and audit1.get("mutation_idempotency_key") == rows1[0]["idempotency_key"],
    )
    check(
        "scenario 1 audit binding: mutation_resource_key matches the real journal row's own "
        "'case:<case_id>' resource_key",
        audit1 is not None and audit1.get("mutation_resource_key") == rows1[0]["resource_key"],
    )
    check(
        "scenario 1 audit binding: canonical_sha256 matches the CURRENT real canonical file's hash",
        audit1 is not None and audit1.get("canonical_sha256") == sha256_file(fx1["canonical_path"]),
    )
    check(
        "scenario 1: the real advisory lock was released again (nothing left holding it)",
        lock_is_held_by_anyone(advisory_lock_id_for(fx1["resource_key"])) is False,
    )

    # ============================================================
    # SCENARIO 2 - deterministic replay of the SAME request. The real
    # writer must total ONE invocation across both calls.
    # ============================================================

    result2 = approve(fx1, principal1, repo1)

    check("scenario 2: the retry REPLAYED (replayed=True)", result2.replayed is True)
    check(
        "scenario 2: the REAL writer still totals exactly ONE invocation across both requests",
        writer_state["calls"] == 1,
    )
    check("scenario 2: the SAME real journal row was reused", result2.journal_id == result1.journal_id)
    check(
        "scenario 2: no SECOND journal row was created in the real database",
        len(journal_rows(fx1["resource_key"])) == 1,
    )
    check(
        "scenario 2: the replay is DETERMINISTIC - same journal_id, same canonical_hash, same "
        "canonical_path as the fresh call",
        result2.journal_id == result1.journal_id
        and result2.canonical_hash == result1.canonical_hash
        and result2.canonical_path == result1.canonical_path,
    )
    check(
        "scenario 2: a third identical request replays identically again (idempotency is stable, "
        "not one-shot)",
        approve(fx1, principal1, repo1).journal_id == result1.journal_id and writer_state["calls"] == 1,
    )

    # ============================================================
    # SCENARIO 3 - TWO REAL CONNECTIONS, ONE REAL CASE LOCK. Proves
    # genuine cross-connection mutual exclusion: while connection A
    # holds `case:<case_id>` via the REAL pg_advisory_lock, a second,
    # fully independent real connection driving the REAL facade blocks
    # BEFORE writing anything to the journal - and completes only once
    # A releases.
    # ============================================================

    fx3 = make_case("case_pgint_lockblock")
    principal3, repo3 = make_principal_and_repo(fx3["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    holder_conn = pg_connect()
    holder_lock_id = _mutation_lock.acquire_case_lock_session(holder_conn, fx3["case_id"])
    check(
        "scenario 3: connection A really acquired the case lock (a real advisory_lock_id was assigned)",
        isinstance(holder_lock_id, int),
    )

    blocked_result = {}

    def run_blocked_approval():
        try:
            blocked_result["result"] = approve(fx3, principal3, repo3)
        except BaseException as error:  # recorded, re-checked on the main thread
            blocked_result["error"] = error

    worker = threading.Thread(target=run_blocked_approval, daemon=True)
    worker.start()

    # ROW 19C-2a FINAL AUDIT REMEDIATION: ask PostgreSQL itself whether
    # a real session is queued behind the holder, instead of inferring
    # it from a sleep. See `wait_for_lock_waiter()`'s own docstring for
    # why the sleep-only inference could pass vacuously.
    observed_waiter = wait_for_lock_waiter(holder_lock_id)
    check(
        "scenario 3: PostgreSQL's OWN pg_locks reports a genuinely WAITING (not granted) advisory "
        "lock on this case - server-observed proof of blocking, not a timing inference",
        observed_waiter,
        f"no NOT-granted advisory lock appeared for advisory_lock_id={holder_lock_id}",
    )
    check(
        "scenario 3: exactly ONE session holds the lock GRANTED (connection A) while that waiter waits",
        _count_advisory_locks(holder_lock_id, granted=True) == 1,
        f"granted={_count_advisory_locks(holder_lock_id, granted=True)}",
    )

    check(
        "scenario 3: the second real connection is STILL BLOCKED on the real case lock",
        worker.is_alive() and "result" not in blocked_result and "error" not in blocked_result,
        f"blocked_result={blocked_result!r}",
    )
    check(
        "scenario 3: while blocked, it has written NOTHING to the real journal (the lock is taken "
        "strictly BEFORE any journal gate/idempotency SQL)",
        journal_rows(fx3["resource_key"]) == [],
    )
    check(
        "scenario 3: the blocked request has NOT touched the real canonical artefact either",
        not fx3["canonical_path"].exists(),
    )
    check(
        "scenario 3: the REAL writer has not been invoked while blocked",
        writer_state["calls"] == 0,
    )

    released = _mutation_lock.release_lock_session(holder_conn, holder_lock_id)
    check("scenario 3: connection A's real lock release reported success", released is True)
    holder_conn.close()

    worker.join(timeout=90)
    check("scenario 3: once A released, the blocked request completed", not worker.is_alive())
    check(
        "scenario 3: the previously-blocked request succeeded on its own connection",
        "error" not in blocked_result and blocked_result.get("result") is not None,
        f"blocked_result={blocked_result!r}",
    )
    if blocked_result.get("result") is not None:
        check(
            "scenario 3: it then really promoted the canonical artefact and journaled 'completed'",
            fx3["canonical_path"].exists()
            and len(journal_rows(fx3["resource_key"])) == 1
            and journal_rows(fx3["resource_key"])[0]["state"] == "completed"
            and writer_state["calls"] == 1,
        )

    # ============================================================
    # SCENARIO 4 - A DIFFERENT ACTOR'S STALE PRE-LOCK SNAPSHOT.
    # Actor B computes its pre-lock snapshot, then blocks on the case
    # lock while actor A genuinely changes the case. Under the lock, B's
    # recomputed composite snapshot differs -> PreconditionRaceDetectedError,
    # with ZERO prepared journal rows and ZERO writer invocations.
    #
    # Synchronization is EVENT-DRIVEN, not timing-guesswork: a
    # pass-through wrapper around `_compute_precondition_snapshot`
    # signals the main thread the moment B's PRE-LOCK snapshot has been
    # taken, which is the only point after which changing the files can
    # possibly constitute a race for B.
    # ============================================================

    fx4 = make_case("case_pgint_race")
    principal4a, repo4a = make_principal_and_repo(fx4["case_id"], user_id=1, session_id=100)
    principal4b, repo4b = make_principal_and_repo(fx4["case_id"], user_id=2, session_id=200)
    writer_state["calls"] = 0
    writer_state["fault"] = None

    b_snapshot_taken = threading.Event()
    _real_compute_snapshot = facade._compute_precondition_snapshot
    snapshot_calls = {"count": 0}

    def counting_compute_snapshot(pending_path, canonical_path):
        snapshot = _real_compute_snapshot(pending_path, canonical_path)
        snapshot_calls["count"] += 1
        if snapshot_calls["count"] == 1:
            b_snapshot_taken.set()
        return snapshot

    holder_conn4 = pg_connect()
    holder_lock_id4 = _mutation_lock.acquire_case_lock_session(holder_conn4, fx4["case_id"])

    race_result = {}

    def run_racing_approval():
        try:
            race_result["result"] = approve(fx4, principal4b, repo4b)
        except BaseException as error:
            race_result["error"] = error

    try:
        facade._compute_precondition_snapshot = counting_compute_snapshot
        racer = threading.Thread(target=run_racing_approval, daemon=True)
        racer.start()

        check(
            "scenario 4: actor B's PRE-LOCK snapshot was really taken (event-driven, not a sleep)",
            b_snapshot_taken.wait(timeout=60),
        )
        # B is now blocked on the lock actor A holds. Actor A changes
        # the case for real, exactly as a concurrent promotion would.
        fx4["canonical_path"].write_text(
            '{"written_by": "a concurrent writer while actor B waited for the case lock"}',
            encoding="utf-8",
        )
        check(
            "scenario 4: actor A's change really landed on disk while B was blocked",
            fx4["canonical_path"].exists(),
        )
        check(
            "scenario 4: PostgreSQL's OWN pg_locks confirms actor B is genuinely WAITING on the case "
            "lock (server-observed, not inferred)",
            wait_for_lock_waiter(holder_lock_id4),
        )
        check(
            "scenario 4: B is still blocked, and has still written nothing to the real journal",
            racer.is_alive() and journal_rows(fx4["resource_key"]) == [],
        )

        _mutation_lock.release_lock_session(holder_conn4, holder_lock_id4)
        racer.join(timeout=90)
    finally:
        facade._compute_precondition_snapshot = _real_compute_snapshot
        holder_conn4.close()

    check("scenario 4: B's request finished (did not hang)", not racer.is_alive())
    check(
        "scenario 4: B's request was REJECTED with PreconditionRaceDetectedError, under the lock",
        isinstance(race_result.get("error"), PreconditionRaceDetectedError),
        f"race_result={race_result!r}",
    )
    check(
        "scenario 4: PreconditionRaceDetectedError is a StaleViewError, so main.py's existing "
        "STALE_VIEW handling covers it unchanged",
        isinstance(race_result.get("error"), StaleViewError),
    )
    check(
        "scenario 4: ZERO prepared (or any) journal rows were written for the raced request",
        journal_rows(fx4["resource_key"]) == [],
        f"rows={journal_rows(fx4['resource_key'])}",
    )
    check(
        "scenario 4: the REAL writer was NEVER invoked for the raced request",
        writer_state["calls"] == 0,
    )
    check(
        "scenario 4: actor B's snapshot really was computed TWICE (pre-lock, then again under the lock)",
        snapshot_calls["count"] == 2,
        f"count={snapshot_calls['count']}",
    )
    check(
        "scenario 4: the real advisory lock is free again after the rejection",
        lock_is_held_by_anyone(advisory_lock_id_for(fx4["resource_key"])) is False,
    )

    # ============================================================
    # SCENARIO 5 - A GENUINE REAL-WRITER EXCEPTION (no injected fault):
    # the pending document is real, its hash really matches what the
    # request claims, and the composite snapshot really is unchanged -
    # so the facade's precondition legitimately passes - but the REAL
    # deadline_approval validator rejects the document's CONTENT. The
    # journal row must end up 'reconciliation_required', NEVER 'failed'.
    # ============================================================

    fx5 = make_case("case_pgint_writerfail", pending_content='{"deadline_analysis_id": "not-valid-at-all"}')
    principal5, repo5 = make_principal_and_repo(fx5["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    check(
        "scenario 5 preflight: the request's expected_hash really matches the (invalid) pending "
        "document, so the facade's own precondition genuinely passes",
        fx5["expected_hash"] == sha256_file(fx5["pending_path"]),
    )

    # The REAL exception here is `deadline_validator.DeadlineValidationError`,
    # raised by the real `validate_deadline_analysis(raise_on_error=True)`
    # call inside the real `deadline_approval.inspect_pending()` - NOT
    # `deadline_approval`'s own wrapper class, which only fires for a
    # `valid=False` RESULT rather than a raised validation error. Both
    # are accepted here because which of the two the real chain raises
    # is Row 8's own internal business (and either one is equally a
    # "the writer raised" case from the coordinator's point of view) -
    # but a generic `Exception` is deliberately NOT accepted, so an
    # unrelated failure (a TypeError from a bad signature, say) could
    # never masquerade as this scenario passing.
    writer_error5 = expect_raises(
        (deadline_approval.DeadlineApprovalError, _deadline_validator.DeadlineValidationError),
        lambda: approve(fx5, principal5, repo5),
        "scenario 5: the REAL writer's OWN domain exception propagates out of the facade unchanged",
    )
    check(
        "scenario 5: that exception really came from the REAL deadline validator chain (its message "
        "names the real validator), and was neither swallowed nor reclassified by the coordinator",
        writer_error5 is not None and "DEADLINE VALIDATOR" in str(writer_error5),
        f"error={writer_error5!r}",
    )
    check(
        "scenario 5: the REAL writer really was invoked (this is a writer failure, not a "
        "precondition rejection)",
        writer_state["calls"] == 1,
    )
    rows5 = journal_rows(fx5["resource_key"])
    check(
        "scenario 5: the real journal row is 'reconciliation_required' - NEVER 'failed' (a writer's "
        "own exception is not evidence about the file's state)",
        len(rows5) == 1 and rows5[0]["state"] == "reconciliation_required",
        f"rows={[(r['id'], r['state']) for r in rows5]}",
    )
    check(
        "scenario 5: that row carries NO resolution_code and NO failure_code (nothing has been "
        "resolved or classified yet)",
        rows5[0]["resolution_code"] is None and rows5[0]["failure_code"] is None,
    )
    check(
        "scenario 5: executing_at IS set (the writer boundary really was crossed) but resolved_at is NOT",
        rows5[0]["executing_at"] is not None and rows5[0]["resolved_at"] is None,
    )
    check(
        "scenario 5: no canonical artefact was produced by the failed writer",
        not fx5["canonical_path"].exists(),
    )
    check(
        "scenario 5: the real advisory lock was still released despite the writer exception",
        lock_is_held_by_anyone(advisory_lock_id_for(fx5["resource_key"])) is False,
    )

    # --- The resource is now GATED for real. A new, DIFFERENT request
    #     on the same case is refused by the real journal gate. ---
    fx5_retry_hash = fx5["expected_hash"]
    fx5["pending_path"].write_text('{"deadline_analysis_id": "still-not-valid"}', encoding="utf-8")
    fx5["expected_hash"] = sha256_file(fx5["pending_path"])
    expect_raises(
        mutcoord.ResourceGatedError,
        lambda: approve(fx5, principal5, repo5),
        "scenario 5: a NEW request on the now-gated case is refused with ResourceGatedError",
    )
    check(
        "scenario 5: the gate refusal added no journal row and did not re-invoke the writer",
        len(journal_rows(fx5["resource_key"])) == 1 and writer_state["calls"] == 1,
    )

    # ============================================================
    # SCENARIO 6 - NO INFORMATION LEAK FROM A GATED RESOURCE. An
    # UNAUTHORIZED caller asking about the (genuinely gated) case above
    # must be indistinguishable from one asking about a perfectly
    # ordinary, ungated case: same exception type, same reason code,
    # and ZERO journal SQL either way.
    # ============================================================

    fx6_ungated = make_case("case_pgint_ungated")
    principal6, repo6_denied_gated = make_principal_and_repo(fx5["case_id"], user_id=7, session_id=700, assigned=False)
    _, repo6_denied_ungated = make_principal_and_repo(fx6_ungated["case_id"], user_id=7, session_id=700, assigned=False)
    writer_state["calls"] = 0

    class CountingConnFactory:
        """A REAL connection factory that also counts how many
        connections were actually opened - so "zero connections" is
        proven, not assumed."""

        def __init__(self):
            self.opened = 0

        def __call__(self):
            self.opened += 1
            return pg_connect()

    factory_gated = CountingConnFactory()
    factory_ungated = CountingConnFactory()

    error_gated = expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: facade.approve_case_scoped_mutation(
            ROW_KEY, fx5["case_id"], fx5["expected_hash"],
            principal=principal6, authz_repository=repo6_denied_gated, conn_factory=factory_gated,
        ),
        "scenario 6: an unauthorized caller on the GATED case is denied by the outer authz check",
    )
    error_ungated = expect_raises(
        _authz.CaseAccessDeniedError,
        lambda: facade.approve_case_scoped_mutation(
            ROW_KEY, fx6_ungated["case_id"], fx6_ungated["expected_hash"],
            principal=principal6, authz_repository=repo6_denied_ungated, conn_factory=factory_ungated,
        ),
        "scenario 6: an unauthorized caller on an ORDINARY ungated case is denied identically",
    )

    check(
        "scenario 6: NO gate/idempotency information leaks - the gated and ungated denials are the "
        "SAME exception type with the SAME reason_code and the SAME message",
        error_gated is not None and error_ungated is not None
        and type(error_gated) is type(error_ungated)
        and getattr(error_gated, "reason_code", None) == getattr(error_ungated, "reason_code", None)
        and str(error_gated) == str(error_ungated),
        f"gated={error_gated!r} ungated={error_ungated!r}",
    )
    check(
        "scenario 6: the outer denial opened ZERO real database connections in BOTH cases",
        factory_gated.opened == 0 and factory_ungated.opened == 0,
        f"gated={factory_gated.opened} ungated={factory_ungated.opened}",
    )
    check(
        "scenario 6: the gated case's real journal row was neither read-for-decision nor changed "
        "by the denied request",
        len(journal_rows(fx5["resource_key"])) == 1
        and journal_rows(fx5["resource_key"])[0]["state"] == "reconciliation_required",
    )
    check(
        "scenario 6: the ungated case still has ZERO journal rows after the denial",
        journal_rows(fx6_ungated["resource_key"]) == [],
    )
    check(
        "scenario 6: the REAL writer was never invoked for either denial",
        writer_state["calls"] == 0,
    )
    check(
        "scenario 6: neither denial left the real advisory lock held",
        lock_is_held_by_anyone(advisory_lock_id_for(fx5["resource_key"])) is False
        and lock_is_held_by_anyone(advisory_lock_id_for(fx6_ungated["resource_key"])) is False,
    )

    # ============================================================
    # SCENARIO 7 - COMPLETION-UNCERTAIN ROW, RESOLVED BY REAL
    # RECONCILIATION WITH CORRECT AUDIT BINDING. The REAL writer
    # completes in full (real canonical write, real audit record with
    # real bindings), then the call fails to return cleanly. The row
    # becomes 'reconciliation_required'; the REAL production adapter
    # then independently corroborates it from the REAL artefacts and
    # the REAL reconciliation path resolves it to 'completed'.
    # ============================================================

    fx7 = make_case("case_pgint_reconcile_ok")
    principal7, repo7 = make_principal_and_repo(fx7["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = "after"

    try:
        expect_raises(
            RuntimeError,
            lambda: approve(fx7, principal7, repo7),
            "scenario 7: the post-writer fault propagates out of the facade unchanged",
        )
    finally:
        writer_state["fault"] = None

    rows7 = journal_rows(fx7["resource_key"])
    check(
        "scenario 7: the row is 'reconciliation_required' even though the real writer DID succeed",
        len(rows7) == 1 and rows7[0]["state"] == "reconciliation_required",
        f"rows={[(r['id'], r['state']) for r in rows7]}",
    )
    check(
        "scenario 7: the REAL canonical artefact really was written by the real writer",
        fx7["canonical_path"].exists(),
    )
    audit_path7, audit7 = latest_audit_record(fx7["case_id"])
    check(
        "scenario 7: the REAL audit record carries all THREE bindings, correctly",
        audit7 is not None
        and audit7.get("mutation_idempotency_key") == rows7[0]["idempotency_key"]
        and audit7.get("mutation_resource_key") == rows7[0]["resource_key"]
        and audit7.get("canonical_sha256") == sha256_file(fx7["canonical_path"]),
        f"audit={audit7!r}",
    )

    # --- REAL reconciliation, REAL production registry, REAL lock. ---
    recon_conn7 = pg_connect()
    try:
        dry_run7 = mr.inspect_reconciliation(recon_conn7, rows7[0]["id"], PRODUCTION_REGISTRY)
        check(
            "scenario 7: the DRY-RUN inspection (real adapter, real evidence) would resolve it to "
            "'completed' via post-state verification",
            dry_run7.new_state == "completed"
            and dry_run7.resolution_code == RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
            f"dry_run={dry_run7!r}",
        )
        check(
            "scenario 7: the dry run issued ZERO UPDATEs (the row is still unresolved)",
            journal_rows(fx7["resource_key"])[0]["state"] == "reconciliation_required",
        )
        applied7 = mr.reconcile_and_apply_journal_entry(
            recon_conn7, rows7[0]["id"], PRODUCTION_REGISTRY,
            resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c2a-integration-test",
        )
        check(
            "scenario 7: the REAL --apply reconciliation resolved the row to 'completed'",
            applied7.new_state == "completed",
        )
    finally:
        recon_conn7.close()

    rows7_after = journal_rows(fx7["resource_key"])
    check(
        "scenario 7: the real database row is now 'completed', with the RECONCILED resolution_code",
        rows7_after[0]["state"] == "completed"
        and rows7_after[0]["resolution_code"] == RESOLUTION_CODE_COMPLETED_POST_STATE_VERIFIED,
        f"row={rows7_after[0]!r}",
    )
    check(
        "scenario 7: 0004's reconciliation provenance really was recorded on the resolved row",
        rows7_after[0]["reconciled_by_actor_type"] == "cli_service"
        and rows7_after[0]["reconciled_by_actor_ref"] == "row19c2a-integration-test",
    )
    check(
        "scenario 7: the reconciled observed_post_hash equals the REAL canonical file's own hash",
        rows7_after[0]["observed_post_hash"] == sha256_file(fx7["canonical_path"]),
    )
    check(
        "scenario 7: reconciliation did NOT re-invoke the writer (evidence-gathering is read-only)",
        writer_state["calls"] == 1,
    )
    check(
        "scenario 7: the resource is no longer gated - the row reached a terminal state",
        all(r["state"] not in ("prepared", "executing", "reconciliation_required") for r in rows7_after),
    )

    # ============================================================
    # SCENARIO 8 - BROKEN AUDIT BINDING MUST NEVER PRODUCE 'completed'.
    # Same setup as scenario 7, but the REAL audit record's binding is
    # tampered with before reconciliation. Proven separately for the
    # idempotency-key binding, the resource-key binding, and the
    # canonical-hash binding.
    # ============================================================

    def build_uncertain_case(case_id, user_id, session_id):
        fixture = make_case(case_id)
        principal, repo = make_principal_and_repo(fixture["case_id"], user_id=user_id, session_id=session_id)
        writer_state["fault"] = "after"
        try:
            with contextlib.suppress(RuntimeError):
                approve(fixture, principal, repo)
        finally:
            writer_state["fault"] = None
        rows = journal_rows(fixture["resource_key"])
        assert len(rows) == 1 and rows[0]["state"] == "reconciliation_required", rows
        return fixture, rows[0]

    binding_break_cases = [
        ("idempotency-key binding", "case_pgint_break_idem", {"mutation_idempotency_key": "not-the-right-key"}),
        ("resource-key binding", "case_pgint_break_res", {"mutation_resource_key": "case:some_other_case"}),
        ("MISSING resource-key binding (a pre-Row-19C-2a style audit record)",
         "case_pgint_break_missing", {"mutation_resource_key": None}),
        ("BLANK idempotency-key binding", "case_pgint_break_blank", {"mutation_idempotency_key": "   "}),
    ]

    for label, case_id, tamper in binding_break_cases:
        fixture, row = build_uncertain_case(case_id, user_id=11, session_id=1100)
        audit_path, audit_record = latest_audit_record(fixture["case_id"])
        audit_path.write_text(json.dumps({**audit_record, **tamper}), encoding="utf-8")

        conn = pg_connect()
        try:
            outcome = mr.reconcile_and_apply_journal_entry(conn, row["id"], PRODUCTION_REGISTRY)
        finally:
            conn.close()

        after = journal_rows(fixture["resource_key"])[0]
        check(
            f"scenario 8: a broken {label} does NOT reconcile to 'completed'",
            outcome.new_state != "completed" and after["state"] != "completed",
            f"outcome={outcome!r} row_state={after['state']!r}",
        )
        check(
            f"scenario 8: a broken {label} leaves the row unresolved "
            "('reconciliation_required'), with NO resolution_code",
            after["state"] == "reconciliation_required" and after["resolution_code"] is None,
            f"row={after!r}",
        )

    # The canonical-hash binding, on an otherwise perfectly-bound audit
    # record: the artefact on disk was overwritten AFTER the audit
    # record was written, so bindings 1+2 still match and only 3-vs-4
    # catches it.
    fixture8h, row8h = build_uncertain_case("case_pgint_break_hash", user_id=12, session_id=1200)
    check(
        "scenario 8 preflight: the canonical-hash case starts out CORRECTLY bound",
        latest_audit_record(fixture8h["case_id"])[1].get("canonical_sha256")
        == sha256_file(fixture8h["canonical_path"]),
    )
    fixture8h["canonical_path"].write_text('{"overwritten":"out of band"}', encoding="utf-8")
    conn8h = pg_connect()
    try:
        outcome8h = mr.reconcile_and_apply_journal_entry(conn8h, row8h["id"], PRODUCTION_REGISTRY)
    finally:
        conn8h.close()
    after8h = journal_rows(fixture8h["resource_key"])[0]
    check(
        "scenario 8: an out-of-band canonical overwrite (bindings 1+2 still matching) does NOT "
        "reconcile to 'completed'",
        outcome8h.new_state == "reconciliation_required" and after8h["state"] == "reconciliation_required",
        f"outcome={outcome8h!r} row_state={after8h['state']!r}",
    )

    # ============================================================
    # SCENARIO 9 - AN EXTERNALLY CHANGED CANONICAL MUST NOT CAUSE A
    # REPLAY TO RE-RUN THE WRITER. The completed row from scenario 1 is
    # replayed after its canonical artefact is changed out of band: the
    # request is refused (the outcome can no longer be corroborated),
    # and - the point of this scenario - the writer is NOT re-invoked.
    # ============================================================

    writer_calls_before_9 = writer_state["calls"]
    canonical_backup_9 = fx1["canonical_path"].read_text(encoding="utf-8")
    fx1["canonical_path"].write_text(
        '{"changed_by":"something entirely outside this approval path"}', encoding="utf-8",
    )

    expect_raises(
        facade.AuditBindingVerificationFailedError,
        lambda: approve(fx1, principal1, repo1),
        "scenario 9: a replay whose canonical artefact changed externally is refused with "
        "AuditBindingVerificationFailedError",
    )
    check(
        "scenario 9: the REAL writer was NOT re-invoked (a replay never re-runs the writer, "
        "regardless of what the filesystem now looks like)",
        writer_state["calls"] == writer_calls_before_9,
    )
    check(
        "scenario 9: the refusal added no journal row and left the completed row untouched",
        len(journal_rows(fx1["resource_key"])) == 1
        and journal_rows(fx1["resource_key"])[0]["state"] == "completed",
    )
    check(
        "scenario 9: the externally-changed canonical file was NOT silently repaired or reverted "
        "by the refused request",
        fx1["canonical_path"].read_text(encoding="utf-8")
        == '{"changed_by":"something entirely outside this approval path"}',
    )
    fx1["canonical_path"].write_text(canonical_backup_9, encoding="utf-8")
    check(
        "scenario 9: with the canonical artefact restored, the SAME request replays cleanly again "
        "and STILL does not re-invoke the writer",
        approve(fx1, principal1, repo1).replayed is True
        and writer_state["calls"] == writer_calls_before_9,
    )

    # ============================================================
    # SCENARIO 10 - REAL ROWCOUNT FAILURE CLASSIFICATIONS. The journal
    # row is DELETEd out of band through a second real connection right
    # after the genuine INSERT/UPDATE, so the next completely
    # unmodified coordinator UPDATE really does affect 0 rows.
    # ============================================================

    # 10a) 'prepared' -> 'executing' fails: the writer must NEVER run.
    fx10a = make_case("case_pgint_rowcount_exec")
    principal10a, repo10a = make_principal_and_repo(fx10a["case_id"], user_id=21, session_id=2100)
    writer_state["calls"] = 0
    writer_state["fault"] = None

    try:
        install_delete_after("prepared")
        error10a = expect_raises(
            mutcoord.JournalExecutingTransitionFailedError,
            lambda: approve(fx10a, principal10a, repo10a),
            "scenario 10a: a real rowcount-0 'prepared'->'executing' UPDATE raises "
            "JournalExecutingTransitionFailedError",
        )
    finally:
        restore_coordinator_internals()

    check(
        "scenario 10a: the REAL writer was NEVER invoked (the failure is strictly before the "
        "writer boundary)",
        writer_state["calls"] == 0,
    )
    check(
        "scenario 10a: the error carries the real observed rowcount (0)",
        error10a is not None and error10a.rowcount == 0,
    )
    check(
        "scenario 10a: no canonical artefact was produced",
        not fx10a["canonical_path"].exists(),
    )
    check(
        "scenario 10a: the real advisory lock was still released",
        lock_is_held_by_anyone(advisory_lock_id_for(fx10a["resource_key"])) is False,
    )

    # 10b) 'executing' -> 'completed' fails AFTER the real writer
    #      already succeeded: the genuinely-ambiguous case.
    fx10b = make_case("case_pgint_rowcount_complete")
    principal10b, repo10b = make_principal_and_repo(fx10b["case_id"], user_id=22, session_id=2200)
    writer_state["calls"] = 0
    writer_state["fault"] = None

    try:
        install_delete_after("executing")
        error10b = expect_raises(
            mutcoord.JournalCompletionUncertainError,
            lambda: approve(fx10b, principal10b, repo10b),
            "scenario 10b: a real rowcount-0 'executing'->'completed' UPDATE raises "
            "JournalCompletionUncertainError",
        )
    finally:
        restore_coordinator_internals()

    check(
        "scenario 10b: the REAL writer DID run exactly once (this failure is strictly AFTER the "
        "writer returned successfully)",
        writer_state["calls"] == 1,
    )
    check(
        "scenario 10b: the REAL canonical artefact really was promoted, even though the journal "
        "could not record it",
        fx10b["canonical_path"].exists(),
    )
    check(
        "scenario 10b: the error carries the real rowcount (0) AND the writer's own "
        "observed_post_hash",
        error10b is not None and error10b.rowcount == 0
        and error10b.observed_post_hash == sha256_file(fx10b["canonical_path"]),
    )
    check(
        "scenario 10b: this outcome is neither a success nor a plain failure - it maps to the SAME "
        "closed MUTATION_REQUIRES_REVIEW contract as a gated/audit-binding outcome",
        isinstance(error10b, mutcoord.MutationCoordinatorError),
    )
    check(
        "scenario 10b: the real advisory lock was still released",
        lock_is_held_by_anyone(advisory_lock_id_for(fx10b["resource_key"])) is False,
    )

    # ============================================================
    # SCENARIO 11 - the plain (non-race) staleness rejection, on the
    # real stack: the caller's own claimed expected_hash simply does not
    # match the real pending document, and nothing changed underneath.
    # ============================================================

    fx11 = make_case("case_pgint_stale")
    principal11, repo11 = make_principal_and_repo(fx11["case_id"], user_id=31, session_id=3100)
    writer_state["calls"] = 0
    writer_state["fault"] = None

    stale_error11 = expect_raises(
        StaleViewError,
        lambda: approve(fx11, principal11, repo11, expected_hash="0" * 64),
        "scenario 11: a stale claimed expected_hash is rejected with StaleViewError",
    )
    check(
        "scenario 11: it is the PLAIN StaleViewError, not the PreconditionRaceDetectedError "
        "subclass (nothing actually changed underneath this request)",
        stale_error11 is not None and not isinstance(stale_error11, PreconditionRaceDetectedError),
    )
    check(
        "scenario 11: ZERO journal rows and ZERO writer invocations",
        journal_rows(fx11["resource_key"]) == [] and writer_state["calls"] == 0,
    )
    check(
        "scenario 11: no canonical artefact was produced",
        not fx11["canonical_path"].exists(),
    )

    # ============================================================
    # SCENARIO 12 - ROW 19C-2a FINAL AUDIT REMEDIATION, BINDING 3b:
    # `journal.observed_post_hash == current canonical SHA-256`.
    #
    # The nastiest case the earlier four-binding check could not see:
    # the canonical artefact AND its audit record are changed together,
    # CONSISTENTLY, out of band. Bindings 1, 2, 4 and 5 all still hold
    # (the audit record is internally perfect and correctly bound), so
    # ONLY the journal's own recorded post-state hash reveals that the
    # artefact on disk is no longer the one this `completed` row
    # attests to. Without binding 3b the facade would have reported
    # success AND handed the stale journal hash to the success page.
    # ============================================================

    fx12 = make_case("case_pgint_posthash")
    principal12, repo12 = make_principal_and_repo(fx12["case_id"], user_id=1, session_id=100)
    writer_state["calls"] = 0
    writer_state["fault"] = None

    result12 = approve(fx12, principal12, repo12)
    row12 = journal_rows(fx12["resource_key"])[0]
    check(
        "scenario 12 preflight: a normal completed approval, with the journal's observed_post_hash "
        "matching both the real canonical file and the real audit record",
        result12.replayed is False
        and row12["state"] == "completed"
        and row12["observed_post_hash"] == sha256_file(fx12["canonical_path"]),
    )
    check(
        "scenario 12: a FRESH approval's returned canonical_hash is the hash of the real canonical "
        "artefact the real writer just produced",
        result12.canonical_hash == sha256_file(fx12["canonical_path"]),
    )

    # Now rewrite BOTH the canonical artefact and its audit record so
    # they remain perfectly consistent with EACH OTHER.
    audit_path12, audit12 = latest_audit_record(fx12["case_id"])
    tampered_canonical_12 = '{"tampered":"canonical and audit rewritten together, consistently"}'
    fx12["canonical_path"].write_text(tampered_canonical_12, encoding="utf-8")
    new_canonical_hash_12 = sha256_file(fx12["canonical_path"])
    audit_path12.write_text(
        json.dumps({**audit12, "canonical_sha256": new_canonical_hash_12}), encoding="utf-8",
    )
    check(
        "scenario 12: after the tamper, bindings 1, 2, 4 and 5 ALL still hold (the audit record is "
        "internally perfect) - only binding 3b can possibly catch this",
        audit12.get("mutation_idempotency_key") == row12["idempotency_key"]
        and audit12.get("mutation_resource_key") == row12["resource_key"]
        and audit12.get("pending_sha256") == row12["pre_revision"]
        and new_canonical_hash_12 != row12["observed_post_hash"],
    )

    calls_before_12 = writer_state["calls"]
    expect_raises(
        facade.AuditBindingVerificationFailedError,
        lambda: approve(fx12, principal12, repo12),
        "scenario 12: the replay is REJECTED because journal.observed_post_hash no longer matches the "
        "current canonical SHA-256, even though canonical and audit agree with each other",
    )
    check(
        "scenario 12: the rejected replay did NOT re-invoke the writer",
        writer_state["calls"] == calls_before_12,
    )
    check(
        "scenario 12: the rejected replay added no journal row and left the completed row untouched",
        len(journal_rows(fx12["resource_key"])) == 1
        and journal_rows(fx12["resource_key"])[0]["state"] == "completed"
        and journal_rows(fx12["resource_key"])[0]["observed_post_hash"] == row12["observed_post_hash"],
    )
    check(
        "scenario 12: the rejected replay did not silently repair the tampered canonical artefact",
        fx12["canonical_path"].read_text(encoding="utf-8") == tampered_canonical_12,
    )

    # Restore consistency (canonical back to the writer's own output,
    # audit back to its original record) and confirm the SAME request
    # then replays cleanly and returns the FRESHLY VERIFIED hash.
    fx12["canonical_path"].write_text(
        fx12["pending_path"].read_text(encoding="utf-8"), encoding="utf-8",
    )
    audit_path12.write_text(json.dumps(audit12), encoding="utf-8")
    restored_hash_12 = sha256_file(fx12["canonical_path"])
    if restored_hash_12 == row12["observed_post_hash"]:
        replayed_12 = approve(fx12, principal12, repo12)
        check(
            "scenario 12: with consistency restored, the SAME request replays cleanly and its "
            "canonical_hash is the FRESHLY VERIFIED current canonical hash",
            replayed_12.replayed is True and replayed_12.canonical_hash == restored_hash_12,
            f"replayed={replayed_12.replayed} hash={replayed_12.canonical_hash!r} vs {restored_hash_12!r}",
        )
        check(
            "scenario 12: that clean replay still did not re-invoke the writer",
            writer_state["calls"] == calls_before_12,
        )
    else:
        check(
            "scenario 12: restoring the canonical artefact reproduces the writer's own output hash",
            False,
            f"restored={restored_hash_12!r} != journal={row12['observed_post_hash']!r} - the real "
            "writer's canonical output is not a byte-copy of the pending document for this family, "
            "so this sub-check cannot be evaluated",
        )

    # ============================================================
    # SCENARIO 13 - ROW 19C-2a FINAL AUDIT REMEDIATION, BINDING 5:
    # `audit.pending_sha256 == journal/request pre_revision`, proven on
    # BOTH paths - the facade's request-time replay check AND the
    # out-of-band reconciliation adapter.
    # ============================================================

    # 13a) REPLAY path.
    fx13 = make_case("case_pgint_pendinghash")
    principal13, repo13 = make_principal_and_repo(fx13["case_id"], user_id=2, session_id=200)
    writer_state["calls"] = 0
    writer_state["fault"] = None

    approve(fx13, principal13, repo13)
    row13 = journal_rows(fx13["resource_key"])[0]
    audit_path13, audit13 = latest_audit_record(fx13["case_id"])
    check(
        "scenario 13a preflight: the REAL audit record's pending_sha256 equals the journal row's own "
        "pre_revision",
        audit13.get("pending_sha256") == row13["pre_revision"] and row13["pre_revision"] is not None,
        f"audit={audit13.get('pending_sha256')!r} journal={row13['pre_revision']!r}",
    )

    calls_before_13 = writer_state["calls"]
    for label, tamper in [
        ("WRONG", {"pending_sha256": "e" * 64}),
        ("MISSING", {"pending_sha256": None}),
        ("BLANK", {"pending_sha256": "  "}),
    ]:
        audit_path13.write_text(json.dumps({**audit13, **tamper}), encoding="utf-8")
        expect_raises(
            facade.AuditBindingVerificationFailedError,
            lambda: approve(fx13, principal13, repo13),
            f"scenario 13a: a replay is REJECTED when the audit record's pending_sha256 is {label} "
            "(binding 5, checked directly rather than left to the idempotency key transitively)",
        )
    check(
        "scenario 13a: none of those rejected replays re-invoked the writer",
        writer_state["calls"] == calls_before_13,
    )
    audit_path13.write_text(json.dumps(audit13), encoding="utf-8")

    # 13b) RECONCILIATION path - an unresolved row whose audit record's
    #      pending_sha256 does not match must NEVER reconcile to
    #      'completed', even though every other binding holds.
    for label, tamper in [
        ("WRONG", {"pending_sha256": "d" * 64}),
        ("MISSING", {"pending_sha256": None}),
    ]:
        fixture, row = build_uncertain_case(f"case_pgint_pend_{label.lower()}", user_id=11, session_id=1100)
        audit_path, audit_record = latest_audit_record(fixture["case_id"])
        check(
            f"scenario 13b ({label}) preflight: this row's audit record starts out CORRECTLY bound on "
            "binding 5",
            audit_record.get("pending_sha256") == row["pre_revision"],
        )
        audit_path.write_text(json.dumps({**audit_record, **tamper}), encoding="utf-8")

        conn13b = pg_connect()
        try:
            outcome13b = mr.reconcile_and_apply_journal_entry(conn13b, row["id"], PRODUCTION_REGISTRY)
        finally:
            conn13b.close()

        after13b = journal_rows(fixture["resource_key"])[0]
        check(
            f"scenario 13b: reconciliation does NOT produce 'completed' when the audit record's "
            f"pending_sha256 is {label}",
            outcome13b.new_state != "completed" and after13b["state"] != "completed",
            f"outcome={outcome13b!r} state={after13b['state']!r}",
        )
        check(
            f"scenario 13b ({label}): the row is left unresolved with NO resolution_code and NO "
            "reconciliation provenance",
            after13b["state"] == "reconciliation_required"
            and after13b["resolution_code"] is None
            and after13b["reconciled_by_actor_type"] is None,
            f"row={after13b!r}",
        )

    # ============================================================
    # SCENARIO 14 - the production-default authz repository lifecycle is
    # covered by an ISOLATED test, deliberately not here.
    #
    # `ui/tests/test_mutation_approval_facade_isolated.py` section 13
    # exercises the REAL `_resolve_authz_repository()` /
    # `_default_authz_repository()` with only `ui.services.db.
    # get_connection` stubbed, and proves: the `(repository, close)`
    # contract; a REAL `authz.PostgresAuthzRepository` built on the
    # opened connection; the connection opened exactly once and closed
    # EXACTLY once across a full production-default approval; both the
    # outer and inner authz checks really issuing their SQL against it;
    # the connection still closed on the authz-denial exception path;
    # an injected repository opening nothing and closing nothing; and a
    # closer that itself raises being logged without replacing the
    # outcome.
    #
    # That belongs THERE rather than here because it is about
    # connection LIFECYCLE, which a stub connection can observe far
    # more precisely (open/close call counts, exact SQL issued) than a
    # real psycopg connection can - and because this file deliberately
    # injects `authz_repository=` so that its own subject stays
    # MUTATION INTEGRITY rather than IAM persistence (see this file's
    # own header, "WHAT IS NOT REAL, AND EXACTLY WHY", item 1). This
    # check simply records that the coverage exists and is not silently
    # missing from the suite as a whole.
    # ============================================================

    _facade_isolated_test = REPO_ROOT / "ui" / "tests" / "test_mutation_approval_facade_isolated.py"
    _isolated_source = _facade_isolated_test.read_text(encoding="utf-8")
    check(
        "scenario 14: the production-default authz repository lifecycle IS covered, by "
        "test_mutation_approval_facade_isolated.py's own section 13 (not silently missing)",
        "_resolve_authz_repository(None)" in _isolated_source
        and "default authz (full flow): that IAM connection was closed EXACTLY once" in _isolated_source,
    )

    # ================================================================
    # ROW 19C-3a SLICE 2 REAL-POSTGRES PATH-PROOF REMEDIATION
    #
    # SCENARIO A1 - PRE-LOCK NESTED ESCAPE, against the REAL production
    # facade/coordinator, a REAL disposable PostgreSQL journal, and a
    # REAL NTFS junction (never monkeypatched/mocked). `reviews_dir`
    # (one of the three chains `approve_case_scoped_mutation()`
    # verifies pre-lock) is made a live junction pointing OUTSIDE the
    # case root, with a plausible forged audit file planted inside the
    # escape target - proving (a) the REAL facade raises
    # `NestedPathContainmentError` BEFORE any journal/lock connection is
    # even opened, (b) the real journal table genuinely has ZERO rows
    # for this resource, (c) the real writer never ran, and (d) the
    # planted spy file was never read (byte-identical before/after).
    # ================================================================

    fx_a1 = make_case("case_a1_prelock_escape")
    principal_a1, repo_a1 = make_principal_and_repo(fx_a1["case_id"])
    writer_state["calls"] = 0
    writer_state["fault"] = None

    reviews_dir_a1 = deadline_approval.get_reviews_dir(fx_a1["case_id"])
    reviews_dir_a1.parent.mkdir(parents=True, exist_ok=True)  # `mklink /J` requires the immediate parent to exist
    outside_root_a1 = Path(tempfile.mkdtemp(prefix="vergi_pgint_a1_outside_"))
    try:
        spy_path_a1 = outside_root_a1 / "spy_should_never_be_read.approval.json"
        spy_path_a1.write_text(
            json.dumps({"planted": "outside content - must NEVER be read", "case_id": fx_a1["case_id"]}),
            encoding="utf-8",
        )
        spy_before_a1 = sha256_file(spy_path_a1)
        pending_before_a1 = sha256_file(fx_a1["pending_path"])

        make_directory_escape_link(reviews_dir_a1, outside_root_a1)
        check(
            "A1 precondition: reviews_dir is genuinely a live junction/symlink pointing outside "
            "the case root (os.path.lexists true, real entry present)",
            os.path.lexists(reviews_dir_a1),
        )

        conn_calls_a1 = []

        def _counting_conn_factory_a1():
            conn_calls_a1.append(1)
            return pg_connect()

        a1_error = None
        try:
            facade.approve_case_scoped_mutation(
                ROW_KEY, fx_a1["case_id"], fx_a1["expected_hash"],
                principal=principal_a1, authz_repository=repo_a1, conn_factory=_counting_conn_factory_a1,
            )
        except BaseException as error:
            a1_error = error

        check(
            "A1: the REAL production facade raised NestedPathContainmentError for the live "
            "escaping reviews_dir junction",
            isinstance(a1_error, facade.NestedPathContainmentError),
            f"got {a1_error!r}",
        )
        check(
            "A1: NestedPathContainmentError IS an ApprovalUiError subclass (zero ui/main.py "
            "route changes needed)",
            issubclass(facade.NestedPathContainmentError, facade.ApprovalUiError),
        )
        check(
            "A1: ZERO journal/lock connections were opened at all (pre-lock failure, before "
            "conn_factory() is ever called)",
            conn_calls_a1 == [],
        )
        check(
            "A1: the REAL database has EXACTLY ZERO journal rows for this resource_key",
            journal_rows(fx_a1["resource_key"]) == [],
            f"got {journal_rows(fx_a1['resource_key'])!r}",
        )
        check(
            "A1: PostgreSQL's OWN pg_locks shows no lock was ever requested for this resource "
            "(mutation_resources has no row -> advisory_lock_id is None -> held-by-anyone is False)",
            lock_is_held_by_anyone(advisory_lock_id_for(fx_a1["resource_key"])) is False,
        )
        check(
            "A1: the REAL writer (deadline_approval.run_approve) was never invoked",
            writer_state["calls"] == 0,
        )
        check(
            "A1: the canonical artefact still does not exist",
            not fx_a1["canonical_path"].exists(),
        )
        check(
            "A1: the REAL pending file is byte-unchanged",
            sha256_file(fx_a1["pending_path"]) == pending_before_a1,
        )
        check(
            "A1: the planted spy file OUTSIDE the case root was NEVER read/modified (byte-identical) "
            "- the escape target's content never influenced this rejection",
            sha256_file(spy_path_a1) == spy_before_a1,
        )
    finally:
        if os.path.lexists(reviews_dir_a1):
            os.rmdir(reviews_dir_a1)  # removes the junction/symlink LINK only, never the target's content
        shutil.rmtree(outside_root_a1, ignore_errors=True)

    # ================================================================
    # SCENARIO A2 - UNDER-LOCK CARRY-FORWARD PATH SWAP, against TWO REAL
    # PostgreSQL connections and the REAL `argument_approval` writer (one
    # of the 4 carry-forward families). Connection A holds the REAL
    # `case:<case_id>` advisory lock; a second, fully independent real
    # connection driving the REAL facade genuinely BLOCKS on it
    # (server-observed via `pg_locks`, never a sleep-based guess). WHILE
    # B waits, `history/carry_forward` (safe at the moment B's own
    # pre-lock read happened) is turned into a live junction pointing
    # OUTSIDE the case root, with a forged `carry_forward_*.json` planted
    # inside. When A releases, B's FRESH under-lock carry-forward gate
    # (`precondition_callback`) must catch the escape - the writer must
    # never run, and the real journal must show ZERO rows.
    # ================================================================

    a2_case_id = f"case_a2_carryforward_swap_{RUN_TOKEN}"
    a2_case_dir = _TMP_CASES / a2_case_id
    a2_arguments_dir = a2_case_dir / "arguments"
    a2_arguments_dir.mkdir(parents=True)
    (a2_case_dir / "case.json").write_text(json.dumps({"case_id": a2_case_id}), encoding="utf-8")
    a2_pending_path = argument_approval.get_pending_path(a2_case_id)
    a2_pending_path.write_text(json.dumps({"case_id": a2_case_id, "synthetic": True}), encoding="utf-8")
    a2_expected_hash = sha256_file(a2_pending_path)
    # ROW 19C-3a SLICE 2 FINAL NARROW REMEDIATION: a REAL "before" snapshot,
    # taken here - before the worker thread starts and before the
    # carry_forward junction swap - so the later "byte-unchanged" check
    # below compares against an independently-taken prior value instead of
    # comparing a value to itself (which would be true unconditionally,
    # even if the file had been silently rewritten in between).
    a2_pending_before = sha256_file(a2_pending_path)
    a2_resource_key = _mutation_lock.case_resource_key(a2_case_id)
    a2_canonical_path = argument_approval.get_canonical_path(a2_case_id)
    principal_a2, repo_a2 = make_principal_and_repo(a2_case_id, user_id=11, session_id=1100)

    a2_writer_calls = {"n": 0}
    _REAL_ARGUMENT_RUN_APPROVE = argument_approval.run_approve

    def _a2_counting_run_approve(case_id, *, mutation_idempotency_key=None, mutation_resource_key=None):
        a2_writer_calls["n"] += 1
        return _REAL_ARGUMENT_RUN_APPROVE(
            case_id, mutation_idempotency_key=mutation_idempotency_key, mutation_resource_key=mutation_resource_key,
        )

    argument_approval.run_approve = _a2_counting_run_approve

    a2_carry_dir = argument_approval.get_carry_forward_dir(a2_case_id)
    a2_carry_dir.parent.mkdir(parents=True, exist_ok=True)  # `history/` must exist before `mklink /J` can create carry_forward under it
    a2_outside_root = Path(tempfile.mkdtemp(prefix="vergi_pgint_a2_outside_"))
    a2_holder_conn = None
    try:
        a2_holder_conn = pg_connect()
        a2_holder_lock_id = _mutation_lock.acquire_case_lock_session(a2_holder_conn, a2_case_id)
        check(
            "A2: connection A really acquired the REAL case lock (a real advisory_lock_id was assigned)",
            isinstance(a2_holder_lock_id, int),
        )

        a2_blocked_result = {}

        def _a2_run_blocked():
            try:
                a2_blocked_result["result"] = facade.approve_case_scoped_mutation(
                    "arguments", a2_case_id, a2_expected_hash,
                    principal=principal_a2, authz_repository=repo_a2, conn_factory=pg_connect,
                )
            except BaseException as error:
                a2_blocked_result["error"] = error

        a2_worker = threading.Thread(target=_a2_run_blocked, daemon=True)
        a2_worker.start()

        a2_observed_waiter = wait_for_lock_waiter(a2_holder_lock_id)
        check(
            "A2: PostgreSQL's OWN pg_locks reports a genuinely WAITING (not granted) advisory lock "
            "for this case - session B is really blocked, not merely believed to be",
            a2_observed_waiter,
            f"no NOT-granted advisory lock appeared for advisory_lock_id={a2_holder_lock_id}",
        )
        check(
            "A2: while B waits, it has written NOTHING to the real journal yet",
            journal_rows(a2_resource_key) == [],
        )

        # WHILE B waits (proven blocked above), swap history/carry_forward
        # to a live escaping junction with a forged matching entry inside.
        a2_forged_entry_content = json.dumps(
            {"carried_records": [{"entity_type": "claim", "new_id": "forged_id_never_trusted"}]},
        )
        (a2_outside_root / "carry_forward_evil.json").write_text(a2_forged_entry_content, encoding="utf-8")
        a2_outside_spy_before = sha256_file(a2_outside_root / "carry_forward_evil.json")
        make_directory_escape_link(a2_carry_dir, a2_outside_root)
        check(
            "A2 precondition: history/carry_forward is genuinely a live junction/symlink pointing "
            "outside the case root, created WHILE session B was still blocked",
            os.path.lexists(a2_carry_dir),
        )

        a2_released = _mutation_lock.release_lock_session(a2_holder_conn, a2_holder_lock_id)
        check("A2: connection A's real lock release reported success", a2_released is True)
        a2_holder_conn.close()
        a2_holder_conn = None

        a2_worker.join(timeout=90)
        check("A2: once A released, the previously-blocked request completed (thread finished)", not a2_worker.is_alive())
        check(
            "A2: the FRESH under-lock carry-forward verification rejected B with "
            "NestedPathContainmentError - the escape introduced while waiting was caught, never "
            "silently accepted",
            isinstance(a2_blocked_result.get("error"), facade.NestedPathContainmentError),
            f"got {a2_blocked_result!r}",
        )
        check(
            "A2: the REAL argument_approval writer was NEVER invoked",
            a2_writer_calls["n"] == 0,
        )
        check(
            "A2: the REAL database has EXACTLY ZERO journal rows for this resource_key (no "
            "prepared/executing/reconciliation_required row was ever created)",
            journal_rows(a2_resource_key) == [],
            f"got {journal_rows(a2_resource_key)!r}",
        )
        check(
            "A2: the canonical artefact was never created",
            not a2_canonical_path.exists(),
        )
        check(
            "A2: the pending file is byte-unchanged (compared against a REAL prior snapshot taken "
            "before the worker thread started and before the carry_forward junction swap - not a "
            "value compared against itself)",
            sha256_file(a2_pending_path) == a2_pending_before,
            f"before={a2_pending_before!r} after={sha256_file(a2_pending_path)!r}",
        )
        check(
            "A2: the forged carry-forward content planted OUTSIDE the case root was never read "
            "(byte-identical) - the gate verifies path safety only, content is never consulted",
            sha256_file(a2_outside_root / "carry_forward_evil.json") == a2_outside_spy_before,
        )
    finally:
        argument_approval.run_approve = _REAL_ARGUMENT_RUN_APPROVE
        if a2_holder_conn is not None:
            try:
                _mutation_lock.release_lock_session(a2_holder_conn, a2_holder_lock_id)
            except Exception:
                pass
            a2_holder_conn.close()
        if os.path.lexists(a2_carry_dir):
            os.rmdir(a2_carry_dir)
        shutil.rmtree(a2_outside_root, ignore_errors=True)

finally:
    deadline_approval.run_approve = _REAL_RUN_APPROVE
    restore_coordinator_internals()
    for _module, _original in _original_cases_dirs:
        _module.CASES_DIR = _original
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


# ----------------------------------------------------------------
# Post-conditions: nothing was left monkeypatched, and this
# repository's own real `data/` tree is byte-for-byte unchanged.
# ----------------------------------------------------------------

check(
    "teardown: deadline_approval.run_approve is the genuine production function again",
    deadline_approval.run_approve is _REAL_RUN_APPROVE,
)
check(
    "teardown: the coordinator's own internals are unpatched again",
    mutcoord._insert_prepared is _REAL_INSERT_PREPARED
    and mutcoord._mark_executing is _REAL_MARK_EXECUTING,
)
check(
    "teardown: every redirected CASES_DIR was restored to the real cases root",
    all(
        Path(os.path.realpath(str(module.CASES_DIR))) == _REAL_CASES_ROOT
        for module, _original in _original_cases_dirs
    ),
)
check(
    "teardown: the temporary case tree was removed",
    not _TMP_ROOT.exists(),
)

_REAL_DATA_AFTER = snapshot_real_data_tree()
check(
    "this repository's REAL data/ tree is byte-for-byte UNCHANGED by this entire suite",
    _REAL_DATA_AFTER == _REAL_DATA_BEFORE,
    f"before={len(_REAL_DATA_BEFORE)} files, after={len(_REAL_DATA_AFTER)} files; "
    f"differing={sorted(set(_REAL_DATA_BEFORE) ^ set(_REAL_DATA_AFTER))[:5]}",
)

summarize_and_exit()
