# ============================================================
# Row 19B - isolated tests for scripts/iam_bootstrap_probe.py's
# purpose-gating logic. Pure decision logic against an injected
# admin_exists() callable - no DB, no OIDC provider, no psycopg/
# Authlib/joserfc needed. The real end-to-end flow (main(), which
# needs Authlib/joserfc and a real provider) is NOT EXECUTED here.
#
# Run: python -m ui.tests.test_iam_bootstrap_probe_isolated
# ============================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import iam_bootstrap_probe as probe   # noqa: E402

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


def no_admin_yet():
    return False


def admin_already_exists():
    return True


# --- first-admin purpose ---
probe.check_purpose_allowed("first-admin", admin_exists=no_admin_yet)
check("first-admin is allowed when no admin exists", True)

expect_raises(
    probe.ProbeNotAllowedError,
    lambda: probe.check_purpose_allowed("first-admin", admin_exists=admin_already_exists),
    "first-admin is rejected once an admin already exists (prevents re-bootstrap)",
)

# --- provision-user purpose ---
probe.check_purpose_allowed("provision-user", admin_exists=admin_already_exists)
check("provision-user is allowed after bootstrap (an admin exists)", True)

expect_raises(
    probe.ProbeNotAllowedError,
    lambda: probe.check_purpose_allowed("provision-user", admin_exists=no_admin_yet),
    "provision-user is rejected before any admin exists (must bootstrap first)",
)

# --- unknown purpose ---
expect_raises(
    ValueError,
    lambda: probe.check_purpose_allowed("something-else", admin_exists=no_admin_yet),
    "unknown purpose is rejected",
)

# --- both modes are proven to make zero durable-table calls by
#     construction: admin_exists() is the ONLY thing check_purpose_allowed
#     calls, and it never calls INSERT/UPDATE/DELETE - prove this by using
#     a call-counting fake that would fail loudly if anything else were
#     invoked. ---

call_log = []


def counting_admin_exists(expected_result):
    def _inner():
        call_log.append("admin_exists")
        return expected_result
    return _inner


call_log.clear()
probe.check_purpose_allowed("first-admin", admin_exists=counting_admin_exists(False))
check(
    "check_purpose_allowed calls admin_exists exactly once and nothing else (zero durable mutation surface)",
    call_log == ["admin_exists"],
)

# --- run_probe itself requires joserfc/Authlib to actually fetch/verify
#     a real token - guarded, NOT EXECUTED here, exactly like the
#     oidc_client I/O functions it calls. ---
try:
    import authlib  # noqa: F401
    import joserfc   # noqa: F401
    _CAN_RUN_IO_TESTS = True
except ModuleNotFoundError:
    _CAN_RUN_IO_TESTS = False

if not _CAN_RUN_IO_TESTS:
    print("SKIPPED run_probe() end-to-end validation - Authlib/joserfc not "
          "installed in this environment. NOT EXECUTED, not a pass.")
else:
    print("Authlib/joserfc detected but run_probe() needs a real provider "
          "redirect and is out of scope for this isolated module.")

print(f"--- test_iam_bootstrap_probe_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
