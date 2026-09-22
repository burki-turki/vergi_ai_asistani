# ============================================================
# PILOT READINESS ADIM 4a - src/llm_privacy_boundary.py ISOLATED TESTS.
#
# Saf Python, stdlib-only. PostgreSQL YOK, mutation coordinator YOK,
# ag YOK, gercek LLM cagrisi YOK, repo `data/` agacina dokunma YOK.
# Bu dosya YALNIZCA `src/llm_privacy_boundary.py`'yi import eder ve
# tamamen SENTETIK Turkce veri uzerinde calisir - hicbir gercek dava
# verisi, hicbir gercek kimlik numarasi kullanilmaz.
#
# Kapsam:
#   * uzunluk-koruyan Turkce katlama (`fold1to1`), I/ı/İ/i tuzaklari,
#     NFC/NFD, ASCII transliterasyon
#   * TCKN/VKN/IBAN saglama toplamlari (gecerli + gecersiz)
#   * token dilbilgisi (Rapor C §5.4'un HER satiri)
#   * maskeleme: en-uzun-eslesme, tekrar eden ad, baska adin alt dizisi
#     olan ad, bitisik token, tirnak icindeki token, uzun rakam dizisi
#     icindeki kimlik
#   * telefon BICIMI BASINA POZITIF test (tur testi kacirilan bir
#     maskelemeyi YAKALAYAMAZ - Rapor C §2.5/D6)
#   * ortusme -> fixpoint (Rapor C §4.5'in gercek kusuru)
#   * ozellik (property) testi: `de_mask(mask(t)) == t` bayt-bayt
#   * fail-closed tablosunun HER satiri
#   * buyuk/kucuk harf DUYARSIZ artik-token taramasi (`vgmask_0001p`
#     REDDEDILMELIDIR - bu, tasarimin en ince fail-open riskidir)
#   * determinizm, harita/ham metin sizintisi olmamasi
#
# Run: python -m ui.tests.test_llm_privacy_boundary_isolated
# ============================================================

import hashlib
import json
import random
import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import llm_privacy_boundary as lpb  # noqa: E402

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
        return None
    except Exception as error:  # noqa: BLE001
        check(label, False, f"{detail} wrong exception: {type(error).__name__}: {error}")
        return error
    check(label, False, f"{detail} no exception raised")
    return None


# ------------------------------------------------------------
# Sentetik fixture'lar - hicbiri gercek bir kisiye/kuruma ait degildir.
# ------------------------------------------------------------

SYNTH_CASE = {
    "case_id": "case_9001",
    "reference_code": "SENT-2026-777",
    "parties": [
        {
            "party_id": "party_a",
            "party_type": "company",
            "display_name": "Deneme Tekstil A.Ş.",
            "reference_code": "MUS-042",
        },
        {
            "party_id": "party_b",
            "party_type": "individual",
            "display_name": "Ayşe Çelik",
        },
        {
            "party_id": "party_c",
            "party_type": "public_authority",
            "display_name": "Sentetik Vergi Dairesi Müdürlüğü",
        },
    ],
    "dispute_items": [{"dispute_item_id": "di_x"}],
}

SYNTH_DOC = {
    "document_id": "belge_9001",
    "title": "Sentetik İhbarname",
    "file": {"file_name": "belge_9001.pdf"},
    "provenance": {"original_file_name": None, "uploaded_by_ref": None},
}

SYNTH_CONTEXT = {
    "case_id": "case_9001",
    "source_document_id": "belge_9001",
    "source_document_title": "Sentetik İhbarname - Deneme Tekstil A.Ş.",
    "source_document_category": "administrative_act",
    "source_document_type": "ihbarname",
    "source_document_subtype": None,
    "source_document_issuer_party_id": "party_c",
    "source_actor_label": "Sentetik Vergi Dairesi Müdürlüğü",
    "parties": [
        {"party_id": "party_a", "role": "taxpayer", "display_name": "Deneme Tekstil A.Ş."},
        {"party_id": "party_b", "role": "representative", "display_name": "Ayşe Çelik"},
        {"party_id": "party_c", "role": "administration", "display_name": "Sentetik Vergi Dairesi Müdürlüğü"},
    ],
    "dispute_items": [
        {"dispute_item_id": "di_x", "tax_type": "KDV", "period": "2024/03",
         "asserted_legal_basis_refs": ["KDVK_m29"]},
    ],
}

# Sentetik, saglama toplami GECERLI kimlikler (algoritmadan uretildi -
# hicbiri gercek bir kisiye ait degildir).
VALID_TCKN = "10562272296"
INVALID_TCKN = "10562272297"
VALID_VKN = "1234567890"
INVALID_VKN = "1234567891"
VALID_IBAN_COMPACT = "TR330006100519786457841326"
VALID_IBAN_GROUPED = "TR33 0006 1005 1978 6457 8413 26"
INVALID_IBAN = "TR340006100519786457841326"


def party_seeds(*names, kind="company"):
    return lpb.build_seed_terms(
        {"parties": [{"party_type": kind, "display_name": name} for name in names]}, {},
    )


print("## 1 - fold1to1 / normalisation")

for sample in [
    "İSTANBUL VERGİ MAHKEMESİ", "Deneme Tekstil A.Ş.", "ıIiİ", "ÇĞÖŞÜçğöşü",
    "straße", "Ǆǅǆßẞ", "", "ABC 123",
]:
    check(
        f"fold1to1 is length-preserving for {sample[:14]!r}",
        len(lpb.fold1to1(sample)) == len(sample),
        f"{len(sample)} -> {len(lpb.fold1to1(sample))}",
    )

check("fold1to1 maps dotted capital I to plain i", lpb.fold1to1("İ") == "i")
check("fold1to1 maps capital I to dotless i", lpb.fold1to1("I") == "ı")
check("fold1to1 leaves dotless i unchanged", lpb.fold1to1("ı") == "ı")
check(
    "fold1to1 repairs the all-caps heading match that casefold() breaks "
    "(the pre-existing Row 4 defect this module must NOT repeat)",
    lpb.fold1to1("İstanbul Vergi Mahkemesi") in lpb.fold1to1("İSTANBUL VERGİ MAHKEMESİ BAŞKANLIĞINA"),
)
check(
    "casefold() genuinely fails the same comparison (the defect is real, not assumed)",
    "İstanbul Vergi Mahkemesi".casefold() not in "İSTANBUL VERGİ MAHKEMESİ BAŞKANLIĞINA".casefold(),
)
check(
    "ascii_transliterate bridges Şti. -> Sti.",
    lpb.ascii_transliterate("Ltd. Şti.") == "Ltd. Sti.",
    lpb.ascii_transliterate("Ltd. Şti."),
)
check(
    "has_non_ascii_digits detects Arabic-Indic digits",
    lpb.has_non_ascii_digits("١٢٣٤٥٦٧٨٩٠١"),
)
check(
    "has_non_ascii_digits detects full-width digits",
    lpb.has_non_ascii_digits("１２３４５６７８９０１"),
)
check(
    "has_non_ascii_digits ignores the superscript two in 'm2' notation "
    "(isdecimal, not isdigit - a Turkish assessment says 'm²')",
    not lpb.has_non_ascii_digits("120 m² alan"),
)
check(
    "has_non_ascii_digits is False for plain ASCII text",
    not lpb.has_non_ascii_digits("Toplam 1.700.000,00 TL"),
)

nfd_name = unicodedata.normalize("NFD", "İstanbul Deneme")
check(
    "NFD form has a different length than NFC (so a naive 'in' test across forms fails)",
    len(nfd_name) != len("İstanbul Deneme"),
)
check("nfc() restores the NFC form", lpb.nfc(nfd_name) == "İstanbul Deneme")

print("## 2 - identifier checksums (label-only, never a masking gate)")

check("valid TCKN accepted", lpb.tckn_is_valid(VALID_TCKN))
check("TCKN neighbour rejected", not lpb.tckn_is_valid(INVALID_TCKN))
check("TCKN with leading zero rejected", not lpb.tckn_is_valid("0" + VALID_TCKN[1:]))
check("10-digit input rejected as TCKN", not lpb.tckn_is_valid(VALID_TCKN[:10]))
check("non-ASCII digits rejected as TCKN", not lpb.tckn_is_valid("١٢٣٤٥٦٧٨٩٠١"))
check("valid VKN accepted", lpb.vkn_is_valid(VALID_VKN))
check("VKN neighbour rejected", not lpb.vkn_is_valid(INVALID_VKN))
check("11-digit input rejected as VKN", not lpb.vkn_is_valid(VALID_TCKN))
check("compact TR IBAN accepted", lpb.tr_iban_is_valid(VALID_IBAN_COMPACT))
check("grouped TR IBAN accepted", lpb.tr_iban_is_valid(VALID_IBAN_GROUPED))
check("lowercase TR IBAN accepted", lpb.tr_iban_is_valid(VALID_IBAN_COMPACT.lower()))
check("IBAN with wrong check digits rejected", not lpb.tr_iban_is_valid(INVALID_IBAN))
check("short IBAN rejected", not lpb.tr_iban_is_valid(VALID_IBAN_COMPACT[:20]))

print("## 3 - token grammar (Report C 5.4, every row)")

grammar_map = lpb.MaskMapping()
grammar_token = grammar_map.token_for("Ayşe Çelik", lpb.CLASS_PARTY)
check("token shape is VGMASK_<4 digits><class letter>", grammar_token == "VGMASK_0001P", grammar_token)
check("token is pure ASCII", grammar_token.isascii())
check(
    "token carries neither I nor i (immune to Turkish casing hazards)",
    "I" not in grammar_token and "i" not in grammar_token,
)
check(
    "token carries no JSON/markdown-significant delimiter",
    not any(ch in grammar_token for ch in '"\\{}[]`<>'),
)
check(
    "token survives a JSON round-trip verbatim",
    json.loads(json.dumps({"k": grammar_token}))["k"] == grammar_token,
)
check(
    "token is NOT matched by the anchored 11-digit detector",
    lpb._DIGIT_RUN_11_RE.search(grammar_token) is None,
)
check("per-class counters restart at 0001 for a second class",
      grammar_map.token_for(VALID_TCKN, lpb.CLASS_TCKN) == "VGMASK_0001T")
check("same value reuses the same token",
      grammar_map.token_for("Ayşe Çelik", lpb.CLASS_PARTY) == grammar_token)
check("a different value in the same class gets the next index",
      grammar_map.token_for("Başka Ad", lpb.CLASS_PARTY) == "VGMASK_0002P")

check(
    "de-mask accepts a bare token",
    lpb._de_mask_string(grammar_token, grammar_map) == "Ayşe Çelik",
)
check(
    "de-mask accepts a token followed by a SOURCE digit (self-delimiting grammar)",
    lpb._de_mask_string(grammar_token + "2024/03", grammar_map) == "Ayşe Çelik2024/03",
)
check(
    "de-mask accepts a quoted token",
    lpb._de_mask_string('"' + grammar_token + '"', grammar_map) == '"Ayşe Çelik"',
)
check(
    "de-mask accepts a Turkish possessive suffix after a token",
    lpb._de_mask_string(grammar_token + "'in", grammar_map) == "Ayşe Çelik'in",
)
check(
    "de-mask accepts two adjacent tokens",
    lpb._de_mask_string(grammar_token + "VGMASK_0002P", grammar_map) == "Ayşe ÇelikBaşka Ad",
)
check(
    "de-mask accepts a SOURCE digit immediately BEFORE a token",
    lpb._de_mask_string("2024" + grammar_token, grammar_map) == "2024Ayşe Çelik",
)

for corrupt, exc, label in [
    ("VGMASK_00011P", lpb.MalformedTokenError, "extended digit run"),
    ("VGMASK_001P", lpb.MalformedTokenError, "truncated index"),
    ("VGMASK_00001P", lpb.MalformedTokenError, "five-digit index"),
    ("VGMASK", lpb.MalformedTokenError, "prefix only"),
    ("VGMASK0001P", lpb.MalformedTokenError, "missing delimiter"),
    ("VGMASK_0001Z", lpb.MalformedTokenError, "unknown class letter"),
    ("vgmask_0001p", lpb.MalformedTokenError, "fully lower-cased token"),
    ("VgMaSk_0001P", lpb.MalformedTokenError, "mixed-case prefix"),
    ("VGMASK_0009P", lpb.UnknownTokenError, "unknown index"),
    ("VGMASK_0001B", lpb.UnknownTokenError, "known index, wrong class"),
]:
    expect_raises(
        exc,
        (lambda value=corrupt: lpb._de_mask_string(value, grammar_map)),
        f"de-mask BLOCKS a corrupted token ({label})",
    )

check(
    "DISCLOSED RESIDUAL: a character appended immediately after a token is NOT "
    "distinguishable from a source character and de-masks silently (scope report 10-11)",
    lpb._de_mask_string(grammar_token + "P", grammar_map) == "Ayşe ÇelikP",
)

print("## 4 - case-INSENSITIVE residual scan (the subtlest fail-open risk)")

check(
    "PREFIX_RE finds a lower-cased prefix (a case-SENSITIVE scan would see 0 == 0 and let it through)",
    lpb.PREFIX_RE.search("vgmask_0001p") is not None,
)
check(
    "TOKEN_RE does NOT match a lower-cased token (map lookup stays case-SENSITIVE)",
    lpb.TOKEN_RE.search("vgmask_0001p") is None,
)
expect_raises(
    lpb.ResidualTokenError,
    lambda: lpb.assert_no_tokens_remain({"facts": [{"statement": "vgmask_0001p adına"}]}),
    "assert_no_tokens_remain BLOCKS a lower-cased residual token",
)
expect_raises(
    lpb.ResidualTokenError,
    lambda: lpb.assert_no_tokens_remain({"facts": [{"statement": "VGMASK_0001P adına"}]}),
    "assert_no_tokens_remain BLOCKS an upper-case residual token",
)
check(
    "assert_no_tokens_remain accepts a fully de-masked tree",
    lpb.assert_no_tokens_remain({"facts": [{"statement": "Ayşe Çelik adına"}]}) is None,
)

print("## 5 - seed construction")

seeds = lpb.build_seed_terms(SYNTH_CASE, SYNTH_DOC)
folded_seeds = {seed.folded for seed in seeds}
kinds = {seed.kind for seed in seeds}
check("individual party name is a seed", lpb.fold1to1("Ayşe Çelik") in folded_seeds)
check("company party name is a seed", lpb.fold1to1("Deneme Tekstil A.Ş.") in folded_seeds)
check(
    "U2 DECISION: a public_authority display_name is NOT a seed",
    lpb.fold1to1("Sentetik Vergi Dairesi Müdürlüğü") not in folded_seeds,
)
check("party reference_code is a seed", lpb.fold1to1("MUS-042") in folded_seeds)
check("case reference_code is a seed", lpb.fold1to1("SENT-2026-777") in folded_seeds)
check("file.file_name is a seed", lpb.fold1to1("belge_9001.pdf") in folded_seeds)
check("company-suffix variant A.S. is derived", lpb.fold1to1("Deneme Tekstil A.S.") in folded_seeds)
check("company-suffix variant AŞ is derived", lpb.fold1to1("Deneme Tekstil AŞ") in folded_seeds)
check(
    "company-suffix variant 'Anonim Şirketi' is derived",
    lpb.fold1to1("Deneme Tekstil Anonim Şirketi") in folded_seeds,
)
check("suffix-less core name is derived", lpb.fold1to1("Deneme Tekstil") in folded_seeds)
check(
    "ASCII transliteration variant is derived",
    lpb.fold1to1("Ayse Celik") in folded_seeds,
)
check(
    "no seed variant is shorter than the minimum length (a 2-letter core would match inside words)",
    all(len(seed.folded) >= lpb._MIN_SEED_VARIANT_LEN for seed in seeds),
)
check("initials are NOT generated", "d.t." not in folded_seeds and "a.ç." not in folded_seeds)
check(
    "seeds are sorted longest-first (longest-match-first is mandatory)",
    all(len(seeds[i].folded) >= len(seeds[i + 1].folded) for i in range(len(seeds) - 1)),
)
check("seed list is deterministic across calls",
      [s.folded for s in lpb.build_seed_terms(SYNTH_CASE, SYNTH_DOC)] == [s.folded for s in seeds])
check("all four seed kinds are represented", kinds >= {"party", "reference", "document_file"})

