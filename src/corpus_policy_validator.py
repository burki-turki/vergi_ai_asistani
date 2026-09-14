# ============================================================
# VERGİ AI - CORPUS POLICY VALIDATOR V1.
#
# AMAÇ:
#
# data/corpus_policy/corpus_policy.json içindeki mevzuat/içtihat
# corpus politikasını (source authority tiers, belge ailesi
# admission/provenance kuralları, quality gate registry, security/
# temporal/update/governance kuralları):
#
# 1. JSON Schema
# 2. Kapalı sözlük (closed vocabulary) tutarlılığı
# 3. belge_turu ailesi ile documents.schema.json arasında drift
# 4. Aile içi iç tutarlılık (admission <-> tier <-> prerequisites)
# 5. quality_gates gate_id tekilliği
# 6. required_provenance_fields'in documents.schema.json'da GERÇEKTEN
#    var olan alan adlarına karşılık gelmesi
#
# açısından doğrulamak.
#
#
# KRİTİK PRENSİP:
#
# Bu validator policy İÇERİĞİNİN hukuken doğru olduğunu KANITLAMAZ.
#
# Yalnız policy artefaktının kendi içinde tutarlı, kapalı-sözlüklü ve
# documents.schema.json ile drift'siz olmasını sağlar.
#
#
# BİLİNÇLİ SAPMA (deadline_rule_validator.py emsalinden):
#
# run_self_test() fixture'larını `data/`'nin altındaki kalıcı bir
# dizine DEĞİL, `tempfile.TemporaryDirectory()`'ye yazar - gerçek
# `data/` ağacına hiçbir self-test koşusu dokunmaz.
#
#
# load_policy() bu modülün DIŞINDAKİ modüller (manifest_validator.py,
# provision_manifest_validator.py) tarafından da import edilir - saf,
# yan etkisiz bir JSON yükleyicidir, kendi başına doğrulama YAPMAZ.
# ============================================================


import argparse
import json
import sys

from pathlib import Path

from jsonschema import (
    Draft202012Validator,
    FormatChecker,
)


# ============================================================
# VERSION
# ============================================================

CORPUS_POLICY_VALIDATOR_VERSION = "1"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

DATA_DIR = (
    BASE_DIR
    / "data"
)

CORPUS_POLICY_SCHEMA_PATH = (
    DATA_DIR
    / "corpus_policy.schema.json"
)

CORPUS_POLICY_PATH = (
    DATA_DIR
    / "corpus_policy"
    / "corpus_policy.json"
)

DOCUMENTS_SCHEMA_PATH = (
    DATA_DIR
    / "documents.schema.json"
)


# ============================================================
# EXCEPTION
# ============================================================

class CorpusPolicyValidationError(Exception):
    pass


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path):

    path = Path(path)

    if not path.exists():

        raise FileNotFoundError(
            f"JSON dosyası bulunamadı:\n{path}"
        )

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


def load_policy(path=None):
    """Saf, yan etkisiz yükleyici - şema/iş-kuralı doğrulaması YAPMAZ.
    `path=None` iken gerçek, repo-committed CORPUS_POLICY_PATH'i
    yükler. `manifest_validator.py`/`provision_manifest_validator.py`
    bu fonksiyonu kendi (varsayılan, her zaman GERÇEK committed
    policy'ye işaret eden) çağrılarında kullanır - bu modülün
    CORPUS_POLICY_PATH sabiti test amaçlı monkeypatch edilebilir
    (diğer src/*.py modüllerinin DATA_DIR/MEVZUAT_DIR sabitleriyle
    aynı, yerleşik konvansiyon)."""

    return load_json(path or CORPUS_POLICY_PATH)


# ============================================================
# SCHEMA
# ============================================================

