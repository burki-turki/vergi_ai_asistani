# ============================================================
# VERGİ AI - ADIM 10 B YOLU: MANUEL FACT GİRİŞ MOTORU
# (`generation.fact_manual`).
#
# Avukatın orijinal belgeyle karşılaştırdığı TEK bir tebliğ tarihi
# girdisini (`documents/<doc>/manual_input/manual_facts.input.json`),
# `case_fact_extraction.schema.json`'a uyan DETERMİNİSTİK bir pending
# extraction'a (`extractor.method = "manual"`) çeviren saf, ağsız motor.
#
# SINIRLAR (bilinçli):
#   - Bu modül HİÇBİR ağ/LLM kütüphanesi import etmez, alt süreç
#     başlatmaz, `ui.` paketini import etmez ve bir `main()`/komut satırı
#     giriş noktası TAŞIMAZ. Tek çağıran `ui/services/
#     manual_fact_mutation_facade.py`'dir (mutation coordinator/journal
#     altında).
#   - Ürettiği her fact `verification_state = "unverified"` taşır.
#     Manuel giriş VERIFICATION DEĞİLDİR; doğrulama yalnız
#     `verification.fact` akışıyla yapılır (CLAUDE.md §3 Prensip 4/5/7).
#     `confidence = 1.0` model güveni değildir (K-4).
#   - Canonical `facts.json`'a ASLA yazmaz; yalnız pending + kendi
#     generation audit kaydını üretir.
#   - Doğrulama kuralları baytlar üzerinde çalışır: her girdi dosyası
#     çağıran tarafından BİR KEZ okunur, aynı `bytes` nesnesi hash'e,
#     ayrıştırmaya ve alıntı eşleşmesine verilir (TOCTOU, L-1).
#   - Karşılaştırmalar locale'e duyarlı DEĞİLDİR: büyük/küçük harf
#     dönüşümü (`lower`/`casefold`) kullanılmaz; normalizasyon yalnız
#     Unicode NFC + boşluk daraltmadır.
#
# YAZIM SIRASI (N-M1 kullanıcı kararı, 2026-10-08 - exact-scope §2.6'nın
# replace-ÖNCE sırasının YERİNE GEÇER):
#   1. temp (`<pending>.manual.tmp`, O_CREAT|O_EXCL, LF, fsync)
#   2. tam dosya validator'ı (temp üzerinde)
#   3. generation audit (O_CREAT|O_EXCL, LF, fsync) - içinde, henüz
#      diskte olmayan pending'in DONDURULMUŞ bayt sha256'sı
#   4. os.replace(temp, pending)
#   5. post-write assert (diskten yeniden okunan sha == dondurulmuş sha)
# Bu sırayla her sert çöküş noktası mevcut reconciliation kurallarıyla
# çözülür: temp-yalnız -> failed; audit var / pending yok -> failed;
# audit var / pending var -> completed. Önceki tasarımın kalıcı
# "pending var / audit yok" (dual-false) penceresi ortadan kalkar.
#
# ROLLBACK (yalnız süreç hayattayken, bu çağrının KENDİ oluşturduğu
# dosyalar): önce pending (adım 4 tamamlandıysa), sonra temp, en son
# audit. Audit YALNIZ pending başarıyla silindiyse (veya hiç
# oluşmadıysa) silinir - pending silinemezse audit bırakılır, böylece
# disk "audit var / pending var" ile tutarlı kalır (completed'e
# reconcile olur). Yarım yazılmış audit (N-L1) her iki aileyi de kalıcı
# fail-closed durduracağı için, yazımı başarısız olan audit dosyası
# açılan yol üzerinden silinir.
# ============================================================

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

import case_fact_validator
import fact_approval
import path_containment


# ============================================================
# SÜRÜMLER / SABİTLER
# ============================================================

MANUAL_FACT_ENGINE_VERSION = "manual_fact_entry_v1"

EXTRACTOR_VERSION = "manual_fact_entry_v1"

ACTION_FAMILY = "generation.fact_manual"

CHANNEL = "local_lawyer_manual_fact_cli"

TARGET_STATE = "generated"

GENERATION_AUDIT_SCHEMA_VERSION = "1"

