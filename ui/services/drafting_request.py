# ============================================================
# VERGİ AI - LAWYER UI, ROW 18C (YAPILANDIRILMIŞ AVUKAT GİRDİSİ)
#
# MİMARİ SINIR (Option A-prime, kullanıcı kararı - kontrat, 2026-09-05):
#   - Bu modül (ve onu çağıran HTTP route'ları) YALNIZ görüntüler,
#     doğrular ve `data/cases/<case_id>/drafting/inputs/lawyer_input.json`
#     dosyasını kaydeder/geri yükler.
#   - Bu modül HİÇBİR ZAMAN Drafting Engine'i (`build_drafting_engine_output`),
#     bir agent'ı veya bir network/API çağrısını ÇAĞIRMAZ - bunlar
#     yalnız ayrı, elle çalıştırılan `ui/run_drafting_request.py` CLI
#     köprüsünün (`--generate-pending` bayrağı ARKASINDA) işidir.
#   - Bu modül Row 15'in (`src/drafting_*.py`) TEK bir satırını bile
#     DEĞİŞTİRMEZ/KOPYALAMAZ - yalnız zaten PUBLIC olan
#     `normalize_lawyer_input`, `compute_lawyer_input_hash`,
#     `is_valid_request_input`, `has_valid_lawyer_text`,
#     `compute_request_authorization` fonksiyonlarını OLDUĞU GİBİ
#     import edip çağırır (Prensip 10, review_registry.py/live_view.py
#     ile AYNI ilke).
#   - Bu modül KENDİ atomik-yazma yardımcısını taşır
#     (`_atomic_write_json`) - `drafting_engine.atomic_write_json`'ı
#     İMPORT ETMEZ (kasıtlı mimari sınır, kullanıcı kararı: Row 18,
#     Row 15'in iç I/O yardımcılarına BAĞIMLI hale gelmez - tıpkı
#     `common.py`'nin kendi bağımsız `sha256_file`'ı taşıması gibi).
#
# DURABLE ARTEFAKT: `data/case_lawyer_input.schema.json` (bu turda
# oluşturuldu) - `lawyer_input` alanı, YEREL olarak inşa edilmiş bir
# `referencing.Registry` üzerinden LOCKED `case_drafting.schema.json`
# içindeki `#/$defs/lawyer_input` tanımına `$ref` ile atıf yapar; bu
# tanım hiçbir şekilde KOPYALANMAZ/ZAYIFLATILMAZ. Registry yalnız
# YEREL, ÖNCEDEN DİSKTEN yüklenmiş şema içeriğinden inşa edilir -
# hiçbir `retrieve=` callback'i TANIMLANMAZ, dolayısıyla şema
# çözümlemesi için hiçbir kod yolu network'e ULAŞAMAZ (yerelde
# kayıtlı olmayan bir referans `Unresolvable` fırlatır - network'e
# DÜŞMEZ).
#
# GİZLİLİK SINIRI (kontrat madde 7): `request_text` ve
# `lawyer_provided_text` İÇERİĞİ bu modülün ÜRETTİĞİ hiçbir hata
# mesajında, log satırında veya dosya adında YER ALMAZ - yalnız alan
# adları, uzunluklar, sabit hata kodları ve hash'ler.
# ============================================================

import json
import os
import shutil

from datetime import datetime, timezone
from pathlib import Path

from referencing import Registry, Resource
from jsonschema import Draft202012Validator, FormatChecker

from .paths import CASES_DIR, DATA_DIR, to_repo_relative
from .common import (
    DraftingRequestUiError,
    DraftingRequestFormError,
    DraftingRequestValidationError,
    DraftingRequestStaleInputError,
    DraftingRequestNamingCollisionError,
    DraftingRequestSaveFailedError,
    sha256_file,
)

# `.paths` import'u SRC_DIR'i zaten sys.path'e ekledi (bkz. paths.py) -
# bu yüzden src/ modülleri burada doğrudan import edilebilir (Prensip
# 10 - src/'nin bir KOPYASI/YENİDEN YAZIMI değil, olduğu gibi import).
from drafting_engine import (                                    # noqa: E402
    normalize_lawyer_input,
    DraftingEngineError,
    get_pending_path,
    get_canonical_path,
)
from drafting_policy import (                                    # noqa: E402
    DRAFT_INTENT_TYPES,
    APPEAL_LEVELS,
    compute_lawyer_input_hash,
    is_valid_request_input,
    has_valid_lawyer_text,
    compute_request_authorization,
)
from legal_research_validator import (                           # noqa: E402
    load_canonical_issues,
    LegalResearchValidationError,
)


