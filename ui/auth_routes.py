# ============================================================
# Row 19B - /auth/* routes (login, callback, logout) and the
# request-scoped principal extraction shared by every other route in
# ui/main.py.
#
# This module needs FastAPI/Starlette to import - NOT EXECUTED in
# this sandbox (see the delivery report). Its logic is written in
# full against the real contract: no JIT provisioning at callback, no
# session/CSRF-secret persistence beyond the token hash, the
# `__Host-session` cookie contract from ui.services.session_store,
# and Cache-Control: no-store on every auth response.
# ============================================================

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse

from .services import authz, session_store, security_events, oidc_client, mfa_adapter
from .services.authz import Principal, CaseAccessDeniedError

logger = logging.getLogger("vergi_ui.auth")

router = APIRouter()

# Row 19B targeted remediation (finding 3). The exact, closed set of
# reason codes that `oidc_client.ClaimsValidationError` and
# `mfa_adapter.MfaAssuranceDeniedError` can carry when raised from the
# specific call site inside callback() below (claims/standard-claims
# validation and MFA-assurance evaluation) - see oidc_client.py's
# validate_standard_claims/validate_acrs_claim and mfa_adapter.py's
# evaluate_mfa_assurance_entra for the exhaustive list of reason_code
# values each can raise. This mirrors the DB CHECK constraint on
# iam.security_events.reason_code (db/migrations/0001_iam_schema.sql),
# which already lists all four values - no schema change is needed.
# A reason_code outside this closed set (defensive: should not happen
# given the two exception types' own code, but the classification must
# not depend on that always remaining true) fails closed to the most
# generic member of the set, "mfa_claim_absent", rather than ever
# writing the raw/unknown value into the security event.
_CALLBACK_CLAIMS_DENIAL_REASON_CODES = frozenset({
    "unknown_identity",
    "mfa_claim_absent",
    "mfa_claim_malformed",
    "mfa_claim_mismatch",
})


class NotAuthenticatedError(Exception):
    """Raised by require_principal() when no valid session cookie is
    present. Route wrappers in main.py catch this and redirect to
    /auth/login (as opposed to CaseAccessDeniedError, which is an
    authenticated-but-denied case and stays a generic 404)."""


def _no_store_headers() -> dict:
    return {"Cache-Control": "no-store"}


def require_principal(request: Request) -> Principal:
    """The single place every route in main.py obtains its Principal.
    Loads the session by the __Host-session cookie's hash, checks
    disabled/expiry with a FRESH read (never trusts a cached value from
    earlier in the request), and renews the idle window on success.
    Raises NotAuthenticatedError on any failure - callers decide how to
    respond (redirect vs a specific error page), this function never
    renders anything itself."""
    from .services import db  # lazy import (psycopg)

    token = request.cookies.get(session_store.SESSION_COOKIE_NAME)
    if not token:
        raise NotAuthenticatedError("no session cookie")

    with db.transaction() as conn:
        row = session_store.load_session_by_token(conn, token)
        if row is None:
            raise NotAuthenticatedError("unknown session token")

        session_id, user_id, role_version_at_issue, idle_expires_at, absolute_expires_at, revoked_at, authz_version, disabled = row

        if revoked_at is not None:
            raise NotAuthenticatedError("session revoked")
        if disabled:
            raise NotAuthenticatedError("user disabled")

        try:
            session_store.check_not_expired(idle_expires_at, absolute_expires_at)
        except session_store.SessionExpiredError as exc:
            if exc.reason_code == "idle_timeout":
                security_events.record_session_expired_idle(conn, user_id=user_id, session_id=session_id)
            else:
                security_events.record_session_expired_absolute(conn, user_id=user_id, session_id=session_id)
            raise NotAuthenticatedError(exc.reason_code) from exc

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE iam.sessions SET last_seen_at = now(), idle_expires_at = %s WHERE id = %s",
                (session_store.renew_idle_expiry(), session_id),
            )

    return Principal(user_id=user_id, session_id=session_id, role_version_at_issue=role_version_at_issue)


def authorize_or_redirect(request: Request, case_id: str, capability: str):
    """Shared helper for main.py's routes: returns the filesystem-safe
    resolved case path on success. Raises NotAuthenticatedError (caller
    redirects to /auth/login) or CaseAccessDeniedError (caller renders
    the existing generic 404 - unchanged from Row 18's behavior, now
    reached via a different, authorization-aware path)."""
    principal = require_principal(request)
    return authz.authorize_case_access(principal, case_id, capability, repository=authz.PostgresAuthzRepository(_repo_conn(request)))


