# ============================================================
# VERGİ AI - DEMO P1 - TEK KOMUT: sentetik dosya -> sayfaya bağlı bulgu raporu (HTML)
#
#   python -m ui.demo_case_review --demo-root <DEPO DIŞI klasör> [--spec <demo_spec.json>] [--siki]
#
# Demo kökü (depo dışı):  belgeler/<pdf'ler> + demo_spec.json
# Üretilen:               vaka/<demo_id>/ (yeni) ve cikti/inceleme_<zaman>.html (yeni dosya)
#
# SENTETİK DEMO; gerçek dosya yolu DEĞİLDİR. Ağ/LLM/PostgreSQL yoktur.
# stdout YALNIZ çıktı yolunu ve özet sayıları basar (içerik basmaz); hata YALNIZ
# kapalı kod (`HATA: <KOD>`), traceback basılmaz.
# `--siki`: alıntısı eşleşmeyen örnek bulgu varsa REDDEDİLİR (hiçbir şey yazılmadan).
# Vaka dizini zaten varsa yeniden HAZIRLANMAZ; yalnız yeni bir rapor dosyası üretilir.
# ============================================================

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):  # `python ui/demo_case_review.py` ile de çalışsın
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.services import demo_p1_facts as F  # noqa: E402
from ui.services import demo_p1_intake as I  # noqa: E402
from ui.services import demo_p1_report as P  # noqa: E402
from ui.services.demo_p1_spec import DemoError, MAX_SPEC_BYTES, parse_spec  # noqa: E402
from ui.services.office_flow_records import OfficeFlowError, write_new_file  # noqa: E402


def _read_spec(spec_path) -> bytes:
    path = Path(spec_path)
    real = Path(os.path.realpath(str(path)))
    repo = Path(os.path.realpath(str(I.REPO_ROOT)))
    if real == repo or repo in real.parents:
        raise DemoError("DEMO_KOKU_DEPO_ICINDE")
    try:
        if not path.is_file():
            raise DemoError("SPEC_YOK")
        with open(str(path), "rb") as handle:
            data = handle.read(MAX_SPEC_BYTES + 1)
    except OSError:
        raise DemoError("SPEC_YOK") from None
    return data


def _prepare(root: Path, spec, *, extractor, siki: bool):
    docs = I.analyze_documents(root, spec, extractor=extractor)
    findings, refs = F.evaluate(spec, docs)
    if siki and F.warning_count(findings, refs) > 0:
        raise DemoError("ALINTI_ESLESMEDI")  # hiçbir şey yazılmadan
    case_dir = I.write_case(root, spec, docs)
    written = F.write_facts(case_dir, spec, findings, refs)
    resolver_info = {}
    for ref in refs:
        if not ref.written:
            continue
        try:
            with open(str(written[ref.referenced_in_doc]), "rb") as handle:
                content = json.loads(handle.read().decode("utf-8"))
            fact = next(x for x in content["facts"] if x["fact_id"] == ref.fact_id)
        except (OSError, ValueError, KeyError, StopIteration):
            resolver_info[ref.fact_id] = None
            continue
        resolver_info[ref.fact_id] = F.resolver_unresolved(
            I.case_paths(root, spec.demo_id)["case_root"], spec.demo_id, fact, ref.referenced_in_doc)
    F.write_result_record(case_dir, F.build_result_record(spec, docs, findings, refs, resolver_info=resolver_info))
    return case_dir


def _write_output(root: Path, out_dir: Path, text: str) -> Path:
    try:
        os.mkdir(str(out_dir))
    except FileExistsError:
        pass
    except OSError:
        raise DemoError("YAZMA_BASARISIZ") from None
    I.ensure_inside_root(root, out_dir)  # bağlantı/junction/kök dışı -> DIZIN_GUVENSIZ, ilk yazmadan ÖNCE
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for attempt in range(1, 100):
        name = f"inceleme_{stamp}.html" if attempt == 1 else f"inceleme_{stamp}_{attempt}.html"
        target = out_dir / name
        try:
            write_new_file(target, text.encode("utf-8"))
            return target
        except OfficeFlowError as error:
            if getattr(error, "code", "") == "DOSYA_MEVCUT":
                continue
            raise DemoError("YAZMA_BASARISIZ") from None
    raise DemoError("DOSYA_MEVCUT")


def run(demo_root, spec_path=None, *, siki: bool = False, extractor=None) -> dict:
    root = I.check_demo_root(demo_root)
    spec = parse_spec(_read_spec(spec_path or (root / I.SPEC_NAME)))
    paths = I.case_paths(root, spec.demo_id)
    created = False
    if not I.case_exists(root, spec.demo_id):
        _prepare(root, spec, extractor=extractor, siki=siki)
        created = True
    else:
        I.verify_existing_case(root, spec)  # yarım / başka spec / bağlantı -> açık ret, sessiz devralma yok
    data = P.load_report_data(paths["case_dir"])
    if siki and data.record["warning_count"] > 0:
        raise DemoError("ALINTI_ESLESMEDI")
    target = _write_output(root, paths["out_dir"], P.render_html(data))
    record = data.record
    return {
        "output": target,
        "created": created,
        "documents": len(record["documents"]),
        "matched": sum(1 for f in record["findings"] if f["written"]),
        "warnings": record["warning_count"],
        "refs": len(record["missing_refs"]),
    }


def main(argv=None, *, extractor=None, stdout=None, stderr=None) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = argparse.ArgumentParser(prog="python -m ui.demo_case_review", add_help=True)
    parser.add_argument("--demo-root", required=True)
    parser.add_argument("--spec", default=None)
    parser.add_argument("--siki", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_info:
        return 2 if exit_info.code not in (0, None) else 0
    try:
        result = run(args.demo_root, args.spec, siki=args.siki, extractor=extractor)
    except DemoError as error:
        print(f"HATA: {error.code}", file=err)
        return 1
    except Exception:
        print("HATA: BILINMEYEN_HATA", file=err)
        return 1
    print(f"ÇIKTI: {result['output']}", file=out)
    print(f"vaka: {'yeni hazırlandı' if result['created'] else 'mevcut, yeniden hazırlanmadı'}", file=out)
    print(f"belge: {result['documents']}", file=out)
    print(f"bulgu eşleşen: {result['matched']}; alıntısı eşleşmeyen (uyarı): {result['warnings']}", file=out)
    print(f"atıf kaydı: {result['refs']}", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
