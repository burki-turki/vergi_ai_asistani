# ============================================================
# Row 19B - FastAPI TestClient tests for ui/auth_routes.py
# (GET /auth/login, GET /auth/callback, POST /auth/logout) and the
# require_principal/authorize_or_redirect wiring into ui/main.py's
# other routes.
#
# BU DOSYA CLOUD SANDBOX'TA DEĞİL, SİZİN MAKİNENİZDE (FastAPI +
# Authlib + joserfc + psycopg kurulu Python 3.14 venv) çalıştırılmak
# üzere yazıldı - mirrors test_routes.py's own guard/skip convention
# exactly (see that file's header). NOT EXECUTED in this sandbox.
#
# WHAT THIS FILE DOES NOT DEPEND ON: a real PostgreSQL cluster or a
# real Microsoft Entra tenant. `ui.services.db.get_connection` is
# monkeypatched to a small in-memory fake (same style as
# test_iam_admin_isolated.py's FakeDB/FakeCursor - a minimal SQL
# pattern-matcher for exactly the statements auth_routes.py/
# session_store.py/security_events.py issue), and
# `ui.services.oidc_client.build_authorization_url` /
# `exchange_code_for_tokens` / `fetch_and_verify_id_token` are
# monkeypatched to avoid a real network call to Authlib/joserfc/Entra -
# this isolates auth_routes.py's OWN orchestration logic (which this
# Row adds) from oidc_client.py's claims-shape validation logic
# (already fully covered, independently, by
# test_oidc_client_isolated.py's 35/35 real passes) and from
# mfa_adapter.py's tiering logic (test_mfa_adapter_isolated.py, 13/13).
# `auth_routes._key_provider` / `_server_pepper` (deliberately
# NotImplementedError seams for Row 19D's real KMS wiring) are
# monkeypatched to a real ui.services.transient_secrets.InMemoryKeyProvider
# and a fixed pepper - exercising the REAL encrypt/decrypt/HKDF code
# paths with a test-only key source, never a hidden bypass of the
# crypto itself.
#
# Run: python -m ui.tests.test_auth_routes
# ============================================================

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:

    import fastapi           # noqa: F401
    from fastapi.testclient import TestClient

    _FASTAPI_AVAILABLE = True

except ModuleNotFoundError:

    _FASTAPI_AVAILABLE = False


if not _FASTAPI_AVAILABLE:

    print("SKIPPED: fastapi bu ortamda kurulu değil - Row 19B auth route testleri çalıştırılamadı.")
    print("Bu dosyayı FastAPI/Authlib/joserfc/psycopg'in kurulu olduğu hedef ortamda çalıştırıp sonucu bildirin.")
    sys.exit(0)


from ui.services import db as db_module              # noqa: E402
from ui.services import oidc_client                  # noqa: E402
from ui.services import transient_secrets as ts       # noqa: E402
from ui.services import security_events as se         # noqa: E402
from ui.services import paths as svc_paths            # noqa: E402
from ui.services.authz import Principal               # noqa: E402
from ui import auth_routes                             # noqa: E402
from ui.main import app                                 # noqa: E402

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


# ----------------------------------------------------------------
# In-memory fake "Postgres" - minimal SQL pattern matcher for exactly
# the statements auth_routes.py / session_store.py / security_events.py
# issue. Modeled on test_iam_admin_isolated.py's FakeDB/FakeCursor.
# ----------------------------------------------------------------

class FakeDB:
    def __init__(self):
        self.users = {}                 # id -> {disabled, authz_version}
        self.identities = {}            # (issuer, subject) -> user_id
        self.oidc_transactions = {}     # id -> dict
        self.oidc_by_state_hash = {}    # state_hash -> id
        self.sessions = {}              # id -> dict
        self.events = []                # list of (event_type, *values)
        # Row 19B test-harness reconciliation: GET / now goes through
        # authz.list_accessible_case_ids -> PostgresAuthzRepository,
        # which needs case_assignments/admin-role data to answer its
        # real queries (see the three new FakeCursor branches below) -
        # these two collections did not exist before that route change.
        self.case_assignments = {}      # id -> {user_id, case_id, revoked}
        self.admins = set()             # {user_id, ...} holding the 'admin' role
        self._next_id = 1

    def _alloc(self):
        i = self._next_id
        self._next_id += 1
        return i