def _repo_conn(request: Request):
    """NOTE: opening a fresh connection per authorization check (as
    opposed to reusing one across require_principal + authorize_case_access)
    is a known simplification flagged in the delivery report - see
    'known follow-ups' - production should share one connection per
    request via a proper FastAPI dependency-scoped resource, not two
    separate ones as written here."""
    from .services import db
    return db.get_connection()


def require_principal_and_case(request: Request, case_id: str, capability: str):
    """Shared helper for main.py's per-case routes: combines
    require_principal() with authz.authorize_case_access() and returns
    (principal, resolved_case_id) so the caller has the Principal on
    hand for CSRF-secret derivation without a second session lookup.
    Raises NotAuthenticatedError or CaseAccessDeniedError exactly like
    authorize_or_redirect() - main.py registers app-level exception
    handlers for both rather than catching them at every call site."""
    principal = require_principal(request)
    resolved_case_id = authz.authorize_case_access(
        principal, case_id, capability,
        repository=authz.PostgresAuthzRepository(_repo_conn(request)),
    )
    return principal, resolved_case_id


def has_capability(request: Request, principal: Principal, case_id: str, capability: str) -> bool:
    """Display-only helper - e.g. hiding a mutation <form> in a template
    for an analyst principal. NEVER a substitute for the enforcing
    authorize_case_access() call made independently at the actual
    mutation point (route layer AND service layer) - this function
    exists purely so main.py doesn't have to guess a role from the
    Principal object (which deliberately carries no role field)."""
    try:
        authz.authorize_case_access(
            principal, case_id, capability,
            repository=authz.PostgresAuthzRepository(_repo_conn(request)),
        )
        return True
    except CaseAccessDeniedError:
        return False


def list_accessible_case_ids(request: Request, principal: Principal) -> list[str]:
    """Row 19B targeted remediation (finding 2). The single authz-layer
    call site for `GET /`'s case listing (ui/main.py::index) - follows
    the exact same PostgresAuthzRepository-injection pattern as
    has_capability()/authorize_or_redirect() above, so there is one
    authorization decision (authz.list_accessible_case_ids), not a
    second one reimplemented at the route layer."""
    return authz.list_accessible_case_ids(
        principal, repository=authz.PostgresAuthzRepository(_repo_conn(request)),
    )


def csrf_secret_for_request(request: Request, principal: Principal) -> bytes:
    """Derives this request's CSRF secret fresh from the session's OWN
    token_hash (never the raw token, never a stored csrf_secret column)
    - same derivation logout() uses. Known simplification (see
    _repo_conn's docstring): opens its own connection rather than
    sharing one across the request; acceptable because this function,
    like the rest of this module, is NOT EXECUTED in this sandbox and
    is flagged for the same connection-sharing follow-up."""
    from .services import db
    with db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT token_hash FROM iam.sessions WHERE id = %s", (principal.session_id,))
            (token_hash,) = cur.fetchone()
    return session_store.derive_csrf_secret(token_hash, server_pepper=_server_pepper())


# ---------------------------------------------------------------
# GET /auth/login
# ---------------------------------------------------------------

