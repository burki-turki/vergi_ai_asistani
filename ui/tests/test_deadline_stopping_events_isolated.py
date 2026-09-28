# ============================================================
# PILOT READINESS ADIM 7 / SLICE 1 - STOPPING-EVENT ATTESTATION GATE
# src/deadline_calculator.py + src/deadline_engine.py ISOLATED TESTS.
#
# KAPSAM (dar): bu modül YALNIZ fail-closed kapıyı test eder. Bu
# slice'ta hiçbir hukuki süre aritmetiği (tarhiyat sonrası uzlaşmanın
# 15 günlük tabanı, İYUK m.11'in kalan süresi/zımni reddi, VUK
# m.35/376'nın yeni başlangıcı, pişmanlık ihlali, takdir komisyonu)
# MODELLENMEZ - kapı yalnız DURDURUR.
#
# DAR, EXACT İDDİA (abartılmaz): case.json çapraz kontrolü bir
# DEDEKTÖR DEĞİLDİR. Yalnız `action_category` sözlüğünün ifade
# edebildiği İKİ değeri (`settlement`, `correction_complaint`) görür.
# VUK m.35, usulsüz tebligat, VUK m.376, pişmanlık ihlali, takdir
# komisyonu eksikliği ve genel İYUK m.11 başvurusu `action_category`
# veya `event_type` sözlüklerinde HİÇ TEMSİL EDİLMEZ; bu altı hâl
# tamamen avukatın `none` beyanına dayanır. Bölüm K bunu AÇIKÇA
# kanıtlar (aşırı-iddiayı önleyen negatif test).
#
# Bu dosya SALT-OKUNURDUR: gerçek `data/` ağacına yazılmaz (her
# senaryo kendi `tempfile` kopyasında çalışır, `deadline_validator.
# CASES_DIR`/`deadline_engine.CASES_DIR` geçici olarak yönlendirilir),
# PostgreSQL yok, ağ yok, gerçek müvekkil verisi yok, LLM yok.
#
# Run: python ui/tests/test_deadline_stopping_events_isolated.py
# ============================================================

import ast
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import deadline_calculator as dc                       # noqa: E402
import deadline_engine                                 # noqa: E402
import deadline_validator                              # noqa: E402

REAL_DATA_DIR = REPO_ROOT / "data"
REAL_CASE_0001 = REAL_DATA_DIR / "cases" / "case_0001"
CASE_ID = "case_0001"
ANCHOR_EVENT_ID = "timeline_event_003"

VALID_REF = "AV-BEYAN-2026-001"

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


def _snapshot_data_tree():
    out = {}
    for path in REAL_DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(REAL_DATA_DIR))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            except OSError:
                out[str(path.relative_to(REAL_DATA_DIR))] = "<unreadable>"
    return out


RULE = dc.load_production_rule()
PRODUCTION_CALENDAR = dc.load_holiday_calendar()

SELECTION = {
    "selection_state": "selected",
    "calculation_allowed": True,
    "selected_rule": RULE,
}


def _anchor(date_iso, verification_state="verified", precision="exact"):
    return {
        "event_id": ANCHOR_EVENT_ID,
        "event_type": "notification_date",
        "date": date_iso,
        "date_precision": precision,
        "verification_state": verification_state,
        "confidence": 0.95,
    }


class CaseSandbox:
    """Gerçek `case_0001`'in TEK KULLANIMLIK kopyası; gerçek `data/`
    ağacına ASLA yazılmaz. `action_category` listesi istenirse
    değiştirilebilir (çelişki testleri için)."""

    def __init__(self, action_categories=None):
        self.action_categories = action_categories
        self.tmp = None
        self._orig_validator = None
        self._orig_engine = None

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="stopev_"))
        cases = self.tmp / "cases"
        cases.mkdir(parents=True)
        self.case_dir = cases / CASE_ID
        shutil.copytree(REAL_CASE_0001, self.case_dir)

        if self.action_categories is not None:
            case_json = self.case_dir / "case.json"
            data = json.loads(case_json.read_text(encoding="utf-8"))
            actions = []
            for i, cat in enumerate(self.action_categories, 1):
                actions.append({
                    "action_id": f"action_test_{i:03d}",
                    "action_category": cat,
                    "action_type": "sentetik test kaydı",
                    "issuing_authority": "Test Vergi Dairesi",
                    "action_date": "2026-02-05",
                    "notification_date": "2026-02-10",
                    "source_document_id": None,
                    "verification_state": "unverified",
                    "notes": None,
                })
            data["administrative_actions"] = actions
            case_json.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        self._orig_validator = deadline_validator.CASES_DIR
        self._orig_engine = deadline_engine.CASES_DIR
        deadline_validator.CASES_DIR = cases
        deadline_engine.CASES_DIR = cases
        return self

    def __exit__(self, *exc):
        deadline_validator.CASES_DIR = self._orig_validator
        deadline_engine.CASES_DIR = self._orig_engine
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _record(anchor_event=None, **kwargs):
    """`build_deadline_record()` sarmalayıcısı - çağıranın açıkça
    geçmediği stopping parametreleri KASITLI olarak geçilmez (default
    davranışın test edilebilmesi için)."""
    return dc.build_deadline_record(
        case_id=CASE_ID,
        anchor_event=anchor_event if anchor_event is not None else _anchor("2026-02-10"),
        selection=SELECTION,
        ruleset_path=dc.DEFAULT_RULESET_PATH,
        holiday_calendar=PRODUCTION_CALENDAR,
        judicial_recess_applicable=True,
        **kwargs,
    )


