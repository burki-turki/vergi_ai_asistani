# ============================================================
# VERGİ AI - DEMO P1 - RAPOR (statik, internetsiz HTML)
#
# Çıktı: tek dosya, dış kaynaksız (http(s)/<link>/<script>/uzak font YOK), JS YOK;
# `<details>` ve bağlantılarla çalışır. Tüm dinamik metin KAÇIŞLIDIR.
#
# Her bulguda İKİ bilgi AYRI satırlardadır:
#   "Hazırlayan"        -> kaynak etiketi (yazıyla; eşleşmeden ETKİLENMEZ)
#   "Alıntı eşleşmesi"  -> EŞLEŞTİ / EŞLEŞMEDİ / SAYFA YOK (belirtilen belge + fiziksel sayfa)
#
# Bağlantı (`file:///…pdf#page=N`) bir EK ÖZELLİKTİR: bağlantı çalışsın ya da çalışmasın
# belge adı + fiziksel sayfa no + o sayfanın metni HER ZAMAN raporda bulunur.
#
# Rapor gövdesi yalnız spec / sayfa metni / SABİT etiketlerden oluşur; yazılım
# hukuki sonuç/cümle ÜRETMEZ.
# ============================================================

from __future__ import annotations

import hashlib
import html
import json
import os
from dataclasses import dataclass
from pathlib import Path

from ui.services.demo_p1_facts import (
    CHECK_FOUND, MATCH_NO, MATCH_NOPAGE, MATCH_OK, LABELS_NAME, RESULT_NAME,
    find_excerpt, validate_result_record,
)
from ui.services.demo_p1_spec import DemoError, ORIGIN_LABELS

MATCH_LABELS = {MATCH_OK: "EŞLEŞTİ", MATCH_NO: "EŞLEŞMEDİ", MATCH_NOPAGE: "SAYFA YOK"}
SYSTEM_LABEL = ORIGIN_LABELS["sistem"]

# Birleşik ifade (kullanıcı kararı; tam metin)
COMBINED_NOT_FOUND = "İhbarnamede atıf var, sunulan dosyalar arasında bulunamadı"