# ============================================================
# SABİTLER
# ============================================================

CURRENT_FILENAME = "lawyer_input.json"
NO_EXISTING_INPUT_SENTINEL = "no_existing_input"

WRAPPER_SCHEMA_PATH = DATA_DIR / "case_lawyer_input.schema.json"
DRAFTING_SCHEMA_PATH = DATA_DIR / "case_drafting.schema.json"

REQUEST_TYPE_MAX_LENGTH = 200
REQUEST_TEXT_MAX_LENGTH = 5000
LAWYER_TEXT_MAX_LENGTH = 50000

FIELD_LIMITS = {
    "request_type": REQUEST_TYPE_MAX_LENGTH,
    "request_text": REQUEST_TEXT_MAX_LENGTH,
    "lawyer_provided_text": LAWYER_TEXT_MAX_LENGTH,
}

# HTTP POST gövdesi için tam sınır - `ui/main.py`'deki ASGI
# ara-katmanıyla (yalnız bu route'a özgü) BİREBİR AYNI değer.
MAX_REQUEST_BODY_BYTES = 128 * 1024

ISSUE_SELECTION_NOT_PROVIDED = "not_provided"
ISSUE_SELECTION_NONE = "none"
ISSUE_SELECTION_SPECIFIC = "specific"
ISSUE_SELECTION_MODES = {
    ISSUE_SELECTION_NOT_PROVIDED, ISSUE_SELECTION_NONE, ISSUE_SELECTION_SPECIFIC,
}

DRAFT_INTENT_NOT_SET = "not_set"

_EMPTY_SELECTED_SOURCE_IDS = {
    "selected_claim_ids": [],
    "selected_counterargument_ids": [],
    "selected_rebuttal_ids": [],
    "selected_risk_ids": [],
    "selected_strategy_ids": [],
}

_MAX_NAMING_ATTEMPTS = 20


# ============================================================
# YOL YARDIMCILARI (Row 15'in `drafting/` alt ağacından AYRI - Row
# 18C KENDİ `drafting/inputs/` alt ağacını taşır, Row 15'in
# `drafting/history/` [pending geçmişi] veya Layer B'nin
# `drafting/reviews/` alt dizinleriyle ASLA ÇAKIŞMAZ).
# ============================================================

def get_inputs_dir(case_id):

    return CASES_DIR / case_id / "drafting" / "inputs"


def get_current_input_path(case_id):

    return get_inputs_dir(case_id) / CURRENT_FILENAME


def get_input_history_dir(case_id):

    return get_inputs_dir(case_id) / "history"


def get_input_audit_dir(case_id):

    return get_inputs_dir(case_id) / "audit"


# ============================================================
# ŞEMA / YEREL $ref REGISTRY
#
# Her çağrıda YENİDEN inşa edilir (iki küçük JSON dosyası okumak -
# performans endişesi YOK, yerel/tek-kullanıcılı bir araç) - bu,
# testlerin `WRAPPER_SCHEMA_PATH`/`DRAFTING_SCHEMA_PATH` modül
# sabitlerini GEÇİCİ olarak başka (sentetik/bozuk) dosyalara
# yönlendirip önbelleğe TAKILMADAN doğrulama hatalarını
# sınayabilmesini sağlar.
# ============================================================

def _load_json_file(path):

    path = Path(path)

    with open(path, "r", encoding="utf-8") as file:

        return json.load(file)


def build_wrapper_validator():
    """Yalnız YEREL, önceden diskten yüklenmiş şema içeriğinden bir
    `referencing.Registry` inşa eder - hiçbir `retrieve=` callback'i
    TANIMLANMAZ, dolayısıyla şema çözümlemesi network'e ULAŞAMAZ
    (kayıtlı olmayan bir $ref `Unresolvable` fırlatır)."""

    wrapper_schema = _load_json_file(WRAPPER_SCHEMA_PATH)
    drafting_schema = _load_json_file(DRAFTING_SCHEMA_PATH)

    registry = Registry().with_resource(
        drafting_schema["$id"], Resource.from_contents(drafting_schema),
    )

    return Draft202012Validator(wrapper_schema, registry=registry, format_checker=FormatChecker())


