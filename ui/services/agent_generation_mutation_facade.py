# ============================================================
# VERGİ AI - ROW 19C-3c-ii: CASE-SCOPED AGENT-GATED PENDING
# GENERATION MUTATION FACADE.
#
# Beş case-scoped, agent-gated pending-generation writer'ını (issue_
# spotting, evidence, argument, risk_strategy, drafting - Row 9/12/13/
# 14/15) mutation coordinator/journal altyapısına bağlayan, AYRI ve
# BAĞIMSIZ facade - `generation_mutation_facade.py` (deadline/timeline,
# Row 19C-3c-i, tamamen deterministik, 2 anahtarlı, LOCKED) GENİŞLETİLMEZ
# (repo emsali: her yeni kontrat şekli kendi facade+adapters çiftini
# alır). Bu facade `generation_mutation_facade.py`'nin genel mimarisini
# (outer/inner authz, composite pre-state snapshot, kilit-altı fresh
# re-derivation, writer-root kontratı) TAKİP EDER, ama İKİ önemli
# yönden ONDAN İLERİ GİDER:
#
#   1. GİRDİ TARAMASI: `generation_mutation_facade.py`'nin OUTPUT
#      path'leri (pending/history/reviews) yalnız KENDİ facade-seviyeli
#      precondition/replay kontrolleri için türetilir - writer'a HİÇ
#      geçirilmez (writer kendi ham getter'larını tekrar çağırır). Bu
#      facade bu boşluğu KAPATIR: `VerifiedGenerationOutputPaths`
#      writer'a (`write_pending(..., verified_paths=...)`) DOĞRUDAN
#      geçirilir - writer bütün output I/O'sunu SADECE bu nesneler
#      üzerinden yapar.
#   2. IDENTITY: `input_digest` beş ailenin HER BİRİ için, containment-
#      before-traversal bir manifest scanner'la (`_scan_verified_leaf_
#      chain`/`_scan_single_file` - HİÇBİR raw `Path.glob()`/`is_dir`/
#      `is_file`/`exists`/`stat` KULLANILMAZ, `_scan_timeline_verified_
#      inputs()`'in AYNI segment-segment disiplininin genellenmiş hali)
#      + `generation_mode`/`model_id`/`prompt_agent_version`'dan kurulan
#      bir `identity_payload` sözlüğünün canonical-bytes hash'idir.
#
# ACTION FAMILY'LER: `generation.issue_spotting` / `generation.evidence`
# / `generation.argument` / `generation.risk_strategy` /
# `generation.drafting`. Kanal ayrımı YOK - CLI-only (`python -m
# ui.cli_mutate generation --row-key <family> ...`, MEVCUT/LOCKED
# `generation` namespace'inin additive genişlemesi); web mutasyon yüzeyi
# YOKTUR (bilinçli kapsam dışı).
#
# 3/3/8/10/12 SABİT LOGICAL-INPUT MANİFESTİ (§FAMILY_INPUT_SPECS):
# issue_spotting=3, evidence=3, argument=8 (canonical arguments.json
# carry-forward kaynağı DAHİL), risk_strategy=10 (canonical risk_
# strategy.json carry-forward kaynağı DAHİL), drafting=12 (risk_
# strategy upstream girdisi + lawyer_input + canonical drafting.json
# carry-forward kaynağı DAHİL). Her giriş builder çıktısını veya carry-
# forward sonucunu etkileyebilecek bir dosyadır - builder'ın kendi
# `analysis_metadata` alanları (varsa) YALNIZ informational amaçlıdır,
# identity OTORİTESİ DEĞİLDİR (builder raw bytes değil, reshaped/
# semantic bir Python yapısını hash'ler - iki hash şeması KARŞILAŞTIRIL-
# MAZ, facade'in KENDİ bağımsız manifest hash'i TEK identity kaynağıdır).
#
# ARGUMENT'A ÖZGÜ: `build_argument_engine_output(...,
# write_carry_forward_audit_enabled=False)` - dış-lock build sırasında
# HİÇBİR carry-forward audit dosyası YAZILMAZ (Blocker 1, ROW 19C-3c-ii
# FINAL FIVE BLOCKERS CLOSURE raporu). `carry_records` build sonucundan
# alınıp DONDURULUR (bkz. "FREEZE/RECONSTRUCT" bölümü) ve under-lock
# writer_callback'e taşınır - `argument_engine.write_pending()` orada
# HEM carry-forward audit'i (varsa) HEM coordinator success audit'ini,
# TEK rollback sınırı içinde, sabit sırayla (carry-forward ÖNCE,
# coordinator SONRA, ikincisi başarısız olursa birincisi için best-
# effort temizlik) üretir.
#
# FREEZE/RECONSTRUCT (Onay mesajının "Bağlayıcı ek düzeltme A/B"'si):
# `identity_payload` ve (argument için) `carry_records`, facade
# tarafından üretildikleri anda HEMEN canonical JSON bytes'a
# dondurulur (`json.dumps(..., sort_keys=True, separators=(",", ":"))
# .encode("utf-8")`). Pre-build/under-lock karşılaştırması BU BYTES
# ÜZERİNDEN yapılır (yalnız hash değil - byte-for-byte eşitlik).
# Writer'a/audit'e geçirilen nesne HER ZAMAN `json.loads(frozen_bytes)`
# ile üretilen TAZE bir kopyadır - ilk mutable dict/list referansı
# freeze'den sonra bir daha KULLANILMAZ.
#
# LLM_CLIENT TEST SEAM (production'da hiçbir zaman erişilemez):
# `preview_generation()` VE `apply_generation()` additive, keyword-only
# `llm_client=None` kabul eder - bu bir CLI flag DEĞİLDİR, yalnız
# dependency-injection/test seam'idir. `ui/cli_mutate.py`'nin
# `_run_generation()` dispatch'i bu parametreyi HİÇBİR ZAMAN GEÇMEZ (bu
# dosyanın kendi call shape'i bunu kanıtlar - imzada isim yok demek
# argüman yok demektir). `llm_client is None` + agent mode ->
# model_id/prompt_agent_version GERÇEK, ailenin kendi modülünden
# importlib ile ÇAĞRI ANINDA okunan sabitlerdir. `llm_client` verilmişse
# (yalnız test) -> model_id="external_injected_client",
# prompt_agent_version YİNE GERÇEK sabittir (aynı gerçek prompt-
# builder kodu çalışır, yalnız hangi MODEL cevap verdiği bilinmez).
# Deterministic mode: model_id="deterministic_no_model",
# prompt_agent_version="n/a" (llm_client verilse bile - agent hiç
# etkinleştirilmediği için client'a HİÇ dokunulmaz).
#
# WRITER-ROOT KONTRATI: writer containment kökü ÇAĞRI ANINDA writer
# modülünün KENDİ `CASES_DIR` attribute'undan okunur, asla cache'lenmez.
#
# POST-STATE: generation'ın pending çıktısı DETERMİNİSTİK DEĞİLDİR
# (`generated_at`) - yazarın KENDİ raporladığı `pending_sha256`
# (`write_pending()`'in dönüş dict'i) TEK doğruluk kaynağıdır.
#
# AUDIT/REPLAY: her beş yazar KENDİ `*.generation_audit.json` kaydını
# (case-scoped `generation_reviews/` dizini, `O_CREAT|O_EXCL` + zaman
# damgalı taban ad) yazarın KENDİ atomic-write+rollback sınırı İÇİNDE
# üretir. `mutation_actor_ref` alanı `entry.actor_label`'a (mevcut,
# NOT NULL journal kolonu, ROW 19C-2b'de eklendi - HİÇBİR migration
# gerekmez) bağlanır.
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
# Kapalı row_key -> writer modülü eşlemesi (Layer A/promotion/
# generation_mutation_facade'in kendi sözlüklerinden BİLİNÇLİ AYRI -
# repo emsali: her kontrat şekli kendi kapalı eşlemesini taşır).
# ----------------------------------------------------------------

AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME = {
    "issue_spotting": "issue_spotting_engine",
    "evidence": "evidence_engine",
    "argument": "argument_engine",
    "risk_strategy": "risk_strategy_engine",
    "drafting": "drafting_engine",
}

_BUILD_FUNCTION_NAME_BY_ROW_KEY = {
    "issue_spotting": "build_issue_engine_output",
    "evidence": "build_evidence_engine_output",
    "argument": "build_argument_engine_output",
    "risk_strategy": "build_risk_strategy_engine_output",
    "drafting": "build_drafting_engine_output",
}

_AGENT_MODULE_NAME_BY_ROW_KEY = {
    "issue_spotting": "issue_spotting_agent",
    "evidence": "evidence_agent",
    "argument": "argument_agent",
    "risk_strategy": "risk_strategy_agent",
    "drafting": "drafting_agent",
}

_AGENT_VERSION_ATTR_BY_ROW_KEY = {
    "issue_spotting": "ISSUE_SPOTTING_AGENT_VERSION",
    "evidence": "EVIDENCE_AGENT_VERSION",
    "argument": "ARGUMENT_AGENT_VERSION",
    "risk_strategy": "RISK_STRATEGY_AGENT_VERSION",
    "drafting": "DRAFTING_AGENT_VERSION",
}

_ACTION_FAMILY_PREFIX = "generation."

_CASE_RESOURCE_KEY_PREFIX = "case:"

TARGET_STATE = "generated"

CHANNEL = "local_lawyer_generation_cli"

