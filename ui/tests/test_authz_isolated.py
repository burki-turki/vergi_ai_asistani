# ============================================================
# Row 19B - isolated tests for ui/services/authz.py.
# Pure logic + in-memory fake repository, no DB required.
# Run: python -m ui.tests.test_authz_isolated
# ============================================================

import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import authz   # noqa: E402
from ui.services.common import UnknownCaseError   # noqa: E402

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


def fake_resolver(case_id: str) -> str:
    return f"/data/cases/{case_id}"


repo = authz.InMemoryAuthzRepository()
repo.sessions[1] = authz.SessionRecord(user_id=100, current_authz_version=3, disabled=False)
repo.sessions[2] = authz.SessionRecord(user_id=100, current_authz_version=3, disabled=False)
repo.assignments[(100, "case_0001")] = authz.CaseAssignmentRecord(role="lawyer")
repo.assignments[(100, "case_0002")] = authz.CaseAssignmentRecord(role="analyst")

lawyer = authz.Principal(user_id=100, session_id=1, role_version_at_issue=3)
analyst_principal = authz.Principal(user_id=100, session_id=2, role_version_at_issue=3)

# --- lawyer: read + mutate on assigned case ---
path = authz.authorize_case_access(lawyer, "case_0001", "read", repository=repo, resolve_case_id=fake_resolver)
check("lawyer can read an assigned case", path == "/data/cases/case_0001")
path = authz.authorize_case_access(lawyer, "case_0001", "mutate", repository=repo, resolve_case_id=fake_resolver)
check("lawyer can mutate an assigned case", path == "/data/cases/case_0001")

# --- analyst: read yes, mutate no ---
path = authz.authorize_case_access(analyst_principal, "case_0002", "read", repository=repo, resolve_case_id=fake_resolver)
check("analyst can read an assigned case", path == "/data/cases/case_0002")
expect_raises(
    authz.CaseAccessDeniedError,
    lambda: authz.authorize_case_access(analyst_principal, "case_0002", "mutate", repository=repo, resolve_case_id=fake_resolver),
    "analyst is denied mutate capability (both route AND service layers rely on this same check)",
)

# --- existence-blind: a truly nonexistent case_id and a real case_id
# this user simply has no assignment for must raise the IDENTICAL
# reason_code, so a caller/log can never tell them apart.
try:
    authz.authorize_case_access(lawyer, "case_9999_nonexistent", "read", repository=repo, resolve_case_id=fake_resolver)
    check("nonexistent case is denied", False)
except authz.CaseAccessDeniedError as e1:
    # case_0002 genuinely exists (it's assigned to this same user_id as
    # analyst) but `lawyer` here is a DIFFERENT session for the same
    # user_id - use a case_id with zero assignment rows for this user_id
    # at all, to isolate "unassigned" from "nonexistent" cleanly:
    other_user_only_case = "case_0002"
    del repo.assignments[(100, other_user_only_case)]  # temporarily remove to simulate "unassigned for this user"
    try:
        authz.authorize_case_access(lawyer, other_user_only_case, "read", repository=repo, resolve_case_id=fake_resolver)
        check("cross-check", False)
    except authz.CaseAccessDeniedError as e2:
        check(
            "nonexistent case_id and an existing-but-unassigned case_id raise the identical reason_code (existence-blind)",
            e1.reason_code == e2.reason_code == "assignment_revoked",
        )
    finally:
        repo.assignments[(100, other_user_only_case)] = authz.CaseAssignmentRecord(role="analyst")  # restore

# --- TARGETED REMEDIATION: a case_id that passes steps 1-4 (fresh
# session, valid syntax, an ACTIVE assignment row, correct capability -
# e.g. a case_assignments row that survived a case directory being
# removed/renamed, or simply a stale/permissive record) but whose
# filesystem resolution step (paths.resolve_case_id, injected here as a
# fake) raises UnknownCaseError must NOT leak that raw exception to the
# caller (this was the real bug: it propagated unhandled through
# authorize_case_access, through require_principal_and_case, into
# FastAPI, crashing test_routes.py/test_drafting_request_routes.py with
# an unhandled UnknownCaseError instead of a controlled denial). It must
# be converted to the SAME CaseAccessDeniedError family, with the SAME
# reason_code, as a genuinely-unassigned case - existence-blind end to
# end, not just at the syntax-validation step.
repo.assignments[(100, "case_resolves_to_nothing")] = authz.CaseAssignmentRecord(role="lawyer")


def resolver_that_raises_unknown_case(case_id: str) -> str:
    raise UnknownCaseError(f"{case_id} does not match any real case directory")


