# ============================================================
# KOL A / MALI TATIL DILIM B / ALT DILIM B1
# src/receivable_record_validator.py ISOLATED TESTS.
#
# Saf Python; PostgreSQL yok, mutation coordinator yok, ag yok.
# Yalniz kurgusal veri ("Kurgusal ..." adlar, synthetic_* kimlikler).
# data/cases altina YAZMAZ ve oradan OKUMAZ. Tek gercek dosya okumasi:
# data/deadline_rules/deadline_rules.json (salt-okunur; dort belge
# turunun uc taslak kuralin document_types birlesimiyle ayni oldugunu
# capraz kontrol etmek icin) ve sema dosyasi (sema-dogrulayici
# tutarliligi icin).
#
# Dosya-okumaz/yazmaz (kural 11) testi builtins.open / io.open /
# os.open / pathlib.Path.* fonksiyonlarini kisa sureligine hata
# firlatan sahtelerle degistirir ve try/finally ile MUTLAKA geri alir.
# sys.addaudithook KULLANILMAZ ve alt surec baslatilmaz (Adim 4c
# GUARD_INHERITANCE_MISMATCH dersi).
#
# Run: python ui/tests/test_receivable_record_validator_isolated.py
# ============================================================

import ast
import builtins
import copy
import io
import json
import os
import pathlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import receivable_record_validator as rrv  # noqa: E402

MODULE_NAME = "test_receivable_record_validator_isolated"

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {label}")
    else:
        failed += 1
        safe_detail = str(detail).encode("ascii", "backslashreplace").decode("ascii")
        print(f"FAIL {label} {safe_detail}")


# ============================================================
# FIXTURES (kurgusal)
# ============================================================

CASE_ID = "synthetic_case_b1"
ACTION_DOC = "synthetic_doc_action"
STATEMENT_DOC = "synthetic_doc_statement"
UNRELATED_DOC = "synthetic_doc_unrelated"


def make_documents():
    return {
        ACTION_DOC: {
            "document_type": "odeme_emri",
            "page_count": 3,
            "active": True,
        },
        STATEMENT_DOC: {
            "document_type": "kurgusal_borc_dokumu",
            "page_count": 5,
            "active": True,
        },
        UNRELATED_DOC: {
            "document_type": "kurgusal_diger_belge",
            "page_count": 2,
            "active": True,
        },
    }


def null_verification():
    return {
        "verification_state": "unverified",
        "completeness_attested": None,
        "items_evidence": None,
        "creditors_evidence": None,
        "verification_audit_ref": None,
    }


def base_record():
    """Gecerli, teyitsiz, same_document kaydi."""
    return {
        "schema_version": 1,
        "case_id": CASE_ID,
        "record_id": "synthetic_rec_001",
        "action_document_id": ACTION_DOC,
        "action_document_type": "odeme_emri",
        "link_basis": {
            "kind": "same_document",
            "debt_statement_document_id": None,
            "basis": None,
            "description": None,
        },
        "creditors": [
            {
                "creditor_id": "synthetic_cr_1",
                "role": "ikisi",
                "authority_type": "vergi_dairesi_mudurlugu",
                "authority_name": "Kurgusal Vergi Dairesi Mudurlugu",
                "source_document_id": ACTION_DOC,
                "page": 1,
            }
        ],
        "items": [
            {
                "item_id": "synthetic_item_1",
                "receivable_kind": "asil",
                "subject_type": "gelir_vergisi",
                "subject_other_name": None,
                "related_subject_type": None,
                "related_subject_other_name": None,
                "period": {
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                    "label": None,
                },
                "tax_code": "0001",
                "creditor_id": "synthetic_cr_1",
                "source_document_id": ACTION_DOC,
                "page": 2,
            },
            {
                "item_id": "synthetic_item_2",
                "receivable_kind": "vergi_ziyai_cezasi",
                "subject_type": "vergi_ziyai_cezasi",
                "subject_other_name": None,
                "related_subject_type": "gelir_vergisi",
                "related_subject_other_name": None,
                "period": {
                    "start_date": None,
                    "end_date": None,
                    "label": "Kurgusal donem 2025",
                },
                "tax_code": None,
                "creditor_id": "synthetic_cr_1",
                "source_document_id": ACTION_DOC,
                "page": 3,
            },
        ],
        "verification": null_verification(),
    }


def debt_record():
    """Gecerli, teyitsiz, debt_statement kaydi (kalem borc dokumunden)."""
    record = base_record()
    record["link_basis"] = {
        "kind": "debt_statement",
        "debt_statement_document_id": STATEMENT_DOC,
        "basis": "by_tracking_no",
        "description": "Kurgusal takip numarasi ile baglandi",
    }
    record["items"][1]["source_document_id"] = STATEMENT_DOC
    record["items"][1]["page"] = 5
    return record


def verified_record():
    """Gecerli, teyitli kayit (yalniz allow_verified=True iken gecerli)."""
    record = base_record()
    record["verification"] = {
        "verification_state": "verified",
        "completeness_attested": True,
        "items_evidence": [
            {
                "item_id": "synthetic_item_1",
                "evidence_document_id": ACTION_DOC,
                "page": 2,
            },
            {
                "item_id": "synthetic_item_2",
                "evidence_document_id": ACTION_DOC,
                "page": 3,
            },
        ],
        "creditors_evidence": [
            {
                "creditor_id": "synthetic_cr_1",
                "evidence_document_id": ACTION_DOC,
                "page": 1,
            }
        ],
        "verification_audit_ref": "synthetic_audit_001",
    }
    return record


_DEFAULT_DOCUMENTS = object()


def run(record, documents=_DEFAULT_DOCUMENTS, case_id=CASE_ID, **kwargs):
    if documents is _DEFAULT_DOCUMENTS:
        documents = make_documents()
    return rrv.validate_receivable_record(
        record,
        case_id=case_id,
        documents=documents,
        **kwargs,
    )


def expect(label, record, expected, documents=_DEFAULT_DOCUMENTS, case_id=CASE_ID, **kwargs):
    try:
        result = run(record, documents=documents, case_id=case_id, **kwargs)
    except Exception as error:  # noqa: BLE001
        check(label, False, f"raised {type(error).__name__}")
        return None
    check(label, result == sorted(expected), detail=repr(result))
    return result


# ============================================================
# 0) SEMA / SABIT TUTARLILIGI
# ============================================================

SCHEMA_PATH = REPO_ROOT / "data" / "case_receivable_record.schema.json"
with open(SCHEMA_PATH, "r", encoding="utf-8") as _handle:
    SCHEMA = json.load(_handle)

check("schema loaded once at import (validator available)", rrv._SCHEMA_VALIDATOR is not None)
check("module schema equals on-disk schema", rrv.RECEIVABLE_RECORD_SCHEMA == SCHEMA)
check("schema_version const is 1", SCHEMA["properties"]["schema_version"] == {"type": "integer", "const": 1})


