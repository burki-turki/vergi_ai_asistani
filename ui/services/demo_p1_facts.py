# ============================================================
# VERGİ AI - DEMO P1 - OLGULAR (önceden hazırlanmış bulgular, sayfa-kapsamlı eşleşme)
#
# Her bulguda İKİ bilgi AYRIDIR ve birbirini değiştirmez:
#   1) HAZIRLAYAN  = spec'teki origin (Önceden hazırlanmış örnek / Avukat girdisi).
#                    Alıntı eşleşse de etiket DEĞİŞMEZ ("Sistem çıkardı"ya dönüşmez).
#   2) ALINTI EŞLEŞMESİ = alıntı, belirtilen belgenin belirtilen FİZİKSEL sayfasının
#                    metninde (boşluk-daraltılmış, NFC) bulundu mu: ESLESTI / ESLESMEDI / SAYFA_YOK.
#                    YALNIZ o sayfada aranır ("belgede ilk eşleşme" YOKTUR).
#
# Eşleşmeyen bulgu: sessizce düşmez, facts.json'a YAZILMAZ, sonuç kaydında
# `written=false` ile kalır ve raporda ayrı uyarı bölümünde görünür.
#
# Eksik atıf (ör. Ek-2): İKİ AYRI bilgi — (a) örneğe önceden girilmiş atıf
# (Önceden hazırlanmış örnek; alıntısı ESLESTI/ESLESMEDI) ve (b) uygulamanın denetimi
# (Sistem çıkardı): atıf adı sunulan belgelerin kimlik/dosya adı/başlık/referans
# numaralarıyla normalize karşılaştırıldı -> BULUNDU / BULUNAMADI.
#
# Olgular `case_fact_extraction.schema.json`'a uygundur: tümü `unverified`,
# extractor.method="manual" (model/LLM yok). Yazma: yalnız vaka dizini, O_EXCL.
# ============================================================

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ui.services import paths as _paths  # noqa: F401 - src/ sys.path
from ui.services.demo_p1_spec import (  # noqa: E402
    DemoError, DemoSpec, ORIGIN_LABELS, _DOC_ID_RE, _FACT_ID_RE, _FILE_NAME_RE,
)
from ui.services.office_flow_records import OfficeFlowError, write_new_file, canonical_bytes

MATCH_OK = "ESLESTI"
MATCH_NO = "ESLESMEDI"
MATCH_NOPAGE = "SAYFA_YOK"
MATCH_VALUES = (MATCH_OK, MATCH_NO, MATCH_NOPAGE)

CHECK_FOUND = "BULUNDU"
CHECK_NOT_FOUND = "BULUNAMADI"
CHECK_VALUES = (CHECK_FOUND, CHECK_NOT_FOUND)

LABELS_NAME = "demo_content_labels.json"
RESULT_NAME = "demo_p1_sonuc.json"

# harf/rakam sınırında böler ("ek2" == "ek 2"); ondalık/bölümlü sayı TEK jetondur ("2.1" != "2")
_TOKEN_RE = re.compile(r"[a-zçğıöşüâîû]+|[0-9]+(?:[.,][0-9]+)*")
_ROMAN = {"ii": "2", "iii": "3", "iv": "4", "vi": "6", "vii": "7", "viii": "8", "ix": "9"}  # tek harfli (i, v, x) YOK


# ----------------------------------------------------------------
# Alıntı eşleşmesi (YALNIZ ilgili sayfanın metninde)
# ----------------------------------------------------------------


def find_excerpt(page_text: str, excerpt: str):
    """Boşluk-daraltılmış (satır sonu bölünmüş alıntı dahil), NFC, büyük/küçük harf DUYARLI.
    Dönüş: (başlangıç, bitiş) — `page_text`'in kendi indeksleri — veya None."""
    tokens = unicodedata.normalize("NFC", str(excerpt)).split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    match = re.search(pattern, unicodedata.normalize("NFC", str(page_text)))
    return (match.start(), match.end()) if match else None


def match_status(pages, page: int, excerpt: str) -> str:
    if type(page) is not int or page < 1 or page > len(pages):
        return MATCH_NOPAGE
    return MATCH_OK if find_excerpt(pages[page - 1], excerpt) else MATCH_NO


