# ============================================================
# VERGİ AI - ROW 19C-3c-iv SLICE 1: DETERMINISTIC + AGENT LEGAL
# RESEARCH / CASE LAW PENDING-GENERATION MUTATION FACADE
# (retrieval/discovery deferred).
#
# `src/legal_research_engine.py`'nin (Row 10, LOCKED) VE `src/case_law_
# engine.py`'nin (Row 11, LOCKED) case-scoped, hem deterministik hem
# agent-modlu pending-generation writer'larını mutation coordinator/
# journal altyapısına bağlayan, AYRI ve BAĞIMSIZ, TEK birleşik facade -
# önceki YEDİ facade/adapter çiftinden (Layer A, Layer B, drafting_
# request, promotion, deterministic-generation, agent-generation,
# fact-extraction) HİÇBİRİ GENİŞLETİLMEZ. Bu facade `agent_generation_
# mutation_facade.py`'nin (Row 19C-3c-ii, LOCKED) genel mimarisini
# (outer/inner authz, composite pre-state snapshot, kilit-altı fresh
# re-derivation, writer-root kontratı, dual deterministic/agent mode,
# outside-lock build + frozen handoff, VerifiedGenerationOutputPaths
# writer handoff) TAKİP EDER - fact_extraction'ın build-skip precheck
# optimizasyonu bu ailede YOKTUR (agent_generation precedent'iyle
# tutarlı - bu optimizasyon hiçbir zaman zorunlu değildi).
#
# İKİ action family, TEK facade: `generation.legal_research` /
# `generation.case_law` (formül `agent_generation_action_family_for()`
# ile AYNI: `f"generation.{row_key}"`). `target_ref`ler case_id
# TAŞIMAZ (resource_key zaten taşır) - `legal_research.pending` /
# `case_law.pending` (formül AYNI: `f"{row_key}.pending"`).
#
# RETRIEVAL/DISCOVERY BU SLICE'TA KESİN OLARAK DEVRE DIŞI: her
# coordinated build'de `use_discovery=False` (legal_research) SABİT
# geçirilir; `retrieval_fn` HİÇBİR ZAMAN geçirilmez; `retriever.py`/
# `rag.py`/`ingest.py` HİÇ import edilmez (her iki motorun modül-
# seviyesi importlarının temiz olduğu Fable incelemesinde kanıtlanmıştır -
# yalnız discovery/agent modülleri kendi LAZY importlarını taşır).
#
# GLOBAL GİRDİLER (data/documents.json, data/provisions.json) YALNIZ
# OKUNUR ve digest'e bağlanır - bunların mutasyonu AYRI bir maintenance
# fazının konusudur; bu slice'ta case-scoped `case:<case_id>` kilidinden
# BAŞKA hiçbir kilit ALINMAZ.
#
# GLOBAL GİRDİ CONTAINMENT - beş/bir önceki ailenin HİÇBİRİNDE olmayan,
# bu aileye özgü İKİNCİ bir containment kökü: case-scoped girdiler
# `case_root_real` (CASES_DIR altında) altında doğrulanır; global
# `documents.json`/`provisions.json` AYRI bir `data_root_real` (motorun
# kendi `DATA_DIR`, `BASE_DIR` altında doğrulanmış) altında doğrulanır -
# iki kök birbirine KARIŞTIRILMAZ.
#
# ALTI/DÖRT SABİT LOGICAL-INPUT MANİFESTİ (§FAMILY_INPUT_SPECS):
# legal_research = issues (case-scoped, zorunlu) + facts (case-scoped,
# documents/ dizini zorunlu, tekil facts.json'lar opsiyonel) + timeline
# (case-scoped, zorunlu) + deadline (case-scoped, OPSİYONEL - motor
# eksikliğini uyarıyla tolere eder) + global_documents (data-root,
# OPSİYONEL - `load_legal_documents_index()` eksikse `{}` döner) +
# global_provisions (data-root, ZORUNLU - `load_provisions_manifest()`
# eksikse `FileNotFoundError` fırlatır). case_law = issues (zorunlu) +
# timeline (zorunlu) + research (case-scoped, OPSİYONEL - motor
# eksikliğini uyarıyla tolere eder) + global_documents (OPSİYONEL).
# case_law'ın manifestinde `global_provisions` YOKTUR (case_law zinciri
# `provision` kelimesini hiç içermez - builder'ın okumadığı bir girdi
# identity'ye SOKULMAZ).
#
# IDENTITY: `identity_payload` YEDİ alan taşır - `manifest_version`
# (row_key başına AYRI literal: `row19c3civ.legal_research.manifest.v1`
# / `row19c3civ.case_law.manifest.v1`), `case_id` (BİLİNÇLİ, fact_
# extraction'ın `document_id` sapmasıyla AYNI ilke - resource_key zaten
# case_id taşısa da audit-okunabilirlik için tekrar edilir), `manifest`,
# `generation_mode`, `model_id`, `engine_version` (motorun KENDİ
# `LEGAL_RESEARCH_ENGINE_VERSION`/`CASE_LAW_ENGINE_VERSION` sabiti,
# call-time okunur), `prompt_agent_version`. `secondary_input_hash =
# None` (bu ailede gerçek per-run parametre yok).
#
# DUAL MODE (agent_generation ile AYNI network sözleşmesi - fact_
# extraction'ın DAHA SIKI kuralı DEĞİL): `with_agent=False` ->
# deterministik (`model_id="deterministic_no_model"`,
# `prompt_agent_version="n/a"`); `with_agent=True` -> agent
# (`llm_client` verilmişse `model_id="external_injected_client"`, aksi
# halde production `DEFAULT_AGENT_MODEL`). `allow_network` YALNIZ
# `with_agent` İLE BİRLİKTE anlamlıdır (tek başına reddedilir); preview
# HİÇBİR model/network çağrısı yapmaz.
#
# LLM_CLIENT TEST SEAM (production'da hiçbir zaman erişilemez):
# `preview_generation()` VE `apply_generation()` additive, keyword-only
# `llm_client=None` kabul eder - CLI flag DEĞİLDİR. `ui/cli_mutate.py`'nin
# `_run_generation()` dispatch'i bu parametreyi HİÇBİR ZAMAN GEÇMEZ.
#
# WRITER-ROOT KONTRATI: writer containment kökü ÇAĞRI ANINDA writer
# modülünün KENDİ `CASES_DIR`/`DATA_DIR`/`BASE_DIR` attribute'larından
# okunur, asla cache'lenmez.
#
# POST-STATE: generation'ın pending çıktısı DETERMİNİSTİK DEĞİLDİR
# (`research_analysis_id`/`case_law_analysis_id`/`generated_at`) -
# yazarın KENDİ raporladığı `pending_sha256` TEK doğruluk kaynağıdır.
#
# AUDIT/REPLAY: her iki writer KENDİ `*.generation_audit.json` kaydını
# (case-scoped `generation_reviews/` dizini, `O_CREAT|O_EXCL` + zaman
# damgalı taban ad) KENDİ atomic-write+rollback sınırı İÇİNDE üretir.
# `channel = "local_lawyer_legal_research_case_law_cli"` - önceki
# facade'lerin channel sentinel'i YENİDEN KULLANILMAZ.
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
# Kapalı row_key -> writer modülü eşlemesi - önceki ailelerin kendi
# sözlüklerinden BİLİNÇLİ AYRI (repo emsali: her kontrat şekli kendi
# kapalı eşlemesini taşır).
# ----------------------------------------------------------------

LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME = {
    "legal_research": "legal_research_engine",
    "case_law": "case_law_engine",
}

_ENGINE_VERSION_ATTR_BY_ROW_KEY = {
    "legal_research": "LEGAL_RESEARCH_ENGINE_VERSION",
    "case_law": "CASE_LAW_ENGINE_VERSION",
}

_AGENT_MODULE_NAME_BY_ROW_KEY = {
    "legal_research": "legal_research_agent",
    "case_law": "case_law_agent",
}

_AGENT_VERSION_ATTR_BY_ROW_KEY = {
    "legal_research": "LEGAL_RESEARCH_AGENT_VERSION",
    "case_law": "CASE_LAW_AGENT_VERSION",
}

_MANIFEST_VERSION_BY_ROW_KEY = {
    "legal_research": "row19c3civ.legal_research.manifest.v1",
    "case_law": "row19c3civ.case_law.manifest.v1",
}

# ----------------------------------------------------------------
# ALTI/DÖRT SABİT LOGICAL-INPUT SPESİFİKASYONLARI.
#
# Her giriş: (logical_name, kind, extra).
#   kind == "facts"         -> documents/*/extractions/facts.json
#                              (documents/ dizininin KENDİSİ zorunlu -
#                              yoksa TÜM attempt fail-closed durur;
#                              tekil facts.json'lar opsiyonel).
#   kind == "single"         -> case-scoped sabit segment dizisi,
#                              extra = (segments, required).
#   kind == "global_single"  -> DATA-ROOT-scoped (case_root_real
#                              DEĞİL, data_root_real altında) sabit
#                              segment dizisi, extra = (segments,
#                              required) - bu ailede case_law digest'i
#                              provisions.json TAŞIMAZ (D13: builder
#                              okumuyor).
# ----------------------------------------------------------------

