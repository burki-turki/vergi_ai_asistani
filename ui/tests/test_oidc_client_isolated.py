# ============================================================
# Row 19B - isolated tests for ui/services/oidc_client.py and
# ui/services/transient_secrets.py (PKCE verifier storage lives in
# the OIDC transaction lifecycle, so its tests live here).
#
# The target UI runtime must carry every auth dependency at its exact
# ui/requirements.txt pin. Authorization and token requests execute against
# an httpx MockTransport; real sockets and .env access are forbidden.
#
# Run: python -m ui.tests.test_oidc_client_isolated
# ============================================================

import asyncio
import importlib
import importlib.metadata
import json
import os
import socket
import sys
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_ENV_OPENS = []
_EXTERNAL_SOCKET_EVENTS = []


def _audit(event, args):
    if event == "open" and args:
        try:
            path = os.fspath(args[0])
        except TypeError:
            return
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if Path(path).name == ".env":
            _ENV_OPENS.append(path)
    elif event == "socket.getaddrinfo":
        _EXTERNAL_SOCKET_EVENTS.append((event, args))
    elif event == "socket.connect" and len(args) > 1:
        address = args[1]
        if not (
            isinstance(address, tuple)
            and address
            and address[0] in {"127.0.0.1", "::1"}
        ):
            _EXTERNAL_SOCKET_EVENTS.append((event, args))


sys.addaudithook(_audit)

from ui.services import oidc_client as oc          # noqa: E402
from ui.services import transient_secrets as ts    # noqa: E402

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


# ----------------------------------------------------------------
# 1) PKCE / state / nonce
# ----------------------------------------------------------------
v1, c1 = oc.generate_pkce_pair()
v2, c2 = oc.generate_pkce_pair()
check("pkce verifier/challenge are non-empty", bool(v1) and bool(c1))
check("pkce pairs are unique across calls", v1 != v2 and c1 != c2)
check("pkce challenge is NOT the verifier itself", c1 != v1)

import hashlib, base64
expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(v1.encode()).digest()).rstrip(b"=").decode()
check("pkce challenge is exactly S256(verifier)", c1 == expected_challenge)

s1, s2 = oc.generate_state(), oc.generate_state()
check("state values are unique across calls", s1 != s2)
n1, n2 = oc.generate_nonce(), oc.generate_nonce()
check("nonce values are unique across calls", n1 != n2)

h1 = oc.hash_transaction_value("abc")
h2 = oc.hash_transaction_value("abc")
h3 = oc.hash_transaction_value("abd")
check("hash_transaction_value is deterministic", h1 == h2)
check("hash_transaction_value differs on different input", h1 != h3)
check("hash_transaction_value never returns the raw value", h1 != "abc")

# ----------------------------------------------------------------
# 2) EntraProviderConfig / claims request construction
# ----------------------------------------------------------------
cfg = oc.EntraProviderConfig(
    tenant_id="11111111-1111-1111-1111-111111111111",
    client_id="client-abc",
    authorization_endpoint="https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
    token_endpoint="https://login.microsoftonline.com/tenant/oauth2/v2.0/token",
    jwks_uri="https://login.microsoftonline.com/tenant/discovery/v2.0/keys",
    redirect_uri="https://app.example/auth/callback",
    required_authentication_context_id="c1-lawyer-mfa",
    mfa_tier="entra_p1",
)

claims_req = oc.build_claims_request(cfg)
check(
    "claims request targets the configured context id (not a hardcoded value)",
    claims_req == {"id_token": {"acrs": {"essential": True, "value": "c1-lawyer-mfa"}}},
)

expect_raises(
    ValueError,
    lambda: oc.EntraProviderConfig(
        tenant_id="t", client_id="c", authorization_endpoint="a", token_endpoint="b",
        jwks_uri="j", redirect_uri="r", required_authentication_context_id="", mfa_tier="entra_p1",
    ),
    "empty required_authentication_context_id is rejected at construction",
)

# ----------------------------------------------------------------
# 3) Standard claims validation (iss/aud/tid/nonce)
# ----------------------------------------------------------------
expected = oc.ExpectedClaims(
    issuer="https://login.microsoftonline.com/tenant/v2.0",
    audience="client-abc",
    tenant_id="11111111-1111-1111-1111-111111111111",
    nonce="nonce-xyz",
)