def validate_schema(policy):

    schema = load_json(CORPUS_POLICY_SCHEMA_PATH)

    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    errors = sorted(
        validator.iter_errors(policy),
        key=lambda error: list(error.absolute_path),
    )

    messages = []

    for error in errors:

        path = ".".join(
            str(part) for part in error.absolute_path
        )

        if path:

            messages.append(f"{path}: {error.message}")

        else:

            messages.append(error.message)

    return messages


# ============================================================
# documents.schema.json CROSS-CHECKS
# ============================================================

def known_belge_turu_values():

    schema = load_json(DOCUMENTS_SCHEMA_PATH)

    return set(
        schema["$defs"]["document"]["properties"]["belge_turu"]["enum"]
    )


def known_document_field_names():

    schema = load_json(DOCUMENTS_SCHEMA_PATH)

    return set(
        schema["$defs"]["document"]["properties"].keys()
    )


def validate_belge_turu_family_drift(policy):

    errors = []

    known = known_belge_turu_values()

    declared = set(
        (policy.get("document_family_rules") or {}).keys()
    )

    missing_in_policy = known - declared

    extra_in_policy = declared - known

    if missing_in_policy:

        errors.append(
            "belge_turu ailesi drift: documents.schema.json'da olup "
            "policy document_family_rules'da olmayan değerler: "
            f"{sorted(missing_in_policy)}"
        )

    if extra_in_policy:

        errors.append(
            "belge_turu ailesi drift: policy document_family_rules'da "
            "olup documents.schema.json belge_turu enum'unda olmayan "
            f"değerler: {sorted(extra_in_policy)}"
        )

    return errors


def validate_provenance_field_names(policy):

    errors = []

    known_fields = known_document_field_names()

    family_rules = policy.get("document_family_rules") or {}

    for family_name, rule in sorted(family_rules.items()):

        if not isinstance(rule, dict):

            continue

        for field_name in rule.get("required_provenance_fields", []) or []:

            if field_name not in known_fields:

                errors.append(
                    f"document_family_rules.{family_name}: "
                    "required_provenance_fields içinde documents."
                    f"schema.json'da tanımlı olmayan alan adı: "
                    f"{field_name}"
                )

    return errors


# ============================================================
# FAMILY INTERNAL CONSISTENCY
# ============================================================

def validate_family_consistency(policy):

    errors = []

    family_rules = policy.get("document_family_rules") or {}

    for family_name, rule in sorted(family_rules.items()):

        if not isinstance(rule, dict):

            continue

        admission = rule.get("admission")

        tier = rule.get("tier")

        prerequisites = rule.get("prerequisites") or []

        if admission == "allowed" and prerequisites:

            errors.append(
                f"document_family_rules.{family_name}: "
                "admission='allowed' ama prerequisites boş değil "
                f"({prerequisites}) - çelişen kural."
            )

        if admission == "deferred" and not prerequisites:

            errors.append(
                f"document_family_rules.{family_name}: "
                "admission='deferred' ama prerequisites boş - "
                "erteleme gerekçesi (population kuralı) tanımlı değil."
            )

        if admission == "prohibited" and tier is not None:

            errors.append(
                f"document_family_rules.{family_name}: "
                "admission='prohibited' ama tier atanmış "
                f"({tier}) - çelişen kural."
            )

    return errors


# ============================================================
# QUALITY GATE UNIQUENESS
# ============================================================

def validate_gate_uniqueness(policy):

    errors = []

    seen = set()

    for gate in policy.get("quality_gates") or []:

        if not isinstance(gate, dict):

            continue

        gate_id = gate.get("gate_id")

        if gate_id in seen:

            errors.append(
                f"quality_gates: duplicate gate_id: {gate_id}"
            )

        seen.add(gate_id)

    return errors


# ============================================================
# SOURCE AUTHORITY TIER UNIQUENESS
# ============================================================

