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
