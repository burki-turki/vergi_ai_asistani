# ============================================================
# KOL A / MALİ TATİL DİLİM A - İŞLEM BELGESİNE BAĞLI ALACAK MODU
# ISOLATED, READ-ONLY TESTS.
#
# Bu modül, `src/deadline_calculator.py`'ye eklenen
# `mali_tatil_receivable_basis = "action_document_receivables"` modunu
# (yalnız üç TASLAK kural: ödeme emri, borçluya haciz / e-haciz
# bildirimi, gıyapta ihtiyati haciz) sözleşmenin her adımı için
# sentetik girdilerle sınar:
#
#   adım 1  çapa olayında türü kuralın document_types listesinde olan
#           TAM BİR belge (liste boşsa başarısız)
#   adım 2  o belgeye bağlı en az bir uyuşmazlık kalemi
#   adım 3  bağlı kalemlerin hepsi verified (K3)
#   adım 4  o belgeye ait TAM BİR idari işlem kaydı; idare dolu ve
#           verified
#   adım 5  idare sınıfı: istisna -> mali tatil yok; "vergi dairesi"
#           (K5) -> devam; diğer -> needs_review
#   adım 6  bağlı kalemlerin vergi türü sınıfı (listeler değişmeden);
#           mixed -> mali tatilsiz erken tarih (avukat 3.2)
#   adım 7  eksik bağ koruması (yalnız mali tatil UYGULATACAK sonuçta)
#   adım 9  fark notu (hesaplanan ve needs_review sonuçlarda)
#   adım 10 iz notu (belge kimliği + kalem kimlikleri)
#   adım 11 eski biçimli / boş bağlam -> needs_review
#   adım 12 registry: alanı taşıyan her kural KANUN_5604_m1 taşır
#           (YALNIZ statik kontrol; çalışma anında ek kapı YOKTUR)
#   adım 13 çapa olayının related_dispute_item_ids alanı kullanılmaz
#   K6      Temmuz'a değmeyen sürede sonuç bugünküyle aynı
#
# KAYNAK AYRIMI (her kontrolün etiketinde yazılıdır):
#   [AVUKAT 4.2]  Avukatın imzalı cevabındaki TEK altın örnek: ödeme
#                 emrinin konusu ÖTV, dosyada ayrıca gelir vergisi;
#                 tebliğ 20.06.2026 -> son gün 06.07.2026; fark avukata
#                 gösterilir; 07.09.2026 kesin tarih olarak SUNULMAZ.
#   [MÜHENDİS]    Mühendis türetimi senaryolar. Bunlar avukatın
#                 örneği DEĞİLDİR. Beklenen tarih, mümkün olan her
#                 yerde aynı vergi sınıfıyla bugünkü (dosya geneli)
#                 hesabın verdiği sonuçla karşılaştırılarak sınanır -
#                 Adım 7 aritmetiği değişmemiştir.
#
# NE KANITLANMAZ:
#   - "verified" genel bir işarettir; kalemin türünün işlem belgesinin
#     KENDİSİNDEN teyit edildiğini veya bağ listesinin TAM olduğunu
#     göstermez (K3). Yanlış belgeye bağlanmış ve verified işaretlenmiş
#     bir kalem yine yanlış sonuç verebilir; adım 7 bunu yalnız dosyada
#     bağsız farklı bir kalem varsa yakalar. Avukatın belge + sayfa +
#     "bağ tam" teyidi Dilim B'nin işidir.
#   - "vergi dairesi" tanıması (K5) ve bağın yalnız Temmuz penceresinde
#     aranması (K6) MÜHENDİS yorumudur; avukata sorulacaktır.
#   - Fer'i kalemler ve ceza kaleminin bağlı olduğu vergi (K4) açıktır.
#   - Kurallar TASLAKTIR; tüm hesaplar kuralın YALNIZ BELLEKTE
#     etkinleştirilmiş kopyasıyla yapılır.
#
# Bu dosya SALT-OKUNURDUR: gerçek case dizini, PostgreSQL, ağ/API veya
# gerçek kişi/kurum/dosya verisi KULLANILMAZ. Geçici dosyalar yalnız
# işletim sisteminin geçici dizinine yazılır ve koşu sonunda silinir.
# Gerçek `data/` ağacının bayt-değişmezliği başta ve sonda doğrulanır.
#
# Run: python ui/tests/test_deadline_mali_tatil_receivable_link_isolated.py
# ============================================================

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import deadline_calculator as dc                       # noqa: E402
import deadline_rule_selection_policy as selection     # noqa: E402
import deadline_rule_validator as rule_validator       # noqa: E402
import deadline_validator                               # noqa: E402

REAL_DATA_DIR = REPO_ROOT / "data"
RULESET_PATH = REAL_DATA_DIR / "deadline_rules" / "deadline_rules.json"
PROVISIONS_PATH = REAL_DATA_DIR / "provisions.json"
SCHEMA_PATH = REAL_DATA_DIR / "deadline_rule.schema.json"

FIELD = "mali_tatil_receivable_basis"
BASIS = "action_document_receivables"
MALI_REF = "KANUN_5604_m1"

IYUK_RULE_ID = "iyuk_tax_court_general_lawsuit_filing"
PAYMENT_ORDER = "aatuhk_6183_payment_order_lawsuit_filing"
SEIZURE = "iyuk_seizure_and_e_seizure_lawsuit_filing"
PRECAUTIONARY = "aatuhk_6183_precautionary_seizure_in_absentia_lawsuit_filing"
DRAFT_RULE_IDS = (PAYMENT_ORDER, SEIZURE, PRECAUTIONARY)

DOC = "synthetic_doc_action"
OTHER_DOC = "synthetic_doc_other"
TAX_OFFICE = "Kurgusal Vergi Dairesi Müdürlüğü"

CALCULATED = "calculated"
NEEDS_REVIEW = "needs_review"

LAWYER_ANCHOR = "2026-06-20"
LAWYER_EXPECTED = "2026-07-06"
LATE_DATE_NOT_TO_PRESENT = "2026-09-07"
NON_JULY_ANCHOR = "2026-02-10"

ATTESTATION_REF = "AV-BEYAN-KOLA-MT-A-SENTETIK-001"

passed = 0
failed = 0

CALENDAR = None


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
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rule_by_id(ruleset, rule_id):
    matches = [r for r in ruleset["rules"] if r.get("rule_id") == rule_id]
    return matches[0] if len(matches) == 1 else None


def _activated(rule):
    """YALNIZ BELLEKTE etkinleştirilmiş kopya (status/calculation_enabled)."""
    clone = copy.deepcopy(rule)
    clone["status"] = "active"
    clone["calculation_enabled"] = True
    return clone


def _without_field(rule):
    """Bugünkü (dosya geneli) davranışın karşılaştırma kopyası."""
    clone = copy.deepcopy(rule)
    clone.pop(FIELD, None)
    return clone


# ----------------------------------------------------------------
# SENTETİK DOSYA YAPI TAŞLARI (gerçek veri YOK)
# ----------------------------------------------------------------

def _item(item_id, tax_type, docs=(DOC,), verification="verified"):
    return {
        "dispute_item_id": item_id,
        "tax_type": tax_type,
        "period": {"start": None, "end": None, "label": None},
        "principal_tax": None,
        "penalty_type": None,
        "penalty_amount": None,
        "total_amount": None,
        "asserted_legal_basis_refs": [],
        "source_document_ids": list(docs),
        "verification_state": verification,
        "notes": None,
    }


