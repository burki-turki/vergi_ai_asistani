# ============================================================
# Row 18C - İZOLE SAF-PYTHON TESTLERİ (manuel CLI köprüsü:
# `ui/run_drafting_request.py`). FastAPI'YE İHTİYAÇ DUYMAZ.
#
# Bu dosya, CLI'nin VARSAYILAN çalıştırmasının TAMAMEN SALT-OKUNUR
# olduğunu, `--generate-pending` bayrağı OLMADAN
# `build_drafting_engine_output`/`write_pending`'in HİÇBİR ZAMAN
# çağrılmadığını (gerçek fonksiyonlar GEÇİCİ olarak sahte/sayaçlı
# fonksiyonlarla değiştirilerek KANITLANIR - yalnız "muhtemelen
# çağrılmadı" değil), her geçersiz bayrak kombinasyonunun HİÇBİR
# MUTASYON OLMADAN reddedildiğini ve bu köprünün hiçbir GERÇEK case'e
# dokunmadığını doğrular. TÜM mutasyon/case senaryoları yalnız
# `tempfile.TemporaryDirectory()` içindeki SENTETİK case'lerle
# çalışır.
#
# Çalıştırma: python ui/tests/test_run_drafting_request_isolated.py
# ============================================================

import contextlib
import hashlib
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.services import paths as real_paths                      # noqa: E402
from ui.services import drafting_request as dr                    # noqa: E402
from ui import run_drafting_request as cli                        # noqa: E402
from ui.services.common import UnknownCaseError                   # noqa: E402

import drafting_engine                                            # noqa: E402
import legal_research_validator as lrv                            # noqa: E402

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        print(f"FAIL {label} {detail}")


def snapshot_tree(*roots):
    manifest = {}
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                manifest[str(path)] = (path.stat().st_size, path.stat().st_mtime_ns, digest)
    return manifest


_SNAPSHOT_ROOTS = (real_paths.DATA_DIR, real_paths.SRC_DIR)
_before_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)


@contextlib.contextmanager
def isolated_case():
    original_cases_dir = dr.CASES_DIR
    original_get_issues_dir = lrv.get_issues_dir
    original_list_case_ids = real_paths.list_case_ids
    original_resolve_case_id = real_paths.resolve_case_id

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        case_id = "case_iso_cli_bridge"
        (tmp_path / case_id).mkdir(parents=True)

        dr.CASES_DIR = tmp_path
        lrv.get_issues_dir = lambda cid: tmp_path / cid / "legal_analysis" / "issue_spotting"
        real_paths.list_case_ids = lambda: [case_id]
        real_paths.resolve_case_id = lambda cid: cid if cid == case_id else original_resolve_case_id(cid)

        try:
            yield (case_id, tmp_path)
        finally:
            dr.CASES_DIR = original_cases_dir
            lrv.get_issues_dir = original_get_issues_dir
            real_paths.list_case_ids = original_list_case_ids
            real_paths.resolve_case_id = original_resolve_case_id