# ----------------------------------------------------------------
# Atıf adı <-> sunulan belgeler (normalize karşılaştırma)
# ----------------------------------------------------------------


def name_tokens(text: str) -> list:
    """Türkçe-duyarlı küçük harf; sayısal jetonlar tamsayıya normalize (001 == 1)."""
    value = unicodedata.normalize("NFC", str(text)).replace("İ", "i").replace("I", "ı").lower()
    tokens = []
    for token in _TOKEN_RE.findall(value):
        if token[0].isdigit():
            tokens.append(".".join(str(int(part)) for part in re.split(r"[.,]", token)))  # 001 -> 1; 2,1 -> 2.1
        else:
            tokens.append(_ROMAN.get(token.replace("ı", "i"), token))  # "II" -> "ıı" (Türkçe küçük harf) -> "ii" -> 2
    return tokens


def _contains_sequence(haystack: list, needle: list) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


def _is_number(token: str) -> bool:
    return token[0].isdigit()


def _ambiguous_reference(tokens: list, lead: str) -> bool:
    """Aynı kaynakta `lead` sözcüğünü (ör. 'ek') FARKLI sayıların izlediği (Ek 2 ... Ek-3) belirsizdir."""
    numbers = {tokens[i + 1] for i in range(len(tokens) - 1) if tokens[i] == lead and _is_number(tokens[i + 1])}
    return len(numbers) > 1


def system_check_reference(name: str, docs, exclude_doc_id=None):
    """Atıf adı, sunulan belgelerin kimliği / dosya adı / başlığıyla karşılaştırılır.
    Jeton dizisi BİTİŞİK olarak tek bir kaynakta geçmelidir (Ek-2 != Ek-1; Ek-2 != Ek-20).
    Atfı İÇEREN belge aday değildir (kendi başlığındaki atıf, başka bir belge bulunduğu anlamına gelmez).
    Adda hem en az bir sayısal hem en az bir sözcük jetonu yoksa ('Ek' veya '2' tek başına) eşleşme
    ARANMAZ -> BULUNAMADI. Sayısal jeton TAM jetondur ('Ek-2.1' atfı 'Ek-2' DEĞİLDİR). Bir kaynakta
    aynı sözcüğü FARKLI sayılar izliyorsa ('Ek 2 değildir; Ek-3', 'Ek-2 ve Ek-3') kaynak BELİRSİZDİR ->
    eşleşme SAYILMAZ (fail-closed; gerçek çok-atıflı bir başlık da BULUNAMADI döner)."""
    needle = name_tokens(name)
    if not any(_is_number(token) for token in needle) or all(_is_number(token) for token in needle):
        return CHECK_NOT_FOUND, None
    lead = next(token for token in needle if not _is_number(token))
    for doc in docs:
        if exclude_doc_id is not None and doc.doc_id == exclude_doc_id:
            continue
        stem = Path(doc.file_name).stem
        for source in (doc.doc_id, stem, doc.title):
            tokens = name_tokens(source)
            if _contains_sequence(tokens, needle) and not _ambiguous_reference(tokens, lead):
                return CHECK_FOUND, doc.doc_id
    return CHECK_NOT_FOUND, None


# ----------------------------------------------------------------
# Sonuç nesneleri
# ----------------------------------------------------------------


@dataclass(frozen=True)
class FindingResult:
    fact_id: str
    doc_id: str
    page: int
    excerpt: str
    statement: str
    fact_kind: str
    origin: str
    match: str
    values: tuple = ()

    @property
    def written(self) -> bool:
        return self.match == MATCH_OK


@dataclass(frozen=True)
class MissingRefResult:
    fact_id: str
    referenced_in_doc: str
    page: int
    excerpt: str
    referenced_name: str
    origin: str
    citation_match: str
    system_check: str
    found_doc_id: object

    @property
    def written(self) -> bool:
        return self.citation_match == MATCH_OK


