# ============================================================
# VERGİ AI - FACT VERIFICATION WORKFLOW (Layer V)
#
# AMAÇ:
#
# Canonical, doküman-scoped `facts.json` içindeki TEK bir fact'in
# `verification_state` alanını (unverified/partially_verified/verified)
# insan kararı + kanıt referansı (evidence-ref) + audit ile değiştirmek.
#
# Bu writer Layer A (promotion, src/fact_approval.py) DEĞİLDİR - fact
# approval extraction'ın belgeye uygun olduğunu onaylar,
# verification_state'i asla değiştirmez (bkz. fact_approval.py'nin
# kendi modül başlık yorumu: "Bu nedenle fact verification_state
# değerleri değiştirilmez."). Bu writer de Layer B review DEĞİLDİR -
# `review_registry`'nin `get_canonical_path(review_kind, case_id)`
# imzası document_id almaz, doküman-scoped bir hedefi ifade edemez.
#
# Bu modül ui.services.fact_verification_mutation_facade tarafından
# kilit-altı doğrulanmış Path paketiyle (`verified_paths`) çağrılır -
# doğrudan CLI mutasyon yolu YOKTUR (bu dosyada `main()`/`__main__`
# TANIMLANMAZ - kapatılacak bir legacy bypass yoktur, hiç açılmamıştır).
#
# Yalnız hedef fact'in `verification_state` alanı değişir - başka
# hiçbir fact alanı, üst-düzey extraction alanı veya diğer fact'ler
# DOKUNULMAZ. Serializer TEK kaynaktır: `fact_approval._canonical_json_
# bytes` (import edilir, yeniden yazılmaz).
#
# Network/model KULLANILMAZ - bu saf bir insan-kararı kayıt işlemidir.
# ============================================================

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import fact_approval
import path_containment
from case_fact_validator import (
    source_has_locator as _shared_source_has_locator,
    validate_fact_extraction,
)

FACT_VERIFICATION_VERSION = "1"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CASES_DIR = DATA_DIR / "cases"

VALID_STATES = ("unverified", "partially_verified", "verified")
POSITIVE_STATES = ("verified", "partially_verified")

CANONICAL_FILENAME = "facts.json"


# ============================================================
# PATH GETTERS (raw candidate üretimi - güvenlik doğrulaması DEĞİL;
# çağıran (facade) bu ham yolu kendi bağımsız containment
# doğrulamasından geçirmek ZORUNDADIR - promotion emsali).
# ============================================================

def get_extractions_dir(case_id, document_id):
    return CASES_DIR / case_id / "documents" / document_id / "extractions"


def get_canonical_path(case_id, document_id):
    return get_extractions_dir(case_id, document_id) / CANONICAL_FILENAME


def get_history_dir(case_id, document_id):
    return get_extractions_dir(case_id, document_id) / "history"


def get_verification_reviews_dir(case_id, document_id):
    """Audit dizini `reviews/fact_verifications/` - promotion'ın (fact_
    approval.get_reviews_dir) flat `reviews/`'ine kardeş DEĞİL, onun
    İÇİNDE bir alt dizin (Layer B'nin `reviews/<family>_reviews/`
    nesting konvansiyonunun birebir aynısı) - iki ailenin audit
    dosyaları asla karışmaz."""
    return get_extractions_dir(case_id, document_id) / "reviews" / "fact_verifications"


def get_document_dir(case_id, document_id):
    return CASES_DIR / case_id / "documents" / document_id


def get_document_json_path(case_id, document_id):
    return get_document_dir(case_id, document_id) / "document.json"


# ============================================================
# JSON / HASH / TIME HELPERS
# ============================================================

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        while True:
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def now_iso():
    return datetime.now().astimezone().isoformat()


def now_stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# ============================================================
# TEK SERİALİZATION KAYNAĞI - fact_approval'ın kendi
# `_canonical_json_bytes`/`_canonical_json_text`'ini yeniden kullanır
# (ikinci bir serializer İCAT EDİLMEZ - drift imkânsız).
# ============================================================

