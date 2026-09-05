# ============================================================
# Row 18C - Ham Jinja2 render / autoescape testleri
# (drafting_request.html, drafting_request_result.html). FastAPI'ye
# İHTİYAÇ DUYMAZ - `ui/services/drafting_request.py`'yi GERÇEK
# case_0001 verisiyle (salt-okunur, mümkün olduğunda) çağırıp
# şablonları doğrudan `jinja2.Environment` ile render eder
# (Starlette'in `Jinja2Templates`'inin kullandığı autoescape=True
# ayarıyla - `test_review_templates_isolated.py`/
# `test_templates_isolated.py` (Row 18a/18b) ile AYNI desen).
#
# Bu dosya, `ui/main.py`'deki GERÇEK route'ların
# (`drafting_request_page`, `drafting_request_confirm`) her birine
# geçirdiği context anahtarlarını BİREBİR aynı şekilde kullanır.
#
# Çalıştırma: python ui/tests/test_drafting_request_templates_isolated.py
# ============================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jinja2  # noqa: E402

from ui.services import paths  # noqa: E402
from ui.services import drafting_request as dr  # noqa: E402

TEMPLATES_DIR = str(REPO_ROOT / "ui" / "templates")

_case_ids = paths.list_case_ids()

if not _case_ids:
    print("Hiç case yok - Row 18C şablon testleri çalıştırılamıyor.")
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
        print(f"FAIL {label}: BEKLENMEDİK biçimde mevcut: {present}")
    else:
        passed += 1
        print(f"PASS {label}")


def _render_page(**overrides):
    ctx = dict(
        case_id=CASE_ID, current_wrapper=None, current_validation_errors=None,
        expected_current_input_hash=dr.NO_EXISTING_INPUT_SENTINEL,
        pending_status={"exists": False, "matches_saved": None, "unreadable": False},
        canonical_status={"exists": False, "matches_saved": None, "unreadable": False},
        canonical_issues=[], draft_intent_types=sorted(dr.DRAFT_INTENT_TYPES),
        appeal_levels=sorted(dr.APPEAL_LEVELS), request_authorized_explanation=None,
        csrf_token="dummy_csrf", confirm_action=f"/cases/{CASE_ID}/drafting-request/confirm",
        back_url=f"/cases/{CASE_ID}", limits=dr.FIELD_LIMITS,
    )
    ctx.update(overrides)
    return env.get_template("drafting_request.html").render(**ctx)


# ============================================================
# 1) GERÇEK case_0001 VERİSİYLE (salt-okunur) - kayıtlı girdi
#    olsun/olmasın GET görünümü render edilebilmeli.
# ============================================================

try:
    real_view = dr.build_drafting_request_view(CASE_ID)
except Exception as error:
    print(f"UYARI: gerçek case_0001 için build_drafting_request_view başarısız oldu ({error!r}) - "
          "yalnız sentetik testlerle devam ediliyor.")
    real_view = None

if real_view is not None:
    html_real = check(
        "drafting_request.html (GERÇEK case_0001 - salt-okunur)",
        lambda: _render_page(
            current_wrapper=real_view["current_wrapper"],
            current_validation_errors=real_view["current_validation_errors"],
            expected_current_input_hash=real_view["expected_current_input_hash"],
            pending_status=real_view["pending_status"], canonical_status=real_view["canonical_status"],
            canonical_issues=real_view["canonical_issues"],
            request_authorized_explanation=real_view["request_authorized_explanation"],
        ),
    )
    check_contains("drafting_request.html (GERÇEK case_0001): case_id doğru gömülü", html_real, CASE_ID)


# ============================================================
# 2) SENTETİK - BOŞ DURUM (hiç kayıtlı girdi yok)
# ============================================================

html_empty = check("drafting_request.html (sentetik - hiç kayıtlı girdi yok)", lambda: _render_page())
check_contains(
    "drafting_request.html (boş durum): 'henüz kaydedilmiş bir avukat girdisi yok' banner'ı var",
    html_empty, "henüz kaydedilmiş bir avukat girdisi yok",
)
check_contains(
    "drafting_request.html: kaydetmenin ÜRETİM ANLAMINA GELMEDİĞİ uyarısı sayfada var",
    html_empty, "Kaydetmek, bir taslak", "ÜRETMEZ",
)