_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;margin:1.5rem;line-height:1.45;color:#1b1b1b}
.bant{background:#7a1f1f;color:#fff;font-weight:700;padding:.6rem 1rem;letter-spacing:.05em}
.not{background:#f3f3f3;border-left:4px solid #888;padding:.5rem .8rem;margin:.6rem 0}
table{border-collapse:collapse;margin:.6rem 0}th,td{border:1px solid #bbb;padding:.3rem .6rem;text-align:left;vertical-align:top}
section.bulgu,section.atif{border:1px solid #ccc;padding:.6rem 1rem;margin:1rem 0}
section.uyari{border-color:#b36b00;background:#fff7e8}
dt{font-weight:700;margin-top:.35rem}dd{margin-left:1rem}
.eslesti{color:#0b5d1e;font-weight:700}.eslesmedi{color:#9a2200;font-weight:700}
pre{white-space:pre-wrap;background:#fafafa;border:1px solid #ddd;padding:.6rem}
mark{background:#ffe066}
"""


# ----------------------------------------------------------------
# Veri
# ----------------------------------------------------------------


@dataclass(frozen=True)
class ReportData:
    record: dict
    pages_by_doc: dict   # doc_id -> tuple(sayfa metinleri)
    pdf_uri: dict        # doc_id -> "file:///…pdf" veya None
    pdf_state: dict      # doc_id -> "tamam" | "degismis" | "yok"


def _read_text(path: Path) -> str:
    try:
        with open(str(path), "rb") as handle:
            return handle.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        raise DemoError("SONUC_KAYDI_GECERSIZ") from None


def _split(text: str) -> list:
    pages = text.split("\f")
    if len(pages) > 1 and pages[-1] == "":
        pages = pages[:-1]
    return pages


def load_report_data(case_dir) -> ReportData:
    """Yalnız vaka dizinindeki sonuç kaydını, belge metinlerini ve PDF kopyalarını okur."""
    case_dir = Path(case_dir)
    if not case_dir.is_dir():
        raise DemoError("VAKA_YOK")
    try:
        record = validate_result_record(json.loads(_read_text(case_dir / RESULT_NAME)))
    except ValueError:
        raise DemoError("SONUC_KAYDI_GECERSIZ") from None
    pages_by_doc, pdf_uri, pdf_state = {}, {}, {}
    for doc in record["documents"]:
        pages = _split(_read_text(case_dir / "documents" / doc["doc_id"] / "extracted" / f"{doc['doc_id']}.txt"))
        if len(pages) != doc["page_count"]:
            raise DemoError("SONUC_KAYDI_GECERSIZ")
        pages_by_doc[doc["doc_id"]] = tuple(pages)
        pdf_path = case_dir / doc["pdf_rel"]
        try:
            with open(str(pdf_path), "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            pdf_uri[doc["doc_id"]], pdf_state[doc["doc_id"]] = None, "yok"
            continue
        pdf_uri[doc["doc_id"]] = Path(os.path.abspath(str(pdf_path))).as_uri()
        pdf_state[doc["doc_id"]] = "tamam" if digest == doc["sha256"] else "degismis"
    return ReportData(record, pages_by_doc, pdf_uri, pdf_state)


# ----------------------------------------------------------------
# HTML parçaları
# ----------------------------------------------------------------


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _link(data: ReportData, doc_id: str, page: int) -> str:
    uri = data.pdf_uri.get(doc_id)
    if not uri:
        return ("<dd>Bağlantı yok (PDF bulunamadı). Belge adı ve fiziksel sayfa numarasıyla PDF'i elle açın; "
                "sayfa metni aşağıdadır.</dd>")
    note = ""
    if data.pdf_state.get(doc_id) == "degismis":
        note = " <strong>UYARI: PDF, hazırlamadan sonra değişmiş görünüyor.</strong>"
    return (f'<dd><a href="{_e(uri)}#page={int(page)}">Belgeyi {int(page)}. fiziksel sayfada aç</a>{note} '
            "<small>(Bağlantı, PDF görüntüleyiciye bağlıdır; sayfayı doğrudan açmazsa belge adı ve fiziksel sayfa "
            "numarasıyla elle gidin.)</small></dd>")


def _page_text_block(data: ReportData, doc: dict, page: int, excerpt: str, *, highlight: bool) -> str:
    pages = data.pages_by_doc[doc["doc_id"]]
    if page < 1 or page > len(pages):
        return f'<p class="eslesmedi">Belirtilen fiziksel sayfa ({int(page)}) belgede yok.</p>'
    text = pages[page - 1]
    span = find_excerpt(text, excerpt) if highlight else None
    if span:
        body = f"{_e(text[:span[0]])}<mark>{_e(text[span[0]:span[1]])}</mark>{_e(text[span[1]:])}"
    else:
        body = _e(text)
    return (f"<details open><summary>Fiziksel sayfa {int(page)} metni — {_e(doc['title'])}</summary>"
            f"<pre>{body}</pre></details>")


def _match_sentence(match: str, doc: dict, page: int) -> str:
    title, number = _e(doc["title"]), int(page)
    if match == MATCH_OK:
        return (f'<dd class="eslesti">{MATCH_LABELS[match]} — alıntı "{title}" belgesinin '
                f"fiziksel sayfa {number} metninde bulundu.</dd>")
    if match == MATCH_NO:
        return (f'<dd class="eslesmedi">{MATCH_LABELS[match]} — alıntı "{title}" belgesinin '
                f"fiziksel sayfa {number} metninde bulunamadı.</dd>")
    return f'<dd class="eslesmedi">{MATCH_LABELS[match]} — belirtilen fiziksel sayfa ({number}) belgede yok.</dd>'


def _finding_block(data: ReportData, item: dict, docs: dict, *, warning: bool) -> str:
    doc = docs[item["doc_id"]]
    cls = "bulgu uyari" if warning else "bulgu"
    return (
        f'<section class="{cls}" id="bulgu-{_e(item["fact_id"])}">'
        f'<h3>{_e(item["statement"])}</h3><dl>'
        f'<dt>Hazırlayan</dt><dd class="hazirlayan">{_e(ORIGIN_LABELS[item["origin"]])}</dd>'
        f'<dt>Alıntı eşleşmesi</dt>{_match_sentence(item["match"], doc, item["page"])}'
        "<dt>Doğrulama durumu</dt><dd>doğrulanmamış (unverified)</dd>"
        f'<dt>Belge</dt><dd>{_e(doc["title"])} <small>(dosya: {_e(doc["file_name"])}; kimlik: {_e(doc["doc_id"])})</small></dd>'
        f'<dt>Fiziksel sayfa</dt><dd>{int(item["page"])} / {int(doc["page_count"])}</dd>'
        f'<dt>Alıntı</dt><dd><q>{_e(item["excerpt"])}</q></dd>'
        f'<dt>Bağlantı</dt>{_link(data, doc["doc_id"], item["page"])}'
        "</dl>"
        f'{_page_text_block(data, doc, item["page"], item["excerpt"], highlight=item["match"] == MATCH_OK)}'
        "</section>"
    )


def _combined_sentence(item: dict, docs: dict) -> str:
    cited_doc = docs[item["referenced_in_doc"]]
    found_doc = docs.get(item["found_doc_id"]) if item["found_doc_id"] else None
    matched = item["citation_match"] == MATCH_OK
    found = item["system_check"] == CHECK_FOUND
    if matched and not found:
        if cited_doc["document_type"] == "vergi_ceza_ihbarnamesi":
            return COMBINED_NOT_FOUND
        return f'{cited_doc["title"]} belgesinde atıf var, sunulan dosyalar arasında bulunamadı'
    if matched and found:
        target = f'{found_doc["title"]} ({found_doc["doc_id"]})' if found_doc else "sunulan belge"
        return f"Atıf var; sunulan dosyada bulundu: {target}"
    if found:
        target = f'{found_doc["title"]} ({found_doc["doc_id"]})' if found_doc else "sunulan belge"
        return ("Örneğe girilen atıf belirtilen sayfada doğrulanamadı "
                f"({MATCH_LABELS[item['citation_match']]}); ancak sunulan dosyada bulundu: {target}")
    return ("Örneğe girilen atıf belirtilen sayfada doğrulanamadı "
            f"({MATCH_LABELS[item['citation_match']]}); uygulama sunulan dosyalar arasında da eşleşme bulamadı")


def _missing_ref_block(data: ReportData, item: dict, docs: dict) -> str:
    doc = docs[item["referenced_in_doc"]]
    system_result = ("sunulan dosyada bulundu" if item["system_check"] == CHECK_FOUND
                     else "sunulan dosyalar arasında eşleşme bulunamadı")
    found_doc = docs.get(item["found_doc_id"]) if item["found_doc_id"] else None
    if found_doc:
        system_result += f': {_e(found_doc["title"])} ({_e(found_doc["doc_id"])})'
    resolver = item["resolver_unresolved"]
    resolver_line = ""
    if resolver is not None:
        listed = ", ".join(_e(x) for x in resolver) if resolver else "yok"
        resolver_line = ("<dt>Belge atıf çözücüsü (yalnız belgelerin referans numaralarına bakar; çözümsüz atıflar)</dt>"
                         f"<dd>{listed}</dd>")
    return (
        f'<section class="atif" id="atif-{_e(item["fact_id"])}">'
        f'<h3>Atıf: {_e(item["referenced_name"])}</h3>'
        f'<p class="birlesik"><strong>{_e(_combined_sentence(item, docs))}</strong></p>'
        "<h4>1) Örneğe önceden girilmiş atıf</h4><dl>"
        f'<dt>Hazırlayan</dt><dd class="hazirlayan">{_e(ORIGIN_LABELS[item["origin"]])}</dd>'
        f'<dt>Alıntı eşleşmesi</dt>{_match_sentence(item["citation_match"], doc, item["page"])}'
        f'<dt>Belge</dt><dd>{_e(doc["title"])} <small>(dosya: {_e(doc["file_name"])}; kimlik: {_e(doc["doc_id"])})</small></dd>'
        f'<dt>Fiziksel sayfa</dt><dd>{int(item["page"])} / {int(doc["page_count"])}</dd>'
        f'<dt>Alıntı</dt><dd><q>{_e(item["excerpt"])}</q></dd>'
        f'<dt>Bağlantı</dt>{_link(data, doc["doc_id"], item["page"])}'
        "</dl>"
        f'{_page_text_block(data, doc, item["page"], item["excerpt"], highlight=item["citation_match"] == MATCH_OK)}'
        "<h4>2) Uygulamanın denetimi</h4><dl>"
        f'<dt>Hazırlayan</dt><dd class="hazirlayan">{_e(SYSTEM_LABEL)}</dd>'
        "<dt>Yöntem</dt><dd>Atıf adı, sunulan belgelerin (atfı içeren belge hariç) kimliği, dosya adı ve başlığıyla "
        "karşılaştırıldı. Adında sayı ve sözcük birlikte bulunmayan atıflar için eşleşme aranmaz.</dd>"
        f"<dt>Sonuç</dt><dd>{system_result}</dd>"
        f"{resolver_line}</dl></section>"
    )


# ----------------------------------------------------------------
# Sayfa
# ----------------------------------------------------------------


def render_html(data: ReportData) -> str:
    record = data.record
    docs = {doc["doc_id"]: doc for doc in record["documents"]}
    matched = [f for f in record["findings"] if f["written"]]
    unmatched = [f for f in record["findings"] if not f["written"]]
    refs = record["missing_refs"]
    unmatched_refs = [r for r in refs if not r["citation_written"]]
    warnings = len(unmatched) + len(unmatched_refs)

    parts = [
        '<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8">',
        "<title>DEMO — Dosya İnceleme Raporu (sentetik)</title>",
        f"<style>{_CSS}</style></head><body>",
        '<div class="bant">DEMO — SENTETİK</div>',
        '<div class="not">Bu rapor yalnız sentetik örnek belgelerle çalışır. Hukuki sonuç, görüş veya karar içermez. '
        "Yazılım bu raporda hukuki bir sonuç cümlesi üretmez.</div>",
        "<h1>Dosya İnceleme Raporu</h1>",
        '<div class="not"><strong>Nasıl okunur?</strong> Her bulguda iki bilgi AYRI satırlardadır: '
        "<em>Hazırlayan</em> bulguyu kimin hazırladığını gösterir; <em>Alıntı eşleşmesi</em> ayrı bir kontroldür ve alıntının "
        "belirtilen belgenin belirtilen sayfasında bulunup bulunmadığını gösterir. Eşleşme, hazırlayan etiketini değiştirmez. "
        "<em>Fiziksel sayfa</em>, PDF'in kaçıncı sayfası olduğunu gösterir; belge üzerinde basılı sayfa numarasıyla "
        "aynı olmayabilir.</div>",
        f"<p>Belge: {len(record['documents'])} · Eşleşen bulgu: {len(matched)} · "
        f"Alıntısı eşleşmeyen: {warnings} · Atıf kaydı: {len(refs)}</p>",
        "<h2>Belgeler</h2><table><tr><th>Belge</th><th>Dosya</th><th>Kimlik</th><th>Fiziksel sayfa sayısı</th>"
        "<th>PDF</th></tr>",
    ]
    for doc in record["documents"]:
        uri = data.pdf_uri.get(doc["doc_id"])
        state = data.pdf_state.get(doc["doc_id"], "yok")
        cell = (f'<a href="{_e(uri)}#page=1">PDF\'i aç</a>' if uri else "PDF bulunamadı")
        if state == "degismis":
            cell += " (UYARI: hazırlamadan sonra değişmiş)"
        parts.append(f"<tr><td>{_e(doc['title'])}</td><td>{_e(doc['file_name'])}</td><td>{_e(doc['doc_id'])}</td>"
                     f"<td>{int(doc['page_count'])}</td><td>{cell}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>Bulgular</h2>")
    if matched:
        parts.append("<table><tr><th>Bulgu</th><th>Belge</th><th>Fiziksel sayfa</th><th>Hazırlayan</th>"
                     "<th>Alıntı eşleşmesi</th></tr>")
        for item in matched:
            parts.append(
                f'<tr><td><a href="#bulgu-{_e(item["fact_id"])}">{_e(item["statement"])}</a></td>'
                f'<td>{_e(docs[item["doc_id"]]["title"])}</td><td>{int(item["page"])}</td>'
                f'<td>{_e(ORIGIN_LABELS[item["origin"]])}</td><td>{MATCH_LABELS[item["match"]]}</td></tr>')
        parts.append("</table>")
        parts.extend(_finding_block(data, item, docs, warning=False) for item in matched)
    else:
        parts.append("<p>Eşleşen bulgu yok.</p>")

    parts.append("<h2>Alıntısı eşleşmeyen örnek bulgular</h2>")
    if unmatched:
        parts.append('<div class="not">UYARI: Aşağıdaki bulguların alıntısı belirtilen belgenin belirtilen sayfasında '
                     "bulunamadı. Bu bulgular olgu kaydına YAZILMADI; burada, doğrulanamadıkları için ayrıca gösterilir.</div>")
        parts.extend(_finding_block(data, item, docs, warning=True) for item in unmatched)
    elif unmatched_refs:
        parts.append("<p>Eşleşmeyen örnek bulgu yok; alıntısı eşleşmeyen kayıt yalnız aşağıdaki atıf kayıtlarındadır "
                     f"({len(unmatched_refs)}).</p>")
    else:
        parts.append("<p>Yok.</p>")

    not_found = [r for r in refs if r["system_check"] != CHECK_FOUND]
    found = [r for r in refs if r["system_check"] == CHECK_FOUND]
    parts.append("<h2>Dosyada bulunmayan atıflar</h2>")
    if not_found:
        parts.extend(_missing_ref_block(data, item, docs) for item in not_found)
    else:
        parts.append("<p>Yok.</p>")
    parts.append("<h2>Sunulan dosyalarda bulunan atıflar</h2>")
    if found:
        parts.extend(_missing_ref_block(data, item, docs) for item in found)
    else:
        parts.append("<p>Yok.</p>")

    parts.append("</body></html>")
    return "\n".join(parts) + "\n"
