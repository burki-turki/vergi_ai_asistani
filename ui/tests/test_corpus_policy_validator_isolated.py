# ============================================================
# CORPUS POLICY FOUNDATION - isolated tests for
# src/corpus_policy_validator.py: kalıcı, non-tautological kanıt evi.
#
# Bu dosya corpus_policy_validator.py'nin KENDİ run_self_test()'inden
# (T01-T20, modülün kendi içinde) AYRIDIR - bu dosya modülün public
# API'sini `ui/tests/` katmanından, repo'nun standart check()-sayaçlı
# konvansiyonuyla, tempdir-izoleli olarak dener; hiçbir gerçek data/
# ağacına yazmaz.
#
# Run: python -m ui.tests.test_corpus_policy_validator_isolated
# ============================================================

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import corpus_policy_validator as cpv  # noqa: E402
import ingest  # noqa: E402

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


def expect_raises(exc_type, fn, label, detail=""):
    try:
        fn()
    except exc_type:
        check(label, True)
    except Exception as error:
        check(label, False, f"{detail} - unexpected exception: {type(error).__name__}: {error!r}")
    else:
        check(label, False, f"{detail} - no exception raised")


# ================================================================
# SCHEMA VALID/INVALID
# ================================================================

def test_valid_fixture_schema_and_business_rules_pass():
    fixture = cpv.create_valid_fixture()
    result = cpv.validate_corpus_policy(policy=fixture)
    check("valid fixture: schema+business-rules pass", result["valid"] is True, result["errors"])
    check("valid fixture: errors list empty", result["errors"] == [])


def test_real_committed_policy_validates_cleanly():
    result = cpv.validate_corpus_policy()
    check("real committed corpus_policy.json: valid", result["valid"] is True, result["errors"])
    check("real committed corpus_policy.json: policy_id matches", result["policy_id"] == "vergi_ai_corpus_policy_v1")
    check("real committed corpus_policy.json: family_count == 10", result["family_count"] == 10, result["family_count"])


def test_missing_required_top_level_field_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    del fixture["policy_version"]
    result = cpv.validate_corpus_policy(policy=fixture)
    check("missing required top-level field (policy_version) rejected", result["valid"] is False)


def test_wrong_schema_version_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["schema_version"] = 2
    result = cpv.validate_corpus_policy(policy=fixture)
    check("schema_version != 1 (const violation) rejected", result["valid"] is False)


def test_wrong_policy_id_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["policy_id"] = "some_other_policy_id"
    result = cpv.validate_corpus_policy(policy=fixture)
    check("wrong policy_id (const violation) rejected", result["valid"] is False)


def test_policy_version_below_minimum_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["policy_version"] = 0
    result = cpv.validate_corpus_policy(policy=fixture)
    check("policy_version < 1 rejected", result["valid"] is False)


# ================================================================
# additionalProperties:false - ROOT AND NESTED
# ================================================================

def test_unknown_root_field_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["unexpected_root_field"] = True
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown root-level field rejected (root additionalProperties:false)", result["valid"] is False)


def test_unknown_document_family_rule_field_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["document_family_rules"]["Kanun"]["unexpected_field"] = True
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown document_family_rule field rejected (nested additionalProperties:false)", result["valid"] is False)


def test_unknown_quality_gate_field_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["quality_gates"][0]["unexpected_field"] = True
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown quality_gate field rejected (nested additionalProperties:false)", result["valid"] is False)


def test_unknown_source_authority_tier_field_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["source_authority_tiers"][0]["unexpected_field"] = True
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown source_authority_tier field rejected (nested additionalProperties:false)", result["valid"] is False)


def test_unknown_security_rules_field_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["security_rules"]["unexpected_field"] = True
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown security_rules field rejected (nested additionalProperties:false)", result["valid"] is False)


def test_unknown_temporal_requirements_field_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["temporal_requirements"]["unexpected_field"] = True
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown temporal_requirements field rejected (nested additionalProperties:false)", result["valid"] is False)


def test_unknown_update_rules_field_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["update_rules"]["unexpected_field"] = True
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown update_rules field rejected (nested additionalProperties:false)", result["valid"] is False)


def test_unknown_governance_field_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["governance"]["unexpected_field"] = True
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown governance field rejected (nested additionalProperties:false)", result["valid"] is False)


# ================================================================
# CLOSED VOCABULARIES
# ================================================================

def test_unknown_belge_turu_key_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["document_family_rules"]["Bilinmeyen Belge Türü"] = fixture["document_family_rules"].pop("Diğer")
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown belge_turu key rejected (closed document_family_rules key set)", result["valid"] is False)


def test_unknown_admission_value_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["document_family_rules"]["Kanun"]["admission"] = "maybe_allowed"
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown admission value rejected", result["valid"] is False)


