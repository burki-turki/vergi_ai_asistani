# ============================================================
# BÜRO MODELİ / T1 - ui/services/office_flow_outcomes.py İZOLE TESTİ
# + STATİK (AST) TARAMALAR: yeni 7 kaynak modülde ağ/LLM import'u yok,
#   subprocess YALNIZ intake'te, kayıt silen/budayan kod yolu yok,
#   saklama/süre mantığı yok ("3 yıl" hiçbir mantığa bağlı değil).
#
# Kapsam: üç kayıt (pilot test sonucu / imha kaydı / destek özeti) KAPALI
# şemalar; içerik koruması (tarih/hash/yol/ad/e-posta/uzun sayı RED);
# O_EXCL sıra numaralı yazım; açık BASLADI tespiti; hata eşleme (str(error)
# asla taşınmaz).
# ============================================================

import ast
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


def summarize_and_exit():
    print(f"--- test_office_flow_outcomes_isolated: {passed} passed, {failed} failed, {skipped} skipped ---")
    sys.exit(1 if failed else 0)


from ui.services import office_flow_outcomes as O  # noqa: E402
from ui.services import office_flow_records as R  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="vergi_t1_outcomes_"))


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except R.OfficeFlowError as error:
        return error.code
    return None


SENTINELS = ("10.02.2026", "2026-02-10", "12.03.2026", "a" * 64, "C:\\Users\\x\\gizli.pdf", "/tmp/gizli", "kisi@ornek.com",
             "1234567890", "ihbarname_kaynak.pdf", "Ad Soyad 5/6/2026")

