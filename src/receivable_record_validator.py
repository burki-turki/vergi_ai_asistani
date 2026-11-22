# ============================================================
# VERGİ AI - RECEIVABLE RECORD VALIDATOR V1
# (Kol A / mali tatil Dilim B / alt dilim B1)
#
# AMAÇ:
#
# İşlem belgesi başına tutulan "alacak kaydı"nın
# (data/case_receivable_record.schema.json) saf doğrulayıcısı.
#
#   validate_receivable_record(record, *, case_id, documents,
#                              allow_verified=False)
#       -> list[(kod, yol)]
#
# Boş liste = geçerli. Her hata (sabit ASCII kod, yapısal yol)
# biçimindedir (ör. ("PAGE_OUT_OF_RANGE", "items[2].page")).
#
# SINIRLAR (bilinçli):
#
#   - Bu modül SINIFLANDIRMA YAPMAZ. Hiçbir alan değerine "mali tatil
#     kapsamı içi/dışı" anlamı yüklenmez; sözcük listeleri yalnız VERİ
#     sözcükleridir (paket K12). Hesap, rapor, CLI, registry bu dilimde
#     DEĞİŞMEZ; bu kaydı bugün hiçbir yol yazmaz veya okumaz.
#   - Teyit eden kullanıcı kimliği ve teyit zamanı kayıtta TUTULMAZ;
#     denetim (reviews/) kaydında tutulur (K15, verification.fact
#     emsali). Kayıttaki teyit bloğu: verification_state,
#     completeness_attested, items_evidence[], creditors_evidence[],
#     verification_audit_ref.
#   - completeness_attested'ın değeri doğrulayıcının kararını
#     ETKİLEMEZ (yalnız teyitli blokta bool olarak dolu olması
#     zorunludur); hesaptaki etkisi B4'te belirlenir.
#
# SAFLIK (paket §12 kural 11):
#
#   - Şema dosyası modül yüklenirken BİR KEZ okunur ve şema
#     doğrulayıcısı BİR KEZ kurulur. validate_receivable_record()
#     dosya okumaz, yazmaz; ağ, LLM, alt süreç, `ui.` import'u yoktur;
#     main() yoktur.
#   - Girdi değiştirilmez. İstisna fırlatılmaz: bozuk tipte girdi için
#     sabit kodlu hata listesi döner; beklenmeyen bir iç hata da tek,
#     sabit, fail-closed bir koda çevrilir (asla boş liste).
#   - jsonschema'nın .message metni, belge içeriği, ad, değer, belge
#     kimliği (documents anahtarı) veya dosya yolu hata çıktısına
#     YAZILMAZ. Yol yalnız şemada tanımlı alan adları ve dizi
#     indekslerinden oluşur.
#
# SIRA:
#
#   1) Argüman tipleri (case_id, documents). Hata varsa yalnız onlar.
#   2) Şema (kural 1) + katı tip ekleri (tamsayı alanlarda
#      type(x) is int, takvim tarihi geçerliliği, boş dönem). Hata
#      varsa YALNIZ bunlar döner; anlam kuralları çalışmaz.
#   3) Anlam kuralları 2-10.
# ============================================================


import json
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator


# ============================================================
# VERSION / PATHS
# ============================================================

RECEIVABLE_RECORD_VALIDATOR_VERSION = "1"

BASE_DIR = Path(__file__).resolve().parent.parent

RECEIVABLE_RECORD_SCHEMA_PATH = (
    BASE_DIR
    / "data"
    / "case_receivable_record.schema.json"
)


# ============================================================
# SABİT SÖZCÜK LİSTELERİ (veri; sınıflandırma DEĞİL)
# ============================================================

# Üç taslak kuralın (deadline_rules.json, mali_tatil_receivable_basis
# = action_document_receivables) applicability.document_types
# birleşimi. Registry OKUNMAZ; test çapraz kontrol eder.
SUPPORTED_ACTION_DOCUMENT_TYPES = frozenset(
    {
        "odeme_emri",
        "borcluya_haciz_bildirimi",
        "borcluya_e_haciz_bildirimi",
        "ihtiyati_haciz_giyapta_tebligi",
    }
)

