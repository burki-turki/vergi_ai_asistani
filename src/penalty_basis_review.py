# ============================================================
# PENALTY-BASIS-V1 - CEZA İHBARNAMESİ / DAYANAK KARŞILAŞTIRMA RAPORU.
#
# Ürün genişletme işi; bir roadmap Row'u DEĞİLDİR. Yalnız Python
# standart kütüphanesi kullanılır; proje modülü import edilmez (hiçbir
# LOCKED katmana bağlı değildir).
#
# Girdi: tek bir klasör. İçinde `statements.json` (operatörün elle
# etiketlediği ifadeler; bkz. data/penalty_basis_statements.schema.json)
# ve bu dosyanın `documents[]` listesinde adı geçen `.txt` belgeler
# bulunur. Klasörde listede olmayan bir girdi veya listede olup klasörde
# olmayan bir belge = ret.
#
# Çıktı: tek, kendi içinde yeterli bir HTML dosyası (dış kaynak, ağ,
# JavaScript yok; girdiden gelen her metin html.escape'ten geçer).
#
# Deterministik kurallar (hepsi fail-closed):
# - Her alıntı kendi belgesinin metninde birebir (normalizasyon yok) ve
#   TAM BİR KEZ geçmelidir; çakışan geçişler de sayılır.
# - Aynı belgedeki iki alıntı çakışamaz (vurgulama tek katmanlıdır).
# - Belgeler BOM'suz, katı UTF-8 okunur; BOM = ret. \r karakterleri
#   eşleştirmede olduğu gibi kalır; HTML gösteriminde CRLF ve tek CR
#   satır sonuna (LF) çevrilir (çıktı yalnız LF içerir).
# - documents[] içinde tam bir belge `is_notice: true` (ihbarname)
#   taşır; bütün administrative_act ifadeleri (header_item taşıyanlar
#   dahil) yalnız o belgeden olabilir ve o belgeden yalnız
#   administrative_act ifadesi kabul edilir; header_item taşıyan ifade
#   sale_ref taşıyamaz. Tebliğ usulü/tarihi bu sürümde yalnız is_notice
#   belgesinden işaretlenebilir; ayrı tebliğ belgesi bu sürümün sınırıdır.
# - Bir satış ancak en az bir officer_observation ifadesi ona bağlıysa
#   "memurun tespit ettiği satış" sayılır; officer_observation ifadesi
#   sale_ref taşımak zorundadır.
# - Satış tarihi/tutarı yalnız `{value, statement_id}` biçiminde, o
#   satışa bağlı bir ifadenin alıntısında birebir ve iki yanında rakam
#   veya harf olmadan geçiyorsa kabul edilir; öbür yanında rakam olan
#   bir nokta veya virgül de sınır sayılmaz ("1.120,00 TL" içinde
#   "120,00 TL" kabul edilmez). Bir kartta yalnız o kartın rolündeki
#   ifadelere bağlı değerler gösterilir; her değerin yanında kaynağın rol
#   etiketi yazar. Mükellef beyanına bağlı değer yalnız o beyanın kendi
#   satırında görünür; ihbarnameye bağlı değer, kart içinde ihbarname
#   ifadesinin kendi satırında görünür (kartın başlığı zaten idare
#   işlemi değerlerini gösteriyorsa satırda tekrarlanmaz).
# - Hiçbir hukuki sonuç, öneri veya süre üretilmez. Ekrandaki bütün
#   sabit metinler yalnız FIXED_TEXTS içindedir.
#
# Çıktı kuralı ui/deadline_report.py'den sıkıdır: mutlak, ilk iki
# karakteri `\` veya `/` olmayan (UNC / aygıt ad alanı yok, karışık
# ayraç dahil), adı nokta veya boşlukla bitmeyen, repo DIŞI (modülün
# kendi reposu ve üst dizinlerinden herhangi birinde `.git` bulunan her
# ağaç), üst dizini var, dosya önceden yok ('x' kipi), UTF-8 BOM'suz,
# yalnız LF. İki düz `X:\…` yolun sürücü harfleri farklıysa biri
# ötekinin "içinde değil" sayılır; bunun dışında yol karşılaştırması
# yapılamazsa (önekli yol, UNC, beklenmeyen hata) ret.
# Ret: stdout boş, stderr tek satır "RAPOR REDDEDİLDİ: <sabit_kod>",
# exit != 0; belge metni / yol / istisna ayrıntısı basılmaz.
#
# Run: python src/penalty_basis_review.py --input <klasör> --output <mutlak yol>
# ============================================================

import argparse
import contextlib
import html
import json
import os
import sys
from pathlib import Path

REFUSAL_PREFIX = "RAPOR REDDEDİLDİ: "
OUTPUT_WRITTEN_PREFIX = "RAPOR YAZILDI: "
ENCODING_FAILURE_FALLBACK_LINE = b"RAPOR REDDEDILDI: INTERNAL_ERROR\n"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2

STATEMENTS_FILE_NAME = "statements.json"
MAX_STATEMENTS_BYTES = 2_000_000
MAX_DOCUMENT_BYTES = 2_000_000
MAX_EXCERPT_CHARS = 4000
MAX_DISPLAY_CHARS = 200

ROLES = (
    "complainant_allegation",
    "officer_relay",
    "officer_observation",
    "taxpayer_statement",
    "administrative_act",
)
HEADER_ITEMS = (
    "evrak_turu",
    "ceza_turu",
    "madde_no",
    "madde_basligi",
    "teblig_usulu",
    "teblig_tarihi",
)
TAGGED_BY = "operator"

