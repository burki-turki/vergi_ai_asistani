# ============================================================
# VERGİ AI - ROW 19C-3c-iii: FACT EXTRACTION GENERATION MUTATION
# FACADE.
#
# `src/fact_extraction_engine.py`'nin (Row 4, LOCKED) document-scoped,
# agent-gated (deterministik modu OLMAYAN) pending-generation writer'ını
# mutation coordinator/journal altyapısına bağlayan, AYRI ve BAĞIMSIZ
# facade - ne `generation_mutation_facade.py` (deadline/timeline, Row
# 19C-3c-i, deterministik, LOCKED) ne `agent_generation_mutation_
# facade.py` (issue_spotting/evidence/argument/risk_strategy/drafting,
# Row 19C-3c-ii, case-scoped, LOCKED) GENİŞLETİLMEZ (repo emsali: her
# yeni kontrat şekli kendi facade+adapters çiftini alır). Bu facade
# önceki iki facade'in genel mimarisini (outer/inner authz, composite
# pre-state snapshot, kilit-altı fresh re-derivation, writer-root
# kontratı, frozen candidate/identity disiplini) TAKİP EDER, ama İKİ
# önemli yönden ONLARDAN AYRILIR:
#
#   1. DOCUMENT-SCOPED TARGET_REF (case-scoped DEĞİL): `target_ref =
#      f"fact.{document_id}.pending"` - `promotion_mutation_facade.py`
#      (Row 19C-3b Slice 2)'nin ZATEN kullandığı `fact.{document_id}.*`
#      namespace'inin doğal generation-tarafı uzantısı
#      (`promotion_mutation_facade.py:778`, `target_ref = f"fact.
#      {document_id}.canonical"`). `resource_key` YİNE case-scoped'tur
#      (`case:<case_id>`, Row 19A "case başına tek kilit" kararı) - aynı
#      case'teki farklı belgeler için generation istekleri AYNI case
#      kilidini paylaşır (serileşir), ama her belgenin KENDİ, bağımsız
#      target_ref/idempotency kimliği vardır.
#   2. READ-ONLY, UNLOCKED BUILD-SKIP PRECHECK (spec §D "BINDING REPLAY
#      CONSISTENCY CORRECTION"): `fact_extraction_engine.py`'nin
#      `extraction_id`/her `fact_id`/`run_at` alanları `run_stamp =
#      datetime.now()...` İÇERİR - yani LLM'İ İKİNCİ KEZ ÇAĞIRMADAN AYNI
#      `analysis` dict'i yeniden üretmek İMKÂNSIZDIR (deadline/timeline'ın
#      SAF deterministik yeniden-hesaplanabilirliğinin AKSİNE, ve
#      precedent'in kendisinin de HİÇ ÇÖZMEDİĞİ bir problem - Row
#      19C-3c-ii `apply_generation()`'ı build'i HER ZAMAN koşulsuz
#      çalıştırır, yalnız WRITER'ı tekrar çağırmaz). Bu facade, kilit
#      ALINMADAN ÖNCE, salt-okunur bir `_precheck_build_skip()`
#      optimizasyonuyla, aynı `idempotency_key` için HERHANGİ bir journal
#      satırı (state'İNDEN BAĞIMSIZ) zaten VARSA build'i atlar - ama bu
#      YALNIZ bir optimizasyondur, hiçbir zaman bir SONUÇ üretmez/
#      döndürmez: otoriter karar HER ZAMAN, İSTİSNASIZ,
#      `mutation_coordinator.run_mutation()`'ın KENDİ, DEĞİŞTİRİLMEMİŞ,
#      kilit-altı idempotency-lookup'una bırakılır (CLAUDE.md Row 19A
#      kararı: "Kilit öncesi bir journal-gate ön-kontrolü yalnız
#      hızlı-red optimizasyonu olarak izinlidir"). Build atlandığında
#      `writer_callback` bir fail-closed SENTINEL'e bağlanır - sessiz
#      rebuild veya eksik candidate yazımı ASLA yapılmaz.
#
# ACTION FAMILY: `generation.fact_extraction` (TEK). Kanal ayrımı YOK -
# CLI-only (`python -m ui.cli_mutate generation --row-key
# fact_extraction --document <DOC_ID> ...`, MEVCUT/LOCKED `generation`
# namespace'inin additive genişlemesi - `generation_mutation_facade.py`/
# `agent_generation_mutation_facade.py`'nin KENDİ row-key evrenleri
# GENİŞLETİLMEZ); web mutasyon yüzeyi YOKTUR (bilinçli kapsam dışı).
#
# DÖRT SABİT LOGICAL-INPUT MANİFESTİ (§_build_manifest_containers):
# `case` (tekil, zorunlu), `target_document` (tekil, zorunlu,
# document_id-parametreli), `target_document_text` (tekil, zorunlu,
# document_id-türetilmiş deterministik konvansiyon - şema-ZORLANMIŞ
# DEĞİLDİR), `case_documents` (değişken kardinaliteli, case'teki TÜM
# `documents/*/document.json`, target_document'i KASITLI olarak TEKRAR
# içerir - defensive completeness, precedent'in "documents" kind'iyle
# AYNI ilke). `document_id`, önceki BEŞ ailenin HİÇBİRİNDE OLMAYAN,
# RUNTIME bir manifest boyutudur.
#
# IDENTITY: `identity_payload` YEDİ alan taşır - `manifest_version`,
# `document_id` (BİLİNÇLİ SAPMA: `target_ref` zaten document_id'yi
# dolaylı taşıdığı için precedent'in minimalist ilkesinden bir SAPMADIR,
# audit-okunabilirlik gerekçesiyle AÇIKÇA işaretlenmiştir), `manifest`,
# `generation_mode` (HER ZAMAN "agent" - bu ailede deterministik mod
# YOKTUR), `model_id`, `engine_version` (YENİ - `FACT_EXTRACTION_ENGINE_
# VERSION`, `PROMPT_VERSION`'dan BAĞIMSIZ üçüncü bir sürüm boyutu),
# `prompt_agent_version`. `secondary_input_hash = None` (bu ailede
# deadline'ın holiday/calendar gibi ayrık bir "generation parametresi"
# YOKTUR).
#
# `--model` YOKTUR (coordinated CLI'da hiçbir zaman olmadı, bu facade'in
# icadı DEĞİL) - production model kimliği HER ZAMAN call-time okunan
# `fact_extraction_engine.DEFAULT_MODEL` sabitidir.
#
# LLM_CLIENT TEST SEAM (production'da hiçbir zaman erişilemez):
# `preview_generation()` VE `apply_generation()` additive, keyword-only
# `llm_client=None` kabul eder - CLI flag DEĞİLDİR, yalnız dependency-
# injection/test seam'idir. `ui/cli_mutate.py`'nin `_run_generation()`
# dispatch'i bu parametreyi HİÇBİR ZAMAN GEÇMEZ.
#
# DUAL NETWORK GATE (bu ailede beş aileden DAHA SIKI): preview
# `with_agent=True` ZORUNLUDUR (bu ailede `with_agent=False` YOKTUR);
# apply `with_agent` VE `allow_network` İKİSİ DE ZORUNLUDUR - deadline/
# timeline'ın (`with_agent`/`allow_network` HİÇ kabul etmediği) VE
# BEŞ agent-generation ailesinin (`allow_network` yalnız `with_agent`
# ile birlikteyken anlamlı, ama apply için `with_agent` OPSİYONEL -
# deterministik mod var) AKSİNE.
#
# WRITER-ROOT KONTRATI: writer containment kökü ÇAĞRI ANINDA writer
# modülünün KENDİ `CASES_DIR` attribute'undan okunur, asla cache'lenmez.
#
# POST-STATE: generation'ın pending çıktısı DETERMİNİSTİK DEĞİLDİR
# (`extraction_id`/her `fact_id`/`run_at` bir `run_stamp` İÇERİR) -
# yazarın KENDİ raporladığı `pending_sha256` TEK doğruluk kaynağıdır.
#
# AUDIT/REPLAY: writer KENDİ `*.generation_audit.json` kaydını
# (document-scoped `documents/<document_id>/extractions/
# generation_reviews/` dizini, `O_CREAT|O_EXCL` + zaman damgalı taban
# ad) KENDİ atomic-write+rollback sınırı İÇİNDE üretir.
# `channel = "local_lawyer_fact_extraction_cli"` - `"local_lawyer_
# generation_cli"`/diğer LOCKED facade dosyalarının channel sentinel'i
# YENİDEN KULLANILMAZ (cross-family channel-tamper tespiti için her
# facade'in KENDİ ayrı channel'ı olmalıdır).
#
# OS-LEVEL LINK-SWAP / TOCTOU: bu facade'in verified-path handoff'u
# doğrulama ile writer'ın GERÇEK `open()`/`os.replace()` syscall'ı
# arasındaki dar pencereyi ATOMİK OLARAK KAPATTIĞINI İDDİA ETMEZ -
# Row 19A'nın T15 kararı uyarınca bu, Row 19D (OS ACL / service
# identity) borcu olarak AÇIKÇA KALIR.
# ============================================================