def canonical_json_text(data):
    return fact_approval._canonical_json_text(data)


def canonical_json_bytes(data):
    return fact_approval._canonical_json_bytes(data)


class FactVerificationSerializationError(Exception):
    """Canonical dosya `_canonical_json_bytes()` biçiminde DEĞİL
    (key-order/indent farklı) - sessiz reformat asla yapılmaz, fail-
    closed reddedilir."""


def verify_canonical_serialization_form(raw_bytes: bytes) -> dict:
    """EOL-toleranslı yapısal eşitlik kontrolü + parse: LF ve CRLF
    girdi ikisi de kabul edilir (`\\r\\n` -> `\\n` normalize edilerek
    karşılaştırılır); key-order veya indentation farklıysa fail-closed
    reddedilir. Başarıda ayrıştırılmış dict'i döner (tekrar parse
    gerekmez)."""
    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
    except Exception as error:
        raise FactVerificationSerializationError(
            "Canonical dosya UTF-8 JSON olarak ayrıştırılamadı."
        ) from error
    if not isinstance(parsed, dict):
        raise FactVerificationSerializationError(
            "Canonical dosya bir JSON nesnesi değil."
        )
    reserialized_text = canonical_json_text(parsed)
    normalized_raw_text = raw_bytes.decode("utf-8").replace("\r\n", "\n")
    if reserialized_text != normalized_raw_text:
        raise FactVerificationSerializationError(
            "Canonical dosya beklenen kanonik serialization biçiminde değil "
            "(key-order/indent farklı) - sessiz reformat yapılmaz."
        )
    return parsed


def find_fact(extraction: dict, fact_id: str):
    for fact in extraction.get("facts", []) or []:
        if fact.get("fact_id") == fact_id:
            return fact
    return None


def source_has_locator(source):
    return _shared_source_has_locator(source or {})


def allowed_evidence_document_ids(extraction: dict, fact: dict) -> set:
    """İzinli evidence kümesi: {extraction.source_document_id} ∪
    fact.related_document_ids - başka HİÇBİR belge (case içindeki
    diğer aktif belgeler dahil) kabul edilmez."""
    allowed = set()
    source_document_id = extraction.get("source_document_id")
    if source_document_id:
        allowed.add(source_document_id)
    for document_id in fact.get("related_document_ids", []) or []:
        if document_id:
            allowed.add(document_id)
    return allowed


def compute_expected_post_canonical_bytes(raw_before: bytes, fact_id: str, target_state: str) -> bytes:
    """Saf, deterministik dönüşüm: hedef fact'in `verification_state`'i
    dışında HİÇBİR şey değişmez. Dosya sistemine hiçbir şey yazmaz."""
    extraction = json.loads(raw_before.decode("utf-8"))
    new_extraction = copy.deepcopy(extraction)
    found = False
    for fact in new_extraction.get("facts", []) or []:
        if fact.get("fact_id") == fact_id:
            fact["verification_state"] = target_state
            found = True
            break
    if not found:
        raise ValueError(f"fact_id={fact_id!r} beklenen-bayt hesaplaması için bulunamadı.")
    return canonical_json_bytes(new_extraction)


# ============================================================
# VERIFIED-PATH TOPOLOJİ KONTROLÜ
# ============================================================

_VERIFIED_PATHS_KEYS = frozenset(
    {"extractions_dir", "canonical_path", "history_dir", "reviews_dir"}
)