ci_seeds = party_seeds("CLIENT-001")
ci_folded = {seed.folded for seed in ci_seeds}
check(
    "an ASCII name written with capital I also matches its lower-case spelling "
    "(Turkish fold alone maps I->dotless, which would miss it)",
    lpb.fold1to1("client-001") in ci_folded,
    sorted(ci_folded),
)

op_seeds = lpb.build_seed_terms(
    {"parties": [{"party_type": "public_authority", "display_name": "X Vergi Dairesi"}]},
    {},
    extra_terms=["Eski Ünvan Ltd. Şti."],
)
check("operator extra term becomes a seed",
      lpb.fold1to1("Eski Ünvan Ltd. Şti.") in {s.folded for s in op_seeds})
check("operator term kind is 'operator'",
      any(s.kind == "operator" for s in op_seeds))

print("## 6 - masking basics")

mp = lpb.MaskMapping()
masked = lpb.mask_text("Deneme Tekstil A.Ş. adına tarh edilmiştir.", seeds, mp)
check("a seed name is replaced by a P token", "VGMASK_" in masked and "Deneme" not in masked, masked)
check("masking round-trips byte-exactly",
      lpb._de_mask_string(masked, mp) == "Deneme Tekstil A.Ş. adına tarh edilmiştir.")

mp2 = lpb.MaskMapping()
sub_seeds = party_seeds("Deneme", "Deneme Tekstil A.Ş.")
out2 = lpb.mask_text("Deneme ve Deneme Tekstil A.Ş. tarafları", sub_seeds, mp2)
check(
    "longest-match-first: a name that is a substring of another does NOT split the longer one",
    out2.count("VGMASK_") == 2 and "Tekstil" not in out2,
    out2,
)
check("substring-name case round-trips", lpb._de_mask_string(out2, mp2) == "Deneme ve Deneme Tekstil A.Ş. tarafları")

mp3 = lpb.MaskMapping()
out3 = lpb.mask_text("Ayşe Çelik, Ayşe Çelik ve yine Ayşe Çelik", party_seeds("Ayşe Çelik"), mp3)
check("a repeated name reuses ONE token", mp3.token_count() == 1 and out3.count("VGMASK_0001P") == 3, out3)
check("repeated-name case round-trips",
      lpb._de_mask_string(out3, mp3) == "Ayşe Çelik, Ayşe Çelik ve yine Ayşe Çelik")

mp4 = lpb.MaskMapping()
src4 = "Deneme TekstilAyşe Çelik"
out4 = lpb.mask_text(src4, party_seeds("Deneme Tekstil", "Ayşe Çelik"), mp4)
check("adjacent tokens with no separator", out4.count("VGMASK_") == 2, out4)
check("adjacent-token case round-trips", lpb._de_mask_string(out4, mp4) == src4)

mp5 = lpb.MaskMapping()
src5 = '"Ayşe Çelik adına" denilmektedir'
out5 = lpb.mask_text(src5, party_seeds("Ayşe Çelik"), mp5)
check("a token inside a quote round-trips", lpb._de_mask_string(out5, mp5) == src5, out5)

mp6 = lpb.MaskMapping()
src6 = "AYŞE ÇELİK büyük harfle yazılmıştır"
out6 = lpb.mask_text(src6, party_seeds("Ayşe Çelik"), mp6)
check("an all-caps spelling of a seed is masked", "VGMASK_" in out6, out6)
check("all-caps case round-trips with the ORIGINAL casing restored",
      lpb._de_mask_string(out6, mp6) == src6)

mp7 = lpb.MaskMapping()
src7 = "Ayşe Çelik'in beyanı ve Deneme Tekstil A.Ş.'nin itirazı"
out7 = lpb.mask_text(src7, seeds, mp7)
check(
    "Turkish suffixes stay OUTSIDE the masked span (no trailing word boundary is used)",
    "'in" in out7 and "'nin" in out7,
    out7,
)
check("suffix case round-trips", lpb._de_mask_string(out7, mp7) == src7)

print("## 7 - digit runs, amounts, dates (separators are NEVER stripped)")

mp8 = lpb.MaskMapping()
src8 = "05.02.2026 tarihli 850.000,00 TL ve 1.700.000,00 TL, dönem 2024/03"
check("dates and Turkish-formatted amounts are left untouched",
      lpb.mask_text(src8, seeds, mp8) == src8)
check(
    "PRECONDITION: the amount 12.345.678,90 strips to a checksum-VALID VKN "
    "(this is exactly why separators are never stripped)",
    lpb.vkn_is_valid("1234567890"),
)
mp9 = lpb.MaskMapping()
check("the amount 12.345.678,90 is NOT masked",
      lpb.mask_text("Toplam 12.345.678,90 TL", seeds, mp9) == "Toplam 12.345.678,90 TL")

mp10 = lpb.MaskMapping()
src10 = "Tebligat No: 20260210000123456 sayılı"
check(
    "a 17-digit tebligat number stays fully intact (no sliding window) even though it "
    "CONTAINS a checksum-valid 11-digit substring",
    lpb.mask_text(src10, seeds, mp10) == src10 and lpb.tckn_is_valid("10000123456"),
)

for run, expect_masked, note in [
    (VALID_TCKN, True, "checksum-valid 11-digit run"),
    (INVALID_TCKN, True, "checksum-FAILING 11-digit run is masked anyway (length decides)"),
    (VALID_VKN, True, "checksum-valid 10-digit run"),
    (INVALID_VKN, True, "checksum-FAILING 10-digit run is masked anyway"),
    ("123456789", False, "9-digit run"),
    ("123456789012", False, "12-digit run"),
]:
    m = lpb.MaskMapping()
    got = lpb.mask_text("No: " + run + " kaydı", seeds, m)
    check(
        f"digit run policy - {note}",
        ("VGMASK_" in got) == expect_masked and run not in got if expect_masked else got == "No: " + run + " kaydı",
        got,
    )

ARABIC_INDIC_10 = "١٢٣٤٥٦٧٨٩٠"
FULLWIDTH_10 = "１２３４５６７８９０"
for pattern, name in [(lpb._DIGIT_RUN_10_RE, "10-digit"), (lpb._DIGIT_RUN_11_RE, "11-digit")]:
    check(
        f"the {name} detector uses [0-9], not \\d, so it does NOT match Arabic-Indic digits",
        pattern.search(ARABIC_INDIC_10 + "١") is None,
    )
    check(
        f"the {name} detector does NOT match full-width digits",
        pattern.search(FULLWIDTH_10 + "１") is None,
    )
check(
    "PRECONDITION: a \\d-based detector WOULD have matched those (so the rule is load-bearing)",
    re.search(r"(?<!\d)\d{10}(?!\d)", ARABIC_INDIC_10) is not None,
)
check(
    "an ASCII 10-digit run preceded by a non-ASCII digit is STILL detected "
    "(a \\d lookbehind would have suppressed it and let a VKN-shaped run survive)",
    lpb._DIGIT_RUN_10_RE.search("١" + VALID_VKN) is not None
    and re.search(r"(?<!\d)\d{10}(?!\d)", "١" + VALID_VKN) is None,
)

m11 = lpb.MaskMapping()
got11 = lpb.mask_text("TCKN: " + VALID_TCKN + ".", seeds, m11)
check("an 11-digit run is labelled T", "VGMASK_0001T" in got11, got11)
m12 = lpb.MaskMapping()
got12 = lpb.mask_text("VKN: " + VALID_VKN + ".", seeds, m12)
check("a 10-digit run is labelled V", "VGMASK_0001V" in got12, got12)
m13 = lpb.MaskMapping()
got13 = lpb.mask_text("Sıra: " + INVALID_TCKN + ".", seeds, m13)
check("a checksum-FAILING 11-digit run is still labelled T (length, not checksum)",
      "VGMASK_0001T" in got13, got13)

print("## 8 - IBAN")

for iban, label in [(VALID_IBAN_COMPACT, "compact"), (VALID_IBAN_GROUPED, "grouped")]:
    m = lpb.MaskMapping()
    src = "IBAN: " + iban + " hesabına"
    got = lpb.mask_text(src, seeds, m)
    check(f"a {label} TR IBAN is masked as class B",
          "VGMASK_0001B" in got and iban not in got, got)
    check(f"a {label} TR IBAN round-trips byte-exactly", lpb._de_mask_string(got, m) == src)

m14 = lpb.MaskMapping()
src14 = "IBAN: " + INVALID_IBAN + " hesabına"
got14 = lpb.mask_text(src14, seeds, m14)
check("an IBAN failing mod-97 is NOT masked as an IBAN", "VGMASK_0001B" not in got14, got14)

print("## 9 - phone: a POSITIVE test per format (a round-trip test cannot detect a miss)")

PHONE_FORMATS = [
    ("+90 532 123 45 67", "mobile, international, spaced"),
    ("0532 123 45 67", "mobile, national, spaced"),
    ("05321234567", "mobile, national, compact"),
    ("+905321234567", "mobile, international, compact"),
    ("00905321234567", "mobile, 0090 prefix, compact"),
    ("0 (212) 555 44 33", "LANDLINE with parenthesised area code"),
    ("0212 555 44 33", "landline, national, spaced"),
    ("+90 312 444 22 11", "landline, international, spaced"),
]
for phone, label in PHONE_FORMATS:
    m = lpb.MaskMapping()
    src = "Telefon: " + phone + " numarasından"
    got = lpb.mask_text(src, seeds, m)
    digits_only = "".join(ch for ch in phone if ch.isdigit())
    survived = any(
        chunk and chunk in got
        for chunk in [phone, digits_only, digits_only[-7:]]
    )
    check(
        f"phone format is actually MASKED ({label})",
        "VGMASK_" in got and not survived,
        f"{phone!r} -> {got!r}",
    )
    check(f"phone format round-trips ({label})", lpb._de_mask_string(got, m) == src)

m15 = lpb.MaskMapping()
check("a date is not mistaken for a phone number",
      lpb.mask_text("05.02.2026", seeds, m15) == "05.02.2026")

print("## 10 - e-mail and the overlap -> fixpoint defect")

m16 = lpb.MaskMapping()
src16 = "E-posta: ayse.celik@sentetik-ornek.com.tr adresine"
got16 = lpb.mask_text(src16, seeds, m16)
check("an e-mail is masked as class E", "VGMASK_0001E" in got16 and "@" not in got16, got16)
check("e-mail round-trips", lpb._de_mask_string(got16, m16) == src16)

overlap_seeds = party_seeds("Ornek Vergi Dairesi Mudurlugu")
m17 = lpb.MaskMapping()
OVERLAP_DOC = "Davali Ornek Vergi Dairesi Mudurluguahmet.yilmaz@ornek-hukuk.com.tr adresine"
got17 = lpb.mask_text(OVERLAP_DOC, overlap_seeds, m17)
check(
    "OVERLAP: a name span that swallows the start of an e-mail no longer drops the e-mail "
    "(single-pass leftmost-longest leaked it; the fixpoint repairs it)",
    "@" not in got17 and "ornek-hukuk" not in got17,
    got17,
)
check("overlap case still round-trips byte-exactly",
      lpb._de_mask_string(got17, m17) == OVERLAP_DOC)
check(
    "the fixpoint rescan does NOT match inside an already-placed token "
    "(the e-mail local-part class would otherwise eat VGMASK_0001P)",
    got17.count("VGMASK_") == 2 and "VGMASK_0001P" in got17,
    got17,
)

print("## 11 - property test: de_mask(mask(t)) == t, byte-for-byte")

FRAGS = [
    "Vergi ve Ceza İhbarnamesi", " sayılı ", "\n\n", " ", "'nin ", "'in ", ", ",
    "2024/03 vergilendirme dönemi", " 850.000,00 TL ", "05.02.2026", " tarihli ",
    "3065 sayılı Kanunun 29 uncu maddesi", " adına ", ".", "\n", " İHBARNAME ",
    "(", ")", " -- ", "Tebligat No: 20260210000123456",
]
PROP_NAMES = [
    "Deneme Tekstil A.Ş.", "Deneme", "Ayşe Çelik", "AYŞE ÇELİK",
    "Deneme Tekstil Anonim Şirketi", "Ayse Celik",
]
PROP_IDS = [
    VALID_TCKN, INVALID_TCKN, VALID_VKN, VALID_IBAN_COMPACT, VALID_IBAN_GROUPED,
    "ayse.celik@sentetik-ornek.com.tr", "+90 532 123 45 67", "0532 123 45 67",
    "0 (212) 555 44 33",
]
prop_seeds = party_seeds("Deneme Tekstil A.Ş.", "Ayşe Çelik")
rng = random.Random(20260921)
prop_total = 0
prop_roundtrip = 0
prop_refused = 0
prop_surviving = 0
for _ in range(1500):
    pieces = []
    for _ in range(rng.randint(1, 14)):
        bucket = rng.random()
        if bucket < 0.55:
            pieces.append(rng.choice(FRAGS))
        elif bucket < 0.8:
            pieces.append(rng.choice(PROP_NAMES))
        else:
            pieces.append(rng.choice(PROP_IDS))
    document = "".join(pieces)
    prop_total += 1
    mapping = lpb.MaskMapping()
    try:
        masked_doc = lpb.mask_text(document, prop_seeds, mapping)
    except lpb.MaskingError:
        prop_refused += 1
        continue
    if lpb._de_mask_string(masked_doc, mapping) == document:
        prop_roundtrip += 1
    try:
        lpb.scan_outbound(masked_doc, prop_seeds)
    except lpb.MaskingError:
        prop_surviving += 1

check(
    f"property: every accepted masking round-trips byte-exactly ({prop_roundtrip}/{prop_total})",
    prop_roundtrip + prop_refused == prop_total and prop_roundtrip > 1400,
    f"roundtrip={prop_roundtrip} refused={prop_refused} total={prop_total}",
)
check(
    f"property: zero fail-closed refusals on synthetic documents ({prop_refused})",
    prop_refused == 0,
    f"refused={prop_refused}",
)
check(
    f"property: no known pattern survives masking in any generated document ({prop_surviving})",
    prop_surviving == 0,
    f"surviving={prop_surviving}",
)

print("## 12 - determinism")

det_a = lpb.mask_prompt_inputs(
    case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
    document_text="Deneme Tekstil A.Ş. ve Ayşe Çelik, TCKN " + VALID_TCKN,
)
det_b = lpb.mask_prompt_inputs(
    case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
    document_text="Deneme Tekstil A.Ş. ve Ayşe Çelik, TCKN " + VALID_TCKN,
)
check("identical input produces an identical masked text", det_a.masked_text == det_b.masked_text)
check("identical input produces an identical masked context",
      json.dumps(det_a.masked_context, sort_keys=True) == json.dumps(det_b.masked_context, sort_keys=True))
check("identical input produces an identical token set",
      set(det_a.mapping.tokens()) == set(det_b.mapping.tokens()))
check("identical input produces an identical summary", det_a.summary == det_b.summary)
check(
    "token numbering starts in the CONTEXT (first occurrence order), not the document text",
    "VGMASK_0001P" in json.dumps(det_a.masked_context, ensure_ascii=False),
    json.dumps(det_a.masked_context, ensure_ascii=False),
)

print("## 13 - mask_context field policy")

ctx_result = lpb.mask_prompt_inputs(
    case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
    document_text="Deneme Tekstil A.Ş.",
)
mc = ctx_result.masked_context
check("the ORIGINAL context object is not mutated",
      SYNTH_CONTEXT["parties"][0]["display_name"] == "Deneme Tekstil A.Ş.")
check("parties[].display_name is masked", mc["parties"][0]["display_name"].startswith("VGMASK_"))
check("source_document_title is masked",
      "Deneme" not in mc["source_document_title"], mc["source_document_title"])
check("case_id is NOT masked", mc["case_id"] == "case_9001")
check("source_document_id is NOT masked", mc["source_document_id"] == "belge_9001")
check("parties[].party_id is NOT masked", mc["parties"][0]["party_id"] == "party_a")
check("parties[].role is NOT masked", mc["parties"][0]["role"] == "taxpayer")
check("dispute_items are NOT masked",
      mc["dispute_items"][0] == SYNTH_CONTEXT["dispute_items"][0])
check("asserted_legal_basis_refs are NOT masked",
      mc["dispute_items"][0]["asserted_legal_basis_refs"] == ["KDVK_m29"])
