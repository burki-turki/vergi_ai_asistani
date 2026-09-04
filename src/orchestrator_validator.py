# ============================================================
# VERGİ AI - ORCHESTRATOR VALIDATOR V1 (Row 17)
#
# BAĞIMSIZ DOĞRULAMA: kayıtlı case_view.json'un kendi alanlarına
# GÜVENMEZ - orchestrator_engine.build_case_view()'ı AYNI saf
# fonksiyonla YENİDEN ÇAĞIRIR ve kayıtlı belgeyle TAM (derin)
# karşılaştırır (Row 16 qa_validator.py ile AYNI disiplin: motorun
# kendi hesapladığı değere güvenilmez, bağımsız yeniden üretimle
# karşılaştırılır).
#
# case_view saf bir DETERMİNİSTİK BİRLEŞTİRME olduğundan (agent/LLM
# katmanı YOK - Row 17 kapsam kararı: seçenek A), "bağımsız yeniden
# hesaplama" burada Row 16'daki gibi check-by-check karşılaştırma
# DEĞİL, üç zaman damgası alanı (generated_at, scan_started_at,
# scan_completed_at) HARİÇ TAM belge eşitliğidir - girdi değişmediği
# sürece iki çağrı birebir AYNI belgeyi üretmek ZORUNDADIR.
# ============================================================

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from qa_discovery import DATA_DIR
from orchestrator_discovery import get_source_path, load_source_scope
from orchestrator_policy import ORCHESTRATOR_SOURCE_REGISTRY
import orchestrator_engine


CASE_VIEW_SCHEMA_PATH = DATA_DIR / "case_view.schema.json"

# Belge eşitliği karşılaştırmasından HARİÇ TUTULAN alanlar - bunlar
# yalnız duvar-saati zaman damgasıdır, iki bağımsız çağrı arasında
# FARKLI olması BEKLENİR ve bir tutarsızlık/tahrifat SAYILMAZ.
_VOLATILE_TOP_LEVEL_FIELDS = ("generated_at",)
_VOLATILE_METADATA_FIELDS = ("scan_started_at", "scan_completed_at")


def load_json(path):

    with open(path, encoding="utf-8") as file:

        return json.load(file)


def validate_schema(view):

    schema = load_json(CASE_VIEW_SCHEMA_PATH)

    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    return [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in validator.iter_errors(view)]


def validate_case_id(view, expected_case_id):

    if expected_case_id is None:

        return []

    if view.get("case_id") != expected_case_id:

        return [f"case_id uyuşmuyor: beklenen={expected_case_id}, kayıtlı={view.get('case_id')}"]

    return []


def validate_generated_at(view):

    errors = []

    if not isinstance(view.get("generated_at"), str) or not view["generated_at"]:

        errors.append("generated_at eksik/geçersiz.")

    metadata = view.get("analysis_metadata", {})

    for field in _VOLATILE_METADATA_FIELDS:

        if not isinstance(metadata.get(field), str) or not metadata[field]:

            errors.append(f"analysis_metadata.{field} eksik/geçersiz.")

    return errors


def check_snapshot_freshness(view):
    """
    Kayıtlı dependency_manifest'in raw_byte_sha256 değerlerini GÜNCEL
    11 kaynak dosyayla karşılaştırır. Uyuşmazlık 'STALE' (tahrifat
    DEĞİL, yeniden tarama gerekli) olarak sınıflandırılır - Row 16
    qa_validator.check_snapshot_freshness ile AYNI ilke.
    """

    manifest = view.get("analysis_metadata", {}).get("dependency_manifest", [])
    case_id = view.get("case_id")
    stale_refs = []

    manifest_by_ref = {entry.get("artifact_ref"): entry for entry in manifest}

    for scope_id in ORCHESTRATOR_SOURCE_REGISTRY:

        entry = manifest_by_ref.get(scope_id)

        if entry is None:

            stale_refs.append(scope_id)
            continue

        live = load_source_scope(scope_id, case_id)

        if live["raw_bytes_sha256"] != entry.get("raw_byte_sha256"):

            stale_refs.append(scope_id)

        if live["artifact_state"] != entry.get("artifact_state"):

            stale_refs.append(scope_id)

    return sorted(set(stale_refs))


def _strip_volatile(view):

    import copy

    stripped = copy.deepcopy(view)

    for field in _VOLATILE_TOP_LEVEL_FIELDS:

        stripped.pop(field, None)

    metadata = stripped.get("analysis_metadata")

    if isinstance(metadata, dict):

        for field in _VOLATILE_METADATA_FIELDS:

            metadata.pop(field, None)

    return stripped


