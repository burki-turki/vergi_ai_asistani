# ============================================================
# DEMO P1 - ui/demo_case_review.py (CLI) İZOLE TESTİ
#
#   uçtan uca, depo DIŞI demo klasöründe, enjekte metin çıkarıcıyla:
#   - ilk çalıştırma vakayı hazırlar + HTML üretir; ikinci çalıştırma yeniden hazırlamaz, İKİNCİ HTML üretir
#   - `demo_` olmayan kimlik / depo içi kök / bozuk-eksik spec / bilinmeyen argüman: kapalı hata kodu, içerik sızmaz
#   - --siki: eşleşmeyen alıntı varsa HİÇBİR ŞEY yazılmadan RET
#   - ağ yok, alt süreç yok (enjekte çıkarıcı), PDF'ler değişmez, yazma yalnız demo kökünde
#   - stdout yalnız yol + sayılar (alıntı/sayfa metni/belge içeriği yok)
# ============================================================

import hashlib
import io
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
    print(f"--- test_demo_case_review_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui import demo_case_review as C  # noqa: E402

TEBLIG = "İhbarname, mükellefe 10.02.2026 tarihinde tebliğ edilmiştir."
TEXTS = {
    "ihbarname.pdf": "SAYFA-BIR-BASLIK\nDüzenleme Tarihi: 05.02.2026\n" + TEBLIG + "\nEkler: Ek-1 Vergi İnceleme Raporu.\fSAYFA-IKI-BASLIK\n" + TEBLIG + "\nEk-2 (Bilirkişi görüşü) ekte sunulmuştur.\f",
    "tebligat.pdf": "Tebliğ tarihi: 10.02.2026\f",
    "vir.pdf": "Rapor Tarihi: 20.01.2026\fVergi aslı: 850.000,00 TL\f",
}
DATE = lambda iso: [{"value_type": "date", "label": "Tarih", "value": iso}]  # noqa: E731


def finding(fact_id, doc, page, excerpt, kind, statement, values=None):
    item = {"fact_id": fact_id, "doc_id": doc, "page": page, "excerpt": excerpt, "fact_kind": kind,
            "statement": statement, "origin": "ornek"}
    if values:
        item["degerler"] = values
    return item


def spec_raw(demo_id="demo_001", *, with_bad_finding=True):
    findings = [
        finding("b01_s1", "ihbarname_001", 1, TEBLIG, "date_fact", "Tebliğ (1. sayfa)", DATE("2026-02-10")),
        finding("b02_s2", "ihbarname_001", 2, TEBLIG, "date_fact", "Tebliğ (2. sayfa)", DATE("2026-02-10")),
        finding("b03_teb", "tebligat_001", 1, "Tebliğ tarihi: 10.02.2026", "date_fact", "Mazbata tarihi", DATE("2026-02-10")),
    ]
    if with_bad_finding:
        findings.append(finding("b04_yanlis", "ihbarname_001", 2, "Düzenleme Tarihi: 05.02.2026", "date_fact", "Yanlış sayfa", DATE("2026-02-05")))
    return {
        "schema_version": 1, "demo_id": demo_id,
        "belgeler": [
            {"doc_id": "ihbarname_001", "file_name": "ihbarname.pdf", "document_type": "vergi_ceza_ihbarnamesi",
             "title": "Vergi ve ceza ihbarnamesi (sentetik)", "declared_page_count": 2},
            {"doc_id": "tebligat_001", "file_name": "tebligat.pdf", "document_type": "teblig_mazbatasi",
             "title": "Tebliğ mazbatası (sentetik)", "declared_page_count": 1},
            {"doc_id": "ek_001", "file_name": "vir.pdf", "document_type": "vergi_inceleme_raporu",
             "title": "Vergi inceleme raporu (Ek-1, sentetik)", "declared_page_count": 2},
        ],
        "bulgular": findings,
        "eksik_atiflar": [
            {"fact_id": "a01_ek2", "referenced_in_doc": "ihbarname_001", "page": 2,
             "excerpt": "Ek-2 (Bilirkişi görüşü) ekte sunulmuştur.", "referenced_name": "Ek-2", "origin": "ornek"},
        ],
    }


TMP = Path(tempfile.mkdtemp(prefix="vergi_p1_cli_"))
LINKS = []
EVENTS = {"on": False, "net": [], "proc": [], "opened": [], "writes": []}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_TRUNC", 0)


def _audit(event, args):
    if not EVENTS["on"]:
        return
    try:
        if event.startswith("socket.") and event not in ("socket.gethostname",):
            EVENTS["net"].append(event)
        elif event in ("subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn"):
            EVENTS["proc"].append(event)
        elif event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            path = os.path.normcase(os.path.realpath(os.fsdecode(args[0])))
            mode = args[1] if len(args) > 1 and isinstance(args[1], str) else ""
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            EVENTS["opened"].append(path)
            if any(c in mode for c in "wax+") or flags & _WRITE_FLAGS:
                EVENTS["writes"].append(path)
    except Exception:
        pass


sys.addaudithook(_audit)


def norm(path):
    return os.path.normcase(os.path.realpath(str(path)))


def make_root(name, raw=None, *, spec_name="demo_spec.json"):
    root = TMP / name
    (root / "belgeler").mkdir(parents=True)
    for file_name in TEXTS:
        (root / "belgeler" / file_name).write_bytes(b"%PDF-1.4\n% sentetik " + file_name.encode() + b"\n")
    (root / "beklenen_degerlendirme.txt").write_text("AVUKAT CEVABI (decoy)", encoding="utf-8")
    (root / "belgeler" / "beklenen_degerlendirme_AYRI.docx").write_text("decoy", encoding="utf-8")
    if raw is not False:
        (root / spec_name).write_text(json.dumps(raw or spec_raw(), ensure_ascii=False), encoding="utf-8")
    return root


def run(argv, *, extractor=None):
    out, err = io.StringIO(), io.StringIO()
    rc = C.main(argv, extractor=extractor or (lambda source: TEXTS[Path(source).name]), stdout=out, stderr=err)
    return rc, out.getvalue(), err.getvalue()


def pdf_state(root):
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_size, p.stat().st_mtime_ns) for p in sorted((root / "belgeler").glob("*.pdf"))}