FAMILY_INPUT_SPECS = {
    "legal_research": [
        ("issues", "single", (("issues", "issues.json"), True)),
        ("facts", "facts", None),
        ("timeline", "single", (("timeline", "timeline.json"), True)),
        ("deadline", "single", (("deadlines", "deadline.json"), False)),
        ("global_documents", "global_single", (("documents.json",), False)),
        ("global_provisions", "global_single", (("provisions.json",), True)),
    ],
    "case_law": [
        ("issues", "single", (("issues", "issues.json"), True)),
        ("timeline", "single", (("timeline", "timeline.json"), True)),
        ("research", "single", (("research", "research.json"), False)),
        ("global_documents", "global_single", (("documents.json",), False)),
    ],
}

# Exact, kapalı logical_name allowlist'i per family - adapter'ın
# identity_payload shape doğrulaması bunu KENDİ bağımsız kopyasında
# taşır (bu sözlük import EDİLMEZ, yalnız değeri iki tarafta da AYNI
# kaynaktan elle senkron tutulur; drift, izole bir canary testiyle
# yakalanır).
FAMILY_LOGICAL_NAME_COUNTS = {row_key: len(spec) for row_key, spec in FAMILY_INPUT_SPECS.items()}

_ACTION_FAMILY_PREFIX = "generation."

_CASE_RESOURCE_KEY_PREFIX = "case:"

TARGET_STATE = "generated"

CHANNEL = "local_lawyer_legal_research_case_law_cli"

_logger = logging.getLogger("vergi_ai.legal_research_case_law_mutation_facade")


def _log_critical_safely(message: str) -> None:
    try:
        _logger.critical(message)
    except Exception:
        pass


def legal_research_case_law_action_family_for(row_key: str) -> str:
    """`generation.<row_key>` - hem bu modülün MutationIntent'i hem
    `legal_research_case_law_mutation_adapters.register_into()` BU
    fonksiyonu çağırır; iki taraf farklı string'lere kayamaz."""
    if row_key not in LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME:
        raise KeyError(f"row_key={row_key!r} is not a known legal-research/case-law family")
    return f"{_ACTION_FAMILY_PREFIX}{row_key}"


def legal_research_case_law_target_ref_for(row_key: str) -> str:
    return f"{row_key}.pending"


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ----------------------------------------------------------------
# Hata sınıfları - HEPSİ `ApprovalUiError` alt sınıfı (ui.cli_mutate'in
# mevcut, DEĞİŞTİRİLMEMİŞ domain-error tanıma mekanizması bunları
# otomatik tanır).
# ----------------------------------------------------------------


class LegalResearchCaseLawArgumentError(ApprovalUiError):
    """Kullanım-şekli/argüman sözleşmesi ihlali - HERHANGİ bir DB/
    filesystem I/O'sundan ÖNCE fırlatılır."""


class LegalResearchCaseLawInputContainmentError(ApprovalUiError):
    """Writer-root/nested/girdi-taraması containment doğrulaması
    başarısız (kaçan/kırık/döngüsel link, kök doğrulanamadı, in-tree
    alias, geçersiz segment adı, gerekli girdi eksik)."""


class LegalResearchCaseLawResolvedCaseIdMismatchError(ApprovalUiError):
    """İç (kilit-altı) authz'ın çözdüğü case_id, dış (pre-lock)
    authz'ınkinden farklı."""


class LegalResearchCaseLawAuditBindingVerificationFailedError(ApprovalUiError):
    """Safe-replay corroboration başarısız - insan reconciliation'ı
    gerekir."""

    def __init__(self, *, journal_id: int, idempotency_key: str, reason: str):
        self.journal_id = journal_id
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(
            f"journal_id={journal_id}: legal research/case law safe-replay audit-binding "
            f"verification failed (idempotency_key={idempotency_key!r}): {reason}"
        )


# ----------------------------------------------------------------
# WRITER-ROOT / NESTED CONTAINMENT (case-scoped) - bu modülün KENDİ
# bağımsız kopyası (adapters kendi kopyasını taşır, iki taraf
# birbirinden import ETMEZ; yalnız karar içermeyen `src/path_
# containment.py` paylaşılır).
# ----------------------------------------------------------------


def _resolve_module_case_root_real(module, case_id: str) -> Path:
    cases_dir = module.CASES_DIR
    try:
        _path_containment.validate_segment(case_id)
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise LegalResearchCaseLawInputContainmentError(
            "Generation case kökü containment doğrulamasından geçemedi."
        ) from error


