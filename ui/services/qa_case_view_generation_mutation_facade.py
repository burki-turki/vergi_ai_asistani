# ============================================================
# VERGİ AI - PHASE B (COMMIT A): QA / CASE-VIEW COORDINATED PENDING
# GENERATION MUTATION FACADE.
#
# Row 16 (QA, `qa_engine.build_qa_engine_output`) ve Row 17
# (Orchestrator, `orchestrator_engine.build_case_view`) için ilk RESMÎ
# pending publisher'ları mutation coordinator/journal altyapısına
# bağlayan, AYRI ve BAĞIMSIZ facade. Row 19A'nın "QA/Orchestrator
# pending-generation publisher'ları YOK" boşluğunu kapatır; önceki
# SEKİZ facade/adapter çiftinin (Layer A, Layer B, drafting_request,
# promotion, deterministic-generation, agent-generation,
# fact-extraction, legal_research/case_law) HİÇBİRİ GENİŞLETİLMEZ (repo
# emsali: her yeni kontrat şekli kendi facade+adapters çiftini alır).
#
# ACTION FAMILY'LER: `generation.qa` / `generation.case_view`
# (`target_ref` = `qa.pending` / `case_view.pending`, `target_state` =
# `generated`, `resource_key` = `case:<case_id>`). CLI-only (`python -m
# ui.cli_mutate generation --row-key qa|case_view ...`, MEVCUT
# `generation` namespace'inin additive genişlemesi); web mutasyon yüzeyi
# YOKTUR.
#
# SALT DETERMİNİSTİK - AGENT MODU YOKTUR: iki builder da saf, LLM'siz,
# network'süz fonksiyonlardır. `with_agent`/`allow_network` her iki
# row_key için, preview'da da apply'da da KOŞULSUZ reddedilir (pilot
# egress evreni GENİŞLETİLMEZ - `test_rag_pilot_egress_gate_isolated`'ın
# 8 üyelik `--with-agent` evreni bu iki aileyi İÇERMEZ ve içermemelidir).
# Bu facade'de `llm_client` DI seam'i BİLİNÇLİ olarak YOKTUR.
#
# IDENTITY: `input_digest`, containment-before-traversal bir manifest
# scanner'la (Row 19C-3c-ii disiplininin bağımsız kopyası - raw
# `Path.glob()`/`is_dir`/`is_file`/`exists`/`stat` KULLANILMAZ) kurulan
# `identity_payload` sözlüğünün canonical-bytes hash'idir. QA 12 logical
# container (case, documents, facts + 9 tek-dosyalı upstream scope),
# case_view 11 logical container (case + 9 tek-dosyalı scope + canonical
# qa.json) - bkz. `FAMILY_INPUT_SPECS`. Builder'ların KENDİ
# `analysis_metadata.dependency_manifest`'i identity OTORİTESİ DEĞİLDİR.
#
# CASE_VIEW ÖN KOŞULU (fail-closed): canonical `qa.json` MEVCUT ve
# `qa_validator.validate_qa_analysis()` ile GÜNCEL/GEÇERLİ olmak
# ZORUNDADIR (stale snapshot = red). Kontrol preview'da, apply'ın
# pre-lock aşamasında VE kilit altında ayrı ayrı yapılır; canonical
# qa.json'un ham-bayt hash'i `qa` container'ı üzerinden identity'ye
# BAĞLANIR. QA için `qa_generation_status == "aborted_source_changed"`
# bir pending ASLA yazılmaz; case_view için yalnız
# `generation_status == "completed"` yazılır.
#
# PORTABLE AUDIT (kullanıcı kararı, Phase B Commit A madde 4): iki
# writer'ın generation audit'indeki `history_backup_path` MUTLAK yol
# DEĞİL, repo-göreli canonical locator'dır (`data/cases/<case_id>/
# <qa|case_view>/history/<ad>`); adapter bu değeri yalnız DOĞRULANMIŞ
# history dizini altında, ada göre çözer.
#
# OS-LEVEL LINK-SWAP / TOCTOU: bu facade'in verified-path handoff'u
# doğrulama ile writer'ın gerçek `open()`/`os.replace()` syscall'ı
# arasındaki dar pencereyi ATOMİK OLARAK KAPATTIĞINI İDDİA ETMEZ - Row
# 19D (OS ACL / service identity) borcu olarak AÇIKÇA KALIR.
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
# Kapalı row_key -> writer modülü eşlemesi (önceki facade'lerin kendi
# sözlüklerinden BİLİNÇLİ AYRI).
# ----------------------------------------------------------------

QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME = {
    "qa": "qa_engine",
    "case_view": "orchestrator_engine",
}

_BUILD_FUNCTION_NAME_BY_ROW_KEY = {
    "qa": "build_qa_engine_output",
    "case_view": "build_case_view",
}

# Aile dizini adı (audit locator'ının `data/cases/<case_id>/<family_dir>/
# history/<ad>` biçimindeki sabit üçüncü segmenti) - adapter'ın kendi
# bağımsız kopyası bu değeri yeniden türetir.
FAMILY_DIR_BY_ROW_KEY = {
    "qa": "qa",
    "case_view": "case_view",
}

_ACTION_FAMILY_PREFIX = "generation."

_CASE_RESOURCE_KEY_PREFIX = "case:"

TARGET_STATE = "generated"

CHANNEL = "local_lawyer_generation_cli"

# Salt deterministik provenance sentinel'leri - Row 19C-3c-ii'nin
# deterministic-mode sentinel'leriyle AYNI literal'ler (bir okuyucu
# "deterministic_no_model" gördüğünde aileden bağımsız aynı anlamı
# çıkarır).
GENERATION_MODE = "deterministic"

MODEL_ID = "deterministic_no_model"

PROMPT_AGENT_VERSION = "n/a"

_MANIFEST_VERSION = "phaseb.qa_case_view_generation.v1"

_logger = logging.getLogger("vergi_ai.qa_case_view_generation_mutation_facade")


def _log_critical_safely(message: str) -> None:
    try:
        _logger.critical(message)
    except Exception:
        pass


def qa_case_view_generation_action_family_for(row_key: str) -> str:
    """`generation.<row_key>` - hem bu modülün MutationIntent'i hem
    `qa_case_view_generation_mutation_adapters.register_into()` BU
    fonksiyonu çağırır; iki taraf farklı string'lere kayamaz."""
    return f"{_ACTION_FAMILY_PREFIX}{row_key}"


def qa_case_view_generation_target_ref_for(row_key: str) -> str:
    return f"{row_key}.pending"


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ----------------------------------------------------------------
# Hata sınıfları - HEPSİ `ApprovalUiError` alt sınıfı (ui.cli_mutate'in
# mevcut, DEĞİŞTİRİLMEMİŞ domain-error tanıma mekanizması bunları
# otomatik tanır).
# ----------------------------------------------------------------


class QaCaseViewGenerationArgumentError(ApprovalUiError):
    """Kullanım-şekli/argüman sözleşmesi ihlali - HERHANGİ bir DB/
    filesystem I/O'sundan ÖNCE fırlatılır."""


class QaCaseViewGenerationAgentModeRefusedError(QaCaseViewGenerationArgumentError):
    """PHASE B: bu iki aile SALT deterministiktir - `with_agent`/
    `allow_network` KOŞULSUZ reddedilir (preview VE apply). Pilot egress
    evreni bu facade ile GENİŞLEMEZ."""


class QaCaseViewGenerationInputContainmentError(ApprovalUiError):
    """Writer-root/nested/girdi-taraması containment doğrulaması
    başarısız (kaçan/kırık/döngüsel link, kök doğrulanamadı, in-tree
    alias, geçersiz segment adı, gerekli girdi eksik)."""


class QaCaseViewGenerationResolvedCaseIdMismatchError(ApprovalUiError):
    """İç (kilit-altı) authz'ın çözdüğü case_id, dış (pre-lock)
    authz'ınkinden farklı."""


class QaCaseViewGenerationAuditBindingVerificationFailedError(ApprovalUiError):
    """Safe-replay corroboration başarısız - insan reconciliation'ı
    gerekir."""

    def __init__(self, *, journal_id: int, idempotency_key: str, reason: str):
        self.journal_id = journal_id
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(
            f"journal_id={journal_id}: qa/case_view generation safe-replay audit-binding "
            f"verification failed (idempotency_key={idempotency_key!r}): {reason}"
        )


class CaseViewQaPrerequisiteError(ApprovalUiError):
    """case_view üretimi için canonical `qa.json` YOK veya
    `qa_validator` ile GÜNCEL/GEÇERLİ DEĞİL (stale snapshot dahil) -
    fail-closed red, sıfır journal satırı, sıfır yazım."""


