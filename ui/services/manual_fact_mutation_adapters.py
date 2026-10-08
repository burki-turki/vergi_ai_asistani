# ============================================================
# VERGİ AI - ADIM 10 B YOLU: MANUEL FACT GİRİŞİ RECONCILIATION ADAPTER
# (`generation.fact_manual`).
#
# `reconciliation_operator._default_registry_factory()`'nin 12. kaynağı
# (10 approval + 24 review + 1 drafting_request + 2 promotion + 2
# generation + 5 agent generation + 1 fact_extraction + 2 legal_research/
# case_law + 2 rag_bundle + 1 verification.fact + 2 qa/case_view + 1
# fact_manual = 53 routing key).
#
# BAĞIMSIZ KANIT İLKESİ: bu modül facade'in karar/doğrulama
# fonksiyonlarını İMPORT ETMEZ. Containment, kimlik formülleri ve audit
# eşleşmesi burada BAĞIMSIZ İKİNCİ implementasyondur (izole canary testi
# iki implementasyonun aynı girdide aynı sonucu verdiğini kanıtlar).
#
# PRE-STATE: yalnız `entry.pre_hash`, OPAK `entry.pre_revision` (asla
# yeniden inşa edilmez) ve containment-doğrulanmış pending varlığı/sha'sı.
# JSON parse etmez, audit taramaz, girdi okumaz.
#
# POST-STATE: pending normal dosya + `generation_reviews/
# *.generation_audit.json` içinde TAM bağlamalı TEK bir audit:
# schema_version, case_id, document_id, target_ref, target_state,
# action_family, channel, mutation_actor_ref, mutation_idempotency_key,
# mutation_resource_key, pending_sha256 (== güncel pending), outcome,
# identity_payload'tan yeniden hesaplanan input_digest, ve audit'teki
# `(input_digest, attempt)`'ten yeniden hesaplanan composite ==
# `entry.pre_revision` (LLM adapter'ının literal `input_digest ==
# pre_revision` kontrolü bu ailede composite karşılığıyla değiştirilir).
# Ayrıştırılamayan HERHANGİ bir aday post-state'i False yapar (K-13).
#
# N-M1 yazım sırasıyla çöküş hücreleri: temp-yalnız -> pre=True ->
# failed; audit var / pending yok -> pre=True -> failed; audit var /
# pending var -> post=True -> completed.
# ============================================================

from __future__ import annotations

import fnmatch
import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import path_containment as _path_containment  # noqa: E402

from . import mutation_registry as mr
from .manual_fact_mutation_facade import ACTION_FAMILY, ENGINE_MODULE_NAME

_DUAL_FALSE = mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

# Facade formüllerinin BAĞIMSIZ kopyaları - facade'in literalleriyle
# BİREBİR aynı olmak ZORUNDADIR (F-N12 canary).
_REVISION_VERSION = "step10b.fact_manual_revision.v1"
_SNAPSHOT_VERSION = "step10b.fact_manual.snapshot.v1"
_SNAPSHOT_ABSENT = "__absent__"
_SNAPSHOT_PRESENT = "__present__"
_CHANNEL = "local_lawyer_manual_fact_cli"
_TARGET_STATE = "generated"
_TARGET_REF_PREFIX = "fact."
_TARGET_REF_SUFFIX = ".pending"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


class _ContainmentUnwind(Exception):
    """İç sinyal - modül sınırını aşmaz."""


def _canonical_bytes(payload) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def candidate_pre_revision(input_digest: str, attempt: int) -> str:
    return hashlib.sha256(_canonical_bytes({
        "revision_version": _REVISION_VERSION,
        "input_digest": input_digest,
        "attempt": attempt,
    })).hexdigest()


def candidate_pre_hash(pre_revision: str, pending_sha):
    presence = _SNAPSHOT_PRESENT if pending_sha is not None else _SNAPSHOT_ABSENT
    return hashlib.sha256(_canonical_bytes({
        "snapshot_version": _SNAPSHOT_VERSION,
        "pre_revision": pre_revision,
        "pending_presence": presence,
        "pending_sha256": pending_sha if pending_sha is not None else _SNAPSHOT_ABSENT,
    })).hexdigest()


def _parse_document_id(target_ref):
    if not isinstance(target_ref, str):
        return None
    if not target_ref.startswith(_TARGET_REF_PREFIX) or not target_ref.endswith(_TARGET_REF_SUFFIX):
        return None
    middle = target_ref[len(_TARGET_REF_PREFIX):-len(_TARGET_REF_SUFFIX)]
    if not middle:
        return None
    try:
        _path_containment.validate_segment(middle)
    except _path_containment.PathContainmentError:
        return None
    return middle


def _child(current_real: Path, seg: str, root_real: Path) -> Path | None:
    """Var olmayan -> None; var olan -> containment + parent/ad eşitliği
    zorunlu (aksi halde unwind)."""
    try:
        _path_containment.validate_segment(seg)
    except _path_containment.PathContainmentError as error:
        raise _ContainmentUnwind() from error
    raw = current_real / seg
    if not os.path.lexists(raw):
        return None
    try:
        real = _path_containment.resolve_existing(raw, root=root_real)
    except _path_containment.PathContainmentError as error:
        raise _ContainmentUnwind() from error
    if real.parent != current_real or real.name != seg:
        raise _ContainmentUnwind()
    return real


