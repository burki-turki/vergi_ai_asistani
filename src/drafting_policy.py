# ============================================================
# VERGİ AI - DRAFTING POLICY V1
#
# Saf deterministik sabitler, taksonomiler, parmak izi (fingerprint)
# ve bağımsız serbest-metin güvenlik primitifleri. Bu modül HİÇBİR
# LLM/network çağrısı yapmaz; agent, discovery, engine ve validator'ın
# import ettiği ORTAK, düşük seviyeli katmandır.
#
# ROW 14 YASAK-İFADE SÖZLÜĞÜNÜN KÖRLEMESİNE KOPYALANMAMASI:
# Row 9/13/14'ün "iptal edilmelidir"/"hukuka aykırıdır"/"kabul
# edilmelidir" gibi ifadeleri YASAKLAMASININ nedeni, o katmanların
# NÖTR/analitik metin üretmesi gerekliliğidir. Drafting'in amacı ise
# müvekkilin pozisyonunu SAVUNMAKTIR - bu ifadeler bir dilekçenin
# "talep" bölümünde NORMAL içeriktir. Bu yüzden bu modül iki AYRI
# sözlük tanımlar:
#   UNIVERSAL_FORBIDDEN_PHRASES -> HER bağlamda yasak (dava sonucu
#     tahmini/garantisi - Row 14'ten aynen miras, outcome-guarantee
#     dili evrensel olarak sorunludur).
#   CONDITIONAL_ADVOCACY_PHRASES -> YALNIZ section_type='request' VE
#     metin confirmed bir kaynağa/lawyer_provided_text'e dayanan bir
#     savunma ifadesiyken İZİN VERİLİR (Row 9'dan aynen miras, ama
#     Row 9'un kendi dosyası/listesi MUTATE EDİLMEZ - yalnız import
#     edilip Row 15'in kendi bağlamsal kapısı eklenir).
# ============================================================

import hashlib
import json
import re

from timeline_consolidation_policy import normalize_text_tr as _canonical_normalize_text_tr
from issue_spotting_validator import FORBIDDEN_PHRASES as _ROW9_ADVOCACY_PHRASES
from risk_strategy_policy import FORBIDDEN_PHRASE_FRAGMENTS as _ROW14_OUTCOME_PHRASES


# ============================================================
# DRAFT INTENT TYPE (V1 - 5 SABİT DEĞER)
# ============================================================

DRAFT_INTENT_TYPES = {
    "initial_lawsuit_petition",
    "response_petition",
    "statement_on_merits",
    "appeal_petition",
    "supplementary_petition",
}

APPEAL_LEVELS = {"istinaf", "temyiz"}


# ============================================================
# SELECTION SCOPE (3 DEĞER - eksik seçim != bilinçli dışlama)
# ============================================================

SELECTION_SCOPES = {
    "selection_not_provided",
    "selected",
    "not_selected_by_lawyer",
}


# ============================================================
# EXECUTION STATE (drafting'e özgü, Row 14'ün "identified"
# adlarını DOĞRUDAN KOPYALAMAZ - "no_section_produced" bu row'un
# kendi terminolojisidir)
# ============================================================

EXECUTION_STATES = {
    "analysis_not_run",
    "blocked_missing_input",
    "blocked_upstream_not_run",
    "analysis_failed",
    "no_section_produced",
    "analysis_partial",
    "analysis_completed",
}

# Bu execution_state'lerde produced_section_count KESİN OLARAK
# sıfır olmalıdır. analysis_partial BİLEREK bu kümede DEĞİLDİR -
# tüm adaylar reddedilmişse (madde 4) analysis_partial +
# produced_section_count=0 GEÇERLİDİR.
ZERO_SECTION_EXECUTION_STATES = {
    "analysis_not_run",
    "blocked_missing_input",
    "blocked_upstream_not_run",
    "analysis_failed",
    "no_section_produced",
}

BLOCK_REASONS = {
    "no_confirmed_source_for_issue",
    "blocked_missing_lawyer_input",
    "source_hard_denied",
    "all_candidate_sources_rejected",
}


# ============================================================
# 11 REFERANS ALANI (9 temel + 2 opsiyonel: risk/strategy)
# ============================================================

