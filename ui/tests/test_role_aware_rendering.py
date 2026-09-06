# ============================================================
# Row 19B - isolated tests for the three role-aware template guards
# added in this Row (case_view.html's drafting-request link,
# approval_review.html's confirm <form>, review_detail.html's confirm
# <form>). Uses Jinja2 directly (no FastAPI/Starlette needed) - this
# module genuinely renders the real, on-disk template files, not a
# reimplementation of their logic.
#
# TEMPLATE DEPENDENCY NOTE (read before editing): case_view.html,
# approval_review.html and review_detail.html all `{% import
# "macros.html" as m %}`. macros.html itself is UNCHANGED by Row 19B
# (not in the 40-path allowlist) and is therefore not staged in this
# sandbox's ui/templates/ directory alongside the files this Row DOES
# touch. To let this test genuinely render the real templates rather
# than skipping, a read-only reference copy of macros.html (plus
# error.html/index.html, unused by this file but staged at the same
# time) was pulled directly from the real repository via the device
# bridge and placed under `_reference_only_not_delivered/` at the repo
# root - confirmed byte-identical (sha256) to the file the device
# reports. That directory is NOT one of the 40 authorized paths and
# MUST NOT be delivered - see the delivery report. On the real machine
# this test's template loader resolves macros.html from the real
# `ui/templates/` directory instead (see TEMPLATE_DIRS below) and the
# reference copy is irrelevant/unused there.
#
# Run: python -m ui.tests.test_role_aware_rendering
# ============================================================

import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jinja2 import Environment, ChoiceLoader, FileSystemLoader  # noqa: E402

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


# Real ui/templates/ FIRST (authoritative on a real checkout - if
# macros.html is ever added there for real, this loader finds it and
# the reference copy below is never consulted). The
# _reference_only_not_delivered copy is a SANDBOX-ONLY fallback so this
# test does not have to be skipped here.
_REFERENCE_ONLY_DIR = REPO_ROOT / "_reference_only_not_delivered" / "ui" / "templates"

TEMPLATE_DIRS = [str(UI_DIR / "templates")]
if _REFERENCE_ONLY_DIR.is_dir():
    TEMPLATE_DIRS.append(str(_REFERENCE_ONLY_DIR))

env = Environment(
    loader=ChoiceLoader([FileSystemLoader(d) for d in TEMPLATE_DIRS]),
    autoescape=True,
)


def render(name, **context):
    return env.get_template(name).render(**context)


# ---------------------------------------------------------------
# case_view.html - drafting-request link gated on can_view_drafting_request
# (Row 19B: lawyer-only, main.py computes this via
# auth_routes.has_capability(..., "mutate")).
# ---------------------------------------------------------------

_CASE_VIEW_BASE_CONTEXT = dict(
    case_id="case_iso_0001",
    view={"case_summary": {"title": "Örnek Dava"}, "generation_status": "ok", "issue_panel": []},
    is_stale=False,
    has_canonical=True,
)

html_lawyer_case_view = render("case_view.html", can_view_drafting_request=True, **_CASE_VIEW_BASE_CONTEXT)
check(
    "case_view.html: lawyer (can_view_drafting_request=True) sees the drafting-request link",
    "/drafting-request" in html_lawyer_case_view,
)

html_analyst_case_view = render("case_view.html", can_view_drafting_request=False, **_CASE_VIEW_BASE_CONTEXT)
check(
    "case_view.html: analyst (can_view_drafting_request=False) does NOT see the drafting-request link",
    "/drafting-request" not in html_analyst_case_view,
)
check(
    "case_view.html: analyst still sees the unrelated approvals/reviews links (guard is scoped, not a blanket removal)",
    "/approvals" in html_analyst_case_view and "/reviews" in html_analyst_case_view,
)

# ---------------------------------------------------------------
# approval_review.html - confirm <form> gated on can_mutate.
# ---------------------------------------------------------------

