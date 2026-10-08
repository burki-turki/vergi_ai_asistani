# ============================================================
# VERGİ AI - ADIM 10 B YOLU: MANUEL FACT GİRİŞİ MUTATION FACADE
# (`generation.fact_manual`).
#
# `src/manual_fact_entry_engine.py`'nin deterministik, ağsız pending
# writer'ını mutation coordinator/journal altyapısına bağlayan, AYRI ve
# BAĞIMSIZ (sekizinci) facade. Hiçbir mevcut facade GENİŞLETİLMEZ.
#
# KİMLİK (exact-scope §2.2):
#   action_family = generation.fact_manual
#   channel       = local_lawyer_manual_fact_cli
#   target_ref    = fact.<document_id>.pending   (document-scoped)
#   resource_key  = case:<case_id>
#   input_digest  = sha256(kanonik manifest) - attempt GİRMEZ
#   pre_revision  = sha256({revision_version, input_digest, attempt})
#   pre_hash      = sha256({snapshot_version, pre_revision,
#                           pending_presence, pending_sha256})
# `--expected-input-digest` HAM input_digest ile karşılaştırılır.
#
# KURAL YERLERİ: PL = pre-lock (bağlantı/kilit öncesi), PC = kilit
# altında sıfırdan yeniden okuma (`precondition_callback`), W = writer.
# PL/PC reddi SIFIR journal satırı ve SIFIR dosya bırakır; W hatası
# coordinator tarafından `reconciliation_required` yapılır.
#
# MESAJ SÖZLEŞMESİ: sabit Türkçe literal + kural kodu + gerekirse
# mantıksal ad. Alıntı metni, girdi içeriği, `str(alt_hata)` ve MUTLAK
# YOL mesaja girmez (`ui.cli_mutate` `str(error)` basar). Orijinal
# istisna yalnız `__cause__` olarak zincirlenir.
#
# M-09 JOURNAL DURUMU (N-L4): pending zaten varsa, mesaj aynı target_ref
# için son journal satırını (id + state) gösterir. Bu okuma YALNIZ apply
# yolunda ve DIŞ 'mutate' authz'ından SONRA yapılır: PL'de ayrı, salt-
# okunur, en-iyi-çaba bir bağlantıyla (hata -> "bilinmiyor"), PC'de
# kilidi tutan bağlantı üzerinden (iç authz'dan sonra). Preview journal
# OKUMAZ.
#
# OS-LEVEL LINK-SWAP / TOCTOU: kilit-altı doğrulama ile writer'ın tekil
# syscall'ları arasındaki dar pencere ATOMİK OLARAK KAPATILMAZ (Row 19A
# T15 -> Row 19D borcu).
# ============================================================

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mutation_guard import MutationIntent, compute_idempotency_key  # noqa: E402
import path_containment as _path_containment  # noqa: E402

from . import authz as _authz
from . import mutation_coordinator as _mutation_coordinator
from . import mutation_lock as _mutation_lock
from .common import (
    ApprovalUiError,
    PreconditionRaceDetectedError,
    StaleViewError,
)

ENGINE_MODULE_NAME = "manual_fact_entry_engine"

ACTION_FAMILY = "generation.fact_manual"

CHANNEL = "local_lawyer_manual_fact_cli"

TARGET_STATE = "generated"

MANIFEST_VERSION = "step10b.fact_manual.manifest.v1"

REVISION_VERSION = "step10b.fact_manual_revision.v1"

SNAPSHOT_VERSION = "step10b.fact_manual.snapshot.v1"

SNAPSHOT_ABSENT = "__absent__"

SNAPSHOT_PRESENT = "__present__"

_CASE_RESOURCE_KEY_PREFIX = "case:"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

_logger = logging.getLogger("vergi_ai.manual_fact_mutation_facade")


def _log_critical_safely(message: str) -> None:
    try:
        _logger.critical(message)
    except Exception:
        pass


def manual_fact_target_ref_for(document_id: str) -> str:
    return f"fact.{document_id}.pending"


def _engine():
    return importlib.import_module(ENGINE_MODULE_NAME)


# ----------------------------------------------------------------
# Hata sınıfları - `ManualFactPostWriteInvariantError` dışında HEPSİ
# `ApprovalUiError` alt sınıfıdır (`ui.cli_mutate._is_known_domain_error`
# değişmeden tanır).
# ----------------------------------------------------------------


class ManualFactArgumentError(ApprovalUiError):
    """Kullanım-şekli ihlali - her DB/dosya I/O'sundan ÖNCE."""


class ManualFactInputContainmentError(ApprovalUiError):
    """Okunan/yazılacak bir yol containment doğrulamasından geçemedi
    (yok / kırık / döngüsel / kaçan / in-tree alias / normal dosya
    değil)."""


class ManualFactInputInvalidError(ApprovalUiError):
    """Manuel girdi kodlama/şema/tarih kuralını ihlal ediyor (M-02,
    M-03, M-15)."""


class ManualFactDocumentIneligibleError(ApprovalUiError):
    """Hedef belge uygun değil (M-04 sayfa, M-05 tür/aktiflik)."""


