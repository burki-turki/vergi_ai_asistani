# ============================================================
# VERGİ AI - DEMO P1 - SPEC (kapalı şemalı demo_spec.json)
#
# P1 demo: üç SENTETİK belge + önceden hazırlanmış bulgular + eksik atıflar.
# Bu modül yalnız spec'i yükler/doğrular; dosya sistemine yazmaz, ağ/LLM
# kullanmaz.
#
# KAPALI ŞEMA: bilinmeyen anahtar -> RET (her düzeyde). Kaynak etiketi (origin)
# yalnız "ornek" (Önceden hazırlanmış örnek) veya "avukat" (Avukat girdisi) olabilir;
# "Sistem çıkardı" etiketi spec'te YAZILAMAZ (yazılımın kendi tespitleri için
# ayrılmıştır; önceden hazırlanmış bir bulgunun "sistem çıkardı" diye etiketlenmesi
# dürüstlük ihlalidir).
#
# Mesajlar YALNIZ kapalı kodlardır: `str(error)` içerik/yol taşıyamaz.
# ============================================================

from __future__ import annotations

import datetime
import json
import re
import unicodedata
from dataclasses import dataclass

DEMO_ERROR_CODES = frozenset({
    "SPEC_YOK", "SPEC_BOZUK", "SPEC_ALAN_GECERSIZ", "DEMO_KIMLIGI_GECERSIZ",
    "DEMO_KOKU_GECERSIZ", "DEMO_KOKU_DEPO_ICINDE", "KAYNAK_YOK",
    "KAYNAK_PDF_DEGIL", "KAYNAK_ICERIDE", "CIKARICI_BASARISIZ", "METIN_BOS",
    "METIN_COK_UZUN", "SAYFA_SAYISI_UYUSMUYOR", "DIZIN_MEVCUT", "DOSYA_MEVCUT",
    "YAZMA_BASARISIZ", "TOHUM_DOGRULAMA_BASARISIZ", "OLGU_DOGRULAMA_BASARISIZ",
    "ALINTI_ESLESMEDI", "VAKA_YOK", "SONUC_KAYDI_GECERSIZ", "KULLANIM_HATASI",
    "BILINMEYEN_HATA", "DIZIN_GUVENSIZ", "VAKA_YARIM", "VAKA_UYUSMUYOR",
})


class DemoError(Exception):
    """Mesajı YALNIZ kapalı koddur."""

    def __init__(self, code: str):
        if code not in DEMO_ERROR_CODES:
            code = "BILINMEYEN_HATA"
        self.code = code
        super().__init__(code)


# Kaynak etiketi (yazıyla). "sistem" yalnız yazılımın kendi tespitlerinde kullanılır.
ORIGIN_LABELS = {
    "ornek": "Önceden hazırlanmış örnek",
    "avukat": "Avukat girdisi",
    "sistem": "Sistem çıkardı",
}
SPEC_ALLOWED_ORIGINS = ("ornek", "avukat")

# case_fact_extraction.schema.json fact_kind alt kümesi (demo için yeterli olanlar).
ALLOWED_FACT_KINDS = (
    "event", "administrative_claim", "taxpayer_claim", "document_finding",
    "monetary_fact", "date_fact", "legal_reference", "procedural_fact", "other",
)

MAX_SPEC_BYTES = 256 * 1024
MAX_DOCUMENTS = 10
MAX_FINDINGS = 200
MAX_MISSING_REFS = 50
MAX_EXCERPT_CHARS = 500
MAX_STATEMENT_CHARS = 500
MAX_TITLE_CHARS = 200

_DEMO_ID_RE = re.compile(r"^demo_[a-z0-9_]{1,40}$")
_DOC_ID_RE = re.compile(r"^[a-z0-9_]{3,40}$")
_FACT_ID_RE = re.compile(r"^[a-z0-9_-]{3,80}$")
_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. -]{0,100}\.pdf$")
_DOC_TYPE_RE = re.compile(r"^[a-z0-9_]{3,60}$")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONEY_RE = re.compile(r"^-?(\d{1,15})(?:\.(\d{1,2}))?$")  # işaretli tutar (şema: ^-?\d+(\.\d{1,2})?$)
MONEY_CURRENCIES = ("TRY", "USD", "EUR")
VALUE_TYPES = ("date", "money", "reference", "string")
MAX_VALUES = 8


