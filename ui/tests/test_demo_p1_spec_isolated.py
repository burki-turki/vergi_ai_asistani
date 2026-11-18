# ============================================================
# DEMO P1 - ui/services/demo_p1_spec.py İZOLE TESTİ
#
# Kapalı şemalı demo_spec.json: bilinmeyen anahtar RET; `demo_` kimlik kilidi;
# kaynak etiketi dürüstlüğü ("Sistem çıkardı" spec'te YAZILAMAZ); sayfa/alıntı
# kuralları; yapılandırılmış değerlerin alıntıda GÖRÜNMESİ; kapalı hata kodları;
# demo modüllerinde ağ/subprocess importu YOK (AST taraması).
# ============================================================

import ast
import copy
import json
import sys
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

passed = 0
failed = 0
skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def summarize_and_exit():
    print(f"--- test_demo_p1_spec_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import demo_p1_spec as S  # noqa: E402

BASE = {
    "schema_version": 1,
    "demo_id": "demo_001",
    "belgeler": [
        {"doc_id": "ihbarname_001", "file_name": "ihbarname.pdf", "document_type": "vergi_ceza_ihbarnamesi",
         "title": "Vergi ve ceza ihbarnamesi (sentetik)", "declared_page_count": 2},
        {"doc_id": "ek_001", "file_name": "vir.pdf", "document_type": "vergi_inceleme_raporu",
         "title": "Vergi inceleme raporu (Ek-1, sentetik)", "declared_page_count": 2},
    ],
    "bulgular": [
        {"fact_id": "b01", "doc_id": "ihbarname_001", "page": 1,
         "excerpt": "İhbarname, mükellefe 10.02.2026 tarihinde tebliğ edilmiştir.", "fact_kind": "date_fact",
         "statement": "Tebliğ tarihi", "origin": "ornek",
         "degerler": [{"value_type": "date", "label": "Tebliğ tarihi", "value": "2026-02-10"}]},
        {"fact_id": "b02", "doc_id": "ek_001", "page": 2, "excerpt": "Vergi aslı: 850.000,00 TL",
         "fact_kind": "monetary_fact", "statement": "Vergi aslı", "origin": "avukat",
         "degerler": [{"value_type": "money", "label": "Vergi aslı", "value": "850000.00"}]},
        {"fact_id": "b03", "doc_id": "ek_001", "page": 1, "excerpt": "Rapor No: VIR-DEMO-0001",
         "fact_kind": "document_finding", "statement": "Rapor no", "origin": "ornek"},
    ],
    "eksik_atiflar": [
        {"fact_id": "a01", "referenced_in_doc": "ihbarname_001", "page": 2,
         "excerpt": "Ek-2 (Bilirkişi görüşü) ekte sunulmuştur.", "referenced_name": "Ek-2", "origin": "ornek"},
    ],
}


def code_of(raw):
    try:
        S.validate_spec(raw)
    except S.DemoError as error:
        return error.code
    except Exception as error:  # pragma: no cover
        return "UNEXPECTED:" + type(error).__name__
    return None


def mutated(fn):
    raw = copy.deepcopy(BASE)
    fn(raw)
    return raw


# ---------------- geçerli spec
spec = S.validate_spec(copy.deepcopy(BASE))
check("a valid spec parses into frozen dataclasses (2 documents, 3 findings, 1 missing ref)",
      len(spec.documents) == 2 and len(spec.findings) == 3 and len(spec.missing_refs) == 1 and spec.demo_id == "demo_001")
check("structured values are parsed into DemoValue tuples (date + money)",
      spec.findings[0].values[0].value_type == "date" and spec.findings[1].values[0].value_type == "money"
      and spec.findings[2].values == ())
try:
    spec.demo_id = "x"
    frozen = False
except Exception:
    frozen = True
check("the parsed spec is immutable", frozen)
check("parse_spec accepts raw bytes (with a UTF-8 BOM)",
      S.parse_spec(b"\xef\xbb\xbf" + json.dumps(BASE, ensure_ascii=False).encode("utf-8")).demo_id == "demo_001")
def _raises(fn, code):
    try:
        fn()
    except S.DemoError as error:
        return error.code == code
    except Exception:
        return False
    return False


check("parse_spec: invalid JSON -> SPEC_BOZUK", _raises(lambda: S.parse_spec(b"{nope"), "SPEC_BOZUK"))
check("parse_spec: invalid UTF-8 -> SPEC_BOZUK", _raises(lambda: S.parse_spec(b"\xff\xfe\x00{}"), "SPEC_BOZUK"))
check("parse_spec: oversized payload -> SPEC_BOZUK", _raises(lambda: S.parse_spec(b" " * (S.MAX_SPEC_BYTES + 1)), "SPEC_BOZUK"))
check("parse_spec: a non-bytes input -> SPEC_BOZUK", _raises(lambda: S.parse_spec("{}"), "SPEC_BOZUK"))

# ---------------- kapalı şema
check("an unknown TOP-LEVEL key is refused", code_of(mutated(lambda r: r.update({"ekstra": 1}))) == "SPEC_ALAN_GECERSIZ")
check("a MISSING top-level key is refused", code_of(mutated(lambda r: r.pop("eksik_atiflar"))) == "SPEC_ALAN_GECERSIZ")
check("an unknown key inside a document is refused", code_of(mutated(lambda r: r["belgeler"][0].update({"x": 1}))) == "SPEC_ALAN_GECERSIZ")
check("an unknown key inside a finding is refused", code_of(mutated(lambda r: r["bulgular"][0].update({"x": 1}))) == "SPEC_ALAN_GECERSIZ")
check("an unknown key inside a missing-ref is refused", code_of(mutated(lambda r: r["eksik_atiflar"][0].update({"x": 1}))) == "SPEC_ALAN_GECERSIZ")
check("an unknown key inside a structured value is refused",
      code_of(mutated(lambda r: r["bulgular"][0]["degerler"][0].update({"x": 1}))) == "SPEC_ALAN_GECERSIZ")
check("schema_version must be exactly 1", code_of(mutated(lambda r: r.update({"schema_version": 2}))) == "SPEC_ALAN_GECERSIZ")
check("a boolean is NOT accepted as an integer (schema_version)", code_of(mutated(lambda r: r.update({"schema_version": True}))) == "SPEC_ALAN_GECERSIZ")
check("a non-object spec is refused", code_of([1, 2]) == "SPEC_ALAN_GECERSIZ")

# ---------------- demo_ kimlik kilidi
for bad in ("case_0001", "demo", "Demo_001", "demo_", "demo-001", "demo_" + "x" * 41, "demo_a/b", "demo_..", "", None, 5):
    check(f"demo_id {bad!r} is refused (DEMO_KIMLIGI_GECERSIZ)", code_of(mutated(lambda r, b=bad: r.update({"demo_id": b}))) == "DEMO_KIMLIGI_GECERSIZ")
check("a demo_ id with digits/underscores is accepted", code_of(mutated(lambda r: r.update({"demo_id": "demo_a_1"}))) is None)

# ---------------- belgeler
check("an empty document list is refused", code_of(mutated(lambda r: r.update({"belgeler": []}))) == "SPEC_ALAN_GECERSIZ")
check("a duplicate doc_id is refused", code_of(mutated(lambda r: r["belgeler"][1].update({"doc_id": "ihbarname_001"}))) == "SPEC_ALAN_GECERSIZ")
check("a duplicate file_name is refused (case-insensitive)", code_of(mutated(lambda r: r["belgeler"][1].update({"file_name": "IHBARNAME.PDF"}))) == "SPEC_ALAN_GECERSIZ")
for bad_name in ("../x.pdf", "a/b.pdf", "a\\b.pdf", "x.txt", "x.pdf.exe", ".pdf", "C:x.pdf", "x\n.pdf"):
    check(f"file_name {bad_name!r} is refused", code_of(mutated(lambda r, b=bad_name: r["belgeler"][0].update({"file_name": b}))) == "SPEC_ALAN_GECERSIZ")
check("a bad doc_id is refused", code_of(mutated(lambda r: r["belgeler"][0].update({"doc_id": "A"}))) == "SPEC_ALAN_GECERSIZ")
check("declared_page_count must be an int >= 1", code_of(mutated(lambda r: r["belgeler"][0].update({"declared_page_count": 0}))) == "SPEC_ALAN_GECERSIZ"
      and code_of(mutated(lambda r: r["belgeler"][0].update({"declared_page_count": "2"}))) == "SPEC_ALAN_GECERSIZ"
      and code_of(mutated(lambda r: r["belgeler"][0].update({"declared_page_count": True}))) == "SPEC_ALAN_GECERSIZ")

# ---------------- kaynak etiketi dürüstlüğü
check("origin 'sistem' (Sistem çıkardı) can NOT be written in a pre-prepared finding",
      code_of(mutated(lambda r: r["bulgular"][0].update({"origin": "sistem"}))) == "SPEC_ALAN_GECERSIZ")
check("origin 'sistem' can NOT be written in a missing-ref either",
      code_of(mutated(lambda r: r["eksik_atiflar"][0].update({"origin": "sistem"}))) == "SPEC_ALAN_GECERSIZ")
check("an unknown origin is refused", code_of(mutated(lambda r: r["bulgular"][0].update({"origin": "model"}))) == "SPEC_ALAN_GECERSIZ")
check("origin 'ornek' and 'avukat' are the only spec origins", S.SPEC_ALLOWED_ORIGINS == ("ornek", "avukat"))
check("the origin labels are the exact Turkish texts the lawyer reads",
      S.ORIGIN_LABELS == {"ornek": "Önceden hazırlanmış örnek", "avukat": "Avukat girdisi", "sistem": "Sistem çıkardı"})

# ---------------- bulgu alanları
check("a finding for an unknown document is refused", code_of(mutated(lambda r: r["bulgular"][0].update({"doc_id": "yok_001"}))) == "SPEC_ALAN_GECERSIZ")
check("a page below 1 is refused", code_of(mutated(lambda r: r["bulgular"][0].update({"page": 0}))) == "SPEC_ALAN_GECERSIZ")
check("a page above the declared page count is refused", code_of(mutated(lambda r: r["bulgular"][0].update({"page": 3}))) == "SPEC_ALAN_GECERSIZ")
check("a non-integer / boolean page is refused",
      code_of(mutated(lambda r: r["bulgular"][0].update({"page": "1"}))) == "SPEC_ALAN_GECERSIZ"
      and code_of(mutated(lambda r: r["bulgular"][0].update({"page": True}))) == "SPEC_ALAN_GECERSIZ"
      and code_of(mutated(lambda r: r["bulgular"][0].update({"page": 1.0}))) == "SPEC_ALAN_GECERSIZ")
for bad_excerpt in ("", "   ", "iki\nsatır", "tab\tkarakter", "ff\fsayfa", "x" * (S.MAX_EXCERPT_CHARS + 1), None, 5):
    check(f"excerpt {bad_excerpt!r:.30} is refused (single non-empty line)",
          code_of(mutated(lambda r, b=bad_excerpt: r["bulgular"][2].update({"excerpt": b}))) == "SPEC_ALAN_GECERSIZ")
check("excerpt text is NFC-normalized by the parser",
      S.validate_spec(mutated(lambda r: r["bulgular"][2].update({"excerpt": "Rapor No: VIR-DEMO-0001 ı̇"}))).findings[2].excerpt
      == __import__("unicodedata").normalize("NFC", "Rapor No: VIR-DEMO-0001 ı̇"))
check("a duplicate fact_id among findings is refused", code_of(mutated(lambda r: r["bulgular"][1].update({"fact_id": "b01"}))) == "SPEC_ALAN_GECERSIZ")
check("a fact_id shared between a finding and a missing-ref is refused", code_of(mutated(lambda r: r["eksik_atiflar"][0].update({"fact_id": "b01"}))) == "SPEC_ALAN_GECERSIZ")
check("a bad fact_id is refused", code_of(mutated(lambda r: r["bulgular"][0].update({"fact_id": "B 01"}))) == "SPEC_ALAN_GECERSIZ")
check("a fact_kind outside the allowed set is refused", code_of(mutated(lambda r: r["bulgular"][0].update({"fact_kind": "evidence_reference"}))) == "SPEC_ALAN_GECERSIZ")
check("an empty statement is refused", code_of(mutated(lambda r: r["bulgular"][0].update({"statement": ""}))) == "SPEC_ALAN_GECERSIZ")

# ---------------- yapılandırılmış değerler
check("date_fact WITHOUT a date value is refused (mirrors case_fact_validator)",
      code_of(mutated(lambda r: r["bulgular"][0].update({"degerler": []}))) == "SPEC_ALAN_GECERSIZ")
check("monetary_fact WITHOUT a money value is refused",
      code_of(mutated(lambda r: r["bulgular"][1].update({"degerler": []}))) == "SPEC_ALAN_GECERSIZ")
check("legal_reference WITHOUT a reference value is refused",
      code_of(mutated(lambda r: r["bulgular"][2].update({"fact_kind": "legal_reference"}))) == "SPEC_ALAN_GECERSIZ")
check("a date value that does NOT appear in the excerpt is refused (the software never writes an unseen value)",
      code_of(mutated(lambda r: r["bulgular"][0]["degerler"][0].update({"value": "2026-02-11"}))) == "SPEC_ALAN_GECERSIZ")
check("an impossible calendar date is refused", code_of(mutated(lambda r: r["bulgular"][0]["degerler"][0].update({"value": "2026-02-30"}))) == "SPEC_ALAN_GECERSIZ")
check("a non-ISO date value is refused", code_of(mutated(lambda r: r["bulgular"][0]["degerler"][0].update({"value": "10.02.2026"}))) == "SPEC_ALAN_GECERSIZ")
check("the dd/mm/yyyy spelling in the excerpt is accepted for the same date",
      code_of(mutated(lambda r: r["bulgular"][0].update({"excerpt": "Tebliğ: 10/02/2026"}))) is None)
check("a money value that does not appear (Turkish format) in the excerpt is refused",
      code_of(mutated(lambda r: r["bulgular"][1]["degerler"][0].update({"value": "850000.50"}))) == "SPEC_ALAN_GECERSIZ")
check("a malformed money value is refused", code_of(mutated(lambda r: r["bulgular"][1]["degerler"][0].update({"value": "850.000,00"}))) == "SPEC_ALAN_GECERSIZ")
check("a reference value must appear in the excerpt",
      code_of(mutated(lambda r: r["bulgular"][2].update({"fact_kind": "legal_reference",
              "degerler": [{"value_type": "reference", "label": "Rapor", "value": "VIR-DEMO-0001"}]}))) is None
      and code_of(mutated(lambda r: r["bulgular"][2].update({"fact_kind": "legal_reference",
              "degerler": [{"value_type": "reference", "label": "Rapor", "value": "VIR-DEMO-9999"}]}))) == "SPEC_ALAN_GECERSIZ")
check("an unknown value_type is refused", code_of(mutated(lambda r: r["bulgular"][0]["degerler"][0].update({"value_type": "number"}))) == "SPEC_ALAN_GECERSIZ")
check("degerler must be a list", code_of(mutated(lambda r: r["bulgular"][0].update({"degerler": "x"}))) == "SPEC_ALAN_GECERSIZ")
check("degerler is OPTIONAL for non-structured kinds", S.validate_spec(copy.deepcopy(BASE)).findings[2].values == ())

# ---------------- eksik atıflar
check("a missing-ref for an unknown document is refused", code_of(mutated(lambda r: r["eksik_atiflar"][0].update({"referenced_in_doc": "yok_001"}))) == "SPEC_ALAN_GECERSIZ")
check("a missing-ref page above the declared count is refused", code_of(mutated(lambda r: r["eksik_atiflar"][0].update({"page": 9}))) == "SPEC_ALAN_GECERSIZ")
check("a missing-ref with an empty referenced_name is refused", code_of(mutated(lambda r: r["eksik_atiflar"][0].update({"referenced_name": " "}))) == "SPEC_ALAN_GECERSIZ")
check("a spec with NO findings and NO missing refs is valid (empty report)",
      code_of(mutated(lambda r: r.update({"bulgular": [], "eksik_atiflar": []}))) is None)

# ---------------- kapalı hata kodları
error = S.DemoError("NOT_A_REAL_CODE")
check("an unknown error code collapses to BILINMEYEN_HATA", error.code == "BILINMEYEN_HATA" and str(error) == "BILINMEYEN_HATA")
check("the new closed codes exist (DIZIN_GUVENSIZ, VAKA_YARIM, VAKA_UYUSMUYOR)", {"DIZIN_GUVENSIZ", "VAKA_YARIM", "VAKA_UYUSMUYOR"} <= S.DEMO_ERROR_CODES)
check("every closed code stringifies to itself only (no content/path can ride along)",
      all(str(S.DemoError(code)) == code for code in S.DEMO_ERROR_CODES))
try:
    S.validate_spec(mutated(lambda r: r["bulgular"][0].update({"excerpt": "GİZLİ_İÇERİK\nikinci satır"})))
    leaked = None
except S.DemoError as caught:
    leaked = str(caught) + repr(caught.args)
check("a refusal never echoes the offending content", leaked is not None and "GİZLİ" not in leaked)

# ---------------- M-2: değer-alıntı eşlemesi TAM JETON (alt dize eşleşmesi yetmez)
def value_case(excerpt, value_type, value, kind, currency=None):
    def edit(raw):
        item = {"value_type": value_type, "label": "Değer", "value": value}
        if currency is not None:
            item["currency"] = currency
        raw["bulgular"][2].update({"excerpt": excerpt, "fact_kind": kind, "degerler": [item]})
    return code_of(mutated(edit))


def money(excerpt, value, currency=None):
    return value_case(excerpt, "money", value, "monetary_fact", currency)


check("M-2: '11.000,00' does NOT satisfy 1000.00 (was accepted as a substring of the Turkish format)",
      value_case("Vergi aslı: 11.000,00 TL", "money", "1000.00", "monetary_fact") == "SPEC_ALAN_GECERSIZ")
check("M-2: '1.100,00' does NOT satisfy 100.00", value_case("Vergi aslı: 1.100,00 TL", "money", "100.00", "monetary_fact") == "SPEC_ALAN_GECERSIZ")
check("M-2: '1.000,005' does NOT satisfy 1000.00 (a further digit follows)", value_case("Tutar 1.000,005 TL", "money", "1000.00", "monetary_fact") == "SPEC_ALAN_GECERSIZ")
check("M-2: '21.000,00' does NOT satisfy 1000.00", value_case("Tutar 21.000,00 TL", "money", "1000.00", "monetary_fact") == "SPEC_ALAN_GECERSIZ")
check("M-2: the legitimate Turkish amount '1.000,00' satisfies 1000.00 (also at the end and before punctuation)",
      value_case("Vergi aslı: 1.000,00 TL", "money", "1000.00", "monetary_fact") is None
      and value_case("Vergi aslı 1.000,00", "money", "1000.00", "monetary_fact") is None
      and value_case("Toplam 1.000,00, ayrıca", "money", "1000.00", "monetary_fact") is None)
check("M-2: '850.000,00' satisfies 850000.00 and '850.000,00 TL.' (trailing dot) too",
      value_case("Vergi aslı: 850.000,00 TL.", "money", "850000.00", "monetary_fact") is None)
check("M-2: '110.02.2026' does NOT satisfy 2026-02-10", value_case("Tebliğ: 110.02.2026", "date", "2026-02-10", "date_fact") == "SPEC_ALAN_GECERSIZ")
check("M-2: '10.02.20261' does NOT satisfy 2026-02-10", value_case("Tebliğ: 10.02.20261", "date", "2026-02-10", "date_fact") == "SPEC_ALAN_GECERSIZ")
check("M-2: '1.10.02.2026' does NOT satisfy 2026-02-10", value_case("Tebliğ: 1.10.02.2026", "date", "2026-02-10", "date_fact") == "SPEC_ALAN_GECERSIZ")
check("M-2: the legitimate spellings '10.02.2026' / '(10.02.2026)' / '10.02.2026.' / '10/02/2026' satisfy 2026-02-10",
      all(value_case(f"Tebliğ {text}", "date", "2026-02-10", "date_fact") is None
          for text in ("10.02.2026", "(10.02.2026)", "10.02.2026.", "10/02/2026", "10.02.2026'da")))
check("M-2: a reference that is only a PREFIX of a longer identifier is refused (VIR-DEMO-0001 in VIR-DEMO-00012)",
      value_case("Rapor No: VIR-DEMO-00012", "reference", "VIR-DEMO-0001", "legal_reference") == "SPEC_ALAN_GECERSIZ")
check("M-2: the whole identifier is accepted, also before punctuation",
      value_case("Rapor No: VIR-DEMO-0001, ekte", "reference", "VIR-DEMO-0001", "legal_reference") is None)
# ---------------- P1-L-C: tutarın İŞARETİ ve açık PARA BİRİMİ alıntıyla çelişemez
check("L-C: +1000.00 vs '-1.000,00 TL' is refused (the minus sign was silently lost)", money("Vergi aslı: -1.000,00 TL", "1000.00") == "SPEC_ALAN_GECERSIZ")
check("L-C: +1000.00 vs '−1.000,00' (U+2212 minus) is refused", money("Vergi aslı: \u22121.000,00 TL", "1000.00") == "SPEC_ALAN_GECERSIZ")
check("L-C: +1000.00 vs '(1.000,00)' (accounting parentheses) is refused", money("Vergi aslı: (1.000,00)", "1000.00") == "SPEC_ALAN_GECERSIZ")
check("L-C: +1000.00 vs '(1.000,00 TL)' (parentheses around amount and unit) is refused", money("Vergi aslı: (1.000,00 TL)", "1000.00") == "SPEC_ALAN_GECERSIZ")
check("L-C: +1000.00 vs '(-)1.000,00' is refused", money("Vergi aslı: (-)1.000,00 TL", "1000.00") == "SPEC_ALAN_GECERSIZ")
check("L-C: +1000.00 vs '-₺1.000,00' and '₺-1.000,00' are refused", money("Tutar -₺1.000,00", "1000.00") == "SPEC_ALAN_GECERSIZ" and money("Tutar ₺-1.000,00", "1000.00") == "SPEC_ALAN_GECERSIZ")
check("L-C: a NEGATIVE spec amount (-1000.00) is accepted only when the excerpt is negative too",
      money("Vergi aslı: -1.000,00 TL", "-1000.00") is None and money("Vergi aslı: \u22121.000,00 TL", "-1000.00") is None
      and money("Vergi aslı: (1.000,00)", "-1000.00") is None and money("Vergi aslı: (-)1.000,00", "-1000.00") is None)
check("L-C: a NEGATIVE spec amount against a POSITIVE excerpt is refused", money("Vergi aslı: 1.000,00 TL", "-1000.00") == "SPEC_ALAN_GECERSIZ")
check("L-C: fail-closed: a dash with one space ('- 1.000,00', 'TL - 1.000,00') is read as a minus sign (a false refusal is cheaper than a lost sign); it matches a negative spec amount",
      money("Tutar TL - 1.000,00", "1000.00") == "SPEC_ALAN_GECERSIZ" and money("Tutar - 1.000,00", "1000.00") == "SPEC_ALAN_GECERSIZ"
      and money("Tutar - 1.000,00", "-1000.00") is None)
check("L-C: positive control - '1.000,00 TL', '1.000,00 TRY', '1.000,00 ₺', 'TL 1.000,00', '₺1.000,00' all satisfy 1000.00 (TRY)",
      all(money(text, "1000.00") is None for text in ("Vergi aslı: 1.000,00 TL", "Vergi aslı: 1.000,00 TRY", "Vergi aslı: 1.000,00 ₺",
                                                    "Vergi aslı: TL 1.000,00", "Vergi aslı: ₺1.000,00", "Vergi aslı: 1.000,00 tl")))
check("L-C: no explicit unit in the excerpt = TRY by default (not a conflict)", money("Vergi aslı: 1.000,00", "1000.00") is None and money("Vergi aslı: 1.000,00", "1000.00", "TRY") is None)
check("L-C: an excerpt that states USD / $ / EUR / € is refused for a TRY spec amount",
      all(money(text, "1000.00") == "SPEC_ALAN_GECERSIZ" for text in ("Tutar 1.000,00 USD", "Tutar $1.000,00", "Tutar 1.000,00 $",
                                                                      "Tutar 1.000,00 EUR", "Tutar €1.000,00", "Tutar 1.000,00 €")))
check("L-C: ... and also when currency 'TRY' is written explicitly in the spec", money("Tutar 1.000,00 USD", "1000.00", "TRY") == "SPEC_ALAN_GECERSIZ")
check("L-C: a spec amount in USD is refused against a TL excerpt and against an excerpt with no unit (never assumes a currency the document does not state)",
      money("Tutar 1.000,00 TL", "1000.00", "USD") == "SPEC_ALAN_GECERSIZ" and money("Tutar 1.000,00", "1000.00", "USD") == "SPEC_ALAN_GECERSIZ")
check("L-C: USD / EUR specs are accepted with a matching explicit unit ($ USD € EUR)",
      money("Tutar 1.000,00 USD", "1000.00", "USD") is None and money("Tutar $1.000,00", "1000.00", "USD") is None
      and money("Tutar 1.000,00 EUR", "1000.00", "EUR") is None and money("Tutar €1.000,00", "1000.00", "EUR") is None)
check("L-C: the optional 'currency' field is closed: unknown code, lowercase, non-string and use on a non-money value are refused",
      money("Tutar 1.000,00 TL", "1000.00", "GBP") == "SPEC_ALAN_GECERSIZ" and money("Tutar 1.000,00 TL", "1000.00", "try") == "SPEC_ALAN_GECERSIZ"
      and money("Tutar 1.000,00 TL", "1000.00", 5) == "SPEC_ALAN_GECERSIZ"
      and value_case("Rapor No: VIR-DEMO-0001", "reference", "VIR-DEMO-0001", "legal_reference", "TRY") == "SPEC_ALAN_GECERSIZ")
check("L-C: the parsed value carries the currency (default TRY; explicit USD kept)",
      S.validate_spec(mutated(lambda r: r["bulgular"][1]["degerler"][0].update({"currency": "TRY"}))).findings[1].values[0].currency == "TRY"
      and S.validate_spec(mutated(lambda r: (r["bulgular"][1].update({"excerpt": "Vergi aslı: 850.000,00 USD"}), r["bulgular"][1]["degerler"][0].update({"currency": "USD"})))).findings[1].values[0].currency == "USD"
      and S.validate_spec(copy.deepcopy(BASE)).findings[1].values[0].currency == "TRY")
check("L-C: the M-2 pairs still hold with the sign/unit rules (11.000,00 vs 1000.00 refused; 1.100,00 vs 100.00 refused)",
      money("Vergi aslı: 11.000,00 TL", "1000.00") == "SPEC_ALAN_GECERSIZ" and money("Vergi aslı: 1.100,00 TL", "100.00") == "SPEC_ALAN_GECERSIZ")
check("L-C: a malformed sign (--1000.00, +1000.00, '- 1000.00') is refused in the spec value", all(money("Tutar 1.000,00", v) == "SPEC_ALAN_GECERSIZ" for v in ("--1000.00", "+1000.00", "- 1000.00")))

# L-6: string değerleri de alıntıyla karşılaştırılır (boşluk daraltılmış TAM eşleşme)
check("L-6: a 'string' value absent from the excerpt is refused", value_case("Rapor No: VIR-DEMO-0001", "string", "Başka bir değer", "document_finding") == "SPEC_ALAN_GECERSIZ")
check("L-6: a 'string' value that is a mid-word fragment is refused ('apor' inside 'Rapor')", value_case("Rapor No: VIR-DEMO-0001", "string", "apor", "document_finding") == "SPEC_ALAN_GECERSIZ")
check("L-6: a 'string' value matches after whitespace collapsing (double spaces in the excerpt)",
      value_case("Rapor   No:  VIR-DEMO-0001", "string", "Rapor No: VIR-DEMO-0001", "document_finding") is None)
check("L-6: a 'string' value made only of whitespace is refused", value_case("Rapor No: VIR-DEMO-0001", "string", "   ", "document_finding") == "SPEC_ALAN_GECERSIZ")
# M-2 sonuç düzeyi: reddedilen çift olgu kaydına YAZILAMAZ (facts.json'a değer girmez çünkü spec reddedildi)
check("M-2: the refused pair never reaches a spec object (no money_value could be written for it)",
      code_of(mutated(lambda r: r["bulgular"][1].update({"excerpt": "Vergi aslı: 11.000,00 TL"}))) == "SPEC_ALAN_GECERSIZ")

# ---------------- AST: demo modüllerinde ağ/subprocess/LLM importu yok
FORBIDDEN = {"socket", "urllib", "http", "requests", "httpx", "httpx2", "anthropic", "openai", "smtplib", "ftplib",
             "subprocess", "ssl", "asyncio", "webbrowser", "xmlrpc", "telnetlib"}
SOURCES = ["ui/demo_case_review.py", "ui/services/demo_p1_spec.py", "ui/services/demo_p1_intake.py",
           "ui/services/demo_p1_facts.py", "ui/services/demo_p1_report.py"]
for rel in SOURCES:
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    check(f"{rel}: no network / subprocess / LLM import ({sorted(names & FORBIDDEN) or 'none'})", not (names & FORBIDDEN))

# AST taraması gerçekten tautolojik değil: yasaklı bir import görürse yakalar
probe = ast.parse("import socket\nfrom urllib import request\n")
probe_names = set()
for node in ast.walk(probe):
    if isinstance(node, ast.Import):
        probe_names.update(alias.name.split(".")[0] for alias in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        probe_names.add(node.module.split(".")[0])
check("the AST scan would CATCH a forbidden import (it is not vacuous)", probe_names & FORBIDDEN == {"socket", "urllib"})

summarize_and_exit()