class FakeCursor:
    def __init__(self, db: FakeDB):
        self.db = db
        self._result = None
        self._result_list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        db = self.db
        s = " ".join(sql.split())
        self._result_list = []

        if s.startswith("INSERT INTO iam.oidc_login_transactions"):
            (state_hash, nonce_hash, ciphertext, nonce, key_id, alg, req_ctx_id) = params
            txn_id = db._alloc()
            db.oidc_transactions[txn_id] = dict(
                id=txn_id, state_hash=state_hash, nonce_hash=nonce_hash,
                pkce_verifier_ciphertext=ciphertext, pkce_verifier_nonce=nonce,
                pkce_key_id=key_id, pkce_enc_alg=alg,
                required_authentication_context_id=req_ctx_id,
                consumed_at=None, expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            )
            db.oidc_by_state_hash[state_hash] = txn_id
            self._result = None
            return

        if s.startswith("SELECT id, nonce_hash, pkce_verifier_ciphertext"):
            (state_hash,) = params
            txn_id = db.oidc_by_state_hash.get(state_hash)
            txn = db.oidc_transactions.get(txn_id) if txn_id is not None else None
            if txn is None or txn["consumed_at"] is not None or txn["expires_at"] <= datetime.now(timezone.utc):
                self._result = None
            else:
                self._result = (
                    txn["id"], txn["nonce_hash"], txn["pkce_verifier_ciphertext"],
                    txn["pkce_verifier_nonce"], txn["pkce_key_id"], txn["pkce_enc_alg"],
                    txn["required_authentication_context_id"],
                )
            return

        if s.startswith("UPDATE iam.oidc_login_transactions SET consumed_at"):
            (txn_id,) = params
            db.oidc_transactions[txn_id]["consumed_at"] = datetime.now(timezone.utc)
            self._result = None
            return

        if s.startswith("SELECT u.id, u.disabled, u.authz_version FROM iam.external_identities"):
            issuer, subject = params
            uid = db.identities.get((issuer, subject))
            self._result = (uid, db.users[uid]["disabled"], db.users[uid]["authz_version"]) if uid is not None else None
            return

        if s.startswith("INSERT INTO iam.sessions"):
            (user_id, token_hash, role_version_at_issue, idle_expires_at, absolute_expires_at) = params
            sid = db._alloc()
            db.sessions[sid] = dict(
                id=sid, user_id=user_id, token_hash=token_hash,
                role_version_at_issue=role_version_at_issue,
                idle_expires_at=idle_expires_at, absolute_expires_at=absolute_expires_at,
                revoked_at=None, last_seen_at=None,
            )
            self._result = (sid,)
            return

        if s.startswith("SELECT s.id, s.user_id, s.role_version_at_issue"):
            (token_hash,) = params
            match = next((row for row in db.sessions.values() if row["token_hash"] == token_hash), None)
            if match is None:
                self._result = None
            else:
                u = db.users[match["user_id"]]
                self._result = (
                    match["id"], match["user_id"], match["role_version_at_issue"],
                    match["idle_expires_at"], match["absolute_expires_at"], match["revoked_at"],
                    u["authz_version"], u["disabled"],
                )
            return

        if s.startswith("UPDATE iam.sessions SET last_seen_at"):
            (idle_expires_at, session_id) = params
            db.sessions[session_id]["idle_expires_at"] = idle_expires_at
            self._result = None
            return

        if s.startswith("SELECT token_hash FROM iam.sessions"):
            (session_id,) = params
            self._result = (db.sessions[session_id]["token_hash"],)
            return

        if s.startswith("UPDATE iam.sessions SET revoked_at"):
            (session_id,) = params
            db.sessions[session_id]["revoked_at"] = datetime.now(timezone.utc)
            self._result = None
            return

        if s.startswith("INSERT INTO iam.security_events"):
            db.events.append(tuple(params))
            self._result = None
            return

        # Row 19B test-harness reconciliation: GET / -> main.py's
        # index() -> auth_routes.list_accessible_case_ids ->
        # authz.list_accessible_case_ids -> PostgresAuthzRepository,
        # whose exact queries (authz.py, unchanged by this reconciliation)
        # were not previously handled here, causing "unhandled SQL".
        # Narrow, exact-shape support only - no bypass of the real
        # authz.list_accessible_case_ids decision function itself.

        if s.startswith("SELECT s.user_id, u.authz_version, u.disabled FROM iam.sessions"):
            (session_id,) = params
            row = db.sessions.get(session_id)
            if row is None or row["revoked_at"] is not None:
                self._result = None
            else:
                u = db.users[row["user_id"]]
                self._result = (row["user_id"], u["authz_version"], u["disabled"])
            return

        if s.startswith("SELECT case_id FROM iam.case_assignments"):
            (user_id,) = params
            self._result_list = [
                (a["case_id"],) for a in db.case_assignments.values()
                if a["user_id"] == user_id and not a["revoked"]
            ]
            self._result = None
            return

        if s.startswith("SELECT 1 FROM iam.user_roles"):
            (user_id,) = params
            self._result = (1,) if user_id in db.admins else None
            return

        raise AssertionError(f"unhandled SQL in fake: {s!r}")

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result_list