# ================================================================
# A) KARAR TABLOSU - altı dal, exact reason literalleri
# ================================================================

def test_a_decision_table():
    with CaseSandbox():
        # A1 - none + geçerli ref + çelişki yok -> DEVAM
        r = _record(stopping_event_status="none",
                    stopping_event_attestation_ref=VALID_REF)
        check(
            "A1 none + geçerli ref + çelişki yok -> hesaplamaya DEVAM (calculated)",
            r["calculation_state"] == "calculated"
            and r["calculated_deadline"] == "2026-03-12",
            r,
        )

        # A2 - none + ref yok
        r = _record(stopping_event_status="none")
        check(
            "A2 none + ref YOK -> needs_review / "
            "stopping_event_none_requires_attestation_ref",
            r["calculation_state"] == "needs_review"
            and r["calculated_deadline"] is None
            and r["requires_human_review"] is True
            and r["notes"] == "stopping_event_none_requires_attestation_ref",
            r,
        )

        # A4 - present
        r = _record(stopping_event_status="present",
                    stopping_event_attestation_ref=VALID_REF)
        check(
            "A4 present -> needs_review / "
            "stopping_event_present_requires_lawyer_review",
            r["calculation_state"] == "needs_review"
            and r["calculated_deadline"] is None
            and r["requires_human_review"] is True
            and r["notes"] == "stopping_event_present_requires_lawyer_review",
            r,
        )

        # A5a - explicit unknown
        r = _record(stopping_event_status="unknown",
                    stopping_event_attestation_ref=VALID_REF)
        check(
            "A5a explicit unknown -> needs_review / stopping_event_status_unknown",
            r["calculation_state"] == "needs_review"
            and r["calculated_deadline"] is None
            and r["requires_human_review"] is True
            and r["notes"] == "stopping_event_status_unknown",
            r,
        )

        # A5b - parametre HİÇ verilmedi (C maddesi)
        r = _record()
        check(
            "A5b/C parametre HİÇ verilmedi (default) -> needs_review / "
            "stopping_event_status_unknown - default ASLA 'none' DEĞİL",
            r["calculation_state"] == "needs_review"
            and r["calculated_deadline"] is None
            and r["requires_human_review"] is True
            and r["notes"] == "stopping_event_status_unknown",
            r,
        )

        # A5c - tanınmayan değer (Python seviyesinde fail-closed)
        r = _record(stopping_event_status="NONE",
                    stopping_event_attestation_ref=VALID_REF)
        check(
            "A5c tanınmayan status ('NONE' - büyük harf) -> fail-closed unknown, "
            "sessizce 'none' sayılMAZ",
            r["calculation_state"] == "needs_review"
            and r["notes"] == "stopping_event_status_unknown",
            r,
        )

    # A3 - çelişki (kendi sandbox'ı)
    with CaseSandbox(action_categories=["settlement"]):
        r = _record(stopping_event_status="none",
                    stopping_event_attestation_ref=VALID_REF)
        check(
            "A3 none + settlement kaydı -> needs_review / "
            "stopping_event_attestation_conflicts_with_case_record",
            r["calculation_state"] == "needs_review"
            and r["calculated_deadline"] is None
            and r["requires_human_review"] is True
            and r["notes"] == "stopping_event_attestation_conflicts_with_case_record",
            r,
        )