REF_FIELDS = (
    "source_fact_ids",
    "source_timeline_event_ids",
    "source_deadline_ids",
    "source_legal_research_ids",
    "source_case_law_ids",
    "source_evidence_candidate_ids",
    "source_claim_ids",
    "source_counterargument_ids",
    "source_rebuttal_ids",
    "source_risk_ids",
    "source_strategy_ids",
)

# Mevcudiyeti (canonical dosya varlığı) case'e göre değişebilecek
# opsiyonel referans alanları.
OPTIONAL_REF_FIELDS = ("source_evidence_candidate_ids", "source_risk_ids", "source_strategy_ids")


# ============================================================
# SECTION TYPE / RENDERING MODE / NOTE TYPE / SUGGESTION TYPE
# ============================================================

SECTION_TYPES = {
    "facts_summary",
    "legal_basis",
    "argument_summary",
    "request",
    "procedural_history",
}

# YALNIZ bu section_type'larda avukatın AÇIK ÜRETİM YETKİSİ
# ZORUNLUDUR (talep yetkisi ayrımı - madde G/7 ve remediation madde 3).
REQUEST_AUTHORITY_REQUIRED_SECTION_TYPES = {"request"}

# 4 opsiyonel/atıf-yalnız referans alanı - HİÇBİR ZAMAN "direct"
# sayılmaz (case_law/legal_research/risk/strategy hiçbir zaman
# "onaylı olgu" değildir, her zaman flagged notla sunulur).
ALWAYS_FLAGGED_REF_FIELDS = {
    "source_legal_research_ids", "source_case_law_ids", "source_risk_ids", "source_strategy_ids",
}


def is_ref_direct(ref, section_issue_ids, direct_lookup):
    """
    direct_lookup: {(source_field, issue_id): set(direct_ids)} - yalnız
    fact/timeline/deadline/evidence/claim/counterargument/rebuttal için
    anlamlıdır. ALWAYS_FLAGGED_REF_FIELDS içindeki alanlar hiçbir zaman
    direct DEĞİLDİR.
    """

    if ref["source_field"] in ALWAYS_FLAGGED_REF_FIELDS:

        return False

    for issue_id in section_issue_ids:

        if ref["source_id"] in direct_lookup.get((ref["source_field"], issue_id), set()):

            return True

    return False


def is_valid_request_input(request_input):
    """
    Q2 yetkilendirmesi için request_input'un YAPISAL geçerliliği (madde 4,
    Targeted Guard Hardening). Yalnız dict'in truthy olması YETMEZ:
      - dict olmalı, şemanın izin verdiği İKİ alan DIŞINDA alan taşımamalı
        (additionalProperties:false ile tutarlı - kod seviyesinde bağımsız
        yeniden doğrulama, şemaya güvenmeden).
      - request_type: string olmalı VE trim sonrası boş OLMAMALI (mevcut
        şemanın kendi alan tanımına - non-empty string - uygunluk; Row 15
        için YENİ bir kapalı request_type sözlüğü İCAT EDİLMEDİ, bu kapsam
        dışıdır).
      - request_text: string olmalı VE trim sonrası boş OLMAMALI (yalnız
        whitespace içeren bir metin de GEÇERSİZ sayılır).
    """

    if not isinstance(request_input, dict):

        return False

    if set(request_input.keys()) - {"request_type", "request_text"}:

        return False

    request_type = request_input.get("request_type")

    request_text = request_input.get("request_text")

    if not isinstance(request_type, str) or not request_type.strip():

        return False

    if not isinstance(request_text, str) or not request_text.strip():

        return False

    return True


def has_valid_lawyer_text(text):
    """
    lawyer_provided_text için aynı disiplin: yalnız whitespace içeren bir
    metin GEÇERLİ SAYILMAZ (madde 4 - lawyer_provided_text genel bir
    güvenlik istisnasına dönüşmemeli).
    """

    return isinstance(text, str) and bool(text.strip())


def compute_request_authorization(request_input, lawyer_provided_text):
    """
    İKİ AYRI SORU, KARIŞTIRILMAZ:
      Q1 (dayanak var mı?)     -> is_grounded_advocacy (confirmed argüman
                                    VEYA avukat girdisi de yeterlidir).
      Q2 (avukat AÇIKÇA bu ÜRETİMİ istedi mi?) -> BU fonksiyon, YALNIZ
                                    YAPISAL OLARAK GEÇERLİ request_input
                                    VEYA GEÇERLİ (boş/whitespace olmayan)
                                    lawyer_provided_text ile cevaplanabilir.
                                    Confirmed argument/risk/strategy TEK
                                    BAŞINA Q2'ye ASLA EVET cevabı VEREMEZ -
                                    bir hukuki iddianın onaylanmış olması,
                                    avukatın bir TALEP SECTION'I
                                    üretilmesini istediği anlamına GELMEZ.
    """

    return is_valid_request_input(request_input) or has_valid_lawyer_text(lawyer_provided_text)

