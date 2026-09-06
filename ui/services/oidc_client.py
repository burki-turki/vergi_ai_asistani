# ============================================================
# Row 19B - OIDC client (Microsoft Entra ID Workforce as the first
# real provider; core stays provider-neutral).
#
# One authoritative validation path:
#   - Authlib (authlib.integrations.httpx_client.AsyncOAuth2Client)
#     builds the Authorization Code + PKCE request and performs the
#     token exchange. Used directly, NOT its Starlette-session
#     convenience wrapper - OIDC transaction state lives server-side
#     in iam.oidc_login_transactions, never in a client-side session
#     cookie.
#   - joserfc is the SOLE validator of signature / algorithm-allowlist
#     / issuer / audience / azp / nonce / time-claims against JWKS.
#     Authlib's own authlib.jose is never used, to avoid overlapping
#     validators.
#
# This module is split deliberately:
#   - PURE functions (PKCE/state/nonce generation, the `claims`
#     request payload, and post-decode claims-shape validation
#     including the acrs array/membership rule) import NOTHING but
#     the stdlib and are exercised directly by
#     ui/tests/test_oidc_client_isolated.py in every environment,
#     including this cloud sandbox.
#   - I/O functions (`build_authorization_url`'s Authlib call,
#     `fetch_and_verify_id_token`'s joserfc call) lazy-import Authlib
#     / joserfc so importing this module never requires them; only
#     CALLING those two functions does. Neither is executed in this
#     sandbox (Authlib/joserfc are not installable here - see the
#     delivery report) - production behavior is implemented in full,
#     not stubbed.
# ============================================================

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------
# PKCE / state / nonce - pure stdlib (secrets, hashlib, base64).
# ---------------------------------------------------------------

def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) per RFC 7636 S256."""
    code_verifier = _b64url_no_pad(secrets.token_bytes(32))
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = _b64url_no_pad(digest)
    return code_verifier, code_challenge


def generate_state() -> str:
    return _b64url_no_pad(secrets.token_bytes(32))


def generate_nonce() -> str:
    return _b64url_no_pad(secrets.token_bytes(32))


def hash_transaction_value(value: str) -> str:
    """One-way hash for state/nonce as stored in iam.oidc_login_transactions -
    the raw values are never persisted, only their SHA-256 hash for
    later exact comparison at callback time."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------
# Provider configuration and the `claims` request payload.
# ---------------------------------------------------------------

@dataclass(frozen=True)
class EntraProviderConfig:
    tenant_id: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    redirect_uri: str
    required_authentication_context_id: str  # tenant-specific, never hardcoded
    mfa_tier: str  # "entra_free" | "entra_p1" - drives mfa_adapter's two-tier logic

    def __post_init__(self) -> None:
        if not self.required_authentication_context_id:
            raise ValueError(
                "required_authentication_context_id must come from validated "
                "tenant-specific configuration; it must never be empty or a "
                "hardcoded universal placeholder"
            )


def build_claims_request(provider_config: EntraProviderConfig) -> dict[str, Any]:
    """The OIDC `claims` request parameter (OIDC Core S5.5.1). The scalar
    `value` targets one specific Authentication Context; per the OIDC Core
    spec, when the returned claim is a JSON array, an essential-claim
    `value` request is satisfied if the array CONTAINS that value - this
    is why the request stays scalar even though the response is validated
    as an array below."""
    return {
        "id_token": {
            "acrs": {
                "essential": True,
                "value": provider_config.required_authentication_context_id,
            }
        }
    }


@dataclass(frozen=True)
class AuthorizationRequest:
    url: str
    state: str
    nonce: str
    code_verifier: str


def build_authorization_url(
    provider_config: EntraProviderConfig,
    *,
    scope: str = "openid profile",
) -> AuthorizationRequest:
    """Builds the real Authorization Code + PKCE redirect URL via Authlib.
    Lazy-imports Authlib so this module remains importable without it.
    NOT EXECUTED in this sandbox (Authlib is not installed) - the call
    site and parameter construction are real, non-placeholder code."""
    from authlib.integrations.httpx_client import OAuth2Client  # lazy import

    state = generate_state()
    nonce = generate_nonce()
    code_verifier, code_challenge = generate_pkce_pair()

    client = OAuth2Client(
        client_id=provider_config.client_id,
        redirect_uri=provider_config.redirect_uri,
        code_challenge_method="S256",
    )
    import json as _json

    url, _state = client.create_authorization_url(
        provider_config.authorization_endpoint,
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        scope=scope,
        claims=_json.dumps(build_claims_request(provider_config)),
    )
    return AuthorizationRequest(url=url, state=state, nonce=nonce, code_verifier=code_verifier)


