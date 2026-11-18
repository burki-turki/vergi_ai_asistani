# ============================================================
# VERGİ AI - BÜRO MODELİ / T1 - F1 DOSYA HAZIRLAMA (TOHUM) + F3 ADAY SATIRLAR
#
# Bugün hiçbir KOORDİNELİ case/document yazıcısı yoktur (T-1: seed
# yazıcısı koordinatörsüz; bugünkü elle hazırlığın AYNISINI yapar, mevcut
# validator'larla kapatır). Bu modül:
#
#   - kaynak PDF yolunu SALT-OKUNUR kabul eder: yalnız "rb" açılır; hiçbir
#     yerde yazma/silme/yeniden adlandırma yoktur; kaynak yol çalışma/ofis
#     kökü içindeyse veya hedefle aynı dosyaysa REDDEDİLİR (KAYNAK_ICERIDE /
#     KAYNAK_AYNI_DOSYA);
#   - metni ENJEKTE EDİLEBİLİR çıkarıcıyla alır (varsayılan: Poppler
#     `pdftotext`; subprocess YALNIZ bu dosyadaki varsayılan çıkarıcıdadır);
#   - yeni vaka dizinini O_EXCL + sahiplik işaretiyle açar, case.json /
#     document.json / belge kopyası / çıkarılmış metni yazar ve mevcut
#     case_validator + case_document_validator'dan geçirir;
#   - F3 için çıkarılmış metinden, TAM BİR tarih içeren aday satırları çıkarır.
#
# Ağ/LLM import'u yok.
# ============================================================

from __future__ import annotations

import os
import re
import shutil
import subprocess  # YALNIZ varsayılan Poppler çıkarıcısı için (bkz. üstteki not)
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ui.services.office_flow_records import (
    OfficeFlowError, RunManifest, RunPaths, create_owned_dir, sha256_hex, write_new_file,
    canonical_bytes,
)

DOC_ID = "ihbarname_001"
DOC_FILE_NAME = "ihbarname_001.pdf"
TEXT_LIMIT_CHARS = 60000
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_CANDIDATE_CHARS = 500

ALLOWED_TAX_TYPES = (
    "KDV", "Kurumlar vergisi", "Gelir vergisi", "Damga vergisi",
    "Veraset ve intikal vergisi", "Motorlu taşıtlar vergisi",
    "Vergi ziyaı cezası", "Usulsüzlük cezası", "Özel usulsüzlük cezası",
)

# manual_fact_entry_engine._EXCERPT_DATE_RE ile BİREBİR (test parite kontrolü yapar).
_DATE_TOKEN_RE = re.compile(r"(?<![0-9])([0-9]{2})([./])([0-9]{2})\2([0-9]{4})(?![0-9])")


# ----------------------------------------------------------------
# Kaynak yol (salt-okunur)
# ----------------------------------------------------------------


def _real(path) -> Path:
    return Path(os.path.realpath(str(path)))


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def _aliases_protected_root(real: Path, protected_roots, same) -> bool:
    """Kaynağın herhangi bir ÜST dizini, korunan köklerden biriyle AYNI dizin mi?
    (dosya-kimliği karşılaştırması: UNC/subst/junction takma adlarını da yakalar;
    yol metni karşılaştırması bunları kaçırır). Var olmayan kök atlanır."""
    existing = [Path(root) for root in protected_roots if os.path.lexists(str(root))]
    current = real
    while True:
        for root in existing:
            try:
                if same(str(current), str(root)):
                    return True
            except OSError:
                continue
        if current.parent == current:
            return False
        current = current.parent


def check_source_path(source, *, protected_roots, alias_samefile=None) -> Path:
    """Kaynak PDF: var, normal dosya, .pdf, korunan köklerin DIŞINDA
    (gerçek yol içerme + dosya-kimliğiyle takma ad denetimi; kopyalamadan ÖNCE)."""
    path = Path(source)
    try:
        if not path.is_file():
            raise OfficeFlowError("KAYNAK_YOK")
    except OSError:
        raise OfficeFlowError("KAYNAK_YOK") from None
    if path.suffix.lower() != ".pdf":
        raise OfficeFlowError("KAYNAK_PDF_DEGIL")
    real = _real(path)
    for root in protected_roots:
        if _inside(real, _real(root)):
            raise OfficeFlowError("KAYNAK_ICERIDE")
    if _aliases_protected_root(real, protected_roots, alias_samefile or os.path.samefile):
        raise OfficeFlowError("KAYNAK_ICERIDE")
    return path


