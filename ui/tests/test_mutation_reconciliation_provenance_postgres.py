# ============================================================
# Row 19C-2a - REAL PostgreSQL proof for
# db/migrations/0004_mutation_reconciliation_provenance.sql and the
# `ui/services/mutation_registry.py` changes built on top of it:
# `JournalEntrySnapshot.idempotency_key`, `reconcile_and_apply_journal_
# entry()`'s new `resolved_by_actor_type`/`resolved_by_actor_ref`
# keyword params, and the new `inspect_reconciliation()` dry-run
# function (including its fail-closed `LockReleaseAnomalyError` unlock
# discipline) - against an actual, disposable PostgreSQL database, not
# a fake connection.
#
# WHY THIS FILE EXISTS SEPARATELY FROM test_reconciliation_isolated.py
# AND test_mutation_journal_postgres.py
# ----------------------------------------------------------------
# test_reconciliation_isolated.py proves this project's OWN decision/
# ordering/provenance-threading LOGIC against an in-memory fake table -
# it cannot prove that 0004's own SQL (four CHECK constraints, two
# ADD COLUMN IF NOT EXISTS statements) is valid, executable PostgreSQL,
# nor that those constraints ACTUALLY reject the row shapes they are
# meant to at the real database level. test_mutation_journal_postgres.py
# proves ui.services.mutation_coordinator.py's own real-PostgreSQL
# behavior and does not touch 0004 or mutation_registry.py's provenance
# additions at all. This file is the real-database counterpart
# specifically for 0004 and the reconciliation-provenance/dry-run
# additions layered on top of it.
#
# PREREQUISITE: this file assumes 0001_iam_schema.sql,
# 0002_mutation_resources.sql, 0003_mutation_journal.sql AND
# 0004_mutation_reconciliation_provenance.sql have ALL already been
# applied to the database named by VERGI_TEST_PG_DSN - exactly the same
# convention test_mutation_journal_postgres.py already uses for
# 0001-0003 (this file never invokes `psql -f <migration>.sql` itself;
# it only CONNECTS to an already-migrated database and exercises real
# SQL/application code against it). 0004's own idempotent-re-run
# property (applying it twice produces an identical schema and zero
# data changes) is proven separately, directly with `psql`, as part of
# this Row's delivery evidence - not duplicated here as Python.
#
# TWO BACKENDS, SAME REASON AS test_mutation_journal_postgres.py: this
# file prefers a REAL `psycopg` connection whenever importable, and
# falls back to the same minimal `psql`-subprocess DB-API-2.0 shim only
# when `psycopg` cannot be installed (this sandbox's own situation -
# see that file's own header comment for the full Windows-vs-POSIX
# rationale; this file's copy of the shim is intentionally the same
# shape for the same reasons, kept as its own copy rather than an
# import, matching this project's existing convention of each
# real-PostgreSQL test file being self-contained).
#
# SKIPPED with an explicit message if no reachable PostgreSQL is
# configured for this run via VERGI_TEST_PG_DSN (never silently
# treated as a pass) - matching this project's other real-DB test
# files' own contract.
#
# Run: python -m ui.tests.test_mutation_reconciliation_provenance_postgres
# (requires: VERGI_TEST_PG_DSN=<a database with 0001+0002+0003+0004
#  already applied>, PGHOST/PGPORT/PGUSER/PGPASSWORD as needed; install
#  `psycopg` to use the real-driver backend, or set
#  VERGI_TEST_PSQL_BIN so the sandbox-fallback shim can find `psql`)
# ============================================================

import os
import re
import select
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
SRC_DIR = REPO_ROOT / "src"
for p in (REPO_ROOT, SRC_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

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


PG_DB = os.environ.get("VERGI_TEST_PG_DSN")

if not PG_DB:
    print(
        "SKIPPED real PostgreSQL reconciliation-provenance checks - VERGI_TEST_PG_DSN "
        "not set to a reachable disposable database (with 0001+0002+0003+0004 already "
        "applied) in this run. NOT EXECUTED, not a pass."
    )
    print(f"--- test_mutation_reconciliation_provenance_postgres: {passed} passed, {failed} failed ---")
    sys.exit(0)


try:
    import psycopg  # the REAL production driver (see ui/services/db.py) - preferred whenever importable
    PSYCOPG_AVAILABLE = True
except Exception:
    psycopg = None
    PSYCOPG_AVAILABLE = False


def resolve_psql_executable():
    override = os.environ.get("VERGI_TEST_PSQL_BIN")
    if override:
        return override
    return shutil.which("psql")


PSQL_BIN = None
if not PSYCOPG_AVAILABLE:
    PSQL_BIN = resolve_psql_executable()
    if not PSQL_BIN or not Path(PSQL_BIN).is_file():
        check(
            "psql executable resolved (VERGI_TEST_PSQL_BIN or PATH) - required ONLY because "
            "psycopg is not importable in this environment",
            False,
            "VERGI_TEST_PG_DSN is set, `import psycopg` failed, and no usable psql executable "
            "was found via VERGI_TEST_PSQL_BIN or PATH either",
        )
        print(f"--- test_mutation_reconciliation_provenance_postgres: {passed} passed, {failed} failed ---")
        sys.exit(1)

print(
    f"backend: REAL psycopg {getattr(psycopg, '__version__', '?')} (production driver)"
    if PSYCOPG_AVAILABLE else
    "backend: psql-subprocess shim (sandbox fallback - psycopg not importable here)"
)


# ----------------------------------------------------------------
# Minimal DB-API-2.0 shim over ONE long-lived interactive `psql`
# process - SANDBOX FALLBACK ONLY. Same shape and same reasons as
# ui/tests/test_mutation_journal_postgres.py's own copy - see that
# file's header comment for the full rationale; kept as its own copy
# here rather than an import, matching this project's existing
# convention of each real-PostgreSQL test file being self-contained.
# ----------------------------------------------------------------

def _sql_literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"test shim _sql_literal: unsupported param type {type(value)!r} for value {value!r}")