def _sanitized_schema_errors(validator, instance):
    """jsonschema'nın VARSAYILAN hata mesajları bazı doğrulayıcılar için
    (`maxLength` yok burada ama `type`/`enum`/`const`/`pattern` dahil
    birçoğu) GEÇERSİZ DEĞERİN KENDİSİNİ mesaja gömer - bu, `lawyer_input.
    request_input.request_text` / `lawyer_provided_text` gibi serbest
    metin alanları için KABUL EDİLEMEZ (madde 7: bu içerik hiçbir
    hata mesajında/logda YER ALAMAZ). Bu yüzden `error.message`
    ASLA kullanılmaz - yalnız YOL (alan adları/indeksler) ve
    doğrulayıcı adı (`type`/`required`/`enum` vb.) ile SABİT, içerik
    taşımayan bir açıklama üretilir."""

    errors = []

    for error in validator.iter_errors(instance):

        path = "/".join(str(part) for part in error.absolute_path) or "(kök)"

        errors.append(f"şema ihlali: alan={path} kural={error.validator}")

    return errors


# ============================================================
# İSTEK ALANI DOĞRULAMASI (madde 5/7 - form-seviyesi, Row 15'in KENDİ
# semantiğinden AYRI: uzunluk sınırları Row 18C'YE ÖZGÜDÜR, LOCKED
# şemada/Row 15'te böyle bir sınır YOKTUR)
# ============================================================

def _check_max_length(field_name, value, max_length):

    if isinstance(value, str) and len(value) > max_length:

        raise DraftingRequestFormError(
            f"{field_name} alanı azami {max_length} karakteri aşıyor."
        )


def _clean_optional_text(field_name, raw_value, max_length):
    """None/boş/yalnız-boşluk -> None; aksi halde DEĞER AYNEN (trim
    dışında hiçbir normalizasyon uygulanmaz - avukatın serbest metnini
    içerik olarak DEĞİŞTİRMEK bu katmanın işi değildir)."""

    if raw_value is None:

        return None

    if not isinstance(raw_value, str):

        raise DraftingRequestFormError(f"{field_name} alanı beklenmeyen bir türde gönderildi.")

    _check_max_length(field_name, raw_value, max_length)

    if raw_value.strip() == "":

        return None

    return raw_value


def build_lawyer_input_from_form(
    *,
    draft_intent_type_choice,
    appeal_level_choice,
    issue_selection_mode,
    selected_issue_ids_raw,
    request_type_raw,
    request_text_raw,
    lawyer_provided_text_raw,
):
    """Ham form alanlarından SÖZDİZİMSEL olarak sağlam (ama henüz
    canonical issue üyeliği/Row 15 appeal_level kuralı/hash
    tutarlılığı KONTROL EDİLMEMİŞ) bir `lawyer_input` sözlüğü inşa
    eder. `selected_source_ids` HİÇBİR ZAMAN formdan OKUNMAZ - beş
    dizi de her zaman boş olarak sabitlenir (madde 5: "rezerve/pasif"
    - bu alan editable UI'da HİÇ GÖSTERİLMEZ)."""

    # --- draft_intent_type ---
    if draft_intent_type_choice in (None, "", DRAFT_INTENT_NOT_SET):

        draft_intent_type = None

    elif draft_intent_type_choice not in DRAFT_INTENT_TYPES:

        raise DraftingRequestFormError("draft_intent_type için geçersiz bir seçim gönderildi.")

    else:

        draft_intent_type = draft_intent_type_choice

    # --- appeal_level ---
    appeal_level = _clean_optional_text("appeal_level", appeal_level_choice, 32)

    if appeal_level is not None and appeal_level not in APPEAL_LEVELS:

        raise DraftingRequestFormError("appeal_level için geçersiz bir seçim gönderildi.")

    # --- issue seçim tri-state'i (madde 5 - yinelenen reddi BURADA,
    # sözdizimsel/I/O gerektirmeyen bir kontrol; canonical ÜYELİK
    # kontrolü ve NİHAİ SIRALAMA paylaşılan doğrulayıcının işi) ---
    if issue_selection_mode not in ISSUE_SELECTION_MODES:

        raise DraftingRequestFormError("issue seçim modu için geçersiz bir değer gönderildi.")

    if issue_selection_mode == ISSUE_SELECTION_NOT_PROVIDED:

        selected_issue_ids = None

    elif issue_selection_mode == ISSUE_SELECTION_NONE:

        selected_issue_ids = []

    else:

        raw_list = [item for item in (selected_issue_ids_raw or []) if isinstance(item, str) and item != ""]

        if not raw_list:

            raise DraftingRequestFormError(
                "'select_specific' seçiliyken en az bir issue işaretlenmelidir "
                "(hiçbirini seçmek için 'select_none' kullanın)."
            )

        if len(raw_list) != len(set(raw_list)):

            raise DraftingRequestFormError("Aynı issue birden fazla kez seçilemez (yinelenen seçim).")

        selected_issue_ids = list(raw_list)

    # --- request_input (madde 5 - ikisi-birden ya da ikisi-de-boş) ---
    request_type = _clean_optional_text("request_type", request_type_raw, REQUEST_TYPE_MAX_LENGTH)
    request_text = _clean_optional_text("request_text", request_text_raw, REQUEST_TEXT_MAX_LENGTH)

    if (request_type is None) != (request_text is None):

        raise DraftingRequestFormError(
            "request_type ve request_text birlikte doldurulmalı ya da ikisi de boş bırakılmalı."
        )

    request_input = None if request_type is None else {
        "request_type": request_type, "request_text": request_text,
    }

    # --- lawyer_provided_text ---
    lawyer_provided_text = _clean_optional_text(
        "lawyer_provided_text", lawyer_provided_text_raw, LAWYER_TEXT_MAX_LENGTH,
    )

    return {
        "draft_intent_type": draft_intent_type,
        "appeal_level": appeal_level,
        "selected_issue_ids": selected_issue_ids,
        "selected_source_ids": dict(_EMPTY_SELECTED_SOURCE_IDS),
        "request_input": request_input,
        "lawyer_provided_text": lawyer_provided_text,
    }