RECEIVABLE_KINDS = (
    "asil",
    "gecikme_zammi",
    "gecikme_faizi",
    "vergi_ziyai_cezasi",
    "usulsuzluk_cezasi",
    "ozel_usulsuzluk_cezasi",
    "diger_ceza",
    "diger",
)

# K12: asıl kalemin konu sözcükleri (ilk 13 değer). Bugünkü
# hesaplayıcı listelerindeki vergi adlarından türetildi + resim, harç,
# diger. Yeni ad eklemek hukuki karardır; bu modülde YAPILMAZ.
TAX_SUBJECT_TYPES = (
    "gelir_vergisi",
    "kurumlar_vergisi",
    "katma_deger_vergisi",
    "damga_vergisi",
    "veraset_ve_intikal_vergisi",
    "motorlu_tasitlar_vergisi",
    "ozel_tuketim_vergisi",
    "banka_ve_sigorta_muameleleri_vergisi",
    "ozel_iletisim_vergisi",
    "sans_oyunlari_vergisi",
    "resim",
    "harc",
    "diger",
)

# Asıl dışındaki kalemde subject_type, receivable_kind ile AYNI adlı
# değerdir ("diger" için "diger").
KIND_TO_SUBJECT_TYPE = {
    "gecikme_zammi": "gecikme_zammi",
    "gecikme_faizi": "gecikme_faizi",
    "vergi_ziyai_cezasi": "vergi_ziyai_cezasi",
    "usulsuzluk_cezasi": "usulsuzluk_cezasi",
    "ozel_usulsuzluk_cezasi": "ozel_usulsuzluk_cezasi",
    "diger_ceza": "diger_ceza",
    "diger": "diger",
}

SUBJECT_TYPES = TAX_SUBJECT_TYPES + (
    "gecikme_zammi",
    "gecikme_faizi",
    "vergi_ziyai_cezasi",
    "usulsuzluk_cezasi",
    "ozel_usulsuzluk_cezasi",
    "diger_ceza",
)

CREDITOR_ROLES = (
    "tarh_eden",
    "tahsil_eden",
    "ikisi",
    "belirsiz",
)

AUTHORITY_TYPES = (
    "vergi_dairesi_mudurlugu",
    "vergi_dairesi_baskanligi",
    "malmudurlugu",
    "defterdarlik",
    "gumruk",
    "belediye",
    "il_ozel_idaresi",
    "diger",
)

LINK_BASIS_KINDS = (
    "same_document",
    "debt_statement",
)

LINK_BASIS_BASES = (
    "by_tracking_no",
    "by_file_no",
    "other",
)

VERIFICATION_STATES = (
    "unverified",
    "verified",
)

# unverified kayıtta null olması gereken teyit alanları (kural 9).
VERIFICATION_NULL_WHEN_UNVERIFIED_FIELDS = (
    "completeness_attested",
    "items_evidence",
    "creditors_evidence",
    "verification_audit_ref",
)

DOCUMENT_ENTRY_REQUIRED_KEYS = (
    "document_type",
    "page_count",
    "active",
)


# ============================================================
# ŞEMA (modül yüklenirken BİR KEZ)
# ============================================================

def _collect_property_names(node, names):
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            for key in properties:
                names.add(key)
        for value in node.values():
            _collect_property_names(value, names)
    elif isinstance(node, list):
        for value in node:
            _collect_property_names(value, names)


def _load_schema_once():
    try:
        with open(
            RECEIVABLE_RECORD_SCHEMA_PATH,
            "r",
            encoding="utf-8",
        ) as handle:
            schema = json.load(handle)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        names = set()
        _collect_property_names(schema, names)
        return schema, validator, frozenset(names)
    except Exception:  # noqa: BLE001 - fail-closed at call time
        return None, None, frozenset()


(
    RECEIVABLE_RECORD_SCHEMA,
    _SCHEMA_VALIDATOR,
    _SCHEMA_PROPERTY_NAMES,
) = _load_schema_once()


# ============================================================
# HATA KODLARI (sabit ASCII)
# ============================================================