try:
    # ---------------------------------------------------------------- 1. pilot test sonucu
    ok_uyumlu = O.build_test_result(sonuc="UYUMLU", kontrol_turu="ILK_KONTROL")
    check("test result UYUMLU: exactly the closed keys, NO category key, NO time/identity/hash field",
          ok_uyumlu == {"kayit_surumu": 1, "yazilim_surumu": R.SOFTWARE_VERSION, "sonuc": "UYUMLU", "kontrol_turu": "ILK_KONTROL"})
    ok_uyusmazlik = O.build_test_result(sonuc="UYUSMAZLIK", kontrol_turu="YENIDEN_KONTROL", hata_kategorisi="TATIL_KAYDIRMASI")
    check("test result UYUSMAZLIK carries a closed-list category and the control kind",
          ok_uyusmazlik["hata_kategorisi"] == "TATIL_KAYDIRMASI" and ok_uyusmazlik["kontrol_turu"] == "YENIDEN_KONTROL")
    check("UYUSMAZLIK without a category is refused", code_of(O.build_test_result, sonuc="UYUSMAZLIK", kontrol_turu="ILK_KONTROL") == "KAYIT_SEMASI_GECERSIZ")
    check("UYUMLU WITH a category is refused", code_of(O.build_test_result, sonuc="UYUMLU", kontrol_turu="ILK_KONTROL", hata_kategorisi="SURE_KURALI") == "KAYIT_SEMASI_GECERSIZ")
    check("a category outside the closed list (free text) is refused",
          code_of(O.build_test_result, sonuc="UYUSMAZLIK", kontrol_turu="ILK_KONTROL", hata_kategorisi="avukat yanlis yapmis") == "KAYIT_SEMASI_GECERSIZ")
    check("an unknown result / control kind is refused",
          code_of(O.build_test_result, sonuc="BELKI", kontrol_turu="ILK_KONTROL") == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.build_test_result, sonuc="UYUMLU", kontrol_turu="TEKRAR") == "KAYIT_SEMASI_GECERSIZ")
    check("the closed category list is exactly the four lawyer-approvable categories",
          set(R.ERROR_CATEGORIES) == {"TEBLIG_TARIHI_SECIMI", "SURE_KURALI", "TATIL_KAYDIRMASI", "NEDEN_HENUZ_BELIRLENEMEDI"})
    for extra in ("kayit_zamani", "dosya_kodu", "run_id", "tarih", "hash"):
        check(f"validate_test_result refuses an extra field `{extra}` (closed schema)",
              code_of(O.validate_test_result, {**ok_uyumlu, extra: "x"}) == "KAYIT_SEMASI_GECERSIZ")
    check("the test result schema has NO retention/time field at all", not any("zaman" in k or "sure" in k or "saklama" in k for k in O.TEST_RESULT_KEYS))

    # ---------------------------------------------------------------- 2. içerik koruması
    for sentinel in SENTINELS:
        check(f"content guard rejects a sentinel string ({sentinel[:12]}...)", code_of(O._assert_clean_string, sentinel) == "KAYIT_ICERIK_RED")
    check("content guard accepts closed enum strings", all(code_of(O._assert_clean_string, s) is None
          for s in ("UYUMLU", "CALISMA_DIZINI_BELGE_KOPYASI", "YALNIZ_PILOT_KOPYALARI", "office_flow_t1")))
    check("a software version containing a date is refused by the version pattern",
          code_of(O.validate_test_result, {**ok_uyumlu, "yazilim_surumu": "v 10.02.2026"}) == "KAYIT_SEMASI_GECERSIZ")

    # ---------------------------------------------------------------- 3. imha kaydı
    items = [{"tur": "CALISMA_DOSYALARI", "adet": 20, "sonuc": "PLANLANDI"}, {"tur": "PILOT_HESAP_RAPORU", "adet": 1, "sonuc": "PLANLANDI"}]
    started = O.build_imha_record(asama="BASLADI", kopya_turleri=items)
    check("imha BASLADI: no result field; carries time, copy TYPES+counts, method, scope and the not-deleted list",
          "genel_sonuc" not in started and started["asama"] == "BASLADI" and started["yontem"] == "DOSYA_SISTEMI_SILME"
          and started["tamamlandi_kapsami"] == "YALNIZ_PILOT_KOPYALARI" and started["silinmeyenler"] == ["VERITABANI_ISLEM_KAYITLARI"]
          and O._TIME_RE.match(started["islem_zamani"]))
    done = O.build_imha_record(asama="SONUC", kopya_turleri=[{"tur": "CALISMA_DOSYALARI", "adet": 20, "sonuc": "TAMAMLANDI"}], genel_sonuc="TAMAMLANDI")
    check("imha SONUC: carries the overall result", done["genel_sonuc"] == "TAMAMLANDI" and set(done) <= set(O.IMHA_KEYS))
    check("a BASLADI record with a result is refused (TAMAMLANDI cannot be claimed at the start)",
          code_of(O.build_imha_record, asama="BASLADI", kopya_turleri=items, genel_sonuc="TAMAMLANDI") == "KAYIT_SEMASI_GECERSIZ")
    check("a SONUC record WITHOUT a result is refused", code_of(O.build_imha_record, asama="SONUC", kopya_turleri=items) == "KAYIT_SEMASI_GECERSIZ")
    check("an unknown overall result / stage is refused",
          code_of(O.build_imha_record, asama="SONUC", kopya_turleri=[], genel_sonuc="BELKI") == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.build_imha_record, asama="BITTI", kopya_turleri=[]) == "KAYIT_SEMASI_GECERSIZ")
    check("an unknown copy type or a negative/float count is refused",
          code_of(O.build_imha_record, asama="BASLADI", kopya_turleri=[{"tur": "MUVEKKIL_DOSYASI", "adet": 1, "sonuc": "PLANLANDI"}]) == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.build_imha_record, asama="BASLADI", kopya_turleri=[{"tur": "CALISMA_DOSYALARI", "adet": -1, "sonuc": "PLANLANDI"}]) == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.build_imha_record, asama="BASLADI", kopya_turleri=[{"tur": "CALISMA_DOSYALARI", "adet": 1.5, "sonuc": "PLANLANDI"}]) == "KAYIT_SEMASI_GECERSIZ")
    check("an item with an extra key (e.g. a file name) is refused",
          code_of(O.build_imha_record, asama="BASLADI", kopya_turleri=[{"tur": "CALISMA_DOSYALARI", "adet": 1, "sonuc": "PLANLANDI", "ad": "x.pdf"}]) == "KAYIT_SEMASI_GECERSIZ")
    check("an imha record with a free-text extra field is refused", code_of(O.validate_imha_record, {**done, "not": "belge adi"}) == "KAYIT_SEMASI_GECERSIZ")
    check("the imha time field is the ONLY date-like string and must be a UTC timestamp",
          code_of(O.validate_imha_record, {**done, "islem_zamani": "10.02.2026"}) == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.validate_imha_record, {**done, "islem_zamani": "2026-02-10"}) == "KAYIT_SEMASI_GECERSIZ")
    check("scope/method/not-deleted constants cannot be altered",
          code_of(O.validate_imha_record, {**done, "tamamlandi_kapsami": "TUM_VERI"}) == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.validate_imha_record, {**done, "silinmeyenler": []}) == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.validate_imha_record, {**done, "yontem": "GUVENLI_SILME"}) == "KAYIT_SEMASI_GECERSIZ")

    # ---------------------------------------------------------------- 4. kayitlar/ yazıcıları
    records_dir = TMP / "kayitlar"
    records_dir.mkdir()
    token = O.new_imha_token()
    p1 = O.write_imha_record(records_dir, token, started)
    p2 = O.write_imha_record(records_dir, token, done)
    check("imha records get sequence-numbered files (0001, 0002) and are never overwritten",
          p1.name == f"imha_{token}_0001.json" and p2.name == f"imha_{token}_0002.json" and p1.exists() and p2.exists())
    first_bytes = p1.read_bytes()
    O.write_imha_record(records_dir, token, started)
    check("a third record becomes 0003; the earlier files are byte-identical", p1.read_bytes() == first_bytes and (records_dir / f"imha_{token}_0003.json").exists())
    check("imha_records_for lists (seq, record) pairs in order", [s for s, _ in O.imha_records_for(records_dir, token)] == [1, 2, 3])
    check("the open-deletion detector: the LAST record is BASLADI -> the token is open", O.open_imha_tokens(records_dir) == [token])
    token2 = O.new_imha_token()
    O.write_imha_record(records_dir, token2, started)
    O.write_imha_record(records_dir, token2, done)
    check("a token whose last record is SONUC is NOT open; the open one is still reported alone", O.open_imha_tokens(records_dir) == [token])
    result_token = O.new_result_token()
    pr = O.write_test_result(records_dir, ok_uyumlu, token=result_token)
    before = pr.read_bytes()
    check("the same result token cannot be written twice (O_EXCL): no duplicate result after a restart",
          code_of(O.write_test_result, records_dir, ok_uyusmazlik, result_token) == "DOSYA_MEVCUT" and pr.read_bytes() == before)
    check("test results without a token get a fresh random one each time",
          O.write_test_result(records_dir, ok_uyumlu).name != O.write_test_result(records_dir, ok_uyumlu).name)
    written_text = "".join(p.read_text(encoding="utf-8") for p in records_dir.iterdir())
    check("everything written under kayitlar/ is sentinel-free", not any(s in written_text for s in SENTINELS if s not in ("1234567890",)))
    check("no file under kayitlar/ was ever deleted by these writers (all written files still exist)",
          len(list(records_dir.iterdir())) == 3 + 2 + 1 + 2)

    # ---------------------------------------------------------------- 5. destek özeti
    summary = O.build_support_summary(islem_adimi="F3", hata_kodu="YETKI_YOK")
    check("support summary has EXACTLY three fields: version, step, error code", set(summary) == {"yazilim_surumu", "islem_adimi", "hata_kodu"})
    summary2 = O.build_support_summary(islem_adimi="F5", hata_kategorisi="SURE_KURALI")
    check("support summary may carry the closed category INSTEAD of a code", set(summary2) == {"yazilim_surumu", "islem_adimi", "hata_kategorisi"})
    check("support summary requires exactly one of code/category",
          code_of(O.build_support_summary, islem_adimi="F3") == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.build_support_summary, islem_adimi="F3", hata_kodu="YETKI_YOK", hata_kategorisi="SURE_KURALI") == "KAYIT_SEMASI_GECERSIZ")
    check("support summary refuses an unknown step, an unknown code or an unknown category",
          code_of(O.build_support_summary, islem_adimi="F9", hata_kodu="YETKI_YOK") == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.build_support_summary, islem_adimi="F3", hata_kodu="10.02.2026 tarihli hata") == "KAYIT_SEMASI_GECERSIZ"
          and code_of(O.build_support_summary, islem_adimi="F3", hata_kategorisi="serbest") == "KAYIT_SEMASI_GECERSIZ")
    rendered = O.render_support_summary(summary)
    check("the rendered summary shows only the three fields plus a 'nothing is sent automatically' notice",
          rendered.count("=") == 3 and "YAZILIM_SURUMU=" in rendered and "ISLEM_ADIMI=F3" in rendered and "HATA_KODU=YETKI_YOK" in rendered
          and "otomatik göndermez" in rendered)

    class CaseAccessDeniedError(Exception):
        pass

    class DatabaseNotConfiguredError(Exception):
        pass

    class ApprovalUiError(Exception):
        pass

    class StaleViewError(ApprovalUiError):
        pass

    class FakePsycopgError(Exception):
        __module__ = "psycopg.errors"

    mapping = {
        "office error keeps its code": (R.OfficeFlowError("ANCHOR_BELIRSIZ"), "ANCHOR_BELIRSIZ"),
        "CaseAccessDeniedError -> YETKI_YOK": (CaseAccessDeniedError("x"), "YETKI_YOK"),
        "DatabaseNotConfiguredError": (DatabaseNotConfiguredError("x"), "VERITABANI_YAPILANDIRMASI_YOK"),
        "psycopg family -> VERITABANI_HATASI": (FakePsycopgError("x"), "VERITABANI_HATASI"),
        "any ApprovalUiError subclass -> ZINCIR_ADIMI_BASARISIZ": (StaleViewError("x"), "ZINCIR_ADIMI_BASARISIZ"),
        "OSError -> DOSYA_ISLEMI_BASARISIZ": (PermissionError("x"), "DOSYA_ISLEMI_BASARISIZ"),
        "EOFError -> KULLANICI_ILERLETMEDI": (EOFError(), "KULLANICI_ILERLETMEDI"),
        "KeyboardInterrupt -> KULLANICI_ILERLETMEDI": (KeyboardInterrupt(), "KULLANICI_ILERLETMEDI"),
        "unknown -> BILINMEYEN_HATA": (ZeroDivisionError("x"), "BILINMEYEN_HATA"),
    }
    for label, (exc, expected) in mapping.items():
        check(f"error mapping: {label}", O.error_code_for(exc) == expected, O.error_code_for(exc))
    leaky = RuntimeError("tarih 10.02.2026 yol C:\\gizli\\ihbarname.pdf hash " + "a" * 64)
    out = O.render_support_summary(O.build_support_summary(islem_adimi="F2", hata_kodu=O.error_code_for(leaky)))
    check("a leaky exception message never reaches the support output (only the closed code does)",
          not any(s in out for s in ("10.02.2026", "gizli", "ihbarname", "a" * 16)) and "BILINMEYEN_HATA" in out)
    check("every closed error code is valid for the support summary", all(O.build_support_summary(islem_adimi="F0", hata_kodu=c) for c in R.ERROR_CODES))

    # ---------------------------------------------------------------- 6. STATİK (AST) TARAMALAR
    sources = [UI_DIR / "office_deadline_flow.py"] + sorted((UI_DIR / "services").glob("office_flow_*.py"))
    check("exactly the seven T1 source modules are present", len(sources) == 7 and {p.name for p in sources} == {
        "office_deadline_flow.py", "office_flow_records.py", "office_flow_intake.py", "office_flow_preflight.py",
        "office_flow_report.py", "office_flow_outcomes.py", "office_flow_cleanup.py"}, str([p.name for p in sources]))
    BANNED = {"anthropic", "openai", "httpx", "httpx2", "requests", "urllib", "urllib3", "socket", "http", "smtplib",
              "ftplib", "telnetlib", "ssl", "truststore", "aiohttp", "websockets", "xmlrpc", "asyncio"}
    network_hits, subprocess_files, delete_calls, retention_names, dynamic_imports = [], [], [], [], []
    DELETE_ATTRS = {"remove", "unlink", "rmdir", "rmtree", "removedirs", "rename", "replace"}
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in BANNED:
                        network_hits.append((path.name, alias.name))
                    if top == "subprocess":
                        subprocess_files.append(path.name)
            elif isinstance(node, ast.ImportFrom):
                top = (node.module or "").split(".")[0]
                if top in BANNED:
                    network_hits.append((path.name, node.module))
                if top == "subprocess":
                    subprocess_files.append(path.name)
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else "")
                if name == "__import__":
                    dynamic_imports.append(path.name)
                # `replace`/`rename` yalnız `os.`/`shutil.` alıcısıyla dosya sistemi işlemidir
                # (str.replace bir dosya işlemi DEĞİLDİR).
                receiver = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else ""
                if name in DELETE_ATTRS and (name not in ("replace", "rename") or receiver in ("os", "shutil")):
                    delete_calls.append((path.name, name))
            ids = []
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                ids.append(node.name)
            elif isinstance(node, ast.Name):
                ids.append(node.id)
            elif isinstance(node, ast.Attribute):
                ids.append(node.attr)
            for ident in ids:
                low = ident.lower()
                if any(w in low for w in ("retention", "saklama", "prune", "purge", "expire", "ttl", "timedelta")):
                    retention_names.append((path.name, ident))
    check("NO network/LLM/mail/async import in ANY of the seven T1 source modules (AST scan)", not network_hits, str(network_hits))
    check("`subprocess` is imported ONLY by office_flow_intake.py (the default Poppler extractor)", sorted(set(subprocess_files)) == ["office_flow_intake.py"], str(subprocess_files))
    check("no dynamic `__import__` in any T1 source module", not dynamic_imports, str(dynamic_imports))
    outcomes_deletes = [d for d in delete_calls if d[0] == "office_flow_outcomes.py"]
    check("office_flow_outcomes.py has NO delete/rename/replace call at all (records are never removed or pruned)", not outcomes_deletes, str(outcomes_deletes))
    check("no T1 module other than cleanup/records deletes or renames anything",
          all(d[0] in ("office_flow_cleanup.py", "office_flow_records.py") for d in delete_calls), str(delete_calls))
    check("no retention/pruning/expiry identifier exists in any T1 source module (no '3 years' logic anywhere)", not retention_names, str(retention_names))
    constants = []
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool) and node.value in (365, 1095, 1096, 36, 94608000):
                constants.append((path.name, node.value))
    check("no calendar-duration constant (365/1095/36 months/seconds-in-3-years) in any T1 source module", not constants, str(constants))
    check("the support-summary builder never reads/writes any file", "open(" not in ast.get_source_segment(
        Path(UI_DIR / "services" / "office_flow_outcomes.py").read_text(encoding="utf-8"),
        next(n for n in ast.walk(ast.parse((UI_DIR / "services" / "office_flow_outcomes.py").read_text(encoding="utf-8")))
             if isinstance(n, ast.FunctionDef) and n.name == "build_support_summary")))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

check("the temp tree of this test was removed", not TMP.exists())
summarize_and_exit()
