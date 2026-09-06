# ============================================================
# Row 19B - isolated tests for ui/services/session_store.py.
# Pure logic (token/hash, expiry math, cookie attrs, HKDF CSRF
# derivation) - no DB, no network. The DB-backed CRUD functions
# (create_session/load_session_by_token) are NOT EXECUTED here -
# they lazy-import psycopg, which is unavailable in this sandbox.
#
# Run: python -m ui.tests.test_session_store_isolated
# ============================================================

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import session_store as ss   # noqa: E402

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


# --- token / hash ---
t1, t2 = ss.generate_session_token(), ss.generate_session_token()
check("session tokens are unique across calls", t1 != t2)
h1 = ss.hash_session_token(t1)
check("hash is deterministic for the same token", h1 == ss.hash_session_token(t1))
check("hash never equals the raw token", h1 != t1)
check("hash differs for a different token", h1 != ss.hash_session_token(t2))

# --- expiry math ---
now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
expiry = ss.compute_expiry(now)
check("idle expiry is now + 30 minutes", expiry.idle_expires_at == now + timedelta(minutes=30))
check("absolute expiry is now + 8 hours", expiry.absolute_expires_at == now + timedelta(hours=8))

ss.check_not_expired(expiry.idle_expires_at, expiry.absolute_expires_at, now=now + timedelta(minutes=10))
check("a session well within both windows passes", True)

expect_raises(
    ss.SessionExpiredError,
    lambda: ss.check_not_expired(expiry.idle_expires_at, expiry.absolute_expires_at, now=now + timedelta(minutes=31)),
    "idle timeout (31 minutes of inactivity) is rejected",
)
try:
    ss.check_not_expired(expiry.idle_expires_at, expiry.absolute_expires_at, now=now + timedelta(minutes=31))
    check("idle timeout reason_code", False)
except ss.SessionExpiredError as e:
    check("idle timeout reports reason_code=idle_timeout", e.reason_code == "idle_timeout")

# absolute timeout even if idle was continuously renewed (simulate: idle
# window itself pushed out past 8h, but absolute_expires_at is fixed at
# creation and never moves)
far_future = now + timedelta(hours=9)
expect_raises(
    ss.SessionExpiredError,
    lambda: ss.check_not_expired(far_future + timedelta(minutes=25), expiry.absolute_expires_at, now=far_future),
    "absolute timeout (8 hours) is rejected even with a freshly-renewed idle window",
)
try:
    ss.check_not_expired(far_future + timedelta(minutes=25), expiry.absolute_expires_at, now=far_future)
    check("absolute timeout reason_code", False)
except ss.SessionExpiredError as e:
    check("absolute timeout reports reason_code=absolute_timeout (distinct from idle)", e.reason_code == "absolute_timeout")

renewed = ss.renew_idle_expiry(now)
check("renew_idle_expiry slides exactly 30 minutes forward", renewed == now + timedelta(minutes=30))

# --- cookie contract ---
c = ss.build_session_cookie("token-value")
check("cookie name is __Host-session", c.name == "__Host-session")
check("cookie is Secure", c.secure is True)
check("cookie is HttpOnly", c.httponly is True)
check("cookie SameSite=Lax", c.samesite == "Lax")
check("cookie Path=/", c.path == "/")
check("cookie has no Max-Age/Expires (not persistent)", c.max_age is None)

logout_c = ss.build_logout_cookie()
check(
    "logout cookie matches the original's exact name/path/attributes",
    (logout_c.name, logout_c.path, logout_c.secure, logout_c.httponly, logout_c.samesite)
    == (c.name, c.path, c.secure, c.httponly, c.samesite),
)
check("logout cookie sets Max-Age=0", logout_c.max_age == 0)
check("logout cookie value is empty", logout_c.value == "")

# --- CSRF secret derivation (HKDF via `cryptography`) ---
pepper = b"server-pepper-32-bytes-exactly!!"
secret_a = ss.derive_csrf_secret(h1, server_pepper=pepper)
secret_a2 = ss.derive_csrf_secret(h1, server_pepper=pepper)
check("CSRF secret derivation is deterministic for the same (token_hash, pepper)", secret_a == secret_a2)
check("derived CSRF secret is 32 bytes", len(secret_a) == 32)

other_hash = ss.hash_session_token(t2)
secret_b = ss.derive_csrf_secret(other_hash, server_pepper=pepper)
check("different sessions derive different CSRF secrets", secret_a != secret_b)

other_pepper = b"a-completely-different-pepper!!!"
secret_c = ss.derive_csrf_secret(h1, server_pepper=other_pepper)
check("a different server pepper derives a different CSRF secret for the same session", secret_a != secret_c)

check(
    "no csrf_secret is ever derived from the raw token (only from its hash)",
    ss.derive_csrf_secret(h1, server_pepper=pepper) == ss.derive_csrf_secret(ss.hash_session_token(t1), server_pepper=pepper),
)

# --- DB-backed functions are guarded/NOT EXECUTED ---
try:
    import psycopg  # noqa: F401
    _HAS_PSYCOPG = True
except ModuleNotFoundError:
    _HAS_PSYCOPG = False

if not _HAS_PSYCOPG:
    print("SKIPPED create_session / load_session_by_token - psycopg not installed in this environment. NOT EXECUTED, not a pass.")
else:
    print("psycopg detected but real-DB session CRUD tests require a live iam schema - see test_iam_migrations_isolated.py.")

print(f"--- test_session_store_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