def _action(action_id="action_synth_001", authority=TAX_OFFICE, doc=DOC,
            verification="verified", category="payment_order"):
    return {
        "action_id": action_id,
        "action_category": category,
        "action_type": "sentetik_islem",
        "issuing_authority": authority,
        "action_date": None,
        "notification_date": None,
        "source_document_id": doc,
        "verification_state": verification,
        "notes": None,
    }


def _case(items=(), actions=(), case_id="synthetic_case_mt_a"):
    return {
        "schema_version": 1,
        "case_id": case_id,
        "active": True,
        "title": "Kol A mali tatil Dilim A sentetik dosya",
        "case_type": None,
        "stage": None,
        "dispute_items": list(items),
        "administrative_actions": list(actions),
        "events": [],
        "proceedings": [],
    }


def _anchor(date=LAWYER_ANCHOR, docs=(DOC,), related=None):
    event = {
        "event_id": "timeline_event_synthetic",
        "event_type": "notification_date",
        "date": date,
        "date_precision": "exact",
        "verification_state": "verified",
        "confidence": 0.95,
        "source_document_ids": list(docs),
    }
    if related is not None:
        event["related_dispute_item_ids"] = list(related)
    return event


def _index(rule, docs=(DOC,)):
    return {doc: rule["applicability"]["document_types"][0] for doc in docs}


def _assess(rule, case, anchor=None, index=None):
    return dc.evaluate_mali_tatil_action_document_receivables(
        case,
        anchor if anchor is not None else _anchor(),
        rule,
        index if index is not None else _index(rule),
    )


def _calc(rule, anchor_date, context, recess=True):
    return dc.calculate_rule_deadline(
        anchor_date=anchor_date,
        rule=rule,
        holiday_calendar=CALENDAR,
        judicial_recess_applicable=recess,
        case_tax_context=context,
    )


def _today(rule, anchor_date, tax_types, authorities=(), recess=True):
    """Bugünkü (dosya geneli) hesap: alanı olmayan kopya + eski bağlam."""
    return _calc(
        _without_field(rule),
        anchor_date,
        {"tax_types": set(tax_types), "issuing_authorities": set(authorities)},
        recess=recess,
    )


def _state(result):
    return {
        k: result.get(k)
        for k in (
            "calculation_state", "calculated_deadline", "mali_tatil_applied",
            "mali_tatil_exclusion_reason", "mali_tatil_receivable_reason_code",
            "judicial_recess_applied", "reason",
        )
    }


# ================================================================
# (0) ÖN KOŞULLAR + (12) REGISTRY TUTARLILIĞI
# ================================================================

def test_registry_and_schema(ruleset):
    result = rule_validator.validate_deadline_rules(
        ruleset_path=RULESET_PATH, raise_on_error=False,
    )
    check(
        "(0) gerçek registry deadline_rule_validator'dan geçer; 1 active + 3 draft, "
        "hesaplaması açık yalnız 1 kural",
        result["valid"] is True
        and result["errors"] == []
        and result["status_counts"] == {"active": 1, "draft": 3}
        and result["calculation_enabled_count"] == 1,
        result["errors"],
    )
    schema = _load_json(SCHEMA_PATH)
    rule_def = schema["$defs"]["deadline_rule"]
    check(
        "(0) şema: alan isteğe bağlı, tek değerli enum, required'a EKLENMEDİ, "
        "schema_version const 1",
        rule_def["properties"].get(FIELD) == {"type": "string", "enum": [BASIS]}
        and FIELD not in rule_def["required"]
        and rule_def["additionalProperties"] is False
        and schema["properties"]["schema_version"]["const"] == 1,
        rule_def["properties"].get(FIELD),
    )
    for rule_id in DRAFT_RULE_IDS:
        rule = _rule_by_id(ruleset, rule_id)
        check(
            f"(0) {rule_id}: alan '{BASIS}' değerini taşır; status=draft, "
            "calculation_enabled=false DEĞİŞMEDİ",
            rule is not None
            and rule.get(FIELD) == BASIS
            and rule["status"] == "draft"
            and rule["calculation_enabled"] is False
            and dc.rule_uses_mali_tatil_receivable_basis(rule) is True,
            rule and {k: rule.get(k) for k in (FIELD, "status", "calculation_enabled")},
        )
    iyuk = _rule_by_id(ruleset, IYUK_RULE_ID)
    check(
        "(0) İYUK ihbarname kuralı alanı TAŞIMAZ (dosya geneli davranış korunur)",
        iyuk is not None
        and FIELD not in iyuk
        and dc.rule_uses_mali_tatil_receivable_basis(iyuk) is False,
    )

    carriers = [r for r in ruleset["rules"] if FIELD in r]
    lacking = [r["rule_id"] for r in carriers if MALI_REF not in r.get("legal_basis_refs", [])]
    check(
        "(12) registry tutarlılığı: alanı taşıyan her kural KANUN_5604_m1 dayanağını taşır "
        "(boş olmayan küme: 3 kural)",
        len(carriers) == 3 and lacking == [],
        {"carriers": [r["rule_id"] for r in carriers], "lacking": lacking},
    )
    unknown_values = [r["rule_id"] for r in carriers if r[FIELD] != BASIS]
    check(
        "(12) registry: alanı taşıyan kurallarda tanınmayan değer YOK",
        unknown_values == [],
        unknown_values,
    )


# ================================================================
# [AVUKAT 4.2] TEK ALTIN ÖRNEK
# ================================================================

def test_lawyer_example(ruleset):
    rule = _activated(_rule_by_id(ruleset, PAYMENT_ORDER))
    case = _case(
        items=[
            _item("item_otv", "ÖTV"),
            _item("item_gv", "Gelir Vergisi", docs=()),
        ],
        actions=[_action()],
    )
    assessment = _assess(rule, case)
    result = _calc(rule, LAWYER_ANCHOR, assessment)
    check(
        "[AVUKAT 4.2] ÖTV ödeme emri (bağlı, teyitli) + dosyada ayrıca gelir vergisi: "
        "tebliğ 20.06.2026 -> son gün 06.07.2026, mali tatil UYGULANMAZ",
        result["calculation_state"] == CALCULATED
        and result["calculated_deadline"] == LAWYER_EXPECTED
        and result["mali_tatil_applied"] is False
        and result["mali_tatil_exclusion_reason"] == "tax_type_excluded:ötv",
        _state(result),
    )
    check(
        "[AVUKAT 4.2] 07.09.2026 kesin tarih olarak SUNULMAZ",
        result["calculated_deadline"] != LATE_DATE_NOT_TO_PRESENT,
        _state(result),
    )
    check(
        "[AVUKAT 4.2] ÖTV-gelir vergisi farkı avukata gösterilir (fark işareti + not)",
        assessment["difference"] is True
        and assessment["linked_classes"] == ["excluded"]
        and assessment["unlinked_classes"] == ["included"]
        and any(n.startswith("mali_tatil_receivable_difference=linked:excluded;unlinked:included")
                for n in assessment["notes"]),
        assessment["notes"],
    )
    today = _today(rule, LAWYER_ANCHOR, {"gelir vergisi"})
    check(
        "[AVUKAT 4.2] karşılaştırma: bugünkü dosya-geneli yöntem aynı dosyada avukatın "
        "yanlış dediği 07.09.2026'yı verirdi (değişikliğin gerekçesi)",
        today["calculation_state"] == CALCULATED
        and today["calculated_deadline"] == LATE_DATE_NOT_TO_PRESENT,
        _state(today),
    )