from __future__ import annotations

import hashlib
import json
import logging
import os
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
    sha256_file,
)

# ----------------------------------------------------------------
# Kapalı row_key -> writer modülü eşlemesi - beş/iki aileninkinden
# BİLİNÇLİ AYRI (repo emsali: her kontrat şekli kendi kapalı eşlemesini
# taşır). Bu ailede tek bir row_key vardır ("fact_extraction") - yalnız
# `ui/cli_mutate.py`'nin `--row-key` choices birleşimi ve reconciliation
# adapter registration'ı için taşınır; `preview_generation()`/
# `apply_generation()`'ın KENDİSİ bir row_key parametresi ALMAZ (tek
# aile, gereksiz tekrar).
# ----------------------------------------------------------------

FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME = {
    "fact_extraction": "fact_extraction_engine",
}

_ACTION_FAMILY = "generation.fact_extraction"

_CASE_RESOURCE_KEY_PREFIX = "case:"

TARGET_STATE = "generated"

CHANNEL = "local_lawyer_fact_extraction_cli"

_MANIFEST_VERSION = "row19c3ciii.fact_extraction.manifest.v1"

_logger = logging.getLogger("vergi_ai.fact_extraction_mutation_facade")


def _log_critical_safely(message: str) -> None:
    try:
        _logger.critical(message)
    except Exception:
        pass


def fact_extraction_action_family_for(row_key: str) -> str:
    """`generation.fact_extraction` - HER ZAMAN aynı, tek değerli
    sabit; `row_key` yalnız `agent_generation_action_family_for(row_key)`
    ile AYNI çağrı şekli için taşınır (reconciliation adapter'ın
    `register_into()`'u bu fonksiyonu çağırır - iki taraf farklı
    string'lere kayamaz)."""
    if row_key not in FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME:
        raise KeyError(f"row_key={row_key!r} is not a known fact-extraction family")
    return _ACTION_FAMILY


def fact_extraction_target_ref_for(document_id: str) -> str:
    return f"fact.{document_id}.pending"


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ----------------------------------------------------------------
# Hata sınıfları - HEPSİ `ApprovalUiError` alt sınıfı (ui.cli_mutate'in
# mevcut, DEĞİŞTİRİLMEMİŞ domain-error tanıma mekanizması bunları
# otomatik tanır) - TEK istisna: `FactExtractionBuildSkippedInvariantError`
# (bkz. o sınıfın kendi docstring'i - bilinçli olarak taban `Exception`,
# ApprovalUiError DEĞİL, çünkü bu bir domain-red DEĞİL, gerçek bir
# programlama-invariant ihlalidir - genuine unexpected failure olarak
# ele alınmalı, sahte-temiz bir "ERROR: ..." satırının ARKASINA
# GİZLENMEMELİDİR).
# ----------------------------------------------------------------


class FactExtractionArgumentError(ApprovalUiError):
    """Kullanım-şekli/argüman sözleşmesi ihlali - HERHANGİ bir DB/
    filesystem I/O'sundan ÖNCE fırlatılır."""