RENDERING_MODES = {"direct_quote", "paraphrase", "citation_only"}

NOTE_TYPES = {
    "disputed_content",
    "needs_review_flagged",
    "agent_suggested_citation_only",
    "gap_note",
}

SUGGESTION_TYPES = {
    "missing_source_grounding",
    "unaddressed_issue",
    "request_input_needed",
    "additional_review_needed",
}

REASON_CODES = {
    "explicit_textual_match",
    "lawyer_selected_source",
    "deterministic_gap_note",
    "general_contextual_relevance",
}


# ============================================================
# JSON / HASH HELPERS (Row 13/14 ile birebir aynı desen)
# ============================================================

def canonical_dumps(value):

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_of(value):

    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


def reference_set_signature(record):

    return {field: sorted(record.get(field, []) or []) for field in REF_FIELDS}


def collect_ref_ids(record):

    ids = set()

    for field in REF_FIELDS:

        ids |= set(record.get(field, []) or [])

    return ids


# ============================================================
# İKİ AYRI PARMAK İZİ AİLESİ (Row 13/14 ile aynı ilke):
#   DEDUP  -> yalnız TEK ÇALIŞTIRMA içi duplicate tespiti; serbest
#     metni (section_text/grounded_explanation) DIŞLAR.
#   CONTENT -> Layer B carry-forward'ın "insan TAM OLARAK NEYİ
#     onayladı" sorusuna cevap verir; serbest metni VE referans
#     edilen kaynakların KENDİ İÇERİK/DURUM imzasını (source_
#     signature - engine tarafından hesaplanıp parametre olarak
#     verilir) VE avukat girdisi hash'ini VE generation_policy_
#     version'ı ZORUNLU OLARAK DAHİL EDER - aksi halde bir önceki
#     'confirmed' durumu, kaynağı/avukat girdisi değişmiş bir
#     section'a sessizce taşınabilir (madde 6, addendum).
# ============================================================

def compute_section_dedup_fingerprint(section, ref_field_id_pairs):

    return sha256_of(
        {
            "kind": "section_dedup",
            "section_type": section["section_type"],
            "source_issue_ids": sorted(section.get("source_issue_ids", [])),
            "ref_field_id_pairs": sorted(ref_field_id_pairs),
        }
    )


def compute_section_content_fingerprint(
    section, ref_signature_full, source_content_signature, lawyer_input_hash, generation_policy_version,
):

    return sha256_of(
        {
            "kind": "section_content",
            "section_type": section["section_type"],
            "source_issue_ids": sorted(section.get("source_issue_ids", [])),
            "section_text": section.get("section_text"),
            "ref_signature_full": sorted(ref_signature_full),
            "source_content_signature": sorted(source_content_signature),
            "lawyer_input_hash": lawyer_input_hash,
            "generation_policy_version": generation_policy_version,
        }
    )


def compute_suggestion_dedup_fingerprint(suggestion):

    return sha256_of(
        {
            "kind": "suggestion_dedup",
            "suggestion_type": suggestion["suggestion_type"],
            "source_issue_id": suggestion.get("source_issue_id"),
            "related_reference_ids": sorted(suggestion.get("related_reference_ids", []) or []),
        }
    )


def compute_suggestion_content_fingerprint(suggestion):

    return sha256_of(
        {
            "kind": "suggestion_content",
            "suggestion_type": suggestion["suggestion_type"],
            "source_issue_id": suggestion.get("source_issue_id"),
            "related_reference_ids": sorted(suggestion.get("related_reference_ids", []) or []),
            "reason_code": suggestion.get("reason_code"),
            "grounded_explanation": suggestion.get("grounded_explanation"),
        }
    )