class FakeConn:
    def __init__(self, db: FakeDB):
        self.db = db

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


SHARED_DB = FakeDB()


def _fake_get_connection():
    return FakeConn(SHARED_DB)


# Monkeypatch the ONE seam both db.transaction() and _repo_conn() use -
# every route in this test suite shares SHARED_DB, exactly like every
# real request in production shares one real PostgreSQL cluster.
db_module.get_connection = _fake_get_connection

# Deterministic, tenant-config-shaped provider - the real _load_provider_config()
# is bypassed here (it reads os.environ) so this suite does not depend on
# environment variables; the env-var reading itself is a one-line function
# with no branching logic worth a TestClient round trip.
_REQUIRED_CTX = "c1-lawyer-mfa"
_PROVIDER_CONFIG = oidc_client.EntraProviderConfig(
    tenant_id="11111111-1111-1111-1111-111111111111",
    client_id="client-abc",
    authorization_endpoint="https://login.microsoftonline.com/x/oauth2/v2.0/authorize",
    token_endpoint="https://login.microsoftonline.com/x/oauth2/v2.0/token",
    jwks_uri="https://login.microsoftonline.com/x/discovery/v2.0/keys",
    redirect_uri="https://app.example/auth/callback",
    required_authentication_context_id=_REQUIRED_CTX,
    mfa_tier="entra_p1",
)
auth_routes._load_provider_config = lambda: _PROVIDER_CONFIG

_TEST_KEY_PROVIDER = ts.InMemoryKeyProvider()
_TEST_KEY_PROVIDER.add_key("k1", b"0" * 32)
_TEST_PEPPER = b"1" * 32
auth_routes._key_provider = lambda: _TEST_KEY_PROVIDER
auth_routes._server_pepper = lambda: _TEST_PEPPER

# Real AuthorizationRequest with a REAL state/nonce/code_verifier
# (pure stdlib, no Authlib needed) but a fixed, obviously-fake `.url` -
# this exercises auth_routes.login()'s own PKCE-persistence orchestration
# for real while avoiding a dependency on Authlib's URL-building.
_LAST_AUTH_REQUEST = {}


def _fake_build_authorization_url(provider_config, *, scope="openid profile"):
    from ui.services.oidc_client import AuthorizationRequest, generate_state, generate_nonce, generate_pkce_pair
    state = generate_state()
    nonce = generate_nonce()
    code_verifier, _challenge = generate_pkce_pair()
    req = AuthorizationRequest(url="https://login.microsoftonline.com/x/fake-auth-url", state=state, nonce=nonce, code_verifier=code_verifier)
    _LAST_AUTH_REQUEST["value"] = req
    return req


async def _fake_exchange_code_for_tokens(provider_config, *, code, code_verifier):
    check(
        "exchange_code_for_tokens receives the SAME code_verifier the AEAD ciphertext decrypted to",
        code_verifier == _LAST_AUTH_REQUEST["value"].code_verifier,
    )
    return {"id_token": "fake-id-token-not-a-real-jwt"}


_NEXT_CLAIMS = {}


def _fake_fetch_and_verify_id_token(id_token, *, jwks_uri, allowed_algorithms=("RS256",)):
    check("fetch_and_verify_id_token receives the id_token from the token response", id_token == "fake-id-token-not-a-real-jwt")
    return _NEXT_CLAIMS["value"]


oidc_client.build_authorization_url = _fake_build_authorization_url
oidc_client.exchange_code_for_tokens = _fake_exchange_code_for_tokens
oidc_client.fetch_and_verify_id_token = _fake_fetch_and_verify_id_token

client = TestClient(app, client=("127.0.0.1", 12345))


