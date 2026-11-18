# ============================================================
# BÜRO MODELİ / T1 - ui/services/office_flow_preflight.py İZOLE TESTİ
#
# "Dış YZ çağrısı REDDEDİLİR" (ayrı test) ve "TEMP yönlendirmesi":
#   - `anthropic`/`openai` import EDİLEBİLİR ise F0 reddeder (gerçek bir
#     zehirli `anthropic.py` modülüyle; sys.modules=None işaretiyle; probe
#     enjeksiyonuyla)
#   - ANTHROPIC_*/OPENAI_* ortam değişkeni varsa reddeder
#   - DSN loopback, office-root geçerli/repo dışı, aynı birim, sistem sürücüsü
#   - TMP/TEMP/TMPDIR + tempfile koşu dizinine yönlendirilir ve GERİ alınır
# ============================================================

import importlib
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


def summarize_and_exit():
    print(f"--- test_office_flow_preflight_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import office_flow_preflight as P  # noqa: E402
from ui.services import office_flow_records as R  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vergi_t1_preflight_"))


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except R.OfficeFlowError as error:
        return error.code
    return None


try:
    # ---------------------------------------------------------------- dış YZ paketi
    check("the default probe says `anthropic` is NOT importable in this runtime (the office package has no wheel)",
          P.default_import_probe("anthropic") is False)
    check("the default probe is False for any non-existent package", P.default_import_probe("kesinlikle_yok_paket_xyz") is False)
    check("an injected probe that reports `anthropic` importable -> DIS_YZ_PAKETI_VAR",
          P.check_external_ai_absent(import_probe=lambda n: n == "anthropic", env={}) == ["DIS_YZ_PAKETI_VAR"])
    check("an injected probe that reports `openai` importable -> DIS_YZ_PAKETI_VAR",
          P.check_external_ai_absent(import_probe=lambda n: n == "openai", env={}) == ["DIS_YZ_PAKETI_VAR"])
    check("with neither package importable and a clean env the check passes", P.check_external_ai_absent(import_probe=lambda n: False, env={"PATH": "x"}) == [])

    poison_dir = TMP / "zehirli"
    poison_dir.mkdir()
    (poison_dir / "anthropic.py").write_text("raise RuntimeError('POISON: an external AI client must never be imported')\n", encoding="utf-8")
    sys.path.insert(0, str(poison_dir))
    importlib.invalidate_caches()
    sys.modules.pop("anthropic", None)
    try:
        poisoned_detected = P.default_import_probe("anthropic")
        still_not_imported = "anthropic" not in sys.modules
    finally:
        sys.path.remove(str(poison_dir))
        importlib.invalidate_caches()
    check("a poisoned `anthropic` on sys.path is DETECTED by the probe without ever being imported (find_spec only)",
          poisoned_detected is True and still_not_imported)
    sys.path.insert(0, str(poison_dir))
    importlib.invalidate_caches()
    try:
        result = P.run_preflight(office_root=TMP, case_root=TMP, repo_root=REPO_ROOT / "yok", dsn="", env={}, allow_system_drive=True)
    finally:
        sys.path.remove(str(poison_dir))
        importlib.invalidate_caches()
    check("run_preflight REFUSES (DIS_YZ_PAKETI_VAR) when the poisoned package is on the path", "DIS_YZ_PAKETI_VAR" in result.failed and not result.ok)
    sys.modules["anthropic"] = None
    try:
        none_marker = P.default_import_probe("anthropic")
    finally:
        sys.modules.pop("anthropic", None)
    check("a sys.modules `None` marker (blocked import) counts as NOT importable", none_marker is False)
    sys.modules["anthropic"] = object()
    try:
        loaded_marker = P.default_import_probe("anthropic")
    finally:
        sys.modules.pop("anthropic", None)
    check("an already-loaded `anthropic` module counts as importable (refused)", loaded_marker is True)
    check("ANTHROPIC_API_KEY in the environment -> DIS_YZ_ORTAM_ANAHTARI_VAR",
          P.check_external_ai_absent(import_probe=lambda n: False, env={"ANTHROPIC_API_KEY": "x"}) == ["DIS_YZ_ORTAM_ANAHTARI_VAR"])
    check("a lower-case anthropic_* variable and an OPENAI_* variable are caught too",
          P.check_external_ai_absent(import_probe=lambda n: False, env={"anthropic_base_url": "x"}) == ["DIS_YZ_ORTAM_ANAHTARI_VAR"]
          and P.check_external_ai_absent(import_probe=lambda n: False, env={"OPENAI_API_KEY": "x"}) == ["DIS_YZ_ORTAM_ANAHTARI_VAR"])
    check("unrelated variables (even containing the word) are not a false positive",
          P.check_external_ai_absent(import_probe=lambda n: False, env={"MY_ANTHROPIC_NOTE": "x", "PATH": "y"}) == [])
    both = P.check_external_ai_absent(import_probe=lambda n: True, env={"ANTHROPIC_API_KEY": "x"})
    check("both failures are reported together", both == ["DIS_YZ_PAKETI_VAR", "DIS_YZ_ORTAM_ANAHTARI_VAR"])

    # ---------------------------------------------------------------- DSN
    for index, (dsn, expected_ok) in enumerate((
        ("postgresql://u:p@127.0.0.1:5432/db", True), ("postgresql://u:p@localhost/db", True),
        ("postgresql://u:p@[::1]:5432/db", True), ("postgresql:///db", True), ("dbname=x", True),
        ("host=127.0.0.1 dbname=x", True), ("host='localhost' dbname=x", True), ("host=/var/run/postgresql dbname=x", True),
        ("postgresql://u:p@db.example.com:5432/db", False), ("postgresql://u:p@10.0.0.5/db", False),
        ("host=db.example.com dbname=x", False), ("postgresql://u:pa@ss@evil.example.com/db", False),
    ), start=1):
        # Etiket DSN metnini TAŞIMAZ (runner'ın sır taraması `kullanıcı:parola@` biçimini yakalar).
        check(f"DSN loopback check #{index}: the host is {'loopback/local' if expected_ok else 'remote'} -> {'ok' if expected_ok else 'refused'}",
              (P.check_dsn_loopback(dsn, env={}) == []) == expected_ok, f"host={P.dsn_host(dsn, {})}")
    check("with no host in the DSN, PGHOST decides: remote refused, loopback ok",
          P.check_dsn_loopback("dbname=x", env={"PGHOST": "db.example.com"}) == ["DSN_LOOPBACK_DEGIL"]
          and P.check_dsn_loopback("dbname=x", env={"PGHOST": "127.0.0.1"}) == [])

    # ---------------------------------------------------------------- office-root
    check("office-root: an existing absolute dir outside the repo is accepted", P.check_office_root(TMP, repo_root=REPO_ROOT) == [])
    check("office-root: a relative path is refused", P.check_office_root("goreli/yol", repo_root=REPO_ROOT) == ["OFFICE_ROOT_GECERSIZ"])
    check("office-root: a non-existent dir is refused", P.check_office_root(TMP / "yok", repo_root=REPO_ROOT) == ["OFFICE_ROOT_GECERSIZ"])
    check("office-root: a dir INSIDE the repository is refused (records must not live in the repo tree)",
          P.check_office_root(REPO_ROOT / "data", repo_root=REPO_ROOT) == ["OFFICE_ROOT_GECERSIZ"])
    a_file = TMP / "dosya.txt"
    a_file.write_text("x", encoding="utf-8")
    check("office-root: a plain file is refused", P.check_office_root(a_file, repo_root=REPO_ROOT) == ["OFFICE_ROOT_GECERSIZ"])

    # ---------------------------------------------------------------- aynı birim / sistem sürücüsü
    check("same volume: equal device ids pass", P.check_same_volume(TMP, TMP, volume_probe=lambda p: 7) == [])
    check("same volume: identical roots with equal ids pass and differing ids by path fail",
          P.check_same_volume("a", "b", volume_probe=lambda p: 7) == []
          and P.check_same_volume("a", "b", volume_probe=lambda p: 7 if p == "a" else 8) == ["BIRIM_FARKLI"])
    ids = iter([1, 2])
    check("same volume: the office-root and the case root on DIFFERENT volumes -> BIRIM_FARKLI",
          P.check_same_volume("a", "b", volume_probe=lambda p: next(ids)) == ["BIRIM_FARKLI"])
    check("same volume: a probe error fails closed", P.check_same_volume("a", "b", volume_probe=lambda p: (_ for _ in ()).throw(OSError())) == ["BIRIM_FARKLI"])
    real_same = P.check_same_volume(TMP, TMP)
    check("same volume: the real st_dev probe works on this machine", real_same == [])
    check("system drive: office-root ON the system drive -> SISTEM_SURUCUSU",
          P.check_not_system_drive("E:\\ofis", system_drive="E:", drive_of=lambda p: "E:") == ["SISTEM_SURUCUSU"])
    check("system drive: a different drive passes", P.check_not_system_drive("D:\\ofis", system_drive="C:", drive_of=lambda p: "D:") == [])

    # ---------------------------------------------------------------- toplu
    res = P.run_preflight(office_root=TMP, case_root=TMP, repo_root=REPO_ROOT, dsn="postgresql://u:p@db.example.com/x", env={"ANTHROPIC_API_KEY": "k"},
                          import_probe=lambda n: n == "anthropic", volume_probe=lambda p: 1, system_drive="Z:", drive_of=lambda p: "Z:")
    check("run_preflight collects EVERY failure (does not stop at the first)",
          set(res.failed) == {"DIS_YZ_PAKETI_VAR", "DIS_YZ_ORTAM_ANAHTARI_VAR", "DSN_LOOPBACK_DEGIL", "SISTEM_SURUCUSU"}, str(res.failed))
    check("raise_if_failed raises the FIRST failure code", code_of(P.raise_if_failed, res) == "DIS_YZ_PAKETI_VAR")
    clean = P.run_preflight(office_root=TMP, case_root=TMP, repo_root=REPO_ROOT, dsn="", env={}, import_probe=lambda n: False,
                            volume_probe=lambda p: 1, system_drive="Z:", drive_of=lambda p: "D:")
    check("a clean environment passes every check and raise_if_failed is silent",
          clean.ok and not clean.warnings and len(clean.passed) == 5 and code_of(P.raise_if_failed, clean) is None, str(clean))
    dev = P.run_preflight(office_root=TMP, case_root=TMP, repo_root=REPO_ROOT, dsn="", env={}, import_probe=lambda n: False,
                          volume_probe=lambda p: 1, system_drive="D:", drive_of=lambda p: "D:", allow_system_drive=True)
    check("the system-drive rule can be relaxed ONLY explicitly (developer/test) and then a loud WARNING is returned (never silent)",
          dev.ok and dev.warnings == ["SISTEM_SURUCUSU_IZIN_VERILDI_GELISTIRME"])
    strict = P.run_preflight(office_root=TMP, case_root=TMP, repo_root=REPO_ROOT, dsn="", env={}, import_probe=lambda n: False,
                             volume_probe=lambda p: 1, system_drive="D:", drive_of=lambda p: "D:")
    check("without the explicit relaxation the system-drive rule FAILS the preflight", strict.failed == ["SISTEM_SURUCUSU"])
    check("a failed preflight never lets the external-AI refusal be relaxed by the system-drive option",
          "DIS_YZ_PAKETI_VAR" in P.run_preflight(office_root=TMP, case_root=TMP, repo_root=REPO_ROOT, dsn="", env={}, import_probe=lambda n: True,
                                                 volume_probe=lambda p: 1, system_drive="D:", drive_of=lambda p: "D:", allow_system_drive=True).failed)

    # ---------------------------------------------------------------- TEMP yönlendirmesi
    system_temp = os.path.realpath(tempfile.gettempdir())
    before_env = {k: os.environ.get(k) for k in ("TMP", "TEMP", "TMPDIR")}
    before_tempdir = tempfile.tempdir
    target = TMP / "kosu_tmp"
    target.mkdir()
    prior = P.redirect_temp(target)
    try:
        check("redirect_temp: tempfile.gettempdir() and TMP/TEMP/TMPDIR all point at the run tmp dir", P.verify_temp_redirected(target))
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.close()
        created_inside = os.path.dirname(os.path.realpath(handle.name)) == os.path.realpath(str(target))
        os.unlink(handle.name)
        check("a NamedTemporaryFile created while redirected lands INSIDE the run tmp dir", created_inside, handle.name)
        check("the previous temp settings were captured for restoration", prior.previous_tempdir == before_tempdir)
    finally:
        P.restore_temp(prior)
    check("restore_temp restores tempfile.tempdir exactly and the system temp is used again",
          tempfile.tempdir == before_tempdir and os.path.realpath(tempfile.gettempdir()) == system_temp)
    check("restore_temp restores (or removes) every TMP/TEMP/TMPDIR variable exactly", {k: os.environ.get(k) for k in ("TMP", "TEMP", "TMPDIR")} == before_env)
    check("verify_temp_redirected is False once restored", not P.verify_temp_redirected(target))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