# ================================================================
# [MÜHENDİS] ADIM ADIM SÖZLEŞME
# ================================================================

def test_steps(ruleset):
    rule = _activated(_rule_by_id(ruleset, PAYMENT_ORDER))
    gv_linked = _item("item_gv", "Gelir Vergisi")
    otv_linked = _item("item_otv", "ÖTV")

    def review(label, case, code, anchor=None, index=None, rule_override=None):
        used_rule = rule_override if rule_override is not None else rule
        assessment = _assess(used_rule, case, anchor=anchor, index=index)
        result = _calc(used_rule, LAWYER_ANCHOR, assessment)
        check(
            label,
            assessment["outcome"] == NEEDS_REVIEW
            and assessment["reason_code"] == code
            and result["calculation_state"] == NEEDS_REVIEW
            and result["calculated_deadline"] is None
            and result.get("mali_tatil_receivable_reason_code") == code
            and ("reason_code=" + code) in result["reason"],
            {"assessment": (assessment["outcome"], assessment["reason_code"]),
             "result": _state(result)},
        )
        return assessment

    # --- adım 1 ---
    review(
        "[MÜHENDİS] adım 1: çapada iki aday işlem belgesi (ikisi de odeme_emri) -> "
        "needs_review (işlem belgesi belirlenemedi)",
        _case(items=[gv_linked], actions=[_action()]),
        "mali_tatil_receivable_action_document_unresolved",
        anchor=_anchor(docs=(DOC, OTHER_DOC)),
        index=_index(rule, docs=(DOC, OTHER_DOC)),
    )
    review(
        "[MÜHENDİS] adım 1: çapa belgesinin türü kuralın listesinde değil -> needs_review",
        _case(items=[gv_linked], actions=[_action()]),
        "mali_tatil_receivable_action_document_unresolved",
        index={DOC: "vergi_ceza_ihbarnamesi"},
    )
    review(
        "[MÜHENDİS] adım 1: çapa belgesinin türü bilinmiyor (belge kaydı yok) -> needs_review",
        _case(items=[gv_linked], actions=[_action()]),
        "mali_tatil_receivable_action_document_unresolved",
        index={},
    )
    review(
        "[MÜHENDİS] adım 1: çapanın source_document_ids listesi boş -> needs_review",
        _case(items=[gv_linked], actions=[_action()]),
        "mali_tatil_receivable_action_document_unresolved",
        anchor=_anchor(docs=()),
    )
    empty_types = copy.deepcopy(rule)
    empty_types["applicability"]["document_types"] = []
    review(
        "[MÜHENDİS] adım 1: document_types listesi BOŞ kural kopyası -> needs_review "
        "(boş liste burada joker DEĞİLDİR)",
        _case(items=[gv_linked], actions=[_action()]),
        "mali_tatil_receivable_action_document_unresolved",
        index={DOC: "odeme_emri"},
        rule_override=empty_types,
    )
    one_of_two = _assess(
        rule, _case(items=[gv_linked], actions=[_action()]),
        anchor=_anchor(docs=(DOC, OTHER_DOC, DOC)),
        index={DOC: "odeme_emri", OTHER_DOC: "dava_dilekcesi"},
    )
    check(
        "[MÜHENDİS] adım 1: çapada başka türde ikinci belge (ve aynı kimliğin tekrarı) varken "
        "tek aday kalır -> işlem belgesi belirlenir",
        one_of_two["action_document_id"] == DOC and one_of_two["outcome"] == "apply",
        (one_of_two["action_document_id"], one_of_two["outcome"], one_of_two["reason_code"]),
    )
    upper = _assess(rule, _case(items=[gv_linked], actions=[_action()]), index={DOC: " ODEME_EMRI "})
    check(
        "[MÜHENDİS] adım 1: belge türü kural seçimiyle AYNI normalizasyondan geçer "
        "(büyük harf / boşluk)",
        upper["action_document_id"] == DOC and upper["outcome"] == "apply",
        (upper["outcome"], upper["reason_code"]),
    )

    # --- adım 2 ---
    review(
        "[MÜHENDİS] adım 2: aynı dosyada kalem var ama hiçbiri işlem belgesine bağlı değil -> "
        "needs_review (alacak ile işlem arasında bağ yok)",
        _case(items=[_item("item_gv", "Gelir Vergisi", docs=(OTHER_DOC,)),
                     _item("item_otv", "ÖTV", docs=())],
              actions=[_action()]),
        "mali_tatil_receivable_no_linked_item",
    )
    review(
        "[MÜHENDİS] adım 2: dosyada hiç uyuşmazlık kalemi yok -> needs_review",
        _case(items=[], actions=[_action()]),
        "mali_tatil_receivable_no_linked_item",
    )

    # --- adım 3 ---
    review(
        "[MÜHENDİS] adım 3: bağlı ÖTV kalemi teyitsiz (unverified) -> needs_review",
        _case(items=[_item("item_otv", "ÖTV", verification="unverified")], actions=[_action()]),
        "mali_tatil_receivable_item_unverified",
    )
    review(
        "[MÜHENDİS] adım 3: iki bağlı kalemden biri teyitsiz -> needs_review",
        _case(items=[gv_linked, _item("item_kdv", "KDV", verification="partially_verified")],
              actions=[_action()]),
        "mali_tatil_receivable_item_unverified",
    )

    # --- adım 4 ---
    review(
        "[MÜHENDİS] adım 4: işlem belgesine ait idari işlem kaydı yok -> needs_review",
        _case(items=[gv_linked], actions=[_action(doc=OTHER_DOC)]),
        "mali_tatil_receivable_authority_unresolved",
    )
    review(
        "[MÜHENDİS] adım 4: işlem belgesine ait İKİ idari işlem kaydı -> needs_review "
        "(alacaklı idare tek değil)",
        _case(items=[gv_linked],
              actions=[_action("action_a"), _action("action_b", category="collection")]),
        "mali_tatil_receivable_authority_unresolved",
    )
    for label, authority in (("boş", None), ("yalnız boşluk", "   ")):
        review(
            f"[MÜHENDİS] adım 4: alacaklı idare {label} -> needs_review",
            _case(items=[gv_linked], actions=[_action(authority=authority)]),
            "mali_tatil_receivable_authority_unresolved",
        )
    review(
        "[MÜHENDİS] adım 4: idari işlem kaydı teyitsiz -> needs_review",
        _case(items=[gv_linked], actions=[_action(verification="unverified")]),
        "mali_tatil_receivable_authority_unresolved",
    )

    # --- adım 5 ---
    belediye = _assess(
        rule, _case(items=[gv_linked], actions=[_action(authority="Kurgusal Belediye Başkanlığı")]),
    )
    belediye_result = _calc(rule, LAWYER_ANCHOR, belediye)
    belediye_today = _today(rule, LAWYER_ANCHOR, {"gelir vergisi"}, {"kurgusal belediye başkanlığı"})
    check(
        "[MÜHENDİS] adım 5: alacaklı idare belediye -> mali tatil YOK, kesin tarih hesaplanır "
        "(bugünkü istisna sonucuyla aynı tarih)",
        belediye["outcome"] == "no_mali_tatil"
        and belediye_result["calculation_state"] == CALCULATED
        and belediye_result["mali_tatil_applied"] is False
        and belediye_result["mali_tatil_exclusion_reason"] == "issuing_authority_excluded:belediye"
        and belediye_result["calculated_deadline"] == belediye_today["calculated_deadline"]
        == LAWYER_EXPECTED,
        (_state(belediye_result), _state(belediye_today)),
    )
    gumruk = _assess(rule, _case(items=[gv_linked], actions=[_action(authority="Kurgusal Gümrük Müdürlüğü")]))
    check(
        "[MÜHENDİS] adım 5: alacaklı idare gümrük -> mali tatil YOK",
        gumruk["outcome"] == "no_mali_tatil"
        and gumruk["exclusion_reason"] == "issuing_authority_excluded:gümrük",
        (gumruk["outcome"], gumruk["exclusion_reason"]),
    )
    for authority in ("Kurgusal Malmüdürlüğü", "Kurgusal Sigorta Kurumu", "Kurgusal Tahsilat Birimi"):
        review(
            f"[MÜHENDİS] adım 5: alacaklı idare '{authority}' tanınmıyor -> needs_review (K5)",
            _case(items=[gv_linked], actions=[_action(authority=authority)]),
            "mali_tatil_receivable_authority_unclassified",
        )
    dotted = _assess(rule, _case(items=[gv_linked], actions=[_action(authority="KURGUSAL VERGİ DAİRESİ")]))
    check(
        "[MÜHENDİS] adım 5: 'VERGİ DAİRESİ' (büyük İ) tanınır - Türkçe İ normalizasyonu (K5)",
        dotted["outcome"] == "apply",
        (dotted["outcome"], dotted["reason_code"]),
    )

    # --- adım 6 ---
    gecikme = review(
        "[MÜHENDİS] adım 6: bağlı kalem gecikme zammı -> needs_review (K4, fer'i tanınmaz)",
        _case(items=[_item("item_gz", "gecikme zammı")], actions=[_action()]),
        "mali_tatil_receivable_tax_type_unrecognized",
    )
    review(
        "[MÜHENDİS] adım 6: bağlı gelir vergisi + bağlı gecikme faizi -> needs_review (K4)",
        _case(items=[gv_linked, _item("item_gf", "gecikme faizi")], actions=[_action()]),
        "mali_tatil_receivable_tax_type_unrecognized",
    )
    blank = dict(_item("item_blank", "x"))
    blank["tax_type"] = "   "
    review(
        "[MÜHENDİS] adım 6: bağlı gelir vergisi yanında vergi türü BOŞ bağlı kalem -> needs_review "
        "(boş değer sessizce atılmaz)",
        _case(items=[gv_linked, blank], actions=[_action()]),
        "mali_tatil_receivable_tax_type_unrecognized",
    )
    check(
        "[MÜHENDİS] adım 6: gecikme zammı sonucunda iz notu belge ve kalem kimliğini taşır",
        gecikme["notes"][0]
        == "mali_tatil_receivable_link=action_document:%s;linked_dispute_items:item_gz;"
           "action:action_synth_001" % DOC,
        gecikme["notes"],
    )
    otv_only = _assess(rule, _case(items=[otv_linked], actions=[_action()]))
    otv_result = _calc(rule, LAWYER_ANCHOR, otv_only)
    check(
        "[MÜHENDİS] adım 6: yalnız ÖTV bağlı ve teyitli -> mali tatil YOK, 06.07.2026",
        otv_only["outcome"] == "no_mali_tatil"
        and otv_result["calculated_deadline"] == LAWYER_EXPECTED
        and otv_result["mali_tatil_applied"] is False,
        _state(otv_result),
    )
    mixed = _assess(rule, _case(items=[otv_linked, gv_linked], actions=[_action()]))
    mixed_result = _calc(rule, LAWYER_ANCHOR, mixed)
    today_mixed = _today(rule, LAWYER_ANCHOR, {"ötv", "gelir vergisi"})
    today_excluded = _today(rule, LAWYER_ANCHOR, {"ötv"})
    check(
        "[MÜHENDİS] adım 6: karışık (ÖTV + gelir vergisi, ikisi de bağlı ve teyitli) -> "
        "mali tatilsiz ERKEN tarih (avukat 3.2); bugün needs_review idi",
        mixed["outcome"] == "no_mali_tatil"
        and mixed_result["calculation_state"] == CALCULATED
        and mixed_result["mali_tatil_applied"] is False
        and mixed_result["mali_tatil_exclusion_reason"] == "mixed_receivables_no_mali_tatil"
        and mixed_result["calculated_deadline"] == today_excluded["calculated_deadline"]
        == LAWYER_EXPECTED
        and today_mixed["calculation_state"] == NEEDS_REVIEW,
        (_state(mixed_result), _state(today_mixed)),
    )
    gv_only = _assess(rule, _case(items=[gv_linked], actions=[_action()]))
    gv_result = _calc(rule, LAWYER_ANCHOR, gv_only)
    today_gv = _today(rule, LAWYER_ANCHOR, {"gelir vergisi"})
    check(
        "[MÜHENDİS] adım 8: yalnız gelir vergisi bağlı ve teyitli, idare vergi dairesi -> "
        "mali tatil UYGULANIR; tarih bugünkü dahil-sınıf hesabıyla aynı (aritmetik değişmedi)",
        gv_only["outcome"] == "apply"
        and gv_result["calculation_state"] == CALCULATED
        and gv_result["mali_tatil_applied"] is True
        and gv_result["calculated_deadline"] == today_gv["calculated_deadline"]
        and gv_result["provisional_deadline"] == today_gv["provisional_deadline"],
        (_state(gv_result), _state(today_gv)),
    )
    no_recess = _calc(rule, LAWYER_ANCHOR, gv_only, recess=False)
    today_no_recess = _today(rule, LAWYER_ANCHOR, {"gelir vergisi"}, recess=False)
    check(
        "[MÜHENDİS] Adım 7 C.6 yeni modda da korunur: asgari beş gün tarihi tek başına "
        "belirliyor ve adli tatil False -> needs_review (bugünküyle aynı)",
        no_recess["calculation_state"] == NEEDS_REVIEW
        and no_recess["calculated_deadline"] is None
        and "mali_tatil_grace_floor_unconfirmed_without_recess" in no_recess["reason"]
        and today_no_recess["calculation_state"] == NEEDS_REVIEW
        and "mali_tatil_grace_floor_unconfirmed_without_recess" in today_no_recess["reason"],
        (_state(no_recess), _state(today_no_recess)),
    )
    recess_unknown = _calc(rule, LAWYER_ANCHOR, gv_only, recess=None)
    check(
        "[MÜHENDİS] mali tatil uygulanan sonuç adli tatil dönemine düşüyor ve adli tatil "
        "beyanı bilinmiyor -> needs_review (mevcut kapı değişmedi)",
        recess_unknown["calculation_state"] == NEEDS_REVIEW
        and recess_unknown["calculated_deadline"] is None
        and recess_unknown["mali_tatil_applied"] is True,
        _state(recess_unknown),
    )

    # --- adım 7 ---
    guard = _assess(
        rule,
        _case(items=[gv_linked, _item("item_otv_unlinked", "ÖTV", docs=())], actions=[_action()]),
    )
    guard_result = _calc(rule, LAWYER_ANCHOR, guard)
    check(
        "[MÜHENDİS] adım 7: bağlı yalnız gelir vergisi + BAĞSIZ ÖTV -> needs_review; "
        "07.09.2026 kesin tarih olarak ÇIKMAZ",
        guard["outcome"] == NEEDS_REVIEW
        and guard["reason_code"] == "mali_tatil_receivable_unlinked_item_conflict"
        and guard_result["calculation_state"] == NEEDS_REVIEW
        and guard_result["calculated_deadline"] is None
        and guard["difference"] is True,
        (guard["reason_code"], _state(guard_result)),
    )
    for label, unlinked in (
        ("bilinmeyen tür", _item("item_x", "bilinmeyen vergi", docs=())),
        ("gecikme zammı", _item("item_gz", "gecikme zammı", docs=())),
        ("boş tür", dict(_item("item_e", "y", docs=()), tax_type="")),
    ):
        result = _assess(rule, _case(items=[gv_linked, unlinked], actions=[_action()]))
        check(
            f"[MÜHENDİS] adım 7: bağlı gelir vergisi + bağsız '{label}' kalem -> needs_review",
            result["outcome"] == NEEDS_REVIEW
            and result["reason_code"] == "mali_tatil_receivable_unlinked_item_conflict",
            (result["outcome"], result["reason_code"]),
        )
    unlinked_included = _assess(
        rule,
        _case(items=[gv_linked, _item("item_kdv_unlinked", "KDV", docs=())], actions=[_action()]),
    )
    check(
        "[MÜHENDİS] adım 7: bağsız kalem de dahil sınıfta (KDV) -> mali tatil uygulanır, fark notu YOK",
        unlinked_included["outcome"] == "apply" and unlinked_included["difference"] is False,
        (unlinked_included["outcome"], unlinked_included["notes"]),
    )
    early = _assess(
        rule,
        _case(items=[otv_linked, _item("item_bilinmeyen", "bilinmeyen vergi", docs=())],
              actions=[_action()]),
    )
    check(
        "[MÜHENDİS] adım 7 yalnız mali tatil UYGULATACAK sonucu durdurur: bağlı ÖTV + bağsız "
        "bilinmeyen tür -> mali tatilsiz erken tarih",
        early["outcome"] == "no_mali_tatil" and early["difference"] is True,
        (early["outcome"], early["reason_code"]),
    )

    # --- adım 9 ---
    same_classes = _assess(
        rule,
        _case(items=[otv_linked, _item("item_bsmv", "BSMV", docs=())], actions=[_action()]),
    )
    check(
        "[MÜHENDİS] adım 9: bağlı ve bağsız kalemlerin sınıfı aynı -> fark notu YOK",
        same_classes["difference"] is False
        and not any(n.startswith("mali_tatil_receivable_difference=") for n in same_classes["notes"]),
        same_classes["notes"],
    )
    only_linked = _assess(rule, _case(items=[otv_linked], actions=[_action()]))
    check(
        "[MÜHENDİS] adım 9 okuması (yazar kararı): bağsız kalem yoksa fark tanımsızdır -> not YOK",
        only_linked["difference"] is False and len(only_linked["notes"]) == 1,
        only_linked["notes"],
    )

    # --- adım 13 ---
    related = _assess(
        rule,
        _case(items=[gv_linked, _item("item_otv_unlinked", "ÖTV", docs=())], actions=[_action()]),
        anchor=_anchor(related=["item_gv", "item_otv_unlinked"]),
    )
    check(
        "[MÜHENDİS] adım 13: çapanın related_dispute_item_ids alanı bağ kurmaz (kullanılmaz)",
        related["outcome"] == NEEDS_REVIEW
        and related["reason_code"] == "mali_tatil_receivable_unlinked_item_conflict"
        and related["linked_dispute_item_ids"] == ["item_gv"],
        (related["outcome"], related["linked_dispute_item_ids"]),
    )

    # --- bozuk girdi ---
    broken = dc.evaluate_mali_tatil_action_document_receivables(None, None, rule, None)
    broken2 = dc.evaluate_mali_tatil_action_document_receivables(
        {"dispute_items": "x", "administrative_actions": 5}, _anchor(), rule, _index(rule),
    )
    check(
        "[MÜHENDİS] bozuk girdi hata fırlatmaz, needs_review sonucu verir",
        broken["outcome"] == NEEDS_REVIEW and broken2["outcome"] == NEEDS_REVIEW,
        (broken["reason_code"], broken2["reason_code"]),
    )