def _good_claims(nonce):
    return {
        "iss": f"https://login.microsoftonline.com/{_PROVIDER_CONFIG.tenant_id}/v2.0",
        "aud": _PROVIDER_CONFIG.client_id,
        "tid": _PROVIDER_CONFIG.tenant_id,
        "nonce": nonce,
        "sub": "sub-lawyer-1",
        "acrs": [_REQUIRED_CTX],
    }


def _do_login_redirect():
    """Drives GET /auth/login and returns the AuthorizationRequest that
    was persisted (state/nonce/code_verifier) - httpx TestClient does not
    follow the redirect to the (fake) external authorization_endpoint."""
    resp = client.get("/auth/login", follow_redirects=False)
    check("GET /auth/login redirects (302) to the authorization endpoint", resp.status_code == 302)
    check("GET /auth/login response is Cache-Control: no-store", resp.headers.get("cache-control") == "no-store")
    return _LAST_AUTH_REQUEST["value"]


# ----------------------------------------------------------------
# 1) Full successful login round trip -> a session cookie is set,
#    exactly one login_success security event is recorded.
# ----------------------------------------------------------------

auth_req = _do_login_redirect()
check(
    "GET /auth/login persisted exactly one oidc_login_transactions row",
    len(SHARED_DB.oidc_transactions) == 1,
)

# Seed an existing, active, non-disabled user/identity - Row 19B's no-JIT
# contract requires this row to ALREADY exist; the callback below must
# never create it.
_USER_ID = 100
SHARED_DB.users[_USER_ID] = {"disabled": False, "authz_version": 1}
SHARED_DB.identities[(f"https://login.microsoftonline.com/{_PROVIDER_CONFIG.tenant_id}/v2.0", "sub-lawyer-1")] = _USER_ID

_NEXT_CLAIMS["value"] = _good_claims(auth_req.nonce)

resp = client.get(f"/auth/callback?code=abc&state={auth_req.state}", follow_redirects=False)
check("GET /auth/callback (valid, MFA-satisfied, known identity) redirects to /", resp.status_code == 302 and resp.headers["location"] == "/")
check("GET /auth/callback sets the __Host-session cookie", "__Host-session" in resp.cookies)
check("no user/identity row was created (no-JIT contract)", len(SHARED_DB.users) == 1 and len(SHARED_DB.identities) == 1)
check("exactly one session row was created", len(SHARED_DB.sessions) == 1)

_session_row = next(iter(SHARED_DB.sessions.values()))
check("the new session's role_version_at_issue matches the user's CURRENT authz_version", _session_row["role_version_at_issue"] == 1)

login_success_events = [e for e in SHARED_DB.events if e[0] == "login_success"]
check("exactly one login_success security event was recorded", len(login_success_events) == 1)

_session_cookie_value = resp.cookies.get("__Host-session")

# ----------------------------------------------------------------
# 2) Replay of the SAME state (one-time consumption) -> denied, no
#    second session created.
# ----------------------------------------------------------------

_NEXT_CLAIMS["value"] = _good_claims(auth_req.nonce)
resp_replay = client.get(f"/auth/callback?code=abc&state={auth_req.state}", follow_redirects=False)
check("replaying the SAME state is denied (401)", resp_replay.status_code == 401)
check("replay created no second session", len(SHARED_DB.sessions) == 1)

# ----------------------------------------------------------------
# 3) Unknown identity (no matching external_identities row) -> generic
#    denial, no session, a login_denied_unknown_identity event.
# ----------------------------------------------------------------

auth_req_2 = _do_login_redirect()
_NEXT_CLAIMS["value"] = dict(_good_claims(auth_req_2.nonce), sub="sub-nobody")
resp_unknown = client.get(f"/auth/callback?code=abc&state={auth_req_2.state}", follow_redirects=False)
check("unknown (issuer, subject) identity is denied (401), never JIT-provisioned", resp_unknown.status_code == 401)
check("unknown identity created no session", len(SHARED_DB.sessions) == 1)
check(
    "a login_denied_unknown_identity event was recorded for the unknown-identity denial",
    any(e[0] == "login_denied_unknown_identity" for e in SHARED_DB.events),
)

# ----------------------------------------------------------------
# 4) Disabled user -> denied, a login_denied_disabled_user event.
# ----------------------------------------------------------------