def listing(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


try:
    # ================= uçtan uca: ilk çalıştırma
    root = make_root("kok_1")
    pdfs_before = pdf_state(root)
    other_before = {k: v for k, v in {str(p): p.read_bytes() for p in TMP.rglob("*") if p.is_file() and "kok_1" not in str(p)}.items()}
    EVENTS.update(on=True, net=[], proc=[], opened=[], writes=[])
    rc, out, err = run(["--demo-root", str(root)])
    EVENTS["on"] = False
    check("first run: exit 0 and nothing on stderr", rc == 0 and err == "", err)
    outputs = sorted((root / "cikti").glob("inceleme_*.html"))
    check("first run: exactly one report file under <demo-root>/cikti", len(outputs) == 1)
    html = outputs[0].read_text(encoding="utf-8") if outputs else ""
    check("first run: stdout shows the output path, 'yeni hazırlandı' and the counts (3 documents; 3 matched; 1 warning; 1 citation)",
          f"ÇIKTI: {outputs[0]}" in out and "vaka: yeni hazırlandı" in out and "belge: 3" in out
          and "bulgu eşleşen: 3; alıntısı eşleşmeyen (uyarı): 1" in out and "atıf kaydı: 1" in out, out)
    check("stdout carries NO document content (no excerpt, no page text, no title)",
          not any(token in out for token in ("İhbarname, mükellefe", "SAYFA-BIR", "Bilirkişi", "Vergi inceleme raporu")))
    check("the prepared case exists under vaka/<demo_id> with facts, labels and the result record",
          (root / "vaka" / "demo_001" / "case.json").is_file() and (root / "vaka" / "demo_001" / "demo_p1_sonuc.json").is_file()
          and (root / "vaka" / "demo_001" / "demo_content_labels.json").is_file()
          and len(list((root / "vaka" / "demo_001" / "documents").glob("*/extractions/facts.json"))) == 2)
    check("the report shows both the matched and the unmatched finding and the Ek-2 combined sentence",
          "Tebliğ (1. sayfa)" in html and "EŞLEŞMEDİ" in html and "İhbarnamede atıf var, sunulan dosyalar arasında bulunamadı" in html)
    check("AD-12: the source PDFs are byte/size/mtime identical after the run", pdf_state(root) == pdfs_before)
    check("AD-10: neither decoy 'beklenen_degerlendirme*' file was ever opened", not [p for p in EVENTS["opened"] if "beklenen_degerlendirme" in p])
    check("no network event and no subprocess/exec was started (injected extractor)", EVENTS["net"] == [] and EVENTS["proc"] == [], str(EVENTS["net"] + EVENTS["proc"]))
    root_real = norm(root)
    check("every write-mode open was inside the demo root (and the detector saw real writes)",
          bool(EVENTS["writes"]) and all(w.startswith(root_real) for w in EVENTS["writes"]), str([w for w in EVENTS["writes"] if not w.startswith(root_real)][:3]))
    check("nothing outside the demo root changed in the temp tree",
          other_before == {str(p): p.read_bytes() for p in TMP.rglob("*") if p.is_file() and "kok_1" not in str(p)})
    check("the temp case did not create anything inside the repo's data/cases",
          not (REPO_ROOT / "data" / "cases" / "demo_001").exists())

    # ================= ikinci çalıştırma
    rc2, out2, err2 = run(["--demo-root", str(root)])
    outputs2 = sorted((root / "cikti").glob("inceleme_*.html"))
    check("AD-13: second run: exit 0, 'mevcut, yeniden hazırlanmadı', and a SECOND, distinct report file (first not overwritten)",
          rc2 == 0 and "vaka: mevcut, yeniden hazırlanmadı" in out2 and len(outputs2) == 2 and outputs2[0].read_bytes() == outputs[0].read_bytes()
          and len({p.name for p in outputs2}) == 2, out2 + err2)
    case_before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "vaka").rglob("*") if p.is_file()}
    run(["--demo-root", str(root)])
    case_after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / "vaka").rglob("*") if p.is_file()}
    check("re-running never rewrites the prepared case (vaka/ byte-identical)", case_before == case_after)
    check("two reports of the same case have identical content", outputs2[0].read_bytes() == outputs2[1].read_bytes())

    # ================= --spec açık yol
    root_s = make_root("kok_spec", raw=False)
    spec_out = TMP / "baska_yer_spec.json"
    spec_out.write_text(json.dumps(spec_raw(), ensure_ascii=False), encoding="utf-8")
    rc_s, out_s, err_s = run(["--demo-root", str(root_s), "--spec", str(spec_out)])
    check("an explicit --spec outside the demo root works", rc_s == 0 and len(list((root_s / "cikti").glob("*.html"))) == 1, err_s)

    # ================= hata yolları (kapalı kod, içerik yok)
    root_e = make_root("kok_e1", raw=False)
    rc_e, out_e, err_e = run(["--demo-root", str(root_e)])
    check("a missing demo_spec.json -> 'HATA: SPEC_YOK', exit 1, nothing created",
          rc_e == 1 and err_e.strip() == "HATA: SPEC_YOK" and not (root_e / "vaka").exists() and not (root_e / "cikti").exists())
    root_b = make_root("kok_e2", raw=False)
    (root_b / "demo_spec.json").write_text("{bozuk", encoding="utf-8")
    rc_b, _, err_b = run(["--demo-root", str(root_b)])
    check("a corrupt spec -> HATA: SPEC_BOZUK, exit 1", rc_b == 1 and err_b.strip() == "HATA: SPEC_BOZUK")
    bad_id = make_root("kok_e3", spec_raw("case_0001"))
    rc_i, _, err_i = run(["--demo-root", str(bad_id)])
    check("AD-9: a demo id that does not start with demo_ (case_0001) is refused; nothing is created",
          rc_i == 1 and err_i.strip() == "HATA: DEMO_KIMLIGI_GECERSIZ" and not (bad_id / "vaka").exists())
    rc_r, _, err_r = run(["--demo-root", str(REPO_ROOT / "ui")])
    check("a demo root INSIDE the repo is refused", rc_r == 1 and err_r.strip() == "HATA: DEMO_KOKU_DEPO_ICINDE")
    rc_d, _, err_d = run(["--demo-root", str(REPO_ROOT / "data" / "cases")])
    check("the repo's data/cases is refused as a demo root", rc_d == 1 and err_d.strip() == "HATA: DEMO_KOKU_DEPO_ICINDE")
    rc_n, _, err_n = run(["--demo-root", str(TMP / "yok_kok")])
    check("a non-existing demo root -> HATA: DEMO_KOKU_GECERSIZ", rc_n == 1 and err_n.strip() == "HATA: DEMO_KOKU_GECERSIZ")
    rc_rel, _, err_rel = run(["--demo-root", "goreli_kok"])
    check("a relative demo root is refused", rc_rel == 1 and err_rel.strip() == "HATA: DEMO_KOKU_GECERSIZ")
    rc_spec_repo, _, err_spec_repo = run(["--demo-root", str(root_s), "--spec", str(REPO_ROOT / "CLAUDE.md")])
    check("a --spec inside the repo is refused (never read)", rc_spec_repo == 1 and err_spec_repo.strip() == "HATA: DEMO_KOKU_DEPO_ICINDE")
    rc_u, _, err_u = run(["--bilinmeyen"])
    check("an unknown argument -> exit 2 (usage), no traceback on stdout", rc_u == 2)
    rc_m, _, err_m = run([])
    check("a missing --demo-root -> exit 2", rc_m == 2)

    def exploding(source):
        raise RuntimeError("GİZLİ İÇERİK Poppler çöktü")

    root_x = make_root("kok_e4")
    rc_x, out_x, err_x = run(["--demo-root", str(root_x)], extractor=exploding)
    check("an extractor failure -> HATA: CIKARICI_BASARISIZ with NO message/content/traceback",
          rc_x == 1 and err_x.strip() == "HATA: CIKARICI_BASARISIZ" and "GİZLİ" not in out_x + err_x and "Traceback" not in out_x + err_x)
    check("an extractor failure leaves no half-built case and no output", not (root_x / "vaka").exists() and not (root_x / "cikti").exists())
    wrong = dict(TEXTS)
    wrong["vir.pdf"] = "tek sayfa\f"
    rc_p, _, err_p = run(["--demo-root", str(make_root("kok_e5"))], extractor=lambda s: wrong[Path(s).name])
    check("a physical page count different from the declared one -> HATA: SAYFA_SAYISI_UYUSMUYOR", rc_p == 1 and err_p.strip() == "HATA: SAYFA_SAYISI_UYUSMUYOR")

    # ================= --siki
    root_k = make_root("kok_siki")
    rc_k, out_k, err_k = run(["--demo-root", str(root_k), "--siki"])
    check("AD-2: --siki with an unmatched excerpt -> HATA: ALINTI_ESLESMEDI, exit 1",
          rc_k == 1 and err_k.strip() == "HATA: ALINTI_ESLESMEDI")
    check("AD-2: --siki wrote NOTHING (no vaka/, no cikti/)", not (root_k / "vaka").exists() and not (root_k / "cikti").exists())
    root_ok = make_root("kok_siki_ok", spec_raw(with_bad_finding=False))
    rc_ok, out_ok, err_ok = run(["--demo-root", str(root_ok), "--siki"])
    check("AD-2: --siki with every excerpt matching passes (exit 0) — the Ek-2 absence is not an excerpt failure",
          rc_ok == 0 and "alıntısı eşleşmeyen (uyarı): 0" in out_ok, err_ok)
    rc_plain, _, _ = run(["--demo-root", str(root_k)])
    rc_after, _, err_after = run(["--demo-root", str(root_k), "--siki"])
    check("--siki on an already prepared case with warnings is also refused (and writes no new report)",
          rc_plain == 0 and rc_after == 1 and err_after.strip() == "HATA: ALINTI_ESLESMEDI" and len(list((root_k / "cikti").glob("*.html"))) == 1)

    # ================= yanlış hazırlanmış vaka: kapalı hata, sessiz devralma yok
    root_h = make_root("kok_yarim")
    (root_h / "vaka" / "demo_001").mkdir(parents=True)
    rc_h, _, err_h = run(["--demo-root", str(root_h)])
    check("a half-written case dir is NOT silently adopted (closed error 'HATA: <KOD>', no report written)",
          rc_h == 1 and err_h.strip() == "HATA: VAKA_YARIM" and not (root_h / "cikti").exists())
    check("module-level entry: the CLI has a __main__ guard (importing it runs nothing)", "__main__" in (UI_DIR / "demo_case_review.py").read_text(encoding="utf-8"))

    # ================= M-1 (CLI): vaka/ ve cikti/ bağlantıları; _write_output'un kendi koruması
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

    def entries(path):
        return sorted(str(p.relative_to(path)) for p in Path(path).rglob("*"))

    outside_a = TMP / "disari_a"
    outside_a.mkdir()
    root_l1 = make_root("kok_link_vaka")
    if not mklink(outside_a, root_l1 / "vaka"):
        print("SKIPPED link scenarios - no junction/symlink support here")
        skipped += 1
    else:
        EVENTS.update(on=True, net=[], proc=[], opened=[], writes=[])
        rc_l1, out_l1, err_l1 = run(["--demo-root", str(root_l1)])
        EVENTS["on"] = False
        check("M-1 (CLI): vaka is a junction to a directory outside the root: HATA: DIZIN_GUVENSIZ, exit 1, no output on stdout",
              rc_l1 == 1 and err_l1.strip() == "HATA: DIZIN_GUVENSIZ" and out_l1 == "", err_l1)
        check("M-1 (CLI): ... the junction target stays EMPTY and no cikti/ was created in the root", entries(outside_a) == [] and not (root_l1 / "cikti").exists())
        check("M-1 (CLI): ... no write-mode open went to a path outside the demo root",
              not [w for w in EVENTS["writes"] if not w.startswith(norm(root_l1)) and not w.endswith((".pyc",))], str(EVENTS["writes"][:3]))

        outside_b = TMP / "disari_b"
        outside_b.mkdir()
        root_l2 = make_root("kok_link_cikti")
        mklink(outside_b, root_l2 / "cikti")
        rc_l2, out_l2, err_l2 = run(["--demo-root", str(root_l2)])
        check("M-1 (CLI): cikti is a junction to a directory outside the root: HATA: DIZIN_GUVENSIZ and no case/HTML written",
              rc_l2 == 1 and err_l2.strip() == "HATA: DIZIN_GUVENSIZ" and entries(outside_b) == [] and entries(root_l2 / "vaka") == [], err_l2)

        # case hazırlandıktan SONRA cikti bağlantıya çevrilirse: _write_output'un kendi koruması
        outside_c = TMP / "disari_c"
        outside_c.mkdir()
        root_l3 = make_root("kok_link_cikti_sonra")
        rc_first, _, _ = run(["--demo-root", str(root_l3)])
        for produced in (root_l3 / "cikti").glob("*"):
            produced.unlink()
        os.rmdir(str(root_l3 / "cikti"))
        mklink(outside_c, root_l3 / "cikti")
        rc_l3, out_l3, err_l3 = run(["--demo-root", str(root_l3)])
        check("M-1 (CLI): cikti turned into a junction AFTER the case exists: _write_output refuses (DIZIN_GUVENSIZ), target empty",
              rc_first == 0 and rc_l3 == 1 and err_l3.strip() == "HATA: DIZIN_GUVENSIZ" and entries(outside_c) == [], err_l3)

    # ================= L-3 / L-5 (CLI): var olan vakayı devralma
    root_h2 = make_root("kok_yarim2")
    (root_h2 / "vaka" / "demo_001").mkdir(parents=True)
    rc_y, _, err_y = run(["--demo-root", str(root_h2)])
    check("L-5 (CLI): an empty leftover case dir -> HATA: VAKA_YARIM (clear code, no misleading result error); the tool deletes nothing",
          rc_y == 1 and err_y.strip() == "HATA: VAKA_YARIM" and (root_h2 / "vaka" / "demo_001").is_dir() and not (root_h2 / "cikti").exists())
    root_ch = make_root("kok_spec_degisti")
    rc_a, _, _ = run(["--demo-root", str(root_ch)])
    changed_spec = spec_raw()
    changed_spec["belgeler"][0]["title"] = "Başka bir başlıkla değiştirilmiş spec"
    (root_ch / "demo_spec.json").write_text(json.dumps(changed_spec, ensure_ascii=False), encoding="utf-8")
    reports_before = sorted((root_ch / "cikti").glob("*.html"))
    rc_b, out_b, err_b = run(["--demo-root", str(root_ch)])
    check("L-3 (CLI): the spec CHANGED after the case was prepared: HATA: VAKA_UYUSMUYOR (no stale report produced)",
          rc_a == 0 and rc_b == 1 and err_b.strip() == "HATA: VAKA_UYUSMUYOR" and out_b == "" and sorted((root_ch / "cikti").glob("*.html")) == reports_before)
    root_ow = make_root("kok_baska_id")
    run(["--demo-root", str(root_ow)])
    marker_path = root_ow / "vaka" / "demo_001" / ".demo_p1_owner"
    marker_path.write_text(json.dumps({"kind": "demo_p1_case", "demo_id": "demo_777", "spec_digest": "0" * 64}), encoding="utf-8")
    rc_o, _, err_o = run(["--demo-root", str(root_ow)])
    check("L-3 (CLI): an existing case whose ownership marker names another demo id is not adopted (VAKA_UYUSMUYOR)",
          rc_o == 1 and err_o.strip() == "HATA: VAKA_UYUSMUYOR")
    root_cr = make_root("kok_sonuc_bozuk")
    run(["--demo-root", str(root_cr)])
    record_path = root_cr / "vaka" / "demo_001" / "demo_p1_sonuc.json"
    tampered = json.loads(record_path.read_text(encoding="utf-8"))
    tampered["documents"][0]["pdf_rel"] = "../../disari.pdf"
    record_path.write_text(json.dumps(tampered), encoding="utf-8")
    rc_t, _, err_t = run(["--demo-root", str(root_cr)])
    check("L-3 (CLI): a result record with a traversing pdf_rel is refused (SONUC_KAYDI_GECERSIZ), never followed",
          rc_t == 1 and err_t.strip() == "HATA: SONUC_KAYDI_GECERSIZ")
    check("O-2: NO junction/symlink created by this module resolves into the real repo (every link target is under the temporary tree)",
          all(norm(link).startswith(norm(TMP)) and not norm(link).startswith(norm(REPO_ROOT)) for link in LINKS))
finally:
    EVENTS["on"] = False
    for _link in LINKS:
        try:
            os.rmdir(str(_link))  # yalnız bağlantıyı kaldırır; hedefe dokunmaz
        except OSError:
            pass
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
