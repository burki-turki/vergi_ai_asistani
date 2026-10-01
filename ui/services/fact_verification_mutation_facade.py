# ============================================================
# VERGİ AI - FACT VERIFICATION WORKFLOW: MUTATION FACADE.
#
# `verification.fact` action family'sini (fact-level, doküman-scoped
# `facts.json` içindeki TEK bir fact'in `verification_state`'ini
# değiştiren, CLI-only, coordinated bir mutasyon ailesi) mutation
# coordinator/journal altyapısına bağlayan AYRI, BAĞIMSIZ facade.
#
# Ne Layer A'nın exact-10 `mutation_approval_facade.py`'sine, ne
# `promotion_mutation_facade.py`'ye (document-scoped ama TÜM dosyayı
# pending'den yeniden yazan promotion) katlanmaz - hiçbiri fact-level
# (üçüncü segment: fact_id) bir hedefi ifade edemez.
#
# ACTION FAMILY: `verification.fact` (kanal soneki yok - CLI-only).
# target_ref = fact.<document_id>.<fact_id>.verification
# resource_key = case:<case_id>
#
# STATE MODEL: yalnız 6 gerçek geçiş kabul edilir (self-transition'ların
# üçü REDDEDİLİR - unverified->unverified, partially_verified->
# partially_verified, verified->verified). Self-transition
# `FactVerificationNoOpError` ile fail-closed reddedilir, pre-lock VE
# kilit-altı, sıfır journal satırı.
#
# EVIDENCE: `verified`/`partially_verified` hedeflerinde evidence-ref
# ZORUNLU + hedef fact'in mevcut source locator'ı ZORUNLU;
# `unverified` hedefinde evidence-ref opsiyonel. İzinli evidence kümesi
# yalnız {extraction.source_document_id} ∪ fact.related_document_ids -
# case içindeki başka HİÇBİR aktif belge kabul edilmez.
#
# IDENTITY: `pre_revision = sha256(canonical_json({revision_version,
# canonical_sha256, attempt}))` - `--attempt` (default 1) kimliğe
# girer (rag_bundle emsali) çünkü canonical dosyanın kendisi
# operatörün kontrolünde değildir; bir `failed` satırdan sonra aynı
# H ile retry edebilmek için attempt artırılır.
#
# F2 REMEDIATION (bağımsız inceleme, Medium) - REVISION/STATE-CYCLE
# ÇAKIŞMASI: identity content-hash tabanlı olduğundan, 3-durumlu ve geri
# alınabilir bir alan (ör. u->p->v->p) canonical baytlarını daha önce
# görülmüş bir revizyona GERİ getirebilir; aynı aktör + aynı attempt için
# identity, daha önce TAMAMLANMIŞ bir journal satırıyla çakışır. Formül
# ve generic coordinator sözleşmesi DEĞİŞTİRİLMEDİ (migration/uuid/
# zaman damgası/gizli attempt artışı YOK); çakışma açık, fail-closed
# ve operatöre doğru yönlendirilen bir sözleşmeye bağlandı:
#   (a) coordinator aynı fingerprint'li completed satırı "replay"
#       olarak döndürürse `_verify_completed_replay_binding()` ÖNCE eski
#       audit'in FULL binding'ini (actor/resource/family/target_ref/
#       document/fact/from+target state/evidence/secondary/attempt/
#       identity_payload+pre_revision/request_fingerprint/canonical
#       before+after/contained+hash-doğrulanmış history backup/
#       exactly-one) doğrular - tamper VARSA cycle diye SINIFLANDIRILMAZ,
#       generic `FactVerificationAuditBindingVerificationFailedError`
#       fırlar; audit SAĞLAM ve güncel canonical == stored
#       observed_post_hash ise GENUINE replay (stored result, writer
#       çağrılmaz); audit SAĞLAM fakat güncel canonical hash stored
#       observed_post_hash'ten FARKLI ve isteğin beyan ettiği pre-state
#       hash'ine EŞİT ise `FactVerificationRevisionCycleConflictError`
#       (sabit mesaj: `--attempt N+1` kullanın; attempt OTOMATİK
#       ARTIRILMAZ; sıfır mutasyon/journal/audit);
#   (b) coordinator aynı identity + FARKLI fingerprint için
#       `IdempotencyConflictError` fırlatırsa facade bunu güvenlik
#       davranışını zayıflatmadan (aynı sınıfın ALT SINIFI, sıfır
#       mutasyon, hiçbir alan sessizce kabul edilmez)
#       `FactVerificationIdentityConflictError`'a çevirir: gerçek bir
#       request conflict'i olabileceğini söyler, bilinçli bir
#       state-cycle ise `--attempt N+1` gerektiğini bildirir.
#
# `pre_hash` (composite)
# = sha256(canonical_json({snapshot_version, canonical_sha256,
# audit_manifest_digest})) - evidence belgesi hash'i BU composite'e
# GİRMEZ, ayrı bir pre-lock/kilit-altı precondition olarak karşılaştırılır
# (Fable D12 düzeltmesi: composite'in adapter tarafından audit'siz
# yeniden hesaplanabilir kalması için). `secondary_input_hash` =
# sha256(canonical_json({"evidence_document_id": X})) if X else None -
# fingerprint'te, kimlikte DEĞİL (Layer B review_note emsali).
#
# WRITER SINIRI: `src/fact_verification.apply_verification()` yalnız
# kilit-altı doğrulanmış Path paketiyle (verified_paths ZORUNLU),
# atomik yazım + O_EXCL history backup + O_EXCL audit + tam rollback.
# ============================================================

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

import os  # noqa: E402
import fact_verification  # noqa: E402
from mutation_guard import MutationIntent, compute_idempotency_key, compute_request_fingerprint  # noqa: E402
import path_containment as _path_containment  # noqa: E402

from . import authz as _authz
from . import mutation_coordinator as _mutation_coordinator
from . import mutation_lock as _mutation_lock
from .common import (
    ApprovalUiError,
    PreconditionRaceDetectedError,
    StaleViewError,
)

FACT_VERIFICATION_ACTION_FAMILY = "verification.fact"
FACT_VERIFICATION_TARGET_STATES = ("unverified", "partially_verified", "verified")
POSITIVE_TARGET_STATES = ("verified", "partially_verified")