def test_unknown_enforcement_stage_value_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["quality_gates"][0]["enforcement_stage"] = "at_some_point"
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown enforcement_stage value rejected", result["valid"] is False)


def test_unknown_outcome_value_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["quality_gates"][0]["outcome"] = "warn_only"
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown outcome value rejected", result["valid"] is False)


def test_unknown_text_basis_declaration_value_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["temporal_requirements"]["text_basis_declaration"] = "some_other_basis"
    result = cpv.validate_corpus_policy(policy=fixture)
    check("unknown text_basis_declaration value rejected", result["valid"] is False)


def test_placeholder_threshold_string_rejected_by_type():
    # threshold's schema type is ["integer","number","null"] - a
    # placeholder STRING like "TBD" is structurally impossible, never a
    # separate business-rule check (§O: "sayısal eşikler policy'de
    # SOMUT değerlerle - placeholder yasak").
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["quality_gates"][0]["threshold"] = "TBD"
    result = cpv.validate_corpus_policy(policy=fixture)
    check("placeholder string threshold rejected by schema type constraint", result["valid"] is False)


def test_belge_turu_enum_byte_equality_with_documents_schema():
    known = cpv.known_belge_turu_values()
    documents_schema = json.loads((REPO_ROOT / "data" / "documents.schema.json").read_text(encoding="utf-8"))
    from_documents_schema = set(documents_schema["$defs"]["document"]["properties"]["belge_turu"]["enum"])
    check(
        "belge_turu enum byte-equality: corpus_policy_validator's own view matches documents.schema.json",
        known == from_documents_schema, (known, from_documents_schema),
    )
    real_policy = cpv.load_policy()
    check(
        "belge_turu enum byte-equality: real committed policy's family keys match documents.schema.json enum",
        set(real_policy["document_family_rules"].keys()) == from_documents_schema,
    )


def test_belge_turu_drift_missing_family_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    del fixture["document_family_rules"]["Sirküler"]
    result = cpv.validate_corpus_policy(policy=fixture)
    check("belge_turu drift (a documents.schema.json value missing from policy) rejected", result["valid"] is False)


# ================================================================
# SEMANTIC CONSISTENCY
# ================================================================

def test_admission_allowed_with_prerequisites_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["document_family_rules"]["Kanun"]["prerequisites"] = ["some_prereq"]
    result = cpv.validate_corpus_policy(policy=fixture)
    check("admission=allowed with non-empty prerequisites rejected (contradictory)", result["valid"] is False)


def test_admission_deferred_without_prerequisites_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["document_family_rules"]["Sirküler"]["prerequisites"] = []
    result = cpv.validate_corpus_policy(policy=fixture)
    check("admission=deferred with empty prerequisites rejected (no blocking reason declared)", result["valid"] is False)


def test_admission_prohibited_with_tier_assigned_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["document_family_rules"]["Diğer"]["tier"] = 3
    result = cpv.validate_corpus_policy(policy=fixture)
    check("admission=prohibited with an assigned tier rejected (a prohibited family cannot have a population tier)", result["valid"] is False)


def test_duplicate_quality_gate_id_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["quality_gates"].append(dict(fixture["quality_gates"][0]))
    result = cpv.validate_corpus_policy(policy=fixture)
    check("duplicate quality_gates.gate_id rejected", result["valid"] is False)


def test_duplicate_source_authority_tier_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["source_authority_tiers"].append({"tier": fixture["source_authority_tiers"][0]["tier"], "name": "dup", "description": "dup"})
    result = cpv.validate_corpus_policy(policy=fixture)
    check("duplicate source_authority_tiers.tier rejected", result["valid"] is False)


def test_required_provenance_field_not_in_documents_schema_rejected():
    fixture = copy.deepcopy(cpv.create_valid_fixture())
    fixture["document_family_rules"]["Kanun"]["required_provenance_fields"] = ["this_field_does_not_exist_anywhere"]
    result = cpv.validate_corpus_policy(policy=fixture)
    check(
        "required_provenance_fields entry not present in documents.schema.json's document properties rejected",
        result["valid"] is False,
    )


def test_real_policy_required_provenance_fields_all_exist_in_documents_schema():
    real_policy = cpv.load_policy()
    known_fields = cpv.known_document_field_names()
    for family_name, rule in real_policy["document_family_rules"].items():
        for field_name in rule["required_provenance_fields"]:
            check(
                f"real policy: {family_name}.required_provenance_fields entry '{field_name}' exists in documents.schema.json",
                field_name in known_fields,
            )


# ================================================================
# RAW-BYTE HASH DETERMINISM (ingest.calculate_file_hash, the exact
# idiom corpus_policy_sha256/source_manifest entries use - §I).
# ================================================================