def evaluate(spec: DemoSpec, docs):
    """Bellekte: her bulgu ve atıf için eşleşme + sistem denetimi. Diske YAZMAZ."""
    pages_by_doc = {doc.doc_id: doc.pages for doc in docs}
    findings = [
        FindingResult(f.fact_id, f.doc_id, f.page, f.excerpt, f.statement, f.fact_kind, f.origin,
                      match_status(pages_by_doc[f.doc_id], f.page, f.excerpt), f.values)
        for f in spec.findings
    ]
    refs = []
    for ref in spec.missing_refs:
        check, found = system_check_reference(ref.referenced_name, docs, exclude_doc_id=ref.referenced_in_doc)
        refs.append(MissingRefResult(
            ref.fact_id, ref.referenced_in_doc, ref.page, ref.excerpt, ref.referenced_name, ref.origin,
            match_status(pages_by_doc[ref.referenced_in_doc], ref.page, ref.excerpt), check, found,
        ))
    return findings, refs


def warning_count(findings, refs) -> int:
    return sum(1 for f in findings if not f.written) + sum(1 for r in refs if not r.written)


# ----------------------------------------------------------------
# facts.json (şema-geçerli; tümü unverified; extractor.method=manual)
# ----------------------------------------------------------------


def _note_for(origin: str) -> str:
    return f"Kaynak: {ORIGIN_LABELS[origin]} (sentetik demo); model güveni değildir."


def _fact_record(*, fact_id, kind, statement, page, excerpt, origin, structured_values):
    return {
        "fact_id": fact_id,
        "fact_kind": kind,
        "statement": statement,
        "normalized_statement": None,
        "extraction_basis": "explicit_text",
        "attributed_party_id": None,
        "attributed_actor_label": None,
        "source": {"page": page, "section": None, "paragraph": None, "text_excerpt": excerpt},
        "structured_values": structured_values,
        "related_party_ids": [],
        "related_document_ids": [],
        "related_dispute_item_ids": [],
        "confidence": 1.0,
        "verification_state": "unverified",
        "notes": _note_for(origin),
    }


def _structured(value) -> dict:
    """Spec değeri -> olgu şemasının structured_value'su (yalnız ilgili alan dolu)."""
    record = {
        "value_type": value.value_type, "label": value.label, "string_value": None,
        "number_value": None, "date_value": None, "money_value": None, "reference_value": None,
    }
    if value.value_type == "date":
        record["date_value"] = value.value
    elif value.value_type == "money":
        integer, _sep, decimals = value.value.partition(".")  # işaret ("-") integer ile birlikte korunur
        record["money_value"] = {"amount": f"{integer}.{decimals.ljust(2, '0')}", "currency": value.currency}
    elif value.value_type == "reference":
        record["reference_value"] = value.value
    else:
        record["string_value"] = value.value
    return record


def build_facts_by_doc(spec: DemoSpec, findings, refs) -> dict:
    """doc_id -> facts.json içeriği (yalnız eşleşen bulgular/atıflar; en az 1 olgusu olan belgeler)."""
    facts_by_doc = {}
    for item in findings:
        if not item.written:
            continue
        facts_by_doc.setdefault(item.doc_id, []).append(_fact_record(
            fact_id=item.fact_id, kind=item.fact_kind, statement=item.statement, page=item.page,
            excerpt=item.excerpt, origin=item.origin,
            structured_values=[_structured(value) for value in item.values],
        ))
    for ref in refs:
        if not ref.written:
            continue
        facts_by_doc.setdefault(ref.referenced_in_doc, []).append(_fact_record(
            fact_id=ref.fact_id, kind="evidence_reference",
            statement=f"Belgede atıf yapılan ek: {ref.referenced_name}",
            page=ref.page, excerpt=ref.excerpt, origin=ref.origin,
            structured_values=[{
                "value_type": "reference", "label": "Atıf yapılan ek", "string_value": None,
                "number_value": None, "date_value": None, "money_value": None,
                "reference_value": ref.referenced_name,
            }],
        ))
    result = {}
    for doc_id, facts in facts_by_doc.items():
        result[doc_id] = {
            "schema_version": 1,
            "extraction_id": f"extract_{doc_id}_demo_p1",
            "case_id": spec.demo_id,
            "source_document_id": doc_id,
            "status": "completed",
            "extractor": {
                "method": "manual", "provider": None, "model": None,
                "extractor_version": "demo_p1_v1", "prompt_version": None, "run_at": None,
            },
            "facts": facts,
            "warnings": [],
            "notes": "DEMO-SENTETIK: önceden hazırlanmış örnek bulgular; model/LLM kullanılmadı.",
        }
    return result


