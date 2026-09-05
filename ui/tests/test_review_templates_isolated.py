# ============================================================
# Row 18b - Ham Jinja2 render / autoescape testleri (Layer B inceleme
# kararları şablonları: reviews_list.html, review_detail.html,
# review_result.html). FastAPI'ye İHTİYAÇ DUYMAZ - `ui/services/*`
# katmanını GERÇEK case_0001 verisiyle (mümkün olduğunda) çağırıp
# şablonları doğrudan `jinja2.Environment` ile render eder
# (Starlette'in `Jinja2Templates`'inin kullandığı autoescape=True
# ayarıyla - `test_templates_isolated.py`'nin (Row 18a) AYNI deseni).
#
# Bu dosya, main.py'deki GERÇEK route'ların (`reviews_list`,
# `review_detail_page`, `review_confirm`) her birine geçirdiği
# context anahtarlarını (case_id, rows / case_id, record_id, label,
# record, canonical_hash, allowed_targets, csrf_token,
# confirm_action, back_url / case_id, record_id, label,
# previous_state, new_state, canonical_path, canonical_hash,
# audit_path) BİREBİR aynı şekilde kullanır.
#
# Çalıştırma: python ui/tests/test_review_templates_isolated.py
# ============================================================

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jinja2  # noqa: E402

from ui.services import paths, security  # noqa: E402
from ui.services import review_registry as reviewreg  # noqa: E402

TEMPLATES_DIR = str(REPO_ROOT / "ui" / "templates")

_case_ids = paths.list_case_ids()

if not _case_ids:
    print("Hiç case yok - Row 18b şablon testleri çalıştırılamıyor.")
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


# ============================================================
# 1) reviews_list.html - GERÇEK case_0001 verisiyle (12 review_kind'ın
#    hangi durumda olduğuna bakılmaksızın - "invalid"/"canonical yok"/
#    "kayıt yok"/"N kayıt bekliyor" durumlarından HANGİSİ gerçekleşirse
#    gerçekleşsin şablon hata vermeden render etmeli).
# ============================================================

real_rows = reviewreg.full_case_review_status(CASE_ID)
html = check("reviews_list.html (GERÇEK case_0001 rows)", lambda: env.get_template("reviews_list.html").render(
    case_id=CASE_ID, rows=real_rows,
))
check_contains("reviews_list.html: Onaylar ekranına geri link var", html, f"/cases/{CASE_ID}/approvals")

# --- Sentetik rows: 4 durumun TAMAMINI (invalid / canonical yok /
# kayıt yok / N kayıt bekliyor) tek seferde zorluyor, ayrıca kayıt
# linkinin `row.id_field` ile doğru kurulduğunu doğruluyor.
_synthetic_rows = [
    {"review_kind": "evidence.candidate", "row_no": 12, "label": "Delil Adayları", "kind": "invalid",
     "pending_count": 0, "items": []},
    {"review_kind": "evidence.suggestion", "row_no": 12, "label": "Delil Önerileri", "kind": "reviewable",
     "canonical_exists": False, "pending_count": 0, "items": []},
    {"review_kind": "drafting.section", "row_no": 15, "label": "Taslak Bölümleri", "kind": "reviewable",
     "canonical_exists": True, "pending_count": 0, "items": []},
    {"review_kind": "argument.claim", "row_no": 13, "label": "İddialar", "kind": "reviewable",
     "canonical_exists": True, "pending_count": 1,
     "items": [{"claim_id": "c_sentetik_1", "claim_review_state": "needs_review"}], "id_field": "claim_id"},
]
html = check("reviews_list.html (sentetik - 4 durum)", lambda: env.get_template("reviews_list.html").render(
    case_id=CASE_ID, rows=_synthetic_rows,
))
check_contains("reviews_list.html: 'doğrulanamıyor' (invalid) rozeti render edildi", html, "doğrulanamıyor")
check_contains("reviews_list.html: 'canonical yok' render edildi", html, "canonical yok")
check_contains("reviews_list.html: 'incelenecek kayıt yok' render edildi", html, "incelenecek kayıt yok")
check_contains(
    "reviews_list.html: pending_count>0 satırı hem sayıyı hem doğru kayıt linkini gösteriyor",
    html, "1 kayıt bekliyor",
    f"/cases/{CASE_ID}/reviews/argument.claim/c_sentetik_1",
)


# ============================================================
# 2) review_detail.html - önce GERÇEK bir needs_review kaydı var mı
#    diye bakılır (varsa GERÇEK veriyle render edilir); ayrıca
#    autoescape'i sınayan SENTETİK bir kayıtla da (kayıt içinde
#    "<script>" benzeri bir değer) ayrıca render edilir - hiçbir
#    zaman ham HTML/script olarak sızmamalı.
# ============================================================

