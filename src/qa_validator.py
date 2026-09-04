# ============================================================
# VERGİ AI - QA VALIDATOR V1 (Row 16)
#
# BAĞIMSIZ DOĞRULAMA: motorun kendi qa_result değerlerine
# GÜVENMEZ - AYNI saf check fonksiyonlarını (qa_engine) YENİDEN
# ÇAĞIRIR ve kayıtlı sonuçla KARŞILAŞTIRIR. Gerçek bir upstream
# 'failed' bulgusu, doğru şekilde kaydedildiği sürece QA raporunun
# KENDİSİNİ ASLA geçersiz kılmaz - yalnız kaydın kendisiyle
# BAĞIMSIZ yeniden üretim ARASINDAKİ tutarsızlık geçersiz kılar.
# ============================================================

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from qa_discovery import BASE_DIR, DATA_DIR, read_artifact_bytes
from qa_policy import sha256_of_bytes, QA_SCOPE_REGISTRY, QA_CHECK_REGISTRY
import qa_engine


QA_SCHEMA_PATH = DATA_DIR / "case_qa.schema.json"


def load_json(path):

    with open(path, encoding="utf-8") as file:

        return json.load(file)


def validate_schema(analysis):

    schema = load_json(QA_SCHEMA_PATH)

    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    return [f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in validator.iter_errors(analysis)]


def validate_case_id(analysis, expected_case_id):

    if expected_case_id is None:

        return []

    if analysis.get("case_id") != expected_case_id:

        return [f"case_id uyuşmuyor: beklenen={expected_case_id}, kayıtlı={analysis.get('case_id')}"]

    return []


def validate_generated_at(analysis):

    if not isinstance(analysis.get("generated_at"), str) or not analysis["generated_at"]:

        return ["generated_at eksik/geçersiz."]

    return []


def check_snapshot_freshness(analysis):
    """
    Kayıtlı dependency_manifest'in raw_byte_sha256 değerlerini GÜNCEL
    dosyalarla karşılaştırır. Uyuşmazlık varsa bu 'STALE' (tahrifat
    DEĞİL, yeniden tarama gerekli) olarak sınıflandırılır - ayrı bir
    hata sınıfı, "tampered/fabricated" ile AYNI dille SUÇLANMAZ.
    """

    manifest = analysis.get("analysis_metadata", {}).get("dependency_manifest", [])
    stale_refs = []

    for entry in manifest:

        ref = entry.get("artifact_ref")

        if ref == "case.json":

            path = BASE_DIR / "data" / "cases" / analysis.get("case_id", "") / "case.json"

        elif ":" in ref:

            scope, member = ref.split(":", 1)

            from qa_discovery import get_document_path, get_facts_path

            case_id = analysis.get("case_id", "")

            path = get_document_path(case_id, member) if scope == "documents" else get_facts_path(case_id, member)

        else:

            from qa_discovery import get_single_file_scope_path

            path = get_single_file_scope_path(ref, analysis.get("case_id", ""))

        raw_bytes, state = read_artifact_bytes(path)

        current_sha256 = sha256_of_bytes(raw_bytes) if raw_bytes is not None else None

        if current_sha256 != entry.get("raw_byte_sha256"):

            stale_refs.append(ref)

    return stale_refs


def _check_result_key(record):

    return (record["check_id"], record["scope_id"], record.get("member_id"))