def compute_request_authorized_explanation(lawyer_input):
    """Görüntüleme AMAÇLI, salt-okunur bir açıklama - Q1/Q2 ayrımını
    KENDİSİ YENİDEN UYGULAMAZ, doğrudan Row 15'in KENDİ
    `compute_request_authorization`'ını çağırır (madde 5: "hem
    request_input hem lawyer_provided_text boşsa kaydetmeye izin ver,
    ama sabit bir açıklama göster")."""

    authorized = compute_request_authorization(
        lawyer_input.get("request_input"), lawyer_input.get("lawyer_provided_text"),
    )

    if authorized:

        return None

    return (
        "Ne yapılandırılmış bir talep girdisi (request_type + request_text) ne de "
        "avukat tarafından sağlanmış bir metin (lawyer_provided_text) mevcut - bu "
        "durumda bir 'request' section'ı için üretim yetkisi (Q2) YOKTUR. Bu "
        "girdi yine de kaydedilebilir, ancak Drafting Engine (yalnız ayrı CLI "
        "köprüsüyle) çalıştırıldığında 'request' türü bir bölüm üretilemeyecektir."
    )


# ============================================================
# CANONICAL ISSUE ÜYELİĞİ + DETERMİNİSTİK SIRALAMA (madde 2 - reddet,
# SESSİZCE TEKİLLEŞTİRME/ATLAMA YOK; sıralama YALNIZ doğrulamadan
# SONRA uygulanır)
# ============================================================

def _load_canonical_issue_ids(case_id):
    """GERÇEK, var olan `legal_research_validator.load_canonical_issues`
    yükleyicisini OLDUĞU GİBİ çağırır (Row 18C kendi issue-yükleme
    mantığını İCAT ETMEZ). Canonical issues.json henüz YOKSA (yeni bir
    case) veya okunamıyorsa, BOŞ bir küme döner - bu durumda
    `selected_issue_ids` için `[]` (açıkça 'hiçbiri') hâlâ geçerlidir,
    ama boş-olmayan HERHANGİ bir liste otomatik olarak 'sahte/bilinmeyen
    id' olarak reddedilir (aşağıya bakınız)."""

    try:

        loaded = load_canonical_issues(case_id)

    except (FileNotFoundError, LegalResearchValidationError):

        return set()

    return set(loaded.get("issue_index", {}).keys())