_real_reviewable = next(
    (row for row in real_rows if row.get("kind") == "reviewable" and row.get("pending_count", 0) > 0),
    None,
)

# NOT (targeted remediation, 2026-09-05): CSRF token artık BEŞ
# parçaya bağlıdır - case_id + review_kind + record_id + target_state
# + canonical_hash - `allowed_targets`'taki HER hedef için AYRI bir
# token üretilip `csrf_tokens_by_target` HAM SÖZLÜK olarak şablona
# geçirilir (main.py'nin GERÇEK üretim şekliyle BİREBİR AYNI).
#
# SCRIPT-CONTEXT JSON SERIALIZATION HARDENING (2026-09-05): şablon
# artık bunu Jinja'nın KENDİ `|tojson` filtresiyle serileştiriyor
# (elle `json.dumps(...)` + `|safe` DEĞİL) - bu yüzden bu dosya da
# artık `csrf_tokens_by_target_json` diye ÖNCEDEN SERİLEŞTİRİLMİŞ bir
# string ÜRETMİYOR/GEÇİRMİYOR, main.py ile BİREBİR AYNI şekilde HAM
# sözlüğü geçiriyor.

if _real_reviewable:
    _review_kind = _real_reviewable["review_kind"]
    _record_id = _real_reviewable["items"][0][_real_reviewable["id_field"]]
    _found = reviewreg.get_review_record(_review_kind, CASE_ID, _record_id)
    _secret = security.new_csrf_secret()
    _allowed = sorted(reviewreg.get_allowed_targets(_review_kind))
    _tokens_by_target = {
        t: security.make_csrf_token(_secret, CASE_ID, _review_kind, _record_id, t, _found["canonical_hash"])
        for t in _allowed
    }
    _csrf = _tokens_by_target[_allowed[0]]

    html = check("review_detail.html (GERÇEK needs_review kaydı)", lambda: env.get_template("review_detail.html").render(
        case_id=CASE_ID, record_id=_record_id, label=_real_reviewable["label"],
        record=_found["record"], canonical_hash=_found["canonical_hash"],
        allowed_targets=_allowed,
        csrf_tokens_by_target=_tokens_by_target,
        csrf_token=_csrf, confirm_action=f"/cases/{CASE_ID}/reviews/{_review_kind}/{_record_id}/confirm",
        back_url=f"/cases/{CASE_ID}/reviews",
    ))
    check_contains("review_detail.html: csrf_token gizli alanı render edildi", html, 'name="csrf_token"', _csrf)
    check_contains("review_detail.html: expected_hash gizli alanı render edildi", html, 'name="expected_hash"', _found["canonical_hash"])
    check_contains(
        "review_detail.html: her hedef için AYRI bir token Jinja |tojson ile JS haritasına gömülü (doğru anahtar/değer çiftleri)",
        html, *[f'"{t}": "{tok}"' for t, tok in _tokens_by_target.items()],
    )
    check_not_contains(
        "review_detail.html: gömülü JSON HTML-entity-escape edilmiş tırnak (&quot;) İÇERMİYOR (|tojson kullanılıyor, |safe DEĞİL)",
        html, "&quot;",
    )
else:
    print("UYARI: GERÇEK case_0001'de hâlâ needs_review durumunda bir kayıt yok - GERÇEK veriyle review_detail.html testi atlandı.")

# --- Sentetik autoescape testi: kayıt içeriğinde HTML/script benzeri
# değerler VE csrf_token/back_url'de tehlikeli karakterler olsa bile
# ham olarak sızmamalı.
_malicious_record = {
    "claim_id": "c_xss_test",
    "claim_review_state": "needs_review",
    "claim_text": "<script>alert('xss')</script>",
    "attacker_field": "\" onmouseover=\"alert(1)",
}
_synthetic_tokens_by_target = {"confirmed": "dummy_csrf_token_confirmed", "rejected": "dummy_csrf_token_rejected"}
html = check("review_detail.html (sentetik - autoescape/XSS)", lambda: env.get_template("review_detail.html").render(
    case_id=CASE_ID, record_id="c_xss_test", label="İddialar (sentetik)",
    record=_malicious_record, canonical_hash="c" * 64,
    allowed_targets=["confirmed", "rejected"],
    csrf_tokens_by_target=_synthetic_tokens_by_target,
    csrf_token=_synthetic_tokens_by_target["confirmed"],
    confirm_action=f"/cases/{CASE_ID}/reviews/argument.claim/c_xss_test/confirm",
    back_url=f"/cases/{CASE_ID}/reviews",
))
check_not_contains(
    "review_detail.html: kayıt içindeki <script> HAM olarak SIZMIYOR (autoescape çalışıyor)",
    html, "<script>alert('xss')</script>",
)
check_contains(
    "review_detail.html: kayıt içindeki < karakteri HTML-escape edilmiş olarak render edildi",
    html, "&lt;script&gt;",
)
check_contains(
    "review_detail.html: her hedef için AYRI bir token (POZİTİF kontrol - bkz. madde 6) Jinja |tojson ile JS haritasına DOĞRU anahtar/değerle gömülü",
    html, '"confirmed": "dummy_csrf_token_confirmed"', '"rejected": "dummy_csrf_token_rejected"',
)
check_not_contains(
    "review_detail.html: gömülü JSON HTML-entity-escape edilmiş tırnak (&quot;) İÇERMİYOR (|tojson kullanılıyor, |safe DEĞİL)",
    html, "&quot;",
)
check_contains(
    "review_detail.html: select'in onchange'i csrf_token alanını CSRF_TOKENS_BY_TARGET ile günceller",
    html, "CSRF_TOKENS_BY_TARGET[this.value]", 'id="csrf_token"',
)


