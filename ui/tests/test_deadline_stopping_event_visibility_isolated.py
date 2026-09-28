# ============================================================
# PILOT READINESS ADIM 7 / SLICE 2 - CANONICAL DEADLINE +
# CASE_VIEW VISIBILITY (ISOLATED)
#
# KAPSAM: Slice 2'nin GÖRÜNÜRLÜK yarısı - canonical deadline
# kaydından case_view projeksiyonuna, oradan avukat ekranına.
# Deadline yazıcı tarafının 12 durumluk tablosu KARDEŞ modüldedir
# (`test_deadline_stopping_events_isolated.py`, bölüm L).
#
# Bu dosya SALT-OKUNURDUR ve SAF IN-PROCESS'tir:
#   - `subprocess`/`Popen` YOK (Adım 4c F1'in `GUARD_INHERITANCE_
#     MISMATCH` sınıfı bu yüzden TEKRARLAMAZ),
#   - kendi ağ-guard'ını KURMAZ,
#   - PostgreSQL yok, ağ yok, LLM yok, gerçek müvekkil verisi yok,
#   - gerçek `data/` ağacına YAZMAZ (her mutasyon kendi tempdir
#     kopyasında; koşu başı/sonu bayt-manifesti karşılaştırılır).
#
# Run: python -m ui.tests.test_deadline_stopping_event_visibility_isolated
# ============================================================

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jinja2                                          # noqa: E402

import deadline_calculator as dc                       # noqa: E402
import orchestrator_discovery                          # noqa: E402
import orchestrator_engine                             # noqa: E402
import orchestrator_policy                             # noqa: E402

REAL_DATA_DIR = REPO_ROOT / "data"
REAL_CASE_0001 = REAL_DATA_DIR / "cases" / "case_0001"
TEMPLATES_DIR = REPO_ROOT / "ui" / "templates"
CASE_ID = "case_0001"

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label}" + (f"  [{detail}]" if detail else ""))


def _snapshot_data_tree():
    out = {}
    for p in sorted(REAL_DATA_DIR.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(REPO_ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class CaseViewSandbox:
    """`data/cases/` ağacının tempdir kopyası; `orchestrator_discovery`
    ve `orchestrator_engine`'in CASES_DIR'leri oraya yönlendirilir.
    `orchestrator_engine` CASES_DIR'i BY VALUE import ettiği için İKİSİ
    de ayrı ayrı yamanmak ZORUNDADIR."""

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="slice2_visibility_"))
        cases = self.tmp / "cases"
        cases.mkdir(parents=True)
        self.case_dir = cases / CASE_ID
        shutil.copytree(REAL_CASE_0001, self.case_dir)
        self._orig_disc = orchestrator_discovery.CASES_DIR
        self._orig_eng = orchestrator_engine.CASES_DIR
        orchestrator_discovery.CASES_DIR = cases
        orchestrator_engine.CASES_DIR = cases
        return self

    def deadline_path(self):
        return self.case_dir / "deadlines" / "deadline.json"

    def patch_deadline(self, **fields):
        path = self.deadline_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in fields.items():
            if value is _DELETE:
                data["deadlines"][0].pop(key, None)
            else:
                data["deadlines"][0][key] = value
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def __exit__(self, *exc):
        orchestrator_discovery.CASES_DIR = self._orig_disc
        orchestrator_engine.CASES_DIR = self._orig_eng
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


class _Delete:
    pass


_DELETE = _Delete()


def _entry(view):
    return view["deadline_panel"]["deadlines"][0]


# ================================================================
# A) ENUM DRIFT PINI - DÖRT KAYNAK BİREBİR AYNI OLMALI
# ================================================================