# ---------------------------------------------------------------
# Post-decode claims validation - PURE (operates on an already
# signature-verified claims dict; does no I/O and no crypto itself).
# This is what ui/tests/test_oidc_client_isolated.py exercises for
# real in every environment, independent of joserfc's availability.
# ---------------------------------------------------------------

class ClaimsValidationError(Exception):
    """Base for every claims-shape rejection. `reason_code` matches the
    iam.security_events.reason_code enum so callers can log precisely."""

    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


@dataclass(frozen=True)
class ExpectedClaims:
    issuer: str
    audience: str
    tenant_id: str
    # `None` means "skip the nonce check in this function" - used by
    # callers (ui/auth_routes.py) that only ever persisted a HASH of the
    # original nonce (never the raw value, by design - see
    # iam.oidc_login_transactions.nonce_hash) and therefore have no raw
    # value to pass here at all; those callers verify the nonce binding
    # themselves via an explicit hash_transaction_value(...) comparison
    # BEFORE calling validate_claims_for_login. A caller that DOES hold
    # the raw expected nonce (e.g. a test, or a future in-memory-only
    # flow) passes it as a real string for an exact-match check.
    nonce: str | None


def validate_standard_claims(claims: dict[str, Any], expected: ExpectedClaims) -> None:
    """iss / aud / tid / nonce exact-match checks. Signature, alg-allowlist
    and exp/nbf are joserfc's job before this function ever sees `claims` -
    this function assumes the token's cryptographic validity is already
    established and only checks the claim VALUES. `expected.nonce is None`
    skips the nonce check entirely (see the field's docstring above) -
    it does NOT mean "nonce must be empty/absent"."""
    if claims.get("iss") != expected.issuer:
        raise ClaimsValidationError("unknown_identity", "issuer mismatch")
    aud = claims.get("aud")
    if aud == expected.audience:
        pass  # single-audience case - unchanged behavior, no azp requirement
    elif isinstance(aud, list) and expected.audience in aud:
        # Row 19B targeted remediation (finding 4): a multi-audience `aud`
        # array is only acceptable if this token was actually AUTHORIZED
        # FOR this client - `azp` (authorized party) must be present, a
        # string, and equal (exact, case-sensitive) to our own client/
        # audience id. Without this check, a token issued primarily for a
        # different client that merely lists our client_id as a secondary
        # audience would be accepted, which `aud`-array membership alone
        # does not rule out. Missing, wrong-type, or mismatched `azp`
        # fails closed (rejects the login) - it never falls back to
        # treating the token as acceptable.
        azp = claims.get("azp")
        if not isinstance(azp, str) or azp != expected.audience:
            raise ClaimsValidationError("unknown_identity", "multi-audience token missing/mismatched azp")
    else:
        raise ClaimsValidationError("unknown_identity", "audience mismatch")
    if claims.get("tid") != expected.tenant_id:
        raise ClaimsValidationError("unknown_identity", "tenant (tid) mismatch")
    if expected.nonce is not None and claims.get("nonce") != expected.nonce:
        raise ClaimsValidationError("unknown_identity", "nonce mismatch")