def _verify_nested(module, case_root_real: Path, case_id: str, raw_path) -> Path:
    cases_dir = module.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise LegalResearchCaseLawInputContainmentError(
            "Generation yolu beklenen case kapsamı dışında."
        ) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise LegalResearchCaseLawInputContainmentError(
            "Generation yolu containment doğrulamasından geçemedi."
        ) from error


# ----------------------------------------------------------------
# GLOBAL (DATA-ROOT-SCOPED) CONTAINMENT - bu ailede İKİNCİ, AYRI bir
# containment kökü: `documents.json`/`provisions.json` case_root_real
# ALTINDA DEĞİL, motorun KENDİ `DATA_DIR`'inde (kendi `BASE_DIR`'ine
# karşı doğrulanmış) yaşar.
# ----------------------------------------------------------------


def _resolve_module_data_root_real(module) -> Path:
    try:
        return _path_containment.resolve_existing(module.DATA_DIR, root=module.BASE_DIR)
    except _path_containment.PathContainmentError as error:
        raise LegalResearchCaseLawInputContainmentError(
            "Global data kökü containment doğrulamasından geçemedi."
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
        raise LegalResearchCaseLawInputContainmentError(
            "documents/ dizini listelenemedi."
        ) from error

    results = []

    for entry in raw_entries:
        name = entry.name

        try:
            _path_containment.validate_segment(name)
        except _path_containment.PathContainmentError as error:
            raise LegalResearchCaseLawInputContainmentError(
                f"documents/ altında geçersiz segment adı: {name!r}"
            ) from error

        try:
            entry_real = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise LegalResearchCaseLawInputContainmentError(
                f"documents/{name} containment doğrulamasından geçemedi "
                "(kaçan/kırık/döngüsel giriş)."
            ) from error

        if entry_real.parent != documents_dir_real:
            raise LegalResearchCaseLawInputContainmentError(
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
                raise LegalResearchCaseLawInputContainmentError(
                    f"documents/{name}/{'/'.join(leaf_segments[:index+1])} containment "
                    "doğrulamasından geçemedi (kaçan/kırık/döngüsel giriş)."
                ) from error
            if seg_real.parent != current_real:
                raise LegalResearchCaseLawInputContainmentError(
                    f"documents/{name}/{'/'.join(leaf_segments[:index+1])} beklenen dizinin "
                    "doğrudan çocuğu değil (in-tree alias)."
                )
            is_last = index == len(leaf_segments) - 1
            if is_last:
                if not seg_real.is_file():
                    raise LegalResearchCaseLawInputContainmentError(
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
        raise LegalResearchCaseLawInputContainmentError(
            "documents/ taramasında duplicate/alias çözümlenmiş yol tespit edildi."
        )

    return sorted(results, key=lambda pair: pair[0])


def _scan_single_file(root_real: Path, segments, logical_name: str, *, required: bool):
    """Sabit, önceden bilinen bir segment dizisini `root_real`den
    itibaren SEGMENT-SEGMENT tarar - `lexists()` HER segment adımında
    kontrol edilir, böylece ARA bir segment kırık/döngüsel/kaçan bir
    alias olduğunda bu asla "missing"e yanlış sınıflandırılmaz.
    `root_real` case-scoped (`case_root_real`) VEYA data-root-scoped
    (`data_root_real`) olabilir - bu fonksiyon HANGİ kök olduğunu
    bilmez/umursamaz, yalnız kendisine verilen kökten itibaren tarar."""
    current_real = root_real

    for index, seg in enumerate(segments):
        try:
            _path_containment.validate_segment(seg)
        except _path_containment.PathContainmentError as error:
            raise LegalResearchCaseLawInputContainmentError(
                f"{logical_name}: geçersiz segment adı {seg!r}"
            ) from error

        raw_candidate = current_real / seg

        if not os.path.lexists(raw_candidate):
            if required:
                raise LegalResearchCaseLawInputContainmentError(
                    f"required input missing: {logical_name}"
                )
            return {"logical_name": logical_name, "state": "missing", "files": []}

        try:
            seg_real = _path_containment.resolve_existing(raw_candidate, root=root_real)
        except _path_containment.PathContainmentError as error:
            raise LegalResearchCaseLawInputContainmentError(
                f"{logical_name}: containment doğrulamasından geçemedi (kaçan/kırık/döngüsel "
                "giriş)."
            ) from error

        if seg_real.parent != current_real:
            raise LegalResearchCaseLawInputContainmentError(
                f"{logical_name}: beklenen dizinin doğrudan çocuğu değil (in-tree alias)."
            )

        is_last = index == len(segments) - 1

        if is_last:
            if not seg_real.is_file():
                raise LegalResearchCaseLawInputContainmentError(
                    f"{logical_name}: güvenli-fakat-normal-dosya değil."
                )
        else:
            if not seg_real.is_dir():
                if required:
                    raise LegalResearchCaseLawInputContainmentError(
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


def _build_manifest_containers(row_key: str, case_root_real: Path, data_root_real: Path):
    spec = FAMILY_INPUT_SPECS[row_key]

    documents_dir_real_box = {"value": None, "resolved": False}

    def get_documents_dir_real():
        if not documents_dir_real_box["resolved"]:
            try:
                documents_dir_real_box["value"] = _path_containment.resolve_existing(
                    case_root_real / "documents", root=case_root_real,
                )
            except _path_containment.PathContainmentError as error:
                raise LegalResearchCaseLawInputContainmentError(
                    "documents/ containment doğrulamasından geçemedi (veya bulunamadı)."
                ) from error
            documents_dir_real_box["resolved"] = True
        return documents_dir_real_box["value"]

    containers = []

    for logical_name, kind, extra in spec:

        if kind == "facts":
            docs_dir = get_documents_dir_real()
            entries = _scan_verified_leaf_chain(case_root_real, docs_dir, ("extractions", "facts.json"))
            containers.append({
                "logical_name": logical_name,
                "state": "present" if entries else "empty",
                "files": [
                    {"logical_relative_path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    for rel, path in entries
                ],
            })

        elif kind == "single":
            segments, required = extra
            containers.append(_scan_single_file(case_root_real, segments, logical_name, required=required))

        elif kind == "global_single":
            segments, required = extra
            containers.append(_scan_single_file(data_root_real, segments, logical_name, required=required))

        else:
            raise KeyError(f"unknown manifest input kind={kind!r}")

    containers.sort(key=lambda c: c["logical_name"])

    return containers


# ----------------------------------------------------------------
# IDENTITY PAYLOAD - canonical serialization + freeze/reconstruct.
# ----------------------------------------------------------------


def _resolve_generation_provenance(module, row_key: str, with_agent: bool, llm_client):
    """(generation_mode, model_id, engine_version, prompt_agent_version).
    `engine_version` motorun KENDİ, call-time okunan sürüm sabitinden
    gelir (`LEGAL_RESEARCH_ENGINE_VERSION="1"` / `CASE_LAW_ENGINE_
    VERSION="2"` - ikisi FARKLIDIR). `llm_client` yalnız test seam'idir
    (bkz. modül başlığı) - production caller'ı (ui.cli_mutate) bu
    parametreyi HİÇBİR ZAMAN geçirmez."""
    import importlib

    engine_version = getattr(module, _ENGINE_VERSION_ATTR_BY_ROW_KEY[row_key])

    if not with_agent:
        return "deterministic", "deterministic_no_model", engine_version, "n/a"

    agent_module = importlib.import_module(_AGENT_MODULE_NAME_BY_ROW_KEY[row_key])
    prompt_agent_version = getattr(agent_module, _AGENT_VERSION_ATTR_BY_ROW_KEY[row_key])

    if llm_client is not None:
        return "agent", "external_injected_client", engine_version, prompt_agent_version

    model_id = agent_module.DEFAULT_AGENT_MODEL
    return "agent", model_id, engine_version, prompt_agent_version


def _build_identity_payload(row_key, case_id, manifest, generation_mode, model_id, engine_version, prompt_agent_version):
    return {
        "manifest_version": _MANIFEST_VERSION_BY_ROW_KEY[row_key],
        "case_id": case_id,
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
class VerifiedLegalResearchCaseLawOutputPaths:
    family_root: Path
    pending_path: Path
    history_dir: Path
    reviews_dir: Path

    @property
    def identity(self):
        return (
            str(self.family_root), str(self.pending_path), str(self.history_dir), str(self.reviews_dir),
        )


def _derive_verified_output_paths(module, case_root_real: Path, case_id: str):
    raw_pending_path = module.get_pending_path(case_id)
    family_root = _verify_nested(module, case_root_real, case_id, raw_pending_path.parent)
    pending_path = _verify_nested(module, case_root_real, case_id, raw_pending_path)
    history_dir = _verify_nested(module, case_root_real, case_id, module.get_history_dir(case_id))
    reviews_dir = _verify_nested(module, case_root_real, case_id, module.get_reviews_dir(case_id))
    return VerifiedLegalResearchCaseLawOutputPaths(
        family_root=family_root, pending_path=pending_path, history_dir=history_dir, reviews_dir=reviews_dir,
    )


# ----------------------------------------------------------------
# COMPOSITE PRE-STATE SNAPSHOT (pending-conflict kontrolü) - TEK
# paylaşılan literal (her iki row_key için AYNI - snapshot payload'ı
# row_key'e özgü hiçbir şey taşımaz, yalnız input_digest/pending
# durumunu bağlar).
# ----------------------------------------------------------------

_SNAPSHOT_VERSION = "row19c3civ.legal_research_case_law.snapshot.v1"

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
# PENDING-FILE FROZEN-BYTE RECIPE - önceki ailelerin `_freeze_pending_
# bytes()`'i ile BYTE-FOR-BYTE aynı: `json.dumps(..., ensure_ascii=
# False, indent=2)` + tek bir trailing `"\n"`. Bu, `write_pending()`'in
# KENDİ `atomic_write_json()`'ının (`newline="\n"` + `file.write("\n")`)
# yazacağı TAM baytlarla eşleşir.
# ----------------------------------------------------------------


def _freeze_pending_bytes(analysis: dict) -> bytes:
    return json.dumps(analysis, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


# ----------------------------------------------------------------
# WRITER/BUILDER DISPATCH - per-family çağrı şekli farklılıkları TEK
# noktada toplanır.
# ----------------------------------------------------------------


def _invoke_builder(row_key, module, case_id, *, use_agent, llm_client, network_allowed):
    if row_key == "legal_research":
        return module.build_research_engine_output(
            case_id, use_agent=use_agent, llm_client=llm_client,
            use_discovery=False, retrieval_fn=None, network_allowed=network_allowed,
        )
    if row_key == "case_law":
        # ROW 19C-3c-iv SLICE 1 F1 REMEDIATION: case_law'da (legal_research'ün
        # `use_discovery` parametresinin aksine) discovery bir baseline
        # adımdır - `network_allowed` tek başına agent İZNİYLE discovery
        # katmanına da ulaşırdı. `discovery_network_allowed=False` sabiti
        # discovery'yi network yetkisinden YAPISAL olarak ayırır; agent
        # katmanı (Anthropic) `network_allowed` ile İZİNLİ kalmaya devam eder.
        return module.build_case_law_engine_output(
            case_id, use_agent=use_agent, llm_client=llm_client,
            retrieval_fn=None, network_allowed=network_allowed,
            discovery_network_allowed=False,
        )
    raise KeyError(f"unknown row_key={row_key!r}")


def _invoke_writer(
    row_key, module, case_id, candidate, build_result, *,
    verified_paths, input_digest, identity_payload,
    mutation_idempotency_key, mutation_resource_key, mutation_actor_ref,
):
    common_kwargs = dict(
        verified_paths=verified_paths, input_digest=input_digest, identity_payload=identity_payload,
        mutation_idempotency_key=mutation_idempotency_key, mutation_resource_key=mutation_resource_key,
        mutation_actor_ref=mutation_actor_ref,
    )
    if row_key == "legal_research":
        return module.write_pending(case_id, candidate, **common_kwargs)
    if row_key == "case_law":
        return module.write_pending(case_id, candidate, build_result["issue_count"], **common_kwargs)
    raise KeyError(f"unknown row_key={row_key!r}")


# ----------------------------------------------------------------
# ARGÜMAN ŞEKİL KURALLARI - her I/O'dan önce.
# ----------------------------------------------------------------


def _check_argument_shapes(row_key: str, expected_input_digest=None, *, for_apply: bool):
    if row_key not in LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME:
        raise KeyError(f"row_key={row_key!r} is not a known legal-research/case-law family")

    if for_apply and (
        not isinstance(expected_input_digest, str) or not expected_input_digest.strip()
    ):
        raise LegalResearchCaseLawArgumentError(
            "expected_input_digest apply için zorunlu, boş olamaz."
        )


# ----------------------------------------------------------------
# AUTHZ REPO / JOURNAL CONN KURULUMU - önceki facade'lerin kendi
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
# PREVIEW (salt-okunur, model ASLA çağrılmaz)
# ----------------------------------------------------------------


def preview_generation(
    row_key: str,
    case_id: str,
    *,
    with_agent: bool = False,
    llm_client=None,
    principal,
    authz_repository=None,
):
    """Salt-okunur preview. SIRA: dış 'read' authz HER filesystem
    probundan ÖNCE koşar. `llm_client` yalnız identity/provenance
    seçimini belirlemek için KULLANILIR - hiçbir metodu ÇAĞRILMAZ."""
    _check_argument_shapes(row_key, for_apply=False)
    import importlib
    module = importlib.import_module(LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME[row_key])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "read", repository=repository,
        )

        case_root_real = _resolve_module_case_root_real(module, resolved_case_id)
        data_root_real = _resolve_module_data_root_real(module)
        paths = _derive_verified_output_paths(module, case_root_real, resolved_case_id)

        manifest = _build_manifest_containers(row_key, case_root_real, data_root_real)
        generation_mode, model_id, engine_version, prompt_agent_version = _resolve_generation_provenance(
            module, row_key, with_agent, llm_client,
        )
        identity_payload = _build_identity_payload(
            row_key, resolved_case_id, manifest, generation_mode, model_id, engine_version, prompt_agent_version,
        )
        identity_bytes = _canonical_identity_bytes(identity_payload)
        input_digest = _compute_input_digest(identity_bytes)

        return {
            "row_key": row_key,
            "case_id": resolved_case_id,
            "target_ref": legal_research_case_law_target_ref_for(row_key),
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
class LegalResearchCaseLawApplyResult:
    row_key: str
    case_id: str
    pending_path: Path
    pending_sha256: str | None
    audit_path: Path | None
    stdout: str
    journal_id: int
    replayed: bool


def _audit_record_matches_base(record: dict, *, idempotency_key: str, resource_key: str,
                                action_family: str, pending_sha256: str) -> bool:
    if not _nonblank(record.get("mutation_idempotency_key")) or record.get("mutation_idempotency_key") != idempotency_key:
        return False
    if not _nonblank(record.get("mutation_resource_key")) or record.get("mutation_resource_key") != resource_key:
        return False
    if record.get("action_family") != action_family:
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
        raise LegalResearchCaseLawInputContainmentError(
            "Generation reviews dizini listelenemedi."
        ) from error
    results = []
    for entry in raw_entries:
        if not fnmatch.fnmatch(entry.name, "*.generation_audit.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise LegalResearchCaseLawInputContainmentError(
                f"generation_reviews/{entry.name} containment doğrulamasından geçemedi."
            ) from error
        if resolved.parent != reviews_dir_verified:
            raise LegalResearchCaseLawInputContainmentError(
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
    paths: VerifiedLegalResearchCaseLawOutputPaths, case_root_real: Path, *,
    action_family: str, journal_state: str, journal_id: int,
    idempotency_key: str, resource_key: str, observed_post_hash,
):
    """Completed safe-replay corroboration - yalnız `completed`
    durumdaki bir satırı YENİDEN DOĞRULAR (sonuç zaten BİLİNİYOR)."""

    def fail(reason):
        raise LegalResearchCaseLawAuditBindingVerificationFailedError(
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
            action_family=action_family, pending_sha256=current_pending_sha256,
        )
    ]
    if len(matches) != 1:
        fail(
            f"tam-bağlama eşleşen success audit sayısı {len(matches)} (tam 1 olmalı) - "
            "bu completed satır bağımsızca doğrulanamadı"
        )
    return current_pending_sha256, matches[0][0]


def apply_generation(
    row_key: str,
    case_id: str,
    expected_input_digest: str,
    *,
    with_agent: bool = False,
    allow_network: bool = False,
    llm_client=None,
    principal,
    authz_repository=None,
    conn_factory=None,
) -> LegalResearchCaseLawApplyResult:
    """SIRA: (1) argüman şekilleri (saf, I/O'suz); (2) DIŞ
    authorize_case_access('mutate'); (3) pre-lock manifest/identity +
    composite pending snapshot + expected_input_digest karşılaştırması;
    (4) DIŞ-LOCK build (deterministic veya agent, journal satırı
    OLMADAN - retrieval/discovery HİÇBİR ZAMAN tetiklenmez); (5) frozen
    candidate; (6) conn + case lock; (7) run_mutation: İÇ otoriter authz
    -> journal gate -> idempotency -> precondition (SIFIRDAN kilit-altı
    taze re-derivation, byte-for-byte identity karşılaştırması; her red
    sıfır journal satırı) -> writer (verified paths + frozen candidate
    ÜZERİNDEN, HİÇBİR yeniden build/model çağrısı OLMADAN); (8) replay'de
    tam corroboration; (9) maskelemeyen temizlik."""
    import importlib

    _check_argument_shapes(row_key, expected_input_digest, for_apply=True)

    if allow_network and not with_agent:
        raise LegalResearchCaseLawArgumentError(
            "allow_network yalnız with_agent İLE BİRLİKTE anlamlıdır."
        )

    module = importlib.import_module(LEGAL_RESEARCH_CASE_LAW_ROW_KEY_TO_MODULE_NAME[row_key])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        outer_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )

        resource_key = _mutation_lock.case_resource_key(outer_resolved_case_id)
        action_family = legal_research_case_law_action_family_for(row_key)
        target_ref = legal_research_case_law_target_ref_for(row_key)

        pre_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
        pre_data_root = _resolve_module_data_root_real(module)
        pre_paths = _derive_verified_output_paths(module, pre_case_root, outer_resolved_case_id)

        pre_manifest = _build_manifest_containers(row_key, pre_case_root, pre_data_root)
        generation_mode, model_id, engine_version, prompt_agent_version = _resolve_generation_provenance(
            module, row_key, with_agent, llm_client,
        )
        pre_identity_payload = _build_identity_payload(
            row_key, outer_resolved_case_id, pre_manifest, generation_mode, model_id,
            engine_version, prompt_agent_version,
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

        # DIŞ-LOCK BUILD - hiçbir journal satırı, hiçbir filesystem
        # mutasyonu bu noktada OLUŞMAZ. Retrieval/discovery HİÇBİR ZAMAN
        # tetiklenmez (legal_research: use_discovery=False, retrieval_fn=
        # None SABİT; case_law: retrieval_fn=None SABİT VE
        # discovery_network_allowed=False SABİT - agent-network izni
        # (`network_allowed`) YALNIZ Anthropic-agent katmanına ulaşır,
        # discovery katmanına HİÇBİR ZAMAN taşınmaz - bkz. F1 remediation).
        build_result = _invoke_builder(
            row_key, module, outer_resolved_case_id,
            use_agent=with_agent, llm_client=llm_client, network_allowed=allow_network,
        )
        analysis = build_result["analysis"]

        frozen_pending_bytes = _freeze_pending_bytes(analysis)

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

        under_lock_box = {}
        writer_outcome_box = {}

        def authz_callback() -> None:
            inner_resolved_case_id = _authz.authorize_case_access(
                principal, case_id, "mutate", repository=repository,
            )
            if inner_resolved_case_id != outer_resolved_case_id:
                raise LegalResearchCaseLawResolvedCaseIdMismatchError(
                    f"outer authz {outer_resolved_case_id!r} çözdü, inner authz "
                    f"{inner_resolved_case_id!r} - reddedildi."
                )

        def precondition_callback() -> None:
            ul_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
            ul_data_root = _resolve_module_data_root_real(module)
            ul_paths = _derive_verified_output_paths(module, ul_case_root, outer_resolved_case_id)
            if ul_paths.identity != pre_paths.identity:
                raise PreconditionRaceDetectedError(
                    "Bu generation isteği case kilidini beklerken ilgili dizin/dosyaların "
                    "çözümlenmiş (gerçek) konumu DEĞİŞTİ (link swap veya benzeri). İşlem iptal "
                    "edildi, HİÇBİR değişiklik yapılmadı."
                )

            ul_manifest = _build_manifest_containers(row_key, ul_case_root, ul_data_root)
            ul_identity_payload = _build_identity_payload(
                row_key, outer_resolved_case_id, ul_manifest, generation_mode, model_id,
                engine_version, prompt_agent_version,
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
            # Audit'e geçirilecek identity_payload HER ZAMAN frozen bytes'tan
            # TAZE json.loads() ile üretilir - ul_identity_payload (ilk
            # mutable dict) bir daha KULLANILMAZ.
            under_lock_box["identity_payload_for_audit"] = json.loads(
                ul_identity_bytes.decode("utf-8")
            )

        def writer_callback() -> _mutation_coordinator.WriterResult:
            import io
            import contextlib

            ul_paths = under_lock_box["paths"]
            identity_payload_for_audit = under_lock_box["identity_payload_for_audit"]

            # Frozen bytes'tan TAZE reconstruction - build sırasında
            # üretilen `analysis` referansı bir daha KULLANILMAZ.
            candidate = json.loads(frozen_pending_bytes.decode("utf-8"))

            stdout_capture = io.StringIO()
            with contextlib.redirect_stdout(stdout_capture):
                write_result = _invoke_writer(
                    row_key, module, outer_resolved_case_id, candidate, build_result,
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
                        module, replay_case_root, outer_resolved_case_id,
                    )
                    verified_pending_hash, audit_path = _verify_completed_replay_binding(
                        replay_paths, replay_case_root,
                        action_family=action_family,
                        journal_state=outcome.state,
                        journal_id=outcome.journal_id,
                        idempotency_key=idempotency_key_for_audit,
                        resource_key=resource_key,
                        observed_post_hash=outcome.observed_post_hash,
                    )
                except LegalResearchCaseLawInputContainmentError as error:
                    raise LegalResearchCaseLawAuditBindingVerificationFailedError(
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

            return LegalResearchCaseLawApplyResult(
                row_key=row_key,
                case_id=outer_resolved_case_id,
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
