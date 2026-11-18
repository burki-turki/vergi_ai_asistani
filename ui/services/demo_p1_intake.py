# ============================================================
# VERGİ AI - DEMO P1 - GİRİŞ (çok belgeli sentetik vaka, sayfa bölme)
#
# Bu modül yalnız SENTETİK demo içindir; gerçek dosya yolu DEĞİLDİR (T1 ayrıdır).
#
#   - demo kökü DEPO DIŞINDA olmalıdır (realpath + dosya-kimliği denetimi:
#     junction/symlink/subst takma adı; sürücü-göreli yol reddedilir);
#   - YALNIZ spec'te TANIMLI dosyalar açılır: <demo-root>/belgeler/<file_name>.
#     Demo kökünün/komşusunun başka hiçbir dosyası açılmaz, dizin listelenmez;
#   - PDF'ler SALT-OKUNUR ("rb"); kopya vaka dizinine O_EXCL ile yazılır;
#   - metin ENJEKTE EDİLEBİLİR çıkarıcıyla alınır (varsayılan: Poppler
#     `pdftotext` = T1'in public fonksiyonu; subprocess bu dosyada YOKTUR);
#   - sayfa ayracı `\f` KORUNUR (T1'in normalize_extracted_text'i `\f`'i siler,
#     bu yüzden KULLANILMAZ); fiziksel sayfa sayısı = bölme sayısı ve spec'te
#     bildirilen sayıya EŞİT olmalıdır;
#   - çıktı: <demo-root>/vaka/<demo_id>/ (yeni, sahiplik işaretli; üzerine yazma yok).
#
# T1/LOCKED modüllerden yalnız PUBLIC fonksiyonlar import edilir.
# ============================================================

from __future__ import annotations

