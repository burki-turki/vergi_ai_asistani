# ============================================================
# Row 19C-1 - REAL, two-connection PostgreSQL proof for
# ui/services/mutation_lock.py's session-level lock primitives,
# ui/services/mutation_coordinator.py's run_mutation(), and
# ui/services/mutation_registry.py's reconcile_journal_entry() -
# against an actual, disposable PostgreSQL database, not a fake
# connection.
#
# WHY THIS FILE EXISTS SEPARATELY FROM THE FAKE-CONN ISOLATED TESTS
# ----------------------------------------------------------------
# ui/tests/test_mutation_lock_isolated.py, test_mutation_coordinator_isolated.py
# and test_reconciliation_isolated.py all prove this project's OWN
# ordering/gating/classification LOGIC against in-memory fakes - they
# cannot prove two things only a real database can: (1) that the
# actual SQL text is valid, executable PostgreSQL end-to-end, and (2)
# genuine CROSS-CONNECTION concurrency - a session-level
# `pg_advisory_lock` held by one real connection actually BLOCKING a
# second, independent real connection's attempt on the same lock id,
# and PostgreSQL's own guarantee that an uncleanly-dropped connection
# auto-releases its locks. A single one-shot `psql -c "..."` call (as
# used by test_mutation_lock_isolated.py's own real-DB section)
# opens and closes its own connection immediately, so it can prove a
# lock+unlock ROUND TRIP within one session, but never mutual
# exclusion ACROSS two live sessions - that is exactly this file's
# job.
#
# TWO BACKENDS - ROW 19C-1 WINDOWS JOURNAL HARNESS REMEDIATION
# ----------------------------------------------------------------
# This file now PREFERS a REAL `psycopg` connection - the actual
# production driver (see ui/services/db.py) - whenever `psycopg` is
# importable in the running environment. `PsqlSessionConnection` below
# (ONE long-lived interactive `psql` subprocess per "connection",
# exposing just enough of the DB-API 2.0 shape -
# `conn.cursor()`/`cur.execute(sql, params)`/`cur.fetchone()` - to
# drive the REAL, unmodified `ui.services.mutation_lock`/
# `ui.services.mutation_coordinator`/`ui.services.mutation_registry`
# code paths for real) now exists ONLY as a FALLBACK for an
# environment where `psycopg` genuinely cannot be installed (this
# sandbox: no network access to PyPI or the OS package archive -
# confirmed again this round). Both backends drive the exact same
# production code through the exact same `conn.cursor()`/`execute()`/
# `fetchone()` shape, and every assertion below is written to hold
# identically under either one (see `_pg_bool()`/`_pg_int()` just
# below `PsqlSessionConnection` - the ONE place the two backends'
# differing native-type-vs-text result shapes are reconciled, rather
# than scattering backend-specific comparisons through the test
# bodies).
#
# WHY THIS MATTERS: THE WINDOWS OSError(10093, WSANOTINITIALISED) BUG
# ----------------------------------------------------------------
# On a real Windows/psycopg-available run, `test_mutation_journal_postgres`
# previously failed immediately with
# `OSError(10093, "WSAStartup was not called or WSAStartup failed")`
# even though `test_iam_migrations_isolated` and
# `test_mutation_lock_isolated` (which use `psql` one-shot calls, or a
# fake conn, but never this file's own interactive-subprocess shim)
# passed cleanly in the SAME environment. The EXACT function/statement
# that produced it: `PsqlSessionConnection._read_line_with_deadline()`'s
# `select.select([self._stdout_fd], [], [], remaining)` call, where
# `self._stdout_fd` is `self.proc.stdout.fileno()` - the raw OS pipe
# file descriptor of an interactive `psql` child process spawned via
# `subprocess.Popen(..., stdout=subprocess.PIPE)`.
#
# WHY IT HAPPENED ON WINDOWS SPECIFICALLY: `select.select()` is
# implemented on top of Winsock on Windows, and Winsock's `select()`
# accepts ONLY genuine SOCKET handles - never an anonymous pipe handle
# (which is what `subprocess.PIPE` actually creates for a child
# process's stdout on Windows). Handing it a non-socket handle does
# not raise a normal "bad file descriptor" error the way POSIX would;
# instead Winsock's own initialization check rejects the call outright
# with error code 10093 (WSANOTINITIALISED / "successful WSAStartup
# not yet performed"), which Python surfaces as a plain `OSError`. On
# POSIX (this sandbox, and any Linux/macOS runtime), `select()` has no
# such restriction - it operates on any readable file descriptor,
# pipes included - which is exactly why this bug was invisible here
# and only ever showed up on the Windows target runtime. This was
# ALWAYS a property of this TEST FILE's own optional fallback shim -
# nothing in this project's OWN production code
# (ui.services.db/mutation_lock/mutation_coordinator/mutation_registry)
# ever calls `select()`, and no production code path is implicated.
#
# THE FIX: prefer `psycopg` (a real, cross-platform driver that never
# touches `select()` on a raw pipe) whenever it is importable - which
# it is on the reported Windows environment (`psycopg==3.3.5`) - and
# reserve `PsqlSessionConnection`'s `select()`-based shim for the
# narrower case where `psycopg` truly cannot be installed at all (this
# sandbox). The shim's own internals are otherwise UNCHANGED - it
# remains exactly as correct on POSIX as before.
#
# SKIPPED with an explicit message if no reachable PostgreSQL is
# configured for this run via VERGI_TEST_PG_DSN (never silently
# treated as a pass) - matching this project's other real-DB test
# files' own contract.
#
# Run: python -m ui.tests.test_mutation_journal_postgres
# (requires: VERGI_TEST_PG_DSN=<a database with 0001+0002+0003
#  already applied>, PGHOST/PGPORT/PGUSER/PGPASSWORD as needed;
#  install `psycopg` in this Python environment to use the real-driver
#  backend - REQUIRED on Windows, since the `psql`-subprocess shim's
#  own `select()`-based fallback cannot run there, see above - or,
#  where `psycopg` is unavailable, set VERGI_TEST_PSQL_BIN so the
#  sandbox-fallback shim can find `psql`)
# ============================================================

import os
import queue
import re
import select
import shutil
import subprocess
import sys
import threading
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
        "SKIPPED real two-connection PostgreSQL checks - VERGI_TEST_PG_DSN "
        "not set to a reachable disposable database (with 0001+0002+0003 "
        "already applied) in this run. NOT EXECUTED, not a pass."
    )
    print(f"--- test_mutation_journal_postgres: {passed} passed, {failed} failed ---")
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
    # `psql` is ONLY required as a fallback when the real driver is not
    # importable - a `psycopg`-available environment (e.g. the Windows
    # local runtime target) never needs it for this file at all.
    PSQL_BIN = resolve_psql_executable()
    if not PSQL_BIN or not Path(PSQL_BIN).is_file():
        check(
            "psql executable resolved (VERGI_TEST_PSQL_BIN or PATH) - required ONLY because "
            "psycopg is not importable in this environment",
            False,
            "VERGI_TEST_PG_DSN is set, `import psycopg` failed, and no usable psql executable "
            "was found via VERGI_TEST_PSQL_BIN or PATH either",
        )
        print(f"--- test_mutation_journal_postgres: {passed} passed, {failed} failed ---")
        sys.exit(1)

print(
    f"backend: REAL psycopg {getattr(psycopg, '__version__', '?')} (production driver)"
    if PSYCOPG_AVAILABLE else
    "backend: psql-subprocess shim (sandbox fallback - psycopg not importable here)"
)


# ----------------------------------------------------------------
# Minimal DB-API-2.0 shim over ONE long-lived interactive `psql`
# process - SANDBOX FALLBACK ONLY (see the module docstring above).
# Untouched by this remediation: still exactly as correct on POSIX as
# before: it is simply no longer reached at all when `psycopg` is
# importable.
# ----------------------------------------------------------------

