# ============================================================
# BÜRO MODELİ / T1 - ui/services/office_flow_intake.py İZOLE TESTİ
#
# F1 (tohum) + F3 (aday satır):
#   - kaynak PDF SALT-OKUNUR: yalnız "rb"; kök içindeyse/aynı dosyaysa RED
#   - metin çıkarıcı ENJEKTE edilir (gerçek Poppler resmî kapıda koşturulmaz);
#     varsayılan çıkarıcı sahte subprocess/which ile sabit argv/kabuksuz sınanır
#   - tohum mevcut case_validator + case_document_validator'dan GEÇER; tebliğ
#     tarihi tohumda YOK; asıl dosya adı belgeye yazılmaz
#   - aday satır: TAM BİR tarih; motorun M-07/M-08 kurallarından geçer
# ============================================================

import hashlib
import json
import os
import shutil
import subprocess
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
    print(f"--- test_office_flow_intake_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import office_flow_intake as I  # noqa: E402
from ui.services import office_flow_records as R  # noqa: E402
from ui.services import paths as _paths  # noqa: E402,F401  (src/ sys.path)
import manual_fact_entry_engine as ENGINE  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vergi_t1_intake_"))
WATCH = {"source": None, "name": None}
SOURCE_EVENTS = []


def _audit(event, args):
    try:
        if WATCH["source"] and args and isinstance(args[0], (str, bytes, os.PathLike)):
            text = os.fsdecode(args[0])
            if os.path.basename(text) == WATCH["name"] and os.path.normcase(os.path.realpath(text)) == WATCH["source"]:
                if event in ("os.remove", "os.rmdir", "os.rename", "shutil.rmtree", "os.truncate"):
                    SOURCE_EVENTS.append(event)
                elif event == "open" and len(args) > 1 and isinstance(args[1], str) and any(c in args[1] for c in "wax+"):
                    SOURCE_EVENTS.append(("open", args[1]))
                elif event == "open" and len(args) > 2 and isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC):
                    SOURCE_EVENTS.append(("open-flags", args[2]))
    except Exception:
        pass


sys.addaudithook(_audit)


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except R.OfficeFlowError as error:
        return error.code
    return None


def make_junction(link: Path, target: Path) -> bool:
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
        return True
    except Exception:
        pass
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except Exception:
        return False


TEXT = ("SENTETİK İHBARNAME\n"
        "Düzenleme 05.02.2026 ve vade 06.02.2026 tarihlidir.\n"
        "İhbarname mükellefe 10.02.2026 tarihinde tebliğ edilmiştir.\n"
        "Ek yazı 15/02/2026 tarihlidir.\n"
        "Geçersiz takvim günü 31.02.2026 yazıdır.\n")
PDF = b"%PDF-1.4\nsentetik\n%%EOF\n"