# argüman
CODE_CASE_ID_ARGUMENT_INVALID = "CASE_ID_ARGUMENT_INVALID"
CODE_DOCUMENTS_ARGUMENT_INVALID = "DOCUMENTS_ARGUMENT_INVALID"
CODE_DOCUMENT_ENTRY_INVALID = "DOCUMENT_ENTRY_INVALID"

# kural 1 (şema + katı ekler)
CODE_SCHEMA_UNAVAILABLE = "SCHEMA_UNAVAILABLE"
CODE_SCHEMA_INVALID = "SCHEMA_INVALID"
CODE_SCHEMA_TYPE = "SCHEMA_TYPE"
CODE_SCHEMA_DATE_INVALID = "SCHEMA_DATE_INVALID"
CODE_PERIOD_EMPTY = "PERIOD_EMPTY"

_SCHEMA_CODE_BY_KEYWORD = {
    "type": "SCHEMA_TYPE",
    "required": "SCHEMA_REQUIRED",
    "additionalProperties": "SCHEMA_ADDITIONAL_PROPERTY",
    "enum": "SCHEMA_ENUM",
    "const": "SCHEMA_CONST",
    "pattern": "SCHEMA_PATTERN",
    "not": "SCHEMA_FORBIDDEN_CHARACTER",
    "minLength": "SCHEMA_LENGTH",
    "maxLength": "SCHEMA_LENGTH",
    "minimum": "SCHEMA_RANGE",
    "maximum": "SCHEMA_RANGE",
    "minItems": "SCHEMA_ITEMS",
    "maxItems": "SCHEMA_ITEMS",
}

# kural 2
CODE_CASE_ID_MISMATCH = "CASE_ID_MISMATCH"

# kural 3 / 5 / 6 / 10 belge referansları
CODE_ACTION_DOCUMENT_NOT_FOUND = "ACTION_DOCUMENT_NOT_FOUND"
CODE_ACTION_DOCUMENT_NOT_ACTIVE = "ACTION_DOCUMENT_NOT_ACTIVE"
CODE_DOCUMENT_TYPE_INVALID = "DOCUMENT_TYPE_INVALID"
CODE_ACTION_DOCUMENT_TYPE_UNSUPPORTED = "ACTION_DOCUMENT_TYPE_UNSUPPORTED"
CODE_ACTION_DOCUMENT_TYPE_MISMATCH = "ACTION_DOCUMENT_TYPE_MISMATCH"
CODE_DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
CODE_DOCUMENT_NOT_ACTIVE = "DOCUMENT_NOT_ACTIVE"
CODE_PAGE_COUNT_UNKNOWN = "PAGE_COUNT_UNKNOWN"
CODE_PAGE_OUT_OF_RANGE = "PAGE_OUT_OF_RANGE"
CODE_SOURCE_DOCUMENT_NOT_ALLOWED = "SOURCE_DOCUMENT_NOT_ALLOWED"

# kural 4
CODE_DUPLICATE_ITEM_ID = "DUPLICATE_ITEM_ID"
CODE_DUPLICATE_CREDITOR_ID = "DUPLICATE_CREDITOR_ID"

# kural 6
CODE_DEBT_STATEMENT_DOCUMENT_REQUIRED = "DEBT_STATEMENT_DOCUMENT_REQUIRED"
CODE_DEBT_STATEMENT_SAME_AS_ACTION = "DEBT_STATEMENT_SAME_AS_ACTION"
CODE_LINK_BASIS_BASIS_REQUIRED = "LINK_BASIS_BASIS_REQUIRED"
CODE_LINK_BASIS_DESCRIPTION_REQUIRED = "LINK_BASIS_DESCRIPTION_REQUIRED"
CODE_LINK_BASIS_FIELD_NOT_NULL = "LINK_BASIS_FIELD_NOT_NULL"

# kural 7
CODE_CREDITOR_NOT_FOUND = "CREDITOR_NOT_FOUND"
CODE_AUTHORITY_NAME_REQUIRED = "AUTHORITY_NAME_REQUIRED"