# K-13: pending adı fact_approval'ın KENDİ sabitinden gelir - promotion
# zinciri bu adı arar. Ad "llm" der, içerik "manual" der; otorite içerik
# + audit + journal'dır (exact-scope §8/1).
CURRENT_PENDING_FILENAME = fact_approval.CURRENT_PENDING_FILENAME

# `.tmp` ile biter: `*.json.pending`/`*.pending` glob'larına uymaz ve
# LLM motorunun `<pending>.tmp` adından farklıdır.
TEMP_FILENAME = CURRENT_PENDING_FILENAME + ".manual.tmp"

CANONICAL_FILENAME = "facts.json"

MANUAL_INPUT_DIRNAME = "manual_input"

MANUAL_INPUT_FILENAME = "manual_facts.input.json"

GENERATION_REVIEWS_DIRNAME = "generation_reviews"

ELIGIBLE_DOCUMENT_TYPE = "vergi_ceza_ihbarnamesi"

FACT_NOTES = (
    "Manuel giriş (manual_fact_entry_v1); confidence model güveni değildir; "
    "verification değildir."
)

EXTRACTION_NOTES = (
    "Adım 10 B yolu manuel giriş. Avukatın orijinal belgeyle karşılaştırdığı "
    "tebliğ tarihi; verification_state=unverified."
)

_UTF8_BOM = b"\xef\xbb\xbf"

# M-08: ASCII rakam, aynı ayraç (nokta veya eğik çizgi), rakam sınırları.
_EXCERPT_DATE_RE = re.compile(r"(?<![0-9])([0-9]{2})([./])([0-9]{2})\2([0-9]{4})(?![0-9])")

_WHITESPACE_RE = re.compile(r"\s+")

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


# ============================================================
# PATHS (writer-containment seam - facade/adapter bu attribute'u HER
# çağrıda dinamik okur; test redirect sweep'leri aynen çalışır).
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

CASES_DIR = (
    DATA_DIR
    / "cases"
)

INPUT_SCHEMA_PATH = (
    DATA_DIR
    / "manual_fact_input.schema.json"
)

FACT_SCHEMA_PATH = case_fact_validator.FACT_SCHEMA_PATH


# ============================================================
# HATA HİYERARŞİSİ (exact-scope §2.5). Mesajlar sabit literal + kural
# kodu taşır; alıntı metni, girdi içeriği, alt hata metni ve mutlak yol
# mesaja GİRMEZ.
# ============================================================

class ManualFactEntryError(Exception):
    rule = None

    def __init__(self, message: str, *, rule: str | None = None):
        if rule is not None:
            self.rule = rule
        super().__init__(message)


class ManualFactEncodingError(ManualFactEntryError):
    rule = "M-15"


class ManualFactInputSchemaError(ManualFactEntryError):
    rule = "M-02"


class ManualFactDateInvalidError(ManualFactEntryError):
    rule = "M-03"


class ManualFactPageError(ManualFactEntryError):
    rule = "M-04"


class ManualFactDocumentTypeError(ManualFactEntryError):
    rule = "M-05"


class ManualFactSourceTextError(ManualFactEntryError):
    rule = "M-06"


class ManualFactExcerptNotFoundError(ManualFactEntryError):
    rule = "M-07"


class ManualFactExcerptDateMismatchError(ManualFactEntryError):
    rule = "M-08"


class ManualFactCandidateInvalidError(ManualFactEntryError):
    rule = "M-11a"


class ManualFactWriteError(ManualFactEntryError):
    rule = "M-11b"


class ManualFactPostWriteInvariantError(Exception):
    """Programlama invariant'ı: diskteki pending sha, dondurulmuş
    baytların sha'sına eşit değil. Bilinçli olarak `ManualFactEntryError`
    DEĞİLDİR - facade onu domain hatasına çevirmez, ham traceback ile
    yayılır."""


# ============================================================
# YARDIMCILAR
# ============================================================

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest_bytes(payload) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")


def _reject_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ManualFactEncodingError(
                "Manuel girdi JSON'unda tekrarlanan anahtar var (kural M-15).",
            )
        out[key] = value
    return out