try:
    # ---------------------------------------------------------------- aday satırlar
    candidates = I.candidate_lines(TEXT)
    check("candidate lines: ONLY lines with exactly one valid date token (two-date and impossible-date lines are excluded)",
          [c.date_iso for c in candidates] == ["2026-02-10", "2026-02-15"] and [c.index for c in candidates] == [1, 2], str(candidates))
    check("candidate lines keep the line text (stripped, NFC) for the manual-fact excerpt", candidates[0].text == "İhbarname mükellefe 10.02.2026 tarihinde tebliğ edilmiştir.")
    long_line = "x " * 260 + "10.02.2026"
    check("candidate lines: a line over 500 characters is excluded", I.candidate_lines(long_line) == [])
    check("candidate lines: a control character excludes the line", I.candidate_lines("a\x07 10.02.2026") == [])
    check("candidate lines: a tab is tolerated, a date glued to digits is not a token",
          len(I.candidate_lines("\ttebliğ 10.02.2026")) == 1 and I.candidate_lines("sayı 110.02.20261") == [])
    parity_ok = True
    for line in ("a 10.02.2026 b", "a 10/02/2026 b", "10.02.2026 ve 11.02.2026", "31.02.2026", "no date", "10.02/2026", "x10.02.2026y"):
        try:
            engine_dates = ENGINE.extract_excerpt_dates(line)
        except ENGINE.ManualFactEntryError:
            engine_dates = None
        mine = I.candidate_lines(line)
        if engine_dates is None:
            ok = mine == []
        else:
            ok = (len(mine) == 1) == (len(engine_dates) == 1 and len(I._date_tokens(line)) == 1)
        parity_ok = parity_ok and ok
    check("the candidate date token rule matches the manual-fact engine's M-08 regex on a parity sample", parity_ok)
    accepted = True
    for cand in candidates:
        try:
            ENGINE.check_excerpt_in_text(cand.text, TEXT)
            ENGINE.check_excerpt_date(cand.text, cand.date_iso)
        except ENGINE.ManualFactEntryError:
            accepted = False
    check("every candidate passes the engine's own M-07 (excerpt in text) and M-08 (excerpt date == date) rules", accepted)
    schema_bytes = Path(ENGINE.INPUT_SCHEMA_PATH).read_bytes()
    manual = I.build_manual_input("pilotabc", candidates[0], 1)
    parsed = ENGINE.parse_manual_input(R.canonical_bytes(manual), ENGINE.load_input_schema(schema_bytes))
    check("the manual input built from a candidate is accepted by the engine's own parser/schema (M-02/M-03/M-15)",
          parsed["facts"][0]["date"] == "2026-02-10" and parsed["document_id"] == I.DOC_ID)

    # ---------------------------------------------------------------- metin
    check("normalize_extracted_text: NFC, LF only, form feed -> newline", I.normalize_extracted_text("a\r\nb\fc") == "a\nb\nc")
    check("an empty/whitespace text -> METIN_BOS", code_of(I.normalize_extracted_text, "  \n\f ") == "METIN_BOS")
    check("a text over 60.000 characters -> METIN_COK_UZUN", code_of(I.normalize_extracted_text, "a" * 60001) == "METIN_COK_UZUN"
          and I.normalize_extracted_text("a" * 60000))

    # ---------------------------------------------------------------- vergi türü
    check("tax types: the closed G8 list is accepted", I.validate_tax_types(["KDV", "Vergi ziyaı cezası"]) == ["KDV", "Vergi ziyaı cezası"])
    for bad in ([], None, "KDV", ["ÖTV"], ["KDV", "KDV"], ["kdv"], [""]):
        check(f"tax types: {bad!r} is refused (VERGI_TURU_GECERSIZ)", code_of(I.validate_tax_types, bad) == "VERGI_TURU_GECERSIZ")

    # ---------------------------------------------------------------- kaynak yol
    office = TMP / "ofis"
    cases = TMP / "vakalar"
    archive = TMP / "buro_arsivi"
    for d in (office, cases, archive):
        d.mkdir()
    R.ensure_office_infra(office)
    source = archive / "asil_ihbarname.pdf"
    source.write_bytes(PDF)
    os.chmod(source, 0o444)
    SOURCE_ID = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, source.stat().st_mtime_ns)
    WATCH["source"], WATCH["name"] = os.path.normcase(os.path.realpath(str(source))), source.name
    roots = [cases, office]
    check("a regular PDF outside every protected root is accepted", I.check_source_path(source, protected_roots=roots) == source)
    check("a missing path / a directory -> KAYNAK_YOK",
          code_of(I.check_source_path, archive / "yok.pdf", protected_roots=roots) == "KAYNAK_YOK" and code_of(I.check_source_path, archive, protected_roots=roots) == "KAYNAK_YOK")
    notpdf = archive / "not.txt"
    notpdf.write_text("x", encoding="utf-8")
    check("a non-PDF extension -> KAYNAK_PDF_DEGIL", code_of(I.check_source_path, notpdf, protected_roots=roots) == "KAYNAK_PDF_DEGIL")
    inside_case = cases / "x.pdf"
    inside_case.write_bytes(PDF)
    inside_office = office / "x.pdf"
    inside_office.write_bytes(PDF)
    check("a source INSIDE the case root or the office root is refused (KAYNAK_ICERIDE)",
          code_of(I.check_source_path, inside_case, protected_roots=roots) == "KAYNAK_ICERIDE"
          and code_of(I.check_source_path, inside_office, protected_roots=roots) == "KAYNAK_ICERIDE")
    link_dir = TMP / "baglanti_kaynak"
    if make_junction(link_dir, cases):
        check("a source reached through a junction/symlink that resolves INTO the case root is refused (realpath containment)",
              code_of(I.check_source_path, link_dir / "x.pdf", protected_roots=roots) == "KAYNAK_ICERIDE")
        os.rmdir(link_dir)
    else:
        skip("source through a junction into the case root", "no junction/symlink could be created here. NOT EXECUTED, not a pass")
    fake_pdf = archive / "sahte.pdf"
    fake_pdf.write_bytes(b"MZ not a pdf")
    check("a file named .pdf without the %PDF header -> KAYNAK_PDF_DEGIL", code_of(I.read_source_bytes, fake_pdf) == "KAYNAK_PDF_DEGIL")
    check("read_source_bytes returns the exact bytes and writes nothing", I.read_source_bytes(source) == PDF and not SOURCE_EVENTS)

    # ---------------------------------------------------------------- varsayılan çıkarıcı (sahte subprocess)
    calls = []
    real_run, real_which = subprocess.run, shutil.which

    class _Done:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    try:
        shutil.which = lambda name: None
        check("default extractor: no `pdftotext` on PATH -> CIKARICI_BASARISIZ", code_of(I.default_pdftotext_extractor, source) == "CIKARICI_BASARISIZ")
        shutil.which = lambda name: "C:\\poppler\\pdftotext.exe"

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return _Done(0, "SENTETİK METİN\n".encode("utf-8"))
        subprocess.run = fake_run
        text = I.default_pdftotext_extractor(source)
        argv, kwargs = calls[-1]
        check("default extractor: fixed argv list, NO shell, bounded timeout, reads the source as an argument and writes to stdout ('-')",
              isinstance(argv, list) and kwargs.get("shell") is False and kwargs.get("timeout") and argv[-1] == "-" and str(source) in argv
              and argv[0].endswith("pdftotext.exe") and text == "SENTETİK METİN\n", str(argv))
        subprocess.run = lambda argv, **kw: _Done(1, b"")
        check("default extractor: a non-zero exit code -> CIKARICI_BASARISIZ", code_of(I.default_pdftotext_extractor, source) == "CIKARICI_BASARISIZ")
        subprocess.run = lambda argv, **kw: (_ for _ in ()).throw(OSError("yok"))
        check("default extractor: an OS error -> CIKARICI_BASARISIZ (no message leaks)", code_of(I.default_pdftotext_extractor, source) == "CIKARICI_BASARISIZ")
        subprocess.run = lambda argv, **kw: _Done(0, b"\xff\xfe\x00bozuk")
        check("default extractor: non-UTF-8 output -> CIKARICI_BASARISIZ", code_of(I.default_pdftotext_extractor, source) == "CIKARICI_BASARISIZ")
    finally:
        subprocess.run, shutil.which = real_run, real_which

    # ---------------------------------------------------------------- tohum
    def new_paths(tag):
        run_id = R.new_run_id()
        paths = R.build_run_paths(office, cases, f"pilot{tag}", run_id)
        R.create_owned_dir(paths.run_dir, run_id=run_id, kind="run_dir")
        return paths

    seeded = new_paths("a")
    manifest = R.RunManifest()
    result = I.seed_case(paths=seeded, source_pdf=source, page_count=3, tax_types=["KDV"], extractor=lambda p: TEXT, manifest=manifest,
                         protected_roots=roots)
    doc_dir = seeded.case_dir / "documents" / I.DOC_ID
    check("seed: the case dir, the PDF COPY, the extracted text, document.json and case.json exist; the ownership marker is bound to the run",
          (doc_dir / I.DOC_FILE_NAME).read_bytes() == PDF and (doc_dir / "extracted" / f"{I.DOC_ID}.txt").is_file()
          and (doc_dir / "document.json").is_file() and (seeded.case_dir / "case.json").is_file()
          and R.read_owner_marker(seeded.case_dir, run_id=seeded.run_id, kind="case_dir") and result.page_count == 3)
    doc = json.loads((doc_dir / "document.json").read_bytes())
    check("document.json: opaque file name, size/sha of the COPY, the lawyer's page count, no original file name anywhere",
          doc["file"]["file_name"] == I.DOC_FILE_NAME and doc["file"]["sha256"] == hashlib.sha256(PDF).hexdigest()
          and doc["file"]["size_bytes"] == len(PDF) and doc["file"]["page_count"] == 3 and doc["provenance"]["original_file_name"] is None
          and "asil_ihbarname" not in json.dumps(doc) and doc["document_type"] == "vergi_ceza_ihbarnamesi")
    case = json.loads((seeded.case_dir / "case.json").read_bytes())
    check("case.json: NO notification date, NO events/proceedings, zero amounts, only the lawyer's tax type, opaque party names",
          case["administrative_actions"][0]["notification_date"] is None and case["events"] == [] and case["proceedings"] == []
          and [d["tax_type"] for d in case["dispute_items"]] == ["KDV"] and case["dispute_items"][0]["total_amount"]["amount"] == "0.00"
          and "2026" not in json.dumps(case) and case["case_id"] == seeded.case_id)
    import case_validator
    import case_document_validator
    case_result = case_validator.validate_case_file(case_path=str(seeded.case_dir / "case.json"), raise_on_error=True)
    docs_result = case_document_validator.validate_case_documents(case_dir=seeded.case_dir, raise_on_error=True)
    check("the seed passes the REPOSITORY'S OWN case_validator and case_document_validator with zero errors and zero warnings",
          not case_result["warnings"] and not docs_result["warnings"] and docs_result["document_count"] == 1 and docs_result["primary_document_count"] == 1)
    check("the run manifest lists exactly the four tool-created files; the source path is NOT in it",
          sorted((e["rel"], e["tur"]) for e in manifest.entries) == sorted([
              (f"documents/{I.DOC_ID}/{I.DOC_FILE_NAME}", "CALISMA_DIZINI_BELGE_KOPYASI"),
              (f"documents/{I.DOC_ID}/extracted/{I.DOC_ID}.txt", "CIKARILMIS_METIN"),
              (f"documents/{I.DOC_ID}/document.json", "CALISMA_DOSYALARI"), ("case.json", "CALISMA_DOSYALARI")])
          and "asil_ihbarname" not in manifest.to_bytes().decode("utf-8") and str(archive) not in manifest.to_bytes().decode("utf-8"))
    check("the ORIGINAL PDF is untouched by the seed (same sha256/size/mtime_ns, no write/delete/rename audit event)",
          (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_size, source.stat().st_mtime_ns) == SOURCE_ID and not SOURCE_EVENTS, str(SOURCE_EVENTS))
    check("seeded text is exactly the extractor's normalised output",
          (doc_dir / "extracted" / f"{I.DOC_ID}.txt").read_text(encoding="utf-8") == I.normalize_extracted_text(TEXT))

    # ---------------------------------------------------------------- manual input yazımı
    cands = I.candidate_lines(I.read_extracted_text(seeded))
    I.write_manual_input(seeded, I.build_manual_input(seeded.case_id, cands[0], 1), manifest)
    check("the manual input file is written once and registered in the manifest",
          (doc_dir / "manual_input" / "manual_facts.input.json").is_file()
          and any(e["rel"].endswith("manual_facts.input.json") for e in manifest.entries))
    check("a second manual-input write is refused (DIZIN_MEVCUT: no overwrite)", code_of(I.write_manual_input, seeded, I.build_manual_input(seeded.case_id, cands[0], 1), manifest) == "DIZIN_MEVCUT")

    # ---------------------------------------------------------------- reddedilen girişler
    existing_case = cases / "pilotb"
    existing_case.mkdir()
    (existing_case / "benim.txt").write_text("dokunma", encoding="utf-8")
    pb = new_paths("b")
    check("seed NEVER adopts an existing case dir (DIZIN_MEVCUT) and leaves it byte-identical",
          code_of(I.seed_case, paths=pb, source_pdf=source, page_count=1, tax_types=["KDV"], extractor=lambda p: TEXT,
                  manifest=R.RunManifest(), protected_roots=roots) == "DIZIN_MEVCUT"
          and sorted(p.name for p in existing_case.iterdir()) == ["benim.txt"] and (existing_case / "benim.txt").read_text(encoding="utf-8") == "dokunma")
    pc = new_paths("c")
    check("seed refuses a source inside the case root BEFORE creating anything",
          code_of(I.seed_case, paths=pc, source_pdf=inside_case, page_count=1, tax_types=["KDV"], extractor=lambda p: TEXT,
                  manifest=R.RunManifest(), protected_roots=roots) == "KAYNAK_ICERIDE" and not pc.case_dir.exists())
    check("seed refuses an invalid page count / tax type BEFORE touching the filesystem",
          code_of(I.seed_case, paths=pc, source_pdf=source, page_count=0, tax_types=["KDV"], extractor=lambda p: TEXT, manifest=R.RunManifest(), protected_roots=roots) == "SAYFA_GECERSIZ"
          and code_of(I.seed_case, paths=pc, source_pdf=source, page_count=1, tax_types=["ÖTV"], extractor=lambda p: TEXT, manifest=R.RunManifest(), protected_roots=roots) == "VERGI_TURU_GECERSIZ"
          and not pc.case_dir.exists())
    check("seed with an empty extraction -> METIN_BOS and NO case dir is created",
          code_of(I.seed_case, paths=pc, source_pdf=source, page_count=1, tax_types=["KDV"], extractor=lambda p: "  ", manifest=R.RunManifest(), protected_roots=roots) == "METIN_BOS"
          and not pc.case_dir.exists())

    def boom(path):
        raise RuntimeError("tarih 10.02.2026 yol C:\\gizli")
    check("seed with a crashing extractor -> CIKARICI_BASARISIZ (the message never propagates) and NO case dir is created",
          code_of(I.seed_case, paths=pc, source_pdf=source, page_count=1, tax_types=["KDV"], extractor=boom, manifest=R.RunManifest(), protected_roots=roots) == "CIKARICI_BASARISIZ"
          and not pc.case_dir.exists())

    # ---------------------------------------------------------------- aynı dosya (samefile)
    pd = new_paths("d")
    state_before = (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns)
    check("if the copy were the SAME file as the source the seed refuses (KAYNAK_AYNI_DOSYA)",
          code_of(I.seed_case, paths=pd, source_pdf=source, page_count=1, tax_types=["KDV"], extractor=lambda p: TEXT, manifest=R.RunManifest(),
                  protected_roots=roots, samefile=lambda a, b: True) == "KAYNAK_AYNI_DOSYA")
    check("... and it deletes NOTHING itself: the source is intact (no destructive call at all)",
          source.exists() and (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == state_before and not SOURCE_EVENTS)

    # ---------------------------------------------------------------- L-3: kopyalamadan ÖNCE dosya-kimliğiyle takma ad denetimi
    pe = new_paths("e")
    compared = []

    def alias_probe(a, b):
        compared.append((os.path.normcase(os.path.realpath(a)), os.path.normcase(os.path.realpath(b))))
        # yalnız ÜÇÜNCÜ farklı üst dizinden itibaren, vaka kökünün takma adı gibi davran
        return len({x for x, _y in compared}) >= 3 and os.path.normcase(os.path.realpath(b)) == os.path.normcase(os.path.realpath(str(pe.case_dir.parent)))
    # `source` yolu yazıldığı hâliyle korunan kökün içinde DEĞİL (realpath denetimi geçer); ama bir ÜST dizini
    # dosya-kimliğiyle korunan kökün AYNISI gibi davranırsa (subst/UNC/junction takma adı) kopyalamadan önce reddedilir.
    check("L-3: a source whose ANCESTOR is the same directory as a protected root (alias the path text does not reveal) is refused BEFORE anything is created (KAYNAK_ICERIDE)",
          code_of(I.seed_case, paths=pe, source_pdf=source, page_count=1, tax_types=["KDV"], extractor=lambda p: TEXT, manifest=R.RunManifest(),
                  protected_roots=roots, alias_samefile=alias_probe) == "KAYNAK_ICERIDE" and not pe.case_dir.exists()
          and not pe.run_dir.joinpath("x").exists())
    check("L-3: the alias check walks the source's ancestors against every EXISTING protected root (the probe saw the source dir and its parents)",
          any(a == os.path.normcase(os.path.realpath(str(source))) for a, _b in compared) and len({a for a, _b in compared}) >= 3)
    check("L-3: with the real file-identity comparison an unaliased source passes the pre-copy check (no false refusal)",
          I.check_source_path(source, protected_roots=roots) == source)
    check("L-3: a protected root that does not exist yet (the future case dir) is skipped, never an error",
          I.check_source_path(source, protected_roots=roots + [TMP / "henuz_yok"]) == source)
    check("L-3: the pre-copy alias refusal still leaves the source intact (no destructive call)",
          source.exists() and (hashlib.sha256(source.read_bytes()).hexdigest(), source.stat().st_mtime_ns) == state_before and not SOURCE_EVENTS)
finally:
    WATCH["source"] = None
    try:
        os.chmod(TMP / "buro_arsivi" / "asil_ihbarname.pdf", 0o666)
    except OSError:
        pass
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