def test_raw_byte_hash_determinism_same_bytes():
    with tempfile.TemporaryDirectory() as tmp:
        path_a = Path(tmp) / "a.json"
        path_b = Path(tmp) / "b.json"
        content = b'{"policy_id": "hash_determinism_fixture", "value": 1}'
        path_a.write_bytes(content)
        path_b.write_bytes(content)
        hash_a = ingest.calculate_file_hash(path_a)
        hash_b = ingest.calculate_file_hash(path_b)
        check("raw-byte hash: identical byte content -> identical hash", hash_a == hash_b)
        check("raw-byte hash: matches independently-computed hashlib.sha256", hash_a == hashlib.sha256(content).hexdigest())


def test_raw_byte_hash_single_byte_change_differs():
    with tempfile.TemporaryDirectory() as tmp:
        path_a = Path(tmp) / "a.json"
        path_b = Path(tmp) / "b.json"
        content_a = b'{"policy_id": "hash_sensitivity_fixture", "value": 1}'
        content_b = b'{"policy_id": "hash_sensitivity_fixture", "value": 2}'  # single-character diff
        path_a.write_bytes(content_a)
        path_b.write_bytes(content_b)
        check(
            "raw-byte hash: single-byte content change -> different hash",
            ingest.calculate_file_hash(path_a) != ingest.calculate_file_hash(path_b),
        )


def test_raw_byte_hash_crlf_vs_lf_differs():
    with tempfile.TemporaryDirectory() as tmp:
        lf_path = Path(tmp) / "lf.json"
        crlf_path = Path(tmp) / "crlf.json"
        text = '{\n  "policy_id": "crlf_fixture",\n  "value": 1\n}'
        lf_path.write_bytes(text.encode("utf-8"))
        crlf_path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        check(
            "raw-byte hash: LF vs CRLF line endings -> different hash (deliberate byte-sensitivity, not canonicalized)",
            ingest.calculate_file_hash(lf_path) != ingest.calculate_file_hash(crlf_path),
        )


def test_real_committed_policy_hash_is_deterministic_across_reads():
    first = ingest.calculate_file_hash(cpv.CORPUS_POLICY_PATH)
    second = ingest.calculate_file_hash(cpv.CORPUS_POLICY_PATH)
    check("real committed corpus_policy.json: hash is stable across repeated reads", first == second)
    check("real committed corpus_policy.json: hash is a 64-char lowercase hex string", len(first) == 64 and first == first.lower())


# ================================================================
# create_valid_fixture()-INDEPENDENT GOLDEN FIXTURE (totoloji kırıcı)
# ================================================================

def test_independent_hand_written_golden_fixture_validates():
    # Hand-typed, NOT derived from cpv.create_valid_fixture() or
    # cpv.known_belge_turu_values() - a literal, independent minimal
    # policy that must also validate cleanly. Cross-checks that
    # create_valid_fixture() is not merely "shaped like whatever the
    # validator happens to accept" in some self-referential way.
    golden = {
        "schema_version": 1,
        "policy_id": "vergi_ai_corpus_policy_v1",
        "policy_version": 3,
        "effective_from": "2025-06-15",
        "source_authority_tiers": [
            {"tier": 1, "name": "official_gazette", "description": "Golden fixture tier one."},
            {"tier": 2, "name": "secondary_portal", "description": "Golden fixture tier two."},
        ],
        "document_family_rules": {
            "Kanun": {
                "admission": "allowed", "tier": 1, "required_provenance_fields": ["source_url", "kanun_no"],
                "temporal_sensitive": True, "prerequisites": [], "notes": "golden",
            },
            "Bakanlar Kurulu Kararı": {
                "admission": "allowed", "tier": 1, "required_provenance_fields": [],
                "temporal_sensitive": True, "prerequisites": [], "notes": None,
            },
            "Cumhurbaşkanı Kararı": {
                "admission": "allowed", "tier": 1, "required_provenance_fields": [],
                "temporal_sensitive": True, "prerequisites": [], "notes": None,
            },
            "Yönetmelik": {
                "admission": "allowed", "tier": 1, "required_provenance_fields": [],
                "temporal_sensitive": True, "prerequisites": [], "notes": None,
            },
            "Genel Tebliğ": {
                "admission": "allowed", "tier": 2, "required_provenance_fields": [],
                "temporal_sensitive": True, "prerequisites": [], "notes": None,
            },
            "Tebliğ": {
                "admission": "allowed", "tier": 2, "required_provenance_fields": [],
                "temporal_sensitive": True, "prerequisites": [], "notes": None,
            },
            "Sirküler": {
                "admission": "deferred", "tier": None, "required_provenance_fields": [],
                "temporal_sensitive": False, "prerequisites": ["golden_prereq"], "notes": None,
            },
            "Özelge": {
                "admission": "deferred", "tier": None, "required_provenance_fields": [],
                "temporal_sensitive": False, "prerequisites": ["golden_prereq"], "notes": None,
            },
            "Yargı Kararı": {
                "admission": "deferred", "tier": None, "required_provenance_fields": [],
                "temporal_sensitive": False, "prerequisites": ["golden_prereq"], "notes": None,
            },
            "Diğer": {
                "admission": "prohibited", "tier": None, "required_provenance_fields": [],
                "temporal_sensitive": False, "prerequisites": [], "notes": None,
            },
        },
        "quality_gates": [
            {"gate_id": "golden_gate_one", "enforcement_stage": "policy_foundation", "outcome": "reject", "threshold": None},
            {"gate_id": "golden_gate_two", "enforcement_stage": "population", "outcome": "needs_review", "threshold": 0.5},
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
            "capability_model": "golden fixture capability model",
            "policy_change_approval": "golden fixture approval rule",
            "four_eyes_required_in_pilot": False,
            "emergency_rollback_procedure": "golden fixture rollback procedure",
            "notes": None,
        },
        "notes": "Independent hand-written golden fixture - not derived from create_valid_fixture().",
    }
    result = cpv.validate_corpus_policy(policy=golden)
    check("independent hand-written golden fixture: schema+business-rules pass", result["valid"] is True, result["errors"])