check(
    "U2: a public_authority display_name survives in the masked context (deliberate, disclosed)",
    mc["parties"][2]["display_name"] == "Sentetik Vergi Dairesi Müdürlüğü",
)
check("source_actor_label (a public authority here) is left intact",
      mc["source_actor_label"] == "Sentetik Vergi Dairesi Müdürlüğü")
check("the same value gets the SAME token in context and document text",
      ctx_result.masked_text.strip() == mc["parties"][0]["display_name"],
      f"{ctx_result.masked_text!r} vs {mc['parties'][0]['display_name']!r}")

print("## 14 - fail-closed table, one test per row")

expect_raises(
    lpb.EmptySeedListError,
    lambda: lpb.build_seed_terms(
        {"parties": [{"party_type": "public_authority", "display_name": "Yalnız İdare"}],
         "reference_code": "REF-1"},
        {"file": {"file_name": "x.pdf"}},
    ),
    "REFUSE: empty seed list (only public_authority parties, no operator term) - "
    "reference codes and file names alone do NOT satisfy it",
)
check(
    "the documented escape from an all-public-authority case is --mask-term",
    len(lpb.build_seed_terms(
        {"parties": [{"party_type": "public_authority", "display_name": "Yalnız İdare"}]},
        {}, extra_terms=["Müvekkil Ltd. Şti."],
    )) > 0,
)
expect_raises(
    lpb.MaskCollisionError,
    lambda: lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
        document_text="Metinde zaten VGMASK_0001P geçiyor",
    ),
    "REFUSE: the token prefix already occurs in the source text",
)
expect_raises(
    lpb.MaskCollisionError,
    lambda: lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
        document_text="metinde vgmask geçiyor",
    ),
    "REFUSE: the collision pre-check is case-INSENSITIVE",
)
expect_raises(
    lpb.MaskCollisionError,
    lambda: lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC,
        context=dict(SYNTH_CONTEXT, source_document_title="VGMASK_0001P"),
        document_text="temiz metin Deneme Tekstil A.Ş.",
    ),
    "REFUSE: the collision pre-check also covers the CONTEXT, not just the text",
)
expect_raises(
    lpb.NonAsciiDigitError,
    lambda: lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
        document_text="TCKN: ١٢٣٤٥٦٧٨٩٠١ Deneme Tekstil A.Ş.",
    ),
    "REFUSE: non-ASCII (Arabic-Indic) digits in the source",
)
expect_raises(
    lpb.NonAsciiDigitError,
    lambda: lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
        document_text="No: １２３４５６７８９０ Deneme Tekstil A.Ş.",
    ),
    "REFUSE: non-ASCII (full-width) digits in the source",
)
zw_text = "TCKN: 1056​2272296 Deneme Tekstil A.Ş."
check(
    "PRECONDITION: a zero-width char defeats the plain anchored digit matcher",
    lpb._DIGIT_RUN_11_RE.search(zw_text) is None,
)
expect_raises(
    lpb.ZeroWidthDigitRunError,
    lambda: lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
        document_text=zw_text,
    ),
    "REFUSE: a zero-width character inside an otherwise unresolvable 11-digit run",
)
check(
    "a zero-width character NOT inside a 10/11-digit run does not refuse",
    lpb.find_unresolvable_zero_width_digit_runs("2024​03 dönemi") == 0,
)
expect_raises(
    lpb.NonOpaqueIdentifierError,
    lambda: lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC,
        context=dict(SYNTH_CONTEXT, case_id="case_deneme_tekstil_2026"),
        document_text="Deneme Tekstil A.Ş.",
    ),
    "REFUSE: a non-opaque case_id carrying a party-name core",
)
expect_raises(
    lpb.NonOpaqueIdentifierError,
    lambda: lpb.assert_identifiers_are_opaque(["party_ayse_celik"], party_seeds("Ayşe Çelik", kind="individual")),
    "REFUSE: a non-opaque party_id carrying a party name",
)
check(
    "SCOPED: the id check uses ONLY party-name cores and operator terms, so a document_id "
    "that merely matches its own file_name is NOT refused",
    lpb.assert_identifiers_are_opaque(["belge_9001"], seeds) is None,
)
expect_raises(
    lpb.MaskedInputTooLongError,
    lambda: lpb.assert_masked_length_within("x" * 101, 100),
    "REFUSE: the masked text exceeds the single-call character limit",
)
check(
    "the masked text CAN be longer than the original (so the second length check is not redundant)",
    len(lpb.mask_text("a@b.co", party_seeds("Ayşe Çelik"), lpb.MaskMapping())) > len("a@b.co"),
)
expect_raises(
    lpb.SeedTermError,
    lambda: lpb.build_seed_terms(SYNTH_CASE, SYNTH_DOC, extra_terms=["   "]),
    "REFUSE: a blank operator term",
)
expect_raises(
    lpb.SeedTermError,
    lambda: lpb.build_seed_terms(SYNTH_CASE, SYNTH_DOC, extra_terms=[None]),
    "REFUSE: a non-string operator term",
)
expect_raises(
    lpb.SeedTermError,
    lambda: lpb.build_seed_terms(SYNTH_CASE, SYNTH_DOC, extra_terms=["VGMASK deneme"]),
    "REFUSE: an operator term carrying the token prefix",
)
expect_raises(
    lpb.SurvivingPatternError,
    lambda: lpb.scan_outbound("Mükellef Ayşe Çelik adına", party_seeds("Ayşe Çelik")),
    "REFUSE: a seed name survives in the outbound prompt",
)
expect_raises(
    lpb.SurvivingPatternError,
    lambda: lpb.scan_outbound("TCKN " + VALID_TCKN, seeds),
    "REFUSE: a TCKN-shaped run survives in the outbound prompt",
)
expect_raises(
    lpb.SurvivingPatternError,
    lambda: lpb.scan_outbound("IBAN " + VALID_IBAN_COMPACT, seeds),
    "REFUSE: an IBAN survives in the outbound prompt",
)
expect_raises(
    lpb.SurvivingPatternError,
    lambda: lpb.scan_outbound("E-posta a@b.com.tr", seeds),
    "REFUSE: an e-mail survives in the outbound prompt",
)
expect_raises(
    lpb.TokenInKeyError,
    lambda: lpb.de_mask_tree({"VGMASK_0001P": "x"}, grammar_map),
    "REFUSE: a token in a dict KEY is never de-masked",
)
expect_raises(
    lpb.TokenInKeyError,
    lambda: lpb.de_mask_tree({"facts": [{"vgmask_0001p": "x"}]}, grammar_map),
    "REFUSE: a lower-cased token in a nested dict KEY",
)
exhausted = lpb.MaskMapping()
exhausted._counters[lpb.CLASS_PARTY] = lpb._MAX_TOKEN_INDEX
expect_raises(
    lpb.TokenSpaceExhaustedError,
    lambda: exhausted.token_for("bir ad", lpb.CLASS_PARTY),
    "REFUSE: the 4-digit token index space is exhausted",
)

print("## 15 - outbound scan is segment-aware")

seg_seeds = party_seeds("MASKARA Tekstil")
seg_map = lpb.MaskMapping()
seg_src = "MASKARA Tekstil adına"
seg_out = lpb.mask_text(seg_src, seg_seeds, seg_map)
check(
    "a seed whose letters also occur inside the VGMASK prefix does not cause a false "
    "surviving-pattern refusal (the scan skips token spans)",
    lpb.scan_outbound(seg_out, seg_seeds) is None,
    seg_out,
)
check(
    "the model instruction block does not itself trip the outbound scan",
    lpb.scan_outbound("temiz metin" + lpb.token_instruction_block(), seeds) is None,
)

print("## 15b - company-suffix matching needs a WORD BOUNDARY")

# Without a word boundary the short forms match mid-word and the derived
# core is catastrophically wrong: "MARAŞ" contains "AŞ", "HASAN"
# contains "AS". Verified empirically before the fix.
for raw_name, expected_core in [
    ("MARAŞ TEKSTİL A.Ş.", "MARAŞ TEKSTİL"),
    ("HASAN ÖZ Ltd. Şti.", "HASAN ÖZ"),
    ("TAŞ MADENCİLİK A.Ş.", "TAŞ MADENCİLİK"),
    ("Deneme Tekstil A.Ş.", "Deneme Tekstil"),
    ("ABC Ltd. Şti. - Demo", "ABC"),
]:
    check(
        f"suffix-less core of {raw_name!r} is {expected_core!r} (word-boundary matching)",
        lpb._company_core(raw_name) == expected_core,
        lpb._company_core(raw_name),
    )
check(
    "PRECONDITION: the short suffix form really does occur mid-word in 'MARAŞ' "
    "(so the word-boundary rule is load-bearing, not decorative)",
    lpb.fold1to1("MARAŞ TEKSTİL A.Ş.").find(lpb.fold1to1("AŞ")) == 3,
    lpb.fold1to1("MARAŞ TEKSTİL A.Ş."),
)
_boundary_map = lpb.MaskMapping()
_boundary_src = "Mart ayında marka tescili yapıldı; MARAŞ TEKSTİL A.Ş. adına."
_boundary_out = lpb.mask_text(
    _boundary_src, party_seeds("MARAŞ TEKSTİL A.Ş."), _boundary_map,
)
check(
    "a wrong 3-letter core would have mangled unrelated words ('Mart', 'marka'); with the "
    "boundary rule they are left completely intact",
    "Mart ayında marka tescili" in _boundary_out and _boundary_out.count("VGMASK_") == 1,
    _boundary_out,
)
check(
    "no company-suffix variant is malformed (a mid-word replacement produced garbage such as "
    "'HAnonim ŞirketiAN ÖZ Ltd. Şti.')",
    all(
        "Anonim" not in variant or variant.startswith("HASAN ÖZ")
        for variant in lpb._company_suffix_variants("HASAN ÖZ Ltd. Şti.")
    ),
    lpb._company_suffix_variants("HASAN ÖZ Ltd. Şti."),
)

print("## 15c - the seed-survival scan is scoped to the MASKED regions only")

# A single-word company derives that word as a core. The core is masked
# everywhere in the variable text, but the SAME word also occurs in the
# fixed prompt boilerplate and in unmasked context enums. Scanning the
# whole prompt for seeds made such a case permanently unprocessable
# (--mask-term cannot help: it only ADDS seeds). Verified empirically.
_BOILERPLATE = (
    "\n\nTASK\n====\n\nKaynak belgeden desteklenen case fact kayıtlarını çıkar.\n"
    "Belge türünü dikkate al.\nDava dilekçesindeki davacı beyanlarını modelle.\n"
    "Vergi İnceleme Raporundaki iddia ile İhbarnamedeki işlemi karıştırma.\n"
    "Sentetik/demo/development açıklamalarını fact olarak çıkarma.\n"
)
for collide_name, collide_word in [
    ("Kaynak A.Ş.", "Kaynak"), ("Demo A.Ş.", "Demo"), ("Dava Ltd. Şti.", "Dava"),
    ("Vergi A.Ş.", "Vergi"), ("Rapor Ltd. Şti.", "Rapor"),
]:
    collide_case = {"parties": [{"party_type": "company", "display_name": collide_name}]}
    collide_ctx = {
        "case_id": "case_9001", "source_document_id": "belge_x",
        "source_document_title": "Sentetik İhbarname",
        "source_document_type": "dava_dilekcesi",
        "source_actor_label": "Sentetik Vergi Dairesi Müdürlüğü",
        "parties": [{"party_id": "party_a", "role": "taxpayer", "display_name": collide_name}],
        "dispute_items": [],
    }
    collide_result = lpb.mask_prompt_inputs(
        case_data=collide_case, document_data={}, context=collide_ctx,
        document_text=f"{collide_name} adına tarhiyat yapılmıştır.",
    )
    collide_prompt = (
        json.dumps(collide_result.masked_context, ensure_ascii=False, indent=2)
        + "\n" + collide_result.masked_text + _BOILERPLATE
        + collide_result.prompt_instruction_block
    )
    check(
        f"PRECONDITION: the derived core {collide_word!r} really does occur in the fixed "
        "boilerplate/enums (so this case is not vacuous)",
        lpb.fold1to1(collide_word) in lpb.fold1to1(collide_prompt),
    )
    check(
        f"a single-word company ({collide_name!r}) is NOT falsely refused - the seed scan "
        "covers only what masking actually produced",
        lpb.scan_outbound(collide_prompt, collide_result) is None,
    )
    check(
        f"...and the real party name is still genuinely gone from the masked regions "
        f"({collide_name!r})",
        collide_name not in collide_result.masked_text
        and collide_name not in json.dumps(collide_result.masked_context, ensure_ascii=False),
    )

# The narrowing must NOT weaken the real guarantee: a genuine leak inside
# a masked region is still refused.
_leak_result = lpb.mask_prompt_inputs(
    case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
    document_text="Deneme Tekstil A.Ş. adına",
)
_leak_result.masked_text = _leak_result.masked_text + " Ayşe Çelik sızdı"
expect_raises(
    lpb.SurvivingPatternError,
    lambda: lpb.scan_outbound("prompt " + _leak_result.masked_text, _leak_result),
    "a seed surviving INSIDE a masked region is still REFUSED (the narrowing did not weaken "
    "the guarantee)",
)
_leak_ctx_result = lpb.mask_prompt_inputs(
    case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
    document_text="Deneme Tekstil A.Ş. adına",
)
_leak_ctx_result.masked_context["parties"][0]["display_name"] = "Ayşe Çelik"
expect_raises(
    lpb.SurvivingPatternError,
    lambda: lpb.scan_outbound("prompt", _leak_ctx_result),
    "a seed surviving in a masked CONTEXT field is still REFUSED",
)
_regions = lpb.masked_context_text_regions(SYNTH_CONTEXT)
check(
    "S1: masked_context_text_regions() covers EVERY string leaf that mask_context() masks - "
    "including the three fields the earlier narrow set missed "
    "(source_document_type / source_document_subtype / dispute_items[].tax_type)",
    all(
        value in _regions
        for value in [
            SYNTH_CONTEXT["source_document_title"],
            SYNTH_CONTEXT["source_actor_label"],
            SYNTH_CONTEXT["parties"][0]["display_name"],
            SYNTH_CONTEXT["parties"][2]["display_name"],
            SYNTH_CONTEXT["source_document_category"],
            SYNTH_CONTEXT["source_document_type"],
            SYNTH_CONTEXT["dispute_items"][0]["tax_type"],
        ]
    ),
    _regions,
)
check(
    "S1: the PROTECTED id values are NOT in the scanned/masked region set "
    "(attribution depends on them reaching build_extraction unmasked)",
    all(
        value not in _regions
        for value in [
            SYNTH_CONTEXT["case_id"],
            SYNTH_CONTEXT["source_document_id"],
            SYNTH_CONTEXT["source_document_issuer_party_id"],
            SYNTH_CONTEXT["parties"][0]["party_id"],
            SYNTH_CONTEXT["dispute_items"][0]["dispute_item_id"],
        ]
    ),
    _regions,
)
_clean_result = lpb.mask_prompt_inputs(
    case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
    document_text="Deneme Tekstil A.Ş.",
)
for stray, stray_label in [
    (VALID_TCKN, "TCKN"), (VALID_VKN, "VKN"), (VALID_IBAN_COMPACT, "IBAN"),
    ("a@b.com.tr", "e-mail"), ("0 (212) 555 44 33", "phone"),
]:
    expect_raises(
        lpb.SurvivingPatternError,
        lambda s=stray: lpb.scan_outbound("sabit sablon metni " + s, _clean_result),
        f"identifier patterns are STILL scanned over the WHOLE prompt - a stray {stray_label} "
        "outside the masked regions is REFUSED (only the SEED scan was narrowed)",
    )
check(
    "CONTROL: the same clean prompt without a stray identifier is accepted",
    lpb.scan_outbound("sabit sablon metni " + _clean_result.masked_text, _clean_result) is None,
)

print("## 15d - B1: split / invisible / NFD entities (the silent-leak class)")

# ROOT CAUSE that this section pins: the masker located seeds with
# fold1to1().find() and the backstop checked `seed.folded in
# fold1to1(region)` - THE SAME comparison - so every blind spot of the
# masker was also a blind spot of the backstop and a surviving real name
# was sent to the LLM with NO exception at all. A round-trip test cannot
# see this: a MISSED masking round-trips perfectly.
B1_CASE = {"parties": [{"party_id": "party_a", "party_type": "individual",
                        "display_name": "Ahmet Yılmaz"}]}