import dataclasses
import json
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ui.services import paths as _paths  # noqa: F401 - src/ sys.path
from ui.services.demo_p1_spec import DemoError, DemoSpec
from ui.services.office_flow_intake import (  # noqa: E402
    check_source_path, read_source_bytes, default_pdftotext_extractor, validate_seed,
)
from ui.services.office_flow_records import (  # noqa: E402
    OfficeFlowError, write_new_file, canonical_bytes, sha256_hex,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

DOCS_DIRNAME = "belgeler"
CASE_DIRNAME = "vaka"
OUTPUT_DIRNAME = "cikti"
SPEC_NAME = "demo_spec.json"
OWNER_MARKER = ".demo_p1_owner"
TEXT_LIMIT_CHARS = 60000

_CATEGORY_BY_TYPE = {
    "vergi_ceza_ihbarnamesi": "administrative_action",
    "teblig_mazbatasi": "notification",
    "vergi_inceleme_raporu": "audit",
}
_CASE_RELATION_BY_TYPE = {
    "vergi_ceza_ihbarnamesi": "primary_action",
    "teblig_mazbatasi": "notice",
    "vergi_inceleme_raporu": "audit_report",
}

# OfficeFlowError (T1) kodlarından demo kodlarına.
_CODE_MAP = {
    "KAYNAK_YOK": "KAYNAK_YOK", "KAYNAK_PDF_DEGIL": "KAYNAK_PDF_DEGIL",
    "KAYNAK_ICERIDE": "KAYNAK_ICERIDE", "CIKARICI_BASARISIZ": "CIKARICI_BASARISIZ",
    "METIN_BOS": "METIN_BOS", "METIN_COK_UZUN": "METIN_COK_UZUN",
    "TOHUM_DOGRULAMA_BASARISIZ": "TOHUM_DOGRULAMA_BASARISIZ",
    "DOSYA_MEVCUT": "DOSYA_MEVCUT", "DIZIN_MEVCUT": "DIZIN_MEVCUT",
    "YAZMA_BASARISIZ": "YAZMA_BASARISIZ",
}


def _wrap_office(error: OfficeFlowError) -> DemoError:
    return DemoError(_CODE_MAP.get(getattr(error, "code", ""), "BILINMEYEN_HATA"))


# ----------------------------------------------------------------
# Demo kökü
# ----------------------------------------------------------------


def _real(path) -> Path:
    return Path(os.path.realpath(str(path)))


def _is_inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def _aliases(path: Path, other: Path) -> bool:
    """`path` veya herhangi bir ÜST dizini `other` ile AYNI dizin mi (dosya kimliği)?"""
    current = path
    while True:
        try:
            if os.path.exists(str(current)) and os.path.exists(str(other)) and os.path.samefile(str(current), str(other)):
                return True
        except OSError:
            pass
        if current.parent == current:
            return False
        current = current.parent


def check_demo_root(demo_root, *, repo_root=None) -> Path:
    """Mutlak, var olan, DEPO DIŞINDA bir dizin. Depo içindeki/depoyu içeren kök reddedilir."""
    repo = _real(repo_root if repo_root is not None else REPO_ROOT)
    if not isinstance(demo_root, (str, os.PathLike)):
        raise DemoError("DEMO_KOKU_GECERSIZ")
    root = Path(demo_root)
    if not root.is_absolute():
        raise DemoError("DEMO_KOKU_GECERSIZ")  # göreli veya sürücü-göreli (C:foo) yol
    try:
        if not root.is_dir():
            raise DemoError("DEMO_KOKU_GECERSIZ")
    except OSError:
        raise DemoError("DEMO_KOKU_GECERSIZ") from None
    real = _real(root)
    if _is_inside(real, repo) or _is_inside(repo, real) or _aliases(real, repo):
        raise DemoError("DEMO_KOKU_DEPO_ICINDE")
    return root


_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT (Windows junction/symlink/mount point)


def _is_link(path) -> bool:
    """symlink, junction VEYA herhangi bir reparse point mi? (incelenemezse bağlantı SAYILIR)"""
    text = str(path)
    try:
        if os.path.islink(text) or os.path.isjunction(text):
            return True
        attributes = getattr(os.lstat(text), "st_file_attributes", 0)
        return bool(attributes & _REPARSE_POINT)
    except OSError:
        return True


def ensure_inside_root(demo_root, path, *, repo_root=None) -> Path:
    """`path` (demo kökü altındaki vaka/ vaka/<id>/ cikti/ dizini) GERÇEKTEN kökün içinde bir
    dizin mi? Bağlantı/junction/reparse point, kök dışına veya depoya (data/cases dahil) çıkan
    hedef -> DIZIN_GUVENSIZ. HER mkdir'den sonra, İLK yazmadan ÖNCE çağrılır; ihlalde yazma yok."""
    root_real = _real(demo_root)
    repo = _real(repo_root if repo_root is not None else REPO_ROOT)
    candidate = Path(path)
    try:
        if not os.path.isdir(str(candidate)) or _is_link(candidate):
            raise DemoError("DIZIN_GUVENSIZ")
        real = _real(candidate)
        if (not _is_inside(real, root_real) or real == root_real
                or _is_inside(real, repo) or _is_inside(repo, real) or _aliases(real, repo)):
            raise DemoError("DIZIN_GUVENSIZ")
    except OSError:
        raise DemoError("DIZIN_GUVENSIZ") from None
    return candidate


def case_paths(demo_root, demo_id: str) -> dict:
    root = Path(demo_root)
    return {
        "docs_dir": root / DOCS_DIRNAME,
        "case_root": root / CASE_DIRNAME,
        "case_dir": root / CASE_DIRNAME / demo_id,
        "out_dir": root / OUTPUT_DIRNAME,
        "spec_path": root / SPEC_NAME,
    }


def case_exists(demo_root, demo_id: str) -> bool:
    return os.path.lexists(str(case_paths(demo_root, demo_id)["case_dir"]))


def spec_digest(spec: DemoSpec) -> str:
    """Ayrıştırılmış spec'in kanonik özeti (vaka işaretine yazılır; değişen spec fark edilsin)."""
    return sha256_hex(canonical_bytes(dataclasses.asdict(spec)))


def verify_existing_case(demo_root, spec: DemoSpec, *, repo_root=None) -> Path:
    """Var olan vaka dizinini yalnız BİZİM, TAMAMLANMIŞ ve AYNI spec ile hazırlanmışsa devral.
    Bağlantı/kök dışı -> DIZIN_GUVENSIZ; yarım (işaret/sonuç kaydı yok) -> VAKA_YARIM;
    başka demo_id/başka spec -> VAKA_UYUSMUYOR. Araç HİÇBİR şeyi silmez veya onarmaz."""
    root = check_demo_root(demo_root, repo_root=repo_root)
    paths = case_paths(root, spec.demo_id)
    ensure_inside_root(root, paths["case_root"], repo_root=repo_root)
    case_dir = ensure_inside_root(root, paths["case_dir"], repo_root=repo_root)
    marker = case_dir / OWNER_MARKER
    try:
        names = os.listdir(str(case_dir))
        if not os.path.isfile(str(marker)) or _is_link(marker):
            raise DemoError("VAKA_YARIM" if not names else "VAKA_UYUSMUYOR")
        with open(str(marker), "rb") as handle:
            owner = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError):
        raise DemoError("VAKA_UYUSMUYOR") from None
    if (not isinstance(owner, dict) or owner.get("kind") != "demo_p1_case"
            or owner.get("demo_id") != spec.demo_id or owner.get("spec_digest") != spec_digest(spec)):
        raise DemoError("VAKA_UYUSMUYOR")
    for required in ("demo_p1_sonuc.json", "case.json"):
        if not os.path.isfile(str(case_dir / required)) or _is_link(case_dir / required):
            raise DemoError("VAKA_YARIM")
    return case_dir