def _inline_params(sql, params):
    if not params:
        return sql
    parts = sql.split("%s")
    if len(parts) - 1 != len(params):
        raise ValueError(f"param count mismatch: {len(params)} params for {len(parts) - 1} placeholders in {sql!r}")
    out = parts[0]
    for value, part in zip(params, parts[1:]):
        out += _sql_literal(value) + part
    return out


_UPDATE_OR_DELETE_WITHOUT_RETURNING = re.compile(r"^\s*(UPDATE|DELETE)\b", re.IGNORECASE)

# ROW 19C-2a: server-emitted NOTICE/WARNING/etc. messages arrive on the
# SAME merged stream as this shim's actual `-t -A` data rows (this
# class's own `PsqlSessionConnection` merges stderr into stdout - see
# below) and are NOT suppressed by `-q` (`-q` only silences psql's OWN
# client-side banners/prompts, never a message the SERVER itself emits,
# e.g. `pg_advisory_unlock()` on a lock this session no longer holds
# emits a real `WARNING:  you don't own a lock of type ExclusiveLock`).
# Section 8's own real-False-release proof (a genuine
# `pg_advisory_unlock_all()` followed by a real `pg_advisory_unlock()`
# on the now-unheld lock) triggers EXACTLY this: without this filter,
# `self._rows[0]` was the WARNING text rather than the real `f` data
# row, so `fetchone()` returned the (non-empty, therefore Python-truthy)
# WARNING string instead of `False` - silently making a real, verified
# False release look like True to `ui.services.mutation_lock.
# release_lock_session()`'s own `bool(released)`. A REAL psycopg cursor
# never has this problem (server NOTICE/WARNING messages go to the
# connection's own `.notices`, never into a result row) - this filter
# exists solely to make this shim match that real behavior.
_SERVER_MESSAGE_PREFIXES = (
    "WARNING:", "NOTICE:", "INFO:", "DEBUG:", "LOG:", "HINT:", "DETAIL:", "CONTEXT:", "STATEMENT:",
)


def _is_server_message_line(line: str) -> bool:
    return line.lstrip().startswith(_SERVER_MESSAGE_PREFIXES)


class PsqlSessionCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        inlined = _inline_params(sql, params)
        to_send = inlined
        stripped = inlined.rstrip().rstrip(";").rstrip()
        if _UPDATE_OR_DELETE_WITHOUT_RETURNING.match(stripped) and "RETURNING" not in stripped.upper():
            to_send = stripped + " RETURNING 1"
        rows = self._conn._run_and_wait(to_send)
        # ROW 19C-2a: unlike ui/tests/test_mutation_journal_postgres.py's
        # own copy of this shim (which never needs to detect a raw SQL
        # error - every check there goes through this project's own
        # rowcount-checked application code, never a directly-expected
        # CHECK-constraint violation), THIS file's section 2 deliberately
        # sends SQL it EXPECTS PostgreSQL to reject, to prove 0004's own
        # CHECK constraints for real. `psql -q -t -A` (this class's own
        # mode) does not itself abort on a statement error and keeps
        # running - it prints "ERROR:  ..." to what this class merges
        # into the same stream (stderr=subprocess.STDOUT) and then still
        # emits the trailing `\echo` marker, so the marker still arrives
        # and `_run_and_wait` would otherwise return normally as if
        # nothing had gone wrong. A REAL psycopg cursor (the OTHER
        # backend this same file also supports) raises a real exception
        # for the exact same failure - so this shim raises here too, to
        # keep both backends' behavior identical for this file's own
        # negative-constraint assertions.
        for line in rows:
            if line.startswith("ERROR:"):
                raise RuntimeError(f"psql reported a real SQL error: {line}")
        # Strip server-emitted NOTICE/WARNING/etc. lines (see
        # `_is_server_message_line`'s own docstring above) BEFORE they
        # can ever reach `fetchone()` as if they were a real data row.
        self._rows = [line for line in rows if not _is_server_message_line(line)]
        self.rowcount = len(self._rows)

    def fetchone(self):
        if not self._rows:
            return None
        line = self._rows[0]

        def _coerce(field):
            # ROW 19C-2a: `psql -t -A` prints a real boolean column as
            # the bare text "t"/"f" - a REAL psycopg cursor auto-
            # converts that to a native Python bool for the caller, but
            # this shim's fetchone() previously returned the raw text
            # unconverted. That is silently wrong for any application
            # code (e.g. ui.services.mutation_lock.release_lock_session's
            # own `bool(released)`) that trusts a driver to hand back a
            # real bool: `bool("f")` is `True` in Python, because "f" is
            # a non-empty STRING - so a genuine SQL `false` was
            # previously indistinguishable from `true` through this
            # shim. No column this project ever fetches is legitimately
            # the literal single-character text "t" or "f" for a
            # non-boolean reason, so this coercion is safe and makes
            # this shim match the real driver's own behavior.
            if field == "":
                return None
            if field == "t":
                return True
            if field == "f":
                return False
            return field

        return tuple(_coerce(field) for field in line.split("|"))