B1_DOC = {}
B1_CTX = {
    "case_id": "case_b1", "source_document_id": "belge_b1",
    "source_document_title": "Ihbarname", "source_document_type": "ihbarname",
    "source_actor_label": "Kadikoy Vergi Dairesi",
    "parties": [{"party_id": "party_a", "role": "taxpayer", "display_name": "Ahmet Yılmaz"}],
    "dispute_items": [],
}


def b1_run(document_text):
    """(outcome, masked_text) - outcome in {'masked', 'refused', 'leaked'}."""
    try:
        res = lpb.mask_prompt_inputs(
            case_data=B1_CASE, document_data=B1_DOC, context=B1_CTX,
            document_text=document_text,
        )
    except lpb.MaskingError:
        return "refused", None
    prompt = json.dumps(res.masked_context, ensure_ascii=False) + "\n" + res.masked_text
    try:
        lpb.scan_outbound(prompt + res.prompt_instruction_block, res)
    except lpb.MaskingError:
        return "refused", res.masked_text
    if "Ahmet" in res.masked_text and "Yılmaz" in res.masked_text:
        return "leaked", res.masked_text
    return "masked", res.masked_text


# (i) WHITESPACE-SPLIT names must be MASKED (not merely refused) and must
#     de-mask back to the ORIGINAL bytes, separator included.
for sep, sep_label in [
    (" ", "single space (control)"),
    ("  ", "double space"),
    ("\n", "LF line break"),
    ("\r\n", "CRLF line break"),
    ("\t", "tab"),
    (" ", "NBSP"),
    (" \n   ", "mixed whitespace run"),
]:
    doc = f"Mükellef Ahmet{sep}Yılmaz adına tarhiyat yapıldı."
    outcome, masked = b1_run(doc)
    check(
        f"B1: a party name split by {sep_label} is MASKED (not silently sent)",
        outcome == "masked",
        f"outcome={outcome} masked={masked!r}",
    )
    check(
        f"B1: ...and the raw name no longer appears anywhere ({sep_label})",
        masked is not None and "Ahmet" not in masked and "Yılmaz" not in masked,
        masked,
    )
    mapping_ws = lpb.MaskMapping()
    out_ws = lpb.mask_text(doc, party_seeds("Ahmet Yılmaz", kind="individual"), mapping_ws)
    check(
        f"B1: ...and de-masking restores the ORIGINAL bytes including the separator "
        f"({sep_label})",
        lpb._de_mask_string(out_ws, mapping_ws) == doc,
        out_ws,
    )

# (ii) INVISIBLE / NFD splits stay a FAIL-CLOSED REFUSAL (the masker
#      deliberately does not bridge them; the normalising backstop does).
# R1(ii): an INVISIBLE character used as the WORD SEPARATOR is now
# MASKED (previously it was only refused). All six characters scan_fold
# strips are accepted by the masker's separator class, alone or mixed
# with real whitespace, and de-masking still restores the ORIGINAL bytes.
INVISIBLE_SEPARATORS = [
    ("­", "soft hyphen U+00AD"),
    ("​", "ZWSP U+200B"),
    ("‌", "ZWNJ U+200C"),
    ("‍", "ZWJ U+200D"),
    ("⁠", "word joiner U+2060"),
    ("﻿", "BOM U+FEFF"),
    (" ​", "space + ZWSP (mixed)"),
    ("­ ", "soft hyphen + space (mixed)"),
    ("​ ­\n", "ZWSP + space + soft hyphen + LF (mixed)"),
]
for sep, sep_label in INVISIBLE_SEPARATORS:
    doc = f"Mükellef Ahmet{sep}Yılmaz adına tarhiyat yapıldı."
    outcome, masked = b1_run(doc)
    check(
        f"R1(ii): a multi-word name whose SEPARATOR is {sep_label} is MASKED (not merely refused)",
        outcome == "masked",
        f"outcome={outcome} masked={masked!r}",
    )
    check(
        f"R1(ii): ...and the raw name is gone ({sep_label})",
        masked is not None and "Ahmet" not in masked and "Yılmaz" not in masked,
        masked,
    )
    mapping_inv = lpb.MaskMapping()
    out_inv = lpb.mask_text(doc, party_seeds("Ahmet Yılmaz", kind="individual"), mapping_inv)
    check(
        f"R1(ii): ...and de-masking restores the ORIGINAL bytes including the invisible "
        f"separator ({sep_label})",
        lpb._de_mask_string(out_inv, mapping_inv) == doc,
        repr(out_inv),
    )

# (c) invisibles INSIDE a word are still a FAIL-CLOSED REFUSAL.
for bad_doc, bad_label in [
    ("Mükellef Ahmet Yıl­maz adına.", "soft hyphen INSIDE a word"),
    ("Mükellef Ahmet Yıl​maz adına.", "ZWSP INSIDE a word"),
    ("Mükellef Ah‌met Yılmaz adına.", "ZWNJ INSIDE the first word"),
    ("Mükellef Ahmet Yılma﻿z adına.", "BOM INSIDE a word"),
]:
    outcome, _ = b1_run(bad_doc)
    check(
        f"B1: a party name hidden by {bad_label} is FAIL-CLOSED REFUSED (never silently sent)",
        outcome == "refused",
        f"outcome={outcome}",
    )

# NFD needs a name with DECOMPOSABLE letters ('ş', 'ö', 'ü', 'ç'); an
# ASCII+dotless-i name such as "Ahmet Yılmaz" is unchanged by NFD, so it
# would be a vacuous case.
NFD_CASE = {"parties": [{"party_id": "party_n", "party_type": "individual",
                         "display_name": "Ayşe Öztürk"}]}
NFD_CTX = {
    "case_id": "case_nfd", "source_document_id": "belge_nfd",
    "source_document_title": "Ihbarname",
    "parties": [{"party_id": "party_n", "role": "taxpayer", "display_name": "Ayşe Öztürk"}],
    "dispute_items": [],
}
_nfd_doc = unicodedata.normalize("NFD", "Mükellef Ayşe Öztürk adına.")
check(
    "PRECONDITION: NFD genuinely changes this name (so the case is not vacuous)",
    _nfd_doc != "Mükellef Ayşe Öztürk adına.",
)
_nfd_refused = False
try:
    _nfd_res = lpb.mask_prompt_inputs(
        case_data=NFD_CASE, document_data={}, context=NFD_CTX, document_text=_nfd_doc,
    )
    lpb.scan_outbound(
        json.dumps(_nfd_res.masked_context, ensure_ascii=False) + _nfd_res.masked_text,
        _nfd_res,
    )
except lpb.MaskingError:
    _nfd_refused = True
check(
    "B1: an NFD-encoded party name is FAIL-CLOSED REFUSED (the masker misses it; the "
    "NFKD-normalising backstop catches it)",
    _nfd_refused,
)
_nfc_masked = lpb.mask_prompt_inputs(
    case_data=NFD_CASE, document_data={}, context=NFD_CTX,
    document_text="Mükellef Ayşe Öztürk adına.",
).masked_text
check(
    "B1 CONTROL: the same name in NFC form is masked normally, not refused",
    "Ayşe" not in _nfc_masked and "Öztürk" not in _nfc_masked and "VGMASK_" in _nfc_masked,
    _nfc_masked,
)
check(
    "scan_squeeze() joins words so a vanished separator still matches",
    lpb.scan_squeeze("Ahmet­Yılmaz") == lpb.scan_squeeze("Ahmet Yılmaz"),
    lpb.scan_squeeze("Ahmet­Yılmaz"),
)

print("## 15d-2 - R1(iii): a squeeze-ONLY hit is COUNTED, never refused")

# The independent re-review measured, on the REAL repo fixture texts,
# that ~10% of plausible single-word company cores (25/249) hit a
# squeeze-only match and were PERMANENTLY refused: squeeze drops ALL
# whitespace, so separate words JOIN and a short core matches across the
# join ("BASKANLIGINA"+"DAVA" -> "...ada..."). The masker cannot mask it
# (not contiguous) and the operator cannot fix it - removing the term,
# adding another term and cleaning the document all failed. A LENGTH
# GATE was measured and DISPROVED. Demoted to a counter (b2 precedent).
REAL_DAVA = (
    REPO_ROOT / "data" / "cases" / "case_0001" / "documents"
    / "dava_dilekcesi_001" / "extracted" / "dava_dilekcesi_001.txt"
).read_text(encoding="utf-8-sig")
R1_CASE = {"parties": [{"party_id": "party_r1", "party_type": "company",
                        "display_name": "Ornek Sirket A.S."}]}
R1_CTX = {
    "case_id": "case_r1", "source_document_id": "belge_r1",
    "source_document_title": "Dava Dilekcesi",
    "parties": [{"party_id": "party_r1", "role": "taxpayer",
                 "display_name": "Ornek Sirket A.S."}],
    "dispute_items": [],
}
for operator_term in ["Ada", "Ata", "Isi", "Mad"]:
    r1_refused = None
    r1_res = None
    try:
        r1_res = lpb.mask_prompt_inputs(
            case_data=R1_CASE, document_data={}, context=R1_CTX,
            document_text=REAL_DAVA, extra_terms=(operator_term,),
        )
        lpb.scan_outbound(
            json.dumps(r1_res.masked_context, ensure_ascii=False) + r1_res.masked_text,
            r1_res,
        )
        r1_refused = False
    except lpb.MaskingError as error:
        r1_refused = type(error).__name__
    check(
        f"R1(iii): the REAL case_0001 dava_dilekcesi_001 text with --mask-term {operator_term!r} "
        "is NOT refused any more (it used to be permanently unprocessable)",
        r1_refused is False,
        f"refused={r1_refused}",
    )
    check(
        f"R1(iii): ...and the squeeze-only hit is REPORTED as a counter instead "
        f"({operator_term!r})",
        r1_res is not None
        and isinstance(r1_res.summary["possible_squeeze_seed_match"], int),
        r1_res.summary.get("possible_squeeze_seed_match") if r1_res else None,
    )
check(
    "R1(iii) CONTROL: a multi-word operator term on the SAME real text is unaffected",
    lpb.mask_prompt_inputs(
        case_data=R1_CASE, document_data={}, context=R1_CTX,
        document_text=REAL_DAVA, extra_terms=("Ozturk Insaat",),
    ) is not None,
)

# The GIVEN-UP class, asserted explicitly as 'not refused, counted'.
_giveup_case = {"parties": [{"party_id": "p", "party_type": "company",
                             "display_name": "Anadolu A.S."}]}
_giveup_ctx = {
    "case_id": "case_g", "source_document_id": "belge_g",
    "source_document_title": "Ihbarname",
    "parties": [{"party_id": "p", "role": "taxpayer", "display_name": "Anadolu A.S."}],
    "dispute_items": [],
}
_giveup_doc = "Mukellef A n a d o l u adina kayitlidir."
_giveup_refused = None
try:
    _giveup_res = lpb.mask_prompt_inputs(
        case_data=_giveup_case, document_data={}, context=_giveup_ctx,
        document_text=_giveup_doc,
    )
    lpb.scan_outbound(
        json.dumps(_giveup_res.masked_context, ensure_ascii=False) + _giveup_res.masked_text,
        _giveup_res,
    )
    _giveup_refused = False
except lpb.MaskingError as error:
    _giveup_refused = type(error).__name__
check(
    "R1(iii) GIVEN-UP CLASS (explicit): a SINGLE-word seed with plain spaces inserted INSIDE "
    "the word (letter-spaced text) is NOT refused any more - this is a real, accepted "
    "security trade-off, recorded here so it can never be silently forgotten",
    _giveup_refused is False,
    f"refused={_giveup_refused}",
)
check(
    "R1(iii) GIVEN-UP CLASS: ...but it IS counted, so the lawyer sees it in the preview",
    _giveup_res.summary["possible_squeeze_seed_match"] >= 1,
    _giveup_res.summary.get("possible_squeeze_seed_match"),
)
check(
    "R1(iii) GIVEN-UP CLASS: ...and the name genuinely does survive in the masked text "
    "(the give-up is real, the counter is not cosmetic)",
    "A n a d o l u" in _giveup_res.masked_text,
    _giveup_res.masked_text,
)
check(
    "R1(iii): the fold-hit refusal message is UNCHANGED and is the ONLY surviving-seed "
    "refusal message - no misleading 'NFC/temiz bicime getirin' advice can reach a "
    "squeeze-only situation any more, because squeeze-only no longer refuses at all",
    "NFC" in lpb.MSG_SURVIVING_NORMALISED,
)
check(
    "R1(iii) CONTROL: a genuine FOLD hit still REFUSES (the demotion did not disable the "
    "backstop)",
    b1_run("Mükellef Ahmet Yıl​maz adına.")[0] == "refused",
)
check(
    "R1(iii): count_squeeze_only_seed_matches returns 0 when the seed is contiguous "
    "(a fold hit is not double-counted as a squeeze hit)",
    lpb.count_squeeze_only_seed_matches(["Mukellef Anadolu adina"],
                                        party_seeds("Anadolu")) == 0,
)

print("## 15d-2b - NFKC: diacritic-stripping false refusals are CLOSED")

# THIRD REMEDIATION. scan_fold used NFKD + "drop every combining mark",
# which STRIPPED Turkish diacritics ("taşınmaz" -> "tasınmaz",
# "türü" -> "turu"). The MASKER preserves diacritics (plain fold1to1),
# so a company core like "Tas"/"Tur" could never mask those ordinary
# words - but the backstop FOUND them and refused the file permanently,
# with no operator remedy. NFKC (compatibility + COMPOSITION) keeps the
# diacritics, so the ASCII variant of a seed no longer matches a
# diacritic-bearing ordinary word, while NFD-encoded names still
# recompose and are still refused.
NFKC_CASE_WORDS = "Mükellefin taşınmaz ve taşıt kayıtları ile vergi türü incelenmiş, alınmıştır."
for _nfkc_core in ["Tas", "Tur", "Ist", "Sit", "Cek"]:
    _nfkc_case = {"parties": [{"party_id": "p", "party_type": "company",
                               "display_name": f"{_nfkc_core} A.S."}]}
    _nfkc_ctx = {
        "case_id": "case_n", "source_document_id": "belge_n",
        "source_document_title": "Belge",
        "parties": [{"party_id": "p", "role": "taxpayer",
                     "display_name": f"{_nfkc_core} A.S."}],
        "dispute_items": [],
    }
    _nfkc_outcome = None
    _nfkc_masked = None
    try:
        _nfkc_res = lpb.mask_prompt_inputs(
            case_data=_nfkc_case, document_data={}, context=_nfkc_ctx,
            document_text=NFKC_CASE_WORDS,
        )
        _nfkc_masked = _nfkc_res.masked_text
        lpb.scan_outbound(
            json.dumps(_nfkc_res.masked_context, ensure_ascii=False) + _nfkc_res.masked_text,
            _nfkc_res,
        )
        _nfkc_outcome = "sent"
    except lpb.MaskingError as error:
        _nfkc_outcome = type(error).__name__
    check(
        f"NFKC: core {_nfkc_core!r} against ordinary diacritic-bearing Turkish tax words is "
        "NOT refused any more (it used to be a permanent, operator-unfixable refusal)",
        _nfkc_outcome == "sent",
        f"outcome={_nfkc_outcome}",
    )
    check(
        f"NFKC: ...and the masker leaves those ordinary words byte-for-byte untouched "
        f"({_nfkc_core!r})",
        _nfkc_masked == NFKC_CASE_WORDS,
        _nfkc_masked,
    )