class ManualFactSourceTextUnavailableError(ApprovalUiError):
    """`extracted/<doc>.txt` okunamadı veya boş (M-06)."""


class ManualFactExcerptRejectedError(ApprovalUiError):
    """Alıntı metinde bulunamadı veya tarihi girilen date ile eşleşmiyor
    (M-07, M-08)."""


class ManualFactPendingExistsError(ApprovalUiError):
    """Pending (sabit ad) zaten mevcut (M-09)."""


class ManualFactCanonicalExistsError(ApprovalUiError):
    """Canonical facts.json zaten mevcut (M-10)."""


class ManualFactCandidateInvalidError(ApprovalUiError):
    """Bellek-içi aday doğrulaması başarısız (M-11a)."""


class ManualFactIdentityMismatchError(ApprovalUiError):
    """case_id/document_id üç yönlü kimlik kontrolü başarısız (M-13)."""


class ManualFactTempResidueError(ApprovalUiError):
    """Önceki sert çöküşten kalan writer temp dosyası mevcut (M-14).
    Kod onu SİLMEZ; insan inceleyip kaldırır."""


class ManualFactResolvedCaseIdMismatchError(ApprovalUiError):
    """İç (kilit-altı) authz farklı bir case çözdü."""


class ManualFactWriteFailedError(ApprovalUiError):
    """Writer sınırı GEÇİLDİKTEN sonra hata (M-11b validator FAIL, I/O
    hatası). Journal satırı `reconciliation_required`'dır ve case
    gate'lidir; mesaj journal_id'yi ve reconciliation komutunu taşır."""


class ManualFactAuditBindingVerificationFailedError(ApprovalUiError):
    """Completed safe-replay corroboration başarısız - insan
    reconciliation'ı gerekir."""

    def __init__(self, *, journal_id: int, idempotency_key: str, reason: str):
        self.journal_id = journal_id
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(
            f"journal_id={journal_id}: manuel fact safe-replay audit doğrulaması başarısız "
            f"(idempotency_key={idempotency_key}): {reason}"
        )


def _post_write_invariant_class():
    return _engine().ManualFactPostWriteInvariantError


# ----------------------------------------------------------------
# Motor hatası -> facade hatası (1:1, exact-scope §2.5).
# ----------------------------------------------------------------

_ENGINE_TRANSLATION = (
    ("ManualFactEncodingError", ManualFactInputInvalidError),
    ("ManualFactInputSchemaError", ManualFactInputInvalidError),
    ("ManualFactDateInvalidError", ManualFactInputInvalidError),
    ("ManualFactPageError", ManualFactDocumentIneligibleError),
    ("ManualFactDocumentTypeError", ManualFactDocumentIneligibleError),
    ("ManualFactSourceTextError", ManualFactSourceTextUnavailableError),
    ("ManualFactExcerptNotFoundError", ManualFactExcerptRejectedError),
    ("ManualFactExcerptDateMismatchError", ManualFactExcerptRejectedError),
    ("ManualFactCandidateInvalidError", ManualFactCandidateInvalidError),
)


def _translate_engine_error(error):
    for class_name, target in _ENGINE_TRANSLATION:
        if type(error).__name__ == class_name:
            return target(
                f"Manuel fact girişi reddedildi (kural {error.rule}; {class_name}). "
                "HİÇBİR değişiklik yapılmadı."
            )
    return ManualFactInputInvalidError(
        f"Manuel fact girişi reddedildi ({type(error).__name__}). HİÇBİR değişiklik yapılmadı."
    )


# ----------------------------------------------------------------
# Argüman şekli - her I/O'dan önce.
# ----------------------------------------------------------------


def _check_argument_shapes(case_id, document_id, expected_input_digest=None, attempt=1, *, for_apply: bool):
    for label, value in (("case_id", case_id), ("document_id", document_id)):
        try:
            _path_containment.validate_segment(value)
        except _path_containment.PathContainmentError as error:
            raise ManualFactArgumentError(f"{label} geçersiz bir path bileşeni.") from error
        if value != value.strip():
            raise ManualFactArgumentError(f"{label} baş/son boşluk içeremez.")
    if type(attempt) is not int or attempt < 1:
        raise ManualFactArgumentError("attempt >= 1 bir tamsayı olmalıdır.")
    if for_apply:
        if not isinstance(expected_input_digest, str) or not _SHA256_HEX_RE.match(expected_input_digest):
            raise ManualFactArgumentError(
                "expected_input_digest 64 karakterlik küçük harf hex olmalıdır."
            )
    else:
        if expected_input_digest is not None:
            raise ManualFactArgumentError("expected_input_digest yalnız apply ile anlamlıdır.")
        if attempt != 1:
            raise ManualFactArgumentError("attempt yalnız apply ile anlamlıdır.")