def _deep_diff(recorded, fresh, path=""):
    """
    Saf, genel amaçlı derin fark bulucu. dict/list/scalar için
    yol-etiketli (örn. 'issue_panel[2].evidence.supports_candidate_ids')
    okunabilir fark mesajları üretir. Yeni bir karşılaştırma DSL'i
    İCAT ETMEZ - Python eşitliğine dayanır.
    """

    diffs = []

    if type(recorded) is not type(fresh) and not (
        isinstance(recorded, (int, float)) and isinstance(fresh, (int, float))
    ):

        diffs.append(f"{path or '<root>'}: tip uyuşmuyor (kayıtlı={type(recorded).__name__}, bağımsız={type(fresh).__name__})")
        return diffs

    if isinstance(recorded, dict):

        all_keys = sorted(set(recorded) | set(fresh))

        for key in all_keys:

            child_path = f"{path}.{key}" if path else key

            if key not in recorded:

                diffs.append(f"{child_path}: yalnız bağımsız yeniden hesaplamada var (kayıtlıda EKSİK).")

            elif key not in fresh:

                diffs.append(f"{child_path}: yalnız kayıtlı belgede var (bağımsız yeniden hesaplamada EKSİK - uydurma/fazladan alan şüphesi).")

            else:

                diffs.extend(_deep_diff(recorded[key], fresh[key], child_path))

    elif isinstance(recorded, list):

        if len(recorded) != len(fresh):

            diffs.append(f"{path}: liste uzunluğu uyuşmuyor (kayıtlı={len(recorded)}, bağımsız={len(fresh)})")

        for index in range(min(len(recorded), len(fresh))):

            diffs.extend(_deep_diff(recorded[index], fresh[index], f"{path}[{index}]"))

    else:

        if recorded != fresh:

            diffs.append(f"{path}: değer uyuşmuyor (kayıtlı={recorded!r}, bağımsız={fresh!r})")

    return diffs


def validate_deterministic_view_independently(view, expected_case_id):
    """
    orchestrator_engine.build_case_view()'ı YENİDEN çağırır (aynı saf
    girdi okuma + gruplama fonksiyonları - motorun kendi kaydettiği
    belgeye GÜVENİLMEZ) ve kayıtlı case_view ile (zaman damgaları
    HARİÇ) TAM karşılaştırır.
    """

    fresh = orchestrator_engine.build_case_view(expected_case_id)

    recorded_stripped = _strip_volatile(view)
    fresh_stripped = _strip_volatile(fresh)

    diffs = _deep_diff(recorded_stripped, fresh_stripped)

    return diffs, fresh


def validate_generation_status_consistency(view):
    """
    generation_status yalnız iki değerden biri olabilir (Row 17 v1
    saf deterministik motor: 'completed_with_errors'/'aborted_source_changed'
    bu motor tarafından hiç ÜRETİLMEZ - şemadaki geniş enum Row 16 ile
    aynı sözlüğü paylaşır ama v1 motoru yalnız bu iki değeri üretir).
    """

    status = view.get("generation_status")

    if status not in ("completed", "failed"):

        return [
            f"generation_status={status!r} - Row 17 v1 saf deterministik motorunun "
            "üretmediği bir değer (yalnız 'completed'/'failed' beklenir)."
        ]

    return []


def validate_case_view(case_view_path, expected_case_id=None, raise_on_error=False):

    view = load_json(case_view_path)

    errors = []

    errors.extend(validate_schema(view))
    errors.extend(validate_case_id(view, expected_case_id))
    errors.extend(validate_generated_at(view))
    errors.extend(validate_generation_status_consistency(view))

    case_id = expected_case_id or view.get("case_id")

    stale_refs = check_snapshot_freshness(view)

    if stale_refs:

        errors.append(
            f"STALE SNAPSHOT (tahrifat DEĞİL - yeniden tarama gerekli): raporun kaydettiği "
            f"anlık görüntü güncel kaynaklarla eşleşmiyor: {stale_refs}"
        )

    else:

        diffs, _fresh = validate_deterministic_view_independently(view, case_id)

        if diffs:

            errors.append(
                "BAĞIMSIZ YENİDEN HESAPLAMA UYUŞMAZLIĞI (tahrif edilmiş veya uydurma "
                f"içerik şüphesi) - {len(diffs)} fark:\n" + "\n".join(f"  - {d}" for d in diffs[:50])
            )

    result = {"valid": len(errors) == 0, "errors": errors, "case_id": view.get("case_id")}

    if raise_on_error and errors:

        raise ValueError("\nCASE_VIEW VALIDATION HATASI\n" + "\n".join(f"- {e}" for e in errors))

    return result