class PsqlSessionConnection:
    """autocommit is psql's own default - matching
    ui.services.db.get_session_lock_connection()'s real contract.
    SANDBOX FALLBACK ONLY."""

    def __init__(self, psql_bin, db):
        self.proc = subprocess.Popen(
            [psql_bin, "-d", db, "-q", "-t", "-A"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0,
        )
        self._marker_n = 0
        self.closed = False
        self._read_buf = b""
        self._stdout_fd = self.proc.stdout.fileno()

    def cursor(self):
        return PsqlSessionCursor(self)

    def _send(self, sql):
        stripped = sql.rstrip()
        terminated = stripped if stripped.endswith(";") else stripped + ";"
        self._marker_n += 1
        marker = f"ROW19C2A_PROV_DONE_{self._marker_n}"
        self.proc.stdin.write((terminated + f"\n\\echo {marker}\n").encode("utf-8"))
        self.proc.stdin.flush()
        return marker

    def _read_line_with_deadline(self, deadline):
        while b"\n" not in self._read_buf:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([self._stdout_fd], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(self._stdout_fd, 65536)
            if chunk == b"":
                raise RuntimeError("psql session closed unexpectedly")
            self._read_buf += chunk
        line, _, rest = self._read_buf.partition(b"\n")
        self._read_buf = rest
        return line.decode("utf-8", errors="replace")

    def _await_marker(self, marker, timeout):
        lines = []
        deadline = time.time() + timeout
        while True:
            line = self._read_line_with_deadline(deadline)
            if line is None:
                return False, lines
            if line == marker:
                return True, lines
            lines.append(line)

    def _run_and_wait(self, sql, timeout=15):
        marker = self._send(sql)
        arrived, lines = self._await_marker(marker, timeout)
        if not arrived:
            raise RuntimeError(f"timed out waiting for psql session to respond to: {sql!r} (got so far: {lines!r})")
        return lines

    def close(self):
        if self.closed:
            return
        try:
            self.proc.stdin.write(b"\\q\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        self.closed = True


def open_conn():
    if PSYCOPG_AVAILABLE:
        return psycopg.connect(dbname=PG_DB, autocommit=True)
    return PsqlSessionConnection(PSQL_BIN, PG_DB)


def close_conn(conn):
    conn.close()


# ----------------------------------------------------------------
# Everything below this point is opted in (VERGI_TEST_PG_DSN set) - a
# broken backend/unreachable database, or a missing 0004 migration, is
# now an explicit FAIL, never a silent skip.
# ----------------------------------------------------------------

from ui.services import mutation_lock as ml            # noqa: E402
from ui.services import mutation_registry as mr         # noqa: E402
from mutation_guard import MutationIntent, compute_idempotency_key, compute_request_fingerprint  # noqa: E402


def _insert_raw_journal_row(conn, *, resource_key, action_family, target_ref, state,
                             executing_at_now=False, resolution_code=None, resolved_at_now=False,
                             reconciled_by_actor_type=None, reconciled_by_actor_ref=None):
    """Test-only helper: inserts a row directly, exactly the shape a
    real coordinator/reconciliation write would leave, for scenarios
    this file needs to seed directly rather than drive through
    run_mutation()."""
    intent = MutationIntent(
        actor_type="cli_service", actor_ref="row19c2a_prov_test_actor",
        resource_key=resource_key, action_family=action_family, target_ref=target_ref,
    )
    key = compute_idempotency_key(intent)
    fp = compute_request_fingerprint(intent)
    columns = ["resource_key", "action_family", "actor_label", "target_ref", "idempotency_key", "request_fingerprint", "state"]
    values = [resource_key, action_family, "row19c2a_prov_test_actor", target_ref, key, fp, state]
    if executing_at_now:
        columns.append("executing_at")
        values.append(None)  # placeholder - replaced by now() in SQL text below
    if resolution_code is not None:
        columns.append("resolution_code")
        values.append(resolution_code)
    if resolved_at_now:
        columns.append("resolved_at")
        values.append(None)  # placeholder - replaced by now() in SQL text below
    if reconciled_by_actor_type is not None:
        columns.append("reconciled_by_actor_type")
        values.append(reconciled_by_actor_type)
    if reconciled_by_actor_ref is not None:
        columns.append("reconciled_by_actor_ref")
        values.append(reconciled_by_actor_ref)

    placeholders = []
    final_values = []
    for col, val in zip(columns, values):
        if col in ("executing_at", "resolved_at") and val is None:
            placeholders.append("now()")
        else:
            placeholders.append("%s")
            final_values.append(val)

    sql = (
        f"INSERT INTO mutation.mutation_journal ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) RETURNING id"
    )
    with conn.cursor() as cur:
        cur.execute(sql, tuple(final_values))
        (journal_id,) = cur.fetchone()
    return int(journal_id), key


class RealAdapter:
    def __init__(self, post_state_verified, pre_state_confirmed_unchanged, observed_post_hash=None):
        self._post = post_state_verified
        self._pre = pre_state_confirmed_unchanged
        self._hash = observed_post_hash

    def gather_evidence(self, entry):
        return mr.ReconciliationEvidence(
            post_state_verified=self._post, pre_state_confirmed_unchanged=self._pre,
            observed_post_hash=self._hash,
        )


try:
    # ------------------------------------------------------------
    # 1) 0004's own schema shape - both new columns exist, are
    #    nullable, and are visible via information_schema, against the
    #    REAL, already-migrated database.
    # ------------------------------------------------------------
    conn_schema = open_conn()
    try:
        with conn_schema.cursor() as cur:
            cur.execute(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'mutation' AND table_name = 'mutation_journal' "
                "AND column_name IN ('reconciled_by_actor_type', 'reconciled_by_actor_ref') "
                "ORDER BY column_name"
            )
            with conn_schema.cursor() as cur2:
                cur2.execute(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'mutation' AND table_name = 'mutation_journal' "
                    "AND column_name = 'reconciled_by_actor_ref'"
                )
                actor_ref_row = cur2.fetchone()
            with conn_schema.cursor() as cur3:
                cur3.execute(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'mutation' AND table_name = 'mutation_journal' "
                    "AND column_name = 'reconciled_by_actor_type'"
                )
                actor_type_row = cur3.fetchone()
        check(
            "0004: reconciled_by_actor_type column exists and is nullable, against the REAL database",
            actor_type_row is not None and actor_type_row[1] == "YES",
            f"got {actor_type_row!r}",
        )
        check(
            "0004: reconciled_by_actor_ref column exists and is nullable, against the REAL database",
            actor_ref_row is not None and actor_ref_row[1] == "YES",
            f"got {actor_ref_row!r}",
        )
    finally:
        close_conn(conn_schema)

    # ------------------------------------------------------------
    # 2) 0004's four CHECK constraints, each proven for REAL by
    #    attempting an UPDATE that violates exactly one of them and
    #    confirming PostgreSQL itself rejects it (a real constraint
    #    violation surfacing as a real driver exception), against a
    #    genuinely inserted, already-resolved row.
    # ------------------------------------------------------------
    conn_constraints = open_conn()
    try:
        constraints_case_id = f"__row19c2a_pg_constraints_{uuid.uuid4().hex[:8]}__"
        # acquire_case_lock_session() race-safely creates this
        # resource's row in mutation.mutation_resources - required
        # BEFORE any INSERT into mutation.mutation_journal, whose
        # resource_key column is a real FK into that table.
        ml.acquire_case_lock_session(conn_constraints, constraints_case_id)
        ml.release_lock_session(conn_constraints, ml._get_or_create_resource_advisory_lock_id(conn_constraints, ml.case_resource_key(constraints_case_id)))
        resolved_journal_id, _ = _insert_raw_journal_row(
            conn_constraints, resource_key=f"case:{constraints_case_id}",
            action_family="fam.row19c2a_prov_constraints_test", target_ref="target_constraints",
            state="completed", executing_at_now=True,
            resolution_code="reconciled_completed_post_state_verified", resolved_at_now=True,
        )

        def _try_update(sql, params, label):
            try:
                with conn_constraints.cursor() as cur:
                    cur.execute(sql, params)
                check(label, False, "no constraint violation was raised")
            except Exception as error:
                message = str(error).lower()
                check(
                    label,
                    "constraint" in message or "violat" in message or "check" in message,
                    f"expected a real CHECK-constraint violation, got: {error!r}",
                )

        # 2a) Closed actor-type set.
        _try_update(
            "UPDATE mutation.mutation_journal SET reconciled_by_actor_type = %s, reconciled_by_actor_ref = %s WHERE id = %s",
            ("not_a_real_actor_type", "some_ref", resolved_journal_id),
            "0004 constraint 1 (closed actor-type set): an unrecognized reconciled_by_actor_type is REJECTED by the REAL database",
        )

        # 2b) Non-blank/length-bounded actor_ref - blank.
        _try_update(
            "UPDATE mutation.mutation_journal SET reconciled_by_actor_type = %s, reconciled_by_actor_ref = %s WHERE id = %s",
            ("cli_service", "   ", resolved_journal_id),
            "0004 constraint 2 (actor_ref shape): a whitespace-only reconciled_by_actor_ref is REJECTED by the REAL database",
        )
        # 2b-2) Non-blank/length-bounded actor_ref - too long (256 chars).
        _try_update(
            "UPDATE mutation.mutation_journal SET reconciled_by_actor_type = %s, reconciled_by_actor_ref = %s WHERE id = %s",
            ("cli_service", "x" * 256, resolved_journal_id),
            "0004 constraint 2 (actor_ref shape): a 256-character reconciled_by_actor_ref is REJECTED by the REAL database",
        )

        # 2c) Both-or-neither pairing - only actor_type set.
        _try_update(
            "UPDATE mutation.mutation_journal SET reconciled_by_actor_type = %s, reconciled_by_actor_ref = NULL WHERE id = %s",
            ("cli_service", resolved_journal_id),
            "0004 constraint 3 (both-or-neither): reconciled_by_actor_type alone (actor_ref NULL) is REJECTED by the REAL database",
        )

        # 2d) Provenance-implies-resolved pairing - provenance on an
        # UNRESOLVED row.
        unresolved_case_id = f"__row19c2a_pg_constraints_unresolved_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_constraints, unresolved_case_id)
        ml.release_lock_session(conn_constraints, ml._get_or_create_resource_advisory_lock_id(conn_constraints, ml.case_resource_key(unresolved_case_id)))
        unresolved_journal_id, _ = _insert_raw_journal_row(
            conn_constraints, resource_key=f"case:{unresolved_case_id}",
            action_family="fam.row19c2a_prov_constraints_unresolved_test", target_ref="target_unresolved",
            state="executing", executing_at_now=True,
        )
        _try_update(
            "UPDATE mutation.mutation_journal SET reconciled_by_actor_type = %s, reconciled_by_actor_ref = %s WHERE id = %s",
            ("cli_service", "some_ref", unresolved_journal_id),
            "0004 constraint 4 (provenance implies resolved): provenance on a still-UNRESOLVED "
            "('executing') row is REJECTED by the REAL database",
        )

        # 2e) Sanity: a FULLY valid provenance pairing on an
        # already-resolved row IS accepted.
        with conn_constraints.cursor() as cur:
            cur.execute(
                "UPDATE mutation.mutation_journal SET reconciled_by_actor_type = %s, reconciled_by_actor_ref = %s WHERE id = %s",
                ("cli_service", "row19c2a_valid_ref", resolved_journal_id),
            )
        with conn_constraints.cursor() as cur:
            cur.execute(
                "SELECT reconciled_by_actor_type, reconciled_by_actor_ref FROM mutation.mutation_journal WHERE id = %s",
                (resolved_journal_id,),
            )
            valid_row = cur.fetchone()
        check(
            "0004: a FULLY valid provenance pairing on an already-resolved row IS accepted by the REAL database",
            valid_row == ("cli_service", "row19c2a_valid_ref"),
            f"got {valid_row!r}",
        )
    finally:
        close_conn(conn_constraints)

    # ------------------------------------------------------------
    # 3) reconcile_and_apply_journal_entry() with resolved_by_actor_type/
    #    ref against a REAL 'executing'-origin row - writes provenance
    #    in the SAME atomic UPDATE, queried back fresh.
    # ------------------------------------------------------------
    conn_apply = open_conn()
    try:
        apply_case_id = f"__row19c2a_pg_prov_apply_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_apply, apply_case_id)
        apply_journal_id, apply_key = _insert_raw_journal_row(
            conn_apply, resource_key=f"case:{apply_case_id}",
            action_family="fam.row19c2a_prov_apply_test", target_ref="target_prov_apply",
            state="executing", executing_at_now=True,
        )
        apply_registry = mr.MutationAdapterRegistry().with_adapter(
            "fam.row19c2a_prov_apply_test", RealAdapter(True, False, observed_post_hash="prov_apply_hash"),
        )
        apply_outcome = mr.reconcile_and_apply_journal_entry(
            conn_apply, apply_journal_id, apply_registry,
            resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c2a_real_operator",
        )
        check("reconcile_and_apply_journal_entry() with provenance, against a REAL row, returns new_state='completed'", apply_outcome.new_state == "completed")

        with conn_apply.cursor() as cur:
            cur.execute(
                "SELECT state, resolution_code, reconciled_by_actor_type, reconciled_by_actor_ref, idempotency_key "
                "FROM mutation.mutation_journal WHERE id = %s",
                (apply_journal_id,),
            )
            apply_row = cur.fetchone()
        check(
            "the REAL row (queried back fresh) carries the exact provenance passed to reconcile_and_apply_journal_entry(), "
            "written in the SAME atomic UPDATE as the resolution itself",
            apply_row is not None
            and apply_row[0] == "completed"
            and apply_row[1] == "reconciled_completed_post_state_verified"
            and apply_row[2] == "cli_service"
            and apply_row[3] == "row19c2a_real_operator"
            and apply_row[4] == apply_key,
            f"got {apply_row!r}",
        )
    finally:
        ml.release_lock_session(conn_apply, ml._get_or_create_resource_advisory_lock_id(conn_apply, ml.case_resource_key(apply_case_id)))
        close_conn(conn_apply)

    # ------------------------------------------------------------
    # 4) reconcile_and_apply_journal_entry() with provenance against a
    #    REAL 'prepared'-origin row (the never-executed branch) - also
    #    recorded there, for real.
    # ------------------------------------------------------------
    conn_prepared = open_conn()
    try:
        prepared_case_id = f"__row19c2a_pg_prov_prepared_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_prepared, prepared_case_id)
        prepared_journal_id, _ = _insert_raw_journal_row(
            conn_prepared, resource_key=f"case:{prepared_case_id}",
            action_family="fam.row19c2a_prov_prepared_test", target_ref="target_prov_prepared",
            state="prepared",
        )
        prepared_registry = mr.MutationAdapterRegistry().with_adapter(
            "fam.row19c2a_prov_prepared_test", RealAdapter(False, True),
        )
        prepared_outcome = mr.reconcile_and_apply_journal_entry(
            conn_prepared, prepared_journal_id, prepared_registry,
            resolved_by_actor_type="cli_service", resolved_by_actor_ref="row19c2a_real_operator_prepared",
        )
        check(
            "reconcile_and_apply_journal_entry() with provenance, against a REAL 'prepared'-origin row, "
            "resolves to 'failed' via the prepared-never-executed resolution_code",
            prepared_outcome.new_state == "failed"
            and prepared_outcome.resolution_code == "reconciled_failed_prepared_never_executed",
        )
        with conn_prepared.cursor() as cur:
            cur.execute(
                "SELECT state, executing_at IS NULL, reconciled_by_actor_type, reconciled_by_actor_ref "
                "FROM mutation.mutation_journal WHERE id = %s",
                (prepared_journal_id,),
            )
            prepared_row = cur.fetchone()
        check(
            "the REAL prepared-never-executed row carries the provenance, with executing_at STILL NULL "
            "(the writer was never invoked - provenance does not change that fact)",
            prepared_row == ("failed", True, "cli_service", "row19c2a_real_operator_prepared"),
            f"got {prepared_row!r}",
        )
    finally:
        ml.release_lock_session(conn_prepared, ml._get_or_create_resource_advisory_lock_id(conn_prepared, ml.case_resource_key(prepared_case_id)))
        close_conn(conn_prepared)

    # ------------------------------------------------------------
    # 5) reconcile_and_apply_journal_entry() WITHOUT provenance, against
    #    a REAL row - stays NULL, exactly matching this project's
    #    pre-Row-19C-2a behavior, proving full backward compatibility.
    # ------------------------------------------------------------
    conn_no_prov = open_conn()
    try:
        no_prov_case_id = f"__row19c2a_pg_no_prov_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_no_prov, no_prov_case_id)
        no_prov_journal_id, _ = _insert_raw_journal_row(
            conn_no_prov, resource_key=f"case:{no_prov_case_id}",
            action_family="fam.row19c2a_no_prov_test", target_ref="target_no_prov",
            state="executing", executing_at_now=True,
        )
        no_prov_registry = mr.MutationAdapterRegistry().with_adapter(
            "fam.row19c2a_no_prov_test", RealAdapter(True, False, observed_post_hash="no_prov_hash"),
        )
        mr.reconcile_and_apply_journal_entry(conn_no_prov, no_prov_journal_id, no_prov_registry)
        with conn_no_prov.cursor() as cur:
            cur.execute(
                "SELECT reconciled_by_actor_type, reconciled_by_actor_ref FROM mutation.mutation_journal WHERE id = %s",
                (no_prov_journal_id,),
            )
            no_prov_row = cur.fetchone()
        check(
            "reconcile_and_apply_journal_entry() called WITHOUT provenance kwargs leaves both columns NULL "
            "on a REAL row - full backward compatibility with every pre-Row-19C-2a call site",
            no_prov_row == (None, None),
            f"got {no_prov_row!r}",
        )
    finally:
        ml.release_lock_session(conn_no_prov, ml._get_or_create_resource_advisory_lock_id(conn_no_prov, ml.case_resource_key(no_prov_case_id)))
        close_conn(conn_no_prov)

    # ------------------------------------------------------------
    # 6) inspect_reconciliation() against the REAL database: returns
    #    the outcome a real --apply run would produce, issues ZERO
    #    UPDATEs (row completely unchanged before/after), and the lock
    #    it took is genuinely released afterward (proven by a REAL,
    #    subsequent reconcile_and_apply_journal_entry() on the SAME row
    #    completing promptly rather than hanging).
    # ------------------------------------------------------------
    conn_inspect = open_conn()
    try:
        inspect_case_id = f"__row19c2a_pg_inspect_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_inspect, inspect_case_id)
        inspect_journal_id, inspect_key = _insert_raw_journal_row(
            conn_inspect, resource_key=f"case:{inspect_case_id}",
            action_family="fam.row19c2a_inspect_test", target_ref="target_inspect",
            state="executing", executing_at_now=True,
        )

        with conn_inspect.cursor() as cur:
            cur.execute(
                "SELECT state, resolution_code, reconciled_by_actor_type, reconciled_by_actor_ref, resolved_at "
                "FROM mutation.mutation_journal WHERE id = %s",
                (inspect_journal_id,),
            )
            before_row = cur.fetchone()

        inspect_registry = mr.MutationAdapterRegistry().with_adapter(
            "fam.row19c2a_inspect_test", RealAdapter(True, False, observed_post_hash="inspect_would_be_hash"),
        )
        inspect_outcome = mr.inspect_reconciliation(conn_inspect, inspect_journal_id, inspect_registry)
        check(
            "inspect_reconciliation() against the REAL database returns the outcome a real --apply run would produce",
            inspect_outcome.new_state == "completed" and inspect_outcome.observed_post_hash == "inspect_would_be_hash",
        )

        with conn_inspect.cursor() as cur:
            cur.execute(
                "SELECT state, resolution_code, reconciled_by_actor_type, reconciled_by_actor_ref, resolved_at "
                "FROM mutation.mutation_journal WHERE id = %s",
                (inspect_journal_id,),
            )
            after_row = cur.fetchone()
        check(
            "inspect_reconciliation() left the REAL row COMPLETELY unchanged - ZERO UPDATEs, ever",
            before_row == after_row,
            f"before={before_row!r} after={after_row!r}",
        )

        # The lock inspect_reconciliation() took must be genuinely
        # released - proven by a REAL, subsequent
        # reconcile_and_apply_journal_entry() call on the SAME
        # resource, on this SAME connection, completing normally
        # (were the lock still held by this same session, PostgreSQL's
        # session-level advisory locks are re-entrant for the SAME
        # session, so this alone would not detect a leak from THIS
        # connection - the real, decisive proof is the DIFFERENT-
        # session blocking/release proof already covered end-to-end in
        # test_mutation_journal_postgres.py; this assertion instead
        # confirms the practical, end-to-end consequence for THIS
        # connection: a subsequent real apply call on the same row
        # behaves completely normally after a dry-run inspection).
        apply_after_inspect_outcome = mr.reconcile_and_apply_journal_entry(conn_inspect, inspect_journal_id, inspect_registry)
        check(
            "a REAL reconcile_and_apply_journal_entry() call on the SAME row, right after inspect_reconciliation(), "
            "completes normally and applies for real",
            apply_after_inspect_outcome.new_state == "completed",
        )
        with conn_inspect.cursor() as cur:
            cur.execute("SELECT state FROM mutation.mutation_journal WHERE id = %s", (inspect_journal_id,))
            (final_inspect_state,) = cur.fetchone()
        check("the row is durably 'completed' after the real apply that followed the dry-run inspection", final_inspect_state == "completed")
    finally:
        ml.release_lock_session(conn_inspect, ml._get_or_create_resource_advisory_lock_id(conn_inspect, ml.case_resource_key(inspect_case_id)))
        close_conn(conn_inspect)

    # ------------------------------------------------------------
    # 7) inspect_reconciliation() against a REAL, unresolvable
    #    'prepared'-origin row - raises PreparedJournalUnresolvedError,
    #    exactly like the real --apply path would, with ZERO UPDATEs.
    # ------------------------------------------------------------
    conn_inspect_prepared = open_conn()
    try:
        inspect_prepared_case_id = f"__row19c2a_pg_inspect_prepared_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_inspect_prepared, inspect_prepared_case_id)
        inspect_prepared_journal_id, _ = _insert_raw_journal_row(
            conn_inspect_prepared, resource_key=f"case:{inspect_prepared_case_id}",
            action_family="fam.row19c2a_inspect_prepared_test", target_ref="target_inspect_prepared",
            state="prepared",
        )
        inspect_prepared_registry = mr.MutationAdapterRegistry().with_adapter(
            "fam.row19c2a_inspect_prepared_test", RealAdapter(False, False),
        )
        expect_raises(
            mr.PreparedJournalUnresolvedError,
            lambda: mr.inspect_reconciliation(conn_inspect_prepared, inspect_prepared_journal_id, inspect_prepared_registry),
            "inspect_reconciliation() against a REAL unresolvable 'prepared' row raises PreparedJournalUnresolvedError too",
        )
        with conn_inspect_prepared.cursor() as cur:
            cur.execute(
                "SELECT state, executing_at IS NULL, resolved_at IS NULL FROM mutation.mutation_journal WHERE id = %s",
                (inspect_prepared_journal_id,),
            )
            still_prepared_row = cur.fetchone()
        check(
            "the REAL row is left COMPLETELY untouched (still 'prepared', executing_at/resolved_at still NULL) "
            "after inspect_reconciliation() raises PreparedJournalUnresolvedError",
            still_prepared_row == ("prepared", True, True),
            f"got {still_prepared_row!r}",
        )
    finally:
        ml.release_lock_session(conn_inspect_prepared, ml._get_or_create_resource_advisory_lock_id(conn_inspect_prepared, ml.case_resource_key(inspect_prepared_case_id)))
        close_conn(conn_inspect_prepared)

    # ------------------------------------------------------------
    # 8) ROW 19C-2a FAIL-CLOSED UNLOCK DISCIPLINE, proven for REAL via
    #    CONTROLLED real-DB failure injection: a test-only adapter,
    #    given the SAME real connection/session by closure, calls
    #    `pg_advisory_unlock_all()` on it DURING its own
    #    gather_evidence() - a genuine, real release of every advisory
    #    lock this session holds, including the one
    #    inspect_reconciliation()/reconcile_and_apply_journal_entry()
    #    itself just acquired for this call. When that function's own
    #    `finally` then calls `pg_advisory_unlock()` for real, it
    #    genuinely, for real, returns False (this session no longer
    #    holds it) - no monkeypatching of `ui.services.mutation_lock`
    #    itself anywhere in this section.
    # ------------------------------------------------------------

    class SelfUnlockingAdapter:
        """TEST-ONLY - violates the locking discipline it has no
        license to violate, exactly like
        test_mutation_journal_postgres.py's own `OutOfBandBypassAdapter`
        - but releases THIS SAME session's advisory locks (not a
        separate connection's), which is exactly the real condition
        needed to make a REAL `pg_advisory_unlock()` call return False
        for real."""

        def __init__(self, conn, post_state_verified, pre_state_confirmed_unchanged, observed_post_hash=None):
            self._conn = conn
            self._post = post_state_verified
            self._pre = pre_state_confirmed_unchanged
            self._hash = observed_post_hash

        def gather_evidence(self, entry):
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock_all()")
            return mr.ReconciliationEvidence(
                post_state_verified=self._post, pre_state_confirmed_unchanged=self._pre,
                observed_post_hash=self._hash,
            )

    # 8a) inspect_reconciliation() - a REAL False release with NO other
    # exception propagating -> LockReleaseAnomalyError, for real.
    conn_anomaly = open_conn()
    try:
        anomaly_case_id = f"__row19c2a_pg_anomaly_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_anomaly, anomaly_case_id)
        # Release the ABOVE acquire_case_lock_session's own lock first,
        # so this section starts this session with a clean advisory-lock
        # slate before inspect_reconciliation() takes its own.
        ml.release_lock_session(conn_anomaly, ml._get_or_create_resource_advisory_lock_id(conn_anomaly, ml.case_resource_key(anomaly_case_id)))

        anomaly_journal_id, _ = _insert_raw_journal_row(
            conn_anomaly, resource_key=f"case:{anomaly_case_id}",
            action_family="fam.row19c2a_anomaly_test", target_ref="target_anomaly",
            state="executing", executing_at_now=True,
        )
        anomaly_registry = mr.MutationAdapterRegistry().with_adapter(
            "fam.row19c2a_anomaly_test", SelfUnlockingAdapter(conn_anomaly, True, False, observed_post_hash="anomaly_hash"),
        )
        expect_raises(
            mr.LockReleaseAnomalyError,
            lambda: mr.inspect_reconciliation(conn_anomaly, anomaly_journal_id, anomaly_registry),
            "against the REAL database: inspect_reconciliation() raises LockReleaseAnomalyError for real "
            "when the session's advisory lock was genuinely already released out from under it",
        )
        with conn_anomaly.cursor() as cur:
            cur.execute("SELECT state FROM mutation.mutation_journal WHERE id = %s", (anomaly_journal_id,))
            (anomaly_state,) = cur.fetchone()
        check(
            "against the REAL database: the row is left COMPLETELY untouched despite the LockReleaseAnomalyError "
            "(inspect_reconciliation() issues zero UPDATEs regardless)",
            anomaly_state == "executing",
        )
    finally:
        close_conn(conn_anomaly)

    # 8b) reconcile_and_apply_journal_entry() - the SAME real False
    # release, but this time the UPDATE already succeeded for real
    # before the release runs - must NOT raise; the already-applied,
    # already-durable outcome must be returned exactly as if the
    # release had succeeded, with the anomaly only logged.
    conn_apply_false_release = open_conn()
    _original_log_critical_safely_pg2 = mr._log_critical_safely
    _critical_log_calls_pg2 = []
    mr._log_critical_safely = lambda message: _critical_log_calls_pg2.append(message)
    try:
        apply_false_release_case_id = f"__row19c2a_pg_apply_false_release_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_apply_false_release, apply_false_release_case_id)
        ml.release_lock_session(
            conn_apply_false_release,
            ml._get_or_create_resource_advisory_lock_id(conn_apply_false_release, ml.case_resource_key(apply_false_release_case_id)),
        )

        apply_false_release_journal_id, _ = _insert_raw_journal_row(
            conn_apply_false_release, resource_key=f"case:{apply_false_release_case_id}",
            action_family="fam.row19c2a_apply_false_release_test", target_ref="target_apply_false_release",
            state="executing", executing_at_now=True,
        )
        apply_false_release_registry = mr.MutationAdapterRegistry().with_adapter(
            "fam.row19c2a_apply_false_release_test",
            SelfUnlockingAdapter(conn_apply_false_release, True, False, observed_post_hash="apply_false_release_hash"),
        )
        apply_false_release_outcome = mr.reconcile_and_apply_journal_entry(
            conn_apply_false_release, apply_false_release_journal_id, apply_false_release_registry,
        )
        check(
            "against the REAL database: reconcile_and_apply_journal_entry() NEVER raises on a genuinely-False "
            "real lock release - it returns the outcome it already durably applied",
            apply_false_release_outcome.new_state == "completed",
        )
        with conn_apply_false_release.cursor() as cur:
            cur.execute("SELECT state, observed_post_hash FROM mutation.mutation_journal WHERE id = %s", (apply_false_release_journal_id,))
            apply_false_release_row = cur.fetchone()
        check(
            "against the REAL database: the row WAS still durably updated to 'completed' despite the real False release",
            apply_false_release_row == ("completed", "apply_false_release_hash"),
            f"got {apply_false_release_row!r}",
        )
        check(
            "against the REAL database: the genuinely-False lock release was CRITICALLY logged exactly once",
            len(_critical_log_calls_pg2) == 1,
            f"got {_critical_log_calls_pg2!r}",
        )
    finally:
        mr._log_critical_safely = _original_log_critical_safely_pg2
        close_conn(conn_apply_false_release)

except Exception as error:
    check(
        "the full real-PostgreSQL reconciliation-provenance suite completed without an unexpected exception",
        False,
        repr(error),
    )

print(f"--- test_mutation_reconciliation_provenance_postgres: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
