# ============================================================
# DEMO P1 - ui/services/demo_p1_report.py İZOLE TESTİ
#
#   - statik, dış kaynaksız, betiksiz HTML; tüm metin kaçışlı
#   - her bulguda İKİ bilgi AYRI satırlarda (Hazırlayan / Alıntı eşleşmesi); eşleşme etiketi değiştirmez
#   - "Sistem çıkardı" YALNIZ uygulamanın atıf denetiminde görünür
#   - aynı ifade iki sayfada: bağlantı ve vurgu YALNIZ kendi sayfasında
#   - bağlantı olmadan da belge adı + fiziksel sayfa + sayfa metni görünür
#   - dosya bağlantısı yüzde-kodlu; sayfa parçası #page=N
#   - Ek-2: iki ayrı bilgi + birleşik cümle; Ek-1: bulundu
#   - rapor yazılımın hukuki sonuç cümlesi üretmez; yalnız vaka dizinini okur
# ============================================================

import copy
import hashlib
import json
import os
import re
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
    print(f"--- test_demo_p1_report_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import demo_p1_facts as F  # noqa: E402
from ui.services import demo_p1_intake as I  # noqa: E402
from ui.services import demo_p1_report as P  # noqa: E402
from ui.services import demo_p1_spec as S  # noqa: E402

TEBLIG = "İhbarname, mükellefe 10.02.2026 tarihinde tebliğ edilmiştir."
NASTY_TITLE = 'Vergi ve ceza ihbarnamesi <script>alert(1)</script> & "q"'
TEXTS = {
    "ihbarname.pdf": ("SAYFA-BIR-BASLIK\nDüzenleme Tarihi: 05.02.2026\n" + TEBLIG + "\nEkler: Ek-1 Vergi İnceleme Raporu.\n"
                      "<img src=x onerror=alert(1)>\f"
                      "SAYFA-IKI-BASLIK\nuzun bir önek satırı. " + TEBLIG + "\nEk-2 (Bilirkişi görüşü) ekte sunulmuştur.\f"),
    "tebligat.pdf": "Tebliğ tarihi: 10.02.2026\f",
    "vir.pdf": "Rapor Tarihi: 20.01.2026\fVergi aslı: 850.000,00 TL\f",
}
DATE = lambda iso: [{"value_type": "date", "label": "Tarih", "value": iso}]  # noqa: E731


def finding(fact_id, doc, page, excerpt, kind, statement, origin="ornek", values=None):
    item = {"fact_id": fact_id, "doc_id": doc, "page": page, "excerpt": excerpt, "fact_kind": kind,
            "statement": statement, "origin": origin}
    if values:
        item["degerler"] = values
    return item


SPEC_RAW = {
    "schema_version": 1, "demo_id": "demo_001",
    "belgeler": [
        {"doc_id": "ihbarname_001", "file_name": "ihbarname.pdf", "document_type": "vergi_ceza_ihbarnamesi",
         "title": NASTY_TITLE, "declared_page_count": 2},
        {"doc_id": "tebligat_001", "file_name": "tebligat.pdf", "document_type": "teblig_mazbatasi",
         "title": "Tebliğ mazbatası (sentetik)", "declared_page_count": 1},
        {"doc_id": "ek_001", "file_name": "vir.pdf", "document_type": "vergi_inceleme_raporu",
         "title": "Vergi inceleme raporu (Ek-1, sentetik)", "declared_page_count": 2},
    ],
    "bulgular": [
        finding("b01_s1", "ihbarname_001", 1, TEBLIG, "date_fact", "Tebliğ (1. sayfa)", values=DATE("2026-02-10")),
        finding("b02_s2", "ihbarname_001", 2, TEBLIG, "date_fact", "Tebliğ (2. sayfa)", values=DATE("2026-02-10")),
        finding("b03_html", "ihbarname_001", 1, "<img src=x onerror=alert(1)>", "other", "<b>kalın</b> & ifade"),
        finding("b04_avukat", "tebligat_001", 1, "Tebliğ tarihi: 10.02.2026", "date_fact", "Avukat girdisi", origin="avukat", values=DATE("2026-02-10")),
        finding("b05_yanlis", "ihbarname_001", 2, "Düzenleme Tarihi: 05.02.2026", "date_fact", "Yanlış sayfa", values=DATE("2026-02-05")),
    ],
    "eksik_atiflar": [
        {"fact_id": "a01_ek2", "referenced_in_doc": "ihbarname_001", "page": 2,
         "excerpt": "Ek-2 (Bilirkişi görüşü) ekte sunulmuştur.", "referenced_name": "Ek-2", "origin": "ornek"},
        {"fact_id": "a02_ek1", "referenced_in_doc": "ihbarname_001", "page": 1,
         "excerpt": "Ekler: Ek-1 Vergi İnceleme Raporu.", "referenced_name": "Ek-1", "origin": "ornek"},
    ],
}

TMP = Path(tempfile.mkdtemp(prefix="vergi_p1_report_"))


def build_case(root_name, spec_raw=SPEC_RAW, texts=TEXTS):
    """Gerçek hat: analiz -> değerlendirme -> vaka -> olgular -> sonuç kaydı (enjekte çıkarıcı)."""
    root = TMP / root_name
    (root / "belgeler").mkdir(parents=True)
    for name in texts:
        (root / "belgeler" / name).write_bytes(b"%PDF-1.4\n% sentetik " + name.encode() + b"\n")
    spec = S.validate_spec(copy.deepcopy(spec_raw))
    docs = I.analyze_documents(root, spec, extractor=lambda p: texts[Path(p).name])
    findings, refs = F.evaluate(spec, docs)
    case_dir = I.write_case(root, spec, docs)
    written = F.write_facts(case_dir, spec, findings, refs)
    info = {}
    for ref in refs:
        if ref.written:
            content = json.loads(Path(written[ref.referenced_in_doc]).read_text(encoding="utf-8"))
            fact = next(x for x in content["facts"] if x["fact_id"] == ref.fact_id)
            info[ref.fact_id] = F.resolver_unresolved(case_dir.parent, spec.demo_id, fact, ref.referenced_in_doc)
    F.write_result_record(case_dir, F.build_result_record(spec, docs, findings, refs, resolver_info=info))
    return root, case_dir


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except S.DemoError as error:
        return error.code
    except Exception as error:
        return "UNEXPECTED:" + type(error).__name__
    return None


def section(html_text, section_id):
    start = html_text.index(f'id="{section_id}"')
    start = html_text.rfind("<section", 0, start)
    end = html_text.index("</section>", start) + len("</section>")
    return html_text[start:end]


try:
    root, case_dir = build_case("kok ş demo")  # boşluk + Türkçe karakter: bağlantı kodlaması
    data = P.load_report_data(case_dir)
    page = P.render_html(data)

    # ================= yapı / güvenlik
    check("the page is a complete static HTML document with the DEMO — SENTETİK banner",
          page.startswith("<!DOCTYPE html>") and page.rstrip().endswith("</html>") and "DEMO — SENTETİK" in page)
    check("AD-11: no script, no external resource: no <script, <link, <img, <iframe, <object, @import, url(, http(s)://",
          not re.search(r"<script|<link|<img\b|<iframe|<object|<embed|@import|url\(|https?://", page, re.I))
    real_tags = re.findall(r"<[a-zA-Z][^>]*>", page)
    check("no real tag carries an event-handler attribute (on...=); escaped text is not a tag",
          bool(real_tags) and not [t for t in real_tags if re.search(r"\son\w+\s*=", t, re.I)])
    hrefs = re.findall(r'href="([^"]*)"', page)
    check("every link is either an in-page anchor (#bulgu-/#atif-) or a file:/// PDF link",
          bool(hrefs) and all(h.startswith(("#bulgu-", "#atif-", "file:///")) for h in hrefs), str(hrefs[:5]))
    check("no src= attribute anywhere", "src=" not in page.replace("&lt;img src=x", ""))
    check("AD-8: the explanatory note says the software produces no legal conclusion",
          "Hukuki sonuç, görüş veya karar içermez" in page)
    text_only = re.sub(r"<[^>]+>", " ", page)
    for phrase in ("süre geçmiştir", "dava açılabilir", "hak düşürücü", "zamanaşımı", "kesinleşmiştir", "iptal edilmelidir", "haklıdır", "kazanır"):
        check(f"AD-8: the report never states the legal conclusion {phrase!r}", phrase not in text_only)
    check("rendering is deterministic (same data -> same bytes)", page == P.render_html(P.load_report_data(case_dir)))

    # ================= kaçış
    check("the nasty document title is ESCAPED everywhere (no raw <script> tag)", "<script" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page)
    check("a page text containing an <img onerror> tag is escaped inside the <pre>", "&lt;img src=x onerror=alert(1)&gt;" in page and "<img" not in page)
    check("a statement with <b> and & is escaped (&lt;b&gt; ... &amp;)", "&lt;b&gt;kalın&lt;/b&gt; &amp; ifade" in page)

    # ================= iki bilgi ayrı
    sec1 = section(page, "bulgu-b01_s1")
    check("AD-2: a finding carries 'Hazırlayan' and 'Alıntı eşleşmesi' as TWO separate <dt>/<dd> rows",
          "<dt>Hazırlayan</dt><dd" in sec1 and "<dt>Alıntı eşleşmesi</dt><dd" in sec1
          and sec1.index("<dt>Hazırlayan</dt>") < sec1.index("<dt>Alıntı eşleşmesi</dt>"))
    check("AD-7: the preparer row says only the preparer ('Önceden hazırlanmış örnek') and never the match word",
          re.search(r'<dt>Hazırlayan</dt><dd class="hazirlayan">([^<]*)</dd>', sec1).group(1) == "Önceden hazırlanmış örnek")
    check("the match row states the match with document title and physical page",
          "EŞLEŞTİ" in sec1 and "fiziksel sayfa 1 metninde bulundu" in sec1)
    sec_lawyer = section(page, "bulgu-b04_avukat")
    check("an 'avukat' finding shows 'Avukat girdisi' as the preparer",
          re.search(r'<dt>Hazırlayan</dt><dd class="hazirlayan">([^<]*)</dd>', sec_lawyer).group(1) == "Avukat girdisi")
    sec_bad = section(page, "bulgu-b05_yanlis")
    check("AD-2: the UNMATCHED finding shows EŞLEŞMEDİ but its preparer stays 'Önceden hazırlanmış örnek' (match never relabels)",
          "EŞLEŞMEDİ" in sec_bad and re.search(r'<dt>Hazırlayan</dt><dd class="hazirlayan">([^<]*)</dd>', sec_bad).group(1) == "Önceden hazırlanmış örnek")
    check("the unmatched finding is listed ONLY under the warning heading (not in the matched table/sections)",
          'class="bulgu uyari"' in sec_bad and 'id="bulgu-b05_yanlis"' not in page.split("Alıntısı eşleşmeyen örnek bulgular</h2>")[0]
          and "Bu bulgular olgu kaydına YAZILMADI" in page)
    check("every finding block says it is unverified (unverified)", all("doğrulanmamış (unverified)" in section(page, f"bulgu-{i}") for i in ("b01_s1", "b02_s2", "b03_html", "b04_avukat", "b05_yanlis")))
    check("AD-2: 'Sistem çıkardı' appears ONLY in the application's own reference check (once per citation record: 2)",
          page.count("Sistem çıkardı") == 2 and all("Sistem çıkardı" not in section(page, f"bulgu-{i}") for i in ("b01_s1", "b02_s2", "b03_html", "b04_avukat", "b05_yanlis")))
    check("the summary line counts documents, matched, unmatched and citations (3 / 4 / 1 / 2)",
          "Belge: 3 · Eşleşen bulgu: 4 · Alıntısı eşleşmeyen: 1 · Atıf kaydı: 2" in page)

    # ================= aynı ifade iki sayfada
    sec_p1, sec_p2 = section(page, "bulgu-b01_s1"), section(page, "bulgu-b02_s2")
    check("AD-4: the page-1 finding links to #page=1 and the page-2 finding to #page=2",
          '#page=1">' in sec_p1 and '#page=2">' in sec_p2 and '#page=2"' not in sec_p1 and '#page=1"' not in sec_p2)
    check("AD-4: the page-2 finding shows page 2's text (SAYFA-IKI) and NOT page 1's (SAYFA-BIR)",
          "SAYFA-IKI-BASLIK" in sec_p2 and "SAYFA-BIR-BASLIK" not in sec_p2)
    check("AD-4: exactly one highlight (<mark>) in each block, wrapping the excerpt text",
          sec_p1.count("<mark>") == 1 and sec_p2.count("<mark>") == 1 and f"<mark>{TEBLIG}</mark>" in sec_p2)
    check("the highlight is inside the page text, not in the bare quote line",
          "<q>" + TEBLIG + "</q>" in sec_p2 and sec_p2.index("<mark>") > sec_p2.index("<pre>"))
    check("the unmatched block has NO <mark> (nothing to highlight on that page)", "<mark>" not in sec_bad)
    check("the physical page is shown as 'N / total'", "<dt>Fiziksel sayfa</dt><dd>2 / 2</dd>" in sec_p2)

    # ================= bağlantı kodlaması
    uri_ihb = data.pdf_uri["ihbarname_001"]
    check("AD-3: the link is a file:/// URI with percent-encoded space and non-ASCII characters (no raw space or 'ş')",
          uri_ihb.startswith("file:///") and " " not in uri_ihb and "ş" not in uri_ihb and "%20" in uri_ihb and "%C5%9F" in uri_ihb, uri_ihb)
    check("the page fragment is appended AFTER the encoded path (…pdf#page=2)", f'href="{uri_ihb}#page=2"' in sec_p2)
    check("the document table also links each PDF at #page=1", page.count("#page=1\">PDF'i aç</a>") == 3)

    # ================= Ek-2 / Ek-1
    ek2, ek1 = section(page, "atif-a01_ek2"), section(page, "atif-a02_ek1")
    check("AD-6: the Ek-2 block shows the exact combined sentence",
          '<p class="birlesik"><strong>İhbarnamede atıf var, sunulan dosyalar arasında bulunamadı</strong></p>' in ek2)
    check("AD-6: the Ek-2 block has the TWO separate parts: '1) Örneğe önceden girilmiş atıf' then '2) Uygulamanın denetimi'",
          ek2.index("<h4>1) Örneğe önceden girilmiş atıf</h4>") < ek2.index("<h4>2) Uygulamanın denetimi</h4>"))
    part1, part2 = ek2.split("<h4>2) Uygulamanın denetimi</h4>")
    check("AD-6: part 1 preparer = 'Önceden hazırlanmış örnek' with its own match row (EŞLEŞTİ)",
          'class="hazirlayan">Önceden hazırlanmış örnek<' in part1 and "EŞLEŞTİ" in part1 and "Sistem çıkardı" not in part1)
    check("AD-6: part 2 preparer = 'Sistem çıkardı' and result = no match among the presented documents",
          'class="hazirlayan">Sistem çıkardı<' in part2 and "sunulan dosyalar arasında eşleşme bulunamadı" in part2 and "Önceden hazırlanmış örnek" not in part2)
    check("the resolver cross-check line is shown with its limited scope and lists Ek-2 as unresolved",
          "yalnız belgelerin referans numaralarına bakar" in part2 and "<dd>Ek-2</dd>" in part2)
    check("AD-6: Ek-1 is found: 'sunulan dosyada bulundu' with the document id; no 'bulunamadı' combined sentence",
          "Atıf var; sunulan dosyada bulundu:" in ek1 and "ek_001" in ek1 and "bulunamadı</strong>" not in ek1)
    check("the Ek-2 block links to the physical page 2 of the cited document", '#page=2">' in ek2)

    # ================= bağlantısız (PDF yok) gösterim
    pdf_copy = next((case_dir / "documents" / "ihbarname_001").glob("*.pdf"))
    pdf_bytes = pdf_copy.read_bytes()
    pdf_copy.unlink()
    nolink = P.render_html(P.load_report_data(case_dir))
    nsec = section(nolink, "bulgu-b02_s2")
    check("AD-5: without the PDF there is NO file:/// link for that document", all("ihbarname" not in h for h in re.findall(r'href="([^"]*)"', nolink)))
    check("AD-5: without a link the block still shows document name, physical page and the page text",
          "Bağlantı yok (PDF bulunamadı)" in nsec and "ihbarname.pdf" in nsec and "<dd>2 / 2</dd>" in nsec and "SAYFA-IKI-BASLIK" in nsec and "<mark>" in nsec)
    pdf_copy.write_bytes(pdf_bytes + b"%changed")
    changed = P.render_html(P.load_report_data(case_dir))
    check("a PDF changed after preparation is flagged (UYARI) but the report still renders",
          changed.count("UYARI: PDF, hazırlamadan sonra değişmiş görünüyor.") >= 1 and "UYARI: hazırlamadan sonra değişmiş" in changed)
    pdf_copy.write_bytes(pdf_bytes)
    check("restoring the PDF removes the warning", "hazırlamadan sonra değişmiş" not in P.render_html(P.load_report_data(case_dir)))

    # ================= yükleme hataları + yalnız vaka dizini okunur
    check("a missing case dir -> VAKA_YOK", code_of(P.load_report_data, TMP / "yok") == "VAKA_YOK")
    root_b, case_b = build_case("kok_bozuk")
    (case_b / F.RESULT_NAME).write_text("{not json", encoding="utf-8")
    check("a corrupt result record -> SONUC_KAYDI_GECERSIZ", code_of(P.load_report_data, case_b) == "SONUC_KAYDI_GECERSIZ")
    root_c, case_c = build_case("kok_kayip")
    (case_c / F.RESULT_NAME).unlink()
    check("a missing result record -> SONUC_KAYDI_GECERSIZ", code_of(P.load_report_data, case_c) == "SONUC_KAYDI_GECERSIZ")
    root_d, case_d = build_case("kok_sayfa")
    txt = case_d / "documents" / "ihbarname_001" / "extracted" / "ihbarname_001.txt"
    txt.write_bytes(txt.read_bytes() + b"fazla sayfa\x0c")
    check("an extracted text whose page count differs from the record -> SONUC_KAYDI_GECERSIZ", code_of(P.load_report_data, case_d) == "SONUC_KAYDI_GECERSIZ")

    opened = []

    def _audit(event, args):
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            opened.append(os.path.normcase(os.path.realpath(os.fsdecode(args[0]))))

    sys.addaudithook(_audit)
    mark = len(opened)
    P.load_report_data(case_dir)
    reads = [p for p in opened[mark:] if not p.endswith((".pyc", ".pyd", ".dll"))]
    check("the report reads ONLY files inside the case dir (no spec, no belgeler/, no decoy)",
          bool(reads) and all(p.startswith(os.path.normcase(os.path.realpath(str(case_dir)))) for p in reads), str(reads[:4]))
    check("the report module has no write path: it only reads and returns a string", not hasattr(P, "write_report") and isinstance(page, str))

    # ================= L-7 (m19): boş sayfalar KORUNUR (ortadaki ve sondaki); rapor sayfa sayısıyla tutarlı
    blank_texts = {"bos.pdf": "Birinci sayfa metni\f\fÜçüncü sayfa SON-SAYFA-METNI\f"}
    blank_spec = {
        "schema_version": 1, "demo_id": "demo_bos",
        "belgeler": [{"doc_id": "bos_belge", "file_name": "bos.pdf", "document_type": "vergi_ceza_ihbarnamesi",
                      "title": "Ortası boş sayfalı belge", "declared_page_count": 3}],
        "bulgular": [finding("b_son", "bos_belge", 3, "SON-SAYFA-METNI", "other", "Üçüncü sayfa")],
        "eksik_atiflar": [],
    }
    root_blank, case_blank = build_case("kok_bos", blank_spec, blank_texts)
    try:
        data_blank = P.load_report_data(case_blank)
    except S.DemoError:
        data_blank = None  # sayfa sayısı kayıtla uyuşmaz (boş sayfa düşürülmüş) -> aşağıdaki kontroller KIRMIZI
    check("m19: a blank MIDDLE page is kept - the report data has 3 pages and the middle one is empty",
          data_blank is not None and data_blank.pages_by_doc["bos_belge"] == ("Birinci sayfa metni", "", "Üçüncü sayfa SON-SAYFA-METNI"))
    page_blank = P.render_html(data_blank) if data_blank is not None else ""
    check("m19: the finding on page 3 is shown as '3 / 3' and highlights the page-3 text (page numbers did not shift)",
          bool(page_blank) and "<dt>Fiziksel sayfa</dt><dd>3 / 3</dd>" in section(page_blank, "bulgu-b_son") and "<mark>SON-SAYFA-METNI</mark>" in section(page_blank, "bulgu-b_son"))
    last_blank_texts = {"bos.pdf": "Sayfa bir\f\f"}
    last_blank_spec = copy.deepcopy(blank_spec)
    last_blank_spec["demo_id"] = "demo_bos2"
    last_blank_spec["belgeler"][0]["declared_page_count"] = 2
    last_blank_spec["bulgular"] = [finding("b_bir", "bos_belge", 1, "Sayfa bir", "other", "Birinci sayfa")]
    root_lb, case_lb = build_case("kok_bos2", last_blank_spec, last_blank_texts)
    check("m19: a blank LAST page is kept too (2 pages: 'Sayfa bir' and an empty one)", code_of(P.load_report_data, case_lb) is None and P.load_report_data(case_lb).pages_by_doc["bos_belge"] == ("Sayfa bir", ""))
    check("m19: the report module's page split keeps blank pages (direct)",
          P._split("a\f\fc\f") == ["a", "", "c"] and P._split("a\f\f") == ["a", ""] and P._split("tek") == ["tek"])

    # ================= L-4: özet sayısı ile bölümler tutarlı; 'bulundu' atıf 'bulunmayan' başlığı altında DEĞİL
    not_found_part = page.split("<h2>Dosyada bulunmayan atıflar</h2>")[1].split("<h2>Sunulan dosyalarda bulunan atıflar</h2>")[0]
    found_part = page.split("<h2>Sunulan dosyalarda bulunan atıflar</h2>")[1]
    check("L-4: the Ek-2 citation (not found) sits under 'Dosyada bulunmayan atıflar' and Ek-1 (found) does NOT",
          'id="atif-a01_ek2"' in not_found_part and 'id="atif-a02_ek1"' not in not_found_part)
    check("L-4: the Ek-1 citation (found among the presented files) sits under its own heading 'Sunulan dosyalarda bulunan atıflar'",
          'id="atif-a02_ek1"' in found_part and 'id="atif-a01_ek2"' not in found_part)
    ref_only_spec = {
        "schema_version": 1, "demo_id": "demo_atif",
        "belgeler": [{"doc_id": "ihbarname_001", "file_name": "ihbarname.pdf", "document_type": "vergi_ceza_ihbarnamesi",
                      "title": "Sentetik ihbarname", "declared_page_count": 2}],
        "bulgular": [],
        "eksik_atiflar": [{"fact_id": "a_yanlis", "referenced_in_doc": "ihbarname_001", "page": 1,
                           "excerpt": "Ek-9 ekte sunulmuştur.", "referenced_name": "Ek-9", "origin": "ornek"}],
    }
    root_ro, case_ro = build_case("kok_atif", ref_only_spec, {"ihbarname.pdf": TEXTS["ihbarname.pdf"]})
    page_ro = P.render_html(P.load_report_data(case_ro))
    unmatched_section = page_ro.split("<h2>Alıntısı eşleşmeyen örnek bulgular</h2>")[1].split("<h2>")[0]
    check("L-4: summary says 1 unmatched (the citation) and the 'unmatched findings' section does NOT claim 'Yok.'",
          "Alıntısı eşleşmeyen: 1" in page_ro and "<p>Yok.</p>" not in unmatched_section and "yalnız aşağıdaki atıf kayıtlarındadır (1)" in unmatched_section)
    check("L-4: with no unmatched anything the section still says 'Yok.' (summary 0)",
          "Alıntısı eşleşmeyen: 0" in page_blank and "<p>Yok.</p>" in page_blank.split("<h2>Alıntısı eşleşmeyen örnek bulgular</h2>")[1].split("<h2>")[0])
    check("L-2/L-4: the method line discloses that names without a number AND a word are not searched, and the citing document is excluded",
          "atfı içeren belge hariç" in ek2 and "Adında sayı ve sözcük birlikte bulunmayan atıflar için eşleşme aranmaz" in ek2)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