def validate_and_sort_selected_issue_ids(selected_issue_ids, case_id):
    """`selected_issue_ids` için TAM kural: None/[] OLDUĞU GİBİ geçer;
    dolu bir liste ÖNCE yinelenen (savunma derinliği - form katmanı
    zaten reddetmiş olsa da BURADA da bağımsız olarak kontrol edilir),
    SONRA GÜNCEL canonical issue kümesine üyelik için kontrol edilir
    (sahte/bilinmeyen/eski bir id TÜM kaydı reddeder) - yalnız İKİSİ DE
    geçtikten SONRA lexicographic olarak SIRALANIR (madde 2: sıralama
    asla doğrulamanın YERİNE geçmez, yalnız doğrulamadan SONRA
    uygulanan bir NORMALİZASYONDUR)."""

    if selected_issue_ids is None:

        return None

    if selected_issue_ids == []:

        return []

    if len(selected_issue_ids) != len(set(selected_issue_ids)):

        raise DraftingRequestValidationError(
            "selected_issue_ids yinelenen değer(ler) içeriyor.",
            errors=["selected_issue_ids: yinelenen issue_id reddedildi"],
        )

    known_issue_ids = _load_canonical_issue_ids(case_id)

    unknown = sorted(set(selected_issue_ids) - known_issue_ids)

    if unknown:

        raise DraftingRequestValidationError(
            "selected_issue_ids, canonical issues.json'da bulunmayan (sahte/bilinmeyen/eski) "
            "id(ler) içeriyor.",
            errors=[f"selected_issue_ids: bilinmeyen issue_id sayısı={len(unknown)}"],
        )

    return sorted(selected_issue_ids)


# ============================================================
# PAYLAŞILAN TAM WRAPPER DOĞRULAYICISI (kontrat madde 1/4) - HEM HTTP
# servisi HEM CLI köprüsü, hem KAYDETME (write) ÖNCESİ/SONRASI hem de
# salt-okunur GÖRÜNTÜLEME (GET / `--generate-pending` verilmemiş CLI)
# için AYNI fonksiyonu çağırır. Sekiz kontrol de burada:
#   1) wrapper şeması (yerel $ref registry ile)
#   2) case_id eşleşmesi (allowlisted route/CLI case ile)
#   3) source sabiti
#   4) Row 15 normalize_lawyer_input semantiği (appeal_level kuralı)
#   5) GÜNCEL canonical issue üyeliği
#   6) yinelenen issue reddi
#   7) deterministik sıralama (ZATEN sıralı mı - burada YENİDEN
#      SIRALANMAZ, yalnız doğrulanır; bozuk/elle-değiştirilmiş bir
#      dosya bu yüzden REDDEDİLİR)
#   8) saklanan lawyer_input_hash tutarlılığı
# ============================================================

def validate_wrapper_schema_and_consistency(wrapper, expected_case_id):

    if not isinstance(wrapper, dict):

        raise DraftingRequestValidationError(
            "wrapper bir JSON nesnesi değil.", errors=["wrapper: dict bekleniyor"],
        )

    validator = build_wrapper_validator()

    schema_errors = _sanitized_schema_errors(validator, wrapper)

    if schema_errors:

        raise DraftingRequestValidationError(
            "wrapper şema doğrulamasından geçemedi.", errors=schema_errors,
        )

    if wrapper.get("case_id") != expected_case_id:

        raise DraftingRequestValidationError(
            "wrapper case_id, beklenen (allowlisted) case ile eşleşmiyor.",
            errors=["case_id: beklenen case ile eşleşmiyor"],
        )

    if wrapper.get("source") != "local_lawyer_ui_submission":

        raise DraftingRequestValidationError(
            "wrapper source sabiti geçersiz.", errors=["source: beklenen sabitle eşleşmiyor"],
        )

    lawyer_input = wrapper.get("lawyer_input")

    try:

        normalize_lawyer_input(lawyer_input)

    except DraftingEngineError as error:

        # DraftingEngineError mesajları YALNIZ draft_intent_type/
        # appeal_level gibi SABİT/kapalı-küme değerler taşır - avukatın
        # serbest metnini ASLA içermez, bu yüzden burada `str(error)`
        # kullanmak madde 7'yi İHLAL ETMEZ.
        raise DraftingRequestValidationError(
            "lawyer_input, Row 15 normalize_lawyer_input kuralından geçemedi.",
            errors=[f"lawyer_input: {error}"],
        ) from error

    selected_issue_ids = lawyer_input.get("selected_issue_ids")

    if selected_issue_ids:

        if len(selected_issue_ids) != len(set(selected_issue_ids)):

            raise DraftingRequestValidationError(
                "lawyer_input.selected_issue_ids yinelenen değer(ler) içeriyor.",
                errors=["selected_issue_ids: yinelenen issue_id"],
            )

        known_issue_ids = _load_canonical_issue_ids(expected_case_id)

        unknown = sorted(set(selected_issue_ids) - known_issue_ids)

        if unknown:

            raise DraftingRequestValidationError(
                "lawyer_input.selected_issue_ids bilinmeyen/sahte id(ler) içeriyor.",
                errors=[f"selected_issue_ids: bilinmeyen issue_id sayısı={len(unknown)}"],
            )

        if list(selected_issue_ids) != sorted(selected_issue_ids):

            raise DraftingRequestValidationError(
                "lawyer_input.selected_issue_ids deterministik (lexicographic) sırada değil.",
                errors=["selected_issue_ids: sıra deterministik değil"],
            )

    recomputed_hash = compute_lawyer_input_hash(lawyer_input)

    if recomputed_hash != wrapper.get("lawyer_input_hash"):

        raise DraftingRequestValidationError(
            "saklanan lawyer_input_hash, yeniden hesaplanan hash ile tutarsız.",
            errors=["lawyer_input_hash: tutarsız"],
        )

    return True