def validate_deterministic_results_independently(analysis, expected_case_id):
    """
    qa_engine.build_qa_engine_output()'u YENİDEN çağırır (AYNI saf
    check fonksiyonları - motorun kendi hesapladığı değere GÜVENİLMEZ)
    ve kayıtlı qa_check_results ile TEK TEK karşılaştırır.
    """

    errors = []

    fresh = qa_engine.build_qa_engine_output(expected_case_id)

    fresh_by_key = {_check_result_key(r): r for r in fresh["qa_check_results"]}
    recorded_by_key = {}

    for record in analysis.get("qa_check_results", []):

        key = _check_result_key(record)

        if key in recorded_by_key:

            errors.append(f"Duplicate check_result (aynı check_id/scope_id/member_id): {key}")

            continue

        recorded_by_key[key] = record

    for key, fresh_record in fresh_by_key.items():

        recorded_record = recorded_by_key.get(key)

        if recorded_record is None:

            errors.append(f"Eksik check_result (beklenen instance rapor edilmemiş): {key}")

            continue

        if recorded_record["qa_result"] != fresh_record["qa_result"]:

            errors.append(
                f"{key}: kayıtlı qa_result ({recorded_record['qa_result']!r}) bağımsız yeniden "
                f"hesaplamayla ({fresh_record['qa_result']!r}) EŞLEŞMİYOR - tahrif edilmiş veya "
                "uydurma sonuç şüphesi."
            )

    for key in recorded_by_key:

        if key not in fresh_by_key:

            errors.append(f"Fazladan/tanınmayan check_result (registry'de kayıtlı değil): {key}")

    # Coverage - bağımsız yeniden hesaplanan qa_coverage ile karşılaştır.
    fresh_coverage_by_scope = {c["scope_id"]: c for c in fresh["qa_coverage"]}
    recorded_coverage_by_scope = {c["scope_id"]: c for c in analysis.get("qa_coverage", [])}

    if len(recorded_coverage_by_scope) != len(QA_SCOPE_REGISTRY):

        errors.append(f"qa_coverage tam 11 scope içermiyor (kayıtlı={len(recorded_coverage_by_scope)}).")

    for scope_id in QA_SCOPE_REGISTRY:

        fresh_c = fresh_coverage_by_scope.get(scope_id)
        recorded_c = recorded_coverage_by_scope.get(scope_id)

        if recorded_c is None:

            errors.append(f"qa_coverage'da eksik scope: {scope_id}")

            continue

        for field in ("artifact_state", "required", "member_enumeration_state", "expected_member_count"):

            if recorded_c.get(field) != fresh_c.get(field):

                errors.append(
                    f"qa_coverage[{scope_id}].{field}: kayıtlı={recorded_c.get(field)!r} "
                    f"bağımsız={fresh_c.get(field)!r} eşleşmiyor."
                )

    return errors, fresh


def validate_generation_status_consistency(analysis):

    errors = []

    results = analysis.get("qa_check_results", [])

    error_count = sum(1 for r in results if r["qa_result"] == "error")
    not_run_count = sum(1 for r in results if r["qa_result"] == "not_run")

    status = analysis.get("qa_generation_status")

    if status == "completed" and (error_count > 0 or not_run_count > 0):

        errors.append(
            f"qa_generation_status='completed' ama error={error_count}, not_run={not_run_count} "
            "(tutarsız - completed_with_errors/aborted_source_changed olmalıydı)."
        )

    if status == "completed_with_errors" and (error_count == 0 or not_run_count > 0):

        errors.append(
            f"qa_generation_status='completed_with_errors' ama error={error_count}, "
            f"not_run={not_run_count} (tutarsız)."
        )

    post_comparison = analysis.get("analysis_metadata", {}).get("post_scan_manifest_comparison", {})

    if status == "aborted_source_changed" and post_comparison.get("consistent") is True:

        errors.append("qa_generation_status='aborted_source_changed' ama post_scan_manifest_comparison.consistent=True (tutarsız).")

    return errors


def validate_qa_analysis(qa_path, expected_case_id=None, raise_on_error=False):

    analysis = load_json(qa_path)

    errors = []

    errors.extend(validate_schema(analysis))
    errors.extend(validate_case_id(analysis, expected_case_id))
    errors.extend(validate_generated_at(analysis))
    errors.extend(validate_generation_status_consistency(analysis))

    case_id = expected_case_id or analysis.get("case_id")

    stale_refs = check_snapshot_freshness(analysis)

    if stale_refs:

        errors.append(
            f"STALE SNAPSHOT (tahrifat DEĞİL - yeniden tarama gerekli): raporun kaydettiği "
            f"anlık görüntü güncel dosyalarla eşleşmiyor: {stale_refs}"
        )

    else:

        det_errors, _fresh = validate_deterministic_results_independently(analysis, case_id)
        errors.extend(det_errors)

    result = {"valid": len(errors) == 0, "errors": errors, "case_id": analysis.get("case_id")}

    if raise_on_error and errors:

        raise ValueError("\nQA VALIDATION HATASI\n" + "\n".join(f"- {e}" for e in errors))

    return result