good_claims = {
    "iss": expected.issuer, "aud": expected.audience, "tid": expected.tenant_id,
    "nonce": expected.nonce, "sub": "user-subject-1",
}
oc.validate_standard_claims(good_claims, expected)
check("matching standard claims pass validation", True)

for field, bad_value, label in [
    ("iss", "https://evil.example/v2.0", "wrong issuer rejected"),
    ("aud", "someone-elses-client", "wrong audience rejected"),
    ("tid", "22222222-2222-2222-2222-222222222222", "wrong tenant (tid) rejected"),
    ("nonce", "replayed-or-wrong-nonce", "wrong nonce rejected"),
]:
    bad = dict(good_claims)
    bad[field] = bad_value
    expect_raises(oc.ClaimsValidationError, lambda b=bad: oc.validate_standard_claims(b, expected), label)

aud_array_claims = dict(good_claims)
aud_array_claims["aud"] = ["someone-else", "client-abc"]
expect_raises(
    oc.ClaimsValidationError,
    lambda: oc.validate_standard_claims(aud_array_claims, expected),
    "Row 19B targeted remediation (finding 4): multi-audience aud array WITHOUT azp is now rejected, "
    "not silently accepted (previous behavior - regression guard for the fix)",
)

# ----------------------------------------------------------------
# 3b) Row 19B targeted remediation (finding 4) - multi-audience `azp`.
# When `aud` is an array containing the expected audience, `azp` must
# be present, a string, and equal (exact, case-sensitive) to the
# expected audience. Single-string `aud` behavior (checked just above,
# in section 3) is unchanged and requires no azp at all.
# ----------------------------------------------------------------

aud_array_with_correct_azp = dict(good_claims)
aud_array_with_correct_azp["aud"] = ["someone-else", "client-abc"]
aud_array_with_correct_azp["azp"] = "client-abc"
oc.validate_standard_claims(aud_array_with_correct_azp, expected)
check("multi-audience aud array WITH correct azp (exact match) passes", True)

aud_array_missing_azp = dict(good_claims)
aud_array_missing_azp["aud"] = ["someone-else", "client-abc"]
expect_raises(
    oc.ClaimsValidationError,
    lambda: oc.validate_standard_claims(aud_array_missing_azp, expected),
    "multi-audience aud array with azp entirely ABSENT is rejected (fails closed)",
)

aud_array_wrong_azp = dict(good_claims)
aud_array_wrong_azp["aud"] = ["someone-else", "client-abc"]
aud_array_wrong_azp["azp"] = "someone-else"
expect_raises(
    oc.ClaimsValidationError,
    lambda: oc.validate_standard_claims(aud_array_wrong_azp, expected),
    "multi-audience aud array with azp naming a DIFFERENT client is rejected",
)

aud_array_case_mismatched_azp = dict(good_claims)
aud_array_case_mismatched_azp["aud"] = ["someone-else", "client-abc"]
aud_array_case_mismatched_azp["azp"] = "Client-ABC"
expect_raises(
    oc.ClaimsValidationError,
    lambda: oc.validate_standard_claims(aud_array_case_mismatched_azp, expected),
    "azp match is case-sensitive - a differently-cased near-match is rejected, not coerced",
)

aud_array_nonstring_azp = dict(good_claims)
aud_array_nonstring_azp["aud"] = ["someone-else", "client-abc"]
aud_array_nonstring_azp["azp"] = ["client-abc"]
expect_raises(
    oc.ClaimsValidationError,
    lambda: oc.validate_standard_claims(aud_array_nonstring_azp, expected),
    "azp present but wrong type (array instead of string) is rejected, not coerced/stringified",
)

aud_array_empty_string_azp = dict(good_claims)
aud_array_empty_string_azp["aud"] = ["someone-else", "client-abc"]
aud_array_empty_string_azp["azp"] = ""
expect_raises(
    oc.ClaimsValidationError,
    lambda: oc.validate_standard_claims(aud_array_empty_string_azp, expected),
    "azp present as an empty string is rejected (does not equal the expected audience)",
)

single_string_aud_no_azp = dict(good_claims)  # aud is a plain string (no array) - unchanged from section 3
check(
    "single-string aud claims carry no azp key in this test's fixture (sanity check of the fixture itself)",
    "azp" not in single_string_aud_no_azp,
)
oc.validate_standard_claims(single_string_aud_no_azp, expected)
check("single-string aud (no azp at all) still passes unchanged - azp is only required for the multi-audience case", True)