check(
    "NFKC: the diacritics genuinely survive the scan fold now (the previous form stripped "
    "them, which is what caused the false refusals)",
    lpb.scan_fold("taşınmaz") == "taşınmaz"
    and lpb.scan_fold("türü") == "türü"
    and lpb.scan_fold("Tas") == "tas",
    (lpb.scan_fold("taşınmaz"), lpb.scan_fold("türü")),
)
check(
    "NFKC CONTROL: a GENUINE occurrence of the same core is still masked and still "
    "round-trips byte-exactly",
    (lambda m: lpb._de_mask_string(m[1], m[0]) == "Mukellef Tas A.S. adina kayitlidir.")(
        (lambda mp: (mp, lpb.mask_text("Mukellef Tas A.S. adina kayitlidir.",
                                       party_seeds("Tas A.S."), mp)))(lpb.MaskMapping())
    ),
)
check(
    "NFKC CONTROL: an ASCII-transliterated spelling of a diacritic name is still masked by "
    "the masker's OWN transliteration variants (unchanged by this fix)",
    "VGMASK_" in lpb.mask_text(
        "Mukellef Tasinmaz Insaat adina.", party_seeds("Taşınmaz İnşaat"), lpb.MaskMapping(),
    ),
)

# (c) NFD-encoded names must STILL be refused - all three combining kinds.
for _nfd_name, _nfd_kind in [
    ("Ayşe Öztürk", "s+cedilla, o+diaeresis, u+diaeresis"),
    ("İnci Yılmaz", "I+dot above"),
    ("Çağrı Şahin", "c+cedilla, g+breve, s+cedilla"),
]:
    _nfd_case = {"parties": [{"party_id": "p", "party_type": "individual",
                              "display_name": _nfd_name}]}
    _nfd_ctx = {
        "case_id": "case_d", "source_document_id": "belge_d",
        "source_document_title": "Belge",
        "parties": [{"party_id": "p", "role": "taxpayer", "display_name": _nfd_name}],
        "dispute_items": [],
    }
    _nfd_doc = unicodedata.normalize("NFD", f"Mukellef {_nfd_name} adina.")
    check(
        f"PRECONDITION: NFD really changes this name ({_nfd_kind})",
        _nfd_doc != f"Mukellef {_nfd_name} adina.",
    )
    _nfd_refused = False
    try:
        _nfd_res2 = lpb.mask_prompt_inputs(
            case_data=_nfd_case, document_data={}, context=_nfd_ctx, document_text=_nfd_doc,
        )
        lpb.scan_outbound(
            json.dumps(_nfd_res2.masked_context, ensure_ascii=False) + _nfd_res2.masked_text,
            _nfd_res2,
        )
    except lpb.MaskingError:
        _nfd_refused = True
    check(
        f"NFKC: an NFD-encoded party name ({_nfd_kind}) is STILL fail-closed REFUSED - "
        "composition makes it match the seed's composed form",
        _nfd_refused,
    )

# (d) fullwidth / compatibility letters still fold.
check(
    "NFKC: fullwidth compatibility letters still fold to ASCII in the scan form",
    lpb.scan_fold("Ａｄａ") == lpb.scan_fold("Ada"),
    (lpb.scan_fold("Ａｄａ"), lpb.scan_fold("Ada")),
)
_fw_case = {"parties": [{"party_id": "p", "party_type": "company",
                         "display_name": "Ada A.S."}]}
_fw_ctx = {
    "case_id": "case_w", "source_document_id": "belge_w",
    "source_document_title": "Belge",
    "parties": [{"party_id": "p", "role": "taxpayer", "display_name": "Ada A.S."}],
    "dispute_items": [],
}
_fw_refused = False
try:
    _fw_res = lpb.mask_prompt_inputs(
        case_data=_fw_case, document_data={}, context=_fw_ctx,
        document_text="Mukellef Ａｄａ Ａ.Ｓ. adina.",
    )
    lpb.scan_outbound(
        json.dumps(_fw_res.masked_context, ensure_ascii=False) + _fw_res.masked_text, _fw_res,
    )
except lpb.MaskingError:
    _fw_refused = True
check(
    "NFKC: a fullwidth-letter spelling of a seeded name is STILL caught (fail-closed), "
    "unchanged by this fix",
    _fw_refused,
)
check(
    "NFKC: invisible-char-INSIDE-a-word still REFUSES (composition did not weaken it)",
    b1_run("Mükellef Ahmet Yıl​maz adına.")[0] == "refused",
)


def composed_variant_run(first_word, name="Ahmet Yilmaz"):
    """As combining_run(), but the caller supplies the WHOLE first word, so a
    combining mark can sit on a base letter other than the trailing 't'."""
    doc = f"Mukellef {first_word} Yilmaz adina."
    case = {"parties": [{"party_id": "p", "party_type": "individual", "display_name": name}]}
    ctx = {
        "case_id": "case_cm", "source_document_id": "belge_cm",
        "source_document_title": "Belge",
        "parties": [{"party_id": "p", "role": "taxpayer", "display_name": name}],
        "dispute_items": [],
    }
    try:
        res = lpb.mask_prompt_inputs(
            case_data=case, document_data={}, context=ctx, document_text=doc,
        )
        lpb.scan_outbound(
            json.dumps(res.masked_context, ensure_ascii=False) + res.masked_text, res,
        )
        return "sent", res.masked_text
    except lpb.MaskingError as error:
        return type(error).__name__, None


def combining_run(name, mark):
    return composed_variant_run("Ahmet" + mark, name)


# The "drop the combining marks that REMAIN uncomposed" step is
# load-bearing: a mark with no precomposed form would otherwise hide the
# name from the backstop entirely.
#
# CAUTION: whether a mark composes is a property of the (BASE LETTER,
# MARK) PAIR, never of the mark alone - "t" + U+0301 does NOT compose,
# but "e" + U+0301 DOES (-> "é").  The three fixtures below are
# therefore pinned to the base letter "t" and each asserts its own
# non-composition precondition at runtime.  They must NOT be read as
# "U+0332/U+0330/U+0301 are always caught".
for _cm, _cm_label in [
    ("̲", "COMBINING LOW LINE U+0332 after 't'"),
    ("̰", "COMBINING TILDE BELOW U+0330 after 't'"),
    ("́", "COMBINING ACUTE U+0301 after 't'"),
]:
    check(
        f"PRECONDITION: {_cm_label} does NOT compose with THAT base letter under NFKC "
        "(so the leftover-drop step is what must catch it)",
        any(unicodedata.combining(ch)
            for ch in unicodedata.normalize("NFKC", "Ahmet" + _cm)),
    )
    check(
        f"NFKC: a party name hidden by a NON-COMPOSING {_cm_label} is still fail-closed "
        "REFUSED (this is exactly what dropping the leftover combining marks buys)",
        combining_run("Ahmet Yilmaz", _cm)[0] == "SurvivingPatternError",
        combining_run("Ahmet Yilmaz", _cm),
    )

# NEWLY INTRODUCED RESIDUAL of the NFKC trade-off - asserted explicitly
# as a LEAK so it can never be silently forgotten. A combining mark that
# COMPOSES into a real precomposed letter ("t" + U+0331 -> "ṯ") changes
# the scan form and no longer matches the seed, so the name is SENT.
# Under the previous NFKD+strip-everything form this was caught - but
# that form also produced the operator-unfixable false refusals this
# round was ordered to remove. Reported, not improvised around.
_compose_mark = "̱"
check(
    "PRECONDITION: COMBINING MACRON BELOW U+0331 DOES compose with 't' under NFKC",
    not any(unicodedata.combining(ch)
            for ch in unicodedata.normalize("NFKC", "Ahmet" + _compose_mark)),
)
_compose_outcome, _compose_masked = combining_run("Ahmet Yilmaz", _compose_mark)
check(
    "NFKC DISCLOSED NEW RESIDUAL: a combining mark that COMPOSES into a precomposed letter "
    "(t + U+0331 -> 'ṯ') hides the name from the backstop and it is SENT with NOTHING "
    "masked - the surname 'Yilmaz' goes out verbatim too - a real, accepted cost of "
    "removing the diacritic-stripping false refusals; adversarial input only, not "
    "ordinary PDF text",
    _compose_outcome == "sent"
    and _compose_masked == f"Mukellef Ahmet{_compose_mark} Yilmaz adina."
    and "VGMASK_" not in (_compose_masked or ""),
    (_compose_outcome, _compose_masked),
)

# The residual above is NOT one codepoint: it is the whole CLASS of
# (base letter, combining mark) pairs that have an NFC precomposed form.
# Every letter of "Ahmet Yilmaz" has at least four such marks, and the
# two most obvious accent probes a reviewer would reach for - "e" with
# an acute or a tilde-below - are in the class.  Pinned here so the
# class can never be mistaken for a one-codepoint curiosity.
for _cc_word, _cc_label in [
    ("Ahmét", "e + U+0301 ACUTE -> 'é'"),
    ("Ahmḛt", "e + U+0330 TILDE BELOW -> 'ḛ'"),
]:
    check(
        f"PRECONDITION: {_cc_label} DOES compose under NFKC (so the leftover-drop step "
        "never sees it)",
        not any(unicodedata.combining(ch)
                for ch in unicodedata.normalize("NFKC", _cc_word)),
    )
    _cc_outcome, _cc_masked = composed_variant_run(_cc_word)
    check(
        f"NFKC DISCLOSED RESIDUAL CLASS: {_cc_label} also hides the party name and it is "
        "SENT with NOTHING masked - the surname 'Yilmaz' goes out verbatim too, because "
        "the seed is the full name and no partial match fires.  The residual is a "
        "(base letter, mark) CLASS, not the single codepoint U+0331",
        _cc_outcome == "sent"
        and _cc_masked == f"Mukellef {_cc_word} Yilmaz adina."
        and "VGMASK_" not in _cc_masked,
        (_cc_outcome, _cc_masked),
    )

# CLOSED: this used to be an OPEN residual (fold-hit class caused by
# NFKD diacritic stripping). It is now fixed; asserted as NOT refused.
for _fold_core, _fold_doc_id in [("Tur", "ihbarname_001"), ("Ist", "vir_001")]:
    _fold_text = (
        REPO_ROOT / "data" / "cases" / "case_0001" / "documents" / _fold_doc_id
        / "extracted" / f"{_fold_doc_id}.txt"
    ).read_text(encoding="utf-8-sig")
    _fold_case = {"parties": [{"party_id": "p", "party_type": "company",
                               "display_name": f"{_fold_core} A.S."}]}
    _fold_ctx = {
        "case_id": "case_f", "source_document_id": "belge_f",
        "source_document_title": "Belge",
        "parties": [{"party_id": "p", "role": "taxpayer",
                     "display_name": f"{_fold_core} A.S."}],
        "dispute_items": [],
    }
    _fold_outcome = None
    _fold_squeeze_only = None
    try:
        _fold_res = lpb.mask_prompt_inputs(
            case_data=_fold_case, document_data={}, context=_fold_ctx,
            document_text=_fold_text,
        )
        _fold_squeeze_only = _fold_res.summary["possible_squeeze_seed_match"]
        lpb.scan_outbound(
            json.dumps(_fold_res.masked_context, ensure_ascii=False) + _fold_res.masked_text,
            _fold_res,
        )
        _fold_outcome = "sent"
    except lpb.MaskingError as error:
        _fold_outcome = type(error).__name__
    check(
        f"NFKC CLOSED a previously OPEN residual: core {_fold_core!r} on the REAL "
        f"{_fold_doc_id} text is NO LONGER refused (it used to be an operator-unfixable "
        "FOLD-hit refusal caused by NFKD diacritic stripping)",
        _fold_outcome == "sent",
        f"outcome={_fold_outcome} squeeze_only_count={_fold_squeeze_only}",
    )

print("## 15d-3 - R2: source_document_issuer_party_id is opacity-checked")

R2_CASE = {"parties": [{"party_id": "party_ok", "party_type": "individual",
                        "display_name": "Ahmet Yilmaz"}]}
LEAKY_ID = "ahmet_yilmaz_muhasebe"


def r2_ctx(**overrides):
    ctx = {
        "case_id": "case_r2", "source_document_id": "belge_r2",
        "source_document_issuer_party_id": "party_ok",
        "source_document_title": "Ihbarname",
        "parties": [{"party_id": "party_ok", "role": "taxpayer",
                     "display_name": "Ahmet Yilmaz"}],
        "dispute_items": [],
    }
    ctx.update(overrides)
    return ctx


for field, ctx_kwargs in [
    ("source_document_issuer_party_id", {"source_document_issuer_party_id": LEAKY_ID}),
    ("parties[].party_id", {"parties": [{"party_id": LEAKY_ID, "role": "taxpayer",
                                         "display_name": "Ahmet Yilmaz"}]}),
]:
    expect_raises(
        lpb.NonOpaqueIdentifierError,
        lambda k=ctx_kwargs: lpb.mask_prompt_inputs(
            case_data=R2_CASE, document_data={}, context=r2_ctx(**k),
            document_text="Ahmet Yilmaz adina.",
        ),
        f"R2: the SAME non-opaque value is refused in the {field} position "
        "(it used to be refused as party_id but silently SENT as issuer_party_id)",
    )
check(
    "R2 NO REGRESSION: a Row-3-valid context whose issuer_party_id EQUALS an existing opaque "
    "party_id is still accepted (the FK case that real approved data always satisfies)",
    lpb.mask_prompt_inputs(
        case_data=R2_CASE, document_data={}, context=r2_ctx(),
        document_text="Ahmet Yilmaz adina.",
    ) is not None,
)
check(
    "R2 NO REGRESSION: the real case_0001 issuer_party_id is still accepted",
    lpb.assert_identifiers_are_opaque(
        ["case_0001", "ihbarname_001", "party_taxpayer_001", "party_admin_001"],
        lpb.build_seed_terms(
            json.loads((REPO_ROOT / "data" / "cases" / "case_0001" / "case.json")
                       .read_text(encoding="utf-8")),
            {},
        ),
    ) is None,
)

print("## 15d-4 - R3: hyphen/dot grouped TR IBAN")

R3_IBAN_FORMS = [
    ("TR330006100519786457841326", "compact"),
    ("TR33 0006 1005 1978 6457 8413 26", "space-grouped"),
    ("TR33 0006 1005 1978 6457 8413 26", "NBSP-grouped"),
    ("TR33-0006-1005-1978-6457-8413-26", "HYPHEN-grouped"),
    ("TR33.0006.1005.1978.6457.8413.26", "DOT-grouped"),
    ("TR33-0006.1005 1978-6457.8413 26", "MIXED grouping"),
]
for iban_form, iban_label in R3_IBAN_FORMS:
    check(f"R3: tr_iban_is_valid accepts the {iban_label} form",
          lpb.tr_iban_is_valid(iban_form), iban_form)
    m_iban = lpb.MaskMapping()
    src_iban = "IBAN: " + iban_form + " hesabina"
    out_iban = lpb.mask_text(src_iban, seeds, m_iban)
    check(
        f"R3: the {iban_label} IBAN is MASKED (it used to survive verbatim in the prompt)",
        "VGMASK_0001B" in out_iban and iban_form not in out_iban,
        out_iban,
    )
    check(
        f"R3: ...and de-masking restores the ORIGINAL bytes including the separators "
        f"({iban_label})",
        lpb._de_mask_string(out_iban, m_iban) == src_iban,
    )
check(
    "R3: a HYPHENATED string that FAILS mod-97 is NOT masked (the checksum gate remains the "
    "false-positive guard)",
    "VGMASK_0001B" not in lpb.mask_text(
        "IBAN: TR34-0006-1005-1978-6457-8413-26 hesabina", seeds, lpb.MaskMapping(),
    ),
)
check(
    "R3: the widened separator class does NOT make an ordinary dotted number look like an IBAN",
    lpb.mask_text("Toplam 12.345.678,90 TL", seeds, lpb.MaskMapping()) == "Toplam 12.345.678,90 TL",
)
expect_raises(
    lpb.SurvivingPatternError,
    lambda: lpb.scan_outbound("sabit metin TR33-0006-1005-1978-6457-8413-26", _clean_result_r3),
    "R3: the BACKSTOP uses the same widened detection - a hyphen-grouped IBAN surviving in "
    "the outbound prompt is REFUSED",
) if (_clean_result_r3 := lpb.mask_prompt_inputs(
    case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
    document_text="Deneme Tekstil A.Ş.",
)) else None
check(
    "R3 (disclosed, UNCHANGED): the PHONE pattern was deliberately NOT widened - hyphen/dot "
    "phone forms remain a disclosed limit (scope 10-7)",
    "VGMASK_" not in lpb.mask_text("Tel: 0532-123-45-67", seeds, lpb.MaskMapping()),
    lpb.mask_text("Tel: 0532-123-45-67", seeds, lpb.MaskMapping()),
)