REFUSAL_CODES = frozenset({
    "USAGE_ERROR",
    "OUTPUT_PATH_RELATIVE",
    "OUTPUT_PATH_INVALID",
    "OUTPUT_PARENT_MISSING",
    "OUTPUT_PATH_IN_REPO",
    "OUTPUT_PATH_IN_INPUT",
    "OUTPUT_EXISTS",
    "OUTPUT_WRITE_FAILED",
    "INPUT_DIR_INVALID",
    "INPUT_UNEXPECTED_ENTRY",
    "STATEMENTS_MISSING",
    "STATEMENTS_TOO_LARGE",
    "STATEMENTS_BOM",
    "STATEMENTS_NOT_UTF8",
    "STATEMENTS_INVALID_JSON",
    "STATEMENTS_SCHEMA_INVALID",
    "UNKNOWN_ROLE",
    "UNKNOWN_HEADER_ITEM",
    "HEADER_ITEM_ROLE_INVALID",
    "HEADER_ITEM_SALE_REF_INVALID",
    "NOTICE_DOCUMENT_COUNT_INVALID",
    "NOTICE_STATEMENT_DOCUMENT_INVALID",
    "NOTICE_DOCUMENT_ROLE_INVALID",
    "OBSERVATION_SALE_REF_MISSING",
    "DUPLICATE_ID",
    "UNKNOWN_DOCUMENT_REF",
    "UNKNOWN_SALE_REF",
    "UNKNOWN_STATEMENT_REF",
    "SALE_UNREFERENCED",
    "SALE_VALUE_STATEMENT_MISMATCH",
    "SALE_VALUE_NOT_IN_EXCERPT",
    "SALE_VALUE_NOT_DELIMITED",
    "DOCUMENT_NOT_LISTED",
    "DOCUMENT_MISSING",
    "DOCUMENT_TOO_LARGE",
    "DOCUMENT_BOM",
    "DOCUMENT_NOT_UTF8",
    "DOCUMENT_CONTROL_CHAR",
    "EXCERPT_NOT_FOUND",
    "EXCERPT_AMBIGUOUS",
    "EXCERPT_OVERLAP",
    "INTERNAL_ERROR",
})

# ------------------------------------------------------------
# SABİT METİNLER - kapalı liste. Rapordaki her sabit Türkçe ifade
# yalnız buradan gelir; yasak ifade denetimi (FORBIDDEN_PHRASES) bu
# sözlük ve üretilen HTML üzerinde testle yapılır.
# ------------------------------------------------------------
FIXED_TEXTS = {
    "doc_title": "Ceza ihbarnamesi – dayanak karşılaştırma raporu",
    "banner": (
        "Bu rapor bir okuma yardımıdır. İfadeleri operatör elle işaretlemiştir; "
        "hiçbiri doğrulanmamıştır. Rapor hukuki sonuç, öneri veya süre üretmez; "
        "nihai hukuki değerlendirme avukata aittir."
    ),
    "scope_note": (
        "Rapor yalnız 6. bölümde listelenen belgelere dayanır; bu listede yer "
        "almayan belgeler hakkında bir şey söylemez."
    ),
    "toc_title": "İçindekiler",
    "s1": "1. Evrak ve ceza türü",
    "s2": "2. Madde numarası ve başlığı",
    "s3": "3. Satışlar: ihbarname ve dayanak yan yana",
    "s4": "4. Tebliğ usulü ve tarihi",
    "s5": "5. Avukata sorular",
    "s6": "6. İncelenen belgeler",
    "s2_note": "İhbarnamede yazdığı gibi; mevzuat kaydıyla doğrulanmadı.",
    "s4_note": "Süre hesabı bu raporda yapılmaz.",
    "header_not_tagged": "Operatör bu başlık için alıntı işaretlemedi.",
    "s3_left_title": "İhbarname ne diyor",
    "s3_right_title": "Dayanak belgeler ne diyor",
    "s3_left_not_tagged": "Operatör ihbarnamenin ceza açıklaması için alıntı işaretlemedi.",
    "no_observed_sale": (
        "İncelenen belgelerde belirli bir satış veya memurun ayrıca yaptığı "
        "bir tespit görünmüyor."
    ),
    "no_observation_complaint_sale": (
        "İncelenen belgelerde memurun ayrıca yaptığı bir tespit görünmüyor; "
        "satışın tarih ve tutarı yalnız şikâyetçinin anlatımında geçiyor."
    ),
    "no_officer_finding": "İncelenen belgelerde memurun ayrıca yaptığı bir tespit görünmüyor.",
    "based_on": "Bu not şu ifadelere dayanır:",
    "no_basis_statements": "Operatör bu dosyada şikâyet veya aktarım ifadesi işaretlemedi.",
    "card_observation": "Memurun tespit ettiği satış",
    "card_complaint": "Şikâyet iddiası",
    "card_complaint_sale": "Şikâyet iddiası (operatör bir satış kaydıyla ilişkilendirdi)",
    "card_complaint_unobserved_sale": "Şikâyette anlatılan satış (memur gözlemi değil)",
    "card_taxpayer": "Mükellef beyanı",
    "sale_label": "Satış kaydı",
    "notice_sale_no_basis": (
        "Operatör, ihbarnamenin bağlandığı bu satış için dayanak belgelerde "
        "şikâyet, aktarım veya gözlem ifadesi işaretlemedi."
    ),
    "date_label": "Tarih",
    "amount_label": "Tutar",
    "value_role_source": "kaynak",
    "value_not_tagged": "operatör alıntıyla işaretlemedi",
    "act_linked": "İhbarname bu satışa bağlanmış (operatör işareti)",
    "act_sale_ref": "Operatörün bağladığı satış kaydı",
    "taxpayer_sale_ref": "Operatörün ilişkilendirdiği satış kaydı",
    "q_which_sale": "İhbarname hangi satış için düzenlenmiş?",
    "q_notice_sale_basis": (
        "İhbarnamenin bağlandığı satış dayanak belgelerin hangi satırında geçiyor?"
    ),
    "q_header_not_tagged": (
        "Operatör şu başlık için alıntı işaretlemedi: {label}. Bu bilgi "
        "ihbarnamenin hangi yerinde yazıyor?"
    ),
    "no_questions": "Bu dosya için kurala bağlı bir soru üretilmedi.",
    "tagged_note": "işaretleyen: operatör, doğrulanmadı",
    "source_label": "Kaynak",
    "section_label": "belgedeki bölüm",
    "goto_doc": "belgedeki yerine git",
    "doc_type_label": "Belge türü",
    "doc_file_label": "Dosya adı",
    "doc_fulltext": "Belgenin tam metni",
    "back_to_top": "başa dön",
    "role.complainant_allegation": "Şikâyetçi iddiası",
    "role.officer_relay": "Memurun aktarımı",
    "role.officer_observation": "Memurun gözlemi",
    "role.taxpayer_statement": "Mükellef beyanı",
    "role.administrative_act": "İdare işlemi",
    "header.evrak_turu": "Evrak türü",
    "header.ceza_turu": "Ceza türü",
    "header.madde_no": "Madde numarası",
    "header.madde_basligi": "Madde başlığı",
    "header.teblig_usulu": "Tebliğ usulü",
    "header.teblig_tarihi": "Tebliğ tarihi",
}