# ----------------------------------------------------------------
# CONTAINMENT - bu modülün KENDİ bağımsız kopyası (adapter kendi
# kopyasını taşır). Her segmentte: validate_segment -> lexists ->
# resolve_existing -> parent eşitliği VE ad eşitliği (aynı dizindeki
# kardeşe işaret eden link'i de reddeder).
# ----------------------------------------------------------------


def _resolve_case_root_real(module, case_id: str) -> Path:
    cases_dir = module.CASES_DIR
    try:
        _path_containment.validate_segment(case_id)
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise ManualFactInputContainmentError(
            "Case kökü containment doğrulamasından geçemedi (kural M-01)."
        ) from error


def _verify_existing_child(current_real: Path, seg: str, case_root_real: Path, logical_name: str) -> Path:
    try:
        _path_containment.validate_segment(seg)
    except _path_containment.PathContainmentError as error:
        raise ManualFactInputContainmentError(
            f"{logical_name}: geçersiz segment adı (kural M-01)."
        ) from error
    raw_candidate = current_real / seg
    if not os.path.lexists(raw_candidate):
        raise ManualFactInputContainmentError(f"{logical_name}: bulunamadı (kural M-01).")
    try:
        seg_real = _path_containment.resolve_existing(raw_candidate, root=case_root_real)
    except _path_containment.PathContainmentError as error:
        raise ManualFactInputContainmentError(
            f"{logical_name}: containment doğrulamasından geçemedi (kaçan/kırık/döngüsel giriş; kural M-01)."
        ) from error
    if seg_real.parent != current_real or seg_real.name != seg:
        raise ManualFactInputContainmentError(
            f"{logical_name}: beklenen dizinin doğrudan çocuğu değil (in-tree alias; kural M-01)."
        )
    return seg_real


def _read_single_file(case_root_real: Path, segments, logical_name: str):
    """Sabit segment dizisini tarar ve dosyayı BİR KEZ okur. Dönüş:
    (çözümlenmiş yol, ham baytlar)."""
    current_real = case_root_real
    for index, seg in enumerate(segments):
        seg_real = _verify_existing_child(current_real, seg, case_root_real, logical_name)
        is_last = index == len(segments) - 1
        if is_last:
            if not seg_real.is_file():
                raise ManualFactInputContainmentError(
                    f"{logical_name}: normal bir dosya değil (kural M-01)."
                )
        elif not seg_real.is_dir():
            raise ManualFactInputContainmentError(f"{logical_name}: ara segment dizin değil (kural M-01).")
        current_real = seg_real
    try:
        data = current_real.read_bytes()
    except OSError as error:
        raise ManualFactInputContainmentError(f"{logical_name}: okunamadı (kural M-01).") from error
    return current_real, data