single_string_aud_with_azp_present_but_irrelevant = dict(good_claims)
single_string_aud_with_azp_present_but_irrelevant["azp"] = "totally-different-value-that-would-fail-if-checked"
oc.validate_standard_claims(single_string_aud_with_azp_present_but_irrelevant, expected)
check(
    "single-string aud still passes even if azp is present with an unrelated value - "
    "azp is never consulted outside the multi-audience branch",
    True,
)

# ----------------------------------------------------------------
# 4) acrs array/membership validation - the corrected v2 contract
# ----------------------------------------------------------------
required_id = "c1-lawyer-mfa"

ok_claims = {"acrs": ["c2", required_id]}
result = oc.validate_acrs_claim(ok_claims, required_id)
check("acrs positive: required id present among extra well-formed ids", result == ["c2", required_id])

expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({}, required_id),
    "acrs absent is rejected (MFA_CLAIM_ABSENT)",
)
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({"acrs": required_id}, required_id),
    "acrs as bare scalar string is rejected",
)
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({"acrs": []}, required_id),
    "acrs as empty array is rejected",
)
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({"acrs": [1, required_id]}, required_id),
    "acrs containing a non-string element is rejected",
)
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({"acrs": [required_id, ""]}, required_id),
    "acrs containing an empty string element is rejected",
)
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({"acrs": [required_id, required_id]}, required_id),
    "acrs containing duplicate values is rejected",
)
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({"acrs": ["c2", "c3"]}, required_id),
    "acrs missing the required id (unknown/mismatching context) is rejected",
)
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({"acrs": [required_id.upper()]}, required_id),
    "acrs membership check is case-sensitive (near-match case differs) rejected",
)
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({"acrs": [required_id + " "]}, required_id),
    "acrs membership check rejects trailing-whitespace near-match",
)
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_acrs_claim({"acrs": [required_id + "-extra"]}, required_id),
    "acrs membership check rejects superstring near-match",
)

# ----------------------------------------------------------------
# 5) validate_claims_for_login composition, incl. Entra Free vs P1 shape
# ----------------------------------------------------------------
full_claims_p1 = dict(good_claims)
full_claims_p1["acrs"] = ["c2", required_id]
identity = oc.validate_claims_for_login(
    full_claims_p1, expected, require_acrs=True, required_authentication_context_id=required_id,
)
check("validate_claims_for_login (P1 path) returns validated acrs", identity.acrs == ["c2", required_id])
check("validate_claims_for_login extracts subject", identity.subject == "user-subject-1")

identity_free = oc.validate_claims_for_login(good_claims, expected, require_acrs=False)
check("validate_claims_for_login (Free path) does not require/return acrs", identity_free.acrs is None)

expect_raises(
    ValueError,
    lambda: oc.validate_claims_for_login(good_claims, expected, require_acrs=True, required_authentication_context_id=None),
    "require_acrs=True without a configured context id is a programming error, fails closed",
)

missing_sub = dict(good_claims)
del missing_sub["sub"]
expect_raises(
    oc.ClaimsValidationError, lambda: oc.validate_claims_for_login(missing_sub, expected, require_acrs=False),
    "missing sub claim is rejected",
)

# ----------------------------------------------------------------
# 6) access-token substitution is structurally impossible here:
#    validate_acrs_claim only ever takes a claims dict the caller
#    must have sourced from the validated ID token - prove that
#    passing an access-token-shaped claims dict (no acrs at all,
#    since access tokens are opaque to this app) still fails closed
#    exactly like any other missing-claim case, never silently
#    substituting.
# ----------------------------------------------------------------
access_token_shaped_claims = {"aud": "https://graph.microsoft.com", "scp": "User.Read"}
expect_raises(
    oc.ClaimsValidationError,
    lambda: oc.validate_acrs_claim(access_token_shaped_claims, required_id),
    "access-token-shaped claims (no acrs) fail closed, never substituted",
)

# ----------------------------------------------------------------
# 7) transient_secrets - PKCE verifier envelope round trip
# ----------------------------------------------------------------
kp = ts.InMemoryKeyProvider()
kp.add_key("pkce-k1", b"1" * 32)
enc = ts.encrypt_transient_secret(v1.encode(), key_provider=kp, associated_data=h1.encode())
dec = ts.decrypt_transient_secret(enc, key_provider=kp, associated_data=h1.encode())
check("PKCE verifier AEAD round-trip recovers the exact verifier", dec.decode() == v1)