def _walk_objects(node, path, out):
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            out.append((path, node))
        for key, value in node.items():
            _walk_objects(value, f"{path}/{key}", out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_objects(value, f"{path}/{index}", out)


_objects = []
_walk_objects(SCHEMA, "#", _objects)
check("schema has exactly 8 object nodes (record + 7 defs)", len(_objects) == 8, detail=len(_objects))
for _path, _node in _objects:
    check(
        f"schema object {_path}: additionalProperties is false",
        _node.get("additionalProperties") is False,
    )
    check(
        f"schema object {_path}: every property key is required (nullable, not optional)",
        set(_node.get("required", [])) == set(_node.get("properties", {}).keys()),
    )

_defs = SCHEMA["$defs"]
check(
    "schema action_document_type enum == validator SUPPORTED_ACTION_DOCUMENT_TYPES",
    set(SCHEMA["properties"]["action_document_type"]["enum"]) == set(rrv.SUPPORTED_ACTION_DOCUMENT_TYPES),
)
check(
    "schema receivable_kind enum == validator RECEIVABLE_KINDS",
    _defs["item"]["properties"]["receivable_kind"]["enum"] == list(rrv.RECEIVABLE_KINDS),
)
check(
    "schema subjectType enum == validator SUBJECT_TYPES",
    _defs["subjectType"]["enum"] == list(rrv.SUBJECT_TYPES),
)
check(
    "schema relatedSubjectType enum == TAX_SUBJECT_TYPES + null",
    _defs["relatedSubjectType"]["enum"] == list(rrv.TAX_SUBJECT_TYPES) + [None],
)
check(
    "schema creditor role enum == validator CREDITOR_ROLES",
    _defs["creditor"]["properties"]["role"]["enum"] == list(rrv.CREDITOR_ROLES),
)
check(
    "schema authority_type enum == validator AUTHORITY_TYPES",
    _defs["creditor"]["properties"]["authority_type"]["enum"] == list(rrv.AUTHORITY_TYPES),
)
check(
    "schema link_basis kind enum == validator LINK_BASIS_KINDS",
    _defs["linkBasis"]["properties"]["kind"]["enum"] == list(rrv.LINK_BASIS_KINDS),
)
check(
    "schema link_basis basis enum == validator LINK_BASIS_BASES + null",
    _defs["linkBasis"]["properties"]["basis"]["enum"] == list(rrv.LINK_BASIS_BASES) + [None],
)
check(
    "schema verification_state enum == validator VERIFICATION_STATES",
    _defs["verification"]["properties"]["verification_state"]["enum"] == list(rrv.VERIFICATION_STATES),
)
check(
    "K15: verification block has exactly the five approved fields (no confirmer identity, no time)",
    set(_defs["verification"]["properties"].keys())
    == {
        "verification_state",
        "completeness_attested",
        "items_evidence",
        "creditors_evidence",
        "verification_audit_ref",
    },
)
check(
    "K6: no amount / quote field anywhere in the schema",
    not any(
        token in json.dumps(SCHEMA)
        for token in ('"amount"', '"tutar"', '"quote"', '"excerpt"', '"text_excerpt"')
    ),
)
check(
    "h: no completeness-like field outside the verification block",
    all(
        "complete" not in key
        for name, node in _defs.items()
        if name != "verification"
        for key in node.get("properties", {}).keys()
    )
    and all("complete" not in key for key in SCHEMA["properties"].keys()),
)
check(
    "KIND_TO_SUBJECT_TYPE covers every non-asil kind with the same-named value (diger -> diger)",
    set(rrv.KIND_TO_SUBJECT_TYPE) == set(rrv.RECEIVABLE_KINDS) - {"asil"}
    and all(key == value for key, value in rrv.KIND_TO_SUBJECT_TYPE.items()),
)
check(
    "TAX_SUBJECT_TYPES is exactly the 13 K12 values",
    list(rrv.TAX_SUBJECT_TYPES)
    == [
        "gelir_vergisi", "kurumlar_vergisi", "katma_deger_vergisi", "damga_vergisi",
        "veraset_ve_intikal_vergisi", "motorlu_tasitlar_vergisi", "ozel_tuketim_vergisi",
        "banka_ve_sigorta_muameleleri_vergisi", "ozel_iletisim_vergisi",
        "sans_oyunlari_vergisi", "resim", "harc", "diger",
    ],
)

# Dort belge turu == uc taslak kuralin document_types birlesimi
# (registry YALNIZ testte, salt-okunur okunur).
RULES_PATH = REPO_ROOT / "data" / "deadline_rules" / "deadline_rules.json"
with open(RULES_PATH, "r", encoding="utf-8") as _handle:
    _rules = json.load(_handle)
_receivable_rules = [
    rule
    for rule in _rules["rules"]
    if rule.get("mali_tatil_receivable_basis") == "action_document_receivables"
]
_union = set()
for _rule in _receivable_rules:
    for _doc_type in _rule["applicability"]["document_types"]:
        _union.add(_doc_type.strip().casefold())
check(
    "registry cross-check: exactly three rules carry the action_document_receivables basis",
    len(_receivable_rules) == 3,
    detail=len(_receivable_rules),
)
check(
    "registry cross-check: union of their document_types == validator SUPPORTED_ACTION_DOCUMENT_TYPES",
    _union == set(rrv.SUPPORTED_ACTION_DOCUMENT_TYPES),
    detail=sorted(_union),
)


# ============================================================
# 1) POZITIF TABANLAR
# ============================================================

expect("baseline: unverified same_document record is valid", base_record(), [])
expect("baseline: unverified debt_statement record is valid", debt_record(), [])
expect("baseline: verified record is valid with allow_verified=True", verified_record(), [], allow_verified=True)
_rec = verified_record()
_rec["verification"]["completeness_attested"] = False
expect(
    "rule 10: completeness_attested=False is also structurally valid (validator does not decide on its value)",
    _rec,
    [],
    allow_verified=True,
)
expect("baseline: unverified record is valid with allow_verified=True too", base_record(), [], allow_verified=True)


# ============================================================
# 2) KURAL 1 - SEMA (+ kati ekler) ve "once sema" sirasi
# ============================================================

_rec = base_record()
del _rec["record_id"]
expect("rule 1: missing top-level field -> SCHEMA_REQUIRED", _rec, [("SCHEMA_REQUIRED", "record_id")])

_rec = base_record()
del _rec["items"][0]["page"]
expect("rule 1: missing nested field -> SCHEMA_REQUIRED with structural path", _rec, [("SCHEMA_REQUIRED", "items[0].page")])

_rec = base_record()
_rec["kurgusal_fazla_alan"] = 1
expect("rule 1: extra top-level field -> SCHEMA_ADDITIONAL_PROPERTY at parent", _rec, [("SCHEMA_ADDITIONAL_PROPERTY", "record")])

_rec = base_record()
_rec["creditors"][0]["kurgusal_fazla_alan"] = 1
expect("rule 1: extra nested field -> SCHEMA_ADDITIONAL_PROPERTY at parent object", _rec, [("SCHEMA_ADDITIONAL_PROPERTY", "creditors[0]")])

_rec = base_record()
_rec["verification"]["confirmed_by"] = "synthetic_user"
expect("K15: confirmer identity field is rejected in the record", _rec, [("SCHEMA_ADDITIONAL_PROPERTY", "verification")])

_rec = base_record()
_rec["verification"]["confirmed_at"] = "2026-11-21"
expect("K15: confirmation time field is rejected in the record", _rec, [("SCHEMA_ADDITIONAL_PROPERTY", "verification")])

_rec = base_record()
_rec["items"][0]["amount"] = "100.00"
expect("K6: amount field is rejected", _rec, [("SCHEMA_ADDITIONAL_PROPERTY", "items[0]")])

_rec = base_record()
_rec["items"][0]["completeness_attested"] = True
expect("h: completeness-like field outside verification block is rejected", _rec, [("SCHEMA_ADDITIONAL_PROPERTY", "items[0]")])

_rec = base_record()
_rec["items"][0]["receivable_kind"] = "kurgusal_tur"
expect("rule 1: receivable_kind outside enum -> SCHEMA_ENUM", _rec, [("SCHEMA_ENUM", "items[0].receivable_kind")])

_rec = base_record()
_rec["creditors"][0]["role"] = "kurgusal_rol"
expect("rule 1: creditor role outside enum -> SCHEMA_ENUM", _rec, [("SCHEMA_ENUM", "creditors[0].role")])

_rec = base_record()
_rec["creditors"][0]["authority_type"] = "vergi_dairesi"
expect("rule 1: authority_type outside enum -> SCHEMA_ENUM", _rec, [("SCHEMA_ENUM", "creditors[0].authority_type")])

_rec = base_record()
_rec["items"][0]["subject_type"] = "kurgusal_vergi"
expect("c: subject_type outside closed list -> SCHEMA_ENUM (no new tax names)", _rec, [("SCHEMA_ENUM", "items[0].subject_type")])

_rec = base_record()
_rec["link_basis"]["kind"] = "kurgusal"
expect("rule 1: link_basis kind outside enum -> SCHEMA_ENUM", _rec, [("SCHEMA_ENUM", "link_basis.kind")])

_rec = debt_record()
_rec["link_basis"]["basis"] = "by_name"
expect("rule 1: link_basis basis outside enum -> SCHEMA_ENUM", _rec, [("SCHEMA_ENUM", "link_basis.basis")])

_rec = base_record()
_rec["verification"]["verification_state"] = "partially_verified"
expect("rule 1: verification_state outside {unverified, verified} -> SCHEMA_ENUM", _rec, [("SCHEMA_ENUM", "verification.verification_state")])

_rec = base_record()
_rec["schema_version"] = 2
expect("rule 1: schema_version 2 -> SCHEMA_CONST", _rec, [("SCHEMA_CONST", "schema_version")])

_rec = base_record()
_rec["schema_version"] = 1.0
expect("rule 1 strict: schema_version 1.0 -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "schema_version")])

_rec = base_record()
_rec["schema_version"] = True
expect("rule 1: schema_version True -> rejected", _rec, [("SCHEMA_CONST", "schema_version"), ("SCHEMA_TYPE", "schema_version")])

_rec = base_record()
_rec["items"][0]["page"] = 2.0
expect("rule 1 strict: page 2.0 -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "items[0].page")])

_rec = base_record()
_rec["creditors"][0]["page"] = 1.0
expect("rule 1 strict: creditor page 1.0 -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "creditors[0].page")])

_rec = base_record()
_rec["items"][0]["page"] = True
expect("rule 1: page True -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "items[0].page")])

_rec = base_record()
_rec["items"][0]["page"] = 0
expect("rule 1: page 0 -> SCHEMA_RANGE", _rec, [("SCHEMA_RANGE", "items[0].page")])

_rec = base_record()
_rec["items"][0]["page"] = "2"
expect("rule 1: page '2' -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "items[0].page")])

_rec = base_record()
_rec["record_id"] = "Synthetic_Rec"
expect("rule 1: id with uppercase -> SCHEMA_PATTERN", _rec, [("SCHEMA_PATTERN", "record_id")])

_rec = base_record()
_rec["record_id"] = "synthetic_rec\n"
_res = run(_rec)
check("rule 1: id with trailing newline is rejected", _res != [] and all(path == "record_id" for _, path in _res), detail=repr(_res))

_rec = base_record()
_rec["record_id"] = 5
expect("rule 1: non-string id -> only SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "record_id")])

_rec = base_record()
_rec["link_basis"]["debt_statement_document_id"] = 5
expect("rule 1: non-string nullable id -> only SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "link_basis.debt_statement_document_id")])

_rec = base_record()
_rec["record_id"] = "ab"
expect("rule 1: id shorter than 3 -> SCHEMA_LENGTH", _rec, [("SCHEMA_LENGTH", "record_id")])

_rec = base_record()
_rec["record_id"] = "a" * 129
expect("rule 1: id longer than 128 -> SCHEMA_LENGTH", _rec, [("SCHEMA_LENGTH", "record_id")])

_rec = base_record()
_rec["creditors"][0]["authority_name"] = "Kurgusal\nIdare"
expect("g: free text with line break -> SCHEMA_FORBIDDEN_CHARACTER", _rec, [("SCHEMA_FORBIDDEN_CHARACTER", "creditors[0].authority_name")])

for _char_label, _char in (
    ("CR", "\r"),
    ("TAB", "\t"),
    ("NUL", "\x00"),
    ("DEL", "\x7f"),
    ("NEL U+0085", "\u0085"),
    ("LINE SEPARATOR U+2028", "\u2028"),
    ("PARAGRAPH SEPARATOR U+2029", "\u2029"),
    ("ZERO WIDTH SPACE U+200B", "\u200b"),
    ("BOM U+FEFF", "\ufeff"),
    ("LEFT-TO-RIGHT ISOLATE U+2066", "\u2066"),
    ("POP DIRECTIONAL ISOLATE U+2069", "\u2069"),
    ("WORD JOINER U+2060", "\u2060"),
):
    _rec = base_record()
    _rec["creditors"][0]["authority_name"] = f"Kurgusal{_char}Idare"
    expect(
        f"g: free text with {_char_label} -> SCHEMA_FORBIDDEN_CHARACTER",
        _rec,
        [("SCHEMA_FORBIDDEN_CHARACTER", "creditors[0].authority_name")],
    )

_rec = base_record()
_rec["creditors"][0]["authority_name"] = "x" * 120
expect("g: free text of exactly 120 chars is valid", _rec, [])

_rec = base_record()
_rec["creditors"][0]["authority_name"] = "x" * 121
expect("g: free text of 121 chars -> SCHEMA_LENGTH", _rec, [("SCHEMA_LENGTH", "creditors[0].authority_name")])

_rec = base_record()
_rec["creditors"][0]["authority_name"] = "   "
expect("g: whitespace-only free text -> SCHEMA_PATTERN (needs a visible char)", _rec, [("SCHEMA_PATTERN", "creditors[0].authority_name")])

_rec = base_record()
_rec["creditors"][0]["authority_name"] = ""
expect("g: empty free text -> SCHEMA_LENGTH", _rec, [("SCHEMA_LENGTH", "creditors[0].authority_name")])

_rec = base_record()
_rec["creditors"][0]["authority_name"] = 5
expect("g: non-string free text -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "creditors[0].authority_name")])

_rec = base_record()
_rec["items"][1]["period"]["label"] = "Kurgusal\ndonem"
expect("f/g: period label with line break -> SCHEMA_FORBIDDEN_CHARACTER", _rec, [("SCHEMA_FORBIDDEN_CHARACTER", "items[1].period.label")])

_rec = debt_record()
_rec["link_basis"]["description"] = "y" * 121
expect("g: link_basis description too long -> SCHEMA_LENGTH", _rec, [("SCHEMA_LENGTH", "link_basis.description")])

_rec = base_record()
_rec["items"][0]["tax_code"] = "A" * 17
expect("f: tax_code longer than 16 -> SCHEMA_LENGTH", _rec, [("SCHEMA_LENGTH", "items[0].tax_code")])

_rec = base_record()
_rec["items"][0]["tax_code"] = "A" * 16
expect("f: tax_code of 16 letters/digits is valid", _rec, [])

_rec = base_record()
_rec["items"][0]["tax_code"] = "00-1"
expect("f: tax_code with dash -> SCHEMA_PATTERN", _rec, [("SCHEMA_PATTERN", "items[0].tax_code")])

_rec = base_record()
_rec["items"][0]["tax_code"] = "001\n"
_res = run(_rec)
check("f: tax_code with trailing newline is rejected", _res != [] and all(path == "items[0].tax_code" for _, path in _res), detail=repr(_res))

_rec = base_record()
_rec["items"][0]["tax_code"] = "\u0661\u0662"
expect("f: tax_code with non-ASCII digits -> SCHEMA_PATTERN", _rec, [("SCHEMA_PATTERN", "items[0].tax_code")])

_rec = base_record()
_rec["items"][0]["period"]["start_date"] = "2026-13-45"
expect("f: calendar-invalid date -> SCHEMA_DATE_INVALID", _rec, [("SCHEMA_DATE_INVALID", "items[0].period.start_date")])

_rec = base_record()
_rec["items"][0]["period"]["end_date"] = "2025-02-29"
expect("f: non-leap-year Feb 29 -> SCHEMA_DATE_INVALID", _rec, [("SCHEMA_DATE_INVALID", "items[0].period.end_date")])

_rec = base_record()
_rec["items"][0]["period"]["end_date"] = "2024-02-29"
expect("f: leap-year Feb 29 is valid", _rec, [])

_rec = base_record()
_rec["items"][0]["period"]["start_date"] = "2025-1-01"
expect("f: non-YYYY-MM-DD date -> SCHEMA_PATTERN", _rec, [("SCHEMA_PATTERN", "items[0].period.start_date")])

_rec = base_record()
_rec["items"][0]["period"]["start_date"] = "\u0662\u0660\u0662\u0665-01-01"
expect("f: date with non-ASCII digits -> SCHEMA_PATTERN", _rec, [("SCHEMA_PATTERN", "items[0].period.start_date")])

_rec = base_record()
_rec["items"][0]["period"]["start_date"] = "2025-01-01\n"
_res = run(_rec)
check(
    "f: date with trailing newline is rejected by the schema itself (not only by the strict calendar check)",
    _res != []
    and all(path == "items[0].period.start_date" for _, path in _res)
    and all(code.startswith("SCHEMA_") and code != "SCHEMA_DATE_INVALID" for code, _ in _res),
    detail=repr(_res),
)

_rec = base_record()
_rec["items"][0]["period"] = {"start_date": None, "end_date": None, "label": None}
expect("f: period with all fields null -> PERIOD_EMPTY", _rec, [("PERIOD_EMPTY", "items[0].period")])

_rec = base_record()
_rec["items"][0]["period"] = {"start_date": "2025-01-01", "end_date": None, "label": None}
expect("f: period with only start_date is valid", _rec, [])

_rec = base_record()
_rec["items"] = []
expect("rule 4: zero items -> SCHEMA_ITEMS", _rec, [("SCHEMA_ITEMS", "items")])

_rec = base_record()
_rec["creditors"] = []
expect("rule 4: zero creditors -> SCHEMA_ITEMS", _rec, [("SCHEMA_ITEMS", "creditors")])

_rec = base_record()
_rec["action_document_type"] = "vergi_ceza_ihbarnamesi"
expect("rule 3: action_document_type outside the four -> SCHEMA_ENUM", _rec, [("SCHEMA_ENUM", "action_document_type")])

for _bad_label, _bad_record in (
    ("list", []),
    ("None", None),
    ("string", "kurgusal"),
    ("int", 7),
):
    expect(f"rule 1: record of type {_bad_label} -> SCHEMA_TYPE at root, no exception", _bad_record, [("SCHEMA_TYPE", "record")])

_self_list = []
_self_list.append(_self_list)
expect("rule 1: self-referencing list record -> SCHEMA_TYPE at root, no exception", _self_list, [("SCHEMA_TYPE", "record")])

# "once sema" sirasi: sema hatasi varken anlam kurallari CALISMAZ.
_rec = base_record()
_rec["case_id"] = "synthetic_other_case"
_rec["items"][0]["receivable_kind"] = "kurgusal_tur"
expect(
    "order: schema error + case mismatch -> ONLY schema errors are returned",
    _rec,
    [("SCHEMA_ENUM", "items[0].receivable_kind")],
)
_rec = base_record()
_rec["case_id"] = "synthetic_other_case"
_rec["items"][0]["page"] = 2.0
expect(
    "order: strict-type error + case mismatch -> ONLY the strict-type error is returned",
    _rec,
    [("SCHEMA_TYPE", "items[0].page")],
)
_rec = verified_record()
_rec["items"][0]["receivable_kind"] = "kurgusal_tur"
expect(
    "order: schema error on a verified record in default mode -> no VERIFIED_NOT_ALLOWED_IN_MODE",
    _rec,
    [("SCHEMA_ENUM", "items[0].receivable_kind")],
)


# ============================================================
# 2b) DUZELTME TURU 1 - M-1 / L-1 / L-3 (bagimsiz inceleme bulgulari)
#   Etiketler bulgu kimligiyle baslar (M-1a ... L-3).
# ============================================================


def _text_field_record(field, value):
    """Bes serbest metin alanindan birine deger yazar; (kayit, yol) doner.
    Alan, degeri gerektiren yapida kurulur (ad zorunlu turler)."""
    record = base_record()
    if field == "authority_name":
        record["creditors"][0]["authority_type"] = "diger"
        record["creditors"][0]["authority_name"] = value
        return record, "creditors[0].authority_name"
    if field == "subject_other_name":
        record["items"][0]["subject_type"] = "diger"
        record["items"][0]["subject_other_name"] = value
        return record, "items[0].subject_other_name"
    if field == "related_subject_other_name":
        record["items"][1]["related_subject_type"] = "diger"
        record["items"][1]["related_subject_other_name"] = value
        return record, "items[1].related_subject_other_name"
    if field == "label":
        record["items"][1]["period"]["label"] = value
        return record, "items[1].period.label"
    if field == "description":
        record = debt_record()
        record["link_basis"]["description"] = value
        return record, "link_basis.description"
    raise KeyError(field)


_TEXT_FIELDS = (
    "authority_name",
    "subject_other_name",
    "related_subject_other_name",
    "label",
    "description",
)

# Kontrol: her alan kurgusal bir adla gecerli (asagidaki retler degerden).
for _field in _TEXT_FIELDS:
    _rec, _path = _text_field_record(_field, "Kurgusal Ad")
    expect(f"M-1a/L-3 control: {_field} with a normal name is valid", _rec, [])

# M-1a: iki kisa ad alaninda serbest metin sinirlari.
for _field in ("subject_other_name", "related_subject_other_name"):
    for _value_label, _value, _code in (
        ("empty string", "", "SCHEMA_LENGTH"),
        ("whitespace only", "   ", "SCHEMA_PATTERN"),
        ("line break", "Kurgusal\nAd", "SCHEMA_FORBIDDEN_CHARACTER"),
        ("121 chars", "x" * 121, "SCHEMA_LENGTH"),
    ):
        _rec, _path = _text_field_record(_field, _value)
        expect(f"M-1a g: {_field} {_value_label} -> {_code}", _rec, [(_code, _path)])
    _rec, _path = _text_field_record(_field, "x" * 120)
    expect(f"M-1a g: {_field} of exactly 120 chars is valid", _rec, [])

# M-1b: verification_audit_ref segment kalibi (teyit kipi acik).
for _value_label, _value, _expected in (
    ("uppercase", "Synthetic_Audit_001", [("SCHEMA_PATTERN", "verification.verification_audit_ref")]),
    ("with space", "synthetic audit 001", [("SCHEMA_PATTERN", "verification.verification_audit_ref")]),
    ("2 chars", "ab", [("SCHEMA_LENGTH", "verification.verification_audit_ref")]),
    ("129 chars", "a" * 129, [("SCHEMA_LENGTH", "verification.verification_audit_ref")]),
    ("trailing newline", "synthetic_audit_001\n", [("SCHEMA_FORBIDDEN_CHARACTER", "verification.verification_audit_ref")]),
    ("int", 5, [("SCHEMA_TYPE", "verification.verification_audit_ref")]),
):
    _rec = verified_record()
    _rec["verification"]["verification_audit_ref"] = _value
    expect(f"M-1b h: verification_audit_ref {_value_label} -> rejected", _rec, _expected, allow_verified=True)

for _value_label, _value in (("3 chars", "abc"), ("128 chars", "a" * 128)):
    _rec = verified_record()
    _rec["verification"]["verification_audit_ref"] = _value
    expect(f"M-1b h: verification_audit_ref {_value_label} is valid", _rec, [], allow_verified=True)

# M-1c: alacakli sayfasi ve alacakli kanit sayfasi alt siniri.
for _page in (0, -1):
    _rec = base_record()
    _rec["creditors"][0]["page"] = _page
    expect(f"M-1c rule 5: creditors[0].page = {_page} -> SCHEMA_RANGE", _rec, [("SCHEMA_RANGE", "creditors[0].page")])
    _rec = verified_record()
    _rec["verification"]["creditors_evidence"][0]["page"] = _page
    expect(
        f"M-1c rule 10: creditors_evidence[0].page = {_page} -> SCHEMA_RANGE",
        _rec,
        [("SCHEMA_RANGE", "verification.creditors_evidence[0].page")],
        allow_verified=True,
    )

# M-1d: her kimlik alaninda buyuk harfli deger -> tam olarak tek
# SCHEMA_PATTERN. Ayni buyuk harfli anahtar documents icinde de VAR
# (red belge bulunamamasindan degil semadan gelmeli).
_UPPER_ID = "Synthetic_Upper_Id"


def _set_path(record, keys, value):
    node = record
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value


for _builder, _keys, _path, _kwargs in (
    (base_record, ("case_id",), "case_id", {}),
    (base_record, ("action_document_id",), "action_document_id", {}),
    (base_record, ("creditors", 0, "creditor_id"), "creditors[0].creditor_id", {}),
    (base_record, ("creditors", 0, "source_document_id"), "creditors[0].source_document_id", {}),
    (base_record, ("items", 0, "item_id"), "items[0].item_id", {}),
    (base_record, ("items", 0, "creditor_id"), "items[0].creditor_id", {}),
    (base_record, ("items", 0, "source_document_id"), "items[0].source_document_id", {}),
    (debt_record, ("link_basis", "debt_statement_document_id"), "link_basis.debt_statement_document_id", {}),
    (verified_record, ("verification", "items_evidence", 0, "item_id"), "verification.items_evidence[0].item_id", {"allow_verified": True}),
    (verified_record, ("verification", "items_evidence", 0, "evidence_document_id"), "verification.items_evidence[0].evidence_document_id", {"allow_verified": True}),
    (verified_record, ("verification", "creditors_evidence", 0, "creditor_id"), "verification.creditors_evidence[0].creditor_id", {"allow_verified": True}),
    (verified_record, ("verification", "creditors_evidence", 0, "evidence_document_id"), "verification.creditors_evidence[0].evidence_document_id", {"allow_verified": True}),
):
    _rec = _builder()
    _set_path(_rec, _keys, _UPPER_ID)
    _docs = make_documents()
    _docs[_UPPER_ID] = copy.deepcopy(_docs[ACTION_DOC])
    expect(f"M-1d rule 1: uppercase {_path} -> exactly SCHEMA_PATTERN", _rec, [("SCHEMA_PATTERN", _path)], documents=_docs, **_kwargs)

# M-1e: tax_code yalniz ASCII harf/rakam.
for _value_label, _value in (
    ("underscore", "00_1"),
    ("space", "00 1"),
    ("Turkish letter", "00\u00e71"),
):
    _rec = base_record()
    _rec["items"][0]["tax_code"] = _value
    expect(f"M-1e f: tax_code with {_value_label} -> SCHEMA_PATTERN", _rec, [("SCHEMA_PATTERN", "items[0].tax_code")])

# L-1: items_evidence sayfasinda kati tamsayi.
_rec = verified_record()
_rec["verification"]["items_evidence"][0]["page"] = 2.0
expect("L-1 rule 10 strict: items_evidence page 2.0 -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "verification.items_evidence[0].page")], allow_verified=True)

# L-1: yazarin ekledigi yasak karakterler (metin icinde).
for _char_label, _char in (
    ("SOFT HYPHEN U+00AD", "\u00ad"),
    ("LEFT-TO-RIGHT MARK U+200E", "\u200e"),
    ("LEFT-TO-RIGHT EMBEDDING U+202A", "\u202a"),
    ("RIGHT-TO-LEFT OVERRIDE U+202E", "\u202e"),
    ("INVISIBLE SEPARATOR U+2063", "\u2063"),
):
    _rec, _path = _text_field_record("authority_name", f"Kurgusal{_char}Idare")
    expect(f"L-1 g: free text with {_char_label} -> SCHEMA_FORBIDDEN_CHARACTER", _rec, [("SCHEMA_FORBIDDEN_CHARACTER", _path)])

# L-3 (secenek A): yeni yasak bloklar (metin icinde; harf sarti
# karsilandigi icin red yalniz yasak bloktan gelir).
for _char_label, _char in (
    ("SURROGATE U+D800", "\ud800"),
    ("SURROGATE U+DFFF", "\udfff"),
    ("ARABIC LETTER MARK U+061C", "\u061c"),
    ("INHIBIT SYMMETRIC SWAPPING U+206A", "\u206a"),
    ("NOMINAL DIGIT SHAPES U+206F", "\u206f"),
    ("INTERLINEAR ANNOTATION ANCHOR U+FFF9", "\ufff9"),
    ("INTERLINEAR ANNOTATION TERMINATOR U+FFFB", "\ufffb"),
    ("NONCHARACTER U+FFFE", "\ufffe"),
    ("NONCHARACTER U+FFFF", "\uffff"),
):
    _rec, _path = _text_field_record("authority_name", f"Kurgusal{_char}Idare")
    expect(f"L-3 g: free text with {_char_label} -> SCHEMA_FORBIDDEN_CHARACTER", _rec, [("SCHEMA_FORBIDDEN_CHARACTER", _path)])

# L-3: tek basina gorunmez / yazilamaz kod noktasi ad olamaz.
for _char_label, _char, _code in (
    ("U+D800", "\ud800", "SCHEMA_FORBIDDEN_CHARACTER"),
    ("U+E000", "\ue000", "SCHEMA_PATTERN"),
    ("U+FFFE", "\ufffe", "SCHEMA_FORBIDDEN_CHARACTER"),
    ("U+FFFF", "\uffff", "SCHEMA_FORBIDDEN_CHARACTER"),
    ("U+061C", "\u061c", "SCHEMA_FORBIDDEN_CHARACTER"),
    ("U+206A", "\u206a", "SCHEMA_FORBIDDEN_CHARACTER"),
    ("U+206F", "\u206f", "SCHEMA_FORBIDDEN_CHARACTER"),
    ("U+FFF9", "\ufff9", "SCHEMA_FORBIDDEN_CHARACTER"),
    ("U+3164", "\u3164", "SCHEMA_PATTERN"),
    ("U+115F", "\u115f", "SCHEMA_PATTERN"),
    ("U+180E", "\u180e", "SCHEMA_PATTERN"),
    ("U+2800", "\u2800", "SCHEMA_PATTERN"),
    ("U+FFA0", "\uffa0", "SCHEMA_PATTERN"),
    ("U+034F", "\u034f", "SCHEMA_PATTERN"),
    ("U+FE0F", "\ufe0f", "SCHEMA_PATTERN"),
    ("U+17B5", "\u17b5", "SCHEMA_PATTERN"),
    ("U+E0020", "\U000e0020", "SCHEMA_PATTERN"),
    ("U+1D173", "\U0001d173", "SCHEMA_PATTERN"),
    ("punctuation only", "-.,'()/", "SCHEMA_PATTERN"),
    ("single dot", ".", "SCHEMA_PATTERN"),
):
    _rec, _path = _text_field_record("authority_name", _char)
    expect(f"L-3 g: name made only of {_char_label} -> {_code}", _rec, [(_code, _path)])

# L-3: harf/rakam sarti bes serbest metin alaninin hepsinde.
for _field in _TEXT_FIELDS:
    _rec, _path = _text_field_record(_field, "\u3164")
    expect(f"L-3 g: {_field} made only of U+3164 -> SCHEMA_PATTERN", _rec, [("SCHEMA_PATTERN", _path)])

# L-3: normal Turkce adlar ve tek harf / tek rakam KABUL.
for _name_label, _name in (
    ("Kurgusal Malmudurlugu (Turkish)", "Kurgusal Malm\u00fcd\u00fcrl\u00fc\u011f\u00fc"),
    ("Kurgusal Il Ozel Idaresi (Turkish)", "Kurgusal \u0130l \u00d6zel \u0130daresi"),
    ("Kurgusal Guesioc Vergi Dairesi (Turkish)", "Kurgusal \u011e\u00fc\u015f\u0131\u00f6\u00e7 Vergi Dairesi"),
    ("single digit 7", "7"),
):
    _rec, _path = _text_field_record("authority_name", _name)
    expect(f"L-3 g: name {_name_label} is valid", _rec, [])

for _letter in "\u00c7\u011e\u0130\u00d6\u015e\u00dc\u00e7\u011f\u0131\u00f6\u015f\u00fc":
    _rec, _path = _text_field_record("authority_name", _letter)
    expect(f"L-3 g: name of the single Turkish letter U+{ord(_letter):04X} is valid", _rec, [])

# ============================================================
# 2c) DUZELTME TURU 2 - M-A / O-C (yeniden inceleme 1 bulgulari)
#   Etiketler bulgu kimligiyle baslar (M-A, O-C). Kod noktalari
#   yalniz sayisal sabit + chr() ile uretilir (kaynak saf ASCII).
# ============================================================

# M-A: onaydaki bes yasak araligin HER kod noktasi, harf sarti
# karsilanmis bir adin icinde -> tam olarak tek
# SCHEMA_FORBIDDEN_CHARACTER. Aralik basina TEK toplu kontrol;
# denenen sayi sabit uzunlukla karsilastirilir.
_MA_EXPECTED = [("SCHEMA_FORBIDDEN_CHARACTER", "creditors[0].authority_name")]
for _ma_label, _ma_first, _ma_last, _ma_size in (
    ("U+D800-U+DFFF", 0xD800, 0xDFFF, 2048),
    ("U+061C", 0x061C, 0x061C, 1),
    ("U+206A-U+206F", 0x206A, 0x206F, 6),
    ("U+FFF9-U+FFFB", 0xFFF9, 0xFFFB, 3),
    ("U+FFFE-U+FFFF", 0xFFFE, 0xFFFF, 2),
):
    _ma_tried = 0
    _ma_bad = []
    for _ma_cp in range(_ma_first, _ma_last + 1):
        _ma_tried += 1
        try:
            _rec, _path = _text_field_record("authority_name", "Kurgusal" + chr(_ma_cp) + "Idare")
            _ma_ok = run(_rec) == _MA_EXPECTED
        except Exception:  # noqa: BLE001
            _ma_ok = False
        if not _ma_ok:
            _ma_bad.append(_ma_cp)
    check(
        f"M-A range {_ma_label} ({_ma_size}): every code point inside a name -> SCHEMA_FORBIDDEN_CHARACTER",
        _ma_bad == [] and _ma_tried == _ma_size,
        detail="tried=%d nonconforming=%d first=%s" % (
            _ma_tried,
            len(_ma_bad),
            ",".join("U+%04X" % _cp for _cp in _ma_bad[:5]),
        ),
    )

# O-C: yalniz buyuk ASCII harfli ad gecerli.
_rec, _path = _text_field_record("authority_name", "KDV")
expect("O-C: upper-case ASCII only name 'KDV' -> valid", _rec, [])


# ============================================================
# 3) KURAL 2 - DOSYA BAGI
# ============================================================

expect("rule 2: case_id mismatch -> CASE_ID_MISMATCH", base_record(), [("CASE_ID_MISMATCH", "case_id")], case_id="synthetic_case_other")
expect("rule 2: case_id differing only in case -> CASE_ID_MISMATCH", base_record(), [("CASE_ID_MISMATCH", "case_id")], case_id=CASE_ID.upper())


# ============================================================
# 4) KURAL 3 - ISLEM BELGESI
# ============================================================

_docs = make_documents()
del _docs[ACTION_DOC]
_rec = base_record()
_res = expect(
    "rule 3: action document not in documents -> ACTION_DOCUMENT_NOT_FOUND (+ rule 5 source errors)",
    _rec,
    [
        ("ACTION_DOCUMENT_NOT_FOUND", "action_document_id"),
        ("DOCUMENT_NOT_FOUND", "creditors[0].source_document_id"),
        ("DOCUMENT_NOT_FOUND", "items[0].source_document_id"),
        ("DOCUMENT_NOT_FOUND", "items[1].source_document_id"),
    ],
    documents=_docs,
)

for _active_label, _active_value in (
    ("False", False),
    ("string 'false'", "false"),
    ("string 'True'", "True"),
    ("int 1", 1),
    ("None", None),
):
    _docs = make_documents()
    _docs[ACTION_DOC]["active"] = _active_value
    expect(
        f"i2: action document active={_active_label} is NOT active",
        base_record(),
        [
            ("ACTION_DOCUMENT_NOT_ACTIVE", "action_document_id"),
            ("DOCUMENT_NOT_ACTIVE", "creditors[0].source_document_id"),
            ("DOCUMENT_NOT_ACTIVE", "items[0].source_document_id"),
            ("DOCUMENT_NOT_ACTIVE", "items[1].source_document_id"),
        ],
        documents=_docs,
    )

_docs = make_documents()
_docs[ACTION_DOC]["document_type"] = "borcluya_haciz_bildirimi"
expect("rule 3: document type differs from action_document_type -> ACTION_DOCUMENT_TYPE_MISMATCH", base_record(), [("ACTION_DOCUMENT_TYPE_MISMATCH", "action_document_type")], documents=_docs)

_docs = make_documents()
_docs[ACTION_DOC]["document_type"] = "vergi_ceza_ihbarnamesi"
expect("rule 3: document type outside the four -> ACTION_DOCUMENT_TYPE_UNSUPPORTED", base_record(), [("ACTION_DOCUMENT_TYPE_UNSUPPORTED", "action_document_id")], documents=_docs)

_docs = make_documents()
_docs[ACTION_DOC]["document_type"] = "  ODEME_EMRI \t"
expect("rule 3: document type normalised (strip + casefold) before comparison", base_record(), [], documents=_docs)

for _dt_label, _dt_doc, _dt_value, _dt_record in (
    ("action document int", ACTION_DOC, 5, base_record),
    ("action document None", ACTION_DOC, None, base_record),
    ("action document bytes", ACTION_DOC, b"odeme_emri", base_record),
    ("debt statement int (referenced)", STATEMENT_DOC, 5, debt_record),
    ("debt statement list (referenced)", STATEMENT_DOC, ["kurgusal"], debt_record),
    ("unreferenced document int", UNRELATED_DOC, 5, base_record),
):
    _docs = make_documents()
    _docs[_dt_doc]["document_type"] = _dt_value
    expect(
        f"i2: non-string document_type on {_dt_label} -> DOCUMENT_TYPE_INVALID (every entry, fail-closed)",
        _dt_record(),
        [("DOCUMENT_TYPE_INVALID", "argument.documents")],
        documents=_docs,
    )

for _doc_type in sorted(rrv.SUPPORTED_ACTION_DOCUMENT_TYPES):
    _docs = make_documents()
    _docs[ACTION_DOC]["document_type"] = _doc_type
    _rec = base_record()
    _rec["action_document_type"] = _doc_type
    expect(f"rule 3: supported action document type {_doc_type} is valid", _rec, [], documents=_docs)


# ============================================================
# 5) KURAL 4 - KIMLIKLER
# ============================================================

_rec = base_record()
_rec["items"][1]["item_id"] = "synthetic_item_1"
expect("rule 4: duplicate item_id -> DUPLICATE_ITEM_ID", _rec, [("DUPLICATE_ITEM_ID", "items[1].item_id")])

_rec = base_record()
_rec["creditors"].append(copy.deepcopy(_rec["creditors"][0]))
expect("rule 4: duplicate creditor_id -> DUPLICATE_CREDITOR_ID", _rec, [("DUPLICATE_CREDITOR_ID", "creditors[1].creditor_id")])

_rec = base_record()
_second = copy.deepcopy(_rec["creditors"][0])
_second["creditor_id"] = "synthetic_cr_2"
_second["role"] = "tahsil_eden"
_rec["creditors"].append(_second)
expect("rule 4: two distinct creditors (multiple creditors) is valid", _rec, [])


# ============================================================
# 6) KURAL 5 - KAYNAK VE SAYFA
# ============================================================

_rec = base_record()
_rec["items"][0]["source_document_id"] = "synthetic_doc_missing"
expect(
    "rule 5: item source document not in documents -> DOCUMENT_NOT_FOUND (+ not allowed)",
    _rec,
    [("DOCUMENT_NOT_FOUND", "items[0].source_document_id"), ("SOURCE_DOCUMENT_NOT_ALLOWED", "items[0].source_document_id")],
)

_docs = make_documents()
_docs[STATEMENT_DOC]["active"] = "false"
_rec = debt_record()
expect(
    "rule 5/6: inactive debt statement as source -> DOCUMENT_NOT_ACTIVE on source and link",
    _rec,
    [("DOCUMENT_NOT_ACTIVE", "items[1].source_document_id"), ("DOCUMENT_NOT_ACTIVE", "link_basis.debt_statement_document_id")],
    documents=_docs,
)

for _pc_label, _pc_value in (
    ("True", True),
    ("False", False),
    ("0", 0),
    ("-1", -1),
    ("3.5", 3.5),
    ("3.0", 3.0),
    ("string '3'", "3"),
    ("None", None),
):
    _docs = make_documents()
    _docs[ACTION_DOC]["page_count"] = _pc_value
    expect(
        f"rule 5 / i2: page_count={_pc_label} -> PAGE_COUNT_UNKNOWN (fail-closed)",
        base_record(),
        [
            ("PAGE_COUNT_UNKNOWN", "creditors[0].page"),
            ("PAGE_COUNT_UNKNOWN", "items[0].page"),
            ("PAGE_COUNT_UNKNOWN", "items[1].page"),
        ],
        documents=_docs,
    )

_rec = base_record()
_rec["items"][0]["page"] = 4
expect("rule 5: page > page_count -> PAGE_OUT_OF_RANGE", _rec, [("PAGE_OUT_OF_RANGE", "items[0].page")])

_rec = base_record()
_rec["creditors"][0]["page"] = 4
expect("rule 5: creditor page > page_count -> PAGE_OUT_OF_RANGE", _rec, [("PAGE_OUT_OF_RANGE", "creditors[0].page")])

_rec = base_record()
_rec["items"][0]["page"] = 3
expect("rule 5: page == page_count is valid (boundary)", _rec, [])

_rec = base_record()
_rec["items"][1]["source_document_id"] = STATEMENT_DOC
expect("rule 5: same_document but item read from another document -> SOURCE_DOCUMENT_NOT_ALLOWED", _rec, [("SOURCE_DOCUMENT_NOT_ALLOWED", "items[1].source_document_id")])

_rec = base_record()
_rec["creditors"][0]["source_document_id"] = UNRELATED_DOC
expect("rule 5: same_document but creditor read from another document -> SOURCE_DOCUMENT_NOT_ALLOWED", _rec, [("SOURCE_DOCUMENT_NOT_ALLOWED", "creditors[0].source_document_id")])

_rec = debt_record()
_rec["items"][0]["source_document_id"] = UNRELATED_DOC
expect("rule 5: debt_statement but item from an unrelated document -> SOURCE_DOCUMENT_NOT_ALLOWED", _rec, [("SOURCE_DOCUMENT_NOT_ALLOWED", "items[0].source_document_id")])

_rec = debt_record()
_rec["creditors"][0]["source_document_id"] = STATEMENT_DOC
_rec["creditors"][0]["page"] = 4
expect("rule 5: debt_statement allows creditor read from the debt statement", _rec, [])

_rec = debt_record()
_rec["items"][1]["page"] = 6
expect("rule 5: page beyond the debt statement's page_count -> PAGE_OUT_OF_RANGE", _rec, [("PAGE_OUT_OF_RANGE", "items[1].page")])


# ============================================================
# 7) KURAL 6 - BORC DOKUMU BAGI
# ============================================================

_rec = debt_record()
_rec["link_basis"]["debt_statement_document_id"] = None
_rec["items"][1]["source_document_id"] = ACTION_DOC
_rec["items"][1]["page"] = 3
expect("rule 6: debt_statement without document id -> DEBT_STATEMENT_DOCUMENT_REQUIRED", _rec, [("DEBT_STATEMENT_DOCUMENT_REQUIRED", "link_basis.debt_statement_document_id")])

_rec = debt_record()
_rec["link_basis"]["debt_statement_document_id"] = ACTION_DOC
_rec["items"][1]["source_document_id"] = ACTION_DOC
_rec["items"][1]["page"] = 3
expect("rule 6: debt statement equal to the action document -> DEBT_STATEMENT_SAME_AS_ACTION", _rec, [("DEBT_STATEMENT_SAME_AS_ACTION", "link_basis.debt_statement_document_id")])

_docs = make_documents()
del _docs[STATEMENT_DOC]
_rec = debt_record()
_rec["items"][1]["source_document_id"] = ACTION_DOC
_rec["items"][1]["page"] = 3
expect("rule 6: debt statement not in documents -> DOCUMENT_NOT_FOUND", _rec, [("DOCUMENT_NOT_FOUND", "link_basis.debt_statement_document_id")], documents=_docs)

_docs = make_documents()
_docs[STATEMENT_DOC]["active"] = 1
_rec = debt_record()
_rec["items"][1]["source_document_id"] = ACTION_DOC
_rec["items"][1]["page"] = 3
expect("rule 6 / i2: debt statement active=1 is not active -> DOCUMENT_NOT_ACTIVE", _rec, [("DOCUMENT_NOT_ACTIVE", "link_basis.debt_statement_document_id")], documents=_docs)

_rec = debt_record()
_rec["link_basis"]["basis"] = None
expect("rule 6: debt_statement without basis -> LINK_BASIS_BASIS_REQUIRED", _rec, [("LINK_BASIS_BASIS_REQUIRED", "link_basis.basis")])

_rec = debt_record()
_rec["link_basis"]["basis"] = "other"
_rec["link_basis"]["description"] = None
expect("e: basis 'other' without description -> LINK_BASIS_DESCRIPTION_REQUIRED", _rec, [("LINK_BASIS_DESCRIPTION_REQUIRED", "link_basis.description")])

_rec = debt_record()
_rec["link_basis"]["basis"] = "by_file_no"
_rec["link_basis"]["description"] = None
expect("L-4 e: basis by_file_no without description -> LINK_BASIS_DESCRIPTION_REQUIRED", _rec, [("LINK_BASIS_DESCRIPTION_REQUIRED", "link_basis.description")])

# L-4 (duzeltme turu 1, secenek A): debt_statement kaydinda aciklama
# dayanak (basis) ne olursa olsun zorunlu.
_rec = debt_record()
_rec["link_basis"]["basis"] = "by_tracking_no"
_rec["link_basis"]["description"] = None
expect("L-4 e: basis by_tracking_no without description -> LINK_BASIS_DESCRIPTION_REQUIRED", _rec, [("LINK_BASIS_DESCRIPTION_REQUIRED", "link_basis.description")])

_rec = debt_record()
_rec["link_basis"]["basis"] = "by_tracking_no"
expect("L-4 e: basis by_tracking_no with description is valid", _rec, [])

_rec = debt_record()
_rec["link_basis"]["basis"] = "by_file_no"
expect("L-4 e: basis by_file_no with description is valid", _rec, [])

_rec = debt_record()
_rec["link_basis"]["basis"] = None
_rec["link_basis"]["description"] = None
expect(
    "L-4 e: debt_statement without basis and without description -> both LINK_BASIS_BASIS_REQUIRED and LINK_BASIS_DESCRIPTION_REQUIRED",
    _rec,
    [("LINK_BASIS_BASIS_REQUIRED", "link_basis.basis"), ("LINK_BASIS_DESCRIPTION_REQUIRED", "link_basis.description")],
)

_rec = debt_record()
_rec["link_basis"]["basis"] = "other"
expect("e: basis 'other' with description is valid", _rec, [])

for _field, _value in (
    ("debt_statement_document_id", STATEMENT_DOC),
    ("basis", "by_tracking_no"),
    ("description", "Kurgusal aciklama"),
):
    _rec = base_record()
    _rec["link_basis"][_field] = _value
    expect(f"rule 6: same_document with non-null {_field} -> LINK_BASIS_FIELD_NOT_NULL", _rec, [("LINK_BASIS_FIELD_NOT_NULL", f"link_basis.{_field}")])


# ============================================================
# 8) KURAL 7 - ALACAKLI REFERANSI
# ============================================================

_rec = base_record()
_rec["items"][0]["creditor_id"] = "synthetic_cr_missing"
expect("rule 7: item creditor_id not in creditors -> CREDITOR_NOT_FOUND", _rec, [("CREDITOR_NOT_FOUND", "items[0].creditor_id")])

_rec = base_record()
_rec["creditors"][0]["authority_type"] = "diger"
_rec["creditors"][0]["authority_name"] = None
expect("rule 7: authority_type diger without authority_name -> AUTHORITY_NAME_REQUIRED", _rec, [("AUTHORITY_NAME_REQUIRED", "creditors[0].authority_name")])

_rec = base_record()
_rec["creditors"][0]["authority_type"] = "diger"
_rec["creditors"][0]["authority_name"] = "Kurgusal Ozel Idare"
expect("rule 7: authority_type diger with authority_name is valid", _rec, [])

_rec = base_record()
_rec["creditors"][0]["authority_name"] = None
expect("rule 7: non-diger authority_type without name is valid", _rec, [])

for _authority_type in rrv.AUTHORITY_TYPES:
    for _role in rrv.CREDITOR_ROLES:
        _rec = base_record()
        _rec["creditors"][0]["authority_type"] = _authority_type
        _rec["creditors"][0]["role"] = _role
        expect(f"d: authority_type {_authority_type} + role {_role} is structurally valid", _rec, [])


# ============================================================
# 9) KURAL 8 - FER'I VE CEZA YAPISI (yalniz yapi)
# ============================================================

_rec = base_record()
_rec["items"][0]["subject_type"] = "gecikme_zammi"
expect("rule 8: asil item with a non-tax subject_type -> SUBJECT_TYPE_KIND_MISMATCH", _rec, [("SUBJECT_TYPE_KIND_MISMATCH", "items[0].subject_type")])

_rec = base_record()
_rec["items"][0]["related_subject_type"] = "gelir_vergisi"
expect("rule 8: asil item with related_subject_type -> RELATED_SUBJECT_TYPE_NOT_NULL", _rec, [("RELATED_SUBJECT_TYPE_NOT_NULL", "items[0].related_subject_type")])

_rec = base_record()
_rec["items"][1]["subject_type"] = "gelir_vergisi"
expect("rule 8: non-asil item whose subject_type is not its own kind -> SUBJECT_TYPE_KIND_MISMATCH", _rec, [("SUBJECT_TYPE_KIND_MISMATCH", "items[1].subject_type")])

_rec = base_record()
_rec["items"][1]["subject_type"] = "usulsuzluk_cezasi"
expect("rule 8: non-asil item with another kind's subject_type -> SUBJECT_TYPE_KIND_MISMATCH", _rec, [("SUBJECT_TYPE_KIND_MISMATCH", "items[1].subject_type")])

_rec = base_record()
del _rec["items"][1]["related_subject_type"]
expect("rule 8: non-asil item without the related_subject_type KEY -> SCHEMA_REQUIRED", _rec, [("SCHEMA_REQUIRED", "items[1].related_subject_type")])

_rec = base_record()
del _rec["items"][0]["related_subject_type"]
expect("rule 8: asil item without the related_subject_type KEY -> SCHEMA_REQUIRED (key always present)", _rec, [("SCHEMA_REQUIRED", "items[0].related_subject_type")])

_rec = base_record()
_rec["items"][1]["related_subject_type"] = None
expect("rule 8: non-asil item with related_subject_type null (not determinable) is valid", _rec, [])

_rec = base_record()
_rec["items"][1]["related_subject_type"] = "ozel_tuketim_vergisi"
expect("rule 8: penalty related to OTV is structurally valid (no classification)", _rec, [])

_rec = base_record()
_rec["items"][1]["related_subject_type"] = "gecikme_zammi"
expect("c: related_subject_type outside the first 13 values -> SCHEMA_ENUM", _rec, [("SCHEMA_ENUM", "items[1].related_subject_type")])

_rec = base_record()
_rec["items"][0]["subject_type"] = "diger"
expect("rule 8: subject_type diger without subject_other_name -> SUBJECT_OTHER_NAME_REQUIRED", _rec, [("SUBJECT_OTHER_NAME_REQUIRED", "items[0].subject_other_name")])

_rec = base_record()
_rec["items"][0]["subject_type"] = "diger"
_rec["items"][0]["subject_other_name"] = "Kurgusal Ozel Vergi"
expect("rule 8: subject_type diger with subject_other_name is valid", _rec, [])

_rec = base_record()
_rec["items"][0]["subject_other_name"] = "Kurgusal Ad"
expect("rule 8: subject_other_name on a non-diger subject -> SUBJECT_OTHER_NAME_NOT_ALLOWED", _rec, [("SUBJECT_OTHER_NAME_NOT_ALLOWED", "items[0].subject_other_name")])

_rec = base_record()
_rec["items"][1]["related_subject_type"] = "diger"
expect("rule 8: related_subject_type diger without name -> RELATED_SUBJECT_OTHER_NAME_REQUIRED", _rec, [("RELATED_SUBJECT_OTHER_NAME_REQUIRED", "items[1].related_subject_other_name")])

_rec = base_record()
_rec["items"][1]["related_subject_type"] = "diger"
_rec["items"][1]["related_subject_other_name"] = "Kurgusal Ilgili Vergi"
expect("rule 8: related_subject_type diger with name is valid", _rec, [])

_rec = base_record()
_rec["items"][1]["related_subject_type"] = None
_rec["items"][1]["related_subject_other_name"] = "Kurgusal Ad"
expect("rule 8: related name with null related_subject_type -> RELATED_SUBJECT_OTHER_NAME_NOT_ALLOWED", _rec, [("RELATED_SUBJECT_OTHER_NAME_NOT_ALLOWED", "items[1].related_subject_other_name")])

_rec = base_record()
_rec["items"][0]["related_subject_other_name"] = "Kurgusal Ad"
expect("rule 8: related name on an asil item -> RELATED_SUBJECT_OTHER_NAME_NOT_ALLOWED", _rec, [("RELATED_SUBJECT_OTHER_NAME_NOT_ALLOWED", "items[0].related_subject_other_name")])

_rec = base_record()
_rec["items"][1]["receivable_kind"] = "diger"
_rec["items"][1]["subject_type"] = "diger"
_rec["items"][1]["subject_other_name"] = "Kurgusal Diger Alacak"
expect("rule 8: kind diger -> subject_type diger with name is valid", _rec, [])

_rec = base_record()
_rec["items"][1]["receivable_kind"] = "diger"
_rec["items"][1]["subject_type"] = "diger"
expect("rule 8: kind diger without subject_other_name -> SUBJECT_OTHER_NAME_REQUIRED", _rec, [("SUBJECT_OTHER_NAME_REQUIRED", "items[1].subject_other_name")])

for _tax_subject in rrv.TAX_SUBJECT_TYPES:
    _rec = base_record()
    _rec["items"][0]["subject_type"] = _tax_subject
    if _tax_subject == "diger":
        _rec["items"][0]["subject_other_name"] = "Kurgusal Ad"
    expect(f"c: asil item with subject_type {_tax_subject} is structurally valid", _rec, [])

for _kind in rrv.RECEIVABLE_KINDS:
    if _kind == "asil":
        continue
    for _related in list(rrv.TAX_SUBJECT_TYPES) + [None]:
        _rec = base_record()
        _item = _rec["items"][1]
        _item["receivable_kind"] = _kind
        _item["subject_type"] = rrv.KIND_TO_SUBJECT_TYPE[_kind]
        _item["subject_other_name"] = "Kurgusal Ad" if _kind == "diger" else None
        _item["related_subject_type"] = _related
        _item["related_subject_other_name"] = "Kurgusal Ilgili" if _related == "diger" else None
        expect(f"c: kind {_kind} related {_related} is structurally valid", _rec, [])


# ============================================================
# 10) KURAL 9 - TEYIT KIPI (uc kip)
# ============================================================

expect("rule 9 mode A: unverified record, default mode -> valid", base_record(), [])
expect(
    "rule 9 mode B: verified record, default mode -> VERIFIED_NOT_ALLOWED_IN_MODE",
    verified_record(),
    [("VERIFIED_NOT_ALLOWED_IN_MODE", "verification.verification_state")],
)
expect(
    "rule 9 mode B: verified record, allow_verified=False explicit -> VERIFIED_NOT_ALLOWED_IN_MODE",
    verified_record(),
    [("VERIFIED_NOT_ALLOWED_IN_MODE", "verification.verification_state")],
    allow_verified=False,
)
expect("rule 9 mode C: verified record, allow_verified=True -> valid", verified_record(), [], allow_verified=True)

for _flag_label, _flag in (
    ("string 'True'", "True"),
    ("string 'False'", "False"),
    ("int 1", 1),
    ("None", None),
):
    expect(
        f"rule 9 strict: allow_verified={_flag_label} does NOT enable verified mode",
        verified_record(),
        [("VERIFIED_NOT_ALLOWED_IN_MODE", "verification.verification_state")],
        allow_verified=_flag,
    )

_rec = verified_record()
_rec["verification"]["items_evidence"] = None
expect(
    "rule 9: verified record in default mode does not run rule 10 (only the mode error)",
    _rec,
    [("VERIFIED_NOT_ALLOWED_IN_MODE", "verification.verification_state")],
)

_filled_values = {
    "completeness_attested": False,
    "items_evidence": [],
    "creditors_evidence": [],
    "verification_audit_ref": "synthetic_audit_001",
}
for _field in rrv.VERIFICATION_NULL_WHEN_UNVERIFIED_FIELDS:
    for _mode_label, _mode in (("default mode", False), ("allow_verified=True", True)):
        _rec = base_record()
        _rec["verification"][_field] = copy.deepcopy(_filled_values[_field])
        expect(
            f"rule 9: unverified record with non-null {_field} ({_mode_label}) -> VERIFICATION_FIELD_NOT_NULL",
            _rec,
            [("VERIFICATION_FIELD_NOT_NULL", f"verification.{_field}")],
            allow_verified=_mode,
        )


# ============================================================
# 11) KURAL 10 - TEYITLI BLOK YAPISI (allow_verified=True)
# ============================================================

_rec = verified_record()
_rec["verification"]["verification_audit_ref"] = None
expect("rule 10: verified without verification_audit_ref -> VERIFICATION_AUDIT_REF_REQUIRED", _rec, [("VERIFICATION_AUDIT_REF_REQUIRED", "verification.verification_audit_ref")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["completeness_attested"] = None
expect("rule 10: verified without completeness_attested -> COMPLETENESS_ATTESTED_REQUIRED", _rec, [("COMPLETENESS_ATTESTED_REQUIRED", "verification.completeness_attested")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["completeness_attested"] = "true"
expect("rule 10: completeness_attested as string -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "verification.completeness_attested")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["completeness_attested"] = 1
expect("rule 10: completeness_attested as int 1 -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "verification.completeness_attested")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["items_evidence"] = None
expect(
    "rule 10: verified without items_evidence -> ITEMS_EVIDENCE_REQUIRED",
    _rec,
    [("ITEMS_EVIDENCE_REQUIRED", "verification.items_evidence")],
    allow_verified=True,
)

_rec = verified_record()
_rec["verification"]["creditors_evidence"] = None
expect(
    "rule 10: verified without creditors_evidence -> CREDITORS_EVIDENCE_REQUIRED",
    _rec,
    [("CREDITORS_EVIDENCE_REQUIRED", "verification.creditors_evidence")],
    allow_verified=True,
)

_rec = verified_record()
del _rec["verification"]["items_evidence"][1]
expect("rule 10: one item without evidence -> EVIDENCE_MISSING", _rec, [("EVIDENCE_MISSING", "items[1].item_id")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["creditors_evidence"] = []
expect("rule 10: creditor without evidence -> EVIDENCE_MISSING", _rec, [("EVIDENCE_MISSING", "creditors[0].creditor_id")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["items_evidence"] = []
expect(
    "rule 10: empty items_evidence -> EVIDENCE_MISSING for every item",
    _rec,
    [("EVIDENCE_MISSING", "items[0].item_id"), ("EVIDENCE_MISSING", "items[1].item_id")],
    allow_verified=True,
)

_rec = verified_record()
_rec["verification"]["items_evidence"].append(copy.deepcopy(_rec["verification"]["items_evidence"][0]))
expect("rule 10: two evidence entries for one item -> EVIDENCE_DUPLICATE_TARGET", _rec, [("EVIDENCE_DUPLICATE_TARGET", "verification.items_evidence[2].item_id")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["creditors_evidence"].append(
    {"creditor_id": "synthetic_cr_ghost", "evidence_document_id": ACTION_DOC, "page": 1}
)
expect("rule 10: evidence for an unknown creditor -> EVIDENCE_TARGET_NOT_FOUND", _rec, [("EVIDENCE_TARGET_NOT_FOUND", "verification.creditors_evidence[1].creditor_id")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["items_evidence"][0]["item_id"] = "synthetic_item_ghost"
expect(
    "rule 10: evidence for an unknown item -> EVIDENCE_TARGET_NOT_FOUND + EVIDENCE_MISSING",
    _rec,
    [("EVIDENCE_MISSING", "items[0].item_id"), ("EVIDENCE_TARGET_NOT_FOUND", "verification.items_evidence[0].item_id")],
    allow_verified=True,
)

_rec = verified_record()
_rec["verification"]["items_evidence"][0]["evidence_document_id"] = "synthetic_doc_missing"
expect("rule 10: evidence document not in documents -> DOCUMENT_NOT_FOUND", _rec, [("DOCUMENT_NOT_FOUND", "verification.items_evidence[0].evidence_document_id")], allow_verified=True)

_docs = make_documents()
_docs[UNRELATED_DOC]["active"] = "false"
_rec = verified_record()
_rec["verification"]["creditors_evidence"][0]["evidence_document_id"] = UNRELATED_DOC
expect("rule 10 / i2: evidence document active='false' -> DOCUMENT_NOT_ACTIVE", _rec, [("DOCUMENT_NOT_ACTIVE", "verification.creditors_evidence[0].evidence_document_id")], documents=_docs, allow_verified=True)

for _pc_label, _pc_value in (("True", True), ("0", 0), ("3.5", 3.5), ("string '3'", "3"), ("None", None)):
    _docs = make_documents()
    _docs[UNRELATED_DOC]["page_count"] = _pc_value
    _rec = verified_record()
    _rec["verification"]["items_evidence"][0]["evidence_document_id"] = UNRELATED_DOC
    _rec["verification"]["items_evidence"][0]["page"] = 1
    expect(
        f"rule 10 / i2: evidence page_count={_pc_label} -> PAGE_COUNT_UNKNOWN",
        _rec,
        [("PAGE_COUNT_UNKNOWN", "verification.items_evidence[0].page")],
        documents=_docs,
        allow_verified=True,
    )

_rec = verified_record()
_rec["verification"]["items_evidence"][0]["page"] = 4
expect("rule 10: evidence page > page_count -> PAGE_OUT_OF_RANGE", _rec, [("PAGE_OUT_OF_RANGE", "verification.items_evidence[0].page")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["creditors_evidence"][0]["page"] = 2.0
expect("rule 10 strict: evidence page 2.0 -> SCHEMA_TYPE", _rec, [("SCHEMA_TYPE", "verification.creditors_evidence[0].page")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["items_evidence"][0]["page"] = 0
expect("rule 10: evidence page 0 -> SCHEMA_RANGE", _rec, [("SCHEMA_RANGE", "verification.items_evidence[0].page")], allow_verified=True)

_rec = verified_record()
_rec["verification"]["items_evidence"][0]["evidence_document_id"] = STATEMENT_DOC
_rec["verification"]["items_evidence"][0]["page"] = 5
expect("rule 10: evidence may cite any active document with a valid page (contract minimum)", _rec, [], allow_verified=True)

_res_true = run(verified_record(), allow_verified=True)
_rec = verified_record()
_rec["verification"]["completeness_attested"] = False
_res_false = run(_rec, allow_verified=True)
check("rule 10: completeness_attested True and False give the same result (no decision on value)", _res_true == _res_false == [], detail=repr((_res_true, _res_false)))


# ============================================================
# 12) ARGUMANLAR (i2) - bozuk tip, istisna yok
# ============================================================

for _docs_label, _docs_value in (
    ("None", None),
    ("list", []),
    ("string", "kurgusal"),
    ("tuple of pairs", ((ACTION_DOC, {}),)),
):
    expect(
        f"i2: documents={_docs_label} -> DOCUMENTS_ARGUMENT_INVALID",
        base_record(),
        [("DOCUMENTS_ARGUMENT_INVALID", "argument.documents")],
        documents=_docs_value,
    )

_docs = make_documents()
_docs[UNRELATED_DOC] = ["not", "a", "dict"]
expect("i2: a documents entry that is not a dict -> DOCUMENT_ENTRY_INVALID", base_record(), [("DOCUMENT_ENTRY_INVALID", "argument.documents")], documents=_docs)

for _missing_key in rrv.DOCUMENT_ENTRY_REQUIRED_KEYS:
    _docs = make_documents()
    del _docs[UNRELATED_DOC][_missing_key]
    expect(
        f"i2: a documents entry without {_missing_key} -> DOCUMENT_ENTRY_INVALID",
        base_record(),
        [("DOCUMENT_ENTRY_INVALID", "argument.documents")],
        documents=_docs,
    )

_docs = make_documents()
_docs[7] = {"document_type": "odeme_emri", "page_count": 1, "active": True}
expect("i2: a documents key that is not a string -> DOCUMENT_ENTRY_INVALID", base_record(), [("DOCUMENT_ENTRY_INVALID", "argument.documents")], documents=_docs)

_docs = make_documents()
_docs[UNRELATED_DOC]["kurgusal_ek_anahtar"] = 1
expect("i2: extra keys in a documents entry are tolerated", base_record(), [], documents=_docs)

expect("i2: empty documents dict -> action document not found", base_record(), [
    ("ACTION_DOCUMENT_NOT_FOUND", "action_document_id"),
    ("DOCUMENT_NOT_FOUND", "creditors[0].source_document_id"),
    ("DOCUMENT_NOT_FOUND", "items[0].source_document_id"),
    ("DOCUMENT_NOT_FOUND", "items[1].source_document_id"),
], documents={})

for _case_label, _case_value in (("None", None), ("int", 1), ("bytes", b"synthetic_case_b1")):
    expect(
        f"argument: case_id={_case_label} -> CASE_ID_ARGUMENT_INVALID",
        base_record(),
        [("CASE_ID_ARGUMENT_INVALID", "argument.case_id")],
        case_id=_case_value,
    )

expect(
    "argument: invalid case_id and documents together -> both argument errors, nothing else",
    base_record(),
    [("CASE_ID_ARGUMENT_INVALID", "argument.case_id"), ("DOCUMENTS_ARGUMENT_INVALID", "argument.documents")],
    case_id=None,
    documents=None,
)


class _ExplodingDocuments(dict):
    def get(self, *args, **kwargs):
        raise RuntimeError("kurgusal patlama")


expect(
    "rule 11: unexpected internal exception -> single fail-closed VALIDATOR_INTERNAL_ERROR (never empty, never raises)",
    base_record(),
    [("VALIDATOR_INTERNAL_ERROR", "record")],
    documents=_ExplodingDocuments(make_documents()),
)

_saved_schema_validator = rrv._SCHEMA_VALIDATOR
try:
    rrv._SCHEMA_VALIDATOR = None
    _unavailable_result = run(base_record())
finally:
    rrv._SCHEMA_VALIDATOR = _saved_schema_validator
check(
    "rule 11: schema not loaded -> single fail-closed SCHEMA_UNAVAILABLE (never empty)",
    _unavailable_result == [("SCHEMA_UNAVAILABLE", "record")],
    detail=repr(_unavailable_result),
)
check("rule 11: schema validator restored after the SCHEMA_UNAVAILABLE check", rrv._SCHEMA_VALIDATOR is _saved_schema_validator)


# ============================================================
# 13) KURAL 11 - GIRDI DEGISMEZ (derin kopya)
# ============================================================

_purity_cases = [
    ("unverified valid", base_record(), make_documents(), {}),
    ("debt valid", debt_record(), make_documents(), {}),
    ("verified default mode", verified_record(), make_documents(), {}),
    ("verified allow mode", verified_record(), make_documents(), {"allow_verified": True}),
]
_bad = base_record()
_bad["items"][0]["receivable_kind"] = "kurgusal_tur"
_purity_cases.append(("schema failing", _bad, make_documents(), {}))
_bad = verified_record()
_bad["verification"]["items_evidence"].append({"item_id": "synthetic_item_ghost", "evidence_document_id": ACTION_DOC, "page": 9})
_purity_cases.append(("rule 10 failing", _bad, make_documents(), {"allow_verified": True}))
_docs_bad = make_documents()
_docs_bad[ACTION_DOC]["page_count"] = "3"
_purity_cases.append(("page_count trap", base_record(), _docs_bad, {}))

for _label, _record, _documents, _kwargs in _purity_cases:
    _record_before = copy.deepcopy(_record)
    _documents_before = copy.deepcopy(_documents)
    run(_record, documents=_documents, **_kwargs)
    check(f"rule 11: record unchanged after validation ({_label})", _record == _record_before)
    check(f"rule 11: documents unchanged after validation ({_label})", _documents == _documents_before)

_res_a = run(base_record())
_res_b = run(base_record())
check("rule 11: repeated calls are deterministic", _res_a == _res_b == [])


# ============================================================
# 14) KURAL 11 - DOSYA OKUMAZ / YAZMAZ
#   Sahte fonksiyonlar kisa sureligine yerlestirilir ve finally ile
#   MUTLAKA geri alinir. audit hook ve alt surec KULLANILMAZ.
# ============================================================

_io_calls = []


def _forbidden_io(*args, **kwargs):
    _io_calls.append(1)
    raise RuntimeError("file access forbidden in this test")


_patch_targets = [
    (builtins, "open"),
    (io, "open"),
    (os, "open"),
    (pathlib.Path, "open"),
    (pathlib.Path, "read_text"),
    (pathlib.Path, "read_bytes"),
    (pathlib.Path, "write_text"),
    (pathlib.Path, "write_bytes"),
]

_io_scenarios = [
    ("mode A unverified", base_record(), {}, []),
    ("mode B verified default", verified_record(), {}, [("VERIFIED_NOT_ALLOWED_IN_MODE", "verification.verification_state")]),
    ("mode C verified allow", verified_record(), {"allow_verified": True}, []),
    ("schema failing", _purity_cases[4][1], {}, [("SCHEMA_ENUM", "items[0].receivable_kind")]),
    ("debt valid", debt_record(), {}, []),
]

# Isinma: olasi tembel import'lar yamadan ONCE tamamlansin.
for _label, _record, _kwargs, _expected in _io_scenarios:
    run(_record, **_kwargs)

_originals = [(owner, name, getattr(owner, name)) for owner, name in _patch_targets]
_io_results = []
try:
    for _owner, _name, _original in _originals:
        setattr(_owner, _name, _forbidden_io)
    for _label, _record, _kwargs, _expected in _io_scenarios:
        _io_results.append((_label, run(_record, **_kwargs), _expected))
finally:
    for _owner, _name, _original in _originals:
        setattr(_owner, _name, _original)

check(
    "rule 11: all file-IO functions restored after the patch block",
    all(getattr(owner, name) is original for owner, name, original in _originals),
)
check("rule 11: validator made zero file-IO calls while IO was forbidden", _io_calls == [], detail=len(_io_calls))
for _label, _result, _expected in _io_results:
    check(f"rule 11: validator works with file IO forbidden ({_label})", _result == _expected, detail=repr(_result))


# ============================================================
# 15) SIZINTI YOK - hata ciktisinda girdi degeri / mesaj metni yok
# ============================================================

_SENTINEL_TEXT = "Kurgusal Sizinti Adi"
_SENTINEL_KEY = "kurgusal_sizinti_anahtari"
_SENTINEL_ENUM = "kurgusal_sizinti_enum"
_SENTINEL_DOC_KEY = "synthetic_doc_sizinti_anahtar"
_SENTINEL_DOC_TYPE = "Kurgusal Sizinti Turu"
_SENTINEL_CASE = "synthetic_sizinti_case"
_SENTINEL_ID = "synthetic_sizinti_kimlik"

_leak_runs = []

_rec = base_record()
_rec["creditors"][0]["authority_name"] = _SENTINEL_TEXT + ("x" * 200)
_leak_runs.append(("over-long free text", run(_rec)))

_rec = base_record()
_rec["creditors"][0]["authority_name"] = _SENTINEL_TEXT + "\n"
_leak_runs.append(("free text with line break", run(_rec)))

_rec = base_record()
_rec[_SENTINEL_KEY] = _SENTINEL_TEXT
_rec["items"][0][_SENTINEL_KEY] = 1
_leak_runs.append(("extra key names", run(_rec)))

_rec = base_record()
_rec["items"][0]["receivable_kind"] = _SENTINEL_ENUM
_leak_runs.append(("enum-violating value", run(_rec)))

_rec = base_record()
_rec["record_id"] = _SENTINEL_TEXT
_leak_runs.append(("pattern-violating id", run(_rec)))

_docs = make_documents()
_docs[_SENTINEL_DOC_KEY] = "not a dict"
_leak_runs.append(("invalid documents entry key", run(base_record(), documents=_docs)))

_docs = make_documents()
_docs[ACTION_DOC]["document_type"] = _SENTINEL_DOC_TYPE
_leak_runs.append(("unsupported document_type value", run(base_record(), documents=_docs)))

_leak_runs.append(("case mismatch value", run(base_record(), case_id=_SENTINEL_CASE)))

_rec = base_record()
_rec["items"][0]["creditor_id"] = _SENTINEL_ID
_leak_runs.append(("unknown creditor reference value", run(_rec)))

_rec = base_record()
_rec["items"][0]["source_document_id"] = _SENTINEL_ID
_leak_runs.append(("unknown source document value", run(_rec)))

_rec = verified_record()
_rec["verification"]["items_evidence"][0]["item_id"] = _SENTINEL_ID
_leak_runs.append(("unknown evidence target value", run(_rec, allow_verified=True)))

check(
    "leak: path renderer stops at an unknown (input-provided) key and never prints it",
    rrv._render_path(["items", 0, _SENTINEL_KEY, "page"]) == "items[0]"
    and rrv._render_path([_SENTINEL_KEY]) == "record"
    and rrv._render_path(["verification", "items_evidence", 1, "page"]) == "verification.items_evidence[1].page",
    detail=repr(rrv._render_path(["items", 0, _SENTINEL_KEY, "page"])),
)

_JSONSCHEMA_MESSAGE_FRAGMENTS = (
    "is not one of",
    "is a required property",
    "Additional properties",
    "does not match",
    "is not of type",
    "is too long",
    "is too short",
    "should not be valid",
    "was expected",
    "is less than",
)

for _label, _result in _leak_runs:
    _text = repr(_result)
    check(f"leak: {_label} produced at least one error", len(_result) >= 1, detail=_text)
    check(
        f"leak: {_label} output contains no input value / key / document id",
        all(
            sentinel not in _text
            for sentinel in (
                _SENTINEL_TEXT,
                _SENTINEL_KEY,
                _SENTINEL_ENUM,
                _SENTINEL_DOC_KEY,
                _SENTINEL_DOC_TYPE,
                _SENTINEL_CASE,
                _SENTINEL_ID,
                "Kurgusal",
                ACTION_DOC,
                STATEMENT_DOC,
                UNRELATED_DOC,
            )
        ),
        detail=_text,
    )
    check(
        f"leak: {_label} output contains no jsonschema message text",
        all(fragment not in _text for fragment in _JSONSCHEMA_MESSAGE_FRAGMENTS),
        detail=_text,
    )


# ============================================================
# 16) CIKTI BICIMI - sabit ASCII buyuk harf kod + yapisal yol
# ============================================================

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PATH_RE = re.compile(
    r"^(record|argument\.case_id|argument\.documents|"
    r"[a-z_]+(\[[0-9]+\])?(\.[a-z_]+(\[[0-9]+\])?)*)$"
)

_all_outputs = [result for _, result in _leak_runs]
for _label, _record, _documents, _kwargs in _purity_cases:
    _all_outputs.append(run(_record, documents=_documents, **_kwargs))
_shape_ok = True
_shape_detail = ""
for _result in _all_outputs:
    if not isinstance(_result, list):
        _shape_ok = False
        _shape_detail = repr(_result)
        break
    for _entry in _result:
        if not (
            isinstance(_entry, tuple)
            and len(_entry) == 2
            and type(_entry[0]) is str
            and type(_entry[1]) is str
            and _CODE_RE.match(_entry[0])
            and _PATH_RE.match(_entry[1])
        ):
            _shape_ok = False
            _shape_detail = repr(_entry)
            break
check("output: every error is (ASCII UPPER code, structural path) tuple", _shape_ok, detail=_shape_detail)
check(
    "output: result list is sorted and has no duplicates",
    all(result == sorted(set(result)) for result in _all_outputs),
)


# ============================================================
# 17) STATIK - dogrulayicinin import ettikleri, main() yok
# ============================================================

_validator_source = (SRC_DIR / "receivable_record_validator.py").read_text(encoding="utf-8")
_import_lines = sorted(
    {
        line.strip()
        for line in _validator_source.splitlines()
        if re.match(r"^\s*(import|from)\s", line)
    }
)
check(
    "static: validator imports exactly json, datetime.date, pathlib.Path, jsonschema.Draft202012Validator",
    _import_lines
    == sorted(
        {
            "import json",
            "from datetime import date",
            "from pathlib import Path",
            "from jsonschema import Draft202012Validator",
        }
    ),
    detail=repr(_import_lines),
)
check("static: validator defines no main()", re.search(r"^def main\(", _validator_source, re.MULTILINE) is None)
check("static: validator has no __main__ block", "__main__" not in _validator_source)

# L-2 (duzeltme turu 1): kural 11 icin AST denetimi. Sema dosyasini
# yukleyen tek fonksiyon (_load_schema_once) DISINDAKI hicbir fonksiyon
# govdesinde dosya erisimine giden adlar gecmez. Yalniz kaynak metni
# ayristirilir; audit hook ve alt surec KULLANILMAZ.
_L2_LOADER = "_load_schema_once"
_L2_FORBIDDEN_NAMES = frozenset(
    {
        "Path",
        "BASE_DIR",
        "RECEIVABLE_RECORD_SCHEMA_PATH",
        "open",
        "__import__",
        "exec",
        "eval",
    }
)


def _l2_names_in(node):
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in _L2_FORBIDDEN_NAMES:
            found.add(sub.id)
        elif isinstance(sub, ast.Attribute) and sub.attr in _L2_FORBIDDEN_NAMES:
            found.add(sub.attr)
    return found


_l2_tree = ast.parse(_validator_source)
_l2_functions = [
    node
    for node in ast.walk(_l2_tree)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
]
_l2_loaders = [node for node in _l2_functions if node.name == _L2_LOADER]
_l2_scanned = [node for node in _l2_functions if node.name != _L2_LOADER]
_l2_scanned_names = {node.name for node in _l2_scanned}
check("L-2 static: exactly one schema loader function _load_schema_once", len(_l2_loaders) == 1, detail=len(_l2_loaders))
check(
    "L-2 static control: the loader itself references open and RECEIVABLE_RECORD_SCHEMA_PATH (detector is not vacuous)",
    len(_l2_loaders) == 1 and {"open", "RECEIVABLE_RECORD_SCHEMA_PATH"} <= _l2_names_in(_l2_loaders[0]),
    detail=repr(sorted(_l2_names_in(_l2_loaders[0])) if _l2_loaders else None),
)
check(
    "L-2 static control: at least 25 other functions scanned, including validate_receivable_record and _validate",
    len(_l2_scanned) >= 25 and {"validate_receivable_record", "_validate"} <= _l2_scanned_names,
    detail=len(_l2_scanned),
)
_l2_violations = sorted(
    (node.name, name)
    for node in _l2_scanned
    for name in _l2_names_in(node)
)
check(
    "L-2 static rule 11: no function other than the loader uses Path / BASE_DIR / RECEIVABLE_RECORD_SCHEMA_PATH / open / __import__ / exec / eval",
    _l2_violations == [],
    detail=repr(_l2_violations),
)


print(f"--- {MODULE_NAME}: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