# ================================================================
# B) 14 AVUKAT-ONAYLI ALTIN ÖRNEK - build_deadline_record ÜZERİNDEN
#    (mevcut test_deadline_lawyer_golden_examples_isolated.py
#    DEĞİŞTİRİLMEDEN; o dosya calculate_rule_deadline'ı test eder)
# ================================================================

GOLDEN = [
    ("S01", "2026-02-10", "calculated", "2026-03-12"),
    ("S02", "2026-01-15", "calculated", "2026-02-16"),
    ("S03", "2026-01-16", "calculated", "2026-02-16"),
    ("S04", "2026-12-02", "calculated", "2027-01-04"),
    ("S05", "2026-09-28", "needs_review", None),
    ("S06", "2026-09-29", "calculated", "2026-10-30"),
    ("S07", "2026-06-19", "calculated", "2026-09-07"),
    ("S08", "2026-06-20", "calculated", "2026-09-07"),
    ("S09", "2026-08-01", "calculated", "2026-09-07"),
    ("S10", "2026-08-02", "calculated", "2026-09-01"),
    ("S11", "2030-07-01", "calculated", "2030-09-09"),
    ("S12", "2028-01-30", "calculated", "2028-02-29"),
    ("S13", "2032-12-03", "calculated", "2033-01-05"),
    ("A-1", "2029-03-22", "calculated", "2029-04-30"),
]


def test_b_golden_regression():
    with CaseSandbox():
        for case_id, anchor, exp_state, exp_date in GOLDEN:
            r = _record(
                anchor_event=_anchor(anchor),
                stopping_event_status="none",
                stopping_event_attestation_ref=VALID_REF,
            )
            ok = (r["calculation_state"] == exp_state
                  and r["calculated_deadline"] == exp_date)
            check(
                "B %s: build_deadline_record + status=none + geçerli ref -> %s"
                % (case_id, exp_date if exp_date else exp_state),
                ok,
                "BEKLENEN state=%r date=%r | GÖZLENEN state=%r date=%r notes=%r"
                % (exp_state, exp_date, r["calculation_state"],
                   r["calculated_deadline"], str(r.get("notes"))[:120]),
            )

        # S05'in engellenme SEBEBİ stopping kapısı DEĞİL, yarım gün
        # politikasıdır - kapı S05'i "ele geçirmiş" olmamalıdır.
        r = _record(
            anchor_event=_anchor("2026-09-28"),
            stopping_event_status="none",
            stopping_event_attestation_ref=VALID_REF,
        )
        check(
            "B S05 ayrımı: engel yarım gün politikasından gelir, stopping "
            "kapısından DEĞİL (notes stopping_event_* literali TAŞIMAZ)",
            not str(r.get("notes") or "").startswith("stopping_event_"),
            r.get("notes"),
        )


# ================================================================
# D) KAPI SIRASI - doğrulanmamış anchor kapıya HİÇ ulaşmaz
# ================================================================

def test_d_gate_ordering():
    with CaseSandbox():
        r = _record(anchor_event=_anchor("2026-02-10", verification_state="unverified"))
        check(
            "D doğrulanmamış anchor + stopping parametresi YOK -> "
            "blocked_unverified_anchor (stopping kapısı BASTIRMAZ)",
            r["calculation_state"] == "blocked_unverified_anchor",
            r,
        )
        r = _record(
            anchor_event=_anchor("2026-02-10", verification_state="unverified"),
            stopping_event_status="present",
        )
        check(
            "D doğrulanmamış anchor + status=present -> yine "
            "blocked_unverified_anchor (sıra korunur)",
            r["calculation_state"] == "blocked_unverified_anchor",
            r,
        )
        r = _record(
            anchor_event=_anchor("2026-02-10", precision="month"),
            stopping_event_status="none",
            stopping_event_attestation_ref=VALID_REF,
        )
        check(
            "D date_precision != exact -> stopping kapısından ÖNCEKİ "
            "needs_review korunur (notes stopping_event_* DEĞİL)",
            r["calculation_state"] == "needs_review"
            and not str(r.get("notes") or "").startswith("stopping_event_"),
            r,
        )


# ================================================================
# E) ÇELİŞKİ KONTROLLERİ - yalnız iki kategori engeller
# ================================================================