_CASE_RESOURCE_KEY_PREFIX = "case:"
_SNAPSHOT_VERSION = "row_v.fact_verification.snapshot.v1"
_REVISION_VERSION = "row_v.fact_verification.v1"

_logger = logging.getLogger("vergi_ai.fact_verification_mutation_facade")


def _log_critical_safely(message: str) -> None:
    try:
        _logger.critical(message)
    except Exception:
        pass


# ----------------------------------------------------------------
# Hata sınıfları - `ApprovalUiError` alt sınıfları (ui.cli_mutate'in
# `_is_known_domain_error()` bu taban sınıfı zaten tanır).
# ----------------------------------------------------------------


class FactVerificationArgumentError(ApprovalUiError):
    """Kullanım-şekli/argüman sözleşmesi ihlali - HERHANGİ bir DB/
    filesystem I/O'sundan ÖNCE fırlatılır."""


class FactVerificationNestedPathContainmentError(ApprovalUiError):
    """Writer-root/nested containment doğrulaması başarısız."""


class FactVerificationFactNotFoundError(ApprovalUiError):
    """case/document/fact_id üçlüsü canonical facts.json içinde
    bulunamadı (canonical dosyanın kendisi de dahil, existence-blind
    değildir - ayrı, adlandırılmış bir hata sınıfı; outer authz zaten
    önce çalıştığından bu bir bilgi sızıntısı YARATMAZ)."""


class FactVerificationNoOpError(ApprovalUiError):
    """Self-transition (from_state == target_state) reddedildi -
    sıfır journal satırı, sıfır filesystem değişikliği (pre-lock VE
    kilit-altı doğrulanır)."""


class FactVerificationEvidenceNotAllowedError(ApprovalUiError):
    """`--evidence-ref`, izinli kümenin ({source_document_id} ∪
    related_document_ids) dışında VEYA hedef belge active=True
    değil."""


class FactVerificationMissingLocatorError(ApprovalUiError):
    """`verified`/`partially_verified` hedefi için fact'in kaynak
    locator'ı YOK."""


class FactVerificationEvidenceDocumentInvalidError(ApprovalUiError):
    """Evidence document.json okunamadı/ayrıştırılamadı."""


class FactVerificationPreconditionRaceDetectedError(PreconditionRaceDetectedError):
    """`StaleViewError`'ın bir ALT SINIFI: case kilidi ALINDIKTAN sonra
    yeniden hesaplanan composite pre-state (canonical sha + audit-
    manifest digest) VEYA evidence belgesi durumu, kilit BEKLENMEDEN
    ÖNCE hesaplanmış olan snapshot ile UYUŞMUYOR. Sıfır `prepared`
    journal satırı yazılır, writer HİÇ ÇAĞRILMAZ."""


class FactVerificationResolvedCaseIdMismatchError(ApprovalUiError):
    """İç (kilit-altı) authz'ın çözdüğü case_id, dış (pre-lock)
    authz'ınkinden farklı."""


class FactVerificationAuditBindingVerificationFailedError(ApprovalUiError):
    """Safe-replay corroboration başarısız - insan reconciliation'ı
    gerekir. F2 remediation: bu sınıf artık YALNIZ gerçekten bozuk/
    tampered/eksik audit-backup kanıtı veya sınıflandırılamayan bir
    canonical durumu için fırlar; sağlam bir audit'in üzerine gelen
    state-cycle çakışması AYRI `FactVerificationRevisionCycleConflictError`
    ile raporlanır."""

    def __init__(self, *, journal_id: int, idempotency_key: str, reason: str):
        self.journal_id = journal_id
        self.idempotency_key = idempotency_key
        self.reason = reason
        super().__init__(
            f"journal_id={journal_id}: fact-verification safe-replay audit-binding verification "
            f"failed (idempotency_key={idempotency_key!r}): {reason}"
        )


_REVISION_CYCLE_MESSAGE = (
    "Revision/state-cycle çakışması: bu fact'in canonical baytları, aynı aktörün daha önce "
    "TAMAMLANMIŞ aynı-identity (aynı canonical hash + aynı attempt) mutasyonunun ÖNCESİNDEKİ "
    "duruma geri dönmüş; bu istek o tamamlanmış satırın güvenli tekrarı DEĞİLDİR ve hiçbir "
    "mutasyon/journal/audit yazılmadı. Aynı logical mutasyonu yeni bir identity ile uygulamak "
    "için --attempt N+1 kullanın (attempt otomatik ARTIRILMAZ)."
)

_IDENTITY_CONFLICT_MESSAGE = (
    "Identity çakışması: aynı aktör + aynı canonical hash + aynı attempt için journal'da FARKLI "
    "bir istek (target_state ve/veya evidence) kayıtlı - bu gerçek bir request conflict'i "
    "olabilir; hiçbir mutasyon yapılmadı ve mevcut isteğin hiçbir alanı sessizce kabul edilmedi. "
    "Eğer bu bilinçli bir state-cycle işlemiyse (fact daha önceki bir duruma geri getirildiyse) "
    "aynı isteği --attempt N+1 ile yeni identity altında tekrar edin (attempt otomatik "
    "ARTIRILMAZ)."
)


class FactVerificationRevisionCycleConflictError(ApprovalUiError):
    """F2 remediation: sağlam (full-binding) bir completed audit mevcut,
    ancak güncel canonical hash o satırın `observed_post_hash`'i DEĞİL,
    isteğin beyan ettiği pre-state hash'i (= audit `canonical_sha256_
    before`) - fact bir state-cycle ile önceki revizyona geri dönmüş.
    Fail-closed: sıfır mutasyon/journal/audit; operatör `--attempt N+1`
    ile yeni identity açar. Mesaj sabittir (secret/path/evidence içeriği
    YOK)."""

    def __init__(self, *, journal_id: int):
        self.journal_id = journal_id
        super().__init__(f"journal_id={journal_id}: " + _REVISION_CYCLE_MESSAGE)


class FactVerificationIdentityConflictError(ApprovalUiError, _mutation_coordinator.IdempotencyConflictError):
    """F2 remediation: coordinator'ın generic `IdempotencyConflictError`'
    ının fact-verification'a özgü, eyleme dönük ALT SINIFI (her iki
    tabanı da taşır - mevcut `except IdempotencyConflictError` yolları ve
    CLI'nin domain-error sınıflandırması DEĞİŞMEDEN çalışır). Güvenlik
    davranışı zayıflatılmaz: sıfır mutasyon, otomatik retry/attempt
    artışı YOK, hiçbir alan sessizce kabul edilmez. Mesaj sabittir."""

    def __init__(self):
        super().__init__(_IDENTITY_CONFLICT_MESSAGE)