# ============================================================
# 3) SENTETİK - XSS/SCRIPT PAYLOAD (kayıtlı girdi + canonical issue
#    başlığı + doğrulama hatası mesajı İÇİNDE) - autoescape/`|tojson`
#    hiçbir zaman ham HTML/script SIZDIRMAMALI.
# ============================================================

_malicious_wrapper = {
    "saved_at": "2026-01-01T00:00:00+00:00",
    "lawyer_input_hash": "a" * 64,
    "lawyer_input": {
        "draft_intent_type": "appeal_petition", "appeal_level": "istinaf",
        "selected_issue_ids": ["iss_xss"],
        "request_input": {
            "request_type": "<script>alert('xss-type')</script>",
            "request_text": "\" onmouseover=\"alert(1)",
        },
        "lawyer_provided_text": "</textarea><script>alert('xss-text')</script>",
    },
}

html_xss = check(
    "drafting_request.html (sentetik - XSS payload'lı kayıtlı girdi)",
    lambda: _render_page(
        current_wrapper=_malicious_wrapper,
        canonical_issues=[{"issue_id": "iss_xss", "title": "<script>alert('xss-title')</script>"}],
        current_validation_errors=["şema ihlali: alan=<script>alert('err')</script> kural=type"],
    ),
)
check_not_contains(
    "drafting_request.html: hiçbir <script> payload'ı HAM olarak SIZMIYOR",
    html_xss,
    "<script>alert('xss-type')</script>", "<script>alert('xss-text')</script>",
    "<script>alert('xss-title')</script>", "<script>alert('err')</script>",
    "</textarea><script>",
)
check_contains(
    "drafting_request.html: script payload'ları HTML-escape edilmiş olarak render edildi",
    html_xss, "&lt;script&gt;",
)
check_contains(
    "drafting_request.html: sunucu tarafı sabit APPEAL_PETITION_VALUE |tojson ile JS'e gömülü",
    html_xss, 'const APPEAL_PETITION_VALUE = "appeal_petition";',
)
check_not_contains(
    "drafting_request.html: gömülü JSON HTML-entity-escape edilmiş tırnak İÇERMİYOR (|tojson kullanılıyor)",
    html_xss, "&quot;appeal_petition&quot;",
)


# ============================================================
# 4) SENTETİK - drafting_request_result.html (autoescape + sabit
#    "bu üretim anlamına gelmez" uyarı metni)
# ============================================================

html_result = check(
    "drafting_request_result.html (sentetik)",
    lambda: env.get_template("drafting_request_result.html").render(
        case_id=CASE_ID, saved_at="2026-01-01T00:00:00+00:00", lawyer_input_hash="b" * 64,
        back_url=f"/cases/{CASE_ID}/drafting-request", case_home_url=f"/cases/{CASE_ID}",
    ),
)
check_contains(
    "drafting_request_result.html: dört sabit 'bu anlama gelmez' maddesi mevcut",
    html_result,
    "taslak (draft) ÜRETİLMEDİ", "Drafting Agent veya herhangi bir LLM ÇALIŞTIRILMADI",
    "kimliği doğrulanmış bir avukattan geldiği anlamına GELMEZ",
    "canonical drafting çıktısı (varsa) DEĞİŞMEDİ",
)
check_contains("drafting_request_result.html: hash doğru gömülü", html_result, "b" * 64)

html_result_empty_hash = check(
    "drafting_request_result.html (boş girdi - hash yok)",
    lambda: env.get_template("drafting_request_result.html").render(
        case_id=CASE_ID, saved_at="2026-01-01T00:00:00+00:00", lawyer_input_hash=None,
        back_url=f"/cases/{CASE_ID}/drafting-request", case_home_url=f"/cases/{CASE_ID}",
    ),
)
check_contains(
    "drafting_request_result.html: null hash için sabit açıklama gösteriliyor",
    html_result_empty_hash, "boş girdi - hash yok",
)


print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
