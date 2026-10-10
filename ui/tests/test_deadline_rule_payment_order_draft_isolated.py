# ============================================================
# KOL A / DİLİM 1 - AATUHK m.58 ÖDEME EMRİ SÜRE KURALI (DRAFT)
# ISOLATED, READ-ONLY TESTS.
#
# Bu modül, `data/deadline_rules/deadline_rules.json`'a TASLAK olarak
# eklenen `aatuhk_6183_payment_order_lawsuit_filing` kuralının ve onu
# destekleyen `kanun_6183` belge kaydı ile `kanun_6183_m58_f1_v1`
# provision kaydının, GERÇEK (commit'li) registry/manifest dosyaları
# üzerinde şu sözleşmeyi koruduğunu mekanik olarak doğrular:
#
#   (1) gerçek registry deadline_rule_validator'dan geçer; yeni kural
#       status=draft, calculation_enabled=false ve document_types boş
#       DEĞİL (boş liste seçim politikasında jokerdir);
#   (2) CLAUDE.md §13.2 mekanik bekçisi: yeni kuralın legal_basis_refs
#       listesinde 5604 / İYUK m.8/2, m.8/3, m.61/1 ref'leri YOK - bu
#       ref'lerin bağlanması avukat kararına bağlıdır;
#   (3) seçim politikası: ihbarname çapasında mevcut İYUK kuralı seçilir,
#       odeme_emri çapasında no_match (draft kural aday olmaz);
#   (4) hesaplayıcı: odeme_emri çapasında blocked_missing_rule,
#       calculated_deadline=None, requires_human_review=True;
#   (5) Legal Knowledge Engine: İYUK kuralı tamamen çözülür ve
#       aktivasyona uygundur; yeni kuralın m.58/1 hükmü unverified
#       olduğu için aktivasyona UYGUN DEĞİLDİR.
#
# Pozitif kontrol: draft kuralın YALNIZ BELLEKTE (dosyaya yazılmadan)
# aktive edilmiş bir kopyası odeme_emri çapasında seçilir ve çift belge
# türlü çapada ambiguous verir - yani (3)'teki no_match bir belge türü
# uyuşmazlığından DEĞİL, kuralın draft olmasından kaynaklanır.
#
# Bu dosya SALT-OKUNURDUR: case dizini, PostgreSQL, mutation
# coordinator, ağ/API çağrısı veya gerçek müvekkil verisi KULLANILMAZ;
# tüm çapalar sentetiktir. `data/` ağacının bayt-değişmezliği koşu
# başında ve sonunda doğrulanır.
#
# Run: python ui/tests/test_deadline_rule_payment_order_draft_isolated.py
# ============================================================

import copy
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import deadline_calculator as dc                       # noqa: E402
import deadline_legal_basis_resolver as resolver       # noqa: E402
import deadline_rule_selection_policy as selection     # noqa: E402
import deadline_rule_validator as rule_validator       # noqa: E402
import manifest_validator                               # noqa: E402
import provision_manifest_validator                     # noqa: E402

REAL_DATA_DIR = REPO_ROOT / "data"
RULESET_PATH = REAL_DATA_DIR / "deadline_rules" / "deadline_rules.json"
DOCUMENTS_PATH = REAL_DATA_DIR / "documents.json"
PROVISIONS_PATH = REAL_DATA_DIR / "provisions.json"

IYUK_RULE_ID = "iyuk_tax_court_general_lawsuit_filing"
DRAFT_RULE_ID = "aatuhk_6183_payment_order_lawsuit_filing"
DRAFT_REF = "AATUHK_6183_m58_1"

# CLAUDE.md §13.2 / avukat kararına bağlı, taslağa BİLİNÇLİ OLARAK
# eklenmeyen ref'ler.
EXCLUDED_REFS = (
    "KANUN_5604_m1",
    "IYUK_2577_m8_2",
    "IYUK_2577_m8_3",
    "IYUK_2577_m61_1",
)

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