def validate_tier_values_used(policy):

    errors = []

    seen = set()

    for entry in policy.get("source_authority_tiers") or []:

        if not isinstance(entry, dict):

            continue

        tier = entry.get("tier")

        if tier in seen:

            errors.append(
                f"source_authority_tiers: duplicate tier: {tier}"
            )

        seen.add(tier)

    return errors


# ============================================================
# MAIN VALIDATION
# ============================================================

def validate_corpus_policy(policy=None, raise_on_error=False):

    if policy is None:

        policy = load_policy()

    errors = []

    warnings = []

    # ========================================================
    # SCHEMA
    # ========================================================

    errors.extend(validate_schema(policy))

    # Schema başarısızsa (örn. gerekli anahtar eksik) iç tutarlılık
    # kontrolleri KeyError riski taşır - manifest_validator.py'nin
    # kendi validate_manifest_file() emsaliyle AYNI fail-fast deseni.
    if not errors:

        errors.extend(validate_belge_turu_family_drift(policy))

        errors.extend(validate_provenance_field_names(policy))

        errors.extend(validate_family_consistency(policy))

        errors.extend(validate_gate_uniqueness(policy))

        errors.extend(validate_tier_values_used(policy))

    errors = list(dict.fromkeys(errors))

    warnings = list(dict.fromkeys(warnings))

    valid = len(errors) == 0

    result = {
        "valid": valid,
        "validator_version": CORPUS_POLICY_VALIDATOR_VERSION,
        "policy_id": policy.get("policy_id"),
        "policy_version": policy.get("policy_version"),
        "family_count": len(policy.get("document_family_rules") or {}),
        "gate_count": len(policy.get("quality_gates") or []),
        "errors": errors,
        "warnings": warnings,
    }

    if raise_on_error and errors:

        raise CorpusPolicyValidationError(
            "CORPUS POLICY VALIDATOR V1: FAIL\n\n- "
            + "\n- ".join(errors)
        )

    return result


# ============================================================
# TEST FIXTURE
# ============================================================

def create_valid_fixture():

    return {
        "schema_version": 1,
        "policy_id": "vergi_ai_corpus_policy_v1",
        "policy_version": 1,
        "effective_from": "2026-01-01",
        "source_authority_tiers": [
            {
                "tier": 1,
                "name": "resmi_gazete",
                "description": "Fixture tier 1.",
            },
        ],
        "document_family_rules": {
            "Kanun": {
                "admission": "allowed",
                "tier": 1,
                "required_provenance_fields": ["source_url"],
                "temporal_sensitive": True,
                "prerequisites": [],
                "notes": None,
            },
            "Bakanlar Kurulu Kararı": {
                "admission": "allowed",
                "tier": 1,
                "required_provenance_fields": [],
                "temporal_sensitive": True,
                "prerequisites": [],
                "notes": None,
            },
            "Cumhurbaşkanı Kararı": {
                "admission": "allowed",
                "tier": 1,
                "required_provenance_fields": [],
                "temporal_sensitive": True,
                "prerequisites": [],
                "notes": None,
            },
            "Yönetmelik": {
                "admission": "allowed",
                "tier": 1,
                "required_provenance_fields": [],
                "temporal_sensitive": True,
                "prerequisites": [],
                "notes": None,
            },
            "Genel Tebliğ": {
                "admission": "allowed",
                "tier": 2,
                "required_provenance_fields": [],
                "temporal_sensitive": True,
                "prerequisites": [],
                "notes": None,
            },
            "Tebliğ": {
                "admission": "allowed",
                "tier": 2,
                "required_provenance_fields": [],
                "temporal_sensitive": True,
                "prerequisites": [],
                "notes": None,
            },
            "Sirküler": {
                "admission": "deferred",
                "tier": None,
                "required_provenance_fields": [],
                "temporal_sensitive": False,
                "prerequisites": ["fixture_prerequisite"],
                "notes": None,
            },
            "Özelge": {
                "admission": "deferred",
                "tier": None,
                "required_provenance_fields": [],
                "temporal_sensitive": False,
                "prerequisites": ["fixture_prerequisite"],
                "notes": None,
            },
            "Yargı Kararı": {
                "admission": "deferred",
                "tier": None,
                "required_provenance_fields": [],
                "temporal_sensitive": False,
                "prerequisites": ["fixture_prerequisite"],
                "notes": None,
            },
            "Diğer": {
                "admission": "prohibited",
                "tier": None,
                "required_provenance_fields": [],
                "temporal_sensitive": False,
                "prerequisites": [],
                "notes": None,
            },
        },
        "quality_gates": [
            {
                "gate_id": "fixture_gate",
                "enforcement_stage": "policy_foundation",
                "outcome": "reject",
                "threshold": None,
            },
        ],
        "security_rules": {
            "rag_prompt_boundary_required_before_population": True,
            "anonymization_required_for": ["Özelge"],
            "path_containment_required_for_acquisition_writers": True,
            "notes": None,
        },
        "temporal_requirements": {
            "current_law_only": True,
            "valid_from_requires_originating_evidence": True,
            "originating_evidence_kinds": ["statute_text", "amending_law"],
            "cross_version_interval_check_enabled": True,
            "text_basis_declaration": "editorially_consolidated_current",
            "notes": None,
        },
        "update_rules": {
            "manual_curation_only": True,
            "in_place_overwrite_prohibited": True,
            "build_requires_human_approval": True,
            "activate_requires_human_approval": True,
            "automated_crawler_fetch_enabled": False,
            "notes": None,
        },
        "governance": {
            "capability_model": "fixture capability model",
            "policy_change_approval": "fixture approval rule",
            "four_eyes_required_in_pilot": False,
            "emergency_rollback_procedure": "fixture rollback procedure",
            "notes": None,
        },
        "notes": "Corpus Policy Validator V1 self-test fixture. Gerçek policy değildir.",
    }