def test_e_conflict_matrix():
    matrix = [
        (["settlement"], True, "settlement"),
        (["correction_complaint"], True, "correction_complaint"),
        (["audit"], False, "audit"),
        (["assessment"], False, "assessment"),
        (["assessment_and_penalty", "audit"], False, "gerçek case_0001 kategorileri"),
        (["audit", "settlement"], True, "karışık - biri bile yeterli"),
        ([], False, "hiç administrative_action yok"),
    ]
    for categories, should_block, label in matrix:
        with CaseSandbox(action_categories=categories):
            r = _record(stopping_event_status="none",
                        stopping_event_attestation_ref=VALID_REF)
            blocked = (
                r["calculation_state"] == "needs_review"
                and r.get("notes") ==
                "stopping_event_attestation_conflicts_with_case_record"
            )
            check(
                "E %s -> %s" % (label, "ENGELLE" if should_block else "DEVAM"),
                blocked is should_block,
                r,
            )


# ================================================================
# F) attestation_ref SINIRLARI
# ================================================================

def test_f_attestation_ref_bounds():
    invalid = [
        (None, "None"),
        ("", "boş string"),
        ("   ", "yalnız whitespace"),
        (123, "non-str int"),
        (["ref"], "non-str list"),
        (True, "non-str bool"),
        ({"a": 1}, "non-str dict"),
        ("x" * 201, "201 karakter"),
        ("a" + chr(10) + "b", "LF"),
        ("a" + chr(13) + "b", "CR"),
        ("a" + chr(9) + "b", "TAB"),
        ("a" + chr(0) + "b", "NUL kontrol karakteri"),
    ]
    with CaseSandbox():
        for value, label in invalid:
            r = _record(stopping_event_status="none",
                        stopping_event_attestation_ref=value)
            check(
                "F geçersiz ref (%s) -> fail-closed / "
                "stopping_event_none_requires_attestation_ref" % label,
                r["calculation_state"] == "needs_review"
                and r["notes"] == "stopping_event_none_requires_attestation_ref",
                r,
            )
        for value, label in [("x", "1 karakter"), ("y" * 200, "200 karakter"),
                             ("AV/2026-17 (ıİşğüöÇ)", "Türkçe + noktalama")]:
            r = _record(stopping_event_status="none",
                        stopping_event_attestation_ref=value)
            check(
                "F geçerli ref (%s) -> hesaplamaya DEVAM" % label,
                r["calculation_state"] == "calculated",
                r,
            )

    check(
        "F non-str ref hiçbir exception üretmez (saf fonksiyon fail-closed "
        "False döner)",
        dc.is_valid_stopping_event_attestation_ref(object()) is False
        and dc.is_valid_stopping_event_attestation_ref(None) is False,
    )


# ================================================================
# G) AUDIT KALICILIĞI - ham status/ref generation audit'inde
# ================================================================

def _write_and_read_audit(status, ref, *, analysis):
    """`write_pending()`'i TAM mutation-binding ile çağırır ve yazılan
    generation audit kaydını okur."""
    result = deadline_engine.write_pending(
        case_id=CASE_ID,
        analysis=analysis,
        anchor_event_id=ANCHOR_EVENT_ID,
        input_digest="d" * 64,
        generation_parameters_digest="g" * 64,
        mutation_idempotency_key="idk-stopev",
        mutation_resource_key=f"case:{CASE_ID}",
        mutation_actor_ref="7",
        attempt=1,
        stopping_event_status=status,
        stopping_event_attestation_ref=ref,
    )
    audit_path = Path(result["audit_path"])
    return json.loads(audit_path.read_text(encoding="utf-8"))