# kural 8
CODE_SUBJECT_TYPE_KIND_MISMATCH = "SUBJECT_TYPE_KIND_MISMATCH"
CODE_RELATED_SUBJECT_TYPE_NOT_NULL = "RELATED_SUBJECT_TYPE_NOT_NULL"
CODE_SUBJECT_OTHER_NAME_REQUIRED = "SUBJECT_OTHER_NAME_REQUIRED"
CODE_SUBJECT_OTHER_NAME_NOT_ALLOWED = "SUBJECT_OTHER_NAME_NOT_ALLOWED"
CODE_RELATED_SUBJECT_OTHER_NAME_REQUIRED = "RELATED_SUBJECT_OTHER_NAME_REQUIRED"
CODE_RELATED_SUBJECT_OTHER_NAME_NOT_ALLOWED = (
    "RELATED_SUBJECT_OTHER_NAME_NOT_ALLOWED"
)

# kural 9
CODE_VERIFIED_NOT_ALLOWED_IN_MODE = "VERIFIED_NOT_ALLOWED_IN_MODE"
CODE_VERIFICATION_FIELD_NOT_NULL = "VERIFICATION_FIELD_NOT_NULL"

# kural 10
CODE_VERIFICATION_AUDIT_REF_REQUIRED = "VERIFICATION_AUDIT_REF_REQUIRED"
CODE_COMPLETENESS_ATTESTED_REQUIRED = "COMPLETENESS_ATTESTED_REQUIRED"
CODE_ITEMS_EVIDENCE_REQUIRED = "ITEMS_EVIDENCE_REQUIRED"
CODE_CREDITORS_EVIDENCE_REQUIRED = "CREDITORS_EVIDENCE_REQUIRED"
CODE_EVIDENCE_TARGET_NOT_FOUND = "EVIDENCE_TARGET_NOT_FOUND"
CODE_EVIDENCE_DUPLICATE_TARGET = "EVIDENCE_DUPLICATE_TARGET"
CODE_EVIDENCE_MISSING = "EVIDENCE_MISSING"

# kural 11 (son çare)
CODE_VALIDATOR_INTERNAL_ERROR = "VALIDATOR_INTERNAL_ERROR"


# ============================================================
# YOL YARDIMCILARI
# ============================================================

ROOT_PATH = "record"


def _render_path(parts):
    """Yalnız int indeksler ve şemada tanımlı alan adları yazılır.
    Bilinmeyen bir anahtar (girdiden gelen, ör. fazla alan adı)
    görülürse yol orada KESİLİR; anahtar asla çıktıya yazılmaz."""
    rendered = ""
    for part in parts:
        if type(part) is int:
            rendered += f"[{part}]"
        elif isinstance(part, str) and part in _SCHEMA_PROPERTY_NAMES:
            rendered += f".{part}" if rendered else part
        else:
            break
    return rendered or ROOT_PATH


def _join(prefix, name):
    if not prefix or prefix == ROOT_PATH:
        return name
    return f"{prefix}.{name}"


# ============================================================
# KURAL 1 - ŞEMA
# ============================================================

def _is_null_type_error(error):
    return (
        error.validator == "type"
        and error.validator_value == "null"
    )


def _resolve_schema_error(error):
    """anyOf (nullable) hatalarında null-olmayan dalın asıl hatasına
    iner; böylece kod daha özgül olur. Mesaj metni hiç okunmaz."""
    depth = 0
    while (
        error.validator in ("anyOf", "oneOf")
        and error.context
        and depth < 16
    ):
        candidates = [
            sub
            for sub in error.context
            if not _is_null_type_error(sub)
        ]
        if not candidates:
            break
        candidates.sort(
            key=lambda sub: (
                0 if sub.validator == "type" else 1,
                len(list(sub.relative_schema_path)),
                str(sub.validator),
            )
        )
        error = candidates[0]
        depth += 1
    return error


def _schema_errors(record):
    errors = []
    for raw_error in _SCHEMA_VALIDATOR.iter_errors(record):
        error = _resolve_schema_error(raw_error)
        path = _render_path(error.absolute_path)
        keyword = error.validator
        if keyword == "required":
            instance = error.instance
            required = error.validator_value
            if isinstance(instance, dict) and isinstance(required, list):
                for name in required:
                    if (
                        isinstance(name, str)
                        and name not in instance
                        and name in _SCHEMA_PROPERTY_NAMES
                    ):
                        errors.append(
                            ("SCHEMA_REQUIRED", _join(path, name))
                        )
                continue
        code = _SCHEMA_CODE_BY_KEYWORD.get(
            keyword,
            CODE_SCHEMA_INVALID,
        )
        errors.append((code, path))
    return errors