@dataclass(frozen=True)
class DemoDocument:
    doc_id: str
    file_name: str
    document_type: str
    title: str
    declared_page_count: int


@dataclass(frozen=True)
class DemoValue:
    value_type: str
    label: str
    value: str
    currency: str = "TRY"  # yalnız money için anlamlı; spec'te yazılmazsa TRY


@dataclass(frozen=True)
class DemoFinding:
    fact_id: str
    doc_id: str
    page: int
    excerpt: str
    fact_kind: str
    statement: str
    origin: str
    values: tuple = ()


@dataclass(frozen=True)
class DemoMissingRef:
    fact_id: str
    referenced_in_doc: str
    page: int
    excerpt: str
    referenced_name: str
    origin: str


@dataclass(frozen=True)
class DemoSpec:
    demo_id: str
    documents: tuple
    findings: tuple
    missing_refs: tuple


# ----------------------------------------------------------------
# Küçük, katı doğrulayıcılar
# ----------------------------------------------------------------


def _fail():
    raise DemoError("SPEC_ALAN_GECERSIZ")


def _is_int(value) -> bool:
    return type(value) is int


def _exact_keys(obj, required, optional=()):
    if not isinstance(obj, dict):
        _fail()
    keys = set(obj.keys())
    if not all(isinstance(key, str) for key in keys):
        _fail()
    if not set(required) <= keys or not keys <= set(required) | set(optional):
        _fail()


def _text(value, *, max_chars, single_line=False) -> str:
    if not isinstance(value, str):
        _fail()
    cleaned = unicodedata.normalize("NFC", value)
    if not cleaned.strip() or len(cleaned) > max_chars:
        _fail()
    for char in cleaned:
        category = unicodedata.category(char)
        if category == "Cc" or (single_line and category in ("Zl", "Zp")):
            _fail()
    return cleaned


def _page(value, declared: int) -> int:
    if not _is_int(value) or value < 1 or value > declared:
        _fail()
    return value


def _origin(value) -> str:
    if value not in SPEC_ALLOWED_ORIGINS:
        _fail()
    return value


def _turkish_money(value: str) -> str:
    """"850000.00" -> "850.000,00" (alıntıda aranan biçim; işaret ayrıca denetlenir)."""
    match = _MONEY_RE.match(value)
    integer, decimals = match.group(1), (match.group(2) or "").ljust(2, "0")
    grouped = f"{int(integer):,}".replace(",", ".")
    return f"{grouped},{decimals}"


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _token_in(token: str, excerpt: str, *, forbid_before: str, forbid_after: str) -> bool:
    """`token`, alıntıda TAM JETON olarak geçiyor mu? Önünde/ardında rakam (veya binlik/ondalık
    ayracı) bulunan bir geçiş ('11.000,00' içindeki '1.000,00') eşleşme SAYILMAZ."""
    pattern = f"(?<![{forbid_before}]){re.escape(token)}(?![{forbid_after}])"
    return re.search(pattern, excerpt) is not None


# Tutar bağlamı: İŞARET ve açık PARA BİRİMİ. Spec doğrulamasında RET mimarisi (alıntıyla çelişen
# işaret/birim olgu kaydına yazılamaz; fail-closed). Alıntıda birim AÇIKÇA yoksa varsayılan TRY.
_UNIT_ALT = r"(?:₺|\$|€|(?<![A-Za-z])(?:TL|TRY|USD|EUR)(?![A-Za-z]))"
_UNIT_TO_CURRENCY = {"₺": "TRY", "TL": "TRY", "TRY": "TRY", "$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR"}
_NEG_BEFORE = (
    re.compile(r"[-\u2212]\s?(?:" + _UNIT_ALT + r"\s?)?$", re.I),      # -1.000,00 / −1.000,00 / -₺1.000,00
    re.compile(_UNIT_ALT + r"\s?[-\u2212]$", re.I),                    # ₺-1.000,00 / TL -1.000,00
    re.compile(r"\(-\)\s?(?:" + _UNIT_ALT + r"\s?)?$", re.I),         # (-)1.000,00
)
_PAREN_OPEN_BEFORE = re.compile(r"\(\s?(?:" + _UNIT_ALT + r"\s?)?$", re.I)
_PAREN_CLOSE_AFTER = re.compile(r"^\s?(?:" + _UNIT_ALT + r")?\s?\)", re.I)
_UNIT_BEFORE = re.compile(r"(" + _UNIT_ALT + r")\s?(?:[-\u2212]|\(-\)|\()?\s?$", re.I)
_UNIT_AFTER = re.compile(r"^\s?(" + _UNIT_ALT + r")", re.I)


