# ============================================================
# VERGİ AI - FACT VERIFICATION WORKFLOW: RECONCILIATION ADAPTER.
#
# `verification.fact` journal satırları için `ui.services.mutation_
# registry.ReconciliationAdapter` implementasyonu + `register_into()`
# (reconciliation operator'ün merged registry'sine ONUNCU merge kaynağı
# olarak eklenir - `build_production_registry()` + 9 `register_into()`
# zinciri: 10 approval + 24 review + 1 drafting_request + 2 promotion +
# 2 deterministic-generation + 5 agent-generation + 1
# fact-extraction-generation + 2 legal-research/case-law-generation +
# 2 rag-bundle + 1 verification.fact = 50 routing key).
#
# BAĞIMSIZ KANIT İLKESİ: bu modül `fact_verification_mutation_facade`'in
# karar/containment/matcher fonksiyonlarını İMPORT ETMEZ (yalnız karar
# içermeyen `FACT_VERIFICATION_ACTION_FAMILY` sabiti paylaşılır) -
# containment/snapshot/audit-eşleşme mantığı burada BAĞIMSIZ ikinci
# implementasyondur; birindeki bug diğerini maskeleyemez. Yalnız
# önceden var olan, karar içermeyen GENERIC primitive'ler ortak
# kullanılır: `src/path_containment.py` (containment) ve
# `src/mutation_guard.py` (idempotency/fingerprint digest'i).
#
# F1 REMEDIATION (bağımsız inceleme, Medium): ilk implementasyonun
# post-state matcher'ı yalnız idempotency_key/resource_key/action_family/
# target_ref/canonical_sha256/outcome + identity_payload->pre_revision
# bağlıyordu; actor, target/from state, evidence, secondary hash, attempt,
# document/fact id, history backup ve request_fingerprint tamper'ları
# post_state_verified=True verebiliyordu (13/13 kabul). Artık aşağıdaki
# FULL BINDING uygulanır - herhangi biri düşerse post=False.
#
# KARAR KURALI:
#   - POST-STATE yalnız TAM OLARAK BİR adet FULL-BINDING success audit
#     bulunduğunda verified sayılır. Full binding (`_full_binding()`):
#       (1) outcome == success; (2) mutation_idempotency_key ==
#       entry.idempotency_key; (3) mutation_resource_key ==
#       entry.resource_key; (4) mutation_actor_ref == entry.actor_label;
#       (5) action_family == verification.fact; (6) target_ref ==
#       entry.target_ref; (7) target_ref'ten ayrıştırılan document_id/
#       fact_id == audit document_id/fact_id; (8) hedef fact canonical'da
#       mevcut; (9) audit target_state == entry.target_state; (10)/(12)
#       güncel canonical fact state == target_state; (11) audit
#       from_state == history backup'taki hedef fact'in state'i ve
#       from_state != target_state; (13)/(14) evidence_document_id ile
#       secondary_input_hash kendi aralarında tutarlı (bağımsız
#       recompute) ve fingerprint'e giren değerle aynı; (15)/(16) audit
#       attempt == identity_payload.attempt, identity_payload.
#       canonical_sha256 == canonical_sha256_before, identity_payload'dan
#       yeniden hesaplanan pre_revision == entry.pre_revision; (17)/(18)
#       audit alanlarından yeniden kurulan MutationIntent ile
#       `mutation_guard.compute_idempotency_key/compute_request_
#       fingerprint` == entry.idempotency_key / entry.request_fingerprint;
#       (19) canonical_sha256 (after) == diskteki güncel hash; (20)
#       entry.observed_post_hash NULL değilse == canonical_sha256 (NULL
#       yalnız `_mark_completed` öncesi crash'te olur - o zaman audit +
#       disk kanıtı yeterlidir, journal hash'i YOKTUR); (21)-(24)
#       history_backup_path beklenen extractions/history kökü altında
#       containment-doğrulanmış, exact-parent, mevcut REGULAR dosya;
#       gerçek sha256 == history_backup_sha256 == canonical_sha256_before;
#       backup JSON parse edilir, source_document_id == document_id ve
#       hedef fact'in state'i == from_state; (26) eksik/boş/yanlış tipli
#       herhangi bir alan fail-closed; (27) hiçbir audit/journal alanına
#       kör güvenilmez - her şey diskten yeniden hesaplanır.
#     Audit yok/bozuk/birden çok eşleşme -> canonical doğru GÖRÜNSE
#     BİLE otomatik completed YOK; karar pre-state kanıtına düşer.
#   - PRE-STATE yalnız güncel composite (canonical sha + audit-manifest
#     digest) satırın kendi `pre_hash`'ine EŞİTSE confirmed-unchanged
#     sayılır -> `failed` çözümü.
#   - İkisi de kanıtlanamıyorsa dual-false: journal satırı DEĞİŞMEZ.
#   - Containment/parse anomalisi HER ZAMAN dual-false'a düşer.
#
# Reconciliation writer/model/network ÇAĞIRMAZ.
# ============================================================

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import fact_verification  # noqa: E402
import path_containment as _path_containment  # noqa: E402
from mutation_guard import (  # noqa: E402  (generic, pre-existing, decision-free digest primitive)
    MutationIntent as _MutationIntent,
    compute_idempotency_key as _compute_idempotency_key,
    compute_request_fingerprint as _compute_request_fingerprint,
)