def compute_lawyer_input_hash(lawyer_input):
    """
    lawyer_input tamamen boş/varsayılan ise (hiçbir avukat girdisi
    sağlanmamış) None döner (eksik <> açıkça sağlanmış boş anlam
    farkı korunur - madde C).
    """

    is_empty = (
        lawyer_input.get("draft_intent_type") is None
        and lawyer_input.get("appeal_level") is None
        and lawyer_input.get("selected_issue_ids") is None
        and not any(lawyer_input.get("selected_source_ids", {}).values())
        and lawyer_input.get("request_input") is None
        and lawyer_input.get("lawyer_provided_text") is None
    )

    if is_empty:

        return None

    return sha256_of(lawyer_input)


# ============================================================
# DETERMİNİSTİK GAP-NOTE TEMPLATE (draft_review_notes.gap_note)
# ============================================================

GAP_NOTE_TEMPLATE = (
    "Bu issue için '{block_reason}' nedeniyle üretim gerçekleştirilememiştir; "
    "bu bir hukuki sonuç veya olgu tespiti değildir, yalnız bir süreç kaydıdır."
)


def render_gap_note(block_reason):

    if block_reason not in BLOCK_REASONS:

        raise ValueError(f"Bilinmeyen block_reason: {block_reason}")

    return GAP_NOTE_TEMPLATE.format(block_reason=block_reason)


DISPUTED_CONTENT_TEMPLATE = (
    "Bu issue ile ilişkili '{source_id}' zaman çizelgesi olayı '{state}' "
    "durumundadır; bu nedenle gövde metnine dahil edilmemiştir, yalnız bu "
    "inceleme notu olarak kaydedilmiştir."
)


def render_disputed_content_note(source_id, state):

    return DISPUTED_CONTENT_TEMPLATE.format(source_id=source_id, state=state)


AGENT_SUGGESTED_CITATION_TEMPLATE = (
    "Bu issue için '{source_id}' araştırma kaydı yalnız bir öneri "
    "(agent_suggested) niteliğindedir; resmi bir hukuki dayanak veya doğrudan "
    "alıntı olarak KULLANILAMAZ, yalnız bu inceleme notuyla izlenebilir."
)


def render_agent_suggested_citation_note(source_id):

    return AGENT_SUGGESTED_CITATION_TEMPLATE.format(source_id=source_id)


NEEDS_REVIEW_FLAGGED_TEMPLATE = (
    "'{section_id}' section'ı '{source_field}:{source_id}' kaynağına "
    "dayanmaktadır; bu kaynak henüz nihai olarak incelenmemiş/doğrulanmamıştır "
    "(flagged). İlgili section metni bu belirsizliği açıkça belirtmelidir."
)


def render_needs_review_flagged_note(section_id, source_field, source_id):

    return NEEDS_REVIEW_FLAGGED_TEMPLATE.format(
        section_id=section_id, source_field=source_field, source_id=source_id,
    )


# ============================================================
# BAĞLAMSAL YASAK-İFADE POLİTİKASI (Row 15'e özgü)
# ============================================================

normalize_text_tr = _canonical_normalize_text_tr

UNIVERSAL_FORBIDDEN_PHRASES = tuple(sorted(set(_ROW14_OUTCOME_PHRASES)))

CONDITIONAL_ADVOCACY_PHRASES = tuple(sorted(set(_ROW9_ADVOCACY_PHRASES)))

ID_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{6,}")

QUOTE_PATTERN = re.compile(r"[\"“”]([^\"“”]{3,})[\"“”]")

DATE_TOKEN_PATTERN = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")

AMOUNT_TOKEN_PATTERN = re.compile(r"\b\d[\d.,]{2,}\s?(?:TL|TRY|USD|EUR)\b")

DURATION_TOKEN_PATTERN = re.compile(r"\b\d{1,4}\s?(?:gün|gun|hafta|ay|yıl|yil)\b", re.IGNORECASE)

BARE_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")