class FactExtractionInputContainmentError(ApprovalUiError):
    """Writer-root/nested/girdi-taraması containment doğrulaması
    başarısız (kaçan/kırık/döngüsel link, kök doğrulanamadı, in-tree
    alias, geçersiz segment adı, gerekli girdi eksik)."""


class FactExtractionResolvedCaseIdMismatchError(ApprovalUiError):
    """İç (kilit-altı) authz'ın çözdüğü case_id, dış (pre-lock)
    authz'ınkinden farklı."""


class FactExtractionAuditBindingVerificationFailedError(ApprovalUiError):
    """Safe-replay corroboration başarısız - insan reconciliation'ı
    gerekir."""

    def __init__(self, *, journal_id: int, idempotency_key: str, reason: str):
        self.journal_id = journal_id
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(
            f"journal_id={journal_id}: fact extraction safe-replay audit-binding "
            f"verification failed (idempotency_key={idempotency_key!r}): {reason}"
        )


class FactExtractionBuildSkippedInvariantError(Exception):
    """ROW 19C-3c-iii §D: `_precheck_build_skip()` bu idempotency_key
    için build'in gereksiz olduğunu (zaten bir journal satırı VAR)
    öngördü, ama `mutation_coordinator.run_mutation()`'ın OTORİTER,
    kilit-altı kendi idempotency lookup'u BEKLENMEDİK biçimde bu
    writer_callback'e ULAŞTI - yani pre-check'in optimistik varsayımı
    YANLIŞ çıktı (yapısal olarak ulaşılamaz olması beklenen bir durum -
    idempotency_key tablonun TÜM geçmişi boyunca UNIQUE'tir, bir satır
    asla silinmez). Bu koşulda frozen bir candidate YOKTUR - burada
    fırlatmak TEK güvenli seçenektir; sessiz rebuild veya eksik
    candidate yazımı ASLA yapılmaz. Bilinçli olarak `ApprovalUiError`
    DEĞİLDİR - bu bir domain-red değil, gerçek bir programlama-invariant
    ihlalidir, `ui.cli_mutate`'in bilinen-hata sınıflandırmasından
    KAÇAR ve tam traceback'iyle propagate eder."""


# ----------------------------------------------------------------
# WRITER-ROOT / NESTED CONTAINMENT - bu modülün KENDİ bağımsız kopyası
# (adapters kendi kopyasını taşır, iki taraf birbirinden import ETMEZ;
# yalnız karar içermeyen `src/path_containment.py` paylaşılır).
# ----------------------------------------------------------------


def _resolve_module_case_root_real(module, case_id: str) -> Path:
    cases_dir = module.CASES_DIR
    try:
        _path_containment.validate_segment(case_id)
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise FactExtractionInputContainmentError(
            "Fact extraction case kökü containment doğrulamasından geçemedi."
        ) from error


def _verify_nested(module, case_root_real: Path, case_id: str, raw_path) -> Path:
    cases_dir = module.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise FactExtractionInputContainmentError(
            "Fact extraction yolu beklenen case kapsamı dışında."
        ) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise FactExtractionInputContainmentError(
            "Fact extraction yolu containment doğrulamasından geçemedi."
        ) from error


# ----------------------------------------------------------------
# CONTAINMENT-BEFORE-TRAVERSAL MANIFEST SCANNER - `agent_generation_
# mutation_facade.py`'nin (LOCKED) AYNI, kaynaktan doğrulanmış
# disiplini: önce yalnız `entry.name` üzerinden saf string
# classification/segment validation, ancak SONRA containment + exact-
# parent doğrulaması, ancak ONDAN SONRA is_dir/is_file/stat/open/read.
# HİÇBİR raw `Path.glob()`, raw `is_dir()`, raw `is_file()`, raw
# `exists()` veya raw `stat()` KULLANILMAZ.
# ----------------------------------------------------------------