# ============================================================
# 2b) SCRIPT-CONTEXT JSON SERIALIZATION HARDENING (2026-09-05) -
#     NEGATİF testler: `csrf_tokens_by_target`'ın (hedef ADI veya
#     token DEĞERİ - ikisi de) script-KIRAN karakterler ("</script>",
#     "<", ">", "&", çift/tek tırnak) İÇERSE BİLE, Jinja'nın KENDİ
#     `|tojson` filtresi bunları HER ZAMAN Unicode kaçış dizilerine
#     çevirir - bu değerler ASLA ham/ÇALIŞTIRILABİLİR markup olarak
#     görünmemeli (özellikle "</script>" - bu, <script> bloğundan
#     KAÇIP ardından gelen bir <script> etiketini ÇALIŞTIRABİLİRDİ).
#     Bu, sunucunun KENDİSİ her zaman güvenli hex HMAC token'ları
#     ürettiği gerçeğine GÜVENMEYEN, şablonun KENDİ savunma
#     derinliğidir.
# ============================================================

_xss_probe_value = "</script><script>alert(String.fromCharCode(88,83,83))</script>\"'&<>"
_xss_tokens_by_target = {
    "confirmed": _xss_probe_value,
    "rejected": "dummy_csrf_token_rejected",
}
html = check(
    "review_detail.html (NEGATİF - CSRF token DEĞERİ script-kıran karakterler içeriyor)",
    lambda: env.get_template("review_detail.html").render(
        case_id=CASE_ID, record_id="c_xss_probe", label="İddialar (script-context sertleştirme probu)",
        record={"claim_id": "c_xss_probe", "claim_review_state": "needs_review"},
        canonical_hash="d" * 64,
        allowed_targets=["confirmed", "rejected"],
        csrf_tokens_by_target=_xss_tokens_by_target,
        csrf_token=_xss_probe_value,
        confirm_action=f"/cases/{CASE_ID}/reviews/argument.claim/c_xss_probe/confirm",
        back_url=f"/cases/{CASE_ID}/reviews",
    ),
)
check_not_contains(
    "review_detail.html: script-kıran '</script>' dizisi HAM/ÇALIŞTIRILABİLİR olarak HİÇBİR YERDE görünmüyor",
    html, "</script><script>alert(String.fromCharCode(88,83,83))</script>",
)
check_not_contains(
    "review_detail.html: gömülü <script> bloğunun İÇİNDE ham '</script>' dizisi YOK (blok erken KAPANMAZ)",
    html, "CSRF_TOKENS_BY_TARGET = {\"confirmed\": \"</script>",
)
check_contains(
    "review_detail.html: |tojson '<' ve '>' karakterlerini \\u003c / \\u003e olarak Unicode-kaçışlı gömüyor ('</script>' KAÇIŞI dahil)",
    html, "\\u003c/script\\u003e\\u003cscript\\u003e",
)
check_contains(
    "review_detail.html: |tojson '&' karakterini \\u0026 olarak Unicode-kaçışlı gömüyor",
    html, "\\u0026",
)
check_contains(
    "review_detail.html: |tojson tek tırnak (') karakterini \\u0027 olarak Unicode-kaçışlı gömüyor",
    html, "\\u0027",
)
check_not_contains(
    "review_detail.html: ham (kaçışsız) '<script>alert' dizisi hiçbir yerde YOK",
    html, "<script>alert(String.fromCharCode",
)


# ============================================================
# 3) review_result.html - başarı ekranı; repo-göreli path'ler
#    gösterilir, ham mutlak filesystem path'i ASLA sızmaz; audit_path
#    None olduğunda "bulunamadı" render edilir.
# ============================================================