def _money_context_matches(amount_text: str, negative: bool, currency: str, excerpt: str) -> bool:
    """`amount_text` (TR biçimli, işaretsiz) alıntıda TAM JETON olarak geçmeli; geçişin İŞARETİ
    (önde -, −, (-), ya da tutarı saran parantez) spec işaretiyle, açık PARA BİRİMİ (₺ TL TRY $ USD € EUR)
    spec para birimiyle çelişmemeli. Birim açıkça yazılmamışsa TRY varsayılır."""
    pattern = f"(?<![0-9.,]){re.escape(amount_text)}(?![0-9])"
    for found in re.finditer(pattern, excerpt):
        before, after = excerpt[:found.start()], excerpt[found.end():]
        found_negative = (any(rx.search(before) for rx in _NEG_BEFORE)
                          or bool(_PAREN_OPEN_BEFORE.search(before) and _PAREN_CLOSE_AFTER.search(after)))
        unit = _UNIT_BEFORE.search(before) or _UNIT_AFTER.search(after)
        found_currency = _UNIT_TO_CURRENCY[unit.group(1).upper() if unit.group(1).isalpha() else unit.group(1)] if unit else "TRY"
        if found_negative == negative and found_currency == currency:
            return True
    return False


def _value(item, excerpt: str) -> DemoValue:
    """Yapılandırılmış değer: kapalı tür; her değer alıntıda TAM JETON olarak GÖRÜNMELİDİR
    (yazılım, alıntıda olmayan bir değeri olgu kaydına yazmaz; alt dize eşleşmesi yetmez)."""
    _exact_keys(item, ("value_type", "label", "value"), optional=("currency",))
    value_type = item["value_type"]
    if value_type not in VALUE_TYPES:
        _fail()
    currency = "TRY"
    if "currency" in item:
        if value_type != "money" or item["currency"] not in MONEY_CURRENCIES:
            _fail()
        currency = item["currency"]
    label = _text(item["label"], max_chars=80, single_line=True)
    value = _text(item["value"], max_chars=200, single_line=True)
    if value_type == "date":
        match = _ISO_DATE_RE.match(value)
        if not match:
            _fail()
        year, month, day = (int(group) for group in match.groups())
        try:
            datetime.date(year, month, day)
        except ValueError:
            _fail()
        if not any(_token_in(f"{day:02d}{sep}{month:02d}{sep}{year}", excerpt,
                             forbid_before="0-9./,", forbid_after="0-9")
                   for sep in (".", "/")):
            _fail()
    elif value_type == "money":
        if not _MONEY_RE.match(value) or not _money_context_matches(
                _turkish_money(value.lstrip("-")), value.startswith("-"), currency, excerpt):
            _fail()
    elif value_type == "reference":
        if not _token_in(value, excerpt, forbid_before=r"\w", forbid_after=r"\w"):
            _fail()
    else:  # string: boşluk daraltılmış TAM eşleşme (kelime sınırlı)
        collapsed = _collapse(value)
        if not collapsed or not _token_in(collapsed, _collapse(excerpt), forbid_before=r"\w", forbid_after=r"\w"):
            _fail()
    return DemoValue(value_type, label, value, currency)


def _values(raw_values, excerpt: str, fact_kind: str) -> tuple:
    if not isinstance(raw_values, list) or len(raw_values) > MAX_VALUES:
        _fail()
    values = tuple(_value(item, excerpt) for item in raw_values)
    kinds = {value.value_type for value in values}
    # case_fact_validator ile aynı kurallar (spec düzeyinde, erken ret)
    if ((fact_kind == "date_fact" and "date" not in kinds)
            or (fact_kind == "monetary_fact" and "money" not in kinds)
            or (fact_kind == "legal_reference" and "reference" not in kinds)):
        _fail()
    return values


# ----------------------------------------------------------------
# Yükleme
# ----------------------------------------------------------------