def _is_strict_int(value):
    return type(value) is int


def _strict_shape_errors(record):
    """Şemanın Python tarafındaki katı ekleri (kural 1'in parçası):
    jsonschema 'integer' için 2.0 ve 'const 1' için 1.0 kabul eder;
    burada type(x) is int istenir. Tarihler gerçek takvim tarihi
    olmalı; dönem en az bir dolu alan taşımalı."""
    errors = []

    if not _is_strict_int(record["schema_version"]):
        errors.append((CODE_SCHEMA_TYPE, "schema_version"))

    for index, creditor in enumerate(record["creditors"]):
        if not _is_strict_int(creditor["page"]):
            errors.append((CODE_SCHEMA_TYPE, f"creditors[{index}].page"))

    for index, item in enumerate(record["items"]):
        prefix = f"items[{index}]"
        if not _is_strict_int(item["page"]):
            errors.append((CODE_SCHEMA_TYPE, f"{prefix}.page"))
        period = item["period"]
        for field in ("start_date", "end_date"):
            value = period[field]
            if value is None:
                continue
            try:
                date.fromisoformat(value)
            except (TypeError, ValueError):
                errors.append(
                    (CODE_SCHEMA_DATE_INVALID, f"{prefix}.period.{field}")
                )
        if (
            period["start_date"] is None
            and period["end_date"] is None
            and period["label"] is None
        ):
            errors.append((CODE_PERIOD_EMPTY, f"{prefix}.period"))

    verification = record["verification"]
    for field in ("items_evidence", "creditors_evidence"):
        entries = verification[field]
        if entries is None:
            continue
        for index, entry in enumerate(entries):
            if not _is_strict_int(entry["page"]):
                errors.append(
                    (
                        CODE_SCHEMA_TYPE,
                        f"verification.{field}[{index}].page",
                    )
                )

    return errors


# ============================================================
# ARGÜMANLAR (documents şemanın dışındadır - katı tip kuralları)
# ============================================================

def _argument_errors(case_id, documents):
    errors = []

    if not isinstance(case_id, str):
        errors.append((CODE_CASE_ID_ARGUMENT_INVALID, "argument.case_id"))

    if not isinstance(documents, dict):
        errors.append(
            (CODE_DOCUMENTS_ARGUMENT_INVALID, "argument.documents")
        )
        return errors

    for key, entry in documents.items():
        if (
            not isinstance(key, str)
            or not isinstance(entry, dict)
            or any(
                required not in entry
                for required in DOCUMENT_ENTRY_REQUIRED_KEYS
            )
        ):
            # Belge kimliği (anahtar) veya değer çıktıya YAZILMAZ.
            errors.append(
                (CODE_DOCUMENT_ENTRY_INVALID, "argument.documents")
            )
            return errors

    # i2: document_type HER girdide str olmalı (yalnız işlem belgesinde
    # değil); değilse sabit, fail-closed kod. Normalizasyon (strip +
    # casefold) yalnız str üzerinde yapılır, str() ile ZORLANMAZ.
    for entry in documents.values():
        if not isinstance(entry["document_type"], str):
            errors.append(
                (CODE_DOCUMENT_TYPE_INVALID, "argument.documents")
            )
            break

    return errors


def _document_is_active(entry):
    return entry["active"] is True


def _valid_page_count(entry):
    page_count = entry["page_count"]
    if type(page_count) is int and page_count >= 1:
        return page_count
    return None


def _normalize_document_type(value):
    return value.strip().casefold()