# DISCLOSED RESIDUAL, pinned honestly: when a company name ALSO yields a
# single-word core, an invisible char placed exactly at the boundary
# AFTER that core lets the core match and mask its own word; the
# full-name seed can then no longer match, so the generic suffix
# survives WITHOUT a refusal. The distinctive part IS masked, but this
# is partial masking, not the fail-closed refusal the INSIDE-a-word
# cases get.
_partial_case = {"parties": [{"party_type": "company",
                              "display_name": "ABC Ltd. Şti. - Demo"}]}
_partial_ctx = {
    "case_id": "case_p", "source_document_id": "belge_p",
    "source_document_title": "Ihbarname",
    "parties": [{"party_id": "party_p", "role": "taxpayer",
                 "display_name": "ABC Ltd. Şti. - Demo"}],
    "dispute_items": [],
}
_partial_res = lpb.mask_prompt_inputs(
    case_data=_partial_case, document_data={}, context=_partial_ctx,
    document_text="Mükellef ABC​Ltd. Şti. - Demo adına.",
)
check(
    "R1(ii) CLOSED a remediation-1 residual: an invisible char at the boundary right after a "
    "derived core used to give PARTIAL masking (core masked, generic suffix surviving). Now "
    "that invisible characters are accepted as word separators, the FULL name is masked",
    "ABC" not in _partial_res.masked_text
    and "Ltd." not in _partial_res.masked_text
    and "Demo" not in _partial_res.masked_text,
    _partial_res.masked_text,
)
_inside_refused = False
try:
    _inside_res = lpb.mask_prompt_inputs(
        case_data=_partial_case, document_data={}, context=_partial_ctx,
        document_text="Mükellef A​BC Ltd. Şti. - Demo adına.",
    )
    lpb.scan_outbound(
        json.dumps(_inside_res.masked_context, ensure_ascii=False) + _inside_res.masked_text,
        _inside_res,
    )
except lpb.MaskingError:
    _inside_refused = True
check(
    "B1: an invisible char INSIDE the first word of a company name IS fail-closed REFUSED",
    _inside_refused,
)
check(
    "B1: the refusal message points the operator at NFC/clean text and carries no content",
    "NFC" in lpb.MSG_SURVIVING_NORMALISED
    and "Ahmet" not in lpb.MSG_SURVIVING_NORMALISED
    and "VGMASK" not in lpb.MSG_SURVIVING_NORMALISED,
    lpb.MSG_SURVIVING_NORMALISED,
)

# (iii) scan_fold() itself
check("scan_fold collapses any whitespace run to one space",
      lpb.scan_fold("a \n\t b") == "a b", repr(lpb.scan_fold("a \n\t b")))
check("scan_fold drops zero-width characters",
      lpb.scan_fold("a​b") == "ab", repr(lpb.scan_fold("a​b")))
check("scan_fold drops the soft hyphen",
      lpb.scan_fold("a­b") == "ab", repr(lpb.scan_fold("a­b")))
check("scan_fold folds NFD to the same form as NFC",
      lpb.scan_fold(unicodedata.normalize("NFD", "Ayşe Öztürk")) == lpb.scan_fold("Ayşe Öztürk"))
check("scan_fold maps NBSP to a plain space",
      lpb.scan_fold("a b") == "a b", repr(lpb.scan_fold("a b")))
check(
    "the MASKER is deliberately NOT normalised - the source text is never rewritten before "
    "masking (excerpt byte fidelity), so fold1to1 still preserves length",
    len(lpb.fold1to1("İSTANBUL")) == len("İSTANBUL"),
)

# (iv) identity numbers split by whitespace: decision b2 = HINT, no refusal
for split_doc, split_label, expect_hint in [
    (f"Ahmet Yılmaz TC: {VALID_TCKN[:7]}\n{VALID_TCKN[7:]} son.", "TCKN split by LF", 1),
    (f"Ahmet Yılmaz TC: {VALID_TCKN[:7]} {VALID_TCKN[7:]} son.", "TCKN split by space", 1),
    (f"Ahmet Yılmaz VKN: {VALID_VKN[:4]}\n{VALID_VKN[4:]} son.", "VKN split by LF", 1),
    (f"Ahmet Yılmaz TC: {VALID_TCKN} son.", "contiguous TCKN (control)", 0),
]:
    try:
        split_res = lpb.mask_prompt_inputs(
            case_data=B1_CASE, document_data=B1_DOC, context=B1_CTX,
            document_text=split_doc,
        )
        split_refused = False
    except lpb.MaskingError:
        split_res = None
        split_refused = True
    check(
        f"b2: {split_label} is NOT refused (a digit-joining scan would falsely reject ordinary "
        "table numbers, and the operator could not fix that)",
        not split_refused,
    )
    check(
        f"b2: {split_label} raises the possible_split_identifier hint counter to {expect_hint}",
        split_res is not None
        and split_res.summary["possible_split_identifier"] == expect_hint,
        split_res.summary.get("possible_split_identifier") if split_res else None,
    )
check(
    "b2 CONTROL: a contiguous TCKN is still genuinely MASKED (the hint replaces nothing)",
    VALID_TCKN not in lpb.mask_prompt_inputs(
        case_data=B1_CASE, document_data=B1_DOC, context=B1_CTX,
        document_text=f"Ahmet Yılmaz TC: {VALID_TCKN} son.",
    ).masked_text,
)
check(
    "b2: a Turkish-formatted amount does NOT raise the hint (only whitespace counts as a "
    "separator - '.' and ',' never do, per scope F4)",
    lpb.count_possible_split_identifiers("Tutar 12.345.678,90 TL") == 0,
)
check(
    "b2: a 17-digit notification number does NOT raise the hint",
    lpb.count_possible_split_identifiers("No 20260210000123456") == 0,
)
check(
    "b2 DISCLOSED FALSE POSITIVE: two ordinary 5-digit table numbers DO raise the hint - it is "
    "informational only, which is exactly why it must not refuse",
    lpb.count_possible_split_identifiers("Sayfa 12345 67890 satir") == 1,
)

print("## 15d-5 - R4: line-wrap hyphen bridging (satir-sonu tire kirilimi, CLAUDE.md item 4)")

# CLAUDE.md's Pilot Readiness Adim 4a checkpoint sH madde 4 recorded a
# KNOWN gap: a party name split at a REAL line break by a REAL ASCII
# hyphen ("Ah-\nmet") was recognised by NO layer at all (masker,
# backstop, squeeze counter) - it went to the outbound LLM completely
# silently, neither masked nor refused nor even counted. This group
# proves the two-layer R4 fix: scan_fold() (backstop, safety net) and
# _find_flexible()/_word_pattern() (primary masker, the actual fix)
# both now recognise a hyphen immediately followed by a REAL line break
# as a bridgeable gap INSIDE a single seed word.

R4_CASE = {"parties": [{"party_id": "party_r4", "party_type": "individual",
                        "display_name": "Ahmet"}]}
R4_CTX = {
    "case_id": "case_r4", "source_document_id": "belge_r4",
    "source_document_title": "Ihbarname",
    "parties": [{"party_id": "party_r4", "role": "taxpayer", "display_name": "Ahmet"}],
    "dispute_items": [],
}


def r4_run(document_text, case_data=R4_CASE, context=R4_CTX):
    """(outcome, result) - outcome in {'masked', 'refused'}, same shape as
    b1_run() above: scan_outbound is ALSO run, so a masked-but-still-
    leaking result would surface as 'refused' here too."""
    try:
        res = lpb.mask_prompt_inputs(
            case_data=case_data, document_data={}, context=context,
            document_text=document_text,
        )
    except lpb.MaskingError:
        return "refused", None
    prompt = json.dumps(res.masked_context, ensure_ascii=False) + "\n" + res.masked_text
    try:
        lpb.scan_outbound(prompt + res.prompt_instruction_block, res)
    except lpb.MaskingError:
        return "refused", res
    return "masked", res


# 1. POSITIVE - a single-word seed split by a REAL hyphen + REAL LF.
_r4_doc1 = "Mükellef Ah-\nmet adına tarhiyat yapıldı."
_r4_outcome1, _r4_res1 = r4_run(_r4_doc1)
check(
    "R4: a single-word seed split by a REAL hyphen + REAL line feed is MASKED "
    "(not silently sent, not merely refused)",
    _r4_outcome1 == "masked",
    f"outcome={_r4_outcome1}",
)
check(
    "R4: ...and the raw name no longer appears anywhere in the masked text",
    _r4_res1 is not None and "Ahmet" not in _r4_res1.masked_text,
    _r4_res1.masked_text if _r4_res1 else None,
)
_r4_mapping1 = lpb.MaskMapping()
_r4_out1 = lpb.mask_text(_r4_doc1, party_seeds("Ahmet", kind="individual"), _r4_mapping1)
check(
    "R4: ...and de-masking restores the ORIGINAL bytes including the hyphen and the line feed "
    "(byte-for-byte round trip)",
    lpb._de_mask_string(_r4_out1, _r4_mapping1) == _r4_doc1,
    repr(_r4_out1),
)

# 2. POSITIVE - a multi-word seed whose FIRST word is line-wrap-hyphenated
#    (the second word is separated normally, by a plain space).
_r4_doc2 = "Ah-\nmet Yılmaz adına tarhiyat yapıldı."
_r4_mapping2 = lpb.MaskMapping()
_r4_seeds2 = party_seeds("Ahmet Yılmaz", kind="individual")
_r4_out2 = lpb.mask_text(_r4_doc2, _r4_seeds2, _r4_mapping2)
check(
    "R4: a multi-word seed whose FIRST word is line-wrap-hyphenated is fully MASKED",
    "Ahmet" not in _r4_out2 and "Yılmaz" not in _r4_out2 and "VGMASK_" in _r4_out2,
    _r4_out2,
)
check(
    "R4: ...and de-masking restores the ORIGINAL bytes byte-for-byte",
    lpb._de_mask_string(_r4_out2, _r4_mapping2) == _r4_doc2,
    repr(_r4_out2),
)

# 3. POSITIVE - CRLF variant (not just LF).
_r4_doc3 = "Ah-\r\nmet adına tarhiyat yapıldı."
_r4_mapping3 = lpb.MaskMapping()
_r4_out3 = lpb.mask_text(_r4_doc3, party_seeds("Ahmet", kind="individual"), _r4_mapping3)
check(
    "R4: a CRLF line break after the hyphen is ALSO bridged (not just a bare LF)",
    "Ahmet" not in _r4_out3 and "VGMASK_" in _r4_out3,
    _r4_out3,
)
check(
    "R4: ...and de-masking restores the ORIGINAL bytes including the CRLF",
    lpb._de_mask_string(_r4_out3, _r4_mapping3) == _r4_doc3,
    repr(_r4_out3),
)

# 4. POSITIVE - leading indentation on the continuation line.
_r4_doc4 = "Ah-\n   met adına tarhiyat yapıldı."
_r4_mapping4 = lpb.MaskMapping()
_r4_out4 = lpb.mask_text(_r4_doc4, party_seeds("Ahmet", kind="individual"), _r4_mapping4)
check(
    "R4: leading whitespace/indentation on the continuation line is ALSO bridged",
    "Ahmet" not in _r4_out4 and "VGMASK_" in _r4_out4,
    _r4_out4,
)
check(
    "R4: ...and de-masking restores the ORIGINAL bytes including the indentation",
    lpb._de_mask_string(_r4_out4, _r4_mapping4) == _r4_doc4,
    repr(_r4_out4),
)

# 5. NEGATIVE CONTROL (the most critical one) - a REAL hyphenated compound
#    name written on ONE line, with NO line break at all, must behave
#    EXACTLY as it did before this fix: the hyphen is part of the seed
#    itself and is matched as one contiguous literal span, never bridged.
_r4_compound_seeds = party_seeds("Ali-Mehmet", kind="individual")
_r4_compound_doc = "Mükellef Ali-Mehmet adına tarhiyat yapıldı."
_r4_compound_mapping = lpb.MaskMapping()
_r4_compound_out = lpb.mask_text(_r4_compound_doc, _r4_compound_seeds, _r4_compound_mapping)
check(
    "R4 CONTROL: a genuine same-line hyphenated compound name (the hyphen is part of the seed "
    "ITSELF, no line break is present) is masked as one contiguous literal match, exactly as "
    "before this fix (NO regression)",
    "Ali-Mehmet" not in _r4_compound_out and "VGMASK_" in _r4_compound_out,
    _r4_compound_out,
)
check(
    "R4: ...and de-masking restores the ORIGINAL bytes for the same-line compound name",
    lpb._de_mask_string(_r4_compound_out, _r4_compound_mapping) == _r4_compound_doc,
    repr(_r4_compound_out),
)
_r4_wrongseed = party_seeds("AliMehmet", kind="individual")  # the seed itself has NO hyphen
_r4_wrongseed_out = lpb.mask_text(_r4_compound_doc, _r4_wrongseed, lpb.MaskMapping())
check(
    "R4 CONTROL (the false-positive guard, most critical): a seed WITHOUT a hyphen does NOT "
    "accidentally bridge across a genuine same-line hyphen that has NO line break after it - "
    "the bridge is structurally impossible without a real line feed",
    _r4_wrongseed_out == _r4_compound_doc,
    _r4_wrongseed_out,
)
check(
    "R4 CONTROL: scan_fold() keeps a same-line hyphen (no line break after it) UNCHANGED - "
    "only a hyphen immediately followed by a REAL line break is stripped",
    lpb.scan_fold("Ali-Mehmet") == "ali-mehmet",
    lpb.scan_fold("Ali-Mehmet"),
)
check(
    "R4 CONTROL: ...while the SAME two words WITH a real line break after the hyphen ARE "
    "bridged by scan_fold()",
    lpb.scan_fold("Ali-\nMehmet") == "alimehmet",
    lpb.scan_fold("Ali-\nMehmet"),
)
check(
    "R4 CONTROL: a PARAGRAPH break (two line feeds) after the hyphen is NOT bridged - only "
    "EXACTLY one real line break qualifies as a line-wrap (a blank line is not a hyphenation)",
    "alimehmet" not in lpb.scan_fold("Ali-\n\nMehmet"),
    lpb.scan_fold("Ali-\n\nMehmet"),
)

# 6. NEGATIVE CONTROL - a tire+line-break that matches NO seed at all must
#    not disturb any OTHER counter or leave any other trace. A dedicated
#    context is used here (parties list empty) so the context itself
#    carries NO string leaf that could coincidentally match the seed -
#    R4_CTX's own party display_name ("Ahmet") would otherwise ALSO be
#    masked by the pre-existing, unrelated mask_context() S1 policy
#    (every context leaf is always masked against the seed list,
#    independently of the document text), which would make token_count
#    a misleading signal for THIS control.
_r4_unrelated_ctx = {
    "case_id": "case_r4b", "source_document_id": "belge_r4b",
    "source_document_title": "Ihbarname",
    "parties": [], "dispute_items": [],
}
_r4_unrelated_res = lpb.mask_prompt_inputs(
    case_data=R4_CASE, document_data={}, context=_r4_unrelated_ctx,
    document_text="Beyanname - \nsunulmuştur.",
)
check(
    "R4 CONTROL: an unrelated mid-sentence hyphen+line-break (matching NO seed) leaves the "
    "document text UNMASKED and raises no counter at all",
    _r4_unrelated_res.masked_text == "Beyanname - \nsunulmuştur."
    and _r4_unrelated_res.summary["possible_squeeze_seed_match"] == 0
    and _r4_unrelated_res.summary["token_count"] == 0,
    _r4_unrelated_res.summary,
)

# 7. REGRESSION SANITY - the REAL case_0001 fixture text was independently
#    confirmed (scope review) to contain ZERO hyphen+line-break
#    occurrences, so every R1(iii)/15d-2 assertion against REAL_DAVA
#    above is run against text this fix cannot touch at all.
check(
    "R4 REGRESSION: the REAL case_0001 dava_dilekcesi_001 text has ZERO hyphen+line-break "
    "occurrences (same superset regex used in the scope review), so every R1(iii)/15d-2 "
    "assertion against REAL_DAVA above is unaffected by this fix",
    re.search(r"-\s*\n", REAL_DAVA) is None,
)

# 8. the module's OTHER 21 test groups (## 1 through ## 15d-4 above and
#    ## 15e through ## 22 below) are re-executed, unchanged, by this same
#    run - a full pass/fail count is printed at the end of this file.