# ============================================================
# SONUÇ-GARANTİSİ KALIP AİLESİ (madde 3, Targeted Guard Hardening)
#
# UNIVERSAL_FORBIDDEN_PHRASES (Row 14'ten miras) yalnız SABİT, TAM
# ifadeleri (ör. "kesin olarak kazanilacaktir") substring olarak
# yakalar - "kesinlikle kazanilacaktir" gibi FARKLI bir kesinlik-
# zarfı + FARKLI bir fiil çekimi kombinasyonunu KAÇIRIR. Bu bölüm,
# KAPALI, AÇIKÇA TANIMLI iki listeyi (kesinlik zarfları + kazan/kaybet
# fiil kökleri) YAKIN MESAFEDE (aynı cümle içinde, ~40 karakter
# penceresi) birlikte arayan bir REGEX AİLESİ ekler - yeni bir genel
# semantik değerlendirme motoru DEĞİLDİR, yalnız BELİRGİN çekim/yazım
# varyantlarını kapsayan dar bir kalıp genişletmesidir.
#
# "kazan" kökü (?!c) ile KASITLI OLARAK "kazanç/kazancı" (gelir/kâr
# anlamına gelen İSİM) ile ÇAKIŞMAZ - yalnız FİİL çekimlerini
# (kazanir, kazandi, kazanacak, kazanilir, kazanilacaktir, kazanan...)
# yakalar. "kaybet" kökü Türkçe ünsüz yumuşaması nedeniyle "kayb(et|ed)"
# olarak genişletilmiştir (kaybedecek, kaybedildi, kaybedilir).
#
# Meşru taraf iddiası/talep dili ("işlemin iptalini talep ediyoruz")
# bu kalıplarla HİÇBİR ORTAK KÖK TAŞIMADIĞI için ETKİLENMEZ.
# ============================================================

OUTCOME_CERTAINTY_MARKERS = (
    "kesinlikle",
    "kesin olarak",
    "kesin bir sekilde",
    "mutlaka",
    "suphesiz",
    "hic suphesiz",
    "yuzde yuz",
    "istisnasiz",
)

_OUTCOME_MARKER_ALTERNATION = "|".join(re.escape(marker) for marker in OUTCOME_CERTAINTY_MARKERS)

_OUTCOME_VERB_STEM = r"(?:kazan(?!c)[a-z]*|kayb(?:et|ed)[a-z]*)"

OUTCOME_GUARANTEE_PATTERN = re.compile(
    rf"\b(?:{_OUTCOME_MARKER_ALTERNATION})\b[^.!?]{{0,40}}\b{_OUTCOME_VERB_STEM}\b"
    rf"|\b{_OUTCOME_VERB_STEM}\b[^.!?]{{0,40}}\b(?:{_OUTCOME_MARKER_ALTERNATION})\b"
)


def find_outcome_guarantee_matches(text):
    """
    Metnin NORMALİZE edilmiş halinde, bir kesinlik-zarfı ile bir kazan/
    kaybet fiil çekiminin aynı cümle içinde (nokta/ünlem/soru işaretiyle
    sınırlı, ~40 karakter penceresinde) birlikte geçtiği yerleri bulur.
    """

    if not text:

        return []

    normalized = normalize_text_tr(text)

    return [match.group(0) for match in OUTCOME_GUARANTEE_PATTERN.finditer(normalized)]


def check_forbidden_phrases_context(record_id, text, section_type, is_grounded_advocacy):
    """
    Universal (dava sonucu tahmini/garantisi) HER ZAMAN yasaktır.
    Conditional (savunma/talep dili, ör. 'iptal edilmelidir') YALNIZ
    section_type='request' VE is_grounded_advocacy=True iken izinlidir
    (confirmed bir claim/counterargument/rebuttal'ın paraphrase'i veya
    avukatın kendi lawyer_provided_text'i).
    """

    errors = []

    if not text:

        return errors

    normalized = normalize_text_tr(text)

    for phrase in UNIVERSAL_FORBIDDEN_PHRASES:

        if normalize_text_tr(phrase) in normalized:

            errors.append(
                f"{record_id}: metin evrensel yasaklı dava sonucu/garanti "
                f"ifadesi içeriyor ('{phrase}')."
            )

    for outcome_match in find_outcome_guarantee_matches(text):

        errors.append(
            f"{record_id}: metin kesinlik-zarfı + kazan/kaybet fiil çekimi "
            f"kombinasyonu içeriyor (kalıp: '{outcome_match}') - dava sonucu "
            "garantisi/tahmini HİÇBİR bağlamda izinli değildir."
        )

    allow_conditional = (section_type == "request" and is_grounded_advocacy is True)

    if not allow_conditional:

        for phrase in CONDITIONAL_ADVOCACY_PHRASES:

            if normalize_text_tr(phrase) in normalized:

                errors.append(
                    f"{record_id}: metin yalnız grounded 'request' section'ında "
                    f"izinli bir savunma ifadesi içeriyor ('{phrase}') ama bu "
                    "bağlamda (section_type/grounding) izinli değil."
                )

    return errors