# ============================================================
# SELF TEST
# ============================================================

def run_self_test():

    print()
    print("======================================")
    print(" VERGİ AI - CORPUS POLICY VALIDATOR V1")
    print("======================================")

    # ========================================================
    # T01 SCHEMA FILE EXISTS
    # ========================================================

    assert CORPUS_POLICY_SCHEMA_PATH.exists()

    load_json(CORPUS_POLICY_SCHEMA_PATH)

    print("T01 Corpus policy schema load: PASS")

    # ========================================================
    # T02 VALID FIXTURE (in-memory)
    # ========================================================

    fixture = create_valid_fixture()

    result = validate_corpus_policy(policy=fixture)

    if not result["valid"]:

        for error in result["errors"]:

            print("-", error)

    assert result["valid"] is True

    print("T02 Valid fixture policy: PASS")

    # ========================================================
    # T03 CROSS-VALIDATE AGAINST create_valid_fixture()-INDEPENDENT
    # GOLDEN FIXTURE (totoloji kırıcı - deadline_rule_validator
    # emsalinden farklı olarak, create_valid_fixture()'ın kendi
    # yapısına GÜVENMEYEN, elle yazılmış minimal ikinci bir fixture).
    # ========================================================

    golden = {
        "schema_version": 1,
        "policy_id": "vergi_ai_corpus_policy_v1",
        "policy_version": 1,
        "effective_from": "2026-01-01",
        "source_authority_tiers": [
            {"tier": 1, "name": "t1", "description": "d1"},
            {"tier": 2, "name": "t2", "description": "d2"},
        ],
        "document_family_rules": {
            name: {
                "admission": "prohibited",
                "tier": None,
                "required_provenance_fields": [],
                "temporal_sensitive": False,
                "prerequisites": [],
                "notes": None,
            }
            for name in known_belge_turu_values()
        },
        "quality_gates": [
            {"gate_id": "g1", "enforcement_stage": "policy_foundation", "outcome": "reject", "threshold": None},
        ],
        "security_rules": {
            "rag_prompt_boundary_required_before_population": False,
            "anonymization_required_for": [],
            "path_containment_required_for_acquisition_writers": False,
            "notes": None,
        },
        "temporal_requirements": {
            "current_law_only": True,
            "valid_from_requires_originating_evidence": False,
            "originating_evidence_kinds": ["statute_text"],
            "cross_version_interval_check_enabled": False,
            "text_basis_declaration": "as_published_original",
            "notes": None,
        },
        "update_rules": {
            "manual_curation_only": True,
            "in_place_overwrite_prohibited": True,
            "build_requires_human_approval": True,
            "activate_requires_human_approval": True,
            "automated_crawler_fetch_enabled": False,
            "notes": None,
        },
        "governance": {
            "capability_model": "golden",
            "policy_change_approval": "golden",
            "four_eyes_required_in_pilot": True,
            "emergency_rollback_procedure": "golden",
            "notes": None,
        },
        "notes": None,
    }

    golden_result = validate_corpus_policy(policy=golden)

    assert golden_result["valid"] is True, golden_result["errors"]

    print("T03 Independent golden fixture (all-prohibited families): PASS")

    # ========================================================
    # T04 REAL, REPO-COMMITTED POLICY VALIDATES CLEANLY
    # ========================================================

    real_result = validate_corpus_policy()

    if not real_result["valid"]:

        for error in real_result["errors"]:

            print("-", error)

    assert real_result["valid"] is True

    print("T04 Real committed corpus_policy.json: PASS")

    # ========================================================
    # T05 UNKNOWN belge_turu KEY REJECTED (closed vocabulary)
    # ========================================================

    import copy

    broken = copy.deepcopy(fixture)

    broken["document_family_rules"]["Bilinmeyen Tur"] = broken["document_family_rules"].pop("Diğer")

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T05 Unknown belge_turu key blocked: PASS")

    # ========================================================
    # T06 UNKNOWN admission VALUE REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["document_family_rules"]["Kanun"]["admission"] = "maybe"

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T06 Unknown admission value blocked: PASS")

    # ========================================================
    # T07 UNKNOWN enforcement_stage VALUE REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["quality_gates"][0]["enforcement_stage"] = "sometime"

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T07 Unknown enforcement_stage value blocked: PASS")

    # ========================================================
    # T08 UNKNOWN outcome VALUE REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["quality_gates"][0]["outcome"] = "warn"

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T08 Unknown outcome value blocked: PASS")

    # ========================================================
    # T09 belge_turu DRIFT (missing family) REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    del broken["document_family_rules"]["Diğer"]

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T09 belge_turu drift (missing family) blocked: PASS")

    # ========================================================
    # T10 SEMANTIC CONFLICT: admission=allowed WITH prerequisites
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["document_family_rules"]["Kanun"]["prerequisites"] = ["should_not_be_here"]

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T10 admission=allowed with non-empty prerequisites blocked: PASS")

    # ========================================================
    # T11 SEMANTIC CONFLICT: admission=prohibited WITH tier
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["document_family_rules"]["Diğer"]["tier"] = 1

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T11 admission=prohibited with assigned tier blocked: PASS")

    # ========================================================
    # T12 SEMANTIC CONFLICT: admission=deferred WITHOUT prerequisites
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["document_family_rules"]["Sirküler"]["prerequisites"] = []

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T12 admission=deferred without prerequisites blocked: PASS")

    # ========================================================
    # T13 DUPLICATE gate_id REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["quality_gates"].append(dict(broken["quality_gates"][0]))

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T13 Duplicate quality_gates gate_id blocked: PASS")

    # ========================================================
    # T14 UNKNOWN required_provenance_fields VALUE REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["document_family_rules"]["Kanun"]["required_provenance_fields"] = ["not_a_real_document_field"]

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T14 Unknown required_provenance_fields entry blocked: PASS")

    # ========================================================
    # T15 DUPLICATE source_authority_tiers.tier REJECTED
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["source_authority_tiers"].append({"tier": 1, "name": "dup", "description": "dup"})

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T15 Duplicate source_authority_tiers.tier blocked: PASS")

    # ========================================================
    # T16 additionalProperties:false AT ROOT
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["unknown_top_level_field"] = "nope"

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T16 Unknown top-level field blocked (root additionalProperties:false): PASS")

    # ========================================================
    # T17 additionalProperties:false INSIDE document_family_rule
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["document_family_rules"]["Kanun"]["unknown_nested_field"] = "nope"

    result = validate_corpus_policy(policy=broken)

    assert result["valid"] is False

    print("T17 Unknown nested field blocked (document_family_rule additionalProperties:false): PASS")

    # ========================================================
    # T18 DISK LOAD PATH - tempdir-isolated, real data/ untouched
    # ========================================================

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:

        tmp_path = Path(tmp) / "disk_fixture_corpus_policy.json"

        with open(tmp_path, "w", encoding="utf-8") as file:

            json.dump(fixture, file, ensure_ascii=False)

        loaded = load_policy(tmp_path)

        disk_result = validate_corpus_policy(policy=loaded)

        assert disk_result["valid"] is True, disk_result["errors"]

    print("T18 Disk-loaded fixture (tempdir-isolated) validates: PASS")

    # ========================================================
    # T19 MISSING POLICY FILE FAILS CLOSED
    # ========================================================

    with tempfile.TemporaryDirectory() as tmp:

        missing_path = Path(tmp) / "does_not_exist.json"

        try:

            load_policy(missing_path)

            raised = False

        except FileNotFoundError:

            raised = True

        assert raised is True

    print("T19 Missing policy file fails closed (FileNotFoundError): PASS")

    # ========================================================
    # T20 raise_on_error=True RAISES CorpusPolicyValidationError
    # ========================================================

    broken = copy.deepcopy(fixture)

    broken["document_family_rules"]["Kanun"]["admission"] = "maybe"

    try:

        validate_corpus_policy(policy=broken, raise_on_error=True)

        raised = False

    except CorpusPolicyValidationError:

        raised = True

    assert raised is True

    print("T20 raise_on_error=True raises CorpusPolicyValidationError: PASS")

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print("Policy:", real_result["policy_id"])
    print("Family count:", real_result["family_count"])
    print("Gate count:", real_result["gate_count"])
    print()
    print("======================================")
    print(" CORPUS POLICY VALIDATOR V1: 20/20 PASS")
    print("======================================")


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="Vergi AI Corpus Policy Validator V1"
    )

    parser.add_argument(
        "--policy",
        dest="policy_path",
        default=None,
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        dest="self_test",
    )

    args = parser.parse_args()

    if args.self_test or args.policy_path is None:

        run_self_test()

        return

    print()
    print("======================================")
    print(" VERGİ AI - CORPUS POLICY VALIDATOR V1")
    print("======================================")

    try:

        policy = load_policy(Path(args.policy_path))

        result = validate_corpus_policy(policy=policy, raise_on_error=False)

    except Exception as error:

        print()
        print("VALIDATION ERROR")
        print(error)
        print()
        print("======================================")
        print(" CORPUS POLICY VALIDATOR V1: FAIL")
        print("======================================")

        sys.exit(1)

    print()
    print("Policy:", result["policy_id"])
    print("Family count:", result["family_count"])
    print("Gate count:", result["gate_count"])

    if result["errors"]:

        print()
        print("Errors:")

        for error in result["errors"]:

            print("-", error)

    print()
    print("======================================")

    if result["valid"]:

        print(" CORPUS POLICY VALIDATOR V1: PASS")

    else:

        print(" CORPUS POLICY VALIDATOR V1: FAIL")

        sys.exit(1)

    print("======================================")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    main()