# ----------------------------------------------------------------
# Metin ve sayfa bölme (`\f` KORUNUR)
# ----------------------------------------------------------------


def normalize_text(raw) -> str:
    """NFC + satır sonu LF. `\\f` (sayfa ayracı) KORUNUR."""
    if not isinstance(raw, str):
        raise DemoError("CIKARICI_BASARISIZ")
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > TEXT_LIMIT_CHARS:
        raise DemoError("METIN_COK_UZUN")
    return text


def split_pages(text: str) -> list:
    """`\\f` ile bölünür; YALNIZ sondaki tek boş parça düşer, ortadaki boş
    sayfa korunur. Hiç içerik yoksa METIN_BOS."""
    pages = text.split("\f")
    if len(pages) > 1 and pages[-1] == "":
        pages = pages[:-1]
    if not any(page.strip() for page in pages):
        raise DemoError("METIN_BOS")
    return pages


def join_pages(pages) -> str:
    """Poppler biçimi: her sayfanın SONUNA `\\f`."""
    return "".join(page + "\f" for page in pages)


# ----------------------------------------------------------------
# Analiz (bellekte; diske YAZMAZ)
# ----------------------------------------------------------------


@dataclass(frozen=True)
class DocPages:
    doc_id: str
    file_name: str
    title: str
    document_type: str
    pdf_bytes: bytes
    sha256: str
    size_bytes: int
    pages: tuple
    source_path: Path


def default_extractor(source_path) -> str:
    return default_pdftotext_extractor(source_path)


def analyze_documents(demo_root, spec: DemoSpec, *, extractor=None, repo_root=None) -> list:
    """Her belge için: kaynak denetimi -> salt-okunur okuma -> enjekte edilebilir çıkarıcı ->
    `\\f` bölme -> bildirilen sayfa sayısıyla karşılaştırma. YALNIZ spec'te tanımlı dosyalar açılır."""
    repo = Path(repo_root) if repo_root is not None else REPO_ROOT
    root = check_demo_root(demo_root, repo_root=repo)
    paths = case_paths(root, spec.demo_id)
    protected = [repo, paths["case_root"], paths["out_dir"]]
    extract = extractor or default_extractor
    result = []
    for doc in spec.documents:
        source = paths["docs_dir"] / doc.file_name
        try:
            source = check_source_path(source, protected_roots=protected)
            data = read_source_bytes(source)
        except OfficeFlowError as error:
            raise _wrap_office(error) from None
        try:
            raw = extract(source)
        except OfficeFlowError as error:
            raise _wrap_office(error) from None
        except DemoError:
            raise
        except Exception:
            raise DemoError("CIKARICI_BASARISIZ") from None
        pages = split_pages(normalize_text(raw))
        if len(pages) != doc.declared_page_count:
            raise DemoError("SAYFA_SAYISI_UYUSMUYOR")
        result.append(DocPages(
            doc_id=doc.doc_id, file_name=doc.file_name, title=doc.title,
            document_type=doc.document_type, pdf_bytes=data, sha256=sha256_hex(data),
            size_bytes=len(data), pages=tuple(pages), source_path=source,
        ))
    return result


# ----------------------------------------------------------------
# JSON kurucular (şema-geçerli, sentetik)
# ----------------------------------------------------------------


def build_demo_case_json(demo_id: str, docs) -> dict:
    first = docs[0]
    primary = next((d for d in docs if d.document_type == "vergi_ceza_ihbarnamesi"), first)
    refs = []
    for doc in docs:
        refs.append({
            "document_id": doc.doc_id,
            "relation_type": _CASE_RELATION_BY_TYPE.get(doc.document_type, "other"),
            "primary": doc.doc_id == primary.doc_id,
            "notes": None,
        })
    money = {"amount": "0.00", "currency": "TRY"}
    return {
        "schema_version": 1,
        "case_id": demo_id,
        "active": True,
        "title": "DEMO - Sentetik dosya",
        "case_type": "assessment_and_penalty",
        "case_status": "pending",
        "stage": "pre_litigation",
        "client_side": "taxpayer",
        "confidentiality_level": "confidential",
        "jurisdiction": "TR",
        "language": "tr",
        "parties": [
            {"party_id": "party_taxpayer_001", "role": "taxpayer", "party_type": "company",
             "display_name": "Mükellef (sentetik demo)", "reference_code": None, "notes": None},
            {"party_id": "party_admin_001", "role": "administration", "party_type": "public_authority",
             "display_name": "İdare (sentetik demo)", "reference_code": None, "notes": None},
        ],
        "dispute_items": [{
            "dispute_item_id": "dispute_001",
            "tax_type": "KDV",
            "period": {"kind": "other", "label": "demo", "start_date": None, "end_date": None},
            "principal_tax": dict(money),
            "penalty_type": None,
            "penalty_amount": dict(money),
            "total_amount": dict(money),
            "asserted_legal_basis_refs": [],
            "source_document_ids": [primary.doc_id],
            "verification_state": "unverified",
            "notes": "Sentetik demo: tutarlar bu alanda taşınmaz.",
        }],
        "administrative_actions": [{
            "action_id": "action_001",
            "action_category": "assessment_and_penalty",
            "action_type": "Vergi ceza ihbarnamesi",
            "issuing_authority": "İdare (sentetik demo)",
            "action_date": None,
            "notification_date": None,
            "source_document_id": primary.doc_id,
            "verification_state": "unverified",
            "notes": None,
        }],
        "events": [],
        "proceedings": [],
        "case_document_refs": refs,
        "related_cases": [],
        "tags": [],
    }