# ----------------------------------------------------------------
# 8) Exact dependency pins and real Authlib request construction over a
#    mocked transport. A missing dependency is a counted failure, never skip.
# ----------------------------------------------------------------
required_dependencies = {
    "authlib": ("Authlib", "1.8.0"),
    "joserfc": ("joserfc", "1.7.5"),
    "psycopg": ("psycopg", "3.3.5"),
    "cryptography": ("cryptography", "50.0.1"),
}
dependencies_ready = True
for module_name, (distribution_name, expected_version) in required_dependencies.items():
    try:
        importlib.import_module(module_name)
        actual_version = importlib.metadata.version(distribution_name)
    except Exception as error:
        dependencies_ready = False
        check(
            f"required dependency {module_name} imports at pin {expected_version}",
            False,
            f"{type(error).__name__}: {error}",
        )
    else:
        matches = actual_version == expected_version
        dependencies_ready = dependencies_ready and matches
        check(
            f"required dependency {module_name} imports at pin {expected_version}",
            matches,
            f"actual={actual_version}",
        )

if dependencies_ready:
    import httpx
    import authlib.integrations.httpx_client as authlib_httpx

    transport_requests = []

    def forbidden_sync_request(request):
        transport_requests.append(request)
        raise AssertionError("authorization URL construction attempted network I/O")

    original_oauth2_client = authlib_httpx.OAuth2Client

    def oauth2_client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(forbidden_sync_request)
        return original_oauth2_client(*args, **kwargs)

    with mock.patch.object(authlib_httpx, "OAuth2Client", side_effect=oauth2_client_factory), \
         mock.patch.object(socket, "create_connection", side_effect=AssertionError("real socket forbidden")), \
         mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")):
        authorization_request = oc.build_authorization_url(cfg)

    query = parse_qs(urlparse(authorization_request.url).query)
    check("build_authorization_url uses PKCE S256", query.get("code_challenge_method") == ["S256"])
    expected_live_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(authorization_request.code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    check("authorization URL carries the S256 challenge for its returned verifier", query.get("code_challenge") == [expected_live_challenge])
    check("authorization URL carries non-empty state", query.get("state") == [authorization_request.state] and bool(authorization_request.state))
    check("authorization URL carries non-empty nonce", query.get("nonce") == [authorization_request.nonce] and bool(authorization_request.nonce))
    claims_from_url = json.loads(query["claims"][0])
    check(
        "authorization claims requests essential acrs with the expected value",
        claims_from_url == {"id_token": {"acrs": {"essential": True, "value": cfg.required_authentication_context_id}}},
    )
    check("authorization URL construction uses zero transport calls", transport_requests == [])

    token_requests = []

    async def token_handler(request):
        token_requests.append(request)
        return httpx.Response(
            200,
            json={"access_token": "mock-access", "token_type": "Bearer", "id_token": "mock-id"},
            request=request,
        )

    original_async_client = authlib_httpx.AsyncOAuth2Client

    def async_client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(token_handler)
        return original_async_client(*args, **kwargs)

    with mock.patch.object(authlib_httpx, "AsyncOAuth2Client", side_effect=async_client_factory), \
         mock.patch.object(socket, "create_connection", side_effect=AssertionError("real socket forbidden")), \
         mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS forbidden")):
        token_result = asyncio.run(
            oc.exchange_code_for_tokens(cfg, code="mock-code", code_verifier=authorization_request.code_verifier)
        )

    check("token exchange completes through the mocked transport", token_result.get("access_token") == "mock-access" and len(token_requests) == 1)
    token_body = parse_qs(token_requests[0].content.decode("ascii"), keep_blank_values=True)
    check("token exchange sends no client_secret", "client_secret" not in token_body)
    check("token exchange sends no client_assertion", "client_assertion" not in token_body and "client_assertion_type" not in token_body)
    check("token exchange sends client_id in the request body", token_body.get("client_id") == [cfg.client_id])
    check("token exchange sends the exact PKCE verifier", token_body.get("code_verifier") == [authorization_request.code_verifier])

check("OIDC isolated test opened no .env file", _ENV_OPENS == [], repr(_ENV_OPENS))
check(
    "OIDC isolated test made no external socket or DNS call",
    _EXTERNAL_SOCKET_EVENTS == [],
    repr(_EXTERNAL_SOCKET_EVENTS),
)

print(f"--- test_oidc_client_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