def _check_document_ref(
    documents,
    document_id,
    page,
    document_path,
    page_path,
    errors,
):
    """Kural 5 (ve kural 10 kanıt sayfaları): belge var + aktif,
    page_count geçerli tamsayı, page <= page_count. Belge geçerliyse
    True döner."""
    entry = documents.get(document_id)
    if entry is None:
        errors.append((CODE_DOCUMENT_NOT_FOUND, document_path))
        return False
    if not _document_is_active(entry):
        errors.append((CODE_DOCUMENT_NOT_ACTIVE, document_path))
        return False
    page_count = _valid_page_count(entry)
    if page_count is None:
        errors.append((CODE_PAGE_COUNT_UNKNOWN, page_path))
        return False
    if page is None or page > page_count:
        errors.append((CODE_PAGE_OUT_OF_RANGE, page_path))
        return False
    return True


# ============================================================
# ANLAM KURALLARI 2-10
# ============================================================

def _rule_2_case_binding(record, case_id, errors):
    if record["case_id"] != case_id:
        errors.append((CODE_CASE_ID_MISMATCH, "case_id"))


def _rule_3_action_document(record, documents, errors):
    action_id = record["action_document_id"]
    entry = documents.get(action_id)
    if entry is None:
        errors.append((CODE_ACTION_DOCUMENT_NOT_FOUND, "action_document_id"))
        return
    if not _document_is_active(entry):
        errors.append(
            (CODE_ACTION_DOCUMENT_NOT_ACTIVE, "action_document_id")
        )
        return
    # document_type'ın str olduğu argüman aşamasında her girdi için
    # doğrulandı (_argument_errors).
    normalized = _normalize_document_type(entry["document_type"])
    if normalized not in SUPPORTED_ACTION_DOCUMENT_TYPES:
        errors.append(
            (CODE_ACTION_DOCUMENT_TYPE_UNSUPPORTED, "action_document_id")
        )
        return
    if normalized != record["action_document_type"]:
        errors.append(
            (CODE_ACTION_DOCUMENT_TYPE_MISMATCH, "action_document_type")
        )


def _rule_4_unique_ids(record, errors):
    seen_items = set()
    for index, item in enumerate(record["items"]):
        item_id = item["item_id"]
        if item_id in seen_items:
            errors.append((CODE_DUPLICATE_ITEM_ID, f"items[{index}].item_id"))
        seen_items.add(item_id)

    seen_creditors = set()
    for index, creditor in enumerate(record["creditors"]):
        creditor_id = creditor["creditor_id"]
        if creditor_id in seen_creditors:
            errors.append(
                (
                    CODE_DUPLICATE_CREDITOR_ID,
                    f"creditors[{index}].creditor_id",
                )
            )
        seen_creditors.add(creditor_id)


def _allowed_source_ids(record):
    link_basis = record["link_basis"]
    allowed = {record["action_document_id"]}
    if link_basis["kind"] == "debt_statement":
        debt_id = link_basis["debt_statement_document_id"]
        if debt_id is not None:
            allowed.add(debt_id)
    return allowed


def _rule_5_sources_and_pages(record, documents, errors):
    allowed = _allowed_source_ids(record)

    for collection in ("creditors", "items"):
        for index, entry in enumerate(record[collection]):
            prefix = f"{collection}[{index}]"
            source_id = entry["source_document_id"]
            source_path = f"{prefix}.source_document_id"
            _check_document_ref(
                documents,
                source_id,
                entry["page"],
                source_path,
                f"{prefix}.page",
                errors,
            )
            if source_id not in allowed:
                errors.append((CODE_SOURCE_DOCUMENT_NOT_ALLOWED, source_path))