def extract_quoted_spans(text):

    return [match.group(1) for match in QUOTE_PATTERN.finditer(text)]


def find_unverified_quotes(text, citable_texts):

    unverified = []

    for span in extract_quoted_spans(text):

        if not any(span in source for source in citable_texts):

            unverified.append(span)

    return unverified


def find_smuggled_ids(text, declared_ids, all_known_ids):

    declared = set(declared_ids)

    smuggled = []

    for token in ID_TOKEN_PATTERN.findall(text):

        if token in all_known_ids and token not in declared:

            smuggled.append(token)

    return smuggled


# ============================================================
# ID-BİÇİMLİ TOKEN TESPİTİ (madde 2, Targeted Guard Hardening)
#
# find_smuggled_ids yalnız GERÇEK, bilinen ama beyan edilmemiş ID'leri
# yakalar - TAMAMEN UYDURMA (canonical'da hiç var olmayan) bir ID
# BİÇİMLİ token'ı KAÇIRIR (all_known_ids'te olmadığı için 'token in
# all_known_ids' koşulu hiç tetiklenmez).
#
# Bu bölüm, REPOSITORY'DEKİ GERÇEK canonical ID üretim kalıplarını
# (aşağıdaki prefix listesi, ilgili engine/agent dosyalarından f-string
# üretim satırları doğrudan okunarak doğrulanmıştır) esas alan DAR bir
# "ID biçimli token" regex'i tanımlar, ve her eşleşen token'ı ÜÇ AYRI
# kategoriye ayırır:
#   - declared_ids içinde: sorun yok.
#   - all_known_ids içinde AMA declared_ids'te yok: 'smuggled' (gerçek
#     bir ID'dir; ya başka bir issue'ya aittir ya da bu kayıt için
#     beyan edilmemiştir - ikisi de aynı köktedir: "bilinen ama bu
#     kayda izinli/beyanlı değil").
#   - all_known_ids içinde HİÇ YOK: 'fabricated' (ID BİÇİMİNDE ama
#     canonical'da karşılığı olmayan, TAMAMEN UYDURULMUŞ).
#
# Prefix kaynakları (doğrudan kod okumasıyla doğrulandı):
#   fact_...                  -> fact_extraction_engine.py (Row 4)
#   timeline_event_...        -> timeline_engine.py (Row 7)
#   deadline_...              -> deadline_engine.py (Row 8)
#   research_...              -> legal_research_engine.py (Row 10)
#   case_law_decision_...     -> case_law_policy.py (Row 11)
#   evidence_candidate_...    -> evidence_agent.py (Row 12)
#   argument_claim_...        -> argument_agent.py (Row 13)
#   argument_counter_...      -> argument_agent.py (Row 13)
#   argument_rebuttal_...     -> argument_agent.py (Row 13)
#   risk_...                  -> risk_strategy_engine.py (Row 14,
#                                 risk_gap_/risk_identified_ alt-türleri)
#   strategy_...              -> risk_strategy_engine.py (Row 14)
#   issue_...                 -> issue_spotting_engine.py (Row 9)
#   draft_section_...         -> drafting_agent.py (Row 15, kendi)
#
# Bu prefix+alt çizgi gereksinimi (normal Türkçe metinde kelimeler
# ARALARINDA BOŞLUK taşır, alt çizgi taşımaz) yanlış-pozitif riskini
# düşük tutar; ID_TOKEN_PATTERN'in (genel 6+ karakter) YERİNE değil,
# ONA EK bağımsız bir kontrol katmanıdır.
# ============================================================

ID_SHAPE_PATTERN = re.compile(
    r"\b(?:"
    r"fact_|timeline_event_|deadline_|research_|case_law_decision_|"
    r"evidence_candidate_|argument_claim_|argument_counter_|argument_rebuttal_|"
    r"risk_|strategy_|issue_|draft_section_"
    r")[A-Za-z0-9_]+\b"
)