# ============================================================
# SELF TEST (gerçek case_0001 üzerinde, izole tempdir'de)
# ============================================================

def run_self_test():

    import copy
    import tempfile

    print()
    print("======================================")
    print(" VERGİ AI - ORCHESTRATOR VALIDATOR V1 (SELF-TEST)")
    print("======================================")

    case_id = "case_0001"

    real = orchestrator_engine.build_case_view(case_id)

    def write_and_validate(view):

        with tempfile.TemporaryDirectory(prefix="orchestrator_validator_selftest_") as td:

            p = Path(td) / "case_view_test.json"

            with open(p, "w", encoding="utf-8") as f:

                json.dump(view, f, ensure_ascii=False)

            return validate_case_view(p, expected_case_id=case_id)

    # T01: genuine, untampered case_view -> PASS
    v1 = write_and_validate(real)

    assert v1["valid"] is True, "\n".join(v1["errors"])

    print("T01 Genuine case_view validator PASS verdi:", "PASS")

    # T02: skaler alan tahrifatı (case_summary.title)
    t2 = copy.deepcopy(real)

    t2["case_summary"]["title"] = "TAHRİF EDİLMİŞ BAŞLIK"

    v2 = write_and_validate(t2)

    assert v2["valid"] is False

    print("T02 Tahrif edilmiş case_summary.title reddedildi:", "PASS")

    # T03: uydurma bir ID eklenmesi (issue_panel[0].legal_research_ids'e
    # var olmayan bir research_id eklenmiş)
    t3 = copy.deepcopy(real)

    assert t3["issue_panel"], "Test fixture varsayımı geçersiz: issue_panel boş."

    t3["issue_panel"][0]["legal_research_ids"] = list(t3["issue_panel"][0]["legal_research_ids"]) + ["research_UYDURMA_999"]

    v3 = write_and_validate(t3)

    assert v3["valid"] is False

    print("T03 Uydurma legal_research_id reddedildi:", "PASS")

    # T04: bir issue_panel kaydının TAMAMEN çıkarılması
    t4 = copy.deepcopy(real)

    t4["issue_panel"] = t4["issue_panel"][1:]

    v4 = write_and_validate(t4)

    assert v4["valid"] is False

    print("T04 Eksik/atlanmış issue_panel kaydı reddedildi:", "PASS")

    # T05: generation_status tahrifatı (completed -> failed, girdi
    # aslında tam mevcutken)
    t5 = copy.deepcopy(real)

    assert t5["generation_status"] == "completed", "Test fixture varsayımı geçersiz: case_0001 generation_status != completed."

    t5["generation_status"] = "failed"

    v5 = write_and_validate(t5)

    assert v5["valid"] is False

    print("T05 Tahrif edilmiş generation_status (completed->failed) reddedildi:", "PASS")

    # T06: STALE snapshot (tahrifat DEĞİL) - manifest sha256 elle bozulmuş
    t6 = copy.deepcopy(real)

    t6["analysis_metadata"]["dependency_manifest"][0]["raw_byte_sha256"] = "0" * 64

    v6 = write_and_validate(t6)

    assert v6["valid"] is False
    assert any("STALE SNAPSHOT" in e for e in v6["errors"])

    print("T06 Stale snapshot ayrı bir hata sınıfıyla (tahrifat DENMEDEN) tespit edildi:", "PASS")

    # T07: şema ihlali (additionalProperties)
    t7 = copy.deepcopy(real)

    t7["unexpected_extra_field"] = "x"

    v7 = write_and_validate(t7)

    assert v7["valid"] is False

    print("T07 Şema ihlali (bilinmeyen alan) reddedildi:", "PASS")

    # T08: gerçek case_0001 verisi self-test boyunca HİÇ değişmedi.
    real_after = orchestrator_engine.build_case_view(case_id)

    real_stripped = _strip_volatile(real)
    real_after_stripped = _strip_volatile(real_after)

    assert real_stripped == real_after_stripped, "Self-test sırasında gerçek case_0001 canonical verisi (dolaylı olarak) değişti."

    print("T08 Self-test boyunca gerçek case_0001 canonical verisi değişmedi:", "PASS")

    print()
    print("======================================")
    print(" ORCHESTRATOR VALIDATOR V1: 8/8 SELF-TEST PASS")
    print("======================================")


if __name__ == "__main__":

    import sys

    if "--self-test" in sys.argv:

        run_self_test()

    else:

        print("orchestrator_validator.py - bkz. --self-test.")