# ----------------------------------------------------------------
# Containment helper'ları - bu modülün KENDİ bağımsız kopyaları
# (adapters kendi kopyasını taşır; iki taraf birbirinden import ETMEZ).
# ----------------------------------------------------------------


def _resolve_case_root_real(case_id: str) -> Path:
    cases_dir = fact_verification.CASES_DIR
    try:
        _path_containment.validate_segment(case_id)
        return _path_containment.resolve_existing(cases_dir / case_id, root=cases_dir)
    except _path_containment.PathContainmentError as error:
        raise FactVerificationNestedPathContainmentError(
            "Fact verification case kökü containment doğrulamasından geçemedi."
        ) from error


def _verify_nested(case_root_real: Path, case_id: str, raw_path) -> Path:
    cases_dir = fact_verification.CASES_DIR
    case_root_raw = cases_dir / case_id
    raw_path = Path(raw_path)
    try:
        relative_parts = raw_path.relative_to(case_root_raw).parts
    except ValueError as error:
        raise FactVerificationNestedPathContainmentError(
            "Fact verification writer yolu beklenen case kapsamı dışında."
        ) from error
    try:
        return _path_containment.resolve_for_create(case_root_real, *relative_parts)
    except _path_containment.PathContainmentError as error:
        raise FactVerificationNestedPathContainmentError(
            "Fact verification writer yolu containment doğrulamasından geçemedi."
        ) from error


def _verify_document_dir(case_root_real: Path, case_id: str, document_id: str) -> Path:
    try:
        _path_containment.validate_segment(document_id)
        documents_dir_real = _path_containment.resolve_existing(
            case_root_real / "documents", root=case_root_real,
        )
        doc_dir_real = _path_containment.resolve_existing(
            documents_dir_real / document_id, root=case_root_real,
        )
    except _path_containment.PathContainmentError as error:
        raise FactVerificationNestedPathContainmentError(
            "Fact verification doküman dizini containment doğrulamasından geçemedi."
        ) from error
    if doc_dir_real.parent != documents_dir_real:
        raise FactVerificationNestedPathContainmentError(
            "Fact verification doküman dizini beklenen parent'ın doğrudan çocuğu değil."
        )
    if not doc_dir_real.is_dir():
        raise FactVerificationNestedPathContainmentError(
            "Fact verification doküman girdisi bir dizin değil."
        )
    return doc_dir_real


@dataclass(frozen=True)
class _VerificationPaths:
    extractions_dir: Path
    canonical_path: Path
    history_dir: Path
    reviews_dir: Path

    @property
    def identity(self):
        return (
            str(self.extractions_dir), str(self.canonical_path),
            str(self.history_dir), str(self.reviews_dir),
        )


def _derive_verified_paths(case_root_real: Path, case_id: str, document_id: str) -> _VerificationPaths:
    _verify_document_dir(case_root_real, case_id, document_id)
    raw_extractions = fact_verification.get_extractions_dir(case_id, document_id)
    raw_canonical = fact_verification.get_canonical_path(case_id, document_id)
    raw_history = fact_verification.get_history_dir(case_id, document_id)
    raw_reviews = fact_verification.get_verification_reviews_dir(case_id, document_id)
    return _VerificationPaths(
        extractions_dir=_verify_nested(case_root_real, case_id, raw_extractions),
        canonical_path=_verify_nested(case_root_real, case_id, raw_canonical),
        history_dir=_verify_nested(case_root_real, case_id, raw_history),
        reviews_dir=_verify_nested(case_root_real, case_id, raw_reviews),
    )


def _resolve_and_check_evidence_document(case_root_real: Path, case_id: str, evidence_document_id: str) -> str:
    """Evidence belgesinin containment-doğrulanmış document.json'ını
    okur, `active is True` kontrolünü yapar (identity, truthiness
    DEĞİL), ham baytların sha256'sını döner."""
    doc_dir_real = _verify_document_dir(case_root_real, case_id, evidence_document_id)
    try:
        doc_json_real = _path_containment.resolve_existing(
            doc_dir_real / "document.json", root=case_root_real,
        )
    except _path_containment.PathContainmentError as error:
        raise FactVerificationNestedPathContainmentError(
            "Evidence document.json containment doğrulamasından geçemedi."
        ) from error
    if doc_json_real.parent != doc_dir_real:
        raise FactVerificationNestedPathContainmentError(
            "Evidence document.json beklenen dizinin doğrudan çocuğu değil."
        )
    try:
        raw = doc_json_real.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except Exception as error:
        raise FactVerificationEvidenceDocumentInvalidError(
            f"Evidence document.json okunamadı/ayrıştırılamadı: {evidence_document_id!r}"
        ) from error
    if not isinstance(data, dict) or data.get("active") is not True:
        raise FactVerificationEvidenceNotAllowedError(
            f"evidence_document_id={evidence_document_id!r} active=True değil - reddedildi."
        )
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------
# Audit manifest / composite pre-state.
# ----------------------------------------------------------------