_MANIFEST_VERSION = "row19c3cii.agent_generation.v1"

_logger = logging.getLogger("vergi_ai.agent_generation_mutation_facade")


def _log_critical_safely(message: str) -> None:
    try:
        _logger.critical(message)
    except Exception:
        pass


def agent_generation_action_family_for(row_key: str) -> str:
    """`generation.<row_key>` - hem bu modülün MutationIntent'i hem
    `agent_generation_mutation_adapters.register_into()` BU fonksiyonu
    çağırır; iki taraf farklı string'lere kayamaz."""
    return f"{_ACTION_FAMILY_PREFIX}{row_key}"


def agent_generation_target_ref_for(row_key: str) -> str:
    return f"{row_key}.pending"


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ----------------------------------------------------------------
# Hata sınıfları - HEPSİ `ApprovalUiError` alt sınıfı (ui.cli_mutate'in
# mevcut, DEĞİŞTİRİLMEMİŞ domain-error tanıma mekanizması bunları
# otomatik tanır).
# ----------------------------------------------------------------


class AgentGenerationArgumentError(ApprovalUiError):
    """Kullanım-şekli/argüman sözleşmesi ihlali - HERHANGİ bir DB/
    filesystem I/O'sundan ÖNCE fırlatılır."""


class AgentGenerationInputContainmentError(ApprovalUiError):
    """Writer-root/nested/girdi-taraması containment doğrulaması
    başarısız (kaçan/kırık/döngüsel link, kök doğrulanamadı, in-tree
    alias, geçersiz segment adı, gerekli girdi eksik)."""


class AgentGenerationResolvedCaseIdMismatchError(ApprovalUiError):
    """İç (kilit-altı) authz'ın çözdüğü case_id, dış (pre-lock)
    authz'ınkinden farklı."""


class AgentGenerationAuditBindingVerificationFailedError(ApprovalUiError):
    """Safe-replay corroboration başarısız - insan reconciliation'ı
    gerekir."""

    def __init__(self, *, journal_id: int, idempotency_key: str, reason: str):
        self.journal_id = journal_id
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(
            f"journal_id={journal_id}: agent generation safe-replay audit-binding "
            f"verification failed (idempotency_key={idempotency_key!r}): {reason}"
        )


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
        raise AgentGenerationInputContainmentError(
            "Generation case kökü containment doğrulamasından geçemedi."
        ) from error


def _verify_nested(module, case_root_real: Path, case_id: str, raw_path) -> Path:
    cases_dir = module.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise AgentGenerationInputContainmentError(
            "Generation yolu beklenen case kapsamı dışında."
        ) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise AgentGenerationInputContainmentError(
            "Generation yolu containment doğrulamasından geçemedi."
        ) from error


# ----------------------------------------------------------------
# CONTAINMENT-BEFORE-TRAVERSAL MANIFEST SCANNER.
#
# HİÇBİR raw `Path.glob()`, raw `is_dir()`, raw `is_file()`, raw
# `exists()` veya raw `stat()` KULLANILMAZ - `_scan_timeline_verified_
# inputs()`'in (generation_mutation_facade.py, LOCKED) AYNI, genellenmiş
# disiplini: önce yalnız `entry.name` üzerinden saf string
# classification/segment validation, ancak SONRA containment + exact-
# parent doğrulaması, ancak ONDAN SONRA is_dir/is_file/stat/open/read.
# Missing/broken/looping/escaping ayrımı `os.path.lexists()` + `path_
# containment.resolve_existing()` ile yapılır - raw `.exists()` HİÇBİR
# YERDE bir pre-gate olarak KULLANILMAZ (broken link asla "missing"
# sayılmaz). `logical_relative_path` DOĞRULANMIŞ SEGMENT ADLARINDAN
# kurulur - hiçbir zaman resolved/target path'ten TÜRETİLMEZ (safe
# internal alias'ın logical yolu korunur, hedefin resolved yolu
# identity'ye SIZMAZ).
# ----------------------------------------------------------------