def test_g_audit_persistence():
    cases = [
        ("none", VALID_REF, "none-valid"),
        ("none", None, "none-invalid (ref yok)"),
        ("present", VALID_REF, "present"),
        ("unknown", None, "unknown"),
        (None, None, "parametre hiç verilmedi"),
    ]
    for status, ref, label in cases:
        with CaseSandbox() as box:
            analysis = deadline_engine.build_deadline_engine_output(
                case_id=CASE_ID,
                anchor_event_id=ANCHOR_EVENT_ID,
                ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
                stopping_event_status=status,
                stopping_event_attestation_ref=ref,
            )
            audit = _write_and_read_audit(status, ref, analysis=analysis)
            check(
                "G audit (%s): iki ham alan MEVCUT ve girdiyle BİREBİR eşit" % label,
                "stopping_event_status" in audit
                and "stopping_event_attestation_ref" in audit
                and audit["stopping_event_status"] == status
                and audit["stopping_event_attestation_ref"] == ref,
                {k: audit.get(k) for k in
                 ("stopping_event_status", "stopping_event_attestation_ref")},
            )
            del box

    # none-conflict dalı
    with CaseSandbox(action_categories=["settlement"]):
        analysis = deadline_engine.build_deadline_engine_output(
            case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
            ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
            stopping_event_status="none",
            stopping_event_attestation_ref=VALID_REF,
        )
        audit = _write_and_read_audit("none", VALID_REF, analysis=analysis)
        check(
            "G audit (none-conflict): ham alanlar needs_review dalında da "
            "KAYBOLMAZ",
            audit["stopping_event_status"] == "none"
            and audit["stopping_event_attestation_ref"] == VALID_REF,
            audit,
        )

    # present/unknown ile ref verilmişse ref SESSİZCE SİLİNMEZ
    with CaseSandbox():
        analysis = deadline_engine.build_deadline_engine_output(
            case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
            ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
            stopping_event_status="present",
            stopping_event_attestation_ref=VALID_REF,
        )
        audit = _write_and_read_audit("present", VALID_REF, analysis=analysis)
        check(
            "G audit: present + ref -> ref SESSİZCE SİLİNMEZ, verbatim saklanır",
            audit["stopping_event_attestation_ref"] == VALID_REF,
            audit,
        )

    # non-str ref: JSON serialization KIRILMAMALI
    with CaseSandbox():
        analysis = deadline_engine.build_deadline_engine_output(
            case_id=CASE_ID, anchor_event_id=ANCHOR_EVENT_ID,
            ruleset_path=deadline_engine.DEFAULT_RULESET_PATH,
            stopping_event_status="none",
            stopping_event_attestation_ref=123,
        )
        try:
            audit = _write_and_read_audit("none", 123, analysis=analysis)
            ok = audit["stopping_event_attestation_ref"] == 123
            detail = audit
        except Exception as exc:                       # noqa: BLE001
            ok = False
            detail = f"{type(exc).__name__}: {exc}"
        check(
            "G audit: non-str ref (int) audit yazımını/JSON serialization'ı "
            "KIRMAZ, fail-closed sonuç korunur",
            ok,
            detail,
        )
        # DÜRÜST NOT: `build_deadline_engine_output()` GERÇEK `case_0001`
        # timeline'ını kullanır ve oradaki `timeline_event_003`
        # `verification_state="unverified"`tir. Bu yüzden engine yolu
        # stopping kapısına HİÇ ULAŞMADAN, daha ÖNCEKİ
        # `blocked_unverified_anchor` kapısında durur - bu, kapı
        # SIRASININ (D maddesi) engine seviyesinde de doğru olduğunun
        # ek kanıtıdır. Bu yüzden burada stopping-literali DEĞİL,
        # yalnız FAIL-CLOSED sonuç assert edilir.
        first = analysis["deadlines"][0]
        check(
            "G non-str ref ile üretilen analiz yine fail-closed "
            "(calculated_deadline None, requires_human_review True)",
            first["calculated_deadline"] is None
            and first["requires_human_review"] is True
            and first["calculation_state"] != "calculated",
            first,
        )
        check(
            "G engine yolu gerçek case_0001'in unverified anchor'ı nedeniyle "
            "stopping kapısından ÖNCE durur (sıra kanıtı)",
            first["calculation_state"] == "blocked_unverified_anchor",
            first["calculation_state"],
        )


# ================================================================
# I) KALICI AST BYPASS TESTİ
# ================================================================