def _has_forbidden_control(text: str) -> bool:
    for ch in text:
        if ch == "\t":
            continue
        category = unicodedata.category(ch)
        if category == "Cc":
            return True
    return False


def normalize_for_match(text: str) -> str:
    """Yalnız KARŞILAŞTIRMA içindir; saklanmaz. NFC + her boşluk dizisi
    tek boşluk + baş/son boşluk kırpma. Büyük/küçük harf dönüşümü
    YAPILMAZ."""
    normalized = unicodedata.normalize("NFC", text)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def load_input_schema(schema_bytes: bytes) -> dict:
    try:
        return json.loads(schema_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManualFactInputSchemaError(
            "Manuel girdi şeması okunamadı (kural M-02).",
        ) from error


# ============================================================
# M-15 / M-02 / M-03: GİRDİ
# ============================================================

def parse_manual_input(raw_bytes: bytes, input_schema: dict) -> dict:
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise ManualFactEncodingError("Manuel girdi bayt olarak verilmelidir (kural M-15).")

    if raw_bytes.startswith(_UTF8_BOM):
        raise ManualFactEncodingError(
            "Manuel girdi UTF-8 BOM ile başlıyor; BOM'suz UTF-8 zorunludur (kural M-15).",
        )

    try:
        text = bytes(raw_bytes).decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ManualFactEncodingError(
            "Manuel girdi geçerli UTF-8 değil (kural M-15).",
        ) from error

    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise ManualFactEncodingError(
            "Manuel girdi geçerli JSON değil (kural M-15).",
        ) from error

    validator = Draft202012Validator(input_schema)
    if any(True for _ in validator.iter_errors(data)):
        raise ManualFactInputSchemaError(
            "Manuel girdi şemaya uymuyor (kural M-02).",
        )

    # Şema `integer`'ı bool'dan ayırır; savunma derinliği olarak açık tip
    # kontrolleri (N-O4: True bir int'tir).
    if type(data.get("schema_version")) is not int:
        raise ManualFactInputSchemaError("schema_version tamsayı olmalıdır (kural M-02).")

    for key in ("case_id", "document_id"):
        value = data.get(key)
        if not isinstance(value, str) or value != value.strip() or "\n" in value:
            raise ManualFactInputSchemaError(f"{key} biçimi geçersiz (kural M-02).")

    fact = data["facts"][0]

    if type(fact.get("page")) is not int:
        raise ManualFactInputSchemaError("page tamsayı olmalıdır (kural M-02).")

    check_calendar_date(fact.get("date"))

    excerpt = fact.get("text_excerpt")
    if unicodedata.normalize("NFC", excerpt) != excerpt:
        raise ManualFactEncodingError(
            "text_excerpt Unicode NFC biçiminde değil (kural M-15).",
        )
    if _has_forbidden_control(excerpt):
        raise ManualFactEncodingError(
            "text_excerpt kontrol karakteri içeriyor (kural M-15).",
        )

    return data


def check_calendar_date(value) -> date:
    if not isinstance(value, str) or len(value) != 10:
        raise ManualFactDateInvalidError("date YYYY-MM-DD biçiminde olmalıdır (kural M-03).")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ManualFactDateInvalidError(
            "date gerçek bir takvim günü değil (kural M-03).",
        ) from error
    if parsed.isoformat() != value:
        raise ManualFactDateInvalidError("date ISO biçimine birebir dönmüyor (kural M-03).")
    return parsed


# ============================================================
# M-04 / M-05: BELGE UYGUNLUĞU
# ============================================================

def check_document_eligibility(document: dict, page: int) -> int:
    if not isinstance(document, dict):
        raise ManualFactDocumentTypeError("document.json bir nesne olmalıdır (kural M-05).")

    if document.get("document_type") != ELIGIBLE_DOCUMENT_TYPE:
        raise ManualFactDocumentTypeError(
            "Belge türü manuel tebliğ girişi için uygun değil (kural M-05).",
        )

    if document.get("active") is not True:
        raise ManualFactDocumentTypeError("Belge aktif değil (kural M-05).")

    file_section = document.get("file")
    page_count = file_section.get("page_count") if isinstance(file_section, dict) else None

    if type(page_count) is not int:
        raise ManualFactPageError(
            "document.json file.page_count tamsayı değil veya boş; operatör "
            "doldurmadan manuel giriş yapılamaz (kural M-04).",
        )

    if page_count < 1:
        raise ManualFactPageError("document.json file.page_count >= 1 olmalıdır (kural M-04).")

    if type(page) is not int or page < 1 or page > page_count:
        raise ManualFactPageError("page belge sayfa aralığının dışında (kural M-04).")

    return page_count


# ============================================================
# M-06 / M-07 / M-08: KAYNAK METİN VE ALINTI
# ============================================================

def decode_source_text(raw_bytes: bytes) -> str:
    """`extracted/<doc>.txt` LLM motoruyla aynı artefakttır: `utf-8-sig`
    ile çözülür (BOM tolere edilir); ham sha çağıranda BOM dahil
    hesaplanır."""
    try:
        text = bytes(raw_bytes).decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ManualFactSourceTextError(
            "Belge metni geçerli UTF-8 değil (kural M-06).",
        ) from error
    if not normalize_for_match(text):
        raise ManualFactSourceTextError("Belge metni boş (kural M-06).")
    return text


def check_excerpt_in_text(excerpt: str, source_text: str) -> None:
    needle = normalize_for_match(excerpt)
    if not needle or needle not in normalize_for_match(source_text):
        raise ManualFactExcerptNotFoundError(
            "text_excerpt belge metninde birebir bulunamadı (kural M-07).",
        )


def extract_excerpt_dates(excerpt: str):
    """Alıntıdaki `GG.AA.YYYY` / `GG/AA/YYYY` token'ları. Geçersiz bir
    token `ManualFactExcerptDateMismatchError` üretir."""
    found = set()
    for match in _EXCERPT_DATE_RE.finditer(excerpt):
        day, _sep, month, year = match.groups()
        try:
            found.add(date(int(year), int(month), int(day)).isoformat())
        except ValueError as error:
            raise ManualFactExcerptDateMismatchError(
                "text_excerpt geçersiz bir takvim tarihi içeriyor (kural M-08).",
            ) from error
    return found


def check_excerpt_date(excerpt: str, date_iso: str) -> None:
    found = extract_excerpt_dates(excerpt)
    if not found:
        raise ManualFactExcerptDateMismatchError(
            "text_excerpt içinde tarih bulunamadı (kural M-08).",
        )
    if found != {date_iso}:
        raise ManualFactExcerptDateMismatchError(
            "text_excerpt içindeki tarih(ler) girilen date ile birebir eşleşmiyor (kural M-08).",
        )


# ============================================================
# DETERMİNİSTİK EXTRACTION
# ============================================================

def iso_to_tr(date_iso: str) -> str:
    year, month, day = date_iso.split("-")
    return f"{day}.{month}.{year}"


def build_extraction(case_id: str, document_id: str, input_digest: str, manual_input: dict) -> dict:
    if not isinstance(input_digest, str) or not _SHA256_HEX_RE.match(input_digest):
        raise ManualFactCandidateInvalidError("input_digest geçersiz (kural M-11a).")

    fact_input = manual_input["facts"][0]
    date_iso = fact_input["date"]
    short = input_digest[:12]

    fact = {
        "fact_id": f"fact_{document_id}_manual_v1_{short}_001",
        "fact_kind": "date_fact",
        "statement": f"Tebliğ Tarihi: {iso_to_tr(date_iso)}",
        "normalized_statement": None,
        "extraction_basis": "explicit_text",
        "attributed_party_id": None,
        "attributed_actor_label": None,
        "source": {
            "page": fact_input["page"],
            "section": None,
            "paragraph": None,
            "text_excerpt": fact_input["text_excerpt"],
        },
        "structured_values": [
            {
                "value_type": "date",
                "label": "Tebliğ Tarihi",
                "string_value": None,
                "number_value": None,
                "date_value": date_iso,
                "money_value": None,
                "reference_value": None,
            }
        ],
        "related_party_ids": [],
        "related_document_ids": [],
        "related_dispute_item_ids": [],
        "confidence": 1.0,
        "verification_state": "unverified",
        "notes": FACT_NOTES,
    }

    return {
        "schema_version": 1,
        "extraction_id": f"extract_{document_id}_manual_v1_{short}",
        "case_id": case_id,
        "source_document_id": document_id,
        "status": "completed",
        "extractor": {
            "method": "manual",
            "provider": None,
            "model": None,
            "extractor_version": EXTRACTOR_VERSION,
            "prompt_version": None,
            "run_at": None,
        },
        "facts": [fact],
        "warnings": [],
        "notes": EXTRACTION_NOTES,
    }


def validate_candidate_in_memory(extraction: dict, fact_schema: dict) -> None:
    """M-11a: her fact `unverified` + mevcut fact şemasına bellek-içi
    şema doğrulaması (`case_fact_validator.validate_schema` yalnız
    ÇAĞRILIR)."""
    facts = extraction.get("facts") if isinstance(extraction, dict) else None
    if not isinstance(facts, list) or not facts:
        raise ManualFactCandidateInvalidError("Aday extraction fact içermiyor (kural M-11a).")
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("verification_state") != "unverified":
            raise ManualFactCandidateInvalidError(
                "Aday extraction'da verification_state=unverified olmayan fact var (kural M-11a).",
            )
    extractor = extraction.get("extractor")
    if not isinstance(extractor, dict) or extractor.get("method") != "manual":
        raise ManualFactCandidateInvalidError("Aday extraction method=manual değil (kural M-11a).")
    if case_fact_validator.validate_schema(extraction, fact_schema):
        raise ManualFactCandidateInvalidError(
            "Aday extraction fact şemasına uymuyor (kural M-11a).",
        )


def freeze_pending_bytes(extraction: dict) -> bytes:
    """LLM ailesinin `_freeze_pending_bytes()` tarifinin aynısı: LF,
    indent=2, ensure_ascii=False, tek trailing newline."""
    return json.dumps(extraction, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def evaluate_candidate(
    *,
    case_id: str,
    document_id: str,
    input_digest: str,
    manual_input_bytes: bytes,
    input_schema_bytes: bytes,
    document_bytes: bytes,
    source_text_bytes: bytes,
    fact_schema: dict,
) -> dict:
    """PL ve PC'de AYNI şekilde çalışan saf değerlendirme: M-02…M-08,
    M-11a, M-15. Dönüş dondurulmuş aday baytlarını içerir."""
    input_schema = load_input_schema(input_schema_bytes)
    manual_input = parse_manual_input(manual_input_bytes, input_schema)

    try:
        document = json.loads(bytes(document_bytes).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManualFactDocumentTypeError("document.json okunamadı (kural M-05).") from error

    fact_input = manual_input["facts"][0]
    page_count = check_document_eligibility(document, fact_input["page"])

    source_text = decode_source_text(source_text_bytes)
    check_excerpt_in_text(fact_input["text_excerpt"], source_text)
    check_excerpt_date(fact_input["text_excerpt"], fact_input["date"])

    extraction = build_extraction(case_id, document_id, input_digest, manual_input)
    validate_candidate_in_memory(extraction, fact_schema)
    frozen = freeze_pending_bytes(extraction)

    return {
        "manual_input": manual_input,
        "document": document,
        "page_count": page_count,
        "extraction": extraction,
        "frozen_pending_bytes": frozen,
        "pending_sha256": sha256_bytes(frozen),
        "notification_date": fact_input["date"],
        "page": fact_input["page"],
        "excerpt_sha256": sha256_bytes(fact_input["text_excerpt"].encode("utf-8")),
    }


# ============================================================
# WRITER (N-M1 sırası; bkz. modül başlığı)
# ============================================================

def audit_record_bytes(record: dict) -> bytes:
    """LF + tek trailing newline; platform satır sonu çevrimi YOK (CRLF
    çalışma kopyası sapması sınıfından kaçınılır)."""
    return json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def _unlink_quietly(path: Path) -> bool:
    try:
        if os.path.lexists(path):
            os.unlink(path)
        return True
    except OSError:
        return False


def _write_open_fd(fd: int, data: bytes) -> None:
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_excl_fsync(path: Path, data: bytes) -> None:
    """O_CREAT|O_EXCL ile oluşturur; yazım/fsync başarısız olursa bu
    çağrının KENDİ oluşturduğu dosyayı siler (yarım artık bırakmaz)."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    try:
        _write_open_fd(fd, data)
    except BaseException:
        _unlink_quietly(path)
        raise


def _create_audit_excl(reviews_dir: Path, document_id: str, data: bytes) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"manual_{document_id}_{stamp}"
    suffix = 0
    while True:
        name = f"{base}.generation_audit.json" if suffix == 0 else f"{base}_{suffix}.generation_audit.json"
        path_containment.validate_segment(name)
        candidate = path_containment.resolve_for_create(reviews_dir, name)
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            suffix += 1
            if suffix > 1000:
                raise ManualFactWriteError(
                    "Generation audit için boş ad bulunamadı (kural M-11b).",
                )
            continue
        try:
            _write_open_fd(fd, data)
        except BaseException:
            # N-L1: yarım audit her iki aileyi kalıcı durdurur - bu
            # çağrının KENDİ açtığı yol silinir.
            _unlink_quietly(candidate)
            raise
        return candidate


def write_manual_pending(
    *,
    extractions_dir: Path,
    reviews_dir: Path,
    pending_path: Path,
    temp_path: Path,
    frozen_pending_bytes: bytes,
    audit_record: dict,
    document_id: str,
    validate=None,
) -> dict:
    """Kilit altında, `executing` satırı varken çağrılır. Yolların hepsi
    çağıran tarafından kilit altında doğrulanmış nesnelerdir.
    `audit_record`'a `pending_sha256` bu fonksiyonda eklenir (dondurulmuş
    baytlardan). `validate` yalnız test seam'idir; None ise gerçek
    `case_fact_validator.validate_fact_extraction` kullanılır."""
    if validate is None:
        validate = case_fact_validator.validate_fact_extraction

    # Savunma derinliği (E-N9): writer, kendisine verilen baytları HİÇBİR
    # dosya oluşturmadan önce M-11a kurallarından yeniden geçirir -
    # `verified` bir fact içeren aday asla diske ulaşmaz.
    try:
        candidate = json.loads(bytes(frozen_pending_bytes).decode("utf-8"))
        fact_schema = json.loads(Path(FACT_SCHEMA_PATH).read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as error:
        raise ManualFactCandidateInvalidError(
            "Writer'a verilen aday baytları ayrıştırılamadı (kural M-11a).",
        ) from error
    validate_candidate_in_memory(candidate, fact_schema)
    if freeze_pending_bytes(candidate) != bytes(frozen_pending_bytes):
        raise ManualFactCandidateInvalidError(
            "Writer'a verilen aday baytları kanonik dondurma tarifine uymuyor (kural M-11a).",
        )

    expected_sha = sha256_bytes(frozen_pending_bytes)
    record = dict(audit_record)
    record["pending_sha256"] = expected_sha
    audit_bytes = audit_record_bytes(record)

    extractions_dir.mkdir(parents=False, exist_ok=True)
    reviews_dir.mkdir(parents=False, exist_ok=True)

    temp_created = False
    audit_path = None
    replaced = False

    try:
        _write_excl_fsync(temp_path, frozen_pending_bytes)
        temp_created = True

        validation = validate(temp_path, raise_on_error=True)
        if not isinstance(validation, dict) or validation.get("valid") is not True:
            raise ManualFactWriteError("Tam dosya validator'ı PASS vermedi (kural M-11b).")

        audit_path = _create_audit_excl(reviews_dir, document_id, audit_bytes)

        os.replace(temp_path, pending_path)
        replaced = True
        temp_created = False

        observed_sha = sha256_bytes(Path(pending_path).read_bytes())
        if observed_sha != expected_sha:
            raise ManualFactPostWriteInvariantError(
                "Diskteki pending sha, dondurulmuş aday baytlarının sha'sı ile eşleşmiyor.",
            )
    except BaseException:
        pending_removed = True
        if replaced:
            pending_removed = _unlink_quietly(pending_path)
        if temp_created:
            _unlink_quietly(temp_path)
        if audit_path is not None and pending_removed:
            _unlink_quietly(audit_path)
        raise

    return {
        "pending_path": pending_path,
        "pending_sha256": expected_sha,
        "audit_path": audit_path,
        "audit_record": record,
    }
