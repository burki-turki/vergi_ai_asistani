# ============================================================
# DEMO P1 - ui/services/demo_p1_intake.py İZOLE TESTİ
#
#   - demo kökü DEPO DIŞINDA (depo içi / depoyu içeren / junction takma adı / göreli / sürücü-göreli RET)
#   - YALNIZ spec'te tanımlı dosyalar açılır; komşudaki "beklenen_degerlendirme*" decoy'u HİÇ açılmaz,
#     demo kökü/`belgeler` dizini listelenmez (sys.addaudithook)
#   - `\f` sayfa ayracı KORUNUR; yalnız sondaki tek boş parça düşer, ortadaki boş sayfa korunur;
#     bildirilen sayfa sayısıyla uyuşmazlık RET
#   - PDF'ler SALT-OKUNUR (sha256/boyut/mtime_ns önce=sonra; yazma/silme/yeniden adlandırma olayı yok)
#   - vaka dizini O_EXCL + işaretli; mevcut mevcut vakayı DEVRALMAZ; yazma yalnız demo kökü altında
#   - metin çıkarıcı ENJEKTE edilir (gerçek Poppler resmî kapıda koşturulmaz)
# ============================================================

import hashlib
import json
import os
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


def skip(label, detail=""):
    global skipped
    skipped += 1
    print(f"SKIPPED {label} - {detail}")


def summarize_and_exit():
    print(f"--- test_demo_p1_intake_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import demo_p1_intake as I  # noqa: E402
from ui.services import demo_p1_spec as S  # noqa: E402
from ui.services import office_flow_intake as T1  # noqa: E402

TEXTS = {
    "ihbarname.pdf": "Sayfa bir.\nİhbarname, mükellefe 10.02.2026 tarihinde tebliğ edilmiştir.\fSayfa iki.\nEk-2 ekte sunulmuştur.\f",
    "tebligat.pdf": "Tebliğ tarihi: 10.02.2026\f",
    "vir.pdf": "VIR bir.\fVIR iki.\f",
}
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
    "bulgular": [], "eksik_atiflar": [],
}
SPEC = S.validate_spec(SPEC_RAW)

TMP = Path(tempfile.mkdtemp(prefix="vergi_p1_intake_"))
STATE = {"watch": [], "events": []}
LINKS = []


def _audit(event, args):
    try:
        if not STATE["watch"]:
            return
        if event in ("open", "os.listdir", "os.scandir", "os.remove", "os.rmdir", "os.rename", "os.replace",
                     "shutil.rmtree", "os.truncate") and args and isinstance(args[0], (str, bytes, os.PathLike)):
            text = os.path.normcase(os.path.realpath(os.fsdecode(args[0])))
            mode = args[1] if event == "open" and len(args) > 1 and isinstance(args[1], str) else ""
            flags = args[2] if event == "open" and len(args) > 2 and isinstance(args[2], int) else 0
            STATE["events"].append((event, text, mode, flags))
    except Exception:
        pass


sys.addaudithook(_audit)

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_TRUNC", 0)


def is_write(event):
    """open olayı: metin kipinde (w/a/x/+) VEYA düşük seviyeli bayraklarda (O_WRONLY/O_CREAT/...) yazma."""
    return event[0] == "open" and (any(c in event[2] for c in "wax+") or bool(event[3] & _WRITE_FLAGS))


def norm(path):
    return os.path.normcase(os.path.realpath(str(path)))


def make_root(name, texts=None, *, decoys=True):
    root = TMP / name
    (root / "belgeler").mkdir(parents=True)
    for file_name in TEXTS:
        (root / "belgeler" / file_name).write_bytes(b"%PDF-1.4\n% sentetik " + file_name.encode() + b"\n")
    if decoys:
        for decoy in (root / "beklenen_degerlendirme.txt", root / "belgeler" / "beklenen_degerlendirme_AYRI.docx",
                      TMP / f"{name}_beklenen_degerlendirme.md"):
            decoy.write_text("AVUKAT CEVABI (decoy)", encoding="utf-8")
    return root, (texts or TEXTS)