def _rule_6_debt_statement(record, documents, errors):
    link_basis = record["link_basis"]
    debt_id = link_basis["debt_statement_document_id"]
    basis = link_basis["basis"]
    description = link_basis["description"]

    if link_basis["kind"] == "same_document":
        for field, value in (
            ("debt_statement_document_id", debt_id),
            ("basis", basis),
            ("description", description),
        ):
            if value is not None:
                errors.append(
                    (CODE_LINK_BASIS_FIELD_NOT_NULL, f"link_basis.{field}")
                )
        return

    debt_path = "link_basis.debt_statement_document_id"
    if debt_id is None:
        errors.append((CODE_DEBT_STATEMENT_DOCUMENT_REQUIRED, debt_path))
    elif debt_id == record["action_document_id"]:
        errors.append((CODE_DEBT_STATEMENT_SAME_AS_ACTION, debt_path))
    else:
        entry = documents.get(debt_id)
        if entry is None:
            errors.append((CODE_DOCUMENT_NOT_FOUND, debt_path))
        elif not _document_is_active(entry):
            errors.append((CODE_DOCUMENT_NOT_ACTIVE, debt_path))

    if basis is None:
        errors.append((CODE_LINK_BASIS_BASIS_REQUIRED, "link_basis.basis"))
    # L-4 (düzeltme turu 1, seçenek A): debt_statement kaydında açıklama
    # dayanak (basis) ne olursa olsun zorunludur; dayanak null olsa da
    # ayrıca raporlanır.
    if description is None:
        errors.append(
            (CODE_LINK_BASIS_DESCRIPTION_REQUIRED, "link_basis.description")
        )


def _rule_7_creditor_refs(record, errors):
    creditor_ids = {
        creditor["creditor_id"]
        for creditor in record["creditors"]
    }
    for index, creditor in enumerate(record["creditors"]):
        if (
            creditor["authority_type"] == "diger"
            and creditor["authority_name"] is None
        ):
            errors.append(
                (
                    CODE_AUTHORITY_NAME_REQUIRED,
                    f"creditors[{index}].authority_name",
                )
            )
    for index, item in enumerate(record["items"]):
        if item["creditor_id"] not in creditor_ids:
            errors.append(
                (CODE_CREDITOR_NOT_FOUND, f"items[{index}].creditor_id")
            )


def _rule_8_item_structure(record, errors):
    """Yalnız YAPI: hiçbir değere kapsam içi/dışı anlamı verilmez."""
    for index, item in enumerate(record["items"]):
        prefix = f"items[{index}]"
        kind = item["receivable_kind"]
        subject_type = item["subject_type"]
        related = item.get("related_subject_type")

        if kind == "asil":
            if subject_type not in TAX_SUBJECT_TYPES:
                errors.append(
                    (CODE_SUBJECT_TYPE_KIND_MISMATCH, f"{prefix}.subject_type")
                )
            if related is not None:
                errors.append(
                    (
                        CODE_RELATED_SUBJECT_TYPE_NOT_NULL,
                        f"{prefix}.related_subject_type",
                    )
                )
        else:
            if subject_type != KIND_TO_SUBJECT_TYPE.get(kind):
                errors.append(
                    (CODE_SUBJECT_TYPE_KIND_MISMATCH, f"{prefix}.subject_type")
                )

        other_name = item["subject_other_name"]
        if subject_type == "diger":
            if other_name is None:
                errors.append(
                    (
                        CODE_SUBJECT_OTHER_NAME_REQUIRED,
                        f"{prefix}.subject_other_name",
                    )
                )
        elif other_name is not None:
            errors.append(
                (
                    CODE_SUBJECT_OTHER_NAME_NOT_ALLOWED,
                    f"{prefix}.subject_other_name",
                )
            )

        related_other_name = item["related_subject_other_name"]
        if related == "diger":
            if related_other_name is None:
                errors.append(
                    (
                        CODE_RELATED_SUBJECT_OTHER_NAME_REQUIRED,
                        f"{prefix}.related_subject_other_name",
                    )
                )
        elif related_other_name is not None:
            errors.append(
                (
                    CODE_RELATED_SUBJECT_OTHER_NAME_NOT_ALLOWED,
                    f"{prefix}.related_subject_other_name",
                )
            )


def _rule_9_mode(record, allow_verified_mode, errors):
    """Kural 9. Teyitli blok kurallarının (kural 10) çalışıp
    çalışmayacağını döndürür."""
    verification = record["verification"]
    state = verification["verification_state"]

    if state == "verified":
        if not allow_verified_mode:
            errors.append(
                (
                    CODE_VERIFIED_NOT_ALLOWED_IN_MODE,
                    "verification.verification_state",
                )
            )
            return False
        return True

    for field in VERIFICATION_NULL_WHEN_UNVERIFIED_FIELDS:
        if verification[field] is not None:
            errors.append(
                (CODE_VERIFICATION_FIELD_NOT_NULL, f"verification.{field}")
            )
    return False