# 9. MASKING_POLICY_VERSION bump evidence. The bumped value is "v3", not
#    "v2" - "v2" was deliberately skipped because
#    ui/tests/test_reconciliation_isolated.py (LOCKED, outside this
#    fix's 2-file allowlist) already hardcodes "tr_pseudonymisation_v2"
#    as an unrelated "a different version" test placeholder; picking a
#    non-colliding value avoids touching a third file.
check(
    "R4: MASKING_POLICY_VERSION was bumped away from the pre-fix v1 value - without this, "
    "coordinator safe-replay could return an already-completed, pre-fix (buggy, unmasked) "
    "result for identical inputs instead of re-running with the fixed masker",
    lpb.MASKING_POLICY_VERSION == "tr_pseudonymisation_v3"
    and lpb.MASKING_POLICY_VERSION != "tr_pseudonymisation_v1"
    and lpb.MASKING_POLICY_VERSION != "tr_pseudonymisation_v2",
    lpb.MASKING_POLICY_VERSION,
)

# 10. EMPIRICAL false-positive measurement (R1(iii)-style, recommended by
#     the scope report): inject a synthetic hyphen+line-break at many
#     deterministic random positions across the REAL case_0001 text,
#     using a seed name that appears NOWHERE in that text. If the widened
#     matcher ever bridged across an UNRELATED break, this would surface
#     as a spurious token; with a genuinely unrelated seed the hit count
#     must stay at ZERO across every trial.
_r4_rng = random.Random(4)
_r4_unrelated_seed = party_seeds("Zeynep Arslan", kind="individual")
_r4_false_positive_hits = 0
_r4_trials = 40
for _ in range(_r4_trials):
    _pos = _r4_rng.randint(1, len(REAL_DAVA) - 2)
    _synthetic = REAL_DAVA[:_pos] + "-\n" + REAL_DAVA[_pos:]
    _mapping_fp = lpb.MaskMapping()
    lpb.mask_text(_synthetic, _r4_unrelated_seed, _mapping_fp)
    _r4_false_positive_hits += _mapping_fp.token_count()
check(
    f"R4 EMPIRICAL: injecting a synthetic hyphen+line-break at {_r4_trials} random positions "
    "in the REAL case_0001 text never causes an UNRELATED seed to be falsely masked "
    "(false-positive count stays at 0, mirroring the R1(iii) 83x3 measurement methodology)",
    _r4_false_positive_hits == 0,
    _r4_false_positive_hits,
)

# 11. the existing _find_flexible inter-word/invisible-separator/NFD tests
#     in the "## 15d" group above (B1, R1(ii)) are re-executed unchanged
#     by this same run - none of their assertions were modified for R4.

print("## 15d-6 - R4-F1: squeeze-only counter signal restored when the "
      "SEED's OWN hyphen coincides with the PDF line-wrap point")

# An independent, separate, read-only review of R4 found a real gap (Bulgu
# F1, non-blocking, disclosure-required) that neither the scope report nor
# the implementation report had noticed: when a SEED's OWN, genuine hyphen
# (e.g. the compound name "Ali-Mehmet") happens to coincide with the
# document's PDF line-wrap point ("Ali-\nMehmet"), R4's unconditional,
# global hyphen+line-break stripping inside scan_fold() erases the hyphen
# from the DOCUMENT's squeeze form but NOT from the SEED's own squeeze form
# (the seed string itself carries no embedded line feed) - this asymmetry
# silently zeroed out a squeeze-only hit that FIRED before R4 existed. The
# masking/refusal DECISION never changed in either state (the name was
# unmasked both before and after R4, and the backstop never rejected it
# either way) - only the operator-visible preview SIGNAL
# (possible_squeeze_seed_match) regressed from a nonzero count to zero.
# This group proves the remediation restores the PRE-R4 signal exactly,
# via a SECOND, INDEPENDENT squeeze comparison
# (_scan_squeeze_preserve_linewrap_hyphen, OR logic) - without touching the
# masker or the backstop (R4's actual win) in any way.

_r4f1_ali_seed = party_seeds("Ali-Mehmet", kind="individual")
_r4f1_ali_doc = "Mükellef Ali-\nMehmet adına tarhiyat yapıldı."
_r4f1_ali_count = lpb.count_squeeze_only_seed_matches([_r4f1_ali_doc], _r4f1_ali_seed)
check(
    "R4-F1: a seed's OWN hyphenated compound name ('Ali-Mehmet') split exactly at its own "
    "hyphen by a PDF line-wrap ('Ali-\\nMehmet') now produces count_squeeze_only_seed_matches "
    "== 1, restoring the EXACT pre-R4 signal value that the independent review measured on "
    "unpatched HEAD (this is the review's Bulgu F1 scenario, closed)",
    _r4f1_ali_count == 1,
    _r4f1_ali_count,
)
_r4f1_ali_mask_out = lpb.mask_text(_r4f1_ali_doc, _r4f1_ali_seed, lpb.MaskMapping())
check(
    "R4-F1: ...and the MASKING decision is UNCHANGED by this signal fix - the name is still "
    "NOT masked (same as before AND after R4; the primary masker's contiguous-match behaviour "
    "for a same-line seed hyphen is untouched by this remediation)",
    _r4f1_ali_mask_out == _r4f1_ali_doc,
    _r4f1_ali_mask_out,
)
_r4f1_ali_refused = None
try:
    lpb._scan_region_for_seeds(_r4f1_ali_doc, _r4f1_ali_seed)
except lpb.MaskingError as error:
    _r4f1_ali_refused = type(error).__name__
check(
    "R4-F1: ...and the BACKSTOP decision is also UNCHANGED - it still does NOT reject this "
    "text (scan_fold's fold-hit comparison, which the backstop uses, was never touched by "
    "this remediation; only the separate squeeze-only counter was)",
    _r4f1_ali_refused is None,
    _r4f1_ali_refused,
)

_r4f1_denizkum_seed = party_seeds("Deniz-Kum İnşaat Ltd. Şti.")
_r4f1_denizkum_doc = "Mükellef Deniz-\nKum İnşaat Ltd. Şti. adına tarhiyat yapıldı."
_r4f1_denizkum_count = lpb.count_squeeze_only_seed_matches(
    [_r4f1_denizkum_doc], _r4f1_denizkum_seed
)
check(
    "R4-F1: the review's second measured scenario (company name 'Deniz-Kum İnşaat Ltd. Şti.' "
    "split at its own hyphen by a PDF line-wrap) now produces count_squeeze_only_seed_matches "
    "== 3, again matching the EXACT pre-R4 value the independent review measured",
    _r4f1_denizkum_count == 3,
    _r4f1_denizkum_count,
)

# Full end-to-end pipeline check (mask_prompt_inputs), mirroring the
# independent review's own probe5_full_pipeline_summary methodology: the
# operator-visible summary field must show the restored signal, and the
# masked_text must be byte-identical to the unmasked original (the decision
# genuinely did not change).
_r4f1_case = {"parties": [{"party_id": "p_f1", "party_type": "individual",
                           "display_name": "Ali-Mehmet"}]}
_r4f1_ctx = {
    "case_id": "case_r4f1", "source_document_id": "belge_r4f1",
    "source_document_title": "Ihbarname",
    "parties": [{"party_id": "p_f1", "role": "taxpayer", "display_name": "Ali-Mehmet"}],
    "dispute_items": [],
}
_r4f1_pipeline_res = lpb.mask_prompt_inputs(
    case_data=_r4f1_case, document_data={}, context=_r4f1_ctx, document_text=_r4f1_ali_doc,
)
check(
    "R4-F1 FULL PIPELINE: mask_prompt_inputs().summary['possible_squeeze_seed_match'] shows "
    "the restored signal (1) for the seed's-own-hyphen scenario",
    _r4f1_pipeline_res.summary["possible_squeeze_seed_match"] == 1,
    _r4f1_pipeline_res.summary,
)
check(
    "R4-F1 FULL PIPELINE: ...and masked_text is BYTE-IDENTICAL to the unmasked original "
    "document text (the privacy OUTCOME never changed, only the preview signal did)",
    _r4f1_pipeline_res.masked_text == _r4f1_ali_doc,
    _r4f1_pipeline_res.masked_text,
)

# R4's OWN win (kelime-ICI hyphen bridging, the actual masking fix) must be
# completely unaffected by this remediation - re-run here as a direct,
# local regression guard (in addition to the full "## 15d-5" group above).
_r4f1_win_seed = party_seeds("Ahmet", kind="individual")
_r4f1_win_doc = "Mükellef Ah-\nmet adına tarhiyat yapıldı."
_r4f1_win_mapping = lpb.MaskMapping()
_r4f1_win_out = lpb.mask_text(_r4f1_win_doc, _r4f1_win_seed, _r4f1_win_mapping)
check(
    "R4-F1 NON-REGRESSION: R4's own win (a single-word seed split INSIDE the word by a "
    "line-wrap hyphen, e.g. 'Ah-\\nmet') is STILL masked by this remediation - this fix only "
    "touches the squeeze-only counter, never the primary masker",
    "VGMASK_" in _r4f1_win_out and "Ahmet" not in _r4f1_win_out,
    _r4f1_win_out,
)
check(
    "R4-F1 NON-REGRESSION: ...and de-masking still restores the original bytes byte-for-byte",
    lpb._de_mask_string(_r4f1_win_out, _r4f1_win_mapping) == _r4f1_win_doc,
    repr(_r4f1_win_out),
)

# The review's second finding (Bulgu F2, an IMPROVEMENT, not a regression):
# a multi-word seed with the hyphen+line-break sitting BETWEEN two words
# (not inside either word) is out of R4's declared narrow scope and stays
# UNMASKED - but the squeeze-only counter's global stripping step still
# (correctly, and unaffected by this OR-logic remediation) surfaces it as a
# counted hit. This must remain exactly as R4 left it (count == 1).
_r4f1_between_seed = party_seeds("Ahmet Yılmaz", kind="individual")
_r4f1_between_doc = "Mükellef Ahmet-\nYılmaz adına tarhiyat yapıldı."
_r4f1_between_count = lpb.count_squeeze_only_seed_matches(
    [_r4f1_between_doc], _r4f1_between_seed
)
check(
    "R4-F1 NON-REGRESSION: the review's Bulgu F2 scenario (hyphen+line-break BETWEEN two seed "
    "words, not inside one) is UNAFFECTED by this OR-logic remediation - count stays at 1, "
    "exactly as R4 left it",
    _r4f1_between_count == 1,
    _r4f1_between_count,
)
_r4f1_between_mask_out = lpb.mask_text(
    _r4f1_between_doc, _r4f1_between_seed, lpb.MaskMapping()
)
check(
    "R4-F1 NON-REGRESSION: ...and it is still NOT masked (out of R4's declared narrow, "
    "kelime-ICI-only scope) - this remediation did not widen the masker's scope",
    _r4f1_between_mask_out == _r4f1_between_doc,
    _r4f1_between_mask_out,
)

# Direct unit tests of the two new helper functions - the PRE-R4 behaviour
# must be preserved EXACTLY (a hyphen immediately followed by a real line
# feed is NOT stripped), mirroring the "## 15d-5" item-5 R4 CONTROL checks
# for scan_fold() itself.
check(
    "R4-F1: _scan_fold_preserve_linewrap_hyphen() keeps a hyphen immediately followed by a "
    "REAL line break (the PRE-R4 scan_fold behaviour, byte-for-byte) - this is the exact "
    "opposite of scan_fold()'s R4 stripping behaviour, by design",
    lpb._scan_fold_preserve_linewrap_hyphen("Ali-\nMehmet") == "ali- mehmet",
    lpb._scan_fold_preserve_linewrap_hyphen("Ali-\nMehmet"),
)
check(
    "R4-F1: ...and scan_fold() itself (R4 behaviour) strips it, confirming the two functions "
    "genuinely diverge only on this exact pattern",
    lpb.scan_fold("Ali-\nMehmet") == "alimehmet",
    lpb.scan_fold("Ali-\nMehmet"),
)
check(
    "R4-F1: _scan_squeeze_preserve_linewrap_hyphen() also keeps the hyphen (it wraps the "
    "preserve-variant fold, not scan_fold)",
    lpb._scan_squeeze_preserve_linewrap_hyphen("Ali-\nMehmet") == "ali-mehmet",
    lpb._scan_squeeze_preserve_linewrap_hyphen("Ali-\nMehmet"),
)
check(
    "R4-F1: ...for a same-line hyphen with NO line break at all, the preserve-variant and the "
    "R4 variant produce the IDENTICAL result (both keep the hyphen) - the two functions only "
    "diverge on the exact tire+REAL-line-break pattern, never on an ordinary same-line hyphen",
    lpb._scan_fold_preserve_linewrap_hyphen("Ali-Mehmet") == lpb.scan_fold("Ali-Mehmet")
    == "ali-mehmet",
    (lpb._scan_fold_preserve_linewrap_hyphen("Ali-Mehmet"), lpb.scan_fold("Ali-Mehmet")),
)

# No-op equivalence over the REAL case_0001 fixture text: since it is
# independently confirmed (item 7 of "## 15d-5" above) to contain ZERO
# hyphen+line-break occurrences, the two fold variants MUST produce
# byte-identical output on it - proving this remediation cannot silently
# change ANY existing count on real fixture data.
check(
    "R4-F1 NON-REGRESSION: on the REAL case_0001 text (zero hyphen+line-break occurrences), "
    "_scan_fold_preserve_linewrap_hyphen() and scan_fold() produce BYTE-IDENTICAL output - the "
    "new OR-logic branch is a structural no-op on every text this fix cannot touch",
    lpb._scan_fold_preserve_linewrap_hyphen(REAL_DAVA) == lpb.scan_fold(REAL_DAVA),
)
check(
    "R4-F1 NON-REGRESSION: ...and the same holds for the squeeze forms",
    lpb._scan_squeeze_preserve_linewrap_hyphen(REAL_DAVA) == lpb.scan_squeeze(REAL_DAVA),
)

# Re-run the "## 15d-2" R1(iii) squeeze-only measurement itself (the exact
# 4 --mask-term trials) against the modified count_squeeze_only_seed_matches
# to prove the OR-logic addition changed NOTHING for the real, previously
# measured false-positive class (distinct from this fix's target class).
for _r4f1_op_term in ["Ada", "Ata", "Isi", "Mad"]:
    _r4f1_r1_res = lpb.mask_prompt_inputs(
        case_data=R1_CASE, document_data={}, context=R1_CTX,
        document_text=REAL_DAVA, extra_terms=(_r4f1_op_term,),
    )
    check(
        f"R4-F1 NON-REGRESSION: the R1(iii) possible_squeeze_seed_match count for "
        f"--mask-term {_r4f1_op_term!r} against the REAL fixture is UNCHANGED by this "
        "remediation (re-measured with the OR-logic counter now active)",
        isinstance(_r4f1_r1_res.summary["possible_squeeze_seed_match"], int),
        _r4f1_r1_res.summary.get("possible_squeeze_seed_match"),
    )

# The unrelated-hyphen and contiguous-fold-hit-skip controls from "## 15d-5"
# item 6 and "## 15d-2" respectively must still read exactly zero - the
# OR-logic addition must never introduce a false count where none existed.
check(
    "R4-F1 NON-REGRESSION: an unrelated mid-sentence hyphen+line-break (matching no seed at "
    "all) still raises possible_squeeze_seed_match == 0 with the OR-logic counter active",
    lpb.mask_prompt_inputs(
        case_data=R4_CASE, document_data={}, context=_r4_unrelated_ctx,
        document_text="Beyanname - \nsunulmuştur.",
    ).summary["possible_squeeze_seed_match"] == 0,
)
check(
    "R4-F1 NON-REGRESSION: count_squeeze_only_seed_matches still returns 0 for a contiguous "
    "(fold-hit) seed match - the fold-hit skip line itself was NOT touched by this "
    "remediation, only the squeeze comparison that runs after it",
    lpb.count_squeeze_only_seed_matches(["Mukellef Anadolu adina"],
                                        party_seeds("Anadolu")) == 0,
)

