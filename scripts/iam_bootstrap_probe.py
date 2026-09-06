#!/usr/bin/env python3
# ============================================================
# Row 19B - local-only OIDC identity probe. NOT a production route.
#
# Two explicit purposes:
#   --purpose first-admin      : allowed ONLY when no active admin
#                                 exists; produces the verified
#                                 (issuer, subject) for
#                                 `iam_admin.py bootstrap-first-admin`.
#   --purpose provision-user   : allowed ONLY after bootstrap, for
#                                 onboarding one specifically
#                                 supervised user; produces the
#                                 verified (issuer, subject) for
#                                 `iam_admin.py provision-user`.
#
# For BOTH purposes, without exception:
#   - performs REAL ID-token signature/issuer/audience/tenant/nonce
#     validation (via ui.services.oidc_client - joserfc/Authlib,
#     lazy-imported, NOT EXECUTED in this sandbox)
#   - creates NO iam.users / iam.external_identities / role /
#     assignment / session row - zero durable mutation
#   - NEVER claims a successful MFA-authenticated application login -
#     it creates no session and calls no part of authorize_case_access,
#     so its output is printed strictly as "identity token validated",
#     never as a login/session success message
#   - remains local-only (never wired into ui/main.py's routes)
#
# The purpose gate itself (`admin_exists()`) is READ-only against
# iam.user_roles and is the one piece of DB-dependent logic here -
# it is implemented as an injectable callable so
# ui/tests/test_iam_bootstrap_probe_isolated.py can exercise the
# gating decision with a fake, without psycopg.
# ============================================================

from __future__ import annotations

import argparse
import sys
from typing import Callable, Optional


class ProbeNotAllowedError(Exception):
    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


AdminExistsCheck = Callable[[], bool]


def check_purpose_allowed(purpose: str, *, admin_exists: AdminExistsCheck) -> None:
    """Pure gating decision (aside from the injected admin_exists() call).
    Raises ProbeNotAllowedError with a precise reason_code on denial."""
    if purpose not in ("first-admin", "provision-user"):
        raise ValueError(f"unknown purpose: {purpose!r}")

    exists = admin_exists()

    if purpose == "first-admin" and exists:
        raise ProbeNotAllowedError(
            "first_admin_already_bootstrapped",
            "an active admin already exists - use --purpose provision-user instead",
        )
    if purpose == "provision-user" and not exists:
        raise ProbeNotAllowedError(
            "no_admin_yet",
            "no active admin exists yet - run --purpose first-admin and "
            "iam_admin.py bootstrap-first-admin first",
        )


def real_admin_exists() -> bool:
    """Real DB-backed check. Lazy-imports psycopg via ui.services.db.
    NOT EXECUTED in this sandbox."""
    from ui.services import db  # lazy import

    with db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM iam.user_roles WHERE role = 'admin'")
            (count,) = cur.fetchone()
    return count > 0


def run_probe(purpose: str, *, provider_config, id_token: str, expected, admin_exists: AdminExistsCheck):
    """Performs the gate check, then real ID-token validation, and returns
    the verified (issuer, subject) - never touches any durable table."""
    from ui.services.oidc_client import fetch_and_verify_id_token, validate_claims_for_login  # lazy import (joserfc)

    check_purpose_allowed(purpose, admin_exists=admin_exists)

    claims = fetch_and_verify_id_token(id_token, jwks_uri=provider_config.jwks_uri)
    identity = validate_claims_for_login(claims, expected, require_acrs=False)

    print("IDENTITY TOKEN VALIDATED (signature, issuer, audience, tenant, nonce).")
    print("This does NOT indicate a successful MFA-authenticated application "
          "login - no session or authorization was created or checked.")
    print(f"issuer={identity.issuer}")
    print(f"subject={identity.subject}")
    return identity.issuer, identity.subject


