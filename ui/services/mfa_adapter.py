# ============================================================
# Row 19B - MFA assurance adapter (two-tier: Entra ID Free vs P1).
#
# Pure decision logic - takes an already claims-validated identity
# (from ui.services.oidc_client.validate_claims_for_login), never raw
# tokens. No network, no DB. Fully executed by
# ui/tests/test_mfa_adapter_isolated.py in every environment.
#
# Contract recap:
#   - Entra ID Free: Conditional Access Authentication Context is not
#     available at this tier. This function ALWAYS fails closed here
#     (MFA_CLAIM_ABSENT), even if a caller mistakenly passed a claims
#     dict containing an `acrs` array - Free-tier trust is never
#     derived from claim content, only from the configured tier.
#   - Entra ID P1: assurance is satisfied only when the ID token's
#     validated `acrs` array contains the tenant-configured
#     `required_authentication_context_id` (see oidc_client.
#     validate_acrs_claim for the exact array-shape rules).
#   - This module does NOT and CANNOT verify that a Conditional Access
#     policy actually binds that Authentication Context to an MFA
#     grant control - that is exclusively a Row 19D deployment gate
#     performed via Microsoft Graph. Nothing here claims otherwise.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ui.services.oidc_client import ClaimsValidationError, validate_acrs_claim


class MfaAssuranceLevel(str, Enum):
    NONE = "none"
    ENTRA_FREE_UNAVAILABLE = "entra_free_unavailable"
    ENTRA_P1_CONTEXT_SATISFIED = "entra_p1_context_satisfied"


class MfaAssuranceDeniedError(Exception):
    def __init__(self, reason_code: str, detail: str = ""):
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


@dataclass(frozen=True)
class MfaAssuranceResult:
    satisfied: bool
    level: MfaAssuranceLevel
    policy_version: str


# Bump this string whenever the assurance RULE (not the tenant config)
# changes, so historical iam.security_events rows remain interpretable.
_POLICY_VERSION = "row19b-v1"


def evaluate_mfa_assurance_entra(
    *,
    provider_tier: str,  # "entra_free" | "entra_p1"
    id_token_claims: dict,
    required_authentication_context_id: str,
) -> MfaAssuranceResult:
    """Raises MfaAssuranceDeniedError (fail closed) unless P1 + a valid,
    exact acrs-array membership match. `id_token_claims` MUST be sourced
    from a signature-validated ID token - never from an access token."""
    if provider_tier == "entra_free":
        raise MfaAssuranceDeniedError(
            "mfa_claim_absent",
            "Entra ID Free has no Conditional Access Authentication Context; "
            "MFA assurance always fails closed at this tier",
        )

    if provider_tier != "entra_p1":
        raise ValueError(f"unknown provider_tier: {provider_tier!r}")

    try:
        validate_acrs_claim(id_token_claims, required_authentication_context_id)
    except ClaimsValidationError as exc:
        raise MfaAssuranceDeniedError(exc.reason_code, str(exc)) from exc

    return MfaAssuranceResult(
        satisfied=True,
        level=MfaAssuranceLevel.ENTRA_P1_CONTEXT_SATISFIED,
        policy_version=_POLICY_VERSION,
    )
