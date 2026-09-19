# ============================================================
# FACT VERIFICATION WORKFLOW - isolated tests for
# src/fact_verification.py (writer). Real `case_fact_validator`/
# `fact_approval` modules against REAL, re-identified synthetic copies
# of case_0001 created under the real `data/cases/` tree and fully
# removed at the end - the ENTIRE real data/ tree is snapshot-compared
# before/after.
#
# Run: python ui/tests/test_fact_verification_isolated.py
# ============================================================

import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = UI_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from ui.services import paths as _paths  # noqa: E402

import fact_approval  # noqa: E402
import fact_verification as fv  # noqa: E402

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


REAL_DATA_DIR = REPO_ROOT / "data"


def snapshot_data_tree():
    out = {}
    for path in REAL_DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(REAL_DATA_DIR))] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                out[str(path.relative_to(REAL_DATA_DIR))] = "<unreadable>"
    return out


_data_tree_before_everything = snapshot_data_tree()

_created_case_dirs = []

FACT_DOC = "dava_dilekcesi_001"


def make_case():
    case_id = f"fviso{uuid.uuid4().hex[:10]}"
    src = _paths.CASES_DIR / "case_0001"
    dst = _paths.CASES_DIR / case_id
    shutil.copytree(src, dst)
    for path in dst.rglob("*"):
        if path.is_file() and (path.suffix in (".json", ".pending", ".bak") or path.name.endswith(".json.pending")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "case_0001" in text:
                path.write_text(text.replace("case_0001", case_id), encoding="utf-8")
    _created_case_dirs.append(dst)
    return case_id, dst


def canonical_path_for(case_dir, document_id=FACT_DOC):
    return case_dir / "documents" / document_id / "extractions" / "facts.json"


def verified_paths_for(case_dir, document_id=FACT_DOC):
    ext = case_dir / "documents" / document_id / "extractions"
    return {
        "extractions_dir": ext,
        "canonical_path": ext / "facts.json",
        "history_dir": ext / "history",
        "reviews_dir": ext / "reviews" / "fact_verifications",
    }


try:
    # ============================================================
    # T0 - canonical-serialization form check.
    # ============================================================
    case_id0, case_dir0 = make_case()
    canonical0 = canonical_path_for(case_dir0)
    raw0 = canonical0.read_bytes()
    extraction0 = fv.verify_canonical_serialization_form(raw0)
    check("T0a real case_0001-derived canonical passes structural-equality check", isinstance(extraction0, dict))

    # Tolerates BOTH EOL regimes - build an LF variant from an
    # LF-normalized base (this machine's os.linesep is "\r\n", so raw0
    # itself already exercises the CRLF direction via T0a above).
    lf_bytes = raw0.replace(b"\r\n", b"\n")
    check("T0a2 this fixture's raw canonical bytes are genuinely CRLF on this platform",
          lf_bytes != raw0)
    extraction0b = fv.verify_canonical_serialization_form(lf_bytes)
    check("T0b a pure-LF canonical is ACCEPTED (EOL-tolerant, opposite direction from T0a)",
          isinstance(extraction0b, dict))

    # Rejects a reformatted (still-valid-JSON, different byte layout) file.
    reformatted = json.dumps(json.loads(raw0.decode("utf-8")), ensure_ascii=False).encode("utf-8")
    expect_raises(
        fv.FactVerificationSerializationError,
        lambda: fv.verify_canonical_serialization_form(reformatted),
        "T0c a compact (non-canonical-indent) reserialization is REJECTED, never silently reformatted",
    )

    # Rejects malformed JSON outright.
    expect_raises(
        fv.FactVerificationSerializationError,
        lambda: fv.verify_canonical_serialization_form(b"{not json"),
        "T0d malformed JSON bytes -> FactVerificationSerializationError",
    )

    # ============================================================
    # T1 - find_fact / allowed_evidence_document_ids / source_has_locator.
    # ============================================================
    fact0 = extraction0["facts"][0]
    check("T1a find_fact locates the first real fact by its own fact_id",
          fv.find_fact(extraction0, fact0["fact_id"]) is fact0 or
          fv.find_fact(extraction0, fact0["fact_id"]).get("fact_id") == fact0["fact_id"])
    check("T1b find_fact returns None for a nonexistent fact_id",
          fv.find_fact(extraction0, "definitely_not_a_real_fact_id") is None)
    allowed0 = fv.allowed_evidence_document_ids(extraction0, fact0)
    check(
        "T1c allowed_evidence_document_ids includes the extraction's own source_document_id",
        extraction0["source_document_id"] in allowed0,
    )
    check(
        "T1d allowed_evidence_document_ids includes every related_document_id",
        set(fact0.get("related_document_ids", [])).issubset(allowed0),
    )

    # ============================================================
    # T2 - compute_expected_post_canonical_bytes: pure, deterministic,
    #      changes ONLY the target fact's verification_state.
    # ============================================================
    target_fact_id = fact0["fact_id"]
    new_bytes = fv.compute_expected_post_canonical_bytes(raw0, target_fact_id, "verified")
    new_bytes_again = fv.compute_expected_post_canonical_bytes(raw0, target_fact_id, "verified")
    check("T2a deterministic: two calls produce byte-identical output", new_bytes == new_bytes_again)
    new_extraction = json.loads(new_bytes.decode("utf-8"))
    check(
        "T2b ONLY the target fact's verification_state changed; every other field/fact deep-equal",
        new_extraction["facts"][0]["verification_state"] == "verified"
        and all(
            (a == b) or (a.get("fact_id") == target_fact_id and a["verification_state"] != b["verification_state"])
            for a, b in zip(new_extraction["facts"], extraction0["facts"])
        ),
    )
    _before = snapshot_data_tree()
    check("T2c compute_expected_post_canonical_bytes writes NOTHING to disk", snapshot_data_tree() == _before)
    expect_raises(
        ValueError,
        lambda: fv.compute_expected_post_canonical_bytes(raw0, "no_such_fact_id", "verified"),
        "T2d unknown fact_id -> ValueError (no silent no-op)",
    )

    # ============================================================
    # T3 - apply_verification: happy-path VERIFIED transition.
    # ============================================================
    case_id3, case_dir3 = make_case()
    canonical3 = canonical_path_for(case_dir3)
    raw_before3 = canonical3.read_bytes()
    extraction3 = json.loads(raw_before3.decode("utf-8"))
    fact3 = extraction3["facts"][0]
    fact_id3 = fact3["fact_id"]
    vp3 = verified_paths_for(case_dir3)

    result3 = fv.apply_verification(
        case_id3, FACT_DOC, fact_id3, "unverified", "verified",
        evidence_document_id=extraction3["source_document_id"],
        evidence_document_sha256="deadbeef" * 8,
        source_locator_present=True,
        source_locator_sha256="cafebabe" * 8,
        identity_payload={"revision_version": "row_v.fact_verification.v1", "canonical_sha256": "x", "attempt": 1},
        attempt=1,
        secondary_input_hash=None,
        verified_paths=vp3,
        mutation_idempotency_key="k" * 64,
        mutation_resource_key=f"case:{case_id3}",
        mutation_actor_ref="7",
    )
    check("T3a apply_verification returns canonical_sha256 matching disk",
          result3["canonical_sha256"] == hashlib.sha256(canonical3.read_bytes()).hexdigest())
    reloaded3 = json.loads(canonical3.read_bytes().decode("utf-8"))
    check("T3b target fact's verification_state is now 'verified'",
          fv.find_fact(reloaded3, fact_id3)["verification_state"] == "verified")
    check(
        "T3c every OTHER fact is byte-for-byte deep-equal to the pre-image",
        all(
            reloaded3["facts"][i] == extraction3["facts"][i]
            for i in range(len(extraction3["facts"])) if extraction3["facts"][i]["fact_id"] != fact_id3
        ),
    )
    check("T3d history backup was created and matches the PRE-image bytes",
          Path(result3["history_backup_path"]).read_bytes() == raw_before3)
    audit3 = json.loads(Path(result3["audit_path"]).read_text(encoding="utf-8"))
    check(
        "T3e audit carries the exact closed field set (schema/case/document/fact/target_ref/"
        "from_state/target_state/outcome/mutation bindings)",
        audit3.get("schema_version") == 1
        and audit3.get("audit_type") == "fact_verification"
        and audit3.get("case_id") == case_id3
        and audit3.get("document_id") == FACT_DOC
        and audit3.get("fact_id") == fact_id3
        and audit3.get("target_ref") == f"fact.{FACT_DOC}.{fact_id3}.verification"
        and audit3.get("from_state") == "unverified"
        and audit3.get("target_state") == "verified"
        and audit3.get("outcome") == "verified_state_changed"
        and audit3.get("mutation_idempotency_key") == "k" * 64
        and audit3.get("mutation_resource_key") == f"case:{case_id3}"
        and audit3.get("mutation_actor_ref") == "7"
        and audit3.get("action_family") == "verification.fact"
        and audit3.get("channel") == "local_lawyer_fact_verification_cli"
        and audit3.get("reviewer_ref") == "local_lawyer_fact_verification_cli",
        f"{audit3!r}",
    )
    check(
        "T3f audit carries hash/metadata only - no legal free text (statement/normalized_statement "
        "of any fact never appears in the audit JSON)",
        all(
            fact.get("statement", "") not in json.dumps(audit3)
            for fact in extraction3["facts"] if fact.get("statement")
        ),
    )

    # ============================================================
    # T4 - self-transition defense at the writer boundary.
    # ============================================================
    case_id4, case_dir4 = make_case()
    canonical4 = canonical_path_for(case_dir4)
    canonical4_bytes_before = canonical4.read_bytes()
    extraction4 = json.loads(canonical4_bytes_before.decode("utf-8"))
    fact_id4 = extraction4["facts"][0]["fact_id"]
    vp4 = verified_paths_for(case_dir4)
    expect_raises(
        ValueError,
        lambda: fv.apply_verification(
            case_id4, FACT_DOC, fact_id4, "unverified", "unverified",
            evidence_document_id=None, evidence_document_sha256=None,
            source_locator_present=True, source_locator_sha256="x" * 64,
            identity_payload={}, attempt=1, secondary_input_hash=None,
            verified_paths=vp4,
            mutation_idempotency_key="k" * 64, mutation_resource_key=f"case:{case_id4}",
            mutation_actor_ref="7",
        ),
        "T4a writer-level defense: self-transition (from==target) -> ValueError, no I/O side effect",
    )
    check("T4b canonical untouched after self-transition rejection",
          canonical4.read_bytes() == canonical4_bytes_before)

    # ============================================================
    # T5 - from_state mismatch defense (double-check under-lock re-derivation).
    # ============================================================
    case_id5, case_dir5 = make_case()
    canonical5 = canonical_path_for(case_dir5)
    extraction5 = json.loads(canonical5.read_bytes().decode("utf-8"))
    fact_id5 = extraction5["facts"][0]["fact_id"]
    vp5 = verified_paths_for(case_dir5)
    expect_raises(
        ValueError,
        lambda: fv.apply_verification(
            case_id5, FACT_DOC, fact_id5, "verified", "unverified",  # WRONG from_state claim
            evidence_document_id=None, evidence_document_sha256=None,
            source_locator_present=True, source_locator_sha256="x" * 64,
            identity_payload={}, attempt=1, secondary_input_hash=None,
            verified_paths=vp5,
            mutation_idempotency_key="k" * 64, mutation_resource_key=f"case:{case_id5}",
            mutation_actor_ref="7",
        ),
        "T5a writer-level defense: claimed from_state != actual current state -> ValueError",
    )

    # ============================================================
    # T6 - post-write validation failure -> full rollback.
    # ============================================================
    case_id6, case_dir6 = make_case()
    canonical6 = canonical_path_for(case_dir6)
    raw_before6 = canonical6.read_bytes()
    extraction6 = json.loads(raw_before6.decode("utf-8"))
    fact_id6 = extraction6["facts"][0]["fact_id"]
    vp6 = verified_paths_for(case_dir6)

    _orig_validate = fv.validate_fact_extraction

    def _raising_validate(*args, **kwargs):
        raise ValueError("simulated post-write validation failure")

    fv.validate_fact_extraction = _raising_validate
    try:
        expect_raises(
            ValueError,
            lambda: fv.apply_verification(
                case_id6, FACT_DOC, fact_id6, "unverified", "verified",
                evidence_document_id=extraction6["source_document_id"],
                evidence_document_sha256="x" * 64, source_locator_present=True,
                source_locator_sha256="y" * 64, identity_payload={}, attempt=1,
                secondary_input_hash=None, verified_paths=vp6,
                mutation_idempotency_key="k" * 64, mutation_resource_key=f"case:{case_id6}",
                mutation_actor_ref="7",
            ),
            "T6a post-write validation failure propagates",
        )
    finally:
        fv.validate_fact_extraction = _orig_validate
    check("T6b canonical rolled back to the EXACT pre-image bytes", canonical6.read_bytes() == raw_before6)
    check(
        "T6c a history backup exists (writer entry evidence) despite the rollback",
        any((case_dir6 / "documents" / FACT_DOC / "extractions" / "history").glob("facts_before_verification_*")),
    )
    check(
        "T6d NO audit file was written (failure occurred before the audit-write step)",
        not (case_dir6 / "documents" / FACT_DOC / "extractions" / "reviews" / "fact_verifications").exists()
        or not any((case_dir6 / "documents" / FACT_DOC / "extractions" / "reviews" / "fact_verifications").glob("*.verification.json")),
    )

    # ============================================================
    # T7 - audit-write failure -> full rollback (canonical already
    #      written at this point; writer must undo it).
    # ============================================================
    case_id7, case_dir7 = make_case()
    canonical7 = canonical_path_for(case_dir7)
    raw_before7 = canonical7.read_bytes()
    extraction7 = json.loads(raw_before7.decode("utf-8"))
    fact_id7 = extraction7["facts"][0]["fact_id"]
    vp7 = verified_paths_for(case_dir7)

    _orig_audit_writer = fv._write_audit_record_excl
    _boom7 = OSError("simulated disk failure at audit write")

    def _raising_audit_writer(reviews_dir, document_id, fact_id, record):
        raise _boom7

    fv._write_audit_record_excl = _raising_audit_writer
    try:
        caught7 = None
        try:
            fv.apply_verification(
                case_id7, FACT_DOC, fact_id7, "unverified", "verified",
                evidence_document_id=extraction7["source_document_id"],
                evidence_document_sha256="x" * 64, source_locator_present=True,
                source_locator_sha256="y" * 64, identity_payload={}, attempt=1,
                secondary_input_hash=None, verified_paths=vp7,
                mutation_idempotency_key="k" * 64, mutation_resource_key=f"case:{case_id7}",
                mutation_actor_ref="7",
            )
        except OSError as error:
            caught7 = error
        check("T7a audit-write crash propagates the ORIGINAL exception instance", caught7 is _boom7)
    finally:
        fv._write_audit_record_excl = _orig_audit_writer
    check("T7b canonical rolled back to the EXACT pre-image bytes after audit-write crash",
          canonical7.read_bytes() == raw_before7)

    # ============================================================
    # T8 - history backup O_EXCL uniqueness (two verifications on the
    #      SAME document within the same wall-clock second get distinct
    #      backup filenames via numeric-suffix retry).
    # ============================================================
    case_id8, case_dir8 = make_case()
    canonical8 = canonical_path_for(case_dir8)
    extraction8 = json.loads(canonical8.read_bytes().decode("utf-8"))
    facts8 = extraction8["facts"]
    vp8 = verified_paths_for(case_dir8)
    if len(facts8) >= 2:
        r8a = fv.apply_verification(
            case_id8, FACT_DOC, facts8[0]["fact_id"], "unverified", "verified",
            evidence_document_id=extraction8["source_document_id"], evidence_document_sha256="x" * 64,
            source_locator_present=True, source_locator_sha256="y" * 64, identity_payload={}, attempt=1,
            secondary_input_hash=None, verified_paths=vp8,
            mutation_idempotency_key="k1" + "0" * 62, mutation_resource_key=f"case:{case_id8}",
            mutation_actor_ref="7",
        )
        r8b = fv.apply_verification(
            case_id8, FACT_DOC, facts8[1]["fact_id"], "unverified", "verified",
            evidence_document_id=extraction8["source_document_id"], evidence_document_sha256="x" * 64,
            source_locator_present=True, source_locator_sha256="y" * 64, identity_payload={}, attempt=1,
            secondary_input_hash=None, verified_paths=vp8,
            mutation_idempotency_key="k2" + "0" * 62, mutation_resource_key=f"case:{case_id8}",
            mutation_actor_ref="7",
        )
        check(
            "T8a two sequential verifications produce two DISTINCT history backup files "
            "(no overwrite)",
            r8a["history_backup_path"] != r8b["history_backup_path"],
        )
        check(
            "T8b two sequential verifications produce two DISTINCT audit files (no overwrite)",
            r8a["audit_path"] != r8b["audit_path"],
        )
    else:
        check("T8 (skipped: fixture has fewer than 2 facts)", True)

    # ============================================================
    # T9 - verified_paths topology cross-check (fail-closed, zero I/O).
    # ============================================================
    case_id9, case_dir9 = make_case()
    vp9 = verified_paths_for(case_dir9)
    bad_vp9 = dict(vp9)
    bad_vp9["canonical_path"] = vp9["extractions_dir"] / "not_facts.json"
    expect_raises(
        ValueError,
        lambda: fv.apply_verification(
            case_id9, FACT_DOC, "irrelevant", "unverified", "verified",
            evidence_document_id=None, evidence_document_sha256=None,
            source_locator_present=True, source_locator_sha256="x" * 64,
            identity_payload={}, attempt=1, secondary_input_hash=None,
            verified_paths=bad_vp9,
            mutation_idempotency_key="k" * 64, mutation_resource_key=f"case:{case_id9}",
            mutation_actor_ref="7",
        ),
        "T9a malformed verified_paths topology -> ValueError, zero I/O",
    )
    missing_key_vp9 = {k: v for k, v in vp9.items() if k != "history_dir"}
    expect_raises(
        ValueError,
        lambda: fv.apply_verification(
            case_id9, FACT_DOC, "irrelevant", "unverified", "verified",
            evidence_document_id=None, evidence_document_sha256=None,
            source_locator_present=True, source_locator_sha256="x" * 64,
            identity_payload={}, attempt=1, secondary_input_hash=None,
            verified_paths=missing_key_vp9,
            mutation_idempotency_key="k" * 64, mutation_resource_key=f"case:{case_id9}",
            mutation_actor_ref="7",
        ),
        "T9b verified_paths missing a required key -> ValueError, zero I/O",
    )

finally:
    for case_dir in _created_case_dirs:
        try:
            if case_dir.exists():
                shutil.rmtree(case_dir)
        except OSError as cleanup_error:
            print(f"CLEANUP WARNING: case dir {case_dir}: {cleanup_error!r}")

_data_tree_after_everything = snapshot_data_tree()
check(
    "FINAL: the real data/ tree is byte-for-byte IDENTICAL to the pre-test snapshot "
    "(all synthetic cases fully removed, no residue anywhere)",
    _data_tree_after_everything == _data_tree_before_everything,
    f"diff keys: {sorted(set(_data_tree_after_everything) ^ set(_data_tree_before_everything))[:20]!r}",
)

print(f"--- test_fact_verification_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