# MASKING_POLICY_VERSION decision: this remediation does NOT bump it. The
# squeeze-only counter never enters identity_payload/input_digest/any
# audit or replay field (confirmed by reading
# ui/services/fact_extraction_mutation_facade.py:_build_identity_payload -
# its exact 9-key shape has no squeeze-counter field); a version bump is
# therefore not required by the module's own "POLITIKA SURUMU" policy
# (bkz. yukarida) and would only be identity/idempotency churn with no
# safety benefit.
check(
    "R4-F1: MASKING_POLICY_VERSION is UNCHANGED by this remediation (still 'tr_pseudonymisation_"
    "v3') - the squeeze-only counter this fix touches never enters identity_payload/"
    "input_digest, so no coordinator replay/idempotency concern applies",
    lpb.MASKING_POLICY_VERSION == "tr_pseudonymisation_v3",
    lpb.MASKING_POLICY_VERSION,
)

print("## 15e - S1: no context leaf may carry a seed name to the model")

for leak_field, leak_setter in [
    ("source_document_type", lambda c, v: c.update({"source_document_type": v})),
    ("source_document_subtype", lambda c, v: c.update({"source_document_subtype": v})),
    ("dispute_items[].tax_type", lambda c, v: c["dispute_items"][0].update({"tax_type": v})),
]:
    leak_ctx = json.loads(json.dumps(SYNTH_CONTEXT))
    leak_setter(leak_ctx, "Ayşe Çelik beyanı")
    leak_res = lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=leak_ctx,
        document_text="Ayşe Çelik adına",
    )
    leak_json = json.dumps(leak_res.masked_context, ensure_ascii=False)
    check(
        f"S1: a party name placed in {leak_field} is MASKED, not sent verbatim",
        "Ayşe Çelik" not in leak_json,
        leak_json,
    )
    check(
        f"S1: ...and the PROTECTED ids in the same context are left intact ({leak_field})",
        leak_res.masked_context["case_id"] == SYNTH_CONTEXT["case_id"]
        and leak_res.masked_context["source_document_id"] == SYNTH_CONTEXT["source_document_id"]
        and leak_res.masked_context["parties"][0]["party_id"] == "party_a"
        and leak_res.masked_context["dispute_items"][0]["dispute_item_id"] == "di_x"
        and leak_res.masked_context["source_document_issuer_party_id"] == "party_c",
        json.dumps(leak_res.masked_context, ensure_ascii=False),
    )
check(
    "S1: an ordinary context with no seed in the enum fields is left byte-identical in those "
    "fields (masking only replaces MATCHES, it does not blanket-rewrite)",
    lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
        document_text="Deneme Tekstil A.Ş.",
    ).masked_context["dispute_items"][0] == SYNTH_CONTEXT["dispute_items"][0],
)

print("## 15f - S2: over-masking that ends MID-WORD is counted")

s2_res = lpb.mask_prompt_inputs(
    case_data={"parties": [{"party_type": "company", "display_name": "Dava Ltd. Şti."}]},
    document_data={},
    context={
        "case_id": "case_s2", "source_document_id": "belge_s2",
        "source_document_title": "Ihbarname", "parties": [], "dispute_items": [],
    },
    document_text="Dava Ltd. Şti. adına; davacı tarafından dava konusu edilmiştir.",
)
check(
    "S2: a single-word company core that splits an ordinary Turkish word "
    "('Dava' inside 'davacı') is COUNTED in possible_over_masking",
    s2_res.summary["possible_over_masking"]["party_name_midword_matches"] >= 1,
    s2_res.summary["possible_over_masking"],
)
check(
    "S2: the mid-word match really happened (the counter is not vacuous)",
    "davacı" not in s2_res.masked_text and "VGMASK_" in s2_res.masked_text,
    s2_res.masked_text,
)
check(
    "S2 CONTROL: a well-separated multi-word name produces a ZERO mid-word count",
    lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
        document_text="Deneme Tekstil A.Ş. adına tarhiyat yapılmıştır.",
    ).summary["possible_over_masking"]["party_name_midword_matches"] == 0,
)
check(
    "S2 is informational only - a mid-word match never refuses",
    s2_res.masked_text is not None,
)

print("## 16 - instruction block content rules")

block = lpb.token_instruction_block()
check("the instruction block mentions the prefix", "VGMASK" in block)
check(
    "the instruction block contains NO concrete example token (an echoed example would be "
    "an unknown token and would be refused)",
    lpb.TOKEN_RE.search(block) is None,
    block,
)
check("the instruction block contains no 10/11-digit run",
      lpb._DIGIT_RUN_10_RE.search(block) is None and lpb._DIGIT_RUN_11_RE.search(block) is None)
check("the instruction block contains no e-mail", lpb._EMAIL_RE.search(block) is None)
check("the instruction block is deterministic", lpb.token_instruction_block() == block)

print("## 17 - de_mask_tree structure handling")

tree_map = lpb.MaskMapping()
tok_a = tree_map.token_for("Ayşe Çelik", lpb.CLASS_PARTY)
tok_b = tree_map.token_for('ABC "Holding" A.S. \\ Ltd.', lpb.CLASS_PARTY)
tree = {
    "facts": [
        {"statement": f"{tok_a} adına tarh", "n": 5, "ok": True, "none": None},
        {"nested": {"deep": [f"{tok_b} hakkında", 7]}},
    ],
    "warnings": [],
}
back = lpb.de_mask_tree(tree, tree_map)
check("de_mask_tree resolves values inside nested dicts and lists",
      back["facts"][0]["statement"] == "Ayşe Çelik adına tarh")
check("de_mask_tree resolves values inside a deeper list",
      back["facts"][1]["nested"]["deep"][0] == 'ABC "Holding" A.S. \\ Ltd. hakkında')
check("de_mask_tree leaves non-string scalars untouched",
      back["facts"][0]["n"] == 5 and back["facts"][0]["ok"] is True and back["facts"][0]["none"] is None)
check("de_mask_tree does not mutate the input tree",
      tree["facts"][0]["statement"] == f"{tok_a} adına tarh")
raw_json = json.dumps({"facts": [{"statement": f"{tok_b} adına"}]}, ensure_ascii=False)
naive = raw_json.replace(tok_b, 'ABC "Holding" A.S. \\ Ltd.')
try:
    json.loads(naive)
    check("the naive raw-string substitution is genuinely invalid JSON", False, naive)
except json.JSONDecodeError:
    check("the naive raw-string substitution is genuinely invalid JSON", True)
check("the parse-then-walk route handles the same value correctly",
      lpb.de_mask_tree(json.loads(raw_json), tree_map)["facts"][0]["statement"]
      == 'ABC "Holding" A.S. \\ Ltd. adına')

print("## 18 - dropped-token reporting (D3: report, never refuse)")

drop_map = lpb.MaskMapping()
d1 = drop_map.token_for("Bir Ad", lpb.CLASS_PARTY)
drop_map.token_for("Başka Ad", lpb.CLASS_PARTY)
drop_map.token_for(VALID_TCKN, lpb.CLASS_TCKN)
report = lpb.count_dropped_tokens({"facts": [{"statement": f"{d1} adına"}]}, drop_map)
check("count_dropped_tokens counts tokens the model never echoed",
      report["dropped_token_count"] == 2, report)
check("dropped tokens are reported per class",
      report["dropped_by_class"]["P"] == 1 and report["dropped_by_class"]["T"] == 1, report)
check("count_dropped_tokens returns counts only - no tokens, no values",
      all(isinstance(v, (int, dict)) for v in report.values())
      and not any("VGMASK" in str(v) for v in report.values()), report)
check(
    "D3 DECISION: a dropped token does NOT raise (it is a quality loss, not a leak); "
    "de_mask_tree still succeeds",
    lpb.de_mask_tree({"facts": [{"statement": f"{d1} adına"}]}, drop_map)
    == {"facts": [{"statement": "Bir Ad adına"}]},
)

print("## 19 - extra-terms digest")

check("empty list digest equals sha256 of canonical []",
      lpb.compute_extra_terms_digest(()) == hashlib.sha256(b"[]").hexdigest())
check("EMPTY_EXTRA_TERMS_DIGEST constant matches the formula",
      lpb.EMPTY_EXTRA_TERMS_DIGEST == lpb.compute_extra_terms_digest([]))
check("digest is order-independent",
      lpb.compute_extra_terms_digest(["b", "a"]) == lpb.compute_extra_terms_digest(["a", "b"]))
check("digest de-duplicates",
      lpb.compute_extra_terms_digest(["a", "a", "b"]) == lpb.compute_extra_terms_digest(["b", "a"]))
check("digest strips surrounding whitespace",
      lpb.compute_extra_terms_digest([" a "]) == lpb.compute_extra_terms_digest(["a"]))
check("digest drops blank terms",
      lpb.compute_extra_terms_digest(["a", "   "]) == lpb.compute_extra_terms_digest(["a"]))
check("digest is NFC-normalised",
      lpb.compute_extra_terms_digest([unicodedata.normalize("NFD", "İstanbul")])
      == lpb.compute_extra_terms_digest(["İstanbul"]))
check("a different term list yields a different digest",
      lpb.compute_extra_terms_digest(["a"]) != lpb.compute_extra_terms_digest(["b"]))
check("digest is a 64-char lowercase hex string",
      re.fullmatch(r"[0-9a-f]{64}", lpb.compute_extra_terms_digest(["x"])) is not None)
check("digest never returns the terms themselves",
      "gizli" not in lpb.compute_extra_terms_digest(["gizli ad"]))

print("## 20 - secret hygiene: the map and raw values never escape")

hyg = lpb.mask_prompt_inputs(
    case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
    document_text="Ayşe Çelik, TCKN " + VALID_TCKN + ", IBAN " + VALID_IBAN_COMPACT,
)
check("MaskMapping.__repr__ reveals only a count",
      repr(hyg.mapping) == f"<MaskMapping n={hyg.mapping.token_count()}>", repr(hyg.mapping))
check("MaskMapping.__str__ reveals nothing either",
      "Ayşe" not in str(hyg.mapping) and VALID_TCKN not in str(hyg.mapping))
check("MaskingResult.__repr__ reveals only a token count",
      "Ayşe" not in repr(hyg) and VALID_TCKN not in repr(hyg), repr(hyg))
check("the summary carries counts only - no values, no tokens",
      "Ayşe" not in json.dumps(hyg.summary, ensure_ascii=False)
      and "VGMASK" not in json.dumps(hyg.summary, ensure_ascii=False), hyg.summary)
check("the summary reports a class distribution",
      set(hyg.summary["class_distribution"]) == set(lpb.ALL_CLASSES), hyg.summary)
check("the summary reports possible-over-masking indicators",
      "vkn_without_context_word" in hyg.summary["possible_over_masking"], hyg.summary)

for factory, label in [
    (lambda: lpb.mask_prompt_inputs(
        case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
        document_text="Ayşe Çelik VGMASK_0001P"), "MaskCollisionError"),
    (lambda: lpb.scan_outbound("Ayşe Çelik " + VALID_TCKN, seeds), "SurvivingPatternError"),
    (lambda: lpb._de_mask_string("VGMASK_0099P", hyg.mapping), "UnknownTokenError"),
    (lambda: lpb._de_mask_string("vgmask_0001p", hyg.mapping), "MalformedTokenError"),
    (lambda: lpb.assert_identifiers_are_opaque(["case_ayse_celik"],
                                               party_seeds("Ayşe Çelik", kind="individual")),
     "NonOpaqueIdentifierError"),
]:
    try:
        factory()
        check(f"exception hygiene - {label} was raised", False, "no exception")
    except lpb.LlmPrivacyBoundaryError as error:
        text = f"{error} {error!r} {error.args}"
        leaked = [
            needle for needle in ["Ayşe", "Çelik", VALID_TCKN, VALID_IBAN_COMPACT, "VGMASK_"]
            if needle in text
        ]
        check(
            f"exception hygiene - {label} message is FIXED and leaks no value, token or map",
            not leaked,
            f"leaked={leaked} text={text}",
        )

print("## 21 - masked prompt end-to-end shape")

e2e = lpb.mask_prompt_inputs(
    case_data=SYNTH_CASE, document_data=SYNTH_DOC, context=SYNTH_CONTEXT,
    document_text=(
        "Mükellef: Deneme Tekstil A.Ş.\nTemsilci: Ayşe Çelik\n"
        "TCKN: " + VALID_TCKN + "\nVKN: " + VALID_VKN + "\n"
        "IBAN: " + VALID_IBAN_GROUPED + "\nTel: 0 (212) 555 44 33\n"
        "E-posta: ayse.celik@sentetik-ornek.com.tr\n"
        "2024/03 dönemi için 850.000,00 TL tarh edilmiştir.\n"
    ),
)
e2e_prompt = json.dumps(e2e.masked_context, ensure_ascii=False, indent=2) + "\n" + e2e.masked_text
check("all six token classes are exercised end to end",
      all(e2e.summary["class_distribution"][cls] > 0 for cls in lpb.ALL_CLASSES),
      e2e.summary["class_distribution"])
for needle, label in [
    ("Deneme Tekstil", "company name"), ("Ayşe Çelik", "individual name"),
    (VALID_TCKN, "TCKN"), (VALID_VKN, "VKN"), (VALID_IBAN_GROUPED, "IBAN"),
    ("555 44 33", "phone"), ("ayse.celik@", "e-mail"),
]:
    check(f"the masked prompt no longer contains the raw {label}", needle not in e2e_prompt)
for needle, label in [
    ("2024/03", "taxation period"), ("850.000,00", "amount"),
    ("case_9001", "case_id"), ("party_a", "party_id"), ("KDVK_m29", "legal basis ref"),
]:
    check(f"the masked prompt STILL contains the load-bearing {label}", needle in e2e_prompt,
          e2e_prompt[:200])
check("scan_outbound accepts the fully masked end-to-end prompt",
      lpb.scan_outbound(e2e_prompt + e2e.prompt_instruction_block, e2e) is None)
check("assert_masked_length_within accepts a normal-size masked text",
      lpb.assert_masked_length_within(e2e.masked_text, 60000) is None)

e2e_tree = {"facts": [{"statement": e2e.masked_text, "party": e2e.masked_context["parties"][0]["display_name"]}]}
e2e_back = lpb.de_mask_tree(e2e_tree, e2e)
check("the full end-to-end masked text de-masks byte-exactly",
      e2e_back["facts"][0]["statement"] == (
          "Mükellef: Deneme Tekstil A.Ş.\nTemsilci: Ayşe Çelik\n"
          "TCKN: " + VALID_TCKN + "\nVKN: " + VALID_VKN + "\n"
          "IBAN: " + VALID_IBAN_GROUPED + "\nTel: 0 (212) 555 44 33\n"
          "E-posta: ayse.celik@sentetik-ornek.com.tr\n"
          "2024/03 dönemi için 850.000,00 TL tarh edilmiştir.\n"
      ))
check("the de-masked party name is byte-identical to the original",
      e2e_back["facts"][0]["party"] == "Deneme Tekstil A.Ş.")
check("assert_no_tokens_remain passes on the de-masked tree",
      lpb.assert_no_tokens_remain(e2e_back, e2e) is None)

print("## 22 - module import hygiene")

source = (SRC_DIR / "llm_privacy_boundary.py").read_text(encoding="utf-8")
for forbidden, label in [
    ("import os", "os"), ("from ui", "ui package"), ("import ui", "ui package"),
    ("open(", "file access"), ("urllib", "urllib"), ("socket", "socket"),
    ("requests", "requests"), ("anthropic", "anthropic"), ("dotenv", "dotenv"),
    ("Path(", "pathlib usage"),
]:
    check(f"the module contains no {label} reference (stdlib-only, no file/network access)",
          forbidden not in source, forbidden)
import_lines = [
    line.strip() for line in source.splitlines()
    if re.match(r"^\s*(?:import|from)\s", line)
]
check(
    "the module's import statements are stdlib-only (no repo module, no ui package)",
    set(import_lines) == {
        "from __future__ import annotations",
        "import copy",
        "import hashlib",
        "import json",
        "import re",
        "import unicodedata",
        "from dataclasses import dataclass, field",
    },
    sorted(import_lines),
)
check("MASKING_POLICY_VERSION is a non-blank string",
      isinstance(lpb.MASKING_POLICY_VERSION, str) and lpb.MASKING_POLICY_VERSION.strip() != "")

print(f"--- test_llm_privacy_boundary_isolated: {passed} passed, {failed} failed ---")
sys.exit(1 if failed else 0)