def test_i_no_production_bypass():
    tree = ast.parse(io.open(SRC_DIR / "deadline_calculator.py",
                             encoding="utf-8").read())
    funcs = sorted(
        (n.lineno, n.end_lineno, n.name)
        for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
    )

    def owner(line):
        found = None
        for lo, hi, name in funcs:
            if lo <= line <= hi:
                found = name
        return found

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name == "calculate_rule_deadline":
                own = owner(node.lineno)
                if own not in ("build_deadline_record", "run_self_test"):
                    offenders.append((node.lineno, own))
    check(
        "I deadline_calculator.py: calculate_rule_deadline YALNIZ "
        "build_deadline_record ve run_self_test içinden çağrılıyor "
        "(üretimde kapı atlanamaz)",
        not offenders,
        offenders,
    )

    external = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        if path.name == "deadline_calculator.py":
            continue
        try:
            t = ast.parse(io.open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for node in ast.walk(t):
            if isinstance(node, ast.Call):
                name = (getattr(node.func, "attr", None)
                        or getattr(node.func, "id", None))
                if name == "calculate_rule_deadline":
                    external.append((path.name, node.lineno))
    check(
        "I src/** içinde deadline_calculator.py DIŞINDA hiçbir "
        "calculate_rule_deadline çağrısı YOK",
        not external,
        external,
    )

    analysis_callers = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        try:
            t = ast.parse(io.open(path, encoding="utf-8").read())
        except SyntaxError:
            continue
        for node in ast.walk(t):
            if isinstance(node, ast.Call):
                name = (getattr(node.func, "attr", None)
                        or getattr(node.func, "id", None))
                if name == "build_case_deadline_analysis":
                    analysis_callers.append((path.name, node.lineno))
    check(
        "I build_case_deadline_analysis src/** içinde TAM 3 yerden çağrılıyor "
        "(engine üretim yolu + run_self_test + salt-okunur main) - hepsi "
        "build_deadline_record choke point'inden geçer",
        len(analysis_callers) == 3,
        analysis_callers,
    )


# ================================================================
# K) AŞIRI-İDDİA ÖNLEYİCİ NEGATİF TEST
# ================================================================

def test_k_cross_check_is_not_a_detector():
    # VUK m.35 / usulsüz tebligat / VUK m.376 / pişmanlık / takdir
    # komisyonu / genel İYUK m.11 -> `action_category` sözlüğünde
    # KARŞILIĞI YOK. Bunlar `other`/`notification`/`payment_order` gibi
    # kategorilere düşer ve çapraz kontrol tarafından YAKALANMAZ.
    unrepresented = ["other", "notification", "payment_order", "collection",
                     "refund", "audit", "assessment", "penalty"]
    with CaseSandbox(action_categories=unrepresented):
        r = _record(stopping_event_status="none",
                    stopping_event_attestation_ref=VALID_REF)
        check(
            "K çapraz kontrol DEDEKTÖR DEĞİLDİR: L1/L3/L4/L5/L6/L7'yi temsil "
            "edebilecek 8 kategori YAKALANMAZ - bu hâller tamamen avukatın "
            "'none' beyanına dayanır (disclosure, kusur değil)",
            r["calculation_state"] == "calculated",
            r,
        )
    check(
        "K çapraz kontrolün gördüğü kategori kümesi EXACT olarak iki değerdir",
        dc.STOPPING_EVENT_CONFLICT_ACTION_CATEGORIES
        == frozenset({"settlement", "correction_complaint"}),
        dc.STOPPING_EVENT_CONFLICT_ACTION_CATEGORIES,
    )


# ================================================================
# SABİT LİTERAL PİNLERİ
# ================================================================

def test_reason_literals_pinned():
    expected = {
        "STOPPING_EVENT_REASON_UNKNOWN": "stopping_event_status_unknown",
        "STOPPING_EVENT_REASON_PRESENT":
            "stopping_event_present_requires_lawyer_review",
        "STOPPING_EVENT_REASON_MISSING_REF":
            "stopping_event_none_requires_attestation_ref",
        "STOPPING_EVENT_REASON_CONFLICT":
            "stopping_event_attestation_conflicts_with_case_record",
    }
    for name, literal in expected.items():
        check(
            "LITERAL %s == %r" % (name, literal),
            getattr(dc, name) == literal,
            getattr(dc, name, "<yok>"),
        )
    check(
        "LITERAL status evreni exact ('none','present','unknown')",
        dc.STOPPING_EVENT_STATUS_VALUES == ("none", "present", "unknown"),
        dc.STOPPING_EVENT_STATUS_VALUES,
    )


# ================================================================
# J) DATA-TREE INVARIANCE
# ================================================================

# ================================================================
# L) ADIM 7 / SLICE 2 - CANONICAL ALANLAR: 12 DURUM
#
# Slice 1 iki alanı YALNIZ kapı girdisi ve generation-audit alanı
# olarak taşıyordu; `base_record` onları DÜŞÜRÜYORDU. Slice 2 onları
# canonical deadline kaydına yazar. Aşağıdaki tablo düzeltilmiş
# sözleşmenin 12 durumunu exact olarak pinler.
#
# KRİTİK (satır 1): stopping gate'ini GEÇMEK bir `calculated`
# GARANTİSİ DEĞİLDİR - kapı yalnız KENDİ engelini kaldırır; sonuç
# downstream zincir (hafta sonu/resmî tatil/adli tatil/mali tatil,
# takvim kapsamı, S05 yarım-gün politikası) tarafından belirlenir.
# ================================================================

def test_l_canonical_fields_12_states():

    def rec(**kw):
        with CaseSandbox():
            return _record(**kw)

    # --- 1: none + geçerli ref + çelişki yok -> gate GEÇİLİR ---
    r1 = rec(
        stopping_event_status="none",
        stopping_event_attestation_ref=VALID_REF,
    )
    check(
        "L1 none+geçerli ref: canonical status='none', ref VERBATIM",
        r1["stopping_event_status"] == "none"
        and r1["stopping_event_attestation_ref"] == VALID_REF,
        r1,
    )
    check(
        "L1b none+geçerli ref: stopping-event kapısı GEÇİLDİ (notes artık bir "
        "stopping reason literali DEĞİL) - ama bu bir 'calculated' GARANTİSİ DEĞİLDİR; "
        "sonuç downstream zincire aittir",
        r1["notes"] not in (
            dc.STOPPING_EVENT_REASON_UNKNOWN,
            dc.STOPPING_EVENT_REASON_PRESENT,
            dc.STOPPING_EVENT_REASON_MISSING_REF,
            dc.STOPPING_EVENT_REASON_CONFLICT,
        ),
        r1.get("notes"),
    )
    check(
        "L1c none+geçerli ref: calculation_state downstream mantığın sonucudur "
        "(şemanın tanıdığı bir değer; 'calculated' ZORUNLU DEĞİL)",
        r1["calculation_state"] in (
            "calculated", "needs_review", "blocked_unverified_anchor",
            "blocked_missing_rule", "blocked_ambiguous_rule", "not_applicable",
        ),
        r1["calculation_state"],
    )

    # --- 2/3/4: none + ref yok / geçersiz / non-str ---
    for label, ref in (
        ("L2 none+ref YOK", None),
        ("L3 none+geçersiz string ref", "   "),
        ("L4 none+non-str ref", 12345),
    ):
        r = rec(
            stopping_event_status="none",
            stopping_event_attestation_ref=ref,
        )
        check(
            f"{label} -> needs_review + canonical ref null + sabit reason",
            r["calculation_state"] == "needs_review"
            and r["calculated_deadline"] is None
            and r["requires_human_review"] is True
            and r["stopping_event_status"] == "none"
            and r["stopping_event_attestation_ref"] is None
            and r["notes"] == dc.STOPPING_EVENT_REASON_MISSING_REF,
            r,
        )

    # --- 5: none + settlement çelişkisi -> ref KORUNUR ---
    with CaseSandbox(action_categories=["settlement"]):
        r5 = _record(
            stopping_event_status="none",
            stopping_event_attestation_ref=VALID_REF,
        )
    check(
        "L5 none+çelişki -> conflict reason, ref KORUNUR (gerçekten verilmiş bir beyandır)",
        r5["calculation_state"] == "needs_review"
        and r5["stopping_event_status"] == "none"
        and r5["stopping_event_attestation_ref"] == VALID_REF
        and r5["notes"] == dc.STOPPING_EVENT_REASON_CONFLICT,
        r5,
    )

    # --- 6/7/8: present ---
    r6 = rec(stopping_event_status="present")
    check(
        "L6 present+ref YOK -> needs_review, status='present', ref null",
        r6["calculation_state"] == "needs_review"
        and r6["calculated_deadline"] is None
        and r6["stopping_event_status"] == "present"
        and r6["stopping_event_attestation_ref"] is None
        and r6["notes"] == dc.STOPPING_EVENT_REASON_PRESENT,
        r6,
    )
    r7 = rec(
        stopping_event_status="present",
        stopping_event_attestation_ref=VALID_REF,
    )
    check(
        "L7 present+geçerli ref -> ref VERBATIM korunur (status'tan BAĞIMSIZ)",
        r7["stopping_event_status"] == "present"
        and r7["stopping_event_attestation_ref"] == VALID_REF
        and r7["notes"] == dc.STOPPING_EVENT_REASON_PRESENT,
        r7,
    )
    r8 = rec(
        stopping_event_status="present",
        stopping_event_attestation_ref=object(),
    )
    check(
        "L8 present+non-str ref -> ref null, crash YOK",
        r8["stopping_event_status"] == "present"
        and r8["stopping_event_attestation_ref"] is None,
        r8,
    )

    # --- 9/10: unknown ---
    r9 = rec(stopping_event_status="unknown")
    check(
        "L9 unknown+ref YOK -> needs_review, status='unknown', ref null",
        r9["calculation_state"] == "needs_review"
        and r9["stopping_event_status"] == "unknown"
        and r9["stopping_event_attestation_ref"] is None
        and r9["notes"] == dc.STOPPING_EVENT_REASON_UNKNOWN,
        r9,
    )
    r10 = rec(
        stopping_event_status="unknown",
        stopping_event_attestation_ref=VALID_REF,
    )
    check(
        "L10 unknown+geçerli ref -> ref VERBATIM korunur",
        r10["stopping_event_status"] == "unknown"
        and r10["stopping_event_attestation_ref"] == VALID_REF,
        r10,
    )

    # --- 11: parametre TAMAMEN omitted -> #9 ile BİREBİR aynı ---
    r11 = rec()
    check(
        "L11 parametre omitted -> L9 ile BİREBİR aynı (default ASLA 'none' DEĞİL)",
        r11["stopping_event_status"] == "unknown"
        and r11["stopping_event_attestation_ref"] is None
        and r11["notes"] == dc.STOPPING_EVENT_REASON_UNKNOWN
        and r11["calculation_state"] == r9["calculation_state"],
        r11,
    )
    check(
        "L11b tanınmayan bir status string'i de 'unknown'a düşer (fail-closed)",
        rec(stopping_event_status="bogus")["stopping_event_status"] == "unknown",
    )

    # --- 12: legacy canonical (iki anahtar da YOK) ---
    legacy = json.loads(
        (REAL_CASE_0001 / "deadlines" / "deadline.json").read_text(encoding="utf-8")
    )
    check(
        "L12 legacy canonical kayıt iki anahtarı da TAŞIMIYOR (Slice 2 öncesi üretim) "
        "- okunabilir kalır, projeksiyon onu 'unknown' gösterir, ASLA 'none'",
        all(
            "stopping_event_status" not in d
            and "stopping_event_attestation_ref" not in d
            for d in legacy["deadlines"]
        ),
    )

    # --- ERKEN DÖNÜŞ DALLARI: iki anahtar HER kayıtta fiziksel olarak var ---
    early = _record(
        anchor_event=_anchor("2026-02-10", verification_state="unverified"),
        stopping_event_status="none",
        stopping_event_attestation_ref=VALID_REF,
    )
    check(
        "L13 blocked_unverified_anchor (stopping kapısına HİÇ ULAŞMAYAN erken dönüş) "
        "kaydında da İKİ ANAHTAR fiziksel olarak MEVCUT",
        "stopping_event_status" in early
        and "stopping_event_attestation_ref" in early,
        sorted(early.keys()),
    )

    # --- ŞEMA: iki alan optional, required DEĞİŞMEDİ, const 1 ---
    schema = json.loads(
        (REAL_DATA_DIR / "case_deadline.schema.json").read_text(encoding="utf-8")
    )
    dl = schema["$defs"]["deadline"]
    check(
        "L14 şema: iki alan properties'te, required'a EKLENMEDİ, "
        "additionalProperties hâlâ false, schema_version const hâlâ 1",
        "stopping_event_status" in dl["properties"]
        and "stopping_event_attestation_ref" in dl["properties"]
        and "stopping_event_status" not in dl["required"]
        and "stopping_event_attestation_ref" not in dl["required"]
        and len(dl["required"]) == 16
        and dl["additionalProperties"] is False
        and schema["properties"]["schema_version"]["const"] == 1,
    )
    check(
        "L15 legacy canonical belge PATCH'LENMİŞ şemaya karşı HÂLÂ geçerli "
        "(geriye uyumluluk)",
        deadline_validator.validate_schema(legacy) == [],
        deadline_validator.validate_schema(legacy)[:3],
    )


def run_self_test():
    before = _snapshot_data_tree()

    test_reason_literals_pinned()
    test_a_decision_table()
    test_b_golden_regression()
    test_d_gate_ordering()
    test_e_conflict_matrix()
    test_f_attestation_ref_bounds()
    test_g_audit_persistence()
    test_i_no_production_bypass()
    test_k_cross_check_is_not_a_detector()
    test_l_canonical_fields_12_states()

    after = _snapshot_data_tree()
    check(
        "J bu test modülü: gerçek data/ ağacı tüm koşu boyunca bayt-değişmez "
        "(her senaryo kendi tempdir kopyasında; ağ yok, PostgreSQL yok, "
        "gerçek müvekkil verisi yok)",
        before == after,
        sorted(set(before) ^ set(after))[:5],
    )

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