def build_demo_document_json(demo_id: str, doc: DocPages) -> dict:
    return {
        "schema_version": 1,
        "document_id": doc.doc_id,
        "case_id": demo_id,
        "active": True,
        "title": doc.title,
        "document_category": _CATEGORY_BY_TYPE.get(doc.document_type, "other"),
        "document_type": doc.document_type,
        "document_subtype": None,
        "confidentiality_level": "confidential",
        "jurisdiction": "TR",
        "language": "tr",
        "summary": None,
        "file": {
            "file_name": doc.file_name,
            "relative_path": f"cases/{demo_id}/documents/{doc.doc_id}/{doc.file_name}",
            "format": "pdf",
            "mime_type": "application/pdf",
            "sha256": doc.sha256,
            "page_count": len(doc.pages),
            "size_bytes": doc.size_bytes,
        },
        "provenance": {
            "source_origin": "generated",
            "source_description": "Sentetik demo belgesi (P1).",
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
            "extracted_text_path": f"documents/{doc.doc_id}/extracted/{doc.doc_id}.txt",
            "parser_version": "poppler_pdftotext",
        },
        "verification_state": "unverified",
        "tags": [],
    }


# ----------------------------------------------------------------
# Yazma (yalnız demo kökü altında; O_EXCL)
# ----------------------------------------------------------------


def _mkdir(path: Path, *, exist_ok: bool = False) -> None:
    try:
        os.mkdir(str(path))
    except FileExistsError:
        if not exist_ok:
            raise DemoError("DIZIN_MEVCUT") from None
    except OSError:
        raise DemoError("YAZMA_BASARISIZ") from None


def _write(path: Path, data: bytes) -> None:
    try:
        write_new_file(path, data)
    except OfficeFlowError as error:
        raise _wrap_office(error) from None


def write_case(demo_root, spec: DemoSpec, docs, *, repo_root=None) -> Path:
    """Yeni vaka dizini: işaret, PDF kopyaları, `\\f` korunmuş metin, document.json, case.json;
    ardından mevcut validator'lar. Var olan vaka dizinini DEVRALMAZ (DIZIN_MEVCUT)."""
    root = check_demo_root(demo_root, repo_root=repo_root)
    paths = case_paths(root, spec.demo_id)
    _mkdir(paths["case_root"], exist_ok=True)
    ensure_inside_root(root, paths["case_root"], repo_root=repo_root)
    _mkdir(paths["out_dir"], exist_ok=True)
    ensure_inside_root(root, paths["out_dir"], repo_root=repo_root)
    case_dir = paths["case_dir"]
    _mkdir(case_dir)
    ensure_inside_root(root, case_dir, repo_root=repo_root)
    _write(case_dir / OWNER_MARKER, canonical_bytes(
        {"kind": "demo_p1_case", "demo_id": spec.demo_id, "spec_digest": spec_digest(spec)}))
    _mkdir(case_dir / "documents")
    for doc in docs:
        doc_dir = case_dir / "documents" / doc.doc_id
        _mkdir(doc_dir)
        _mkdir(doc_dir / "extracted")
        _write(doc_dir / doc.file_name, doc.pdf_bytes)
        _write(doc_dir / "extracted" / f"{doc.doc_id}.txt", join_pages(doc.pages).encode("utf-8"))
        _write(doc_dir / "document.json", canonical_bytes(build_demo_document_json(spec.demo_id, doc)))
    _write(case_dir / "case.json", canonical_bytes(build_demo_case_json(spec.demo_id, docs)))
    try:
        validate_seed(case_dir)
    except OfficeFlowError as error:
        raise _wrap_office(error) from None
    return case_dir