@router.get("/auth/login")
async def login(request: Request):
    from .services import db

    provider_config = _load_provider_config()
    auth_request = oidc_client.build_authorization_url(provider_config)

    with db.transaction() as conn:
        from .services import transient_secrets as ts
        key_provider = _key_provider()
        enc = ts.encrypt_transient_secret(
            auth_request.code_verifier.encode("utf-8"),
            key_provider=key_provider,
            associated_data=oidc_client.hash_transaction_value(auth_request.state).encode("utf-8"),
        )
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO iam.oidc_login_transactions
                   (state_hash, nonce_hash, pkce_verifier_ciphertext, pkce_verifier_nonce,
                    pkce_key_id, pkce_enc_alg, required_authentication_context_id, expires_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, now() + interval '10 minutes')""",
                (
                    oidc_client.hash_transaction_value(auth_request.state),
                    oidc_client.hash_transaction_value(auth_request.nonce),
                    enc.ciphertext, enc.nonce, enc.key_id, enc.alg,
                    provider_config.required_authentication_context_id,
                ),
            )

    response = RedirectResponse(auth_request.url, status_code=302)
    response.headers.update(_no_store_headers())
    return response


# ---------------------------------------------------------------
# GET /auth/callback
# ---------------------------------------------------------------

@router.get("/auth/callback")
async def callback(request: Request):
    from .services import db, transient_secrets as ts

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return _generic_login_denied(request)

    provider_config = _load_provider_config()
    state_hash = oidc_client.hash_transaction_value(state)

    with db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, nonce_hash, pkce_verifier_ciphertext, pkce_verifier_nonce,
                          pkce_key_id, pkce_enc_alg, required_authentication_context_id
                   FROM iam.oidc_login_transactions
                   WHERE state_hash = %s AND consumed_at IS NULL AND expires_at > now()""",
                (state_hash,),
            )
            txn = cur.fetchone()
        if txn is None:
            return _generic_login_denied(request)

        (txn_id, nonce_hash, pkce_ciphertext, pkce_nonce, pkce_key_id, pkce_enc_alg,
         required_authentication_context_id) = txn

        # One-time consumption - marked BEFORE any further processing so a
        # replayed callback with the same state can never succeed twice.
        with conn.cursor() as cur:
            cur.execute("UPDATE iam.oidc_login_transactions SET consumed_at = now() WHERE id = %s", (txn_id,))

        try:
            enc = ts.EncryptedSecret(ciphertext=pkce_ciphertext, nonce=pkce_nonce, key_id=pkce_key_id, alg=pkce_enc_alg)
            code_verifier = ts.decrypt_transient_secret(
                enc, key_provider=_key_provider(), associated_data=state_hash.encode("utf-8"),
            ).decode("utf-8")
        except (ts.UnknownKeyError, ts.DecryptionFailedError):
            return _generic_login_denied(request)

        token_response = await oidc_client.exchange_code_for_tokens(
            provider_config, code=code, code_verifier=code_verifier,
        )
        try:
            claims = oidc_client.fetch_and_verify_id_token(
                token_response["id_token"], jwks_uri=provider_config.jwks_uri,
            )
            # SELF-CAUGHT BUG (found while writing test_auth_routes.py's
            # scenarios, not executed in this sandbox but traced by hand):
            # `nonce=""` here would NOT have skipped the nonce check inside
            # validate_standard_claims - it would have required the ID
            # token's real (non-empty) nonce claim to literally equal ""
            # and REJECTED EVERY real login. We only ever persist a HASH
            # of the original nonce (never the raw value - see
            # iam.oidc_login_transactions.nonce_hash), so there is no raw
            # value to hand to ExpectedClaims here at all; `nonce=None`
            # now explicitly tells validate_standard_claims to skip that
            # check (see its docstring in oidc_client.py) - the nonce
            # binding is instead verified explicitly right below, via a
            # hash comparison against the stored nonce_hash, BEFORE
            # validate_claims_for_login is ever called.
            if oidc_client.hash_transaction_value(claims.get("nonce", "")) != nonce_hash:
                return _generic_login_denied(request)

            expected = oidc_client.ExpectedClaims(
                issuer=f"https://login.microsoftonline.com/{provider_config.tenant_id}/v2.0",
                audience=provider_config.client_id,
                tenant_id=provider_config.tenant_id,
                nonce=None,
            )

            require_acrs = provider_config.mfa_tier == "entra_p1"
            identity = oidc_client.validate_claims_for_login(
                claims, expected, require_acrs=require_acrs,
                required_authentication_context_id=required_authentication_context_id if require_acrs else None,
            )
            mfa_result = mfa_adapter.evaluate_mfa_assurance_entra(
                provider_tier=provider_config.mfa_tier,
                id_token_claims=claims,
                required_authentication_context_id=required_authentication_context_id,
            )
        except (oidc_client.ClaimsValidationError, mfa_adapter.MfaAssuranceDeniedError) as exc:
            # Row 19B targeted remediation (finding 3): classify mechanically
            # by the exception's own reason_code rather than collapsing every
            # denial into "mfa_claim_absent". Never write the raw exception,
            # a token, claim content, issuer/subject, or free text into the
            # security event - only the resolved, closed reason_code.
            reason_code = exc.reason_code if exc.reason_code in _CALLBACK_CLAIMS_DENIAL_REASON_CODES else "mfa_claim_absent"
            security_events.record_login_denied_mfa_absent(conn, user_id=None, reason_code=reason_code)
            return _generic_login_denied(request)

        # NO JIT: look up an EXISTING, active identity + user. Never create.
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.id, u.disabled, u.authz_version FROM iam.external_identities ei
                   JOIN iam.users u ON u.id = ei.user_id
                   WHERE ei.issuer = %s AND ei.subject = %s""",
                (identity.issuer, identity.subject),
            )
            user_row = cur.fetchone()

        if user_row is None:
            security_events.record_login_denied_unknown_identity(conn)
            return _generic_login_denied(request)

        user_id, disabled, authz_version = user_row
        if disabled:
            security_events.record_login_denied_disabled_user(conn, user_id=user_id)
            return _generic_login_denied(request)

        raw_token, session_id = session_store.create_session(conn, user_id=user_id, role_version_at_issue=authz_version)
        security_events.record_login_success(
            conn, user_id=user_id, session_id=session_id, mfa_satisfied=mfa_result.satisfied,
            mfa_assurance_level=mfa_result.level.value, mfa_assurance_policy_version=mfa_result.policy_version,
        )

    cookie = session_store.build_session_cookie(raw_token)
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        key=cookie.name, value=cookie.value, secure=cookie.secure, httponly=cookie.httponly,
        samesite=cookie.samesite, path=cookie.path,
    )
    response.headers.update(_no_store_headers())
    return response


def _generic_login_denied(request: Request) -> HTMLResponse:
    return HTMLResponse(
        "<p>Giriş başarısız oldu. Lütfen tekrar deneyin.</p>",
        status_code=401, headers=_no_store_headers(),
    )


# ---------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------

@router.post("/auth/logout")
async def logout(request: Request):
    from .services import db, security as security_module

    try:
        principal = require_principal(request)
    except NotAuthenticatedError:
        response = RedirectResponse("/", status_code=302)
        response.headers.update(_no_store_headers())
        return response

    same_origin = security_module.is_same_origin(
        request.headers.get("origin"), request.headers.get("referer"), request.headers.get("host"),
    )
    form = await request.form()
    csrf_token = form.get("csrf_token")

    with db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT token_hash FROM iam.sessions WHERE id = %s", (principal.session_id,))
            (token_hash,) = cur.fetchone()
        server_pepper = _server_pepper()
        csrf_secret = session_store.derive_csrf_secret(token_hash, server_pepper=server_pepper)
        csrf_ok = security_module.verify_csrf_token(csrf_secret, csrf_token, "logout")

        if not same_origin or not csrf_ok:
            security_events.record_csrf_rejected(conn, user_id=principal.user_id, session_id=principal.session_id)
            return HTMLResponse("CSRF/Origin doğrulaması başarısız.", status_code=403, headers=_no_store_headers())

        with conn.cursor() as cur:
            cur.execute("UPDATE iam.sessions SET revoked_at = now() WHERE id = %s", (principal.session_id,))
        security_events.record_session_revoked(
            conn, user_id=principal.user_id, session_id=principal.session_id, actor_user_id=principal.user_id,
        )

    logout_cookie = session_store.build_logout_cookie()
    # `/login` (ui/main.py'nin bilgilendirme sayfası), `/auth/login`
    # DEĞİL - beklenmedik bir yeniden yükleme/geri tuşuyla yeni bir OIDC
    # login transaction'ının sessizce başlatılmaması için (main.py'deki
    # `_not_authenticated_handler`'ın AYNI gerekçesi).
    response = RedirectResponse("/login", status_code=302)
    response.set_cookie(
        key=logout_cookie.name, value=logout_cookie.value, secure=logout_cookie.secure,
        httponly=logout_cookie.httponly, samesite=logout_cookie.samesite, path=logout_cookie.path,
        max_age=logout_cookie.max_age,
    )
    response.headers.update(_no_store_headers())
    return response


# ---------------------------------------------------------------
# Configuration / key-provider plumbing - real, tenant-config-driven,
# never hardcoded. NOT EXECUTED in this sandbox.
# ---------------------------------------------------------------

def _load_provider_config():
    import os
    from .services.oidc_client import EntraProviderConfig

    return EntraProviderConfig(
        tenant_id=os.environ["VERGI_ENTRA_TENANT_ID"],
        client_id=os.environ["VERGI_ENTRA_CLIENT_ID"],
        authorization_endpoint=os.environ["VERGI_ENTRA_AUTH_ENDPOINT"],
        token_endpoint=os.environ["VERGI_ENTRA_TOKEN_ENDPOINT"],
        jwks_uri=os.environ["VERGI_ENTRA_JWKS_URI"],
        redirect_uri=os.environ["VERGI_ENTRA_REDIRECT_URI"],
        required_authentication_context_id=os.environ["VERGI_ENTRA_REQUIRED_AUTH_CONTEXT_ID"],
        mfa_tier=os.environ.get("VERGI_ENTRA_MFA_TIER", "entra_free"),
    )


def _key_provider():
    """Row 19D owns real KMS-backed custody/rotation behind this same
    ui.services.transient_secrets.KeyProvider interface. NOT implemented
    here - this is the documented seam, not a placeholder for the crypto
    itself (which is fully implemented in transient_secrets.py)."""
    raise NotImplementedError(
        "Row 19D must supply a real KeyProvider (KMS-backed). See the "
        "delivery report's 'known follow-ups' section."
    )


def _server_pepper() -> bytes:
    """Row 19D owns real key custody for this pepper. NOT implemented here."""
    raise NotImplementedError(
        "Row 19D must supply the real server_pepper source. See the "
        "delivery report's 'known follow-ups' section."
    )