# ================================================================
# [MÜHENDİS] DÜZELTME TURU 1 - SINIR DURUMLARI (M-1) VE TİP KONTROLÜ (L-1)
#
# M1-a..M1-f: bağımsız incelemede (RM02, RM05, RM08, RM09, RM10, RM12)
# testlerin yakalamadığı geç tarih yönündeki kapıları sabitler. Bunlar
# MEVCUT doğru davranışı sabitler; kod değişikliği gerektirmez.
# L-1: alacaklı idare metin değilse veya işlem listesinde sözlük olmayan
# kayıt varsa kesin tarih yok (yalnız şemaya AYKIRI girdi).
# Kurum adları KURGUSALDIR.
# ================================================================

CASE_SCHEMA_PATH = REAL_DATA_DIR / "case.schema.json"


def test_round1_boundaries(ruleset):
    rule = _activated(_rule_by_id(ruleset, PAYMENT_ORDER))
    gv_linked = _item("item_gv", "Gelir Vergisi")

    def review(label, case, code, anchor=None, index=None):
        assessment = _assess(rule, case, anchor=anchor, index=index)
        result = _calc(rule, LAWYER_ANCHOR, assessment)
        check(
            label,
            assessment["outcome"] == NEEDS_REVIEW
            and assessment["reason_code"] == code
            and result["calculation_state"] == NEEDS_REVIEW
            and result["calculated_deadline"] is None
            and result.get("mali_tatil_receivable_reason_code") == code
            and ("reason_code=" + code) in result["reason"],
            {"assessment": (assessment["outcome"], assessment["reason_code"]),
             "result": _state(result)},
        )

    control = _assess(rule, _case(items=[gv_linked], actions=[_action()]))
    control_result = _calc(rule, LAWYER_ANCHOR, control)
    check(
        "[MÜHENDİS] M1/L-1 kontrol: aynı kurgu, tek teyitli 'vergi dairesi' kaydı -> mali tatil "
        "uygulanır, 07.09.2026 (aşağıdaki needs_review kontrolleri non-vacuous)",
        control["outcome"] == "apply"
        and control_result["calculation_state"] == CALCULATED
        and control_result["calculated_deadline"] == LATE_DATE_NOT_TO_PRESENT,
        _state(control_result),
    )

    # --- M1-a: adım 4, işlem kaydının verified dışı her şema değeri ---
    schema_states = _load_json(CASE_SCHEMA_PATH)["$defs"]["verificationState"]["enum"]
    non_verified = [value for value in schema_states if value != "verified"]
    check(
        "[MÜHENDİS] M1-a ön koşul: case.schema.json verificationState enum'unda 'verified' "
        "dışı değerler var (partially_verified dahil)",
        "verified" in schema_states
        and "partially_verified" in non_verified
        and len(non_verified) >= 1,
        schema_states,
    )
    for state in non_verified:
        review(
            f"[MÜHENDİS] M1-a adım 4: idari işlem kaydı verification_state='{state}' -> "
            "needs_review, kesin tarih yok",
            _case(items=[gv_linked], actions=[_action(verification=state)]),
            "mali_tatil_receivable_authority_unresolved",
        )

    # --- M1-b: adım 4, aynı belgeye biri teyitli biri teyitsiz iki kayıt ---
    review(
        "[MÜHENDİS] M1-b adım 4: aynı işlem belgesine iki idari işlem kaydı (biri verified "
        "vergi dairesi, biri unverified) -> needs_review (teklik tüm kayıtlarda aranır)",
        _case(items=[gv_linked],
              actions=[_action("action_verified"),
                       _action("action_unverified", authority="Kurgusal Belediye Başkanlığı",
                               verification="unverified")]),
        "mali_tatil_receivable_authority_unresolved",
    )
    review(
        "[MÜHENDİS] M1-b adım 4: aynı işlem belgesine iki kayıt, ikisi de 'vergi dairesi', "
        "biri unverified -> needs_review",
        _case(items=[gv_linked],
              actions=[_action("action_verified"),
                       _action("action_unverified", verification="unverified")]),
        "mali_tatil_receivable_authority_unresolved",
    )

    # --- M1-c: adım 5, istisna anahtar kelimesi + "vergi dairesi" ---
    both = _assess(
        rule,
        _case(items=[gv_linked], actions=[_action(authority="Kurgusal Belediye Vergi Dairesi")]),
    )
    both_result = _calc(rule, LAWYER_ANCHOR, both)
    check(
        "[MÜHENDİS] M1-c adım 5: idare adında hem 'belediye' hem 'vergi dairesi' -> istisna ÖNCE: "
        "mali tatil YOK, erken tarih 06.07.2026 (07.09.2026 DEĞİL)",
        both["outcome"] == "no_mali_tatil"
        and both["exclusion_reason"] == "issuing_authority_excluded:belediye"
        and both_result["calculation_state"] == CALCULATED
        and both_result["mali_tatil_applied"] is False
        and both_result["mali_tatil_exclusion_reason"] == "issuing_authority_excluded:belediye"
        and both_result["calculated_deadline"] == LAWYER_EXPECTED
        and both_result["calculated_deadline"] != LATE_DATE_NOT_TO_PRESENT,
        (both["outcome"], both["exclusion_reason"], _state(both_result)),
    )
    gumruk_both = _assess(
        rule,
        _case(items=[gv_linked], actions=[_action(authority="Kurgusal Gümrük Vergi Dairesi")]),
    )
    gumruk_both_result = _calc(rule, LAWYER_ANCHOR, gumruk_both)
    check(
        "[MÜHENDİS] M1-c adım 5: idare adında hem 'gümrük' hem 'vergi dairesi' -> mali tatil YOK, "
        "06.07.2026",
        gumruk_both["outcome"] == "no_mali_tatil"
        and gumruk_both["exclusion_reason"] == "issuing_authority_excluded:gümrük"
        and gumruk_both_result["calculated_deadline"] == LAWYER_EXPECTED,
        (gumruk_both["outcome"], gumruk_both["exclusion_reason"], _state(gumruk_both_result)),
    )

    # --- M1-d: adım 5 (K5), "vergi" geçen ama "vergi dairesi" geçmeyen ---
    for authority in ("Kurgusal Vergi Tahsilat Birimi", "Kurgusal Vergi Müdürlüğü"):
        review(
            f"[MÜHENDİS] M1-d adım 5 (K5): idare '{authority}' ('vergi' var, 'vergi dairesi' "
            "yok) -> needs_review",
            _case(items=[gv_linked], actions=[_action(authority=authority)]),
            "mali_tatil_receivable_authority_unclassified",
        )

    # --- M1-e: adım 2, kalem çapanın işlem belgesi OLMAYAN belgesine bağlı ---
    review(
        "[MÜHENDİS] M1-e adım 2: çapada işlem belgesi + başka belge; kalem yalnız diğer belgeye "
        "bağlı -> needs_review (alacak ile işlem arasında bağ yok)",
        _case(items=[_item("item_gv", "Gelir Vergisi", docs=(OTHER_DOC,))], actions=[_action()]),
        "mali_tatil_receivable_no_linked_item",
        anchor=_anchor(docs=(DOC, OTHER_DOC)),
        index={DOC: "odeme_emri", OTHER_DOC: "dava_dilekcesi"},
    )

    # --- M1-f (RM08): sözlük olmayan (bağsız) uyuşmazlık kaydı ---
    for label, junk in (("metin", "kurgusal-bozuk-kalem-kaydi"), ("sayı", 42)):
        review(
            f"[MÜHENDİS] M1-f adım 7: bağlı teyitli gelir vergisi + sözlük olmayan dispute_items "
            f"kaydı ({label}) -> needs_review (sessizce atlanmaz)",
            _case(items=[gv_linked, junk], actions=[_action()]),
            "mali_tatil_receivable_unlinked_item_conflict",
        )

    # --- L-1: alacaklı idare metin değil / işlem listesinde sözlük olmayan kayıt ---
    for label, authority in (
        ("liste", ["Kurgusal Vergi Dairesi"]),
        ("sözlük", {"ad": "Kurgusal Vergi Dairesi"}),
    ):
        review(
            f"[MÜHENDİS] L-1 adım 4: issuing_authority {label} (içinde 'Kurgusal Vergi Dairesi') -> "
            "needs_review (alacaklı idare belirlenemedi), 07.09.2026 yok",
            _case(items=[gv_linked], actions=[_action(authority=authority)]),
            "mali_tatil_receivable_authority_unresolved",
        )
    review(
        "[MÜHENDİS] L-1 adım 4: administrative_actions listesinde geçerli kaydın yanında sözlük "
        "olmayan kayıt -> needs_review (teklik sayımı onu atlamaz)",
        _case(items=[gv_linked], actions=[_action(), "kurgusal-bozuk-islem-kaydi"]),
        "mali_tatil_receivable_authority_unresolved",
    )