def _scan_verification_audits(case_root_real: Path, reviews_dir_real: Path):
    """Containment-before-stat tarama: ad sınıflandırması ÖNCE (saf
    string), eşleşen HER giriş için containment + exact-parent
    membership HERHANGİ bir stat/open/JSON-read'den ÖNCE."""
    if not reviews_dir_real.is_dir():
        return []
    try:
        raw_entries = sorted(reviews_dir_real.iterdir(), key=lambda p: p.name)
    except OSError as error:
        raise FactVerificationNestedPathContainmentError(
            "Fact verification reviews dizini listelenemedi."
        ) from error
    results = []
    for entry in raw_entries:
        if not fnmatch.fnmatch(entry.name, "*.verification.json"):
            continue
        try:
            resolved = _path_containment.resolve_existing(entry, root=case_root_real)
        except _path_containment.PathContainmentError as error:
            raise FactVerificationNestedPathContainmentError(
                "Fact verification audit girişi containment doğrulamasından geçemedi."
            ) from error
        if resolved.parent != reviews_dir_real:
            raise FactVerificationNestedPathContainmentError(
                "Fact verification audit girişi beklenen dizinin dışına çözülüyor (in-tree alias)."
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


def _compute_audit_manifest_digest(case_root_real: Path, reviews_dir_real: Path) -> str:
    entries = _scan_verification_audits(case_root_real, reviews_dir_real)
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


def compute_identity_payload(canonical_sha256: str, attempt: int) -> dict:
    return {
        "revision_version": _REVISION_VERSION,
        "canonical_sha256": canonical_sha256,
        "attempt": attempt,
    }


def compute_pre_revision(identity_payload: dict) -> str:
    payload = json.dumps(
        identity_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _compute_secondary_input_hash(evidence_document_id):
    if evidence_document_id is None:
        return None
    payload = json.dumps(
        {"evidence_document_id": evidence_document_id},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _allowed_evidence_document_ids(extraction: dict, fact: dict) -> set:
    return fact_verification.allowed_evidence_document_ids(extraction, fact)


# ----------------------------------------------------------------
# Authz / conn wiring - Layer A/promotion facade'lerinin bağımsız
# kopyaları.
# ----------------------------------------------------------------


def _default_authz_repository():
    from . import db as _db  # lazy import (psycopg)

    conn = _db.get_connection()
    return _authz.PostgresAuthzRepository(conn), conn.close


def _resolve_authz_repository(authz_repository):
    if authz_repository is not None:
        return authz_repository, lambda: None
    return _default_authz_repository()


def _default_conn_factory():
    from . import db as _db  # lazy import

    return _db.get_session_lock_connection()


# ----------------------------------------------------------------
# Argüman şekil kuralları - her I/O'dan önce.
# ----------------------------------------------------------------


def _check_common_identity_args(case_id, document_id, fact_id):
    if not isinstance(case_id, str) or not case_id.strip():
        raise FactVerificationArgumentError("case_id boş olamaz.")
    if not isinstance(document_id, str) or not document_id.strip():
        raise FactVerificationArgumentError("document_id boş olamaz.")
    if not isinstance(fact_id, str) or not fact_id.strip():
        raise FactVerificationArgumentError("fact_id boş olamaz.")


def _check_argument_shapes(target_state, expected_hash, evidence_document_id, attempt):
    if target_state not in FACT_VERIFICATION_TARGET_STATES:
        raise FactVerificationArgumentError(
            f"target_state, {FACT_VERIFICATION_TARGET_STATES!r} kümesinden biri olmalıdır."
        )
    if not isinstance(expected_hash, str) or not expected_hash.strip():
        raise FactVerificationArgumentError("expected_hash zorunlu, boş olamaz.")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise FactVerificationArgumentError("attempt >= 1 tam sayı olmalıdır.")
    if evidence_document_id is not None and (
        not isinstance(evidence_document_id, str) or not evidence_document_id.strip()
    ):
        raise FactVerificationArgumentError("evidence_document_id verildiyse boş olamaz.")
    if target_state in POSITIVE_TARGET_STATES:
        if evidence_document_id is None or not evidence_document_id.strip():
            raise FactVerificationArgumentError(
                f"target_state={target_state} için evidence_document_id ZORUNLUDUR."
            )


# ----------------------------------------------------------------
# STALE DOWNSTREAM WARNING (kesin sözleşme - §K).
# ----------------------------------------------------------------

_STALE_DOWNSTREAM_FAMILIES = (
    "timeline", "deadline", "issue_spotting", "legal_research", "case_law",
    "evidence", "arguments", "risk_strategy", "drafting", "qa", "case_view",
)

_RERUN_ORDER = (
    "generation.timeline",
    "promotion.timeline",
    "generation.deadline",
    "approval.deadline",
    "generation.issue_spotting",
    "approval.issue_spotting",
    "generation.legal_research",
    "approval.legal_research",
    "generation.case_law",
    "approval.case_law",
    "generation.evidence",
    "approval.evidence",
    "generation.argument",
    "approval.arguments",
    "generation.risk_strategy",
    "approval.risk_strategy",
    "generation.drafting",
    "approval.drafting",
    # ADIM 9 REMEDIATION A: Holiday Calendar Phase B added coordinated
    # qa/case_view publishers. qa reads every canonical through drafting;
    # case_view requires a current canonical qa.json - hence this order.
    "generation.qa",
    "approval.qa",
    "generation.case_view",
    "approval.case_view",
)

# Every stale family now has a coordinated rerun path. The header is kept
# (rendered as `none`) so the CLI block keeps its three-section shape.
_NO_COORDINATED_PATH = ()


def render_stale_downstream_block() -> str:
    lines = ["STALE_DOWNSTREAM:", " ".join(_STALE_DOWNSTREAM_FAMILIES), "", "RERUN_ORDER:"]
    lines.extend(_RERUN_ORDER)
    lines.append("")
    lines.append("NO_COORDINATED_PATH:")
    lines.append(" ".join(_NO_COORDINATED_PATH) if _NO_COORDINATED_PATH else "none")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------
# PREVIEW (salt-okunur).
# ----------------------------------------------------------------


def preview_verification(case_id: str, document_id: str, fact_id: str, *, principal, authz_repository=None):
    """Salt-okunur preview. Sıra: dış 'read' authz HER filesystem
    probundan ÖNCE koşar. `--target-state` almaz, sıfır journal/lock/
    write; `run_mutation`/`conn_factory` ÇAĞRILMAZ."""
    _check_common_identity_args(case_id, document_id, fact_id)

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "read", repository=repository,
        )
        case_root_real = _resolve_case_root_real(resolved_case_id)
        paths = _derive_verified_paths(case_root_real, resolved_case_id, document_id)
        if not paths.canonical_path.is_file():
            raise FactVerificationFactNotFoundError(
                f"Canonical facts.json bulunamadı: {paths.canonical_path}"
            )
        raw = paths.canonical_path.read_bytes()
        extraction = fact_verification.verify_canonical_serialization_form(raw)
        fact = fact_verification.find_fact(extraction, fact_id)
        if fact is None:
            raise FactVerificationFactNotFoundError(f"fact_id={fact_id!r} bulunamadı.")
        allowed = sorted(_allowed_evidence_document_ids(extraction, fact))
        canonical_sha256 = hashlib.sha256(raw).hexdigest()
        return {
            "case_id": resolved_case_id,
            "document_id": document_id,
            "fact_id": fact_id,
            "from_state": fact.get("verification_state"),
            "source_locator_present": fact_verification.source_has_locator(fact.get("source")),
            "canonical_sha256": canonical_sha256,
            "allowed_evidence_documents": allowed,
        }
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(
                f"WARNING: preview_verification authz repository close failed: {close_error!r}"
            )


# ----------------------------------------------------------------
# APPLY (koordine, journal'lı, idempotent mutasyon).
# ----------------------------------------------------------------


@dataclass(frozen=True)
class FactVerificationApplyResult:
    case_id: str
    document_id: str
    fact_id: str
    from_state: str
    target_state: str
    canonical_hash: str | None
    audit_path: Path | None
    journal_id: int
    replayed: bool


_SUCCESS_OUTCOME = "verified_state_changed"
_IDENTITY_PAYLOAD_KEYS = frozenset({"revision_version", "canonical_sha256", "attempt"})
_HEX64 = frozenset("0123456789abcdef")


def _is_sha256_hex(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX64


def _nonblank(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _replay_history_backup_ok(record: dict, *, history_dir_real: Path, document_id: str, fact_id: str) -> bool:
    """Facade-side (independent of the adapter's own copy) history-backup
    binding: `history_backup_path` MUST resolve, containment-verified and
    exact-parent, to a REGULAR file under the verified extractions/
    history directory; real sha256 == `history_backup_sha256` ==
    `canonical_sha256_before`; parsed backup carries `from_state` for the
    SAME document/fact. Never raises past this boundary."""
    try:
        raw_path = record.get("history_backup_path")
        backup_sha = record.get("history_backup_sha256")
        before_sha = record.get("canonical_sha256_before")
        if not _nonblank(raw_path) or not _is_sha256_hex(backup_sha) or backup_sha != before_sha:
            return False
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = history_dir_real / raw_path
        if not os.path.lexists(candidate):
            return False
        resolved = _path_containment.resolve_existing(candidate, root=history_dir_real)
        if resolved.parent != history_dir_real or not resolved.is_file():
            return False
        raw_bytes = resolved.read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != backup_sha:
            return False
        parsed = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(parsed, dict) or parsed.get("source_document_id") != document_id:
            return False
        backup_fact = fact_verification.find_fact(parsed, fact_id)
        return isinstance(backup_fact, dict) and backup_fact.get("verification_state") == record.get("from_state")
    except Exception:
        return False


def _replay_audit_fully_bound(
    record, *, intent, idempotency_key, request_fingerprint, expected_hash, attempt,
    evidence_document_id, secondary_input_hash, document_id, fact_id, observed_post_hash,
    history_dir_real,
) -> bool:
    """FULL, state-independent binding of ONE audit candidate to THIS
    request's own identity/fingerprint and to the journal's stored
    post-hash (F1 remediation - facade-side, written independently of
    `fact_verification_mutation_adapters._full_binding()`; the two never
    share a matcher, so a bug in one cannot mask the other). Everything
    is recomputed; nothing in the audit is trusted on its own. Does NOT
    look at the CURRENT canonical bytes - the caller classifies the
    current state (genuine replay vs state-cycle vs unverifiable)."""
    try:
        if not isinstance(record, dict) or record.get("outcome") != _SUCCESS_OUTCOME:
            return False
        if record.get("mutation_idempotency_key") != idempotency_key:
            return False
        if record.get("mutation_resource_key") != intent.resource_key:
            return False
        if record.get("mutation_actor_ref") != intent.actor_ref:
            return False
        if record.get("action_family") != FACT_VERIFICATION_ACTION_FAMILY:
            return False
        if record.get("target_ref") != intent.target_ref:
            return False
        if record.get("document_id") != document_id or record.get("fact_id") != fact_id:
            return False
        from_state = record.get("from_state")
        if record.get("target_state") != intent.target_state or from_state not in FACT_VERIFICATION_TARGET_STATES:
            return False
        if from_state == intent.target_state:
            return False
        if record.get("evidence_document_id") != evidence_document_id:
            return False
        if record.get("secondary_input_hash") != secondary_input_hash:
            return False
        if record.get("attempt") != attempt or isinstance(record.get("attempt"), bool):
            return False
        identity_payload = record.get("identity_payload")
        if not isinstance(identity_payload, dict) or set(identity_payload) != _IDENTITY_PAYLOAD_KEYS:
            return False
        if identity_payload != compute_identity_payload(expected_hash, attempt):
            return False
        if compute_pre_revision(identity_payload) != intent.pre_revision:
            return False
        before_sha = record.get("canonical_sha256_before")
        after_sha = record.get("canonical_sha256")
        if not _is_sha256_hex(before_sha) or before_sha != expected_hash:
            return False
        if not _is_sha256_hex(after_sha) or after_sha == before_sha:
            return False
        if not observed_post_hash or after_sha != observed_post_hash:
            return False
        # request_fingerprint / idempotency_key recomputed from the AUDIT's
        # own fields through the generic digest - must equal OURS.
        rebuilt = MutationIntent(
            actor_type=intent.actor_type,
            actor_ref=record.get("mutation_actor_ref"),
            resource_key=record.get("mutation_resource_key"),
            action_family=record.get("action_family"),
            target_ref=record.get("target_ref"),
            target_state=record.get("target_state"),
            pre_hash=intent.pre_hash,
            pre_revision=compute_pre_revision(identity_payload),
            secondary_input_hash=record.get("secondary_input_hash"),
        )
        if compute_idempotency_key(rebuilt) != idempotency_key:
            return False
        if compute_request_fingerprint(rebuilt) != request_fingerprint:
            return False
        return _replay_history_backup_ok(
            record, history_dir_real=history_dir_real, document_id=document_id, fact_id=fact_id,
        )
    except Exception:
        return False


def _verify_completed_replay_binding(
    case_id, document_id, fact_id, *, journal_state, journal_id, intent, idempotency_key,
    request_fingerprint, expected_hash, attempt, evidence_document_id, secondary_input_hash,
    observed_post_hash,
):
    """Coordinator says "same identity + same fingerprint, already
    completed". Three fail-closed outcomes (F1/F2 remediation):
      1. exactly ONE fully-bound audit (see `_replay_audit_fully_bound`)
         AND current canonical == stored observed_post_hash AND the
         target fact is in target_state -> GENUINE replay: returns
         (current_sha, audit_path, from_state); writer never runs;
      2. exactly ONE fully-bound audit BUT current canonical == the
         request's declared pre-state (== audit canonical_sha256_before)
         AND the target fact is in the audited from_state -> the fact was
         cycled back: `FactVerificationRevisionCycleConflictError`
         (`--attempt N+1`), zero mutation;
      3. anything else (zero/multiple bound audits, any tamper, corrupt
         sibling, missing history dir/backup, unclassifiable canonical) ->
         `FactVerificationAuditBindingVerificationFailedError`.
    A tampered audit is NEVER classified as a cycle (1/2 require the
    full binding first)."""
    def fail(reason):
        raise FactVerificationAuditBindingVerificationFailedError(
            journal_id=journal_id, idempotency_key=idempotency_key, reason=reason,
        )

    if journal_state != "completed":
        fail(f"bu corroboration yalnız 'completed' satır için tanımlıdır (state={journal_state!r})")

    try:
        case_root_real = _resolve_case_root_real(case_id)
        paths = _derive_verified_paths(case_root_real, case_id, document_id)
    except FactVerificationNestedPathContainmentError as error:
        fail(f"replay corroboration sırasında containment hatası: {error}")
        return  # unreachable, keeps type-checkers happy

    if not paths.canonical_path.is_file():
        fail("canonical artefakt şu an mevcut değil")
    raw = paths.canonical_path.read_bytes()
    current_sha = hashlib.sha256(raw).hexdigest()
    try:
        extraction = fact_verification.verify_canonical_serialization_form(raw)
    except Exception as error:
        fail(f"canonical serialization doğrulanamadı: {error}")
        return
    fact = fact_verification.find_fact(extraction, fact_id)
    if fact is None:
        fail("hedef fact güncel canonical içinde bulunamadı")
    current_state = fact.get("verification_state")

    history_dir_real = None
    try:
        if os.path.lexists(paths.history_dir):
            resolved_history = _path_containment.resolve_existing(paths.history_dir, root=case_root_real)
            if resolved_history.is_dir():
                history_dir_real = resolved_history
    except _path_containment.PathContainmentError:
        history_dir_real = None
    if history_dir_real is None:
        fail("history dizini mevcut değil/containment doğrulamasından geçemedi - backup bağı kurulamaz")

    entries = _scan_verification_audits(case_root_real, paths.reviews_dir)
    if any(record is None for _path, record in entries):
        fail("reviews dizininde parse edilemeyen audit dosyası var - içerik-bağlama güvenle yapılamaz")
    bound = [
        (path, record) for path, record in entries
        if _replay_audit_fully_bound(
            record, intent=intent, idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint, expected_hash=expected_hash, attempt=attempt,
            evidence_document_id=evidence_document_id, secondary_input_hash=secondary_input_hash,
            document_id=document_id, fact_id=fact_id, observed_post_hash=observed_post_hash,
            history_dir_real=history_dir_real,
        )
    ]
    if len(bound) != 1:
        fail(
            f"full-binding eşleşen success audit sayısı {len(bound)} (tam 1 olmalı) - audit/backup "
            "tampered, eksik veya çoğaltılmış; bu completed satır bağımsızca doğrulanamadı"
        )
    matched_path, matched_record = bound[0]
    # (1) genuine replay
    if current_sha == observed_post_hash and current_state == intent.target_state:
        return current_sha, matched_path, matched_record.get("from_state")
    # (2) sound audit, canonical cycled back to the request's own pre-state
    if (
        current_sha == expected_hash
        and current_sha == matched_record.get("canonical_sha256_before")
        and current_state == matched_record.get("from_state")
    ):
        raise FactVerificationRevisionCycleConflictError(journal_id=journal_id)
    # (3) neither the completed post-state nor the declared pre-state
    fail(
        "güncel canonical, tamamlanmış satırın post-state'i DEĞİL ve isteğin beyan ettiği pre-state "
        "de DEĞİL - durum sınıflandırılamadı; insan reconciliation'ı gerekir"
    )


def apply_verification_mutation(
    case_id: str,
    document_id: str,
    fact_id: str,
    expected_hash: str,
    target_state: str,
    *,
    evidence_document_id=None,
    attempt: int = 1,
    principal,
    authz_repository=None,
    conn_factory=None,
) -> FactVerificationApplyResult:
    """SIRA: (1) argüman şekilleri (saf, I/O'suz); (2) DIŞ
    authorize_case_access('mutate'); (3) pre-lock containment + fact
    okuma + evidence/locator kontrolleri (bunlar bu writer'ın asla
    değiştirmediği alanlara bağlı olduğundan replay-güvenlidir) +
    composite snapshot; (4) conn + case lock; (5) run_mutation: İÇ
    otoriter authz -> journal gate -> idempotency -> precondition
    (SIFIRDAN kilit-altı yeniden doğrulama) -> writer; (6) replay'de tam
    corroboration; (7) maskelemeyen temizlik.

    ÖNEMLİ TASARIM NOTU (self-transition + staleness kontrolünün
    KASITLI olarak precondition_callback'e ERTELENMESİ): identity
    (`pre_revision`) yalnız operatörün DEKLARE ETTİĞİ `expected_hash` +
    `attempt`'ten türetilir - freshly-read disk hash'inden ASLA (bkz.
    `compute_identity_payload` çağrısı, `expected_hash` argümanı ile).
    Bu, promotion facade'inin `pre_revision=expected_hash` deseninin
    doğrudan devamıdır. Eğer self-transition/staleness kontrolleri
    BURADA (pre-lock, run_mutation'dan ÖNCE) yapılsaydı, gerçek bir
    safe-replay denemesi (aynı H + aynı attempt + aynı target_state +
    aynı evidence) - ilk deneme zaten BAŞARIYLA tamamlanıp canonical'ı
    mutasyona uğrattıktan SONRA - bu pre-lock kontrolünde YANLIŞLIKLA
    "self-transition" (çünkü fresh from_state artık target_state'e eşit)
    veya "stale" (çünkü fresh hash artık expected_hash'ten farklı) olarak
    reddedilir ve coordinator'ın kendi idempotency-lookup'ına (safe
    replay'i TANIYAN tek yer) ASLA ULAŞAMAZDI. Bu yüzden ikisi de
    `precondition_callback`'e taşınmıştır - `run_mutation()` bunu YALNIZ
    idempotency lookup'ın GERÇEK bir replay bulamadığı durumda çağırır;
    genuine bir safe replay bu kontrollerin HİÇBİRİNE asla uğramaz."""
    _check_common_identity_args(case_id, document_id, fact_id)
    _check_argument_shapes(target_state, expected_hash, evidence_document_id, attempt)

    repository, close_repository = _resolve_authz_repository(authz_repository)
    try:
        outer_resolved_case_id = _authz.authorize_case_access(
            principal, case_id, "mutate", repository=repository,
        )
        resource_key = _mutation_lock.case_resource_key(outer_resolved_case_id)

        pre_case_root = _resolve_case_root_real(outer_resolved_case_id)
        pre_paths = _derive_verified_paths(pre_case_root, outer_resolved_case_id, document_id)
        if not pre_paths.canonical_path.is_file():
            raise FactVerificationFactNotFoundError(
                f"Canonical facts.json bulunamadı: {pre_paths.canonical_path}"
            )
        raw_pre = pre_paths.canonical_path.read_bytes()
        extraction_pre = fact_verification.verify_canonical_serialization_form(raw_pre)
        fact_pre = fact_verification.find_fact(extraction_pre, fact_id)
        if fact_pre is None:
            raise FactVerificationFactNotFoundError(f"fact_id={fact_id!r} bulunamadı.")

        # `canonical_sha256_pre` yalnız (a) pre-lock/kilit-altı DRIFT
        # tespiti için composite `pre_hash` baseline'ı ve (b) evidence-
        # ile-locator kontrolleri için kullanılır - kimlik (`pre_revision`)
        # İÇİN DEĞİL (bkz. yukarıdaki tasarım notu). Self-transition ve
        # `expected_hash` staleness kontrolleri BİLİNÇLİ olarak
        # `precondition_callback`'e ERTELENMİŞTİR.
        canonical_sha256_pre = hashlib.sha256(raw_pre).hexdigest()

        allowed_evidence = _allowed_evidence_document_ids(extraction_pre, fact_pre)
        if evidence_document_id is not None and evidence_document_id not in allowed_evidence:
            raise FactVerificationEvidenceNotAllowedError(
                f"evidence_document_id={evidence_document_id!r} izinli kümede değil "
                f"({sorted(allowed_evidence)!r})."
            )
        evidence_document_sha256_pre = None
        if evidence_document_id is not None:
            evidence_document_sha256_pre = _resolve_and_check_evidence_document(
                pre_case_root, outer_resolved_case_id, evidence_document_id,
            )

        if target_state in POSITIVE_TARGET_STATES and not fact_verification.source_has_locator(
            fact_pre.get("source")
        ):
            raise FactVerificationMissingLocatorError(
                f"fact_id={fact_id!r} kaynak locator taşımıyor; target_state={target_state} "
                "için zorunlu."
            )

        source_locator_present = fact_verification.source_has_locator(fact_pre.get("source"))
        source_locator_sha256 = hashlib.sha256(
            json.dumps(
                fact_pre.get("source"), sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()

        audit_manifest_digest_pre = _compute_audit_manifest_digest(pre_case_root, pre_paths.reviews_dir)
        pre_hash = _compute_pre_hash(canonical_sha256_pre, audit_manifest_digest_pre)
        # KİMLİK yalnız operatörün DEKLARE ETTİĞİ expected_hash'ten -
        # freshly-read canonical_sha256_pre'den DEĞİL (bkz. fonksiyonun
        # kendi docstring'indeki tasarım notu).
        identity_payload = compute_identity_payload(expected_hash, attempt)
        pre_revision = compute_pre_revision(identity_payload)
        secondary_input_hash = _compute_secondary_input_hash(evidence_document_id)

        target_ref = f"fact.{document_id}.{fact_id}.verification"

        intent = MutationIntent(
            actor_type="iam_user",
            actor_ref=str(principal.user_id),
            resource_key=resource_key,
            action_family=FACT_VERIFICATION_ACTION_FAMILY,
            target_ref=target_ref,
            target_state=target_state,
            pre_hash=pre_hash,
            pre_revision=pre_revision,
            secondary_input_hash=secondary_input_hash,
        )
        idempotency_key_for_audit = compute_idempotency_key(intent)

        under_lock_box = {}
        writer_outcome_box = {}

        def authz_callback() -> None:
            inner_resolved_case_id = _authz.authorize_case_access(
                principal, case_id, "mutate", repository=repository,
            )
            if inner_resolved_case_id != outer_resolved_case_id:
                raise FactVerificationResolvedCaseIdMismatchError(
                    f"outer authz {outer_resolved_case_id!r} çözdü, inner authz "
                    f"{inner_resolved_case_id!r} - farklı case'i tarif ediyor; reddedildi."
                )

        def precondition_callback() -> None:
            ul_case_root = _resolve_case_root_real(outer_resolved_case_id)
            ul_paths = _derive_verified_paths(ul_case_root, outer_resolved_case_id, document_id)
            if ul_paths.identity != pre_paths.identity:
                raise FactVerificationPreconditionRaceDetectedError(
                    "Bu verification isteği case kilidini beklerken ilgili dizin/dosyaların "
                    "çözümlenmiş (gerçek) konumu DEĞİŞTİ. Onay iptal edildi, HİÇBİR değişiklik "
                    "yapılmadı."
                )
            if not ul_paths.canonical_path.is_file():
                raise FactVerificationFactNotFoundError(
                    f"Canonical facts.json bulunamadı: {ul_paths.canonical_path}"
                )
            raw_ul = ul_paths.canonical_path.read_bytes()
            extraction_ul = fact_verification.verify_canonical_serialization_form(raw_ul)
            fact_ul = fact_verification.find_fact(extraction_ul, fact_id)
            if fact_ul is None:
                raise FactVerificationFactNotFoundError(f"fact_id={fact_id!r} bulunamadı.")
            canonical_sha256_ul = hashlib.sha256(raw_ul).hexdigest()
            # STALENESS - BİLİNÇLİ olarak burada, precondition_callback
            # içinde: `run_mutation()` bu callback'i YALNIZ idempotency
            # lookup'ın bunu bir safe-replay OLARAK TANIMADIĞI durumda
            # çağırır - genuine bir replay bu kontrole ASLA uğramaz
            # (bkz. fonksiyonun kendi docstring'i).
            if canonical_sha256_ul != expected_hash:
                raise StaleViewError(
                    "Preview alındıktan sonra (veya case kilidini beklerken) canonical facts.json "
                    f"DEĞİŞTİ (beklenen: {expected_hash}, şimdiki: {canonical_sha256_ul}). Onay "
                    "iptal edildi."
                )
            # SELF-TRANSITION - AYNI gerekçeyle burada (bkz. docstring).
            # `canonical_sha256_ul == expected_hash` az önce KANITLANDI,
            # bu yüzden `from_state_ul` operatörün preview'da gördüğü
            # GERÇEK durumdur - fresh-read tesadüfen "artık aynı" hâle
            # gelmiş DEĞİLDİR.
            from_state_ul = fact_ul.get("verification_state")
            if from_state_ul == target_state:
                raise FactVerificationNoOpError(
                    f"Fact zaten {target_state!r} durumunda - self-transition reddedildi "
                    "(sıfır mutasyon, sıfır journal satırı)."
                )
            audit_manifest_digest_ul = _compute_audit_manifest_digest(ul_case_root, ul_paths.reviews_dir)
            pre_hash_ul = _compute_pre_hash(canonical_sha256_ul, audit_manifest_digest_ul)
            if pre_hash_ul != pre_hash:
                raise FactVerificationPreconditionRaceDetectedError(
                    "Case kilidini beklerken audit-manifest durumu DEĞİŞTİ. Onay iptal edildi, "
                    "HİÇBİR değişiklik yapılmadı."
                )
            if evidence_document_id is not None:
                evidence_sha_ul = _resolve_and_check_evidence_document(
                    ul_case_root, outer_resolved_case_id, evidence_document_id,
                )
                if evidence_sha_ul != evidence_document_sha256_pre:
                    raise FactVerificationPreconditionRaceDetectedError(
                        "Case kilidini beklerken evidence belgesi DEĞİŞTİ. Onay iptal edildi, "
                        "HİÇBİR değişiklik yapılmadı."
                    )
            under_lock_box["paths"] = ul_paths
            under_lock_box["case_root"] = ul_case_root
            under_lock_box["from_state"] = from_state_ul

        def writer_callback() -> _mutation_coordinator.WriterResult:
            ul = under_lock_box["paths"]
            writer_result = fact_verification.apply_verification(
                outer_resolved_case_id, document_id, fact_id, under_lock_box["from_state"], target_state,
                evidence_document_id=evidence_document_id,
                evidence_document_sha256=evidence_document_sha256_pre,
                source_locator_present=source_locator_present,
                source_locator_sha256=source_locator_sha256,
                identity_payload=identity_payload,
                attempt=attempt,
                secondary_input_hash=secondary_input_hash,
                verified_paths={
                    "extractions_dir": ul.extractions_dir,
                    "canonical_path": ul.canonical_path,
                    "history_dir": ul.history_dir,
                    "reviews_dir": ul.reviews_dir,
                },
                mutation_idempotency_key=idempotency_key_for_audit,
                mutation_resource_key=resource_key,
                mutation_actor_ref=str(principal.user_id),
            )
            writer_outcome_box["audit_path"] = writer_result["audit_path"]
            return _mutation_coordinator.WriterResult(
                observed_post_hash=writer_result["canonical_sha256"], result=None,
            )

        conn = (conn_factory or _default_conn_factory)()
        advisory_lock_id = _mutation_lock.acquire_case_lock_session(conn, outer_resolved_case_id)
        try:
            try:
                outcome = _mutation_coordinator.run_mutation(
                    conn, intent,
                    actor_user_id=principal.user_id,
                    authz_callback=authz_callback,
                    precondition_callback=precondition_callback,
                    writer_callback=writer_callback,
                )
            except _mutation_coordinator.IdempotencyConflictError as conflict_error:
                # F2.2: same identity (same actor + canonical hash + attempt),
                # DIFFERENT fingerprint (target_state/evidence). The generic
                # refusal is kept intact (subclass, zero mutation, nothing
                # accepted) but made fact-verification-specific and
                # actionable (`--attempt N+1` for a deliberate state-cycle).
                raise FactVerificationIdentityConflictError() from conflict_error

            if outcome.replayed:
                verified_canonical_hash, audit_path, replay_from_state = _verify_completed_replay_binding(
                    outer_resolved_case_id, document_id, fact_id,
                    journal_state=outcome.state, journal_id=outcome.journal_id,
                    intent=intent, idempotency_key=idempotency_key_for_audit,
                    request_fingerprint=compute_request_fingerprint(intent),
                    expected_hash=expected_hash, attempt=attempt,
                    evidence_document_id=evidence_document_id,
                    secondary_input_hash=secondary_input_hash,
                    observed_post_hash=outcome.observed_post_hash,
                )
                result_from_state = replay_from_state
            else:
                verified_canonical_hash = outcome.observed_post_hash
                audit_path = writer_outcome_box.get("audit_path")
                result_from_state = under_lock_box["from_state"]

            return FactVerificationApplyResult(
                case_id=outer_resolved_case_id, document_id=document_id, fact_id=fact_id,
                from_state=result_from_state, target_state=target_state,
                canonical_hash=verified_canonical_hash, audit_path=audit_path,
                journal_id=outcome.journal_id, replayed=outcome.replayed,
            )
        finally:
            try:
                try:
                    released = _mutation_lock.release_lock_session(conn, advisory_lock_id)
                except Exception as release_error:
                    _log_critical_safely(
                        f"CRITICAL: apply_verification_mutation() lock release RAISED for "
                        f"resource_key={resource_key!r} (advisory_lock_id={advisory_lock_id!r}): "
                        f"{release_error!r} - outcome unchanged, investigate out of band"
                    )
                else:
                    if not released:
                        _log_critical_safely(
                            f"CRITICAL: apply_verification_mutation() release_lock_session "
                            f"returned False for resource_key={resource_key!r} "
                            f"(advisory_lock_id={advisory_lock_id!r}) - outcome unchanged, "
                            "investigate out of band"
                        )
            finally:
                try:
                    conn.close()
                except Exception as close_error:
                    _log_critical_safely(
                        f"CRITICAL: apply_verification_mutation() journal connection close "
                        f"failed: {close_error!r} - outcome unchanged"
                    )
    finally:
        try:
            close_repository()
        except Exception as close_error:
            _log_critical_safely(
                f"WARNING: apply_verification_mutation authz repository close failed: {close_error!r}"
            )