# ============================================================
# ATOMİK YAZMA / ÇAKIŞMAYA DAYANIKLI ADLANDIRMA (Row 18C'YE ÖZGÜ,
# BAĞIMSIZ - `drafting_engine.atomic_write_json`'ı İMPORT ETMEZ)
# ============================================================

def _atomic_write_json(path, data):

    path = Path(path)

    path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = path.parent / (path.name + ".tmp")

    with open(temp_path, "w", encoding="utf-8", newline="\n") as file:

        json.dump(data, file, ensure_ascii=False, indent=2)

        file.write("\n")

        file.flush()

        os.fsync(file.fileno())

    os.replace(temp_path, path)


def _cleanup_temp_file(path):

    temp_path = Path(path).parent / (Path(path).name + ".tmp")

    if temp_path.exists():

        temp_path.unlink()


def _reserve_collision_safe_path(directory, prefix, suffix, max_attempts=_MAX_NAMING_ATTEMPTS):
    """UTC mikrosaniye damgası + sayısal çakışma soneki (`_01`, `_02`,
    ...) ile `os.O_CREAT|os.O_EXCL` KULLANARAK BENZERSİZ, BOŞ bir dosya
    REZERVE eder (yalnız TEKRARLI saat okumasına GÜVENMEZ - mocked/
    düşük-çözünürlüklü bir saat AYNI mikrosaniyeyi dönebilir; bu
    fonksiyon bunu bir istisna/SIRADAKİ SONEK ile ÇÖZER). Tüm
    denemeler tükenirse `DraftingRequestNamingCollisionError` fırlatır
    - kapalı-tarafa düşülür, hiçbir şey yazılmaz."""

    directory = Path(directory)

    directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "Z"

    last_error = None

    for attempt in range(max_attempts):

        suffix_tag = "" if attempt == 0 else f"_{attempt:02d}"

        candidate = directory / f"{prefix}{timestamp}{suffix_tag}{suffix}"

        try:

            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)

            os.close(fd)

            return candidate

        except FileExistsError as error:

            last_error = error

            continue

    raise DraftingRequestNamingCollisionError(
        "Geçmiş/audit dosya adı çakışması, azami deneme sayısı içinde çözülemedi."
    ) from last_error


# ============================================================
# TAZELİK (FRESHNESS) TOKEN
# ============================================================

def compute_current_freshness_token(case_id):

    digest = sha256_file(get_current_input_path(case_id))

    return digest if digest is not None else NO_EXISTING_INPUT_SENTINEL


# ============================================================
# KAYDETME YAŞAM DÖNGÜSÜ (madde 3/6) - ilk-kayıt/üzerine-yazma
# rollback AYRIMI TAM olarak burada uygulanır.
# ============================================================

def _write_audit_record(case_id, *, action, previous_token, new_raw_hash, lawyer_input_hash, saved_at, history_backup_path):

    audit_dir = get_input_audit_dir(case_id)

    audit_path = _reserve_collision_safe_path(audit_dir, "lawyer_input_save_", ".audit.json")

    record = {
        "case_id": case_id,
        "action": action,
        "previous_input_token": previous_token,
        "new_current_raw_sha256": new_raw_hash,
        "lawyer_input_hash": lawyer_input_hash,
        "saved_at": saved_at,
        "history_backup_path": str(history_backup_path) if history_backup_path else None,
    }

    try:

        _atomic_write_json(audit_path, record)

    except Exception:

        if audit_path.exists():

            audit_path.unlink()

        raise

    return audit_path