def test_a_enum_drift_pin():
    deadline_schema = json.loads(
        (REAL_DATA_DIR / "case_deadline.schema.json").read_text(encoding="utf-8")
    )
    view_schema = json.loads(
        (REAL_DATA_DIR / "case_view.schema.json").read_text(encoding="utf-8")
    )
    from_deadline_schema = tuple(
        deadline_schema["$defs"]["deadline"]["properties"]["stopping_event_status"]["enum"]
    )
    from_view_schema = tuple(
        view_schema["$defs"]["deadline_entry_ref"]["properties"]["stopping_event_status"]["enum"]
    )
    check(
        "A1 enum drift pini: deadline_calculator == orchestrator_policy == "
        "case_deadline.schema == case_view.schema",
        dc.STOPPING_EVENT_STATUS_VALUES
        == orchestrator_policy.STOPPING_EVENT_STATUS_ENUM
        == from_deadline_schema
        == from_view_schema,
        f"{dc.STOPPING_EVENT_STATUS_VALUES} / "
        f"{orchestrator_policy.STOPPING_EVENT_STATUS_ENUM} / "
        f"{from_deadline_schema} / {from_view_schema}",
    )
    check(
        "A2 fail-closed default sabiti 'unknown' (ASLA 'none')",
        orchestrator_policy.STOPPING_EVENT_STATUS_UNKNOWN == "unknown"
        == dc.STOPPING_EVENT_STATUS_UNKNOWN,
    )
    check(
        "A3 case_view şeması: üç alan optional (required DEĞİŞMEDİ), "
        "additionalProperties false, schema_version const 1",
        "stopping_event_status" in view_schema["$defs"]["deadline_entry_ref"]["properties"]
        and "stopping_event_attestation_ref" in view_schema["$defs"]["deadline_entry_ref"]["properties"]
        and "notes" in view_schema["$defs"]["deadline_entry_ref"]["properties"]
        and view_schema["$defs"]["deadline_entry_ref"]["required"] == [
            "deadline_id", "deadline_type", "calculation_state",
            "calculated_deadline", "expiry_state", "requires_human_review",
        ]
        and view_schema["$defs"]["deadline_entry_ref"]["additionalProperties"] is False
        and view_schema["properties"]["schema_version"]["const"] == 1,
    )


# ================================================================
# B) PROJEKSİYON - legacy, pass-through, fail-closed
# ================================================================

def test_b_projection():
    # B1 - gerçek (legacy) canonical: iki anahtar YOK -> unknown/null
    view = orchestrator_engine.build_case_view(CASE_ID)
    e = _entry(view)
    check(
        "B1 legacy canonical (alanlar YOK) -> status='unknown', ref=null "
        "(missing ASLA 'none' DEĞİL)",
        e["stopping_event_status"] == "unknown"
        and e["stopping_event_attestation_ref"] is None,
        e,
    )
    check(
        "B1b legacy canonical -> notes BİREBİR pass-through (null değil)",
        isinstance(e["notes"], str) and len(e["notes"]) > 0,
        e.get("notes"),
    )

    with CaseViewSandbox() as box:
        # B2 - alanlar mevcut: VERBATIM pass-through
        box.patch_deadline(
            stopping_event_status="none",
            stopping_event_attestation_ref="AV-BEYAN-2026-001",
            notes="ornek hesaplama notu",
        )
        e2 = _entry(orchestrator_engine.build_case_view(CASE_ID))
        check(
            "B2 alanlar mevcut -> VERBATIM pass-through (status/ref/notes)",
            e2["stopping_event_status"] == "none"
            and e2["stopping_event_attestation_ref"] == "AV-BEYAN-2026-001"
            and e2["notes"] == "ornek hesaplama notu",
            e2,
        )

        # B3 - tanınmayan status -> fail-closed unknown
        box.patch_deadline(stopping_event_status="bogus")
        e3 = _entry(orchestrator_engine.build_case_view(CASE_ID))
        check(
            "B3 tanınmayan status -> fail-closed 'unknown' (projeksiyon onu "
            "canonical'dan KÖRÜ KÖRÜNE taşımaz)",
            e3["stopping_event_status"] == "unknown",
            e3,
        )

        # B4 - status null -> unknown, ASLA none
        box.patch_deadline(stopping_event_status=None)
        e4 = _entry(orchestrator_engine.build_case_view(CASE_ID))
        check(
            "B4 status null -> 'unknown', ASLA 'none'",
            e4["stopping_event_status"] == "unknown",
            e4,
        )

        # B5 - determinizm: aynı canonical -> bayt-aynı projeksiyon
        box.patch_deadline(
            stopping_event_status="present",
            stopping_event_attestation_ref="R-DET",
            notes="determinizm",
        )
        p1 = orchestrator_engine.build_case_view(CASE_ID)["deadline_panel"]
        p2 = orchestrator_engine.build_case_view(CASE_ID)["deadline_panel"]
        check(
            "B5 determinizm: aynı canonical -> BAYT-AYNI deadline_panel",
            json.dumps(p1, sort_keys=True, ensure_ascii=False)
            == json.dumps(p2, sort_keys=True, ensure_ascii=False),
        )

        # B6 - case_view generation audit dosyasını OKUMAZ
        audit_dir = box.case_dir / "deadlines" / "generation_reviews"
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / "poison.generation_audit.json").write_text(
            json.dumps({"stopping_event_status": "none",
                        "stopping_event_attestation_ref": "AUDIT-ONLY-REF"}),
            encoding="utf-8",
        )
        e6 = _entry(orchestrator_engine.build_case_view(CASE_ID))
        check(
            "B6 case_view generation audit'i KAYNAK OLARAK OKUMAZ "
            "(audit'teki 'none'/ref projeksiyona SIZMAZ)",
            e6["stopping_event_status"] == "present"
            and e6["stopping_event_attestation_ref"] == "R-DET",
            e6,
        )


