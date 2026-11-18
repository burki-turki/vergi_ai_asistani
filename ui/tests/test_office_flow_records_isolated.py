# ============================================================
# BÜRO MODELİ / T1 - ui/services/office_flow_records.py İZOLE TESTİ
# (ağsız, PostgreSQL'siz; yalnız geçici dizinler)
#
# Kapsam: kapalı hata kodu, O_EXCL tek-yazımlık yazıcı, sahiplik işaretli
# dizin, durum makinesi (UYUSMAZLIK -> UYUMLU YOK), bağımsız okuma kaydı
# doğrulaması, kimlik anlık görüntüsü + ek teyit, girdi manifesti
# (yalnız AD döner), "sonuç görüldü" işareti, koşu bildirimi (kaynak yol YOK).
# ============================================================

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
    print(f"--- test_office_flow_records_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import office_flow_records as R  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vergi_t1_records_"))


def raises_code(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except R.OfficeFlowError as error:
        return error.code
    return None


try:
    # ---------------------------------------------------------------- hata kodu
    error = R.OfficeFlowError("YETKI_YOK")
    check("closed error set: a known code is kept and str(error) is ONLY the code", error.code == "YETKI_YOK" and str(error) == "YETKI_YOK")
    error = R.OfficeFlowError("10.02.2026 C:\\gizli\\yol")
    check("closed error set: an unknown/free-text code collapses to BILINMEYEN_HATA (no content can ride on an error)",
          error.code == "BILINMEYEN_HATA" and "2026" not in str(error) and "gizli" not in str(error))
    check("every process step label is one of F0..F6", R.PROCESS_STEPS == ("F0", "F1", "F2", "F3", "F4", "F5", "F6"))

    # ---------------------------------------------------------------- O_EXCL
    target = TMP / "tek.json"
    R.write_new_file(target, b"ilk")
    code = raises_code(R.write_new_file, target, b"ikinci")
    check("write_new_file is O_EXCL: the second write is refused (DOSYA_MEVCUT) and the first bytes survive",
          code == "DOSYA_MEVCUT" and target.read_bytes() == b"ilk", str(code))
    check("write_new_file refuses an unwritable location with a closed code (YAZMA_BASARISIZ)",
          raises_code(R.write_new_file, TMP / "yok_dizin" / "x.json", b"x") == "YAZMA_BASARISIZ")
    replace_target = TMP / "calisma.json"
    R.atomic_replace_file(replace_target, b"v1")
    R.atomic_replace_file(replace_target, b"v2")
    check("atomic_replace_file replaces a working record atomically and leaves no side file",
          replace_target.read_bytes() == b"v2" and not (TMP / "calisma.json.tmp").exists())

    # ---------------------------------------------------------------- sahiplik işareti
    run_id = R.new_run_id()
    check("run ids are random 32-hex and never repeat", re.fullmatch(r"[0-9a-f]{32}", run_id) and run_id != R.new_run_id())
    owned = R.create_owned_dir(TMP / "vaka1", run_id=run_id, kind="case_dir")
    check("create_owned_dir makes a NEW dir with a valid ownership marker bound to (run_id, kind)",
          owned.is_dir() and R.read_owner_marker(owned, run_id=run_id, kind="case_dir"))
    check("the marker does NOT validate for another run id or another kind",
          not R.read_owner_marker(owned, run_id=R.new_run_id(), kind="case_dir")
          and not R.read_owner_marker(owned, run_id=run_id, kind="run_dir"))
    existing = TMP / "mevcut"
    existing.mkdir()
    (existing / "benim_dosyam.txt").write_text("dokunma", encoding="utf-8")
    code = raises_code(R.create_owned_dir, existing, run_id=run_id, kind="case_dir")
    check("create_owned_dir NEVER adopts an existing directory (DIZIN_MEVCUT) and does not touch its content",
          code == "DIZIN_MEVCUT" and sorted(p.name for p in existing.iterdir()) == ["benim_dosyam.txt"]
          and (existing / "benim_dosyam.txt").read_text(encoding="utf-8") == "dokunma", str(code))
    (owned / R.OWNER_MARKER_NAME).write_text("{bozuk", encoding="utf-8")
    check("a corrupted marker is not an ownership proof", not R.read_owner_marker(owned, run_id=run_id, kind="case_dir"))
    check("a missing marker is not an ownership proof", not R.read_owner_marker(TMP / "olmayan", run_id=run_id, kind="case_dir"))

    # ---------------------------------------------------------------- durum makinesi
    check("the legal happy path UYUMLU is reachable step by step ending in deletion",
          all(R.transition_allowed(a, b) for a, b in (
              ("HAZIRLANIYOR", "OKUMA_KAYITLI"), ("OKUMA_KAYITLI", "SISTEM_ZINCIRI"),
              ("SISTEM_ZINCIRI", "KARSILASTIRMA_YAPILDI"), ("KARSILASTIRMA_YAPILDI", "UYUMLU_RAPOR_KONTROLU"),
              ("UYUMLU_RAPOR_KONTROLU", "KONTROL_TAMAM"), ("KONTROL_TAMAM", "SILME_ONAYI_BEKLIYOR"),
              ("SILME_ONAYI_BEKLIYOR", "SILINIYOR"), ("SILINIYOR", "SILINDI"))))
    check("the UYUSMAZLIK path ends only via the lawyer's closing (INCELEME_KAPALI) and never reaches an UYUMLU state",
          R.transition_allowed("UYUSMAZLIK_INCELEME_ACIK", "INCELEME_KAPALI")
          and not any(R.transition_allowed(a, b) for a in ("UYUSMAZLIK_INCELEME_ACIK", "INCELEME_KAPALI")
                      for b in ("UYUMLU_RAPOR_KONTROLU", "KONTROL_TAMAM")))
    # Hiçbir durumdan UYUSMAZLIK_* durumlarına GERİ dönüş yok ve UYUSMAZLIK_* hiçbir yoldan KONTROL_TAMAM'a erişemez.
    reachable = {"UYUSMAZLIK_INCELEME_ACIK"}
    frontier = ["UYUSMAZLIK_INCELEME_ACIK"]
    while frontier:
        node = frontier.pop()
        for nxt in R.STATES:
            if R.transition_allowed(node, nxt) and nxt not in reachable:
                reachable.add(nxt)
                frontier.append(nxt)
    check("transitive closure: nothing reachable from UYUSMAZLIK_INCELEME_ACIK is UYUMLU_RAPOR_KONTROLU/KONTROL_TAMAM/GECERSIZ",
          not ({"UYUMLU_RAPOR_KONTROLU", "KONTROL_TAMAM", "GECERSIZ"} & reachable), str(sorted(reachable)))
    check("deletion can be entered only from the lawyer-triggered/inert states (never while UYUSMAZLIK review is open or before 'kontrol tamamlandı')",
          "UYUSMAZLIK_INCELEME_ACIK" not in R.DELETION_ENTRY_STATES and "UYUMLU_RAPOR_KONTROLU" not in R.DELETION_ENTRY_STATES
          and "KARSILASTIRMA_YAPILDI" not in R.DELETION_ENTRY_STATES
          and {"SILME_ONAYI_BEKLIYOR", "GECERSIZ", "DURDURULDU", "SILINIYOR", "SILME_YARIM", "SILME_REDDEDILDI"} == set(R.DELETION_ENTRY_STATES))
    check("L-6: a refused deletion plan has its OWN state SILME_REDDEDILDI (not SILME_YARIM); reachable from every deletion-entry state, retryable only into SILINIYOR",
          "SILME_REDDEDILDI" in R.STATES and all(R.transition_allowed(a, "SILME_REDDEDILDI") for a in (
              "SILME_ONAYI_BEKLIYOR", "GECERSIZ", "DURDURULDU", "SILINIYOR", "SILME_YARIM"))
          and [b for b in R.STATES if R.transition_allowed("SILME_REDDEDILDI", b)] == ["SILINIYOR"]
          and not R.transition_allowed("UYUSMAZLIK_INCELEME_ACIK", "SILME_REDDEDILDI")
          and not R.transition_allowed("UYUMLU_RAPOR_KONTROLU", "SILME_REDDEDILDI"))
    state = R.RunState.new(run_id=run_id, case_id="abc123", dosya_kodu="DK1")
    check("a fresh run starts HAZIRLANIYOR with no result", state.state == "HAZIRLANIYOR" and state["sonuc"] is None)
    check("an illegal transition is refused (DURUM_GECISI_GECERSIZ) and the state is unchanged",
          raises_code(state.set_state, "KONTROL_TAMAM") == "DURUM_GECISI_GECERSIZ" and state.state == "HAZIRLANIYOR")
    paths = R.build_run_paths(TMP / "ofis", TMP / "vakalar", "abc123", run_id)
    (TMP / "ofis").mkdir()
    R.ensure_office_infra(TMP / "ofis")
    R.create_owned_dir(paths.run_dir, run_id=run_id, kind="run_dir")
    R.create_run_state_file(paths, state)
    state.set_state("OKUMA_KAYITLI")
    R.save_run_state(paths, state)
    loaded = R.load_run_state(paths.run_dir)
    check("run state persists atomically and reloads with its history", loaded.state == "OKUMA_KAYITLI" and loaded["gecmis"] == ["HAZIRLANIYOR", "OKUMA_KAYITLI"])
    check("create_run_state_file is O_EXCL (a second creation is refused)", raises_code(R.create_run_state_file, paths, state) == "DOSYA_MEVCUT")
    check("case id / dosya kodu syntax is enforced",
          raises_code(R.validate_case_id, "BÜYÜK") == "KOD_GECERSIZ" and raises_code(R.validate_case_id, "a") == "KOD_GECERSIZ"
          and R.validate_case_id("abc-123_x") == "abc-123_x" and raises_code(R.validate_dosya_kodu, "../x") == "KOD_GECERSIZ")

    # ---------------------------------------------------------------- koşu bildirimi
    manifest = R.RunManifest()
    manifest.add(root="case", rel="documents\\d\\x.pdf", tur="CALISMA_DIZINI_BELGE_KOPYASI")
    manifest.add(root="run", rel="okuma_kaydi.json", tur="CALISMA_DOSYALARI")
    manifest.add(root="run", rel="okuma_kaydi.json", tur="CALISMA_DOSYALARI")
    payload = json.loads(manifest.to_bytes().decode("utf-8"))
    check("the run manifest lists only the tool's own files (deduplicated, posix paths) and the source is a FLAG, never a path",
          len(payload["entries"]) == 2 and payload["kaynak_salt_okunur"] is True
          and all("\\" not in e["rel"] for e in payload["entries"]) and "kaynak" not in manifest.to_bytes().decode("utf-8").replace("kaynak_salt_okunur", ""))
    check("the manifest rejects an unknown root or an unknown copy type",
          raises_code(manifest.add, root="x", rel="a", tur="CALISMA_DOSYALARI") == "KAYIT_SEMASI_GECERSIZ"
          and raises_code(manifest.add, root="case", rel="a", tur="BELGE_ARSIVI") == "KAYIT_SEMASI_GECERSIZ")
    manifest.add_dir(root="case", rel="documents/d")
    manifest.add_dir(root="case", rel="documents\\d")
    R.save_manifest(paths, manifest)
    loaded_manifest = R.RunManifest.load(paths.manifest_path)
    check("the manifest round-trips from disk", [e["rel"] for e in loaded_manifest.entries] == ["documents/d/x.pdf", "okuma_kaydi.json"])
    check("H-1: the manifest also lists the tool's own DIRECTORIES (deduplicated) and exposes membership lookups per root",
          loaded_manifest.dirs == [{"root": "case", "rel": "documents/d"}] and loaded_manifest.dir_rels("case") == {"documents/d"}
          and loaded_manifest.file_types("run") == {"okuma_kaydi.json": "CALISMA_DOSYALARI"}
          and loaded_manifest.file_types("case") == {"documents/d/x.pdf": "CALISMA_DIZINI_BELGE_KOPYASI"})
    check("H-1: unsafe manifest paths are refused (absolute, drive, parent traversal, empty part, non-string)",
          all(raises_code(manifest.add, root="case", rel=bad, tur="CALISMA_DOSYALARI") == "KAYIT_SEMASI_GECERSIZ"
              for bad in ("/etc/x", "C:/x.json", "../x.json", "a/../x.json", "a//x.json", "", "./x.json", None))
          and raises_code(manifest.add_dir, root="run", rel="..") == "KAYIT_SEMASI_GECERSIZ")
    bad_manifest = TMP / "bad_manifest.json"
    for label, payload in (("entries not a list", {"kaynak_salt_okunur": True, "entries": "x"}),
                           ("entry missing a key", {"kaynak_salt_okunur": True, "entries": [{"root": "case"}]}),
                           ("entry with a bad path", {"kaynak_salt_okunur": True, "entries": [{"root": "case", "rel": "../x", "tur": "CALISMA_DOSYALARI"}]}),
                           ("dirs not a list", {"kaynak_salt_okunur": True, "entries": [], "dirs": 3}),
                           ("source flag missing", {"entries": []})):
        bad_manifest.write_text(json.dumps(payload), encoding="utf-8")
        check(f"H-1: a corrupt manifest is refused at load ({label}) - never silently treated as empty",
              raises_code(R.RunManifest.load, bad_manifest) == "KAYIT_SEMASI_GECERSIZ")
    bad_manifest.write_text("{ not json", encoding="utf-8")
    check("H-1: an unparsable manifest file is refused at load", raises_code(R.RunManifest.load, bad_manifest) == "DOSYA_ISLEMI_BASARISIZ")
    bad_manifest.write_text(json.dumps({"kaynak_salt_okunur": True, "entries": []}), encoding="utf-8")
    check("H-1: a legacy manifest without a dirs list still loads (empty dirs)", R.RunManifest.load(bad_manifest).dirs == [])

    # ---------------------------------------------------------------- tarih/okuma kaydı
    check("date input accepts GG.AA.YYYY, GG/AA/YYYY and ISO and returns ISO",
          R.parse_date_input("10.02.2026") == "2026-02-10" and R.parse_date_input("10/02/2026") == "2026-02-10"
          and R.parse_date_input("2026-02-10") == "2026-02-10")
    check("date input rejects impossible/ambiguous values (31.02, 1-digit parts, other separators, out-of-range years)",
          all(raises_code(R.parse_date_input, v) == "OKUMA_KAYDI_GECERSIZ"
              for v in ("31.02.2026", "1.2.2026", "2026.02.10", "10-02-2026", "", "10.02.1800", "abc")))
    check("stopping-event ref: opaque tokens are accepted; dates, 6+ digit runs, empty and free punctuation are refused",
          R.validate_stopping_ref("BEYAN-T1") == "BEYAN-T1"
          and all(raises_code(R.validate_stopping_ref, v) == "OKUMA_KAYDI_GECERSIZ"
                  for v in ("10.02.2026", "123456", "", "a/b", "x" * 65)))
    identity = R.IdentitySnapshot(user_id=7, display_name="Av. Örnek", windows_user="u", machine_name="m", db_time="2026-11-18T10:00:00+00:00")
    good = dict(tebligat_tarihi="10.02.2026", sayfa=1, kor_son_gun="12.03.2026", adli_tatil="no",
                stopping_status="none", stopping_ref="BEYAN-T1", identity=identity)
    record = R.build_reading_record(**good)
    check("the reading record carries ONLY date, page, blind last day, two declarations, the stopping ref and the identity snapshot",
          set(record) == {"kayit_surumu", "kayit_turu", "tebligat_tarihi", "sayfa", "kor_son_gun", "adli_tatil",
                          "stopping_event_status", "stopping_event_ref", "kimlik"}
          and "text_excerpt" not in json.dumps(record) and record["tebligat_tarihi"] == "2026-02-10")
    for label, mutation, expected in (
        ("page must be a positive int", {"sayfa": "1"}, "OKUMA_KAYDI_GECERSIZ"),
        ("page 0 is refused", {"sayfa": 0}, "OKUMA_KAYDI_GECERSIZ"),
        ("judicial recess must be yes/no/unknown", {"adli_tatil": "belki"}, "OKUMA_KAYDI_GECERSIZ"),
        ("stopping status must be none/present/unknown", {"stopping_status": "yok"}, "OKUMA_KAYDI_GECERSIZ"),
        ("stopping 'none' REQUIRES an opaque ref", {"stopping_ref": None}, "OKUMA_KAYDI_GECERSIZ"),
        ("the blind last day must be a real date", {"kor_son_gun": "31.04.2026"}, "OKUMA_KAYDI_GECERSIZ"),
    ):
        check(f"reading record validation: {label}", raises_code(R.build_reading_record, **{**good, **mutation}) == expected)
    present = R.build_reading_record(**{**good, "stopping_status": "present", "stopping_ref": None})
    check("stopping 'present'/'unknown' may omit the ref", present["stopping_event_ref"] is None)
    run_dir_paths = R.build_run_paths(TMP / "ofis", TMP / "vakalar", "abc123", run_id)
    sha = R.write_reading_record(run_dir_paths, record)
    check("the reading record is written once (O_EXCL), its sha is the file's sha, a second write is refused",
          R.sha256_hex(run_dir_paths.reading_path.read_bytes()) == sha and raises_code(R.write_reading_record, run_dir_paths, record) == "DOSYA_MEVCUT")
    check("the reading record loads back unchanged", R.load_reading_record(run_dir_paths) == record)
    check("L-1: with the run-state sha the reading record loads (verified); a mismatching sha is OKUMA_KAYDI_GECERSIZ",
          R.load_reading_record(run_dir_paths, expected_sha=sha) == record
          and raises_code(R.load_reading_record, run_dir_paths, expected_sha="0" * 64) == "OKUMA_KAYDI_GECERSIZ")
    reading_bytes = run_dir_paths.reading_path.read_bytes()
    run_dir_paths.reading_path.write_bytes(reading_bytes.replace(b"2026-02-10", b"2026-02-11"))
    check("L-1: a reading record edited AFTER it was recorded fails verification (same size, different bytes)",
          raises_code(R.load_reading_record, run_dir_paths, expected_sha=sha) == "OKUMA_KAYDI_GECERSIZ")
    run_dir_paths.reading_path.write_bytes(reading_bytes)
    check("L-1: restoring the exact bytes verifies again", R.load_reading_record(run_dir_paths, expected_sha=sha) == record)

    # ---------------------------------------------------------------- imha jetonu bağı (H-2)
    bind_run = R.new_run_id()
    bind_office = TMP / "ofis_bag"
    bind_office.mkdir()
    R.ensure_office_infra(bind_office)
    bind_paths = R.build_run_paths(bind_office, TMP / "vakalar_bag", "vakabag", bind_run)
    R.create_owned_dir(bind_paths.run_dir, run_id=bind_run, kind="run_dir")
    check("H-2: without a binding file the run has NO token binding (None, never another run's)",
          R.read_imha_binding(bind_paths.run_dir, run_id=bind_run) is None)
    bind_token = R.imha_token_for_run(bind_run)
    check("L-d: the run's token is DERIVED from its run id (deterministic, 16 hex, different for a different run)",
          bind_token == R.imha_token_for_run(bind_run) and len(bind_token) == 16 and bind_token != R.imha_token_for_run(R.new_run_id()))
    check("L-d: a binding whose token is NOT this run's derived token is refused at write time (another run's series)",
          raises_code(R.write_imha_binding, bind_paths, token="ab" * 8, dosya_kodu="DKBAG") == "KAYIT_SEMASI_GECERSIZ")
    R.write_imha_binding(bind_paths, token=bind_token, dosya_kodu="DKBAG")
    binding = R.read_imha_binding(bind_paths.run_dir, run_id=bind_run)
    check("H-2: the binding carries ONLY run id, token, case id and file code - written once (O_EXCL), read back for the SAME run",
          binding == {"kayit_surumu": 1, "kos": bind_run, "imha_token": bind_token, "case_id": "vakabag", "dosya_kodu": "DKBAG"}
          and raises_code(R.write_imha_binding, bind_paths, token=bind_token, dosya_kodu="DKBAG") == "DOSYA_MEVCUT")
    check("H-2: a binding is NEVER returned for a different run id (token stays bound to its own run)",
          R.read_imha_binding(bind_paths.run_dir, run_id=R.new_run_id()) is None)
    check("H-2: an invalid token or file code is refused when writing a binding",
          raises_code(R.write_imha_binding, bind_paths, token="XYZ", dosya_kodu="DKBAG") == "KAYIT_SEMASI_GECERSIZ"
          and raises_code(R.write_imha_binding, bind_paths, token=bind_token, dosya_kodu="../x") == "KOD_GECERSIZ")
    binding_file = bind_paths.run_dir / R.IMHA_BINDING_NAME
    for label, payload in (("corrupt JSON", b"{ nope"), ("token not 16 hex", json.dumps({**binding, "imha_token": "zz"}).encode()),
                           ("bad case id", json.dumps({**binding, "case_id": "../x"}).encode()),
                           ("wrong schema version", json.dumps({**binding, "kayit_surumu": 9}).encode()),
                           ("L-d tampered token = ANOTHER run's series (well-formed 16 hex, not this run's)", json.dumps({**binding, "imha_token": "ab" * 8}).encode())):
        binding_file.write_bytes(payload)
        check(f"H-2: a damaged binding is treated as NO binding ({label})", R.read_imha_binding(bind_paths.run_dir, run_id=bind_run) is None)
    check("H-2: run_state_present distinguishes ABSENT from CORRUPT (a corrupt file is 'present' and load fails)",
          not R.run_state_present(bind_paths.run_dir)
          and (bind_paths.run_dir / R.RUN_STATE_NAME).write_text("{ bozuk", encoding="utf-8") is not None
          and R.run_state_present(bind_paths.run_dir)
          and raises_code(R.load_run_state, bind_paths.run_dir) == "DOSYA_ISLEMI_BASARISIZ")
    (bind_paths.run_dir / R.RUN_STATE_NAME).write_text(json.dumps({"durum": "BILINMEYEN"}), encoding="utf-8")
    check("H-2: a state file with an unknown state is a schema error, not a silent default", raises_code(R.load_run_state, bind_paths.run_dir) == "KAYIT_SEMASI_GECERSIZ")
    # L-h: tam şema doğrulaması
    good_state = R.RunState.new(run_id=bind_run, case_id="vakabag", dosya_kodu="DKBAG").data
    state_file = bind_paths.run_dir / R.RUN_STATE_NAME
    state_file.write_text(json.dumps({**good_state, "okuma_sha": "x", "sistem_ozeti": None}), encoding="utf-8")
    check("L-h: a complete state (plus the flow's extra fields) loads", R.load_run_state(bind_paths.run_dir).state == "HAZIRLANIYOR")
    for label, mutate in (
        ("missing gecmis", lambda d: d.pop("gecmis")), ("gecmis not a list", lambda d: d.update(gecmis="HAZIRLANIYOR")),
        ("gecmis empty", lambda d: d.update(gecmis=[])), ("gecmis with an unknown state", lambda d: d.update(gecmis=["X", "HAZIRLANIYOR"])),
        ("gecmis last != durum", lambda d: d.update(gecmis=["OKUMA_KAYITLI"])), ("missing case_id", lambda d: d.pop("case_id")),
        ("case_id traversal", lambda d: d.update(case_id="../x")), ("bad dosya_kodu", lambda d: d.update(dosya_kodu="a b")),
        ("rapor_gecersiz not bool", lambda d: d.update(rapor_gecersiz=1)), ("imha_token malformed", lambda d: d.update(imha_token="zz")),
        ("imha_token not str", lambda d: d.update(imha_token=5)), ("kos not str", lambda d: d.update(kos=7)),
        ("schema version wrong", lambda d: d.update(kayit_surumu=2)), ("sonuc wrong type", lambda d: d.update(sonuc=3)),
        ("missing durdu_nedeni", lambda d: d.pop("durdu_nedeni")), ("not a dict", None),
    ):
        broken = json.loads(json.dumps(good_state))
        if mutate is None:
            state_file.write_text("[1, 2]", encoding="utf-8")
        else:
            mutate(broken)
            state_file.write_text(json.dumps(broken), encoding="utf-8")
        check(f"L-h: an incomplete/mistyped state is KAYIT_SEMASI_GECERSIZ at LOAD time ({label})",
              raises_code(R.load_run_state, bind_paths.run_dir) == "KAYIT_SEMASI_GECERSIZ")

    # ---------------------------------------------------------------- kimlik
    check("full-name confirmation: exact match after NFC + whitespace squeeze",
          R.confirm_full_name("  Av.   Örnek  ", "Av. Örnek") and R.confirm_full_name("Av. Örnek", "Av. Örnek"))
    check("full-name confirmation: other name, empty, different case or substring all fail",
          not R.confirm_full_name("Av. Başka", "Av. Örnek") and not R.confirm_full_name("", "Av. Örnek")
          and not R.confirm_full_name("av. örnek", "Av. Örnek") and not R.confirm_full_name("Av.", "Av. Örnek"))

    class _Cur:
        def __init__(self, conn):
            self.conn = conn
            self._last = None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self._last = sql

        def fetchone(self):
            if "FROM iam.users" in self._last:
                return self.conn.user_row
            import datetime
            return (datetime.datetime(2026, 11, 18, 10, 0, 0, tzinfo=datetime.timezone.utc),)

    class _Conn:
        def __init__(self, user_row):
            self.user_row = user_row

        def cursor(self):
            return _Cur(self)

    class _Assign:
        def __init__(self, role):
            self.role = role

    class _Repo:
        def __init__(self, assignment):
            self.assignment = assignment

        def get_active_case_assignment(self, user_id, case_id):
            return self.assignment

    snap = R.capture_identity(_Conn(("Av. Örnek", False)), 7, "abc123", repository=_Repo(_Assign("lawyer")))
    check("identity snapshot: active user + assigned lawyer -> user id, registered name, OS user, machine, DB time",
          snap.user_id == 7 and snap.display_name == "Av. Örnek" and snap.windows_user and snap.machine_name and "2026-11-18" in snap.db_time)
    check("identity: a missing user is refused (YETKI_YOK)", raises_code(R.capture_identity, _Conn(None), 7, "abc123", repository=_Repo(_Assign("lawyer"))) == "YETKI_YOK")
    check("identity: a disabled user is refused (YETKI_YOK)", raises_code(R.capture_identity, _Conn(("x", True)), 7, "abc123", repository=_Repo(_Assign("lawyer"))) == "YETKI_YOK")
    check("identity: an unassigned user is refused (YETKI_YOK)", raises_code(R.capture_identity, _Conn(("x", False)), 7, "abc123", repository=_Repo(None)) == "YETKI_YOK")
    check("identity: a non-lawyer assignment role is refused (YETKI_YOK)", raises_code(R.capture_identity, _Conn(("x", False)), 7, "abc123", repository=_Repo(_Assign("analyst"))) == "YETKI_YOK")

    # ---------------------------------------------------------------- girdi manifesti
    case_dir = TMP / "vakam"
    (case_dir / "documents" / "doc1" / "extracted").mkdir(parents=True)
    (case_dir / "documents" / "doc1" / "extractions").mkdir()
    (case_dir / "timeline").mkdir()
    (case_dir / "case.json").write_text("{}", encoding="utf-8")
    (case_dir / "documents" / "doc1" / "document.json").write_text("{}", encoding="utf-8")
    (case_dir / "documents" / "doc1" / "extracted" / "doc1.txt").write_text("metin", encoding="utf-8")
    (case_dir / "documents" / "doc1" / "extractions" / "facts.json").write_text("{\"v\":1}", encoding="utf-8")
    (case_dir / "timeline" / "timeline.json").write_text("{\"t\":1}", encoding="utf-8")
    glob_file = TMP / "global.json"
    glob_file.write_text("g1", encoding="utf-8")
    m1 = R.compute_input_manifest(case_dir, {"ruleset": glob_file})
    check("input manifest covers case.json, document.json, extracted text, canonical facts, canonical timeline and the global inputs",
          set(m1) == {"case.json", "documents/doc1/document.json", "documents/doc1/extractions/facts.json",
                      "documents/doc1/extracted/doc1.txt", "timeline/timeline.json", "global:ruleset"}
          and all(v is not None for v in m1.values()))
    check("input manifest is deterministic", R.compute_input_manifest(case_dir, {"ruleset": glob_file}) == m1
          and R.manifest_digest(m1) == R.manifest_digest(dict(m1)))
    check("an unchanged input yields NO changed names", R.changed_inputs(m1, R.compute_input_manifest(case_dir, {"ruleset": glob_file})) == [])
    (case_dir / "documents" / "doc1" / "extractions" / "facts.json").write_text("{\"v\":2}", encoding="utf-8")
    changed = R.changed_inputs(m1, R.compute_input_manifest(case_dir, {"ruleset": glob_file}))
    check("a changed verified input is reported BY NAME ONLY (never a hash)",
          changed == ["documents/doc1/extractions/facts.json"] and not any(re.search(r"[0-9a-f]{32}", c) for c in changed))
    glob_file.write_text("g2", encoding="utf-8")
    check("a changed GLOBAL input (ruleset/provisions/holiday calendar) is detected too",
          "global:ruleset" in R.changed_inputs(m1, R.compute_input_manifest(case_dir, {"ruleset": glob_file})))
    (case_dir / "timeline" / "timeline.json").unlink()
    check("a deleted input is a change (None != hash)", "timeline/timeline.json" in R.changed_inputs(m1, R.compute_input_manifest(case_dir, {"ruleset": glob_file})))
    (case_dir / "deadlines").mkdir()
    fp0 = R.deadline_fingerprint(case_dir)
    (case_dir / "deadlines" / "deadline_x_v1.json.pending").write_text("p", encoding="utf-8")
    fp1 = R.deadline_fingerprint(case_dir)
    (case_dir / "deadlines" / "deadline.json").write_text("c", encoding="utf-8")
    fp2 = R.deadline_fingerprint(case_dir)
    check("the deadline fingerprint tracks pending and canonical separately", fp0 == {"pending": None, "canonical": None}
          and fp1["pending"] and fp1["canonical"] is None and fp2["canonical"] and fp2 != fp1)

    # ---------------------------------------------------------------- sonuç görüldü işareti
    history = TMP / "gecmis"
    history.mkdir()
    check("a file code never seen before is ILK_KONTROL", R.determine_kontrol_turu(history, "DK1") == "ILK_KONTROL")
    R.mark_result_seen(history, "DK1")
    R.mark_result_seen(history, "DK1")
    check("after the system result was seen the SAME file code is YENIDEN_KONTROL; another code is still ILK_KONTROL",
          R.determine_kontrol_turu(history, "DK1") == "YENIDEN_KONTROL" and R.determine_kontrol_turu(history, "DK2") == "ILK_KONTROL")
    files = list(history.iterdir())
    check("the marker is content-free, named by a digest (NOT the file code) and idempotent (one file)",
          len(files) == 1 and "DK1" not in files[0].name and json.loads(files[0].read_bytes()) == {"kayit_surumu": 1, "sonuc_gorulmus": True})
    check("an invalid file code is refused for the marker store", raises_code(R.mark_result_seen, history, "../x") == "KOD_GECERSIZ")

    # ---------------------------------------------------------------- koşu yolları
    ensure_root = TMP / "ofis2"
    ensure_root.mkdir()
    R.ensure_office_infra(ensure_root)
    R.ensure_office_infra(ensure_root)
    check("office infra (runs/, kayitlar/, dosya_gecmisi/) is created idempotently", sorted(p.name for p in ensure_root.iterdir()) == ["dosya_gecmisi", "kayitlar", "runs"])
    rp = R.build_run_paths(ensure_root, TMP / "vakalar", "abc123", "r" * 32)
    check("run paths put the case dir under the case root and the run dir/tmp under office-root/runs",
          rp.case_dir == TMP / "vakalar" / "abc123" and rp.run_dir == ensure_root / "runs" / ("r" * 32)
          and rp.tmp_dir == rp.run_dir / "tmp" and rp.records_dir == ensure_root / "kayitlar")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
