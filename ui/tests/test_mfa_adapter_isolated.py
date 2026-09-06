# ============================================================
# Row 19B - isolated tests for ui/services/mfa_adapter.py.
# Pure logic, no external package required. Runs in every
# environment, including this cloud sandbox.
#
# Run: python -m ui.tests.test_mfa_adapter_isolated
# ============================================================

import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import mfa_adapter as mfa   # noqa: E402

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


REQUIRED_ID = "c1-lawyer-mfa"

# Entra Free: ALWAYS fails closed, even if (mistakenly) handed a
# claims dict that already contains a matching acrs array.
expect_raises(
    mfa.MfaAssuranceDeniedError,
    lambda: mfa.evaluate_mfa_assurance_entra(
        provider_tier="entra_free", id_token_claims={}, required_authentication_context_id=REQUIRED_ID,
    ),
    "Entra Free with no acrs fails closed",
)
expect_raises(
    mfa.MfaAssuranceDeniedError,
    lambda: mfa.evaluate_mfa_assurance_entra(
        provider_tier="entra_free",
        id_token_claims={"acrs": [REQUIRED_ID]},
        required_authentication_context_id=REQUIRED_ID,
    ),
    "Entra Free fails closed even with a matching acrs array present (tier gate, not claim-driven)",
)

# Entra P1: satisfied only on exact membership.
result = mfa.evaluate_mfa_assurance_entra(
    provider_tier="entra_p1",
    id_token_claims={"acrs": ["c2", REQUIRED_ID]},
    required_authentication_context_id=REQUIRED_ID,
)
check("Entra P1 with required id present is satisfied", result.satisfied is True)
check("Entra P1 result reports the correct assurance level", result.level == mfa.MfaAssuranceLevel.ENTRA_P1_CONTEXT_SATISFIED)
check("Entra P1 result carries a policy_version for audit", bool(result.policy_version))

for label, claims in [
    ("Entra P1 with acrs absent fails closed", {}),
    ("Entra P1 with acrs as scalar fails closed", {"acrs": REQUIRED_ID}),
    ("Entra P1 with acrs empty array fails closed", {"acrs": []}),
    ("Entra P1 with acrs containing only unrelated ids fails closed", {"acrs": ["c2", "c3"]}),
    ("Entra P1 with acrs containing duplicates fails closed", {"acrs": [REQUIRED_ID, REQUIRED_ID]}),
    ("Entra P1 with near-match case difference fails closed", {"acrs": [REQUIRED_ID.upper()]}),
]:
    expect_raises(
        mfa.MfaAssuranceDeniedError,
        lambda c=claims: mfa.evaluate_mfa_assurance_entra(
            provider_tier="entra_p1", id_token_claims=c, required_authentication_context_id=REQUIRED_ID,
        ),
        label,
    )

expect_raises(
    ValueError,
    lambda: mfa.evaluate_mfa_assurance_entra(
        provider_tier="entra_free_trial_typo", id_token_claims={}, required_authentication_context_id=REQUIRED_ID,
    ),
    "unknown provider_tier is a programming error, fails closed",
)

# This module must never claim to verify the Conditional Access
# policy-to-context binding - that is exclusively a Row 19D gate.
check(
    "module does not expose any policy-binding verification function",
    not hasattr(mfa, "verify_policy_binding") and not hasattr(mfa, "check_conditional_access_policy"),
)

print(f"--- test_mfa_adapter_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