try:
    authz.authorize_case_access(
        lawyer, "case_resolves_to_nothing", "read",
        repository=repo, resolve_case_id=resolver_that_raises_unknown_case,
    )
    check("an assigned-but-filesystem-unresolvable case_id is denied, not silently allowed", False)
except authz.CaseAccessDeniedError as unresolvable_error:
    check(
        "UnknownCaseError from resolve_case_id is converted to CaseAccessDeniedError, not left to propagate raw",
        True,
    )
    check(
        "the converted error carries the SAME reason_code as a genuinely-unassigned case (existence-blind at the resolver step too)",
        unresolvable_error.reason_code == "assignment_revoked",
    )
except UnknownCaseError:
    check("an assigned-but-filesystem-unresolvable case_id is denied, not left to propagate raw UnknownCaseError", False)

# regression guard: a real, assigned, filesystem-resolvable case_id must
# still succeed exactly as before this fix (item 4 - valid/assigned
# access must not change).
path = authz.authorize_case_access(lawyer, "case_0001", "read", repository=repo, resolve_case_id=fake_resolver)
check("a genuinely resolvable, assigned case still succeeds unaffected by the UnknownCaseError handling", path == "/data/cases/case_0001")

# --- revoked assignment (simulated: remove it) takes effect immediately ---
del repo.assignments[(100, "case_0001")]
expect_raises(
    authz.CaseAccessDeniedError,
    lambda: authz.authorize_case_access(lawyer, "case_0001", "read", repository=repo, resolve_case_id=fake_resolver),
    "revoked assignment is denied on the very next call (no caching)",
)
repo.assignments[(100, "case_0001")] = authz.CaseAssignmentRecord(role="lawyer")  # restore

# --- authz_version mismatch (role/assignment changed elsewhere) denies immediately ---
stale_principal = authz.Principal(user_id=100, session_id=1, role_version_at_issue=2)  # session says v3, principal carries stale v2
expect_raises(
    authz.CaseAccessDeniedError,
    lambda: authz.authorize_case_access(stale_principal, "case_0001", "read", repository=repo, resolve_case_id=fake_resolver),
    "stale role_version_at_issue vs live authz_version is denied (mid-session revocation takes effect next request)",
)

# --- disabled user is denied even with a valid-looking assignment ---
repo.sessions[3] = authz.SessionRecord(user_id=100, current_authz_version=3, disabled=True)
disabled_principal = authz.Principal(user_id=100, session_id=3, role_version_at_issue=3)
expect_raises(
    authz.CaseAccessDeniedError,
    lambda: authz.authorize_case_access(disabled_principal, "case_0001", "read", repository=repo, resolve_case_id=fake_resolver),
    "disabled user is denied",
)

# --- unknown session ---
ghost_principal = authz.Principal(user_id=100, session_id=999, role_version_at_issue=3)
expect_raises(
    authz.CaseAccessDeniedError,
    lambda: authz.authorize_case_access(ghost_principal, "case_0001", "read", repository=repo, resolve_case_id=fake_resolver),
    "unknown/expired session is denied",
)

# --- case_id syntax validation happens BEFORE any repository call ---
class ExplodingRepository(authz.InMemoryAuthzRepository):
    def get_active_case_assignment(self, user_id, case_id):
        raise AssertionError("must not be reached for a syntactically invalid case_id")

exploding_repo = ExplodingRepository()
exploding_repo.sessions[1] = authz.SessionRecord(user_id=100, current_authz_version=3, disabled=False)
for bad_case_id in ["../etc/passwd", "case/0001", "", "a" * 65, "case 0001"]:
    expect_raises(
        authz.CaseAccessDeniedError,
        lambda cid=bad_case_id: authz.authorize_case_access(lawyer, cid, "read", repository=exploding_repo, resolve_case_id=fake_resolver),
        f"malformed case_id {bad_case_id!r} is rejected before any assignment lookup",
    )

# --- admin has zero case-content capability on its own ---
check(
    "admin role is not present in the capability matrix at all (no case access from the role alone)",
    "admin" not in authz._ROLE_CAPABILITIES,
)

# ----------------------------------------------------------------
# Row 19B targeted remediation (finding 2) - authz.list_accessible_case_ids.
# The single authz-layer source of truth for GET /'s case listing.
# ----------------------------------------------------------------

listing_repo = authz.InMemoryAuthzRepository()

# lawyer with two active assignments, one revoked
listing_repo.sessions[10] = authz.SessionRecord(user_id=200, current_authz_version=1, disabled=False)
listing_repo.assignments[(200, "case_a")] = authz.CaseAssignmentRecord(role="lawyer")
listing_repo.assignments[(200, "case_b")] = authz.CaseAssignmentRecord(role="lawyer")
lawyer_principal = authz.Principal(user_id=200, session_id=10, role_version_at_issue=1)