# ================================================================
# C) UI - etiketler, null-ref, duplicate-render, XSS
# ================================================================

_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=True,
)

_BASE_VIEW = {
    "case_summary": {"title": "Örnek Dava"},
    "generation_status": "completed",
    "issue_panel": [],
}

_BASE_ENTRY = {
    "deadline_id": "deadline_001",
    "deadline_type": "lawsuit_filing",
    "calculation_state": "needs_review",
    "calculated_deadline": None,
    "expiry_state": "not_evaluated",
    "requires_human_review": True,
    "stopping_event_status": "unknown",
    "stopping_event_attestation_ref": None,
    "notes": None,
}


def _render(entry_overrides=None, panel_overrides=None):
    entry = copy.deepcopy(_BASE_ENTRY)
    entry.update(entry_overrides or {})
    panel = {
        "source_state": "present_valid",
        "deadline_analysis_id": "deadline_case_0001_v1",
        "deadlines": [entry],
    }
    panel.update(panel_overrides or {})
    view = copy.deepcopy(_BASE_VIEW)
    view["deadline_panel"] = panel
    return _ENV.get_template("case_view.html").render(
        case_id="case_iso_0001", view=view, is_stale=False, has_canonical=True,
    )


def test_c_ui():
    html_unknown = _render()
    check(
        "C1 unknown -> exact metin",
        "Durdurucu olay durumu bilinmiyor — hesaplama durduruldu" in html_unknown,
    )
    check(
        "C2 none -> exact metin ('beyan' kelimesini TAŞIR; bağımsız doğrulanmış "
        "bir hukuki gerçek gibi SUNULMAZ)",
        "Durdurucu olay yok beyanı"
        in _render({"stopping_event_status": "none"}),
    )
    check(
        "C3 present -> exact metin",
        "Durdurucu olay mevcut — avukat incelemesi gerekli"
        in _render({"stopping_event_status": "present"}),
    )

    check(
        "C4 ref null -> 'Beyan referansı' satırı HİÇ render EDİLMEZ",
        "Beyan referansı" not in html_unknown,
    )
    html_ref = _render({"stopping_event_attestation_ref": "AV-BEYAN-2026-001"})
    check(
        "C5 ref dolu -> 'Beyan referansı: <değer>' render edilir",
        "Beyan referansı" in html_ref and "AV-BEYAN-2026-001" in html_ref,
    )

    check(
        "C6 notes null -> 'Hesaplama notu' satırı render EDİLMEZ",
        "Hesaplama notu" not in html_unknown,
    )
    html_notes = _render({"notes": "stopping_event_status_unknown"})
    check(
        "C7 notes dolu -> başlık TAM OLARAK 'Hesaplama notu' ('Neden' DEĞİL) "
        "ve değer BİREBİR",
        "Hesaplama notu" in html_notes
        and "stopping_event_status_unknown" in html_notes
        and "Neden:" not in html_notes,
    )

    # --- duplicate render ---
    check(
        "C8 generic <details> dökümü deadline_panel'i ARTIK render ETMİYOR",
        "<summary>deadline_panel</summary>" not in html_unknown,
    )
    check(
        "C9 deadline paneli ekranda TAM BİR KEZ görünür",
        html_unknown.count("Deadline Paneli") == 1,
        html_unknown.count("Deadline Paneli"),
    )

    # --- kayıpsızlık ---
    html_full = _render({
        "calculated_deadline": "2026-03-12",
        "expiry_state": "not_evaluated",
        "stopping_event_status": "none",
        "stopping_event_attestation_ref": "AV-R",
        "notes": "n",
    })
    check(
        "C10 blok KAYIPSIZ: dokuz alanın tamamı ekranda "
        "(`case_summary` tuzağına düşülmedi)",
        all(
            token in html_full
            for token in (
                "deadline_001", "lawsuit_filing", "needs_review",
                "2026-03-12", "not_evaluated", "evet",
                "Durdurucu olay yok beyanı", "AV-R", "Hesaplama notu",
            )
        ),
    )
    check(
        "C11 panel seviyesindeki iki alan da gösterilir",
        "present_valid" in html_full and "deadline_case_0001_v1" in html_full,
    )
    check(
        "C12 boş deadlines listesi açıkça ele alınır (panel DICT olduğu için "
        "boşken bile truthy'dir)",
        "(bu dosyada deadline kaydı yok)"
        in _render(panel_overrides={"deadlines": []}),
    )

    # --- XSS / escaping ---
    payloads = {
        "script": "<script>alert('xss')</script>",
        "attr": '" onmouseover="alert(1)',
        "amp": "a & b",
        "table": "</table><script>alert(2)</script>",
    }
    for name, payload in payloads.items():
        html = _render({
            "stopping_event_attestation_ref": payload,
            "notes": payload,
        })
        check(
            f"C13-{name} ref/notes içindeki payload HAM olarak SIZMIYOR "
            "(autoescape çalışıyor, |safe YOK)",
            payload not in html,
        )
    html_script = _render({"stopping_event_attestation_ref": payloads["script"]})
    check(
        "C14 <script> escape edilmiş biçimde görünüyor (&lt;script&gt;)",
        "&lt;script&gt;" in html_script,
    )
    check(
        "C15 ref otomatik hyperlink YAPILMIYOR (üretilen <a> sayısı sabit kalır)",
        _render({"stopping_event_attestation_ref": "https://ornek.test/belge"}).count("<a ")
        == html_unknown.count("<a "),
    )
    check(
        "C16 Markdown yorumlanmıyor (ham metin olarak kalır)",
        "**kalin**" in _render({"notes": "**kalin**"}),
    )

    # --- bidi / zero-width: canonical'a ULAŞAMAZ ---
    for name, bad in (
        ("bidi U+202E", "AV‮BEYAN"),
        ("zero-width U+200B", "AV​BEYAN"),
    ):
        check(
            f"C17-{name} ref validator tarafından REDDEDİLİR "
            "(str.isprintable() -> canonical'a hiç ulaşamaz)",
            dc.is_valid_stopping_event_attestation_ref(bad) is False,
        )
    check(
        "C18 şablonlarda canlı `|safe` bypass'ı YOK",
        "|safe" not in (TEMPLATES_DIR / "case_view.html").read_text(encoding="utf-8")
        and "|safe" not in (TEMPLATES_DIR / "macros.html").read_text(encoding="utf-8"),
    )