SHARED_DB.users[_USER_ID]["disabled"] = True
auth_req_3 = _do_login_redirect()
_NEXT_CLAIMS["value"] = _good_claims(auth_req_3.nonce)
resp_disabled = client.get(f"/auth/callback?code=abc&state={auth_req_3.state}", follow_redirects=False)
check("a disabled user's otherwise-valid login is denied (401)", resp_disabled.status_code == 401)
check("disabled-user denial created no session", len(SHARED_DB.sessions) == 1)
check(
    "a login_denied_disabled_user event was recorded",
    any(e[0] == "login_denied_disabled_user" for e in SHARED_DB.events),
)
SHARED_DB.users[_USER_ID]["disabled"] = False  # restore for later scenarios

# ----------------------------------------------------------------
# 5) MFA/acrs absent when required (entra_p1 tier) -> denied, a
#    login_denied_mfa_absent event, NEVER a session.
# ----------------------------------------------------------------

auth_req_4 = _do_login_redirect()
claims_no_acrs = _good_claims(auth_req_4.nonce)
del claims_no_acrs["acrs"]
_NEXT_CLAIMS["value"] = claims_no_acrs
resp_no_mfa = client.get(f"/auth/callback?code=abc&state={auth_req_4.state}", follow_redirects=False)
check("missing acrs on the P1 tier is denied (401)", resp_no_mfa.status_code == 401)
check("missing-acrs denial created no session", len(SHARED_DB.sessions) == 1)
check(
    "a login_denied_mfa_absent event was recorded for the missing-acrs denial",
    any(e[0] == "login_denied_mfa_absent" for e in SHARED_DB.events),
)

# ----------------------------------------------------------------
# 6) Tampered/wrong nonce -> denied BEFORE validate_claims_for_login
#    ever runs (verified via the explicit hash comparison, independent
#    of the ExpectedClaims.nonce=None skip fixed in oidc_client.py).
# ----------------------------------------------------------------

auth_req_5 = _do_login_redirect()
_NEXT_CLAIMS["value"] = _good_claims("a-completely-different-nonce")
resp_bad_nonce = client.get(f"/auth/callback?code=abc&state={auth_req_5.state}", follow_redirects=False)
check("a tampered/mismatched nonce is denied (401)", resp_bad_nonce.status_code == 401)
check("mismatched-nonce denial created no session", len(SHARED_DB.sessions) == 1)


def _last_mfa_absent_reason_code():
    matches = [e for e in SHARED_DB.events if e[0] == "login_denied_mfa_absent"]
    return matches[-1][2] if matches else None


# ----------------------------------------------------------------
# 6b) Row 19B targeted remediation (finding 3) - login-denial security-
# event classification. Every ClaimsValidationError/MfaAssuranceDeniedError
# reaching callback()'s except-block must be recorded with ITS OWN
# reason_code, not collapsed into "mfa_claim_absent" across the board.
# One scenario per closed reason_code this call site can actually
# produce, proving each is classified distinctly and correctly.
# ----------------------------------------------------------------

# 6b-i) acrs missing entirely -> mfa_claim_absent (already exercised by
# scenario 5 above as a behavioral/status-code check; re-verified here
# for its EXACT reason_code, now that misclassification is the thing
# under test).
auth_req_6 = _do_login_redirect()
claims_acrs_absent = _good_claims(auth_req_6.nonce)
del claims_acrs_absent["acrs"]
_NEXT_CLAIMS["value"] = claims_acrs_absent
resp_acrs_absent = client.get(f"/auth/callback?code=abc&state={auth_req_6.state}", follow_redirects=False)
check("acrs-absent denial (P1 tier) is a 401", resp_acrs_absent.status_code == 401)
check("acrs-absent denial is classified as reason_code=mfa_claim_absent", _last_mfa_absent_reason_code() == "mfa_claim_absent")

# 6b-ii) acrs present but malformed (wrong type) -> mfa_claim_malformed
auth_req_7 = _do_login_redirect()
claims_acrs_malformed = _good_claims(auth_req_7.nonce)
claims_acrs_malformed["acrs"] = _REQUIRED_CTX  # bare scalar string, not an array
_NEXT_CLAIMS["value"] = claims_acrs_malformed
resp_acrs_malformed = client.get(f"/auth/callback?code=abc&state={auth_req_7.state}", follow_redirects=False)
check("malformed-acrs denial (P1 tier) is a 401", resp_acrs_malformed.status_code == 401)
check(
    "malformed-acrs (scalar instead of array) denial is classified as reason_code=mfa_claim_malformed, "
    "NOT collapsed into mfa_claim_absent",
    _last_mfa_absent_reason_code() == "mfa_claim_malformed",
)