def _scan_verified_leaf_chain(case_root_real: Path, documents_dir_real: Path, leaf_segments):
    """`documents/<name>/<leaf_segments...>` zincirini segment-segment
    tarar. Dönüş: `[(logical_relative_path, resolved_path), ...]`,
    `logical_relative_path` ile sıralı. Duplicate resolved path (iki
    logical giriş AYNI güvenli hedefe çözümlenirse) TÜM taramayı
    fail-closed durdurur - `_scan_timeline_verified_inputs()`'in AYNI,
    kaynaktan doğrulanmış kararı (bkz. bu dosyanın modül başlığı)."""
    try:
        raw_entries = sorted(documents_dir_real.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise AgentGenerationInputContainmentError(
            "documents/ dizini listelenemedi."
        ) from error

    results = []

    for entry in raw_entries:
        name = entry.name

        try:
            _path_containment.validate_segment(name)
        except _path_containment.PathContainmentError as error:
            raise AgentGenerationInputContainmentError(
                f"documents/ altında geçersiz segment adı: {name!r}"
            ) from error

        try:
            entry_real = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise AgentGenerationInputContainmentError(
                f"documents/{name} containment doğrulamasından geçemedi "
                "(kaçan/kırık/döngüsel giriş)."
            ) from error

        if entry_real.parent != documents_dir_real:
            raise AgentGenerationInputContainmentError(
                f"documents/{name} beklenen dizinin doğrudan çocuğu değil (in-tree alias)."
            )

        if not entry_real.is_dir():
            # Güvenli-fakat-eşleşmeyen decoy - orijinal glob semantiğiyle
            # AYNI (bir dizin olmayan üst-seviye giriş asla eşleşmezdi).
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
                raise AgentGenerationInputContainmentError(
                    f"documents/{name}/{'/'.join(leaf_segments[:index+1])} containment "
                    "doğrulamasından geçemedi (kaçan/kırık/döngüsel giriş)."
                ) from error
            if seg_real.parent != current_real:
                raise AgentGenerationInputContainmentError(
                    f"documents/{name}/{'/'.join(leaf_segments[:index+1])} beklenen dizinin "
                    "doğrudan çocuğu değil (in-tree alias)."
                )
            is_last = index == len(leaf_segments) - 1
            if is_last:
                if not seg_real.is_file():
                    raise AgentGenerationInputContainmentError(
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
        raise AgentGenerationInputContainmentError(
            "documents/ taramasında duplicate/alias çözümlenmiş yol tespit edildi."
        )

    return sorted(results, key=lambda pair: pair[0])


def _scan_single_file(case_root_real: Path, segments, logical_name: str, *, required: bool):
    """Sabit, önceden bilinen bir segment dizisini (ör. `("issues",
    "issues.json")`) SEGMENT-SEGMENT tarar - `lexists()` HER segment
    adımında (yalnız son segment değil) kontrol edilir, böylece ARA bir
    segment kırık/döngüsel/kaçan bir alias olduğunda bu asla "missing"e
    yanlış sınıflandırılmaz."""
    current_real = case_root_real

    for index, seg in enumerate(segments):
        try:
            _path_containment.validate_segment(seg)
        except _path_containment.PathContainmentError as error:
            raise AgentGenerationInputContainmentError(
                f"{logical_name}: geçersiz segment adı {seg!r}"
            ) from error

        raw_candidate = current_real / seg

        if not os.path.lexists(raw_candidate):
            if required:
                raise AgentGenerationInputContainmentError(
                    f"required input missing: {logical_name}"
                )
            return {"logical_name": logical_name, "state": "missing", "files": []}

        try:
            seg_real = _path_containment.resolve_existing(raw_candidate, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise AgentGenerationInputContainmentError(
                f"{logical_name}: containment doğrulamasından geçemedi (kaçan/kırık/döngüsel "
                "giriş)."
            ) from error

        if seg_real.parent != current_real:
            raise AgentGenerationInputContainmentError(
                f"{logical_name}: beklenen dizinin doğrudan çocuğu değil (in-tree alias)."
            )

        is_last = index == len(segments) - 1

        if is_last:
            if not seg_real.is_file():
                raise AgentGenerationInputContainmentError(
                    f"{logical_name}: güvenli-fakat-normal-dosya değil."
                )
        else:
            if not seg_real.is_dir():
                if required:
                    raise AgentGenerationInputContainmentError(
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
# 3/3/8/10/12 SABİT LOGICAL-INPUT SPESİFİKASYONLARI.
#
# Her giriş: (logical_name, kind, segments-or-None).
#   kind == "facts"      -> documents/*/extractions/facts.json (REQUIRED
#                            - documents/ dizininin kendisi yoksa TÜM
#                            attempt fail-closed durur, builder'ın kendi
#                            required-input hata sınıfıyla AYNI nokta).
#   kind == "documents"   -> documents/*/document.json (SOFT - documents/
#                            dizini yoksa state="missing"; PRATİKTE bu
#                            dal hiçbir zaman tetiklenmez çünkü "facts"
#                            HER ailenin spesifikasyonunda ÖNCE gelir ve
#                            documents/ eksikse zaten oradan raise eder -
#                            defensive completeness için KORUNUR).
#   kind == "single"      -> sabit segment dizisi, segments[2] =
#                            required (bool).
# ----------------------------------------------------------------

FAMILY_INPUT_SPECS = {
    "issue_spotting": [
        ("facts", "facts", None),
        ("timeline", "single", (("timeline", "timeline.json"), True)),
        ("deadline", "single", (("deadlines", "deadline.json"), False)),
    ],
    "evidence": [
        ("issues", "single", (("issues", "issues.json"), True)),
        ("facts", "facts", None),
        ("documents", "documents", None),
    ],
    "argument": [
        ("issues", "single", (("issues", "issues.json"), True)),
        ("facts", "facts", None),
        ("evidence", "single", (("evidence", "evidence.json"), False)),
        ("legal_research", "single", (("research", "research.json"), False)),
        ("case_law", "single", (("case_law", "case_law.json"), False)),
        ("timeline", "single", (("timeline", "timeline.json"), False)),
        ("deadline", "single", (("deadlines", "deadline.json"), False)),
        ("canonical_arguments_self", "single", (("arguments", "arguments.json"), False)),
    ],
    "risk_strategy": [
        ("issues", "single", (("issues", "issues.json"), True)),
        ("facts", "facts", None),
        ("evidence", "single", (("evidence", "evidence.json"), False)),
        ("legal_research", "single", (("research", "research.json"), False)),
        ("case_law", "single", (("case_law", "case_law.json"), False)),
        ("timeline", "single", (("timeline", "timeline.json"), False)),
        ("deadline", "single", (("deadlines", "deadline.json"), False)),
        ("documents", "documents", None),
        ("arguments", "single", (("arguments", "arguments.json"), False)),
        ("canonical_risk_strategy_self", "single", (("risk_strategy", "risk_strategy.json"), False)),
    ],
    "drafting": [
        ("issues", "single", (("issues", "issues.json"), True)),
        ("facts", "facts", None),
        ("evidence", "single", (("evidence", "evidence.json"), False)),
        ("legal_research", "single", (("research", "research.json"), False)),
        ("case_law", "single", (("case_law", "case_law.json"), False)),
        ("timeline", "single", (("timeline", "timeline.json"), False)),
        ("deadline", "single", (("deadlines", "deadline.json"), False)),
        ("documents", "documents", None),
        ("arguments", "single", (("arguments", "arguments.json"), False)),
        ("risk_strategy", "single", (("risk_strategy", "risk_strategy.json"), False)),
        ("lawyer_input", "single", (("drafting", "inputs", "lawyer_input.json"), False)),
        ("canonical_drafting_self", "single", (("drafting", "drafting.json"), False)),
    ],
}

# Exact, kapalı logical_name allowlist'i per family - adapter'ın
# identity_payload shape doğrulaması bunu KENDİ bağımsız kopyasında
# taşır (bu sözlük import EDİLMEZ, yalnız değeri - liste - iki tarafta
# da AYNI kaynaktan, bu dosyanın kendi docstring'inden elle senkron
# tutulur; drift, izole bir canary testiyle yakalanır).
FAMILY_LOGICAL_NAME_COUNTS = {row_key: len(spec) for row_key, spec in FAMILY_INPUT_SPECS.items()}


def _build_manifest_containers(row_key: str, case_root_real: Path, case_id: str):
    spec = FAMILY_INPUT_SPECS[row_key]

    documents_dir_real_box = {"value": None, "resolved": False}

    def get_documents_dir_real():
        if not documents_dir_real_box["resolved"]:
            try:
                documents_dir_real_box["value"] = _path_containment.resolve_existing(
                    case_root_real / "documents", root=case_root_real,
                )
            except _path_containment.PathContainmentError as error:
                raise AgentGenerationInputContainmentError(
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

        elif kind == "documents":
            try:
                docs_dir = get_documents_dir_real()
            except AgentGenerationInputContainmentError:
                # Defensive completeness - bkz. bu bölümün başlık yorumu.
                containers.append({"logical_name": logical_name, "state": "missing", "files": []})
                continue
            entries = _scan_verified_leaf_chain(case_root_real, docs_dir, ("document.json",))
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

        else:
            raise KeyError(f"unknown manifest input kind={kind!r}")

    containers.sort(key=lambda c: c["logical_name"])

    return containers


# ----------------------------------------------------------------
# IDENTITY PAYLOAD - canonical serialization + freeze/reconstruct.
# ----------------------------------------------------------------


def _resolve_generation_provenance(row_key: str, with_agent: bool, llm_client):
    """(generation_mode, model_id, prompt_agent_version). `llm_client`
    yalnız test seam'idir (bkz. modül başlığı) - production caller'ı
    (ui.cli_mutate) bu parametreyi HİÇBİR ZAMAN geçirmez."""
    import importlib

    if not with_agent:
        return "deterministic", "deterministic_no_model", "n/a"

    agent_module = importlib.import_module(_AGENT_MODULE_NAME_BY_ROW_KEY[row_key])
    prompt_agent_version = getattr(agent_module, _AGENT_VERSION_ATTR_BY_ROW_KEY[row_key])

    if llm_client is not None:
        return "agent", "external_injected_client", prompt_agent_version

    model_id = agent_module.DEFAULT_AGENT_MODEL
    return "agent", model_id, prompt_agent_version


def _build_identity_payload(manifest, generation_mode, model_id, prompt_agent_version):
    return {
        "manifest_version": _MANIFEST_VERSION,
        "manifest": manifest,
        "generation_mode": generation_mode,
        "model_id": model_id,
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
class VerifiedGenerationOutputPaths:
    family_root: Path
    pending_path: Path
    history_dir: Path
    reviews_dir: Path
    carry_forward_dir: Path | None

    @property
    def identity(self):
        return (
            str(self.family_root), str(self.pending_path), str(self.history_dir),
            str(self.reviews_dir),
            str(self.carry_forward_dir) if self.carry_forward_dir is not None else None,
        )


def _derive_verified_output_paths(module, case_root_real: Path, case_id: str, row_key: str):
    raw_pending_path = module.get_pending_path(case_id)
    family_root = _verify_nested(module, case_root_real, case_id, raw_pending_path.parent)
    pending_path = _verify_nested(module, case_root_real, case_id, raw_pending_path)
    history_dir = _verify_nested(module, case_root_real, case_id, module.get_history_dir(case_id))
    reviews_dir = _verify_nested(module, case_root_real, case_id, module.get_reviews_dir(case_id))
    carry_forward_dir = None
    if row_key == "argument":
        carry_forward_dir = _verify_nested(
            module, case_root_real, case_id, module.get_carry_forward_dir(case_id),
        )
    return VerifiedGenerationOutputPaths(
        family_root=family_root, pending_path=pending_path, history_dir=history_dir,
        reviews_dir=reviews_dir, carry_forward_dir=carry_forward_dir,
    )


# ----------------------------------------------------------------
# COMPOSITE PRE-STATE SNAPSHOT (pending-conflict kontrolü) -
# `generation_mutation_facade._compute_generation_snapshot()`'ın AYNI
# formülü, `generation_mutation_adapters.py`'nin bağımsız kopyasıyla
# reconciliation sırasında YENİDEN İNŞA edilebilir olması için.
# ----------------------------------------------------------------

_SNAPSHOT_VERSION = "row19c3cii.agent_generation.v1"

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
# PENDING-FILE FROZEN-BYTE RECIPE (Blocker 3, önceki turlar) - beş
# writer'ın `atomic_write_json()`'ı ile BYTE-FOR-BYTE aynı: `newline=
# "\n"` (LF-only, os.linesep çevrimi YOK) + `json.dump(...,
# ensure_ascii=False, indent=2)` + tek bir trailing `"\n"`.
# ----------------------------------------------------------------


def _freeze_pending_bytes(analysis: dict) -> bytes:
    return json.dumps(analysis, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def _freeze_json_bytes(value) -> bytes:
    """`carry_records` gibi non-identity, non-pending yardımcı
    yapıların dondurulması için - canonical (sort_keys) DEĞİL, çünkü bu
    bytes hiçbir hash/karşılaştırma girdisi DEĞİLDİR, yalnız mutation-
    safety için bir freeze/reconstruct noktasıdır (Onay mesajı,
    Düzeltme B)."""
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


# ----------------------------------------------------------------
# WRITER/BUILDER DISPATCH - per-family çağrı şekli farklılıkları TEK
# noktada toplanır.
# ----------------------------------------------------------------


def _invoke_builder(row_key, module, case_id, *, use_agent, llm_client, network_allowed, lawyer_input=None):
    build_fn = getattr(module, _BUILD_FUNCTION_NAME_BY_ROW_KEY[row_key])
    if row_key == "argument":
        return build_fn(
            case_id, use_agent=use_agent, llm_client=llm_client, network_allowed=network_allowed,
            write_carry_forward_audit_enabled=False,
        )
    if row_key == "drafting":
        return build_fn(
            case_id, lawyer_input=lawyer_input, use_agent=use_agent, llm_client=llm_client,
            network_allowed=network_allowed,
        )
    return build_fn(case_id, use_agent=use_agent, llm_client=llm_client, network_allowed=network_allowed)


def _invoke_writer(
    row_key, module, case_id, candidate, build_result, *,
    verified_paths, input_digest, identity_payload,
    mutation_idempotency_key, mutation_resource_key, mutation_actor_ref,
    carry_records_for_write,
):
    common_kwargs = dict(
        verified_paths=verified_paths, input_digest=input_digest, identity_payload=identity_payload,
        mutation_idempotency_key=mutation_idempotency_key, mutation_resource_key=mutation_resource_key,
        mutation_actor_ref=mutation_actor_ref,
    )
    if row_key == "issue_spotting":
        return module.write_pending(case_id, candidate, **common_kwargs)
    if row_key == "evidence":
        return module.write_pending(case_id, candidate, build_result["issue_count"], **common_kwargs)
    if row_key == "argument":
        return module.write_pending(
            case_id, candidate, build_result["issue_count"],
            carried_ids=build_result["carried_ids"], carry_records=carry_records_for_write,
            **common_kwargs,
        )
    if row_key in ("risk_strategy", "drafting"):
        return module.write_pending(case_id, candidate, build_result["issue_count"], **common_kwargs)
    raise KeyError(f"unknown row_key={row_key!r}")


def _load_drafting_lawyer_input(case_id):
    """`ui.services.drafting_request.load_current_wrapper()`'ın (Row
    18C, LOCKED, DEĞİŞTİRİLMEDİ) raw wrapper'ından `lawyer_input` alt-
    nesnesini çıkarır. Bu, `ui/run_drafting_request.py --generate-
    pending`'in ZATEN yaptığı AYNI çağrı şekli - yalnız orası artık
    kapalı, bu facade AYNI kaynaktan okuyarak onun yerini alır."""
    from . import drafting_request as _drafting_request

    wrapper = _drafting_request.load_current_wrapper(case_id)
    if wrapper is None:
        return None
    return wrapper.get("lawyer_input")


# ----------------------------------------------------------------
# ARGÜMAN ŞEKİL KURALLARI - her I/O'dan önce.
# ----------------------------------------------------------------


def _check_argument_shapes(row_key: str, expected_input_digest=None, *, for_apply: bool):
    if row_key not in AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME:
        raise KeyError(f"row_key={row_key!r} is not a known agent-generation family")

    if for_apply and (
        not isinstance(expected_input_digest, str) or not expected_input_digest.strip()
    ):
        raise AgentGenerationArgumentError(
            "expected_input_digest apply için zorunlu, boş olamaz."
        )


# ----------------------------------------------------------------
# AUTHZ REPO / JOURNAL CONN KURULUMU - Layer A/promotion/generation
# facade'lerinin kendi desenlerinin bağımsız kopyaları.
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
    module = importlib.import_module(AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME[row_key])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "read", repository=repository,
        )

        case_root_real = _resolve_module_case_root_real(module, resolved_case_id)
        paths = _derive_verified_output_paths(module, case_root_real, resolved_case_id, row_key)

        manifest = _build_manifest_containers(row_key, case_root_real, resolved_case_id)
        generation_mode, model_id, prompt_agent_version = _resolve_generation_provenance(
            row_key, with_agent, llm_client,
        )
        identity_payload = _build_identity_payload(manifest, generation_mode, model_id, prompt_agent_version)
        identity_bytes = _canonical_identity_bytes(identity_payload)
        input_digest = _compute_input_digest(identity_bytes)

        return {
            "row_key": row_key,
            "case_id": resolved_case_id,
            "target_ref": agent_generation_target_ref_for(row_key),
            "input_digest": input_digest,
            "generation_mode": generation_mode,
            "model_id": model_id,
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
class AgentGenerationApplyResult:
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
        raise AgentGenerationInputContainmentError(
            "Generation reviews dizini listelenemedi."
        ) from error
    results = []
    for entry in raw_entries:
        if not fnmatch.fnmatch(entry.name, "*.generation_audit.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise AgentGenerationInputContainmentError(
                f"generation_reviews/{entry.name} containment doğrulamasından geçemedi."
            ) from error
        if resolved.parent != reviews_dir_verified:
            raise AgentGenerationInputContainmentError(
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
    paths: VerifiedGenerationOutputPaths, case_root_real: Path, *,
    action_family: str, journal_state: str, journal_id: int,
    idempotency_key: str, resource_key: str, observed_post_hash,
):
    """Completed safe-replay corroboration - yalnız `completed`
    durumdaki bir satırı YENİDEN DOĞRULAR (sonuç zaten BİLİNİYOR).
    Pre-state/post-state kanıtının TAMAMEN BAĞIMSIZ iki fonksiyona
    bölünmesi zorunluluğu bu fonksiyona değil, `agent_generation_
    mutation_adapters.py`'nin `gather_evidence()`'ına aittir - orada
    gerçek SONUÇ bilinmez (prepared/executing/reconciliation_required
    bir satır için)."""

    def fail(reason):
        raise AgentGenerationAuditBindingVerificationFailedError(
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
) -> AgentGenerationApplyResult:
    """SIRA: (1) argüman şekilleri (saf, I/O'suz); (2) DIŞ
    authorize_case_access('mutate'); (3) pre-lock manifest/identity +
    composite pending snapshot + expected_input_digest karşılaştırması;
    (4) DIŞ-LOCK build (deterministic veya agent, journal satırı
    OLMADAN); (5) frozen candidate/identity/carry_records; (6) conn +
    case lock; (7) run_mutation: İÇ otoriter authz -> journal gate ->
    idempotency -> precondition (SIFIRDAN kilit-altı taze re-derivation,
    byte-for-byte identity karşılaştırması; her red sıfır journal
    satırı) -> writer (verified paths + frozen candidate ÜZERİNDEN,
    HİÇBİR yeniden build/model çağrısı OLMADAN); (8) replay'de tam
    corroboration; (9) maskelemeyen temizlik."""
    import importlib

    _check_argument_shapes(row_key, expected_input_digest, for_apply=True)

    if allow_network and not with_agent:
        raise AgentGenerationArgumentError(
            "allow_network yalnız with_agent İLE BİRLİKTE anlamlıdır."
        )

    module = importlib.import_module(AGENT_GENERATION_ROW_KEY_TO_MODULE_NAME[row_key])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        outer_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )

        resource_key = _mutation_lock.case_resource_key(outer_resolved_case_id)
        action_family = agent_generation_action_family_for(row_key)
        target_ref = agent_generation_target_ref_for(row_key)

        pre_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
        pre_paths = _derive_verified_output_paths(module, pre_case_root, outer_resolved_case_id, row_key)

        pre_manifest = _build_manifest_containers(row_key, pre_case_root, outer_resolved_case_id)
        generation_mode, model_id, prompt_agent_version = _resolve_generation_provenance(
            row_key, with_agent, llm_client,
        )
        pre_identity_payload = _build_identity_payload(
            pre_manifest, generation_mode, model_id, prompt_agent_version,
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

        lawyer_input = None
        if row_key == "drafting":
            lawyer_input = _load_drafting_lawyer_input(outer_resolved_case_id)

        # DIŞ-LOCK BUILD - hiçbir journal satırı, hiçbir filesystem
        # mutasyonu (argument'ın kendi carry-forward audit'i DAHİL -
        # write_carry_forward_audit_enabled=False) bu noktada OLUŞMAZ.
        build_result = _invoke_builder(
            row_key, module, outer_resolved_case_id,
            use_agent=with_agent, llm_client=llm_client, network_allowed=allow_network,
            lawyer_input=lawyer_input,
        )
        analysis = build_result["analysis"]

        frozen_pending_bytes = _freeze_pending_bytes(analysis)

        frozen_carry_records_bytes = None
        if row_key == "argument":
            frozen_carry_records_bytes = _freeze_json_bytes(build_result.get("carry_records") or [])

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
                raise AgentGenerationResolvedCaseIdMismatchError(
                    f"outer authz {outer_resolved_case_id!r} çözdü, inner authz "
                    f"{inner_resolved_case_id!r} - reddedildi."
                )

        def precondition_callback() -> None:
            ul_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
            ul_paths = _derive_verified_output_paths(
                module, ul_case_root, outer_resolved_case_id, row_key,
            )
            if ul_paths.identity != pre_paths.identity:
                raise PreconditionRaceDetectedError(
                    "Bu generation isteği case kilidini beklerken ilgili dizin/dosyaların "
                    "çözümlenmiş (gerçek) konumu DEĞİŞTİ (link swap veya benzeri). İşlem iptal "
                    "edildi, HİÇBİR değişiklik yapılmadı."
                )

            ul_manifest = _build_manifest_containers(row_key, ul_case_root, outer_resolved_case_id)
            ul_identity_payload = _build_identity_payload(
                ul_manifest, generation_mode, model_id, prompt_agent_version,
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
            # mutable dict) bir daha KULLANILMAZ (Onay mesajı, Düzeltme A).
            under_lock_box["identity_payload_for_audit"] = json.loads(
                ul_identity_bytes.decode("utf-8")
            )

        def writer_callback() -> _mutation_coordinator.WriterResult:
            import io
            import contextlib

            ul_paths = under_lock_box["paths"]
            identity_payload_for_audit = under_lock_box["identity_payload_for_audit"]

            # Frozen bytes'tan TAZE reconstruction - build sırasında
            # üretilen `analysis`/`carry_records` referansları bir daha
            # KULLANILMAZ (Onay mesajı, Düzeltme A/B).
            candidate = json.loads(frozen_pending_bytes.decode("utf-8"))
            carry_records_for_write = None
            if row_key == "argument":
                carry_records_for_write = json.loads(frozen_carry_records_bytes.decode("utf-8"))

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
                    carry_records_for_write=carry_records_for_write,
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
                        module, replay_case_root, outer_resolved_case_id, row_key,
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
                except AgentGenerationInputContainmentError as error:
                    raise AgentGenerationAuditBindingVerificationFailedError(
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

            return AgentGenerationApplyResult(
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