from . import mutation_registry as mr
from .fact_verification_mutation_facade import FACT_VERIFICATION_ACTION_FAMILY

_DUAL_FALSE = mr.ReconciliationEvidence(post_state_verified=False, pre_state_confirmed_unchanged=False)

_SNAPSHOT_VERSION = "row_v.fact_verification.snapshot.v1"
# Contract constants re-stated HERE (not imported from the facade) - the
# adapter is an independent second implementation of the binding.
_REVISION_VERSION = "row_v.fact_verification.v1"
_SUCCESS_OUTCOME = "verified_state_changed"
_VALID_STATES = ("unverified", "partially_verified", "verified")
_ACTOR_TYPE = "iam_user"
_IDENTITY_PAYLOAD_KEYS = frozenset({"revision_version", "canonical_sha256", "attempt"})
_HEX64 = frozenset("0123456789abcdef")


class NestedPathContainmentError(Exception):
    """Internal-only: containment helper'larından `gather_evidence()`'ın
    dual-false dönüşüne unwind sinyali - modül sınırını asla aşmaz."""


class UnexpectedResourceKeyShapeError(Exception):
    """`case:<case_id>` olmayan resource_key ile bu adapter'a
    yönlenen satır - yapısal olarak ulaşılmaz backstop."""


def _resolve_case_root_real(case_id: str) -> Path:
    cases_dir = fact_verification.CASES_DIR
    try:
        _path_containment.validate_segment(case_id)
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise NestedPathContainmentError(str(error)) from error


def _verify_nested(case_root_real: Path, case_id: str, raw_path) -> Path:
    cases_dir = fact_verification.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise NestedPathContainmentError(str(error)) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise NestedPathContainmentError(str(error)) from error