def extractor_for(texts):
    return lambda source: texts[Path(source).name]


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except S.DemoError as error:
        return error.code
    except Exception as error:
        return "UNEXPECTED:" + type(error).__name__
    return None


def tree_state(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


try:
    # ================= check_demo_root
    root, texts = make_root("kok_ok")
    check("an absolute existing directory OUTSIDE the repo is accepted", I.check_demo_root(root) == root)
    check("a relative path is refused (DEMO_KOKU_GECERSIZ)", code_of(I.check_demo_root, "demo_kok") == "DEMO_KOKU_GECERSIZ")
    if os.name == "nt":
        check("a drive-relative path (C:demo) is refused", code_of(I.check_demo_root, "C:demo_kok") == "DEMO_KOKU_GECERSIZ")
        check("a rooted-without-drive path (\\demo) is refused", code_of(I.check_demo_root, "\\demo_kok") == "DEMO_KOKU_GECERSIZ")
    else:
        skip("drive-relative path refusal", "Windows-only form")
    check("a non-existing directory is refused", code_of(I.check_demo_root, TMP / "yok_kok") == "DEMO_KOKU_GECERSIZ")
    (TMP / "dosya.txt").write_text("x", encoding="utf-8")
    check("a FILE as the demo root is refused", code_of(I.check_demo_root, TMP / "dosya.txt") == "DEMO_KOKU_GECERSIZ")
    check("a non-path value is refused", code_of(I.check_demo_root, None) == "DEMO_KOKU_GECERSIZ")
    check("a directory INSIDE the repo is refused (DEMO_KOKU_DEPO_ICINDE)", code_of(I.check_demo_root, REPO_ROOT / "ui") == "DEMO_KOKU_DEPO_ICINDE")
    check("data/cases under the repo is refused", code_of(I.check_demo_root, REPO_ROOT / "data" / "cases") == "DEMO_KOKU_DEPO_ICINDE")
    check("the repo root itself is refused", code_of(I.check_demo_root, REPO_ROOT) == "DEMO_KOKU_DEPO_ICINDE")
    check("a directory that CONTAINS the repo is refused (the parent of the repo)",
          code_of(I.check_demo_root, REPO_ROOT.parent) == "DEMO_KOKU_DEPO_ICINDE")
    # Windows junction: TMP\takma -> <SAHTE DEPO>\ui  (realpath + dosya kimliği). Hedef GERÇEK depo DEĞİL:
    # sahte depo geçici dizindedir ve `repo_root=` ile "depo" olarak verilir.
    junction = TMP / "takma_depo"
    takma_repo = TMP / "takma_fakerepo"
    (takma_repo / "ui").mkdir(parents=True)
    made = False
    try:
        import _winapi
        _winapi.CreateJunction(str(takma_repo / "ui"), str(junction))
        LINKS.append(junction)
        made = True
    except Exception:
        made = False
    if made:
        check("a junction pointing INTO the (fake) repo is refused as the demo root",
              code_of(I.check_demo_root, junction, repo_root=takma_repo) == "DEMO_KOKU_DEPO_ICINDE")
        check("the junction target is under the temporary fake repo and NOT under the real repo",
              norm(junction).startswith(norm(takma_repo)) and not norm(junction).startswith(norm(REPO_ROOT)))
    else:
        skip("junction into the repo", "no junction support here")
    check("an injected repo_root is honoured (a tmp dir treated as the repo refuses its own children)",
          code_of(I.check_demo_root, root, repo_root=TMP) == "DEMO_KOKU_DEPO_ICINDE")

    # ================= metin / sayfa
    check("normalize_text keeps the form feed (page separator) and normalizes CRLF/CR to LF",
          I.normalize_text("a\r\nb\rc\fd") == "a\nb\nc\fd")
    check("normalize_text NFC-normalizes (decomposed İ/ş compose)", I.normalize_text("Ş") == "Ş")
    check("normalize_text refuses a non-string", code_of(I.normalize_text, b"x") == "CIKARICI_BASARISIZ")
    check("normalize_text refuses an oversized text (METIN_COK_UZUN)", code_of(I.normalize_text, "x" * (I.TEXT_LIMIT_CHARS + 1)) == "METIN_COK_UZUN")
    check("split_pages: 'p1 FF p2 FF' -> 2 pages (only the single trailing empty piece drops)", I.split_pages("p1\fp2\f") == ["p1", "p2"])
    check("split_pages: no trailing form feed -> still 2 pages", I.split_pages("p1\fp2") == ["p1", "p2"])
    check("split_pages: a blank MIDDLE page is KEPT ('p1 FF FF p3 FF' -> 3 pages)", I.split_pages("p1\f\fp3\f") == ["p1", "", "p3"])
    check("split_pages: a blank LAST page is kept ('p1 FF FF' -> 2 pages)", I.split_pages("p1\f\f") == ["p1", ""])
    check("split_pages: a single page without any form feed -> 1 page", I.split_pages("tek sayfa") == ["tek sayfa"])
    check("split_pages: all-blank text -> METIN_BOS", code_of(I.split_pages, "\f\f  \f") == "METIN_BOS" and code_of(I.split_pages, "") == "METIN_BOS")
    check("join_pages is the Poppler layout (FF after EVERY page) and round-trips through split_pages",
          I.join_pages(["a", "", "c"]) == "a\f\fc\f" and I.split_pages(I.join_pages(["a", "", "c"])) == ["a", "", "c"])

    # ================= analyze_documents (bellekte)
    pdf_files = [root / "belgeler" / name for name in TEXTS]
    before = {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_size, p.stat().st_mtime_ns) for p in pdf_files}
    STATE["watch"] = [norm(root), norm(TMP)]
    STATE["events"] = []
    docs = I.analyze_documents(root, SPEC, extractor=extractor_for(texts))
    STATE["watch"] = []
    check("analyze: three documents with the declared physical page counts (2, 1, 2)", [(d.doc_id, len(d.pages)) for d in docs] == [("ihbarname_001", 2), ("tebligat_001", 1), ("ek_001", 2)])
    check("analyze: page texts are split on the preserved form feed", docs[0].pages[0].startswith("Sayfa bir.") and docs[0].pages[1].startswith("Sayfa iki."))
    check("analyze: the SHA-256 and size of each PDF are recorded from the bytes read",
          all(d.sha256 == before[str(d.source_path)][0] and d.size_bytes == before[str(d.source_path)][1] for d in docs))
    opened = {e[1] for e in STATE["events"] if e[0] == "open"}
    decoys = {norm(root / "beklenen_degerlendirme.txt"), norm(root / "belgeler" / "beklenen_degerlendirme_AYRI.docx"),
              norm(TMP / "kok_ok_beklenen_degerlendirme.md")}
    check("AD-10: no decoy 'beklenen_degerlendirme*' file (root, belgeler/, neighbour) was ever opened", not (opened & decoys))
    check("AD-10: ONLY the declared PDFs (and no other file) were opened while analyzing",
          {p for p in opened if p.startswith(norm(root))} <= {norm(p) for p in pdf_files})
    listed = [e for e in STATE["events"] if e[0] in ("os.listdir", "os.scandir") and e[1] in (norm(root), norm(root / "belgeler"), norm(TMP))]
    check("AD-10: neither the demo root, nor belgeler/, nor its parent was LISTED", not listed, str(listed))
    check("AD-12: every source PDF was opened read-only (no write mode) and nothing was removed/renamed",
          not [e for e in STATE["events"] if is_write(e) and e[1].startswith(norm(root / "belgeler"))]
          and not [e for e in STATE["events"] if e[0] in ("os.remove", "os.rename", "os.replace", "shutil.rmtree")])
    after = {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_size, p.stat().st_mtime_ns) for p in pdf_files}
    check("AD-12: sha256 / size / mtime_ns of each source PDF are identical before and after analysis", before == after)
    check("analyze writes NOTHING to disk (no vaka/ cikti/ created)", not (root / "vaka").exists() and not (root / "cikti").exists())

    # --- hata yolları
    wrong = dict(texts)
    wrong["ihbarname.pdf"] = "tek sayfa\f"
    check("AD-1: a physical page count different from the declared one is refused (SAYFA_SAYISI_UYUSMUYOR)",
          code_of(I.analyze_documents, root, SPEC, extractor=extractor_for(wrong)) == "SAYFA_SAYISI_UYUSMUYOR")
    more = dict(texts)
    more["vir.pdf"] = "a\fb\fc\f"
    check("AD-1: MORE pages than declared are refused too", code_of(I.analyze_documents, root, SPEC, extractor=extractor_for(more)) == "SAYFA_SAYISI_UYUSMUYOR")
    blank = dict(texts)
    blank["tebligat.pdf"] = " \f"
    check("an all-blank extraction is refused (METIN_BOS)", code_of(I.analyze_documents, root, SPEC, extractor=extractor_for(blank)) == "METIN_BOS")

    def boom(source):
        raise RuntimeError("Poppler yok")

    check("an extractor that raises collapses to CIKARICI_BASARISIZ (no traceback/content)", code_of(I.analyze_documents, root, SPEC, extractor=boom) == "CIKARICI_BASARISIZ")
    check("an extractor returning a non-string is refused", code_of(I.analyze_documents, root, SPEC, extractor=lambda s: b"x") == "CIKARICI_BASARISIZ")
    check("a text over the limit is refused (METIN_COK_UZUN)",
          code_of(I.analyze_documents, root, SPEC, extractor=lambda s: ("x" * 30000 + "\f") * 3) == "METIN_COK_UZUN")
    root2, _ = make_root("kok_eksik")
    (root2 / "belgeler" / "vir.pdf").unlink()
    check("a declared PDF that does not exist is refused (KAYNAK_YOK)", code_of(I.analyze_documents, root2, SPEC, extractor=extractor_for(texts)) == "KAYNAK_YOK")
    root3, _ = make_root("kok_pdf_degil")
    (root3 / "belgeler" / "vir.pdf").write_bytes(b"MZ not a pdf")
    check("a declared file that is not a PDF is refused (KAYNAK_PDF_DEGIL)", code_of(I.analyze_documents, root3, SPEC, extractor=extractor_for(texts)) == "KAYNAK_PDF_DEGIL")
    check("analyze inside the repo is refused before anything is opened", code_of(I.analyze_documents, REPO_ROOT / "ui", SPEC, extractor=extractor_for(texts)) == "DEMO_KOKU_DEPO_ICINDE")

    # ================= write_case
    root4, texts4 = make_root("kok_yaz")
    docs4 = I.analyze_documents(root4, SPEC, extractor=extractor_for(texts4))
    outside_before = tree_state(TMP)
    pdf4 = {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in (root4 / "belgeler").glob("*.pdf")}
    STATE["watch"] = [norm(root4), norm(TMP)]
    STATE["events"] = []
    case_dir = I.write_case(root4, SPEC, docs4)
    STATE["watch"] = []
    check("write_case: the case dir is <demo-root>/vaka/<demo_id> with an ownership marker", case_dir == root4 / "vaka" / "demo_001" and (case_dir / I.OWNER_MARKER).is_file())
    check("write_case: cikti/ (output dir) is created", (root4 / "cikti").is_dir())
    for doc in docs4:
        doc_dir = case_dir / "documents" / doc.doc_id
        txt = (doc_dir / "extracted" / f"{doc.doc_id}.txt").read_bytes()
        check(f"write_case: {doc.doc_id}: the extracted text keeps one form feed per page ({len(doc.pages)})", txt.count(b"\x0c") == len(doc.pages))
        check(f"write_case: {doc.doc_id}: re-splitting the written text returns the same pages", I.split_pages(txt.decode("utf-8")) == list(doc.pages))
        check(f"write_case: {doc.doc_id}: the PDF copy is byte-identical to the source", (doc_dir / doc.file_name).read_bytes() == doc.pdf_bytes)
        meta = json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))
        check(f"write_case: {doc.doc_id}: document.json carries the physical page count and the PDF sha256",
              meta["file"]["page_count"] == len(doc.pages) and meta["file"]["sha256"] == doc.sha256)
    case_json = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    check("write_case: case.json lists all three documents, exactly one primary",
          [r["document_id"] for r in case_json["case_document_refs"]] == ["ihbarname_001", "tebligat_001", "ek_001"]
          and sum(1 for r in case_json["case_document_refs"] if r["primary"]) == 1
          and case_json["case_id"] == "demo_001")
    cats = {json.loads((case_dir / "documents" / d.doc_id / "document.json").read_text(encoding="utf-8"))["document_category"] for d in docs4}
    check("write_case: document categories follow the type map (administrative_action / notification / audit)", cats == {"administrative_action", "notification", "audit"})
    try:
        T1.validate_seed(case_dir)
        seed_ok = True
    except Exception:
        seed_ok = False
    check("write_case: the written seed passes the existing T1 validate_seed (path-based; works outside CASES_DIR)", seed_ok)
    broken = TMP / "kok_yaz_bozuk"
    shutil.copytree(case_dir, broken)
    bad_case = json.loads((broken / "case.json").read_text(encoding="utf-8"))
    bad_case.pop("case_type")
    (broken / "case.json").write_text(json.dumps(bad_case), encoding="utf-8")
    try:
        T1.validate_seed(broken)
        refused = False
    except Exception:
        refused = True
    check("validate_seed is NOT vacuous: a case.json without a required key is refused", refused)
    shutil.rmtree(broken, ignore_errors=True)
    check("AD-12: the source PDFs are still byte/mtime-identical after write_case",
          {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in (root4 / "belgeler").glob("*.pdf")} == pdf4)
    write_targets = {e[1] for e in STATE["events"] if is_write(e)}
    check("writes happened ONLY under the demo root (every write-mode/low-level write open is inside it)",
          bool(write_targets) and all(t.startswith(norm(root4)) for t in write_targets), str(sorted(write_targets))[:300])
    check("the write detector is not vacuous: it saw the case files being created (case.json among the targets)",
          any(t.endswith("case.json") for t in write_targets))
    check("nothing outside the demo root changed in the temp tree",
          {k: v for k, v in tree_state(TMP).items() if not k.startswith("kok_yaz")} == {k: v for k, v in outside_before.items() if not k.startswith("kok_yaz")})
    check("write_case does NOT adopt an existing case dir (second call -> DIZIN_MEVCUT)", code_of(I.write_case, root4, SPEC, docs4) == "DIZIN_MEVCUT")
    check("case_exists reports the prepared case", I.case_exists(root4, "demo_001") and not I.case_exists(root4, "demo_002"))
    check("write_case refuses a demo root inside the repo", code_of(I.write_case, REPO_ROOT / "ui", SPEC, docs4) == "DEMO_KOKU_DEPO_ICINDE")

    # ================= kurucular
    case_obj = I.build_demo_case_json("demo_009", docs4)
    check("build_demo_case_json: titled DEMO, confidential, no amounts/dates in the seed",
          case_obj["title"].startswith("DEMO") and case_obj["administrative_actions"][0]["notification_date"] is None
          and case_obj["dispute_items"][0]["principal_tax"]["amount"] == "0.00")
    doc_obj = I.build_demo_document_json("demo_009", docs4[1])
    check("build_demo_document_json: provenance says synthetic demo and the relative path is case-scoped",
          doc_obj["provenance"]["source_origin"] == "generated" and doc_obj["file"]["relative_path"].startswith("cases/demo_009/documents/tebligat_001/"))

    # ================= M-1: vaka/ , vaka/<id>/ , cikti/ bağlantı-junction güvenliği (sıfır yazma + kapalı hata)
    def mklink(target, link):
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        except Exception:
            try:
                os.symlink(str(target), str(link), target_is_directory=True)
            except (OSError, NotImplementedError):
                return False
        LINKS.append(link)
        return True

    def fake_repo(name):
        repo = TMP / f"{name}_fakerepo"
        for sub in ("data/cases", "docs"):
            (repo / sub).mkdir(parents=True)
        return repo

    def entries(path):
        return sorted(str(p.relative_to(path)) for p in Path(path).rglob("*"))

    def foreign_writes(root_path):
        base = norm(root_path)
        return [e for e in STATE["events"] if is_write(e) and not e[1].startswith(base)]

    def scenario(name, *, link_name, target_of, repo_kind="fake"):
        """Kök kur, `link_name`'i hedefe junction yap, write_case çağır."""
        scen_root, scen_texts = make_root(name)
        scen_docs = I.analyze_documents(scen_root, SPEC, extractor=extractor_for(scen_texts))
        repo = fake_repo(name)
        target = target_of(repo, scen_root)
        target.mkdir(parents=True, exist_ok=True)
        if not mklink(target, scen_root / link_name):
            return None
        STATE["watch"] = [norm(TMP)]
        STATE["events"] = []
        code = code_of(I.write_case, scen_root, SPEC, scen_docs, repo_root=repo if repo_kind == "fake" else None)
        events_foreign = foreign_writes(scen_root)
        STATE["watch"] = []
        return scen_root, target, code, events_foreign

    r = scenario("lnk_vaka_repo", link_name="vaka", target_of=lambda repo, rt: repo / "data" / "cases")
    if r is None:
        skip("junction/symlink scenarios", "no link support here")
    else:
        scen_root, target, code, ev = r
        check("M-1: vaka -> <repo>/data/cases junction: write_case refused with DIZIN_GUVENSIZ", code == "DIZIN_GUVENSIZ", str(code))
        check("M-1: ... ZERO files written into the repo's data/cases (and no cikti/ created either)",
              entries(target) == [] and not (scen_root / "cikti").exists())
        check("M-1: ... no write-mode open outside the demo root (audit-hook)", ev == [], str(ev[:3]))

        r = scenario("lnk_cikti_docs", link_name="cikti", target_of=lambda repo, rt: repo / "docs")
        scen_root, target, code, ev = r
        check("M-1: cikti -> <repo>/docs junction: write_case refused with DIZIN_GUVENSIZ", code == "DIZIN_GUVENSIZ", str(code))
        check("M-1: ... ZERO files written into docs and NO case written (vaka/ stays empty)",
              entries(target) == [] and entries(scen_root / "vaka") == [])
        check("M-1: ... no write-mode open outside the demo root (audit-hook)", ev == [], str(ev[:3]))

        r = scenario("lnk_vaka_elsewhere", link_name="vaka", target_of=lambda repo, rt: TMP / "baska_yer_1", repo_kind="real")
        scen_root, target, code, ev = r
        check("M-1: vaka -> a random directory OUTSIDE the demo root: refused (DIZIN_GUVENSIZ), target stays empty",
              code == "DIZIN_GUVENSIZ" and entries(target) == [] and ev == [], str((code, ev[:2])))

        r = scenario("lnk_vaka_inside", link_name="vaka", target_of=lambda repo, rt: rt / "kok_ici_baska", repo_kind="real")
        scen_root, target, code, ev = r
        check("M-1: vaka -> another directory INSIDE the root is refused too (a link is a link: only the link check catches this)",
              code == "DIZIN_GUVENSIZ" and entries(target) == [], str(code))

        r = scenario("lnk_cikti_elsewhere", link_name="cikti", target_of=lambda repo, rt: TMP / "baska_yer_2", repo_kind="real")
        scen_root, target, code, ev = r
        check("M-1: cikti -> outside the root: refused, target stays empty", code == "DIZIN_GUVENSIZ" and entries(target) == [] and ev == [])

        # vaka/<demo_id> kendisi bağlantı: ne yazılır ne devralınır
        scen_root, scen_texts = make_root("lnk_case_dir")
        scen_docs = I.analyze_documents(scen_root, SPEC, extractor=extractor_for(scen_texts))
        (scen_root / "vaka").mkdir()
        elsewhere = TMP / "baska_yer_3"
        elsewhere.mkdir()
        if mklink(elsewhere, scen_root / "vaka" / "demo_001"):
            check("M-1: vaka/<demo_id> is itself a link: write_case does not write through it (DIZIN_MEVCUT), target empty",
                  code_of(I.write_case, scen_root, SPEC, scen_docs) == "DIZIN_MEVCUT" and entries(elsewhere) == [])
            check("M-1: an existing case dir that is a link is NOT adopted (verify_existing_case -> DIZIN_GUVENSIZ)",
                  code_of(I.verify_existing_case, scen_root, SPEC) == "DIZIN_GUVENSIZ")

        # doğrudan birim: SAHTE deponun data/cases'ine junction (gerçek depoya HİÇBİR bağlantı kurulmaz)
        unit_root, _ = make_root("lnk_unit")
        (unit_root / "vaka_gercek").mkdir()
        unit_repo = fake_repo("lnk_unit")
        if mklink(unit_repo / "data" / "cases", unit_root / "vaka_depo"):
            check("M-1: ensure_inside_root: a junction to the fake repo's data/cases is refused (no write attempted)",
                  code_of(I.ensure_inside_root, unit_root, unit_root / "vaka_depo", repo_root=unit_repo) == "DIZIN_GUVENSIZ")
            check("O-2: that junction's target is the TEMPORARY fake repo's data/cases (not the real repo's)",
                  norm(unit_root / "vaka_depo") == norm(unit_repo / "data" / "cases") and not norm(unit_root / "vaka_depo").startswith(norm(REPO_ROOT)))
        check("M-1: ensure_inside_root accepts a plain directory inside the root", I.ensure_inside_root(unit_root, unit_root / "vaka_gercek") == unit_root / "vaka_gercek")
        check("M-1: ensure_inside_root refuses the root itself and a non-directory",
              code_of(I.ensure_inside_root, unit_root, unit_root) == "DIZIN_GUVENSIZ"
              and code_of(I.ensure_inside_root, unit_root, unit_root / "yok_dizin") == "DIZIN_GUVENSIZ")
        outside_real = TMP / "baska_yer_4"
        (outside_real / "x").mkdir(parents=True)
        if mklink(outside_real, unit_root / "ara"):
            check("M-1: an ANCESTOR link (root/ara -> outside, root/ara/x a real dir) is refused by the realpath containment",
                  not I._is_link(unit_root / "ara" / "x") and code_of(I.ensure_inside_root, unit_root, unit_root / "ara" / "x") == "DIZIN_GUVENSIZ")
        check("M-1: _is_link recognises a regular directory as NOT a link", not I._is_link(unit_root / "vaka_gercek"))
        check("M-1: injected repo_root: a plain dir inside the injected 'repo' is refused",
              code_of(I.ensure_inside_root, unit_root, unit_root / "vaka_gercek", repo_root=unit_root) == "DIZIN_GUVENSIZ")

    # ================= L-3 / L-5: var olan vakayı devralma
    root9, texts9 = make_root("devral")
    docs9 = I.analyze_documents(root9, SPEC, extractor=extractor_for(texts9))
    case9 = I.write_case(root9, SPEC, docs9)
    marker9 = json.loads((case9 / I.OWNER_MARKER).read_text(encoding="utf-8"))
    check("the ownership marker carries demo_id and the spec digest", marker9["demo_id"] == "demo_001" and marker9["spec_digest"] == I.spec_digest(SPEC) and len(marker9["spec_digest"]) == 64)
    check("L-5: a case with a marker but NO result record is half-written: VAKA_YARIM (not a misleading result error)",
          code_of(I.verify_existing_case, root9, SPEC) == "VAKA_YARIM")
    (case9 / "demo_p1_sonuc.json").write_text("{}", encoding="utf-8")
    check("L-3: an existing complete case with the SAME spec is adopted", I.verify_existing_case(root9, SPEC) == case9)
    changed = json.loads(json.dumps(SPEC_RAW))
    changed["belgeler"][0]["title"] = "Başka bir başlık"
    check("L-3: the spec CHANGED after the case was prepared: refused (VAKA_UYUSMUYOR), not silently re-reported",
          code_of(I.verify_existing_case, root9, S.validate_spec(changed)) == "VAKA_UYUSMUYOR")
    (case9 / I.OWNER_MARKER).write_text(json.dumps({"kind": "demo_p1_case", "demo_id": "demo_999", "spec_digest": marker9["spec_digest"]}), encoding="utf-8")
    check("L-3: a marker of ANOTHER demo id is refused", code_of(I.verify_existing_case, root9, SPEC) == "VAKA_UYUSMUYOR")
    (case9 / I.OWNER_MARKER).write_text("not json", encoding="utf-8")
    check("L-3: a corrupt marker is refused", code_of(I.verify_existing_case, root9, SPEC) == "VAKA_UYUSMUYOR")
    (case9 / I.OWNER_MARKER).unlink()
    check("L-3: a non-empty dir without a marker is not ours (VAKA_UYUSMUYOR)", code_of(I.verify_existing_case, root9, SPEC) == "VAKA_UYUSMUYOR")
    root10, _ = make_root("leer")
    (root10 / "vaka" / "demo_001").mkdir(parents=True)
    check("L-5: an EMPTY leftover case dir is half-written (VAKA_YARIM); the tool never deletes it",
          code_of(I.verify_existing_case, root10, SPEC) == "VAKA_YARIM" and (root10 / "vaka" / "demo_001").is_dir())

    # ================= L-7: üretim kodu validate_seed'i GERÇEKTEN çağırır ve hatasını kapalı koda çevirir
    calls = []
    original_seed = I.validate_seed
    try:
        root11, texts11 = make_root("seed_izle")
        docs11 = I.analyze_documents(root11, SPEC, extractor=extractor_for(texts11))
        I.validate_seed = lambda case_dir: calls.append(Path(case_dir))
        case11 = I.write_case(root11, SPEC, docs11)
        check("L-7: write_case CALLS validate_seed exactly once, with the new case dir (production path, not just the test)",
              calls == [case11], str(calls))

        def failing(case_dir):
            raise T1.OfficeFlowError("TOHUM_DOGRULAMA_BASARISIZ")

        I.validate_seed = failing
        root12, texts12 = make_root("seed_hata")
        docs12 = I.analyze_documents(root12, SPEC, extractor=extractor_for(texts12))
        check("L-7: a validate_seed failure becomes the closed code TOHUM_DOGRULAMA_BASARISIZ",
              code_of(I.write_case, root12, SPEC, docs12) == "TOHUM_DOGRULAMA_BASARISIZ")

        def exploding_seed(case_dir):
            raise RuntimeError("beklenmeyen")

        I.validate_seed = exploding_seed
        root13, texts13 = make_root("seed_patla")
        docs13 = I.analyze_documents(root13, SPEC, extractor=extractor_for(texts13))
        check("L-7: an unexpected validator exception is NOT swallowed (it propagates to the CLI's closed fallback)",
              code_of(I.write_case, root13, SPEC, docs13) == "UNEXPECTED:RuntimeError")
    finally:
        I.validate_seed = original_seed

    check("O-2: NO junction/symlink created by this module resolves into the real repo (every link target is under the temporary tree)",
          bool(LINKS) and all(norm(link).startswith(norm(TMP)) and not norm(link).startswith(norm(REPO_ROOT)) for link in LINKS),
          str([str(norm(l)) for l in LINKS if not norm(l).startswith(norm(TMP))]))
finally:
    STATE["watch"] = []
    for _link in LINKS:
        try:
            os.rmdir(str(_link))  # junction/symlink yalnız bağlantıyı kaldırır; hedefe dokunmaz
        except OSError:
            pass
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