def find_id_reference_issues(text, declared_ids, all_known_ids):
    """
    Döner: {"fabricated": [...], "smuggled": [...]} - iki liste de
    boşsa metinde sorunlu bir ID-biçimli referans YOKTUR. Declared_ids
    içindeki token'lar (gerçek, bu kayıt için izinli referanslar)
    HİÇBİR listeye girmez - pozitif durum ayrı test edilir.
    """

    if not text:

        return {"fabricated": [], "smuggled": []}

    declared = set(declared_ids)

    fabricated = []

    smuggled = []

    seen = set()

    for match in ID_SHAPE_PATTERN.finditer(text):

        token = match.group(0)

        if token in seen:

            continue

        seen.add(token)

        if token in declared:

            continue

        if token in all_known_ids:

            smuggled.append(token)

        else:

            fabricated.append(token)

    return {"fabricated": fabricated, "smuggled": smuggled}


def find_unsupported_numeric_tokens(text, citable_texts):

    unsupported = []

    for pattern in (DATE_TOKEN_PATTERN, AMOUNT_TOKEN_PATTERN, DURATION_TOKEN_PATTERN, BARE_YEAR_PATTERN):

        for match in pattern.finditer(text):

            token = match.group(0)

            if not any(token in source for source in citable_texts):

                unsupported.append(token)

    return unsupported


# ============================================================
# BELİRSİZLİK SUNUMU (contains_unreviewed_source TEK BAŞINA
# YETERLİ DEĞİLDİR) - flagged bir kaynağa dayanan HER referansın
# kendi claim_span'i, section_text içinde GERÇEKTEN var olmalı VE
# o claim_span'in KENDİSİ bir belirsizlik ifadesi taşımalıdır.
# Metnin başka bir yerindeki genel bir uyarı, farklı bir flagged
# referansın kesin dille yazılmasını MEŞRULAŞTIRMAZ - kontrol HER
# ref için AYRI AYRI yapılır.
# ============================================================

HEDGE_PHRASES = (
    "dogrulanmamis",
    "henuz incelenmemis",
    "inceleme bekleyen",
    "belirsizdir",
    "kesinlesmemis",
    "onaylanmamis",
    "tespit edilen olasi",
    "ileri surulen ancak henuz incelenmemis",
    "degerlendirilemedi",
)


def has_hedge_phrase(text):

    if not text:

        return False

    normalized = normalize_text_tr(text)

    return any(normalize_text_tr(phrase) in normalized for phrase in HEDGE_PHRASES)


def find_refs_missing_hedge(section_text, flagged_refs):
    """
    flagged_refs: contains_unreviewed_source'a katkı yapan (direct
    OLMAYAN) draft_source_ref kayıtlarının listesi. Her biri için:
      1. claim_span dolu olmalı,
      2. claim_span, section_text'in GERÇEK bir alt-dizesi olmalı
         (icat edilmiş/uydurma span reddedilir),
      3. claim_span'in KENDİSİ bir HEDGE_PHRASES ifadesi taşımalı.
    Şartlardan biri sağlanmazsa o ref "hedge eksik" listesine girer.
    """

    missing = []

    for ref in flagged_refs:

        claim_span = ref.get("claim_span")

        if not claim_span or not isinstance(claim_span, str):

            missing.append(ref.get("source_ref_id") or ref.get("source_id"))

            continue

        if claim_span not in (section_text or ""):

            missing.append(ref.get("source_ref_id") or ref.get("source_id"))

            continue

        if not has_hedge_phrase(claim_span):

            missing.append(ref.get("source_ref_id") or ref.get("source_id"))

    return missing


def collect_citable_texts(fact_index, fact_ids):
    """
    Doğrulanabilir doğrudan-alıntı kaynağı YALNIZ fact.source.text_excerpt'tir
    (data/case_fact_extraction.schema.json). Mevzuat/içtihat şemalarında
    tam metin alanı YOKTUR - bu fonksiyon KASITLI OLARAK yalnız fact
    kaynaklarını tarar.
    """

    texts = []

    for fact_id in fact_ids:

        record = fact_index.get(fact_id)

        if record is None:
            continue

        fact = record["fact"]

        excerpt = (fact.get("source") or {}).get("text_excerpt")

        if isinstance(excerpt, str) and excerpt:

            texts.append(excerpt)

        statement = fact.get("statement")

        if isinstance(statement, str) and statement:

            texts.append(statement)

    return texts


if __name__ == "__main__":

    print("drafting_policy.py - saf modül, self-test yok.")
