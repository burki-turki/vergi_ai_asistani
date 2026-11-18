# ============================================================
# DEMO P1 - ui/services/demo_p1_facts.py İZOLE TESTİ
#
#   - İKİ bilgi AYRI: hazırlayan (origin) ve alıntı eşleşmesi; eşleşme etiketi DEĞİŞTİRMEZ
#   - alıntı YALNIZ belirtilen FİZİKSEL sayfanın metninde aranır ("belgede ilk eşleşme" YOK);
#     aynı ifade iki sayfada -> her bulgu kendi sayfasına
#   - eşleşmeyen bulgu SESSİZCE DÜŞMEZ ama facts.json'a YAZILMAZ
#   - Ek-2: önceden girilmiş atıf ayrı, uygulamanın denetimi ayrı
#   - facts.json mevcut case_fact_validator'dan geçer; FactRepository/DocumentReferenceResolver
#     demo kökünde (CASES_DIR dışında) çalışır
# ============================================================

import copy
import json
import shutil
import sys
import tempfile
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
    print(f"--- test_demo_p1_facts_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import demo_p1_facts as F  # noqa: E402
from ui.services import demo_p1_intake as I  # noqa: E402
from ui.services import demo_p1_spec as S  # noqa: E402
from ui.services import paths as _paths  # noqa: E402,F401  (src/ sys.path)
import case_fact_validator  # noqa: E402
from fact_repository import FactRepository  # noqa: E402

TEBLIG = "İhbarname, mükellefe 10.02.2026 tarihinde tebliğ edilmiştir."
TEXTS = {
    "ihbarname.pdf": ("SENTETİK ÖRNEK — İHBARNAME\nDüzenleme Tarihi: 05.02.2026\n" + TEBLIG + "\nEkler: Ek-1 Vergi İnceleme Raporu.\f"
                      "SENTETİK ÖRNEK — İHBARNAME (DEVAM)\nİkinci sayfa başlığı DEVAM\n\n" + "bu satır daha uzun bir öneki doldurur. " + TEBLIG
                      + "\nEk-2 (Bilirkişi görüşü) ekte sunulmuştur.\f"),
    "tebligat.pdf": "Tebliğ tarihi: 10.02.2026\f",
    "vir.pdf": "Rapor Tarihi: 20.01.2026\fVergi inceleme sonucunda\nKDV matrahı eksik beyan edilmiş görünmektedir.\nVergi aslı: 850.000,00 TL\f",
}


def finding(fact_id, doc, page, excerpt, kind, statement, origin="ornek", values=None):
    item = {"fact_id": fact_id, "doc_id": doc, "page": page, "excerpt": excerpt, "fact_kind": kind,
            "statement": statement, "origin": origin}
    if values:
        item["degerler"] = values
    return item


DATE = lambda label, iso: [{"value_type": "date", "label": label, "value": iso}]  # noqa: E731
SPEC_RAW = {
    "schema_version": 1, "demo_id": "demo_001",
    "belgeler": [
        {"doc_id": "ihbarname_001", "file_name": "ihbarname.pdf", "document_type": "vergi_ceza_ihbarnamesi",
         "title": "Vergi ve ceza ihbarnamesi (sentetik)", "declared_page_count": 2},
        {"doc_id": "tebligat_001", "file_name": "tebligat.pdf", "document_type": "teblig_mazbatasi",
         "title": "Tebliğ mazbatası (sentetik)", "declared_page_count": 1},
        {"doc_id": "ek_001", "file_name": "vir.pdf", "document_type": "vergi_inceleme_raporu",
         "title": "Vergi inceleme raporu (Ek-1, sentetik)", "declared_page_count": 2},
    ],
    "bulgular": [
        finding("b01_s1", "ihbarname_001", 1, TEBLIG, "date_fact", "Tebliğ (1. sayfa)", values=DATE("Tebliğ tarihi", "2026-02-10")),
        finding("b02_s2", "ihbarname_001", 2, TEBLIG, "date_fact", "Tebliğ (2. sayfa, tekrar)", values=DATE("Tebliğ tarihi", "2026-02-10")),
        finding("b03_teb", "tebligat_001", 1, "Tebliğ tarihi: 10.02.2026", "date_fact", "Mazbata tebliğ tarihi", values=DATE("Tebliğ tarihi", "2026-02-10")),
        finding("b04_wrap", "ek_001", 2, "Vergi inceleme sonucunda KDV matrahı eksik beyan edilmiş görünmektedir.", "administrative_claim", "Satır sonu bölünmüş alıntı"),
        finding("b05_para", "ek_001", 2, "Vergi aslı: 850.000,00 TL", "monetary_fact", "Tutar",
                values=[{"value_type": "money", "label": "Vergi aslı", "value": "850000.00"}]),
        finding("b06_yanlis_sayfa", "ihbarname_001", 2, "Düzenleme Tarihi: 05.02.2026", "date_fact", "Yanlış sayfa (alıntı 1. sayfada)",
                values=DATE("Düzenleme tarihi", "2026-02-05")),
        finding("b07_avukat", "tebligat_001", 1, "Tebliğ tarihi: 10.02.2026", "date_fact", "Avukat girdisi örneği", origin="avukat",
                values=DATE("Tebliğ tarihi", "2026-02-10")),
    ],
    "eksik_atiflar": [
        {"fact_id": "a01_ek2", "referenced_in_doc": "ihbarname_001", "page": 2,
         "excerpt": "Ek-2 (Bilirkişi görüşü) ekte sunulmuştur.", "referenced_name": "Ek-2", "origin": "ornek"},
        {"fact_id": "a02_ek1", "referenced_in_doc": "ihbarname_001", "page": 1,
         "excerpt": "Ekler: Ek-1 Vergi İnceleme Raporu.", "referenced_name": "Ek-1", "origin": "ornek"},
        {"fact_id": "a03_eslesmez", "referenced_in_doc": "ihbarname_001", "page": 1,
         "excerpt": "Ek-9 ekte sunulmuştur.", "referenced_name": "Ek-9", "origin": "ornek"},
    ],
}
SPEC = S.validate_spec(SPEC_RAW)
TMP = Path(tempfile.mkdtemp(prefix="vergi_p1_facts_"))


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except S.DemoError as error:
        return error.code
    except Exception as error:
        return "UNEXPECTED:" + type(error).__name__
    return None


try:
    # ================= find_excerpt / match_status
    text = "İlk satır\nİhbarname, mükellefe\n10.02.2026 tarihinde\ntebliğ edilmiştir. son"
    span = F.find_excerpt(text, "İhbarname, mükellefe 10.02.2026 tarihinde tebliğ edilmiştir.")
    check("find_excerpt: an excerpt wrapped over several lines still matches (whitespace collapsed)", span is not None)
    check("find_excerpt: the returned span slices back to the ORIGINAL text (newlines intact)",
          span is not None and text[span[0]:span[1]] == "İhbarname, mükellefe\n10.02.2026 tarihinde\ntebliğ edilmiştir.")
    check("find_excerpt: matching is CASE-SENSITIVE", F.find_excerpt("Tebliğ Tarihi", "tebliğ tarihi") is None)
    check("find_excerpt: a decomposed (NFD) excerpt matches the NFC page text",
          F.find_excerpt("Şikâyet", "Şikâyet") is not None)
    check("find_excerpt: regex metacharacters in the excerpt are LITERAL", F.find_excerpt("Ek-2 (Bilirkişi). ", "Ek-2 (Bilirkişi).") is not None
          and F.find_excerpt("Ek-2 Xx", "Ek-2 .*") is None)
    check("find_excerpt: an empty/whitespace excerpt never matches", F.find_excerpt("abc", "") is None and F.find_excerpt("abc", "  ") is None)
    pages = ["birinci sayfa " + TEBLIG, "ikinci sayfa, tamamen farklı"]
    check("match_status: found on the stated page -> ESLESTI", F.match_status(pages, 1, TEBLIG) == F.MATCH_OK)
    check("AD-4: the phrase exists ONLY on page 1 but the finding says page 2 -> ESLESMEDI (no whole-document first match)",
          F.match_status(pages, 2, TEBLIG) == F.MATCH_NO)
    check("match_status: a page beyond the document -> SAYFA_YOK", F.match_status(pages, 3, TEBLIG) == F.MATCH_NOPAGE)
    check("match_status: page 0 / negative / non-int -> SAYFA_YOK", all(F.match_status(pages, p, TEBLIG) == F.MATCH_NOPAGE for p in (0, -1, "1", None, 1.5)))
    two = ["x" * 20 + TEBLIG, "y" * 45 + TEBLIG]
    check("AD-4: the SAME phrase on two pages: each page matches, at ITS OWN offset",
          F.match_status(two, 1, TEBLIG) == F.MATCH_OK and F.match_status(two, 2, TEBLIG) == F.MATCH_OK
          and F.find_excerpt(two[0], TEBLIG)[0] == 20 and F.find_excerpt(two[1], TEBLIG)[0] == 45)

    # ================= atıf adı <-> belgeler
    check("name_tokens: Turkish-aware lowercase (İ -> i, I -> ı) and numeric normalization (001 == 1)",
          F.name_tokens("İHBARNAME Ek-001") == ["ihbarname", "ek", "1"] and F.name_tokens("IŞIK") == ["ışık"])
    check("name_tokens: punctuation-only names produce no tokens", F.name_tokens("!!--") == [])

    class D:  # sunulan belge (yalnız kimlik/dosya/başlık)
        def __init__(self, doc_id, file_name, title):
            self.doc_id, self.file_name, self.title = doc_id, file_name, title

    presented = [D("ihbarname_001", "ihbarname.pdf", "Vergi ve ceza ihbarnamesi (sentetik)"),
                 D("tebligat_001", "tebligat.pdf", "Tebliğ mazbatası (sentetik)"),
                 D("ek_001", "vir.pdf", "Vergi inceleme raporu (Ek-1, sentetik)")]
    check("AD-6: 'Ek-2' is NOT found among the presented documents (Ek-2 != Ek-1)", F.system_check_reference("Ek-2", presented) == (F.CHECK_NOT_FOUND, None))
    check("AD-6: 'Ek-1' IS found, in the document whose title carries it", F.system_check_reference("Ek-1", presented) == (F.CHECK_FOUND, "ek_001"))
    check("a differently spelled name finds the same document ('EK 1', 'ek-001')",
          F.system_check_reference("EK 1", presented)[1] == "ek_001" and F.system_check_reference("ek-001", presented)[1] == "ek_001")
    check("a name is matched by the document id too ('tebligat 1' -> tebligat_001)", F.system_check_reference("tebligat 1", presented) == (F.CHECK_FOUND, "tebligat_001"))
    check("an empty-token name is never 'found'", F.system_check_reference("???", presented) == (F.CHECK_NOT_FOUND, None))
    check("the token sequence must be CONTIGUOUS ('Ek 3' is not found because 'ek' and '3' are not adjacent anywhere)",
          F.system_check_reference("Ek 3", [D("a_001", "a.pdf", "Ek rapor 3")]) == (F.CHECK_NOT_FOUND, None))

    # ================= vaka hazırlığı + evaluate
    root = TMP / "demo_kok"
    (root / "belgeler").mkdir(parents=True)
    for name in TEXTS:
        (root / "belgeler" / name).write_bytes(b"%PDF-1.4\n% sentetik " + name.encode() + b"\n")
    docs = I.analyze_documents(root, SPEC, extractor=lambda p: TEXTS[Path(p).name])
    findings, refs = F.evaluate(SPEC, docs)
    by_id = {f.fact_id: f for f in findings}
    check("evaluate: seven findings; six match, ONE (b06) does not", len(findings) == 7 and sum(1 for f in findings if f.written) == 6 and not by_id["b06_yanlis_sayfa"].written)
    check("evaluate: b06's alıntı exists only on page 1 but is claimed on page 2 -> ESLESMEDI", by_id["b06_yanlis_sayfa"].match == F.MATCH_NO)
    check("evaluate: the two-page phrase findings each match their own page",
          by_id["b01_s1"].match == F.MATCH_OK and by_id["b02_s2"].match == F.MATCH_OK and by_id["b01_s1"].page == 1 and by_id["b02_s2"].page == 2)
    check("evaluate: the line-wrapped excerpt matches", by_id["b04_wrap"].match == F.MATCH_OK)
    check("AD-2: a MATCHING pre-prepared finding keeps origin 'ornek' (matching never relabels it as the system's)",
          all(f.origin == "ornek" for f in findings if f.written and f.fact_id != "b07_avukat") and by_id["b07_avukat"].origin == "avukat")
    check("AD-2: an UNMATCHED finding keeps its origin too (the match result and the preparer are separate)",
          by_id["b06_yanlis_sayfa"].origin == "ornek")
    check("evaluate: a missing-ref reports citation match and system check SEPARATELY (Ek-2: matched + not found; Ek-1: matched + found)",
          (refs[0].citation_match, refs[0].system_check, refs[0].found_doc_id) == (F.MATCH_OK, F.CHECK_NOT_FOUND, None)
          and (refs[1].citation_match, refs[1].system_check, refs[1].found_doc_id) == (F.MATCH_OK, F.CHECK_FOUND, "ek_001"))
    check("evaluate: an unmatched citation (Ek-9) is not written but still gets a system check (not found)",
          refs[2].citation_match == F.MATCH_NO and not refs[2].written and refs[2].system_check == F.CHECK_NOT_FOUND)
    check("warning_count counts unmatched findings AND unmatched citations (1 + 1)", F.warning_count(findings, refs) == 2)

    # ================= build_facts_by_doc
    built = F.build_facts_by_doc(SPEC, findings, refs)
    all_ids = {fact["fact_id"] for content in built.values() for fact in content["facts"]}
    check("the UNMATCHED finding and the unmatched citation are NOT in any facts.json (they are not silently written)",
          "b06_yanlis_sayfa" not in all_ids and "a03_eslesmez" not in all_ids)
    check("every matched finding and matched citation IS written (b01 b02 b03 b04 b05 b07 + a01 a02)", all_ids == {"b01_s1", "b02_s2", "b03_teb", "b04_wrap", "b05_para", "b07_avukat", "a01_ek2", "a02_ek1"})
    check("a document with no matched facts gets no facts.json content (a completed extraction must not be empty)",
          set(built.keys()) == {"ihbarname_001", "tebligat_001", "ek_001"})
    empty_spec = copy.deepcopy(SPEC_RAW)
    empty_spec["bulgular"] = [finding("z01_teb", "tebligat_001", 1, "Tebliğ tarihi: 10.02.2026", "date_fact", "x", values=DATE("t", "2026-02-10"))]
    empty_spec["eksik_atiflar"] = []
    espec = S.validate_spec(empty_spec)
    ef, er = F.evaluate(espec, docs)
    check("only documents that have a matched fact appear (tebligat only)", set(F.build_facts_by_doc(espec, ef, er).keys()) == {"tebligat_001"})
    sample = built["ihbarname_001"]
    check("facts.json header: manual extractor, no model/provider, completed, demo note",
          sample["extractor"]["method"] == "manual" and sample["extractor"]["model"] is None and sample["extractor"]["provider"] is None
          and sample["status"] == "completed" and "model/LLM kullanılmadı" in sample["notes"])
    facts_all = [fact for content in built.values() for fact in content["facts"]]
    check("every written fact is 'unverified' and explicit_text with the page + excerpt as its source",
          all(f["verification_state"] == "unverified" and f["extraction_basis"] == "explicit_text"
              and f["source"]["page"] >= 1 and f["source"]["text_excerpt"] for f in facts_all))
    by_fact = {f["fact_id"]: f for f in facts_all}
    check("structured values: date -> date_value ISO; money -> money_value {amount, currency}; others null",
          by_fact["b01_s1"]["structured_values"][0]["date_value"] == "2026-02-10"
          and by_fact["b05_para"]["structured_values"][0]["money_value"] == {"amount": "850000.00", "currency": "TRY"}
          and by_fact["b05_para"]["structured_values"][0]["date_value"] is None)
    check("the Ek-2 citation becomes an evidence_reference fact with a reference structured value",
          by_fact["a01_ek2"]["fact_kind"] == "evidence_reference" and by_fact["a01_ek2"]["structured_values"][0]["value_type"] == "reference"
          and by_fact["a01_ek2"]["structured_values"][0]["reference_value"] == "Ek-2")
    check("the fact notes state the preparer in words ('Önceden hazırlanmış örnek' / 'Avukat girdisi')",
          "Önceden hazırlanmış örnek" in by_fact["b01_s1"]["notes"] and "Avukat girdisi" in by_fact["b07_avukat"]["notes"]
          and not any("Sistem çıkardı" in f["notes"] for f in facts_all))

    # ================= write_facts (disk) + doğrulayıcılar
    case_dir = I.write_case(root, SPEC, docs)
    written = F.write_facts(case_dir, SPEC, findings, refs)
    check("write_facts: one facts.json per document that has matched facts", set(written) == {"ihbarname_001", "tebligat_001", "ek_001"})
    revalidated = True
    for doc_id, path in written.items():
        try:
            case_fact_validator.validate_fact_extraction(facts_path=str(path), raise_on_error=True)
        except Exception:
            revalidated = False
    check("every written facts.json passes the EXISTING case_fact_validator (re-run independently, outside CASES_DIR)", revalidated)
    bad = json.loads(Path(written["tebligat_001"]).read_text(encoding="utf-8"))
    bad["facts"][0]["fact_kind"] = "date_fact"
    bad["facts"][0]["structured_values"] = []
    broken_path = TMP / "facts_bozuk.json"
    broken_path.write_text(json.dumps(bad), encoding="utf-8")
    try:
        # bozuk dosyayı vaka düzeninde sına: aynı yerleşim, farklı içerik
        shutil.copytree(case_dir, TMP / "kopya_vaka")
        (TMP / "kopya_vaka" / "documents" / "tebligat_001" / "extractions" / "facts.json").write_text(json.dumps(bad), encoding="utf-8")
        case_fact_validator.validate_fact_extraction(facts_path=str(TMP / "kopya_vaka" / "documents" / "tebligat_001" / "extractions" / "facts.json"), raise_on_error=True)
        refuses = False
    except Exception:
        refuses = True
    check("the validator is not vacuous: a date_fact WITHOUT a date value is refused", refuses)
    labels = json.loads((case_dir / F.LABELS_NAME).read_text(encoding="utf-8"))["labels"]
    check("the content-label side file covers EVERY written fact and nothing else", set(labels) == all_ids)
    check("labels carry the preparer in words; none is the system's",
          labels["b01_s1"]["origin_label"] == "Önceden hazırlanmış örnek" and labels["b07_avukat"]["origin_label"] == "Avukat girdisi"
          and all(v["origin"] in ("ornek", "avukat") for v in labels.values()))
    check("a write_facts call does NOT overwrite (second call -> DIZIN_MEVCUT)", code_of(F.write_facts, case_dir, SPEC, findings, refs) == "DIZIN_MEVCUT")

    repo = FactRepository(case_dir.parent)
    try:
        records = repo.get_all_facts("demo_001")
        repo_ok = len(records) == len(all_ids)
    except Exception as error:
        repo_ok = False
    check("FactRepository(cases_dir) reads the demo facts outside CASES_DIR (count == written facts)", repo_ok)

    # ================= atıf çözücü
    ek2 = json.loads(Path(written["ihbarname_001"]).read_text(encoding="utf-8"))
    fact_ek2 = next(f for f in ek2["facts"] if f["fact_id"] == "a01_ek2")
    check("DocumentReferenceResolver (demo root): the Ek-2 reference is UNRESOLVED",
          F.resolver_unresolved(case_dir.parent, "demo_001", fact_ek2, "ihbarname_001") == ["Ek-2"])
    check("the resolver cross-check degrades to None (never raises) when the case dir is missing",
          F.resolver_unresolved(TMP / "yok", "demo_001", fact_ek2, "ihbarname_001") is None)

    # ================= sonuç kaydı
    record = F.build_result_record(SPEC, docs, findings, refs, resolver_info={"a01_ek2": ["Ek-2"]})
    check("result record: validates, counts and flags are right",
          F.validate_result_record(copy.deepcopy(record)) and record["warning_count"] == 2
          and [f["match"] for f in record["findings"]].count("ESLESTI") == 6)
    check("result record: the preparer is never 'sistem' anywhere",
          all(f["origin"] in ("ornek", "avukat") for f in record["findings"]) and all(r["origin"] in ("ornek", "avukat") for r in record["missing_refs"]))
    check("result record: the match and the preparer are SEPARATE fields of every finding",
          all("match" in f and "origin" in f for f in record["findings"]))
    check("result record: the PDF sha256 and page counts are stored per document",
          [(d["doc_id"], d["page_count"]) for d in record["documents"]] == [("ihbarname_001", 2), ("tebligat_001", 1), ("ek_001", 2)]
          and all(len(d["sha256"]) == 64 for d in record["documents"]))

    def rec_code(mutator):
        broken = copy.deepcopy(record)
        mutator(broken)
        try:
            F.validate_result_record(broken)
        except S.DemoError as error:
            return error.code
        return None

    check("result record: an unknown top-level key is refused (SONUC_KAYDI_GECERSIZ)", rec_code(lambda r: r.update({"x": 1})) == "SONUC_KAYDI_GECERSIZ")
    check("result record: an unknown match value is refused", rec_code(lambda r: r["findings"][0].update({"match": "BELKI"})) == "SONUC_KAYDI_GECERSIZ")
    check("result record: an unknown origin on a finding is refused", rec_code(lambda r: r["findings"][0].update({"origin": "model"})) == "SONUC_KAYDI_GECERSIZ")
    check("result record: a finding for an unknown document is refused", rec_code(lambda r: r["findings"][0].update({"doc_id": "yok"})) == "SONUC_KAYDI_GECERSIZ")
    check("result record: a non-bool 'written' is refused", rec_code(lambda r: r["findings"][0].update({"written": 1})) == "SONUC_KAYDI_GECERSIZ")
    check("result record: a bad system_check value is refused", rec_code(lambda r: r["missing_refs"][0].update({"system_check": "BELKI"})) == "SONUC_KAYDI_GECERSIZ")
    check("result record: found_doc_id must be a presented document", rec_code(lambda r: r["missing_refs"][0].update({"found_doc_id": "yok"})) == "SONUC_KAYDI_GECERSIZ")
    check("result record: a non-object record is refused", code_of(F.validate_result_record, [1]) == "SONUC_KAYDI_GECERSIZ")
    check("result record: write_result_record persists canonical JSON that round-trips",
          (F.write_result_record(case_dir, record), json.loads((case_dir / F.RESULT_NAME).read_text(encoding="utf-8")) == record)[1])
    check("result record: writing it twice is refused (DOSYA_MEVCUT; no overwrite)", code_of(F.write_result_record, case_dir, record) == "DOSYA_MEVCUT")

    # ================= P1-L-C: facts.json money_value alıntıyla tutarlı (işaret + para birimi)
    cur_raw = copy.deepcopy(SPEC_RAW)
    cur_raw["bulgular"] = [
        finding("c01_usd", "ek_001", 2, "Vergi aslı: 1.250,50 USD", "monetary_fact", "USD tutar", values=[{"value_type": "money", "label": "Tutar", "value": "1250.50", "currency": "USD"}]),
        finding("c02_neg", "ek_001", 2, "Düzeltme: -2.000,00 TL", "monetary_fact", "Negatif tutar", values=[{"value_type": "money", "label": "Tutar", "value": "-2000.00"}]),
        finding("c03_try", "ek_001", 2, "Vergi aslı: 850.000,00 TL", "monetary_fact", "TRY tutar", values=[{"value_type": "money", "label": "Tutar", "value": "850000.00"}]),
    ]
    cur_raw["eksik_atiflar"] = []
    cur_texts = dict(TEXTS)
    cur_texts["vir.pdf"] = "Rapor Tarihi: 20.01.2026\fVergi aslı: 1.250,50 USD\nDüzeltme: -2.000,00 TL\nVergi aslı: 850.000,00 TL\f"
    cur_root = TMP / "para_kok"
    (cur_root / "belgeler").mkdir(parents=True)
    for name in cur_texts:
        (cur_root / "belgeler" / name).write_bytes(b"%PDF-1.4\n% sentetik " + name.encode() + b"\n")
    cur_spec = S.validate_spec(cur_raw)
    cur_docs = I.analyze_documents(cur_root, cur_spec, extractor=lambda p: cur_texts[Path(p).name])
    cur_findings, cur_refs = F.evaluate(cur_spec, cur_docs)
    cur_facts = {f["fact_id"]: f for content in F.build_facts_by_doc(cur_spec, cur_findings, cur_refs).values() for f in content["facts"]}
    check("P1-L-C: facts.json money_value.currency follows the excerpt/spec (USD stays USD, TRY stays TRY)",
          cur_facts["c01_usd"]["structured_values"][0]["money_value"] == {"amount": "1250.50", "currency": "USD"}
          and cur_facts["c03_try"]["structured_values"][0]["money_value"] == {"amount": "850000.00", "currency": "TRY"})
    check("P1-L-C: a negative amount keeps its sign in facts.json (the minus is not lost)",
          cur_facts["c02_neg"]["structured_values"][0]["money_value"] == {"amount": "-2000.00", "currency": "TRY"})
    cur_case = I.write_case(cur_root, cur_spec, cur_docs)
    cur_written = F.write_facts(cur_case, cur_spec, cur_findings, cur_refs)
    check("P1-L-C: the signed / USD amounts pass the existing case_fact_validator (schema: -?digits, ^[A-Z]{3}$)", set(cur_written) == {"ek_001"})

    # ================= L-2: sistem denetimi (atfı içeren belge aday değil; en az bir sayı + bir sözcük; bitişik jeton)
    self_cited = [D("ihbarname_001", "ihbarname.pdf", "İhbarname (Ek-2 atfı içerir)"),
                  D("tebligat_001", "tebligat.pdf", "Tebliğ mazbatası (sentetik)")]
    check("L-2: the document that CONTAINS the citation is not a candidate (its own title 'Ek-2 atfı içerir' must not read as 'found')",
          F.system_check_reference("Ek-2", self_cited, exclude_doc_id="ihbarname_001") == (F.CHECK_NOT_FOUND, None))
    check("L-2: without the exclusion the same title WOULD match (the exclusion is what prevents the false 'bulundu')",
          F.system_check_reference("Ek-2", self_cited) == (F.CHECK_FOUND, "ihbarname_001"))
    other_has = self_cited + [D("ek_002", "ek2.pdf", "Bilirkişi görüşü (Ek-2)")]
    check("L-2: a DIFFERENT presented document that carries Ek-2 is still found", F.system_check_reference("Ek-2", other_has, exclude_doc_id="ihbarname_001") == (F.CHECK_FOUND, "ek_002"))
    check("L-2: 'Ek' alone never returns 'found' (no number)", F.system_check_reference("Ek", presented) == (F.CHECK_NOT_FOUND, None))
    check("L-2: '2' alone never returns 'found' (no word)", F.system_check_reference("2", other_has) == (F.CHECK_NOT_FOUND, None))
    check("L-2: 'EK2' (no hyphen/space) matches 'Ek-2' (adjacent-token normalization 'ek2' == 'ek 2')", F.system_check_reference("EK2", other_has, exclude_doc_id="ihbarname_001")[0] == F.CHECK_FOUND)
    check("L-2: a document titled 'EK2' matches the name 'Ek-2'", F.system_check_reference("Ek-2", [D("x_001", "x.pdf", "EK2 belgesi")])[0] == F.CHECK_FOUND)
    check("L-2: 'EK-II' matches 'Ek-2' (roman numeral 2)", F.system_check_reference("EK-II", other_has, exclude_doc_id="ihbarname_001")[0] == F.CHECK_FOUND)
    check("L-2: Ek-2 vs Ek-20 stays distinct (both directions)",
          F.system_check_reference("Ek-2", [D("a_001", "a.pdf", "Ek-20 raporu")])[0] == F.CHECK_NOT_FOUND
          and F.system_check_reference("Ek-20", [D("a_001", "a.pdf", "Ek-2 raporu")])[0] == F.CHECK_NOT_FOUND)
    check("L-2: name_tokens splits letter/digit boundaries and maps multi-letter roman numerals only",
          F.name_tokens("EK2") == ["ek", "2"] and F.name_tokens("Ek-II") == ["ek", "2"] and F.name_tokens("Ek-V") == ["ek", "v"])
    self_spec = copy.deepcopy(SPEC_RAW)
    self_spec["belgeler"][0]["title"] = "İhbarname (Ek-2 atfı içerir)"
    self_root = TMP / "self_kok"
    (self_root / "belgeler").mkdir(parents=True)
    for name in TEXTS:
        (self_root / "belgeler" / name).write_bytes(b"%PDF-1.4\n% sentetik " + name.encode() + b"\n")
    self_s = S.validate_spec(self_spec)
    self_docs = I.analyze_documents(self_root, self_s, extractor=lambda p: TEXTS[Path(p).name])
    _, self_refs = F.evaluate(self_s, self_docs)
    check("L-2 (end to end): an ihbarname titled '(Ek-2 atfı içerir)' no longer turns the Ek-2 citation into 'found'",
          [r.system_check for r in self_refs][0] == F.CHECK_NOT_FOUND and self_refs[0].found_doc_id is None)

    # ================= P1-L-F: Ek-2 sistem denetiminde iki YANLIŞ 'bulundu' + belirsizlik kuralı
    def ek2(title, file_name="x.pdf", doc_id="x_001"):
        return F.system_check_reference("Ek-2", [D(doc_id, file_name, title)])[0]

    check("L-F (a): a document titled 'Ek 2 değildir; Ek-3' is NOT 'Ek-2' (two different 'ek N' references: ambiguous -> BULUNAMADI)",
          ek2("Ek 2 değildir; Ek-3") == F.CHECK_NOT_FOUND)
    check("L-F (b): a document titled 'Ek-2.1 tablo' is NOT 'Ek-2' (2.1 is one numeric token) -> BULUNAMADI",
          ek2("Ek-2.1 tablo") == F.CHECK_NOT_FOUND and ek2("Ek-2,1 tablo") == F.CHECK_NOT_FOUND and ek2("Ek 2.10 ayrıntı") == F.CHECK_NOT_FOUND)
    check("L-F: the same decimal rule on the file name (ek2.1.pdf) -> BULUNAMADI",
          ek2("Belge", "ek2.1.pdf") == F.CHECK_NOT_FOUND)
    check("L-F positive: genuine Ek-2 titles are still FOUND ('Ek-2', 'EK-2 Bilirkişi Raporu', 'Ek-02', 'Ek-II', 'Ek-2.', 'Ek-2, sentetik', 'Ek 2')",
          all(ek2(title) == F.CHECK_FOUND for title in ("Ek-2", "EK-2 Bilirkişi Raporu", "Ek-02", "Ek-II", "Ek-2.", "Ek-2, sentetik", "Ek 2", "Bilirkişi görüşü (Ek-2)")))
    check("L-F positive: a genuine Ek-2 by file name ('ek2.pdf') or by document id ('ek_002', 'ek_2') is still FOUND",
          ek2("Bilirkişi görüşü", "ek2.pdf") == F.CHECK_FOUND and ek2("Bilirkişi görüşü", "belge.pdf", "ek_002") == F.CHECK_FOUND
          and ek2("Bilirkişi görüşü", "belge.pdf", "ek_2") == F.CHECK_FOUND)
    check("L-F: the SAME number twice ('Ek-2 ... Ek-2') is not ambiguous (found)", ek2("Ek-2 raporu ve Ek-2 eki") == F.CHECK_FOUND)
    check("L-F disclosed fail-closed case: a genuine multi-reference title 'Ek-2 ve Ek-3 birleşik' returns BULUNAMADI for Ek-2 AND for Ek-3",
          ek2("Ek-2 ve Ek-3 birleşik") == F.CHECK_NOT_FOUND
          and F.system_check_reference("Ek-3", [D("x_001", "x.pdf", "Ek-2 ve Ek-3 birleşik")])[0] == F.CHECK_NOT_FOUND)
    check("L-F: ... but the same document is still found through an UNAMBIGUOUS source (file name ek2.pdf)",
          ek2("Ek-2 ve Ek-3 birleşik", "ek2.pdf") == F.CHECK_FOUND)
    check("L-F: another lead word is not confused: 'Ek-2' is not blocked by 'Ek-3' in a different word context ('Ek-2 raporu, Ekim 3')",
          ek2("Ek-2 raporu, Ekim 3. gün") == F.CHECK_FOUND)
    check("L-F: name_tokens keeps decimals as ONE token and normalizes parts (Ek-2.1 -> ek, 2.1; Ek-02 -> ek, 2; 2,1 -> 2.1)",
          F.name_tokens("Ek-2.1") == ["ek", "2.1"] and F.name_tokens("Ek-02") == ["ek", "2"] and F.name_tokens("Ek 2,1") == ["ek", "2.1"]
          and F.name_tokens("Ek-2.") == ["ek", "2"])
    amb_spec = copy.deepcopy(SPEC_RAW)
    amb_spec["belgeler"][1]["title"] = "Ek 2 değildir; Ek-3"
    amb_s = S.validate_spec(amb_spec)
    amb_docs = I.analyze_documents(self_root, amb_s, extractor=lambda p: TEXTS[Path(p).name])
    _, amb_refs = F.evaluate(amb_s, amb_docs)
    check("L-F (end to end): with such a title among the presented documents the Ek-2 citation stays BULUNAMADI; the pre-prepared citation (origin 'ornek', ESLESTI) and the system check are separate fields",
          amb_refs[0].system_check == F.CHECK_NOT_FOUND and amb_refs[0].found_doc_id is None and amb_refs[0].origin == "ornek"
          and amb_refs[0].citation_match == F.MATCH_OK)

    # ================= L-3: sonuç kaydı doğrulaması (desen/yol, çelişki, tutarlılık)
    check("L-3: a doc_id with path traversal ('..') is refused", rec_code(lambda r: r["documents"][0].update({"doc_id": ".."})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a doc_id with a separator is refused", rec_code(lambda r: r["documents"][0].update({"doc_id": "a/bcd"})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: an absolute pdf_rel is refused", rec_code(lambda r: r["documents"][0].update({"pdf_rel": "C:/Windows/system32/x.pdf"})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a pdf_rel with '..' is refused", rec_code(lambda r: r["documents"][0].update({"pdf_rel": "../../x.pdf"})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a pdf_rel with a backslash is refused", rec_code(lambda r: r["documents"][0].update({"pdf_rel": "documents\\\\x\\\\y.pdf"})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a pdf_rel that is not exactly documents/<doc_id>/<file_name> is refused",
          rec_code(lambda r: r["documents"][0].update({"pdf_rel": "documents/baska_belge/x.pdf"})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a file_name with a separator is refused", rec_code(lambda r: r["documents"][0].update({"file_name": "a/b.pdf"})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a malformed sha256 is refused", rec_code(lambda r: r["documents"][0].update({"sha256": "xyz"})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a duplicate doc_id is refused", rec_code(lambda r: r["documents"][1].update({"doc_id": r["documents"][0]["doc_id"], "pdf_rel": r["documents"][0]["pdf_rel"], "file_name": r["documents"][0]["file_name"]})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a contradictory finding (match=ESLESMEDI but written=True) is refused",
          rec_code(lambda r: (r["findings"][next(i for i, f in enumerate(r["findings"]) if f["match"] == "ESLESMEDI")].update({"written": True}),
                              r.update({"warning_count": r["warning_count"] - 1}))) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: the opposite contradiction (match=ESLESTI but written=False) is refused",
          rec_code(lambda r: (r["findings"][0].update({"written": False}),
                              r.update({"warning_count": r["warning_count"] + 1}))) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a contradictory citation (citation_match=ESLESTI but citation_written=False) is refused",
          rec_code(lambda r: (r["missing_refs"][0].update({"citation_written": False}),
                              r.update({"warning_count": r["warning_count"] + 1}))) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a warning_count that disagrees with the records is refused", rec_code(lambda r: r.update({"warning_count": 0})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: system_check=BULUNDU without a found_doc_id (and the reverse) is refused",
          rec_code(lambda r: r["missing_refs"][0].update({"system_check": "BULUNDU", "found_doc_id": None})) == "SONUC_KAYDI_GECERSIZ"
          and rec_code(lambda r: r["missing_refs"][0].update({"system_check": "BULUNAMADI", "found_doc_id": r["documents"][0]["doc_id"]})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: a fact_id with unsafe characters is refused", rec_code(lambda r: r["findings"][0].update({"fact_id": "A B"})) == "SONUC_KAYDI_GECERSIZ")
    check("L-3: the genuine record still validates after the tightening", F.validate_result_record(copy.deepcopy(record)) == record)

    # ================= L-7: üretim kodu validate_fact_extraction'ı GERÇEKTEN çağırır ve hatasını kapalı koda çevirir
    seen = []
    original_validate = case_fact_validator.validate_fact_extraction
    try:
        root_v = TMP / "izle_kok"
        (root_v / "belgeler").mkdir(parents=True)
        for name in TEXTS:
            (root_v / "belgeler" / name).write_bytes(b"%PDF-1.4\n% sentetik " + name.encode() + b"\n")
        docs_v = I.analyze_documents(root_v, SPEC, extractor=lambda p: TEXTS[Path(p).name])
        findings_v, refs_v = F.evaluate(SPEC, docs_v)
        case_v = I.write_case(root_v, SPEC, docs_v)
        case_fact_validator.validate_fact_extraction = lambda **kw: seen.append(kw)
        written_v = F.write_facts(case_v, SPEC, findings_v, refs_v)
        check("L-7: write_facts CALLS validate_fact_extraction once per facts.json, with that file and raise_on_error=True",
              len(seen) == len(written_v) == 3 and {Path(kw["facts_path"]) for kw in seen} == set(written_v.values())
              and all(kw.get("raise_on_error") is True for kw in seen), str(seen)[:200])

        def failing_validator(**kw):
            raise ValueError("şema ihlali")

        case_fact_validator.validate_fact_extraction = failing_validator
        root_w = TMP / "hata_kok"
        (root_w / "belgeler").mkdir(parents=True)
        for name in TEXTS:
            (root_w / "belgeler" / name).write_bytes(b"%PDF-1.4\n% sentetik " + name.encode() + b"\n")
        docs_w = I.analyze_documents(root_w, SPEC, extractor=lambda p: TEXTS[Path(p).name])
        findings_w, refs_w = F.evaluate(SPEC, docs_w)
        case_w = I.write_case(root_w, SPEC, docs_w)
        check("L-7: a validator failure becomes the closed code OLGU_DOGRULAMA_BASARISIZ (no message/content)",
              code_of(F.write_facts, case_w, SPEC, findings_w, refs_w) == "OLGU_DOGRULAMA_BASARISIZ")
    finally:
        case_fact_validator.validate_fact_extraction = original_validate
finally:
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