# ================================================================
# [MÜHENDİS] ADIM 11 - ESKİ BİÇİMLİ / BOŞ BAĞLAM, YANLIŞ SONUÇ NESNESİ
# ================================================================

def test_context_guard(ruleset):
    rule = _activated(_rule_by_id(ruleset, PAYMENT_ORDER))
    good = _assess(rule, _case(items=[_item("item_gv", "Gelir Vergisi")], actions=[_action()]))
    cases = [
        ("bağlam None", None, "mali_tatil_receivable_context_missing"),
        ("eski biçimli dosya-geneli bağlam (gelir vergisi)",
         {"tax_types": {"gelir vergisi"}, "issuing_authorities": set()},
         "mali_tatil_receivable_context_missing"),
        ("eski biçimli dosya-geneli bağlam (ÖTV)",
         {"tax_types": {"ötv"}, "issuing_authorities": set()},
         "mali_tatil_receivable_context_missing"),
        ("başka kurala ait sonuç nesnesi",
         dict(good, rule_id=SEIZURE), "mali_tatil_receivable_context_missing"),
        ("bilinmeyen outcome", dict(good, outcome="maybe"), "mali_tatil_receivable_context_missing"),
        ("istisna gerekçesi boş no_mali_tatil",
         dict(good, outcome="no_mali_tatil", exclusion_reason=""),
         "mali_tatil_receivable_context_missing"),
        ("needs_review ama gerekçe kodu tanınmıyor",
         dict(good, outcome="needs_review", reason_code="x"),
         "mali_tatil_receivable_context_missing"),
    ]
    for label, context, code in cases:
        result = _calc(rule, LAWYER_ANCHOR, context)
        check(
            f"[MÜHENDİS] adım 11: {label} + Temmuz'a değen süre -> needs_review "
            "(dosya geneline sessizce DÖNMEZ)",
            result["calculation_state"] == NEEDS_REVIEW
            and result["calculated_deadline"] is None
            and result["mali_tatil_applied"] is False
            and result.get("mali_tatil_receivable_reason_code") == code,
            _state(result),
        )
    unknown_basis = copy.deepcopy(rule)
    unknown_basis[FIELD] = "file_wide"
    result = _calc(unknown_basis, LAWYER_ANCHOR, dict(good))
    check(
        "[MÜHENDİS] kuralda tanınmayan alan değeri (bellekte) -> needs_review (dosya geneline DÖNMEZ)",
        result["calculation_state"] == NEEDS_REVIEW
        and result.get("mali_tatil_receivable_reason_code") == "mali_tatil_receivable_basis_unknown",
        _state(result),
    )
    check(
        "[MÜHENDİS] doğru sonuç nesnesiyle aynı çağrı hesaplanır (kontrol non-vacuous)",
        _calc(rule, LAWYER_ANCHOR, good)["calculation_state"] == CALCULATED,
    )


