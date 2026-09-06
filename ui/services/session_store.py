# ============================================================
# Row 19B - server-side opaque sessions, cookie contract, and
# session-derived CSRF secret.
#
# Split the same way as the other Row 19B modules: PURE functions
# (token/hash generation, expiry math, cookie attribute construction,
# HKDF-based CSRF secret derivation) need only the stdlib + the
# already-available `cryptography` package and are fully executed by
# ui/tests/test_session_store_isolated.py. DB-backed CRUD
# (create_session / load_session / revoke_session / touch_session)
# lazy-imports ui.services.db and is NOT EXECUTED in this sandbox.
# ============================================================

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

IDLE_TIMEOUT = timedelta(minutes=30)
ABSOLUTE_TIMEOUT = timedelta(hours=8)

SESSION_COOKIE_NAME = "__Host-session"

_CSRF_HKDF_INFO = b"vergi-ai:csrf:v1"
_CSRF_SECRET_LENGTH = 32


# ---------------------------------------------------------------
# Opaque token / hash - pure stdlib.
# ---------------------------------------------------------------

def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """SHA-256 hash, stored as iam.sessions.token_hash. The raw token is
    NEVER persisted - only this hash, and only this hash is compared
    against the incoming cookie value on every request."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------
# Expiry math - pure.
# ---------------------------------------------------------------

@dataclass(frozen=True)
class SessionExpiry:
    idle_expires_at: datetime
    absolute_expires_at: datetime


def compute_expiry(now: datetime | None = None) -> SessionExpiry:
    now = now or datetime.now(timezone.utc)
    return SessionExpiry(
        idle_expires_at=now + IDLE_TIMEOUT,
        absolute_expires_at=now + ABSOLUTE_TIMEOUT,
    )


class SessionExpiredError(Exception):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def check_not_expired(idle_expires_at: datetime, absolute_expires_at: datetime, *, now: datetime | None = None) -> None:
    """Raises SessionExpiredError with the correct reason_code (idle_timeout
    vs absolute_timeout) - callers use this to pick which
    security_events writer to call."""
    now = now or datetime.now(timezone.utc)
    if now >= absolute_expires_at:
        raise SessionExpiredError("absolute_timeout")
    if now >= idle_expires_at:
        raise SessionExpiredError("idle_timeout")


def renew_idle_expiry(now: datetime | None = None) -> datetime:
    """Called on every authenticated request that does NOT fail expiry -
    slides the idle window forward without touching absolute_expires_at."""
    now = now or datetime.now(timezone.utc)
    return now + IDLE_TIMEOUT


# ---------------------------------------------------------------
# Cookie attribute contract - pure.
# ---------------------------------------------------------------

@dataclass(frozen=True)
class CookieAttributes:
    name: str
    value: str
    secure: bool
    httponly: bool
    samesite: str
    path: str
    max_age: int | None  # None => session cookie (no Max-Age/Expires at all)


def build_session_cookie(token: str) -> CookieAttributes:
    return CookieAttributes(
        name=SESSION_COOKIE_NAME, value=token, secure=True, httponly=True,
        samesite="Lax", path="/", max_age=None,
    )


def build_logout_cookie() -> CookieAttributes:
    """The clearing Set-Cookie MUST match the original cookie's exact
    name/path/attributes, differing only by Max-Age=0 and an empty value -
    a mismatched attribute set silently fails to clear the cookie in some
    browsers."""
    return CookieAttributes(
        name=SESSION_COOKIE_NAME, value="", secure=True, httponly=True,
        samesite="Lax", path="/", max_age=0,
    )


# ---------------------------------------------------------------
# CSRF secret derivation - HKDF via `cryptography` (already a
# dependency via joserfc's own requirement; no extra package needed,
# no stored csrf_secret column anywhere).
# ---------------------------------------------------------------

def derive_csrf_secret(token_hash: str, *, server_pepper: bytes) -> bytes:
    """ikm = the session's OWN token_hash bytes (never the raw token);
    salt = server_pepper (from a Row-19D-backed key-provider interface,
    never persisted/exposed - callers pass it in, this function has no
    notion of where it comes from). Deterministic per (token_hash,
    server_pepper) pair - re-derived fresh per request, never cached in
    the DB."""
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_CSRF_SECRET_LENGTH,
        salt=server_pepper,
        info=_CSRF_HKDF_INFO,
    )
    return hkdf.derive(token_hash.encode("utf-8"))


# ---------------------------------------------------------------
# DB-backed session CRUD - lazy psycopg import. NOT EXECUTED here.
# ---------------------------------------------------------------

def create_session(conn, *, user_id: int, role_version_at_issue: int) -> tuple[str, int]:
    """Returns (raw_token, session_id). Caller sets the cookie from
    raw_token and discards it immediately after - only the hash is
    persisted."""
    token = generate_session_token()
    token_hash = hash_session_token(token)
    expiry = compute_expiry()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO iam.sessions
               (user_id, token_hash, role_version_at_issue, idle_expires_at, absolute_expires_at)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (user_id, token_hash, role_version_at_issue, expiry.idle_expires_at, expiry.absolute_expires_at),
        )
        session_id = cur.fetchone()[0]
    return token, session_id


def load_session_by_token(conn, token: str):
    token_hash = hash_session_token(token)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT s.id, s.user_id, s.role_version_at_issue, s.idle_expires_at,
                      s.absolute_expires_at, s.revoked_at, u.authz_version, u.disabled
               FROM iam.sessions s JOIN iam.users u ON u.id = s.user_id
               WHERE s.token_hash = %s""",
            (token_hash,),
        )
        return cur.fetchone()
