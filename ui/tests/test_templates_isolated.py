# ============================================================
# Row 18a - Ham Jinja2 render / autoescape testleri (targeted
# remediation). FastAPI'ye ihtiyaç duymaz - `ui/services/*` katmanını
# GERÇEK case_0001 verisiyle çağırıp şablonları doğrudan
# `jinja2.Environment` ile render eder (Starlette'in
# `Jinja2Templates`'inin kullandığı autoescape=True ayarıyla).
#
# TARGETED REMEDIATION: bu dosya, main.py/approval_registry.py'de bu
# turda yapılan şekil değişikliklerini (csrf_token context'e eklendi,
# error.html'e `code` eklendi, fact/timeline artık
# `unsupported_pending_resolution` şeklinde, `reg.fact_review`/
# `reg.fact_approve`/`reg.timeline_review`/`reg.timeline_approve`
# KALDIRILDI) yansıtacak şekilde önceki turdaki şablon testinin
# YERİNİ ALIR.
#
# Çalıştırma: python ui/tests/test_templates_isolated.py
# ============================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jinja2  # noqa: E402

from ui.services import paths, live_view, security  # noqa: E402
from ui.services import approval_registry as reg  # noqa: E402

TEMPLATES_DIR = str(REPO_ROOT / "ui" / "templates")

_case_ids = paths.list_case_ids()

if not _case_ids:
    print("Hiç case yok - şablon testleri çalıştırılamıyor.")
    sys.exit(1)

CASE_ID = _case_ids[0]

env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
    autoescape=True,  # Starlette'in Jinja2Templates varsayılanıyla AYNI
)

passed = 0
failed = 0


def check(label, fn):
    global passed, failed
    try:
        html = fn()
        assert isinstance(html, str) and len(html) > 0
        passed += 1
        print(f"PASS {label} ({len(html)} chars)")
        return html
    except Exception as e:
        failed += 1
        print(f"FAIL {label}: {type(e).__name__}: {e}")
        return None


def check_contains(label, html, *substrings):
    global passed, failed
    if html is None:
        failed += 1
        print(f"FAIL {label}: render yoktu")
        return
    missing = [s for s in substrings if s not in html]
    if missing:
        failed += 1
        print(f"FAIL {label}: eksik: {missing}")
    else:
        passed += 1
        print(f"PASS {label}")


def check_not_contains(label, html, *substrings):
    global passed, failed
    if html is None:
        failed += 1
        print(f"FAIL {label}: render yoktu")
        return
    present = [s for s in substrings if s in html]
    if present:
        failed += 1
        print(f"FAIL {label}: BULUNMAMASI gereken metin bulundu: {present}")
    else:
        passed += 1
        print(f"PASS {label}")


# --- gerçek servis katmanı verisiyle fixture'lar ---
live = live_view.build_live_view(CASE_ID)
staleness = live_view.get_case_view_with_staleness(CASE_ID)
rows = reg.full_case_approval_status(CASE_ID)
cv_review = reg.case_scoped_review("case_view", CASE_ID)
first_issue = live["issue_panel"][0]

_secret = security.new_csrf_secret()
_csrf_token = security.make_csrf_token(_secret, CASE_ID, "case_view", cv_review["pending_hash"])

check("index.html (with cases)", lambda: env.get_template("index.html").render(
    case_ids=paths.list_case_ids(),
))
check("index.html (empty)", lambda: env.get_template("index.html").render(
    case_ids=[],
))

check("case_view.html (fresh, has_canonical, not stale)", lambda: env.get_template("case_view.html").render(
    case_id=CASE_ID, view=staleness["live_view"], is_stale=False, has_canonical=True,
))
check("case_view.html (stale)", lambda: env.get_template("case_view.html").render(
    case_id=CASE_ID, view=staleness["live_view"], is_stale=True, has_canonical=True,
))
check("case_view.html (no canonical yet)", lambda: env.get_template("case_view.html").render(
    case_id=CASE_ID, view=staleness["live_view"], is_stale=False, has_canonical=False,
))

check("issue_detail.html", lambda: env.get_template("issue_detail.html").render(
    case_id=CASE_ID, issue=first_issue,
))

html = check("approvals_list.html", lambda: env.get_template("approvals_list.html").render(
    case_id=CASE_ID, rows=rows,
))
check_not_contains(
    "approvals_list.html: fact/timeline satırları artık onay linki İÇERMİYOR",
    html, "/approvals/fact/", "/approvals/timeline/",
)
check_contains(
    "approvals_list.html: unsupported_pending_resolution bilgi metni render ediliyor",
    html, "web üzerinden onay desteklenmiyor",
)

html = check("approval_review.html (case_scoped, csrf_token ile)", lambda: env.get_template("approval_review.html").render(
    case_id=CASE_ID, row=cv_review["row"], pending_hash=cv_review["pending_hash"],
    analysis=cv_review["analysis"], confirm_action=f"/cases/{CASE_ID}/approvals/case_view/confirm",
    back_url=f"/cases/{CASE_ID}/approvals", csrf_token=_csrf_token,
))
check_contains(
    "approval_review.html: csrf_token gizli alanı render edildi",
    html, 'name="csrf_token"', _csrf_token,
)

# NOT: `reg.fact_review`/`reg.fact_approve`/`reg.timeline_review`/
# `reg.timeline_approve` bu turda KALDIRILDI (bkz. approval_registry.py
# docstring) - bu yüzden ayrı bir "approval_review.html (fact)" testi
# artık YOK. Fact/timeline artık yalnız approvals_list.html üzerinden
# salt-bilgi olarak (yukarıdaki test) doğrulanıyor.

html = check("approval_result.html", lambda: env.get_template("approval_result.html").render(
    case_id=CASE_ID, label="Product Orchestrator (Case View)",
    canonical_path=paths.to_repo_relative(paths.CASES_DIR / CASE_ID / "case_view" / "case_view.json"),
    canonical_hash="a" * 64,
    audit_path=paths.to_repo_relative(paths.CASES_DIR / CASE_ID / "case_view" / "reviews" / "x.approval.json"),
))
check_not_contains(
    "approval_result.html: ham mutlak dosya sistemi path'i SIZMIYOR",
    html, str(paths.BASE_DIR),
)
check("approval_result.html (no audit found)", lambda: env.get_template("approval_result.html").render(
    case_id=CASE_ID, label="X", canonical_path="x.json", canonical_hash="b" * 64,
    audit_path=None,
))

html = check("error.html (code ile)", lambda: env.get_template("error.html").render(
    title="Hata",
    message="Görünüm bu ekran açıldıktan sonra değişti - onay iptal edildi.",
    code="STALE_VIEW",
    back_url=f"/cases/{CASE_ID}/approvals",
))
check_contains("error.html: hata kodu render edildi", html, "STALE_VIEW")
check_not_contains(
    "error.html: ham exception/traceback metni İÇERMİYOR",
    html, "Traceback", "raise ", "  File \"",
)

print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