# ================================================================
# [MÜHENDİS] K6 - TEMMUZ'A DEĞMEYEN SÜRE
# ================================================================

def test_k6_window(ruleset):
    for rule_id in DRAFT_RULE_IDS:
        rule = _activated(_rule_by_id(ruleset, rule_id))
        for label, context in (
            ("bağlam None", None),
            ("eski biçimli bağlam", {"tax_types": {"ötv"}, "issuing_authorities": set()}),
            ("bağ yok", _assess(rule, _case(items=[_item("i_1", "ÖTV", docs=())], actions=[]))),
        ):
            new = _calc(rule, NON_JULY_ANCHOR, context)
            old = _calc(_without_field(rule), NON_JULY_ANCHOR,
                        {"tax_types": {"gelir vergisi"}, "issuing_authorities": set()})
            check(
                f"[MÜHENDİS] K6 {rule_id}: Şubat çapası, {label} -> sonuç bugünküyle BİREBİR aynı "
                "(window_not_relevant, hesaplandı)",
                new == old
                and new["calculation_state"] == CALCULATED
                and new["mali_tatil_exclusion_reason"] == "window_not_relevant",
                (_state(new), _state(old)),
            )


# ================================================================
# GEÇİCİ DİZİN - UÇTAN UCA (build_deadline_record)
# ================================================================