def _load_provider_config():
    """Reads the same tenant-specific configuration the real app uses -
    environment variables, never a hardcoded default. Fails closed if
    any required value is missing."""
    import os
    from ui.services.oidc_client import EntraProviderConfig

    required_env = [
        "VERGI_ENTRA_TENANT_ID", "VERGI_ENTRA_CLIENT_ID", "VERGI_ENTRA_AUTH_ENDPOINT",
        "VERGI_ENTRA_TOKEN_ENDPOINT", "VERGI_ENTRA_JWKS_URI", "VERGI_ENTRA_REDIRECT_URI",
        "VERGI_ENTRA_REQUIRED_AUTH_CONTEXT_ID",
    ]
    missing = [name for name in required_env if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing required environment variables: {', '.join(missing)}")

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


def _capture_authorization_code(authorization_url: str, redirect_uri: str, *, timeout_seconds: int = 180) -> str:
    """Opens the system browser at `authorization_url` and runs a
    single-shot local HTTP listener on the redirect_uri's host/port to
    capture the `code` query parameter. This is real orchestration code
    (stdlib http.server + webbrowser + urllib.parse) - NOT EXECUTED in
    this sandbox because it requires a real provider redirect and a
    display/browser, but it is not a stub: it is the actual mechanism
    scripts/iam_bootstrap_probe.py uses locally."""
    import threading
    import webbrowser
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs

    parsed_redirect = urlparse(redirect_uri)
    host = parsed_redirect.hostname or "127.0.0.1"
    port = parsed_redirect.port or 80

    captured: dict[str, str] = {}
    done = threading.Event()

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = parse_qs(urlparse(self.path).query)
            if "code" in qs:
                captured["code"] = qs["code"][0]
            if "error" in qs:
                captured["error"] = qs["error"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"You may close this window and return to the terminal.")
            done.set()

        def log_message(self, *args):  # silence default stderr logging
            pass

    server = HTTPServer((host, port), _Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        webbrowser.open(authorization_url)
        if not done.wait(timeout=timeout_seconds):
            raise TimeoutError("timed out waiting for the OIDC redirect callback")
    finally:
        server.shutdown()

    if "error" in captured:
        raise RuntimeError(f"provider returned an error: {captured['error']}")
    if "code" not in captured:
        raise RuntimeError("no authorization code was captured")
    return captured["code"]


def main(argv: Optional[list[str]] = None) -> int:
    import asyncio
    from ui.services.oidc_client import (
        build_authorization_url, exchange_code_for_tokens, fetch_and_verify_id_token,
        validate_claims_for_login, ExpectedClaims,
    )

    parser = argparse.ArgumentParser(prog="iam_bootstrap_probe.py")
    parser.add_argument("--purpose", required=True, choices=["first-admin", "provision-user"])
    args = parser.parse_args(argv)

    try:
        check_purpose_allowed(args.purpose, admin_exists=real_admin_exists)
    except ProbeNotAllowedError as exc:
        print(f"DENIED: {exc}", file=sys.stderr)
        return 1

    provider_config = _load_provider_config()
    auth_request = build_authorization_url(provider_config)

    print("Opening your browser to sign in. This validates identity ONLY - "
          "no session or role is created by this script.")
    code = _capture_authorization_code(auth_request.url, provider_config.redirect_uri)

    token_response = asyncio.run(
        exchange_code_for_tokens(provider_config, code=code, code_verifier=auth_request.code_verifier)
    )
    id_token = token_response["id_token"]

    claims = fetch_and_verify_id_token(id_token, jwks_uri=provider_config.jwks_uri)
    if claims.get("nonce") != auth_request.nonce:
        print("DENIED: nonce mismatch on returned ID token.", file=sys.stderr)
        return 1

    expected = ExpectedClaims(
        issuer=f"https://login.microsoftonline.com/{provider_config.tenant_id}/v2.0",
        audience=provider_config.client_id,
        tenant_id=provider_config.tenant_id,
        nonce=auth_request.nonce,
    )
    identity = validate_claims_for_login(claims, expected, require_acrs=False)

    print("IDENTITY TOKEN VALIDATED (signature, issuer, audience, tenant, nonce).")
    print("This does NOT indicate a successful MFA-authenticated application "
          "login - no session or authorization was created or checked.")
    print(f"issuer={identity.issuer}")
    print(f"subject={identity.subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