# 6b-iii) acrs present, well-formed, but missing the required context id -> mfa_claim_mismatch
auth_req_8 = _do_login_redirect()
claims_acrs_mismatch = _good_claims(auth_req_8.nonce)
claims_acrs_mismatch["acrs"] = ["some-other-context", "yet-another"]
_NEXT_CLAIMS["value"] = claims_acrs_mismatch
resp_acrs_mismatch = client.get(f"/auth/callback?code=abc&state={auth_req_8.state}", follow_redirects=False)
check("acrs-mismatch denial (P1 tier) is a 401", resp_acrs_mismatch.status_code == 401)
check(
    "acrs present but not containing the required context is classified as reason_code=mfa_claim_mismatch, "
    "NOT collapsed into mfa_claim_absent",
    _last_mfa_absent_reason_code() == "mfa_claim_mismatch",
)

# 6b-iv) standard-claims failure (wrong issuer) reaching the SAME except
# block -> unknown_identity, not mfa_claim_absent. This is the case the
# original bug most visibly mishandled: a ClaimsValidationError NOT
# related to MFA at all was still being written as mfa_claim_absent.
auth_req_9 = _do_login_redirect()
claims_wrong_issuer = _good_claims(auth_req_9.nonce)
claims_wrong_issuer["iss"] = "https://login.microsoftonline.com/some-other-tenant/v2.0"
_NEXT_CLAIMS["value"] = claims_wrong_issuer
resp_wrong_issuer = client.get(f"/auth/callback?code=abc&state={auth_req_9.state}", follow_redirects=False)
check("wrong-issuer denial is a 401", resp_wrong_issuer.status_code == 401)
check(
    "a standard-claims failure (wrong issuer) is classified as reason_code=unknown_identity, "
    "NOT collapsed into mfa_claim_absent - the original bug this remediation fixes",
    _last_mfa_absent_reason_code() == "unknown_identity",
)

# 6b-v) Entra ID Free tier's unconditional structural denial (raised
# directly by mfa_adapter.MfaAssuranceDeniedError, a DIFFERENT exception
# type than oidc_client.ClaimsValidationError but caught by the SAME
# except clause) -> still mfa_claim_absent, proving both exception types
# in the except tuple are classified through the same closed mapping.
_PROVIDER_CONFIG_FREE = oidc_client.EntraProviderConfig(
    tenant_id=_PROVIDER_CONFIG.tenant_id,
    client_id=_PROVIDER_CONFIG.client_id,
    authorization_endpoint=_PROVIDER_CONFIG.authorization_endpoint,
    token_endpoint=_PROVIDER_CONFIG.token_endpoint,
    jwks_uri=_PROVIDER_CONFIG.jwks_uri,
    redirect_uri=_PROVIDER_CONFIG.redirect_uri,
    required_authentication_context_id=_REQUIRED_CTX,
    mfa_tier="entra_free",
)
_original_load_provider_config = auth_routes._load_provider_config
auth_routes._load_provider_config = lambda: _PROVIDER_CONFIG_FREE
try:
    auth_req_10 = _do_login_redirect()
    claims_free_tier = _good_claims(auth_req_10.nonce)
    del claims_free_tier["acrs"]  # Free tier never has/needs acrs - the denial is purely tier-structural
    _NEXT_CLAIMS["value"] = claims_free_tier
    resp_free_tier = client.get(f"/auth/callback?code=abc&state={auth_req_10.state}", follow_redirects=False)
    check("Entra ID Free tier's unconditional MFA denial is a 401", resp_free_tier.status_code == 401)
    check(
        "Entra Free's provider-tier/policy denial (MfaAssuranceDeniedError, a different exception type than "
        "ClaimsValidationError) is STILL correctly classified as mfa_claim_absent via the same closed mapping",
        _last_mfa_absent_reason_code() == "mfa_claim_absent",
    )
finally:
    auth_routes._load_provider_config = _original_load_provider_config

# 6b-vi) defensive fail-closed: an exception reaching the except-block
# with a reason_code OUTSIDE the closed set this call site can produce
# must never be written verbatim - it must fall back to the generic
# mfa_claim_absent member, proving misclassification into an
# unrecognized/raw value is impossible even if oidc_client.py's own
# vocabulary were ever extended incorrectly.
_original_validate_claims_for_login = oidc_client.validate_claims_for_login