def _scan_case_documents(case_root_real: Path):
    """Validator'ın `documents_dir.glob("*/document.json")` kümesinin
    containment-first karşılığı (N-O3). Dönüş: [(mantıksal_ad, ham
    bayt)], sıralı. Alias/kaçan giriş TÜM taramayı durdurur."""
    documents_real = _verify_existing_child(case_root_real, "documents", case_root_real, "documents")
    if not documents_real.is_dir():
        raise ManualFactInputContainmentError("documents: dizin değil (kural M-01).")
    try:
        entries = sorted(documents_real.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise ManualFactInputContainmentError("documents: listelenemedi (kural M-01).") from error

    results = []
    seen = set()
    for entry in entries:
        name = entry.name
        entry_real = _verify_existing_child(documents_real, name, case_root_real, f"documents/{name}")
        if not entry_real.is_dir():
            continue
        leaf_raw = entry_real / "document.json"
        if not os.path.lexists(leaf_raw):
            continue
        leaf_real = _verify_existing_child(
            entry_real, "document.json", case_root_real, f"documents/{name}/document.json",
        )
        if not leaf_real.is_file():
            raise ManualFactInputContainmentError(
                f"documents/{name}/document.json: normal bir dosya değil (kural M-01)."
            )
        if leaf_real in seen:
            raise ManualFactInputContainmentError("documents: duplicate/alias çözümlenmiş yol (kural M-01).")
        seen.add(leaf_real)
        try:
            data = leaf_real.read_bytes()
        except OSError as error:
            raise ManualFactInputContainmentError(
                f"documents/{name}/document.json: okunamadı (kural M-01)."
            ) from error
        results.append((f"documents/{name}/document.json", data))
    return results


def _verify_write_dir_chain(case_root_real: Path, segments, logical_name: str) -> Path:
    """Yazma tarafı ara dizinleri (N-L6): mevcut her segment gerçek bir
    dizin olmalı ve parent/ad eşitliğini sağlamalı; ilk mevcut olmayan
    segmentten itibaren yol yalnız İNŞA edilir (dosya sistemine
    dokunulmaz)."""
    current = case_root_real
    for index, seg in enumerate(segments):
        try:
            _path_containment.validate_segment(seg)
        except _path_containment.PathContainmentError as error:
            raise ManualFactInputContainmentError(f"{logical_name}: geçersiz segment (kural M-01).") from error
        if not os.path.lexists(current / seg):
            for rest in segments[index:]:
                _path_containment.validate_segment(rest)
                current = current / rest
            return current
        seg_real = _verify_existing_child(current, seg, case_root_real, logical_name)
        if not seg_real.is_dir():
            raise ManualFactInputContainmentError(f"{logical_name}: dizin değil (kural M-01).")
        current = seg_real
    return current


@dataclass(frozen=True)
class _OutputPaths:
    document_dir: Path
    extractions_dir: Path
    reviews_dir: Path
    pending_path: Path
    temp_path: Path
    canonical_path: Path

    @property
    def identity(self):
        return tuple(str(p) for p in (
            self.document_dir, self.extractions_dir, self.reviews_dir,
            self.pending_path, self.temp_path, self.canonical_path,
        ))


def _derive_output_paths(module, case_root_real: Path, document_id: str) -> _OutputPaths:
    document_dir = _verify_write_dir_chain(case_root_real, ("documents", document_id), "documents/<doc>")
    if not os.path.lexists(document_dir):
        raise ManualFactInputContainmentError("documents/<doc>: belge dizini bulunamadı (kural M-01).")
    extractions_dir = _verify_write_dir_chain(
        case_root_real, ("documents", document_id, "extractions"), "extractions",
    )
    reviews_dir = _verify_write_dir_chain(
        case_root_real,
        ("documents", document_id, "extractions", module.GENERATION_REVIEWS_DIRNAME),
        "generation_reviews",
    )
    for name in (module.CURRENT_PENDING_FILENAME, module.TEMP_FILENAME, module.CANONICAL_FILENAME):
        _path_containment.validate_segment(name)
    return _OutputPaths(
        document_dir=document_dir,
        extractions_dir=extractions_dir,
        reviews_dir=reviews_dir,
        pending_path=extractions_dir / module.CURRENT_PENDING_FILENAME,
        temp_path=extractions_dir / module.TEMP_FILENAME,
        canonical_path=extractions_dir / module.CANONICAL_FILENAME,
    )


# ----------------------------------------------------------------
# KİMLİK FORMÜLLERİ (adapter bağımsız kopyasını taşır; F-N12 canary).
# ----------------------------------------------------------------


def _canonical_bytes(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def compute_input_digest(manifest: dict) -> str:
    return hashlib.sha256(_canonical_bytes(manifest)).hexdigest()


def compute_pre_revision(input_digest: str, attempt: int) -> str:
    return hashlib.sha256(_canonical_bytes({
        "revision_version": REVISION_VERSION,
        "input_digest": input_digest,
        "attempt": attempt,
    })).hexdigest()


def _sha256_of_lexisting_file(path: Path):
    if not os.path.lexists(path):
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "__unreadable__"


def compute_pre_hash(pre_revision: str, pending_path: Path) -> str:
    sha = _sha256_of_lexisting_file(pending_path)
    presence = SNAPSHOT_PRESENT if sha is not None else SNAPSHOT_ABSENT
    return hashlib.sha256(_canonical_bytes({
        "snapshot_version": SNAPSHOT_VERSION,
        "pre_revision": pre_revision,
        "pending_presence": presence,
        "pending_sha256": sha if sha is not None else SNAPSHOT_ABSENT,
    })).hexdigest()


# ----------------------------------------------------------------
# TOPLAMA + DEĞERLENDİRME (PL ve PC aynı fonksiyonu sıfırdan çağırır).
# ----------------------------------------------------------------


@dataclass(frozen=True)
class _Evaluation:
    case_root_real: Path
    paths: _OutputPaths
    manifest: dict
    input_digest: str
    frozen_pending_bytes: bytes
    pending_sha256: str
    notification_date: str
    page: int
    excerpt_sha256: str


def _journal_state_text(lookup):
    if lookup is None:
        return "journal durumu: kayıt yok/bilinmiyor"
    journal_id, state = lookup
    return f"journal durumu: journal_id={journal_id} state={state}"


def _lookup_family_journal_state(conn, resource_key: str, target_ref: str):
    """En-iyi-çaba, salt-okunur: aynı aile + target_ref için son satır.
    Hata -> None (mesaj 'bilinmiyor' der)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, state FROM mutation.mutation_journal WHERE resource_key = %s "
                "AND action_family = %s AND target_ref = %s ORDER BY id DESC LIMIT 1",
                (resource_key, ACTION_FAMILY, target_ref),
            )
            row = cur.fetchone()
    except Exception:
        return None
    if not row:
        return None
    return row[0], row[1]


def _check_output_absence(paths: _OutputPaths, *, journal_lookup=None) -> None:
    if os.path.lexists(paths.canonical_path):
        raise ManualFactCanonicalExistsError(
            "Bu belge için canonical facts.json zaten mevcut; manuel giriş reddedildi "
            "(kural M-10). HİÇBİR değişiklik yapılmadı."
        )
    if os.path.lexists(paths.pending_path):
        state_text = _journal_state_text(journal_lookup() if journal_lookup is not None else None)
        raise ManualFactPendingExistsError(
            "Bu belge için pending extraction zaten mevcut (kime ait olursa olsun); manuel giriş "
            f"reddedildi (kural M-09; {state_text}). HİÇBİR değişiklik yapılmadı."
        )
    if os.path.lexists(paths.temp_path):
        raise ManualFactTempResidueError(
            "Önceki bir çöküşten kalan writer temp dosyası mevcut; insan incelemesi ve elle "
            "kaldırma gerekir (kural M-14). Kod onu silmez. HİÇBİR değişiklik yapılmadı."
        )


def _parse_json_bytes(data: bytes, logical_name: str):
    try:
        return json.loads(bytes(data).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManualFactInputInvalidError(f"{logical_name} geçerli JSON değil (kural M-15).") from error


def _evaluate(module, case_id: str, document_id: str, *, journal_lookup=None) -> _Evaluation:
    case_root_real = _resolve_case_root_real(module, case_id)
    paths = _derive_output_paths(module, case_root_real, document_id)
    _check_output_absence(paths, journal_lookup=journal_lookup)

    _input_path, manual_input_bytes = _read_single_file(
        case_root_real,
        ("documents", document_id, module.MANUAL_INPUT_DIRNAME, module.MANUAL_INPUT_FILENAME),
        "manual_input",
    )
    _case_path, case_bytes = _read_single_file(case_root_real, ("case.json",), "case.json")
    _doc_path, document_bytes = _read_single_file(
        case_root_real, ("documents", document_id, "document.json"), "document.json",
    )
    try:
        _text_path, text_bytes = _read_single_file(
            case_root_real, ("documents", document_id, "extracted", f"{document_id}.txt"),
            "extracted/<doc>.txt",
        )
    except ManualFactInputContainmentError as error:
        raise ManualFactSourceTextUnavailableError(
            "Belge metni (extracted/<doc>.txt) bulunamadı veya containment doğrulamasından "
            "geçemedi (kural M-06). HİÇBİR değişiklik yapılmadı."
        ) from error
    case_documents = _scan_case_documents(case_root_real)

    try:
        schema_bytes = Path(module.INPUT_SCHEMA_PATH).read_bytes()
        fact_schema = json.loads(Path(module.FACT_SCHEMA_PATH).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManualFactInputInvalidError("Repo şema dosyaları okunamadı (kural M-02).") from error

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "case_id": case_id,
        "document_id": document_id,
        "engine_version": module.MANUAL_FACT_ENGINE_VERSION,
        "input_schema_sha256": hashlib.sha256(schema_bytes).hexdigest(),
        "manual_input_sha256": hashlib.sha256(manual_input_bytes).hexdigest(),
        "case_json_sha256": hashlib.sha256(case_bytes).hexdigest(),
        "document_json_sha256": hashlib.sha256(document_bytes).hexdigest(),
        "source_text_sha256": hashlib.sha256(text_bytes).hexdigest(),
        "case_documents": [
            {"logical_relative_path": rel, "sha256": hashlib.sha256(data).hexdigest()}
            for rel, data in case_documents
        ],
    }
    input_digest = compute_input_digest(manifest)

    try:
        result = module.evaluate_candidate(
            case_id=case_id,
            document_id=document_id,
            input_digest=input_digest,
            manual_input_bytes=manual_input_bytes,
            input_schema_bytes=schema_bytes,
            document_bytes=document_bytes,
            source_text_bytes=text_bytes,
            fact_schema=fact_schema,
        )
    except module.ManualFactEntryError as error:
        raise _translate_engine_error(error) from error

    # M-13: üç yönlü kimlik.
    case_data = _parse_json_bytes(case_bytes, "case.json")
    manual_input = result["manual_input"]
    document = result["document"]
    if not (
        manual_input.get("case_id") == case_id
        and isinstance(case_data, dict) and case_data.get("case_id") == case_id
        and document.get("case_id") == case_id
    ):
        raise ManualFactIdentityMismatchError(
            "case_id girdi / --case / document.json / case.json arasında eşleşmiyor (kural M-13). "
            "HİÇBİR değişiklik yapılmadı."
        )
    if not (
        manual_input.get("document_id") == document_id
        and document.get("document_id") == document_id
        and paths.document_dir.name == document_id
    ):
        raise ManualFactIdentityMismatchError(
            "document_id girdi / --document / document.json / belge dizini arasında eşleşmiyor "
            "(kural M-13). HİÇBİR değişiklik yapılmadı."
        )

    return _Evaluation(
        case_root_real=case_root_real,
        paths=paths,
        manifest=manifest,
        input_digest=input_digest,
        frozen_pending_bytes=result["frozen_pending_bytes"],
        pending_sha256=result["pending_sha256"],
        notification_date=result["notification_date"],
        page=result["page"],
        excerpt_sha256=result["excerpt_sha256"],
    )


# ----------------------------------------------------------------
# AUTHZ REPO / CONN KURULUMU.
# ----------------------------------------------------------------


def _default_authz_repository():
    from . import db as _db
    conn = _db.get_connection()
    return _authz.PostgresAuthzRepository(conn), conn.close


def _resolve_authz_repository(authz_repository):
    if authz_repository is not None:
        return authz_repository, lambda: None
    return _default_authz_repository()


def _default_conn_factory():
    from . import db as _db
    return _db.get_session_lock_connection()


# ----------------------------------------------------------------
# PREVIEW (salt-okunur; journal okumaz; alıntı metni DÖNDÜRMEZ - K-18).
# ----------------------------------------------------------------


def preview_manual_fact(case_id: str, document_id: str, *, principal, authz_repository=None) -> dict:
    _check_argument_shapes(case_id, document_id, for_apply=False)
    module = _engine()

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "read", repository=repository,
        )
        evaluation = _evaluate(module, resolved_case_id, document_id)
        return {
            "case_id": resolved_case_id,
            "document_id": document_id,
            "target_ref": manual_fact_target_ref_for(document_id),
            "input_digest": evaluation.input_digest,
            "pending_sha256": evaluation.pending_sha256,
            "notification_date": evaluation.notification_date,
            "page": evaluation.page,
            "excerpt_found": True,
            "text_excerpt_sha256": evaluation.excerpt_sha256,
        }
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(f"WARNING: preview_manual_fact authz repository close failed: {close_error!r}")


# ----------------------------------------------------------------
# REPLAY CORROBORATION (completed satır; N-L3).
# ----------------------------------------------------------------


def _scan_generation_audits(case_root_real: Path, reviews_dir: Path):
    import fnmatch

    if not os.path.lexists(reviews_dir):
        return []
    try:
        reviews_real = _path_containment.resolve_existing(reviews_dir, root=case_root_real)
    except _path_containment.PathContainmentError as error:
        raise ManualFactInputContainmentError("generation_reviews containment hatası.") from error
    if reviews_real != reviews_dir or not reviews_real.is_dir():
        raise ManualFactInputContainmentError("generation_reviews: in-tree alias veya dizin değil.")
    try:
        entries = sorted(reviews_real.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise ManualFactInputContainmentError("generation_reviews listelenemedi.") from error
    results = []
    for entry in entries:
        if not fnmatch.fnmatchcase(entry.name, "*.generation_audit.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise ManualFactInputContainmentError("generation_reviews girdisi containment hatası.") from error
        if resolved.parent != reviews_real or resolved.name != entry.name:
            raise ManualFactInputContainmentError("generation_reviews girdisi in-tree alias.")
        try:
            record = json.loads(resolved.read_bytes().decode("utf-8"))
            if not isinstance(record, dict):
                record = None
        except Exception:
            record = None
        results.append((resolved, record))
    return results


def _audit_record_matches(record, *, case_id, document_id, idempotency_key, resource_key,
                          target_ref, actor_ref, pending_sha256, pre_revision) -> bool:
    if not isinstance(record, dict):
        return False
    expected = {
        "schema_version": "1",
        "case_id": case_id,
        "document_id": document_id,
        "target_ref": target_ref,
        "target_state": TARGET_STATE,
        "action_family": ACTION_FAMILY,
        "channel": CHANNEL,
        "mutation_actor_ref": actor_ref,
        "mutation_idempotency_key": idempotency_key,
        "mutation_resource_key": resource_key,
        "pending_sha256": pending_sha256,
        "outcome": "generated",
        "revision_version": REVISION_VERSION,
    }
    for key, value in expected.items():
        if record.get(key) != value:
            return False
    input_digest = record.get("input_digest")
    attempt = record.get("attempt")
    if not isinstance(input_digest, str) or not _SHA256_HEX_RE.match(input_digest):
        return False
    if type(attempt) is not int or attempt < 1:
        return False
    identity_payload = record.get("identity_payload")
    if not isinstance(identity_payload, dict) or compute_input_digest(identity_payload) != input_digest:
        return False
    composite = compute_pre_revision(input_digest, attempt)
    return composite == pre_revision and record.get("pre_revision") == pre_revision


def _verify_completed_replay_binding(module, case_id, document_id, *, outcome, idempotency_key,
                                     resource_key, target_ref, actor_ref, pre_revision):
    def fail(reason):
        raise ManualFactAuditBindingVerificationFailedError(
            journal_id=outcome.journal_id, idempotency_key=idempotency_key, reason=reason,
        )

    if outcome.state != "completed":
        fail("journal satırı 'completed' değil")
    try:
        case_root_real = _resolve_case_root_real(module, case_id)
        paths = _derive_output_paths(module, case_root_real, document_id)
        entries = _scan_generation_audits(case_root_real, paths.reviews_dir)
    except ManualFactInputContainmentError:
        fail("replay doğrulaması sırasında containment hatası")
    current_sha = _sha256_of_lexisting_file(paths.pending_path)
    if current_sha is None or not paths.pending_path.is_file():
        fail("pending artefakt şu an mevcut değil")
    if outcome.observed_post_hash != current_sha:
        fail("journal observed_post_hash diskteki pending ile eşleşmiyor")
    if any(record is None for _path, record in entries):
        fail("generation_reviews içinde ayrıştırılamayan audit var")
    matches = [
        path for path, record in entries
        if _audit_record_matches(
            record, case_id=case_id, document_id=document_id, idempotency_key=idempotency_key,
            resource_key=resource_key, target_ref=target_ref, actor_ref=actor_ref,
            pending_sha256=current_sha, pre_revision=pre_revision,
        )
    ]
    if len(matches) != 1:
        fail(f"tam bağlamalı audit sayısı {len(matches)} (tam 1 olmalı)")
    return current_sha, matches[0]


# ----------------------------------------------------------------
# APPLY
# ----------------------------------------------------------------


@dataclass(frozen=True)
class ManualFactApplyResult:
    case_id: str
    document_id: str
    pending_sha256: str
    audit_file: str | None
    journal_id: int
    attempt: int
    replayed: bool


def _close_quietly(conn, label):
    try:
        conn.close()
    except Exception as close_error:
        _log_critical_safely(f"WARNING: {label} close failed: {close_error!r}")


def apply_manual_fact(
    case_id: str,
    document_id: str,
    expected_input_digest: str,
    *,
    attempt: int = 1,
    principal,
    authz_repository=None,
    conn_factory=None,
) -> ManualFactApplyResult:
    """SIRA: (1) argüman şekli; (2) DIŞ 'mutate' authz; (3) PL kuralları
    + expected_input_digest; (4) intent; (5) bağlantı + case kilidi;
    (6) run_mutation (iç authz -> gate -> idempotency -> PC [sıfırdan
    kilit-altı yeniden değerlendirme] -> prepared -> executing ->
    writer); (7) replay'de tam corroboration."""
    _check_argument_shapes(case_id, document_id, expected_input_digest, attempt, for_apply=True)
    module = _engine()
    factory = conn_factory or _default_conn_factory
    target_ref = manual_fact_target_ref_for(document_id)

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        outer_case_id = _authz.authorize_case_access(principal, case_id, "mutate", repository=repository)
        resource_key = _mutation_lock.case_resource_key(outer_case_id)

        def pre_lock_journal_lookup():
            try:
                lookup_conn = factory()
            except Exception:
                return None
            try:
                return _lookup_family_journal_state(lookup_conn, resource_key, target_ref)
            finally:
                _close_quietly(lookup_conn, "pre-lock journal lookup connection")

        pre = _evaluate(module, outer_case_id, document_id, journal_lookup=pre_lock_journal_lookup)

        if pre.input_digest != expected_input_digest:
            raise StaleViewError(
                "Preview alındıktan sonra manuel girdi veya bağlı belgeler DEĞİŞTİ "
                f"(beklenen input_digest: {expected_input_digest}, şimdiki: {pre.input_digest}). "
                "İşlem iptal edildi, HİÇBİR değişiklik yapılmadı."
            )

        pre_revision = compute_pre_revision(pre.input_digest, attempt)
        pre_hash = compute_pre_hash(pre_revision, pre.paths.pending_path)

        intent = MutationIntent(
            actor_type="iam_user",
            actor_ref=str(principal.user_id),
            resource_key=resource_key,
            action_family=ACTION_FAMILY,
            target_ref=target_ref,
            target_state=TARGET_STATE,
            pre_hash=pre_hash,
            pre_revision=pre_revision,
            secondary_input_hash=None,
        )
        idempotency_key = compute_idempotency_key(intent)

        under_lock_box = {}
        conn_box = {}

        def authz_callback() -> None:
            inner_case_id = _authz.authorize_case_access(principal, case_id, "mutate", repository=repository)
            if inner_case_id != outer_case_id:
                raise ManualFactResolvedCaseIdMismatchError(
                    "İç authz farklı bir case çözdü; reddedildi."
                )

        def precondition_callback() -> None:
            held_conn = conn_box["conn"]
            ul = _evaluate(
                module, outer_case_id, document_id,
                journal_lookup=lambda: _lookup_family_journal_state(held_conn, resource_key, target_ref),
            )
            if ul.paths.identity != pre.paths.identity or ul.case_root_real != pre.case_root_real:
                raise PreconditionRaceDetectedError(
                    "Kilit beklenirken ilgili dizinlerin çözümlenmiş konumu DEĞİŞTİ (link swap veya "
                    "benzeri). İşlem iptal edildi, HİÇBİR değişiklik yapılmadı."
                )
            if ul.input_digest != pre.input_digest:
                raise PreconditionRaceDetectedError(
                    "Kilit beklenirken manuel girdi veya bağlı belgeler DEĞİŞTİ. İşlem iptal edildi, "
                    "HİÇBİR değişiklik yapılmadı."
                )
            if ul.input_digest != expected_input_digest:
                raise StaleViewError(
                    "Kilit altındaki input_digest beklenen değerle eşleşmiyor. İşlem iptal edildi."
                )
            if compute_pre_hash(pre_revision, ul.paths.pending_path) != pre_hash:
                raise PreconditionRaceDetectedError(
                    "Kilit beklenirken pending durumu DEĞİŞTİ. İşlem iptal edildi, HİÇBİR değişiklik "
                    "yapılmadı."
                )
            if ul.frozen_pending_bytes != pre.frozen_pending_bytes:
                raise PreconditionRaceDetectedError(
                    "Kilit altında üretilen aday baytları pre-lock adayından farklı. İşlem iptal edildi."
                )
            under_lock_box["evaluation"] = ul
            under_lock_box["audit_record"] = {
                "schema_version": module.GENERATION_AUDIT_SCHEMA_VERSION,
                "case_id": outer_case_id,
                "document_id": document_id,
                "target_ref": target_ref,
                "target_state": TARGET_STATE,
                "action_family": ACTION_FAMILY,
                "channel": CHANNEL,
                "mutation_actor_ref": str(principal.user_id),
                "mutation_idempotency_key": idempotency_key,
                "mutation_resource_key": resource_key,
                "input_digest": ul.input_digest,
                "attempt": attempt,
                "revision_version": REVISION_VERSION,
                "pre_revision": pre_revision,
                "identity_payload": json.loads(json.dumps(ul.manifest)),
                "excerpt_sha256": ul.excerpt_sha256,
                "engine_version": module.MANUAL_FACT_ENGINE_VERSION,
                "extractor_version": module.EXTRACTOR_VERSION,
                "first_write": True,
                "outcome": "generated",
                "written_at": _now_iso(),
            }

        def writer_callback() -> _mutation_coordinator.WriterResult:
            ul = under_lock_box["evaluation"]
            try:
                written = module.write_manual_pending(
                    extractions_dir=ul.paths.extractions_dir,
                    reviews_dir=ul.paths.reviews_dir,
                    pending_path=ul.paths.pending_path,
                    temp_path=ul.paths.temp_path,
                    frozen_pending_bytes=ul.frozen_pending_bytes,
                    audit_record=under_lock_box["audit_record"],
                    document_id=document_id,
                )
            except module.ManualFactPostWriteInvariantError:
                raise
            except (module.ManualFactEntryError, OSError, ValueError,
                    _path_containment.PathContainmentError) as error:
                raise ManualFactWriteFailedError(
                    f"Manuel fact writer'ı başarısız ({type(error).__name__})."
                ) from error
            under_lock_box["audit_path"] = written["audit_path"]
            return _mutation_coordinator.WriterResult(
                observed_post_hash=written["pending_sha256"],
                result=None,
            )

        conn = factory()
        conn_box["conn"] = conn
        advisory_lock_id = _mutation_lock.acquire_case_lock_session(conn, outer_case_id)
        try:
            try:
                outcome = _mutation_coordinator.run_mutation(
                    conn, intent,
                    actor_user_id=principal.user_id,
                    authz_callback=authz_callback,
                    precondition_callback=precondition_callback,
                    writer_callback=writer_callback,
                )
            except ManualFactWriteFailedError as error:
                # N-L7: writer sınırı geçildi; satır reconciliation_required
                # ve case gate'li. Mesaj journal kimliğini ve çözüm yolunu
                # taşır.
                journal_text = "journal_id=bilinmiyor"
                try:
                    found = _mutation_coordinator._idempotency_lookup(conn, idempotency_key)
                    if found is not None:
                        journal_text = f"journal_id={found[0]} state={found[1]}"
                except Exception:
                    pass
                raise ManualFactWriteFailedError(
                    f"{error} Writer sınırı geçildi; {journal_text}. Case bu satır çözülene kadar "
                    "gate'lidir: önce `python -m ui.reconciliation_operator --journal-id <ID>` ile "
                    "inceleyin, ardından yeniden deneme için `--attempt N+1` kullanın."
                ) from error.__cause__

            if outcome.replayed:
                verified_sha, audit_path = _verify_completed_replay_binding(
                    module, outer_case_id, document_id, outcome=outcome,
                    idempotency_key=idempotency_key, resource_key=resource_key,
                    target_ref=target_ref, actor_ref=str(principal.user_id), pre_revision=pre_revision,
                )
            else:
                verified_sha = outcome.observed_post_hash
                audit_path = under_lock_box.get("audit_path")

            return ManualFactApplyResult(
                case_id=outer_case_id,
                document_id=document_id,
                pending_sha256=verified_sha,
                audit_file=Path(audit_path).name if audit_path is not None else None,
                journal_id=outcome.journal_id,
                attempt=attempt,
                replayed=outcome.replayed,
            )
        finally:
            try:
                try:
                    released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
                except Exception as release_error:
                    _log_critical_safely(
                        f"CRITICAL: apply_manual_fact() lock release RAISED for resource_key={resource_key!r}: "
                        f"{release_error!r}"
                    )
                else:
                    if not released:
                        _log_critical_safely(
                            f"CRITICAL: apply_manual_fact() release_lock_session returned False for "
                            f"resource_key={resource_key!r}"
                        )
            finally:
                _close_quietly(conn, "apply_manual_fact journal connection")
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(f"WARNING: apply_manual_fact authz repository close failed: {close_error!r}")


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat()