def _check_verified_paths_topology(verified_paths):
    if set(verified_paths.keys()) != _VERIFIED_PATHS_KEYS:
        raise ValueError(
            f"verified_paths anahtar seti tam olarak {sorted(_VERIFIED_PATHS_KEYS)} olmalıdır."
        )
    extractions_dir = Path(verified_paths["extractions_dir"])
    canonical_path = Path(verified_paths["canonical_path"])
    history_dir = Path(verified_paths["history_dir"])
    reviews_dir = Path(verified_paths["reviews_dir"])

    failures = []
    if canonical_path.parent != extractions_dir or canonical_path.name != CANONICAL_FILENAME:
        failures.append("canonical_path topolojisi beklenen değil")
    if history_dir.parent != extractions_dir:
        failures.append("history_dir, extractions_dir'in doğrudan çocuğu değil")
    if reviews_dir.parent != extractions_dir / "reviews":
        failures.append("reviews_dir, extractions_dir/reviews'in doğrudan çocuğu değil")
    if failures:
        raise ValueError(
            "verified_paths topoloji çapraz-kontrolü başarısız (hiçbir yazım yapılmadı): "
            + "; ".join(failures)
        )
    return {
        "extractions_dir": extractions_dir,
        "canonical_path": canonical_path,
        "history_dir": history_dir,
        "reviews_dir": reviews_dir,
    }


# ============================================================
# ATOMIC WRITE / ROLLBACK / AUDIT
# ============================================================

def _atomic_write(path, data_bytes: bytes):
    path = Path(path)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "wb") as file:
        file.write(data_bytes)
        file.flush()
        os.fsync(file.fileno())
    os.replace(tmp_path, path)


class FactVerificationRollbackFailedError(Exception):
    """Rollback (canonical'ı önceki baytlara geri yazma) BAŞARISIZ oldu -
    orijinal exception ile birlikte CRITICAL loglanmalı (facade/
    coordinator sorumluluğu - bu satırdan sonra journal
    `reconciliation_required` kalır)."""


def _rollback_canonical(canonical_path, raw_before: bytes):
    try:
        _atomic_write(canonical_path, raw_before)
    except Exception as error:
        raise FactVerificationRollbackFailedError(str(error)) from error


def _write_history_backup_excl(history_dir, canonical_hash_before, raw_before):
    history_dir.mkdir(parents=True, exist_ok=True)
    base = f"facts_before_verification_{now_stamp()}_{canonical_hash_before[:8]}"
    suffix = 0
    while True:
        name = f"{base}.json" if suffix == 0 else f"{base}_{suffix}.json"
        path_containment.validate_segment(name)
        candidate = path_containment.resolve_for_create(history_dir, name)
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            suffix += 1
            if suffix > 1000:
                raise RuntimeError(
                    "History backup dosya adı için 1000 denemede boş ad bulunamadı."
                )
            continue
        with os.fdopen(fd, "wb") as file:
            file.write(raw_before)
        return candidate


def _write_audit_record_excl(reviews_dir, document_id, fact_id, audit_record):
    reviews_dir.mkdir(parents=True, exist_ok=True)
    base = f"{document_id}_{fact_id}_{now_stamp()}"
    suffix = 0
    while True:
        name = f"{base}.verification.json" if suffix == 0 else f"{base}_{suffix}.verification.json"
        path_containment.validate_segment(name)
        candidate = path_containment.resolve_for_create(reviews_dir, name)
        try:
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            suffix += 1
            if suffix > 1000:
                raise RuntimeError(
                    "Audit dosya adı için 1000 denemede boş ad bulunamadı."
                )
            continue
        with os.fdopen(fd, "wb") as file:
            file.write(canonical_json_bytes(audit_record))
        return candidate


# ============================================================
# WRITER
# ============================================================