def parse_spec(data: bytes) -> DemoSpec:
    """Ham bayttan kapalı-şemalı spec. Herhangi bir hata -> kapalı kod."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_SPEC_BYTES:
        raise DemoError("SPEC_BOZUK")
    try:
        raw = json.loads(bytes(data).decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise DemoError("SPEC_BOZUK") from None
    return validate_spec(raw)


def validate_spec(raw) -> DemoSpec:
    _exact_keys(raw, ("schema_version", "demo_id", "belgeler", "bulgular", "eksik_atiflar"))
    if not _is_int(raw["schema_version"]) or raw["schema_version"] != 1:
        _fail()
    demo_id = raw["demo_id"]
    if not isinstance(demo_id, str) or not _DEMO_ID_RE.match(demo_id):
        raise DemoError("DEMO_KIMLIGI_GECERSIZ")

    documents_raw = raw["belgeler"]
    if not isinstance(documents_raw, list) or not 1 <= len(documents_raw) <= MAX_DOCUMENTS:
        _fail()
    documents = []
    seen_ids, seen_files = set(), set()
    for item in documents_raw:
        _exact_keys(item, ("doc_id", "file_name", "document_type", "title", "declared_page_count"))
        doc_id = item["doc_id"]
        file_name = item["file_name"]
        document_type = item["document_type"]
        if not isinstance(doc_id, str) or not _DOC_ID_RE.match(doc_id) or doc_id in seen_ids:
            _fail()
        if (not isinstance(file_name, str) or not _FILE_NAME_RE.match(file_name)
                or file_name.casefold() in seen_files):
            _fail()
        if not isinstance(document_type, str) or not _DOC_TYPE_RE.match(document_type):
            _fail()
        title = _text(item["title"], max_chars=MAX_TITLE_CHARS, single_line=True)
        declared = item["declared_page_count"]
        if not _is_int(declared) or not 1 <= declared <= 500:
            _fail()
        seen_ids.add(doc_id)
        seen_files.add(file_name.casefold())
        documents.append(DemoDocument(doc_id, file_name, document_type, title, declared))
    declared_by_doc = {doc.doc_id: doc.declared_page_count for doc in documents}

    findings_raw = raw["bulgular"]
    if not isinstance(findings_raw, list) or len(findings_raw) > MAX_FINDINGS:
        _fail()
    findings = []
    seen_fact_ids = set()
    for item in findings_raw:
        _exact_keys(item, ("fact_id", "doc_id", "page", "excerpt", "fact_kind", "statement", "origin"),
                    optional=("degerler",))
        fact_id = item["fact_id"]
        if not isinstance(fact_id, str) or not _FACT_ID_RE.match(fact_id) or fact_id in seen_fact_ids:
            _fail()
        doc_id = item["doc_id"]
        if doc_id not in declared_by_doc:
            _fail()
        if item["fact_kind"] not in ALLOWED_FACT_KINDS:
            _fail()
        excerpt = _text(item["excerpt"], max_chars=MAX_EXCERPT_CHARS, single_line=True)
        seen_fact_ids.add(fact_id)
        findings.append(DemoFinding(
            fact_id=fact_id,
            doc_id=doc_id,
            page=_page(item["page"], declared_by_doc[doc_id]),
            excerpt=excerpt,
            fact_kind=item["fact_kind"],
            statement=_text(item["statement"], max_chars=MAX_STATEMENT_CHARS, single_line=True),
            origin=_origin(item["origin"]),
            values=_values(item.get("degerler", []), excerpt, item["fact_kind"]),
        ))

    refs_raw = raw["eksik_atiflar"]
    if not isinstance(refs_raw, list) or len(refs_raw) > MAX_MISSING_REFS:
        _fail()
    refs = []
    for item in refs_raw:
        _exact_keys(item, ("fact_id", "referenced_in_doc", "page", "excerpt", "referenced_name", "origin"))
        fact_id = item["fact_id"]
        if not isinstance(fact_id, str) or not _FACT_ID_RE.match(fact_id) or fact_id in seen_fact_ids:
            _fail()
        doc_id = item["referenced_in_doc"]
        if doc_id not in declared_by_doc:
            _fail()
        seen_fact_ids.add(fact_id)
        refs.append(DemoMissingRef(
            fact_id=fact_id,
            referenced_in_doc=doc_id,
            page=_page(item["page"], declared_by_doc[doc_id]),
            excerpt=_text(item["excerpt"], max_chars=MAX_EXCERPT_CHARS, single_line=True),
            referenced_name=_text(item["referenced_name"], max_chars=80, single_line=True),
            origin=_origin(item["origin"]),
        ))

    return DemoSpec(demo_id, tuple(documents), tuple(findings), tuple(refs))
