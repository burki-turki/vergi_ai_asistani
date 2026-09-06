# ============================================================
# Row 19B - PostgreSQL connection helper.
#
# psycopg 3 (psycopg[binary,pool]) is the chosen driver - both sync
# and async APIs, prebuilt wheels on the target platforms, chosen
# over asyncpg (asyncio-only) per the approved dependency contract.
#
# psycopg is imported LAZILY, inside functions, never at module
# top-level. This means `import ui.services.db` always succeeds
# (letting authz.py / mutation_lock.py / security_events.py stay
# importable and their pure logic testable) even in an environment
# where psycopg cannot be installed; only actually opening a
# connection requires it. NOT EXECUTED in this sandbox for that
# reason - psycopg is not installable here (see the delivery report).
# ============================================================

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator


class DatabaseNotConfiguredError(Exception):
    """Raised when VERGI_IAM_DATABASE_URL is unset - fails closed rather
    than silently falling back to any default (never a production DB
    guessed at, never a hardcoded local default that could mask
    misconfiguration)."""


def get_dsn() -> str:
    dsn = os.environ.get("VERGI_IAM_DATABASE_URL")
    if not dsn:
        raise DatabaseNotConfiguredError(
            "VERGI_IAM_DATABASE_URL is not set; refusing to guess a database"
        )
    return dsn


def get_connection():
    """Returns a new psycopg connection with autocommit disabled (caller
    controls the transaction boundary explicitly)."""
    import psycopg  # lazy import

    conn = psycopg.connect(get_dsn())
    conn.autocommit = False
    return conn


@contextmanager
def transaction() -> Iterator["object"]:
    """Opens one connection, one transaction. Commits on clean exit,
    rolls back on any exception (including inside `with`), and always
    closes the connection. Every durable IAM mutation in this project
    uses exactly one call to this context manager - the whole mutation
    (data change + typed security event) happens inside the `with`
    block, and `mutation_lock.acquire_global_iam_lock(conn)` is called
    first thing inside it for the nine admin commands that require it."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_session_lock_connection():
    """Row 19C-1 addition (UNCHANGED: `get_connection()`/`transaction()`
    above remain exactly as Row 19B left them - this is a new,
    additive function, not a modification of either).

    Returns a NEW psycopg connection in autocommit mode - every
    statement commits immediately, with no explicit `conn.commit()`
    call needed or expected from the caller. This is ONLY for
    `ui.services.mutation_coordinator`, which must hold a
    session-level `pg_advisory_lock` (see
    `ui.services.mutation_lock.acquire_case_lock_session`/
    `acquire_global_lock_session`) across several SEPARATELY-durable
    writes (a journal `prepared` row, then an `executing` update, then
    the real file mutation running OUTSIDE any Postgres transaction,
    then a final `completed`/`failed` update) - each step must become
    visible to a concurrent reconciliation process as soon as it
    happens, not sit inside one long transaction that could still be
    rolled back.

    Autocommit mode does not, by itself, change when the advisory lock
    releases - `pg_advisory_lock` is tied to the SESSION (this
    connection), never to any one transaction, autocommit or not. What
    autocommit mode buys here is simply that the caller does not have
    to remember to call `conn.commit()` after every one of those
    several separate writes. The lock still auto-releases if this
    connection drops uncleanly (crash, network loss) - that is
    PostgreSQL's own guarantee for `pg_advisory_lock`, not something
    this function implements.

    The caller is fully responsible for eventually releasing the lock
    (`mutation_lock.release_lock_session`) and closing this connection
    in a `finally` block - this function does not return a context
    manager, unlike `transaction()`, because a single `with`-scoped
    commit/rollback cycle is not the right shape for a lock that must
    outlive several independent commits."""
    import psycopg  # lazy import, matches get_connection()

    conn = psycopg.connect(get_dsn())
    conn.autocommit = True
    return conn