def run_cli(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(argv)
    return (rc, buf.getvalue())


# ============================================================
# 1) HER GEÇERSİZ BAYRAK KOMBİNASYONU - HİÇBİR MUTASYON/case
#    doğrulaması OLMADAN reddediliyor (case_id KASITLI OLARAK
#    bilinmeyen bırakıldı - reddin case_id çözümlemesinden BİLE ÖNCE
#    geldiğini kanıtlamak için).
# ============================================================

rc, out = run_cli(["--case", "hic_boyle_bir_case_yok", "--with-agent"])
check("T01 --with-agent, --generate-pending OLMADAN reddediliyor (rc=2)", rc == 2)
check("T02 T01: case_id çözümlemesine HİÇ ULAŞMADI (case-özel hata YOK)", "bilinmeyen case_id" not in out)

rc, out = run_cli(["--case", "hic_boyle_bir_case_yok", "--allow-network"])
check("T03 --allow-network, --generate-pending OLMADAN reddediliyor (rc=2)", rc == 2)

rc, out = run_cli(["--case", "hic_boyle_bir_case_yok", "--generate-pending", "--allow-network"])
check("T04 --allow-network, --with-agent OLMADAN reddediliyor (rc=2)", rc == 2)

rc, out = run_cli(["--case", "gercekten_yok_boyle_case"])
check("T05 bilinmeyen case_id reddediliyor (rc=2)", rc == 2)
check("T06 T05: hata mesajı case_id'yi ADLANDIRIYOR ama başka hiçbir şey YAPMADI", "bilinmeyen case_id" in out)


# ============================================================
# 2) "NO PATH ARGUMENT" - parser hiçbir dosya-yolu bayrağı SUNMUYOR.
# ============================================================

import inspect
_source = inspect.getsource(cli.main)
check(
    "T07 CLI kaynağında `--case` DIŞINDA hiçbir 'path'/'file'/'dosya' argümanı TANIMLANMADI",
    all(tok not in _source for tok in ("--input-file", "--lawyer-input-json", "--path", "type=Path", "type=open")),
)
check(
    "T08 CLI kaynağı yalnız beklenen DÖRT bayrağı tanımlıyor",
    _source.count('parser.add_argument("--') == 4,
)


# ============================================================
# 3) VARSAYILAN (bayraksız) ÇALIŞTIRMA - TAMAMEN SALT-OKUNUR, HİÇBİR
#    ENGINE/WRITE ÇAĞRISI YOK (gerçek fonksiyonlar SAYAÇLI sahtelerle
#    DEĞİŞTİRİLEREK kanıtlanır).
# ============================================================

with isolated_case() as (case_id, tmp_path):
    call_counts = {"build": 0, "write": 0}

    original_build = drafting_engine.build_drafting_engine_output
    original_write = drafting_engine.write_pending

    def counting_build(*a, **kw):
        call_counts["build"] += 1
        return original_build(*a, **kw)

    def counting_write(*a, **kw):
        call_counts["write"] += 1
        return original_write(*a, **kw)

    drafting_engine.build_drafting_engine_output = counting_build
    drafting_engine.write_pending = counting_write

    try:
        # 3a) kayıtlı girdi HİÇ YOK.
        rc, out = run_cli(["--case", case_id])
        check("T09 kayıtlı girdi yokken varsayılan çalıştırma rc=0", rc == 0)
        check("T10 kayıtlı girdi yokken: 'KAYITLI GİRDİ YOK' raporlanıyor", "KAYITLI GİRDİ YOK" in out)
        check("T11 kayıtlı girdi yokken: SALT-OKUNUR olduğu açıkça belirtiliyor", "SALT-OKUNUR" in out)
        check("T12 build_drafting_engine_output HİÇ ÇAĞRILMADI", call_counts["build"] == 0)
        check("T13 write_pending HİÇ ÇAĞRILMADI", call_counts["write"] == 0)
        check("T14 varsayılan çalıştırma current dosyayı OLUŞTURMADI", not dr.get_current_input_path(case_id).exists())

        # 3b) geçerli bir kayıtlı girdi VAR - yine de salt-okunur kalmalı.
        token = dr.compute_current_freshness_token(case_id)
        dr.save_lawyer_input_from_form(
            case_id=case_id, draft_intent_type_choice="not_set", appeal_level_choice="",
            issue_selection_mode="not_provided", selected_issue_ids_raw=[],
            request_type_raw="", request_text_raw="", lawyer_provided_text_raw="cli test metni",
            expected_current_input_hash=token,
        )
        audit_count_before = len(list(dr.get_input_audit_dir(case_id).glob("*")))

        rc, out = run_cli(["--case", case_id])
        check("T15 geçerli kayıtlı girdiyle varsayılan çalıştırma rc=0", rc == 0)
        check("T16 wrapper doğrulaması PASS raporlanıyor", "Wrapper doğrulaması: PASS" in out)
        check("T17 build_drafting_engine_output HÂLÂ ÇAĞRILMADI", call_counts["build"] == 0)
        check("T18 write_pending HÂLÂ ÇAĞRILMADI", call_counts["write"] == 0)
        check(
            "T19 varsayılan çalıştırma audit sayısını ARTIRMADI (hiçbir yeni yazma yok)",
            len(list(dr.get_input_audit_dir(case_id).glob("*"))) == audit_count_before,
        )

        # 3c) --generate-pending OLMADAN --with-agent/--allow-network zaten
        # üstte case-bağımsız test edildi; burada AYRICA geçerli bir case
        # ile de reddedildiğini doğruluyoruz (savunma derinliği).
        rc, out = run_cli(["--case", case_id, "--with-agent"])
        check("T20 geçerli case + --with-agent (--generate-pending YOK) yine reddediliyor", rc == 2)
        check("T21 T20: build_drafting_engine_output ÇAĞRILMADI", call_counts["build"] == 0)

    finally:
        drafting_engine.build_drafting_engine_output = original_build
        drafting_engine.write_pending = original_write


# ============================================================
# 4) --generate-pending İÇİN GEÇERSİZ/EKSİK WRAPPER REDDİ
# ============================================================

with isolated_case() as (case_id, tmp_path):
    call_counts = {"build": 0}
    original_build = drafting_engine.build_drafting_engine_output
    drafting_engine.build_drafting_engine_output = lambda *a, **kw: call_counts.__setitem__("build", call_counts["build"] + 1) or original_build(*a, **kw)

    try:
        rc, out = run_cli(["--case", case_id, "--generate-pending"])
        check("T22 kayıtlı girdi YOKKEN --generate-pending reddediliyor (rc=2)", rc == 2)
        check("T23 T22: build_drafting_engine_output ÇAĞRILMADI", call_counts["build"] == 0)

        # Bozuk bir wrapper dosyası yaz (şemadan geçemez).
        bad_path = dr.get_current_input_path(case_id)
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text('{"schema_version": 1, "bogus": true}', encoding="utf-8")

        rc, out = run_cli(["--case", case_id, "--generate-pending"])
        check("T24 GEÇERSİZ wrapper varken --generate-pending reddediliyor (rc=2)", rc == 2)
        check("T25 T24: build_drafting_engine_output ÇAĞRILMADI", call_counts["build"] == 0)
    finally:
        drafting_engine.build_drafting_engine_output = original_build


# ============================================================
# 5) GERÇEK data/ ve src/ AĞAÇLARININ HİÇBİR TESTLE DEĞİŞMEDİĞİNİN
#    BYTE-DÜZEYİNDE KANITI (bu köprü GERÇEK hiçbir case'e DOKUNMADI).
# ============================================================

_after_snapshot = snapshot_tree(*_SNAPSHOT_ROOTS)
check(
    "T26 GERÇEK data/ ve src/ ağaçları bu test dosyasıyla DEĞİŞMEDİ (byte-düzeyinde)",
    _before_snapshot == _after_snapshot,
    f"fark={set(_before_snapshot) ^ set(_after_snapshot)}",
)


print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