# ================================================================
# D) UÇTAN UCA - canonical -> case_view değer eşliği
# ================================================================

def test_d_end_to_end_equality():
    with CaseViewSandbox() as box:
        box.patch_deadline(
            stopping_event_status="present",
            stopping_event_attestation_ref="AV-E2E-001",
            notes="e2e notu",
        )
        canonical = json.loads(box.deadline_path().read_text(encoding="utf-8"))["deadlines"][0]
        projected = _entry(orchestrator_engine.build_case_view(CASE_ID))
        check(
            "D1 canonical -> case_view değer eşliği (status/ref/notes)",
            canonical["stopping_event_status"] == projected["stopping_event_status"]
            and canonical["stopping_event_attestation_ref"] == projected["stopping_event_attestation_ref"]
            and canonical["notes"] == projected["notes"],
            f"{canonical} vs {projected}",
        )
        html = _ENV.get_template("case_view.html").render(
            case_id=CASE_ID,
            view=orchestrator_engine.build_case_view(CASE_ID),
            is_stale=False, has_canonical=True,
        )
        check(
            "D2 canonical -> ekran: ref ve notes avukatın gördüğü HTML'de",
            "AV-E2E-001" in html and "e2e notu" in html,
        )


def run_self_test():
    print()
    print("======================================")
    print(" ADIM 7 / SLICE 2 - VISIBILITY (ISOLATED)")
    print("======================================")

    before = _snapshot_data_tree()

    test_a_enum_drift_pin()
    test_b_projection()
    test_c_ui()
    test_d_end_to_end_equality()

    after = _snapshot_data_tree()
    check(
        "E1 gerçek data/ ağacı tüm koşu boyunca BAYT-DEĞİŞMEZ "
        "(her mutasyon kendi tempdir kopyasında)",
        before == after,
        sorted(set(before) ^ set(after))[:5],
    )

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_self_test() else 1)