def _locate(module, case_id: str, document_id: str):
    cases_dir = module.CASES_DIR
    try:
        _path_containment.validate_segment(case_id)
        case_root = _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise _ContainmentUnwind() from error
    current = case_root
    for seg in ("documents", document_id, "extractions"):
        nxt = _child(current, seg, case_root)
        if nxt is None:
            return case_root, None, None
        if not nxt.is_dir():
            raise _ContainmentUnwind()
        current = nxt
    extractions = current
    reviews = _child(extractions, module.GENERATION_REVIEWS_DIRNAME, case_root)
    if reviews is not None and not reviews.is_dir():
        raise _ContainmentUnwind()
    return case_root, extractions, reviews


def _pending_sha(case_root: Path, extractions, module):
    """(sha | None). Mevcut ama normal dosya olmayan / alias pending ->
    unwind."""
    if extractions is None:
        return None
    pending = _child(extractions, module.CURRENT_PENDING_FILENAME, case_root)
    if pending is None:
        return None
    if not pending.is_file():
        raise _ContainmentUnwind()
    try:
        return hashlib.sha256(pending.read_bytes()).hexdigest()
    except OSError as error:
        raise _ContainmentUnwind() from error


def _scan_audits(case_root: Path, reviews):
    if reviews is None:
        return []
    try:
        entries = sorted(reviews.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise _ContainmentUnwind() from error
    out = []
    for entry in entries:
        if not fnmatch.fnmatchcase(entry.name, "*.generation_audit.json"):
            continue
        real = _child(reviews, entry.name, case_root)
        if real is None or not real.is_file():
            raise _ContainmentUnwind()
        try:
            record = json.loads(real.read_bytes().decode("utf-8"))
            if not isinstance(record, dict):
                record = None
        except Exception:
            record = None
        out.append(record)
    return out


def _audit_matches(record: dict, entry: mr.JournalEntrySnapshot, *, case_id: str, document_id: str,
                   pending_sha: str) -> bool:
    exact = {
        "schema_version": "1",
        "case_id": case_id,
        "document_id": document_id,
        "target_ref": entry.target_ref,
        "target_state": _TARGET_STATE,
        "action_family": ACTION_FAMILY,
        "channel": _CHANNEL,
        "mutation_actor_ref": entry.actor_label,
        "mutation_idempotency_key": entry.idempotency_key,
        "mutation_resource_key": entry.resource_key,
        "pending_sha256": pending_sha,
        "outcome": "generated",
        "revision_version": _REVISION_VERSION,
    }
    for key, value in exact.items():
        if not isinstance(record.get(key), str) or record.get(key) != value:
            return False
    if entry.target_state != _TARGET_STATE or entry.action_family != ACTION_FAMILY:
        return False
    input_digest = record.get("input_digest")
    attempt = record.get("attempt")
    if not isinstance(input_digest, str) or not _SHA256_HEX_RE.match(input_digest):
        return False
    if type(attempt) is not int or attempt < 1:
        return False
    identity_payload = record.get("identity_payload")
    if not isinstance(identity_payload, dict):
        return False
    if identity_payload.get("case_id") != case_id or identity_payload.get("document_id") != document_id:
        return False
    if hashlib.sha256(_canonical_bytes(identity_payload)).hexdigest() != input_digest:
        return False
    composite = candidate_pre_revision(input_digest, attempt)
    if composite != entry.pre_revision or record.get("pre_revision") != entry.pre_revision:
        return False
    return True


class ManualFactReconciliationAdapter:
    """Salt-okunur; hiçbir dosya/DB mutasyonu yapmaz."""

    def __init__(self, module):
        self._module = module

    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if not isinstance(entry.resource_key, str) or not entry.resource_key.startswith("case:"):
            return _DUAL_FALSE
        case_id = entry.resource_key[len("case:"):]
        document_id = _parse_document_id(entry.target_ref)
        if document_id is None:
            return _DUAL_FALSE
        try:
            case_root, extractions, reviews = _locate(self._module, case_id, document_id)
            pending_sha = _pending_sha(case_root, extractions, self._module)
        except _ContainmentUnwind:
            return _DUAL_FALSE

        pre_ok = self._pre_state(entry, pending_sha)
        post_ok = self._post_state(entry, case_root, reviews, case_id, document_id, pending_sha)

        return mr.ReconciliationEvidence(
            post_state_verified=post_ok,
            pre_state_confirmed_unchanged=pre_ok,
            observed_post_hash=pending_sha if post_ok else None,
        )

    @staticmethod
    def _pre_state(entry: mr.JournalEntrySnapshot, pending_sha) -> bool:
        if not isinstance(entry.pre_hash, str) or not entry.pre_hash:
            return False
        if not isinstance(entry.pre_revision, str) or not entry.pre_revision:
            return False
        return candidate_pre_hash(entry.pre_revision, pending_sha) == entry.pre_hash

    @staticmethod
    def _post_state(entry, case_root, reviews, case_id, document_id, pending_sha) -> bool:
        if pending_sha is None:
            return False
        try:
            records = _scan_audits(case_root, reviews)
        except _ContainmentUnwind:
            return False
        if any(record is None for record in records):
            return False
        matches = [
            record for record in records
            if _audit_matches(record, entry, case_id=case_id, document_id=document_id, pending_sha=pending_sha)
        ]
        return len(matches) == 1


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    module = importlib.import_module(ENGINE_MODULE_NAME)
    return registry.with_adapter(ACTION_FAMILY, ManualFactReconciliationAdapter(module))
