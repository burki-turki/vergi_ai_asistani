# ============================================================
# BÜRO MODELİ / T1 - ui/services/office_flow_cleanup.py İZOLE TESTİ
#
# Silme: sahiplik işareti + kapalı tür listesi; bilinmeyen girdi / işaretsiz
# hedef / bağlantı (junction) => HİÇBİR ŞEY silinmez (REDDEDILDI);
# BASLADI -> sil -> doğrula -> SONUC; TAMAMLANDI yalnız doğrulamadan SONRA;
# yarım silme KISMEN; süreç ölümü (BaseException) => son kayıt BASLADI;
# yeniden başlatmada yalnız kalan bildirimli öğeler silinir.
# Asıl PDF ve kök dışı hiçbir şeye dokunulmaz (audit-hook + bayt/mtime kanıtı).
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
    print(f"--- test_office_flow_cleanup_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import office_flow_cleanup as C  # noqa: E402
from ui.services import office_flow_outcomes as O  # noqa: E402
from ui.services import office_flow_records as R  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vergi_t1_cleanup_"))
SOURCE_EVENTS = []
WATCH = {"path": None}


def _audit(event, args):
    try:
        if WATCH["path"] and args and event in ("os.remove", "os.rmdir", "os.rename", "shutil.rmtree", "open"):
            first = args[0]
            if isinstance(first, (str, bytes, os.PathLike)) and os.path.normcase(os.path.realpath(os.fsdecode(first))) == WATCH["path"]:
                if event != "open" or (isinstance(args[1], str) and any(c in args[1] for c in "wax+")):
                    SOURCE_EVENTS.append(event)
    except Exception:
        pass


sys.addaudithook(_audit)


class SimulatedKill(BaseException):
    pass


class FaultyFs(C.FsOps):
    def __init__(self, deny=None, fail_after=None, kill_after=None):
        self.deny, self.fail_after, self.kill_after, self.calls = deny, fail_after, kill_after, 0

    def unlink(self, path):
        self.calls += 1
        if self.deny and self.deny in str(path).replace("\\", "/"):
            raise PermissionError("kilitli")
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("beklenmeyen")
        if self.kill_after is not None and self.calls > self.kill_after:
            raise SimulatedKill()
        super().unlink(path)


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


def listing(*roots):
    out = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            out.extend(os.path.join(dirpath, f) for f in files)
    return sorted(out)


def build_run(tag, *, with_unknown=False):
    """Gerçek bir koşunun dosya düzenini taklit eden sentetik düzen."""
    office = TMP / f"ofis_{tag}"
    cases = TMP / f"vakalar_{tag}"
    office.mkdir()
    cases.mkdir()
    R.ensure_office_infra(office)
    run_id = R.new_run_id()
    paths = R.build_run_paths(office, cases, f"vaka{tag}", run_id)
    R.create_owned_dir(paths.run_dir, run_id=run_id, kind="run_dir")
    R.create_owned_dir(paths.case_dir, run_id=run_id, kind="case_dir")
    doc = paths.case_dir / "documents" / "ihbarname_001"
    for rel in ("documents", "documents/ihbarname_001", "documents/ihbarname_001/extracted", "documents/ihbarname_001/extractions",
                "documents/ihbarname_001/extractions/reviews", "timeline", "deadlines", "deadlines/reviews"):
        (paths.case_dir / rel).mkdir(exist_ok=True)
    files = {
        "case.json": b"{}", "documents/ihbarname_001/document.json": b"{}", "documents/ihbarname_001/ihbarname_001.pdf": b"%PDF copy",
        "documents/ihbarname_001/extracted/ihbarname_001.txt": b"metin", "documents/ihbarname_001/extractions/facts.json": b"{}",
        "documents/ihbarname_001/extractions/facts_x.json.pending": b"{}", "documents/ihbarname_001/extractions/reviews/a.approval.json": b"{}",
        "timeline/timeline.json": b"{}", "deadlines/deadline.json": b"{}", "deadlines/reviews/b.approval.json": b"{}",
        "deadlines/deadline.json.before_approval_x.bak": b"b",
    }
    for rel, data in files.items():
        (paths.case_dir / rel).write_bytes(data)
    (paths.run_dir / "run_state.json").write_text(json.dumps({"durum": "SILME_ONAYI_BEKLIYOR"}), encoding="utf-8")
    (paths.run_dir / "okuma_kaydi.json").write_text("{}", encoding="utf-8")
    (paths.run_dir / "pilot_hesap_raporu.txt").write_text("rapor", encoding="utf-8")
    paths.tmp_dir.mkdir()
    (paths.tmp_dir / "tmpabc123").write_bytes(b"gecici")
    (paths.tmp_dir / "alt").mkdir()
    (paths.tmp_dir / "alt" / "tmpdef456").write_bytes(b"gecici2")
    # Koşu bildirimi: akışın KENDİ oluşturduğu her dosya/dizin (gerçek akışta
    # `_tracked`/`restore_temp` bunu yapar). Silme üyeliği YALNIZ buradan gelir.
    manifest = R.RunManifest()
    for rel in ("documents", "documents/ihbarname_001", "documents/ihbarname_001/extracted", "documents/ihbarname_001/extractions",
                "documents/ihbarname_001/extractions/reviews", "timeline", "deadlines", "deadlines/reviews"):
        manifest.add_dir(root="case", rel=rel)
    for rel in files:
        manifest.add(root="case", rel=rel, tur=C.classify_case_file(rel))
    for rel in ("run_state.json", "okuma_kaydi.json"):
        manifest.add(root="run", rel=rel, tur="CALISMA_DOSYALARI")
    manifest.add(root="run", rel="pilot_hesap_raporu.txt", tur="PILOT_HESAP_RAPORU")
    manifest.add_dir(root="run", rel="tmp")
    manifest.add_dir(root="run", rel="tmp/alt")
    manifest.add(root="run", rel="tmp/tmpabc123", tur="GECICI_DOSYALAR")
    manifest.add(root="run", rel="tmp/alt/tmpdef456", tur="GECICI_DOSYALAR")
    R.save_manifest(paths, manifest)
    if with_unknown:
        (doc / "yabanci.docx").write_bytes(b"baska biri")
    return paths


def manifest_of(paths):
    return R.RunManifest.load(paths.manifest_path)


def save_manifest_of(paths, manifest):
    R.save_manifest(paths, manifest)


def run_delete(paths, **kwargs):
    return C.execute_deletion(paths, records_dir=paths.records_dir, confirmed=True, **kwargs)


def imha(paths, token):
    return [r for _s, r in O.imha_records_for(paths.records_dir, token)]


# Asıl PDF (kök dışı, salt-okunur)
ORIGINAL = TMP / "buro_arsivi" / "asil_ihbarname.pdf"
ORIGINAL.parent.mkdir()
ORIGINAL.write_bytes(b"%PDF-1.4 asil belge")
os.chmod(ORIGINAL, 0o444)
WATCH["path"] = os.path.normcase(os.path.realpath(str(ORIGINAL)))
ORIGINAL_ID = (hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(), ORIGINAL.stat().st_size, ORIGINAL.stat().st_mtime_ns)
(TMP / "buro_arsivi" / "musteri_dosyasi.txt").write_text("muvekkil dosyasi", encoding="utf-8")


def original_ok():
    return ORIGINAL.exists() and (hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(), ORIGINAL.stat().st_size,
                                  ORIGINAL.stat().st_mtime_ns) == ORIGINAL_ID and not SOURCE_EVENTS and (
        TMP / "buro_arsivi" / "musteri_dosyasi.txt").read_text(encoding="utf-8") == "muvekkil dosyasi"


try:
    # ---------------------------------------------------------------- sınıflandırma
    for rel, expected in (
        ("case.json", "CALISMA_DOSYALARI"), ("documents/d/document.json", "CALISMA_DOSYALARI"),
        ("documents/d/d.pdf", "CALISMA_DIZINI_BELGE_KOPYASI"), ("documents/d/extracted/d.txt", "CIKARILMIS_METIN"),
        ("documents/d/manual_input/manual_facts.input.json", "CALISMA_DOSYALARI"),
        ("documents/d/extractions/reviews/fact_verifications/x.verification.json", "CALISMA_DOSYALARI"),
        ("documents/d/extractions/history/f.json", "CALISMA_DOSYALARI"), ("timeline/timeline_v1_1.json.pending", "CALISMA_DOSYALARI"),
        ("deadlines/generation_reviews/g.generation_audit.json", "CALISMA_DOSYALARI"), ("deadlines/deadline.json.before_x.bak", "CALISMA_DOSYALARI"),
        (".office_flow_owner", "INFRA"),
    ):
        check(f"case-dir classification: {rel} -> {expected}", C.classify_case_file(rel) == expected, str(C.classify_case_file(rel)))
    for rel in ("notlar.docx", "documents/d/notlar.docx", "documents/d/extracted/d.docx", "documents/d/x.exe", "baska_dizin/a.json",
                "drafting/drafting.json", "documents/d/extractions/a.sh", "timeline/a.docx", "gizli.txt", "documents/d/sub/deep/a.json"):
        check(f"case-dir classification: {rel} is NOT in the closed list (ownership uncertain)", C.classify_case_file(rel) is None)
    for rel, expected in (("run_state.json", "CALISMA_DOSYALARI"), ("run_manifest.json", "CALISMA_DOSYALARI"), ("okuma_kaydi.json", "CALISMA_DOSYALARI"),
                          ("run_state.json.tmp", "CALISMA_DOSYALARI"), ("pilot_hesap_raporu.txt", "PILOT_HESAP_RAPORU"),
                          ("tmp/tmpabc", "GECICI_DOSYALAR"), ("tmp/alt/tmpdef", "GECICI_DOSYALAR"), (".office_flow_owner", "INFRA")):
        check(f"run-dir classification: {rel} -> {expected}", C.classify_run_file(rel) == expected)
    check("run-dir classification: a stray file is not owned", C.classify_run_file("notlarim.txt") is None and C.classify_run_file("baska/a.txt") is None)

    # ---------------------------------------------------------------- plan + onaysız çağrı
    p1 = build_run("a")
    plan = C.build_deletion_plan(p1)
    check("a clean owned layout yields an OK plan with ZERO unknown entries and per-type counts",
          plan.ok and plan.unknown_count == 0 and set(plan.counts) == {"CALISMA_DOSYALARI", "CALISMA_DIZINI_BELGE_KOPYASI", "CIKARILMIS_METIN",
                                                                        "PILOT_HESAP_RAPORU", "GECICI_DOSYALAR"}, f"{plan.counts} {plan.unknown_count}")
    check("the plan exposes only (type, count) pairs for the lawyer — no file names",
          all(set(item) == {"tur", "adet"} for item in plan.type_counts()))
    before = listing(p1.case_dir, p1.run_dir)
    try:
        C.execute_deletion(p1, records_dir=p1.records_dir, confirmed=False)
        code = None
    except R.OfficeFlowError as error:
        code = error.code
    check("without the lawyer's separate confirmation nothing is deleted and no record is written (SILME_ONAYI_YOK)",
          code == "SILME_ONAYI_YOK" and listing(p1.case_dir, p1.run_dir) == before and not list(p1.records_dir.iterdir()))

    # ---------------------------------------------------------------- tam silme (S1 mantığı)
    result = run_delete(p1)
    records_a = imha(p1, result.token)
    check("a healthy deletion ends TAMAMLANDI with both owned dirs gone",
          result.outcome == "TAMAMLANDI" and not p1.case_dir.exists() and not p1.run_dir.exists(), f"{result}")
    check("it wrote exactly BASLADI then SONUC=TAMAMLANDI (never a result before the verification)",
          [r["asama"] for r in records_a] == ["BASLADI", "SONUC"] and "genel_sonuc" not in records_a[0] and records_a[1]["genel_sonuc"] == "TAMAMLANDI")
    check("the records carry the scope YALNIZ_PILOT_KOPYALARI and list the DB records as NOT deleted",
          all(r["tamamlandi_kapsami"] == "YALNIZ_PILOT_KOPYALARI" and r["silinmeyenler"] == ["VERITABANI_ISLEM_KAYITLARI"] for r in records_a))
    check("the SONUC record lists each type with its count and TAMAMLANDI",
          {i["tur"]: (i["adet"], i["sonuc"]) for i in records_a[1]["kopya_turleri"]}.get("PILOT_HESAP_RAPORU") == (1, "TAMAMLANDI")
          and {i["tur"] for i in records_a[1]["kopya_turleri"]} == {"CALISMA_DOSYALARI", "CALISMA_DIZINI_BELGE_KOPYASI", "CIKARILMIS_METIN", "PILOT_HESAP_RAPORU", "GECICI_DOSYALAR"})
    check("kayitlar/ itself and everything outside the owned dirs survived", p1.records_dir.exists() and p1.office_root.exists() and original_ok())

    # ---------------------------------------------------------------- yabancı dosya / işaret yok / bağlantı
    p2 = build_run("b", with_unknown=True)
    before = listing(p2.case_dir, p2.run_dir)
    r2 = run_delete(p2)
    rec2 = imha(p2, r2.token)
    check("a foreign file inside the owned case dir -> REDDEDILDI: NOTHING deleted", r2.outcome == "REDDEDILDI" and listing(p2.case_dir, p2.run_dir) == before)
    check("the refusal is a SINGLE SONUC record (no BASLADI, no TAMAMLANDI) with an empty type list",
          len(rec2) == 1 and rec2[0]["asama"] == "SONUC" and rec2[0]["genel_sonuc"] == "REDDEDILDI" and rec2[0]["kopya_turleri"] == [])
    check("the refusal reason is the closed ownership code", r2.refusal_code == "SILME_BELIRSIZ_SAHIPLIK")
    (p2.case_dir / "documents" / "ihbarname_001" / "yabanci.docx").unlink()
    r2b = run_delete(p2, token=r2.token)
    check("once the lawyer removes the foreign file the same run can be deleted (TAMAMLANDI)", r2b.outcome == "TAMAMLANDI" and not p2.case_dir.exists())

    p3 = build_run("c")
    (p3.case_dir / R.OWNER_MARKER_NAME).unlink()
    before = listing(p3.case_dir, p3.run_dir)
    r3 = run_delete(p3)
    check("a case dir WITHOUT the ownership marker (wrong target) is refused, nothing deleted",
          r3.outcome == "REDDEDILDI" and r3.refusal_code == "SAHIPLIK_ISARETI_YOK" and listing(p3.case_dir, p3.run_dir) == before)

    p4 = build_run("d")
    (p4.case_dir / R.OWNER_MARKER_NAME).write_text(json.dumps({"kayit_surumu": 1, "kos": R.new_run_id(), "tur": "case_dir"}), encoding="utf-8")
    before = listing(p4.case_dir, p4.run_dir)
    r4 = run_delete(p4)
    check("a marker that belongs to ANOTHER run is refused (not this run's copy)", r4.outcome == "REDDEDILDI" and listing(p4.case_dir, p4.run_dir) == before)

    p5 = build_run("e")
    outside = TMP / "disarida"
    outside.mkdir()
    decoy = outside / "kritik_dosya.txt"
    decoy.write_text("silinmemeli", encoding="utf-8")
    linked = make_junction(p5.case_dir / "documents" / "baglanti", outside)
    if not linked:
        skip("junction/symlink inside the owned dir", "neither a junction nor a symlink could be created here. NOT EXECUTED, not a pass")
    else:
        before = listing(p5.case_dir, p5.run_dir)
        r5 = run_delete(p5)
        check("a junction/link inside the owned dir is NOT followed: REDDEDILDI, the decoy outside survives",
              r5.outcome == "REDDEDILDI" and decoy.exists() and decoy.read_text(encoding="utf-8") == "silinmemeli", f"{r5}")
        check("... and nothing inside the owned dir was deleted either", listing(p5.case_dir, p5.run_dir) == before and decoy.exists())
        os.rmdir(p5.case_dir / "documents" / "baglanti")

    # ---------------------------------------------------------------- (a) kilitli tek dosya
    p6 = build_run("f")
    r6 = run_delete(p6, fs=FaultyFs(deny="extractions/facts.json"))
    rec6 = imha(p6, r6.token)
    check("one undeletable path -> KISMEN; records BASLADI + SONUC=KISMEN; NEVER TAMAMLANDI",
          r6.outcome == "KISMEN" and [r["asama"] for r in rec6] == ["BASLADI", "SONUC"] and rec6[-1]["genel_sonuc"] == "KISMEN"
          and all(r.get("genel_sonuc") != "TAMAMLANDI" for r in rec6), f"{rec6}")
    check("the remaining TYPE is listed as KISMEN (others TAMAMLANDI)",
          {i["tur"]: i["sonuc"] for i in rec6[-1]["kopya_turleri"]}.get("CALISMA_DOSYALARI") == "KISMEN"
          and {i["tur"]: i["sonuc"] for i in rec6[-1]["kopya_turleri"]}.get("PILOT_HESAP_RAPORU") == "TAMAMLANDI")
    check("the ownership marker and run state are RETAINED so the deletion can be resumed (the rest of the content is gone)",
          R.read_owner_marker(p6.case_dir, run_id=p6.run_id, kind="case_dir") and (p6.run_dir / "run_state.json").exists()
          and not (p6.case_dir / "case.json").exists() and (p6.case_dir / "documents" / "ihbarname_001" / "extractions" / "facts.json").exists())
    r6b = run_delete(p6, token=r6.token)
    rec6b = imha(p6, r6.token)
    check("a healthy retry finishes: BASLADI + SONUC=TAMAMLANDI appended, exactly ONE TAMAMLANDI overall, both dirs gone",
          r6b.outcome == "TAMAMLANDI" and [r["asama"] for r in rec6b][-2:] == ["BASLADI", "SONUC"]
          and sum(1 for r in rec6b if r.get("genel_sonuc") == "TAMAMLANDI") == 1 and not p6.case_dir.exists() and not p6.run_dir.exists())

    # ---------------------------------------------------------------- (b) beklenmeyen istisna
    p7 = build_run("g")
    r7 = run_delete(p7, fs=FaultyFs(fail_after=1))
    rec7 = imha(p7, r7.token)
    check("an unexpected exception after the first unlink -> KISMEN, the rest remains, no TAMAMLANDI",
          r7.outcome == "KISMEN" and rec7[-1]["genel_sonuc"] == "KISMEN" and p7.case_dir.exists())
    r7b = run_delete(p7, token=r7.token)
    check("the retry completes the remaining owned copies only", r7b.outcome == "TAMAMLANDI" and not p7.case_dir.exists() and original_ok())

    # ---------------------------------------------------------------- (c) süreç ölümü
    p8 = build_run("h")
    token8 = O.new_imha_token()
    killed = False
    try:
        run_delete(p8, token=token8, fs=FaultyFs(kill_after=3))
    except SimulatedKill:
        killed = True
    rec8 = imha(p8, token8)
    check("process death mid-deletion: only BASLADI exists, NO SONUC, NO TAMAMLANDI anywhere",
          killed and len(rec8) == 1 and rec8[0]["asama"] == "BASLADI" and "genel_sonuc" not in rec8[0])
    check("the interrupted deletion is detected as an OPEN token", O.open_imha_tokens(p8.records_dir) == [token8])
    remaining_before = listing(p8.case_dir, p8.run_dir)
    ref = build_run("h2ref")  # aynı düzenin kesintisiz hâli: kıyas için dosya sayısı
    initial_count = len(listing(ref.case_dir, ref.run_dir))
    r8 = run_delete(p8, token=token8)
    rec8b = imha(p8, token8)
    check("the restart planned only what was LEFT (fewer files than the original layout) and finished: SONUC=TAMAMLANDI",
          len(remaining_before) < initial_count and r8.outcome == "TAMAMLANDI"
          and [r["asama"] for r in rec8b] == ["BASLADI", "BASLADI", "SONUC"] and rec8b[-1]["genel_sonuc"] == "TAMAMLANDI")
    check("after the restart no open token remains and the owned dirs are gone",
          O.open_imha_tokens(p8.records_dir) == [] and not p8.case_dir.exists() and not p8.run_dir.exists())
    check("the BASLADI of the restart lists FEWER planned items than the first one",
          sum(i["adet"] for i in rec8b[1]["kopya_turleri"]) < sum(i["adet"] for i in rec8b[0]["kopya_turleri"]))

    # ---------------------------------------------------------------- çökme penceresi: işaretsiz boş kök
    p10 = build_run("j")
    for p in listing(p10.case_dir):
        if not p.endswith(R.OWNER_MARKER_NAME):
            os.unlink(p)
    shutil.rmtree(p10.case_dir / "documents")
    shutil.rmtree(p10.case_dir / "timeline")
    shutil.rmtree(p10.case_dir / "deadlines")
    os.unlink(p10.case_dir / R.OWNER_MARKER_NAME)
    token10 = O.new_imha_token()
    O.write_imha_record(p10.records_dir, token10, O.build_imha_record(asama="BASLADI", kopya_turleri=[]))
    plan10 = C.build_deletion_plan(p10)
    check("WITHOUT an open deletion record an empty unmarked case dir is NOT adopted (ownership unproven)",
          not plan10.ok and plan10.refusal_code == "SAHIPLIK_ISARETI_YOK")
    r10 = run_delete(p10, token=token10)
    check("WITH an open BASLADI record the empty unmarked remnant of a crashed deletion is finished (TAMAMLANDI)",
          r10.outcome == "TAMAMLANDI" and not p10.case_dir.exists() and not p10.run_dir.exists(), f"{r10}")

    # ---------------------------------------------------------------- H-1: üyelik BİLDİRİMDEN gelir (desen yetmez)
    foreign_cases = (
        ("case", "documents/ihbarname_001/baska_muvekkil.pdf", "a PDF with a closed-type NAME that the run never registered"),
        ("case", "deadlines/buro_notu.json", "a .json work-name the run never registered"),
        ("case", "deadlines/eski_not.json.pending", "a .pending work-name the run never registered"),
        ("case", "deadlines/deadline.json.eski.bak", "a .bak work-name the run never registered"),
        ("case", "documents/ihbarname_001/extracted/baska.txt", "an extracted-text name the run never registered"),
        ("run", "pilot_hesap_raporu_eski_muvekkil.txt", "a pilot_hesap_raporu*.txt look-alike the run never registered"),
        ("run", "tmp/kisisel_not.docx", "a file dropped into tmp/ that the run never registered"),
        ("run", "tmp/alt/baska.dat", "a file dropped into a registered tmp subdir that the run never registered"),
    )
    for index, (root_name, rel, label) in enumerate(foreign_cases):
        pf = build_run(f"p1_{index}")
        base = pf.case_dir if root_name == "case" else pf.run_dir
        (base / rel).write_bytes(b"BUROYA AIT")
        pf_plan = C.build_deletion_plan(pf)
        before = listing(pf.case_dir, pf.run_dir)
        rf = run_delete(pf)
        recf = imha(pf, rf.token)
        check(f"H-1: {label} -> plan refused, counted as UNREGISTERED (not unclassified)",
              not pf_plan.ok and pf_plan.refusal_code == "SILME_BELIRSIZ_SAHIPLIK" and pf_plan.unregistered_count == 1
              and pf_plan.unclassified_count == 0, f"{pf_plan.unregistered_count}/{pf_plan.unclassified_count}")
        check(f"H-1: ... and NOTHING is deleted, REDDEDILDI as a single SONUC record, never TAMAMLANDI ({rel})",
              rf.outcome == "REDDEDILDI" and listing(pf.case_dir, pf.run_dir) == before and (base / rel).read_bytes() == b"BUROYA AIT"
              and [r["asama"] for r in recf] == ["SONUC"] and recf[0]["genel_sonuc"] == "REDDEDILDI")
    for root_name, rel in (("case", "deadlines/bos_dizin"), ("run", "tmp/yeni_klasor")):
        pd = build_run(f"p1d_{root_name}")
        (pd.case_dir if root_name == "case" else pd.run_dir).joinpath(rel).mkdir()
        before_dirs = sorted(os.path.join(r, d) for base in (pd.case_dir, pd.run_dir) for r, ds, _f in os.walk(base) for d in ds)
        rd = run_delete(pd)
        check(f"H-1: an UNREGISTERED empty directory ({rel}) is also unknown membership -> REDDEDILDI, directory kept",
              rd.outcome == "REDDEDILDI" and (pd.case_dir if root_name == "case" else pd.run_dir).joinpath(rel).is_dir()
              and before_dirs == sorted(os.path.join(r, d) for base in (pd.case_dir, pd.run_dir) for r, ds, _f in os.walk(base) for d in ds))
    pa = build_run("p1_infra")
    (pa.case_dir / "run_state.json").write_text("{}", encoding="utf-8")
    plan_a = C.build_deletion_plan(pa)
    check("H-1: the run-root infra NAMES are not infra inside the case dir (a stray run_state.json there is unknown membership)",
          not plan_a.ok and plan_a.unknown_count == 1)
    pm = build_run("p1_type")
    mm = manifest_of(pm)
    mm.entries = [e if e["rel"] != "case.json" else {**e, "tur": "PILOT_HESAP_RAPORU"} for e in mm.entries]
    save_manifest_of(pm, mm)
    check("H-1: a manifest entry whose TYPE disagrees with the closed-list type is not accepted (unknown)",
          not C.build_deletion_plan(pm).ok and C.build_deletion_plan(pm).unregistered_count == 1)
    pu = build_run("p1_uncl")
    (pu.case_dir / "documents" / "ihbarname_001" / "yabanci.docx").write_bytes(b"x")
    mu = manifest_of(pu)
    mu.entries.append({"root": "case", "rel": "documents/ihbarname_001/yabanci.docx", "tur": "CALISMA_DOSYALARI"})
    save_manifest_of(pu, mu)
    pu_plan = C.build_deletion_plan(pu)
    check("H-1: registration alone is not enough either - a name outside the closed type list stays unclassified (both gates must pass)",
          not pu_plan.ok and pu_plan.unclassified_count == 1 and pu_plan.unregistered_count == 0)

    # bildirim dosyası bozuk / yok
    pc = build_run("p1_corrupt")
    pc.manifest_path.write_text("{ bozuk json", encoding="utf-8")
    before = listing(pc.case_dir, pc.run_dir)
    rc = run_delete(pc)
    check("H-1: a CORRUPT manifest is never treated as empty or as 'delete everything': REDDEDILDI, nothing deleted",
          rc.outcome == "REDDEDILDI" and rc.refusal_code == "SILME_BELIRSIZ_SAHIPLIK" and listing(pc.case_dir, pc.run_dir) == before)
    pn = build_run("p1_missing")
    os.unlink(pn.manifest_path)
    before = listing(pn.case_dir, pn.run_dir)
    rn = run_delete(pn)
    check("H-1: a MISSING manifest while real content exists -> every content file is unregistered -> REDDEDILDI, nothing deleted",
          rn.outcome == "REDDEDILDI" and listing(pn.case_dir, pn.run_dir) == before)
    po = build_run("p1_infraonly")
    shutil.rmtree(po.case_dir)
    for entry in list(po.run_dir.iterdir()):
        if entry.name not in (R.OWNER_MARKER_NAME, "run_state.json", "run_manifest.json"):
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    os.unlink(po.manifest_path)
    R.write_imha_binding(po, token=R.imha_token_for_run(po.run_id), dosya_kodu="DKINFRA")
    plan_o = C.build_deletion_plan(po)
    ro = run_delete(po)
    check("H-1: with the case dir gone and ONLY run-infra files left (state, marker, binding) a missing manifest is fine -> TAMAMLANDI, run dir gone",
          plan_o.ok and plan_o.counts == {"CALISMA_DOSYALARI": 1} and ro.outcome == "TAMAMLANDI" and not po.run_dir.exists(), f"{plan_o.counts} {ro}")

    pk = build_run("p1_corrupt_infra")
    shutil.rmtree(pk.case_dir)
    for entry in list(pk.run_dir.iterdir()):
        if entry.name not in (R.OWNER_MARKER_NAME, "run_state.json", "run_manifest.json"):
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    pk.manifest_path.write_text("{ bozuk json", encoding="utf-8")
    rk = run_delete(pk)
    check("H-1: a CORRUPT manifest is refused on its OWN even when nothing but run-infra is left (not 'empty manifest, nothing to protect'): REDDEDILDI, run dir kept",
          rk.outcome == "REDDEDILDI" and rk.refusal_code == "SILME_BELIRSIZ_SAHIPLIK" and pk.run_dir.exists() and (pk.run_dir / "run_state.json").exists())

    # L-f: silme denemesi BAŞLAMIŞ jetonda "hiç başlamadı" anlamlı REDDEDILDI yazılmaz
    pq = build_run("lf")
    rq1 = run_delete(pq, fs=FaultyFs(deny="extractions/facts.json"))
    (pq.case_dir / "documents" / "ihbarname_001" / "baska_muvekkil.pdf").write_bytes(b"BURO")
    records_before_lf = imha(pq, rq1.token)
    rq2 = run_delete(pq, token=rq1.token)
    check("L-f: after a PARTIAL deletion (BASLADI + SONUC=KISMEN) a refused retry on the SAME token writes NO 'REDDEDILDI = never started' record: the KISMEN stays the last word",
          rq1.outcome == "KISMEN" and rq2.outcome == "REDDEDILDI" and rq2.token == rq1.token
          and imha(pq, rq1.token) == records_before_lf and imha(pq, rq1.token)[-1]["genel_sonuc"] == "KISMEN"
          and not any(r.get("genel_sonuc") == "REDDEDILDI" for r in imha(pq, rq1.token)))
    pq2 = build_run("lf2")
    tq2 = O.new_imha_token()
    O.write_imha_record(pq2.records_dir, tq2, O.build_imha_record(asama="BASLADI", kopya_turleri=[]))
    (pq2.case_dir / "deadlines" / "buro_notu.json").write_bytes(b"BURO")
    rq3 = run_delete(pq2, token=tq2)
    check("L-f: a refused retry on a token whose last record is an OPEN BASLADI leaves it open (no fake REDDEDILDI)",
          rq3.outcome == "REDDEDILDI" and O.open_imha_tokens(pq2.records_dir) == [tq2] and len(imha(pq2, tq2)) == 1)
    pq3 = build_run("lf3")
    (pq3.case_dir / "documents" / "ihbarname_001" / "baska.pdf").write_bytes(b"BURO")
    rq4 = run_delete(pq3)
    check("L-f: a FIRST refusal (no deletion ever started) is still recorded as the single SONUC=REDDEDILDI",
          rq4.outcome == "REDDEDILDI" and [r["asama"] for r in imha(pq3, rq4.token)] == ["SONUC"] and imha(pq3, rq4.token)[0]["genel_sonuc"] == "REDDEDILDI")

    # bağlantı/junction: bildirimde KAYITLI olsa bile bilinmeyen (M7)
    outside_m7 = TMP / "disarida_m7"
    outside_m7.mkdir()
    pl = build_run("m7")
    link_path = pl.case_dir / "documents" / "baglanti"
    if not make_junction(link_path, outside_m7):
        skip("registered junction inside the owned dir", "neither a junction nor a symlink could be created here. NOT EXECUTED, not a pass")
    else:
        ml = manifest_of(pl)
        ml.add_dir(root="case", rel="documents/baglanti")
        save_manifest_of(pl, ml)
        pl_plan = C.build_deletion_plan(pl)
        before = listing(pl.case_dir, pl.run_dir)
        rl = run_delete(pl)
        check("M7: a junction/link to an EMPTY outside dir, even REGISTERED in the manifest, is unknown membership (unclassified), not a directory to delete",
              not pl_plan.ok and pl_plan.unclassified_count == 1 and link_path not in pl_plan.dirs
              and not any(str(link_path) in str(f[0]) for f in pl_plan.files), f"{pl_plan.unclassified_count} {pl_plan.ok}")
        check("M7: ... deleting is REFUSED as a whole: nothing deleted, the outside dir and the link itself are untouched",
              rl.outcome == "REDDEDILDI" and outside_m7.is_dir() and listing(pl.case_dir, pl.run_dir) == before
              and (os.path.isjunction(str(link_path)) or os.path.islink(str(link_path))))
        os.rmdir(link_path)
    for kind_name in ("case_dir", "run_dir"):
        pr = build_run(f"m7_{kind_name}")
        real_dir = getattr(pr, kind_name)
        moved = real_dir.with_name(real_dir.name + "_gercek")
        os.rename(real_dir, moved)
        if not make_junction(real_dir, moved):
            os.rename(moved, real_dir)
            skip(f"owned ROOT replaced by a junction ({kind_name})", "no junction/symlink could be created here. NOT EXECUTED, not a pass")
            continue
        moved_before = listing(moved)
        rr = run_delete(pr)
        check(f"M7: an owned ROOT ({kind_name}) that is itself a junction/link is never followed: REDDEDILDI, the real directory is untouched",
              rr.outcome == "REDDEDILDI" and listing(moved) == moved_before)
        os.rmdir(real_dir)
        os.rename(moved, real_dir)

    # kök gerçek yolu PLAN anında donar (L-4)
    pz = build_run("l4")
    plan_z = C.build_deletion_plan(pz)
    inside_file = pz.case_dir / "case.json"
    check("L-4: the plan freezes each root's real path; a file under the unchanged root is inside", C._within_roots(inside_file, plan_z)
          and set(plan_z.roots_real) == {"case_dir", "run_dir"})
    swapped_orig = pz.case_dir.with_name(pz.case_dir.name + "_orijinal")
    decoy_root = TMP / "bambaska_kok"
    decoy_root.mkdir()
    (decoy_root / "case.json").write_text("{}", encoding="utf-8")
    os.rename(pz.case_dir, swapped_orig)
    if make_junction(pz.case_dir, decoy_root):
        check("L-4: if the root is swapped for a link AFTER planning, a path 'under' it is no longer inside the frozen root (nothing would be deleted)",
              not C._within_roots(pz.case_dir / "case.json", plan_z) and (decoy_root / "case.json").exists())
        os.rmdir(pz.case_dir)
    else:
        skip("root swapped for a link after planning", "no junction/symlink could be created here. NOT EXECUTED, not a pass")
    os.rename(swapped_orig, pz.case_dir)
    plan_z.roots_real["case_dir"] = Path(os.path.realpath(str(TMP / "baska")))
    check("L-4: a tampered frozen root rejects every path (the comparison uses the frozen value, not a fresh lookup)",
          not C._within_roots(inside_file, plan_z))

    # TAMAMLANDI: bildirimdeki HER öğenin yokluğu doğrulanır
    px = build_run("v1")
    plan_x = C.build_deletion_plan(px)
    check("verification: every manifest item (files and dirs of both roots) is part of the plan's verification list",
          len(plan_x.manifest_paths) == len(manifest_of(px).entries) + len(manifest_of(px).dirs))
    survivor = TMP / "bildirimde_kalan.txt"
    survivor.write_text("x", encoding="utf-8")
    plan_x.manifest_paths.append(survivor)
    check("verification: a manifest item that still exists is reported as a leftover (so TAMAMLANDI cannot be claimed)",
          survivor in C._manifest_leftovers(plan_x))
    survivor.unlink()
    rx = run_delete(px)
    check("verification: after a healthy deletion no manifest item remains", rx.outcome == "TAMAMLANDI" and C._manifest_leftovers(plan_x) == [])

    # ---------------------------------------------------------------- asla kök dışı
    p11 = build_run("k")
    sibling = p11.office_root / "baska_klasor"
    sibling.mkdir()
    (sibling / "dokunma.txt").write_text("x", encoding="utf-8")
    (p11.case_dir.parent / "baska_vaka").mkdir()
    (p11.case_dir.parent / "baska_vaka" / "case.json").write_text("{}", encoding="utf-8")
    run_delete(p11)
    check("siblings of the owned dirs (another case, another office folder, kayitlar/) are untouched",
          (sibling / "dokunma.txt").exists() and (p11.case_dir.parent / "baska_vaka" / "case.json").exists() and p11.records_dir.exists())
    check("the ORIGINAL PDF and the office's client file were never touched across ALL scenarios (hash/size/mtime + no write/delete audit event)",
          original_ok(), f"{SOURCE_EVENTS}")

    # ---------------------------------------------------------------- kayıtlarda içerik yok
    all_text = "".join(p.read_text(encoding="utf-8") for base in TMP.glob("ofis_*") for p in (base / "kayitlar").iterdir())
    check("no imha record of any scenario contains a path, a file name, a hash or a date other than the UTC timestamp",
          not any(s in all_text for s in ("tmpabc123", "ihbarname_001", "facts.json", "vaka", "\\", "/tmp", "asil_ihbarname", ".pdf", ORIGINAL_ID[0])))
    check("the cleanup module never reads the original's path (no such parameter exists on any public function)",
          all("source" not in str(sig) and "kaynak" not in str(sig) for sig in
              (C.build_deletion_plan.__code__.co_varnames, C.execute_deletion.__code__.co_varnames)))
finally:
    try:
        os.chmod(ORIGINAL, 0o666)
    except OSError:
        pass
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