def _scan_verified_leaf_chain(case_root_real: Path, documents_dir_real: Path, leaf_segments):
    """`documents/<name>/<leaf_segments...>` zincirini segment-segment
    tarar. Dönüş: `[(logical_relative_path, resolved_path), ...]`,
    `logical_relative_path` ile sıralı. Duplicate resolved path TÜM
    taramayı fail-closed durdurur."""
    try:
        raw_entries = sorted(documents_dir_real.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise FactExtractionInputContainmentError(
            "documents/ dizini listelenemedi."
        ) from error

    results = []

    for entry in raw_entries:
        name = entry.name

        try:
            _path_containment.validate_segment(name)
        except _path_containment.PathContainmentError as error:
            raise FactExtractionInputContainmentError(
                f"documents/ altında geçersiz segment adı: {name!r}"
            ) from error

        try:
            entry_real = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise FactExtractionInputContainmentError(
                f"documents/{name} containment doğrulamasından geçemedi "
                "(kaçan/kırık/döngüsel giriş)."
            ) from error

        if entry_real.parent != documents_dir_real:
            raise FactExtractionInputContainmentError(
                f"documents/{name} beklenen dizinin doğrudan çocuğu değil (in-tree alias)."
            )

        if not entry_real.is_dir():
            continue

        current_real = entry_real
        logical_parts = ["documents", name]
        found = True

        for index, seg in enumerate(leaf_segments):
            raw_candidate = current_real / seg
            if not os.path.lexists(raw_candidate):
                found = False
                break
            try:
                seg_real = _path_containment.resolve_existing(raw_candidate, root=case_root_real)
            except _path_containment.PathContainmentError as error:
                raise FactExtractionInputContainmentError(
                    f"documents/{name}/{'/'.join(leaf_segments[:index+1])} containment "
                    "doğrulamasından geçemedi (kaçan/kırık/döngüsel giriş)."
                ) from error
            if seg_real.parent != current_real:
                raise FactExtractionInputContainmentError(
                    f"documents/{name}/{'/'.join(leaf_segments[:index+1])} beklenen dizinin "
                    "doğrudan çocuğu değil (in-tree alias)."
                )
            is_last = index == len(leaf_segments) - 1
            if is_last:
                if not seg_real.is_file():
                    raise FactExtractionInputContainmentError(
                        f"documents/{name}/{'/'.join(leaf_segments)} güvenli-fakat-normal-dosya "
                        "değil."
                    )
            else:
                if not seg_real.is_dir():
                    found = False
                    break
            current_real = seg_real
            logical_parts.append(seg)

        if found:
            results.append(("/".join(logical_parts), current_real))

    resolved_paths = [path for _name, path in results]
    if len(set(resolved_paths)) != len(resolved_paths):
        raise FactExtractionInputContainmentError(
            "documents/ taramasında duplicate/alias çözümlenmiş yol tespit edildi."
        )

    return sorted(results, key=lambda pair: pair[0])


def _scan_single_file(case_root_real: Path, segments, logical_name: str, *, required: bool):
    """Sabit, önceden bilinen bir segment dizisini SEGMENT-SEGMENT
    tarar - `lexists()` HER segment adımında kontrol edilir, böylece
    ARA bir segment kırık/döngüsel/kaçan bir alias olduğunda bu asla
    "missing"e yanlış sınıflandırılmaz."""
    current_real = case_root_real

    for index, seg in enumerate(segments):
        try:
            _path_containment.validate_segment(seg)
        except _path_containment.PathContainmentError as error:
            raise FactExtractionInputContainmentError(
                f"{logical_name}: geçersiz segment adı {seg!r}"
            ) from error

        raw_candidate = current_real / seg

        if not os.path.lexists(raw_candidate):
            if required:
                raise FactExtractionInputContainmentError(
                    f"required input missing: {logical_name}"
                )
            return {"logical_name": logical_name, "state": "missing", "files": []}

        try:
            seg_real = _path_containment.resolve_existing(raw_candidate, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise FactExtractionInputContainmentError(
                f"{logical_name}: containment doğrulamasından geçemedi (kaçan/kırık/döngüsel "
                "giriş)."
            ) from error

        if seg_real.parent != current_real:
            raise FactExtractionInputContainmentError(
                f"{logical_name}: beklenen dizinin doğrudan çocuğu değil (in-tree alias)."
            )

        is_last = index == len(segments) - 1

        if is_last:
            if not seg_real.is_file():
                raise FactExtractionInputContainmentError(
                    f"{logical_name}: güvenli-fakat-normal-dosya değil."
                )
        else:
            if not seg_real.is_dir():
                if required:
                    raise FactExtractionInputContainmentError(
                        f"required input missing (intermediate not a directory): {logical_name}"
                    )
                return {"logical_name": logical_name, "state": "missing", "files": []}

        current_real = seg_real

    sha256 = hashlib.sha256(current_real.read_bytes()).hexdigest()
    logical_relative_path = "/".join(segments)

    return {
        "logical_name": logical_name,
        "state": "present",
        "files": [{"logical_relative_path": logical_relative_path, "sha256": sha256}],
    }


# ----------------------------------------------------------------
# DÖRT SABİT LOGICAL-INPUT MANİFESTİ.
# ----------------------------------------------------------------


def _build_manifest_containers(case_root_real: Path, document_id: str):
    containers = []

    containers.append(
        _scan_single_file(case_root_real, ("case.json",), "case", required=True)
    )
    containers.append(
        _scan_single_file(
            case_root_real, ("documents", document_id, "document.json"),
            "target_document", required=True,
        )
    )
    containers.append(
        _scan_single_file(
            case_root_real,
            ("documents", document_id, "extracted", f"{document_id}.txt"),
            "target_document_text", required=True,
        )
    )

    try:
        documents_dir_real = _path_containment.resolve_existing(
            case_root_real / "documents", root=case_root_real,
        )
    except _path_containment.PathContainmentError as error:
        raise FactExtractionInputContainmentError(
            "documents/ containment doğrulamasından geçemedi (veya bulunamadı)."
        ) from error

    entries = _scan_verified_leaf_chain(case_root_real, documents_dir_real, ("document.json",))
    containers.append({
        "logical_name": "case_documents",
        "state": "present" if entries else "empty",
        "files": [
            {"logical_relative_path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for rel, path in entries
        ],
    })

    containers.sort(key=lambda c: c["logical_name"])

    return containers


# ----------------------------------------------------------------
# IDENTITY PAYLOAD - canonical serialization + freeze/reconstruct.
# ----------------------------------------------------------------


def _resolve_generation_provenance(module, llm_client):
    """(generation_mode, model_id, engine_version, prompt_agent_version).
    `generation_mode` bu ailede HER ZAMAN "agent"tir (deterministik mod
    YOKTUR). `llm_client` yalnız test seam'idir - production caller'ı
    (ui.cli_mutate) bu parametreyi HİÇBİR ZAMAN geçirmez."""
    engine_version = module.FACT_EXTRACTION_ENGINE_VERSION
    prompt_agent_version = module.PROMPT_VERSION

    if llm_client is not None:
        return "agent", "external_injected_client", engine_version, prompt_agent_version

    return "agent", module.DEFAULT_MODEL, engine_version, prompt_agent_version


def _build_identity_payload(document_id, manifest, generation_mode, model_id, engine_version, prompt_agent_version):
    return {
        "manifest_version": _MANIFEST_VERSION,
        "document_id": document_id,
        "manifest": manifest,
        "generation_mode": generation_mode,
        "model_id": model_id,
        "engine_version": engine_version,
        "prompt_agent_version": prompt_agent_version,
    }


def _canonical_identity_bytes(identity_payload) -> bytes:
    return json.dumps(
        identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _compute_input_digest(identity_bytes: bytes) -> str:
    return hashlib.sha256(identity_bytes).hexdigest()


# ----------------------------------------------------------------
# OUTPUT-SIDE VERIFIED PATH HANDOFF.
# ----------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedFactExtractionOutputPaths:
    document_extractions_dir: Path
    pending_path: Path
    history_dir: Path
    reviews_dir: Path

    @property
    def identity(self):
        return (
            str(self.document_extractions_dir), str(self.pending_path),
            str(self.history_dir), str(self.reviews_dir),
        )


def _derive_verified_output_paths(module, case_root_real: Path, case_id: str, document_id: str):
    raw_pending_path = module.get_pending_path(case_id, document_id)
    document_extractions_dir = _verify_nested(module, case_root_real, case_id, raw_pending_path.parent)
    pending_path = _verify_nested(module, case_root_real, case_id, raw_pending_path)
    history_dir = _verify_nested(
        module, case_root_real, case_id, module.get_history_dir(case_id, document_id),
    )
    reviews_dir = _verify_nested(
        module, case_root_real, case_id, module.get_reviews_dir(case_id, document_id),
    )
    return VerifiedFactExtractionOutputPaths(
        document_extractions_dir=document_extractions_dir, pending_path=pending_path,
        history_dir=history_dir, reviews_dir=reviews_dir,
    )


# ----------------------------------------------------------------
# COMPOSITE PRE-STATE SNAPSHOT (pending-conflict kontrolü) -
# `_MANIFEST_VERSION`'dan BİLİNÇLİ OLARAK AYRIŞTIRILMIŞ bir literal
# (precedent'in `_SNAPSHOT_VERSION`/`_MANIFEST_VERSION`'ı AYNI string
# taşıdığı kafa karıştırıcı emsali TEKRARLANMAZ).
# ----------------------------------------------------------------

_SNAPSHOT_VERSION = "row19c3ciii.fact_extraction.snapshot.v1"

SNAPSHOT_ABSENT = "__absent__"

SNAPSHOT_PRESENT = "__present__"


@dataclass(frozen=True)
class _PendingSnapshot:
    input_digest: str
    pending_presence: str
    pending_sha256: str
    composite_digest: str


def _compute_pending_snapshot(input_digest: str, pending_path: Path) -> _PendingSnapshot:
    pending_sha = sha256_file(pending_path)
    pending_presence = SNAPSHOT_PRESENT if pending_sha is not None else SNAPSHOT_ABSENT
    pending_sha256 = pending_sha if pending_sha is not None else SNAPSHOT_ABSENT
    payload = json.dumps(
        {
            "snapshot_version": _SNAPSHOT_VERSION,
            "input_digest": input_digest,
            "pending_presence": pending_presence,
            "pending_sha256": pending_sha256,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    composite_digest = hashlib.sha256(payload).hexdigest()
    return _PendingSnapshot(
        input_digest=input_digest, pending_presence=pending_presence,
        pending_sha256=pending_sha256, composite_digest=composite_digest,
    )


# ----------------------------------------------------------------
# PENDING-FILE FROZEN-BYTE RECIPE - diğer beş ailenin
# `_freeze_pending_bytes()`'i ile BYTE-FOR-BYTE aynı: `json.dumps(...,
# ensure_ascii=False, indent=2)` + tek bir trailing `"\n"`. Bu, `write_
# pending()`'in KENDİ `atomic_write_json()`'ının (`newline="\n"` +
# `file.write("\n")`) yazacağı TAM baytlarla eşleşir.
# ----------------------------------------------------------------


def _freeze_pending_bytes(extraction: dict) -> bytes:
    return json.dumps(extraction, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


# ----------------------------------------------------------------
# READ-ONLY, UNLOCKED BUILD-SKIP PRECHECK (spec §D).
#
# YALNIZ bir optimizasyondur - HİÇBİR SONUÇ üretmez/döndürmez, case
# lock'ı veya run_mutation()'ı ASLA atlamaz, journal'a YAZMAZ, dosya
# YAZMAZ, model ÇAĞIRMAZ. Otoriter karar HER ZAMAN `mutation_
# coordinator.run_mutation()`'ın KENDİ, DEĞİŞTİRİLMEMİŞ kilit-altı
# idempotency-lookup'una bırakılır (`_idempotency_lookup()`,
# `mutation_coordinator.py:321-339` - bu fonksiyon o sorgunun BAĞIMSIZ,
# salt-okunur bir kopyasını taşır, o modülü İMPORT ETMEZ).
#
# Spec §D'nin kesin tablosu: current idempotency_key için HERHANGİ bir
# journal satırı VARSA (state'İNDEN BAĞIMSIZ - completed/failed/
# prepared/executing/reconciliation_required, fingerprint eşleşse de
# eşleşmese de) -> build_needed=False. Satır YOKSA -> build_needed=True.
# DB hatası/malformed/belirsizlik -> build_needed=True (fail-safe: bir
# YANLIŞLIKLA build'in ATLANMASI güvenlik açığı DEĞİLDİR - run_
# mutation() kendi otoriter kontrolüyle YİNE doğru sonucu üretir - ama
# bir YANLIŞLIKLA build'in ÇALIŞTIRILMASI da hiçbir şeyi bozmaz, sadece
# boşa gider; bu yüzden belirsizlikte HER ZAMAN build'e düşülür).
# ----------------------------------------------------------------


def _precheck_build_skip(conn_factory, idempotency_key: str) -> bool:
    try:
        conn = conn_factory()
    except Exception:
        return True

    try:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM mutation.mutation_journal WHERE idempotency_key = %s",
                    (idempotency_key,),
                )
                row = cur.fetchone()
        except Exception:
            return True
        return row is None
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ----------------------------------------------------------------
# AUTHZ REPO / JOURNAL CONN KURULUMU - diğer facade'lerin kendi
# desenlerinin bağımsız kopyaları.
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
# ARGÜMAN ŞEKİL KURALLARI - her I/O'dan önce.
# ----------------------------------------------------------------


def _check_argument_shapes(
    document_id, expected_input_digest=None, *, for_apply: bool, with_agent: bool, allow_network: bool = False,
):
    if not _nonblank(document_id):
        raise FactExtractionArgumentError(
            "document_id boş olamaz."
        )

    if not with_agent:
        raise FactExtractionArgumentError(
            "fact_extraction ailesi için with_agent HER ZAMAN True olmalıdır (preview dahil) - "
            "bu ailede deterministik mod yoktur."
        )

    if for_apply:
        if not _nonblank(expected_input_digest):
            raise FactExtractionArgumentError(
                "expected_input_digest apply için zorunlu, boş olamaz."
            )
        if not allow_network:
            raise FactExtractionArgumentError(
                "fact_extraction apply için allow_network HER ZAMAN True olmalıdır (with_agent ile "
                "BİRLİKTE) - bu ailede deterministik mod yoktur."
            )


# ----------------------------------------------------------------
# PREVIEW (salt-okunur, model ASLA çağrılmaz)
# ----------------------------------------------------------------


def preview_generation(
    case_id: str,
    document_id: str,
    *,
    with_agent: bool = False,
    llm_client=None,
    principal,
    authz_repository=None,
):
    """Salt-okunur preview. SIRA: dış 'read' authz HER filesystem
    probundan ÖNCE koşar. `llm_client` yalnız identity/provenance
    seçimini belirlemek için KULLANILIR - hiçbir metodu ÇAĞRILMAZ.
    `with_agent=False` (varsayılan) KOŞULSUZ reddedilir - bu ailede
    yalnız `with_agent=True` geçerlidir."""
    import importlib

    _check_argument_shapes(document_id, for_apply=False, with_agent=with_agent)

    module = importlib.import_module(FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME["fact_extraction"])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "read", repository=repository,
        )

        case_root_real = _resolve_module_case_root_real(module, resolved_case_id)
        paths = _derive_verified_output_paths(module, case_root_real, resolved_case_id, document_id)

        manifest = _build_manifest_containers(case_root_real, document_id)
        generation_mode, model_id, engine_version, prompt_agent_version = _resolve_generation_provenance(
            module, llm_client,
        )
        identity_payload = _build_identity_payload(
            document_id, manifest, generation_mode, model_id, engine_version, prompt_agent_version,
        )
        identity_bytes = _canonical_identity_bytes(identity_payload)
        input_digest = _compute_input_digest(identity_bytes)

        return {
            "case_id": resolved_case_id,
            "document_id": document_id,
            "target_ref": fact_extraction_target_ref_for(document_id),
            "input_digest": input_digest,
            "generation_mode": generation_mode,
            "model_id": model_id,
            "engine_version": engine_version,
            "prompt_agent_version": prompt_agent_version,
            "pending_exists": paths.pending_path.is_file(),
            "pending_sha256": sha256_file(paths.pending_path),
        }
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(
                f"WARNING: preview_generation authz repository close failed: {close_error!r}"
            )


# ----------------------------------------------------------------
# APPLY (koordine, journal'lı, idempotent mutasyon)
# ----------------------------------------------------------------


@dataclass(frozen=True)
class FactExtractionApplyResult:
    case_id: str
    document_id: str
    pending_path: Path
    pending_sha256: str | None
    audit_path: Path | None
    stdout: str
    journal_id: int
    replayed: bool


def _audit_record_matches_base(
    record: dict, *, idempotency_key: str, resource_key: str, action_family: str,
    document_id: str, pending_sha256: str,
) -> bool:
    if not _nonblank(record.get("mutation_idempotency_key")) or record.get("mutation_idempotency_key") != idempotency_key:
        return False
    if not _nonblank(record.get("mutation_resource_key")) or record.get("mutation_resource_key") != resource_key:
        return False
    if record.get("action_family") != action_family:
        return False
    if record.get("document_id") != document_id:
        return False
    if not _nonblank(record.get("pending_sha256")) or record.get("pending_sha256") != pending_sha256:
        return False
    if record.get("outcome") != "generated":
        return False
    return True


def _scan_generation_audits(case_root_real: Path, reviews_dir_verified: Path):
    """`*.generation_audit.json` girişlerinin containment-before-stat
    taraması - kaçan/kırık/alias giriş TÜM taramayı fail-closed
    durdurur; parse edilemeyen giriş `(path, None)` döner."""
    import fnmatch

    if not reviews_dir_verified.is_dir():
        return []
    try:
        raw_entries = sorted(reviews_dir_verified.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise FactExtractionInputContainmentError(
            "Fact extraction reviews dizini listelenemedi."
        ) from error
    results = []
    for entry in raw_entries:
        if not fnmatch.fnmatch(entry.name, "*.generation_audit.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise FactExtractionInputContainmentError(
                f"generation_reviews/{entry.name} containment doğrulamasından geçemedi."
            ) from error
        if resolved.parent != reviews_dir_verified:
            raise FactExtractionInputContainmentError(
                f"generation_reviews/{entry.name}: in-tree alias."
            )
        try:
            with open(resolved, "r", encoding="utf-8") as file:
                record = json.load(file)
            if not isinstance(record, dict):
                record = None
        except Exception:
            record = None
        results.append((resolved, record))
    return results


def _verify_completed_replay_binding(
    paths: VerifiedFactExtractionOutputPaths, case_root_real: Path, *,
    document_id: str, action_family: str, journal_state: str, journal_id: int,
    idempotency_key: str, resource_key: str, observed_post_hash,
):
    """Completed safe-replay corroboration - yalnız `completed`
    durumdaki bir satırı YENİDEN DOĞRULAR (sonuç zaten BİLİNİYOR)."""

    def fail(reason):
        raise FactExtractionAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key, reason=reason,
        )

    if journal_state != "completed":
        fail(f"journal_state={journal_state!r} beklenen 'completed' değil")

    current_pending_sha256 = sha256_file(paths.pending_path)
    if current_pending_sha256 is None:
        fail(f"pending artefakt şu an mevcut değil: {paths.pending_path}")
    if not _nonblank(observed_post_hash):
        fail(f"journal satırı boş/eksik observed_post_hash taşıyor ({observed_post_hash!r})")
    if observed_post_hash != current_pending_sha256:
        fail(
            f"journal observed_post_hash={observed_post_hash!r} ile diskteki pending "
            f"({current_pending_sha256!r}) eşleşmiyor"
        )
    if not resource_key.startswith(_CASE_RESOURCE_KEY_PREFIX) or not resource_key[len(_CASE_RESOURCE_KEY_PREFIX):]:
        fail(f"resource_key={resource_key!r} geçerli bir case:<case_id> anahtarı değil")

    entries = _scan_generation_audits(case_root_real, paths.reviews_dir)
    unparseable = [path for path, record in entries if record is None]
    if unparseable:
        fail(
            f"reviews dizininde parse edilemeyen {len(unparseable)} adet *.generation_audit.json "
            "var - içerik-bağlama güvenle yapılamaz"
        )
    matches = [
        (path, record) for path, record in entries
        if _audit_record_matches_base(
            record, idempotency_key=idempotency_key, resource_key=resource_key,
            action_family=action_family, document_id=document_id, pending_sha256=current_pending_sha256,
        )
    ]
    if len(matches) != 1:
        fail(
            f"tam-bağlama eşleşen success audit sayısı {len(matches)} (tam 1 olmalı) - "
            "bu completed satır bağımsızca doğrulanamadı"
        )
    return current_pending_sha256, matches[0][0]


def apply_generation(
    case_id: str,
    document_id: str,
    expected_input_digest: str,
    *,
    with_agent: bool = False,
    allow_network: bool = False,
    llm_client=None,
    principal,
    authz_repository=None,
    conn_factory=None,
) -> FactExtractionApplyResult:
    """SIRA (spec §G/§I): (1) argüman şekilleri (saf, I/O'suz); (2) DIŞ
    authorize_case_access('mutate'); (3) pre-lock manifest/identity +
    composite pending snapshot + expected_input_digest karşılaştırması;
    (4) MutationIntent/idempotency_key/request_fingerprint; (5) SALT-
    OKUNUR, KİLİTSİZ build-skip precheck (§D - yalnız bir bayrak, HİÇBİR
    SONUÇ); (6) GEREKLİYSE dış-lock build (deterministik mod YOK, HER
    ZAMAN agent); (7) frozen candidate; (8) conn + case lock; (9)
    run_mutation: İÇ otoriter authz -> journal gate -> idempotency ->
    precondition (SIFIRDAN kilit-altı taze re-derivation; her red sıfır
    journal satırı) -> writer (verified paths + frozen candidate
    ÜZERİNDEN, YA DA build atlandıysa fail-closed sentinel); (10)
    replay'de tam corroboration; (11) maskelemeyen temizlik."""
    import importlib

    _check_argument_shapes(
        document_id, expected_input_digest, for_apply=True, with_agent=with_agent, allow_network=allow_network,
    )

    module = importlib.import_module(FACT_EXTRACTION_ROW_KEY_TO_MODULE_NAME["fact_extraction"])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        outer_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )

        resource_key = _mutation_lock.case_resource_key(outer_resolved_case_id)
        action_family = _ACTION_FAMILY
        target_ref = fact_extraction_target_ref_for(document_id)

        pre_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
        pre_paths = _derive_verified_output_paths(module, pre_case_root, outer_resolved_case_id, document_id)

        pre_manifest = _build_manifest_containers(pre_case_root, document_id)
        generation_mode, model_id, engine_version, prompt_agent_version = _resolve_generation_provenance(
            module, llm_client,
        )
        pre_identity_payload = _build_identity_payload(
            document_id, pre_manifest, generation_mode, model_id, engine_version, prompt_agent_version,
        )
        pre_identity_bytes = _canonical_identity_bytes(pre_identity_payload)
        input_digest = _compute_input_digest(pre_identity_bytes)

        if input_digest != expected_input_digest:
            raise StaleViewError(
                "Preview alındıktan sonra girdi içeriği DEĞİŞTİ "
                f"(beklenen input_digest: {expected_input_digest}, şimdiki: {input_digest}). "
                "İşlem iptal edildi, HİÇBİR değişiklik yapılmadı."
            )

        pre_pending_snapshot = _compute_pending_snapshot(input_digest, pre_paths.pending_path)

        intent = MutationIntent(
            actor_type="iam_user",
            actor_ref=str(principal.user_id),
            resource_key=resource_key,
            action_family=action_family,
            target_ref=target_ref,
            target_state=TARGET_STATE,
            pre_hash=pre_pending_snapshot.composite_digest,
            pre_revision=input_digest,
            secondary_input_hash=None,
        )
        idempotency_key_for_audit = compute_idempotency_key(intent)

        # ---- READ-ONLY, UNLOCKED BUILD-SKIP PRECHECK (spec §D) ----
        # Yalnız bir optimizasyondur - hiçbir sonuç üretmez/döndürmez;
        # otoriter karar HER ZAMAN adım (9)'daki run_mutation()'a
        # bırakılır.
        build_needed = _precheck_build_skip(conn_factory or _default_conn_factory, idempotency_key_for_audit)

        frozen_pending_bytes = None

        if build_needed:
            # DIŞ-LOCK BUILD - hiçbir journal satırı, hiçbir filesystem
            # mutasyonu bu noktada OLUŞMAZ. Bu ailede deterministik mod
            # YOKTUR - `llm_client` verilmişse (test-only) o kullanılır,
            # aksi halde gerçek `call_llm()` production dalı (yalnız
            # `--with-agent --allow-network` ile buraya ulaşılır) tetiklenir.
            text_path = module.get_extracted_text_path(outer_resolved_case_id, document_id)
            build_result = module.build_fact_extraction(
                outer_resolved_case_id, document_id, text_path,
                model=module.DEFAULT_MODEL, llm_client=llm_client,
            )
            extraction = build_result["extraction"]
            frozen_pending_bytes = _freeze_pending_bytes(extraction)

        under_lock_box = {}
        writer_outcome_box = {}

        def authz_callback() -> None:
            inner_resolved_case_id = _authz.authorize_case_access(
                principal, case_id, "mutate", repository=repository,
            )
            if inner_resolved_case_id != outer_resolved_case_id:
                raise FactExtractionResolvedCaseIdMismatchError(
                    f"outer authz {outer_resolved_case_id!r} çözdü, inner authz "
                    f"{inner_resolved_case_id!r} - reddedildi."
                )

        def precondition_callback() -> None:
            ul_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
            ul_paths = _derive_verified_output_paths(
                module, ul_case_root, outer_resolved_case_id, document_id,
            )
            if ul_paths.identity != pre_paths.identity:
                raise PreconditionRaceDetectedError(
                    "Bu generation isteği case kilidini beklerken ilgili dizin/dosyaların "
                    "çözümlenmiş (gerçek) konumu DEĞİŞTİ (link swap veya benzeri). İşlem iptal "
                    "edildi, HİÇBİR değişiklik yapılmadı."
                )

            ul_manifest = _build_manifest_containers(ul_case_root, document_id)
            ul_identity_payload = _build_identity_payload(
                document_id, ul_manifest, generation_mode, model_id, engine_version, prompt_agent_version,
            )
            ul_identity_bytes = _canonical_identity_bytes(ul_identity_payload)

            if ul_identity_bytes != pre_identity_bytes:
                raise StaleViewError(
                    "Preview/pre-lock alındıktan sonra girdi içeriği DEĞİŞTİ. İşlem iptal "
                    "edildi, HİÇBİR değişiklik yapılmadı."
                )

            ul_pending_snapshot = _compute_pending_snapshot(input_digest, ul_paths.pending_path)
            if ul_pending_snapshot.composite_digest != pre_pending_snapshot.composite_digest:
                raise PreconditionRaceDetectedError(
                    "Bu generation isteği case kilidini beklerken pending durumu DEĞİŞTİ. "
                    "İşlem iptal edildi, HİÇBİR değişiklik yapılmadı."
                )

            under_lock_box["paths"] = ul_paths
            under_lock_box["case_root"] = ul_case_root
            # Audit'e geçirilecek identity_payload HER ZAMAN frozen
            # bytes'tan TAZE json.loads() ile üretilir - ul_identity_
            # payload (ilk mutable dict) bir daha KULLANILMAZ.
            under_lock_box["identity_payload_for_audit"] = json.loads(
                ul_identity_bytes.decode("utf-8")
            )

        def writer_callback() -> _mutation_coordinator.WriterResult:
            if not build_needed:
                # spec §D madde 6: build_needed=False iken coordinator
                # beklenmedik biçimde writer'a ulaşırsa sentinel açık
                # invariant exception fırlatır. Sessiz rebuild veya
                # eksik candidate yazımı YAPILMAZ.
                raise FactExtractionBuildSkippedInvariantError(
                    "build_needed=False iken writer_callback'e ulaşıldı - "
                    "_precheck_build_skip()'in optimistik varsayımı run_mutation()'ın "
                    "otoriter, kilit-altı idempotency lookup'u tarafından DOĞRULANMADI. "
                    "Frozen bir candidate yok; sessiz rebuild veya eksik yazım YAPILMAZ."
                )

            import io
            import contextlib

            ul_paths = under_lock_box["paths"]
            identity_payload_for_audit = under_lock_box["identity_payload_for_audit"]

            # Frozen bytes'tan TAZE reconstruction - build sırasında
            # üretilen `extraction` referansı bir daha KULLANILMAZ.
            candidate = json.loads(frozen_pending_bytes.decode("utf-8"))

            stdout_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture):
                write_result = module.write_pending(
                    outer_resolved_case_id, document_id, candidate,
                    verified_paths=ul_paths,
                    input_digest=input_digest,
                    identity_payload=identity_payload_for_audit,
                    mutation_idempotency_key=idempotency_key_for_audit,
                    mutation_resource_key=resource_key,
                    mutation_actor_ref=str(principal.user_id),
                )

            writer_outcome_box["audit_path"] = write_result["audit_path"]
            writer_outcome_box["pending_path"] = write_result["pending_path"]

            return _mutation_coordinator.WriterResult(
                observed_post_hash=write_result["pending_sha256"],
                result=stdout_capture.getvalue(),
            )

        conn = (conn_factory or _default_conn_factory)()
        advisory_lock_id = _mutation_lock.acquire_case_lock_session(conn, outer_resolved_case_id)
        try:
            outcome = _mutation_coordinator.run_mutation(
                conn, intent,
                actor_user_id=principal.user_id,
                authz_callback=authz_callback,
                precondition_callback=precondition_callback,
                writer_callback=writer_callback,
            )

            if outcome.replayed:
                try:
                    replay_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
                    replay_paths = _derive_verified_output_paths(
                        module, replay_case_root, outer_resolved_case_id, document_id,
                    )
                    verified_pending_hash, audit_path = _verify_completed_replay_binding(
                        replay_paths, replay_case_root,
                        document_id=document_id,
                        action_family=action_family,
                        journal_state=outcome.state,
                        journal_id=outcome.journal_id,
                        idempotency_key=idempotency_key_for_audit,
                        resource_key=resource_key,
                        observed_post_hash=outcome.observed_post_hash,
                    )
                except FactExtractionInputContainmentError as error:
                    raise FactExtractionAuditBindingVerificationFailedError(
                        journal_id=outcome.journal_id, idempotency_key=idempotency_key_for_audit,
                        reason=f"replay corroboration sırasında containment hatası: {error}",
                    ) from error
                stdout_text = ""
                pending_path_result = replay_paths.pending_path
            else:
                verified_pending_hash = outcome.observed_post_hash
                stdout_text = outcome.result
                audit_path = writer_outcome_box.get("audit_path")
                pending_path_result = under_lock_box["paths"].pending_path

            return FactExtractionApplyResult(
                case_id=outer_resolved_case_id,
                document_id=document_id,
                pending_path=pending_path_result,
                pending_sha256=verified_pending_hash,
                audit_path=audit_path,
                stdout=stdout_text,
                journal_id=outcome.journal_id,
                replayed=outcome.replayed,
            )
        finally:
            try:
                try:
                    released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
                except Exception as release_error:
                    _log_critical_safely(
                        f"CRITICAL: apply_generation() lock release RAISED for "
                        f"resource_key={resource_key!r} (advisory_lock_id={advisory_lock_id!r}): "
                        f"{release_error!r} - outcome unchanged, investigate out of band"
                    )
                else:
                    if not released:
                        _log_critical_safely(
                            f"CRITICAL: apply_generation() release_lock_session returned False "
                            f"for resource_key={resource_key!r} (advisory_lock_id={advisory_lock_id!r}) "
                            "- outcome unchanged, investigate out of band"
                        )
            finally:
                try:
                    conn.close()
                except Exception as close_error:
                    _log_critical_safely(
                        f"CRITICAL: apply_generation() journal connection close failed: "
                        f"{close_error!r} - outcome unchanged"
                    )
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(
                f"WARNING: apply_generation authz repository close failed: {close_error!r}"
            )