def apply_verification(
    case_id,
    document_id,
    fact_id,
    from_state,
    target_state,
    *,
    evidence_document_id=None,
    evidence_document_sha256=None,
    source_locator_present,
    source_locator_sha256,
    identity_payload,
    attempt,
    secondary_input_hash=None,
    verified_paths,
    mutation_idempotency_key,
    mutation_resource_key,
    mutation_actor_ref,
):
    """Kilit-altı doğrulanmış `verified_paths` paketiyle deterministik
    fact-state yazımı. Yalnız hedef fact'in `verification_state`'ini
    değiştirir; diğer fact'ler ve üst-düzey alanlar deep-equal kalır.
    Network/model kullanmaz. `verified_paths` ZORUNLUDUR - legacy/raw
    yol dalı YOKTUR (bu writer'ın hiçbir emsali olmadığından
    `verified_paths=None` dalı bilinçli olarak TANIMLANMAZ)."""

    paths = _check_verified_paths_topology(verified_paths)
    canonical_path = paths["canonical_path"]
    history_dir = paths["history_dir"]
    reviews_dir = paths["reviews_dir"]

    raw_before = canonical_path.read_bytes()
    extraction = verify_canonical_serialization_form(raw_before)
    target_fact = find_fact(extraction, fact_id)
    if target_fact is None:
        raise ValueError(f"fact_id={fact_id!r} canonical içinde bulunamadı (writer sınırı).")
    if target_fact.get("verification_state") != from_state:
        raise ValueError(
            "Writer sınırında from_state uyuşmazlığı (kilit-altı çift kontrol) - "
            f"beklenen={from_state!r}, gerçek={target_fact.get('verification_state')!r}."
        )
    if from_state == target_state:
        raise ValueError("Writer sınırında self-transition (bu asla oluşmamalıydı).")

    canonical_sha_before = sha256_bytes(raw_before)
    backup_path = _write_history_backup_excl(history_dir, canonical_sha_before, raw_before)

    new_bytes = compute_expected_post_canonical_bytes(raw_before, fact_id, target_state)

    _atomic_write(canonical_path, new_bytes)

    try:
        validate_fact_extraction(facts_path=canonical_path, raise_on_error=True)
        observed = sha256_file(canonical_path)
        expected = sha256_bytes(new_bytes)
        if observed != expected:
            raise ValueError(
                "Writer post-write hash uyuşmazlığı "
                f"(beklenen={expected!r}, gözlenen={observed!r})."
            )
        reparsed = json.loads(canonical_path.read_bytes().decode("utf-8"))
        reparsed_fact = find_fact(reparsed, fact_id)
        if reparsed_fact is None or reparsed_fact.get("verification_state") != target_state:
            raise ValueError("Writer post-write parse-back doğrulaması başarısız.")
    except Exception:
        _rollback_canonical(canonical_path, raw_before)
        raise

    audit_record = {
        "schema_version": 1,
        "audit_type": "fact_verification",
        "case_id": case_id,
        "document_id": document_id,
        "fact_id": fact_id,
        "target_ref": f"fact.{document_id}.{fact_id}.verification",
        "from_state": from_state,
        "target_state": target_state,
        "attempt": attempt,
        "identity_payload": identity_payload,
        "evidence_document_id": evidence_document_id,
        "evidence_document_sha256": evidence_document_sha256,
        "source_locator_present": bool(source_locator_present),
        "source_locator_sha256": source_locator_sha256,
        "secondary_input_hash": secondary_input_hash,
        "mutation_idempotency_key": mutation_idempotency_key,
        "mutation_resource_key": mutation_resource_key,
        "mutation_actor_ref": mutation_actor_ref,
        "action_family": "verification.fact",
        "channel": "local_lawyer_fact_verification_cli",
        "reviewer_ref": "local_lawyer_fact_verification_cli",
        "canonical_sha256_before": canonical_sha_before,
        "canonical_sha256": observed,
        "history_backup_path": str(backup_path),
        "history_backup_sha256": canonical_sha_before,
        "generated_at": now_iso(),
        "outcome": "verified_state_changed",
    }

    try:
        audit_path = _write_audit_record_excl(reviews_dir, document_id, fact_id, audit_record)
    except Exception:
        _rollback_canonical(canonical_path, raw_before)
        raise

    return {
        "canonical_path": canonical_path,
        "canonical_sha256": observed,
        "canonical_sha256_before": canonical_sha_before,
        "audit_path": audit_path,
        "history_backup_path": backup_path,
    }