def _mkdir(path: Path) -> None:
    try:
        os.mkdir(str(path))
    except FileExistsError:
        raise DemoError("DIZIN_MEVCUT") from None
    except OSError:
        raise DemoError("YAZMA_BASARISIZ") from None


def _write(path: Path, data: bytes) -> None:
    try:
        write_new_file(path, data)
    except OfficeFlowError as error:
        raise DemoError("DOSYA_MEVCUT" if getattr(error, "code", "") == "DOSYA_MEVCUT" else "YAZMA_BASARISIZ") from None


def _validate_facts_file(facts_path: Path) -> None:
    try:
        import case_fact_validator
        case_fact_validator.validate_fact_extraction(facts_path=str(facts_path), raise_on_error=True)
    except Exception:
        raise DemoError("OLGU_DOGRULAMA_BASARISIZ") from None


def resolver_unresolved(case_root, demo_id: str, fact: dict, doc_id: str):
    """DocumentReferenceResolver çapraz kontrolü (src/ public API; demo kökünde çalışır).
    Hata -> None (rapor yalnız bilgi amaçlı gösterir)."""
    try:
        from document_reference_resolver import DocumentReferenceResolver
        resolver = DocumentReferenceResolver(demo_id, cases_dir=case_root)
        return sorted(str(x) for x in resolver.resolve_fact(fact, doc_id).get("unresolved", []))
    except Exception:
        return None


def write_facts(case_dir, spec: DemoSpec, findings, refs) -> dict:
    """facts.json (belge başına) + doğrulama + kaynak etiketi yan dosyası. Döner: doc_id -> facts yolu."""
    case_dir = Path(case_dir)
    facts_by_doc = build_facts_by_doc(spec, findings, refs)
    written = {}
    labels = {}
    for doc in spec.documents:
        content = facts_by_doc.get(doc.doc_id)
        if not content:
            continue
        extractions = case_dir / "documents" / doc.doc_id / "extractions"
        _mkdir(extractions)
        path = extractions / "facts.json"
        _write(path, canonical_bytes(content))
        _validate_facts_file(path)
        written[doc.doc_id] = path
        for fact in content["facts"]:
            labels[fact["fact_id"]] = None
    origin_by_id = {f.fact_id: f.origin for f in findings}
    origin_by_id.update({r.fact_id: r.origin for r in refs})
    label_map = {
        fact_id: {"origin": origin_by_id[fact_id], "origin_label": ORIGIN_LABELS[origin_by_id[fact_id]]}
        for fact_id in labels
    }
    _write(case_dir / LABELS_NAME, canonical_bytes({"schema_version": 1, "labels": label_map}))
    return written


# ----------------------------------------------------------------
# Sonuç kaydı (rapor bunu okur)
# ----------------------------------------------------------------


def build_result_record(spec: DemoSpec, docs, findings, refs, *, resolver_info=None) -> dict:
    resolver_info = resolver_info or {}
    return {
        "schema_version": 1,
        "demo_id": spec.demo_id,
        "documents": [{
            "doc_id": d.doc_id, "file_name": d.file_name, "title": d.title,
            "document_type": d.document_type, "page_count": len(d.pages), "sha256": d.sha256,
            "pdf_rel": f"documents/{d.doc_id}/{d.file_name}",
        } for d in docs],
        "findings": [{
            "fact_id": f.fact_id, "doc_id": f.doc_id, "page": f.page, "excerpt": f.excerpt,
            "statement": f.statement, "fact_kind": f.fact_kind, "origin": f.origin,
            "match": f.match, "written": f.written,
        } for f in findings],
        "missing_refs": [{
            "fact_id": r.fact_id, "referenced_in_doc": r.referenced_in_doc, "page": r.page,
            "excerpt": r.excerpt, "referenced_name": r.referenced_name, "origin": r.origin,
            "citation_match": r.citation_match, "citation_written": r.written,
            "system_check": r.system_check, "found_doc_id": r.found_doc_id,
            "resolver_unresolved": resolver_info.get(r.fact_id),
        } for r in refs],
        "warning_count": warning_count(findings, refs),
    }