def _rule_10_evidence_list(
    record,
    documents,
    field,
    target_key,
    collection,
    required_code,
    errors,
):
    entries = record["verification"][field]
    list_path = f"verification.{field}"
    if entries is None:
        errors.append((required_code, list_path))
        return

    known = [
        entry[target_key]
        for entry in record[collection]
    ]
    known_set = set(known)
    covered = set()

    for index, entry in enumerate(entries):
        prefix = f"{list_path}[{index}]"
        target = entry[target_key]
        if target not in known_set:
            errors.append(
                (CODE_EVIDENCE_TARGET_NOT_FOUND, f"{prefix}.{target_key}")
            )
        elif target in covered:
            errors.append(
                (CODE_EVIDENCE_DUPLICATE_TARGET, f"{prefix}.{target_key}")
            )
        else:
            covered.add(target)
        _check_document_ref(
            documents,
            entry["evidence_document_id"],
            entry["page"],
            f"{prefix}.evidence_document_id",
            f"{prefix}.page",
            errors,
        )

    for index, target in enumerate(known):
        if target not in covered:
            errors.append(
                (CODE_EVIDENCE_MISSING, f"{collection}[{index}].{target_key}")
            )


def _rule_10_verified_block(record, documents, errors):
    verification = record["verification"]

    if verification["verification_audit_ref"] is None:
        errors.append(
            (
                CODE_VERIFICATION_AUDIT_REF_REQUIRED,
                "verification.verification_audit_ref",
            )
        )

    # Değeri (true/false) karar vermez; yalnız bool olarak dolu olmalı.
    if type(verification["completeness_attested"]) is not bool:
        errors.append(
            (
                CODE_COMPLETENESS_ATTESTED_REQUIRED,
                "verification.completeness_attested",
            )
        )

    _rule_10_evidence_list(
        record,
        documents,
        "items_evidence",
        "item_id",
        "items",
        CODE_ITEMS_EVIDENCE_REQUIRED,
        errors,
    )
    _rule_10_evidence_list(
        record,
        documents,
        "creditors_evidence",
        "creditor_id",
        "creditors",
        CODE_CREDITORS_EVIDENCE_REQUIRED,
        errors,
    )


# ============================================================
# PUBLIC API
# ============================================================

def _finish(errors):
    unique = sorted(set(errors))
    return [
        (str(code), str(path))
        for code, path in unique
    ]


def _validate(record, case_id, documents, allow_verified):
    if _SCHEMA_VALIDATOR is None:
        return [(CODE_SCHEMA_UNAVAILABLE, ROOT_PATH)]

    argument_errors = _argument_errors(case_id, documents)
    if argument_errors:
        return _finish(argument_errors)

    schema_errors = _schema_errors(record)
    if schema_errors:
        return _finish(schema_errors)

    strict_errors = _strict_shape_errors(record)
    if strict_errors:
        return _finish(strict_errors)

    # Teyit kipi yalnız allow_verified is True iken açıktır
    # (ör. "False" dizesi veya 1 teyit kipini AÇMAZ).
    allow_verified_mode = allow_verified is True

    errors = []
    _rule_2_case_binding(record, case_id, errors)
    _rule_3_action_document(record, documents, errors)
    _rule_4_unique_ids(record, errors)
    _rule_5_sources_and_pages(record, documents, errors)
    _rule_6_debt_statement(record, documents, errors)
    _rule_7_creditor_refs(record, errors)
    _rule_8_item_structure(record, errors)
    if _rule_9_mode(record, allow_verified_mode, errors):
        _rule_10_verified_block(record, documents, errors)
    return _finish(errors)


def validate_receivable_record(
    record,
    *,
    case_id,
    documents,
    allow_verified=False,
):
    """Alacak kaydını doğrular. Boş liste = geçerli. İstisna
    fırlatmaz, girdiyi değiştirmez, dosya okumaz/yazmaz."""
    try:
        return _validate(record, case_id, documents, allow_verified)
    except Exception:  # noqa: BLE001 - kural 11: asla istisna yok
        return [(CODE_VALIDATOR_INTERNAL_ERROR, ROOT_PATH)]