def test_golden_fixture_and_create_valid_fixture_are_genuinely_different_objects():
    golden_policy_version = 3
    default_fixture = cpv.create_valid_fixture()
    check(
        "golden fixture is not literally identical to create_valid_fixture() (genuine cross-check, not a copy)",
        default_fixture["policy_version"] != golden_policy_version,
    )


# ================================================================
# SELF-TEST DISK ISOLATION - real data/ untouched.
# ================================================================

def _hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshot_data_tree():
    data_dir = REPO_ROOT / "data"
    snapshot = {}
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            snapshot[str(path.relative_to(data_dir))] = _hash_file(path)
    return snapshot


def test_module_self_test_does_not_touch_real_data_tree():
    before = _snapshot_data_tree()
    # corpus_policy_validator.run_self_test() writes its own disk-load
    # fixture (T18) to a tempfile.TemporaryDirectory() - never under
    # data/ (see that module's own "BİLİNÇLİ SAPMA" header note).
    cpv.run_self_test()
    after = _snapshot_data_tree()
    check("corpus_policy_validator.run_self_test() leaves the real data/ tree byte-unchanged", before == after)


def run_self_test():
    before_data_snapshot = _snapshot_data_tree()

    test_valid_fixture_schema_and_business_rules_pass()
    test_real_committed_policy_validates_cleanly()
    test_missing_required_top_level_field_rejected()
    test_wrong_schema_version_rejected()
    test_wrong_policy_id_rejected()
    test_policy_version_below_minimum_rejected()

    test_unknown_root_field_rejected()
    test_unknown_document_family_rule_field_rejected()
    test_unknown_quality_gate_field_rejected()
    test_unknown_source_authority_tier_field_rejected()
    test_unknown_security_rules_field_rejected()
    test_unknown_temporal_requirements_field_rejected()
    test_unknown_update_rules_field_rejected()
    test_unknown_governance_field_rejected()

    test_unknown_belge_turu_key_rejected()
    test_unknown_admission_value_rejected()
    test_unknown_enforcement_stage_value_rejected()
    test_unknown_outcome_value_rejected()
    test_unknown_text_basis_declaration_value_rejected()
    test_placeholder_threshold_string_rejected_by_type()
    test_belge_turu_enum_byte_equality_with_documents_schema()
    test_belge_turu_drift_missing_family_rejected()

    test_admission_allowed_with_prerequisites_rejected()
    test_admission_deferred_without_prerequisites_rejected()
    test_admission_prohibited_with_tier_assigned_rejected()
    test_duplicate_quality_gate_id_rejected()
    test_duplicate_source_authority_tier_rejected()
    test_required_provenance_field_not_in_documents_schema_rejected()
    test_real_policy_required_provenance_fields_all_exist_in_documents_schema()

    test_raw_byte_hash_determinism_same_bytes()
    test_raw_byte_hash_single_byte_change_differs()
    test_raw_byte_hash_crlf_vs_lf_differs()
    test_real_committed_policy_hash_is_deterministic_across_reads()

    test_independent_hand_written_golden_fixture_validates()
    test_golden_fixture_and_create_valid_fixture_are_genuinely_different_objects()

    test_module_self_test_does_not_touch_real_data_tree()

    after_data_snapshot = _snapshot_data_tree()
    check("this entire test module: real data/ tree byte-unchanged across the full run", before_data_snapshot == after_data_snapshot)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