class QaGenerationAbortedError(ApprovalUiError):
    """QA taraması sırasında kaynak değişti (`qa_generation_status ==
    aborted_source_changed`) - pending ASLA yazılmaz."""


class CaseViewGenerationIncompleteError(ApprovalUiError):
    """Orchestrator `generation_status != "completed"` üretti (eksik
    zorunlu kaynak) - pending ASLA yazılmaz (Layer A da 'failed'i
    reddederdi; burada yazım bile yapılmaz)."""


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
        raise QaCaseViewGenerationInputContainmentError(
            "Generation case kökü containment doğrulamasından geçemedi."
        ) from error


def _verify_nested(module, case_root_real: Path, case_id: str, raw_path) -> Path:
    cases_dir = module.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise QaCaseViewGenerationInputContainmentError(
            "Generation yolu beklenen case kapsamı dışında."
        ) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise QaCaseViewGenerationInputContainmentError(
            "Generation yolu containment doğrulamasından geçemedi."
        ) from error


# ----------------------------------------------------------------
# CONTAINMENT-BEFORE-TRAVERSAL MANIFEST SCANNER (Row 19C-3c-ii
# disiplininin bağımsız kopyası - raw glob/is_dir/is_file/exists/stat
# HİÇBİR YERDE bir pre-gate olarak kullanılmaz; missing/broken/looping/
# escaping ayrımı `os.path.lexists()` + `resolve_existing()` ile yapılır;
# logical_relative_path DOĞRULANMIŞ SEGMENT ADLARINDAN kurulur).
# ----------------------------------------------------------------