result = authz.list_accessible_case_ids(lawyer_principal, repository=listing_repo, resolve_case_id=fake_resolver)
check(
    "lawyer sees exactly their own active, resolvable assigned case ids",
    result == sorted(["/data/cases/case_a", "/data/cases/case_b"]),
    f"got {result}",
)

# analyst with one active assignment
listing_repo.sessions[11] = authz.SessionRecord(user_id=201, current_authz_version=1, disabled=False)
listing_repo.assignments[(201, "case_c")] = authz.CaseAssignmentRecord(role="analyst")
analyst_listing_principal = authz.Principal(user_id=201, session_id=11, role_version_at_issue=1)
result = authz.list_accessible_case_ids(analyst_listing_principal, repository=listing_repo, resolve_case_id=fake_resolver)
check("analyst sees exactly their own active assigned case ids", result == ["/data/cases/case_c"])

# cross-user: user 200's assignments must never leak into user 201's listing
check(
    "cross-user isolation: analyst's listing does not include the lawyer's (different user_id) case ids",
    "/data/cases/case_a" not in result and "/data/cases/case_b" not in result,
)

# admin: ALWAYS empty, unconditionally - even if also explicitly assigned a case
listing_repo.sessions[12] = authz.SessionRecord(user_id=202, current_authz_version=1, disabled=False)
listing_repo.admins.add(202)
listing_repo.assignments[(202, "case_admin_also_assigned")] = authz.CaseAssignmentRecord(role="lawyer")
admin_listing_principal = authz.Principal(user_id=202, session_id=12, role_version_at_issue=1)
result = authz.list_accessible_case_ids(admin_listing_principal, repository=listing_repo, resolve_case_id=fake_resolver)
check(
    "global admin sees ZERO case ids, unconditionally - even when also explicitly assigned a case as lawyer",
    result == [],
    f"got {result}",
)

# revoked assignment must not appear
listing_repo.sessions[13] = authz.SessionRecord(user_id=203, current_authz_version=1, disabled=False)
listing_repo.assignments[(203, "case_revoked_target")] = authz.CaseAssignmentRecord(role="lawyer")
revoked_listing_principal = authz.Principal(user_id=203, session_id=13, role_version_at_issue=1)
del listing_repo.assignments[(203, "case_revoked_target")]  # InMemoryAuthzRepository has no revoked_at - simulate revocation by removal, matching get_active_case_assignment's own existing convention in this fake
result = authz.list_accessible_case_ids(revoked_listing_principal, repository=listing_repo, resolve_case_id=fake_resolver)
check("a revoked (removed) assignment does not appear in the listing", result == [])

# stale/nonexistent assigned case (filesystem no longer resolves it) is
# silently dropped, not raised, and does not affect other resolvable
# case ids for the same user.
listing_repo.sessions[14] = authz.SessionRecord(user_id=204, current_authz_version=1, disabled=False)
listing_repo.assignments[(204, "case_stale")] = authz.CaseAssignmentRecord(role="lawyer")
listing_repo.assignments[(204, "case_fine")] = authz.CaseAssignmentRecord(role="lawyer")
stale_listing_principal = authz.Principal(user_id=204, session_id=14, role_version_at_issue=1)


def resolver_stale_or_fine(case_id: str) -> str:
    if case_id == "case_stale":
        raise UnknownCaseError("case_stale no longer exists on disk")
    return f"/data/cases/{case_id}"


result = authz.list_accessible_case_ids(stale_listing_principal, repository=listing_repo, resolve_case_id=resolver_stale_or_fine)
check(
    "a stale/nonexistent assigned case is silently omitted, without erroring the whole listing",
    result == ["/data/cases/case_fine"],
    f"got {result}",
)

# denial-path defensiveness: unauthenticated/disabled/stale-version session -> empty, never raises
check(
    "unknown session -> empty list, not an exception",
    authz.list_accessible_case_ids(
        authz.Principal(user_id=999, session_id=9999, role_version_at_issue=1),
        repository=listing_repo, resolve_case_id=fake_resolver,
    ) == [],
)
listing_repo.sessions[15] = authz.SessionRecord(user_id=205, current_authz_version=1, disabled=True)
check(
    "disabled user's session -> empty list, not an exception",
    authz.list_accessible_case_ids(
        authz.Principal(user_id=205, session_id=15, role_version_at_issue=1),
        repository=listing_repo, resolve_case_id=fake_resolver,
    ) == [],
)
check(
    "stale role_version_at_issue -> empty list, not an exception",
    authz.list_accessible_case_ids(
        authz.Principal(user_id=200, session_id=10, role_version_at_issue=999),
        repository=listing_repo, resolve_case_id=fake_resolver,
    ) == [],
)

print(f"--- test_authz_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