def _verified_provisions_fixture(tmp_root):
    """Üretim hüküm kaydının GEÇİCİ kopyası: 6183 m.58/1 ve m.15/1
    "doğrulanmış" kurulur (etkinleştirme sonrasının VARSAYIMSAL
    modeli). Üretim kaydı DEĞİŞTİRİLMEZ."""
    manifest = _load_json(PROVISIONS_PATH)
    for provision in manifest["provisions"]:
        if provision["provision_id"] not in ("kanun_6183_m58_f1", "kanun_6183_m15_f1"):
            continue
        provision["verification_state"] = "verified"
        provision["formal"]["verified"] = True
        provision["formal"]["status"] = "active"
        provision["formal"]["valid_from"] = "2018-01-01"
        for item in provision["formal"]["evidence"]:
            item["verified"] = True
        provision["formal"]["evidence"].append({
            "evidence_id": "ev_test_only_%s_mt_a" % provision["provision_id"],
            "kind": "amending_law",
            "source_document_id": None,
            "source_url": "https://example.invalid/test-only-fixture",
            "citation": "YALNIZ TEST: sentetik kanıt",
            "verified": True,
            "notes": "Geçici test kopyası; üretim kaydı değildir.",
        })
    path = tmp_root / "provisions_verified_fixture.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_case(cases_dir, case_id, case, documents):
    case_dir = cases_dir / case_id
    (case_dir / "documents").mkdir(parents=True)
    data = dict(case, case_id=case_id)
    (case_dir / "case.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    for document_id, document_type in documents.items():
        doc_dir = case_dir / "documents" / document_id
        doc_dir.mkdir()
        (doc_dir / "document.json").write_text(json.dumps({
            "schema_version": 1,
            "document_id": document_id,
            "case_id": case_id,
            "active": True,
            "document_type": document_type,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class _E2E:
    def __init__(self, ruleset, tmp_root):
        self.cases_dir = tmp_root / "cases"
        self.cases_dir.mkdir()
        self.provisions_path = _verified_provisions_fixture(tmp_root)
        active = copy.deepcopy(ruleset)
        for rule in active["rules"]:
            if rule["rule_id"] in DRAFT_RULE_IDS:
                rule["status"] = "active"
                rule["calculation_enabled"] = True
        self.active = active
        self.ruleset_path = tmp_root / "deadline_rules_active_fixture.json"
        self.ruleset_path.write_text(
            json.dumps(active, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        self.counter = 0

    def record(self, document_type, case, anchor_date, recess=True, documents=None):
        self.counter += 1
        case_id = "kola_mt_a_case_%03d" % self.counter
        _write_case(self.cases_dir, case_id, case, documents or {DOC: document_type})
        anchor = _anchor(date=anchor_date)
        case_data, _ = deadline_validator.load_case(case_id)
        context = selection.build_case_context(case_id, case_data, anchor)
        sel = selection.select_deadline_rule(self.active, anchor, context)
        record = dc.build_deadline_record(
            case_id=case_id,
            anchor_event=anchor,
            selection=sel,
            ruleset_path=self.ruleset_path,
            holiday_calendar=CALENDAR,
            judicial_recess_applicable=recess,
            provisions_path=self.provisions_path,
            stopping_event_status="none",
            stopping_event_attestation_ref=ATTESTATION_REF,
        )
        return sel, record


def _notes(record):
    return record.get("notes") or ""


def test_end_to_end(ruleset, tmp_root):
    e2e = _E2E(ruleset, tmp_root)
    for rule_id, document_type in (
        (PAYMENT_ORDER, "odeme_emri"),
        (SEIZURE, "borcluya_haciz_bildirimi"),
        (SEIZURE, "borcluya_e_haciz_bildirimi"),
        (PRECAUTIONARY, "ihtiyati_haciz_giyapta_tebligi"),
    ):
        rule = _activated(_rule_by_id(ruleset, rule_id))
        for label, items, tax_types in (
            ("bağlı teyitli gelir vergisi", [_item("item_gv", "Gelir Vergisi")], {"gelir vergisi"}),
            ("bağlı teyitli ÖTV", [_item("item_otv", "ÖTV")], {"ötv"}),
        ):
            sel, record = e2e.record(
                document_type, _case(items=items, actions=[_action()]), LAWYER_ANCHOR,
            )
            today = _today(rule, LAWYER_ANCHOR, tax_types)
            check(
                f"[MÜHENDİS] uçtan uca {rule_id} / {document_type} / {label}: belge kaydı -> "
                "seçim -> bağ -> hesap; tarih aynı sınıfla bugünkü hesapla aynı",
                sel["selection_state"] == "selected"
                and sel["selected_rule"]["rule_id"] == rule_id
                and record["calculation_state"] == CALCULATED
                and record["calculated_deadline"] == today["calculated_deadline"]
                and record["rule_id"] == rule_id
                and ("mali_tatil_receivable_link=action_document:%s;linked_dispute_items:%s"
                     % (DOC, items[0]["dispute_item_id"])) in _notes(record),
                {k: record.get(k) for k in ("calculation_state", "calculated_deadline", "notes")},
            )
        sel, record = e2e.record(
            document_type, _case(items=[_item("item_gv", "Gelir Vergisi", docs=())],
                                 actions=[_action()]), LAWYER_ANCHOR,
        )
        check(
            f"[MÜHENDİS] uçtan uca {rule_id} / {document_type}: bağ yok + Temmuz -> needs_review, "
            "notta gerekçe kodu",
            record["calculation_state"] == NEEDS_REVIEW
            and record["calculated_deadline"] is None
            and record["requires_human_review"] is True
            and "reason_code=mali_tatil_receivable_no_linked_item" in _notes(record),
            {k: record.get(k) for k in ("calculation_state", "notes")},
        )

    # [AVUKAT 4.2] uçtan uca: not hem hesaplanan kayıtta.
    sel, record = e2e.record(
        "odeme_emri",
        _case(items=[_item("item_otv", "ÖTV"), _item("item_gv", "Gelir Vergisi", docs=())],
              actions=[_action()]),
        LAWYER_ANCHOR,
    )
    check(
        "[AVUKAT 4.2] uçtan uca: 06.07.2026, kayıt notunda fark uyarısı + iz + ÖTV istisnası",
        record["calculation_state"] == CALCULATED
        and record["calculated_deadline"] == LAWYER_EXPECTED
        and "mali_tatil=tax_type_excluded:ötv" in _notes(record)
        and "mali_tatil_receivable_difference=linked:excluded;unlinked:included;"
            "unlinked_dispute_items:item_gv" in _notes(record)
        and "mali_tatil_receivable_link=action_document:%s;linked_dispute_items:item_otv;"
            "action:action_synth_001" % DOC in _notes(record),
        _notes(record),
    )

    # adım 9: fark notu needs_review sonucunda da.
    sel, record = e2e.record(
        "odeme_emri",
        _case(items=[_item("item_otv", "ÖTV", verification="unverified"),
                     _item("item_gv", "Gelir Vergisi", docs=())],
              actions=[_action()]),
        LAWYER_ANCHOR,
    )
    check(
        "[MÜHENDİS] adım 9: fark notu needs_review kaydında da görünür (teyitsiz bağlı ÖTV + "
        "bağsız gelir vergisi)",
        record["calculation_state"] == NEEDS_REVIEW
        and "reason_code=mali_tatil_receivable_item_unverified" in _notes(record)
        and "mali_tatil_receivable_difference=linked:excluded;unlinked:included" in _notes(record),
        _notes(record),
    )
    sel, record = e2e.record(
        "odeme_emri",
        _case(items=[_item("item_gv", "Gelir Vergisi"), _item("item_otv", "ÖTV", docs=())],
              actions=[_action()]),
        LAWYER_ANCHOR,
    )
    check(
        "[MÜHENDİS] adım 7 + 9 uçtan uca: bağlı gelir vergisi + bağsız ÖTV -> needs_review, "
        "07.09.2026 yok, fark notu var",
        record["calculation_state"] == NEEDS_REVIEW
        and record["calculated_deadline"] is None
        and "reason_code=mali_tatil_receivable_unlinked_item_conflict" in _notes(record)
        and "mali_tatil_receivable_difference=linked:included;unlinked:excluded" in _notes(record),
        _notes(record),
    )
    sel, record = e2e.record(
        "odeme_emri",
        _case(items=[_item("item_otv", "ÖTV"), _item("item_gv", "Gelir Vergisi")],
              actions=[_action()]),
        LAWYER_ANCHOR,
    )
    check(
        "[MÜHENDİS] karışık uçtan uca: not 'mali_tatil=mixed_receivables_no_mali_tatil', "
        "erken tarih 06.07.2026",
        record["calculation_state"] == CALCULATED
        and record["calculated_deadline"] == LAWYER_EXPECTED
        and "mali_tatil=mixed_receivables_no_mali_tatil" in _notes(record),
        _notes(record),
    )
    sel, record = e2e.record(
        "odeme_emri",
        _case(items=[_item("item_gv", "Gelir Vergisi")], actions=[_action()]),
        LAWYER_ANCHOR,
        recess=None,
    )
    check(
        "[MÜHENDİS] mali tatil sonrası adli tatil beyanı bilinmiyor (sonraki kapı) -> needs_review "
        "ve iz notu yine kayıtta",
        record["calculation_state"] == NEEDS_REVIEW
        and "mali_tatil_receivable_link=action_document:%s" % DOC in _notes(record),
        _notes(record),
    )

    # K6 uçtan uca: Şubat çapası, bağ yok -> bugünküyle aynı kayıt, ek not yok.
    sel, record = e2e.record(
        "odeme_emri",
        _case(items=[_item("item_otv", "ÖTV", docs=())], actions=[]),
        NON_JULY_ANCHOR,
    )
    check(
        "[MÜHENDİS] K6 uçtan uca: Şubat çapası, bağ yok -> hesaplandı (25.02.2026), "
        "kayıtta mali_tatil_receivable notu YOK",
        record["calculation_state"] == CALCULATED
        and record["calculated_deadline"] == "2026-02-25"
        and "mali_tatil_receivable" not in _notes(record),
        _notes(record),
    )

    # İYUK ihbarname kuralı dosya-geneli davranışını korur.
    sel, record = e2e.record(
        "vergi_ceza_ihbarnamesi",
        _case(items=[_item("item_gv", "Gelir Vergisi", docs=())], actions=[]),
        LAWYER_ANCHOR,
    )
    iyuk_rule = _rule_by_id(ruleset, IYUK_RULE_ID)
    iyuk_today = _calc(iyuk_rule, LAWYER_ANCHOR,
                       {"tax_types": {"gelir vergisi"}, "issuing_authorities": set()})
    check(
        "[MÜHENDİS] İYUK ihbarname kuralı: bağ ve işlem kaydı OLMADAN dosya-geneli gelir "
        "vergisiyle hesaplanır (değişmedi), yeni not yok",
        sel["selected_rule"]["rule_id"] == IYUK_RULE_ID
        and record["calculation_state"] == CALCULATED
        and record["calculated_deadline"] == iyuk_today["calculated_deadline"]
        and "mali_tatil_receivable" not in _notes(record),
        (_notes(record), _state(iyuk_today)),
    )
    return e2e


def run_self_test():
    global CALENDAR
    before = _snapshot_data_tree()
    CALENDAR = dc.load_holiday_calendar()
    ruleset = _load_json(RULESET_PATH)

    test_registry_and_schema(ruleset)
    test_lawyer_example(ruleset)
    test_steps(ruleset)
    test_round1_boundaries(ruleset)
    test_context_guard(ruleset)
    test_k6_window(ruleset)

    tmp_root = Path(tempfile.mkdtemp(prefix="vergi_kola_mt_a_"))
    original_cases_dir = deadline_validator.CASES_DIR
    original_selection_data_dir = selection.DATA_DIR
    try:
        deadline_validator.CASES_DIR = tmp_root / "cases"
        selection.DATA_DIR = tmp_root
        test_end_to_end(ruleset, tmp_root)
    finally:
        deadline_validator.CASES_DIR = original_cases_dir
        selection.DATA_DIR = original_selection_data_dir
        shutil.rmtree(tmp_root, ignore_errors=True)
    check(
        "yama geri alındı ve geçici dizin silindi",
        deadline_validator.CASES_DIR == original_cases_dir
        and selection.DATA_DIR == original_selection_data_dir
        and not tmp_root.exists(),
    )
    after = _snapshot_data_tree()
    check(
        "bu test modülü: gerçek data/ ağacı tüm koşu boyunca bayt-değişmez",
        before == after,
    )
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    ok = run_self_test()
    sys.exit(0 if ok else 1)