# Rapor metninde asla geçmemesi gereken ifadeler (testle denetlenir).
FORBIDDEN_PHRASES = (
    "mevcut değil",
    "bulunmamaktadır",
    "hukuka aykırı",
    "hukuka uygun",
    "yerindedir",
    "kesinlikle",
    "iptal edilmeli",
    "kazan",
)

SECTION_HEADER_ITEMS = {
    "b1": ("evrak_turu", "ceza_turu"),
    "b2": ("madde_no", "madde_basligi"),
    "b4": ("teblig_usulu", "teblig_tarihi"),
}

_ID_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
_FILE_NAME_CHARS = _ID_CHARS | {"."}
_ALLOWED_CONTROL = frozenset("\n\r\t")

_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;max-width:1100px;margin:0 auto;padding:16px;color:#1b1b1b;line-height:1.45}
h1{font-size:1.5em;margin-bottom:4px}
h2{border-bottom:2px solid #444;padding-bottom:4px;margin-top:32px}
.banner{background:#fff4d6;border:1px solid #d9a400;padding:10px;margin:12px 0}
.note{font-style:italic;color:#444}
.toc a{margin-right:12px}
.cols{display:flex;gap:16px;align-items:flex-start}
.col{flex:1;min-width:0}
.card{border:1px solid #888;border-radius:6px;padding:10px;margin:10px 0;background:#fafafa}
.card h4{margin:0 0 8px 0}
.card-observation{border-left:6px solid #1f5fbf}
.card-complaint{border-left:6px solid #8a8a8a}
.card-taxpayer{border-left:6px solid #2e8b57;background:#eef8f1}
.stmt{border:1px solid #ccc;border-radius:4px;padding:8px;margin:8px 0;background:#fff}
.stmt-role{font-weight:bold;font-size:.9em}
.stmt blockquote{margin:6px 0;padding:4px 10px;border-left:3px solid #999;white-space:pre-wrap}
.stmt-meta{font-size:.85em;color:#444}
.role-complainant_allegation .stmt-role{color:#8a4b00}
.role-officer_relay .stmt-role{color:#6b5b00}
.role-officer_observation .stmt-role{color:#1f5fbf}
.role-administrative_act .stmt-role{color:#7a1f1f}
.stmt.role-taxpayer_statement{background:#eef8f1;border-color:#2e8b57}
.role-taxpayer_statement .stmt-role{color:#1e6b40}
.act-link{border-top:1px dashed #7a1f1f;margin-top:8px;padding-top:6px}
.sale-values{margin:4px 0 8px 0}
.doc{border-top:1px solid #bbb;margin-top:18px}
pre.doctext{white-space:pre-wrap;background:#f6f6f6;border:1px solid #ddd;padding:10px;font-family:Consolas,monospace;font-size:.9em}
mark{background:#ffe680;scroll-margin-top:80px}
mark.role-taxpayer_statement{background:#bfe8cc}
mark:target{background:#ffb84d;outline:3px solid #c05800}
""".strip("\n")


class ReportRefused(Exception):
    """Every refusal. `code` is always one of REFUSAL_CODES - the ONLY
    thing ever shown to the operator."""

    def __init__(self, code: str):
        if code not in REFUSAL_CODES:
            code = "INTERNAL_ERROR"
        self.code = code
        super().__init__(code)


class _UsageError(Exception):
    pass


class _HelpRequested(Exception):
    def __init__(self, text: str):
        self.text = text
        super().__init__("help")


class _NonExitingArgumentParser(argparse.ArgumentParser):
    """argparse never calls sys.exit() and never echoes argument values;
    every usage problem becomes the single fixed refusal USAGE_ERROR."""

    def error(self, message: str) -> None:  # noqa: D102
        raise _UsageError()

    def exit(self, status: int = 0, message: str | None = None) -> None:  # noqa: D102
        raise _UsageError()

    def print_help(self, file=None) -> None:  # noqa: D102
        raise _HelpRequested(self.format_help())


def _build_arg_parser():
    parser = _NonExitingArgumentParser(
        prog="python src/penalty_basis_review.py",
        description=(
            "Ceza ihbarnamesi - dayanak karşılaştırma raporu (salt-okunur). "
            "Girdi klasöründeki statements.json ve belgelerden tek bir HTML yazar."
        ),
    )
    parser.add_argument("--input", dest="input_dir", required=True)
    parser.add_argument(
        "--output", dest="output", required=True,
        help="Mutlak, repo DIŞI, henüz var olmayan dosya yolu (üst dizin önceden mevcut olmalı).",
    )
    return parser


# ============================================================
# OUTPUT TARGET (repo-dışı, yalnız-oluştur)
# ============================================================

def _plain_drive_letter(norm: str):
    """The drive letter of a plain `X:\\...` path, else None (prefixed
    `\\\\?\\` / `\\\\.\\` forms and UNC paths are not plain)."""
    if len(norm) >= 3 and norm[0].isascii() and norm[0].isalpha() and norm[1] == ":" and norm[2] == "\\":
        return norm[0]
    return None


def _is_within(child, root) -> bool:
    """Two plain `X:\\...` paths on different drive letters: "not within".
    Every other comparison that cannot be made (`\\\\?\\` vs plain form,
    UNC, unexpected error) is a refusal, never "not within"."""
    try:
        child_norm = os.path.normcase(os.path.abspath(str(child)))
        root_norm = os.path.normcase(os.path.abspath(str(root)))
        child_drive = _plain_drive_letter(child_norm)
        root_drive = _plain_drive_letter(root_norm)
        if child_drive is not None and root_drive is not None and child_drive != root_drive:
            return False
        return os.path.commonpath([child_norm, root_norm]) == root_norm
    except Exception:
        raise ReportRefused("OUTPUT_PATH_INVALID") from None


def _repo_root_real() -> Path:
    return Path(__file__).resolve(strict=True).parents[1]


def _is_in_any_repo(path_real: Path) -> bool:
    """The module's own repository, or any directory tree that has a
    `.git` entry (directory or file) in the path itself or one of its
    ancestors (main repository, other working copies)."""
    if _is_within(path_real, _repo_root_real()):
        return True
    try:
        return any(
            os.path.lexists(os.path.join(str(ancestor), ".git"))
            for ancestor in (path_real, *path_real.parents)
        )
    except Exception:
        raise ReportRefused("OUTPUT_PATH_INVALID") from None


def _prepare_output_target(raw: str) -> Path:
    """Pure pre-check, performed BEFORE any input is read. Existence is
    re-enforced atomically by open(..., "x") in _write_output_file()."""
    if not raw or "\x00" in raw:
        raise ReportRefused("OUTPUT_PATH_INVALID")
    # UNC (\\server\share, //server/share) and device namespace
    # (\\?\, \\.\) paths, mixed separators included (/\.\, \/?\), are
    # refused before anything touches them.
    if len(raw) >= 2 and raw[0] in "\\/" and raw[1] in "\\/":
        raise ReportRefused("OUTPUT_PATH_INVALID")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise ReportRefused("OUTPUT_PATH_RELATIVE")
    name = candidate.name
    if name in ("", ".", "..") or ":" in name or name.endswith((".", " ")):
        raise ReportRefused("OUTPUT_PATH_INVALID")
    try:
        parent_real = candidate.parent.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ReportRefused("OUTPUT_PARENT_MISSING") from None
    if not parent_real.is_dir():
        raise ReportRefused("OUTPUT_PARENT_MISSING")
    target = parent_real / name
    if _is_in_any_repo(parent_real) or _is_in_any_repo(target):
        raise ReportRefused("OUTPUT_PATH_IN_REPO")
    if os.path.lexists(target):
        raise ReportRefused("OUTPUT_EXISTS")
    return target


def _write_output_file(target: Path, text: str) -> None:
    try:
        handle = open(target, "x", encoding="utf-8", newline="")
    except FileExistsError:
        raise ReportRefused("OUTPUT_EXISTS") from None
    except OSError:
        raise ReportRefused("OUTPUT_WRITE_FAILED") from None
    created_ok = False
    try:
        # Post-create containment re-check (a parent swapped for a link
        # into the repository between pre-check and open is refused and
        # the file this call itself just created is removed).
        if _is_in_any_repo(Path(target).resolve(strict=True)):
            raise ReportRefused("OUTPUT_PATH_IN_REPO")
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        created_ok = True
    except ReportRefused:
        raise
    except Exception:
        raise ReportRefused("OUTPUT_WRITE_FAILED") from None
    finally:
        handle.close()
        if not created_ok:
            with contextlib.suppress(OSError):
                os.unlink(target)


# ============================================================
# INPUT READING AND VALIDATION
# ============================================================

def _resolve_input_dir(raw: str) -> Path:
    if not raw or "\x00" in raw:
        raise ReportRefused("INPUT_DIR_INVALID")
    try:
        real = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError):
        raise ReportRefused("INPUT_DIR_INVALID") from None
    if not real.is_dir():
        raise ReportRefused("INPUT_DIR_INVALID")
    return real


def _read_limited(path: Path, limit: int, too_large_code: str) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ReportRefused(too_large_code)
    return data


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _reject_constant(_name):
    raise ValueError("non-finite number")


def _has_bad_control(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if (code < 0x20 or 0x7F <= code < 0xA0) and ch not in _ALLOWED_CONTROL:
            return True
    return False


def _is_id(value) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and all(ch in _ID_CHARS for ch in value)
    )


def _is_file_name(value) -> bool:
    if not isinstance(value, str) or not (5 <= len(value) <= 100):
        return False
    if value == STATEMENTS_FILE_NAME or not value.endswith(".txt"):
        return False
    if value[0] == "." or not all(ch in _FILE_NAME_CHARS for ch in value):
        return False
    return Path(value).name == value


def _is_display_text(value, max_len=MAX_DISPLAY_CHARS) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= max_len
        and value.strip() != ""
        and not _has_bad_control(value)
    )


def _require_object(value, required, optional=()):
    if not isinstance(value, dict):
        raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
    keys = set(value)
    if not set(required) <= keys or not keys <= set(required) | set(optional):
        raise ReportRefused("STATEMENTS_SCHEMA_INVALID")


def _load_statements(input_dir: Path) -> dict:
    path = input_dir / STATEMENTS_FILE_NAME
    if path.is_symlink() or not path.is_file():
        raise ReportRefused("STATEMENTS_MISSING")
    try:
        data = _read_limited(path, MAX_STATEMENTS_BYTES, "STATEMENTS_TOO_LARGE")
    except ReportRefused:
        raise
    except OSError:
        raise ReportRefused("STATEMENTS_MISSING") from None
    if data.startswith(b"\xef\xbb\xbf"):
        raise ReportRefused("STATEMENTS_BOM")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ReportRefused("STATEMENTS_NOT_UTF8") from None
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise ReportRefused("STATEMENTS_INVALID_JSON") from None


def _occurs_delimited(value: str, excerpt: str) -> bool:
    """At least one occurrence of `value` in `excerpt` whose neighbouring
    characters (if any) are neither digits nor letters, nor a "." or ","
    with a digit on its other side: "20,00 TL" inside "120,00 TL" and
    "120,00 TL" / "1" / "00 TL" inside "1.120,00 TL" do not count."""
    start = excerpt.find(value)
    while start >= 0:
        end = start + len(value)
        before_ok = start == 0 or not (
            excerpt[start - 1].isalnum()
            or (excerpt[start - 1] in ".," and start >= 2 and excerpt[start - 2].isdigit())
        )
        after_ok = end == len(excerpt) or not (
            excerpt[end].isalnum()
            or (excerpt[end] in ".," and end + 1 < len(excerpt) and excerpt[end + 1].isdigit())
        )
        if before_ok and after_ok:
            return True
        start = excerpt.find(value, start + 1)
    return False


def _validate_sale_value(value) -> None:
    _require_object(value, ("value", "statement_id"))
    if not _is_display_text(value["value"]) or not _is_id(value["statement_id"]):
        raise ReportRefused("STATEMENTS_SCHEMA_INVALID")


def _validate_structure(doc) -> dict:
    """Hand-written mirror of data/penalty_basis_statements.schema.json
    plus the referential rules a schema cannot express. Returns an
    index used by rendering."""
    _require_object(doc, ("schema_version", "documents", "statements", "sales"))
    version = doc["schema_version"]
    if type(version) is not int or version != 1:
        raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
    documents, statements, sales = doc["documents"], doc["statements"], doc["sales"]
    if not isinstance(documents, list) or not documents:
        raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
    if not isinstance(statements, list) or not statements:
        raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
    if not isinstance(sales, list):
        raise ReportRefused("STATEMENTS_SCHEMA_INVALID")

    for item in documents:
        _require_object(item, ("document_id", "file_name", "title", "document_type"), ("is_notice",))
        if not _is_id(item["document_id"]) or not _is_file_name(item["file_name"]):
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
        if not _is_display_text(item["title"]) or not _is_display_text(item["document_type"]):
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
        if "is_notice" in item and type(item["is_notice"]) is not bool:
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")

    for item in statements:
        _require_object(
            item,
            ("statement_id", "document_id", "excerpt", "role", "tagged_by"),
            ("section", "sale_ref", "header_item"),
        )
        if not _is_id(item["statement_id"]) or not _is_id(item["document_id"]):
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
        if not _is_display_text(item["excerpt"], MAX_EXCERPT_CHARS):
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
        if item["tagged_by"] != TAGGED_BY:
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
        if "section" in item and not _is_display_text(item["section"]):
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
        if "sale_ref" in item and not _is_id(item["sale_ref"]):
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
        role = item["role"]
        if not isinstance(role, str):
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
        if role not in ROLES:
            raise ReportRefused("UNKNOWN_ROLE")
        if "header_item" in item:
            header_item = item["header_item"]
            if not isinstance(header_item, str):
                raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
            if header_item not in HEADER_ITEMS:
                raise ReportRefused("UNKNOWN_HEADER_ITEM")
            if role != "administrative_act":
                raise ReportRefused("HEADER_ITEM_ROLE_INVALID")
            if "sale_ref" in item:
                raise ReportRefused("HEADER_ITEM_SALE_REF_INVALID")
        if role == "officer_observation" and "sale_ref" not in item:
            raise ReportRefused("OBSERVATION_SALE_REF_MISSING")

    for item in sales:
        _require_object(item, ("sale_id",), ("date", "amount"))
        if not _is_id(item["sale_id"]):
            raise ReportRefused("STATEMENTS_SCHEMA_INVALID")
        for key in ("date", "amount"):
            if key in item:
                _validate_sale_value(item[key])

    doc_by_id, stmt_by_id, sale_by_id = {}, {}, {}
    file_names = set()
    for item in documents:
        if item["document_id"] in doc_by_id or item["file_name"] in file_names:
            raise ReportRefused("DUPLICATE_ID")
        doc_by_id[item["document_id"]] = item
        file_names.add(item["file_name"])
    for item in statements:
        if item["statement_id"] in stmt_by_id:
            raise ReportRefused("DUPLICATE_ID")
        stmt_by_id[item["statement_id"]] = item
    for item in sales:
        if item["sale_id"] in sale_by_id:
            raise ReportRefused("DUPLICATE_ID")
        sale_by_id[item["sale_id"]] = item

    for item in statements:
        if item["document_id"] not in doc_by_id:
            raise ReportRefused("UNKNOWN_DOCUMENT_REF")
        if "sale_ref" in item and item["sale_ref"] not in sale_by_id:
            raise ReportRefused("UNKNOWN_SALE_REF")

    notice_ids = [item["document_id"] for item in documents if item.get("is_notice") is True]
    if len(notice_ids) != 1:
        raise ReportRefused("NOTICE_DOCUMENT_COUNT_INVALID")
    for item in statements:
        if item["role"] == "administrative_act" and item["document_id"] != notice_ids[0]:
            raise ReportRefused("NOTICE_STATEMENT_DOCUMENT_INVALID")
        if item["document_id"] == notice_ids[0] and item["role"] != "administrative_act":
            raise ReportRefused("NOTICE_DOCUMENT_ROLE_INVALID")

    referenced_sales = {item["sale_ref"] for item in statements if "sale_ref" in item}
    for item in sales:
        if item["sale_id"] not in referenced_sales:
            raise ReportRefused("SALE_UNREFERENCED")
        for key in ("date", "amount"):
            if key not in item:
                continue
            bound = stmt_by_id.get(item[key]["statement_id"])
            if bound is None:
                raise ReportRefused("UNKNOWN_STATEMENT_REF")
            if bound.get("sale_ref") != item["sale_id"]:
                raise ReportRefused("SALE_VALUE_STATEMENT_MISMATCH")
            if item[key]["value"] not in bound["excerpt"]:
                raise ReportRefused("SALE_VALUE_NOT_IN_EXCERPT")
            if not _occurs_delimited(item[key]["value"], bound["excerpt"]):
                raise ReportRefused("SALE_VALUE_NOT_DELIMITED")

    return {
        "documents": documents,
        "statements": statements,
        "sales": sales,
        "doc_by_id": doc_by_id,
        "stmt_by_id": stmt_by_id,
        "sale_by_id": sale_by_id,
    }


def _check_directory_listing(input_dir: Path, documents) -> None:
    listed = {item["file_name"] for item in documents}
    present = set()
    try:
        with os.scandir(input_dir) as entries:
            for entry in entries:
                if entry.name == STATEMENTS_FILE_NAME:
                    continue
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    raise ReportRefused("INPUT_UNEXPECTED_ENTRY")
                present.add(entry.name)
    except ReportRefused:
        raise
    except OSError:
        raise ReportRefused("INPUT_DIR_INVALID") from None
    # Exact string comparison (no case folding even on NTFS).
    if present - listed:
        raise ReportRefused("DOCUMENT_NOT_LISTED")
    if listed - present:
        raise ReportRefused("DOCUMENT_MISSING")


def _load_document_texts(input_dir: Path, documents) -> dict:
    texts = {}
    for item in documents:
        path = input_dir / item["file_name"]
        try:
            data = _read_limited(path, MAX_DOCUMENT_BYTES, "DOCUMENT_TOO_LARGE")
        except ReportRefused:
            raise
        except OSError:
            raise ReportRefused("DOCUMENT_MISSING") from None
        if data.startswith(b"\xef\xbb\xbf"):
            raise ReportRefused("DOCUMENT_BOM")
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ReportRefused("DOCUMENT_NOT_UTF8") from None
        if _has_bad_control(text):
            raise ReportRefused("DOCUMENT_CONTROL_CHAR")
        texts[item["document_id"]] = text
    return texts


def _locate_excerpts(statements, texts) -> dict:
    """Exactly-once match (overlapping occurrences count) and no overlap
    between two excerpts of the same document. Returns
    {document_id: [(start, end, statement), ...]} sorted by start."""
    spans = {}
    for item in statements:
        text = texts[item["document_id"]]
        excerpt = item["excerpt"]
        first = text.find(excerpt)
        if first < 0:
            raise ReportRefused("EXCERPT_NOT_FOUND")
        if text.find(excerpt, first + 1) >= 0:
            raise ReportRefused("EXCERPT_AMBIGUOUS")
        spans.setdefault(item["document_id"], []).append((first, first + len(excerpt), item))
    for doc_spans in spans.values():
        doc_spans.sort(key=lambda span: span[0])
        for previous, current in zip(doc_spans, doc_spans[1:]):
            if current[0] < previous[1]:
                raise ReportRefused("EXCERPT_OVERLAP")
    return spans


# ============================================================
# RENDERING
# ============================================================

def _t(key: str) -> str:
    return html.escape(FIXED_TEXTS[key], quote=True)


def _d(text: str) -> str:
    """Input-derived text for display: CRLF, then a lone CR, become LF
    (display only), then escaped."""
    return html.escape(text.replace("\r\n", "\n").replace("\r", "\n"), quote=True)


def _d_slice(text: str, start: int, end: int) -> str:
    """_d of text[start:end]; a CR whose LF starts the next slice is left
    to that LF, so a CRLF split by a highlight boundary stays one line
    break."""
    if start < end < len(text) and text[end - 1] == "\r" and text[end] == "\n":
        end -= 1
    return _d(text[start:end])


def _value_html(bound, index) -> str:
    role = index["stmt_by_id"][bound["statement_id"]]["role"]
    return (
        f'{_d(bound["value"])} ({_t("value_role_source")}: '
        f'<a href="#s-{bound["statement_id"]}">{_t("role." + role)}</a>)'
    )


def _render_statement(item, index, show_act_values=False) -> str:
    doc = index["doc_by_id"][item["document_id"]]
    sid = item["statement_id"]
    meta = [f'{_t("source_label")}: {_d(doc["title"])}']
    if "section" in item:
        meta.append(f'{_t("section_label")}: {_d(item["section"])}')
    meta.append(f'<a href="#s-{sid}">{_t("goto_doc")}</a>')
    meta.append(_t("tagged_note"))
    # A sale value bound to a taxpayer statement is shown only here, on
    # the statement's own row, with its own role label. A value bound to
    # a notice statement is shown the same way when the caller asks for
    # it (inside a card whose header does not show notice values).
    own_values = ""
    if item["role"] == "taxpayer_statement" or (
        show_act_values and item["role"] == "administrative_act"
    ):
        rows = []
        for sale in index["sales"]:
            for key, label_key in (("date", "date_label"), ("amount", "amount_label")):
                if key in sale and sale[key]["statement_id"] == sid:
                    rows.append(f"<div>{_t(label_key)}: {_value_html(sale[key], index)}</div>")
        if rows:
            own_values = f'<div class="sale-values">{"".join(rows)}</div>'
    return (
        f'<div class="stmt role-{item["role"]}">'
        f'<div class="stmt-role">{_t("role." + item["role"])}</div>'
        f'<blockquote>{_d(item["excerpt"])}</blockquote>'
        f"{own_values}"
        f'<div class="stmt-meta">{" · ".join(meta)}</div>'
        f"</div>\n"
    )


def _render_sale_values(sale, index, card_roles) -> str:
    """Only values bound to a statement whose role belongs to this card
    are shown; any other binding reads as "not tagged" here."""
    rows = []
    for key, label_key in (("date", "date_label"), ("amount", "amount_label")):
        bound = sale.get(key)
        if bound is not None and index["stmt_by_id"][bound["statement_id"]]["role"] in card_roles:
            value_html = _value_html(bound, index)
        else:
            value_html = _t("value_not_tagged")
        rows.append(f"<div>{_t(label_key)}: {value_html}</div>")
    return f'<div class="sale-values">{"".join(rows)}</div>\n'


def _render_act_links(acts, index, card_roles) -> str:
    """Notice statements linked to the card's sale. Their bound values are
    shown on their own row unless the card header already shows notice
    values (so one value never appears twice in one card)."""
    if not acts:
        return ""
    show_act_values = "administrative_act" not in card_roles
    body = "".join(_render_statement(item, index, show_act_values) for item in acts)
    return f'<div class="act-link"><strong>{_t("act_linked")}</strong>\n{body}</div>\n'


def _render_card(css_class, title_html, inner) -> str:
    return f'<div class="card {css_class}"><h4>{title_html}</h4>\n{inner}</div>\n'


def _sale_title(title_key, sale_id) -> str:
    return f'{_t(title_key)} — {_t("sale_label")}: {_d(sale_id)}'


def _observed_sale_ids(index) -> list:
    observed = {
        item["sale_ref"] for item in index["statements"]
        if item["role"] == "officer_observation"
    }
    return [sale["sale_id"] for sale in index["sales"] if sale["sale_id"] in observed]


def _acts_for_sale(index, sale_id) -> list:
    return [
        item for item in index["statements"]
        if item["role"] == "administrative_act" and item.get("sale_ref") == sale_id
    ]


def _taxpayer_for_sale(index, sale_id) -> list:
    return [
        item for item in index["statements"]
        if item["role"] == "taxpayer_statement" and item.get("sale_ref") == sale_id
    ]


def _render_taxpayer_card(index, placed_ids=frozenset()) -> str:
    taxpayer = [
        item for item in index["statements"]
        if item["role"] == "taxpayer_statement" and item["statement_id"] not in placed_ids
    ]
    if not taxpayer:
        return ""
    parts = []
    for item in taxpayer:
        if "sale_ref" in item:
            parts.append(f'<div>{_t("taxpayer_sale_ref")}: {_d(item["sale_ref"])}</div>\n')
        parts.append(_render_statement(item, index))
    return _render_card("card-taxpayer", _t("card_taxpayer"), "".join(parts))


COMPLAINT_ROLES = ("complainant_allegation", "officer_relay")
OBSERVATION_ROLES = ("officer_observation",)
NOTICE_ROLES = ("administrative_act",)


def _notice_sales_without_basis(index) -> list:
    """Sales the notice (administrative_act) is linked to while no
    complaint, relay or observation statement references them."""
    statements = index["statements"]
    act_linked = {
        item["sale_ref"] for item in statements
        if item["role"] == "administrative_act" and "sale_ref" in item
    }
    basis_linked = {
        item["sale_ref"] for item in statements
        if item["role"] in COMPLAINT_ROLES + OBSERVATION_ROLES and "sale_ref" in item
    }
    return [
        sale["sale_id"] for sale in index["sales"]
        if sale["sale_id"] in act_linked and sale["sale_id"] not in basis_linked
    ]


def _no_observation_sentence_key(index) -> str:
    """First sentence of the right column when no sale is observed:
    (1) no sale record at all -> no_observed_sale;
    (2) exactly one sale record, at least one complaint/relay statement
        linked to it, and BOTH its date and amount bound to
        complaint/relay statements -> no_observation_complaint_sale (R-1);
    (3) every other case -> no_officer_finding (R-5)."""
    sales = index["sales"]
    if not sales:
        return "no_observed_sale"
    if len(sales) == 1:
        sale = sales[0]
        complaint_linked = any(
            item["role"] in COMPLAINT_ROLES and item.get("sale_ref") == sale["sale_id"]
            for item in index["statements"]
        )
        has_both_values = "date" in sale and "amount" in sale
        values_from_complaint = has_both_values and all(
            index["stmt_by_id"][sale[key]["statement_id"]]["role"] in COMPLAINT_ROLES
            for key in ("date", "amount")
        )
        if complaint_linked and has_both_values and values_from_complaint:
            return "no_observation_complaint_sale"
    return "no_officer_finding"


def _render_unobserved_sale_inner(index, sale_id, card_roles, head, placed_taxpayer) -> str:
    """Card body for a sale no officer_observation references: its own
    role's values, the given head statements, the taxpayer statements and
    the notice statements linked to the sale."""
    taxpayer = _taxpayer_for_sale(index, sale_id)
    placed_taxpayer.update(item["statement_id"] for item in taxpayer)
    return (
        _render_sale_values(index["sale_by_id"][sale_id], index, card_roles)
        + head
        + "".join(_render_statement(item, index) for item in taxpayer)
        + _render_act_links(_acts_for_sale(index, sale_id), index, card_roles)
    )


def _render_notice_sale_cards(index, placed_taxpayer) -> str:
    parts = []
    for sale_id in _notice_sales_without_basis(index):
        inner = _render_unobserved_sale_inner(
            index, sale_id, NOTICE_ROLES,
            f'<p>{_t("notice_sale_no_basis")}</p>\n', placed_taxpayer,
        )
        parts.append(_render_card("card-notice-sale", f'{_t("sale_label")}: {_d(sale_id)}', inner))
    return "".join(parts)


def _render_section_3_right(index) -> str:
    statements = index["statements"]
    observed_ids = _observed_sale_ids(index)
    # Complaint statements: complainant_allegation + officer_relay. They
    # are never merged into an observation card.
    complaint = [item for item in statements if item["role"] in COMPLAINT_ROLES]
    unlinked = [item for item in complaint if "sale_ref" not in item]
    complaint_sale_ids = [
        sale["sale_id"] for sale in index["sales"]
        if any(item.get("sale_ref") == sale["sale_id"] for item in complaint)
    ]
    # A taxpayer_statement linked to a sale is shown (in its own colour)
    # inside that sale's card: the observation card when the sale is
    # observed, otherwise its complaint or notice card. Everything else
    # goes to the separate taxpayer card.
    placed_taxpayer = set()
    parts = []

    def complaint_sale_card(sale_id, title_key):
        linked = "".join(
            _render_statement(item, index) for item in complaint if item.get("sale_ref") == sale_id
        )
        if sale_id in observed_ids:
            inner = _render_sale_values(index["sale_by_id"][sale_id], index, COMPLAINT_ROLES) + linked
        else:
            inner = _render_unobserved_sale_inner(index, sale_id, COMPLAINT_ROLES, linked, placed_taxpayer)
        return _render_card("card-complaint", _sale_title(title_key, sale_id), inner)

    if not observed_ids:
        parts.append(f'<p class="no-observed-sale">{_t(_no_observation_sentence_key(index))}</p>\n')
        if complaint:
            parts.append(f'<p>{_t("based_on")}</p>\n')
            parts.append("".join(_render_statement(item, index) for item in unlinked))
        else:
            parts.append(f'<p>{_t("no_basis_statements")}</p>\n')
        for sale_id in complaint_sale_ids:
            parts.append(complaint_sale_card(sale_id, "card_complaint_unobserved_sale"))
        parts.append(_render_notice_sale_cards(index, placed_taxpayer))
        parts.append(_render_taxpayer_card(index, placed_taxpayer))
        return "".join(parts)

    if unlinked:
        parts.append(_render_card(
            "card-complaint", _t("card_complaint"),
            "".join(_render_statement(item, index) for item in unlinked),
        ))
    for sale_id in complaint_sale_ids:
        parts.append(complaint_sale_card(sale_id, "card_complaint_sale"))

    for sale_id in observed_ids:
        sale = index["sale_by_id"][sale_id]
        observations = [
            item for item in statements
            if item["role"] == "officer_observation" and item["sale_ref"] == sale_id
        ]
        taxpayer = _taxpayer_for_sale(index, sale_id)
        placed_taxpayer.update(item["statement_id"] for item in taxpayer)
        inner = (
            _render_sale_values(sale, index, OBSERVATION_ROLES)
            + "".join(_render_statement(item, index) for item in observations)
            + "".join(_render_statement(item, index) for item in taxpayer)
            + _render_act_links(_acts_for_sale(index, sale_id), index, OBSERVATION_ROLES)
        )
        parts.append(_render_card("card-observation", _sale_title("card_observation", sale_id), inner))

    parts.append(_render_notice_sale_cards(index, placed_taxpayer))
    parts.append(_render_taxpayer_card(index, placed_taxpayer))
    return "".join(parts)


def _render_section_3(index) -> str:
    acts = [
        item for item in index["statements"]
        if item["role"] == "administrative_act" and "header_item" not in item
    ]
    if acts:
        left_parts = []
        for item in acts:
            left_parts.append(_render_statement(item, index))
            if "sale_ref" in item:
                left_parts.append(f'<div>{_t("act_sale_ref")}: {_d(item["sale_ref"])}</div>\n')
        left = "".join(left_parts)
    else:
        left = f'<p>{_t("s3_left_not_tagged")}</p>\n'
    return (
        '<div class="cols">'
        f'<div class="col"><h3>{_t("s3_left_title")}</h3>\n{left}</div>'
        f'<div class="col"><h3>{_t("s3_right_title")}</h3>\n{_render_section_3_right(index)}</div>'
        "</div>\n"
    )


def _render_header_items(index, header_items) -> str:
    parts = []
    for header_item in header_items:
        tagged = [item for item in index["statements"] if item.get("header_item") == header_item]
        parts.append(f'<h3>{_t("header." + header_item)}</h3>\n')
        if tagged:
            parts.append("".join(_render_statement(item, index) for item in tagged))
        else:
            parts.append(f'<p>{_t("header_not_tagged")}</p>\n')
    return "".join(parts)


def _questions(index) -> list:
    questions = []
    if _observed_sale_ids(index) and not any(
        item["role"] == "administrative_act" and "sale_ref" in item
        for item in index["statements"]
    ):
        questions.append(FIXED_TEXTS["q_which_sale"])
    if _notice_sales_without_basis(index):
        questions.append(FIXED_TEXTS["q_notice_sale_basis"])
    tagged_items = {item["header_item"] for item in index["statements"] if "header_item" in item}
    for header_item in HEADER_ITEMS:
        if header_item not in tagged_items:
            questions.append(
                FIXED_TEXTS["q_header_not_tagged"].format(label=FIXED_TEXTS["header." + header_item])
            )
    return questions


def _render_section_5(index) -> str:
    questions = _questions(index)
    if not questions:
        return f'<p>{_t("no_questions")}</p>\n'
    items = "".join(f"<li>{html.escape(text, quote=True)}</li>\n" for text in questions)
    return f'<ol class="questions">\n{items}</ol>\n'


def _render_document_text(text, doc_spans) -> str:
    out = []
    cursor = 0
    for start, end, item in doc_spans:
        out.append(_d_slice(text, cursor, start))
        out.append(
            f'<mark id="s-{item["statement_id"]}" class="role-{item["role"]}">'
            f"{_d_slice(text, start, end)}</mark>"
        )
        cursor = end
    out.append(_d_slice(text, cursor, len(text)))
    return "".join(out)


def _render_section_6(index, texts, spans) -> str:
    parts = []
    for doc in index["documents"]:
        doc_id = doc["document_id"]
        parts.append(
            f'<div class="doc" id="d-{doc_id}">'
            f'<h3>{_d(doc["title"])}</h3>\n'
            f'<div>{_t("doc_type_label")}: {_d(doc["document_type"])} · '
            f'{_t("doc_file_label")}: {_d(doc["file_name"])}</div>\n'
            f'<div class="note">{_t("doc_fulltext")}</div>\n'
            f'<pre class="doctext">{_render_document_text(texts[doc_id], spans.get(doc_id, []))}</pre>\n'
            f'<a href="#top">{_t("back_to_top")}</a>'
            "</div>\n"
        )
    return "".join(parts)


def _section(anchor, title_key, body, note_key=None) -> str:
    note = f'<p class="note">{_t(note_key)}</p>\n' if note_key else ""
    return f'<section id="{anchor}">\n<h2>{_t(title_key)}</h2>\n{note}{body}</section>\n'


def render_report(index, texts, spans) -> str:
    toc = " ".join(
        f'<a href="#b{n}">{_t("s" + str(n))}</a>' for n in range(1, 7)
    )
    body = "".join((
        _section("b1", "s1", _render_header_items(index, SECTION_HEADER_ITEMS["b1"])),
        _section("b2", "s2", _render_header_items(index, SECTION_HEADER_ITEMS["b2"]), "s2_note"),
        _section("b3", "s3", _render_section_3(index)),
        _section("b4", "s4", _render_header_items(index, SECTION_HEADER_ITEMS["b4"]), "s4_note"),
        _section("b5", "s5", _render_section_5(index)),
        _section("b6", "s6", _render_section_6(index, texts, spans), "scope_note"),
    ))
    document = (
        "<!DOCTYPE html>\n"
        '<html lang="tr">\n<head>\n<meta charset="utf-8">\n'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">\n"
        f'<title>{_t("doc_title")}</title>\n'
        f"<style>\n{_CSS}\n</style>\n</head>\n<body>\n"
        f'<h1 id="top">{_t("doc_title")}</h1>\n'
        f'<div class="banner">{_t("banner")}</div>\n'
        f'<p class="note">{_t("scope_note")}</p>\n'
        f'<nav class="toc"><strong>{_t("toc_title")}:</strong> {toc}</nav>\n'
        f"{body}"
        "</body>\n</html>\n"
    )
    if "\r" in document:
        raise ReportRefused("INTERNAL_ERROR")
    return document


def build_report(input_dir_raw: str) -> str:
    input_dir = _resolve_input_dir(input_dir_raw)
    index = _validate_structure(_load_statements(input_dir))
    _check_directory_listing(input_dir, index["documents"])
    texts = _load_document_texts(input_dir, index["documents"])
    spans = _locate_excerpts(index["statements"], texts)
    return render_report(index, texts, spans)


def main(argv: list[str] | None = None, *, stdout=None, stderr=None) -> int:
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    try:
        args = _build_arg_parser().parse_args(sys.argv[1:] if argv is None else argv)
    except _HelpRequested as help_requested:
        stdout.write(help_requested.text)
        return EXIT_OK
    except _UsageError:
        stderr.write(f"{REFUSAL_PREFIX}USAGE_ERROR\n")
        return EXIT_USAGE
    try:
        output_target = _prepare_output_target(args.output)
        input_real = _resolve_input_dir(args.input_dir)
        if _is_within(output_target, input_real):
            raise ReportRefused("OUTPUT_PATH_IN_INPUT")
        report = build_report(args.input_dir)
        _write_output_file(output_target, report)
        stdout.write(f"{OUTPUT_WRITTEN_PREFIX}{output_target}\n")
        return EXIT_OK
    except ReportRefused as refusal:
        stderr.write(f"{REFUSAL_PREFIX}{refusal.code}\n")
        return EXIT_REFUSED
    except Exception:
        stderr.write(f"{REFUSAL_PREFIX}INTERNAL_ERROR\n")
        return EXIT_REFUSED


def _emit_encoding_failure_fallback() -> None:
    with contextlib.suppress(Exception):
        buffer = getattr(sys.stderr, "buffer", None)
        if buffer is not None:
            buffer.write(ENCODING_FAILURE_FALLBACK_LINE)
            buffer.flush()
        else:
            sys.stderr.write(ENCODING_FAILURE_FALLBACK_LINE.decode("ascii"))
            sys.stderr.flush()


def _console_entrypoint() -> int:
    """Forces strict UTF-8 + LF on both streams and never lets a raw
    traceback reach the console."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    except Exception:
        _emit_encoding_failure_fallback()
        return EXIT_REFUSED
    try:
        return main()
    except BaseException:
        with contextlib.suppress(Exception):
            sys.stderr.write(f"{REFUSAL_PREFIX}INTERNAL_ERROR\n")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(_console_entrypoint())