def _scan_audits(case_root_real: Path, reviews_dir_real: Path):
    if not reviews_dir_real.is_dir():
        return []
    try:
        raw_entries = sorted(reviews_dir_real.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise NestedPathContainmentError(str(error)) from error
    results = []
    for entry in raw_entries:
        if not fnmatch.fnmatch(entry.name, "*.verification.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise NestedPathContainmentError(str(error)) from error
        if resolved.parent != reviews_dir_real:
            raise NestedPathContainmentError(f"in-tree alias: {entry.name!r}")
        try:
            with open(resolved, "r", encoding="utf-8") as file:
                record = json.load(file)
            if not isinstance(record, dict):
                record = None
        except Exception:
            record = None
        results.append((resolved, record))
    return results


def _compute_audit_manifest_digest(case_root_real: Path, reviews_dir_real: Path) -> str:
    entries = _scan_audits(case_root_real, reviews_dir_real)
    manifest = []
    for path, _record in entries:
        manifest.append([path.name, hashlib.sha256(path.read_bytes()).hexdigest()])
    payload = json.dumps(
        {"manifest": manifest}, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compute_pre_hash(canonical_sha256: str, audit_manifest_digest: str) -> str:
    payload = json.dumps(
        {
            "snapshot_version": _SNAPSHOT_VERSION,
            "canonical_sha256": canonical_sha256,
            "audit_manifest_digest": audit_manifest_digest,
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _recompute_pre_revision_from_identity_payload(identity_payload) -> str | None:
    if not isinstance(identity_payload, dict):
        return None
    payload = json.dumps(
        identity_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256_hex(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64


def _is_attempt(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _recompute_secondary_input_hash(evidence_document_id):
    """Independent re-statement of the facade's `secondary_input_hash`
    contract: `sha256(canonical_json({"evidence_document_id": X}))` when
    an evidence document was given, `None` otherwise."""
    if evidence_document_id is None:
        return None
    payload = json.dumps(
        {"evidence_document_id": evidence_document_id},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_history_backup(record: dict, *, history_dir_real: Path, document_id: str, fact_id: str) -> bool:
    """Bindings (21)-(24): the audit's `history_backup_path` MUST resolve
    (containment-verified, exact parent) to a REGULAR file directly
    under the verified `extractions/history` directory; its real
    sha256 MUST equal BOTH `history_backup_sha256` and
    `canonical_sha256_before`; and its JSON MUST genuinely carry the
    audited `from_state` for the SAME document/fact. Any escape,
    missing file, non-regular entry, hash mismatch, parse failure or
    state mismatch -> False (never raises past this boundary)."""
    try:
        raw_path = record.get("history_backup_path")
        backup_sha = record.get("history_backup_sha256")
        before_sha = record.get("canonical_sha256_before")
        from_state = record.get("from_state")
        if not _nonblank(raw_path) or not _is_sha256_hex(backup_sha) or not _is_sha256_hex(before_sha):
            return False
        if backup_sha != before_sha:
            return False
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = history_dir_real / raw_path
        if not os.path.lexists(candidate):
            return False
        resolved = _path_containment.resolve_existing(candidate, root=history_dir_real)
        if resolved.parent != history_dir_real:
            return False
        if not resolved.is_file():
            return False
        raw_bytes = resolved.read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != backup_sha:
            return False
        parsed = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(parsed, dict) or parsed.get("source_document_id") != document_id:
            return False
        backup_fact = fact_verification.find_fact(parsed, fact_id)
        if not isinstance(backup_fact, dict) or backup_fact.get("verification_state") != from_state:
            return False
        return True
    except Exception:
        return False


def _full_binding(
    record: dict,
    entry: mr.JournalEntrySnapshot,
    *,
    document_id: str,
    fact_id: str,
    current_canonical_sha256: str,
    current_fact_state,
    history_dir_real: Path,
) -> bool:
    """FULL audit<->journal<->disk binding for ONE candidate audit record
    (see the module header's KARAR KURALI for the numbered contract).
    Every check is fail-closed; any missing, blank, wrongly-typed or
    mismatching value returns False. Nothing in `record` or `entry` is
    trusted on its own - hashes and digests are recomputed."""
    try:
        if not isinstance(record, dict):
            return False
        # (1) success outcome
        if record.get("outcome") != _SUCCESS_OUTCOME:
            return False
        # (2)/(3)/(4)/(5)/(6) journal-side identifiers
        if not _nonblank(entry.idempotency_key) or record.get("mutation_idempotency_key") != entry.idempotency_key:
            return False
        if not _nonblank(entry.resource_key) or record.get("mutation_resource_key") != entry.resource_key:
            return False
        actor_ref = record.get("mutation_actor_ref")
        if not _nonblank(actor_ref) or not _nonblank(entry.actor_label) or actor_ref != entry.actor_label:
            return False
        if record.get("action_family") != FACT_VERIFICATION_ACTION_FAMILY:
            return False
        if not _nonblank(entry.target_ref) or record.get("target_ref") != entry.target_ref:
            return False
        # (7)/(8) document/fact identity, parsed from target_ref by the caller
        if record.get("document_id") != document_id or record.get("fact_id") != fact_id:
            return False
        if current_fact_state not in _VALID_STATES:
            return False
        # (9)/(10)/(11)/(12) states
        target_state = record.get("target_state")
        from_state = record.get("from_state")
        if target_state not in _VALID_STATES or from_state not in _VALID_STATES:
            return False
        if target_state != entry.target_state or from_state == target_state:
            return False
        if current_fact_state != target_state:
            return False
        # (13)/(14) evidence <-> secondary_input_hash consistency
        evidence_document_id = record.get("evidence_document_id")
        if evidence_document_id is not None and not _nonblank(evidence_document_id):
            return False
        secondary = record.get("secondary_input_hash")
        if secondary is not None and not _is_sha256_hex(secondary):
            return False
        if _recompute_secondary_input_hash(evidence_document_id) != secondary:
            return False
        # (15)/(16) attempt / identity_payload / pre_revision
        identity_payload = record.get("identity_payload")
        if not isinstance(identity_payload, dict) or set(identity_payload) != _IDENTITY_PAYLOAD_KEYS:
            return False
        if identity_payload.get("revision_version") != _REVISION_VERSION:
            return False
        attempt = record.get("attempt")
        if not _is_attempt(attempt) or not _is_attempt(identity_payload.get("attempt")):
            return False
        if identity_payload["attempt"] != attempt:
            return False
        before_sha = record.get("canonical_sha256_before")
        if not _is_sha256_hex(before_sha) or identity_payload.get("canonical_sha256") != before_sha:
            return False
        recomputed_pre_revision = _recompute_pre_revision_from_identity_payload(identity_payload)
        if not _nonblank(entry.pre_revision) or recomputed_pre_revision != entry.pre_revision:
            return False
        # (17)/(18) idempotency_key + request_fingerprint recomputed from
        # the AUDIT's own fields through the generic mutation_guard digest
        # - binds actor/target_state/secondary/pre_revision to the journal.
        intent = _MutationIntent(
            actor_type=_ACTOR_TYPE,
            actor_ref=actor_ref,
            resource_key=entry.resource_key,
            action_family=FACT_VERIFICATION_ACTION_FAMILY,
            target_ref=entry.target_ref,
            target_state=target_state,
            pre_hash=entry.pre_hash if _nonblank(entry.pre_hash) else "recompute_only",
            pre_revision=recomputed_pre_revision,
            secondary_input_hash=secondary,
        )
        if _compute_idempotency_key(intent) != entry.idempotency_key:
            return False
        if not _nonblank(entry.request_fingerprint) or _compute_request_fingerprint(intent) != entry.request_fingerprint:
            return False
        # (19) post-state hash: the DISK is authoritative (recomputed by
        # the caller), never the audit's own claim. (20) - "audit after-hash
        # == journal observed_post_hash" - is enforced on the facade's
        # completed-replay path, where the coordinator hands over the
        # journal's stored hash; `mutation_registry.JournalEntrySnapshot`
        # (READ-ONLY this turn) deliberately does not carry
        # `observed_post_hash` (a row reaching this adapter is
        # non-terminal and that column is NULL/untrusted by contract), so
        # this adapter binds the after-hash to the disk instead.
        after_sha = record.get("canonical_sha256")
        if not _is_sha256_hex(after_sha) or after_sha != current_canonical_sha256:
            return False
        if after_sha == before_sha:
            return False
        # (21)-(24) history backup
        if not _verify_history_backup(record, history_dir_real=history_dir_real, document_id=document_id, fact_id=fact_id):
            return False
        return True
    except Exception:
        return False


class FactVerificationReconciliationAdapter:
    """`verification.fact` için tek adapter sınıfı. Salt-okunur;
    hiçbir file/DB mutasyonu yapmaz (Protocol kontratı). Writer/model/
    network HİÇBİR ZAMAN çağrılmaz."""

    def gather_evidence(self, entry: mr.JournalEntrySnapshot) -> mr.ReconciliationEvidence:
        if not entry.resource_key.startswith("case:"):
            raise UnexpectedResourceKeyShapeError(
                f"journal_id={entry.journal_id}: expected 'case:<case_id>', got {entry.resource_key!r}"
            )
        case_id = entry.resource_key[len("case:"):]

        target_ref = entry.target_ref or ""
        if not (target_ref.startswith("fact.") and target_ref.endswith(".verification")):
            return _DUAL_FALSE
        middle = target_ref[len("fact."):-len(".verification")]
        parts = middle.rsplit(".", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return _DUAL_FALSE
        document_id, fact_id = parts

        try:
            case_root_real = _resolve_case_root_real(case_id)
            _path_containment.validate_segment(document_id)
            raw_canonical = fact_verification.get_canonical_path(case_id, document_id)
            raw_reviews = fact_verification.get_verification_reviews_dir(case_id, document_id)
            raw_history = fact_verification.get_history_dir(case_id, document_id)
            canonical_verified = _verify_nested(case_root_real, case_id, raw_canonical)
            reviews_verified = _verify_nested(case_root_real, case_id, raw_reviews)
            history_verified = _verify_nested(case_root_real, case_id, raw_history)
        except (NestedPathContainmentError, _path_containment.PathContainmentError):
            return _DUAL_FALSE

        if not canonical_verified.is_file():
            # Canonical yok - post-state kurulamaz; pre-state'e düş
            # (aşağıda `current_canonical_sha` None olacağından post
            # bloğu doğal olarak atlanır).
            current_canonical_sha = None
            raw_canonical_bytes = None
        else:
            raw_canonical_bytes = canonical_verified.read_bytes()
            current_canonical_sha = hashlib.sha256(raw_canonical_bytes).hexdigest()

        # ---- POST-STATE: exactly-one FULL-BINDING success audit (see
        # `_full_binding()` - audit <-> journal <-> disk <-> history backup,
        # every hash/digest recomputed, nothing trusted). ----
        if current_canonical_sha is not None:
            try:
                extraction = fact_verification.verify_canonical_serialization_form(raw_canonical_bytes)
                fact = fact_verification.find_fact(extraction, fact_id)
            except Exception:
                fact = None
            if fact is not None and fact.get("verification_state") == entry.target_state:
                try:
                    entries = _scan_audits(case_root_real, reviews_verified)
                except NestedPathContainmentError:
                    return _DUAL_FALSE
                history_dir_real = None
                try:
                    if os.path.lexists(history_verified):
                        history_dir_real = _path_containment.resolve_existing(history_verified, root=case_root_real)
                        if not history_dir_real.is_dir():
                            history_dir_real = None
                except _path_containment.PathContainmentError:
                    history_dir_real = None
                if history_dir_real is not None and not any(record is None for _path, record in entries):
                    matches = [
                        (path, record) for path, record in entries
                        if _full_binding(
                            record, entry,
                            document_id=document_id, fact_id=fact_id,
                            current_canonical_sha256=current_canonical_sha,
                            current_fact_state=fact.get("verification_state"),
                            history_dir_real=history_dir_real,
                        )
                    ]
                    if len(matches) == 1:
                        return mr.ReconciliationEvidence(
                            post_state_verified=True,
                            pre_state_confirmed_unchanged=False,
                            observed_post_hash=current_canonical_sha,
                        )
                # Parse edilemeyen aday, history dizini yok/escape VEYA
                # 0/>1 full-binding eşleşme -> otomatik completed YOK,
                # pre-state kanıtına düşülür.

        # ---- PRE-STATE: güncel composite == satırın pre_hash'i. ----
        if _nonblank(entry.pre_hash) and current_canonical_sha is not None:
            try:
                audit_manifest_digest = _compute_audit_manifest_digest(case_root_real, reviews_verified)
            except NestedPathContainmentError:
                return _DUAL_FALSE
            current_composite = _compute_pre_hash(current_canonical_sha, audit_manifest_digest)
            if current_composite == entry.pre_hash:
                return mr.ReconciliationEvidence(
                    post_state_verified=False, pre_state_confirmed_unchanged=True,
                )

        return _DUAL_FALSE


def register_into(registry: mr.MutationAdapterRegistry) -> mr.MutationAdapterRegistry:
    """`verification.fact` ailesini var olan bir registry'ye ekler -
    `reconciliation_operator._default_registry_factory()`'nin ONUNCU
    merge kaynağı (`build_production_registry()` + 9 `register_into()`;
    50 routing key)."""
    return registry.with_adapter(FACT_VERIFICATION_ACTION_FAMILY, FactVerificationReconciliationAdapter())