def write_result_record(case_dir, record: dict) -> None:
    _write(Path(case_dir) / RESULT_NAME, canonical_bytes(record))


def _ok_keys(obj, keys) -> bool:
    return isinstance(obj, dict) and set(obj.keys()) == set(keys)


def validate_result_record(record) -> dict:
    """Kapalı şema; bozuksa SONUC_KAYDI_GECERSIZ (rapor bozuk kayıttan üretilmez)."""
    def bad():
        raise DemoError("SONUC_KAYDI_GECERSIZ")

    if not _ok_keys(record, ("schema_version", "demo_id", "documents", "findings", "missing_refs", "warning_count")):
        bad()
    if record["schema_version"] != 1 or type(record["warning_count"]) is not int:
        bad()
    if not isinstance(record["demo_id"], str) or not all(isinstance(record[k], list) for k in ("documents", "findings", "missing_refs")):
        bad()
    for doc in record["documents"]:
        if not _ok_keys(doc, ("doc_id", "file_name", "title", "document_type", "page_count", "sha256", "pdf_rel")):
            bad()
        if type(doc["page_count"]) is not int or doc["page_count"] < 1 or not all(
                isinstance(doc[k], str) for k in ("doc_id", "file_name", "title", "document_type", "sha256", "pdf_rel")):
            bad()
    for doc in record["documents"]:
        # kimlik/yol deseni: mutlak yol, '..', ayraç, sürücü RET (rapor yalnız vaka dizininden okur)
        if (not _DOC_ID_RE.match(doc["doc_id"]) or not _FILE_NAME_RE.match(doc["file_name"])
                or doc["pdf_rel"] != f"documents/{doc['doc_id']}/{doc['file_name']}"
                or not re.fullmatch(r"[0-9a-f]{64}", doc["sha256"])):
            bad()
    doc_ids = {doc["doc_id"] for doc in record["documents"]}
    if len(doc_ids) != len(record["documents"]):
        bad()
    for item in record["findings"]:
        if not _ok_keys(item, ("fact_id", "doc_id", "page", "excerpt", "statement", "fact_kind", "origin", "match", "written")):
            bad()
        if (item["doc_id"] not in doc_ids or item["match"] not in MATCH_VALUES or item["origin"] not in ORIGIN_LABELS
                or type(item["page"]) is not int or type(item["written"]) is not bool
                or not all(isinstance(item[k], str) for k in ("fact_id", "excerpt", "statement", "fact_kind"))
                or not _FACT_ID_RE.match(item["fact_id"])
                or item["written"] != (item["match"] == MATCH_OK)):  # çelişkili kayıt RET
            bad()
    for item in record["missing_refs"]:
        if not _ok_keys(item, ("fact_id", "referenced_in_doc", "page", "excerpt", "referenced_name", "origin",
                               "citation_match", "citation_written", "system_check", "found_doc_id", "resolver_unresolved")):
            bad()
        if (item["referenced_in_doc"] not in doc_ids or item["citation_match"] not in MATCH_VALUES
                or item["system_check"] not in CHECK_VALUES or item["origin"] not in ORIGIN_LABELS
                or type(item["page"]) is not int or type(item["citation_written"]) is not bool
                or not all(isinstance(item[k], str) for k in ("fact_id", "excerpt", "referenced_name"))
                or not _FACT_ID_RE.match(item["fact_id"])
                or item["citation_written"] != (item["citation_match"] == MATCH_OK)):
            bad()
        found = item["found_doc_id"]
        if (found is not None and found not in doc_ids) or ((found is not None) != (item["system_check"] == CHECK_FOUND)):
            bad()
        unresolved = item["resolver_unresolved"]
        if unresolved is not None and not (isinstance(unresolved, list) and all(isinstance(x, str) for x in unresolved)):
            bad()
    expected = (sum(1 for f in record["findings"] if not f["written"])
                + sum(1 for r in record["missing_refs"] if not r["citation_written"]))
    if record["warning_count"] != expected:
        bad()
    return record