html = check("review_result.html (audit_path VAR)", lambda: env.get_template("review_result.html").render(
    case_id=CASE_ID, record_id="c1", label="İddialar",
    previous_state="needs_review", new_state="confirmed",
    canonical_path=paths.to_repo_relative(paths.CASES_DIR / CASE_ID / "arguments" / "arguments.json"),
    canonical_hash="d" * 64,
    audit_path=paths.to_repo_relative(
        paths.CASES_DIR / CASE_ID / "arguments" / "reviews" / "argument_reviews" / "x.review.json"
    ),
))
check_contains("review_result.html: durum geçişi (previous_state -> new_state) render edildi", html, "needs_review", "confirmed")
check_not_contains(
    "review_result.html: ham mutlak dosya sistemi path'i SIZMIYOR",
    html, str(paths.BASE_DIR),
)

html = check("review_result.html (audit_path YOK)", lambda: env.get_template("review_result.html").render(
    case_id=CASE_ID, record_id="c1", label="İddialar",
    previous_state="needs_review", new_state="rejected",
    canonical_path="x/arguments.json", canonical_hash="e" * 64,
    audit_path=None,
))
check_contains("review_result.html (audit_path YOK): 'bulunamadı' render edildi", html, "bulunamadı")


# ============================================================
# 4) error.html - Row 18b'nin domain-ret yolu (`_domain_error_page`,
#    code="REVIEW_DOMAIN_REJECTED").
#
#    FINAL DOMAIN-ERROR REDACTION REMEDIATION (2026-09-05): önceki
#    turda main.py, bu yola GERÇEK domain exception'ının KENDİ
#    mesajını (`str(error)`) geçiriyordu - bu VARSAYIM (mesajın HER
#    ZAMAN path/traceback-free olduğu) LOCK-READINESS incelemesinde
#    YANLIŞ çıktı (5 backend'in TAMAMI aynı domain sınıflarıyla
#    MUTLAK path içeren bir mesaj fırlatabiliyordu). main.py ARTIK bu
#    yola ASLA `str(error)` geçirmiyor - yalnız
#    `_ERROR_MESSAGES["REVIEW_DOMAIN_REJECTED"]` SABİT metnini
#    (aşağıdaki placeholder ile TEMSİL EDİLİR - main.py'nin GERÇEK
#    dize kopyası burada TUTULMAZ, tek kaynak main.py'dedir) - bu
#    yüzden bu şablon artık genel diğer kodlarla (aşağıdaki döngü)
#    AYNI GENERIC-MESAJ deseniyle test edilir, ARTIK "gerçek domain
#    mesajı" ayrı bir senaryo DEĞİLDİR (main.py katmanında zaten HİÇ
#    ULAŞMIYOR - bkz. `test_review_routes.py::T15`, ki main.py'nin
#    KENDİSİNİ uçtan uca sınayan TEK yer orasıdır).
#
#    Şablonun KENDİSİ (error.html) hâlâ autoescape=True ile render
#    edilir - aşağıdaki ayrı XSS-denemesi testi, şablon katmanının
#    KENDİSİNİN de (main.py'nin redaksiyonundan BAĞIMSIZ, savunma
#    derinliği olarak) hiçbir zaman ham `<script>` geçirmediğini
#    kanıtlar.
# ============================================================

html = check("error.html (REVIEW_DOMAIN_REJECTED, sentetik XSS denemesi - savunma derinliği)", lambda: env.get_template("error.html").render(
    title="İnceleme reddedildi",
    message="<script>alert('domain-xss')</script>",
    code="REVIEW_DOMAIN_REJECTED",
    back_url=f"/cases/{CASE_ID}/reviews",
))
check_not_contains(
    "error.html: <script> HAM olarak SIZMIYOR (autoescape, savunma derinliği - main.py ARTIK bu şablona hiçbir zaman ham metin geçirmiyor)",
    html, "<script>alert('domain-xss')</script>",
)
check_not_contains(
    "error.html: ham exception/traceback metni İÇERMİYOR",
    html, "Traceback", "raise ", "  File \"",
)

for code in ("REVIEW_DOMAIN_REJECTED", "REVIEW_STALE_VIEW", "REVIEW_RECORD_NOT_FOUND", "REVIEW_NOTE_INVALID", "REVIEW_FAMILY_INVALID", "UNKNOWN_REVIEW_KIND", "REVIEW_TRANSITION_FAILED"):
    html = check(f"error.html ({code}, generic mesaj)", lambda code=code: env.get_template("error.html").render(
        title="Hata", message=f"[{code} için sabit generic metin - main.py._ERROR_MESSAGES]",
        code=code, back_url=f"/cases/{CASE_ID}/reviews",
    ))
    check_contains(f"error.html: {code} kodu render edildi", html, code)


print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