def save_lawyer_input(case_id, wrapper, expected_current_input_hash):
    """`wrapper` ZATEN tam olarak inşa edilmiş VE
    `validate_wrapper_schema_and_consistency` ile ÖN-KONTROLDEN
    geçirilmiş olmalıdır (çağıran - `save_lawyer_input_from_form` -
    bunu garanti eder). Bu fonksiyon YALNIZ tazelik kontrolü + atomik
    yazma + POST-WRITE doğrulama + audit + (herhangi bir adım
    başarısız olursa) TAM rollback'ten sorumludur."""

    current_path = get_current_input_path(case_id)

    actual_token = compute_current_freshness_token(case_id)

    if actual_token != expected_current_input_hash:

        raise DraftingRequestStaleInputError(
            "Girdi bu ekran açıldıktan sonra değişti - kaydetme reddedildi (sıfır mutasyon, sıfır audit)."
        )

    is_first_save = actual_token == NO_EXISTING_INPUT_SENTINEL

    inputs_dir = get_inputs_dir(case_id)

    inputs_dir.mkdir(parents=True, exist_ok=True)

    provisional_backup_path = None

    if not is_first_save:

        history_dir = get_input_history_dir(case_id)

        provisional_backup_path = _reserve_collision_safe_path(
            history_dir, "lawyer_input_before_save_", ".json",
        )

        try:

            shutil.copy2(current_path, provisional_backup_path)

        except Exception:

            if provisional_backup_path.exists():

                provisional_backup_path.unlink()

            raise DraftingRequestSaveFailedError(
                "Mevcut girdinin geçici yedeği alınamadı - hiçbir şey değiştirilmedi."
            )

    try:

        _atomic_write_json(current_path, wrapper)

        written = _load_json_file(current_path)

        validate_wrapper_schema_and_consistency(written, case_id)

        new_raw_hash = sha256_file(current_path)

        audit_path = _write_audit_record(
            case_id,
            action="first_save" if is_first_save else "overwrite",
            previous_token=actual_token,
            new_raw_hash=new_raw_hash,
            lawyer_input_hash=wrapper.get("lawyer_input_hash"),
            saved_at=wrapper.get("saved_at"),
            history_backup_path=(
                None if is_first_save
                else to_repo_relative(provisional_backup_path)
            ),
        )

    except Exception as error:

        if is_first_save:

            if current_path.exists():

                current_path.unlink()

        else:

            # Orijinali BAYT-BAYT ve İZİNLERİYLE geri yükle (copy2 hem
            # içeriği hem mod/mtime bitlerini KORUR) - yazma adımının
            # KENDİSİ (os.replace ÖNCESİ) başarısız olduysa current_path
            # ZATEN orijinaldir; bu durumda da AYNI restore çağrısı
            # ZARARSIZDIR (bayt-bayt AYNI içeriği kendi üzerine kopyalar).
            shutil.copy2(provisional_backup_path, current_path)

            if provisional_backup_path.exists():

                provisional_backup_path.unlink()

        _cleanup_temp_file(current_path)

        if isinstance(error, DraftingRequestUiError):

            raise

        raise DraftingRequestSaveFailedError(
            "Kaydetme işlemi (yazma/doğrulama/audit) tamamlanamadı - değişiklikler geri alındı."
        ) from error

    return {"wrapper": written, "audit_path": audit_path, "history_backup_path": provisional_backup_path}