_APPROVAL_REVIEW_BASE_CONTEXT = dict(
    case_id="case_iso_0001",
    row={"label": "Örnek Onay", "row_no": 3},
    pending_hash="a" * 64,
    analysis={"ozet": "test"},
    csrf_token="token123",
    confirm_action="/cases/case_iso_0001/approvals/row3/confirm",
    back_url="/cases/case_iso_0001/approvals",
)

html_lawyer_approval = render("approval_review.html", can_mutate=True, **_APPROVAL_REVIEW_BASE_CONTEXT)
check(
    "approval_review.html: lawyer (can_mutate=True) sees the confirm <form>",
    "<form" in html_lawyer_approval and 'name="csrf_token"' in html_lawyer_approval,
)

html_analyst_approval = render("approval_review.html", can_mutate=False, **_APPROVAL_REVIEW_BASE_CONTEXT)
check(
    "approval_review.html: analyst (can_mutate=False) does NOT see the confirm <form>",
    "<form" not in html_analyst_approval,
)
check(
    "approval_review.html: analyst sees an explanatory denial banner instead of a blank section",
    "yetkiniz yok" in html_analyst_approval,
)
check(
    "approval_review.html: the read-only record content (kayıt içeriği) still renders for the analyst - the guard hides only the mutation form",
    "test" in html_analyst_approval,
)

# ---------------------------------------------------------------
# review_detail.html - confirm <form> (+ CSRF-token script) gated on
# can_mutate.
# ---------------------------------------------------------------

_REVIEW_DETAIL_BASE_CONTEXT = dict(
    case_id="case_iso_0001",
    record_id="rec-1",
    label="Örnek İnceleme",
    record={"ozet": "kayit-icerigi"},
    canonical_hash="b" * 64,
    allowed_targets=["approved", "rejected"],
    csrf_tokens_by_target={"approved": "tokA", "rejected": "tokB"},
    csrf_token="tokA",
    confirm_action="/cases/case_iso_0001/reviews/qa.suggestion/rec-1/confirm",
    back_url="/cases/case_iso_0001/reviews",
)

html_lawyer_review = render("review_detail.html", can_mutate=True, **_REVIEW_DETAIL_BASE_CONTEXT)
check(
    "review_detail.html: lawyer (can_mutate=True) sees the confirm <form> and the CSRF-token-by-target script",
    "<form" in html_lawyer_review and "CSRF_TOKENS_BY_TARGET" in html_lawyer_review,
)

html_analyst_review = render("review_detail.html", can_mutate=False, **_REVIEW_DETAIL_BASE_CONTEXT)
check(
    "review_detail.html: analyst (can_mutate=False) does NOT see the confirm <form>",
    "<form" not in html_analyst_review,
)
check(
    "review_detail.html: analyst sees an explanatory denial banner instead of a blank section",
    "yetkiniz yok" in html_analyst_review,
)
check(
    "review_detail.html: the read-only record content still renders for the analyst - the guard hides only the mutation form",
    "kayit-icerigi" in html_analyst_review,
)

# ---------------------------------------------------------------
# base.html - the now-corrected footer no longer claims auth/session/
# authorization are out of scope (Row 19B added exactly those).
# ---------------------------------------------------------------

html_base = render("base.html")
check(
    "base.html: footer no longer falsely claims authentication is out of scope",
    "kimlik doğrulama" not in html_base.lower() or "eklenmiştir" in html_base,
)
check(
    "base.html: footer no longer references the old 'Row 19' not-yet-built framing verbatim",
    "kapsamında değildir (Row 19)" not in html_base,
)

# ---------------------------------------------------------------
# login.html - renders standalone and links to /auth/login.
# ---------------------------------------------------------------

html_login = render("login.html")
check("login.html: renders and links to /auth/login", 'href="/auth/login"' in html_login)

print(f"--- test_role_aware_rendering: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