def run_self_test():

    import copy
    import tempfile

    print()
    print("======================================")
    print(" VERGİ AI - QA VALIDATOR V1 (SELF-TEST)")
    print("======================================")

    case_id = "case_0001"

    real = qa_engine.build_qa_engine_output(case_id)

    def write_and_validate(analysis):

        with tempfile.TemporaryDirectory(prefix="qa_validator_selftest_") as td:

            p = Path(td) / "qa_test.json"

            with open(p, "w", encoding="utf-8") as f:

                json.dump(analysis, f, ensure_ascii=False)

            return validate_qa_analysis(p, expected_case_id=case_id)

    # T01: genuine, untampered rapor -> PASS (gerçek 'blocked' bulgular İÇEREBİLİR)
    v1 = write_and_validate(real)

    assert v1["valid"] is True

    has_non_passed = any(r["qa_result"] != "passed" for r in real["qa_check_results"])

    assert has_non_passed, "Test fixture varsayımı geçersiz - gerçek raporda non-passed sonuç yok."

    print("T01 Genuine rapor (içinde GERÇEK blocked bulgular VAR) validator PASS verdi:", "PASS")

    # T02: passed -> failed tahrifat
    t2 = copy.deepcopy(real)

    for r in t2["qa_check_results"]:

        if r["qa_result"] == "passed":

            r["qa_result"] = "failed"

            break

    v2 = write_and_validate(t2)

    assert v2["valid"] is False

    print("T02 Tahrif edilmiş passed->failed reddedildi:", "PASS")

    # T03: failed/blocked -> passed tahrifat (bulguyu gizleme girişimi)
    t3 = copy.deepcopy(real)

    for r in t3["qa_check_results"]:

        if r["qa_result"] == "blocked":

            r["qa_result"] = "passed"

            break

    v3 = write_and_validate(t3)

    assert v3["valid"] is False

    print("T03 Tahrif edilmiş blocked->passed (bulgu gizleme) reddedildi:", "PASS")

    # T04: check_result tamamen ÇIKARILMIŞ (omitted not_applicable/diğer)
    t4 = copy.deepcopy(real)

    t4["qa_check_results"] = t4["qa_check_results"][1:]

    v4 = write_and_validate(t4)

    assert v4["valid"] is False

    print("T04 Eksik/atlanmış check_result reddedildi:", "PASS")

    # T05: sayaç/coverage tahrifatı (qa_coverage'dan bir scope silinmiş)
    t5 = copy.deepcopy(real)

    t5["qa_coverage"] = t5["qa_coverage"][1:]

    v5 = write_and_validate(t5)

    assert v5["valid"] is False

    print("T05 Eksik qa_coverage scope'u reddedildi:", "PASS")

    # T06: STALE snapshot (tahrifat DEĞİL) - manifest sha256 elle bozulmuş
    t6 = copy.deepcopy(real)

    t6["analysis_metadata"]["dependency_manifest"][0]["raw_byte_sha256"] = "0" * 64

    v6 = write_and_validate(t6)

    assert v6["valid"] is False
    assert any("STALE SNAPSHOT" in e for e in v6["errors"])

    print("T06 Stale snapshot ayrı bir hata sınıfıyla (tahrifat DENMEDEN) tespit edildi:", "PASS")

    # T07: generation_status tutarsızlığı (completed ama error var)
    t7 = copy.deepcopy(real)

    t7["qa_check_results"][0]["qa_result"] = "error"

    t7["qa_generation_status"] = "completed"

    v7 = write_and_validate(t7)

    assert v7["valid"] is False

    print("T07 qa_generation_status='completed' ama error mevcut - tutarsızlık reddedildi:", "PASS")

    # T08: schema ihlali (additionalProperties)
    t8 = copy.deepcopy(real)

    t8["unexpected_extra_field"] = "x"

    v8 = write_and_validate(t8)

    assert v8["valid"] is False

    print("T08 Şema ihlali (bilinmeyen alan) reddedildi:", "PASS")

    # T09: gerçek case_0001 hiçbir şekilde mutate edilmedi (yalnız okuma)
    real_after = qa_engine.build_qa_engine_output(case_id)

    assert real_after["qa_check_results"] == real["qa_check_results"]

    print("T09 Self-test boyunca gerçek case_0001 canonical verisi değişmedi:", "PASS")

    print()
    print("======================================")
    print(" QA VALIDATOR V1: 9/9 SELF-TEST PASS")
    print("======================================")


if __name__ == "__main__":

    import sys

    if "--self-test" in sys.argv:

        run_self_test()

    else:

        print("qa_validator.py - bkz. --self-test.")