def save_lawyer_input_from_form(
    *,
    case_id,
    draft_intent_type_choice,
    appeal_level_choice,
    issue_selection_mode,
    selected_issue_ids_raw,
    request_type_raw,
    request_text_raw,
    lawyer_provided_text_raw,
    expected_current_input_hash,
):
    """Form -> (sözdizimsel doğrulama) -> (issue üyeliği + sıralama) ->
    (wrapper inşası) -> (TAM paylaşılan doğrulayıcı, ÖN-KONTROL olarak)
    -> (kaydetme yaşam döngüsü, TAZELİK kontrolü BURADA da tekrar
    KENDİ İÇİNDE yapılır) sırasını uygular."""

    lawyer_input = build_lawyer_input_from_form(
        draft_intent_type_choice=draft_intent_type_choice,
        appeal_level_choice=appeal_level_choice,
        issue_selection_mode=issue_selection_mode,
        selected_issue_ids_raw=selected_issue_ids_raw,
        request_type_raw=request_type_raw,
        request_text_raw=request_text_raw,
        lawyer_provided_text_raw=lawyer_provided_text_raw,
    )

    lawyer_input["selected_issue_ids"] = validate_and_sort_selected_issue_ids(
        lawyer_input["selected_issue_ids"], case_id,
    )

    try:

        normalized = normalize_lawyer_input(lawyer_input)

    except DraftingEngineError as error:

        raise DraftingRequestValidationError(
            "lawyer_input, Row 15 normalize_lawyer_input kuralından geçemedi.",
            errors=[f"lawyer_input: {error}"],
        ) from error

    saved_at = datetime.now().astimezone().isoformat()

    wrapper = {
        "schema_version": 1,
        "case_id": case_id,
        "saved_at": saved_at,
        "source": "local_lawyer_ui_submission",
        "lawyer_input_hash": compute_lawyer_input_hash(normalized),
        "lawyer_input": normalized,
    }

    # Yazmadan ÖNCE son bir tam-tutarlılık kontrolü (kontrat madde 6:
    # "validate and normalize every submitted value" - yazma İŞLEMİNDEN
    # ÖNCEKİ son savunma katmanı; POST-WRITE doğrulama `save_lawyer_input`
    # İÇİNDE AYRICA yapılır).
    validate_wrapper_schema_and_consistency(wrapper, case_id)

    result = save_lawyer_input(case_id, wrapper, expected_current_input_hash)

    return result["wrapper"]


def load_current_wrapper(case_id):
    """GÜNCEL dosyayı OLDUĞU GİBİ (doğrulamadan) yükler - `None` döner
    dosya yoksa. Doğrulama AYRI, açık bir adımdır
    (`validate_wrapper_schema_and_consistency`) - bu fonksiyon SESSİZCE
    geçersiz bir dosyayı GEÇERLİ gibi GÖSTERMEZ."""

    path = get_current_input_path(case_id)

    if not path.exists():

        return None

    return _load_json_file(path)


# ============================================================
# PENDING / CANONICAL EŞLEŞME DURUMU (salt-okunur karşılaştırma - Row
# 15'in KENDİ yol yardımcılarını [`get_pending_path`/`get_canonical_path`]
# OLDUĞU GİBİ kullanır, hiçbir şey YAZMAZ/DEĞİŞTİRMEZ)
# ============================================================

def _lawyer_input_hash_status(path, saved_hash):

    path = Path(path)

    if not path.exists():

        return {"exists": False, "matches_saved": None, "unreadable": False}

    try:

        data = _load_json_file(path)

        stored_hash = data.get("analysis_metadata", {}).get("lawyer_input_hash")

    except Exception:

        return {"exists": True, "matches_saved": None, "unreadable": True}

    return {"exists": True, "matches_saved": (stored_hash == saved_hash), "unreadable": False}


def get_pending_and_canonical_status(case_id, saved_hash):

    return {
        "pending": _lawyer_input_hash_status(get_pending_path(case_id), saved_hash),
        "canonical": _lawyer_input_hash_status(get_canonical_path(case_id), saved_hash),
    }


# ============================================================
# GET SAYFASI İÇİN TAM GÖRÜNÜM (main.py route'u bunu doğrudan çağırır)
# ============================================================

def build_drafting_request_view(case_id):

    current_wrapper = load_current_wrapper(case_id)

    current_validation_errors = None

    if current_wrapper is not None:

        try:

            validate_wrapper_schema_and_consistency(current_wrapper, case_id)

        except DraftingRequestValidationError as error:

            current_validation_errors = list(error.errors)

    saved_hash = current_wrapper.get("lawyer_input_hash") if current_wrapper else None

    try:

        canonical_issues = load_canonical_issues(case_id).get("issues", [])

    except (FileNotFoundError, LegalResearchValidationError):

        canonical_issues = []

    request_authorized_explanation = None

    if current_wrapper is not None and current_validation_errors is None:

        request_authorized_explanation = compute_request_authorized_explanation(
            current_wrapper["lawyer_input"],
        )

    status = get_pending_and_canonical_status(case_id, saved_hash)

    return {
        "current_wrapper": current_wrapper,
        "current_validation_errors": current_validation_errors,
        "expected_current_input_hash": compute_current_freshness_token(case_id),
        "canonical_issues": canonical_issues,
        "pending_status": status["pending"],
        "canonical_status": status["canonical"],
        "request_authorized_explanation": request_authorized_explanation,
    }