def _scan_single_file(case_root_real: Path, segments, logical_name: str, *, required: bool):
    current_real = case_root_real

    for index, seg in enumerate(segments):
        try:
            _path_containment.validate_segment(seg)
        except _path_containment.PathContainmentError as error:
            raise QaCaseViewGenerationInputContainmentError(
                f"{logical_name}: geçersiz segment adı {seg!r}"
            ) from error

        raw_candidate = current_real / seg

        if not os.path.lexists(raw_candidate):
            if required:
                raise QaCaseViewGenerationInputContainmentError(
                    f"required input missing: {logical_name}"
                )
            return {"logical_name": logical_name, "state": "missing", "files": []}

        try:
            seg_real = _path_containment.resolve_existing(raw_candidate, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise QaCaseViewGenerationInputContainmentError(
                f"{logical_name}: containment doğrulamasından geçemedi (kaçan/kırık/döngüsel "
                "giriş)."
            ) from error

        if seg_real.parent != current_real:
            raise QaCaseViewGenerationInputContainmentError(
                f"{logical_name}: beklenen dizinin doğrudan çocuğu değil (in-tree alias)."
            )

        is_last = index == len(segments) - 1

        if is_last:
            if not seg_real.is_file():
                raise QaCaseViewGenerationInputContainmentError(
                    f"{logical_name}: güvenli-fakat-normal-dosya değil."
                )
        else:
            if not seg_real.is_dir():
                if required:
                    raise QaCaseViewGenerationInputContainmentError(
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


def _scan_verified_leaf_chain(case_root_real: Path, documents_dir_real: Path, leaf_segments):
    """`documents/<name>/<leaf_segments...>` zincirini segment-segment
    tarar. Dönüş: `[(logical_relative_path, resolved_path), ...]`,
    `logical_relative_path` ile sıralı. Duplicate resolved path TÜM
    taramayı fail-closed durdurur."""
    try:
        raw_entries = sorted(documents_dir_real.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise QaCaseViewGenerationInputContainmentError(
            "documents/ dizini listelenemedi."
        ) from error

    results = []

    for entry in raw_entries:
        name = entry.name

        try:
            _path_containment.validate_segment(name)
        except _path_containment.PathContainmentError as error:
            raise QaCaseViewGenerationInputContainmentError(
                f"documents/ altında geçersiz segment adı: {name!r}"
            ) from error

        try:
            entry_real = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise QaCaseViewGenerationInputContainmentError(
                f"documents/{name} containment doğrulamasından geçemedi "
                "(kaçan/kırık/döngüsel giriş)."
            ) from error

        if entry_real.parent != documents_dir_real:
            raise QaCaseViewGenerationInputContainmentError(
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
                raise QaCaseViewGenerationInputContainmentError(
                    f"documents/{name}/{'/'.join(leaf_segments[:index+1])} containment "
                    "doğrulamasından geçemedi (kaçan/kırık/döngüsel giriş)."
                ) from error
            if seg_real.parent != current_real:
                raise QaCaseViewGenerationInputContainmentError(
                    f"documents/{name}/{'/'.join(leaf_segments[:index+1])} beklenen dizinin "
                    "doğrudan çocuğu değil (in-tree alias)."
                )
            is_last = index == len(leaf_segments) - 1
            if is_last:
                if not seg_real.is_file():
                    raise QaCaseViewGenerationInputContainmentError(
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
        raise QaCaseViewGenerationInputContainmentError(
            "documents/ taramasında duplicate/alias çözümlenmiş yol tespit edildi."
        )

    return sorted(results, key=lambda pair: pair[0])


# ----------------------------------------------------------------
# 12/11 SABİT LOGICAL-INPUT SPESİFİKASYONLARI.
#
# Her giriş: (logical_name, kind, extra).
#   kind == "single"     -> (segments, required)
#   kind == "leaf_chain" -> (leaf_segments,) - documents/*/<leaf...>;
#                            documents/ dizini yoksa state="missing"
#                            (QA'nın kendisi de belge üyeliği olmadan
#                            çalışabilir - fail-closed red builder'ın
#                            kendi qa_generation_status'ünde yaşar).
# ----------------------------------------------------------------

FAMILY_INPUT_SPECS = {
    "qa": [
        ("case", "single", (("case.json",), True)),
        ("documents", "leaf_chain", (("document.json",),)),
        ("facts", "leaf_chain", (("extractions", "facts.json"),)),
        ("timeline", "single", (("timeline", "timeline.json"), False)),
        ("deadline", "single", (("deadlines", "deadline.json"), False)),
        ("issues", "single", (("issues", "issues.json"), False)),
        ("legal_research", "single", (("research", "research.json"), False)),
        ("case_law", "single", (("case_law", "case_law.json"), False)),
        ("evidence", "single", (("evidence", "evidence.json"), False)),
        ("arguments", "single", (("arguments", "arguments.json"), False)),
        ("risk_strategy", "single", (("risk_strategy", "risk_strategy.json"), False)),
        ("drafting", "single", (("drafting", "drafting.json"), False)),
    ],
    "case_view": [
        ("case", "single", (("case.json",), True)),
        ("timeline", "single", (("timeline", "timeline.json"), False)),
        ("deadline", "single", (("deadlines", "deadline.json"), False)),
        ("issues", "single", (("issues", "issues.json"), False)),
        ("legal_research", "single", (("research", "research.json"), False)),
        ("case_law", "single", (("case_law", "case_law.json"), False)),
        ("evidence", "single", (("evidence", "evidence.json"), False)),
        ("arguments", "single", (("arguments", "arguments.json"), False)),
        ("risk_strategy", "single", (("risk_strategy", "risk_strategy.json"), False)),
        ("drafting", "single", (("drafting", "drafting.json"), False)),
        ("qa", "single", (("qa", "qa.json"), False)),
    ],
}

FAMILY_LOGICAL_NAME_COUNTS = {row_key: len(spec) for row_key, spec in FAMILY_INPUT_SPECS.items()}

_QA_CANONICAL_SEGMENTS = ("qa", "qa.json")


def _build_manifest_containers(row_key: str, case_root_real: Path, case_id: str):
    spec = FAMILY_INPUT_SPECS[row_key]

    documents_dir_box = {"resolved": False, "value": None}

    def get_documents_dir_real():
        """`documents/` dizini yoksa None (soft); varsa containment-
        doğrulanmış gerçek dizin; kaçan/kırık/döngüsel ise raise."""
        if not documents_dir_box["resolved"]:
            raw_documents_dir = case_root_real / "documents"
            if not os.path.lexists(raw_documents_dir):
                documents_dir_box["value"] = None
            else:
                try:
                    resolved = _path_containment.resolve_existing(raw_documents_dir, root=case_root_real)
                except _path_containment.PathContainmentError as error:
                    raise QaCaseViewGenerationInputContainmentError(
                        "documents/ containment doğrulamasından geçemedi (kaçan/kırık/döngüsel giriş)."
                    ) from error
                if resolved.parent != case_root_real:
                    raise QaCaseViewGenerationInputContainmentError(
                        "documents/ beklenen dizinin doğrudan çocuğu değil (in-tree alias)."
                    )
                if not resolved.is_dir():
                    raise QaCaseViewGenerationInputContainmentError(
                        "documents/ güvenli-fakat-dizin-değil."
                    )
                documents_dir_box["value"] = resolved
            documents_dir_box["resolved"] = True
        return documents_dir_box["value"]

    containers = []

    for logical_name, kind, extra in spec:

        if kind == "single":
            segments, required = extra
            containers.append(_scan_single_file(case_root_real, segments, logical_name, required=required))

        elif kind == "leaf_chain":
            (leaf_segments,) = extra
            docs_dir = get_documents_dir_real()
            if docs_dir is None:
                containers.append({"logical_name": logical_name, "state": "missing", "files": []})
                continue
            entries = _scan_verified_leaf_chain(case_root_real, docs_dir, leaf_segments)
            containers.append({
                "logical_name": logical_name,
                "state": "present" if entries else "empty",
                "files": [
                    {"logical_relative_path": rel, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                    for rel, path in entries
                ],
            })

        else:
            raise KeyError(f"unknown manifest input kind={kind!r}")

    containers.sort(key=lambda c: c["logical_name"])

    return containers


# ----------------------------------------------------------------
# IDENTITY PAYLOAD - canonical serialization + freeze/reconstruct.
# ----------------------------------------------------------------


def _build_identity_payload(manifest):
    return {
        "manifest_version": _MANIFEST_VERSION,
        "manifest": manifest,
        "generation_mode": GENERATION_MODE,
        "model_id": MODEL_ID,
        "prompt_agent_version": PROMPT_AGENT_VERSION,
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
class VerifiedQaCaseViewOutputPaths:
    family_root: Path
    pending_path: Path
    history_dir: Path
    reviews_dir: Path

    @property
    def identity(self):
        return (
            str(self.family_root), str(self.pending_path), str(self.history_dir),
            str(self.reviews_dir),
        )


def _derive_verified_output_paths(module, case_root_real: Path, case_id: str):
    raw_pending_path = module.get_pending_path(case_id)
    family_root = _verify_nested(module, case_root_real, case_id, raw_pending_path.parent)
    pending_path = _verify_nested(module, case_root_real, case_id, raw_pending_path)
    history_dir = _verify_nested(module, case_root_real, case_id, module.get_history_dir(case_id))
    reviews_dir = _verify_nested(module, case_root_real, case_id, module.get_reviews_dir(case_id))
    return VerifiedQaCaseViewOutputPaths(
        family_root=family_root, pending_path=pending_path, history_dir=history_dir,
        reviews_dir=reviews_dir,
    )


# ----------------------------------------------------------------
# CASE_VIEW ÖN KOŞULU - canonical qa.json MEVCUT + GÜNCEL/GEÇERLİ.
# ----------------------------------------------------------------


def _verified_existing_file_or_none(case_root_real: Path, segments):
    """Segment-segment containment-doğrulanmış mevcut dosya; hiç yoksa
    None; kaçan/kırık/döngüsel/alias ise raise."""
    current_real = case_root_real
    for index, seg in enumerate(segments):
        raw_candidate = current_real / seg
        if not os.path.lexists(raw_candidate):
            return None
        try:
            seg_real = _path_containment.resolve_existing(raw_candidate, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise QaCaseViewGenerationInputContainmentError(
                f"{'/'.join(segments[:index+1])}: containment doğrulamasından geçemedi."
            ) from error
        if seg_real.parent != current_real:
            raise QaCaseViewGenerationInputContainmentError(
                f"{'/'.join(segments[:index+1])}: in-tree alias."
            )
        is_last = index == len(segments) - 1
        if is_last:
            if not seg_real.is_file():
                raise QaCaseViewGenerationInputContainmentError(
                    f"{'/'.join(segments)}: güvenli-fakat-normal-dosya değil."
                )
        elif not seg_real.is_dir():
            return None
        current_real = seg_real
    return current_real


def _check_case_view_qa_prerequisite(case_root_real: Path, case_id: str) -> str:
    """case_view: canonical `qa.json` mevcut VE `qa_validator` ile
    güncel/geçerli olmak ZORUNDADIR (stale snapshot = red). Dönüş:
    canonical qa.json'un ham-bayt SHA-256'sı (identity'ye ayrıca `qa`
    container'ı üzerinden girer). `qa_validator` fonksiyon-içi import
    edilir (modül başında `qa_engine`'i import eder)."""
    import importlib

    qa_path = _verified_existing_file_or_none(case_root_real, _QA_CANONICAL_SEGMENTS)
    if qa_path is None:
        raise CaseViewQaPrerequisiteError(
            "case_view üretimi için canonical qa.json MEVCUT DEĞİL - önce `generation --row-key qa` "
            "ile pending QA üretilip Layer A (`approval --row-key qa`) ile onaylanmalıdır. İşlem "
            "iptal edildi, HİÇBİR değişiklik yapılmadı."
        )

    qa_validator = importlib.import_module("qa_validator")
    try:
        validation = qa_validator.validate_qa_analysis(
            qa_path, expected_case_id=case_id, raise_on_error=False,
        )
    except Exception as error:  # noqa: BLE001 - fail-closed sınıflandırma
        raise CaseViewQaPrerequisiteError(
            "case_view üretimi için canonical qa.json DOĞRULANAMADI (okuma/parse hatası). İşlem "
            "iptal edildi, HİÇBİR değişiklik yapılmadı."
        ) from error

    if validation.get("valid") is not True:
        errors = validation.get("errors") or []
        raise CaseViewQaPrerequisiteError(
            "case_view üretimi için canonical qa.json GÜNCEL/GEÇERLİ DEĞİL (stale snapshot veya "
            f"validator hatası; {len(errors)} hata) - önce QA yeniden üretilip onaylanmalıdır. "
            "İşlem iptal edildi, HİÇBİR değişiklik yapılmadı."
        )

    return hashlib.sha256(qa_path.read_bytes()).hexdigest()


# ----------------------------------------------------------------
# COMPOSITE PRE-STATE SNAPSHOT (pending-conflict kontrolü) - adapters
# kendi bağımsız kopyasıyla YENİDEN İNŞA eder.
# ----------------------------------------------------------------

_SNAPSHOT_VERSION = "phaseb.qa_case_view_generation.snapshot.v1"

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
# PENDING-FILE FROZEN-BYTE RECIPE - iki writer'ın `atomic_write_json()`
# tarifiyle aynı (`ensure_ascii=False, indent=2` + tek trailing LF).
# ----------------------------------------------------------------


def _freeze_pending_bytes(analysis: dict) -> bytes:
    return json.dumps(analysis, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


# ----------------------------------------------------------------
# BUILDER DISPATCH + fail-closed sonuç kapıları.
# ----------------------------------------------------------------


def _invoke_builder(row_key, module, case_id):
    build_fn = getattr(module, _BUILD_FUNCTION_NAME_BY_ROW_KEY[row_key])
    analysis = build_fn(case_id)
    if not isinstance(analysis, dict):
        raise QaCaseViewGenerationArgumentError(
            f"{row_key} builder beklenmeyen bir sonuç türü döndürdü."
        )
    if row_key == "qa":
        if analysis.get("qa_generation_status") == "aborted_source_changed":
            raise QaGenerationAbortedError(
                "QA taraması sırasında kaynak değişti (qa_generation_status="
                "aborted_source_changed) - pending üretimi fail-closed reddedildi. İşlem iptal "
                "edildi, HİÇBİR değişiklik yapılmadı."
            )
    elif row_key == "case_view":
        if analysis.get("generation_status") != "completed":
            raise CaseViewGenerationIncompleteError(
                "Orchestrator generation_status='completed' üretmedi (bir veya daha fazla zorunlu "
                f"kaynak eksik; generation_status={analysis.get('generation_status')!r}) - pending "
                "üretimi fail-closed reddedildi. İşlem iptal edildi, HİÇBİR değişiklik yapılmadı."
            )
    return analysis


# ----------------------------------------------------------------
# ARGÜMAN ŞEKİL KURALLARI - her I/O'dan önce.
# ----------------------------------------------------------------


def agent_mode_refusal_message(row_key: str) -> str:
    """SABİT ret metni (tek otorite - facade burada fırlatır,
    `ui.cli_mutate` kendi usage-shape katmanında AYNI fonksiyonu
    çağırır). Hiçbir path/exception/case verisi yansıtmaz."""
    return (
        f"HATA: --row-key {row_key} için agent modu YOKTUR (Phase B): bu aile salt "
        "deterministiktir - --with-agent/--allow-network preview'da da apply'da da kabul edilmez."
    )


def _check_argument_shapes(
    row_key: str,
    expected_input_digest=None,
    *,
    for_apply: bool,
    with_agent: bool = False,
    allow_network: bool = False,
):
    """Saf, I/O'suz. Bilinmeyen row_key `KeyError`; `with_agent`/
    `allow_network` KOŞULSUZ ret (DI seam muafiyeti YOKTUR - bu ailede
    agent kodu hiç yoktur); apply için boş olmayan
    `expected_input_digest` zorunlu."""
    if row_key not in QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME:
        raise KeyError(f"row_key={row_key!r} is not a known qa/case_view generation family")

    if with_agent or allow_network:
        raise QaCaseViewGenerationAgentModeRefusedError(agent_mode_refusal_message(row_key))

    if for_apply and (
        not isinstance(expected_input_digest, str) or not expected_input_digest.strip()
    ):
        raise QaCaseViewGenerationArgumentError(
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


def _derive_identity(row_key, module, case_root_real, case_id):
    """(paths, manifest, identity_payload, identity_bytes, input_digest)
    - case_view için ön koşul kapısı manifest'ten SONRA, identity'den
    ÖNCE çalışır (qa container'ı zaten manifest içindedir)."""
    paths = _derive_verified_output_paths(module, case_root_real, case_id)
    manifest = _build_manifest_containers(row_key, case_root_real, case_id)
    if row_key == "case_view":
        _check_case_view_qa_prerequisite(case_root_real, case_id)
    identity_payload = _build_identity_payload(manifest)
    identity_bytes = _canonical_identity_bytes(identity_payload)
    input_digest = _compute_input_digest(identity_bytes)
    return paths, manifest, identity_payload, identity_bytes, input_digest


# ----------------------------------------------------------------
# PREVIEW (salt-okunur; builder ÇAĞRILMAZ, network yok)
# ----------------------------------------------------------------


def preview_generation(
    row_key: str,
    case_id: str,
    *,
    with_agent: bool = False,
    allow_network: bool = False,
    principal,
    authz_repository=None,
):
    """Salt-okunur preview. SIRA: argüman şekilleri -> dış 'read' authz
    (HER filesystem probundan ÖNCE) -> manifest/identity (+ case_view
    ön koşulu)."""
    _check_argument_shapes(
        row_key, for_apply=False, with_agent=with_agent, allow_network=allow_network,
    )
    import importlib
    module = importlib.import_module(QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME[row_key])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "read", repository=repository,
        )

        case_root_real = _resolve_module_case_root_real(module, resolved_case_id)
        paths, _manifest, _identity_payload, _identity_bytes, input_digest = _derive_identity(
            row_key, module, case_root_real, resolved_case_id,
        )

        return {
            "row_key": row_key,
            "case_id": resolved_case_id,
            "target_ref": qa_case_view_generation_target_ref_for(row_key),
            "input_digest": input_digest,
            "generation_mode": GENERATION_MODE,
            "model_id": MODEL_ID,
            "prompt_agent_version": PROMPT_AGENT_VERSION,
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
class QaCaseViewGenerationApplyResult:
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
    if record.get("channel") != CHANNEL:
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
        raise QaCaseViewGenerationInputContainmentError(
            "Generation reviews dizini listelenemedi."
        ) from error
    results = []
    for entry in raw_entries:
        if not fnmatch.fnmatch(entry.name, "*.generation_audit.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise QaCaseViewGenerationInputContainmentError(
                f"generation_reviews/{entry.name} containment doğrulamasından geçemedi."
            ) from error
        if resolved.parent != reviews_dir_verified:
            raise QaCaseViewGenerationInputContainmentError(
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
    paths: VerifiedQaCaseViewOutputPaths, case_root_real: Path, *,
    action_family: str, journal_state: str, journal_id: int,
    idempotency_key: str, resource_key: str, observed_post_hash,
):
    """Completed safe-replay corroboration - yalnız `completed`
    durumdaki bir satırı YENİDEN DOĞRULAR. Tam pre/post bağımsız kanıt
    adapters'ın `gather_evidence()`'ına aittir."""

    def fail(reason):
        raise QaCaseViewGenerationAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key, reason=reason,
        )

    if journal_state != "completed":
        fail(f"journal_state={journal_state!r} beklenen 'completed' değil")

    current_pending_sha256 = sha256_file(paths.pending_path)
    if current_pending_sha256 is None:
        fail("pending artefakt şu an mevcut değil")
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
    principal,
    authz_repository=None,
    conn_factory=None,
) -> QaCaseViewGenerationApplyResult:
    """SIRA: (1) argüman şekilleri (saf, I/O'suz; agent/network koşulsuz
    ret); (2) DIŞ authorize_case_access('mutate'); (3) pre-lock
    manifest/identity (+ case_view ön koşulu) + composite pending
    snapshot + expected_input_digest karşılaştırması; (4) DIŞ-LOCK
    deterministik build (journal satırı OLMADAN; aborted/incomplete
    sonuç burada fail-closed reddedilir); (5) frozen candidate/identity;
    (6) conn + case lock; (7) run_mutation: İÇ otoriter authz -> journal
    gate -> idempotency -> precondition (SIFIRDAN kilit-altı taze
    re-derivation, byte-for-byte identity karşılaştırması, case_view ön
    koşulunun yeniden kontrolü; her red sıfır journal satırı) -> writer
    (verified paths + frozen candidate ÜZERİNDEN, yeniden build OLMADAN);
    (8) replay'de corroboration; (9) maskelemeyen temizlik."""
    import importlib

    _check_argument_shapes(
        row_key, expected_input_digest, for_apply=True,
        with_agent=with_agent, allow_network=allow_network,
    )

    module = importlib.import_module(QA_CASE_VIEW_GENERATION_ROW_KEY_TO_MODULE_NAME[row_key])

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        outer_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )

        resource_key = _mutation_lock.case_resource_key(outer_resolved_case_id)
        action_family = qa_case_view_generation_action_family_for(row_key)
        target_ref = qa_case_view_generation_target_ref_for(row_key)

        pre_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
        pre_paths, _pre_manifest, _pre_identity_payload, pre_identity_bytes, input_digest = _derive_identity(
            row_key, module, pre_case_root, outer_resolved_case_id,
        )

        if input_digest != expected_input_digest:
            raise StaleViewError(
                "Preview alındıktan sonra girdi içeriği DEĞİŞTİ "
                f"(beklenen input_digest: {expected_input_digest}, şimdiki: {input_digest}). "
                "İşlem iptal edildi, HİÇBİR değişiklik yapılmadı."
            )

        pre_pending_snapshot = _compute_pending_snapshot(input_digest, pre_paths.pending_path)

        # DIŞ-LOCK BUILD - saf, deterministik; hiçbir journal satırı,
        # hiçbir filesystem mutasyonu bu noktada OLUŞMAZ.
        analysis = _invoke_builder(row_key, module, outer_resolved_case_id)

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
                raise QaCaseViewGenerationResolvedCaseIdMismatchError(
                    f"outer authz {outer_resolved_case_id!r} çözdü, inner authz "
                    f"{inner_resolved_case_id!r} - reddedildi."
                )

        def precondition_callback() -> None:
            ul_case_root = _resolve_module_case_root_real(module, outer_resolved_case_id)
            ul_paths, _ul_manifest, _ul_identity_payload, ul_identity_bytes, _ul_digest = _derive_identity(
                row_key, module, ul_case_root, outer_resolved_case_id,
            )
            if ul_paths.identity != pre_paths.identity:
                raise PreconditionRaceDetectedError(
                    "Bu generation isteği case kilidini beklerken ilgili dizin/dosyaların "
                    "çözümlenmiş (gerçek) konumu DEĞİŞTİ (link swap veya benzeri). İşlem iptal "
                    "edildi, HİÇBİR değişiklik yapılmadı."
                )

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
            # TAZE json.loads() ile üretilir.
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
                write_result = module.write_pending(
                    outer_resolved_case_id, candidate,
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
                except QaCaseViewGenerationInputContainmentError as error:
                    raise QaCaseViewGenerationAuditBindingVerificationFailedError(
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

            return QaCaseViewGenerationApplyResult(
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