def _raise_unrecognized_reason_code(*args, **kwargs):
    raise oidc_client.ClaimsValidationError("totally_unrecognized_reason_code", "simulated")


oidc_client.validate_claims_for_login = _raise_unrecognized_reason_code
try:
    auth_req_11 = _do_login_redirect()
    _NEXT_CLAIMS["value"] = _good_claims(auth_req_11.nonce)
    resp_unrecognized = client.get(f"/auth/callback?code=abc&state={auth_req_11.state}", follow_redirects=False)
    check("an exception carrying an unrecognized reason_code is still denied (401)", resp_unrecognized.status_code == 401)
    check(
        "an unrecognized/out-of-vocabulary reason_code is NEVER written verbatim to the security event - "
        "it fails closed to the generic mfa_claim_absent, proving misclassification is impossible",
        _last_mfa_absent_reason_code() == "mfa_claim_absent",
    )
finally:
    oidc_client.validate_claims_for_login = _original_validate_claims_for_login

# ----------------------------------------------------------------
# 7) require_principal() wiring: an unauthenticated request to a
#    protected route redirects to /login (NOT straight to /auth/login -
#    see the comment in main.py's _not_authenticated_handler).
# ----------------------------------------------------------------

anon_resp = client.get("/", follow_redirects=False)
check("GET / with no session cookie redirects to /login", anon_resp.status_code == 302 and anon_resp.headers["location"] == "/login")

_idle_expires_before_renewal = _session_row["idle_expires_at"]

authed_resp = client.get("/", cookies={"__Host-session": _session_cookie_value}, follow_redirects=False)
check("GET / with a valid session cookie succeeds (200)", authed_resp.status_code == 200)

# require_principal() unconditionally UPDATEs idle_expires_at to a fresh
# now()+30min on every successful authenticated request (session_store.
# renew_idle_expiry) - compare the recorded value before/after rather
# than reasoning about absolute_expires_at, which this call never touches.
check(
    "require_principal() renewed (slid forward) the session's idle_expires_at on a successful authenticated request",
    _session_row["idle_expires_at"] > _idle_expires_before_renewal,
)

# ----------------------------------------------------------------
# 7b) Row 19B test-harness reconciliation - GET / case-enumeration
# route proof. main.py's index() now calls the REAL
# authz.list_accessible_case_ids -> PostgresAuthzRepository, which
# issues real session-state / active-assignment / admin-role queries
# this file's FakeCursor answers via the new branches above (not a
# monkeypatch of list_accessible_case_ids itself, and not a fixed
# return value) - so this exercises the ACTUAL production decision
# function through the ACTUAL route.
# ----------------------------------------------------------------

_CASE_OWN_REVOKED = "case_auth_routes_own_revoked_row19b"
_CASE_OTHER_USER = "case_auth_routes_belongs_to_someone_else_row19b"
_CASE_STALE = "case_auth_routes_stale_unresolvable_row19b"
_OTHER_USER_ID = 777
SHARED_DB.users.setdefault(_OTHER_USER_ID, {"disabled": False, "authz_version": 1})


def _add_assignment(user_id, cid, revoked=False):
    aid = SHARED_DB._alloc()
    SHARED_DB.case_assignments[aid] = {"user_id": user_id, "case_id": cid, "revoked": revoked}
    return aid


_add_assignment(_USER_ID, _CASE_OWN_REVOKED, revoked=True)
_add_assignment(_OTHER_USER_ID, _CASE_OTHER_USER)
_add_assignment(_USER_ID, _CASE_STALE)  # not a real case directory - paths.resolve_case_id must drop it silently

# The "own active, resolvable" positive case needs a case_id that
# GENUINELY resolves via the real (unmocked) paths.resolve_case_id -
# resolve_case_id only ever returns a case_id that list_case_ids()
# itself discovered on disk, so a synthetic string can never satisfy it.
_real_case_ids_for_listing = svc_paths.list_case_ids()
if _real_case_ids_for_listing:
    _real_own_case_id = _real_case_ids_for_listing[0]
    _add_assignment(_USER_ID, _real_own_case_id)