def validate_acrs_claim(claims: dict[str, Any], required_authentication_context_id: str) -> list[str]:
    """Validates `acrs` per the corrected Row 19B contract:
      - must be present
      - must be a JSON array (never a scalar)
      - must be non-empty
      - every element must be a non-empty string
      - no duplicate elements
      - `required_authentication_context_id` must be an EXACT,
        case-sensitive MEMBER of the array (not equal to the whole array)
      - additional well-formed context IDs in the array do NOT cause
        rejection
    Returns the validated list on success; raises ClaimsValidationError
    (reason_code drawn from the iam.security_events enum) on any failure.
    Access-token-sourced `acrs` must NEVER be passed to this function -
    callers must only pass claims decoded from the validated ID token.
    """
    if "acrs" not in claims:
        raise ClaimsValidationError("mfa_claim_absent", "acrs claim missing from ID token")

    acrs = claims["acrs"]

    if isinstance(acrs, str):
        raise ClaimsValidationError("mfa_claim_malformed", "acrs is a scalar string, not an array")
    if not isinstance(acrs, list):
        raise ClaimsValidationError("mfa_claim_malformed", f"acrs has unexpected type {type(acrs).__name__}")
    if len(acrs) == 0:
        raise ClaimsValidationError("mfa_claim_malformed", "acrs is an empty array")
    for element in acrs:
        if not isinstance(element, str):
            raise ClaimsValidationError("mfa_claim_malformed", f"acrs contains a non-string element: {element!r}")
        if element == "":
            raise ClaimsValidationError("mfa_claim_malformed", "acrs contains an empty string element")
    if len(set(acrs)) != len(acrs):
        raise ClaimsValidationError("mfa_claim_malformed", "acrs contains duplicate values")

    if required_authentication_context_id not in acrs:
        raise ClaimsValidationError(
            "mfa_claim_mismatch",
            f"required context {required_authentication_context_id!r} not present in acrs {acrs!r}",
        )

    return acrs


@dataclass(frozen=True)
class ValidatedIdentity:
    issuer: str
    subject: str
    acrs: list[str] | None  # None when the provider tier never returns acrs (Entra Free)


def validate_claims_for_login(
    claims: dict[str, Any],
    expected: ExpectedClaims,
    *,
    require_acrs: bool,
    required_authentication_context_id: str | None = None,
) -> ValidatedIdentity:
    """Composes the standard-claims check with the optional acrs check.
    `require_acrs=False` is the Entra Free path (mfa_adapter always fails
    that tier closed regardless of what this returns - see mfa_adapter.py);
    `require_acrs=True` is the Entra P1 path."""
    validate_standard_claims(claims, expected)

    subject = claims.get("sub")
    if not subject or not isinstance(subject, str):
        raise ClaimsValidationError("unknown_identity", "missing or invalid sub claim")

    acrs: list[str] | None = None
    if require_acrs:
        if not required_authentication_context_id:
            raise ValueError("required_authentication_context_id must be provided when require_acrs=True")
        acrs = validate_acrs_claim(claims, required_authentication_context_id)

    return ValidatedIdentity(issuer=expected.issuer, subject=subject, acrs=acrs)


# ---------------------------------------------------------------
# Real signature verification + JWKS retrieval - joserfc. Lazy-import;
# NOT EXECUTED in this sandbox (joserfc is not installed here).
# ---------------------------------------------------------------

def fetch_and_verify_id_token(
    id_token: str,
    *,
    jwks_uri: str,
    allowed_algorithms: tuple[str, ...] = ("RS256",),
) -> dict[str, Any]:
    """Fetches the provider's JWKS and verifies `id_token`'s signature,
    algorithm (against `allowed_algorithms` - no `alg: none`, no
    algorithm confusion), and standard time claims (exp/nbf) via joserfc.
    Returns the decoded claims dict on success (still needs
    validate_claims_for_login() applied by the caller for value checks).
    Raises on any verification failure - never returns unverified claims.
    """
    from joserfc import jwt as joserfc_jwt          # lazy import
    from joserfc.jwk import KeySet                  # lazy import
    import httpx

    resp = httpx.get(jwks_uri, timeout=10.0)
    resp.raise_for_status()
    key_set = KeySet.import_key_set(resp.json())

    token = joserfc_jwt.decode(id_token, key_set, algorithms=list(allowed_algorithms))
    joserfc_jwt.JWTClaimsRegistry(
        exp={"essential": True},
        nbf={"essential": False},
    ).validate(token.claims)
    return token.claims


async def exchange_code_for_tokens(
    provider_config: EntraProviderConfig,
    *,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Performs the real Authorization Code + PKCE token exchange via
    Authlib's AsyncOAuth2Client (used directly, not the Starlette-session
    wrapper). Lazy-import; NOT EXECUTED in this sandbox."""
    from authlib.integrations.httpx_client import AsyncOAuth2Client  # lazy import

    async with AsyncOAuth2Client(
        client_id=provider_config.client_id,
        redirect_uri=provider_config.redirect_uri,
    ) as client:
        token = await client.fetch_token(
            provider_config.token_endpoint,
            code=code,
            code_verifier=code_verifier,
        )
    return token