def read_source_bytes(source) -> bytes:
    """Kaynağı YALNIZ okuma kipinde açar."""
    try:
        with open(str(source), "rb") as handle:
            data = handle.read(MAX_SOURCE_BYTES + 1)
    except OSError:
        raise OfficeFlowError("KAYNAK_YOK") from None
    if len(data) > MAX_SOURCE_BYTES or not data.startswith(b"%PDF"):
        raise OfficeFlowError("KAYNAK_PDF_DEGIL")
    return data


# ----------------------------------------------------------------
# Metin çıkarıcı (enjekte edilebilir)
# ----------------------------------------------------------------


def default_pdftotext_extractor(source_path) -> str:
    """Varsayılan: Poppler `pdftotext` (yerel, internetsiz). Resmî test
    kapısında KOŞTURULMAZ (T3: cihazda ölçülür). Kabuk YOK, sabit argv."""
    exe = shutil.which("pdftotext")
    if exe is None:
        raise OfficeFlowError("CIKARICI_BASARISIZ")
    try:
        completed = subprocess.run(  # noqa: S603 - sabit argv, kabuk yok
            [exe, "-enc", "UTF-8", "-eol", "unix", str(source_path), "-"],
            capture_output=True, timeout=120, check=False, shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise OfficeFlowError("CIKARICI_BASARISIZ") from None
    if completed.returncode != 0:
        raise OfficeFlowError("CIKARICI_BASARISIZ")
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise OfficeFlowError("CIKARICI_BASARISIZ") from None


def normalize_extracted_text(text: str) -> str:
    cleaned = unicodedata.normalize("NFC", str(text)).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\f", "\n")
    if not cleaned.strip():
        raise OfficeFlowError("METIN_BOS")
    if len(cleaned) > TEXT_LIMIT_CHARS:
        raise OfficeFlowError("METIN_COK_UZUN")
    return cleaned


# ----------------------------------------------------------------
# Tohum (case.json / document.json)
# ----------------------------------------------------------------


def validate_tax_types(tax_types) -> list:
    if not isinstance(tax_types, (list, tuple)) or not tax_types:
        raise OfficeFlowError("VERGI_TURU_GECERSIZ")
    cleaned = []
    for item in tax_types:
        if item not in ALLOWED_TAX_TYPES or item in cleaned:
            raise OfficeFlowError("VERGI_TURU_GECERSIZ")
        cleaned.append(item)
    return cleaned


def build_case_json(case_id: str, tax_types) -> dict:
    """Kimlik/tutar/tarih taşımayan, şema-geçerli TOHUM. Tebliğ tarihi
    BURADA YOKTUR (yalnız avukatın F2/F3 girdisinden gelir)."""
    money = {"amount": "0.00", "currency": "TRY"}
    items = []
    for index, tax_type in enumerate(validate_tax_types(tax_types), start=1):
        items.append({
            "dispute_item_id": f"dispute_{index:03d}",
            "tax_type": tax_type,
            "period": {"kind": "other", "label": "pilot", "start_date": None, "end_date": None},
            "principal_tax": dict(money),
            "penalty_type": None,
            "penalty_amount": dict(money),
            "total_amount": dict(money),
            "asserted_legal_basis_refs": [],
            "source_document_ids": [DOC_ID],
            "verification_state": "unverified",
            "notes": None,
        })
    return {
        "schema_version": 1,
        "case_id": case_id,
        "active": True,
        "title": "Pilot dosyası",
        "case_type": "assessment_and_penalty",
        "case_status": "pending",
        "stage": "pre_litigation",
        "client_side": "taxpayer",
        "confidentiality_level": "confidential",
        "jurisdiction": "TR",
        "language": "tr",
        "parties": [
            {"party_id": "party_taxpayer_001", "role": "taxpayer", "party_type": "company",
             "display_name": "Mükellef (pilot)", "reference_code": None, "notes": None},
            {"party_id": "party_admin_001", "role": "administration", "party_type": "public_authority",
             "display_name": "İdare (pilot)", "reference_code": None, "notes": None},
        ],
        "dispute_items": items,
        "administrative_actions": [{
            "action_id": "action_001",
            "action_category": "assessment_and_penalty",
            "action_type": "Vergi ceza ihbarnamesi",
            "issuing_authority": "İdare (pilot)",
            "action_date": None,
            "notification_date": None,
            "source_document_id": DOC_ID,
            "verification_state": "unverified",
            "notes": None,
        }],
        "events": [],
        "proceedings": [],
        "case_document_refs": [{
            "document_id": DOC_ID, "relation_type": "notice", "primary": True, "notes": None,
        }],
        "related_cases": [],
        "tags": [],
    }


def build_document_json(case_id: str, *, sha256: str, size_bytes: int, page_count: int) -> dict:
    return {
        "schema_version": 1,
        "document_id": DOC_ID,
        "case_id": case_id,
        "active": True,
        "title": "Vergi ve ceza ihbarnamesi (pilot kopyası)",
        "document_category": "administrative_action",
        "document_type": "vergi_ceza_ihbarnamesi",
        "document_subtype": None,
        "confidentiality_level": "confidential",
        "jurisdiction": "TR",
        "language": "tr",
        "summary": None,
        "file": {
            "file_name": DOC_FILE_NAME,
            "relative_path": f"cases/{case_id}/documents/{DOC_ID}/{DOC_FILE_NAME}",
            "format": "pdf",
            "mime_type": "application/pdf",
            "sha256": sha256,
            "page_count": page_count,
            "size_bytes": size_bytes,
        },
        "provenance": {
            "source_origin": "user_upload",
            "source_description": "Büro bilgisayarında dosya avukatı tarafından hazırlanan pilot kopyası.",
            "source_url": None,
            "original_file_name": None,
            "received_at": None,
            "uploaded_by_ref": None,
        },
        "issuer_party_id": "party_admin_001",
        "recipient_party_ids": ["party_taxpayer_001"],
        "dates": [],
        "reference_numbers": [],
        "relations": [],
        "processing": {
            "ingest_enabled": False,
            "parser": "case_pdf",
            "chunk_strategy": "document_sections",
            "ocr_required": False,
            "ocr_completed": False,
            "text_extraction_status": "completed",
            "index_status": "not_indexed",
            "extracted_text_path": f"documents/{DOC_ID}/extracted/{DOC_ID}.txt",
            "parser_version": "poppler_pdftotext",
        },
        "verification_state": "unverified",
        "tags": [],
    }


@dataclass(frozen=True)
class SeedResult:
    case_id: str
    doc_id: str
    page_count: int
    text_chars: int


def _mkdir(path: Path) -> None:
    try:
        os.mkdir(str(path))
    except FileExistsError:
        raise OfficeFlowError("DIZIN_MEVCUT") from None
    except OSError:
        raise OfficeFlowError("YAZMA_BASARISIZ") from None


def validate_seed(case_dir) -> None:
    """Mevcut validator'lar (açık yol argümanıyla; argümansız çağrı
    case_0001'i doğrulardı). Herhangi bir hata -> kapalı kod."""
    from ui.services import paths as _paths  # noqa: F401 - src/ sys.path
    import case_validator
    import case_document_validator

    try:
        case_validator.validate_case_file(case_path=str(Path(case_dir) / "case.json"), raise_on_error=True)
        case_document_validator.validate_case_documents(case_dir=Path(case_dir), raise_on_error=True)
    except Exception:
        raise OfficeFlowError("TOHUM_DOGRULAMA_BASARISIZ") from None


def seed_case(
    *, paths: RunPaths, source_pdf, page_count: int, tax_types, extractor,
    manifest: RunManifest, protected_roots, samefile=None, alias_samefile=None,
) -> SeedResult:
    """F1. Sıra: kaynak denetimi -> çıkarma -> yeni vaka dizini (O_EXCL +
    işaret) -> dosyalar -> validator. Var olan vaka dizinini DEVRALMAZ."""
    if type(page_count) is not int or page_count < 1:
        raise OfficeFlowError("SAYFA_GECERSIZ")
    tax = validate_tax_types(tax_types)
    source = check_source_path(source_pdf, protected_roots=protected_roots, alias_samefile=alias_samefile)
    data = read_source_bytes(source)
    try:
        text = normalize_extracted_text(extractor(source))
    except OfficeFlowError:
        raise
    except Exception:
        raise OfficeFlowError("CIKARICI_BASARISIZ") from None

    case_dir = create_owned_dir(paths.case_dir, run_id=paths.run_id, kind="case_dir")
    doc_dir = case_dir / "documents" / DOC_ID
    _mkdir(case_dir / "documents")
    _mkdir(doc_dir)
    _mkdir(doc_dir / "extracted")

    pdf_path = doc_dir / DOC_FILE_NAME
    write_new_file(pdf_path, data)
    same = samefile or os.path.samefile
    try:
        if same(str(source), str(pdf_path)):
            # ASLA silme: yalnız reddet (kopya = kaynak olamaz).
            raise OfficeFlowError("KAYNAK_AYNI_DOSYA")
    except OSError:
        pass
    manifest.add(root="case", rel=f"documents/{DOC_ID}/{DOC_FILE_NAME}", tur="CALISMA_DIZINI_BELGE_KOPYASI")

    text_path = doc_dir / "extracted" / f"{DOC_ID}.txt"
    write_new_file(text_path, text.encode("utf-8"))
    manifest.add(root="case", rel=f"documents/{DOC_ID}/extracted/{DOC_ID}.txt", tur="CIKARILMIS_METIN")

    doc_json = build_document_json(
        paths.case_id, sha256=sha256_hex(data), size_bytes=len(data), page_count=page_count,
    )
    write_new_file(doc_dir / "document.json", canonical_bytes(doc_json))
    manifest.add(root="case", rel=f"documents/{DOC_ID}/document.json", tur="CALISMA_DOSYALARI")
    write_new_file(case_dir / "case.json", canonical_bytes(build_case_json(paths.case_id, tax)))
    manifest.add(root="case", rel="case.json", tur="CALISMA_DOSYALARI")
    validate_seed(case_dir)
    return SeedResult(case_id=paths.case_id, doc_id=DOC_ID, page_count=page_count, text_chars=len(text))


# ----------------------------------------------------------------
# F3 - aday tarih satırları (F2 kaydından SONRA çağrılır)
# ----------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    index: int
    text: str
    date_iso: str


def _date_tokens(line: str):
    tokens = []
    for match in _DATE_TOKEN_RE.finditer(line):
        day, _sep, month, year = match.groups()
        tokens.append((int(year), int(month), int(day)))
    return tokens


def candidate_lines(text: str) -> list:
    """TAM BİR tarih token'ı içeren, ≤500 karakterli, kontrol karakteri
    taşımayan satırlar. Birden çok tarih içeren satır ADAY DEĞİLDİR (motorun
    M-08 kuralı alıntıdaki TÜM tarihlerin eşleşmesini ister)."""
    from datetime import date

    candidates = []
    for number, raw in enumerate(str(text).split("\n"), start=1):
        line = unicodedata.normalize("NFC", raw).strip()
        if not line or len(line) > MAX_CANDIDATE_CHARS:
            continue
        if any(unicodedata.category(ch) == "Cc" and ch != "\t" for ch in line):
            continue
        tokens = _date_tokens(line)
        if len(tokens) != 1:
            continue
        year, month, day = tokens[0]
        try:
            iso = date(year, month, day).isoformat()
        except ValueError:
            continue
        candidates.append(Candidate(index=len(candidates) + 1, text=line, date_iso=iso))
    return candidates


def read_extracted_text(paths: RunPaths) -> str:
    target = paths.case_dir / "documents" / DOC_ID / "extracted" / f"{DOC_ID}.txt"
    try:
        return target.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise OfficeFlowError("METIN_BOS") from None


def build_manual_input(case_id: str, candidate: Candidate, page: int) -> dict:
    return {
        "schema_version": 1, "case_id": case_id, "document_id": DOC_ID,
        "facts": [{
            "role": "notification_date", "date": candidate.date_iso,
            "page": page, "text_excerpt": candidate.text,
        }],
    }


def write_manual_input(paths: RunPaths, manual_input: dict, manifest: RunManifest) -> None:
    input_dir = paths.case_dir / "documents" / DOC_ID / "manual_input"
    _mkdir(input_dir)
    write_new_file(input_dir / "manual_facts.input.json", canonical_bytes(manual_input))
    manifest.add(
        root="case", rel=f"documents/{DOC_ID}/manual_input/manual_facts.input.json",
        tur="CALISMA_DOSYALARI",
    )