resp_listing = client.get("/", cookies={"__Host-session": _session_cookie_value}, follow_redirects=False)
check(
    "GET / (lawyer, valid session, active/revoked/stale/cross-user assignments seeded) -> 200, does not crash",
    resp_listing.status_code == 200,
    f"status={resp_listing.status_code}",
)

if _real_case_ids_for_listing:
    check(
        "GET / lists the user's own ACTIVE, filesystem-resolvable assigned case",
        _real_own_case_id in resp_listing.text,
    )
else:
    print(
        "SKIPPED the positive resolvable-case assertion for GET / - no real case exists under "
        "data/cases/ in this run. NOT EXECUTED, not a pass; the negative/isolation assertions "
        "below still ran and do not depend on real case data."
    )

check("GET / does NOT list the user's own REVOKED assignment", _CASE_OWN_REVOKED not in resp_listing.text)
check(
    "GET / does NOT list a case assigned to a DIFFERENT user_id (cross-user isolation)",
    _CASE_OTHER_USER not in resp_listing.text,
)
check(
    "GET / does NOT list a stale/nonexistent assigned case (filesystem-unresolvable), and the page still renders",
    _CASE_STALE not in resp_listing.text,
)

SHARED_DB.admins.add(_USER_ID)
try:
    resp_admin_listing = client.get("/", cookies={"__Host-session": _session_cookie_value}, follow_redirects=False)
    check("GET / (same session, now marked global admin) -> 200", resp_admin_listing.status_code == 200)
    if _real_case_ids_for_listing:
        check(
            "GET / lists ZERO case ids for a global admin, even though the same active assignment "
            "from above still exists (unconditional admin veto)",
            _real_own_case_id not in resp_admin_listing.text,
        )
    check(
        "GET / (admin) also lists none of the revoked/other-user/stale markers",
        _CASE_OWN_REVOKED not in resp_admin_listing.text
        and _CASE_OTHER_USER not in resp_admin_listing.text
        and _CASE_STALE not in resp_admin_listing.text,
    )
finally:
    SHARED_DB.admins.discard(_USER_ID)  # restore non-admin state for the rest of this file

SHARED_DB.case_assignments.clear()  # isolation: nothing seeded here leaks past this point in the file

# ----------------------------------------------------------------
# 8) POST /auth/logout: missing/wrong CSRF -> 403, session NOT revoked;
#    correct CSRF + same-origin -> session revoked, cookie cleared,
#    redirected to /login.
# ----------------------------------------------------------------

resp_logout_bad_csrf = client.post(
    "/auth/logout", cookies={"__Host-session": _session_cookie_value},
    data={"csrf_token": "wrong"}, follow_redirects=False,
)
check("POST /auth/logout with a wrong CSRF token is rejected (403)", resp_logout_bad_csrf.status_code == 403)
check("a wrong-CSRF logout attempt does NOT revoke the session", _session_row["revoked_at"] is None)

real_csrf_secret = auth_routes.csrf_secret_for_request(
    None, Principal(user_id=_USER_ID, session_id=_session_row["id"], role_version_at_issue=1),
)
from ui.services import security as security_module
real_csrf_token = security_module.make_csrf_token(real_csrf_secret, "logout")

resp_logout_ok = client.post(
    "/auth/logout", cookies={"__Host-session": _session_cookie_value},
    data={"csrf_token": real_csrf_token},
    # Deliberately NO Origin/Referer header here - security.is_same_origin
    # treats an ABSENT header as "allow" (some legitimate clients omit
    # Origin on same-origin POSTs); test_routes.py's own T10 uses this
    # same absent-header path for its "should succeed" case and reserves
    # an explicit WRONG Origin (http://evil.example-style) for the
    # negative case, which is not this scenario's concern (CSRF-token
    # correctness is what this scenario isolates).
    follow_redirects=False,
)
check("POST /auth/logout with the correct CSRF token + same-origin succeeds (302 -> /login)", resp_logout_ok.status_code == 302 and resp_logout_ok.headers["location"] == "/login")
check("logout revoked the session", _session_row["revoked_at"] is not None)
check(
    "a session_revoked security event was recorded for the logout",
    any(e[0] == "session_revoked" for e in SHARED_DB.events),
)

after_logout_resp = client.get("/", cookies={"__Host-session": _session_cookie_value}, follow_redirects=False)
check("the revoked session cookie no longer authenticates (redirects to /login again)", after_logout_resp.status_code == 302 and after_logout_resp.headers["location"] == "/login")

print(f"--- test_auth_routes: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