def _sql_literal(value):
    """Deliberately supports ONLY the three Python types this
    project's own mutation_lock.py/mutation_coordinator.py/
    mutation_registry.py ever pass as a query parameter (str, int,
    None) - this is test-only glue for a fixed, already-known set of
    call sites, NOT a general-purpose SQL parameter binder, and it
    must never be mistaken for one or reused anywhere else. A real
    driver (psycopg) is what production code uses; this exists only
    for the environment where psycopg cannot be installed."""
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


class PsqlSessionCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self.rowcount = -1  # DB-API-2.0 default before any execute()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        inlined = _inline_params(sql, params)
        # ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION: production
        # code (ui.services.mutation_registry's guarded reconciliation
        # UPDATE) now reads `cur.rowcount` after an UPDATE, exactly as
        # a real psycopg cursor already reports it natively. This shim
        # is `psql -t -A` (tuples-only) mode, which suppresses psql's
        # own "UPDATE n" command tag entirely - so, ONLY for an
        # UPDATE/DELETE that does not already carry its own RETURNING
        # clause, this appends `RETURNING 1` before sending the
        # statement and derives `.rowcount` from how many rows come
        # back. This never changes what production code's own SQL
        # actually modifies (RETURNING does not affect which rows an
        # UPDATE/DELETE touches) and the extra returned column is never
        # read via fetchone() for these statements - only its COUNT is
        # used. A real psycopg cursor needs none of this: `.rowcount`
        # is simply always accurate there already.
        to_send = inlined
        stripped = inlined.rstrip().rstrip(";").rstrip()
        if _UPDATE_OR_DELETE_WITHOUT_RETURNING.match(stripped) and "RETURNING" not in stripped.upper():
            to_send = stripped + " RETURNING 1"
        self._rows = self._conn._run_and_wait(to_send)
        self.rowcount = len(self._rows)

    def fetchone(self):
        if not self._rows:
            return None
        line = self._rows[0]
        return tuple(None if field == "" else field for field in line.split("|"))


class PsqlSessionConnection:
    """autocommit is psql's own default (no BEGIN issued unless a
    caller explicitly runs one) - matching
    ui.services.db.get_session_lock_connection()'s real contract.
    SANDBOX FALLBACK ONLY - see this module's own header comment for
    why this is never used at all when `psycopg` is importable, and
    exactly what Windows-only failure mode that avoids."""

    def __init__(self, psql_bin, db):
        # bufsize=0 + NO text=True: raw, unbuffered binary pipes. This
        # is deliberate, not an oversight - see `_read_line_with_deadline`'s
        # docstring for why mixing `select.select()` with a Python
        # TextIOWrapper's OWN internal read-ahead buffering is a real
        # bug (caught during this file's own first real run - a
        # buffered `readline()` can silently consume MULTIPLE lines
        # from one OS-level read, including a line `select()` never
        # gets to see as "newly ready" on the raw fd, causing a
        # spurious timeout on data that had, in fact, already arrived).
        # `select()` on this fd is itself POSIX-only-safe - see the
        # module docstring's WSANOTINITIALISED section for why this
        # whole class is a sandbox fallback, never used on Windows
        # when `psycopg` is available.
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
        """Sends `sql` plus a trailing `\\echo` marker, WITHOUT waiting
        for the response - used internally by `_run_and_wait()` below.

        `psql`'s stdin interface (unlike psycopg's extended query
        protocol, which needs no terminator - one `execute()` call is
        always exactly one statement) only recognizes a SQL command as
        COMPLETE once it sees a trailing `;` - this project's own
        production SQL strings (see ui/services/mutation_lock.py etc.)
        deliberately omit it, matching psycopg's own convention. This
        shim, and ONLY this shim, appends one if missing so `psql`
        actually executes the statement instead of buffering it
        forever waiting for a terminator that never arrives (this was
        a real bug caught during this file's own first real run - see
        the Row 19C-1 delivery report)."""
        stripped = sql.rstrip()
        terminated = stripped if stripped.endswith(";") else stripped + ";"
        self._marker_n += 1
        marker = f"ROW19C1_DONE_{self._marker_n}"
        self.proc.stdin.write((terminated + f"\n\\echo {marker}\n").encode("utf-8"))
        self.proc.stdin.flush()
        return marker

    def _read_line_with_deadline(self, deadline):
        """Reads ONE newline-terminated line from `self._stdout_fd`,
        using RAW `os.read()` calls into `self._read_buf` (never a
        buffered `TextIOWrapper.readline()`) so that `select.select()`
        below is always polling the exact same place data actually
        gets consumed from - the mismatch that caused this file's own
        real bug on its first run (see `__init__`'s docstring). This
        `select()` call is the EXACT statement that raises
        `OSError(10093, ...)` on Windows (see the module docstring) -
        POSIX-only by construction, which is exactly why this class is
        never used at all once `psycopg` is importable. Returns None
        if no complete line arrives before `deadline`."""
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
        """Non-blocking-with-deadline read: returns (True, lines) if
        the marker arrived within `timeout` seconds, or (False,
        lines-so-far) if it did not - the caller decides what "did not
        arrive in time" means (e.g. proof that a lock call is
        genuinely BLOCKED server-side, not merely slow)."""
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

    def kill_uncleanly(self):
        """Simulates a real crash/network drop - SIGKILL, no `\\q`, no
        clean shutdown - to prove PostgreSQL's OWN auto-release-on-
        disconnect guarantee (never anything this shim or
        mutation_lock.py itself implements)."""
        self.proc.kill()
        self.proc.wait(timeout=10)
        self.closed = True