def _snapshot_data_tree():
    out = {}
    for path in REAL_DATA_DIR.rglob("*"):
        if path.is_file():
            try:
                out[str(path.relative_to(REAL_DATA_DIR))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            except OSError:
                out[str(path.relative_to(REAL_DATA_DIR))] = "<unreadable>"
    return out


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rule_by_id(ruleset, rule_id):
    matches = [r for r in ruleset["rules"] if r.get("rule_id") == rule_id]
    return matches[0] if len(matches) == 1 else None


def _anchor():
    return {
        "event_id": "timeline_event_synthetic",
        "event_type": "notification_date",
        "date": "2026-02-10",
        "date_precision": "exact",
        "verification_state": "verified",
        "confidence": 0.95,
        "source_document_ids": ["synthetic_doc_001"],
    }


def _context(document_types):
    return {
        "case_types": set(),
        "tax_types": {"kdv"},
        "case_stages": set(),
        "anchor_document_types": set(document_types),
    }


# ================================================================
# (1) REGISTRY VALIDATION + DRAFT SHAPE
# ================================================================

def test_registry_validation(ruleset):
    result = rule_validator.validate_deadline_rules(
        ruleset_path=RULESET_PATH, raise_on_error=False,
    )
    check(
        "(1) gerçek registry deadline_rule_validator'dan geçer (errors=[])",
        result["valid"] is True and result["errors"] == [],
        result["errors"],
    )
    check(
        "(1) registry: 2 kural, 1 active + 1 draft, yalnız 1 calculation_enabled",
        result["rule_count"] == 2
        and result["status_counts"] == {"active": 1, "draft": 1}
        and result["calculation_enabled_count"] == 1,
        result,
    )

    draft = _rule_by_id(ruleset, DRAFT_RULE_ID)
    check("(1) yeni kural registry'de tam bir kez bulunur", draft is not None)
    if draft is None:
        return

    check("(1) yeni kural status=draft", draft["status"] == "draft", draft["status"])
    check(
        "(1) yeni kural calculation_enabled=false",
        draft["calculation_enabled"] is False,
    )
    check(
        "(1) yeni kural requires_human_review=true",
        draft["requires_human_review"] is True,
    )
    document_types = draft["applicability"]["document_types"]
    check(
        "(1) yeni kural document_types boş DEĞİL (boş liste = joker)",
        isinstance(document_types, list) and len(document_types) > 0,
        document_types,
    )
    check(
        "(1) yeni kural document_types == ['odeme_emri']",
        document_types == ["odeme_emri"],
        document_types,
    )
    check(
        "(1) yeni kural: notification_date çapası, 15 takvim günü, next_day",
        draft["anchor_event_types"] == ["notification_date"]
        and draft["duration"] == {"value": 15, "unit": "day"}
        and draft["start_rule"] == "next_day"
        and draft["day_count_policy"] == "calendar_days",
        draft,
    )
    check(
        "(1) yeni kural priority mevcut İYUK kuralıyla KASITLI eşit (100)",
        draft["priority"] == _rule_by_id(ruleset, IYUK_RULE_ID)["priority"] == 100,
    )
    check(
        "(1) yeni kural notları TASLAK / LEGAL_APPROVED yok uyarısıyla başlar",
        isinstance(draft["notes"], str)
        and draft["notes"].startswith("TASLAK — AVUKAT TEYİDİ BEKLİYOR (LEGAL_APPROVED yok)"),
    )


# ================================================================
# (2) §13.2 MECHANICAL GUARD
# ================================================================

def test_excluded_refs_guard(ruleset):
    draft = _rule_by_id(ruleset, DRAFT_RULE_ID)
    refs = draft["legal_basis_refs"] if draft else None
    check(
        "(2) yeni kuralın legal_basis_refs == ['AATUHK_6183_m58_1']",
        refs == [DRAFT_REF],
        refs,
    )
    for excluded in EXCLUDED_REFS:
        check(
            f"(2) §13.2 bekçisi: yeni kuralda {excluded} YOK (avukat kararına bağlı)",
            refs is not None and excluded not in refs,
            refs,
        )
    iyuk = _rule_by_id(ruleset, IYUK_RULE_ID)
    check(
        "(2) bekçi non-vacuous: aynı dört ref mevcut İYUK kuralında GERÇEKTEN var",
        iyuk is not None and all(r in iyuk["legal_basis_refs"] for r in EXCLUDED_REFS),
    )


# ================================================================
# (3) SELECTION POLICY
# ================================================================

def test_selection(ruleset):
    ihbarname = selection.select_deadline_rule(
        ruleset, _anchor(), _context(["vergi_ceza_ihbarnamesi"]),
    )
    check(
        "(3) ihbarname çapası: mevcut İYUK kuralı seçilir",
        ihbarname["selection_state"] == "selected"
        and ihbarname["selected_rule"]["rule_id"] == IYUK_RULE_ID,
        {k: ihbarname.get(k) for k in ("selection_state", "reason", "rejected_rules")},
    )
    rejected = {r["rule_id"]: r["reasons"] for r in ihbarname["rejected_rules"]}
    check(
        "(3) ihbarname çapası: draft kural rule_not_active_or_enabled ile reddedilir",
        "rule_not_active_or_enabled" in rejected.get(DRAFT_RULE_ID, []),
        rejected,
    )

    odeme = selection.select_deadline_rule(
        ruleset, _anchor(), _context(["odeme_emri"]),
    )
    check(
        "(3) odeme_emri çapası: no_match (draft kural aday olmaz)",
        odeme["selection_state"] == "no_match"
        and odeme["selected_rule"] is None
        and odeme["calculation_allowed"] is False
        and odeme["requires_human_review"] is True,
        {k: odeme.get(k) for k in ("selection_state", "reason", "rejected_rules")},
    )
    rejected = {r["rule_id"]: r["reasons"] for r in odeme["rejected_rules"]}
    check(
        "(3) odeme_emri çapası: draft kuralın TEK red nedeni draft/disabled olması",
        rejected.get(DRAFT_RULE_ID) == ["rule_not_active_or_enabled"],
        rejected,
    )
    check(
        "(3) odeme_emri çapası: İYUK kuralı document_type_mismatch ile reddedilir",
        "document_type_mismatch" in rejected.get(IYUK_RULE_ID, []),
        rejected,
    )

    # Pozitif kontrol (YALNIZ BELLEKTE - dosyaya yazılmaz).
    activated = copy.deepcopy(ruleset)
    draft = _rule_by_id(activated, DRAFT_RULE_ID)
    draft["status"] = "active"
    draft["calculation_enabled"] = True
    hypothetical = selection.select_deadline_rule(
        activated, _anchor(), _context(["odeme_emri"]),
    )
    check(
        "(3) pozitif kontrol: bellekte aktive edilmiş kopya odeme_emri çapasında seçilir",
        hypothetical["selection_state"] == "selected"
        and hypothetical["selected_rule"]["rule_id"] == DRAFT_RULE_ID,
        hypothetical.get("selection_state"),
    )
    both = selection.select_deadline_rule(
        activated, _anchor(), _context(["odeme_emri", "vergi_ceza_ihbarnamesi"]),
    )
    check(
        "(3) pozitif kontrol: çift belge türlü çapada eşit priority -> ambiguous (fail-closed)",
        both["selection_state"] == "ambiguous"
        and both["selected_rule"] is None
        and sorted(both["ambiguous_rule_ids"]) == sorted([IYUK_RULE_ID, DRAFT_RULE_ID]),
        both.get("selection_state"),
    )


# ================================================================
# (4) CALCULATOR
# ================================================================

def test_calculator(ruleset):
    odeme = selection.select_deadline_rule(
        ruleset, _anchor(), _context(["odeme_emri"]),
    )
    record = dc.build_deadline_record(
        case_id="synthetic_case_payment_order",
        anchor_event=_anchor(),
        selection=odeme,
        ruleset_path=RULESET_PATH,
        holiday_calendar=dc.load_holiday_calendar(),
        stopping_event_status="none",
        stopping_event_attestation_ref=None,
    )
    check(
        "(4) odeme_emri çapası: calculation_state=blocked_missing_rule",
        record["calculation_state"] == "blocked_missing_rule",
        record,
    )
    check(
        "(4) odeme_emri çapası: calculated_deadline=None",
        record["calculated_deadline"] is None,
    )
    check(
        "(4) odeme_emri çapası: requires_human_review=True",
        record["requires_human_review"] is True,
    )
    check(
        "(4) odeme_emri çapası: draft kural kayda sızmaz (rule_id çözülmemiş)",
        record["rule_id"] == "unresolved_deadline_rule"
        and record["legal_basis_refs"] == [],
        record.get("rule_id"),
    )


# ================================================================
# (5) LEGAL KNOWLEDGE ENGINE
# ================================================================

def test_resolver():
    out = resolver.resolve_ruleset_legal_basis(RULESET_PATH)
    by_id = {r["rule_id"]: r for r in out["rules"]}

    iyuk = by_id.get(IYUK_RULE_ID)
    check(
        "(5) İYUK kuralı: tüm ref'ler çözülür ve aktivasyona uygundur",
        iyuk is not None
        and iyuk["all_resolved"] is True
        and iyuk["all_basis_verified"] is True
        and iyuk["activation_eligible"] is True
        and iyuk["unresolved_refs"] == []
        and iyuk["activation_blocked_refs"] == [],
        iyuk,
    )

    draft = by_id.get(DRAFT_RULE_ID)
    check(
        "(5) yeni kural: aktivasyona UYGUN DEĞİL, m.58/1 ref'i bloklu",
        draft is not None
        and draft["activation_eligible"] is False
        and draft["all_basis_verified"] is False
        and draft["activation_blocked_refs"] == [DRAFT_REF],
        draft,
    )
    resolution = None
    if draft is not None:
        resolution = next(
            (r for r in draft["resolutions"] if r["legal_basis_ref"] == DRAFT_REF), None,
        )
    check(
        "(5) m.58/1 ref'i kanun_6183 m.58 f.1 kaydına tam fıkra eşleşmesiyle bulunur",
        resolution is not None
        and resolution["parsed"]["document_id"] == "kanun_6183"
        and resolution["repository_match_type"] == "exact_fikra"
        and resolution["selected_provision_version_ids"] == ["kanun_6183_m58_f1_v1"],
        resolution,
    )
    check(
        "(5) m.58/1 hükmü unverified -> resolved=False, activation_eligible=False",
        resolution is not None
        and resolution["resolved"] is False
        and resolution["activation_eligible"] is False,
        resolution,
    )


# ================================================================
# SUPPORTING DATA RECORDS
# ================================================================

def test_supporting_records():
    documents = _load_json(DOCUMENTS_PATH)["documents"]
    doc = [d for d in documents if d["document_id"] == "kanun_6183"]
    check("kanun_6183 belge kaydı tam bir kez bulunur", len(doc) == 1)
    if len(doc) == 1:
        doc = doc[0]
        check(
            "kanun_6183: ingest.enabled=false, Kanun, kanun_no 6183, RG 1953-07-28 / 8469",
            doc["ingest"]["enabled"] is False
            and doc["belge_turu"] == "Kanun"
            and doc["kanun_no"] == "6183"
            and doc["resmi_gazete_tarihi"] == "1953-07-28"
            and doc["resmi_gazete_sayisi"] == "8469",
            doc,
        )

    provisions = _load_json(PROVISIONS_PATH)["provisions"]
    prov = [p for p in provisions if p["provision_version_id"] == "kanun_6183_m58_f1_v1"]
    check("kanun_6183_m58_f1_v1 provision kaydı tam bir kez bulunur", len(prov) == 1)
    if len(prov) == 1:
        prov = prov[0]
        check(
            "kanun_6183_m58_f1_v1: unverified, formal.verified=false, status=unknown, evidence=[]",
            prov["verification_state"] == "unverified"
            and prov["formal"]["verified"] is False
            and prov["formal"]["status"] == "unknown"
            and prov["formal"]["evidence"] == [],
            prov["formal"],
        )

    manifest = manifest_validator.validate_manifest_file(raise_on_error=False)
    check(
        "gerçek documents.json validate_manifest_file()'dan geçer",
        manifest["valid"] is True, manifest["errors"],
    )
    admissibility_errors, _warnings = (
        manifest_validator.validate_corpus_policy_admissibility(documents)
    )
    check(
        "gerçek documents.json gerçek corpus policy admissibility'den geçer",
        admissibility_errors == [], admissibility_errors,
    )
    provisions_result = provision_manifest_validator.validate_provisions_file(
        raise_on_error=False,
    )
    check(
        "gerçek provisions.json provision_manifest_validator'dan geçer",
        provisions_result["valid"] is True, provisions_result["errors"],
    )


def run_self_test():
    before_data_snapshot = _snapshot_data_tree()

    ruleset = _load_json(RULESET_PATH)
    test_registry_validation(ruleset)
    test_excluded_refs_guard(ruleset)
    test_selection(ruleset)
    test_calculator(ruleset)
    test_resolver()
    test_supporting_records()

    after_data_snapshot = _snapshot_data_tree()
    check(
        "bu test modülü: gerçek data/ ağacı tüm koşu boyunca bayt-değişmez "
        "(SALT-OKUNUR - case dizini yok, PostgreSQL yok, ağ yok, yazma yok)",
        before_data_snapshot == after_data_snapshot,
    )

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