def db_row_count(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        (value,) = cur.fetchone()
    return value


# ----------------------------------------------------------------
# Result-shape reconciliation: a real psycopg connection returns
# native Python types (bool, int) for boolean/integer columns; the
# text-based psql-subprocess shim returns everything as strings
# ("t"/"f", "1", ...). This is the ONE place both shapes are
# reconciled, rather than scattering backend-specific comparisons
# through the test bodies below.
# ----------------------------------------------------------------

def _pg_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value == "t"
    raise TypeError(f"unexpected PostgreSQL boolean representation: {value!r}")


def _pg_int(value):
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError(f"unexpected PostgreSQL integer representation: {value!r}")


# ----------------------------------------------------------------
# Backend-agnostic connection helpers - EVERY test section below opens
# its connections through `open_conn()`, never through
# `PsqlSessionConnection(...)` directly, so the choice of backend is
# made in exactly ONE place.
# ----------------------------------------------------------------

def open_conn():
    """Opens ONE new database session, autocommit, matching
    ui.services.db.get_session_lock_connection()'s real contract.
    Prefers a REAL psycopg connection whenever psycopg is importable;
    falls back to the psql-subprocess shim only when it is not (see
    the module docstring)."""
    if PSYCOPG_AVAILABLE:
        return psycopg.connect(dbname=PG_DB, autocommit=True)
    return PsqlSessionConnection(PSQL_BIN, PG_DB)


def close_conn(conn):
    conn.close()


class DeferredStatement:
    """Runs ONE SQL statement on `conn` in a background thread,
    WITHOUT blocking the caller, so a test can separately check -
    via a BOUNDED `threading.Event.wait(timeout)`, never `select()`
    on anything and never a fixed `sleep()` guess - whether it has
    completed yet. Used ONLY for the cross-connection blocking proof
    below (session B's attempt at a lock session A already holds),
    which must be issued without waiting for a reply so this test can
    separately, and with a bounded timeout, check whether it is still
    blocked server-side.

    Works identically whether `conn` is a real psycopg connection or
    the `PsqlSessionConnection` sandbox-fallback shim - both expose
    the same `.cursor()` -> `.execute()`/`.fetchone()` shape, and this
    class touches nothing beyond that shape. This is deliberately a
    plain background THREAD, not a `select()`-based multiplexer - the
    exact class of mechanism (`select()` on a non-socket handle) that
    caused the Windows failure this remediation fixes; a thread plus
    `threading.Event` has no such platform restriction on any OS."""

    def __init__(self, conn, sql, params=None):
        self._done = threading.Event()
        self._error = None
        self._row = None

        def _run():
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    self._row = cur.fetchone()
            except Exception as error:  # noqa: BLE001 - captured, re-raised via result()
                self._error = error
            finally:
                self._done.set()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def completed(self, timeout):
        """True iff the statement finished (successfully or not)
        within `timeout` seconds - a real, bounded synchronization
        wait (`threading.Event.wait`), never a fixed `sleep()` guess."""
        return self._done.wait(timeout)

    def result(self):
        """Only meaningful after `completed()` has returned True.
        Re-raises the statement's own exception if it failed, else
        returns its `fetchone()` row."""
        if self._error is not None:
            raise self._error
        return self._row


def _read_line_bounded(stream, timeout):
    """Reads ONE line from `stream` with a BOUNDED wait, using a
    background reader thread plus `queue.Queue.get(timeout=...)` -
    deliberately NEVER `select.select()` on this stream. `stream` here
    is a genuine OS pipe (a subprocess's stdout), and `select()` on a
    non-socket handle is exactly the Windows-only failure mode
    (OSError 10093, WSANOTINITIALISED) this remediation removes - a
    plain blocking `readline()` call in a background thread has no
    such platform restriction, on any OS. Returns None if no line
    arrived within `timeout` seconds (the reader thread is left
    running as a daemon - harmless; it simply finishes whenever the
    subprocess eventually writes to or closes its stdout)."""
    result_queue = queue.Queue(maxsize=1)

    def _reader():
        try:
            result_queue.put(stream.readline())
        except Exception:
            result_queue.put("")

    threading.Thread(target=_reader, daemon=True).start()
    try:
        return result_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def spawn_killable_lock_holder(case_id):
    """Acquires a session-level case lock via the REAL
    `ui.services.mutation_lock.acquire_case_lock_session()`, but
    through a holder that lives in its OWN, separate OS-level process
    - so that process can be killed ABRUPTLY (SIGKILL / TerminateProcess,
    no clean libpq goodbye) without also tearing down THIS test
    process, proving PostgreSQL's own auto-release-on-disconnect
    guarantee. Returns (kill_fn, lock_id).

    - psycopg backend: spawns a genuinely separate `python -c "..."`
      subprocess that imports the REAL `ui.services.mutation_lock` and
      calls the REAL `acquire_case_lock_session()` itself (with its
      OWN real psycopg connection), then blocks waiting to be torn
      down - `kill_fn()` is that subprocess's own `Popen.kill()`. This
      is necessary (rather than, say, forcibly closing a psycopg
      connection's underlying socket from within THIS process) because
      an "unclean disconnect" must be a genuine OS-level process
      teardown, not something orchestrated cooperatively from the same
      process that is supposed to observe its effects.
    - psql-shim backend: each `PsqlSessionConnection` already IS its
      own separate `psql` subprocess by construction (see this
      module's own header comment) - `kill_fn()` is simply that
      connection's own `kill_uncleanly()`.
    """
    if PSYCOPG_AVAILABLE:
        script = (
            "import sys\n"
            f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
            f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
            "import psycopg\n"
            "from ui.services import mutation_lock as ml\n"
            f"conn = psycopg.connect(dbname={PG_DB!r}, autocommit=True)\n"
            f"lock_id = ml.acquire_case_lock_session(conn, {case_id!r})\n"
            "print(f'LOCK_ID={lock_id}', flush=True)\n"
            "sys.stdin.readline()\n"  # blocks here until killed (or fed a line) - never exits on its own
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        )
        line = _read_line_bounded(proc.stdout, timeout=15)
        if line is None or not line.startswith("LOCK_ID="):
            proc.kill()
            raise RuntimeError(
                f"psycopg lock-holder subprocess did not report a lock id in time (got: {line!r})"
            )
        lock_id = int(line.strip().split("=", 1)[1])

        def _kill():
            proc.kill()
            proc.wait(timeout=10)

        return _kill, lock_id

    conn = PsqlSessionConnection(PSQL_BIN, PG_DB)
    lock_id = ml.acquire_case_lock_session(conn, case_id)
    return conn.kill_uncleanly, lock_id


# ----------------------------------------------------------------
# Everything below this point is opted in (VERGI_TEST_PG_DSN set) - a
# broken backend/unreachable database is now an explicit FAIL, never a
# silent skip.
# ----------------------------------------------------------------

from ui.services import mutation_lock as ml            # noqa: E402
from ui.services import mutation_coordinator as mc      # noqa: E402
from ui.services import mutation_registry as mr         # noqa: E402
from mutation_guard import MutationIntent               # noqa: E402

try:
    # ------------------------------------------------------------
    # 1) Cross-connection mutual exclusion, through the REAL
    #    production functions (mutation_lock.acquire_case_lock_session/
    #    release_lock_session), on a case_id unique to this run so
    #    concurrent CI runs (if any) never collide.
    # ------------------------------------------------------------
    probe_case_id = f"__row19c1_pg_probe_{uuid.uuid4().hex[:8]}__"

    conn_a = open_conn()
    conn_b = open_conn()
    try:
        lock_id_a = ml.acquire_case_lock_session(conn_a, probe_case_id)
        check("session A acquires the case lock via the REAL mutation_lock.acquire_case_lock_session()", isinstance(lock_id_a, (str, int)))

        # Session B's attempt at the SAME resource - a raw
        # pg_advisory_lock call on the SAME lock id (bypassing the
        # get-or-create resource lookup, which is not what is being
        # proven here), fired in a background thread (DeferredStatement)
        # so this test can check - with a BOUNDED wait, never select()
        # and never a fixed sleep - whether it is still blocked
        # server-side.
        deferred_b = DeferredStatement(conn_b, "SELECT pg_advisory_lock(%s)", (int(lock_id_a),))
        check(
            "session B's attempt at the SAME advisory lock id genuinely BLOCKS while session A holds it (real cross-connection exclusion)",
            deferred_b.completed(1.5) is False,
        )

        released = ml.release_lock_session(conn_a, lock_id_a)
        check("session A releases the lock via the REAL mutation_lock.release_lock_session()", released is True)

        check(
            "session B's PREVIOUSLY BLOCKED lock attempt completes promptly once session A releases it",
            deferred_b.completed(10) is True,
        )
        deferred_b.result()  # re-raises if session B's own call itself errored

        # Clean up session B's now-held lock so it doesn't linger for
        # the rest of this database's lifetime.
        with conn_b.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (int(lock_id_a),))
            (unlock_result,) = cur.fetchone()
        check("session B's own cleanup unlock succeeds", _pg_bool(unlock_result))
    finally:
        close_conn(conn_a)
        close_conn(conn_b)

    # ------------------------------------------------------------
    # 2) Connection-loss auto-release - a session acquires the lock
    #    then is KILLED UNCLEANLY (a genuine OS-level process kill, no
    #    clean disconnect) - a fresh session C must then be able to
    #    acquire the SAME lock, proving PostgreSQL's own guarantee
    #    (never something this project's own code implements).
    # ------------------------------------------------------------
    kill_a2, lock_id_a2 = spawn_killable_lock_holder(probe_case_id)
    conn_c = open_conn()
    try:
        kill_a2()

        # PostgreSQL needs a brief moment to notice the dropped socket
        # and release the session's locks - poll (a NON-blocking,
        # idempotent, immediately-returning call) up to a bounded
        # deadline, rather than sleeping a single fixed guess.
        acquired = False
        deadline = time.time() + 10
        while time.time() < deadline and not acquired:
            with conn_c.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (int(lock_id_a2),))
                (result,) = cur.fetchone()
            if _pg_bool(result):
                acquired = True
            else:
                time.sleep(0.2)
        check(
            "a fresh session CAN acquire the lock after the holder's connection was killed uncleanly (auto-release proven)",
            acquired,
        )
        if acquired:
            with conn_c.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (int(lock_id_a2),))
    finally:
        close_conn(conn_c)
        # the killable holder is already dead (killed above) - nothing to close.

    # ------------------------------------------------------------
    # 3) End-to-end: run_mutation() against a REAL connection, real
    #    journal table, real constraints - happy path through to
    #    'completed', verified by querying the row back afterward.
    # ------------------------------------------------------------
    conn_d = open_conn()
    try:
        happy_case_id = f"__row19c1_pg_e2e_happy_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_d, happy_case_id)

        intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{happy_case_id}", action_family="fam.row19c1_pg_test",
            target_ref="target_e2e",
        )
        outcome = mc.run_mutation(
            conn_d, intent, actor_user_id=None,
            authz_callback=lambda: None,
            precondition_callback=lambda: None,
            writer_callback=lambda: mc.WriterResult(observed_post_hash="e2e_real_hash", result="e2e_ok"),
        )
        check("run_mutation() against a REAL connection returns state='completed'", outcome.state == "completed")

        with conn_d.cursor() as cur:
            cur.execute(
                "SELECT state, observed_post_hash, resolved_at IS NOT NULL FROM mutation.mutation_journal WHERE id = %s",
                (int(outcome.journal_id),),
            )
            row = cur.fetchone()
        check(
            "the REAL journal row (queried back fresh) reflects state='completed' with the real observed_post_hash and resolved_at set",
            row is not None and row[0] == "completed" and row[1] == "e2e_real_hash" and _pg_bool(row[2]),
            f"got {row!r}",
        )

        # Re-running the identical intent must be a safe replay - the
        # writer must NOT run again (proven by a callback that would
        # raise if invoked a second time).
        def _writer_must_not_run_again():
            raise AssertionError("writer_callback was invoked on what should have been a safe replay")

        replay_outcome = mc.run_mutation(
            conn_d, intent, actor_user_id=None,
            authz_callback=lambda: None, precondition_callback=lambda: None,
            writer_callback=_writer_must_not_run_again,
        )
        check("re-running the IDENTICAL intent against the REAL database is a safe replay (writer not re-invoked)", replay_outcome.replayed is True)
        check("the safe replay returns the ORIGINAL observed_post_hash from the real row", replay_outcome.observed_post_hash == "e2e_real_hash")
    finally:
        ml.release_lock_session(conn_d, ml._get_or_create_resource_advisory_lock_id(conn_d, ml.case_resource_key(happy_case_id)))
        close_conn(conn_d)

    # ------------------------------------------------------------
    # 4) End-to-end: a writer failure that must become
    #    'reconciliation_required' against the REAL database, then
    #    genuinely reconciled via mutation_registry.reconcile_journal_entry()
    #    with a fake adapter, with the outcome durably applied using
    #    the SAME journal-write path the coordinator itself uses.
    # ------------------------------------------------------------
    conn_e = open_conn()
    try:
        recon_case_id = f"__row19c1_pg_e2e_recon_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_e, recon_case_id)

        recon_intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{recon_case_id}", action_family="fam.row19c1_pg_recon_test",
            target_ref="target_recon",
        )

        def _writer_crashes_ambiguously():
            raise OSError("simulated disk write timeout - unknown whether the file changed")

        expect_raises(
            OSError,
            lambda: mc.run_mutation(
                conn_e, recon_intent, actor_user_id=None,
                authz_callback=lambda: None, precondition_callback=lambda: None,
                writer_callback=_writer_crashes_ambiguously,
            ),
            "an ordinary writer exception against the REAL database propagates",
        )

        with conn_e.cursor() as cur:
            cur.execute(
                "SELECT id, state FROM mutation.mutation_journal WHERE resource_key = %s AND action_family = %s",
                (f"case:{recon_case_id}", "fam.row19c1_pg_recon_test"),
            )
            recon_row = cur.fetchone()
        check(
            "the REAL journal row for the crashed writer is 'reconciliation_required' (queried back fresh, never 'failed')",
            recon_row is not None and recon_row[1] == "reconciliation_required",
            f"got {recon_row!r}",
        )
        recon_journal_id = int(recon_row[0])

        class RealDbFakeAdapter:
            """A FAKE adapter (per Row 19C-1's own scope: no real
            production adapter is connected this turn) - but exercised
            here against the REAL mutation_registry.reconcile_journal_entry(),
            the REAL mutation_lock session-lock primitives, and a REAL
            journal row, which is exactly what this file exists to
            prove."""

            def gather_evidence(self, entry):
                return mr.ReconciliationEvidence(
                    post_state_verified=True, pre_state_confirmed_unchanged=False,
                    observed_post_hash="reconciled_real_hash",
                )

        # ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION: there is no
        # longer a separate decide-then-apply pair of public calls -
        # reconcile_and_apply_journal_entry() re-reads the row
        # AUTHORITATIVELY by journal_id itself (never trusting a
        # caller-supplied snapshot), decides, and durably applies the
        # outcome, all under the SAME held lock, in ONE call.
        registry = mr.MutationAdapterRegistry().with_adapter("fam.row19c1_pg_recon_test", RealDbFakeAdapter())
        recon_outcome = mr.reconcile_and_apply_journal_entry(conn_e, recon_journal_id, registry)
        check("reconcile_and_apply_journal_entry() against the REAL database returns new_state='completed'", recon_outcome.new_state == "completed")

        with conn_e.cursor() as cur:
            cur.execute(
                "SELECT state, observed_post_hash, resolution_code, resolved_at IS NOT NULL "
                "FROM mutation.mutation_journal WHERE id = %s",
                (recon_journal_id,),
            )
            final_row = cur.fetchone()
        check(
            "the reconciled row, queried back fresh, is durably 'completed' with the reconciled observed_post_hash, resolution_code and resolved_at all set",
            final_row is not None
            and final_row[0] == "completed"
            and final_row[1] == "reconciled_real_hash"
            and final_row[2] == "reconciled_completed_post_state_verified"
            and _pg_bool(final_row[3]),
            f"got {final_row!r}",
        )
    finally:
        ml.release_lock_session(conn_e, ml._get_or_create_resource_advisory_lock_id(conn_e, ml.case_resource_key(recon_case_id)))
        close_conn(conn_e)

    # ------------------------------------------------------------
    # 5) Row 19C-1 TARGETED CONTRACT REMEDIATION: a TERMINAL `failed`
    #    row already on record (queried back through the REAL,
    #    unconditional, all-state `_idempotency_lookup` SQL - never
    #    exercised by sections 3/4 above, which only ever see
    #    `completed`/`reconciliation_required` rows) must produce
    #    `PriorAttemptFailedError` deterministically, insert NO new
    #    row, and never invoke authz/precondition/writer - proven here
    #    against the real database, not just the fake-conn harness in
    #    ui/tests/test_mutation_coordinator_isolated.py.
    # ------------------------------------------------------------
    conn_f = open_conn()
    try:
        failed_case_id = f"__row19c1_pg_e2e_failed_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_f, failed_case_id)

        failed_intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{failed_case_id}", action_family="fam.row19c1_pg_failed_test",
            target_ref="target_failed",
        )
        # mutation_coordinator.py itself never writes a `failed` row
        # any more (see its own dispatch contract) - a `failed` row can
        # only ever originate from prior, out-of-band reconciliation, so
        # this test seeds one directly, exactly the shape reconciliation
        # would leave behind.
        from mutation_guard import compute_idempotency_key as _ck, compute_request_fingerprint as _cf  # noqa: E402
        real_key_f = _ck(failed_intent)
        real_fp_f = _cf(failed_intent)
        with conn_f.cursor() as cur:
            cur.execute(
                "INSERT INTO mutation.mutation_journal ("
                "  resource_key, action_family, actor_label, target_ref,"
                "  idempotency_key, request_fingerprint, state, failure_code, executing_at, resolved_at"
                ") VALUES (%s, %s, %s, %s, %s, %s, 'failed', %s, now(), now()) RETURNING id",
                (
                    f"case:{failed_case_id}", "fam.row19c1_pg_failed_test", "row19c1_pg_test_actor",
                    "target_failed", real_key_f, real_fp_f, "precondition_failed",
                ),
            )
            (seeded_failed_id,) = cur.fetchone()

        def _writer_must_never_run():
            raise AssertionError("writer_callback was invoked despite a prior TERMINAL failed row for this exact idempotency_key")

        def _authz_must_never_run():
            raise AssertionError("authz_callback was invoked despite a prior TERMINAL failed row for this exact idempotency_key")

        def _precondition_must_never_run():
            raise AssertionError("precondition_callback was invoked despite a prior TERMINAL failed row for this exact idempotency_key")

        expect_raises(
            mc.PriorAttemptFailedError,
            lambda: mc.run_mutation(
                conn_f, failed_intent, actor_user_id=None,
                authz_callback=_authz_must_never_run,
                precondition_callback=_precondition_must_never_run,
                writer_callback=_writer_must_never_run,
            ),
            "a prior TERMINAL failed row (real database) deterministically re-reports as PriorAttemptFailedError",
        )

        with conn_f.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM mutation.mutation_journal WHERE idempotency_key = %s",
                (real_key_f,),
            )
            (count_for_key,) = cur.fetchone()
        check("the failed row's idempotency_key STILL has exactly one row after the refused retry (real database)", _pg_int(count_for_key) == 1)

        with conn_f.cursor() as cur:
            cur.execute(
                "SELECT state, failure_code FROM mutation.mutation_journal WHERE id = %s",
                (seeded_failed_id,),
            )
            unchanged_row = cur.fetchone()
        check(
            "the pre-existing failed row is completely untouched (real database)",
            unchanged_row == ("failed", "precondition_failed"),
            f"got {unchanged_row!r}",
        )
    finally:
        ml.release_lock_session(conn_f, ml._get_or_create_resource_advisory_lock_id(conn_f, ml.case_resource_key(failed_case_id)))
        close_conn(conn_f)

    # ------------------------------------------------------------
    # 6) ROW 19C-1 RECONCILIATION ATOMICITY REMEDIATION - the decision
    #    is driven ONLY by the AUTHORITATIVE, lock-held reread, never
    #    by anything believed beforehand. Proven against the REAL
    #    database: seed a row via a real writer crash (leaving
    #    'reconciliation_required'), then resolve it out-of-band to
    #    'completed' BEFORE ever calling reconcile_and_apply_journal_entry()
    #    - standing in for "this row was already resolved by the time
    #    anyone got around to reconciling it, so whatever anyone might
    #    have believed about it is now stale" - and confirm the call
    #    fails closed on the CURRENT, real, authoritative state, never
    #    on the outdated one.
    # ------------------------------------------------------------
    conn_g = open_conn()
    try:
        stale_case_id = f"__row19c1_pg_stale_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_g, stale_case_id)

        stale_intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{stale_case_id}", action_family="fam.row19c1_pg_stale_test",
            target_ref="target_stale",
        )

        def _writer_crashes_for_stale_test():
            raise OSError("simulated crash for the authoritative-reread test")

        expect_raises(
            OSError,
            lambda: mc.run_mutation(
                conn_g, stale_intent, actor_user_id=None,
                authz_callback=lambda: None, precondition_callback=lambda: None,
                writer_callback=_writer_crashes_for_stale_test,
            ),
            "seeding: an ordinary writer exception leaves a REAL 'reconciliation_required' row to reconcile",
        )

        with conn_g.cursor() as cur:
            cur.execute(
                "SELECT id FROM mutation.mutation_journal WHERE resource_key = %s AND action_family = %s",
                (f"case:{stale_case_id}", "fam.row19c1_pg_stale_test"),
            )
            (stale_journal_id,) = cur.fetchone()
        stale_journal_id = int(stale_journal_id)

        # Directly resolve the row to 'completed' OUT-OF-BAND, via raw
        # SQL - standing in for "another process already resolved this
        # by the time we get around to reconciling it".
        with conn_g.cursor() as cur:
            cur.execute(
                "UPDATE mutation.mutation_journal SET state = 'completed', resolution_code = %s, "
                "resolved_at = now() WHERE id = %s",
                ("reconciled_completed_post_state_verified", stale_journal_id),
            )

        class MustNeverRunAdapter:
            def gather_evidence(self, entry):
                raise AssertionError("adapter was invoked for an already-TERMINAL authoritative row")

        stale_registry = mr.MutationAdapterRegistry().with_adapter("fam.row19c1_pg_stale_test", MustNeverRunAdapter())
        expect_raises(
            mr.UnsupportedJournalStateError,
            lambda: mr.reconcile_and_apply_journal_entry(conn_g, stale_journal_id, stale_registry),
            "reconcile_and_apply_journal_entry() fails closed on the CURRENT (authoritative) 'completed' state, "
            "never on the 'reconciliation_required' state the row was in when this test first observed it",
        )
    finally:
        ml.release_lock_session(conn_g, ml._get_or_create_resource_advisory_lock_id(conn_g, ml.case_resource_key(stale_case_id)))
        close_conn(conn_g)

    # ------------------------------------------------------------
    # 7) A second reconciliation attempt that starts while the FIRST
    #    holds the resource's session lock must genuinely BLOCK (real
    #    PostgreSQL pg_advisory_lock exclusion), and once the first has
    #    resolved the row and released the lock, the second must see
    #    the row's now-TERMINAL AUTHORITATIVE state and fail closed
    #    WITHOUT ever invoking its own adapter and WITHOUT writing a
    #    second time - proven with two REAL, separate connections and
    #    a background thread, using ONLY bounded waits
    #    (thread.join(timeout=...), a bounded pg_stat_activity poll to
    #    a real deadline) - never a fragile fixed sleep standing in for
    #    synchronization, and never reduced to a single connection.
    # ------------------------------------------------------------
    conn_race_x = open_conn()
    conn_race_y = open_conn()
    try:
        race_case_id = f"__row19c1_pg_race_{uuid.uuid4().hex[:8]}__"

        race_intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{race_case_id}", action_family="fam.row19c1_pg_race_test",
            target_ref="target_race",
        )

        def _writer_crashes_for_race():
            raise OSError("simulated crash for the two-connection race test")

        ml.acquire_case_lock_session(conn_race_x, race_case_id)
        try:
            expect_raises(
                OSError,
                lambda: mc.run_mutation(
                    conn_race_x, race_intent, actor_user_id=None,
                    authz_callback=lambda: None, precondition_callback=lambda: None,
                    writer_callback=_writer_crashes_for_race,
                ),
                "seeding: leaves a REAL 'reconciliation_required' row for the race test",
            )
        finally:
            ml.release_lock_session(conn_race_x, ml._get_or_create_resource_advisory_lock_id(conn_race_x, ml.case_resource_key(race_case_id)))

        with conn_race_x.cursor() as cur:
            cur.execute(
                "SELECT id FROM mutation.mutation_journal WHERE resource_key = %s AND action_family = %s",
                (f"case:{race_case_id}", "fam.row19c1_pg_race_test"),
            )
            (race_journal_id,) = cur.fetchone()
        race_journal_id = int(race_journal_id)

        adapter_y_call_count = {"n": 0}

        class SpyAdapterY:
            def gather_evidence(self, entry):
                adapter_y_call_count["n"] += 1
                return mr.ReconciliationEvidence(
                    post_state_verified=True, pre_state_confirmed_unchanged=False, observed_post_hash="race_y_hash",
                )

        registry_y = mr.MutationAdapterRegistry().with_adapter("fam.row19c1_pg_race_test", SpyAdapterY())

        # conn_race_x takes the resource lock FIRST, directly (not via
        # reconcile_and_apply_journal_entry), so this test controls
        # exactly when it releases.
        lock_id_x = ml.acquire_case_lock_session(conn_race_x, race_case_id)

        # conn_race_y's own backend pid, captured BEFORE it attempts
        # the lock, so this test can bounded-poll pg_stat_activity for
        # THAT specific pid genuinely blocking on a lock.
        with conn_race_y.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            (race_y_pid,) = cur.fetchone()
        race_y_pid = int(race_y_pid)

        result_holder = {}

        def _run_conn_y():
            try:
                result_holder["outcome"] = mr.reconcile_and_apply_journal_entry(conn_race_y, race_journal_id, registry_y)
            except Exception as error:
                result_holder["error"] = error

        thread_y = threading.Thread(target=_run_conn_y, daemon=True)
        thread_y.start()

        # Bounded poll (real deadline, never a fixed sleep standing in
        # for synchronization) confirming session Y is GENUINELY
        # blocked waiting on a lock before session X proceeds -
        # otherwise this test's OWN timing, not real PostgreSQL
        # exclusion, could accidentally decide who "wins".
        deadline = time.time() + 10
        y_is_blocked = False
        while time.time() < deadline:
            with conn_race_x.cursor() as cur:
                cur.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (race_y_pid,))
                row = cur.fetchone()
            if row is not None and row[0] == "Lock":
                y_is_blocked = True
                break
            time.sleep(0.05)
        check("session Y's reconciliation attempt is GENUINELY blocked (real PostgreSQL lock wait, observed via pg_stat_activity)", y_is_blocked)

        # While Y is blocked, X (the lock holder) performs its OWN
        # reconciliation through the SAME real public entry point Y
        # itself uses, from the connection that already holds the
        # lock - pg_advisory_lock is per-SESSION and re-entrant for a
        # session that already holds it, so this does not self-block.
        class AdapterX:
            def gather_evidence(self, entry):
                return mr.ReconciliationEvidence(
                    post_state_verified=True, pre_state_confirmed_unchanged=False, observed_post_hash="race_x_hash",
                )

        registry_x = mr.MutationAdapterRegistry().with_adapter("fam.row19c1_pg_race_test", AdapterX())
        outcome_x = mr.reconcile_and_apply_journal_entry(conn_race_x, race_journal_id, registry_x)
        check("session X (the lock holder) resolves the row to 'completed' first, while STILL holding the outer lock", outcome_x.new_state == "completed")

        ml.release_lock_session(conn_race_x, lock_id_x)

        thread_y.join(timeout=15)
        check("session Y's blocked call completed within a bounded timeout after X released the lock", not thread_y.is_alive())
        check(
            "session Y's authoritative reread saw the row ALREADY 'completed' and failed closed with UnsupportedJournalStateError",
            isinstance(result_holder.get("error"), mr.UnsupportedJournalStateError),
            f"got {result_holder!r}",
        )
        check("session Y's own adapter was NEVER invoked (fails closed before ever reaching it)", adapter_y_call_count["n"] == 0)

        with conn_race_x.cursor() as cur:
            cur.execute("SELECT state, observed_post_hash FROM mutation.mutation_journal WHERE id = %s", (race_journal_id,))
            final_race_row = cur.fetchone()
        check(
            "the row's final state/hash is EXACTLY what session X wrote - session Y never got a second write in",
            final_race_row == ("completed", "race_x_hash"),
            f"got {final_race_row!r}",
        )
    finally:
        close_conn(conn_race_x)
        close_conn(conn_race_y)

    # ------------------------------------------------------------
    # 8) ReconciliationApplyFailedError - the guarded UPDATE's rowcount
    #    check, proven for REAL against the real database: an adapter
    #    that (test-only - a real adapter must NEVER do this) reaches
    #    out through a SEPARATE, real connection and resolves the row
    #    out-of-band DURING its own gather_evidence() call, standing in
    #    for "something outside this module's own locking discipline
    #    changed the row between the authoritative reread and the
    #    apply step" (PostgreSQL's advisory locks are cooperative, not
    #    mandatory - they do not themselves prevent a raw UPDATE from
    #    an unrelated session that never even attempts the lock). The
    #    guarded UPDATE must then affect zero real rows, and this must
    #    be a VISIBLE, counted failure - never a silent no-op.
    # ------------------------------------------------------------
    conn_h = open_conn()
    try:
        rowcount_case_id = f"__row19c1_pg_rowcount_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_h, rowcount_case_id)

        rowcount_intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{rowcount_case_id}", action_family="fam.row19c1_pg_rowcount_test",
            target_ref="target_rowcount",
        )

        def _writer_crashes_for_rowcount():
            raise OSError("simulated crash for the rowcount test")

        expect_raises(
            OSError,
            lambda: mc.run_mutation(
                conn_h, rowcount_intent, actor_user_id=None,
                authz_callback=lambda: None, precondition_callback=lambda: None,
                writer_callback=_writer_crashes_for_rowcount,
            ),
            "seeding: leaves a REAL 'reconciliation_required' row for the rowcount test",
        )

        with conn_h.cursor() as cur:
            cur.execute(
                "SELECT id FROM mutation.mutation_journal WHERE resource_key = %s AND action_family = %s",
                (f"case:{rowcount_case_id}", "fam.row19c1_pg_rowcount_test"),
            )
            (rowcount_journal_id,) = cur.fetchone()
        rowcount_journal_id = int(rowcount_journal_id)

        class OutOfBandBypassAdapter:
            """Deliberately violates the locking discipline it is given
            no license to violate - TEST-ONLY, to prove the guarded
            UPDATE's rowcount check for real. A real reconciliation
            adapter (Row 19C-2+ scope) must NEVER do this - it must
            only ever READ domain evidence, never mutate
            mutation.mutation_journal itself."""

            def gather_evidence(self, entry):
                bypass_conn = open_conn()
                try:
                    with bypass_conn.cursor() as cur:
                        cur.execute(
                            "UPDATE mutation.mutation_journal SET state = 'completed', "
                            "resolution_code = %s, resolved_at = now() WHERE id = %s",
                            ("reconciled_completed_post_state_verified", rowcount_journal_id),
                        )
                finally:
                    close_conn(bypass_conn)
                return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)

        rowcount_registry = mr.MutationAdapterRegistry().with_adapter("fam.row19c1_pg_rowcount_test", OutOfBandBypassAdapter())
        expect_raises(
            mr.ReconciliationApplyFailedError,
            lambda: mr.reconcile_and_apply_journal_entry(conn_h, rowcount_journal_id, rowcount_registry),
            "a guarded UPDATE affecting zero real rows (resolved out-of-band mid-flight) is a VISIBLE, counted real-database failure",
        )

        with conn_h.cursor() as cur:
            cur.execute("SELECT state, resolution_code FROM mutation.mutation_journal WHERE id = %s", (rowcount_journal_id,))
            final_rowcount_row = cur.fetchone()
        check(
            "the row is left exactly as the out-of-band bypass wrote it - this call's own (never-applied) decision never landed on top",
            final_rowcount_row == ("completed", "reconciled_completed_post_state_verified"),
            f"got {final_rowcount_row!r}",
        )
    finally:
        ml.release_lock_session(conn_h, ml._get_or_create_resource_advisory_lock_id(conn_h, ml.case_resource_key(rowcount_case_id)))
        close_conn(conn_h)

    # ------------------------------------------------------------
    # 9) The 'prepared' permanent-gate fix, proven against the REAL
    #    database: a 'prepared' row is inserted DIRECTLY (exactly the
    #    shape run_mutation()'s own _insert_prepared() would have left
    #    behind, modeling a crash between that commit and the
    #    'executing' transition - run_mutation() is never called for
    #    this row at all). First prove the resource IS gated (the
    #    bug's own visible symptom, still true - reconciliation is the
    #    fix, not a change to the gate itself), then prove
    #    reconciliation genuinely resolves it - an escape path that
    #    did not exist before this remediation - and that the resource
    #    is truly unblocked afterwards.
    # ------------------------------------------------------------
    conn_i = open_conn()
    try:
        prepared_case_id = f"__row19c1_pg_prepared_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_i, prepared_case_id)

        prepared_intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{prepared_case_id}", action_family="fam.row19c1_pg_prepared_test",
            target_ref="target_prepared",
        )
        from mutation_guard import compute_idempotency_key as _ck2, compute_request_fingerprint as _cf2  # noqa: E402
        prepared_key = _ck2(prepared_intent)
        prepared_fp = _cf2(prepared_intent)

        with conn_i.cursor() as cur:
            cur.execute(
                "INSERT INTO mutation.mutation_journal ("
                "  resource_key, action_family, actor_label, target_ref,"
                "  idempotency_key, request_fingerprint, state"
                ") VALUES (%s, %s, %s, %s, %s, %s, 'prepared') RETURNING id",
                (
                    f"case:{prepared_case_id}", "fam.row19c1_pg_prepared_test", "row19c1_pg_test_actor",
                    "target_prepared", prepared_key, prepared_fp,
                ),
            )
            (prepared_journal_id,) = cur.fetchone()
        prepared_journal_id = int(prepared_journal_id)

        # Before this remediation, this resource would now be
        # PERMANENTLY blocked with NO code path able to ever move a
        # 'prepared' row anywhere else. First prove the gate itself
        # (the bug's own symptom, unchanged by this fix):
        expect_raises(
            mc.ResourceGatedError,
            lambda: mc.run_mutation(
                conn_i, prepared_intent, actor_user_id=None,
                authz_callback=lambda: None, precondition_callback=lambda: None,
                writer_callback=lambda: mc.WriterResult(observed_post_hash="should_never_run", result=None),
            ),
            "the resource IS gated by the stuck 'prepared' row (the bug's own symptom - reconciliation is the fix, not a gate change)",
        )

        # ... then prove reconciliation genuinely provides the escape
        # this remediation adds: an adapter proving the pre-state was
        # NEVER touched resolves this 'prepared' row to 'failed', for
        # real, against the real database.
        class PreStateNeverTouchedAdapter:
            def gather_evidence(self, entry):
                return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)

        prepared_registry = mr.MutationAdapterRegistry().with_adapter("fam.row19c1_pg_prepared_test", PreStateNeverTouchedAdapter())
        prepared_outcome = mr.reconcile_and_apply_journal_entry(conn_i, prepared_journal_id, prepared_registry)
        check(
            "a stuck 'prepared' row (writer never invoked) resolves to 'failed' with the PREPARED-specific resolution_code, against the REAL database",
            prepared_outcome.new_state == "failed" and prepared_outcome.resolution_code == "reconciled_failed_prepared_never_executed",
        )

        with conn_i.cursor() as cur:
            cur.execute(
                "SELECT state, resolution_code, executing_at IS NOT NULL, resolved_at IS NOT NULL "
                "FROM mutation.mutation_journal WHERE id = %s",
                (prepared_journal_id,),
            )
            final_prepared_row = cur.fetchone()
        # ROW 19C-1 TIMESTAMP SEMANTICS CORRECTION: the writer was NEVER
        # invoked for this row (it went straight from a raw 'prepared'
        # INSERT to reconciliation - run_mutation()/_mark_executing()
        # never ran) - so executing_at must STAY NULL, never be
        # backfilled. Fabricating one here would be a factual falsehood
        # in this legal/security journal. resolved_at IS set (this
        # outcome IS terminal/final), and 0003's own real CHECK
        # constraints (mutation_journal_executing_at_matches_state /
        # mutation_journal_prepared_never_executed_code_is_exclusive)
        # would reject this exact row shape if executing_at were
        # non-NULL - see test_iam_migrations_isolated.py's dedicated
        # negative-constraint proofs for that.
        check(
            "the REAL row is durably 'failed' with the prepared-never-executed resolution_code, executing_at STAYS NULL "
            "(writer never invoked - no fabricated execution timestamp), resolved_at IS set",
            final_prepared_row is not None
            and final_prepared_row[0] == "failed"
            and final_prepared_row[1] == "reconciled_failed_prepared_never_executed"
            and not _pg_bool(final_prepared_row[2])
            and _pg_bool(final_prepared_row[3]),
            f"got {final_prepared_row!r}",
        )

        # The resource is NOW genuinely unblocked: a fresh attempt (a
        # NEW idempotency_key - an intent whose identity fields were
        # unchanged would hash to the SAME, now-permanently-failed key;
        # see PriorAttemptFailedError) proceeds normally.
        new_attempt_intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{prepared_case_id}", action_family="fam.row19c1_pg_prepared_test",
            target_ref="target_prepared", pre_hash="freshly_reread_hash", pre_revision="rev2",
        )
        new_attempt_outcome = mc.run_mutation(
            conn_i, new_attempt_intent, actor_user_id=None,
            authz_callback=lambda: None, precondition_callback=lambda: None,
            writer_callback=lambda: mc.WriterResult(observed_post_hash="new_attempt_hash", result="new_ok"),
        )
        check(
            "once reconciled, the resource is genuinely UNBLOCKED - a fresh attempt (new idempotency_key) completes normally",
            new_attempt_outcome.state == "completed",
        )
    finally:
        ml.release_lock_session(conn_i, ml._get_or_create_resource_advisory_lock_id(conn_i, ml.case_resource_key(prepared_case_id)))
        close_conn(conn_i)

    # ------------------------------------------------------------
    # 10) ROW 19C-1 TIMESTAMP SEMANTICS CORRECTION - the COUNTERPART
    #     proof to section 9: a row that DID cross the writer boundary
    #     (origin 'reconciliation_required', which only ever exists
    #     because _mark_executing() already set a REAL executing_at
    #     before the writer ran) must KEEP that real, non-NULL
    #     executing_at when reconciled to 'failed' via the GENERAL
    #     branch (RESOLUTION_CODE_FAILED_PRE_STATE_UNCHANGED, never the
    #     prepared-never-executed code) - proving this correction did
    #     NOT collaterally strip/null executing_at from a row that
    #     genuinely was executed, against the REAL database.
    # ------------------------------------------------------------
    conn_j = open_conn()
    try:
        executed_failed_case_id = f"__row19c1_pg_executed_failed_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_j, executed_failed_case_id)

        executed_failed_intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{executed_failed_case_id}", action_family="fam.row19c1_pg_executed_failed_test",
            target_ref="target_executed_failed",
        )

        def _writer_crashes_for_executed_failed():
            raise OSError("simulated crash - writer WAS invoked (executing_at already set) before this failure")

        expect_raises(
            OSError,
            lambda: mc.run_mutation(
                conn_j, executed_failed_intent, actor_user_id=None,
                authz_callback=lambda: None, precondition_callback=lambda: None,
                writer_callback=_writer_crashes_for_executed_failed,
            ),
            "seeding: an ordinary writer exception leaves a REAL 'reconciliation_required' row, "
            "with executing_at ALREADY set by _mark_executing() before the writer ever ran",
        )

        with conn_j.cursor() as cur:
            cur.execute(
                "SELECT id, executing_at IS NOT NULL FROM mutation.mutation_journal "
                "WHERE resource_key = %s AND action_family = %s",
                (f"case:{executed_failed_case_id}", "fam.row19c1_pg_executed_failed_test"),
            )
            executed_failed_row = cur.fetchone()
        check(
            "the seeded 'reconciliation_required' row already has a REAL (non-NULL) executing_at before reconciliation runs",
            executed_failed_row is not None and _pg_bool(executed_failed_row[1]),
            f"got {executed_failed_row!r}",
        )
        executed_failed_journal_id = int(executed_failed_row[0])

        class PreStateUnchangedAdapter:
            def gather_evidence(self, entry):
                return mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=True)

        executed_failed_registry = mr.MutationAdapterRegistry().with_adapter(
            "fam.row19c1_pg_executed_failed_test", PreStateUnchangedAdapter(),
        )
        executed_failed_outcome = mr.reconcile_and_apply_journal_entry(
            conn_j, executed_failed_journal_id, executed_failed_registry,
        )
        check(
            "an 'reconciliation_required'-origin row (writer DID run) reconciles to 'failed' via the GENERAL "
            "resolution_code (never the prepared-never-executed one), against the REAL database",
            executed_failed_outcome.new_state == "failed"
            and executed_failed_outcome.resolution_code == "reconciled_failed_pre_state_confirmed_unchanged",
        )

        with conn_j.cursor() as cur:
            cur.execute(
                "SELECT state, resolution_code, executing_at IS NOT NULL, resolved_at IS NOT NULL "
                "FROM mutation.mutation_journal WHERE id = %s",
                (executed_failed_journal_id,),
            )
            final_executed_failed_row = cur.fetchone()
        check(
            "the REAL row is durably 'failed' with the GENERAL resolution_code, and executing_at REMAINS non-NULL "
            "(this row genuinely crossed the writer boundary - the correction never touches this branch's executing_at)",
            final_executed_failed_row is not None
            and final_executed_failed_row[0] == "failed"
            and final_executed_failed_row[1] == "reconciled_failed_pre_state_confirmed_unchanged"
            and _pg_bool(final_executed_failed_row[2])
            and _pg_bool(final_executed_failed_row[3]),
            f"got {final_executed_failed_row!r}",
        )
    finally:
        ml.release_lock_session(conn_j, ml._get_or_create_resource_advisory_lock_id(conn_j, ml.case_resource_key(executed_failed_case_id)))
        close_conn(conn_j)

    # ------------------------------------------------------------
    # 11) ROW 19C-1 FINAL PREPARED-INCONCLUSIVE SEMANTICS CORRECTION -
    #     proven against the REAL database: for a 'prepared'-origin
    #     row, every evidence combination OTHER than the one
    #     legitimate 'failed' resolution must raise
    #     PreparedJournalUnresolvedError, leave the row COMPLETELY
    #     untouched (still 'prepared', executing_at/resolved_at/
    #     resolution_code all NULL - no UPDATE ever issued), keep the
    #     resource genuinely gated (a fresh mutation attempt still
    #     raises ResourceGatedError), and release the lock normally -
    #     proven for all three required evidence shapes, then confirm
    #     the SAME row can still later be resolved via the legitimate
    #     path once stronger evidence becomes available.
    # ------------------------------------------------------------
    conn_k = open_conn()
    try:
        unresolved_case_id = f"__row19c1_pg_prepared_unresolved_{uuid.uuid4().hex[:8]}__"
        ml.acquire_case_lock_session(conn_k, unresolved_case_id)

        unresolved_intent = MutationIntent(
            actor_type="cli_service", actor_ref="row19c1_pg_test_actor",
            resource_key=f"case:{unresolved_case_id}", action_family="fam.row19c1_pg_prepared_unresolved_test",
            target_ref="target_prepared_unresolved",
        )
        from mutation_guard import compute_idempotency_key as _ck3, compute_request_fingerprint as _cf3  # noqa: E402
        unresolved_key = _ck3(unresolved_intent)
        unresolved_fp = _cf3(unresolved_intent)

        with conn_k.cursor() as cur:
            cur.execute(
                "INSERT INTO mutation.mutation_journal ("
                "  resource_key, action_family, actor_label, target_ref,"
                "  idempotency_key, request_fingerprint, state"
                ") VALUES (%s, %s, %s, %s, %s, %s, 'prepared') RETURNING id",
                (
                    f"case:{unresolved_case_id}", "fam.row19c1_pg_prepared_unresolved_test", "row19c1_pg_test_actor",
                    "target_prepared_unresolved", unresolved_key, unresolved_fp,
                ),
            )
            (unresolved_journal_id,) = cur.fetchone()
        unresolved_journal_id = int(unresolved_journal_id)

        def _unresolved_row_snapshot():
            with conn_k.cursor() as cur:
                cur.execute(
                    "SELECT state, executing_at IS NULL, resolved_at IS NULL, resolution_code IS NULL "
                    "FROM mutation.mutation_journal WHERE id = %s",
                    (unresolved_journal_id,),
                )
                return cur.fetchone()

        baseline_snapshot = _unresolved_row_snapshot()
        check(
            "seeded 'prepared' row starts with executing_at/resolved_at/resolution_code all NULL",
            baseline_snapshot is not None and baseline_snapshot[0] == "prepared"
            and _pg_bool(baseline_snapshot[1]) and _pg_bool(baseline_snapshot[2]) and _pg_bool(baseline_snapshot[3]),
            f"got {baseline_snapshot!r}",
        )

        class EvidenceAdapter:
            def __init__(self, post_state_verified, pre_state_confirmed_unchanged):
                self._post = post_state_verified
                self._pre = pre_state_confirmed_unchanged

            def gather_evidence(self, entry):
                return mr.ReconciliationEvidence(
                    post_state_verified=self._post, pre_state_confirmed_unchanged=self._pre,
                )

        for label, post_v, pre_v in (
            ("insufficient evidence (both proofs False)", False, False),
            ("contradictory evidence (both proofs True)", True, True),
            ("post_state_verified=True only (writer never invoked)", True, False),
        ):
            registry_case = mr.MutationAdapterRegistry().with_adapter(
                "fam.row19c1_pg_prepared_unresolved_test", EvidenceAdapter(post_v, pre_v),
            )
            expect_raises(
                mr.PreparedJournalUnresolvedError,
                lambda registry_case=registry_case: mr.reconcile_and_apply_journal_entry(
                    conn_k, unresolved_journal_id, registry_case,
                ),
                f"prepared + {label} raises PreparedJournalUnresolvedError against the REAL database",
            )
            after_snapshot = _unresolved_row_snapshot()
            check(
                f"prepared + {label}: the REAL row is COMPLETELY untouched (still 'prepared', "
                "executing_at/resolved_at/resolution_code still all NULL - no UPDATE ever issued)",
                after_snapshot == baseline_snapshot,
                f"got {after_snapshot!r}",
            )

            # The resource remains genuinely gated - a fresh mutation
            # attempt on the SAME resource is still refused.
            expect_raises(
                mc.ResourceGatedError,
                lambda: mc.run_mutation(
                    conn_k, unresolved_intent, actor_user_id=None,
                    authz_callback=lambda: None, precondition_callback=lambda: None,
                    writer_callback=lambda: mc.WriterResult(observed_post_hash="should_never_run", result=None),
                ),
                f"prepared + {label}: the resource is STILL gated by the (still-unresolved) 'prepared' row",
            )

        # Finally: the SAME row can still be resolved via the
        # legitimate path once stronger evidence proves the pre-state
        # was unchanged - this correction only refuses to GUESS, it
        # never permanently blocks a genuine future resolution.
        final_registry = mr.MutationAdapterRegistry().with_adapter(
            "fam.row19c1_pg_prepared_unresolved_test", EvidenceAdapter(False, True),
        )
        final_outcome = mr.reconcile_and_apply_journal_entry(conn_k, unresolved_journal_id, final_registry)
        check(
            "the SAME 'prepared' row, later given conclusive evidence, still resolves to 'failed' "
            "via the legitimate never-executed path, against the REAL database",
            final_outcome.new_state == "failed"
            and final_outcome.resolution_code == "reconciled_failed_prepared_never_executed",
        )
        with conn_k.cursor() as cur:
            cur.execute(
                "SELECT state, executing_at IS NULL, resolved_at IS NOT NULL FROM mutation.mutation_journal WHERE id = %s",
                (unresolved_journal_id,),
            )
            resolved_snapshot = cur.fetchone()
        check(
            "the finally-resolved REAL row is durably 'failed' with executing_at STILL NULL and resolved_at now set",
            resolved_snapshot is not None
            and resolved_snapshot[0] == "failed" and _pg_bool(resolved_snapshot[1]) and _pg_bool(resolved_snapshot[2]),
            f"got {resolved_snapshot!r}",
        )
    finally:
        ml.release_lock_session(conn_k, ml._get_or_create_resource_advisory_lock_id(conn_k, ml.case_resource_key(unresolved_case_id)))
        close_conn(conn_k)

except Exception as error:
    check(
        "the full real-PostgreSQL suite completed without an unexpected exception",
        False,
        repr(error),
    )

print(f"--- test_mutation_journal_postgres: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
